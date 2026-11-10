"""The System view's cables run round the boards, not over them.

A cable leaves each board by the edge nearest its connector and runs outside the boards from
there, as it does in the System's 3D: drawn straight across, W1 in the two-board example ran
over the whole relay board and its Nano to reach the supply. Two connectors facing each other
across the bench are still joined straight.
"""

from __future__ import annotations

import itertools
import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import PerfDocument
from perfboard_studio.ui.systemview import (
    CABLE_CLEARANCE_MM,
    Point,
    Rect,
    SystemView,
    _crosses,
    _crossings,
    _grown,
    cable_route,
    nearest_side,
    offset_route,
)

SYSTEM = Path(__file__).resolve().parents[1] / "examples" / "relay-and-supply.perf"
LOOKUP = footprint_lookup()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _system() -> PerfDocument:
    return persist.parse_document_or_throw(SYSTEM.read_text(encoding="utf-8"))


def _inside(point: Point, rect: Rect) -> bool:
    return rect[0] < point[0] < rect[2] and rect[1] < point[1] < rect[3]


def _to_edge(point: Point, rect: Rect) -> float:
    x, y = point
    return min(x - rect[0], y - rect[1], rect[2] - x, rect[3] - y)


def _view(doc: PerfDocument) -> SystemView:
    _app()
    view = SystemView(LOOKUP)
    view.resize(1400, 700)
    view.set_document(doc)
    return view


def test_a_cable_meets_a_board_only_near_its_own_connector() -> None:
    doc = _system()
    view = _view(doc)
    frames = view.board_frames()
    assert len(frames) == 2 and doc.cables
    for cable in doc.cables:
        paths = view.cable_paths(cable.id)
        assert len(paths) == len(cable.wires)
        for path in paths:
            start = path.pointAtPercent(0.0)
            end = path.pointAtPercent(1.0)
            pins = {cable.a.board: (start.x(), start.y()), cable.b.board: (end.x(), end.y())}
            for step in range(1001):
                at = path.pointAtPercent(step / 1000)
                point = (at.x(), at.y())
                for board_id, frame in frames.items():
                    if not _inside(point, frame):
                        continue
                    # On a board, a wire is on its way between its own pin and the edge
                    # nearest that pin: never further from the pin than the pin is from
                    # the edge, and never on a board it does not end on.
                    assert board_id in pins, (cable.ref, board_id, point)
                    pin = pins[board_id]
                    assert math.dist(point, pin) <= _to_edge(pin, frame) + 1.0, (
                        cable.ref, board_id, point, pin
                    )


def test_a_cables_wires_cross_only_where_they_gather_into_a_connector() -> None:
    # W1 runs from J102's pins (+12V left, GND right) to J1's (GND left, +12V right): its
    # two wires change sides once, as the real cable would with a half-twist. They do it
    # where they gather from the connector's pin pitch into the cable -- on its board, or in
    # the clearance just past its edge -- never along the run, where they lie side by side.
    doc = _system()
    view = _view(doc)
    frames = {
        board_id: _grown(frame, CABLE_CLEARANCE_MM + 1.0)
        for board_id, frame in view.board_frames().items()
    }
    for cable in doc.cables:
        ways = [
            [(at.x(), at.y()) for at in (p.pointAtPercent(k / 400) for k in range(401))]
            for p in view.cable_paths(cable.id)
        ]
        assert _crossings(ways) <= 1, cable.ref
        for one, other in itertools.combinations(ways, 2):
            for p, q in itertools.pairwise(one):
                for r, s in itertools.pairwise(other):
                    if _crossings([[p, q], [r, s]]):
                        at = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
                        assert any(
                            _inside(at, frames[end.board]) for end in (cable.a, cable.b)
                        ), (cable.ref, at)


def test_wires_beside_one_route_never_cross() -> None:
    # Round two corners turning opposite ways, which is where a wire given its own
    # clearance round each board crossed the other.
    route: list[Point] = [(0.0, 0.0), (0.0, -10.0), (40.0, -10.0), (40.0, 50.0), (10.0, 50.0), (10.0, 30.0)]
    ways = [offset_route(route, d) for d in (-1.2, -0.4, 0.4, 1.2)]
    assert _crossings(ways) == 0
    for way in ways:
        assert len(way) == len(route)
        for (p, q), (u, v) in zip(itertools.pairwise(way), itertools.pairwise(route), strict=True):
            # Each run stays parallel to the route's.
            assert abs((q[0] - p[0]) * (v[1] - u[1]) - (q[1] - p[1]) * (v[0] - u[0])) < 1e-9


def test_facing_connectors_are_joined_straight() -> None:
    left: Rect = (0.0, 0.0, 50.0, 40.0)
    right: Rect = (60.0, 0.0, 110.0, 40.0)
    start, end = (48.0, 20.0), (62.0, 20.0)
    assert nearest_side(start, left) == "right"
    assert nearest_side(end, right) == "left"
    way = cable_route(start, (left, "right"), end, (right, "left"), [left, right], 3.0)
    assert all(y == 20.0 for _x, y in way)
    assert way[0] == start and way[-1] == end


def test_a_cable_goes_round_a_board_between_its_ends() -> None:
    first: Rect = (0.0, 0.0, 50.0, 40.0)
    middle: Rect = (60.0, 0.0, 110.0, 40.0)
    last: Rect = (120.0, 0.0, 170.0, 40.0)
    start, end = (48.0, 20.0), (122.0, 20.0)
    way = cable_route(start, (first, "right"), end, (last, "left"), [first, middle, last], 3.0)
    for p, q in itertools.pairwise(way):
        assert not _crosses(p, q, middle), (p, q)
    # ...and the ends' own boards only on the straight run out of each.
    assert not any(_crosses(p, q, first) for p, q in itertools.pairwise(way[1:]))
    assert not any(_crosses(p, q, last) for p, q in itertools.pairwise(way[:-1]))
    assert way[0] == start and way[-1] == end


def test_a_connector_leaves_by_its_nearest_edge() -> None:
    board: Rect = (0.0, 0.0, 60.0, 80.0)
    assert nearest_side((30.0, 2.0), board) == "top"
    assert nearest_side((58.0, 40.0), board) == "right"
    assert nearest_side((30.0, 77.0), board) == "bottom"
    assert nearest_side((1.0, 40.0), board) == "left"
