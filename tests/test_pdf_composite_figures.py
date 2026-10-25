"""Composite recognition must preserve exact independent text/pixel ownership."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pdfplumber
from PIL import Image, ImageChops
import pytest

from supertranslator.pdf_extract import extract_pdf
from supertranslator.pdf_media import (
    PdfMediaError, partition_graphic_regions, render_pdf_pages,
)
from supertranslator.models import read_segments
from supertranslator.protection import restore_tokens
from tests.pdf_composite_figure_fixtures import make_composite_figure_pdf


@pytest.mark.parametrize(("frame", "font", "scale", "origin"), [
    ("rect", "Helvetica", 1.0, (0.0, 0.0)),
    ("lines", "Times-Roman", 0.8, (0.0, 0.0)),
    ("path", "Helvetica", 1.4, (0.0, 0.0)),
    ("rect", "Times-Roman", 1.4, (23.0, -31.0)),
    ("lines", "Helvetica", 0.8, (-17.0, 29.0)),
    ("path", "Times-Roman", 1.0, (19.0, 11.0)),
    ("split-lines", "Helvetica", 1.0, (0.0, 0.0)),
])
def test_native_composite_ownership_across_encodings(
    tmp_path: Path, frame: str, font: str, scale: float,
    origin: tuple[float, float],
) -> None:
    # Removing the witnessed-prose exception loses this original sentence/art.
    fixture = make_composite_figure_pdf(tmp_path / "source.pdf", frame=frame,
                                      font=font, scale=scale, origin=origin)
    with pdfplumber.open(fixture.source) as pdf:
        page = pdf.pages[0]
        partition = partition_graphic_regions(page, page_number=1)
        assert len(partition.figures) == 1
        assert partition.figures[0].bbox == pytest.approx(fixture.frame_bbox)
        box = fixture.frame_bbox
        expected_indices = {
            i for i, char in enumerate(page.chars) if char["text"].strip()
            and box[0] <= char["x0"] <= char["x1"] <= box[2]
            and box[1] <= char["top"] <= char["bottom"] <= box[3]
        }
        assert "".join(page.chars[i]["text"] for i in sorted(expected_indices)) == (
            fixture.figure_text.replace(" ", "")
        )
        owners = {
            i: [region for region in partition.figures
                if region.bbox[0] <= char["x0"] <= char["x1"] <= region.bbox[2]
                and region.bbox[1] <= char["top"] <= char["bottom"] <= region.bbox[3]]
            for i, char in enumerate(page.chars) if char["text"].strip()
        }
        assert {i for i, regions in owners.items() if regions} == expected_indices
        assert all(len(regions) <= 1 for regions in owners.values())
        assert partition.figures[0].owned_selectable_characters == len(expected_indices)


@pytest.mark.parametrize("frame", ["missing-side", "diagonal-only", "curved-only"])
def test_composite_rejects_inferred_or_broken_frame(tmp_path: Path, frame: str) -> None:
    fixture = make_composite_figure_pdf(tmp_path / "source.pdf", frame=frame)
    with pdfplumber.open(fixture.source) as pdf:
        assert pdf.pages[0].rects  # Negative mutation retained substantial artwork.
        with pytest.raises(PdfMediaError, match="cannot partition selectable prose"):
            partition_graphic_regions(pdf.pages[0], page_number=1)


@pytest.mark.parametrize("case", ["missing", "too-far", "low-overlap", "ambiguous", "cross-page"])
def test_composite_requires_unique_caption_relation(tmp_path: Path, case: str) -> None:
    fixture = make_composite_figure_pdf(tmp_path / "source.pdf", case=case)
    with pdfplumber.open(fixture.source) as pdf:
        with pytest.raises(PdfMediaError, match="cannot partition selectable prose"):
            partition_graphic_regions(pdf.pages[0], page_number=1)


def test_composite_refuses_intervening_body(tmp_path: Path) -> None:
    fixture = make_composite_figure_pdf(tmp_path / "source.pdf", case="intervening-body")
    with pdfplumber.open(fixture.source) as pdf:
        with pytest.raises(PdfMediaError, match="cannot partition selectable prose"):
            partition_graphic_regions(pdf.pages[0], page_number=1)


def test_composite_refuses_partial_glyph(tmp_path: Path) -> None:
    fixture = make_composite_figure_pdf(tmp_path / "source.pdf", case="partial-glyph")
    with pdfplumber.open(fixture.source) as pdf:
        with pytest.raises(PdfMediaError, match="partial glyph overlap"):
            partition_graphic_regions(pdf.pages[0], page_number=1)


@pytest.mark.parametrize("case", ["crossing", "wrapped-crossing"])
def test_composite_refuses_caption_crossing_frame(tmp_path: Path, case: str) -> None:
    fixture = make_composite_figure_pdf(tmp_path / "source.pdf", case=case)
    with pdfplumber.open(fixture.source) as pdf:
        with pytest.raises(PdfMediaError, match="cannot partition selectable prose"):
            partition_graphic_regions(pdf.pages[0], page_number=1)


def test_text_only_box_remains_selectable_callout(tmp_path: Path) -> None:
    fixture = make_composite_figure_pdf(tmp_path / "source.pdf", case="text-only")
    document = extract_pdf(fixture.source, tmp_path / "doc.json",
                           tmp_path / "segments.jsonl", tmp_path / "media")
    assert not [block for block in document.blocks if block.kind == "figure"]
    assert [block.source_text for block in document.blocks
            if block.semantic_role == "callout-body"] == [fixture.figure_text]


def test_split_frame_without_internal_artwork_cannot_own_prose(tmp_path: Path) -> None:
    # Counting a partial side as internal artwork would rasterize this prose.
    fixture = make_composite_figure_pdf(
        tmp_path / "source.pdf", frame="split-lines", case="no-artwork",
    )
    with pdfplumber.open(fixture.source) as pdf:
        page = pdf.pages[0]
        assert len(page.lines) == 5
        assert not page.rects and not page.curves and not page.images
        assert page.extract_text().endswith(fixture.caption_text)
        with pytest.raises(PdfMediaError, match="cannot partition selectable prose"):
            partition_graphic_regions(page, page_number=1)


@pytest.mark.parametrize("case", ["valid", "wrapped", "above"])
def test_composite_caption_and_body_have_exact_disjoint_targets(tmp_path: Path, case: str) -> None:
    fixture = make_composite_figure_pdf(tmp_path / "source.pdf", case=case)
    source_sha = hashlib.sha256(fixture.source.read_bytes()).hexdigest()
    document = extract_pdf(fixture.source, tmp_path / "doc.json",
                           tmp_path / "segments.jsonl", tmp_path / "media")
    assert document.schema_version == document.extracted_schema_version == "1.2"
    assert document.translation_units
    assert not [finding for finding in document.flow_findings if finding.severity == "required"]
    figures = [block for block in document.blocks if block.kind == "figure"]
    captions = [block for block in document.blocks if block.kind == "caption"]
    assert len(figures) == len(captions) == 1
    assert figures[0].bbox == fixture.frame_bbox
    assert figures[0].caption_id == captions[0].id
    assert captions[0].caption_id == figures[0].id
    assert captions[0].source_text == fixture.caption_text
    targets = [restore_tokens(segment.source_text, segment.protected)
               for segment in read_segments(tmp_path / "segments.jsonl")]
    assert sorted(targets) == sorted([fixture.caption_text, fixture.body_text])
    assert not any(fixture.figure_text in target for target in targets)
    block_ids = [block_id for unit in document.translation_units
                 for block_id in unit.source_block_ids]
    assert len(block_ids) == len(set(block_ids))
    target_ids = [block_id for unit in document.translation_units
                  if unit.segment_id is not None for block_id in unit.source_block_ids]
    assert figures[0].id not in target_ids
    assert sorted(target_ids) == sorted(block.id for block in document.blocks if block.source_text)
    rendered = render_pdf_pages(fixture.source, tmp_path / "independent-render", dpi=144)
    with Image.open(rendered[0]) as page, Image.open(tmp_path / figures[0].media_path) as crop:
        expected = page.crop((120, 360, 1000, 800))  # Hand-declared frame at 2 pixels/point.
        assert crop.size == expected.size
        assert ImageChops.difference(crop.convert("RGB"), expected.convert("RGB")).getbbox() is None
    assert hashlib.sha256(fixture.source.read_bytes()).hexdigest() == source_sha


def test_composite_preserves_independent_table_targets(tmp_path: Path) -> None:
    fixture = make_composite_figure_pdf(tmp_path / "source.pdf", case="outside-table")
    document = extract_pdf(fixture.source, tmp_path / "doc.json",
                           tmp_path / "segments.jsonl", tmp_path / "media")
    assert [block.bbox for block in document.blocks if block.kind == "figure"] == [fixture.frame_bbox]
    assert sorted(block.source_text for block in document.blocks if block.kind == "table-cell") == sorted(fixture.table_text)
    targets = [restore_tokens(segment.source_text, segment.protected)
               for segment in read_segments(tmp_path / "segments.jsonl")]
    assert sorted(targets) == sorted([fixture.caption_text, fixture.body_text, *fixture.table_text])
