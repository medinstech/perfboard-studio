"""Delete on a selected wire (``sheet.wire.cut``): the wire goes, and a pin that only it
joined leaves the net. The rules are the command's docstring; each is one test here."""

from __future__ import annotations

from perfboard_studio.commands import CutSheetWiresPayload

from .test_sheet_tee import _bus, _pin, _tee, _wire


def _nodes(bus) -> list[set[tuple[str, str]]]:
    return [{(n.component_ref, n.pin) for n in net.nodes} for net in bus.document.nets]


def _cut(bus, wire):
    return bus.dispatch("sheet.wire.cut", CutSheetWiresPayload(wires=(wire,)))


def test_cutting_the_only_wire_of_a_two_pin_net_takes_the_net_with_it() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    wire = bus.document.sheet_wires[0]
    assert _cut(bus, wire).ok
    assert bus.document.sheet_wires == () and bus.document.nets == ()
    bus.undo()
    assert len(bus.document.sheet_wires) == 1 and len(bus.document.nets) == 1


def test_a_pin_another_wire_still_joins_stays_and_the_other_leaves() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    _wire(bus, _pin("R2", "1"), _pin("R3", "1"))
    first = bus.document.sheet_wires[0]
    assert _cut(bus, first).ok
    assert _nodes(bus) == [{("R2", "1"), ("R3", "1")}]


def test_both_ends_joined_by_other_wires_leaves_the_net_whole() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    _wire(bus, _pin("R2", "1"), _pin("R3", "1"))
    _wire(bus, _pin("R3", "1"), _pin("R1", "2"))
    before = _nodes(bus)
    assert _cut(bus, bus.document.sheet_wires[0]).ok
    assert _nodes(bus) == before and len(bus.document.sheet_wires) == 2


def test_cutting_a_wire_takes_its_tees_and_the_pins_only_they_joined() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    assert _tee(bus, _pin("R3", "1"), (_pin("R1", "2"), _pin("R2", "1")))[0].ok
    host = next(w for w in bus.document.sheet_wires if w.tap is None)
    assert _cut(bus, host).ok
    assert bus.document.sheet_wires == () and bus.document.nets == ()


def test_a_pin_joined_by_name_only_is_never_touched() -> None:
    from perfboard_studio.commands import ConnectPinsPayload

    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    net = bus.document.nets[0]
    assert bus.dispatch("net.connect", ConnectPinsPayload(id=net.id, nodes=(_pin("R4", "1"),))).ok
    assert _cut(bus, bus.document.sheet_wires[0]).ok
    assert _nodes(bus) == [{("R4", "1")}]
