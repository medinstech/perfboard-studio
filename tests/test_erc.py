"""ERC: whether the circuit is right, before anybody asks whether the board is.

Every rule here is about a circuit nobody has placed: the parts are in the DESIGN and the
board is empty, because that is when the check is worth most -- before a board is bought.
One test holds that a part on the board is judged exactly as one in the design, so nothing
below is weaker for leaving the board out. The parts come from the catalog, which is where
the pin names these rules read come from in practice.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import get_args

import pytest

from perfboard_studio.catalog import catalog_part, search_catalog
from perfboard_studio.commands import create_empty_document
from perfboard_studio.erc import (
    KIND_BY_ARCHETYPE,
    RULES,
    SEVERITY,
    ErcFinding,
    run_erc,
    supply_kind,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.guide import GuideOptions, build_guide
from perfboard_studio.model import (
    BodyArchetype,
    ComponentInstance,
    DocumentMeta,
    HoleCoord,
    Net,
    NetClass,
    NetNode,
    PerfDocument,
    SchematicPart,
)
from perfboard_studio.parsers.kicad import infer_net_class
from perfboard_studio.persist import parse_document_or_throw

ROOT = Path(__file__).resolve().parents[1]
LOOKUP = footprint_lookup()
META = DocumentMeta(name="erc", created="", modified="")


def cat(ref: str, catalog_id: str) -> SchematicPart:
    """A catalog part in the design, exactly as Add Part puts one there."""
    entry = catalog_part(catalog_id)
    assert entry is not None, catalog_id
    return SchematicPart(
        id=f"id-{ref}",
        ref=ref,
        value=entry.placed_value,
        footprint_id=entry.footprint_id,
        pin_names=entry.pin_names,
        symbol=entry.symbol,
    )


def plain(ref: str, footprint_id: str, **fields: object) -> SchematicPart:
    return SchematicPart(id=f"id-{ref}", ref=ref, value=ref, footprint_id=footprint_id, **fields)  # type: ignore[arg-type]


def circuit(
    parts: list[SchematicPart],
    nets: dict[str, tuple[str, ...]],
    classes: dict[str, NetClass] | None = None,
    **net_fields: dict[str, object],
) -> PerfDocument:
    """Parts and nets written as ``{"VCC": ("U1.8", "C1.1")}``; a net's class is the one the
    window gives a net of that name unless ``classes`` says otherwise."""
    built: list[Net] = []
    for index, (name, pins) in enumerate(nets.items()):
        nodes = tuple(NetNode(*pin.split(".")) for pin in pins)
        net_class = (classes or {}).get(name, infer_net_class(name))
        built.append(Net(id=f"n{index}", name=name, nodes=nodes, net_class=net_class))
    return dataclasses.replace(
        create_empty_document(META), parts=tuple(parts), nets=tuple(built)
    )


def checked(
    doc: PerfDocument, lookup=LOOKUP, *, power_entry: bool = False  # type: ignore[no-untyped-def]
) -> tuple[ErcFinding, ...]:
    """``run_erc``, without ``no-power-entry`` unless a test asks for it.

    Every circuit in this file is drawn without a connector, and that rule says so -- rightly
    -- about every one that names a supply. A test about another rule reads the rest; the
    rule's own tests pass ``power_entry=True``, and the shipped examples are held to ALL the
    rules in ``test_no_shipped_example_has_a_finding``.
    """
    return tuple(
        finding
        for finding in run_erc(doc, lookup)
        if power_entry or finding.rule != "no-power-entry"
    )


def rules(doc: PerfDocument) -> list[tuple[str, tuple[str, ...]]]:
    """Each finding as (rule, the pins it names), which is what a test asserts on."""
    return [(f.rule, tuple(f"{p.component_ref}.{p.pin}" for p in f.pins)) for f in checked(doc)]


# ---------------------------------------------------------------------------
# Completeness, and the boards that ship
# ---------------------------------------------------------------------------


def test_every_archetype_says_what_kind_of_part_it_is() -> None:
    assert set(KIND_BY_ARCHETYPE) == set(get_args(BodyArchetype))


def test_every_rule_has_a_severity_and_errors_come_first() -> None:
    assert set(SEVERITY) == set(RULES)
    severities = [SEVERITY[rule] for rule in RULES]
    assert severities == sorted(severities)  # "error" < "warning"


def test_no_shipped_example_has_a_finding() -> None:
    """The examples were built and checked by hand; a rule that fired on one would be a rule
    arguing with a working circuit."""
    for path in sorted((ROOT / "examples").rglob("*.perf")):
        doc = parse_document_or_throw(path.read_text(encoding="utf-8"))
        assert run_erc(doc, LOOKUP) == (), path.name


def test_the_catalog_s_supply_pins_are_exactly_the_ones_named_as_supplies() -> None:
    """Measured over every pin name the catalog has. VP and VN on an ESP32 are GPIOs, VIN,
    VBUS and 3V3 on a module may be outputs, and none of them is a chip's supply. V+ and V-
    are a split-supply op-amp's rails and VS the LM386's; VBAT on a DS1307 is a coin cell it
    can run without, and VREF on an ADC is the scale it measures against."""
    found: dict[str, set[str]] = {}
    for entry in search_catalog(""):
        for _, name in entry.pin_names:
            kind = supply_kind(name)
            if kind is not None:
                found.setdefault(kind, set()).add(name)
    assert found == {
        "positive": {"VCC", "VCC1", "VCC2", "VDD", "AVCC", "+VS", "V+", "VS"},
        "ground": {"GND", "AGND", "DGND"},
        "negative": {"VSS", "V-"},
    }


def test_a_document_with_no_nets_is_not_checked_part_by_part() -> None:
    """Parts and nothing joining them is a circuit not started, not twelve findings."""
    doc = circuit([cat("U1", "ne555"), plain("R1", "r-axial-4")], {})
    assert checked(doc, LOOKUP) == ()


def test_a_part_on_the_board_is_judged_as_one_in_the_design() -> None:
    designed = circuit([cat("U1", "ne555"), plain("R1", "r-axial-4")], {"OUT": ("U1.3", "R1.1")})
    part = designed.parts[0]
    placed = dataclasses.replace(
        designed,
        parts=designed.parts[1:],
        components=(
            ComponentInstance(
                id=part.id,
                ref=part.ref,
                value=part.value,
                footprint_id=part.footprint_id,
                anchor=HoleCoord(3, 3),
                pin_names=part.pin_names,
            ),
        ),
    )
    assert rules(placed) == rules(designed) != []


# ---------------------------------------------------------------------------
# Supplies
# ---------------------------------------------------------------------------


def test_a_chip_with_its_supply_unwired_cannot_work() -> None:
    parts = [cat("U1", "ne555"), plain("R1", "r-axial-4"), plain("C1", "c-disc-p2")]
    doc = circuit(parts, {"OUT": ("U1.3", "R1.1"), "GND": ("U1.1", "C1.2")})
    findings = checked(doc, LOOKUP)
    assert [(f.rule, f.severity, f.pins) for f in findings] == [
        ("supply-unconnected", "error", (NetNode("U1", "8"),))
    ]
    assert findings[0].message == "U1 pin 8 (VCC) is connected to nothing, so the chip is not powered."
    assert findings[0].refs == ("U1",)

    powered = circuit(parts, {"OUT": ("U1.3", "R1.1"), "GND": ("U1.1", "C1.2"), "VCC": ("U1.8", "C1.1")})
    assert checked(powered, LOOKUP) == ()


def test_a_chip_nobody_has_wired_yet_is_one_warning_and_not_a_list_of_errors() -> None:
    """While a circuit is being drawn most chips are not wired at all. Its supplies are not
    news then; that it is connected to nothing is."""
    doc = circuit([cat("U1", "ne555"), plain("R1", "r-axial-4"), plain("R2", "r-axial-4")], {"A": ("R1.2", "R2.1")})
    assert rules(doc) == [("part-unconnected", ())]


def test_a_supply_alone_on_its_net_is_not_a_supply() -> None:
    """A power label put on one pin and spelled differently on the other is the commonest way
    a chip ends up unpowered on a sheet that LOOKS wired."""
    parts = [cat("U1", "ne555"), plain("R1", "r-axial-4"), plain("C1", "c-disc-p2")]
    doc = circuit(
        parts,
        {"OUT": ("U1.3", "R1.1"), "GND": ("U1.1", "C1.2"), "VCC": ("U1.8",), "Vcc": ("C1.1",)},
    )
    assert rules(doc) == [
        ("supply-unconnected", ("U1.8",)),
        ("single-pin-net", ("U1.8",)),
        ("single-pin-net", ("C1.1",)),
    ]


def test_one_of_two_ground_pins_left_open_is_a_warning() -> None:
    """An ATmega328 has GND on 8 and 22, and both are meant to be wired."""
    parts = [cat("U1", "atmega328p"), plain("C1", "c-disc-p2"), plain("C2", "c-disc-p2")]
    doc = circuit(parts, {"+5V": ("U1.7", "U1.20", "C1.1"), "GND": ("U1.8", "C1.2"), "RST": ("U1.1", "C2.1")})
    findings = checked(doc, LOOKUP)
    assert [(f.rule, f.severity, f.pins) for f in findings] == [
        ("supply-pin-open", "warning", (NetNode("U1", "22"),))
    ]
    assert "while pin 8 (GND) is" in findings[0].message


def test_every_supply_by_its_own_name_and_avcc_is_one_of_them() -> None:
    parts = [cat("U1", "atmega328p"), plain("C1", "c-disc-p2")]
    doc = circuit(parts, {"+5V": ("U1.7", "C1.1"), "GND": ("U1.8", "U1.22", "C1.2")})
    assert rules(doc) == [("supply-unconnected", ("U1.20",))]


def test_a_module_needs_its_ground_and_nothing_else() -> None:
    """A Nano's VIN, 5V and 3V3 can each be the one it is powered by or one it powers
    something else from -- and two GND pins are one ground on its own board."""
    parts = [cat("A1", "arduino-nano"), plain("R1", "r-axial-4"), plain("LED1", "led-5mm")]
    grounded = circuit(parts, {"D2": ("A1.9", "R1.1"), "GND": ("A1.4", "LED1.2")})
    assert checked(grounded, LOOKUP) == ()

    floating = circuit(parts, {"D2": ("A1.9", "R1.1"), "K": ("R1.2", "LED1.2")})
    findings = checked(floating, LOOKUP)
    assert [(f.rule, f.pins) for f in findings] == [
        ("supply-unconnected", (NetNode("A1", "4"), NetNode("A1", "7")))
    ]
    assert findings[0].message == (
        "A1 pins 4 and 7 (GND) are connected to nothing, so the module shares no ground with "
        "the rest of the circuit."
    )


def test_a_regulator_needs_its_input_and_an_lm317_its_adj() -> None:
    parts = [cat("U1", "7805"), plain("C1", "c-disc-p2"), plain("C2", "c-disc-p2")]
    doc = circuit(parts, {"GND": ("U1.2", "C1.2", "C2.2"), "+5V": ("U1.3", "C2.1")})
    findings = checked(doc, LOOKUP)
    assert [f.message for f in findings] == [
        "U1 pin 1 (IN) is connected to nothing, so the regulator has no input."
    ]

    parts = [cat("U2", "lm317t"), plain("C1", "c-disc-p2"), plain("C2", "c-disc-p2")]
    doc = circuit(parts, {"VIN": ("U2.3", "C1.1"), "VOUT": ("U2.2", "C2.1")})
    assert [f.message for f in checked(doc, LOOKUP)] == [
        "U2 pin 1 (ADJ) is connected to nothing, so its output is not regulated."
    ]


def test_in_is_a_supply_only_on_a_regulator() -> None:
    """On a ULN2003 the inputs are IN1..IN7, and on a block somebody described with VCC, GND,
    IN and OUT the IN is a signal. Neither is a regulator's input."""
    box = plain(
        "U1",
        "box-4x1-p1-r1-12x5x10",
        pin_names=(("1", "VCC"), ("2", "GND"), ("3", "IN"), ("4", "OUT")),
    )
    doc = circuit([box, plain("R1", "r-axial-4")], {"+5V": ("U1.1", "R1.1"), "GND": ("U1.2", "R1.2")})
    assert checked(doc, LOOKUP) == ()
    # ...and it IS checked as a chip: its own GND left open is found.
    doc = circuit([box, plain("R1", "r-axial-4")], {"+5V": ("U1.1", "R1.1"), "S": ("U1.3", "R1.2")})
    assert rules(doc) == [("supply-unconnected", ("U1.2",))]


# ---------------------------------------------------------------------------
# Drawn in backwards
# ---------------------------------------------------------------------------


def test_a_chip_drawn_in_backwards_is_on_the_wrong_rails() -> None:
    parts = [cat("U1", "ne555"), plain("C1", "c-disc-p2")]
    doc = circuit(parts, {"+5V": ("U1.1", "C1.1"), "GND": ("U1.8", "C1.2")})
    assert [f.message for f in checked(doc, LOOKUP)] == [
        "U1 pin 1 (GND) is on +5V, a power net: its ground is connected to a supply.",
        "U1 pin 8 (VCC) is on GND, a ground net: its supply is connected to ground.",
    ]


def test_a_part_with_its_supplies_tied_together_is_left_alone() -> None:
    """A DS18B20 in parasite mode has VDD on ground, as its datasheet says to."""
    parts = [cat("U1", "ds18b20"), plain("R1", "r-axial-4")]
    doc = circuit(parts, {"GND": ("U1.1", "U1.3", "R1.2"), "DQ": ("U1.2", "R1.1")})
    assert checked(doc, LOOKUP) == ()


def test_an_electrolytic_in_backwards() -> None:
    parts = [plain("C1", "c-elec-d5-p2"), plain("R1", "r-axial-4")]
    doc = circuit(parts, {"+5V": ("C1.2", "R1.1"), "GND": ("C1.1", "R1.2")})
    findings = checked(doc, LOOKUP)
    assert [(f.rule, f.severity) for f in findings] == [("polarity-reversed", "error")]
    assert findings[0].message == (
        "C1's + lead (pin 1) is on GND, a ground net, and its - lead (pin 2) on +5V, a "
        "supply: it is drawn the wrong way round."
    )
    assert findings[0].net_ids == ("n1", "n0")


def test_on_a_negative_rail_the_plus_on_ground_is_right() -> None:
    """KiCad's import calls -12V a power net, and a decoupling cap on it has its + on ground.
    So does a rail declared negative by its voltage, whatever it is called."""
    parts = [plain("C1", "c-elec-d5-p2"), plain("R1", "r-axial-4")]
    doc = circuit(parts, {"-12V": ("C1.2", "R1.1"), "GND": ("C1.1", "R1.2")})
    assert checked(doc, LOOKUP) == ()
    declared = dataclasses.replace(
        doc,
        nets=(dataclasses.replace(doc.nets[0], name="RAIL", net_class="power", voltage_v=-9.0), doc.nets[1]),
    )
    assert checked(declared, LOOKUP) == ()


def test_an_led_in_backwards_never_lights_and_a_clamp_diode_is_not_backwards() -> None:
    parts = [plain("LED1", "led-5mm"), plain("R1", "r-axial-4")]
    doc = circuit(parts, {"+5V": ("LED1.2", "R1.1"), "GND": ("LED1.1", "R1.2")})
    assert [f.message for f in checked(doc, LOOKUP)] == [
        "LED1's anode (pin 1) is on GND, a ground net, and its cathode (pin 2) on +5V, a "
        "supply: it is drawn the wrong way round and will never light."
    ]

    clamp = [cat("D1", "1n4148"), plain("R1", "r-axial-4")]
    doc = circuit(clamp, {"+5V": ("D1.1", "R1.1"), "GND": ("D1.2", "R1.2")})
    assert checked(doc, LOOKUP) == ()


# ---------------------------------------------------------------------------
# NC pins, and nets that name what is not there
# ---------------------------------------------------------------------------


def test_a_wired_nc_pin_is_a_warning_on_a_sensor() -> None:
    """Pin 3 of a DHT11 is NC; a data wire on it is the wire meant for pin 2."""
    parts = [cat("U1", "dht11"), plain("R1", "r-axial-4")]
    doc = circuit(parts, {"+5V": ("U1.1", "R1.1"), "DATA": ("U1.3", "R1.2"), "GND": ("U1.4", "R1.2")})
    found = rules(doc)
    assert ("nc-pin-connected", ("U1.3",)) in found


def test_nc_on_a_terminal_or_a_relay_module_is_a_contact() -> None:
    """On the relay terminal of nano-relay NC is the normally-closed contact (that board is
    held clean above); on a module carrying COM, NO and NC, so is it."""
    module = plain(
        "K1",
        "box-6x1-p1-r1-30x15x18",
        pin_names=(("1", "VCC"), ("2", "GND"), ("3", "IN"), ("4", "COM"), ("5", "NO"), ("6", "NC")),
    )
    nets = {"+5V": ("K1.1", "K1.3"), "GND": ("K1.2", "J1.2"), "LOAD": ("K1.6", "J1.1")}
    doc = circuit([module, plain("J1", "screw-terminal-2")], nets)
    assert checked(doc, LOOKUP) == ()
    # The same pin on the same block with no contacts beside it IS an absence.
    sensor = dataclasses.replace(module, pin_names=(*module.pin_names[:3], ("6", "NC")))
    doc = circuit([sensor, plain("J1", "screw-terminal-2")], nets)
    assert rules(doc) == [("nc-pin-connected", ("K1.6",))]


def test_a_net_naming_a_pin_the_part_lacks_and_a_part_nobody_has() -> None:
    """Neither joins anything: U1's only wire goes to a pin it does not have, so U1 is
    connected to nothing, and R2's goes to a part nobody has."""
    parts = [cat("U1", "ne555"), plain("R1", "r-axial-4"), plain("R2", "r-axial-4")]
    doc = circuit(parts, {"X": ("U1.9", "R1.1"), "Y": ("R2.1", "Q7.1"), "Z": ("R1.2", "R2.2")})
    found = checked(doc, LOOKUP)
    assert [(f.rule, f.severity, f.message) for f in found if f.rule.startswith(("pin-", "part-"))] == [
        ("pin-not-on-part", "error", "X names U1 pin 9, which dip-8 does not have."),
        ("part-unconnected", "warning", "U1 is connected to nothing: no pin of it is on a net with another pin."),
        ("part-not-defined", "warning", "Y names Q7, which is neither on the board nor in the design."),
    ]


def test_a_finding_is_plain_data_about_named_pins() -> None:
    parts = [cat("U1", "ne555"), plain("R1", "r-axial-4")]
    doc = circuit(parts, {"OUT": ("U1.3", "R1.1"), "GND": ("U1.1", "R1.2")})
    for finding in checked(doc, LOOKUP):
        assert isinstance(finding, ErcFinding)
        assert finding.rule in RULES and finding.severity == SEVERITY[finding.rule]
        assert finding.refs and finding.pins


def test_the_guide_says_it_is_building_a_circuit_with_an_error_in_it() -> None:
    """LVS passes a board that faithfully reproduces an unpowered chip, so nothing else in
    the guide would mention it -- and the guide is what sends somebody to the iron."""
    parts = [cat("U1", "ne555"), plain("R1", "r-axial-4"), plain("C1", "c-disc-p2")]
    doc = circuit(parts, {"OUT": ("U1.3", "R1.1"), "GND": ("U1.1", "C1.2")})
    english = build_guide(doc, LOOKUP)
    warning = next(w for w in english.warnings if w.code == "erc-error")
    assert warning.message.startswith("1 error(s) in the circuit itself (U1) — a chip or a module")
    turkish = build_guide(doc, LOOKUP, GuideOptions(language="tr"))
    warning = next(w for w in turkish.warnings if w.code == "erc-error")
    assert warning.message.startswith("Devrenin kendisinde 1 hata var (U1) — ")

    powered = circuit(parts, {"OUT": ("U1.3", "R1.1"), "GND": ("U1.1", "C1.2"), "VCC": ("U1.8", "C1.1")})
    assert "erc-error" not in {w.code for w in build_guide(powered, LOOKUP).warnings}


@pytest.mark.parametrize("name", ["GND", "gnd", " GND ", "AGND", "PGND", "GND2", "0V"])
def test_ground_is_ground_however_it_is_written(name: str) -> None:
    assert supply_kind(name) == "ground"


@pytest.mark.parametrize("name", ["VIN", "VBUS", "3V3", "+5V", "VP", "VN", "VE", "VO", "VREF", "VMOT", "IN", ""])
def test_these_are_not_supplies_a_chip_must_be_given(name: str) -> None:
    assert supply_kind(name) is None


# ---------------------------------------------------------------------------
# no-power-entry
# ---------------------------------------------------------------------------


def _blinker(*extra: SchematicPart, **nets: tuple[str, ...]) -> PerfDocument:
    """A 555 blinker drawn pin to pin -- VCC, GND and the timing -- plus ``extra``."""
    parts = [cat("U1", "ne555"), plain("R1", "r-axial-4"), plain("C1", "c-elec-d5-p2"), *extra]
    wired = {
        "VCC": ("U1.8", "U1.4", "R1.1"),
        "GND": ("U1.1", "C1.2"),
        "THR": ("U1.6", "U1.2", "C1.1"),
        "DIS": ("U1.7", "R1.2"),
    }
    for name, pins in nets.items():
        wired[name] = (*wired.get(name, ()), *pins)
    return circuit(list(parts), wired)


def test_a_circuit_with_nothing_to_bring_power_in_is_told_so() -> None:
    """The blinker of the round-1 walkthrough: VCC and GND joined, no battery clip and no
    terminal anywhere, and every check passed. One warning, ringed on the chip's supply."""
    (finding,) = checked(_blinker(), power_entry=True)
    assert (finding.rule, finding.severity) == ("no-power-entry", "warning")
    assert finding.pins == (NetNode("U1", "8"),)
    assert finding.refs == ("U1",)
    assert finding.message == (
        "Nothing brings power onto the board: no connector, terminal, battery clip or module "
        "is wired to VCC and GND. Wire one to the supply and to ground."
    )


def test_any_connector_or_module_on_a_supply_net_brings_power_in() -> None:
    """A terminal, a header, a battery clip's pads or a devkit: whatever is wired to a
    supply net is the way in. Whether it reaches both rails is not judged."""
    for extra, where in (
        (plain("J1", "screw-terminal-2"), {"VCC": ("J1.1",), "GND": ("J1.2",)}),
        (plain("J1", "hdr-1x2"), {"GND": ("J1.2",)}),
        (cat("BT1", "battery-9v-clip"), {"VCC": ("BT1.1",), "GND": ("BT1.2",)}),
        (cat("A1", "arduino-nano"), {"GND": ("A1.29",)}),
    ):
        doc = _blinker(extra, **where)
        assert [f for f in checked(doc, power_entry=True) if f.rule == "no-power-entry"] == [], extra.ref


def test_a_terminal_on_a_regulators_input_is_a_way_in() -> None:
    """Power comes in through a 7805: the terminal is on IN, the chips on OUT. Nothing about
    the topology is judged, so a connector on any supply net -- IN included -- is enough."""
    doc = _blinker(
        cat("U2", "7805"),
        plain("J1", "screw-terminal-2"),
        VIN=("J1.1", "U2.1"),
        GND=("J1.2", "U2.2"),
        VCC=("U2.3",),
    )
    assert [f.rule for f in checked(doc, power_entry=True)] == []


def test_nothing_is_said_where_no_supply_is_named() -> None:
    """Two resistors and an LED on signal nets: nothing in it names a supply, so there is
    nothing to judge, and nothing is said."""
    doc = circuit(
        [plain("R1", "r-axial-4"), plain("R2", "r-axial-4"), plain("D1", "led-5mm")],
        {"A": ("R1.2", "D1.1"), "B": ("D1.2", "R2.1")},
    )
    assert [f.rule for f in checked(doc, power_entry=True)] == []


def test_a_long_list_of_supplies_is_cut_short() -> None:
    doc = circuit(
        [cat("U1", "ne555"), plain("R1", "r-axial-4"), plain("R2", "r-axial-4"),
         plain("R3", "r-axial-4"), plain("R4", "r-axial-4")],
        {"VCC": ("U1.8", "R1.1"), "GND": ("U1.1", "R1.2"), "+5V": ("R2.1", "R3.1"),
         "+12V": ("R3.2", "R4.1"), "GNDA": ("R4.2", "R2.2")},
    )
    (finding,) = checked(doc, power_entry=True)
    assert "is wired to VCC, GND, +5V and 2 more." in finding.message
