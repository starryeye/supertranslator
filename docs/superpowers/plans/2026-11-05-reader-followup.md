# Reader follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Preserve the existing direct implementation preference; no per-task delegation or approval loop.

**Goal:** Fix the three P2 findings and regenerate/publish the same three RFCs without weakening protection.
**Architecture:** Add owned list grouping after reviewed edits/selectors and before sanitation. Reuse existing joins/text_edits for AI editorial changes.
**Tech Stack:** Existing Python, BeautifulSoup, pytest, Playwright, installed wheel and Jekyll.
**Spec:** docs/superpowers/specs/2026-11-05-reader-followup-design.md

## Global Constraints

- English CS/security terms stay English; Python never translates.
- Old outputs, PDF behavior, separate skills, exact link/literal/token protections remain unchanged.
- Use new output folders, patch version 0.10.2; commit and immediately push each commit.
- Preserve direct execution; P3 reference-label consistency is explicitly deferred.

## Review Focus

- Never group across unreviewed prose, headings, literals, or nonempty separators.
- Keep empty anchor IDs, inline subtrees, flattened text, numbering and code exact.
- Existing nth-of-type selectors must resolve before grouping changes sibling positions.
- Existing native/ARIA list ownership must not gain nested redundant lists.
- Regenerated live documents must match the actual installed runtime and receive new visual hashes.

### Task 1: Owned reviewed lists

**Files:** src/supertranslator/reader.py, tests/test_reader.py; README.md and version metadata.
**Interfaces:** `_group_reviewed_lists(article: Tag) -> None`; consume existing data-reader-list markers after text edits and presentation resolution, before sanitation; do not change the review schema.

- [ ] Add failing export tests for ownership of a single reviewed item and contiguous groups with empty ID spacers; assert exact text/IDs/literals.
- [ ] Add boundary tests separating unreviewed prose, pre, headings and nonempty separators; retain native/ARIA parents; verify positional text-edit selectors before wrapping.
- [ ] Run tests/test_reader.py; observe ownership failures, then implement the minimal grouping helper and invocation.
- [ ] Run focused reader/assembly/protection tests and full pytest suite; all must pass.
- [ ] Update docs/version to 0.10.2, final fresh-context branch review; address Important/Critical in one tested pass; commit and immediately push feature branch.

### Task 2: Release, regenerate, compare and publish

**Files:** explicit reader review JSONs/new output directories; existing marketplace metadata and RFC archive/blog only.
**Interfaces:** existing export-reader/qa-reader commands and optional source-bound text_edits, no new fields.

- [ ] Add the §6 join and AI-author the three bounded normative paragraph/list edits with original-language evidence. Existing text-edit protection must accept them without changes.
- [ ] Native Windows/macOS installed-wheel CI passes, release 0.10.2, update marketplace pin; immediately push each commit.
- [ ] Install released runtime, verify package files, regenerate all three to unused output folders; QA, direct changed-paragraph comparison, protected-content and complete layout inspection, fresh visual approvals.
- [ ] Publish the three archive/blog bundles using existing publication mechanism; build Jekyll, push, verify Pages and exact live bytes/CSS/navigation. Preserve review evidence and report deferred P3.
