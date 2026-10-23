"""Routing a stripboard, which is a different problem from routing a perfboard.

``autoroute.py`` answers "what copper do I add". On stripboard the copper is already
there, in whole rows, so the question splits in two and the first half is subtraction:

  **WHERE MUST THE TRACK BE BROKEN?** Two pins of different nets sitting on one strip are
  shorted by the board itself, before anybody picks up an iron. Every such pair needs a
  cut between them, and if there is no free hole between them there is no cut to make --
  which is a real dead end, reported rather than routed around, because the fix is to
  move a part and that is the user's decision.

  **WHAT IS STILL NOT JOINED?** After the cuts, a net's pins sit in some number of
  separate islands. Each island has to be linked to the next, and on stripboard that is a
  wire link over the COMPONENT side: the solder side is one sheet of parallel copper, so
  anything laid across it there shorts every strip it crosses. A link goes into a FREE
  hole of each strip -- one lead to a hole, as a breadboard jumper goes into a free hole
  of its clip -- and under a part only where no pair of free holes keeps it out.

WHY THE CUTS AND THE LINKS ARE ONE COMMAND. They are one decision. A cut removes a
connection the board was providing and a link puts back the one the circuit wanted;
committing them separately would put a state on the undo stack that nobody designed --
a board cut apart with nothing linking it, or worse, linked with nothing cut, which is a
short. ``stripboard.apply`` takes both.

WHAT THIS DOES NOT DO. It does not move parts. On stripboard placement IS most of the
design -- pins that want to share a net want to share a row -- and an autorouter that
quietly rearranged the board would be answering a question nobody asked. It reports what
it could not separate and leaves the decision where it belongs. ``placer.py`` is the tool
for that half, and it reads the same rule this module refuses by: ``cannot-separate``
below and its ``strip_conflict`` term count the same pairs, out of
``stripboard.MIN_SEPARABLE_GAP``. Two answers to "can this board be wired" would mean an
optimiser packing boards this planner then declines to finish.

Pure and deterministic, like every planner above it: the same board plans the same way.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import pairwise

from .breadboard import has_breadboard_pattern
from .command import CommandContext, CommandError
from .commands import (
    AddConductorPayload,
    ApplyStripboardPlanPayload,
    NewConductor,
    NewWireConductor,
    add_conductor,
    create_document_id_generator,
)
from .connectivity import FootprintLookup, PhysicalPinRef, extract_physical_nets
from .geometry import all_pin_holes, format_hole, hole_key, holes_under_line, manhattan
from .model import ComponentId, HoleCoord, NetId, PerfDocument, TrackCut
from .occupancy import OccupancyIndex, build_occupancy
from .stripboard import (
    cut_between,
    is_stripboard,
    joined_by_board,
    position_along,
    segment_holes,
    strip_index,
)
from .wiregauge import wire_gauge_for_current

# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlannedCut:
    at: HoleCoord
    #: The two pins the board was shorting together, named the way the guide names them.
    between: tuple[PhysicalPinRef, PhysicalPinRef]
    reason: str


@dataclass(frozen=True, slots=True)
class PlannedLink:
    net_id: NetId
    net_name: str
    from_hole: HoleCoord
    to_hole: HoleCoord
    holes: int


@dataclass(frozen=True, slots=True)
class StripProblem:
    """Something the planner could not do, with the reason and where.

    PLAN.md Sec 13 names the trap this exists to avoid: an autorouter that routes most of
    a board and leaves a handful of connections that are then impossible to finish by
    hand, without saying so. Everything unresolved comes back here.
    """

    code: str
    message: str
    holes: tuple[HoleCoord, ...] = ()


@dataclass(frozen=True, slots=True)
class StripboardPlan:
    """A proposed set of cuts and links. Nothing is committed until the caller says so."""

    document: PerfDocument
    cuts: tuple[TrackCut, ...]
    conductors: tuple[NewConductor, ...]
    planned_cuts: tuple[PlannedCut, ...]
    links: tuple[PlannedLink, ...]
    problems: tuple[StripProblem, ...]
    label: str
    #: What a re-route takes up before it lays anything (``breadroute.plan_joined_reroute``).
    remove_ids: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.cuts and not self.conductors and not self.remove_ids

    def payload(self) -> ApplyStripboardPlanPayload:
        """The one command that commits this plan, as a single undo step."""
        return ApplyStripboardPlanPayload(
            cuts=tuple(cut.at for cut in self.cuts),
            conductors=self.conductors,
            cut_ids=tuple(cut.id for cut in self.cuts),
            label=self.label,
            remove_ids=self.remove_ids,
        )


def describe_plan(plan: StripboardPlan) -> str:
    """One line, for a status bar or a confirmation dialog."""
    if plan.is_empty and not plan.problems:
        return "Nothing to do: every net is already right on this board."
    if has_breadboard_pattern(plan.document.board):
        bits = [f"{len(plan.links)} jumper(s)"]
    else:
        bits = [f"{len(plan.cuts)} cut(s)", f"{len(plan.links)} link(s)"]
    if plan.remove_ids:
        bits.insert(0, f"{len(plan.remove_ids)} old conductor(s) ripped up")
    if plan.problems:
        bits.append(f"{len(plan.problems)} problem(s)")
    return ", ".join(bits)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_stripboard(
    doc: PerfDocument,
    lookup: FootprintLookup,
    only_net_ids: tuple[NetId, ...] | None = None,
) -> StripboardPlan:
    """Work out the cuts and links this board needs, without touching it.

    Cuts first and links second, and the order is not a style: a cut changes what is
    connected to what, so planning the links against the uncut board would link islands
    that are about to be separated and miss the ones the cuts create.
    """
    if not is_stripboard(doc.board):
        return StripboardPlan(
            document=doc,
            cuts=(),
            conductors=(),
            planned_cuts=(),
            links=(),
            problems=(
                StripProblem(
                    code="not-stripboard",
                    # States the fact rather than describing a replan that did not happen:
                    # this returns an EMPTY plan, so "autoroute plans it as a perfboard"
                    # read as a report on work nothing here did.
                    message=(
                        f"This board is {doc.board.type}, which has no tracks to cut or "
                        f"link; use autoroute on it."
                    ),
                ),
            ),
            label="",
        )

    wanted = wanted_nets(doc, only_net_ids)
    pins = pins_by_hole(doc, lookup)
    problems: list[StripProblem] = []

    working, cuts, planned_cuts, cut_problems = _plan_cuts(doc, pins, wanted)
    problems.extend(cut_problems)

    conductors, links, link_problems = _plan_links(working, lookup, pins, wanted)
    problems.extend(link_problems)

    ctx = CommandContext(next_id=create_document_id_generator(working))
    preview = working
    for spec in conductors:
        try:
            preview = add_conductor.apply(preview, AddConductorPayload(conductor=spec), ctx)
        except CommandError as err:  # pragma: no cover - a planner bug, reported not raised
            problems.append(StripProblem(code=err.code, message=err.message))

    return StripboardPlan(
        document=preview,
        cuts=cuts,
        conductors=tuple(conductors),
        planned_cuts=tuple(planned_cuts),
        links=tuple(links),
        problems=tuple(problems),
        label=f"Autoroute stripboard: {len(cuts)} cut(s), {len(conductors)} link(s)",
    )


def wanted_nets(doc: PerfDocument, only_net_ids: tuple[NetId, ...] | None) -> dict[NetId, str]:
    ids = set(only_net_ids) if only_net_ids is not None else None
    return {net.id: net.name for net in doc.nets if ids is None or net.id in ids}


def pins_by_hole(doc: PerfDocument, lookup: FootprintLookup) -> dict[str, tuple[PhysicalPinRef, HoleCoord]]:
    """Every pin on the board by hole key, so a hole can name what is standing in it.

    Two pins in one hole is a document DRC objects to and this planner cannot fix, so the
    first in document order wins -- the same rule the 2D scene uses for the same reason.
    """
    out: dict[str, tuple[PhysicalPinRef, HoleCoord]] = {}
    for component in doc.components:
        footprint = lookup(component.footprint_id)
        if footprint is None:
            continue
        for pin, hole in all_pin_holes(component, footprint):
            out.setdefault(hole_key(hole), (PhysicalPinRef(component.ref, pin.number), hole))
    return out


def net_of_pin(doc: PerfDocument, wanted: dict[NetId, str]) -> dict[tuple[str, str], NetId]:
    return {
        (node.component_ref, node.pin): net.id
        for net in doc.nets
        if net.id in wanted
        for node in net.nodes
    }


def _plan_cuts(
    doc: PerfDocument,
    pins: dict[str, tuple[PhysicalPinRef, HoleCoord]],
    wanted: dict[NetId, str],
) -> tuple[PerfDocument, tuple[TrackCut, ...], list[PlannedCut], list[StripProblem]]:
    """Break every strip that is shorting two different nets together.

    Walks the pins along each strip in order and looks only at CONSECUTIVE pairs: cutting
    between neighbours is the only cut that separates anything, and a pass over every pair
    would propose the same cut several times over.

    A pin whose net nobody declared is left alone rather than treated as its own net --
    an undeclared pin is a gap in the schematic, and cutting the board because of one
    would be the tool acting on a guess.
    """
    net_of = net_of_pin(doc, wanted)
    # A drill may not go through a hole that has anything soldered into it: a pin, or any
    # hole a conductor touches. Blunt on purpose -- the question is only "may a bit go
    # here", and the answer is no for all of them.
    occupied = frozenset(pins) | frozenset(
        hole_key(hole) for conductor in doc.conductors for hole in conductor.path
    )

    by_strip: dict[int, list[tuple[int, PhysicalPinRef, HoleCoord]]] = {}
    for pin_ref, hole in pins.values():
        if (pin_ref.component_ref, pin_ref.pin) not in net_of:
            continue
        index = strip_index(doc.board, hole)
        position = position_along(doc.board, hole)
        by_strip.setdefault(index, []).append((position, pin_ref, hole))

    working = doc
    cuts: list[TrackCut] = []
    planned: list[PlannedCut] = []
    problems: list[StripProblem] = []
    next_id = create_document_id_generator(doc)

    for index in sorted(by_strip):
        row = sorted(by_strip[index], key=lambda entry: (entry[0], entry[1]))
        for (_, first_ref, first_hole), (_, second_ref, second_hole) in pairwise(row):
            net_a = net_of[(first_ref.component_ref, first_ref.pin)]
            net_b = net_of[(second_ref.component_ref, second_ref.pin)]
            if net_a == net_b:
                continue
            if not joined_by_board(working, first_hole, second_hole):
                continue  # An earlier cut already separated them.

            at = cut_between(working, first_hole, second_hole, occupied)
            if at is None:
                problems.append(
                    StripProblem(
                        code="cannot-separate",
                        message=(
                            f"{first_ref.component_ref}.{first_ref.pin} ({wanted[net_a]}) and "
                            f"{second_ref.component_ref}.{second_ref.pin} ({wanted[net_b]}) share "
                            f"the strip through {format_hole(first_hole, doc.board)} and there is no free "
                            f"hole between them to cut. Move one of the parts."
                        ),
                        holes=(first_hole, second_hole),
                    )
                )
                continue

            cut = TrackCut(id=next_id("cut"), at=at)
            cuts.append(cut)
            planned.append(
                PlannedCut(
                    at=at,
                    between=(first_ref, second_ref),
                    reason=(
                        f"{wanted[net_a]} and {wanted[net_b]} both sit on this strip; the board "
                        f"joins them until it is cut."
                    ),
                )
            )
            working = dataclasses.replace(working, cuts=(*working.cuts, cut))

    return working, tuple(cuts), planned, problems


# ---------------------------------------------------------------------------
# Where a link goes in: shared with breadroute, which jumpers a breadboard's clips
# ---------------------------------------------------------------------------
#
# One lead to a hole. A pin fills its own, so a link reaches a strip by a FREE hole of it,
# the way a breadboard jumper reaches a clip, and both planners choose those holes by the one
# search below: this module is beneath breadroute, which imports it.

#: What a link or a jumper passing under a part costs, in holes of extra length. Enough that
#: one round the part always wins when there is one -- the perfboard router's position (it
#: refuses such a jumper) softened to a preference, because laying a link or a flat jumper
#: first and the part over it is ordinary practice on stripboard and on a breadboard, and a
#: refusal could leave a strip or a clip unreachable that a person would simply link under
#: the chip. ``jumper-under-body`` still warns about it, and the guide fits it first.
UNDER_BODY_COST = 100

#: A link or a jumper: its two ends.
type Join = tuple[HoleCoord, HoleCoord]

#: The holes it runs through, ends and corners: two of them for a straight one.
type JumperRoute = tuple[HoleCoord, ...]

#: The parts standing over each row and each column of the board, as (position, part) in
#: order along it: :func:`cover_of`.
type Cover = tuple[dict[int, list[tuple[int, ComponentId]]], dict[int, list[tuple[int, ComponentId]]]]

#: How a link between two holes is laid, and what that costs: :func:`straight_router`, or
#: breadroute's along the grid.
type Router = Callable[[HoleCoord, HoleCoord], tuple[int, JumperRoute]]


def free_holes(holes: Iterable[HoleCoord], used: set[str]) -> list[HoleCoord]:
    """The holes a link end could go into: nothing in them yet. A hole under a part's body
    counts -- the link goes in first and the part over it, which is ordinary practice and
    the only way to reach a strip or a clip a trimmer or a can stands over -- but it is
    priced (:func:`straight_router`), so it is never chosen while an open hole will do."""
    return sorted({h for h in holes if hole_key(h) not in used}, key=lambda h: (h.row, h.col))


def cover_of(doc: PerfDocument, occupancy: OccupancyIndex) -> Cover:
    """Every hole a body covers, by row and by column, read once. A run along a row or a
    column is answered from these instead of walking it hole by hole: a breadboard's grid
    jumper is priced along a hundred-odd shapes for every pair of holes it might join, and
    walking them was almost all of the time a breadboard took to plan (50 s on
    atmega328-relay)."""
    by_row: dict[int, list[tuple[int, ComponentId]]] = {}
    by_col: dict[int, list[tuple[int, ComponentId]]] = {}
    for row in range(doc.board.rows):
        for col in range(doc.board.cols):
            part = occupancy.body_covers(HoleCoord(col, row))
            if part is not None:
                by_row.setdefault(row, []).append((col, part))
                by_col.setdefault(col, []).append((row, part))
    return by_row, by_col


def parts_under(path: JumperRoute, occupancy: OccupancyIndex, cover: Cover | None = None) -> int:
    """How many parts a link along ``path`` passes under: the holes under it other than its
    two ends, counted as ``jumper-under-body`` counts them -- a corner included, since the
    wire lies over it. A run along a row or a column is read off ``cover`` when it is given,
    which is the same holes: ``holes_under_line`` of such a run is every hole on it."""
    ends = {(path[0].col, path[0].row), (path[-1].col, path[-1].row)}
    crossed: set[ComponentId | None] = set()
    for p, q in pairwise(path):
        if cover is not None and p.row == q.row:
            low, high = sorted((p.col, q.col))
            crossed.update(
                part for col, part in cover[0].get(p.row, ()) if low <= col <= high and (col, p.row) not in ends
            )
        elif cover is not None and p.col == q.col:
            low, high = sorted((p.row, q.row))
            crossed.update(
                part for row, part in cover[1].get(p.col, ()) if low <= row <= high and (p.col, row) not in ends
            )
        else:
            crossed.update(
                occupancy.body_covers(h) for h in holes_under_line(p, q) if (h.col, h.row) not in ends
            )
    crossed.discard(None)
    return len(crossed)


def straight_router(occupancy: OccupancyIndex, cover: Cover) -> Router:
    """A straight link between two holes, with its cost: its length in holes, plus
    :data:`UNDER_BODY_COST` for every part it runs under and for each end that goes in
    under one. Remembered per pair, because a planner asks again for the link it chose."""
    seen: dict[tuple[str, str], tuple[int, JumperRoute]] = {}

    def route(a: HoleCoord, b: HoleCoord) -> tuple[int, JumperRoute]:
        key = (hole_key(a), hole_key(b))
        found = seen.get(key)
        if found is None:
            covered = sum(occupancy.body_covers(end) is not None for end in (a, b))
            path = (a, b)
            cost = manhattan(a, b) + UNDER_BODY_COST * parts_under(path, occupancy, cover)
            found = seen[key] = (cost + UNDER_BODY_COST * covered, path)
        return found

    return route


def cheapest_join(
    left: Iterable[HoleCoord], right: Iterable[HoleCoord], used: set[str], route: Router
) -> tuple[int, Join] | None:
    """The cheapest link between two sets of holes, ties broken by position so the plan is
    the same every time.

    Pairs are tried shortest first and the search stops once a pair's LENGTH alone reaches
    the best COST found: the length is a lower bound on the cost, so nothing later can
    win, and the answer is exactly the exhaustive one. It matters -- a breadboard's supply
    island is priced against every hole of two fifty-hole rails, and walking each jumper's
    holes for the parts it passes under was nearly all of a placement trial on a breadboard.
    """
    pairs = sorted(
        (manhattan(a, b), a.col, a.row, b.col, b.row, a, b)
        for a in free_holes(left, used)
        for b in free_holes(right, used)
        if a != b
    )
    best: tuple[tuple[int, int, int, int, int], Join] | None = None
    for length, a_col, a_row, b_col, b_row, a, b in pairs:
        if best is not None and length > best[0][0]:
            break
        key = (route(a, b)[0], a_col, a_row, b_col, b_row)
        if best is None or key < best[0]:
            best = (key, (a, b))
    return None if best is None else (best[0][0], best[1])


def take_join(join: Join, used: set[str]) -> Join:
    used.update((hole_key(join[0]), hole_key(join[1])))
    return join


def _plan_links(
    doc: PerfDocument,
    lookup: FootprintLookup,
    pins: dict[str, tuple[PhysicalPinRef, HoleCoord]],
    wanted: dict[NetId, str],
) -> tuple[list[NewConductor], list[PlannedLink], list[StripProblem]]:
    """Join up the islands each net is left in, nearest pair first, each link from a FREE
    hole of one island's strip to a free hole of the other's.

    Islands come from the CONNECTIVITY engine rather than from the strips, so a link the
    user already fitted, a solder blob between two rows and a strip all count as the one
    thing they physically are -- something that already joins these pins. The alternative,
    grouping by strip, would propose a link parallel to every wire already on the board.

    ONE LEAD TO A HOLE. A pin fills its own hole, so a link goes into another hole of the
    same strip, as a link is fitted on Veroboard: through the board and soldered to the
    copper, which connectivity counts. The ends are chosen by length, plus
    :data:`UNDER_BODY_COST` for every part the link would run under or end beneath, so a
    link goes under a part only when no pair of free holes keeps it out -- and then
    ``jumper-under-body`` says so and the guide fits it first. Linked pin to pin, as this
    used to be, 103 of the 128 links on the six finished examples and the placed blinker
    made into stripboard ran under a part (150 warnings), every end in a hole a lead already
    filled; from free holes it is 30 (34 warnings), 19 ends of 256 beside a lead, and a
    sixth less wire.

    A strip with no free hole left is linked at a pin's own hole, beside its lead, so no
    island is left unjoined for want of a hole.
    """
    island_of: dict[tuple[str, str], str] = {}
    island_holes: dict[str, list[HoleCoord]] = {}
    for island in extract_physical_nets(doc, lookup):
        island_holes[island.id] = [node.hole for node in island.nodes]
        for pin in island.pins:
            island_of[(pin.component_ref, pin.pin)] = island.id

    hole_of = {(ref.component_ref, ref.pin): hole for ref, hole in pins.values()}
    occupancy = build_occupancy(doc, lookup)
    route = straight_router(occupancy, cover_of(doc, occupancy))
    # One lead to a hole: a pin fills its own, and so does each end of a conductor.
    used: set[str] = set(pins)
    for conductor in doc.conductors:
        if conductor.path:
            used.update((hole_key(conductor.path[0]), hole_key(conductor.path[-1])))

    conductors: list[NewConductor] = []
    links: list[PlannedLink] = []
    problems: list[StripProblem] = []

    for net in doc.nets:
        if net.id not in wanted:
            continue
        islands: dict[str, None] = {}
        missing = 0
        for node in net.nodes:
            key = (node.component_ref, node.pin)
            island_id = island_of.get(key)
            if key not in hole_of or island_id is None:
                missing += 1
                continue
            islands.setdefault(island_id, None)
        if missing:
            problems.append(
                StripProblem(
                    code="pin-not-found",
                    message=(
                        f"{missing} pin(s) of {net.name} could not be found on the board: the "
                        f"part is not placed, its footprint is not in the library, or the "
                        f"netlist names a pin the footprint does not have. Nothing was linked "
                        f"to them."
                    ),
                )
            )
        if len(islands) < 2:
            continue

        # Nearest-pair merging: join the two closest islands, merge them, repeat. The
        # links a person would fit, in the order they would fit them, and short links
        # first means a later one is never made redundant by an earlier one.
        groups = [_on_its_strips(doc, island_holes[island]) for island in sorted(islands)]
        while len(groups) > 1:
            choice = _nearest(groups, used, route) or _nearest(groups, used - set(pins), route)
            if choice is None:  # pragma: no cover - every island has a pin, and a pin a hole
                break
            i, j, (a, b) = choice
            take_join((a, b), used)
            conductors.append(
                NewWireConductor(
                    path=(a, b),
                    # A link goes over the COMPONENT side. The solder side of a stripboard
                    # is one sheet of parallel copper, so a wire laid there shorts every
                    # strip it crosses -- which is the one mistake this planner must never
                    # make on the user's behalf.
                    kind="top-jumper",
                    side="top",
                    # The same gauge the perfboard router writes: see
                    # router._RouteContext.wire_gauge_awg.
                    gauge_awg=(
                        None if net.current_a is None else wire_gauge_for_current(net.current_a)
                    ),
                    net_id=net.id,
                )
            )
            links.append(
                PlannedLink(
                    net_id=net.id, net_name=net.name, from_hole=a, to_hole=b, holes=manhattan(a, b)
                )
            )
            groups[i] = groups[i] + groups[j]
            del groups[j]

    return conductors, links, problems


def _on_its_strips(doc: PerfDocument, holes: list[HoleCoord]) -> list[HoleCoord]:
    """Every hole of every strip an island is on -- where a link can reach it. A hole on no
    strip (a pin in a cut hole) is reachable only at itself."""
    reach: dict[str, HoleCoord] = {}
    for hole in holes:
        for other in segment_holes(doc, hole) or (hole,):
            reach.setdefault(hole_key(other), other)
    return list(reach.values())


def _nearest(
    groups: list[list[HoleCoord]], used: set[str], route: Router
) -> tuple[int, int, Join] | None:
    """The cheapest link between any two islands, and which two: the first pair wins a tie,
    so the plan is the same every time."""
    choice: tuple[int, int, int, Join] | None = None
    for i, left in enumerate(groups):
        for j in range(i + 1, len(groups)):
            found = cheapest_join(left, groups[j], used, route)
            if found is not None and (choice is None or found[0] < choice[0]):
                choice = (found[0], i, j, found[1])
    return None if choice is None else (choice[1], choice[2], choice[3])
