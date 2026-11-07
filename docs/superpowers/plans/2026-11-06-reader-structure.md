# Source-reviewed reader structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Preserve the existing direct implementation preference; no per-task delegation or repeated approval loop.

**Goal:** Repair the approved definition/list findings and regenerate PKCE without weakening preservation checks.

**Architecture:** Add optional `structure` to reader-review schema 1.0. Resolve and validate structural selections before wrappers alter positional selectors; apply trusted structure after source sanitation. Separate reviewed lists express separate record groups. Keep existing `list_items` behavior when `structure` is absent.

**Tech Stack:** Existing Python, BeautifulSoup, pytest and Playwright; no dependencies added.

**Spec:** docs/superpowers/specs/2026-11-06-reader-structure-design.md

## Global Constraints

- English CS terms, 18px/16px prose, 1.75 line height, and exact literal/link/ID/hash protection stay.
- Old review files and accepted outputs remain usable and unchanged. Python never translates; no RFC-, phrase-, or site-specific production branches are permitted.
- Do not modify PDF processing, publish sites, or translate other RFCs in this change.
- Commit and immediately push each implementation commit. Candidate-runtime regeneration is not a plugin release or marketplace update.

## Review Focus

- A definition boundary inside an existing link/emphasis subtree must be rejected rather than splitting the subtree; a boundary between intact subtrees must preserve them.
- Invalid depths (including bools), duplicate/overlapping selectors and reordered or non-contiguous items must fail without publishing output.
- Empty anchor spacers remain intact; nonempty prose, headings and literal blocks must not be swallowed by a list.
- Original positional text-edit and presentation selectors must resolve before any new wrapping; source-supplied classes/markers must not impersonate reviewed structure.
- Old `list_items` and native HTML definitions/lists must keep their existing behavior; nested children and long definition labels must remain readable at 390px.

---

### Task 1: Explicit structure with exact-content preservation

**Files:** Create `src/supertranslator/reader_structure.py`; modify `src/supertranslator/reader.py`, `src/supertranslator/web_assets/reader.css`, `tests/test_reader.py`, `README.md`.

**Interfaces:** Optional review field:

```json
{
  "structure": {
    "definitions": [{"selector": "#definition", "term_end": 13, "evidence": "Source-reviewed name/description boundary"}],
    "lists": [{"items": [{"selector": "#parent", "depth": 0}, {"selector": "#child", "depth": 1}], "evidence": "Source-reviewed hierarchy"}]
  }
}
```

`term_end` is a Python-character offset in the selected paragraph's exact text after approved text edits; no stripping/normalization or inferred separator. Each list starts at depth 0; a following item increases by at most one. Both arrays and all object fields are validated strictly. Definitions/lists cannot overlap each other, old `list_items`, archived source notes or a native/ARIA item owner; refuse those unsupported combinations instead of silently reshaping existing lists. Select only live flat-inline `p`/`div` blocks. All members of each list share a parent and follow document order with only whitespace/empty-anchor spacers between them.

Produce `resolve_structure(article: Tag, review: dict) -> ResolvedStructure` and `apply_structure(article: Tag, resolved: ResolvedStructure) -> None` in the new module. Resolve after existing joins/text edits and presentation selection, before old list grouping/sanitization. Apply after sanitization, before presentation output; retain exact-preservation comparisons. A definition keeps its container ID and uses a generated definition layout with term/description elements; the boundary may split a direct text node but never an inline subtree. List wrappers use ARIA list/listitem containers around the original intact blocks, nesting child lists inside the previous parent item, without inventing numeric markers. Store `structure` in the output manifest; the existing review/render hashes cover it and its output.

- [x] Add real-export tests using the existing `bundle` fixture and hand-authored HTML. `test_reviewed_definition_separates_term_without_changing_text_or_inline_links` asserts label/description containers, their exact text, unchanged link attributes/IDs, and literal text. `test_reviewed_lists_keep_child_under_parent_and_groups_separate` asserts a two-level hierarchy, a second separate group, original item order/markers and exact text. Run these first and observe failure from the currently unsupported `structure` field.
- [x] Add rejection cases for split-inside-inline boundaries, empty/out-of-range/bool offsets, empty term/description, malformed arrays/objects, empty/duplicate selectors, overlapping definitions/lists/old selections, native-owner selections, depth jumps/bools/negative depths, reversed or non-contiguous members, archived/furniture selections and block descendants. Assert no output directory is published. Add positive cases for an intact inline term, empty anchor spacers, a return to a shallower list depth and positional text edits/presentation selection. These tests pin all five Review Focus items.
- [x] Implement the two named interfaces and integrate the optional field in schema validation and manifest output. Preserve old behavior when absent. Use trusted resolved element identities, not source-provided marker/class names, to authorize new structure.
- [x] Add scoped styles for generated definitions and list groups only. Keep existing prose/native-list styles; make long terms stack above descriptions on mobile. Add real browser assertions for term/description separation, deeper child indentation, group gaps, minimum 16px font and absence of document overflow at 1440/768/390px; existing native/legacy-list tests must pass unchanged.
- [x] Document the optional JSON field and offset semantics in README. Run `.venv/bin/python -m pytest tests/test_reader.py -q`, then `.venv/bin/python -m pytest -q`; report any environment failures explicitly. Review the final diff for preservation and schema compatibility. Commit the implementation, tests and design/plan docs, then immediately push its feature branch; do not merge main implicitly.

### Task 2: Qualification example and actual PKCE verification

**Files:** Modify `skills/supertranslator-web/references/review-rubric.md`; create fresh PKCE review/output/evidence under `translated-pages/`; leave all previously accepted PKCE files untouched.

**Interfaces:** Consume Task 1 `structure` and existing `text_edits`, `export-reader`, `qa-reader` contracts. Use the accepted PKCE translation bundle as input; the existing source-bound text edit records the AI-authored §6.2.1 correction and its original-language evidence. No second full translation is claimed.

- [x] Read the applicable skill-authoring instructions before changing agent-facing review instructions. Add a short contrasting example showing that persuasive grounds are not necessarily unavoidable grounds, while retaining CS noun policy. Check the consuming AI's judgment on this error and on an unchanged valid condition; do not use a source-text grep as a quality test.
- [x] Build/install a local candidate wheel into an isolated runtime and verify its provenance and packaged CSS. Create a new reader-review with explicitly inspected definition offsets, nested condition items and separate registration groups. Author the exception correction as an exact-input-bound `text_edit`; validate it using the unchanged English/numeric/inline protections.
- [x] Export to an unused PKCE directory and run initial `qa-reader`. Compare all original/translated blocks and protected literals; inspect every generated screenshot tile at all three widths, with focused before/after definition/list views. Write new exact-render-hash visual evidence only after inspection and rerun final QA. Preserve old-output checksums and record which runtime produced the candidate. A remaining required finding prevents a success claim.
- [x] Record tests, corrected/unchanged content, screenshots and any deferred minor issues in a concise review report. Review/commit/push the rubric change after verification. Do not bump or publish a plugin release, update marketplace pins, replace public pages or merge main unless separately authorized.

## Self-review

The approved goals map to Task 1 structure preservation and Task 2 semantic/actual-output review. No new extraction inference, PDF engine or publication workflow is introduced. The two structure interfaces have the same names/types in every step. User approved execution on 2026-11-07. The final reviewer identified one minor test gap: the presentation-overlap case rejects an invalid TOC target before reaching the intended new guard; production behavior was independently verified with a valid target. This test refinement is deferred, not claimed covered.

## Execution result — 2026-11-07

- Task 1 implemented and independently reviewed: source/installed reader runs each 128 passed; full suite 3354 passed, 15 skipped, 2 deselected. Implementation commit `b9eda02` pushed immediately.
- Task 2 reference example applied by a fresh AI reviewer to three contrasting cases; local installed candidate generated into a fresh PKCE folder. Full text differs only by the approved AI exception correction; literals and156 prior files unchanged. All22 viewport tiles personally inspected; exact-render-bound final QA passed.
- One minor test refinement and pre-existing editorial polish remain deferred. See `../specs/2026-11-07-reader-structure-verification.md` for evidence, execution rulings and limits.
- No merge, plugin release, marketplace update or public-site change performed. Local candidate provenance explicitly distinguishes it from released0.10.2.
