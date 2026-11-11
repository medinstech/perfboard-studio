"""What copper drawn by hand would do, asked before it is laid (``ui/drawcheck.py``).

On ne555-astable, whose copper is all on the solder side: the audit's own cases, each the
answer DRC gives once the copper is in, asked before it is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    AddConductorPayload,
    NewSolderTraceConductor,
    NewWireConductor,
    create_document_id_generator,
    create_standard_registry,
    wire_side,
)
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import format_hole, parse_hole
from perfboard_studio.lvs import run_lvs
from perfboard_studio.model import ConductorKind, HoleCoord, PerfDocument
from perfboard_studio.ui.drawcheck import check_drawn

NE555 = Path(__file__).resolve().parents[1] / "examples" / "ne555-astable.perf"


@pytest.fixture(scope="module")
def ne555() -> PerfDocument:
    return persist.deserialize_document(NE555.read_text(encoding="utf-8")).document


def _path(document: PerfDocument, *refs: str) -> tuple[HoleCoord, ...]:
    holes = tuple(parse_hole(ref, document.board) for ref in refs)
    assert all(hole is not None for hole in holes), refs
    return holes  # type: ignore[return-value]


def _net(document: PerfDocument, name: str) -> str:
    return next(net.id for net in document.nets if net.name == name)


def test_a_run_through_another_nets_pad_is_a_short_at_that_pad(ne555: PerfDocument) -> None:
    """F1 is LED_A's; F2 is LED1's other leg, on GND. Every pad a run crosses is soldered."""
    checked = check_drawn(ne555, footprint_lookup(), "solder-trace", _path(ne555, "F1", "F2", "F3"))

    assert checked.worst is not None
    assert checked.worst.kind == "short" and checked.worst.severity == "error"
    assert format_hole(checked.worst.hole, ne555.board) == "F2"
    assert checked.worst.nets == ("LED_A", "GND")
    assert checked.net_id is None, "copper on two nets claims neither"


def test_a_wire_touches_only_its_ends(ne555: PerfDocument) -> None:
    """The same holes as a bare wire: it lies over F2 and is soldered at F1 and F3 only
    -- so no short at F2, which a run there would be."""
    checked = check_drawn(ne555, footprint_lookup(), "insulated-wire", _path(ne555, "F1", "F3"))

    assert not [p for p in checked.problems if p.kind == "short"]


def test_the_net_comes_from_what_the_copper_meets_not_only_two_pins(ne555: PerfDocument) -> None:
    """G6 is the end of a GND wire, not a pin: the old rule wanted a pin of one net at BOTH
    ends and gave this wire no net, which Redo Wiring then never touched."""
    checked = check_drawn(ne555, footprint_lookup(), "bare-wire", _path(ne555, "G6", "F2"))

    assert checked.problems == ()
    assert checked.net_id == _net(ne555, "GND")


def test_copper_on_nothing_claims_nothing(ne555: PerfDocument) -> None:
    checked = check_drawn(ne555, footprint_lookup(), "solder-trace", _path(ne555, "B6", "B5", "B4"))

    assert checked.problems == () and checked.net_id is None


def test_a_bare_wire_across_bare_wires_crosses_where_they_meet(ne555: PerfDocument) -> None:
    """Q6 → Q2 across the two VCC wires: named at the holes the lines share, the way a
    person finds them, and as errors -- bare copper on bare copper touches."""
    checked = check_drawn(ne555, footprint_lookup(), "bare-wire", _path(ne555, "Q6", "Q2"))

    crossings = [(p.other.id if p.other else "", format_hole(p.hole, ne555.board))
                 for p in checked.problems if p.kind == "cross"]
    assert crossings == [("cond-5", "Q4"), ("cond-6", "Q3")]
    assert checked.net_id == _net(ne555, "DISCH")


def test_a_wire_along_another_is_a_warning_not_an_error(ne555: PerfDocument) -> None:
    """Not a short and refused nowhere -- the router prices it -- so amber, not red."""
    checked = check_drawn(ne555, footprint_lookup(), "insulated-wire", _path(ne555, "P1", "S1"))

    assert [(p.kind, p.severity, p.other.id if p.other else "") for p in checked.problems] == [
        ("along", "warning", "cond-1")
    ]


def test_the_same_copper_twice_is_found(ne555: PerfDocument) -> None:
    checked = check_drawn(ne555, footprint_lookup(), "solder-trace", _path(ne555, "I1", "H1", "G1", "F1"))

    assert checked.duplicate is not None and checked.duplicate.id == "cond-13"
    assert checked.net_id == _net(ne555, "LED_A")


def _laid(document: PerfDocument, kind: ConductorKind, path: tuple[HoleCoord, ...]) -> PerfDocument:
    bus = CommandBus(
        document, create_standard_registry(), CommandContext(next_id=create_document_id_generator(document))
    )
    spec = (
        NewSolderTraceConductor(path=path, kind="solder-trace")
        if kind == "solder-trace"
        else NewWireConductor(path=path, kind="bare-wire", side=wire_side(kind, document.board))
    )
    assert bus.dispatch("conductor.add", AddConductorPayload(conductor=spec)).ok
    return bus.document


@pytest.mark.parametrize(
    ("refs", "nets"),
    [(("F1", "F2", "F3"), {"LED_A", "GND"}), (("I4", "J4", "K4"), {"OUT", "CTRL"})],
)
def test_a_short_the_preview_marks_is_the_short_lvs_finds_once_it_is_laid(
    ne555: PerfDocument, refs: tuple[str, ...], nets: set[str]
) -> None:
    """One answer, two askers: the check is the engine's predicates asked early, so the two
    nets it says a run would join are the two LVS finds joined after the click."""
    lookup = footprint_lookup()
    path = _path(ne555, *refs)
    checked = check_drawn(ne555, lookup, "solder-trace", path)
    assert checked.worst is not None and set(checked.worst.nets) == nets

    before = {i.net_names for i in run_lvs(ne555, lookup).issues if i.kind == "short"}
    after = {
        i.net_names for i in run_lvs(_laid(ne555, "solder-trace", path), lookup).issues
        if i.kind == "short"
    }
    assert any(set(names) == nets for names in after - before), after - before


def test_a_crossing_the_preview_marks_is_the_crossing_drc_finds_once_it_is_laid(
    ne555: PerfDocument,
) -> None:
    lookup = footprint_lookup()
    path = _path(ne555, "Q6", "Q2")
    crossed = {p.other.id for p in check_drawn(ne555, lookup, "bare-wire", path).problems if p.other}

    before = {(v.rule, v.message) for v in run_drc(ne555, lookup)}
    found = {
        conductor_id
        for v in run_drc(_laid(ne555, "bare-wire", path), lookup)
        if (v.rule, v.message) not in before and v.rule == "conductor-crossing"
        for conductor_id in v.conductor_ids
    }
    assert crossed and crossed <= found, (crossed, found)


@pytest.mark.parametrize(
    ("kind", "refs", "found"),
    [
        ("solder-trace", ("G1", "H1"), "cond-13"),
        ("solder-trace", ("I1", "H1", "G1"), "cond-13"),
        ("solder-trace-wired", ("F1", "G1", "H1", "I1"), "cond-13"),
        ("solder-trace", ("H1", "I1", "J1"), None),
        ("bare-wire", ("G6", "G4", "G2", "F2"), "cond-2"),
        ("insulated-wire", ("F2", "G2", "G6"), "cond-2"),
        ("bare-wire", ("G6", "F6", "F2"), None),
    ],
)
def test_copper_exactly_over_copper_is_found_and_partly_over_is_not(
    ne555: PerfDocument, kind: ConductorKind, refs: tuple[str, ...], found: str | None
) -> None:
    """A run over a stretch of a run's pads, plain or wired, and a wire along exactly
    another's line -- a point mid-leg is not a corner -- add nothing. A run carried past
    the end, or a wire between the same ends by another corner, is new copper."""
    checked = check_drawn(ne555, footprint_lookup(), kind, _path(ne555, *refs))
    assert (checked.duplicate.id if checked.duplicate else None) == found
