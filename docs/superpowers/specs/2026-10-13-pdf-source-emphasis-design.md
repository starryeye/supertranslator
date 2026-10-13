# PDF source-faithful ordinary-text emphasis

## Intent and human decisions

This is a narrow amendment to the existing release-readiness effort, not a new translator or restart of completed tasks. The user approved general heading/body design and correction after actual all-page inspection found regular11pt explanatory prose rendered as bold16pt. They then clarified that forcing an uncertain line into a definite heading/body appearance is unnecessary: a visually ambiguous source should remain similarly ambiguous in the translation. The user confirmed preserving the source's emphasis while reflowing Korean line lengths/pages.

The user decided the outcome, not the mechanism below. The controller recommends making ordinary text's visible size/weight depend on existing source typography, not inferred heading rank. Python, existing ReportLab/Noto fonts, public CLI/models, semantic/figure hashes and held-handle publication remain unchanged. No machine-translation service, fresh automatic semantic/visual approval or new dependency is introduced.

Scope approval is not approval of this concrete document or its subsequent implementation plan. No production/test code is changed until both are reviewed by the human.

## Observed problem and revised target

At source SHA `1d8d04d0efc27ba510956a0d981609f6f5e592fe`, the ordinary figure explanation is regular11pt against predominantly10pt body. Existing `classify_document_lines` assigns it heading level2 because its font is at least1pt above the body mode. Assembly then maps inferred level2 to16pt bold, while the actual title remains18pt bold. Raw source, extracted blocks, actual layout, independently opened original/output pages and the controlled read-only probe are retained under `.web-translator/release-readiness-20261012`.

The revised target is to remove unsupported **visible amplification**, not claim perfect semantic heading recognition. Structural kinds remain provisional internal data used for unit grouping, heading context, anchors and notes. An ambiguous heading candidate must not become visually definite merely because of that kind. The existing classifier is not silently declared fixed or bypassed: its ambiguity remains, but rendering no longer converts that ambiguity into a invented size/weight hierarchy.

The known example should retain an approximately10% size difference and regular weight, rather than a roughly45% enlargement and newly bold face. Actual true titles remain larger/bold where the source supplies that evidence.

## Chosen narrow mechanism — controller recommendation

### One document typography context from existing data

Compute an in-memory ordinary-body reference using existing physical `PdfBlock` styles, not translated text, source filenames, font family names or inferred heading ranks:

1. Prefer nonempty, nonbold `paragraph` blocks with `semantic_role == body`.
2. If none exist, use nonempty body-role paragraphs regardless of weight.
3. If there are no such paragraphs, use nonempty body-role list items.
4. If no ordinary-body evidence exists, use the existing normalized body size11pt as the reference; this makes heading-only documents retain their existing source point-size differences without guessing a new body style.

Use non-whitespace source-character counts to select the modal source size; round source sizes to3decimal places to discard extraction jitter, breaking equal votes in favor of the smaller size. Very small positive sizes must not become a zero divisor when rounded: retain their valid positive value for the vote, or reject nonfinite derived sizing through the existing assembly error contract. Do not invent a size cluster from captions, tables, page furniture, footnotes, references, chapter openers or other specialized roles. Do not double-count physical blocks through logical unit membership.

This private context is calculated once per assembly and threaded to ordinary-text style selection in both existing composition paths. It is not persisted, added to schemas or rebuilt from generated review/output values. Helper names and a small private value type, if useful, are builder choices; no module-wide reorganization.

### Source-relative size and observed weight

For ordinary body-role headings, paragraphs and list items:

`output size = max(existing minimum9pt, normalized body11pt × source size / source body reference)`

Use stabilized source sizing for jitter-insensitive equality. Above the existing minimum, preserve the source size ratios and ordering; at the floor, document the unavoidable readability normalization rather than claim pixel-identical typography. Derived sizes must be finite and positive; unrenderable text must fail closed through existing layout/resource budgets, never clip, silently shrink below9pt or publish a partial output. Do not add guessed maximum-font/source-hash allowlists.

Choose the existing embedded Regular or Bold face from `PdfBlock.style.bold`; do not force Bold merely because `kind == heading`, or force a bold source paragraph back to Regular. Preserve the existing proven inline-emphasis markup and label/link escaping; this change is not a new alignment of translated words to source font spans. The document's available block-level weight evidence is the fidelity boundary, not recovery of unavailable original typography.

Keep the existing structural anchors, list markers/nesting, note ownership, heading context and source IDs. Heading `keepWithNext`/structural placement remains in force; the style's visible size/weight no longer comes from the rank table18/16/14/... . Use leading that scales from the effective font size while retaining current safe paragraph/heading leading ratios; it must fit the actual glyph size rather than retain a fixed leading that can overlap newly enlarged text.

The original example has body reference10pt, normalized body11pt, source explanation11pt: expected ordinary explanation12.1pt Regular, actual title18pt becomes19.8pt Bold, and ordinary10pt prose11pt Regular. These are independent expected ratios from raw source evidence, not a fixture-specific branch. Uniformly scaled sources must produce the same relative output emphasis. In heading-only documents with source18/14/14/18 and no body reference, expected output sizes are18/14/14/18, not the old18/16/16/18 rank substitution.

### Specialized composition remains out of scope

Caption, table, footnote, page furniture, TOC entries, references, openers, epigraphs and callouts keep their existing specialized composition/appearance rules in this task. Their content/ownership and all current safety checks remain intact. This is not a promise to reproduce every source font, color, alignment, whitespace or exact page count. Existing Korean body alignment and reflow are retained. Table width/post-table spacing and retained source-page labels are separate observations, not bundled fixes.

An ordinary-heading/paragraph boundary may remain ambiguous internally. This document does not authorize adding a new classifier, changing translation unit membership, creating TOC entries, claiming a semantic-confidence score or reclassifying source data simply to make rendering look right. If implementation shows that faithfully rendering the available evidence requires changing a public schema, specialized composition, ownership or expected corpus bytes, stop and seek separate authority.

## File surface and immutable evidence

Expected production surface: `src/web_translator/pdf_assemble.py` ordinary style/context and its existing callers only. Test surface: `tests/test_pdf_assemble.py`, and focused real output checks in `tests/test_pdf_pipeline.py` if needed. Existing fixture producers may be used, not rewritten to disguise the output change. No `pdf_layout.py` classification rewrite, extraction/model/digest/media/QA strategy change or workflow edit is needed; native CI already selects the pipeline module.

All33committed fixture files and prior real-book/input/output hashes stay byte-identical. Existing stored translations remain regression inputs, not a new AI translation. Only affected tests whose assertions encode the intentionally replaced rank-based **rendering** contract may be updated, with independent source-style expectations and a truthful test name; do not loosen source/figure/review hash checks or change fixture goldens. The semantic classification/context contracts remain unchanged.

No source main merge, force push, tag overwrite, PyPI publish, reinstall, rename or private-evidence cleanup. Every commit is immediately pushed; independent review precedes product commits. Keep the running release-readiness ledger and earlier evidence; do not replay completed Tasks1/2/3/7/8/9/10 as fresh work.

## Required acceptance

- TDD first proves unsupported heading-kind amplification on a real rendered PDF, including Regular/Bold font evidence and actual glyph point sizes, not only a mocked style helper. The known general ambiguous source and at least one differently worded/font-named/uniformly scaled source must expose the old behavior; no exact sentence/book/font exception is permitted.
- Positive cases cover genuine bold headings, small regular heading candidates, bold ordinary paragraphs, equal source sizes, heading-only fallback, body/list fallback, extraction jitter and the9pt floor. Separate structural invariants verify unchanged source IDs/order, unit membership, list markers, anchors and footnote owners. Genuine TOC/context semantics are not replaced by font rank assertions.
- Mixed inline-emphasis/link rendering still executes its existing evidence-bound path; neither all-Regular nor all-Bold output may hide the point-size/weight assertions. Both composition callers must supply the same source context, with direct focused coverage where only one path is exposed by public assembly.
- Existing font embedding/ToUnicode, layout bounds/splitting, tables/captions/notes, no-clobber and exact semantic/figure review tests continue to pass. Changes must be verified by risk-proportionate focused tests plus affected assembly/pipeline collateral, retaining original true exits and exact environment-only reruns. No full project/marker/baseline replay during this scoped implementation.
- A new private run of the independent acceptance sources produces the final translated PDFs after the reviewed correction. Controller reopens actual original/output pages and confirms that unsupported amplification is gone, while all other13dimension observations/limits remain recorded. Previous failed visual outputs and reports are preserved, not rewritten or retroactively approved. Specialized-role limits remain explicit; synthetic approval records are not actual visual certification.
- Exact pushed-SHA Windows/macOS pipeline and retained QA guards must pass. Only then resume Task4's one frozen full non-live gate, whole-branch review and previously approved version/package/native/tag/release/catalog sequence. If source changes invalidate an earlier gate, rerun only its affected evidence; do not retranslate user books or replay identical completed gates solely to aggregate IDs.

## Calls left to the builder

Private helper/context names, exact focused test organization, safe leading formula retaining current ordinary-text leading ratios, and minimal plumbing within existing callers are implementation details. The source-relative formula, body-evidence fallback order, no structural reclassification, immutable goldens, specialized exclusions and review/publication gates are binding design choices proposed for human review.

This remains bounded source-emphasis correction. Neither a classification-accuracy claim nor universal commercial-quality/500-page translation certification follows from it.
