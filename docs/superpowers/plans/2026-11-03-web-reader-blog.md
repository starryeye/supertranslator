# Reviewed Reading Editions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce readable reviewed HTML editions and publish three RFCs in the existing blog.

**Architecture:** An additive deterministic reader exporter consumes an existing reviewed
bundle plus an exact-byte-bound editorial review. Standalone and Jekyll fragment outputs
share one article and stylesheet. Original capture/translation and legacy QA remain unchanged.

**Tech Stack:** Python, BeautifulSoup, existing filesystem guards, Playwright, Jekyll.

**Spec:** docs/superpowers/specs/2026-11-03-web-reader-blog-design.md

## Global Constraints

- No machine translation; reuse reviewed AI translations and compare joined paragraphs.
- Preserve existing HTML workflow, historical runs, protected content and blog theme.
- New outputs only; exact input digest binding and safe local asset handling.
- Body 18px desktop / 16px narrow, line-height 1.75, maximum width 48rem.
- Only RFC 6749, 6750, 9700; commit and immediately push every commit.

## Review Focus

- Ambiguous content selectors must fail before output creation.
- Joining across unreviewed content must fail, not lose content.
- Code/diagram text, inline destinations and page anchors must survive transformations.
- Traversal/symlink assets and executable markup must not enter reading editions.
- Blog templating must not interpret literal technical text as Liquid or duplicate IDs.

### Task 1: Reader export and browser regression tests

**Files:** Create `src/supertranslator/reader.py`, `web_assets/reader.css`,
`tests/test_reader.py`; modify `cli.py`, `pyproject.toml`, README and web CI.

**Interfaces:** `export_reader(input_dir: Path, review_path: Path, output_dir: Path) -> Path`.
CLI: `export-reader --input-dir PATH --review PATH --output-dir NEW_PATH`.
`reader_qa.py` exposes `qa_reader(output_dir: Path, visual_review: Path | None = None) -> dict`;
CLI `qa-reader --output-dir PATH [--visual-review PATH]`.
Review: schema_version, input_html_sha256, content_selector, title, removals, joins,
heading_levels, list_items. Each join has selectors; all transformations recorded.

- [ ] Write failing tests for clean article export, bound review, ambiguous selectors,
  unsafe assets, nonadjacent joins, anchor/literal preservation, no overwrite and CLI.
- [ ] Run tests and observe the absent implementation fail.
- [ ] Implement exporter/CSS/CLI, with unchanged source-mode behavior.
- [ ] Verify real Chromium desktop/mobile typography and local scrolling.
- [ ] Run focused and full suites; review whole branch independently once.
- [ ] Commit and immediately push feature branch.

### Task 2: Regenerate and verify three reading editions

**Files:** New per-document review JSON and reader outputs; `standard-document/rfc/`.

**Interfaces:** Task 1 CLI emits exact reusable `article.html` and asset manifest.

- [ ] Inspect every furniture removal and paragraph join against source and translation.
- [ ] Generate fresh directories using the plugin, without overwriting historical runs.
- [ ] Verify all retained article text/links/literals and input/output digests.
- [ ] Inspect desktop/mobile full-page contact sheets and matching source regions.
- [ ] Update stored editions and reports, commit and immediately push.

### Task 3: Publish full texts in existing blog

**Files:** Existing blog `_posts/Blog/` two removals; three `_posts/Standards/*.html`,
reader stylesheet/assets and review evidence; category/navigation adjustments only.

**Interfaces:** Task 2 article bytes are embedded without a second translation.

- [ ] Build existing Jekyll baseline and record available toolchain.
- [ ] Export three HTML posts with explicit permalinks and safe Liquid handling.
- [ ] Remove precisely the two retired posts; retain Git history and existing theme.
- [ ] Build and verify post content, links, home/archive, dark-mode contrast and mobile.
- [ ] Commit/push and check successful Pages deployment and live content.
- [ ] Release additive plugin version 0.9.0, tag and update marketplace pin after gates pass.
