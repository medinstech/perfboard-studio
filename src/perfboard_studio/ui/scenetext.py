"""Editor labels drawn at a constant on-screen size, positioned by scene coordinates.

THE PROBLEM. The 2D scene works in millimetres -- one scene unit is one mm, which is what
makes the 1:1 PDF exact -- and the view is scaled anywhere from 1.5 to 90 pixels per mm.
Text sized in scene units inherits that: a label that reads well at 12 px/mm is an
illegible smear at 2 and a wall of letters at 60. Ruler labels and component references are
annotation, not artwork on the board, so they should hold one comfortable size while the
board zooms underneath them -- which is how every editor with an axis ruler behaves.

There is a second, sharper reason not to size them in millimetres. A point is 1/72 inch OF
THE PAINT DEVICE, so a "2 pt" label is about 18 pixels on the PDF writer's 600 dpi page
and under 3 on a 96 dpi screen. At that size some platforms' font engines draw nothing at
all and report no error -- the offscreen Qt platform used for headless rendering is one of
them, which means a millimetre-sized label can vanish from CI output while looking fine on
a developer's screen. Sizing in device pixels puts every label well clear of that floor.

So: the position comes from the scene (the transform maps it), and the size does not (the
transform is reset before drawing). Paper is the exception, and a page is told apart by its
device (``QPagedPaintDevice``): printed text has to scale with the page, so a reference
drawn into the 1:1 PDF is drawn in millimetres (:func:`draw_printed_reference`). It was
not, once, and came out half a millimetre tall.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter

from .bodies import PIN_NAME_HEIGHT_MM

#: pixel size -> font. Rulers draw dozens of labels per repaint, so building a QFont and
#: its metrics every time is worth avoiding.
_CACHE: dict[tuple[int, bool], QFont] = {}


def label_font(pixel_size: int, bold: bool = False) -> QFont:
    key = (pixel_size, bold)
    cached = _CACHE.get(key)
    if cached is None:
        cached = QFont()
        cached.setPixelSize(pixel_size)
        cached.setBold(bold)
        _CACHE[key] = cached
    return cached


def draw_label(
    painter: QPainter,
    anchor: QPointF,
    text: str,
    pixel_size: int,
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
    bold: bool = False,
    offset: QPointF | None = None,
    background: QColor | None = None,
) -> None:
    """Draw ``text`` at a fixed ``pixel_size``, anchored at the scene point ``anchor``.

    ``offset`` shifts the label in DEVICE pixels after positioning, which is how a drop
    shadow or a few pixels of clearance stay constant instead of growing with zoom.

    ``background`` puts a rounded plate behind the text, a few pixels bigger than it -- the
    one way to keep a label readable over whatever it lands on: pads, a pale body, the
    printed legend. A drop shadow a pixel wide does it over flat substrate and nowhere else.
    """
    font = label_font(pixel_size, bold)
    box = _label_box(painter.transform().map(anchor), text, font, offset)

    painter.save()
    painter.resetTransform()
    painter.setFont(font)
    if background is not None:
        pen = painter.pen()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        radius = QFontMetricsF(font).height() * 0.3
        painter.drawRoundedRect(_plate(box, text, font, alignment), radius, radius)
        painter.setPen(pen)
    painter.drawText(box, int(alignment), text)
    painter.restore()


def label_plate_rect(
    device_anchor: QPointF,
    text: str,
    pixel_size: int,
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
    bold: bool = False,
    offset: QPointF | None = None,
) -> QRectF:
    """The plate :func:`draw_label` puts behind ``text``, in DEVICE pixels, for an anchor
    already mapped to the device. What a click on a label has to be measured against: the
    same arithmetic as the drawing, so the two cannot disagree about where a label is."""
    font = label_font(pixel_size, bold)
    return _plate(_label_box(device_anchor, text, font, offset), text, font, alignment)


def _label_box(device: QPointF, text: str, font: QFont, offset: QPointF | None) -> QRectF:
    """A box around the anchor big enough for the text, which the text is then aligned
    inside. Simpler and more predictable than juggling baselines per alignment case."""
    if offset is not None:
        device = device + offset
    metrics = QFontMetricsF(font)
    width = metrics.horizontalAdvance(text)
    height = metrics.height()
    return QRectF(device.x() - width, device.y() - height, width * 2, height * 2)


def _plate(box: QRectF, text: str, font: QFont, alignment: Qt.AlignmentFlag) -> QRectF:
    """The text's own rect inside ``box``, a few pixels bigger: the label's plate."""
    return QFontMetricsF(font).boundingRect(box, int(alignment), text).adjusted(-4, -1, 4, 1)


#: Physical labels are rasterised from a font this tall and then scaled down to the
#: millimetre size asked for. Any comfortably large number works; what matters is that
#: the font engine is never handed the sub-point size the millimetres alone would imply.
_PHYSICAL_FONT_PX = 64


def draw_physical_label(
    painter: QPainter,
    centre: QPointF,
    text: str,
    height_mm: float,
    bold: bool = True,
    max_width_mm: float | None = None,
    rotation_deg: float = 0.0,
) -> None:
    """Draw ``text`` at a size in MILLIMETRES, centred on a scene point.

    THE EXACT OPPOSITE OF :func:`draw_label`, and both are needed. An annotation this
    program adds -- a ruler label, a reference designator -- should hold its size while
    the board zooms. Ink printed on the board should not: it is 1.2 mm of silkscreen
    whatever the zoom, and it has to come out 1.2 mm on the 1:1 PDF that gets taped to
    the board.

    Simply asking for a millimetre-sized font does not work, for the reason set out in
    this module's header: at one scene unit per millimetre that is a fraction of a point,
    and the font engine quietly draws nothing. So the glyph is rasterised from a
    comfortably large font and the PAINTER is scaled to bring it down to size -- which
    leaves it subject to the scene transform, and therefore physical, while the font
    itself is never small.
    """
    font = label_font(_PHYSICAL_FONT_PX, bold)
    metrics = QFontMetricsF(font)
    # Cap height rather than the full line height: what a person means by "1.2 mm text"
    # is the height of a capital, not the box including the space for descenders.
    cap = metrics.capHeight()
    if cap <= 0:  # pragma: no cover - a platform with no font database
        cap = _PHYSICAL_FONT_PX * 0.7
    scale = height_mm / cap
    width = max(metrics.horizontalAdvance(text), 1.0)
    height = max(metrics.height(), 1.0)

    # Narrow the whole label rather than letting it run over its neighbours. A board's
    # printed legend lives in a strip barely a millimetre wide, so "07" has to be set
    # smaller than "7" -- which is what a board actually does. Measured from the font's
    # own metrics instead of a characters-times-a-ratio guess, since the ratio is wrong
    # for exactly the strings that need this (digits are narrower than letters).
    if max_width_mm is not None and width * scale > max_width_mm:
        scale = max_width_mm / width

    painter.save()
    painter.translate(centre)
    # Rotated BEFORE scaling, so the caller's ``max_width_mm`` still means "across the
    # glyphs" rather than "across the screen" -- which is the whole point of turning a
    # row number on its side: the strip it has to fit into is narrow one way and a whole
    # pitch deep the other.
    if rotation_deg:
        painter.rotate(rotation_deg)
    painter.scale(scale, scale)
    painter.setFont(font)
    painter.drawText(
        QRectF(-width, -height, width * 2, height * 2), int(Qt.AlignmentFlag.AlignCenter), text
    )
    painter.restore()


def physical_label_width_mm(
    text: str, height_mm: float, max_width_mm: float | None = None, bold: bool = True
) -> float:
    """How long :func:`draw_physical_label` will draw ``text``, in millimetres -- so a
    caller can start a label at a point rather than centre it on one."""
    font = label_font(_PHYSICAL_FONT_PX, bold)
    metrics = QFontMetricsF(font)
    cap = metrics.capHeight()
    if cap <= 0:  # pragma: no cover - a platform with no font database
        cap = _PHYSICAL_FONT_PX * 0.7
    width = max(metrics.horizontalAdvance(text), 1.0) * height_mm / cap
    return min(width, max_width_mm) if max_width_mm is not None else width


def reference_plate(
    device_anchor: QPointF,
    reference: str,
    value: str,
    pixel_size: int,
    offset: QPointF | None = None,
) -> tuple[QRectF, QRectF, QRectF]:
    """Where a part's reference and, after it on the same plate, its value are drawn, in
    DEVICE pixels: (plate, reference box, value box), the text standing just above
    ``device_anchor`` and centred on it, as :func:`draw_label` sets a reference alone.

    ONE PLATE, ONE LINE: "R1 10k". The value is read as part of the name it belongs to,
    and it lands where the reference already does -- over the body, never on a pin row or
    a pin name, which is where a label of its own under the part would have had to go.
    """
    if offset is not None:
        device_anchor = device_anchor + offset
    bold = QFontMetricsF(label_font(pixel_size, True))
    plain = QFontMetricsF(label_font(pixel_size, False))
    reference_width = bold.horizontalAdvance(reference)
    gap = plain.horizontalAdvance(" ") if value else 0.0
    value_width = plain.horizontalAdvance(value) if value else 0.0
    height = bold.height()
    left = device_anchor.x() - (reference_width + gap + value_width) / 2
    top = device_anchor.y() - height
    reference_box = QRectF(left, top, reference_width, height)
    value_box = QRectF(left + reference_width + gap, top, value_width, height)
    plate = QRectF(left, top, reference_width + gap + value_width, height).adjusted(-4, -1, 4, 1)
    return plate, reference_box, value_box


def draw_reference(
    painter: QPainter,
    anchor: QPointF,
    reference: str,
    value: str,
    pixel_size: int,
    *,
    offset: QPointF | None,
    background: QColor,
    reference_colour: QColor,
    value_colour: QColor,
) -> None:
    """A reference with its value after it, on one plate, at a fixed ``pixel_size``
    (:func:`reference_plate` says where). The value in the regular weight and its own
    colour, so the name still reads first."""
    plate, reference_box, value_box = reference_plate(
        painter.transform().map(anchor), reference, value, pixel_size, offset
    )
    painter.save()
    painter.resetTransform()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(background)
    radius = QFontMetricsF(label_font(pixel_size, True)).height() * 0.3
    painter.drawRoundedRect(plate, radius, radius)
    left = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    painter.setPen(reference_colour)
    painter.setFont(label_font(pixel_size, True))
    painter.drawText(reference_box, left, reference)
    painter.setPen(value_colour)
    painter.setFont(label_font(pixel_size, False))
    painter.drawText(value_box, left, value)
    painter.restore()


def draw_printed_reference(
    painter: QPainter,
    anchor: QPointF,
    reference: str,
    value: str,
    height_mm: float,
    value_mm: float,
    gap_mm: float,
    *,
    background: QColor,
    reference_colour: QColor,
    value_colour: QColor,
) -> None:
    """The same plate in MILLIMETRES, for paper: standing ``gap_mm`` above the scene
    point ``anchor``, the reference ``height_mm`` tall and the value ``value_mm``, their
    feet on one line.

    The editor's labels hold a pixel size, which is right on a screen and wrong on a
    page: drawn into the 1:1 PDF, a 12 px reference came out 12 dots of a 600 dpi printer,
    half a millimetre, beside pin names printed at 0.9 mm. Paper gets its labels the way
    it gets everything else on it, in millimetres.
    """
    reference_width = physical_label_width_mm(reference, height_mm, bold=True)
    gap = height_mm * 0.45 if value else 0.0
    value_width = physical_label_width_mm(value, value_mm, bold=False) if value else 0.0
    width = reference_width + gap + value_width
    plate_height = height_mm * 1.8
    pad = height_mm * 0.35
    centre_y = anchor.y() - gap_mm - plate_height / 2
    left = anchor.x() - width / 2
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(background)
    plate = QRectF(left - pad, centre_y - plate_height / 2, width + 2 * pad, plate_height)
    painter.drawRoundedRect(plate, plate_height * 0.3, plate_height * 0.3)
    painter.setPen(reference_colour)
    draw_physical_label(
        painter, QPointF(left + reference_width / 2, centre_y), reference, height_mm, bold=True
    )
    if value:
        painter.setPen(value_colour)
        # Centred on the line a capital of its own height would stand on with the
        # reference's: down by half the difference.
        draw_physical_label(
            painter,
            QPointF(
                left + reference_width + gap + value_width / 2,
                centre_y + (height_mm - value_mm) / 2,
            ),
            value,
            value_mm,
            bold=False,
        )
    painter.restore()


#: Without a font to ask, how far a character of a pin name advances, per millimetre of
#: its height -- a capital's, which is what names mostly are.
_UNMEASURED_ADVANCE = 0.72


def pin_name_width_mm(name: str) -> float:
    """How long a pin name is printed, in millimetres.

    The one measure ``bodies.lay_out_pin_names`` is given by both views, so that both
    leave off the same names. With no Qt application there is no font to measure -- a 3D
    render from a bare engine -- and a capital's width per character stands in for it.
    """
    if QGuiApplication.instance() is None:
        return max(len(name), 1) * PIN_NAME_HEIGHT_MM * _UNMEASURED_ADVANCE
    return physical_label_width_mm(name, PIN_NAME_HEIGHT_MM, bold=False)


def label_extent_mm(pixel_size: int, scale: float) -> float:
    """How many millimetres of scene a ``pixel_size`` label occupies at ``scale`` px/mm.

    Items need this for ``boundingRect``: Qt uses the bounding rect to decide what to
    repaint, so a label drawn outside its item's rect can leave debris behind when the view
    scrolls. Since these labels do not shrink with the board, the scene-space room they need
    GROWS as the view zooms out -- the opposite of the usual intuition, and the reason this
    is computed rather than guessed at.
    """
    return pixel_size / max(scale, 0.01)
