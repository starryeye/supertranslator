"""Logical identity for selectable, source-bound continued callout prose."""

from dataclasses import replace

import pytest
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from supertranslator.pdf_extract import extract_pdf
from supertranslator.pdf_models import PdfContractError
from supertranslator.pdf_units import (
    decide_callout_join, decide_page_join, project_protected_occurrences, project_unit_text,
)
from tests.pdf_callout_fixtures import make_page_spanning_callout_pdf


def _continued_source(path, *, list_item=False, pages=2, one_line=False, hanging=False,
                      complete=False, new_marker=False, incompatible_indent=False):
    """Actual open borders and independently specified full-width glyph lines."""
    first = ["Record the initial 12 chamber readings",
             "and retain https://example.org/data for comparison",
             "while the measured account continues across the boundary"]
    if list_item:
        first[0] = "1. " + first[0]
    if one_line:
        first = first[-1:]
    middle = ["without losing the ordering of any source observation",
              "or assigning independent translations to incomplete clauses",
              "while the measured account continues across another boundary"]
    last = ["without losing any of the original 24 observations",
            "and with every protected source link preserved",
            "until this complete measured account reaches its conclusion."]
    if complete:
        first[-1] += "."
    if new_marker:
        last[0] = "2. " + last[0]
    canvas = Canvas(str(path), pagesize=(600, 760), invariant=1)
    hanging_indent = stringWidth("1. ", "Helvetica", 10) * 390 / stringWidth(first[0], "Helvetica", 10)
    for index in range(pages):
        top, bottom = (300, 700) if index == 0 else (60, 460)
        if 0 < index < pages - 1:
            bottom = 120
        canvas.line(60, 760 - top, 60, 760 - bottom)
        canvas.line(480, 760 - top, 480, 760 - bottom)
        if index == 0:
            canvas.line(60, 760 - top, 480, 760 - top)
            canvas.setFont("Helvetica-Bold", 12)
            canvas.drawString(75, 760 - top - 25, "Independent measured observations")
        if index == pages - 1:
            canvas.line(60, 760 - bottom, 480, 760 - bottom)
        if (one_line and index == 0) or ((hanging or incompatible_indent) and index == pages - 1):
            canvas.setFont("Helvetica", 10)
            for n, text in enumerate(("A complete independent account calibrates the source lines",
                                      "and preserves a second measured interval for inspection",
                                      "before its separate paragraph ends.")):
                canvas.drawString(75, 760 - (400 if index == 0 else 200) - n * 14, text)
        lines = first if index == 0 else last if index == pages - 1 else middle
        start = bottom - 9 - 14 * (len(lines) - 1) if index < pages - 1 else top + 18
        for n, text in enumerate(lines):
            indent = hanging_indent if hanging and (index > 0 or n > 0) else 0
            if incompatible_indent and index > 0:
                indent = 15
            obj = canvas.beginText(75 + indent, 760 - start - n * 14)
            obj.setFont("Helvetica", 10)
            measured_width = 280 if complete and index == 0 and n == len(lines) - 1 else 390 - indent
            obj.setHorizScale(measured_width / stringWidth(text, "Helvetica", 10) * 100)
            obj.textLine(text)
            canvas.drawText(obj)
        canvas.showPage()
    canvas.save()
    expected = ("Record the initial 12 chamber readings and retain https://example.org/data for comparison "
                "while the measured account continues across the boundary ")
    if list_item:
        expected = "1. " + expected
    if one_line:
        expected = "while the measured account continues across the boundary "
    if pages == 3:
        expected += ("without losing the ordering of any source observation "
                     "or assigning independent translations to incomplete clauses "
                     "while the measured account continues across another boundary ")
    expected += ("without losing any of the original 24 observations "
                 "and with every protected source link preserved "
                 "until this complete measured account reaches its conclusion.")
    return path, expected


def _extract(tmp_path, **kwargs):
    source, expected = _continued_source(tmp_path / "source.pdf", **kwargs)
    return extract_pdf(source, tmp_path / "document.json", tmp_path / "segments.jsonl",
                       tmp_path / "media"), expected


@pytest.mark.parametrize("list_item,pages,one_line,hanging", [(False, 2, False, False),
    (True, 2, False, False), (False, 3, False, False), (False, 2, True, False),
    (True, 2, False, True)])
def test_callout_boundary_preserves_paragraph_and_item_identity(tmp_path, list_item, pages, one_line, hanging):
    # Removing group routing must split a sentence/item and fail this identity assertion.
    document, expected = _extract(tmp_path, list_item=list_item, pages=pages, one_line=one_line,
                                  hanging=hanging)
    by_id = {b.id: b for b in document.blocks}
    body_units = [u for u in document.translation_units if u.semantic_role == "callout-body"
                  and not by_id[u.source_block_ids[0]].source_text.startswith("A complete")]
    assert len(body_units) == 1
    unit, = body_units
    assert len(unit.source_block_ids) == pages
    assert [by_id[i].page_number for i in unit.source_block_ids] == list(range(1, pages + 1))
    projection = project_unit_text(unit, by_id, callout_groups=document.callout_groups,
                                   document_schema_version=document.schema_version)
    assert projection.text == expected
    assert len([u for u in document.translation_units if u.semantic_role == "callout-title"]) == 1
    for span in projection.spans:
        if span.source_end > span.source_start:
            assert projection.text[span.unit_start:span.unit_end] == by_id[span.block_id].source_text[span.source_start:span.source_end]
    assert len({by_id[i].segment_id for i in unit.source_block_ids}) == 1
    if one_line:
        independent, = [u for u in document.translation_units
                        if by_id[u.source_block_ids[0]].source_text.startswith("A complete")]
        assert len(independent.source_block_ids) == 1


def test_callout_protected_occurrences_require_bound_group_context(tmp_path):
    document, _ = _extract(tmp_path, list_item=True)
    body_units = [u for u in document.translation_units if u.semantic_role == "callout-body"]
    assert len(body_units) == 1
    unit, = body_units
    by_id = {b.id: b for b in document.blocks}
    assert len(unit.source_block_ids) == 2
    for context in ({}, {"callout_groups": document.callout_groups},
                    {"document_schema_version": "1.3"}):
        with pytest.raises(PdfContractError):
            project_unit_text(unit, by_id, **context)
        with pytest.raises(PdfContractError):
            project_protected_occurrences(unit, by_id, **context)
    occurrences = project_protected_occurrences(unit, by_id,
        callout_groups=document.callout_groups, document_schema_version="1.3")
    assert [o.value for o in occurrences] == ["1", "12", "https://example.org/data", "24"]
    for occurrence in occurrences:
        assert "".join(by_id[s.block_id].source_text[s.source_start:s.source_end]
                       for s in occurrence.source_spans) == occurrence.value


def test_sentence_final_callout_fragments_remain_required_ambiguity(tmp_path):
    fixture = make_page_spanning_callout_pdf(tmp_path / "source.pdf")
    document = extract_pdf(fixture.source, tmp_path / "document.json",
                           tmp_path / "segments.jsonl", tmp_path / "media")
    assert len([u for u in document.translation_units if u.semantic_role == "callout-body"]) == 2
    assert len(document.flow_findings) == 1
    assert document.flow_findings[0].severity == "required"


@pytest.mark.parametrize("case", ["complete", "new-marker"])
def test_source_proven_complete_paragraph_and_new_list_marker_stay_separate(tmp_path, case):
    document, _ = _extract(tmp_path, list_item=case == "new-marker",
                            complete=case == "complete", new_marker=case == "new-marker")
    body = [u for u in document.translation_units if u.semantic_role == "callout-body"]
    assert len(body) == 2
    assert all(len(u.source_block_ids) == 1 for u in body)
    assert [u.kind for u in body] == (["paragraph", "paragraph"] if case == "complete"
                                    else ["list-item", "list-item"])
    assert not document.flow_findings


def test_native_inline_list_with_incompatible_continuation_requires_ambiguity(tmp_path):
    # A real bound chain and self-consistent indented glyphs must not silently
    # authorize independent targets for an unfinished inline item.
    document, _ = _extract(tmp_path, list_item=True, incompatible_indent=True)
    assert len(document.callout_groups) == 1
    body = [u for u in document.translation_units if u.semantic_role == "callout-body"]
    assert len(body) == 3
    assert all(len(u.source_block_ids) == 1 for u in body)
    by_id = {b.id: b for b in document.blocks}
    left, right = [by_id[u.source_block_ids[0]] for u in body[:2]]
    assert left.kind == "list-item" and left.source_text.endswith("across the boundary")
    assert right.kind == "paragraph" and right.source_text.startswith("without losing")
    assert left.bbox[0] == 75 and right.bbox[0] == 90
    assert len(document.flow_findings) == 1
    finding, = document.flow_findings
    assert (finding.left_block_id, finding.right_block_id, finding.severity) == (left.id, right.id, "required")


def test_callout_overflow_exception_cannot_shorten_ordinary_body_frame(tmp_path):
    document, _ = _extract(tmp_path)
    unit, = [u for u in document.translation_units if u.semantic_role == "callout-body"]
    by_id = {b.id: b for b in document.blocks}
    left, right = [replace(by_id[i], semantic_role="body") for i in unit.source_block_ids]
    evidence = unit.joins[0].evidence
    decision = decide_page_join(left, right, evidence.left, evidence.right,
                                {p.number: p for p in document.pages})
    assert decision.status == "ambiguous"
    assert "too short" in decision.finding.message


def test_two_valid_source_groups_never_share_a_logical_unit(tmp_path):
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for index in range(2):
        source, _ = _continued_source(tmp_path / f"source-{index}.pdf")
        for page in PdfReader(source).pages:
            writer.add_page(page)
    source = tmp_path / "two-groups.pdf"
    with source.open("wb") as stream:
        writer.write(stream)
    document = extract_pdf(source, tmp_path / "document.json",
                           tmp_path / "segments.jsonl", tmp_path / "media")
    assert len(document.callout_groups) == 2
    body = [u for u in document.translation_units if u.semantic_role == "callout-body"]
    assert [len(u.source_block_ids) for u in body] == [2, 2]
    by_id = {b.id: b for b in document.blocks}
    crossed = replace(body[0], source_block_ids=(body[0].source_block_ids[-1],
                                               body[1].source_block_ids[0]))
    with pytest.raises(PdfContractError, match="one bound source group"):
        project_unit_text(crossed, by_id, callout_groups=document.callout_groups,
                           document_schema_version="1.3")


def test_callout_protected_discretionary_word_and_note_keep_every_physical_span(tmp_path):
    # Projection consumes source-bound model records; simulate a supported
    # discretionary glyph here without depending on an installed Unicode font.
    document, _ = _extract(tmp_path)
    unit, = [u for u in document.translation_units if u.semantic_role == "callout-body"]
    by_id = {b.id: b for b in document.blocks}
    left_id, right_id = unit.source_block_ids
    note = replace(by_id[left_id], id="pdf:page-0002:block-9999", page_number=2,
                   kind="footnote", semantic_role="body", source_text="* A measured note.",
                   segment_id=None)
    by_id[note.id] = note
    by_id[left_id] = replace(by_id[left_id], source_text="Retain 12 * https://example.org/para‐",
                             destination=note.id)
    by_id[right_id] = replace(by_id[right_id], source_text="meter and 24 observations.")
    unit = replace(unit, joins=(replace(unit.joins[0], operation="remove-discretionary-hyphen"),))
    occurrences = project_protected_occurrences(unit, by_id,
        callout_groups=document.callout_groups, document_schema_version="1.3")
    assert [(o.value, o.kind) for o in occurrences] == [
        ("12", "number"), ("*", "footnote-marker"),
        ("https://example.org/parameter", "url"), ("24", "number")]
    note_marker = occurrences[1]
    assert (note_marker.owner_block_id, note_marker.note_id) == (left_id, note.id)
    url = occurrences[2]
    assert [s.block_id for s in url.source_spans] == [left_id, left_id, right_id]
    assert "".join(by_id[s.block_id].source_text[s.source_start:s.source_end]
                   for s in url.source_spans) == "https://example.org/para‐meter"
    assert "".join(by_id[s.block_id].source_text[s.source_start:s.source_end]
                   for s in url.source_spans if s.unit_start < s.unit_end) == url.value
    projection = project_unit_text(unit, by_id, callout_groups=document.callout_groups,
                                   document_schema_version="1.3")
    assert projection.text == "Retain 12 * https://example.org/parameter and 24 observations."
    removed, = [s for s in projection.spans if s.unit_start == s.unit_end]
    assert by_id[removed.block_id].source_text[removed.source_start:removed.source_end] == "‐"


@pytest.mark.parametrize("mutation", ["missing-group", "foreign-group", "duplicate-group",
                                     "reordered", "duplicate", "title", "body", "reference", "new-marker"])
def test_joined_callout_projection_refuses_foreign_or_invalid_members(tmp_path, mutation):
    document, _ = _extract(tmp_path)
    unit, = [u for u in document.translation_units if u.semantic_role == "callout-body"]
    by_id = {b.id: b for b in document.blocks}
    groups = document.callout_groups
    if mutation == "missing-group":
        groups = ()
    elif mutation == "foreign-group":
        first, second = groups[0].fragments
        groups = (replace(groups[0], fragments=(first, replace(second,
                    source_block_ids=(first.source_block_ids[0],)))),)
    elif mutation == "duplicate-group":
        groups = (*groups, *groups)
    elif mutation == "reordered":
        unit = replace(unit, source_block_ids=tuple(reversed(unit.source_block_ids)))
    elif mutation == "duplicate":
        unit = replace(unit, source_block_ids=(unit.source_block_ids[0],) * 2)
    else:
        identifier = unit.source_block_ids[-1]
        changes = {"title": {"semantic_role": "callout-title", "kind": "heading"},
                   "body": {"semantic_role": "body"},
                   "reference": {"semantic_role": "reference-entry"},
                   "new-marker": {"source_text": "2. A separate item begins here."}}[mutation]
        by_id[identifier] = replace(by_id[identifier], **changes)
    with pytest.raises(PdfContractError):
        project_unit_text(unit, by_id, callout_groups=groups, document_schema_version="1.3")


@pytest.mark.parametrize("mutation", ["missing-owned", "foreign-line", "punctuation", "uppercase",
                                     "ragged", "pitch", "inline-to-hanging", "new-title", "new-item"])
def test_callout_join_requires_complete_positive_physical_evidence(tmp_path, mutation):
    document, _ = _extract(tmp_path, list_item=True)
    unit, = [u for u in document.translation_units if u.semantic_role == "callout-body"]
    by_id = {b.id: b for b in document.blocks}
    left, right = [by_id[i] for i in unit.source_block_ids]
    lb, rb = unit.joins[0].evidence.left, unit.joins[0].evidence.right
    # Re-extract actual owned glyph lines rather than fabricating positive evidence.
    import pdfplumber
    from supertranslator.pdf_layout import group_words_into_lines
    from supertranslator.pdf_extract import collect_owned_flow_lines
    with pdfplumber.open(tmp_path / "source.pdf") as pdf:
        lines = {n + 1: group_words_into_lines(page.extract_words(
            return_chars=True, extra_attrs=["fontname", "size"])) for n, page in enumerate(pdf.pages)}
    flags = {}
    owned = collect_owned_flow_lines(document.blocks, document.pages, lines,
        callout_groups=document.callout_groups, discretionary_continuations=flags)
    if mutation == "missing-owned":
        owned.pop(left.id)
    elif mutation == "foreign-line":
        owned[left.id] = (*owned[left.id][:-1], replace(owned[left.id][-1], text="Unowned prose"))
    elif mutation in {"punctuation", "uppercase", "ragged", "inline-to-hanging"}:
        target = left if mutation in {"punctuation", "ragged"} else right
        members = list(owned[target.id])
        index = -1 if target == left else 0
        line = members[index]
        if mutation == "punctuation":
            members[index] = replace(line, text=line.text + ".")
            left = replace(left, source_text=left.source_text + ".")
        elif mutation == "uppercase":
            members[index] = replace(line, text="W" + line.text[1:])
            right = replace(right, source_text="W" + right.source_text[1:])
        elif mutation == "ragged":
            members[index] = replace(line, bbox=(*line.bbox[:2], line.bbox[2] - 30, line.bbox[3]))
        else:
            members = [replace(member, bbox=(member.bbox[0] + 15, *member.bbox[1:])) for member in members]
            right = replace(right, bbox=(right.bbox[0] + 15, *right.bbox[1:]))
        owned[target.id] = tuple(members)
        if target.id == left.id:
            lb = replace(lb, last_line=members[-1])
        else:
            rb = replace(rb, first_line=members[0], last_line=members[-1])
            if mutation == "inline-to-hanging":
                rb = replace(rb, text_indent=15)
    elif mutation == "pitch":
        rb = replace(rb, line_pitch=rb.line_pitch * 1.3)
    elif mutation == "new-title":
        right = replace(right, kind="heading", semantic_role="callout-title")
    else:
        right = replace(right, kind="list-item", source_text="2. " + right.source_text)
    by_id[left.id], by_id[right.id] = left, right
    decision = decide_callout_join(left, right, lb, rb,
        {p.number: p for p in document.pages}, group=document.callout_groups[0],
        owned_lines=owned, ownership_blocks=list(by_id.values()), owned_line_continuations=flags)
    assert decision.status != "join"
    if mutation in {"missing-owned", "foreign-line", "punctuation", "uppercase", "ragged", "pitch", "inline-to-hanging"}:
        assert decision.finding is not None and decision.finding.severity == "required"
    if mutation == "inline-to-hanging":
        assert rb.text_indent == rb.first_line.bbox[0] - rb.column_bbox[0] == 15
        ordinary = decide_page_join(replace(left, semantic_role="body"),
            replace(right, semantic_role="body"), lb, rb, {p.number: p for p in document.pages})
        assert ordinary.status == "separate" and ordinary.finding is None
