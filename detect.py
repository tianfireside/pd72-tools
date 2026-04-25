"""
Scan an OCR'd PDF and emit a draft TOML bookmark config.

Usage: python detect.py input.pdf [output.toml]

Output defaults to input.bookmarks.draft.toml in the same folder.

Strategy:
- The index page is the source of truth for the top-level structure: how many
  tabs there are, what each is, and what order they're in. We parse it.
- For each indexed entry, find its start page in the PDF:
    - Notice of Application: match to detected NOA header page.
    - Affidavit #N of X: match to detected affidavit page with same affiant+number.
    - Anything else (e.g. a standalone document): keyword-search the gap between
      the previous and next matched tabs.
- For affidavit tabs, parse the body for "Exhibit X" references — that list
  is the canonical exhibit inventory. Pair each reference with an exhibit
  cover sheet (or a nested-affidavit page) found in the post-body window.
- Detected affidavits NOT matched to any index entry = nested exhibits of
  another affidavit. They count as exhibit slots in their parent's window
  and are not emitted as top-level bookmarks.

Always review the draft before passing to bookmark.py.
"""

import os
import re
import sys
from pathlib import Path

from pypdf import PdfReader


# ---- patterns ----

# Form headers (the "[Rule ..." prefix distinguishes the form heading from
# the words "AFFIDAVIT" / "NOTICE OF APPLICATION" appearing in body text).
RE_AFFIDAVIT_HEADER = re.compile(r"\bAFFIDAVIT\s*\[Rule", re.IGNORECASE)
RE_NOA_HEADER = re.compile(r"NOTICE\s+OF\s+APPLICATION\s*\[?\s*Rule", re.IGNORECASE)

# BC standard exhibit stamp. OCR sometimes runs the words together
# ("ThisisExhibit"), so allow zero-or-more whitespace between them.
RE_EXHIBIT_COVER = re.compile(r"this\s*is\s*exhibit", re.IGNORECASE)

# Index page header. The "TAB DOCUMENT DATE" column heading is highly
# distinctive and rarely appears outside an actual index.
RE_INDEX_HEADER = re.compile(
    r"INDEX[\s\S]{0,100}TAB\s+DOCUMENT\s+DATE",
    re.IGNORECASE,
)

# A row in the index. Tab number, description, then a date in some format.
RE_INDEX_ROW = re.compile(
    r"^\s*(?P<tab>\d+)\s+"
    r"(?P<desc>.+?)"
    r"\s+(?:Filed|Made|Sworn|Affirmed)?\s*"
    r"(?P<date>\d{1,2}[-/][A-Za-z]+[-/]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s*$",
    re.MULTILINE,
)

# Inside an index row description, identify the entry kind.
RE_DESC_NOA = re.compile(r"Notice\s+of\s+Application", re.IGNORECASE)
RE_DESC_AFFIDAVIT = re.compile(
    r"[Aa]ffidavit\s*#?\s*(\d+)\s+of\s+(.+?)\s*$",
)

# Signature line on an affidavit. OCR mangles "BEFORE ME" frequently.
RE_SIGNATURE = re.compile(
    r"(?:AFFIRMED|SWORN)\s+BEFO\w*\s*ME"
    r"|A\s+Commissioner\s+for\s+(?:T|t)aking\s+Affidavits",
    re.IGNORECASE,
)

# Affiant name + ordinal: "1st affidavit of WING CHEONG FONG" or
# "2nd Affidavit of Karin Wang". OCR is messy:
#   - "affidavit" -> "aflldavit" (l/i confusion), match \w*davit
#   - "2nd" -> "2\"*^" (garbled ordinal), allow non-letter junk between
#   - spaces collapse: "affidavitofWING" / "Affidavitof Karin"
RE_AFFIANT = re.compile(
    r"(?P<num>\d+)(?:st|nd|rd|th)?[^A-Za-z]{0,10}"
    r"\w*[Dd]avit\s*"
    r"(?:of|Of|OF)\s*"
    r"(?P<name>[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){1,4})",
)

# Exhibit references inside an affidavit body.
RE_EXHIBIT_REF = re.compile(
    r"Exhibit"
    r"[\s\"\u201c\u201d\u2018\u2019']*"
    r"([A-Z]+)"
    r"[\s\"\u201c\u201d\u2018\u2019']*"
    r"([^.]{0,150})",
    re.IGNORECASE,
)


# ---- helpers ----


def letter_value(s: str) -> int:
    """A=1, Z=26, AA=27, AZ=52, BA=53. Spreadsheet-column ordering."""
    n = 0
    for c in s.upper():
        n = n * 26 + (ord(c) - 64)
    return n


def normalize_name(raw: str) -> str:
    """Convert OCR'd 'WING CHEONG FONG' to 'Wing Cheong Fong'."""
    return " ".join(w.capitalize() for w in raw.split())


def clean_description(tail: str) -> str:
    """Tidy the captured tail of an Exhibit reference into a usable title fragment."""
    s = " ".join(tail.split())
    s = re.sub(
        r"^(?:is|are|hereto|attached|stamped|marked|being|to|a|an|the|copy|copies)\s+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.split(r"AFFIRMED|SWORN|Commissioner", s, maxsplit=1, flags=re.IGNORECASE)[0]
    s = s.strip(" ,;:-")
    return s[:120]


def toml_str(s: str) -> str:
    """Escape a Python string into a TOML basic-string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---- classification ----


def classify_pages(pages: list[str]) -> list[dict]:
    """Return a list of page metadata dicts (one per page, 1-indexed in 'page')."""
    info = []
    for i, txt in enumerate(pages):
        d = {"page": i + 1, "type": None, "text": txt}
        # Order matters: index check first (it has TAB DOCUMENT DATE which is
        # very specific). Then form headers. Then exhibit cover sheets.
        if RE_INDEX_HEADER.search(txt):
            d["type"] = "index"
        elif RE_AFFIDAVIT_HEADER.search(txt):
            d["type"] = "affidavit"
            m = RE_AFFIANT.search(txt)
            if m:
                d["affiant"] = normalize_name(m.group("name"))
                d["number"] = int(m.group("num"))
        elif RE_NOA_HEADER.search(txt):
            d["type"] = "noa"
        elif RE_EXHIBIT_COVER.search(txt):
            d["type"] = "exhibit_cover"
        if RE_SIGNATURE.search(txt):
            d["has_signature"] = True
        info.append(d)
    return info


# ---- index parsing ----


def parse_index(text: str) -> list[dict]:
    """Parse an index page's text into a list of entries (one per tab)."""
    entries = []
    for m in RE_INDEX_ROW.finditer(text):
        tab = int(m.group("tab"))
        desc = m.group("desc").strip()
        entry: dict = {"tab": tab, "desc": desc, "title": desc}

        if RE_DESC_NOA.search(desc):
            entry["kind"] = "noa"
        elif (am := RE_DESC_AFFIDAVIT.search(desc)):
            entry["kind"] = "affidavit"
            entry["number"] = int(am.group(1))
            entry["affiant"] = am.group(2).strip()
        else:
            entry["kind"] = "other"

        entries.append(entry)
    # Tab numbers should be sequential; sort by tab to be safe.
    entries.sort(key=lambda e: e["tab"])
    return entries


# ---- matching index to detected pages ----


def find_other_tab_page(
    description: str,
    pages: list[str],
    pages_info: list[dict],
    gap_start: int,
    gap_end: int,
) -> int | None:
    """Find best-match page in [gap_start, gap_end] for an index description.

    Used for entries that aren't NOA or affidavit (e.g. a standalone "Death
    Certificate" tab). Scores each page by how many distinctive keywords from
    the description appear on it.

    Pages classified as 'exhibit_cover' are skipped: a standalone tab is its
    own document, not an exhibit. Without this guard the scorer happily picks
    e.g. an affidavit's Death Cert exhibit cover over the real standalone
    Death Cert tab a few pages later.

    Tie-breaks toward later pages — a standalone tab usually sits right
    before the next tab, not within the previous tab's exhibits.
    """
    stop_words = {
        "with", "this", "that", "from", "have", "been", "were", "and",
        "the", "for", "of", "in", "on", "at", "to", "by",
    }
    keywords = {
        w.lower()
        for w in re.findall(r"\b\w+\b", description)
        if len(w) > 3 and w.lower() not in stop_words
    }
    if not keywords:
        return None
    threshold = max(2, len(keywords) // 3)
    candidates = []
    for p in range(max(1, gap_start), min(len(pages), gap_end) + 1):
        if pages_info[p - 1]["type"] == "exhibit_cover":
            continue
        text = pages[p - 1].lower()
        score = sum(1 for k in keywords if k in text)
        if score >= threshold:
            candidates.append((p, score))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[1], x[0]))
    return candidates[-1][0]


def match_index_to_pages(
    entries: list[dict],
    pages: list[str],
    pages_info: list[dict],
) -> set[int]:
    """For each index entry, set entry['start_page']. Return the set of detected
    affidavit pages that did NOT match any index entry — those are nested."""
    detected_noa = [p["page"] for p in pages_info if p["type"] == "noa"]
    detected_affs = [p for p in pages_info if p["type"] == "affidavit"]
    used_noa: set[int] = set()
    used_aff: set[int] = set()

    # Pass 1: NOA + affidavit (these have strong signals)
    for entry in entries:
        if entry["kind"] == "noa":
            for p in detected_noa:
                if p not in used_noa:
                    entry["start_page"] = p
                    used_noa.add(p)
                    break
            else:
                entry["start_page"] = None
        elif entry["kind"] == "affidavit":
            target_name = entry["affiant"].lower()
            target_num = entry["number"]
            entry["start_page"] = None
            for ap in detected_affs:
                if ap["page"] in used_aff:
                    continue
                if ap.get("number") != target_num:
                    continue
                if not ap.get("affiant"):
                    continue
                if ap["affiant"].lower() == target_name:
                    entry["start_page"] = ap["page"]
                    used_aff.add(ap["page"])
                    break

    # Pass 2: 'other' entries — search the gap between matched neighbours
    for i, entry in enumerate(entries):
        if entry["kind"] != "other":
            continue
        prev_page = 0
        for j in range(i - 1, -1, -1):
            if entries[j].get("start_page"):
                prev_page = entries[j]["start_page"]
                break
        next_page = len(pages) + 1
        for j in range(i + 1, len(entries)):
            if entries[j].get("start_page"):
                next_page = entries[j]["start_page"]
                break
        entry["start_page"] = find_other_tab_page(
            entry["desc"], pages, pages_info, prev_page + 1, next_page - 1
        )

    # Compute end_page for each entry from the next entry's start_page
    for i, entry in enumerate(entries):
        if entry.get("start_page") is None:
            entry["end_page"] = None
            continue
        next_start = None
        for j in range(i + 1, len(entries)):
            if entries[j].get("start_page"):
                next_start = entries[j]["start_page"]
                break
        entry["end_page"] = (next_start - 1) if next_start else len(pages)

    # For any entry we couldn't locate, attach a hint range (gap between
    # matched neighbours) so the interactive prompt can tell the user where
    # to look in the PDF.
    for i, entry in enumerate(entries):
        if entry.get("start_page") is not None:
            continue
        prev_page = 0
        for j in range(i - 1, -1, -1):
            if entries[j].get("start_page"):
                prev_page = entries[j]["start_page"]
                break
        next_page = len(pages) + 1
        for j in range(i + 1, len(entries)):
            if entries[j].get("start_page"):
                next_page = entries[j]["start_page"]
                break
        entry["_hint_lo"] = prev_page + 1
        entry["_hint_hi"] = next_page - 1

    nested = {ap["page"] for ap in detected_affs if ap["page"] not in used_aff}
    return nested


# ---- per-affidavit body / exhibit work ----


def find_body_end(pages_info: list[dict], start: int, end: int) -> int:
    """Last page of affidavit body. Body ends at the signature page, or one
    page before the first exhibit cover, whichever comes first."""
    for p in range(start, end + 1):
        info = pages_info[p - 1]
        if info["type"] == "exhibit_cover" and p > start:
            return p - 1
        if info.get("has_signature") and p > start:
            return p
    return end


def parse_body_exhibits(body_text: str) -> list[dict]:
    """Ordered list of unique exhibits referenced in body text."""
    seen: dict[str, dict] = {}
    for m in RE_EXHIBIT_REF.finditer(body_text):
        letter = m.group(1).upper()
        desc = clean_description(m.group(2))
        if letter not in seen:
            seen[letter] = {"letter": letter, "desc": desc}
        elif not seen[letter]["desc"] and desc:
            seen[letter]["desc"] = desc
    return sorted(seen.values(), key=lambda e: letter_value(e["letter"]))


def find_exhibit_slots(
    pages: list[str],
    pages_info: list[dict],
    body_end: int,
    section_end: int,
    nested_pages: set[int],
    n_needed: int,
) -> list[dict]:
    """Find up to n_needed exhibit anchor pages in the window.

    A slot is either a BC exhibit cover sheet or a nested-affidavit start
    page. The body is the source of truth for how many exhibits exist
    (n_needed) — we stop once we have that many.

    When we hit a nested affidavit it counts as one slot, but its own
    internal exhibit covers must NOT be mistaken for the parent's slots.
    We peek at the nested affidavit's body to count its exhibits, then
    skip that many cover pages before resuming the search.
    """
    slots: list[dict] = []
    p = body_end + 1
    while p <= section_end and len(slots) < n_needed:
        if p in nested_pages:
            slots.append({"page": p, "kind": "nested"})
            # Walk the nested affidavit's body until its first exhibit cover.
            q = p + 1
            while q <= section_end and pages_info[q - 1]["type"] != "exhibit_cover":
                q += 1
            nested_body_text = "\n".join(pages[i - 1] for i in range(p, q))
            n_skip = len(parse_body_exhibits(nested_body_text))
            # Skip that many cover pages (the nested affidavit's own exhibits).
            skipped = 0
            while q <= section_end and skipped < n_skip:
                if pages_info[q - 1]["type"] == "exhibit_cover":
                    skipped += 1
                q += 1
            p = q
            continue
        if pages_info[p - 1]["type"] == "exhibit_cover":
            slots.append({"page": p, "kind": "cover"})
        p += 1
    return slots


def build_affidavit_exhibits(
    entry: dict,
    pages: list[str],
    pages_info: list[dict],
    nested_pages: set[int],
    warnings: list[str],
) -> list[dict]:
    """Parse the affidavit body and pair its exhibit references with slots."""
    label = f"Tab {entry['tab']} {entry['title']}"
    body_end = find_body_end(pages_info, entry["start_page"], entry["end_page"])
    body_text = "\n".join(
        pages[p - 1] for p in range(entry["start_page"], body_end + 1)
    )
    body_exhibits = parse_body_exhibits(body_text)
    slots = find_exhibit_slots(
        pages, pages_info, body_end, entry["end_page"], nested_pages, len(body_exhibits)
    )

    exhibits = []
    for i, ref in enumerate(body_exhibits):
        ex_title = f"Exhibit {ref['letter']}"
        if ref["desc"]:
            ex_title += f" - {ref['desc']}"
        slot = slots[i] if i < len(slots) else None
        if slot is None:
            warnings.append(
                f"{label}: body lists Exhibit {ref['letter']} but no slot found in "
                f"pages {body_end + 1}-{entry['end_page']}; needs manual page"
            )
            exhibits.append({
                "title": ex_title,
                "page": None,
                "_hint_lo": body_end + 1,
                "_hint_hi": entry["end_page"],
                "_kind": f"Exhibit {ref['letter']}",
                "_parent": label,
            })
            continue
        exhibits.append({"title": ex_title, "page": slot["page"]})
    return exhibits


# ---- main ----


def detect(pdf_path: Path) -> tuple[list[dict], list[str]]:
    reader = PdfReader(str(pdf_path))
    pages = [(p.extract_text() or "") for p in reader.pages]
    pages_info = classify_pages(pages)
    warnings: list[str] = []

    index_pages = [p for p in pages_info if p["type"] == "index"]
    if not index_pages:
        warnings.append(
            "No index page detected. detect.py needs an index to anchor the top-level "
            "structure. Add one (PD-72 requires it anyway), or write the TOML by hand."
        )
        return [], warnings

    index_text = pages[index_pages[0]["page"] - 1]
    entries = parse_index(index_text)
    if not entries:
        warnings.append(
            f"Index page found at p{index_pages[0]['page']} but no rows parsed. "
            f"Check the index format; expected 'TAB DOCUMENT DATE' table layout."
        )
        return [], warnings

    nested_pages = match_index_to_pages(entries, pages, pages_info)

    bookmarks = []
    for entry in entries:
        label = f"Tab {entry['tab']} {entry['title']}"
        if entry.get("start_page") is None:
            warnings.append(f"{label}: could not locate start page in PDF; needs manual fill-in")
            bookmarks.append({
                "title": entry["title"],
                "page": None,
                "tab": entry["tab"],
                "_hint_lo": entry.get("_hint_lo"),
                "_hint_hi": entry.get("_hint_hi"),
                "_kind": f"Tab {entry['tab']}",
            })
            continue

        bookmark = {
            "title": entry["title"],
            "page": entry["start_page"],
            "tab": entry["tab"],
        }
        if entry["kind"] == "affidavit":
            bookmark["exhibit"] = build_affidavit_exhibits(
                entry, pages, pages_info, nested_pages, warnings
            )
        bookmarks.append(bookmark)

    return bookmarks, warnings


def emit_toml(
    bookmarks: list[dict],
    warnings: list[str],
    pdf_path: Path,
    draft: bool = True,
) -> str:
    """Render bookmarks to TOML.

    draft=True: include warnings header and comment-out any unresolved entries
    so a human can fill them in. Used by --batch mode.

    draft=False: clean output for bookmark.py to consume directly. Caller is
    responsible for ensuring every entry has a page (interactive mode prompts
    for or drops anything missing).
    """
    header = (
        f"# Draft bookmarks for {pdf_path.name}\n"
        f"# Generated by detect.py. REVIEW BEFORE PASSING TO bookmark.py.\n"
        if draft
        else f"# Bookmarks for {pdf_path.name}\n# Generated by detect.py.\n"
    )
    lines = [header.rstrip(), ""]

    if draft and warnings:
        lines.append("# WARNINGS:")
        for w in warnings:
            lines.append(f"#   - {w}")
        lines.append("")

    for b in bookmarks:
        if b.get("tab") is not None:
            lines.append(f"# Tab {b['tab']}")
        if b["page"] is None:
            lines.append("# [[bookmark]]")
            lines.append(f"# title = {toml_str(b['title'])}")
            lines.append("# page = ?    # COULD NOT AUTO-DETECT - fill in manually then uncomment")
            lines.append("")
            continue
        lines.append("[[bookmark]]")
        lines.append(f"title = {toml_str(b['title'])}")
        lines.append(f"page = {b['page']}")
        lines.append("")
        for ex in b.get("exhibit", []):
            if ex["page"] is None:
                lines.append("  # [[bookmark.exhibit]]")
                lines.append(f"  # title = {toml_str(ex['title'])}")
                lines.append("  # page = ?    # COULD NOT AUTO-DETECT - fill in manually then uncomment")
                lines.append("")
                continue
            lines.append("  [[bookmark.exhibit]]")
            lines.append(f"  title = {toml_str(ex['title'])}")
            lines.append(f"  page = {ex['page']}")
            lines.append("")

    return "\n".join(lines)


# ---- interactive resolution ----


def collect_unknowns(bookmarks: list[dict]) -> list[dict]:
    """Walk the bookmark tree and gather every entry still missing a page."""
    unknowns: list[dict] = []
    for b in bookmarks:
        if b.get("page") is None:
            unknowns.append({
                "ref": b,
                "kind": b.get("_kind", "Tab"),
                "parent": None,
                "title": b["title"],
                "hint_lo": b.get("_hint_lo"),
                "hint_hi": b.get("_hint_hi"),
            })
        for ex in b.get("exhibit", []):
            if ex.get("page") is None:
                unknowns.append({
                    "ref": ex,
                    "kind": ex.get("_kind", "Exhibit"),
                    "parent": ex.get("_parent") or b["title"],
                    "title": ex["title"],
                    "hint_lo": ex.get("_hint_lo"),
                    "hint_hi": ex.get("_hint_hi"),
                })
    return unknowns


def _read_page(prompt: str, n_pages: int, hint_lo: int | None, hint_hi: int | None) -> int | None:
    """Prompt until the user gives a valid page number, or chooses to leave out.

    Returns the page number, or None if the user opted to leave the bookmark out.
    """
    page_re = re.compile(r"^(?:p|page\s*)?(\d+)$", re.IGNORECASE)
    while True:
        raw = input(prompt).strip()
        low = raw.lower()
        if low in ("out", "o", "leave out", "skip", "none"):
            confirm = input("    Leave this bookmark out? [y/N]: ").strip().lower()
            if confirm == "y":
                return None
            continue
        m = page_re.match(low)
        if not m:
            print("    Sorry, I didn't catch that. Type a page number (e.g. 64) or 'out'.")
            continue
        page = int(m.group(1))
        if page < 1 or page > n_pages:
            print(f"    The PDF only has {n_pages} pages. Try again.")
            continue
        if hint_lo and hint_hi and not (hint_lo <= page <= hint_hi):
            confirm = input(
                f"    Page {page} is outside the suggested range "
                f"({hint_lo}-{hint_hi}). Use it anyway? [y/N]: "
            ).strip().lower()
            if confirm != "y":
                continue
        return page


def interactive_resolve(
    bookmarks: list[dict], pdf_path: Path, n_pages: int
) -> list[dict]:
    """Walk every unknown, prompt the user, fill in pages, drop any left out."""
    unknowns = collect_unknowns(bookmarks)
    if not unknowns:
        return _drop_unfilled(bookmarks)

    print()
    print("=" * 60)
    print(f"We need help with {len(unknowns)} missing page(s).")
    print("Opening the PDF in your default viewer — keep it visible.")
    print("=" * 60)
    try:
        os.startfile(str(pdf_path))
    except (OSError, AttributeError):
        # not Windows or no associated viewer; user can open manually
        print(f"(Couldn't auto-open. Please open {pdf_path.name} yourself.)")

    for i, unk in enumerate(unknowns, 1):
        print()
        print(f"--- Question {i} of {len(unknowns)} ---")
        if unk["parent"]:
            print(f"  We're looking for {unk['kind']} in {unk['parent']}.")
        else:
            print(f"  We're looking for {unk['kind']}: {unk['title']}.")
        if unk["hint_lo"] and unk["hint_hi"]:
            if unk["hint_lo"] == unk["hint_hi"]:
                print(f"  It should be on page {unk['hint_lo']}.")
            else:
                print(f"  Look in the PDF between page {unk['hint_lo']} and page {unk['hint_hi']}.")
                print(f"  It usually starts on a page with a stamp that says \"This is Exhibit ...\".")
        page = _read_page(
            "  Page number (or 'out' to leave out): ",
            n_pages,
            unk["hint_lo"],
            unk["hint_hi"],
        )
        unk["ref"]["page"] = page

    return _drop_unfilled(bookmarks)


def _drop_unfilled(bookmarks: list[dict]) -> list[dict]:
    """Remove any bookmark/exhibit the user chose to leave out (page is None)."""
    out = []
    for b in bookmarks:
        if b.get("page") is None:
            continue
        b["exhibit"] = [e for e in b.get("exhibit", []) if e.get("page") is not None]
        out.append(b)
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    batch = "--batch" in sys.argv
    if not args:
        print("Usage: python detect.py input.pdf [output.toml] [--batch]")
        sys.exit(1)

    input_file = Path(args[0])
    if not input_file.exists():
        raise FileNotFoundError(input_file)

    # Interactive mode writes a clean .bookmarks.toml directly (no manual rename
    # step). Batch mode writes .bookmarks.draft.toml with comments for review.
    suffix = ".bookmarks.draft.toml" if batch else ".bookmarks.toml"
    output_file = Path(args[1]) if len(args) > 1 else input_file.with_suffix(suffix)

    print(f"Scanning {input_file.name}...")
    bookmarks, warnings = detect(input_file)
    n_pages = len(PdfReader(str(input_file)).pages)

    if not batch:
        bookmarks = interactive_resolve(bookmarks, input_file, n_pages)

    toml = emit_toml(bookmarks, warnings, input_file, draft=batch)
    output_file.write_text(toml, encoding="utf-8")

    n_top = sum(1 for b in bookmarks if b.get("page") is not None)
    n_ex = sum(len(b.get("exhibit", [])) for b in bookmarks)
    print()
    print(f"Done — {n_top} document(s), {n_ex} exhibit(s).")
    print(f"Saved to: {output_file.name}")
    if batch:
        if warnings:
            print(f"\n{len(warnings)} warning(s):")
            for w in warnings:
                print(f"  - {w}")
        print("Review, rename to remove '.draft', then pass to bookmark.py.")
    else:
        print(f"Next: python bookmark.py \"{input_file}\"")
