"""Native selectable ownership of source-proven multi-page callouts."""

from hashlib import sha256
from io import BytesIO
from dataclasses import replace

import pdfplumber
import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from supertranslator.pdf_extract import extract_pdf
from tests.pdf_callout_fixtures import make_page_spanning_callout_pdf


@pytest.mark.parametrize("shift,scale,origin,rotation", [
    (0, 1.0, (0, 0), 0), (60, 1.0, (0, 0), 0),
    (60, .8, (23, -31), 90), (0, 1.4, (-17, 29), 270),
])
def test_side_correspondence_preserves_independent_source_ownership(tmp_path, shift, scale, origin, rotation):
    from pypdf import Transformation
    from pypdf.generic import RectangleObject
    from supertranslator.pdf_callout_validation import validate_callout_source
    from supertranslator.pdf_extract import logical_pdf_bytes
    from tests.pdf_callout_fixtures import make_uncalibrated_callout_pdf
    source, expected = make_uncalibrated_callout_pdf(tmp_path / "source.pdf", shift=shift)
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(source))
    ox, oy = origin
    for page in writer.pages:
        page.add_transformation(Transformation().scale(scale).translate(ox, oy))
        page.mediabox = RectangleObject((ox, oy, ox + 600 * scale, oy + 760 * scale))
        page.cropbox = RectangleObject(page.mediabox)
        page.rotate(rotation)
    with source.open("wb") as stream:
        writer.write(stream)
    original = source.read_bytes()
    document = extract_pdf(source, tmp_path / "document.json", tmp_path / "segments.jsonl", tmp_path / "media")
    validate_callout_source(document, source_pdf_bytes=original)
    group, = document.callout_groups
    assert [f.page_number for f in group.fragments] == [1, 2]
    with pdfplumber.open(BytesIO(logical_pdf_bytes(original))) as pdf:
        owned_text = []
        for index, fragment in enumerate(group.fragments):
            x = 60 + (shift if index else 0)
            top, bottom = (300, 700) if index == 0 else (60, 460)
            box = (ox + x * scale, -oy + top * scale, ox + (x + 420) * scale, -oy + bottom * scale)
            assert fragment.border_bbox == pytest.approx(box)
            indexes = tuple(i for i, c in enumerate(pdf.pages[index].chars)
                            if c["text"].strip() and box[0] <= c["x0"] <= c["x1"] <= box[2]
                            and box[1] <= c["top"] <= c["bottom"] <= box[3])
            assert fragment.character_indexes == indexes
            owned_text.extend(pdf.pages[index].chars[i]["text"] for i in indexes)
    assert "".join(owned_text) == expected.replace(" ", "")
    assert source.read_bytes() == original


def test_grouped_source_keeps_genuine_closed_legacy_callout(tmp_path):
    from tests.test_pdf_callout_units import _continued_source
    from supertranslator.pdf_callout_validation import validate_callout_source
    source, _ = _continued_source(tmp_path / "chain.pdf")
    closed = BytesIO()
    canvas = Canvas(closed, pagesize=(600, 760), invariant=1)
    canvas.rect(60, 400, 420, 180)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(75, 555, "Independent closed box")
    canvas.setFont("Helvetica", 10)
    canvas.drawString(75, 530, "A complete legacy observation stays in its own closed frame.")
    canvas.drawString(75, 516, "Its separate ownership does not require a spanning group.")
    canvas.save()
    writer = PdfWriter()
    writer.append(PdfReader(source))
    writer.append(PdfReader(closed))
    with source.open("wb") as stream:
        writer.write(stream)
    document = extract_pdf(source, tmp_path / "document.json", tmp_path / "segments.jsonl", tmp_path / "media")
    assert len(document.callout_groups) == 1
    legacy = [b for b in document.blocks if b.page_number == 3]
    assert [b.semantic_role for b in legacy] == ["callout-title", "callout-body"]
    assert all(b.id not in f.source_block_ids for b in legacy for f in document.callout_groups[0].fragments)
    validate_callout_source(document, source_pdf_bytes=source.read_bytes())


@pytest.mark.parametrize("case", ["paragraph", "list"])
@pytest.mark.parametrize("pages,border,scale,origin,mirrored", [
    (2, "lines", 1.0, (0, 0), False),
    (3, "path", 0.8, (23, -31), True),
    (2, "path", 1.4, (-17, 29), True),
])
def test_native_callout_chain_extracts_exact_selectable_targets(
    tmp_path, case, pages, border, scale, origin, mirrored,
):
    # Missing routing must fail at extraction, not silently rasterize source prose.
    fixture = make_page_spanning_callout_pdf(tmp_path / "source.pdf", case=case,
        pages=pages, border=border, scale=scale, origin=origin, mirrored=mirrored)
    document = extract_pdf(fixture.source, tmp_path / "document.json",
                           tmp_path / "segments.jsonl", tmp_path / "media")
    assert document.schema_version == document.extracted_schema_version == "1.3"
    group, = document.callout_groups
    assert group.id == "pdf:callout-000001"
    assert tuple(f.page_number for f in group.fragments) == tuple(range(1, pages + 1))
    if pages == 2:
        assert [f.source_block_ids for f in group.fragments] == [
            ("pdf:page-0001:block-0003", "pdf:page-0001:block-0004"),
            ("pdf:page-0002:block-0002",)]
    members = {identifier for f in group.fragments for identifier in f.source_block_ids}
    blocks = [b for b in document.blocks if b.id in members]
    first = ("1. Record the initial chamber reading and retain the continuing observation."
             if case == "list" else
             "The copper chamber retains a steady signal while each measured interval remains selectable.")
    continuation = "The returning signal reaches the second chamber and provides an independent observation."
    middle_first = "The copper chamber retains a steady signal while each measured interval remains selectable."
    expected = ["Measured observations", first]
    if pages == 3:
        expected.extend([continuation, middle_first])
    expected.append(continuation)
    assert [b.source_text for b in blocks] == expected
    assert [b.kind for b in blocks] == ["heading", "list-item" if case == "list" else "paragraph", *(["paragraph"] * (len(expected) - 2))]
    assert [b.semantic_role for b in blocks] == ["callout-title", *(["callout-body"] * (len(expected) - 1))]
    assert [identifier for unit in document.translation_units
            for identifier in unit.source_block_ids if identifier in members] == [b.id for b in blocks]
    assert all(b.segment_id and b.continuation_of is None for b in blocks)
    assert len({b.segment_id for b in blocks}) == len(blocks)
    with pdfplumber.open(fixture.source) as pdf:
        for fragment, (_, box) in zip(group.fragments, fixture.frame_bboxes):
            page = pdf.pages[fragment.page_number - 1]
            assert fragment.page_bbox == page.bbox
            assert fragment.border_bbox == pytest.approx(box)
            assert fragment.character_indexes == tuple(i for i, c in enumerate(page.chars)
                if c["text"].strip() and box[0] <= c["x0"] <= c["x1"] <= box[2]
                and box[1] <= c["top"] <= c["bottom"] <= box[3])
    assert not any(b.kind in {"table-cell", "figure"} for b in document.blocks)
    outside = [b.source_text for b in document.blocks if b.id not in members]
    assert outside.count(fixture.outside_texts[0]) == 2
    if pages == 3:
        assert outside.count("Outside") == 1
    assert not list((tmp_path / "media").glob("*.png"))


def test_callout_does_not_claim_independent_table_figure_or_furniture(tmp_path):
    fixture = make_page_spanning_callout_pdf(tmp_path / "source.pdf")
    overlay = BytesIO()
    canvas = Canvas(overlay, pagesize=(600, 760))
    for x in (500, 540, 580):
        canvas.line(x, 600, x, 660)
    for y in (600, 620, 640, 660):
        canvas.line(500, y, 580, y)
    canvas.setFont("Helvetica", 6)
    for index, (left, right) in enumerate((("Key", "Value"), ("Alpha", "12"), ("Beta", "24"))):
        canvas.drawString(503, 648 - index * 20, left)
        canvas.drawString(543, 648 - index * 20, right)
    canvas.rect(500, 350, 80, 100)
    canvas.line(500, 350, 580, 450)
    canvas.save()
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(fixture.source))
    writer.pages[0].merge_page(PdfReader(overlay).pages[0])
    with fixture.source.open("wb") as stream:
        writer.write(stream)
    document = extract_pdf(fixture.source, tmp_path / "document.json",
                           tmp_path / "segments.jsonl", tmp_path / "media")
    group, = document.callout_groups
    members = {identifier for fragment in group.fragments for identifier in fragment.source_block_ids}
    outside = [b for b in document.blocks if b.id not in members]
    assert [b.source_text for b in outside if b.kind == "table-cell"] == ["Key", "Value", "Alpha", "12", "Beta", "24"]
    figure, = [b for b in outside if b.kind == "figure"]
    assert figure.bbox == (500, 310, 580, 410)
    assert (tmp_path / figure.media_path).is_file()
    assert len(list((tmp_path / "media").glob("*.png"))) == 1
    assert [b.source_text for b in outside].count(fixture.outside_texts[0]) == 2
    assert len([b for b in outside if b.kind == "header"]) == 2
    assert len([b for b in outside if b.kind == "footer"]) == 2


@pytest.mark.parametrize("case", ["partial-glyph", "grid", "artwork", "crossing-artwork", "nested", "irregular"])
def test_native_callout_rejects_conflicting_source_ownership(tmp_path, case):
    from supertranslator.pdf_layout import PdfExtractionError
    fixture = make_page_spanning_callout_pdf(tmp_path / "source.pdf", case=case)
    with pytest.raises(PdfExtractionError, match="callout page .*bounds .*reason"):
        extract_pdf(fixture.source, tmp_path / "document.json",
                    tmp_path / "segments.jsonl", tmp_path / "media")
    assert not (tmp_path / "document.json").exists()


def test_callout_role_alone_cannot_enable_list_continuation(tmp_path):
    # A semantic label alone is not geometry proof of list ownership.
    from supertranslator.pdf_layout import build_text_blocks, group_words_into_lines
    fixture = make_page_spanning_callout_pdf(tmp_path / "source.pdf", case="list")
    with pdfplumber.open(fixture.source) as pdf:
        lines = group_words_into_lines(pdf.pages[0].extract_words(
            return_chars=True, extra_attrs=["fontname", "size"]))
    selected = [line for line in lines if 660 < line.top < 700]
    first, second = selected
    unproven = [replace(first, kind="list-item", semantic_role="callout-body"),
                replace(second, kind="paragraph", semantic_role="callout-body")]
    assert [b.source_text for b in build_text_blocks(unproven, 1)] == [
        "1. Record the initial chamber reading", "and retain the continuing observation."]


@pytest.mark.parametrize("mutation", ["missing-member", "changed-text", "duplicate-member", "duplicate-chain"])
def test_callout_binding_requires_exact_physical_glyph_owners(tmp_path, mutation):
    from supertranslator.pdf_callouts import (
        bind_callout_groups, collect_callout_pages, discover_callout_chains,
    )
    from supertranslator.pdf_layout import PdfExtractionError
    fixture = make_page_spanning_callout_pdf(tmp_path / "source.pdf")
    document = extract_pdf(fixture.source, tmp_path / "document.json",
                           tmp_path / "segments.jsonl", tmp_path / "media")
    with pdfplumber.open(fixture.source) as pdf:
        evidence = collect_callout_pages(pdf.pages)
    chains = discover_callout_chains(evidence)
    blocks = list(document.blocks)
    owner = next(b for b in blocks if b.semantic_role == "callout-title")
    if mutation == "missing-member":
        blocks.remove(owner)
    elif mutation == "changed-text":
        blocks = [replace(b, source_text=b.source_text + " lost") if b == owner else b for b in blocks]
    elif mutation == "duplicate-member":
        blocks.append(owner)
    else:
        chains = (*chains, *chains)
    with pytest.raises(PdfExtractionError, match="callout page .*bounds .*reason"):
        bind_callout_groups(chains, blocks, {p.page_number: p for p in evidence})


def test_callout_equivalent_split_paths_do_not_become_artwork(tmp_path):
    # Two actual L-shaped source paths together prove each open fragment.
    source = tmp_path / "split-paths.pdf"
    canvas = Canvas(str(source), pagesize=(600, 760))
    expected = []
    for index in range(2):
        top, bottom = (300, 700) if index == 0 else (60, 460)
        cap = top if index == 0 else bottom
        for x in (60, 480):
            path = canvas.beginPath()
            path.moveTo(x, 760 - (bottom if index == 0 else top))
            path.lineTo(x, 760 - cap)
            path.lineTo(270, 760 - cap)
            canvas.drawPath(path)
        canvas.setFont("Helvetica", 10)
        texts = ("The first selectable observation remains native.",
                 "A separate measured line confirms source ownership.")
        ys = (677, 691) if index == 0 else (78, 92)
        for text, y in zip(texts, ys):
            canvas.drawString(75, 760 - y, text)
        expected.append(" ".join(texts))
        canvas.showPage()
    canvas.save()
    document = extract_pdf(source, tmp_path / "document.json",
                           tmp_path / "segments.jsonl", tmp_path / "media")
    assert len(document.callout_groups) == 1
    assert [b.source_text for b in document.blocks] == expected
    assert all(b.kind == "paragraph" and b.segment_id for b in document.blocks)
    assert not list((tmp_path / "media").glob("*.png"))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("origin", [(23, -31), (-17, 29)])
def test_callout_source_projection_matches_extraction(tmp_path, rotation, origin):
    # A separate projection or origin normalization loses the original glyph indexes.
    from supertranslator.pdf_extract import logical_pdf_bytes
    fixture = make_page_spanning_callout_pdf(tmp_path / "source.pdf", origin=origin)
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(fixture.source))
    for page in writer.pages:
        page.rotate(rotation)
    with fixture.source.open("wb") as stream:
        writer.write(stream)
    before = fixture.source.read_bytes()
    digest = sha256(before).hexdigest()
    projected = logical_pdf_bytes(before)
    assert all(page.rotation == 0 for page in PdfReader(BytesIO(projected)).pages)
    if rotation == 0:
        assert projected == before
    document = extract_pdf(fixture.source, tmp_path / "document.json",
                           tmp_path / "segments.jsonl", tmp_path / "media")
    assert document.source_sha256 == sha256(fixture.source.read_bytes()).hexdigest() == digest
    with pdfplumber.open(BytesIO(projected)) as pdf:
        for fragment, (_, border) in zip(document.callout_groups[0].fragments, fixture.frame_bboxes):
            page = pdf.pages[fragment.page_number - 1]
            assert fragment.page_bbox == page.bbox == (origin[0], -origin[1], origin[0] + 600, -origin[1] + 760)
            assert fragment.border_bbox == border
            assert fragment.character_indexes == tuple(i for i, c in enumerate(page.chars)
                if c["text"].strip() and border[0] <= c["x0"] <= c["x1"] <= border[2]
                and border[1] <= c["top"] <= c["bottom"] <= border[3])
