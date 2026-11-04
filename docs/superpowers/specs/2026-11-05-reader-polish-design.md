# Reader polish following direct source comparison

The user accepts English-first nouns (`client`, `resource owner`, `authorization server`). Keep that policy, the two skills, PDF behavior, historical runs, and source-preserving web output unchanged. Fix the other four findings from `translated-pages/direct-review-20261104/review.md` and regenerate/publish the same three RFCs. Prior direct-execution preference applies; do not introduce another approval loop.

## Approach

Extend the existing explicit reader review rather than adding document-name exceptions or rewriting historical translation runs. A stylesheet-only change cannot repair print-only navigation or sentences; rebuilding all translations is unnecessary. The controller supplies bounded, source-compared sentence edits and presentation selections. Python validates them and performs deterministic assembly; it never translates.

Existing schema 1.0 reviews remain accepted. Two optional fields are additive:

- `text_edits`: entries with exactly `selector`, `input_html_sha256`, `replacement_html`, `source_text`, `evidence`. Select exactly one p/li after paragraph joins. Bind canonical inner HTML, require nonempty original-language source and AI semantic evidence, preserve every inline subtree, all English/digit atoms, and protected normative/URL/code tokens. Inline subtrees may move as intact units; new tags, changed links/code, lost tokens, overlapping/repeated edits and edits inside source notes fail before output publication.
- `presentation`: exactly `toc_selectors`, `metadata_selectors`, `title_selectors`, `navigation`. Each selector matches one reviewed element, must not overlap another selection, and cannot select the article root or contain unrelated body prose. Titles must be headings; metadata is a dl/table/header or a div containing a dl; original TOC selections are a heading/p/nav or a div containing nav. Archive original TOC blocks in source notes; fold metadata into a native details element near the start. Preserve all original content, IDs, links and literals. Build a collapsed, hierarchical native-details navigation from live headings, with collision-free deterministic IDs. Mark reviewed document titles; only an explicit `.st-reader-embed` host wrapper hides them in favor of its visible blog title. Standalone titles stay visible.

Mark pilcrow fragment links with a scoped class, retain labels/destinations, lower their resting visual prominence and restore it on keyboard focus/hover. Reduce embedded top padding and heading whitespace; do not shrink body below 18px desktop / 16px mobile. Navigation uses compact spacing, not paragraph margins. No JavaScript, new dependency or template framework.

## Evidence and acceptance

Maintain exact hashes and old QA failure behavior. Record bounded sentence edits separately from the previous whole-document semantic review. Editorial source and evidence are hashed with reader review; output changes require fresh visual approval. Never reuse the old visual digest for changed render bytes.

Use synthetic non-RFC examples for regressions: tag/link/token mutation rejection, changed input digest, malformed/overlapping selections, generated-ID collision, nested headings, copied destinations, metadata preservation, native keyboard navigation and visible focus, embedded/standalone title behavior and real browser readability. Run the full suite plus installed-wheel macOS/Windows CI. A single fresh-context final review precedes release.

For actual results, keep English nouns, AI-correct the two demonstrated sentence defects, preserve untouched prose/literals, and regenerate RFC 6749/6750/9700 to new directories. Validate navigation links, closed TOC, compact initial layout, pilcrow focus behavior, full retained text with exactly the approved edits, and screenshots. Build existing Jekyll blog with only the explicit host wrapper/content update. Release 0.10.0, update marketplace pin, install it and update runtime, regenerate using that installed runtime, commit/immediately push each commit, publish archives/blog, and verify live URLs.

Integration correction: the installed 0.10.0 export correctly failed the inspected-render equality gate when archived headings re-entered navigation. BeautifulSoup may retain manually assigned class attributes as strings; class comparison must normalize through `get_attribute_list`. Keep the immutable 0.10.0 tag, supersede it with 0.10.1, retain the unapproved partial output, use new versioned directories, and rerun the final gates before publishing any result.
