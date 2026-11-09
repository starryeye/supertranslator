"""Strict validation and source-ordered merging of translator results."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
import io
import json
from pathlib import Path
import re
from typing import TextIO

from supertranslator.models import Segment, Translation
from supertranslator.zones import Zone
from supertranslator.preformatted_contract import canonical_loads


_TOKEN_PATTERN = re.compile(r"⟦WT:\d{6}⟧")
_ZONE_ID_PATTERN = re.compile(r"zone-[0-9]{3,}")


class TranslationContractError(ValueError):
    """A translator result violates its immutable zone assignment."""


def validate_zone_results(
    zone: Zone, records: Sequence[Translation]
) -> None:
    """Require an exact, string-only result for every assigned target."""
    assigned = _validated_string_ids(zone.target_ids, "zone target ID")
    if len(assigned) != len(set(assigned)):
        raise TranslationContractError("duplicate target ID in zone assignment")

    result_ids: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, Translation):
            raise TranslationContractError(
                f"translation record {index} must be a Translation"
            )
        _validate_string_fields(record, index)
        result_ids.append(record.segment_id)

    duplicate_ids = sorted(
        segment_id
        for segment_id, count in Counter(result_ids).items()
        if count > 1
    )
    if duplicate_ids:
        raise TranslationContractError(
            f"duplicate translation IDs: {', '.join(duplicate_ids)}"
        )

    assigned_set = set(assigned)
    unassigned = sorted(set(result_ids) - assigned_set)
    if unassigned:
        raise TranslationContractError(
            f"unassigned translation IDs: {', '.join(unassigned)}"
        )
    missing = [segment_id for segment_id in assigned if segment_id not in result_ids]
    if missing:
        raise TranslationContractError(
            f"missing translation IDs: {', '.join(missing)}"
        )

    for record in records:
        expected = Counter(zone.expected_tokens.get(record.segment_id, ()))
        actual = Counter(_TOKEN_PATTERN.findall(record.text))
        if actual != expected:
            raise TranslationContractError(
                f"protected-token multiset changed for {record.segment_id}"
            )


def merge_translations(
    segments: Sequence[Segment],
    zones: Sequence[Zone],
    result_dir: Path,
) -> dict[str, Translation]:
    """Load one JSONL file per zone and return targets in source order."""
    return _merge_translations(
        segments, zones,
        lambda zone: _read_zone_records(Path(result_dir) / f"{zone.id}.jsonl"),
    )


def merge_translation_payloads(
    segments: Sequence[Segment], zones: Sequence[Zone], payloads: Mapping[str, bytes]
) -> dict[str, Translation]:
    """Validate held exact zone bytes without reopening their filesystem names."""
    return _merge_translations(
        segments, zones,
        lambda zone: _parse_zone_records(
            io.StringIO(payloads[f"translations/{zone.id}.jsonl"].decode("utf-8")),
            f"{zone.id}.jsonl", strict=True,
        ),
    )


def _merge_translations(
    segments: Sequence[Segment], zones: Sequence[Zone],
    load_records: Callable[[Zone], list[Translation]],
) -> dict[str, Translation]:
    ordered_segments = list(segments)
    target_segments = [item for item in ordered_segments if item.target]
    target_ids = _validated_string_ids(
        [item.id for item in target_segments], "source target ID"
    )
    if len(target_ids) != len(set(target_ids)):
        raise TranslationContractError("duplicate source target ID")

    zone_ids = _validated_string_ids([zone.id for zone in zones], "zone ID")
    invalid_zone_ids = [
        zone_id for zone_id in zone_ids if _ZONE_ID_PATTERN.fullmatch(zone_id) is None
    ]
    if invalid_zone_ids:
        raise TranslationContractError(
            f"invalid zone ID: {', '.join(invalid_zone_ids)}"
        )
    if len(zone_ids) != len(set(zone_ids)):
        raise TranslationContractError("duplicate zone ID")

    assigned_ids = [segment_id for zone in zones for segment_id in zone.target_ids]
    if Counter(assigned_ids) != Counter(target_ids):
        raise TranslationContractError(
            "zone target IDs do not form an exact partition of source targets"
        )

    source_tokens = {
        item.id: tuple(token.token for token in item.protected)
        for item in target_segments
    }
    merged: dict[str, Translation] = {}
    for zone in zones:
        records = load_records(zone)
        validation_zone = replace(
            zone,
            expected_tokens={
                segment_id: source_tokens[segment_id]
                for segment_id in zone.target_ids
            },
        )
        validate_zone_results(validation_zone, records)
        for record in records:
            if record.segment_id in merged:
                raise TranslationContractError(
                    f"duplicate final translation ID: {record.segment_id}"
                )
            merged[record.segment_id] = record

    missing = [segment_id for segment_id in target_ids if segment_id not in merged]
    foreign = sorted(set(merged) - set(target_ids))
    if missing:
        raise TranslationContractError(
            f"missing final translation IDs: {', '.join(missing)}"
        )
    if foreign:
        raise TranslationContractError(
            f"unassigned final translation IDs: {', '.join(foreign)}"
        )
    return {segment_id: merged[segment_id] for segment_id in target_ids}


def _read_zone_records(path: Path) -> list[Translation]:
    if not path.is_file():
        raise TranslationContractError(f"missing zone result file: {path}")

    try:
        with path.open(encoding="utf-8") as stream:
            return _parse_zone_records(stream, path.name)
    except OSError as error:
        raise TranslationContractError(
            f"cannot read zone result file {path}: {error}"
        ) from error


def _parse_zone_records(stream: TextIO, label: str, *, strict: bool = False) -> list[Translation]:
    records: list[Translation] = []
    for line_number, line in enumerate(stream, start=1):
        if not line.strip():
            continue
        try:
            data = canonical_loads(line) if strict else json.loads(line)
        except ValueError as error:
            detail = str(error) if strict else "invalid JSON"
            raise TranslationContractError(f"{label} line {line_number}: {detail}") from error
        if not isinstance(data, Mapping):
            raise TranslationContractError(f"{label} line {line_number}: record must be an object")
        try:
            records.append(Translation.from_dict(data))
        except ValueError as error:
            raise TranslationContractError(f"{label} line {line_number}: {error}") from error
    return records


def _validated_string_ids(values: Sequence[object], context: str) -> list[str]:
    if any(not isinstance(value, str) for value in values):
        raise TranslationContractError(f"{context} must be a string")
    return list(values)  # type: ignore[return-value]


def _validate_string_fields(record: Translation, index: int) -> None:
    if not isinstance(record.segment_id, str):
        raise TranslationContractError(
            f"translation record {index} segment_id must be a string"
        )
    if not isinstance(record.text, str):
        raise TranslationContractError(
            f"translation record {index} text must be a string"
        )
    if record.notes is not None and not isinstance(record.notes, str):
        raise TranslationContractError(
            f"translation record {index} notes must be a string or null"
        )
    if not isinstance(record.glossary_observations, Mapping):
        raise TranslationContractError(
            f"translation record {index} glossary_observations must be an object"
        )
    for key, value in record.glossary_observations.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TranslationContractError(
                "translation glossary observation keys and values must be strings"
            )
