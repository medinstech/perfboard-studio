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

import itertools
import math
from collections.abc import Callable, Iterable, Sequence
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
    QFocusEvent,
    QFontMetricsF,
    QKeyEvent,
    QMouseEvent,
    QNativeGestureEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QResizeEvent,
    QTransform,
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
from perfboard_studio.model import NetNode, Point2, SheetWire
from perfboard_studio.schematic import (
    GRID_MM,
    NET_LABEL_MM,
    PIN_LABEL_MM,
    PIN_PITCH_MM,
    RAIL_BAR_REACH,
    RAIL_GLYPH_MM,
    REF_LABEL_MM,
    VALUE_LABEL_MM,
    Annotation,
    Label,
    NoConnect,
    Rail,
    SchematicDrawing,
    Symbol,
    Wire,
    moved_corner,
    moved_run,
    no_connect_arms,
    rail_glyph_bars,
    route_sheet_wire,
    snap_to_grid,
)

from . import theme
from .canvasinput import wheel_intent
from .i18n import t
from .scenetext import draw_flag_label, draw_outlined_label, label_font, label_plate_rect

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
# ("The board's look is saved with it"): `theme` colours the application, `view2d`'s block
# colours the physical object, and this colours a DRAWING -- which is neither. A schematic
# is ink on paper, so it is drawn as ink on paper: one line weight for everything, colour
# used only to separate the three net classes and to say what is selected.

#: The paper and the ink are the theme's: dark ink on near-white in the light theme, light
#: on the board's own near-black in the dark one.
SHEET = theme.ACTIVE.sheet_paper
INK = theme.ACTIVE.sheet_ink
INK_DIM = theme.ACTIVE.sheet_ink_dim
#: The grid, and the every-fifth line that lets you count squares without counting them.
#:
#: A schematic without one is a drawing floating in the dark: nothing says how big the
#: sheet is, nothing says whether two symbols are aligned, and the pan has no landmarks --
#: which is what "there is nowhere to look" feels like on an empty document. It is drawn at
#: the layout's OWN pitch (``schematic.GRID_MM``, 2.54 mm, the same pitch as the board),
#: so the squares mean something rather than being wallpaper.
GRID_MAJOR = theme.ACTIVE.sheet_grid_major
#: Inside a symbol's body, and behind a net's name: a tint of the paper, so a symbol is a
#: thing on the sheet rather than an outline over the grid.
BODY_FILL = theme.ACTIVE.sheet_body
#: The net classes in the ratsnest's colours, so a net is one colour on the board and on
#: the sheet. They were two: amber power here and orange there, and two blues.
SIGNAL = theme.NET_COLOURS["signal"]
POWER = theme.NET_COLOURS["power"]
GROUND = theme.NET_COLOURS["ground"]
HIGHLIGHT = theme.ACTIVE.accent
UNDEFINED = theme.ACTIVE.warning

#: Line weights in millimetres of sheet. A schematic has one weight for wires and a
#: slightly heavier one for symbol bodies, which is what makes a body read as a thing and a
#: wire as a connection between things.
#: Chosen on 2026-10-28 from rendered sheets, heavier than the 0.30 / 0.40 they were: at
#: the zoom a sheet opens at, a 0.3 mm wire in a light colour was a hairline.
WIRE_MM = 0.40
BODY_MM = 0.50
HIGHLIGHT_MM = 0.85

#: Junction dot radius, in millimetres of sheet, so it is part of the drawing rather than
#: of the zoom. The rail glyph gets no constant here at all: its bars sit in room the LAYOUT
#: cleared, so ``schematic.rail_glyph_bars`` owns them and both renderers ask it rather than
#: each holding a half-width that could drift wider than the clearance.
DOT_MM = 0.75

#: The smallest each kind of text is drawn, in pixels, however far the sheet is zoomed out.
#: Above it text is its sheet size -- the size the layout cleared room for.
#: Chosen from sheets rendered side by side at the zoom they open at, 3 to 5 px/mm in a
#: typical panel. The floors were 8/7/7/6, a step under the sheet sizes at 5 px/mm, so a
#: fitted sheet drew its text at its own size -- and its pin names 6 px tall, which nobody
#: could read without zooming in first, the first thing anybody opening a sheet then did.
#: At these the text is read where the sheet opens, a little larger than the room the
#: layout cleared for it; ``BOUNDS_PAD_MM`` is what keeps that from leaving debris.
REF_PX = 13
VALUE_PX = 11
NET_PX = 11
PIN_PX = 10

#: Text on the sheet is outlined in the paper's colour, so it reads where it crosses a wire.
TEXT_HALO = theme.ACTIVE.sheet_paper

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
SELECTED = theme.ACTIVE.sheet_selected
SELECTION_BOX_MM = 0.25
#: How far outside a symbol's own box the selection rectangle is drawn.
SELECTION_PAD_MM = 0.8

#: A note: ink on the drawing that is not the circuit, so it is drawn in the dim ink and
#: never in a net colour.
NOTE = theme.ACTIVE.sheet_note
NOTE_MM = 0.30

#: The line that follows the pointer while a wire is being drawn, and the box that follows
#: it while a shape is.
GHOST_MM = 0.35

#: What ERC says about a pin, drawn ON the pin: a ring in the application's error and warning
#: colours, because a finding is the application talking about the drawing rather than part
#: of the drawing. Chosen on 2026-10-19 from three rendered candidates (filled rings for
#: both, this, and a "!" badge beside the pin). The warning ring is DASHED AND UNFILLED
#: because the warning amber was ``POWER`` then: a filled amber ring on a +5V wire read as
#: one more dot on the rail. Power is the ratsnest's orange now, and the shapes still differ,
#: so severity reads without the colour.
MARK_ERROR = theme.ACTIVE.danger
MARK_WARNING = theme.ACTIVE.warning
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

#: WHAT DELETE DOES TO A SELECTED WIRE, in one place so it is one line to change.
#: "disconnect" is KiCad's: the wire goes and a pin only it joined leaves the net
#: (``sheet.wire.cut``); "rub-out" takes the line off and leaves the pins connected, the net
#: saying so by name (``sheet.wire.delete``, still the right-click "Remove Line Only").
#: The window reads it in ``MainWindow._on_sheet_wires_delete``.
WIRE_DELETE: Literal["disconnect", "rub-out"] = "disconnect"

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
        #: The drawn wire the next Delete rubs out, and the one under the pointer, as paths.
        self.selected_wire_path: tuple[Point2, ...] = ()
        self.hover_wire_path: tuple[Point2, ...] = ()
        #: The wires as a drag in progress would leave them (``SchematicView.live_wires_for``),
        #: drawn in place of the drawing's own while the symbols are held.
        self.live_wires: tuple[Wire, ...] | None = None

    def set_wire_selection(self, path: Sequence[Point2], hover: Sequence[Point2] = ()) -> None:
        path, hover = tuple(path), tuple(hover)
        if path == self.selected_wire_path and hover == self.hover_wire_path:
            return
        self.selected_wire_path, self.hover_wire_path = path, hover
        self.update()

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

        for wire in drawing.wires if self.live_wires is None else self.live_wires:
            self._stroke(painter, wire.path, wire.net_class, wire.net_id in self.highlight_nets)
        for rail in drawing.rails:
            self._stroke(painter, rail.path, rail.net_class, rail.net_id in self.highlight_nets)
            self._rail_glyph(painter, rail)

        if self.hover_wire_path and self.hover_wire_path != self.selected_wire_path:
            self._stroke(painter, self.hover_wire_path, "signal", True)
        if self.selected_wire_path:
            self._stroke(painter, self.selected_wire_path, "signal", True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(SELECTED)))
            for corner in self.selected_wire_path:
                painter.drawEllipse(_point(corner), DOT_MM, DOT_MM)
            painter.setBrush(Qt.BrushStyle.NoBrush)

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
                if shape.filled:
                    painter.setBrush(QBrush(QColor(colour)))
                elif _is_body(polygon):
                    painter.setBrush(QBrush(QColor(BODY_FILL)))
                else:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
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
        pins_fit = pin_text_fits(scale, sizes["pin"])
        places = label_places(
            self.drawing.labels, painter.transform(), sizes,
            wires=[wire.path for wire in self.drawing.wires], rails=self.drawing.rails,
        )
        back = painter.transform().inverted()[0]
        for index, label in enumerate(self.drawing.labels):
            if label.kind != "pin" and index not in places:
                continue
            if label.kind == "rail":
                device, alignment = places[index]
                draw_outlined_label(
                    painter, back.map(device), label.text, sizes["net"], alignment,
                    bold=False, colour=QColor(SIGNAL), halo=QColor(TEXT_HALO),
                )
                continue
            if label.kind == "ref":
                colour, size, bold = INK, sizes["ref"], True
            elif label.kind == "value":
                colour, size, bold = INK_DIM, sizes["value"], False
            elif label.kind in ("net", "rail"):
                colour, size, bold = SIGNAL, sizes["net"], False
            else:
                if not pins_fit:
                    continue
                colour, size, bold = INK_DIM, sizes["pin"], False
            if label.kind == "net":
                draw_flag_label(
                    painter, _point(label.at), label.text, size, label_alignment(label),
                    colour=QColor(colour), fill=QColor(BODY_FILL),
                )
                continue
            draw_outlined_label(
                painter, _point(label.at), label.text, size, label_alignment(label),
                bold=bold, colour=QColor(colour), halo=QColor(TEXT_HALO),
            )


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------


#: Which label keeps its place when two would print on one another, most important
#: first: what a part is called, then what a wire is called, then a supply's name, then a
#: part's value. Pin text is inside its own symbol and has ``pin_text_fits`` instead.
LABEL_PRIORITY = {"ref": 0, "net": 1, "rail": 2, "value": 3}


def visible_labels(
    labels: Sequence[Label],
    transform: QTransform,
    sizes: dict[str, int],
    wires: Sequence[Sequence[Point2]] = (),
    rails: Sequence[Rail] = (),
) -> list[int]:
    """The labels that can be drawn at this zoom without printing over one another, by
    index into ``labels`` -- ``label_places`` without the places."""
    return sorted(label_places(labels, transform, sizes, wires, rails))


#: How far a supply's name stands off its own glyph when it is moved beside it, in device
#: pixels: past the plate's own padding (``scenetext._plate``), so the plate clears the bar.
RAIL_NAME_GAP_PX = 6.0


def label_places(
    labels: Sequence[Label],
    transform: QTransform,
    sizes: dict[str, int],
    wires: Sequence[Sequence[Point2]] = (),
    rails: Sequence[Rail] = (),
) -> dict[int, tuple[QPointF, Qt.AlignmentFlag]]:
    """Where each label that can be drawn at this zoom goes: its anchor in DEVICE pixels
    and ``draw_label``'s alignment, by index into ``labels``.

    The LAYOUT never overlaps two labels: each is placed clear of the others at its size on
    the sheet, and the exports draw them at that size. The panel cannot -- zoomed out, text
    is held at a size that can be read (``label_px``), two or three times the room the
    layout gave it, and "VCC" landed on "VCC", a value on a net's name, a whole connector's
    names in one smudge. So the panel draws them in ``LABEL_PRIORITY`` order and leaves out
    any that would land on one already drawn; each comes back as the view closes in and
    there is room, and nothing on paper changes. Deterministic: same sheet, same zoom, same
    labels.

    A supply's name must not print on a WIRE either (``wires``, the drawing's), nor on a
    rail's stub or bars (``rails``). The layout keeps it inside the band over its bar, which
    stops short of the next lane; held at a readable size it reached into that lane, and the
    NE555 arranged had a VCC printed across the wire running there. So where it is drawn
    over its bar would meet one, it tries its other places in ``_rail_name_places`` order
    and takes the first that is clear, and only where none is does it wait for a closer
    zoom. Two rails on one board are told apart by nothing else -- orange says power, not
    which one. A net's own name sits on its own wire, on a flag, so it is not asked.
    """
    order = sorted(
        (index for index, label in enumerate(labels) if label.kind in LABEL_PRIORITY),
        key=lambda index: (LABEL_PRIORITY[labels[index].kind], index),
    )
    # Each line on screen with the rail it belongs to, None for a wire: a name over its own
    # bar is where the layout put it, and its own glyph does not count against it there.
    lines: list[tuple[Rail | None, Sequence[Point2]]] = [(None, path) for path in wires]
    for rail in rails:
        lines.append((rail, rail.path))
        lines.extend((rail, bar) for bar in rail_glyph_bars(rail))
    runs = [
        (owner, transform.mapRect(QRectF(_point(p), _point(q)).normalized()).adjusted(-1, -1, 1, 1))
        for owner, path in lines
        for p, q in itertools.pairwise(path)
    ]
    kept: dict[int, tuple[QPointF, Qt.AlignmentFlag]] = {}
    taken: list[QRectF] = []
    for index in order:
        label = labels[index]
        size = sizes["net"] if label.kind in ("net", "rail") else sizes[label.kind]
        bold = label.kind in ("ref", "net")
        places = [(transform.map(_point(label.at)), label_alignment(label))]
        own: Rail | None = None
        if label.kind == "rail":
            own, places = _rail_name_places(label, places[0], transform, rails)
        for place, (device, alignment) in enumerate(places):
            rect = label_plate_rect(device, label.text, size, alignment, bold=bold)
            if label.kind == "rail" and any(
                rect.intersects(run) for owner, run in runs
                if place or owner is None or owner is not own
            ):
                continue
            if any(rect.intersects(other) for other in taken):
                continue
            kept[index] = (device, alignment)
            taken.append(rect)
            break
    return kept


def _rail_name_places(
    label: Label,
    over: tuple[QPointF, Qt.AlignmentFlag],
    transform: QTransform,
    rails: Sequence[Rail],
) -> tuple[Rail | None, list[tuple[QPointF, Qt.AlignmentFlag]]]:
    """A supply's name's glyph and places, the one the layout gave it first: past the end of the bar
    (where the layout put it), then beside the bar to the right and to the left, then on
    the stub's side of the bar, right of the stub and left of it.

    The glyph is the rail whose name this is, at the label's x -- ``_rail_names`` puts the
    name on the bar's centre line -- and nearest in y. A label no rail owns keeps its one
    place.
    """
    own = [
        rail for rail in rails
        if rail.net_name == label.text and abs(rail.at.x - label.at.x) < 1e-6
    ]
    if not own:
        return None, [over]
    rail = min(own, key=lambda rail: abs(rail.at.y - label.at.y))
    bar = transform.map(_point(rail.at))
    half = transform.map(QPointF(rail.at.x + RAIL_GLYPH_MM * RAIL_BAR_REACH, rail.at.y)).x() - bar.x()
    gap = RAIL_NAME_GAP_PX
    # The stub is below the bar for a rail pointing up, and above it for one pointing down.
    stub_side = Qt.AlignmentFlag.AlignBottom if rail.direction == "up" else Qt.AlignmentFlag.AlignTop
    step = gap if rail.direction == "up" else -gap
    middle = Qt.AlignmentFlag.AlignVCenter
    return rail, [
        over,
        (QPointF(bar.x() + half + gap, bar.y()), Qt.AlignmentFlag.AlignRight | middle),
        (QPointF(bar.x() - half - gap, bar.y()), Qt.AlignmentFlag.AlignLeft | middle),
        (QPointF(bar.x() + gap, bar.y() + step), Qt.AlignmentFlag.AlignRight | stub_side),
        (QPointF(bar.x() - gap, bar.y() + step), Qt.AlignmentFlag.AlignLeft | stub_side),
    ]


def pin_text_fits(px_per_mm: float, pin_px: int) -> bool:
    """Whether a pin's name and number can be drawn at this zoom without running into the
    next pin's. Zoomed out on a big chip the pins are closer together on screen than the
    text is tall, and every name and number over-printed its neighbours into a grey bar; the
    pins themselves are still drawn, and the text comes back as soon as it fits."""
    height = QFontMetricsF(label_font(pin_px, False)).height()
    return PIN_PITCH_MM * px_per_mm >= height * PIN_TEXT_ROOM


#: How much more than one line of pin text a pin's pitch on screen has to be.
PIN_TEXT_ROOM = 1.1


def _is_body(polygon: QPolygonF) -> bool:
    """A closed outline with room inside it -- a symbol's body, a resistor's box -- rather
    than an arrowhead or a diode's bar, which stay outlines."""
    box = polygon.boundingRect()
    return box.width() > BODY_MIN_MM and box.height() > BODY_MIN_MM


#: The smallest closed outline that is filled as a body, in sheet millimetres.
BODY_MIN_MM = 1.5


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
    #: A drawn wire was dragged by a corner or a run into a new shape: (ref a, pin a,
    #: ref b, pin b, the new path as (x, y) pairs). Its ends and its net stay as they were.
    wireReshaped = Signal(str, str, str, str, list)
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
    #: Delete was pressed with a drawn wire selected: a list of (ref a, pin a, ref b,
    #: pin b). What Delete means to a wire is ``WIRE_DELETE``, applied by the window.
    wireDeleteRequested = Signal(list)
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
        #: The corners clicked since the wire tool's first click, in the order they were
        #: clicked, snapped to the grid. Empty, a pin-to-pin wire is routed round the
        #: symbols (``_pin_to_pin``); with any, the wire goes where it was clicked.
        self.corners: list[QPointF] = []
        #: Where the pointer last was, so a corner taken back with Backspace redraws the
        #: preview to where the pointer still is.
        self._pointer: QPointF | None = None
        self.selected_refs: list[str] = []
        self.selected_notes: list[int] = []
        #: The drawn wire that is selected, by its two pins, and the wires of a sheet still
        #: being arranged as they WOULD be drawn once it is frozen
        #: (``schematic.wires_as_drawn``, handed over by the window): on that sheet a wire is
        #: clicked like any other, and the freeze happens when something is done to it.
        self.selected_wire: tuple[NetNode, NetNode] | None = None
        self.unfrozen_wires: tuple[SheetWire, ...] = ()
        #: Asked while symbols are dragged, with (ref, x, y) for each: the wires as the drop
        #: would leave them, or None. Set by the window.
        self.live_wires_for: (
            Callable[[list[tuple[str, float, float]]], tuple[Wire, ...] | None] | None
        ) = None
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
        #: A pin pressed in Select: a drag from it is a wire (``mouseMoveEvent``), a click
        #: on it is a click on its symbol.
        self._pin_press: tuple[str, str] | None = None
        #: A drawn wire pressed in Select: its two pins, the path it is drawn on, and what
        #: the press took hold of -- a corner or a run, by index (``_grab``). A drag past
        #: the start distance reshapes it (``_reshaping``); a click only selects it.
        self._press_wire: (
            tuple[tuple[NetNode, NetNode], tuple[Point2, ...], str, int] | None
        ) = None
        self._reshaping = False
        #: The last route ``_pin_to_pin`` found: the drawing itself (held, so a new one is
        #: never mistaken for it), the two pins, the route.
        self._route_memo: (
            tuple[SchematicDrawing, tuple[tuple[str, str], tuple[str, str]], tuple[Point2, ...] | None]
            | None
        ) = None
        #: Middle-button panning, which every tool leaves alone. See set_tool.
        self._panning = False
        self._pan_origin = QPointF()
        #: Which button the pan started on: the middle one, or the left with Space held.
        self._pan_button = Qt.MouseButton.MiddleButton
        #: Space is down, so the left button pans -- the laptop's middle button.
        self._space_held = False
        #: Every wheel pans, and Ctrl+wheel zooms (View > Mouse Wheel). The window sets it.
        self.wheel_scrolls = False
        #: The rubber band, while one is being pulled over empty sheet.
        self._band_from: QPointF | None = None
        #: What a band pulled with Shift or Ctrl adds to: the selection when it started.
        self._band_keeps: list[str] = []
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
        # The major lines only: every 2.54 mm line drew a dense check over the whole sheet,
        # and on paper-white a check is louder than the drawing on it. Chosen 2026-10-28.
        for step, colour in ((GRID_MM * self.GRID_MAJOR_EVERY, GRID_MAJOR),):
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
        self._show_wire_selection()
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
        self.corners = []
        self._clear_ghosts()
        if self.item is not None and self.item.hover_pin is not None:
            # A ring under the pointer means "the wire tool would take this"; with another
            # tool armed it would be a promise nothing keeps.
            self.item.hover_pin = None
            self.item.update()
        self._tool_cursor()

    def set_wiring(self, on: bool) -> None:
        """The wire tool, by the name the window's Wire button has always used."""
        self.set_tool("wire" if on else "select")

    def set_selection(self, refs: Sequence[str], notes: Sequence[int] = ()) -> None:
        self.selected_refs = list(refs)
        self.selected_notes = list(notes)
        self.selected_wire = None
        if self.item is not None:
            self.item.set_selection(refs, {f"n{index}" for index in notes})
            self._show_wire_selection()

    def set_unfrozen_wires(self, wires: Sequence[SheetWire]) -> None:
        """The wires a sheet still being arranged would draw if it were frozen now."""
        self.unfrozen_wires = tuple(wires)
        self._show_wire_selection()

    def wire_runs(self) -> list[tuple[tuple[NetNode, NetNode], tuple[Point2, ...]]]:
        """Every wire that can be selected, by its two pins, with the path it is drawn on:
        the drawn wires, or on a sheet nobody has frozen yet the ones the freeze would keep."""
        if self.item is None:
            return []
        runs = [
            (wire.ends, tuple(wire.path))
            for wire in self.item.drawing.wires
            if wire.ends is not None
        ]
        if not runs:
            runs = [((wire.a, wire.b), tuple(wire.path)) for wire in self.unfrozen_wires]
        return runs

    def wire_at(
        self, scene_pos: QPointF
    ) -> tuple[tuple[NetNode, NetNode], tuple[Point2, ...]] | None:
        """The wire nearest the point within ``PICK_MM``, or None."""
        best: tuple[float, tuple[tuple[NetNode, NetNode], tuple[Point2, ...]]] | None = None
        for ends, path in self.wire_runs():
            for start, end in itertools.pairwise(path):
                distance = _distance_to_segment(scene_pos, _point(start), _point(end))
                if distance <= PICK_MM and (best is None or distance < best[0]):
                    best = (distance, (ends, path))
        return best[1] if best is not None else None

    def _path_of(self, ends: tuple[NetNode, NetNode] | None) -> tuple[Point2, ...]:
        if ends is None:
            return ()
        for run_ends, path in self.wire_runs():
            if run_ends == ends:
                return path
        return ()

    def _show_wire_selection(self, hover: Sequence[Point2] = ()) -> None:
        """Paint the selected wire, and forget it if the drawing no longer has it."""
        if self.item is None:
            return
        path = self._path_of(self.selected_wire)
        if not path:
            self.selected_wire = None
        self.item.set_wire_selection(path, hover)

    def _select_wire(self, ends: tuple[NetNode, NetNode], where: QPointF) -> None:
        """Select one drawn wire: it is what Delete rubs out. The net it is on is lit as
        before, so a click on a wire still says which net that is."""
        self.set_selection([], [])
        self.selectionChanged.emit([])
        net = self.net_at(where)
        if net is not None:
            self.netClicked.emit(net[0])
        self.selected_wire = ends
        self._show_wire_selection()

    def wire_in_progress(self) -> bool:
        """Whether the wire tool has its first click -- a pin or a wire -- and is waiting
        for corners or the end."""
        return self.pending_pin is not None or self.pending_tee is not None

    def _drop_wire(self) -> None:
        """Let go of the wire being drawn, corners and all; the tool stays armed. The
        window is told as a miss always told it (``pinClicked`` with no pin)."""
        self.set_pending_pin(None)
        self.pending_tee = None
        self.corners = []
        self._clear_ghosts()
        self.pinClicked.emit("", "")

    def _add_corner(self, where: QPointF) -> None:
        """A click on bare sheet while a wire is being drawn: a corner, on the grid."""
        corner = _snapped(where)
        if not self.corners or self.corners[-1] != corner:
            self.corners.append(corner)
        self._refresh_wire_ghost()

    def _lead_horizontal(self, pin: tuple[str, str]) -> bool:
        """Whether a pin's lead runs across the sheet: a wire leaves and enters it that way."""
        if self.item is not None:
            for symbol in self.item.drawing.symbols:
                if symbol.ref != pin[0]:
                    continue
                for symbol_pin in symbol.pins:
                    if symbol_pin.number == pin[1]:
                        return symbol_pin.side in ("left", "right")
        return True

    def _cornered(
        self,
        start: tuple[str, str] | Tee,
        end: tuple[str, str] | Tee | QPointF,
    ) -> tuple[QPointF, ...]:
        """The wire from its first click through the corners to ``end`` -- a pin, a T, or
        the pointer -- in the order it was drawn. See ``cornered_path``."""
        if self.item is None:
            return ()
        drawing = self.item.drawing
        if isinstance(start, Tee):
            origin, leaves_across = start.at, not start.horizontal
        else:
            anchor = pin_anchor(drawing, *start)
            if anchor is None:
                return ()
            origin, leaves_across = anchor, self._lead_horizontal(start)
        if isinstance(end, Tee):
            return cornered_path(origin, leaves_across, self.corners, end.at, tee=end.horizontal)
        if isinstance(end, QPointF):
            return cornered_path(origin, leaves_across, self.corners, _snapped(end))
        target = pin_anchor(drawing, *end)
        if target is None:
            return ()
        return cornered_path(
            origin, leaves_across, self.corners, target, arrives_across=self._lead_horizontal(end)
        )

    def _refresh_wire_ghost(self) -> None:
        """Draw the wire being drawn, through its corners, as far as the pointer: to the pin
        or the wire under it as the click there would finish it, else to the pointer."""
        if self.item is None or self._pointer is None or not self.corners:
            return
        start: tuple[str, str] | Tee | None = self.pending_pin or self.pending_tee
        if start is None:
            return
        where = self._pointer
        aimed = self.pin_at(where)
        tee = self.tee_at(where) if aimed is None else None
        if aimed is not None and aimed != start:
            self.item.ghost_path = self._cornered(start, aimed)
        elif tee is not None and not isinstance(start, Tee):
            self.item.ghost_path = self._cornered(start, tee)
        else:
            self.item.ghost_path = self._cornered(start, where)
        self.item.update()

    def gesture_in_flight(self) -> bool:
        """Whether the left button is in the middle of something Escape can call off: a
        drag of symbols, a rubber band, or a shape being pulled out."""
        return (
            self._dragging
            or self._reshaping
            or self._band_from is not None
            or self._shape_from is not None
        )

    def select_all(self) -> None:
        """Every symbol on the sheet (Edit > Select All)."""
        if self.item is None:
            return
        self.set_selection([symbol.ref for symbol in self.item.drawing.symbols])
        self.selectionChanged.emit(list(self.selected_refs))

    def _clear_ghosts(self) -> None:
        self._dragging = False
        self._band_from = None
        self._shape_from = None
        self._press_at = None
        self._press_ref = None
        self._press_note = None
        self._press_scene = None
        self._pin_press = None
        self._press_wire = None
        self._reshaping = False
        if self.item is not None:
            self.item.drag_offset = None
            self.item.live_wires = None
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
        """Zoom or pan, by the rule the board uses too (``canvasinput.wheel_intent``)."""
        intent = wheel_intent(event, self.wheel_scrolls)
        if intent.zoom_steps:
            factor = self._clamped_factor(1.18**intent.zoom_steps)
            if factor != 1.0:
                self.scale(factor, factor)
            self._fitted = True
            self._hand_over_framing()
        elif intent.pan_x or intent.pan_y:
            self._hand_over_framing()
            self._pan_by(intent.pan_x, intent.pan_y)
        event.accept()

    def _pinch(self, factor: float) -> None:
        """A trackpad pinch the platform reports as a gesture (macOS) rather than as the
        Ctrl+wheel ``wheelEvent`` already zooms (Windows)."""
        factor = self._clamped_factor(factor)
        if factor != 1.0:
            self.scale(factor, factor)
        self._fitted = True
        self._hand_over_framing()

    def _pan_by(self, dx: float, dy: float) -> None:
        """Move the content by this many pixels: right and down are positive."""
        horizontal = self.horizontalScrollBar()
        vertical = self.verticalScrollBar()
        horizontal.setValue(horizontal.value() - round(dx))
        vertical.setValue(vertical.value() - round(dy))

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
        # PANNING IS THE MIDDLE BUTTON, in every tool, and the left one with Space held, for
        # a laptop that has no middle button. See set_tool.
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_held
        ):
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
            elif pin is None and self.wire_in_progress():
                # BARE SHEET IS A CORNER while a wire is being drawn; it used to call the
                # wire off, so a wire could only ever go where the route put it. Inside a
                # symbol's box it is neither: a corner there would draw the wire through
                # the part, which reads as a short.
                if self.symbol_at(where) is None:
                    self._add_corner(where)
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
        # Shift or Ctrl adds to the selection or takes back out of it, as on the board
        # (``view2d.BoardView._shift_as_ctrl``): Shift used to add and never remove here,
        # and Ctrl did nothing, while on the board it was the other way round.
        additive = bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
        )
        symbol = self.symbol_at(where)
        if symbol is not None and additive and symbol.ref in self.selected_refs:
            # Let go of, and nothing more: a symbol just taken out of the selection is not
            # one to start dragging.
            self.set_selection([ref for ref in self.selected_refs if ref != symbol.ref])
            self.selectionChanged.emit(list(self.selected_refs))
            event.accept()
            return
        if symbol is not None:
            # A PRESS ON A PIN IS WHERE A WIRE STARTS, in Select as in Connect: dragged, it
            # draws the wire (``mouseMoveEvent``) instead of moving the part, which is what
            # a pointer on a pin means far more often. Clicked, it is still a click on the
            # symbol, which is selected either way; the body is what moves it.
            pin = None if additive else self.pin_at(where)
            if pin is None:
                self._press_ref = symbol.ref
            else:
                self._pin_press = pin
            if symbol.ref not in self.selected_refs:
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

        run = self.wire_at(where)
        if run is not None:
            self._select_wire(run[0], where)
            # Held, so that a drag reshapes it: a corner pressed moves, else the run.
            self._press_wire = (run[0], run[1], *_grab(run[1], where))
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
        if additive:
            # A band pulled with Shift or Ctrl adds what it takes to what is selected.
            self._band_keeps = list(self.selected_refs)
            event.accept()
            return
        self._band_keeps = []
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
            self._emit_tee(pin, self.pending_tee)
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
        cornered = self._cornered(pending, pin) if self.corners else ()
        self.set_pending_pin(None)
        self.corners = []
        self._clear_ghosts()
        if start is None or end is None:
            return
        drawn = cornered or self._pin_to_pin(pending, pin, start, end)
        path = [(point.x(), point.y()) for point in drawn]
        self.wireDrawn.emit(pending[0], pending[1], pin[0], pin[1], path)

    def _pin_to_pin(
        self, a: tuple[str, str], b: tuple[str, str], start: QPointF, end: QPointF
    ) -> tuple[QPointF, ...]:
        """The wire from pin to pin: round the symbols (``schematic.route_sheet_wire``), or
        the elbow it always was where there is no way round.

        The last answer is kept with the drawing it was found on: the preview asks on
        every move of the pointer, and the route only changes when the pin under it does.
        """
        if self.item is None:
            return _elbow(start, end)
        drawing = self.item.drawing
        memo = self._route_memo
        if memo is None or memo[0] is not drawing or memo[1] != (a, b):
            memo = (drawing, (a, b), route_sheet_wire(drawing, a, b))
            self._route_memo = memo
        routed = memo[2]
        if routed is None:
            return _elbow(start, end)
        return tuple(QPointF(point.x, point.y) for point in routed)

    def _tee_click(self, tee: Tee) -> None:
        """The wire tool clicked on a wire: finish a T from the pin taken first, or take
        the wire first and wait for the pin."""
        pending = self.pending_pin
        if pending is not None:
            self._emit_tee(pending, tee)
            return
        # Another wire clicked after the first: it is the start now, and corners clicked
        # from the old one would hang off nothing.
        self.corners = []
        self.pending_tee = tee
        self.teeStarted.emit(
            " – ".join(f"{end.component_ref}.{end.pin}" for end in tee.ends)
        )

    def _emit_tee(self, pin: tuple[str, str], tee: Tee) -> None:
        # The corners were clicked from whichever end came first, and the stored path runs
        # from the pin to the T whichever it was.
        cornered: tuple[QPointF, ...] = ()
        if self.corners:
            if self.pending_tee is tee:
                cornered = tuple(reversed(self._cornered(tee, pin)))
            else:
                cornered = self._cornered(pin, tee)
        self.set_pending_pin(None)
        self.pending_tee = None
        self.corners = []
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
        drawn = cornered or _tee_path(start, tee.at, tee.horizontal)
        path = [(point.x(), point.y()) for point in drawn]
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

        if (
            self._pin_press is not None
            and self.pending_pin is None
            and event.buttons() & Qt.MouseButton.LeftButton
            and self._press_at is not None
            and (event.position().toPoint() - self._press_at).manhattanLength() > DRAG_WIRE_PX
        ):
            # Far enough from the pin pressed for this to be a drag: the wire starts there.
            self.set_pending_pin(self._pin_press)
        wiring_from_select = self._pin_press is not None and self.pending_pin is not None

        if self.item is not None and (self.tool == "wire" or wiring_from_select):
            hovered = self.pin_at(where)
            if hovered != self.item.hover_pin:
                self.item.hover_pin = hovered
                self.item.update()

        self._pointer = where
        if self.item is not None and self.tool == "wire" and self.corners:
            self._refresh_wire_ghost()
        elif (
            self.item is not None
            and (self.tool == "wire" or wiring_from_select)
            and self.pending_pin is not None
        ):
            start = pin_anchor(self.item.drawing, *self.pending_pin)
            if start is not None:
                # Over a wire, the preview is the T it would draw: square onto the wire.
                # Over another pin, the route the wire will take round the symbols.
                aimed = self.pin_at(where)
                tee = self.tee_at(where) if aimed is None else None
                aimed_at = pin_anchor(self.item.drawing, *aimed) if aimed is not None else None
                self.item.ghost_path = (
                    _tee_path(start, tee.at, tee.horizontal)
                    if tee is not None
                    else self._pin_to_pin(self.pending_pin, aimed, start, aimed_at)
                    if aimed is not None and aimed_at is not None and aimed != self.pending_pin
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

        if self._pin_press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            event.accept()
            return

        if self._press_ref is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag_symbols(event, where)
            event.accept()
            return

        if self._press_note is not None and event.buttons() & Qt.MouseButton.LeftButton:
            event.accept()
            return

        if self._press_wire is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag_wire(event, where)
            event.accept()
            return

        if self.item is not None and self.tool == "select" and not event.buttons():
            over = self.wire_at(where)
            self._show_wire_selection(over[1] if over is not None else ())
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
        offset = _snapped(where - start)
        if offset != self.item.drag_offset and self.live_wires_for is not None:
            # The wires follow the symbols while they are held, laid as the drop will lay
            # them: the answer comes from the window, which owns the document.
            self.item.live_wires = self.live_wires_for(
                [
                    (symbol.ref, symbol.at.x + offset.x(), symbol.at.y + offset.y())
                    for symbol in self.item.drawing.symbols
                    if symbol.ref in self.selected_refs
                ]
            )
        self.item.drag_offset = offset
        self.item.update()

    def _reshaped(self, where: QPointF) -> tuple[Point2, ...]:
        """The pressed wire's path with what the press took hold of moved to ``where``."""
        if self._press_wire is None:
            return ()
        _ends, path, kind, index = self._press_wire
        to = Point2(x=where.x(), y=where.y())
        return moved_corner(path, index, to) if kind == "corner" else moved_run(path, index, to)

    def _drag_wire(self, event: QMouseEvent, where: QPointF) -> None:
        """Show the pressed wire as it would be drawn with its corner or run where the
        pointer is. Nothing is dispatched until the button comes up."""
        if self._press_at is None or self.item is None:
            return
        moved = event.position().toPoint() - self._press_at
        if not self._reshaping and moved.manhattanLength() < QApplication.startDragDistance():
            return
        self._reshaping = True
        self.item.ghost_path = tuple(_point(point) for point in self._reshaped(where))
        self.item.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._panning and event.button() == self._pan_button:
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

        if self._pin_press is not None:
            # A drag from a pin in Select ends as the wire tool's drag does: on another pin
            # it draws the wire, on a drawn wire it tees into it, and anywhere else nothing
            # is drawn. Select stays Select either way.
            self._pin_press = None
            if self.pending_pin is not None:
                pin = self.pin_at(where)
                tee = self.tee_at(where) if pin is None else None
                if pin is not None and pin != self.pending_pin:
                    self._wire_click(pin)
                elif tee is not None:
                    self._tee_click(tee)
                self.set_pending_pin(None)
                if self.item is not None and self.item.hover_pin is not None:
                    self.item.hover_pin = None
                    self.item.update()
            self._clear_ghosts()
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
                kept = self._band_keeps
                taken = [ref for ref in self._symbols_within(box) if ref not in kept]
                self.set_selection([*kept, *taken])
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

        if self._press_wire is not None:
            held, reshaping = self._press_wire, self._reshaping
            path = self._reshaped(where) if reshaping else ()
            self._clear_ghosts()
            if path and path != held[1]:
                a, b = held[0]
                self.wireReshaped.emit(
                    a.component_ref, a.pin, b.component_ref, b.pin,
                    [(point.x, point.y) for point in path],
                )
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
        # Escape too, but only in the middle of a gesture: the window's Escape shortcut
        # took the key first, so the "never mind" below was unreachable in the running
        # application and a drag let go wherever the pointer happened to be.
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
            and self.gesture_in_flight()
        ):
            event.accept()
            return True
        if (
            isinstance(event, QNativeGestureEvent)
            and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture
        ):
            self._pinch(1.0 + event.value())
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space:
            # Held, it turns the left button into the hand (see mousePressEvent). Taken
            # here, autorepeat and all, so it never reaches a tool as a key of its own.
            if not event.isAutoRepeat():
                self._space_held = True
                if not self._panning:
                    self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        turn = _turn_of(event)
        if turn is not None:
            self.turnRequested.emit(turn)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            if self.gesture_in_flight():
                # Called off, and nothing else: the selection the drag was carrying stays,
                # which is what a second Escape is for.
                self._clear_ghosts()
            elif self.wire_in_progress():
                # The wire being drawn goes, corners and all, and the tool stays for the
                # next one; a second Escape puts the tool down.
                self._drop_wire()
            elif self.tool != "select":
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
        if event.key() == Qt.Key.Key_Backspace and self.wire_in_progress():
            # The last corner taken back; with none left, nothing -- Escape drops the wire.
            if self.corners:
                self.corners.pop()
                if self.item is not None and not self.corners:
                    self.item.ghost_path = ()
                    self.item.update()
                self._refresh_wire_ghost()
            event.accept()
            return
        deleting = event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        if deleting and self.selected_wire is not None:
            a, b = self.selected_wire
            self.wireDeleteRequested.emit([(a.component_ref, a.pin, b.component_ref, b.pin)])
            event.accept()
            return
        if deleting and (self.selected_refs or self.selected_notes):
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self._space_held = False
                if not self._panning:
                    self._tool_cursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        # A Space released while another widget had the keyboard never comes back here,
        # and a left button that still panned afterwards would be a tool that had stopped
        # working.
        self._space_held = False
        if not self._panning:
            self._tool_cursor()
        super().focusOutEvent(event)

    # -- panning, on the middle button or Space with the left -------------------------------

    def _start_pan(self, event: QMouseEvent) -> None:
        self._panning = True
        self._pan_button = event.button()
        self._hand_over_framing()
        self._pan_origin = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _pan_to(self, event: QMouseEvent) -> None:
        delta = event.position() - self._pan_origin
        self._pan_origin = event.position()
        self._pan_by(delta.x(), delta.y())

    def _end_pan(self) -> None:
        self._panning = False
        if self._space_held:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self._tool_cursor()

    def _tool_cursor(self) -> None:
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
        if self.wire_in_progress():
            # A wire being drawn goes first, as Escape does; the next right-click puts the
            # tool down.
            self._drop_wire()
            event.accept()
            return
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


def cornered_path(
    start: QPointF,
    leaves_across: bool,
    corners: Sequence[QPointF],
    end: QPointF,
    *,
    arrives_across: bool | None = None,
    tee: bool | None = None,
) -> tuple[QPointF, ...]:
    """A wire drawn corner by corner: from ``start`` through every clicked corner to ``end``,
    each leg straight where the two points line up and an elbow where they do not.

    EVERY CLICK IS A CORNER, so an elbow's first run is across the run that came into the
    point it leaves -- going on in the same line would make the clicked point no corner at
    all. Out of a pin the first run follows its lead (``leaves_across``: the lead runs
    across the sheet), out of a T it is square off the wire. The last leg comes into a pin
    along its lead (``arrives_across``) and onto a wire square (``tee``: whether the wire
    it lands on is horizontal), as ``_tee_path`` does; to the pointer, neither is asked.
    Points that add nothing -- a repeat, or one in the middle of a straight run -- are
    left out, so what is stored is the corners and the two ends."""
    points = [start]
    across = leaves_across
    for corner in corners:
        here = points[-1]
        if _same(here.y(), corner.y()) or _same(here.x(), corner.x()):
            # In line: one run, and the next one turns off it.
            across = not _same(here.y(), corner.y())
        else:
            points.append(
                QPointF(corner.x(), here.y()) if across else QPointF(here.x(), corner.y())
            )
            # The elbow's second run is the other way, so the next turns back to this one.
        points.append(corner)
    here = points[-1]
    if tee is not None:
        points.extend(_tee_path(here, end, tee)[1:])
    elif _same(here.y(), end.y()) or _same(here.x(), end.x()):
        points.append(end)
    else:
        last_across = arrives_across if arrives_across is not None else not across
        corner = QPointF(here.x(), end.y()) if last_across else QPointF(end.x(), here.y())
        if len(points) >= 2 and _turns_back(points[-2], here, corner):
            # Into the pin along its lead would run back down the line just drawn; coming
            # in from the side is the lesser fault.
            corner = QPointF(end.x(), here.y()) if last_across else QPointF(here.x(), end.y())
        points.extend((corner, end))
    return _tidied(points)


def _same(a: float, b: float) -> bool:
    return abs(a - b) < 1e-6


def _turns_back(a: QPointF, b: QPointF, c: QPointF) -> bool:
    """Whether the run from ``b`` to ``c`` goes back the way ``a`` to ``b`` came."""
    return (b.x() - a.x()) * (c.x() - b.x()) < -1e-9 or (b.y() - a.y()) * (c.y() - b.y()) < -1e-9


def _tidied(points: Sequence[QPointF]) -> tuple[QPointF, ...]:
    """The path without repeated points, or points in the middle of a straight run.

    A point where the line turns back on itself is kept: it is somebody's corner, and taking
    it out would quietly draw a different wire."""
    kept: list[QPointF] = []
    for point in points:
        kept.append(point)
        while len(kept) >= 2:
            a, b = kept[-2], kept[-1]
            if _same(a.x(), b.x()) and _same(a.y(), b.y()):
                del kept[-1]
                continue
            if len(kept) >= 3:
                first = kept[-3]
                in_line = (_same(first.x(), a.x()) and _same(a.x(), b.x())) or (
                    _same(first.y(), a.y()) and _same(a.y(), b.y())
                )
                if in_line and not _turns_back(first, a, b):
                    del kept[-2]
                    continue
            break
    return tuple(kept)


def _grab(path: Sequence[Point2], where: QPointF) -> tuple[str, int]:
    """What a press on a drawn wire takes hold of: a corner within ``PICK_MM`` -- never
    one of the two ends, which are its pins and stay on them -- or else the run nearest."""
    corners = [
        (math.hypot(point.x - where.x(), point.y - where.y()), index)
        for index, point in enumerate(path)
        if 0 < index < len(path) - 1
    ]
    near = min(corners, default=None)
    if near is not None and near[0] <= PICK_MM:
        return "corner", near[1]
    runs = [
        (_distance_to_segment(where, _point(start), _point(end)), index)
        for index, (start, end) in enumerate(itertools.pairwise(path))
    ]
    return "run", min(runs, default=(0.0, 0))[1]


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
