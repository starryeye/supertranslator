"""Recompute native callout provenance from the current held source snapshot.

No approval is cached: callers retain these exact immutable bytes and verify
their anchored files through publication. Source boxes are x0/y0/x1/y1;
drawn table parts are top-origin x/y/width/height.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io

import pdfplumber
from pypdf import PdfReader

from supertranslator.pdf_acquire import MAX_PDF_BYTES
from supertranslator.pdf_callout_models import validate_callout_group_membership
from supertranslator.pdf_callouts import (
    bind_callout_groups, collect_callout_pages, discover_callout_chains,
)
from supertranslator.pdf_models import PdfContractError, PdfDocument
from supertranslator.pdf_flowables import PdfAssemblyLayout, PdfAssemblyError


def validate_callout_source(document: PdfDocument, *, source_pdf_bytes: bytes) -> None:
    """Independently prove the declared source chains without a media render."""
    validate_callout_group_membership(document)
    if document.schema_version != "1.3":
        return
    from supertranslator.pdf_extract import (
        _normalized_rotation, _valid_dimension, _valid_page_bbox,
        _validated_page_tree_count, collect_flow_boundaries,
        collect_owned_flow_lines, logical_pdf_bytes,
    )
    from supertranslator.pdf_layout import _block_source_text, repair_line_fragments
    from supertranslator.pdf_units import build_translation_units, validate_unit_membership

    try:
        if (not isinstance(source_pdf_bytes, bytes) or len(source_pdf_bytes) > MAX_PDF_BYTES
                or not source_pdf_bytes.rstrip(b" \t\r\n\f\x00").endswith(b"%%EOF")):
            raise PdfContractError("callout source exceeds limits or lacks final EOF")
        if hashlib.sha256(source_pdf_bytes).hexdigest() != document.source_sha256:
            raise PdfContractError("callout source SHA-256 differs from document")
        reader = PdfReader(io.BytesIO(source_pdf_bytes), strict=True)
        if reader.is_encrypted:
            raise PdfContractError("encrypted callout source is unsupported")
        count = _validated_page_tree_count(reader)
        if not 1 <= count <= 500 or count != document.page_count or len(reader.pages) != count:
            raise PdfContractError("callout source page count/limit mismatch")
        focus = sorted({fragment.page_number for group in document.callout_groups
                        for fragment in group.fragments} | {
                            block.page_number for block in document.blocks
                            if block.semantic_role in {"callout-title", "callout-body"}})
        if not focus or any(number < 1 or number > count for number in focus):
            raise PdfContractError("callout focus page is absent from actual source")
        with pdfplumber.open(io.BytesIO(logical_pdf_bytes(source_pdf_bytes))) as pdf:
            if len(pdf.pages) != count:
                raise PdfContractError("callout source readers disagree on page count")
            # Geometry is cheap; text/primitives are collected only for the
            # declared/source-callout pages and fixed physical-neighbor window.
            for declared, actual, raw in zip(document.pages, pdf.pages, reader.pages, strict=True):
                _valid_page_bbox(actual.bbox, declared.number)
                geometry = (_valid_dimension(actual.width, declared.number, "width"),
                            _valid_dimension(actual.height, declared.number, "height"),
                            _normalized_rotation(raw.get("/Rotate", 0)))
                if geometry != (declared.width, declared.height, declared.rotation):
                    raise PdfContractError("callout source page geometry mismatch")
            pages = collect_callout_pages(pdf.pages, page_numbers=focus)
        page_map = {page.page_number: page for page in pages}
        if not set(focus).issubset(page_map):
            raise PdfContractError("callout focus page evidence is incomplete")
        if [group.id for group in document.callout_groups] != [
                f"pdf:callout-{index:06d}" for index in range(1, len(document.callout_groups) + 1)]:
            raise PdfContractError("callout publication requires canonical document group IDs")
        by_anchor = {}
        # Overlapping groups share a discovery focus so no declared chain is
        # cut at a shared page. Disjoint neighbors remain furniture-only.
        components = []
        for group in document.callout_groups:
            component = {fragment.page_number for fragment in group.fragments}
            separate = []
            for previous in components:
                if component & previous:
                    component.update(previous)
                else:
                    separate.append(previous)
            components = [*separate, component]
        # Independently inspect role-bearing pages omitted from the declared
        # groups. Closed legacy boxes yield no chain and remain valid. Keep
        # declared disjoint components separate so neighbors remain context.
        covered = set().union(*components)
        for number in sorted(set(focus) - covered):
            if components and number - 1 in components[-1] and not components[-1] & covered:
                components[-1].add(number)
            else:
                components.append({number})
        for component in sorted(components, key=min):
            group_focus = tuple(sorted(component))
            window = {number for page in group_focus for number in (page - 1, page, page + 1)}
            observed = discover_callout_chains(
                tuple(page for page in pages if page.page_number in window), focus_pages=group_focus)
            by_anchor.update({(chain.fragments[0].page_number, chain.fragments[0].border_bbox): chain
                              for chain in observed})
        if len(by_anchor) != len(document.callout_groups):
            raise PdfContractError("callout source chains do not exactly cover declared groups")
        blocks = {block.id: block for block in document.blocks}
        first_orders = []
        regenerated = []
        for group in document.callout_groups:
            anchor = (group.fragments[0].page_number, group.fragments[0].border_bbox)
            chain = by_anchor.pop(anchor, None)
            if chain is None:
                raise PdfContractError("callout source anchor does not identify a proven chain")
            # Sparse discovery numbers are deliberately not document identities.
            actual, = bind_callout_groups((replace(chain, id=group.id),), document.blocks, page_map)
            if actual != group:
                raise PdfContractError("callout source fragment/member/glyph evidence mismatch")
            regenerated.append(actual)
            first_orders.append(blocks[group.fragments[0].source_block_ids[0]].order)
            for fragment in group.fragments:
                lines = repair_line_fragments(page_map[fragment.page_number].lines)
                for member in fragment.source_block_ids:
                    block = blocks[member]
                    owned = [line for line in lines if _inside(
                        (line.x0, line.top, line.x1, line.bottom), block.bbox)]
                    if not owned or _block_source_text(owned) != block.source_text:
                        raise PdfContractError("callout source/block text projection mismatch")
        if first_orders != sorted(set(first_orders)):
            raise PdfContractError("callout groups must follow first physical source member order")
        validate_unit_membership(document)
        line_map = {page.page_number: page.lines for page in pages}
        flags = {}
        owned = collect_owned_flow_lines(document.blocks, document.pages, line_map,
            discretionary_continuations=flags, callout_groups=regenerated)
        boundaries = collect_flow_boundaries(document.blocks, document.pages, line_map,
            owned_lines=owned, callout_groups=regenerated)
        units, findings = build_translation_units(document.blocks, document.pages, boundaries,
            owned_lines=owned, owned_line_continuations=flags, callout_groups=regenerated)
        members = {member for group in regenerated for fragment in group.fragments
                   for member in fragment.source_block_ids}
        if any(f.severity == "required" and (f.left_block_id in members or f.right_block_id in members)
               for f in findings) or any(f.severity == "required" for f in document.flow_findings):
            raise PdfContractError("callout source has required flow findings")
        def projection(unit):
            return unit.source_block_ids, unit.kind, unit.semantic_role, unit.joins
        if ([projection(u) for u in units if set(u.source_block_ids) & members]
                != [projection(u) for u in document.translation_units if set(u.source_block_ids) & members]):
            raise PdfContractError("callout source logical-unit projection mismatch")
    except PdfContractError:
        raise
    except Exception as error:
        raise PdfContractError(f"invalid callout source evidence: {error}") from error


def _inside(inner, outer, tolerance=1e-6):
    return (inner[0] >= outer[0] - tolerance and inner[1] >= outer[1] - tolerance
            and inner[2] <= outer[2] + tolerance and inner[3] <= outer[3] + tolerance)


def _xyxy(bounds):
    x, y, width, height = bounds
    return x, y, x + width, y + height


def validate_callout_layout(document: PdfDocument, layout: PdfAssemblyLayout) -> None:
    """Bind actual drawn owners/parts to the independently proven source groups."""
    validate_callout_group_membership(document)
    if document.schema_version != "1.3":
        if layout.callout_parts or any(item.callout_group_id for item in layout.flowables):
            raise PdfContractError("legacy layout cannot claim grouped callout output")
        return
    if layout.schema_version != "1.3":
        raise PdfContractError("native callout document requires native 1.3 layout")
    try:
        PdfAssemblyLayout.from_dict(layout.to_dict())
    except PdfAssemblyError as error:
        raise PdfContractError(f"invalid callout layout: {error}") from error
    owners = {}
    group_units = {}
    for group in document.callout_groups:
        members = tuple(member for fragment in group.fragments for member in fragment.source_block_ids)
        units = [u for u in document.translation_units if set(u.source_block_ids) & set(members)]
        if tuple(member for unit in units for member in unit.source_block_ids) != members:
            raise PdfContractError("callout units must exactly preserve ordered source members")
        group_units[group.id] = units
        owners.update({unit.id: group.id for unit in units})
    if {part.group_id for part in layout.callout_parts} != set(group_units):
        raise PdfContractError("callout output groups differ from source groups")
    for item in layout.flowables:
        if item.callout_group_id != owners.get(item.unit_id):
            raise PdfContractError("callout output owner captures or drops a source unit")
    anchors = dict(layout.anchor_pages)
    from supertranslator.pdf_assemble import _anchor_name
    for group_id, units in group_units.items():
        records = [r for r in layout.flowables if r.callout_group_id == group_id]
        if tuple(dict.fromkeys(r.unit_id for r in records)) != tuple(u.id for u in units):
            raise PdfContractError("callout output must cover source units once in order")
        for unit in units:
            parts = [r for r in records if r.unit_id == unit.id]
            if any(r.source_block_ids != unit.source_block_ids or r.block_id != unit.source_block_ids[0]
                   for r in parts):
                raise PdfContractError("callout output physical aliases do not match source owners")
            if any(anchors.get(_anchor_name(member)) != parts[0].page_number for member in unit.source_block_ids):
                raise PdfContractError("callout member anchor is detached from its owner")
        titles = [u for u in units if u.semantic_role == "callout-title"]
        bodies = [u for u in units if u.semantic_role == "callout-body"]
        if not bodies or len(titles) > 1 or (titles and titles[0] != units[0]):
            raise PdfContractError("callout must have optional unique leading title and body")
        if not titles:
            continue
        title_records = [r for r in records if r.unit_id == units[0].id]
        first_body = next(r for r in records if r.unit_id == bodies[0].id)
        # _append_callout_group uses spaceAfter=6 and no spaceBefore for
        # both title and body. Permit only floating-point layout roundoff;
        # source font scaling and list indentation do not change this gap.
        title_body_gap = title_records[0].bounds[1] - (first_body.bounds[1] + first_body.bounds[3])
        if (len(title_records) != 1 or title_records[0].page_number != first_body.page_number
                or not -1e-6 <= title_body_gap <= 6 + 1e-6):
            raise PdfContractError("callout title is detached from first body")
    for part in layout.callout_parts:
        box = _xyxy(part.bounds)
        for item in layout.flowables:
            if item.page_number != part.page_number:
                continue
            x, y, width, height = item.bounds
            item_box = (x, layout.page_size.height - y - height, x + width, layout.page_size.height - y)
            if item.callout_group_id != part.group_id and (
                min(box[2], item_box[2]) - max(box[0], item_box[0]) > 1e-6
                and min(box[3], item_box[3]) - max(box[1], item_box[1]) > 1e-6
            ):
                raise PdfContractError("callout output captures outside body/table/figure content")
