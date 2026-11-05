"""The System view: every board of the document, drawn as the Board panel draws it, and the
cables between them.

Behind the board strip's first entry (``ui.boardstrip``). Each board is the 2D scene's own
drawing of that board alone (``system.board_document``), so a board looks here exactly as it
does when opened; the cables are drawn over them, one curve per wire in the wire's colour --
the colour the harness cuts it in -- from its pin on one connector to its pin on the other.
Double-click a board to open it. The boards sit in a row in the order the document holds
them; where a person may move them is a later decision, and nothing here is saved.
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
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QWidget,
)

from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.geometry import all_pin_holes
from perfboard_studio.guide import net_colours
from perfboard_studio.model import BoardId, Cable, CableEnd, Net, PerfDocument
from perfboard_studio.system import board_document, board_ids, board_title, connector_of

from . import theme
from .i18n import t
from .view2d import BoardScene, hole_to_screen

#: Pixels per millimetre a board is drawn at before it is scaled into the view: enough that
#: a part's label still reads when the System view is the whole panel.
DRAW_PX_PER_MM = 6.0

#: Millimetres between two boards, and round the row.
GAP_MM = 25.0

#: What a wire with no colour of its own and no net is drawn in.
_WIRE_COLOURS = {
    "red": "#d4373a", "black": "#2b2d31", "blue": "#2f6fd6", "green": "#2f9e44",
    "yellow": "#e3b505", "orange": "#e8730c", "white": "#f0f0f0", "grey": "#8a8f98",
    "brown": "#8b5a2b", "purple": "#8e44ad",
}

_BOARD_ROLE = 0  # QGraphicsItem.data key holding a board's id


class SystemView(QGraphicsView):
    """The boards in a row and their cables; double-clicking a board asks for it."""

    board_opened = Signal(str)

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

    def set_document(self, doc: PerfDocument, language: str = "en") -> None:
        """Draw ``doc``'s boards and cables, unless it is the document already drawn."""
        if doc is self._shown:
            return
        self._shown = doc
        self._scene.clear()
        origins: dict[BoardId, tuple[QPointF, PerfDocument, QRectF]] = {}
        x = 0.0
        for board_id in board_ids(doc):
            view = board_document(doc, board_id)
            pixmap, rect = self._draw(view)
            at = QPointF(x, 0.0)
            item = QGraphicsPixmapItem(pixmap)
            item.setScale(1.0 / DRAW_PX_PER_MM)
            item.setPos(at)
            item.setData(_BOARD_ROLE, board_id)
            self._scene.addItem(item)
            self._frame(at, rect, board_title(doc, board_id, language), board_id)
            origins[board_id] = (at, view, rect)
            x += rect.width() + GAP_MM
        colours = net_colours(doc)
        net_of = {(node.component_ref, node.pin): net for net in doc.nets for node in net.nodes}
        for cable in doc.cables:
            self._cable(doc, cable.a, cable.b, cable, origins, colours, net_of)
        bounds = self._scene.itemsBoundingRect()
        hint = QGraphicsSimpleTextItem(t("Double-click a board to open it."))
        hint.setBrush(QBrush(QColor(theme.ACTIVE.text_secondary)))
        font = QFont(self.font())
        font.setPointSizeF(4.0)
        hint.setFont(font)
        hint.setPos(bounds.center().x() - hint.boundingRect().width() / 2, bounds.bottom() + GAP_MM / 2)
        self._scene.addItem(hint)
        self._fit()

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
        label = QGraphicsSimpleTextItem(title)
        label.setBrush(QBrush(QColor(theme.ACTIVE.text)))
        font = QFont(self.font())
        font.setPointSizeF(4.0)
        font.setBold(True)
        label.setFont(font)
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
    ) -> None:
        a_pins = self._pin_points(doc, a_end, origins)
        b_pins = self._pin_points(doc, b_end, origins)
        a_part = connector_of(doc, a_end)
        for wire in cable.wires:
            p, q = a_pins.get(wire.a_pin), b_pins.get(wire.b_pin)
            if p is None or q is None:
                continue
            net = net_of.get((a_part.ref, wire.a_pin)) if a_part is not None else None
            colour_id = wire.colour or (colours.get(net.id, "grey") if net is not None else "grey")
            sag = max(p.y(), q.y()) + 18
            path = QPainterPath(p)
            mid = (p.x() + q.x()) / 2
            path.cubicTo(QPointF(mid, sag), QPointF(mid, sag), q)
            shadow = self._scene.addPath(path, QPen(QColor("#0b0c0f"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            shadow.setZValue(2)
            line = self._scene.addPath(path, QPen(QColor(_WIRE_COLOURS.get(colour_id, "#8a8f98")), 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            line.setZValue(3)

    def _fit(self) -> None:
        bounds = self._scene.itemsBoundingRect().adjusted(-GAP_MM / 2, -GAP_MM / 2, GAP_MM / 2, GAP_MM / 2)
        self._scene.setSceneRect(bounds)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        item: QGraphicsItem | None = self.itemAt(event.position().toPoint())
        board_id = item.data(_BOARD_ROLE) if item is not None else None
        if isinstance(board_id, str):
            self.board_opened.emit(board_id)
            return
        super().mouseDoubleClickEvent(event)
