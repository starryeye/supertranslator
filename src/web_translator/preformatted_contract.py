"""Strict, immutable wire records for preformatted web-source classification.

Offsets are Unicode codepoints in the html.parser DOM text stream. Paths count
all children (including text nodes), so they are not CSS/tag-only positions.
"""

from __future__ import annotations

import hashlib
import base64
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
NORMALIZATION_POLICY = "prose-reflow-literals-preserved"
ROLES = frozenset({
    "prose", "heading", "list-item", "caption", "literal-code",
    "literal-diagram", "literal-table", "literal-layout", "blank", "unknown",
})
RESERVED = (
    "data-wt-preformatted-root", "data-wt-preformatted-block",
    "data-wt-preformatted-literal", "data-wt-preformatted-url",
    "data-wt-preformatted-marker",
)
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"(?:pre|line|constraint|package|block)-[0-9]{6}\Z")
_PATH = re.compile(r"/(?:[A-Za-z][A-Za-z0-9:_-]*|#text)\[[0-9]+\](?:/(?:[A-Za-z][A-Za-z0-9:_-]*|#text)\[[0-9]+\])*$")


class PreformattedContractError(ValueError):
    """A preformatted producer/review record violates its contract."""


def _fail(message: str) -> None:
    raise PreformattedContractError(message)


def _json_safe(value: object) -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise PreformattedContractError("invalid Unicode") from exc
        return
    if isinstance(value, float):
        _fail("floating-point/NaN values are not permitted")
    if isinstance(value, (list, tuple)):
        for item in value:
            _json_safe(item)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail("JSON keys must be strings")
            _json_safe(key)
            _json_safe(item)
        return
    _fail("non-JSON value")


def canonical_bytes(value: object) -> bytes:
    _json_safe(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_loads(raw: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        _fail(f"invalid numeric constant: {value}")

    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (TypeError, json.JSONDecodeError) as exc:
        raise PreformattedContractError("invalid JSON") from exc
    _json_safe(result)
    return result


def _map(data: object, name: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(data, Mapping) or set(data) != keys:
        _fail(f"{name} fields must be exactly {sorted(keys)}")
    _json_safe(data)
    return data


def _str(value: object, name: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        _fail(f"{name} must be a string")
    _json_safe(value)
    return value


def _int(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _id(value: object, name: str, prefix: str) -> str:
    result = _str(value, name)
    if not _ID.fullmatch(result) or not result.startswith(prefix + "-"):
        _fail(f"{name} has invalid id")
    return result


def _hash(value: object, name: str) -> str:
    result = _str(value, name)
    if not _HASH.fullmatch(result):
        _fail(f"{name} must be a SHA256 hash")
    return result


def _path(value: object, name: str) -> str:
    result = _str(value, name)
    if not _PATH.fullmatch(result):
        _fail(f"{name} is an unsafe DOM path")
    return result


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        _fail(f"{name} must be a list")
    return list(value)


def _freeze_json(value: object) -> object:
    """Own nested JSON values so a frozen record cannot be mutated indirectly."""
    _json_safe(value)
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    """Export fresh, ordinary JSON containers rather than record internals."""
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _strings(value: object, name: str, prefix: str | None = None) -> tuple[str, ...]:
    items = _list(value, name)
    return tuple(_id(item, name, prefix) if prefix else _str(item, name) for item in items)


@dataclass(frozen=True, slots=True)
class PreRoot:
    id: str
    path: str
    attributes: dict[str, object]
    text_start: int
    text_end: int
    inline_nodes: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", _freeze_json(self.attributes))
        object.__setattr__(self, "inline_nodes", tuple(_freeze_json(x) for x in self.inline_nodes))

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "path": self.path, "attributes": _thaw_json(self.attributes),
                "text_start": self.text_start, "text_end": self.text_end,
                "inline_nodes": _thaw_json(self.inline_nodes)}

    @classmethod
    def from_dict(cls, data: object) -> PreRoot:
        d = _map(data, "root", {"id", "path", "attributes", "text_start", "text_end",
                                 "inline_nodes"})
        attrs = d["attributes"]
        if not isinstance(attrs, Mapping) or any(not isinstance(k, str) for k in attrs):
            _fail("root attributes must be a JSON object")
        start = _int(d["text_start"], "root.text_start")
        end = _int(d["text_end"], "root.text_end")
        if end < start:
            _fail("root offsets are reversed")
        inline_nodes = []
        for node in _list(d["inline_nodes"], "root.inline_nodes"):
            item = _map(node, "inline node", {"path", "tag", "attributes"})
            if not isinstance(item["attributes"], Mapping):
                _fail("inline node attributes must be an object")
            inline_nodes.append({"path": _path(item["path"], "inline node.path"),
                                 "tag": _str(item["tag"], "inline node.tag", nonempty=True),
                                 "attributes": dict(item["attributes"])})
        return cls(_id(d["id"], "root.id", "pre"), _path(d["path"], "root.path"),
                   dict(attrs), start, end, tuple(inline_nodes))


def _slice(item: object) -> dict[str, object]:
    d = _map(item, "source-node slice", {"path", "start", "end"})
    start = _int(d["start"], "slice.start")
    end = _int(d["end"], "slice.end")
    if end <= start:
        _fail("source-node slice must have positive length")
    return {"path": _path(d["path"], "slice.path"), "start": start, "end": end}


@dataclass(frozen=True, slots=True)
class PreLine:
    id: str
    pre_id: str
    ordinal: int
    text: str
    separator: str
    slices: tuple[dict[str, object], ...]
    separator_slices: tuple[dict[str, object], ...]
    constraint_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "slices", tuple(_freeze_json(x) for x in self.slices))
        object.__setattr__(self, "separator_slices", tuple(_freeze_json(x) for x in self.separator_slices))
        object.__setattr__(self, "constraint_ids", tuple(self.constraint_ids))

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "pre_id": self.pre_id, "ordinal": self.ordinal,
                "text": self.text, "separator": self.separator,
                "slices": _thaw_json(self.slices), "separator_slices": _thaw_json(self.separator_slices),
                "constraint_ids": list(self.constraint_ids)}

    @classmethod
    def from_dict(cls, data: object) -> PreLine:
        d = _map(data, "line", {"id", "pre_id", "ordinal", "text", "separator",
                                "slices", "separator_slices", "constraint_ids"})
        separator = _str(d["separator"], "line.separator")
        if separator not in {"", "\n", "\r", "\r\n"}:
            _fail("line separator must be exact physical newline")
        text = _str(d["text"], "line.text")
        if "\r" in text or "\n" in text:
            _fail("line text contains a physical separator")
        return cls(_id(d["id"], "line.id", "line"), _id(d["pre_id"], "line.pre_id", "pre"),
                   _int(d["ordinal"], "line.ordinal", minimum=1), text, separator,
                   tuple(_slice(x) for x in _list(d["slices"], "line.slices")),
                   tuple(_slice(x) for x in _list(d["separator_slices"], "line.separator_slices")),
                   _strings(d["constraint_ids"], "line.constraint_ids", "constraint"))


@dataclass(frozen=True, slots=True)
class PreConstraint:
    id: str
    kind: str
    path: str
    text: str
    text_start: int
    text_end: int
    line_ids: tuple[str, ...]
    attributes: dict[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_ids", tuple(self.line_ids))
        object.__setattr__(self, "attributes", _freeze_json(self.attributes))

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind, "path": self.path,
                "text": self.text, "text_start": self.text_start,
                "text_end": self.text_end, "line_ids": list(self.line_ids),
                "attributes": _thaw_json(self.attributes)}

    @classmethod
    def from_dict(cls, data: object) -> PreConstraint:
        d = _map(data, "constraint", {"id", "kind", "path", "text", "text_start",
                                      "text_end", "line_ids", "attributes"})
        kind = _str(d["kind"], "constraint.kind")
        if kind not in {"explicit-code", "excluded"}:
            _fail("constraint.kind is unknown")
        start = _int(d["text_start"], "constraint.text_start")
        end = _int(d["text_end"], "constraint.text_end")
        if end < start:
            _fail("constraint offsets are reversed")
        if not isinstance(d["attributes"], Mapping):
            _fail("constraint attributes must be an object")
        return cls(_id(d["id"], "constraint.id", "constraint"), kind,
                   _path(d["path"], "constraint.path"), _str(d["text"], "constraint.text"),
                   start, end, _strings(d["line_ids"], "constraint.line_ids", "line"),
                   dict(d["attributes"]))


@dataclass(frozen=True, slots=True)
class PreformattedAnalysis:
    schema_version: str
    source_sha256: str
    roots: tuple[PreRoot, ...]
    lines: tuple[PreLine, ...]
    constraints: tuple[PreConstraint, ...]
    package_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("roots", "lines", "constraints", "package_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "source_sha256": self.source_sha256,
                "roots": [x.to_dict() for x in self.roots],
                "lines": [x.to_dict() for x in self.lines],
                "constraints": [x.to_dict() for x in self.constraints],
                "package_ids": list(self.package_ids)}

    @classmethod
    def from_dict(cls, data: object) -> PreformattedAnalysis:
        d = _map(data, "analysis", {"schema_version", "source_sha256", "roots", "lines",
                                    "constraints", "package_ids"})
        if d["schema_version"] != SCHEMA_VERSION:
            _fail("analysis schema_version is unsupported")
        result = cls(SCHEMA_VERSION, _hash(d["source_sha256"], "analysis.source_sha256"),
                     tuple(PreRoot.from_dict(x) for x in _list(d["roots"], "analysis.roots")),
                     tuple(PreLine.from_dict(x) for x in _list(d["lines"], "analysis.lines")),
                     tuple(PreConstraint.from_dict(x) for x in _list(d["constraints"], "analysis.constraints")),
                     _strings(d["package_ids"], "analysis.package_ids", "package"))
        if [r.id for r in result.roots] != [f"pre-{i:06d}" for i in range(1, len(result.roots) + 1)]:
            _fail("analysis root ids are not ordered")
        if [line.id for line in result.lines] != [f"line-{i:06d}" for i in range(1, len(result.lines) + 1)]:
            _fail("analysis line ids are not ordered")
        if [c.id for c in result.constraints] != [f"constraint-{i:06d}" for i in range(1, len(result.constraints) + 1)]:
            _fail("analysis constraint ids are not ordered")
        if [p for p in result.package_ids] != [f"package-{i:06d}" for i in range(1, len(result.package_ids) + 1)]:
            _fail("analysis package ids are not ordered")
        roots = {r.id for r in result.roots}
        constraints = {c.id for c in result.constraints}
        for line in result.lines:
            if line.pre_id not in roots or any(c not in constraints for c in line.constraint_ids):
                _fail("line references unknown root or constraint")
        return result


def _context(value: object) -> dict[str, object]:
    d = _map(value, "package context", {"id", "text", "excerpt"})
    text = _str(d["text"], "context.text")
    if len(text) > 256 or type(d["excerpt"]) is not bool:
        _fail("package context excerpt is invalid")
    return {"id": _id(d["id"], "context.id", "line"), "text": text,
            "excerpt": d["excerpt"]}


@dataclass(frozen=True, slots=True)
class ClassificationPackage:
    schema_version: str
    id: str
    analysis_sha256: str
    target_lines: tuple[str, ...]
    context_before: tuple[dict[str, object], ...]
    context_after: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_lines", tuple(self.target_lines))
        object.__setattr__(self, "context_before", tuple(_freeze_json(x) for x in self.context_before))
        object.__setattr__(self, "context_after", tuple(_freeze_json(x) for x in self.context_after))

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "id": self.id,
                "analysis_sha256": self.analysis_sha256,
                "target_lines": list(self.target_lines),
                "context_before": _thaw_json(self.context_before),
                "context_after": _thaw_json(self.context_after)}

    @classmethod
    def from_dict(cls, data: object) -> ClassificationPackage:
        d = _map(data, "package", {"schema_version", "id", "analysis_sha256",
                                   "target_lines", "context_before", "context_after"})
        if d["schema_version"] != SCHEMA_VERSION:
            _fail("package schema_version is unsupported")
        targets = _strings(d["target_lines"], "package.target_lines", "line")
        before = tuple(_context(x) for x in _list(d["context_before"], "package.context_before"))
        after = tuple(_context(x) for x in _list(d["context_after"], "package.context_after"))
        if not targets or len(targets) > 200 or len(before) > 2 or len(after) > 2:
            _fail("package bounds are invalid")
        return cls(SCHEMA_VERSION, _id(d["id"], "package.id", "package"),
                   _hash(d["analysis_sha256"], "package.analysis_sha256"),
                   targets, before, after)


@dataclass(frozen=True, slots=True)
class ReviewedBlock:
    id: str
    pre_id: str
    line_ids: tuple[str, ...]
    role: str
    evidence: str
    metadata: dict[str, object]
    literal_spans: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_ids", tuple(self.line_ids))
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))
        object.__setattr__(self, "literal_spans", tuple(_freeze_json(x) for x in self.literal_spans))

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "pre_id": self.pre_id, "line_ids": list(self.line_ids),
                "role": self.role, "evidence": self.evidence, "metadata": _thaw_json(self.metadata),
                "literal_spans": _thaw_json(self.literal_spans)}

    @classmethod
    def from_dict(cls, data: object) -> ReviewedBlock:
        d = _map(data, "block", {"id", "pre_id", "line_ids", "role", "evidence",
                                 "metadata", "literal_spans"})
        role = _str(d["role"], "block.role")
        if role not in ROLES:
            _fail("block role is unknown")
        metadata = d["metadata"]
        if not isinstance(metadata, Mapping):
            _fail("block metadata must be an object")
        spans = tuple(_map(x, "literal span", {"kind", "start_line_id", "start_column",
                                                 "end_line_id", "end_column", "source_sha256"})
                      for x in _list(d["literal_spans"], "block.literal_spans"))
        return cls(_id(d["id"], "block.id", "block"), _id(d["pre_id"], "block.pre_id", "pre"),
                   _strings(d["line_ids"], "block.line_ids", "line"), role,
                   _str(d["evidence"], "block.evidence"), dict(metadata),
                   tuple(dict(x) for x in spans))


@dataclass(frozen=True, slots=True)
class ReviewedBlocks:
    schema_version: str
    source_sha256: str
    analysis_sha256: str
    package_sha256: dict[str, str]
    blocks: tuple[ReviewedBlock, ...]
    unresolved_required: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "package_sha256", _freeze_json(self.package_sha256))
        object.__setattr__(self, "blocks", tuple(self.blocks))
        object.__setattr__(self, "unresolved_required", tuple(self.unresolved_required))

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "source_sha256": self.source_sha256,
                "analysis_sha256": self.analysis_sha256,
                "package_sha256": _thaw_json(self.package_sha256),
                "blocks": [x.to_dict() for x in self.blocks],
                "unresolved_required": list(self.unresolved_required)}

    @classmethod
    def from_dict(cls, data: object) -> ReviewedBlocks:
        d = _map(data, "review", {"schema_version", "source_sha256", "analysis_sha256",
                                  "package_sha256", "blocks", "unresolved_required"})
        if d["schema_version"] != SCHEMA_VERSION:
            _fail("review schema_version is unsupported")
        hashes = d["package_sha256"]
        if not isinstance(hashes, Mapping):
            _fail("review package_sha256 must be an object")
        parsed_hashes = {_id(k, "review package id", "package"): _hash(v, "review package hash")
                         for k, v in hashes.items()}
        unresolved = _strings(d["unresolved_required"], "review.unresolved_required")
        if unresolved != tuple(sorted(set(unresolved))):
            _fail("review unresolved_required must be sorted and unique")
        return cls(SCHEMA_VERSION, _hash(d["source_sha256"], "review.source_sha256"),
                   _hash(d["analysis_sha256"], "review.analysis_sha256"), parsed_hashes,
                   tuple(ReviewedBlock.from_dict(x) for x in _list(d["blocks"], "review.blocks")),
                   unresolved)


@dataclass(frozen=True, slots=True)
class NormalizationSummary:
    schema_version: str
    policy: str
    source_sha256: str
    review_sha256: str
    projection_sha256: str
    translated_blocks: int
    preserved_blocks: int
    unknown_blocks: int
    preserved_reasons: dict[str, int]
    generated_assets: tuple[dict[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "preserved_reasons", _freeze_json(self.preserved_reasons))
        object.__setattr__(self, "generated_assets", tuple(_freeze_json(x) for x in self.generated_assets))

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "policy": self.policy,
                "source_sha256": self.source_sha256, "review_sha256": self.review_sha256,
                "projection_sha256": self.projection_sha256,
                "translated_blocks": self.translated_blocks,
                "preserved_blocks": self.preserved_blocks,
                "unknown_blocks": self.unknown_blocks,
                "preserved_reasons": _thaw_json(self.preserved_reasons),
                "generated_assets": _thaw_json(self.generated_assets)}

    @classmethod
    def from_dict(cls, data: object) -> NormalizationSummary:
        d = _map(data, "normalization summary", {"schema_version", "policy", "source_sha256",
            "review_sha256", "projection_sha256", "translated_blocks", "preserved_blocks",
            "unknown_blocks", "preserved_reasons", "generated_assets"})
        if d["schema_version"] != SCHEMA_VERSION or d["policy"] != NORMALIZATION_POLICY:
            _fail("normalization summary schema or policy is unsupported")
        reasons = d["preserved_reasons"]
        if not isinstance(reasons, Mapping) or any(k not in {"literal-code", "literal-diagram",
                "literal-table", "literal-layout", "blank"} for k in reasons):
            _fail("summary preserved_reasons is invalid")
        parsed_reasons = {k: _int(v, "summary preserved reason") for k, v in reasons.items()}
        assets = []
        for value in _list(d["generated_assets"], "summary.generated_assets"):
            item = _map(value, "generated asset", {"path", "sha256"})
            path = _str(item["path"], "generated asset.path", nonempty=True)
            if not re.fullmatch(r"assets/wt-preformatted-[0-9a-f]{16}\.css", path):
                _fail("generated asset path is invalid")
            assets.append({"path": path, "sha256": _hash(item["sha256"], "generated asset.sha256")})
        translated = _int(d["translated_blocks"], "summary.translated_blocks")
        preserved = _int(d["preserved_blocks"], "summary.preserved_blocks")
        unknown = _int(d["unknown_blocks"], "summary.unknown_blocks")
        if sum(parsed_reasons.values()) != preserved or unknown or len(assets) != 1:
            _fail("normalization summary counts/assets are inconsistent")
        return cls(SCHEMA_VERSION, NORMALIZATION_POLICY, _hash(d["source_sha256"], "summary.source_sha256"),
                   _hash(d["review_sha256"], "summary.review_sha256"),
                   _hash(d["projection_sha256"], "summary.projection_sha256"),
                   translated, preserved, unknown, parsed_reasons, tuple(assets))


@dataclass(frozen=True, slots=True)
class ProjectionArtifact:
    unmarked_html: str
    css_bytes: bytes
    css_path: str
    evidence: dict[str, object]
    summary: NormalizationSummary

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", _freeze_json(self.evidence))

    def to_dict(self) -> dict[str, object]:
        return {"unmarked_html": self.unmarked_html,
                "css_base64": base64.b64encode(self.css_bytes).decode("ascii"),
                "css_path": self.css_path, "evidence": _thaw_json(self.evidence),
                "summary": self.summary.to_dict()}

    @classmethod
    def from_dict(cls, data: object) -> ProjectionArtifact:
        d = _map(data, "projection artifact", {"unmarked_html", "css_base64", "css_path",
                                               "evidence", "summary"})
        encoded = _str(d["css_base64"], "artifact.css_base64")
        try:
            css = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise PreformattedContractError("artifact CSS base64 is invalid") from exc
        if base64.b64encode(css).decode("ascii") != encoded:
            _fail("artifact CSS base64 is not canonical")
        summary = NormalizationSummary.from_dict(d["summary"])
        path = _str(d["css_path"], "artifact.css_path")
        digest = hashlib.sha256(css).hexdigest()
        if (summary.generated_assets[0]["path"] != path
                or summary.generated_assets[0]["sha256"] != digest
                or path != f"assets/wt-preformatted-{digest[:16]}.css"):
            _fail("artifact CSS asset identity mismatch")
        html = _str(d["unmarked_html"], "artifact.unmarked_html")
        if hashlib.sha256(html.encode("utf-8")).hexdigest() != summary.projection_sha256:
            _fail("artifact projection SHA256 mismatch")
        evidence = d["evidence"]
        if not isinstance(evidence, Mapping):
            _fail("artifact evidence must be an object")
        return cls(html, css, path, dict(evidence), summary)
