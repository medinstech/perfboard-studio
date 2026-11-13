"""An end of a drawn wire dragged onto another pin (``sheet.wire.reconnect``): the pin it
left comes off the net as a cut takes it off, the pin it went to joins as a drawn wire joins
it, and a T on the wire stays on it. The rules are the command's docstring; each is a test."""

from __future__ import annotations

import itertools

import pytest

from perfboard_studio.commands import ReconnectSheetWirePayload
from perfboard_studio.model import NetNode, Point2
from perfboard_studio.schematic import moved_end

from .test_sheet_cut import _chain, _nodes, _wire_between
from .test_sheet_tee import _at, _bus, _drawing, _pin, _tee, _wire


@pytest.fixture(scope="module", autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _reconnect(bus, wire, end: NetNode, to: NetNode):
    """Move ``end`` of ``wire`` to ``to``, along the path the view would hand over."""
    path = wire.path if end == wire.b else tuple(reversed(wire.path))
    target = _at(_drawing(bus), to.component_ref, to.pin)
    return bus.dispatch(
        "sheet.wire.reconnect",
        ReconnectSheetWirePayload(
            a=wire.a, b=wire.b, end=end, to=to, path=moved_end(path, target)
        ),
    )


def _square(path) -> bool:
    return all(abs(a.x - b.x) < 1e-6 or abs(a.y - b.y) < 1e-6 for a, b in itertools.pairwise(path))


def test_the_end_moves_to_the_new_pin_and_the_old_one_leaves_the_net() -> None:
    bus = _bus()
    r1, r2, r3 = _pin("R1", "2"), _pin("R2", "1"), _pin("R3", "1")
    _wire(bus, r1, r2)
    (net,) = bus.document.nets
    (wire,) = bus.document.sheet_wires
    result = _reconnect(bus, wire, r2, r3)
    assert result.ok, result.message
    (after,) = bus.document.nets
    assert after.id == net.id and after.name == net.name
    assert _nodes(bus) == [{("R1", "2"), ("R3", "1")}]
    (moved,) = bus.document.sheet_wires
    assert (moved.a, moved.b) == (r1, r3) and _square(moved.path)
    assert moved.path[-1] == _at(_drawing(bus), "R3", "1")
    assert result.description == "Move the wire from R1.2 off R2.1 onto R3.1"
    assert bus.undo() and bus.document.sheet_wires == (wire,) and bus.document.nets == (net,)


def test_moving_the_first_end_keeps_the_wire_running_from_its_new_pin() -> None:
    bus = _bus()
    r1, r2, r4 = _pin("R1", "2"), _pin("R2", "1"), _pin("R4", "1")
    _wire(bus, r1, r2)
    (wire,) = bus.document.sheet_wires
    assert _reconnect(bus, wire, r1, r4).ok
    (moved,) = bus.document.sheet_wires
    assert (moved.a, moved.b) == (r4, r2)
    drawing = _drawing(bus)
    assert moved.path[0] == _at(drawing, "R4", "1") and moved.path[-1] == _at(drawing, "R2", "1")


def test_a_pin_another_wire_still_holds_stays_and_the_net_splits_where_the_wires_part() -> None:
    bus = _bus()
    r1, r2, r3, r4 = _pin("R1", "2"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1")
    _chain(bus, r1, r2, r3)
    # R1-R2 moved off R2 onto R4: R2 is still held by R2-R3, and the wires now draw two
    # pieces, R1-R4 and R2-R3. Two of each, so the one with the net's first pin keeps GND.
    assert _reconnect(bus, _wire_between(bus, r1, r2), r2, r4).ok
    names = {net.name: {(n.component_ref, n.pin) for n in net.nodes} for net in bus.document.nets}
    assert names["GND"] == {("R1", "2"), ("R4", "1")}
    (other,) = (pins for name, pins in names.items() if name != "GND")
    assert other == {("R2", "1"), ("R3", "1")}
    for wire in bus.document.sheet_wires:
        assert any(wire.a in net.nodes and wire.b in net.nodes for net in bus.document.nets)


def test_a_pin_on_another_net_is_refused_and_nothing_changes() -> None:
    bus = _bus()
    r1, r2, r3, r4 = _pin("R1", "2"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1")
    _wire(bus, r1, r2)
    _wire(bus, r3, r4)
    before = bus.document
    result = _reconnect(bus, _wire_between(bus, r1, r2), r2, r3)
    assert not result.ok and result.code == "two-nets"
    assert bus.document is before


def test_a_t_on_the_wire_follows_it_to_the_new_pin() -> None:
    bus = _bus()
    r1, r2, r3, r4 = _pin("R1", "2"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1")
    _wire(bus, r1, r2)
    assert _tee(bus, r3, (r1, r2))[0].ok
    assert _reconnect(bus, _wire_between(bus, r1, r2), r2, r4).ok
    tee = next(w for w in bus.document.sheet_wires if w.tap is not None)
    assert tee.host_pins == frozenset((r1, r4))
    assert _nodes(bus) == [{("R1", "2"), ("R3", "1"), ("R4", "1")}]
    # And it is drawn on the wire, not dropped to its pin.
    assert any(w.ends == (r3, tee.b) for w in _drawing(bus).wires)


def test_the_end_of_a_t_on_its_wire_is_not_a_pin_to_move() -> None:
    bus = _bus()
    r1, r2, r3, r4 = _pin("R1", "2"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1")
    _wire(bus, r1, r2)
    assert _tee(bus, r3, (r1, r2))[0].ok
    tee = next(w for w in bus.document.sheet_wires if w.tap is not None)
    result = bus.dispatch(
        "sheet.wire.reconnect",
        ReconnectSheetWirePayload(a=tee.a, b=tee.b, end=tee.b, to=r4, path=tee.path),
    )
    assert not result.ok and result.code == "branch-end"


def test_refusals_name_what_is_wrong() -> None:
    bus = _bus()
    r1, r2, r3 = _pin("R1", "2"), _pin("R2", "1"), _pin("R3", "1")
    _wire(bus, r1, r2)
    (wire,) = bus.document.sheet_wires
    path = (Point2(x=0, y=0), Point2(x=2.54, y=0))
    for end, to, code in (
        (r2, r2, "nothing-to-do"),
        (r2, r1, "same-pin"),
        (r3, r2, "not-an-end"),
    ):
        result = bus.dispatch(
            "sheet.wire.reconnect",
            ReconnectSheetWirePayload(a=wire.a, b=wire.b, end=end, to=to, path=path),
        )
        assert not result.ok and result.code == code, (end, to, result.code)
    slanted = (wire.path[0], Point2(x=wire.path[0].x + 5.08, y=wire.path[0].y + 2.54))
    result = bus.dispatch(
        "sheet.wire.reconnect",
        ReconnectSheetWirePayload(a=wire.a, b=wire.b, end=r2, to=r3, path=slanted),
    )
    assert not result.ok and result.code == "diagonal-wire"


# -- the gesture ----------------------------------------------------------------------------


def test_the_selected_wires_end_dragged_onto_a_pin_moves_there() -> None:
    from PySide6.QtCore import QPointF

    from perfboard_studio.ui.viewsch import pin_anchor

    from .test_sheet_reshape import _drag, _drawn, _select_view
    from .test_ui import _send_mouse

    _, view = _select_view()
    told: list[tuple] = []
    view.wireEndMoved.connect(lambda *args: told.append(args))
    try:
        wire = _drawn(view)
        start, end = wire.path[0], wire.path[-1]
        middle = view.mapFromScene(QPointF((start.x + end.x) / 2, (start.y + end.y) / 2))
        _send_mouse(view, "press", middle)
        _send_mouse(view, "release", middle)
        assert view.selected_wire is not None
        target = pin_anchor(view.item.drawing, "R3", "1")
        _drag(view, QPointF(end.x, end.y), target)
        ((a_ref, a_pin, b_ref, b_pin, e_ref, e_pin, t_ref, t_pin, path),) = told
        assert (a_ref, a_pin, b_ref, b_pin) == ("R1", "2", "R2", "1")
        assert (e_ref, e_pin, t_ref, t_pin) == ("R2", "1", "R3", "1")
        points = [Point2(x=x, y=y) for x, y in path]
        assert (points[0].x, points[0].y) == (start.x, start.y)
        assert abs(points[-1].x - target.x()) < 1e-6 and abs(points[-1].y - target.y()) < 1e-6
        assert _square(points) and not view.gesture_in_flight()
    finally:
        view.close()
        view.deleteLater()


def test_only_the_selected_wires_end_is_taken_off_its_pin() -> None:
    """With no wire selected, a press where a wire meets its pin is not a hold on that
    end: a wire is never torn off a pin by a press that only selected it."""
    from PySide6.QtCore import QPointF

    from perfboard_studio.ui.viewsch import pin_anchor

    from .test_sheet_reshape import _drag, _drawn, _select_view

    _, view = _select_view()
    moved: list[tuple] = []
    view.wireEndMoved.connect(lambda *args: moved.append(args))
    try:
        end = _drawn(view).path[-1]
        _drag(view, QPointF(end.x, end.y), pin_anchor(view.item.drawing, "R3", "1"))
        assert moved == []
    finally:
        view.close()
        view.deleteLater()


def test_an_end_let_go_over_no_pin_stays_where_it_was() -> None:
    from PySide6.QtCore import QPointF

    from .test_sheet_reshape import _drag, _drawn, _select_view
    from .test_ui import _send_mouse

    _, view = _select_view()
    told: list[tuple] = []
    view.wireEndMoved.connect(lambda *args: told.append(args))
    try:
        wire = _drawn(view)
        start, end = wire.path[0], wire.path[-1]
        middle = view.mapFromScene(QPointF((start.x + end.x) / 2, (start.y + end.y) / 2))
        _send_mouse(view, "press", middle)
        _send_mouse(view, "release", middle)
        _drag(view, QPointF(end.x, end.y), QPointF(end.x, end.y + 30))
        assert told == [] and view.item.ghost_path == ()
    finally:
        view.close()
        view.deleteLater()
