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

### `hyperlink.py` — Add clickable index hyperlinks

Reads the bookmarks TOML and stamps a `/Link` annotation on each index row,
pointing to the bookmarked target page. Uses pdfplumber for line-level bbox
detection. Idempotent — wipes existing link annotations on the index page
first.

```
python hyperlink.py input.pdf [config.toml] [output.pdf]
```

### `build.py` — Run the full pipeline

Canonical entry point for the bookmark + link half of the pipeline. Runs
`detect` → interactive review → `bookmark` → `hyperlink` in one shot,
regenerating the TOML from the current PDF every time so it cannot drift.
The standalone scripts remain callable for debugging; bypassing `build.py`
reintroduces the drift risk it exists to prevent.

```
python build.py input_paged.pdf [output.pdf]
```

### `compliance.py` — Verify a finished PDF against PD-72

Runs every PD-72 requirement as an independent check and prints a per-check
report. Exits 0 if all pass, 1 if any fail. Cover-page form check is
intentionally skipped (form layouts vary too much per matter).

```
python compliance.py final.pdf
```

## PD-72 compliance checklist

- [x] Searchable text (OCR) — `ocr.py` (verified by `compliance.py`)
- [x] Page numbers top-centre, sequential — `pagenumber.py` (verified by `compliance.py`)
- [x] Bookmarks per document and exhibit — `bookmark.py` (+ `detect.py` for draft)
- [x] Hyperlinked index — `hyperlink.py` (verified by `compliance.py`)
- [x] No password protection — verified by `compliance.py`
- [x] Under 50 MB — verified by `compliance.py`

## Setup

```
pip install ocrmypdf pypdf reportlab pdfplumber
winget install UB-Mannheim.TesseractOCR
```
