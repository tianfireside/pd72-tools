# pd72-tools

Python scripts for preparing electronic application records that comply with BC Supreme Court Practice Direction PD-72 (effective March 31, 2026).

## Scripts

### `ocr.py` — Make PDFs searchable

Runs OCR on scanned pages only, skipping pages that already have a text layer.

```
python ocr.py input.pdf [output.pdf]
```

Output defaults to `input_OCR.pdf` in the same folder.

**Requires:** Tesseract OCR (`winget install UB-Mannheim.TesseractOCR`), `pip install ocrmypdf`

### `pagenumber.py` — Add sequential page numbers

Stamps a page number top-centre on every page.

```
python pagenumber.py input.pdf [output.pdf]
```

Output defaults to `input_paged.pdf` in the same folder.

### `bookmark.py` — Add nested bookmarks from TOML

Reads a sidecar TOML config and writes a PDF with one bookmark per document
and one nested bookmark per exhibit. Validates that all pages are in strictly
increasing order. Wipes any pre-existing outline so re-runs are idempotent.

```
python bookmark.py input.pdf [config.toml] [output.pdf]
```

Config defaults to `input.bookmarks.toml`. Output defaults to `input_bookmarked.pdf`.

### `detect.py` — Auto-generate a draft bookmark TOML

Scans an OCR'd record, parses the index page as the source of truth for
top-level structure, then locates each tab in the PDF (NOA/affidavits by form
header + affiant name; standalone documents by keyword search in the gap
between matched neighbours). For affidavit tabs, parses the body for
"Exhibit X" references and pairs them with BC exhibit cover sheets.

```
python detect.py input.pdf [output.toml]
```

Output defaults to `input.bookmarks.draft.toml`. **Always review** before
renaming to `.bookmarks.toml` and passing to `bookmark.py`.

## PD-72 compliance checklist

- [x] Searchable text (OCR) — `ocr.py`
- [x] Page numbers top-centre, sequential — `pagenumber.py`
- [x] Bookmarks per document and exhibit — `bookmark.py` (+ `detect.py` for draft)
- [ ] Hyperlinked index
- [ ] No password protection
- [ ] Under 50 MB

## Setup

```
pip install ocrmypdf pypdf reportlab
winget install UB-Mannheim.TesseractOCR
```
