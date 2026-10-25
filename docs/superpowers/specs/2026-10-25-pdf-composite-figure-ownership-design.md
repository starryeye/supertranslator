# Caption-witnessed composite PDF figures

Status: detailed design approved by the user's subsequent “네” on 2026-10-25. Implementation plan awaits review; no product code has changed.

## Intent

Allow a genuine source illustration to contain sentence-shaped example data without treating those sentences as independent book prose. Preserve its original pixels. Keep ordinary body, captions and independently extracted tables selectable and translatable. Translation and semantic/visual decisions remain direct AI work, not machine translation or automatic approval.

The immediate request is a whole, 491-page selectable-text book. Acquisition succeeded; extraction stopped on a framed profile-to-relational-schema illustration. The original page was visually inspected: the profile's summary, work history and education are example data within the illustration, not surrounding book prose. The input is below the existing page and byte limits. Nothing has been translated, approved or published for this run.

No book/title/page/font allowlist, source editing, image-text replacement, lowered safety limits, OCR, stale approval reuse or golden-file regeneration is permitted. A fix for the reproduced page does not itself establish that the remaining source pages can all be extracted or translated.

## Root cause

`pdf-extract` calls `_extract_page_materials`, then `partition_graphic_regions`. Candidate graphic bounds come from source raster/vector geometry. `_has_prose(owned_lines)` then rejects every candidate containing aligned multi-line prose or a styled title followed by prose. That shape also occurs in legitimate UI examples and diagram data. The rejection happens before the existing exact-character inventory and explicit master figure review can inspect it.

The source reproduces this error with unchanged bytes. Existing callout and graphic-safety regressions must remain meaningful: a decorative frame or a large stroke crossing body prose does not establish illustration ownership.

## Alternatives and selected boundary

1. Skip the offending page, specific words or fonts: rejected as source-specific and incomplete.
2. Remove the prose gate for every candidate: rejected; it unnecessarily admits unbounded or ambiguous prose/art mixtures.
3. Admit a narrow, structurally witnessed candidate and retain explicit AI approval: selected.

Only the semantic-shape refusal gains a narrow exception. Source geometry, complete character ownership, translatable-block exclusion, exact source/media/inventory/review binding and all publication gates remain unchanged.

## Proposed behavior

A prose-bearing graphic may reach extraction output as an **unapproved figure candidate** only when all the following source evidence exists:

- Its complete bounds correspond to a genuine closed, axis-aligned source frame. An enclosing bounding box inferred from a diagonal/curved stroke is not a frame. Handle equivalent rectangle primitives, four actual sides, and straight closed rectangle paths consistently; use existing geometric tolerances.
- It contains actual non-border artwork; a text-only boxed paragraph remains a callout, not a rasterized figure.
- There is an explicit, spatially separate figure caption outside the frame, accepted by the existing `Figure`/`Fig.` caption contract. Reuse that recognition and the existing distance/overlap/unique-matching semantics rather than introduce a second caption language or guess from font names.
- The source caption-to-figure relation is unambiguous across the page's candidates. A nearby caption is not permission to choose an arbitrary figure.
- No independently extracted non-caption text lies between the relevant frame edge and caption in their connecting strip. A caption cannot reach through ordinary prose to justify a candidate.
- Every candidate-owned glyph is completely inside the actual frame and has exactly one owner. Partial glyphs, conflicting peer ownership and overlap with a genuinely translatable block still fail closed.

An absent/broken frame, missing/distant/ambiguous caption, intervening body text or uncertain ownership keeps the existing refusal. Ordinary uncaptioned artwork with non-prose labels retains its existing behavior; this change adds no general support for uncaptioned prose-bearing artwork.

Caption evidence is recognition evidence, **not semantic approval**. The controller must inspect every original figure with source-page context, distinguish actual UI fields/node/data-label groups from absorbed body/caption prose, and record exact disjoint character groups with specific reasons in the current `figure_text_review`. An empty, missing, stale, incomplete, `required-fix` or invalid review must still block assembly, QA and finalization. A mistaken candidate is rejected at master review; it is never silently certified as an illustration.

Caption text remains outside the preserved image and enters normal translation exactly once. Independent body/table text outside the figure remains selectable. Intrinsic example data/table-like labels inside an approved illustration remain original artwork, as in the existing figure-review policy. This design authorizes no reconstructed or translated screenshot.

## Implementation boundary and builder choices

Limit production changes to the graphic classifier and the minimum shared caption-evidence helper/call-site changes required to reuse existing caption logic. Keep the extraction 1.2, inventory 1.0, semantic review, final manifest and thirteen visual dimensions unchanged. Do not duplicate the caption matching algorithm or introduce an override flag/approval cache.

The builder chooses the smallest pure-helper organization and how to represent temporary caption/geometry evidence. Such temporary evidence must not invent or change persisted source block IDs or target partitions. Reuse the existing isolated checkout on a dedicated `codex/` branch; preserve all older worktrees and evidence. No implementation on main or automatic main merge/public release/catalog/cache modification is part of this design. Each resulting commit must be pushed immediately, following the user's standing instruction.

## Acceptance

- Synthetic selectable PDFs reproduce framed composite artwork with sentence-shaped example data; vary text, font, scale, translation of origin and rectangle encoding rather than copy private book text/coordinates.
- Verify accepted candidate geometry, exact per-character ownership, disjoint caption/body targets, unchanged artwork pixels and explicit caption pairing. Caption wraps stay normal selectable targets, not cropped artwork.
- Existing decorated-callout/large-stroke prose refusal remains. Add negative cases for absent/broken/diagonal-only frames, text-only boxes, absent/distant/ambiguous captions, intervening body text and crossing glyphs. Do not weaken old expected refusals to make the new case pass.
- A generated candidate does not publish without exact current master approval. Test missing/stale/foreign/incomplete/required-fix figure evidence and body/caption overlap through existing assembly/QA/finalization consumers. Keep hash and race/refusal tests unchanged.
- Use faithful failing regressions before implementation, focused GREEN, independent task and final code review, the non-live suite, and proportionate exact-commit native macOS/Windows gates. No repeated full suite for unchanged code or mutation of old approved artifacts.
- After code validation, start a fresh native run against the entire original PDF using an explicitly identified candidate runtime, without modifying the installed/public 0.8.0 package or its immutable tag. Retain the failed run and source bytes. Run all-page extraction before translation dispatch to expose additional blockers honestly; do not patch source evidence or reuse old unit maps.
- Resume the whole-book AI translation only after extraction and required ownership/flow checks pass. All source figure reviews, zone semantic reviews and every rendered output page still require inspection before finalization. Only successful finalization produces the three promised public artifacts; otherwise preserve diagnostics and report the exact incomplete stage.

## Decisions to review

The source-frame plus unambiguous-caption witness was the builder's recommended conservative boundary and is now included in the approved design. It intentionally leaves other ambiguous prose-bearing illustrations unsupported rather than guessing. Implementation follows only after review of its separate plan.
