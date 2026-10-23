"""The schematic panel: the sheet ``schematic.py`` generates, on screen and clickable.

WHAT IS EDITABLE HERE IS THE CIRCUIT, AND THE DRAWING IS STILL DERIVED.
``perfboard_studio.schematic`` builds a whole sheet from the document every time; this file
paints one, reports clicks, and hands them back to the window as commands -- add a part,
move it, turn it, draw a wire, name a net, place the lot. What a gesture SENDS is always a
position or a pair of pins, never a change to the document: every edit on this sheet is a
command like any other, so the drawing has no state of its own to get out of step.

NOTHING HERE DECIDES WHAT AN EDIT MEANS. A right-click reports a position and the window
builds the menu, the same division ``view2d.BoardView.contextMenuRequested`` draws: which
command a click becomes depends on whether a part is in the design or on the board, and
this file knows about a drawing.

ONE ITEM PAINTS THE WHOLE SHEET, AND THE HIT TESTING IS DONE BY HAND. A symbol per
``QGraphicsItem`` would give hover and selection for free, and would also mean a bounding
rect and a ``shape()`` per symbol kind, ten of which exist. The drawing is a few hundred
primitives, it is rebuilt wholesale whenever the document changes, and "which symbol is
under this point" is a rectangle test -- so one item, one repaint, and two small
predicates below. What that buys is that the panel has no state the drawing does not
already carry, which is why refreshing it cannot leave anything stale behind.

CROSS-PROBING IS THE POINT OF HAVING IT IN THE WINDOW. LVS says "net VOUT is open" and the
board shows copper; until now there was nothing to look at that said what VOUT *is*.
Clicking a symbol selects that part on the board, clicking a net highlights it there, and
a selection made on the board or in the Nets dock lights up here -- so the two views are
two views of one thing rather than two applications in one window.

Labels are drawn at the size the LAYOUT reserved room for, in millimetres of sheet, and
never smaller than a floor in pixels (``label_px``). They used to hold a fixed pixel size,
the board's reasoning for its reference designators -- but a sheet is not a board with
annotation on it: every lane is placed to clear text of a measured height
(``schematic.REF_BAND_MM`` and its neighbours), and text that did not shrink with the sheet
was two to three times that height at the zoom the panel opens on, so the trunks the layout
had kept out of "NE555" and "10nF" ran through them on screen and nowhere else. The floor
is what the fixed size was protecting: a fitted view whose labels shrank to nothing would
be the one view that says nothing.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QEvent, QLineF, QMimeData, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QContextMenuEvent,
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QStyleOptionGraphicsItem,
    QWidget,
)

from perfboard_studio.erc import ErcFinding, ErcSeverity
from perfboard_studio.model import NetNode, Point2
from perfboard_studio.schematic import (
    GRID_MM,
    NET_LABEL_MM,
    PIN_LABEL_MM,
    REF_LABEL_MM,
    VALUE_LABEL_MM,
    Annotation,
    Label,
    NoConnect,
    Rail,
    SchematicDrawing,
    Symbol,
    Wire,
    no_connect_arms,
    rail_glyph_bars,
    snap_to_grid,
)

from . import theme
from .i18n import t
from .scenetext import draw_label

# The drag formats live with the board, which is what receives one of them and which
# already owns the vocabulary a drop lands in (screen_to_hole). Two constants, three views.
from .view2d import FOOTPRINT_MIME, PART_MIME, picture_beside_the_pointer

#: Which tool has the left button on the sheet.
#:
#: SELECT IS A TOOL AND NOT THE ABSENCE OF ONE, which is what makes Escape mean the same
#: thing everywhere: whatever you are in the middle of, one press puts you back to picking
#: things up. An editor whose "no tool" state is unreachable is an editor you get stuck in.
type SheetTool = Literal["select", "wire", "label", "text", "line", "rectangle", "circle"]

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
#
# A third colour table, and the reason there are three is set out in docs/ARCHITECTURE.md
# ("Appearance is a view setting"): `theme` colours the application, `view2d`'s block
# colours the physical object, and this colours a DRAWING -- which is neither. A schematic
# is ink on paper, so it is drawn as ink on paper: one line weight for everything, colour
# used only to separate the three net classes and to say what is selected.

SHEET = "#161a21"
INK = "#c8d0de"
INK_DIM = "#7d8698"
#: The grid, and the every-fifth line that lets you count squares without counting them.
#:
#: A schematic without one is a drawing floating in the dark: nothing says how big the
#: sheet is, nothing says whether two symbols are aligned, and the pan has no landmarks --
#: which is what "there is nowhere to look" feels like on an empty document. It is drawn at
#: the layout's OWN pitch (``schematic.GRID_MM``, 2.54 mm, the same pitch as the board),
#: so the squares mean something rather than being wallpaper.
GRID = "#1e2531"
GRID_MAJOR = "#28313f"
SIGNAL = "#7fb2e5"
POWER = "#e0a33c"
GROUND = "#8f97a8"
HIGHLIGHT = theme.ACCENT
UNDEFINED = theme.WARNING

#: Line weights in millimetres of sheet. A schematic has one weight for wires and a
#: slightly heavier one for symbol bodies, which is what makes a body read as a thing and a
#: wire as a connection between things.
WIRE_MM = 0.30
BODY_MM = 0.40
HIGHLIGHT_MM = 0.85

#: Junction dot radius, in millimetres of sheet, so it is part of the drawing rather than
#: of the zoom. The rail glyph gets no constant here at all: its bars sit in room the LAYOUT
#: cleared, so ``schematic.rail_glyph_bars`` owns them and both renderers ask it rather than
#: each holding a half-width that could drift wider than the clearance.
DOT_MM = 0.75

#: The smallest each kind of text is drawn, in pixels, however far the sheet is zoomed out.
#: Above it text is its sheet size -- the size the layout cleared room for.
#: A step under the sizes the text is drawn at when a typical sheet is fitted to a
#: typical panel (about 5 px/mm), so a fitted sheet draws its text at its own size and the
#: floor is only reached zoomed further out than that.
REF_PX = 8
VALUE_PX = 7
NET_PX = 7
PIN_PX = 6

#: The largest, so a sheet zoomed right in to one pin does not ask the font engine for
#: glyphs a hundred pixels tall.
MAX_LABEL_PX = 72


def label_px(size_mm: float, floor_px: int, px_per_mm: float) -> int:
    """How tall to draw text that is ``size_mm`` of sheet, at this zoom, in pixels."""
    return max(floor_px, min(MAX_LABEL_PX, round(size_mm * px_per_mm)))

#: Scene-space padding on the item's bounding rect. The labels do not shrink with the
#: sheet, so the room they need GROWS as the view zooms out (``scenetext`` explains why).
#: An over-large rect only widens a repaint region; too small leaves label debris behind.
BOUNDS_PAD_MM = 40.0

#: Selection, which is a different thing from the cross-probing HIGHLIGHT and has to look
#: like one. Highlight says "this is the net you asked about on the board"; selection says
#: "this is what the next key press acts on", so it gets a box round it rather than a
#: heavier line -- two symbols, one lit and one selected, must not read the same.
SELECTED = "#f0f3f8"
SELECTION_BOX_MM = 0.25
#: How far outside a symbol's own box the selection rectangle is drawn.
SELECTION_PAD_MM = 0.8

#: A note: ink on the drawing that is not the circuit, so it is drawn in the dim ink and
#: never in a net colour.
NOTE = "#9aa6ba"
NOTE_MM = 0.30

#: The line that follows the pointer while a wire is being drawn, and the box that follows
#: it while a shape is.
GHOST_MM = 0.35

#: What ERC says about a pin, drawn ON the pin: a ring in the application's error and warning
#: colours, because a finding is the application talking about the drawing rather than part
#: of the drawing. Chosen on 2026-10-19 from three rendered candidates (filled rings for
#: both, this, and a "!" badge beside the pin). The warning ring is DASHED AND UNFILLED
#: because the warning amber is ``POWER``: a filled amber ring on a +5V wire read as one more
#: dot on the rail. The two differ in shape as well as colour, so severity reads without it.
MARK_ERROR = theme.ERROR
MARK_WARNING = theme.WARNING
MARK_RADIUS_MM = 1.35
MARK_MM = 0.45
#: How much of the error colour fills its ring: enough to find from across the sheet, little
#: enough to read the pin number under it.
MARK_FILL_ALPHA = 55
#: Where a finding about a whole part (it is connected to nothing) is ringed: just past the
#: top-right corner of its symbol, where no lead and no label is.
PART_MARK_OFFSET_MM = 0.6

#: How close a click has to land to a wire to count as hitting it, in millimetres.
PICK_MM = 1.6

#: The same for a pin, and deliberately larger. A wire is a long target and a pin is a
#: point; the pins of a DIP are one 2.54 mm pitch apart, so this stays under half of that
#: or two neighbouring pins would compete for the same click.
PIN_PICK_MM = 1.2

#: ...and never smaller on screen than this, nor larger on the sheet than that. At the zoom
#: a sheet is fitted at, 1.2 mm is five pixels -- a target a hand misses more often than
#: it hits. The larger radius is safe because the NEAREST pin within it wins (``pin_at``):
#: two neighbouring DIP pins never both claim a click, however far each one reaches.
PIN_PICK_PX = 8
PIN_PICK_MAX_MM = 2.0

#: How far the pointer has to travel between press and release for the wire tool to read
#: the gesture as a drag from one pin to another rather than as a click.
DRAG_WIRE_PX = 6


def _point(point: Point2) -> QPointF:
    return QPointF(point.x, point.y)


def _class_colour(net_class: str) -> str:
    if net_class == "power":
        return POWER
    if net_class == "ground":
        return GROUND
    return SIGNAL


#: One mark: the worse severity of everything said about the spot, and every message said.
type Mark = tuple[ErcSeverity, tuple[str, ...]]


def finding_marks(
    findings: Iterable[ErcFinding],
) -> tuple[dict[tuple[str, str], Mark], dict[str, Mark]]:
    """Where ERC's findings go on the sheet: ``(by pin, by part)``.

    A finding that names pins marks each of them -- both leads of an electrolytic drawn
    backwards. One that names only a part (connected to nothing) marks the part. A pin
    with an error and a warning is an error, and its tooltip says both.
    """
    pins: dict[tuple[str, str], Mark] = {}
    parts: dict[str, Mark] = {}
    for finding in findings:
        if finding.pins:
            for node in finding.pins:
                key = (node.component_ref, node.pin)
                pins[key] = _with(pins.get(key), finding)
        else:
            for ref in finding.refs:
                parts[ref] = _with(parts.get(ref), finding)
    return pins, parts


def _with(mark: Mark | None, finding: ErcFinding) -> Mark:
    """A mark with one more finding said about the same spot: the worse severity wins."""
    if mark is None:
        return (finding.severity, (finding.message,))
    severity, messages = mark
    if finding.severity == "error":
        severity = "error"
    if finding.message not in messages:
        messages = (*messages, finding.message)
    return (severity, messages)


def pin_anchor(drawing: SchematicDrawing, ref: str, number: str) -> QPointF | None:
    """Where a named pin sits on the sheet, in scene millimetres."""
    for symbol in drawing.symbols:
        if symbol.ref != ref:
            continue
        for pin in symbol.pins:
            if pin.number == number:
                return QPointF(symbol.at.x + pin.at.x, symbol.at.y + pin.at.y)
    return None


# ---------------------------------------------------------------------------
# The sheet
# ---------------------------------------------------------------------------


class SheetItem(QGraphicsItem):
    """Everything on the sheet, painted in one pass.

    Order matters and is the order a draughtsman would use: wires first so a symbol sits on
    top of the line reaching it, then rails, then junction dots, then bodies, then text.
    """

    def __init__(self, drawing: SchematicDrawing) -> None:
        super().__init__()
        self.drawing = drawing
        self.highlight_refs: frozenset[str] = frozenset()
        self.highlight_nets: frozenset[str] = frozenset()
        #: What the next key press acts on. Separate from the highlight above, which is
        #: what the board or the Nets dock is pointing at.
        self.selected_refs: frozenset[str] = frozenset()
        self.selected_notes: frozenset[str] = frozenset()
        #: The pin waiting for its partner while a wire is being drawn.
        self.pending_pin: tuple[str, str] | None = None
        #: The pin the wire tool would take if the button went down now -- ringed, so the
        #: click lands where it is aimed rather than one pin along.
        self.hover_pin: tuple[str, str] | None = None
        #: Where the symbols being dragged are, relative to where the document says they
        #: are. Painted rather than committed, so a drag that is let go outside the sheet
        #: -- or undone -- leaves nothing behind.
        self.drag_offset: QPointF | None = None
        #: The wire or the shape following the pointer, as scene points.
        self.ghost_path: tuple[QPointF, ...] = ()
        self.ghost_shape: tuple[str, QPointF, QPointF] | None = None
        #: What ERC says about each pin and each whole part (``finding_marks``).
        self.pin_marks: dict[tuple[str, str], Mark] = {}
        self.part_marks: dict[str, Mark] = {}

    def boundingRect(self) -> QRectF:
        return QRectF(0.0, 0.0, self.drawing.width, self.drawing.height).adjusted(
            -BOUNDS_PAD_MM, -BOUNDS_PAD_MM, BOUNDS_PAD_MM, BOUNDS_PAD_MM
        )

    def set_selection(self, refs: Iterable[str], notes: Iterable[str]) -> None:
        refs_set, notes_set = frozenset(refs), frozenset(notes)
        if refs_set == self.selected_refs and notes_set == self.selected_notes:
            return
        self.selected_refs, self.selected_notes = refs_set, notes_set
        self.update()

    def set_highlight(self, refs: Iterable[str], net_ids: Iterable[str]) -> None:
        refs_set, nets_set = frozenset(refs), frozenset(net_ids)
        if refs_set == self.highlight_refs and nets_set == self.highlight_nets:
            return
        self.highlight_refs, self.highlight_nets = refs_set, nets_set
        self.update()

    def set_findings(self, findings: Iterable[ErcFinding]) -> None:
        pins, parts = finding_marks(findings)
        if pins == self.pin_marks and parts == self.part_marks:
            return
        self.pin_marks, self.part_marks = pins, parts
        self.update()

    def part_mark_at(self, ref: str) -> QPointF | None:
        """Where the ring for a finding about a whole part goes."""
        for symbol in self.drawing.symbols:
            if symbol.ref == ref:
                return QPointF(
                    symbol.at.x + symbol.width + PART_MARK_OFFSET_MM,
                    symbol.at.y - PART_MARK_OFFSET_MM,
                )
        return None

    # -- painting ------------------------------------------------------------

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        drawing = self.drawing

        for wire in drawing.wires:
            self._stroke(painter, wire.path, wire.net_class, wire.net_id in self.highlight_nets)
        for rail in drawing.rails:
            self._stroke(painter, rail.path, rail.net_class, rail.net_id in self.highlight_nets)
            self._rail_glyph(painter, rail)

        for junction in drawing.junctions:
            lit = junction.net_id in self.highlight_nets
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(HIGHLIGHT if lit else SIGNAL)))
            painter.drawEllipse(_point(junction.at), DOT_MM, DOT_MM)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for mark in drawing.no_connects:
            self._no_connect(painter, mark)

        for index, note in enumerate(drawing.annotations):
            self._annotation(painter, note, f"n{index}" in self.selected_notes)

        for symbol in drawing.symbols:
            self._symbol(painter, symbol)

        # Over the symbols and the no-connect crosses -- an unpowered VCC is a crossed-out
        # pin, and the ring has to read through the cross -- and under the text, so the pin
        # number in the ring stays readable.
        self._marks(painter)
        self._selection(painter)
        self._ghost(painter)

        if self.pending_pin is not None:
            # An open ring on the pin waiting for its partner, the same gesture the board
            # uses: half a decision has been made and it has to be visible, because the
            # other half is a click somewhere else entirely.
            anchor = pin_anchor(drawing, *self.pending_pin)
            if anchor is not None:
                pen = QPen(QColor(HIGHLIGHT))
                pen.setWidthF(HIGHLIGHT_MM * 0.7)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(anchor, PICK_MM, PICK_MM)

        if self.hover_pin is not None and self.hover_pin != self.pending_pin:
            anchor = pin_anchor(drawing, *self.hover_pin)
            if anchor is not None:
                pen = QPen(QColor(HIGHLIGHT))
                pen.setWidthF(HIGHLIGHT_MM * 0.4)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(anchor, PICK_MM * 0.8, PICK_MM * 0.8)

        self._labels(painter)

    def _stroke(
        self, painter: QPainter, path: Sequence[Point2], net_class: str, lit: bool
    ) -> None:
        pen = QPen(QColor(HIGHLIGHT if lit else _class_colour(net_class)))
        pen.setWidthF(HIGHLIGHT_MM if lit else WIRE_MM)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([_point(point) for point in path]))

    def _rail_glyph(self, painter: QPainter, rail: Rail) -> None:
        """Three shrinking bars for ground, a bar on a stem for power.

        Two glyphs rather than one coloured one: a schematic is read at a glance and often
        printed in black, and a reader should not have to know a colour convention to tell
        the rail that sinks from the rail that sources.

        WHERE the bars are is not this file's to decide -- ``schematic.rail_glyph_bars``
        answers that for the exported sheet too, and a glyph drawn one way on screen and
        another on paper would be two answers to the question the glyph exists to answer.
        """
        lit = rail.net_id in self.highlight_nets
        pen = QPen(QColor(HIGHLIGHT if lit else _class_colour(rail.net_class)))
        pen.setWidthF(HIGHLIGHT_MM if lit else BODY_MM)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for start, end in rail_glyph_bars(rail):
            painter.drawLine(_point(start), _point(end))

    def _no_connect(self, painter: QPainter, mark: NoConnect) -> None:
        """A cross on a pin no net in the document reaches.

        Drawn in the dim ink for the reason the exported sheet uses its own: an unused pin
        on a header is the ordinary case rather than a fault, and a mark that shouted would
        be shouting on nearly every connector. WHERE the strokes go is not this file's to
        decide, the same as the rail glyph -- ``schematic.no_connect_arms`` answers it for
        paper too.
        """
        pen = QPen(QColor(INK_DIM))
        pen.setWidthF(WIRE_MM)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for start, end in no_connect_arms(mark):
            painter.drawLine(_point(start), _point(end))

    def _symbol(self, painter: QPainter, symbol: Symbol) -> None:
        lit = symbol.ref in self.highlight_refs
        colour = HIGHLIGHT if lit else (UNDEFINED if symbol.undefined else INK)
        pen = QPen(QColor(colour))
        pen.setWidthF(HIGHLIGHT_MM if lit else BODY_MM)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if symbol.undefined:
            # A net is wired to a part nothing in the document defines, so its pins are
            # whatever the netlist happened to mention. Dashed because it is a hole in the
            # design. NOT dashed merely for being unplaced: on a schematic being drawn that
            # is every symbol on the sheet, and a sheet drawn entirely in dashes says
            # nothing.
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.save()
        painter.translate(symbol.at.x, symbol.at.y)
        painter.setPen(pen)
        for shape in symbol.shapes:
            if shape.kind == "circle":
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(_point(shape.points[0]), shape.radius, shape.radius)
                continue
            polygon = QPolygonF([_point(point) for point in shape.points])
            if shape.kind == "polygon":
                painter.setBrush(QBrush(QColor(colour)) if shape.filled else Qt.BrushStyle.NoBrush)
                painter.drawPolygon(polygon)
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolyline(polygon)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.restore()

    def _marks(self, painter: QPainter) -> None:
        """A ring on every pin and part ERC has something to say about (``MARK_*``)."""
        spots: list[tuple[QPointF, ErcSeverity]] = []
        for (ref, number), (severity, _) in self.pin_marks.items():
            anchor = pin_anchor(self.drawing, ref, number)
            if anchor is not None:
                spots.append((anchor, severity))
        for ref, (severity, _) in self.part_marks.items():
            corner = self.part_mark_at(ref)
            if corner is not None:
                spots.append((corner, severity))
        for at, severity in spots:
            colour = QColor(MARK_ERROR if severity == "error" else MARK_WARNING)
            pen = QPen(colour)
            pen.setWidthF(MARK_MM)
            if severity == "error":
                fill = QColor(colour)
                fill.setAlpha(MARK_FILL_ALPHA)
                painter.setBrush(QBrush(fill))
            else:
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
            painter.drawEllipse(at, MARK_RADIUS_MM, MARK_RADIUS_MM)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _annotation(self, painter: QPainter, note: Annotation, selected: bool) -> None:
        """A caption or a box. Never in a net colour: a note is not part of the circuit and
        must not read as one."""
        pen = QPen(QColor(SELECTED if selected else NOTE))
        pen.setWidthF(NOTE_MM)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        box = QRectF(_point(note.at), _point(note.to)).normalized()
        if note.kind == "line":
            painter.drawLine(_point(note.at), _point(note.to))
        elif note.kind == "rectangle":
            painter.drawRect(box)
        elif note.kind == "circle":
            painter.drawEllipse(box)
        else:
            # MILLIMETRES, NOT PIXELS, and this is the one piece of text on the sheet that
            # is. A reference is annotation and holds its screen size (scenetext argues it
            # at length); a note is something somebody WROTE on the drawing at a size they
            # chose, so it scales with the sheet exactly as silkscreen does on the board.
            font = painter.font()
            font.setPointSizeF(max(0.5, note.size_mm))
            painter.save()
            painter.setFont(font)
            painter.drawText(_point(note.at), note.text)
            painter.restore()

    def _selection(self, painter: QPainter) -> None:
        """A thin box round everything the next key press acts on.

        A BOX AND NOT A HEAVIER LINE, because the sheet already uses weight and colour for
        the cross-probing highlight -- "this is the net you asked about on the board". A
        selected symbol and a highlighted one have to be tellable apart, and they routinely
        are both at once.
        """
        if not self.selected_refs:
            return
        pen = QPen(QColor(SELECTED))
        pen.setWidthF(SELECTION_BOX_MM)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        offset = self.drag_offset or QPointF(0.0, 0.0)
        for symbol in self.drawing.symbols:
            if symbol.ref not in self.selected_refs:
                continue
            box = QRectF(
                symbol.at.x + offset.x() - SELECTION_PAD_MM,
                symbol.at.y + offset.y() - SELECTION_PAD_MM,
                symbol.width + 2 * SELECTION_PAD_MM,
                symbol.height + 2 * SELECTION_PAD_MM,
            )
            painter.drawRect(box)

    def _ghost(self, painter: QPainter) -> None:
        """The wire or the shape following the pointer, and the symbols being dragged.

        Everything here is a PICTURE of an edit that has not happened. Nothing is committed
        until the button comes up, which is what lets Escape and a drag off the sheet both
        mean "never mind" without a command having to be undone.
        """
        if self.drag_offset is not None:
            pen = QPen(QColor(SELECTED))
            pen.setWidthF(GHOST_MM)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for symbol in self.drawing.symbols:
                if symbol.ref not in self.selected_refs:
                    continue
                painter.save()
                painter.translate(
                    symbol.at.x + self.drag_offset.x(), symbol.at.y + self.drag_offset.y()
                )
                for shape in symbol.shapes:
                    if shape.kind == "circle":
                        painter.drawEllipse(
                            _point(shape.points[0]), shape.radius, shape.radius
                        )
                    else:
                        painter.drawPolyline(
                            QPolygonF([_point(point) for point in shape.points])
                        )
                painter.restore()

        if self.ghost_path:
            pen = QPen(QColor(HIGHLIGHT))
            pen.setWidthF(GHOST_MM)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(QPolygonF(list(self.ghost_path)))

        if self.ghost_shape is not None:
            kind, start, end = self.ghost_shape
            pen = QPen(QColor(SELECTED))
            pen.setWidthF(GHOST_MM)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            box = QRectF(start, end).normalized()
            if kind == "line":
                painter.drawLine(start, end)
            elif kind == "circle":
                painter.drawEllipse(box)
            else:
                painter.drawRect(box)

    def _labels(self, painter: QPainter) -> None:
        # Pixels per millimetre of sheet, from the painter rather than the view: the same
        # item is painted into the panel and, through ``QGraphicsScene.render``, into a
        # picture at another scale.
        scale = math.hypot(painter.transform().m11(), painter.transform().m12())
        sizes = {
            "ref": label_px(REF_LABEL_MM, REF_PX, scale),
            "value": label_px(VALUE_LABEL_MM, VALUE_PX, scale),
            "net": label_px(NET_LABEL_MM, NET_PX, scale),
            "pin": label_px(PIN_LABEL_MM, PIN_PX, scale),
        }
        for label in self.drawing.labels:
            if label.kind == "ref":
                colour, size, bold = INK, sizes["ref"], True
            elif label.kind == "value":
                colour, size, bold = INK_DIM, sizes["value"], False
            elif label.kind in ("net", "rail"):
                colour, size, bold = SIGNAL, sizes["net"], False
            else:
                colour, size, bold = INK_DIM, sizes["pin"], False
            painter.setPen(QPen(QColor(colour)))
            draw_label(painter, _point(label.at), label.text, size, label_alignment(label), bold=bold)


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------


def label_alignment(label: Label) -> Qt.AlignmentFlag:
    """Where a label's text goes relative to its point, in ``draw_label``'s own terms.

    Those are not Qt's usual ones: ``draw_label`` aligns the text inside a box CENTRED on
    the point, so AlignRight puts the text to the point's right and AlignTop puts it above.
    ``Label.anchor`` says which end of the text is at the point -- "left" means the text
    starts there and runs right -- and the SVG export, and the layout that reserved room for
    each label, read it that way. The panel read the Qt words at face value and drew every
    label in the opposite quadrant: net names left of and below their point, over the wires
    the layout had kept clear and off the sheet's left edge ("XTAL1" showing as "TAL1"),
    references below their point, values above it, and pin numbers on the wrong side of
    their leads.
    """
    horizontal = {
        "left": Qt.AlignmentFlag.AlignRight,
        "centre": Qt.AlignmentFlag.AlignHCenter,
        "right": Qt.AlignmentFlag.AlignLeft,
    }[label.anchor]
    if label.kind in ("ref", "net", "rail"):  # above the point -- a net name's is its baseline
        vertical = Qt.AlignmentFlag.AlignTop
    elif label.kind == "value":  # below it
        vertical = Qt.AlignmentFlag.AlignBottom
    else:  # a pin number, centred on it
        vertical = Qt.AlignmentFlag.AlignVCenter
    return horizontal | vertical


def _turn_of(event: QKeyEvent) -> int | None:
    """+1 for R, -1 for Shift+R -- the board's own Rotate keys -- and None for anything else."""
    if event.key() != Qt.Key.Key_R:
        return None
    modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
    if modifiers == Qt.KeyboardModifier.NoModifier:
        return 1
    if modifiers == Qt.KeyboardModifier.ShiftModifier:
        return -1
    return None


class SchematicView(QGraphicsView):
    """Pan, zoom, and report what was clicked.

    ``set_drawing`` deliberately leaves the viewpoint alone -- the same rule
    ``view3d.populate_renderer`` follows about the camera. Editing one net must not throw
    away the part of the sheet somebody was looking at; ``fit`` is the only thing that
    moves the view, and it is called on the first drawing and from the button.
    """

    #: A symbol was clicked. Carries the reference, which is what the board speaks.
    partClicked = Signal(str)
    #: A symbol was double-clicked.
    partActivated = Signal(str)
    #: A wire or rail was clicked. Carries the net id.
    netClicked = Signal(str)
    #: A pin was clicked while wiring. Carries the reference and the pin number.
    pinClicked = Signal(str, str)
    #: Nothing was clicked.
    cleared = Signal()
    #: Symbols were dragged to new places ON THE SHEET. Carries (reference, x, y) in
    #: sheet millimetres, already snapped to the grid. ONE GESTURE, TWO DESTINATIONS,
    #: decided by where the pointer is let go: dropped on the board it places the part
    #: (``view2d.BoardView.partDropped``), dropped here it moves the symbol.
    symbolsMoved = Signal(list)
    #: A wire was drawn between two pins: (ref a, pin a, ref b, pin b, path as a list of
    #: (x, y) pairs). The VIEW does not decide what that means to the circuit -- see
    #: ``commands.plan_pin_join`` and the window's handler.
    wireDrawn = Signal(str, str, str, str, list)
    #: A T was drawn: a pin wired onto a wire already on the sheet. (ref, pin, then the two
    #: pins that name the wire -- ref a, pin a, ref b, pin b -- then the path from the pin
    #: to the point on the wire, as (x, y) pairs.) What it means to the circuit is the
    #: window's business again: the pin joins the wire's net.
    wireTeed = Signal(str, str, str, str, str, str, list)
    #: The wire tool's first click landed on a wire rather than a pin. Carries the wire's
    #: two ends as "R1.2 – U1.4", for the status bar.
    teeStarted = Signal(str)
    #: A pin was clicked with the label tool: join it to a net by NAME. The window asks
    #: which name, because that is a question with a dialog behind it.
    labelRequested = Signal(str, str)
    #: A row was dragged out of the Parts panel and dropped on the sheet. Carries the
    #: footprint id and where it landed. It is ``part.add`` and not ``component.place``:
    #: the board is not involved, which is the whole point of drawing the circuit first.
    footprintDropped = Signal(str, float, float)
    #: A note was drawn: (kind, x0, y0, x1, y1). For text the two points are the same and
    #: the window asks what it should say.
    noteDrawn = Signal(str, float, float, float, float)
    #: A note was dragged. Carries its index in ``drawing.annotations`` and the new corner.
    noteMoved = Signal(int, float, float)
    #: Delete was pressed with something selected.
    deleteRequested = Signal()
    #: R (+1) or Shift+R (-1) was pressed: turn the selected symbols by that many quarters.
    turnRequested = Signal(int)
    #: The selection changed on the sheet itself.
    selectionChanged = Signal(list)
    #: The viewport position of a right-click that wants a menu. WHAT is on it is the
    #: window's business, for the reason ``view2d.BoardView.contextMenuRequested`` says: the
    #: entries are commands about the circuit, and a view that built its own would be a
    #: second list of what can be done to a part, free to disagree with the panel's buttons.
    contextMenuRequested = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.item: SheetItem | None = None
        self._fitted = False
        #: Whether somebody has chosen the view -- zoomed or panned -- since it was last
        #: fitted. Until they have, the sheet is re-fitted whenever the panel changes size.
        self._user_framed = False
        #: Which tool has the left button. "select" is the one every other tool returns to,
        #: which is why it is a tool at all rather than the absence of one -- an editor with
        #: no way back to plain selecting is an editor you get stuck in.
        self.tool: SheetTool = "select"
        self.wiring = False
        self.pending_pin: tuple[str, str] | None = None
        #: The wire tool's first click, when it was on a wire: the T it will be.
        self.pending_tee: Tee | None = None
        self.selected_refs: list[str] = []
        self.selected_notes: list[int] = []
        #: ERC's findings, kept here for the selection's reason: the item is thrown away on
        #: every rebuild, and the findings arrive from the window, not from the drawing.
        self.findings: tuple[ErcFinding, ...] = ()
        self.setBackgroundBrush(QBrush(QColor(SHEET)))
        #: Where the press that might become a drag happened, in viewport coordinates, and
        #: what was under it. Held because a drag is a press PLUS movement: acting on the
        #: press alone would make every click on a symbol start one.
        self._press_at: QPoint | None = None
        self._press_ref: str | None = None
        self._press_note: int | None = None
        self._press_scene: QPointF | None = None
        self._dragging = False
        #: Middle-button panning, which every tool leaves alone. See set_tool.
        self._panning = False
        self._pan_origin = QPointF()
        #: The rubber band, while one is being pulled over empty sheet.
        self._band_from: QPointF | None = None
        #: Where a shape tool started.
        self._shape_from: QPointF | None = None
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._show_scroll_bars(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # The sheet is a drop target for its own symbols and for a row dragged out of the
        # Parts panel, which is what lets a part be added by dragging it here.
        self.setAcceptDrops(True)

    #: How many grid squares make a major line. Five, which is what squared paper and every
    #: schematic tool uses, and it is the count the eye can take in without counting.
    GRID_MAJOR_EVERY = 5

    #: Below this many device pixels per square the grid is not drawn at all. A grid finer
    #: than the eye can separate is not a grid, it is a grey wash over the drawing -- and at
    #: a fit-to-window zoom on a big sheet that is exactly what 2.54 mm comes to.
    MIN_GRID_PX = 4.0

    def drawBackground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        """The sheet, and the grid on it.

        Painted here rather than as items for the reason the whole sheet is one item: a
        line per grid square on a 460 mm sheet is nine thousand items to hold, transform
        and hit-test, for something nothing will ever click on. ``drawBackground`` is given
        the exposed rectangle, so the cost is what is on screen and not what exists.

        The minor grid disappears before the major one does, which is what makes zooming
        out readable instead of grey.
        """
        # Qt's own signature allows either; every caller in practice hands over a QRectF,
        # and the arithmetic below wants one.
        rect = QRectF(rect)
        painter.fillRect(rect, QColor(SHEET))
        scale = self.current_scale()
        minor = GRID_MM * scale
        major = minor * self.GRID_MAJOR_EVERY
        if major < self.MIN_GRID_PX:
            return

        # Cosmetic pens: a grid line is one pixel at every zoom, like a ruler's, rather
        # than something that thickens as you come in. Same call scenetext makes about
        # annotation holding a screen size.
        for step, colour in ((GRID_MM, GRID), (GRID_MM * self.GRID_MAJOR_EVERY, GRID_MAJOR)):
            if step * scale < self.MIN_GRID_PX:
                continue
            pen = QPen(QColor(colour))
            pen.setCosmetic(True)
            pen.setWidth(1)
            painter.setPen(pen)
            first_x = math.floor(rect.left() / step) * step
            first_y = math.floor(rect.top() / step) * step
            lines = []
            x = first_x
            while x <= rect.right():
                lines.append(QLineF(x, rect.top(), x, rect.bottom()))
                x += step
            y = first_y
            while y <= rect.bottom():
                lines.append(QLineF(rect.left(), y, rect.right(), y))
                y += step
            painter.drawLines(lines)

    def set_drawing(self, drawing: SchematicDrawing) -> None:
        refs = self.item.highlight_refs if self.item else frozenset()
        nets = self.item.highlight_nets if self.item else frozenset()
        self._scene.clear()
        self.item = SheetItem(drawing)
        self.item.set_highlight(refs, nets)
        # The SELECTION survives a rebuild, which the old panel never had to think about:
        # a drawing is rebuilt after every command, and a selection that vanished each time
        # would mean turning a symbol twice took two clicks on it. The refs are kept on the
        # VIEW rather than on the item for exactly that reason -- the item is thrown away.
        self.item.set_selection(
            [ref for ref in self.selected_refs if any(s.ref == ref for s in drawing.symbols)],
            {f"n{index}" for index in self.selected_notes},
        )
        self.item.pending_pin = self.pending_pin
        self.item.set_findings(self.findings)
        self._scene.addItem(self.item)
        self._scene.setSceneRect(self.item.boundingRect())
        # A fitted sheet STAYS fitted when it changes size, as it does when the panel does:
        # a paste or a part parked past the edge widens it, and with no scroll bars on a
        # fitted sheet (see fit) the new part would be somewhere nothing can scroll to.
        if drawing.symbols and not self._user_framed:
            self.fit()

    def set_highlight(self, refs: Iterable[str], net_ids: Iterable[str]) -> None:
        if self.item is not None:
            self.item.set_highlight(refs, net_ids)

    def set_findings(self, findings: Iterable[ErcFinding]) -> None:
        """What ERC says about the circuit, ringed on the pins it is about.

        On screen only. The exported sheet is the circuit, and a finding is the application
        talking about it -- the same line the selection box and the highlight do not cross.
        """
        self.findings = tuple(findings)
        if self.item is not None:
            self.item.set_findings(self.findings)

    def findings_at(self, scene_pos: QPointF) -> tuple[str, ...]:
        """What ERC said about the pin or the part ring under a point, for the tooltip."""
        if self.item is None:
            return ()
        pin = self.pin_at(scene_pos)
        if pin is not None and pin in self.item.pin_marks:
            return self.item.pin_marks[pin][1]
        for ref, (_, messages) in self.item.part_marks.items():
            corner = self.item.part_mark_at(ref)
            if corner is not None and math.hypot(
                scene_pos.x() - corner.x(), scene_pos.y() - corner.y()
            ) <= max(MARK_RADIUS_MM, self.pin_pick_radius()):
                return messages
        symbol = self.symbol_at(scene_pos)
        if symbol is not None and symbol.ref in self.item.part_marks:
            return self.item.part_marks[symbol.ref][1]
        return ()

    def set_tool(self, tool: SheetTool) -> None:
        """Which tool has the left button.

        PANNING IS THE MIDDLE BUTTON IN EVERY MODE, and that is what makes tools possible
        here at all. It used to be a left drag on empty sheet, so arming the wire tool had
        to turn panning off -- otherwise every near miss on a pin scrolled the sheet out
        from under it -- and with more than two tools that trade stops working: a rubber
        band, a rectangle and a wire all want the left button on empty sheet, and none of
        them can have it while panning does.
        """
        self.tool = tool
        self.wiring = tool == "wire"
        self.set_pending_pin(None)
        self.pending_tee = None
        self._clear_ghosts()
        if self.item is not None and self.item.hover_pin is not None:
            # A ring under the pointer means "the wire tool would take this"; with another
            # tool armed it would be a promise nothing keeps.
            self.item.hover_pin = None
            self.item.update()
        self.setCursor(
            Qt.CursorShape.ArrowCursor if tool == "select" else Qt.CursorShape.CrossCursor
        )

    def set_wiring(self, on: bool) -> None:
        """The wire tool, by the name the window's Wire button has always used."""
        self.set_tool("wire" if on else "select")

    def set_selection(self, refs: Sequence[str], notes: Sequence[int] = ()) -> None:
        self.selected_refs = list(refs)
        self.selected_notes = list(notes)
        if self.item is not None:
            self.item.set_selection(refs, {f"n{index}" for index in notes})

    def _clear_ghosts(self) -> None:
        self._dragging = False
        self._band_from = None
        self._shape_from = None
        self._press_at = None
        self._press_ref = None
        self._press_note = None
        self._press_scene = None
        if self.item is not None:
            self.item.drag_offset = None
            self.item.ghost_path = ()
            self.item.ghost_shape = None
            self.item.update()

    def set_pending_pin(self, pin: tuple[str, str] | None) -> None:
        self.pending_pin = pin
        if self.item is not None:
            self.item.pending_pin = pin
            self.item.update()

    def pin_pick_radius(self) -> float:
        """How close to a pin a click has to land, in sheet millimetres, at this zoom."""
        scale = self.current_scale() or 1.0
        return min(PIN_PICK_MAX_MM, max(PIN_PICK_MM, PIN_PICK_PX / scale))

    def pin_at(self, scene_pos: QPointF) -> tuple[str, str] | None:
        """The nearest pin within ``PIN_PICK_MM``, as ``(reference, pin number)``.

        Nearest rather than first, for the reason ``net_at`` is: the pins of a DIP are one
        pitch apart and picking whichever was built first would make half of them
        unreachable.
        """
        if self.item is None:
            return None
        radius = self.pin_pick_radius()
        best: tuple[float, str, str] | None = None
        for symbol in self.item.drawing.symbols:
            for pin in symbol.pins:
                dx = scene_pos.x() - (symbol.at.x + pin.at.x)
                dy = scene_pos.y() - (symbol.at.y + pin.at.y)
                distance = (dx * dx + dy * dy) ** 0.5
                if distance <= radius and (best is None or distance < best[0]):
                    best = (distance, symbol.ref, pin.number)
        return (best[1], best[2]) if best is not None else None

    def tee_at(self, scene_pos: QPointF) -> Tee | None:
        """The point on a DRAWN wire a T would land on, within ``PICK_MM`` of the pointer.

        Only a wire somebody drew (``Wire.ends``): a net label's stub and a rail are the
        sheet's own shorthand, and a branch off one would be a branch off nothing stored.
        Snapped to the grid along the run it lands on, and kept on that run.
        """
        if self.item is None:
            return None
        best: tuple[float, tuple[NetNode, NetNode], QPointF, QPointF] | None = None
        for wire in self.item.drawing.wires:
            if wire.ends is None:
                continue
            for start, end in zip(wire.path, wire.path[1:], strict=False):
                a, b = _point(start), _point(end)
                distance = _distance_to_segment(scene_pos, a, b)
                if distance <= PICK_MM and (best is None or distance < best[0]):
                    best = (distance, wire.ends, a, b)
        if best is None:
            return None
        _distance, ends, a, b = best
        horizontal = abs(b.y() - a.y()) < abs(b.x() - a.x())
        snapped = _snapped(scene_pos)
        if horizontal:
            at = QPointF(min(max(snapped.x(), min(a.x(), b.x())), max(a.x(), b.x())), a.y())
        else:
            at = QPointF(a.x(), min(max(snapped.y(), min(a.y(), b.y())), max(a.y(), b.y())))
        return Tee(ends=ends, at=at, horizontal=horizontal)

    def fit(self) -> None:
        if self.item is None:
            return
        sheet = QRectF(0.0, 0.0, self.item.drawing.width, self.item.drawing.height)
        if sheet.isEmpty():
            return
        # NO SCROLL BARS ON A FITTED SHEET. The scene is the sheet plus BOUNDS_PAD_MM, so a
        # fit of the sheet leaves the scene overflowing by the pad; an as-needed bar comes
        # in, takes its width off the viewport, and that is a resize -- which fits again,
        # finds the scene now fits, takes the bar away, and is resized back. Measured: over
        # 8000 fits in 50 ms in a 300 px panel nobody was touching, and no frame drawn. A
        # fitted sheet is all on screen, so the bars would show nothing anyway.
        self._show_scroll_bars(False)
        self.fitInView(sheet, Qt.AspectRatioMode.KeepAspectRatio)
        self._fitted = True
        # Fit hands the view back to the sheet: the next resize fits it again.
        self._user_framed = False

    def _show_scroll_bars(self, shown: bool) -> None:
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if shown
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)

    def _hand_over_framing(self) -> None:
        """Somebody zoomed or panned: the view is theirs, and the scroll bars come back.

        Marked theirs BEFORE the bars return, because a bar coming in is itself a resize,
        and a resize of a view still marked fitted would fit it -- undoing the very zoom
        that brought the bar in."""
        self._user_framed = True
        self._show_scroll_bars(True)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep a fitted sheet fitted while the panel finds its size.

        THE FIRST FIT HAPPENED WHILE THE PANEL WAS SMALL. A sheet is fitted the first time
        it has something on it, and in a window being built that is before the dock has its
        real size -- so the 555 opened at under 3 px/mm in a panel with room for 5, every
        piece of text at the pixel floor (``label_px``) and bigger than the room the layout
        had cleared for it. Until somebody zooms or pans, a new size is a new fit.
        """
        super().resizeEvent(event)
        if self._fitted and not self._user_framed:
            self.fit()

    # -- picking -------------------------------------------------------------

    def symbol_at(self, scene_pos: QPointF) -> Symbol | None:
        if self.item is None:
            return None
        for symbol in self.item.drawing.symbols:
            box = QRectF(symbol.at.x, symbol.at.y, symbol.width, symbol.height)
            if box.contains(scene_pos):
                return symbol
        return None

    def net_at(self, scene_pos: QPointF) -> tuple[str, str] | None:
        """The nearest wire or rail within ``PICK_MM``, as ``(net_id, net_name)``.

        Nearest rather than first: two nets can run a millimetre apart in a crowded
        channel, and picking whichever happened to be built first would make one of them
        unselectable.
        """
        if self.item is None:
            return None
        best: tuple[float, str, str] | None = None
        runs: list[Wire | Rail] = [*self.item.drawing.wires, *self.item.drawing.rails]
        for run in runs:
            for start, end in zip(run.path, run.path[1:], strict=False):
                distance = _distance_to_segment(scene_pos, _point(start), _point(end))
                if distance <= PICK_MM and (best is None or distance < best[0]):
                    best = (distance, run.net_id, run.net_name)
        return (best[1], best[2]) if best is not None else None

    # -- gestures ------------------------------------------------------------

    #: The zoom range, in scene units per pixel. The sheet is drawn in millimetres like
    #: the board, so the board's own limits are the right ones here too: without any, a
    #: few trackpad flicks zoomed to a blank field or into one pin with nothing but the
    #: Fit button to recover.
    MIN_SCALE = 0.5
    MAX_SCALE = 60.0

    def current_scale(self) -> float:
        return float(self.transform().m11())

    def _clamped_factor(self, factor: float) -> float:
        current = self.current_scale()
        target = min(self.MAX_SCALE, max(self.MIN_SCALE, current * factor))
        return target / current if current else 1.0

    def wheelEvent(self, event: QWheelEvent) -> None:
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        factor = self._clamped_factor(1.18**steps)
        if factor != 1.0:
            self.scale(factor, factor)
        self._fitted = True
        self._hand_over_framing()
        event.accept()

    def zoom_by(self, factor: float) -> None:
        """Zoom about the centre, for a keyboard shortcut."""
        factor = self._clamped_factor(factor)
        if factor == 1.0:
            return
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.scale(factor, factor)
        self.setTransformationAnchor(anchor)
        self._fitted = True
        self._hand_over_framing()

    #: Every tool that draws a note by dragging a box out.
    SHAPE_TOOLS: tuple[str, ...] = ("line", "rectangle", "circle")

    def note_at(self, scene_pos: QPointF) -> int | None:
        """The index into ``drawing.annotations`` of the note under a point, or None.

        Last first, so the one drawn on top is the one picked -- which is the order the
        painter put them down in and therefore the order the eye reads them.
        """
        if self.item is None:
            return None
        for index in range(len(self.item.drawing.annotations) - 1, -1, -1):
            note = self.item.drawing.annotations[index]
            box = QRectF(_point(note.at), _point(note.to)).normalized()
            if note.kind == "text":
                # A text note is a point with writing beside it, so it is given a target
                # rather than being unclickable.
                box = QRectF(
                    note.at.x - PICK_MM,
                    note.at.y - note.size_mm,
                    max(note.size_mm * len(note.text) * 0.7, 4 * PICK_MM),
                    note.size_mm * 1.6,
                )
            elif box.width() < 2 * PICK_MM or box.height() < 2 * PICK_MM:
                box = box.adjusted(-PICK_MM, -PICK_MM, PICK_MM, PICK_MM)
            if note.kind in ("line", "text") or not box.contains(scene_pos):
                if note.kind == "line":
                    start, end = _point(note.at), _point(note.to)
                    if _distance_to_segment(scene_pos, start, end) <= PICK_MM:
                        return index
                    continue
                if note.kind == "text" and box.contains(scene_pos):
                    return index
                if note.kind != "text":
                    continue
                continue
            return index
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # PANNING IS THE MIDDLE BUTTON, in every tool. See set_tool.
        if event.button() == Qt.MouseButton.MiddleButton:
            self._start_pan(event)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        where = self.mapToScene(event.position().toPoint())
        self._press_at = event.position().toPoint()
        self._press_scene = where

        if self.tool == "wire":
            pin = self.pin_at(where)
            # A pin wins over the wire running into it: at a pin the two are one point, and
            # a wire drawn to a pin is the ordinary case.
            tee = self.tee_at(where) if pin is None else None
            if tee is not None:
                self._tee_click(tee)
            else:
                self._wire_click(pin)
            event.accept()
            return

        if self.tool == "label":
            pin = self.pin_at(where)
            if pin is not None:
                self.labelRequested.emit(pin[0], pin[1])
            event.accept()
            return

        if self.tool == "text":
            point = snap_to_grid(Point2(x=where.x(), y=where.y()))
            self.noteDrawn.emit("text", point.x, point.y, point.x, point.y)
            event.accept()
            return

        if self.tool in self.SHAPE_TOOLS:
            self._shape_from = _snapped(where)
            event.accept()
            return

        # -- the select tool ------------------------------------------------
        symbol = self.symbol_at(where)
        if symbol is not None:
            self._press_ref = symbol.ref
            if symbol.ref not in self.selected_refs:
                additive = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                refs = [*self.selected_refs, symbol.ref] if additive else [symbol.ref]
                self.set_selection(refs)
                self.selectionChanged.emit(list(self.selected_refs))
            self.partClicked.emit(symbol.ref)
            event.accept()
            return

        note = self.note_at(where)
        if note is not None:
            self._press_note = note
            self.set_selection([], [note])
            self.selectionChanged.emit([])
            event.accept()
            return

        net = self.net_at(where)
        if net is not None:
            self.set_selection([], [])
            self.selectionChanged.emit([])
            self.netClicked.emit(net[0])
            event.accept()
            return

        self._band_from = where
        self.set_selection([], [])
        self.selectionChanged.emit([])
        self.cleared.emit()
        event.accept()

    def _wire_click(self, pin: tuple[str, str] | None) -> None:
        """One click of the wire tool: take the first pin, or draw to the second.

        THE PATH IS DECIDED HERE, which is what makes the wire tool draw a wire rather than
        merely connect two pins. It used to hand both clicks to the window, which joined the
        pins through the board's own connect tool and left no line on the sheet at all --
        the connection was made and the drawing said nothing about it.

        The window is still told about the first click (``pinClicked``), because what the
        status bar says about a half-made pair is its business.
        """
        if pin is None:
            # A miss cancels the half-made pair rather than leaving it armed. The
            # alternative is a stale first pin joining itself to whatever is clicked three
            # gestures later.
            self.set_pending_pin(None)
            self.pending_tee = None
            self.pinClicked.emit("", "")
            return
        if self.pending_tee is not None:
            # The wire was clicked first: this pin branches off it.
            tee = self.pending_tee
            self.pending_tee = None
            self._emit_tee(pin, tee)
            return
        pending = self.pending_pin
        if pending is None or pending == pin:
            self.set_pending_pin(None if pending == pin else pin)
            self.pinClicked.emit(*(("", "") if pending == pin else pin))
            return
        if self.item is None:
            return
        start = pin_anchor(self.item.drawing, *pending)
        end = pin_anchor(self.item.drawing, *pin)
        self.set_pending_pin(None)
        self._clear_ghosts()
        if start is None or end is None:
            return
        path = [(point.x(), point.y()) for point in _elbow(start, end)]
        self.wireDrawn.emit(pending[0], pending[1], pin[0], pin[1], path)

    def _tee_click(self, tee: Tee) -> None:
        """The wire tool clicked on a wire: finish a T from the pin taken first, or take
        the wire first and wait for the pin."""
        pending = self.pending_pin
        if pending is not None:
            self._emit_tee(pending, tee)
            return
        self.pending_tee = tee
        self.teeStarted.emit(
            " – ".join(f"{end.component_ref}.{end.pin}" for end in tee.ends)
        )

    def _emit_tee(self, pin: tuple[str, str], tee: Tee) -> None:
        self.set_pending_pin(None)
        self.pending_tee = None
        self._clear_ghosts()
        if self.item is None:
            return
        if NetNode(component_ref=pin[0], pin=pin[1]) in tee.ends:
            # A branch from one of the wire's own ends back onto it joins nothing new.
            self.pinClicked.emit("", "")
            return
        start = pin_anchor(self.item.drawing, *pin)
        if start is None:
            return
        path = [(point.x(), point.y()) for point in _tee_path(start, tee.at, tee.horizontal)]
        a, b = tee.ends
        self.wireTeed.emit(pin[0], pin[1], a.component_ref, a.pin, b.component_ref, b.pin, path)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            self._pan_to(event)
            event.accept()
            return

        where = self.mapToScene(event.position().toPoint())

        if self.item is not None and self._shape_from is not None:
            self.item.ghost_shape = (self.tool, self._shape_from, _snapped(where))
            self.item.update()
            event.accept()
            return

        if self.item is not None and self._band_from is not None:
            self.item.ghost_shape = ("rectangle", self._band_from, where)
            self.item.update()
            event.accept()
            return

        if self.item is not None and self.tool == "wire":
            hovered = self.pin_at(where)
            if hovered != self.item.hover_pin:
                self.item.hover_pin = hovered
                self.item.update()

        if self.item is not None and self.tool == "wire" and self.pending_pin is not None:
            start = pin_anchor(self.item.drawing, *self.pending_pin)
            if start is not None:
                # Over a wire, the preview is the T it would draw: square onto the wire.
                tee = self.tee_at(where) if self.pin_at(where) is None else None
                self.item.ghost_path = (
                    _tee_path(start, tee.at, tee.horizontal)
                    if tee is not None
                    else _elbow(start, _snapped(where))
                )
                self.item.update()
        elif self.item is not None and self.tool == "wire" and self.pending_tee is not None:
            pin = self.pin_at(where)
            target = pin_anchor(self.item.drawing, *pin) if pin is not None else None
            tee = self.pending_tee
            self.item.ghost_path = _tee_path(
                target if target is not None else _snapped(where), tee.at, tee.horizontal
            )
            self.item.update()

        if self._press_ref is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag_symbols(event, where)
            event.accept()
            return

        if self._press_note is not None and event.buttons() & Qt.MouseButton.LeftButton:
            event.accept()
            return

        self.setToolTip(self.describe(where))
        super().mouseMoveEvent(event)

    def _drag_symbols(self, event: QMouseEvent, where: QPointF) -> None:
        """Move the selection about the sheet, or hand it to the board.

        ONE GESTURE, TWO DESTINATIONS, and which one it is is decided by where the pointer
        goes: inside the sheet it is a move, and the moment it leaves the panel it becomes
        a Qt drag carrying the reference -- which is what lands it on a hole when it is
        dropped on the board. Anything else would mean two ways to pick a symbol up.
        """
        if self._press_at is None or self.item is None:
            return
        moved = event.position().toPoint() - self._press_at
        if not self._dragging and moved.manhattanLength() < QApplication.startDragDistance():
            return
        if not self.viewport().rect().contains(event.position().toPoint()):
            ref = self._press_ref
            self._clear_ghosts()
            if ref is not None:
                self._start_board_drag(ref)
            return
        self._dragging = True
        start = self._press_scene or where
        self.item.drag_offset = _snapped(where - start)
        self.item.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._end_pan()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return

        where = self.mapToScene(event.position().toPoint())

        if self.tool == "wire":
            # A DRAG FROM A PIN IS A WIRE, as much as two clicks are. The press already took
            # the first pin; released over another pin, or over a drawn wire, the drag ends
            # the wire there. Released over nothing, the first pin stays taken and the next
            # click finishes it -- the gesture falls back to the two clicks it always was.
            pressed = self._press_at
            self._press_at = None
            travelled = (
                (event.position().toPoint() - pressed).manhattanLength()
                if pressed is not None
                else 0
            )
            if travelled > DRAG_WIRE_PX and self.pending_pin is not None:
                pin = self.pin_at(where)
                if pin is not None and pin != self.pending_pin:
                    self._wire_click(pin)
                elif pin is None:
                    tee = self.tee_at(where)
                    if tee is not None:
                        self._tee_click(tee)
            event.accept()
            return

        if self._shape_from is not None:
            start, end = self._shape_from, _snapped(where)
            self._clear_ghosts()
            if start != end:
                self.noteDrawn.emit(self.tool, start.x(), start.y(), end.x(), end.y())
            event.accept()
            return

        if self._band_from is not None:
            box = QRectF(self._band_from, where).normalized()
            self._clear_ghosts()
            if box.width() > 1.0 or box.height() > 1.0:
                self.set_selection(self._symbols_within(box))
                self.selectionChanged.emit(list(self.selected_refs))
            event.accept()
            return

        if self._dragging and self.item is not None and self.item.drag_offset is not None:
            offset = self.item.drag_offset
            moved = [
                (symbol.ref, symbol.at.x + offset.x(), symbol.at.y + offset.y())
                for symbol in self.item.drawing.symbols
                if symbol.ref in self.selected_refs
            ]
            self._clear_ghosts()
            if moved and (offset.x() or offset.y()):
                self.symbolsMoved.emit(moved)
            event.accept()
            return

        if self._press_note is not None:
            self._clear_ghosts()
            event.accept()
            return

        self._clear_ghosts()
        super().mouseReleaseEvent(event)

    def _symbols_within(self, box: QRectF) -> list[str]:
        if self.item is None:
            return []
        return [
            symbol.ref
            for symbol in self.item.drawing.symbols
            if box.intersects(
                QRectF(symbol.at.x, symbol.at.y, symbol.width, symbol.height)
            )
        ]

    def event(self, event: QEvent) -> bool:
        # R TURNS WHAT IS SELECTED IN THE VIEW THAT HAS THE KEYBOARD. The board's Rotate owns
        # R for the whole window, and the sheet's Turn used to own it too -- two shortcuts
        # on one key, which Qt calls ambiguous and answers by firing NEITHER: with a part
        # selected on the board and the schematic panel open, R did nothing anywhere.
        # Accepting the override is how a focused widget takes a key back from the
        # window's shortcuts, so R reaches keyPressEvent below and the board keeps it
        # everywhere else.
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and _turn_of(event) is not None
        ):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        turn = _turn_of(event)
        if turn is not None:
            self.turnRequested.emit(turn)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            if self.tool != "select":
                self.set_tool("select")
            else:
                self._clear_ghosts()
                self.set_selection([], [])
                self.selectionChanged.emit([])
            event.accept()
            return
        step = {
            Qt.Key.Key_Left: (-GRID_MM, 0.0),
            Qt.Key.Key_Right: (GRID_MM, 0.0),
            Qt.Key.Key_Up: (0.0, -GRID_MM),
            Qt.Key.Key_Down: (0.0, GRID_MM),
        }.get(Qt.Key(event.key()))
        if step is not None and self.selected_refs and self.item is not None:
            # ONE GRID SQUARE, and the same command a drag ends in -- so it undoes and
            # redoes as one thing, which is the rule the board's own nudge follows.
            dx, dy = step
            self.symbolsMoved.emit(
                [
                    (symbol.ref, symbol.at.x + dx, symbol.at.y + dy)
                    for symbol in self.item.drawing.symbols
                    if symbol.ref in self.selected_refs
                ]
            )
            event.accept()
            return
        deleting = event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        if deleting and (self.selected_refs or self.selected_notes):
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    # -- panning, on the middle button ---------------------------------------

    def _start_pan(self, event: QMouseEvent) -> None:
        self._panning = True
        self._hand_over_framing()
        self._pan_origin = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _pan_to(self, event: QMouseEvent) -> None:
        delta = event.position() - self._pan_origin
        self._pan_origin = event.position()
        horizontal = self.horizontalScrollBar()
        vertical = self.verticalScrollBar()
        horizontal.setValue(horizontal.value() - int(delta.x()))
        vertical.setValue(vertical.value() - int(delta.y()))

    def _end_pan(self) -> None:
        self._panning = False
        self.setCursor(
            Qt.CursorShape.ArrowCursor
            if self.tool == "select"
            else Qt.CursorShape.CrossCursor
        )

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self.tool != "select":
            # The board's rule: a mode owns the first click of any pair. Two quick clicks
            # on a pin used to take the pin AND open its part's properties over the
            # half-made connection.
            event.accept()
            return
        symbol = self.symbol_at(self.mapToScene(event.position().toPoint()))
        if symbol is not None:
            self.partActivated.emit(symbol.ref)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Ask the window for a menu, unless a tool has a claim on this click.

        While a tool is armed, a right-click cancels instead -- the gesture every drawing
        tool uses for "not that one". A menu here would open over the pin somebody was
        aiming at and leave the pending pin armed underneath it, which is the board's own
        rule about a mode owning the click.
        """
        if self.tool != "select":
            self.set_tool("select")
            event.accept()
            return
        self.contextMenuRequested.emit(event.pos())
        event.accept()

    def _dragged_ref(self, event: QDragMoveEvent | QDropEvent) -> str | None:
        data = event.mimeData()
        if data is None or not data.hasFormat(PART_MIME):
            return None
        return data.text().strip() or None

    def _dragged_footprint(self, event: QDragMoveEvent | QDropEvent) -> str | None:
        data = event.mimeData()
        if data is None or not data.hasFormat(FOOTPRINT_MIME):
            return None
        return data.text().strip() or None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dragged_ref(event) is None and self._dragged_footprint(event) is None:
            event.ignore()
            return
        event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._dragged_ref(event) is None and self._dragged_footprint(event) is None:
            event.ignore()
            return
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        """A symbol dropped back on the sheet, or a part dragged in from the library.

        The second one is the sheet's half of "add a part": the library is a list of what a
        part could BE, and dropping one here is saying this design has one, there. It is
        ``part.add`` and not ``component.place`` -- the board is not involved, which is the
        whole point of drawing a circuit first.
        """
        where = _snapped(self.mapToScene(event.position().toPoint()))
        footprint_id = self._dragged_footprint(event)
        if footprint_id is not None:
            event.acceptProposedAction()
            self.footprintDropped.emit(footprint_id, where.x(), where.y())
            return
        ref = self._dragged_ref(event)
        if ref is None or self.item is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.symbolsMoved.emit([(ref, where.x(), where.y())])

    def _start_board_drag(self, ref: str) -> None:
        """Hand a symbol to whatever is outside this panel.

        WHAT IS DRAGGED IS THE PART, not the symbol. Dropped on the board it lands on a
        HOLE, which is the only position a part has -- so this is the schematic's half of
        "put this one part there", and the board's half is an ordinary ``part.place``.
        """
        data = QMimeData()
        data.setData(PART_MIME, ref.encode("utf-8"))
        # Plain text as well, so dropping one on a text field or another application says
        # something useful rather than nothing.
        data.setText(ref)
        drag = QDrag(self)
        drag.setMimeData(data)
        picture = self._symbol_pixmap(ref)
        if picture is not None:
            # Beside the pointer: over the board the ghost is what shows where it lands.
            drag.setPixmap(picture_beside_the_pointer(picture))
            drag.setHotSpot(QPoint(0, 0))
        drag.exec(Qt.DropAction.CopyAction)

    #: How big the picture under the pointer may get while a symbol is being dragged. A
    #: 40-pin DIP at sheet scale is most of the panel, and a drag whose cursor covers what
    #: it is being aimed at is a drag you cannot aim.
    DRAG_PICTURE_PX = 120

    def _symbol_pixmap(self, ref: str) -> QPixmap | None:
        """The symbol itself, rendered small, to carry under the pointer.

        The SHEET ITEM draws it rather than a second drawing being made: one item paints
        the whole sheet, so asking it to paint a rectangle of itself is the only way to get
        a picture of one symbol that cannot disagree with the symbol on screen.
        """
        if self.item is None:
            return None
        symbol = next((s for s in self.item.drawing.symbols if s.ref == ref), None)
        if symbol is None:
            return None
        box = QRectF(symbol.at.x, symbol.at.y, symbol.width, symbol.height)
        if box.isEmpty():
            return None
        scale = min(
            self.DRAG_PICTURE_PX / box.width(), self.DRAG_PICTURE_PX / box.height(), 12.0
        )
        picture = QPixmap(
            max(1, round(box.width() * scale)), max(1, round(box.height() * scale))
        )
        picture.fill(QColor(SHEET))
        painter = QPainter(picture)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(scale, scale)
        painter.translate(-box.left(), -box.top())
        self.item.paint(painter, QStyleOptionGraphicsItem(), None)
        painter.end()
        return picture

    def describe(self, scene_pos: QPointF) -> str:
        """What is under the cursor, as one line -- and below it, what ERC says about the
        pin or the part there, a line each. Empty when there is nothing.

        Separate from the tooltip so it can be tested without a mouse, which is the only
        way this file gets tested at all on a machine with no font database.

        While wiring it names PINS and nothing else, because a pin is the only thing a
        click can land on then — a tooltip offering a net under the cursor would be
        describing something the next click cannot select.
        """
        lines = (self._what_is_under(scene_pos), *self.findings_at(scene_pos))
        return "\n".join(line for line in lines if line)

    def _what_is_under(self, scene_pos: QPointF) -> str:
        if self.wiring:
            pin = self.pin_at(scene_pos)
            return f"{pin[0]}.{pin[1]}" if pin is not None else ""
        symbol = self.symbol_at(scene_pos)
        if symbol is not None:
            parts = [symbol.ref]
            if symbol.value:
                parts.append(symbol.value)
            if symbol.footprint_id:
                parts.append(symbol.footprint_id)
            if symbol.undefined:
                parts.append(t("not in the design"))
            elif symbol.unplaced:
                parts.append(t("not placed yet"))
            return " · ".join(parts)
        net = self.net_at(scene_pos)
        return net[1] if net is not None else ""


def _snapped(point: QPointF) -> QPointF:
    """The nearest grid intersection, through the engine's own answer.

    ``schematic.snap_to_grid`` is the one place a sheet position is rounded, so a symbol
    dropped by this panel and a wire drawn by it land on the same lattice -- and so does
    anything an agent puts there through the MCP server.
    """
    snapped = snap_to_grid(Point2(x=point.x(), y=point.y()))
    return QPointF(snapped.x, snapped.y)


def _elbow(start: QPointF, end: QPointF) -> tuple[QPointF, ...]:
    """Two orthogonal segments between two points, turning once.

    HORIZONTAL FIRST, always. A wire tool that picked the corner by whichever leg was
    longer would flip the route while the pointer moved, which makes it impossible to aim;
    one rule means the preview only ever grows and shrinks. A wire that wants the other
    corner is two wires, or a drag through the middle.
    """
    if start.x() == end.x() or start.y() == end.y():
        return (start, end)
    return (start, QPointF(end.x(), start.y()), end)


@dataclass(frozen=True, slots=True)
class Tee:
    """Where a T lands: the drawn wire, by the two pins that name it, and the point on it."""

    ends: tuple[NetNode, NetNode]
    at: QPointF
    #: Whether the run it lands on is horizontal, which decides the corner of the branch.
    horizontal: bool


def _tee_path(start: QPointF, at: QPointF, host_horizontal: bool) -> tuple[QPointF, ...]:
    """From a pin to a T, meeting the wire square on.

    NOT ``_elbow``'s horizontal-first rule: onto a vertical wire that rule ends with a
    vertical run lying along the wire instead of a line coming into it, which is a wire
    drawn on top of a wire and no T at all. So the last run is always across the wire.
    """
    if start.x() == at.x() or start.y() == at.y():
        return (start, at)
    corner = QPointF(at.x(), start.y()) if host_horizontal else QPointF(start.x(), at.y())
    return (start, corner, at)


def _distance_to_segment(point: QPointF, start: QPointF, end: QPointF) -> float:
    dx, dy = end.x() - start.x(), end.y() - start.y()
    length = dx * dx + dy * dy
    if length <= 1e-12:
        return QPointF(point - start).manhattanLength()
    t = ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / length
    t = max(0.0, min(1.0, t))
    near = QPointF(start.x() + t * dx, start.y() + t * dy)
    delta = point - near
    return float((delta.x() ** 2 + delta.y() ** 2) ** 0.5)
