"""The port tool on the sheet: a ground, a supply or a name put on a pin or on bare sheet,
picked up, dragged, wired to with Connect and deleted -- the view's half and the window's
seam (``sheet.port.*``, ``tests/test_sheet_ports.py`` for the commands themselves)."""

from __future__ import annotations

import itertools

import pytest

from perfboard_studio.commands import AddNetPayload, AddSheetPortPayload
from perfboard_studio.model import NetNode, Point2, PortLink
from perfboard_studio.schematic import (
    GRID_MM,
    build_schematic,
    pin_position,
    port_stub,
    rail_glyph_box,
    snap_to_grid,
)

from .test_sheet_tee import LOOKUP, _bus

G = GRID_MM


@pytest.fixture(scope="module", autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _view(bus):
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.viewsch import SchematicView

    view = SchematicView()
    view.resize(900, 600)
    view.show()
    QApplication.processEvents()
    view.set_drawing(build_schematic(bus.document, LOOKUP))
    view.fit()
    QApplication.processEvents()
    return view


def _click(view, at) -> None:
    from PySide6.QtCore import QPointF

    from .test_ui import _send_mouse

    point = view.mapFromScene(QPointF(at.x, at.y) if isinstance(at, Point2) else at)
    _send_mouse(view, "press", point)
    _send_mouse(view, "release", point)


def _drag(view, start, end) -> None:
    from PySide6.QtCore import QPointF

    from .test_ui import _send_mouse

    a, b = view.mapFromScene(start), view.mapFromScene(end)
    _send_mouse(view, "press", a)
    for step in range(1, 6):
        _send_mouse(view, "move", QPointF(a) + (QPointF(b) - QPointF(a)) * (step / 5), pressed=True)
    _send_mouse(view, "release", b)


def _key(view, key) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def _dispatch_placed(bus, told) -> None:
    kind, name, x, y, ref, pin, path = told
    links = ()
    if ref:
        links = (
            PortLink(pin=NetNode(ref, pin), path=tuple(Point2(x=px, y=py) for px, py in path)),
        )
    result = bus.dispatch(
        "sheet.port.add",
        AddSheetPortPayload(kind=kind, name=name, at=Point2(x=x, y=y), links=links),
    )
    assert result.ok, result.message


def _with_ground(bus, ref: str = "R1", pin: str = "1"):
    """A ground port on a pin, put there the way the tool puts it."""
    drawing = build_schematic(bus.document, LOOKUP)
    stub = port_stub(drawing, "ground", "GND", ref, pin)
    assert stub is not None
    result = bus.dispatch(
        "sheet.port.add",
        AddSheetPortPayload(
            kind="ground", name="GND", at=stub[-1], links=(PortLink(pin=NetNode(ref, pin), path=stub),)
        ),
    )
    assert result.ok, result.message
    return bus.document.sheet_ports[-1]


# -- where a port put on a pin goes --------------------------------------------------------


def test_a_ground_put_on_a_pin_is_drawn_exactly_where_the_sheet_drew_that_pins_ground() -> None:
    """Putting GND on a pin the sheet already shows on ground changes only who owns it."""
    bus = _bus()
    assert bus.dispatch(
        "net.add",
        AddNetPayload(
            name="GND", net_class="ground", nodes=(NetNode("R1", "1"), NetNode("R3", "1"))
        ),
    ).ok
    before = build_schematic(bus.document, LOOKUP)
    anchor = pin_position(before, "R1", "1")
    (derived,) = [rail for rail in before.rails if rail.path[0] == anchor]
    stub = port_stub(before, "ground", "GND", "R1", "1")
    assert stub == derived.path
    port = _with_ground(bus)
    after = build_schematic(bus.document, LOOKUP)
    (owned,) = [rail for rail in after.rails if rail.path[0] == anchor]
    assert owned.port == port.id
    assert (owned.path, owned.at, owned.direction) == (derived.path, derived.at, derived.direction)


def test_a_name_put_on_a_pin_runs_out_along_the_way_the_pin_points() -> None:
    bus = _bus()
    drawing = build_schematic(bus.document, LOOKUP)
    anchor = pin_position(drawing, "R1", "1")
    stub = port_stub(drawing, "label", "CLK", "R1", "1")
    assert stub is not None and stub[0] == anchor
    (start, end) = stub
    assert start.y == end.y and end.x != start.x
    assert port_stub(drawing, "label", "CLK", "R1", "9") is None


# -- the tool ---------------------------------------------------------------------------------


def test_the_port_tool_on_a_pin_hands_over_the_port_and_its_wire_and_stays_armed() -> None:
    bus = _bus()
    view = _view(bus)
    told: list[tuple] = []
    view.portPlaced.connect(lambda *args: told.append(args))
    try:
        view.arm_port("ground", "GND")
        anchor = pin_position(view.item.drawing, "R1", "1")
        _click(view, anchor)
        ((kind, name, x, y, ref, pin, path),) = told
        stub = port_stub(view.item.drawing, "ground", "GND", "R1", "1")
        assert (kind, name, ref, pin) == ("ground", "GND", "R1", "1")
        assert (x, y) == (stub[-1].x, stub[-1].y)
        assert path == [(p.x, p.y) for p in stub]
        assert view.tool == "port"
        _dispatch_placed(bus, told[0])
        gnd = next(net for net in bus.document.nets if net.name == "GND")
        assert gnd.net_class == "ground" and NetNode("R1", "1") in gnd.nodes
    finally:
        view.close()
        view.deleteLater()


def test_the_port_tool_on_bare_sheet_puts_the_port_down_on_the_grid_with_no_wire() -> None:
    bus = _bus()
    view = _view(bus)
    told: list[tuple] = []
    view.portPlaced.connect(lambda *args: told.append(args))
    try:
        view.arm_port("supply", "+5V")
        where = Point2(x=100.0 + 0.4, y=80.0 - 0.3)
        _click(view, where)
        ((kind, name, x, y, ref, pin, path),) = told
        snapped = snap_to_grid(Point2(x=x, y=y))
        assert (kind, name, ref, pin, path) == ("supply", "+5V", "", "", [])
        assert (x, y) == (snapped.x, snapped.y)
        assert abs(x - where.x) <= G and abs(y - where.y) <= G
        _dispatch_placed(bus, told[0])
        assert not any(net.name == "+5V" for net in bus.document.nets)
        assert bus.document.sheet_ports[-1].links == ()
    finally:
        view.close()
        view.deleteLater()


def test_the_port_tool_shows_what_the_click_would_put_down_and_escape_puts_it_away() -> None:
    from PySide6.QtCore import QPointF, Qt

    from .test_ui import _send_mouse

    bus = _bus()
    view = _view(bus)
    try:
        view.arm_port("ground", "GND")
        anchor = pin_position(view.item.drawing, "R1", "1")
        _send_mouse(view, "move", view.mapFromScene(QPointF(anchor.x, anchor.y)))
        kind, name, _at, stub = view.item.port_ghost
        assert (kind, name) == ("ground", "GND")
        assert stub == port_stub(view.item.drawing, "ground", "GND", "R1", "1")
        _key(view, Qt.Key.Key_Escape)
        assert view.tool == "select" and view.item.port_ghost is None
    finally:
        view.close()
        view.deleteLater()


# -- a port on the sheet ------------------------------------------------------------------------


def test_a_port_is_selected_by_its_glyph_dragged_by_whole_squares_and_deleted() -> None:
    from PySide6.QtCore import QPointF, Qt

    bus = _bus()
    port = _with_ground(bus)
    view = _view(bus)
    moved: list[tuple] = []
    deleted: list[list] = []
    view.portMoved.connect(lambda *args: moved.append(args))
    view.portDeleteRequested.connect(lambda ids: deleted.append(ids))
    try:
        (placed,) = view.item.drawing.ports
        x0, y0, x1, y1 = placed.box
        middle = QPointF((x0 + x1) / 2, (y0 + y1) / 2)
        _click(view, middle)
        assert view.selected_ports == [port.id] and view.selected_refs == []
        _drag(view, middle, middle + QPointF(3 * G + 0.4, 2 * G - 0.3))
        ((id_, x, y),) = moved
        assert id_ == port.id
        assert (round(x - port.at.x, 6), round(y - port.at.y, 6)) == (round(3 * G, 6), round(2 * G, 6))
        assert view.item.port_drag is None and not view.gesture_in_flight()
        _key(view, Qt.Key.Key_Delete)
        assert deleted == [[port.id]]
    finally:
        view.close()
        view.deleteLater()


def test_a_click_on_a_symbol_lets_go_of_the_port() -> None:
    from PySide6.QtCore import QPointF

    bus = _bus()
    _with_ground(bus)
    view = _view(bus)
    try:
        (placed,) = view.item.drawing.ports
        x0, y0, x1, y1 = placed.box
        _click(view, QPointF((x0 + x1) / 2, (y0 + y1) / 2))
        symbol = next(s for s in view.item.drawing.symbols if s.ref == "R2")
        _click(view, QPointF(symbol.at.x + symbol.width / 2, symbol.at.y + symbol.height / 2))
        assert view.selected_ports == [] and view.selected_refs == ["R2"]
        assert view.item.selected_ports == frozenset()
    finally:
        view.close()
        view.deleteLater()


@pytest.mark.parametrize("pin_first", [True, False])
def test_connect_wires_a_pin_to_a_port_from_either_end(pin_first: bool) -> None:
    from perfboard_studio.commands import LinkSheetPortPayload

    bus = _bus()
    port = _with_ground(bus)
    view = _view(bus)
    told: list[tuple] = []
    view.portLinked.connect(lambda *args: told.append(args))
    try:
        view.set_tool("wire")
        anchor = pin_position(view.item.drawing, "R3", "1")
        (placed,) = view.item.drawing.ports
        glyph = Point2(x=(placed.box[0] + placed.box[2]) / 2, y=(placed.box[1] + placed.box[3]) / 2)
        for at in (anchor, glyph) if pin_first else (glyph, anchor):
            _click(view, at)
        ((id_, ref, pin, path),) = told
        assert (id_, ref, pin) == (port.id, "R3", "1")
        assert path[0] == (anchor.x, anchor.y) and path[-1] == (port.at.x, port.at.y)
        assert all(a[0] == b[0] or a[1] == b[1] for a, b in itertools.pairwise(path))
        assert not view.wire_in_progress()
        link = PortLink(pin=NetNode(ref, pin), path=tuple(Point2(x=x, y=y) for x, y in path))
        assert bus.dispatch("sheet.port.link", LinkSheetPortPayload(id=id_, link=link)).ok
        gnd = next(net for net in bus.document.nets if net.name == "GND")
        assert NetNode("R3", "1") in gnd.nodes
    finally:
        view.close()
        view.deleteLater()


def test_the_glyph_box_a_click_finds_is_the_one_the_sheet_clears() -> None:
    bus = _bus()
    _with_ground(bus)
    drawing = build_schematic(bus.document, LOOKUP)
    (rail,) = [rail for rail in drawing.rails if rail.port is not None]
    (placed,) = drawing.ports
    assert placed.box == rail_glyph_box(rail)


# -- the window ----------------------------------------------------------------------------------


def test_the_window_puts_a_port_down_in_one_undo_step_and_delete_disconnects_it() -> None:
    from PySide6.QtCore import Qt

    from .test_ui import _close, _window_on

    bus = _bus()
    window = _window_on(bus.document)
    try:
        window.show_schematic()
        view = window.schematic_view
        window.on_sheet_port("ground", "GND")
        assert view.tool == "port" and window.act_sheet_tool["port"].isChecked()
        assert window.act_sheet_tool["port"].text() == "GND"
        before = window.bus.system_document
        _click(view, pin_position(view.item.drawing, "R1", "1"))
        after = window.bus.system_document
        (port,) = after.sheet_ports
        assert port.links[0].pin == NetNode("R1", "1")
        assert any(net.name == "GND" and NetNode("R1", "1") in net.nodes for net in after.nets)
        window.bus.undo()
        assert window.bus.system_document == before
        window.bus.redo()
        placed = window.bus.system_document
        view.select_ports([port.id])
        _key(view, Qt.Key.Key_Delete)
        gone = window.bus.system_document
        assert gone.sheet_ports == ()
        # Disconnected, as a wire is on Delete and a power symbol is in KiCad: the pin
        # only the port held leaves ground, the status line says so, and one undo step
        # brings both back.
        assert not any(NetNode("R1", "1") in net.nodes for net in gone.nets)
        said = window.statusBar().currentMessage()
        assert "R1.1" in said and "Ctrl+Z" in said, said
        window.bus.undo()
        assert window.bus.system_document == placed
    finally:
        _close(window)
