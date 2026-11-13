"""A drawn wire is reshaped by dragging it in Select: a corner pressed goes where it is
dragged, anything else drags the run under the pointer sideways
(``schematic.moved_corner`` / ``moved_run``). The ends stay on their pins, every run stays
across or down, and ``sheet.wire.reshape`` stores the new path and touches no net."""

from __future__ import annotations

import itertools

import pytest

from perfboard_studio.commands import DrawSheetWirePayload, ReshapeSheetWirePayload
from perfboard_studio.model import NetNode, Point2, SheetWire
from perfboard_studio.schematic import GRID_MM, moved_corner, moved_run

from .test_sheet_tee import _bus, _pin

G = GRID_MM


@pytest.fixture(scope="module", autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _xy(path) -> list[tuple[float, float]]:
    return [(round(p.x, 3), round(p.y, 3)) for p in path]


def _square(path) -> bool:
    return all(abs(a.x - b.x) < 1e-6 or abs(a.y - b.y) < 1e-6 for a, b in itertools.pairwise(path))


def _turns_back(path) -> bool:
    for a, b, c in zip(path, path[1:], path[2:], strict=False):
        in_line = (abs(a.x - b.x) < 1e-9 and abs(b.x - c.x) < 1e-9) or (
            abs(a.y - b.y) < 1e-9 and abs(b.y - c.y) < 1e-9
        )
        if in_line and (b.x - a.x) * (c.x - b.x) + (b.y - a.y) * (c.y - b.y) < 0:
            return True
    return False


def _path(*points: tuple[float, float]) -> tuple[Point2, ...]:
    return tuple(Point2(x=x * G, y=y * G) for x, y in points)


# -- the geometry ---------------------------------------------------------------------------


def test_the_straight_wire_between_two_pins_dragged_down_is_a_u_off_both_pins() -> None:
    path = moved_run(_path((0, 0), (10, 0)), 0, Point2(x=5 * G, y=3 * G))
    # One square of the wire stays at each pin, leaving it the way its lead points.
    assert _xy(path) == _xy(_path((0, 0), (1, 0), (1, 3), (9, 3), (9, 0), (10, 0)))


def test_a_run_between_two_corners_slides_and_the_runs_either_side_follow() -> None:
    z = _path((0, 0), (4, 0), (4, 4), (8, 4))
    assert _xy(moved_run(z, 1, Point2(x=6 * G, y=1.0))) == _xy(
        _path((0, 0), (6, 0), (6, 4), (8, 4))
    )


def test_a_run_dragged_along_itself_is_the_same_wire() -> None:
    z = _path((0, 0), (4, 0), (4, 4), (8, 4))
    assert moved_run(z, 1, Point2(x=4 * G, y=9 * G)) == z


def test_a_corner_between_corners_takes_its_neighbours_with_it() -> None:
    path = _path((0, 0), (2, 0), (2, 2), (6, 2), (6, 4), (8, 4))
    moved = moved_corner(path, 2, Point2(x=3 * G, y=3 * G))
    assert _xy(moved) == _xy(_path((0, 0), (3, 0), (3, 3), (6, 3), (6, 4), (8, 4)))


def test_a_corner_next_to_a_pin_leaves_the_pin_sideways_and_never_doubles_back() -> None:
    z = _path((0, 0), (4, 0), (4, 4), (8, 4))
    # Dragged up past the line the wire leaves its pin on: the straight-on elbow would run
    # up and straight back down, so the wire steps out one square and goes round.
    moved = moved_corner(z, 1, Point2(x=6 * G, y=-2 * G))
    assert moved[0] == z[0] and moved[-1] == z[-1]
    assert abs(moved[1].y - moved[0].y) < 1e-9, "it still leaves the pin sideways"
    assert _square(moved) and not _turns_back(moved)
    assert Point2(x=6 * G, y=-2 * G) in moved


def test_an_end_is_never_a_corner_to_drag() -> None:
    z = _path((0, 0), (4, 0), (4, 4))
    assert moved_corner(z, 0, Point2(x=9 * G, y=9 * G)) == z
    assert moved_corner(z, 2, Point2(x=9 * G, y=9 * G)) == z


def test_where_the_pointer_is_snaps_to_the_grid() -> None:
    path = moved_run(_path((0, 0), (10, 0)), 0, Point2(x=5 * G, y=3 * G + 0.4))
    assert all(round(p.y / G, 6).is_integer() for p in path)


# -- the command ----------------------------------------------------------------------------


def _drawn_bus():
    """``test_sheet_tee._bus`` with one wire drawn straight across from R1.2 to R2.1."""
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.schematic import build_schematic

    bus = _bus()
    drawing = build_schematic(bus.document, footprint_lookup())
    anchors = {
        (s.ref, pin.number): Point2(x=s.at.x + pin.at.x, y=s.at.y + pin.at.y)
        for s in drawing.symbols
        for pin in s.pins
    }
    start, end = anchors[("R1", "2")], anchors[("R2", "1")]
    path = (start, end) if start.y == end.y else (start, Point2(x=end.x, y=start.y), end)
    wire = SheetWire(a=_pin("R1", "2"), b=_pin("R2", "1"), path=path)
    assert bus.dispatch("sheet.wire", DrawSheetWirePayload(wire=wire)).ok
    return bus


def test_reshape_stores_the_path_and_leaves_every_net_alone() -> None:
    bus = _drawn_bus()
    nets = bus.document.nets
    (wire,) = bus.document.sheet_wires
    new = moved_run(wire.path, 0, Point2(x=wire.path[0].x + 5 * G, y=wire.path[0].y + 4 * G))
    result = bus.dispatch(
        "sheet.wire.reshape", ReshapeSheetWirePayload(a=wire.a, b=wire.b, path=new)
    )
    assert result.ok, result.message
    assert bus.document.nets == nets
    (reshaped,) = bus.document.sheet_wires
    assert reshaped.path == new and (reshaped.a, reshaped.b) == (wire.a, wire.b)
    assert bus.undo() and bus.document.sheet_wires == (wire,)


def test_a_path_handed_over_from_the_other_end_is_stored_the_way_the_wire_runs() -> None:
    bus = _drawn_bus()
    (wire,) = bus.document.sheet_wires
    new = moved_run(wire.path, 0, Point2(x=wire.path[0].x, y=wire.path[0].y - 3 * G))
    result = bus.dispatch(
        "sheet.wire.reshape",
        ReshapeSheetWirePayload(a=wire.b, b=wire.a, path=tuple(reversed(new))),
    )
    assert result.ok, result.message
    assert bus.document.sheet_wires[0].path == new


def test_reshape_refuses_a_slant_a_wire_that_is_not_there_and_no_change() -> None:
    bus = _drawn_bus()
    (wire,) = bus.document.sheet_wires
    slanted = (wire.path[0], Point2(x=wire.path[-1].x, y=wire.path[-1].y + G))
    for payload, code in (
        (ReshapeSheetWirePayload(a=wire.a, b=wire.b, path=slanted), "diagonal-wire"),
        (
            ReshapeSheetWirePayload(a=_pin("R3", "1"), b=_pin("R4", "1"), path=wire.path),
            "no-such-wire",
        ),
        (ReshapeSheetWirePayload(a=wire.a, b=wire.b, path=wire.path), "nothing-to-do"),
    ):
        result = bus.dispatch("sheet.wire.reshape", payload)
        assert not result.ok and result.code == code
    assert bus.document.sheet_wires == (wire,)


def test_the_undo_label_names_the_wire_by_its_pins() -> None:
    bus = _drawn_bus()
    (wire,) = bus.document.sheet_wires
    new = moved_run(wire.path, 0, Point2(x=wire.path[0].x, y=wire.path[0].y + 3 * G))
    result = bus.dispatch(
        "sheet.wire.reshape", ReshapeSheetWirePayload(a=wire.a, b=wire.b, path=new)
    )
    assert result.ok and result.description == "Reshape the wire from R1.2 to R2.1"


# -- the gesture ----------------------------------------------------------------------------


def _select_view():
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.schematic import build_schematic
    from perfboard_studio.ui.viewsch import SchematicView

    bus = _drawn_bus()
    view = SchematicView()
    view.resize(900, 600)
    view.show()
    QApplication.processEvents()
    view.set_drawing(build_schematic(bus.document, footprint_lookup()))
    view.fit()
    QApplication.processEvents()
    return bus, view


def _drawn(view):
    return next(w for w in view.item.drawing.wires if w.ends is not None)


def _drag(view, start, end, *, release: bool = True) -> None:
    from PySide6.QtCore import QPointF

    from .test_ui import _send_mouse

    a, b = view.mapFromScene(start), view.mapFromScene(end)
    _send_mouse(view, "press", a)
    for step in range(1, 6):
        at = QPointF(a) + (QPointF(b) - QPointF(a)) * (step / 5)
        _send_mouse(view, "move", at, pressed=True)
    if release:
        _send_mouse(view, "release", b)


def test_dragging_the_middle_of_a_wire_down_reshapes_it_and_keeps_its_ends() -> None:
    from PySide6.QtCore import QPointF

    bus, view = _select_view()
    told: list[tuple] = []
    view.wireReshaped.connect(lambda *args: told.append(args))
    try:
        wire = _drawn(view)
        start, end = wire.path[0], wire.path[-1]
        middle = QPointF((start.x + end.x) / 2, (start.y + end.y) / 2)
        _drag(view, middle, middle + QPointF(0, 4 * G))
        ((a_ref, a_pin, b_ref, b_pin, path),) = told
        assert {(a_ref, a_pin), (b_ref, b_pin)} == {("R1", "2"), ("R2", "1")}
        points = [Point2(x=x, y=y) for x, y in path]
        assert _xy(points[:1] + points[-1:]) == _xy((start, end))
        assert _square(points) and max(p.y for p in points) > start.y + 3 * G
        assert view.item.ghost_path == () and not view.gesture_in_flight()
        # And the command takes what the view hands it.
        result = bus.dispatch(
            "sheet.wire.reshape",
            ReshapeSheetWirePayload(
                a=NetNode(a_ref, a_pin), b=NetNode(b_ref, b_pin), path=tuple(points)
            ),
        )
        assert result.ok, result.message
    finally:
        view.close()
        view.deleteLater()


def test_a_click_on_a_wire_selects_it_and_reshapes_nothing() -> None:
    from PySide6.QtCore import QPointF

    from .test_ui import _send_mouse

    _, view = _select_view()
    told: list[tuple] = []
    view.wireReshaped.connect(lambda *args: told.append(args))
    try:
        wire = _drawn(view)
        start, end = wire.path[0], wire.path[-1]
        at = view.mapFromScene(QPointF((start.x + end.x) / 2, (start.y + end.y) / 2))
        _send_mouse(view, "press", at)
        _send_mouse(view, "release", at)
        assert told == [] and view.selected_wire is not None
    finally:
        view.close()
        view.deleteLater()


def test_escape_mid_drag_puts_the_wire_back() -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    from .test_ui import _send_mouse

    _, view = _select_view()
    told: list[tuple] = []
    view.wireReshaped.connect(lambda *args: told.append(args))
    try:
        wire = _drawn(view)
        start, end = wire.path[0], wire.path[-1]
        middle = QPointF((start.x + end.x) / 2, (start.y + end.y) / 2)
        _drag(view, middle, middle + QPointF(0, 4 * G), release=False)
        assert view.gesture_in_flight() and view.item.ghost_path
        QApplication.sendEvent(
            view,
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier),
        )
        assert not view.gesture_in_flight() and view.item.ghost_path == ()
        _send_mouse(view, "release", view.mapFromScene(middle + QPointF(0, 4 * G)))
        assert told == []
    finally:
        view.close()
        view.deleteLater()
