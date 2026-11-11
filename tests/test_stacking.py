"""No two conductors in one place, measured on every board the repository has.

``occupancy.stacking_layers`` decides how far below (or above) the board every conductor is
drawn, and the 2D view, the 3D view, the STEP export and the build guide's order all read
it. These tests hold its answers to the two physical facts it exists for, on every example
and golden board as it is shipped and as auto-wire lays it again:

* two conductors on one face that touch -- cross, or share a stretch of one line -- are not
  at one level;
* a wire lying across the hole another conductor ends in is above it, because that one
  comes down to its pad there. A loop (``stacking_loops``) is exempt: no order satisfies it;
* a wire lying across a pin's hole on the face its lead comes out of is off level 0, clear
  of the trimmed stub.

They ask the engine rather than the drawn tubes, so they hold whatever the views do with
the levels (``tests/test_ui.py::test_no_two_conductors_are_drawn_in_the_same_place``
measures the tubes, on the goldens).
"""

from __future__ import annotations

import dataclasses
import itertools
from pathlib import Path

import pytest

from perfboard_studio import persist, system
from perfboard_studio.autoroute import AutorouteOptions, plan_autoroute
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import (
    all_pin_holes,
    hole_key,
    holes_under_line,
    paths_cross,
    paths_overlap,
)
from perfboard_studio.model import Conductor, PerfDocument, contacts_every_path_hole
from perfboard_studio.occupancy import stacking_layers, stacking_loops
from perfboard_studio.router import RouterOptions

ROOT = Path(__file__).resolve().parents[1]
BOARDS = sorted((ROOT / "examples").rglob("*.perf")) + sorted(
    (ROOT / "tools" / "diffcheck" / "golden").glob("*.perf")
)
LOOKUP = footprint_lookup()


def _boards(path: Path) -> list[tuple[str, PerfDocument]]:
    whole = persist.deserialize_document(path.read_text(encoding="utf-8")).document
    return [(board_id, system.board_document(whole, board_id)) for board_id in system.board_ids(whole)]


def _is_wire(conductor: Conductor) -> bool:
    return not contacts_every_path_hole(conductor) and len(conductor.path) >= 2


def _lies_across(conductor: Conductor) -> set[str]:
    ends = {hole_key(conductor.path[0]), hole_key(conductor.path[-1])}
    under = {
        hole_key(hole)
        for start, stop in itertools.pairwise(conductor.path)
        for hole in holes_under_line(start, stop)
    }
    return under - ends


def _faults(doc: PerfDocument) -> list[str]:
    levels = stacking_layers(doc, lookup=LOOKUP)
    looped = {member: loop for loop in stacking_loops(doc) for member in loop}
    faults: list[str] = []
    stubs = {
        (hole_key(hole), "bottom" if component.side == "top" else "top")
        for component in doc.components
        if (footprint := LOOKUP(component.footprint_id)) is not None
        for _pin, hole in all_pin_holes(component, footprint)
    }
    for conductor in doc.conductors:
        if _is_wire(conductor) and levels[conductor.id] == 0:
            over = sorted(k for k in _lies_across(conductor) if (k, conductor.side) in stubs)
            if over:
                faults.append(f"{conductor.id} lies at level 0 across the leads at {over}")
    drawn = [c for c in doc.conductors if len(c.path) >= 2]
    for a, b in itertools.combinations(drawn, 2):
        if a.side != b.side or not (_is_wire(a) or _is_wire(b)):
            continue
        touching = paths_cross(a.path, b.path) is not None or paths_overlap(a.path, b.path)
        if touching and levels[a.id] == levels[b.id]:
            faults.append(f"{a.id} and {b.id} touch at one level ({levels[a.id]})")
        for upper, lower in ((a, b), (b, a)):
            if not _is_wire(upper) or not _is_wire(lower):
                continue
            if looped.get(upper.id) is not None and looped.get(upper.id) == looped.get(lower.id):
                continue
            ends = {hole_key(lower.path[0]), hole_key(lower.path[-1])}
            if ends & _lies_across(upper) and levels[upper.id] <= levels[lower.id]:
                faults.append(
                    f"{upper.id} (level {levels[upper.id]}) lies across the end of "
                    f"{lower.id} (level {levels[lower.id]})"
                )
    return faults


CASES = [
    pytest.param(path, board_id, id=f"{path.stem}-{board_id}")
    for path in BOARDS
    for board_id, _doc in _boards(path)
]


@pytest.mark.parametrize(("path", "board_id"), CASES)
def test_no_two_conductors_are_stacked_into_each_other_as_shipped(path: Path, board_id: str) -> None:
    """With no loop exempt: the examples were auto-wired again once the router stopped
    making them (three, on arduino-io-shield and atmega328-relay, drawn through each other)."""
    doc = dict(_boards(path))[board_id]
    assert _faults(doc) == []
    assert stacking_loops(doc) == ()


@pytest.mark.parametrize(("path", "board_id"), CASES)
def test_no_two_conductors_are_stacked_into_each_other_once_auto_wired(
    path: Path, board_id: str
) -> None:
    """Auto-wired as the window lays wires, along the grid: where the 14 came from."""
    doc = dict(_boards(path))[board_id]
    if not doc.components:
        pytest.skip("nothing to wire")
    bare = dataclasses.replace(doc, conductors=())
    plan = plan_autoroute(bare, LOOKUP, AutorouteOptions(router=RouterOptions(wire_path="grid")))
    assert _faults(plan.document) == []


@pytest.mark.parametrize(("path", "board_id"), CASES)
def test_a_board_stacks_the_same_before_save_and_after_open(path: Path, board_id: str) -> None:
    """``persist`` writes conductors sorted by id, and auto-wire appends them as it makes
    them; stacking in document order drew the arduino example's wires one way as auto-wire
    left them and another once saved and opened."""
    doc = dict(_boards(path))[board_id]
    if not doc.components:
        pytest.skip("nothing to wire")
    bare = dataclasses.replace(doc, conductors=())
    plan = plan_autoroute(bare, LOOKUP, AutorouteOptions(router=RouterOptions(wire_path="grid")))
    reopened = persist.deserialize_document(persist.serialize_document(plan.document)).document

    assert stacking_layers(reopened, lookup=LOOKUP) == stacking_layers(plan.document, lookup=LOOKUP)
    assert stacking_layers(doc, lookup=LOOKUP) == stacking_layers(
        dataclasses.replace(doc, conductors=tuple(reversed(doc.conductors))), lookup=LOOKUP
    )


@pytest.mark.parametrize(("path", "board_id"), CASES)
def test_auto_wire_makes_no_stacking_loop(path: Path, board_id: str) -> None:
    """Two wires each lying across the other's end can be soldered in neither order, and no
    stacking draws them apart. The router prices lying across the end of a wire that has to
    be above the new one (``RouterCosts.wire_into_loop``); the auto-wired atmega328-relay
    and arduino-io-shield each made one before it did."""
    doc = dict(_boards(path))[board_id]
    if not doc.components:
        pytest.skip("nothing to wire")
    bare = dataclasses.replace(doc, conductors=())
    plan = plan_autoroute(bare, LOOKUP, AutorouteOptions(router=RouterOptions(wire_path="grid")))
    assert stacking_loops(plan.document) == ()
