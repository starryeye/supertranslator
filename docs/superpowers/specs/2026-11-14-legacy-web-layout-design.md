# Legacy web layout compatibility

Finish the existing OIDC Discovery run without retranslating it. Its source-layout bundle exceeds a 390px viewport, and its reading edition needs to recognize the legacy fragment targets that already work in browsers.

## Approaches

- Apply responsive CSS only during final assembly for projected fixed-width code layouts, and recognize existing named anchors in the reader. This is the approved approach: a browser probe fit the actual page at 390px, with seven examples locally scrollable and the desktop layout unchanged.
- Changing the held projection invalidates evidence; relaxing QA leaves a broken mobile page. Neither is in scope.

## Contract

- An eligible source-layout bundle can add one exact backend-owned style after the captured head content, active only at viewport widths of 768px or less. Long inline text may wrap and projected examples inside inline table-formatted div wrappers can use the available width. Code retains fixed spacing and local scrolling.
- The fixed CSS declarations may use deterministic, escaped selector values derived from the held input. QA recomputes the complete expected stylesheet; source HTML and body markup never receive generated targeting markers. Dynamic or inline-important declarations that cannot be safely overridden retain the ordinary viewport checks.
- Keep captured HTML, projection, captured CSS, translated content, semantic evidence, and every QA gate unchanged. Older output without the generated style remains subject to the same acceptance checks.
- Recognize nonempty `a[name]` as a fragment target, preserve its name through export, and never generate a navigation ID that shadows it. Duplicate IDs and unresolved links remain failures.
- Reuse the 471 approved translation targets, use new output directories, and require fresh browser and visual verification of the result. No release or public posting.
