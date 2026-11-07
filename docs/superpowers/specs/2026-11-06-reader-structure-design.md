# Source-reviewed reader structure — small-change design

Approved by the user on 2026-11-06, following the PKCE full-source comparison.
This records the approved design from
`/private/tmp/supertranslator-pkce-direct-review-jwOO42QL/fix-design.md`.

## Intent and constraints

Preserve reviewed definition boundaries, nested list relationships and record
grouping in reading editions without changing source meaning. English CS terms,
18px/16px prose, 1.75 line height, and exact literal/link/ID/hash protection stay.
Old review files and accepted outputs remain usable and unchanged. Python never
translates; no RFC-, phrase-, or site-specific production branches are permitted.

## Causes and approach

The current `list_items` selector array expresses no depth or group boundaries.
Some original list children were classified as prose, so preserving projection
depth alone would not repair them. Definition names and descriptions share a
paragraph whose whitespace is collapsed by normal prose layout.

Add optional explicit structural review to the existing reader review. AI reviews
the source and specifies definition boundaries and ordered lists with depths;
separate list records retain separate visual groups. Code validates and applies
only those decisions, bound to the exact input HTML. Retain the old flat-list path
when the optional review is absent. Reject invalid boundaries, overlapping
selections, non-contiguous members and impossible depth transitions.

Alternatives considered: global newline preservation would break reflowing prose;
number/word heuristics would introduce another classification engine. Neither is
appropriate to this bounded repair. Existing HTML definition/native list structure
needs no new inference.

## Deliverables and non-goals

Implement regressions before product changes. Preserve existing inline subtrees,
text, numbering, order, links, literals and IDs. Add a qualification-review example
for persuasive versus unavoidable grounds; the existing rubric already prohibits
strengthening exceptions, so do not claim another sentence guarantees quality.

Generate PKCE into a fresh directory, with the AI-authored exception correction,
and inspect its full content and PC/mobile rendering against the source. Do not
rewrite accepted bundles, weaken QA, modify PDF processing, translate other RFCs,
publish sites, or introduce a translation service. Commit and immediately push
each implementation commit; distinguish candidate runtime from a released plugin.

Success means visible name/description boundaries, nested 4a/4b below 4, distinct
registration groups, faithful exception meaning, unchanged protected content,
passing old/new tests and fresh exact-byte-bound visual approval.
