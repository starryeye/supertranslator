# Legacy Web Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Finish the existing OIDC Discovery translation and fix the two generic web compatibility defects it exposed.

**Architecture:** Add responsive CSS only to final HTML without changing the held projection. Accept and preserve actual browser fragment destinations in the reading edition.

**Tech Stack:** Python, Beautiful Soup, pytest, Playwright Chromium.

**Spec:** [Legacy web layout compatibility](../specs/2026-11-14-legacy-web-layout-design.md)

## Global Constraints

- No changes to the capture, projection and its CSS, translations, or semantic evidence.
- No relaxed QA, release, or public posting. Use new output directories.

## Review Focus

- Narrow viewport fit and inner code scroll without desktop changes (Task 1).
- Wrong, duplicate, misplaced, or ineligible generated CSS does not bypass integrity checks (Task 1).
- Ordinary assembly without a projected wrapper remains unchanged (Task 1).
- Percent-encoded names resolve; missing names and names on non-anchor tags do not (Task 2).
- Generated navigation cannot shadow legacy names; duplicate IDs remain errors (Task 2).

### Task 1: Responsive source-layout fallback

**Files:** `src/supertranslator/assemble.py`, `src/supertranslator/web_content.py`, `src/supertranslator/qa.py`, `tests/test_preformatted_pipeline.py`, `tests/test_web_content.py`.

**Interface:** `assemble_page` emits a final direct head style tagged `data-wt-mobile-layout="preformatted"` when an inline table-formatted div contains a direct projected root. Output QA validates the exact generated style against the source-bound contract before comparing DOM content and normalizes its position for head-owner correspondence.

- [ ] Add `test_projected_fixed_width_wrapper_passes_mobile_qa`: no document overflow at 390px, literal scrolls within its own box, wrapper display stays table at 1440px, and source/projection/assets and literal bytes are unchanged. Run before implementing; expect the viewport gate to fail.
- [ ] Add `test_mobile_layout_style_is_exact_and_source_bound`: changed, duplicate, moved, and ineligible styles fail integrity; absence is still subject to ordinary QA. Ordinary assembly does not add the marker.
- [ ] Append a deterministic source-derived style only to eligible output, using fixed declarations and exact escaped selectors for eligible inline styles. At 768px and below allow long inline text to wrap and the qualifying wrapper to use block sizing. Recompute the exact style from the held source before removing it for source-output comparison.
- [ ] Run the new tests and `pytest tests/test_assemble.py tests/test_qa.py tests/test_preformatted_pipeline.py tests/test_web_content.py`.

### Task 2: Preserve legacy fragment targets

**Files:** `src/supertranslator/reader.py`, `src/supertranslator/reader_layout.py`, `src/supertranslator/reader_qa.py`, `tests/test_reader.py`.

**Interface:** `_preserved` inventories legacy names; `qa_reader` checks decoded fragment strings against IDs and names; navigation reserves both namespaces before generating IDs.

- [ ] Add `test_reading_edition_resolves_legacy_named_anchors` with percent-encoded, missing, and non-anchor variants. Extend navigation collision coverage to an `a[name]`. Run before implementation; valid legacy variants must fail initially.
- [ ] Recognize and protect nonempty `a[name]` without renaming targets or accepting duplicate IDs. Run `pytest tests/test_reader.py`.
- [ ] Review both diffs and test evidence, then commit in the repository's existing style and immediately push the current branch.

### Task 3: Finish the existing document

- [ ] Reassemble from the held capture and review into a new source-layout folder. Run normal QA and verify the unchanged approval digest and seven exact example blocks.
- [ ] Use supertranslator-render to export a new reader from the QA-passed bundle. Inspect browser screenshot tiles and compare against the original, then bind the visual review only to the checked edition. Keep the run incomplete if either gate fails.
