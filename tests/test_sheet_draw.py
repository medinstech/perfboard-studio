"""The wire tool draws corner by corner: a pin or a wire to start, a click on bare sheet for
each corner, a pin or a wire to finish (``SchematicView``, ``viewsch.cornered_path``). Esc
or a right-click drops the wire being drawn, Backspace takes back its last corner, and
``sheet.wire`` refuses a run on a slant."""

from __future__ import annotations

import itertools

import pytest

from .test_ui import _blank_window, _close, _pin_on_screen, _send_mouse, _wire_view


@pytest.fixture(scope="module", autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _pts(path) -> list[tuple[float, float]]:
    return [(round(p.x(), 3), round(p.y(), 3)) for p in path]


def _square(path) -> bool:
    return all(
        abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6 for a, b in itertools.pairwise(path)
    )


# -- the geometry ---------------------------------------------------------------------------


def test_each_click_is_a_corner_and_the_last_leg_comes_into_the_pin_along_its_lead() -> None:
    from PySide6.QtCore import QPointF

    from perfboard_studio.ui.viewsch import cornered_path

    path = cornered_path(
        QPointF(0, 0), True, [QPointF(10, 10)], QPointF(30, 20), arrives_across=True
    )
    # Out of the pin along its lead, an elbow to the corner, then into the end pin across.
    # The corner falls in the middle of the run down, so it is not stored as a point.
    assert _pts(path) == [(0, 0), (10, 0), (10, 20), (30, 20)]


def test_the_last_leg_never_runs_back_down_the_line_just_drawn() -> None:
    from PySide6.QtCore import QPointF

    from perfboard_studio.ui.viewsch import cornered_path

    path = _pts(
        cornered_path(QPointF(0, 0), True, [QPointF(10, 10)], QPointF(20, 0), arrives_across=True)
    )
    assert path == [(0, 0), (10, 0), (10, 10), (20, 10), (20, 0)]


def test_corners_in_one_line_are_one_run() -> None:
    from PySide6.QtCore import QPointF

    from perfboard_studio.ui.viewsch import cornered_path

    path = cornered_path(
        QPointF(0, 0), True, [QPointF(10, 0), QPointF(20, 0)], QPointF(30, 0), arrives_across=True
    )
    assert _pts(path) == [(0, 0), (30, 0)]


def test_a_branch_drawn_with_corners_lands_square_on_the_wire() -> None:
    from PySide6.QtCore import QPointF

    from perfboard_studio.ui.viewsch import cornered_path

    # Onto a horizontal wire at (40, 0): the last run comes down onto it, not along it.
    path = _pts(cornered_path(QPointF(0, 20), True, [QPointF(20, 30)], QPointF(40, 0), tee=True))
    assert path[-1] == (40, 0) and path[-2][0] == 40 and _square(path)


# -- the gesture ----------------------------------------------------------------------------


def _below(view, mm: float = 7.62):
    """A point of bare sheet under every symbol, in scene millimetres."""
    from PySide6.QtCore import QPointF

    bottom = max(s.at.y + s.height for s in view.item.drawing.symbols)
    return lambda x: QPointF(x, bottom + mm)


def _click_scene(view, point) -> None:
    at = view.mapFromScene(point)
    _send_mouse(view, "press", at)
    _send_mouse(view, "release", at)


def _anchor(view, ref, number):
    from perfboard_studio.ui.viewsch import pin_anchor

    return pin_anchor(view.item.drawing, ref, number)


def test_a_click_on_bare_sheet_is_a_corner_and_the_wire_goes_through_it() -> None:
    window, view = _wire_view()
    drawn: list[tuple] = []
    view.wireDrawn.connect(lambda *args: drawn.append(args))
    try:
        start, end = _anchor(view, "R1", "2"), _anchor(view, "R2", "1")
        under = _below(view)
        first, second = under(start.x() + 5.08), under(end.x() - 5.08)
        start_px, end_px = _pin_on_screen(view, "R1", "2"), _pin_on_screen(view, "R2", "1")
        _send_mouse(view, "press", start_px)
        _send_mouse(view, "release", start_px)
        _click_scene(view, first)
        assert view.pending_pin == ("R1", "2"), "a miss used to call the wire off"
        _click_scene(view, second)
        assert len(view.corners) == 2
        # The preview goes through both corners to wherever the pointer is.
        _send_mouse(view, "move", end_px)
        ghost = _pts(view.item.ghost_path)
        assert _pts([first])[0] in ghost and _pts([second])[0] in ghost
        _send_mouse(view, "press", end_px)
        _send_mouse(view, "release", end_px)

        ((a_ref, a_pin, b_ref, b_pin, path),) = drawn
        assert (a_ref, a_pin, b_ref, b_pin) == ("R1", "2", "R2", "1")
        rounded = [(round(x, 3), round(y, 3)) for x, y in path]
        assert rounded[0] == _pts([start])[0] and rounded[-1] == _pts([end])[0]
        assert _pts([first])[0] in rounded and _pts([second])[0] in rounded
        assert _square(rounded)
        assert view.corners == [] and view.pending_pin is None
    finally:
        view.close()
        view.deleteLater()
        _close(window)


def test_a_click_inside_a_symbol_takes_no_corner() -> None:
    from PySide6.QtCore import QPointF

    window, view = _wire_view()
    try:
        px = _pin_on_screen(view, "R1", "2")
        _send_mouse(view, "press", px)
        _send_mouse(view, "release", px)
        body = next(s for s in view.item.drawing.symbols if s.ref == "R2")
        _click_scene(view, QPointF(body.at.x + body.width / 2, body.at.y + body.height / 2))
        assert view.corners == [] and view.pending_pin == ("R1", "2")
    finally:
        view.close()
        view.deleteLater()
        _close(window)


def _key(view, key) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(view, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_backspace_takes_back_a_corner_and_escape_drops_the_wire_then_the_tool() -> None:
    from PySide6.QtCore import Qt

    window, view = _wire_view()
    told: list[tuple] = []
    view.pinClicked.connect(lambda *args: told.append(args))
    try:
        under = _below(view)
        px = _pin_on_screen(view, "R1", "2")
        _send_mouse(view, "press", px)
        _send_mouse(view, "release", px)
        _click_scene(view, under(10.16))
        _click_scene(view, under(30.48))
        _key(view, Qt.Key.Key_Backspace)
        assert len(view.corners) == 1 and view.pending_pin == ("R1", "2")
        _key(view, Qt.Key.Key_Escape)
        assert view.corners == [] and view.pending_pin is None and view.tool == "wire"
        assert told[-1] == ("", "")
        assert view.item.ghost_path == ()
        _key(view, Qt.Key.Key_Escape)
        assert view.tool == "select"
    finally:
        view.close()
        view.deleteLater()
        _close(window)


def test_a_right_click_drops_the_wire_and_the_next_puts_the_tool_down() -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent

    window, view = _wire_view()
    try:
        px = _pin_on_screen(view, "R1", "2")
        _send_mouse(view, "press", px)
        _send_mouse(view, "release", px)
        _click_scene(view, _below(view)(10.16))
        menu = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5))
        view.contextMenuEvent(menu)
        assert not view.wire_in_progress() and view.corners == [] and view.tool == "wire"
        view.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5)))
        assert view.tool == "select"
    finally:
        view.close()
        view.deleteLater()
        _close(window)


# -- through the window and the command -----------------------------------------------------


def _add(window, ref: str) -> None:
    from perfboard_studio.commands import AddPartPayload

    assert window.bus.dispatch("part.add", AddPartPayload(ref=ref, footprint_id="r-axial-3")).ok


def test_a_wire_drawn_with_corners_is_stored_as_drawn_and_joins_the_pins() -> None:
    window = _blank_window()
    for ref in ("R1", "R2"):
        _add(window, ref)
    view = window.schematic_view
    window.on_sheet_tool("wire")
    window._refresh_schematic_panel()
    corner = _below(view)(_anchor(view, "R1", "2").x() + 5.08)
    view._wire_click(("R1", "2"))
    view._add_corner(corner)
    view._wire_click(("R2", "1"))

    (net,) = window.bus.document.nets
    assert {(n.component_ref, n.pin) for n in net.nodes} == {("R1", "2"), ("R2", "1")}
    (wire,) = window.bus.document.sheet_wires
    points = [(round(p.x, 3), round(p.y, 3)) for p in wire.path]
    assert (round(corner.x(), 3), round(corner.y(), 3)) in points and _square(points)
    _close(window)


def test_a_wire_clicked_first_then_corners_then_a_pin_is_a_t_stored_from_the_pin() -> None:
    from .test_ui import _middle_of_drawn_wire

    window = _blank_window()
    for ref in ("R1", "R2", "R3"):
        _add(window, ref)
    view = window.schematic_view
    window.on_sheet_tool("wire")
    view._wire_click(("R1", "2"))
    view._wire_click(("R2", "1"))
    window._refresh_schematic_panel()

    middle, ends = _middle_of_drawn_wire(view)
    tee = view.tee_at(middle)
    view._tee_click(tee)
    corner = _below(view, 12.7)(tee.at.x() + 7.62)
    view._add_corner(corner)
    view._wire_click(("R3", "1"))

    branch = next(w for w in window.bus.document.sheet_wires if w.tap is not None)
    points = [(round(p.x, 3), round(p.y, 3)) for p in branch.path]
    assert branch.a.component_ref == "R3" and branch.host_pins == frozenset(ends)
    assert points[0] == _pts([_anchor(view, "R3", "1")])[0]
    assert points[-1] == _pts([tee.at])[0]
    assert (round(corner.x(), 3), round(corner.y(), 3)) in points and _square(points)
    assert len(window.bus.document.nets[0].nodes) == 3
    _close(window)


def test_the_command_refuses_a_wire_on_a_slant() -> None:
    from perfboard_studio.commands import DrawSheetWirePayload
    from perfboard_studio.model import Point2, SheetWire

    from .test_sheet_tee import _bus, _pin

    bus = _bus()
    wire = SheetWire(
        a=_pin("R1", "2"), b=_pin("R2", "1"), path=(Point2(x=0, y=0), Point2(x=5.08, y=2.54))
    )
    result = bus.dispatch("sheet.wire", DrawSheetWirePayload(wire=wire))
    assert not result.ok and result.code == "diagonal-wire"
    assert bus.document.nets == ()
