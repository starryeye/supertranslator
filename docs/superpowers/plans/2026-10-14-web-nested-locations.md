# Nested Web Translation Locations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox syntax for tracking.

**Goal:** Unblock the official AIMS 00 HTML translation by fixing generic overlapping body/attribute location ownership without losing visible text.

**Architecture:** Assign each eligible visible text span to exactly one translation location before marking the DOM. Attribute-bearing nested elements must not make their body disappear behind another location's protected placeholder. Keep parent prose only when it owns independent text, and retain located attribute/content restoration contracts.

**Tech Stack:** Existing Python >=3.11, BeautifulSoup/lxml, pytest and the existing CLI; no new dependency.

**Spec:** Human-approved small-change description in the 2026-10-14 chat (async call_4982e4dfe5ae46819f6dc482f2f45045). Human explicitly approved this implementation plan with “네” on 2026-10-14 before implementation.

## Global Constraints

- Body and translatable attributes each appear exactly once; no skipped non-empty parent text or placeholder-only target.
- Keep URL, code, normative keyword, SVG/math, translate=no and reserved-marker protections.
- Do not change CSS capture rules, preformatted-content policy, schema, resource limits, versions, dependencies or existing fixture outputs.
- No document-, URL-, identifier-, sentence- or site-specific extraction exception.
- Retain old runs and private evidence; every commit is immediately pushed. Root owns review, commit and push; no main merge or release publication in this task.
- Official translation uses the same version's official https://datatracker.ietf.org/doc/html/draft-ietf-wimse-aims-00 endpoint, whose HTML has normal paragraphs and no missing rfc-local.css reference. It is an explicitly announced equivalent official document endpoint, not a silent version upgrade.

## Review Focus

1. A table cell containing only a titled link must not fail or lose its body.
2. Parent text before/after a titled child must survive exactly once.
3. Multi-level titled/aria-labeled elements must not duplicate text or reorder restoration.
4. Attribute-only images and protected-only/excluded descendants retain existing behavior.
5. Nested block/list/table ownership, table row semantic types and idempotent extraction remain compatible.

### Task 1: Fix nested body/attribute ownership

**Files:** Modify src/web_translator/extract.py; add regressions in tests/test_extract.py and tests/test_assemble.py only. The plan document is controller-owned.

**Interfaces:** Keep extract_segments(source_html: Path, segments_path: Path) -> list[Segment] and public model/assembly APIs unchanged. Downstream plan-zones, prepare-assignments, deterministic translation validation and assembly consume unchanged contracts.

- [ ] **Step 1:** Write independent literal regressions for `<td><a href="https://example.com/spec" title="Agent authentication">agent-spec</a></td>` and mixed parent prose. Restore both source and translated body/attributes through real assembly; assert each visible body and attribute exactly once, link href unchanged, no empty parent target, table row type retained wherever applicable. Add bounded multi-level and exclusion cases for the five review classes; never use the producer to compute expected text.
- [ ] **Step 2:** Run new regressions first with PYTHONPATH=src /Users/starryeye/play/web-translator/.venv/bin/python -m pytest <exact new test node IDs> -q. Require failures caused by the actual ownership/loss defect, not collection or fixture errors; preserve true exits/logs/XML.
- [ ] **Step 3:** Make the minimal ownership correction in extract.py. Do not suppress the invariant error, skip non-empty content, add permissive retries or alter protected-token rules.
- [ ] **Step 4:** Run new cases, then tests/test_extract.py tests/test_assemble.py tests/test_pipeline.py tests/test_cli_contract.py once. Run the complete non-live suite once on the frozen code with `PYTHONPATH=src P -m pytest -m 'not live' -q --junitxml <private XML>`. Report every skip/failure and exact failed IDs; separate any permission-only rerun. No repeated baseline/full-suite replay per review round.
- [ ] **Step 5:** Root reads raw evidence and independently freezes exact diff/stat/file hashes; independent task review, then whole-branch review before commit. Root commits the reviewed files using existing conventions and immediately pushes codex/web-nested-locations. Existing branch/main/tag and all user outputs remain intact.
- [ ] **Step 6:** With PYTHONPATH pointing to the reviewed worktree's src, capture/extract the official Datatracker HTML into a new run under the primary workspace. Require source-body coverage of Abstract, Introduction, Agent Identity Management System and later Security/Privacy/References before preparing assignments. AI translators own isolated zones; master reviews all six dimensions, normalizes English-first terminology and runs assembly/QA. Do not call a partial artifact complete. Original-page preformatted prose remains a separate design task, not fixed by this deliverable.

## Controller self-review

The one task covers all five review classes, keeps public interfaces unchanged, and has a real extract/assemble regression plus affected and whole-project gates. CSS and preformatted support are excluded rather than implicitly weakened. Translation continues only after review; original-link support remains explicitly unfinished until its separate design is approved and implemented.
