"""Conservative selectable-text callout chains proven from source geometry.

Evidence here confers no extraction assignment or publication permission.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from statistics import median
from types import SimpleNamespace

from supertranslator.pdf_layout import (
    PdfExtractionError, PdfLine, _character_bbox, _character_fully_inside_bbox,
    _find_caption_matching, classify_document_lines, group_words_into_lines, split_list_marker,
)
from supertranslator.pdf_media import (
    _box_sides, _curve_has_interior_artwork, _object_bbox, _straight_path_edges,
    source_axis_aligned_edges,
)
from supertranslator.pdf_models import BBox, PdfBlock
from supertranslator.pdf_callout_models import PdfCalloutFragment, PdfCalloutGroup


@dataclass(frozen=True, slots=True)
class PdfCalloutPageEvidence:
    page_number: int
    page_bbox: BBox
    words: tuple[Mapping[str, object], ...]
    lines: tuple[PdfLine, ...]
    characters: tuple[Mapping[str, object], ...]
    primitives: Mapping[str, tuple[Mapping[str, object], ...]]


@dataclass(frozen=True, slots=True)
class PdfCalloutFragmentEvidence:
    page_number: int
    page_bbox: BBox
    border_bbox: BBox
    content_bbox: BBox
    open_top: bool
    open_bottom: bool
    character_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PdfCalloutChainEvidence:
    id: str
    fragments: tuple[PdfCalloutFragmentEvidence, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    fragment: PdfCalloutFragmentEvidence
    em: float
    pitch: float | None
    intervals: tuple[float, ...]
    indents: tuple[float, ...]
    open_edge_distances: tuple[float, ...]


def collect_callout_pages(
    pages: Sequence[object], *, page_numbers: Sequence[int] | None = None,
) -> tuple[PdfCalloutPageEvidence, ...]:
    """Retain raw source evidence; optional selection includes physical neighbors.

    Neighbors calibrate furniture only; discovery's focus controls endpoints.
    """
    selected = None if page_numbers is None else {
        neighbor for number in page_numbers for neighbor in (number - 1, number, number + 1)
    }
    result = []
    for index, page in enumerate(pages, 1):
        number = int(getattr(page, "page_number", index))
        if selected is not None and number not in selected:
            continue
        words = tuple(page.extract_words(return_chars=True, extra_attrs=["fontname", "size"]))
        box = tuple(float(value) for value in page.bbox)
        result.append(PdfCalloutPageEvidence(
            number, box, words, tuple(group_words_into_lines(words)),
            tuple(page.chars), {key: tuple(getattr(page, key, ()))
                                for key in ("images", "lines", "rects", "curves")},
        ))
    return tuple(result)


def match_callout_fragments(candidates: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """Require one complete unique assignment using the shared matching engine."""
    matching = _find_caption_matching(candidates)
    if matching is None or any(
        _find_caption_matching(candidates, forbidden=edge) is not None
        for edge in matching.items()
    ):
        raise PdfExtractionError("unproven callout chain: missing or ambiguous whole matching")
    return matching


def _fail(page: PdfCalloutPageEvidence, box: BBox, reason: str) -> None:
    raise PdfExtractionError(f"callout page {page.page_number} bounds {box}: reason {reason}")


def _inside(inner: BBox, outer: BBox) -> bool:
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


def _intersects(a: BBox, b: BBox) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _union(boxes: Sequence[BBox]) -> BBox:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _covered(side: BBox, edges: Sequence[BBox]) -> bool:
    horizontal = side[1] == side[3]
    axis, fixed = (0, 1) if horizontal else (1, 0)
    intervals = sorted((e[axis], e[axis + 2]) for e in edges
        if abs(e[fixed] - side[fixed]) <= 1.0
        and abs(e[fixed + 2] - side[fixed]) <= 1.0)
    end = side[axis]
    for start, stop in intervals:
        if start > end + 1.0:
            break
        end = max(end, stop)
    return end >= side[axis + 2] - 1.0


def _furniture_lines(page: PdfCalloutPageEvidence,
                     by_number: Mapping[int, PdfCalloutPageEvidence]) -> tuple[PdfLine, ...]:
    # Always the same immediate physical window, never the sparse input order.
    window = []
    for number in (page.page_number - 1, page.page_number, page.page_number + 1):
        peer = by_number.get(number)
        if peer is None:
            window.append(([], 1.0))
            continue
        x0, top, x1, bottom = peer.page_bbox
        lines = [replace(line, words=tuple(replace(word,
            x0=word.x0 - x0, x1=word.x1 - x0,
            top=word.top - top, bottom=word.bottom - top) for word in line.words),
            page_width=x1 - x0, page_height=bottom - top) for line in peer.lines]
        window.append((lines, bottom - top))
    classified = classify_document_lines(window)[1]
    return tuple(line for line, local in zip(page.lines, classified)
                 if local.kind not in {"header", "footer", "page-number"})


def _vertical_runs(edges: Sequence[BBox]) -> tuple[BBox, ...]:
    by_x = defaultdict(list)
    for x0, top, x1, bottom in edges:
        if x0 == x1 and bottom > top:
            by_x[x0].append((top, bottom))
    result = []
    for x, intervals in sorted(by_x.items()):
        top, bottom = sorted(intervals)[0]
        for start, stop in sorted(intervals)[1:]:
            if start <= bottom + 1.0:
                bottom = max(bottom, stop)
            else:
                result.append((x, top, x, bottom))
                top, bottom = start, stop
        result.append((x, top, x, bottom))
    return tuple(result)


def _candidates(page: PdfCalloutPageEvidence,
                by_number: Mapping[int, PdfCalloutPageEvidence]) -> tuple[_Candidate, ...]:
    primitive_page = SimpleNamespace(**page.primitives)
    edges = source_axis_aligned_edges(primitive_page)
    runs = _vertical_runs(edges)
    non_furniture = _furniture_lines(page, by_number)
    result = []
    for index, left in enumerate(runs):
        for right in runs[index + 1:]:
            if left[0] >= right[0] or abs(left[1] - right[1]) > 1 or abs(left[3] - right[3]) > 1:
                continue
            if any(left[0] < middle[0] < right[0]
                   and abs(left[1] - middle[1]) <= 1
                   and abs(left[3] - middle[3]) <= 1 for middle in runs):
                continue  # Do not invent an enclosing box across peer side pairs.
            box = (left[0], min(left[1], right[1]), right[0], max(left[3], right[3]))
            owned_lines = [line for line in page.lines
                           if _inside((line.x0, line.top, line.x1, line.bottom), box)]
            if not owned_lines:
                continue
            open_top = not _covered((box[0], box[1], box[2], box[1]), edges)
            open_bottom = not _covered((box[0], box[3], box[2], box[3]), edges)
            if not open_top and not open_bottom:
                continue  # Existing single-page support remains the sole owner.
            if not _inside(box, page.page_bbox):
                _fail(page, box, "border outside actual page")
            indexes = []
            glyph_boxes = []
            for char_index, char in enumerate(page.characters):
                if not str(char.get("text", "")).strip():
                    continue
                char_box = _character_bbox(char)
                if char_box is not None and _intersects(char_box, box):
                    if not _character_fully_inside_bbox(char, box):
                        _fail(page, box, "partial glyph overlap")
                    indexes.append(char_index)
                    glyph_boxes.append(char_box)
            if not indexes:
                continue
            content = _union(glyph_boxes)
            # All ink inside the proposed text-only container must be perimeter.
            sides = _box_sides(box)
            def on_border(ink):
                return any(_inside(ink, (s[0] - 1, s[1] - 1, s[2] + 1, s[3] + 1)) for s in sides)
            for kind in ("images", "rects", "lines"):
                for item in page.primitives[kind]:
                    ink = _object_bbox(item)
                    touches_interior = ink is not None and (
                        _intersects(ink, box) or _inside(ink, box))
                    if touches_interior and not on_border(ink):
                        _fail(page, box, "interior artwork, nested border, or grid")
            for item in page.primitives["curves"]:
                ink = _object_bbox(item)
                if (ink is not None and _intersects(ink, box)
                        and (item.get("fill")
                             or _curve_has_interior_artwork(item, box)
                             or any(_intersects(segment, box) and not on_border(segment)
                                    for segment in _straight_path_edges(item))
                             or not item.get("path")
                             or any(c[0] not in {"m", "l", "h"} for c in item["path"]))):
                    _fail(page, box, "curved or irregular container/artwork")
            sizes = [word.size for line in owned_lines if not line.is_heading for word in line.words]
            if not sizes:
                _fail(page, box, "no observed body text")
            em = median(sizes)
            body = sorted((line for line in owned_lines if not line.is_heading
                           and abs(line.size - em) <= em * .15), key=lambda line: line.top)
            gaps = [b.top - a.top for a, b in zip(body, body[1:]) if 0 < b.top - a.top <= em * 2]
            if not gaps and len(body) != 1:
                _fail(page, box, "insufficient observed body-line pitch")
            pitch = median(gaps) if gaps else None
            # Border-owned text cannot turn into furniture merely by repeating.
            column = [line for line in page.lines if line.x0 < box[2] and line.x1 > box[0]
                      and (line in non_furniture or line in owned_lines)]
            edge_distances = []
            for is_open, border_edge, content_edge, is_top in (
                (open_top, box[1], content[1], True),
                (open_bottom, box[3], content[3], False),
            ):
                if not is_open:
                    continue
                edge = min(line.top for line in column) if is_top else max(line.bottom for line in column)
                edge_distances.append(abs(border_edge - edge))
                if ((pitch is not None and abs(border_edge - edge) > 1.5 * pitch)
                        or abs(content_edge - edge) > 1e-6):
                    _fail(page, box, "opening not at column non-furniture edge or intervening prose")
                # No text may run outside the actual source side extent.
                if (is_top and content_edge < border_edge) or (not is_top and content_edge > border_edge):
                    _fail(page, box, "open glyph bounds exceed source sides")
            fragment = PdfCalloutFragmentEvidence(page.page_number, page.page_bbox,
                box, content, open_top, open_bottom, tuple(indexes))
            indents = []
            for index, line in enumerate(body):
                edge = line.x0
                marker = split_list_marker(line.text)
                if marker is not None:
                    if len(line.words) < 2 or line.words[0].text != marker[0]:
                        _fail(page, box, "missing list marker/body word ownership")
                    following = body[index + 1] if index + 1 < len(body) else None
                    # An inline item continues at its marker margin; a hanging
                    # item continues at its positively observed first body word.
                    if (following is None or split_list_marker(following.text) is not None
                            or abs(following.x0 - line.x0) > em * .25):
                        edge = line.words[1].x0
                indents.append(edge - box[0])
            result.append(_Candidate(fragment, em, pitch, tuple(gaps),
                                     tuple(indents), tuple(edge_distances)))
    for i, candidate in enumerate(result):
        if any(set(candidate.fragment.character_indexes) & set(peer.fragment.character_indexes)
               for peer in result[i + 1:]):
            _fail(page, candidate.fragment.border_bbox, "competing glyph owners")
    return tuple(result)


def _compatible(left: _Candidate, right: _Candidate) -> bool:
    a, b = left.fragment, right.fragment
    aw, bw = a.page_bbox[2] - a.page_bbox[0], b.page_bbox[2] - b.page_bbox[0]
    # Normalize widths into the observed body's point scale, not page position.
    width_delta = abs((a.border_bbox[2] - a.border_bbox[0]) / aw
                      - (b.border_bbox[2] - b.border_bbox[0]) / bw) * max(aw, bw)
    em = max(left.em, right.em)
    a_sides = ((a.border_bbox[0] - a.page_bbox[0]) / aw,
               (a.border_bbox[2] - a.page_bbox[0]) / aw)
    b_sides = ((b.border_bbox[0] - b.page_bbox[0]) / bw,
               (b.border_bbox[2] - b.page_bbox[0]) / bw)
    tolerance = .25 * max(left.em / aw, right.em / bw)
    placed = any(all(abs(x - y) <= tolerance for x, y in zip(a_sides, sides))
                 for sides in (b_sides, (1 - b_sides[1], 1 - b_sides[0])))
    if not (b.page_number == a.page_number + 1 and a.open_bottom and b.open_top
            and placed
            and width_delta <= .25 * em
            and any(abs(x - y) <= .25 * em for x in left.indents for y in right.indents)
            and abs(left.em - right.em) <= em * .15):
        return False
    pitches = []
    for candidate, peer in ((left, right), (right, left)):
        pitch = candidate.pitch
        if pitch is None:
            if (peer.pitch is None or len(peer.intervals) < 2 or any(
                    abs(interval - peer.pitch) > peer.em * .15 for interval in peer.intervals)):
                return False
            page, other = candidate.fragment.page_bbox, peer.fragment.page_bbox
            pitch = peer.pitch * (page[3] - page[1]) / (other[3] - other[1])
        if any(distance > 1.5 * pitch for distance in candidate.open_edge_distances):
            return False
        pitches.append(pitch)
    return abs(pitches[0] - pitches[1]) <= max(pitches) * .15


def discover_callout_chains(
    pages: Sequence[PdfCalloutPageEvidence], *, focus_pages: Sequence[int] | None = None,
) -> tuple[PdfCalloutChainEvidence, ...]:
    """Prove complete consecutive chains, refusing every uncertain focus fragment."""
    by_number = {page.page_number: page for page in pages}
    if len(by_number) != len(pages):
        raise PdfExtractionError("duplicate callout page evidence")
    focus = set(by_number) if focus_pages is None else set(focus_pages)
    if not focus.issubset(by_number):
        raise PdfExtractionError(f"callout focus page absent from evidence: {sorted(focus - set(by_number))}")
    candidates = [candidate for number in sorted(focus)
                  for candidate in _candidates(by_number[number], by_number)]
    by_id = {str(index): candidate for index, candidate in enumerate(candidates)}
    graph = {key: tuple(other for other, target in by_id.items() if _compatible(candidate, target))
             for key, candidate in by_id.items() if candidate.fragment.open_bottom}
    try:
        matching = match_callout_fragments(graph)
    except PdfExtractionError as exc:
        if candidates:
            first = candidates[0].fragment
            _fail(by_number[first.page_number], first.border_bbox, str(exc))
        raise
    incoming = set(matching.values())
    for key, candidate in by_id.items():
        if candidate.fragment.open_top != (key in incoming):
            _fail(by_number[candidate.fragment.page_number], candidate.fragment.border_bbox,
                  "missing start/end cap or unmatched continuation")
    chains = []
    for key, candidate in by_id.items():
        if candidate.fragment.open_top:
            continue
        fragments = [candidate.fragment]
        while key in matching:
            key = matching[key]
            fragments.append(by_id[key].fragment)
        if len(fragments) < 2 or fragments[-1].open_bottom:
            _fail(by_number[fragments[0].page_number], fragments[0].border_bbox, "incomplete chain")
        chains.append(PdfCalloutChainEvidence(f"pdf:callout-{len(chains) + 1:06d}", tuple(fragments)))
    return tuple(chains)


def bind_callout_groups(
    chains: Sequence[PdfCalloutChainEvidence], blocks: Sequence[PdfBlock],
    pages: Mapping[int, PdfCalloutPageEvidence],
) -> list[PdfCalloutGroup]:
    """Bind physical members only after proving exact original glyph ownership."""
    groups = []
    assigned: set[str] = set()
    for chain in chains:
        fragments = []
        for fragment in chain.fragments:
            page = pages[fragment.page_number]
            members = sorted((block for block in blocks
                if block.page_number == fragment.page_number
                and _intersects(block.bbox, fragment.content_bbox)), key=lambda b: b.order)
            if not members or any(
                block.id in assigned or not _inside(block.bbox, fragment.content_bbox)
                or block.semantic_role not in {"callout-title", "callout-body"}
                or block.kind not in {"heading", "paragraph", "list-item"}
                for block in members
            ):
                _fail(page, fragment.border_bbox, "ambiguous physical callout members")
            ownership: dict[int, str] = {}
            for block in members:
                count = 0
                for index, char in enumerate(page.characters):
                    if not str(char.get("text", "")).strip():
                        continue
                    box = _character_bbox(char)
                    if box is None or not _intersects(box, block.bbox):
                        continue
                    if index in ownership or not _character_fully_inside_bbox(char, block.bbox):
                        _fail(page, fragment.border_bbox, "partial or duplicate member glyph")
                    ownership[index] = block.id
                    count += sum(not c.isspace() for c in str(char["text"]))
                if count != sum(not c.isspace() for c in block.source_text):
                    _fail(page, fragment.border_bbox, "member source character accounting")
            if set(ownership) != set(fragment.character_indexes):
                _fail(page, fragment.border_bbox, "incomplete member glyph ownership")
            identifiers = tuple(block.id for block in members)
            assigned.update(identifiers)
            fragments.append(PdfCalloutFragment(
                fragment.page_number, fragment.page_bbox, fragment.border_bbox,
                fragment.content_bbox, fragment.open_top, fragment.open_bottom,
                fragment.character_indexes, identifiers))
        groups.append(PdfCalloutGroup(chain.id, tuple(fragments)))
    return groups
