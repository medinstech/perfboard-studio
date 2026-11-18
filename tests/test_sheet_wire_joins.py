"""A wire drawn between two pins on different nets joins the nets (``sheet.wire``), as a line
does on every schematic. It used to be refused -- "disconnect one of the pins first" -- so
once two pins were wired nothing more could be drawn between them, and the sheet read as
taking one connection to a point. Which net stays is ``commands._kept_of``; the join itself
is ``net.merge``'s, and so is the refusal for a supply and its ground."""

from __future__ import annotations

from perfboard_studio.commands import DrawSheetWirePayload, UpdateNetPayload
from perfboard_studio.model import NetNode, Point2, SheetWire

from .test_sheet_tee import _bus, _pin, _tee, _wire


def _two_nets():  # type: ignore[no-untyped-def]
    """R1.2-R2.1 wired, and R3.1-R4.1: two nets of two pins, both named automatically."""
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    _wire(bus, _pin("R3", "1"), _pin("R4", "1"))
    return bus


def _net_of(bus, node: NetNode):  # type: ignore[no-untyped-def]
    return next(net for net in bus.document.nets if node in net.nodes)


def _draw(bus, a: NetNode, b: NetNode):  # type: ignore[no-untyped-def]
    path = (Point2(x=0.0, y=0.0), Point2(x=5.0, y=0.0))
    return bus.dispatch("sheet.wire", DrawSheetWirePayload(wire=SheetWire(a=a, b=b, path=path)))


def _rename(bus, node: NetNode, name: str, net_class=None) -> None:  # type: ignore[no-untyped-def]
    net = _net_of(bus, node)
    result = bus.dispatch("net.update", UpdateNetPayload(id=net.id, name=name, net_class=net_class))
    assert result.ok, result.message


def test_a_wire_between_two_nets_joins_them_in_one_undo_step() -> None:
    bus = _two_nets()
    before = bus.document
    first, second = _net_of(bus, _pin("R2", "1")), _net_of(bus, _pin("R3", "1"))
    result = _draw(bus, _pin("R2", "1"), _pin("R3", "1"))
    assert result.ok, result.message
    # Two automatic names and two pins each: the net of the pin drawn TO stays.
    assert result.description == f"Wire R2.1 to R3.1, joining {first.name} into {second.name}"
    (net,) = bus.document.nets
    assert net.id == second.id and net.name == second.name
    assert {(n.component_ref, n.pin) for n in net.nodes} == {
        ("R1", "2"), ("R2", "1"), ("R3", "1"), ("R4", "1")
    }
    # All three lines are drawn: one net holds both ends of each.
    assert len(bus.document.sheet_wires) == 3
    assert bus.undo() and bus.document == before


def test_a_name_somebody_chose_stays_whichever_way_the_wire_is_drawn() -> None:
    for a, b in (("R2", "R3"), ("R3", "R2")):
        bus = _two_nets()
        _rename(bus, _pin("R1", "2"), "RESET")
        result = _draw(bus, _pin(a, "1"), _pin(b, "1"))
        assert result.ok, result.message
        (net,) = bus.document.nets
        assert net.name == "RESET"
        assert result.description.endswith("into RESET")


def test_a_ground_stays_over_a_signal() -> None:
    bus = _two_nets()
    _rename(bus, _pin("R3", "1"), "GND", "ground")
    assert _draw(bus, _pin("R3", "1"), _pin("R2", "1")).ok
    (net,) = bus.document.nets
    assert (net.name, net.net_class) == ("GND", "ground")


def test_a_supply_and_its_ground_are_still_refused() -> None:
    bus = _two_nets()
    _rename(bus, _pin("R1", "2"), "VCC", "power")
    _rename(bus, _pin("R3", "1"), "GND", "ground")
    before = bus.document
    result = _draw(bus, _pin("R2", "1"), _pin("R3", "1"))
    assert not result.ok and result.code == "two-supplies"
    assert bus.document is before


def test_a_t_onto_a_wire_of_another_net_joins_it_too() -> None:
    bus = _two_nets()
    _rename(bus, _pin("R1", "2"), "RESET")
    branch = _net_of(bus, _pin("R3", "1")).name
    result, _at = _tee(bus, _pin("R3", "1"), (_pin("R1", "2"), _pin("R2", "1")))
    assert result.ok, result.message
    assert result.description == (
        f"Wire R3.1 onto the wire from R1.2 to R2.1, joining {branch} into RESET"
    )
    (net,) = bus.document.nets
    assert net.name == "RESET" and len(net.nodes) == 4
