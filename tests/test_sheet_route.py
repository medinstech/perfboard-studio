"""A wire drawn on the sheet goes round the symbols (``schematic.route_sheet_wire``).

The wire tool drew two segments turning once, whatever was in the way, so a 555 blinker
wired pin to pin had its lines across R1, R2, C1 and J1 and the sheet read as shorted.
What is pinned: a drawn wire is orthogonal, starts and ends exactly on its two pins, leaves
each pin the way its lead points, and crosses no symbol's box -- on a sheet built to put
one in the way, and between every pair of pins of a real example's sheet.

And it never reads as a join that is not there. The first version only priced running
along another net's wire, so the NE555 a new user wired pin to pin had two nets on one
line in nine places. Pinned: no run of a wire on another net's line and no corner or end
of one on another's, on sheets built to tempt it and on every example wired pin to pin.
"""

from __future__ import annotations

import dataclasses
import itertools
from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import NetNode, PerfDocument, Point2, SheetWire, SymbolPlacement
from perfboard_studio.schematic import (
    GRID_MM,
    SchematicDrawing,
    Symbol,
    SymbolPin,
    Wire,
    build_schematic,
    pin_position,
    rail_glyph_bars,
    route_sheet_wire,
)
from perfboard_studio.system import circuit_parts

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
G = GRID_MM


def _resistor(ref: str, x: float, y: float) -> Symbol:
    return Symbol(
        ref=ref, value="", kind="resistor", footprint_id=None, at=Point2(x, y), shapes=(),
        pins=(
            SymbolPin("1", None, Point2(0.0, GRID_MM), "left"),
            SymbolPin("2", None, Point2(3 * GRID_MM, GRID_MM), "right"),
        ),
        width=3 * GRID_MM, height=2 * GRID_MM,
    )


def _crosses(symbol: Symbol, path: tuple[Point2, ...], ends: tuple[Point2, Point2]) -> bool:
    """Whether the path touches the symbol's box anywhere but at the wire's own two ends."""
    x0, y0 = symbol.at.x, symbol.at.y
    x1, y1 = x0 + symbol.width, y0 + symbol.height
    for p, q in itertools.pairwise(path):
        steps = max(1, round(max(abs(q.x - p.x), abs(q.y - p.y)) / (GRID_MM / 4)))
        for i in range(steps + 1):
            x = p.x + (q.x - p.x) * i / steps
            y = p.y + (q.y - p.y) * i / steps
            if any(abs(x - e.x) < 1e-6 and abs(y - e.y) < 1e-6 for e in ends):
                continue
            if x0 - 1e-6 <= x <= x1 + 1e-6 and y0 - 1e-6 <= y <= y1 + 1e-6:
                return True
    return False


def _orthogonal(path: tuple[Point2, ...]) -> bool:
    return all(abs(p.x - q.x) < 1e-6 or abs(p.y - q.y) < 1e-6 for p, q in itertools.pairwise(path))


def test_a_wire_goes_round_a_symbol_in_its_way() -> None:
    r1 = _resistor("R1", 0.0, 0.0)
    r2 = _resistor("R2", 20 * GRID_MM, 0.0)
    blocker = Symbol(
        ref="U1", value="", kind="ic", footprint_id=None, at=Point2(8 * GRID_MM, -2 * GRID_MM),
        shapes=(), pins=(), width=4 * GRID_MM, height=6 * GRID_MM,
    )
    drawing = SchematicDrawing(symbols=(r1, blocker, r2))
    path = route_sheet_wire(drawing, ("R1", "2"), ("R2", "1"))
    assert path is not None
    start, end = pin_position(drawing, "R1", "2"), pin_position(drawing, "R2", "1")
    assert path[0] == start and path[-1] == end
    assert _orthogonal(path)
    assert not _crosses(blocker, path, (start, end))  # type: ignore[arg-type]
    assert not any(_crosses(s, path, (start, end)) for s in (r1, r2))  # type: ignore[arg-type]
    # Out of each pin the way its lead points: R1's pin 2 points right, R2's pin 1 left.
    assert path[1].x > path[0].x and path[-2].x < path[-1].x
    # With nothing in the way it is the straight line it always was.
    straight = route_sheet_wire(SchematicDrawing(symbols=(r1, r2)), ("R1", "2"), ("R2", "1"))
    assert straight == (start, end)


def test_no_wire_between_two_pins_of_an_example_crosses_a_symbol() -> None:
    lookup = footprint_lookup()
    doc = persist.parse_document_or_throw((EXAMPLES / "ne555-astable.perf").read_text(encoding="utf-8"))
    drawing = build_schematic(doc, lookup)
    pins = [(symbol.ref, pin.number) for symbol in drawing.symbols for pin in symbol.pins]
    tried = 0
    for a, b in itertools.islice(itertools.combinations(pins, 2), 0, None, 7):
        path = route_sheet_wire(drawing, a, b)
        if path is None:
            continue
        tried += 1
        ends = (pin_position(drawing, *a), pin_position(drawing, *b))
        assert _orthogonal(path), (a, b)
        assert not any(_crosses(symbol, path, ends) for symbol in drawing.symbols), (a, b, path)  # type: ignore[arg-type]
    assert tried >= 20


def test_a_pin_that_is_not_there_is_no_route() -> None:
    drawing = SchematicDrawing(symbols=(_resistor("R1", 0.0, 0.0),))
    assert route_sheet_wire(drawing, ("R1", "1"), ("R9", "1")) is None
    assert route_sheet_wire(drawing, ("R1", "1"), ("R1", "1")) is None


def _lines(drawing: SchematicDrawing) -> list[tuple[str, tuple[Point2, ...]]]:
    """Every line on the sheet with its net: the wires, the rails' stubs and their bars."""
    lines = [(wire.net_id, wire.path) for wire in drawing.wires]
    for rail in drawing.rails:
        lines.append((rail.net_id, rail.path))
        lines.extend((rail.net_id, bar) for bar in rail_glyph_bars(rail))
    return lines


def _on(point: Point2, p: Point2, q: Point2) -> bool:
    """Whether ``point`` lies on the segment from ``p`` to ``q``, ends included."""
    eps = 1e-6
    if abs(p.x - q.x) < eps and abs(point.x - p.x) < eps:
        return min(p.y, q.y) - eps <= point.y <= max(p.y, q.y) + eps
    if abs(p.y - q.y) < eps and abs(point.y - p.y) < eps:
        return min(p.x, q.x) - eps <= point.x <= max(p.x, q.x) + eps
    return False


def _false_joins(drawing: SchematicDrawing) -> list[str]:
    """Each place two nets read as joined: a run of one along a run of the other, or a
    corner or end of one on the other's line. A crossing square on is not one."""
    found = []
    lines = _lines(drawing)
    for (net_a, path_a), (net_b, path_b) in itertools.combinations(lines, 2):
        if net_a == net_b:
            continue
        runs_a = [(p, q) for p, q in itertools.pairwise(path_a) if p != q]
        runs_b = [(p, q) for p, q in itertools.pairwise(path_b) if p != q]
        for (p, q), (r, s) in itertools.product(runs_a, runs_b):
            if abs(p.y - q.y) < 1e-6 and abs(r.y - s.y) < 1e-6 and abs(p.y - r.y) < 1e-6:
                shared = min(max(p.x, q.x), max(r.x, s.x)) - max(min(p.x, q.x), min(r.x, s.x))
            elif abs(p.x - q.x) < 1e-6 and abs(r.x - s.x) < 1e-6 and abs(p.x - r.x) < 1e-6:
                shared = min(max(p.y, q.y), max(r.y, s.y)) - max(min(p.y, q.y), min(r.y, s.y))
            else:
                continue
            if shared > 1e-6:
                found.append(f"{net_a} along {net_b} at {p}..{q}")
        for nodes, net, runs, against in ((path_a, net_a, runs_b, net_b), (path_b, net_b, runs_a, net_a)):
            for point in nodes:
                if any(_on(point, r, s) for r, s in runs):
                    found.append(f"{net} meets {against} at {point}")
    return found


def _wire(net: str, *points: Point2) -> Wire:
    return Wire(net_id=net, net_name=net, net_class="signal", path=points)


def _with(drawing: SchematicDrawing, path: tuple[Point2, ...]) -> SchematicDrawing:
    mine = Wire(
        net_id="mine", net_name="MINE", net_class="signal", path=path,
        ends=(NetNode(component_ref="R1", pin="2"), NetNode(component_ref="R2", pin="1")),
    )
    return dataclasses.replace(drawing, wires=(*drawing.wires, mine))


def test_a_wire_is_never_laid_along_another_nets_line() -> None:
    """Another net's wire lies on the row the straight route would take, in a U: the new
    wire goes past it, not along it -- two nets on one line read as one."""
    other = _wire("other", Point2(6 * G, -6 * G), Point2(6 * G, G), Point2(14 * G, G), Point2(14 * G, -6 * G))
    drawing = SchematicDrawing(symbols=(_resistor("R1", 0.0, 0.0), _resistor("R2", 20 * G, 0.0)), wires=(other,))
    path = route_sheet_wire(drawing, ("R1", "2"), ("R2", "1"))
    assert path is not None and _orthogonal(path)
    assert not _false_joins(_with(drawing, path))


def test_a_wire_does_not_end_another_nets_line_on_itself_but_crosses_one_square_on() -> None:
    """A line of another net ENDING on the straight route would make a T, so the wire
    steps round its end; one running right across it is crossed square on, which is what
    a crossing is."""
    r1, r2 = _resistor("R1", 0.0, 0.0), _resistor("R2", 20 * G, 0.0)
    ends_on_it = _wire("other", Point2(10 * G, -6 * G), Point2(10 * G, G))
    drawing = SchematicDrawing(symbols=(r1, r2), wires=(ends_on_it,))
    path = route_sheet_wire(drawing, ("R1", "2"), ("R2", "1"))
    assert path is not None
    assert not _false_joins(_with(drawing, path))
    assert len(path) > 2

    across = _wire("other", Point2(10 * G, -6 * G), Point2(10 * G, 6 * G))
    drawing = SchematicDrawing(symbols=(r1, r2), wires=(across,))
    path = route_sheet_wire(drawing, ("R1", "2"), ("R2", "1"))
    assert path == (pin_position(drawing, "R1", "2"), pin_position(drawing, "R2", "1"))


def test_a_wire_keeps_a_track_between_symbols_three_grids_apart() -> None:
    """The boxes are the symbols' own: one grid of margin round each left a single track
    between symbols the layout put three apart, and every wire after the first went round
    the outside. Two wires through the same gap now both go through it."""
    r1, r2 = _resistor("R1", 0.0, 0.0), _resistor("R2", 6 * G, 0.0)
    r3, r4 = _resistor("R3", 0.0, 10 * G), _resistor("R4", 6 * G, 10 * G)
    drawing = SchematicDrawing(symbols=(r1, r2, r3, r4))
    first = route_sheet_wire(drawing, ("R1", "2"), ("R4", "1"))
    assert first is not None
    assert max(p.x for p in first) <= 6 * G, "through the gap between the columns"


def _frozen_unwired(doc: PerfDocument) -> PerfDocument:
    """``doc`` with its sheet frozen where the layout put every symbol, and no wire drawn:
    every connection said by name at its pins, as the window has it before the first wire."""
    doc = dataclasses.replace(doc, sheet=(), sheet_wires=())
    ids = {part.ref: part.id for part in circuit_parts(doc)}  # every board's, as the window freezes
    drawing = build_schematic(doc, footprint_lookup())
    return dataclasses.replace(
        doc,
        sheet=tuple(
            SymbolPlacement(id=ids[s.ref], at=s.at, rotation=s.rotation, mirrored=s.mirrored)
            for s in drawing.symbols
            if s.ref in ids
        ),
    )


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.perf")), ids=lambda path: path.stem)
def test_an_example_wired_pin_to_pin_has_no_join_that_is_not_there(path: Path) -> None:
    """Every net of a real example drawn the way a person draws it -- one wire from each
    pin to the next, in the order the netlist lists them -- and no wire laid along another
    net's line or meeting one at a corner, on the sheet as it is when the last is drawn."""
    lookup = footprint_lookup()
    doc = _frozen_unwired(persist.parse_document_or_throw(path.read_text(encoding="utf-8")))
    drawn = 0
    for net in doc.nets:
        for a, b in itertools.pairwise(net.nodes):
            drawing = build_schematic(doc, lookup)
            ends = ((a.component_ref, a.pin), (b.component_ref, b.pin))
            if pin_position(drawing, *ends[0]) is None or pin_position(drawing, *ends[1]) is None:
                continue
            route = route_sheet_wire(drawing, *ends)
            assert route is not None, (net.name, ends)
            doc = dataclasses.replace(doc, sheet_wires=(*doc.sheet_wires, SheetWire(a=a, b=b, path=route)))
            drawn += 1
    assert drawn >= 6
    assert _false_joins(build_schematic(doc, lookup)) == []
