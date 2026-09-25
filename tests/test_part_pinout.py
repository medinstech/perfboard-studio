"""A part saying what it is: declared pin names and a declared symbol.

THE PINOUT IS A FACT ABOUT THE PART, NOT THE PACKAGE. The registry refuses to guess which
leg of a TO-92 is the base, and it is right to -- BC547 and 2N3904 disagree on the same
outline. What these tests pin is the other half of that argument: the person who chose the
part CAN say, the document now has somewhere to write it, and everything downstream reads
it from one place (``model.pin_name_of``) without any of it changing for a part that says
nothing -- which is what keeps every golden fixture byte-identical.

Grouped by layer: the model's normal form, the file, the commands, the sheet, the guide,
and the MCP session, because each is a separate place the declaration could be dropped on
the floor.
"""

from __future__ import annotations

import json
from typing import get_args

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    AddNetPayload,
    AddPartPayload,
    PartPlacement,
    PlaceComponentPayload,
    PlacePartsPayload,
    UnplaceComponentPayload,
    UpdateComponentPayload,
    UpdatePartPayload,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.guide import _polarity_note, build_guide
from perfboard_studio.mcp.session import BoardSession
from perfboard_studio.model import (
    DocumentMeta,
    HoleCoord,
    NetNode,
    PartSymbol,
    PerfDocument,
    normalized_pin_names,
    pin_name_of,
)
from perfboard_studio.persist import PART_SYMBOLS, serialize_document
from perfboard_studio.schematic import (
    DECLARED_SYMBOL_PINS,
    GRID_MM,
    LEAD_MM,
    Symbol,
    build_schematic,
)

META = DocumentMeta(name="pinout", created="", modified="")
REGISTRY = footprint_lookup()


def new_bus() -> CommandBus:
    return CommandBus(
        create_empty_document(META),
        create_standard_registry(),
        CommandContext(next_id=create_id_generator()),
    )


def add(bus: CommandBus, ref: str, footprint: str, value: str = "", **declared) -> None:
    result = bus.dispatch(
        "part.add", AddPartPayload(ref=ref, footprint_id=footprint, value=value, **declared)
    )
    assert result.ok, result.message


def wire(bus: CommandBus, name: str, *pins: str) -> None:
    nodes = tuple(NetNode(component_ref=p.split(".")[0], pin=p.split(".")[1]) for p in pins)
    assert bus.dispatch("net.add", AddNetPayload(name=name, nodes=nodes)).ok


def symbol(doc: PerfDocument, ref: str) -> Symbol:
    return next(s for s in build_schematic(doc, REGISTRY).symbols if s.ref == ref)


def notes(doc: PerfDocument) -> tuple[str, ...]:
    return build_schematic(doc, REGISTRY).notes


GDS = (("1", "G"), ("2", "D"), ("3", "S"))
CBE = (("1", "C"), ("2", "B"), ("3", "E"))


# ---------------------------------------------------------------------------
# The model: one normal form
# ---------------------------------------------------------------------------


def test_pin_names_are_stored_in_pin_order_not_text_order() -> None:
    """Pin 10 after pin 9. Stored as text order, a forty-pin module's names would come
    back from the file in an order nobody wrote them in."""
    assert normalized_pin_names({"10": "IO10", "2": "IO2", "1": "3V3"}) == (
        ("1", "3V3"),
        ("2", "IO2"),
        ("10", "IO10"),
    )


def test_a_blank_name_means_no_name_and_a_blank_number_is_refused() -> None:
    assert normalized_pin_names({" 1 ": " G ", "2": "  "}) == (("1", "G"),)
    with pytest.raises(ValueError):
        normalized_pin_names({"": "G"})
    with pytest.raises(ValueError):
        normalized_pin_names("G,D,S")


def test_the_part_name_wins_over_the_footprint_name() -> None:
    led = REGISTRY("led-5mm")
    assert led is not None
    bus = new_bus()
    add(bus, "D1", "led-5mm", pin_names=(("1", "ANODE"),))
    part = bus.document.parts[0]
    assert pin_name_of(part, led.pins[0]) == "ANODE"
    # ...and a pin the part says nothing about keeps the registry's name.
    assert pin_name_of(part, led.pins[1]) == "K"
    assert pin_name_of(None, led.pins[1]) == "K"


def test_every_declarable_symbol_says_what_it_needs() -> None:
    """A symbol a part can declare but the sheet has no rule for would draw -- or crash --
    on the first part that declared it. Both lists are read from the one ``PartSymbol``."""
    assert set(DECLARED_SYMBOL_PINS) == set(get_args(PartSymbol))
    assert set(PART_SYMBOLS) == set(get_args(PartSymbol))


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


def test_a_part_that_declares_nothing_writes_nothing() -> None:
    """The stripAxis rule. Every fixture in the repository is a part that declares
    nothing, and they all re-serialize to their own bytes only because of this."""
    bus = new_bus()
    add(bus, "R1", "r-axial-4", "10k")
    text = serialize_document(bus.document)
    assert "pinNames" not in text
    assert '"symbol"' not in text


@pytest.mark.parametrize("placed", [False, True], ids=["part", "component"])
def test_declarations_survive_the_file(placed: bool) -> None:
    bus = new_bus()
    add(bus, "Q1", "to220", "IRF9540N", pin_names=GDS, symbol="pmos")
    if placed:
        part_id = bus.document.parts[0].id
        assert bus.dispatch(
            "part.place",
            PlacePartsPayload(placements=(PartPlacement(id=part_id, anchor=HoleCoord(3, 3)),)),
        ).ok
    text = serialize_document(bus.document)
    reloaded = persist.parse_document_or_throw(text)
    owner = reloaded.components[0] if placed else reloaded.parts[0]
    assert owner.pin_names == GDS
    assert owner.symbol == "pmos"
    assert serialize_document(reloaded) == text
    # An object, in pin order, after every field that was there before it.
    body = json.loads(text)
    entry = body["components" if placed else "parts"][0]
    assert list(entry)[-2:] == ["pinNames", "symbol"]
    assert entry["pinNames"] == {"1": "G", "2": "D", "3": "S"}


def test_a_hand_edited_file_is_read_in_normal_form() -> None:
    bus = new_bus()
    add(bus, "Q1", "to220", pin_names=GDS)
    body = json.loads(serialize_document(bus.document))
    body["parts"][0]["pinNames"] = {"3": " S ", "1": "G", "2": "D"}
    reloaded = persist.parse_document_or_throw(json.dumps(body))
    assert reloaded.parts[0].pin_names == GDS


@pytest.mark.parametrize(
    "field,value",
    [("symbol", "triac"), ("pinNames", {"1": 5}), ("pinNames", ["G", "D"])],
    ids=["unknown-symbol", "non-text-name", "not-an-object"],
)
def test_a_malformed_declaration_is_refused_at_load_with_a_path(field: str, value) -> None:
    bus = new_bus()
    add(bus, "Q1", "to220")
    body = json.loads(serialize_document(bus.document))
    body["parts"][0][field] = value
    result = persist.deserialize_document(json.dumps(body))
    assert not result.ok
    assert result.path is not None and result.path.startswith("parts[0]")


# ---------------------------------------------------------------------------
# The commands
# ---------------------------------------------------------------------------


def test_an_undrawable_symbol_is_refused_by_name() -> None:
    bus = new_bus()
    result = bus.dispatch(
        "part.add", AddPartPayload(ref="Q1", footprint_id="to220", symbol="triac")  # type: ignore[arg-type]
    )
    assert not result.ok
    assert result.code == "invalid-symbol"
    assert "pmos" in (result.message or "")


def test_a_name_on_no_pin_number_is_refused() -> None:
    bus = new_bus()
    result = bus.dispatch(
        "part.add", AddPartPayload(ref="Q1", footprint_id="to220", pin_names=(("", "G"),))
    )
    assert not result.ok
    assert result.code == "invalid-pin-names"


def test_placing_and_unplacing_carry_the_declaration_both_ways() -> None:
    """A placement that dropped the pinout would turn a MOSFET back into a box the moment
    it was put down -- and unplacing it again would not bring the MOSFET back."""
    bus = new_bus()
    add(bus, "Q1", "to220", pin_names=GDS, symbol="pmos")
    part_id = bus.document.parts[0].id
    assert bus.dispatch(
        "part.place",
        PlacePartsPayload(placements=(PartPlacement(id=part_id, anchor=HoleCoord(3, 3)),)),
    ).ok
    placed = bus.document.components[0]
    assert (placed.pin_names, placed.symbol) == (GDS, "pmos")
    assert bus.dispatch("component.unplace", UnplaceComponentPayload(id=part_id)).ok
    back = bus.document.parts[0]
    assert (back.pin_names, back.symbol) == (GDS, "pmos")


def test_component_place_takes_a_declaration_too() -> None:
    """The route a paste and an agent's place_component both take."""
    bus = new_bus()
    assert bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref="T1",
            value="BC547",
            footprint_id="to92",
            anchor=HoleCoord(2, 2),
            pin_names=CBE,
            symbol="npn",
        ),
    ).ok
    assert bus.document.components[0].symbol == "npn"


@pytest.mark.parametrize("placed", [False, True], ids=["part.update", "component.update"])
def test_an_update_leaves_replaces_or_clears(placed: bool) -> None:
    """``None`` leaves the names, an empty tuple clears them, and the symbol has a third
    state -- KEEP -- because for it None already means "declares nothing"."""
    bus = new_bus()
    add(bus, "Q1", "to220", pin_names=GDS, symbol="pmos")
    part_id = bus.document.parts[0].id
    if placed:
        bus.dispatch(
            "part.place",
            PlacePartsPayload(placements=(PartPlacement(id=part_id, anchor=HoleCoord(3, 3)),)),
        )

    def update(**fields):
        if placed:
            return bus.dispatch("component.update", UpdateComponentPayload(id=part_id, **fields))
        return bus.dispatch("part.update", UpdatePartPayload(id=part_id, **fields))

    def current():
        return (bus.document.components if placed else bus.document.parts)[0]

    assert update(value="IRF9540N").ok
    assert (current().pin_names, current().symbol) == (GDS, "pmos")
    assert update(pin_names=(("1", "GATE"),)).ok
    assert current().pin_names == (("1", "GATE"),)
    assert current().symbol == "pmos"
    assert update(pin_names=(), symbol=None).ok
    assert (current().pin_names, current().symbol) == ((), None)


# ---------------------------------------------------------------------------
# The sheet
# ---------------------------------------------------------------------------


def _declared_doc(footprint: str, names, declared: str, value: str = "") -> PerfDocument:
    bus = new_bus()
    add(bus, "X1", footprint, value, pin_names=names, symbol=declared)
    return bus.document


@pytest.mark.parametrize(
    "declared,names,left,top,bottom",
    [
        ("npn", CBE, "B", "C", "E"),
        ("pnp", CBE, "B", "E", "C"),
        ("nmos", GDS, "G", "D", "S"),
        ("pmos", GDS, "G", "S", "D"),
    ],
)
def test_a_declared_transistor_puts_each_named_lead_where_the_symbol_says(
    declared: str, names, left: str, top: str, bottom: str
) -> None:
    """The control lead on the left, and the conventional lead on top for each: collector
    of an NPN, emitter of a PNP, drain of an N-channel, source of a P-channel -- current
    runs down the page through every one of them. A lead in the wrong place is a symbol
    that draws a working circuit the wrong way round."""
    drawn = symbol(_declared_doc("to92", names, declared), "X1")
    assert drawn.kind == declared
    by_name = {pin.name: pin for pin in drawn.pins}
    assert by_name[left].side == "left"
    assert by_name[top].side == "right" and by_name[bottom].side == "right"
    assert by_name[top].at.y < by_name[bottom].at.y
    # The PACKAGE number goes with the name, wherever the symbol put it.
    assert {pin.number: pin.name for pin in drawn.pins} == dict(names)


def test_a_declared_transistor_without_named_leads_stays_a_box_and_says_why() -> None:
    """The declaration alone is not the pinout. Drawing a MOSFET from "pmos" with unnamed
    leads would be assigning the gate to pin 1 on the part's behalf -- the claim the whole
    registry is built to refuse."""
    doc = _declared_doc("to220", (("1", "G"),), "pmos")
    assert symbol(doc, "X1").kind == "box"
    assert any("X1: declared pmos" in note and "D, G, S" in note for note in notes(doc))


def test_a_declared_zener_and_fuse_draw_as_themselves() -> None:
    assert symbol(_declared_doc("d-do35", (), "zener"), "X1").kind == "zener"
    assert symbol(_declared_doc("c-disc-p2", (), "fuse"), "X1").kind == "fuse"


def test_a_zener_on_an_unpolarised_package_needs_its_leads_named() -> None:
    """A DO-35 knows its band is pin 1; a generic axial knows nothing, and a zener drawn
    the wrong way round clamps nothing. It falls back to what the package looks like --
    a resistor, not a box -- and the note says so."""
    doc = _declared_doc("r-axial-4", (), "zener")
    assert symbol(doc, "X1").kind == "resistor"
    assert any("cathode" in note and "resistor instead" in note for note in notes(doc))
    named = _declared_doc("r-axial-4", (("1", "A"), ("2", "K")), "zener")
    drawn = symbol(named, "X1")
    assert drawn.kind == "zener"
    # Cathode on the left, as for every diode on this sheet.
    assert next(pin for pin in drawn.pins if pin.name == "K").side == "left"


def test_a_name_on_a_pin_the_package_lacks_is_reported() -> None:
    doc = _declared_doc("to92", (("1", "C"), ("7", "X")), None)  # type: ignore[arg-type]
    assert any("X1: names pin(s) 7" in note for note in notes(doc))


def test_named_pins_print_the_name_inside_and_the_number_on_the_lead() -> None:
    bus = new_bus()
    add(bus, "U1", "dip-8", "SN65HVD230", pin_names=(("1", "D"), ("4", "R")))
    add(bus, "U2", "dip-8", "SN65HVD230")
    drawing = build_schematic(bus.document, REGISTRY)
    u1 = next(s for s in drawing.symbols if s.ref == "U1")
    u2 = next(s for s in drawing.symbols if s.ref == "U2")
    inside = {label.text for label in drawing.labels if label.kind == "pin"
              and u1.at.x + LEAD_MM <= label.at.x <= u1.at.x + u1.width - LEAD_MM
              and u1.at.y <= label.at.y <= u1.at.y + u1.height}
    assert {"D", "R"} <= inside
    # An unnamed pin keeps its number where it always was, and a named one has its
    # number outside the body, on the lead.
    assert "2" in inside and "1" not in inside
    # Two short names fit in the ordinary width; nothing about U2 changed.
    assert u1.width == u2.width


def test_a_box_widens_to_fit_long_names_and_only_then() -> None:
    names = tuple((str(n), f"GPIO_LONG_{n}") for n in range(1, 39))
    bus = new_bus()
    add(bus, "U1", "box-2x19-p10-r1-28x51x10", pin_names=names)
    add(bus, "U2", "box-2x19-p10-r1-28x51x10")
    u1, u2 = symbol(bus.document, "U1"), symbol(bus.document, "U2")
    assert u1.width > u2.width
    # Whole grid squares, so the right-hand leads stay on the grid.
    assert abs(round(u1.width / GRID_MM) * GRID_MM - u1.width) < 1e-9


def test_a_connector_name_starts_past_the_shroud_line() -> None:
    """A name starting where a number does runs straight through the shroud line."""
    bus = new_bus()
    add(bus, "J1", "hdr-1x2", pin_names=(("1", "24V-L"), ("2", "GND")))
    drawing = build_schematic(bus.document, REGISTRY)
    j1 = next(s for s in drawing.symbols if s.ref == "J1")
    shroud_x = j1.at.x + LEAD_MM + 1.4 * GRID_MM
    for label in drawing.labels:
        if label.kind == "pin" and label.text in ("24V-L", "GND"):
            assert label.at.x > shroud_x


def test_a_part_that_declares_nothing_draws_the_sheet_it_always_did() -> None:
    """The same circuit, once as it was and once with an empty declaration: identical."""
    plain = new_bus()
    add(plain, "Q1", "to92", "BC547")
    empty = new_bus()
    add(empty, "Q1", "to92", "BC547", pin_names=(), symbol=None)
    assert build_schematic(plain.document, REGISTRY) == build_schematic(empty.document, REGISTRY)


# ---------------------------------------------------------------------------
# The guide
# ---------------------------------------------------------------------------


def test_a_three_legged_part_is_oriented_leg_by_leg_when_it_names_them() -> None:
    footprint = REGISTRY("to220")
    assert footprint is not None
    bus = new_bus()
    assert bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref="Q1", value="IRF9540N", footprint_id="to220", anchor=HoleCoord(2, 2), pin_names=GDS
        ),
    ).ok
    component = bus.document.components[0]
    holes = (("1", HoleCoord(2, 2)), ("2", HoleCoord(3, 2)), ("3", HoleCoord(4, 2)))
    note = _polarity_note(footprint, holes, component)
    assert note is not None
    assert note.startswith("G (gate) in C3; D (drain) in D3; S (source) in E3")
    # Unnamed, it is what it always was.
    assert "check the package outline" in (_polarity_note(footprint, holes) or "")


def test_a_probe_names_the_pin_the_part_named() -> None:
    session = BoardSession()
    session.place_component("J1", "hdr-1x2", "B2", pin_names={"1": "24V-L", "2": "GND"})
    session.place_component("R1", "r-axial-4", "B6", value="10k")
    session.create_net("VIN", "power", ["J1.1", "R1.1"])
    session.create_net("GND", "ground", ["J1.2", "R1.2"])
    assert session.autoroute()["unrouted"] == 0
    guide = build_guide(session.document, REGISTRY)
    text = json.dumps(
        [check.instruction for phase in guide.phases for check in phase.checkpoints]
    )
    assert "J1 pin 1 (24V-L)" in text
    # Only a DECLARED name is appended: the resistor's pins get nothing.
    assert "R1 pin 1 (" not in text and "R1 pin 2 (" not in text


# ---------------------------------------------------------------------------
# The MCP session
# ---------------------------------------------------------------------------


def test_an_agent_declares_reads_back_and_clears() -> None:
    session = BoardSession()
    assert session.add_part("Q1", "to220", "IRF9540N", pin_names={"1": "G", "2": "D", "3": "S"},
                            symbol="pmos")["ok"]
    listed = session.list_parts()["parts"][0]
    assert listed["pin_names"] == {"1": "G", "2": "D", "3": "S"} and listed["symbol"] == "pmos"
    assert session.place_parts([{"ref": "Q1", "at": "C3"}])["ok"]
    component = session.get_component("Q1")
    assert component["symbol"] == "pmos"
    assert [pin["name"] for pin in component["pins"]] == ["G", "D", "S"]
    # update_part reaches a part on the board, and "" clears a declaration.
    assert session.update_part("Q1", symbol="")["ok"]
    assert "symbol" not in session.get_component("Q1")


def test_an_agent_cannot_change_the_package_under_a_placed_part() -> None:
    session = BoardSession()
    session.place_component("Q1", "to220", "C3")
    with pytest.raises(Exception, match="unplace_component"):
        session.update_part("Q1", footprint_id="to92")


def test_an_agent_gets_a_refusal_as_data_for_a_bad_symbol() -> None:
    session = BoardSession()
    result = session.add_part("Q1", "to220", symbol="triac")
    assert result["ok"] is False and result["code"] == "invalid-symbol"
