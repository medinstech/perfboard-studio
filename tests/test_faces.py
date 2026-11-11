"""Copper on either face of a double-sided board (0.25).

A solder trace may lie on the component side of a board with pads there, and a net may
prefer a face. This file pins what the document holds and what the commands accept; the
router, DRC and the guide each test their own part where they live.
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

from perfboard_studio import persist
from perfboard_studio.autoroute import AutorouteOptions, AutoroutePlan, plan_autoroute, score_plan
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    KEEP,
    AddConductorPayload,
    AddNetPayload,
    NewSolderTraceConductor,
    UpdateNetPayload,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.connectivity import extract_physical_nets
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import (
    all_pin_holes,
    format_hole,
    holes_under_line,
    is_adjacent4,
)
from perfboard_studio.guide import ConductorStep, GuideOptions, build_guide
from perfboard_studio.lvs import run_lvs
from perfboard_studio.model import (
    BoardSide,
    HoleCoord,
    PerfDocument,
    SolderTraceConductor,
    has_component_side_copper,
)
from perfboard_studio.occupancy import build_occupancy
from perfboard_studio.router import RouterFaces, RouterOptions, options_for_style
from perfboard_studio.ui.clipboard import _new_conductor
from perfboard_studio.wiringstats import wiring_stats

LOOKUP = footprint_lookup()

REPO = pathlib.Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO / "tools" / "diffcheck" / "golden"
NE555 = GOLDEN_DIR / "ne555.perf"


def _doc() -> PerfDocument:
    return persist.parse_document_or_throw(NE555.read_text(encoding="utf-8"))


def _bus(doc: PerfDocument) -> CommandBus:
    return CommandBus(
        doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc))
    )


def _free_run(doc: PerfDocument) -> tuple[HoleCoord, ...]:
    """Three holes in a row that nothing on the ne555 golden uses: the bottom row's end."""
    row = doc.board.rows - 1
    cols = doc.board.cols
    return tuple(HoleCoord(col, row) for col in range(cols - 3, cols))


def test_no_golden_fixture_has_copper_on_the_component_side() -> None:
    """Every fixture is a dump of the single-face engine, so none holds a top trace and
    every one keeps its bytes; the day a regenerated fixture holds one, this says so."""
    for path in sorted(GOLDEN_DIR.glob("*.perf")):
        doc = persist.parse_document_or_throw(path.read_text(encoding="utf-8"))
        assert not any(
            isinstance(c, SolderTraceConductor) and c.side == "top" for c in doc.conductors
        ), path.name
        assert all(n.preferred_side is None for n in doc.nets), path.name


def test_a_trace_on_the_component_side_is_laid_and_saved_as_it_is() -> None:
    doc = _doc()
    assert has_component_side_copper(doc.board)
    bus = _bus(doc)

    result = bus.dispatch(
        "conductor.add",
        AddConductorPayload(conductor=NewSolderTraceConductor(path=_free_run(doc), side="top")),
    )

    assert result.ok, result.message
    trace = bus.document.conductors[-1]
    assert isinstance(trace, SolderTraceConductor) and trace.side == "top"
    again = persist.parse_document_or_throw(persist.serialize_document(bus.document))
    assert again.conductors[-1] == trace
    assert '"side": "top"' in persist.serialize_document(bus.document)


@pytest.mark.parametrize(
    "change",
    [{"single_sided": True}, {"type": "stripboard"}, {"type": "plain"}, {"type": "breadboard"}],
    ids=["single-sided", "stripboard", "plain", "breadboard"],
)
def test_no_trace_is_laid_on_a_face_with_no_pads(change: dict[str, object]) -> None:
    doc = _doc()
    board = dataclasses.replace(doc.board, **change)  # type: ignore[arg-type]
    doc = dataclasses.replace(doc, board=board)
    assert not has_component_side_copper(board)

    result = _bus(doc).dispatch(
        "conductor.add",
        AddConductorPayload(conductor=NewSolderTraceConductor(path=_free_run(doc), side="top")),
    )

    assert not result.ok
    assert result.code == "no-copper-on-face"


def test_a_file_with_a_top_trace_on_a_single_sided_board_still_opens() -> None:
    """As a conductor off the board does: DRC reports it, the builder keeps their file."""
    doc = _doc()
    trace = SolderTraceConductor(id="t", path=_free_run(doc), side="top")
    doc = dataclasses.replace(
        doc,
        board=dataclasses.replace(doc.board, single_sided=True),
        conductors=(*doc.conductors, trace),
    )

    again = persist.parse_document_or_throw(persist.serialize_document(doc))

    assert again.conductors[-1] == trace


def test_a_nets_preferred_face_is_set_kept_and_cleared_and_left_out_of_the_file_at_none() -> None:
    doc = _doc()
    bus = _bus(doc)
    net = doc.nets[0]
    plain = persist.serialize_document(doc)
    assert "preferredSide" not in plain

    assert bus.dispatch("net.update", UpdateNetPayload(id=net.id, preferred_side="top")).ok
    assert bus.document.nets[0].preferred_side == "top"
    text = persist.serialize_document(bus.document)
    assert '"preferredSide": "top"' in text
    assert persist.parse_document_or_throw(text).nets[0].preferred_side == "top"

    assert bus.dispatch("net.update", UpdateNetPayload(id=net.id, name="RENAMED")).ok
    assert bus.document.nets[0].preferred_side == "top", "KEEP is the default"

    assert bus.dispatch("net.update", UpdateNetPayload(id=net.id, preferred_side=None)).ok
    assert bus.document.nets[0].preferred_side is None
    assert UpdateNetPayload(id=net.id).preferred_side is KEEP

    refused = bus.dispatch("net.update", UpdateNetPayload(id=net.id, preferred_side="left"))  # type: ignore[arg-type]
    assert not refused.ok and refused.code == "invalid-side"


def test_a_new_net_may_say_its_face() -> None:
    bus = _bus(_doc())

    assert bus.dispatch("net.add", AddNetPayload(name="RAIL", preferred_side="bottom")).ok

    assert bus.document.nets[-1].preferred_side == "bottom"


def test_a_copied_trace_keeps_its_face() -> None:
    trace = SolderTraceConductor(id="t", path=(HoleCoord(0, 0), HoleCoord(1, 0)), side="top")

    spec = _new_conductor(trace, trace.path, {})

    assert isinstance(spec, NewSolderTraceConductor) and spec.side == "top"


# ---------------------------------------------------------------------------
# What the board joins, and what DRC says about it
# ---------------------------------------------------------------------------


def _with(doc: PerfDocument, *conductors: SolderTraceConductor) -> PerfDocument:
    return dataclasses.replace(doc, conductors=(*doc.conductors, *conductors))


def _net_of(doc: PerfDocument, conductor_id: str) -> str:
    return next(n.id for n in extract_physical_nets(doc, LOOKUP) if conductor_id in n.conductor_ids)


def test_a_pinless_hole_both_faces_reach_is_a_via() -> None:
    """A trace on each face, meeting in a hole with no pin: one net, through the plating
    (connectivity's pass 2b). Apart, they are two."""
    doc = dataclasses.replace(_doc(), conductors=())
    a, b, c = _free_run(doc)
    top = SolderTraceConductor(id="top", path=(a, b), side="top")
    under = SolderTraceConductor(id="under", path=(b, c), side="bottom")
    apart = SolderTraceConductor(id="under", path=(c,), side="bottom")

    assert _net_of(_with(doc, top, under), "top") == _net_of(_with(doc, top, under), "under")
    assert _net_of(_with(doc, top, apart), "top") != _net_of(_with(doc, top, apart), "under")


def test_a_trace_on_the_component_side_through_two_nets_pins_is_a_short() -> None:
    """A pin joins its hole's two faces, so solder on the component side shorts two pins
    exactly as it would underneath."""
    doc = dataclasses.replace(_doc(), conductors=())
    pins = [
        (component.ref, pin.number, hole)
        for component in doc.components
        for footprint in (LOOKUP(component.footprint_id),)
        if footprint is not None
        for pin, hole in all_pin_holes(component, footprint)
    ]
    net_of = {
        (node.component_ref, node.pin): net.id for net in doc.nets for node in net.nodes
    }
    first, second = next(
        (p, q)
        for p in pins
        for q in pins
        if is_adjacent4(p[2], q[2])
        and (p[0], p[1]) in net_of
        and (q[0], q[1]) in net_of
        and net_of[(p[0], p[1])] != net_of[(q[0], q[1])]
    )
    before = run_lvs(doc, LOOKUP).summary.shorts

    bridged = _with(doc, SolderTraceConductor(id="t", path=(first[2], second[2]), side="top"))

    assert run_lvs(bridged, LOOKUP).summary.shorts > before


def test_solder_on_a_face_with_no_pads_is_an_error_and_not_on_one_with_pads() -> None:
    doc = _doc()
    trace = SolderTraceConductor(id="t", path=_free_run(doc), side="top")
    single = dataclasses.replace(
        _with(doc, trace), board=dataclasses.replace(doc.board, single_sided=True)
    )

    found = [v for v in run_drc(single, LOOKUP) if v.rule == "no-copper-on-face"]

    assert [(v.severity, v.conductor_ids) for v in found] == [("error", ("t",))]
    assert "component side" in found[0].message
    assert not [v for v in run_drc(_with(doc, trace), LOOKUP) if v.rule == "no-copper-on-face"]
    underneath = dataclasses.replace(trace, side="bottom")
    assert not [
        v
        for v in run_drc(dataclasses.replace(single, conductors=(*doc.conductors, underneath)), LOOKUP)
        if v.rule == "no-copper-on-face"
    ]


def test_a_component_side_trace_under_a_parts_body_is_named() -> None:
    """Component-side copper is laid after the parts, so under one it cannot be laid at
    all: copper-under-body names it, on the component side. The same run underneath, with
    every part on the component side, is not under anything."""
    doc = dataclasses.replace(_doc(), conductors=())
    occupancy = build_occupancy(doc, LOOKUP)
    run = next(
        (HoleCoord(col, row), HoleCoord(col + 1, row), HoleCoord(col + 2, row))
        for row in range(doc.board.rows)
        for col in range(doc.board.cols - 2)
        if occupancy.body_covers(HoleCoord(col + 1, row), "top") is not None
    )
    trace = SolderTraceConductor(id="t", path=run, side="top")

    found = [v for v in run_drc(_with(doc, trace), LOOKUP) if v.rule == "copper-under-body"]

    assert found and all(v.conductor_ids == ("t",) for v in found)
    assert "on the component side" in found[0].message
    under = dataclasses.replace(trace, side="bottom")
    assert not [v for v in run_drc(_with(doc, under), LOOKUP) if v.rule == "copper-under-body"]


# ---------------------------------------------------------------------------
# The router on both faces (RouterOptions.faces)
# ---------------------------------------------------------------------------


def _solder_plan(doc: PerfDocument, faces: RouterFaces, **prefer: BoardSide) -> AutoroutePlan:
    """``doc`` stripped of its copper and wired in the solder style, the nets named in
    ``prefer`` given that face."""
    bare = dataclasses.replace(
        doc,
        conductors=(),
        nets=tuple(dataclasses.replace(n, preferred_side=prefer.get(n.name)) for n in doc.nets),
    )
    router = options_for_style("solder", RouterOptions(wire_path="grid", faces=faces))
    return plan_autoroute(bare, LOOKUP, AutorouteOptions(router=router))


def test_one_face_is_the_default_and_both_faces_with_no_preference_stays_underneath() -> None:
    """``faces`` is "solder" unless asked, which is every golden route. Asked for both with
    no net preferring a face, the NE555's solder-style plan is the solder side's to the
    conductor: two traces cannot cross on opposite faces of a plated board any more than
    on one, so a trace only costs more on top -- and on this board no wire is better off
    over the parts either."""
    assert RouterOptions().faces == "solder"
    doc = _doc()

    assert _solder_plan(doc, "both").conductors == _solder_plan(doc, "solder").conductors


def test_a_net_that_prefers_the_component_side_is_wired_there_without_a_short() -> None:
    doc = _doc()
    gnd = next(n.id for n in doc.nets if n.name == "GND")

    plan = _solder_plan(doc, "both", GND="top")

    on_top = [c for c in plan.conductors if c.side == "top"]
    assert on_top and all(c.net_id == gnd for c in on_top)
    assert run_lvs(plan.document, LOOKUP).summary.shorts == 0
    rules = {v.rule for v in run_drc(plan.document, LOOKUP)}
    assert not rules & {"no-copper-on-face", "copper-under-body", "conductor-crossing"}


def test_the_faces_meet_in_a_via_and_the_plan_counts_it() -> None:
    plan = _solder_plan(_doc(), "both", GND="top")
    occupancy = build_occupancy(plan.document, LOOKUP)

    vias = wiring_stats(plan.document, LOOKUP).vias

    assert vias, "GND no longer changes face on the ne555"
    for hole in vias:
        assert occupancy.pin_at(hole) is None
        sides = {c.side for c in plan.document.conductors if hole in c.path}
        assert sides == {"top", "bottom"}
    assert score_plan(plan, _doc(), LOOKUP).face_changes == len(vias)


def test_a_preference_is_ignored_on_one_face_and_on_a_board_with_no_pads_on_top() -> None:
    doc = _doc()
    single = dataclasses.replace(doc, board=dataclasses.replace(doc.board, single_sided=True))

    assert not any(c.side == "top" for c in _solder_plan(doc, "solder", GND="top").conductors)
    assert not any(c.side == "top" for c in _solder_plan(single, "both", GND="top").conductors)


def test_solder_on_the_component_side_closes_its_holes_underneath() -> None:
    """A plated hole is one piece of copper: what is soldered on top of it is on its pad
    underneath, so nothing on the solder side may pass through it."""
    doc = dataclasses.replace(_doc(), conductors=())
    run = _free_run(doc)
    top = _with(doc, SolderTraceConductor(id="t", path=run, side="top"))

    occupancy = build_occupancy(top, LOOKUP)

    assert all(occupancy.is_copper_blocked(hole, "bottom") for hole in run)
    assert not any(build_occupancy(doc, LOOKUP).is_copper_blocked(hole, "bottom") for hole in run)


def _balanced_plan(path: pathlib.Path, faces: RouterFaces) -> AutoroutePlan:
    doc = dataclasses.replace(persist.parse_document_or_throw(path.read_text(encoding="utf-8")), conductors=())
    return plan_autoroute(doc, LOOKUP, AutorouteOptions(router=RouterOptions(wire_path="grid", faces=faces)))


def test_a_wire_over_the_component_side_lies_across_no_pin_and_under_no_part() -> None:
    """On arduino-io-shield one wire goes over the top, where it lies across nothing of
    the solder side's: the stack, the pins and the ends lain across all come down."""
    shield = REPO / "examples" / "arduino-io-shield.perf"
    one_face, both = _balanced_plan(shield, "solder"), _balanced_plan(shield, "both")
    occupancy = build_occupancy(both.document, LOOKUP)

    over = [c for c in both.document.conductors if c.side == "top"]

    assert over and all(c.kind == "top-jumper" for c in over), "no wire goes over the top"
    for wire in over:
        ends = {wire.path[0], wire.path[-1]}
        lain = {h for a, b in zip(wire.path, wire.path[1:], strict=False) for h in holes_under_line(a, b)}
        for hole in lain - ends:
            assert occupancy.pin_at(hole) is None, f"{wire.id} lies across a pin at {hole}"
            assert occupancy.body_covers(hole, "top") is None, f"{wire.id} runs under a part"
    assert run_lvs(both.document, LOOKUP).summary.shorts == 0
    assert not [v for v in run_drc(both.document, LOOKUP) if v.rule == "jumper-under-body"]
    before, after = wiring_stats(one_face.document, LOOKUP), wiring_stats(both.document, LOOKUP)
    assert after.max_level < before.max_level
    assert after.over_pins + after.over_ends < before.over_pins + before.over_ends


def test_a_short_through_the_plating_is_found_not_only_avoided() -> None:
    """The router keeps a top trace's holes closed underneath; this is the same physics
    seen from outside the router. Two nets' traces on opposite faces, soldered into one
    pinless hole, are one piece of copper: LVS finds the short. With the solder-side
    trace kept out of that hole, the faces are separate copper and there is none."""
    doc = dataclasses.replace(_doc(), conductors=())
    occupancy = build_occupancy(doc, LOOKUP)
    net_of = {(node.component_ref, node.pin): net.id for net in doc.nets for node in net.nodes}
    pins = {
        (hole.col, hole.row): net_of[(component.ref, pin.number)]
        for component in doc.components
        for footprint in (LOOKUP(component.footprint_id),)
        if footprint is not None
        for pin, hole in all_pin_holes(component, footprint)
        if (component.ref, pin.number) in net_of
    }

    def free(col: int, row: int) -> bool:
        return (
            0 <= col < doc.board.cols
            and 0 <= row < doc.board.rows
            and occupancy.pin_at(HoleCoord(col, row)) is None
        )

    # A pinless hole with a pin of one net beside it on one side and a pin of another
    # net beside it on another, and a second pinless hole beside it to move to.
    p, q, via, aside = next(
        (HoleCoord(*a), HoleCoord(*b), HoleCoord(col, row), HoleCoord(*c))
        for col in range(doc.board.cols)
        for row in range(doc.board.rows)
        if free(col, row)
        for a in ((col - 1, row), (col + 1, row), (col, row - 1), (col, row + 1))
        for b in ((col - 1, row), (col + 1, row), (col, row - 1), (col, row + 1))
        if a in pins and b in pins and pins[a] != pins[b]
        for c in ((col - 1, row), (col + 1, row), (col, row - 1), (col, row + 1))
        if c not in (a, b) and free(*c)
    )
    top = SolderTraceConductor(id="top", path=(p, via), side="top")
    before = run_lvs(_with(doc, top), LOOKUP).summary.shorts

    shorted = _with(doc, top, SolderTraceConductor(id="under", path=(q, via), side="bottom"))
    through = _with(
        doc,
        top,
        SolderTraceConductor(id="under", path=(q, via, aside), side="bottom"),
    )
    clear = _with(doc, top, SolderTraceConductor(id="under", path=(q,), side="bottom"))

    assert run_lvs(shorted, LOOKUP).summary.shorts > before
    assert _net_of(shorted, "top") == _net_of(shorted, "under")
    # Through the hole and on past it is the same short: a trace is soldered at every
    # hole it crosses, on whichever face it lies.
    assert run_lvs(through, LOOKUP).summary.shorts > before
    assert run_lvs(clear, LOOKUP).summary.shorts == before


def test_the_guide_lays_the_component_side_after_the_parts_and_probes_each_via() -> None:
    """Solder on the component side opens phase 7: after the parts, whose leads a filled
    hole would keep out, and before the long wires. Every via gets one line on the first
    step that lays the solder side's copper into it, and one probe across it after phase
    7, from its component-side pad to the next hole of that copper. Turkish says the same."""
    wired = _solder_plan(_doc(), "both", GND="top").document
    via_holes = wiring_stats(wired, LOOKUP).vias
    assert via_holes, "GND no longer changes face on the ne555"
    top_runs = {
        c.id for c in wired.conductors if isinstance(c, SolderTraceConductor) and c.side == "top"
    }

    for language, title, via_word in (
        ("en", "Component-side solder, then long insulated wires", "is a via"),
        ("tr", "Parça yüzündeki lehim, ardından uzun izoleli teller", "bir via"),
    ):
        guide = build_guide(wired, LOOKUP, GuideOptions(language=language))
        phases = {phase.number: phase for phase in guide.phases}
        seventh = phases[7]
        assert seventh.title == title
        conductor_steps = [s for s in seventh.steps if isinstance(s, ConductorStep)]
        # The component side's runs, all of them and nothing else, at the head of phase 7.
        head = conductor_steps[: len(top_runs)]
        assert {s.conductor_id for s in head} == top_runs
        assert not any(
            s.conductor_id in top_runs for phase in guide.phases if phase.number != 7
            for s in phase.steps if isinstance(s, ConductorStep)
        )
        for via in via_holes:
            said = format_hole(via, wired.board)
            noted = [
                s
                for phase in guide.phases
                for s in phase.steps
                if isinstance(s, ConductorStep)
                and any(note.startswith(said) and via_word in note for note in s.notes)
            ]
            assert len(noted) == 1 and noted[0].side == "bottom" and via in noted[0].path
            probes = [
                c for c in seventh.checkpoints if c.kind == "continuity" and c.holes[:1] == (via,)
            ]
            assert len(probes) == 1
            assert is_adjacent4(via, probes[0].holes[1]) or probes[0].holes[1] in noted[0].path


def test_a_guide_with_no_component_side_copper_keeps_phase_7_as_it_was() -> None:
    guide = build_guide(_doc(), LOOKUP)

    assert {p.number: p.title for p in guide.phases}[7] == "Long insulated wires"
    assert not any("via" in c.title for p in guide.phases for c in p.checkpoints)
