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

## PD-72 compliance checklist

- [ ] Searchable text (OCR) — `ocr.py`
- [ ] Page numbers top-centre, sequential
- [ ] Bookmarks per document and exhibit
- [ ] Hyperlinked index
- [ ] No password protection
- [ ] Under 50 MB

## Setup

```
pip install ocrmypdf pypdf
winget install UB-Mannheim.TesseractOCR
```
