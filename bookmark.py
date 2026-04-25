"""
Add nested bookmarks to a PDF from a sidecar TOML config.

Usage: python bookmark.py input.pdf [config.toml] [output.pdf]

Config defaults to input.bookmarks.toml in the same folder.
Output defaults to input_bookmarked.pdf in the same folder.

TOML format (page numbers are 1-indexed PDF pages):

    [[bookmark]]
    title = "Notice of Application"
    page = 7

    [[bookmark]]
    title = "Affidavit #1 of John Smith"
    page = 12

      [[bookmark.exhibit]]
      title = "Exhibit A - Will"
      page = 15

      [[bookmark.exhibit]]
      title = "Exhibit B - Death Certificate"
      page = 22
"""

import sys
import tomllib
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject


def add_bookmarks(
    input_path: str,
    config_path: str | None = None,
    output_path: str | None = None,
) -> Path:
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(input_file)

    config_file = (
        Path(config_path)
        if config_path
        else input_file.with_suffix(".bookmarks.toml")
    )
    if not config_file.exists():
        raise FileNotFoundError(
            f"No bookmark config found at {config_file}. "
            f"Create it or pass an explicit path."
        )

    output_file = (
        Path(output_path)
        if output_path
        else input_file.with_stem(input_file.stem + "_bookmarked")
    )

    with open(config_file, "rb") as f:
        config = tomllib.load(f)

    reader = PdfReader(str(input_file))
    writer = PdfWriter(clone_from=reader)
    n_pages = len(reader.pages)

    # Wipe any existing outline so the TOML is authoritative (idempotent re-runs)
    root = writer._root_object
    outlines_key = NameObject("/Outlines")
    if outlines_key in root:
        del root[outlines_key]

    print(f"Input:  {input_file} ({input_file.stat().st_size / 1_000_000:.1f} MB, {n_pages} pages)")
    print(f"Config: {config_file}")
    print(f"Output: {output_file}\n")

    bookmarks = config.get("bookmark", [])
    if not bookmarks:
        raise ValueError(f"No [[bookmark]] entries found in {config_file}")

    _validate_sequence(bookmarks, n_pages)

    n_top = 0
    n_exhibit = 0

    for entry in bookmarks:
        parent = writer.add_outline_item(entry["title"], entry["page"] - 1)
        n_top += 1
        print(f"- {entry['title']} (p. {entry['page']})")
        for exhibit in entry.get("exhibit", []):
            writer.add_outline_item(exhibit["title"], exhibit["page"] - 1, parent=parent)
            n_exhibit += 1
            print(f"    - {exhibit['title']} (p. {exhibit['page']})")

    with open(output_file, "wb") as f:
        writer.write(f)

    size = output_file.stat().st_size / 1_000_000
    print(f"\nAdded {n_top} document bookmark(s), {n_exhibit} exhibit bookmark(s).")
    print(f"Done. Output: {output_file} ({size:.1f} MB)")
    return output_file


def _validate_page(entry: dict, n_pages: int) -> None:
    page = entry.get("page")
    title = entry.get("title", "<untitled>")
    if page is None:
        raise ValueError(f"Bookmark '{title}' is missing a page number")
    if not isinstance(page, int) or page < 1 or page > n_pages:
        raise ValueError(
            f"Bookmark '{title}' has invalid page {page!r} (PDF has {n_pages} pages)"
        )


def _validate_sequence(bookmarks: list[dict], n_pages: int) -> None:
    """Walk every bookmark in document order; pages must strictly increase.

    Tabs are sequential, exhibits sit inside their tab, and a tab cannot
    start before the previous tab's last exhibit. Catches misordered TOMLs
    before they produce a confusingly bookmarked PDF.
    """
    prev_page = 0
    prev_title = "<start of document>"
    for entry in bookmarks:
        _validate_page(entry, n_pages)
        page = entry["page"]
        if page <= prev_page:
            raise ValueError(
                f"Bookmark '{entry['title']}' (page {page}) must come after "
                f"'{prev_title}' (page {prev_page}). Tabs and exhibits must "
                f"be in strictly increasing page order."
            )
        prev_page, prev_title = page, entry["title"]
        for exhibit in entry.get("exhibit", []):
            _validate_page(exhibit, n_pages)
            ep = exhibit["page"]
            if ep <= prev_page:
                raise ValueError(
                    f"Exhibit '{exhibit['title']}' (page {ep}) must come after "
                    f"'{prev_title}' (page {prev_page}). Tabs and exhibits must "
                    f"be in strictly increasing page order."
                )
            prev_page, prev_title = ep, exhibit["title"]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python bookmark.py input.pdf [config.toml] [output.pdf]")
        sys.exit(1)
    add_bookmarks(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else None,
        sys.argv[3] if len(sys.argv) > 3 else None,
    )
