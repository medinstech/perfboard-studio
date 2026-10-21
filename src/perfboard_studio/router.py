"""Connection router (PLAN.md Sec 6).

Ported from the original TypeScript engine (packages/core/src/router.ts).

WHAT THIS IS, AND DELIBERATELY IS NOT.

This is not a press-the-button-and-get-a-finished-board autorouter. Every existing
perfboard tool that promised that produced the complaint the plan quotes: "it routed
most of it and left four connections that were then impossible to finish by hand."
The target here is an interactive assistant: route ONE connection well, fast enough
that dragging a part can re-route what it touched, and be honest when nothing works.

HOW IT DECIDES.

Perfboard offers several physically different ways to join two points, so the router
evaluates each as a candidate strategy and picks the cheapest feasible one. That maps
directly onto the cost table in PLAN.md Sec 6.1:

  solder trace        cheap per step, but orthogonal only, cannot cross other copper
  wired solder trace  same path, plus a spine -- for long runs and current-carrying rails
  bare wire           cheap, straight, but cannot cross other copper
  insulated wire       crosses anything, costs preparation time
  top jumper           last resort: visible, and it occupies component space

THE PART THAT MATTERS MOST.

The solder-trace search puts R5' -- the ~0.6 mm gap to a neighbouring pad of another
net -- into the COST, not into a post-hoc warning. A router that merely avoids illegal
routes produces boards that are legal and unpleasant to solder. A router that prices
the risk produces boards that are legal AND buildable, and that is the whole argument
for this project existing (PLAN.md Sec 6.1).

Deterministic: no clock, no RNG. The same board and request always give the same route.

PORT FIDELITY NOTE. The TypeScript source scans its open list linearly for the lowest
f-score, and which of several equal-f nodes it pops decides which of several equally good
paths comes out -- so the ORDER matters to the golden fixtures, not just the costs. It
pops the earliest-pushed of the lowest f. ``_OpenList`` is a heap keyed on (f, push order),
which pops exactly that node every time; it was a scan here for years on the belief that a
heap breaks ties differently, which a heap on f ALONE does. Every golden route stayed
byte-identical when it changed, which is the only reason to believe it was safe.

...and the scan was not most of the cost either, which was worth measuring first. Autorouting a 100 x 60 board with 60 parts took 6.8 s, and a profile
put the search's own loop at under a tenth of it: the time was in ``_has_foreign_neighbour``
(R5' priced into the search, asked a million times for about two thousand distinct
questions per route) and in building ``"37,12"`` hole-key strings 15.8 million times.
Memoising the first and keying this module's own sets on ``(col, row)`` tuples took the
same board to 4.5 s -- 33% -- with every golden route still byte-identical, which is the
only reason to believe the change was safe.

KNOWN COST-MODEL LIMITATION, kept for the same reason. The spine surcharge is applied
AFTER the search, once the path length is known (see ``_solder_trace_candidate``), so it
is not part of what A* minimises. A long detour that avoids proximity risk can therefore
be chosen over a shorter risky path and only then pick up the surcharge that makes it the
more expensive of the two -- e.g. a 12-step clear detour (12, then +6 spine = 18) beating
a 2-step path with one risk hole (14). Both routes are legal and buildable and the
difference is small, so this is a quality wart rather than a defect.

Expressing it properly means running the search twice -- once bounded to a pure trace's
maximum length, once unbounded -- and comparing the finished candidates. That is a real
improvement and it would change which path some existing routes take, which is exactly
what the golden fixtures exist to detect. It is deliberately NOT done here: the
differential proof against the TypeScript engine is worth more than the last few percent
of route quality, and a caller who needs the shorter route can already pick it out of
``RouteResult.alternatives``.
"""

from __future__ import annotations

import dataclasses
import heapq
import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from .commands import (
    NewConductor,
    NewLeadBendConductor,
    NewSolderTraceConductor,
    NewWireConductor,
    wire_side,
)
from .connectivity import FootprintLookup, PhysicalNet, extract_physical_nets
from .geometry import (
    format_hole,
    hole_to_mm,
    holes_under_line,
    is_inside_board,
    manhattan,
    neighbors4,
    path_length_mm,
    same_hole,
    segments_touch,
    unusable_holes,
)
from .model import (
    Board,
    HoleCoord,
    NetId,
    PerfDocument,
    SolderBuildup,
    SpineSpec,
    is_crossing_blocked,
)
from .occupancy import OccupancyIndex, build_occupancy
from .wiregauge import wire_gauge_for_current

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouterCosts:
    """Per-strategy cost table (PLAN.md Sec 6.1).

    Money is a proxy for a person's real judgement: solder is cheapest for a short
    hop, but nobody drags it twenty pads, so past ``max_pure_solder_trace_pads`` a
    wire wins on cost -- see ``RouterOptions.max_pure_solder_trace_pads``. The R5'
    proximity risk is charged here too, not merely flagged, so the A* search below
    steers around risky ground instead of only reporting it afterwards.
    """

    #: Per hole stepped along a pure solder trace. Cheap: this is the preferred primitive.
    solder_trace_step: float = 1
    #: One-off cost of preparing and laying a wire spine along a trace.
    solder_trace_spine_fixed: float = 6
    bare_wire_fixed: float = 8
    bare_wire_per_mm: float = 0.15
    insulated_wire_fixed: float = 18
    insulated_wire_per_mm: float = 0.2
    top_jumper_fixed: float = 40
    top_jumper_per_mm: float = 0.3
    #: Charged per trace hole that has a different-net pad as an orthogonal neighbour.
    #: This is DRC rule R5' expressed as money instead of a warning, so the search
    #: steers around risky ground instead of merely reporting it afterwards.
    proximity_risk: float = 12
    #: A component's own leg, bent to a nearby hole. Effectively free (PLAN.md Sec 6.1):
    #: there is no wire to cut, strip or dress, and it is already soldered at one end.
    #: Not zero, so that a shorter bend still beats a longer one and the search does not
    #: wander.
    lead_bend_fixed: float = 0.5
    lead_bend_per_mm: float = 0.02
    #: One short insulated jumper carrying a solder trace over something it may not cross.
    #: Cheaper than ``insulated_wire_fixed`` because that prices a whole run -- measuring,
    #: cutting, stripping and dressing a wire across the board -- whereas a hop is a
    #: two-or-three-hole offcut. Pricing them the same would mean a run needing one crossing
    #: might as well be wire end to end, which is the opposite of what a builder wants.
    insulated_hop_fixed: float = 10
    #: One bend in a wire laid along the grid (``RouterOptions.wire_path`` "grid"): a corner
    #: somebody forms with pliers, and one the eye has to follow afterwards. About six
    #: millimetres of bare wire, so the search takes one bend over a long detour and a
    #: straight run over a dog-leg. Unused by a straight wire, which is every golden route.
    wire_bend: float = 1
    #: Per hole a wire laid along the grid passes over that another conductor already lies
    #: across or ends on: what crossing one costs. Kept small, because an insulated wire
    #: crossing another is what insulation is for. Unused when straight.
    wire_over_copper: float = 1
    #: Per step a wire laid along the grid runs ALONG another conductor, on top of it. Two
    #: wires stacked down one row are legal and hide each other completely from above, so
    #: this is priced well past the two bends and two holes of a detour onto a free row --
    #: measured on atmega328-relay, where two insulated wires shared three holes of row 18
    #: at the crossing price alone. Unused when straight.
    wire_along_copper: float = 3
    #: One bend in a SOLDER TRACE. Zero -- which is every golden route, and "balanced" -- is
    #: the original search, to which a run that goes one hole across and one hole down in a
    #: staircase costs exactly what an L of the same length does, so it drew staircases:
    #: 77 one-hole steps in the solder-first routing of the six examples. A trace somebody
    #: drags along a board goes straight and turns where it has to, and a staircase is a
    #: row of extra bridges to make and inspect. Above zero the searches run over (hole,
    #: heading) so a bend can be priced -- see ``_find_turning_trace_path``.
    trace_bend: float = 0


DEFAULT_ROUTER_COSTS = RouterCosts()


#: How a wire is laid between its two ends.
#:
#:   "straight"  One straight run, whatever the angle. What the original engine did and what
#:               every golden route records, so it stays the engine's default.
#:   "grid"      Square to the grid, along the rows and columns of holes, with as few bends
#:               as the board allows -- how a person actually dresses wire on perfboard. A
#:               diagonal wire is shorter and is the one thing nobody builds: it crosses
#:               everything near it at an angle, lies across pads it has no business near
#:               (a straight bare wire passed 0.2 mm from a foreign pad on arduino-io-shield)
#:               and turns a finished board into a cat's cradle. A bare wire on the grid lies
#:               over pad centres and is refused where any of them is a pin, a joint or
#:               copper; an insulated one may pass over anything, and is laid square only so
#:               the board can be read.
type WirePath = Literal["straight", "grid"]

#: Every :data:`WirePath`, for a caller that has to check a name it was handed. Spelled out
#: rather than read with ``get_args``, which answers an empty tuple for a ``type`` alias.
WIRE_PATHS: tuple[WirePath, ...] = ("straight", "grid")


#: What the router may do when a connection cannot be made without crossing something that
#: must not be crossed. This is a judgement about the builder, not about the board, so it is
#: theirs to make:
#:
#:   "hop"    Solder trace as far as it goes, and one short insulated jumper over each
#:            obstacle. The default, because it is what someone building by hand does: most
#:            of the run is solder and only the crossing costs a piece of wire.
#:   "wire"   A crossing means a single insulated wire for the whole connection, end to end.
#:            For anyone who would rather run one clean wire than solder up to a jumper.
#:   "refuse" No wire of any kind. Solder traces only, and a connection that needs more is
#:            reported unrouted rather than made with wire the user did not ask for.
type CrossingPolicy = Literal["hop", "wire", "refuse"]

#: Every :data:`CrossingPolicy`, for a caller that has to check a name it was handed --
#: spelled out for the reason :data:`WIRE_PATHS` is.
CROSSING_POLICIES: tuple[CrossingPolicy, ...] = ("hop", "wire", "refuse")


#: How the board is going to be ASSEMBLED, when the builder has decided that in advance.
#:
#: This is a commitment, not a weighting, and the difference is the whole point. A cost
#: table only makes the preferred primitive *cheaper*, so a single awkward pad can still
#: flip one connection to a wire -- on a board where most holes have a neighbour, R5'
#: proximity risk at 12 a hole outweighs an entire bare wire at 8, and the run somebody
#: asked to be solder becomes wire exactly where they were watching. Someone who has said
#: "I am building this with solder traces" is not asking for solder to be favoured; they
#: are telling the tool how the board gets built.
#:
#: So a preference RANKS BEFORE COST: every strategy in the chosen family beats every
#: strategy outside it, however the two are priced. Cost still decides within the family,
#: which is what keeps the search sensible. The other family is reached only when the
#: preferred one cannot make the connection at all -- a crossing it may not pass, a hole it
#: cannot reach -- so "wire for the rest" means the rest that is physically impossible,
#: rather than the rest that happened to score badly.
#:
#:   "solder"     Solder traces, including a run hopped over a crossing with a short
#:                jumper. Wire only where no trace can be made.
#:   "wire"       Wire, for someone assembling with wire.
#:   "lead-bend"  A component's own leg first, then solder, then wire.
type StrategyPreference = Literal["solder", "wire", "lead-bend"]

#: Which family each strategy belongs to. A hopped trace counts as SOLDER: it is a solder
#: run with a two-hole jumper where it had to cross something, and calling that "wire"
#: would mean a preference for solder rejected the very mechanism that lets solder get
#: past an obstacle -- leaving the whole connection to be a wire instead, which is more
#: wire, not less.
_STRATEGY_FAMILY: dict[RouteStrategy, StrategyPreference] = {
    "solder-trace": "solder",
    "solder-trace-wired": "solder",
    "solder-trace-hopped": "solder",
    "lead-bend": "lead-bend",
    "bare-wire": "wire",
    "insulated-wire": "wire",
    "top-jumper": "wire",
}


def _preference_rank(strategy: RouteStrategy, prefer: StrategyPreference | None) -> int:
    """0 for a strategy the builder committed to, 1 for anything else -- and for a builder
    committed to bending legs, solder before wire, 1 and 2.

    With no preference every strategy ranks 0, so the sort collapses to cost alone and the
    router behaves exactly as it always has -- which is what keeps the golden routes valid.

    "Lead-bend" always SAID "then solder, then wire", and ranked the two alike, leaving the
    order to the cost table: a winding trace with a hop in it once bends were priced came to
    more than a bare wire's 30, and a connection on the NE555 became a wire for a builder who
    had asked for solder second.
    """
    if prefer is None:
        return 0
    family = _STRATEGY_FAMILY.get(strategy)
    if family == prefer:
        return 0
    if prefer == "lead-bend":
        return 1 if family == "solder" else 2
    return 1


@dataclass(frozen=True, slots=True)
class RouterOptions:
    costs: RouterCosts = DEFAULT_ROUTER_COSTS
    #: Beyond this many pads, a pure solder trace is unreliable; a spine gets proposed.
    max_pure_solder_trace_pads: int = 6
    #: Top jumpers are ugly and block component space; off by default.
    allow_top_jumper: bool = False
    #: Whether the router may fold a component's own leg to a nearby hole. Off by
    #: default: it is the cheapest primitive there is, so turning it on changes what the
    #: router produces on the boards the golden fixtures pin, which has to be a decision
    #: somebody makes rather than a silent change.
    allow_lead_bend: bool = False
    #: How far a bent leg may reach, in holes. Past this the unsupported span fatigues and
    #: shorts against its neighbours -- the threshold DRC rule 10 reports on.
    max_lead_bend_holes: int = 4
    #: Search ceiling, so a hopeless request fails fast instead of scanning the board.
    max_expanded_nodes: int = 20000
    #: See :data:`CrossingPolicy`.
    crossing_policy: CrossingPolicy = "hop"
    #: See :data:`StrategyPreference`. ``None`` weighs every strategy purely on cost, which
    #: is what "balanced" means and what every golden route is produced with.
    prefer: StrategyPreference | None = None
    #: How many blocked holes one insulated hop may span. A wire crossing occupies about one
    #: hole and a trace two or three; past that the obstacle is a wall, not something to step
    #: over, and the search should go round it instead.
    max_hop_holes: int = 3
    #: See :data:`WirePath`. Top jumpers stay straight either way: a component-side link is
    #: a straight piece of wire between two holes by definition, and a hop is already square.
    wire_path: WirePath = "straight"


DEFAULT_ROUTER_OPTIONS = RouterOptions()


# ---------------------------------------------------------------------------
# Routing styles -- which primitive the builder actually wants
# ---------------------------------------------------------------------------

#: How this board is going to be built. Not a quality setting: a judgement about the
#: person holding the iron, in the same way ``CrossingPolicy`` is.
#:
#: The cost table encodes ONE opinion about that person, and on a populated board that
#: opinion comes out as wire almost everywhere. Measured on the NE555 fixture with the
#: default table: 4 solder traces and 11 wires. The dominant term is ``proximity_risk``
#: at 12 per hole -- R5', the 0.6 mm gap to a neighbouring pad of another net. That is
#: the right thing to charge (PLAN.md Sec 6.1 argues for exactly it) and at that weight a
#: single risky hole makes a four-step trace dearer than a wire, which on a board where
#: most holes have a neighbour means traces are priced out precisely where they are most
#: wanted.
#:
#: So the weight becomes the user's choice rather than the tool's:
#:
#:   "balanced"    The table as it is, and NO commitment (``prefer`` stays None): every
#:                 primitive weighed on its own cost. Every golden fixture is routed with
#:                 this, so it must not move. NE555: 4 traces, 10 wires.
#:   "solder"      Solder wherever solder reaches. R5' still steers the search and still
#:                 becomes a measurement in the build guide, but it no longer vetoes a
#:                 trace; wire is dear, and a long run gets a spine rather than becoming
#:                 a wire. NE555: all 14 connections are traces (11 plain, 2 spined, 1
#:                 hopped over a crossing) and not one is a wire -- the planner tries
#:                 other net orders for this style, which is what took the hops from 4.
#:   "wire"        For someone who would rather cut and dress wire than drag solder
#:                 along a row of pads. Wire is cheap and traces are not. NE555: 14 wires.
#:   "lead-bend"   Fold the component's own leg wherever it reaches, then solder, then
#:                 wire. The cheapest primitive there is, and the only one the router
#:                 never used to produce at all. NE555: 5 bends and 9 traces.
#:
#: THE COSTS ARE NOT WHAT MAKES THESE HOLD. Every style except "balanced" also sets
#: ``RouterOptions.prefer``, and that is what turns each one from a tendency into a
#: commitment -- see StrategyPreference. Pricing alone left a single awkward pad able to
#: flip a run to wire, which is precisely the complaint these styles existed to answer.
#:
#: NOT a PEP 695 ``type`` alias, and it cannot become one. This name is read at RUN TIME:
#: ``mcp/session.py`` calls ``get_args(RoutingStyle)`` both to list the styles an agent
#: may ask for and to check the one it did. ``get_args`` of a ``type`` alias returns an
#: empty tuple, so the modern spelling would leave the list empty and refuse every style
#: on the surface -- silently, since neither call raises.
RoutingStyle: TypeAlias = Literal["balanced", "solder", "wire", "lead-bend"]  # noqa: UP040


#: What a bend in a trace costs in the two styles that lay long traces -- see
#: ``RouterCosts.trace_bend``. One hole's worth: a bend is taken over a detour of two holes
#: and a staircase never beats an L of the same length.
TRACE_BEND_FOR_SOLDER_STYLES: float = 1

#: What a short insulated hop costs in those two styles, against the 10 of every other.
#:
#: Pricing bends made a long winding trace dearer than a short one with a hop in it, so on
#: its own it bought straightness with jumpers -- 46 of them became 54 across the examples,
#: for a builder who chose solder to have fewer. A hop at 16 gives most of them back.
#: MEASURED over the six examples and the NE555, solder style, against no bend price and
#: hops at 10: bends 273 -> 186, trace length 1306 -> 1335 holes, jumpers 46 -> 49, nothing
#: unrouted. At 20 the jumpers were 45 but the traces 6% longer; the user chose this middle.
HOP_FOR_SOLDER_STYLES: float = 16


def costs_for_style(style: RoutingStyle) -> RouterCosts:
    """The cost table for a routing style. ``balanced`` is the defaults, untouched."""
    if style == "solder":
        return RouterCosts(
            # Still charged, so the search prefers a clear row to a risky one and the
            # guide still turns each risky hole into an isolation measurement. Just no
            # longer enough to lose to a wire on its own.
            proximity_risk=2,
            bare_wire_fixed=30,
            insulated_wire_fixed=40,
            solder_trace_spine_fixed=4,
            trace_bend=TRACE_BEND_FOR_SOLDER_STYLES,
            insulated_hop_fixed=HOP_FOR_SOLDER_STYLES,
        )
    if style == "wire":
        return RouterCosts(
            solder_trace_step=4,
            bare_wire_fixed=3,
            insulated_wire_fixed=6,
            solder_trace_spine_fixed=12,
        )
    if style == "lead-bend":
        return RouterCosts(
            proximity_risk=2,
            bare_wire_fixed=30,
            insulated_wire_fixed=40,
            trace_bend=TRACE_BEND_FOR_SOLDER_STYLES,
            insulated_hop_fixed=HOP_FOR_SOLDER_STYLES,
        )
    return DEFAULT_ROUTER_COSTS


def options_for_style(
    style: RoutingStyle, base: RouterOptions = DEFAULT_ROUTER_OPTIONS
) -> RouterOptions:
    """``base`` with the style's costs and the flags that style implies.

    Kept as one function so a caller cannot pick up the cheap-solder costs and forget the
    longer pure-trace limit that makes them usable, which would produce a board full of
    spines nobody asked for.
    """
    costs = costs_for_style(style)
    if style == "solder":
        # Solder-first means a long run stays a trace instead of turning into a wire at
        # six pads. It gets a spine, which is what a long rail wants anyway (Sec 6.2).
        #
        # `prefer` is what makes the menu item mean what it says. Without it this was
        # "solder trace where it happens to be cheapest", and the costs below only tilted
        # the odds -- so a single pad next to another net could still turn the run somebody
        # asked to be solder into a wire. With it, a trace loses only to being impossible.
        return dataclasses.replace(
            base, costs=costs, max_pure_solder_trace_pads=20, prefer="solder"
        )
    if style == "lead-bend":
        return dataclasses.replace(
            base,
            costs=costs,
            max_pure_solder_trace_pads=20,
            allow_lead_bend=True,
            prefer="lead-bend",
        )
    if style == "wire":
        return dataclasses.replace(base, costs=costs, prefer="wire")
    # "balanced" alone leaves `prefer` unset, and that IS what balanced means: no
    # commitment has been made, so every primitive is weighed on its own cost. It is also
    # what every golden route is produced with, so this branch must stay a no-op.
    return dataclasses.replace(base, costs=costs)

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

type RouteStrategy = Literal[
    "solder-trace",
    "solder-trace-wired",
    "lead-bend",
    "bare-wire",
    "insulated-wire",
    "top-jumper",
    #: Solder trace with one or more short insulated jumpers where it has to cross something.
    #: Several conductors in one candidate -- which RouteCandidate.conductors has always been
    #: a tuple for.
    "solder-trace-hopped",
]


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    strategy: RouteStrategy
    conductors: tuple[NewConductor, ...]
    cost: float
    #: Why this came out the way it did. Surfaced in the UI and reused by the guide.
    explanation: str
    #: Trace holes that sit next to a different net -- these become measurement steps.
    risk_holes: tuple[HoleCoord, ...]


@dataclass(frozen=True, slots=True)
class RouteResult:
    ok: bool
    best: RouteCandidate | None = None
    #: Every feasible strategy, cheapest first. Lets the UI offer "use a wire instead".
    alternatives: tuple[RouteCandidate, ...] = ()
    #: Populated only when nothing was feasible. Never fails silently.
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RouteRequest:
    #: Trailing underscore: ``from`` is a Python keyword.
    from_: HoleCoord
    to: HoleCoord
    #: Net being routed. Holes already on this net are free to pass through.
    net_id: NetId | None = None
    buildup: SolderBuildup | None = None
    #: Holes the SCHEMATIC intends to be this same net, whether or not the board joins
    #: them yet -- normally every pin hole of the net (``ratsnest.NetRatsnest.pin_holes``).
    #:
    #: Without this, the router can only see PHYSICAL nets, so every unrouted pin of the
    #: very net being routed looks like foreign copper: passing beside one is charged R5'
    #: proximity risk and passing through one is forbidden outright. Both are wrong, and
    #: together they rule out the standard perfboard technique -- run a rail along the row
    #: and let it pick up each pin on the way (PLAN.md Sec 6.2). Supplying these holes
    #: says "this ground is mine", which makes the rail both legal and cheap.
    #:
    #: Empty by default, so a caller that does not supply it gets exactly the
    #: point-to-point behaviour the golden fixtures pin down.
    net_holes: tuple[HoleCoord, ...] = ()
    #: ``(component_id, pin_number)`` of the pin at ``from_``, when there is one. Only the
    #: caller knows it, and only a lead bend needs it: it is that component's leg being
    #: folded, so the conductor has to name whose. None means no lead bend is offered.
    from_pin: tuple[str, str] | None = None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def route_connection(
    doc: PerfDocument,
    lookup: FootprintLookup,
    request: RouteRequest,
    options: RouterOptions = DEFAULT_ROUTER_OPTIONS,
) -> RouteResult:
    from_ = request.from_
    to = request.to

    if not is_inside_board(from_, doc.board) or not is_inside_board(to, doc.board):
        return RouteResult(ok=False, alternatives=(), reason="Endpoint is outside the board.")
    dead = _dead_hole_keys(doc)
    for endpoint in (from_, to):
        # Refused here rather than routed around, because there is nothing to route TO: a
        # finger has no bore and a bore has taken the pad, so no conductor of any kind can
        # be soldered at that end. The answer is to move the part, which is placement.
        if _key(endpoint) in dead:
            return RouteResult(
                ok=False,
                alternatives=(),
                reason=(
                    f"{format_hole(endpoint, doc.board)} has no pad to solder to — a mounting bore or "
                    f"an edge-connector finger is there. Move the part."
                ),
            )
    if same_hole(from_, to):
        return RouteResult(ok=False, alternatives=(), reason="Start and end are the same hole.")

    occupancy = build_occupancy(doc, lookup)
    net_at = _build_net_index(doc, lookup)
    blocked_segments = _blocked_segments(doc)
    ctx = _RouteContext(
        doc=doc,
        occupancy=occupancy,
        net_at=net_at,
        opts=options,
        own_net_id=request.net_id,
        net_holes=frozenset(_key(hole) for hole in request.net_holes),
        declared_own_nets=frozenset(
            net_id for net_id in (net_at(hole) for hole in request.net_holes) if net_id is not None
        ),
        blocked_segments=blocked_segments,
        swept_blocked_holes=_trace_blocked_holes(doc),
        wire_joint_holes=_wire_joint_holes(doc),
        unusable_holes=dead,
        opts_from_pin=request.from_pin,
        wire_gauge_awg=_declared_wire_gauge(doc, request.net_id),
        segment_cells=(
            _segment_cells(blocked_segments) if options.wire_path == "grid" else {}
        ),
        covered_holes=_covered_holes(doc) if options.wire_path == "grid" else frozenset(),
        covered_steps=_covered_steps(doc) if options.wire_path == "grid" else frozenset(),
    )

    candidates: list[RouteCandidate] = []
    buildup: SolderBuildup = request.buildup if request.buildup is not None else "normal"
    if options.allow_lead_bend:
        bend = _lead_bend_candidate(ctx, from_, to)
        if bend is not None:
            candidates.append(bend)
    trace = _solder_trace_candidate(ctx, from_, to, buildup)
    if trace is not None:
        candidates.append(trace)

    # What may be used when solder alone cannot get there is the BUILDER's decision, so it is
    # read from the options rather than assumed -- see CrossingPolicy.
    policy = options.crossing_policy
    if policy == "hop":
        hopped = _hopping_trace_candidate(ctx, from_, to, buildup)
        if hopped is not None:
            candidates.append(hopped)
    if policy != "refuse":
        wire = _grid_wire_candidate if options.wire_path == "grid" else _straight_wire_candidate
        bare = wire(ctx, from_, to, "bare-wire")
        if bare is not None:
            candidates.append(bare)
        insulated = wire(ctx, from_, to, "insulated-wire")
        if insulated is not None:
            candidates.append(insulated)
        if options.allow_top_jumper:
            jumper = _straight_wire_candidate(ctx, from_, to, "top-jumper")
            if jumper is not None:
                candidates.append(jumper)

    # PREFERENCE RANKS BEFORE COST. With no preference this is the cost sort it has always
    # been (every rank is 0); with one, the family the builder committed to wins outright
    # and cost only decides within it. See StrategyPreference for why a cost table alone
    # cannot express "I am assembling this board with solder traces".
    candidates.sort(key=lambda c: (_preference_rank(c.strategy, options.prefer), c.cost, c.strategy))
    if not candidates:
        refused = (
            " No wire is allowed by the current crossing policy, so only a solder trace was "
            "tried."
            if policy == "refuse"
            else " Every strategy was blocked — try moving a part, or allow a top jumper."
        )
        return RouteResult(
            ok=False,
            alternatives=(),
            reason=f"No route found from {format_hole(from_, doc.board)} to {format_hole(to, doc.board)}.{refused}",
        )
    best = candidates[0]
    return RouteResult(ok=True, best=best, alternatives=tuple(candidates))


def _declared_wire_gauge(doc: PerfDocument, net_id: NetId | None) -> int | None:
    """The gauge to write on this net's wires, or None if the net declares no current.

    Only a DECLARED current chooses a gauge. A net that says nothing gets None, not AWG 24:
    the file then records exactly what it always recorded, and the build guide still prints
    AWG 24 for it, from the same function it would have used anyway.
    """
    if net_id is None:
        return None
    for net in doc.nets:
        if net.id == net_id:
            return None if net.current_a is None else wire_gauge_for_current(net.current_a)
    return None


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RouteContext:
    doc: PerfDocument
    occupancy: OccupancyIndex
    #: Physical net id occupying a hole's solder side, if any.
    net_at: Callable[[HoleCoord], str | None]
    opts: RouterOptions
    own_net_id: NetId | None
    #: Hole keys of ``RouteRequest.net_holes``. Empty for a plain point-to-point request.
    net_holes: frozenset[tuple[int, int]] = frozenset()
    #: Segments of existing conductors that may not be crossed, on the solder side.
    #: Checked geometrically, because occupancy is per HOLE and two runs cross between holes
    #: (see geometry.segments_touch) -- which is how the router used to produce boards with
    #: bare wires lying across each other that DRC then reported as clean.
    blocked_segments: tuple[tuple[HoleCoord, HoleCoord], ...] = ()
    #: Hole keys those segments sweep across, including the ones a wire merely passes over.
    #: Precomputed so the trace search can reject them in constant time.
    swept_blocked_holes: frozenset[tuple[int, int]] = frozenset()
    #: Holes where an insulated wire or a top jumper is soldered down. See
    #: :func:`_wire_joint_holes` for why neither of the two sets above contains them.
    wire_joint_holes: frozenset[tuple[int, int]] = frozenset()
    #: Holes nothing can be soldered into at all -- a mounting bore has taken the pad, or
    #: an edge-connector finger is solid copper with no bore. See geometry.unusable_holes,
    #: which is the same set drc.py reports a run on as an error.
    unusable_holes: frozenset[tuple[int, int]] = frozenset()
    #: Physical net ids those declared holes already sit in -- precomputed here rather
    #: than rediscovered per neighbour, since the set is fixed for the whole search.
    declared_own_nets: frozenset[str] = frozenset()
    #: See ``RouteRequest.from_pin``.
    opts_from_pin: tuple[str, str] | None = None
    #: The gauge every wire laid for this net is written with: the one the build guide
    #: would cut for the current the net declares (``wiregauge.wire_gauge_for_current``),
    #: stored so the document says what was planned and DRC's ``current-capacity`` rule can
    #: notice when the net later outgrows it. None when the net declares no current, which
    #: leaves every such wire exactly as the golden routes record it.
    wire_gauge_awg: int | None = None
    #: The nets that count as "ours" for a given pair of endpoints, worked out once.
    #:
    #: MEASURED, not guessed at. Routing a 100 x 60 board with 60 parts spent 9 of its 19
    #: seconds inside ``_has_foreign_neighbour``, which was rebuilding this set -- two
    #: net lookups and a set construction -- on each of a million calls, for a value that
    #: cannot change during a search. The cache is a plain dict on a frozen dataclass,
    #: which is legal and is the point: the context is immutable, the memo is not part of
    #: what it means.
    endpoint_own_nets: dict[tuple[int, int, int, int], frozenset[str]] = field(
        default_factory=dict
    )
    #: Whether a hole is risky, for a given pair of endpoints. Same reasoning and the same
    #: measurement: for a fixed search the answer depends only on the hole, the net index
    #: and the endpoints, none of which move -- and A* asks about the same hole once per
    #: neighbour that leads to it. The million calls above were about 2,000 distinct
    #: questions per search, asked over and over.
    risky_holes: dict[tuple[int, int, int, int, int, int], bool] = field(default_factory=dict)
    #: Whether a solder trace may pass through a hole (``_is_traversable_by_trace``), by
    #: hole. Fixed for the life of the context like the two above, and asked by every
    #: search this context runs -- the plain trace, the hopping one -- once per neighbour
    #: that leads to the hole: 880,000 questions in one auto-place of atmega328-relay.
    traversable: dict[tuple[int, int], bool] = field(default_factory=dict)
    #: For a wire laid along the grid: which of ``blocked_segments`` have a bounding box
    #: covering each hole, so a step between two neighbours is tested against the few
    #: segments near it rather than every one on the board. Empty for straight wires.
    segment_cells: dict[tuple[int, int], tuple[int, ...]] = field(default_factory=dict)
    #: For a wire laid along the grid: every hole some solder-side conductor already lies
    #: across or ends on, whatever it is -- see ``RouterCosts.wire_over_copper``.
    covered_holes: frozenset[tuple[int, int]] = frozenset()
    #: ...and every step between two neighbouring holes that one of them already runs along,
    #: smaller hole first -- see ``RouterCosts.wire_along_copper``.
    covered_steps: frozenset[tuple[tuple[int, int], tuple[int, int]]] = frozenset()
    #: Whether a step between two neighbouring holes lies across blocked copper, asked once
    #: per step and remembered -- the search asks about the same step from several states.
    blocked_edges: dict[tuple[tuple[int, int], tuple[int, int]], bool] = field(
        default_factory=dict
    )


def _dead_hole_keys(doc: PerfDocument) -> frozenset[tuple[int, int]]:
    """``geometry.unusable_holes`` in this module's own (col, row) key.

    Translated once per route rather than per hole, for the reason :func:`_key` exists and
    which ``test_this_module_keys_its_own_sets_on_coordinates_not_strings`` pins: the
    trace search asks about a hole millions of times on a large board, and ``hole_key``'s
    string is the encoding for things that cross a module boundary, not for a hot set.
    """
    return frozenset(
        (int(col), int(row))
        for col, _, row in (key.partition(",") for key in unusable_holes(doc))
    )


def _key(hole: HoleCoord) -> tuple[int, int]:
    """This module's hole key, and deliberately NOT ``geometry.hole_key``.

    MEASURED. The searches below key their closed set, their g-scores and three
    membership sets by hole, and on a 100 x 60 board that was 15.8 million calls to
    ``hole_key`` -- 2.1 seconds of building ``"37,12"`` strings, more than the A* search
    itself spent. A tuple of two ints hashes to the same effect with none of the
    formatting, and nothing here ever needs the key to be readable: these sets are
    internal to one route and never cross a module boundary, which is exactly the
    condition under which the shared string encoding stops earning its keep.

    ``geometry.hole_key`` stays the one encoding for everything that DOES cross one --
    occupancy, connectivity, DRC -- and those have golden output that must not move.
    """
    return (hole.col, hole.row)


def _blocked_segments(doc: PerfDocument) -> tuple[tuple[HoleCoord, HoleCoord], ...]:
    """Every solder-side run of existing conductor that a new one may not cross."""
    segments: list[tuple[HoleCoord, HoleCoord]] = []
    for conductor in doc.conductors:
        if conductor.side != "bottom" or not is_crossing_blocked(conductor):
            continue
        for index in range(len(conductor.path) - 1):
            segments.append((conductor.path[index], conductor.path[index + 1]))
    return tuple(segments)


def _trace_blocked_holes(doc: PerfDocument) -> frozenset[tuple[int, int]]:
    """Holes a new solder trace may not use because existing copper lies across them.

    The holes a conductor's `path` LISTS are already blocked by the occupancy index; these are
    the ones it only passes over, which for a wire is everything between its two ends. Kept
    here rather than folded into occupancy because that index's golden output is part of the
    differential proof against the TypeScript engine, and widening it moves three suites at
    once -- see the note in occupancy.build_occupancy.
    """
    keys: set[tuple[int, int]] = set()
    for conductor in doc.conductors:
        if conductor.side != "bottom" or not is_crossing_blocked(conductor):
            continue
        for index in range(len(conductor.path) - 1):
            for hole in holes_under_line(conductor.path[index], conductor.path[index + 1]):
                keys.add(_key(hole))
    return frozenset(keys)


def _wire_joint_holes(doc: PerfDocument) -> frozenset[tuple[int, int]]:
    """Holes where an insulated wire or a top jumper is soldered to its pad.

    The insulation stops at the two ends: each is a bare solder joint on the solder side,
    exactly like a pin. But neither kind is ``is_crossing_blocked``, so occupancy does not
    block those holes, and a joint that is not also a pin was blocked by nothing at all.
    Two insulated hops meeting on an empty pad (``_emit_trace_run`` lays no trace for a
    one-hole run) left that pad free, and the next net's trace ran straight through it: a
    short that LVS reported and DRC did not. The same hole under a bare wire or a bent lead
    is the same short.

    Every golden route already avoids these holes, which is why blocking them moves none.
    """
    keys: set[tuple[int, int]] = set()
    for conductor in doc.conductors:
        if is_crossing_blocked(conductor) or len(conductor.path) < 2:
            continue
        keys.add(_key(conductor.path[0]))
        keys.add(_key(conductor.path[-1]))
    return frozenset(keys)


def _crosses_existing(ctx: _RouteContext, a: HoleCoord, b: HoleCoord) -> bool:
    """Would a straight run from ``a`` to ``b`` lie across existing uncrossable copper?"""
    return any(
        segments_touch(a, b, start, end) for start, end in ctx.blocked_segments
    )


def _build_net_index(doc: PerfDocument, lookup: FootprintLookup) -> Callable[[HoleCoord], str | None]:
    nets: list[PhysicalNet] = extract_physical_nets(doc, lookup)
    by_hole: dict[tuple[int, int], str] = {}
    for net in nets:
        for node in net.nodes:
            by_hole[_key(node.hole)] = net.id

    def net_at(hole: HoleCoord) -> str | None:
        return by_hole.get(_key(hole))

    return net_at


# ---------------------------------------------------------------------------
# Strategy 1: solder trace, via A* over the 4-neighbour grid
# ---------------------------------------------------------------------------


def _solder_trace_candidate(
    ctx: _RouteContext, from_: HoleCoord, to: HoleCoord, buildup: SolderBuildup
) -> RouteCandidate | None:
    path = _find_solder_trace_path(ctx, from_, to)
    if path is None:
        return None

    costs = ctx.opts.costs
    max_pure_solder_trace_pads = ctx.opts.max_pure_solder_trace_pads
    risk_holes = tuple(hole for hole in path if _has_foreign_neighbour(ctx, hole, from_, to))
    step_cost = (len(path) - 1) * costs.solder_trace_step
    # The bends the search priced, priced again here, or the candidates below are compared
    # on a different bill from the one that chose their paths: a trace that went round the
    # long way to stay straight would lose to a hop that the search itself would not take.
    # Nothing at all when bends are free, which keeps every golden cost to the last bit.
    risk_cost = len(risk_holes) * costs.proximity_risk + _bends_of(path) * costs.trace_bend

    needs_spine = len(path) > max_pure_solder_trace_pads
    kind: Literal["solder-trace", "solder-trace-wired"] = (
        "solder-trace-wired" if needs_spine else "solder-trace"
    )
    spine_cost = costs.solder_trace_spine_fixed if needs_spine else 0.0

    conductor: NewConductor = NewSolderTraceConductor(
        path=tuple(path),
        buildup=buildup,
        spine=SpineSpec(material="tinned-copper", gauge=0.6) if needs_spine else None,
        net_id=ctx.own_net_id,
        layer_z=0,
        kind=kind,
        side="bottom",
    )

    parts: list[str] = [
        f"{len(path)} pads from {format_hole(from_, ctx.doc.board)} to {format_hole(to, ctx.doc.board)}"
    ]
    if needs_spine:
        parts.append(
            f"longer than {max_pure_solder_trace_pads} pads, so a tinned-copper spine is "
            "proposed — it drops the resistance by roughly an order of magnitude and makes "
            "the joint repeatable"
        )
    if risk_holes:
        holes_text = ", ".join(format_hole(hole, ctx.doc.board) for hole in risk_holes)
        parts.append(
            f"{len(risk_holes)} pad(s) sit next to a different net ({holes_text}) — check "
            "isolation there after soldering"
        )

    return RouteCandidate(
        strategy=kind,
        conductors=(conductor,),
        cost=step_cost + risk_cost + spine_cost,
        explanation=f"Solder trace: {'; '.join(parts)}.",
        risk_holes=risk_holes,
    )


# ---------------------------------------------------------------------------
# Strategy 1b: solder trace that hops what it may not cross
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Step:
    """One step of a hopping path: where it lands, and whether it got there over an obstacle."""

    hole: HoleCoord
    hopped: bool


def _hopping_trace_candidate(
    ctx: _RouteContext, from_: HoleCoord, to: HoleCoord, buildup: SolderBuildup
) -> RouteCandidate | None:
    """Solder trace most of the way, with a short insulated jumper over each blockage.

    This is how a perfboard actually gets built when two connections have to cross. You do not
    run wire the whole way and you cannot run solder through another net's copper; you solder
    up to the obstacle, bridge it with a scrap of insulated wire, and carry on soldering. The
    result is several conductors for one connection, which ``RouteCandidate.conductors`` has
    always been a tuple to allow.

    Only offered under ``CrossingPolicy`` "hop". Under "wire" the whole run becomes one
    insulated wire instead, and under "refuse" neither is offered and the connection is
    reported unrouted -- the user's call, not the router's.
    """
    steps = _find_hopping_path(ctx, from_, to)
    if steps is None:
        return None
    if not any(step.hopped for step in steps):
        return None  # No obstacle: the plain solder-trace candidate already covers this.

    costs = ctx.opts.costs
    conductors: list[NewConductor] = []
    risk_holes: list[HoleCoord] = []
    cost = 0.0
    hops = 0

    run: list[HoleCoord] = [steps[0].hole]
    for step in steps[1:]:
        if not step.hopped:
            run.append(step.hole)
            continue
        # A hop closes the trace run before it, then jumps.
        cost += _emit_trace_run(ctx, run, buildup, conductors, risk_holes, from_, to)
        hop_from, hop_to = run[-1], step.hole
        conductors.append(
            NewWireConductor(
                path=(hop_from, hop_to),
                kind="insulated-wire",
                side="bottom",
                gauge_awg=ctx.wire_gauge_awg,
                net_id=ctx.own_net_id,
                # Above the copper it steps over, so the 3D view stacks it correctly.
                layer_z=1,
            )
        )
        cost += costs.insulated_hop_fixed + path_length_mm((hop_from, hop_to), ctx.doc.board) * (
            costs.insulated_wire_per_mm
        )
        hops += 1
        run = [step.hole]
    cost += _emit_trace_run(ctx, run, buildup, conductors, risk_holes, from_, to)
    # As for the plain trace: the bends the search priced -- see _solder_trace_candidate.
    cost += _bends_of([step.hole for step in steps]) * costs.trace_bend

    if not conductors:
        return None

    trace_count = sum(1 for c in conductors if c.kind in ("solder-trace", "solder-trace-wired"))
    parts = [
        f"solder trace from {format_hole(from_, ctx.doc.board)} to {format_hole(to, ctx.doc.board)} in {trace_count} run(s), "
        f"with {hops} insulated hop(s) over conductors it may not cross"
    ]
    if risk_holes:
        holes_text = ", ".join(format_hole(hole, ctx.doc.board) for hole in risk_holes)
        parts.append(
            f"{len(risk_holes)} pad(s) sit next to a different net ({holes_text}) — check "
            "isolation there after soldering"
        )
    return RouteCandidate(
        strategy="solder-trace-hopped",
        conductors=tuple(conductors),
        cost=cost,
        explanation=f"Hopped solder trace: {'; '.join(parts)}.",
        risk_holes=tuple(risk_holes),
    )


def _emit_trace_run(
    ctx: _RouteContext,
    run: list[HoleCoord],
    buildup: SolderBuildup,
    conductors: list[NewConductor],
    risk_holes: list[HoleCoord],
    from_: HoleCoord,
    to: HoleCoord,
) -> float:
    """Append one solder-trace conductor for ``run`` and return its cost.

    A run of a single hole is not a conductor -- it is the landing pad of one hop and the
    take-off of the next, which happens when two obstacles sit two holes apart. The pad is
    still joined, by the two wires that meet on it.
    """
    if len(run) < 2:
        return 0.0
    costs = ctx.opts.costs
    risky = [hole for hole in run if _has_foreign_neighbour(ctx, hole, from_, to)]
    risk_holes.extend(risky)
    needs_spine = len(run) > ctx.opts.max_pure_solder_trace_pads
    conductors.append(
        NewSolderTraceConductor(
            path=tuple(run),
            buildup=buildup,
            spine=SpineSpec(material="tinned-copper", gauge=0.6) if needs_spine else None,
            net_id=ctx.own_net_id,
            layer_z=0,
            kind="solder-trace-wired" if needs_spine else "solder-trace",
            side="bottom",
        )
    )
    return (
        (len(run) - 1) * costs.solder_trace_step
        + len(risky) * costs.proximity_risk
        + (costs.solder_trace_spine_fixed if needs_spine else 0.0)
    )


def _find_hopping_path(
    ctx: _RouteContext, from_: HoleCoord, to: HoleCoord
) -> list[_Step] | None:
    """A* over holes where, as well as stepping to a free neighbour, the search may JUMP over
    up to ``max_hop_holes`` blocked ones in a straight line and land on a free hole.

    Separate from ``_find_solder_trace_path`` rather than a flag on it, because that function
    reproduces the TypeScript engine's search exactly and forty-five golden routes depend on
    it doing so. A hop is a different move with a different cost, and bolting it on would put
    the differential proof at risk for no gain.
    """
    costs = ctx.opts.costs
    if costs.trace_bend > 0:
        turning = _find_turning_trace_path(ctx, from_, to, hops=True)
        if turning is not None:
            return turning
    start_key = _key(from_)
    goal_key = _key(to)

    g_score: dict[tuple[int, int], float] = {start_key: 0.0}
    came_from: dict[tuple[int, int], tuple[HoleCoord, bool]] = {}
    open_list = _OpenList(from_, manhattan(from_, to) * costs.solder_trace_step)
    closed: set[tuple[int, int]] = set()
    expanded = 0

    while open_list:
        current = open_list.pop()
        current_key = _key(current)
        if current_key == goal_key:
            return _reconstruct_steps(came_from, current, from_)
        if current_key in closed:
            continue
        closed.add(current_key)

        expanded += 1
        if expanded > ctx.opts.max_expanded_nodes:
            return None

        g = g_score.get(current_key, math.inf)
        for move_to, hopped, step_cost in _moves_from(ctx, current, from_, to):
            next_key = _key(move_to)
            if next_key in closed:
                continue
            tentative = g + step_cost
            if tentative >= g_score.get(next_key, math.inf):
                continue
            g_score[next_key] = tentative
            came_from[next_key] = (current, hopped)
            open_list.push(move_to, tentative + manhattan(move_to, to) * costs.solder_trace_step)
    return None


def _bends_of(holes: list[HoleCoord]) -> int:
    """How many times a run of holes changes direction -- a hop counting as one straight
    move along its own line."""
    bends = 0
    previous: tuple[int, int] | None = None
    for a, b in itertools.pairwise(holes):
        heading = ((b.col > a.col) - (b.col < a.col), (b.row > a.row) - (b.row < a.row))
        if previous is not None and heading != previous:
            bends += 1
        previous = heading
    return bends


#: A trace's state in the turning search: (col, row, d_col, d_row), the direction it
#: arrived in -- (0, 0) at the start, where no bend has been made yet.
_Heading = tuple[int, int, int, int]


def _find_turning_trace_path(
    ctx: _RouteContext, from_: HoleCoord, to: HoleCoord, *, hops: bool
) -> list[_Step] | None:
    """The trace searches with bends priced (``RouterCosts.trace_bend``): A* over (hole,
    heading), with exactly the moves and costs of ``_find_solder_trace_path`` -- or, with
    ``hops``, of ``_find_hopping_path`` -- plus the bend cost wherever the heading changes.

    Only reached when bends cost something, which no golden route does, so those searches
    keep reproducing the original byte for byte; this one only has to be deterministic,
    which a heap on (f, push order) is. Given four times the node ceiling, because a state
    per heading is up to four per hole; a caller whose search this cannot finish falls back
    to its own, so pricing bends never costs a connection.
    """
    costs = ctx.opts.costs
    bend = costs.trace_bend
    step_cost = costs.solder_trace_step
    goal = _key(to)
    start: _Heading = (from_.col, from_.row, 0, 0)
    g_score: dict[_Heading, float] = {start: 0.0}
    came_from: dict[_Heading, tuple[_Heading, bool]] = {}
    heap: list[tuple[float, int, _Heading]] = [(manhattan(from_, to) * step_cost, 0, start)]
    pushed = 1
    closed: set[_Heading] = set()
    expanded = 0
    ceiling = ctx.opts.max_expanded_nodes * 4

    while heap:
        _f, _order, state = heapq.heappop(heap)
        col, row, heading_col, heading_row = state
        if (col, row) == goal:
            steps: list[_Step] = []
            cursor = state
            while cursor != start:
                previous, hopped = came_from[cursor]
                steps.append(_Step(hole=HoleCoord(col=cursor[0], row=cursor[1]), hopped=hopped))
                cursor = previous
            steps.append(_Step(hole=from_, hopped=False))
            steps.reverse()
            return steps
        if state in closed:
            continue
        closed.add(state)
        expanded += 1
        if expanded > ceiling:
            return None
        g = g_score[state]
        for landing, hopped, cost in _moves_from(ctx, HoleCoord(col=col, row=row), from_, to):
            if hopped and not hops:
                continue
            d_col = (landing.col > col) - (landing.col < col)
            d_row = (landing.row > row) - (landing.row < row)
            turned = (heading_col, heading_row) not in ((0, 0), (d_col, d_row))
            nxt: _Heading = (landing.col, landing.row, d_col, d_row)
            if nxt in closed:
                continue
            tentative = g + cost + (bend if turned else 0.0)
            if tentative >= g_score.get(nxt, math.inf):
                continue
            g_score[nxt] = tentative
            came_from[nxt] = (state, hopped)
            heapq.heappush(heap, (tentative + manhattan(landing, to) * step_cost, pushed, nxt))
            pushed += 1
    return None


def _moves_from(
    ctx: _RouteContext, hole: HoleCoord, from_: HoleCoord, to: HoleCoord
) -> list[tuple[HoleCoord, bool, float]]:
    """Legal moves out of a hole: (destination, was it a hop, cost)."""
    costs = ctx.opts.costs
    goal_key = _key(to)
    moves: list[tuple[HoleCoord, bool, float]] = []

    for direction_col, direction_row in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        step = HoleCoord(col=hole.col + direction_col, row=hole.row + direction_row)
        if not is_inside_board(step, ctx.doc.board):
            continue
        is_goal = _key(step) == goal_key
        if is_goal or _is_traversable_by_trace(ctx, step):
            cost = costs.solder_trace_step
            if _has_foreign_neighbour(ctx, step, from_, to):
                cost += costs.proximity_risk
            moves.append((step, False, cost))
            continue

        # Blocked. Try to jump over it and land on clear ground beyond, which is what a short
        # insulated jumper does. The landing hole must be free (or the goal); the holes flown
        # over need not be, since the wire is insulated.
        for span in range(2, ctx.opts.max_hop_holes + 2):
            landing = HoleCoord(
                col=hole.col + direction_col * span, row=hole.row + direction_row * span
            )
            if not is_inside_board(landing, ctx.doc.board):
                break
            landing_is_goal = _key(landing) == goal_key
            if not landing_is_goal and not _is_traversable_by_trace(ctx, landing):
                continue
            moves.append(
                (
                    landing,
                    True,
                    costs.insulated_hop_fixed
                    + path_length_mm((hole, landing), ctx.doc.board) * costs.insulated_wire_per_mm,
                )
            )
            break
    return moves


def _reconstruct_steps(
    came_from: dict[tuple[int, int], tuple[HoleCoord, bool]], goal: HoleCoord, start: HoleCoord
) -> list[_Step]:
    # Each entry records how the search ARRIVED at that hole, so a hole's flag must be read
    # from its own entry. Carrying the flag over to the predecessor instead shifts every hop
    # one step back along the path: the jumper gets placed before the obstacle, and the trace
    # after it inherits the jump -- producing a "solder trace" with a hole missing from its
    # chain, which is not a solder trace at all.
    steps: list[_Step] = []
    cursor = goal
    while not same_hole(cursor, start):
        entry = came_from.get(_key(cursor))
        steps.append(_Step(hole=cursor, hopped=entry is not None and entry[1]))
        if entry is None:
            break
        cursor = entry[0]
    steps.append(_Step(hole=start, hopped=False))
    steps.reverse()
    return steps


class _OpenList:
    """A*'s open list: the lowest f first, and among equal f the one pushed EARLIEST.

    That is exactly what the original engine's linear scan picked -- it kept entries in the
    order they were appended, removed them in place, and took the first with the lowest f
    under a strict ``<`` -- so a heap keyed on (f, push order) pops the same hole every time
    and every golden route stays byte-identical. It was kept a scan on the belief that a
    heap would break ties differently; a heap on f ALONE would, and this is not that one.
    Measured: the scan was an eighth of an auto-place on atmega328-relay.
    """

    __slots__ = ("_heap", "_pushed")

    def __init__(self, start: HoleCoord, f: float) -> None:
        self._heap: list[tuple[float, int, HoleCoord]] = [(f, 0, start)]
        self._pushed = 1

    def __bool__(self) -> bool:
        return bool(self._heap)

    def push(self, hole: HoleCoord, f: float) -> None:
        heapq.heappush(self._heap, (f, self._pushed, hole))
        self._pushed += 1

    def pop(self) -> HoleCoord:
        return heapq.heappop(self._heap)[2]


def _find_solder_trace_path(
    ctx: _RouteContext, from_: HoleCoord, to: HoleCoord
) -> list[HoleCoord] | None:
    """A* over holes, 4-connected.

    Blocked cells are holes whose solder-side copper already belongs to something
    else; the two endpoints are always allowed since they are what we are joining.
    The proximity risk is charged as step cost so the search prefers routes that
    keep clear of foreign pads rather than merely legal ones.
    """
    costs = ctx.opts.costs
    if costs.trace_bend > 0:
        turning = _find_turning_trace_path(ctx, from_, to, hops=False)
        if turning is not None:
            return [step.hole for step in turning]
    max_expanded_nodes = ctx.opts.max_expanded_nodes
    start_key = _key(from_)
    goal_key = _key(to)

    g_score: dict[tuple[int, int], float] = {start_key: 0.0}
    came_from: dict[tuple[int, int], HoleCoord] = {}
    # Lowest f first, ties to the earliest pushed -- the original's scan, see _OpenList.
    open_list = _OpenList(from_, manhattan(from_, to) * costs.solder_trace_step)
    closed: set[tuple[int, int]] = set()
    expanded = 0

    while open_list:
        current = open_list.pop()

        current_key = _key(current)
        if current_key == goal_key:
            return _reconstruct(came_from, current, from_)
        if current_key in closed:
            continue
        closed.add(current_key)

        expanded += 1
        if expanded > max_expanded_nodes:
            return None

        g = g_score.get(current_key, math.inf)
        for next_hole in neighbors4(current, ctx.doc.board):
            next_key = _key(next_hole)
            if next_key in closed:
                continue
            is_endpoint = next_key == goal_key
            if not is_endpoint and not _is_traversable_by_trace(ctx, next_hole):
                continue

            step = costs.solder_trace_step
            if _has_foreign_neighbour(ctx, next_hole, from_, to):
                step += costs.proximity_risk

            tentative = g + step
            if tentative >= g_score.get(next_key, math.inf):
                continue

            g_score[next_key] = tentative
            came_from[next_key] = current
            open_list.push(next_hole, tentative + manhattan(next_hole, to) * costs.solder_trace_step)

    return None


def _is_traversable_by_trace(ctx: _RouteContext, hole: HoleCoord) -> bool:
    """A trace may pass through a hole that is empty, or already on the net being routed."""
    key = (hole.col, hole.row)
    remembered = ctx.traversable.get(key)
    if remembered is None:
        remembered = ctx.traversable[key] = _traversable(ctx, hole)
    return remembered


def _traversable(ctx: _RouteContext, hole: HoleCoord) -> bool:
    """The answer :func:`_is_traversable_by_trace` remembers."""
    if ctx.occupancy.is_copper_blocked(hole, "bottom"):
        return False
    # Also refuse holes an existing WIRE lies across. Occupancy indexes a wire by its two
    # ends only (a documented gap it keeps for its own differential proof), so without this
    # the search would run a solder trace straight through the middle of an existing wire --
    # which DRC's conductor-crossing rule then, correctly, calls an error. A router must not
    # produce what the checker rejects.
    if _key(hole) in ctx.swept_blocked_holes:
        return False
    # A solder trace is soldered down at EVERY pad it crosses, so a hole with no pad
    # breaks the run part-way along. Exactly the set drc.py calls an error, read from the
    # one function both of them share.
    if _key(hole) in ctx.unusable_holes:
        return False
    # A wire's soldered end is a joint like a pin, and gets the same treatment below: a
    # hole the caller declared this net's own may be run through, anything else may not.
    if _key(hole) in ctx.wire_joint_holes and _key(hole) not in ctx.net_holes:
        return False
    pin = ctx.occupancy.pin_at(hole)
    # A foreign pin in the way is a hard stop: soldering across it would short it in. A pin
    # the caller has declared part of this same net is the opposite -- running the trace
    # through it is how a rail collects its pins (see RouteRequest.net_holes), and doing so
    # is what makes one long rail cheaper than a fan of separate hops.
    return not (pin and _key(hole) not in ctx.net_holes)


def _has_foreign_neighbour(
    ctx: _RouteContext, hole: HoleCoord, from_: HoleCoord, to: HoleCoord
) -> bool:
    """Does this hole have an orthogonal neighbour belonging to a different net?

    At 2.54 mm pitch the pad-edge gap is well under a millimetre, so this is where a
    dragged bead of solder ends up somewhere it should not. DRC rule R5', priced into
    the search.

    "Different" is judged against the physical nets of the two endpoints AND against any
    holes the caller declared as this net's own (``RouteRequest.net_holes``): a bridge to
    a pad that is supposed to be on this net is not a defect, so charging risk for it
    would price the router out of the rails it should be building.
    """
    memo_key = (from_.col, from_.row, to.col, to.row, hole.col, hole.row)
    remembered = ctx.risky_holes.get(memo_key)
    if remembered is not None:
        return remembered

    key = (from_.col, from_.row, to.col, to.row)
    own_nets = ctx.endpoint_own_nets.get(key)
    if own_nets is None:
        found: set[str] = set(ctx.declared_own_nets)
        for endpoint in (from_, to):
            net_id = ctx.net_at(endpoint)
            if net_id is not None:
                found.add(net_id)
        own_nets = frozenset(found)
        ctx.endpoint_own_nets[key] = own_nets

    risky = False
    for neighbour in neighbors4(hole, ctx.doc.board):
        if same_hole(neighbour, from_) or same_hole(neighbour, to):
            continue
        if _key(neighbour) in ctx.net_holes:
            continue
        net_id = ctx.net_at(neighbour)
        if net_id is not None and net_id not in own_nets:
            risky = True
            break
    ctx.risky_holes[memo_key] = risky
    return risky


def _reconstruct(
    came_from: dict[tuple[int, int], HoleCoord], goal: HoleCoord, start: HoleCoord
) -> list[HoleCoord]:
    path: list[HoleCoord] = [goal]
    cursor = goal
    while not same_hole(cursor, start):
        prev = came_from.get(_key(cursor))
        if prev is None:
            break
        path.append(prev)
        cursor = prev
    path.reverse()
    return path


# ---------------------------------------------------------------------------
# Strategies 2-4: straight wires
# ---------------------------------------------------------------------------


def _lead_bend_candidate(
    ctx: _RouteContext, from_: HoleCoord, to: HoleCoord
) -> RouteCandidate | None:
    """The component's own leg, bent over to reach a nearby hole.

    The cheapest primitive on the board and, until now, the only one the router never
    produced: PLAN.md Sec 6.1 prices it at roughly nothing because there is no wire to
    cut, stretch or strip -- the leg is already there and already soldered at one end.

    Three constraints make it a real thing rather than free wire. It has to start at a
    COMPONENT PIN, since that is whose leg is being bent, which is why ``RouteRequest``
    grew ``from_pin``. It is bounded by ``max_lead_bend_holes``, because past that the
    unsupported span fatigues and shorts against its neighbours -- the same threshold
    DRC rule 10 reports on. And it is bare metal on the solder side, so it may not cross
    other copper any more than a bare wire may.

    Off by default (``RouterOptions.allow_lead_bend``). Turning it on changes what the
    router produces on boards the golden fixtures pin, so it is a deliberate choice --
    the same treatment ``allow_top_jumper`` gets, and for the same reason.
    """
    pin = ctx.opts_from_pin
    if pin is None:
        return None
    component_id, pin_number = pin

    if manhattan(from_, to) > ctx.opts.max_lead_bend_holes:
        return None

    crossed = holes_under_line(from_, to)
    for hole in crossed:
        if same_hole(hole, from_) or same_hole(hole, to):
            continue
        if ctx.occupancy.is_copper_blocked(hole, "bottom"):
            return None
        if ctx.occupancy.pin_at(hole):
            return None
        if _key(hole) in ctx.wire_joint_holes:
            return None
    if _crosses_existing(ctx, from_, to):
        return None

    length_mm = path_length_mm((from_, to), ctx.doc.board)
    conductor: NewConductor = NewLeadBendConductor(
        path=(from_, to),
        component_id=component_id,
        pin_number=pin_number,
        net_id=ctx.own_net_id,
        layer_z=0,
    )
    return RouteCandidate(
        strategy="lead-bend",
        conductors=(conductor,),
        cost=ctx.opts.costs.lead_bend_fixed + length_mm * ctx.opts.costs.lead_bend_per_mm,
        explanation=(
            f"Lead bend: fold {pin_number}'s own leg {length_mm:.1f} mm from "
            f"{format_hole(from_, ctx.doc.board)} to {format_hole(to, ctx.doc.board)} — no wire to cut, and it is "
            "already soldered at one end."
        ),
        risk_holes=(),
    )


def _straight_wire_candidate(
    ctx: _RouteContext,
    from_: HoleCoord,
    to: HoleCoord,
    kind: Literal["bare-wire", "insulated-wire", "top-jumper"],
) -> RouteCandidate | None:
    costs = ctx.opts.costs
    crossed = holes_under_line(from_, to)

    if kind == "bare-wire":
        # Bare wire cannot cross another conductor's copper or sit on a foreign pad.
        for hole in crossed:
            if same_hole(hole, from_) or same_hole(hole, to):
                continue
            if ctx.occupancy.is_copper_blocked(hole, "bottom"):
                return None
            if ctx.occupancy.pin_at(hole):
                return None
            if _key(hole) in ctx.wire_joint_holes:
                return None
        # ...and it cannot lie ACROSS one either. The hole checks above only see copper the
        # line lands on; two runs at an angle cross between holes, touching none in common.
        # Without this the router happily produced boards with bare wires resting on each
        # other -- physically a short, and the exact defect DRC's conductor-crossing rule
        # reports (see geometry.segments_touch).
        if _crosses_existing(ctx, from_, to):
            return None
    if kind == "top-jumper":
        # A top jumper must not have to run underneath a component body.
        for hole in crossed:
            if ctx.occupancy.body_covers(hole):
                return None

    length_mm = path_length_mm((from_, to), ctx.doc.board)

    if kind == "bare-wire":
        fixed = costs.bare_wire_fixed
        per_mm = costs.bare_wire_per_mm
    elif kind == "insulated-wire":
        fixed = costs.insulated_wire_fixed
        per_mm = costs.insulated_wire_per_mm
    else:
        fixed = costs.top_jumper_fixed
        per_mm = costs.top_jumper_per_mm

    side = wire_side(kind, ctx.doc.board)
    layer_z = 1 if kind == "insulated-wire" else 0

    conductor: NewConductor = NewWireConductor(
        path=(from_, to),
        kind=kind,
        side=side,
        gauge_awg=ctx.wire_gauge_awg,
        color=None,
        net_id=ctx.own_net_id,
        layer_z=layer_z,
    )

    if kind == "bare-wire":
        note = "clear straight run on the solder side"
    elif kind == "insulated-wire":
        note = "insulated, so it may pass over other conductors"
    else:
        note = "component-side jumper — visible, and it takes up board space"

    # Capitalised like every other candidate's explanation: these lines are read side by
    # side in the router's report, and "Solder trace: ..." above "bare wire: ..." reads as
    # two different kinds of sentence rather than two entries in one list.
    explanation = (
        f"{kind.replace('-', ' ', 1).capitalize()}: {length_mm:.1f} mm from "
        f"{format_hole(from_, ctx.doc.board)} to {format_hole(to, ctx.doc.board)} — {note}."
    )

    return RouteCandidate(
        strategy=kind,
        conductors=(conductor,),
        cost=fixed + length_mm * per_mm,
        explanation=explanation,
        risk_holes=(),
    )


# ---------------------------------------------------------------------------
# Strategies 2-3, laid along the grid
# ---------------------------------------------------------------------------

#: The four steps along the grid, and which of them turns straight back on each.
_GRID_STEPS: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))
_REVERSE = (1, 0, 3, 2)


def _grid_wire_candidate(
    ctx: _RouteContext,
    from_: HoleCoord,
    to: HoleCoord,
    kind: Literal["bare-wire", "insulated-wire", "top-jumper"],
) -> RouteCandidate | None:
    """A wire laid square to the grid, with as few bends as the board allows.

    Its ``path`` is the two ends and the CORNERS between them, and nothing else has to
    learn anything for that to be right: a wire is joined only at its ends
    (``model.contacts_every_path_hole``), and occupancy, DRC and both views already read a
    wire as the straight runs between consecutive points of its path. A top jumper stays
    straight -- see ``RouterOptions.wire_path``.
    """
    if kind == "top-jumper":
        return _straight_wire_candidate(ctx, from_, to, kind)
    bare = kind == "bare-wire"
    costs = ctx.opts.costs
    per_mm = costs.bare_wire_per_mm if bare else costs.insulated_wire_per_mm
    fixed = costs.bare_wire_fixed if bare else costs.insulated_wire_fixed
    found = _find_grid_wire_path(ctx, from_, to, bare=bare, per_mm=per_mm)
    if found is None:
        return None
    holes, laying = found
    path = _corners(holes)
    bends = len(path) - 2
    length_mm = path_length_mm(path, ctx.doc.board)

    conductor: NewConductor = NewWireConductor(
        path=path,
        kind=kind,
        side="bottom",
        gauge_awg=ctx.wire_gauge_awg,
        color=None,
        net_id=ctx.own_net_id,
        layer_z=0 if bare else 1,
    )
    note = (
        "along the grid on the solder side, clear of every other net's pad"
        if bare
        else "insulated, so it may pass over other conductors"
    )
    return RouteCandidate(
        strategy=kind,
        conductors=(conductor,),
        # The search's own total -- length, bends, and what it lies over and along -- so a
        # wire that had to lie on top of another is priced as such against the other kinds.
        cost=fixed + laying,
        explanation=(
            f"{kind.replace('-', ' ', 1).capitalize()}: {length_mm:.1f} mm from "
            f"{format_hole(from_, ctx.doc.board)} to {format_hole(to, ctx.doc.board)} with {bends} bend(s) — {note}."
        ),
        risk_holes=(),
    )


def _find_grid_wire_path(
    ctx: _RouteContext, from_: HoleCoord, to: HoleCoord, *, bare: bool, per_mm: float
) -> tuple[list[HoleCoord], float] | None:
    """A* over (hole, heading), so a bend can be priced: the holes the wire lies over, in
    order, and what laying it costs.

    A heap keyed on (f, insertion order), like the trace searches' ``_OpenList``, over a
    state that also carries a heading. No golden route was ever laid along the grid, so
    there is nothing here for the tie-breaking to agree with -- only to be deterministic.
    """
    board = ctx.doc.board
    step = board.pitch * per_mm
    bend = ctx.opts.costs.wire_bend
    over = ctx.opts.costs.wire_over_copper
    along = ctx.opts.costs.wire_along_copper
    start = _key(from_)
    goal = _key(to)

    def estimate(col: int, row: int) -> float:
        # Admissible: the Manhattan length is unavoidable, and so is one bend whenever
        # the two ends share neither a row nor a column.
        d_col, d_row = abs(col - goal[0]), abs(row - goal[1])
        return (d_col + d_row) * step + (bend if d_col and d_row else 0.0)

    # A state is (col, row, heading), heading -1 at the start where there is none yet.
    best: dict[tuple[int, int, int], float] = {(start[0], start[1], -1): 0.0}
    came_from: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    heap: list[tuple[float, int, float, int, int, int]] = [
        (estimate(*start), 0, 0.0, start[0], start[1], -1)
    ]
    order = 0
    expanded = 0
    while heap:
        _f, _order, g, col, row, heading = heapq.heappop(heap)
        state = (col, row, heading)
        if g > best.get(state, math.inf):
            continue
        if (col, row) == goal:
            holes = [HoleCoord(col=col, row=row)]
            while state in came_from:
                state = came_from[state]
                holes.append(HoleCoord(col=state[0], row=state[1]))
            holes.reverse()
            return holes, g
        expanded += 1
        # The ceiling counts HOLES, and this search may visit each one in four headings.
        if expanded > ctx.opts.max_expanded_nodes * len(_GRID_STEPS):
            return None
        for turn, (d_col, d_row) in enumerate(_GRID_STEPS):
            if heading != -1 and turn == _REVERSE[heading]:
                continue
            nxt = (col + d_col, row + d_row)
            if not (0 <= nxt[0] < board.cols and 0 <= nxt[1] < board.rows):
                continue
            if nxt != goal and not _wire_may_lie_over(ctx, nxt, bare=bare):
                continue
            if bare and _step_crosses_copper(ctx, (col, row), nxt):
                continue
            cost = g + step + (bend if heading not in (-1, turn) else 0.0)
            if nxt != goal and nxt in ctx.covered_holes:
                cost += over
            if (min((col, row), nxt), max((col, row), nxt)) in ctx.covered_steps:
                cost += along
            next_state = (nxt[0], nxt[1], turn)
            if cost >= best.get(next_state, math.inf):
                continue
            best[next_state] = cost
            came_from[next_state] = state
            order += 1
            heapq.heappush(heap, (cost + estimate(*nxt), order, cost, nxt[0], nxt[1], turn))
    return None


def _wire_may_lie_over(ctx: _RouteContext, key: tuple[int, int], *, bare: bool) -> bool:
    """Whether a wire may pass over this hole on its way somewhere else.

    Nothing may lie over a hole that has no pad -- a bore or a finger. A BARE wire touches
    every pad it lies on, so it is also refused wherever something is soldered: a pin, a
    wire's end, another conductor's copper, or the holes a straight bare wire already lies
    across -- the same four the straight bare wire and the trace search refuse.
    """
    if key in ctx.unusable_holes:
        return False
    if not bare:
        return True
    hole = HoleCoord(col=key[0], row=key[1])
    return not (
        ctx.occupancy.is_copper_blocked(hole, "bottom")
        or ctx.occupancy.pin_at(hole)
        or key in ctx.wire_joint_holes
        or key in ctx.swept_blocked_holes
    )


def _step_crosses_copper(ctx: _RouteContext, a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Would a bare wire stepping from ``a`` to its neighbour ``b`` lie across blocked copper?

    The holes themselves are ``_wire_may_lie_over``'s business; this is copper crossing
    BETWEEN them. ``holes_under_line`` already counts both holes either side of such a gap,
    so on every board measured this refuses nothing the hole test had not -- it is here so
    a step is judged by ``segments_touch``, the one definition DRC's conductor-crossing
    uses, rather than by a sampling that happens to agree. Remembered per step, and asked
    only of the segments whose bounding box covers one of the two holes.
    """
    edge = (a, b) if a <= b else (b, a)
    known = ctx.blocked_edges.get(edge)
    if known is not None:
        return known
    near = set(ctx.segment_cells.get(a, ())) | set(ctx.segment_cells.get(b, ()))
    start, end = HoleCoord(col=a[0], row=a[1]), HoleCoord(col=b[0], row=b[1])
    crosses = any(
        segments_touch(start, end, *ctx.blocked_segments[index]) for index in sorted(near)
    )
    ctx.blocked_edges[edge] = crosses
    return crosses


def _covered_holes(doc: PerfDocument) -> frozenset[tuple[int, int]]:
    """Every hole a solder-side conductor lies across or ends on -- see ``wire_over_copper``."""
    keys: set[tuple[int, int]] = set()
    for conductor in doc.conductors:
        if conductor.side != "bottom":
            continue
        for index in range(len(conductor.path) - 1):
            for hole in holes_under_line(conductor.path[index], conductor.path[index + 1]):
                keys.add(_key(hole))
    return frozenset(keys)


def _covered_steps(doc: PerfDocument) -> frozenset[tuple[tuple[int, int], tuple[int, int]]]:
    """Every step between neighbouring holes a solder-side conductor runs along.

    Only a run square to the grid has any: a diagonal one crosses a grid step, which is
    ``wire_over_copper``'s business, and never lies along one.
    """
    steps: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for conductor in doc.conductors:
        if conductor.side != "bottom":
            continue
        for a, b in itertools.pairwise(conductor.path):
            if a.col != b.col and a.row != b.row:
                continue
            d_col = (b.col > a.col) - (b.col < a.col)
            d_row = (b.row > a.row) - (b.row < a.row)
            here = (a.col, a.row)
            while here != (b.col, b.row):
                there = (here[0] + d_col, here[1] + d_row)
                steps.add((min(here, there), max(here, there)))
                here = there
    return frozenset(steps)


def _segment_cells(
    segments: tuple[tuple[HoleCoord, HoleCoord], ...],
) -> dict[tuple[int, int], tuple[int, ...]]:
    """Which segments' bounding boxes cover each hole -- see ``_step_crosses_copper``."""
    cells: dict[tuple[int, int], list[int]] = {}
    for index, (a, b) in enumerate(segments):
        for col in range(min(a.col, b.col), max(a.col, b.col) + 1):
            for row in range(min(a.row, b.row), max(a.row, b.row) + 1):
                cells.setdefault((col, row), []).append(index)
    return {cell: tuple(indices) for cell, indices in cells.items()}


def _corners(holes: list[HoleCoord]) -> tuple[HoleCoord, ...]:
    """The two ends and every hole where the run turns: what a wire's ``path`` records."""
    kept = [holes[0]]
    for before, here, after in zip(holes, holes[1:], holes[2:], strict=False):
        if (here.col - before.col, here.row - before.row) != (
            after.col - here.col,
            after.row - here.row,
        ):
            kept.append(here)
    kept.append(holes[-1])
    return tuple(kept)


# ---------------------------------------------------------------------------
# Helpers used by callers
# ---------------------------------------------------------------------------


def connection_length_mm(from_: HoleCoord, to: HoleCoord, board: Board) -> float:
    """Straight-line distance in mm, for callers ordering work by how far apart pins are."""
    a = hole_to_mm(from_, board)
    b = hole_to_mm(to, board)
    return math.hypot(b.x - a.x, b.y - a.y)
