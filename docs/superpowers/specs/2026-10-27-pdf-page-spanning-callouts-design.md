# Page-spanning selectable-text PDF callouts

Status: the user approved the recommended approach on 2026-10-27: prove adjacent source callout fragments belong together, preserve titles/lists, translate a continued logical paragraph as one AI target, and reflow Korean output. This detailed design awaits approval. No product implementation is authorized yet.

## Intent and current evidence

Support ordinary explanatory text boxes that continue across source pages. Their text must remain selectable and AI-translated, not become a preserved illustration. This serves diverse book PDFs, not a title/page/font-specific exception. Source artwork remains original pixels; independent tables, captions, code, references and surrounding body retain their existing ownership and protection.

The verified candidate baseline is `98f6d107a1db886de43b49779bc2a603c181cd44`. It passed independent code review and exact-SHA native macOS/Windows PDF jobs. A fresh whole-source run then stopped at PDF page 76 of the user's unchanged 491-page source. Source-page views 76–77 show a text callout opening near one page's end and closing on the next. Its first fragment lacks a bottom border; the continuation lacks a top border. The existing decorator recognizes complete rectangles, not this document-level relationship. Their connected border geometry becomes a graphic candidate and the prose guard correctly refuses it. The diagnostic run and all original bytes remain preserved privately; private book text/images are not fixtures or repository material.

Fixing decoration alone is insufficient. `classify_graphic_text_lines` currently sets callout lines to paragraph kinds, the hanging-list and owned-flow collectors are body-only, `pdf_units` permits multi-member units only for ordinary body, and `_consume_role_group` stops at a source page boundary. All these consumers must agree on the new proven structure. Do not misrepresent extraction success as end-to-end support.

## Approaches and selected direction

1. Loosen the prose-bearing figure guard or preserve the box as an image: rejected. It loses selectable translated prose and confuses text decoration with illustration ownership.
2. Recognize each open box independently and translate its physical page fragments separately: smaller, but incomplete. It can accept unrelated broken borders, split sentences/list items into separate targets, and leave separate output boxes at arbitrary source page boundaries.
3. Prove a source callout chain before table/figure ownership; carry its identity through logical paragraph/list joining and output grouping: recommended and selected by the user's subsequent “네”. This costs coordinated extraction, contract and renderer work, but preserves the requested structure and the AI's complete logical context.

The retained Python/pdfplumber, logical-unit, ReportLab and shared translator contracts remain the foundation. The exact pure-helper organization is a builder choice, not a new service or translation backend.

## Goals and explicit bounds

- Recognize one uniquely matched text-only callout spanning two or more consecutive source pages, including a chain with intermediate fragments open at both page edges.
- Preserve one title, separate complete paragraphs and list items. Join only a paragraph or list item actually continued over a source page boundary; never translate the whole box as one undifferentiated target.
- Preserve source block IDs, page/position/text evidence and reversible source membership. Korean output may span a different number of pages while retaining one logical callout and exact target coverage.
- Initially support actual axis-aligned straight source borders, including equivalent line/path encodings, with page-relative geometry and observed typography rather than a book template. This bounded initial shape scope is the builder's recommendation. Rounded/nested/irregular containers and artwork embedded in a newly detected open-border chain are not newly enabled by this design; uncertain candidates still fail closed. Existing supported single-page callout/icon cases must not regress.
- No page/title/phrase/font allowlists, OCR, machine translation, source edits, synthetic closing borders as source evidence, automatic semantic passes, weakened figure exceptions, lowered limits or old approval reuse. Limits stay 500 input pages and 50 MiB.

## Recognition and text ownership

Establish document-level evidence before any fragment can be claimed by table or figure detection. Inspect neighboring source pages within the existing held-source workflow; reuse extracted words/lines/primitives instead of repeatedly parsing or rendering the book. The builder decides the minimum prepass/cache organization.

Recognition needs actual border segments, not the union bounding box of arbitrary strokes. A chain has a real starting cap and side borders, compatible side borders on any intermediate pages, and a real ending cap. Open ends must correspond to adjacent page content edges, not an arbitrary hole in a mid-page rectangle. Width, side alignment, indentation, typography and content-edge placement must agree in page-relative/observed-text terms, allowing mirrored margins and harmless source scaling. The builder must pin numeric tolerances and the edge-evidence derivation in the implementation plan and synthetic tests; no private source measurements become constants.

Relations are globally unique across competing page candidates: do not choose nearest/first. Missing caps, nonconsecutive pages, interrupted/incompatible geometry, multiple plausible successors/predecessors, a new independent box/title, or incompatible text ownership cannot authorize a chain. An unproven chain stays unclaimed and is refused as before or yields a required finding before assignments; it must never silently become independent translated fragments.

Require selectable text and no independently owned grid/artwork inside a newly admitted text-only chain. Whole glyph ownership, peer overlap, table/figure exclusion and source character accounting remain mandatory. External prose, headers/footers, page numbers, links, notes and independent tables/illustrations must not be swallowed into the box. Filtering of proven decoration before table detection and exclusion from figure candidates must consume the same accepted evidence; duplicating recognizers in those consumers is forbidden.

## Logical content and provenance

Carry stable, explicit callout-group membership and ordered source fragment evidence through extraction. Do not infer later grouping merely from adjacent `callout-body` roles. Keep physical evidence unchanged; container membership and logical translation units are separate concepts. Do not repurpose `continuation_of`, whose current contract is reference-entry ownership.

Reuse the existing positive logical-flow checks where they apply, scoped to members of the same proven callout. Extend owned-line collection, list-marker/hanging-indent handling, boundary construction, unit membership validation and source projection coherently. Titles and unrelated list items/paragraphs remain separate units. A continued list item retains its original marker exactly once and includes its hanging continuation. Punctuation, lowercase text, a repeated title or style similarity alone proves neither continuation nor separation. Ambiguous ownership/flow remains a required blocker.

All readers/validators, assignment preparation, rendering ownership, semantic digest and QA consumers must agree on the new evidence. No unbound sidecar or validator-only role bypass is allowed. The existing 1.2 contract currently excludes multi-member callout units; do not assert format compatibility merely because JSON field names fit. The builder must perform a contract-impact check in the plan and select the minimum explicit versioned extension if needed. Exact version/field names and internal data types are builder decisions to make concrete in that reviewed plan. Old documents remain diagnostic-readable; new publication cannot borrow old unit maps, bindings or approvals. Any new canonical group evidence must be included in current semantic input binding and independently validated against bound source/document membership.

## Korean output

Group new source fragments by their proven callout identity, not source page equality or a shared role alone. Preserve title/body/list hierarchy, indentation and original emphasis. Reuse the existing readable Korean fonts/minimum-size policy. Do not invent/repeat a title or add translated prose just to indicate a split.

Compose the callout as reflowable content. A long box may split naturally over output pages; it must not force an oversized keep-together block, clipping, overlap, tiny text or blank-page loops. Emit each logical translation once while retaining anchors/provenance for all physical members. Keep two adjacent but independent callouts distinct; ordinary body following the closing fragment must remain outside.

Only the three existing public filenames are delivered: `translated.pdf`, `manifest.json`, `review-report.md`. If minimum versioned provenance additions are needed in their contracts, enumerate them and their backward-read/publication behavior in the plan; do not silently reinterpret historical artifacts or create a fourth public approval file. Existing thirteen visual dimensions and source/media/review hash checks remain mandatory.

## Verification and rollout

Use independent selectable synthetic PDFs, not private book fragments or regenerated golden files. Cover two-page and three-or-more-page chains; line/path border encodings; varied fonts, scales/origins and mirrored margins; titled/body-only boxes; complete separate paragraphs; split paragraphs/words/list items; and Korean output longer than a page. Assert exact disjoint character/target ownership, source membership, single marker/title emission, no swallowed body/table/figure/footer, and selectable correctly grouped output.

Negative coverage must retain meaningful content/artwork while varying one defect: missing/false caps, mid-page broken frames, intervening pages/content, shifted/mismatched/competing boxes, orphan source endpoints, real interior art/grids, crossing glyphs and foreign/duplicate/reordered group members. Test independent group/flow binding rejection, stale approvals and assembly/QA/finalization failure preservation. Keep existing closed-callout, body joins, references, figures, table and filesystem/race regressions intact. Exact helper signatures/field names and test ownership belong in the plan rather than a speculative code recipe here.

After focused RED/GREEN, independent task/final review, one full non-live regression gate on the frozen feature candidate and actual exact-SHA macOS/Windows gates, allocate a fresh empty run and reacquire/re-extract the entire unchanged original. Keep acquisition logs/provenance outside the allocated run until acquisition succeeds. Preserve all earlier failed runs. New unsupported ownership/flow remains a reported blocker, not permission for another implicit feature expansion.

If extraction passes, resume the existing direct-AI `korean-first` workflow: immutable assignments, indivisible logical units under the 12,000-character budget, controller semantic/figure review, every output page's visual review and successful finalization before completion. No private content is committed/pushed. Every actual docs/code commit is pushed immediately. No automatic main merge, public release/version tag, catalog or installed-cache change is part of this work.

## Approval boundary

This is a connected extension across existing components, not a one-line extraction workaround. The user chose the approach; the detailed document still needs approval, followed by the separate implementation plan. Builder check may settle minor internal organization choices; it cannot change these product/safety boundaries. Implementation and book re-execution do not begin merely because this document exists.
