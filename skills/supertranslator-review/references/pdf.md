# Complete PDF comparison

Use the supplied original and actual final PDF directly. Do not reacquire a supplied
PDF or require the plugin's internal extraction/approval schema. Existing read-only
inspection tools such as `pdfinfo`, `pdftotext`, `pdfplumber`, and Poppler rendering
can identify text and render pages into the separate review workspace. Inspect
available tool help before choosing flags; keep each path a separate argument.
Do not call acquisition, assembly, or QA finalization to perform this review.

## Logical content across physical pages

Record both page counts. Extract selectable text with page boundaries and layout
coordinates where useful, but read against the actual pages to catch extraction
loss, order problems, artwork text and glyph substitutions. If extraction is
inadequate, report the affected content and capability gap; do not invent text.

Map logical units using section/title anchors, text spans and page/bounding-box
locations on both sides. Join paragraphs, tables, lists and notes that continue
across pages for semantic judgment. One source unit can map to several output
pages, and vice versa. Different page counts or page numbers alone are not errors;
follow the logical content and inspect any added, blank or missing pages in context.

The reviewer must directly read each actual paired unit, including nearby clauses,
through front matter, body, tables, figure labels/captions, notes, references and
the final appendix. Compare qualifications, exception thresholds, negation,
normative force, actors, quantities and cross-references, not only protected words.
For every qualified unit, fill the rule record in [report requirements](report.md),
using the complete logical clause across page breaks and both located wordings.
Record missing/added units and unresolved mappings explicitly. Never infer semantic
success from an old review, text length, or an extraction/validation pass.

## Every-page visual coverage

Render and open **every original and every final page**. Contact sheets are an index
for coverage and overall rhythm, not sole evidence when detail is unreadable.
Open page images or crops at sufficiently high detail to judge the actual text,
glyphs, diagrams, table cells, captions and footnotes. Record which detailed images
were inspected for each page. Inspect all continuation/page-transition boundaries,
including logical units flowing to different output pages.

Judge typography, spacing, heading hierarchy, group/list indentation, table and
artwork alignment, caption ownership, footnote placement, clipping/overlap,
broken glyphs, reading order and disruptive page breaks/empty space. Source quirks
are distinct from newly introduced defects; re-typesetting need not reproduce the
source's physical pagination or whitespace exactly. Report page/bounding-box
locations on both sides and evidence at readable resolution for each issue.

Maintain source-page and output-page ledgers separately, with semantic-unit links,
overview/detail paths, inspected state and remaining questions. A failed image
tool leaves those pages visually unreviewed even if rendering succeeded. Preserve
diagnostics, checkpoint the precise gaps, and do not claim all-page inspection or
complete review until those gaps are resolved.
