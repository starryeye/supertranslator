# Preserve proven diagram ownership before callout discovery

Status: the user selected the recommended minimal correction and approved this short design through subsequent “네” replies on 2026-10-30. Implementation planning is authorized; no implementation has started.

## Intent and evidence

Restore ordinary diagram handling without losing selectable, directly AI-translated page-spanning callout prose. A whole-source run on `77c753036d4bd6fd6ccb6258c5dfa26288d05fbf` stopped because the new callout prepass paired separate vertical strokes inside a diagram. Bounded diagnosis showed the existing graphic partitioner already accepts the complete diagram; callout discovery runs first and rejects the artificial inner frame before that ownership can be established. Native macOS/Windows tests passed on that baseline, but did not cover this combination.

This is a bounded source-ownership regression correction, not a new translation backend or permission to swallow prose into images. Private source content and measurements must not become repository fixtures or recognition constants.

## Approaches

1. **Reuse existing positive figure evidence before enumerating inner callout candidates — selected.** Keep the current diagram rules and share their result with callout discovery. This adds a narrow exclusion and preserves the existing architecture; shared computation must avoid duplicated or weaker recognizers.
2. **Redesign figure/callout ownership as one integrated classifier — not selected.** It could centralize more decisions but changes extraction and publication contracts more broadly than this regression needs.

## Proposed behavior and builder choices

- Reuse the existing source candidate construction and positive composite-figure witness: actual closed frame, independently drawn interior artwork, uniquely matched explicit caption and the current separation/geometry checks. Factor shared pure computation only as needed; do not copy a relaxed version into the callout module.
- Before assembling a callout candidate from two strokes, exclude it only when its complete proposed border and owned glyphs are inside one positively proven figure. Partial glyph containment, boundary-crossing or competing ownership must not gain an exclusion. A rectangle, caption, image proximity, small size, familiar label or a failed callout test alone is not proof.
- Do not implement a blanket “ignore invalid callouts” fallback or call the full partitioner and suppress its errors. Unproven diagrams and real broken/ambiguous callout chains retain their existing required refusals. Source tables, prose-only boxes and real callout fragments cannot manufacture figure evidence.
- Compute the same evidence from the current cached raw lines, characters and primitives in both extraction and independent held-source revalidation. No caller-supplied approval flag, serialized figure exemption, persistent cache, additional whole-source parse/render or new sidecar is introduced.
- After this narrow exclusion, leave chain caps, physical page edges, normalized sides, pitch/indentation, global uniqueness and logical-unit validation unchanged. Ordinary media partitioning, exact glyph ownership, figure inventory/AI label review, source/media/review hashes and publication rollback still decide their own existing gates.

The shared pure-helper organization and focused test names are builder decisions to pin in the implementation plan. Retain current conditional document/layout/manifest versions and old artifact bytes; no schema, dependency, filesystem-strategy or rendering-policy changes are needed.

## Bounds and verification

- Use independently drawn selectable synthetic diagrams with unrelated equal-height vertical strokes and internal labels. Vary geometry, line/path encodings, fonts, scale and page origins; never reproduce a private page as a fixture. Assert one original figure, exact disjoint glyph/target ownership and separately translated caption/body.
- Keep closed-frame, interior-artwork and caption negatives meaningful: missing/false frame, no artwork, ambiguous/missing caption, crossing glyphs and partial containment must not become successful figure exemptions. Preserve real two/three-page callouts, one-line edges, hanging lists, old closed boxes, mixed figure/callout pages and independent source/publication rebind refusals.
- Prove the regression with RED before production edits, then renew affected detection/media/extraction/publication tests and independent review of this correction. Keep earlier full-suite evidence attributed to its original frozen bytes; it is not a full-suite claim for amended code. Require actual macOS and Windows PDF CI on the final pushed correction SHA.
- Only then allocate a fresh empty private run and reacquire/re-extract the entire unchanged user PDF once. Preserve earlier runs; no slicing, source edits, approval reuse, machine translation or book-specific exceptions. A new required blocker is reported rather than silently broadening this correction.

## Workflow and non-goals

Keep the existing branch/worktree and subagent-driven implementation choice. This separately approved regression scope does not reopen completed tasks or create a second fix wave in the previous final review. Every actual docs/code commit is pushed immediately. No automatic main merge, version/release tag, catalog update, installed-cache change or private-content commit is authorized.

The output contract remains exactly `translated.pdf`, `manifest.json`, and `review-report.md`, only after direct-AI translation, all semantic/visual reviews and successful finalization. This design authorizes no claim that the book has already been translated.
