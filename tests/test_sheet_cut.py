"""Delete on a selected wire (``sheet.wire.cut``): the wire goes, and a pin that only it
joined leaves the net. The rules are the command's docstring; each is one test here."""

from __future__ import annotations

import itertools

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


# -- a net whose every pin is a wire end is split where the cut leaves it in two ---------


def _chain(bus, *pins):
    """One net drawn as a chain of wires, pin to pin, renamed GND with a class and a current
    so the split can be seen to copy them."""
    from perfboard_studio.commands import UpdateNetPayload

    for a, b in itertools.pairwise(pins):
        _wire(bus, a, b)
    (net,) = bus.document.nets
    update = UpdateNetPayload(id=net.id, name="GND", net_class="ground", current_a=0.5)
    assert bus.dispatch("net.update", update).ok


def _wire_between(bus, a, b):
    return next(w for w in bus.document.sheet_wires if {w.a, w.b} == {a, b})


def test_cutting_the_middle_of_a_fully_wired_chain_splits_the_net_in_two() -> None:
    bus = _bus()
    _chain(bus, _pin("R1", "1"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1"))
    gnd = bus.document.nets[0]
    assert _cut(bus, _wire_between(bus, _pin("R2", "1"), _pin("R3", "1"))).ok
    kept, new = bus.document.nets
    # Two pieces of two: the name stays with the piece holding the net's first pin.
    assert (kept.id, kept.name) == (gnd.id, "GND")
    assert {(n.component_ref, n.pin) for n in kept.nodes} == {("R1", "1"), ("R2", "1")}
    assert {(n.component_ref, n.pin) for n in new.nodes} == {("R3", "1"), ("R4", "1")}
    assert new.id != gnd.id and new.name == "N1"
    assert (new.net_class, new.current_a) == ("ground", 0.5)
    bus.undo()
    assert bus.document.nets == (gnd,) and len(bus.document.sheet_wires) == 3


def test_the_larger_piece_keeps_the_name_wherever_the_first_pin_went() -> None:
    bus = _bus()
    _chain(
        bus, _pin("R1", "1"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1"), _pin("R4", "2")
    )
    assert _cut(bus, _wire_between(bus, _pin("R2", "1"), _pin("R3", "1"))).ok
    kept, new = bus.document.nets
    assert kept.name == "GND" and len(kept.nodes) == 3
    assert {(n.component_ref, n.pin) for n in new.nodes} == {("R1", "1"), ("R2", "1")}


def test_no_wire_is_left_on_two_nets_after_a_split() -> None:
    bus = _bus()
    _chain(bus, _pin("R1", "1"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1"))
    assert _tee(bus, _pin("R4", "2"), (_pin("R3", "1"), _pin("R4", "1")))[0].ok
    assert _cut(bus, _wire_between(bus, _pin("R2", "1"), _pin("R3", "1"))).ok
    doc = bus.document
    for wire in doc.sheet_wires:
        assert any(wire.a in n.nodes and wire.b in n.nodes for n in doc.nets), wire
    # The T rode along with the wire it lands on.
    assert {(n.component_ref, n.pin) for n in doc.nets[0].nodes} == {
        ("R3", "1"), ("R4", "1"), ("R4", "2")
    }


def test_a_pin_joined_by_name_keeps_a_cut_chain_one_net() -> None:
    from perfboard_studio.commands import ConnectPinsPayload

    bus = _bus()
    _chain(bus, _pin("R1", "1"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1"))
    net = bus.document.nets[0]
    assert bus.dispatch("net.connect", ConnectPinsPayload(id=net.id, nodes=(_pin("R4", "2"),))).ok
    assert _cut(bus, _wire_between(bus, _pin("R2", "1"), _pin("R3", "1"))).ok
    (whole,) = bus.document.nets
    assert len(whole.nodes) == 5


def test_a_loop_cut_once_stays_one_net() -> None:
    bus = _bus()
    _chain(bus, _pin("R1", "1"), _pin("R2", "1"), _pin("R3", "1"), _pin("R1", "1"))
    assert _cut(bus, _wire_between(bus, _pin("R2", "1"), _pin("R3", "1"))).ok
    (net,) = bus.document.nets
    assert net.name == "GND" and len(net.nodes) == 3
