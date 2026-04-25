"""
Add clickable hyperlinks to the index page of a record.

Usage: python hyperlink.py input.pdf [config.toml] [output.pdf]

Config defaults to input.bookmarks.toml in the same folder.
Output defaults to input_hyperlinked.pdf.

Reads index_pages and bookmarks from the TOML, finds each tab row on
the index page using pdfplumber for line-level bboxes, and stamps a
/Link annotation on each row pointing to the bookmarked tab page.

Idempotent — wipes existing link annotations on the index page first.
"""

import re
import sys
import tomllib
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import ArrayObject, NameObject


# Lines on the index page that start with a digit followed by whitespace
# are tab rows. Anything else (column headers, page titles) is skipped.
RE_TAB_ROW = re.compile(r"^\s*\d+\s+\S")


def add_hyperlinks(
    input_path: str,
    config_path: str | None = None,
    output_path: str | None = None,
) -> Path:
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(input_file)

    config_file = (
        Path(config_path) if config_path
        else input_file.with_suffix(".bookmarks.toml")
    )
    if not config_file.exists():
        raise FileNotFoundError(
            f"No bookmark config found at {config_file}. Run detect.py first."
        )

    output_file = (
        Path(output_path) if output_path
        else input_file.with_stem(input_file.stem + "_hyperlinked")
    )

    with open(config_file, "rb") as f:
        config = tomllib.load(f)

    index_pages = config.get("index_pages", [])
    if not index_pages:
        raise ValueError(
            f"No 'index_pages' in {config_file}. Re-run detect.py to refresh the TOML."
        )
    bookmarks = config.get("bookmark", [])
    if not bookmarks:
        raise ValueError(f"No [[bookmark]] entries in {config_file}.")

    print(f"Input:  {input_file.name}")
    print(f"Config: {config_file.name}")
    print(f"Output: {output_file.name}")
    print(f"Index page(s): {index_pages}\n")

    # Walk each index page, harvest the bbox of every tab row.
    rows = _find_tab_rows(input_file, index_pages)

    if len(rows) != len(bookmarks):
        print(
            f"WARNING: found {len(rows)} tab row(s) on index page(s) but "
            f"{len(bookmarks)} bookmark(s) in TOML. Linking by order — "
            f"verify the result."
        )

    reader = PdfReader(str(input_file))
    writer = PdfWriter(clone_from=reader)

    # Wipe existing /Link annotations on each index page so re-runs are idempotent.
    for ipage in index_pages:
        page_obj = writer.pages[ipage - 1]
        if "/Annots" in page_obj:
            kept = [
                a for a in page_obj["/Annots"]
                if a.get_object().get("/Subtype") != "/Link"
            ]
            page_obj[NameObject("/Annots")] = ArrayObject(kept)

    # Stamp one link per row → bookmark, paired by index order.
    # pypdf's Link writes /Dest as [NumberObject(idx), /Fit], but the PDF
    # spec requires an indirect ref to the page object — most viewers either
    # ignore the link or jump to the wrong page. Patch /Dest after creation.
    for (ipage, rect), bm in zip(rows, bookmarks):
        target_page = writer.pages[bm["page"] - 1]
        link = Link(rect=rect, target_page_index=bm["page"] - 1)
        ref = writer.add_annotation(page_number=ipage - 1, annotation=link)
        ref.get_object()[NameObject("/Dest")] = ArrayObject([
            target_page.indirect_reference,
            NameObject("/Fit"),
        ])
        title = bm["title"][:50] + ("..." if len(bm["title"]) > 50 else "")
        print(f"  Tab {bm.get('tab', '?')}: {title} -> p{bm['page']}")

    with open(output_file, "wb") as f:
        writer.write(f)

    size_mb = output_file.stat().st_size / 1_000_000
    print(f"\nLinked {len(rows)} row(s). Output: {output_file.name} ({size_mb:.1f} MB)")
    return output_file


def _find_tab_rows(pdf_path: Path, index_pages: list[int]) -> list[tuple[int, tuple[float, float, float, float]]]:
    """Return [(page_1idx, (x1, y1, x2, y2)), ...] for each tab row found.

    pdfplumber gives us top-left coords; PDF link rectangles use bottom-left,
    so we flip Y and pad a couple of points so the click target isn't a hairline.
    """
    out = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for ipage in index_pages:
            page = pdf.pages[ipage - 1]
            h = page.height
            for line in page.extract_text_lines():
                if not RE_TAB_ROW.match(line["text"]):
                    continue
                x0, x1 = line["x0"], line["x1"]
                y_top_pdf = h - line["top"]
                y_bot_pdf = h - line["bottom"]
                out.append((ipage, (x0 - 2, y_bot_pdf - 1, x1 + 2, y_top_pdf + 1)))
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python hyperlink.py input.pdf [config.toml] [output.pdf]")
        sys.exit(1)
    add_hyperlinks(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else None,
        sys.argv[3] if len(sys.argv) > 3 else None,
    )
