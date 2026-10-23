"""Which stock board a design should go on -- TRIED, not estimated.

``placer.suggest_boards`` lays a design out on every stock board with the constructive
:func:`placer.arrange` and ``placer.recommended_board`` takes the first one it fills to a
third or less. That is quick, and it was calibrated on the examples' own recommended boards,
which is to say on itself -- and it was a board and a half too big. The 24-part
``atmega328-relay`` was sent to 9 x 15 cm while it places, routes and checks just as cleanly
on 7 x 9 cm, less than half the board: most of the substrate somebody paid for was bare.

So the recommendation is now answered by BUILDING the design on the boards, the way the
window would: put the whole design on a board (``placer.place_design``), route it, run DRC,
and compare the result with the same design on the roomy board. The cheap answer survives as
the REFERENCE -- the board the circuit certainly has room on -- and the search walks down
from it, one stock size at a time, for as long as the smaller board builds as well:

- every part placed, every connection routed, no DRC error;
- no placement warning the roomy board does not have (``PLACEMENT_WARNING_RULES`` --
  a hot part beside one that minds, a part under a screw head, a body over the edge, a
  terminal's wire entry blocked or facing into the board);
- no more than ``ROUTE_COST_TOLERANCE`` times the reference's routing cost.

It stops at the first board that fails, and recommends the smallest one that passed.

Pure, like every engine module: no clock, no Qt, and nothing random that is not seeded, so
the same design gets the same answer every time. The time a trial takes is the host's
business -- the window runs this on a worker thread with a Cancel button, and a trial that
was stopped part way is thrown away rather than judged.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Literal, TypeAlias

from .autoroute import DEFAULT_AUTOROUTE_OPTIONS, AutorouteOptions, AutoroutePlan, plan_autoroute
from .command import CommandError
from .commands import document_on_preset
from .connectivity import FootprintLookup
from .drc import run_drc
from .geometry import BoardPreset
from .model import PerfDocument
from .placer import (
    PHYSICAL_WARNING_RULES,
    BoardSuggestion,
    DesignPlacement,
    Mapper,
    PlacementOptions,
    design_entries,
    place_design,
    recommended_board,
    suggest_boards,
)
from .stripboard import is_stripboard

#: The DRC warnings a smaller board may not add: every warning about where a part IS, in
#: the placer's own table, so the judge and the placer's ranking cannot disagree about
#: which warnings a placement is responsible for.
PLACEMENT_WARNING_RULES: tuple[str, ...] = tuple(rule for _, rule in PHYSICAL_WARNING_RULES)

#: How much dearer to route a smaller board may be than the reference and still count as
#: building as well -- the "balanced" setting, chosen over 1.05 and over no limit at all.
#:
#: What ``tools/measure_board_choice.py --seeds 0 1 2 3`` found, every example taken back to
#: its design and tried from the reference down: every smaller board that built with no new
#: warning cost between 0.80 and 1.17 times its reference, and every one rejected on cost
#: alone came out at 1.22 or more --
#:
#:     accepted, highest    nano-relay 7 x 9 1.17 · atmega328-relay 6 x 8 1.16 · 1.15, 1.14
#:     dearer, lowest       ne555-blinker 2 x 8 1.22 · lm317-supply 3 x 7 1.23 · nano 6 x 8 1.27
#:
#: -- so 1.20 falls in the gap between them rather than on either side of one. The ratio is a
#: proxy: routed solder-first, the atmega on 6 x 8 cm needed 57 wires where 9 x 15 needed 26,
#: and that is the kind of board it is there to catch.
ROUTE_COST_TOLERANCE = 1.20

#: How each board is placed for its trial: exactly as Auto-place and Place on the Board
#: place, the placer's own defaults at seed 0.
#:
#: Lighter was tried and is not worth the time it saves. A verdict compares ONE placement on
#: the smaller board with ONE on the reference, and an anneal's routed cost varies from seed
#: to seed -- nano-relay's reference came out between 353 and 402 -- so a lucky reference
#: rejects a board that builds perfectly well. Over seeds 0-3, two restarts with two routed
#: recommended four different boards for nano-relay and two each for ne555-astable and
#: lm317-supply; four restarts with two routed still left nano-relay on 9 x 15 cm at seed 0.
#: The defaults gave ne555-astable one answer on every seed and the other two one answer on
#: three of four, at about twice the time of the lightest.
#:
#: What the defaults recommend at seeds 0, 1, 2, 3, and the whole question's time at seed 0:
#:
#:     arduino-io-shield   5 x 7 ->  2 x 8   2 x 8   2 x 8   2 x 8      5 s
#:     atmega328-relay     9 x 15 -> 7 x 9   7 x 9   6 x 8   6 x 8     25 s
#:     lm317-supply        6 x 8 ->  4 x 6   4 x 6   4 x 6   2 x 8      8 s
#:     lpb1-booster        7 x 9 ->  5 x 7   5 x 7   5 x 7   5 x 7      4 s
#:     nano-relay          9 x 15 -> 7 x 9   6 x 8   6 x 8   6 x 8     10 s
#:     ne555-astable       4 x 6 ->  2 x 8   2 x 8   2 x 8   2 x 8      3 s
#:     ne555-blinker       6 x 8 ->  2 x 8   2 x 8   3 x 7   3 x 7     10 s
#:
#: A seed can still move an answer by a size, and only ever between boards that both built
#: as well as the reference: which of two acceptable boards is the smallest acceptable one
#: is the part a single anneal cannot settle. The window asks at seed 0, so the same design
#: always gets the same answer.
TRIAL_PLACEMENT_OPTIONS = PlacementOptions(seed=0)

#: The most boards below the reference one question will try. The longest descent measured
#: is four (lm317-supply and ne555-blinker, 6 x 8 cm down to 2 x 8), and a trial is up to ten
#: seconds on a 24-part design; a reference several sizes too big would otherwise try every
#: board in the list.
MAX_SMALLER_BOARDS_TRIED = 4

#: What a trial found. ``reference`` is the roomy board itself, built cleanly; the rest are
#: a smaller board's verdict against it, in the order they are checked.
VerdictKind: TypeAlias = Literal[  # noqa: UP040 -- read at run time by get_args
    "reference", "accepted", "too-small", "unrouted", "drc-errors", "new-warnings", "dearer"
]


@dataclass(frozen=True, slots=True)
class BoardTrialOptions:
    placement: PlacementOptions = TRIAL_PLACEMENT_OPTIONS
    #: The engine's routing defaults: what ``placer._pick_best`` prices every candidate in,
    #: and what ``ROUTE_COST_TOLERANCE`` was measured against.
    routing: AutorouteOptions = DEFAULT_AUTOROUTE_OPTIONS
    route_cost_tolerance: float = ROUTE_COST_TOLERANCE
    max_smaller_boards: int = MAX_SMALLER_BOARDS_TRIED


@dataclass(frozen=True, slots=True)
class BoardTrial:
    """One design built on one stock board, and what came of it."""

    suggestion: BoardSuggestion
    #: The design on this board with nothing yet placed -- or None if the board would not
    #: take it at all (a part already down that the smaller grid strands). What a caller
    #: compares, through ``placer.placement_inputs``, to know whether ``placed`` is still
    #: the answer for the document in front of it.
    document: PerfDocument | None
    placed: DesignPlacement | None
    #: Parts left off the board that some board could have taken -- a footprint the
    #: registry does not know is left off every board, and says nothing about this one.
    unplaced: tuple[str, ...]
    unrouted: int
    route_cost: float
    drc_errors: int
    #: DRC's findings on the routed board, one count per ``PLACEMENT_WARNING_RULES`` entry.
    warnings: tuple[int, ...]

    @property
    def preset(self) -> BoardPreset:
        return self.suggestion.preset

    @property
    def builds(self) -> bool:
        """Every part on, every connection made, nothing DRC calls an error."""
        return (
            self.placed is not None
            and not self.unplaced
            and self.unrouted == 0
            and self.drc_errors == 0
        )


@dataclass(frozen=True, slots=True)
class BoardVerdict:
    trial: BoardTrial
    kind: VerdictKind
    #: This board's routing cost over the reference's -- 1.0 for the reference itself, and
    #: None where there is nothing to compare (a board that would not take the design).
    cost_ratio: float | None
    #: The rules this board draws more often than the reference, for ``new-warnings``.
    new_warnings: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.kind in ("reference", "accepted")

    @property
    def preset(self) -> BoardPreset:
        return self.trial.preset


@dataclass(frozen=True, slots=True)
class BoardChoice:
    """The answer to "which board", with the trials it was reached by."""

    suggestions: tuple[BoardSuggestion, ...]
    #: The board the circuit certainly has room on (``placer.recommended_board``), which
    #: every smaller board is measured against. None when it fits no stock board at all.
    reference: BoardSuggestion | None
    #: In the order they were tried: the reference first, then smaller and smaller.
    verdicts: tuple[BoardVerdict, ...]
    recommended: BoardSuggestion | None
    #: False when the search was stopped before it would have ended by itself; the
    #: recommendation is then the smallest board tried so far.
    complete: bool

    def verdict_for(self, preset: BoardPreset) -> BoardVerdict | None:
        return next((v for v in self.verdicts if v.preset == preset), None)


def try_board(
    document: PerfDocument,
    suggestion: BoardSuggestion,
    lookup: FootprintLookup,
    options: BoardTrialOptions = BoardTrialOptions(),  # noqa: B008 -- frozen, shared safely
    should_stop: Callable[[], bool] | None = None,
    mapper: Mapper | None = None,
) -> BoardTrial | None:
    """Put ``document``'s design on ``suggestion``'s board, route it and check it.

    Exactly what the window does with that board -- ``board.applyPreset``
    (``commands.document_on_preset``), ``placer.place_design``, the autorouter -- on a copy,
    with the copper stripped first, because the question is what it costs to BUILD the
    design on this board and copper laid for another board answers nothing.

    Labels written on the board are dropped if the smaller board would not hold them: they
    are text somebody placed for the board they had, and nothing about where parts go or
    how they route depends on them. A part already on the board that the new grid strands
    is different -- that board cannot take the design, and says so as ``too-small``.

    Returns None when ``should_stop`` asked for it part way: a trial cut short is not a
    verdict on the board, and is thrown away rather than judged.
    """
    stopped = False

    def latch() -> bool:
        nonlocal stopped
        if not stopped and should_stop is not None and should_stop():
            stopped = True
        return stopped

    bare = replace(document, conductors=(), cuts=())
    on: PerfDocument | None = None
    for candidate in (bare, replace(bare, board_notes=())):
        try:
            on = document_on_preset(candidate, suggestion.preset, suggestion.board)
            break
        except CommandError:
            continue
    if on is None:
        stranded = tuple(sorted(c.ref for c in document.components))
        return BoardTrial(suggestion, None, None, stranded, 0, 0.0, 0, _no_warnings())

    placed = place_design(on, lookup, options.placement, should_stop=latch, mapper=mapper)
    if latch():
        return None
    known = {part.ref for part in on.parts if lookup(part.footprint_id) is not None}
    unplaced = tuple(ref for ref in placed.unplaced if ref in known)

    route = _route_already_planned(placed, options.routing) or plan_autoroute(
        placed.document, lookup, options.routing
    )
    findings = run_drc(route.document, lookup)
    return BoardTrial(
        suggestion=suggestion,
        document=on,
        placed=placed,
        unplaced=unplaced,
        unrouted=route.summary.links_unrouted,
        route_cost=route.summary.total_cost,
        drc_errors=sum(1 for v in findings if v.severity == "error"),
        warnings=tuple(
            sum(1 for v in findings if v.rule == rule and v.severity == "warning")
            for rule in PLACEMENT_WARNING_RULES
        ),
    )


def _route_already_planned(
    placed: DesignPlacement, routing: AutorouteOptions
) -> AutoroutePlan | None:
    """The route the placer priced this very placement with, when it is one.

    The placer routes every candidate it shortlists to choose between them, so the winner
    has already been routed -- on the same board, with the copper stripped, with the
    engine's default options -- and planning it again here was one route in eight of every
    trial, for an answer already in hand. Taken only when the document is EQUAL to the one
    that route was made on and the options are the defaults it was made with: the planner
    is pure, so that is the same answer by construction; anything less -- a part sent back
    to the design after placing, options of a caller's own -- is planned again.
    """
    routed = placed.plan.routed if placed.plan is not None else None
    if routed is None or routing != DEFAULT_AUTOROUTE_OPTIONS:
        return None
    return routed.plan if routed.document == placed.document else None


def _no_warnings() -> tuple[int, ...]:
    return tuple(0 for _ in PLACEMENT_WARNING_RULES)


def _failure(trial: BoardTrial) -> VerdictKind | None:
    """Why a board does not build at all, or None when it does."""
    if trial.placed is None or trial.unplaced:
        return "too-small"
    if trial.unrouted:
        return "unrouted"
    if trial.drc_errors:
        return "drc-errors"
    return None


def reference_verdict(trial: BoardTrial) -> BoardVerdict:
    """The roomy board's own verdict: ``reference`` when it builds, and otherwise why not
    -- in which case nothing is measured against it."""
    return BoardVerdict(trial, _failure(trial) or "reference", 1.0)


def judge(trial: BoardTrial, reference: BoardTrial, tolerance: float) -> BoardVerdict:
    """A smaller board against the reference, by the checks in the module docstring, in
    that order: the first that fails names the verdict."""
    failure = _failure(trial)
    if failure is not None:
        ratio = None if trial.placed is None or trial.unplaced else _ratio(trial, reference)
        return BoardVerdict(trial, failure, ratio)
    ratio = _ratio(trial, reference)
    new = tuple(
        rule
        for rule, mine, theirs in zip(
            PLACEMENT_WARNING_RULES, trial.warnings, reference.warnings, strict=True
        )
        if mine > theirs
    )
    if new:
        return BoardVerdict(trial, "new-warnings", ratio, new)
    # Compared as a product rather than a ratio, so a reference that costs nothing -- a
    # design with nothing to wire -- still accepts a board that costs nothing either.
    if trial.route_cost > reference.route_cost * tolerance + 1e-9:
        return BoardVerdict(trial, "dearer", ratio)
    return BoardVerdict(trial, "accepted", ratio)


def _ratio(trial: BoardTrial, reference: BoardTrial) -> float:
    if reference.route_cost <= 0:
        return 1.0 if trial.route_cost <= 0 else float("inf")
    return trial.route_cost / reference.route_cost


def _area(suggestion: BoardSuggestion) -> float:
    return suggestion.preset.width_mm * suggestion.preset.height_mm


def choose_board(
    document: PerfDocument,
    lookup: FootprintLookup,
    suggestions: Sequence[BoardSuggestion] | None = None,
    options: BoardTrialOptions = BoardTrialOptions(),  # noqa: B008 -- frozen, shared safely
    should_stop: Callable[[], bool] | None = None,
    on_trial: Callable[[BoardPreset], None] | None = None,
    mapper: Mapper | None = None,
) -> BoardChoice:
    """The smallest stock board ``document``'s design builds as well on as on a roomy one.

    ``suggestions`` are ``placer.suggest_boards``'s, worked out here when not given; the
    reference is ``placer.recommended_board`` of them. The reference is tried first -- a
    reference that does not build cleanly is not a yardstick, and nothing is measured
    against it -- then every smaller board of the family, largest first, until one is
    rejected or ``options.max_smaller_boards`` have been tried.

    Nothing is tried on a stripboard, whose boards are judged by a different planner that
    no tolerance here was measured on, nor when there is no smaller board to try; the
    reference is the answer, as it always was.

    ``on_trial`` is told each board just before it is tried, for a progress label, and
    ``mapper`` is handed to the placer for each trial (``placer.Mapper``).
    """
    if suggestions is None:
        suggestions = suggest_boards(document.board, design_entries(document), document.nets, lookup)
    reference = recommended_board(suggestions)
    everything = tuple(suggestions)
    if reference is None or is_stripboard(document.board):
        return BoardChoice(everything, reference, (), reference, True)
    smaller = sorted(
        (s for s in everything if _area(s) < _area(reference)),
        key=lambda s: (-_area(s), s.preset.name),
    )[: options.max_smaller_boards]
    if not smaller:
        return BoardChoice(everything, reference, (), reference, True)

    if on_trial is not None:
        on_trial(reference.preset)
    yardstick = try_board(document, reference, lookup, options, should_stop, mapper)
    if yardstick is None:
        return BoardChoice(everything, reference, (), reference, False)
    verdicts = [reference_verdict(yardstick)]
    recommended = reference
    complete = True
    if verdicts[0].accepted:
        for suggestion in smaller:
            if should_stop is not None and should_stop():
                complete = False
                break
            if on_trial is not None:
                on_trial(suggestion.preset)
            trial = try_board(document, suggestion, lookup, options, should_stop, mapper)
            if trial is None:
                complete = False
                break
            verdict = judge(trial, yardstick, options.route_cost_tolerance)
            verdicts.append(verdict)
            if not verdict.accepted:
                break
            recommended = suggestion
    return BoardChoice(everything, reference, tuple(verdicts), recommended, complete)
