# Supertranslator Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (the user's existing execution method) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the repository, plugin, Python package, executable and real local project folder to `supertranslator`, without providing legacy-name compatibility aliases.

**Architecture:** Rename the actual implementation package and its callers, not just its display metadata. Keep separate web/PDF skills sharing the same translation/review implementation, under the proposed new names `supertranslator-web` and `supertranslator-pdf`. New runs use `.supertranslator/runs`; past results and immutable evidence remain historical data, not a compatibility runtime.

**Tech Stack:** Existing Python/setuptools, Git/GitHub, Codex plugin manifests and external marketplace.

**Spec:** The user's 2026-10-24 publish/rename request, explicit 2026-10-25 answer, “호환 이름도 모두 제거하도록 계획 변경,” and subsequent “진행” approving the revised implementation/release plan. This revision replaces the compatibility-preserving draft.

**Revised:** 2026-10-25. The preceding `0.7.0` publication is already complete: upstream main/tag commit `d1a9a13f432980d86cb9a15c6b758a7ab00b9184`, marketplace main `7a694bfa9dc79ca6e99113b2457966c48534df44`. Do not replay that release or overwrite its tag.

## Global Constraints

- Start the rename from published `0.7.0` (`d1a9a13`), reusing the retained isolated checkout on a `codex/` rename branch. Do not create nested worktrees or include private runs/results in commits.
- Release the renamed plugin as `0.8.0`; document the intentional breaking rename and reinstall/new-workspace requirements. Never overwrite prior tags or erase release history.
- GitHub repository: `starryeye/supertranslator`; plugin `name` and `displayName`: `supertranslator`; Python distribution: `supertranslator`.
- Implementation package: `src/supertranslator`; command: `supertranslator`; module invocation: `python -m supertranslator`. Do not ship `web_translator`, an old console script, a forwarding module or a legacy-name fallback.
- Proposed skill names/directories: `supertranslator-web` and `supertranslator-pdf`. Preserve separate input routing and shared references; do not provide duplicate old-name skills.
- New run root: `.supertranslator/runs`. Do not discover or resume `.web-translator/runs` as a fallback. Keep output directory names (`translated-pages`, `translated-pdfs`), artifact filenames, schemas, protection/ownership/hash checks, AI-only translation and semantic/visual approval requirements unchanged.
- Update active environment-variable naming to `SUPERTRANSLATOR_FORBID_SOURCE_ROOT`; keep the installed-source-fallback guard effective under the new name, without accepting the old environment variable as an alias.
- Old names may remain only as historical records, immutable old fixtures/release evidence, migration documentation or explicit negative tests. Do not rewrite old approved results, hashes, source captures, audit logs or past design documents to make their spelling match the new brand. Existing wire markers such as `data-wt-*` are document-format identifiers, not executable aliases; changing them is out of scope.
- Move the real project root from `/Users/starryeye/play/web-translator` to `/Users/starryeye/play/supertranslator` only after remote release and marketplace verification.
- Preserve all linked worktrees, untracked runs, prior results and audit evidence; repair Git worktree registrations after the move. The old project path must be absent, including dangling links: no compatibility symlink, forwarding directory or duplicate checkout. Old absolute local links will stop resolving; return the new absolute links and tell the user to reopen the project at its new real path.
- Preserve past `.web-translator` data without automatically moving its internal files into the active new run root or rewriting embedded paths/digests. Historical data is not a supported `0.8.0` resume path. Finished HTML/PDF artifacts remain readable at their new project-root location.
- For installed plugins, document removing the old identity and installing `supertranslator@starryeye`. Do not edit installed caches or the app's saved-project database directly, or silently reinstall plugins in unrelated workspaces.
- Prove old-distribution uninstall/new-distribution install in an isolated environment, including absence of old module/command entry points. After the real folder move, rebuild this project's `.venv` under the new absolute path rather than retaining invalid old shebangs/editable references. Retain the old venv as a clearly inactive, ignored archival backup; do not mutate unrelated environments. Runtime dependencies must satisfy the existing bounds, with no new translation backend.
- Every commit is immediately pushed; do not force-push, delete branches/worktrees, replace old artifacts or rename the catalog repository `starryeye/plugins`.
- GitHub may retain its platform-managed redirect from the old repository URL. This plan creates no application compatibility alias, but does not create a replacement old-name repository or promise to disable GitHub's own redirects.

## Review Focus

- Fresh and migrated installations expose only the new executable/module/distribution, without accidentally succeeding through a globally installed old package.
- Both renamed skills remain separately selectable; moved cross-skill references resolve and shared AI-only translation/review behavior is unchanged.
- Package/font/CSS/resource paths, binary font-license attributes and the installed-source-fallback guard survive the module rename on Windows/macOS.
- New runs allocate only under `.supertranslator/runs`; an existing historical run directory must not trigger old-root discovery/fallback, and path/identity/hash defenses remain intact.
- Folder relocation repairs nested Git registrations and creates a working new-path venv without altering old artifact bytes or leaving an old-root link.

## Task 1: Rename the actual runtime and skill identities

**Files:** Move `src/web_translator/` to `src/supertranslator/`; move `skills/web-translator/` to `skills/supertranslator-web/` and `skills/pdf-translator/` to `skills/supertranslator-pdf/`. Update package/skill consumers in `.codex-plugin/plugin.json`, `pyproject.toml`, `.gitattributes`, `.gitignore`, `README.md`, `scripts/version.py`, `scripts/vendor_pdf_fonts.py`, `.github/workflows/`, `tests/*.py` and `tests/live/test_sample_pages.py`. Existing runtime files owning run roots, reports, network identity and resource lookups change spelling only, not their safety algorithms. Historical fixture content is not a bulk replacement target.

**Interfaces:** Only `supertranslator.cli:console_main`, `supertranslator`, `python -m supertranslator`, the two new skill identities, and `.supertranslator/runs` are active. The existing three-file version contract now locates `src/supertranslator/__init__.py`. New manifests identify their tool as `supertranslator`; existing immutable manifests are not rewritten.

- [ ] Add isolated subprocess/package tests requiring new executable/module help to succeed, old module execution to fail with no module found, and no old console entry point in the installed distribution. Baseline against the current package must fail for the missing new interface, not a test typo. Pin the expected new metadata and two skill identities independently of production constants.
- [ ] Add run-allocation cases requiring `.supertranslator/runs` even when a historical `.web-translator/runs` already exists, without modifying that historical directory. Keep foreign/symlink/reparse/replacement negative cases. Add a moved-reference/package-resource gate that actually reads the new package's bundled fonts/CSS and both skill references. Do not add an old-name blacklist or change format readers merely to force old files to fail; the boundary is no named alias/discovery/migration path.
- [ ] Rename the package, skill directories and active callers/configuration using reviewed mechanical substitutions; read the actual diff for unintended string/fixture changes. Update `scripts/version.py`'s package location before setting all three versions to `0.8.0`. Fix all active module-resource, runtime-root, tool identity, new environment-variable and binary-license paths without modifying publication algorithms or protection formats.
- [ ] Update maintained instructions to the new module, command, skill names, run root and URL. Explicitly disclose that old commands, skill names and unfinished old runs are not a supported `0.8.0` interface. Read skill-creator/writing-skills before changing skill instructions; this is identity/reference migration, not a new translation workflow.
- [ ] Build wheel/sdist in temporary directories; install into a fresh isolated interpreter and inspect actual module/resource paths outside the checkout. Exercise both supported new invocations, no old aliases, new run allocation and absent checkout fallback. Separately install the previous release, uninstall it, install `0.8.0`, and verify no old distribution/module/command remains in that controlled environment.
- [ ] Run version/metadata/CLI/skill/path/resource covering gates and the non-live suite against the renamed tree. Preserve failures and exact skips; do not regenerate previously approved golden artifacts or remove source/hash defenses to obtain green tests. Any fixture-contract conflict not caused by a simple owned name/path expectation needs an explicit reviewed resolution.
- [ ] Obtain scoped independent review, resolve findings with covering regressions, commit and immediately push. Verify exact-SHA Windows/macOS web and PDF CI before main integration/release; if integration changes bytes, refresh affected gates on the actual released SHA. Keep the user's subagent-driven method and prior artifacts.

## Task 2: Rename remote and publish catalog migration

**Files:** `starryeye/plugins/.agents/plugins/marketplace.json`, its `README.md`, `scripts/validate_marketplace.py`, `tests/test_validate_marketplace.py`.

**Interfaces:** One catalog entry named `supertranslator`, new upstream URL, `v0.8.0`, exact peeled commit SHA. The existing strict remote verifier remains authoritative.

- [ ] Confirm the new repository name remains unused and the authenticated account retains administration rights. Finish reviewed main integration/version checks without overwriting the earlier release.
- [ ] Rename the existing GitHub repository, preserving its ID/history/releases; update the shared local `origin` URL and verify the new endpoint. Do not add a separate old-name repository or an alias entry in the catalog; GitHub's automatic redirect remains platform behavior, not a migration feature.
- [ ] Publish immutable `v0.8.0` and its release notes only after exact-SHA gates pass.
- [ ] Update catalog fixture expectations first; observe old-name/version rejection, then update catalog metadata and strict validator to the new identity without weakening tag/SHA/manifest checks. The catalog contains only `supertranslator`, not a legacy listing. Keep rejecting vendored plugin code under both old and new paths as a negative safety check, not compatibility support.
- [ ] Run all catalog tests, offline validation and `--verify-remote`; require new name, source URL, version, immutable tag/SHA and manifest metadata to agree. Document explicit old-plugin/distribution removal and new installation, including the new two-skill names; no automatic installed-cache mutation.
- [ ] Commit using existing catalog message style, immediately push main, and verify its remote SHA and released source reference.

## Task 3: Move local project without losing work

**Files:** Filesystem root directory, Git worktree administrative paths and this project's replacement `.venv`; no result/manifest/report content edits or app database edits.

**Interfaces:** New real root `/Users/starryeye/play/supertranslator`; no filesystem entry at `/Users/starryeye/play/web-translator`, including a dangling symlink. A new-path venv exposes only the new module/distribution/command. The user must reopen the app project at its new path.

- [ ] Before the last move, confirm destination absent and snapshot all worktree registrations/HEADs, tracked status, representative result/evidence hashes and runtime dependency versions. Prepare a controlled new-env installation test; record exact new-root verification commands and warn that the current app's old workspace path will cease to exist.
- [ ] Move the real root once; repair the nested `.worktrees/pdf-commercial-layout` and `.worktrees/release-0.3.0` registrations from the new root. Preserve their branches and every untracked/ignored artifact. Do not follow or create an old-root alias to make verification succeed.
- [ ] Retain the former project venv as an inactive ignored archival backup and build a new `.venv` at the new real root. Install the reviewed `0.8.0` distribution and required runtime dependencies, preserving dependency bounds. Do not reuse old absolute shebangs/editable files or change unrelated workspace environments.
- [ ] From the explicit new workdir, verify all worktree HEADs/status and new origin, new-root interpreter/CLI/module/resource paths and version consistency. Require old-root `lexists` to be false and old command/module absent from the new project environment. Compare completed artifact bytes/hashes at their relocated paths; do not rewrite their contents to repair old embedded paths.
- [ ] Report the new repository URL, `0.8.0`, install identity, both new skill names and actual folder/new artifact links. Explain that old local absolute links and old run resumption are intentionally unsupported, past results remain preserved, and app/plugin setup requires explicit reopen/reinstall rather than a compatibility link.

## Reference

GitHub rename behavior: https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository

## Approval

Approved by the user's subsequent “진행” on 2026-10-25, after presentation of the revised scope and its no-old-link consequence. Execute the three tasks with the existing subagent-driven method, commit/immediate-push convention, independent review and exact-SHA native gates. `0.7.0` is already published and remains unchanged; it is not a pending prerequisite to replay.
