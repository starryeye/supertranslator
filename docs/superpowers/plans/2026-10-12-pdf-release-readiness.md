# PDF Release Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The human already selected subagent-driven execution; do not ask them to select it again.

**Goal:** Close the figure-free QA review race and actual Windows blockers, establish general PDF/web compatibility, then publish the verified `0.6.0` release through the immutable marketplace reference.

**Architecture:** Keep the held-handle QA/publication design and existing canonical fixtures. Make master-review verification independent of optional figure verification, restore least-privilege Windows directory enumeration, and diagnose fixture byte differences independently. The controller owns actual visual acceptance, retained verification evidence, commits/pushes and two-repository release publication.

**Tech Stack:** Python >=3.11, pytest, ctypes Windows APIs, ReportLab, pypdf, pdfplumber, Poppler, existing Playwright capture, Git and GitHub Actions/CLI. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-11-pdf-release-readiness-design.md` (approved 2026-10-12).

## Global Constraints

- Python >=3.11; Windows and macOS; existing dependencies only unless a newly evidenced need is separately approved.
- Text-selectable input only; no OCR; refuse scans and encryption. Input cap 500 pages, 50 MiB. Logical-unit budget remains 12,000 characters; rendering/resource budgets remain enforced.
- Original artwork unchanged; selectable body/captions/table text translated by AI. Numbers and other protected source content remain exact.
- Per successful PDF run: exactly `translated.pdf`, `manifest.json`, `review-report.md`; failed/unreviewed runs do not expose success artifacts.
- No book-specific exception or permissive source ownership heuristic. Distinct PDF/web skills and shared translation/review contracts remain intact.
- Every commit is followed immediately by push. Review precedes product/release commits; test evidence precedes completion claims.
- No public schema, semantic-digest, dependency-floor or filesystem-strategy change. Surface any such need for approval, including an unrelated defect uncovered by native CI.
- No source `main` merge, force push, tag overwrite, PyPI publication, repository rename, local plugin reinstall or private-evidence cleanup. Keep the old book input/run/output and completed 2026-10-09 plan intact.
- Stored synthetic translations and approvals are regression inputs, not a new AI translation, human approval or commercial-quality certificate. New prose translation, if needed, must be AI-authored and normally reviewed.

## Review Focus

1. Whitespace-only master-review edits are still byte changes: Task 1 rejects them without treating semantic equivalence as authorization.
2. Identical-byte replacement is still a different file: Task 1 refuses it and preserves the replacement, including on repeated QA preparation.
3. A root Windows handle must enumerate Unicode child names twice without consuming/staling the enumeration: Task 2 tests the real root, not only already-permitted relative child handles.
4. Cross-platform fixture differences must identify the exact path/bytes rather than silently replacing expected evidence: Task 3 tests actionable diagnostics and requires the native mismatch to disappear.
5. A correctly named tag with the wrong peeled SHA is not a valid release: Task 6 retains annotated-tag acceptance and wrong-SHA/missing-tag refusals before catalog publication.

---

## Workspace, ownership and file map

Source root `R=/Users/starryeye/play/web-translator/.worktrees/pdf-commercial-layout`, named branch `codex/pdf-commercial-layout`, planning baseline `805fe59fc43f34c522781c9767f84d15029438a2`. Reuse this existing isolated worktree after read-only identity/status checks; do not create a second checkout or replay unchanged old baselines.

Source commands below run in `R`. Define `P=/Users/starryeye/play/web-translator/.venv/bin/python`; pytest commands use `PYTHONPATH=src "$P" -m pytest`. Use `apply_patch` for file edits. Create a new, initially absent private evidence directory `E=$R/.web-translator/release-readiness-20261012`; if occupied, choose a new unique suffix, never reuse/overwrite it. Keep raw logs/XML, exact command/exit/dependency versions, hashes and CI URLs there. Runtime test tools may create their normal outputs there. Do not commit `E`, previous logs or `translated-pdfs`.

Marketplace root `M=/Users/starryeye/play/plugins`, normal branch `main`; observed baseline `38f2af669190a292b432db0ab181853e80971f70`. It is outside writable roots: obtain normal exact-target escalation for any write, not a permission bypass. Recheck clean checkout and current remote before edits; reconcile unexpected advancement/user changes.

- `src/web_translator/pdf_qa.py`: private preparation guard, existing rollback/publication boundaries; no new public API.
- `tests/test_pdf_qa.py`: new preparation lifetime tests using `make_native_unit_qa_run` and existing publication hooks.
- `tests/test_pdf_name_preservation.py`: unchanged-name happy path; reuse `approved_run` for name-only races.
- `tests/test_pdf_figure_review.py`: existing real-figure and optional-empty regressions; reuse `publication_case(..., case="figure-free", evidence=True)`.
- `src/web_translator/pdf_acquire.py`: Windows root handle access only.
- `tests/test_pdf_acquire.py`, `tests/test_pdf_pipeline.py`: access contract, real Windows enumeration, fixture diagnostics and existing end-to-end gates.
- `tests/pdf_fixtures.py`: only the responsible existing generator if retained native byte evidence proves a defect; never bulk-regenerate committed fixtures.
- `.github/workflows/pdf-cross-platform.yml`: select new QA/native/diagnostic tests in the existing packaged matrix, preserving runner/Poppler configuration.
- `README.md`: canonical visual-dimension count correction only.
- `.codex-plugin/plugin.json`, `pyproject.toml`, `src/web_translator/__init__.py`: synchronized `0.6.0` through `scripts/version.py`.
- Marketplace `.agents/plugins/marketplace.json`, `scripts/validate_marketplace.py`, `tests/test_validate_marketplace.py`, `README.md`: immutable release metadata, expected version and install references; no vendored implementation.

Each implementer reads the approved spec, global constraints and its own task. Implementers do not commit/push, modify prior real-book evidence or publish releases. Controller runs the selected SDD review gates, stages exact task files only, commits in existing `fix:/test:/docs:/chore:` style and immediately pushes. If a push fails, resolve/report it before creating another commit. Independent task reviews precede progression; whole-branch review precedes release.

### Task 1: Bind every QA preparation to the consumed master review

**Files:** Modify `src/web_translator/pdf_qa.py:1697-1705`; test `tests/test_pdf_qa.py`; optionally add a case in `tests/test_pdf_name_preservation.py`. Workflow selection belongs to Task 2.

**Interfaces:** Consumes `prepare_pdf_qa(run_dir: Path, output_dir: Path) -> PdfQAResult`, `make_native_unit_qa_run(tmp_path, *, case="joined")`, `approved_run(tmp_path, *, notes=False)` and `publication_case(root, *, case, evidence=True)`. Produces the same private `_verify_prepare_figure_snapshot(run_anchor: Any, opened: Mapping[str, Any], figure_snapshot: Any | None, review_bytes: bytes | None) -> None` with unconditional master-review identity/byte validation at both existing call sites. No downstream API changes.

- [ ] **Step 1: Add failing lifetime tests.** Name the main parametrized test `test_prepare_figure_free_master_review_races_fail_closed`. Cases: review shape `plain/name-only/optional-empty`, mutation `content/identity`, hook `render/pages-publish/json-publish`, prior successful preparation `False/True`. For `plain` use `make_native_unit_qa_run`; `name-only` assemble `approved_run`; `optional-empty` assemble the existing figure-free publication fixture. Snapshot staged-PDF bytes and all existing prior QA page/record bytes before installing the hook. Hooks wrap `render_pdf_pages`, `_publish_qa_artifact_directory`, and `assembly._publish_new_file` (filter the latter to `pdf-qa.json`), mutate once after the original returns. Content writes `original_bytes + b" "`; identity moves the original to a saved private name then writes identical bytes at `review.json`.

  Assert `pytest.raises(PdfQAFailure)`, hook fired, current replacement/edit bytes survive, staged PDF is byte-identical, final output absent. Initial preparation leaves neither public QA artifact; repeated preparation restores the exact original record and page inventory/bytes. Also add `test_prepare_figure_free_review_unchanged_finalizes_exact_artifacts`: all three shapes prepare, receive test-only visual evidence via the existing helper, finalize, and retain exactly the three specified filenames. Do not fake a figure snapshot for integration tests.

  Normalize each existing fixture to `(run_dir, output_dir)` before hooking. Core assertions (plus the prior record/page byte mapping comparison when `prior=True`):

  ```python
  with pytest.raises(PdfQAFailure):
      prepare_pdf_qa(run_dir, output_dir)
  assert fired
  assert (run_dir / "review.json").read_bytes() == original_review + (b" " if mutation == "content" else b"")
  assert (run_dir / "staged-output/translated.pdf").read_bytes() == staged_before
  assert not output_dir.exists()
  if not prior:
      assert not (run_dir / "pdf-qa.json").exists()
      assert not (run_dir / "qa-pages").exists()
  ```
- [ ] **Step 2: Run new race tests before the fix.** `PYTHONPATH=src "$P" -m pytest tests/test_pdf_qa.py -k 'figure_free_master_review_races' -q`. Retain RED output: ordinary figure-free cases must fail because preparation unexpectedly succeeds, not because fixture validation or rendering fails. Optional-empty coverage may already pass; report that accurately.
- [ ] **Step 3: Change only the existing guard.** Keep `figure_snapshot.verify()` conditional on a non-`None` snapshot; execute `_verify_anchored_evidence` for `review.json` and exact held-byte comparison independently of that condition. Keep both current pre/post-publication calls and existing error conversion/rollback. Do not weaken evidence, invent review fields or alter successful artifact schemas.
- [ ] **Step 4: Verify GREEN and collateral contracts.** `PYTHONPATH=src "$P" -m pytest tests/test_pdf_qa.py tests/test_pdf_name_preservation.py tests/test_pdf_figure_review.py -q`. Expect zero failures with native-Windows skips recorded, no skip added to a new generic case. Check race restoration and replacement preservation assertions, not just exception counts.
- [ ] **Step 5: Review, commit and immediately push.** Controller reviews exact diff and retained RED/GREEN; stage only changed task files, commit `fix: bind figure-free PDF QA to master review`, then `git push origin codex/pdf-commercial-layout`. Verify upstream ahead/behind `0 0`.

### Task 2: Restore native Windows root-directory enumeration

**Files:** Modify `src/web_translator/pdf_acquire.py:820-864`, `tests/test_pdf_acquire.py`, `tests/test_pdf_pipeline.py`, `.github/workflows/pdf-cross-platform.yml`.

**Interfaces:** Consumes `_open_windows_run_anchor(path: Path) -> _WindowsDirectoryPathAnchor` and existing `assembly._open_directory_anchor`/`assembly._anchored_directory_names`. Produces the same root handle contract with `FILE_LIST_DIRECTORY=0x00000001`, existing share flags `0x00000001 | 0x00000002 | 0x00000004`, disposition `3`, flags `0x02000000 | 0x00200000`. No fallback enumeration, added write privileges or POSIX change.

- [ ] **Step 1: Add access-contract and actual-root tests.** `test_windows_run_anchor_requests_only_directory_list_access` uses a callable fake `CreateFileW` recording arguments (patch `ctypes.WinDLL` with `raising=False` on macOS; stub only `current_path`), asserts the exact values above and handle close once. `test_windows_run_anchor_closes_handle_when_path_validation_fails` makes `current_path` raise, asserts the opened handle is closed and the failure propagates. Native `test_windows_root_anchor_enumerates_exact_unicode_children` is skipped only when `os.name != "nt"`: create `alpha.txt`, `한글.txt`, `하위 폴더`; open the root directly and assert the sorted three names on two calls, then close. Retain the existing relative-child enumeration test unchanged.

  ```python
  assert recorded_args[1:] == (0x00000001, 0x00000001 | 0x00000002 | 0x00000004,
                               None, 3, 0x02000000 | 0x00200000, None)
  # Native test, after directly opening the root anchor:
  assert assembly._anchored_directory_names(anchor) == sorted(["alpha.txt", "한글.txt", "하위 폴더"])
  assert assembly._anchored_directory_names(anchor) == sorted(["alpha.txt", "한글.txt", "하위 폴더"])
  ```
- [ ] **Step 2: Capture RED.** `PYTHONPATH=src "$P" -m pytest tests/test_pdf_acquire.py -k 'windows_run_anchor' -q`. Exact access assertion must expose current `0`, not a mock setup failure. Existing actual Windows CI failure is supporting native evidence, not a substitute for the regression.
- [ ] **Step 3: Apply the least-privilege change.** Set the existing `CreateFileW` requested access to `0x00000001`; retain security/share/open/identity/cleanup logic. Add both contract tests, the native root test and Task 1's new test node IDs to the existing matrix selection. Do not relax runtime guards or change Windows runner/Poppler versions.
- [ ] **Step 4: Run local collateral checks.** `PYTHONPATH=src "$P" -m pytest tests/test_pdf_acquire.py tests/test_pdf_assemble.py tests/test_pdf_pipeline.py tests/test_plugin_layout.py -q`. Expect local zero failures, accurately listed Windows-only skips. A previously evidenced independent fixture mismatch belongs to Task 3; it must not be relabeled as an enumeration failure or silently ignored.
- [ ] **Step 5: Review, commit and immediately push.** Commit exact task files as `fix: grant Windows PDF anchors directory list access`; push immediately. Inspect the Actions run for that exact SHA. Require the new actual-root test to execute/pass on Windows and retained preparation/finalization tests to lose access-denied failures. Save both job outcomes and remaining exact failed IDs; Task 3 owns the independent fixture mismatch. Do not report the release candidate green if any matrix test still fails.

### Task 3: Diagnose and eliminate the native fixture byte mismatch

**Files:** Modify `tests/test_pdf_pipeline.py:638-704`; only if evidenced, modify responsible existing producer in `tests/pdf_fixtures.py`. No committed fixture PDFs, translations, reviews or sidecars may change.

**Interfaces:** Consumes `generate_acceptance_fixtures(root: Path) -> None` and the existing committed fixture tree. Add test-only `_assert_fixture_bytes_equal(expected_root: Path, actual_root: Path, relatives: list[Path]) -> None`; it raises `AssertionError` listing every differing relative path, expected/actual length and SHA-256, and first differing byte offset with bounded nearby hex. An identical comparison returns normally. No production interface changes.

- [ ] **Step 1: Add diagnostic regression.** `test_fixture_byte_comparison_reports_exact_mismatch` creates two small trees containing one equal and two unequal files (one byte replacement, one length-only tail difference). Assert both unequal paths, lengths, hashes, first offsets/hex appear in the exception and the equal filename does not. `test_fixture_byte_comparison_accepts_identical_files` asserts normal return. Run those exact IDs: expect RED because the helper is absent.

  Use `same.txt=b"same"` in both, `changed.pdf` expected `b"abc"` versus actual `b"axc"`, and `tail.pdf` expected `b"ab"` versus actual `b"abc"`. Diagnostic labels are `expected_len`, `actual_len`, `expected_sha256`, `actual_sha256`, `first_offset`, `expected_hex`, `actual_hex`.

  ```python
  with pytest.raises(AssertionError) as error:
      _assert_fixture_bytes_equal(expected_root, actual_root, relatives)
  message = str(error.value)
  assert "changed.pdf" in message and "tail.pdf" in message
  assert "same.txt" not in message
  assert "first_offset=1" in message and "first_offset=2" in message
  assert "expected_len=2" in message and "actual_len=3" in message
  assert hashlib.sha256(b"abc").hexdigest() in message
  assert hashlib.sha256(b"axc").hexdigest() in message
  ```
- [ ] **Step 2: Implement diagnostic comparison.** Keep strict byte equality; call the helper for both regenerated-vs-committed and regenerated-vs-`core.autocrlf=true` checkout comparisons. Preserve file-inventory assertions and native fixture regeneration. Run new tests and `test_committed_pdf_acceptance_fixtures_regenerate_byte_for_byte`: expect local PASS with useful diagnostics for intentional differences.
- [ ] **Step 3: Review/publish diagnostics, then collect native evidence.** Commit `test: report exact PDF fixture byte mismatches`, immediately push, obtain the exact-SHA Windows mismatch text and installed dependency versions. Retain raw job evidence and local comparison; do not infer that the encrypted fixture, line endings or dependency version caused it merely from plausibility. If native regeneration now passes, record the prior cause as unconfirmed and make no speculative producer edit.
- [ ] **Step 4: If mismatches persist, isolate the actual producer defect before its fix.** Reproduce the differing paths through `generate_acceptance_fixtures` and compare first offsets plus PDF metadata/object fields or exact sidecar bytes. Add `test_acceptance_fixture_producer_preserves_committed_bytes_across_platforms` covering those exact files and the evidenced variation; keep real byte comparison as the oracle. Modify only the responsible existing producer under `tests/pdf_fixtures.py`, with no new production API and no expected-byte rewrite. Record the cause and chosen producer/values in the task evidence before editing. If reproducing/eliminating the difference would require new dependencies, schema/filesystem strategy or altered committed expected artifacts, stop for a narrow design decision; downstream release stays blocked.
- [ ] **Step 5: Prove the conditional fix.** Run both new diagnostics and complete fixture-regeneration/pipeline/rejection tests in `tests/test_pdf_pipeline.py`. Controller review must see evidence-specific RED/GREEN, unchanged committed fixture hashes and no hidden normalization/skip. If a producer fix was necessary, commit `fix: preserve PDF acceptance fixture bytes across platforms`, push immediately; otherwise no empty fix commit. Both native matrix jobs must now pass on the exact pushed SHA before Task 4 can accept a candidate.

### Task 4: Generality, visual acceptance and frozen compatibility gate

**Files:** Modify `README.md` dimension wording; create only private evidence under `E` (not shipped). Reuse existing pipeline/fixture tests without inventing new AI/human approvals.

**Interfaces:** Consumes Tasks 1–3's reviewed source and green native candidate, existing four acceptance fixtures, `PdfFinalManifest.from_dict`, canonical `_VISUAL_DIMENSIONS`, existing HTML snapshot/live tests. Produces a hash-bound private `acceptance-report.md`, retained pytest log/XML/exit, inspected PDF outputs and native CI links. No production API changes.

- [ ] **Step 1: Check and correct the documentation contract.** Verify `_VISUAL_DIMENSIONS` contains exactly thirteen canonical entries; change the README's stale eight-dimension statement to thirteen. Controller reviews/checks the documentation-only diff, commits `docs: align PDF visual review dimensions`, immediately pushes before freezing source.
- [ ] **Step 2: Run the independent full PDF fixtures with retained output.** `PYTHONPATH=src "$P" -m pytest tests/test_pdf_pipeline.py::test_committed_pdf_acceptance_fixtures_complete_local_reviewed_pipeline -q --basetemp="$E/diverse-pdf" --junitxml="$E/diverse-pdf.xml"`. `--basetemp` must be a new absent exact subdirectory because pytest deletes it if reused. Expect all five cases to pass (four independent documents plus the non-ASCII local-path case). Retain actual run/output directories, source/translation/manifest/report hashes and parsed manifest/report equality. This is test-only pipeline approval evidence, not actual visual acceptance.
- [ ] **Step 3: Controller performs actual all-page inspection.** Read/apply the PDF skill before rendering/inspection. Render the independent original and resulting PDFs via Poppler into new private directories; inspect every source/output page at readable resolution using image tools. Record headings, two-column reading order, full table cells/spans/repeated headers, footnote owners/placement, figure artwork/captions, clipping, selectable Korean/font evidence, source/output reflow and any limitations by page. Reopen actual PDFs/manifest/report; compare selectable text with the existing independent semantic oracle and exact embedded report JSON with manifest. If any defect appears, do not issue a visual pass; return the specific defect for bounded investigation and invalidate affected acceptance after its fix. Preserve prior 50-page book evidence separately.
- [ ] **Step 4: Run input and HTML gates.** Execute exact existing nodes `tests/test_pdf_extract.py::test_inspect_pdf_accepts_exact_page_count_limit`, `::test_reject_unsupported_pdf_enforces_page_count`, `::test_inspect_pdf_accepts_source_at_exact_size_limit`, `::test_inspect_pdf_rejects_unsupported_document_structure`; acquire size/redirect regressions in `tests/test_pdf_acquire.py`; `tests/test_pdf_pipeline.py::test_committed_pdf_rejections_never_publish_final_output`, `::test_http_pdf_acquire_and_extract_uses_real_transport`; `tests/test_pipeline.py::test_versioned_representative_snapshot_runs_complete_reviewed_pipeline`. Prefix each shortened `::` with its named file. Expect all selected cases to pass. Run `PYTHONPATH=src "$P" -m pytest tests/live/test_sample_pages.py -m live -o addopts='' -q --junitxml="$E/live.xml"` with deliberate network/browser permission; expect both URLs captured/extracted. Live failures block that claimed gate until resolved or explicitly accepted by the human; do not call capture a fresh translation.
- [ ] **Step 5: Freeze and run one full non-live gate.** Record reviewed HEAD, tracked diff hash, runtime/dependency versions and actual fixture hashes. Run `PYTHONPATH=src "$P" -m pytest -m 'not live' -q --junitxml="$E/full.xml"` with a retained raw log and true pytest exit (no pipeline masking). Expect zero failures or, for evidenced environment errors only, keep original failed exit plus rerun exactly those failed IDs under scoped permission. Reconcile XML IDs without duplicate counting, all-and-only rerun coverage and native skips. No repeat of an identical completed full gate solely to aggregate IDs. Any source/test change after freeze requires affected verification again.
- [ ] **Step 6: Whole-branch review and exact native gate.** Fresh reviewer checks the complete release-readiness diff against the approved spec, retained TDD/race/native/visual evidence, unchanged source-specific evidence and all constraints. Resolve findings using the selected SDD process; preserve its limits instead of silently launching an extra fix wave. Obtain both native CI jobs green on the frozen current SHA. This gate is required before version/release work.

### Task 5: Publish the verified upstream `0.6.0`

**Files:** Modify `.codex-plugin/plugin.json`, `pyproject.toml`, `src/web_translator/__init__.py` through the existing version helper. Release notes are controller-authored private evidence/GitHub metadata.

**Interfaces:** Consumes Task 4's accepted frozen SHA/evidence. Produces immutable annotated `v0.6.0`, verified peeled release SHA and stable GitHub release. Plugin name/source URL and all public translation commands remain unchanged.

- [ ] **Step 1: Preflight.** Confirm source branch/status/upstream, no unexpected tracked edits and remote absence of `refs/tags/v0.6.0` (including peeled ref). Record current three versions `0.5.2`. If the target tag/release exists unexpectedly, stop to reconcile rather than overwrite it.
- [ ] **Step 2: Synchronize version and verify.** Run `"$P" scripts/version.py set 0.6.0`, then `"$P" scripts/version.py check` (exact `0.6.0`, exit 0) and `PYTHONPATH=src "$P" -m pytest tests/test_versioning.py tests/test_plugin_layout.py -q` (zero failures). Build fresh wheel and sdist using `"$P" -m build --outdir "$E/dist-0.6.0"`; use new disposable Python 3.11+ environments to install each artifact and check imported `web_translator.__version__ == '0.6.0'` and `web-translator --help` contains PDF and HTML entry points. Retain build/install logs; no PyPI upload or changes to the user's plugin environment.
- [ ] **Step 3: Review/version commit/push.** Review exact three-file metadata diff and package smoke; commit `chore: release version 0.6.0`, immediately push. Record that versioned full SHA and require macOS and Windows package matrix jobs green on it; do not reuse the pre-version CI SHA.
- [ ] **Step 4: Tag and release.** With the exact versioned SHA verified, run `git tag -a v0.6.0 <verified-SHA> -m "Release v0.6.0"`, then immediately `git push origin refs/tags/v0.6.0`. Check `git ls-remote origin refs/tags/v0.6.0 'refs/tags/v0.6.0^{}'`: peeled SHA must equal the versioned SHA, not the annotation object's SHA. Create `gh release create v0.6.0 --verify-tag --title 'v0.6.0' --notes-file <retained-notes>` (stable, not prerelease). Notes state selectable-only limits, AI-authored workflow, unchanged artwork, reviewed logical/reflow improvements, exact Windows/macOS evidence and honestly bounded acceptance coverage. Verify release/tag metadata; no implicit merge to `main`.

### Task 6: Deploy the immutable marketplace reference

**Files:** In `M`, modify `.agents/plugins/marketplace.json`, `scripts/validate_marketplace.py`, `tests/test_validate_marketplace.py`, `README.md` only.

**Interfaces:** Consumes verified remote `v0.6.0` and its peeled full SHA from Task 5. Produces remote marketplace `main` whose single existing plugin has version `0.6.0`, source ref `v0.6.0`, exact release SHA and unchanged URL `https://github.com/starryeye/web-translator.git`. `validate_repository(root)` and remote verifier contracts remain unchanged; validator expected version becomes `0.6.0`.

- [ ] **Step 1: Recheck permission and checkout.** Read applicable marketplace instructions, resolve clean named `main`/remote equality and obtain exact-repository write escalation. Never discard user changes or modify a copied catalog elsewhere. Review existing commit conventions before selecting the catalog message.
- [ ] **Step 2: Establish release-metadata RED.** Update `VALID_ENTRY` and matching test fixtures to `0.6.0`/`v0.6.0` first; run `"$P" -m unittest tests/test_validate_marketplace.py -v` in `M`. Expect existing offline validation against stale `EXPECTED_PLUGIN_VERSION='0.5.2'` to fail. Preserve annotated-tag acceptance, missing-tag and wrong-SHA/manifest/version-check refusal tests, including `test_remote_verification_accepts_matching_annotated_tag` and `test_remote_verification_rejects_sha_manifest_and_version_check_failures`.
- [ ] **Step 3: Update catalog and validation metadata.** Change the catalog's version/ref/SHA, expected validator constant and README's release/install references. Compare every copied interface/policy/author/description field with the tagged upstream plugin manifest; unchanged upstream values stay exact. No vendored source, loose branch ref or annotation-object SHA.
- [ ] **Step 4: Verify before publication.** In `M`, run `"$P" -m unittest tests/test_validate_marketplace.py -v`, `"$P" scripts/validate_marketplace.py`, `"$P" scripts/validate_marketplace.py --verify-remote`. Require zero test failures and both validator exits 0; remote check must actually fetch/tag-resolve/clone/check upstream manifest and version. Retain truthful network/environment errors and resolve before deployment; mocked remote tests alone are insufficient.
- [ ] **Step 5: Independent review, commit and immediate push.** Review exact four-file diff and raw offline/remote proof; stage only those files, commit using marketplace's existing message convention, immediately `git push origin main`. Recheck remote main SHA/local ahead-behind `0 0` and rerun remote validator against published catalog. Source branch/worktree remain intact.
- [ ] **Step 6: Final handoff.** Report source versioned commit, tag/peeled SHA, GitHub release, marketplace commit, fresh native results, four inspected fixture families, exact boundary/live coverage and any limitation. Deployment is complete only when the published catalog resolves the verified immutable release. Distinguish input-cap validation from a full 500-page translation and fixture regression from a commercial translation certificate.

## Controller self-review (planning only)

- Spec coverage: figure-free identity/bytes/rollback -> Task 1; Windows access/byte-difference separation -> Tasks 2–3; independent fixtures/all-page visual/input/HTML/frozen evidence -> Task 4; synchronized version/packaging/immutable release -> Task 5; catalog/remote verification -> Task 6. Retained book, AI-only translation, exact artifacts, scope limits and immediate pushes apply globally.
- Step/type consistency: existing public signatures stay unchanged; the only added interface is the test-only byte comparison helper consumed inside Task 3. Stage hooks refer to current preparation publication sites. Dynamic native producer investigation is evidence-driven and cannot relax expected artifacts or expand approved scope.
- Review Focus: all five conditions above have named tests/gates in their owning task. Initial/repeated preparation and three review shapes are covered, as are root-vs-child Windows handles and annotation-vs-peeled commit identity.
- Proportion: this plan specifies six independent reviewable deliverables and release gates; it does not transcribe implementation bodies or repeat the completed previous plan.
- Planning status: no new product/test/version/catalog implementation or release publication has occurred. Human review of this plan is required before beginning preserved subagent-driven execution.
