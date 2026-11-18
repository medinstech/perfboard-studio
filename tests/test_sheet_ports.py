"""A supply, a ground or a name somebody PUT on the sheet (``SheetPort``).

The netlist is still the circuit: a port names its net by name, linking a pin to one puts
the pin on that net, and a link is drawn only while its pin is on the net the port names.
Every command that takes a pin off a net takes its links with it, in the same step.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    AddNetPayload,
    AddPartPayload,
    AddSheetPortPayload,
    AutoSymbolsPayload,
    DeleteNetPayload,
    DeletePartPayload,
    DeleteSheetPortsPayload,
    DisconnectPinsPayload,
    LinkSheetPortPayload,
    MergeNetsPayload,
    MoveSheetPortPayload,
    MoveSymbolsPayload,
    UpdateNetPayload,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import (
    DocumentMeta,
    Net,
    NetNode,
    Point2,
    PortLink,
    SheetPortKind,
    SymbolPlacement,
    net_named,
)
from perfboard_studio.schematic import SchematicDrawing, build_schematic, pin_position

LOOKUP = footprint_lookup()


def _pin(ref: str, pin: str) -> NetNode:
    return NetNode(component_ref=ref, pin=pin)


def _bus() -> CommandBus:
    """R1 and R2 side by side, R3 below, every symbol placed by hand."""
    bus = CommandBus(
        create_empty_document(DocumentMeta(name="t", created="", modified="")),
        create_standard_registry(),
        CommandContext(next_id=create_id_generator()),
    )
    for ref in ("R1", "R2", "R3"):
        assert bus.dispatch("part.add", AddPartPayload(ref=ref, footprint_id="r-axial-3")).ok
    ids = {part.ref: part.id for part in bus.document.parts}
    where = {"R1": (20.32, 20.32), "R2": (60.96, 20.32), "R3": (35.56, 40.64)}
    placed = MoveSymbolsPayload(
        placements=tuple(
            SymbolPlacement(id=ids[ref], at=Point2(x=x, y=y)) for ref, (x, y) in where.items()
        )
    )
    assert bus.dispatch("symbol.move", placed).ok
    return bus


def _drawing(bus: CommandBus) -> SchematicDrawing:
    return build_schematic(bus.document, LOOKUP)


def _link(bus: CommandBus, pin: NetNode, at: Point2) -> PortLink:
    """A wire from ``pin`` to ``at``, down (or across) then along, as the tool draws it."""
    start = pin_position(_drawing(bus), pin.component_ref, pin.pin)
    assert start is not None
    if start.x == at.x or start.y == at.y:
        return PortLink(pin=pin, path=(start, at))
    return PortLink(pin=pin, path=(start, Point2(x=start.x, y=at.y), at))


def _put(
    bus: CommandBus, kind: SheetPortKind, name: str, pins: tuple[NetNode, ...], at: Point2
) -> str:
    links = tuple(_link(bus, pin, at) for pin in pins)
    result = bus.dispatch("sheet.port.add", AddSheetPortPayload(kind=kind, name=name, at=at, links=links))
    assert result.ok, result.message
    (port,) = [p for p in bus.document.sheet_ports if p.at == at]
    return port.id


def _net_of(bus: CommandBus, pin: NetNode) -> Net | None:
    return next((net for net in bus.document.nets if pin in net.nodes), None)


def _honest(bus: CommandBus) -> None:
    """Every link names its pin's actual net."""
    for port in bus.document.sheet_ports:
        net = net_named(bus.document.nets, port.name)
        for link in port.links:
            assert net is not None and link.pin in net.nodes, (port, link.pin)


GROUND_AT = Point2(x=20.32, y=35.56)
SUPPLY_AT = Point2(x=60.96, y=10.16)


# -- putting one down ------------------------------------------------------------------


def test_a_ground_put_on_a_pin_puts_the_pin_on_ground() -> None:
    bus = _bus()
    port = _put(bus, "ground", "GND", (_pin("R1", "2"),), GROUND_AT)
    net = _net_of(bus, _pin("R1", "2"))
    assert net is not None and net.name == "GND" and net.net_class == "ground"
    assert "GND" in bus.history()[-1]
    # One undo takes back the port and the connection together.
    assert bus.undo()
    assert bus.document.sheet_ports == () and _net_of(bus, _pin("R1", "2")) is None
    assert bus.redo()
    assert [p.id for p in bus.document.sheet_ports] == [port]


def test_a_second_ground_joins_the_same_net() -> None:
    bus = _bus()
    _put(bus, "ground", "GND", (_pin("R1", "2"),), GROUND_AT)
    _put(bus, "ground", "gnd ", (_pin("R2", "2"),), Point2(x=60.96, y=35.56))
    (net,) = bus.document.nets
    assert set(net.nodes) == {_pin("R1", "2"), _pin("R2", "2")}
    # Stored under the net's own spelling, whatever was typed.
    assert {p.name for p in bus.document.sheet_ports} == {"GND"}


def test_a_ground_on_a_pin_of_a_signal_names_that_net() -> None:
    bus = _bus()
    assert bus.dispatch(
        "net.add", AddNetPayload(name="N1", net_class="signal", nodes=(_pin("R1", "2"), _pin("R2", "1")))
    ).ok
    _put(bus, "ground", "GND", (_pin("R1", "2"),), GROUND_AT)
    (net,) = bus.document.nets
    assert net.name == "GND" and net.net_class == "ground"
    assert set(net.nodes) == {_pin("R1", "2"), _pin("R2", "1")}


def test_a_supply_and_a_ground_are_never_joined() -> None:
    bus = _bus()
    _put(bus, "ground", "GND", (_pin("R1", "2"),), GROUND_AT)
    _put(bus, "supply", "+5V", (_pin("R2", "1"),), SUPPLY_AT)
    before = bus.document
    link = _link(bus, _pin("R2", "1"), GROUND_AT)
    (ground,) = [p for p in bus.document.sheet_ports if p.kind == "ground"]
    result = bus.dispatch("sheet.port.link", LinkSheetPortPayload(id=ground.id, link=link))
    assert not result.ok
    assert bus.document is before


def test_a_label_does_not_make_a_ground_a_signal() -> None:
    bus = _bus()
    _put(bus, "ground", "GND", (_pin("R1", "2"),), GROUND_AT)
    result = bus.dispatch(
        "sheet.port.add",
        AddSheetPortPayload(
            kind="label", name="OUT", at=Point2(x=40.64, y=10.16),
            links=(_link(bus, _pin("R1", "2"), Point2(x=40.64, y=10.16)),),
        ),
    )
    assert not result.ok and result.code == "wrong-class"


def test_a_supply_cannot_name_a_ground_net() -> None:
    bus = _bus()
    assert bus.dispatch(
        "net.add", AddNetPayload(name="GND", net_class="ground", nodes=(_pin("R1", "2"),))
    ).ok
    result = bus.dispatch(
        "sheet.port.add", AddSheetPortPayload(kind="supply", name="GND", at=SUPPLY_AT)
    )
    assert not result.ok and result.code == "wrong-class"


def test_a_port_with_no_name_is_refused() -> None:
    bus = _bus()
    result = bus.dispatch("sheet.port.add", AddSheetPortPayload(kind="ground", name="  ", at=GROUND_AT))
    assert not result.ok


def test_a_diagonal_link_is_refused() -> None:
    bus = _bus()
    start = pin_position(_drawing(bus), "R1", "2")
    assert start is not None
    link = PortLink(pin=_pin("R1", "2"), path=(start, GROUND_AT))
    result = bus.dispatch(
        "sheet.port.add", AddSheetPortPayload(kind="ground", name="GND", at=GROUND_AT, links=(link,))
    )
    assert not result.ok


# -- the drawing -----------------------------------------------------------------------


def test_a_linked_pin_draws_no_glyph_of_its_own() -> None:
    bus = _bus()
    port = _put(bus, "ground", "GND", (_pin("R1", "2"), _pin("R2", "2")), GROUND_AT)
    drawing = _drawing(bus)
    grounds = [rail for rail in drawing.rails if rail.net_name == "GND"]
    # One glyph, the port's, with a wire from each pin to it -- not one more at each pin.
    assert [rail.port for rail in grounds] == [port]
    assert [p.id for p in drawing.ports] == [port]


def test_a_ground_with_one_link_is_drawn_with_the_link_for_its_stem() -> None:
    bus = _bus()
    _put(bus, "ground", "GND", (_pin("R1", "2"),), GROUND_AT)
    (rail,) = [rail for rail in _drawing(bus).rails if rail.net_name == "GND"]
    start = pin_position(_drawing(bus), "R1", "2")
    assert rail.path[0] == start and rail.path[-1] == GROUND_AT
    assert rail.direction == "down"


def test_a_supply_points_up() -> None:
    bus = _bus()
    _put(bus, "supply", "+5V", (_pin("R2", "1"),), SUPPLY_AT)
    (rail,) = [rail for rail in _drawing(bus).rails if rail.net_name == "+5V"]
    assert rail.direction == "up"


def test_a_moved_port_takes_its_wires_with_it() -> None:
    bus = _bus()
    port = _put(bus, "ground", "GND", (_pin("R1", "2"),), GROUND_AT)
    there = Point2(x=GROUND_AT.x, y=GROUND_AT.y + 5.08)
    assert bus.dispatch("sheet.port.move", MoveSheetPortPayload(id=port, at=there)).ok
    (rail,) = [rail for rail in _drawing(bus).rails if rail.port == port]
    assert rail.at == there and rail.path[-1] == there


def test_a_label_names_its_net_where_it_was_put_and_nowhere_else() -> None:
    bus = _bus()
    at = Point2(x=40.64, y=10.16)
    _put(bus, "label", "OUT", (_pin("R1", "2"),), at)
    _put(bus, "label", "OUT", (_pin("R2", "1"),), Point2(x=50.8, y=10.16))
    drawing = _drawing(bus)
    names = [label for label in drawing.labels if label.kind == "net" and label.text == "OUT"]
    assert len(names) == 2
    assert not [label for _, label in drawing.quiet_names if label.text == "OUT"]


# -- deleting one ----------------------------------------------------------------------


def test_deleting_a_port_keeps_the_connection_and_cutting_it_does_not() -> None:
    bus = _bus()
    port = _put(bus, "ground", "GND", (_pin("R1", "2"), _pin("R2", "2")), GROUND_AT)
    assert bus.dispatch("sheet.port.delete", DeleteSheetPortsPayload(ids=(port,))).ok
    assert bus.document.sheet_ports == ()
    net = _net_of(bus, _pin("R1", "2"))
    assert net is not None and net.name == "GND"
    # Each pin is drawn as any pin on ground nothing is wired at.
    assert [rail.port for rail in _drawing(bus).rails if rail.net_name == "GND"] == [None, None]

    assert bus.undo()
    assert bus.dispatch("sheet.port.delete", DeleteSheetPortsPayload(ids=(port,), cut=True)).ok
    assert _net_of(bus, _pin("R1", "2")) is None
    assert bus.document.nets == ()


def test_cutting_one_of_two_grounds_keeps_the_pins_the_other_holds() -> None:
    bus = _bus()
    first = _put(bus, "ground", "GND", (_pin("R1", "2"),), GROUND_AT)
    _put(bus, "ground", "GND", (_pin("R2", "2"),), Point2(x=60.96, y=35.56))
    assert bus.dispatch("sheet.port.delete", DeleteSheetPortsPayload(ids=(first,), cut=True)).ok
    (net,) = bus.document.nets
    assert set(net.nodes) == {_pin("R2", "2")}


# -- a link never outlives its pin's place on the net -----------------------------------


def _grounded() -> CommandBus:
    bus = _bus()
    _put(bus, "ground", "GND", (_pin("R1", "2"), _pin("R2", "2")), GROUND_AT)
    _put(bus, "supply", "+5V", (_pin("R2", "1"),), SUPPLY_AT)
    return bus


def _ground(bus: CommandBus) -> Net:
    net = net_named(bus.document.nets, "GND")
    assert net is not None
    return net


def _supply(bus: CommandBus) -> Net:
    net = net_named(bus.document.nets, "+5V")
    assert net is not None
    return net


TAKES_A_PIN_OFF: dict[str, Callable[[CommandBus], tuple[str, object]]] = {
    "net.disconnect": lambda bus: (
        "net.disconnect", DisconnectPinsPayload(id=_ground(bus).id, nodes=(_pin("R1", "2"),))
    ),
    "net.delete": lambda bus: ("net.delete", DeleteNetPayload(id=_ground(bus).id)),
    "part.delete": lambda bus: (
        "part.delete",
        DeletePartPayload(id=next(p.id for p in bus.document.parts if p.ref == "R1")),
    ),
    "net.merge": lambda bus: (
        "net.merge", MergeNetsPayload(id=_supply(bus).id, into=_ground(bus).id)
    ),
}


@pytest.mark.parametrize("name", sorted(TAKES_A_PIN_OFF))
def test_every_link_names_its_pins_net_after(name: str) -> None:
    bus = _grounded()
    _honest(bus)
    command, payload = TAKES_A_PIN_OFF[name](bus)
    result = bus.dispatch(command, payload)
    _honest(bus)
    if result.ok:
        assert bus.undo()
        _honest(bus)


def test_disconnecting_a_pin_drops_its_link_in_the_same_step() -> None:
    bus = _grounded()
    assert bus.dispatch(
        "net.disconnect", DisconnectPinsPayload(id=_ground(bus).id, nodes=(_pin("R1", "2"),))
    ).ok
    (ground,) = [p for p in bus.document.sheet_ports if p.kind == "ground"]
    assert [link.pin for link in ground.links] == [_pin("R2", "2")]
    # And one undo brings both back.
    assert bus.undo()
    (ground,) = [p for p in bus.document.sheet_ports if p.kind == "ground"]
    assert {link.pin for link in ground.links} == {_pin("R1", "2"), _pin("R2", "2")}


def test_renaming_a_net_carries_its_ports() -> None:
    bus = _grounded()
    assert bus.dispatch("net.update", UpdateNetPayload(id=_supply(bus).id, name="VCC")).ok
    (supply,) = [p for p in bus.document.sheet_ports if p.kind == "supply"]
    assert supply.name == "VCC" and [link.pin for link in supply.links] == [_pin("R2", "1")]
    _honest(bus)


def test_merging_a_net_carries_its_ports_to_the_name_it_keeps() -> None:
    bus = _bus()
    _put(bus, "label", "A", (_pin("R1", "2"),), Point2(x=40.64, y=10.16))
    _put(bus, "label", "B", (_pin("R2", "1"),), Point2(x=50.8, y=10.16))
    a = net_named(bus.document.nets, "A")
    b = net_named(bus.document.nets, "B")
    assert a is not None and b is not None
    assert bus.dispatch("net.merge", MergeNetsPayload(id=b.id, into=a.id)).ok
    assert {p.name for p in bus.document.sheet_ports} == {"A"}
    assert sum(len(p.links) for p in bus.document.sheet_ports) == 2
    _honest(bus)


def test_a_drawing_put_back_by_the_layout_has_no_ports() -> None:
    bus = _grounded()
    assert bus.dispatch("symbol.auto", AutoSymbolsPayload(ids=())).ok
    assert bus.document.sheet_ports == ()
    # The circuit is what it was.
    assert _ground(bus).nodes


# -- the file ----------------------------------------------------------------------------


def test_ports_round_trip_through_the_file() -> None:
    bus = _grounded()
    text = persist.serialize_document(bus.document)
    assert '"sheetPorts"' in text
    loaded = persist.deserialize_document(text)
    assert loaded.ok
    assert loaded.document.sheet_ports == tuple(sorted(bus.document.sheet_ports, key=lambda p: p.id))
    assert persist.serialize_document(loaded.document) == text


def test_a_document_with_no_ports_says_nothing_about_them() -> None:
    assert '"sheetPorts"' not in persist.serialize_document(_bus().document)


def test_a_link_off_its_net_loads_with_a_warning() -> None:
    bus = _grounded()
    ground = _ground(bus)
    doc = dataclasses.replace(
        bus.document,
        nets=tuple(
            dataclasses.replace(net, nodes=tuple(n for n in net.nodes if n != _pin("R1", "2")))
            if net.id == ground.id else net
            for net in bus.document.nets
        ),
    )
    loaded = persist.deserialize_document(persist.serialize_document(doc))
    assert loaded.ok
    assert any("R1.2 is not on GND" in w for w in loaded.warnings)
    # And it is never drawn as if it joined them: no line of the ground's reaches R1.2,
    # while R2.2's link, still true, is the glyph's stem.
    drawing = build_schematic(loaded.document, LOOKUP)
    r1 = pin_position(drawing, "R1", "2")
    r2 = pin_position(drawing, "R2", "2")
    (rail,) = [r for r in drawing.rails if r.net_name == "GND"]
    assert rail.port is not None and rail.path[0] == r2
    lines = [rail.path, *(w.path for w in drawing.wires if w.net_name == "GND")]
    assert all(r1 not in path for path in lines)


def test_a_port_of_no_kind_is_refused_at_load() -> None:
    text = persist.serialize_document(_grounded().document).replace('"kind": "ground"', '"kind": "earth"')
    result = persist.deserialize_document(text)
    assert not result.ok and result.code == "sheet-port-kind-invalid"
