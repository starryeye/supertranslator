# PDF rerendering from exact approved inputs

## Reuse boundary

Locate the private reviewed native 1.2 run, not only its final `translated.pdf`.
Required evidence includes `source.pdf`, `source.json`, `document.json`,
`segments.jsonl`, `zones/`, immutable `assignments/` including
`.pdf-unit-binding.json`, `translations/`, `glossary.json`, and `review.json`.
Figure-bearing runs also need the exact figure inventory, media and AI figure
decisions. `prepare-pdf-render` validates the exact semantic input digest,
resolved six-dimension semantic approval, native logical-unit binding, source,
and current figure evidence; it does not issue new approval. A source-PDF hash
alone cannot establish reuse validity. Missing/stale/unresolved/legacy evidence
is a diagnostic: stop without reacquisition, extraction or translation.

Current `pdf-assemble` regenerates the complete PDF with the installed renderer
and bundled Noto Sans KR fonts. Pagination can change throughout the document.
It has no font-size, margin, page-size, theme or settings-file option. A request
for unsupported typesetting controls is a limitation, not permission to change
the runtime, source ownership, translations, glossary or approved evidence.

## Allocate, prepare, assemble

From the intended workspace use `supertranslator.paths.lexical_workspace()`
and `create_pdf_run_paths(workspace, source_label, datetime.now(UTC))`.
For example, invoke this fixed program through the resolved native interpreter
and pass the approved run's absolute path as its one argument:

```text
<python> -c 'import json,sys; from datetime import UTC,datetime; from supertranslator.paths import lexical_workspace,create_pdf_run_paths; p=create_pdf_run_paths(lexical_workspace(),sys.argv[1],datetime.now(UTC)); print(json.dumps({"work_dir":str(p.work_dir),"output_dir":str(p.output_dir)},ensure_ascii=False))' <approved-run>
```

Parse stdout as one JSON object with exactly `work_dir` and `output_dir`, each
an absolute string (PowerShell `ConvertFrom-Json`; POSIX a JSON parser, not word
splitting). Retain the allocator's lexical paths: empty `work_dir` is an exact
child of `.supertranslator/runs`, reserved `output_dir` is an unused exact child
of `translated-pdfs`, and both share the same run ID. Do not create the output,
resolve links, use `..`, guess paths after a parser failure, or evaluate stdout
as code. Symlink/reparse paths and overlapping/nonempty destinations are refused.
Keep source run, new run, and new output separate; preserve the old output too.

Run with the main skill's native interpreter/path argument contract, stopping
on nonzero exit:

```text
<python> -m supertranslator prepare-pdf-render --input-run-dir <approved-run> --run-dir <new-run> --output-dir <new-output>
<python> -m supertranslator pdf-assemble --run-dir <new-run> --output-dir <new-output>
<python> -m supertranslator pdf-qa prepare --run-dir <new-run> --output-dir <new-output>
```

Preparation copies exact approved input bytes into the new run. It excludes old
staging, layout, QA, rendered pages and visual approval. Assembly creates only
private `staged-output/translated.pdf`; QA preparation writes `pdf-qa.json` and
bounded numbered page renders/contact sheets under `qa-pages/`. Neither publishes
the reserved output. No new translation or independent full comparison is run.

## Required fresh all-page visual evidence

Read the new `pdf-qa.json`. Inspect EVERY current numbered contact sheet with an
image-viewing tool, confirm collective coverage of every output page exactly
once, and inspect full-page/detail views wherever sheets cannot establish the
quality. Follow reflow across page transitions; do not assume source and output
page numbers coincide. Automated metrics and prior passing output are not
visual inspection. Browser/image-tool failure means incomplete QA, not approval.

Write a NEW `<new-run>/pdf-layout-review.json` with exactly these six fields:

| Field | Required value |
| --- | --- |
| `schema_version` | `"1.0"` |
| `staged_pdf_sha256` | Current `pdf-qa.json` staged PDF digest |
| `pages_reviewed` | Sorted unique integer array covering all current output pages |
| `contact_sheets_reviewed` | Exact current `contact_sheet_pages` mapping, after inspecting each sheet |
| `findings` | All thirteen dimensions below, each exactly `verdict` and nonempty `evidence` |
| `unresolved_required` | Sorted unique dimension names marked `required-fix`; empty only if all pass |

Canonical findings: `heading_hierarchy`, `text_legibility`, `table_legibility`,
`figure_caption_pairing`, `footnote_placement`, `page_transitions`,
`clipping_overlap`, `glyph_rendering`, `semantic_structure`, `toc_navigation`,
`reference_formatting`, `text_image_separation`, `terminology_readability`.
Each verdict is `pass` or `required-fix`. Evidence must describe your actual
inspection; do not copy sample or old approval text. The last five publication
dimensions need page-specific evidence about opener/callout grouping, printed
TOC pages and link destinations, separate hanging-indent references, selectable
translated prose outside source artwork, and natural Korean terminology with
protected content retained. Explicitly describe absent features when applicable.

Do not copy old `pdf-layout-review.json`, even if the staged digest is identical.
If any finding needs a fix, do not finalize. Report unsupported fixes or requests
requiring changed translation/ownership; preserve approved inputs. For a supported
render-only revision, repeat preparation into a fresh run and all affected QA and
new all-page inspection. Never edit QA bindings to make old evidence appear current.

## Finalize and deliver

Only after all fresh checks and visual findings pass:

```text
<python> -m supertranslator pdf-qa finalize --run-dir <new-run> --output-dir <new-output>
```

Return absolute links to the three published files: `translated.pdf`,
`manifest.json`, `review-report.md`. State reused input identity, requested
change, all-page QA coverage and warnings. Until finalize succeeds, keep staged
output private and describe the exact blocker; do not present a staged-PDF link
as completion. Old runs, published files and review records remain unchanged.
