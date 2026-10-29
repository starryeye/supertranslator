"""Source geometry proof, independent ownership, and refusal boundaries."""

from pathlib import Path

import pdfplumber
import pytest
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader, PdfWriter

from supertranslator.pdf_callouts import (
    collect_callout_pages, discover_callout_chains, match_callout_fragments,
)
from supertranslator.pdf_layout import PdfExtractionError
from supertranslator.pdf_media import source_axis_aligned_edges, _has_closed_graphic_frame
from tests.pdf_callout_fixtures import make_page_spanning_callout_pdf


@pytest.mark.parametrize(("pages", "border", "font", "scale", "origin", "mirrored"), [
    (2, "lines", "Helvetica", 1.0, (0, 0), False),
    (3, "path", "Times-Roman", 0.8, (23, -31), True),
    (2, "path", "Helvetica", 1.4, (-17, 29), True),
    (3, "lines", "Times-Roman", 1.4, (0, 0), False),
])
def test_callout_chain_native_geometry_matrix(tmp_path, pages, border, font, scale, origin, mirrored):
    # Losing a cap/side, swallowing outside glyphs, or normalizing away origin breaks this.
    fixture = make_page_spanning_callout_pdf(tmp_path / "native.pdf", pages=pages,
        border=border, font=font, scale=scale, origin=origin, mirrored=mirrored)
    with pdfplumber.open(fixture.source) as pdf:
        evidence = collect_callout_pages(pdf.pages)
        chains = discover_callout_chains(evidence)
        assert tuple(tuple(f.page_number for f in c.fragments) for c in chains) == fixture.group_pages
        assert len(chains) == 1
        for fragment, (number, box) in zip(chains[0].fragments, fixture.frame_bboxes):
            page = pdf.pages[number - 1]
            expected = tuple(i for i, char in enumerate(page.chars)
                if char["text"].strip() and box[0] <= char["x0"] <= char["x1"] <= box[2]
                and box[1] <= char["top"] <= char["bottom"] <= box[3])
            assert fragment.character_indexes == expected
            assert fragment.page_bbox == page.bbox
            assert fragment.border_bbox == pytest.approx(box)
            assert fragment.open_top == (number > 1)
            assert fragment.open_bottom == (number < pages)
            assert fragment.content_bbox != fragment.border_bbox
        owned = "".join(evidence[f.page_number - 1].characters[i]["text"]
                        for f in chains[0].fragments for i in f.character_indexes)
        assert fixture.title_texts[0].replace(" ", "") in owned
        assert owned == "".join((*fixture.title_texts, *fixture.paragraph_texts)).replace(" ", "")
        assert all(text.replace(" ", "") not in owned for text in fixture.outside_texts)


def test_callout_matching_is_global_not_greedy():
    assert match_callout_fragments({"a": ("x", "y"), "b": ("x",)}) == {"a": "y", "b": "x"}
    assert match_callout_fragments({}) == {}
    for candidates in ({"a": ()}, {"a": ("x",), "b": ("x",)},
                       {"a": ("x", "y"), "b": ("x", "y")}):
        with pytest.raises(PdfExtractionError):
            match_callout_fragments(candidates)


def test_callout_no_input():
    assert collect_callout_pages(()) == ()
    assert discover_callout_chains(()) == ()


def test_absent_direct_focus_is_contextual_extraction_error():
    # A missing focus must not leak a dictionary implementation exception.
    with pytest.raises(PdfExtractionError, match=r"(?i)focus.*7"):
        discover_callout_chains((), focus_pages=(7,))


@pytest.mark.parametrize("shift", [40, 80])
def test_unexplained_equal_width_side_shift_is_refused(tmp_path, shift):
    from tests.pdf_callout_fixtures import make_uncalibrated_callout_pdf
    source, _ = make_uncalibrated_callout_pdf(tmp_path / "shift.pdf", shift=shift)
    with pdfplumber.open(source) as pdf:
        with pytest.raises(PdfExtractionError):
            discover_callout_chains(collect_callout_pages(pdf.pages))


@pytest.mark.parametrize("case", ["insufficient-peer", "contradictory-peer", "distant-edge", "mismatched-hanging", "inline-to-hanging"])
def test_uncalibrated_source_refuses_unproven_peer_or_text_edge(tmp_path, case):
    from tests.pdf_callout_fixtures import make_uncalibrated_callout_pdf
    source, _ = make_uncalibrated_callout_pdf(tmp_path / "invalid.pdf", case=case)
    with pdfplumber.open(source) as pdf:
        with pytest.raises(PdfExtractionError):
            discover_callout_chains(collect_callout_pages(pdf.pages))


def test_physical_one_line_cannot_choose_between_two_pitch_donors(tmp_path):
    # Both peers have two measured intervals and exact direct/reflected sides.
    source = tmp_path / "ambiguous-one-line.pdf"
    canvas = Canvas(str(source), pagesize=(600, 760), invariant=1)
    for page in range(2):
        for x in ((40,) if page == 0 else (40, 360)):
            top, bottom = (650, 700) if page == 0 else (60, 460)
            canvas.line(x, 760 - top, x, 760 - bottom)
            canvas.line(x + 200, 760 - top, x + 200, 760 - bottom)
            cap = top if page == 0 else bottom
            canvas.line(x, 760 - cap, x + 200, 760 - cap)
            canvas.setFont("Helvetica", 10)
            lines = ("Measured source continues",) if page == 0 else (
                "without missing an observation", "or inventing unrelated words", "until its account is complete.")
            for n, text in enumerate(lines):
                canvas.drawString(x + 12, 760 - (691 if page == 0 else 78 + n * 14), text)
        canvas.showPage()
    canvas.save()
    with pdfplumber.open(source) as pdf:
        with pytest.raises(PdfExtractionError, match="ambiguous"):
            discover_callout_chains(collect_callout_pages(pdf.pages))


def test_callout_sparse_focus_uses_neighbors_only_as_context(tmp_path):
    # An orphan on a context page must not become an undeclared chain endpoint.
    fixture = make_page_spanning_callout_pdf(tmp_path / "pair.pdf")
    reader = PdfReader(fixture.source)
    writer = PdfWriter()
    for index in (0, 1, 0):
        writer.add_page(reader.pages[index])
    source = tmp_path / "with-context.pdf"
    with source.open("wb") as stream:
        writer.write(stream)
    with pdfplumber.open(source) as pdf:
        all_pages = collect_callout_pages(pdf.pages)
        sparse = collect_callout_pages(pdf.pages, page_numbers=(1, 2))
        assert [p.page_number for p in sparse] == [1, 2, 3]
        focused = discover_callout_chains(sparse, focus_pages=(1, 2))
        assert focused == discover_callout_chains(all_pages, focus_pages=(1, 2))
        assert [[f.page_number for f in c.fragments] for c in focused] == [[1, 2]]
        with pytest.raises(PdfExtractionError):
            discover_callout_chains(all_pages)


def test_callout_focus_keeps_all_competing_candidates(tmp_path):
    source = tmp_path / "competitors.pdf"
    canvas = Canvas(str(source), pagesize=(600, 760))
    for page in range(2):
        for x in (40, 360):
            top, bottom = (300, 700) if page == 0 else (60, 460)
            canvas.line(x, 760 - top, x, 760 - bottom)
            canvas.line(x + 200, 760 - top, x + 200, 760 - bottom)
            y = top if page == 0 else bottom
            canvas.line(x, 760 - y, x + 200, 760 - y)
            canvas.setFont("Helvetica", 10)
            for text, baseline in (("A selectable observation", 677 if page == 0 else 78),
                                   ("continues independently.", 691 if page == 0 else 92)):
                canvas.drawString(x + 12, 760 - baseline, text)
        canvas.showPage()
    canvas.save()
    with pdfplumber.open(source) as pdf:
        with pytest.raises(PdfExtractionError, match="ambiguous"):
            discover_callout_chains(collect_callout_pages(pdf.pages), focus_pages=(1, 2))


@pytest.mark.parametrize("case", ["width-mismatch", "indent-mismatch", "pitch-mismatch", "font-mismatch"])
def test_callout_flow_geometry_must_meet_pinned_tolerances(tmp_path, case):
    # Widening the .25 em/15% comparisons admits these source-incompatible ends.
    fixture = make_page_spanning_callout_pdf(tmp_path / "flow.pdf", case=case)
    with pdfplumber.open(fixture.source) as pdf:
        with pytest.raises(PdfExtractionError):
            discover_callout_chains(collect_callout_pages(pdf.pages))


def test_callout_existing_one_point_coverage_tolerance(tmp_path):
    fixture = make_page_spanning_callout_pdf(tmp_path / "tolerance.pdf", case="tolerated-gap")
    with pdfplumber.open(fixture.source) as pdf:
        assert len(discover_callout_chains(collect_callout_pages(pdf.pages))) == 1


def test_callout_list_glyphs_remain_selectable(tmp_path):
    fixture = make_page_spanning_callout_pdf(tmp_path / "list.pdf", case="list")
    with pdfplumber.open(fixture.source) as pdf:
        evidence = collect_callout_pages(pdf.pages)
        chain, = discover_callout_chains(evidence)
        text = "".join(evidence[f.page_number - 1].characters[i]["text"]
                       for f in chain.fragments for i in f.character_indexes)
        assert fixture.list_item_texts[0].replace(" ", "") in text


@pytest.mark.parametrize("case", ["crossing-path", "filled-open-path"])
def test_callout_path_ink_cannot_cross_or_fill_the_interior(tmp_path, case):
    fixture = make_page_spanning_callout_pdf(tmp_path / "path-ink.pdf", case=case, border="path")
    with pdfplumber.open(fixture.source) as pdf:
        assert pdf.pages[0].curves
        if case == "crossing-path":
            assert len(pdf.pages[0].curves) == 2
            assert pdf.pages[0].curves[1]["path"] == [
                ("m", (40, 400)), ("l", (500, 460)), ("l", (510, 480)),
            ]
        else:
            assert pdf.pages[0].curves[0]["fill"]
        with pytest.raises(PdfExtractionError, match=r"page .*bounds.*reason"):
            discover_callout_chains(collect_callout_pages(pdf.pages))


@pytest.mark.parametrize("case", ["external-below", "external-above", "mid-page"])
def test_callout_edge_proof_excludes_furniture_and_external_prose(tmp_path, case):
    fixture = make_page_spanning_callout_pdf(tmp_path / "edge.pdf", case=case)
    with pdfplumber.open(fixture.source) as pdf:
        with pytest.raises(PdfExtractionError, match=r"page .*bounds.*reason"):
            discover_callout_chains(collect_callout_pages(pdf.pages))


@pytest.mark.parametrize("case", ["gap", "diagonal-cap", "curved-cap", "missing-caps",
    "intervening-page", "competing", "grid", "artwork", "crossing-artwork", "partial-glyph", "nested", "irregular"])
def test_callout_chain_refuses_false_edges_or_competing_owners(tmp_path, case):
    fixture = make_page_spanning_callout_pdf(tmp_path / "false.pdf", case=case,
                                            pages=3 if case == "intervening-page" else 2)
    with pdfplumber.open(fixture.source) as pdf:
        assert any(p.lines or p.rects or p.curves for p in pdf.pages)
        with pytest.raises(PdfExtractionError, match=r"page .*bounds.*reason"):
            discover_callout_chains(collect_callout_pages(pdf.pages))


def test_open_path_support_does_not_relax_composite_frame_witness(tmp_path):
    source = tmp_path / "two-l.pdf"
    canvas = Canvas(str(source), pagesize=(300, 400))
    for points in (((40, 100), (40, 300), (240, 300)),
                   ((240, 300), (240, 100), (40, 100))):
        path = canvas.beginPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        canvas.drawPath(path)
    canvas.save()
    with pdfplumber.open(source) as pdf:
        page = pdf.pages[0]
        assert len(source_axis_aligned_edges(page)) == 4
        assert not _has_closed_graphic_frame(page, (40, 100, 240, 300))
