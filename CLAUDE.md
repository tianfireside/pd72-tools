# pd72-tools

Internal Python tooling to prepare electronic application records that comply with **BC Supreme Court Practice Direction PD-72** (Associate Judges Chambers Pilot Project, effective March 31, 2026).

Used by Tian Luo (solo lawyer, Fireside Law / Direction Legal LLP). Not a product — internal scripts, run from the command line, output back to the local filesystem.

## What PD-72 requires

Each electronic application record must be a **single PDF** that is:

- **Searchable** — text layer present on every page (OCR scanned pages)
- **Bookmarked** — one bookmark per document and per exhibit
- **Hyperlinked index** — entries link to the start of each document
- **Page-numbered** — sequential, top-centre of every page
- **Cover page** — Form 30.001 (civil) or F32.2 (family), with email + phone for *all* parties
- **Under 50 MB**, **no password protection**, no embedded scripts

The Practice Direction itself is at `C:\Users\Work\Downloads\PD-72_Electronic_Application_Records.pdf`.

## Reference test case

`C:\Users\Work\Downloads\Application Record - 240139.pdf` — Estate of Ping Li (file P142689). 76 pages. Used to validate every script in this repo. Hearing was 2026-04-28.

Structure: cover page → index (5 tabs) → notice of application → 3 affidavits with exhibits.

## Workflow assumptions

- **Cover page is always prepared by hand.** It changes too much per matter to be worth automating. Scripts here pick up *after* the cover page exists.
- Affidavits and exhibits are exported from Word (or scanned in), then assembled into a single record.
- The user runs scripts on Windows. Paths should handle spaces and forward/backslash mixing.

## Build order

Tick items off `README.md`'s checklist as scripts land. Current state:

- [x] `ocr.py` — searchable text via ocrmypdf, skips pages that already have text
- [x] `pagenumber.py` — sequential page numbers top-centre via reportlab + pypdf
- [ ] bookmarks per document/exhibit
- [ ] hyperlinked index
- [ ] full assembler (combines all of the above into one command)
- [ ] compliance checker (verifies a PDF meets all PD-72 requirements)

## Stack

- **Python 3.14** on Windows
- **ocrmypdf** for OCR (calls Tesseract under the hood)
- **pypdf** for page-level edits, bookmarks, metadata
- **pikepdf** when pypdf isn't enough (object-level PDF editing)
- **reportlab** for drawing new content onto pages (page numbers, watermarks)

Avoid heavier frameworks. These are short scripts, not a service.

## Working with this repo's owner

Same conventions as the fireside.law repo:

- **Build one step at a time and stop.** Don't batch multiple scripts in a single change.
- **Ask before installing anything new** — Tesseract, Ghostscript, new pip packages.
- **Test against the reference case** (`Application Record - 240139.pdf`) before declaring a script done.
- **Explain new tech when introducing it.** The user is learning the PDF tooling alongside you.

## Commits

- Claude is the sole author of all commits in this repo. Always use `git commit --author="Claude <noreply@anthropic.com>"`.
- Never add `Co-Authored-By` trailers.
- Never modify global git config.

## Hosting

GitHub: https://github.com/tianfireside/pd72-tools. Push to `master` is fine — no deploy hooks, no CI, scripts run locally.
