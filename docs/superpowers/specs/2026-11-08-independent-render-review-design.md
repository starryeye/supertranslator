# Independent render and full-comparison review skills

Status: design and both implementation plans approved by the user on 2026-11-08.
Implementation started on `feat/independent-render-review`; completion and release
status are tracked separately from this approval.

## Intent

Expose two separate user-facing capabilities in the existing supertranslator plugin:

- `supertranslator-render`: reuse approved AI translation for HTML editing/output
  or PDF re-typesetting without retranslation.
- `supertranslator-review`: independently compare an original document and the
  actual final translation, including complete semantic and visual inspection.

Keep `supertranslator-web` and `supertranslator-pdf` as separate translation entry
points. The spelling `upertranslator-render` was corrected by the user to
`supertranslator-render`.

## Approaches and chosen boundary

Options discussed were adding stage options to the two translation skills or adding
separate user-facing skills backed by existing modules. The user requested the
independent review skill, explicitly excluded it from the web/PDF/render procedures,
and also requested the render skill. Use separate skills with shared implementation;
do not duplicate the engines or introduce a replacement translation framework.

Existing automatic validation, master semantic approval, and required output visual
QA remain in the translation/render workflows. They are not replaced by, delegated
to, or made dependent on the new standalone review skill.

## Render contract

- Accept an existing reviewed run/bundle and a supported requested layout change,
  or regenerate using the updated renderer. Locate and verify its original and
  translation evidence; a final HTML/PDF alone is not necessarily a reusable run.
- Reuse the existing HTML `assemble`/`export-reader` and PDF `pdf-assemble`/QA
  capabilities where applicable. Inspect their state/output constraints before
  implementing safe reuse; successful arbitrary rerendering is not assumed.
- Preserve approved translation, protected content, assets, and source ownership.
  Do not reacquire/extract the original or dispatch AI translation implicitly.
- If required evidence is absent/stale, the requested setting is unsupported, or
  fixing the request requires changing translation, report the specific limitation.
  Do not silently restart translation, invent approval, or weaken existing checks.
- Produce a new output revision, preserving old runs, outputs, and review records.
  A PDF may require whole-document re-typesetting because pagination changes.
- Run existing applicable integrity and output QA. Reuse semantic approval only for
  the exact still-valid inputs; bind new visual evidence to the new output.
- Do not invoke `supertranslator-review` or require its report to complete rendering.
  Public website deployment is not part of this skill.

## Standalone review contract

- Activate for a user request to review/compare an original and translated final
  HTML/PDF, including natural-language requests for the established full comparison.
  Do not activate merely because translation or rendering is finishing.
- Resolve the exact original and actual final artifact. Read the final output, not
  just intermediary translations or old reports. If a required input is unavailable,
  report the limitation rather than claiming full source comparison.
- Default to complete direct comparison: all claims, actors, conditions, exceptions,
  negation, normative force, terminology, coherence, and natural Korean throughout
  front matter, body, tables, captions, footnotes, references, and appendices.
- Retained English CS terminology is intentional, not an error by itself. Respect
  the user's terminology policy and distinguish source quirks from translation bugs.
- Compare original and result visually throughout. For HTML inspect the entire
  document at desktop, tablet, and mobile widths (existing 1440/768/390 baselines).
  For PDF cover every source/output page, following logical content across reflow
  rather than assuming equal page counts or matching page numbers.
- Judge font size, spacing, hierarchy, grouping, lists, tables, artwork/captions,
  footnotes, transitions, clipping, glyphs, and reading order. Inspect detailed views
  where overview/contact-sheet views cannot establish the relevant quality.
- Automated checks supplement direct reading and image inspection; hashes, a prior
  pass, screenshots merely existing, or a sample do not prove full review.
- Narrow review only when the user explicitly requests it. Never silently downgrade
  an ordinary review request to automated QA, changed-only review, or a sample.
- Produce a separate report with input identity, actual coverage, located findings,
  source/result differences, impact, recommendations, and unreviewed limitations.
  Track completed coverage for long reviews; incomplete coverage is not completion.
- Preserve reviewed inputs. Evidence/report writes go to a separate review location;
  do not run QA commands that mutate the original output in place.
- No artifact corrections, retranslation, renderer edits, commits of reviewed
  artifacts, publication approval, or public deployment are implied by review.

## Size, implementation order, and checks

Start with two focused skill entrypoints and only necessary references/integration
changes. Implement/test render first, then implement/test review independently.
No new service, universal document model, OCR support, cross-format conversion,
review-mode framework, or automatic translate-review-fix loop is in scope.

Use representative HTML and PDF artifacts to test actual stage selection, reuse of
approved content, preserved originals, truthful review coverage, and the absence of
review invocation in the other workflows. Validate skill discovery and packaging;
test behavioral instructions with bounded independent scenarios, not just wording
matches. Follow the user's standing commit-and-immediate-push preference when
committing, and report release/install status separately from implementation.

Render-first is the assistant's proposed implementation order. This design does not
authorize replacing the three existing public RFC editions or publishing PKCE;
those require a separate requested publication step after verification.
