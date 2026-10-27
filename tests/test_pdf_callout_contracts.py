"""Strict source-group contracts, independent of detection and publication."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from supertranslator.pdf_callout_models import (
    PdfCalloutFragment, PdfCalloutGroup, validate_callout_group_membership,
)
from supertranslator.pdf_models import (
    PDF_LOGICAL_DOCUMENT_VERSIONS, PdfContractError, PdfDocument,
    has_logical_pdf_units, upgrade_pdf_document_to_units,
)
from tests.pdf_unit_fixtures import make_unit_document


def _fragment(page: int, *, open_top: bool, open_bottom: bool) -> dict:
    return {
        "page_number": page,
        "page_bbox": [-10.0, -20.0, 590.0, 780.0],
        "border_bbox": [20.0, 20.0, 500.0, 700.0],
        "content_bbox": [30.0, 30.0, 490.0, 690.0],
        "open_top": open_top,
        "open_bottom": open_bottom,
        "character_indexes": [0, 2, 3],
        "source_block_ids": [f"pdf:page-{page:04d}:block-0001"],
    }


def _group() -> dict:
    fragments = [
        _fragment(1, open_top=False, open_bottom=True),
        _fragment(2, open_top=True, open_bottom=True),
        _fragment(3, open_top=True, open_bottom=False),
    ]
    fragments[0]["source_block_ids"].append("pdf:page-0001:block-0002")
    return {"id": "pdf:callout-000001", "fragments": fragments}


def _payload() -> dict:
    # Literal geometry and singleton units keep these contracts independent of
    # the later joined-callout producer and its projection/evidence logic.
    blocks = []
    units = []
    for page, number, role, kind, text, top in [
        (1, 1, "callout-title", "heading", "A title", 40.0),
        (1, 2, "callout-body", "paragraph", "A complete paragraph.", 80.0),
        (2, 1, "callout-body", "paragraph", "A second paragraph.", 40.0),
        (3, 1, "callout-body", "list-item", "A complete item.", 40.0),
    ]:
        block_id = f"pdf:page-{page:04d}:block-{number:04d}"
        segment_id = f"seg-{len(blocks) + 1:06d}"
        blocks.append({
            "id": block_id, "page_number": page, "order": len(blocks),
            "kind": kind, "bbox": [40.0, top, 300.0, top + 15.0],
            "style": {"font_size": 12.0, "bold": False, "alignment": "left",
                      "indentation": 0.0, "space_after": 8.0},
            "semantic_role": role, "continuation_of": None,
            "source_text": text, "segment_id": segment_id,
            "table_id": None, "row": None, "column": None,
            "row_span": 1, "column_span": 1, "media_path": None,
            "caption_id": None, "uri": None, "destination": None,
        })
        units.append({
            "id": f"pdf:unit-{len(units) + 1:06d}", "source_block_ids": [block_id],
            "kind": kind, "semantic_role": role, "segment_id": segment_id, "joins": [],
        })
    return {
        "schema_version": "1.3", "source_sha256": "a" * 64,
        "page_count": 3, "selectable_characters": 60, "scan_candidate_pages": [],
        "pages": [{"number": page, "width": 600.0, "height": 800.0, "rotation": 0}
                  for page in (1, 2, 3)],
        "blocks": blocks, "table_cells": [], "links": [], "extraction_warnings": [],
        "extracted_schema_version": "1.3", "translation_units": units,
        "flow_findings": [], "callout_groups": [_group()],
    }


def _add_disjoint_group(payload: dict) -> dict:
    other = deepcopy(payload["callout_groups"][0])
    other["id"] = "pdf:callout-000002"
    for fragment in other["fragments"]:
        page = fragment["page_number"]
        block_id = f"pdf:page-{page:04d}:block-0003"
        block = deepcopy(payload["blocks"][0])
        block.update(id=block_id, page_number=page, order=len(payload["blocks"]),
                     segment_id=f"seg-{len(payload['blocks']) + 1:06d}")
        payload["blocks"].append(block)
        payload["translation_units"].append({
            "id": f"pdf:unit-{len(payload['translation_units']) + 1:06d}",
            "source_block_ids": [block_id], "kind": "heading",
            "semantic_role": "callout-title", "segment_id": block["segment_id"], "joins": [],
        })
        fragment["source_block_ids"] = [block_id]
        fragment["character_indexes"] = [4, 5]
    payload["callout_groups"].append(other)
    return other


def test_callout_contract_round_trip_and_old_bytes() -> None:
    payload = _payload()
    document = PdfDocument.from_dict(payload)
    assert document.to_dict() == payload
    assert document.callout_groups[0].to_dict() == payload["callout_groups"][0]
    assert document.callout_groups[0].fragments[0].character_indexes == (0, 2, 3)
    with pytest.raises(FrozenInstanceError):
        document.callout_groups[0].id = "pdf:callout-000002"

    old = deepcopy(payload)
    old.pop("callout_groups")
    old.update(schema_version="1.2", extracted_schema_version="1.2")
    old_bytes = json.dumps(old, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert json.dumps(PdfDocument.from_dict(old).to_dict(), ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8") == old_bytes
    with pytest.raises(PdfContractError):
        PdfDocument.from_dict({**old, "callout_groups": []})


@pytest.mark.parametrize("field,value", [
    ("page_number", True), ("page_number", 0), ("page_number", "1"),
    ("page_bbox", [0, 0, 0, 800]), ("page_bbox", [0, 0, 600, float("inf")]),
    ("page_bbox", [False, 0, 600, 800]), ("page_bbox", [0, 0, "600", 800]),
    ("page_bbox", [0, 0, 600]), ("border_bbox", [20, 20, 20, 30]),
    ("border_bbox", [-11, 20, 500, 700]), ("border_bbox", [20, 20, 591, 700]),
    ("content_bbox", [19, 30, 490, 690]), ("content_bbox", [30, 30, 490, 701]),
    ("content_bbox", [30, 30, float("nan"), 690]),
    ("open_top", 1), ("open_bottom", "false"),
    ("character_indexes", []), ("character_indexes", [True]), ("character_indexes", [-1]),
    ("character_indexes", [1, 0]), ("character_indexes", [0, 0]),
    ("character_indexes", [0.0]), ("character_indexes", "0"),
    ("source_block_ids", []), ("source_block_ids", [1]),
    ("source_block_ids", ["foreign"]),
    ("source_block_ids", ["pdf:page-0002:block-0001"]),
    ("source_block_ids", ["pdf:page-0001:block-0001"] * 2),
])
def test_fragment_rejects_invalid_geometry_indexes_and_members(field, value) -> None:
    fragment = _fragment(1, open_top=False, open_bottom=True)
    fragment[field] = value
    with pytest.raises(PdfContractError):
        PdfCalloutFragment.from_dict(fragment)


@pytest.mark.parametrize("record,payload", [
    (PdfCalloutFragment, _fragment(1, open_top=False, open_bottom=True)),
    (PdfCalloutGroup, _group()),
])
def test_callout_records_require_exact_fields(record, payload) -> None:
    with pytest.raises(PdfContractError):
        record.from_dict({**payload, "unknown": True})
    missing = dict(payload)
    missing.pop(next(iter(missing)))
    with pytest.raises(PdfContractError):
        record.from_dict(missing)
    with pytest.raises(PdfContractError):
        record.from_dict([])


@pytest.mark.parametrize("mutation", [
    "bad-id", "numeric-id", "empty", "single", "gap", "reverse", "duplicate-page",
    "open-first", "closed-first-bottom", "closed-middle-top", "closed-middle-bottom",
    "closed-last-top", "open-last-bottom",
])
def test_group_requires_one_consecutive_open_border_chain(mutation) -> None:
    group = _group()
    fragments = group["fragments"]
    if mutation == "bad-id":
        group["id"] = "pdf:callout-1"
    elif mutation == "numeric-id":
        group["id"] = 1
    elif mutation == "empty":
        group["fragments"] = []
    elif mutation == "single":
        group["fragments"] = fragments[:1]
    elif mutation == "gap":
        group["fragments"] = [fragments[0], fragments[-1]]
    elif mutation == "reverse":
        fragments.reverse()
    elif mutation == "duplicate-page":
        fragments[1] = deepcopy(fragments[0])
    else:
        index, field, value = {
            "open-first": (0, "open_top", True),
            "closed-first-bottom": (0, "open_bottom", False),
            "closed-middle-top": (1, "open_top", False),
            "closed-middle-bottom": (1, "open_bottom", False),
            "closed-last-top": (2, "open_top", False),
            "open-last-bottom": (2, "open_bottom", True),
        }[mutation]
        fragments[index][field] = value
    with pytest.raises(PdfContractError):
        PdfCalloutGroup.from_dict(group)


def test_two_page_chain_and_negative_page_origins_are_valid() -> None:
    group = _group()
    group["fragments"] = [group["fragments"][0],
                          _fragment(2, open_top=True, open_bottom=False)]
    group["fragments"][0].update(border_bbox=[-8, -18, 500, 700],
                                  content_bbox=[-7, -17, 490, 690])
    assert PdfCalloutGroup.from_dict(group).to_dict() == group


def test_fragment_requires_nonempty_source_character_evidence() -> None:
    fragment = _fragment(1, open_top=False, open_bottom=True)
    fragment["character_indexes"] = []
    with pytest.raises(PdfContractError):
        PdfCalloutFragment.from_dict(fragment)


@pytest.mark.parametrize("mutation", [
    "no-groups", "duplicate-group", "foreign-member", "reordered-members",
    "wrong-page", "wrong-page-size", "outside-content", "body", "figure", "table-cell",
    "footnote", "caption", "missing-unit", "bad-unit", "unassigned", "bad-block",
    "cross-group-block", "cross-group-character", "conflicting-page-bbox",
])
def test_document_rejects_illegal_callout_membership_and_nested_records(mutation) -> None:
    payload = _payload()
    fragment = payload["callout_groups"][0]["fragments"][0]
    block = payload["blocks"][0]
    if mutation == "no-groups":
        payload["callout_groups"] = []
    elif mutation == "duplicate-group":
        payload["callout_groups"].append(deepcopy(payload["callout_groups"][0]))
    elif mutation == "foreign-member":
        fragment["source_block_ids"][0] = "pdf:page-0001:block-0099"
    elif mutation == "reordered-members":
        fragment["source_block_ids"].reverse()
    elif mutation == "wrong-page":
        # Stable ID syntax alone must not authorize a physical block on another page.
        block["page_number"] = 2
    elif mutation == "wrong-page-size":
        fragment["page_bbox"] = [-10, -20, 600, 780]
    elif mutation == "outside-content":
        block["bbox"] = [21, 31, 300, 45]
    elif mutation == "body":
        block["semantic_role"] = payload["translation_units"][0]["semantic_role"] = "body"
    elif mutation in {"figure", "table-cell", "footnote", "caption"}:
        block["kind"] = payload["translation_units"][0]["kind"] = mutation
    elif mutation == "missing-unit":
        payload["translation_units"].pop()
    elif mutation == "bad-unit":
        payload["translation_units"][0]["unknown"] = True
    elif mutation == "bad-block":
        block["style"]["font_size"] = 0
    elif mutation == "unassigned":
        block["segment_id"] = payload["translation_units"][0]["segment_id"] = None
    else:
        other = _add_disjoint_group(payload)
        for other_fragment, original in zip(other["fragments"], payload["callout_groups"][0]["fragments"], strict=True):
            if mutation == "cross-group-block":
                other_fragment["source_block_ids"] = original["source_block_ids"]
            elif mutation == "cross-group-character":
                other_fragment["character_indexes"] = original["character_indexes"]
            else:
                other_fragment["page_bbox"] = [-5, -20, 595, 780]
    with pytest.raises(PdfContractError):
        PdfDocument.from_dict(payload)


@pytest.mark.parametrize("origin", ["1.0", "1.1", "1.2", "1.4", None])
def test_native_callout_document_refuses_old_or_unknown_origin(origin) -> None:
    payload = _payload()
    payload["extracted_schema_version"] = origin
    with pytest.raises(PdfContractError):
        PdfDocument.from_dict(payload)


def test_legacy_adapter_cannot_claim_a_native_callout_origin() -> None:
    with pytest.raises(PdfContractError):
        upgrade_pdf_document_to_units(_payload())
    document = make_unit_document()
    assert has_logical_pdf_units(document)
    assert not has_logical_pdf_units(replace(document, schema_version="1.1"))
    assert has_logical_pdf_units(PdfDocument.from_dict(_payload()))
    assert PDF_LOGICAL_DOCUMENT_VERSIONS == frozenset({"1.2", "1.3"})


def test_distinct_groups_can_share_pages_but_not_members_or_character_indexes() -> None:
    payload = _payload()
    _add_disjoint_group(payload)
    assert PdfDocument.from_dict(payload).to_dict() == payload


def test_logical_unit_capability_does_not_enable_native_callout_assignment() -> None:
    from supertranslator.pdf_unit_bindings import PdfUnitBindingError, require_assignable_pdf
    document = PdfDocument.from_dict(_payload())
    assert has_logical_pdf_units(document)
    with pytest.raises(PdfUnitBindingError, match="native 1.2 extraction"):
        require_assignable_pdf(document)


def test_joined_callout_requires_native_group_context() -> None:
    payload = make_unit_document().to_dict()
    payload.update(schema_version="1.3", extracted_schema_version="1.3")
    for block in payload["blocks"]:
        block["semantic_role"] = "callout-body"
    payload["translation_units"][0]["semantic_role"] = "callout-body"
    group = _group()
    group["fragments"] = [group["fragments"][0],
                          _fragment(2, open_top=True, open_bottom=False)]
    group["fragments"][0]["source_block_ids"] = [payload["blocks"][0]["id"]]
    for fragment in group["fragments"]:
        fragment["page_bbox"] = [0, 0, 612, 792]
        fragment["border_bbox"] = [20, 20, 600, 760]
        fragment["content_bbox"] = [30, 30, 590, 750]
    payload["callout_groups"] = [group]
    document = PdfDocument.from_dict(payload)
    from supertranslator.pdf_units import project_unit_text
    unit, = document.translation_units
    by_id = {b.id: b for b in document.blocks}
    assert project_unit_text(unit, by_id, callout_groups=document.callout_groups,
                             document_schema_version="1.3").text == "A paragraph continues."
    with pytest.raises(PdfContractError, match="multi-member unit must be a body"):
        project_unit_text(unit, by_id, callout_groups=document.callout_groups,
                          document_schema_version="1.2")


def test_fragment_order_must_also_follow_actual_document_block_order() -> None:
    payload = _payload()
    payload["blocks"][1], payload["blocks"][2] = payload["blocks"][2], payload["blocks"][1]
    for index, block in enumerate(payload["blocks"]):
        block["order"] = index
    payload["translation_units"][1], payload["translation_units"][2] = (
        payload["translation_units"][2], payload["translation_units"][1])
    for index, unit in enumerate(payload["translation_units"], 1):
        unit["id"] = f"pdf:unit-{index:06d}"
    with pytest.raises(PdfContractError):
        PdfDocument.from_dict(payload)


@pytest.mark.parametrize("mutation", ["origin", "empty", "member", "fragment", "unit", "old-root"])
def test_direct_constructor_cannot_serialize_invalid_callout_contracts(mutation) -> None:
    document = PdfDocument.from_dict(_payload())
    with pytest.raises(PdfContractError):
        if mutation == "origin":
            document = replace(document, extracted_schema_version="1.2")
        elif mutation == "empty":
            document = replace(document, callout_groups=[])
        elif mutation == "unit":
            document.translation_units.pop()
        elif mutation == "old-root":
            document = replace(document, schema_version="1.2", extracted_schema_version="1.2")
        elif mutation == "fragment":
            fragment = replace(document.callout_groups[0].fragments[0], open_top=1)
            fragment.to_dict()
        else:
            group = document.callout_groups[0]
            fragment = replace(group.fragments[0], source_block_ids=("pdf:page-0001:block-0099",))
            document = replace(document, callout_groups=[replace(group, fragments=(fragment, *group.fragments[1:]))])
        document.to_dict()


def test_membership_validation_accepts_presegmentation_source_groups() -> None:
    document = PdfDocument.from_dict(_payload())
    document = replace(document,
                       blocks=[replace(block, segment_id=None) for block in document.blocks],
                       translation_units=[replace(unit, segment_id=None) for unit in document.translation_units])
    validate_callout_group_membership(document)
    with pytest.raises(PdfContractError):
        document.to_dict()
