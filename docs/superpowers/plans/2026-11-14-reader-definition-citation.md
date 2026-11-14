# Readable Definitions and Citation Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OIDC Discovery reading edition readable without changing its 471 approved translations.

**Architecture:** Bound the label width in the shared reader stylesheet. Add an optional exact-input-bound citation selection that relocates only reviewed trailing detail text to script-free inline disclosures, while keeping links and all other protected content intact.

**Tech Stack:** Python 3.11+, Beautiful Soup, CSS, native HTML popover, pytest, Playwright Chromium.

**Spec:** [Readable definitions and citation details](../specs/2026-11-14-reader-definition-citation-design.md)

## Global Constraints

- Reuse the QA-passed source-layout bundle unchanged; no retranslation, new semantic approval, modification of prior outputs, or publication.
- No new dependency, scripted controls, source-authored controls/CSS, or weakened CSP or QA. Commit accepted tasks in the existing style and immediately push to the current feature branch.
- No change to old review JSON requirements. A fresh revision must pass both browser and visual QA.

## Review Focus

- Long native definition terms must leave at least half of the available definition-list width to the description; short labels and mobile stacking retain their current behavior (Task 1).
- Source-authored controls, malformed or repeated selectors, non-trailing detail, and detail with nested semantics must not become disclosures (Task 2).
- Visually hidden detail must still exist once in the output, and neither original citation navigation nor existing IDs/names may change (Task 2).
- A keyboard user and a touch user must be able to reveal the detail and still follow the citation link with no script (Task 2).
- A new candidate must not inherit the old visual evidence even though it reuses semantic approval (Task 3).

### Task 1: Bound definition-list term width

**Files:** `src/supertranslator/web_assets/reader.css`, `tests/test_reader.py`.

**Interface:** Native `dl/dt/dd` and existing `.st-definition` remain unchanged in the HTML. Desktop native definition lists keep two columns; the term track is bounded to 40% with wrap-friendly items, and when the layout is narrow the existing stacked styles still apply.

- [ ] Add `test_native_definition_list_leaves_readable_description_width` with an ordinary glossary and a list containing a long single-token term. At 1440px and 768px verify the compact term track is smaller, the long-list description uses at least half the list width, and text is not clipped. At 390px verify the description is below the term. Run before implementation; expect the long-term width assertion to fail.
- [ ] Update only native definition CSS to cap the term track and enable wrapping without resizing all compact lists; keep the existing mobile rule. Check actual element bounds, not just stylesheet strings.
- [ ] Run the regression and `tests/test_reader.py`. Review, commit, and immediately push.

### Task 2: Add explicitly reviewed citation disclosures

**Files:** `src/supertranslator/reader.py`, new `src/supertranslator/reader_citations.py`, `src/supertranslator/web_assets/reader.css`, `tests/test_reader.py`, `README.md`, `skills/supertranslator-render/references/html.md`.

**Interface:** Add optional top-level `citation_details`, a list of objects with exactly `selector` (one anchor), `detail_selector` (matching one or more of that exact anchor's trailing direct child spans), and `detail_sha256` (SHA-256 of the concatenated exact detail text, encoded UTF-8). Missing or empty leaves existing rendering unchanged. Resolve before structural wrapping/sanitization; apply after existing presentation and preservation checks, contracting no other comparison.

- [ ] Add `test_reader_citation_details_preserve_link_and_exact_detail`: original destination, non-detail link text and inline labels unchanged, exact detail appears once in output, safe generated ID avoids preexisting IDs and legacy names, and standalone/fragment agree. Include a neighboring untreated citation and old reviews. Expect export to reject the new field before implementing.
- [ ] Add `test_reader_citation_details_reject_invalid_source_selection`: stale hash, duplicate anchor, missing/ambiguous anchor, no visible label, non-trailing selection, nested nodes or destination-bearing/hidden detail, protected literal/foreign/inert/archive ancestor, and source-authored control. Assert no output on failure. Plain-text detail spans may have source classes, but no other attributes. Preserve source whitespace inside selected detail nodes; no generated copy of the original details remains inside the link.
- [ ] Add `test_reader_citation_popover_works_with_keyboard_and_touch` with actual Chromium default-hidden state, focus and Enter, tap, dismissal, and independent citation navigation, under the standalone CSP. Ensure the generated button and detail still work in the embedded article; no script or external dependency.
- [ ] Implement `resolve_citation_details(article: Tag, selections: list)` and `apply_citation_details(article: Tag, resolved, source_url: str) -> None`. Capture the protected inventory immediately before applying, retain unchanged links byte-equivalently after normalization, and verify only the reviewed anchors' exact text inventory entries change as specified, with a one-to-one mapping to exact new disclosure text. Generated IDs use `st-citation-0001` onward, avoiding IDs and legacy names. Generate controls after source sanitization with explicit `type="button"` and contextual accessible labels; leave link attributes/destination unmodified by this transformation. Scope compact button and width-limited popover CSS to reader-generated controls.
- [ ] Document the optional field and its bounds. Run `tests/test_reader.py tests/test_render_workflow.py`, review prior compatible exports/fixtures, commit and immediately push.

### Task 3: Regenerate and visually review OIDC Discovery

- [ ] Derive 107 exact selections and their detail hashes from the unchanged approved source-layout bundle; retain all existing title, heading, and archival decisions. Export through `supertranslator-render` into a new directory.
- [ ] Run `qa-reader` at 1440/768/390px, inspect all fresh tiles and open disclosure states, and measure actual definition-list width. Check original links and code examples and verify new output uses the same input and approval bytes. Require a new visual record bound to the new reader digest before marking passed. Report limitations and push status; do not merge, publish, or start another document.
