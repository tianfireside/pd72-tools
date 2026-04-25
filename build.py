"""
Orchestrate detect -> review -> bookmark -> hyperlink as one command.

Usage: python build.py input_paged.pdf [output.pdf]

Regenerates the bookmark TOML from the PDF on every run so it can't fall
out of sync with the document. Walks the user through any unknowns
interactively, then stamps bookmarks and the hyperlinked index in one
shot. Output defaults to input_final.pdf.

This is the canonical entry point for the bookmark/link half of the
pipeline. The standalone scripts (detect.py, bookmark.py, hyperlink.py)
remain callable for debugging, but bypassing build.py reintroduces the
drift risk it exists to prevent.
"""

import sys
from pathlib import Path

from pypdf import PdfReader

from bookmark import add_bookmarks
from detect import detect, emit_toml, interactive_resolve
from hyperlink import add_hyperlinks


def build(input_path: str, output_path: str | None = None) -> Path:
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(input_file)

    output_file = (
        Path(output_path) if output_path
        else input_file.with_stem(input_file.stem + "_final")
    )
    toml_file = input_file.with_suffix(".bookmarks.toml")
    intermediate = input_file.with_stem(input_file.stem + "_tmp_bookmarked")

    print(f"Input:  {input_file.name}")
    print(f"Output: {output_file.name}")
    print()

    # 1. Detect — fresh scan of the current PDF, every time.
    print("[1/4] Scanning PDF for index, affidavits, and exhibits...")
    bookmarks, index_pages, warnings, ctx = detect(input_file)
    if not bookmarks:
        print("\nDetect found no bookmarks. Cannot continue:")
        for w in warnings:
            print(f"  - {w}")
        sys.exit(1)
    n_pages = len(PdfReader(str(input_file)).pages)
    n_top = sum(1 for b in bookmarks if b.get("page") is not None)
    n_unknown = sum(1 for b in bookmarks if b.get("page") is None) + sum(
        1 for b in bookmarks for e in b.get("exhibit", []) if e.get("page") is None
    )
    print(f"  Found {n_top} top-level bookmark(s), {n_unknown} need your input.")

    # 2. Review — confirm every affidavit start and every exhibit (page +
    #    title). Only path for human correction; no manual TOML editing.
    print("\n[2/4] Reviewing detected bookmarks...")
    bookmarks = interactive_resolve(bookmarks, ctx, input_file, n_pages)

    # Persist the reviewed TOML next to the input as an audit artifact.
    # It's an OUTPUT of this run, not an input to the next — build.py
    # regenerates it each time.
    toml = emit_toml(
        bookmarks, warnings, input_file, index_pages=index_pages, draft=False
    )
    toml_file.write_text(toml, encoding="utf-8")
    print(f"\nReviewed TOML saved to: {toml_file.name}")

    # 3. Bookmark — stamp the outline tree.
    print("\n[3/4] Adding bookmarks...")
    add_bookmarks(str(input_file), str(toml_file), str(intermediate))

    # 4. Hyperlink — stamp clickable rows on the index page.
    print("\n[4/4] Adding index hyperlinks...")
    try:
        add_hyperlinks(str(intermediate), str(toml_file), str(output_file))
    finally:
        if intermediate.exists():
            intermediate.unlink()

    size = output_file.stat().st_size / 1_000_000
    print(f"\nDone. Final PDF: {output_file.name} ({size:.1f} MB)")
    return output_file


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python build.py input_paged.pdf [output.pdf]")
        sys.exit(1)
    build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
