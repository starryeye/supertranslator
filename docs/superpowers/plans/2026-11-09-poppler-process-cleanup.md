# Poppler Process Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development, the user's preserved execution method. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure interruption and monitoring failures do not leave this runner's external PDF child alive.

**Architecture:** Keep `_run_poppler(command: list[str], action: str) -> None` and its current limits. Add one local lifecycle cleanup path that terminates/reaps only its own still-running child and preserves the primary exception. No process manager or renderer redesign.

**Tech Stack:** Existing Python subprocess/pytest; no new dependency.

**Spec:** `docs/superpowers/specs/2026-11-09-reviewed-web-integrity-and-runtime-fixes-design.md`, section C and shared boundaries. Executes after the web integrity plan.

## Global Constraints

- Preserve the original failure/interrupt; cleanup must not swallow it or replace it with a secondary error.
- Do not kill unrelated processes or change ownership guards.
- Existing timeout/output budgets, PDF semantic/figure/hash contracts and native platform support are unchanged.
- Never modify user `temp/`, published translations, prior review evidence, or untracked historical runs as implementation fixtures.
- Commit on an isolated work branch and push immediately after each commit; no release/install/publication.

## Review Focus

1. KeyboardInterrupt/SystemExit while communicate waits: own child is dead/reaped and original exception escapes.
2. Output-directory monitoring raises while child still runs: same PdfMediaError preserved, no writer remains.
3. Launch fails before a child exists, or child exits just before cleanup: no unrelated kill or secondary-error replacement.
4. Nonzero exit, timeout and output-budget failure keep their original diagnostics and limits.
5. Cleanup itself raises while another error is active: retain the primary failure and do not report success.

---

### Task 1: Bounded lifecycle cleanup and regression tests

**Files:** Modify `src/supertranslator/pdf_media.py`; add focused cases in `tests/test_pdf_media.py`.

**Interfaces:** `_run_poppler` signature/return and `PdfMediaError` remain unchanged. A private local cleanup helper is permitted only if needed to share normal/exception handling; no public API.

- [ ] **Write failing tests:** `test_poppler_interrupt_reaps_child_and_preserves_interrupt` parametrizes KeyboardInterrupt/SystemExit with a captured real sleeping Python child, asserting original type/value and `child.poll() is not None` after exit. Always include fixture-finally cleanup so a RED test cannot leak a child.
- [ ] **Write monitoring/race tests:** `test_poppler_monitor_error_reaps_child` uses a missing synthetic output directory and real child, asserts `PdfMediaError` for monitoring and reaped child. `test_poppler_cleanup_keeps_primary_error` uses narrow process doubles for secondary kill/reap failures and exited-child races. Assert launch failure has no attempted unrelated kill, and normal success never kills an already-finished child.
- [ ] **Run RED:** `<PYTHON> -m pytest tests/test_pdf_media.py -q -k 'poppler and (interrupt or monitor_error or cleanup)'`; confirm the known live-child leak, not unrelated setup failure.
- [ ] **Implement minimal cleanup:** retain shell=False, current communicate polling, timeout/output-budget checks and return-code diagnostics. Track the actual Popen child; kill only if still alive and always reap as far as the real subprocess API permits. Keep the active primary exception if cleanup fails; never suppress it into successful return.
- [ ] **Run GREEN:** focused tests above, then `<PYTHON> -m pytest tests/test_pdf_media.py tests/test_pdf_extract_transaction.py tests/test_pdf_render.py -q`; verify no probe children remain. Existing process-budget tests still assert their original limits.
- [ ] **Independent scoped review, commit and immediate push:** `fix: reap PDF tool processes on interrupted execution`. Controller reviews before committing; no extra implementation agents or broad fixes.

## Handoff

- Local `<PYTHON>` and worktree import setup are defined in the companion web integrity plan's Implementation Calls; native CI uses its installed wheel.
- [ ] User confirms the plan; interpreter must import this worktree, not the canonical checkout's editable package.
- [ ] CI companion adds coverage in existing native jobs. Full suite/whole-branch review are shared final gates after all three plans, not duplicated here.
- [ ] Record modeled-call coverage separately from actual process/Windows execution, and disclose cleanup limitations rather than inventing guarantees.
