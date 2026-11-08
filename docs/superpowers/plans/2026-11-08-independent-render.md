# Independent Render Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (the user's preserved execution method) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `supertranslator-render` for reusing approved translation without reacquisition, extraction, or AI translation.

**Architecture:** Reuse existing HTML `export-reader`/`qa-reader` and native PDF assembly/QA. A small PDF preparation command copies validated inputs to a fresh allocated run because an old run's `staged-output` and `layout.json` intentionally prevent reassembly. Neither this skill nor its helpers invokes the independent comparison-review skill.

**Tech Stack:** Existing Python >=3.11 package, argparse, pytest, Playwright, ReportLab/Poppler; plugin Markdown skills. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-08-independent-render-review-design.md` (approved 2026-11-08).

## Global Constraints

- Preserve existing runs, outputs, translation bytes, semantic/figure approvals, and exact checks. Never copy old visual approval into a new revision.
- No implicit retranslation, source reacquisition/re-extraction, approval creation, or website publication.
- Keep web/PDF translation entrypoints and existing QA; do not invoke `supertranslator-review`.
- Use supported current layout operations/current installed renderer only. New font/spacing controls, arbitrary CSS injection, and the five PKCE presentation fixes are not included in this skill-exposure change.
- The managed worktree is currently detached. At execution time use the worktree skill's native branch/handoff procedure before committing; do not overwrite local main or user work. Every commit must be pushed immediately; report a push blocker rather than claiming remote delivery.
- Read skill-creator, writing-skills (including its linked discovery/testing guidance), and the relevant existing code before implementing. Behavioral skill tests precede authoring.

## Review Focus

1. Completed PDF runs already contain staging: new revision must leave the old entire tree unchanged.
2. Post-approval translation, unit-map, figure, or glossary changes: refuse reuse, never re-sign them.
3. Linked/reparse/replaced paths, destination collisions, and copy failure: no clobber or partial usable run.
4. HTML positional edits/joins and final reader bundles: reuse the correct original bound bundle/review; do not apply old edits twice.
5. Unsupported layout requests or missing evidence: return a precise limitation without silently starting translation or full comparison review.

---

### Task 1: Fresh PDF render-input preparation

**Files:** Create `src/supertranslator/pdf_render.py`, `tests/test_pdf_render.py`; modify `src/supertranslator/cli.py`, `.github/workflows/pdf-cross-platform.yml`.

**Interfaces:**
- Consumes existing `hold_pdf_semantic_inputs`, `validate_pdf_semantic_review_snapshot`, `hold_pdf_figure_inputs`, figure approval validation, report semantic-review parsing, and anchored filesystem primitives. Reuse validators; do not fork the PDF contract.
- Produces `prepare_pdf_render(input_run_dir: Path, run_dir: Path, output_dir: Path) -> Path`, returning the prepared `run_dir`; `PdfRenderError(ValueError)` for refusal.
- CLI: `prepare-pdf-render --input-run-dir <old-run> --run-dir <new-allocated-run> --output-dir <new-reserved-output>`. Success exit 0, contract refusal exit 4 (`EXIT_CONTRACT_FAILURE`). Include the command in `_command_output_root`'s PDF set and retain the normal held allocator contract, not the reader-command bypass.

- [ ] **Step 1: Write failing behavior tests.** Use `tests.pdf_unit_fixtures.run_native_unit_pipeline` for a real completed native run (its translations/approvals are explicitly synthetic). Write `test_prepares_completed_pdf_for_new_render_without_changing_old_run` asserting full old-run/output inventories and bytes unchanged; destination semantic digest and `review.json` bytes identical; source PDF and figure media bytes identical; no `staged-output`, `layout.json`, `pdf-qa.json`, `pdf-layout-review.json`, or `qa-pages` copied. Assembly of the prepared run must work without acquire/extract/planning/translation. Assert `pdf-qa finalize` cannot succeed before fresh visual evidence.
- [ ] **Step 2: Add refusal tests.** `test_prepare_refuses_changed_approved_inputs` parametrizes translations, document/unit binding, glossary, review, source PDF, figure inventory/media (include a source figure case). `test_prepare_refuses_nonempty_or_overlapping_destination` covers existing files, equal/nested source, and a reserved output collision. `test_prepare_rejects_linked_inputs_and_replacement` covers source/destination ancestors, a linked input child, and replacement during publication; include native Windows reparse coverage where available. `test_prepare_failure_leaves_no_usable_partial_run` injects a copy/publication failure and verifies no input marker set is accepted, no unrelated sentinel removed, and all source bytes preserved. Repeat successful paths with spaces and Korean directory names.
- [ ] **Step 3: Run** `<PYTHON> -m pytest tests/test_pdf_render.py -q`. Confirm missing command/function behavior fails for the intended reason, not fixture/import errors.
- [ ] **Step 4: Implement minimal preparation.** Validate source semantic/figure approval and unresolved findings while holding inputs and `review.json`; validate source PDF hash even without artwork. Copy the held approved semantic payloads, exact `review.json`, `source.pdf`, and required media only. Preserve all binding/digest bytes; copying is not a new approval. Do not copy stages, QA, page renders, old layout, source decisions not needed for consumption, or unknown children. Use an owned temporary child and existing no-clobber/identity-checked primitives; validate the staged copy before publication and revalidate held source at publication. Keep partial publication unusable, clean only owned temporary files, and propagate errors. Do not use recursive `copytree` over arbitrary run contents or resolve linked paths.
- [ ] **Step 5: Wire CLI and verify real consumption.** Implement `_prepare_pdf_render_command(args: argparse.Namespace) -> None`; map `PdfRenderError` to `CLIContractError`. The CLI must pass an empty destination through the normal allocated-run identity checks. Extend native PDF CI's test selection with `tests/test_pdf_render.py`. Run `<PYTHON> -m pytest tests/test_pdf_render.py tests/test_cli_contract.py tests/test_pdf_pipeline.py -q`; confirm native figure/free and figure-bearing preparation and fresh assembly pass, while stale approvals remain refused. Capture actual renderer output, not a mocked assembler's success.
- [ ] **Step 6: Review, commit, immediately push.** Independently review this helper and its failure behavior before moving to the skill task. Suggested commit: `feat: prepare approved PDF inputs for independent rerendering`.

### Task 2: Render skill, discovery, and honest behavioral validation

**Files:** Create `skills/supertranslator-render/SKILL.md`, `skills/supertranslator-render/references/html.md`, `skills/supertranslator-render/references/pdf.md`, `tests/test_render_workflow.py`; modify `tests/test_plugin_layout.py`, `README.md`, `.codex-plugin/plugin.json` descriptions only if needed for discovery.

**Interfaces:** Consumes Task 1 command and unchanged `export-reader`, `qa-reader`, `pdf-assemble`, `pdf-qa prepare/finalize`. Produces a discoverable plugin skill, not a new general render API or settings schema. References are format-specific and loaded only for the selected format.

- [ ] **Step 1: Run bounded pre-skill behavioral controls.** In separate temporary workspaces, give fresh agents real requests to rerender an already finished PDF and edit an existing HTML reader, plus missing/stale evidence and a request requiring translation changes. Supply raw artifacts/current tools only, not expected answers. Record actual stage choices and mutations. Test the previously observed unsafe shortcuts (restarting translation, overwriting old output, or inventing approval); do not fabricate failures. Apply writing-skills' no-guidance controls and five-repetition wording checks where a shaping rule is justified.
- [ ] **Step 2: Write failing integration tests.** `test_html_render_reuses_bound_bundle_once` reuses the `bundle` fixture from `tests.test_reader` and verifies two exports to different output directories preserve source bytes, literal/link facts, and exactly-once existing editorial edits. A second-generation reader must trace back to its bound input rather than blindly re-exporting the reader with old selectors. `test_pdf_render_reuses_exact_semantic_approval_but_requires_fresh_visual_review` drives Task 1 through the documented command sequence. Extend the plugin-layout test to discover the render skill in addition to existing skills; do not require review to be present yet.
- [ ] **Step 3: Run** `<PYTHON> -m pytest tests/test_render_workflow.py tests/test_plugin_layout.py -q`; identify the expected missing skill/integration failure.
- [ ] **Step 4: Author the skill and two focused references.** Frontmatter trigger: user requests layout-only editing or rerendering an existing reviewed HTML/PDF, not initial translation or source-to-result full comparison. Explain locating the approved input, supported current settings versus unsupported requests, platform-native interpreter invocation, new output revision, integrity/QA gates, and normal completion artifacts. HTML uses bound original bundle plus reviewed layout instructions; PDF uses Task 1 then existing assembly/QA and fresh required visual inspection. Retain valid historical AI text edits exactly once; do not create new wording edits. A final artifact without needed private inputs is a diagnostic, not permission to reacquire or translate. Neither reference routes to `supertranslator-review`.
- [ ] **Step 5: Run the same bounded behavioral scenarios with the skill.** Verify actual files/output and input fingerprints, not the agent's self-reported compliance. Fresh visual approval in synthetic tests must be explicitly test-only; agents must not produce professional acceptance evidence they did not inspect. Test that normal successful rendering does not launch the independent comparison review. Test an impossible change returns a limitation and preserves all inputs.
- [ ] **Step 6: Validate** `<PYTHON> /Users/starryeye/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/supertranslator-render`; run `<PYTHON> -m pytest tests/test_render_workflow.py tests/test_plugin_layout.py tests/test_skill_contract.py tests/test_reader.py tests/test_pdf_render.py -q`. Add README examples clearly distinguishing initial translation, rerender, existing QA, and separately requested full review.
- [ ] **Step 7: Independently review, commit, immediately push.** Suggested commit: `feat: add independent HTML and PDF render skill`.

## Handoff and completion

- [ ] Self-review this plan against the spec before handoff. It covers reuse/refusal, no-clobber, exact approval, formats, user routing, and independent review exclusion; does not implement unrelated PDF layout features.
- [ ] After user plan approval execute through the existing subagent-driven method. Read the companion review plan separately; it adds no runtime dependency to this skill.
- [ ] Before overall implementation completion run the full project suite `<PYTHON> -m pytest -q`, skill validators, and relevant Windows/macOS native CI. Report skips/failures and behavioral evidence honestly. Verify the execution interpreter imports this checkout/installed package as intended, not an unrelated editable checkout.
- [ ] Source commits/pushes are not a plugin release. Record package/marketplace/cache versions and propose the scoped release separately; do not silently deploy public documents or claim installation updated.
