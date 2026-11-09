# Web Review and Output Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development, the user's preserved execution method, task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind web semantic approval to the exact consumed inputs and reject final HTML that does not contain the approved content.

**Architecture:** A small web snapshot module extends the existing validated processing-source lease to the consumed review inputs. A pure approved-content preparation layer shares legitimate normalization/restoration with assembly, while QA independently checks actual DOM ownership/locations. Evidence and reader export bind the same final bytes; no new renderer or automatic independent review is introduced.

**Tech Stack:** Existing Python 3.11+, BeautifulSoup, SHA-256, anchored filesystem primitives, pytest and Chromium. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-09-reviewed-web-integrity-and-runtime-fixes-design.md`, sections A/B and shared boundaries.

## Global Constraints

- Existing translations can be reused without retranslation, but old web semantic approvals without an input binding cannot be upgraded automatically.
- Never modify user `temp/`, published translations, prior review evidence, or untracked historical runs as implementation fixtures.
- Assembly and QA consume the same held bytes that were validated and revalidate before success/publication; retain existing symlink/reparse, identity, token, literal, structure and CSS guards.
- No machine translation, automatic independent review, automatic semantic reapproval, or translate-review-fix loop.
- PDF semantic/figure/hash contracts, optional-image policy, initial web viewport policy and full-comparison review requirements are unchanged.
- Commit on an isolated work branch and push immediately after each commit. Release/install/main merge/publication are separate.

## Implementation Calls

- In all three companion plans, `<PYTHON>` means `/Users/starryeye/play/supertranslator/.venv/bin/python` on this host. Run from this worktree with `PYTHONPATH=/Users/starryeye/.codex/worktrees/reader-source-structure/supertranslator/src`; verify `supertranslator.__file__` points here, not the canonical editable checkout. Native CI retains its installed-wheel interpreter/provenance checks instead of this local override.
- The inventory file-record hash key is exactly `sha256`.
- Use `web-review-input --run-dir <run>` as a read-only preparation command. Emit exactly one normal status JSON object with an additional `review_input` object; existing commands retain their three-field status JSON.
- New web AI approvals live in `web-review.json`, not the old `review.json` (which remains untouched). Fields are exactly `semantic_input_sha256`, `unresolved_required`, `retries`, `section_findings`; retain all existing six-dimension validation. PDF keeps its existing record names/schema.
- `review_input` fields: `schema_version: "1.0"`, `semantic_input_sha256`, `terminology_policy: {id: "english-technical-first-use-ko-gloss", version: "1.0"}`, `files` sorted uniquely by relative path. File fields: `path`, `byte_length`, lowercase SHA-256. Digest domain is `supertranslator:web-semantic-input:1`; bind that domain, policy and exact sorted file records using canonical UTF-8 JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`).
- Successful source-bundle evidence adds `web_integrity` with exactly `schema_version: "1.0"`, `semantic_input_sha256`, `approval_sha256`, `html_sha256`; all digests are lowercase 64-hex. It describes current validated bytes, not approval authenticity before inspection.
- Use existing processing-source selection with `phase="assemble"` for read-only preparation; no new source-selector phase or review-input file is necessary. Do not write under the run while its complete root inventory is held.

## Review Focus

1. Old unbound approval or changed translation/glossary/source/assignment: reject consumption without modifying history or silently issuing a new AI approval.
2. Valid normal and normalized/preformatted runs, including Unicode/spaces: same source selector, literal bytes and policies as before.
3. Ordinary text, located attributes and nested owners with no protection tokens: inversion/omission/addition must fail, without double-counting child translations.
4. Same-name replacement, late mutation and interruption: no mixed snapshot consumption, foreign deletion or stale public PASS after a failed current attempt.
5. Consumer handoff: a passing manifest with a different HTML hash, or legacy evidence with no binding, cannot become a newly trusted render input.

---

### Task 1: Read-only web semantic input snapshot and preparation command

**Files:** Create `src/supertranslator/web_review.py`, `tests/web_review_fixtures.py`, `tests/test_web_review.py`; modify `src/supertranslator/cli.py`, `src/supertranslator/translations.py`, `tests/test_cli_contract.py` only as needed for the new read-only command and held-byte parsing.

**Interfaces:**
- `hold_web_semantic_inputs(run_dir: Path, *, phase: str = "assemble") -> ContextManager[WebSemanticInputSnapshot]`; snapshot exposes `processing_source`, exact `payloads`, parsed `capture`, `segments`, `zones`, `translations`, `glossary`, `review_input`, and `verify() -> None`.
- `WebSemanticReviewInput.to_dict() -> dict[str, object]` follows the exact preparation schema above. `WebReviewError(ValueError)` covers invalid/changed inputs.
- Snapshot uses `hold_processing_source` and its held readers/anchors. Include every byte file already held by the validated source selection (capture/raw/projected source, captured/generated assets and normalization evidence), then `segments.jsonl`, `glossary.json`, exact `zones/zone-*.json`, `assignments/zone-*.json`, and `translations/zone-*.jsonl` for the validated zone set. Do not invent a `zones.json` file. Validate assignments against existing source/zone records. Approval files and preparation output are excluded from the digest.
- Extract/reuse current value/record validation where necessary; never parse a file by pathname again after validating its held bytes. Retain public `merge_translations` behavior for other callers; a shared byte-record loader may be added for the snapshot, with existing token/coverage validation unchanged.
- Test helper `make_reviewable_web_run(root: Path, *, preformatted: bool = False) -> Path` creates a valid synthetic captured/extracted/zoned/assigned/translated run following existing CLI fixture patterns; no user artifacts or public network. It does not approve meaning.

- [ ] **Write failing tests:** `test_web_review_input_is_read_only_and_canonical` asserts `before_inventory == after_inventory`, stable digest on repeat, exact schema/policy/sorted inventory and one stdout JSON status. `test_web_review_input_changes_with_consumed_bytes` varies translation notes/text, glossary, assignment and validated source/projection fixtures and asserts either a changed digest or the existing source-validation refusal, never the old digest. Include missing/extra zone entries, linked files/ancestors, Unicode/space paths, duplicate JSON keys and same-name replacement; assert the intended diagnostic.
- [ ] **Run RED:** `<PYTHON> -m pytest tests/test_web_review.py tests/test_cli_contract.py -q`; confirm missing new command/module is the relevant failure, not environment setup.
- [ ] **Implement snapshot/command:** use held source payloads plus exact validated child inventories; reject duplicate/ambiguous records. Add a narrowly optional `review_input` parameter to `_emit_status` and have only this command populate it, without extra stdout records or payload-key overrides. Explicitly route this command to `translated-pages`.
- [ ] **Run GREEN:** same focused command, plus existing translation/preformatted contract suites affected by extracted parsers. Confirm normal/preformatted input snapshots are read-only; no approval is generated.
- [ ] **Review, commit, immediately push:** `feat: bind web semantic review inputs`. Controller reviews the full candidate including untracked files before committing; implementer leaves changes uncommitted.

### Task 2: Consume exact bound approval and bind QA evidence/reader input

**Files:** Modify `src/supertranslator/web_review.py`, `cli.py`, `models.py`, `report.py`, `reader.py`, `skills/supertranslator-web/SKILL.md`, `skills/supertranslator-render/references/html.md`, `README.md`; update `tests/test_web_review.py`, `test_cli_contract.py`, `test_pipeline.py`, `test_preformatted_pipeline.py`, `test_reader.py`, `test_render_workflow.py` fixture generators as needed. Do not rewrite committed reference artifacts under `tests/fixtures/` or unrelated PDF modules.

**Interfaces:**
- `hold_web_semantic_approval(snapshot: WebSemanticInputSnapshot) -> ContextManager[WebSemanticApproval]` reads held `web-review.json`, rejects duplicate/extra fields, checks digest/current six-dimension decisions, and exposes `review: MasterReview`, `approval_sha256`, `verify()`. Never accepts the legacy filename as a fallback.
- Add `WebIntegrity` in `models.py` with the exact four evidence fields above and strict `from_dict`/`to_dict`; `QAResult` and `ManifestProvenance` may carry `web_integrity: WebIntegrity | None = None` so non-web and isolated failure writers are not changed. A production passing web publication requires it.
- Production `assemble` and `qa` consume parsed snapshot values and current resolved approval, not separately reopened paths. Reuse `_preformatted_qa_evidence` for ordinary web re-QA too: recoverable prior evidence remains private on a failed/rejected attempt; public PASS is not restored. Reuse its publication/rollback implementation rather than adding a new transaction engine.
- Reader export requires source-bundle `web_integrity.html_sha256` to equal exact input bytes, alongside existing QA/review checks. Missing legacy binding diagnoses fresh semantic review + QA needed; it does not modify old files. Existing reader output `qa-reader` hash/visual contracts remain unchanged. Render still traces to its original canonical source bundle, not blind derivative replay.

- [ ] **Write failing tests:** `test_web_assembly_and_qa_refuse_unbound_or_stale_approval` asserts missing legacy-only approval, wrong digest and unresolved findings fail before publication with old input/approval inventories unchanged. `test_web_snapshot_consumption_rejects_replacement_and_late_mutation` injects source/translation/approval changes after snapshot capture, including after report publication; assert failure, no current public PASS, exact private recovery and preservation of foreign files. Exercise normal and preformatted modes.
- [ ] **Write handoff tests:** `test_reader_refuses_missing_or_mismatched_web_integrity` checks stale `qa_status: passed`, modified index bytes and malformed evidence; valid bound bundle still exports and preserves original bytes. Update synthetic fixtures to issue explicitly TEST ONLY approvals for their exact fixed inputs, not from tampered final output.
- [ ] **Run RED:** `<PYTHON> -m pytest tests/test_web_review.py tests/test_cli_contract.py tests/test_reader.py tests/test_pipeline.py tests/test_preformatted_pipeline.py -q`; distinguish real contract failures from Chromium/loopback restrictions.
- [ ] **Implement consumption/evidence/docs:** preserve existing exit classes (contract 4, assembly 5, QA 6), path routing, PDF formats and existing source guards. Bind exact final HTML only after it is held/verified through publication; failed results carry no new success binding. Web skill inserts `web-review-input` before the existing AI master review and writes `web-review.json`; API reference changes do not add the independent review skill or automatic reapproval. Explain the legacy one-time AI re-review and preservation of old artifacts.
- [ ] **Run GREEN:** focused suites above plus affected report/render tests and skill validators. Old reader artifacts remain readable, not migrated. Mark API/reference validation as such; do not claim fresh behavioral quality evaluations that were not run.
- [ ] **Review, commit, immediately push:** `fix: require bound web approval and current output evidence`.

### Task 3: Compare actual final owned content against approved payloads

**Files:** Create `src/supertranslator/web_content.py`, `tests/test_web_content.py`; modify `assemble.py`, `qa.py`, `models.py`, `cli.py`; update QA/pipeline/render fixture helpers and focused assertions in `tests/test_qa.py`, `tests/test_assemble.py`, `tests/test_pipeline.py`, `tests/test_preformatted_pipeline.py`, `tests/test_render_workflow.py` where needed.

**Interfaces:**
- `ApprovedWebContent` stores `attributes: dict[str, str]`, `content_html: str | None` for one source-owned target.
- `prepare_approved_web_content(source_html: str, segments: Mapping[str, Segment], translations: Mapping[str, Translation], glossary: Mapping[str, str]) -> dict[str, ApprovedWebContent]` derives exact document order, legitimate first-use normalization, token restoration and located payloads. Assembly and QA reuse this input transformation; QA does not call the output-writing assembler or merely trust its output hash.
- `check_approved_web_content(source_html: str, output_html: str, segments: Mapping[str, Segment], expected: Mapping[str, ApprovedWebContent]) -> list[Finding]` independently checks real corresponding DOM locations. Mask separately owned descendants on both sides consistently, preserving ownership/order; check their own content separately. Verify non-owned source/literal content and reject added prose outside target owners except fixed backend metadata/attribution. No broad whitespace normalization.
- `QAInputs` carries `target_segments` and `approved_contents` (optional construction defaults may preserve existing call syntax, but absent/incomplete values produce a required `approved-content-contract` finding). Actual mismatches produce required `approved-content-integrity` with IDs/locations/hashes, not full document dumps. These checks run before browser QA. Existing findings/guards are retained, not replaced.

- [ ] **Write failing tests:** `test_plain_text_inversion_fails_full_qa` uses the independently fixed approved 수락 payload and altered 거부 final, asserts `not result.passed` and `approved-content-integrity`; the untouched control asserts pass with real Chromium. `test_owned_content_rejects_omission_addition_and_duplication` covers ordinary text with no protected tokens, extra prose outside target owners, translated title/alt/labels, and nested parent/link ownership.
- [ ] **Write exactness tests:** `test_expected_content_preserves_normalization_and_literals` accepts legitimate glossary first-use, entities, source IDs/inline structure and correct nested child translation exactly once; rejects whitespace/code/ASCII changes, wrong attribute placement and hidden comparison bypass. Run corresponding normalized/preformatted literal cases. Test absent/partial expected contracts explicitly; never derive expected values from the altered output to make a negative test pass.
- [ ] **Run RED:** `<PYTHON> -m pytest tests/test_web_content.py tests/test_qa.py tests/test_assemble.py -q` and the old inversion reproduction in a separate synthetic copy. Confirm wrong final fails for the intended new check, not browser startup or missing approval.
- [ ] **Implement the pure preparation and independent comparator:** retain assembler's marker/topology/security validation. Only share legitimate input transforms; actual location matching and expected-vs-actual comparison must not certify whatever the renderer emitted. Use explicit DOM/entity normalization with literal exactness, not fuzzy similarity or language-model calls.
- [ ] **Run GREEN:** affected QA/assembly/pipeline/render/preformatted suites, both synthetic browser controls, and evidence/reader tests. Assert approved inputs unchanged and no public PASS on changed final/late output mutation. Tests must retain their original independent protected-token/asset/structure assertions.
- [ ] **Review, commit, immediately push:** `fix: verify approved web content in final HTML`.

## Handoff / final gates

- [ ] Self-review every spec requirement against its owning task and ensure shared types/signatures agree. No gap deferred under a passing claim.
- [ ] User confirms this implementation plan before production code changes. Preserve subagent-driven execution; no repeated continuation prompts between approved tasks.
- [ ] After process and CI companion plans are integrated, run the full project suite once on the final candidate with authorized Chromium/loopback, both native CI matrices, and a whole-branch independent review. Use focused runs per task, not a 20-minute full suite per edit.
- [ ] Record actual skips/failures, source/interpreter provenance, exact commit/push, and release/install/main merge status separately. Never use real user artifacts as test fixtures.
