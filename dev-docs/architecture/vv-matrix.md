# V&V Matrix — Format Spec

Per the MBSE upgrade path (system review §6.x equivalent — discussed
2026-05-27), every FR / NFR / UN / KPM Issue body carries explicit
verification and validation evidence. This makes the
*requirement → test → KPM* chain machine-readable and renders as a
matrix in `dev-docs/photonforge-architecture.md`.

The matrix is the SysML «verify» relationship in tabular form.

## Definitions

- **Verified By:** the *proof* that the requirement is correctly
  implemented. Usually a unit/integration test or a script.
  Answers: *"how do we know the code does what the requirement says?"*
- **Validated By:** the *demonstration* that the requirement actually
  satisfies its parent user need. Usually an E2E test, KPM measurement,
  or hardware soak. Answers: *"how do we know the requirement was the
  right one?"*

## Issue body format

Add these two sections to the Issue body. Each line is a single
verification or validation source. The grammar is:

```
**Verified By:**
- <kind>: <reference>
- <kind>: <reference>

**Validated By:**
- <kind>: <reference>
```

`<kind>` is one of:

| Kind | Reference shape | Example |
|---|---|---|
| `pytest` | `tests/<file>::<func>` or just `tests/<file>` | `pytest: tests/test_sharpness.py::test_score_is_normalized` |
| `KPM` | `KPM-X.Y` | `KPM: KPM-1.3` |
| `E2E` | `tests/e2e/<file>` or a Stage marker | `E2E: Stage 2 milestone` |
| `soak` | the soak log + cycle target | `soak: KPM-1.4 (50 cycles)` |
| `manual` | a description | `manual: operator confirms zenity dialog appears` |
| `script` | `scripts/<file> <args>` | `script: scripts/check_drift.py` |
| `inspection` | what's inspected | `inspection: PR diff shows no docs/ paths left` |

Blank line ends the section. Other `**Field:**` headings end the
section. Order: `Verified By` always before `Validated By`.

## Per-Issue-type conventions

| Issue type | Verified By | Validated By |
|---|---|---|
| **UN** (user need) | rolls up from its FR/NFR/IF children (no direct entry) | one E2E or observable check that proves the need is met for a real user (you) |
| **FR** (functional) | one or more `pytest` lines | the KPM or E2E that touches this code path |
| **NFR** (non-functional) | usually a `script`, `inspection`, or `pytest` line | the KPM (most NFRs constrain a measurable property) |
| **KPM** | the benchmark script + its assertion (`pytest` or `script`) | (KPMs are self-validating — leave Validated By empty or `N/A`) |

## Rendering

`scripts/generate_docs.py` walks all Issues with `type: fr`,
`type: nfr`, `type: kpm`, `type: user-need`, parses these two
sections, and renders a V&V matrix into
`dev-docs/photonforge-architecture.md` between the
`<!-- AUTO:vv_matrix -->` sentinels.

A requirement with empty Verified-By is flagged `⚠ unverified` in the
rendered matrix — useful for finding the next test to write.

## Example (FR-1.4)

```markdown
**Implementation:** Normalized Laplacian Variance

**Parent UN:** UN-012

**Verified By:**
- pytest: tests/test_sharpness.py::test_sharp_image_scores_high
- pytest: tests/test_sharpness.py::test_blurry_image_scores_low
- pytest: tests/test_sharpness.py::test_score_is_normalized
- pytest: tests/test_sharpness.py::test_missing_image_returns_zero

**Validated By:**
- E2E: Stage 2 milestone — sharpness column populated in library.db
```

## Migration

Roll out per stage as the Issues for that stage stabilize. Stage 2
(Core Engine) and Stage 4 (Host Integration) are good starting
points — both have landed code and tests, so the V&V lines write
themselves. Stage 6 (scoring redesign) is in flight, so its V&V
lines will land alongside each step of the migration checklist.
