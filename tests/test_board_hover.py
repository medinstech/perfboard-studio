"""What the board says under the pointer before anything is pressed.

A part under the pointer is outlined and shows the move cursor when it can move; a locked
one promises nothing, and an armed tool's cross shows through. The connect and draw tools
ring the pin they would take, as the sheet's wire tool always has. The ring survives a
rebuild, which every command makes: an item ``clear()`` destroyed and a wrapper kept to it
is how one tool used to take every other down with it.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QGraphicsSceneHoverEvent

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import all_pin_holes
from perfboard_studio.model import HoleCoord, PerfDocument
from perfboard_studio.ui.view2d import BoardScene, ComponentItem, hole_to_screen

DENSE = Path(__file__).resolve().parents[1] / "tools" / "diffcheck" / "golden" / "dense.perf"
LOOKUP = footprint_lookup()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _dense() -> PerfDocument:
    return persist.parse_document_or_throw(DENSE.read_text(encoding="utf-8"))


def _scene(doc: PerfDocument) -> BoardScene:
    _app()
    return BoardScene(doc, LOOKUP, side="top", show_ratsnest=False, show_rulers=False)


def _item(scene: BoardScene, ref: str) -> ComponentItem:
    return next(
        item for item in scene.items() if isinstance(item, ComponentItem) and item.comp.ref == ref
    )


def _hover(item: ComponentItem, kind: QEvent.Type) -> None:
    event = QGraphicsSceneHoverEvent(kind)
    {
        QEvent.Type.GraphicsSceneHoverEnter: item.hoverEnterEvent,
        QEvent.Type.GraphicsSceneHoverMove: item.hoverMoveEvent,
        QEvent.Type.GraphicsSceneHoverLeave: item.hoverLeaveEvent,
    }[kind](event)


def _a_pin_and_an_empty_hole(doc: PerfDocument) -> tuple[HoleCoord, HoleCoord]:
    # Not every part: the fixtures carry one footprint id neither engine has (c-disc-1).
    used = {
        (at.col, at.row)
        for component in doc.components
        if (footprint := LOOKUP(component.footprint_id)) is not None
        for _pin, at in all_pin_holes(component, footprint)
    }
    pin = next(HoleCoord(*hole) for hole in sorted(used))
    empty = next(
        HoleCoord(col, row)
        for row in range(doc.board.rows)
        for col in range(doc.board.cols)
        if (col, row) not in used
    )
    return pin, empty


def test_a_part_under_the_pointer_says_it_can_be_moved() -> None:
    doc = _dense()
    scene = _scene(doc)
    item = _item(scene, doc.components[0].ref)
    assert item.acceptHoverEvents()
    _hover(item, QEvent.Type.GraphicsSceneHoverEnter)
    assert item.hovered
    assert item.hasCursor() and item.cursor().shape() == Qt.CursorShape.SizeAllCursor
    _hover(item, QEvent.Type.GraphicsSceneHoverLeave)
    assert not item.hovered and not item.hasCursor()


def test_a_locked_part_and_an_armed_tool_get_no_move_cursor() -> None:
    doc = _dense()
    first = doc.components[0]
    locked = dataclasses.replace(
        doc, components=(dataclasses.replace(first, locked=True), *doc.components[1:])
    )
    scene = _scene(locked)
    item = _item(scene, first.ref)
    _hover(item, QEvent.Type.GraphicsSceneHoverEnter)
    assert item.hovered and not item.hasCursor()

    scene = _scene(doc)
    item = _item(scene, first.ref)
    _hover(item, QEvent.Type.GraphicsSceneHoverEnter)
    assert item.hasCursor()
    scene.arm_connect(True)
    _hover(item, QEvent.Type.GraphicsSceneHoverMove)
    assert not item.hasCursor(), "the tool's cross shows through"
    scene.arm_connect(False)
    _hover(item, QEvent.Type.GraphicsSceneHoverMove)
    assert item.hasCursor()


def test_the_connect_and_draw_tools_ring_the_pin_under_the_pointer() -> None:
    doc = _dense()
    scene = _scene(doc)
    pin, empty = _a_pin_and_an_empty_hole(doc)

    scene.hover_at(hole_to_screen(pin, doc.board, "top"))
    assert scene.pin_hover_hole() is None, "no tool, no ring"

    scene.arm_connect(True)
    scene.hover_at(hole_to_screen(pin, doc.board, "top"))
    assert scene.pin_hover_hole() == pin
    scene.hover_at(hole_to_screen(empty, doc.board, "top"))
    assert scene.pin_hover_hole() is None
    scene.hover_at(hole_to_screen(pin, doc.board, "top"))
    scene.arm_connect(False)
    assert scene.pin_hover_hole() is None, "put the tool down and the ring goes"

    scene.arm_drawing("solder-trace")
    scene.hover_at(hole_to_screen(pin, doc.board, "top"))
    assert scene.pin_hover_hole() == pin
    scene.hover_left()
    assert scene.pin_hover_hole() is None


def test_the_ring_survives_a_rebuild() -> None:
    """Every command rebuilds the scene. The ring is destroyed with the rest and made again
    on the next hover, so a tool still armed across the rebuild keeps working -- and putting
    it down afterwards raises nothing."""
    doc = _dense()
    scene = _scene(doc)
    pin, _empty = _a_pin_and_an_empty_hole(doc)
    scene.arm_connect(True)
    scene.hover_at(hole_to_screen(pin, doc.board, "top"))
    assert scene.pin_hover_hole() == pin
    scene.set_document(dataclasses.replace(doc))
    assert scene.pin_hover_hole() is None
    scene.hover_at(hole_to_screen(pin, doc.board, "top"))
    assert scene.pin_hover_hole() == pin
    scene.leave_mode()
    assert scene.pin_hover_hole() is None
