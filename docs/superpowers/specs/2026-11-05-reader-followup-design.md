# Direct-review reader follow-up

Implement the user's acceptance of `translated-pages/direct-review-20261105/review.md` using the existing direct-execution preference from the reader-polish design. Do not introduce another approval loop or restart translation.

## Intent and constraints

Repair the three P2 findings: the remaining split condition in RFC 6749 §6, awkward source-compared normative sentences in RFC 9700, and unowned synthetic list items in the generic reader. English CS/security terms stay English; Python never translates. Keep old inputs/outputs, all exact token/link/literal protections, PDF behavior, and the two skills unchanged. Create new reviewed outputs rather than overwrite historical results.

## Approaches

The accepted narrow approach reuses existing explicit paragraph joins and bounded AI text edits. Changing source extraction or retranslating all documents would invalidate already-reviewed text unnecessarily. For lists, use a `div role="list"` around contiguous explicitly reviewed items, retaining the original p/div elements, text, markers and IDs. Replacing items with native li would change protected numbering and break stored selectors for no additional benefit in this patch. CSS-only indentation cannot fix ownership.

## Assembly change

Group only elements explicitly marked by `list_items`. Resolve all existing review selectors and apply text edits before introducing wrappers. Group across whitespace and empty anchor spacers only; a heading, prose, literal or nonempty separator ends a group. Move inter-item whitespace/spacers intact so text and fragment boundaries remain identical. Existing immediate native/ARIA list parents need no extra wrapper. No new public review fields, dependency, CSS layout, automatic content classification or document-specific code.

## Editorial changes

Add the missed approved join for block-001082/block-001083. The controller authors natural Korean replacements for RFC 9700 §4.5.3.2 and §2.6, compares each against the original and retains intact normative/reference/code subtrees and English/numeric atoms. No machine translation. The P3 Section/Appendix label inconsistency is deferred: changing it would require relaxing current English-atom and link-label invariants; this release must not quietly weaken those protections.

## Acceptance and publication

Synthetic non-RFC tests prove list ownership, preservation, safe grouping boundaries and unchanged reviewed selectors/edits. Full suite, one fresh final code review, then patch release 0.10.2 with existing installed-wheel Windows/macOS checks. Each commit is pushed immediately. Regenerate the same three RFCs with the released runtime; validate unchanged prose except approved joins/edits, exact protected content, valid navigation and new visual approvals. Update only those archive/blog publications and verify live bytes/CSS and mobile/desktop layout. Keep unresolved minor label consistency visible in the handoff.
