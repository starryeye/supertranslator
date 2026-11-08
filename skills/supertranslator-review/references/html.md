# Complete HTML comparison

Read the exact final HTML and inspect its browser rendering; a source capture,
translation JSON, CSS inspection, or PDF export is not its rendered screen.
Use existing browser/screenshot tools or a local Playwright installation, with
paths passed as separate arguments. Store all generated files outside the inputs.

## Content correspondence

Map the complete source and final document in reading order using stable IDs,
selectors and short text anchors. Account for added and missing units in both
directions, including empty headings, inline link text/destinations, meaningful
attributes (title/alt/labels), lists, table cells/headers, preformatted content,
artwork labels, captions, footnotes, notices, references, and late appendices.
An apparent missing unit may have moved: locate it before deciding omission.

Read the actual final text for every mapping with enough adjacent context to judge
actor, predicate, condition, exception, scope and normative strength. Preserved
protected tokens do not prove ordinary-text fidelity. Review short qualifications
as carefully as the main claim. For every qualified unit, populate the rule record
in [report requirements](report.md) from the actual paired wording and context,
including thresholds expressed by ordinary adjectives rather than numbers.
Record inspected unit ranges and any unresolved mappings in the report.

Collapsed source notes and navigation are still content. Inspect relevant closed
and opened states without editing the files. Check that reading order, anchors,
links and disclosure labels still lead to the right material. Source notes moved
intentionally should be compared in their new location, not counted as omissions.

## Visual coverage

Inspect both original and final at viewport widths **1440, 768 and 390 CSS pixels**.
For each width record viewport height, document scroll height, and state. Capture
readable overlapping vertical tiles from top to bottom, including the final bottom
edge. A full-page image is useful as an index; zoom or tile it where text/detail
cannot be judged. Open and inspect the actual images, not just create them.

Maintain a ledger of artifact, width, state, y-range, screenshot path, and inspected
status. The intervals must cover the whole scroll height with no holes. For each
relevant opened disclosure, capture and inspect its newly visible content and
surrounding layout; record changed scroll height and additional tiles. Overflowing
tables/diagrams require inspection of offscreen horizontal content or a readable
expanded view as well as the initial viewport. Mark absent disclosures as N/A.

Compare font size, line height, margins/spacing, hierarchy, list indentation,
definitions/group boundaries, tables, code/ASCII alignment, artwork/caption
relationships, footnotes, section transitions, clipping, glyphs and reading order.
Reflow and a different intentional design are not defects by themselves. Verify
that the design still preserves relationships and makes all content readable.

## Tool gaps

Use bounded attempts: on a concrete browser failure, retain the diagnostic and
try an available supported alternative. Do not spend the review retrying the same
failed launch or bypass environment restrictions. If rendered inspection remains
unavailable, finish the possible text comparison and checkpoint visual coverage as
incomplete. CSS can substantiate a static risk; label that evidence accurately.
PDF screenshots, viewport metadata and desktop-only samples cannot stand in for
missing HTML/tablet/mobile inspection. Explicit layout-only review likewise does
not imply a semantic comparison.
