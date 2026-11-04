# supertranslator

`supertranslator` is a cross-platform Codex plugin for Windows and macOS with two clearly
selectable workflows:

- `supertranslator-web` translates one supported public static HTML URL into an offline Korean
  bundle while preserving its DOM, links, styles, and captured assets.
- `supertranslator-pdf` translates one local text-selectable PDF, attached text-selectable PDF,
  or public HTTP(S) PDF URL into a reviewed Korean PDF.

Both workflows use the same Python package, immutable semantic zones, translation
contract, glossary, validation, and master-review rubric. Format-specific commands handle
HTML or PDF acquisition, extraction, assembly, and QA.

## Setup

### Breaking rename in 0.8.0

The repository is now [starryeye/supertranslator](https://github.com/starryeye/supertranslator).
Remove the old `web-translator@starryeye` plugin and install `supertranslator@starryeye`.
Use a new workspace/run with `supertranslator-web` or `supertranslator-pdf`, the
`supertranslator` command, or `python -m supertranslator`. For a Python installation,
uninstall the `web-translator` distribution before installing `supertranslator`.
Old commands (`web-translator`, `python -m web_translator`), skill names
(`web-translator`, `pdf-translator`), and unfinished `.web-translator/runs` are not
supported 0.8.0 interfaces. There are no aliases or automatic run migration/resume.
Keep historical runs and completed outputs unchanged; new runs use `.supertranslator/runs`.
After moving a local checkout to its new real path, recreate its virtual environment
there rather than reusing old absolute interpreter paths.

Use Python 3.11 or newer. On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m playwright install chromium
# Install Poppler, then open a new PowerShell so pdfinfo.exe and pdftoppm.exe are on PATH.
winget install -e --id oschwartz10612.Poppler
```

On macOS with a POSIX shell:

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[test]"
./.venv/bin/python -m playwright install chromium
brew install poppler
```

Chromium supports HTML layout, offline, and screenshot QA. Poppler provides `pdfinfo` and
`pdftoppm` for PDF inspection and rendering. If the Windows package manager is unavailable,
install a trusted Poppler distribution and add its `Library\bin` directory to `PATH`.
Confirm both executables are available before starting a PDF run.

## Versioning

The release version is declared in `.codex-plugin/plugin.json` and mirrored in
`pyproject.toml` and `src/supertranslator/__init__.py`. Keep all three synchronized
with the standard-library-only helper. Replace `<PYTHON>` with the repository-local
interpreter for your platform:

```text
<PYTHON> scripts/version.py check
<PYTHON> scripts/version.py show
<PYTHON> scripts/version.py bump patch
<PYTHON> scripts/version.py set 1.0.0
```

Use `patch` for compatible fixes, `minor` for backward-compatible features, and
`major` for breaking changes. Marketplace releases reference an immutable upstream
tag and commit SHA; Codex materializes the pinned Git source declared by the marketplace.

## Use from Codex

### Public HTML

Ask Codex to translate exactly one public URL, for example:

```text
Translate this page into an offline Korean HTML bundle:
https://docs.spring.io/spring-ai/reference/concepts.html
```

The skill creates a unique work directory under `.supertranslator/runs/`, captures and
extracts the page, delegates translation zones, performs master review, assembles the
page, and runs QA. A successful output has this layout:

```text
translated-pages/<host>-<path>-<UTC timestamp>/
|-- index.html
|-- assets/ (when captured)
|-- manifest.json
`-- review-report.md
```

The completion response links to `index.html` and `review-report.md` with absolute local
paths and reports optional asset warnings.

Allocation keeps absolute lexical paths and requires the run and reserved output to be
exact children of the held `.supertranslator/runs` and `translated-pages` roots. A symlink
or reparse ancestor, dangling link, or replacement race fails closed.

### Reading editions and blog publication

The existing webpage output preserves source layout. When a readable independent
edition is requested, export an already reviewed bundle using an explicit editorial
review, without modifying the source capture or historical output:

```text
<PYTHON> -m supertranslator export-reader --input-dir <completed-bundle> --review <reader-review.json> --output-dir <new-reader-directory>
<PYTHON> -m supertranslator qa-reader --output-dir <new-reader-directory>
```

`reader-review.json` has exactly these fields:

```json
{
  "schema_version": "1.0",
  "input_html_sha256": "<SHA256 of the exact input index.html bytes>",
  "content_selector": "article",
  "title": "Document title",
  "removals": [],
  "joins": [],
  "heading_levels": {},
  "list_items": []
}
```

The selector must match exactly one document region. Inspect it against the source;
do not omit introductory matter, notices, references, figures or appendices. Each
`removals` entry has `selector`, `text_sha256` (the selected element's UTF-8 text),
and a nonempty `reason`; it moves reviewed running-page furniture into collapsed
source notes, not into the trash. Only `pre`, `table`, `header`, and `footer` can be
moved. A `joins` entry is `{"selectors": ["#paragraph-a", "#paragraph-b"]}`: it joins
adjacent prose in order after furniture/blank-spacer removal, preserving inline DOM,
IDs and text. Inspect the full English/Korean paragraph before approving a join;
unrelated paragraphs, lists and parameter definitions remain separate. Rephrasing is
not automated by this exporter. `heading_levels` maps reviewed heading selectors to
levels 1..6; `list_items` names source list paragraphs needing hanging indentation.

The output contains standalone `index.html`, reusable `article.html`, a scoped
`assets/reader.css`, captured assets, `manifest.json`, `review-report.md` and exact
input/editorial evidence. Prose is 18px desktop / 16px narrow, line-height 1.75, with
a 48rem maximum reading column. Code and diagrams keep fixed spacing and local
horizontal scrolling. Article colors inherit an embedding blog's light/dark theme.

QA checks exact HTML/article/CSS/asset bytes and real Chromium rendering at
1440/768/390px. The first QA run retains numbered, at-most-3000px-high screenshot
tiles covering the complete document (rather than unreliable giant screenshots) and leaves the edition
`pending-visual-review`. After personally comparing source and full screenshots,
write a visual review with exactly `render_input_sha256` (from the new manifest),
`verdict` (`pass`), and meaningful
`evidence`, then run:

```text
<PYTHON> -m supertranslator qa-reader --output-dir <new-reader-directory> --visual-review <visual-review.json>
```

Only this successful final run marks the derivative `passed`. It does not replace
or invent a new semantic approval for the original AI translation. When embedding
`article.html`, copy its assets and scope CSS, rewrite only the local asset base,
and disable template interpretation of literal technical text (for example Jekyll
Liquid). Publishing or removing blog posts requires the user's authorization; it is
not an automatic side effect of translation or reader export.

The rendering digest includes HTML, reusable article, CSS and captured asset hashes;
changing only a figure still requires fresh visual approval. Simple static inline SVG
geometry is preserved. Inline SVG requiring external styling or unsupported attributes
is refused rather than silently damaged; the existing source-preserving mode remains
available for those pages.

Optional `text_edits` in schema 1.0 reviews allow AI-reviewed sentence corrections
after paragraph joins. Each entry has exactly `selector`, `input_html_sha256`
(SHA256 of the selected p/li's canonical UTF-8 inner HTML), `replacement_html`,
`source_text` (the original-language counterpart) and `evidence` (the controller's
semantic comparison). English nouns, identifiers, numeric atoms, normative tokens,
and every intact inline subtree must remain. Intact reference/keyword subtrees may
move to support natural Korean order. Python does not translate, and missing source
evidence, changed links/code/tokens, stale input or overlapping edits fail closed.
Corrections are recorded separately from the historical full-document review;
changed output requires fresh visual approval. English-first terminology remains.

Optional `presentation` has exactly `toc_selectors`, `metadata_selectors`,
`title_selectors` (arrays of exact source-region selectors), and `navigation` (a
boolean). Selectors resolve after joins but before source styling is removed.
Original print TOC entries (dot-leader/page-number paragraphs or a native nav),
headings and metadata containers are explicitly reviewed: no content is deleted.
Old TOC elements move to source notes; metadata is available under “문서 정보”.
Live headings produce a compact, initially collapsed keyboard-operable TOC with
collision-free anchors. Old IDs and links remain. Standalone document titles stay
visible; only hosts supplying their own visible title should wrap the identical
article fragment in `<div class="st-reader-embed">…</div>` to suppress duplicate
document titles. Pilcrow links remain focusable with a subdued resting appearance.

### Local, attached, or public PDF

Ask Codex to translate exactly one supported PDF. Local paths containing spaces and
non-ASCII characters are passed as one native shell argument:

```text
Translate this local text-selectable PDF into Korean:
/Users/me/자료 폴더/분기 보고서.pdf
```

```text
Translate this public HTTP(S) PDF URL into Korean:
https://example.com/reports/quarterly-report.pdf
```

An attachment is supported when Codex exposes it as a readable local path. The PDF skill
creates a unique private run directory, acquires and extracts the source, uses the shared
zone translation and semantic review, assembles a staged PDF with embedded Noto Sans KR
Regular and Bold fonts, prepares automated/rendered QA, and requires master inspection of
every numbered contact sheet. Font licensing and source provenance are stored beside the
package fonts in `src/supertranslator/font_assets/OFL.txt` and `PROVENANCE.json`.

The Korean edition preserves the source trim size and distinct publication structures:
TOC hierarchy and output-page links, dedication and epigraph, part/chapter openers,
selectable callouts with independent icons, figures and captions, hanging-indent
references, and owner-linked footnote continuations. Source artwork stays intact while
translated prose remains selectable. Technical prose uses `한국어(English)` at first use
and Korean thereafter; protected products, code, identifiers, URLs, numbers, and citation
facts stay exact. Genuine reference annotations remain translatable. The webpage
workflow keeps its existing English-first policy and command selection.
Citation protection is conservative: explicit `Note:`/`Annotation:` suffixes can be
translated, while unclear citation/prose boundaries stop extraction with block evidence.
The deterministic publication fixture and independent synthetic layouts are regression
coverage, not a claim of acceptance across all real-world book or bibliography styles.

PDF input is limited to 500 pages and 50 MiB. Scanned/image-only PDFs are rejected;
there is no OCR fallback. Every run uses fresh paths without overwriting the source or
previous outputs. Partial-input TOC destinations outside the supplied PDF remain visible
with an unresolved-excerpt warning instead of a fabricated link.

Only `pdf-qa finalize` publishes a successful output:

```text
translated-pdfs/<source>-<UTC timestamp>/
|-- translated.pdf
|-- manifest.json
`-- review-report.md
```

The completion response links to all three files using absolute local paths. Staged or
partially reviewed PDFs are never presented as completed output.

PDF allocation applies the same held-root contract with `translated-pdfs`. The workflow
accepts a standalone uncaptioned figure and preserves it once, while orphan or ambiguous
captions fail. An unreconstructed visible link is only a warning when its
visible label and destination remain in both final artifacts; missing visible text fails.

After translations and glossary content are final, `pdf-review-input` creates canonical
semantic-review evidence. PDF `review.json` carries its `semantic_input_sha256`, binding
the exact segments, zones, assignments, translations, and glossary policy/content before
assembly and both QA stages.

Fresh PDF extraction uses native schema/origin 1.2: one translation target owns a
complete logical unit, including proven cross-page paragraph continuations. Physical
block text, IDs, geometry, and relationships remain unchanged. Required extraction-flow
findings stop planning; indivisible units exceeding the configured 12,000-character
budget are refused. Legacy extractions remain diagnostic-only and require a fresh run
for new assignments or publication. The immutable assignment binding and semantic
digest cover the unit map and exact reviewed bytes, so old approval cannot be reused
merely because the source PDF is unchanged. Native manifests distinguish physical
translated blocks from logical units and report paragraph-start member anchors.

Poppler/Pillow rendering is limited to 36,000,000 pixels per page, 2,000,000,000 pixels
per PDF, 64 MiB per encoded PNG, and 4 GiB for the rendered set. Each Poppler subprocess
is limited to 600 seconds. Decoded dimensions are checked before full decode. These
deterministic budgets remain enforced on platforms without an OS-level address-space
limit.

### Performance-oriented orchestration

The default skill targets three size-balanced zones, starts each translator with no
inherited chat history, and passes document input through immutable assignment files.
The master validates and reviews each completed zone while the other translators are
still running, then performs one final aggregate validation. This keeps the complete
master-review and fail-closed guarantees while reducing duplicated context and idle time.

## Direct CLI stages

The skill detects the active OS and uses the repository-local interpreter automatically.
For manual diagnosis, replace `<PYTHON>` below with `.\.venv\Scripts\python.exe` on
Windows PowerShell or `./.venv/bin/python` on macOS. Keep every URL and path as one
native shell argument. For example:

```powershell
$python = (Resolve-Path ".\.venv\Scripts\python.exe").Path
& $python -m supertranslator capture $url --run-dir $workDir
& $python -m supertranslator assemble --run-dir $workDir --output-dir $outputDir
```

```sh
python="$(cd .venv/bin && pwd -P)/python"
"$python" -m supertranslator capture "$url" --run-dir "$work_dir"
"$python" -m supertranslator assemble --run-dir "$work_dir" --output-dir "$output_dir"
```

The complete stage sequence is:

```text
<PYTHON> -m supertranslator capture <URL> --run-dir <WORK_DIR>
<PYTHON> -m supertranslator extract --run-dir <WORK_DIR>
<PYTHON> -m supertranslator plan-zones --run-dir <WORK_DIR> --max-chars 12000 --target-zones 3
<PYTHON> -m supertranslator prepare-assignments --run-dir <WORK_DIR>
<PYTHON> -m supertranslator validate-translations --run-dir <WORK_DIR> --zone-id zone-001
<PYTHON> -m supertranslator validate-translations --run-dir <WORK_DIR>
<PYTHON> -m supertranslator assemble --run-dir <WORK_DIR> --output-dir <OUTPUT_DIR>
<PYTHON> -m supertranslator qa --run-dir <WORK_DIR> --output-dir <OUTPUT_DIR>
```

For a local or public PDF, bind the complete source path or URL to one shell variable and
run the PDF stages in order:

```text
<PYTHON> -m supertranslator pdf-acquire <FILE_OR_URL> --run-dir <WORK_DIR>
<PYTHON> -m supertranslator pdf-extract --run-dir <WORK_DIR>
<PYTHON> -m supertranslator plan-zones --run-dir <WORK_DIR> --max-chars 12000 --target-zones 3
<PYTHON> -m supertranslator prepare-assignments --run-dir <WORK_DIR>
<PYTHON> -m supertranslator validate-translations --run-dir <WORK_DIR> --zone-id <ZONE_ID>
<PYTHON> -m supertranslator validate-translations --run-dir <WORK_DIR>
<PYTHON> -m supertranslator pdf-review-input --run-dir <WORK_DIR>
<PYTHON> -m supertranslator pdf-assemble --run-dir <WORK_DIR> --output-dir <OUTPUT_DIR>
<PYTHON> -m supertranslator pdf-qa prepare --run-dir <WORK_DIR> --output-dir <OUTPUT_DIR>
<MASTER> inspect every contact sheet and write strict pdf-layout-review.json
<PYTHON> -m supertranslator pdf-qa finalize --run-dir <WORK_DIR> --output-dir <OUTPUT_DIR>
```

`pdf-qa prepare` writes automated evidence and numbered contact sheets under the private
run directory. The master review records exact page/contact-sheet coverage and all thirteen
visual dimensions before `pdf-qa finalize` checks the evidence and atomically publishes
the three final artifacts.

Each command exits nonzero on a required failure. Existing output directories are never
overwritten.

## Tests and validation

Routine tests are deterministic and exclude network-marked tests by default. Replace
`<PYTHON>` with the platform-specific interpreter path described above and resolve the
installed skill/plugin validator directories for your Codex installation:

```text
<PYTHON> -m pytest -q
<PYTHON> -m pytest tests/test_skill_contract.py -q
<PYTHON> <SKILL_CREATOR_DIR>/scripts/quick_validate.py skills/supertranslator-web
<PYTHON> <SKILL_CREATOR_DIR>/scripts/quick_validate.py skills/supertranslator-pdf
<PYTHON> <PLUGIN_CREATOR_DIR>/scripts/validate_plugin.py .
```

With explicit network approval, run the two upstream compatibility checks separately:

```text
<PYTHON> -m pytest -m live -q
```

These tests are diagnostic because live source pages can change. Upstream drift must not
be treated as a deterministic regression in the default suite.

## Limitations

The HTML workflow accepts one unauthenticated public HTTP(S) static page. It does not
support private or authenticated pages, CAPTCHA flows, JavaScript-only applications,
recursive site translation, publishing, or guaranteed pixel-identical line wrapping.
Missing optional images or fonts may remain origin fallbacks and are reported as warnings;
missing critical HTML or CSS fails the run.

The PDF workflow accepts one readable local/attached PDF or public HTTP(S) PDF, up to
50 MiB and 500 pages, only when its required text is selectable. It rejects scanned,
encrypted, malformed, oversized, over-page-limit, non-PDF, private-network, authenticated,
or structurally ambiguous inputs. It does not OCR scans or preserve source line wrapping
pixel-for-pixel. Missing required text, tables, figures, captions, embedded fonts, pages,
or semantic/visual review evidence is a failure rather than a warning.
