# Preformatted source contract

Read after `prepare-preformatted` creates `preformatted/analysis.json`, before `extract`.
This adapter makes prose in ordinary `<pre>` translatable through the existing web
workflow. It is not another translator or permission to author HTML. The original
`source.html`, `capture.json` and captured assets remain exact; the backend creates
`preformatted-source.html` and separately bound critical CSS.

## Classification and master approval

1. Read the immutable analysis and every `preformatted/packages/package-NNNNNN.json`.
   Analysis inventories roots, physical lines, separators, original attributes/IDs,
   node slices and explicit preservation constraints. Packages carry target lines plus
   bounded read-only neighbors. Only target lines count toward coverage: at most 200
   lines and 12,000 text characters per package; at most two context lines per side,
   each excerpt at most 256 characters. Never truncate or expand the package to fit.
2. Classify every target line exactly once, in original order, into contiguous blocks
   within one pre root. AI judges meaning; deterministic inventory is not a heuristic
   approval. A block may cross a package boundary, but not an intervening page header,
   footer or other literal island. Inspect both sides of each boundary. A physical
   line or proposed block over 12,000 text characters stops; do not hide it as literal.
3. The master inspects **every block** against its actual source, including every
   preservation decision. Translate explanatory sentences, normative requirements,
   headings, lists and captions; adjacent drawings, code or aligned content do not
   make surrounding prose disposable. Record a source quotation as `evidence` and
   keep a concise master inspection record explaining each literal decision, both
   boundary transitions and any ambiguity. A plausible paragraph classified literal
   is not safe just because its record validates. No source-specific whitelist applies.
4. Write `preformatted/review.json` using the exact record below. Unknown or unresolved
   content stops before materialization. The backend checks structure, source hashes
   and coverage, not semantic correctness. Only a fully inspected, resolved partition
   can proceed. Do not infer approval from a nonempty reason or a passing validator.

| Role | Decision and exact metadata |
| --- | --- |
| `prose` | Reflow and translate prose. `{}` |
| `heading` | Translate a source heading. `{"level": 1}` through level 6; no impossible hierarchy jumps. |
| `list-item` | Translate item prose; retain its original marker, without a second generated label. `{"depth": 0, "marker_span": {"line_id": "line-000001", "start": 0, "end": 2}}`; span must identify the original marker, depth starts at 0 and increases at most one. |
| `caption` | Translate caption. `{}` or `{"adjacent_block_id": "block-000002"}` for an immediately adjacent diagram/table only. |
| `literal-code` | Requires an explicit source code constraint; never guess code from punctuation. `{}` |
| `literal-diagram` | Preserve exact drawing, including labels and spacing; explain its graphical role. `{}` |
| `literal-table` | Phase 1 preserves the whole fixed table, including English text. Explain column/alignment evidence and disclose this limitation. `{}` |
| `literal-layout` | Preserve genuine page furniture or fixed layout; explain why it is not document prose. `{}` |
| `blank` | Whitespace-only lines. Empty evidence is allowed only here. `{}` |
| `unknown` | Unresolved required finding; cannot materialize. `{}` |

Do not add rationale keys to the strict wire record. Its `evidence` is a literal
substring of the block's decoded text (including recorded separators), not a free-form
explanation; put the master's explanation in the separate inspection record.

## Exact reviewed record

Use the existing `canonical_sha256` from `web_translator.preformatted_contract` for
the parsed analysis/package objects. Copy `source_sha256` from analysis, not a guessed
hash of normalized text. `package_sha256` maps **every** package stem to its canonical
digest. No extra/missing keys or duplicate JSON keys are allowed.

```json
{
  "schema_version": "1.0",
  "source_sha256": "<analysis.source_sha256>",
  "analysis_sha256": "<canonical analysis digest>",
  "package_sha256": {"package-000001": "<canonical package digest>"},
  "blocks": [
    {
      "id": "block-000001",
      "pre_id": "pre-000001",
      "line_ids": ["line-000001"],
      "role": "prose",
      "evidence": "<literal source quotation>",
      "metadata": {},
      "literal_spans": []
    }
  ],
  "unresolved_required": []
}
```

Replace all illustrative values with actual source-bound values. Block IDs are the
continuous `block-000001` sequence; pre/line IDs come from analysis. Flattened block
line IDs must exactly equal the analysis line sequence. Role-inapplicable metadata
must be empty. Never edit analysis/packages, invent markup, IDs, markers or associations.

For each URL broken across physical lines, protect the entire original span in the
owning block's `literal_spans`. Each span has exactly `kind: "url"`, `start_line_id`,
`start_column`, `end_line_id`, `end_column`, `source_sha256`. Columns are zero-based
Unicode codepoint offsets, end-exclusive, in decoded analysis line text; include all
recorded separators between endpoints. Hash the exact selected decoded string's UTF-8
bytes, including CR/LF and decoded entities (e.g. `&`, not HTML `&amp;`). It must remain
inside that block. Preserve address, wrapping and punctuation exactly; malformed or
unrepresentable boundaries stop instead of guessed URL repair. Do not replace URL
text, split a protected span across blocks or translate drawing labels.

## Materialize and resume the existing workflow

Using SKILL.md's resolved interpreter and native path argument rules, run:

```text
<python> -m web_translator materialize-preformatted --run-dir <work-dir>
```

Stop on any nonzero exit. This creates the deterministic projected source and locks
the reviewed bytes in provenance; subsequent review edits require a fresh run, not
automatic regeneration. Inspect the projection's prose, literals, IDs/links and both
boundaries against the master record, then resume SKILL.md at `extract`, `plan-zones`
and immutable translation assignments. Keep English-first glossary display, exact
zone partition, AI-only translation, same-agent maximum-two retries, and every-zone
six-dimensional master review including both read-only boundaries unchanged.

Normal `assemble` and `qa` must pass and produce `index.html`, `manifest.json` and
`review-report.md`. Inspect desktop and narrow screenshots, including each drawing,
wrapped URL, list and page-furniture transition; the main-only clipping metric is not
enough. Report optional-asset warnings and preserved fixed-table/layout English.
Existing numeric-entity/style limitations remain; do not repair them by changing the
raw capture, hiding prose as literal, arbitrary AI markup or machine translation.
