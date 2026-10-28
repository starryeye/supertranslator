"""Developer-only Korean composer regressions; no publication permission."""

import io
import copy
from dataclasses import replace

import pdfplumber
import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

from supertranslator.models import read_segments, Translation
from supertranslator.pdf_assemble import PdfRenderUnit, _build_rich_document, _anchor_name, _unit_markups
from supertranslator.pdf_extract import extract_pdf
from supertranslator.pdf_flowables import PdfPageSize
from supertranslator.pdf_models import PdfSourceRecord
from tests.test_pdf_callout_units import _continued_source


def _render_case(tmp_path, *, note=False, reference_size=10, composition_role=None):
    writer = PdfWriter()
    if composition_role is not None:
        prefix = io.BytesIO()
        canvas = Canvas(prefix, pagesize=(600, 760))
        if composition_role == "opener":
            canvas.setFont("Helvetica-Bold", 14)
            canvas.drawString(75, 600, "PART I")
            canvas.setFont("Helvetica-Bold", 24)
            canvas.drawString(75, 565, "Measured foundations")
        else:
            canvas.setFont("Helvetica-Oblique", 12)
            canvas.drawString(180, 450, '"A measured thought to retain."')
            canvas.setFont("Helvetica", 10)
            canvas.drawString(240, 430, "— The observer")
        canvas.save()
        writer.add_page(PdfReader(prefix).pages[0])
    for index in range(2):
        source, _ = _continued_source(tmp_path / f"chain-{index}.pdf", list_item=index == 1)
        for page in PdfReader(source).pages:
            writer.add_page(page)
    overlay = io.BytesIO()
    canvas = Canvas(overlay, pagesize=(600, 760))
    canvas.setFont("Helvetica", reference_size)
    canvas.drawString(75, 220, "Following independent account ends here.")
    canvas.save()
    writer.pages[-1].merge_page(PdfReader(overlay).pages[0])
    overlay = io.BytesIO()
    canvas = Canvas(overlay, pagesize=(600, 760))
    line = "and retain https://example.org/data for comparison"
    scale = 390 / stringWidth(line, "Helvetica", 10)
    x = 75 + stringWidth("and retain ", "Helvetica", 10) * scale
    width = stringWidth("https://example.org/data", "Helvetica", 10) * scale
    canvas.linkURL("https://example.org/data", (x, 81, x + width, 93), relative=0)
    canvas.showPage()
    canvas.save()
    writer.pages[int(composition_role is not None)].merge_page(PdfReader(overlay).pages[0])
    if note:
        overlay = io.BytesIO()
        canvas = Canvas(overlay, pagesize=(600, 760))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(467, 654, "*")
        canvas.drawString(75, 70, "* A measured source note.")
        canvas.save()
        writer.pages[1].merge_page(PdfReader(overlay).pages[0])
    for number, page in enumerate(writer.pages, 1):
        overlay = io.BytesIO()
        canvas = Canvas(overlay, pagesize=(600, 760))
        canvas.setFont("Helvetica", 10)
        canvas.drawString(300, 20, str(number))
        canvas.save()
        page.merge_page(PdfReader(overlay).pages[0])
    source = tmp_path / "source.pdf"
    with source.open("wb") as stream:
        writer.write(stream)
    document = extract_pdf(source, tmp_path / "document.json", tmp_path / "segments.jsonl", tmp_path / "media")
    assert document.schema_version == "1.3" and len(document.callout_groups) == 2
    assert not document.flow_findings
    assert len([block for block in document.blocks if block.kind == "page-number"]) == (5 if composition_role else 4)
    first_callout_page = document.callout_groups[0].fragments[0].page_number
    segments = {segment.id: segment for segment in read_segments(tmp_path / "segments.jsonl")}
    blocks = {block.id: block for block in document.blocks}
    render_units = []
    for unit in document.translation_units:
        first = blocks[unit.source_block_ids[0]]
        if unit.semantic_role == "callout-title":
            text = "첫 번째 관측 상자" if first.page_number == first_callout_page else "두 번째 관측 상자"
        elif unit.semantic_role == "callout-body":
            text = ("긴 관측 문단 시작 " + "측정한 결과를 순서대로 보존하고 충분한 간격으로 읽습니다. " * 320
                    + "12 https://example.org/data 24 긴 관측 문단 끝") if unit.kind == "paragraph" else "1. 목록 관측값 12 https://example.org/data 24 보존 완료"
            if composition_role is not None and unit.kind == "paragraph":
                text = "관측 본문 12 https://example.org/data 24 검증 끝"
        elif unit.semantic_role == "part-label":
            text = "제일부"
        elif unit.semantic_role == "part-title":
            text = "관측의 기초"
        elif unit.semantic_role == "epigraph":
            text = "기록한 생각을 보존합니다."
        elif unit.semantic_role == "epigraph-attribution":
            text = "관측자"
        elif unit.kind == "footnote":
            text = "* 이어지는 관측의 출처 각주"
        else:
            text = "상자 다음의 독립 본문"
        if note and first.page_number == 1 and unit.semantic_role == "callout-body":
            text += " *"
        render_units.append(PdfRenderUnit(unit, tuple(blocks[i] for i in unit.source_block_ids), segments[unit.segment_id], text))
    source_record = PdfSourceRecord("1.0", "local", str(source), str(source), "application/pdf", source.stat().st_size,
                                    document.source_sha256, "2026-10-28T00:00:00Z", [], [])
    translations = {}
    for render in render_units:
        protected_text = render.text
        for token in render.segment.protected:
            protected_text = protected_text.replace(token.value, token.token, 1)
        translations[render.segment.id] = Translation(render.segment.id, protected_text)
    markup, _links = _unit_markups(document, render_units, translations, {})
    evidence = {}
    output = tmp_path / "synthetic-callout.pdf"
    parts = []
    with output.open("wb") as stream:
        records = _build_rich_document(document,
            [(render.source_blocks[0], render.segment, render.text) for render in render_units],
            source_record, stream, PdfPageSize("A4", 595.2756, 841.8898), {},
            render_units=render_units, publication_evidence=evidence, unit_markup=markup, callout_parts=parts)
    assert parts == evidence["callout_parts"]
    return document, render_units, records, evidence, output


@pytest.mark.parametrize("composition_role", ["opener", "epigraph"])
def test_composed_source_page_precedes_grouped_callout_without_delaying_following_body(tmp_path, composition_role):
    # Routing grouped content before the source-page fence puts the callout on
    # the opener/epigraph page, then moves the following ordinary body instead.
    document, units, records, evidence, output = _render_case(tmp_path, composition_role=composition_role)
    roles = {"part-label", "part-title"} if composition_role == "opener" else {"epigraph", "epigraph-attribution"}
    composed = [record for record in records if record.semantic_role in roles]
    assert {record.semantic_role for record in composed} == roles
    assert {record.page_number for record in composed} == {1}
    assert {part.page_number for part in evidence["callout_parts"]} == {2}
    following, = [record for record in records if record.semantic_role == "body" and record.kind == "paragraph"]
    assert following.page_number == 2
    for render in units:
        assert all(_anchor_name(member) in evidence["anchor_pages"] for member in render.unit.source_block_ids)
    assert len({record.unit_id for record in records if record.callout_group_id}) == 4
    with pdfplumber.open(output) as pdf:
        assert len(pdf.pages) == 2
        first, second = [page.extract_text() or "" for page in pdf.pages]
    assert "첫 번째 관측 상자" not in first
    for phrase in ("첫 번째 관측 상자", "두 번째 관측 상자", "관측 본문", "목록 관측값", "상자 다음의 독립 본문"):
        assert second.count(phrase) == 1


def test_linked_callout_reflow_preserves_units_and_anchors(tmp_path):
    # Dropping group routing renders physical fragments twice or loses owners;
    # dropping table tracking loses actual split membership and aliases.
    document, units, records, evidence, output = _render_case(tmp_path)
    with pdfplumber.open(output) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        assert len(pdf.pages) > 2
    for phrase in ("첫 번째 관측 상자", "두 번째 관측 상자", "긴 관측 문단 시작", "긴 관측 문단 끝", "목록 관측값", "상자 다음의 독립 본문"):
        assert text.count(phrase) == 1
    for render in units:
        assert all(_anchor_name(member) in evidence["anchor_pages"] for member in render.unit.source_block_ids)
    grouped = [record for record in records if record.semantic_role.startswith("callout-")]
    assert all(record.callout_group_id in {group.id for group in document.callout_groups} for record in grouped)
    assert {record.unit_id for record in grouped} == {render.unit.id for render in units if render.unit.semantic_role.startswith("callout-")}
    parts = evidence["callout_parts"]
    first_parts = [part for part in parts if part.group_id == document.callout_groups[0].id]
    assert len(first_parts) > 1
    assert [part.split_part for part in first_parts] == list(range(len(first_parts)))
    assert all(part.bounds[1] >= 54 for part in parts)
    assert all(part.unit_ids for part in parts)
    source_link, = [link for link in document.links if link.uri == "https://example.org/data"]
    assert source_link.reconstructed
    assert any(annotation.get_object().get("/A", {}).get("/URI") == "https://example.org/data"
               for page in PdfReader(output).pages for annotation in page.get("/Annots", []))
    for render in units:
        unit_records = [record for record in records if record.unit_id == render.unit.id]
        assert [record.split_part for record in unit_records] == list(range(len(unit_records)))


def test_grouped_continued_member_owns_note_on_its_rendered_page(tmp_path):
    document, units, records, evidence, output = _render_case(tmp_path, note=True)
    note, = [block for block in document.blocks if block.kind == "footnote"]
    owner, = [block for block in document.blocks if block.destination == note.id]
    render, = [u for u in units if owner.id in u.unit.source_block_ids]
    assert owner.id == render.unit.source_block_ids[-1]
    note_record, = [record for record in records if record.block_id == note.id]
    assert note_record.footnote_owner_id == owner.id
    assert note_record.footnote_ownership == "protected-footnote-marker"
    owner_records = [record for record in records if record.unit_id == render.unit.id]
    assert note_record.page_number == owner_records[-1].page_number
    assert evidence["callout_parts"]
    with pdfplumber.open(output) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert text.count("이어지는 관측의 출처 각주") == 1


def test_grouped_body_retains_source_relative_font_scale(tmp_path):
    # Replacing source-relative sizing by the old flat callout body size loses
    # this independently selected 10pt / 9pt source relationship.
    _document, _units, records, _evidence, _output = _render_case(tmp_path, reference_size=9)
    assert all(record.font_size == pytest.approx(110 / 9) for record in records if record.semantic_role == "callout-body")


def test_table_moves_title_with_first_body_at_frame_edge(tmp_path):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
    from supertranslator.pdf_callout_flowables import TrackedCalloutTable
    from supertranslator.pdf_flowables import TrackedFlowable
    parts, records, counters = [], [], {}
    style = ParagraphStyle("edge", fontName="Helvetica", fontSize=10, leading=12)
    children = [TrackedFlowable(Paragraph(text, style),
        block_id=f"pdf:page-0001:block-{i:04d}", kind="heading" if i == 1 else "paragraph",
        source_order=i, split_part=0, font_size=10, frame=(36, 36, 228, 228),
        records=records, part_counters=counters, semantic_role="callout-title" if i == 1 else "callout-body",
        unit_id=f"pdf:unit-{i:06d}", source_block_ids=(f"pdf:page-0001:block-{i:04d}",),
        callout_group_id="pdf:callout-000001")
        for i, text in enumerate(("One source title", "First body text " * 80), 1)]
    table = Table([[children]], colWidths=[216], splitInRow=1, style=[("VALIGN", (0, 0), (-1, -1), "TOP")])
    tracked = TrackedCalloutTable(table, group_id="pdf:callout-000001",
        unit_ids=("pdf:unit-000001", "pdf:unit-000002"), parts=parts, records=records, counters=counters)
    output = tmp_path / "title-edge.pdf"
    SimpleDocTemplate(str(output), pagesize=(300, 300), leftMargin=36, rightMargin=36,
        topMargin=36, bottomMargin=36).build([Spacer(1, 190), tracked])
    assert parts[0].page_number == 2
    assert parts[0].unit_ids == ("pdf:unit-000001", "pdf:unit-000002")
    with pdfplumber.open(output) as pdf:
        assert "One source title" not in (pdf.pages[0].extract_text() or "")
        assert "One source title" in pdf.pages[1].extract_text()
        assert sum((page.extract_text() or "").count("One source title") for page in pdf.pages) == 1


def test_callout_layout_requires_coherent_parts_and_native_schema(tmp_path):
    from supertranslator.pdf_flowables import PdfAssemblyLayout, PdfAssemblyError
    document, units, records, evidence, output = _render_case(tmp_path)
    layout = PdfAssemblyLayout("1.3", str(tmp_path / "output"), "0" * 64,
        PdfPageSize("A4", 595.2756, 841.8898), 9.0,
        tuple(sorted(records, key=lambda r: (r.source_order, r.split_part))), (),
        anchor_pages=tuple(sorted(evidence["anchor_pages"].items())),
        callout_parts=tuple(evidence["callout_parts"]))
    data = layout.to_dict()
    assert PdfAssemblyLayout.from_dict(data).to_dict() == data
    assert set(data["callout_parts"][0]) == {"group_id", "page_number", "split_part", "bounds", "unit_ids"}
    for mutation in ("old-schema", "missing", "foreign-unit", "duplicate-part", "reorder", "wrong-page", "foreign-group", "missing-owner", "boolean-index", "group-on-body", "outside-page", "child-outside", "split-gap"):
        changed = copy.deepcopy(data)
        if mutation == "old-schema":
            changed["schema_version"] = "1.2"
        elif mutation == "missing":
            changed["callout_parts"] = []
        elif mutation == "foreign-unit":
            changed["callout_parts"][0]["unit_ids"] = ["pdf:unit-999999"]
        elif mutation == "duplicate-part":
            changed["callout_parts"].append(changed["callout_parts"][0])
        elif mutation == "reorder":
            changed["callout_parts"].reverse()
        elif mutation == "wrong-page":
            changed["callout_parts"][0]["page_number"] = 999
        elif mutation == "foreign-group":
            changed["flowables"][0]["callout_group_id"] = "pdf:callout-999999"
        elif mutation == "missing-owner":
            changed["flowables"] = [r for r in changed["flowables"] if r.get("unit_id") != units[0].unit.id]
        elif mutation == "boolean-index":
            changed["callout_parts"][0]["split_part"] = True
        elif mutation == "outside-page":
            changed["callout_parts"][0]["bounds"][0] = 900
        elif mutation == "child-outside":
            changed["callout_parts"][0]["bounds"][2] = 1
        elif mutation == "split-gap":
            changed["flowables"][0]["split_part"] = 2
        else:
            changed["flowables"][-1]["callout_group_id"] = document.callout_groups[0].id
        with pytest.raises(PdfAssemblyError):
            PdfAssemblyLayout.from_dict(changed)
    legacy = replace(layout, schema_version="1.2", callout_parts=(),
        flowables=tuple(replace(r, callout_group_id=None) for r in layout.flowables))
    assert "callout_parts" not in legacy.to_dict()
    assert all("callout_group_id" not in r for r in legacy.to_dict()["flowables"])
