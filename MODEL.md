# Implicit domain model — what the scripts already share

This is a **starting draft**, not a design spec. It surfaces the model the
four existing scripts already operate against without ever naming. The goal
is to argue with this draft until it's right, *then* write code for the
remaining checklist items (hyperlink, assembler, compliance checker).

Read it as: "here is what the code believes is true today." Disagreements
between scripts are flagged. Gaps the next three scripts will widen are
flagged. Nothing here was invented — it was extracted.

---

## The entities the code already touches

### Record
The single PDF that PD-72 is about. None of the scripts name this concept,
but every script operates on one.

Implicit attributes (gleaned from how scripts treat it):
- a single PDF file on disk
- a fixed page count (1-indexed throughout)
- a structured sequence: cover page → index page(s) → ordered tabs
- a state vector PD-72 cares about: { searchable, page-numbered, bookmarked,
  hyperlinked, has-cover, under-50MB, unencrypted }
- only `detect.py` reads structure; the others treat the Record as an opaque
  PDF + page count

### Document
A top-level entry in the record's index. The thing a tab points at. Each
script that thinks about documents calls them something different:
- `bookmark.py` calls them "bookmarks"
- `detect.py` calls them "tabs" / "entries"
- the index calls them rows

Implicit attributes:
- tab number (1-indexed; strictly increasing in document order)
- title
- date (multiple string formats accepted: `dd-MMM-yyyy`, `yyyy-mm-dd`, etc.)
- kind: `noa` | `affidavit` | `other`
- start page (1-indexed PDF page)
- end page (computed: next tab's start minus 1; last tab ends at page count)

### Affidavit (a Document)
The only Document kind with internal structure that the code parses.
- affiant name (proper-cased)
- ordinal (1, 2, 3...)
- body region: from start page to (first exhibit cover − 1) or signature
  page, whichever comes first
- has zero or more Exhibits
- can itself be nested (i.e., be an exhibit of another affidavit)

### Exhibit
- belongs to exactly one Affidavit
- letter: spreadsheet-column ordering A, B, ... Z, AA, AB, ... AZ, BA, ...
- description: free-form fragment captured from the body's "Exhibit X is..."
  reference
- start page (1-indexed)
- anchored by either a BC standard exhibit cover sheet ("This is Exhibit X
  referred to in the affidavit of Y") OR a nested-affidavit start page
- if it's a nested affidavit, that nested affidavit has its own exhibits
  which are NOT promoted to the Record's outline

### Index
A page (or pages) inside the Record listing the tabs. Treated by `detect.py`
as the source of truth for top-level structure.
- attributes: page location, rows
- each row: tab number, description, date

### Cover page
PD-72 mandated (Form 30.001 civil / F32.2 family). **Not modeled by any
script.** Prepared by hand. Scripts assume it exists at page 1.

### Page (a unit of classification)
- 1-indexed throughout
- type (mutually exclusive, as `detect.py` classifies):
  `index` | `affidavit` | `noa` | `exhibit_cover` | (none = body content)
- attribute: `has_signature` (bool, OCR-tolerant match)

---

## Where the scripts agree

- **Pages are 1-indexed everywhere.** No off-by-one ambiguity.
- **Single-PDF input, single-PDF output.** Every transform stage produces
  a new PDF; nothing fans out or in.
- **Naming convention is suffix-based:** `_OCR`, `_paged`, `_bookmarked`.
  Same folder as input.
- **The outline is exactly two levels deep:** Record → Document → Exhibit.
  No deeper nesting is representable in the TOML or in `bookmark.py`'s
  validation.
- **The TOML is authoritative when present.** `bookmark.py` wipes any
  existing `/Outlines` before applying the TOML.
- **Strictly increasing page order across the entire outline** (validated
  by `bookmark.py._validate_sequence`).

---

## Where the scripts disagree (or don't talk to each other)

### 1. There is no "Record" type
Every script takes `input.pdf` as a string. Nothing tracks what state the
PDF is in (OCR'd? paged? bookmarked?). The compliance checker will need
this; the assembler will need this; today nothing has it.

### 2. The TOML schema grew by accretion
- `bookmark.py` consumes `{title, page, exhibit: [{title, page}]}`.
- `detect.py` produces that, plus annotations on entries it can't resolve
  (`_hint_lo`, `_hint_hi`, `_kind`, `_parent`) — these are stripped before
  emit, but they live in the in-memory dict.
- A future hyperlink script wants to know the **index page(s)** to stamp
  link annotations onto. That's a new top-level field.
- A future assembler will want **source-file provenance** ("this affidavit
  came from `wing-affidavit.docx`") to handle re-runs cleanly.

The schema has no version, no validator, no documentation. Each new script
will keep extending it unless we draw a line.

### 3. Document "kind" lives in detect.py and nowhere else
`detect.py` knows that NOAs don't have exhibits and affidavits do.
`bookmark.py` doesn't — you could put exhibits under a `Notice of
Application` bookmark and it would happily render them. That's a real
invariant of the legal domain that isn't enforced or even named outside
detect.

### 4. Failure semantics are inconsistent
| Script | On failure |
|---|---|
| `ocr.py` | prints exit code, doesn't raise |
| `pagenumber.py` | no failure path |
| `bookmark.py` | raises `ValueError` for invariant violations |
| `detect.py` | accumulates warnings; interactive mode prompts; batch writes draft TOML |

The compliance checker needs a single, codified vocabulary: hard error vs.
warning vs. info, and what's recoverable.

### 5. Validation logic is duplicated and partial
- `bookmark.py._validate_sequence` enforces strictly increasing pages.
- `detect.py` implicitly enforces the same thing while building.
- The compliance checker will re-implement this a third time unless we
  pull it into one place.

### 6. PD-72 compliance criteria are scattered (or absent)
The CLAUDE.md / README.md list them informally:
searchable, bookmarks, hyperlinked index, page-numbered top-centre, cover
page (Form 30.001/F32.2), <50MB, no password, no embedded scripts.

None of these live in code. The compliance checker will need each one
expressed as a check function returning a structured result.

### 7. Pipeline order is implicit
The right order is: OCR → page numbers → detect (needs OCR) → bookmark
(reads paged PDF) → hyperlink index (needs bookmarks done) → final
compliance check. Today this lives in your head and in the README's
checklist. The assembler will need it codified as a DAG (some steps depend
on others; some are independent).

### 8. The interactive prompt UX has no shared vocabulary
`detect.py`'s prompts say "Exhibit C of Affidavit #2 of Karin Wang."
A future assembler prompt might say "Tab 3 source file?" or
"Re-run OCR on page 47?". These should have a consistent voice, a
consistent way of opening the PDF, a consistent way of accepting "out".
That's UX, but it leans on the model: every prompt is *about* something in
the Record.

---

## Open questions to nail down before writing more code

These are listed in roughly the order they affect code:

1. **Is a Record a class, or just a folder convention?** Either works. A
   class lets us track state (OCR'd? paged?) and own the file path, the
   page count, and a reference to the TOML. A folder convention is
   lighter weight but pushes the same concerns into every script.
2. **Is the TOML the canonical model, or a serialization of one?**
   Today it's the model. If we treat it as serialization, we get a typed
   in-memory representation (dataclasses) that scripts pass around and
   the TOML is a load/save format only.
3. **Document kinds: closed enum or open string?** PD-72 only contemplates
   a few (NOA, application response, affidavits, factums, authorities).
   Closed enum is more pleasant to work with and forces a deliberate add
   when something new shows up.
4. **Where do exhibit-pairing heuristics live?** Today in `detect.py`.
   If a new affidavit-only script needs them, we'll either move them or
   duplicate. Probably want them on the Affidavit type itself.
5. **Compliance checker output format.** A list of `Issue(level, message,
   page_ref?)` is the obvious shape, but it locks in the prompt UX too.
6. **Where does the cover page fit?** It's not auto-generated, but the
   compliance checker needs to verify it exists and contains the right
   form. That means at least *recognizing* it.
7. **How do we represent "this Record is at pipeline stage N"?** Filename
   suffix? Embedded XMP metadata? A sidecar `.state.json`? Affects
   re-runs, idempotency, and the assembler's ability to skip done work.

---

## Minimum viable model

If we pick the lightest option that gets us through hyperlink + assembler
+ compliance checker without further accretion, it looks something like:

```python
# Pseudo-code, not committed code.

@dataclass
class Exhibit:
    letter: str           # "A", "AB"
    title: str
    page: int

@dataclass
class Document:
    tab: int
    title: str
    kind: Literal["noa", "affidavit", "other"]
    page: int
    exhibits: list[Exhibit] = field(default_factory=list)
    # affidavit-only:
    affiant: str | None = None
    number: int | None = None

@dataclass
class Record:
    pdf_path: Path
    n_pages: int
    cover_page: int           # always 1, today
    index_pages: list[int]    # for hyperlinking
    documents: list[Document]

    # invariants checked in __post_init__ or a .validate() method:
    #  - all pages 1 <= p <= n_pages
    #  - tab pages strictly increasing
    #  - exhibits within their parent's [page, next_doc.page) range
    #  - exhibit letters in spreadsheet-column order within their parent
    #  - only affidavits have exhibits
```

The TOML becomes a load/save format for `Record`. `detect.py`, `bookmark.py`,
hyperlink, and compliance all consume `Record` instances.

This is the smallest jump from "implicit model in TOML" to "explicit model
in code" that I can see. Open to argument that it's still too much, or
that it's missing something the next three scripts will need.

---

## What I'd want from you before writing code

For each of the seven open questions above: a one-line answer or "I don't
care, you pick". That converts this draft into a spec. Then we either
build the dataclasses + migrate the existing scripts, or decide the
folder-convention path is good enough for the three remaining scripts and
keep going point-tool.
