---
name: supertranslator-render
description: Use when a user requests layout-only editing, a reading edition, or rerendering of an existing reviewed HTML bundle or PDF run. Not for initial translation or a full original-to-final comparison review.
---

# Supertranslator Render

Reuse approved translation; produce a new output revision with its own output QA.
Rendering is not retranslation or a new full-document semantic approval.

## Resolve the request

Identify the existing artifact, its approved private inputs, and the requested
layout change. Read only the selected format's guide:

| Existing format | Required guide | Reusable input |
| --- | --- | --- |
| HTML / reading edition | [HTML](references/html.md) | Original QA-passed bundle plus source-bound reader review |
| PDF | [PDF](references/pdf.md) | Native reviewed private run with exact semantic/figure evidence |

An exported reader is a derivative, not automatically the input bound by its
`reader-review.json`. Locate the original bundle using its exact byte bindings
before export. A final PDF alone also lacks the private run needed for reuse.
If required inputs are missing, stale, or unresolved, report which evidence is
needed and stop. Do not reacquire, extract, or translate to fill the gap.

Check support before allocating output. HTML supports reviewed structure and
presentation selections described in its guide. PDF supports regeneration with
the current renderer; it has no arbitrary font/margin/page-size settings API.
For unsupported changes, state the limitation and preserve all inputs. A request
requiring different wording or source ownership is outside render-only scope;
report that boundary instead of creating new translation edits.

For example, “add a collapsed TOC to this existing reader” means locate its
bound original bundle, retain its historical reviewed `text_edits`, add the
supported `presentation.navigation` selection in a separate review revision,
export once from that bundle into a new directory, and inspect the new output.

## Execution and completion

Detect the active OS/shell. Resolve an existing environment that imports this
plugin's `supertranslator` package. Use its absolute native interpreter directly:
PowerShell `& $python`, POSIX `"$python"`. A repository-local environment normally
uses `.venv\Scripts\python.exe` or `.venv/bin/python`. Do not activate a shell
environment or construct/evaluate command strings. Every path is one argument,
including spaces and non-ASCII characters. The guides' `<python>` and path tokens
are notation: substitute native invocation and actual paths before execution.

Preserve old runs, outputs, and approval records. Use an unused output revision;
never patch published HTML/CSS/PDF or manifests to bypass byte bindings. Retain
valid historical editorial edits exactly once from their bound input; add no
new wording edits. Stop on a nonzero stage result and retain its diagnostics.

Run the format's integrity gates and freshly inspect the new visual output,
even when a deterministic rerender has the same digest as its predecessor.
Old visual-review files are historical evidence, not new inspection. If browser
or image inspection is unavailable, report QA incomplete without inventing pass
evidence. Normal completion links the new artifacts and reports the requested
change, reused input identity, QA coverage, and warnings/limitations.

Do not invoke `supertranslator-review` or require its report. Independent full
comparison, renderer development, and public deployment are separate requests.
