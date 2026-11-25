"""The sheet arranged the way a person draws it: blocks, flow, and short wires.

The first derived sheet laid symbols in a grid of cells and ran every wire in the channels
between them. That never crossed a symbol, and it was also why a microcontroller's
crystal, its reset parts and its driver ended up wherever the grid had a free cell, joined
to the chip by a pair of net names: 30 of atmega328-relay's 35 printed names were such
pairs at U1's pins. This module replaced it.

This module answers the question a person answers before drawing anything -- what belongs
next to what -- and writes the answer as an ordinary hand-drawn sheet: a
``SymbolPlacement`` per part and a ``SheetWire`` per short connection, so everything it
produces can be moved, turned and rewired like anything drawn by hand.

- **Hubs** are the chips: an IC or a box with many pins. Everything else is grouped by the
  signal nets between non-hub parts into **clusters**, each attached to the hub pins its
  nets reach -- the crystal and its load capacitors on XTAL1/XTAL2, the reset network on
  RESET, a driver chain on the pin that drives it.
- **A cluster sits on the side of its hub its pins are on**, in columns going outward by
  how many parts away from the chip each part is, and **connectors at the edges**.
- **A cluster no hub reaches** (the power input, an indicator LED) flows left to right in
  a band above the hub, from its connector.
- **Supplies point up and grounds down.** Every part is turned to the one of its eight
  orientations that best points each pin where it wants to go: a supply pin up, a ground
  pin down, a signal pin towards the part it connects to.
- **A net inside one block is wired, a net between blocks is named.** Wires are laid with
  ``schematic.route_sheet_wire``, shortest nets first, and one whose route is far longer
  than the gap it crosses is left to the names.

Pure, like every module outside ``ui/``: same document in, same arrangement out, ties broken
by reference.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .connectivity import FootprintLookup
from .model import (
    NetNode,
    PerfDocument,
    Point2,
    PortLink,
    Rotation,
    SheetPort,
    SheetPortKind,
    SheetWire,
    SymbolPlacement,
)
from .schematic import (
    DEFAULT_SCHEMATIC_OPTIONS,
    GRID_MM,
    Rail,
    SchematicDrawing,
    SchematicOptions,
    Symbol,
    Wire,
    _collect_symbols,
    _orient_body,
    _part_labels,
    _part_text_width,
    _Placed,
    _rail_names,
    _ref_sort_key,
    _resolve_nets,
    _ResolvedNet,
    port_stub,
    route_sheet_wire,
)
from .schsymbols import PinSide, SymbolBody, SymbolKind, SymbolPin
from .system import every_component

#: A chip the sheet is arranged around: an IC, or a box with this many pins or more.
HUB_MIN_PINS = 6

#: Kinds that are drawn upright whatever their pins want: their text and their pin rows
#: read one way. A chip or a box may still be mirrored.
_UPRIGHT: frozenset[SymbolKind] = frozenset({"ic", "box", "relay", "switch"})

#: Kinds whose pins stay in a row across the page: turned end over end, or mirrored, so
#: their pin order can follow the pins they are wired to.
_LEVEL: frozenset[SymbolKind] = frozenset({"connector", "jack"})

#: Kinds that sit at the edge of the sheet, where the board meets the world.
_EDGE: frozenset[SymbolKind] = frozenset({"connector", "jack", "battery"})

#: Free grid steps between the hub and its first column, between two columns, and between
#: two parts stacked in one column. Room for the wires, and for the reference and value.
HUB_GAP = 10
COLUMN_GAP = 8
STACK_GAP = 3
BAND_GAP = 8

#: Free grid steps between two parts of a ladder: room for the wire that joins there.
LADDER_GAP = 4

#: Grid steps a supply or ground glyph takes past the pin it hangs from.
GLYPH_ROOM = 4
#: Grid squares a supply's stub and name take beside a side pin.
RAIL_LABEL_ROOM = 5
#: Grid squares a connector's reference takes over it, and its value under it.
CONNECTOR_TEXT_ROOM = 2

#: A wire whose route is longer than this many times the gap between its pins, plus the
#: slack, is not drawn: the net is named at the pin instead.
DETOUR_FACTOR = 2.5
DETOUR_SLACK_MM = 25.0

_OPPOSITE: dict[PinSide, PinSide] = {
    "left": "right", "right": "left", "top": "bottom", "bottom": "top"
}


@dataclass(frozen=True, slots=True)
class Arrangement:
    """Where every part goes, and the wires laid between them."""

    placements: tuple[SymbolPlacement, ...]
    wires: tuple[SheetWire, ...]
    ports: tuple[SheetPort, ...]


@dataclass(slots=True)
class _Part:
    ref: str
    placed: _Placed
    hub: bool = False
    cluster: int = -1
    depth: int = 0
    column: tuple[int, int] = (0, 0)
    rotation: Rotation = 0
    mirrored: bool = False
    body: SymbolBody | None = None
    x: float = 0.0
    y: float = 0.0
    done: bool = False

    @property
    def kind(self) -> SymbolKind:
        return self.placed.kind

    @property
    def shape(self) -> SymbolBody:
        return self.body if self.body is not None else self.placed.body

    def pin(self, number: str) -> SymbolPin:
        return next(pin for pin in self.shape.pins if pin.number == number)

    def anchor(self, number: str) -> Point2:
        pin = self.pin(number)
        return Point2(self.x + pin.at.x, self.y + pin.at.y)


def _grid(value: float) -> float:
    return round(value / GRID_MM) * GRID_MM


def _turned_cost(
    body: SymbolBody, rotation: Rotation, mirrored: bool, wants: dict[str, tuple[PinSide, float]]
) -> tuple[float, SymbolBody]:
    turned = _orient_body(body, rotation, mirrored)
    cost = 0.0
    for pin in turned.pins:
        want = wants.get(pin.number)
        if want is None:
            continue
        side, weight = want
        if pin.side == side:
            continue
        cost += weight * (2.0 if pin.side == _OPPOSITE[side] else 1.0)
    # Upright and unmirrored where nothing is lost by it.
    cost += (0.01 if rotation else 0.0) + (0.02 if mirrored else 0.0)
    return cost, turned


def _orient(
    part: _Part,
    wants: dict[str, tuple[PinSide, float]],
    targets: dict[str, float] | None = None,
) -> None:
    """Turn ``part`` the way its pins want to point, and, among the turns that do, the one
    whose pins come in the order of the placed pins they are wired to (``targets``, pin ->
    the height of what it joins), so the wires between them do not cross."""
    if part.kind in _UPRIGHT:
        rotations: tuple[Rotation, ...] = (0,)
    elif part.kind in _LEVEL:
        rotations = (0, 180)
    else:
        rotations = (0, 90, 180, 270)
    best: tuple[float, int, Rotation, bool, SymbolBody] | None = None
    for index, (rotation, mirrored) in enumerate(
        (r, m) for m in (False, True) for r in rotations
    ):
        cost, turned = _turned_cost(part.placed.body, rotation, mirrored, wants)
        if targets:
            heights = {pin.number: pin.at.y for pin in turned.pins if pin.number in targets}
            order = sorted(heights)
            cost += 0.5 * sum(
                1
                for i, a in enumerate(order)
                for b in order[i + 1:]
                if (heights[a] - heights[b]) * (targets[a] - targets[b]) < 0
            )
        if best is None or (cost, index) < best[:2]:
            best = (cost, index, rotation, mirrored, turned)
    assert best is not None
    part.rotation, part.mirrored, part.body = best[2], best[3], best[4]


class _Layout:
    def __init__(
        self, doc: PerfDocument, lookup: FootprintLookup, options: SchematicOptions
    ) -> None:
        notes: list[str] = []
        self.doc = doc
        self.options = options
        self.symbols = _collect_symbols(doc, lookup, notes)
        self.resolved: list[_ResolvedNet] = _resolve_nets(doc, self.symbols, notes, options)
        self.parts = {
            ref: _Part(ref=ref, placed=placed)
            for ref, placed in sorted(self.symbols.items(), key=lambda kv: _ref_sort_key(kv[0]))
        }
        #: (ref, pin) -> the net it is on.
        self.net_of: dict[tuple[str, str], _ResolvedNet] = {}
        for item in self.resolved:
            for ref, pin in item.pins:
                self.net_of[(ref, pin.number)] = item
        for part in self.parts.values():
            pins = part.placed.body.pins
            part.hub = part.kind in ("ic", "box") and len(pins) >= HUB_MIN_PINS
        self.hubs = [p for p in self.parts.values() if p.hub]
        self.hubs.sort(key=lambda p: (-len(p.placed.body.pins), _ref_sort_key(p.ref)))

    # -- what is joined to what --------------------------------------------

    def signal_nets(self) -> list[_ResolvedNet]:
        return [item for item in self.resolved if not item.rail and len(item.pins) > 1]

    def refs_on(self, item: _ResolvedNet) -> list[str]:
        seen: list[str] = []
        for ref, _pin in item.pins:
            if ref not in seen:
                seen.append(ref)
        return seen

    def rail_want(self, ref: str, number: str) -> tuple[PinSide, float] | None:
        item = self.net_of.get((ref, number))
        if item is None or not item.rail:
            return None
        return ("bottom", 2.0) if item.net.net_class == "ground" else ("top", 2.0)

    def is_shunt(self, part: _Part) -> bool:
        """Two pins, one on a rail: a part hung between a signal and a supply."""
        pins = part.placed.body.pins
        if len(pins) != 2:
            return False
        rails = [self.rail_want(part.ref, pin.number) is not None for pin in pins]
        return rails.count(True) == 1

    def clusters(self) -> list[list[str]]:
        parent = {ref: ref for ref in self.parts}

        def find(ref: str) -> str:
            while parent[ref] != ref:
                parent[ref] = parent[parent[ref]]
                ref = parent[ref]
            return ref

        for item in self.signal_nets():
            members = [ref for ref in self.refs_on(item) if not self.parts[ref].hub]
            for other in members[1:]:
                a, b = find(members[0]), find(other)
                if a != b:
                    parent[max(a, b, key=_ref_sort_key)] = min(a, b, key=_ref_sort_key)
        groups: dict[str, list[str]] = defaultdict(list)
        for ref, part in self.parts.items():
            if not part.hub:
                groups[find(ref)].append(ref)
        return sorted(
            (sorted(group, key=_ref_sort_key) for group in groups.values()),
            key=lambda group: _ref_sort_key(group[0]),
        )

    def hub_pins_of(self, group: Sequence[str]) -> list[tuple[_Part, SymbolPin]]:
        """The hub pins a cluster's signal nets reach."""
        members = set(group)
        found: list[tuple[_Part, SymbolPin]] = []
        for item in self.signal_nets():
            refs = self.refs_on(item)
            if not members.intersection(refs):
                continue
            for ref, pin in item.pins:
                if self.parts[ref].hub:
                    found.append((self.parts[ref], pin))
        return found

    def depths(self, group: Sequence[str], sources: Iterable[str]) -> dict[str, int]:
        """Steps from the sources, over signal nets inside the group."""
        members = set(group)
        depth = {ref: 1 for ref in sources if ref in members}
        frontier = sorted(depth, key=_ref_sort_key)
        while frontier:
            following: list[str] = []
            for ref in frontier:
                for item in self.signal_nets():
                    refs = self.refs_on(item)
                    if ref not in refs:
                        continue
                    for other in refs:
                        if other in members and other not in depth:
                            depth[other] = depth[ref] + 1
                            following.append(other)
            frontier = sorted(following, key=_ref_sort_key)
        for ref in group:
            depth.setdefault(ref, 1)
        return depth

    # -- turning ---------------------------------------------------------------

    def wants(self, part: _Part, inward: PinSide) -> dict[str, tuple[PinSide, float]]:
        """Where each pin of ``part`` wants to point, in a block flowing away from
        ``inward``: a supply up, a ground down, a signal towards whatever it joins."""
        out: dict[str, tuple[PinSide, float]] = {}
        for pin in part.placed.body.pins:
            rail = self.rail_want(part.ref, pin.number)
            if rail is not None:
                if part.kind not in _EDGE:
                    out[pin.number] = rail
                continue
            item = self.net_of.get((part.ref, pin.number))
            if item is None or len(item.pins) < 2:
                continue
            others = [self.parts[r] for r in self.refs_on(item) if r != part.ref]
            if any(o.hub or o.depth < part.depth for o in others):
                out[pin.number] = (inward, 1.0)
            elif others and all(o.depth > part.depth for o in others):
                out[pin.number] = (_OPPOSITE[inward], 1.0)
        bridge = self.bridged(part)
        if bridge:
            # A crystal between XTAL1 and XTAL2: stood up between the two, the upper pin to
            # the upper one.
            ordered = sorted(bridge, key=lambda number: (bridge[number], number))
            out[ordered[0]] = ("top", 1.5)
            out[ordered[-1]] = ("bottom", 1.5)
        return out

    def bridged(self, part: _Part) -> dict[str, float]:
        """For a part whose every signal pin is wired straight to one hub's pins on one
        side, pin -> the height of that hub pin; otherwise empty."""
        reached: dict[str, dict[tuple[str, PinSide], float]] = {}
        for pin in part.placed.body.pins:
            item = self.net_of.get((part.ref, pin.number))
            if item is None or item.rail or len(item.pins) < 2:
                continue
            here: dict[tuple[str, PinSide], float] = {}
            for ref, hub_pin in item.pins:
                hub = self.parts[ref]
                if hub.hub:
                    key = (ref, hub.pin(hub_pin.number).side)
                    here.setdefault(key, hub.anchor(hub_pin.number).y)
            if not here:
                return {}
            reached[pin.number] = here
        if len(reached) < 2:
            return {}
        common = set.intersection(*(set(here) for here in reached.values()))
        if not common:
            return {}
        side = min(common)
        return {number: here[side] for number, here in reached.items()}

    def targets(self, part: _Part) -> dict[str, float]:
        """Pin -> the height of the placed pin it is wired to, for every such pin."""
        out: dict[str, float] = {}
        for pin in part.placed.body.pins:
            item = self.net_of.get((part.ref, pin.number))
            if item is None or item.rail:
                continue
            heights = [
                self.parts[r].anchor(q.number).y
                for r, q in item.pins
                if r != part.ref and self.parts[r].done
            ]
            if heights:
                out[pin.number] = min(heights)
        return out

    # -- placing ------------------------------------------------------------

    def target_of(self, part: _Part) -> tuple[SymbolPin, Point2] | None:
        """A pin of ``part`` and the placed pin it joins, nearest the source first."""
        best: tuple[int, str, SymbolPin, Point2] | None = None
        for pin in part.shape.pins:
            item = self.net_of.get((part.ref, pin.number))
            if item is None or item.rail:
                continue
            for ref, other in item.pins:
                placed = self.parts[ref]
                if ref == part.ref or not placed.done:
                    continue
                rank = (0 if placed.hub else placed.depth, ref)
                if best is None or rank < best[:2]:
                    best = (rank[0], rank[1], pin, placed.anchor(other.number))
        return None if best is None else (best[2], best[3])

    def glyph_room(self, part: _Part) -> tuple[float, float]:
        """How far a supply glyph or a vertical signal exit needs above and below ``part``."""
        above = below = 0.0
        for pin in part.shape.pins:
            is_rail = self.rail_want(part.ref, pin.number) is not None
            room = GLYPH_ROOM * GRID_MM if is_rail else 2 * GRID_MM
            if pin.side == "top":
                above = max(above, room)
            elif pin.side == "bottom":
                below = max(below, room)
        return above, below

    def level_with(self, part: _Part) -> tuple[float, int] | None:
        """The top that puts the most of ``part``'s side pins level with the placed pins
        they are wired to, and how many align there, when two or more do: a header beside
        a port reads as straight lines only if the whole row lines up, not just its first
        pin."""
        offsets: list[float] = []
        for pin in part.shape.pins:
            if pin.side not in ("left", "right"):
                continue
            item = self.net_of.get((part.ref, pin.number))
            if item is None or item.rail:
                continue
            for ref, other in item.pins:
                if ref != part.ref and self.parts[ref].done:
                    offsets.append(round(self.parts[ref].anchor(other.number).y - pin.at.y, 3))
        if len(offsets) < 2:
            return None
        counts: dict[float, int] = defaultdict(int)
        for offset in offsets:
            counts[offset] += 1
        best = min(counts, key=lambda offset: (-counts[offset], offset))
        if counts[best] < 2:
            return None
        return best, counts[best]

    def stack(self, column: list[_Part], x_of: dict[str, float], floor: float) -> None:
        """Put one column's parts down, each level with the pin it joins where it can be."""
        desired: list[tuple[float, str, _Part, int]] = []
        for part in column:
            target = self.target_of(part)
            body = part.shape
            level = self.level_with(part)
            aligned = 0
            if level is not None:
                y, aligned = level
            elif target is None:
                y = floor
            else:
                pin, at = target
                if pin.side in ("left", "right"):
                    y = at.y - pin.at.y
                elif pin.side == "top":
                    y = at.y + 2 * GRID_MM
                else:
                    y = at.y - body.height - 2 * GRID_MM
            desired.append((_grid(y), part.ref, part, aligned))
        desired.sort(key=lambda d: (d[0], _ref_sort_key(d[1])))
        # Two parts that want one place give way in proportion: a multi-pin header whose
        # pins line up straight with its hub keeps its level ahead of a single-wire part
        # whose one lead can jog cleanly (weighted isotonic regression, pooled adjacent).
        offsets: list[float] = []
        cursor = 0.0
        for _y, _ref, part, _aligned in desired:
            above, below = self.glyph_room(part)
            cursor += above
            offsets.append(cursor)
            cursor += part.shape.height + below + STACK_GAP * GRID_MM
        blocks: list[list[float]] = []  # [weight, weighted sum, count]
        for (y, _ref, part, aligned), offset in zip(desired, offsets, strict=True):
            weight = 100.0 * aligned if aligned >= 2 else float(max(1, len(self.targets(part))))
            blocks.append([weight, weight * (y - offset), 1.0])
            while len(blocks) > 1 and blocks[-2][1] / blocks[-2][0] > blocks[-1][1] / blocks[-1][0]:
                w, total, count = blocks.pop()
                blocks[-1][0] += w
                blocks[-1][1] += total
                blocks[-1][2] += count
        index = 0
        for weight, total, count in blocks:
            level_y = _grid(total / weight)
            for _ in range(int(count)):
                _y, _ref, part, _aligned = desired[index]
                part.x, part.y = _grid(x_of[part.ref]), _grid(level_y + offsets[index])
                part.done = True
                index += 1

    def ladders(self, refs: Sequence[str]) -> list[list[tuple[str, str, str]]]:
        """Chains of two-pin parts from a supply down to a ground -- a 555's R1, R2 and C1,
        a divider, a resistor and its LED -- each as (ref, upper pin, lower pin) from the
        top. A person draws one standing up in one column, every join a short wire, so the
        sheet does too. Longest first, then by reference; a part is in one ladder at most."""
        pool = sorted(
            (
                r
                for r in refs
                if not self.parts[r].hub
                and self.parts[r].kind not in _EDGE
                and len(self.parts[r].placed.body.pins) == 2
            ),
            key=_ref_sort_key,
        )

        def net(ref: str, number: str) -> _ResolvedNet | None:
            return self.net_of.get((ref, number))

        def numbers(ref: str) -> tuple[str, str]:
            a, b = self.parts[ref].placed.body.pins
            return a.number, b.number

        found: list[list[tuple[str, str, str]]] = []
        used: set[str] = set()
        while True:
            best: list[tuple[str, str, str]] | None = None

            def walk(chain: list[tuple[str, str, str]], via: _ResolvedNet) -> None:
                nonlocal best
                if len(chain) > 4:
                    return
                for ref in pool:
                    if ref in used or any(ref == c[0] for c in chain):
                        continue
                    a, b = numbers(ref)
                    for upper, lower in ((a, b), (b, a)):
                        if net(ref, upper) is not via:
                            continue
                        below = net(ref, lower)
                        if below is None:
                            continue
                        step = [*chain, (ref, upper, lower)]
                        if below.rail and below.net.net_class == "ground":
                            if best is None or len(step) > len(best):
                                best = step
                        elif not below.rail and len(below.pins) > 1:
                            walk(step, below)

            for ref in pool:
                if ref in used:
                    continue
                a, b = numbers(ref)
                for upper, lower in ((a, b), (b, a)):
                    top, below = net(ref, upper), net(ref, lower)
                    if (
                        top is not None and top.rail and top.net.net_class != "ground"
                        and below is not None and not below.rail and len(below.pins) > 1
                    ):
                        walk([(ref, upper, lower)], below)
            if best is None or len(best) < 2:
                return found
            found.append(best)
            used.update(ref for ref, _u, _l in best)

    def lay_ladder(self, ladder: list[tuple[str, str, str]], x: float, near: float) -> float:
        """Stand ``ladder`` up in a column at ``x``, its joins level with the hub pins they
        are wired to where it can, or its top at ``near``. Returns the column's width."""
        parts = [self.parts[ref] for ref, _u, _l in ladder]
        for part, (_ref, upper, lower) in zip(parts, ladder, strict=True):
            _orient(part, {upper: ("top", 3.0), lower: ("bottom", 3.0)})
        width = max(p.shape.width for p in parts)
        tops: list[float] = []
        cursor = 0.0
        for part in parts:
            tops.append(cursor)
            cursor += part.shape.height + LADDER_GAP * GRID_MM
        wanted: list[float] = []
        for index in range(len(parts) - 1):
            ref, _upper, lower = ladder[index]
            item = self.net_of[(ref, lower)]
            join = tops[index] + parts[index].shape.height + LADDER_GAP * GRID_MM / 2
            for r, pin in item.pins:
                if self.parts[r].hub and self.parts[r].done:
                    wanted.append(self.parts[r].anchor(pin.number).y - join)
        start = sum(wanted) / len(wanted) if wanted else near
        for part, top in zip(parts, tops, strict=True):
            part.x = _grid(x + (width - part.shape.width) / 2)
            part.y = _grid(start + top)
            part.done = True
        return width

    def lay_side(self, hub: _Part, side: PinSide, groups: list[list[str]]) -> None:
        """Clusters on one side of a hub, in columns going outward."""
        inward = _OPPOSITE[side]
        parts: list[_Part] = []
        for group in groups:
            sources = [
                ref
                for ref in group
                if any(
                    self.parts[r].hub
                    for item in self.signal_nets()
                    if ref in self.refs_on(item)
                    for r in self.refs_on(item)
                )
            ]
            depth = self.depths(group, sources)
            deepest = max(depth.values())
            for ref in group:
                part = self.parts[ref]
                part.depth = depth[ref]
                if part.kind in _EDGE and part.depth < deepest + 1 and len(group) > 1:
                    part.depth = deepest + 1
                parts.append(part)
        if not parts:
            return
        ladders = self.ladders([p.ref for p in parts])
        in_ladder = {ref for ladder in ladders for ref, _u, _l in ladder}
        for part in parts:
            part.column = (
                part.depth, -1 if self.bridged(part) else 0 if self.is_shunt(part) else 1
            )
        columns: dict[tuple[int, int], list[_Part]] = defaultdict(list)
        for part in parts:
            if part.ref not in in_ladder:
                columns[part.column].append(part)
        if side == "left":
            reach = hub.x - HUB_GAP * GRID_MM
        else:
            reach = hub.x + hub.shape.width + HUB_GAP * GRID_MM
        # Ladders nearest the chip: their joins are what its pins are wired to.
        for ladder in ladders:
            widest = max(self.parts[ref].placed.body.height for ref, _u, _l in ladder)
            x = reach - widest if side == "left" else reach
            width = self.lay_ladder(ladder, x, hub.y)
            if side == "left" and width != widest:
                for ref, _u, _l in ladder:
                    self.parts[ref].x = _grid(self.parts[ref].x + widest - width)
            reach = reach - width - COLUMN_GAP * GRID_MM if side == "left" else (
                reach + width + COLUMN_GAP * GRID_MM
            )
        #: How far the last column's side labels run past its right edge.
        overhang = 0.0
        for key in sorted(columns):
            column = columns[key]
            for part in column:
                _orient(part, self.wants(part, inward), self.targets(part))
            if side == "right" and any(
                pin.side == "left" and self.rail_want(part.ref, pin.number) is not None
                for part in column
                for pin in part.shape.pins
            ):
                # A supply drawn off a left-hand pin points back at the last column, where a
                # part stood on end prints its reference and value past its right edge: on
                # atmega328-relay D2's "1N4148" was printed on the "+5V" at K1's coil once U1
                # was drawn by what its pins do and the columns moved up against each other.
                reach += max(0.0, overhang + RAIL_LABEL_ROOM * GRID_MM - COLUMN_GAP * GRID_MM)
            width = max(p.shape.width for p in column)
            x_of = {}
            for part in column:
                # Centred in its column.
                left = reach - width if side == "left" else reach
                x_of[part.ref] = left + (width - part.shape.width) / 2
            self.stack(column, x_of, hub.y)
            overhang = max(
                (x_of[p.ref] + p.shape.width + self.side_label_room(p) - (reach + width)
                 for p in column),
                default=0.0,
            )
            reach = reach - width - COLUMN_GAP * GRID_MM if side == "left" else (
                reach + width + COLUMN_GAP * GRID_MM
            )

    def side_label_room(self, part: _Part) -> float:
        """Horizontal room a turned part's side reference and value need past its right edge."""
        sides = {pin.side for pin in part.shape.pins}
        if (
            not part.shape.pins
            or not (sides <= {"top", "bottom"})
            or part.kind in ("ic", "connector", "box", "relay")
            or part.shape.names_inside
        ):
            return 0.0
        text = _part_text_width(part.placed, self.options)
        # Screen views hold text at a readable pixel floor, so give side labels breathing
        # room past the paper width before the next body starts.
        return _grid(0.75 * GRID_MM + 1.5 * text + 2 * GRID_MM)

    def edge_rail_order(self, part: _Part) -> dict[str, float]:
        """Vertical preference for an edge connector with no placed signal target yet:
        supplies and signals above ground so the ground glyph drops clear underneath."""
        if part.kind not in _EDGE:
            return {}
        has_ground = any(
            (rail := self.rail_want(part.ref, pin.number)) is not None and rail[0] == "bottom"
            for pin in part.placed.body.pins
        )
        if not has_ground:
            return {}
        return {
            pin.number: 1.0
            if (rail := self.rail_want(part.ref, pin.number)) is not None and rail[0] == "bottom"
            else 0.0
            for pin in part.placed.body.pins
        }

    def orient_edge_inward(self, part: _Part, face: PinSide) -> None:
        """Turn a rail-only edge connector so its pins face ``face`` (into the sheet),
        supply above ground."""
        wants = {pin.number: (face, 1.0) for pin in part.placed.body.pins}
        _orient(part, wants, self.edge_rail_order(part))

    def lay_left_power(self, refs: list[str], left: float) -> None:
        """Rail-only power connectors when there is no upper band: on the left edge beside
        the hub they feed, facing right into the circuit, clear of anything below them."""
        hub = self.hubs[0]
        parts = [self.parts[r] for r in refs]
        for part in parts:
            self.orient_edge_inward(part, "right")
        reach = max(p.shape.width for p in parts) + 4 * GRID_MM
        total_h = sum(p.shape.height for p in parts) + max(0, len(parts) - 1) * STACK_GAP * GRID_MM
        # What is already in the strip the connectors stand in, with its glyphs and a gap.
        # They take the free place nearest the hub's top, looking up and down a grid at a
        # time: lifted above EVERYTHING in the strip, as they were, a column of parts left
        # of a tall chip (the NE555 drawn by what its pins do) sent them to the sheet's
        # top-left corner, alone, and made the sheet a fifth taller for it.
        gap = 2 * GRID_MM
        taken = [
            (p.y - self.glyph_room(p)[0] - gap, p.y + p.shape.height + self.glyph_room(p)[1] + gap)
            for p in self.parts.values()
            if p.done and p.x < left + reach and p.x + p.shape.width > left - 2 * GRID_MM
        ]
        # A connector's reference is printed over it and its value under it, so the stack
        # keeps that room too: measured to the body alone, the value sat a grid's width
        # above whatever was below, and on ne555 with its two-pin parts turned over, LED1's
        # ground glyph rose into J1's "Conn_01x02".
        text = CONNECTOR_TEXT_ROOM * GRID_MM

        def clear(top: float) -> bool:
            return all(
                top + total_h + text <= low or top - text >= high for low, high in taken
            )

        y = hub.y
        if not clear(y):
            step = 0
            while True:
                step += 1
                up, down = hub.y - step * GRID_MM, hub.y + step * GRID_MM
                if clear(up):
                    y = up
                    break
                if clear(down):
                    y = down
                    break
        cursor = _grid(y)
        for part in parts:
            part.x, part.y, part.done = _grid(left), _grid(cursor), True
            cursor += part.shape.height + STACK_GAP * GRID_MM

    def lay_band(self, groups: list[list[str]], loose: list[str], top: float, left: float) -> None:
        """Blocks no hub reaches, flowing left to right from their connectors, in a band
        whose bottom is ``top``."""
        reach = left
        laid: list[_Part] = []
        for ref in [r for r in loose if self.parts[r].kind in _EDGE]:
            part = self.parts[ref]
            self.orient_edge_inward(part, "right")
            part.x, part.y, part.done = _grid(reach), 0.0, True
            reach += part.shape.width + COLUMN_GAP * GRID_MM
            laid.append(part)
        loose = [r for r in loose if self.parts[r].kind not in _EDGE]
        for group in groups:
            ladders = self.ladders(group)
            if len(ladders) == 1 and len(ladders[0]) == len(group):
                width = self.lay_ladder(ladders[0], reach, 0.0)
                laid.extend(self.parts[ref] for ref in group)
                reach += width + COLUMN_GAP * GRID_MM
                continue
            sources = [r for r in group if self.parts[r].kind in _EDGE] or [group[0]]
            depth = self.depths(group, sources)
            columns: dict[tuple[int, int], list[_Part]] = defaultdict(list)
            for ref in group:
                part = self.parts[ref]
                part.depth = depth[ref]
                part.column = (part.depth, 0 if self.is_shunt(part) else 1)
                columns[part.column].append(part)
            for key in sorted(columns):
                column = columns[key]
                for part in column:
                    targets = self.targets(part) or self.edge_rail_order(part)
                    _orient(part, self.wants(part, "left"), targets)
                width = max(p.shape.width for p in column)
                x_of = {p.ref: reach + (width - p.shape.width) / 2 for p in column}
                self.stack(column, x_of, 0.0)
                laid.extend(column)
                reach += width + COLUMN_GAP * GRID_MM
        if loose:
            column = [self.parts[r] for r in loose]
            for part in column:
                _orient(part, self.wants(part, "left"))
            x = reach
            for part in column:
                part.x, part.y, part.done = _grid(x), 0.0, True
                x += part.shape.width + COLUMN_GAP * GRID_MM
                laid.append(part)
        if not laid:
            return
        bottom = max(p.y + p.shape.height + self.glyph_room(p)[1] for p in laid)
        shift = _grid(top - BAND_GAP * GRID_MM - bottom)
        for part in laid:
            part.y += shift

    def lay_row(self, refs: list[str], hub: _Part) -> None:
        """Parts on the hub's rails alone, in a row over it: decoupling."""
        x = hub.x
        for index, ref in enumerate(refs):
            part = self.parts[ref]
            _orient(part, self.wants(part, "left"))
            if index > 0 and any(
                pin.side == "left" and self.rail_want(part.ref, pin.number) is not None
                for pin in part.shape.pins
            ):
                x += GLYPH_ROOM * GRID_MM
            _above, below = self.glyph_room(part)
            part.x = _grid(x)
            part.y = _grid(hub.y - part.shape.height - below - 2 * GRID_MM)
            part.done = True
            x += part.shape.width + max(2 * GRID_MM, self.side_label_room(part))

    def arrange(self) -> None:
        groups = self.clusters()
        x = 0.0
        hub_groups: dict[str, dict[PinSide, list[list[str]]]] = {
            h.ref: defaultdict(list) for h in self.hubs
        }
        band: list[list[str]] = []
        loose_rows: dict[str, list[str]] = defaultdict(list)
        band_loose: list[str] = []
        for group in groups:
            pins = self.hub_pins_of(group)
            if not pins:
                signal = any(
                    self.net_of.get((ref, p.number)) is not None
                    and not self.net_of[(ref, p.number)].rail
                    and len(self.net_of[(ref, p.number)].pins) > 1
                    for ref in group
                    for p in self.parts[ref].placed.body.pins
                )
                if signal or not self.hubs:
                    band.append(group)
                    continue
                # On the rails alone: decoupling by the first hub, a reservoir in the band.
                (ref,) = group if len(group) == 1 else (group[0],)
                if self.parts[ref].kind in _EDGE or self.parts[ref].kind == "polarised-capacitor":
                    band_loose.extend(group)
                else:
                    loose_rows[self.hubs[0].ref].extend(group)
                continue
            votes: dict[tuple[str, PinSide], int] = defaultdict(int)
            for hub, pin in pins:
                votes[(hub.ref, pin.side)] += 1
            (hub_ref, side), _n = min(
                votes.items(), key=lambda kv: (-kv[1], _ref_sort_key(kv[0][0]), kv[0][1])
            )
            hub_groups[hub_ref][side].append(group)
        top = 0.0
        for hub in self.hubs:
            hub.x, hub.y, hub.done = _grid(x), 0.0, True
            hub.body = hub.placed.body
            for side in ("left", "right"):
                self.lay_side(hub, side, hub_groups[hub.ref].get(side, []))
            self.lay_row(loose_rows.get(hub.ref, []), hub)
            right = max(
                (p.x + p.shape.width for p in self.parts.values() if p.done), default=x
            )
            x = right + HUB_GAP * GRID_MM
        if self.hubs:
            placed = [p for p in self.parts.values() if p.done]
            top = min(p.y - self.glyph_room(p)[0] for p in placed)
            left = min(p.x for p in placed)
        else:
            left = 0.0
        if not self.hubs and not band and not band_loose:
            pass
        elif (
            not self.hubs
            and len(band) >= 4
            and all(len(g) == 1 for g in band)
            and not band_loose
        ):
            # A board of unconnected or rail-only parts with no hub: pack into a tidy block
            # rather than one long strip across the page.
            parts = [self.parts[g[0]] for g in band]
            for part in parts:
                _orient(part, self.wants(part, "left"))
            cols = max(2, math.ceil(math.sqrt(len(parts))))
            col_w = max(p.shape.width + self.side_label_room(p) for p in parts)
            row_h = max(
                p.shape.height + sum(self.glyph_room(p)) + STACK_GAP * GRID_MM for p in parts
            )
            for idx, part in enumerate(parts):
                col, row = idx % cols, idx // cols
                part.x = _grid(left + col * (col_w + COLUMN_GAP * GRID_MM))
                part.y = _grid(row * row_h)
                part.done = True
        elif (
            self.hubs
            and not band
            and band_loose
            and all(self.parts[r].kind in _EDGE for r in band_loose)
        ):
            self.lay_left_power(band_loose, left)
        else:
            self.lay_band(band, band_loose, top, left)
        # Anything still without a place (a part on nothing at all) goes in a row under.
        rest = [p for p in self.parts.values() if not p.done]
        if rest:
            placed = [p for p in self.parts.values() if p.done]
            y = max((p.y + p.shape.height for p in placed), default=0.0) + BAND_GAP * GRID_MM
            x = min((p.x for p in placed), default=0.0)
            for part in rest:
                _orient(part, {})
                part.x, part.y, part.done = _grid(x), _grid(y), True
                x += part.shape.width + COLUMN_GAP * GRID_MM
        # Into the sheet's own corner.
        min_x = min(p.x for p in self.parts.values())
        min_y = min(p.y for p in self.parts.values())
        margin = 6 * GRID_MM
        for part in self.parts.values():
            part.x = _grid(part.x - min_x + margin)
            part.y = _grid(part.y - min_y + margin)

    # -- wiring -------------------------------------------------------------

    def placements(self) -> tuple[SymbolPlacement, ...]:
        return tuple(
            SymbolPlacement(
                id=self.part_id(part.ref),
                at=Point2(part.x, part.y),
                rotation=part.rotation,
                mirrored=part.mirrored,
            )
            for part in self.parts.values()
        )

    def part_id(self, ref: str) -> str:
        for component in every_component(self.doc):
            if component.ref == ref:
                return component.id
        for part in self.doc.parts:
            if part.ref == ref:
                return part.id
        return ref

    def block_of(self, ref: str, cluster_of: dict[str, int]) -> int:
        return cluster_of.get(ref, -1)

    def wire_up(self) -> tuple[tuple[SheetWire, ...], tuple[SheetPort, ...]]:
        placements = {p.ref: p for p in self.parts.values()}
        for ref, placed in self.symbols.items():
            part = placements[ref]
            placed.body = part.shape
            placed.x, placed.y = part.x, part.y
        ordered = sorted(self.symbols.values(), key=lambda placed: _ref_sort_key(placed.ref))
        drawing = SchematicDrawing(
            symbols=tuple(
                Symbol(
                    ref=placed.ref,
                    value=placed.value,
                    kind=placed.kind,
                    footprint_id=placed.footprint_id,
                    at=Point2(placed.x, placed.y),
                    shapes=placed.body.shapes,
                    pins=placed.body.pins,
                    width=placed.body.width,
                    height=placed.body.height,
                )
                for placed in ordered
            ),
            labels=tuple(_part_labels(ordered, self.options)),
        )
        # Every supply and ground pin gets its glyph as a port of its own, on the stub the
        # sheet draws a rail pin with: a port is what a person puts down, and it can be
        # dragged off the pin and joined to its neighbours'.
        ports: list[SheetPort] = []
        rails: list[Rail] = []
        for item in self.resolved:
            if not item.rail:
                continue
            kind: SheetPortKind = "ground" if item.net.net_class == "ground" else "supply"
            for ref, pin in item.pins:
                path = port_stub(drawing, kind, item.net.name, ref, pin.number)
                if path is None:
                    continue
                ports.append(
                    SheetPort(
                        id=f"arranged-{ref}-{pin.number}",
                        kind=kind,
                        name=item.net.name,
                        at=path[-1],
                        links=(PortLink(pin=NetNode(ref, pin.number), path=path),),
                    )
                )
                rails.append(
                    Rail(
                        net_id=item.net.id,
                        net_name=item.net.name,
                        net_class=item.net.net_class,
                        path=path,
                        at=path[-1],
                        direction="down" if kind == "ground" else "up",
                    )
                )
        drawing = dataclasses.replace(
            drawing,
            rails=tuple(rails),
            labels=(*drawing.labels, *_rail_names(rails)),
        )

        # Which block each part is in: its cluster, with every hub a block of its own
        # that reaches into each cluster on it.
        cluster_of: dict[str, int] = {}
        for index, group in enumerate(self.clusters()):
            for ref in group:
                cluster_of[ref] = index

        def local(item: _ResolvedNet) -> bool:
            refs = self.refs_on(item)
            hubs = {r for r in refs if self.parts[r].hub}
            blocks = {cluster_of[r] for r in refs if r not in hubs}
            return len(hubs) <= 1 and len(blocks) <= 1

        # Route shortest pin-to-pin connections first across all local nets (Kruskal MST
        # per net), so short direct joins (ladder links, aligned bus pins) never lose their
        # straight lane to a longer cross-block wire.
        PinKey = tuple[str, str]
        parent: dict[tuple[str, PinKey], PinKey] = {}

        def find(net_id: str, key: PinKey) -> PinKey:
            cur = key
            while parent[(net_id, cur)] != cur:
                parent[(net_id, cur)] = parent[(net_id, parent[(net_id, cur)])]
                cur = parent[(net_id, cur)]
            return cur

        candidates: list[tuple[float, str, PinKey, PinKey, _ResolvedNet]] = []
        wire_all = self.options.name_nets_at == 0
        for item in self.signal_nets():
            if not wire_all and not local(item):
                continue
            pins = sorted(
                ((ref, pin.number) for ref, pin in item.pins),
                key=lambda k: (not self.parts[k[0]].hub, _ref_sort_key(k[0]), k[1]),
            )
            at = {
                key: self.symbols[key[0]].anchor_of(self.parts[key[0]].pin(key[1]))
                for key in pins
            }
            for key in pins:
                parent[(item.net.id, key)] = key
            for idx, first in enumerate(pins):
                for second in pins[idx + 1 :]:
                    gap = abs(at[first].x - at[second].x) + abs(at[first].y - at[second].y)
                    candidates.append((gap, item.net.id, first, second, item))
        candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))

        laid: list[Wire] = []
        out: list[SheetWire] = []
        for gap, net_id, first, second, item in candidates:
            ra, rb = find(net_id, first), find(net_id, second)
            if ra == rb:
                continue
            path = route_sheet_wire(
                dataclasses.replace(drawing, wires=tuple(laid)), first, second
            )
            if path is None or (
                not wire_all and _length(path) > DETOUR_FACTOR * gap + DETOUR_SLACK_MM
            ):
                continue
            parent[(net_id, rb)] = ra
            a, b = NetNode(first[0], first[1]), NetNode(second[0], second[1])
            laid.append(
                Wire(
                    net_id=item.net.id,
                    net_name=item.net.name,
                    net_class=item.net.net_class,
                    path=path,
                    ends=(a, b),
                )
            )
            out.append(SheetWire(a=a, b=b, path=path))
        return tuple(out), tuple(ports)


def _length(path: Sequence[Point2]) -> float:
    return sum(abs(q.x - p.x) + abs(q.y - p.y) for p, q in itertools.pairwise(path))


def _shift_arrangement(
    result: Arrangement, dx: float, dy: float
) -> Arrangement:
    """Translate every placement, wire and port by ``(dx, dy)``, snapped to the sheet grid."""
    sdx, sdy = _grid(dx), _grid(dy)
    if sdx == 0.0 and sdy == 0.0:
        return result
    placements = tuple(
        dataclasses.replace(p, at=Point2(_grid(p.at.x + sdx), _grid(p.at.y + sdy)))
        for p in result.placements
    )
    wires = tuple(
        dataclasses.replace(
            w, path=tuple(Point2(_grid(pt.x + sdx), _grid(pt.y + sdy)) for pt in w.path)
        )
        for w in result.wires
    )
    ports = tuple(
        dataclasses.replace(
            port,
            at=Point2(_grid(port.at.x + sdx), _grid(port.at.y + sdy)),
            links=tuple(
                dataclasses.replace(
                    link,
                    path=tuple(
                        Point2(_grid(pt.x + sdx), _grid(pt.y + sdy)) for pt in link.path
                    ),
                )
                for link in port.links
            ),
        )
        for port in result.ports
    )
    return Arrangement(placements=placements, wires=wires, ports=ports)


def _arrange_subset(
    doc: PerfDocument,
    lookup: FootprintLookup,
    options: SchematicOptions,
    selected: set[str],
) -> Arrangement:
    """Arrange only ``selected`` parts on an existing hand-drawn sheet, keeping every other
    symbol, wire and port untouched and shifting the arranged block clear of fixed bodies."""
    sub_doc = dataclasses.replace(
        doc,
        components=tuple(c for c in doc.components if c.ref in selected),
        boards=tuple(
            dataclasses.replace(
                b, components=tuple(c for c in b.components if c.ref in selected)
            )
            for b in doc.boards
        ),
        parts=tuple(p for p in doc.parts if p.ref in selected),
        nets=tuple(
            dataclasses.replace(
                n, nodes=tuple(node for node in n.nodes if node.component_ref in selected)
            )
            for n in doc.nets
            if any(node.component_ref in selected for node in n.nodes)
        ),
        sheet=(),
        sheet_wires=(),
        sheet_ports=(),
    )
    sub_layout = _Layout(sub_doc, lookup, options)
    if not sub_layout.parts:
        return Arrangement(placements=doc.sheet, wires=doc.sheet_wires, ports=doc.sheet_ports)
    sub_layout.arrange()
    sub_wires, sub_ports = sub_layout.wire_up()
    sub = Arrangement(
        placements=sub_layout.placements(), wires=sub_wires, ports=sub_ports
    )

    # Align the arranged block's centre with the selected symbols' old centre on the sheet.
    ref_of = {p.id: p.ref for p in doc.parts}
    ref_of.update({c.id: c.ref for c in every_component(doc)})
    old_selected = [p for p in doc.sheet if ref_of.get(p.id) in selected]
    if old_selected:
        old_cx = (min(p.at.x for p in old_selected) + max(p.at.x for p in old_selected)) / 2
        old_cy = (min(p.at.y for p in old_selected) + max(p.at.y for p in old_selected)) / 2
        new_cx = (min(p.at.x for p in sub.placements) + max(p.at.x for p in sub.placements)) / 2
        new_cy = (min(p.at.y for p in sub.placements) + max(p.at.y for p in sub.placements)) / 2
        sub = _shift_arrangement(sub, old_cx - new_cx, old_cy - new_cy)

    # Shift clear if the arranged block would overlap any fixed unselected symbol.
    full_notes: list[str] = []
    all_symbols = _collect_symbols(doc, lookup, full_notes)
    fixed_boxes: list[tuple[float, float, float, float]] = []
    for placement in doc.sheet:
        ref = ref_of.get(placement.id)
        if ref is None or ref in selected or ref not in all_symbols:
            continue
        body = _orient_body(all_symbols[ref].body, placement.rotation, placement.mirrored)
        fixed_boxes.append(
            (placement.at.x, placement.at.y, placement.at.x + body.width, placement.at.y + body.height)
        )
    if fixed_boxes:
        sub_sizes = {sub_layout.part_id(p.ref): (p.shape.width, p.shape.height) for p in sub_layout.parts.values()}
        margin = STACK_GAP * GRID_MM
        for _ in range(32):
            hit_bottom: float | None = None
            for placement in sub.placements:
                w, h = sub_sizes[placement.id]
                x0, y0, x1, y1 = placement.at.x, placement.at.y, placement.at.x + w, placement.at.y + h
                for fx0, fy0, fx1, fy1 in fixed_boxes:
                    if x0 < fx1 + margin and fx0 - margin < x1 and y0 < fy1 + margin and fy0 - margin < y1:
                        delta = fy1 + margin - y0
                        if hit_bottom is None or delta > hit_bottom:
                            hit_bottom = delta
            if hit_bottom is None:
                break
            sub = _shift_arrangement(sub, 0.0, hit_bottom)

    selected_ids = {p.id for p in sub.placements}
    kept_placements = tuple(p for p in doc.sheet if p.id not in selected_ids)
    kept_wires = tuple(
        w
        for w in doc.sheet_wires
        if w.a.component_ref not in selected and w.b.component_ref not in selected
    )
    kept_ports: list[SheetPort] = []
    for port in doc.sheet_ports:
        remaining = tuple(link for link in port.links if link.pin.component_ref not in selected)
        if remaining:
            kept_ports.append(dataclasses.replace(port, links=remaining))
        elif not port.links:
            kept_ports.append(port)
    used_port_ids = {port.id for port in kept_ports}
    unique_sub_ports: list[SheetPort] = []
    for port in sub.ports:
        pid = port.id
        suffix = 2
        while pid in used_port_ids:
            pid = f"{port.id}-{suffix}"
            suffix += 1
        used_port_ids.add(pid)
        unique_sub_ports.append(dataclasses.replace(port, id=pid))
    return Arrangement(
        placements=kept_placements + sub.placements,
        wires=kept_wires + sub.wires,
        ports=tuple(kept_ports) + tuple(unique_sub_ports),
    )


def arrange_sheet(
    doc: PerfDocument,
    lookup: FootprintLookup,
    options: SchematicOptions = DEFAULT_SCHEMATIC_OPTIONS,
    *,
    refs: Sequence[str] | None = None,
) -> Arrangement:
    """Every part placed and the short connections wired, as a hand-drawn sheet.

    When ``refs`` names a subset of the parts on an already-placed sheet, only those parts
    are arranged and the rest of the sheet stays where it was.
    """
    if refs and doc.sheet:
        selected = set(refs)
        notes: list[str] = []
        all_refs = set(_collect_symbols(doc, lookup, notes))
        if selected and selected < all_refs:
            return _arrange_subset(doc, lookup, options, selected)
    layout = _Layout(doc, lookup, options)
    if not layout.parts:
        return Arrangement(placements=(), wires=(), ports=())
    layout.arrange()
    wires, ports = layout.wire_up()
    return Arrangement(placements=layout.placements(), wires=wires, ports=ports)


def arranged(
    doc: PerfDocument,
    lookup: FootprintLookup,
    options: SchematicOptions = DEFAULT_SCHEMATIC_OPTIONS,
) -> PerfDocument:
    """``doc`` with its sheet arranged: what ``sheet.arrange`` will dispatch."""
    result = arrange_sheet(doc, lookup, options)
    return dataclasses.replace(
        doc, sheet=result.placements, sheet_wires=result.wires, sheet_ports=result.ports
    )


def printed_names(drawing: SchematicDrawing) -> int:
    """The net names a reader has to match up by eye."""
    return sum(1 for label in drawing.labels if label.kind == "net")
