"""
Verify a PDF meets BC Supreme Court PD-72 compliance requirements.

Usage: python compliance.py input.pdf

Checks:
  - Searchable text on every page
  - Bookmarks present (one per document, nested per exhibit)
  - Hyperlinks on the index page
  - Sequential page numbers in the top-centre region
  - File size < 50 MB
  - No password / encryption
  - No embedded JavaScript

Exits 0 if all checks pass, 1 if any fail. Output is a per-check report
listing the offending pages where applicable.

Cover-page form check is intentionally skipped — Form 30.001 / F32.2
layouts vary too much per matter to verify reliably.
"""

import re
import sys
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from detect import RE_INDEX_HEADER

MAX_SIZE_BYTES = 50 * 1_000_000


# ---- individual checks ----

def check_searchable(reader: PdfReader) -> tuple[bool, str, list[int]]:
    """Every page must have an extractable text layer (PD-72: searchable)."""
    blank = []
    for i, page in enumerate(reader.pages, start=1):
        txt = (page.extract_text() or "").strip()
        if not txt:
            blank.append(i)
    if blank:
        return False, f"{len(blank)} page(s) have no text layer", blank
    return True, f"all {len(reader.pages)} page(s) searchable", []


def check_bookmarks(reader: PdfReader) -> tuple[bool, str, list[int]]:
    """Outline must exist with at least one top-level entry."""
    outline = reader.outline or []

    def count(items, depth=0):
        n_top = 0
        n_nested = 0
        for item in items:
            if isinstance(item, list):
                # pypdf nests children as a sublist after the parent.
                sub_top, sub_nested = count(item, depth + 1)
                if depth == 0:
                    n_nested += sub_top + sub_nested
                else:
                    n_nested += sub_top + sub_nested
            else:
                if depth == 0:
                    n_top += 1
                else:
                    n_nested += 1
        return n_top, n_nested

    n_top, n_nested = count(outline)
    if n_top == 0:
        return False, "no bookmarks found", []
    return True, f"{n_top} top-level bookmark(s), {n_nested} nested", []


def check_hyperlinks(reader: PdfReader) -> tuple[bool, str, list[int]]:
    """The index page must carry /Link annotations to the bookmarked tabs.

    Index page is whichever page contains the 'TAB DOCUMENT DATE' header.
    Reads annotations directly off the page dict — pdfplumber's annot
    parser silently drops some /Link entries, so we go to pypdf.
    """
    index_pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "")
        if RE_INDEX_HEADER.search(text):
            index_pages.append(i)

    if not index_pages:
        return False, "no index page detected (looking for 'TAB DOCUMENT DATE')", []

    ip = index_pages[0]
    page = reader.pages[ip - 1]
    annots = page.get("/Annots") or []
    links = [a for a in annots if a.get_object().get("/Subtype") == "/Link"]
    if not links:
        return False, f"index page p{ip} has no /Link annotations", [ip]
    return True, f"{len(links)} link(s) on index page p{ip}", []


def check_page_numbers(pdf_path: Path) -> tuple[bool, str, list[int]]:
    """Each page must show its page number in the top-centre region.

    We scan a band across the top ~6% of each page and look for a token
    that equals the expected page number. pagenumber.py stamps Helvetica
    10pt at (width/2, height-28); we allow a generous bbox to tolerate
    pages that already had a number elsewhere being merged in.
    """
    missing = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            top_band_h = page.height * 0.06
            crop = page.crop((0, 0, page.width, top_band_h))
            text = (crop.extract_text() or "").strip()
            tokens = re.findall(r"\b\d+\b", text)
            if str(i) not in tokens:
                missing.append(i)
    if missing:
        return False, f"{len(missing)} page(s) missing top-centre page number", missing
    return True, f"all {n} page(s) numbered top-centre", []


def check_size(pdf_path: Path) -> tuple[bool, str, list[int]]:
    """File must be under 50 MB (PD-72)."""
    size = pdf_path.stat().st_size
    mb = size / 1_000_000
    if size > MAX_SIZE_BYTES:
        return False, f"{mb:.1f} MB exceeds 50 MB limit", []
    return True, f"{mb:.1f} MB (under 50 MB)", []


def check_encryption(reader: PdfReader) -> tuple[bool, str, list[int]]:
    """No password protection (PD-72)."""
    if reader.is_encrypted:
        return False, "file is encrypted / password-protected", []
    return True, "no password protection", []


def check_javascript(reader: PdfReader) -> tuple[bool, str, list[int]]:
    """No embedded JavaScript or auto-actions (PD-72: no embedded scripts)."""
    findings = []
    root = reader.trailer.get("/Root")
    if root is None:
        return True, "no document catalog (unusual but no JS)", []
    root_obj = root.get_object()

    # Document-level OpenAction (runs when the PDF opens).
    if "/OpenAction" in root_obj:
        findings.append("/OpenAction in catalog")

    # Document-level additional actions.
    if "/AA" in root_obj:
        findings.append("/AA in catalog")

    # Named JavaScript scripts in /Names tree.
    names = root_obj.get("/Names")
    if names is not None:
        names_obj = names.get_object()
        if "/JavaScript" in names_obj:
            findings.append("/JavaScript in /Names tree")

    # Per-page actions.
    for i, page in enumerate(reader.pages, start=1):
        if "/AA" in page:
            findings.append(f"/AA on page {i}")

    if findings:
        return False, "; ".join(findings), []
    return True, "no embedded JavaScript or auto-actions", []


# ---- report ----


def check_compliance(pdf_path: str | Path) -> bool:
    """Run every check, print a report, return True iff all passed."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(path)

    reader = PdfReader(str(path))

    print(f"=== PD-72 Compliance Report ===")
    print(f"File: {path.name}")
    print()

    checks = [
        ("Searchable text",  lambda: check_searchable(reader)),
        ("Bookmarks",        lambda: check_bookmarks(reader)),
        ("Hyperlinked index", lambda: check_hyperlinks(reader)),
        ("Page numbers",     lambda: check_page_numbers(path)),
        ("File size",        lambda: check_size(path)),
        ("No encryption",    lambda: check_encryption(reader)),
        ("No JavaScript",    lambda: check_javascript(reader)),
    ]

    n_failed = 0
    for label, fn in checks:
        try:
            ok, summary, pages = fn()
        except Exception as e:
            ok = False
            summary = f"check raised {type(e).__name__}: {e}"
            pages = []

        tag = "[PASS]" if ok else "[FAIL]"
        print(f"{tag} {label}: {summary}")
        if not ok:
            n_failed += 1
            if pages:
                # Show up to 20 page numbers, then a count for the rest.
                shown = ", ".join(str(p) for p in pages[:20])
                more = f" (+{len(pages) - 20} more)" if len(pages) > 20 else ""
                print(f"         pages: {shown}{more}")

    print()
    if n_failed == 0:
        print("Result: PASS - all checks passed")
        return True
    print(f"Result: FAIL - {n_failed} check(s) failed")
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compliance.py input.pdf")
        sys.exit(1)
    ok = check_compliance(sys.argv[1])
    sys.exit(0 if ok else 1)
