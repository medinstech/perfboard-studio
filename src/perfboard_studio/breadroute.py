"""Wiring a breadboard: jumpers into free holes, and power from the rails.

A breadboard joins five holes to a clip and nothing can be cut (``breadboard.py``), so
of stripboard's two questions only the second is left: **what is still not joined?** The
answer is a jumper wire, and three things make it a different answer from a stripboard
link:

  **A JUMPER GOES INTO A FREE HOLE.** One lead to a hole: a pin already fills its own, so a
  jumper reaches a pin by the clip it shares -- the other holes of the same five. A clip
  whose holes are all taken cannot be reached at all, and is reported (``clip-full``).

  **POWER AND GROUND COME FROM THE RAILS.** Every breadboard ever wired runs its supply
  down the long rails and drops a short jumper from each clip that needs it, so a net of
  class ground takes the - rails and a net of class power the + rails, and every island
  of it is joined to its nearer rail rather than to its neighbour. A rail somebody has
  already wired to a net stays that net's. When both rails of a pair end up carrying a
  net, one jumper bridges them at an end of the board, the way the kits show it.

  **TWO NETS IN ONE CLIP ARE NOT SEPARABLE.** Stripboard can drill between them; this
  board cannot, so the pair is reported as ``cannot-separate`` -- the same code, and the
  same answer: move a part. The placer prices exactly those pairs.

The plan is a ``striproute.StripboardPlan`` with no cuts, so the window, the MCP server
and the placer apply and price a breadboard's wiring through the code they already have
for a board that joins its own holes (``stripboard.apply`` takes a plan with no cuts on a
breadboard). A jumper is a ``top-jumper`` on the top side -- the one kind of copper
``not-on-breadboard`` accepts -- and a jumper that would run under a part is avoided where
another will do, by the same predicate ``jumper-under-body`` warns with.

Pure and deterministic, like every planner: the same board plans the same way.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from itertools import pairwise

from .breadboard import (
    RAIL_CLASS,
    Rail,
    clip_holes,
    clip_of,
    has_breadboard_pattern,
    has_hole,
    rail_of,
    rail_takes,
)
from .command import CommandContext, CommandError
from .commands import (
    AddConductorPayload,
    NewConductor,
    NewWireConductor,
    add_conductor,
    create_document_id_generator,
)
from .connectivity import FootprintLookup, PhysicalPinRef, extract_physical_nets
from .geometry import format_hole, hole_key, holes_under_line, manhattan
from .model import HoleCoord, Net, NetClass, NetId, PerfDocument
from .occupancy import OccupancyIndex, build_occupancy
from .striproute import (
    PlannedLink,
    StripboardPlan,
    StripProblem,
    net_of_pin,
    pins_by_hole,
    plan_stripboard,
    wanted_nets,
)
from .wiregauge import wire_gauge_for_current

#: Which rails a class of net takes, in the order they are handed out.
RAILS_FOR_CLASS: dict[NetClass, tuple[Rail, Rail]] = {
    "ground": ("top-", "bottom-"),
    "power": ("top+", "bottom+"),
}

#: What a jumper passing under a part costs, in holes of extra length. Enough that a
#: jumper round the part always wins when there is one -- the router's position (it
#: refuses such a jumper) softened to a preference, because on a breadboard laying a flat
#: jumper first and the part over it is ordinary practice, and a refusal could leave a
#: clip unreachable that a person would simply wire under the chip.
UNDER_BODY_COST = 100

#: A jumper: its two ends.
type Join = tuple[HoleCoord, HoleCoord]


def plan_joined_board(
    doc: PerfDocument,
    lookup: FootprintLookup,
    only_net_ids: tuple[NetId, ...] | None = None,
) -> StripboardPlan:
    """The plan for a board that joins its own holes: a stripboard's cuts and links, or a
    breadboard's jumpers. What every caller with such a board asks."""
    if has_breadboard_pattern(doc.board):
        return plan_breadboard(doc, lookup, only_net_ids)
    return plan_stripboard(doc, lookup, only_net_ids)


def plan_joined_reroute(
    doc: PerfDocument,
    lookup: FootprintLookup,
    only_net_ids: tuple[NetId, ...] | None = None,
) -> StripboardPlan:
    """Re-route on a board that joins its own holes: its own planner, not the perfboard's.

    The links and jumpers that claim these nets are taken up and planned again, in the step
    that lays the new ones (``remove_ids``). ``autoroute.plan_reroute`` laid solder traces
    and bare wire on a breadboard, which is nineteen not-on-breadboard errors and a short,
    and replaced a stripboard's links with traces along strips already joined. The cuts
    stay: a cut is the board's copper taken away, it claims no net, and the planner reads
    the board as it is cut.
    """
    targets = {net.id for net in doc.nets}
    if only_net_ids is not None:
        targets &= set(only_net_ids)
    remove_ids = tuple(
        sorted(c.id for c in doc.conductors if c.net_id is not None and c.net_id in targets)
    )
    gone = set(remove_ids)
    stripped = dataclasses.replace(
        doc, conductors=tuple(c for c in doc.conductors if c.id not in gone)
    )
    plan = plan_joined_board(stripped, lookup, only_net_ids)
    names = [net.name for net in doc.nets if net.id in targets]
    label = f"Re-route {len(names)} net(s)" if len(names) != 1 else f"Re-route {names[0]}"
    return dataclasses.replace(plan, remove_ids=remove_ids, label=label)


def plan_breadboard(
    doc: PerfDocument,
    lookup: FootprintLookup,
    only_net_ids: tuple[NetId, ...] | None = None,
) -> StripboardPlan:
    """Work out the jumpers this breadboard needs, without touching it."""
    if not has_breadboard_pattern(doc.board):
        return StripboardPlan(
            document=doc, cuts=(), conductors=(), planned_cuts=(), links=(), label="",
            problems=(
                StripProblem(
                    code="not-breadboard",
                    message=f"This board is {doc.board.type}, not a breadboard; use autoroute on it.",
                ),
            ),
        )

    wanted = wanted_nets(doc, only_net_ids)
    every_net = wanted_nets(doc, None)
    pins = pins_by_hole(doc, lookup)
    net_of = net_of_pin(doc, every_net)
    occupancy = build_occupancy(doc, lookup)
    problems = _shorts(doc, pins, net_of, every_net) + _wrong_rails(doc, pins, net_of)

    # What is already joined, by the board and by anything fitted: the islands every jumper
    # below is between. The connectivity engine, not the clips, for striproute's reason --
    # a jumper somebody already fitted counts as what it is.
    island_of: dict[tuple[str, str], str] = {}
    island_holes: dict[str, list[HoleCoord]] = {}
    for island in extract_physical_nets(doc, lookup):
        island_holes[island.id] = [node.hole for node in island.nodes]
        for pin in island.pins:
            island_of[(pin.component_ref, pin.pin)] = island.id

    # One lead to a hole: a pin fills its own, and so does each end of a conductor.
    used: set[str] = set(pins)
    for conductor in doc.conductors:
        if conductor.path:
            used.update((hole_key(conductor.path[0]), hole_key(conductor.path[-1])))

    on_board = {(ref.component_ref, ref.pin) for ref, _ in pins.values()}
    rails = _assign_rails(doc, island_of, island_holes, net_of, on_board)
    # Which rails the board already joins to one another -- a bridge somebody fitted, or the
    # one this planner fitted last time. Every island counts, a bare bridge with no pin on
    # it included, which is why this is not read off the net's own islands below.
    joined = [_reach(doc, holes)[0] for holes in island_holes.values()]
    conductors: list[NewConductor] = []
    links: list[PlannedLink] = []

    for net in doc.nets:
        if net.id not in wanted:
            continue
        islands, missing = _islands(net, on_board, island_of, island_holes)
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
        # An island standing nowhere a breadboard has a hole is in no clip, so no jumper
        # can reach it; DRC calls each such pin no-hole, and this says what it costs.
        holeless = [holes for holes in islands if not _reach(doc, holes)[1]]
        if holeless:
            islands = [holes for holes in islands if _reach(doc, holes)[1]]
            problems.append(
                StripProblem(
                    code="no-hole",
                    message=(
                        f"{len(holeless)} part(s) of {net.name} stand where the breadboard has "
                        f"no hole, so nothing was linked to them. Move them onto the holes."
                    ),
                    holes=tuple(holes[0] for holes in holeless if holes),
                )
            )
        own_rails = sorted(rail for rail, owner in rails.items() if owner == net.id)
        joins = (
            _to_rails(net, islands, own_rails, doc, used, occupancy, problems, joined)
            if own_rails
            else _nearest_first(net, islands, doc, used, occupancy, problems)
        )
        for a, b in joins:
            conductors.append(
                NewWireConductor(
                    path=(a, b),
                    kind="top-jumper",
                    side="top",
                    # The gauge every planner writes: see router._RouteContext.wire_gauge_awg.
                    gauge_awg=None if net.current_a is None else wire_gauge_for_current(net.current_a),
                    net_id=net.id,
                )
            )
            links.append(
                PlannedLink(
                    net_id=net.id, net_name=net.name, from_hole=a, to_hole=b, holes=manhattan(a, b)
                )
            )

    ctx = CommandContext(next_id=create_document_id_generator(doc))
    preview = doc
    for spec in conductors:
        try:
            preview = add_conductor.apply(preview, AddConductorPayload(conductor=spec), ctx)
        except CommandError as err:  # pragma: no cover - a planner bug, reported not raised
            problems.append(StripProblem(code=err.code, message=err.message))

    return StripboardPlan(
        document=preview,
        cuts=(),
        conductors=tuple(conductors),
        planned_cuts=(),
        links=tuple(links),
        problems=tuple(problems),
        label=f"Autoroute breadboard: {len(conductors)} jumper(s)",
    )


def _shorts(
    doc: PerfDocument,
    pins: dict[str, tuple[PhysicalPinRef, HoleCoord]],
    net_of: dict[tuple[str, str], NetId],
    names: dict[NetId, str],
) -> list[StripProblem]:
    """Every clip holding pins of two declared nets: shorted by the board, and nothing a
    wire can undo. One problem per pair of neighbouring pins along the clip, the way
    striproute reports a strip it cannot cut."""
    by_clip: dict[tuple[int, int], list[tuple[PhysicalPinRef, HoleCoord]]] = {}
    for pin_ref, hole in pins.values():
        clip = clip_of(doc.board, hole)
        if clip is not None and (pin_ref.component_ref, pin_ref.pin) in net_of:
            by_clip.setdefault(clip, []).append((pin_ref, hole))
    problems: list[StripProblem] = []
    for clip in sorted(by_clip):
        members = sorted(by_clip[clip], key=lambda m: (m[1].row, m[1].col, m[0].component_ref, m[0].pin))
        for (ref_a, hole_a), (ref_b, hole_b) in pairwise(members):
            net_a = net_of[(ref_a.component_ref, ref_a.pin)]
            net_b = net_of[(ref_b.component_ref, ref_b.pin)]
            if net_a == net_b:
                continue
            problems.append(
                StripProblem(
                    code="cannot-separate",
                    message=(
                        f"{ref_a.component_ref}.{ref_a.pin} ({names[net_a]}) and "
                        f"{ref_b.component_ref}.{ref_b.pin} ({names[net_b]}) are in one clip, "
                        f"{format_hole(hole_a, doc.board)} and {format_hole(hole_b, doc.board)}: "
                        f"the breadboard joins them and nothing can be cut. Move one of the parts."
                    ),
                    holes=(hole_a, hole_b),
                )
            )
    return problems


def _wrong_rails(
    doc: PerfDocument,
    pins: dict[str, tuple[PhysicalPinRef, HoleCoord]],
    net_of: dict[tuple[str, str], NetId],
) -> list[StripProblem]:
    """Every pin standing in a rail its net is not for (``breadboard.rail_takes``). It can
    be wired -- a rail is only a long clip -- but the board would then say "+" over a
    signal, so it is reported, and the placer counts it as a conflict."""
    class_of = {net.id: net.net_class for net in doc.nets}
    problems: list[StripProblem] = []
    for pin_ref, hole in sorted(pins.values(), key=lambda p: (p[1].row, p[1].col)):
        rail = rail_of(doc.board, hole.row) if has_hole(doc.board, hole) else None
        if rail is None:
            continue
        net = net_of.get((pin_ref.component_ref, pin_ref.pin))
        if rail_takes(rail, None if net is None else class_of[net]):
            continue
        what = "a pin no net declares" if net is None else f"a {class_of[net]} net"
        problems.append(
            StripProblem(
                code="wrong-rail",
                message=(
                    f"{pin_ref.component_ref}.{pin_ref.pin} is in the {rail[:-1]} {rail[-1]} rail "
                    f"at {format_hole(hole, doc.board)}, which is for {RAIL_CLASS[rail]}, and this "
                    f"is {what}. Move the part off the rail."
                ),
                holes=(hole,),
            )
        )
    return problems


def _rail_holes(doc: PerfDocument, rail: Rail) -> list[HoleCoord]:
    """Every hole of a rail, left to right; empty on a board without that rail."""
    for row in range(doc.board.rows):
        if rail_of(doc.board, row) == rail:
            return [h for col in range(doc.board.cols) if has_hole(doc.board, h := HoleCoord(col, row))]
    return []


def _assign_rails(
    doc: PerfDocument,
    island_of: dict[tuple[str, str], str],
    island_holes: dict[str, list[HoleCoord]],
    net_of: dict[tuple[str, str], NetId],
    on_board: set[tuple[str, str]],
) -> dict[Rail, NetId]:
    """Which net each rail carries.

    A rail already wired to a net keeps it -- handing it to another would short the two.
    The rest go by class: ground nets the - rails, power nets the + rails, in the order the
    nets are declared. One net of a class takes both rails of its pair; two take one each.
    A third ground or power net gets no rail and is wired like a signal.
    """
    board = doc.board
    nets_of_island: dict[str, set[NetId]] = {}
    for key, island in island_of.items():
        net = net_of.get(key)
        if net is not None:
            nets_of_island.setdefault(island, set()).add(net)

    owned: dict[Rail, NetId] = {}
    for island in sorted(island_holes):
        nets = nets_of_island.get(island, set())
        if len(nets) != 1:
            continue  # A rail joined to two nets is LVS's short to report, not ours to use.
        for hole in island_holes[island]:
            rail = rail_of(board, hole.row) if has_hole(board, hole) else None
            if rail is not None:
                owned.setdefault(rail, next(iter(nets)))

    present = {net_of[key] for key in on_board if key in net_of}
    for net_class, pair in RAILS_FOR_CLASS.items():
        of_class = [net.id for net in doc.nets if net.net_class == net_class and net.id in present]
        free = [rail for rail in pair if rail not in owned and _rail_holes(doc, rail)]
        if not of_class or not free:
            continue
        if len(of_class) == 1:
            for rail in free:
                owned[rail] = of_class[0]
            continue
        takers = [net for net in of_class if net not in owned.values()]
        for rail, net in zip(free, takers, strict=False):
            owned[rail] = net
    return owned


def _islands(
    net: Net,
    on_board: set[tuple[str, str]],
    island_of: dict[tuple[str, str], str],
    island_holes: dict[str, list[HoleCoord]],
) -> tuple[list[list[HoleCoord]], int]:
    """The net's islands as their holes, and how many of its pins are not on the board."""
    seen: dict[str, None] = {}
    missing = 0
    for node in net.nodes:
        key = (node.component_ref, node.pin)
        if key not in on_board or key not in island_of:
            missing += 1
            continue
        seen.setdefault(island_of[key], None)
    return [island_holes[island] for island in sorted(seen)], missing


def _reach(doc: PerfDocument, holes: Iterable[HoleCoord]) -> tuple[set[Rail], list[HoleCoord]]:
    """The rails an island already touches, and every hole of every clip it is in -- which
    is where a jumper can reach it."""
    rails: set[Rail] = set()
    reach: dict[str, HoleCoord] = {}
    for hole in holes:
        if not has_hole(doc.board, hole):
            continue
        rail = rail_of(doc.board, hole.row)
        if rail is not None:
            rails.add(rail)
        for other in clip_holes(doc.board, hole):
            reach.setdefault(hole_key(other), other)
    return rails, list(reach.values())


def _free(holes: Iterable[HoleCoord], used: set[str]) -> list[HoleCoord]:
    """The holes a jumper end could go into: nothing in them yet. A hole under a part's
    body counts -- the jumper goes in first and the part over it, which is ordinary on a
    breadboard and the only way to reach a clip a trimmer or a can stands over -- but it
    is priced (:func:`_cost`), so it is never chosen while an open hole will do."""
    return sorted({h for h in holes if hole_key(h) not in used}, key=lambda h: (h.row, h.col))


def _under_bodies(a: HoleCoord, b: HoleCoord, occupancy: OccupancyIndex) -> int:
    """How many parts a straight jumper from a to b passes under: the holes strictly
    between its ends, counted as ``jumper-under-body`` counts them."""
    ends = {hole_key(a), hole_key(b)}
    crossed = {occupancy.body_covers(h) for h in holes_under_line(a, b) if hole_key(h) not in ends}
    crossed.discard(None)
    return len(crossed)


def _cost(a: HoleCoord, b: HoleCoord, occupancy: OccupancyIndex) -> int:
    """A jumper's length in holes, plus :data:`UNDER_BODY_COST` for every part it runs
    under and for each end that goes in under one."""
    covered = sum(occupancy.body_covers(end) is not None for end in (a, b))
    return manhattan(a, b) + UNDER_BODY_COST * (_under_bodies(a, b, occupancy) + covered)


def _cheapest(
    left: Iterable[HoleCoord], right: Iterable[HoleCoord], used: set[str], occupancy: OccupancyIndex
) -> tuple[int, Join] | None:
    """The cheapest jumper between two sets of holes, ties broken by position so the plan
    is the same every time.

    Pairs are tried shortest first and the search stops once a pair's LENGTH alone reaches
    the best COST found: the length is a lower bound on the cost, so nothing later can
    win, and the answer is exactly the exhaustive one. It matters -- a supply island is
    priced against every hole of two fifty-hole rails, and walking each jumper's holes for
    the parts it passes under was nearly all of a placement trial on a breadboard.
    """
    pairs = sorted(
        (manhattan(a, b), a.col, a.row, b.col, b.row, a, b)
        for a in _free(left, used)
        for b in _free(right, used)
        if a != b
    )
    best: tuple[tuple[int, int, int, int, int], Join] | None = None
    for length, a_col, a_row, b_col, b_row, a, b in pairs:
        if best is not None and length > best[0][0]:
            break
        key = (_cost(a, b, occupancy), a_col, a_row, b_col, b_row)
        if best is None or key < best[0]:
            best = (key, (a, b))
    return None if best is None else (best[0][0], best[1])


def _unreachable(net: Net, holes: list[HoleCoord], doc: PerfDocument) -> StripProblem:
    first = sorted(holes, key=lambda h: (h.row, h.col))[:3]
    return StripProblem(
        code="clip-full",
        message=(
            f"Part of {net.name} (at {', '.join(format_hole(h, doc.board) for h in first)}) cannot "
            f"be reached: every hole of its clip already has a lead in it. Move a part so its "
            f"clip has a hole free for a jumper."
        ),
        holes=tuple(first),
    )


def _take(join: Join, used: set[str]) -> Join:
    used.update((hole_key(join[0]), hole_key(join[1])))
    return join


def _nearest_first(
    net: Net,
    islands: list[list[HoleCoord]],
    doc: PerfDocument,
    used: set[str],
    occupancy: OccupancyIndex,
    problems: list[StripProblem],
) -> list[Join]:
    """Join a signal net's islands nearest pair first, the way striproute links a strip."""
    groups = [_reach(doc, holes)[1] for holes in islands]
    joins: list[Join] = []
    while len(groups) > 1:
        choice: tuple[int, int, int, Join] | None = None
        for i, left in enumerate(groups):
            for j in range(i + 1, len(groups)):
                found = _cheapest(left, groups[j], used, occupancy)
                if found is not None and (choice is None or found[0] < choice[0]):
                    choice = (found[0], i, j, found[1])
        if choice is None:
            problems.append(_unreachable(net, groups[-1], doc))
            break
        _, i, j, join = choice
        joins.append(_take(join, used))
        groups[i] = groups[i] + groups[j]
        del groups[j]
    return joins


def _to_rails(
    net: Net,
    islands: list[list[HoleCoord]],
    own_rails: list[Rail],
    doc: PerfDocument,
    used: set[str],
    occupancy: OccupancyIndex,
    problems: list[StripProblem],
    joined: list[set[Rail]],
) -> list[Join]:
    """Drop a jumper from every island of a supply net to its nearer rail, then bridge the
    two rails of the pair if both ended up carrying it -- unless something on the board
    (``joined``) already joins them. An island touching both rails through a bridge already
    fitted reaches both, and read as needing a bridge it is standing on.
    """
    rail_holes = {rail: _rail_holes(doc, rail) for rail in own_rails}
    joins: list[Join] = []
    reached: set[Rail] = set()
    for holes in islands:
        touched, reach = _reach(doc, holes)
        if touched & set(own_rails):
            reached |= touched & set(own_rails)
            continue
        choice: tuple[int, Rail, Join] | None = None
        for rail in own_rails:
            found = _cheapest(reach, rail_holes[rail], used, occupancy)
            if found is not None and (choice is None or found[0] < choice[0]):
                choice = (found[0], rail, found[1])
        if choice is None:
            problems.append(_unreachable(net, reach, doc))
            continue
        joins.append(_take(choice[2], used))
        reached.add(choice[1])

    if len(reached) == 2 and not any(reached <= rails for rails in joined):
        top, bottom = sorted(reached, key=lambda rail: not rail.startswith("top"))
        bridge = _bridge(rail_holes[top], rail_holes[bottom], doc, used, occupancy)
        if bridge is not None:
            joins.append(_take(bridge, used))
    return joins


def _bridge(
    top: list[HoleCoord],
    bottom: list[HoleCoord],
    doc: PerfDocument,
    used: set[str],
    occupancy: OccupancyIndex,
) -> Join | None:
    """The jumper joining a rail pair: straight across, at the end of the board nearest an
    edge where nothing stands in the way."""
    below = {hole.col: hole for hole in _free(bottom, used)}
    cols = doc.board.cols
    best: tuple[tuple[int, int, int], Join] | None = None
    for a in _free(top, used):
        b = below.get(a.col)
        if b is None:
            continue
        key = (_cost(a, b, occupancy), min(a.col, cols - 1 - a.col), a.col)
        if best is None or key < best[0]:
            best = (key, (a, b))
    return None if best is None else best[1]
