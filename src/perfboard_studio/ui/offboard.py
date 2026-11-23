"""What a part off the board looks like: the thing itself, at its own size, beside the board.

WHY THIS EXISTS. A part on wires (``flying-leads``: a panel pot, a battery clip, a motor) and a
module on the end of a cable (a catalog part "on a header": an LCD, a relay module) were drawn
as what touches the board and nothing more -- grey wires leaving an edge with their ends
labelled, or a bare header. A board with a 9 V battery, a motor and an emergency stop showed
three identical bundles of wire. The builder thinks of the battery, the motor and the button,
not of the pads they land in, so each is drawn here as itself, at its true size, with its
wires carried on from the board's edge to the lug or the pin they are soldered to.

WHAT IT IS, by what the document already says: a part matched to its catalog entry by its
package and its value (the way ``moduleart`` reads a module's value), or else a flying-leads
part by its ``PartSymbol`` and a word in its value ("E-STOP", "Uno"). A module on a header
the catalog does not know stays a header: there is no telling what is on the other end of a
plain header.

ONLY ON THE SCREEN. Nothing here is the board: the 1:1 print, the PDF, the board picture and
every export draw what is inside the outline, and ``BoardScene`` leaves the things out unless
the window asks for them. WHERE each one stands is the part's ``off_board_at`` once the
builder has dragged it, and is worked out (``lay_out``) until then -- past the edge its wires
leave by, clear of the others.

Everything is drawn in millimetres in the thing's own frame: centred on the origin, unturned,
with the side its wires come in on facing +y unless ``Art.facing`` says otherwise.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QGraphicsItem

from perfboard_studio.catalog import catalog_part_placed_as, stands_off_board
from perfboard_studio.geometry import (
    EDGE_DIRECTIONS,
    all_pin_holes,
    flying_lead_routes,
    flying_lead_side,
)
from perfboard_studio.model import ComponentInstance, Footprint, PerfDocument, Point2, pin_name_of

#: How far past the board's edge a wire's run on the board ends: where the 2D view's flying
#: leads end, so a thing's cable carries on from the very point the part's wire stopped.
FLYING_LEAD_PAST_EDGE_MM = 3.5

#: A part is drawn turned a quarter so the side its wires come in on faces the board, and
#: never upside down: a thing below the board is drawn upright and its wires come round.
Facing = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Art:
    """One kind of thing, drawn from above (or from the front, for a panel part)."""

    key: str
    #: Width and height, millimetres, unturned.
    size: tuple[float, float]
    #: Draws the thing centred on the origin.
    draw: Callable[[QPainter], None]
    #: Where wire ``i`` of ``n`` lands, in the thing's frame.
    lands: Callable[[int], list[QPointF]]
    #: The way a wire leaves a landing, in the thing's frame.
    facing: Facing = (0.0, 1.0)
    #: Lettered across its length (a display, a relay module): never turned, the wires come
    #: round to it.
    upright: bool = False
    #: Round, its wires leaving from behind it (a panel button, a piezo disc): never turned,
    #: and its wires come out of whichever side faces the board.
    round_lands: bool = False
    #: Something printed on it that would read upside down: never turned a half turn. A pot,
    #: a jack or a motor has nothing to read, and below the board it is turned over so its
    #: lugs face the board instead of its wires running round it.
    lettered: bool = True
    #: Where the size comes from.
    source: str = ""


# --- drawing helpers -----------------------------------------------------------------------

#: Text is laid out this many pixels high and scaled down to millimetres: a font a millimetre
#: high is hinted to pieces.
_EM = 100.0


@lru_cache(maxsize=8)
def _font(bold: bool, mono: bool) -> QFont:
    font = QFont("Consolas" if mono else "Segoe UI")
    font.setPixelSize(int(_EM))
    font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def text_width_mm(text: str, height_mm: float, bold: bool = False) -> float:
    return QFontMetricsF(_font(bold, False)).horizontalAdvance(text) * height_mm / _EM


def draw_text(
    painter: QPainter,
    at: QPointF,
    text: str,
    height_mm: float,
    colour: QColor,
    *,
    bold: bool = False,
    centre: bool = False,
    mono: bool = False,
) -> None:
    """``text`` with its middle at ``at``, ``height_mm`` to the em."""
    font = _font(bold, mono)
    width = QFontMetricsF(font).horizontalAdvance(text)
    painter.save()
    painter.translate(at)
    painter.scale(height_mm / _EM, height_mm / _EM)
    painter.setFont(font)
    painter.setPen(colour)
    left = -width / 2 if centre else 0.0
    painter.drawText(
        QRectF(left, -_EM, width + 2.0, 2 * _EM),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        text,
    )
    painter.restore()


def _box(painter: QPainter, rect: QRectF, radius: float, fill: QColor | QBrush,
         edge: QColor | None = None, edge_mm: float = 0.3) -> None:
    painter.setPen(QPen(edge, edge_mm) if edge is not None else Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, radius, radius)


def _disc(painter: QPainter, centre: QPointF, radius: float, fill: QColor | QBrush,
          edge: QColor | None = None, edge_mm: float = 0.3) -> None:
    painter.setPen(QPen(edge, edge_mm) if edge is not None else Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawEllipse(centre, radius, radius)


def _across(x0: float, x1: float, colours: Sequence[tuple[float, str]]) -> QBrush:
    """A gradient across x, for a can or a cylinder lying down."""
    gradient = QLinearGradient(x0, 0.0, x1, 0.0)
    for at, colour in colours:
        gradient.setColorAt(at, QColor(colour))
    return QBrush(gradient)


def _hole(painter: QPainter, centre: QPointF, radius: float) -> None:
    _disc(painter, centre, radius + 0.3, QColor("#d8c79a"))
    _disc(painter, centre, radius, QColor("#16181d"))


def _pins(painter: QPainter, x0: float, y: float, count: int, *, female: bool,
          vertical: bool = False) -> None:
    """A row of 2.54 mm header positions from ``(x0, y)``."""
    pitch = 2.54
    if vertical:
        body = QRectF(y - 1.27, x0 - 1.27, 2.54, count * pitch)
    else:
        body = QRectF(x0 - 1.27, y - 1.27, count * pitch, 2.54)
    _box(painter, body, 0.2, QColor("#141416"))
    for i in range(count):
        c = QPointF(y, x0 + i * pitch) if vertical else QPointF(x0 + i * pitch, y)
        if female:
            _box(painter, QRectF(c.x() - 0.5, c.y() - 0.5, 1.0, 1.0), 0.1, QColor("#050506"))
        else:
            _box(painter, QRectF(c.x() - 0.32, c.y() - 0.32, 0.64, 0.64), 0.05, QColor("#d9b54a"))


def _spread(n: int, centre: QPointF, step: float, along_x: bool = True) -> list[QPointF]:
    """``n`` landings ``step`` apart about ``centre``."""
    first = -(n - 1) / 2 * step
    if along_x:
        return [QPointF(centre.x() + first + i * step, centre.y()) for i in range(n)]
    return [QPointF(centre.x(), centre.y() + first + i * step) for i in range(n)]


def _cycle(points: Sequence[QPointF], n: int) -> list[QPointF]:
    """``n`` landings from a thing with a fixed set of lugs: more wires share them."""
    return [points[i % len(points)] for i in range(n)]


_INK = QColor("#eef0f4")
_DARK_INK = QColor("#141416")
_GOLD = QColor("#d9b54a")
_STEEL = [(0.0, "#6d7178"), (0.18, "#c9cdd3"), (0.35, "#f4f5f7"), (0.6, "#aeb2b9"), (1.0, "#5d6168")]


# --- the things --------------------------------------------------------------------------

def _draw_battery_9v(p: QPainter) -> None:
    w, h = 26.5, 48.5
    _box(p, QRectF(-w / 2, -h / 2, w, h), 2.2,
         _across(-w / 2, w / 2, [(0, "#1a1a1c"), (0.5, "#38383c"), (1, "#141416")]))
    band = QRectF(-w / 2, -h / 2 + 8, w, 20)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_across(-w / 2, w / 2, [(0, "#b07a10"), (0.5, "#f0b830"), (1, "#9a6a0c")]))
    p.drawRect(band)
    draw_text(p, band.center(), "9V", 9.0, _DARK_INK, bold=True, centre=True)
    _box(p, QRectF(-w / 2 + 1.5, h / 2 - 9.5, w - 3, 8.5), 1.2, QColor("#0e0e10"), QColor("#2c2c30"))
    p.setPen(QPen(QColor("#8a8e96"), 0.3))
    p.setBrush(QColor("#c7cbd2"))
    p.drawPolygon([
        QPointF(-6.35 + 3.4 * math.cos(math.radians(a)), h / 2 - 5.2 + 3.4 * math.sin(math.radians(a)))
        for a in range(0, 360, 60)
    ])
    p.drawEllipse(QPointF(6.35, h / 2 - 5.2), 2.9, 2.9)


def _draw_aa_holder(p: QPainter) -> None:
    w, h = 31.5, 57.5
    _box(p, QRectF(-w / 2, -h / 2, w, h), 1.6, QColor("#18181a"), QColor("#2e2e32"))
    for x in (-7.4, 7.4):
        cell = QRectF(x - 7.1, -h / 2 + 3.5, 14.2, h - 7.0)
        _box(p, cell, 6.0, _across(cell.left(), cell.right(),
                                   [(0, "#7a2a10"), (0.4, "#e06a20"), (1, "#5a1a08")]))
        cap = QRectF(x - 7.1, -h / 2 + 3.5, 14.2, 9.0)
        _box(p, cap, 6.0, _across(cap.left(), cap.right(), _STEEL))
        draw_text(p, QPointF(x, 6.0), "AA", 4.0, _INK, bold=True, centre=True)
        _box(p, QRectF(x - 2.0, h / 2 - 3.6, 4.0, 1.6), 0.4, QColor("#c7cbd2"))


def _draw_dc_jack(p: QPainter) -> None:
    # A panel jack from the front: the nut on its thread, and the 5.5 mm socket.
    p.setPen(QPen(QColor("#6b6f78"), 0.25))
    p.setBrush(_across(-6.5, 6.5, _STEEL))
    p.drawPolygon([QPointF(6.5 * math.cos(math.radians(a + 30)), 6.5 * math.sin(math.radians(a + 30)))
                   for a in range(0, 360, 60)])
    _disc(p, QPointF(0, 0), 4.0, _across(-4, 4, _STEEL), QColor("#6b6f78"), 0.2)
    _disc(p, QPointF(0, 0), 2.75, QColor("#101012"))
    _disc(p, QPointF(0, 0), 1.05, _across(-1, 1, _STEEL))
    for x in (-3.0, 3.0):
        _box(p, QRectF(x - 1.0, 6.4, 2.0, 3.4), 0.3, QColor("#c9cdd3"), QColor("#7d828b"), 0.2)


def _draw_pot(p: QPainter) -> None:
    # A 16 mm pot from the front of the panel: its body behind, the nut, the knurled shaft.
    _disc(p, QPointF(0, 0), 8.0, _across(-8, 8, _STEEL), QColor("#5d6168"), 0.25)
    for x in (-5.0, 0.0, 5.0):
        _box(p, QRectF(x - 1.1, 6.6, 2.2, 5.0), 0.4, QColor("#c9cdd3"), QColor("#7d828b"), 0.2)
        _disc(p, QPointF(x, 10.2), 0.55, QColor("#1b1d24"))
    p.setPen(QPen(QColor("#6b6f78"), 0.25))
    p.setBrush(_across(-5.0, 5.0, _STEEL))
    p.drawPolygon([QPointF(5.0 * math.cos(math.radians(a + 30)), 5.0 * math.sin(math.radians(a + 30)))
                   for a in range(0, 360, 60)])
    _disc(p, QPointF(0, 0), 3.0, _across(-3, 3, _STEEL), QColor("#5d6168"), 0.2)
    p.setPen(QPen(QColor("#7d828b"), 0.15))
    for i in range(24):
        a = math.radians(i * 15)
        p.drawLine(QPointF(2.3 * math.cos(a), 2.3 * math.sin(a)), QPointF(3.0 * math.cos(a), 3.0 * math.sin(a)))
    p.setPen(QPen(QColor("#3a3d44"), 0.45))
    p.drawLine(QPointF(-2.0, 0.0), QPointF(2.0, 0.0))


def _draw_motor_130(p: QPainter) -> None:
    w = 20.1
    _box(p, QRectF(-1.0, -22.5, 2.0, 8.4), 0.4, QColor("#c9cdd3"))
    _box(p, QRectF(-w / 2, -14.5, w, 25.0), 1.2, _across(-w / 2, w / 2, _STEEL))
    _box(p, QRectF(-3.0, -15.6, 6.0, 1.4), 0.4, QColor("#9ea2aa"))
    _box(p, QRectF(-w / 2 + 0.6, 10.5, w - 1.2, 5.5), 1.4,
         _across(-w / 2, w / 2, [(0, "#2a2a2c"), (0.4, "#58585c"), (1, "#202022")]))
    for x in (-5.0, 5.0):
        _box(p, QRectF(x - 1.2, 15.8, 2.4, 2.6), 0.3, _GOLD)
    _disc(p, QPointF(-7.4, 12.6), 0.6, QColor("#c03a2a"))


def _draw_piezo(p: QPainter) -> None:
    _disc(p, QPointF(0, 0), 13.5, _across(-13.5, 13.5, [(0, "#8a6a20"), (0.4, "#e8c060"), (1, "#7a5a18")]),
          QColor("#6a4e10"), 0.25)
    _disc(p, QPointF(0, 0), 9.85, QColor("#f2f2f2"), QColor("#c8c8c8"), 0.2)
    _disc(p, QPointF(0, 0), 8.6, _across(-8.6, 8.6, _STEEL))
    for at in (QPointF(0, 6.0), QPointF(0, 11.4)):
        _disc(p, at, 0.9, QColor("#b8bcc4"), QColor("#7a7e86"), 0.15)


def _module_board(p: QPainter, w: float, h: float, colour: str, holes: bool = True) -> None:
    _box(p, QRectF(-w / 2, -h / 2, w, h), 0.8, QColor(colour), QColor(colour).darker(150))
    if holes:
        for x in (-w / 2 + 2.2, w / 2 - 2.2):
            for y in (-h / 2 + 2.2, h / 2 - 2.2):
                _hole(p, QPointF(x, y), 1.0)


def _draw_tp4056(p: QPainter) -> None:
    w, h = 26.0, 17.0
    _box(p, QRectF(-w / 2, -h / 2, w, h), 0.6, QColor("#1f4fa8"), QColor("#14336e"))
    _box(p, QRectF(-w / 2 - 1.0, -4.0, 6.0, 8.0), 0.8, _across(-4, 4, _STEEL))
    _box(p, QRectF(-2.5, -3.0, 5.0, 4.0), 0.3, QColor("#1c1c1f"))
    _box(p, QRectF(5.0, -5.5, 3.0, 2.0), 0.2, QColor("#1c1c1f"))
    _box(p, QRectF(5.0, 2.5, 3.0, 2.0), 0.2, QColor("#1c1c1f"))
    for x, y in ((-w / 2 + 2.0, -h / 2 + 2.0), (-w / 2 + 2.0, h / 2 - 2.0)):
        _disc(p, QPointF(x, y), 1.0, _GOLD)
    for i, label in enumerate(("B+", "OUT+", "OUT-", "B-")):
        y = -h / 2 + 2.0 + i * (h - 4.0) / 3
        _disc(p, QPointF(w / 2 - 2.0, y), 1.0, _GOLD)
        draw_text(p, QPointF(w / 2 - 6.5, y), label, 1.2, _INK, bold=True, centre=True)
    _disc(p, QPointF(-3.5, 5.5), 0.6, QColor("#ff3b30"))
    _disc(p, QPointF(-1.5, 5.5), 0.6, QColor("#30a0ff"))


def _draw_boost(p: QPainter, w: float, h: float, inductor: float) -> None:
    _box(p, QRectF(-w / 2, -h / 2, w, h), 0.6, QColor("#1f4fa8"), QColor("#14336e"))
    _box(p, QRectF(-inductor / 2 - 3.0, -inductor / 2, inductor, inductor), 1.2, QColor("#2a2b2f"))
    draw_text(p, QPointF(-3.0, 0.0), "220", 1.6, QColor("#9ea2aa"), bold=True, centre=True)
    _box(p, QRectF(w / 2 - 12.0, -h / 2 + 1.5, 6.5, 4.5), 0.4, QColor("#2f6fd0"), QColor("#1a4a90"), 0.2)
    _disc(p, QPointF(w / 2 - 10.0, -h / 2 + 3.75), 1.2, QColor("#c9a040"))
    _box(p, QRectF(w / 2 - 11.0, 2.0, 5.0, 3.0), 0.3, QColor("#1c1c1f"))
    for x in (-w / 2 + 2.2, w / 2 - 2.2):
        for y in (-h / 2 + 2.6, h / 2 - 2.6):
            _disc(p, QPointF(x, y), 1.2, _GOLD)
            _disc(p, QPointF(x, y), 0.6, QColor("#16181d"))
    draw_text(p, QPointF(-w / 2 + 5.0, -h / 2 + 2.6), "IN+", 1.2, _INK, bold=True, centre=True)
    draw_text(p, QPointF(-w / 2 + 5.0, h / 2 - 2.6), "IN-", 1.2, _INK, bold=True, centre=True)
    draw_text(p, QPointF(w / 2 - 5.2, -h / 2 + 2.6 + 4.4), "OUT+", 1.2, _INK, bold=True, centre=True)
    draw_text(p, QPointF(w / 2 - 5.2, h / 2 - 2.6), "OUT-", 1.2, _INK, bold=True, centre=True)


def _draw_ams1117(p: QPainter) -> None:
    w, h = 26.0, 11.0
    _box(p, QRectF(-w / 2, -h / 2, w, h), 0.6, QColor("#1f4fa8"), QColor("#14336e"))
    _box(p, QRectF(-3.3, -3.4, 6.6, 3.6), 0.2, QColor("#1c1c1f"))
    _box(p, QRectF(-1.5, -4.6, 3.0, 1.4), 0.1, QColor("#c4c8d0"))
    draw_text(p, QPointF(0.0, -1.6), "AMS1117", 0.9, QColor("#9ea2aa"), centre=True)
    _disc(p, QPointF(6.0, 2.5), 0.6, QColor("#ff3b30"))
    for i in range(4):
        _disc(p, QPointF(-w / 2 + 2.0, -3.81 + i * 2.54), 0.7, _GOLD)


def _draw_lcd_1602(p: QPainter) -> None:
    w, h = 80.0, 36.0
    _box(p, QRectF(-w / 2, -h / 2, w, h), 1.0, QColor("#1d6b33"), QColor("#124a22"))
    for x in (-w / 2 + 2.5, w / 2 - 2.5):
        for y in (-h / 2 + 2.5, h / 2 - 2.5):
            _hole(p, QPointF(x, y), 1.4)
    _box(p, QRectF(-35.5, -12.5, 71, 25), 0.6, QColor("#202226"))
    view = QRectF(-32.2, -7.7, 64.5, 15.4)
    gradient = QLinearGradient(0, view.top(), 0, view.bottom())
    gradient.setColorAt(0, QColor("#2f66e0"))
    gradient.setColorAt(1, QColor("#1f49b8"))
    _box(p, view, 0.3, QBrush(gradient))
    cell_w, cell_h, gap = 2.95, 5.55, 0.55
    x0 = -16 * (cell_w + gap) / 2 + gap / 2
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 18))
    for row in range(2):
        for col in range(16):
            p.drawRect(QRectF(x0 + col * (cell_w + gap), -6.4 + row * (cell_h + 0.7) + 0.2, cell_w, cell_h))
    _box(p, QRectF(-w / 2 - 0.2, -5.1, 2.6, 10.2), 0.2, QColor("#141416"))
    for i in range(4):
        _box(p, QRectF(-w / 2 - 4.0, -3.81 + i * 2.54 - 0.32, 5.5, 0.64), 0.05, _GOLD)


def _draw_relay_module(p: QPainter) -> None:
    w, h = 50.0, 26.0
    _box(p, QRectF(-w / 2, -h / 2, w, h), 0.8, QColor("#1c3f8f"), QColor("#12295e"))
    relay = QRectF(-6.0, -9.0, 19.0, 15.5)
    gradient = QLinearGradient(relay.topLeft(), relay.bottomRight())
    gradient.setColorAt(0, QColor("#3d8ff0"))
    gradient.setColorAt(1, QColor("#1f5fc0"))
    _box(p, relay, 0.8, QBrush(gradient))
    draw_text(p, QPointF(relay.center().x(), relay.top() + 3.5), "SONGLE", 2.4, _INK, bold=True, centre=True)
    draw_text(p, QPointF(relay.center().x(), relay.top() + 7.0), "SRD-05VDC-SL-C", 1.55, _INK, centre=True)
    draw_text(p, QPointF(relay.center().x(), relay.top() + 9.6), "10A 250VAC", 1.55, _INK, centre=True)
    terminal = QRectF(w / 2 - 8.0, -7.6, 7.6, 15.2)
    _box(p, terminal, 0.5, QColor("#2f6fd0"))
    for i, label in enumerate(("NO", "COM", "NC")):
        c = QPointF(terminal.center().x(), terminal.top() + 2.55 + i * 5.05)
        _disc(p, c, 1.8, QColor("#c9cdd3"), QColor("#6b6f78"), 0.2)
        p.setPen(QPen(QColor("#4a4e56"), 0.35))
        p.drawLine(QPointF(c.x() - 1.2, c.y()), QPointF(c.x() + 1.2, c.y()))
        draw_text(p, QPointF(terminal.left() - 3.0, c.y()), label, 1.5, _INK, bold=True, centre=True)
    _box(p, QRectF(-18.0, 3.5, 3.0, 4.5), 0.3, QColor("#151517"))
    _disc(p, QPointF(-17.0, -7.0), 1.1, QColor("#ff3b30"))
    for i in range(3):
        _box(p, QRectF(-w / 2 - 3.5, -2.54 + i * 2.54 - 0.32, 5.5, 0.64), 0.05, _GOLD)
    _box(p, QRectF(-w / 2 + 0.6, -3.9, 2.6, 7.8), 0.2, QColor("#141416"))


def _draw_servo(p: QPainter) -> None:
    w, h = 32.2, 12.2
    _box(p, QRectF(-w / 2, -1.25, w, 2.5), 0.6, QColor("#2f6fd0"))
    for x in (-w / 2 + 2.3, w / 2 - 2.3):
        _disc(p, QPointF(x, 0), 1.0, QColor("#16181d"))
    _box(p, QRectF(-11.1, -h / 2, 22.2, h), 0.8, QColor("#2f6fd0"), QColor("#1a4a90"))
    _disc(p, QPointF(-5.5, 0), 5.8, QColor("#3a7ee0"), QColor("#1a4a90"), 0.2)
    _box(p, QRectF(-5.5 - 1.6, -10.5, 3.2, 21.0), 1.6, QColor("#f2f2f2"), QColor("#b8bcc4"), 0.2)
    _disc(p, QPointF(-5.5, 0), 2.4, QColor("#f2f2f2"), QColor("#b8bcc4"), 0.2)
    draw_text(p, QPointF(4.5, 0), "SG90", 2.2, _INK, bold=True, centre=True)


def _draw_estop(p: QPainter) -> None:
    # A 22 mm emergency stop: the yellow legend plate and the red mushroom head.
    gradient = QRadialGradient(QPointF(0, 0), 30)
    gradient.setColorAt(0, QColor("#ffd94a"))
    gradient.setColorAt(1, QColor("#e5b300"))
    _disc(p, QPointF(0, 0), 30.0, QBrush(gradient), QColor("#9c7a00"))
    for i, ch in enumerate("EMERGENCY STOP"):
        a = math.radians(-152 + i * (124 / 13))
        p.save()
        p.translate(26.0 * math.cos(a), 26.0 * math.sin(a))
        p.rotate(math.degrees(a) + 90)
        draw_text(p, QPointF(0, 0), ch, 3.4, _DARK_INK, bold=True, centre=True)
        p.restore()
    _disc(p, QPointF(0, 0), 21.5, QColor("#2a2a2c"), QColor("#202020"))
    head = QRadialGradient(QPointF(-6, -7), 26)
    head.setColorAt(0, QColor("#ff6a5c"))
    head.setColorAt(0.45, QColor("#d4231b"))
    head.setColorAt(1, QColor("#7e0f0b"))
    _disc(p, QPointF(0, 0), 20.0, QBrush(head), QColor("#5e0a08"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 70))
    p.drawEllipse(QPointF(-7, -8.5), 6.5, 3.7)


def _draw_pushbutton(p: QPainter) -> None:
    # A 22 mm panel pushbutton: the bezel and a flush cap.
    _disc(p, QPointF(0, 0), 14.5, _across(-14.5, 14.5, _STEEL), QColor("#5d6168"))
    _disc(p, QPointF(0, 0), 11.0, QColor("#2a2a2c"))
    cap = QRadialGradient(QPointF(-3, -4), 14)
    cap.setColorAt(0, QColor("#6adf7a"))
    cap.setColorAt(1, QColor("#1f8a32"))
    _disc(p, QPointF(0, 0), 10.0, QBrush(cap), QColor("#14581f"))


def _draw_toggle(p: QPainter) -> None:
    # A miniature toggle from the front: the nut, the bushing and the bat.
    p.setPen(QPen(QColor("#6b6f78"), 0.25))
    p.setBrush(_across(-5.5, 5.5, _STEEL))
    p.drawPolygon([QPointF(5.5 * math.cos(math.radians(a + 30)), 5.5 * math.sin(math.radians(a + 30)))
                   for a in range(0, 360, 60)])
    _disc(p, QPointF(0, 0), 3.0, _across(-3, 3, _STEEL), QColor("#5d6168"), 0.2)
    _box(p, QRectF(-1.3, -9.5, 2.6, 9.5), 1.3, _across(-1.3, 1.3, _STEEL), QColor("#5d6168"), 0.2)
    for x in (-3.8, 0.0, 3.8):
        _box(p, QRectF(x - 0.9, 6.0, 1.8, 3.6), 0.3, QColor("#c9cdd3"), QColor("#7d828b"), 0.2)


def _draw_panel_led(p: QPainter) -> None:
    _disc(p, QPointF(0, 0), 5.0, _across(-5, 5, _STEEL), QColor("#5d6168"), 0.25)
    lens = QRadialGradient(QPointF(-1, -1.2), 4)
    lens.setColorAt(0, QColor("#ffb0a8"))
    lens.setColorAt(1, QColor("#c8201a"))
    _disc(p, QPointF(0, 0), 3.0, QBrush(lens))


def _draw_uno(p: QPainter) -> None:
    w, h = 68.6, 53.3
    _box(p, QRectF(-w / 2, -h / 2, w, h), 1.6, QColor("#007f86"), QColor("#005a60"))
    for x, y in ((-w / 2 + 14, -h / 2 + 2.5), (-w / 2 + 15.3, h / 2 - 2.5),
                 (w / 2 - 2.6, -h / 2 + 7.6), (w / 2 - 2.6, h / 2 - 7.6)):
        _hole(p, QPointF(x, y), 1.6)
    _box(p, QRectF(-w / 2 - 6.3, -h / 2 + 9.5, 16.0, 12.0), 0.6, _across(0, 1, _STEEL), QColor("#6b6f78"), 0.2)
    _box(p, QRectF(-w / 2 - 1.8, h / 2 - 17.0, 13.7, 9.0), 0.8, QColor("#151517"))
    _pins(p, -w / 2 + 18.0, -h / 2 + 1.6, 10, female=True)
    _pins(p, -w / 2 + 44.0, -h / 2 + 1.6, 8, female=True)
    _pins(p, -w / 2 + 27.5, h / 2 - 1.6, 8, female=True)
    _pins(p, -w / 2 + 50.4, h / 2 - 1.6, 6, female=True)
    chip = QRectF(-w / 2 + 31, h / 2 - 15.5, 35.5, 7.6)
    _box(p, chip.adjusted(-0.6, -1.6, 0.6, 1.6), 0.3, QColor("#e8e3d8"))
    _box(p, chip, 0.4, QColor("#1c1c1f"))
    draw_text(p, chip.center(), "ATMEGA328P", 1.9, QColor("#9ea2aa"), bold=True, centre=True)
    _box(p, QRectF(-w / 2 + 6.5, -h / 2 + 24.5, 6.0, 6.0), 0.5, QColor("#c9ccd2"))
    _disc(p, QPointF(-w / 2 + 9.5, -h / 2 + 27.5), 1.7, QColor("#2a2a2c"))
    draw_text(p, QPointF(w / 2 - 20, -h / 2 + 15), "UNO", 6.0, _INK, bold=True, centre=True)
    draw_text(p, QPointF(w / 2 - 20, -h / 2 + 20.5), "ARDUINO", 2.4, _INK, bold=True, centre=True)


def _uno_lands(n: int) -> list[QPointF]:
    w, h = 68.6, 53.3
    xs = [-w / 2 + 27.5 + i * 2.54 for i in range(8)] + [-w / 2 + 50.4 + i * 2.54 for i in range(6)]
    return [QPointF(xs[i % len(xs)], h / 2 - 1.6) for i in range(n)]


def _estop_lands(n: int) -> list[QPointF]:
    # The contact block is behind the plate; its wires show at the plate's lower rim.
    return [QPointF(x, 29.0) for x in _xs(n, 4.0)]


def _xs(n: int, step: float) -> list[float]:
    return [-(n - 1) / 2 * step + i * step for i in range(n)]


#: Board colours by maker, for a module nobody has drawn: the prefix of its catalog id.
_MAKER_COLOURS: Sequence[tuple[str, str]] = (
    ("adafruit-", "#1c1d20"),
    ("sparkfun-", "#b8262b"),
    ("ky-", "#1e1f24"),
    ("gy-", "#3b2c7e"),
)
_MODULE_BLUE = "#1c3f8f"


def _generic_module(name: str, pins: Sequence[str], catalog_id: str) -> Art:
    """A module the catalog knows and nobody has drawn: its maker's board colour, the header
    its cable plugs into with each pin's name printed beside it -- which is what its own
    silkscreen says -- and its name."""
    count = max(1, len(pins))
    w = max(24.0, count * 2.54 + 10.0)
    h = 20.0
    colour = next((c for prefix, c in _MAKER_COLOURS if catalog_id.startswith(prefix)), _MODULE_BLUE)
    first = -(count - 1) / 2 * 2.54

    def draw(p: QPainter) -> None:
        _module_board(p, w, h, colour)
        _pins(p, first, h / 2 - 1.6, count, female=False)
        for i, pin in enumerate(pins):
            p.save()
            p.translate(first + i * 2.54, h / 2 - 3.4)
            p.rotate(-90)
            draw_text(p, QPointF(0, 0), pin, 1.15, _INK, bold=True)
            p.restore()
        draw_text(p, QPointF(0, -h / 2 + 5.0), name, 2.4, _INK, bold=True, centre=True)

    return Art(f"module:{catalog_id}", (w, h), draw,
               lambda n: _cycle([QPointF(first + i * 2.54, h / 2 - 1.6) for i in range(count)], n),
               source="no drawing of this module yet: its header, its pin names and its name")


def _generic_thing(name: str) -> Art:
    w, h = max(20.0, text_width_mm(name, 2.0, bold=True) + 6.0), 14.0

    def draw(p: QPainter) -> None:
        _box(p, QRectF(-w / 2, -h / 2, w, h), 2.0, QColor("#3a3d44"), QColor("#5a5e66"))
        draw_text(p, QPointF(0, 0), name, 2.0, _INK, bold=True, centre=True)

    return Art("thing", (w, h), draw, lambda n: [QPointF(x, h / 2) for x in _xs(n, 2.54)],
               source="no idea what it is: a box with its name")


#: The things the catalog sells, by catalog id. Sizes are the maker's where ``source`` names
#: one and the common part's otherwise.
BY_CATALOG_ID: Mapping[str, Art] = {
    "battery-9v-clip": Art("battery-9v", (26.5, 48.5), _draw_battery_9v,
                           lambda n: _cycle([QPointF(-2.0, 24.0), QPointF(2.0, 24.0)], n),
                           source="IEC 6LR61 (PP3): 48.5 x 26.5 x 17.5 mm"),
    "battery-aa-holder": Art("battery-aa", (31.5, 57.5), _draw_aa_holder,
                             lambda n: _cycle([QPointF(-7.4, 28.0), QPointF(7.4, 28.0)], n),
                             source="two AA cells side by side, 14.5 x 50.5 mm each"),
    "dc-jack-panel": Art("dc-jack", (13.0, 20.0), _draw_dc_jack,
                         lambda n: _cycle([QPointF(-3.0, 9.8), QPointF(3.0, 9.8)], n), lettered=False,
                         source="5.5 x 2.1 mm panel jack on an M8 thread"),
    "pot-panel": Art("pot", (16.0, 23.0), _draw_pot,
                     lambda n: _cycle([QPointF(-5.0, 11.6), QPointF(0.0, 11.6), QPointF(5.0, 11.6)], n),
                     lettered=False, source="Alpha RV16: 16 mm body, M7 bushing, 6 mm shaft"),
    "dc-motor-130": Art("motor-130", (20.1, 41.0), _draw_motor_130,
                        lambda n: _cycle([QPointF(-5.0, 18.4), QPointF(5.0, 18.4)], n), lettered=False,
                        source="Mabuchi FA-130: 20.1 x 15.1 x 25.1 mm can, 2 mm shaft"),
    "piezo-disc-7bb": Art("piezo", (27.0, 27.0), _draw_piezo,
                          lambda n: _cycle([QPointF(0.0, 6.0), QPointF(0.0, 11.4)], n), upright=True, round_lands=True,
                          source="Murata 7BB-27-4: 27 mm plate, 19.7 mm element"),
    "tp4056-module": Art("tp4056", (28.0, 17.0), _draw_tp4056,
                         lambda n: _cycle([QPointF(11.0, -6.5), QPointF(11.0, -1.83), QPointF(11.0, 1.83),
                                           QPointF(11.0, 6.5), QPointF(-11.0, -6.5), QPointF(-11.0, 6.5)], n),
                         facing=(1.0, 0.0), source="the common TP4056 module with protection: 26 x 17 mm"),
    "mt3608-boost": Art("mt3608", (37.0, 17.0), lambda p: _draw_boost(p, 37.0, 17.0, 7.0),
                        lambda n: _cycle([QPointF(-16.3, -5.9), QPointF(-16.3, 5.9),
                                          QPointF(16.3, -5.9), QPointF(16.3, 5.9)], n),
                        facing=(0.0, 1.0), source="the common MT3608 module: 37 x 17 mm"),
    "xl6009-boost": Art("xl6009", (43.0, 21.0), lambda p: _draw_boost(p, 43.0, 21.0, 12.0),
                        lambda n: _cycle([QPointF(-19.3, -7.9), QPointF(-19.3, 7.9),
                                          QPointF(19.3, -7.9), QPointF(19.3, 7.9)], n),
                        facing=(0.0, 1.0), source="the common XL6009 module: 43 x 21 mm"),
    "ams1117-33-module": Art("ams1117", (26.0, 11.0), _draw_ams1117,
                             lambda n: _cycle([QPointF(-11.0, -3.81 + i * 2.54) for i in range(4)], n),
                             facing=(-1.0, 0.0), source="the common AMS1117 module: 26 x 11 mm"),
    "lcd-1602-i2c": Art("lcd-1602", (89.0, 36.0), _draw_lcd_1602,
                        lambda n: _cycle([QPointF(-44.0, -3.81 + i * 2.54) for i in range(4)], n),
                        facing=(-1.0, 0.0), upright=True, source="1602 character LCD: 80 x 36 mm"),
    "relay-module-1ch": Art("relay-module", (57.0, 26.0), _draw_relay_module,
                            lambda n: _cycle([QPointF(-28.5, -2.54 + i * 2.54) for i in range(3)], n),
                            facing=(-1.0, 0.0), upright=True,
                            source="the common 1-channel SRD-05VDC module: 50 x 26 mm"),
    "servo-header": Art("servo", (32.2, 22.0), _draw_servo,
                        lambda n: _cycle([QPointF(-1.0 + i, 6.1) for i in range(3)], n),
                        source="TowerPro SG90: 22.2 x 11.8 mm body, 32.2 mm over the tabs"),
}

#: Things a part on wires is, by what it is called, for parts the catalog did not supply.
BY_SYMBOL: Mapping[str, Art] = {
    "battery": BY_CATALOG_ID["battery-9v-clip"],
    "jack": BY_CATALOG_ID["dc-jack-panel"],
    "potentiometer": BY_CATALOG_ID["pot-panel"],
    "motor": BY_CATALOG_ID["dc-motor-130"],
    "buzzer": BY_CATALOG_ID["piezo-disc-7bb"],
    "button": Art("pushbutton", (29.0, 29.0), _draw_pushbutton,
                  lambda n: [QPointF(x, 14.0) for x in _xs(n, 4.0)], upright=True, round_lands=True,
                  source="a 22 mm panel pushbutton: 29 mm bezel"),
    "switch": Art("toggle", (11.0, 20.0), _draw_toggle,
                  lambda n: _cycle([QPointF(-3.8, 9.6), QPointF(0.0, 9.6), QPointF(3.8, 9.6)], n),
                  lettered=False, source="a miniature toggle on a 6 mm bushing"),
    "led": Art("panel-led", (10.0, 10.0), _draw_panel_led,
               lambda n: [QPointF(x, 5.0) for x in _xs(n, 2.54)], upright=True, round_lands=True,
               source="a 5 mm LED in a chrome bezel"),
}

#: Words in a value that say what a part on wires is, before its symbol does.
BY_WORD: Sequence[tuple[tuple[str, ...], Art]] = (
    (("e-stop", "estop", "emergency"), Art("estop", (60.0, 60.0), _draw_estop, _estop_lands, upright=True, round_lands=True,
                                           source="a 22 mm e-stop: 40 mm mushroom, 60 mm legend plate")),
    (("arduino uno", "uno r3"), Art("uno", (75.0, 53.3), _draw_uno, _uno_lands,
                                    source="Arduino Uno R3: 68.6 x 53.3 mm")),
)


def art_for(comp: ComponentInstance, footprint: Footprint) -> Art | None:
    """What ``comp`` is drawn as off the board, or None when it is on it.

    A part on wires is always off the board; a header is only when the catalog says a
    cable plugs into it -- a plain header could have anything on the other end, or nothing.
    """
    if not stands_off_board(comp, footprint):
        return None
    part = catalog_part_placed_as(comp)
    cabled = footprint.body.archetype != "flying-leads"
    if part is not None and part.id in BY_CATALOG_ID:
        return BY_CATALOG_ID[part.id]
    if cabled and part is not None:
        names = [pin_name_of(comp, pin) or pin.number for pin in footprint.pins]
        return _generic_module(comp.value or part.name, names, part.id)
    value = comp.value.lower()
    for words, art in BY_WORD:
        if any(word in value for word in words):
            return art
    if comp.symbol is not None and comp.symbol in BY_SYMBOL:
        return BY_SYMBOL[comp.symbol]
    return _generic_thing(comp.value or comp.ref)


# --- where they stand ----------------------------------------------------------------------

#: The edge a thing stands beyond, as the unit vector pointing off the board.
Side = tuple[float, float]

#: How far past the wires' ends a thing stands, and the room kept between two things.
STAND_OFF_MM = 8.0
CLEARANCE_MM = 3.0


def _turned(v: Facing, degrees: float) -> Facing:
    """``v`` turned on screen (y down) the way ``QPainter.rotate`` turns it."""
    a = math.radians(degrees)
    return (v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a))


def turn_for(art: Art, side: Side) -> float:
    """Degrees to turn the thing so its wires come in from the board's side.

    A quarter turn either way or none, never a half: a thing upside down has its print
    upside down, and a battery below the board is drawn upright with its wires coming round.
    A round or lettered thing (``Art.upright``) is never turned at all.
    """
    if art.upright:
        return 0.0
    towards = (-side[0], -side[1])

    def facing_the_board(degrees: float) -> float:
        f = _turned(art.facing, degrees)
        return f[0] * towards[0] + f[1] * towards[1]

    turns = (0.0, 90.0, -90.0) if art.lettered else (0.0, 90.0, -90.0, 180.0)
    return max(turns, key=facing_the_board)


def turned_size(art: Art, turn: float) -> tuple[float, float]:
    w, h = art.size
    return (h, w) if abs(turn) == 90.0 else (w, h)


def _angle_to(v: Facing, target: Facing) -> float:
    """Degrees that turn ``v`` onto ``target``, both unit vectors."""
    return math.degrees(math.atan2(target[1], target[0]) - math.atan2(v[1], v[0]))


def lands_of(art: Art, turn: float, side: Side, n: int) -> tuple[list[QPointF], QPointF]:
    """Where ``n`` wires land on the thing as drawn, and the way they come in, in the
    thing's frame. A round thing's lands turn to face the board; the drawing does not."""
    spin = _angle_to(art.facing, (-side[0], -side[1])) if art.round_lands else turn
    points = []
    for p in art.lands(n):
        x, y = _turned((p.x(), p.y()), spin)
        points.append(QPointF(x, y))
    nx, ny = _turned(art.facing, spin)
    return points, QPointF(nx, ny)


@dataclass(frozen=True, slots=True)
class Wanted:
    """A thing to stand somewhere: its size as drawn, where its wires end and which edge
    they left by."""

    key: str
    size: tuple[float, float]
    ends: tuple[QPointF, ...]
    side: Side
    #: The middle of its lugs, from its centre: a display wired at one end stands with
    #: that end over the wires, not its middle.
    lands_centre: tuple[float, float] = (0.0, 0.0)


def _beyond(want: Wanted, outline: QRectF) -> QRectF:
    """The first place for it: past the board on its wires' side, centred on their ends."""
    w, h = want.size
    xs = [p.x() for p in want.ends]
    ys = [p.y() for p in want.ends]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    lcx, lcy = want.lands_centre
    if want.side == (0.0, -1.0):
        cx, cy = mx - lcx, min(min(ys), outline.top()) - STAND_OFF_MM - h / 2
    elif want.side == (0.0, 1.0):
        cx, cy = mx - lcx, max(max(ys), outline.bottom()) + STAND_OFF_MM + h / 2
    elif want.side == (1.0, 0.0):
        cx, cy = max(max(xs), outline.right()) + STAND_OFF_MM + w / 2, my - lcy
    else:
        cx, cy = min(min(xs), outline.left()) - STAND_OFF_MM - w / 2, my - lcy
    return QRectF(cx - w / 2, cy - h / 2, w, h)


#: A cable, for the layout: from the middle of its wires' ends to the middle of its lugs.
Corridor = tuple[QPointF, QPointF]
#: Half the width of the band a bundle of cables takes.
CORRIDOR_HALF_MM = 2.0
#: The last stretch of a cable, where it arrives at its own lugs: allowed over its own thing.
ARRIVAL_MM = 4.0
#: How far a thing is tried along its edge, and in what steps.
SEARCH_STEP_MM = 1.5
SEARCH_STEPS = 160


def _middle(points: Sequence[QPointF]) -> QPointF:
    return QPointF(sum(p.x() for p in points) / len(points), sum(p.y() for p in points) / len(points))


def _corridor(want: Wanted, rect: QRectF) -> Corridor:
    lx, ly = want.lands_centre
    return _middle(want.ends), QPointF(rect.center().x() + lx, rect.center().y() + ly)


def _crosses(corridor: Corridor, rect: QRectF) -> bool:
    """Whether the band a cable takes runs through ``rect`` before it arrives (Liang-Barsky
    on the segment, against the rectangle grown by half the band)."""
    a, b = corridor
    dx, dy = b.x() - a.x(), b.y() - a.y()
    run = math.hypot(dx, dy)
    if run <= ARRIVAL_MM:
        return False
    stop = 1.0 - ARRIVAL_MM / run
    grown = rect.adjusted(-CORRIDOR_HALF_MM, -CORRIDOR_HALF_MM, CORRIDOR_HALF_MM, CORRIDOR_HALF_MM)
    low, high = 0.0, stop
    for p, q in (
        (-dx, a.x() - grown.left()),
        (dx, grown.right() - a.x()),
        (-dy, a.y() - grown.top()),
        (dy, grown.bottom() - a.y()),
    ):
        if p == 0.0:
            if q < 0.0:
                return False
            continue
        t = q / p
        if p < 0.0:
            low = max(low, t)
        else:
            high = min(high, t)
        if low > high:
            return False
    return True


def _inside(rect: QRectF) -> QRectF:
    """A thing's own body, for its own cable: short of the edge its lugs are on."""
    m = CORRIDOR_HALF_MM + 1.0
    return rect.adjusted(m, m, -m, -m)


def _clear(
    want: Wanted,
    rect: QRectF,
    board: QRectF,
    taken: Sequence[QRectF],
    corridors: Sequence[Corridor],
    cables_too: bool,
) -> bool:
    """Whether ``want`` can stand at ``rect``: clear of the board and of every thing standing
    and, with ``cables_too``, off every other thing's cable, with its own cable running past
    nothing -- itself included, so a display wired at one end is not stood with that end away
    from the board and its cable under it."""
    grown = rect.adjusted(-CLEARANCE_MM, -CLEARANCE_MM, CLEARANCE_MM, CLEARANCE_MM)
    if grown.intersects(board) or any(grown.intersects(other) for other in taken):
        return False
    if not cables_too:
        return True
    if any(_crosses(corridor, rect) for corridor in corridors):
        return False
    own = _corridor(want, rect)
    return not any(_crosses(own, other) for other in [*taken, _inside(rect)])


def _nearest_clear(
    want: Wanted, board: QRectF, taken: Sequence[QRectF], corridors: Sequence[Corridor], outline: QRectF
) -> QRectF:
    """The smallest move along the edge, either way, or outward, to where it is clear --
    of the cables too if anywhere is, and of the things alone if nowhere is."""
    first = _beyond(want, outline)
    side = want.side
    along = (abs(side[1]), abs(side[0]))
    for cables_too in (True, False):
        if _clear(want, first, board, taken, corridors, cables_too):
            return first
        for i in range(1, SEARCH_STEPS):
            step = i * SEARCH_STEP_MM
            for dx, dy in (
                (along[0] * step, along[1] * step),
                (-along[0] * step, -along[1] * step),
                (side[0] * step, side[1] * step),
            ):
                moved = first.translated(dx, dy)
                if _clear(want, moved, board, taken, corridors, cables_too):
                    return moved
    return first


def _greedy(
    order: Sequence[Wanted], board: QRectF, outline: QRectF, kept: Mapping[str, QPointF]
) -> dict[str, QRectF]:
    placed: dict[str, QRectF] = {}
    taken: list[QRectF] = []
    corridors: list[Corridor] = []
    for want in order:
        centre = kept.get(want.key)
        if centre is not None:
            w, h = want.size
            rect = QRectF(centre.x() - w / 2, centre.y() - h / 2, w, h)
            if rect.intersects(board):
                # Dropped on the board, or the board grew under it since: drawn there it
                # would hide the parts it stands on, so it is laid out like one never moved.
                continue
            placed[want.key] = rect
            taken.append(rect)
            corridors.append(_corridor(want, rect))
    for want in order:
        if want.key in placed:
            continue
        rect = _nearest_clear(want, board, taken, corridors, outline)
        placed[want.key] = rect
        taken.append(rect)
        corridors.append(_corridor(want, rect))
    return placed


def _cost(wanted: Sequence[Wanted], placed: Mapping[str, QRectF], outline: QRectF) -> tuple[int, float]:
    """How bad a layout is: the cables that run under a thing, then how far things went."""
    crossings = 0
    moved = 0.0
    for want in wanted:
        rect = placed[want.key]
        corridor = _corridor(want, rect)
        crossings += sum(
            1 for other in wanted if other.key != want.key and _crosses(corridor, placed[other.key])
        )
        crossings += _crosses(corridor, _inside(rect))
        first = _beyond(want, outline).center()
        moved += math.hypot(rect.center().x() - first.x(), rect.center().y() - first.y())
    return crossings, round(moved, 6)


def lay_out(
    wanted: Sequence[Wanted], outline: QRectF, kept: Mapping[str, QPointF]
) -> dict[str, QRectF]:
    """Where each thing stands: where it was dragged to, or past its edge, clear of the rest.

    The board, grown by the room its wires' markers take, is in the way of every thing worked
    out; so is every thing already standing, and every cable already running to one -- a
    battery laid over a display's cable hides the cable it would have to be lifted off. A
    thing's own cable may not run under another thing, or under itself, either.

    One thing at a time, each where it first fits, so the order matters: a battery placed
    first can take the very place a relay module beside it needed. So a few orders are tried
    -- the document's, the biggest first, the smallest first, along the board -- and the one
    whose cables run under the fewest things, then whose things moved least, is kept. Dragged
    things stand first in every order, so one the builder put somewhere is never pushed.
    Deterministic: the same board lays out the same way every time it is drawn.
    """
    board = outline.adjusted(-STAND_OFF_MM + 2.0, -STAND_OFF_MM + 2.0, STAND_OFF_MM - 2.0, STAND_OFF_MM - 2.0)
    if not wanted:
        return {}

    def area(want: Wanted) -> float:
        return want.size[0] * want.size[1]

    def along(want: Wanted) -> tuple[float, float, float]:
        middle = _middle(want.ends)
        return (want.side[0], want.side[1], middle.x() + middle.y())

    orders = (
        list(wanted),
        sorted(wanted, key=area, reverse=True),
        sorted(wanted, key=area),
        sorted(wanted, key=along),
        list(reversed(wanted)),
    )
    best: dict[str, QRectF] | None = None
    best_cost: tuple[int, float] | None = None
    for order in orders:
        placed = _greedy(order, board, outline, kept)
        cost = _cost(wanted, placed, outline)
        if best_cost is None or cost < best_cost:
            best, best_cost = placed, cost
        if cost[0] == 0 and order is orders[0]:
            break
    assert best is not None
    return best


# --- the item ------------------------------------------------------------------------------

#: How far a cable runs straight out of the board's edge and into a lug before it bends.
CABLE_REACH_MM = 6.0
#: A cable's jacket, as the flying leads on the board draw it.
CABLE_MM = 1.0
#: The housing a jumper's end is crimped into, pushed over a header pin.
DUPONT_MM = 2.4
#: The name under a thing, millimetres high.
TAG_MM = 2.4
TAG_GAP_MM = 2.0
TAG_INK = QColor("#c9ccd3")


@dataclass(frozen=True, slots=True)
class Cable:
    """One wire from the board to the thing: the run on the board (header modules only,
    pin to past the edge; a part on wires draws its own), its colour, and the way it
    leaves the board's edge."""

    on_board: tuple[QPointF, ...]
    end: QPointF
    colour: QColor


class OffBoardItem(QGraphicsItem):
    """The thing a part off the board is, standing beside the board with its wires to it.

    Dragged, it moves itself while the button is down and leaves where it was let go with
    the scene (``on_dropped``), which dispatches ``component.placeOffBoard`` once the
    release is over -- the command rebuilds the scene, and an item that dispatched from its
    own handler would be destroyed inside it. Pressed, it selects its PART, so Properties,
    the right-click menu and Delete all act on the part it is a picture of.
    """

    def __init__(
        self,
        comp: ComponentInstance,
        art: Art,
        turn: float,
        centre: QPointF,
        cables: Sequence[Cable],
        side: Side,
        owner: QGraphicsItem | None,
        on_dropped: Callable[[str, Point2], None] | None = None,
    ) -> None:
        super().__init__()
        #: Told where the thing was let go, once a drag is over -- the scene, which
        #: dispatches the command after the release has finished with this item.
        self.on_dropped = on_dropped
        self.comp = comp
        self.art = art
        self.turn = turn
        self.cables = tuple(cables)
        self.side = side
        self.owner = owner
        self.setPos(centre)
        self.setZValue(55)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(f"{comp.ref} {comp.value}".strip())
        self._press: QPointF | None = None
        self._start = QPointF()
        self.moved = False
        w, h = turned_size(art, turn)
        self._body = QRectF(-w / 2, -h / 2, w, h)
        self._tag = f"{comp.ref}  {comp.value}".strip() if comp.value else comp.ref

    # -- geometry -------------------------------------------------------------------------

    def lands(self) -> list[QPointF]:
        """Where each cable lands on the thing, in item coordinates, paired with the cables
        in the order both lie along the board's edge, so they do not cross on the way."""
        points, _normal = lands_of(self.art, self.turn, self.side, len(self.cables))
        along = (abs(self.side[1]), abs(self.side[0]))

        def key(p: QPointF) -> float:
            return p.x() * along[0] + p.y() * along[1]

        order = sorted(range(len(self.cables)), key=lambda i: key(self.mapFromScene(self.cables[i].end)))
        paired: list[QPointF] = [QPointF()] * len(self.cables)
        for slot, land in zip(order, sorted(points, key=key), strict=True):
            paired[slot] = land
        return paired

    def _land_normal(self) -> QPointF:
        return lands_of(self.art, self.turn, self.side, len(self.cables))[1]

    def _paths(self) -> list[tuple[QPainterPath, QColor, list[QPointF]]]:
        """Each cable as a path in item coordinates: along the board, then a curve from the
        edge to its lug, leaving the edge straight and arriving square to the lug."""
        normal = self._land_normal()
        out = []
        for cable, land in zip(self.cables, self.lands(), strict=True):
            end = self.mapFromScene(cable.end)
            path = QPainterPath()
            board = [self.mapFromScene(p) for p in cable.on_board]
            if board:
                path.moveTo(board[0])
                for p in board[1:]:
                    path.lineTo(p)
                path.lineTo(end)
            else:
                path.moveTo(end)
            reach = min(CABLE_REACH_MM * 2.5, max(CABLE_REACH_MM, math.hypot(land.x() - end.x(), land.y() - end.y()) / 2.5))
            out_of_edge = QPointF(end.x() + self.side[0] * reach, end.y() + self.side[1] * reach)
            into_lug = QPointF(land.x() + normal.x() * reach, land.y() + normal.y() * reach)
            path.cubicTo(out_of_edge, into_lug, land)
            out.append((path, cable.colour, [*board, end, out_of_edge, into_lug, land]))
        return out

    def _tag_centre(self) -> QPointF:
        above = self.side == (0.0, -1.0)
        y = self._body.top() - TAG_GAP_MM - TAG_MM / 2 if above else self._body.bottom() + TAG_GAP_MM + TAG_MM / 2
        return QPointF(0.0, y)

    def boundingRect(self) -> QRectF:
        rect = self._body.adjusted(-1.0, -1.0, 1.0, 1.0)
        half = text_width_mm(self._tag, TAG_MM, bold=True) / 2 + 1.0
        tag = self._tag_centre()
        rect = rect.united(QRectF(tag.x() - half, tag.y() - TAG_MM, 2 * half, 2 * TAG_MM))
        for _path, _colour, points in self._paths():
            for p in points:
                rect = rect.united(QRectF(p.x() - 2.0, p.y() - 2.0, 4.0, 4.0))
        return rect

    def shape(self) -> QPainterPath:
        """The thing and its name: what a click picks up. Not its cables, which cross the
        board over the parts a click there means."""
        path = QPainterPath()
        path.addRect(self._body)
        return path

    # -- painting -------------------------------------------------------------------------

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for path, colour, points in self._paths():
            for pen_colour, width in ((QColor(0, 0, 0, 150), CABLE_MM + 0.22), (colour, CABLE_MM)):
                pen = QPen(pen_colour, width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
            if len(points) > 5:
                # A jumper's housing, pushed over the header pin the run starts at.
                pin = points[0]
                _box(painter, QRectF(pin.x() - DUPONT_MM / 2, pin.y() - DUPONT_MM / 2, DUPONT_MM, DUPONT_MM),
                     0.25, QColor("#141416"), QColor(colour), 0.3)
        painter.save()
        painter.rotate(self.turn)
        self.art.draw(painter)
        painter.restore()
        if self.owner is not None and self.owner.isSelected():
            pen = QPen(SELECTED_RING, 0)
            pen.setWidthF(2.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self._body.adjusted(-1.2, -1.2, 1.2, 1.2), 1.5, 1.5)
        draw_text(painter, self._tag_centre(), self._tag, TAG_MM, TAG_INK, bold=True, centre=True)

    # -- dragging -------------------------------------------------------------------------

    def mousePressEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        scene = self.scene()
        if self.owner is not None and scene is not None:
            if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                scene.clearSelection()
            self.owner.setSelected(True)
        self._press = event.scenePos()
        self._start = self.pos()
        self.moved = False
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event: Any) -> None:
        if self._press is None:
            return
        if not self.moved:
            travelled = event.screenPos() - event.buttonDownScreenPos(Qt.MouseButton.LeftButton)
            if travelled.manhattanLength() < QApplication.startDragDistance():
                return
        self.moved = True
        self.prepareGeometryChange()
        self.setPos(self._start + (event.scenePos() - self._press))

    def mouseReleaseEvent(self, event: Any) -> None:
        self._press = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self.moved and self.on_dropped is not None:
            self.on_dropped(self.comp.id, Point2(round(self.x(), 2), round(self.y(), 2)))
        event.accept()


#: The ring round a thing whose part is selected: the 2D view's selection colour.
SELECTED_RING = QColor("#4f8cff")


def things_for(
    document: PerfDocument,
    lookup: Callable[[str], Footprint | None],
    colour_of: Callable[[ComponentInstance, str], QColor],
    owners: Mapping[str, QGraphicsItem],
    outline: QRectF,
    on_dropped: Callable[[str, Point2], None] | None = None,
) -> list[OffBoardItem]:
    """Every part off the board on ``document``, as the thing it is, laid out beside it.

    A part on the solder side is left out: its wires are drawn from that side, and a thing
    standing beside the component side would be wired to nothing.
    """
    board = document.board
    found: list[tuple[ComponentInstance, Art, float, Side, list[Cable]]] = []
    for comp in document.components:
        if comp.side != "top":
            continue
        fp = lookup(comp.footprint_id)
        if fp is None:
            continue
        art = art_for(comp, fp)
        if art is None:
            continue
        routes = flying_lead_routes(comp, fp, board, FLYING_LEAD_PAST_EDGE_MM)
        if not routes:
            continue
        holes = [at for _pin, at in all_pin_holes(comp, fp)]
        d_col, d_row = EDGE_DIRECTIONS[flying_lead_side(holes, board)]
        side: Side = (float(d_col), float(d_row))
        drawn_by_part = fp.body.archetype == "flying-leads"
        cables = [
            Cable(
                on_board=() if drawn_by_part else tuple(QPointF(p.x, p.y) for p in points[:-1]),
                end=QPointF(points[-1].x, points[-1].y),
                colour=colour_of(comp, number),
            )
            for number, points in routes
        ]
        found.append((comp, art, turn_for(art, side), side, cables))
    wanted = []
    for comp, art, turn, side, cables in found:
        w, h = turned_size(art, turn)
        lands, _normal = lands_of(art, turn, side, len(cables))
        centre = (sum(p.x() for p in lands) / len(lands), sum(p.y() for p in lands) / len(lands))
        # Its name stands above or below it: room for it is part of the room it takes.
        wanted.append(
            Wanted(comp.id, (w, h + 2 * (TAG_GAP_MM + TAG_MM)), tuple(c.end for c in cables), side, centre)
        )
    kept = {
        comp.id: QPointF(comp.off_board_at.x, comp.off_board_at.y)
        for comp, *_rest in found
        if comp.off_board_at is not None
    }
    rects = lay_out(wanted, outline, kept)
    return [
        OffBoardItem(
            comp, art, turn, rects[comp.id].center(), cables, side, owners.get(comp.id), on_dropped
        )
        for comp, art, turn, side, cables in found
    ]
