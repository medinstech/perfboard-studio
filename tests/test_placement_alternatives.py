"""Placement alternatives: the placer's ranking kept whole, wired, and committed as one command.

What is pinned: the first alternative IS what ``plan_placement`` returns; the board as it
is is always among them and nothing offered twice; a card is wired by Auto-wire's own call;
on a wired board the chosen one is ONE ``component.rearrange`` whose result is the preview
that was shown; and the answers are the same however the work is run.
"""

from __future__ import annotations

import dataclasses
import pickle
from pathlib import Path
from typing import Any, get_args

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    ComponentPlacement,
    LockComponentsPayload,
    MoveComponentsPayload,
    RearrangePayload,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import ConductorKind, HoleCoord, PerfDocument
from perfboard_studio.placer import (
    PlacementAlternatives,
    PlacementOptions,
    _layout_key,
    _WireJob,
    plan_placement,
    plan_placements,
    rearrange_label,
    wire_alternative,
    wire_alternatives,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
LOOKUP = footprint_lookup()
#: Short anneals: what is tested is what is kept of the ranking, not how good it is.
QUICK = PlacementOptions(seed=0, iterations=400)


def _example(name: str) -> PerfDocument:
    return persist.parse_document_or_throw((EXAMPLES / f"{name}.perf").read_text(encoding="utf-8"))


def _bus(doc: PerfDocument) -> CommandBus:
    return CommandBus(
        doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc))
    )


def _serial(work: Any, jobs: Any) -> list[Any]:
    """A mapper that runs in this process: the mapper path, without a pool."""
    return [work(job, None) for job in jobs]


@pytest.fixture(scope="module")
def wired_board() -> tuple[PerfDocument, PlacementAlternatives]:
    doc = _example("nano-relay")
    return doc, plan_placements(doc, LOOKUP, QUICK)


# -- the ranking ---------------------------------------------------------------------


@pytest.mark.parametrize(("name", "seed"), [("ne555-astable", 0), ("nano-relay", 0), ("nano-relay", 1)])
def test_the_first_alternative_is_what_plan_placement_returns(name: str, seed: int) -> None:
    doc = _example(name)
    options = dataclasses.replace(QUICK, seed=seed)
    assert plan_placements(doc, LOOKUP, options).best.plan == plan_placement(doc, LOOKUP, options)


def test_the_board_as_it_is_is_offered_once_and_nothing_twice(
    wired_board: tuple[PerfDocument, PlacementAlternatives],
) -> None:
    doc, alternatives = wired_board
    offered = alternatives.alternatives
    assert [a.rank for a in offered] == list(range(1, len(offered) + 1))
    assert sum(a.is_baseline for a in offered) == 1
    assert alternatives.baseline.plan.changes == ()
    assert alternatives.baseline.plan.document == doc
    assert 1 <= len(alternatives.candidates) <= 3
    keys = [_layout_key(a.plan.document, LOOKUP) for a in offered]
    assert len(set(keys)) == len(keys), "an arrangement is offered at most once"


def test_count_bounds_the_arrangements_offered(
    wired_board: tuple[PerfDocument, PlacementAlternatives],
) -> None:
    doc, _ = wired_board
    one = plan_placements(doc, LOOKUP, QUICK, count=1)
    assert len(one.candidates) <= 1
    assert one.best.plan == plan_placement(doc, LOOKUP, QUICK)


def test_nothing_to_move_is_the_board_as_it_is_alone() -> None:
    doc = _example("ne555-astable")
    bus = _bus(doc)
    assert bus.dispatch(
        "component.lockMany",
        LockComponentsPayload(ids=tuple(c.id for c in doc.components), locked=True),
    ).ok
    alternatives = plan_placements(bus.document, LOOKUP, QUICK)
    assert len(alternatives.alternatives) == 1
    assert alternatives.best.is_baseline and alternatives.best.move_payload() is None


def test_a_layout_shifted_turned_or_mirrored_is_the_same_layout() -> None:
    doc = _example("ne555-astable")

    def moved(col: int, row: int) -> PerfDocument:
        return dataclasses.replace(
            doc,
            components=tuple(
                dataclasses.replace(c, anchor=HoleCoord(c.anchor.col + col, c.anchor.row + row))
                for c in doc.components
            ),
        )

    assert _layout_key(moved(1, 2), LOOKUP) == _layout_key(doc, LOOKUP)
    turned = dataclasses.replace(
        doc,
        components=tuple(
            dataclasses.replace(
                c,
                anchor=HoleCoord(-c.anchor.col, -c.anchor.row),
                rotation=(c.rotation + 180) % 360,  # type: ignore[arg-type]
            )
            for c in doc.components
        ),
    )
    assert _layout_key(turned, LOOKUP) == _layout_key(doc, LOOKUP)
    one_part_moved = dataclasses.replace(
        doc,
        components=(
            dataclasses.replace(
                doc.components[0],
                anchor=HoleCoord(doc.components[0].anchor.col, doc.components[0].anchor.row + 1),
            ),
            *doc.components[1:],
        ),
    )
    assert _layout_key(one_part_moved, LOOKUP) != _layout_key(doc, LOOKUP)


# -- wiring a card -------------------------------------------------------------------


def test_a_card_on_a_wired_board_commits_as_one_rearrange_that_is_its_preview(
    wired_board: tuple[PerfDocument, PlacementAlternatives],
) -> None:
    doc, alternatives = wired_board
    candidate = alternatives.candidates[0]
    wired = wire_alternative(candidate, LOOKUP)

    assert isinstance(wired.commit, RearrangePayload)
    assert set(wired.commit.remove_ids) == {c.id for c in doc.conductors}
    assert not set(wired.commit.ids or ()) & {c.id for c in doc.conductors}, (
        "new copper never reuses an id the board held"
    )
    assert wired.commit.label == rearrange_label(candidate.moved, rewired=True)
    assert wired.style is not None

    bus = _bus(doc)
    result = bus.dispatch("component.rearrange", wired.commit)
    assert result.ok, result.message
    assert bus.document == wired.document, "the committed board is the one shown"
    assert bus.history()[-1] == f"Rearrange {candidate.moved} parts and rewire"
    bus.undo()
    assert bus.document is doc, "one undo step"


def test_a_card_on_a_bare_board_commits_the_moves_alone() -> None:
    doc = dataclasses.replace(_example("nano-relay"), conductors=())
    alternatives = plan_placements(doc, LOOKUP, QUICK)
    candidate = alternatives.candidates[0]
    wired = wire_alternative(candidate, LOOKUP)

    assert isinstance(wired.commit, MoveComponentsPayload)
    assert wired.commit == candidate.move_payload()
    assert wired.document.conductors, "the card still shows the copper Auto-wire would lay"
    bus = _bus(doc)
    assert bus.dispatch("component.moveMany", wired.commit).ok
    assert bus.document.components == wired.document.components
    assert bus.document.conductors == ()


def test_the_board_as_it_is_keeps_its_own_copper_and_commits_nothing(
    wired_board: tuple[PerfDocument, PlacementAlternatives],
) -> None:
    doc, alternatives = wired_board
    wired = wire_alternative(alternatives.baseline, LOOKUP)
    assert wired.document == doc
    assert wired.style is None and wired.commit is None


def test_a_card_counts_its_conductors_by_kind(
    wired_board: tuple[PerfDocument, PlacementAlternatives],
) -> None:
    _doc, alternatives = wired_board
    wired = wire_alternative(alternatives.candidates[0], LOOKUP)
    assert [kind for kind, _n in wired.conductors_by_kind] == list(get_args(ConductorKind))
    assert sum(n for _kind, n in wired.conductors_by_kind) == len(wired.document.conductors)


def test_a_stop_before_a_card_leaves_it_unwired(
    wired_board: tuple[PerfDocument, PlacementAlternatives],
) -> None:
    _doc, alternatives = wired_board
    assert wire_alternatives(alternatives, LOOKUP, should_stop=lambda: True) == (None,) * len(
        alternatives.alternatives
    )


def test_wiring_is_the_same_through_a_mapper(
    wired_board: tuple[PerfDocument, PlacementAlternatives],
) -> None:
    _doc, alternatives = wired_board
    serial = wire_alternatives(alternatives, LOOKUP)
    assert wire_alternatives(alternatives, LOOKUP, mapper=_serial) == serial
    job = _WireJob(alternatives.candidates[0], LOOKUP, wired_options(), ("balanced",))
    assert pickle.loads(pickle.dumps(job)) == job, "a worker process can be handed it"


def test_placements_are_the_same_through_a_mapper(
    wired_board: tuple[PerfDocument, PlacementAlternatives],
) -> None:
    doc, alternatives = wired_board
    assert plan_placements(doc, LOOKUP, QUICK, mapper=_serial) == alternatives


def wired_options() -> Any:
    from perfboard_studio.autoroute import AutorouteOptions
    from perfboard_studio.router import RouterOptions

    return AutorouteOptions(router=RouterOptions(wire_path="grid"))


# -- the command ---------------------------------------------------------------------


def test_a_locked_part_refuses_the_whole_rearrangement_and_names_itself() -> None:
    doc = _example("ne555-astable")
    first, second = doc.components[0], doc.components[1]
    bus = _bus(doc)
    assert bus.dispatch(
        "component.lockMany", LockComponentsPayload(ids=(second.id,), locked=True)
    ).ok
    locked = bus.document
    result = bus.dispatch(
        "component.rearrange",
        RearrangePayload(
            placements=(
                ComponentPlacement(id=first.id, anchor=first.anchor, rotation=first.rotation),
                ComponentPlacement(id=second.id, anchor=second.anchor, rotation=second.rotation),
            ),
            remove_ids=tuple(c.id for c in doc.conductors),
            conductors=(),
        ),
    )
    assert not result.ok
    assert second.ref in result.message
    assert bus.document is locked


def test_the_rearrangement_is_said_by_its_count_without_a_label() -> None:
    doc = _example("ne555-astable")
    first = doc.components[0]
    bus = _bus(doc)
    result = bus.dispatch(
        "component.rearrange",
        RearrangePayload(
            placements=(ComponentPlacement(id=first.id, anchor=first.anchor),),
            remove_ids=tuple(c.id for c in doc.conductors),
            conductors=(),
        ),
    )
    assert result.ok, result.message
    assert bus.history()[-1] == "Rearrange 1 part and rewire"
    assert bus.document.conductors == ()
