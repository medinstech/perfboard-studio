"""What a conductor drawn by hand would do, asked before it is laid.

The drawing tool used to lay anything it was given and say "Done": a solder run straight
through another net's pad, a bare wire across two others, and the only sign was the
Problems badge going up by one. The command is right to take them -- a short is a design
fault DRC reports, not a document the bus refuses (CLAUDE.md, "Commands enforce document
integrity; DRC reports design quality") -- but the person drawing deserves to know at the
step, while the pointer is still on the hole.

NO RULE HERE IS NEW. Every answer comes from a predicate the engine already uses for the
same question, so the preview and DRC cannot disagree about what is a short:

- what a conductor touches: ``model.contacts_every_path_hole`` (a solder run every pad it
  crosses, a wire its two ends);
- which nets those holes are on: ``connectivity.extract_physical_nets`` of the board as it
  is;
- what may not cross what: ``model.is_crossing_blocked``, a shared hole, and
  ``geometry.paths_cross`` -- DRC's rules 4 and 4';
- bare copper resting on a joint: ``geometry.holes_under_line``, DRC's rule 4'';
- a wire laid along another wire: ``geometry.paths_overlap``. Not a short and not refused
  anywhere -- the router prices it -- so it is a warning, said in amber.

The same check names the net the new copper joins (``net_id``): the one net its contacts
meet, a pin's or a conductor's. Only when both ends were pins of one net did the tool
claim a net before, so a run drawn on from another run's end, or from a pin to its own
net's copper, went in with no net -- which Redo Wiring and Remove Out-of-Date Wiring then
never touch, and nothing said so.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Literal

from perfboard_studio.commands import wire_side
from perfboard_studio.connectivity import FootprintLookup, extract_physical_nets
from perfboard_studio.geometry import (
    all_pin_holes,
    hole_key,
    holes_under_line,
    paths_cross,
    segments_overlap,
)
from perfboard_studio.model import (
    BoardSide,
    Conductor,
    ConductorKind,
    HoleCoord,
    NetId,
    PerfDocument,
    SolderTraceConductor,
    WireConductor,
    contacts_every_path_hole,
    is_crossing_blocked,
)

Severity = Literal["error", "warning"]

#: The id the candidate goes by while it is checked; no document id looks like it.
_CANDIDATE = "⁣drawn"


@dataclass(frozen=True, slots=True)
class DrawProblem:
    """One thing wrong with the copper being drawn, at one hole."""

    #: "short" (two nets joined), "cross" (copper that may not cross), "joint" (bare copper
    #: lying on another net's joint), "along" (a wire laid along another wire: a warning).
    kind: Literal["short", "cross", "joint", "along"]
    severity: Severity
    hole: HoleCoord
    #: The two net names a short joins, the first being the one the copper started on.
    nets: tuple[str, str] = ("", "")
    #: The conductor crossed or lain along, or None.
    other: Conductor | None = None
    #: The part and pin under a "joint", or "".
    joint: str = ""


@dataclass(frozen=True, slots=True)
class DrawCheck:
    #: The schematic net the copper joins, when exactly one.
    net_id: NetId | None
    #: Errors first, then warnings, each in the order met along the path.
    problems: tuple[DrawProblem, ...]
    #: Copper already lying exactly where this would, or None: a run whose pads include
    #: these in this order, or a wire or jumper along these very corners. Laid, the new
    #: copper would add nothing but a second piece in the same place.
    duplicate: Conductor | None = None

    @property
    def worst(self) -> DrawProblem | None:
        return self.problems[0] if self.problems else None


def candidate(
    document: PerfDocument,
    kind: ConductorKind,
    path: tuple[HoleCoord, ...],
    side: BoardSide = "bottom",
) -> Conductor:
    """The conductor the tool would lay, as the document would hold it. ``side`` is the face
    a solder run goes on (the window's Draw on choice); a wire's face is its kind's."""
    if kind in ("solder-trace", "solder-trace-wired"):
        return SolderTraceConductor(id=_CANDIDATE, path=path, kind=kind, side=side)
    return WireConductor(
        id=_CANDIDATE,
        path=path,
        kind=kind,  # type: ignore[arg-type]
        side=wire_side(kind, document.board),
    )


_RUNS = frozenset({"solder-trace", "solder-trace-wired"})


def _corners(path: tuple[HoleCoord, ...]) -> tuple[HoleCoord, ...]:
    """A wire's path as the line it is: no hole twice in a row, no point mid-leg."""
    out: list[HoleCoord] = []
    for hole in path:
        if out and out[-1] == hole:
            continue
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            ab = (b.col - a.col, b.row - a.row)
            bc = (hole.col - b.col, hole.row - b.row)
            if ab[0] * bc[1] == ab[1] * bc[0] and ab[0] * bc[0] + ab[1] * bc[1] > 0:
                out[-1] = hole
                continue
        out.append(hole)
    return tuple(out)


def _already_there(drawn: Conductor, other: Conductor) -> bool:
    """Whether ``other`` is already exactly the copper ``drawn`` would lay.

    A run over pads a run already solders in that order -- the whole of it or a stretch of
    it, plain or wired -- joins nothing new. A wire or a jumper along exactly another's
    line, ends and corners, is a second wire in the same place. Anything partly over other
    copper is NOT this: it is a run carried on, a wire along a wire (the amber warning),
    or a short.
    """
    if other.side != drawn.side or len(other.path) < 2:
        return False
    if drawn.kind in _RUNS:
        if other.kind not in _RUNS:
            return False
        mine, theirs = tuple(drawn.path), tuple(other.path)
        n = len(mine)
        return any(
            theirs[i : i + n] in (mine, mine[::-1]) for i in range(len(theirs) - n + 1)
        )
    if other.kind in _RUNS or other.kind in ("lead-bend", "strip"):
        return False
    mine = _corners(tuple(drawn.path))
    return _corners(tuple(other.path)) in (mine, mine[::-1])


def check_drawn(
    document: PerfDocument,
    lookup: FootprintLookup,
    kind: ConductorKind,
    path: tuple[HoleCoord, ...],
    *,
    ignoring: str | None = None,
    side: BoardSide = "bottom",
) -> DrawCheck:
    """What laying ``kind`` along ``path`` on ``document``'s board would join and touch.

    ``ignoring`` is a conductor the new path REPLACES -- a run being extended, an end being
    dragged -- which is not something the new path can cross or lie along. ``side`` is the
    face a solder run is drawn on: a run on the component side neither crosses nor lies
    along the copper underneath.
    """
    if len(path) < 2:
        return DrawCheck(net_id=None, problems=())
    drawn = candidate(document, kind, path, side)
    names = {net.id: net.name for net in document.nets}

    # Which schematic nets each hole's copper is on now, by its physical net: the nets of
    # the pins in it, and the nets its conductors claim.
    net_of_pin = {
        (node.component_ref, node.pin): net.id for net in document.nets for node in net.nodes
    }
    claims = {c.id: c.net_id for c in document.conductors if c.net_id is not None}
    physical = extract_physical_nets(document, lookup)
    nets_at: dict[str, tuple[NetId, ...]] = {}
    physical_at: dict[str, str] = {}
    conductor_physical: dict[str, str] = {}
    for each in physical:
        found: dict[NetId, None] = {}
        for pin in each.pins:
            net = net_of_pin.get((pin.component_ref, pin.pin))
            if net is not None:
                found[net] = None
        for conductor_id in each.conductor_ids:
            conductor_physical[conductor_id] = each.id
            claimed = claims.get(conductor_id)
            if claimed is not None:
                found[claimed] = None
        for node in each.nodes:
            key = hole_key(node.hole)
            physical_at.setdefault(key, each.id)
            if found:
                nets_at.setdefault(key, tuple(found))

    contacts = list(path) if contacts_every_path_hole(drawn) else [path[0], path[-1]]
    errors: list[DrawProblem] = []
    warnings: list[DrawProblem] = []

    # The nets met along the contacts, in order: the first is the copper's own.
    met: list[NetId] = []
    for hole in contacts:
        for net in nets_at.get(hole_key(hole), ()):
            if net in met:
                continue
            if met:
                errors.append(
                    DrawProblem(
                        kind="short", severity="error", hole=hole,
                        nets=(names.get(met[0], met[0]), names.get(net, net)),
                    )
                )
            met.append(net)
    own_physical = {physical_at[k] for h in contacts if (k := hole_key(h)) in physical_at}

    def same_copper(other: Conductor) -> bool:
        there = conductor_physical.get(other.id)
        return there is not None and there in own_physical

    duplicate: Conductor | None = None
    for other in document.conductors:
        if other.id == ignoring:
            continue
        if duplicate is None and _already_there(drawn, other):
            duplicate = other
        if other.side != drawn.side or len(other.path) < 2:
            continue
        both_blocked = is_crossing_blocked(drawn) and is_crossing_blocked(other)
        if both_blocked and not same_copper(other):
            shared = next((h for h in path if hole_key(h) in {hole_key(o) for o in other.path}), None)
            at = shared if shared is not None else _meeting_hole(path, other.path)
            if at is not None:
                errors.append(DrawProblem(kind="cross", severity="error", hole=at, other=other))
                continue
        if drawn.kind not in ("solder-trace", "solder-trace-wired") and other.kind not in (
            "solder-trace", "solder-trace-wired", "lead-bend", "strip"
        ):
            along = _first_overlap(path, other.path)
            if along is not None:
                warnings.append(DrawProblem(kind="along", severity="warning", hole=along, other=other))

    if drawn.kind == "bare-wire" and drawn.side == "bottom":
        errors.extend(_over_joints(document, lookup, path, nets_at, met))

    return DrawCheck(
        net_id=met[0] if len(met) == 1 else None,
        problems=(*errors, *warnings),
        duplicate=duplicate,
    )


def _line_holes(path: tuple[HoleCoord, ...]) -> list[HoleCoord]:
    """Every hole a path's line passes over, its own holes included, in order."""
    holes = [path[0]]
    for from_, to in itertools.pairwise(path):
        holes.extend(h for h in holes_under_line(from_, to) if h != from_)
        if holes[-1] != to:
            holes.append(to)
    return holes


def _meeting_hole(a: tuple[HoleCoord, ...], b: tuple[HoleCoord, ...]) -> HoleCoord | None:
    """Where two crossing paths meet, as the hole a person would look at: the first hole on
    ``a``'s line that ``b``'s line also passes over, else ``geometry.paths_cross``'s answer
    for a crossing between holes."""
    if paths_cross(a, b) is None:
        return None
    over_b = {hole_key(h) for h in _line_holes(b)}
    return next((h for h in _line_holes(a) if hole_key(h) in over_b), paths_cross(a, b))


def _first_overlap(a: tuple[HoleCoord, ...], b: tuple[HoleCoord, ...]) -> HoleCoord | None:
    """Where ``a`` first runs along ``b`` (``geometry.segments_overlap``), or None."""
    for a1, a2 in itertools.pairwise(a):
        for b1, b2 in itertools.pairwise(b):
            if segments_overlap(a1, a2, b1, b2):
                return a1
    return None


def _over_joints(
    document: PerfDocument,
    lookup: FootprintLookup,
    path: tuple[HoleCoord, ...],
    nets_at: dict[str, tuple[NetId, ...]],
    own: list[NetId],
) -> list[DrawProblem]:
    """Bare copper resting on a part's joint between its ends, on another net: DRC's
    ``wire-over-joint``, asked through the same ``holes_under_line``."""
    joints: dict[str, str] = {}
    for component in document.components:
        footprint = lookup(component.footprint_id)
        if footprint is None:
            continue
        for pin, hole in all_pin_holes(component, footprint):
            joints.setdefault(hole_key(hole), f"{component.ref}.{pin.number}")
    ends = {hole_key(path[0]), hole_key(path[-1])}
    found: list[DrawProblem] = []
    for from_, to in itertools.pairwise(path):
        for hole in holes_under_line(from_, to):
            key = hole_key(hole)
            if key in ends or key not in joints:
                continue
            there = nets_at.get(key, ())
            if own and there and set(there) <= set(own):
                continue
            found.append(DrawProblem(kind="joint", severity="error", hole=hole, joint=joints[key]))
    return found
