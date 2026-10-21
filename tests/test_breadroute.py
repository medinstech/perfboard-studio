"""Wiring a breadboard: jumpers into free holes, power from the rails -- and the placer and
the planner agreeing about which boards can be wired at all."""

from __future__ import annotations

import dataclasses
import pathlib
import random

import pytest

from perfboard_studio.breadboard import breadboard, has_hole, parse_hole_name, rail_of
from perfboard_studio.breadroute import plan_breadboard, plan_joined_board, plan_joined_reroute
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    ApplyStripboardPlanPayload,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import get_footprint
from perfboard_studio.geometry import all_pin_holes, hole_key
from perfboard_studio.lvs import run_lvs
from perfboard_studio.mcp.session import BoardSession
from perfboard_studio.model import (
    ComponentInstance,
    DocumentMeta,
    HoleCoord,
    Net,
    NetNode,
    PerfDocument,
    SchematicPart,
)
from perfboard_studio.persist import deserialize_document
from perfboard_studio.placer import (
    PlacementWeights,
    _build_nets,
    _build_parts,
    _build_strips,
    _initial_state,
    _make_scorer,
    place_design,
)
from perfboard_studio.striproute import describe_plan

FULL = breadboard("830")
REPO = pathlib.Path(__file__).resolve().parent.parent


def _part(ref: str, footprint: str, at: str, rotation: int = 0) -> ComponentInstance:
    hole = parse_hole_name(FULL, at)
    assert hole is not None, at
    return ComponentInstance(
        id=f"c-{ref}", ref=ref, value="", footprint_id=footprint, anchor=hole,
        rotation=rotation, mirrored=False, locked=False,  # type: ignore[arg-type]
    )


def _node(ref: str, pin: str) -> NetNode:
    return NetNode(component_ref=ref, pin=pin)


def _doc(*components: ComponentInstance, nets: tuple[Net, ...] = (), board=FULL) -> PerfDocument:  # type: ignore[no-untyped-def]
    return PerfDocument(
        meta=DocumentMeta(name="t", created="2026-01-01T00:00:00Z", modified="2026-01-01T00:00:00Z"),
        board=board,
        components=components,
        nets=nets,
    )


#: A 555 across the channel and two resistors: a ground net, a power net, a signal.
TIMER = _doc(
    _part("U1", "dip-8", "e11", rotation=270),
    _part("R1", "r-axial-4", "c21"),
    _part("R2", "r-axial-4", "h21"),
    nets=(
        Net(id="gnd", name="GND", nodes=(_node("U1", "1"), _node("R1", "2")), net_class="ground"),
        Net(
            id="vcc", name="VCC", nodes=(_node("U1", "8"), _node("U1", "4"), _node("R2", "1")),
            net_class="power",
        ),
        Net(id="trig", name="TRIG", nodes=(_node("U1", "2"), _node("R1", "1"), _node("R2", "2"))),
    ),
)


def _apply(doc: PerfDocument, payload: ApplyStripboardPlanPayload) -> PerfDocument:
    bus = CommandBus(doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc)))
    result = bus.dispatch("stripboard.apply", payload)
    assert result.ok, result.message
    assert result.document is not None
    return result.document


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def test_a_planned_breadboard_is_wired_as_drawn_and_breaks_no_rule() -> None:
    plan = plan_joined_board(TIMER, get_footprint)
    assert plan.cuts == () and plan.problems == ()
    assert describe_plan(plan) == f"{len(plan.links)} jumper(s)"
    wired = _apply(TIMER, plan.payload())
    assert run_lvs(wired, get_footprint).ok
    assert not [v for v in run_drc(wired, get_footprint) if v.severity == "error"]
    assert {(c.kind, c.side) for c in wired.conductors} == {("top-jumper", "top")}


def test_one_lead_to_a_hole() -> None:
    """A jumper goes into a free hole of the clip, never into the hole a pin is in, and
    no two jumper ends share one."""
    wired = plan_breadboard(TIMER, get_footprint).document
    pins = {
        hole_key(h)
        for c in wired.components
        for _, h in all_pin_holes(c, get_footprint(c.footprint_id))  # type: ignore[arg-type]
    }
    ends = [hole_key(h) for c in wired.conductors for h in (c.path[0], c.path[-1])]
    assert len(ends) == len(set(ends))
    assert not pins & set(ends)


def test_supply_nets_come_from_their_own_rails_and_a_used_pair_is_bridged() -> None:
    plan = plan_breadboard(TIMER, get_footprint)
    rails_by_net: dict[str, set[str]] = {}
    for link in plan.links:
        for end in (link.from_hole, link.to_hole):
            rail = rail_of(FULL, end.row) if has_hole(FULL, end) else None
            if rail is not None:
                rails_by_net.setdefault(link.net_name, set()).add(rail)
    assert rails_by_net["GND"] <= {"top-", "bottom-"}
    assert rails_by_net["VCC"] <= {"top+", "bottom+"}
    assert "TRIG" not in rails_by_net
    # VCC reaches both + rails (U1.8 is beside the top, U1.4 beside the bottom): one
    # jumper straight across joins them, at an end of the board.
    bridge = [
        link for link in plan.links
        if link.net_name == "VCC" and {rail_of(FULL, link.from_hole.row), rail_of(FULL, link.to_hole.row)} == {"top+", "bottom+"}
    ]
    assert len(bridge) == 1 and bridge[0].from_hole.col == bridge[0].to_hole.col
    assert bridge[0].from_hole.col < 5


def test_two_nets_in_one_clip_cannot_be_separated() -> None:
    doc = dataclasses.replace(TIMER, components=(_part("U1", "dip-8", "e11", rotation=0), *TIMER.components[1:]))
    codes = [p.code for p in plan_breadboard(doc, get_footprint).problems]
    assert codes.count("cannot-separate") >= 1


def test_a_signal_in_a_rail_is_reported_by_the_planner_and_drc_alike() -> None:
    """The + rail is for power. A signal down it is wired as well as anything, and is a
    board that says + over a signal -- so the planner reports it and DRC warns."""
    doc = dataclasses.replace(TIMER, components=(*TIMER.components[:2], _part("R2", "r-axial-4", "T+21")))
    planned = [p for p in plan_breadboard(doc, get_footprint).problems if p.code == "wrong-rail"]
    warned = [v for v in run_drc(doc, get_footprint) if v.rule == "wrong-rail"]
    # R2.1 is VCC and belongs there; R2.2 is TRIG and does not.
    assert len(planned) == len(warned) == 1
    assert "R2" in planned[0].message and warned[0].severity == "warning"


def test_nothing_is_cut_on_a_breadboard_even_by_a_plan() -> None:
    bus = CommandBus(TIMER, create_standard_registry(), CommandContext(next_id=create_document_id_generator(TIMER)))
    hole = parse_hole_name(FULL, "a5")
    assert hole is not None
    result = bus.dispatch("stripboard.apply", ApplyStripboardPlanPayload(cuts=(hole,), conductors=()))
    assert not result.ok and result.code == "breadboard"


def test_an_agent_autoroutes_a_breadboard_with_jumpers() -> None:
    session = BoardSession(document=TIMER)
    result = session.autoroute()
    assert result["ok"] and result["committed"], result
    assert result["cut_count"] == 0 and result["link_count"] == len(session.document.conductors)
    ends = [link[end] for link in result["links"] for end in ("from", "to")]
    assert ends and all(parse_hole_name(FULL, name) is not None for name in ends)


def test_a_reroute_lays_jumpers_again_and_nothing_else() -> None:
    """Re-route Everything went to the perfboard router, which took a breadboard's jumpers
    up and laid solder traces and bare wire in their place: nineteen not-on-breadboard
    errors and a short. A part moved first, so the plan has something to change."""
    wired = _apply(TIMER, plan_joined_board(TIMER, get_footprint).payload())
    moved = dataclasses.replace(
        wired,
        components=(*wired.components[:2], _part("R2", "r-axial-4", "h31")),
    )
    plan = plan_joined_reroute(moved, get_footprint)
    assert set(plan.remove_ids) == {c.id for c in moved.conductors}
    assert describe_plan(plan).startswith(f"{len(plan.remove_ids)} old conductor(s) ripped up")
    again = _apply(moved, plan.payload())
    assert {(c.kind, c.side) for c in again.conductors} == {("top-jumper", "top")}
    assert run_lvs(again, get_footprint).ok
    assert not [v for v in run_drc(again, get_footprint) if v.severity == "error"]


def test_a_stripboard_reroute_keeps_its_cuts_and_lays_links_again() -> None:
    from perfboard_studio.commands import DEFAULT_BOARD

    strips = dataclasses.replace(DEFAULT_BOARD, type="stripboard", strip_axis="horizontal")
    doc = _doc(
        ComponentInstance(id="c-R1", ref="R1", value="", footprint_id="r-axial-4",
                          anchor=HoleCoord(2, 2), rotation=90, mirrored=False, locked=False),
        ComponentInstance(id="c-R2", ref="R2", value="", footprint_id="r-axial-4",
                          anchor=HoleCoord(8, 2), rotation=90, mirrored=False, locked=False),
        nets=(
            Net(id="a", name="A", nodes=(_node("R1", "1"), _node("R2", "2"))),
            Net(id="b", name="B", nodes=(_node("R1", "2"), _node("R2", "1"))),
        ),
        board=strips,
    )
    wired = _apply(doc, plan_joined_board(doc, get_footprint).payload())
    plan = plan_joined_reroute(wired, get_footprint)
    again = _apply(wired, plan.payload())
    assert again.cuts == wired.cuts
    assert {c.kind for c in again.conductors} <= {"top-jumper"}
    assert run_lvs(again, get_footprint).ok


def test_an_agent_reroutes_a_breadboard_with_jumpers() -> None:
    session = BoardSession(document=TIMER)
    assert session.autoroute()["committed"]
    result = session.reroute()
    assert result["ok"], result
    assert {c.kind for c in session.document.conductors} == {"top-jumper"}
    assert not [v for v in run_drc(session.document, get_footprint) if v.severity == "error"]


# ---------------------------------------------------------------------------
# The placer and the planner
# ---------------------------------------------------------------------------


def _conflicts(doc: PerfDocument) -> int:
    parts = _build_parts(doc, get_footprint)
    nets, nets_of, pin_nets = _build_nets(doc, parts)
    strips = _build_strips(doc, parts, pin_nets)
    state = _initial_state(doc, parts, strips)
    scorer = _make_scorer(doc.board, PlacementWeights(), nets, nets_of, strips, frozenset(), ())
    return scorer.full(state).strip_conflicts


def test_the_placer_counts_exactly_what_the_planner_refuses() -> None:
    """One fact, two consumers, the shape of the stripboard test: over a hundred and fifty
    random placements, the pairs and wrong-rail pins the placer prices are the problems the
    planner reports. A disagreement either way hands over a board that cannot be wired or
    scatters one that could."""
    rng = random.Random(7)
    footprints = ("r-axial-4", "dip-8", "led-5mm", "c-disc-p2")
    for trial in range(150):
        components = tuple(
            ComponentInstance(
                id=f"c{i}", ref=f"P{i}", value="", footprint_id=rng.choice(footprints),
                anchor=HoleCoord(rng.randrange(2, 12), rng.randrange(0, 18)),
                rotation=rng.choice((0, 90, 180, 270)), mirrored=False, locked=False,
            )
            for i in range(4)
        )
        holes = [
            hole_key(h) for c in components for _, h in all_pin_holes(c, get_footprint(c.footprint_id))  # type: ignore[arg-type]
        ]
        if len(holes) != len(set(holes)):
            # Two pins in one hole: a collision, priced by its own term and reported by
            # duplicate-pin-hole, and outside this question -- as on stripboard.
            continue
        pins = [(c.ref, p.number) for c in components for p in get_footprint(c.footprint_id).pins]  # type: ignore[union-attr]
        rng.shuffle(pins)
        nets = tuple(
            Net(
                id=f"n{k}", name=f"N{k}", nodes=tuple(_node(r, p) for r, p in pins[k::4]),
                net_class=("ground", "power", "signal", "signal")[k],
            )
            for k in range(3)  # a quarter of the pins left undeclared
        )
        doc = _doc(*components, nets=nets)
        refused = sum(
            p.code in ("cannot-separate", "wrong-rail") for p in plan_breadboard(doc, get_footprint).problems
        )
        assert _conflicts(doc) == refused, f"trial {trial}"


@pytest.mark.parametrize("example", ["ne555-astable", "nano-relay"])
def test_an_example_is_placed_and_wired_on_a_breadboard(example: str) -> None:
    """The whole of it on two real circuits, one with a module wider than a DIP: Place on
    the Board, then the planner, and the board that comes out is the circuit."""
    loaded = deserialize_document((REPO / "examples" / f"{example}.perf").read_text(encoding="utf-8"))
    assert loaded.ok
    doc = loaded.document
    design = dataclasses.replace(
        doc,
        board=FULL,
        components=(),
        conductors=(),
        mounting_holes=(),
        edge_connectors=(),
        board_notes=(),
        parts=doc.parts + tuple(
            SchematicPart(id=c.id, ref=c.ref, value=c.value, footprint_id=c.footprint_id,
                          pin_names=c.pin_names, symbol=c.symbol)
            for c in doc.components
        ),
    )
    placed = place_design(design, get_footprint)
    assert placed.unplaced == ()
    plan = plan_breadboard(placed.document, get_footprint)
    assert plan.problems == ()
    assert run_lvs(plan.document, get_footprint).ok
    assert not [v for v in run_drc(plan.document, get_footprint) if v.severity == "error"]
    # A board the planner has wired needs nothing more from it. Planning it again used to
    # bridge the rail pair a second time: the ground's one island touches both rails
    # through the bridge already there, and that read as two rails reached.
    again = plan_breadboard(plan.document, get_footprint)
    assert again.conductors == () and again.problems == ()
