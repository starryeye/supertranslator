"""Independent selectable composite examples; no detector-derived expectations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject
from reportlab.pdfgen.canvas import Canvas


@dataclass(frozen=True, slots=True)
class CompositeFigureFixture:
    source: Path
    frame_bbox: tuple[float, float, float, float]
    figure_text: str
    caption_text: str
    body_text: str
    table_text: tuple[str, ...]


def make_composite_figure_pdf(
    path: Path, *, frame: str = "rect", case: str = "valid",
    font: str = "Helvetica", scale: float = 1.0,
    origin: tuple[float, float] = (0.0, 0.0),
) -> CompositeFigureFixture:
    """Draw original text/art with a separately declared top-origin frame."""
    width, height = 600 * scale, 760 * scale
    canvas = Canvas(str(path), pagesize=(width, height))
    canvas.translate(*origin)
    canvas.scale(scale, scale)
    figure_lines = (
        "The copper vessel sends a measured pulse",
        "while a second chamber stores the returning signal.",
    )
    caption_lines = ("Figure 7. A vessel and its signal chamber.",)
    if case in {"wrapped", "wrapped-crossing"}:
        caption_lines = ("Figure 7. A vessel and its", "signal chamber remain connected.")
    body_text = "Independent observations remain selectable outside the illustration."
    canvas.setFont(font, 10)
    canvas.drawString(60, 675, body_text)

    if frame == "rect":
        canvas.rect(60, 360, 440, 220)
    elif frame in {"lines", "missing-side", "split-lines"}:
        sides = [(60, 360, 500, 360), (500, 360, 500, 580),
                 (500, 580, 60, 580), (60, 580, 60, 360)]
        if frame == "split-lines":
            sides[:1] = [(60, 360, 280, 360), (280, 360, 500, 360)]
        for side in sides[:3] if frame == "missing-side" else sides:
            canvas.line(*side)
    elif frame == "path":
        path_object = canvas.beginPath()
        path_object.moveTo(60, 360)
        path_object.lineTo(280, 360)
        path_object.lineTo(500, 360)
        path_object.lineTo(500, 580)
        path_object.lineTo(60, 580)
        path_object.close()
        canvas.drawPath(path_object)
    elif frame == "diagonal-only":
        canvas.line(60, 360, 500, 580)
        canvas.line(60, 580, 500, 360)
    elif frame == "curved-only":
        path_object = canvas.beginPath()
        path_object.moveTo(60, 360)
        path_object.curveTo(60, 580, 500, 360, 500, 580)
        path_object.curveTo(500, 360, 60, 580, 60, 360)
        path_object.close()
        canvas.drawPath(path_object)
    else:
        raise ValueError(f"unknown frame: {frame}")

    if case not in {"text-only", "no-artwork"}:
        # A large filled chamber is real internal artwork, not a border/icon.
        canvas.setFillColorRGB(0.2, 0.5, 0.7)
        canvas.rect(100, 385, 320, 70, fill=1)
        canvas.setFillColorRGB(0, 0, 0)
        canvas.line(100, 420, 450, 390)
    for index, text in enumerate(figure_lines):
        canvas.drawString(85, 545 - 15 * index, text)
    if case == "partial-glyph":
        canvas.drawString(497, 490, "W")

    caption_x, caption_y = 80.0, 334.0
    if case == "too-far":
        caption_y = 305
    elif case == "low-overlap":
        caption_x = 490
    elif case == "intervening-body":
        caption_y = 326
        canvas.drawString(100, 348, "An unrelated note blocks this gap.")
    elif case == "crossing":
        caption_y = 362
    elif case == "wrapped-crossing":
        caption_y = 585
    elif case == "above":
        caption_y = 598
    if case not in {"missing", "cross-page", "text-only"}:
        for index, text in enumerate(caption_lines):
            canvas.drawString(caption_x, caption_y - 14 * index, text)
    if case == "ambiguous":
        # A separate, non-prose candidate is also close enough to the caption.
        canvas.rect(90, 285, 350, 20)
        canvas.line(90, 285, 440, 305)
    table_text: tuple[str, ...] = ()
    if case == "outside-table":
        table_text = ("Material", "Reading", "Copper", "Stable")
        for y in (180, 205, 230):
            canvas.line(60, y, 400, y)
        for x in (60, 230, 400):
            canvas.line(x, 180, x, 230)
        for x, y, text in ((70, 214, "Material"), (240, 214, "Reading"),
                           (70, 189, "Copper"), (240, 189, "Stable")):
            canvas.drawString(x, y, text)
    if case == "cross-page":
        canvas.showPage()
        canvas.setFont(font, 10)
        canvas.drawString(80, 334, caption_lines[0])
    canvas.save()
    if origin != (0.0, 0.0):
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(path))
        ox, oy = origin
        bounds = ArrayObject([FloatObject(value) for value in
                              (ox, oy, ox + width, oy + height)])
        writer.pages[0][NameObject("/MediaBox")] = bounds
        writer.pages[0][NameObject("/CropBox")] = ArrayObject(bounds)
        with path.open("wb") as stream:
            writer.write(stream)
    ox, oy = origin
    return CompositeFigureFixture(
        path,
        (ox + 60 * scale, -oy + 180 * scale,
         ox + 500 * scale, -oy + 400 * scale),
        " ".join(figure_lines), " ".join(caption_lines), body_text, table_text,
    )
