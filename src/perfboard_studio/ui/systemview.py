"""The System view: every board of the document, drawn as the Board panel draws it, and the
cables between them.

Behind the board strip's first entry (``ui.boardstrip``). Each board is the 2D scene's own
drawing of that board alone (``system.board_document``), so a board looks here exactly as it
does when opened; the cables are drawn over them, one curve per wire in the wire's colour --
the colour the harness cuts it in -- from its pin on one connector to its pin on the other.
Click a board or a cable to pick it -- Properties shows it (``inspector._SystemBoardEditor``,
``_CableEditor``), and a click on the bare bench shows the system itself -- and double-click a
board to open it. The pick is the window's, handed back by ``set_selected``, so it outlives a
redraw. The boards sit in ``system.board_row``'s row, the one the 3D panel lays them out by
too; where a person may move them is a later decision, and nothing here is saved.
"""

from __future__ import annotations

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
        frame = QGraphicsRectItem(QRectF(at.x() - 3, at.y() - 9, rect.width() + 6, rect.height() + 12))
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
        for wire in cable.wires:
            p, q = a_pins.get(wire.a_pin), b_pins.get(wire.b_pin)
            if p is None or q is None:
                continue
            # The harness's choice (``harness._cable``): its own colour, else its net's
            # -- the net at either end -- else grey.
            net = (net_of.get((a_part.ref, wire.a_pin)) if a_part is not None else None) or (
                net_of.get((b_part.ref, wire.b_pin)) if b_part is not None else None
            )
            colour_id = wire.colour or (colours.get(net.id, "grey") if net is not None else "grey")
            sag = max(p.y(), q.y()) + 18
            path = QPainterPath(p)
            mid = (p.x() + q.x()) / 2
            path.cubicTo(QPointF(mid, sag), QPointF(mid, sag), q)
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
        # A wire is a hairline at this scale: within a few pixels of the curve is on it. Not
        # the item's own shape, which for an open curve is also the area under its sag --
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
