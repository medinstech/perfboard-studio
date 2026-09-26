"""What a KiCad netlist's components are, on a perfboard (``parsers.kicad_parts``).

What is pinned: a KiCad footprint name is read for the package it measures; a value names a
catalog part when its package agrees; a netlist's pin numbers are renumbered to the real
part's where the names say they differ -- KiCad's LED (pin 1 = K), a generic EBC transistor
given a BC547's value -- and left alone where the names cannot settle it; and an import,
from the window or over MCP, places each part with its value and names beside what it
connects to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from perfboard_studio.commands import create_empty_document
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.mcp.session import BoardSession, new_board
from perfboard_studio.model import DocumentMeta
from perfboard_studio.parsers.kicad import parse_kicad_netlist
from perfboard_studio.parsers.kicad_parts import (
    catalog_part_for,
    kicad_footprint_ids,
    pin_renumbering,
    plan_import,
)

LOOKUP = footprint_lookup()


def _first(kicad_footprint: str) -> str | None:
    ids, _note = kicad_footprint_ids(kicad_footprint)
    return next((fid for fid in ids if LOOKUP(fid) is not None), None)


@pytest.mark.parametrize(
    ("kicad", "expected"),
    [
        ("Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", "r-axial-4"),
        ("Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal", "r-axial-3"),
        ("Resistor_THT:R_Axial_DIN0414_L11.9mm_D4.5mm_P20.32mm_Horizontal", "axial-8h-11.9x4.5"),
        ("Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal", "d-do41"),
        ("Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal", "d-do35"),
        ("Diode_THT:D_DO-201AD_P15.24mm_Horizontal", "axial-6h-9.5x5.3-pol"),
        ("Capacitor_THT:CP_Radial_D6.3mm_P2.50mm", "c-elec-d6.3-p1-h11"),
        ("Capacitor_THT:CP_Radial_D5.0mm_P2.00mm", "c-elec-d5-p1-h11"),
        ("Capacitor_THT:CP_Radial_D10.0mm_P5.00mm", "c-elec-d10-p2-h12.5"),
        ("Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm", "c-disc-d5-p2-t2.5"),
        ("Capacitor_THT:C_Rect_L7.2mm_W2.5mm_P5.00mm_FKS2_FKP2_MKS2_MKP2", "c-film-7.2x2.5x5-p2"),
        ("Package_DIP:DIP-8_W7.62mm", "dip-8"),
        ("Package_DIP:DIP-16_W7.62mm_Socket", "dip-16"),
        ("Package_DIP:DIP-40_W15.24mm", "dip-40-wide"),
        ("Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", "hdr-1x4"),
        ("Connector_PinSocket_2.54mm:PinSocket_2x08_P2.54mm_Vertical", "hdr-2x8"),
        ("Connector_IDC:IDC-Header_2x05_P2.54mm_Vertical", "idc-2x5"),
        (
            "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
            "screw-terminal-2",
        ),
        (
            "TerminalBlock_Phoenix:PhoenixContact_MSTBVA_2,5_3-G-5,08_1x03_P5.08mm_Vertical",
            "screw-terminal-3-v",
        ),
        ("TerminalBlock:TerminalBlock_bornier-4_P5.08mm", "screw-terminal-4"),
        ("LED_THT:LED_D5.0mm", "led-5mm"),
        ("LED_THT:LED_D3.0mm_Clear", "led-3mm"),
        ("Package_TO_SOT_THT:TO-92_Inline", "to92"),
        ("Package_TO_SOT_THT:TO-220-3_Vertical", "to220"),
        ("Crystal:Crystal_HC49-4H_Vertical", "xtal-hc49"),
        ("Button_Switch_THT:SW_PUSH_6mm", "sw-tactile-6x6"),
        ("Button_Switch_THT:SW_PUSH_6mm_H5mm", "sw-tactile-6x6"),
        ("Button_Switch_THT:SW_PUSH-12mm_Wuerth-430476085716", "sw-tactile-12x12"),
    ],
)
def test_a_kicad_footprint_name_is_read_for_its_package(kicad: str, expected: str) -> None:
    assert _first(kicad) == expected


@pytest.mark.parametrize(
    ("kicad", "says"),
    [
        ("Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "surface-mount"),
        ("Resistor_SMD:R_0805_2012Metric", "surface-mount"),
        ("Relay_THT:Relay_SPDT_SANYOU_SRD_Series_Form_C", "relay"),
        ("Button_Switch_THT:SW_PUSH_1P1T_6x3.5mm_H4.3_APEM_MJTP1243", "push button"),
        ("Module:Arduino_Nano", "module"),
        ("Package_TO_SOT_THT:TO-220-3_Horizontal_TabDown", "upright"),
        ("Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P2.54mm_Vertical", "laid flat"),
    ],
)
def test_what_is_not_mapped_says_why(kicad: str, says: str) -> None:
    ids, note = kicad_footprint_ids(kicad)
    assert ids == [] and says in note


def test_an_unknown_name_maps_to_nothing_and_says_nothing() -> None:
    assert kicad_footprint_ids("MyLibrary:WeirdThing") == ([], "")


@pytest.mark.parametrize(
    ("value", "lib_part", "expected"),
    [
        ("BC547B", None, "bc547"),
        ("NE555P", None, "ne555"),
        ("L7805CV", None, "7805"),
        ("LM7805", None, "7805"),
        ("1N4007", None, "1n4007"),
        ("IRF9540NPBF", None, "irf9540n"),
        ("ATmega328P-PU", None, "atmega328p"),
        ("", "Timer:NE555P", "ne555"),
        ("LM350T", None, None),  # an LM350 is not an LM35
        ("10k", None, None),
        ("100nF", None, None),
        ("LED", None, None),
    ],
)
def test_a_value_names_a_catalog_part(value: str, lib_part: str | None, expected: str | None) -> None:
    part = catalog_part_for(value, lib_part)
    assert (part.id if part else None) == expected


def test_names_renumber_only_when_they_settle_it() -> None:
    led = (("1", "A"), ("2", "K"))
    assert pin_renumbering((("1", "K"), ("2", "A")), led, {"1", "2"}) == {"1": "2", "2": "1"}
    assert pin_renumbering((("1", "A"), ("2", "K")), led, {"1", "2"}) == {}
    # A name on two pins of the part is one node on it -- a module's two GNDs -- so either
    # will do, and it is the first.
    assert pin_renumbering((("1", "GND"),), (("1", "X"), ("4", "GND"), ("8", "GND")), {"1"}) == {
        "1": "4"
    }
    # A name the schematic has more of than the part does is not settled.
    assert pin_renumbering((("1", "GND"), ("2", "GND")), (("4", "GND"),), {"1", "2"}) == {}
    # Moving pin 1 onto pin 3 while the schematic still uses pin 3 as itself would join them.
    assert pin_renumbering((("1", "C"),), (("3", "C"),), {"1", "3"}) == {}


# ------------------------------------------------------------------- a whole netlist

NETLIST = """(export (version "E")
  (design (source "t.kicad_sch") (tool "Eeschema 8.0.4"))
  (components
    (comp (ref "Q1") (value "BC547")
      (footprint "Package_TO_SOT_THT:TO-92_Inline")
      (libsource (lib "Device") (part "Q_NPN_EBC")))
    (comp (ref "Q2") (value "2N5088")
      (footprint "Package_TO_SOT_THT:TO-92_Inline")
      (libsource (lib "Device") (part "Q_NPN_EBC")))
    (comp (ref "D1") (value "RED")
      (footprint "LED_THT:LED_D5.0mm") (libsource (lib "Device") (part "LED")))
    (comp (ref "D2") (value "GREEN")
      (footprint "LED_THT:LED_D3.0mm") (libsource (lib "Device") (part "LED")))
    (comp (ref "U1") (value "NE555P")
      (footprint "Package_DIP:DIP-8_W7.62mm") (libsource (lib "Timer") (part "NE555P")))
    (comp (ref "U2") (value "L7805")
      (footprint "Package_TO_SOT_THT:TO-220-3_Vertical")
      (libsource (lib "Regulator_Linear") (part "L7805")))
    (comp (ref "U3") (value "LM358")
      (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
      (libsource (lib "Amplifier_Operational") (part "LM358")))
    (comp (ref "C1") (value "100u")
      (footprint "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm")
      (libsource (lib "Device") (part "C_Polarized")))
    (comp (ref "R1") (value "4k7")
      (footprint "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal")
      (libsource (lib "Device") (part "R")))
    (comp (ref "K1") (value "SRD-05VDC")
      (footprint "Relay_THT:Relay_SPDT_SANYOU_SRD_Series_Form_C")
      (libsource (lib "Relay") (part "SANYOU_SRD_Form_C")))
    (comp (ref "J1") (value "PWR")
      (footprint "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical")
      (libsource (lib "Connector_Generic") (part "Conn_01x02"))))
  (nets
    (net (code "1") (name "GND")
      (node (ref "Q1") (pin "1") (pinfunction "E") (pintype "passive"))
      (node (ref "Q2") (pin "1") (pinfunction "E") (pintype "passive"))
      (node (ref "D1") (pin "1") (pinfunction "K") (pintype "passive"))
      (node (ref "D2") (pin "1"))
      (node (ref "U1") (pin "1") (pinfunction "GND") (pintype "power_in"))
      (node (ref "U2") (pin "2") (pinfunction "GND") (pintype "power_in"))
      (node (ref "U3") (pin "4") (pinfunction "V-") (pintype "power_in"))
      (node (ref "C1") (pin "2") (pinfunction "~") (pintype "passive"))
      (node (ref "K1") (pin "2"))
      (node (ref "J1") (pin "2") (pinfunction "Pin_2") (pintype "passive")))
    (net (code "2") (name "COLL")
      (node (ref "Q1") (pin "3") (pinfunction "C") (pintype "passive"))
      (node (ref "Q2") (pin "3") (pinfunction "C") (pintype "passive"))
      (node (ref "K1") (pin "1"))
      (node (ref "R1") (pin "1") (pinfunction "~") (pintype "passive")))
    (net (code "3") (name "BASE")
      (node (ref "Q1") (pin "2") (pinfunction "B") (pintype "input"))
      (node (ref "Q2") (pin "2") (pinfunction "B") (pintype "input"))
      (node (ref "U1") (pin "3") (pinfunction "Q") (pintype "output")))
    (net (code "4") (name "+5V")
      (node (ref "U2") (pin "3") (pinfunction "VO") (pintype "power_out"))
      (node (ref "U1") (pin "8") (pinfunction "VCC") (pintype "power_in"))
      (node (ref "U3") (pin "8") (pinfunction "V+") (pintype "power_in"))
      (node (ref "D1") (pin "2") (pinfunction "A") (pintype "passive"))
      (node (ref "D2") (pin "2"))
      (node (ref "R1") (pin "2") (pinfunction "~") (pintype "passive"))
      (node (ref "C1") (pin "1") (pinfunction "+") (pintype "passive")))
    (net (code "5") (name "VIN")
      (node (ref "U2") (pin "1") (pinfunction "VI") (pintype "power_in"))
      (node (ref "J1") (pin "1") (pinfunction "Pin_1") (pintype "passive")))))
"""


def _plan():
    imported = parse_kicad_netlist(NETLIST)
    document = create_empty_document(DocumentMeta(name="t", created="", modified=""))
    return plan_import(imported, document, LOOKUP)


def _pins(plan, net_name: str) -> set[tuple[str, str]]:
    net = next(n for n in plan.nets if n.name == net_name)
    return {(node.component_ref, node.pin) for node in net.nodes}


def test_the_parser_keeps_what_each_pin_is_called() -> None:
    imported = parse_kicad_netlist(NETLIST)
    q1 = next(c for c in imported.components if c.ref == "Q1")
    assert q1.pin_functions == (("1", "E"), ("2", "B"), ("3", "C"))
    d2 = next(c for c in imported.components if c.ref == "D2")
    assert d2.pin_functions == ()


def test_each_part_is_read_for_what_it_is() -> None:
    plan = _plan()
    got = {ref: (s.footprint_id, s.source, s.part_id, s.value) for ref, s in plan.suggestions.items()}
    assert got["Q1"] == ("to92", "catalog", "bc547", "BC547")
    assert got["Q2"] == ("to92", "kicad", None, "2N5088")
    assert got["D1"] == ("led-5mm", "kicad", None, "RED")
    assert got["U1"] == ("dip-8", "catalog", "ne555", "NE555P")
    assert got["U2"] == ("to220", "catalog", "7805", "L7805")
    # Surface-mount in the schematic, a DIP here -- and said.
    assert got["U3"] == ("dip-8", "catalog", "lm358", "LM358")
    assert any("surface-mount" in line for line in plan.notes["U3"])
    assert got["C1"] == ("c-elec-d6.3-p1-h11", "kicad", None, "100u")
    assert got["R1"] == ("r-axial-4", "kicad", None, "4k7")
    assert got["K1"][0:2] == ("relay-spdt", "guess")
    assert any("relay" in line for line in plan.notes["K1"])
    assert got["J1"] == ("hdr-1x2", "kicad", None, "PWR")


def test_a_generic_ebc_symbol_given_a_bc547s_value_is_wired_for_the_real_bc547() -> None:
    """The symbol says pin 1 is the emitter; a BC547's pin 1 is its collector. The emitter's
    net goes to the BC547's emitter, pin 3."""
    plan = _plan()
    assert ("Q1", "3") in _pins(plan, "GND") and ("Q1", "1") in _pins(plan, "COLL")
    assert ("Q1", "2") in _pins(plan, "BASE")
    assert any("renumbered" in line for line in plan.notes["Q1"])
    # A 2N5088 is not in the catalog: nothing to renumber against, and its names printed.
    assert ("Q2", "1") in _pins(plan, "GND")
    assert dict(plan.suggestions["Q2"].pin_names) == {"1": "E", "2": "B", "3": "C"}


def test_an_led_is_wired_anode_to_this_librarys_pin_1() -> None:
    """KiCad's LED is pin 1 = K. D1 says so in its names; D2 says nothing and is read by
    KiCad's own numbering of LED_D3.0mm."""
    plan = _plan()
    for ref in ("D1", "D2"):
        assert (ref, "2") in _pins(plan, "GND") and (ref, "1") in _pins(plan, "+5V"), ref
        assert any("renumbered" in line for line in plan.notes[ref])
    # Two legs and a polarity mark: no names printed beside them.
    assert plan.suggestions["D1"].pin_names == ()


def test_what_needs_no_renumbering_is_left_exactly_as_it_was() -> None:
    plan = _plan()
    assert ("U1", "1") in _pins(plan, "GND") and ("U1", "8") in _pins(plan, "+5V")
    assert ("U2", "1") in _pins(plan, "VIN") and ("U2", "3") in _pins(plan, "+5V")
    for ref in ("U1", "U2", "C1", "R1", "J1"):
        assert not any("renumbered" in line for line in plan.notes.get(ref, ())), ref


def test_a_part_already_on_the_board_is_renumbered_by_its_own_names() -> None:
    """A re-import after the parts are placed reads the board's parts, not a guess."""
    session = BoardSession(document=new_board(cols=30, rows=20))
    session.place_component("D1", "led-5mm", "C3")
    imported = parse_kicad_netlist(NETLIST)
    plan = plan_import(imported, session.document, session.lookup)
    assert "D1" not in plan.suggestions
    assert ("D1", "2") in _pins(plan, "GND")


# ------------------------------------------------------------------- over MCP


def test_an_agent_imports_and_places_in_one_call(tmp_path: Path) -> None:
    path = tmp_path / "t.net"
    path.write_text(NETLIST, encoding="utf-8")
    session = BoardSession(document=new_board(cols=40, rows=30))
    result = session.import_netlist(str(path), place_missing=True)
    assert result["ok"], result
    assert "Q1" in result["notes"]
    assert {entry["ref"] for entry in result["suggested_parts"]} == {
        "Q1", "Q2", "D1", "D2", "U1", "U2", "U3", "C1", "R1", "K1", "J1"
    }
    assert result["missing_components"] == []
    q1 = next(c for c in session.document.components if c.ref == "Q1")
    assert q1.value == "BC547" and dict(q1.pin_names)["1"] == "C"
    # One undo takes every placed part back.
    session.undo()
    assert session.document.components == ()


def test_without_place_missing_nothing_is_placed(tmp_path: Path) -> None:
    path = tmp_path / "t.net"
    path.write_text(NETLIST, encoding="utf-8")
    session = BoardSession(document=new_board(cols=40, rows=30))
    result = session.import_netlist(str(path))
    assert result["ok"] and "placed" not in result
    assert len(result["missing_components"]) == 11


def test_a_push_button_is_wired_across_its_switched_pair() -> None:
    """KiCad's switch symbol is two pins, and they are the pair pressing it joins. On the
    button as made they land on pins 1 and 2, one side of it, 4.5 mm apart -- where the old
    guess put them on sw-tactile's pins 1 and 2, which that footprint calls one node."""
    footprint = LOOKUP("sw-tactile-6x6")
    assert footprint is not None
    where = {pin.number: (pin.d_col, pin.d_row, pin.name) for pin in footprint.pins}
    assert where == {"1": (0, 0, "A"), "2": (0, 2, "B"), "3": (3, 0, "A"), "4": (3, 2, "B")}
    netlist = NETLIST.replace(
        '(comp (ref "J1")',
        '(comp (ref "SW1") (value "RESET") (footprint "Button_Switch_THT:SW_PUSH_6mm")'
        ' (libsource (lib "Switch") (part "SW_Push"))) (comp (ref "J1")',
    ).replace(
        '(node (ref "J1") (pin "1") (pinfunction "Pin_1") (pintype "passive"))',
        '(node (ref "J1") (pin "1") (pinfunction "Pin_1") (pintype "passive"))'
        ' (node (ref "SW1") (pin "1") (pinfunction "1") (pintype "passive"))',
    )
    document = create_empty_document(DocumentMeta(name="t", created="", modified=""))
    plan = plan_import(parse_kicad_netlist(netlist), document, LOOKUP)
    switch = plan.suggestions["SW1"]
    assert (switch.footprint_id, switch.source) == ("sw-tactile-6x6", "kicad")
    assert "SW1" not in plan.notes


def test_the_catalog_has_the_buttons_as_made() -> None:
    from perfboard_studio.catalog import catalog_part, search_catalog

    for part_id, footprint in (("tact-6x6", "sw-tactile-6x6"), ("tact-12x12", "sw-tactile-12x12")):
        part = catalog_part(part_id)
        assert part is not None and part.footprint_id == footprint
        assert LOOKUP(footprint) is not None
    assert [p.id for p in search_catalog("push button")] == ["tact-6x6", "tact-12x12"]


NANO_NETLIST = """(export (version "E")
  (components
    (comp (ref "A1") (value "Arduino_Nano_v3.x") (footprint "Module:Arduino_Nano")
      (libsource (lib "MCU_Module") (part "Arduino_Nano_v3.x")))
    (comp (ref "R1") (value "1k")
      (footprint "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal")
      (libsource (lib "Device") (part "R"))))
  (nets
    (net (code "1") (name "GND")
      (node (ref "A1") (pin "4") (pinfunction "GND") (pintype "power_in"))
      (node (ref "A1") (pin "29") (pinfunction "GND") (pintype "power_in"))
      (node (ref "R1") (pin "2") (pinfunction "~") (pintype "passive")))
    (net (code "2") (name "LED")
      (node (ref "A1") (pin "5") (pinfunction "D2") (pintype "bidirectional"))
      (node (ref "R1") (pin "1") (pinfunction "~") (pintype "passive")))
    (net (code "3") (name "/RST")
      (node (ref "A1") (pin "3") (pinfunction "~{RESET}") (pintype "input"))
      (node (ref "A1") (pin "19") (pinfunction "A0") (pintype "input")))))
"""


def test_a_kicad_module_is_renumbered_across_its_rows() -> None:
    """KiCad numbers an Arduino Nano down one side and up the other; the catalog's Nano is
    numbered across its rows. Every pin is found by name -- ``~{RESET}`` is RESET, and the
    two GNDs, one net, go to the Nano's two GNDs in order -- and the module note that the
    footprint alone would give is not said, since the catalog part answers it."""
    document = create_empty_document(DocumentMeta(name="t", created="", modified=""))
    plan = plan_import(parse_kicad_netlist(NANO_NETLIST), document, LOOKUP)
    nano = plan.suggestions["A1"]
    assert (nano.source, nano.part_id) == ("catalog", "arduino-nano")
    names = dict(nano.pin_names)
    pins = {
        net.name: {node.pin for node in net.nodes if node.component_ref == "A1"}
        for net in plan.nets
    }
    assert {names[p] for p in pins["GND"]} == {"GND"} and len(pins["GND"]) == 2
    assert {names[p] for p in pins["LED"]} == {"D2"}
    assert {names[p] for p in pins["/RST"]} == {"RESET", "A0"}
    assert not any("module" in line for line in plan.notes["A1"])
    assert any("renumbered" in line for line in plan.notes["A1"])


def test_two_pins_of_one_name_in_different_nets_are_not_guessed_at() -> None:
    """Two "+" inputs of a dual op-amp are not interchangeable: matched in order they could
    swap its channels. Nothing moves."""
    part = (("3", "+"), ("5", "+"))
    schematic = (("5", "+"), ("7", "+"))
    assert pin_renumbering(schematic, part, {"5", "7"}, {"5": "a", "7": "b"}) == {}
    assert pin_renumbering(schematic, part, {"5", "7"}, {"5": "a", "7": "a"}) == {"5": "3", "7": "5"}
