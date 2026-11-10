"""A part on the solder side: turned over, not reflected (``ComponentInstance.side``).

See docs/ARCHITECTURE.md, "A part on the solder side is turned over, not reflected". What is
pinned here, one fact to a test: the file keeps every old byte and says the face only when
it is not the component side; the commands set the face and the reflection together and
refuse what nobody can hold; the rules that compare bodies compare them on one face; the
two rules only a solder-side part has fire where they should and nowhere else; and the
router lays no copper under a part on the solder side.
"""

from __future__ import annotations

import dataclasses

import pytest

from perfboard_studio import persist
from perfboard_studio.breadboard import breadboard, solderable_breadboard
from perfboard_studio.catalog import CATALOG
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    MirrorComponentPayload,
    PlaceComponentPayload,
    SetComponentSidePayload,
    SetComponentSidesPayload,
    _finalize_conductor,
    create_standard_registry,
)
from perfboard_studio.drc import SOLDER_SIDE_LEAD_MM, joint_face, run_drc
from perfboard_studio.footprints import footprint_lookup, standard_footprints
from perfboard_studio.geometry import all_pin_holes, same_hole
from perfboard_studio.mcp.session import new_board
from perfboard_studio.model import (
    Board,
    BoardSide,
    ComponentInstance,
    HoleCoord,
    PerfDocument,
    SolderTraceConductor,
    StripConductor,
    WireConductor,
)
from perfboard_studio.occupancy import build_occupancy
from perfboard_studio.router import RouteRequest, route_connection

REGISTRY = footprint_lookup()


def _part(
    ref: str,
    footprint_id: str,
    col: int,
    row: int,
    rotation: int = 0,
    *,
    side: BoardSide = "top",
    locked: bool = False,
) -> ComponentInstance:
    return ComponentInstance(
        id=f"c-{ref}",
        ref=ref,
        value="",
        footprint_id=footprint_id,
        anchor=HoleCoord(col, row),
        rotation=rotation,  # type: ignore[arg-type]
        mirrored=side == "bottom",
        locked=locked,
        side=side,
    )


def _doc(*parts: ComponentInstance, conductors: tuple = (), board: Board | None = None) -> PerfDocument:  # type: ignore[type-arg]
    blank = new_board(cols=40, rows=40, name="solder side")
    return dataclasses.replace(
        blank, board=board or blank.board, components=parts, conductors=conductors
    )


def _single_sided() -> Board:
    return dataclasses.replace(new_board(cols=40, rows=40).board, single_sided=True)


def _bus(doc: PerfDocument) -> CommandBus:
    return CommandBus(doc, create_standard_registry(), CommandContext(next_id=create_id_generator()))


def _rules(doc: PerfDocument, *rules: str) -> list[tuple[str, str, tuple[str, ...]]]:
    return [
        (v.rule, v.severity, tuple(v.component_ids))
        for v in run_drc(doc, REGISTRY)
        if v.rule in rules
    ]


def _pins(component: ComponentInstance) -> list[HoleCoord]:
    footprint = REGISTRY(component.footprint_id)
    assert footprint is not None
    return [hole for _pin, hole in all_pin_holes(component, footprint)]


# --- the file ----------------------------------------------------------------------------


def test_the_component_side_is_left_out_of_the_file() -> None:
    """The ``stripAxis`` rule: every board saved before a part had a face keeps its bytes,
    and a part on the solder side says so right after ``mirrored``."""
    top = persist.serialize_document(_doc(_part("R1", "r-axial-3", 5, 5)))
    bottom = persist.serialize_document(_doc(_part("R1", "r-axial-3", 5, 5, side="bottom")))
    assert '"side"' not in top
    assert '"mirrored": true,\n      "side": "bottom",\n      "locked": false' in bottom
    loaded = persist.deserialize_document(bottom)
    assert loaded.ok and not loaded.warnings
    assert loaded.document.components[0].side == "bottom"
    assert persist.serialize_document(loaded.document) == bottom


def test_a_file_with_an_unmirrored_part_on_the_solder_side_opens_mirrored() -> None:
    """One meaning, given it and said out loud, where the command refuses to make it."""
    text = persist.serialize_document(_doc(_part("R1", "r-axial-3", 5, 5, side="bottom")))
    text = text.replace('"mirrored": true,', '"mirrored": false,')
    loaded = persist.deserialize_document(text)
    assert loaded.ok
    [component] = loaded.document.components
    assert (component.side, component.mirrored) == ("bottom", True)
    assert any("on the solder side but not mirrored" in w for w in loaded.warnings)


def test_a_face_that_is_not_one_does_not_open() -> None:
    text = persist.serialize_document(_doc(_part("R1", "r-axial-3", 5, 5, side="bottom")))
    assert not persist.deserialize_document(text.replace('"bottom"', '"under"')).ok


# --- the commands ------------------------------------------------------------------------


def test_moving_to_the_solder_side_mirrors_and_back_unmirrors() -> None:
    bus = _bus(_doc(_part("R1", "r-axial-3", 5, 5)))
    result = bus.dispatch("component.setSide", SetComponentSidePayload(id="c-R1", side="bottom"))
    assert result.ok, result
    [r1] = bus.document.components
    assert (r1.side, r1.mirrored) == ("bottom", True)
    assert bus.history() == ("Move R1 to Solder Side",)
    assert bus.dispatch("component.setSide", SetComponentSidePayload(id="c-R1", side="top")).ok
    [r1] = bus.document.components
    assert (r1.side, r1.mirrored) == ("top", False)
    assert bus.history()[-1] == "Move R1 to Component Side"


def _collinear(footprint_id: str) -> bool:
    footprint = REGISTRY(footprint_id)
    if footprint is None or not footprint.pins:
        return False
    return len({p.d_col for p in footprint.pins}) == 1 or len({p.d_row for p in footprint.pins}) == 1


#: Every footprint a part can have -- the registry's and every catalogue part's generated
#: one (a terminal block, a JST header, a sensor, ``wire-<n>``) -- whose pins lie on a line.
COLLINEAR = sorted(
    i for i in set(standard_footprints()) | {p.footprint_id for p in CATALOG} if _collinear(i)
)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_a_part_with_its_pins_in_a_line_turns_over_in_its_own_holes(rotation: int) -> None:
    """Pushed through the same holes from the other face: turned about the line its pins
    lie on, every pin keeps its hole and its net, and only the body changes face."""
    assert {"r-axial-3", "hdr-1x4", "to92", "screw-terminal-2", "led-5mm"} <= set(COLLINEAR)
    moved = []
    for footprint_id in COLLINEAR:
        part = _part("P1", footprint_id, 20, 20, rotation)
        bus = _bus(_doc(part))
        result = bus.dispatch("component.setSide", SetComponentSidePayload(id="c-P1", side="bottom"))
        assert result.ok, (footprint_id, result)
        [turned] = bus.document.components
        assert (turned.side, turned.mirrored) == ("bottom", True)
        if _pins(turned) != _pins(part):
            moved.append(footprint_id)
        assert result.description == "Move P1 to Solder Side", footprint_id
    assert moved == []


def test_r1_on_the_ne555_board_keeps_its_net() -> None:
    """The board the issue was found on: R1 at half a turn, which used to land on W6."""
    r1 = _part("R1", "r-axial-3", 19, 5, 180)
    bus = _bus(_doc(r1))
    assert bus.dispatch("component.setSide", SetComponentSidePayload(id="c-R1", side="bottom")).ok
    [turned] = bus.document.components
    assert _pins(turned) == _pins(r1) == [HoleCoord(19, 5), HoleCoord(16, 5)]
    assert (turned.rotation, turned.mirrored) == (0, True)


@pytest.mark.parametrize("footprint_id", ["r-axial-3", "to92", "dip-8", "hdr-2x5", "relay-spdt"])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_over_and_back_lands_where_it_started(footprint_id: str, rotation: int) -> None:
    part = _part("P1", footprint_id, 20, 20, rotation)
    bus = _bus(_doc(part))
    assert bus.dispatch("component.setSide", SetComponentSidePayload(id="c-P1", side="bottom")).ok
    assert bus.dispatch("component.setSide", SetComponentSidePayload(id="c-P1", side="top")).ok
    assert bus.document.components == (part,)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_a_dip_turned_over_keeps_its_holes_and_swaps_its_rows(rotation: int) -> None:
    """No turn keeps a two-row part's pins on their nets: its rows swap, in the holes it
    took, and the command says the wiring needs redoing."""
    dip = _part("U1", "dip-8", 20, 20, rotation)
    bus = _bus(_doc(dip))
    result = bus.dispatch("component.setSide", SetComponentSidePayload(id="c-U1", side="bottom"))
    assert result.ok
    [turned] = bus.document.components
    before, after = _pins(dip), _pins(turned)
    assert sorted(after) == sorted(before) and after != before
    # Pin 1 and pin 8 face each other across the package; turned over, they trade holes.
    assert (after[0], after[7]) == (before[7], before[0])
    assert result.description == (
        "Move U1 to Solder Side: its rows of pins swapped sides, so its wiring needs redoing"
    )
    assert bus.history() == (result.description,)


def test_what_a_turn_did_to_the_wiring_is_said_in_turkish() -> None:
    from perfboard_studio.ui.engine_text import say
    from perfboard_studio.ui.i18n import language, set_language

    bus = _bus(_doc(_part("U1", "dip-8", 20, 20)))
    over = bus.dispatch("component.setSide", SetComponentSidePayload(id="c-U1", side="bottom"))
    back = bus.dispatch("component.setSide", SetComponentSidePayload(id="c-U1", side="top"))
    assert over.ok and back.ok
    before = language()
    set_language("tr")
    try:
        said = [say(over.description), say(back.description)]
    finally:
        set_language(before)
    assert said == [
        "U1 parçasını lehim yüzüne taşı: bacak sıraları yer değiştirdi, "
        "kablolamasını yeniden yapmanız gerekir",
        "U1 parçasını parça yüzüne taşı: bacak sıraları yer değiştirdi, "
        "kablolamasını yeniden yapmanız gerekir",
    ]


def test_a_relay_whose_pins_are_not_symmetric_says_they_moved() -> None:
    relay = _part("K1", "relay-spdt", 20, 20)
    bus = _bus(_doc(relay))
    result = bus.dispatch("component.setSide", SetComponentSidePayload(id="c-K1", side="bottom"))
    assert result.ok
    [turned] = bus.document.components
    if sorted(_pins(turned)) == sorted(_pins(relay)):
        pytest.skip("relay-spdt's pins are symmetric about the turn")
    assert result.description == (
        "Move K1 to Solder Side: its pins moved to other holes, so its wiring needs redoing"
    )


def test_a_part_mirrored_on_the_component_side_moves_over_without_its_holes_moving() -> None:
    """Setting, not toggling: a board drawn before parts had a face -- a part mirrored to
    mean "from the solder side" -- is moved there with its pins where they were."""
    mirrored = dataclasses.replace(_part("U1", "dip-8", 10, 10), mirrored=True)
    bus = _bus(_doc(mirrored))
    assert bus.dispatch("component.setSide", SetComponentSidePayload(id="c-U1", side="bottom")).ok
    [moved] = bus.document.components
    assert moved.mirrored and _pins(moved) == _pins(mirrored)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (SetComponentSidePayload(id="c-R1", side="top"), "nothing-to-do"),
        (SetComponentSidePayload(id="c-R1", side="under"), "invalid-side"),  # type: ignore[arg-type]
        (SetComponentSidePayload(id="c-L1", side="bottom"), "component-locked"),
    ],
)
def test_what_set_side_refuses(payload: SetComponentSidePayload, code: str) -> None:
    bus = _bus(_doc(_part("R1", "r-axial-3", 5, 5), _part("L1", "r-axial-3", 5, 20, locked=True)))
    result = bus.dispatch("component.setSide", payload)
    assert (result.ok, result.code) == (False, code)


def test_a_part_on_the_solder_side_cannot_be_unmirrored() -> None:
    """It is mirrored by being there; the way back is the other face."""
    bus = _bus(_doc(_part("R1", "r-axial-3", 5, 5, side="bottom")))
    result = bus.dispatch("component.mirror", MirrorComponentPayload(id="c-R1", mirrored=False))
    assert (result.ok, result.code) == (False, "solder-side-unmirrored")


def test_a_group_moves_over_in_one_step_or_not_at_all() -> None:
    doc = _doc(_part("R1", "r-axial-3", 5, 5), _part("R2", "r-axial-3", 5, 10))
    bus = _bus(doc)
    both = SetComponentSidesPayload(
        sides=tuple(SetComponentSidePayload(id=i, side="bottom") for i in ("c-R1", "c-R2"))
    )
    assert bus.dispatch("component.setSideMany", both).ok
    assert [c.side for c in bus.document.components] == ["bottom", "bottom"]
    assert bus.history() == ("Move 2 component(s) to another side",)
    bus.undo()
    assert bus.document == doc

    locked = _doc(_part("R1", "r-axial-3", 5, 5), _part("R2", "r-axial-3", 5, 10, locked=True))
    bus = _bus(locked)
    assert not bus.dispatch("component.setSideMany", both).ok
    assert bus.document == locked


def test_a_part_placed_on_the_solder_side_is_mirrored() -> None:
    bus = _bus(_doc())
    placed = bus.dispatch(
        "component.place",
        PlaceComponentPayload(ref="R1", value="", footprint_id="r-axial-3", anchor=HoleCoord(5, 5), side="bottom"),
    )
    assert placed.ok, placed
    [r1] = bus.document.components
    assert (r1.side, r1.mirrored) == ("bottom", True)
    refused = bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref="R2", value="", footprint_id="r-axial-3", anchor=HoleCoord(5, 10), side="bottom", mirrored=False
        ),
    )
    assert (refused.ok, refused.code) == (False, "solder-side-unmirrored")


def test_a_breadboard_has_no_solder_side_and_a_solderable_one_does() -> None:
    """A solderless breadboard's holes are in plastic, with clips under them: there is no
    underside to put a part on. A solderable breadboard is copper, soldered like any board."""
    for board, ok in ((breadboard("400"), False), (solderable_breadboard("400"), True)):
        bus = _bus(_doc(_part("R1", "r-axial-3", 5, 5), board=board))
        result = bus.dispatch("component.setSide", SetComponentSidePayload(id="c-R1", side="bottom"))
        assert result.ok is ok, (board.type, result)
        if not ok:
            assert result.code == "no-solder-side"


# --- bodies meet on their own face -------------------------------------------------------


def test_two_parts_on_two_faces_do_not_overlap() -> None:
    """The same resistor in the same holes' neighbourhood, one on each face: rule 1 compares
    bodies on one face. Turned onto one face, they overlap again."""
    a = _part("R1", "r-axial-6", 10, 10)
    b = _part("R2", "r-axial-6", 10, 11, side="bottom")
    assert _rules(_doc(a, b), "component-body-overlap") == []
    on_one_face = _doc(a, dataclasses.replace(b, side="top", mirrored=False))
    assert [r for r, *_ in _rules(on_one_face, "component-body-overlap")] == ["component-body-overlap"]


def test_only_the_component_side_is_measured_against_the_case() -> None:
    """``height_limit_mm`` is the room above the board; a body below it is under the board."""
    tall = _part("C1", "c-elec-d8-p3", 10, 10)
    doc = _doc(tall)
    doc = dataclasses.replace(doc, height_limit_mm=5.0)
    assert [r for r, *_ in _rules(doc, "component-too-tall")] == ["component-too-tall"]
    under = dataclasses.replace(doc, components=(dataclasses.replace(tall, side="bottom", mirrored=True),))
    assert _rules(under, "component-too-tall") == []


def test_body_covers_asks_the_face() -> None:
    dip = _part("U1", "dip-8", 10, 10, side="bottom")
    occupancy = build_occupancy(_doc(dip), REGISTRY)
    inside = _inside(dip)
    assert occupancy.body_covers(inside, "bottom") == "c-U1"
    assert occupancy.body_covers(inside, "top") is None
    assert occupancy.body_covers(inside) is None  # The component side, as it always was.


# --- copper-under-body -------------------------------------------------------------------


def _inside(component: ComponentInstance) -> HoleCoord:
    """A hole between a DIP's two rows of pins, under its body and none of its pins."""
    pins = _pins(component)
    cols = sorted({p.col for p in pins})
    rows = sorted({p.row for p in pins})
    return HoleCoord((cols[0] + cols[-1]) // 2, (rows[0] + rows[-1]) // 2)


def _row_under(component: ComponentInstance) -> tuple[HoleCoord, HoleCoord]:
    """A run across a horizontal resistor's body, from above it to below it, at a column
    between its two pins."""
    left, right = _pins(component)
    col = (left.col + right.col) // 2
    return HoleCoord(col, left.row - 2), HoleCoord(col, left.row + 2)


def test_a_trace_under_a_part_on_the_solder_side_is_named() -> None:
    resistor = _part("R1", "r-axial-6", 10, 10, side="bottom")
    start, end = _row_under(resistor)
    trace = SolderTraceConductor(
        id="cond-1", path=tuple(HoleCoord(start.col, row) for row in range(start.row, end.row + 1))
    )
    findings = [v for v in run_drc(_doc(resistor, conductors=(trace,)), REGISTRY) if v.rule == "copper-under-body"]
    assert [(v.severity, v.component_ids, v.conductor_ids) for v in findings] == [
        ("warning", ("c-R1",), ("cond-1",))
    ]
    assert findings[0].message.startswith("Solder trace cond-1 (")
    assert "runs under R1, which is on the solder side" in findings[0].message
    # The same resistor on the component side stands over the trace, not on it.
    on_top = _doc(dataclasses.replace(resistor, side="top", mirrored=False), conductors=(trace,))
    assert _rules(on_top, "copper-under-body") == []


def test_a_wire_is_measured_on_the_holes_it_lies_over() -> None:
    """A wire touches only its ends, but it lies over the holes between them, and that is
    what a body on top of it hides; a top jumper is on the other face altogether."""
    resistor = _part("R1", "r-axial-6", 10, 10, side="bottom")
    start, end = _row_under(resistor)
    for kind, named in (("bare-wire", True), ("insulated-wire", True)):
        wire = WireConductor(id="cond-1", path=(start, end), kind=kind)  # type: ignore[arg-type]
        assert bool(_rules(_doc(resistor, conductors=(wire,)), "copper-under-body")) is named, kind
    jumper = WireConductor(id="cond-1", path=(start, end), kind="top-jumper", side="top")
    assert _rules(_doc(resistor, conductors=(jumper,)), "copper-under-body") == []


def test_copper_ending_at_the_parts_own_pin_is_not_named() -> None:
    """Measured strictly between the ends, as ``jumper-under-body`` measures a jumper: a
    trace that reaches a DIP's pin on the solder side is how that pin is wired."""
    dip = _part("U1", "dip-8", 10, 10, side="bottom")
    pin = _pins(dip)[0]
    trace = SolderTraceConductor(id="cond-1", path=(HoleCoord(pin.col, pin.row - 2), HoleCoord(pin.col, pin.row - 1), pin))
    assert _rules(_doc(dip, conductors=(trace,)), "copper-under-body") == []


def test_a_stripboards_own_strips_are_not_copper_under_a_body() -> None:
    """A strip is the board, there before any part: a part on the solder side of a
    stripboard stands on strips by definition, and naming every one would bury the finding
    for a wire somebody laid there."""
    resistor = _part("R1", "r-axial-6", 10, 10, side="bottom")
    start, end = _row_under(resistor)
    strip = StripConductor(id="strip-1", path=tuple(HoleCoord(start.col, row) for row in range(start.row, end.row + 1)))
    assert _rules(_doc(resistor, conductors=(strip,)), "copper-under-body") == []
    wire = WireConductor(id="cond-1", path=(start, end), kind="bare-wire")
    assert _rules(_doc(resistor, conductors=(strip, wire)), "copper-under-body") != []


def test_a_joint_under_a_body_on_its_face_is_named_from_either_face() -> None:
    """A component-side resistor's joints are on the solder side, and a DIP turned over
    onto that face, its body over one of them, hides it. The DIP is put in from underneath
    on a double-sided board, so ITS joints are on the component side, and the resistor's
    body standing over one hides that. Two findings, each said on its own face. With both
    on the component side neither joint is under a body on its face, and the two bodies
    are rule 1's business, not this one's."""
    dip = _part("U1", "dip-8", 10, 10, side="bottom")
    inside = _inside(dip)
    assert build_occupancy(_doc(dip), REGISTRY).body_covers(inside, "bottom") == "c-U1"
    resistor = _part("R1", "r-axial-6", inside.col, inside.row, 90)
    assert any(same_hole(h, inside) for h in _pins(resistor))
    findings = [
        (v.component_ids, v.message.split(", or")[0])
        for v in run_drc(_doc(dip, resistor), REGISTRY)
        if v.rule == "copper-under-body"
    ]
    assert findings == [
        (("c-U1", "c-R1"), "U1's joint at H14 is under R1, on the component side. Solder U1 before fitting R1"),
        (("c-R1", "c-U1"), "R1's joint at I12 is under U1, on the solder side. Solder R1 before fitting U1"),
    ]
    on_top = _doc(dataclasses.replace(dip, side="top", mirrored=False), resistor)
    assert _rules(on_top, "copper-under-body") == []


def test_where_a_part_on_the_solder_side_is_soldered() -> None:
    """Through to the component side, unless there is no copper there."""
    bottom = _part("R1", "r-axial-3", 5, 5, side="bottom")
    double = new_board(cols=40, rows=40).board
    assert joint_face(_part("R1", "r-axial-3", 5, 5), double) == "bottom"
    assert joint_face(bottom, double) == "top"
    assert joint_face(bottom, _single_sided()) == "bottom"


# --- joint-under-body --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("footprint_id", "severity"),
    [
        # A DIP sits on the board over its pins: no iron reaches them. An error.
        ("dip-8", "error"),
        # An LED stands on its leads over its pins: left long, it can be soldered. A warning.
        ("led-5mm", "warning"),
        # An axial resistor's pins are past the ends of its body: nothing to say.
        ("r-axial-6", None),
    ],
)
def test_a_part_turned_onto_a_single_sided_board_is_soldered_beside_its_body(
    footprint_id: str, severity: str | None
) -> None:
    part = _part("X1", footprint_id, 10, 10, side="bottom")
    single = _rules(_doc(part, board=_single_sided()), "joint-under-body")
    assert single == ([] if severity is None else [("joint-under-body", severity, ("c-X1",))])
    # A double-sided board solders it on the component side, clear of its body.
    assert _rules(_doc(part), "joint-under-body") == []
    # And on the component side of the single-sided board it is soldered as always.
    on_top = dataclasses.replace(part, side="top", mirrored=False)
    assert _rules(_doc(on_top, board=_single_sided()), "joint-under-body") == []


def test_the_leds_warning_says_how_long_to_leave_its_leads() -> None:
    led = _part("D1", "led-5mm", 10, 10, side="bottom")
    [finding] = [v for v in run_drc(_doc(led, board=_single_sided()), REGISTRY) if v.rule == "joint-under-body"]
    assert f"Leave the leads about {SOLDER_SIDE_LEAD_MM} mm long" in finding.message


# --- the router ----------------------------------------------------------------------------


def test_the_router_lays_no_solder_side_copper_under_a_part_on_that_side() -> None:
    """``copper-under-body`` is never a finding about copper the router chose to lay. On the
    component side the resistor stands over the run and the straight trace is the answer;
    turned over, the run goes round it."""
    resistor = _part("R1", "r-axial-6", 10, 10)
    start, end = _row_under(resistor)
    request = RouteRequest(from_=start, to=end)

    over = route_connection(_doc(resistor), REGISTRY, request)
    assert over.ok and over.best is not None
    straight = over.best.conductors[0].path
    assert all(hole.col == start.col for hole in straight)

    turned = _doc(dataclasses.replace(resistor, side="bottom", mirrored=True))
    occupancy = build_occupancy(turned, REGISTRY)
    under = route_connection(turned, REGISTRY, request)
    assert under.ok and under.best is not None
    for candidate in under.alternatives:
        for conductor in candidate.conductors:
            assert not [h for h in conductor.path[1:-1] if occupancy.body_covers(h, "bottom")], candidate.strategy
    laid = tuple(_finalize_conductor(c, f"cond-{i}") for i, c in enumerate(under.best.conductors))
    assert _rules(dataclasses.replace(turned, conductors=laid), "copper-under-body") == []


# --- the guide ---------------------------------------------------------------------------


def test_a_part_on_the_solder_side_is_fitted_last_after_phase_sevens_wires() -> None:
    """Over copper already laid and checked, lowest first; phase 7 says so only here."""
    from perfboard_studio.guide import PartStep, build_guide

    led = _part("D1", "led-5mm", 20, 20, side="bottom")
    resistor = _part("R2", "r-axial-3", 20, 30, side="bottom")
    top = _part("R1", "r-axial-3", 5, 5)
    wire = WireConductor(id="cond-1", path=(HoleCoord(2, 2), HoleCoord(30, 2)), kind="insulated-wire")
    guide = build_guide(_doc(led, resistor, top, conductors=(wire,)), REGISTRY)
    seven = guide.phases[7]
    assert seven.title == "Long insulated wires, then the solder-side parts"
    assert seven.summary.endswith("since it hides what is under it.")
    kinds = [(step.kind, getattr(step, "ref", None)) for step in seven.steps]
    assert kinds[0][0] != "part" and [ref for kind, ref in kinds if kind == "part"] == ["R2", "D1"]
    [r1] = [s for p in guide.phases for s in p.steps if isinstance(s, PartStep) and s.ref == "R1"]
    assert r1.side == "top" and not any("SOLDER side" in n for n in r1.notes)
    [d1] = [s for s in seven.steps if isinstance(s, PartStep) and s.ref == "D1"]
    assert d1.side == "bottom"
    assert any(n.startswith("This part goes on the SOLDER side") and n.endswith("on the component side.") for n in d1.notes)

    plain = build_guide(_doc(top, conductors=(wire,)), REGISTRY)
    assert plain.phases[7].title == "Long insulated wires"


def test_the_guide_says_it_in_turkish() -> None:
    from perfboard_studio.guide import GuideOptions, PartStep, build_guide

    led = _part("D1", "led-5mm", 20, 20, side="bottom")
    guide = build_guide(_doc(led, board=_single_sided()), REGISTRY, GuideOptions(language="tr"))
    seven = guide.phases[7]
    assert seven.title == "Uzun izoleli teller, ardından lehim yüzündeki parçalar"
    [d1] = [s for s in seven.steps if isinstance(s, PartStep)]
    assert any(n.startswith("Bu parça LEHİM yüzüne gelir") and "parça yüzünde bakır yok" in n for n in d1.notes)


def test_the_guides_json_says_the_face_only_when_it_is_the_solder_side() -> None:
    from perfboard_studio.guide import build_guide
    from perfboard_studio.guide_export import guide_to_json

    top = guide_to_json(build_guide(_doc(_part("R1", "r-axial-3", 5, 5)), REGISTRY))
    bottom = guide_to_json(build_guide(_doc(_part("R1", "r-axial-3", 5, 5, side="bottom")), REGISTRY))
    assert '"side"' not in top
    assert '"side": "bottom"' in bottom


# --- 3D and STEP -------------------------------------------------------------------------


def _union(bounds: list[tuple[float, ...]]) -> tuple[float, ...]:
    return (
        min(b[0] for b in bounds), max(b[1] for b in bounds),
        min(b[2] for b in bounds), max(b[3] for b in bounds),
        min(b[4] for b in bounds), max(b[5] for b in bounds),
    )


@pytest.mark.parametrize(("footprint_id", "rotation"), [("to92", 0), ("dip-8", 90), ("c-elec-d8-p3", 270), ("r-axial-6", 180)])
def test_in_3d_a_part_on_the_solder_side_hangs_below_the_board(footprint_id: str, rotation: int) -> None:
    """Turned over, not reflected: the same footprint as the part mirrored on the component
    side, and its height below the board where that one's is above."""
    from perfboard_studio.ui import view3d

    board = new_board(cols=40, rows=40).board
    top = dataclasses.replace(_part("X1", footprint_id, 15, 15, rotation), mirrored=True)
    bottom = _part("X1", footprint_id, 15, 15, rotation, side="bottom")
    above = _union([a.GetBounds() for a in view3d.build_component(REGISTRY, top, board)])
    below = _union([a.GetBounds() for a in view3d.build_component(REGISTRY, bottom, board)])
    assert below[:4] == pytest.approx(above[:4], abs=1e-3)
    t = board.thickness
    assert (below[4], below[5]) == pytest.approx((-t - above[5], -t - above[4]), abs=1e-3)
    assert below[4] < -t - 2.0 and above[5] > 2.0


def test_in_step_a_part_on_the_solder_side_is_the_same_solids_reflected_through_the_board() -> None:
    from perfboard_studio.step_export import Box, Cylinder, board_model

    def solids(component: ComponentInstance) -> list[object]:
        [part] = [p for p in board_model(_doc(component), REGISTRY)[1:] if p.name == "U1"]
        return [s.shape for s in part.solids]

    top = dataclasses.replace(_part("U1", "dip-8", 15, 15), mirrored=True)
    above, below = solids(top), solids(_part("U1", "dip-8", 15, 15, side="bottom"))
    t = new_board().board.thickness
    assert len(above) == len(below)
    for up, down in zip(above, below, strict=True):
        if isinstance(up, Box):
            assert isinstance(down, Box)
            assert down.low == pytest.approx((up.low[0], up.low[1], t - up.high[2]))
            assert down.high == pytest.approx((up.high[0], up.high[1], t - up.low[2]))
        else:
            assert isinstance(up, Cylinder) and isinstance(down, Cylinder)
            assert down.base == pytest.approx((up.base[0], up.base[1], t - up.base[2]))
            assert down.axis == pytest.approx((up.axis[0], up.axis[1], -up.axis[2]))
    body = below[0]
    assert isinstance(body, Box) and body.high[2] == pytest.approx(0.0)


# --- in the window's language --------------------------------------------------------------


def _said_both_ways(message: str, names: dict[str, str]) -> tuple[str, str]:
    from perfboard_studio.ui.engine_text import finding_text
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    try:
        set_language("en")
        english = finding_text(message, names)
        set_language("tr")
        return english, finding_text(message, names)
    finally:
        set_language(before)


def test_every_solder_side_finding_is_said_in_turkish() -> None:
    """No board in the repository has a part on the solder side, so
    ``test_every_finding_on_every_board_is_said_in_turkish`` never meets these findings:
    each is produced here by the real rule and said through the panel's own path."""
    from perfboard_studio.ui.engine_text import names_in

    resistor = _part("R1", "r-axial-6", 10, 10, side="bottom")
    start, end = _row_under(resistor)
    trace = SolderTraceConductor(
        id="cond-1", path=tuple(HoleCoord(start.col, row) for row in range(start.row, end.row + 1))
    )
    wire = WireConductor(id="cond-2", path=(start, end), kind="bare-wire")
    dip = _part("U1", "dip-8", 10, 10, side="bottom")
    inside = _inside(dip)
    docs = [
        _doc(resistor, conductors=(trace,)),
        _doc(resistor, conductors=(wire,)),
        _doc(dip, _part("R1", "r-axial-6", inside.col, inside.row, 90)),
        _doc(dip, board=_single_sided()),
        _doc(_part("D1", "led-5mm", 10, 10, side="bottom"), board=_single_sided()),
    ]
    said: list[tuple[str, str]] = []
    for doc in docs:
        for v in run_drc(doc, REGISTRY):
            if v.rule in ("copper-under-body", "joint-under-body"):
                said.append(_said_both_ways(v.message, names_in(doc, v.message, v.conductor_ids)))
    assert len(said) == 6
    untranslated = [english for english, turkish in said if turkish == english]
    assert untranslated == []
    joined = " ".join(turkish for _english, turkish in said)
    for english_word in ("solder side", "component side", "joint", "Solder trace", "Bare wire", "cond-"):
        assert english_word not in joined, english_word
    assert "Lehim yolu" in joined and "lehim yüzündeki U1" in joined


def test_moving_a_part_over_and_its_refusals_are_said_in_turkish() -> None:
    from perfboard_studio.ui.engine_text import say
    from perfboard_studio.ui.i18n import language, set_language

    bus = _bus(_doc(_part("R1", "r-axial-3", 5, 5), _part("R2", "r-axial-3", 5, 10)))
    results = [
        bus.dispatch("component.setSide", SetComponentSidePayload(id="c-R1", side="bottom")),
        bus.dispatch("component.setSide", SetComponentSidePayload(id="c-R1", side="top")),
        bus.dispatch(
            "component.setSideMany",
            SetComponentSidesPayload(
                sides=tuple(SetComponentSidePayload(id=i, side="bottom") for i in ("c-R1", "c-R2"))
            ),
        ),
    ]
    assert all(result.ok for result in results)
    refusals = [
        bus.dispatch("component.setSide", SetComponentSidePayload(id="c-R1", side="bottom")),
        bus.dispatch("component.mirror", MirrorComponentPayload(id="c-R1", mirrored=False)),
        _bus(_doc(_part("R1", "r-axial-3", 5, 5), board=breadboard("400"))).dispatch(
            "component.setSide", SetComponentSidePayload(id="c-R1", side="bottom")
        ),
        bus.dispatch(
            "component.place",
            PlaceComponentPayload(
                ref="R3", value="", footprint_id="r-axial-3", anchor=HoleCoord(5, 20), side="bottom", mirrored=False
            ),
        ),
    ]
    assert [r.code for r in refusals] == [
        "nothing-to-do", "solder-side-unmirrored", "no-solder-side", "solder-side-unmirrored"
    ]
    english = [r.description for r in results] + [r.message for r in refusals]
    before = language()
    set_language("tr")
    try:
        turkish = [say(sentence) for sentence in english]
    finally:
        set_language(before)
    assert [t for e, t in zip(english, turkish, strict=True) if t == e] == []
    assert turkish[:3] == [
        "R1 parçasını lehim yüzüne taşı",
        "R1 parçasını parça yüzüne taşı",
        "2 parçayı öbür yüze taşı",
    ]


def test_a_copied_part_keeps_its_face_and_a_breadboard_takes_it_on_top() -> None:
    from perfboard_studio.ui.clipboard import block_from_json, block_to_json, paste_payload

    doc = _doc(_part("R1", "r-axial-3", 5, 5, side="bottom"), _part("R2", "r-axial-3", 5, 10))
    text = block_to_json(doc, ["c-R1", "c-R2"])
    assert text.count('"side"') == 1
    block = block_from_json(text)
    assert block is not None
    assert [(c.side, c.mirrored) for c in block.components] == [("bottom", True), ("top", False)]
    for board, face in ((None, "bottom"), (breadboard("400"), "top")):
        target = _doc(board=board)
        bus = _bus(target)
        assert bus.dispatch("block.place", paste_payload(target, block, HoleCoord(10, 2)).payload).ok
        r1 = next(c for c in bus.document.components if c.footprint_id == "r-axial-3" and c.mirrored)
        assert (r1.side, r1.mirrored) == (face, True)
