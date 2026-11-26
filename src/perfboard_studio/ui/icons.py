"""Toolbar icons, drawn in code.

WHY NOT A SET OF SVG FILES. Twenty line drawings as assets would mean a Qt resource
system or a data directory to find at runtime, a licence to track, and a second place
where the palette lives -- and the first time the chrome colour changed, half of them
would be the old grey. These are drawn with the same ``theme`` tokens every panel uses,
so an icon cannot fall out of step with the window around it.

EACH ICON IS THREE PICTURES, inked for its state: secondary text with accent details at
rest, the accent when its tool is checked, and the tertiary text when it cannot be used.
One picture in one colour made a checked tool's icon the same grey as every other, so the
button's tint was the only thing saying which tool was armed.

Each drawing works in a 100 x 100 box and knows nothing about the icon's real size, so
the same function serves a 22 px toolbar and a hidpi screen. The pixmap is rendered at
twice the requested size and told so, which is what keeps the strokes sharp on a 200%
display instead of blurred like a scaled bitmap.

WHAT THE DRAWINGS SAY. Every conductor icon shows the SAME two pads and differs only in
what runs between them -- a solid bar for solder, a thin line for bare wire, a sleeved
line for insulated, an arc that lifts over the board for a top jumper. That is the one
distinction this application is about (``model.ConductorKind``), so it is the distinction
the icons are built around rather than four unrelated pictures.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap

from . import theme

#: Logical icon size. 22 px is the toolbar's, and the only size anything asks for.
SIZE = 22

#: Everything is drawn in this box and scaled down, so the code reads in round numbers.
BOX = 100.0

#: Stroke width in box units: 7.5/100 of the icon, a crisp ~1.65 px at 22 px. It was 8,
#: and the lighter line is the weight the rendered candidates were chosen at.
STROKE = 7.5

_cache: dict[str, QIcon] = {}
_pixmap_cache: dict[tuple[str, str, QIcon.Mode, QIcon.State], QPixmap] = {}


@dataclass(slots=True)
class _Ink:
    """What the drawing in progress is inked with: its lines, and its one accent."""

    body: str
    accent: str


_ink = _Ink(theme.ACTIVE.text_secondary, theme.ACTIVE.accent)


def _state_inks(
    tokens: theme.Tokens, mode: QIcon.Mode, state: QIcon.State
) -> tuple[QIcon.Mode, QIcon.State, str, str]:
    """Normalise ``(mode, state)`` to one of the three inked pictures and return its colours."""
    if mode == QIcon.Mode.Disabled:
        return (QIcon.Mode.Disabled, QIcon.State.Off, tokens.text_tertiary, tokens.text_tertiary)
    if state == QIcon.State.On:
        return (QIcon.Mode.Normal, QIcon.State.On, tokens.accent_text, tokens.accent_text)
    return (QIcon.Mode.Normal, QIcon.State.Off, tokens.text_secondary, tokens.accent)


def _pen(colour: str, width: float = STROKE) -> QPen:
    pen = QPen(QColor(colour), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _pad(painter: QPainter, x: float, y: float, r: float = 11.0) -> None:
    """A pad: the ring every conductor icon starts and ends on."""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(x, y), r, r)


def _dashed_segment(
    painter: QPainter,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    dashes: int = 3,
    ratio: float = 0.52,
) -> None:
    """Explicit round-cap dashes along a segment so Qt dash rounding never drifts at 22 px."""
    dx, dy = x1 - x0, y1 - y0
    step = 1.0 / dashes
    for index in range(dashes):
        t0 = index * step + step * (1.0 - ratio) * 0.5
        t1 = t0 + step * ratio
        painter.drawLine(QPointF(x0 + dx * t0, y0 + dy * t0), QPointF(x0 + dx * t1, y0 + dy * t1))


def _tray(painter: QPainter) -> None:
    """Open U-shaped tray shared by the Import and Export pair."""
    tray = QPainterPath(QPointF(16, 58))
    tray.lineTo(QPointF(16, 76))
    tray.quadTo(QPointF(16, 84), QPointF(24, 84))
    tray.lineTo(QPointF(76, 84))
    tray.quadTo(QPointF(84, 84), QPointF(84, 76))
    tray.lineTo(QPointF(84, 58))
    painter.drawPath(tray)


# ---------------------------------------------------------------------------
# The drawings
# ---------------------------------------------------------------------------


def _save(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(14, 14, 72, 72), 8, 8)
    p.drawRect(QRectF(34, 14, 32, 26))  # the shutter
    p.drawRect(QRectF(28, 56, 44, 30))  # the label


def _turn_arrow(p: QPainter, leftward: bool) -> None:
    """The undo/redo curve: over the top, with the head on the end it points at.

    One function for both, mirrored about the centre, so the pair cannot drift into
    looking like two different gestures.
    """
    # The drawing below points LEFT, which is undo; redo is the mirror of it.
    sign = 1.0 if leftward else -1.0

    def x(value: float) -> float:
        return 50.0 + sign * (value - 50.0)

    path = QPainterPath(QPointF(x(83), 80))
    path.cubicTo(QPointF(x(88), 24), QPointF(x(32), 14), QPointF(x(17), 45))
    p.drawPath(path)
    tip = QPointF(x(17), 45)
    p.drawLine(tip, QPointF(x(42), 45))
    p.drawLine(tip, QPointF(x(19), 20))


def _undo(p: QPainter) -> None:
    _turn_arrow(p, leftward=True)


def _redo(p: QPainter) -> None:
    _turn_arrow(p, leftward=False)


# The conductor tools are told apart by SHAPE, not by a line's weight. They were five
# lines between the same two pads -- thick, thick with a spine, thin, thin with a sleeve,
# curved -- and at 22 px Connect, Solder Trace, Bare Wire and Insulated Wire were all "a line
# between two dots": the builder could not tell them apart without a tooltip. Each is now
# what the thing looks like on a board: solder is beads flowed along a row of pads, a wire
# is bent up out of one hole and down into another, a jumper arches over a part, and
# Connect lays no copper at all, so its link is dashed -- an airwire.


def _beads(p: QPainter) -> None:
    """Three pads in a row with solder flowed along them: a bead on every pad it crosses,
    which is what a solder trace is and a wire is not."""
    p.setPen(_pen(_ink.body, 11.5))
    p.drawLine(QPointF(22, 50), QPointF(78, 50))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(_ink.body))
    for x in (22.0, 50.0, 78.0):
        p.drawEllipse(QPointF(x, 50), 13.0, 13.0)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _solder_trace(p: QPainter) -> None:
    _beads(p)
    # The holes, left open: a bead sits on a pad, around its hole.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.ACTIVE.bg_raised))
    for x in (22.0, 50.0, 78.0):
        p.drawEllipse(QPointF(x, 50), 4.0, 4.0)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _solder_trace_wired(p: QPainter) -> None:
    """The same beads with the wire they are flowed over showing through: the whole
    difference between the two."""
    _beads(p)
    p.setPen(_pen(_ink.accent, 5.5))
    p.drawLine(QPointF(14, 50), QPointF(86, 50))


def _staple() -> QPainterPath:
    """A wire bent up out of one hole, across, and down into another."""
    path = QPainterPath(QPointF(20, 64))
    path.lineTo(QPointF(20, 38))
    path.quadTo(QPointF(20, 20), QPointF(38, 20))
    path.lineTo(QPointF(62, 20))
    path.quadTo(QPointF(80, 20), QPointF(80, 38))
    path.lineTo(QPointF(80, 64))
    return path


def _bare_wire(p: QPainter) -> None:
    _pad(p, 20, 74, 9.5)
    _pad(p, 80, 74, 9.5)
    p.setPen(_pen(_ink.body, 6.5))
    p.drawPath(_staple())


def _insulated_wire(p: QPainter) -> None:
    """The same bent wire in its sleeve, bare only where it goes into the pads -- the
    sleeve is what lets it cross other copper, so it is the accent."""
    _bare_wire(p)
    sleeve = QPainterPath(QPointF(20, 52))
    sleeve.lineTo(QPointF(20, 38))
    sleeve.quadTo(QPointF(20, 20), QPointF(38, 20))
    sleeve.lineTo(QPointF(62, 20))
    sleeve.quadTo(QPointF(80, 20), QPointF(80, 38))
    sleeve.lineTo(QPointF(80, 52))
    p.setPen(_pen(_ink.accent, 14.0))
    p.drawPath(sleeve)


def _top_jumper(p: QPainter) -> None:
    """A wire arching over a part, from one of its pads to the other."""
    _pad(p, 20, 73, 8.5)
    _pad(p, 80, 73, 8.5)
    p.setPen(_pen(_ink.body, 6.0))
    p.drawRoundedRect(QRectF(36, 51, 28, 22), 4, 4)
    arch = QPainterPath(QPointF(20, 65))
    arch.cubicTo(QPointF(20, -2), QPointF(80, -2), QPointF(80, 65))
    p.setPen(_pen(_ink.accent, 7.0))
    p.drawPath(arch)


def _new_net(p: QPainter) -> None:
    """A new net: two connected pads and a balanced accent plus in the open corner."""
    _pad(p, 26, 74, 9.5)
    _pad(p, 76, 46, 9.5)
    p.drawLine(QPointF(34.5, 69.2), QPointF(67.5, 50.8))
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawLine(QPointF(16, 28), QPointF(40, 28))
    p.drawLine(QPointF(28, 16), QPointF(28, 40))


def _connect(p: QPainter) -> None:
    """Two pins and a dashed link between them: joined on the net, and no copper laid --
    the airwire the board draws for a connection still to be wired."""
    _pad(p, 20, 74, 11)
    _pad(p, 80, 26, 11)
    pen = _pen(_ink.accent, 7)
    pen.setDashPattern([1.6, 2.0])
    p.setPen(pen)
    p.drawLine(QPointF(29, 66), QPointF(71, 34))


def _autoroute(p: QPainter) -> None:
    _pad(p, 18, 78, 9)
    _pad(p, 82, 22, 9)
    p.setPen(_pen(_ink.accent, 7))
    path = QPainterPath(QPointF(26, 78))
    for point in (QPointF(50, 78), QPointF(50, 50), QPointF(72, 50), QPointF(72, 30)):
        path.lineTo(point)
    p.drawPath(path)


def _autoplace(p: QPainter) -> None:
    """Auto-arrange / Auto-place: neatly aligned component blocks with an accent sparkle."""
    p.drawRoundedRect(QRectF(16, 18, 28, 26), 5, 5)
    p.drawRoundedRect(QRectF(16, 56, 28, 28), 5, 5)
    p.drawRoundedRect(QRectF(56, 52, 28, 32), 5, 5)
    cx, cy, r, w = 70.0, 29.0, 17.5, 4.6
    spark = QPainterPath(QPointF(cx, cy - r))
    spark.lineTo(QPointF(cx + w, cy - w))
    spark.lineTo(QPointF(cx + r, cy))
    spark.lineTo(QPointF(cx + w, cy + w))
    spark.lineTo(QPointF(cx, cy + r))
    spark.lineTo(QPointF(cx - w, cy + w))
    spark.lineTo(QPointF(cx - r, cy))
    spark.lineTo(QPointF(cx - w, cy - w))
    spark.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(_ink.accent))
    p.drawPath(spark)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _rotate(p: QPainter) -> None:
    """Clockwise circular arrow with a crisp right-angle head."""
    p.drawArc(QRectF(20, 20, 62, 62), 40 * 16, 275 * 16)
    p.setPen(_pen(_ink.accent, STROKE))
    tip = QPointF(76, 31)
    p.drawLine(tip, QPointF(76, 15))
    p.drawLine(tip, QPointF(60, 31))


def _mirror(p: QPainter) -> None:
    """Horizontal reflection across a dashed centre axis: solid left, accent outline right."""
    p.setPen(_pen(_ink.body, 6.0))
    for y0, y1 in ((15, 27), (44, 56), (73, 85)):
        p.drawLine(QPointF(50, y0), QPointF(50, y1))

    left = QPainterPath(QPointF(37, 24))
    left.lineTo(QPointF(16, 76))
    left.lineTo(QPointF(37, 76))
    left.closeSubpath()
    p.setPen(_pen(_ink.body, STROKE))
    p.setBrush(QColor(_ink.body))
    p.drawPath(left)

    right = QPainterPath(QPointF(63, 24))
    right.lineTo(QPointF(84, 76))
    right.lineTo(QPointF(63, 76))
    right.closeSubpath()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawPath(right)


def _flip(p: QPainter) -> None:
    """The board turned over: a horizontal board slab and an accent arrow wrapping around
    its edge from the top face to the underside."""
    p.drawRoundedRect(QRectF(16, 40, 44, 14), 5, 5)
    p.setPen(_pen(_ink.accent, STROKE))
    arc = QPainterPath(QPointF(44, 20))
    arc.cubicTo(QPointF(96, 20), QPointF(96, 74), QPointF(44, 74))
    p.drawPath(arc)
    tip = QPointF(44, 74)
    p.drawLine(tip, QPointF(56, 64))
    p.drawLine(tip, QPointF(56, 84))


def _ratsnest(p: QPainter) -> None:
    """Four open pads (matching Connect) joined by crisp dashed airwires."""
    for x, y in ((24, 24), (76, 24), (24, 76), (76, 76)):
        _pad(p, x, y, 8.5)
    p.setPen(_pen(_ink.accent, 6.5))
    _dashed_segment(p, 36, 24, 64, 24, dashes=2, ratio=0.52)
    _dashed_segment(p, 36, 76, 64, 76, dashes=2, ratio=0.52)
    _dashed_segment(p, 66, 34, 34, 66, dashes=3, ratio=0.50)


def _cube(p: QPainter) -> None:
    top = [QPointF(50, 12), QPointF(86, 32), QPointF(50, 52), QPointF(14, 32)]
    path = QPainterPath(top[0])
    for point in top[1:]:
        path.lineTo(point)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(14, 32), QPointF(14, 68))
    p.drawLine(QPointF(86, 32), QPointF(86, 68))
    p.drawLine(QPointF(50, 52), QPointF(50, 88))
    p.drawLine(QPointF(14, 68), QPointF(50, 88))
    p.drawLine(QPointF(86, 68), QPointF(50, 88))


def _fit(p: QPainter) -> None:
    for x, y, dx, dy in ((16, 16, 1, 1), (84, 16, -1, 1), (16, 84, 1, -1), (84, 84, -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + 22 * dx, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + 22 * dy))
    p.drawRect(QRectF(38, 38, 24, 24))


def _delete(p: QPainter) -> None:
    p.drawLine(QPointF(16, 26), QPointF(84, 26))
    p.drawLine(QPointF(40, 26), QPointF(40, 16))
    p.drawLine(QPointF(60, 26), QPointF(60, 16))
    p.drawLine(QPointF(40, 16), QPointF(60, 16))
    path = QPainterPath(QPointF(24, 26))
    path.lineTo(QPointF(30, 88))
    path.lineTo(QPointF(70, 88))
    path.lineTo(QPointF(76, 26))
    p.drawPath(path)


def _import(p: QPainter) -> None:
    """Import into the project: an open tray with an accent arrow arriving from above."""
    _tray(p)
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawLine(QPointF(50, 16), QPointF(50, 62))
    p.drawLine(QPointF(34, 46), QPointF(50, 62))
    p.drawLine(QPointF(66, 46), QPointF(50, 62))


def _guide(p: QPainter) -> None:
    """The build guide: a numbered list."""
    p.drawRoundedRect(QRectF(18, 12, 64, 76), 6, 6)
    p.setPen(_pen(_ink.accent, 7))
    for y in (34, 52, 70):
        p.drawLine(QPointF(32, y), QPointF(68, y))


def _board(p: QPainter) -> None:
    """The board: a rectangle of substrate with a grid of holes punched through it.

    Holes and not parts, because what distinguishes this panel from the schematic is the
    perfboard itself -- the grid is the whole picture at 22 px, where a resistor is four
    grey pixels.
    """
    p.drawRoundedRect(QRectF(12, 18, 76, 64), 6, 6)
    p.setPen(_pen(_ink.accent, 6))
    for x in (30, 50, 70):
        for y in (36, 50, 64):
            p.drawEllipse(QPointF(x, y), 5, 5)


def _schematic(p: QPainter) -> None:
    """The sheet: a resistor zig-zag between two leads, which is the one symbol nobody
    mistakes for anything else at this size."""
    p.drawLine(QPointF(10, 50), QPointF(26, 50))
    path = QPainterPath(QPointF(26, 50))
    for i, y in enumerate((26, 74, 26, 74, 26, 74)):
        path.lineTo(QPointF(32 + i * 8, y))
    path.lineTo(QPointF(80, 50))
    p.drawPath(path)
    p.setPen(_pen(_ink.accent, 7))
    p.drawLine(QPointF(80, 50), QPointF(90, 50))


def _sch_add(p: QPainter) -> None:
    """Adding a part to the design: a rounded symbol box with leads and a clean accent plus."""
    p.drawRoundedRect(QRectF(22, 40, 38, 40), 6, 6)
    p.drawLine(QPointF(14, 60), QPointF(22, 60))
    p.drawLine(QPointF(60, 60), QPointF(68, 60))
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawLine(QPointF(74, 20), QPointF(74, 44))
    p.drawLine(QPointF(62, 32), QPointF(86, 32))


def _sch_place(p: QPainter) -> None:
    """The design going onto the board: a perfboard substrate with holes and a downward arrow."""
    p.drawRoundedRect(QRectF(18, 46, 64, 38), 7, 7)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(_ink.body))
    for x in (34.0, 50.0, 66.0):
        p.drawEllipse(QPointF(x, 68), 4.5, 4.5)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawLine(QPointF(50, 16), QPointF(50, 48))
    p.drawLine(QPointF(36, 34), QPointF(50, 48))
    p.drawLine(QPointF(64, 34), QPointF(50, 48))


def _float(p: QPainter) -> None:
    """A panel coming out of the window: an open frame with an arrow stepping out top-right."""
    frame = QPainterPath(QPointF(48, 24))
    frame.lineTo(QPointF(24, 24))
    frame.quadTo(QPointF(16, 24), QPointF(16, 32))
    frame.lineTo(QPointF(16, 76))
    frame.quadTo(QPointF(16, 84), QPointF(24, 84))
    frame.lineTo(QPointF(68, 84))
    frame.quadTo(QPointF(76, 84), QPointF(76, 76))
    frame.lineTo(QPointF(76, 52))
    p.drawPath(frame)
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawLine(QPointF(46, 54), QPointF(84, 16))
    head = QPainterPath(QPointF(62, 16))
    head.lineTo(QPointF(84, 16))
    head.lineTo(QPointF(84, 38))
    p.drawPath(head)


def _export(p: QPainter) -> None:
    """Export out of the project: the matching tray with an accent arrow leaving upward."""
    _tray(p)
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawLine(QPointF(50, 62), QPointF(50, 16))
    p.drawLine(QPointF(34, 32), QPointF(50, 16))
    p.drawLine(QPointF(66, 32), QPointF(50, 16))


def _label(p: QPainter) -> None:
    """A net label: the pointed flag a name is written in, on a stub of wire."""
    p.drawLine(QPointF(14, 50), QPointF(24, 50))
    flag = QPainterPath(QPointF(24, 28))
    flag.lineTo(QPointF(68, 28))
    flag.lineTo(QPointF(86, 50))
    flag.lineTo(QPointF(68, 72))
    flag.lineTo(QPointF(24, 72))
    flag.closeSubpath()
    p.drawPath(flag)
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawLine(QPointF(38, 50), QPointF(62, 50))


def _ground(p: QPainter) -> None:
    """A ground: a stem down from a pin, and three shrinking bars under it -- the glyph the
    sheet itself draws, so the button that puts one down shows what it puts down."""
    p.drawLine(QPointF(50, 14), QPointF(50, 50))
    p.drawLine(QPointF(18, 50), QPointF(82, 50))
    p.drawLine(QPointF(30, 68), QPointF(70, 68))
    p.drawLine(QPointF(42, 86), QPointF(58, 86))


def _supply(p: QPainter) -> None:
    """A supply rail: a stem up into an upward VCC rail triangle, pairing with Ground."""
    p.drawLine(QPointF(50, 84), QPointF(50, 46))
    tri = QPainterPath(QPointF(50, 16))
    tri.lineTo(QPointF(78, 46))
    tri.lineTo(QPointF(22, 46))
    tri.closeSubpath()
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawPath(tri)


def _text(p: QPainter) -> None:
    """A capital A, which is what every drawing tool marks its text tool with."""
    path = QPainterPath(QPointF(20, 84))
    path.lineTo(QPointF(50, 18))
    path.lineTo(QPointF(80, 84))
    p.drawPath(path)
    p.drawLine(QPointF(32, 60), QPointF(68, 60))


def _shape(p: QPainter) -> None:
    """A rounded square and a circle: the two shapes an annotation is made of."""
    p.drawRoundedRect(QRectF(16, 16, 44, 44), 7, 7)
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawEllipse(QPointF(64, 64), 20, 20)


def _arrow(p: QPainter) -> None:
    """The pointer: the tool that is no tool, which every editor needs a way back to."""
    path = QPainterPath(QPointF(26, 12))
    path.lineTo(QPointF(26, 82))
    path.lineTo(QPointF(44, 64))
    path.lineTo(QPointF(56, 90))
    path.lineTo(QPointF(68, 84))
    path.lineTo(QPointF(56, 58))
    path.lineTo(QPointF(80, 54))
    path.closeSubpath()
    p.drawPath(path)


def _measure(p: QPainter) -> None:
    """A ruler laid across the box, with its ticks: Measure Distance."""
    p.save()
    p.translate(50, 50)
    p.rotate(-45)
    p.drawRoundedRect(QRectF(-42, -14, 84, 28), 5, 5)
    for x, tall in ((-26, False), (-12, True), (2, False), (16, True), (30, False)):
        p.drawLine(QPointF(x, -14), QPointF(x, -2 if tall else -6))
    p.restore()


def _show(p: QPainter) -> None:
    """Three stacked layers: what is drawn on the board, layer by layer."""
    top = QPainterPath(QPointF(50, 16))
    top.lineTo(QPointF(84, 33))
    top.lineTo(QPointF(50, 50))
    top.lineTo(QPointF(16, 33))
    top.closeSubpath()
    p.drawPath(top)
    mid = QPainterPath(QPointF(16, 50))
    mid.lineTo(QPointF(50, 67))
    mid.lineTo(QPointF(84, 50))
    p.drawPath(mid)
    bot = QPainterPath(QPointF(16, 67))
    bot.lineTo(QPointF(50, 84))
    bot.lineTo(QPointF(84, 67))
    p.drawPath(bot)


def _zoom(p: QPainter, inward: bool) -> None:
    p.drawEllipse(QPointF(42, 42), 26, 26)
    p.drawLine(QPointF(61, 61), QPointF(86, 86))
    p.drawLine(QPointF(30, 42), QPointF(54, 42))
    if inward:
        p.drawLine(QPointF(42, 30), QPointF(42, 54))


def _zoom_in(p: QPainter) -> None:
    _zoom(p, True)


def _zoom_out(p: QPainter) -> None:
    _zoom(p, False)


def _cut_strip(p: QPainter) -> None:
    """A copper strip broken at a hole: Cut Strip."""
    p.drawLine(QPointF(10, 50), QPointF(34, 50))
    p.drawLine(QPointF(66, 50), QPointF(90, 50))
    p.drawEllipse(QPointF(50, 50), 12, 12)
    p.drawLine(QPointF(38, 30), QPointF(62, 70))


def _lock(p: QPainter) -> None:
    """A padlock: Toggle Lock."""
    p.drawRoundedRect(QRectF(22, 46, 56, 40), 6, 6)
    p.drawArc(QRectF(32, 16, 36, 56), 0, 180 * 16)
    p.drawLine(QPointF(32, 44), QPointF(32, 46))
    p.drawLine(QPointF(68, 44), QPointF(68, 46))


def _more(p: QPainter) -> None:
    """Three dots: the rest of what a right-click offers."""
    p.save()
    p.setBrush(p.pen().color())
    for x in (24, 50, 76):
        p.drawEllipse(QPointF(x, 50), 5, 5)
    p.restore()


def _search(p: QPainter) -> None:
    """A magnifier: find a command by its name."""
    p.drawEllipse(QPointF(44, 44), 26, 26)
    p.drawLine(QPointF(63, 63), QPointF(86, 86))


def _next_step(p: QPainter) -> None:
    """A step forward to a bar: the next step not done yet."""
    path = QPainterPath(QPointF(24, 20))
    path.lineTo(QPointF(64, 50))
    path.lineTo(QPointF(24, 80))
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(78, 20), QPointF(78, 80))


def _clear(p: QPainter) -> None:
    """A circle with a cross: clears progress ticks and dismisses canvas hints."""
    p.drawEllipse(QPointF(50, 50), 34, 34)
    p.setPen(_pen(_ink.accent, STROKE))
    p.drawLine(QPointF(37, 37), QPointF(63, 63))
    p.drawLine(QPointF(63, 37), QPointF(37, 63))


def _exploded(p: QPainter) -> None:
    """An isometric component layer lifted off the board with accent lift guides."""
    board = QPainterPath(QPointF(50, 62))
    board.lineTo(QPointF(84, 73))
    board.lineTo(QPointF(50, 84))
    board.lineTo(QPointF(16, 73))
    board.closeSubpath()
    p.drawPath(board)
    part = QPainterPath(QPointF(50, 16))
    part.lineTo(QPointF(76, 26))
    part.lineTo(QPointF(50, 36))
    part.lineTo(QPointF(24, 26))
    part.closeSubpath()
    p.drawPath(part)
    p.setPen(_pen(_ink.accent, 6.5))
    p.drawLine(QPointF(28, 43), QPointF(28, 56))
    p.drawLine(QPointF(72, 43), QPointF(72, 56))


def _camera(p: QPainter) -> None:
    """A camera: put the 3D camera back where it starts."""
    p.drawRoundedRect(QRectF(14, 32, 72, 50), 8, 8)
    p.drawRoundedRect(QRectF(36, 20, 28, 12), 3, 3)
    p.drawEllipse(QPointF(50, 57), 14, 14)


def _home(p: QPainter) -> None:
    """A house: Home, the page with the boards and the examples on it."""
    roof = QPainterPath(QPointF(14, 50))
    roof.lineTo(QPointF(50, 18))
    roof.lineTo(QPointF(86, 50))
    p.drawPath(roof)
    walls = QPainterPath(QPointF(26, 40))
    walls.lineTo(QPointF(26, 84))
    walls.lineTo(QPointF(74, 84))
    walls.lineTo(QPointF(74, 40))
    p.drawPath(walls)
    door = QPainterPath(QPointF(42, 84))
    door.lineTo(QPointF(42, 62))
    door.lineTo(QPointF(58, 62))
    door.lineTo(QPointF(58, 84))
    p.drawPath(door)


def _menu(p: QPainter) -> None:
    """Three lines: the menus, all of them, behind one button in the header."""
    for y in (28, 50, 72):
        p.drawLine(QPointF(18, y), QPointF(82, y))


def _new_circuit(p: QPainter) -> None:
    """A sheet with a plus at its corner: a new circuit, drawn on the sheet first."""
    sheet = QPainterPath(QPointF(56, 84))
    sheet.lineTo(QPointF(22, 84))
    sheet.quadTo(QPointF(16, 84), QPointF(16, 78))
    sheet.lineTo(QPointF(16, 18))
    sheet.quadTo(QPointF(16, 12), QPointF(22, 12))
    sheet.lineTo(QPointF(64, 12))
    sheet.quadTo(QPointF(70, 12), QPointF(70, 18))
    sheet.lineTo(QPointF(70, 50))
    p.drawPath(sheet)
    p.setPen(_pen(_ink.accent, 7))
    p.drawLine(QPointF(72, 60), QPointF(72, 88))
    p.drawLine(QPointF(58, 74), QPointF(86, 74))


def _open(p: QPainter) -> None:
    """A folder: open a board or a project from disk."""
    folder = QPainterPath(QPointF(12, 78))
    folder.lineTo(QPointF(12, 26))
    folder.quadTo(QPointF(12, 22), QPointF(16, 22))
    folder.lineTo(QPointF(38, 22))
    folder.lineTo(QPointF(46, 32))
    folder.lineTo(QPointF(80, 32))
    folder.quadTo(QPointF(84, 32), QPointF(84, 36))
    folder.lineTo(QPointF(84, 44))
    p.drawPath(folder)
    front = QPainterPath(QPointF(12, 78))
    front.lineTo(QPointF(24, 46))
    front.lineTo(QPointF(92, 46))
    front.lineTo(QPointF(80, 78))
    front.closeSubpath()
    p.drawPath(front)


def _tour(p: QPainter) -> None:
    """A play mark in a ring: the tour, a board walked through step by step."""
    p.drawEllipse(QPointF(50, 50), 37, 37)
    play = QPainterPath(QPointF(42, 34))
    play.lineTo(QPointF(66, 50))
    play.lineTo(QPointF(42, 66))
    play.closeSubpath()
    p.setPen(_pen(_ink.accent, 7))
    p.drawPath(play)


def _sun(p: QPainter) -> None:
    """A sun: the light theme. A disc and eight short rays, the rays in the accent."""
    p.drawEllipse(QPointF(50, 50), 17, 17)
    p.setPen(_pen(_ink.accent, 7))
    for step in range(8):
        angle = step * math.pi / 4
        dx, dy = math.cos(angle), math.sin(angle)
        p.drawLine(QPointF(50 + 29 * dx, 50 + 29 * dy), QPointF(50 + 39 * dx, 50 + 39 * dy))


def _moon(p: QPainter) -> None:
    """A crescent moon: the dark theme. One circle with a second taken out of it."""
    disc = QPainterPath()
    disc.addEllipse(QPointF(48, 52), 34, 34)
    bite = QPainterPath()
    bite.addEllipse(QPointF(68, 34), 28, 28)
    p.drawPath(disc.subtracted(bite))


#: Name -> drawing. The names are what the toolbar and the menus ask for.
DRAWINGS: dict[str, Callable[[QPainter], None]] = {
    "save": _save,
    "undo": _undo,
    "redo": _redo,
    "import": _import,
    "guide": _guide,
    "solder-trace": _solder_trace,
    "solder-trace-wired": _solder_trace_wired,
    "bare-wire": _bare_wire,
    "insulated-wire": _insulated_wire,
    "top-jumper": _top_jumper,
    "new-net": _new_net,
    "connect": _connect,
    "autoroute": _autoroute,
    "autoplace": _autoplace,
    "rotate": _rotate,
    "mirror": _mirror,
    "flip": _flip,
    "ratsnest": _ratsnest,
    "3d": _cube,
    "board": _board,
    "schematic": _schematic,
    "sch-add": _sch_add,
    "sch-place": _sch_place,
    "float": _float,
    "export": _export,
    "label": _label,
    "ground": _ground,
    "supply": _supply,
    "text": _text,
    "shape": _shape,
    "arrow": _arrow,
    "fit": _fit,
    "delete": _delete,
    "menu": _menu,
    "home": _home,
    "next-step": _next_step,
    "clear": _clear,
    "exploded": _exploded,
    "camera": _camera,
    "search": _search,
    "measure": _measure,
    "cut-strip": _cut_strip,
    "lock": _lock,
    "more": _more,
    "show": _show,
    "zoom-in": _zoom_in,
    "zoom-out": _zoom_out,
    "new-circuit": _new_circuit,
    "open": _open,
    "tour": _tour,
    "sun": _sun,
    "moon": _moon,
}


def _picture(draw: Callable[[QPainter], None], lines: str, accent: str) -> QPixmap:
    """One drawing in one pair of inks."""
    _ink.body, _ink.accent = lines, accent
    scale = 2  # Drawn at 2x and told so, which is what keeps it sharp on a hidpi screen.
    pixmap = QPixmap(SIZE * scale, SIZE * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(SIZE * scale / BOX, SIZE * scale / BOX)
    painter.setPen(_pen(lines))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw(painter)
    painter.end()
    pixmap.setDevicePixelRatio(float(scale))
    return pixmap


class _ThemedIconEngine(QIconEngine):
    """Paints a named icon from ``theme.ACTIVE`` so live theme switches recolour every
    action, button and menu without rebuilding them."""

    def __init__(self, name: str, draw: Callable[[QPainter], None]) -> None:
        super().__init__()
        self._name = name
        self._draw = draw

    def _base(self, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        tokens = theme.ACTIVE
        norm_mode, norm_state, lines, accent = _state_inks(tokens, mode, state)
        key = (tokens.name, self._name, norm_mode, norm_state)
        cached = _pixmap_cache.get(key)
        if cached is not None:
            return cached
        built = _picture(self._draw, lines, accent)
        _pixmap_cache[key] = built
        return built

    def actualSize(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QSize:
        return size.boundedTo(QSize(SIZE, SIZE))

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        base = self._base(mode, state)
        if size.isEmpty() or (size.width() >= SIZE and size.height() >= SIZE):
            return base
        scale = base.devicePixelRatio()
        scaled = base.scaled(
            QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale))),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(scale)
        return scaled

    def scaledPixmap(
        self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float
    ) -> QPixmap:
        return self.pixmap(size, mode, state)

    def paint(
        self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State
    ) -> None:
        painter.drawPixmap(rect, self._base(mode, state))

    def clone(self) -> QIconEngine:
        return _ThemedIconEngine(self._name, self._draw)


def icon(name: str) -> QIcon:
    """The named icon, backed by a live theme engine and cached per name.

    An unknown name gives an empty icon rather than raising: a missing picture is a
    cosmetic fault, and taking the window down over one would not be.
    """
    cached = _cache.get(name)
    if cached is not None:
        return cached

    draw = DRAWINGS.get(name)
    if draw is None:
        return QIcon()

    built = QIcon(_ThemedIconEngine(name, draw))
    _cache[name] = built
    return built


# ---------------------------------------------------------------------------
# Part pictures
# ---------------------------------------------------------------------------
#
# The library listed sixty-one parts as sixty-one lines of grey text, which is a poor way
# to answer the question people actually bring to it: "which of these is the fat blue one
# with a stripe". So each row now carries a small picture of the part.
#
# THE COLOURS ARE NOT DECORATION AND THEY ARE NOT CHOSEN HERE. Every one comes from
# ``bodies.style_for`` -- the same fill, edge and accent the 2D board and the 3D view draw
# that part with. An electrolytic is the same dark blue in the library, on the board and in
# the render, so picking one from the list and finding it on the board is recognition
# rather than reading. A second palette would drift the first time either was touched.
#
# The VIEW is per archetype, and deliberately not the board's top-down one: a resistor is
# recognised side-on by its bands, a DIP from above by its notch. These are pictures of
# parts as they sit in a drawer, because that is the question this list answers -- the
# board next to it is what shows the footprint.


#: Icon size for a tree row: the picture on its tile. Smaller than the toolbar's, which
#: is a button.
PART_SIZE = 26
#: The picture itself, inside the tile.
PICTURE_SIZE = 20
#: The tile's corner.
TILE_RADIUS = 6

#: Tinned component lead. Matches ``view2d.LEAD``, kept local so the icons do not drag in
#: the whole 2D scene module to draw a wire.
LEAD = "#c2c8d0"

_part_cache: dict[str, QIcon] = {}
_part_pixmap_cache: dict[str, QPixmap] = {}


def _fill(p: QPainter, style: Any, colour: str | None = None) -> None:
    p.setBrush(QColor(colour or style.fill))
    p.setPen(_pen(style.edge, 5))


def _leads(p: QPainter, xs: tuple[float, ...], top: float, bottom: float) -> None:
    p.setPen(_pen(LEAD, 6))
    for x in xs:
        p.drawLine(QPointF(x, top), QPointF(x, bottom))


def _axial(p: QPainter, style: Any, polarized: bool) -> None:
    """A resistor side-on -- or, polarized, a diode: same archetype, different object."""
    p.setPen(_pen(LEAD, 6))
    p.drawLine(QPointF(4, 50), QPointF(26, 50))
    p.drawLine(QPointF(74, 50), QPointF(96, 50))
    _fill(p, style)
    p.drawRoundedRect(QRectF(24, 32, 52, 36), 14, 14)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(style.accent))
    if polarized:
        p.drawRect(QRectF(64, 33, 8, 34))  # the cathode band, at one end only
    else:
        for x in (36, 46, 56):
            p.drawRect(QRectF(x, 33, 6, 34))


def _axial_upright(p: QPainter, style: Any, polarized: bool) -> None:
    """The same resistor or diode stood on end: the barrel upright over one lead, the other
    lead bent back over its top and down beside it."""
    p.setPen(_pen(LEAD, 6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(QPointF(40, 18))
    path.lineTo(QPointF(40, 12))
    path.arcTo(QRectF(40, 4, 24, 16), 180, -180)
    path.lineTo(QPointF(64, 96))
    p.drawPath(path)
    p.drawLine(QPointF(40, 80), QPointF(40, 96))
    _fill(p, style)
    p.drawRoundedRect(QRectF(26, 16, 28, 66), 12, 12)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(style.accent))
    if polarized:
        p.drawRect(QRectF(27, 24, 26, 8))  # the cathode band, at one end only
    else:
        for y in (30, 40, 50):
            p.drawRect(QRectF(27, y, 26, 6))


def _electrolytic(p: QPainter, style: Any) -> None:
    _leads(p, (42, 60), 70, 96)
    _fill(p, style)
    p.drawRoundedRect(QRectF(26, 12, 50, 62), 10, 10)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(style.accent))
    p.drawRect(QRectF(30, 18, 12, 50))  # the polarity stripe down one side
    p.setBrush(QColor(style.edge))
    p.drawEllipse(QRectF(30, 24, 12, 12))


def _disc(p: QPainter, style: Any) -> None:
    _leads(p, (40, 60), 66, 96)
    _fill(p, style)
    p.drawEllipse(QPointF(50, 42), 30, 30)


def _box_film(p: QPainter, style: Any) -> None:
    _leads(p, (38, 62), 70, 96)
    _fill(p, style)
    p.drawRoundedRect(QRectF(20, 16, 60, 56), 6, 6)
    p.setPen(_pen(style.accent, 5))
    p.drawLine(QPointF(30, 34), QPointF(70, 34))


def _dip(p: QPainter, style: Any) -> None:
    """From above, because the notch is how a DIP is recognised and which way up it goes."""
    p.setPen(_pen(LEAD, 7))
    for y in (30, 50, 70):
        p.drawLine(QPointF(8, y), QPointF(24, y))
        p.drawLine(QPointF(76, y), QPointF(92, y))
    _fill(p, style)
    p.drawRoundedRect(QRectF(22, 14, 56, 72), 4, 4)
    p.setPen(_pen(style.accent, 5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(38, 6, 24, 20), 180 * 16, 180 * 16)  # the pin-1 notch


def _to92(p: QPainter, style: Any) -> None:
    _leads(p, (36, 50, 64), 68, 96)
    _fill(p, style)
    path = QPainterPath()
    path.moveTo(QPointF(24, 56))
    path.arcTo(QRectF(20, 10, 60, 60), 190, -200)
    path.closeSubpath()
    p.drawPath(path)


def _to220(p: QPainter, style: Any) -> None:
    _leads(p, (36, 50, 64), 74, 96)
    # The tab first: it is metal, it is the part that bolts down, and it is why this
    # archetype is the one the heat rules care about.
    p.setBrush(QColor("#a8b0ba"))
    p.setPen(_pen("#5a626c", 5))
    p.drawRoundedRect(QRectF(28, 8, 44, 26), 4, 4)
    p.setBrush(QColor("#2b3038"))
    p.drawEllipse(QPointF(50, 18), 7, 7)
    _fill(p, style)
    p.drawRoundedRect(QRectF(26, 30, 48, 46), 4, 4)


def _led(p: QPainter, style: Any) -> None:
    # One lead longer than the other, which is the only thing on an LED that says which
    # way round it goes once it is out of the packet.
    p.setPen(_pen(LEAD, 6))
    p.drawLine(QPointF(40, 66), QPointF(40, 96))
    p.drawLine(QPointF(60, 66), QPointF(60, 84))
    _fill(p, style)
    path = QPainterPath()
    path.moveTo(QPointF(24, 70))
    path.lineTo(QPointF(24, 44))
    path.arcTo(QRectF(24, 14, 52, 60), 180, -180)
    path.lineTo(QPointF(76, 70))
    path.closeSubpath()
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(style.accent))
    p.drawEllipse(QRectF(34, 26, 12, 20))  # the highlight on the lens


def _pin_header(p: QPainter, style: Any) -> None:
    p.setPen(_pen(style.accent, 7))
    for x in (26, 42, 58, 74):
        p.drawLine(QPointF(x, 14), QPointF(x, 44))
        p.drawLine(QPointF(x, 66), QPointF(x, 92))
    _fill(p, style)
    p.drawRect(QRectF(16, 40, 68, 28))


def _pin_socket(p: QPainter, style: Any) -> None:
    """A female header from the front: all plastic, tall, its mouths along the top and
    only the legs below -- no pin stands out of it."""
    p.setPen(_pen(style.accent, 7))
    for x in (26, 42, 58, 74):
        p.drawLine(QPointF(x, 74), QPointF(x, 94))
    _fill(p, style)
    p.drawRect(QRectF(16, 14, 68, 62))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0))
    for x in (26, 42, 58, 74):
        p.drawRect(QRectF(x - 5, 20, 10, 10))


def _right_angle(p: QPainter, style: Any, female: bool) -> None:
    """A right-angle strip from the side: the leg up out of the board and bent over, the
    moulding lying on it, and a header's pin on out the far side."""
    p.setPen(_pen(style.accent, 7))
    reach = 50 if female else 92
    path = QPainterPath(QPointF(22, 94))
    path.lineTo(QPointF(22, 56))
    path.lineTo(QPointF(reach, 56))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    _fill(p, style)
    if female:
        p.drawRect(QRectF(40, 34, 52, 44))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0))
        p.drawRect(QRectF(82, 50, 7, 12))
    else:
        p.drawRect(QRectF(40, 38, 20, 36))


def _pin_header_ra(p: QPainter, style: Any) -> None:
    _right_angle(p, style, female=False)


def _pin_socket_ra(p: QPainter, style: Any) -> None:
    _right_angle(p, style, female=True)


def _box_header(p: QPainter, style: Any) -> None:
    """The header's pins inside a shroud, with the key slot cut in the near wall."""
    _fill(p, style)
    p.drawRect(QRectF(12, 26, 76, 50))
    p.setBrush(QColor(style.fill).lighter(160))
    p.drawRect(QRectF(20, 34, 60, 34))
    # The key slot, a gap in the near wall: the one thing a plain header does not have.
    p.setPen(_pen(style.edge, 1))
    p.setBrush(QColor(style.fill).lighter(160))
    p.drawRect(QRectF(40, 66, 20, 10))
    p.setPen(_pen(style.accent, 6))
    for x in (30, 44, 58, 72):
        p.drawPoint(QPointF(x, 44))
        p.drawPoint(QPointF(x, 58))


def _screw_terminal(p: QPainter, style: Any) -> None:
    _leads(p, (34, 66), 76, 96)
    _fill(p, style)
    p.drawRoundedRect(QRectF(16, 20, 68, 58), 5, 5)
    p.setBrush(QColor(style.accent))
    p.setPen(_pen(style.edge, 4))
    for x in (34, 66):
        p.drawEllipse(QPointF(x, 40), 12, 12)
        p.drawLine(QPointF(x - 7, 40), QPointF(x + 7, 40))


def _potentiometer(p: QPainter, style: Any) -> None:
    _leads(p, (30, 50, 70), 78, 96)
    _fill(p, style)
    p.drawRoundedRect(QRectF(18, 34, 64, 46), 5, 5)
    p.setBrush(QColor(style.accent))
    p.drawEllipse(QPointF(50, 30), 18, 18)
    p.setPen(_pen(style.edge, 6))
    p.drawLine(QPointF(50, 18), QPointF(50, 30))


def _tactile(p: QPainter, style: Any) -> None:
    p.setPen(_pen(LEAD, 6))
    for x, y in ((22, 26), (22, 74), (78, 26), (78, 74)):
        p.drawLine(QPointF(x, y), QPointF(x + (10 if x > 50 else -10), y))
    _fill(p, style)
    p.drawRoundedRect(QRectF(22, 16, 56, 68), 5, 5)
    p.setBrush(QColor(style.accent))
    p.drawEllipse(QPointF(50, 50), 16, 16)


def _crystal(p: QPainter, style: Any) -> None:
    _leads(p, (38, 62), 72, 96)
    _fill(p, style)
    p.drawRoundedRect(QRectF(22, 14, 56, 60), 24, 24)
    p.setPen(_pen(style.accent, 5))
    p.drawLine(QPointF(32, 28), QPointF(32, 60))  # the highlight down a metal can


def _relay(p: QPainter, style: Any) -> None:
    _leads(p, (28, 50, 72), 78, 96)
    _fill(p, style)
    p.drawRoundedRect(QRectF(14, 16, 72, 62), 6, 6)
    p.setPen(_pen(style.accent, 5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(26, 28, 48, 22))


def _module(p: QPainter, style: Any) -> None:
    """A small board of its own: a row of header pins down each long edge and a chip on
    it -- the silhouette of a devkit, which is what most modules are."""
    _fill(p, style)
    p.drawRoundedRect(QRectF(20, 8, 60, 84), 4, 4)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1b1d22"))
    p.drawRect(QRectF(36, 22, 28, 30))
    p.setPen(_pen("#d8b45a", 7))
    for y in (20, 36, 52, 68, 84):
        p.drawPoint(QPointF(28, y))
        p.drawPoint(QPointF(72, y))


def _smd_adapter(p: QPainter, style: Any) -> None:
    """A small square board with a header pin at each corner of its two rows and a chip
    on it with its gull-wing legs out sideways -- smaller than the board, which is the
    difference between this and a DIP at a glance."""
    _fill(p, style)
    p.drawRect(QRectF(14, 14, 72, 72))
    p.setPen(_pen(LEAD, 5))
    for y in (38, 50, 62):
        p.drawLine(QPointF(30, y), QPointF(40, y))
        p.drawLine(QPointF(60, y), QPointF(70, y))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#24262d"))
    p.drawRect(QRectF(38, 30, 24, 40))
    p.setPen(_pen("#d8b45a", 8))
    for y in (24, 38, 52, 66, 78):
        p.drawPoint(QPointF(22, y))
        p.drawPoint(QPointF(78, y))
    # The pin-1 dot on the chip, and the corner it belongs to.
    p.setPen(_pen(style.accent, 5))
    p.drawPoint(QPointF(43, 35))


def _flying_leads(p: QPainter, style: Any) -> None:
    """A row of pads, each with a wire rising out of it and curving away off the board --
    the only part of a panel pot or a jack the board ever has."""
    for x, colour in ((30, "#d32f2f"), (50, "#f2c418"), (70, "#212121")):
        _pad(p, x, 82, 9.0)
        path = QPainterPath()
        path.moveTo(QPointF(x, 78))
        path.cubicTo(QPointF(x, 40), QPointF(x + 4, 24), QPointF(x + 20, 12))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_pen(style.edge, 11))
        p.drawPath(path)
        p.setPen(_pen(colour, 7))
        p.drawPath(path)


def _generic(p: QPainter, style: Any) -> None:
    _leads(p, (36, 64), 72, 96)
    _fill(p, style)
    p.drawRoundedRect(QRectF(20, 20, 60, 52), 5, 5)


#: Archetype -> drawing. One per member of ``model.BodyArchetype``; a test fails if the
#: model gains one and this does not, because a part with no picture in a list of pictures
#: reads as a broken row rather than a missing icon.
PART_DRAWINGS: dict[str, Callable[[QPainter, Any], None]] = {
    "radial-electrolytic": _electrolytic,
    "disc-ceramic": _disc,
    "box-film": _box_film,
    "dip": _dip,
    "to92": _to92,
    "to220": _to220,
    "led-round": _led,
    "pin-header": _pin_header,
    "pin-socket": _pin_socket,
    "pin-header-ra": _pin_header_ra,
    "pin-socket-ra": _pin_socket_ra,
    "screw-terminal": _screw_terminal,
    "potentiometer": _potentiometer,
    "tactile-switch": _tactile,
    "crystal-hc49": _crystal,
    "relay-box": _relay,
    "generic-box": _generic,
    "box-header": _box_header,
    "wire-to-board": _box_header,
    "screw-terminal-vertical": _screw_terminal,
    "module-board": _module,
    "flying-leads": _flying_leads,
    "smd-adapter": _smd_adapter,
}


def _render_part_pixmap(archetype: str, polarized: bool, style: Any, tile_hex: str) -> QPixmap:
    key = f"{archetype}:{polarized}:{style.fill}:{tile_hex}"
    cached = _part_pixmap_cache.get(key)
    if cached is not None:
        return cached

    scale = 2
    pixmap = QPixmap(PART_SIZE * scale, PART_SIZE * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    # A soft tile under the picture: the parts are drawn in their own colours, and a black
    # TO-92 or a dark-blue electrolytic straight on the dark panel was a hole in the row.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(tile_hex))
    painter.drawRoundedRect(QRectF(0.5, 0.5, PART_SIZE - 1, PART_SIZE - 1), TILE_RADIUS, TILE_RADIUS)
    inset = (PART_SIZE - PICTURE_SIZE) / 2
    painter.translate(inset, inset)
    painter.scale(PICTURE_SIZE / BOX, PICTURE_SIZE / BOX)
    if archetype == "axial-cylinder":
        _axial(painter, style, polarized)
    elif archetype == "axial-upright":
        _axial_upright(painter, style, polarized)
    else:
        PART_DRAWINGS.get(archetype, _generic)(painter, style)
    painter.end()
    pixmap.setDevicePixelRatio(float(scale))
    _part_pixmap_cache[key] = pixmap
    return pixmap


class _PartIconEngine(QIconEngine):
    """Paints a part picture on ``theme.ACTIVE.icon_tile`` so library rows follow live switches."""

    def __init__(self, archetype: str, polarized: bool, style: Any) -> None:
        super().__init__()
        self._archetype = archetype
        self._polarized = polarized
        self._style = style

    def _base(self) -> QPixmap:
        return _render_part_pixmap(
            self._archetype, self._polarized, self._style, theme.ACTIVE.icon_tile
        )

    def actualSize(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QSize:
        return size.boundedTo(QSize(PART_SIZE, PART_SIZE))

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        base = self._base()
        if size.isEmpty() or (size.width() >= PART_SIZE and size.height() >= PART_SIZE):
            return base
        scale = base.devicePixelRatio()
        scaled = base.scaled(
            QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale))),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(scale)
        return scaled

    def scaledPixmap(
        self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float
    ) -> QPixmap:
        return self.pixmap(size, mode, state)

    def paint(
        self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State
    ) -> None:
        painter.drawPixmap(rect, self._base())

    def clone(self) -> QIconEngine:
        return _PartIconEngine(self._archetype, self._polarized, self._style)


def part_icon(footprint: Any, value: str | None = None) -> QIcon:
    """A small colour picture of this part, in the colours the board draws it in."""
    from .bodies import style_for

    archetype = footprint.body.archetype
    polarized = bool(footprint.polarized)
    style = style_for(footprint, value)
    key = f"{archetype}:{polarized}:{style.fill}:{style.edge}:{style.accent}"
    cached = _part_cache.get(key)
    if cached is not None:
        return cached
    built = QIcon(_PartIconEngine(archetype, polarized, style))
    _part_cache[key] = built
    return built
