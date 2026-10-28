"""Strict source evidence for a callout spanning consecutive PDF pages.

These records describe ownership only; they confer no publication permission.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
import re
from typing import Any, TYPE_CHECKING

from supertranslator.pdf_models import (
    BBox, PdfContractError, _BLOCK_ID, _require_bbox, _require_bool,
    _require_exact_fields, _require_list, _require_mapping,
    _require_nonnegative_int, _require_positive_int, _require_string,
    _require_string_list,
)

if TYPE_CHECKING:
    from supertranslator.pdf_models import PdfDocument


_CALLOUT_ID = re.compile(r"pdf:callout-\d{6}\Z")


@dataclass(frozen=True, slots=True)
class PdfCalloutLayoutPart:
    """One actually drawn table part; bounds are top-origin (x, y, width, height)."""

    group_id: str
    page_number: int
    split_part: int
    bounds: BBox
    unit_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        data = {"group_id": self.group_id, "page_number": self.page_number,
                "split_part": self.split_part, "bounds": list(self.bounds),
                "unit_ids": list(self.unit_ids)}
        type(self).from_dict(data)
        return data

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PdfCalloutLayoutPart:
        context = "PdfCalloutLayoutPart"
        value = _require_exact_fields(value, context, set(cls.__dataclass_fields__))
        group_id = _require_string(value, "group_id", context)
        if _CALLOUT_ID.fullmatch(group_id) is None:
            raise PdfContractError(f"{context}.group_id must be a stable callout ID")
        bounds = _require_list(value, "bounds", context)
        if (len(bounds) != 4 or any(type(n) not in {int, float} or not math.isfinite(n) for n in bounds)
                or any(n < 0 for n in bounds[:2]) or any(n <= 0 for n in bounds[2:])):
            raise PdfContractError(f"{context}.bounds must be finite top-origin bounds with positive size")
        units = tuple(_require_string_list(value, "unit_ids", context))
        if (not units or len(set(units)) != len(units)
                or any(re.fullmatch(r"pdf:unit-\d{6}", unit) is None for unit in units)):
            raise PdfContractError(f"{context}.unit_ids must be nonempty unique stable unit IDs")
        return cls(group_id, _require_positive_int(value, "page_number", context),
                   _require_nonnegative_int(value, "split_part", context),
                   tuple(float(n) for n in bounds), units)


def _contains(outer: BBox, inner: BBox) -> bool:
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


@dataclass(frozen=True, slots=True)
class PdfCalloutFragment:
    page_number: int
    page_bbox: BBox
    border_bbox: BBox
    content_bbox: BBox
    open_top: bool
    open_bottom: bool
    character_indexes: tuple[int, ...]
    source_block_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        data = {
            "page_number": self.page_number,
            "page_bbox": list(self.page_bbox),
            "border_bbox": list(self.border_bbox),
            "content_bbox": list(self.content_bbox),
            "open_top": self.open_top,
            "open_bottom": self.open_bottom,
            "character_indexes": list(self.character_indexes),
            "source_block_ids": list(self.source_block_ids),
        }
        type(self).from_dict(data)
        return data

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PdfCalloutFragment:
        context = "PdfCalloutFragment"
        value = _require_exact_fields(value, context, {
            "page_number", "page_bbox", "border_bbox", "content_bbox",
            "open_top", "open_bottom", "character_indexes", "source_block_ids",
        })
        page_number = _require_positive_int(value, "page_number", context)
        boxes = {
            name: _require_bbox({"bbox": value[name]}, f"{context}.{name}")
            for name in ("page_bbox", "border_bbox", "content_bbox")
        }
        if not _contains(boxes["page_bbox"], boxes["border_bbox"]):
            raise PdfContractError(f"{context}.border_bbox must be contained in page_bbox")
        if not _contains(boxes["border_bbox"], boxes["content_bbox"]):
            raise PdfContractError(f"{context}.content_bbox must be contained in border_bbox")
        indexes = tuple(
            _require_nonnegative_int({"index": item}, "index", f"{context}.character_indexes[{index}]")
            for index, item in enumerate(_require_list(value, "character_indexes", context))
        )
        if not indexes or indexes != tuple(sorted(set(indexes))):
            raise PdfContractError(f"{context}.character_indexes must be nonempty, sorted and unique")
        members = tuple(_require_string_list(value, "source_block_ids", context))
        if not members or len(set(members)) != len(members):
            raise PdfContractError(f"{context}.source_block_ids must be nonempty and unique")
        for member in members:
            match = _BLOCK_ID.fullmatch(member)
            if match is None or int(match.group("page")) != page_number:
                raise PdfContractError(f"{context}.source_block_ids must be stable members on its page")
        return cls(
            page_number=page_number, page_bbox=boxes["page_bbox"],
            border_bbox=boxes["border_bbox"], content_bbox=boxes["content_bbox"],
            open_top=_require_bool(value, "open_top", context),
            open_bottom=_require_bool(value, "open_bottom", context),
            character_indexes=indexes, source_block_ids=members,
        )


@dataclass(frozen=True, slots=True)
class PdfCalloutGroup:
    id: str
    fragments: tuple[PdfCalloutFragment, ...]

    def to_dict(self) -> dict[str, object]:
        data = {"id": self.id, "fragments": [fragment.to_dict() for fragment in self.fragments]}
        type(self).from_dict(data)
        return data

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PdfCalloutGroup:
        context = "PdfCalloutGroup"
        value = _require_exact_fields(value, context, {"id", "fragments"})
        identifier = _require_string(value, "id", context)
        if _CALLOUT_ID.fullmatch(identifier) is None:
            raise PdfContractError(f"{context}.id must be a stable callout ID")
        fragments = tuple(
            PdfCalloutFragment.from_dict(_require_mapping(item, f"{context}.fragments[{index}]"))
            for index, item in enumerate(_require_list(value, "fragments", context))
        )
        if len(fragments) < 2:
            raise PdfContractError(f"{context}.fragments must span at least two consecutive pages")
        first_page = fragments[0].page_number
        if [fragment.page_number for fragment in fragments] != list(range(first_page, first_page + len(fragments))):
            raise PdfContractError(f"{context}.fragments must span consecutive pages in order")
        for index, fragment in enumerate(fragments):
            if (fragment.open_top, fragment.open_bottom) != (index > 0, index < len(fragments) - 1):
                raise PdfContractError(f"{context}.fragments must form a closed-top/open-bottom chain")
        return cls(identifier, fragments)


def validate_callout_group_membership(document: PdfDocument) -> None:
    """Validate source references without loading parser or media machinery."""
    if document.schema_version != "1.3":
        if document.callout_groups:
            raise PdfContractError("PdfDocument.callout_groups require native schema 1.3")
        return
    if document.extracted_schema_version != "1.3" or not document.callout_groups:
        raise PdfContractError("PdfDocument.callout_groups require native 1.3 origin and nonempty groups")
    pages = {page.number: page for page in document.pages}
    by_id = {block.id: block for block in document.blocks}
    group_ids: set[str] = set()
    seen_blocks: set[str] = set()
    seen_characters: set[tuple[int, int]] = set()
    page_boxes: dict[int, BBox] = {}
    for group in document.callout_groups:
        # Also validate records made directly, not only those parsed from JSON.
        group.to_dict()
        if group.id in group_ids:
            raise PdfContractError("PdfDocument.callout_groups must have unique IDs")
        group_ids.add(group.id)
        orders: list[int] = []
        for fragment in group.fragments:
            page = pages.get(fragment.page_number)
            if page is None:
                raise PdfContractError("PdfDocument.callout_groups must refer to source pages")
            x0, y0, x1, y1 = fragment.page_bbox
            if (x1 - x0, y1 - y0) != (page.width, page.height):
                raise PdfContractError("PdfDocument.callout_groups page_bbox must match source page size")
            prior_bbox = page_boxes.setdefault(page.number, fragment.page_bbox)
            if prior_bbox != fragment.page_bbox:
                raise PdfContractError("PdfDocument.callout_groups page_bbox must be consistent on a source page")
            characters = {(page.number, index) for index in fragment.character_indexes}
            if seen_characters & characters:
                raise PdfContractError("PdfDocument.callout_groups character has duplicate ownership")
            seen_characters.update(characters)
            for block_id in fragment.source_block_ids:
                block = by_id.get(block_id)
                if block is None or block.page_number != fragment.page_number:
                    raise PdfContractError("PdfDocument.callout_groups member must exist on its source page")
                if (block.semantic_role not in {"callout-title", "callout-body"}
                        or block.kind not in {"heading", "paragraph", "list-item"}
                        or not block.source_text.strip()):
                    raise PdfContractError("PdfDocument.callout_groups member must be callout text")
                if not _contains(fragment.content_bbox, block.bbox):
                    raise PdfContractError("PdfDocument.callout_groups member must be contained in content_bbox")
                if block_id in seen_blocks:
                    raise PdfContractError("PdfDocument.callout_groups member has duplicate ownership")
                seen_blocks.add(block_id)
                orders.append(block.order)
        if orders != sorted(orders):
            raise PdfContractError("PdfDocument.callout_groups members must follow physical order")
