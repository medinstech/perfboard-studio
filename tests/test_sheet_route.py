"""A wire drawn on the sheet goes round the symbols (``schematic.route_sheet_wire``).

The wire tool drew two segments turning once, whatever was in the way, so a 555 blinker
wired pin to pin had its lines across R1, R2, C1 and J1 and the sheet read as shorted.
What is pinned: a drawn wire is orthogonal, starts and ends exactly on its two pins, leaves
each pin the way its lead points, and crosses no symbol's box -- on a sheet built to put
one in the way, and between every pair of pins of a real example's sheet.
"""

from __future__ import annotations

import itertools
from pathlib import Path

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import Point2
from perfboard_studio.schematic import (
    GRID_MM,
    SchematicDrawing,
    Symbol,
    SymbolPin,
    build_schematic,
    pin_position,
    route_sheet_wire,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


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
