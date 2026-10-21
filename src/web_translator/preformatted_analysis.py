"""Pure DOM analysis, bounded classification packages and strict review gate."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from collections.abc import Mapping

from bs4 import (
    BeautifulSoup, Comment, Declaration, Doctype, NavigableString,
    ProcessingInstruction, Tag,
)

from web_translator.preformatted_contract import (
    RESERVED,
    SCHEMA_VERSION,
    ClassificationPackage,
    PreConstraint,
    PreLine,
    PreRoot,
    PreformattedAnalysis,
    PreformattedContractError,
    ReviewedBlocks,
    canonical_loads,
    canonical_sha256,
)


_NEWLINE = re.compile(r"\r\n|\r|\n")
_MARKER = re.compile(r"(?:[-*+•]|[0-9]+[.)]|[A-Za-z][.)])\Z")
_EXCLUDED = {"script", "style", "noscript", "svg", "math"}
_MAX_CHARS = 12000


def _path(node: Tag | NavigableString) -> str:
    parts: list[str] = []
    current: Tag | NavigableString | None = node
    while current is not None and not isinstance(current, BeautifulSoup):
        parent = current.parent
        if parent is None:
            break
        siblings = list(parent.children)
        index = next(i for i, child in enumerate(siblings) if child is current)
        name = current.name if isinstance(current, Tag) else "#text"
        parts.append(f"{name}[{index}]")
        current = parent
    return "/" + "/".join(reversed(parts))


def _text_nodes(soup: BeautifulSoup) -> tuple[dict[int, tuple[int, int, str]], str]:
    offsets: dict[int, tuple[int, int, str]] = {}
    stream: list[str] = []
    position = 0
    for node in soup.descendants:
        if not isinstance(node, NavigableString) or isinstance(
            node, (Comment, Declaration, Doctype, ProcessingInstruction)
        ):
            continue
        value = str(node)
        offsets[id(node)] = (position, position + len(value), _path(node))
        stream.append(value)
        position += len(value)
    return offsets, "".join(stream)


def _range(tag: Tag, offsets: dict[int, tuple[int, int, str]]) -> tuple[int, int, str]:
    nodes = [node for node in tag.descendants if id(node) in offsets]
    if nodes:
        start = offsets[id(nodes[0])][0]
        end = offsets[id(nodes[-1])][1]
    else:
        previous = next((node for node in tag.previous_elements if id(node) in offsets), None)
        start = end = offsets[id(previous)][1] if previous is not None else 0
    return start, end, "".join(str(node) for node in nodes)


def _has_language(tag: Tag) -> bool:
    classes = tag.get("class", [])
    return (
        any(str(c).lower().startswith(("language-", "lang-")) for c in classes)
        or bool(tag.get("data-language"))
    )


def _explicit_code(pre: Tag) -> bool:
    if _has_language(pre):
        return True
    direct_codes = [child for child in pre.children if isinstance(child, Tag) and child.name == "code"]
    if len(direct_codes) != 1:
        return False
    return all(
        child is direct_codes[0] or (isinstance(child, NavigableString) and not str(child).strip())
        for child in pre.children
    )


def _excluded(tag: Tag) -> bool:
    return tag.name in _EXCLUDED or str(tag.get("translate", "")).strip().lower() == "no"


def _line_slices(chars: list[tuple[str, int, str, str | None]]) -> tuple[dict[str, object], ...]:
    slices: list[dict[str, object]] = []
    for _, offset, path, _ in chars:
        if slices and slices[-1]["path"] == path and slices[-1]["end"] == offset:
            slices[-1]["end"] = offset + 1
        else:
            slices.append({"path": path, "start": offset, "end": offset + 1})
    return tuple(slices)


def _new_lines(
    pre: Tag,
    pre_id: str,
    offsets: dict[int, tuple[int, int, str]],
    constraint_by_node: dict[int, str],
    first_line: int,
) -> list[PreLine]:
    chars: list[tuple[str, int, str, str | None]] = []
    for node in pre.descendants:
        if id(node) not in offsets:
            continue
        start, _, path = offsets[id(node)]
        constraint: str | None = None
        ancestor = node.parent
        while ancestor is not None and ancestor is not pre.parent:
            if id(ancestor) in constraint_by_node:
                constraint = constraint_by_node[id(ancestor)]
                break
            ancestor = ancestor.parent
        chars.extend((char, start + i, path, constraint) for i, char in enumerate(str(node)))
    value = "".join(char for char, _, _, _ in chars)
    lines: list[PreLine] = []
    cursor = 0
    for match in list(_NEWLINE.finditer(value)) + [None]:
        end = match.start() if match else len(value)
        body = chars[cursor:end]
        separator = chars[end:match.end()] if match else []
        ids = {item[3] for item in body + separator if item[3] is not None}
        lines.append(PreLine(
            id=f"line-{first_line + len(lines):06d}", pre_id=pre_id,
            ordinal=len(lines) + 1, text=value[cursor:end],
            separator=value[end:match.end()] if match else "",
            slices=_line_slices(body), separator_slices=_line_slices(separator),
            constraint_ids=tuple(sorted(ids)),
        ))
        cursor = match.end() if match else len(value)
    return lines


def analyze_preformatted(source_html: str, *, max_chars: int = 12000) -> PreformattedAnalysis:
    """Inventory all physical pre lines without classifying unmarked content."""
    if not isinstance(source_html, str):
        raise PreformattedContractError("source_html must be a string")
    try:
        source_bytes = source_html.encode("utf-8")
    except UnicodeError as exc:
        raise PreformattedContractError("invalid Unicode in source") from exc
    if type(max_chars) is not int or max_chars != _MAX_CHARS:
        raise PreformattedContractError("fixed package budget requires max_chars=12000")
    # html.parser preserves CR, LF and CRLF in NavigableString nodes; lxml
    # normalizes them before the physical-line contract can record them.
    soup = BeautifulSoup(source_html, "html.parser")
    for tag in soup.find_all(True):
        if any(name.lower() in RESERVED for name in tag.attrs):
            raise PreformattedContractError("source uses reserved preformatted attribute")
    for style in soup.find_all("style"):
        if any(name in style.get_text().lower() for name in RESERVED):
            raise PreformattedContractError("source CSS uses reserved preformatted selector")
    offsets, _ = _text_nodes(soup)
    roots: list[PreRoot] = []
    lines: list[PreLine] = []
    constraints: list[PreConstraint] = []
    for pre in soup.find_all("pre"):
        ancestor = pre
        excluded = False
        while isinstance(ancestor, Tag):
            if _excluded(ancestor):
                excluded = True
                break
            ancestor = ancestor.parent
        if excluded or _explicit_code(pre):
            start, end, value = _range(pre, offsets)
            constraints.append(PreConstraint(
                f"constraint-{len(constraints) + 1:06d}",
                "excluded" if excluded else "explicit-code", _path(pre), value,
                start, end, (), dict(pre.attrs),
            ))
            continue
        pre_id = f"pre-{len(roots) + 1:06d}"
        start, end, _ = _range(pre, offsets)
        inline_nodes = tuple(
            {"path": _path(tag), "tag": tag.name, "attributes": dict(tag.attrs)}
            for tag in pre.descendants if isinstance(tag, Tag)
        )
        roots.append(PreRoot(pre_id, _path(pre), dict(pre.attrs), start, end, inline_nodes))
        child_constraints: dict[int, str] = {}
        for tag in pre.descendants:
            if not isinstance(tag, Tag):
                continue
            kind = "excluded" if _excluded(tag) else (
                "explicit-code" if tag.name == "code" or _has_language(tag) else None
            )
            if kind is None:
                continue
            if any(id(parent) in child_constraints for parent in tag.parents if parent is not pre):
                continue
            c_start, c_end, value = _range(tag, offsets)
            constraint_id = f"constraint-{len(constraints) + 1:06d}"
            child_constraints[id(tag)] = constraint_id
            constraints.append(PreConstraint(constraint_id, kind, _path(tag), value,
                                             c_start, c_end, (), dict(tag.attrs)))
        lines.extend(_new_lines(pre, pre_id, offsets, child_constraints, len(lines) + 1))
    for index, constraint in enumerate(constraints):
        matching = tuple(line.id for line in lines if constraint.id in line.constraint_ids)
        constraints[index] = replace(constraint, line_ids=matching)
    provisional = PreformattedAnalysis(SCHEMA_VERSION, hashlib.sha256(source_bytes).hexdigest(),
                                       tuple(roots), tuple(lines), tuple(constraints), ())
    package_count = len(_package_targets(provisional))
    return replace(provisional,
                   package_ids=tuple(f"package-{i:06d}" for i in range(1, package_count + 1)))


def _package_targets(analysis: PreformattedAnalysis) -> list[tuple[PreLine, ...]]:
    groups: list[tuple[PreLine, ...]] = []
    current: list[PreLine] = []
    characters = 0
    for line in analysis.lines:
        size = len(line.text)
        if size > _MAX_CHARS:
            raise PreformattedContractError(f"physical line exceeds {_MAX_CHARS} character unit budget")
        if current and (len(current) == 200 or characters + size > _MAX_CHARS):
            groups.append(tuple(current))
            current = []
            characters = 0
        current.append(line)
        characters += size
    if current:
        groups.append(tuple(current))
    return groups


def _excerpt(line: PreLine) -> dict[str, object]:
    return {"id": line.id, "text": line.text[:256], "excerpt": len(line.text) > 256}


def build_classification_packages(
    analysis: PreformattedAnalysis,
) -> tuple[ClassificationPackage, ...]:
    """Partition every line once; neighboring excerpts are read-only context."""
    if not isinstance(analysis, PreformattedAnalysis):
        raise PreformattedContractError("analysis record is required")
    groups = _package_targets(analysis)
    if len(groups) != len(analysis.package_ids):
        raise PreformattedContractError("analysis package id count is inconsistent")
    digest = canonical_sha256(analysis.to_dict())
    positions = {line.id: i for i, line in enumerate(analysis.lines)}
    result: list[ClassificationPackage] = []
    for package_id, group in zip(analysis.package_ids, groups, strict=True):
        first = positions[group[0].id]
        last = positions[group[-1].id]
        result.append(ClassificationPackage(
            SCHEMA_VERSION, package_id, digest, tuple(line.id for line in group),
            tuple(_excerpt(line) for line in analysis.lines[max(0, first - 2):first]),
            tuple(_excerpt(line) for line in analysis.lines[last + 1:last + 3]),
        ))
    return tuple(result)


def _span_text(span: dict[str, object], line_by_id: dict[str, PreLine], block_ids: tuple[str, ...]) -> str:
    if set(span) != {"kind", "start_line_id", "start_column", "end_line_id", "end_column", "source_sha256"}:
        raise PreformattedContractError("literal span fields are invalid")
    if span["kind"] not in {"literal", "url", "marker"}:
        raise PreformattedContractError("literal span kind is unknown")
    start_id = span["start_line_id"]
    end_id = span["end_line_id"]
    if start_id not in block_ids or end_id not in block_ids:
        raise PreformattedContractError("literal span has foreign line id")
    start_index = block_ids.index(start_id)
    end_index = block_ids.index(end_id)
    start = span["start_column"]
    end = span["end_column"]
    if (type(start) is not int or type(end) is not int or start < 0 or end < 0
            or start_index > end_index or start > len(line_by_id[start_id].text)
            or end > len(line_by_id[end_id].text)
            or (start_index == end_index and end <= start)):
        raise PreformattedContractError("literal span offsets are invalid")
    selected = block_ids[start_index:end_index + 1]
    value = "".join(
        (line_by_id[line_id].text[start:] if i == 0 else line_by_id[line_id].text)
        + (line_by_id[line_id].separator if i < len(selected) - 1 else "")
        for i, line_id in enumerate(selected[:-1])
    ) + line_by_id[end_id].text[(start if start_index == end_index else 0):end]
    if hashlib.sha256(value.encode("utf-8")).hexdigest() != span["source_sha256"]:
        raise PreformattedContractError("literal span source hash mismatch")
    return value


def _validate_metadata(block, line_by_id: dict[str, PreLine], blocks) -> None:
    metadata = block.metadata
    if block.role == "heading":
        if set(metadata) != {"level"} or type(metadata["level"]) is not int or not 1 <= metadata["level"] <= 6:
            raise PreformattedContractError("heading metadata level must be 1..6")
    elif block.role == "list-item":
        if set(metadata) != {"depth", "marker_span"} or type(metadata["depth"]) is not int or metadata["depth"] < 0:
            raise PreformattedContractError("list-item metadata is invalid")
        span = metadata["marker_span"]
        if not isinstance(span, Mapping) or set(span) != {"line_id", "start", "end"}:
            raise PreformattedContractError("list marker span is invalid")
        line_id = span["line_id"]
        start, end = span["start"], span["end"]
        if (line_id != block.line_ids[0] or type(start) is not int or type(end) is not int
                or start < 0 or end <= start or end > len(line_by_id[line_id].text)
                or line_by_id[line_id].text[:start].strip()
                or not _MARKER.fullmatch(line_by_id[line_id].text[start:end])
                or line_by_id[line_id].text[end:end + 1] not in {" ", "\t"}):
            raise PreformattedContractError("list marker must be source-bound, not invented")
    elif block.role == "caption":
        if metadata:
            if set(metadata) != {"adjacent_block_id"}:
                raise PreformattedContractError("caption metadata fields are invalid")
            adjacent = next((i for i, candidate in enumerate(blocks) if candidate.id == metadata["adjacent_block_id"]), None)
            here = blocks.index(block)
            if adjacent is None or abs(adjacent - here) != 1 or blocks[adjacent].role not in {"literal-diagram", "literal-table"}:
                raise PreformattedContractError("caption association must name an adjacent diagram/table block")
    elif metadata:
        raise PreformattedContractError("role-inapplicable metadata fields are invalid")


def _has_unconstrained_text(line: PreLine, constraints: dict[str, PreConstraint]) -> bool:
    """Inspect recorded ranges only; this does not classify the surrounding text."""
    ranges = [(constraints[key].text_start, constraints[key].text_end)
              for key in line.constraint_ids]
    column = 0
    for item in line.slices:
        for offset in range(item["start"], item["end"]):
            if not line.text[column].isspace() and not any(first <= offset < last for first, last in ranges):
                return True
            column += 1
    return False


def validate_review(
    analysis: PreformattedAnalysis,
    packages: tuple[ClassificationPackage, ...],
    payload: object,
) -> ReviewedBlocks:
    """Accept only a hash-bound, complete, ordered, source-evidenced partition."""
    if isinstance(payload, str):
        payload = canonical_loads(payload)
    review = ReviewedBlocks.from_dict(payload)
    expected_packages = build_classification_packages(analysis)
    if tuple(packages) != expected_packages:
        raise PreformattedContractError("package identity/hash mismatch")
    if (review.source_sha256 != analysis.source_sha256
            or review.analysis_sha256 != canonical_sha256(analysis.to_dict())
            or review.package_sha256 != {p.id: canonical_sha256(p.to_dict()) for p in packages}):
        raise PreformattedContractError("review source/analysis/package hash mismatch")
    if review.unresolved_required:
        raise PreformattedContractError("review has unresolved required findings")
    if [b.id for b in review.blocks] != [f"block-{i:06d}" for i in range(1, len(review.blocks) + 1)]:
        raise PreformattedContractError("review block id sequence is invalid")
    line_by_id = {line.id: line for line in analysis.lines}
    constraint_by_id = {constraint.id: constraint for constraint in analysis.constraints}
    actual = [line_id for block in review.blocks for line_id in block.line_ids]
    expected = [line.id for line in analysis.lines]
    if actual != expected:
        raise PreformattedContractError("review coverage must partition all lines in exact order")
    heading_level: int | None = None
    list_depth: int | None = None
    list_pre_id: str | None = None
    for block in review.blocks:
        if not block.line_ids or any(line_by_id[line_id].pre_id != block.pre_id for line_id in block.line_ids):
            raise PreformattedContractError("block coverage crosses pre root")
        if block.role == "unknown":
            raise PreformattedContractError("unknown block role is unresolved required")
        constrained = [line_by_id[line_id] for line_id in block.line_ids if line_by_id[line_id].constraint_ids]
        if constrained and block.role != "literal-code":
            # A whole inline <code> remains opaque to the shared extractor.
            # Standalone constrained lines are still mandatory literal code,
            # and no constraint may be divided between reviewed blocks.
            constraint_ids = {key for line in constrained for key in line.constraint_ids}
            for key in constraint_ids:
                constraint = constraint_by_id[key]
                if (block.role not in {"prose", "heading", "list-item", "caption"}
                        or constraint.path.rsplit("/", 1)[-1].split("[")[0] != "code"
                        or not set(constraint.line_ids).issubset(block.line_ids)
                        or not any(_has_unconstrained_text(line_by_id[line_id], constraint_by_id)
                                   for line_id in constraint.line_ids)):
                    raise PreformattedContractError("explicit code constraint cannot be reclassified or split")
        text = "".join(line_by_id[line_id].text + line_by_id[line_id].separator for line_id in block.line_ids)
        if sum(len(line_by_id[line_id].text) for line_id in block.line_ids) > _MAX_CHARS:
            raise PreformattedContractError(f"review block exceeds {_MAX_CHARS} character unit budget")
        if any(token in block.evidence.lower() for token in RESERVED):
            raise PreformattedContractError("review evidence collides with reserved marker")
        if block.evidence and block.evidence not in text:
            raise PreformattedContractError("review evidence must occur literally within its block")
        if not block.evidence and block.role != "blank":
            raise PreformattedContractError("nonblank block requires literal evidence")
        if block.role == "blank" and any(line_by_id[x].text.strip() for x in block.line_ids):
            raise PreformattedContractError("blank block contains content")
        _validate_metadata(block, line_by_id, review.blocks)
        if block.role == "list-item":
            depth = block.metadata["depth"]
            if list_pre_id != block.pre_id:
                list_depth = None
            if (list_depth is None and depth != 0
                    or list_depth is not None and depth > list_depth + 1):
                raise PreformattedContractError("unsupported list depth transition")
            list_depth = depth
            list_pre_id = block.pre_id
        elif block.role != "blank":
            list_depth = None
            list_pre_id = None
        if block.role == "heading":
            level = block.metadata["level"]
            if heading_level is not None and level > heading_level + 1:
                raise PreformattedContractError("impossible heading hierarchy")
            heading_level = level
        for span in block.literal_spans:
            _span_text(span, line_by_id, block.line_ids)
    return review
