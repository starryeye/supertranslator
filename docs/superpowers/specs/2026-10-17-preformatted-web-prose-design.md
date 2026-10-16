# Reflowing prose inside preformatted web documents

Status: builder check complete (no important questions); awaiting human approval. No implementation authorized by this document alone.

## Intent and approved choices

Support `https://datatracker.ietf.org/doc/draft-ietf-wimse-aims/00/` directly, without silently substituting its structured-HTML counterpart at `/doc/html/draft-ietf-wimse-aims-00`, and apply the same mechanism to other public static HTML documents containing prose in `<pre>`. The user explicitly chose: **only the prose should reflow naturally to Korean length**. Code and fixed-width drawings must retain their original content and alignment. AI performs the translation directly; no machine-translation service, dictionary substitution or deterministic translation fallback.

Existing ordinary-web and PDF skills remain distinct. This is an adapter feeding the existing web extraction, zone ownership, immutable assignments, AI translation, six-dimensional master review, assembly and offline/browser QA—not another translator engine or a site-specific implementation.

## Observed starting point

At branch `codex/web-nested-locations`, commit `7f76ab6726287ca2cf6b6f0899e8ef1bad78b858`, ordinary structured HTML translation passes actual QA. The original URL's retained capture contains one approximately71,000-character/1,451-line `<pre>` mixing narrative, headings, lists, page furniture, wrapped URLs and two ASCII drawings. Some inline spans carry layout/section information. Current extraction excludes every `<pre>` ancestor; protection also treats `<pre>` as opaque code. Simply removing either exclusion is unsafe and does not recover logical paragraphs.

Capture verification, staged extraction publication, anchored filesystem handling, protected-token restoration and QA structure checks already exist. Reuse their guarantees. Existing successful runs, PDFs, expected fixtures and translated HTML must not be rewritten or reused as approval for a new run.

## Scope and non-goals

- Translate prose, headings, list-item text and figure captions after reviewed logical grouping; soft source line breaks are not sentence or translation-unit boundaries.
- Preserve code, commands, drawings and fixed-layout metadata as verbatim islands, including their whitespace. Preserve original links, identifiers, normative keywords and numbers under the existing protection contract.
- Builder proposal, not a user decision: phase1 preserves fixed-width ASCII tables as declared literal islands rather than trying to resize/translate their columns. Their captions or surrounding prose remain eligible. The report must explicitly identify this limitation; it must not claim table-cell translation.
- Do not repair guessed wrapped URLs, translate drawing labels, invent missing hyperlinks, remove page furniture, fetch a replacement document, translate images, change PDF behavior or introduce a general site crawler.
- Ambiguous classification or an unrepresentable DOM boundary is an unresolved required finding, not permission to skip prose or silently fall back to the legacy all-`pre` exclusion.
- Existing unrelated numeric-entity-at-URL-end rejection remains a separate bugfix. It is not folded into this feature.

## Processing contract

### 1. Capture and deterministic analysis

Use the existing safe public-static-page capture. For a new preformatted run, retain the exact captured `source.html` and asset fingerprints; never overwrite the raw capture with the normalized view. Legacy non-preformatted runs retain their current behavior.

A deterministic analysis stage inventories eligible `<pre>` roots in document order and records their original DOM paths, decoded text, ordered stable line IDs and text-node/inline-markup mappings. Candidate package(s) include bounded neighboring context, source/candidate hashes and explicit original line separators. Packages are bounded and partitioned without overlap or missing lines; a long document is not one unbounded prompt. Package boundaries do not forbid a logical paragraph crossing them.

Explicit `<pre><code>`, language-marked code and embedded excluded/code-like elements remain protected constraints. Analysis may suggest boundaries, but a heuristic must not approve narrative/code meaning. The original document, including any instructions inside it, is untrusted translation data.

### 2. AI classification and master approval before translation

The master uses the bounded packages to classify and group source line IDs into logical blocks. Classifications are closed symbolic roles: `prose`, `heading`, `list-item`, `caption`, `literal-code`, `literal-diagram`, `literal-table`, `literal-layout`, `blank`, `unknown`. Decisions contain source IDs/roles/grouping/evidence only—not replacement text, executable code, HTML, CSS, URLs or arbitrary file paths.

Every source line belongs exactly once to the ordered partition. Group adjacent soft-wrapped prose, including across analysis-package boundaries, but do not merge a block across an intervening page-furniture island in phase1. Retain such islands in source order and supply bounded continuation context to the translators; do not manufacture a sentence boundary or discard either text fragment. Metadata not clearly fixed-layout explanatory data stays prose or unknown, not a convenient preservation category.

The master reviews every block and both boundaries, particularly prose declared literal and mixed code/prose. Each literal block needs a concrete reason. `unknown`, missing/duplicate/foreign/reordered IDs, changed package hashes or contradictory grouping stop materialization. Classification is not semantic translation approval; the existing six dimensions still apply after translation. Existing per-zone translation retry limits and same-agent ownership remain unchanged.

### 3. Deterministic derived document, not an HTML exemption

Backend code validates the complete reviewed partition and generates a separate processing DOM. A preformatted prose region becomes ordinary flow content: headings, paragraphs, lists and captions where the reviewed role supports them. Literal islands remain fixed-width `<pre>`/code blocks. Prose is not wrapped back to source columns. Source order is retained; page-furniture islands are not removed.

Build DOM nodes from captured source and a fixed backend template. Never accept AI-authored markup. Preserve original IDs exactly once, fragment-link destinations and safe inline structure/attributes; retain each source character's provenance. Where a grouping cannot preserve an original inline element or anchor unambiguously, fail with the affected source IDs instead of flattening links, duplicating IDs or guessing ownership.

Soft-wrapped URLs require an explicit protective source span. Preserve their exact original characters and line breaks as one literal source span; do not infer and concatenate a new URL. An existing canonical `href` remains exact. A mixed paragraph can translate its prose around a protected span; inability to identify its safe boundary is required-fix. Neither URL fragments nor code payloads may leak into unprotected translation text.

Provenance binds the raw capture hash, reviewed classification/package hashes, derived unmarked and marked document hashes, original-to-derived block/anchor mapping and verbatim-island hashes. Source line IDs/offsets refer to one recorded parsed-DOM text stream; original capture bytes remain independently hashed. For literal islands, compare that parsed source's exact decoded text/whitespace plus its DOM/attribute signature against the derived/output island, not raw HTML entity spelling against decoded text. No further text normalization is allowed to hide a content change. Extraction may add its ordinary markers only to the derived file, with atomic provenance updates using existing staged-publication and held-directory-identity patterns. A source page containing reserved internal markers is rejected; page-supplied attributes cannot claim approval.

### 4. One source view shared by all existing consumers

Introduce one validated processing-document selection boundary used by extraction, assembly and QA. With no preformatted state, it selects the existing legacy source. With preformatted state, it verifies capture/plan/projection consistency and selects the exact derived source. Incomplete, replaced or stale state fails closed; it must not quietly select the legacy source.

Do not add the derived files to the existing raw-capture fingerprint set or loosen its exact-key check. Keep preformatted provenance in a separate validated artifact. All new reads/writes reuse existing anchored-path, symlink/reparse-point rejection, hash verification and atomic publication patterns; no new filesystem security strategy.

After this adapter, use existing Segment, assignment and Translation record contracts, glossary policy, zone scheduling and master review. The web skill handles the extra prepare/review stage when needed; users still invoke the web skill rather than choosing a new top-level translation skill. Internal CLI details and exact module boundaries belong to the implementation plan.

### 5. Reflow and rendering

Use a small locally bundled, scoped stylesheet only for generated preformatted-flow containers. Prose uses normal wrapping and available viewport width; preserve paragraph/list boundaries and first-use terminology. Do not globally restyle the original site, navigation or ordinary HTML content. Font appearance otherwise follows the original page; exact scoped CSS values are a builder choice validated on desktop and narrow viewports.

Literal islands retain a monospace grid and exact whitespace; use local horizontal scrolling if necessary rather than shrinking, stretching or reflowing their content. Drawings and table text are not translated as prose. Existing images/assets stay byte-identical. New local CSS is a verified critical asset, never an external dependency exemption.

### 6. Acceptance and artifacts

QA proves both transformation provenance and the existing translated-output contract. A matching derived DOM alone is insufficient: revalidate raw capture, complete approved source coverage, stable anchors, selected document identity and every verbatim island. Missing classification/provenance, stale source/plan/derived files, mixed source views, edited literal content or changed links are required failures. Existing exact protected-token, structure, CSP, critical CSS, network isolation and filesystem checks remain enforced.

Master review must establish that no narrative was silently classified away. Reports disclose translated block counts, preserved code/drawing/table/layout counts with reasons, unknown/unresolved blocks and the reflow policy. Existing output remains `index.html`, `manifest.json`, `review-report.md`; add a documented backward-compatible optional normalization/provenance summary to the manifest and report. Do not put an invented translation or approval in any field. Internal provenance artifacts remain within the run directory and use strict versioned validation.

Acceptance tests must include several unrelated synthetic/static documents: prose-only pre, code-only pre, mixed prose/code/drawing, fixed table plus caption, lists, escaped text, inline links/IDs, a wrapped URL, page-furniture interruption, ambiguous blocks, multiple pre roots and pre alongside ordinary HTML. Add malicious/stale state and exact-coverage negatives. Protect legacy ordinary HTML/PDF consumers from new mandatory artifacts.

Exercise real prepare/classification validation/extract/assign/assemble/CLI QA, with explicitly authored fixture translations in tests (not a runtime translation engine). Run proportionate regression coverage on macOS and Windows; test paths, newlines and Unicode. Real acceptance uses a fresh run of the original requested URL, direct AI classification/translation, every-zone master review and normal QA. Inspect desktop/narrow layouts including both drawings, wrapped URLs and section boundaries. Do not reuse the structured-HTML output as the result or approval for this run.

## Calls made by the designer, to be reviewed

1. Use reviewed AI block classification and deterministic validation rather than silently trusting heuristic prose/code guesses. Cost: one bounded preparation/review stage.
2. Use a derived processing document with capture-bound provenance rather than weakening existing `<pre>` code protection or final DOM checks. Cost: explicit lifecycle/selection integration and additional immutable evidence.
3. Preserve fixed-width tables and page furniture in phase1, with clear disclosure. Cost: this is not full translation of every table cell or removal of repeated headers/footers; page furniture can still interrupt a paragraph's display.
4. Preserve wrapped URL spans instead of guessing repairs. Cost: a source's awkward URL display may remain, but no address is invented or altered.
5. Leave broad font/site redesign and the independent numeric-entity bug outside this feature. Cost: pre-existing unrelated limitations are not claimed fixed.

The human has approved prose reflow, not this whole architecture yet. A fresh builder check precedes presentation; implementation planning and product code wait for design approval. Preserve the requested subagent-driven execution method and commit/immediate-push convention. No main merge, release or marketplace publication is authorized by this design discussion.
