# Reviewed reading editions and existing blog publication

The user approved the recommended full-text blog approach and proceeding without
further design questions. Implement directly in an isolated feature-branch clone;
do not touch the unrelated PDF worktree or historical translation runs.

## Intent and approach

Keep the existing source-preserving HTML workflow unchanged. Add an explicit
`export-reader` post-processing command for an already reviewed local HTML bundle.
It produces a standalone offline reading edition and the exact same article as an
HTML fragment suitable for the existing Jekyll blog. CSS overrides on the original
site alone cannot remove empty site chrome or safely join interrupted paragraphs;
link-only blog posts do not satisfy the requested full-text blog experience.

## Contract

- Require a review JSON bound to the exact input HTML SHA256; no guessed main content.
  One explicitly reviewed content selector must resolve to exactly one element.
- Review names exact page-furniture elements to move into collapsed source notes,
  adjacent paragraph groups to join, heading levels and source list items to style.
  Joins concatenate existing translated inline DOM in order, never machine-translate
  or invent text. If wording needs changes, the AI rechecks the complete source
  paragraph and updates affected translation evidence separately.
- Retain all content inside the selected article except executable/site styling;
  keep source notes, IDs, links, code, diagrams, figures, normative keywords and numbers.
  Do not silently join across an unreviewed heading, list, figure or paragraph.
- Require successful input QA, retain its original manifest/report alongside new
  provenance. This is a derivative reading edition, not retroactive new semantic approval.
- Use 18px/1.75 desktop body, 16px/1.75 narrow body, maximum 48rem article width,
  (also capped at 768px under larger blog root fonts), 1em paragraph separation,
  semantic heading hierarchy, local overflow for literals
  and tables. Blog dark theme inherits colors; offline edition supplies light colors.
- New output directories only; reject overlap, links/reparse ancestors, unsafe assets,
  foreign local paths, executable markup. Emit `index.html`, `article.html`,
  `assets/reader.css`, `manifest.json`, `review-report.md`, and preserved input evidence.
- New artifacts get fresh browser QA and visual review before public replacement.
  Visual approval binds HTML, reusable article, CSS and all captured asset hashes.
  Check 1440, 768, 390px; prose font >=16px, no document overflow, literal text exact,
  local assets load and internal destinations remain available.

## Publication

Regenerate RFC 6749, 6750 and 9700 only. Keep raw runs unchanged. Update
`standard-document` with the reading editions. Keep the existing Minimal Mistakes
dark skin, author/sidebar/navigation and home archive. Replace precisely the two
existing `_posts/Blog` posts with three full-text RFC posts. Retired articles remain
recoverable from Git history; no force push or history rewriting. No iframe or
Datatracker site navigation inside the article. Use stable `/rfc/rfcNNNN/` permalinks.
Preserve notices, attribution and review links. Validate the Jekyll build and live
desktop/mobile rendering before claiming deployment. Commit and push each change.

## Non-goals

No new translations beyond these three, no PDF changes, no translation service,
no new web framework, no replacement blog theme, no universal inference engine.
