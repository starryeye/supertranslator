# Reviewed web integrity and bounded runtime fixes

Status: design approved after the legacy-review policy explanation; implementation
plans require confirmation before production changes.
Independent builder check: nothing important left to decide before planning.
Base: `45ecdc51096d74bcd66ccd436afa30b4fd40f78e`.

## Intent and approved direction

The user asked to improve the plugin according to the multi-perspective review.
The recommended order is web approval/output integrity, small process/CI fixes,
then real-document use and reuse guidance. This design covers the first two;
it is not a request to expand the renderer or add an automatic review/fix loop.

The user wants AI translation, preserved technical meaning/structure/assets,
intentional English CS terms, and Windows/macOS operation. Code should prove
that reviewed inputs are the inputs consumed, and that their approved translation
is the text actually output. It does not decide whether the AI translation is good.

## Confirmed evidence

- Web `_read_review` validates decisions/zone coverage but no reviewed-input digest.
  `_assemble_selected_command` currently does not consume semantic approval.
- With the same source, approved translation and TEST ONLY semantic review,
  actual `run_qa` accepted both the approved 수락 sentence and an inverted 거부
  final sentence. The controller independently reproduced this with Chromium.
- `_run_poppler` can leave its own child alive on interruption or a render-output
  monitoring error. Isolated real-process probes demonstrated both and cleaned up.
- `test_render_workflow.py` and `test_review_skill_contract.py` are absent from
  both explicit CI test lists. The HTML recipe helper also overwrites one QA command.

Detailed read-only review/probes are retained locally at
`/private/tmp/supertranslator-multiview-review-20261109.AgVxoO/`.
The reproductions are synthetic, not evidence that an existing publication is wrong.

## Approaches and implementation calls

Two web approaches were considered:

1. Record an assembly-time output digest and reject later output changes. This
   catches post-assembly mutation, but alone does not verify that the assembler
   placed the approved text correctly, nor bind prior approval to current inputs.
2. Bind semantic approval to exact inputs, then independently compare approved
   restored/normalized content with its actual final DOM locations. This checks
   both boundaries, including ordinary text without protected tokens.

The assistant chooses approach 2, consistent with the user's requested fix.
Share only the existing legitimate terminology normalization, token restoration
and location-payload interpretation where useful. Do not make QA merely hash
whatever the assembler emitted, or run an output-writing assembly inside QA.
Do not introduce a second renderer or duplicate the large PDF review engine.

## A. Web semantic approval bound to consumed inputs

Provide a web-specific semantic-review preparation command and small input-binding
module using existing anchored-file/validated-source primitives. The prepared
inventory records exact byte lengths and SHA-256s, plus a versioned policy identity.

Bind the actual validated source selection/capture provenance, projected source
and normalization evidence when applicable, segments, zones, assignments,
translation files, and glossary consumed by this run. Use exact validated file
sets, not arbitrary directory contents. Generated review-input metadata and the
approval itself are not part of a self-referential digest.

The master AI reviews those exact inputs and records the prepared digest alongside
the existing six-dimension decisions. The preparation command does not approve
meaning or manufacture review evidence.

Assembly and QA require resolved approval for the same current digest. They parse
and consume the same held input bytes that were validated, retain existing path,
symlink/reparse and replacement guards, and revalidate before success/publication.
Source, translation, glossary, assignment or relevant normalization changes fail
closed; recomputing a digest must never silently re-sign a prior AI approval.

### Approved compatibility policy

Old completed artifacts stay unchanged and readable. Existing translations can
be reused without retranslation, but old web semantic approvals without an input
binding cannot be upgraded automatically: new assembly/QA requires a fresh AI
semantic review of the existing exact inputs. Missing private inputs are diagnosed,
not recreated by implicit extraction or translation. No historical output rewrite
or run migration is performed merely by installing the update.

## B. Approved content compared with actual final HTML

Derive the expected owned text, translated attributes and inline fragments from
the validated approved payload after the same legitimate glossary normalization
and token restoration used for assembly. Compare them to their actual final DOM
locations, retaining nested ownership and checking each location exactly once.

Catch inversion, replacement, omission, duplication and unapproved addition, with
and without protected tokens. Handle located attributes, nested links/parents,
inline markup and source-preserved opaque/literal content. Normalization must be
explicit and narrow; do not broadly collapse whitespace in code/ASCII/literals
or ignore translated attributes. Existing protection/structure/CSS checks remain.

Production QA must not bypass this comparison because an expected value is absent.
Failure gives located segment/attribute diagnostics and no current passing result.
Diagnostics should avoid dumping complete documents or sensitive prose.

Successful evidence binds the reviewed-input identity and exact final HTML bytes.
Reader export/rerender must verify that the QA evidence applies to its bound input
bundle, rather than accepting a stale `qa_status: passed` after that HTML changed.
Already reviewed reader revisions retain their own existing exact-byte contracts;
this does not authorize semantic changes in render-only work.

A failed/rejected new QA attempt cannot publish fresh passing evidence or relabel
stale evidence as current. Preserve existing transactional publication/rollback
strategies and the user's historical artifacts; exact handling of existing evidence
must be specified in the implementation plan, not replaced by broad deletion.

## C. External-process cleanup

Keep `_run_poppler` and its current limits. On every exit path, terminate/reap only
the child it created if still alive. Normal completion, timeout, output-budget or
monitor failure, launch failure and interruption all have covering tests.
Preserve the original failure/interrupt; cleanup must not swallow it or replace it
with a secondary error. Do not kill unrelated processes or change ownership guards.

## D. CI and recipe coverage

Add the two new contract/workflow test files to existing appropriate native CI
jobs with their already installed Chromium/Poppler dependencies. Include new web
integrity regressions in the relevant job. Keep installed-wheel provenance checks.
Retain ordered/distinct HTML QA recipe stages and exercise initial QA and final QA
using explicitly synthetic fresh visual evidence in tests. No new CI framework.

## Boundaries and deferred work

- No machine translation, automatic independent review, automatic semantic
  reapproval, or translate-review-fix loop.
- No renderer rewrite, universal document model, OCR, arbitrary layout settings,
  or changes to PDF semantic/figure/hash contracts.
- No change in this batch to optional-image policy, initial web viewport/visual
  policy, terminology preferences, or the full-comparison review requirements.
- Private-input locator/archiving guidance and real long-document completion,
  resume and cost evaluation follow these confirmed fixes; do not build a new
  archive/orchestration framework in this batch.
- Never modify user `temp/`, published translations, prior review evidence, or
  untracked historical runs as implementation fixtures.
- Release, marketplace/cache installation and public publication are separate.
  Commit on an isolated work branch and push immediately after each commit.

## Verification and execution

Write regression failures first for each distinct boundary. Include the exact
approved-vs-final inversion, changed approval inputs, Unicode/space paths,
normal and preformatted source modes, nested content/attributes, interrupted
consumption/publication, and unchanged successful runs. Negative tests must prove
the intended contract failed, not pass on an unrelated early environment error.

Use focused suites per task, independent scoped reviews, then one full project
suite on the final candidate, the existing Windows/macOS CI, and a fresh synthetic
browser reproduction that now rejects the old bad final but accepts the control.
Keep approvals marked TEST ONLY. Report successful tests separately from actual
AI quality or long-book completion claims.

Preserve the user's subagent-driven implementation method. Web integrity is the
first independently testable deliverable; process cleanup and CI are bounded
follow-ups with their own test/review scopes. No implementation starts before
this design and the subsequent implementation plan are approved.
