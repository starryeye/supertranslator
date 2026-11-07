# Reader structure candidate — verification and decisions

Implementation plan: `../plans/2026-11-06-reader-structure.md`.
Base: `f22e2537c57101d335fd11583b717ec54e451026`.
Scope: optional explicit definition/list structure in derivative readers, one
qualification-reference example, and a new local PKCE candidate. No release,
marketplace change, main merge or public-site replacement is authorized here.

## Evidence

- Six positive real-export/browser tests first failed on unsupported structure.
- A short-comment boundary case separately failed before comments were excluded
  from offset validation; offset semantics now match text extraction/sanitation.
- Source and isolated installed-wheel reader runs each passed 128 tests. The
  installed run disabled source imports; it used Playwright 1.62.0 to match the
  existing Chromium installation. Product dependency declarations are unchanged.
- Skill quick validation and 19 existing skill-contract tests passed. A fresh
  reference application check rejected both a strengthened exception threshold
  and weakened demonstrated necessity, and accepted the correctly conjunctive
  plain condition. This is limited case evidence, not a translation benchmark.
- The original restricted baseline had 3210 passed, 89 failed, 2 errors,
  15 skipped and 2 deselected. All 91 failed/error cases passed on unchanged main
  in an approved unrestricted rerun; browser/local-network restrictions caused
  the initial failures.
- Full changed suite: **3354 passed, 15 skipped, 2 deselected** in 1179.27s.
  Command: `PYTHONPATH=src <existing-venv-python> -m pytest -q` (approved
  unrestricted execution, temporary pytest cache). No product/test code changed
  during or after that run. This is local macOS evidence, not native Windows CI.

## Actual PKCE candidate

Local output: `translated-pages/rfc7636-reader-20261107-structure-candidate` in
the primary checkout. Existing accepted outputs were not replaced. A local wheel
was installed into an isolated temporary runtime; version remains 0.10.2, but
this is NOT the released 0.10.2. Candidate source/wheel/CSS hashes are recorded
in `candidate-provenance.json` beside that result.

Fifteen term/description boundaries, six separate groups and one nested child
list were reviewed explicitly. Entire reader text equals the previous reader
except one AI correction from inevitability to persuasive grounds in §6.2.1.
Literal text/order and 156 previous files remain unchanged. The controller
personally viewed all 22 bounded tiles (7 at 1440px, 7 at 768px, 8 at 390px).
Final browser and exact-render-bound visual QA passed with render input hash
`883859723c47a63137074ed02e70a94d6a2c8282510dfe86def894cc9692f314`.

## Final independent review

One fresh-context whole-branch review: no Critical or Important finding. One
Minor: the presentation-collision test uses an invalid TOC target, so it fails
before exercising the new overlap guard. The reviewer confirmed that a valid
dotted TOC paragraph is correctly rejected by the production overlap guard.
This test-only refinement remains deferred under the approved execution policy.

## Rulings and limitations

1. Final review ran on the frozen working-tree snapshot while the long full
   suite finished, rather than after commit. No product/test code changed after
   the snapshot. Reviewing a different final snapshot would invalidate the gate.
2. This is an accepted-translation derivative with one bounded AI edit, not a
   full retranslation. Previously undetected semantic errors may still exist.
3. Pre-existing credits/contact typography and metadata visibility remain
   deferred. The result is not claimed to have perfect publishing typography.
4. Release/marketplace/public-site readiness is not established. Installed
   marketplace users do not receive these candidate changes until a release.
5. Full visual inspection was by the controller; the independent reviewer
   sampled the mobile nested list, not every screenshot. There were not two
   independent full-document visual reviews.
