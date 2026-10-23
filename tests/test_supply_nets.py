"""A net joined at a supply pin is named after it (``commands.plan_pin_join``).

Drawing a 555 pin to pin made "N1" of its VCC and "N6" of its ground, both of the signal
class: the sheet drew no rail glyph, the guide wired them in no colour and the router laid no
ground first. What is pinned here: a new net takes a supply pin's name and class; a pin whose
name is already a net's joins that net instead of making a second; an automatically named net
takes the name when a supply pin joins it; two different supplies name nothing; and the
board's connect tool (``view2d.join_pins``) and the sheet's wire agree, each in one undo step.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from perfboard_studio.catalog import catalog_part
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    AddPartPayload,
    DrawSheetWirePayload,
    create_empty_document,
    create_standard_registry,
    plan_pin_join,
)
from perfboard_studio.model import (
    DocumentMeta,
    Net,
    NetNode,
    Point2,
    SheetWire,
    supply_net_class,
)

NE555_PINS = catalog_part("ne555").pin_names


def _pin(ref: str, pin: str) -> NetNode:
    return NetNode(component_ref=ref, pin=pin)


def _bus() -> CommandBus:
    """Two 555s, two resistors and a capacitor, in the design and on no board."""
    bus = CommandBus(
        create_empty_document(DocumentMeta(name="t", created="", modified="")),
        create_standard_registry(),
        CommandContext(next_id=create_id_generator()),
    )
    for ref in ("U1", "U2"):
        payload = AddPartPayload(ref=ref, footprint_id="dip-8", value="NE555", pin_names=NE555_PINS)
        assert bus.dispatch("part.add", payload).ok
    for ref, footprint in (("R1", "r-axial-3"), ("R2", "r-axial-3"), ("C1", "c-disc-p2")):
        assert bus.dispatch("part.add", AddPartPayload(ref=ref, footprint_id=footprint)).ok
    return bus


def _wire(bus: CommandBus, a: NetNode, b: NetNode) -> None:
    path = (Point2(x=0.0, y=0.0), Point2(x=10.0, y=0.0))
    result = bus.dispatch("sheet.wire", DrawSheetWirePayload(wire=SheetWire(a=a, b=b, path=path)))
    assert result.ok, result.message


def _net_of(bus: CommandBus, node: NetNode) -> Net:
    return next(net for net in bus.document.nets if node in net.nodes)


def test_a_supply_name_says_which_class_its_net_is() -> None:
    assert supply_net_class("GND") == "ground"
    assert supply_net_class("agnd") == "ground"
    assert supply_net_class("VCC") == "power"
    assert supply_net_class("V+") == "power"
    # Either, by the circuit: VSS is a CMOS chip's ground, V- and VEE are below it.
    assert supply_net_class("VSS") == "ground"
    assert supply_net_class("V-") == "power"
    assert supply_net_class("VEE") == "power"
    assert supply_net_class("TRIG") is None
    assert supply_net_class(None) is None


def test_a_wire_from_a_supply_pin_makes_the_net_it_names() -> None:
    bus = _bus()
    _wire(bus, _pin("U1", "8"), _pin("R1", "1"))
    _wire(bus, _pin("C1", "2"), _pin("U1", "1"))
    vcc, gnd = _net_of(bus, _pin("R1", "1")), _net_of(bus, _pin("C1", "2"))
    assert (vcc.name, vcc.net_class) == ("VCC", "power")
    assert (gnd.name, gnd.net_class) == ("GND", "ground")


def test_a_second_supply_pin_joins_the_net_of_its_name_rather_than_making_another() -> None:
    """A net and its name are one thing: never a "GND_2"."""
    bus = _bus()
    _wire(bus, _pin("U1", "1"), _pin("C1", "2"))
    nets = len(bus.document.nets)
    _wire(bus, _pin("R2", "2"), _pin("U2", "1"))
    assert len(bus.document.nets) == nets
    gnd = _net_of(bus, _pin("U2", "1"))
    assert gnd.name == "GND" and _pin("R2", "2") in gnd.nodes and _pin("U1", "1") in gnd.nodes


def test_an_automatic_net_takes_the_name_of_a_supply_pin_joining_it() -> None:
    """The order a circuit is drawn in does not decide what its ground is called."""
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("C1", "2"))
    assert _net_of(bus, _pin("C1", "2")).name == "N1"
    _wire(bus, _pin("C1", "2"), _pin("U1", "1"))
    gnd = _net_of(bus, _pin("U1", "1"))
    assert (gnd.name, gnd.net_class) == ("GND", "ground")
    assert len(bus.document.nets) == 1

    # ... but a name somebody gave the net is theirs, and a name already taken is not free.
    other = _bus()
    _wire(other, _pin("U1", "1"), _pin("C1", "1"))
    _wire(other, _pin("R1", "2"), _pin("R2", "2"))
    _wire(other, _pin("R2", "2"), _pin("U2", "1"))
    assert _net_of(other, _pin("U2", "1")).name == "N1"


def test_two_different_supplies_name_nothing() -> None:
    """VCC wired to GND is a short to be seen, not a net named after one end of it."""
    bus = _bus()
    plan = plan_pin_join(bus.document, _pin("U1", "8"), _pin("U1", "1"))
    assert (plan.kind, plan.name, plan.net_class) == ("create", "N1", "signal")


def test_the_board_connect_tool_names_nets_the_same_way_in_one_undo_step() -> None:
    from perfboard_studio.ui.view2d import join_pins

    bus = _bus()
    result, refusal = join_pins(bus, ("U1", "8"), ("R1", "1"))
    assert refusal is None and result is not None and result.ok
    vcc = _net_of(bus, _pin("R1", "1"))
    assert (vcc.name, vcc.net_class) == ("VCC", "power")

    result, _ = join_pins(bus, ("R2", "1"), ("C1", "1"))
    assert result is not None and result.ok
    before = len(bus.history())
    result, _ = join_pins(bus, ("U1", "1"), ("C1", "1"))
    assert result is not None and result.ok
    gnd = _net_of(bus, _pin("U1", "1"))
    assert (gnd.name, gnd.net_class) == ("GND", "ground")
    assert len(bus.history()) == before + 1
