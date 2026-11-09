# Integrity and Workflow CI Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development, the user's preserved execution method. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the new integrity/workflow contracts in native CI and preserve both documented HTML QA recipe stages in integration tests.

**Architecture:** Extend existing explicit installed-wheel/native test selections; keep the same workflows, dependencies, artifact retention and platform matrix. Change the recipe helper from command-name overwrite to distinct stage keys and execute the real two-stage HTML QA sequence with TEST ONLY fresh visual evidence.

**Tech Stack:** Existing GitHub Actions, pytest, Chromium, Poppler; no new service/dependency.

**Spec:** `docs/superpowers/specs/2026-11-09-reviewed-web-integrity-and-runtime-fixes-design.md`, section D. Executes after web integrity and process cleanup plans.

## Global Constraints

- Keep installed-wheel provenance checks and existing Windows/macOS native tests.
- No new CI framework, automatic independent review, semantic approval bypass or real-artifact publication.
- Tests use synthetic fresh visual evidence, never pretend that writing a JSON pass constitutes actual professional visual acceptance.
- Never modify user `temp/`, published translations, prior review evidence, or untracked historical runs as implementation fixtures.
- Commit on an isolated work branch and push immediately after each commit; release/install/main merge/publication remain separate.

## Review Focus

1. Both macOS and Windows explicit test lists contain new web review/content and skill/workflow tests, not only one shell branch.
2. HTML initial QA and final QA examples survive parsing separately and execute in order.
3. Missing/stale fresh visual evidence refuses finalization; old output/review bytes stay unchanged.
4. Installed module/CSS/font resources cannot silently fall back to the source checkout.
5. Process cleanup regressions run with the existing PDF tool dependencies and keep artifact diagnostics on failure.

---

### Task 1: Existing native selectors and complete recipe test

**Files:** Modify `.github/workflows/web-preformatted.yml`, `.github/workflows/pdf-cross-platform.yml`, `tests/test_render_workflow.py`; add `tests/test_ci_contract.py`.

**Interfaces:** Existing `render_commands` helper retains command lists but keys HTML QA stages as `qa-reader prepare` and `qa-reader finalize`, while PDF keys remain `pdf-qa prepare`/`pdf-qa finalize`. No runtime CLI change.

- [ ] **Write failing tests:** `test_native_web_jobs_select_new_integrity_and_workflow_tests` asserts existing macOS/Windows web command selections include `test_web_review.py`, `test_web_content.py`, `test_render_workflow.py`, `test_review_skill_contract.py` and `test_ci_contract.py`. `test_native_pdf_jobs_select_process_cleanup_tests` asserts the existing PDF command includes `test_pdf_media.py` without dropping prior native-node selectors. Check command selections, not mere mentions/comments; use existing dependencies/stdlib rather than adding a YAML package.
- [ ] **Write recipe RED:** `test_html_recipe_preserves_both_qa_stages` parses the actual HTML guide and asserts distinct initial/final commands including the final `--visual-review` flag. Extend the real bound-bundle workflow test: export → initial QA → assert pending → final QA refuses missing/stale evidence → issue explicitly TEST ONLY newly bound visual record → final QA passes. Preserve historical text edit once, original/source/first output inventories and existing literal/link checks.
- [ ] **Run RED:** `<PYTHON> -m pytest tests/test_ci_contract.py tests/test_render_workflow.py -q`; expect current selector/duplicate-key omissions, not browser permission errors. Use an authorized browser run when needed for valid test evidence.
- [ ] **Implement selectors/helper:** add exact file selections in both existing web shell branches and PDF cleanup suite in the PDF matrix command. Keep -I, import-mode, forbidden-source-root, JUnit/log/screenshot retention and pinned Poppler/bootstrap checks. No altered skip/marker policy to make CI green.
- [ ] **Run GREEN:** same focused tests plus `tests/test_plugin_layout.py tests/test_skill_contract.py tests/test_renamed_identity.py`; validate both skill references affected by web API documentation. Recipe approval is synthetic; no independent source/final review is invoked.
- [ ] **Independent review, commit, immediate push:** `test: cover integrity and render workflows in native CI`.

## Shared Final Handoff

- Local `<PYTHON>` and worktree import setup are defined in the companion web integrity plan's Implementation Calls; native CI keeps its installed-wheel checks.
- [ ] User confirms all three plans before implementation; preserve subagent-driven execution, one implementer at a time.
- [ ] Run `<PYTHON> -m pytest -q` once on the final stable tree, record exact passes/skips/deselection and imported package path. Full-suite browser/loopback permission failures are environment evidence, not a reason to weaken checks.
- [ ] Read fresh macOS/Windows web and PDF CI results at the final pushed code commit. Confirm installed-wheel tests use the built wheel, not the editable checkout.
- [ ] Perform one whole-branch independent review, plus at most its one bounded final fix wave under the SDD workflow. Keep ordinary task fix rounds scoped and within their cap.
- [ ] Independently repeat the original bad-final/control browser probe with the new valid bound TEST ONLY inputs; require bad-final rejection for content mismatch and normal-control success. Do not mistake a missing new contract for proof of the content checker.
- [ ] Report remaining limitations and local/remote branch status separately from any release/install/publication. Do not merge/publish without the user's choice.
