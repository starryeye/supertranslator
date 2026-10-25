"""Shared caption recognition and unique geometric matching contracts."""

from __future__ import annotations

import pytest

from supertranslator.pdf_layout import (
    PdfExtractionError,
    is_explicit_figure_caption,
    match_figure_caption_bounds,
    pair_figure_captions,
)
from supertranslator.pdf_models import PdfBlock, PdfBlockStyle


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Figure 2-1. A chart", True),
        ("Fig. 3", True),
        ("  fIgUrE 12. A chart", True),
        ("FIG. 4", True),
        ("Example 2-1", False),
        ("See Figure 2", False),
        ("Figure abc", False),
        ("Figure 2abc", False),
        ("", False),
    ],
)
def test_explicit_caption_marker_preserves_existing_syntax(
    text: str, expected: bool,
) -> None:
    assert is_explicit_figure_caption(text) is expected


def test_caption_match_preserves_existing_bounds() -> None:
    figures = {"f": (1, (0.0, 0.0, 100.0, 100.0))}
    captions = {"c": (1, (0.0, 110.0, 100.0, 122.0))}
    assert match_figure_caption_bounds(figures, captions) == {"c": "f"}


@pytest.mark.parametrize(
    "caption_bbox",
    [
        (0.0, 136.0, 100.0, 148.0),
        (0.0, -48.0, 100.0, -36.0),
        (75.0, 110.0, 175.0, 122.0),
        (75.0, 136.0, 175.0, 148.0),
    ],
)
def test_caption_match_includes_distance_and_overlap_boundaries(
    caption_bbox: tuple[float, float, float, float],
) -> None:
    assert match_figure_caption_bounds(
        {"f": (1, (0.0, 0.0, 100.0, 100.0))}, {"c": (1, caption_bbox)},
    ) == {"c": "f"}


@pytest.mark.parametrize(
    "caption_bbox",
    [
        (0.0, 136.001, 100.0, 148.001),
        (0.0, -48.001, 100.0, -36.001),
        (75.001, 110.0, 175.001, 122.0),
    ],
)
def test_caption_match_refuses_just_outside_existing_boundaries(
    caption_bbox: tuple[float, float, float, float],
) -> None:
    with pytest.raises(PdfExtractionError, match="^orphan figure-caption evidence: c$"):
        match_figure_caption_bounds(
            {"f": (1, (0.0, 0.0, 100.0, 100.0))}, {"c": (1, caption_bbox)},
        )


def test_caption_match_never_crosses_source_pages() -> None:
    with pytest.raises(PdfExtractionError, match="^orphan figure-caption evidence: c$"):
        match_figure_caption_bounds(
            {"f": (1, (0.0, 0.0, 100.0, 100.0))},
            {"c": (2, (0.0, 110.0, 100.0, 122.0))},
        )


def test_caption_match_reports_sorted_orphans_without_figures() -> None:
    with pytest.raises(
        PdfExtractionError, match="^orphan figure-caption evidence: a, z$",
    ):
        match_figure_caption_bounds({}, {
            "z": (1, (0.0, 110.0, 100.0, 122.0)),
            "a": (1, (0.0, 110.0, 100.0, 122.0)),
        })


@pytest.mark.parametrize("figure_count", [1, 2])
def test_caption_match_refuses_incomplete_or_nonunique_graph(figure_count: int) -> None:
    with pytest.raises(
        PdfExtractionError, match="^ambiguous figure-caption pairing for a$",
    ):
        match_figure_caption_bounds(
            {f"f{index}": (1, (0.0, 0.0, 100.0, 100.0))
             for index in range(figure_count)},
            {"z": (1, (0.0, 110.0, 100.0, 122.0)),
             "a": (1, (0.0, 110.0, 100.0, 122.0))},
        )


def test_caption_match_uses_unique_complete_graph_not_nearest_first() -> None:
    figures = {
        "f1": (1, (0.0, 0.0, 100.0, 100.0)),
        "f2": (1, (0.0, 130.0, 100.0, 230.0)),
    }
    captions = {
        "c1": (1, (0.0, 120.0, 100.0, 130.0)),
        "c2": (1, (0.0, 235.0, 100.0, 245.0)),
    }
    # c1 is nearest f2, but only f1 leaves f2 available for c2.
    assert match_figure_caption_bounds(figures, captions) == {"c1": "f1", "c2": "f2"}


@pytest.mark.parametrize("figures", [{}, {"f": (1, (0.0, 0.0, 100.0, 100.0))}])
def test_caption_match_without_captions_is_empty(figures: dict) -> None:
    assert match_figure_caption_bounds(figures, {}) == {}


def test_pairing_preserves_full_block_dictionaries_and_uncaptioned_figure() -> None:
    style = PdfBlockStyle(10.0, False, "left", 0.0, 0.0)
    blocks = [
        PdfBlock(
            id="pdf:page-0001:block-0001", page_number=1, order=0,
            kind="figure", bbox=(0.0, 0.0, 100.0, 100.0), style=style,
            media_path="media/figure-0001.png",
        ),
        PdfBlock(
            id="pdf:page-0001:block-0002", page_number=1, order=1,
            kind="caption", bbox=(0.0, 110.0, 100.0, 134.0), style=style,
            source_text="Figure 1. Measurements under controlled conditions show "
            "the changing rate across the complete observation period.",
            segment_id="pdf:page-0001:block-0002",
        ),
        PdfBlock(
            id="pdf:page-0001:block-0003", page_number=1, order=2,
            kind="figure", bbox=(200.0, 300.0, 300.0, 400.0), style=style,
            media_path="media/figure-0002.png",
        ),
    ]
    expected = [
        {
            "id": "pdf:page-0001:block-0001", "page_number": 1, "order": 0,
            "kind": "figure", "bbox": [0.0, 0.0, 100.0, 100.0],
            "media_path": "media/figure-0001.png",
            "source_text": "", "segment_id": None,
            "caption_id": "pdf:page-0001:block-0002",
        },
        {
            "id": "pdf:page-0001:block-0002", "page_number": 1, "order": 1,
            "kind": "caption", "bbox": [0.0, 110.0, 100.0, 134.0],
            "media_path": None,
            "source_text": "Figure 1. Measurements under controlled conditions show "
            "the changing rate across the complete observation period.",
            "segment_id": "pdf:page-0001:block-0002",
            "caption_id": "pdf:page-0001:block-0001",
        },
        {
            "id": "pdf:page-0001:block-0003", "page_number": 1, "order": 2,
            "kind": "figure", "bbox": [200.0, 300.0, 300.0, 400.0],
            "media_path": "media/figure-0002.png",
            "source_text": "", "segment_id": None, "caption_id": None,
        },
    ]
    for item in expected:
        item.update({
            "style": {"font_size": 10.0, "bold": False, "alignment": "left",
                      "indentation": 0.0, "space_after": 0.0},
            "semantic_role": "body", "continuation_of": None,
            "table_id": None, "row": None, "column": None,
            "row_span": 1, "column_span": 1, "uri": None, "destination": None,
        })

    assert [block.to_dict() for block in pair_figure_captions(blocks)] == expected
    assert blocks[0].caption_id is None
