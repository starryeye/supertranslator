# HTML reading-edition rendering

## Resolve the bound input

Work from the original QA-passed translated bundle: `index.html`,
`manifest.json` (`qa_status: "passed"`, `required_findings: []`, public
`source_url`), `review-report.md`, and required `assets/`. Keep its bytes unchanged.
The source manifest must carry strict `web_integrity` evidence (`schema_version: "1.0"`,
`semantic_input_sha256`, `approval_sha256`, `html_sha256`); its HTML digest must match
the exact original `index.html` bytes. A legacy missing binding needs fresh AI semantic
review of the existing exact private inputs, then QA, before a new export. Preserve old
artifacts and translations; do not manufacture a binding from the old final HTML.

For an existing reading edition, read its `manifest.json`, `reader-review.json`,
`input-manifest.json`, and `input-review-report.md`. Find the original bundle
whose exact `index.html` SHA-256 equals `input_html_sha256` in the reader review
and manifest, and whose manifest bytes match `input_manifest_sha256`. The copied
input manifest/report identify prior evidence but do not contain the original
HTML. The exporter does not store a recoverable original-bundle path: inspect
the user's provided run/location and nearby historical evidence to locate it.
If unavailable or mismatched, report the missing bound bundle, not permission
to replay old selectors on the final reader or download the source again.

Preserve the existing review and create a separate review revision when changing
layout. Carry valid historical `text_edits` unchanged: their selectors/hashes are
bound to the original input after its reviewed joins. Exporting again from that
input applies each edit once. Never treat already corrected reader text as the
old edit's input or author new sentence corrections during rendering.

## Supported layout contract

The reader review has required fields `schema_version: "1.0"`,
`input_html_sha256`, `content_selector`, `title`, `removals`, `joins`,
`heading_levels`, `list_items`; optional fields are `text_edits`, `presentation`,
and `structure`. Inspect selections against the bound input before changing them.

- `content_selector` matches exactly one complete document region; retain front
  matter, notices, references, figures, and appendices. Preserve `title` wording.
- `removals` entries contain `selector`, `text_sha256` of exact selected UTF-8
  text, and a nonempty `reason`. Only reviewed `pre`, `table`, `header`, `footer`
  furniture moves to collapsed source notes; content is not deleted.
- `joins` entries contain `selectors`, an ordered array of adjacent prose
  selectors after furniture/blank-spacer handling. Preserve inline DOM and IDs;
  unrelated prose, definitions, and lists remain separate.
- `heading_levels` maps exact heading selectors to integers 1..6.
  `list_items` is an array of reviewed list-paragraph selectors.
- `presentation` has exactly `toc_selectors`, `metadata_selectors`,
  `title_selectors` (selector arrays), and `navigation` (boolean). Original
  print TOC and document metadata can be folded without deleting body content.
  Navigation generates a collapsed TOC from live headings. Standalone titles
  remain visible; an embedding host with its own identical title may use
  `.st-reader-embed` around the unchanged article fragment.
- `structure` has exactly `definitions` and `lists` arrays. A definition has
  `selector`, integer `term_end` (Unicode text offset after joins/text edits),
  and `evidence`; the split cannot cut an inline subtree. A list has `items`
  (`selector`, integer `depth`) and `evidence`. Items are live flat-inline
  sibling `p`/`div` elements in source order, start at depth 0, and increase at
  most one level per item. Separate groups remain separate; do not overlap
  structure, presentation, archived notes, old `list_items`, or native/ARIA owners.

The installed renderer fixes typography (18px desktop / 16px narrow prose,
line-height 1.75, 48rem column), scoped CSS, and local literal scrolling. There
are no CLI font/spacing/color knobs. An arbitrary typography request needs a
separate renderer change; do not edit output CSS and rewrite its digest.
Malformed/unsupported selections and stale hashes must retain their diagnostic.

## Export a new revision

Choose an unused, non-overlapping output directory. Stop after any failed stage.
Use the native interpreter invocation from the main skill; each path is one
argument. This command sequence deliberately starts at export, not translation:

```text
<python> -m supertranslator export-reader --input-dir <bound-bundle> --review <reader-review> --output-dir <new-output>
<python> -m supertranslator qa-reader --output-dir <new-output>
```

`export-reader` preserves IDs, links, figures, literal code/diagrams and assets,
and writes `pending-visual-review`. It produces `index.html`, `article.html`,
`assets/reader.css`, captured assets, manifest/report, and exact review/input
metadata copies. It neither mutates the original bundle nor performs translation.

## Fresh visual QA and delivery

After the first successful `qa-reader`, read the new `browser-qa.json` and
inspect every current `screenshot_tiles` image in `reader-screenshots/` using
image-viewing tools. Cover the whole document at 1440, 768, and 390px; compare
with the bound content/layout instructions. Inspect opened TOC, metadata, and
source-note states when those features are used. Check hierarchy, readable
Korean, grouping, tables, figures/captions, links, literals, clipping and overflow.
File hashes or screenshots merely existing do not establish visual approval.

Write a new visual-review file, separate from the old output, with exactly:
`render_input_sha256` (copy the current new manifest value), `verdict: "pass"`,
and nonempty `evidence` describing the actual complete inspection. Even identical
rerenders need fresh inspection; do not supply an old visual-review file.

```text
<python> -m supertranslator qa-reader --output-dir <new-output> --visual-review <new-visual-review>
```

Only successful final QA and `qa_status: "passed"` complete the edition. Return
absolute links to the new `index.html`, `article.html`, `manifest.json`, and
`review-report.md`, with asset/QA warnings. If browser launch or inspection is
blocked, keep the new edition pending and state the precise incomplete gate;
do not write a passing visual record. Publication is not part of rendering.
