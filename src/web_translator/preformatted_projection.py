"""Deterministic source-derived flow projection for reviewed preformatted prose."""

from __future__ import annotations

import copy
import hashlib
from importlib.resources import files
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from web_translator.preformatted_analysis import (
    _path, _text_nodes, analyze_preformatted, build_classification_packages, validate_review,
)
from web_translator.preformatted_contract import (
    NORMALIZATION_POLICY, SCHEMA_VERSION, NormalizationSummary, PreformattedAnalysis, PreformattedContractError,
    ProjectionArtifact, ReviewedBlocks, canonical_sha256,
)
from web_translator.extract import (
    _attribute_targets, _content_owners, _fragment_without_owned_descendants,
    _has_translatable_text,
)
from web_translator.models import Segment
from web_translator.protection import protect_fragment


_FLOW = {"prose", "heading", "list-item", "caption"}
_PRESERVED = {"literal-code", "literal-diagram", "literal-table", "literal-layout", "blank"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "param", "source", "track", "wbr"}
_TAG_NAME = re.compile(r"<\s*(/?)\s*([A-Za-z][A-Za-z0-9:_-]*)")


def _digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _fail(message: str) -> None:
    raise PreformattedContractError(message)


def _clone_range(pre: Tag, offsets: dict[int, tuple[int, int, str]],
                 start: int, end: int, block_id: str) -> list[Tag | NavigableString]:
    """Copy whole inline elements only; splitting an attributed node is unsafe."""
    def bounds(node: Tag | NavigableString) -> tuple[int, int] | None:
        if isinstance(node, NavigableString):
            item = offsets.get(id(node))
            return (item[0], item[1]) if item else None
        parts = [offsets[id(text)] for text in node.descendants if id(text) in offsets]
        return (parts[0][0], parts[-1][1]) if parts else None

    result: list[Tag | NavigableString] = []
    for child in pre.children:
        if isinstance(child, Comment):
            _fail(f"{block_id}: comment inside eligible pre has no safe line owner")
        span = bounds(child)
        if span is None:
            if isinstance(child, Tag):
                _fail(f"{block_id}: empty inline element has no safe line owner")
            continue
        first, last = span
        if last <= start or first >= end:
            continue
        if isinstance(child, Tag):
            if first < start or last > end:
                _fail(f"{block_id}: unsafe cross-node boundary at {_path(child)}")
            result.append(copy.deepcopy(child))
        else:
            result.append(NavigableString(str(child)[max(0, start - first):min(last, end) - first]))
    return result


def _block_offsets(block, lines_by_id) -> tuple[int, int, str]:
    lines = [lines_by_id[key] for key in block.line_ids]
    pieces = [line.text + line.separator for line in lines]
    slices = [item for line in lines for item in (*line.slices, *line.separator_slices)]
    if not slices:
        # An empty root is legal but has no source-node slice.
        return 0, 0, ""
    return slices[0]["start"], slices[-1]["end"], "".join(pieces)


def _span_interval(span, block, lines_by_id) -> tuple[int, int]:
    position = 0
    starts = {}
    for key in block.line_ids:
        starts[key] = position
        line = lines_by_id[key]
        position += len(line.text) + len(line.separator)
    return (starts[span["start_line_id"]] + span["start_column"],
            starts[span["end_line_id"]] + span["end_column"])


def _verify_flow_reparse(block, lines_by_id, rendered_text: str) -> None:
    """Require each source line's characters exactly; only flow separators may reflow."""
    opaque = [_span_interval(span, block, lines_by_id) for span in block.literal_spans]
    position = 0
    source_position = 0
    for line_id in block.line_ids:
        line = lines_by_id[line_id]
        if not rendered_text.startswith(line.text, position):
            _fail(f"{block.id}: unsafe whitespace/HTML serialization changed source line text")
        position += len(line.text)
        source_position += len(line.text)
        if not line.separator:
            continue
        separator_end = source_position + len(line.separator)
        if any(first <= source_position and separator_end <= last for first, last in opaque):
            alternatives = (line.separator,)
        elif line.separator == "\r\n":
            alternatives = ("\r\n", "\n")
        elif line.separator == "\r":
            alternatives = ("\r", "\n", " ")
        else:
            alternatives = ("\n",)
        matching = next((value for value in alternatives if rendered_text.startswith(value, position)), None)
        if matching is None:
            _fail(f"{block.id}: unsafe whitespace/HTML serialization changed source separator")
        position += len(matching)
        source_position = separator_end
    if position != len(rendered_text):
        _fail(f"{block.id}: unsafe whitespace/HTML serialization added source text")


def _wrap_opaque(soup: BeautifulSoup, element: Tag, start: int, end: int,
                 kind: str, block_id: str) -> str:
    cursor = 0
    for text in list(element.descendants):
        if not isinstance(text, NavigableString) or isinstance(text, Comment):
            continue
        value = str(text)
        stop = cursor + len(value)
        if cursor <= start < end <= stop:
            before, selected, after = value[:start - cursor], value[start - cursor:end - cursor], value[end - cursor:]
            code = soup.new_tag("code")
            code[f"data-wt-preformatted-{kind}"] = block_id
            code.string = selected
            if before:
                text.insert_before(NavigableString(before))
            text.insert_before(code)
            if after:
                text.insert_before(NavigableString(after))
            text.extract()
            return selected
        cursor = stop
    _fail(f"{block_id}: unsafe opaque {kind} span crosses inline DOM nodes")


def _attrs(tag: Tag) -> dict[str, object]:
    return {key: list(value) if isinstance(value, list) else value for key, value in tag.attrs.items()}


def _source_anchors(soup: BeautifulSoup, roots: dict[int, str],
                    offsets: dict[int, tuple[int, int, str]],
                    block_ranges: dict[str, list[tuple[str, int, int]]]) -> list[dict[str, object]]:
    anchors = []
    for tag in soup.find_all(True):
        if tag.name != "a" and not tag.has_attr("id"):
            continue
        owner = next((ancestor for ancestor in tag.parents if id(ancestor) in roots), None)
        if id(tag) in roots:
            owner = tag
        root_id = roots.get(id(owner)) if owner is not None else None
        descendants = [offsets[id(node)] for node in tag.descendants if id(node) in offsets]
        block_id = None
        if root_id is not None and descendants and tag is not owner:
            first, last = descendants[0][0], descendants[-1][1]
            block_id = next((block for block, start, end in block_ranges[root_id]
                             if start <= first and last <= end), None)
        anchors.append({"id": tag.get("id"), "tag": tag.name,
                        "attributes": _attrs(tag),
                        "root_id": root_id, "block_id": block_id,
                        "source_path": _path(tag), "translated_attributes": []})
    return anchors


def _mark_owned_anchor_attributes(soup: BeautifulSoup, anchors: list[dict[str, object]]) -> None:
    """Record only source attributes selected by the existing extraction owner."""
    targets = _attribute_targets(soup)
    anonymous = iter(tag for tag in soup.find_all("a") if not tag.has_attr("id"))
    for anchor in anchors:
        block_id = anchor["block_id"]
        if anchor["id"] is not None:
            tag = soup.find(id=anchor["id"])
        elif anchor["tag"] == "a":
            tag = next(anonymous, None)
        else:
            continue
        if tag is None or (block_id is not None and tag.find_parent(
                attrs={"data-wt-preformatted-block": block_id}) is None):
            _fail("projected anchor ownership changed")
        anchor["translated_attributes"] = list(targets.get(id(tag), ()))


def _constraint_evidence(analysis: PreformattedAnalysis, review: ReviewedBlocks,
                         projected: BeautifulSoup) -> list[dict[str, object]]:
    block_by_line = {line_id: block.id for block in review.blocks for line_id in block.line_ids}
    retained_tags = [tag for tag in projected.find_all("pre")
                     if tag.find_parent(attrs={"data-wt-preformatted-root": True}) is None
                     and not tag.has_attr("data-wt-preformatted-block")]
    retained_ordinal = 0
    result = []
    for item in analysis.constraints:
        owner_ids = {block_by_line[line_id] for line_id in item.line_ids}
        if len(owner_ids) > 1:
            _fail(f"{item.id}: explicit constraint crosses reviewed blocks")
        owner = next(iter(owner_ids), None)
        if owner is None:
            if item.path.split("/")[-1].split("[")[0] != "pre":
                _fail(f"{item.id}: inline constraint has no reviewed owner")
            retained_ordinal += 1
            if retained_ordinal > len(retained_tags):
                _fail(f"{item.id}: retained constraint disappeared during projection")
        result.append({"id": item.id, "path": item.path,
                       "attributes": item.to_dict()["attributes"], "text": item.text,
                       "sha256": _digest(item.text), "owner_block_id": owner,
                       "retained_pre_ordinal": retained_ordinal if owner is None else None,
                       "projected_path": _path(retained_tags[retained_ordinal - 1]) if owner is None else None})
    if retained_ordinal != len(retained_tags):
        _fail("retained constraint count differs from projected DOM")
    return result


def _verify_input(source_html: str, analysis: PreformattedAnalysis,
                  review: ReviewedBlocks) -> None:
    if not isinstance(analysis, PreformattedAnalysis) or not isinstance(review, ReviewedBlocks):
        _fail("analysis and review records are required")
    actual = analyze_preformatted(source_html)
    if actual != analysis:
        _fail("analysis/source identity mismatch")
    validate_review(analysis, build_classification_packages(analysis), review.to_dict())


def project_preformatted(source_html: str, analysis: PreformattedAnalysis,
                         review: ReviewedBlocks) -> ProjectionArtifact:
    """Project only reviewed blocks, retaining source DOM/attributes and exact literals."""
    _verify_input(source_html, analysis, review)
    soup = BeautifulSoup(source_html, "html.parser")
    if soup.select_one("[data-wt-segment]") is not None:
        _fail("raw source uses reserved extraction marker")
    offsets, _ = _text_nodes(soup)
    root_tags = {root.id: next((tag for tag in soup.find_all("pre") if _path(tag) == root.path), None)
                 for root in analysis.roots}
    if any(tag is None for tag in root_tags.values()):
        _fail("analysis root DOM path mismatch")
    root_by_object = {id(tag): key for key, tag in root_tags.items() if tag is not None}
    css_bytes = files("web_translator").joinpath("web_assets", "preformatted-flow.css").read_bytes()
    css_hash = _digest(css_bytes)
    css_path = f"assets/wt-preformatted-{css_hash[:16]}.css"
    lines_by_id = {line.id: line for line in analysis.lines}
    block_ranges: dict[str, list[tuple[str, int, int]]] = {root.id: [] for root in analysis.roots}
    for block in review.blocks:
        start, end, _ = _block_offsets(block, lines_by_id)
        block_ranges[block.pre_id].append((block.id, start, end))
    original_anchors = _source_anchors(soup, root_by_object, offsets, block_ranges)
    evidence_blocks = []
    opaque_spans = []
    preserved_reasons: dict[str, int] = {}
    for root in analysis.roots:
        pre = root_tags[root.id]
        assert pre is not None
        wrapper = soup.new_tag("div")
        for key, value in pre.attrs.items():
            wrapper[key] = copy.deepcopy(value)
        wrapper["data-wt-preformatted-root"] = root.id
        for block in (item for item in review.blocks if item.pre_id == root.id):
            start, end, expected_text = _block_offsets(block, lines_by_id)
            if not expected_text:
                start = end = root.text_start
            if block.role == "heading":
                tag_name = f"h{block.metadata['level']}"
            elif block.role == "prose":
                tag_name = "p"
            elif block.role == "list-item":
                tag_name = "div"
            elif block.role == "caption":
                tag_name = "figcaption"
            elif block.role in _PRESERVED:
                tag_name = "pre"
                preserved_reasons[block.role] = preserved_reasons.get(block.role, 0) + 1
            else:
                _fail(f"{block.id}: unresolved role")
            element = soup.new_tag(tag_name)
            element["data-wt-preformatted-block"] = block.id
            if block.role in _PRESERVED:
                element["data-wt-preformatted-literal"] = block.id
            if block.role == "list-item":
                element["role"] = "listitem"
                element["data-wt-preformatted-depth"] = str(block.metadata["depth"])
                element["style"] = f"--wt-list-depth: {block.metadata['depth']}"
            for child in _clone_range(pre, offsets, start, end, block.id):
                element.append(child)
            if element.get_text() != expected_text:
                _fail(f"{block.id}: source line/DOM text mismatch")
            intervals = []
            for span in block.literal_spans:
                first, last = _span_interval(span, block, lines_by_id)
                intervals.append((first, last, span["kind"], span["source_sha256"]))
            if block.role == "list-item":
                marker = block.metadata["marker_span"]
                first_line = block.line_ids[0]
                # Keep source indentation in the same opaque text node: both
                # html.parser and lxml collapse a whitespace-only sibling to
                # one space when it sits before a <code> marker envelope.
                start_marker = 0
                original_marker_start = int(marker["start"])
                end_marker = int(marker["end"])
                marker_text = lines_by_id[first_line].text[start_marker:end_marker]
                item = (start_marker, end_marker, "marker", _digest(marker_text))
                intervals = [x for x in intervals if not (
                    x[0] == original_marker_start and x[1] == end_marker and x[2] == "marker")]
                intervals.append(item)
            ordered = sorted(intervals, reverse=True)
            block_spans = []
            for index, (first, last, kind, expected_hash) in enumerate(ordered):
                if first < 0 or last > len(expected_text) or first >= last:
                    _fail(f"{block.id}: opaque span interval is invalid")
                if index and last > ordered[index - 1][0]:
                    _fail(f"{block.id}: overlapping opaque spans")
                selected = _wrap_opaque(soup, element, first, last, kind, block.id)
                if _digest(selected) != expected_hash:
                    _fail(f"{block.id}: opaque span hash mismatch")
                block_spans.append({"block_id": block.id, "kind": kind,
                                    "text": selected, "sha256": expected_hash})
            opaque_spans.extend(reversed(block_spans))
            wrapper.append(element)
            evidence_blocks.append({"id": block.id, "pre_id": root.id, "role": block.role,
                                    "line_ids": list(block.line_ids), "text_sha256": _digest(expected_text),
                                    "literal_text": expected_text if block.role in _PRESERVED else None})
        for caption in (item for item in review.blocks if item.pre_id == root.id
                        and item.role == "caption" and item.metadata):
            target_id = caption.metadata["adjacent_block_id"]
            target = wrapper.find(attrs={"data-wt-preformatted-block": target_id})
            caption_tag = wrapper.find(attrs={"data-wt-preformatted-block": caption.id})
            if target is None or caption_tag is None or target.parent is not wrapper or caption_tag.parent is not wrapper:
                _fail(f"{caption.id}: unsafe caption/figure association")
            first, second = sorted((target, caption_tag), key=lambda item: wrapper.contents.index(item))
            if wrapper.contents.index(second) != wrapper.contents.index(first) + 1:
                _fail(f"{caption.id}: nonadjacent figure association")
            figure = soup.new_tag("figure")
            figure["data-wt-preformatted-figure"] = caption.id
            first.insert_before(figure)
            figure.append(first.extract())
            figure.append(second.extract())
        pre.replace_with(wrapper)
    link = soup.new_tag("link", rel="stylesheet", href=css_path)
    if soup.head is not None:
        soup.head.append(link)
    elif soup.html is not None:
        head = soup.new_tag("head")
        head.append(link)
        soup.html.insert(0, head)
    else:
        soup.insert(0, link)
    _mark_owned_anchor_attributes(soup, original_anchors)
    # Numeric CR entities survive both consumers' newline normalization.
    # Scope them to reviewed roots and retained explicit-code <pre> text.
    retained_count = sum(not item.line_ids and item.path.split("/")[-1].split("[")[0] == "pre"
                         for item in analysis.constraints)
    html = _encode_scoped_cr(str(soup), retained_count)
    reparsed = BeautifulSoup(html, "html.parser")
    # html.parser serialization may insert a document-level newline after a
    # doctype, changing all-child paths without moving the retained element.
    constraints = _constraint_evidence(analysis, review, reparsed)
    review_by_id = {block.id: block for block in review.blocks}
    for item in evidence_blocks:
        rendered = reparsed.find(attrs={"data-wt-preformatted-block": item["id"]})
        if rendered is None:
            _fail(f"{item['id']}: projected block disappeared during serialization")
        if item["role"] in _PRESERVED:
            if _digest(rendered.get_text()) != item["text_sha256"]:
                _fail(f"{item['id']}: unsafe literal serialization changed source text")
        else:
            _verify_flow_reparse(review_by_id[item["id"]], lines_by_id, rendered.get_text())
    evidence = {"schema_version": SCHEMA_VERSION, "source_sha256": analysis.source_sha256,
                "review_sha256": canonical_sha256(review.to_dict()),
                "blocks": evidence_blocks, "anchors": original_anchors,
                "opaque_spans": opaque_spans,
                "constraints": constraints}
    summary = NormalizationSummary.from_dict({
        "schema_version": SCHEMA_VERSION, "policy": NORMALIZATION_POLICY,
        "source_sha256": analysis.source_sha256,
        "review_sha256": canonical_sha256(review.to_dict()),
        "projection_sha256": _digest(html),
        "translated_blocks": sum(block.role in _FLOW for block in review.blocks),
        "preserved_blocks": sum(preserved_reasons.values()), "unknown_blocks": 0,
        "preserved_reasons": preserved_reasons,
        "generated_assets": [{"path": css_path, "sha256": css_hash}],
    })
    artifact = ProjectionArtifact(html, css_bytes, css_path, evidence, summary)
    verify_projected_output(artifact, html)
    return artifact


def verify_projection(source_html: str, analysis: PreformattedAnalysis,
                      review: ReviewedBlocks, artifact: ProjectionArtifact) -> None:
    """Reconstruct and compare every derived byte and mapping against held inputs."""
    if not isinstance(artifact, ProjectionArtifact):
        _fail("projection artifact record is required")
    expected = project_preformatted(source_html, analysis, review)
    if artifact.to_dict() != expected.to_dict():
        _fail("projection artifact/mapping differs from deterministic source-derived projection")


def _markup_end(html: str, start: int) -> int:
    quote = None
    for index in range(start + 1, len(html)):
        char = html[index]
        if quote is not None:
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == ">":
            return index + 1
    _fail("marked projection contains unterminated markup")


def _encode_scoped_cr(html: str, expected_retained_pre: int) -> str:
    """Encode only source-bound text tokens, never markup or raw-text bodies."""
    before = BeautifulSoup(html, "html.parser")
    output: list[str] = []
    stack: list[tuple[str, bool]] = []
    retained_pre = 0
    position = 0
    while position < len(html):
        if stack and stack[-1][0] in {"script", "style"}:
            tag_name = stack[-1][0]
            close = re.search(rf"</\s*{tag_name}\b", html[position:], re.IGNORECASE)
            if close is None:
                _fail("projection has unterminated raw-text element")
            end = position + close.start()
            raw = html[position:end]
            if stack[-1][1] and "\r" in raw:
                _fail("source-bound raw-text CR cannot use safe entity transport")
            output.append(raw)
            position = end
        if position >= len(html):
            break
        if html[position] != "<":
            end = html.find("<", position)
            if end < 0:
                end = len(html)
            raw = html[position:end]
            output.append(raw.replace("\r", "&#13;") if stack and stack[-1][1] else raw)
            position = end
            continue
        if html.startswith("<!--", position):
            end = html.find("-->", position + 4)
            if end < 0:
                _fail("projection has unterminated comment")
            end += 3
            output.append(html[position:end])
            position = end
            continue
        end = _markup_end(html, position)
        markup = html[position:end]
        output.append(markup)
        match = _TAG_NAME.match(markup)
        if match is not None:
            closing, name = match.group(1), match.group(2).lower()
            if closing:
                for index in range(len(stack) - 1, -1, -1):
                    if stack[index][0] == name:
                        del stack[index:]
                        break
            elif name not in _VOID and not markup.rstrip().endswith("/>"):
                parsed = BeautifulSoup(markup, "html.parser").find(name)
                generated = parsed is not None and parsed.has_attr("data-wt-preformatted-root")
                retained = name == "pre" and not (stack and stack[-1][1]) and (
                    parsed is None or not parsed.has_attr("data-wt-preformatted-block"))
                if retained:
                    retained_pre += 1
                stack.append((name, (stack[-1][1] if stack else False) or generated or retained))
        position = end
    if retained_pre != expected_retained_pre:
        _fail("retained explicit constraint mapping changed")
    transported = "".join(output)
    after = BeautifulSoup(transported, "html.parser")
    if str(before) != str(after):
        _fail("CR transport changed decoded DOM, attributes or markers")
    return transported


def encode_projection_transport(marked_html: str, artifact: ProjectionArtifact) -> str:
    """Preserve reviewed and retained literal CR after extraction, before publication."""
    if not isinstance(marked_html, str) or not isinstance(artifact, ProjectionArtifact):
        _fail("marked HTML and projection artifact are required")
    before = BeautifulSoup(marked_html, "html.parser")
    if [tag.get("data-wt-preformatted-block") for tag in before.select("[data-wt-preformatted-block]")] != [
            item["id"] for item in artifact.evidence["blocks"]]:
        _fail("marked projection block mapping differs from artifact")
    return _encode_scoped_cr(marked_html, sum(item["owner_block_id"] is None
                                             for item in artifact.evidence["constraints"]))


def verify_projected_output(artifact: ProjectionArtifact, output_html: str,
                            *, segments: list[Segment] | None = None) -> None:
    """Check immutable block, anchor and literal identities after downstream assembly."""
    if not isinstance(artifact, ProjectionArtifact) or not isinstance(output_html, str):
        _fail("projection artifact and output HTML are required")
    evidence = artifact.to_dict()["evidence"]
    if (artifact.summary.projection_sha256 != _digest(artifact.unmarked_html)
            or artifact.summary.generated_assets[0]["sha256"] != _digest(artifact.css_bytes)):
        _fail("projection artifact digest mismatch")
    soup = BeautifulSoup(output_html, "html.parser")
    markers = soup.select("[data-wt-segment]")
    if segments is None:
        if markers:
            _fail("unmarked or final projection contains extraction markers")
    else:
        if [tag.get("data-wt-segment") for tag in markers] != [segment.id for segment in segments]:
            _fail("extraction marker manifest order changed")
        # Reuse the extractor's own target selection on the held, unmarked
        # projection. The manifest names markers; source-derived targets own them.
        source = BeautifulSoup(artifact.unmarked_html, "lxml")
        source_tags = source.find_all(True)
        names = _attribute_targets(source)
        content_owners = _content_owners(source, set(names))
        target_ids = content_owners | set(names)
        expected_positions = []
        for index, tag in enumerate(source_tags):
            if id(tag) not in target_ids:
                continue
            fragment = _fragment_without_owned_descendants(tag, content_owners)
            protected_fragment, _ = protect_fragment(fragment)
            if (id(tag) in content_owners and _has_translatable_text(protected_fragment)) or names.get(id(tag)):
                expected_positions.append(index)
        marked_tags = BeautifulSoup(output_html, "lxml").find_all(True)
        if len(marked_tags) != len(source_tags) or len(segments) != len(expected_positions):
            _fail("extraction marker target count differs from source projection")
        expected_by_position = {position: (ordinal, segment)
                                for ordinal, (position, segment) in enumerate(zip(
                                    expected_positions, segments, strict=True), 1)}
        if len({segment.id for segment in segments}) != len(segments):
            _fail("extraction segment IDs duplicated")
        for position, (original, observed) in enumerate(zip(source_tags, marked_tags, strict=True)):
            owned = expected_by_position.get(position)
            segment = owned[1] if owned is not None else None
            expected_id = segment.id if segment is not None else None
            if (observed.name != original.name or observed.get("id") != original.get("id")
                    or observed.get("data-wt-segment") != expected_id):
                _fail("extraction marker identity or ownership changed")
            if segment is not None and (not segment.target or segment.id != f"seg-{owned[0]:06d}"
                                        or segment.locator != f"[data-wt-segment='{segment.id}']"):
                _fail("extraction segment manifest identity changed")
    blocks = list(evidence["blocks"])
    found = soup.select("[data-wt-preformatted-block]")
    if [tag.get("data-wt-preformatted-block") for tag in found] != [x["id"] for x in blocks]:
        _fail("projected block ID mapping changed or duplicated")
    for item, tag in zip(blocks, found, strict=True):
        root = tag.find_parent(attrs={"data-wt-preformatted-root": item["pre_id"]})
        if root is None:
            _fail(f"{item['id']}: projected block root mapping changed")
        if item["literal_text"] is not None and tag.get_text() != item["literal_text"]:
            _fail(f"{item['id']}: literal island text changed")
    actual_spans = []
    for tag in soup.find_all(True):
        if tag.has_attr("data-wt-preformatted-block"):
            continue
        kinds = [kind for kind in ("literal", "url", "marker")
                 if tag.has_attr(f"data-wt-preformatted-{kind}")]
        if not kinds:
            continue
        if len(kinds) != 1 or tag.name != "code":
            _fail("opaque span tag or kind changed")
        kind = kinds[0]
        block_id = tag[f"data-wt-preformatted-{kind}"]
        owner = tag.find_parent(attrs={"data-wt-preformatted-block": block_id})
        if owner is None:
            _fail(f"{block_id}: opaque {kind} ownership changed")
        actual_spans.append((block_id, kind, tag.get_text()))
    if actual_spans != [(item["block_id"], item["kind"], item["text"])
                        for item in evidence["opaque_spans"]]:
        _fail("opaque span mapping, text or source order changed")
    ids = [str(tag["id"]) for tag in soup.select("[id]")]
    if len(ids) != len(set(ids)):
        _fail("original anchor or ID duplicated")
    for anchor in evidence["anchors"]:
        if anchor["id"] is None:
            continue
        matches = soup.find_all(id=anchor["id"])
        if len(matches) != 1:
            _fail(f"original anchor ID missing or duplicated: {anchor['id']}")
        tag = matches[0]
        observed_attrs = _attrs(tag)
        if segments is not None:
            observed_attrs.pop("data-wt-segment", None)
        if tag.get("data-wt-preformatted-root") == anchor["root_id"]:
            observed_attrs.pop("data-wt-preformatted-root", None)
        protected = set(anchor["attributes"])
        if segments is None:
            protected -= set(anchor["translated_attributes"])
        if (set(observed_attrs) != set(anchor["attributes"])
                or any(observed_attrs[name] != anchor["attributes"][name] for name in protected)):
            _fail(f"original anchor attributes/href changed: {anchor['id']}")
        if anchor["root_id"] is not None:
            root = tag if tag.get("data-wt-preformatted-root") == anchor["root_id"] else tag.find_parent(
                attrs={"data-wt-preformatted-root": anchor["root_id"]})
            if root is None:
                _fail(f"original anchor ownership moved: {anchor['id']}")
        if anchor["block_id"] is not None and tag.find_parent(
                attrs={"data-wt-preformatted-block": anchor["block_id"]}) is None:
            _fail(f"original anchor block ownership moved: {anchor['id']}")
    output_positions = {tag["id"]: index for index, tag in enumerate(soup.find_all(True))
                        if tag.has_attr("id")}
    anonymous_expected = [item for item in evidence["anchors"]
                          if item["id"] is None and item["tag"] == "a"]
    anonymous_actual = [tag for tag in soup.find_all("a") if not tag.has_attr("id")
                        and tag.find_parent(attrs={"data-wt-attribution": "source"}) is None]
    if len(anonymous_actual) != len(anonymous_expected):
        _fail("original anonymous anchor count changed")
    anonymous_positions = {}
    for ordinal, (item, tag) in enumerate(zip(anonymous_expected, anonymous_actual, strict=True)):
        observed = _attrs(tag)
        if segments is not None:
            observed.pop("data-wt-segment", None)
        protected = set(item["attributes"])
        if segments is None:
            protected -= set(item["translated_attributes"])
        if (set(observed) != set(item["attributes"])
                or any(observed[name] != item["attributes"][name] for name in protected)):
            _fail("original anonymous anchor attributes/href changed")
        if item["root_id"] is not None and tag.find_parent(
                attrs={"data-wt-preformatted-root": item["root_id"]}) is None:
            _fail("original anonymous anchor root ownership moved")
        if item["block_id"] is not None and tag.find_parent(
                attrs={"data-wt-preformatted-block": item["block_id"]}) is None:
            _fail("original anonymous anchor block ownership moved")
        anonymous_positions[ordinal] = next(index for index, element in enumerate(soup.find_all(True))
                                           if element is tag)
    anonymous_cursor = iter(anonymous_positions.values())
    source_positions = [output_positions[item["id"]] if item["id"] is not None else next(anonymous_cursor)
                        for item in evidence["anchors"]]
    if source_positions != sorted(source_positions):
        _fail("original anchor/ID source order changed")
    retained = [item for item in evidence["constraints"] if item["owner_block_id"] is None]
    actual_retained = [tag for tag in soup.find_all("pre")
                       if tag.find_parent(attrs={"data-wt-preformatted-root": True}) is None
                       and not tag.has_attr("data-wt-preformatted-block")]
    # Existing extract/assemble consumers parse with lxml before serializing.
    # Derive their exact all-child path from the held projection, never from
    # the translated output under verification.
    consumer_soup = BeautifulSoup(str(BeautifulSoup(artifact.unmarked_html, "lxml")), "html.parser")
    consumer_retained = [tag for tag in consumer_soup.find_all("pre")
                         if tag.find_parent(attrs={"data-wt-preformatted-root": True}) is None
                         and not tag.has_attr("data-wt-preformatted-block")]
    if len(actual_retained) != len(retained):
        _fail("retained explicit source constraint count changed")
    if len(consumer_retained) != len(retained):
        _fail("held projection consumer constraint mapping changed")
    for ordinal, (item, tag) in enumerate(zip(retained, actual_retained, strict=True), 1):
        expected_path = (item["projected_path"] if output_html == artifact.unmarked_html
                         else _path(consumer_retained[ordinal - 1]))
        if (item["retained_pre_ordinal"] != ordinal or _path(tag) != expected_path
                or _attrs(tag) != item["attributes"]
                or tag.get_text() != item["text"]):
            _fail("retained explicit source constraint identity or order changed")
    used: set[int] = set()
    last_position: dict[str, int] = {}
    positions = {id(tag): index for index, tag in enumerate(soup.find_all(True))}
    for item in evidence["constraints"]:
        block_id = item["owner_block_id"]
        if block_id is None:
            continue
        block_tag = soup.find(attrs={"data-wt-preformatted-block": block_id})
        source_tag = item["path"].split("/")[-1].split("[")[0]
        matches = [tag for tag in block_tag.find_all(source_tag)
                   if id(tag) not in used and _attrs(tag) == item["attributes"]
                   and tag.get_text() == item["text"]
                   and positions[id(tag)] > last_position.get(block_id, -1)]
        if not matches:
            _fail("owned explicit source literal constraint changed or duplicated")
        selected = matches[0]
        used.add(id(selected))
        last_position[block_id] = positions[id(selected)]
