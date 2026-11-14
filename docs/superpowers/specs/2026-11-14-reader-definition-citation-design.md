# Readable definitions and citation details

Finish the existing OIDC Discovery reading edition using its QA-passed Korean bundle as the sole source of rendered content. Keep the 471 approved translations, original bundle, and semantic evidence unchanged. This is a generic reading-renderer change, not a new translation pass.

## Approaches

- **Recommended:** cap the label column of native definition-list grids and let long labels wrap. Add an opt-in, source-hash-bound citation selection to the existing reader review: keep the citation link and its visible label unchanged, and expose its preserved detail using a separate inline button and native HTML popover.
- Keep all definitions stacked globally and copy the original hover CSS or use a title attribute for every citation. The first changes compact glossaries unnecessarily; the second imports arbitrary presentation rules or provides unreliable keyboard/touch access. Do not use either shortcut.

## Contract

- Ordinary compact definition lists keep their grid on wide screens, long labels cannot squeeze the description column, and mobile keeps its existing stacked layout. Preserve \<dl\>, \<dt\> and \<dd\> semantics. In the actual 35-term OIDC list, the description should use at least half of the list width on a wide screen.
- Opt-in citation selection is bound to exact approved input bytes, resolves before sanitization, and is restricted to plain-text trailing inline detail nodes inside the same link. Such nodes must have a nonempty visible citation label and no links, destinations, code, images or other semantic subtrees inside their detail. Reject ambiguous, overlapping or stale selections instead of hiding content by heuristic.
- Preserve the exact original link destination, visible label, and detail text. Move the detail exactly once to a generated disclosure separate from the link, with its content preserved by explicit checks rather than weakening the existing protected-link comparison. Generate IDs that cannot shadow existing IDs or legacy anchor names. Do not allow source-authored controls or source CSS through the sanitizer. Use native popovers without adding script or changing CSP; verify pointer, keyboard and touch use as well as actual citation navigation.
- Existing review files remain valid without the optional feature. Do not rewrite past exports or publish the OIDC translation. Export a new revision from the QA-passed bundle and approve it only after automated QA and actual full visual inspection. No next document until delivery status is reported.
