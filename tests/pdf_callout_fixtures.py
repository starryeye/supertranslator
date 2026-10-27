"""Native independent callout chains; all expectations follow drawing commands."""

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject
from reportlab.pdfgen.canvas import Canvas

from supertranslator.pdf_models import BBox


@dataclass(frozen=True, slots=True)
class CalloutFixture:
    source: Path
    group_pages: tuple[tuple[int, ...], ...]
    title_texts: tuple[str, ...]
    paragraph_texts: tuple[str, ...]
    list_item_texts: tuple[str, ...]
    outside_texts: tuple[str, ...]
    frame_bboxes: tuple[tuple[int, BBox], ...]


def make_page_spanning_callout_pdf(
    path: Path, *, pages: int = 2, case: str = "paragraph",
    border: str = "lines", font: str = "Helvetica", scale: float = 1.0,
    origin: tuple[float, float] = (0.0, 0.0), mirrored: bool = False,
) -> CalloutFixture:
    if pages < 2:
        raise ValueError("a spanning callout fixture requires at least two pages")
    width, height = 600 * scale, 760 * scale
    canvas = Canvas(str(path), pagesize=(width, height))
    title = "Measured observations"
    first = ("The copper chamber retains a steady signal", "while each measured interval remains selectable.")
    continuation = ("The returning signal reaches the second chamber", "and provides an independent observation.")
    list_lines = ("1. Record the initial chamber reading", "and retain the continuing observation.")
    boxes = []
    outside = []
    for index in range(pages):
        canvas.translate(*origin)
        canvas.scale(scale, scale)
        x0 = 100 if mirrored and index % 2 else 60
        x1 = x0 + 420
        if case == "width-mismatch" and index > 0:
            x1 -= 4
        top, bottom = ((300, 700) if index == 0 else (60, 460))
        if 0 < index < pages - 1:
            top, bottom = 60, 700
        if case == "mid-page":
            bottom = 550 if index == 0 else bottom
        if case == "intervening-page" and index == 1:
            canvas.setFont(font, 10)
            canvas.drawString(60, 400, "An intervening page is not a continuation.")
            canvas.showPage()
            continue
        sides = [(x0, 760 - top, x0, 760 - bottom), (x1, 760 - top, x1, 760 - bottom)]
        caps = []
        if index == 0 and case != "missing-caps":
            caps.append((x0, 760 - top, x1, 760 - top))
        if index == pages - 1 and case != "missing-caps":
            caps.append((x0, 760 - bottom, x1, 760 - bottom))
        if border == "lines":
            for side in sides:
                canvas.line(*side)
            for cap in caps:
                if case in {"gap", "tolerated-gap"}:
                    canvas.line(cap[0] + (1.01 if case == "gap" else 1.0), cap[1], cap[2], cap[3])
                elif case == "diagonal-cap":
                    canvas.line(cap[0], cap[1] + 5, cap[2], cap[3])
                elif case == "curved-cap":
                    p = canvas.beginPath()
                    p.moveTo(cap[0], cap[1])
                    p.curveTo(cap[0] + 50, cap[1] + 5, cap[2] - 50, cap[3] + 5, cap[2], cap[3])
                    canvas.drawPath(p)
                else:
                    canvas.line(*cap)
        elif border == "path":
            p = canvas.beginPath()
            p.moveTo(x0, 760 - bottom)
            p.lineTo(x0, 760 - top)
            if index == 0 and case != "missing-caps":
                p.lineTo(x1, 760 - top)
                p.lineTo(x1, 760 - bottom)
            else:
                p.moveTo(x1, 760 - top)
                p.lineTo(x1, 760 - bottom)
            if index == pages - 1 and case != "missing-caps":
                p.lineTo(x0, 760 - bottom)
            canvas.drawPath(p, fill=int(case == "filled-open-path"))
        else:
            raise ValueError(border)
        canvas.setFont(font, 10)
        if index == 0:
            canvas.setFont("Helvetica-Bold", 12)
            canvas.drawString(x0 + 15, 760 - top - 25, title)
            canvas.setFont(font, 10)
        texts = (list_lines if case == "list" else first) if index == 0 else continuation
        ys = (bottom - 23, bottom - 9) if index == 0 else (top + 18, top + 32)
        if case == "mid-page" and index == 0:
            ys = (677, 691)  # Break the frame, not the independently drawn prose.
        if 0 < index < pages - 1:
            texts = (*continuation, *first)
            ys = (top + 18, top + 32, bottom - 23, bottom - 9)
        if case == "pitch-mismatch" and index > 0:
            ys = (top + 18, top + 35)
        if case == "font-mismatch" and index > 0:
            canvas.setFont(font, 12)
        for text, y in zip(texts, ys):
            canvas.drawString(x0 + (19 if case == "indent-mismatch" and index > 0 else 15), 760 - y, text)
        outside_text = "Independent outside prose remains outside the callout."
        if 0 < index < pages - 1:
            outside_text = "Outside"
        outside.append(outside_text)
        outside_y = 200 if index == 0 else (400 if index < pages - 1 else 560)
        canvas.drawString(5 if 0 < index < pages - 1 else 60, 760 - outside_y, outside_text)
        canvas.drawString(60, 20, "Calibrated running furniture")
        canvas.drawString(60, 740, "Stable header furniture")
        if case in {"external-below", "external-above"}:
            if (case == "external-below" and index == 0) or (case == "external-above" and index == pages - 1):
                canvas.drawString(x0 + 15, 760 - (bottom + 14 if index == 0 else top - 8), "Ordinary prose blocks this proposed open edge.")
        if case == "partial-glyph":
            canvas.drawString(x1 - 2, 760 - (top + 100), "W")
        if case == "crossing-path":
            p = canvas.beginPath()
            p.moveTo(x0 - 20, 760 - top - 100)
            p.lineTo(x1 + 20, 760 - top - 160)
            p.lineTo(x1 + 30, 760 - top - 180)
            canvas.drawPath(p)
        if case in {"grid", "artwork", "crossing-artwork", "nested", "irregular", "competing"}:
            if case == "crossing-artwork":
                canvas.rect(x1 - 40, 760 - top - 160, 100, 70, fill=1)
            elif case == "artwork":
                canvas.rect(x0 + 40, 760 - top - 160, 200, 70, fill=1)
            elif case == "grid":
                canvas.line(x0, 760 - top - 100, x1, 760 - top - 100)
            elif case == "irregular":
                canvas.line(x0, 760 - top - 100, x0 + 80, 760 - top - 160)
            else:
                canvas.rect(x0 + 5, 760 - bottom + 5, 410, bottom - top - 10)
        ox, oy = origin
        boxes.append((index + 1, (ox + x0 * scale, -oy + top * scale, ox + x1 * scale, -oy + bottom * scale)))
        canvas.showPage()
    canvas.save()
    if origin != (0.0, 0.0):
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(path))
        ox, oy = origin
        for page in writer.pages:
            bounds = ArrayObject([FloatObject(v) for v in (ox, oy, ox + width, oy + height)])
            page[NameObject("/MediaBox")] = bounds
            page[NameObject("/CropBox")] = ArrayObject(bounds)
        with path.open("wb") as stream:
            writer.write(stream)
    paragraph = ("The copper chamber retains a steady signal while each measured interval remains selectable. "
                 "The returning signal reaches the second chamber and provides an independent observation.")
    list_item = ("1. Record the initial chamber reading and retain the continuing observation. "
                 "The returning signal reaches the second chamber and provides an independent observation.")
    paragraphs = (paragraph,) * (pages - 1 if case != "list" else pages - 2)
    return CalloutFixture(path, (tuple(range(1, pages + 1)),), (title,), paragraphs,
                          (list_item,) if case == "list" else (),
                          tuple(outside), tuple(boxes))
