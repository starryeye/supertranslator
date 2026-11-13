# Initial web translation: deliver the reading edition

Use this after `assemble` and source-bundle `qa` succeed. The source-preserving
HTML, assets, manifest, and report remain the immutable QA-passed input, not a
file to patch. If source QA did not pass, stop; do not export a reader.

If the user explicitly requested **only** a source-layout version, return its
absolute `index.html` and `review-report.md` links and all optional-asset
warnings, and stop. “Offline HTML” by itself does not request source-only delivery.

Otherwise:

1. Read the shared [HTML rendering guide](../../supertranslator-render/references/html.md).
   Use its bound input, supported layout contract, export and fresh visual QA
   directly as part of the web workflow; do not start another translation or
   require a separately requested render or independent full comparison.
2. Inspect the actual bound HTML and source structure. Write a fresh
   `reader-review.json` in the private work directory, bound to the approved
   bundle's exact HTML digest. Select the complete article region and retain
   title, front matter, notices, references, and all other document content.
   Use only source-supported decisions: move recurring print furniture to
   source notes, join demonstrably continuous prose, derive navigation from
   reviewed headings, and group lists or definitions only where the source
   supports them. For projected preformatted lists, carry reviewed grouping and
   depth from `data-wt-preformatted-depth` into `structure.lists` where needed;
   the reader strips the projection's styling. If an existing hierarchy cannot
   be preserved safely, report it as a reader blocker. Preserve examples and
   literal content. Leave optional transformations empty or absent when
   unnecessary; simple prose still gets a reading edition. Do not create new
   wording edits in this layout stage.
3. Export to a separate unused sibling of the source bundle (normally the
   source folder name plus `-reader`). Keep both paths absolute and lexical;
   do not reuse or replace an existing output or linked path. Use the same
   resolved interpreter as the web workflow. Run `qa-reader`, inspect all
   current screenshot tiles at 1440, 768, and 390px and relevant opened
   sections, then finalize using fresh visual evidence bound to that edition.
4. Once the reading edition's manifest says `qa_status: "passed"`, lead with
   its absolute `index.html` and `review-report.md` links. Link the original
   QA-passed source-preserving bundle separately for reference and rerendering.
   Report any known limitations.

If the article cannot be selected or safely represented, export fails, or
visual QA cannot finish, report the exact reader blocker and preserve the
completed source bundle. It may be linked as the **source-layout fallback**,
but do not link a pending reader as a completed result or imply that the
default reading delivery passed. Do not bypass an integrity check, silently
discard content, or rerun translation to work around a reader failure.
On every path that delivers the approved source bundle or its derivative,
report optional-asset warnings from the original bundle's manifest
(`assets.missing_optional` and `warnings`), even if absent in the reader report.
