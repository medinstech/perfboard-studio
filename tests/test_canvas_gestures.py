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
from perfboard_studio.model import HoleCoord
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


def test_a_trackpad_is_known_only_by_what_only_a_trackpad_sends() -> None:
    """Pixel deltas (macOS, Wayland) or a scroll phase pan. Nothing else counts: on Windows
    Qt hands a touchpad's scrolling on exactly as a mouse wheel's (``canvasinput``)."""
    assert wheel_intent(_wheel(angle=(0, -30), pixels=(0, -12))) == WheelIntent(pan_y=-12.0)
    phased = wheel_intent(_wheel(angle=(0, NOTCH), phase=Qt.ScrollPhase.ScrollUpdate))
    assert phased.zoom_steps == 0 and phased.pan_y > 0


def test_a_smooth_wheel_zooms_by_the_fraction_it_turned() -> None:
    """A Logitech MX-style smooth or free-spin wheel sends fractions of a notch. The first
    rule read those as a trackpad and panned, so one mouse zoomed and another did not."""
    assert wheel_intent(_wheel(angle=(0, 30))) == WheelIntent(zoom_steps=0.25)
    assert wheel_intent(_wheel(angle=(0, -48))) == WheelIntent(zoom_steps=-0.4)


def test_a_wheel_tilted_sideways_pans_sideways() -> None:
    sideways = wheel_intent(_wheel(angle=(NOTCH, 0)))
    assert sideways.zoom_steps == 0 and sideways.pan_x > 0 and sideways.pan_y == 0


def test_a_wheel_told_to_scroll_pans_and_ctrl_still_zooms() -> None:
    """View > Mouse Wheel > Scrolls: the way out for anyone the detection gets wrong."""
    scrolled = wheel_intent(_wheel(angle=(0, -NOTCH)), wheel_scrolls=True)
    assert scrolled.zoom_steps == 0 and scrolled.pan_y < 0
    zoomed = wheel_intent(_wheel(angle=(0, NOTCH), modifiers=CTRL), wheel_scrolls=True)
    assert zoomed == WheelIntent(zoom_steps=1.0)


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


# -- undo says what it undid ----------------------------------------------------------------


def _window_with_a_placed_part(language: str = "en"):  # type: ignore[no-untyped-def]
    from perfboard_studio.commands import PlaceComponentPayload
    from perfboard_studio.model import HoleCoord
    from perfboard_studio.ui.i18n import set_language
    from perfboard_studio.ui.main import MainWindow

    set_language(language)
    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    window = MainWindow(document)
    result = window.bus.dispatch(
        "component.place",
        PlaceComponentPayload(ref="R99", value="", footprint_id="r-axial-3", anchor=HoleCoord(1, 1)),
    )
    assert result.ok
    return window


def test_undo_and_redo_say_what_they_took_back_and_put_back() -> None:
    """The bar went on showing whatever the last command had said: "Deleted 3 part(s)"
    over a board that already had one of them back."""
    window = _window_with_a_placed_part()
    try:
        placed = window.bus.history()[-1]
        window.statusBar().showMessage("Deleted 3 part(s)")
        window.act_undo.trigger()
        assert window.statusBar().currentMessage() == f"Undone: {placed}"
        window.act_redo.trigger()
        assert window.statusBar().currentMessage() == f"Redone: {placed}"
    finally:
        window._mark_saved()
        window.close()


def test_undo_says_it_in_the_windows_language() -> None:
    from perfboard_studio.ui.i18n import set_language

    window = _window_with_a_placed_part("tr")
    try:
        window.act_undo.trigger()
        said = window.statusBar().currentMessage()
        assert said.startswith("Geri alındı: ")
        assert "Place" not in said  # The command's own label is said in Turkish too.
    finally:
        set_language("en")
        window._mark_saved()
        window.close()


def test_undo_with_nothing_behind_it_leaves_the_bar_alone() -> None:
    from perfboard_studio.ui.main import MainWindow

    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    window = MainWindow(document)
    try:
        window.statusBar().showMessage("routing summary")
        window.on_undo()
        window.on_redo()
        assert window.statusBar().currentMessage() == "routing summary"
    finally:
        window._mark_saved()
        window.close()


# -- turning a part before it is put down -------------------------------------------------------


def _window_placing(footprint_id: str = "r-axial-3"):  # type: ignore[no-untyped-def]
    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta
    from perfboard_studio.ui.main import MainWindow

    stamp = "2026-01-01T00:00:00.000Z"
    window = MainWindow(create_starter_document(DocumentMeta(name="t", created=stamp, modified=stamp)))
    window.scene.arm_placement(footprint_id)
    return window


def test_r_turns_the_part_about_to_be_placed_and_it_goes_down_turned() -> None:
    """R turned the SELECTION while a part was armed, and the ghost stayed upright."""
    from perfboard_studio.geometry import transform_pin_offset
    from perfboard_studio.model import HoleCoord

    window = _window_placing()
    try:
        window.act_rotate_cw.trigger()
        assert window.scene.armed_orientation == (90, False)
        assert window.scene._ghost is not None and window.scene._ghost.part_rotation == 90

        result = window.scene.place_armed(HoleCoord(4, 4))
        assert result is not None and result.ok
        placed = window.bus.document.components[-1]
        assert (placed.rotation, placed.mirrored) == (90, False)
        footprint = window.lookup("r-axial-3")
        far = footprint.pins[-1]
        d_col, d_row = transform_pin_offset(far.d_col, far.d_row, 90, False)
        assert d_col == 0 and d_row != 0  # Its leads now run down the board, not across it.

        # The next one of the same part goes down the same way round...
        assert window.scene.armed_orientation == (90, False)
        # ...and another part starts upright.
        window.scene.arm_placement("led-5mm")
        assert window.scene.armed_orientation == (0, False)
    finally:
        window._mark_saved()
        window.close()


def test_the_ghost_is_judged_turned() -> None:
    """Red where the turned part does not fit, which is not where the upright one doesn't."""
    from perfboard_studio.geometry import transform_pin_offset
    from perfboard_studio.model import HoleCoord

    window = _window_placing()
    try:
        board = window.bus.document.board
        far = window.lookup("r-axial-3").pins[-1]
        d_col, d_row = transform_pin_offset(far.d_col, far.d_row, 90, False)
        # On the last column, with room for the turned leads above or below.
        anchor = HoleCoord(board.cols - 1, board.rows // 2 - d_row // 2)
        assert window.scene._placement_blocked(anchor)  # Upright, its leads run off the edge.
        window.act_rotate_cw.trigger()
        assert d_col == 0
        assert not window.scene._placement_blocked(anchor)
    finally:
        window._mark_saved()
        window.close()


def test_m_flips_the_part_about_to_be_placed_and_r_leaves_the_selection_alone() -> None:
    from perfboard_studio.model import HoleCoord

    window = _window_placing()
    try:
        window.scene.place_armed(HoleCoord(4, 4))
        first = window.bus.document.components[-1]
        window.scene.select_components([first.id])
        window.act_mirror.trigger()
        assert window.scene.armed_orientation == (0, True)
        window.act_rotate_cw.trigger()
        # Still armed, so R was about the part under the pointer, not the selected one.
        assert next(c for c in window.bus.document.components if c.id == first.id).rotation == 0
    finally:
        window._mark_saved()
        window.close()


# -- the wheel choice in the window ------------------------------------------------------------


def test_the_mouse_wheel_choice_reaches_both_canvases_and_outlives_the_window(
    _settings_in_a_temp_file,  # type: ignore[no-untyped-def]
) -> None:
    from perfboard_studio.ui.main import WHEEL_SCROLLS_KEY, MainWindow

    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    window = MainWindow(document)
    try:
        assert not window.view.wheel_scrolls and window.act_wheel[False].isChecked()
        window.act_wheel[True].trigger()
        assert window.view.wheel_scrolls and window.schematic_view.wheel_scrolls
        assert window.act_wheel[True].isChecked() and not window.act_wheel[False].isChecked()
        window._save_session()
    finally:
        window._mark_saved()
        window.close()
    assert _settings_in_a_temp_file.value(WHEEL_SCROLLS_KEY) in (True, "true")

    again = MainWindow(document)
    try:
        again._restore_session()
        assert again.view.wheel_scrolls and again.schematic_view.wheel_scrolls
        assert again.act_wheel[True].isChecked()
    finally:
        again._mark_saved()
        again.close()


def test_a_board_told_to_scroll_pans_under_a_mouse_wheel() -> None:
    view = _board_view()
    try:
        view.wheel_scrolls = True
        scale, scroll = view.current_scale(), _scroll(view)
        QApplication.sendEvent(view.viewport(), _wheel(angle=(0, -NOTCH)))
        assert view.current_scale() == pytest.approx(scale)
        assert _scroll(view)[1] > scroll[1]
        QApplication.sendEvent(view.viewport(), _wheel(angle=(0, NOTCH), modifiers=CTRL))
        assert view.current_scale() == pytest.approx(scale * 1.15)
    finally:
        view.close()


# -- a solder trace is drawn in runs ---------------------------------------------------------


def _trace_scene():  # type: ignore[no-untyped-def]
    from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
    from perfboard_studio.commands import create_empty_document, create_standard_registry
    from perfboard_studio.model import DocumentMeta

    stamp = "2026-01-01T00:00:00.000Z"
    document = create_empty_document(DocumentMeta(name="t", created=stamp, modified=stamp))
    bus = CommandBus(document, create_standard_registry(), CommandContext(next_id=create_id_generator()))
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_drawing("solder-trace")
    return scene, bus


def _holes(*pairs: tuple[int, int]) -> tuple[object, ...]:
    from perfboard_studio.model import HoleCoord

    return tuple(HoleCoord(col, row) for col, row in pairs)


def test_seven_holes_of_solder_are_two_clicks_not_seven() -> None:
    """A trace had to be clicked pad by pad, and a click two holes away did nothing."""
    from perfboard_studio.model import HoleCoord

    scene, bus = _trace_scene()
    scene.draw_click(HoleCoord(2, 20))
    scene.draw_click(HoleCoord(8, 20))
    result = scene.commit_drawing()

    assert result is not None and result.ok, result
    assert bus.document.conductors[0].path == _holes(*((col, 20) for col in range(2, 9)))


def test_a_run_goes_along_the_row_then_down_the_column() -> None:
    from perfboard_studio.model import HoleCoord

    scene, bus = _trace_scene()
    scene.draw_click(HoleCoord(2, 2))
    scene.draw_click(HoleCoord(5, 4))
    scene.commit_drawing()
    assert bus.document.conductors[0].path == _holes(
        (2, 2), (3, 2), (4, 2), (5, 2), (5, 3), (5, 4)
    )


def test_slash_turns_the_corner_the_other_way() -> None:
    from perfboard_studio.model import HoleCoord

    scene, bus = _trace_scene()
    scene.draw_click(HoleCoord(2, 2))
    scene.flip_draw_corner()
    scene.draw_click(HoleCoord(5, 4))
    scene.commit_drawing()
    assert bus.document.conductors[0].path == _holes(
        (2, 2), (2, 3), (2, 4), (3, 4), (4, 4), (5, 4)
    )


def test_a_click_on_the_last_pad_again_finishes_the_trace() -> None:
    """Which is also what the second half of a double-click is."""
    from perfboard_studio.model import HoleCoord

    scene, bus = _trace_scene()
    scene.draw_click(HoleCoord(2, 2))
    scene.draw_click(HoleCoord(4, 2))
    result = scene.draw_click(HoleCoord(4, 2))

    assert result is not None and result.ok, result
    assert len(bus.document.conductors[0].path) == 3
    assert scene.armed_draw_kind is None


def test_a_run_back_over_the_traces_own_pads_is_refused_and_shown_red() -> None:
    from perfboard_studio.model import HoleCoord
    from perfboard_studio.ui.view2d import DrawPreviewItem

    scene, bus = _trace_scene()
    scene.draw_click(HoleCoord(2, 2))
    scene.draw_click(HoleCoord(6, 2))
    assert scene.draw_click(HoleCoord(4, 2)) is None
    scene.hover_at(hole_to_screen(HoleCoord(4, 2), bus.document.board, "top"))

    preview = next(item for item in scene.items() if isinstance(item, DrawPreviewItem))
    assert not preview.next_ok
    assert preview.path == list(_holes(*((col, 2) for col in range(2, 7))))


def test_the_preview_shows_every_pad_the_next_click_would_solder() -> None:
    from perfboard_studio.model import HoleCoord
    from perfboard_studio.ui.view2d import DrawPreviewItem

    scene, bus = _trace_scene()
    scene.draw_click(HoleCoord(2, 2))
    scene.hover_at(hole_to_screen(HoleCoord(4, 3), bus.document.board, "top"))

    preview = next(item for item in scene.items() if isinstance(item, DrawPreviewItem))
    assert preview.next_ok
    assert preview.run == list(_holes((3, 2), (4, 2), (4, 3)))


def test_a_wire_is_still_its_two_ends() -> None:
    from perfboard_studio.model import HoleCoord

    scene, bus = _trace_scene()
    scene.arm_drawing("bare-wire")
    scene.draw_click(HoleCoord(2, 2))
    result = scene.draw_click(HoleCoord(6, 5))
    assert result is not None and result.ok
    assert bus.document.conductors[0].path == _holes((2, 2), (6, 5))


def test_a_double_click_finishes_the_trace() -> None:
    """Through the view, as a person does it: the second half of a double-click lands on
    the pad the first half just reached, which is "finish"."""
    from perfboard_studio.model import HoleCoord

    scene, bus = _trace_scene()
    view = BoardView(scene)
    view.resize(600, 500)
    view.show()
    view.fit_board()
    QApplication.processEvents()
    try:
        port = view.viewport()
        board = bus.document.board
        start = view.mapFromScene(hole_to_screen(HoleCoord(2, 2), board, "top"))
        end = view.mapFromScene(hole_to_screen(HoleCoord(6, 2), board, "top"))
        _click(port, start)
        _mouse(port, QEvent.Type.MouseButtonPress, end, LEFT)
        _mouse(port, QEvent.Type.MouseButtonRelease, end, NONE)
        _mouse(port, QEvent.Type.MouseButtonDblClick, end, LEFT)
        _mouse(port, QEvent.Type.MouseButtonRelease, end, NONE)
        assert bus.document.conductors, "the double-click should have finished the trace"
        assert bus.document.conductors[0].path == _holes(*((col, 2) for col in range(2, 7)))
        assert scene.armed_draw_kind is None
    finally:
        view.close()


# -- a group gesture is one command -------------------------------------------------------------


def _window_with_selected(count: int, *, lock_second: bool = False):  # type: ignore[no-untyped-def]
    from perfboard_studio.commands import UpdateComponentPayload
    from perfboard_studio.ui.main import MainWindow

    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    window = MainWindow(document)
    # Parts the board draws: a fixture's part on a footprint nobody has is not on it.
    ids = [
        c.id
        for c in window.bus.document.components
        if not c.locked and c.id in window.scene.component_items
    ][:count]
    if lock_second:
        assert window.bus.dispatch("component.update", UpdateComponentPayload(id=ids[1], locked=True)).ok
    for component_id in ids:
        window.scene.component_items[component_id].setSelected(True)
    return window, ids


def _close_window(window) -> None:  # type: ignore[no-untyped-def]
    window._mark_saved()
    window.close()


def test_rotating_a_selection_is_one_undo_step() -> None:
    """R over three parts was three commands and three presses of Ctrl+Z."""
    window, _ids = _window_with_selected(3)
    try:
        before = window.bus.document
        steps = len(window.bus.history())
        window.on_rotate_selection(90)
        assert len(window.bus.history()) == steps + 1
        assert window.bus.history()[-1] == "Rotate 3 component(s)"
        window.on_undo()
        assert window.bus.document == before
    finally:
        _close_window(window)


def test_a_locked_part_in_the_selection_turns_none_of_it_and_says_which() -> None:
    """It used to turn the others and refuse the one, leaving the group half turned."""
    window, ids = _window_with_selected(3, lock_second=True)
    try:
        before = window.bus.document
        window.on_rotate_selection(90)
        window.on_mirror_selection()
        assert window.bus.document == before
        locked = next(c for c in before.components if c.id == ids[1])
        assert locked.ref in window.statusBar().currentMessage()
    finally:
        _close_window(window)


def test_locking_a_selection_is_one_step_to_one_state() -> None:
    window, ids = _window_with_selected(3, lock_second=True)
    try:
        steps = len(window.bus.history())
        window.on_toggle_lock_selection()  # The first part is unlocked, so: lock them all.
        assert all(c.locked for c in window.bus.document.components if c.id in ids)
        assert len(window.bus.history()) == steps + 1
        assert window.bus.history()[-1] == "Lock 3 component(s)"
    finally:
        _close_window(window)


def test_deleting_parts_and_their_copper_is_one_undo_step(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A rubber band over two parts and a trace was a Ctrl+Z per part and one for the trace."""
    from perfboard_studio.ui.view2d import ConductorItem

    window, ids = _window_with_selected(2)
    try:
        conductor = next(item for item in window.scene.items() if isinstance(item, ConductorItem))
        conductor.setSelected(True)
        monkeypatch.setattr(type(window), "_confirm", lambda self, *a, **k: True)
        before = window.bus.document
        steps = len(window.bus.history())
        window.on_delete_selection()
        assert not any(c.id in ids for c in window.bus.document.components)
        assert all(c.id != conductor.conductor_id for c in window.bus.document.conductors)
        assert len(window.bus.history()) == steps + 1
        window.on_undo()
        assert window.bus.document == before
    finally:
        _close_window(window)


# -- a dragged part says whether it can land, while it is dragged -----------------------------


def _held_part_scene():  # type: ignore[no-untyped-def]
    from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
    from perfboard_studio.commands import create_standard_registry

    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    bus = CommandBus(document, create_standard_registry(), CommandContext(next_id=create_id_generator()))
    scene = BoardScene(document, footprint_lookup(), side="top", bus=bus)
    view = BoardView(scene)
    view.resize(900, 700)
    view.show()
    view.fit_board()
    QApplication.processEvents()
    selectable = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
    item = next(
        i
        for i in scene.component_items.values()
        if len(i.fp.pins) == 2
        and next((u for u in scene.items(i.sceneBoundingRect().center()) if u.flags() & selectable), None) is i
    )
    return bus, scene, view, item


def _hold_at(view: BoardView, item, delta_cols: int, delta_rows: int) -> QPoint:  # type: ignore[no-untyped-def]
    """Press on the part and move it by whole holes, without letting go."""
    pitch = view.board_scene.document.board.pitch
    start = view.mapFromScene(item.sceneBoundingRect().center())
    end = view.mapFromScene(
        item.sceneBoundingRect().center() + QPointF(delta_cols * pitch, delta_rows * pitch)
    )
    port = view.viewport()
    _mouse(port, QEvent.Type.MouseButtonPress, start, LEFT)
    for i in range(1, 6):
        _mouse(port, QEvent.Type.MouseMove, start + (end - start) * i / 5, LEFT)
    return end


def test_a_part_dragged_onto_another_parts_pin_goes_red_and_says_so_before_the_release() -> None:
    """The ghost of a part being placed has always been red where it cannot go; a part
    already on the board, dragged, found out from a refusal after it was let go."""
    _bus, scene, view, item = _held_part_scene()
    try:
        comp_id = item.comp.id
        other = next(c for c in scene.document.components if c.id != comp_id and c.id in scene.component_items)
        end = _hold_at(view, item, other.anchor.col - item.comp.anchor.col, other.anchor.row - item.comp.anchor.row)
        held = scene.component_items[comp_id]
        assert held.pending_anchor == other.anchor
        assert held.drag_blocked
        said = view.drag_banner.text()
        assert said.startswith(f"{item.comp.ref} → ") and "pin(s) in a used hole" in said
        assert not view.drag_banner.isHidden()

        _mouse(view.viewport(), QEvent.Type.MouseButtonRelease, end, NONE)
        assert view.drag_banner.isHidden()
    finally:
        view.close()


def test_a_part_dragged_off_the_board_says_so_and_a_clear_spot_says_only_where() -> None:
    bus, scene, view, item = _held_part_scene()
    try:
        comp_id = item.comp.id
        board = scene.document.board
        end = _hold_at(view, item, -(item.comp.anchor.col + 3), 0)
        assert scene.component_items[comp_id].drag_blocked
        assert view.drag_banner.text().endswith("· off the board")
        _mouse(view.viewport(), QEvent.Type.MouseButtonRelease, end, NONE)
        assert all(c.anchor == item.comp.anchor for c in bus.document.components if c.id == comp_id)
    finally:
        view.close()

    # A spot the ghost would call clear: the drag says where, and nothing else.
    _bus, scene, view, item = _held_part_scene()
    try:
        comp_id = item.comp.id
        clear = next(
            HoleCoord(col, row)
            for row in range(board.rows)
            for col in range(board.cols)
            if not scene._drop_blocked(item.fp, HoleCoord(col, row), item.comp.rotation, item.comp.mirrored, comp_id)
        )
        end = _hold_at(view, item, clear.col - item.comp.anchor.col, clear.row - item.comp.anchor.row)
        assert not scene.component_items[comp_id].drag_blocked
        assert " · " not in view.drag_banner.text()
        _mouse(view.viewport(), QEvent.Type.MouseButtonRelease, end, NONE)
    finally:
        view.close()


def test_the_ghost_and_the_drag_ask_one_question() -> None:
    """Every hole of the board, for a part armed and the same part dropped: one answer."""
    from perfboard_studio.footprints import get_footprint

    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    scene = BoardScene(document, footprint_lookup(), side="top")
    footprint = get_footprint("r-axial-3")
    assert footprint is not None
    scene.arm_placement("r-axial-3")
    for row in range(-1, document.board.rows + 1):
        for col in range(-1, document.board.cols + 1):
            at = HoleCoord(col, row)
            assert scene._placement_blocked(at) == scene._drop_blocked(footprint, at, 0, False, None), at
