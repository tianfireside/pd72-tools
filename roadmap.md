# Roadmap

This is the long-form plan for where pd72-tools is going. Day-to-day "next slice" tracking lives in `CLAUDE.md`'s build-order checklist; this file holds the bigger picture so the slices stack into something coherent.

## Guiding principles

1. **One step at a time.** Each slice ships standalone. No big-bang refactors.
2. **Test against real records.** The reference case (`Application Record - 240139.pdf`) is the gate. New code that breaks it doesn't ship.
3. **Add second, abstract third.** Don't extract a framework until the second concrete use case forces it. Avoid `DocumentType` / `Detector` interfaces on speculation.
4. **Privilege-aware by default.** Anything that sends document content to a third party must (a) be gated by an explicit BCSC-filing confirmation, and (b) operate under a zero-retention agreement with the AI provider.
5. **Desktop-first.** Stay desktop until distribution pain forces a webapp. PDF processing on a $5 server is too slow to ship.

## Current state (v1.0, April 2026)

- Pipeline scripts: `ocr.py`, `pagenumber.py`, `detect.py`, `bookmark.py`, `hyperlink.py`, `compliance.py`, `build.py`
- Desktop GUI (`gui.py`) with auto-OCR, per-exhibit review cards, save with compliance check
- Inno Setup installer bundling Tesseract 5.4 + Ghostscript 10.03 (~174 MB)
- Released on GitHub, distributed to ~30 BC lawyers

Validated on the Estate of Ping Li reference case. Saves ~1 hour per application record vs. manual prep.

## Phase 1 — Polish (this week)

Small fixes that pay off immediately for current testers. No architecture impact.

- [ ] **Visible blue underlines on index hyperlinks.** `hyperlink.py` adds `/Link` annotations but no visible style; some registry clerks reject because they can't see the link. Overlay a blue underline drawing layer under each linked row, same approach as `pagenumber.py`.
- [ ] **BCSC filing confirmation gate.** A checkbox on the intro page reading "I confirm the substantive contents of this PDF have been filed with the BCSC." The tool refuses to proceed without it. This is the legal-cover precondition for Phase 2.

## Phase 2 — AI-powered detection

Replace `detect.py`'s regex heuristics with Claude. The current accuracy is ~85-90% on standard records; Claude can plausibly hit 99% on filed documents.

**Architecture:** Add a parallel module, don't replace. `detect.py` stays. `detect_ai.py` is added with the same `(bookmarks, index_pages, warnings, ctx)` return shape. The GUI picks based on a setting (default: AI when available, regex on failure).

- [ ] **`anthropic_client.py`** — thin wrapper around the Anthropic SDK. Embeds the API key from a config file the installer drops. Sends with `cache_control` for prompt reuse. Caps at $20/month account-level (manual via Anthropic console).
- [ ] **`detect_ai.py`** — sends per-page text + structural signals to Claude, asks for a JSON document map. Returns same shape as `detect.py`. Includes confidence scores per item.
- [ ] **Model routing via "anything unusual?" prompt.** On the intro screen (next to the BCSC checkbox), an optional free-text field: _"Anything unusual about this record? (nested affidavits, sealed exhibits, multi-affiant packets, etc.)"_ Empty → Haiku 4.5 (~$0.05/record). Filled → Sonnet 4.6 (~$0.20/record), with the description added to the prompt as disambiguation context. The lawyer already knows what's unusual; asking is cheaper than guessing.
- [ ] **Confidence-based escalation.** Even on the Haiku path, if any item comes back below a confidence threshold, retry that document on Sonnet 4.6 before falling back to manual review. Two-tier model use, automatic.
- [ ] **GUI integration** — when AI returns high-confidence results across the board, skip the review cards entirely. Surface only items Claude flagged as uncertain.
- [ ] **Fallback path** — if API call fails (offline, key invalid, $20 cap hit), fall back to regex detector silently with a status-bar note.

**Out of scope for Phase 2:** running our own backend, subscription billing, multi-user auth, Opus/Mythos for any case. Embedded API key + $20 cap + Haiku/Sonnet only is the threat model.

## Phase 3 — Tree-based review UI

Replace the linear card flow with a single editable tree showing the whole document structure. Card-by-card review is the right UI when the model is wrong 15% of the time; once Claude is at 99%, a tree where you scan and fix outliers is the right UI.

- [ ] **`QTreeWidget`-based review pane** — full document tree, inline editing of title and page number, drag-to-reorder, add/remove rows.
- [ ] **PDF preview sync** — clicking any row jumps the preview (already wired for cards, port to tree).
- [ ] **Single Save button** — runs bookmark → hyperlink → compliance in one go.
- [ ] **Card flow removed.** Tree is now the only review UI.

## Phase 4 — Multi-document support

Add Book of Authorities as the second supported document type. This is when the abstraction question becomes real.

The pattern after this phase:

```
pd72-tools/
├── doc_types/
│   ├── application_record.py    # PD-72 detection + compliance rules
│   └── book_of_authorities.py   # PD-XX detection + compliance rules
├── detectors/
│   ├── regex.py                 # Generic regex detector, parameterized by doc type
│   └── ai.py                    # Generic AI detector, parameterized by doc type
├── pipeline/
│   ├── ocr.py / pagenumber.py / bookmark.py / hyperlink.py / compliance.py
└── gui.py
```

But we don't build that structure until Phase 4. In Phase 2-3, `detect_ai.py` and the existing scripts stay where they are.

- [ ] **Document type picker** on intro page: "Application Record (PD-72) / Book of Authorities".
- [ ] **Book of Authorities detector** — finds case names, citations, tab numbers. Different index format (case + citation, not document type).
- [ ] **Book of Authorities compliance** — different rules apply; verify what BCSC actually requires.
- [ ] **Refactor pass** — extract the duplication between the two doc types into the structure above. Only now.

## Phase 5 — Scale (when forced)

Trigger conditions, in order of likelihood:

- **Tester count > 50, multiple firms requesting it for assistants** → consider charging a small subscription, switch from embedded key to small auth'd backend.
- **Cross-platform demand (Mac users at any firm)** → py2app or PyInstaller for macOS. Tesseract/Ghostscript are available there.
- **Browser-based demand ("I want my paralegal to use it without installing anything")** → seriously evaluate webapp. Will require file upload, async OCR queue, user auth, frontend. Months of work, justifies subscription pricing.
- **Other provinces (ON, AB, ...)** → adapt the doc-type framework from Phase 4. The pipeline transfers; the practice directions don't.

None of these are urgent today. Revisit when 2+ trigger conditions are met.

## Open questions to revisit

- **License model.** Currently no explicit license — implicitly proprietary. If we want viral spread among small firms, MIT or AGPL would help; if we plan to charge, leave it closed.
- **Telemetry.** Would help us know if it's actually being used. Has to be opt-in, no client data, just counts. Defer until Phase 4+.
- **Cost ceiling.** $20/month covers maybe 200-400 records depending on prompt size. Monitor and adjust.
- **What to do when Claude is confidently wrong.** The tree UI handles this if the user spots it, but a confident-wrong result that gets blindly Saved is the worst failure mode. Compliance check catches some; not all.

## What this is _not_

- Not a SaaS yet. Not multi-tenant. Not billable.
- Not a full practice management tool. It does one job.
- Not a court-facing tool. The court receives the PDF, not the app.
- Not Ontario- or Alberta-aware. PD-72 is BC-specific; cross-province is Phase 5+.
