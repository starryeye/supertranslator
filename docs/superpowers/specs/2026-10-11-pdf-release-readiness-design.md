# PDF release readiness design

## Intent and authorization

The user approved this order on 2026-10-11: harden figure-free PDF QA review-change detection, verify diverse PDFs and webpage compatibility, then upgrade the version and deploy through `starryeye/plugins`. The goal is a general Windows/macOS translator, not special handling for the existing book sample. Existing PDF/web skills remain distinct and share the Python implementation. AI authors translations directly; no machine-translation service or automatically approved prose is introduced.

This is a new release-readiness effort, not a second final fix wave of the completed 2026-10-09 figure-review plan. Its retained evidence and final 50-page sample must not be overwritten. Implementation waits for approval of this description and the subsequent implementation plan. Preserve the previously chosen subagent-driven execution method.

## Observed baseline

- Existing isolated worktree: `/Users/starryeye/play/web-translator/.worktrees/pdf-commercial-layout`, branch `codex/pdf-commercial-layout`, source baseline `14c5d3bfe0b5f8fd8ee9eff2b7e094971bba7b15`. No tracked uncommitted changes; private runs/logs/output remain untracked.
- Current plugin/package version: `0.5.2` in `.codex-plugin/plugin.json`, `pyproject.toml`, and `src/web_translator/__init__.py`.
- Marketplace: `/Users/starryeye/play/plugins`, clean `main` at `38f2af669190a292b432db0ab181853e80971f70`, catalog pins `v0.5.2` and peeled commit `3ad0dae2006f4244a10962e5e368f11356044301`.
- Previous frozen local verification: 2,643 combined unique passes, 10 native-Windows skips, two live tests excluded. The original sandbox full command exited 1; its exact 21 permission-related cases subsequently passed under scoped escalation. This is baseline evidence, not fresh proof of a new change.
- [Latest source CI](https://github.com/starryeye/web-translator/actions/runs/38141776232), same source HEAD: macOS package-smoke passed; Windows package-smoke failed with 22 failures, 39 setup errors, 50 passes and two skips. Release is therefore blocked even before the new fix.

## 1. Figure-free review lifetime

`prepare_pdf_qa` holds `review.json`, validates its parsed semantic evidence, and captures its bytes. Before publishing QA pages/record and after publishing them it calls `_verify_prepare_figure_snapshot`. That helper returns immediately when no figure snapshot exists, so it skips the master-review identity/content checks for ordinary figure-free and name-only runs.

A read-only differential probe on the existing held review supplied deliberately unequal expected bytes. The no-figure branch returned successfully; a dummy verified figure snapshot caused the expected `PDF master review changed content during QA preparation` refusal. No actual review/input/output was modified. This establishes the skipped guard, not an end-to-end race test.

Required behavior:

- Every QA preparation binds the originally consumed master-review identity and exact bytes through both existing pre/post-publication guard points, whether there are figures, explicit names, an empty optional figure inventory, or neither.
- Keep optional figure-input verification conditional on a real held figure snapshot. No invented figure records or new required names are added.
- A same-inode byte edit and an identical-byte file replacement both fail closed, including during render and after QA publication starts.
- Failed initial preparation exposes no successful `pdf-qa.json`/`qa-pages` pair. Failed repeated preparation restores its prior valid evidence byte-for-byte. The staged PDF remains recoverable, final output stays absent, and foreign replacement files are not deleted.
- An unchanged figure-free review still completes preparation and finalization with exactly three output artifacts.

The builder may retain or clarify the existing private guard name; no public command, model/schema, semantic-digest format, or HTML behavior changes are needed. Main source scope is `src/web_translator/pdf_qa.py`; regression tests should use the existing canonical selectable-PDF fixture producers.

## 2. Windows release blocker

The real Windows failure trace reaches `NtQueryDirectoryFile` through `hold_pdf_semantic_inputs` and `hold_pdf_figure_inputs`; it returns access denied on the held root directory. `pdf_assemble._open_directory_anchor` obtains its fallback handle from `pdf_acquire._open_windows_run_anchor`, whose `CreateFileW` requested access is currently `0`. Relative child-directory opens already request list access.

The bounded leading hypothesis is missing list access on the root handle. Microsoft's [file/directory rights documentation](https://learn.microsoft.com/en-us/windows/win32/wmisdk/file-and-directory-access-rights-constants) assigns `FILE_LIST_DIRECTORY` the value `0x1`; [NtQueryDirectoryFile](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntquerydirectoryfile) enumerates through the supplied directory handle. This hypothesis must be proven with an access-contract regression and real Windows CI, not a mocked-success claim.

Required behavior:

- Request only the necessary directory-list access where the held root anchor is used for enumeration. Do not request administrator rights, generic write/full access, weaken reparse/identity checks, or fall back to path-based enumeration.
- Preserve existing share-read/write/delete flags, handle cleanup, relative publication, no-clobber, and same-identity verification.
- Cover exact returned child names using a real Windows anchor, including non-ASCII names, and exercise native PDF preparation/finalization. POSIX behavior remains unchanged.
- The separate Windows `test_committed_pdf_acceptance_fixtures_regenerate_byte_for_byte` failure has only an uninformative `assert all(...)` today. It is not yet established as the same cause. First retain exact mismatched filenames and byte/hash evidence; then correct only the evidenced producer/platform defect. Do not replace committed expected PDFs/translations, normalize away a meaningful difference, skip the case, or blindly pin/update dependencies.
- If this investigation requires a new dependency floor, artifact schema, filesystem strategy, or unrelated subsystem change, stop and surface that scope change for approval.

Likely source/test scope is `src/web_translator/pdf_acquire.py`, existing Windows anchor tests, `tests/test_pdf_pipeline.py` and the narrowly responsible synthetic fixture producer if byte evidence requires it. The workflow may add the new guards/native tests to its existing matrix. Both macOS and Windows jobs must pass on the release candidate SHA; a prior macOS pass is not a release gate.

## 3. Generality and compatibility acceptance

Use independent committed sources, not a resized or renamed copy of the previous book:

- `technical-document-v1`: ordinary one-column prose and headings, including local paths with spaces/non-ASCII characters.
- `table-report-v1`: selectable cells, merged headers and multipage tables.
- `two-column-footnotes-v1`: column reading order and marker/footnote ownership.
- `figures-captions-v1`: original artwork preservation and translated captions/body.

Run the existing complete reviewed pipelines, reopen their actual outputs and compare with the independent source/semantic oracle. Inspect every resulting source/output page visually, including table spans, reading order, captions, note placement, clipping and text selection. Retain page-specific results, paths, source/output hashes and limitations in a new private acceptance report. Stored synthetic translations and test-only approval helpers are regression evidence; they are not fresh AI translation or commercial certification. Any new actual prose translation must be authored directly by AI and use normal semantic/visual approval before final publication.

Retain the previous 50-page book as separate real-document evidence, not proof of all book styles. Run exact existing 500-page acceptance/501-page refusal and 50-MiB boundary cases; report them as input-boundary verification, not a completed 500-page book translation or performance promise. Scan, encryption and malformed-input refusal must still prevent final output. Public-PDF transport regression remains required.

For HTML, exercise both existing reviewed representative snapshots (`spring-ai-concepts-v1`, `rfc8693-v1`) and the separate opt-in capture/extraction checks for `https://docs.spring.io/spring-ai/reference/concepts.html` and `https://datatracker.ietf.org/doc/html/rfc8693`. These live checks establish acquisition/extraction only, not fresh semantic translation of the sites.

Run one complete non-live suite on the frozen final production/test surface, with raw log/XML, true exit status, exact IDs and platform skips. Use network/browser permissions deliberately; if environmental failures occur, rerun only the evidenced failed IDs and keep the original exit status. Avoid replaying a completed identical long gate merely to aggregate its IDs. Changes after the freeze invalidate affected evidence.

Correct the README's stale "eight visual dimensions" wording to the current thirteen only after checking the canonical contract. No new extraction heuristics, book/product/font allowlists, automatic approval, or broader website support promises are part of this work.

## 4. Version and marketplace deployment

Controller proposal, not an existing user-selected number: release `0.6.0`. Since `v0.5.2` the branch contains unpublished logical-unit/semantic-layout/figure-review functionality as well as compatible fixes. A minor release is clearer than calling the entire accumulated change a patch. Plugin name and repository URL remain unchanged.

Deployment gates/order:

1. Finish scoped TDD fixes, independent task/final review, diverse acceptance, final non-live/live results, wheel/sdist smoke, and green real Windows/macOS CI for the frozen candidate.
2. Update the three existing source version declarations together using the established version helper; validate version consistency and packaging after the metadata change. Commit and immediately push, as with every commit.
3. Require both CI jobs green on the exact versioned SHA. Create a new immutable annotated `v0.6.0` tag pointing to that SHA, push it, verify its remote peeled commit, and create a stable GitHub release with truthful feature/limit notes. Never overwrite an existing remote tag or force push.
4. Update the catalog's version/ref/SHA to that exact upstream release, the matching validator constant/tests, and marketplace README install/tag references. Metadata remains copied from the upstream manifest; do not vendor plugin code.
5. Run the marketplace unit tests, offline validator and remote clone/tag/manifest/version validator before its commit; immediately push the reviewed catalog commit to its normal `main`, then recheck published remote state.

Controller default: tag the reviewed named work branch; no merge into upstream `main` is required for the immutable tag-pinned marketplace and none is implicitly authorized by this design. Keep branch/worktree/private evidence. No PyPI publication, installer migration, automatic local plugin reinstall, rename, source/output overwrite, or cleanup.

`plugins` is outside the current writable roots: any needed write must obtain the normal sandbox escalation for that exact repository, not bypass permissions or copy changes into another catalog. Recheck that checkout and remote `main` are clean/current before modifying or publishing. User edits or unexpected remote advancement require reconciliation, not overwrite/force push.

## Fixed constraints and success criteria

- Python >=3.11; Windows and macOS; existing dependencies only unless a newly evidenced need is separately approved.
- Text-selectable input only; no OCR; refuse scans and encryption. Input cap 500 pages, 50 MiB. Logical-unit budget remains 12,000 characters; rendering/resource budgets remain enforced.
- Original artwork unchanged; selectable body/captions/table text translated by AI. Numbers and other protected source content remain exact.
- Per successful PDF run: exactly `translated.pdf`, `manifest.json`, `review-report.md`; failed/unreviewed runs do not expose success artifacts.
- No book-specific exception or permissive source ownership heuristic. Distinct PDF/web skills and shared translation/review contracts remain intact.
- Every commit is followed immediately by push. Review precedes product/release commits; test evidence precedes completion claims.
- Completion reports exact source/catalog commits and tag, fresh native platform outcomes, inspected fixture coverage, input-boundary limits and any remaining blocker. Deployment is not complete until the remote marketplace resolves the verified immutable release.

## Calls left to the builder

Private guard naming, minimal regression-test organization and capture of Windows mismatch diagnostics are implementation details. Reuse existing canonical fixtures and held-handle APIs; avoid reorganizing large modules or rebuilding all existing fixture machinery. The controller owns actual visual acceptance, frozen evidence reconciliation and commit/push/tag/catalog publication; implementation subagents must not mutate the prior real-book evidence or publish a release.

## Approved Windows remediation addendum (2026-10-12)

The user explicitly approved fixing the newly evidenced Windows UTF-8 test I/O and QA cleanup/restoration defects, with separate regressions and independent reviews. This extends the running effort; it does not weaken any earlier success or evidence contract.

At reviewed commit `2d5c736dba25d9a48dcf96bcf4f5495e9467b044`, [native CI](https://github.com/starryeye/web-translator/actions/runs/38163907823) has macOS 147 passes/10 Windows-only skips and Windows 117 passes/two skips/38 failures. Root enumeration now succeeds. Twenty-eight failures arise from implicit cp1252 reads/writes in test helpers/assertions; eight plain QA race failures expose initial cleanup and repeated-preparation failure; two failures concern the figure fixture's inventory digest. Local probes establish the exact differing file/field, not the native inventory component causing it.

- Make the affected test fixtures and assertions explicitly use UTF-8; retain normal Windows locale in CI. Do not hide failures with a global UTF-8 override, tolerate invalid bytes or skip cases.
- Repair Windows QA moves/cleanup/restoration within the existing held-root, relative-name NT operations. Read-only root/enumeration handles remain read-only. If a mutation requires additional permission, obtain only a short-lived, identity-bound handle for that owned child and close it on every path. No administrator rights, generic write/full access, path-based destructive fallback, replacement clobbering or ownership heuristic is permitted.
- Preserve exact prior QA record/page bytes on failed repeated preparation; initial failure leaves no public QA artifacts. Keep staged PDF recoverable, foreign replacement data intact and final output absent. Handle-release windows, if necessary, require original identity and exact-byte/hash verification after reopening; they cannot silently accept a new snapshot.
- Continue the already authorized fixture diagnosis by retaining actual native canonical inventory, exact document bytes, two crop PNGs, generated review and renderer/encoding versions before temporary cleanup. Only synthetic fixtures may be uploaded as CI diagnostic artifacts; never user books, translations or secrets.
- Do not force/rebind the committed review hash, normalize byte equality, replace expected fixtures, change digest/schema, update dependency/Poppler versions or change production extraction/media behavior based on a hypothesis. A need for any such expansion remains a separate approval decision after component evidence is available.

Builder choices: minimal private mutation-handle and descendant-lifetime organization, UTF-8 regression organization, and native diagnostic packaging. The existing release/marketplace gates and no-cleanup/no-main-merge constraints remain unchanged.
