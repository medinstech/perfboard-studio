"""The System view: every board of the document, drawn as the Board panel draws it, and the
cables between them.

Behind the board strip's first entry (``ui.boardstrip``). Each board is the 2D scene's own
drawing of that board alone (``system.board_document``), so a board looks here exactly as it
does when opened; the cables are drawn over them, one line per wire in the wire's colour --
the colour the harness cuts it in -- from its pin on one connector to its pin on the other:
out of the board by the edge nearest the connector, then round the boards rather than over
them (:func:`cable_route`), as the cable runs in the System's 3D.
Click a board or a cable to pick it -- Properties shows it (``inspector._SystemBoardEditor``,
``_CableEditor``), and a click on the bare bench shows the system itself -- and double-click a
board to open it. The pick is the window's, handed back by ``set_selected``, so it outlives a
redraw. The boards sit in ``system.board_row``'s row, the one the 3D panel lays them out by
too; where a person may move them is a later decision, and nothing here is saved.
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections.abc import Sequence
from typing import Literal

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QWidget,
)

from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.geometry import all_pin_holes
from perfboard_studio.lvs import crossed_cables
from perfboard_studio.model import BoardId, Cable, CableEnd, Net, PerfDocument
from perfboard_studio.system import (
    BOARD_GAP_MM,
    board_document,
    board_ids,
    board_row,
    board_title,
    connector_of,
)
from perfboard_studio.wirecolour import net_colours

from . import theme
from .i18n import t
from .view2d import BoardScene, hole_to_screen, named_insulation

#: Pixels per millimetre a board is drawn at before it is scaled into the view: enough that
#: a part's label still reads when the System view is the whole panel.
DRAW_PX_PER_MM = 6.0

#: Millimetres of bench between two boards (``system.board_row``), and round the row.
GAP_MM = BOARD_GAP_MM

_BOARD_ROLE = 0  # QGraphicsItem.data key holding a board's id
_CABLE_ROLE = 1  # ...and a cable's
_TEXT_OVERSIZE = 10.0  # text is laid out this much larger and scaled back (``_text``)

#: How far outside a board's frame a cable runs, in millimetres: clear of the frame and its
#: title, and under half the bench between two frames, so a cable fits between two boards.
CABLE_CLEARANCE_MM = 3.0
#: How far apart the wires of one cable run beside one another.
WIRE_SPACING_MM = 0.8
#: The radius a cable's corners are rounded to.
CABLE_BEND_MM = 3.0

Point = tuple[float, float]
#: left, top, right, bottom -- y grows downward, as in the scene.
Rect = tuple[float, float, float, float]
Side = Literal["left", "top", "right", "bottom"]


def nearest_side(point: Point, rect: Rect) -> Side:
    """The edge of ``rect`` nearest ``point`` -- the way out of a board for a cable from a
    connector there. Ties go left, top, right, bottom, in that order."""
    x, y = point
    left, top, right, bottom = rect
    distances: list[tuple[float, Side]] = [
        (x - left, "left"), (y - top, "top"), (right - x, "right"), (bottom - y, "bottom")
    ]
    return min(distances, key=lambda d: d[0])[1]


def _outside(point: Point, rect: Rect, side: Side, clearance: float) -> Point:
    x, y = point
    left, top, right, bottom = rect
    return {
        "left": (left - clearance, y),
        "top": (x, top - clearance),
        "right": (right + clearance, y),
        "bottom": (x, bottom + clearance),
    }[side]


def _grown(rect: Rect, by: float) -> Rect:
    return (rect[0] - by, rect[1] - by, rect[2] + by, rect[3] + by)


def _crosses(a: Point, b: Point, rect: Rect) -> bool:
    """Whether the segment ``a``-``b`` passes through the inside of ``rect`` (its edges do
    not count): Liang-Barsky clipping, with the clipped part required to have length."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    low, high = 0.0, 1.0
    for p, q in ((-dx, x0 - rect[0]), (dx, rect[2] - x0), (-dy, y0 - rect[1]), (dy, rect[3] - y0)):
        if p == 0:
            if q <= 0:
                return False
            continue
        r = q / p
        if p < 0:
            low = max(low, r)
        else:
            high = min(high, r)
        if low >= high:
            return False
    inside_x = x0 + dx * (low + high) / 2
    inside_y = y0 + dy * (low + high) / 2
    return rect[0] < inside_x < rect[2] and rect[1] < inside_y < rect[3]


def cable_route(
    start: Point,
    start_out: tuple[Rect, Side],
    end: Point,
    end_out: tuple[Rect, Side],
    boards: Sequence[Rect],
    clearance: float = CABLE_CLEARANCE_MM,
) -> list[Point]:
    """A wire's way from ``start`` to ``end``: straight out of its board by ``start_out``'s
    side to ``clearance`` beyond it, the shortest way round every board in ``boards`` at that
    clearance, and straight in to ``end`` by its side -- so the wire crosses a board only
    between its own pin and that board's edge.

    The way round is the shortest path over the corners of the boards grown by ``clearance``
    (a visibility graph: a corner joins another where the line between them goes through no
    board). Two connectors facing each other across the bench are joined straight. Where no
    way round exists -- a board inside another, which a row never has -- the two exits are
    joined straight, so a wire is never lost.
    """
    a = _outside(start, start_out[0], start_out[1], clearance)
    b = _outside(end, end_out[0], end_out[1], clearance)
    # Grown by a hair less than the corners stand off, so a run along a grown edge is clear.
    walls = [_grown(rect, clearance - 1e-6) for rect in boards]
    nodes: list[Point] = [a, b]
    for rect in boards:
        left, top, right, bottom = _grown(rect, clearance)
        nodes += [(left, top), (right, top), (right, bottom), (left, bottom)]
    nodes = nodes[:2] + [
        n for n in nodes[2:] if not any(w[0] < n[0] < w[2] and w[1] < n[1] < w[3] for w in walls)
    ]

    def clear(p: Point, q: Point) -> bool:
        return not any(_crosses(p, q, wall) for wall in walls)

    best = {0: 0.0}
    came: dict[int, int] = {}
    queue = [(0.0, 0)]
    while queue:
        cost, i = heapq.heappop(queue)
        if i == 1:
            break
        if cost > best.get(i, math.inf):
            continue
        for j in range(len(nodes)):
            if j == i:
                continue
            step = cost + math.dist(nodes[i], nodes[j])
            if step < best.get(j, math.inf) and clear(nodes[i], nodes[j]):
                best[j] = step
                came[j] = i
                heapq.heappush(queue, (step, j))
    way = [b]
    if 1 in came:
        at = 1
        while at in came:
            at = came[at]
            way.append(nodes[at])
    else:
        way.append(a)
    way.reverse()
    return [start, *way, end]


def offset_route(points: Sequence[Point], distance: float) -> list[Point]:
    """A line beside ``points``, ``distance`` millimetres to its right as the scene shows it
    (left for a negative distance), its corners mitred: one wire of a cable running beside
    another. Lines offset from one route never cross, however it bends -- which a wire given
    its own clearance round each board does, the first time the cable turns the other way."""
    kept = [p for i, p in enumerate(points) if i == 0 or math.dist(p, points[i - 1]) > 1e-9]
    if len(kept) < 2:
        return list(points)
    normals: list[Point] = []
    for (x0, y0), (x1, y1) in itertools.pairwise(kept):
        length = math.hypot(x1 - x0, y1 - y0)
        normals.append(((y0 - y1) / length, (x1 - x0) / length))
    beside: list[Point] = []
    for index, (x, y) in enumerate(kept):
        if index == 0:
            nx, ny = normals[0]
        elif index == len(kept) - 1:
            nx, ny = normals[-1]
        else:
            (ax, ay), (bx, by) = normals[index - 1], normals[index]
            dot = ax * bx + ay * by
            # A mitre is the sum of the two normals, stretched to keep its distance from
            # both runs; a hairpin has no mitre worth drawing, and takes the second run's.
            nx, ny = (bx, by) if dot < -0.9 else ((ax + bx) / (1 + dot), (ay + by) / (1 + dot))
        beside.append((x + nx * distance, y + ny * distance))
    return beside


def rounded_path(points: Sequence[Point], radius: float = CABLE_BEND_MM) -> QPainterPath:
    """``points`` as one line with each corner rounded, as a cable bends."""
    path = QPainterPath(QPointF(*points[0]))
    for u, v, w in zip(points, points[1:], points[2:], strict=False):
        first, second = math.dist(u, v), math.dist(v, w)
        if first < 1e-9 or second < 1e-9:
            continue
        r = min(radius, first / 2, second / 2)
        into = (v[0] - (v[0] - u[0]) * r / first, v[1] - (v[1] - u[1]) * r / first)
        out = (v[0] + (w[0] - v[0]) * r / second, v[1] + (w[1] - v[1]) * r / second)
        path.lineTo(QPointF(*into))
        path.quadTo(QPointF(*v), QPointF(*out))
    path.lineTo(QPointF(*points[-1]))
    return path


def _frame_rect(at: QPointF, rect: QRectF) -> Rect:
    """A board's frame in the scene, title included: what a cable keeps clear of."""
    return (at.x() - 3, at.y() - 9, at.x() + rect.width() + 3, at.y() + rect.height() + 3)


class SystemView(QGraphicsView):
    """The boards in a row and their cables; a click picks one, a double-click on a board
    asks for it."""

    board_opened = Signal(str)
    #: A single click: on a board, on a cable, or on neither.
    board_clicked = Signal(str)
    cable_clicked = Signal(str)
    cleared = Signal()

    def __init__(self, lookup: FootprintLookup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("systemView")
        self._lookup = lookup
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor(theme.ACTIVE.canvas)))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._shown: PerfDocument | None = None
        #: What is picked, as the window last said: ("board" | "cable", id), or None.
        self._selected: tuple[str, str] | None = None
        self._frames: dict[BoardId, QGraphicsRectItem] = {}
        #: Each cable's outlines, with the pen each was drawn with before any pick.
        self._outlines: dict[str, list[tuple[QGraphicsPathItem, QPen]]] = {}

    def set_document(self, doc: PerfDocument, language: str = "en") -> None:
        """Draw ``doc``'s boards and cables, unless it is the document already drawn."""
        if doc is self._shown:
            return
        self._shown = doc
        self._scene.clear()
        self._frames = {}
        self._outlines = {}
        origins: dict[BoardId, tuple[QPointF, PerfDocument, QRectF]] = {}
        row = board_row(doc)
        for board_id in board_ids(doc):
            view = board_document(doc, board_id)
            pixmap, rect = self._draw(view)
            # The scene's own frame is the board's, so the drawing goes where the row puts
            # the board's frame, offset by however far the drawing reaches past hole A1.
            dx, dy = row[board_id]
            at = QPointF(dx + rect.x(), dy + rect.y())
            item = QGraphicsPixmapItem(pixmap)
            item.setScale(1.0 / DRAW_PX_PER_MM)
            item.setPos(at)
            item.setData(_BOARD_ROLE, board_id)
            self._scene.addItem(item)
            self._frame(at, rect, board_title(doc, board_id, language), board_id)
            origins[board_id] = (at, view, rect)
        colours = net_colours(doc)
        net_of = {(node.component_ref, node.pin): net for net in doc.nets for node in net.nodes}
        # A cable wired across is drawn in the danger colour, as the finding about it says.
        crossed = {
            pin.component_ref for finding in crossed_cables(doc) for pin in finding.pins
        }
        for cable in doc.cables:
            self._cable(doc, cable.a, cable.b, cable, origins, colours, net_of, crossed)
        bounds = self._scene.itemsBoundingRect()
        hint = self._text(
            t("Click a board or a cable to see it in Properties; double-click a board to open it."),
            theme.ACTIVE.text_secondary,
        )
        hint.setPos(
            bounds.center().x() - hint.sceneBoundingRect().width() / 2, bounds.bottom() + GAP_MM / 2
        )
        self._scene.addItem(hint)
        self._show_selected()
        self._fit()

    def _text(self, text: str, colour: str, *, bold: bool = False) -> QGraphicsSimpleTextItem:
        """Text 4 pt tall in the scene's millimetres, drawn from a font ten times that and
        scaled down: a 4 pt font is laid out in whole pixels, so its spaces rounded away and
        the hint read "görmekiçin" -- at forty the advances are true, and the scale keeps
        the size."""
        item = QGraphicsSimpleTextItem(text)
        item.setBrush(QBrush(QColor(colour)))
        font = QFont(self.font())
        font.setPointSizeF(4.0 * _TEXT_OVERSIZE)
        font.setBold(bold)
        item.setFont(font)
        item.setScale(1.0 / _TEXT_OVERSIZE)
        return item

    def set_selected(self, kind: str | None, item_id: str | None = None) -> None:
        """Ring the picked board or thicken the picked cable; None picks nothing."""
        self._selected = (kind, item_id) if kind is not None and item_id is not None else None
        self._show_selected()

    @property
    def selected(self) -> tuple[str, str] | None:
        return self._selected

    def _show_selected(self) -> None:
        picked = self._selected
        accent = QColor(theme.ACTIVE.accent)
        for board_id, frame in self._frames.items():
            on = picked == ("board", board_id)
            frame.setPen(QPen(accent, 1.0) if on else QPen(QColor(theme.ACTIVE.border), 0.4))
        for cable_id, outlines in self._outlines.items():
            on = picked == ("cable", cable_id)
            for item, pen in outlines:
                if on:
                    wide = QPen(pen)
                    wide.setWidthF(pen.widthF() + 1.4)
                    if pen.color() != QColor(theme.ACTIVE.danger):
                        # Crossed stays red: the pick must not hide what is wrong with it.
                        wide.setColor(accent)
                    item.setPen(wide)
                else:
                    item.setPen(pen)

    def _draw(self, view: PerfDocument) -> tuple[QPixmap, QRectF]:
        """One board as the Board panel draws it, at :data:`DRAW_PX_PER_MM`."""
        scene = BoardScene(view, self._lookup, side="top")
        rect = scene.sceneRect()
        image = QImage(
            max(1, round(rect.width() * DRAW_PX_PER_MM)),
            max(1, round(rect.height() * DRAW_PX_PER_MM)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scene.render(painter, QRectF(0, 0, image.width(), image.height()), rect)
        painter.end()
        return QPixmap.fromImage(image), rect

    def _frame(self, at: QPointF, rect: QRectF, title: str, board_id: BoardId) -> None:
        left, top, right, bottom = _frame_rect(at, rect)
        frame = QGraphicsRectItem(QRectF(left, top, right - left, bottom - top))
        frame.setPen(QPen(QColor(theme.ACTIVE.border), 0.4))
        frame.setBrush(Qt.BrushStyle.NoBrush)
        frame.setZValue(-1)
        frame.setData(_BOARD_ROLE, board_id)
        self._scene.addItem(frame)
        self._frames[board_id] = frame
        label = self._text(title, theme.ACTIVE.text, bold=True)
        label.setPos(at.x(), at.y() - 8.5)
        label.setData(_BOARD_ROLE, board_id)
        self._scene.addItem(label)

    def _pin_points(
        self, doc: PerfDocument, end: CableEnd, origins: dict[BoardId, tuple[QPointF, PerfDocument, QRectF]]
    ) -> dict[str, QPointF]:
        part = connector_of(doc, end)
        if part is None or end.board not in origins:
            return {}
        footprint = self._lookup(part.footprint_id)
        if footprint is None:
            return {}
        at, view, rect = origins[end.board]
        points: dict[str, QPointF] = {}
        for pin, hole in all_pin_holes(part, footprint):
            p = hole_to_screen(hole, view.board, "top")
            points[pin.number] = QPointF(at.x() + p.x() - rect.x(), at.y() + p.y() - rect.y())
        return points

    def _cable(
        self,
        doc: PerfDocument,
        a_end: CableEnd,
        b_end: CableEnd,
        cable: Cable,
        origins: dict[BoardId, tuple[QPointF, PerfDocument, QRectF]],
        colours: dict[str, str],
        net_of: dict[tuple[str, str], Net],
        crossed: set[str],
    ) -> None:
        a_pins = self._pin_points(doc, a_end, origins)
        b_pins = self._pin_points(doc, b_end, origins)
        a_part = connector_of(doc, a_end)
        b_part = connector_of(doc, b_end)
        wrong = a_part is not None and b_part is not None and {a_part.ref, b_part.ref} <= crossed
        if not a_pins or not b_pins:
            return
        frames = {board_id: _frame_rect(at, rect) for board_id, (at, _view, rect) in origins.items()}
        # A cable leaves by the edge nearest its connector as a whole, and is routed once,
        # down its middle; each wire gathers into it from its own pin on the way out and runs
        # beside the others (``offset_route``) until it leaves the bundle for its pin.
        a_out = (frames[a_end.board], nearest_side(_middle(a_pins), frames[a_end.board]))
        b_out = (frames[b_end.board], nearest_side(_middle(b_pins), frames[b_end.board]))
        drawn = [w for w in cable.wires if w.a_pin in a_pins and w.b_pin in b_pins]
        half = (len(drawn) - 1) / 2 * WIRE_SPACING_MM
        start, end = _middle(a_pins), _middle(b_pins)
        # Clear of the boards by the bundle's half-width too, so its outermost wire is.
        centre = cable_route(
            start, a_out, end, b_out, list(frames.values()), CABLE_CLEARANCE_MM + half
        )
        # The wires take their places in the bundle in the order their pins stand across the
        # way out, so none crosses another leaving the first connector; the other order is
        # taken when that is the one that crosses fewer at the second.
        nx, ny = offset_route(centre[:2], 1.0)[0]
        nx, ny = nx - start[0], ny - start[1]
        across = sorted(
            range(len(drawn)),
            key=lambda i: (a_pins[drawn[i].a_pin].x() - start[0]) * nx
            + (a_pins[drawn[i].a_pin].y() - start[1]) * ny,
        )

        def ways_for(order: list[int]) -> list[list[Point]]:
            place = {wire: rank for rank, wire in enumerate(order)}
            ways: list[list[Point]] = []
            for index, wire in enumerate(drawn):
                beside = offset_route(centre, place[index] * WIRE_SPACING_MM - half)
                p, q = a_pins[wire.a_pin], b_pins[wire.b_pin]
                ways.append([(p.x(), p.y()), *beside[1:-1], (q.x(), q.y())])
            return ways

        ways = min((ways_for(across), ways_for(across[::-1])), key=_crossings)
        for wire, way in zip(drawn, ways, strict=True):
            # The harness's choice (``harness._cable``): its own colour, else its net's
            # -- the net at either end -- else grey.
            net = (net_of.get((a_part.ref, wire.a_pin)) if a_part is not None else None) or (
                net_of.get((b_part.ref, wire.b_pin)) if b_part is not None else None
            )
            colour_id = wire.colour or (colours.get(net.id, "grey") if net is not None else "grey")
            path = rounded_path(way)
            # The wire in the colour the board's own wires take for that name (the 2D
            # view's insulation table), over an outline in the window's background.
            colour = named_insulation(colour_id)
            edge = theme.ACTIVE.danger if wrong else theme.ACTIVE.bg_app
            outline = QPen(QColor(edge), 2.2 if wrong else 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            shadow = self._scene.addPath(path, outline)
            shadow.setZValue(2)
            shadow.setData(_CABLE_ROLE, cable.id)
            self._outlines.setdefault(cable.id, []).append((shadow, QPen(outline)))
            line = self._scene.addPath(path, QPen(colour, 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            line.setZValue(3)
            line.setData(_CABLE_ROLE, cable.id)

    def cable_paths(self, cable_id: str) -> list[QPainterPath]:
        """The lines a cable is drawn as, one per wire, in scene millimetres."""
        return [item.path() for item, _pen in self._outlines.get(cable_id, [])]

    def board_frames(self) -> dict[BoardId, Rect]:
        """Each board's frame in the scene, as a cable keeps clear of it."""
        frames: dict[BoardId, Rect] = {}
        for board_id, item in self._frames.items():
            box = item.rect()
            frames[board_id] = (box.left(), box.top(), box.right(), box.bottom())
        return frames

    def _fit(self) -> None:
        bounds = self._scene.itemsBoundingRect().adjusted(-GAP_MM / 2, -GAP_MM / 2, GAP_MM / 2, GAP_MM / 2)
        self._scene.setSceneRect(bounds)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()

    def picked_at(self, point: QPointF) -> tuple[str, str] | None:
        """What a click at ``point`` (in the view) picks: a cable over a board, since a cable
        is drawn over the boards it joins; ("board" | "cable", id), or None."""
        found: tuple[str, str] | None = None
        # A wire is a hairline at this scale: within a few pixels of the line is on it. Not
        # the item's own shape, which for an open path is also the area it bends round --
        # and that lies over the boards the cable joins.
        at = self.mapToScene(point.toPoint())
        stroker = QPainterPathStroker()
        stroker.setWidth(8.0 / max(self.transform().m11(), 1e-6))
        for cable_id, outlines in self._outlines.items():
            if any(stroker.createStroke(item.path()).contains(at) for item, _pen in outlines):
                return ("cable", cable_id)
        for item in self.items(point.toPoint()):
            board_id = item.data(_BOARD_ROLE)
            if isinstance(board_id, str) and found is None:
                found = ("board", board_id)
        return found

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            picked = self.picked_at(event.position())
            if picked is None:
                self.cleared.emit()
            elif picked[0] == "cable":
                self.cable_clicked.emit(picked[1])
            else:
                self.board_clicked.emit(picked[1])
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        item: QGraphicsItem | None = self.itemAt(event.position().toPoint())
        board_id = item.data(_BOARD_ROLE) if item is not None else None
        if isinstance(board_id, str):
            self.board_opened.emit(board_id)
            return
        super().mouseDoubleClickEvent(event)


def _middle(points: dict[str, QPointF]) -> Point:
    xs = [p.x() for p in points.values()]
    ys = [p.y() for p in points.values()]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _crossings(ways: Sequence[Sequence[Point]]) -> int:
    """How many times the wires of one cable cross one another, counted segment by segment."""
    def side(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def cross(p: Point, q: Point, r: Point, s: Point) -> bool:
        return side(p, q, r) * side(p, q, s) < 0 and side(r, s, p) * side(r, s, q) < 0

    count = 0
    for i, one in enumerate(ways):
        for other in ways[i + 1 :]:
            count += sum(
                cross(p, q, r, s)
                for p, q in itertools.pairwise(one)
                for r, s in itertools.pairwise(other)
            )
    return count
