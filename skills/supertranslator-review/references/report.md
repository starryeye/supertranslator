# Review report and resumable evidence

Write a new `review-report.md` in a separate review workspace. This is a human-facing
assessment, not a machine publication-approval schema or replacement for pipeline
QA. Use these required slots; concise tables or linked ledgers can hold long coverage.

## 1. Identity, request and status

- Exact user-requested scope: full semantic+visual comparison by default, or the
  user's explicit narrower scope. List unrelated neighboring artifacts as excluded.
- Original and actual final paths/URLs, version/provenance, byte hashes where
  available, and input inventory. For a URL retain the exact reviewed response/copy
  and capture identity; an undated live URL alone cannot support same-input resume.
- Status: complete, partial, or blocked; summarize findings and the decisive gaps.
  A completed layout-only request is not a completed full semantic comparison.
- Evidence/report location and before/after input-integrity verification. State any
  unexpected mutation and stop trusting affected coverage until resolved.

## 2. Actual content coverage

Map source locations/anchors to final locations, with inspected unit ranges and
evidence of direct contextual comparison. Include front matter, inline/attribute
text, tables, captions, artwork, notes, references, appendices, and moved/hidden
content as applicable; mark absent categories N/A. List unmatched units and
unreviewed ranges explicitly. Do not replace this with a token count or “all checked.”
Record terminology policy, intentional retained English CS terms and source quirks
separately from confirmed translation defects.

For each paired unit containing a requirement, permission, condition, exception or
quantitative limit, include this **required rule record** in the coverage map or
a linked ledger:

| Field | Required comparison |
| --- | --- |
| Source rule | Location and relevant wording; actor/action, normative force, condition and exception threshold (absent components: N/A). |
| Final rule | Location and actual wording; the same components, interpreted in context. |
| Case correspondence | A concrete boundary/exception case: whether each rule permits, requires or prohibits the same action in that case, and why. For an equal verdict, explain what preserves the threshold and scope. |
| Relation and consequence | `equal`, `narrower`, `broader`, `reversed` or `uncertain`, relative to the source's permitted/applicable cases, with a concise justification and linked finding or unresolved question. |

For example, source “Operators may retain records for at most 30 days” versus final
“Operators may retain records for fewer than 30 days”: same actor/action and MAY
force, but the exact 30-day case is permitted only by the source; final permission
is `narrower`. For qualitative conditions, spell out what satisfies each threshold
and compare a case between them. This record supplies the reasoning behind the
verdict, rather than a bare “checked/consistent.” Missing counterparts remain
explicit unmatched-unit findings, not invented paired records.

## 3. Actual visual coverage

- HTML: both artifacts at 1440/768/390, viewport/document heights, tile y-ranges,
  opened/closed states, readable evidence paths and actual inspected status. Link
  coverage ledgers proving no uninspected gaps, including horizontal overflow.
- PDF: separate original/final all-page ledgers, logical mappings across unequal
  pagination, inspected overview/detail images and page-transition coverage.
- Failed tool attempts, static-only observations and remaining unviewed areas.
  Screenshot existence is not inspection; overview thumbnails are not fine-detail
  evidence. Do not mark visual coverage complete from text or CSS alone.

## 4. Located findings

For each issue give an ID, severity (critical/major/minor), category, source and final
locations, relevant source/final wording or visual difference, impact, evidence link
and actionable recommendation. Distinguish confirmed errors, uncertain mappings,
intentional differences and optional polish. A stricter qualification or changed
permission is a semantic difference even without token loss; explain the changed
meaning rather than labelling it merely unnatural. Retained English nouns alone
are not a finding. Recommendations are advice, not permission to edit the artifact.

## 5. Limitations and next checkpoint

State what was actually completed, what remains and the next exact unit/page/tile
or required input/tool. Missing exact source means no full source comparison;
interruption means partial coverage, not a pass. “No issue found” is limited to
the listed inspected scope. A complete report may contain defects: completion
describes coverage, not acceptance, correction, approval or publication readiness.

On resume, recheck the recorded hashes and inventory before reusing coverage. For
changed inputs invalidate affected semantic/visual entries and dependent mappings;
if effects cannot be bounded, redo the full affected artifact's coverage. Record the
new identity and superseded entries instead of silently merging old/new inspections.
Do not treat a previous positive report or matching hash as proof of quality.
