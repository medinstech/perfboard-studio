"""Rewiring a breadboard: re-route by its own planner, an unused lead counted as what it
is in a clip, and jumpers laid along the grid."""

from __future__ import annotations

import dataclasses
import pathlib
import random
from itertools import pairwise

import pytest

from perfboard_studio.breadboard import clip_holes, clip_of
from perfboard_studio.breadroute import (
    _grid_path,
    _router,
    _steps,
    plan_breadboard,
    plan_joined_reroute,
)
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    ApplyStripboardPlanPayload,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import get_footprint
from perfboard_studio.geometry import (
    all_pin_holes,
    hole_key,
    holes_under_line,
    manhattan,
    path_length_mm,
)
from perfboard_studio.guide import build_guide
from perfboard_studio.lvs import run_lvs, stale_conductor_ids
from perfboard_studio.mcp.session import BoardSession, SessionError
from perfboard_studio.model import ComponentInstance, HoleCoord, PerfDocument, SchematicPart
from perfboard_studio.occupancy import build_occupancy
from perfboard_studio.persist import deserialize_document
from perfboard_studio.placer import PlacementOptions, _pick_best, place_design, plan_placement
from perfboard_studio.striproute import UNDER_BODY_COST, cover_of, parts_under
from tests.test_breadroute import FULL, TIMER, _apply, _conflicts, _node, _part

REPO = pathlib.Path(__file__).resolve().parent.parent


def _pin_hole(doc: PerfDocument, ref: str, number: str) -> HoleCoord:
    component = next(c for c in doc.components if c.ref == ref)
    return next(h for p, h in all_pin_holes(component, get_footprint(component.footprint_id)) if p.number == number)  # type: ignore[arg-type]


def _taken(doc: PerfDocument) -> set[str]:
    taken = {
        hole_key(h)
        for c in doc.components
        for _, h in all_pin_holes(c, get_footprint(c.footprint_id))  # type: ignore[arg-type]
    }
    taken |= {hole_key(h) for c in doc.conductors for h in (c.path[0], c.path[-1])}
    return taken


def _free_in_clip(doc: PerfDocument, hole: HoleCoord) -> HoleCoord:
    taken = _taken(doc)
    return next(h for h in clip_holes(doc.board, hole) if hole_key(h) not in taken)


def _header(ref: str, at: HoleCoord) -> ComponentInstance:
    return ComponentInstance(
        id=f"c-{ref}", ref=ref, value="", footprint_id="hdr-1x1", anchor=at,
        rotation=0, mirrored=False, locked=False,
    )


def _wired(doc: PerfDocument) -> PerfDocument:
    return _apply(doc, plan_breadboard(doc, get_footprint).payload())


# ---------------------------------------------------------------------------
# Re-route
# ---------------------------------------------------------------------------


def test_reroute_after_a_move_rewires_the_part_that_moved() -> None:
    wired = _wired(TIMER)
    moved = dataclasses.replace(
        wired,
        components=tuple(
            _part("R1", "r-axial-4", "c31") if c.ref == "R1" else c for c in wired.components
        ),
    )
    plan = plan_joined_reroute(moved, get_footprint, wire_path="grid")
    assert set(plan.remove_ids) == {c.id for c in wired.conductors}
    rewired = _apply(moved, plan.payload())
    assert run_lvs(rewired, get_footprint).ok
    assert len(rewired.conductors) == len(plan.conductors)


def test_reroute_keeps_copper_no_net_claims() -> None:
    wired = _wired(TIMER)
    a = _free_in_clip(wired, _pin_hole(wired, "R1", "1"))
    hand = dataclasses.replace(
        wired.conductors[0], id="hand", net_id=None, path=(a, HoleCoord(a.col + 1, a.row))
    )
    plan = plan_joined_reroute(dataclasses.replace(wired, conductors=(*wired.conductors, hand)), get_footprint)
    assert "hand" not in plan.remove_ids


def test_a_removal_the_board_does_not_have_refuses_the_whole_plan() -> None:
    bus = CommandBus(TIMER, create_standard_registry(), CommandContext(next_id=create_document_id_generator(TIMER)))
    result = bus.dispatch("stripboard.apply", ApplyStripboardPlanPayload(remove_ids=("nope",)))
    assert not result.ok and result.code == "conductor-not-found"


def test_a_second_autoroute_lays_nothing() -> None:
    """The rail pair was bridged again on every run: one island holding both rails is a
    bridge already fitted."""
    session = BoardSession(document=TIMER)
    assert session.autoroute()["committed"]
    again = session.autoroute()
    assert again["ok"] and not again["committed"], again


def test_a_way_of_laying_wire_nobody_has_is_refused_on_a_breadboard_too() -> None:
    with pytest.raises(SessionError):
        BoardSession(document=TIMER).autoroute(wires="diagonal")
    with pytest.raises(SessionError):
        BoardSession(document=TIMER).reroute(wires="diagonal")


# ---------------------------------------------------------------------------
# Stale jumpers
# ---------------------------------------------------------------------------


def test_an_agents_autoroute_clears_the_jumpers_moved_parts_left() -> None:
    """The window cleared stale copper before a breadboard's planner ran and the MCP
    server did not: with both resistors moved, the TRIG jumpers join U1.2 to nothing."""
    wired = _wired(TIMER)
    trig = {c.id for c in wired.conductors if c.net_id == "trig"}
    moved = dataclasses.replace(
        wired,
        components=tuple(
            _part(c.ref, "r-axial-4", {"R1": "c40", "R2": "h40"}[c.ref]) if c.ref in ("R1", "R2") else c
            for c in wired.components
        ),
    )
    assert set(stale_conductor_ids(moved, get_footprint)) >= trig
    session = BoardSession(document=moved)
    result = session.autoroute()
    assert result["stale_removed"] >= len(trig)
    assert not trig & {c.id for c in session.document.conductors}
    assert run_lvs(session.document, get_footprint).ok


def test_a_jumper_in_a_clip_the_board_already_shorts_is_not_taken_up_every_time() -> None:
    """A GND pin moved into a clip that still holds a TRIG pin is shorted by the BOARD,
    whatever the jumper beside it does: the planner says cannot-separate, LVS says short,
    and taking the jumper up only lays it again. A rule calling every jumper in a clip with
    another net's pin stale was tried, and did that here and beside every unused pin on
    stripboard, so a second autoroute was never a no-op."""
    wired = _wired(TIMER)
    jumper = next(c for c in wired.conductors if c.net_id == "trig")
    gnd = next(n for n in TIMER.nets if n.id == "gnd")
    moved = dataclasses.replace(
        wired,
        components=(*wired.components, _header("J9", _free_in_clip(wired, jumper.path[-1]))),
        nets=tuple(
            dataclasses.replace(n, nodes=(*n.nodes, _node("J9", "1"))) if n is gnd else n
            for n in wired.nets
        ),
    )
    assert any(p.code == "cannot-separate" for p in plan_breadboard(moved, get_footprint).problems)
    assert stale_conductor_ids(moved, get_footprint) == ()
    session = BoardSession(document=moved)
    session.autoroute()
    again = session.autoroute()
    assert again["ok"] and not again["committed"] and again["stale_removed"] == 0, again


def test_a_stripboard_link_beside_an_unused_pin_is_not_taken_up_every_time() -> None:
    """On stripboard a pin no net declares is a party to nothing -- striproute does not cut
    to isolate it -- so a link on a strip beside one is where the planner meant it."""
    from perfboard_studio.commands import DEFAULT_BOARD

    strips = dataclasses.replace(DEFAULT_BOARD, type="stripboard", strip_axis="horizontal")
    doc = dataclasses.replace(
        TIMER,
        board=strips,
        components=(
            *(
                ComponentInstance(id=f"c-{ref}", ref=ref, value="", footprint_id="r-axial-4",
                                  anchor=HoleCoord(col, 2), rotation=90, mirrored=False, locked=False)
                for ref, col in (("R1", 2), ("R2", 8))
            ),
            _header("J9", HoleCoord(3, 2)),
        ),
        nets=(
            dataclasses.replace(TIMER.nets[0], id="a", name="A", nodes=(_node("R1", "1"), _node("R2", "2")),
                                net_class="signal"),
            dataclasses.replace(TIMER.nets[0], id="b", name="B", nodes=(_node("R1", "2"), _node("R2", "1")),
                                net_class="signal"),
        ),
    )
    session = BoardSession(document=doc)
    assert session.autoroute()["committed"]
    assert run_lvs(session.document, get_footprint).ok
    assert stale_conductor_ids(session.document, get_footprint) == ()
    again = session.autoroute()
    assert not again["committed"] and again["stale_removed"] == 0, again


# ---------------------------------------------------------------------------
# Unused leads
# ---------------------------------------------------------------------------


def test_an_unused_lead_in_a_clip_is_a_pair_nothing_can_part() -> None:
    """U1.3 is in no net. A header pin of TRIG beside it in its clip joins the 555's output
    to TRIG, which LVS cannot see -- so the planner reports it and the placer counts it."""
    unused = _pin_hole(TIMER, "U1", "3")
    header = _header("J9", _free_in_clip(TIMER, unused))
    trig = next(n for n in TIMER.nets if n.id == "trig")
    doc = dataclasses.replace(
        TIMER,
        components=(*TIMER.components, header),
        nets=tuple(
            dataclasses.replace(n, nodes=(*n.nodes, _node("J9", "1"))) if n is trig else n
            for n in TIMER.nets
        ),
    )
    found = [p for p in plan_breadboard(doc, get_footprint).problems if p.code == "cannot-separate"]
    assert len(found) == 1 and "no net" in found[0].message and "U1.3" in found[0].message
    assert _conflicts(doc) == 1
    assert run_lvs(doc, get_footprint).summary.shorts == 0  # what LVS cannot see


@pytest.mark.parametrize("routed", [False, True])
def test_the_placer_never_hands_back_more_shorted_clips_than_the_board_had(routed: bool) -> None:
    """A board whose own parts overlap is not legal, and every legal candidate beat it
    however many clips it shorted: autoplace on a real breadboard with two bodies touching
    stood a header in a DIP's clips. On a breadboard the clips come first -- and only
    there, where nothing can part them."""
    options = PlacementOptions(seed=0, iterations=50, restarts=1, score_with_router=routed)
    plan = plan_placement(TIMER, get_footprint, options)
    baseline = dataclasses.replace(plan, after=dataclasses.replace(plan.after, overlap_pairs=1))
    shorting = dataclasses.replace(plan, after=dataclasses.replace(plan.after, strip_conflicts=2))
    assert not baseline.after.is_legal and shorting.after.is_legal
    assert _pick_best([shorting], baseline, TIMER, get_footprint, options).after.strip_conflicts == 0

    stripboard = dataclasses.replace(TIMER, board=dataclasses.replace(TIMER.board, type="stripboard"))
    unrouted = dataclasses.replace(options, score_with_router=False)
    assert _pick_best([shorting], baseline, stripboard, get_footprint, unrouted) is shorting


# ---------------------------------------------------------------------------
# Jumpers along the grid
# ---------------------------------------------------------------------------


def _bends(path: tuple[HoleCoord, ...]) -> int:
    return len(path) - 2


def test_a_grid_jumper_runs_along_rows_and_columns_and_wires_the_same_circuit() -> None:
    plan = plan_breadboard(TIMER, get_footprint, wire_path="grid")
    assert plan.problems == ()
    for spec, link in zip(plan.conductors, plan.links, strict=True):
        path = spec.path
        assert all(p.col == q.col or p.row == q.row for p, q in pairwise(path)), path
        assert _bends(path) <= 2
        assert (path[0], path[-1]) == (link.from_hole, link.to_hole)
        assert link.holes == sum(manhattan(p, q) for p, q in pairwise(path))
    wired = _apply(TIMER, plan.payload())
    assert run_lvs(wired, get_footprint).ok
    assert not [v for v in run_drc(wired, get_footprint) if v.severity == "error"]
    # The same ends as straight jumpers would have: only the shape between them moved.
    straight = plan_breadboard(TIMER, get_footprint)
    assert [(link.from_hole, link.to_hole) for link in straight.links] == [
        (link.from_hole, link.to_hole) for link in plan.links
    ]


def test_the_guide_cuts_a_grid_jumper_to_the_length_it_runs() -> None:
    wired = _apply(TIMER, plan_breadboard(TIMER, get_footprint, wire_path="grid").payload())
    bent = {c.id: c for c in wired.conductors if len(c.path) > 2}
    assert bent, "the 555 board has jumpers that turn a corner"
    cuts = {cut.conductor_id: cut for cut in build_guide(wired, get_footprint).cut_list}
    for id_, conductor in bent.items():
        assert cuts[id_].path_mm == pytest.approx(path_length_mm(conductor.path, wired.board))
        assert cuts[id_].cut_mm == pytest.approx(cuts[id_].path_mm + 2 * cuts[id_].strip_mm)


def test_a_grid_jumper_steps_round_a_part_rather_than_under_it() -> None:
    """Straight across a DIP's row is under it; along the grid there is a way round -- a U
    over the top of the chip -- and it is taken."""
    occupancy = build_occupancy(TIMER, get_footprint)
    left, right = _pin_hole(TIMER, "U1", "1"), _pin_hole(TIMER, "U1", "4")
    a, b = HoleCoord(left.col - 3, left.row), HoleCoord(right.col + 3, right.row)
    assert a.row == b.row
    straight_cost, straight = _router(TIMER, occupancy, "straight")(a, b)
    grid_cost, grid = _router(TIMER, occupancy, "grid")(a, b)
    assert straight == (a, b) and straight_cost >= UNDER_BODY_COST
    assert _bends(grid) == 2 and grid_cost < UNDER_BODY_COST
    assert not {occupancy.body_covers(h) for p, q in pairwise(grid) for h in holes_under_line(p, q)} - {None}


def test_an_agent_asks_for_grid_jumpers_by_the_wire_option() -> None:
    grid = BoardSession(document=TIMER)
    grid.autoroute(wires="grid")
    straight = BoardSession(document=TIMER)
    straight.autoroute(wires="straight")
    assert any(len(c.path) > 2 for c in grid.document.conductors)
    assert all(len(c.path) == 2 for c in straight.document.conductors)


def test_grid_jumpers_wire_a_placed_example_with_fewer_parts_over_them() -> None:
    loaded = deserialize_document((REPO / "examples" / "nano-relay.perf").read_text(encoding="utf-8"))
    assert loaded.ok
    doc = loaded.document
    design = dataclasses.replace(
        doc, board=FULL, components=(), conductors=(), mounting_holes=(), edge_connectors=(), board_notes=(),
        parts=doc.parts + tuple(
            SchematicPart(id=c.id, ref=c.ref, value=c.value, footprint_id=c.footprint_id,
                          pin_names=c.pin_names, symbol=c.symbol)
            for c in doc.components
        ),
    )
    placed = place_design(design, get_footprint).document

    def wired(wire_path: str) -> PerfDocument:
        plan = plan_breadboard(placed, get_footprint, wire_path=wire_path)  # type: ignore[arg-type]
        assert plan.problems == ()
        return plan.document

    grid, straight = wired("grid"), wired("straight")
    assert run_lvs(grid, get_footprint).ok
    assert not [v for v in run_drc(grid, get_footprint) if v.severity == "error"]

    def under(doc: PerfDocument) -> int:
        return sum(v.rule == "jumper-under-body" for v in run_drc(doc, get_footprint))

    assert under(grid) <= under(straight)
    assert all(clip_of(grid.board, c.path[0]) is not None for c in grid.conductors)


def test_the_parts_over_a_run_are_the_same_read_off_the_cover_or_walked() -> None:
    """``_cover`` answers a run along a row or a column without walking it, which is what
    took grid jumpers on atmega328-relay from 50 s to about one. It has to be the same
    answer as walking it, ends excluded, for every shape -- or the plan moves."""
    occupancy = build_occupancy(TIMER, get_footprint)
    cover = cover_of(TIMER, occupancy)
    # Every covered hole as the far end of a run and the near end of one, out and back
    # along a row and along a column: the hole the run turns on is the one only it covers.
    for row, along in cover[0].items():
        for col, _part_id in along:
            hole = HoleCoord(col, row)
            for d_col, d_row in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                near = HoleCoord(col + d_col, row + d_row)
                path = (near, hole, near)
                assert parts_under(path, occupancy, cover) == parts_under(path, occupancy) == 1, path
    rng = random.Random(3)
    for _ in range(2000):
        points = [HoleCoord(rng.randrange(TIMER.board.cols), rng.randrange(TIMER.board.rows))]
        for _ in range(rng.randrange(1, 4)):
            last = points[-1]
            step = rng.choice(("row", "col", "any"))
            col = rng.randrange(TIMER.board.cols) if step != "col" else last.col
            row = rng.randrange(TIMER.board.rows) if step != "row" else last.row
            points.append(HoleCoord(col, row))
        path = tuple(points)
        assert parts_under(path, occupancy, cover) == parts_under(path, occupancy), path


def test_a_grid_jumper_takes_a_lane_of_its_own() -> None:
    """Two jumpers down one row hide each other from above, so the second steps off the
    first one's lane when a free one is close -- and the plan as a whole shares little."""
    occupancy = build_occupancy(TIMER, get_footprint)
    a, b = HoleCoord(30, 3), HoleCoord(45, 6)
    first = _grid_path(a, b, TIMER, occupancy)[1]
    second = _grid_path(HoleCoord(30, 2), HoleCoord(45, 7), TIMER, occupancy, _steps(first))[1]
    assert not _steps(first) & _steps(second)

    plan = plan_breadboard(TIMER, get_footprint, wire_path="grid")
    every = [_steps(spec.path) for spec in plan.conductors]
    shared = sum(len(x & y) for i, x in enumerate(every) for y in every[i + 1 :])
    assert shared <= sum(map(len, every)) // 10
