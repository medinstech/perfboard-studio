"""What the pointer and the wheel mean on the two canvases, the board and the sheet.

Pinned here, against real Qt events sent to each view's viewport:

- a mouse wheel turning whole notches zooms, as it always did; anything finer -- a
  trackpad's two fingers -- pans, and Ctrl (a pinch, on Windows) zooms again;
- Space held turns the left button into the hand, on both canvases, so a laptop with no
  middle button can pan, and letting it go gives the left button back to selecting;
- the board and the sheet read a wheel event through one function
  (``canvasinput.wheel_intent``), so they cannot disagree about it.
"""

from __future__ import annotations

import os
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsItem, QWidget

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.schematic import build_schematic
from perfboard_studio.ui.canvasinput import NOTCH, WheelIntent, wheel_intent
from perfboard_studio.ui.view2d import BoardScene, BoardView, hole_to_screen
from perfboard_studio.ui.viewsch import SchematicView

GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "tools" / "diffcheck" / "golden" / "dense.perf"
LEFT = Qt.MouseButton.LeftButton
NONE = Qt.MouseButton.NoButton
NO_KEYS = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


@pytest.fixture(scope="module", autouse=True)
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication(["perfboard-studio-tests"])
    return app  # type: ignore[return-value]


def _wheel(
    angle: tuple[int, int] = (0, 0),
    pixels: tuple[int, int] = (0, 0),
    modifiers: Qt.KeyboardModifier = NO_KEYS,
    at: QPoint | None = None,
    phase: Qt.ScrollPhase = Qt.ScrollPhase.NoScrollPhase,
) -> QWheelEvent:
    point = QPointF(at if at is not None else QPoint(200, 150))
    return QWheelEvent(
        point, point, QPoint(*pixels), QPoint(*angle), NONE, modifiers, phase, False
    )


def _mouse(
    widget: QWidget,
    kind: QEvent.Type,
    at: QPoint,
    buttons: Qt.MouseButton,
    modifiers: Qt.KeyboardModifier = NO_KEYS,
) -> None:
    button = NONE if kind == QEvent.Type.MouseMove else LEFT
    QApplication.sendEvent(
        widget, QMouseEvent(kind, QPointF(at), QPointF(widget.mapToGlobal(at)), button, buttons, modifiers)
    )


def _drag(
    widget: QWidget, start: QPoint, end: QPoint, modifiers: Qt.KeyboardModifier = NO_KEYS
) -> None:
    _mouse(widget, QEvent.Type.MouseButtonPress, start, LEFT, modifiers)
    for step in range(1, 6):
        _mouse(widget, QEvent.Type.MouseMove, start + (end - start) * step / 5, LEFT, modifiers)
    _mouse(widget, QEvent.Type.MouseButtonRelease, end, NONE, modifiers)


def _click(widget: QWidget, at: QPoint, modifiers: Qt.KeyboardModifier = NO_KEYS) -> None:
    _mouse(widget, QEvent.Type.MouseButtonPress, at, LEFT, modifiers)
    _mouse(widget, QEvent.Type.MouseButtonRelease, at, NONE, modifiers)


def _key(widget: QWidget, kind: QEvent.Type, key: Qt.Key) -> None:
    QApplication.sendEvent(widget, QKeyEvent(kind, key, NO_KEYS))


# -- the rule ------------------------------------------------------------------------------


def test_a_mouse_wheel_notch_zooms() -> None:
    assert wheel_intent(_wheel(angle=(0, NOTCH))) == WheelIntent(zoom_steps=1.0)
    assert wheel_intent(_wheel(angle=(0, -2 * NOTCH))) == WheelIntent(zoom_steps=-2.0)


def test_two_fingers_pan_whichever_way_the_platform_reports_them() -> None:
    """Pixel deltas (macOS, Wayland), a fraction of a notch (a Windows precision
    touchpad), a sideways component, or a scroll phase: each is a trackpad, and pans."""
    assert wheel_intent(_wheel(angle=(0, -30), pixels=(0, -12))) == WheelIntent(pan_y=-12.0)
    fraction = wheel_intent(_wheel(angle=(0, 48)))
    assert fraction.zoom_steps == 0 and fraction.pan_y > 0
    sideways = wheel_intent(_wheel(angle=(NOTCH, 0)))
    assert sideways.zoom_steps == 0 and sideways.pan_x > 0 and sideways.pan_y == 0
    phased = wheel_intent(_wheel(angle=(0, NOTCH), phase=Qt.ScrollPhase.ScrollUpdate))
    assert phased.zoom_steps == 0 and phased.pan_y > 0


def test_ctrl_zooms_from_anything_and_a_pinch_by_what_it_amounts_to() -> None:
    """Windows sends a trackpad pinch as Ctrl+wheel in small steps: each is a fraction of
    a notch's zoom, so a pinch adds up instead of racing."""
    assert wheel_intent(_wheel(angle=(0, NOTCH), modifiers=CTRL)) == WheelIntent(zoom_steps=1.0)
    assert wheel_intent(_wheel(angle=(0, 30), modifiers=CTRL)) == WheelIntent(zoom_steps=0.25)
    assert wheel_intent(_wheel(angle=(0, -12), pixels=(0, -5), modifiers=CTRL)).zoom_steps < 0


def test_shift_turns_the_wheel_sideways() -> None:
    intent = wheel_intent(_wheel(angle=(0, NOTCH), modifiers=SHIFT))
    assert intent.zoom_steps == 0 and intent.pan_y == 0 and intent.pan_x > 0


# -- the board -----------------------------------------------------------------------------


def _board_view() -> BoardView:
    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    view = BoardView(BoardScene(document, footprint_lookup(), side="top"))
    view.resize(500, 400)
    view.show()
    # Zoomed in, so there is somewhere to pan to.
    view.resetTransform()
    view.scale(20, 20)
    view.centerOn(view.sceneRect().center())
    QApplication.processEvents()
    return view


def _scroll(view: BoardView | SchematicView) -> tuple[int, int]:
    return view.horizontalScrollBar().value(), view.verticalScrollBar().value()


def test_two_fingers_pan_the_board_and_leave_its_zoom_alone() -> None:
    view = _board_view()
    try:
        scale, scroll = view.current_scale(), _scroll(view)
        QApplication.sendEvent(view.viewport(), _wheel(angle=(0, -40), pixels=(0, -40)))
        assert view.current_scale() == pytest.approx(scale)
        assert _scroll(view)[1] == scroll[1] + 40

        QApplication.sendEvent(view.viewport(), _wheel(angle=(0, NOTCH)))
        assert view.current_scale() == pytest.approx(scale * 1.15)
    finally:
        view.close()


def test_space_turns_the_left_button_into_the_hand_on_the_board() -> None:
    """And only while it is held: let go, and the same drag is a rubber band again."""
    view = _board_view()
    try:
        port = view.viewport()
        view.setFocus()
        before = _scroll(view)
        _key(view, QEvent.Type.KeyPress, Qt.Key.Key_Space)
        assert port.cursor().shape() == Qt.CursorShape.OpenHandCursor
        _drag(port, QPoint(300, 250), QPoint(200, 150))
        assert _scroll(view) == (before[0] + 100, before[1] + 100)
        assert not view.board_scene.selectedItems()
        _key(view, QEvent.Type.KeyRelease, Qt.Key.Key_Space)
        assert port.cursor().shape() == Qt.CursorShape.ArrowCursor

        panned = _scroll(view)
        _drag(port, QPoint(20, 20), QPoint(480, 380))
        assert _scroll(view) == panned
        assert view.board_scene.selectedItems()
    finally:
        view.close()


def test_a_pan_gives_an_armed_tool_its_cross_back() -> None:
    """A pan used to unset the cursor outright, so a part being placed lost its cross the
    first time the board was panned under it."""
    view = _board_view()
    try:
        view.board_scene.arm_measure(True)
        port = view.viewport()
        port.setCursor(Qt.CursorShape.CrossCursor)
        view.setFocus()
        _key(view, QEvent.Type.KeyPress, Qt.Key.Key_Space)
        _drag(port, QPoint(300, 250), QPoint(250, 200))
        _key(view, QEvent.Type.KeyRelease, Qt.Key.Key_Space)
        assert port.cursor().shape() == Qt.CursorShape.CrossCursor
        # The press that panned was not a measurement.
        assert view.board_scene.measure_from() is None
    finally:
        view.close()


def test_a_space_released_elsewhere_does_not_leave_the_board_panning() -> None:
    view = _board_view()
    try:
        view.setFocus()
        _key(view, QEvent.Type.KeyPress, Qt.Key.Key_Space)
        QApplication.sendEvent(view, QEvent(QEvent.Type.FocusOut))
        before = _scroll(view)
        _drag(view.viewport(), QPoint(20, 20), QPoint(480, 380))
        assert _scroll(view) == before
    finally:
        view.close()


# -- the sheet -----------------------------------------------------------------------------


def _sheet_view() -> SchematicView:
    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    view = SchematicView()
    view.resize(500, 400)
    view.show()
    view.set_drawing(build_schematic(document, footprint_lookup()))
    view.resetTransform()
    view.scale(12, 12)
    view._hand_over_framing()
    view.centerOn(view.sceneRect().center())
    QApplication.processEvents()
    return view


def test_two_fingers_pan_the_sheet_and_leave_its_zoom_alone() -> None:
    view = _sheet_view()
    try:
        scale, scroll = view.current_scale(), _scroll(view)
        QApplication.sendEvent(view.viewport(), _wheel(angle=(-36, 0), pixels=(-30, 0)))
        assert view.current_scale() == pytest.approx(scale)
        assert _scroll(view)[0] == scroll[0] + 30

        QApplication.sendEvent(view.viewport(), _wheel(angle=(0, NOTCH)))
        assert view.current_scale() == pytest.approx(scale * 1.18)
    finally:
        view.close()


def test_space_turns_the_left_button_into_the_hand_on_the_sheet() -> None:
    view = _sheet_view()
    try:
        view.setFocus()
        before = _scroll(view)
        _key(view, QEvent.Type.KeyPress, Qt.Key.Key_Space)
        assert view.cursor().shape() == Qt.CursorShape.OpenHandCursor
        _drag(view.viewport(), QPoint(300, 250), QPoint(220, 190))
        assert _scroll(view) == (before[0] + 80, before[1] + 60)
        assert view.selected_refs == []
        _key(view, QEvent.Type.KeyRelease, Qt.Key.Key_Space)
        assert view.cursor().shape() == Qt.CursorShape.ArrowCursor
    finally:
        view.close()


# -- Escape in the middle of a drag ---------------------------------------------------------


def _escape(view: QWidget) -> bool:
    """Escape as the window delivers it: the shortcut-override question first -- a WINDOW
    shortcut owns Escape, so a view that does not take it back never sees the key -- then
    the key itself. Returns whether the view took it back."""
    override = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Escape, NO_KEYS)
    QApplication.sendEvent(view, override)
    QApplication.sendEvent(view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, NO_KEYS))
    return override.isAccepted()


def test_escape_puts_a_dragged_part_back_and_moves_nothing() -> None:
    from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
    from perfboard_studio.commands import create_standard_registry

    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    bus = CommandBus(document, create_standard_registry(), CommandContext(next_id=create_id_generator()))
    scene = BoardScene(document, footprint_lookup(), side="top", bus=bus)
    view = BoardView(scene)
    view.resize(800, 600)
    view.show()
    view.fit_board()
    QApplication.processEvents()
    try:
        port = view.viewport()
        def first_to_take_a_click(point: QPointF) -> object:
            # Qt offers a press to each item under it, top first, until one takes it, and
            # only a selectable item does.
            selectable = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            return next((under for under in scene.items(point) if under.flags() & selectable), None)

        # A two-pin part with nothing selectable over its middle, so the press lands on it.
        item = next(
            i
            for i in scene.component_items.values()
            if len(i.fp.pins) == 2 and first_to_take_a_click(i.sceneBoundingRect().center()) is i
        )
        comp_id, anchor = item.comp.id, item.comp.anchor
        start = view.mapFromScene(item.sceneBoundingRect().center())
        step = round(3 * document.board.pitch * view.current_scale())
        view.setFocus()
        _mouse(port, QEvent.Type.MouseButtonPress, start, LEFT)
        for i in range(1, 6):
            _mouse(port, QEvent.Type.MouseMove, start + QPoint(step * i // 5, 0), LEFT)
        assert scene.component_items[comp_id].pending_anchor != anchor

        assert _escape(view)
        assert scene.component_items[comp_id].pos() == hole_to_screen(anchor, document.board, "top")

        # The rest of the gesture is inert: more movement, then the release.
        _mouse(port, QEvent.Type.MouseMove, start + QPoint(2 * step, step), LEFT)
        _mouse(port, QEvent.Type.MouseButtonRelease, start + QPoint(2 * step, step), NONE)
        assert not bus.history()
        assert scene.component_items[comp_id].pending_anchor == anchor
    finally:
        view.close()


def test_escape_is_left_to_the_window_when_nothing_is_being_dragged() -> None:
    """Taken back only mid-drag: otherwise Escape is the window's, which is what leaves a
    tool from anywhere (``MainWindow.on_stop_tool``)."""
    view = _board_view()
    try:
        assert not _escape(view)
    finally:
        view.close()


def test_escape_puts_dragged_symbols_back_and_keeps_them_selected() -> None:
    """The sheet's own Escape cleared the drag -- but in the window it never arrived,
    because the window's Escape shortcut took the key first."""
    view = _sheet_view()
    try:
        moved: list[object] = []
        view.symbolsMoved.connect(moved.append)
        port = view.viewport()
        symbol = view.item.drawing.symbols[0]
        centre = QPointF(symbol.at.x + symbol.width / 2, symbol.at.y + symbol.height / 2)
        view.centerOn(centre)
        start = view.mapFromScene(centre)
        view.setFocus()
        _mouse(port, QEvent.Type.MouseButtonPress, start, LEFT)
        for i in range(1, 6):
            _mouse(port, QEvent.Type.MouseMove, start + QPoint(12 * i, 6 * i), LEFT)
        assert view.item.drag_offset is not None

        assert _escape(view)
        assert view.item.drag_offset is None
        assert view.selected_refs == [symbol.ref]

        _mouse(port, QEvent.Type.MouseMove, start + QPoint(90, 40), LEFT)
        _mouse(port, QEvent.Type.MouseButtonRelease, start + QPoint(90, 40), NONE)
        assert moved == []
    finally:
        view.close()


# -- one selection grammar ----------------------------------------------------------------


def _clickable_parts(view: BoardView, count: int) -> list[tuple[str, QPoint]]:
    """Parts whose middle a click lands on (nothing selectable drawn over it), and where."""
    scene = view.board_scene
    selectable = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
    found = []
    for comp_id, item in scene.component_items.items():
        centre = item.sceneBoundingRect().center()
        top = next((under for under in scene.items(centre) if under.flags() & selectable), None)
        at = view.mapFromScene(centre)
        if top is item and view.viewport().rect().contains(at):
            found.append((comp_id, at))
        if len(found) == count:
            break
    assert len(found) == count
    return found


@pytest.mark.parametrize("modifier", [SHIFT, CTRL], ids=["shift", "ctrl"])
def test_shift_or_ctrl_adds_a_part_to_the_selection_and_takes_it_back_out(
    modifier: Qt.KeyboardModifier,
) -> None:
    """Shift used to REPLACE the board's selection (Qt reads only Ctrl), while on the
    sheet Shift was the one that added: the same gesture did opposite things."""
    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    view = BoardView(BoardScene(document, footprint_lookup(), side="top"))
    view.resize(800, 600)
    view.show()
    view.fit_board()
    QApplication.processEvents()
    try:
        port, scene = view.viewport(), view.board_scene
        (first, at_first), (second, at_second) = _clickable_parts(view, 2)
        _click(port, at_first)
        _click(port, at_second, modifier)
        assert set(scene.selected_component_ids()) == {first, second}
        _click(port, at_second, modifier)
        assert scene.selected_component_ids() == (first,)
    finally:
        view.close()


def test_a_rubber_band_pulled_with_shift_adds_to_the_board_selection() -> None:
    view = _board_view()
    try:
        port, scene = view.viewport(), view.board_scene
        view.fit_board()
        QApplication.processEvents()
        (first, at_first), = _clickable_parts(view, 1)
        _click(port, at_first)
        _drag(port, QPoint(2, 2), QPoint(port.width() - 2, port.height() // 3), SHIFT)
        selected = set(scene.selected_component_ids())
        assert first in selected and len(selected) > 1
    finally:
        view.close()


def _symbol_point(view: SchematicView, ref: str) -> QPoint:
    symbol = next(s for s in view.item.drawing.symbols if s.ref == ref)
    return view.mapFromScene(QPointF(symbol.at.x + symbol.width / 2, symbol.at.y + symbol.height / 2))


@pytest.mark.parametrize("modifier", [SHIFT, CTRL], ids=["shift", "ctrl"])
def test_shift_or_ctrl_adds_a_symbol_and_takes_it_back_out(modifier: Qt.KeyboardModifier) -> None:
    """Shift added and never removed on the sheet, and Ctrl did nothing at all."""
    view = _sheet_view()
    try:
        view.fit()
        QApplication.processEvents()
        port = view.viewport()
        first, second = (s.ref for s in view.item.drawing.symbols[:2])
        _click(port, _symbol_point(view, first))
        _click(port, _symbol_point(view, second), modifier)
        assert view.selected_refs == [first, second]
        _click(port, _symbol_point(view, second), modifier)
        assert view.selected_refs == [first]
    finally:
        view.close()


def test_a_rubber_band_pulled_with_shift_adds_to_the_sheet_selection() -> None:
    view = _sheet_view()
    try:
        view.fit()
        QApplication.processEvents()
        port = view.viewport()
        symbols = view.item.drawing.symbols
        # The symbol furthest down is kept selected; the band takes the top of the sheet.
        lowest = max(symbols, key=lambda s: s.at.y)
        _click(port, _symbol_point(view, lowest.ref))
        top = view.mapFromScene(QPointF(0, 0))
        band_end = view.mapFromScene(QPointF(view.item.drawing.width, lowest.at.y - 1))
        _drag(port, top + QPoint(1, 1), band_end, SHIFT)
        assert lowest.ref in view.selected_refs and len(view.selected_refs) > 1
    finally:
        view.close()


def test_select_all_takes_every_part_or_every_symbol_by_where_the_keyboard_is() -> None:
    from perfboard_studio.ui.main import MainWindow

    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    window = MainWindow(document)
    try:
        # Where the keyboard is, without depending on which top-level window an offscreen
        # run made active: the routing is what is pinned, not Qt's focus.
        window.schematic_view.hasFocus = lambda: True  # type: ignore[method-assign]
        asked: list[str] = []
        window.schematic_view.select_all = lambda: asked.append("sheet")  # type: ignore[method-assign]
        window.act_select_all.trigger()
        assert asked == ["sheet"]
        assert not window.scene.selected_component_ids()

        # Every part the board draws: the fixture's one part on a footprint neither engine
        # has (``c-disc-1``) is not on the board to be selected.
        drawn = set(window.scene.component_items)
        window.schematic_view.hasFocus = lambda: False  # type: ignore[method-assign]
        window.act_select_all.trigger()
        assert set(window.scene.selected_component_ids()) == drawn
        assert len(drawn) == len(document.components) - 1
    finally:
        window._mark_saved()
        window.close()


def test_select_all_on_the_sheet_takes_every_symbol() -> None:
    view = _sheet_view()
    try:
        seen: list[object] = []
        view.selectionChanged.connect(seen.append)
        view.select_all()
        assert view.selected_refs == [s.ref for s in view.item.drawing.symbols]
        assert seen == [view.selected_refs]
    finally:
        view.close()


def test_ctrl_a_in_a_text_field_stays_the_text_fields() -> None:
    """Select All is a window shortcut; a line edit takes Ctrl+A back for its own text."""
    from PySide6.QtWidgets import QLineEdit

    field = QLineEdit("10k")
    override = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_A, CTRL)
    QApplication.sendEvent(field, override)
    assert override.isAccepted()
