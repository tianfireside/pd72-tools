# Surfacing the implicit domain model — a reusable exercise

This is the generic version of the [MODEL.md](MODEL.md) exercise. It's a
methodology, not a model. Use it when you've grown a project by accretion
and the data structure keeps mutating every time you add a script.

---

## When to run this exercise

You probably need it if **three or more** of these are true:

- Three or more scripts (or modules) operate on the same domain object.
- The shared data structure (TOML/JSON/dict/dataclass) has been extended
  more than once, ad hoc, with no schema doc.
- The next feature you're about to build will require extending it again.
- Validation logic for the same invariant appears in more than one place.
- Failure semantics differ between scripts (one raises, one warns, one
  prints).
- Naming for "the same thing" differs across scripts (`tab` here,
  `bookmark` there, `entry` somewhere else).
- A new contributor would struggle to explain how the scripts fit
  together without reading all of them.

If only one or two are true, point-tool growth is still cheap. Don't
over-design.

---

## How to do it

**Do not invent.** Every entity, attribute, and invariant in your output
should come from existing code. The point is to surface what's already
believed, not to design what should be.

1. **Re-read every script with fresh eyes.** Don't skim. Note what each
   one consumes, produces, and assumes.
2. **For each script, fill in this table privately:**

   | what it consumes | what it produces | entities it references | invariants it assumes | how it fails |
   |---|---|---|---|---|

3. **Cross-reference.** Where do scripts agree on an entity? Where do they
   disagree (different name, different attributes, different invariants)?
4. **Look forward.** What does the next planned feature want to add to
   the schema? That extension is a signal of where the current model is
   thin.
5. **List open questions.** Each one should be a real fork in the road —
   not a stylistic preference. The user answering them converts your
   draft from a description into a spec.
6. **Sketch a minimum-viable explicit model** (dataclasses or similar)
   as one possible answer to the open questions. Frame it as one option,
   not the option.

---

## Output template

Save as `MODEL.md` (or similar) in the project. Sections:

```markdown
# Implicit domain model — what the scripts already share

[1-paragraph framing: this is a draft, surfaces what code believes today,
nothing was invented, goal is to argue then write code.]

## The entities the code already touches

[For each entity:
 - one-line description
 - implicit attributes (with where in the code each comes from, mentally)
 - which scripts touch it]

## Where the scripts agree

[Bullet list of cross-script invariants and conventions everyone obeys.]

## Where the scripts disagree (or don't talk to each other)

[Numbered list. Each item is a real friction with a concrete example.
Examples of frictions to look for:
 - missing top-level type that everything operates on but nobody owns
 - schema accretion (different scripts adding different keys ad hoc)
 - domain rules enforced in one place, ignored everywhere else
 - inconsistent failure semantics
 - duplicated validation
 - implicit pipeline ordering
 - shared-vocabulary gaps (UX strings, log messages)]

## Open questions to nail down before writing more code

[Numbered, in roughly the order they affect code. Each one is a real
decision, not a preference. Format: question + the consequence of each
answer.]

## Minimum viable model

[Pseudo-code sketch of the smallest explicit model that resolves the
disagreements. Frame as "one option, open to argument."]

## What I'd want from you before writing code

[Ask for a one-line answer to each open question, or "I don't care, you
pick." That converts the draft into a spec.]
```

---

## What NOT to include

- **Don't invent entities.** If no script references it, it doesn't go in.
- **Don't design future features.** This is archaeology, not architecture.
- **Don't pick a winner among options.** The MVP sketch is one answer to
  argue against, not the answer.
- **Don't write code yet.** The whole point is to align on the model
  before more code amplifies the disagreements.
- **Don't be prescriptive about pipeline order or UX** unless it's
  already implicit in the scripts. Those are separate decisions.

---

## After producing the doc

1. The user reads it and argues with each open question.
2. Their answers convert the draft into a spec (in-place edits to the
   same file are fine).
3. *Then* you write code: either the explicit model + migrate existing
   scripts, or you collectively decide point-tool is fine and just
   document the convention so future scripts don't drift further.

The exercise is not over until either (a) the explicit model exists in
code or (b) the team has consciously chosen to keep the implicit model
and documented why.
