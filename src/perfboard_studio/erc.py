"""ERC -- whether the CIRCUIT is right, before anybody asks whether the board is.

THE GAP THIS CLOSES. Everything else that checks anything looks at the board. DRC asks
whether the board can be built and LVS asks whether the board is the circuit -- and
neither can ask whether the circuit is any good, because to both of them the netlist is
the truth. An NE555 drawn with its VCC pin connected to nothing passes LVS perfectly: the
board faithfully reproduces a circuit in which the chip has no supply, the guide walks
somebody through soldering it, and the first thing anybody learns about the mistake is a
dead board. Drawing the circuit in this application, rather than importing it from a tool
that ran its own checks, is what made that the commonest mistake there is room for.

WHAT IT KNOWS IS ONLY WHAT THE DOCUMENT SAYS. Every rule reads pin NAMES --
``model.pin_name_of``, the part's declared name first and the footprint's second -- so a
part placed from the catalog, an LED (A, K) or an electrolytic (+, -) is checked, and a DIP
whose pins nobody named is not: an unnamed pin 8 is not a VCC pin to anything here. That is
deliberate rather than a gap to fill from the catalog by the part's value. Nothing in a
document refers back to ``catalog.py`` (its docstring says why), and a check that did would
give a different answer about the same file on a machine whose catalog is a release older.

ERRORS ARE CIRCUITS THAT CANNOT WORK AS DRAWN; WARNINGS ARE CIRCUITS THAT PROBABLY DO NOT.
An error stops the circuit step reading as done (``ui/workflow.py``) and the guide says it
is building a circuit with one, so an error has to be something nobody does on purpose:

- ``supply-unconnected`` -- a chip with a supply pin connected to nothing while the rest of
  it is wired; for a module, no ground pin at all (its 3V3 or 5V may be an output it does
  not need to be given, and pins of one name are joined on the module's own board).
- ``supply-on-wrong-net`` -- a VCC on a ground net, or a GND on a power net: a part drawn in
  backwards. A part whose supply pins are tied TOGETHER is exempt, because that is a
  datasheet configuration rather than a mistake (a DS18B20 in parasite mode has its VDD on
  ground).
- ``polarity-reversed`` -- an electrolytic with its + on ground and its - on a supply, or an
  LED with its anode on ground and its cathode on a supply. Not a diode: a diode from ground
  to a rail is a clamp, and that is how half of them are used. And not on a NEGATIVE rail,
  where the + on ground is exactly right (``is_negative_rail``; KiCad's import classes
  ``-12V`` and ``VEE`` as power, so the class alone would be wrong here).
- ``pin-not-on-part`` -- a net naming a pin the footprint does not have. The connection
  cannot be made by anybody.

and the warnings:

- ``supply-pin-open`` -- one of several pins of a chip's supply connected to nothing while
  another is: an ATmega328's second GND.
- ``nc-pin-connected`` -- a pin the part calls NC is wired, which is how a wire meant for
  the pin beside it shows up. Not on a connector, a relay or anything with NO and COM pins,
  where NC is a normally-closed contact (the relay terminal on ``nano-relay`` is one).
- ``single-pin-net`` -- a net that reaches one pin and so connects nothing; a label spelled
  differently on the pin it was meant for is the usual cause.
- ``part-unconnected`` -- a part no pin of which shares a net with any other pin.
- ``part-not-defined`` -- a net naming a reference that is neither on the board nor in the
  design. A warning, because a netlist handed to the MCP server is read before its parts
  are added, and ``commands.assert_pins_free`` calls that a perfectly good document.

"CONNECTED" MEANS ON A NET WITH ANOTHER PIN THAT EXISTS. A VCC pin alone on a net called
VCC is connected to nothing, and is both a single-pin net and an unpowered chip.

Pure and deterministic, like ``drc`` and ``lvs``: findings come out in ``RULES`` order and,
within a rule, in document order. The board, the copper and the sheet's geometry are never
read, so a design with nothing placed is checked exactly as a finished board is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .connectivity import FootprintLookup
from .model import (
    BodyArchetype,
    ComponentInstance,
    Footprint,
    Net,
    NetId,
    NetNode,
    PerfDocument,
    SchematicPart,
    SupplyKind,
    is_negative_rail,
    pin_name_of,
    supply_kind,
)

type ErcSeverity = Literal["error", "warning"]

#: Every rule, in the order findings are reported: the errors first, the circuit's
#: mistakes before its loose ends.
RULES: tuple[str, ...] = (
    "supply-unconnected",
    "supply-on-wrong-net",
    "polarity-reversed",
    "pin-not-on-part",
    "supply-pin-open",
    "nc-pin-connected",
    "single-pin-net",
    "part-unconnected",
    "part-not-defined",
)

SEVERITY: dict[str, ErcSeverity] = {
    "supply-unconnected": "error",
    "supply-on-wrong-net": "error",
    "polarity-reversed": "error",
    "pin-not-on-part": "error",
    "supply-pin-open": "warning",
    "nc-pin-connected": "warning",
    "single-pin-net": "warning",
    "part-unconnected": "warning",
    "part-not-defined": "warning",
}


@dataclass(frozen=True, slots=True)
class ErcFinding:
    """One thing wrong with the circuit, named down to the pin."""

    #: Stable, kebab-case, one of ``RULES``.
    rule: str
    severity: ErcSeverity
    #: English, like every engine message (CLAUDE.md, "i18n").
    message: str
    #: The parts it is about, by reference -- a finding may be about a part that is not on
    #: the board, which has no component id to give.
    refs: tuple[str, ...] = ()
    pins: tuple[NetNode, ...] = ()
    net_ids: tuple[NetId, ...] = ()


# ---------------------------------------------------------------------------
# What a part is, for these rules
# ---------------------------------------------------------------------------

#: How these rules treat a package. ``chip``: every supply pin it has is needed.
#: ``module``: a board of its own -- pins of one name are joined on it, and only its ground
#: must be shared. ``connector``: passive, any pin may be a spare, and an NC on one is as
#: likely a contact as an absence. ``passive``: no supply of its own.
type PartKind = Literal["chip", "module", "connector", "passive"]

#: Every archetype, because a test holds this to ``BodyArchetype``: a new one has to say
#: which it is rather than be checked as whatever the default would have been.
KIND_BY_ARCHETYPE: dict[BodyArchetype, PartKind] = {
    "axial-cylinder": "passive",
    "radial-electrolytic": "passive",
    "disc-ceramic": "passive",
    "box-film": "passive",
    "dip": "chip",
    "to92": "chip",
    "to220": "chip",
    "led-round": "passive",
    "pin-header": "connector",
    "screw-terminal": "connector",
    "potentiometer": "passive",
    "tactile-switch": "passive",
    "crystal-hc49": "passive",
    "relay-box": "passive",
    # A part somebody described by its pin grid -- a sensor, a module nobody stocks. If it
    # names a pin VCC it means it.
    "generic-box": "chip",
    "box-header": "connector",
    "screw-terminal-vertical": "connector",
    "module-board": "module",
    # A part on the panel, seen from the board as the pads its wires land in.
    "flying-leads": "connector",
    "smd-adapter": "chip",
    # A resistor or a diode, standing or lying: two leads and no supply.
    "axial-upright": "passive",
}

#: Names a pin with nothing inside it is given.
_NO_CONNECT = frozenset({"NC", "N.C.", "N/C", "DNC"})
#: Names that make NC a contact rather than an absence: a relay's set, a switch's.
_CONTACT = frozenset({"NO", "COM"})

#: The three-terminal regulators, by their pins' names: IN is the supply on these and
#: nowhere else (on a module or a custom block "IN" is as often a signal), and ADJ left open
#: is a regulator with nothing to regulate to.
_REGULATOR_SHAPES: tuple[frozenset[str], ...] = (
    frozenset({"IN", "OUT", "GND"}),
    frozenset({"IN", "OUT", "ADJ"}),
)


def _is_positive_rail(net: Net) -> bool:
    return net.net_class == "power" and not is_negative_rail(net)


def _upper(name: str | None) -> str:
    return (name or "").strip().upper()


def _pins_phrase(numbers: list[str]) -> str:
    """"pin 8", "pins 8 and 22", "pins 4, 5, 12 and 13"."""
    if len(numbers) == 1:
        return f"pin {numbers[0]}"
    return f"pins {', '.join(numbers[:-1])} and {numbers[-1]}"


def _is_are(count: int) -> str:
    return "is" if count == 1 else "are"


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

type _Part = ComponentInstance | SchematicPart


@dataclass(frozen=True, slots=True)
class _Pin:
    number: str
    name: str | None


@dataclass(slots=True)
class _Circuit:
    """The document as these rules read it: parts by reference, and who is joined to whom."""

    parts: dict[str, _Part]
    footprints: dict[str, Footprint | None]
    #: The net each pin is on, if any.
    net_of: dict[tuple[str, str], Net]
    #: Each net's pins that EXIST -- a reference something defines, a pin its footprint has.
    real_nodes: dict[NetId, tuple[NetNode, ...]]
    findings: dict[str, list[ErcFinding]] = field(
        default_factory=lambda: {rule: [] for rule in RULES}
    )

    def exists(self, node: NetNode) -> bool:
        if node.component_ref not in self.parts:
            return False
        footprint = self.footprints[node.component_ref]
        # With no footprint there is nothing to say which pins exist; DRC and LVS report
        # the unknown footprint, and this takes the netlist's word for the pin.
        return footprint is None or any(pin.number == node.pin for pin in footprint.pins)

    def joined(self, ref: str, number: str) -> Net | None:
        """The net this pin is on, if that net reaches another pin that exists."""
        net = self.net_of.get((ref, number))
        if net is None or len(self.real_nodes[net.id]) < 2:
            return None
        return net

    def report(
        self,
        rule: str,
        message: str,
        *,
        refs: tuple[str, ...] = (),
        pins: tuple[NetNode, ...] = (),
        nets: tuple[Net, ...] = (),
    ) -> None:
        self.findings[rule].append(
            ErcFinding(
                rule=rule,
                severity=SEVERITY[rule],
                message=message,
                refs=refs,
                pins=pins,
                net_ids=tuple(net.id for net in nets),
            )
        )


def run_erc(doc: PerfDocument, lookup: FootprintLookup) -> tuple[ErcFinding, ...]:
    """Every finding about the circuit, errors first."""
    parts: dict[str, _Part] = {}
    everything: tuple[_Part, ...] = (*doc.components, *doc.parts)
    for part in everything:
        parts.setdefault(part.ref, part)
    circuit = _Circuit(
        parts=parts,
        footprints={ref: lookup(part.footprint_id) for ref, part in parts.items()},
        net_of={},
        real_nodes={},
    )
    for net in doc.nets:
        unique = tuple(dict.fromkeys(net.nodes))
        circuit.real_nodes[net.id] = tuple(node for node in unique if circuit.exists(node))
        for node in unique:
            circuit.net_of.setdefault((node.component_ref, node.pin), net)

    for net in doc.nets:
        _check_net(circuit, net)

    anything_joined = any(len(nodes) >= 2 for nodes in circuit.real_nodes.values())
    for ref, part in parts.items():
        footprint = circuit.footprints[ref]
        if footprint is None:
            continue
        pins = tuple(_Pin(pin.number, pin_name_of(part, pin)) for pin in footprint.pins)
        if not any(circuit.joined(ref, pin.number) for pin in pins):
            if anything_joined:
                circuit.report(
                    "part-unconnected",
                    f"{ref} is connected to nothing: no pin of it is on a net with another "
                    f"pin.",
                    refs=(ref,),
                )
            continue
        kind = KIND_BY_ARCHETYPE[footprint.body.archetype]
        if kind == "module":
            _check_module_ground(circuit, ref, pins)
        elif kind == "chip":
            _check_chip_supplies(circuit, ref, pins)
        _check_wrong_net(circuit, ref, pins)
        _check_polarity(circuit, ref, part, footprint, pins)
        if kind != "connector":
            _check_no_connect(circuit, ref, footprint, pins)

    return tuple(finding for rule in RULES for finding in circuit.findings[rule])


def _check_net(circuit: _Circuit, net: Net) -> None:
    """``part-not-defined``, ``pin-not-on-part`` and ``single-pin-net``."""
    for node in dict.fromkeys(net.nodes):
        if node.component_ref not in circuit.parts:
            circuit.report(
                "part-not-defined",
                f"{net.name} names {node.component_ref}, which is neither on the board nor "
                f"in the design.",
                refs=(node.component_ref,),
                pins=(node,),
                nets=(net,),
            )
            continue
        footprint = circuit.footprints[node.component_ref]
        if footprint is not None and not circuit.exists(node):
            circuit.report(
                "pin-not-on-part",
                f"{net.name} names {node.component_ref} pin {node.pin}, which {footprint.id} "
                f"does not have.",
                refs=(node.component_ref,),
                pins=(node,),
                nets=(net,),
            )
    real = circuit.real_nodes[net.id]
    if not net.nodes:
        circuit.report("single-pin-net", f"{net.name} reaches no pin at all.", nets=(net,))
    elif len(real) == 1:
        only = real[0]
        circuit.report(
            "single-pin-net",
            f"{net.name} reaches only {only.component_ref} pin {only.pin}, so it connects "
            f"nothing. A label spelled differently on the pin it was meant for is the usual "
            f"cause.",
            refs=(only.component_ref,),
            pins=(only,),
            nets=(net,),
        )


def _check_module_ground(circuit: _Circuit, ref: str, pins: tuple[_Pin, ...]) -> None:
    """A module with something wired and none of its ground: ``supply-unconnected``."""
    grounds = [pin for pin in pins if supply_kind(pin.name) == "ground"]
    if not grounds or any(circuit.joined(ref, pin.number) for pin in grounds):
        return
    numbers = [pin.number for pin in grounds]
    names = "/".join(sorted({pin.name or "" for pin in grounds}))
    circuit.report(
        "supply-unconnected",
        f"{ref} {_pins_phrase(numbers)} ({names}) {_is_are(len(numbers))} connected to "
        f"nothing, so the module shares no ground with the rest of the circuit.",
        refs=(ref,),
        pins=tuple(NetNode(ref, number) for number in numbers),
    )


def _check_chip_supplies(circuit: _Circuit, ref: str, pins: tuple[_Pin, ...]) -> None:
    """``supply-unconnected`` for a supply with no pin wired, ``supply-pin-open`` for one
    pin of a supply that has others wired."""
    regulator = frozenset(_upper(pin.name) for pin in pins) in _REGULATOR_SHAPES
    by_name: dict[str, list[_Pin]] = {}
    for pin in pins:
        upper = _upper(pin.name)
        if supply_kind(pin.name) is not None or (regulator and upper in {"IN", "ADJ"}):
            by_name.setdefault(upper, []).append(pin)

    for upper, group in by_name.items():
        name = group[0].name or upper
        open_pins = [pin.number for pin in group if circuit.joined(ref, pin.number) is None]
        if not open_pins:
            continue
        if len(open_pins) == len(group):
            consequence = {
                "positive": "so the chip is not powered",
                "ground": "so the chip has no ground",
                "negative": "so the chip has no supply",
            }.get(
                supply_kind(name) or "",
                "so its output is not regulated"
                if upper == "ADJ"
                else "so the regulator has no input",
            )
            circuit.report(
                "supply-unconnected",
                f"{ref} {_pins_phrase(open_pins)} ({name}) {_is_are(len(open_pins))} "
                f"connected to nothing, {consequence}.",
                refs=(ref,),
                pins=tuple(NetNode(ref, number) for number in open_pins),
            )
            continue
        wired = [pin.number for pin in group if pin.number not in open_pins]
        for number in open_pins:
            circuit.report(
                "supply-pin-open",
                f"{ref} pin {number} ({name}) is connected to nothing, while "
                f"{_pins_phrase(wired)} ({name}) {_is_are(len(wired))}. Every supply pin of "
                f"a chip is meant to be connected.",
                refs=(ref,),
                pins=(NetNode(ref, number),),
            )


def _check_wrong_net(circuit: _Circuit, ref: str, pins: tuple[_Pin, ...]) -> None:
    """``supply-on-wrong-net``: a supply pin on a net of the opposite class."""
    placed: list[tuple[_Pin, SupplyKind, Net]] = []
    for pin in pins:
        kind = supply_kind(pin.name)
        net = circuit.joined(ref, pin.number)
        if kind is not None and net is not None:
            placed.append((pin, kind, net))
    # A part whose positive and ground or negative pins share a net is tied off on purpose
    # -- parasite power, an unused gate held down -- not a part drawn in backwards.
    positive = {net.id for _, kind, net in placed if kind == "positive"}
    other = {net.id for _, kind, net in placed if kind != "positive"}
    if positive & other:
        return
    for pin, kind, net in placed:
        if kind == "positive" and net.net_class == "ground":
            where, what = "a ground net", "its supply is connected to ground"
        elif kind == "ground" and net.net_class == "power":
            where, what = "a power net", "its ground is connected to a supply"
        else:
            continue
        circuit.report(
            "supply-on-wrong-net",
            f"{ref} pin {pin.number} ({pin.name}) is on {net.name}, {where}: {what}.",
            refs=(ref,),
            pins=(NetNode(ref, pin.number),),
            nets=(net,),
        )


def _check_polarity(
    circuit: _Circuit, ref: str, part: _Part, footprint: Footprint, pins: tuple[_Pin, ...]
) -> None:
    """``polarity-reversed``: the positive lead on ground and the negative on a supply."""
    by_name = {_upper(pin.name): pin for pin in pins}
    if len(pins) == 2 and "+" in by_name and "-" in by_name:
        positive, negative = by_name["+"], by_name["-"]
        words = ("+ lead", "- lead", "")
    elif (footprint.body.archetype == "led-round" or part.symbol == "led") and (
        "A" in by_name and "K" in by_name
    ):
        positive, negative = by_name["A"], by_name["K"]
        words = ("anode", "cathode", " and will never light")
    else:
        return
    up, down = circuit.joined(ref, positive.number), circuit.joined(ref, negative.number)
    if up is None or down is None:
        return
    if up.net_class == "ground" and _is_positive_rail(down):
        circuit.report(
            "polarity-reversed",
            f"{ref}'s {words[0]} (pin {positive.number}) is on {up.name}, a ground net, and "
            f"its {words[1]} (pin {negative.number}) on {down.name}, a supply: it is drawn "
            f"the wrong way round{words[2]}.",
            refs=(ref,),
            pins=(NetNode(ref, positive.number), NetNode(ref, negative.number)),
            nets=(up, down),
        )


def _check_no_connect(
    circuit: _Circuit, ref: str, footprint: Footprint, pins: tuple[_Pin, ...]
) -> None:
    """``nc-pin-connected``: a pin with nothing inside it, wired."""
    if footprint.body.archetype == "relay-box":
        return
    if {_upper(pin.name) for pin in pins} & _CONTACT:
        return
    for pin in pins:
        if _upper(pin.name) not in _NO_CONNECT:
            continue
        net = circuit.joined(ref, pin.number)
        if net is None:
            continue
        circuit.report(
            "nc-pin-connected",
            f"{ref} pin {pin.number} ({pin.name}) is on {net.name}, but the part has nothing "
            f"inside on that pin. Check whether the wire was meant for a pin beside it.",
            refs=(ref,),
            pins=(NetNode(ref, pin.number),),
            nets=(net,),
        )
