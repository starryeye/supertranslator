# Reader polish implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. The user requested direct implementation and publication; preserve that execution preference.

**Goal:** Fix the four accepted review findings without translating English nouns.
**Architecture:** Add optional bound sentence edits and structural presentation review to the existing reader exporter; keep all other pipelines unchanged.
**Tech Stack:** Existing Python/BeautifulSoup, native HTML details, scoped CSS, Playwright, existing Jekyll.
**Spec:** docs/superpowers/specs/2026-11-05-reader-polish-design.md

## Global Constraints

- English-first nouns and two separate skills remain unchanged; no PDF modifications or book/RFC-specific code.
- AI supplies only source-compared sentence edits; deterministic code does not translate.
- Old reviews/outputs remain supported; no overwrite, hash weakening or historical-run edits.
- Body 18px desktop / 16px mobile; native accessible navigation, literal preservation.
- Only RFC 6749/6750/9700; every commit immediately pushed; release 0.10.0 after gates.

## Review Focus

- Edits must not change nested inline code/links, normative force or English atoms.
- Presentation choices must not swallow arbitrary prose, IDs or original links.
- Generated anchors must not collide or navigate to archived headings.
- Browser behavior must work in existing themes and with no JavaScript.
- Old exact digest checks and Windows byte encoding remain enforced.

### Task 1: Bound AI sentence corrections

**Files:** create `src/supertranslator/reader_editing.py`; modify `reader.py`, `reader_qa.py`, README; add tests to `tests/test_reader.py`.
**Interfaces:** optional review `text_edits`; helper `apply_text_edits(article, edits)` called after joins before sanitizer; no-op for old reviews. Record edits in output manifest and explain limited semantic evidence in report.

- [ ] Write failures for grammatical correction with unchanged English nouns, intact moved code/reference subtrees, protected-token loss/change, stale HTML hash, overlapping edits and absent semantic evidence.
- [ ] Run `PYTHONPATH=src <python> -m pytest tests/test_reader.py -q`; observe failures for unsupported review fields.
- [ ] Implement review validation and edits with unchanged default behavior.
- [ ] Run reader tests plus protection/assembly tests; all pass.

### Task 2: Readable presentation and navigation

**Files:** create `src/supertranslator/reader_layout.py`; modify `reader.py`, reader CSS, `tests/test_reader.py`, README/version metadata.
**Interfaces:** optional review `presentation`; helper `apply_presentation(article, review)` after sanitation. Native `.st-toc`, `.st-document-info`, `.st-document-title`, `.st-permalink`, embedding wrapper `.st-reader-embed`.

- [ ] Write failures for collision-safe linked hierarchical TOC; source TOC/metadata content retained, no archived heading links; malformed/root/overlapping/unsafe selections rejected.
- [ ] Write real-browser failures for collapsed TOC height, intact standalone title/hidden embedded title, 18/16px prose, subdued/focusable pilcrow.
- [ ] Implement helpers and scoped CSS; run focused and full test suite.
- [ ] Set version 0.10.0, README contract, keep current web CI installed-reader selection; check version/diff, commit and immediately push branch.
- [ ] Fresh-context whole-branch review; address Important/Critical findings in one RED→GREEN fix bundle. Record deferred minors and decisions.

### Task 3: Release, regenerate and publish

**Files:** generated review JSON/artifacts, three archive directories, existing Jekyll posts/assets, marketplace pin/validator/version fixtures.
**Interfaces:** installed 0.10.0 CLI `export-reader`, `qa-reader`; article fragment and CSS reused without a second transformation of body prose.

- [ ] Source-compare the two sentence edits keeping English nouns; construct explicit metadata/title/TOC selections.
- [ ] Verify native Windows/macOS CI; fast-forward main, tag/release, update marketplace with tests and immutable SHA; each commit immediately pushed.
- [ ] Upgrade marketplace/plugin and workspace runtime through supported interfaces; verify actual installed package code.
- [ ] Export to fresh folders, run QA, inspect screenshots and source/text/link preservation, issue new exact visual approval, rerun final QA.
- [ ] Update archive and blog from actual outputs, add explicit embedding wrapper, build and check initial content position and navigation at 1440/768/390px.
- [ ] Commit/immediately push both sites, verify Pages success and exact live text/assets/navigation. Preserve reports and execution evidence; synchronize canonical checkout without touching unrelated PDF worktree.
