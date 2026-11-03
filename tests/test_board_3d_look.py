"""The 3D board says what the 2D board says.

The 2D view and the 3D view are two pictures of one board, and the 3D one exists so
somebody can check that what they are about to solder is what they meant. So wherever the
board model or the 2D view has an answer -- a finger's outline -- the 3D view asks the same
question rather than drawing its own guess. Nothing here renders: every check is on the
geometry the actors are built from, which needs no GL context.
"""

from __future__ import annotations

import dataclasses
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from perfboard_studio.boardfamily import GREEN_DOUBLE_SIDED, PHENOLIC_SINGLE_SIDED, board_for
from perfboard_studio.commands import DEFAULT_BOARD
from perfboard_studio.geometry import (
    edge_finger_rect,
    finger_corner_radius_mm,
    surviving_finger_holes,
)
from perfboard_studio.model import DocumentMeta, PerfDocument

META = DocumentMeta(name="t", created="", modified="")


def _family_doc(family, size_name: str) -> PerfDocument:
    size = next(s for s in family.sizes if s.name == size_name and s.strip)
    made = board_for(family, size, DEFAULT_BOARD)
    return PerfDocument(
        meta=META,
        board=made.board,
        edge_connectors=made.edge_connectors,
        mounting_holes=made.mounting_holes,
    )


@pytest.mark.parametrize("shape", ["rounded", "stadium", "square"])
def test_a_finger_in_3d_is_the_outline_the_2d_draws(shape: str) -> None:
    """The fingers were cubes in 3D, and the green board's stadium strip came out as grey
    bricks beside the round-ended pads of the 2D view. Each is now the rectangle
    ``edge_finger_rect`` gives with its corners rounded to ``finger_corner_radius_mm``,
    the radius view2d draws with: it fills the rectangle, and its corners are cut by the
    radius and no more."""
    from perfboard_studio.ui import view3d

    doc = _family_doc(GREEN_DOUBLE_SIDED, "5 x 7 cm")
    connector = dataclasses.replace(doc.edge_connectors[0], shape=shape)
    hole = surviving_finger_holes(dataclasses.replace(doc, edge_connectors=(connector,)), connector)[0]
    rect = edge_finger_rect(connector, hole, doc.board)
    radius = finger_corner_radius_mm(connector, rect)
    ring = view3d.finger_outline(rect, radius)

    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    assert min(xs) == pytest.approx(rect.x)
    assert max(xs) == pytest.approx(rect.x + rect.width)
    # 3D y runs up where board rows run down.
    assert min(ys) == pytest.approx(-(rect.y + rect.height))
    assert max(ys) == pytest.approx(-rect.y)
    corner = (rect.x, -rect.y)
    nearest = min(math.dist(corner, point) for point in ring)
    assert nearest == pytest.approx(radius * (math.sqrt(2) - 1), abs=1e-6)
    area = sum(ax * by - bx * ay for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True)) / 2
    assert area > 0, "counter-clockwise from above, so the top face looks up"


@pytest.mark.parametrize("family", [GREEN_DOUBLE_SIDED, PHENOLIC_SINGLE_SIDED], ids=lambda f: f.id)
def test_every_finger_on_a_stock_board_is_drawn_from_its_outline(family) -> None:
    """Every surviving finger of each face is one plate: its outline on both faces of the
    copper and the edge between them, and nothing else."""
    from perfboard_studio.ui import view3d

    doc = _family_doc(family, "5 x 7 cm")
    board = doc.board
    expected = 0
    for connector in doc.edge_connectors:
        faces = ("top", "bottom") if connector.face == "both" else (connector.face,)
        sides = sum(1 for face in faces if not (board.single_sided and face == "top"))
        for hole in surviving_finger_holes(doc, connector):
            rect = edge_finger_rect(connector, hole, board)
            ring = view3d.finger_outline(rect, finger_corner_radius_mm(connector, rect))
            expected += sides * 6 * len(ring)  # two faces of the ring, four corners a side
    actors = view3d.build_edge_connectors(doc)
    assert actors
    drawn = sum(actor.GetMapper().GetInput().GetNumberOfPoints() for actor in actors)
    assert drawn == expected
