"""The generated sheet as a file: SVG, and through it PDF and PNG.

``schematic.py`` decides what is on the sheet; this file decides what that looks like on
paper, and knows nothing about perfboard. Same shape as ``guide_export.py``, and the same
rule: pure, deterministic, stdlib only -- no Qt, no clock, no filesystem, strings out. That
is what lets an SVG be compared against a golden file rather than looked at, and what lets
the MCP server and a headless run produce the same sheet the desktop app does.

**SVG IS THE ONLY RENDERER FOR PAPER, AND PDF AND PNG COME OUT OF IT.**
``ui/export_schematic.py`` hands this string to Qt's SVG renderer to paginate or
rasterise it. Three writers over one ``SchematicDrawing`` would be three chances for the
printed sheet, the emailed PNG and the embedded SVG to disagree about what the circuit is,
and the one thing worse than no export is three exports that differ.

**IT IS NOT A SECOND COPY OF THE PANEL, THOUGH, AND THAT IS DELIBERATE.** ``ui/viewsch.py``
paints for a screen and this writes for paper, which are different jobs in two measurable
ways. Screen labels hold a PIXEL size, because a reference that shrank to nothing when the
sheet was fitted to the panel would make the fitted view the one view that says nothing
(``ui/scenetext.py`` sets this out at length); paper labels are millimetres of sheet,
because paper does not zoom -- exactly the split ``export_pdf`` already makes against
``scenetext``. And the panel is light ink on a dark sheet, which is right for a screen at
midnight and wrong for every printer. What the two must NOT decide separately is geometry,
which is why the rail glyph's bars come from ``schematic.rail_glyph_bars`` rather than from
a constant in each file.

**INK ON WHITE, MONOCHROME BY DEFAULT.** The panel colours the three net classes; a printed
sheet does not, and the reason is already written down in the rail glyph: a schematic is
read at a glance and often printed in black, so a reader should never have to know a colour
convention to tell a rail that sinks from one that sources. The glyphs say it, the labels
say it, and the sheet then survives a photocopier. ``SheetInk`` keeps the three classes as
separate fields so a caller that knows its output is a screen can colour them; they are the
same black by default because most outputs are not.

**THE NOTES ARE PRINTED WITH THE SHEET.** ``SchematicDrawing.notes`` is where a pin the
netlist names and the footprint does not, or a part nothing defines, ends up. Dropping them
on the way to paper would hand somebody a picture of a circuit nobody has -- the exact thing
``schematic.py`` built the field to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Literal

from .model import Mm, Point2
from .schematic import (
    FREE_END_MM,
    MARGIN_MM,
    NET_LABEL_MM,
    PIN_LABEL_MM,
    REF_LABEL_MM,
    VALUE_LABEL_MM,
    Annotation,
    FreeWire,
    Label,
    NoConnect,
    Rail,
    SchematicDrawing,
    Symbol,
    Wire,
    no_connect_arms,
    rail_glyph_bars,
)
from .version import __version__

# ---------------------------------------------------------------------------
# Ink
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SheetInk:
    """Colours and sizes for one exported sheet. Millimetres throughout.

    Text sizes are millimetres of sheet rather than points, for the reason the whole
    coordinate system is millimetres: a schematic exported at 1.6 mm text and printed on A3
    has 1.6 mm text, and nothing in the pipeline needs a scale factor to make that true.
    1.27 mm is KiCad's default and reads as small-but-clear on a 2.54 mm grid, so a
    reference a shade above it and a pin number a shade below is the range this stays in.
    """

    background: str = "#ffffff"
    #: Symbol bodies and reference designators. The sheet's main weight.
    ink: str = "#111111"
    #: Values and pin numbers -- present, subordinate, and still black enough to photocopy.
    dim: str = "#444444"
    #: A part nothing in the document defines. Drawn dashed as well as coloured, so the
    #: defect survives a monochrome print, which is the point of not relying on colour.
    undefined: str = "#a11414"
    signal: str = "#111111"
    power: str = "#111111"
    ground: str = "#111111"

    wire_mm: Mm = 0.25
    body_mm: Mm = 0.35
    dot_mm: Mm = 0.60
    #: On, off. A dash long enough to read as deliberate at a glance and at print size.
    dash_mm: tuple[Mm, Mm] = (1.4, 0.9)

    #: From the layout, which reserves a band of room above and below every row for
    #: exactly this text (``schematic.REF_BAND_MM`` / ``VALUE_BAND_MM``).
    ref_mm: Mm = REF_LABEL_MM
    value_mm: Mm = VALUE_LABEL_MM
    #: NOT a number of its own. `schematic.py` reserves a box of exactly this height above
    #: each run so that no wire is drawn through the net's name, and a sheet that then drew
    #: the name at some other size would be filling a gap that was measured for a different
    #: piece of text.
    net_mm: Mm = NET_LABEL_MM
    #: From the layout, for the reason ``net_mm`` is: a box is widened to fit the pin
    #: names its part declares, measured at this size.
    pin_mm: Mm = PIN_LABEL_MM
    title_mm: Mm = 3.2
    note_mm: Mm = 1.6

    #: A stack that resolves to something on every platform this ships to and degrades to
    #: the system sans-serif where it does not. Named rather than left to the renderer
    #: because "whatever the default is" differs between a browser, Qt and Inkscape.
    font_family: str = "DejaVu Sans, Helvetica, Arial, sans-serif"


PAPER = SheetInk()

#: Dark-canvas Night look matching the schematic panel's dark theme, for screen renders;
#: exports to paper (SVG, PDF, PNG) default to ``PAPER`` even when the window is dark.
NIGHT = SheetInk(
    background="#12131a",
    ink="#c8d0de",
    dim="#7d8698",
    undefined="#e5a840",
    signal="#3fa9d4",
    power="#e0723c",
    ground="#7f8794",
)

type SheetPageSize = Literal["auto", "A4", "A3"]

#: ISO paper sizes in millimetres (landscape width, height).
PAGE_DIMENSIONS_MM: dict[Literal["A4", "A3"], tuple[Mm, Mm]] = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
}
FRAME_MARGIN_MM: Mm = 8.0
TITLE_BLOCK_WIDTH_MM: Mm = 90.0
TITLE_BLOCK_HEIGHT_MM: Mm = 22.0


@dataclass(frozen=True, slots=True)
class TitleBlock:
    """Optional engineering title block drawn in the bottom-right corner of an exported sheet.

    Every value is passed in by the host (no clock or filesystem reads inside the engine).
    Omitted by default so bare sheet exports stay unchanged.
    """

    title: str = ""
    revision: str = ""
    date: str = ""
    sheet: str = "1 / 1"


# ---------------------------------------------------------------------------
# Writing numbers and text
# ---------------------------------------------------------------------------


def _n(value: float) -> str:
    """A coordinate, short and stable.

    Three decimals is a thousandth of a millimetre, far finer than anything the layout
    computes on purpose and coarse enough that a platform whose libm rounds the last bit
    differently still writes the same file -- the property the golden comparison rests on
    (``tests/test_footprints.py`` learned this the hard way on macOS arm64).

    Negative zero is normalised away for the same reason: ``-0`` and ``0`` are the same
    point and would otherwise be a diff nobody caused.
    """
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _ceil_to_written(value: float) -> float:
    """``value`` raised until :func:`_n` can write it without losing anything off the end.

    Stated by DOING it rather than by arithmetic on the exponent, because the property
    wanted is exactly "what comes out of ``_n`` is not less than what went in" and every
    cleverer version got the tolerance wrong: ``_n`` rounds to nearest, so a value a float
    ULP above a thousandth (462.2800000000001, which is what a 24-part circuit's sheet
    width came to) is written 462.28 and the viewBox no longer contains its own contents.

    Still a float, so it adds and compares as one.
    """
    written = float(_n(value))
    return written if written >= value else written + 0.001


def _pt(point: Point2) -> str:
    return f"{_n(point.x)},{_n(point.y)}"


def _points(path: tuple[Point2, ...]) -> str:
    return " ".join(_pt(point) for point in path)


def _text(
    content: str,
    x: Mm,
    y: Mm,
    size: Mm,
    colour: str,
    anchor: str,
    ink: SheetInk,
    bold: bool = False,
) -> str:
    """One text element, positioned by its BASELINE.

    The vertical placement is arithmetic here rather than a ``dominant-baseline``
    attribute, and it has to be: Qt's SVG renderer implements SVG Tiny 1.2, which has no
    such attribute, and it is the renderer that produces the PDF. An attribute nothing
    implements does not fail -- it is ignored, and every reference lands on top of its own
    symbol on the printed sheet while the browser preview looks perfect.
    """
    weight = ' font-weight="bold"' if bold else ""
    return (
        f'<text x="{_n(x)}" y="{_n(y)}" font-size="{_n(size)}" fill="{colour}"'
        f' text-anchor="{anchor}" font-family="{escape(ink.font_family, quote=True)}"{weight}>'
        f"{escape(content)}</text>"
    )


#: ``Label.anchor`` to SVG's own word for it. Tiny 1.2 does have ``text-anchor``.
_ANCHOR = {"left": "start", "centre": "middle", "right": "end"}


def _baseline(label: Label, size: Mm) -> Mm:
    """Where the baseline goes so the label sits where the panel puts it.

    ``schematic.py`` places a label by an anchor point and a kind, and the panel turns the
    kind into a Qt alignment: a reference sits ABOVE its point, a value below it, a pin
    number centred on it. Those three readings are reproduced here in the only currency an
    SVG has, which is the baseline offset. The fractions are ordinary font metrics -- a cap
    height is about 0.7 of the em and a descender about 0.2 -- and they only have to be
    close, because a millimetre of sheet is a fifth of a grid step.
    """
    if label.kind == "value":  # below the point
        return label.at.y + size * 0.8
    if label.kind == "pin":  # centred on it
        return label.at.y + size * 0.35
    return label.at.y  # ref, net: above it


# ---------------------------------------------------------------------------
# The sheet
# ---------------------------------------------------------------------------

#: Blank space above the sheet when a title is drawn, and the room one note takes, both as
#: multiples of their own text size. A line and a half of leading is what makes a stack of
#: notes read as a list rather than as a paragraph.
_TITLE_BAND = 2.4
_NOTE_LEADING = 1.7


def _class_colour(net_class: str, ink: SheetInk) -> str:
    if net_class == "power":
        return ink.power
    if net_class == "ground":
        return ink.ground
    return ink.signal


def _wire(run: Wire | Rail | FreeWire, ink: SheetInk) -> str:
    colour = _class_colour(run.net_class, ink)
    return (
        f'<polyline points="{_points(run.path)}" fill="none" '
        f'stroke="{colour}" stroke-width="{_n(ink.wire_mm)}"/>'
    )


def _free_end_box(at: Point2, colour: str, ink: SheetInk) -> str:
    half = FREE_END_MM
    return (
        f'<rect x="{_n(at.x - half)}" y="{_n(at.y - half)}" '
        f'width="{_n(2 * half)}" height="{_n(2 * half)}" '
        f'fill="{ink.background}" stroke="{colour}" stroke-width="{_n(ink.wire_mm)}"/>'
    )


def _glyph(rail: Rail, ink: SheetInk) -> str:
    colour = _class_colour(rail.net_class, ink)
    return "".join(
        f'<line x1="{_n(start.x)}" y1="{_n(start.y)}" x2="{_n(end.x)}" y2="{_n(end.y)}" '
        f'stroke="{colour}" stroke-width="{_n(ink.body_mm)}"/>'
        for start, end in rail_glyph_bars(rail)
    )


def _no_connect(mark: NoConnect, ink: SheetInk) -> str:
    """A cross on a pin the netlist does not reach. Drawn in the dim ink, not the warning
    one: an unused header pin is the ordinary case, and a sheet that shouted about ten of
    them would be crying wolf on the sheet where it matters."""
    return "".join(
        f'<line x1="{_n(start.x)}" y1="{_n(start.y)}" x2="{_n(end.x)}" y2="{_n(end.y)}" '
        f'stroke="{ink.dim}" stroke-width="{_n(ink.wire_mm)}"/>'
        for start, end in no_connect_arms(mark)
    )


def _symbol(symbol: Symbol, ink: SheetInk) -> str:
    """One symbol, drawn in its own coordinates inside a translate.

    A ``transform`` rather than baked-in absolute coordinates, so the file says the same
    thing the model does -- a symbol is a shape plus a place -- and so a reader comparing an
    SVG against ``tests/schematic_golden/`` is comparing the same two numbers.
    """
    colour = ink.undefined if symbol.undefined else ink.ink
    dashes = (
        f' stroke-dasharray="{_n(ink.dash_mm[0])} {_n(ink.dash_mm[1])}"'
        if symbol.undefined
        else ""
    )
    body: list[str] = []
    for shape in symbol.shapes:
        common = f'stroke="{colour}" stroke-width="{_n(ink.body_mm)}"{dashes}'
        if shape.kind == "circle":
            centre = shape.points[0]
            body.append(
                f'<circle cx="{_n(centre.x)}" cy="{_n(centre.y)}" r="{_n(shape.radius)}" '
                f"fill=\"none\" {common}/>"
            )
        elif shape.kind == "polygon":
            fill = colour if shape.filled else "none"
            body.append(f'<polygon points="{_points(shape.points)}" fill="{fill}" {common}/>')
        else:
            body.append(f'<polyline points="{_points(shape.points)}" fill="none" {common}/>')
    return (
        f'<g transform="translate({_pt(symbol.at)})">' + "".join(body) + "</g>"
    )


def _annotation(note: Annotation, ink: SheetInk) -> str:
    """A caption or a box somebody put on the drawing.

    IN THE DIM INK AND NEVER IN A NET COLOUR, the same call the panel makes: a note is not
    part of the circuit and must not read as one. Its text is millimetres of sheet like
    everything else on paper -- and unlike on screen, where a reference holds a pixel size,
    a note is the one piece of text that is millimetres in BOTH, because it is a size
    somebody chose rather than annotation the renderer is sizing.
    """
    left, top = min(note.at.x, note.to.x), min(note.at.y, note.to.y)
    width, height = abs(note.to.x - note.at.x), abs(note.to.y - note.at.y)
    common = f'stroke="{ink.dim}" stroke-width="{_n(ink.wire_mm)}" fill="none"'
    if note.kind == "line":
        return (
            f'<line x1="{_n(note.at.x)}" y1="{_n(note.at.y)}" '
            f'x2="{_n(note.to.x)}" y2="{_n(note.to.y)}" {common}/>'
        )
    if note.kind == "rectangle":
        return (
            f'<rect x="{_n(left)}" y="{_n(top)}" '
            f'width="{_n(width)}" height="{_n(height)}" {common}/>'
        )
    if note.kind == "circle":
        return (
            f'<ellipse cx="{_n(left + width / 2)}" cy="{_n(top + height / 2)}" '
            f'rx="{_n(width / 2)}" ry="{_n(height / 2)}" {common}/>'
        )
    return _text(note.text, note.at.x, note.at.y, note.size_mm, ink.dim, "start", ink)


def _label(label: Label, ink: SheetInk) -> str:
    if label.kind == "ref":
        size, colour, bold = ink.ref_mm, ink.ink, True
    elif label.kind == "value":
        size, colour, bold = ink.value_mm, ink.dim, False
    elif label.kind in ("net", "rail"):
        size, colour, bold = ink.net_mm, ink.signal, False
    else:
        size, colour, bold = ink.pin_mm, ink.dim, False
    return _text(
        label.text,
        label.at.x,
        _baseline(label, size),
        size,
        colour,
        _ANCHOR[label.anchor],
        ink,
        bold=bold,
    )


def _title_block(
    block: TitleBlock, x: Mm, y: Mm, width: Mm, height: Mm, ink: SheetInk
) -> list[str]:
    """An engineering title block in the bottom-right corner, SVG Tiny 1.2 compatible."""
    split_y = y + height * 0.52
    col1 = x + width * 0.30
    col2 = x + width * 0.68
    pad = 2.0
    cap_mm = 1.25
    val_mm = 1.65
    title_mm = 2.4
    out: list[str] = [
        '<g id="title-block" stroke-linecap="round" stroke-linejoin="round">',
        f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(width)}" height="{_n(height)}" '
        f'fill="{ink.background}" stroke="{ink.ink}" stroke-width="{_n(ink.body_mm)}"/>',
        f'<line x1="{_n(x)}" y1="{_n(split_y)}" x2="{_n(x + width)}" y2="{_n(split_y)}" '
        f'stroke="{ink.ink}" stroke-width="{_n(ink.wire_mm)}"/>',
        f'<line x1="{_n(col1)}" y1="{_n(split_y)}" x2="{_n(col1)}" y2="{_n(y + height)}" '
        f'stroke="{ink.ink}" stroke-width="{_n(ink.wire_mm)}"/>',
        f'<line x1="{_n(col2)}" y1="{_n(split_y)}" x2="{_n(col2)}" y2="{_n(y + height)}" '
        f'stroke="{ink.ink}" stroke-width="{_n(ink.wire_mm)}"/>',
    ]
    if block.title:
        out.append(
            _text(
                block.title,
                x + pad,
                y + height * 0.36,
                title_mm,
                ink.ink,
                "start",
                ink,
                bold=True,
            )
        )
    rev_text = block.revision or f"v{__version__}"
    cells = (
        (x + pad, "REV", rev_text),
        (col1 + pad, "DATE", block.date),
        (col2 + pad, "SHEET", block.sheet),
    )
    for cx, caption, value in cells:
        out.append(_text(caption, cx, split_y + 3.0, cap_mm, ink.dim, "start", ink))
        if value:
            out.append(_text(value, cx, y + height - 2.4, val_mm, ink.ink, "start", ink))
    out.append("</g>")
    return out


def _drawing_elements(drawing: SchematicDrawing, ink: SheetInk) -> list[str]:
    """Every circuit primitive, annotation and label of ``drawing`` as SVG elements."""
    out: list[str] = ['<g stroke-linecap="round" stroke-linejoin="round">']
    for wire in drawing.wires:
        out.append(_wire(wire, ink))
    for fw in drawing.free_wires:
        colour = _class_colour(fw.net_class, ink)
        out.append(_wire(fw, ink))
        out.append(_free_end_box(fw.path[-1], colour, ink))
        if fw.free_start:
            out.append(_free_end_box(fw.path[0], colour, ink))
    for rail in drawing.rails:
        out.append(_wire(rail, ink))
        out.append(_glyph(rail, ink))
    for junction in drawing.junctions:
        out.append(
            f'<circle cx="{_n(junction.at.x)}" cy="{_n(junction.at.y)}" '
            f'r="{_n(ink.dot_mm)}" fill="{ink.signal}"/>'
        )
    for mark in drawing.no_connects:
        out.append(_no_connect(mark, ink))
    for symbol in drawing.symbols:
        out.append(_symbol(symbol, ink))
    out.append("</g>")
    for annotation in drawing.annotations:
        out.append(_annotation(annotation, ink))
    for label in drawing.labels:
        out.append(_label(label, ink))
    return out


def _framed_svg(
    drawing: SchematicDrawing,
    title: str | None,
    ink: SheetInk,
    page_size: SheetPageSize,
    title_block: TitleBlock | None,
) -> str:
    """ISO A4/A3 true-scale sheet and/or title-block framed SVG."""
    raw_w = max(drawing.width, 2 * MARGIN_MM)
    raw_h = max(drawing.height, 2 * MARGIN_MM)
    notes_h = (
        ink.note_mm * (_NOTE_LEADING * len(drawing.notes) + 1.0) if drawing.notes else 0.0
    )
    if page_size in PAGE_DIMENSIONS_MM:
        long_mm, short_mm = PAGE_DIMENSIONS_MM[page_size]
        if raw_h > raw_w:
            page_w, page_h = short_mm, long_mm
        else:
            page_w, page_h = long_mm, short_mm
    else:
        tb_h = TITLE_BLOCK_HEIGHT_MM + 4.0 if title_block is not None else 0.0
        page_w = _ceil_to_written(
            max(raw_w + 2 * FRAME_MARGIN_MM, TITLE_BLOCK_WIDTH_MM + 2 * FRAME_MARGIN_MM + 8.0)
        )
        page_h = _ceil_to_written(raw_h + max(notes_h, tb_h) + 2 * FRAME_MARGIN_MM)

    inner_x = FRAME_MARGIN_MM
    inner_y = FRAME_MARGIN_MM
    inner_w = page_w - 2 * FRAME_MARGIN_MM
    inner_h = page_h - 2 * FRAME_MARGIN_MM
    bottom_reserve = (
        max(TITLE_BLOCK_HEIGHT_MM + 2.0, notes_h) if title_block is not None else notes_h
    )
    avail_w = max(inner_w - 4.0, 1.0)
    avail_h = max(inner_h - bottom_reserve - 4.0, 1.0)
    # True 1:1 millimetre scale whenever the drawing fits; scale down uniformly only if larger.
    scale = min(1.0, avail_w / raw_w, avail_h / raw_h)
    tx = inner_x + (inner_w - raw_w * scale) / 2.0
    ty = inner_y + (inner_h - bottom_reserve - raw_h * scale) / 2.0

    doc_title = title or (title_block.title if title_block is not None else "") or "Schematic"
    out: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{_n(page_w)}mm" height="{_n(page_h)}mm" '
        f'viewBox="0 0 {_n(page_w)} {_n(page_h)}">',
        f"<title>{escape(doc_title)}</title>",
        f"<desc>Perfboard Studio {__version__}</desc>",
        f'<rect x="0" y="0" width="{_n(page_w)}" height="{_n(page_h)}" fill="{ink.background}"/>',
        f'<rect x="{_n(inner_x)}" y="{_n(inner_y)}" width="{_n(inner_w)}" '
        f'height="{_n(inner_h)}" fill="none" stroke="{ink.ink}" '
        f'stroke-width="{_n(ink.body_mm)}"/>',
    ]
    if abs(scale - 1.0) < 1e-6:
        out.append(f'<g transform="translate({_n(tx)},{_n(ty)})">')
    else:
        out.append(f'<g transform="translate({_n(tx)},{_n(ty)}) scale({_n(scale)})">')
    out.extend(_drawing_elements(drawing, ink))
    out.append("</g>")

    if title_block is not None:
        tb_x = inner_x + inner_w - TITLE_BLOCK_WIDTH_MM
        tb_y = inner_y + inner_h - TITLE_BLOCK_HEIGHT_MM
        out.extend(
            _title_block(title_block, tb_x, tb_y, TITLE_BLOCK_WIDTH_MM, TITLE_BLOCK_HEIGHT_MM, ink)
        )

    for index, note in enumerate(drawing.notes):
        note_y = (
            inner_y
            + inner_h
            - notes_h
            + ink.note_mm * (1.0 + _NOTE_LEADING * index)
        )
        out.append(
            _text(
                f"· {note}",
                inner_x + 3.0,
                note_y,
                ink.note_mm,
                ink.dim,
                "start",
                ink,
            )
        )

    out.append("</svg>")
    return "\n".join(out) + "\n"


def drawing_to_svg(
    drawing: SchematicDrawing,
    title: str | None = None,
    ink: SheetInk = PAPER,
    *,
    page_size: SheetPageSize = "auto",
    title_block: TitleBlock | None = None,
) -> str:
    """The sheet as one self-contained SVG document.

    ``title`` is the caller's -- usually the document name -- because this module has no
    filesystem and therefore no opinion about what a document is called. It is drawn in a
    band above the sheet and put in the SVG's own ``<title>``, which is what a browser tab
    and an image viewer show.

    With ``page_size`` set to ``"A4"`` or ``"A3"``, or with a :class:`TitleBlock`, the sheet
    is framed on ISO millimetres at true 1:1 scale (scaled down uniformly only if larger than
    the frame) with the title block in the bottom-right corner. With the defaults
    (``page_size="auto"``, ``title_block=None``), the bare sheet output is unchanged.

    The output carries the version that wrote it, in a ``<desc>``, for the reason
    ``guide_to_json`` does: an exported file outlives the session that produced it, and the
    first question about a sheet that looks wrong is which build drew it.
    """
    if page_size != "auto" or title_block is not None:
        return _framed_svg(drawing, title, ink, page_size, title_block)
    # Rounded OUTWARD to the thousandth _n writes, not to the nearest one. A viewBox short
    # of the drawing crops it, and _n rounds to three decimals -- so a sheet whose width
    # lands a float ULP above a thousandth (462.2800000000001, which is what a 24-part
    # circuit produced) was written as 462.28 and cropped by a nanometre. Invisible, and
    # still a viewBox that does not contain its own contents.
    sheet_w = _ceil_to_written(max(drawing.width, 2 * MARGIN_MM))
    sheet_h = _ceil_to_written(max(drawing.height, 2 * MARGIN_MM))

    title_band = ink.title_mm * _TITLE_BAND if title else 0.0
    notes_band = (
        ink.note_mm * (_NOTE_LEADING * len(drawing.notes) + 1.0) if drawing.notes else 0.0
    )
    # The same property for the whole height, stated the same way: the box starts at the
    # WRITTEN -title_band, and its written height has to reach the bottom of the sheet from
    # there. 124.46 of sheet under a 7.68 title came to 132.14 written, and -7.68 + 132.14
    # is 124.45999999999998 -- a sheet cropped by a femtometre, which is still cropped.
    total_h = _ceil_to_written(sheet_h + title_band + notes_band)
    while float(_n(-title_band)) + float(_n(total_h)) < sheet_h + notes_band:
        total_h += 0.001

    out: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{_n(sheet_w)}mm" height="{_n(total_h)}mm" '
        f'viewBox="0 {_n(-title_band)} {_n(sheet_w)} {_n(total_h)}">'
    ]
    out.append(f"<title>{escape(title or 'Schematic')}</title>")
    out.append(f"<desc>Perfboard Studio {__version__}</desc>")
    out.append(
        f'<rect x="0" y="{_n(-title_band)}" width="{_n(sheet_w)}" '
        f'height="{_n(total_h)}" fill="{ink.background}"/>'
    )

    if title:
        out.append(
            _text(
                title,
                MARGIN_MM,
                -title_band + ink.title_mm,
                ink.title_mm,
                ink.ink,
                "start",
                ink,
                bold=True,
            )
        )

    # The order a draughtsman would use, and the order the panel paints in: wires first so
    # a symbol sits on top of the line reaching it, then rails, dots, bodies, text.
    out.extend(_drawing_elements(drawing, ink))

    for index, note in enumerate(drawing.notes):
        out.append(
            _text(
                f"· {note}",
                MARGIN_MM,
                sheet_h + ink.note_mm * (1.0 + _NOTE_LEADING * index),
                ink.note_mm,
                ink.dim,
                "start",
                ink,
            )
        )

    out.append("</svg>")
    return "\n".join(out) + "\n"


__all__ = [
    "FRAME_MARGIN_MM",
    "NIGHT",
    "PAGE_DIMENSIONS_MM",
    "PAPER",
    "TITLE_BLOCK_HEIGHT_MM",
    "TITLE_BLOCK_WIDTH_MM",
    "SheetInk",
    "SheetPageSize",
    "TitleBlock",
    "drawing_to_svg",
]
