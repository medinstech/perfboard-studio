"""A part that is not on the board, and the row of pads its wires land in.

A pot on the panel, a jack in the enclosure, a footswitch: none of them is on the perfboard
and every one of them is wired to it. Its footprint is the pads (``wire-<n>``), so every
module that reads pins took it as it takes any part without learning anything -- and these
tests pin the parts that DID have to learn: the id grammar, the move off the board that
keeps what the package used to say, the one undo step it takes, the guide that wires it in
phase 7 and checks its nets only once its wires are in, the sheet that still draws a pot as a
pot, the edge the wires leave over, and the KiCad footprints that mean the same thing.
"""

from __future__ import annotations

import dataclasses
import itertools
from pathlib import Path

import pytest

from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    AddConductorPayload,
    AddPartPayload,
    NewLeadBendConductor,
    PlaceComponentPayload,
    UpdateComponentPayload,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.footprints import (
    GENERATED_ID_GRAMMAR,
    flying_lead_length_mm,
    footprint_lookup,
    get_footprint,
    off_board_mount,
)
from perfboard_studio.geometry import all_pin_holes, flying_lead_side, format_hole
from perfboard_studio.guide import GuideOptions, PartStep, build_guide
from perfboard_studio.guide_export import cut_list_to_csv, guide_to_html, guide_to_json
from perfboard_studio.lvs import run_lvs
from perfboard_studio.model import (
    Board,
    DocumentMeta,
    HoleCoord,
    PerfDocument,
    SchematicPart,
)
from perfboard_studio.parsers.kicad import ImportedComponent
from perfboard_studio.parsers.kicad_parts import _suggest, kicad_footprint_ids
from perfboard_studio.persist import parse_document_or_throw, serialize_document
from perfboard_studio.placer import EDGE_SEEKING_ARCHETYPES
from perfboard_studio.schematic import build_schematic

ROOT = Path(__file__).resolve().parents[1]
PEDAL = ROOT / "examples" / "lpb1-booster.perf"
REGISTRY = footprint_lookup()
META = DocumentMeta(name="flying", created="", modified="")


def bus_for(doc: PerfDocument) -> CommandBus:
    return CommandBus(doc, create_standard_registry(), CommandContext(next_id=create_id_generator()))


def pedal() -> CommandBus:
    return bus_for(parse_document_or_throw(PEDAL.read_text(encoding="utf-8")))


def mount(bus: CommandBus, ref: str) -> None:
    """What the window's Mount on the Panel does to a placed part."""
    component = next(c for c in bus.document.components if c.ref == ref)
    footprint = REGISTRY(component.footprint_id)
    assert footprint is not None
    moved = off_board_mount(component, footprint)
    result = bus.dispatch(
        "component.update",
        UpdateComponentPayload(
            id=component.id,
            footprint_id=moved.footprint_id,
            pin_names=moved.pin_names,
            symbol=moved.symbol,
        ),
    )
    assert result.ok, result.message


def part(ref: str, footprint_id: str, **fields) -> SchematicPart:
    return SchematicPart(id=f"p-{ref}", ref=ref, value="", footprint_id=footprint_id, **fields)


# ---------------------------------------------------------------------------
# The id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "id_,wires,step,length",
    [
        ("wire-1", 1, 1, None),
        ("wire-3", 3, 1, None),
        ("wire-2-p2", 2, 2, None),
        ("wire-3-l150", 3, 1, 150.0),
        ("wire-4-p3-l1200", 4, 3, 1200.0),
    ],
)
def test_an_id_is_its_wires_their_spacing_and_their_length(
    id_: str, wires: int, step: int, length: float | None
) -> None:
    footprint = get_footprint(id_)
    assert footprint is not None
    assert footprint.id == id_
    assert footprint.body.archetype == "flying-leads"
    # Pad N carries the wire from lead N, in one row: nothing is renumbered.
    assert [(pin.number, pin.d_col, pin.d_row) for pin in footprint.pins] == [
        (str(n + 1), n * step, 0) for n in range(wires)
    ]
    assert flying_lead_length_mm(footprint) == length
    # A length nobody gave is not a zero somebody did.
    assert ("wireLength" in footprint.body.dims) == (length is not None)


@pytest.mark.parametrize(
    "id_", ["wire-0", "wire-03", "wire-3-p1", "wire-3-l5", "wire-3-l9000", "wire-3-l150-p2"]
)
def test_one_spelling_per_part_and_nothing_impossible(id_: str) -> None:
    """The default step is spelled by leaving it out, the parameters come in one order, and a
    wire shorter than a centimetre is a typo -- each would otherwise be a second name for one
    part, or a cut list asking for something nobody can cut."""
    assert get_footprint(id_) is None


def test_the_grammar_says_how_to_ask_for_one() -> None:
    assert "wire-<n>[-p<step>][-l<L>]" in GENERATED_ID_GRAMMAR
    assert "wire-3-l150" in GENERATED_ID_GRAMMAR


def test_it_wants_an_edge() -> None:
    """Every wire landed mid-board is a wire lying across the parts round it."""
    assert "flying-leads" in EDGE_SEEKING_ARCHETYPES


# ---------------------------------------------------------------------------
# Off the board, keeping what the package said
# ---------------------------------------------------------------------------


def test_a_pot_off_the_board_is_still_drawn_as_a_pot() -> None:
    footprint = REGISTRY("pot-3")
    assert footprint is not None
    moved = off_board_mount(part("RV1", "pot-3"), footprint)
    assert moved.footprint_id == "wire-3"
    assert moved.symbol == "potentiometer"


def test_an_led_off_the_board_keeps_which_lead_is_the_anode() -> None:
    """The package named A and K; the pads name nothing. Swapping the footprint alone would
    leave a bezel LED whose polarity nobody could read off the board any more."""
    footprint = REGISTRY("led-5mm")
    assert footprint is not None
    moved = off_board_mount(part("LED1", "led-5mm"), footprint)
    assert moved.pin_names == (("1", "A"), ("2", "K"))
    assert moved.symbol == "led"


def test_the_parts_own_names_and_symbol_win() -> None:
    footprint = REGISTRY("led-5mm")
    assert footprint is not None
    declared = part("LED1", "led-5mm", pin_names=(("1", "ANODE"),), symbol="zener")
    moved = off_board_mount(declared, footprint)
    assert moved.pin_names == (("1", "ANODE"), ("2", "K"))
    assert moved.symbol == "zener"


def test_pins_already_in_a_row_keep_their_holes() -> None:
    """A resistor's leads four holes apart become two pads four holes apart, so on a placed
    part every pad is the hole its pin was in and the copper still reaches it."""
    footprint = REGISTRY("r-axial-4")
    assert footprint is not None
    assert off_board_mount(part("R1", "r-axial-4"), footprint).footprint_id == "wire-2-p4"
    # Pins that are not one row cannot keep their holes, and get the plain row.
    dip = REGISTRY("dip-8")
    assert dip is not None
    assert off_board_mount(part("U1", "dip-8"), dip).footprint_id == "wire-8"


def test_a_part_whose_pins_are_not_one_to_n_is_refused() -> None:
    footprint = REGISTRY("pot-3")
    assert footprint is not None
    odd = dataclasses.replace(
        footprint, pins=tuple(dataclasses.replace(p, number=f"P{p.number}") for p in footprint.pins)
    )
    with pytest.raises(ValueError, match="not numbered 1 to 3"):
        off_board_mount(part("RV1", "pot-3"), odd)


def test_mounting_the_pedals_pot_and_jack_leaves_the_board_wired_as_it_was() -> None:
    """End to end on a shipped board: the pot's three pins were in a row, so its pads are its
    holes, the routed copper still reaches them, and LVS still matches every net."""
    bus = pedal()
    before = run_lvs(bus.document, REGISTRY).summary
    mount(bus, "RV1")
    mount(bus, "J1")
    after = run_lvs(bus.document, REGISTRY)
    assert after.summary == before
    assert after.summary.opens == 0 and after.summary.shorts == 0


# ---------------------------------------------------------------------------
# The command: one step, and the lead bends go with the package
# ---------------------------------------------------------------------------


def _placed(locked: bool = False) -> CommandBus:
    bus = bus_for(create_empty_document(META))
    result = bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref="R1", value="10k", footprint_id="r-axial-4", anchor=HoleCoord(3, 3)
        ),
    )
    assert result.ok, result.message
    if locked:
        component = bus.document.components[0]
        assert bus.dispatch(
            "component.update", UpdateComponentPayload(id=component.id, locked=True)
        ).ok
    return bus


def test_a_new_package_is_one_undo_step() -> None:
    bus = _placed()
    component = bus.document.components[0]
    assert bus.dispatch(
        "component.update", UpdateComponentPayload(id=component.id, footprint_id="wire-2-p4")
    ).ok
    assert bus.document.components[0].footprint_id == "wire-2-p4"
    assert bus.document.components[0].anchor == component.anchor
    bus.undo()
    assert bus.document.components[0].footprint_id == "r-axial-4"


def test_its_lead_bends_go_with_the_old_package() -> None:
    bus = _placed()
    component = bus.document.components[0]
    bend = NewLeadBendConductor(
        path=(HoleCoord(3, 3), HoleCoord(3, 4)), component_id=component.id, pin_number="1"
    )
    assert bus.dispatch("conductor.add", AddConductorPayload(conductor=bend)).ok
    assert bus.document.conductors
    assert bus.dispatch(
        "component.update", UpdateComponentPayload(id=component.id, footprint_id="wire-2-p4")
    ).ok
    assert not bus.document.conductors


def test_a_locked_part_keeps_its_package_and_a_blank_one_is_refused() -> None:
    bus = _placed(locked=True)
    component = bus.document.components[0]
    locked = bus.dispatch(
        "component.update", UpdateComponentPayload(id=component.id, footprint_id="wire-2-p4")
    )
    assert not locked.ok and locked.code == "component-locked"
    bus = _placed()
    blank = bus.dispatch(
        "component.update",
        UpdateComponentPayload(id=bus.document.components[0].id, footprint_id="  "),
    )
    assert not blank.ok and blank.code == "empty-footprint"


def test_the_same_package_again_is_no_change_even_when_locked() -> None:
    bus = _placed(locked=True)
    component = bus.document.components[0]
    assert bus.dispatch(
        "component.update", UpdateComponentPayload(id=component.id, footprint_id="r-axial-4")
    ).ok


def test_a_declared_pot_survives_the_file() -> None:
    bus = pedal()
    mount(bus, "RV1")
    again = parse_document_or_throw(serialize_document(bus.document))
    rv1 = next(c for c in again.components if c.ref == "RV1")
    assert rv1.footprint_id == "wire-3" and rv1.symbol == "potentiometer"


# ---------------------------------------------------------------------------
# The guide
# ---------------------------------------------------------------------------


def _pedal_guide(language: str = "en"):
    bus = pedal()
    mount(bus, "RV1")
    mount(bus, "J1")
    return bus.document, build_guide(bus.document, REGISTRY, GuideOptions(language=language))


def _step(guide, ref: str) -> tuple[int, PartStep]:
    for phase in guide.phases:
        for step in phase.steps:
            if isinstance(step, PartStep) and step.ref == ref:
                return phase.number, step
    raise AssertionError(ref)


def test_its_wires_go_in_with_the_long_wires_and_say_where_each_one_goes() -> None:
    doc, guide = _pedal_guide()
    phase, step = _step(guide, "RV1")
    assert phase == 7
    rv1 = next(c for c in doc.components if c.ref == "RV1")
    holes = all_pin_holes(rv1, REGISTRY(rv1.footprint_id))
    side = flying_lead_side([at for _pin, at in holes], doc.board)
    text = " ".join(step.notes)
    assert f"out over the {side} edge" in text
    for pin, at in holes:
        assert f"{format_hole(at)} to RV1 pin {pin.number}" in text
    assert "Cut each wire long enough to reach RV1" in text
    # Wires are cut, not bent: no lead pitch to bend them to.
    assert step.bend_template_mm is None
    assert step.span.endswith("3 wires")


def test_each_wire_in_the_step_is_named_by_its_net_and_the_colour_it_is_cut_in() -> None:
    """At the bench the thing in the hand is a coloured wire. The step says which colour goes
    in which pad, and the colour is the cut list's -- read from one assignment, so the two
    cannot name one wire differently."""
    _doc, guide = _pedal_guide()
    _phase, step = _step(guide, "RV1")
    text = " ".join(step.notes)
    for lead in (lead for lead in guide.lead_list if lead.ref == "RV1"):
        expected = f"{format_hole(lead.hole)} to RV1 pin {lead.pin} — {lead.net_name}, {lead.colour} wire"
        assert expected in text


def test_a_wire_carries_where_it_goes_in_ids_the_same_in_every_language() -> None:
    from perfboard_studio.guide import lead_marker

    assert lead_marker("RV1", "2", None) == "RV1·2"
    assert lead_marker("J1", "1", "T") == "J1·T"


def test_a_part_off_the_board_prints_no_names_beside_its_pads() -> None:
    """Its names are on its wires' markers; beside the pads they would lie on the wires."""
    from perfboard_studio.ui.bodies import pin_labels

    bus = pedal()
    mount(bus, "J1")
    j1 = next(c for c in bus.document.components if c.ref == "J1")
    named = dataclasses.replace(j1, pin_names=(("1", "T"), ("2", "S")))
    footprint = REGISTRY(named.footprint_id)
    assert footprint is not None
    assert pin_labels(footprint, named, BOARD.pitch) == ()


def test_its_nets_are_checked_only_once_its_wires_are_in() -> None:
    """A continuity check on a net the pot is on, asked for in phase 6 before the pot's wires
    exist, fails for a reason that is not a fault -- the first thing somebody following the
    guide would learn to ignore."""
    _doc, guide = _pedal_guide()
    for phase in guide.phases:
        for check in phase.checkpoints:
            if check.kind != "continuity":
                continue
            refs = {pin.component_ref for pin in check.pins}
            if refs & {"RV1", "J1"}:
                assert phase.number >= 7, check.title


def test_every_wire_is_on_the_cut_list_in_its_nets_colour() -> None:
    _doc, guide = _pedal_guide()
    leads = [lead for lead in guide.lead_list if lead.ref == "RV1"]
    assert [lead.pin for lead in leads] == ["1", "2", "3"]
    assert all(lead.cut_mm is None for lead in leads)
    ground = next(lead for lead in guide.lead_list if lead.net_name == "GND")
    assert ground.colour == "black"
    csv = cut_list_to_csv(guide)
    assert "wire off the board,GND" in csv and ",cut to fit" in csv
    assert "RV1 pin 2" in guide_to_html(guide)
    assert '"lead_list"' in guide_to_json(guide)
    assert any("plus the wires to the parts off the board" in tool for tool in guide.tools)


def test_a_known_length_is_what_the_cut_list_says() -> None:
    bus = pedal()
    rv1 = next(c for c in bus.document.components if c.ref == "RV1")
    assert bus.dispatch(
        "component.update", UpdateComponentPayload(id=rv1.id, footprint_id="wire-3-l150")
    ).ok
    guide = build_guide(bus.document, REGISTRY)
    assert {lead.cut_mm for lead in guide.lead_list} == {150.0}
    # The pad pin 2's wire lands in is wherever the example's placement put it.
    out = next(lead for lead in guide.lead_list if lead.ref == "RV1" and lead.pin == "2")
    pad = format_hole(out.hole, bus.document.board)
    assert f"wire off the board,OUT,{pad},RV1 pin 2,,150.0," in cut_list_to_csv(guide)
    _phase, step = _step(guide, "RV1")
    assert "Cut each wire 150 mm" in " ".join(step.notes)


def test_a_board_with_none_writes_no_list() -> None:
    """The ``language`` rule for an export: no key for an empty list, so every guide written
    before there was such a thing is still what it was."""
    guide = build_guide(pedal().document, REGISTRY)
    assert guide.lead_list == ()
    assert '"lead_list"' not in guide_to_json(guide)


def test_the_turkish_guide_says_it_in_turkish() -> None:
    _doc, guide = _pedal_guide("tr")
    _phase, step = _step(guide, "RV1")
    text = " ".join(step.notes)
    assert "bu kartın üzerinde değil" in text and "Tel tel:" in text
    assert "kart dışı tel" in cut_list_to_csv(guide)


# ---------------------------------------------------------------------------
# The sheet
# ---------------------------------------------------------------------------


def _sheet_symbol(footprint_id: str, **declared):
    bus = bus_for(create_empty_document(META))
    assert bus.dispatch(
        "part.add", AddPartPayload(ref="X1", footprint_id=footprint_id, value="", **declared)
    ).ok
    drawing = build_schematic(bus.document, REGISTRY)
    return next(s for s in drawing.symbols if s.ref == "X1"), drawing.notes


def test_on_the_sheet_it_is_what_it_says_it_is() -> None:
    assert _sheet_symbol("wire-3")[0].kind == "box"
    assert _sheet_symbol("wire-3", symbol="potentiometer")[0].kind == "potentiometer"
    assert (
        _sheet_symbol("wire-2", symbol="led", pin_names=(("1", "A"), ("2", "K")))[0].kind == "led"
    )


def test_a_declared_led_with_no_anode_named_stays_a_box_and_says_why() -> None:
    drawn, notes = _sheet_symbol("wire-2", symbol="led")
    assert drawn.kind == "box"
    assert any("X1: declared led" in note for note in notes)
    drawn, notes = _sheet_symbol("wire-2", symbol="potentiometer")
    assert drawn.kind == "box"
    assert any("a potentiometer has three leads" in note for note in notes)


# ---------------------------------------------------------------------------
# Which edge
# ---------------------------------------------------------------------------

BOARD = Board(
    type="pad-per-hole", cols=30, rows=20, pitch=2.54, thickness=1.6, material="FR4",
    pad_diameter=1.9, drill_diameter=1.0,
)


@pytest.mark.parametrize(
    "holes,side",
    [
        ([HoleCoord(10, 0), HoleCoord(11, 0)], "top"),
        ([HoleCoord(10, 19), HoleCoord(11, 19)], "bottom"),
        ([HoleCoord(0, 9), HoleCoord(0, 10)], "left"),
        ([HoleCoord(29, 9), HoleCoord(29, 10)], "right"),
    ],
)
def test_the_wires_leave_over_the_nearest_edge(holes: list[HoleCoord], side: str) -> None:
    assert flying_lead_side(holes, BOARD) == side


def _strip_at(col: int, row: int, rotation: int = 0):
    from perfboard_studio.model import ComponentInstance

    footprint = REGISTRY("wire-3")
    assert footprint is not None
    component = ComponentInstance(
        id="c1", ref="J1", value="", footprint_id="wire-3", anchor=HoleCoord(col, row),
        rotation=rotation,  # type: ignore[arg-type]
    )
    return component, footprint


def test_a_row_along_its_edge_runs_straight_off_it() -> None:
    from perfboard_studio.geometry import flying_lead_routes, substrate_edges_mm

    component, footprint = _strip_at(10, 1)
    routes = flying_lead_routes(component, footprint, BOARD, 3.0)
    top = substrate_edges_mm(BOARD).min_y
    for _number, points in routes:
        pad, edge, end = points
        assert edge.x == pad.x == end.x
        assert edge.y == pytest.approx(top) and end.y == pytest.approx(top - 3.0)


def test_a_row_pointing_at_its_edge_is_fanned_into_lanes() -> None:
    """Seen from above, three wires laid one over another down one row are one line; the
    cut list says three. Each wire with pads ahead of it steps into a lane of its own."""
    from perfboard_studio.geometry import FLYING_LEAD_LANE_MM, flying_lead_routes

    component, footprint = _strip_at(0, 9)  # pads A10, B10, C10: the row points left
    routes = dict(flying_lead_routes(component, footprint, BOARD, 3.0))
    # Pad 1 is nearest the edge and goes straight; the others step out 45 degrees first.
    assert len(routes["1"]) == 3 and len(routes["2"]) == 4 and len(routes["3"]) == 4
    lanes = [routes[n][-1].y for n in ("1", "2", "3")]
    assert [b - a for a, b in itertools.pairwise(lanes)] == pytest.approx(
        [-FLYING_LEAD_LANE_MM, -FLYING_LEAD_LANE_MM]
    )


def test_a_row_reversed_end_for_end_leaves_over_the_same_edge() -> None:
    """There is no mouth to face: the same pads in the other order are the same pads."""
    row = [HoleCoord(c, 1) for c in range(4, 8)]
    assert flying_lead_side(row, BOARD) == flying_lead_side(row[::-1], BOARD) == "top"


# ---------------------------------------------------------------------------
# KiCad
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,ids",
    [
        ("Connector_Wire:SolderWire-0.1sqmm_1x01_D0.4mm_OD1mm", ["wire-1"]),
        ("Connector_Wire:SolderWire-0.5sqmm_1x02_P4.6mm_D0.9mm_OD2.1mm", ["wire-2-p2"]),
        ("Connector_Wire:SolderWirePad_1x03_P3.81mm_Drill1.2mm", ["wire-3-p2"]),
    ],
)
def test_kicads_wire_pads_are_flying_leads(name: str, ids: list[str]) -> None:
    assert kicad_footprint_ids(name) == (ids, "")
    assert all(get_footprint(i) is not None for i in ids)


def test_a_kicad_pot_wired_from_the_panel_is_declared_a_pot() -> None:
    component = ImportedComponent(
        ref="RV1",
        value="B100k",
        footprint="Connector_Wire:SolderWire-0.5sqmm_1x03_P4.6mm_D0.9mm_OD2.1mm",
        lib_part="Device:R_Potentiometer",
    )
    suggestion, _notes = _suggest(component, 3, REGISTRY)
    assert suggestion.footprint_id == "wire-3-p2"
    assert suggestion.symbol == "potentiometer"


# ---------------------------------------------------------------------------
# An agent
# ---------------------------------------------------------------------------


def test_an_agent_mounts_a_placed_part_on_the_panel_and_nothing_else_changes_footprint() -> None:
    """``update_part(off_board=True)`` is the window's Mount on the Panel for an agent; any
    OTHER footprint on a placed part is still refused, for the reason it always was."""
    from perfboard_studio.mcp.session import BoardSession, SessionError

    session = BoardSession(document=parse_document_or_throw(PEDAL.read_text(encoding="utf-8")))
    result = session.update_part("RV1", off_board=True)
    assert result["ok"], result
    rv1 = next(c for c in session.document.components if c.ref == "RV1")
    assert rv1.footprint_id == "wire-3" and rv1.symbol == "potentiometer"
    with pytest.raises(SessionError, match="unplace_component"):
        session.update_part("J1", footprint_id="hdr-1x3")
    with pytest.raises(SessionError, match="one or the other"):
        session.update_part("J1", footprint_id="wire-2", off_board=True)
