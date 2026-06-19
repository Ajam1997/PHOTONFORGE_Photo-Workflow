# PHOTONForge Darktable Plugin — GUI Polish Brief (Release 1)

**Audience:** Claude Design (GUI prototyping)
**Author:** software_lead research, 2026-06-19
**Goal:** Polish the visual design and information architecture of the PHOTONForge
Darktable lib panel for the Release-1 cut, *within the hard constraints of the
Darktable Lua widget API and GTK3 CSS*. The output of the prototype must be
mechanically translatable into `dt.new_widget(...)` calls + a GTK3 CSS theme.

---

## 0. The one thing to internalize first

This is **not** a web UI. There is no HTML, no DOM, no flexbox/grid, no custom
components, no JS. The panel is a fixed set of GTK widgets created from Lua,
arranged in nested horizontal/vertical boxes, and styled with a **subset of
GTK3 CSS**. A mockup that assumes web layout primitives is unbuildable. Design
*inside the envelope* described in §2–§4. When in doubt, prefer fewer, larger,
clearly-grouped controls over dense custom layouts.

---

## 1. Current state (what exists today)

The panel (`lua/photonforge/panel.lua`) is a single left-dock lib registered in
the lighttable view (`DT_UI_CONTAINER_PANEL_LEFT_CENTER`). Top-to-bottom it is a
flat vertical box containing:

1. **Config paths** (3 rows): `label + entry + "..." browse button` for SD path,
   Destination, Corpus JSONL.
2. **TZ offset** (label + entry).
3. **Run mode** combobox (resume / force / fresh).
4. **File type** combobox (both / raw / jpg).
5. **Pipeline steps**: 5 `check_button` rows (ingest, import, dedup, score, name),
   each with a "last: <timestamp ✓/✗>" label beside it.
6. **Action buttons** (8 total), partially grouped:
   - `▶ Run PHOTONForge` + `■ Stop` (one row)
   - `↥ Sync Tags → DT`
   - `✨ Suggest Training Set`
   - `↻ Refresh Review Flags`
   - `⇅ Collect Corrections`
   - `★ Recalibrate` + `↻ Full Correction Loop` (one row)
7. **Progress label** (single line of text, e.g. `score: 12/40`).
8. **Log view** (read-only `text_view`, 200-line ring buffer).

### Known UX problems to solve
- **Flat wall of controls** — 8 buttons + 4 inputs + 5 checkboxes + log, no
  visual hierarchy or grouping. New users can't tell the primary action (Run)
  from the advanced training-loop actions.
- **Two distinct workflows are intermixed**: (a) the *ingest→name pipeline* and
  (b) the *correction/training loop* (Suggest → Collect → Recalibrate → Rescore).
  These should be visually separated.
- **Progress is a bare text line** — no sense of activity or stage.
- **Status glyphs** (✓/✗) and emoji-prefixed labels are inconsistent and
  unstyled.
- **No empty/first-run guidance** — panel looks identical whether configured or not.

---

## 2. The buildable widget palette (your component library)

Every widget below is created via `dt.new_widget("<type>"){...}`. This is the
**complete** set — there are no others.

| Widget | Use for | Key attributes |
|---|---|---|
| `box` | layout only (h or v) | `orientation` ("horizontal"/"vertical"), children |
| `label` | static text | `label`, `ellipsize`, `halign` |
| `section_label` | titled divider (renders with a rule/border) | `label` |
| `separator` | thin divider line | — |
| `button` | action | `label`, `tooltip`, `clicked_callback`, `sensitive` |
| `check_button` | boolean toggle | `label`, `value` |
| `combobox` | pick-one dropdown | `label`, `value`, list items, `changed_callback` |
| `entry` | single-line text input | `text`, `tooltip`, `is_password` |
| `file_chooser_button` | native folder/file picker | `title`, `value`, `is_directory` |
| `slider` | numeric value | `soft_min/max`, `hard_min/max`, `step`, `digits`, `label` |
| `stack` | **show ONE child at a time** | `active` child — basis for tabs/wizard |
| `text_view` | multi-line text (log) | `text`, `editable` |

**Shared by all widgets:** `name` (the CSS hook — your only per-widget styling
handle), `sensitive` (enable/grey-out), `visible` (show/hide), `tooltip`,
`reset_callback`.

### Structural levers you DO have
- **`stack`** = tabs / wizard steps / collapsible sections. Switch the visible
  child with a combobox or a row of buttons. This is the single biggest tool for
  taming the flat layout — e.g. a "Pipeline" tab vs an "Training" tab.
- **Nested boxes** = arbitrary grouping and rows/columns.
- **`section_label` + `separator`** = visual grouping and hierarchy.
- **`sensitive`/`visible`** = progressive disclosure (grey out Stop until running;
  hide training actions until a corpus path is set).

---

## 3. The styling envelope (GTK3 CSS)

Styling is done in a `.css` theme file (bundled with the plugin or merged into
`~/.config/darktable/user.css`). You target widgets by their `name` attribute.
GTK3's CSS engine supports a **subset** of web CSS.

### Supported
- Selectors: by widget `name`, by GTK node/class, pseudo-classes `:hover`,
  `:disabled`, `:checked`, `:focus`
- `color`, `background-color`, `background-image` (SVG/PNG, incl. icons)
- `font-family`, `font-size`, `font-weight`; helper class `dt_monospace`
- `border`, `border-radius`, `border-color`, `outline`
- `padding`, `margin`, `min-width`, `min-height`
- `box-shadow`, `opacity`, `text-shadow`
- **darktable theme variables** so the panel matches the active theme:
  `@bg_color`, `@fg_color`, `@plugin_bg_color`, `@bauhaus_fill`, grey ramp
  `@grey_00 … @grey_100`
- **darktable helper classes:** `dt_section_label`, `dt_transparent_background`,
  `dt_dimmed`, `dt_monospace`, `dt_bauhaus` (native slider/combo look),
  `dt_no_hover`

### NOT supported — do not design around these
- ❌ No flexbox, grid, `position:absolute`, float, or any web layout engine —
  layout is **only** nested h/v boxes
- ❌ No custom/novel widgets, no canvas, no SVG-in-DOM, no web components
- ❌ No image thumbnails or photo grid inside the panel
- ❌ No real progress **bar** widget (only a text label today) — if a bar is
  desired, the closest buildable approximation is a styled label or a row of
  small fixed boxes; flag any such idea explicitly as "approximation"
- ❌ No tables / data grids / sortable lists
- ❌ No rich text, no inline links, no tooltips with markup beyond plain text
- ❌ No CSS transitions/animations that the design *depends on* (GTK has limited
  transition support; treat motion as nice-to-have, never load-bearing)
- ❌ Panel is a **narrow fixed-width vertical column** (~250–350 px) in a side
  dock, NOT a free-floating resizable window. Design for a tall, narrow strip.

---

## 4. Design goals for Release 1 (the actual ask)

In priority order:

1. **Establish hierarchy.** Make the *primary* path (configure → enable steps →
   Run) visually dominant. Demote the 5 training/correction actions to a
   clearly secondary, collapsible/tabbed area.
2. **Separate the two workflows.** Pipeline (ingest→name) vs. Correction Loop
   (Suggest→Collect→Recalibrate→Rescore). **DECIDED:** use a `stack` with two
   tabs — "Pipeline" and "Training" — switched by a row of two buttons (or a
   combobox) at the top of the panel. The shared config-paths block stays above
   the tab switch (both workflows need it).
3. **Clarify state.** Configured vs. unconfigured, idle vs. running, last-run
   success/failure per step — using only color, `section_label`, `sensitive`,
   icons, and text.
4. **Tidy the action buttons.** Consistent iconography (CSS background-image SVGs
   instead of inline emoji), consistent sizing, primary-button emphasis on Run.
5. **Make progress legible.** Improve the single progress line; propose (and
   label as approximation) any pseudo-progress-bar.
6. **Theme-coherent.** **DECIDED:** style with darktable theme variables /
   helper classes ONLY (`@bg_color`, `@fg_color`, `@plugin_bg_color`, grey ramp,
   `dt_section_label`, etc.) — no bundled custom skin. The panel must look native
   in whatever theme the user runs (light and dark defaults). Accent/emphasis
   must come from existing theme vars, not hard-coded hex colors.

### Explicit non-goals for R1
- No new functionality / no new pipeline steps — **visual + IA polish only**.
- No redesign of the underlying CLI or runner.

---

## 5. Deliverables requested from Claude Design

1. **Annotated layout mockup** of the polished panel (tall narrow column),
   showing the proposed hierarchy, grouping, and any `stack`/tab structure.
   Annotate each region with the **DT widget type** it maps to (from §2).
2. **A second mockup of any secondary state** (e.g. running/in-progress, or the
   Training tab) — because state is conveyed only by `sensitive`/`visible`/color.
3. **A styling spec**: the named CSS hooks (proposed `name` values per widget)
   and the GTK3-CSS rules for each (colors via theme vars, padding, borders,
   icon backgrounds, hover/disabled states). Stay inside §3 "Supported".
4. **Icon list**: which SVG glyphs are needed for which buttons (to replace the
   emoji), as simple monochrome symbolic SVGs that recolor via CSS.
5. A short **"buildability notes"** section flagging anything in the mock that is
   an approximation of an unsupported capability.

### Format
HTML/CSS prototype is fine **as a visual reference only** — but it must be
explicitly mapped back to the §2 widget palette and §3 CSS subset. Treat the
HTML as a picture of the end result, not the implementation. Every visual
element must answer: "which `dt.new_widget` builds this, and which GTK3-CSS rule
styles it?"

---

## 6. Reference

- Widget API: https://docs.darktable.org/lua/stable/lua.api.manual/types/lua_widget/
- Lua scripting manual: https://docs.darktable.org/usermanual/development/en/lua/
- darktable theming/CSS internals: https://deepwiki.com/darktable-org/darktable/5.3-theming-and-css-styling
- GTK3 supported CSS properties: https://docs.gtk.org/gtk3/css-properties.html
- Community CSS theme playground: https://darktable-css.danielepighin.net/instructions
- Current implementation: `lua/photonforge/panel.lua`
