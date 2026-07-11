# House Style — <project name>

The top-level documentation object. Every document an agent or human
authors in this repo follows this index. (Seeded by systems-first-core;
this file is YOURS — edit it as the project's voice evolves.)

## Voice
- Plain prose, complete sentences. Explanations live next to the thing
  they explain, not in a glossary of footnotes.
- Requirement IDs (FR-x.y, UN-XXX, KPM-x.y, IF-x.y) are written exactly;
  the `requirement-id-format` convention checks them.
- Documents state their own status (living / superseded / decided) at the
  top.

## Document classes
Defined in [doc-classes.yml](doc-classes.yml): review-critical docs end as
locked HTML decisions; working docs stay markdown; reports are generated,
never edited. Drafting always happens in markdown.

## Index — templates
| doc type | template | class |
|---|---|---|
| adr | templates/adr.md | working |
| interface-spec | templates/interface-spec.md | working |
| engineer-brief | templates/engineer-brief.md | working |
| impl-plan | templates/impl-plan.md | working |
| design-spec | templates/design-spec.md | review-critical |
| design-review | templates/design-review.md | review-critical |
| system-review | templates/system-review.md | review-critical |
| trade-study | templates/trade-study.md | review-critical |

New doc type with no template? Use the template-writer skill — never
freehand a new document shape.

## Index — conventions
| id | enforce | what |
|---|---|---|
| supersession-banner | blocking | banner format + Archive/ move |
| auto-sections | advisory | AUTO sentinels are sf-docs territory |
| requirement-id-format | advisory | FR/NFR/IF/KPM/UN id syntax |
| docs-impact-matrix | advisory | PR touches X ⇒ must touch Y (fill per project!) |
| locked-decisions | blocking | recorded decisions never change |
| template-format | blocking | templates carry frontmatter |
