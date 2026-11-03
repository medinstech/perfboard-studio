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


# ---------------------------------------------------------------------------
# The print, in the 2D's letters
# ---------------------------------------------------------------------------


@pytest.fixture
def qt() -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])


@pytest.fixture
def fonts(qt) -> None:  # type: ignore[no-untyped-def]
    """Skip where Qt has no fonts -- its offscreen plugin on Windows -- which is not a
    failure of anything being tested; the stand-in is tested on its own below."""
    from PySide6.QtGui import QFontDatabase

    if not QFontDatabase.families():
        pytest.skip("this Qt platform has no font database, so Qt draws no letters")


def _covers(glyphs, x: float, y: float) -> bool:
    """Whether any triangle of ``glyphs`` covers the point."""
    points = glyphs.GetPoints()
    for index in range(glyphs.GetNumberOfCells()):
        ids = glyphs.GetCell(index).GetPointIds()
        if ids.GetNumberOfIds() != 3:
            continue
        (ax, ay, _), (bx, by, _), (cx, cy, _) = (points.GetPoint(ids.GetId(i)) for i in range(3))
        d1 = (x - bx) * (ay - by) - (ax - bx) * (y - by)
        d2 = (x - cx) * (by - cy) - (bx - cx) * (y - cy)
        d3 = (x - ax) * (cy - ay) - (cx - ax) * (y - ay)
        if not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0)):
            return True
    return False


def test_the_print_is_the_2d_font_one_unit_to_a_capital(fonts) -> None:  # type: ignore[no-untyped-def]
    """The legend, the board's lines and a part's ink were vtkVectorText, a stroke font: the
    bold "01" beside a row in 2D was hairlines in 3D. They are the 2D's own glyphs now,
    filled, a capital one unit tall from the baseline -- the size every caller scales by --
    with an O's counter left open."""
    from perfboard_studio.ui import view3d

    h = view3d._glyphs("H")
    _x0, _x1, y0, y1, _z0, _z1 = h.GetBounds()
    assert y0 == pytest.approx(0.0, abs=0.02)
    assert y1 == pytest.approx(1.0, abs=0.02)
    assert h.GetNumberOfPolys() > 0

    ring = view3d._glyphs("O")
    x0, x1, y0, y1, _z0, _z1 = ring.GetBounds()
    assert not _covers(ring, (x0 + x1) / 2, (y0 + y1) / 2), "an O is a ring, not a disc"
    assert _covers(ring, x0 + (x1 - x0) * 0.06, (y0 + y1) / 2), "and its stroke is filled"


def test_a_board_prints_turkish_with_the_font(fonts) -> None:  # type: ignore[no-untyped-def]
    """vtkVectorText knows ASCII and nothing else, so "ALT YÜZ" lost its Ü."""
    from perfboard_studio.ui import view3d

    assert view3d._glyphs("Ü").GetNumberOfPolys() > 0
    assert view3d.can_print("Röle 12V")


def test_with_no_letters_from_qt_the_stand_in_prints_and_says_what_it_cannot(qt, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """No Qt application, or one with no font database (Qt's offscreen plugin on Windows,
    where the glyphs came out EMPTY and the legend vanished): vtkVectorText stands in, the
    legend is still printed, and ``can_print`` says the stand-in has ASCII alone, so a
    part's value is left off rather than misspelt."""
    from perfboard_studio.ui import view3d

    monkeypatch.setattr(view3d, "_qt_available", lambda: False)
    assert view3d._glyphs("A01").GetNumberOfPolys() > 0
    assert not view3d.can_print("Röle 12V")
    assert view3d.can_print("SRD-12VDC")
    doc = _family_doc(GREEN_DOUBLE_SIDED, "5 x 7 cm")
    legend = view3d.build_legend(doc)
    assert legend and all(actor.GetMapper().GetInput().GetNumberOfPolys() > 0 for actor in legend)


def test_whatever_qt_has_the_legend_is_printed(qt) -> None:  # type: ignore[no-untyped-def]
    """The same promise in whatever this platform gives: fonts or none, the letters are
    there."""
    from perfboard_studio.ui import view3d

    assert view3d._glyphs("A01").GetNumberOfPolys() > 0


# ---------------------------------------------------------------------------
# Polarity, from above
# ---------------------------------------------------------------------------


def _painted_cells(footprint_id: str, mirrored: bool = False):
    """Every painted cell of a borrowed package, as (centre x, centre y, z, normal z), in the
    model's frame (x with the column, y up, from pin 1)."""
    import vtk

    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui import partmodels, view3d

    footprint = get_footprint(footprint_id)
    model = partmodels.model_for(footprint_id)
    assert footprint is not None and model is not None
    cells = []
    for piece in model.pieces:
        if piece.material in ("tinned", "steel", "plated"):
            continue
        painted, _rest = view3d._painted_from_above(
            str(piece.path), mirrored, model.turn_deg, model.offset, footprint, 2.54
        )
        if painted is None:
            continue
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(painted)
        normals.ComputeCellNormalsOn()
        normals.ComputePointNormalsOff()
        normals.SplittingOff()
        normals.ConsistencyOff()
        normals.Update()
        mesh = normals.GetOutput()
        centres = vtk.vtkCellCenters()
        centres.SetInputData(mesh)
        centres.Update()
        for index in range(mesh.GetNumberOfCells()):
            x, y, z = centres.GetOutput().GetPoint(index)
            cells.append((x, y, z, mesh.GetCellData().GetNormals().GetTuple3(index)[2]))
    return footprint, model, cells


@pytest.mark.parametrize(
    ("footprint_id", "marked_pin"),
    [("c-elec-d5-p2", "-"), ("led-5mm", "K")],
)
def test_the_2d_polarity_mark_is_painted_where_it_shows_from_above(footprint_id: str, marked_pin: str) -> None:
    """Seen from above a modelled can is mostly its aluminium top, its stripe down a side the
    camera may not face, and an LED's flat is a sliver of its flange; the 2D inks the
    sector it marks over the measured top view (``topview``). The same region is painted
    onto the case where it lands: level faces only, at the top of what they belong to, all
    on the side of the pin the mark is for, and inside the 2D's mark."""
    from PySide6.QtCore import QPointF

    from perfboard_studio.ui.topview import top_view

    footprint, _model, cells = _painted_cells(footprint_id)
    assert cells, "something is painted"
    marked = next(p for p in footprint.pins if p.name == marked_pin)
    other = next(p for p in footprint.pins if p.name != marked_pin)
    region = top_view(footprint, 2.54).polarity
    heights = [z for _x, _y, z, _nz in cells]
    for x, y, _z, nz in cells:
        assert nz > 0.85, "a level face, not the slope of a dome"
        assert region.contains(QPointF(x, -y)), "inside the 2D's own mark"
        to_marked = math.dist((x, y), (marked.d_col * 2.54, -marked.d_row * 2.54))
        to_other = math.dist((x, y), (other.d_col * 2.54, -other.d_row * 2.54))
        assert to_marked < to_other, f"on the {marked_pin} side"
    assert max(heights) - min(heights) < 0.1, "one level: the shoulder, or the flange"


def test_a_part_on_the_solder_side_is_painted_on_its_mirrored_side() -> None:
    """A mirrored mesh is reflected in x about pin 1 (``_mesh``), so its paint is too."""
    _fp, _model, plain = _painted_cells("c-elec-d5-p2")
    _fp, _model, mirrored = _painted_cells("c-elec-d5-p2", mirrored=True)
    assert sorted(round(-x, 6) for x, *_ in plain) == sorted(round(x, 6) for x, *_ in mirrored)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_a_generated_can_carries_the_2d_stripe_on_its_top(rotation: int) -> None:
    """A can with no borrowed model is drawn here, and the 2D inks
    ``ELECTROLYTIC_STRIPE_SHARE`` of its diameter on the minus side: the same band is
    on its top, away from pin 1 whichever way it is turned."""
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.model import ComponentInstance, HoleCoord
    from perfboard_studio.ui import view3d

    comp = ComponentInstance(
        id="c1", ref="C1", value="", footprint_id="c-elec-d6.3-p1-h11",
        anchor=HoleCoord(8, 8), rotation=rotation,
    )
    body = view3d._world_body(footprint_lookup(), comp, DEFAULT_BOARD)
    assert body is not None and body.polarity is not None
    accent = view3d._rgb(body.style.accent)
    tops = [
        piece for piece in view3d._can_pieces(body)
        if piece.rgb == accent and piece.material == view3d.SLEEVE
    ]
    assert len(tops) == 1
    x0, x1, y0, y1, z0, _z1 = tops[0].source.GetBounds()
    assert z0 >= body.height, "on the top"
    centre = ((x0 + x1) / 2 + body.x, (y0 + y1) / 2 + body.y)
    away = math.dist(centre, body.polarity) > math.dist((body.x, body.y), body.polarity)
    assert away, "on the minus side, away from pin 1"
