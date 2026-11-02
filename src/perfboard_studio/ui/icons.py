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

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import ACTIVE as TOKENS

#: Logical icon size. 22 px is the toolbar's, and the only size anything asks for.
SIZE = 22

#: Everything is drawn in this box and scaled down, so the code reads in round numbers.
BOX = 100.0

#: Stroke width in box units: 7.5/100 of the icon, a crisp ~1.65 px at 22 px. It was 8,
#: and the lighter line is the weight the rendered candidates were chosen at.
STROKE = 7.5

_cache: dict[str, QIcon] = {}


@dataclass(slots=True)
class _Ink:
    """What the drawing in progress is inked with: its lines, and its one accent."""

    body: str
    accent: str


_ink = _Ink(TOKENS.text_secondary, TOKENS.accent)

#: (mode, state, lines, accent) for each picture an icon carries.
_STATES = (
    (QIcon.Mode.Normal, QIcon.State.Off, TOKENS.text_secondary, TOKENS.accent),
    (QIcon.Mode.Normal, QIcon.State.On, TOKENS.accent_text, TOKENS.accent_text),
    (QIcon.Mode.Disabled, QIcon.State.Off, TOKENS.text_tertiary, TOKENS.text_tertiary),
)


def _pen(colour: str, width: float = STROKE) -> QPen:
    pen = QPen(QColor(colour), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _pad(painter: QPainter, x: float, y: float, r: float = 11.0) -> None:
    """A pad: the ring every conductor icon starts and ends on."""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(x, y), r, r)


def _arrow_head(painter: QPainter, tip: QPointF, dx: float, dy: float) -> None:
    """A two-stroke head at ``tip``, opening back along (dx, dy)."""
    painter.drawLine(tip, QPointF(tip.x() + dx, tip.y() + dy))
    painter.drawLine(tip, QPointF(tip.x() + dy, tip.y() - dx))


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
        return 50 + sign * (value - 50)

    path = QPainterPath(QPointF(x(78), 74))
    path.cubicTo(QPointF(x(88), 26), QPointF(x(34), 18), QPointF(x(24), 46))
    p.drawPath(path)
    # The head sits on the tip and opens back along the curve, which at this point is
    # heading down and outwards.
    tip = QPointF(x(24), 46)
    p.drawLine(tip, QPointF(x(46), 42))
    p.drawLine(tip, QPointF(x(26), 22))


def _undo(p: QPainter) -> None:
    _turn_arrow(p, leftward=True)


def _redo(p: QPainter) -> None:
    _turn_arrow(p, leftward=False)


def _conductor(p: QPainter, run: Callable[[QPainter], None]) -> None:
    """Two pads with something between them: the shape every conductor icon shares."""
    _pad(p, 22, 72)
    _pad(p, 78, 28)
    run(p)


def _solder_trace(p: QPainter) -> None:
    def run(p: QPainter) -> None:
        p.setPen(_pen(_ink.body, 15))  # thick: solder is the widest thing on the board
        p.drawLine(QPointF(30, 64), QPointF(70, 36))

    _conductor(p, run)


def _solder_trace_wired(p: QPainter) -> None:
    """The same run with a wire spine down it -- the whole difference between the two."""

    def run(p: QPainter) -> None:
        p.setPen(_pen(_ink.body, 15))
        p.drawLine(QPointF(30, 64), QPointF(70, 36))
        p.setPen(_pen(_ink.accent, 5))
        p.drawLine(QPointF(28, 62), QPointF(72, 34))

    _conductor(p, run)


def _bare_wire(p: QPainter) -> None:
    def run(p: QPainter) -> None:
        p.setPen(_pen(_ink.body, 6))
        p.drawLine(QPointF(30, 64), QPointF(70, 36))

    _conductor(p, run)


def _insulated_wire(p: QPainter) -> None:
    def run(p: QPainter) -> None:
        p.setPen(_pen(_ink.body, 6))
        p.drawLine(QPointF(30, 64), QPointF(70, 36))
        # The sleeve, which is the whole difference between this and bare wire.
        p.setPen(_pen(_ink.body, 16))
        p.drawLine(QPointF(42, 55), QPointF(58, 45))

    _conductor(p, run)


def _top_jumper(p: QPainter) -> None:
    def run(p: QPainter) -> None:
        path = QPainterPath(QPointF(26, 66))
        path.cubicTo(QPointF(30, 16), QPointF(70, 16), QPointF(74, 32))
        p.setPen(_pen(_ink.body, 6))
        p.drawPath(path)

    _conductor(p, run)


def _new_net(p: QPainter) -> None:
    _pad(p, 30, 74, 10)
    _pad(p, 76, 40, 10)
    p.drawLine(QPointF(38, 68), QPointF(68, 46))
    p.setPen(_pen(_ink.accent, 10))
    p.drawLine(QPointF(14, 26), QPointF(42, 26))
    p.drawLine(QPointF(28, 12), QPointF(28, 40))


def _connect(p: QPainter) -> None:
    """Two pads and the link between them, with the second pad picked out.

    The accent is doing real work: this is the two-click tool, and the icon says the
    second click is the one that makes the connection.
    """
    _pad(p, 24, 70, 11)
    p.drawLine(QPointF(33, 62), QPointF(67, 38))
    p.setPen(_pen(_ink.accent))
    _pad(p, 76, 30, 11)


def _autoroute(p: QPainter) -> None:
    _pad(p, 18, 78, 9)
    _pad(p, 82, 22, 9)
    p.setPen(_pen(_ink.accent, 7))
    path = QPainterPath(QPointF(26, 78))
    for point in (QPointF(50, 78), QPointF(50, 50), QPointF(72, 50), QPointF(72, 30)):
        path.lineTo(point)
    p.drawPath(path)


def _autoplace(p: QPainter) -> None:
    """A part moved into its place: where it was, where it goes, and the move."""
    pen = _pen(_ink.body, 6)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawRoundedRect(QRectF(10, 14, 36, 24), 4, 4)
    p.setPen(_pen(_ink.body))
    p.drawRoundedRect(QRectF(54, 58, 36, 24), 4, 4)
    p.setPen(_pen(_ink.accent, 7))
    p.drawLine(QPointF(40, 44), QPointF(62, 56))
    p.drawLine(QPointF(62, 56), QPointF(44, 56))
    p.drawLine(QPointF(62, 56), QPointF(62, 38))


def _rotate(p: QPainter) -> None:
    p.drawArc(QRectF(20, 20, 60, 60), 40 * 16, 270 * 16)
    _arrow_head(p, QPointF(72, 26), -4, 20)


def _mirror(p: QPainter) -> None:
    pen = _pen(_ink.body, 5)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawLine(QPointF(50, 10), QPointF(50, 90))
    p.setPen(_pen(_ink.body))
    for direction in (-1, 1):
        path = QPainterPath(QPointF(50 + 12 * direction, 24))
        path.lineTo(QPointF(50 + 34 * direction, 50))
        path.lineTo(QPointF(50 + 12 * direction, 76))
        path.closeSubpath()
        p.drawPath(path)


def _flip(p: QPainter) -> None:
    """The board turned over: the face you are on, the face you would get, and the turn.

    Drawn as two boards side by side rather than one board with an arrow through it,
    because the thing being switched is WHICH SIDE you are looking at, and a picture of a
    single board says nothing about there being two of them.
    """
    p.drawRoundedRect(QRectF(10, 44, 34, 44), 5, 5)
    pen = _pen(_ink.body, 6)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawRoundedRect(QRectF(56, 44, 34, 44), 5, 5)
    p.setPen(_pen(_ink.accent, 7))
    path = QPainterPath(QPointF(20, 36))
    path.cubicTo(QPointF(34, 8), QPointF(66, 8), QPointF(80, 36))
    p.drawPath(path)
    p.drawLine(QPointF(80, 36), QPointF(62, 32))
    p.drawLine(QPointF(80, 36), QPointF(80, 16))


def _ratsnest(p: QPainter) -> None:
    for x, y in ((22, 30), (78, 26), (34, 78), (76, 74)):
        p.setBrush(QColor(_ink.body))
        p.drawEllipse(QPointF(x, y), 7, 7)
    p.setBrush(Qt.BrushStyle.NoBrush)
    pen = _pen(_ink.accent, 6)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawLine(QPointF(22, 30), QPointF(78, 26))
    p.drawLine(QPointF(22, 30), QPointF(34, 78))
    p.drawLine(QPointF(34, 78), QPointF(76, 74))


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
    """A netlist arriving from somewhere else: a sheet, and an arrow into the board."""
    p.drawRoundedRect(QRectF(12, 14, 44, 56), 5, 5)
    p.setPen(_pen(_ink.accent, 7))
    p.drawLine(QPointF(46, 78), QPointF(84, 78))
    _arrow_head(p, QPointF(86, 78), -16, -8)


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
    """Adding a part to the design: a symbol outline and a plus."""
    p.drawRect(QRectF(14, 30, 46, 40))
    p.drawLine(QPointF(6, 50), QPointF(14, 50))
    p.drawLine(QPointF(60, 50), QPointF(68, 50))
    p.setPen(_pen(_ink.accent, 9))
    p.drawLine(QPointF(80, 20), QPointF(80, 52))
    p.drawLine(QPointF(64, 36), QPointF(96, 36))


def _sch_place(p: QPainter) -> None:
    """The design going onto the board: a symbol, an arrow, a grid of holes."""
    p.drawRect(QRectF(8, 34, 28, 26))
    p.drawRoundedRect(QRectF(60, 26, 34, 44), 4, 4)
    for x in (70, 84):
        for y in (38, 50, 62):
            p.drawEllipse(QPointF(x, y), 3.5, 3.5)
    p.setPen(_pen(_ink.accent, 7))
    p.drawLine(QPointF(38, 47), QPointF(54, 47))
    _arrow_head(p, QPointF(56, 47), -12, -7)


def _float(p: QPainter) -> None:
    """A panel coming out of the window: a frame, and a smaller one lifted off it."""
    p.drawRect(QRectF(10, 24, 50, 46))
    p.setPen(_pen(_ink.accent, 7))
    p.drawRect(QRectF(44, 44, 46, 38))
    p.drawLine(QPointF(44, 54), QPointF(90, 54))


def _export(p: QPainter) -> None:
    """A sheet and an arrow leaving it."""
    p.drawRoundedRect(QRectF(12, 14, 46, 72), 5, 5)
    p.setPen(_pen(_ink.accent, 7))
    p.drawLine(QPointF(52, 50), QPointF(90, 50))
    _arrow_head(p, QPointF(92, 50), -16, -8)


def _label(p: QPainter) -> None:
    """A net label: the pointed tag a name is written in, on a stub of wire."""
    p.drawLine(QPointF(8, 50), QPointF(24, 50))
    path = QPainterPath(QPointF(24, 32))
    path.lineTo(QPointF(78, 32))
    path.lineTo(QPointF(94, 50))
    path.lineTo(QPointF(78, 68))
    path.lineTo(QPointF(24, 68))
    path.closeSubpath()
    p.drawPath(path)


def _text(p: QPainter) -> None:
    """A capital A, which is what every drawing tool marks its text tool with."""
    path = QPainterPath(QPointF(20, 84))
    path.lineTo(QPointF(50, 18))
    path.lineTo(QPointF(80, 84))
    p.drawPath(path)
    p.drawLine(QPointF(32, 60), QPointF(68, 60))


def _shape(p: QPainter) -> None:
    """A rectangle and a circle: the two shapes an annotation is made of."""
    p.drawRect(QRectF(10, 28, 48, 40))
    p.setPen(_pen(_ink.accent, 7))
    p.drawEllipse(QPointF(70, 62), 22, 22)


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
    """Two sheets stacked: what is drawn on the board, layer by layer."""
    sheet = QPainterPath(QPointF(50, 16))
    sheet.lineTo(QPointF(86, 36))
    sheet.lineTo(QPointF(50, 56))
    sheet.lineTo(QPointF(14, 36))
    sheet.closeSubpath()
    p.drawPath(sheet)
    under = QPainterPath(QPointF(14, 58))
    under.lineTo(QPointF(50, 78))
    under.lineTo(QPointF(86, 58))
    p.drawPath(under)


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
    """A tick struck through: the ticks taken off."""
    tick = QPainterPath(QPointF(18, 52))
    tick.lineTo(QPointF(40, 74))
    tick.lineTo(QPointF(82, 28))
    p.drawPath(tick)
    p.drawLine(QPointF(20, 20), QPointF(80, 80))


def _exploded(p: QPainter) -> None:
    """Two parts lifted off a board, with the line down to where they go."""
    p.drawLine(QPointF(10, 84), QPointF(90, 84))
    p.drawRect(QRectF(18, 20, 24, 18))
    p.drawRect(QRectF(58, 34, 24, 18))
    for x, top in ((30, 38), (70, 52)):
        p.drawLine(QPointF(x, top + 6), QPointF(x, 78))


def _camera(p: QPainter) -> None:
    """A camera: put the 3D camera back where it starts."""
    p.drawRoundedRect(QRectF(12, 32, 76, 50), 8, 8)
    p.drawRect(QRectF(34, 20, 24, 12))
    p.drawEllipse(QPointF(50, 57), 15, 15)


def _menu(p: QPainter) -> None:
    """Three lines: the menus, all of them, behind one button in the header."""
    for y in (28, 50, 72):
        p.drawLine(QPointF(18, y), QPointF(82, y))


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
    "text": _text,
    "shape": _shape,
    "arrow": _arrow,
    "fit": _fit,
    "delete": _delete,
    "menu": _menu,
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


def icon(name: str) -> QIcon:
    """The named icon, drawn once and kept.

    An unknown name gives an empty icon rather than raising: a missing picture is a
    cosmetic fault, and taking the window down over one would not be.
    """
    cached = _cache.get(name)
    if cached is not None:
        return cached

    draw = DRAWINGS.get(name)
    if draw is None:
        return QIcon()

    built = QIcon()
    for mode, state, lines, accent in _STATES:
        built.addPixmap(_picture(draw, lines, accent), mode, state)
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


#: Icon size for a tree row. Smaller than the toolbar's, which is a button.
PART_SIZE = 20

#: Tinned component lead. Matches ``view2d.LEAD``, kept local so the icons do not drag in
#: the whole 2D scene module to draw a wire.
LEAD = "#c2c8d0"

_part_cache: dict[str, QIcon] = {}


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
    "screw-terminal": _screw_terminal,
    "potentiometer": _potentiometer,
    "tactile-switch": _tactile,
    "crystal-hc49": _crystal,
    "relay-box": _relay,
    "generic-box": _generic,
    "box-header": _box_header,
    "screw-terminal-vertical": _screw_terminal,
    "module-board": _module,
    "flying-leads": _flying_leads,
    "smd-adapter": _smd_adapter,
}


def part_icon(footprint: Any) -> QIcon:
    """A small colour picture of this part, in the colours the board draws it in."""
    from .bodies import style_for

    archetype = footprint.body.archetype
    style = style_for(footprint)
    key = f"{archetype}:{footprint.polarized}:{style.fill}"
    cached = _part_cache.get(key)
    if cached is not None:
        return cached

    scale = 2
    pixmap = QPixmap(PART_SIZE * scale, PART_SIZE * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(PART_SIZE * scale / BOX, PART_SIZE * scale / BOX)
    if archetype == "axial-cylinder":
        _axial(painter, style, bool(footprint.polarized))
    elif archetype == "axial-upright":
        _axial_upright(painter, style, bool(footprint.polarized))
    else:
        PART_DRAWINGS.get(archetype, _generic)(painter, style)
    painter.end()
    pixmap.setDevicePixelRatio(float(scale))

    built = QIcon(pixmap)
    _part_cache[key] = built
    return built
