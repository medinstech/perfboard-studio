"""Which board a design goes on, answered by building it -- ``boardfit``.

Three layers, and only the last one routes anything:

1. The JUDGE, on synthetic trials: what makes a smaller board as good as the roomy one.
2. The SEARCH, with ``try_board`` replaced by a script: which boards are tried, in what
   order, and when it stops -- including when it is told to.
3. Two small REAL trials: that a trial is deterministic, and that the placement it judged
   is the placement the window commits.

The measurements the constants rest on are ``tools/measure_board_choice.py``'s; the
examples moving onto the boards this recommends is ``tests/test_examples.py``'s business.
"""

from __future__ import annotations

import dataclasses

import pytest

from perfboard_studio import boardfit
from perfboard_studio.autoroute import DEFAULT_AUTOROUTE_OPTIONS
from perfboard_studio.boardfit import (
    MAX_SMALLER_BOARDS_TRIED,
    PLACEMENT_WARNING_RULES,
    ROUTE_COST_TOLERANCE,
    TRIAL_PLACEMENT_OPTIONS,
    BoardTrial,
    BoardTrialOptions,
    choose_board,
    judge,
    reference_verdict,
    try_board,
)
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    DEFAULT_BOARD,
    create_document_id_generator,
    create_empty_document,
    create_standard_registry,
    preset_payload,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import STANDARD_PRESETS, BoardPreset, board_from_preset
from perfboard_studio.model import (
    BoardNote,
    ComponentInstance,
    DocumentMeta,
    HoleCoord,
    Net,
    NetNode,
    PerfDocument,
    SchematicPart,
)
from perfboard_studio.placer import (
    PHYSICAL_WARNING_RULES,
    Arrangement,
    BoardSuggestion,
    DesignPlacement,
    PlacementOptions,
    placement_inputs,
    suggest_boards,
)

REGISTRY = footprint_lookup()
META = DocumentMeta(name="boardfit", created="2026-01-01", modified="2026-01-01")
DOUBLE_SIDED = sorted(
    (p for p in STANDARD_PRESETS if not p.single_sided), key=lambda p: p.width_mm * p.height_mm
)


def _preset(name: str) -> BoardPreset:
    return next(p for p in DOUBLE_SIDED if p.name == name)


def _suggestion(name: str, fill: float = 0.2) -> BoardSuggestion:
    preset = _preset(name)
    board = board_from_preset(preset, DEFAULT_BOARD)
    total = board.cols * board.rows
    return BoardSuggestion(preset, board, Arrangement((), (), round(total * fill), total))


def _trial(
    name: str = "5 x 7 cm",
    *,
    cost: float = 100.0,
    unrouted: int = 0,
    errors: int = 0,
    warnings: dict[str, int] | None = None,
    unplaced: tuple[str, ...] = (),
    refused: bool = False,
) -> BoardTrial:
    suggestion = _suggestion(name)
    doc = create_empty_document(META, suggestion.board)
    counts = warnings or {}
    return BoardTrial(
        suggestion=suggestion,
        document=None if refused else doc,
        placed=None if refused else DesignPlacement((), unplaced, (), doc, None),
        unplaced=unplaced,
        unrouted=unrouted,
        route_cost=cost,
        drc_errors=errors,
        warnings=tuple(counts.get(rule, 0) for rule in PLACEMENT_WARNING_RULES),
    )


# ---------------------------------------------------------------------------
# 1. The judge
# ---------------------------------------------------------------------------


def test_a_smaller_board_that_builds_as_well_is_accepted() -> None:
    verdict = judge(_trial("4 x 6 cm", cost=110.0), _trial("5 x 7 cm"), ROUTE_COST_TOLERANCE)
    assert verdict.kind == "accepted" and verdict.accepted
    assert verdict.cost_ratio == pytest.approx(1.1)


def test_the_cost_at_the_tolerance_is_accepted_and_past_it_is_not() -> None:
    reference = _trial("5 x 7 cm", cost=100.0)
    assert judge(_trial("4 x 6 cm", cost=120.0), reference, 1.20).kind == "accepted"
    dearer = judge(_trial("4 x 6 cm", cost=120.01), reference, 1.20)
    assert dearer.kind == "dearer" and not dearer.accepted


@pytest.mark.parametrize("rule", PLACEMENT_WARNING_RULES)
def test_a_warning_the_reference_does_not_have_rejects_the_board(rule: str) -> None:
    verdict = judge(
        _trial("4 x 6 cm", cost=90.0, warnings={rule: 1}), _trial("5 x 7 cm"), ROUTE_COST_TOLERANCE
    )
    assert verdict.kind == "new-warnings"
    assert verdict.new_warnings == (rule,)


def test_a_warning_the_reference_has_too_is_not_held_against_it() -> None:
    """Measured against the roomy board, not against perfection: a design whose regulator
    sits by a capacitor on every board is not made worse by the smaller one."""
    rule = "heat-proximity"
    verdict = judge(
        _trial("4 x 6 cm", warnings={rule: 1}),
        _trial("5 x 7 cm", warnings={rule: 1}),
        ROUTE_COST_TOLERANCE,
    )
    assert verdict.kind == "accepted"


@pytest.mark.parametrize(
    ("trial", "kind"),
    [
        ({"unplaced": ("U1",)}, "too-small"),
        ({"refused": True}, "too-small"),
        ({"unrouted": 2}, "unrouted"),
        ({"errors": 1}, "drc-errors"),
        # In the order they are checked: a board that leaves a connection unrouted is
        # rejected for THAT, whatever else is also wrong with it.
        ({"unrouted": 1, "errors": 3, "cost": 500.0, "warnings": {"heat-proximity": 2}}, "unrouted"),
    ],
)
def test_a_board_that_does_not_build_is_rejected_for_why(trial: dict, kind: str) -> None:
    verdict = judge(_trial("4 x 6 cm", **trial), _trial("5 x 7 cm"), ROUTE_COST_TOLERANCE)
    assert verdict.kind == kind and not verdict.accepted


def test_a_reference_that_costs_nothing_accepts_a_board_that_costs_nothing() -> None:
    """A design with nothing to wire. Compared as a product rather than a ratio, so there
    is no division by zero to reject it with."""
    verdict = judge(_trial("4 x 6 cm", cost=0.0), _trial("5 x 7 cm", cost=0.0), ROUTE_COST_TOLERANCE)
    assert verdict.kind == "accepted" and verdict.cost_ratio == 1.0


def test_the_reference_is_the_yardstick_only_when_it_builds() -> None:
    assert reference_verdict(_trial()).kind == "reference"
    assert reference_verdict(_trial(unrouted=1)).kind == "unrouted"


# ---------------------------------------------------------------------------
# 2. The search
# ---------------------------------------------------------------------------


def _suggestions(reference: str = "6 x 8 cm") -> list[BoardSuggestion]:
    """Every double-sided stock board: the ones below ``reference`` fit but too full to be
    roomy, so ``recommended_board`` picks ``reference`` exactly."""
    area = _preset(reference).width_mm * _preset(reference).height_mm
    return [
        _suggestion(p.name, 0.2 if p.width_mm * p.height_mm >= area else 0.5) for p in DOUBLE_SIDED
    ]


class _Script:
    """``try_board`` replaced by a script of outcomes per board, recording what it is asked."""

    def __init__(self, outcomes: dict[str, dict | None]) -> None:
        self.outcomes = outcomes
        self.tried: list[str] = []

    def __call__(self, document, suggestion, lookup, options, should_stop=None):
        name = suggestion.preset.name
        self.tried.append(name)
        outcome = self.outcomes[name]
        return None if outcome is None else _trial(name, **outcome)


def _choose(monkeypatch, outcomes, *, reference="6 x 8 cm", document=None, **options):
    script = _Script(outcomes)
    monkeypatch.setattr(boardfit, "try_board", script)
    doc = document if document is not None else create_empty_document(META, DEFAULT_BOARD)
    choice = choose_board(
        doc, REGISTRY, _suggestions(reference), options=BoardTrialOptions(**options)
    )
    return choice, script.tried


def test_the_search_descends_from_the_reference_and_stops_at_the_first_rejection(monkeypatch) -> None:
    choice, tried = _choose(
        monkeypatch,
        {"6 x 8 cm": {}, "5 x 7 cm": {"cost": 105.0}, "4 x 6 cm": {"cost": 130.0}},
    )
    assert tried == ["6 x 8 cm", "5 x 7 cm", "4 x 6 cm"], "largest first; bigger boards never"
    assert [v.kind for v in choice.verdicts] == ["reference", "accepted", "dearer"]
    assert choice.recommended is not None and choice.recommended.preset.name == "5 x 7 cm"
    assert choice.reference is not None and choice.reference.preset.name == "6 x 8 cm"
    assert choice.complete


def test_no_more_than_the_cap_are_tried(monkeypatch) -> None:
    every = {p.name: {} for p in DOUBLE_SIDED}
    choice, tried = _choose(monkeypatch, every, max_smaller_boards=2)
    assert tried == ["6 x 8 cm", "5 x 7 cm", "4 x 6 cm"]
    assert choice.recommended is not None and choice.recommended.preset.name == "4 x 6 cm"
    assert choice.complete, "stopping at the cap is the search ending, not being stopped"


def test_a_reference_that_does_not_build_is_not_descended_from(monkeypatch) -> None:
    choice, tried = _choose(monkeypatch, {"6 x 8 cm": {"unrouted": 3}})
    assert tried == ["6 x 8 cm"]
    assert [v.kind for v in choice.verdicts] == ["unrouted"]
    assert choice.recommended == choice.reference


def test_the_smallest_board_as_reference_tries_nothing(monkeypatch) -> None:
    choice, tried = _choose(monkeypatch, {}, reference="2 x 8 cm")
    assert tried == [] and choice.verdicts == ()
    assert choice.recommended is not None and choice.recommended.preset.name == "2 x 8 cm"


def test_stopping_part_way_keeps_the_verdicts_so_far(monkeypatch) -> None:
    """A trial cut short is not a verdict on its board: it is thrown away, the smallest
    board judged so far is the answer, and the choice says it did not finish."""
    choice, tried = _choose(monkeypatch, {"6 x 8 cm": {}, "5 x 7 cm": {}, "4 x 6 cm": None})
    assert tried == ["6 x 8 cm", "5 x 7 cm", "4 x 6 cm"]
    assert [v.preset.name for v in choice.verdicts] == ["6 x 8 cm", "5 x 7 cm"]
    assert choice.recommended is not None and choice.recommended.preset.name == "5 x 7 cm"
    assert not choice.complete


def test_a_stripboard_is_not_tried(monkeypatch) -> None:
    """Its boards are judged by the strip planner, which no tolerance here was measured
    on: the reference stays the answer, as it always was."""
    strips = create_empty_document(
        META, dataclasses.replace(DEFAULT_BOARD, type="stripboard", strip_axis="horizontal")
    )
    choice, tried = _choose(monkeypatch, {}, document=strips)
    assert tried == [] and choice.recommended == choice.reference


def test_each_board_is_named_before_it_is_tried(monkeypatch) -> None:
    named: list[str] = []
    script = _Script({"6 x 8 cm": {}, "5 x 7 cm": {"cost": 500.0}})
    monkeypatch.setattr(boardfit, "try_board", script)
    choose_board(
        create_empty_document(META, DEFAULT_BOARD),
        REGISTRY,
        _suggestions(),
        on_trial=lambda preset: named.append(preset.name),
    )
    assert named == script.tried == ["6 x 8 cm", "5 x 7 cm"]


def test_the_trial_options_are_the_ones_measured() -> None:
    """The numbers ``tools/measure_board_choice.py`` measured, pinned so that changing one
    is a decision with the measurement run again, not an edit."""
    assert PlacementOptions(seed=0) == TRIAL_PLACEMENT_OPTIONS
    assert ROUTE_COST_TOLERANCE == 1.20
    assert MAX_SMALLER_BOARDS_TRIED == 4


def test_the_watched_warnings_are_the_placers_physical_warnings() -> None:
    """One table: what the placer ranks ahead of the routed cost is what a smaller board is
    not allowed to add."""
    assert tuple(rule for _, rule in PHYSICAL_WARNING_RULES) == PLACEMENT_WARNING_RULES


# ---------------------------------------------------------------------------
# 3. Real trials, kept small
# ---------------------------------------------------------------------------


def _design(board_name: str = "9 x 15 cm") -> PerfDocument:
    """A 555-sized design with nothing placed, on a board with room for it."""
    parts = (
        SchematicPart(id="p-U1", ref="U1", value="NE555", footprint_id="dip-8"),
        SchematicPart(id="p-R1", ref="R1", value="1k", footprint_id="r-axial-3"),
        SchematicPart(id="p-R2", ref="R2", value="10k", footprint_id="r-axial-3"),
        SchematicPart(id="p-C1", ref="C1", value="10u", footprint_id="c-elec-d5-p2"),
    )
    nets = (
        Net(id="n1", name="VCC", net_class="power", nodes=(
            NetNode(component_ref="U1", pin="8"), NetNode(component_ref="R1", pin="1"),
        )),
        Net(id="n2", name="DIS", net_class="signal", nodes=(
            NetNode(component_ref="U1", pin="7"), NetNode(component_ref="R1", pin="2"),
            NetNode(component_ref="R2", pin="1"),
        )),
        Net(id="n3", name="THR", net_class="signal", nodes=(
            NetNode(component_ref="U1", pin="6"), NetNode(component_ref="R2", pin="2"),
            NetNode(component_ref="C1", pin="1"),
        )),
        Net(id="n4", name="GND", net_class="ground", nodes=(
            NetNode(component_ref="U1", pin="1"), NetNode(component_ref="C1", pin="2"),
        )),
    )
    board = board_from_preset(_preset(board_name), DEFAULT_BOARD)
    return dataclasses.replace(create_empty_document(META, board), parts=parts, nets=nets)


def _real_suggestion(doc: PerfDocument, name: str) -> BoardSuggestion:
    suggestions = suggest_boards(doc.board, [], doc.nets, REGISTRY)
    return next(s for s in suggestions if s.preset.name == name)


def test_a_trial_is_deterministic() -> None:
    doc = _design()
    suggestion = _real_suggestion(doc, "3 x 7 cm")
    first = try_board(doc, suggestion, REGISTRY)
    assert first is not None and first.builds
    assert try_board(doc, suggestion, REGISTRY) == first


def test_the_placement_a_trial_judged_is_the_one_the_window_commits() -> None:
    """What makes it safe to commit a trial's placement instead of working one out again:
    the board the window applies is the board the trial was placed on, and the payload
    lands the parts exactly where they were judged."""
    doc = _design()
    suggestion = _real_suggestion(doc, "3 x 7 cm")
    trial = try_board(doc, suggestion, REGISTRY)
    assert trial is not None and trial.placed is not None and trial.document is not None

    bus = CommandBus(doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc)))
    assert bus.dispatch("board.applyPreset", preset_payload(suggestion.preset, suggestion.board)).ok
    assert placement_inputs(bus.document) == placement_inputs(trial.document)
    assert bus.dispatch("part.place", trial.placed.payload()).ok
    assert bus.document.components == trial.placed.document.components
    assert bus.document.parts == ()


def test_a_trial_takes_the_route_the_placer_already_made_of_the_same_board(monkeypatch) -> None:
    """The placer routes its shortlist to choose between them, so the winner has been routed
    before the trial asks. Taking that route is right only because it IS the route a fresh
    plan would make -- the same document, the same options, a pure planner -- so both halves
    are held here: the trial does not route again, and what it took equals a route planned
    from nothing."""
    doc = _design()
    suggestion = _real_suggestion(doc, "3 x 7 cm")
    real = boardfit.plan_autoroute
    calls: list[object] = []

    def counted(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(boardfit, "plan_autoroute", counted)
    trial = try_board(doc, suggestion, REGISTRY)

    assert trial is not None and trial.placed is not None and trial.placed.plan is not None
    assert calls == [], "the trial planned a route the placer had already made"
    routed = trial.placed.plan.routed
    assert routed is not None and routed.document == trial.placed.document
    fresh = real(trial.placed.document, REGISTRY)
    assert routed.plan == fresh
    assert (trial.unrouted, trial.route_cost) == (
        fresh.summary.links_unrouted,
        fresh.summary.total_cost,
    )


def test_a_route_made_on_another_document_or_with_other_options_is_not_taken() -> None:
    doc = _design()
    trial = try_board(doc, _real_suggestion(doc, "3 x 7 cm"), REGISTRY)
    assert trial is not None and trial.placed is not None and trial.placed.plan is not None
    placed = trial.placed
    routed = placed.plan.routed
    assert routed is not None

    assert boardfit._route_already_planned(placed, DEFAULT_AUTOROUTE_OPTIONS) is routed.plan
    other = dataclasses.replace(DEFAULT_AUTOROUTE_OPTIONS, max_passes=1)
    assert boardfit._route_already_planned(placed, other) is None
    # A part sent back to the design after placing: not the board that was routed.
    fewer = dataclasses.replace(
        placed,
        document=dataclasses.replace(
            placed.document, components=placed.document.components[1:]
        ),
    )
    assert boardfit._route_already_planned(fewer, DEFAULT_AUTOROUTE_OPTIONS) is None


def test_labels_written_for_a_bigger_board_do_not_stop_a_trial() -> None:
    """Somebody wrote "12V IN" by the far edge of the board they had. On a smaller board
    that text has nowhere to be, and nothing about where parts go depends on it."""
    doc = dataclasses.replace(
        _design(), board_notes=(BoardNote(id="bn-1", at=HoleCoord(30, 50), text="12V IN"),)
    )
    trial = try_board(doc, _real_suggestion(doc, "3 x 7 cm"), REGISTRY)
    assert trial is not None and trial.builds
    assert trial.document is not None and trial.document.board_notes == ()


def test_a_part_already_down_that_a_smaller_board_strands_makes_it_too_small() -> None:
    doc = dataclasses.replace(
        _design(),
        components=(
            ComponentInstance(
                id="cmp-9", ref="R9", value="1k", footprint_id="r-axial-3", anchor=HoleCoord(30, 50)
            ),
        ),
    )
    small = _real_suggestion(doc, "3 x 7 cm")
    trial = try_board(doc, small, REGISTRY)
    assert trial is not None and trial.document is None and not trial.builds
    assert judge(trial, trial, ROUTE_COST_TOLERANCE).kind == "too-small"
