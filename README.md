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

## PD-72 compliance checklist

- [x] Searchable text (OCR) — `ocr.py`
- [x] Page numbers top-centre, sequential — `pagenumber.py`
- [ ] Bookmarks per document and exhibit
- [ ] Hyperlinked index
- [ ] No password protection
- [ ] Under 50 MB

## Setup

```
pip install ocrmypdf pypdf reportlab
winget install UB-Mannheim.TesseractOCR
```
