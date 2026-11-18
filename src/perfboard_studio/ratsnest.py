"""Ratsnest: what the schematic still asks for and the board does not yet provide.

The schematic (``doc.nets``) says which pins belong together. The connectivity engine
says which pins the board actually joins. The difference between the two, expressed as
the *fewest* connections that would close the gap, is the ratsnest -- the thin lines an
editor draws to show remaining work, and the exact work list an autorouter consumes.

TWO PROPERTIES MATTER, AND BOTH COME FROM WORKING OVER PHYSICAL GROUPS.

A net's pins are first bucketed by the physical net they already sit in, and the
spanning tree is built over those BUCKETS rather than over the raw pins:

  - Already-routed pins stop being proposed. Join two pins of a four-pin net and the
    ratsnest drops from three links to two, not "three links, one of which is
    redundant". An editor that ignores this keeps drawing lines over finished work, and
    an autorouter that ignores it happily lays a second trace beside the first.
  - The count is honest. ``len(links)`` is the number of connections still to make, so
    it can be shown to a user and trusted, and "zero links left" genuinely means the
    net is closed. It is a spanning tree, so n groups always yield exactly n-1 links.

A pin the schematic names but the board cannot locate -- an unplaced component, an
unresolvable footprint, a pin number the footprint does not have -- is reported in
``unresolved_pins`` rather than dropped. Nothing about a pin that isn't there can be
routed, but silently omitting it would understate the remaining work; LVS raises the
matching issue, and this keeps the two accounts consistent.

WHAT IS DRAWN IS NOT QUITE WHAT IS ROUTED. A link runs pin to pin, because a router needs a
pin to start from. The line the board view draws (``ratsnest_lines``) runs between the
nearest COPPER of the two groups instead, so a wire whose end was dragged off a pad points
from that pad to the wire's free end two holes away, not to the far pad the wire still
reaches. The same groups and the same count; only the drawn ends move.

Pure and deterministic: no I/O, no clock, no randomness. Ties in the spanning tree are
broken by pin identity, so the same board always produces the same links in the same
order.
"""

from __future__ import annotations

from dataclasses import dataclass

from .connectivity import FootprintLookup, PhysicalPinRef, extract_physical_nets
from .geometry import path_length_mm, pin_hole
from .model import Board, ComponentInstance, HoleCoord, Net, NetClass, NetId, PerfDocument

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RatsnestLink:
    """One connection that still needs making, between two specific pins.

    The pins are the closest pair spanning the two groups being joined, not arbitrary
    representatives: a router handed this link has the shortest available crossing.
    """

    net_id: NetId
    net_name: str
    net_class: NetClass
    a: PhysicalPinRef
    b: PhysicalPinRef
    #: Holes the two pins occupy. Trailing underscore: ``from`` is a Python keyword.
    from_: HoleCoord
    to: HoleCoord
    #: Straight-line distance, for ordering work and for a "total wire left" readout.
    length_mm: float


@dataclass(frozen=True, slots=True)
class NetRatsnest:
    net_id: NetId
    net_name: str
    net_class: NetClass
    #: Spanning tree over the net's not-yet-joined groups: n groups give n-1 links.
    links: tuple[RatsnestLink, ...]
    #: Every hole this net's locatable pins occupy, sorted. This is the net's own ground:
    #: a router may run a rail straight through these (that is how a rail picks its pins
    #: up) and must not charge proximity risk for passing beside them, since a stray
    #: bridge to a pin of the same net is harmless. See ``router.RouteRequest.net_holes``.
    pin_holes: tuple[HoleCoord, ...]
    #: Pins the schematic declares that cannot be located on the board at all.
    unresolved_pins: tuple[PhysicalPinRef, ...]
    #: How many distinct physical nets the net's locatable pins currently occupy.
    #: 1 means closed, 0 means it has no locatable pins.
    group_count: int


@dataclass(frozen=True, slots=True)
class RatsnestLine:
    """One remaining connection as the board view draws it: from the nearest copper of one
    group to the nearest copper of the other.

    Not a ``RatsnestLink``: an end may be a wire's free end or a hole along a solder run,
    where no pin is, and nothing routes from a line. A net has as many lines as links.
    """

    net_id: NetId
    net_name: str
    net_class: NetClass
    from_: HoleCoord
    to: HoleCoord
    length_mm: float


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ResolvedPin:
    pin: PhysicalPinRef
    hole: HoleCoord
    physical_net_id: str


def ratsnest(doc: PerfDocument, lookup: FootprintLookup) -> tuple[NetRatsnest, ...]:
    """The remaining connections, one entry per schematic net, in ``doc.nets`` order.

    Nets that are already closed are still returned, with an empty ``links`` -- a caller
    showing "3 of 11 nets left" needs the total as much as the remainder, and filtering
    is one comprehension away.
    """
    where = _PinIndex.of(doc, lookup)
    return tuple(_net_ratsnest(net, where, doc, lookup) for net in doc.nets)


def net_ratsnest(doc: PerfDocument, lookup: FootprintLookup, net_id: NetId) -> NetRatsnest | None:
    """``ratsnest`` for ONE net, or None when the document has no net by that id.

    The same entry the whole-board call returns for it -- a net's links depend on where
    its own pins stand and nothing else -- without working out every other net's on the
    way. The autorouter asks for one net at a time, after every connection it lays, and
    asking for all of them was a fifth of the time it took to route a large board.
    """
    net = next((candidate for candidate in doc.nets if candidate.id == net_id), None)
    if net is None:
        return None
    return _net_ratsnest(net, _PinIndex.of(doc, lookup), doc, lookup)


@dataclass(frozen=True, slots=True)
class _PinIndex:
    """Which physical net each pin sits in, and which component a reference names."""

    physical_net_of: dict[tuple[str, str], str]
    components_by_ref: dict[str, ComponentInstance]
    #: The holes where each physical net's copper makes contact, for ``ratsnest_lines``
    #: only. Empty unless asked for: the autorouter builds this index after every
    #: connection it lays.
    contact_holes_of: dict[str, frozenset[HoleCoord]]

    @staticmethod
    def of(doc: PerfDocument, lookup: FootprintLookup, *, copper: bool = False) -> _PinIndex:
        physical_net_of: dict[tuple[str, str], str] = {}
        contact_holes_of: dict[str, frozenset[HoleCoord]] = {}
        for pn in extract_physical_nets(doc, lookup):
            for pin in pn.pins:
                physical_net_of[(pin.component_ref, pin.pin)] = pn.id
            if copper:
                contact_holes_of[pn.id] = frozenset(node.hole for node in pn.nodes)
        # First component wins on a duplicate ref, matching lvs.run_lvs -- the two must
        # agree about which hardware a schematic ref refers to or their reports contradict.
        components_by_ref: dict[str, ComponentInstance] = {}
        for component in doc.components:
            components_by_ref.setdefault(component.ref, component)
        return _PinIndex(
            physical_net_of=physical_net_of,
            components_by_ref=components_by_ref,
            contact_holes_of=contact_holes_of,
        )


def _net_ratsnest(
    net: Net, where: _PinIndex, doc: PerfDocument, lookup: FootprintLookup
) -> NetRatsnest:
    resolved, unresolved = _resolve(net, where, lookup)
    groups = _group_by_physical_net(resolved)
    links = _spanning_links(net.id, net.name, net.net_class, groups, doc)

    pin_holes = sorted({(entry.hole.col, entry.hole.row) for entry in resolved})
    return NetRatsnest(
        net_id=net.id,
        net_name=net.name,
        net_class=net.net_class,
        links=links,
        pin_holes=tuple(HoleCoord(col=col, row=row) for col, row in pin_holes),
        unresolved_pins=tuple(sorted(unresolved)),
        group_count=len(groups),
    )


def _resolve(
    net: Net, where: _PinIndex, lookup: FootprintLookup
) -> tuple[list[_ResolvedPin], list[PhysicalPinRef]]:
    """The net's pins the board can locate, each with its hole and physical net, and the
    ones it cannot."""
    resolved: list[_ResolvedPin] = []
    unresolved: list[PhysicalPinRef] = []

    for node in net.nodes:
        ref = PhysicalPinRef(component_ref=node.component_ref, pin=node.pin)
        placed = where.components_by_ref.get(ref.component_ref)
        footprint = lookup(placed.footprint_id) if placed is not None else None
        hole = (
            pin_hole(placed, footprint, ref.pin)
            if placed is not None and footprint is not None
            else None
        )
        physical_net_id = where.physical_net_of.get((ref.component_ref, ref.pin))
        if hole is None or physical_net_id is None:
            unresolved.append(ref)
            continue
        resolved.append(_ResolvedPin(pin=ref, hole=hole, physical_net_id=physical_net_id))
    return resolved, unresolved


def _group_by_physical_net(resolved: list[_ResolvedPin]) -> list[list[_ResolvedPin]]:
    """Bucket a net's pins by the physical net each already belongs to.

    Buckets are ordered by their lowest-sorting pin, and each bucket's members likewise,
    so the spanning tree below starts from the same place every run.
    """
    buckets: dict[str, list[_ResolvedPin]] = {}
    for entry in resolved:
        buckets.setdefault(entry.physical_net_id, []).append(entry)
    groups = [sorted(members, key=lambda e: e.pin) for members in buckets.values()]
    groups.sort(key=lambda members: members[0].pin)
    return groups


#: The cheapest known crossing from the growing tree to one outside group:
#: (length, nearer pin in the tree, pin in the outside group, and their two holes).
#: Ordered so a plain tuple comparison ranks by distance and then by pin identity.
_Crossing = tuple[float, PhysicalPinRef, PhysicalPinRef, HoleCoord, HoleCoord]


def _closest_crossing(
    tree_group: list[_ResolvedPin], other_group: list[_ResolvedPin], board: Board
) -> _Crossing:
    """Shortest pin-to-pin crossing between two groups, ties broken by pin identity."""
    best: _Crossing | None = None
    for a in tree_group:
        for b in other_group:
            candidate: _Crossing = (
                path_length_mm((a.hole, b.hole), board),
                a.pin,
                b.pin,
                a.hole,
                b.hole,
            )
            if best is None or candidate[:3] < best[:3]:
                best = candidate
    assert best is not None  # Every group holds at least one pin by construction.
    return best


def _spanning_links(
    net_id: NetId,
    net_name: str,
    net_class: NetClass,
    groups: list[list[_ResolvedPin]],
    doc: PerfDocument,
) -> tuple[RatsnestLink, ...]:
    """Prim's algorithm over the groups, joining each by its closest crossing pin pair.

    Prim's rather than Kruskal's because the graph is complete over the groups, so there
    is nothing to gain from sorting edges, and growing one tree keeps the emitted order
    stable and readable: each link attaches the next-nearest group to the work already
    planned.

    The cheapest crossing to each outside group is CACHED and refreshed only against the
    group that just joined, which is what keeps this O(groups^2) pair comparisons overall
    instead of recomputing every crossing on every round. That matters on exactly the
    nets where it is easiest to notice: a thirty-pin unrouted ground net starts out as
    thirty separate groups.
    """
    if len(groups) < 2:
        return ()

    board = doc.board
    links: list[RatsnestLink] = []
    # Group 0 seeds the tree; the rest start out measured against it.
    best_to: dict[int, _Crossing] = {
        index: _closest_crossing(groups[0], groups[index], board) for index in range(1, len(groups))
    }

    while best_to:
        chosen = min(best_to, key=lambda index: best_to[index][:3])
        length, pin_a, pin_b, hole_a, hole_b = best_to.pop(chosen)
        links.append(
            RatsnestLink(
                net_id=net_id,
                net_name=net_name,
                net_class=net_class,
                a=pin_a,
                b=pin_b,
                from_=hole_a,
                to=hole_b,
                length_mm=length,
            )
        )
        for index, current in best_to.items():
            crossing = _closest_crossing(groups[chosen], groups[index], board)
            if crossing[:3] < current[:3]:
                best_to[index] = crossing

    return tuple(links)


# ---------------------------------------------------------------------------
# Lines, for the board view
# ---------------------------------------------------------------------------

#: How a place a line may end ranks in a tie: a pin of the net is (0, ref, pin), any other
#: contact (1, "", ""). Between equal lengths a pin wins, so a board whose groups touch no
#: copper but their own pins draws exactly its links.
_Rank = tuple[int, str, str]
_End = tuple[HoleCoord, _Rank]
#: (length, the end in the tree, the end outside it, then their holes for a total order).
_LineKey = tuple[float, _Rank, _Rank, int, int, int, int]
_LineCrossing = tuple[_LineKey, HoleCoord, HoleCoord]


def ratsnest_lines(doc: PerfDocument, lookup: FootprintLookup) -> tuple[RatsnestLine, ...]:
    """Every remaining connection as the board view draws it, in ``doc.nets`` order.

    The same groups as ``ratsnest`` and as many lines as it has links, but each line is
    measured between every hole where a group's copper makes contact -- its pins, a
    wire's two ends, every hole along a solder run -- and not only between its pins. A
    hole a wire merely lies over is not a contact, so no line ends there. This is for the
    eye only: the autorouter, the MCP server and every count and length still read
    ``ratsnest``, whose links run pin to pin.
    """
    where = _PinIndex.of(doc, lookup, copper=True)
    lines: list[RatsnestLine] = []
    for net in doc.nets:
        resolved, _ = _resolve(net, where, lookup)
        groups = _group_by_physical_net(resolved)
        if len(groups) < 2:
            continue
        ends = [_contact_ends(group, where) for group in groups]
        for length, hole_a, hole_b in _spanning_lines(ends, doc.board):
            lines.append(
                RatsnestLine(
                    net_id=net.id,
                    net_name=net.name,
                    net_class=net.net_class,
                    from_=hole_a,
                    to=hole_b,
                    length_mm=length,
                )
            )
    return tuple(lines)


def _contact_ends(group: list[_ResolvedPin], where: _PinIndex) -> list[_End]:
    """Where a line may end on one group: its pins, then the rest of its copper's
    contacts, each hole once."""
    rank: dict[HoleCoord, _Rank] = {}
    for entry in group:
        key = (0, entry.pin.component_ref, entry.pin.pin)
        if entry.hole not in rank or key < rank[entry.hole]:
            rank[entry.hole] = key
    for contact in where.contact_holes_of.get(group[0].physical_net_id, frozenset()):
        rank.setdefault(contact, (1, "", ""))
    return sorted(rank.items(), key=lambda end: (end[1], end[0].col, end[0].row))


def _closest_line(tree_ends: list[_End], other_ends: list[_End], board: Board) -> _LineCrossing:
    best: _LineCrossing | None = None
    for hole_a, key_a in tree_ends:
        for hole_b, key_b in other_ends:
            order: _LineKey = (
                path_length_mm((hole_a, hole_b), board),
                key_a,
                key_b,
                hole_a.col,
                hole_a.row,
                hole_b.col,
                hole_b.row,
            )
            if best is None or order < best[0]:
                best = (order, hole_a, hole_b)
    assert best is not None  # Every group holds at least one pin by construction.
    return best


def _spanning_lines(
    ends: list[list[_End]], board: Board
) -> list[tuple[float, HoleCoord, HoleCoord]]:
    """``_spanning_links``' Prim's, cached the same way, over contact holes instead of pins."""
    out: list[tuple[float, HoleCoord, HoleCoord]] = []
    best_to: dict[int, _LineCrossing] = {
        index: _closest_line(ends[0], ends[index], board) for index in range(1, len(ends))
    }
    while best_to:
        chosen = min(best_to, key=lambda index: best_to[index][0])
        order, hole_a, hole_b = best_to.pop(chosen)
        out.append((order[0], hole_a, hole_b))
        for index, current in best_to.items():
            crossing = _closest_line(ends[chosen], ends[index], board)
            if crossing[0] < current[0]:
                best_to[index] = crossing
    return out


# ---------------------------------------------------------------------------
# Summaries, for a status bar or a CLI line
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RatsnestSummary:
    nets: int
    #: Nets whose locatable pins are already one physical net.
    closed_nets: int
    links: int
    total_length_mm: float
    unresolved_pins: int


def summarize(nets: tuple[NetRatsnest, ...]) -> RatsnestSummary:
    """Counts for a one-line readout. A net with no locatable pins is not 'closed'."""
    return RatsnestSummary(
        nets=len(nets),
        closed_nets=sum(1 for n in nets if n.group_count == 1),
        links=sum(len(n.links) for n in nets),
        total_length_mm=sum(link.length_mm for n in nets for link in n.links),
        unresolved_pins=sum(len(n.unresolved_pins) for n in nets),
    )


def all_links(nets: tuple[NetRatsnest, ...]) -> tuple[RatsnestLink, ...]:
    """Every remaining connection, flattened. Convenience for overlay drawing."""
    return tuple(link for net in nets for link in net.links)
