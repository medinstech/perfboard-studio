"""What a board's wiring costs the person building it, conductor by conductor.

One answer with three askers: ``tools/autowire_scoreboard.py`` (and its ceiling test), which
holds the router to these numbers; the window's summary after Auto-wire and its Problems
drawer, which count them; and a selected wire's Properties, which names what it lies across.
Each total is the sum -- or for the stack, the maximum -- of the entries per conductor, so a
count and the wires it selects can never disagree.

What each number means, and why the scoreboard has it, is "Auto-wire is held to a
scoreboard" in docs/ARCHITECTURE.md. In short:

* ``level`` -- ``occupancy.stacking_layers``: how many wires' thickness below the board.
* ``over_pins`` -- holes a wire lies across, not its own ends, where a pin is: a joint hidden
  under the wire, and where a wire laid later will end.
* ``over_ends`` -- holes a wire lies across where another conductor on its face ends and comes
  down to its pad: each one stacks the wire above that one.
* ``crosses`` -- conductors on the same face sharing a hole with it where the two are not
  soldered together: what it passes over or under.

Only a wire -- soldered at its ends alone (``model.contacts_every_path_hole`` False: a wire, a
jumper, a bent lead) -- lies ACROSS anything; a solder run is soldered at every hole it
passes, so a pin or an end on it is a junction. A run's entry carries its pads and its
crossings, and empty ``over_pins`` / ``over_ends``.

Pure: no clock, no filesystem, no Qt.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from .connectivity import FootprintLookup
from .geometry import hole_key, holes_under_line, path_length_mm
from .model import (
    BoardSide,
    Conductor,
    ConductorId,
    ConductorKind,
    HoleCoord,
    PerfDocument,
    contacts_every_path_hole,
)
from .occupancy import build_occupancy, stacking_layers, stacking_loops
from .ratsnest import ratsnest, summarize


@dataclass(frozen=True, slots=True)
class ConductorStats:
    """One conductor's share of the wiring's cost."""

    conductor_id: ConductorId
    kind: ConductorKind
    side: BoardSide
    #: Soldered at its two ends only (``contacts_every_path_hole`` False), with a path to
    #: lie along. False for a solder run or a strip, and for a conductor of one hole.
    is_wire: bool
    #: ``occupancy.stacking_layers``.
    level: int
    length_mm: float
    #: Corners in a wire's path. 0 for a run, whose path lists every hole it passes.
    bends: int
    #: Holes a run is soldered along. 0 for a wire.
    pads: int
    #: Holes a wire lies across, its own ends excepted, where a pin is.
    over_pins: tuple[HoleCoord, ...]
    #: Holes a wire lies across, its own ends excepted, where another conductor on its face
    #: ends.
    over_ends: tuple[HoleCoord, ...]
    #: Conductors on the same face that share a hole with this one where the two are not
    #: both soldered -- one passes over or under the other there. In document order.
    crosses: tuple[ConductorId, ...]


@dataclass(frozen=True, slots=True)
class WiringStats:
    """A board's wiring, totalled from its conductors' entries."""

    #: Every conductor, in document order.
    conductors: tuple[ConductorStats, ...]
    #: Connections the netlist still needs (``ratsnest``).
    unrouted: int
    #: Sums over the wires.
    wire_mm: float
    bends: int
    over_pins: int
    over_ends: int
    #: The tallest stack of wires: the largest ``level`` among them.
    max_level: int
    #: Sum over the runs.
    trace_pads: int
    #: ``occupancy.stacking_loops``: wires each lying across another's end.
    loops: tuple[tuple[ConductorId, ...], ...]

    def of(self, conductor_id: ConductorId) -> ConductorStats | None:
        """The entry for one conductor, or None when there is no such conductor."""
        return next((c for c in self.conductors if c.conductor_id == conductor_id), None)


def wiring_stats(doc: PerfDocument, lookup: FootprintLookup) -> WiringStats:
    """Every conductor's entry, and the board's totals."""
    levels = stacking_layers(doc, lookup=lookup)
    occupancy = build_occupancy(doc, lookup)
    ending: dict[tuple[str, BoardSide], set[ConductorId]] = {}
    for conductor in doc.conductors:
        if conductor.path:
            for end in (conductor.path[0], conductor.path[-1]):
                ending.setdefault((hole_key(end), conductor.side), set()).add(conductor.id)

    under = {conductor.id: _holes_under(conductor) for conductor in doc.conductors}
    soldered = {conductor.id: _soldered_at(conductor) for conductor in doc.conductors}
    crosses = _crossings(doc, under, soldered)

    entries: list[ConductorStats] = []
    for conductor in doc.conductors:
        is_wire = not contacts_every_path_hole(conductor) and len(conductor.path) >= 2
        over_pins: list[HoleCoord] = []
        over_ends: list[HoleCoord] = []
        if is_wire:
            own = soldered[conductor.id]
            for key, hole in under[conductor.id].items():
                if key in own:
                    continue
                if occupancy.pin_at(hole) is not None:
                    over_pins.append(hole)
                if ending.get((key, conductor.side), set()) - {conductor.id}:
                    over_ends.append(hole)
        entries.append(
            ConductorStats(
                conductor_id=conductor.id,
                kind=conductor.kind,
                side=conductor.side,
                is_wire=is_wire,
                level=levels.get(conductor.id, 0),
                length_mm=path_length_mm(conductor.path, doc.board) if len(conductor.path) >= 2 else 0.0,
                bends=max(0, len(conductor.path) - 2) if is_wire else 0,
                pads=len(conductor.path) if contacts_every_path_hole(conductor) else 0,
                over_pins=tuple(over_pins),
                over_ends=tuple(over_ends),
                crosses=crosses[conductor.id],
            )
        )

    wires = [entry for entry in entries if entry.is_wire]
    return WiringStats(
        conductors=tuple(entries),
        unrouted=summarize(ratsnest(doc, lookup)).links,
        wire_mm=sum(entry.length_mm for entry in wires),
        bends=sum(entry.bends for entry in wires),
        over_pins=sum(len(entry.over_pins) for entry in wires),
        over_ends=sum(len(entry.over_ends) for entry in wires),
        max_level=max((entry.level for entry in wires), default=0),
        trace_pads=sum(entry.pads for entry in entries),
        loops=stacking_loops(doc),
    )


def _holes_under(conductor: Conductor) -> dict[str, HoleCoord]:
    """Every hole the conductor lies across or ends on, by key, in path order."""
    holes: dict[str, HoleCoord] = {}
    if len(conductor.path) == 1:
        holes[hole_key(conductor.path[0])] = conductor.path[0]
    for start, stop in itertools.pairwise(conductor.path):
        for hole in holes_under_line(start, stop):
            holes.setdefault(hole_key(hole), hole)
    return holes


def _soldered_at(conductor: Conductor) -> frozenset[str]:
    """Where the conductor is soldered: every hole of a run's path, a wire's two ends."""
    if not conductor.path:
        return frozenset()
    if contacts_every_path_hole(conductor):
        return frozenset(hole_key(hole) for hole in conductor.path)
    return frozenset({hole_key(conductor.path[0]), hole_key(conductor.path[-1])})


def _crossings(
    doc: PerfDocument,
    under: dict[ConductorId, dict[str, HoleCoord]],
    soldered: dict[ConductorId, frozenset[str]],
) -> dict[ConductorId, tuple[ConductorId, ...]]:
    """For each conductor, the ones on its face it shares a hole with where the two are not
    both soldered. Pairs are prefiltered by bounding box: a board has a few hundred
    conductors, most of them nowhere near each other."""
    found: dict[ConductorId, list[ConductorId]] = {c.id: [] for c in doc.conductors}
    boxes = {c.id: _box(c.path) for c in doc.conductors if c.path}
    placed = [c for c in doc.conductors if c.path]
    for a, b in itertools.combinations(placed, 2):
        if a.side != b.side or not _boxes_meet(boxes[a.id], boxes[b.id]):
            continue
        shared = under[a.id].keys() & under[b.id].keys()
        if any(not (key in soldered[a.id] and key in soldered[b.id]) for key in shared):
            found[a.id].append(b.id)
            found[b.id].append(a.id)
    order = {c.id: index for index, c in enumerate(doc.conductors)}
    return {cid: tuple(sorted(ids, key=order.__getitem__)) for cid, ids in found.items()}


def _box(path: tuple[HoleCoord, ...]) -> tuple[int, int, int, int]:
    cols = [hole.col for hole in path]
    rows = [hole.row for hole in path]
    return min(cols), min(rows), max(cols), max(rows)


def _boxes_meet(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]
