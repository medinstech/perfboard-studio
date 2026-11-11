"""Occupancy index: what physically sits at each (hole, side).

This is the counterpart to connectivity.py, and the split between them is deliberate.
Connectivity answers "what is electrically joined" -- a wire contacts only its two
endpoints. Occupancy answers "what is physically in the way" -- that same wire runs
across every hole on its path, and the router may not lay a bare trace through them.

Keeping the two apart is what lets connectivity stay clean (no meaningless one-node nets
for holes a wire merely crosses) while the router still knows the board is full there.

Pure and deterministic: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .connectivity import FootprintLookup
from .footprints import body_extent, body_is_round
from .geometry import (
    all_pin_holes,
    hole_key,
    hole_to_mm,
    holes_under_line,
    paths_cross,
    paths_overlap,
    point_under_body,
    transform_offset,
    turned_box,
)
from .model import (
    SEATED_ARCHETYPES,
    Board,
    BoardSide,
    ComponentId,
    ComponentInstance,
    Conductor,
    ConductorId,
    ConductorKind,
    Footprint,
    HoleCoord,
    PerfDocument,
    contacts_every_path_hole,
    is_crossing_blocked,
)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OccupyingPin:
    component_id: ComponentId
    component_ref: str
    pin: str


@dataclass(frozen=True, slots=True)
class OccupancyIndex:
    """Precomputed answer to "what is here" for every occupied (hole, side).

    Constructed once by :func:`build_occupancy`; queried through its methods rather
    than by reaching into the underlying maps, which stay private to this module's
    hole-key encoding.
    """

    _conductors_by_node: Mapping[str, tuple[ConductorId, ...]]
    _blocked_nodes: frozenset[str]
    _pins_by_hole: Mapping[str, OccupyingPin]
    _body_by_hole: Mapping[str, ComponentId]
    _sorted_holes: tuple[HoleCoord, ...]
    #: (hole, side) -> (the part, whether its body is seated) for a pin its OWN body covers
    #: on the face the part is on. See :meth:`covered_pin`.
    _covered_pins: Mapping[str, tuple[ComponentId, bool]] = MappingProxyType({})

    def conductors_at(self, hole: HoleCoord, side: BoardSide) -> tuple[ConductorId, ...]:
        """Conductors whose path runs across this hole on this side, contact or not."""
        return self._conductors_by_node.get(_node_key(hole, side), ())

    def pin_at(self, hole: HoleCoord) -> OccupyingPin | None:
        """The component pin in this hole, if any. A pin occupies both sides."""
        return self._pins_by_hole.get(hole_key(hole))

    def is_copper_blocked(self, hole: HoleCoord, side: BoardSide) -> bool:
        """True when a conductor that cannot be crossed already occupies this hole+side.

        A router laying a solder trace or bare wire must treat these as walls;
        insulated wire and top jumpers may pass over them.
        """
        return _node_key(hole, side) in self._blocked_nodes

    def body_covers(self, hole: HoleCoord, side: BoardSide = "top") -> ComponentId | None:
        """Component whose body covers this hole on ``side``, if any: the component side
        unless asked, where every body was before a part could be put on the solder side."""
        return self._body_by_hole.get(_node_key(hole, side))

    def covered_pin(self, hole: HoleCoord, side: BoardSide) -> tuple[ComponentId, bool] | None:
        """The part whose pin is in this hole when its OWN body covers the pad on ``side``,
        and whether that body is seated (``model.SEATED_ARCHETYPES``); None otherwise.

        A seated body -- a header's plastic, a chip, a terminal block -- sits on the board
        over the pad, so no joint can be made there on that face: no copper may end at it
        or pass it. A part standing on its leads clears it if the leads are left long.
        ``drc``'s ``joint-under-body`` and ``copper-at-covered-pin``, the router's two-face
        search and the guide all read this one answer."""
        return self._covered_pins.get(_node_key(hole, side))

    def occupied_holes(self) -> tuple[HoleCoord, ...]:
        """Every hole that has anything at all on it, for quick iteration."""
        return self._sorted_holes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_key(hole: HoleCoord, side: BoardSide) -> str:
    return f"{hole_key(hole)}@{side}"


def build_occupancy(doc: PerfDocument, lookup: FootprintLookup) -> OccupancyIndex:
    conductors_by_node: dict[str, list[ConductorId]] = {}
    blocked_nodes: set[str] = set()
    pins_by_hole: dict[str, OccupyingPin] = {}
    body_by_hole: dict[str, ComponentId] = {}
    covered_pins: dict[str, tuple[ComponentId, bool]] = {}
    holes: dict[str, HoleCoord] = {}

    def remember(hole: HoleCoord) -> None:
        k = hole_key(hole)
        if k not in holes:
            holes[k] = hole

    # --- Component pins and bodies. ---
    for component in doc.components:
        footprint = lookup(component.footprint_id)
        if footprint is None:
            continue

        for pin, hole in all_pin_holes(component, footprint):
            remember(hole)
            pins_by_hole[hole_key(hole)] = OccupyingPin(
                component_id=component.id,
                component_ref=component.ref,
                pin=pin.number,
            )

        for hole in _body_footprint_holes(component, footprint, doc):
            remember(hole)
            body_by_hole[_node_key(hole, component.side)] = component.id

        seated = footprint.body.archetype in SEATED_ARCHETYPES
        for hole in pins_under_own_body(component, footprint, doc.board):
            covered_pins[_node_key(hole, component.side)] = (component.id, seated)

    # --- Conductors: every hole on the path is physically occupied, contact or not. ---
    #
    # KNOWN GAP, deliberately preserved -- see
    # tests/test_occupancy_golden.py::test_known_gap_occupancy_does_not_model_a_straight_run_geometrically.
    # A wire's `path` is its two ENDS, while the wire itself lies across every hole between
    # them, so those holes are missing from this index. The module docstring above describes
    # the swept behaviour, and only solder traces get it, because their paths already list
    # every hole.
    #
    # Filling it in here is the natural fix and it moves the golden output of this index, of
    # the router and of DRC all at once -- three differential suites against the TypeScript
    # engine. The router therefore handles it locally instead (router._trace_blocked_holes),
    # which fixes the routing defect without touching what this index promises. Widening it
    # properly is a decision to take on its own, not a side effect of a bug fix.
    for conductor in doc.conductors:
        blocks = is_crossing_blocked(conductor)
        for hole in conductor.path:
            remember(hole)
            k = _node_key(hole, conductor.side)
            bucket = conductors_by_node.get(k)
            if bucket is None:
                conductors_by_node[k] = [conductor.id]
            else:
                bucket.append(conductor.id)
            if blocks:
                blocked_nodes.add(k)
                if conductor.side == "top" and contacts_every_path_hole(conductor):
                    # Solder on the component side fills a plated hole and comes out on
                    # the solder-side pad, so the hole is copper underneath too: no trace,
                    # bare wire or bent lead there may pass through it. Only since 0.25,
                    # when a trace could first be laid on top, so no golden moves.
                    blocked_nodes.add(_node_key(hole, "bottom"))

    sorted_holes = tuple(sorted(holes.values(), key=lambda h: (h.col, h.row)))

    return OccupancyIndex(
        _conductors_by_node=MappingProxyType(
            {k: tuple(v) for k, v in conductors_by_node.items()}
        ),
        _blocked_nodes=frozenset(blocked_nodes),
        _pins_by_hole=MappingProxyType(pins_by_hole),
        _body_by_hole=MappingProxyType(body_by_hole),
        _sorted_holes=sorted_holes,
        _covered_pins=MappingProxyType(covered_pins),
    )


def placed_body_box(
    component: ComponentInstance, footprint: Footprint, board: Board
) -> tuple[float, float, float, float]:
    """A component's real body as a board-space box, in the millimetre frame of the holes."""
    min_x, max_x, min_y, max_y = turned_box(
        body_extent(footprint, board.pitch).box, component.rotation, component.mirrored
    )
    anchor = hole_to_mm(component.anchor, board)
    return anchor.x + min_x, anchor.x + max_x, anchor.y + min_y, anchor.y + max_y


#: How far inside a body's edge a pin must be to count as under it. A DIP's body box runs
#: exactly along its two pin rows, and the turned, mirrored and offset box lands a few ulps
#: either side of the pin centres: 17.779999999999998 against a pin at 17.78. Measured
#: strictly, one row of a DIP was under its body at some anchors and rotations and neither
#: row at the rest, so ``joint-under-body`` flagged a DIP on the solder side at random. A
#: pin ON the edge is beside the body, which is where a DIP's pins are.
PIN_UNDER_BODY_MARGIN_MM = 1e-6


def pins_under_own_body(
    component: ComponentInstance, footprint: Footprint, board: Board
) -> tuple[HoleCoord, ...]:
    """The holes of a part's pins its own body covers, measured on the real body
    (:func:`placed_body_box`, round where the package is), in pin order. Nothing for a part
    with no outline, or one off the board (``flying-leads``), which has no body here. A pin
    on the body's edge is not under it (:data:`PIN_UNDER_BODY_MARGIN_MM`)."""
    if not footprint.body_outline or footprint.body.archetype == "flying-leads":
        return ()
    min_x, max_x, min_y, max_y = placed_body_box(component, footprint, board)
    margin = PIN_UNDER_BODY_MARGIN_MM
    box = (min_x + margin, max_x - margin, min_y + margin, max_y - margin)
    round_body = body_is_round(footprint)
    under: list[HoleCoord] = []
    for _pin, hole in all_pin_holes(component, footprint):
        at = hole_to_mm(hole, board)
        if point_under_body(at.x, at.y, box, round_body):
            under.append(hole)
    return tuple(under)


def _body_footprint_holes(
    component: ComponentInstance,
    footprint: Footprint,
    doc: PerfDocument,
) -> list[HoleCoord]:
    """Holes covered by a component's body outline, on the face it is on.

    Uses the outline's axis-aligned bounding box, which is what DRC's overlap check
    uses too -- good enough for deciding whether a top-side jumper would have to run
    underneath a part.
    """
    if len(footprint.body_outline) == 0:
        return []

    anchor_mm = hole_to_mm(component.anchor, doc.board)
    min_x = math.inf
    max_x = -math.inf
    min_y = math.inf
    max_y = -math.inf
    for pt in footprint.body_outline:
        tx, ty = transform_offset(pt.x, pt.y, component.rotation, component.mirrored)
        x = anchor_mm.x + tx
        y = anchor_mm.y + ty
        if x < min_x:
            min_x = x
        if x > max_x:
            max_x = x
        if y < min_y:
            min_y = y
        if y > max_y:
            max_y = y

    pitch = doc.board.pitch
    result: list[HoleCoord] = []
    for col in range(math.ceil(min_x / pitch), math.floor(max_x / pitch) + 1):
        for row in range(math.ceil(min_y / pitch), math.floor(max_y / pitch) + 1):
            if 0 <= col < doc.board.cols and 0 <= row < doc.board.rows:
                result.append(HoleCoord(col=col, row=row))
    return result


def can_cross_copper(kind: ConductorKind) -> bool:
    """Conductor kinds a router may lay over occupied copper."""
    return kind in ("insulated-wire", "top-jumper")


# ---------------------------------------------------------------------------
# Stacking: which conductors have to pass over which
# ---------------------------------------------------------------------------


def stacking_layers(
    doc: PerfDocument, *, lookup: FootprintLookup | None
) -> dict[ConductorId, int]:
    """How many steps clear of the board each conductor has to be drawn, per side.

    A wire that crosses another has to pass OVER it. They cannot occupy the same space,
    and two drawn at one height are shown interpenetrating -- which is not a thing wire
    does, and reads as a modelling error because it is one.

    THE FIRST ANSWER WAS A RUNNING INDEX over ``doc.conductors``, which separated
    everything from everything whether or not it needed separating. Measured: on the dense
    fixture that put the last conductor 4.47 mm off a board 1.6 mm thick, and on the NE555
    routed solder-first, 1.92 mm -- with the solder traces, which are soldered flat ONTO
    the pads, floating along with the wires. It traded interpenetration for levitation.

    So only what actually crosses is lifted, and only past what it crosses:

    * **A solder trace is always level 0.** It *is* the copper. It cannot pass over
      anything -- it is soldered at every pad it touches
      (``model.contacts_every_path_hole``), so a trace crossing another is a short, which
      is DRC's ``conductor-crossing`` and not a question about drawing.
    * **Opposite faces cannot collide**, so they are stacked independently.
    * **A shared endpoint is a junction, not a crossing.** Two wires of one net meeting at
      a pad stay level with each other; ``geometry.segments_touch`` already draws that
      line and DRC reads the same one.

    THE DOCUMENT'S OWN ``layer_z`` IS THE FLOOR, and the level returned is the WHOLE
    answer -- not something a caller adds ``layer_z`` back onto. That was the shape of it,
    and it put conductors this function had deliberately separated back in the same place:
    one at ``layer_z`` 1 and stack 0, the other at ``layer_z`` 0 and stack 1, added up to
    the same height and drawn straight through each other. Four of the fifteen golden
    fixtures had exactly that pair.

    * **A wire lying across the hole another conductor ENDS in is above it.** The other
      one is soldered into that hole, so it comes down to the pad there; drawn below the
      wire lying across, it comes down straight through it. Crossing alone only said "not
      at one level", and the stacker put whichever came later on top: on the auto-wired
      atmega328-relay that was 14 wires coming down through another. Physically it is the
      order they go in -- the one whose end is under the other is soldered first -- which
      is why the build guide lays a face's wires lowest first.
    * **Two wires sharing a stretch of one line touch**, even from a hole one of them ends
      in (``geometry.paths_overlap``): a shared endpoint is a junction only while the two
      then go their separate ways.
    * **A wire lying across a pin's hole on the face its lead comes out of is at least
      level 1.** A lead is trimmed about a millimetre past its joint, and a wire laid flat
      across that hole is laid through the stub: seven of them on the golden fixtures, bare
      wires and top jumpers on the solder side, every one at level 0. An insulated wire's
      ``layer_z`` floor is already 1. ``lookup`` is REQUIRED, like ``format_hole``'s board,
      so a caller that forgets it is a type error rather than a view quietly drawing wires
      through leads; None says there are no parts to ask about.

    IN ID ORDER, NOT DOCUMENT ORDER, taking the lowest free level at or above the floor and
    above everything the conductor lies across the end of. ``persist`` writes conductors
    sorted by id, so in document order a board stacked one way as auto-wire left it and
    another after Save and Open. A board where nothing crosses comes back entirely flat,
    which is what such a board looks like. Two wires that each lie across the other's end
    cannot both be above; :func:`stacking_loops` names them, and the one first in id order
    is placed first.

    Pure, so both renderers can read it and neither can drift: a wire drawn passing over
    another in 3D is the one drawn over it in 2D.
    """
    return _stack(doc, lookup)[0]


def stacking_loops(doc: PerfDocument) -> tuple[tuple[ConductorId, ...], ...]:
    """Wires no stacking can draw apart: each lies, directly or through the others, across
    the hole another of them ends in, so none of them can go in first. Each loop once, its
    members in id order."""
    return _stack(doc, None)[1]


def _stack(
    doc: PerfDocument, lookup: FootprintLookup | None
) -> tuple[dict[ConductorId, int], tuple[tuple[ConductorId, ...], ...]]:
    conductors = sorted(doc.conductors, key=lambda c: c.id)
    layers: dict[ConductorId, int] = {}
    placed: list[tuple[Conductor, int]] = []

    # The traces first, ALL of them, before any wire is placed. They cannot move, so a wire
    # has to be judged against every one of them and not merely against the ones that
    # happen to come earlier -- which is how a wire written before the run it crosses ended
    # up buried in it.
    for conductor in conductors:
        if contacts_every_path_hole(conductor) or len(conductor.path) < 2:
            layers[conductor.id] = conductor.layer_z
            placed.append((conductor, conductor.layer_z))
    wires = [c for c in conductors if c.id not in layers]

    # Which wire ends where, per face, and which wires each one has to be above.
    ending: dict[tuple[str, BoardSide], list[int]] = {}
    for index, wire in enumerate(wires):
        for end in {hole_key(wire.path[0]), hole_key(wire.path[-1])}:
            ending.setdefault((end, wire.side), []).append(index)
    # Where a lead comes out, per face: the face opposite the part it belongs to.
    stubs: set[tuple[str, BoardSide]] = set()
    for component in doc.components if lookup is not None else ():
        footprint = lookup(component.footprint_id) if lookup is not None else None
        if footprint is None:
            continue
        face: BoardSide = "bottom" if component.side == "top" else "top"
        for _pin, hole in all_pin_holes(component, footprint):
            stubs.add((hole_key(hole), face))
    above: list[set[int]] = [set() for _ in wires]
    over_stub = [False] * len(wires)
    for index, wire in enumerate(wires):
        ends = {hole_key(wire.path[0]), hole_key(wire.path[-1])}
        for start, stop in zip(wire.path, wire.path[1:], strict=False):
            for hole in holes_under_line(start, stop):
                key = hole_key(hole)
                if key in ends:
                    continue
                if (key, wire.side) in stubs:
                    over_stub[index] = True
                for other in ending.get((key, wire.side), ()):
                    if other != index:
                        above[index].add(other)

    # A loop is every wire that is, through others, above itself: the wires mutually
    # reachable along "lies above". Within one, nothing can satisfy every constraint, so its
    # members go in id order; every constraint from outside it still holds.
    reach: list[set[int]] = []
    for index in range(len(wires)):
        seen: set[int] = set()
        stack = list(above[index])
        while stack:
            other = stack.pop()
            if other not in seen:
                seen.add(other)
                stack.extend(above[other])
        reach.append(seen)
    loop_of = [
        frozenset({index} | {o for o in reach[index] if index in reach[o]})
        for index in range(len(wires))
    ]
    loops = sorted(
        {
            tuple(wires[i].id for i in sorted(members))
            for members in loop_of
            if len(members) > 1
        }
    )

    # Ready once everything it lies above, outside its own loop, is placed; the earliest in
    # id order whenever several are.
    order: list[int] = []
    done: set[int] = set()
    while len(order) < len(wires):
        index = min(
            i
            for i in range(len(wires))
            if i not in done and above[i] - loop_of[i] <= done
        )
        done.add(index)
        order.append(index)

    for index in order:
        conductor = wires[index]
        # Above every wire whose end it lies across that is already placed -- all of them,
        # unless the two are a loop.
        floor = max(
            [conductor.layer_z, 1 if over_stub[index] else 0]
            + [layers[wires[o].id] + 1 for o in above[index] if wires[o].id in layers]
        )
        taken = {
            level
            for other, level in placed
            if other.side == conductor.side
            and _paths_may_meet(conductor.path, other.path)
            and (
                paths_cross(conductor.path, other.path) is not None
                or paths_overlap(conductor.path, other.path)
            )
        }
        level = floor
        while level in taken:
            level += 1
        layers[conductor.id] = level
        placed.append((conductor, level))

    return layers, tuple(loops)


def _paths_may_meet(a: tuple[HoleCoord, ...], b: tuple[HoleCoord, ...]) -> bool:
    """Cheap bounding-box reject before the O(segments x segments) crossing test.

    Most pairs on a real board are nowhere near each other, and ``paths_cross`` is the
    expensive half of a function that runs on every rebuild of the 3D scene.
    """
    a_cols = [h.col for h in a]
    a_rows = [h.row for h in a]
    b_cols = [h.col for h in b]
    b_rows = [h.row for h in b]
    return (
        min(a_cols) <= max(b_cols)
        and max(a_cols) >= min(b_cols)
        and min(a_rows) <= max(b_rows)
        and max(a_rows) >= min(b_rows)
    )


def conductors_touching(
    doc: PerfDocument, component_id: str, lookup: FootprintLookup
) -> tuple[ConductorId, ...]:
    """The copper on ``doc``'s board that runs to a part: its own lead bends, every conductor
    with an end in one of its pin holes, and every solder run across one -- what would be
    left ending in an empty hole, or soldered to nothing, if the part went. In document
    order. What ``component.moveToBoard`` takes off the part's old board with it."""
    component = next((c for c in doc.components if c.id == component_id), None)
    if component is None:
        return ()
    footprint = lookup(component.footprint_id)
    holes = (
        {hole_key(hole) for _pin, hole in all_pin_holes(component, footprint)}
        if footprint is not None
        else set()
    )
    touching: list[ConductorId] = []
    for conductor in doc.conductors:
        if conductor.kind == "lead-bend" and getattr(conductor, "component_id", None) == component_id:
            touching.append(conductor.id)
            continue
        path = getattr(conductor, "path", ())
        if not path:
            continue
        ends = {hole_key(path[0]), hole_key(path[-1])}
        crossed = {hole_key(h) for h in path} if contacts_every_path_hole(conductor) else set()
        if (ends | crossed) & holes:
            touching.append(conductor.id)
    return tuple(touching)

