"""Read-only exact-byte web semantic-review input binding.

The source selector owns every file and directory lease. This module extends
that same lease to the semantic inputs; no validated file is reopened by name.
Preparing this inventory is not a semantic approval.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path
import re
from types import MappingProxyType

from supertranslator.models import Segment, Translation, read_segments_stream
from supertranslator.preformatted_contract import canonical_bytes, canonical_loads
from supertranslator.preformatted_runtime import ProcessingSource, hold_processing_source
from supertranslator.translations import merge_translation_payloads
from supertranslator.zones import Zone


_POLICY = {"id": "english-technical-first-use-ko-gloss", "version": "1.0"}
_DOMAIN = "supertranslator:web-semantic-input:1"
_ZONE_FILE = re.compile(r"zone-[0-9]{3,}\.json\Z")
_ASSIGNMENT_FIELDS = {"context_after", "context_before", "document_summary", "glossary",
                      "schema_version", "targets", "zone_id"}


class WebReviewError(ValueError):
    """A web review input is missing, invalid, ambiguous, or changed."""


@dataclass(frozen=True, slots=True)
class WebSemanticReviewInput:
    semantic_input_sha256: str
    _files: tuple[tuple[str, int, str], ...]

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": "1.0", "semantic_input_sha256": self.semantic_input_sha256,
                "terminology_policy": dict(_POLICY),
                "files": [{"path": path, "byte_length": size, "sha256": digest}
                          for path, size, digest in self._files]}


@dataclass(frozen=True, slots=True)
class WebSemanticInputSnapshot:
    """Parsed values and exact payloads, valid only inside the source lease."""

    processing_source: ProcessingSource
    payloads: Mapping[str, bytes]
    capture: Mapping[str, object]
    segments: list[Segment]
    zones: list[Zone]
    translations: Mapping[str, Translation]
    glossary: Mapping[str, str]
    review_input: WebSemanticReviewInput

    def verify(self) -> None:
        try:
            self.processing_source.verify()
        except (ValueError, OSError) as error:
            raise WebReviewError(str(error)) from error


def _object(payload: bytes, label: str) -> dict:
    value = canonical_loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise WebReviewError(f"{label} must be an object")
    return value


def _string_map(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                          for k, v in value.items()):
        raise WebReviewError(f"{label} must map strings to strings")
    return dict(value)


def _child_set(held, directory: str, expected: list[str] | None = None) -> list[str]:
    names = held.names(directory)
    if expected is not None:
        missing, extra = sorted(set(expected) - set(names)), sorted(set(names) - set(expected))
        if extra:
            raise WebReviewError(f"unexpected {directory} entries: {', '.join(extra)}")
        if missing:
            raise WebReviewError(f"missing {directory} entries: {', '.join(missing)}")
    held.sets[directory] = names
    return names


def _validate_zone_sources(segments: list[Segment], zones: list[Zone]) -> None:
    ids = [segment.id for segment in segments]
    if len(ids) != len(set(ids)):
        raise WebReviewError("duplicate source segment IDs")
    by_id = {segment.id: segment for segment in segments}
    assigned = [sid for zone in zones for sid in zone.target_ids]
    if assigned != [segment.id for segment in segments if segment.target]:
        raise WebReviewError("zone target IDs must partition source targets in order")
    for zone in zones:
        if zone.attempt < 0:
            raise WebReviewError(f"negative zone attempt: {zone.id}")
        context = zone.context_before_ids + zone.context_after_ids
        if len(context) != len(set(context)) or set(context) & set(zone.target_ids):
            raise WebReviewError(f"duplicate or overlapping zone context: {zone.id}")
        if any(sid not in by_id for sid in context):
            raise WebReviewError(f"zone context references missing segments: {zone.id}")
        for sid in zone.target_ids:
            if tuple(zone.expected_tokens[sid]) != tuple(token.token for token in by_id[sid].protected):
                raise WebReviewError(f"zone protected tokens differ from source: {zone.id}")


def _validate_assignments(held, segments: list[Segment], zones: list[Zone]) -> None:
    from supertranslator.cli import _assignment_records
    by_id = {segment.id: segment for segment in segments}
    for zone in zones:
        name = f"assignments/{zone.id}.json"
        value = _object(held.read(name), name)
        if set(value) != _ASSIGNMENT_FIELDS or value["schema_version"] != "1.0" or value["zone_id"] != zone.id:
            raise WebReviewError(f"invalid assignment fields or zone ID: {zone.id}")
        summary = value["document_summary"]
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 4000:
            raise WebReviewError(f"invalid assignment document summary: {zone.id}")
        _string_map(value["glossary"], f"assignment glossary: {zone.id}")
        for key, ids in (("targets", zone.target_ids), ("context_before", zone.context_before_ids),
                         ("context_after", zone.context_after_ids)):
            if value[key] != _assignment_records(ids, by_id, zone.id):
                raise WebReviewError(f"assignment {key} differs from source/zone records: {zone.id}")


@contextmanager
def hold_web_semantic_inputs(
    run_dir: Path, *, phase: str = "assemble"
) -> Iterator[WebSemanticInputSnapshot]:
    """Hold source provenance and the exact validated semantic child inventories."""
    from supertranslator.cli import _capture_from_value, _zone_from_value
    try:
        with hold_processing_source(run_dir, phase=phase) as source:
            held = source._held
            # The source selector already loaded capture, raw/projected source,
            # assets, classification and normalization evidence as applicable.
            segment_bytes = held.read("segments.jsonl")
            for line in segment_bytes.decode("utf-8").splitlines():
                if line.strip():
                    canonical_loads(line)  # Reject duplicate keys before record parsing.
            segments = read_segments_stream(io.StringIO(segment_bytes.decode("utf-8")))
            glossary = _string_map(_object(held.read("glossary.json"), "glossary.json"), "glossary")
            zone_names = _child_set(held, "zones")
            invalid = [name for name in zone_names if _ZONE_FILE.fullmatch(name) is None]
            if invalid:
                raise WebReviewError(f"unexpected zones entries: {', '.join(invalid)}")
            zones = [_zone_from_value(_object(held.read(f"zones/{name}"), f"zones/{name}"),
                                      held.path / "zones" / name)
                     for name in zone_names]
            _validate_zone_sources(segments, zones)
            _child_set(held, "assignments", [f"{zone.id}.json" for zone in zones])
            _validate_assignments(held, segments, zones)
            names = _child_set(held, "translations", [f"{zone.id}.jsonl" for zone in zones])
            for name in names:
                held.read(f"translations/{name}")
            payloads = MappingProxyType({name: payload for name, (_, payload) in sorted(held.files.items())})
            capture = _capture_from_value(_object(payloads["capture.json"], "capture.json"),
                                          held.path / "capture.json", payloads=payloads)
            translations = merge_translation_payloads(segments, zones, payloads)
            files = tuple((name, len(payload), hashlib.sha256(payload).hexdigest())
                          for name, payload in payloads.items())
            file_records = [{"path": name, "byte_length": length, "sha256": digest}
                            for name, length, digest in files]
            digest = hashlib.sha256(canonical_bytes({"domain": _DOMAIN,
                "terminology_policy": _POLICY, "files": file_records})).hexdigest()
            snapshot = WebSemanticInputSnapshot(source, payloads, capture, segments, zones,
                                                translations, glossary, WebSemanticReviewInput(digest, files))
            snapshot.verify()
            yield snapshot
            snapshot.verify()
    except WebReviewError:
        raise
    except (ValueError, OSError, TypeError, KeyError) as error:
        raise WebReviewError(f"cannot hold web semantic inputs: {error}") from error
