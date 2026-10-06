"""3D board view on VTK, rewired onto the real engine.

Promoted from ``prototypes/qt/view3d.py``; the three claims it existed to test
(instanced pad rendering, offscreen render for the build guide, and a solder trace
looking different from a wire) are unchanged, only the data source is. The document is
a real ``perfboard_studio.model.PerfDocument`` and footprints come from an injected
``FootprintLookup`` (``perfboard_studio.footprints.footprint_lookup()`` in practice) rather
than a JSON sidecar file.

Axis note, unchanged from the prototype: rows grow downward in board space
(screen-like), so 3D uses y = -row*pitch. Looking down +Z then matches the 2D editor's
orientation instead of mirroring it.
"""

from __future__ import annotations

import functools
import math
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from typing import Any

import vtk  # type: ignore[import-untyped]
from vtkmodules.util import numpy_support

from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.footprints import (
    LEAD_RADIUS_MM,
    LEAD_TRIM_MM,
    MODULE_PCB_MM,
    MODULE_SEAT_SOCKETED_MM,
    wire_entry,
)
from perfboard_studio.geometry import (
    all_pin_holes,
    board_edge_margin_mm,
    board_note_centre_mm,
    board_size_mm,
    column_label,
    edge_finger_rect,
    hole_key,
    holes_without_grid_pad,
    legend_strip_mm,
    mounting_hole_centre_mm,
    pad_extent_mm,
    printed_label_is_clear,
    printed_row_label,
    surviving_finger_holes,
    transform_offset,
    undrilled_holes,
)
from perfboard_studio.guide import Guide, all_steps, document_at_step, step_focus
from perfboard_studio.model import (
    Board,
    BoardSide,
    Conductor,
    Footprint,
    HoleCoord,
    NetClass,
    PerfDocument,
    Point2,
    contacts_every_path_hole,
)
from perfboard_studio.occupancy import stacking_layers
from perfboard_studio.stripboard import cut_holes, segments

from .boardcolors import scheme_for
from .bodies import (
    PIN_NAME_HEIGHT_MM,
    PIN_NAME_TAG_HEIGHT_MM,
    PIN_NAME_TAG_PAD_MM,
    BodyStyle,
    PinLabel,
    Surface,
    lay_out_pin_names,
    module_block_size,
    pin_labels,
    placement_for,
    polarity_pin_offset,
    resistor_bands,
    style_for,
    surface_for,
)
from .partmodels import ModelPiece, PartModel, header_pin_model, terminal_block_models
from .partmodels import model_for as _model_for

SUBSTRATE_RGB = {
    "FR4": (0.16, 0.36, 0.21),
    "FR2": (0.62, 0.48, 0.29),
    "FR1": (0.68, 0.55, 0.35),
}
#: Fallback copper. The real colour comes from the board's scheme -- bare copper on a
#: phenolic board, plated gold on a masked one.
PAD_RGB = (0.80, 0.66, 0.32)
#: Solder: dull pewter, and rough. Solder is NOT shiny wire, and PLAN.md Sec 8.3 makes
#: telling the two apart at a glance a requirement of this view rather than a nicety --
#: these two used to be (0.72,0.74,0.77) and (0.85,0.87,0.89), which is the same grey.
SOLDER_RGB = (0.68, 0.69, 0.72)
#: Tinned copper wire: brighter, and specular enough to read as metal.
BARE_RGB = (0.90, 0.92, 0.95)
#: An insulated wire with no net colour of its own.
INSULATED_RGB = (0.45, 0.47, 0.52)
#: The bore through the board. Near black, unlit: it is a hole.
DRILL_RGB = (0.06, 0.06, 0.07)
BODY_RGB = (0.22, 0.22, 0.26)
#: Tinned component lead.
LEAD_RGB = (0.78, 0.80, 0.84)
#: Silkscreen ink. Slightly off-white, because a printed legend never is.
LEGEND_RGB = (0.92, 0.93, 0.95)


def _hex_rgb(value: str | None, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    if not value or not value.startswith("#") or len(value) != 7:
        return fallback
    return (int(value[1:3], 16) / 255, int(value[3:5], 16) / 255, int(value[5:7], 16) / 255)


def _lit(value: str, factor: float) -> tuple[float, float, float]:
    """One colour a shade lighter or darker, clamped. For a detail that belongs to the
    part it sits on -- a capacitor's crimped rim, the groove scored into its top -- where
    a second colour from the table would read as a second material."""
    return tuple(min(1.0, channel * factor) for channel in _rgb(value))  # type: ignore[return-value]


def _rgb(value: str) -> tuple[float, float, float]:
    """A colour from ui/bodies.py, which is where 2D and 3D agree on what a part looks like."""
    return _hex_rgb(value, BODY_RGB)


def _xy(board: Board, hole: HoleCoord) -> tuple[float, float]:
    return hole.col * board.pitch, -hole.row * board.pitch


def _board_size_mm(board: Board) -> tuple[float, float]:
    """Delegates to geometry rather than repeating the arithmetic: the substrate here and
    the substrate in the 2D editor and on the 1:1 printout have to be the same size, and a
    second copy of the formula is how a board's border silently stops existing in 3D."""
    return board_size_mm(board)


# --------------------------------------------------------------------------- pieces


#: A rectangle in board millimetres: x0, y0, x1, y1, with y increasing upwards as the
#: renderer has it (a row further down the board is a smaller y).
_Rect = tuple[float, float, float, float]


def board_outline_rect(board: Board) -> _Rect:
    """The substrate's own extent. Pure, so it can be asserted directly.

    From ``board_size_mm``, never from the hole span: the two differ by the printed
    border, and a board whose substrate is drawn to the hole span has no border to print
    the row letters on.
    """
    w, h = _board_size_mm(board)
    centre_x = (board.cols - 1) * board.pitch / 2
    centre_y = -(board.rows - 1) * board.pitch / 2
    return (centre_x - w / 2, centre_y - h / 2, centre_x + w / 2, centre_y + h / 2)


def _tile_grid_rect(board: Board) -> _Rect:
    """What the tiles cover: half a pitch beyond the outermost hole centres, all round."""
    half = board.pitch / 2
    return (
        -half,
        -(board.rows - 1) * board.pitch - half,
        (board.cols - 1) * board.pitch + half,
        half,
    )


def _border_rects(board: Board) -> list[_Rect]:
    """The bare strip between the tiles and the board's edge, as up to four rectangles.

    Empty on a flush-cut board, which is the usual case: most stock is cut on the grid and
    ``border_x_mm``/``border_y_mm`` are zero.
    """
    x0, y0, x1, y1 = board_outline_rect(board)
    gx0, gy0, gx1, gy1 = _tile_grid_rect(board)
    # A tolerance, not a bare comparison: a flush-cut board's border is zero and the two
    # rectangles are computed by different routes, so they differ in the last bit and the
    # naive test produces four rectangles a thousandth of a micron wide.
    slop = board.pitch * 1e-6
    rects: list[_Rect] = []
    if gy1 + slop < y1:
        rects.append((x0, gy1, x1, y1))
    if gy0 - slop > y0:
        rects.append((x0, y0, x1, gy0))
    if gx0 - slop > x0:
        rects.append((x0, gy0, gx0, gy1))
    if gx1 + slop < x1:
        rects.append((gx1, gy0, x1, gy1))
    return rects


def _rect_without(rect: _Rect, hole: _Rect) -> list[_Rect]:
    """What is left of one rectangle once another is taken out of it: up to four pieces."""
    x0, y0, x1, y1 = rect
    hx0, hy0, hx1, hy1 = hole
    if hx1 <= x0 or hx0 >= x1 or hy1 <= y0 or hy0 >= y1:
        return [rect]
    pieces: list[_Rect] = []
    if hy1 < y1:
        pieces.append((x0, hy1, x1, y1))
    if hy0 > y0:
        pieces.append((x0, y0, x1, hy0))
    band_y0, band_y1 = max(y0, hy0), min(y1, hy1)
    if hx0 > x0:
        pieces.append((x0, band_y0, hx0, band_y1))
    if hx1 < x1:
        pieces.append((hx1, band_y0, x1, band_y1))
    return pieces


def _rects_without(rects: list[_Rect], holes: list[_Rect]) -> list[_Rect]:
    for hole in holes:
        rects = [piece for rect in rects for piece in _rect_without(rect, hole)]
    return rects


@dataclass(frozen=True, slots=True)
class _Bore:
    """A hole wider than the grid's own, with the patch of plate it is punched in.

    ``covers`` is the set of tile squares the bore reaches into. They are taken out of the
    tiled surface and this one patch is laid over the lot -- the outer boundary of their
    union, with the bore taken out of the middle. A bore that lands on a hole reaches into
    that tile and its four orthogonal neighbours and no further, which is exactly the set
    ``geometry.consumed_holes`` reports the copper gone from: one bore, one answer, in the
    renderer and in DRC.
    """

    x: float
    y: float
    radius: float
    covers: tuple[_Rect, ...]


def _tile_rect(board: Board, col: int, row: int) -> _Rect:
    half = board.pitch / 2
    x, y = _xy(board, HoleCoord(col, row))
    return (x - half, y - half, x + half, y + half)


def _reach(bore_x: float, bore_y: float, angle: float, rects: tuple[_Rect, ...]) -> float:
    """How far a ray from the bore's centre stays inside a union of rectangles.

    Walked as intervals rather than "the furthest rectangle it hits", because a diagonal
    ray out of a cross-shaped patch leaves through the middle tile's corner and must stop
    there -- the arm it would reach next is not connected along that ray.
    """
    dx, dy = math.cos(angle), math.sin(angle)
    spans: list[tuple[float, float]] = []
    for x0, y0, x1, y1 in rects:
        near, far = 0.0, math.inf
        for origin, delta, low, high in ((bore_x, dx, x0, x1), (bore_y, dy, y0, y1)):
            if abs(delta) < 1e-9:
                if not low <= origin <= high:
                    near, far = 1.0, -1.0
                    break
                continue
            first, second = (low - origin) / delta, (high - origin) / delta
            near = max(near, min(first, second))
            far = min(far, max(first, second))
        if far > max(near, 0.0):
            spans.append((max(near, 0.0), far))
    spans.sort()
    reach = 0.0
    for start, end in spans:
        if start <= reach + 1e-9:
            reach = max(reach, end)
    return reach


def _mounting_bores(doc: PerfDocument) -> list[_Bore]:
    board = doc.board
    bores: list[_Bore] = []
    for mount in doc.mounting_holes:
        # mounting_hole_centre_mm, NEVER hole_to_mm(mount.at): the offset is what puts a
        # corner hole in the border, and this view was drawing every one of them back on
        # the grid -- in the middle of four pads that are perfectly intact.
        centre = mounting_hole_centre_mm(mount, board)
        x, y = centre.x, -centre.y
        radius = mount.diameter / 2
        covers = [
            _tile_rect(board, col, row)
            for col in range(board.cols)
            for row in range(board.rows)
            if _overlaps(_tile_rect(board, col, row), x, y, radius)
        ]
        # Whatever of the bore lies OUTSIDE the tiled grid -- a corner hole in the printed
        # border is entirely outside it -- is patched as a rectangle of its own, clipped so
        # it cannot reach a tile the bore never touched. Growing it to whole tiles instead
        # was the first attempt, and it swallowed the neighbouring hole: the pad was still
        # drawn, over solid board, so the board came out with a blind hole beside every
        # screw.
        margin = radius * 0.2
        covers.extend(
            _rect_without(
                (x - radius - margin, y - radius - margin, x + radius + margin, y + radius + margin),
                _tile_grid_rect(board),
            )
        )
        bores.append(_Bore(x=x, y=y, radius=radius, covers=tuple(covers)))
    return bores


def patched_holes(doc: PerfDocument) -> frozenset[str]:
    """Grid positions a mounting bore's patch has taken over, as ``hole_key`` strings.

    The plate has no hole at these -- the patch is solid board from its outer edge to the
    bore -- so nothing may drill one either, or a tube stands in a place with nothing
    around it. A superset of ``geometry.consumed_holes`` and usually the same set: a bore
    that ate a pad necessarily reaches into that tile.
    """
    board = doc.board
    rects = [rect for bore in _mounting_bores(doc) for rect in bore.covers]
    return frozenset(
        hole_key(HoleCoord(col, row))
        for col in range(board.cols)
        for row in range(board.rows)
        for x, y in (_xy(board, HoleCoord(col, row)),)
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in rects)
    )


def _overlaps(rect: _Rect, x: float, y: float, radius: float) -> bool:
    """Whether a circle reaches into a rectangle. The usual nearest-point test."""
    x0, y0, x1, y1 = rect
    near_x = min(max(x, x0), x1)
    near_y = min(max(y, y0), y1)
    return (near_x - x) ** 2 + (near_y - y) ** 2 < radius**2


class _Mesh:
    """Polygons accumulated by hand, for the parts of the plate there is only one of.

    The tiled surface is glyphed and costs nothing per hole; the border, the bore patches
    and the four edges are a handful of polygons each and go into one actor together.
    """

    def __init__(self) -> None:
        self.points = vtk.vtkPoints()
        self.polys = vtk.vtkCellArray()

    def polygon(self, ring: list[tuple[float, float, float]]) -> None:
        first = self.points.GetNumberOfPoints()
        for x, y, z in ring:
            self.points.InsertNextPoint(x, y, z)
        self.polys.InsertNextCell(len(ring))
        for index in range(len(ring)):
            self.polys.InsertCellPoint(first + index)

    def rectangle(self, rect: _Rect, z: float) -> None:
        x0, y0, x1, y1 = rect
        self.polygon([(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)])

    def data(self) -> vtk.vtkPolyData:
        data = vtk.vtkPolyData()
        data.SetPoints(self.points)
        data.SetPolys(self.polys)
        return data


def _patch(mesh: _Mesh, bore: _Bore, z: float) -> None:
    """The plate around one bore: the outline of the tiles it took, minus the bore."""
    corners = [
        (corner_x, corner_y)
        for x0, y0, x1, y1 in bore.covers
        for corner_x, corner_y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]
    # The corners of the patch are sample points, or its outline would be cut across and
    # leave a gap against the tiles beside it.
    angles = sorted(
        {math.atan2(cy - bore.y, cx - bore.x) % (2 * math.pi) for cx, cy in corners}
        | {2 * math.pi * index / TILE_SIDES for index in range(TILE_SIDES)}
    )
    outer: list[tuple[float, float]] = []
    inner: list[tuple[float, float]] = []
    for angle in angles:
        reach = max(_reach(bore.x, bore.y, angle, bore.covers), bore.radius)
        dx, dy = math.cos(angle), math.sin(angle)
        outer.append((bore.x + reach * dx, bore.y + reach * dy))
        inner.append((bore.x + bore.radius * dx, bore.y + bore.radius * dy))
    for index in range(len(angles)):
        following = (index + 1) % len(angles)
        mesh.polygon(
            [
                (*outer[index], z),
                (*outer[following], z),
                (*inner[following], z),
                (*inner[index], z),
            ]
        )


#: Facets round a hole punched in the board itself, and round the bore's wall. A multiple
#: of four, and the tile is sampled from a corner, so all four corners of a tile are
#: vertices -- a contour that cut them off would leave a pinhole in the board at the
#: corner of every tile.
TILE_SIDES = 24

#: How much wider the hole's wall is than the hole punched in the surface. The wall then
#: sits just BEHIND the rim rather than exactly on it, so no sliver of background can show
#: through the seam between the two.
WALL_OVERSIZE_MM = 0.01


def _tile_with_hole(board: Board) -> vtk.vtkPolyData:
    """One pitch square of substrate with its hole taken out of the middle.

    Tiles are exactly a pitch across, so neighbours share an edge exactly and the tiled
    surface is watertight.
    """
    half = board.pitch / 2
    radius = board.drill_diameter / 2
    angles = [math.pi / 4 + 2 * math.pi * index / TILE_SIDES for index in range(TILE_SIDES)]
    outer: list[tuple[float, float]] = []
    inner: list[tuple[float, float]] = []
    for angle in angles:
        dx, dy = math.cos(angle), math.sin(angle)
        reach = half / max(abs(dx), abs(dy))
        outer.append((reach * dx, reach * dy))
        inner.append((radius * math.cos(angle), radius * math.sin(angle)))
    return _annulus(outer, inner)


def _solid_tile(board: Board) -> vtk.vtkPolyData:
    """The same square with nothing taken out, for a position that was never drilled: an
    edge-connector finger is a solid contact on solid board."""
    half = board.pitch / 2
    mesh = _Mesh()
    mesh.rectangle((-half, -half, half, half), 0.0)
    return mesh.data()


def _glyphed(points: vtk.vtkPoints, source: vtk.vtkPolyData) -> vtk.vtkActor:
    data = vtk.vtkPolyData()
    data.SetPoints(points)
    glyph = vtk.vtkGlyph3DMapper()
    glyph.SetInputData(data)
    glyph.SetSourceData(source)
    glyph.SetOrient(False)
    glyph.SetScaling(False)
    actor = vtk.vtkActor()
    actor.SetMapper(glyph)
    return actor


def build_substrate(doc: PerfDocument) -> list[vtk.vtkActor]:
    """The board itself, WITH ITS HOLES IN IT.

    It used to be one solid cube, and every hole on it was faked by laying a dark cylinder
    over the top. A dark disc on green reads as a mark printed on the board rather than as
    something you can push a lead through -- and on a mounting bore, which has no pad ring
    around it to explain the darkness, it read as a sticker. The fake was chosen because a
    boolean subtraction per hole is thousands of them on a real board, which remains true.
    This is neither: the face is ONE TILE, a pitch square with its hole taken out, glyphed
    at every hole. Both faces come out of the same glyph, so a 945-hole board costs one
    source and two actors rather than 1890 subtractions.

    Three actors: the drilled tiles, the few undrilled ones, and one mesh holding the
    printed border, the patch around each mounting bore and the four edges.
    """
    board = doc.board
    top, bottom = 0.0, -board.thickness
    bores = _mounting_bores(doc)
    patched = [rect for bore in bores for rect in bore.covers]
    undrilled = undrilled_holes(doc)

    drilled_at = vtk.vtkPoints()
    solid_at = vtk.vtkPoints()
    for col in range(board.cols):
        for row in range(board.rows):
            x, y = _xy(board, HoleCoord(col, row))
            if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in patched):
                continue  # A bore took this tile; its patch covers the ground instead.
            target = solid_at if hole_key(HoleCoord(col, row)) in undrilled else drilled_at
            for z in (top, bottom):
                target.InsertNextPoint(x, y, z)

    mesh = _Mesh()
    for z in (top, bottom):
        for rect in _rects_without(_border_rects(board), patched):
            mesh.rectangle(rect, z)
        for bore in bores:
            _patch(mesh, bore, z)
    x0, y0, x1, y1 = board_outline_rect(board)
    for (ax, ay), (bx, by) in (
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    ):
        mesh.polygon([(ax, ay, top), (bx, by, top), (bx, by, bottom), (ax, ay, bottom)])

    rgb = scheme_for(board.material).rgb
    actors: list[vtk.vtkActor] = []
    for points, source in (
        (drilled_at, _tile_with_hole(board)),
        (solid_at, _solid_tile(board)),
    ):
        if points.GetNumberOfPoints() == 0:
            continue
        actors.append(_glyphed(points, source))
    edges = vtk.vtkActor()
    edge_mapper = vtk.vtkPolyDataMapper()
    edge_mapper.SetInputData(mesh.data())
    edges.SetMapper(edge_mapper)
    actors.append(edges)
    for actor in actors:
        actor.GetProperty().SetColor(*rgb)
        _finish(actor.GetProperty(), MASK)
    return actors


#: How far each face's copper stands off the substrate: enough that a flat pad never
#: z-fights the board it lies on, small enough to be invisible.
PAD_LIFT_MM = 0.05

#: How far the dark bore stops SHORT of each face's copper.
#:
#: It used to overshoot by 0.10 mm instead, and a hole that stands proud of its own pad is
#: not a hole. At any grazing angle -- which is most of them, since this view is orbited --
#: every bore showed a black cap standing above the copper and occluding the pads on the
#: rows behind it, so a board read as a grid of black buttons rather than as one with
#: holes drilled through it. Below the copper on both faces, the ring is the topmost thing
#: at every hole, which is what makes it read as a hole.
BORE_UNDER_PAD_MM = 0.015


# ---------------------------------------------------------------------------
# What things are made of
# ---------------------------------------------------------------------------
#
# WHY THE BOARD USED TO LOOK LIKE PAINTED CARD. Every actor was shaded with Phong and a
# pair of hand-picked numbers -- a specular reflectance and an exponent -- which between
# them describe a HIGHLIGHT and say nothing about the material under it. There is no value
# of those two that makes aluminium look like aluminium, because what separates a crystal
# can from a DIP is not the size of its highlight: it is that one of them is a conductor
# and reflects the room in its own colour and the other scatters. Thirty call sites each
# guessed a pair, and the render came out uniformly matte whatever was guessed.
#
# PBR says it in two numbers instead, and both are ones a person can check against a part
# in their hand:
#
#   * ``metallic`` is 0 or 1 and never between. A material either conducts -- tinting what
#     it reflects and having no diffuse colour of its own -- or it does not.
#   * ``roughness`` is how wide it scatters. It is the whole difference between two parts
#     of the same class: moulded epoxy against glossy nylon, a solder fillet against the
#     tinned wire running into it.
#
# The pairs below are the materials actually on a perfboard, named once. A part builder
# names a material rather than inventing numbers, which is what stops two pieces of the
# same physical object -- a solder run and the bead at its end -- being given two finishes
# and drawing a seam that is not there.

#: Moulded epoxy and ABS: a DIP's body, a TO-92, a header's shroud, a switch case.
MOULDED = (0.0, 0.62)
#: Glossy injection-moulded nylon: a screw terminal, a relay case, a potentiometer body.
GLOSS = (0.0, 0.30)
#: Ceramic and phenolic: a disc capacitor, a resistor's own body, the bands printed on it.
CERAMIC = (0.0, 0.66)
#: The printed PVC sleeve shrunk over an electrolytic's can.
SLEEVE = (0.0, 0.28)
#: Tinned copper: a pad, a trimmed lead, a strip of stripboard.
TINNED = (1.0, 0.34)
#: Bright tinned wire, which is what a bare-wire link is. Tighter than a pad because it is
#: drawn wire rather than plated foil.
BRIGHT_TIN = (1.0, 0.18)
#: Solder, and it is ROUGH metal. Making it smooth is what once made a run look like wire,
#: which is the one thing it must not look like.
SOLDER_MAT = (1.0, 0.44)
#: Bare steel and aluminium: a TO-220 tab, a screw head, an electrolytic's crimped rim.
STEEL = (1.0, 0.30)
#: A plated pin. The one part of a board with a mirror finish on it.
PLATED = (1.0, 0.20)
#: Silkscreen ink and the printing on a sleeve: matte, and the only thing on a board that
#: reflects nothing at all.
INK = (0.0, 0.88)
#: Solder mask over laminate. Glossier than anything else large on the board, which is
#: what makes a bare board read as a board.
MASK = (0.0, 0.36)
#: The cut edge of the laminate and the wall of a drilled hole: raw glass-epoxy.
LAMINATE = (0.0, 0.74)
#: PVC insulation on a hook-up wire.
INSULATION = (0.0, 0.40)
#: An LED's epoxy lens: smoother than anything else on the board, because it is cast rather
#: than moulded and it is transmitting rather than reflecting.
LENS = (0.0, 0.06)

#: The names ``ui/models/index.json`` uses for the materials above. A borrowed mesh answers
#: light by the same rules a generated body does, which is the point of not borrowing the
#: source model's own shading.
MODEL_MATERIALS: dict[str, tuple[float, float]] = {
    "moulded": MOULDED,
    "gloss": GLOSS,
    "ceramic": CERAMIC,
    "sleeve": SLEEVE,
    "tinned": TINNED,
    "steel": STEEL,
    "plated": PLATED,
    "lens": LENS,
}


def _to_linear(channel: float) -> float:
    """One sRGB channel as the linear light a physical shader multiplies.

    THE COLOURS IN ``bodies.BODY_STYLES`` ARE sRGB, because they were picked as hex the way
    every colour in this application is picked, and sRGB is what a 2D fill wants. A PBR
    shader wants ALBEDO -- the fraction of light a surface returns -- and the two differ by
    a gamma curve, which is not a small correction: a DIP's #24262d is 0.14 as sRGB and
    0.017 as albedo, and handing the shader the first number renders black epoxy as mid
    grey. Every part on the board came out washed out together, which is the shape of
    mistake that reads as "the lighting is wrong" rather than "the colours are wrong".
    """
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _finish(prop: Any, material: tuple[float, float]) -> None:
    """Shade one actor as a material rather than as a highlight.

    The single place ``SetInterpolationToPBR`` is called, so no actor can be left behind on
    the old model: a scene with both in it lights the two halves by different rules, and
    the half still on Phong reads as a sticker beside the half that is not.

    IT ALSO CONVERTS THE COLOUR, which is why it must be called AFTER ``SetColor`` and not
    before -- see ``_to_linear``. Doing it here rather than at every call site is what makes
    "shaded as a material" and "given an albedo" the same single act: an actor that got one
    without the other is exactly the washed-out part this is here to prevent.
    """
    prop.SetInterpolationToPBR()
    prop.SetMetallic(material[0])
    prop.SetRoughness(material[1])
    prop.SetColor(*(_to_linear(channel) for channel in prop.GetColor()))


def _material_of(surface: Surface) -> tuple[float, float]:
    """The archetype-level material ``bodies.surface_for`` already decided."""
    return (surface.metallic, surface.roughness)


#: How far a contact shadow reaches, in millimetres of board. One hole's width: see
#: ``apply_contact_shadows`` for why it is the whole setting.
CONTACT_SHADOW_MM = 4.0
#: Enough to keep a flat face from shadowing itself, small next to anything real on a board.
CONTACT_SHADOW_BIAS_MM = 0.02
#: Samples per pixel. 32 is where the noise stops showing through the blur on a dense board.
CONTACT_SHADOW_SAMPLES = 32

#: How much rougher a part goes when it is not the subject of a guide step, and how
#: smooth the one that IS goes. See ``_dim`` and ``_pick_out``; they are a pair and the
#: numbers only mean anything against each other.
DIM_ROUGHEN = 0.30
PICK_OUT_ROUGHNESS = 0.30


def pad_z(board: Board, side: BoardSide) -> float:
    """Where one face's copper sits, in board z. Pure, so it can be asserted directly."""
    return PAD_LIFT_MM if side == "top" else -board.thickness - PAD_LIFT_MM


def bore_span_z(board: Board) -> tuple[float, float]:
    """The dark bore's top and bottom, in board z. Pure, for the reason ``pad_z`` is.

    Between the two faces' copper and never past it, while still standing clear of the
    substrate's own faces: the bore has to be visible through the pad's hole from either
    side without standing above the metal around it.
    """
    return (
        pad_z(board, "top") - BORE_UNDER_PAD_MM,
        pad_z(board, "bottom") + BORE_UNDER_PAD_MM,
    )


#: What a conductor measures on the board, in mm.
#:
#: A SOLDER RUN is two numbers, because it is not a uniform thing: a mound on each pad it
#: is soldered to, and a narrower bridge of solder between them. That narrowing is not
#: decoration -- it is what makes the joints countable, and counting joints along a run
#: against the real board is exactly what somebody following the build guide does.
#: 1.2 mm across a joint sits inside a 1.9 mm pad and leaves the copper ring showing;
#: 0.72 mm across the bridge still spans the 0.64 mm gap to the next pad, which is what a
#: run is for.
#:
#: The tube was 0.34 mm at a constant radius with a 1.9x SPHERE dropped on every pad. Under
#: half a real run, thinner than its own joints, and two primitives meeting in a hard
#: crease all the way round -- so it read as balls threaded on a stick, a molecular model
#: rather than a length of solder. It is one varying-radius surface now; see
#: ``_trace_swell``.
TRACE_JOINT_RADIUS_MM = 0.72
TRACE_WAIST_RATIO = 0.52

#: How tall a run stands against how wide it is. Solder WETS copper and spreads: a run is a
#: low bright ridge and a dome on each pad, not a pipe -- and a round tube, however its
#: radius swells, read as grey plumbing laid on the board. Squashed about the copper it is
#: fused to, so the joints and the bridges keep their silhouette from above and lose the
#: height that made them tubes.
TRACE_FLATTEN = 0.5

#: Points along a run per step from one pad to the next. Two -- a pad and a midpoint --
#: made the radius change in straight lines, and a run's outline came out as a row of
#: diamonds; with this many the swell follows a cosine and the outline is round.
TRACE_SAMPLES_PER_STEP = 8

#: The fillet of solder round a lead or a wire end where it goes through its pad: out to
#: this radius on the copper, up the lead this far. A joint is a cone with a concave flank
#: -- a meniscus -- and it is what makes a board look soldered at all: without it a lead
#: came out of a bare ring, which is a board nobody has finished.
SOLDER_FILLET_BASE_MM = 0.80
SOLDER_FILLET_HEIGHT_MM = 0.55

#: How much insulation is stripped off each end of an insulated wire, and the tinned core
#: that shows there and goes down into the hole. A sleeve running right into the joint was
#: a coloured capsule sitting on two pads.
WIRE_STRIP_MM = 1.1
WIRE_CORE_RADIUS_MM = 0.24

#: The radius a wire is bent round, at every corner of its run and where it turns down
#: into its hole. Wire is bent over a finger or a pair of pliers, not folded: a 90-degree
#: mitre in a tube reads as plumbing, which is what an insulated wire looked like.
WIRE_BEND_RADIUS_MM = 0.9

#: 24 AWG hookup wire over the sleeve, and tinned copper for a bare link or a spine.
BARE_WIRE_RADIUS_MM = 0.30
INSULATED_RADIUS_MM = 0.55

#: A wire's two ends get a solder fillet and its length gets none, which is the distinction
#: ``contacts_every_path_hole`` draws and the single most important thing this view says.
#: Modest, because a joint on the end of a wire is a fillet around it, not a bead on it.
BEAD_RATIO_WIRE = 1.20

#: Facets round a drilled hole and round a pad's outline. Twelve made every hole on the
#: board a visible dodecagon as soon as anyone looked closely -- and a perfboard is mostly
#: holes, so that one number set how machine-made the whole thing looked. Both are ONE
#: glyphed source instanced at every hole, so the cost is per board and not per hole.
BORE_SIDES = 28
PAD_SEGMENTS = 40

#: Facets round a tube and round a fillet. Ten and twelve were enough at the whole-board
#: zoom the default camera gives and visibly polygonal as soon as anyone looked closely at
#: a joint -- which is the thing they are most likely to want to look closely at.
TUBE_SIDES = 20
BEAD_RESOLUTION = 20

#: How far one stacking level lifts a conductor clear of the one it crosses.
#:
#: DERIVED FROM THE RADII ABOVE, not chosen: the worst pair that can actually cross is an
#: insulated wire over a solder run, and their tubes stop overlapping when their centres
#: are the sum of the two radii apart. Anything less does not fix the thing stacking
#: exists for -- which is what the 0.08 mm this used to be did not, being a tenth of what
#: two tubes needed, while the offset still accumulated: the level was a running index
#: over every conductor on the board, putting the last one on the dense fixture 4.47 mm
#: off a board 1.6 mm thick. It bought levitation and no clearance.
#: ``occupancy.stacking_layers`` now lifts only what actually crosses something, which is
#: what makes a step this size affordable.
#: How far each stands off its centreline UPWARD -- a run squashed by TRACE_FLATTEN -- and
#: the step is twice the tallest: two of the same kind can cross, and since runs were
#: squashed the tallest pair is two insulated wires, not a wire over a run.
STACK_STEP_MM = (
    2 * max(INSULATED_RADIUS_MM, TRACE_JOINT_RADIUS_MM * TRACE_FLATTEN, BARE_WIRE_RADIUS_MM)
    + 0.15
)


def conductor_radius(cond: Conductor) -> float:
    """The tube one conductor is drawn as. Read by ``build_conductor`` and by
    :func:`conductor_z`, which needs it to rest the tube ON the copper rather than near
    it."""
    if contacts_every_path_hole(cond):
        return TRACE_JOINT_RADIUS_MM  # the widest it gets, which is what has to clear
    if cond.kind in ("insulated-wire", "top-jumper"):
        return INSULATED_RADIUS_MM
    return BARE_WIRE_RADIUS_MM


def conductor_z(cond: Conductor, board: Board, stack: int = 0) -> float:
    """Where one conductor sits, in board z.

    Split out from ``build_conductor`` because the interesting property is arithmetic and
    testing it through VTK means reaching into an unexecuted pipeline, which segfaults.

    RESTING ON THE COPPER, not near it. The height used to be a constant 0.5 mm clear of
    the substrate, which is 0.45 from the pad surface -- and with a 0.34 mm trace radius
    that leaves 0.11 mm of daylight between a solder run and the pad it is supposedly
    soldered to. Small, and visible as a shadow line under every run: it read as floating,
    which is the one thing solder does not do. Taking the radius off the PAD plane makes
    the tube tangent to the copper by construction, for a wire lying on the board as much
    as for a run fused to it, and takes a magic number out of the file.

    The beads at each joint are deliberately larger than that and so reach into the
    substrate. That is correct: a fillet wicks into the hole, the board is opaque, and
    what shows on the surface is the dome.

    ``stack`` is the conductor's level from ``occupancy.stacking_layers`` -- how many
    conductors it has to pass over. Everything on the solder side used to sit at one z per
    ``layer_z``, so two crossing bare wires were drawn INTERSECTING: occupying the same
    space, which is not a thing wire does and looked like a modelling error because it was
    one. See :data:`STACK_STEP_MM` for why the first attempt at fixing that did not.
    """
    # ``stack`` is the WHOLE answer, from ``occupancy.stacking_layers``, which already has
    # the document's own ``layer_z`` as its floor. Adding layer_z again here is what put
    # conductors the stacker had deliberately separated back at one height -- one at
    # layer_z 1 and stack 0, the other at layer_z 0 and stack 1 -- and drew them straight
    # through each other on four of the fifteen golden fixtures.
    lift = STACK_STEP_MM * stack
    # A RUN IS IN THE SURFACE; A WIRE IS ON IT. Solder wets the copper and stands as a
    # half-round ridge over it, so a run's centreline is the pad plane itself and only its
    # outer half shows -- which is also why a joint swells concentrically out of it instead
    # of hanging off its back. A wire lies on top of the board and touches it along one
    # line, so its centreline is a radius clear.
    #
    # The distinction is the one this view exists to make (PLAN.md Sec 8.3), and it is now
    # in the geometry rather than only in the colour.
    standoff = 0.0 if contacts_every_path_hole(cond) else conductor_radius(cond)
    if cond.side == "bottom":
        return pad_z(board, "bottom") - standoff - lift
    return pad_z(board, "top") + standoff + lift


def _stadium_contour(extent_x: float, extent_y: float, count: int) -> list[tuple[float, float]]:
    """Points around a stadium: a rectangle capped with a semicircle at each end.

    That is what an oblong pad is -- not an ellipse, which is what scaling a disc would
    give and what the copper visibly is not. A round pad falls out of the same code with
    a zero-length straight section, so there is one contour routine rather than two.
    """
    radius = min(extent_x, extent_y) / 2
    half = (max(extent_x, extent_y) - min(extent_x, extent_y)) / 2
    vertical = extent_y >= extent_x
    per_arc = max(3, count // 2)
    points: list[tuple[float, float]] = []
    for cap in (1.0, -1.0):
        for i in range(per_arc):
            # Each arc runs a half turn; the straight sides are the polygon edges between
            # the end of one arc and the start of the next, so they need no points of
            # their own.
            angle = math.pi * i / (per_arc - 1)
            dx = radius * math.cos(angle) * cap
            dy = radius * math.sin(angle) * cap
            if vertical:
                points.append((dx, dy + cap * half))
            else:
                points.append((dy + cap * half, dx))
    return points


def _pad_annulus(board: Board) -> vtk.vtkPolyData:
    """One pad as a flat ring: a stadium (or circle) outline with the drill punched out.

    Built by hand rather than with ``vtkDiskSource`` because that source only makes
    circles, and an oblong pad is the shape the board actually has. Still ONE source,
    glyphed at every hole, so the instanced-rendering claim this view exists to prove is
    unaffected.
    """
    extent_x, extent_y = pad_extent_mm(board)
    outer = _stadium_contour(extent_x, extent_y, PAD_SEGMENTS)
    n = len(outer)
    drill_r = board.drill_diameter / 2
    inner = [
        (drill_r * math.cos(2 * math.pi * i / n), drill_r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    return _annulus(outer, inner)


def _annulus(
    outer: list[tuple[float, float]], inner: list[tuple[float, float]]
) -> vtk.vtkPolyData:
    """A flat ring between two closed contours, paired point by point.

    Every punched surface here is one of these -- a pad, a tile of substrate, the patch of
    board around a mounting bore -- so the winding and the pairing are decided once rather
    than three times. The two contours need the same number of points and nothing else:
    the pad's outer contour is a stadium walked by arc and its inner one a circle walked by
    angle, and the quads between them are none the worse for it.
    """
    n = len(outer)
    points = vtk.vtkPoints()
    for x, y in (*outer, *inner):
        points.InsertNextPoint(x, y, 0.0)
    polys = vtk.vtkCellArray()
    for i in range(n):
        j = (i + 1) % n
        polys.InsertNextCell(4)
        for index in (i, j, n + j, n + i):
            polys.InsertCellPoint(index)
    data = vtk.vtkPolyData()
    data.SetPoints(points)
    data.SetPolys(polys)
    return data


def _hole_wall(board: Board, radius: float) -> vtk.vtkPolyData:
    """The inside of one hole: a tube through the board, open at both ends.

    OPEN is the point. A capped cylinder is a plug -- it was the plug this view used to
    fake every hole with, and you cannot see through a plug. With the surface punched
    (see :func:`build_substrate`) this is the wall the drill left, and a hole shows what
    is behind the board, which is what a hole does.
    """
    wall = vtk.vtkCylinderSource()
    wall.SetRadius(radius + WALL_OVERSIZE_MM)
    wall.SetHeight(board.thickness)
    wall.SetResolution(BORE_SIDES)
    wall.CappingOff()
    wall.Update()
    upright = vtk.vtkTransform()
    upright.RotateX(90)  # vtkCylinderSource stands along Y; thickness is along Z.
    turn = vtk.vtkTransformPolyDataFilter()
    turn.SetTransform(upright)
    turn.SetInputData(wall.GetOutput())
    turn.Update()
    return turn.GetOutput()


def build_drills(board: Board, consumed: frozenset[str] = frozenset()) -> vtk.vtkActor:
    """Every hole's wall, in one instanced actor.

    THE BOARD HAD NO HOLES FROM UNDERNEATH before any of this: the substrate was one cube
    and the pads sat only on top, so turning the board over showed a blank green slab, on
    the very view whose job is to check the solder side. The first answer was a dark
    cylinder laid over the surface, which is what this replaces.
    """
    points = vtk.vtkPoints()
    for col in range(board.cols):
        for row in range(board.rows):
            # A mounting bore is a bigger hole in the same place, walled by
            # `build_mounting_holes`. Leaving this one in as well puts a 1 mm tube inside
            # a 3.2 mm one, which z-fights along its whole length.
            if consumed and hole_key(HoleCoord(col, row)) in consumed:
                continue
            x, y = _xy(board, HoleCoord(col, row))
            points.InsertNextPoint(x, y, -board.thickness / 2)

    actor = _glyphed(points, _hole_wall(board, board.drill_diameter / 2))
    prop = actor.GetProperty()
    # The cut edge of the laminate, in shadow: darker than the face, and the same hue --
    # a hole in a brown phenolic board is not the same colour as one in green FR-4.
    prop.SetColor(*(channel * 0.55 for channel in scheme_for(board.material).rgb))
    _finish(prop, LAMINATE)
    return actor


def build_pads(
    board: Board, side: BoardSide = "top", consumed: frozenset[str] = frozenset()
) -> vtk.vtkActor:
    """Every pad on one face, in one instanced actor. The scalability claim, tested.

    Called for BOTH faces. The boards this is modelled on are plated through-hole with an
    annular ring on each side, which is also why the solder side is somewhere you can
    solder at all -- and until now the underside had no copper on it whatsoever.

    An annulus, not a disc: a pad with no hole in it makes the board read as a dotted
    sheet rather than as perfboard, and the hole is the entire point of the part.
    """
    z = pad_z(board, side)
    points = vtk.vtkPoints()
    for col in range(board.cols):
        for row in range(board.rows):
            if consumed and hole_key(HoleCoord(col, row)) in consumed:
                continue  # A mounting bore took this pad's copper away.
            x, y = _xy(board, HoleCoord(col, row))
            points.InsertNextPoint(x, y, z)
    data = vtk.vtkPolyData()
    data.SetPoints(points)

    glyph = vtk.vtkGlyph3DMapper()
    glyph.SetInputData(data)
    glyph.SetSourceData(_pad_annulus(board))
    glyph.SetOrient(False)
    glyph.SetScaling(False)

    actor = vtk.vtkActor()
    actor.SetMapper(glyph)
    actor.GetProperty().SetColor(*scheme_for(board.material).pad_rgb)
    _finish(actor.GetProperty(), TINNED)
    return actor


def build_strips(doc: PerfDocument) -> list[vtk.vtkActor]:
    """The copper a stripboard came with, as one bar per uncut run.

    On the solder side only, because that is the only side it is on. Without it the 3D
    view of a stripboard shows a grid of separate pads -- which is a picture of a
    different board, and this view exists to be checked against the real one.

    One thin box per segment rather than per hole: a 30 x 20 board has 20 of them against
    600 pads, and the strip has to read as one continuous piece of copper anyway.
    """
    runs = segments(doc)
    if not runs:
        return []
    board = doc.board
    extent_x, extent_y = pad_extent_mm(board)
    z = pad_z(board, "bottom")
    actors: list[vtk.vtkActor] = []
    for run in runs:
        first_x, first_y = _xy(board, run.holes[0])
        last_x, last_y = _xy(board, run.holes[-1])
        bar = vtk.vtkCubeSource()
        bar.SetXLength(abs(last_x - first_x) + extent_x)
        bar.SetYLength(abs(last_y - first_y) + extent_y)
        # Thin enough to read as foil rather than as a rail standing off the board, and
        # thick enough that the renderer does not fight the substrate for the same plane.
        bar.SetZLength(0.06)
        actor = vtk.vtkActor()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(bar.GetOutputPort())
        actor.SetMapper(mapper)
        actor.SetPosition((first_x + last_x) / 2, (first_y + last_y) / 2, z)
        actor.GetProperty().SetColor(*scheme_for(board.material).pad_rgb)
        _finish(actor.GetProperty(), TINNED)
        actors.append(actor)
    return actors


def build_mounting_holes(doc: PerfDocument) -> list[vtk.vtkActor]:
    """The screw bores' walls. The plate around them is punched by :func:`build_substrate`.

    A mounting hole is where the old fake was worst. Every other hole had a copper ring
    round it, which explained the darkness in the middle; a bore has its copper taken away,
    so a dark disc lying on bare green read as a sticker on the board rather than a hole
    through it. It is punched now, like every other hole and by the same machinery, which
    is also what stops the two reading as different kinds of thing.
    """
    board = doc.board
    if not doc.mounting_holes:
        return []
    actors: list[vtk.vtkActor] = []
    for bore in _mounting_bores(doc):
        points = vtk.vtkPoints()
        points.InsertNextPoint(bore.x, bore.y, -board.thickness / 2)
        actor = _glyphed(points, _hole_wall(board, bore.radius))
        prop = actor.GetProperty()
        prop.SetColor(*(channel * 0.55 for channel in scheme_for(board.material).rgb))
        _finish(prop, LAMINATE)
        actors.append(actor)
    return actors


def build_edge_connectors(doc: PerfDocument) -> list[vtk.vtkActor]:
    """Connector fingers, as thin copper plates lying on the board's faces."""
    board = doc.board
    actors: list[vtk.vtkActor] = []
    for connector in doc.edge_connectors:
        faces: tuple[BoardSide, ...] = (
            ("top", "bottom") if connector.face == "both" else (connector.face,)
        )
        for face in faces:
            if board.single_sided and face == "top":
                continue  # No copper on the component side at all -- see Board.single_sided.
            append = vtk.vtkAppendPolyData()
            # Only the fingers a bore has not drilled through -- see
            # geometry.surviving_finger_holes, which view2d asks the same question of.
            for hole in surviving_finger_holes(doc, connector):
                rect = edge_finger_rect(connector, hole, board)
                plate = vtk.vtkCubeSource()
                plate.SetXLength(rect.width)
                plate.SetYLength(rect.height)
                plate.SetZLength(0.05)
                # Board y runs downward while 3D y runs up, so the rect's y interval is
                # negated -- the same flip `_xy` applies to every hole in this file.
                plate.SetCenter(
                    rect.x + rect.width / 2,
                    -(rect.y + rect.height / 2),
                    pad_z(board, face),
                )
                plate.Update()
                append.AddInputData(plate.GetOutput())
            if append.GetNumberOfInputConnections(0) == 0:
                continue
            append.Update()
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(append.GetOutputPort())
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*scheme_for(board.material).pad_rgb)
            _finish(actor.GetProperty(), TINNED)
            actors.append(actor)
    return actors


def build_legend(doc: PerfDocument) -> list[vtk.vtkActor]:
    """The addresses printed on the substrate, as flat text on the board's faces.

    Every label of one face goes into ONE actor. A vtkVectorText per label would be a
    hundred actors on a modest board and several hundred on a real one, which is the same
    mistake the pad grid exists to avoid -- and a legend is not worth more actors than
    the copper.
    """
    labels = doc.board.labels
    if labels is None:
        return []
    board = doc.board
    # The strip of bare substrate between the outermost pads and the board edge -- NOT the
    # whole margin, which the pads eat half their extent of. Same reasoning, and the same
    # arithmetic, as view2d.BoardLegendItem._free_strip_mm: the two views have to print the
    # legend in the same place or the 3D board stops matching the one being edited.
    # Asked of the DOCUMENT, not the board: an edge carrying connector fingers has only
    # whatever inset those fingers left, and the 2D legend measures it the same way.
    strip_x = legend_strip_mm(doc, "horizontal")
    strip_y = legend_strip_mm(doc, "vertical")
    margin_x = board_edge_margin_mm(board, "horizontal")
    margin_y = board_edge_margin_mm(board, "vertical")
    height = min(1.15, min(strip_x, strip_y) * 0.6)
    faces: tuple[BoardSide, ...] = (
        ("top", "bottom") if labels.face == "both" else (labels.face,)
    )

    actors: list[vtk.vtkActor] = []
    for face in faces:
        append = vtk.vtkAppendPolyData()
        # (text, x, y, widest it may be) -- the width limits differ between the two runs
        # because their free axes are swapped, exactly as in the 2D legend.
        # 3D y runs up where board rows run down, so the top border is at POSITIVE y here.
        #
        # Measured IN FROM THE BOARD EDGE, exactly as view2d does and for the same reason:
        # out from the pad puts the column letters on top of the connector fingers, which
        # reach most of the way to the edge on the board this application opens on.
        span_w = (board.cols - 1) * board.pitch
        span_h = (board.rows - 1) * board.pitch
        column_ys = [margin_y - strip_y / 2]
        row_xs = [-(margin_x - strip_x / 2)]
        if labels.all_edges:
            column_ys.append(-span_h - margin_y + strip_y / 2)
            row_xs.append(span_w + margin_x - strip_x / 2)
        # Row numbers are turned on their side, as they are on the real boards and in the
        # 2D view: the strip beside a row is narrow across and a whole pitch deep, so a
        # turned number fits where an upright one has to shrink.
        entries: list[tuple[str, float, float, float, float]] = [
            (column_label(col), col * board.pitch, y, board.pitch * 0.9, 0.0)
            for col in range(board.cols)
            for y in column_ys
        ]
        entries += [
            (printed_row_label(row, labels), x, -row * board.pitch, board.pitch * 0.9, 90.0)
            for row in range(board.rows)
            for x in row_xs
        ]
        for text, x, y, max_width, rotate in entries:
            # Not printed where a bore was drilled -- the same question view2d asks, in
            # the same units: board millimetres with y growing DOWN, so 3D's y is negated
            # on the way in. A turned number's box is turned with it.
            box = (height, max_width) if rotate else (max_width, height)
            if not printed_label_is_clear(doc, Point2(x, -y), box[0], box[1]):
                continue
            vector = vtk.vtkVectorText()
            vector.SetText(text)
            vector.Update()
            bounds = vector.GetOutput().GetBounds()
            # vtkVectorText is roughly one unit tall and starts at the origin, so it is
            # scaled to the wanted cap height and then centred on its own bounds.
            scale = height
            text_width = max(bounds[1] - bounds[0], 1e-6)
            if text_width * scale > max_width:
                scale = max_width / text_width
            transform = vtk.vtkTransform()
            transform.Translate(x, y, 0.0)
            if face == "bottom":
                # Ink on the underside, being looked at from underneath: each glyph is
                # reflected about its OWN centre, or turning the board over in 3D shows the
                # legend written backwards. This is the one view where the text is a
                # physical object seen directly rather than an annotation drawn over a
                # picture. (view2d deliberately does the opposite for the face it sees
                # THROUGH the board: reversed 1 mm text is noise there.)
                #
                # ONLY the glyph. Its position is already the physical one, under the column
                # it names, and the camera turning over is what mirrors the picture. The
                # whole legend used to be reflected about the hole span as well, which
                # mirrored it twice: column A was labelled "AH" on the underside, and a
                # one-edge legend moved to the other edge from the one the 2D view prints.
                transform.Scale(-1.0, 1.0, 1.0)
            if rotate:
                transform.RotateZ(rotate)
            transform.Scale(scale, scale, scale)
            transform.Translate(
                -(bounds[0] + bounds[1]) / 2, -(bounds[2] + bounds[3]) / 2, 0.0
            )
            placed = vtk.vtkTransformPolyDataFilter()
            placed.SetTransform(transform)
            placed.SetInputData(vector.GetOutput())
            placed.Update()
            append.AddInputData(placed.GetOutput())
        append.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(append.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        # Just clear of the substrate, on whichever face carries the print. Silkscreen is
        # ink: unlit and matte, so it does not catch highlights the way copper does.
        actor.SetPosition(0.0, 0.0, 0.02 if face == "top" else -board.thickness - 0.02)
        actor.GetProperty().SetColor(*LEGEND_RGB)
        _finish(actor.GetProperty(), INK)
        actors.append(actor)
    return actors


# ------------------------------------------------------- parametric component bodies
#
# One solid per archetype, built from the dimensions already in the footprint registry
# (PLAN.md D6: parametric generation, no mesh library, no share-alike asset licence).
# Previously every part was one grey cube sized from its COURTYARD -- which is padded well
# beyond the physical part -- so a resistor, a DIP and a 10 mm electrolytic were the same
# oversized block. See ui/bodies.py for where the real dimensions come from.


@dataclass(frozen=True, slots=True)
class _Piece:
    """One solid of one component. Positioned by the actor, not baked into the source.

    VTK applies an actor's scale, then its orientation, then its position, so every source
    below is built centred on the origin and placed afterwards. That is what lets a single
    cylinder source serve as an upright can, a lying resistor body and -- squashed by a
    non-uniform scale -- an oval crystal can.
    """

    source: Any
    rgb: tuple[float, float, float]
    position: tuple[float, float, float]
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    #: Euler angles in degrees, as VTK's actor orientation.
    orientation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: What the solid is made of, as ``(metallic, roughness)`` -- one of the named pairs
    #: above, never two numbers invented here. See the material table's own comment.
    material: tuple[float, float] = MOULDED
    opacity: float = 1.0
    #: When set, the source is glyphed at each of these world positions in ONE actor and
    #: ``position`` is ignored. For repeated identical solids -- a header's pins -- where an
    #: actor each would cost more than the whole instanced pad grid.
    instances: tuple[tuple[float, float, float], ...] = ()


#: vtkCylinderSource points along +Y. These turn it along each world axis.
_ALONG_X = (0.0, 0.0, 90.0)
_ALONG_Y = (0.0, 0.0, 0.0)
_ALONG_Z = (90.0, 0.0, 0.0)


def _upright_scale(scale: tuple[float, float, float]) -> tuple[float, float, float]:
    """A world scale rewritten for a cylinder stood upright by ``_ALONG_Z``.

    VTK scales BEFORE it orients, and that turn maps the source's own z onto world y -- so
    a scale written to flatten the world y of an upright can flattens its LENGTH instead.
    The crystal came out a quarter too short with its domed cap floating in the air above
    it, which is what measuring the actors' bounds says and what squinting at the render
    did not.
    """
    return (scale[0], 1.0, scale[1])

#: Component bodies sit this far above the board so they never z-fight with the pads.
_LIFT = 0.12


def _box(x: float, y: float, z: float) -> Any:
    cube = vtk.vtkCubeSource()
    cube.SetXLength(x)
    cube.SetYLength(y)
    cube.SetZLength(z)
    cube.SetCenter(0.0, 0.0, 0.0)
    return cube


#: How much of a moulded case's edge is broken, in millimetres.
#:
#: There is no such thing as a knife edge out of an injection tool: every moulded part has
#: a break on every edge, and it is what a highlight runs along. Small enough to read as a
#: highlight rather than as a shape of its own.
CHAMFER_MM = 0.3


def _moulded_box(x: float, y: float, z: float) -> vtk.vtkPolyData:
    """A box with its top and bottom edges broken, which is what a plastic case has.

    A ``vtkCubeSource`` meets its neighbours at a knife edge, and a knife edge takes exactly
    one shade: this face is flat, the next face is flat, and the boundary between them is a
    line. That is most of why a DIP read as a black rectangle rather than as a piece of
    plastic -- an eye finds an object's edge in the highlight running along it, and there
    was nowhere for one to sit. It costs 16 vertices.

    Only the HORIZONTAL edges are cut. From anywhere this view is looked at, the top edge
    is the one seen against the board; cutting the four vertical corners as well doubles the
    geometry to change a silhouette nobody is looking at.
    """
    chamfer = min(CHAMFER_MM, x / 4, y / 4, z / 3)
    corners = ((0.5, 0.5), (-0.5, 0.5), (-0.5, -0.5), (0.5, -0.5))
    rings = (
        (-z / 2, x - 2 * chamfer, y - 2 * chamfer),
        (-z / 2 + chamfer, x, y),
        (z / 2 - chamfer, x, y),
        (z / 2, x - 2 * chamfer, y - 2 * chamfer),
    )
    points = vtk.vtkPoints()
    for height, width, depth in rings:
        for u, v in corners:
            points.InsertNextPoint(u * width, v * depth, height)
    faces = vtk.vtkCellArray()
    for ring in range(3):
        low, high = ring * 4, (ring + 1) * 4
        for index in range(4):
            nxt = (index + 1) % 4
            faces.InsertNextCell(4)
            for point in (low + index, low + nxt, high + nxt, high + index):
                faces.InsertCellPoint(point)
    for cap, order in ((0, (0, 3, 2, 1)), (12, (0, 1, 2, 3))):
        faces.InsertNextCell(4)
        for index in order:
            faces.InsertCellPoint(cap + index)
    box = vtk.vtkPolyData()
    box.SetPoints(points)
    box.SetPolys(faces)
    # Per-face normals, and the feature angle keeps the chamfer a crease rather than
    # smearing it into the faces either side -- a rounded-looking DIP is the other way to
    # get this wrong.
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(box)
    normals.SetFeatureAngle(30.0)
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOn()
    normals.Update()
    result: vtk.vtkPolyData = normals.GetOutput()
    return result


def _cylinder(radius: float, height: float, resolution: int = 32) -> Any:
    cyl = vtk.vtkCylinderSource()
    cyl.SetRadius(radius)
    cyl.SetHeight(height)
    cyl.SetResolution(resolution)
    cyl.SetCenter(0.0, 0.0, 0.0)
    cyl.CappingOn()
    return cyl


def _upright_cylinder(radius: float, height: float, resolution: int = 12) -> Any:
    """A cylinder standing along Z, ready to be glyphed at every pin of one component.

    The turn is baked into the SOURCE rather than set on the actor because the instanced
    path in ``_actor_for`` has no actor to turn -- one glyph mapper draws every copy, and
    ``SetOrient(False)`` means each copy arrives exactly as the source was built.

    ``SetInputData`` and not ``SetInputConnection``: a connection keeps a RAW pointer back
    to the algorithm that produced it, and the cylinder here is a local that dies with
    this function. Connecting one segfaults the interpreter outright -- measured, not
    feared. Handing over the computed polydata takes a real reference to it and leaves no
    producer to outlive.
    """
    cylinder = _cylinder(radius, height, resolution)
    cylinder.Update()
    upright = vtk.vtkTransform()
    upright.RotateX(90)
    turn = vtk.vtkTransformPolyDataFilter()
    turn.SetTransform(upright)
    turn.SetInputData(cylinder.GetOutput())
    turn.Update()
    return turn


def _d_prism(radius: float, flat: float, height: float, resolution: int = 22) -> vtk.vtkPolyData:
    """A cylinder with ONE side flattened, standing along Z: the shape of a TO-92.

    The flat is not decoration -- it is the only thing on the package that says which way
    round the three legs go, and squashing a cylinder to fake it gives an ellipse, which
    has two flats and marks nothing. Built as a profile rather than as a source because
    VTK has no source for it.
    """
    limit = math.asin(min(max(flat / radius, -1.0), 1.0))
    span = math.pi + 2 * limit
    profile = [
        (
            radius * math.cos(math.pi - limit + span * index / (resolution - 1)),
            radius * math.sin(math.pi - limit + span * index / (resolution - 1)),
        )
        for index in range(resolution)
    ]
    mesh = _Mesh()
    top, bottom = height / 2, -height / 2
    mesh.polygon([(x, y, top) for x, y in profile])
    mesh.polygon([(x, y, bottom) for x, y in reversed(profile)])
    for index in range(len(profile)):
        (ax, ay), (bx, by) = profile[index], profile[(index + 1) % len(profile)]
        mesh.polygon([(ax, ay, bottom), (bx, by, bottom), (bx, by, top), (ax, ay, top)])
    return mesh.data()


def _lathe(profile: list[tuple[float, float]], resolution: int = 48) -> vtk.vtkPolyData:
    """A turned part, from its ``(radius, z)`` profile read bottom to top and swept about Z.

    That is how a turned part is drawn on its own datasheet, and it is the only way to get a
    thread or a chamfer onto a round part: a stack of cylinders meets itself in flat rings
    that catch no light. The profile starts and ends on the axis, so the sweep closes itself.
    Corners sharper than the feature angle stay creases -- a thread's crest, a shaft's
    shoulder -- and everything else is shaded round.
    """
    points = vtk.vtkPoints()
    line = vtk.vtkCellArray()
    line.InsertNextCell(len(profile))
    for index, (radius, z) in enumerate(profile):
        points.InsertNextPoint(radius, 0.0, z)
        line.InsertCellPoint(index)
    outline = vtk.vtkPolyData()
    outline.SetPoints(points)
    outline.SetLines(line)
    sweep = vtk.vtkRotationalExtrusionFilter()
    sweep.SetInputData(outline)
    sweep.SetResolution(resolution)
    sweep.SetAngle(360.0)
    sweep.CappingOff()
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputConnection(sweep.GetOutputPort())
    normals.SetFeatureAngle(50.0)
    normals.SplittingOn()
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.Update()
    result: vtk.vtkPolyData = normals.GetOutput()
    return result


def _rounded_case(x: float, y: float, z: float, corner: float) -> vtk.vtkPolyData:
    """``_moulded_box`` with its four vertical edges rounded to ``corner``: a sealed case.

    A DIP's corners are sharp enough that nobody sees them, which is why ``_moulded_box``
    does not spend geometry on them. A relay is a 15 mm cube standing over everything round
    it, and a cube with knife-edge corners at that size is the look of a placeholder; the
    radius is what a moulded cover of that size has, and the highlight down each corner is
    what reads as one.
    """
    chamfer = min(CHAMFER_MM, x / 4, y / 4, z / 3)
    corner = min(corner, x / 2 - chamfer, y / 2 - chamfer)
    steps = 6

    def ring(width: float, depth: float, height: float) -> list[tuple[float, float, float]]:
        points = []
        for cx, cy, start in (
            (width / 2 - corner, depth / 2 - corner, 0.0),
            (-width / 2 + corner, depth / 2 - corner, 90.0),
            (-width / 2 + corner, -depth / 2 + corner, 180.0),
            (width / 2 - corner, -depth / 2 + corner, 270.0),
        ):
            for step in range(steps + 1):
                angle = math.radians(start + 90.0 * step / steps)
                points.append((cx + corner * math.cos(angle), cy + corner * math.sin(angle), height))
        return points

    rings = [
        ring(x - 2 * chamfer, y - 2 * chamfer, -z / 2),
        ring(x, y, -z / 2 + chamfer),
        ring(x, y, z / 2 - chamfer),
        ring(x - 2 * chamfer, y - 2 * chamfer, z / 2),
    ]
    mesh = _Mesh()
    for low, high in pairwise(rings):
        for index in range(len(low)):
            nxt = (index + 1) % len(low)
            mesh.polygon([low[index], low[nxt], high[nxt], high[index]])
    mesh.polygon(list(reversed(rings[0])))
    mesh.polygon(rings[-1])
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(mesh.data())
    normals.SetFeatureAngle(30.0)
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOn()
    normals.Update()
    result: vtk.vtkPolyData = normals.GetOutput()
    return result


def _knurled_prism(radius: float, height: float, teeth: int = 18) -> vtk.vtkPolyData:
    """A knurled shaft, standing along Z from 0 to ``height``: ``teeth`` straight ridges.

    A plain cylinder is a peg; the ridges are what say "turn me" -- a potentiometer's shaft
    is knurled so a push-on knob grips it, eighteen teeth being the usual count. Faceted on
    purpose: the flat faces between ridges are what catch the light as a knurl does. Capped
    as a fan from the axis, because the star is not convex and a polygon that is not convex
    is drawn wrong.
    """
    ring = [
        (
            (radius if index % 2 == 0 else radius * 0.88) * math.cos(math.pi * index / teeth),
            (radius if index % 2 == 0 else radius * 0.88) * math.sin(math.pi * index / teeth),
        )
        for index in range(2 * teeth)
    ]
    mesh = _Mesh()
    for index in range(len(ring)):
        (ax, ay), (bx, by) = ring[index], ring[(index + 1) % len(ring)]
        mesh.polygon([(0.0, 0.0, height), (ax, ay, height), (bx, by, height)])
        mesh.polygon([(0.0, 0.0, 0.0), (bx, by, 0.0), (ax, ay, 0.0)])
        mesh.polygon([(ax, ay, 0.0), (bx, by, 0.0), (bx, by, height), (ax, ay, height)])
    return mesh.data()


def _printed(text: str, height_mm: float, max_width_mm: float) -> vtk.vtkPolyData | None:
    """``text`` as flat glyphs ``height_mm`` tall, centred on the origin and narrowed to fit
    ``max_width_mm``: the ink printed on a part. ``None`` when nothing would be printed."""
    vector = vtk.vtkVectorText()
    vector.SetText(text)
    vector.Update()
    x0, x1, y0, y1, _z0, _z1 = vector.GetOutput().GetBounds()
    if x1 <= x0:
        return None
    # vtkVectorText is about one unit tall, as the legend already relies on.
    scale = min(height_mm, max_width_mm / (x1 - x0))
    transform = vtk.vtkTransform()
    transform.Scale(scale, scale, 1.0)
    transform.Translate(-(x0 + x1) / 2, -(y0 + y1) / 2, 0.0)
    placed = vtk.vtkTransformPolyDataFilter()
    placed.SetTransform(transform)
    placed.SetInputData(vector.GetOutput())
    placed.Update()
    result: vtk.vtkPolyData = placed.GetOutput()
    return result


def _sphere(radius: float, resolution: int = 28) -> Any:
    sphere = vtk.vtkSphereSource()
    sphere.SetRadius(radius)
    sphere.SetThetaResolution(resolution)
    sphere.SetPhiResolution(resolution)
    sphere.SetCenter(0.0, 0.0, 0.0)
    return sphere


@dataclass(frozen=True, slots=True)
class _WorldBody:
    """A component's body in 3D world space, with its transform already applied."""

    x: float
    y: float
    size_x: float
    size_y: float
    height: float
    axis: str
    style: BodyStyle
    #: The board's own thickness. A body knows where its pins are; without this it does
    #: not know how deep their holes go, and a lead cannot be drawn through one.
    thickness: float
    #: World positions of every pin, and of the polarity pin if the part has one.
    pins: tuple[tuple[float, float], ...]
    polarity: tuple[float, float] | None
    #: The printed colour code, for a resistor whose value could be decoded. Empty for
    #: everything else -- see ``bodies.resistor_bands``, which refuses to guess.
    bands: tuple[str, ...] = ()
    #: Which way the wire entries face, as a world direction, for a part that has them
    #: (``footprints.wire_entry``). The generated terminal draws its openings on that face.
    entry: tuple[float, float] | None = None
    #: What is printed on the part, for a package that carries print -- see ``_marking``.
    marking: str = ""

    @property
    def along(self) -> float:
        return self.size_x if self.axis == "x" else self.size_y

    @property
    def across(self) -> float:
        return self.size_y if self.axis == "x" else self.size_x

    @property
    def lead_bottom_z(self) -> float:
        """Where a lead ends: just past the solder-side copper, as a trimmed one does.

        Not at the copper: an end coplanar with the pad would z-fight it, and a lead you
        cannot see from underneath is one the solder side has no evidence of.
        """
        return -self.thickness - PAD_LIFT_MM - LEAD_TRIM_MM

    @property
    def surface(self) -> Surface:
        """How this part's material catches light. One table, two renderers: the 2D view
        derives its highlight from the same call."""
        return surface_for(self.style)


def _world_body(lookup: FootprintLookup, comp: Any, board: Board) -> _WorldBody | None:
    fp = lookup(comp.footprint_id)
    if fp is None:
        return None
    placement = placement_for(fp, board.pitch)

    def to_world(local_x: float, local_y: float) -> tuple[float, float]:
        tx, ty = transform_offset(local_x, local_y, comp.rotation, comp.mirrored)
        return (
            comp.anchor.col * board.pitch + tx,
            -(comp.anchor.row * board.pitch + ty),
        )

    x, y = to_world(placement.centre_x, placement.centre_y)
    # A quarter turn swaps which world axis each extent lies along; the extents themselves
    # are unchanged, and a sign flip from mirroring cannot affect a length.
    swapped = comp.rotation in (90, 270)
    size_x = placement.size_y if swapped else placement.size_x
    size_y = placement.size_x if swapped else placement.size_y
    axis = placement.axis
    if swapped:
        axis = "y" if axis == "x" else "x"

    polarity_local = polarity_pin_offset(fp, board.pitch)
    facing = wire_entry(fp)
    entry: tuple[float, float] | None = None
    if facing is not None:
        # The footprint frame counts rows downward and the world counts them up-negative,
        # the sign ``to_world`` applies to a position, applied here to a direction.
        turned_x, turned_y = transform_offset(facing[0], facing[1], comp.rotation, comp.mirrored)
        entry = (turned_x, -turned_y)
    return _WorldBody(
        x=x,
        y=y,
        size_x=size_x,
        size_y=size_y,
        height=placement.height,
        axis=axis,
        style=style_for(fp),
        thickness=board.thickness,
        pins=tuple(
            (hole.col * board.pitch, -hole.row * board.pitch)
            for _pin, hole in all_pin_holes(comp, fp)
        ),
        polarity=to_world(*polarity_local) if polarity_local is not None else None,
        # From the document's own value, so the bands cannot disagree with the netlist.
        bands=resistor_bands(fp, comp.value) or (),
        entry=entry,
        marking=_marking(fp, comp.value),
    )


#: Packages whose real parts carry their value in print: a relay's part number across its
#: top, a potentiometer's value stamped into its cover. Nothing else is printed, because
#: nothing else says anything the document knows -- a DIP's print is its manufacturer's.
PRINTED_ARCHETYPES = frozenset({"relay-box", "potentiometer"})


def _marking(fp: Footprint, value: str) -> str:
    """The print on a part: its value, from the document, as a real one carries it.

    Only a value ``vtkVectorText`` can print whole. It has ASCII and nothing else, so
    "Röle 12V" would come out "Rle 12V" -- a wrong label, which is worse than none, and the
    board and the parts list still say what it is.
    """
    text = value.strip()
    if fp.body.archetype not in PRINTED_ARCHETYPES or not text:
        return ""
    return text if all(" " <= char <= "~" for char in text) else ""


def _through_hole_pieces(
    body: _WorldBody,
    top_z: float,
    radius: float = LEAD_RADIUS_MM,
    blade: tuple[float, float] | None = None,
) -> list[_Piece]:
    """The part of every lead that goes down its hole, in ONE instanced actor.

    THE LEADS USED TO STOP IN MID-AIR. A resistor's wire ran horizontally to the pin
    position and ended there, a hand's breadth above the board at this scale, and a DIP
    had no pins at all -- so every part hovered over the holes it is supposed to be
    soldered into, which is the one thing this view exists to show. The lead now turns
    down at the pin, disappears into the hole (the bore is opaque, as a board is) and
    reappears trimmed on the solder side.

    Instanced rather than an actor per pin, for the reason the pad grid is: a 2x20 header
    has forty pins, and forty actors for one connector would cost more than every pad on
    the board.
    """
    bottom = body.lead_bottom_z
    height = top_z - bottom
    if height <= 0 or not body.pins:
        return []
    # ``blade`` is a flat pin rather than a round lead: a DIP and a header are stamped from
    # sheet, and a round pin on a DIP is the detail that makes a rendered package look like
    # a toy. A box needs no turning, so the instanced path takes it as it is.
    return [
        _Piece(
            source=_box(blade[0], blade[1], height)
            if blade is not None
            else _upright_cylinder(radius, height),
            rgb=LEAD_RGB,
            position=(0.0, 0.0, 0.0),
            material=TINNED,
            instances=tuple((pin_x, pin_y, bottom + height / 2) for pin_x, pin_y in body.pins),
        )
    ]


def _lead_pieces(body: _WorldBody, radius: float = LEAD_RADIUS_MM) -> list[_Piece]:
    """Tinned wire from each pin to the body edge, and down through the hole from there.

    This is most of what makes a resistor read as a resistor: the horizontal run says the
    part is standing on its own leads, and the bend down at each end says which holes
    those leads are in.
    """
    pieces: list[_Piece] = []
    half = body.along / 2
    z = min(body.across, 1.4) / 2 + _LIFT
    for pin_x, pin_y in body.pins:
        if body.axis == "x":
            offset = pin_x - body.x
            if abs(offset) <= half + 0.05:
                continue
            run = abs(offset) - half
            centre = body.x + (half + run / 2) * (1 if offset > 0 else -1)
            pieces.append(
                _Piece(
                    source=_cylinder(radius, run, resolution=10),
                    rgb=LEAD_RGB,
                    position=(centre, pin_y, z),
                    orientation=_ALONG_X,
                    material=TINNED,
                )
            )
        else:
            offset = pin_y - body.y
            if abs(offset) <= half + 0.05:
                continue
            run = abs(offset) - half
            centre = body.y + (half + run / 2) * (1 if offset > 0 else -1)
            pieces.append(
                _Piece(
                    source=_cylinder(radius, run, resolution=10),
                    rgb=LEAD_RGB,
                    position=(pin_x, centre, z),
                    orientation=_ALONG_Y,
                    material=TINNED,
                )
            )
    # The drop is added for EVERY pin, including the ones with no horizontal run: a pin
    # under its own body still has to reach the hole it is in. It starts at the TOP of the
    # horizontal run rather than at its centreline, so its flat cap is buried inside that
    # tube and the corner reads as a bend rather than as two pieces meeting.
    return pieces + _through_hole_pieces(body, z + radius, radius)


def _axial_pieces(body: _WorldBody) -> list[_Piece]:
    """A cylinder lying on the board along its leads, with a band at the marked end.

    Covers resistors and DO-41/DO-35 diodes, which share this archetype and are told apart
    by polarity: a diode's band is its cathode stripe, and it is the difference between a
    working circuit and a dead one.
    """
    radius = body.across / 2
    z = radius + _LIFT
    orientation = _ALONG_X if body.axis == "x" else _ALONG_Y
    surface = body.surface
    # A resistor's body is not a tin can: it is moulded with a shoulder at each end, and a
    # flat-ended cylinder is the single thing that made these read as machined blanks. The
    # barrel is shortened by what the two domes add back, so the part still measures the
    # length its footprint says it does.
    dome = min(radius * 0.55, body.along * 0.16)
    pieces = [
        _Piece(
            source=_cylinder(radius, body.along - 2 * dome),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, z),
            orientation=orientation,
            material=_material_of(surface),
        )
    ]
    for end in (-1.0, 1.0):
        along = 1.0 if body.axis == "x" else 0.0
        pieces.append(
            _Piece(
                source=_sphere(radius),
                rgb=_rgb(body.style.fill),
                position=_offset_along(body, end * (body.along / 2 - dome), z),
                # Squashed along the part's own axis, so the end is a shoulder rather than
                # a ball stuck on the end of a tube.
                scale=(
                    (dome / radius, 1.0, 1.0) if along else (1.0, dome / radius, 1.0)
                ),
                material=_material_of(surface),
            )
        )

    return pieces + _axial_markings(body) + _lead_pieces(body)


def _axial_markings(
    body: _WorldBody,
    barrel: tuple[float, float, float] | None = None,
    *,
    polarity_band: bool = True,
) -> list[_Piece]:
    """What is PRINTED on a lying cylinder: the colour code, or the cathode band.

    Separate from the body it is printed on because a borrowed mesh needs it too. A KiCad
    resistor is a bare beige barrel -- the library has no way to know what value a part is,
    and this application does (``bodies.resistor_bands`` reads the document's own value), so
    the shape comes from there and the marking from here. A diode without its band is worse
    than a diode drawn as a box: it is a part whose one distinguishing feature the picture
    has quietly dropped.
    """
    # ``barrel`` is the borrowed mesh's own (radius, centre height, length), because a
    # KiCad DIN0207 is 2.5 mm across and 6.3 mm long where this footprint's placement says
    # 2.0 and 5.0 -- a footprint describes a package family and a model is one part in it.
    # Printing at the footprint's size puts the bands INSIDE the barrel, which is not a
    # subtle failure: they vanish.
    radius, z, along = barrel or (body.across / 2, body.across / 2 + _LIFT, body.along)
    orientation = _ALONG_X if body.axis == "x" else _ALONG_Y
    pieces: list[_Piece] = []
    # Same layout as the 2D view draws: three bands in the near half and the tolerance band
    # at the far end, because that asymmetry is what says which way round to read them.
    for index, colour in enumerate(body.bands):
        fraction = 0.16 + index * 0.15 if index < len(body.bands) - 1 else 0.80
        pieces.append(
            _Piece(
                source=_cylinder(radius * 1.03, along * 0.11, resolution=20),
                rgb=_rgb(colour),
                position=_offset_along(body, (fraction - 0.5) * along, z),
                orientation=orientation,
                material=CERAMIC,
            )
        )

    if body.polarity is not None and polarity_band:
        # A band at the end nearest the marked pin, standing very slightly proud so it is
        # visible against the body rather than fighting it for the same pixels.
        band_width = max(along * 0.16, 0.5)
        offset = (along / 2 - band_width) * _towards(body, body.polarity)
        pieces.append(
            _Piece(
                source=_cylinder(radius * 1.04, band_width),
                rgb=_rgb(body.style.accent),
                position=_offset_along(body, offset, z),
                orientation=orientation,
                material=CERAMIC,
            )
        )
    return pieces


def _can_pieces(body: _WorldBody) -> list[_Piece]:
    """An upright cylinder: electrolytic can or potentiometer.

    An electrolytic gets its polarity stripe down the side nearest the negative lead. On a
    real part that stripe is the only thing distinguishing the two ends, and reversing an
    electrolytic is the classic way to make one vent.
    """
    radius = min(body.size_x, body.size_y) / 2
    pieces = [
        _Piece(
            source=_cylinder(radius, body.height, resolution=48),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, body.height / 2 + _LIFT),
            orientation=_ALONG_Z,
            material=SLEEVE,
        ),
        # The crimped rim at the top, where the sleeve is folded over the can. A thin
        # bright ring and nothing more: this was a WHITE DISC across the whole top, and
        # the two capacitors on a board then read as screw heads -- the first person to
        # see it called them mounting holes.
        _Piece(
            source=_cylinder(radius, 0.22, resolution=48),
            rgb=_lit(body.style.fill, 1.5),
            position=(body.x, body.y, body.height + _LIFT - 0.11),
            orientation=_ALONG_Z,
            material=STEEL,
        ),
        # The top itself is the sleeve, as it is on the real part.
        _Piece(
            source=_cylinder(radius * 0.93, 0.24, resolution=48),
            rgb=_lit(body.style.fill, 1.12),
            position=(body.x, body.y, body.height + _LIFT - 0.1),
            orientation=_ALONG_Z,
            material=SLEEVE,
        ),
    ]
    # The vent, scored into that top rather than printed on it: two shallow grooves, which
    # is what a radial can carries and what it splits along when one lets go.
    for across in (False, True):
        pieces.append(
            _Piece(
                source=(
                    _box(radius * 1.45, radius * 0.1, 0.1)
                    if across
                    else _box(radius * 0.1, radius * 1.45, 0.1)
                ),
                rgb=_lit(body.style.fill, 0.55),
                position=(body.x, body.y, body.height + _LIFT - 0.02),
                material=SLEEVE,
            )
        )
    if body.polarity is not None:
        # The stripe marks the end AWAY from pin 1: pin 1 is the positive lead, so the printed
        # band belongs on the negative side.
        #
        # Thin RADIALLY and wide tangentially, sitting just inside the can's surface, so it
        # reads as printing on the side. A square slab, which is what this was, stuck out of
        # the cylinder as a separate bolted-on block.
        direction = -_towards(body, body.polarity)
        thickness = radius * 0.22
        tangential = radius * 1.05
        source = (
            _box(thickness, tangential, body.height * 0.9)
            if body.axis == "x"
            else _box(tangential, thickness, body.height * 0.9)
        )
        pieces.append(
            _Piece(
                source=source,
                rgb=_rgb(body.style.accent),
                position=_offset_along(
                    body, direction * (radius - thickness * 0.45), body.height / 2 + _LIFT
                ),
                material=INK,
            )
        )
    # Under the can, so only the hole and the solder side ever show them -- which is
    # exactly where a radial capacitor's legs are.
    return pieces + _through_hole_pieces(body, _LIFT + 0.15)


def _disc_pieces(body: _WorldBody) -> list[_Piece]:
    """A ceramic disc standing on edge -- a LENS, not a coin.

    The dipped case is thicker in the middle and thins to a rounded edge, and a flat
    cylinder with a sharp rim was the single thing that made these read as washers stood
    up on the board. A sphere squashed across the leads is the shape, and costs the same
    one solid.
    """
    diameter = body.along
    thickness = body.across
    squash = max(thickness / diameter, 0.08)
    return [
        _Piece(
            source=_sphere(diameter / 2, resolution=32),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, diameter / 2 + _LIFT),
            # Flattened across the leads: the disc's faces look sideways, which is how one
            # is fitted and why two of them side by side need the room they do.
            scale=(1.0, squash, 1.0) if body.axis == "x" else (squash, 1.0, 1.0),
            material=CERAMIC,
        ),
        *_lead_pieces(body),
    ]


def _film_pieces(body: _WorldBody) -> list[_Piece]:
    """A box film capacitor: a slab with ROUNDED ENDS, which is what a dipped case is.

    A bare cuboid was the worst model in the library -- an orange brick sitting on the
    board with nothing about it that said capacitor. The ends are half-round in plan, so
    the case is a stadium prism: one box and two upright cylinders.
    """
    surface = body.surface
    fill = _rgb(body.style.fill)
    radius = body.across / 2
    middle = max(body.along - 2 * radius, body.along * 0.1)
    pieces = [
        _Piece(
            source=(
                _moulded_box(middle, body.across, body.height)
                if body.axis == "x"
                else _moulded_box(body.across, middle, body.height)
            ),
            rgb=fill,
            position=(body.x, body.y, body.height / 2 + _LIFT),
            material=_material_of(surface),
        )
    ]
    for end in (-1.0, 1.0):
        pieces.append(
            _Piece(
                source=_cylinder(radius, body.height, resolution=20),
                rgb=fill,
                position=_offset_along(
                    body, end * (body.along / 2 - radius), body.height / 2 + _LIFT
                ),
                orientation=_ALONG_Z,
                material=_material_of(surface),
            )
        )
    return pieces + _lead_pieces(body)


def _dip_pieces(body: _WorldBody) -> list[_Piece]:
    """A plastic package with a pin-1 dot, which is the only thing telling you which way
    round the chip goes."""
    pieces = [
        _Piece(
            source=_moulded_box(body.size_x, body.size_y, body.height),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, body.height / 2 + _LIFT),
            material=MOULDED,
        )
    ]
    if body.polarity is not None:
        dot_r = min(body.size_x, body.size_y) * 0.055
        # Pulled in from the corner so the dot sits on the package rather than over its edge.
        dot_x = body.x + (body.polarity[0] - body.x) * 0.62
        dot_y = body.y + (body.polarity[1] - body.y) * 0.62
        pieces.append(
            _Piece(
                # A DIMPLE pressed into the plastic, which is what it is: the accent
                # colour at nearly a tenth of the package made it a headlamp, and the one
                # marking on the part came out looking like a component of its own.
                source=_cylinder(dot_r, 0.24, resolution=14),
                rgb=_lit(body.style.fill, 0.55),
                position=(dot_x, dot_y, body.height + _LIFT - 0.06),
                orientation=_ALONG_Z,
                material=MOULDED,
            )
        )
        # AND the notch at the pin-1 end, which is the marking people actually use: the
        # dot goes under a label often enough that a chip is oriented by the semicircle
        # moulded into the end of the package. Cut into the end rather than printed on it,
        # so it reads from the side as well as from above.
        notch_r = min(body.across * 0.22, body.along * 0.12)
        pieces.append(
            _Piece(
                source=_cylinder(notch_r, body.height * 0.9, resolution=18),
                # Darker than the package, or a notch cut into black plastic is invisible
                # against black plastic -- which is what the first attempt drew.
                rgb=_lit(body.style.fill, 0.45),
                position=_offset_along(
                    body,
                    _towards(body, body.polarity) * body.along / 2,
                    body.height / 2 + _LIFT,
                ),
                orientation=_ALONG_Z,
                material=MOULDED,
            )
        )
    # From half way up the package, because a DIP's rows are wider than its body: the pins
    # run down the OUTSIDE of the two long sides, which is what they do on the real part
    # and what tells you at a glance which way the package is turned. Flat, because a DIP's
    # pins are stamped from sheet and a round one reads as a model of a chip.
    blade = (0.5, 0.26) if body.axis == "x" else (0.26, 0.5)
    return pieces + _through_hole_pieces(body, body.height / 2 + _LIFT, blade=blade)


def _to92_pieces(body: _WorldBody) -> list[_Piece]:
    """The D-shaped case, with the flat face the legs are read against.

    It was a squashed cylinder, which is an ellipse: no flat, so nothing on the part said
    which way round it goes -- and getting a transistor round the wrong way is the classic
    way to spend an evening. The flat faces the row of pins, as it does on the real part.
    """
    radius = max(body.size_x, body.size_y) / 2
    return [
        _Piece(
            # The chord sits where the case's own DEPTH puts it: a flat at half the depth
            # shaves a sliver off a cylinder and reads as no flat at all, which is what
            # the first attempt drew.
            source=_d_prism(
                radius,
                max(min(body.size_x, body.size_y) - radius, radius * 0.25),
                body.height,
            ),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, body.height / 2 + _LIFT),
            # The profile is built with its flat towards +y; a part whose pins run along y
            # wants it towards +x instead.
            orientation=(0.0, 0.0, 0.0) if body.axis == "x" else (0.0, 0.0, 90.0),
            material=MOULDED,
        ),
        *_lead_pieces(body),
    ]


def _to220_pieces(body: _WorldBody) -> list[_Piece]:
    """Plastic case with the metal tab above it -- the tab is what decides whether the part
    clears its neighbours and whether it can be bolted to a heatsink."""
    plastic_h = body.height * 0.62
    tab_h = body.height - plastic_h
    # The tab is a sheet of metal the plastic is moulded AROUND, so it is thin and it is
    # flush with the back face -- not a slab the width of the package sitting on top of it,
    # which is what this was and what made a TO-220 read as a two-tone brick. Which face is
    # the back does not matter electrically; that it has one does, because that is the side
    # a heatsink bolts to.
    tab_thickness = min(body.across * 0.22, 1.4)
    back = (body.across - tab_thickness) / 2
    offset_x, offset_y = (0.0, back) if body.axis == "x" else (back, 0.0)
    hole_r = min(body.across, body.along) * 0.16
    return [
        _Piece(
            source=_moulded_box(body.size_x, body.size_y, plastic_h),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, plastic_h / 2 + _LIFT),
            material=MOULDED,
        ),
        _Piece(
            source=(
                _box(body.size_x, tab_thickness, tab_h)
                if body.axis == "x"
                else _box(tab_thickness, body.size_y, tab_h)
            ),
            rgb=_rgb(body.style.accent),
            position=(body.x + offset_x, body.y + offset_y, plastic_h + tab_h / 2 + _LIFT),
            material=STEEL,
        ),
        # The bolt hole, as a dark disc through the tab rather than a hole cut in it: this
        # is a 3 mm feature on a vertical face, where the board's own holes are the surface
        # you spend the whole time looking at. It says the part can be bolted down, which
        # is the fact a height check cares about.
        _Piece(
            source=_cylinder(hole_r, tab_thickness * 1.4, resolution=16),
            rgb=_lit(body.style.accent, 0.3),
            position=(
                body.x + offset_x,
                body.y + offset_y,
                plastic_h + tab_h * 0.62 + _LIFT,
            ),
            orientation=_ALONG_Y if body.axis == "x" else _ALONG_X,
            material=STEEL,
        ),
        *_through_hole_pieces(body, _LIFT + 0.15),
    ]


def _led_pieces(body: _WorldBody) -> list[_Piece]:
    """A cylindrical lens with a domed top, lit like a lens rather than a case."""
    radius = min(body.size_x, body.size_y) / 2
    barrel_h = max(body.height - radius, radius * 0.4)
    lens = _rgb(body.style.fill)
    # From ``style.lens`` rather than from numbers written here: the flag was documented as
    # a shading hint for both views and read by neither, so a lens was lit like a slightly
    # glossy plastic case. A LED that does not look lit does not look like a LED.
    surface = body.surface
    pieces = [
        _Piece(
            source=_cylinder(radius, barrel_h, resolution=36),
            rgb=lens,
            position=(body.x, body.y, barrel_h / 2 + _LIFT),
            orientation=_ALONG_Z,
            material=_material_of(surface),
        ),
        _Piece(
            source=_sphere(radius),
            rgb=lens,
            position=(body.x, body.y, barrel_h + _LIFT),
            material=_material_of(surface),
        ),
        # The flange at the base is the flat that marks the cathode on a real LED.
        _Piece(
            source=_cylinder(radius * 1.12, radius * 0.22, resolution=24),
            rgb=lens,
            position=(body.x, body.y, radius * 0.11 + _LIFT),
            orientation=_ALONG_Z,
            material=_material_of(surface),
        ),
    ]
    return pieces + _lead_pieces(body)


def _header_pieces(body: _WorldBody) -> list[_Piece]:
    """Black moulding with a gold pin standing up over each hole.

    The pins are INSTANCED into one glyph rather than given an actor each. A 2x20 header has
    forty of them, and a board with a few such headers would otherwise add more actors than
    the entire 2400-pad grid does -- the grid is instanced for exactly this reason.
    """
    moulding_h = min(body.height * 0.3, 2.6)
    pin_h = body.height - moulding_h
    return [
        _Piece(
            source=_moulded_box(body.size_x, body.size_y, moulding_h),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, moulding_h / 2 + _LIFT),
            material=MOULDED,
        ),
        _Piece(
            source=_box(0.64, 0.64, pin_h),
            rgb=_rgb(body.style.accent),
            position=(0.0, 0.0, 0.0),
            material=PLATED,
            instances=tuple(
                (pin_x, pin_y, moulding_h + pin_h / 2 + _LIFT) for pin_x, pin_y in body.pins
            ),
        ),
        # The same pin continues below the moulding and through the board, which is what
        # is soldered -- the part standing above it is only the half you can see. Square,
        # because that is what the pin above the moulding already is.
        *_through_hole_pieces(body, _LIFT + 0.15, blade=(0.64, 0.64)),
    ]


def _box_header_pieces(body: _WorldBody) -> list[_Piece]:
    """A shroud of four walls on a floor, gold pins standing in it, and the key slot.

    The slot is the part's whole reason to exist next to a plain header, so it is CUT: the
    wall on the pin-1 row is two pieces with a gap between them. Which wall that is comes
    from the pins themselves -- pin 1 and pin 2 are the pair in the first column, so the
    direction from pin 2 to pin 1 points at the keyed wall however the part is turned.
    """
    floor_h = 1.2
    wall = min(body.size_x, body.size_y) * 0.12
    slot = 4.5
    pieces: list[_Piece] = [
        _Piece(
            source=_moulded_box(body.size_x, body.size_y, floor_h),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, floor_h / 2 + _LIFT),
            material=MOULDED,
        )
    ]
    wall_h = body.height - floor_h
    z = floor_h + wall_h / 2 + _LIFT
    keyed_axis, keyed_sign = "y", -1.0
    if len(body.pins) >= 2:
        dx = body.pins[0][0] - body.pins[1][0]
        dy = body.pins[0][1] - body.pins[1][1]
        keyed_axis = "x" if abs(dx) > abs(dy) else "y"
        keyed_sign = (1.0 if dx > 0 else -1.0) if keyed_axis == "x" else (1.0 if dy > 0 else -1.0)
    for axis in ("x", "y"):
        for sign in (-1.0, 1.0):
            # A wall along the part's other axis, at this side.
            length = body.size_y if axis == "x" else body.size_x
            cx = body.x + (sign * (body.size_x - wall) / 2 if axis == "x" else 0.0)
            cy = body.y + (sign * (body.size_y - wall) / 2 if axis == "y" else 0.0)
            keyed = axis == keyed_axis and sign == keyed_sign
            spans = (
                ((-length / 2, -slot / 2), (slot / 2, length / 2)) if keyed else ((-length / 2, length / 2),)
            )
            for start, end in spans:
                piece_len = end - start
                middle = (start + end) / 2
                size = (wall, piece_len) if axis == "x" else (piece_len, wall)
                offset = (0.0, middle) if axis == "x" else (middle, 0.0)
                pieces.append(
                    _Piece(
                        source=_moulded_box(size[0], size[1], wall_h),
                        rgb=_rgb(body.style.fill),
                        position=(cx + offset[0], cy + offset[1], z),
                        material=MOULDED,
                    )
                )
    pin_h = body.height - 1.5
    pieces.append(
        _Piece(
            source=_box(0.64, 0.64, pin_h),
            rgb=_rgb(body.style.accent),
            position=(0.0, 0.0, 0.0),
            material=PLATED,
            instances=tuple((pin_x, pin_y, pin_h / 2 + _LIFT) for pin_x, pin_y in body.pins),
        )
    )
    return pieces + _through_hole_pieces(body, _LIFT + 0.15, blade=(0.64, 0.64))


def _screw_terminal_pieces(body: _WorldBody) -> list[_Piece]:
    """A block with a screw head per way, so the wire entries are where they look."""
    pieces = [
        _Piece(
            source=_moulded_box(body.size_x, body.size_y, body.height),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, body.height / 2 + _LIFT),
            material=GLOSS,
        )
    ]
    head_r = min(body.across * 0.28, 1.6)
    for pin_x, pin_y in body.pins:
        pieces.append(
            _Piece(
                source=_cylinder(head_r, 0.5, resolution=14),
                rgb=_rgb(body.style.accent),
                # Standing PROUD of the top by _DECAL_PROUD_MM. It used to sit with its top
                # exactly in the block's top face, and two coplanar faces are drawn in
                # whichever order the depth buffer happens to resolve them -- the grey and
                # white blotches a real board showed on every generated terminal. Rendering
                # only: the height rule and the case check read the footprint, not this.
                position=(pin_x, pin_y, body.height + _LIFT - 0.25 + _DECAL_PROUD_MM),
                orientation=_ALONG_Z,
                material=STEEL,
            )
        )
    pieces += _wire_entry_pieces(body)
    return pieces + _through_hole_pieces(body, _LIFT + 0.15)


#: The openings on a generated terminal's entry face: how wide along the row, how deep into
#: the block, how tall, and where their centre sits. From the Phoenix MKDS mesh the borrowed
#: terminals use, whose wire channel runs in at 2.4-5.1 mm on a 13.8 mm block -- so a
#: terminal drawn without a mesh points its mouth the same way, at about the same height,
#: as one drawn with it.
_ENTRY_WIDTH_MM = 1.6
_ENTRY_DEPTH_MM = 0.8
_ENTRY_HEIGHT_MM = 2.4
_ENTRY_CENTRE_Z_MM = 3.75

#: How far a mark drawn on a generated body -- a screw head, a wire opening -- stands out of
#: the face it is on. Not a hair: with the view's near plane pulled in close the depth
#: buffer cannot tell 0.02 mm from coplanar, and a mark it cannot separate from its face
#: comes out as blotches that change as the view turns. A tenth and a half of a millimetre
#: is invisible as a step at any zoom this view reaches and is always resolved.
_DECAL_PROUD_MM = 0.15


def _wire_entry_pieces(body: _WorldBody) -> list[_Piece]:
    """A dark opening per way, on the face ``footprints.wire_entry`` says the wires use.

    Standing ``_DECAL_PROUD_MM`` out of the face rather than a hair (0.02 mm, which the
    depth buffer could not separate from the face), so it does not fight the block's own
    face for the same pixels.
    """
    if body.entry is None:
        return []
    ex, ey = body.entry
    along_x = abs(ex) < abs(ey)  # the openings run along the pin row, across the entry
    size = (
        (_ENTRY_WIDTH_MM, _ENTRY_DEPTH_MM, _ENTRY_HEIGHT_MM)
        if along_x
        else (_ENTRY_DEPTH_MM, _ENTRY_WIDTH_MM, _ENTRY_HEIGHT_MM)
    )
    half_across = (body.size_y if along_x else body.size_x) / 2
    reach = half_across - _ENTRY_DEPTH_MM / 2 + _DECAL_PROUD_MM
    z = min(_ENTRY_CENTRE_Z_MM, body.height * 0.4) + _LIFT
    return [
        _Piece(
            source=_moulded_box(*size),
            rgb=_rgb("#121212"),
            position=(pin_x + ex * reach, pin_y + ey * reach, z),
            material=GLOSS,
        )
        for pin_x, pin_y in body.pins
    ]


def _vertical_terminal_pieces(body: _WorldBody) -> list[_Piece]:
    """The header and the screw plug standing in it, with the wire openings on TOP.

    One block for the pair, because that is what stands on the board once it is wired. The
    openings sit over the pins -- a wire goes straight down into its way -- and the screw
    heads beside them on the same top face, both standing ``_DECAL_PROUD_MM`` proud so the
    depth buffer can tell them from the block.
    """
    pieces = [
        _Piece(
            source=_moulded_box(body.size_x, body.size_y, body.height),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, body.height / 2 + _LIFT),
            material=GLOSS,
        )
    ]
    # Openings and screws split across the block: the across axis is world y for a part
    # lying along x and world x for one turned a quarter.
    shift = body.across * 0.22
    ox, oy = (0.0, shift) if body.axis == "x" else (shift, 0.0)
    top = body.height + _LIFT
    head_r = min(body.across * 0.14, 1.4)
    for pin_x, pin_y in body.pins:
        pieces.append(
            _Piece(
                source=_moulded_box(1.7, 1.7, 1.0),
                rgb=_rgb("#121212"),
                position=(pin_x + ox, pin_y + oy, top - 0.5 + _DECAL_PROUD_MM),
                material=GLOSS,
            )
        )
        pieces.append(
            _Piece(
                source=_cylinder(head_r, 0.5, resolution=14),
                rgb=_rgb(body.style.accent),
                position=(pin_x - ox, pin_y - oy, top - 0.25 + _DECAL_PROUD_MM),
                orientation=_ALONG_Z,
                material=STEEL,
            )
        )
    return pieces + _through_hole_pieces(body, _LIFT + 0.15)


def _pot_pieces(body: _WorldBody) -> list[_Piece]:
    """A rotary potentiometer as it comes for a board: the moulded housing, the steel cover
    crimped over it, the threaded bushing, and the knurled shaft with its screwdriver slot.

    It was a disc with a peg on it. What says "potentiometer" is the top half -- a thread
    somebody puts a panel nut on and a knurl somebody puts a knob on -- so that half gets
    the detail, in the proportions of the common 16 mm part: an M7 bushing and a 6 mm shaft,
    scaled from the footprint's own diameter so a smaller pot keeps its shape. The four
    tabs down the side are how the cover is held on, and the one feature of the silhouette
    that is not round.
    """
    radius = min(body.size_x, body.size_y) / 2
    height = body.height
    housing = height * 0.40
    cover = max(0.3, height * 0.04)
    bushing = height * 0.22
    shaft = height - housing - cover - bushing
    bushing_r = radius * 0.44
    shaft_r = radius * 0.375
    housing_top = _LIFT + housing
    cover_top = housing_top + cover
    shaft_base = cover_top + bushing
    metal = _rgb(body.style.accent)

    pieces = [
        _Piece(
            source=_lathe(
                [
                    (0.0, 0.0),
                    (radius - 0.3, 0.0),
                    (radius, 0.3),
                    (radius, housing),
                    (0.0, housing),
                ],
                resolution=64,
            ),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, _LIFT),
            material=_material_of(body.surface),
        ),
        _Piece(
            source=_lathe(
                [
                    (0.0, 0.0),
                    (radius * 0.985, 0.0),
                    (radius * 0.985, cover * 0.6),
                    (radius * 0.94, cover),
                    (0.0, cover),
                ],
                resolution=64,
            ),
            rgb=metal,
            position=(body.x, body.y, housing_top),
            material=STEEL,
        ),
        # The thread: a crest every 0.75 mm, which is an M7's fine pitch, ending in a
        # chamfer where a nut starts on.
        _Piece(
            source=_lathe(_threaded_profile(bushing_r, bushing), resolution=40),
            rgb=metal,
            position=(body.x, body.y, cover_top),
            material=STEEL,
        ),
        _Piece(
            source=_knurled_prism(shaft_r, shaft),
            rgb=metal,
            position=(body.x, body.y, shaft_base),
            material=STEEL,
        ),
        # The slot across the end of the shaft, which reads on its sides as well as on top.
        _Piece(
            source=_box(shaft_r * 2 + 0.04, shaft_r * 0.26, shaft * 0.3),
            rgb=_lit(body.style.accent, 0.3),
            position=(body.x, body.y, shaft_base + shaft * 0.85 + 0.01),
            material=STEEL,
        ),
    ]
    # The crimp tabs, one to each quarter: bent down over the housing from the cover.
    for quarter in range(4):
        angle = math.pi / 4 + quarter * math.pi / 2
        pieces.append(
            _Piece(
                source=_box(1.2, 0.3, housing * 0.8),
                rgb=metal,
                position=(
                    body.x + (radius + 0.12) * math.cos(angle),
                    body.y + (radius + 0.12) * math.sin(angle),
                    housing_top - housing * 0.4 + 0.02,
                ),
                orientation=(0.0, 0.0, math.degrees(angle) + 90.0),
                material=STEEL,
            )
        )
    printed = _printed(body.marking, radius * 0.17, (radius - bushing_r) * 1.7)
    if printed is not None:
        # Stamped into the cover in front of the bushing, where the default view reads it.
        pieces.append(
            _Piece(
                source=printed,
                rgb=_lit(body.style.accent, 0.35),
                position=(body.x, body.y - (bushing_r + radius) / 2, cover_top + 0.01),
                material=INK,
            )
        )
    pieces.extend(_through_hole_pieces(body, _LIFT + 0.15))
    return pieces


def _threaded_profile(radius: float, height: float) -> list[tuple[float, float]]:
    """A bushing's ``(radius, z)`` profile: a thread of 0.75 mm pitch, chamfered at the top."""
    root = radius * 0.9
    chamfer = min(0.35, height * 0.2)
    profile = [(0.0, 0.0), (radius, 0.0)]
    z = 0.375
    while z < height - chamfer - 0.2:
        profile += [(root, z), (radius, z + 0.375)]
        z += 0.75
    profile += [(radius, height - chamfer), (radius - chamfer, height), (0.0, height)]
    return profile


def _switch_pieces(body: _WorldBody) -> list[_Piece]:
    """A case with the button proud of it, so its travel is visible in a height check."""
    case_h = body.height * 0.7
    button_h = body.height - case_h
    return [
        _Piece(
            source=_moulded_box(body.size_x, body.size_y, case_h),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, case_h / 2 + _LIFT),
            material=MOULDED,
        ),
        _Piece(
            source=_cylinder(min(body.size_x, body.size_y) * 0.22, button_h, resolution=18),
            rgb=_rgb(body.style.accent),
            position=(body.x, body.y, case_h + button_h / 2 + _LIFT),
            orientation=_ALONG_Z,
            material=GLOSS,
        ),
        *_through_hole_pieces(body, _LIFT + 0.15),
    ]


def _crystal_pieces(body: _WorldBody) -> list[_Piece]:
    """An HC-49 can: a flattened metal cylinder, shaded as metal.

    The shading comes from ``style.metallic`` via ``body.surface`` rather than from numbers
    written here. It used to be hardcoded, which meant the one archetype in the registry
    that is literally a metal can was ignoring its own metallic flag -- two sources of
    truth for one fact, and the sort of drift bodies.py exists to prevent.
    """
    radius = max(body.size_x, body.size_y) / 2
    squash = min(body.size_x, body.size_y) / max(body.size_x, body.size_y)
    scale = (1.0, squash, 1.0) if body.size_x >= body.size_y else (squash, 1.0, 1.0)
    surface = body.surface
    # The can is drawn short of its full height and domed over, because a real HC-49 is
    # closed with a pressed cap and a flat-topped tube reads as a slug of metal. The lip
    # near the base is where the can is welded to its header, and it is the detail that
    # says which way up the part goes.
    # Shallow: a can closed with a pressed cap has a rounded shoulder, and a dome the
    # height of its own radius turns the part into a bullet.
    dome = min(radius * squash * 0.55, body.height * 0.16)
    barrel = body.height - dome
    return [
        _Piece(
            source=_cylinder(radius, barrel, resolution=24),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, barrel / 2 + _LIFT),
            orientation=_ALONG_Z,
            scale=_upright_scale(scale),
            material=_material_of(surface),
        ),
        _Piece(
            source=_sphere(radius, resolution=24),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, barrel + _LIFT),
            scale=(scale[0], scale[1], dome / radius),
            material=_material_of(surface),
        ),
        _Piece(
            source=_cylinder(radius * 1.06, 0.35, resolution=24),
            rgb=_lit(body.style.fill, 0.8),
            position=(body.x, body.y, 0.35 / 2 + _LIFT),
            orientation=_ALONG_Z,
            scale=_upright_scale(scale),
            material=_material_of(surface),
        ),
        *_lead_pieces(body),
    ]


def _box_pieces(body: _WorldBody) -> list[_Piece]:
    """Plain case: film capacitors, relays, and anything without its own archetype."""
    surface = body.surface
    return [
        _Piece(
            source=_moulded_box(body.size_x, body.size_y, body.height),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, body.height / 2 + _LIFT),
            material=_material_of(surface),
        ),
        *_lead_pieces(body),
    ]


#: How far a relay's case stands off the board on its moulded feet. Enough to show as the
#: dark line under the case that says it is standing on something.
RELAY_STANDOFF_MM = 0.5
#: The radius of a relay case's vertical edges -- see ``_rounded_case``.
RELAY_CORNER_MM = 1.0


def _relay_pieces(body: _WorldBody) -> list[_Piece]:
    """A sealed relay: a moulded case standing on four feet, with its part number printed
    across the top.

    It was the plain box a film capacitor gets. The print is most of what a relay is to
    look at -- every one carries its coil voltage and its contact rating where a person
    reads them -- and the document knows the one line of it that matters, the value.
    Printed along the case's long side, reading from the front as the parts on a board do.
    """
    standoff = min(RELAY_STANDOFF_MM, body.height * 0.05)
    case = body.height - standoff
    pieces = [
        _Piece(
            source=_rounded_case(body.size_x, body.size_y, case, RELAY_CORNER_MM),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, _LIFT + standoff + case / 2),
            material=_material_of(body.surface),
        )
    ]
    foot = min(1.2, body.size_x / 6, body.size_y / 6)
    for sx in (-1, 1):
        for sy in (-1, 1):
            pieces.append(
                _Piece(
                    source=_box(foot, foot, standoff + 0.02),
                    rgb=_lit(body.style.fill, 0.5),
                    position=(
                        body.x + sx * (body.size_x / 2 - foot),
                        body.y + sy * (body.size_y / 2 - foot),
                        _LIFT + standoff / 2,
                    ),
                    material=MOULDED,
                )
            )
    printed = _printed(body.marking, min(body.size_x, body.size_y) * 0.11, body.along * 0.8)
    if printed is not None:
        pieces.append(
            _Piece(
                source=printed,
                rgb=LEGEND_RGB,
                position=(body.x, body.y, _LIFT + body.height + 0.01),
                orientation=(0.0, 0.0, 0.0 if body.axis == "x" else 90.0),
                material=INK,
            )
        )
    pieces.extend(_through_hole_pieces(body, _LIFT + standoff + 0.15))
    return pieces


_BUILDERS: dict[str, Any] = {
    "axial-cylinder": _axial_pieces,
    "radial-electrolytic": _can_pieces,
    "disc-ceramic": _disc_pieces,
    "box-film": _film_pieces,
    "dip": _dip_pieces,
    "to92": _to92_pieces,
    "to220": _to220_pieces,
    "led-round": _led_pieces,
    "pin-header": _header_pieces,
    "screw-terminal": _screw_terminal_pieces,
    "potentiometer": _pot_pieces,
    "tactile-switch": _switch_pieces,
    "crystal-hc49": _crystal_pieces,
    "relay-box": _relay_pieces,
    "generic-box": _box_pieces,
    "box-header": _box_header_pieces,
    "screw-terminal-vertical": _vertical_terminal_pieces,
    # Drawn by ``_module_pieces`` from ``_pieces_for``, because its pin names are the
    # PART's and a builder here sees only the body. The box is the fallback's fallback.
    "module-board": _box_pieces,
}


def _towards(body: _WorldBody, point: tuple[float, float]) -> float:
    """+1 or -1: which way along the body's axis ``point`` lies."""
    delta = point[0] - body.x if body.axis == "x" else point[1] - body.y
    return 1.0 if delta >= 0 else -1.0


def _offset_along(body: _WorldBody, offset: float, z: float) -> tuple[float, float, float]:
    if body.axis == "x":
        return (body.x + offset, body.y, z)
    return (body.x, body.y + offset, z)


@lru_cache(maxsize=128)
def _mesh(path: str) -> vtk.vtkPolyData:
    """One borrowed mesh, read once and shared by every part that uses it.

    Cached because a board is mostly the same twenty parts over and over and the whole
    scene is rebuilt on every edit -- re-reading a DIP-8 forty times per keystroke is the
    same mistake the pad grid exists not to make. ``SetInputData`` downstream then takes a
    real reference, so nothing here can be collected out from under a mapper.

    NORMALS ARE COMPUTED HERE, because the files carry none, and without them every
    triangle is shaded flat: an LED's dome came out as facets and a can's side as stripes,
    which reads as a low-polygon model however fine the mesh is. The feature angle keeps a
    real edge -- a DIP's shoulder, the rim of a can -- a crease rather than smearing it into
    the faces either side, the same judgement ``_moulded_box`` makes. Once per file, cached.
    """
    reader = vtk.vtkPLYReader()
    reader.SetFileName(path)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputConnection(reader.GetOutputPort())
    normals.SetFeatureAngle(_MESH_FEATURE_ANGLE_DEG)
    normals.SplittingOn()
    normals.Update()
    data = vtk.vtkPolyData()
    data.DeepCopy(normals.GetOutput())
    return data


#: Where a borrowed mesh's smooth shading stops and a crease begins. 40 degrees keeps a
#: 24- or 32-sided can round and a moulded package's shoulders sharp.
_MESH_FEATURE_ANGLE_DEG = 40.0


def _model_pieces(
    body: _WorldBody,
    model: PartModel,
    comp: Any,
    board: Board,
    polarity_mark: tuple[ModelPiece, str] | None = None,
) -> list[_Piece]:
    """A borrowed package, placed on its holes.

    NOTHING IS MEASURED HERE, and that is the point: a KiCad through-hole model's origin is
    pin 1 and its axes run the way this world does -- x with the column, y against the row --
    so the mesh goes down at the anchor and the placement is the component's own rotation.
    Both conventions follow the footprint, and this project's is written down as "the anchor
    is pin 1, at grid offset (0, 0)".

    A quarter turn of a component is a quarter turn CLOCKWISE seen from above, which is
    minus a quarter turn about world z: the footprint frame counts rows downward and the
    world counts them up-negative, and the sign is the difference between the two.

    The body piece is painted from ``bodies.BODY_STYLES`` rather than from the colour the
    model was drawn with -- see ``partmodels`` for why -- and every piece takes one of this
    module's own materials. ``polarity_mark``, when given, is the one piece printed on the
    case that our table has an opinion about -- a diode's band, an electrolytic's minus
    stripe -- and the colour the 2D view draws it in (see ``_polarity_mark``).
    """
    x, y = _xy(board, comp.anchor)
    turn = (0.0, 0.0, -float(comp.rotation))
    # A mirrored part is reflected about the anchor's vertical axis, the same rule
    # ``geometry.transform_offset`` states for its pins, so the mesh is scaled by -1 in x
    # rather than being rebuilt. VTK scales before it orients, which is also the order a
    # part is physically flipped and then turned.
    scale = (-1.0, 1.0, 1.0) if comp.mirrored else (1.0, 1.0, 1.0)
    pieces = []
    for piece in model.pieces:
        if piece.is_body:
            colour = body.style.fill
        elif polarity_mark is not None and piece is polarity_mark[0]:
            colour = polarity_mark[1]
        else:
            colour = piece.color
        pieces.append(
            _Piece(
                source=_mesh(str(piece.path)),
                rgb=_rgb(colour),
                position=(x, y, 0.0),
                orientation=turn,
                scale=scale,
                material=MODEL_MATERIALS.get(piece.material, MOULDED),
            )
        )
    return pieces


#: The materials a model's LEADS and bare metal are made of. A piece that is neither the
#: body nor one of these is something printed or moulded onto the case.
_LEAD_MATERIALS = frozenset({"tinned", "steel", "plated"})


def _is_marking(piece: ModelPiece) -> bool:
    return not piece.is_body and piece.material not in _LEAD_MATERIALS


def _polarity_mark(model: PartModel) -> ModelPiece | None:
    """The biggest thing printed on the case, which on a polarised part is what says which
    way round it goes: a diode's cathode band, an electrolytic's minus stripe.

    The BIGGEST, because the stripe is not the only print on a can -- KiCad draws the minus
    signs down it too, and painting those the stripe's colour would erase them. Measured
    by the piece's own bounds.
    """
    marks = [piece for piece in model.pieces if _is_marking(piece) and len(piece.bounds) == 6]

    def volume(piece: ModelPiece) -> float:
        x0, y0, z0, x1, y1, z1 = piece.bounds
        return (x1 - x0) * (y1 - y0) * (z1 - z0)

    return max(marks, key=volume, default=None)


def _header_model_pieces(body: _WorldBody, model: PartModel) -> list[_Piece]:
    """A header, as one borrowed pin drawn at every hole.

    THE ONE PACKAGE THAT IS A REPETITION. KiCad ships a model per length -- forty of them
    per row count -- and they are the same pin over and over, so one mesh glyphed at the
    holes is the same picture for a fortieth of the library. It is also what lets a header
    of a length nobody shipped a model for be drawn at all, which matters because this
    application generates header footprints on demand.

    The pin is square and its shroud is square, so a turned header needs no turn here: the
    positions already carry it.
    """
    return [
        _Piece(
            source=_mesh(str(piece.path)),
            rgb=_rgb(body.style.fill if piece.is_body else piece.color),
            position=(0.0, 0.0, 0.0),
            material=MODEL_MATERIALS.get(piece.material, MOULDED),
            instances=tuple((px, py, 0.0) for px, py in body.pins),
        )
        for piece in model.pieces
    ]


def _terminal_block_pieces(
    body: _WorldBody, blocks: tuple[PartModel, PartModel, PartModel], comp: Any
) -> list[_Piece]:
    """A screw terminal of any length, as a head at pin 1, a way at every pin between and a
    tail at the last -- see ``partmodels.terminal_block_models``.

    Each slice was cut with its own pin at the origin, so each goes down at its pin and
    takes the component's own turn and mirror, exactly as ``_model_pieces`` does for a
    whole package at pin 1. Turning and mirroring every way about its own pin, at pin
    positions that are already turned and mirrored, is the same block as turning and
    mirroring the whole of it about pin 1 -- the pins say where, the slices say what.
    """
    head, way, tail = blocks
    turn = (0.0, 0.0, -float(comp.rotation))
    scale = (-1.0, 1.0, 1.0) if comp.mirrored else (1.0, 1.0, 1.0)
    placed = [(head, body.pins[0])]
    placed += [(way, pin) for pin in body.pins[1:-1]]
    placed.append((tail, body.pins[-1]))
    return [
        _Piece(
            source=_mesh(str(piece.path)),
            rgb=_rgb(body.style.fill if piece.is_body else piece.color),
            position=(pin_x, pin_y, 0.0),
            orientation=turn,
            scale=scale,
            material=MODEL_MATERIALS.get(piece.material, MOULDED),
        )
        for model, (pin_x, pin_y) in placed
        for piece in model.pieces
    ]


def build_component(lookup: FootprintLookup, comp: Any, board: Board) -> list[vtk.vtkActor]:
    """Every solid making up one placed component.

    A list rather than a single actor because real parts are not one colour: a TO-220 is
    black plastic with a bright metal tab, a pin header is black moulding with gold pins, and
    an electrolytic has a printed stripe. Collapsing those into one actor is what made the
    3D view look like a board full of identical blocks.
    """
    body = _world_body(lookup, comp, board)
    if body is None:
        return []
    footprint = lookup(comp.footprint_id)
    assert footprint is not None  # _world_body already returned None otherwise.
    pieces = _pieces_for(body, footprint, comp, board)
    return [_actor_for(piece) for piece in pieces]


def _barrel_of(model: PartModel) -> tuple[float, float, float] | None:
    """A lying cylinder's radius, height off the board and length, measured off the mesh.

    From the BODY piece rather than the whole model, because the leads run out past both
    ends and would give a barrel three times too long.
    """
    piece = model.body
    if piece is None or len(piece.bounds) != 6:
        return None
    x0, _y0, z0, x1, _y1, z1 = piece.bounds
    return ((z1 - z0) / 2, (z0 + z1) / 2, x1 - x0)


def _pieces_for(
    body: _WorldBody, footprint: Any, comp: Any, board: Board
) -> list[_Piece]:
    """The solids of one part: a borrowed package where there is one, generated otherwise.

    THE GENERATED BODY IS STILL THE ANSWER FOR EVERYTHING ELSE and it is still the fallback
    here -- a footprint nobody mapped, a part asked for by a generated id, a build that
    shipped without the meshes. Nothing depends on a model existing, which is what lets the
    borrowed ones be an improvement rather than a requirement.

    Leads are ours either way. A model is cut off at the board surface by the converter, and
    what goes through the hole and stands trimmed on the solder side is drawn from the
    board's own thickness -- see ``_through_hole_pieces``.
    """
    if footprint.body.archetype == "module-board":
        return _module_pieces(body, footprint, comp, board)
    if footprint.body.archetype == "pin-header":
        header = header_pin_model()
        if header is not None:
            # The borrowed pin is cut at the board surface like every model, so the part of
            # it that goes through the board is ours, square like the pin above it. Without
            # it a header was the one part with nothing showing on the solder side.
            return [
                *_header_model_pieces(body, header),
                *_through_hole_pieces(body, 0.0, blade=(_MODULE_PIN_MM, _MODULE_PIN_MM)),
            ]
    model = _model_for(comp.footprint_id)
    if model is None and footprint.body.archetype == "screw-terminal" and len(body.pins) >= 2:
        # A terminal with no model of its own -- every length the library does not have,
        # which is every length but two and three -- is assembled from the three slices.
        blocks = terminal_block_models()
        if blocks is not None:
            return [
                *_terminal_block_pieces(body, blocks, comp),
                *_through_hole_pieces(body, 0.0),
            ]
    if model is not None:
        axial = footprint.body.archetype == "axial-cylinder"
        # A borrowed polarised part already carries its mark where the real part has it --
        # a diode's band, a can's stripe -- so ours is not added (on a diode it made two
        # bands) and the model's is painted in the style's accent, the colour 2D draws it.
        mark = _polarity_mark(model) if body.polarity is not None else None
        markings = (
            _axial_markings(body, _barrel_of(model), polarity_band=mark is None) if axial else []
        )
        return [
            *_model_pieces(
                body,
                model,
                comp,
                board,
                polarity_mark=(mark, body.style.accent) if mark is not None else None,
            ),
            *markings,
            *_through_hole_pieces(body, 0.0),
        ]
    builder = _BUILDERS.get(footprint.body.archetype, _box_pieces)
    generated: list[_Piece] = builder(body)
    return generated


#: The plastic of a header strip, under a module or holding its pins.
_HEADER_PLASTIC_RGB = (0.11, 0.12, 0.14)
#: How far a module's header pins stand out of the top of its board.
_MODULE_PIN_TIP_MM = 1.6
#: A header pin's section.
_MODULE_PIN_MM = 0.64


def _module_pieces(body: _WorldBody, footprint: Any, comp: Any, board: Board) -> list[_Piece]:
    """A module: its own board up on its seat, the header under it, its pins through it,
    and a block for what is on it. Its pin names are printed by ``build_pin_names``, which
    the View menu can turn off.

    THE HEADER IS WHAT HOLDS IT UP and what is actually soldered to this board: a female
    strip as tall as the seat (8.5 mm is a standard socket) or, soldered straight in, the
    plastic spacer of the module's own male pins. One strip per unbroken run of pins along
    a header row, so a 2 x 19 devkit stands on two strips and a module with pins three holes
    apart on single posts.

    WHAT IS ON THE MODULE is not known -- the id carries its tallest part's height and no
    more -- so it is one dark block that tall in the middle of the board: an honest envelope
    rather than a guessed chip, and the height DRC measures.
    """
    dims = footprint.body.dims
    seat = float(dims.get("seat", MODULE_SEAT_SOCKETED_MM))
    top = float(dims.get("top", 2.0))
    pcb_top = seat + MODULE_PCB_MM
    pitch = board.pitch
    pieces: list[_Piece] = [
        _Piece(
            source=_box(body.size_x, body.size_y, MODULE_PCB_MM),
            rgb=_rgb(body.style.fill),
            position=(body.x, body.y, seat + MODULE_PCB_MM / 2),
            material=MASK,
        )
    ]

    # The header rows, in world axes: a part turned a quarter turns its rows with it.
    along_x = _module_rows_along_world_x(footprint, comp)
    rows: dict[float, list[float]] = {}
    for px, py in body.pins:
        across, along = (py, px) if along_x else (px, py)
        rows.setdefault(round(across, 3), []).append(along)
    for across, positions in rows.items():
        positions.sort()
        run = [positions[0]]
        for position in [*positions[1:], math.inf]:
            if position - run[-1] <= pitch * 1.05:
                run.append(position)
                continue
            length = run[-1] - run[0] + pitch
            middle = (run[0] + run[-1]) / 2
            size = (length, pitch, seat) if along_x else (pitch, length, seat)
            where = (middle, across) if along_x else (across, middle)
            pieces.append(
                _Piece(
                    source=_box(*size),
                    rgb=_HEADER_PLASTIC_RGB,
                    position=(where[0], where[1], seat / 2),
                    material=MOULDED,
                )
            )
            run = [position]

    # The pins, through the module's board and a little out of the top of it.
    stand = MODULE_PCB_MM + _MODULE_PIN_TIP_MM
    pieces.append(
        _Piece(
            source=_box(_MODULE_PIN_MM, _MODULE_PIN_MM, stand),
            rgb=LEAD_RGB,
            position=(0.0, 0.0, 0.0),
            material=TINNED,
            instances=tuple((px, py, seat + stand / 2) for px, py in body.pins),
        )
    )

    # What is on the module: one block as tall as its tallest part.
    block_x, block_y = module_block_size(body.size_x, body.size_y)
    pieces.append(
        _Piece(
            source=_box(block_x, block_y, top),
            rgb=(0.106, 0.114, 0.133),
            position=(body.x, body.y, pcb_top + top / 2),
            material=MOULDED,
        )
    )

    return pieces + _through_hole_pieces(body, 0.0, blade=(_MODULE_PIN_MM, _MODULE_PIN_MM))


def _module_rows_along_world_x(footprint: Any, comp: Any) -> bool:
    """Whether a module's header rows lie along world x: along its own columns when it has
    as many columns as rows (``bodies.pin_labels`` asks the same), swapped by a quarter
    turn."""
    columns = {pin.d_col for pin in footprint.pins}
    rows = {pin.d_row for pin in footprint.pins}
    along_local_x = len(columns) >= len(rows)
    turned = int(comp.rotation) in (90, 270)
    return along_local_x != turned


#: A label on the board in 3D: the 2D view's warm white ink on its dark tag.
BOARD_NOTE_INK_RGB = (0.97, 0.95, 0.87)
BOARD_NOTE_TAG_RGB = (0.09, 0.10, 0.12)


def _label_decal(
    text: str,
    height_mm: float,
    *,
    ink: tuple[float, float, float] = BOARD_NOTE_INK_RGB,
    ground: tuple[float, float, float] | None = BOARD_NOTE_TAG_RGB,
    bold: bool = True,
    pad_mm: float | None = None,
    tag_height_mm: float | None = None,
) -> tuple[Any, float, float] | None:
    """A label drawn by Qt -- every character the font has, a Turkish one included -- on
    its own tag, as a texture, with the millimetres it spans.

    NOT ``vtkVectorText``, which knows ASCII and nothing else: "ALT YÜZ" came out "ALT YZ"
    and an arrow came out as nothing, on the one kind of text in the view that a person
    typed in their own language. ``None`` when there is no Qt application to draw with --
    a bare engine test -- and the caller falls back to the vector glyphs.

    ``ground`` ``None`` leaves the tag clear, for ink printed straight onto something
    (a module's own board). ``pad_mm`` and ``tag_height_mm`` size the tag in millimetres
    where it has to match one drawn elsewhere; left out, it is sized from the letters.
    """
    import numpy
    from PySide6.QtCore import QPointF as _Point
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter

    if QGuiApplication.instance() is None:
        return None
    font = QFont()
    font.setPixelSize(96)
    font.setBold(bold)
    metrics = QFontMetricsF(font)
    cap = metrics.capHeight() or 96 * 0.7
    px_per_mm = cap / height_mm
    pad = cap * 0.35 if pad_mm is None else pad_mm * px_per_mm
    width = max(1, math.ceil(metrics.horizontalAdvance(text) + 2 * pad))
    height = max(1, math.ceil(cap * 1.8 if tag_height_mm is None else tag_height_mm * px_per_mm))
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(_Qt.GlobalColor.transparent if ground is None else QColor.fromRgbF(*ground))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setFont(font)
    painter.setPen(QColor.fromRgbF(*ink))
    painter.drawText(_Point(pad, (height + cap) / 2), text)
    painter.end()
    raw = bytes(image.constBits())[: image.sizeInBytes()]
    rows = numpy.frombuffer(raw, dtype="uint8").reshape(
        height, image.bytesPerLine()
    )[:, : width * 4]
    # VTK counts image rows from the bottom.
    pixels = numpy.ascontiguousarray(rows[::-1]).reshape(-1, 4)
    data = vtk.vtkImageData()
    data.SetDimensions(width, height, 1)
    scalars = numpy_support.numpy_to_vtk(  # type: ignore[no-untyped-call]
        pixels, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR
    )
    scalars.SetNumberOfComponents(4)
    data.GetPointData().SetScalars(scalars)
    texture = vtk.vtkTexture()
    texture.SetInputData(data)
    texture.InterpolateOn()
    per_px = height_mm / cap
    return texture, width * per_px, height * per_px


def _board_note_frame(note: Any, board: Board) -> tuple[Any, bool]:
    """The transform from a label's own frame -- text along +x, up +y -- to the board:
    turned clockwise as seen from its own face, reflected for the underside."""
    centre = board_note_centre_mm(note, board)
    bottom = note.side == "bottom"
    frame = vtk.vtkTransform()
    frame.Translate(
        centre.x,
        -centre.y,
        -board.thickness - PAD_LIFT_MM - _DECAL_PROUD_MM if bottom else PAD_LIFT_MM + _DECAL_PROUD_MM,
    )
    if bottom:
        frame.Scale(-1.0, 1.0, 1.0)
    frame.RotateZ(-float(note.rotation))
    return frame, bottom


def build_board_notes(doc: PerfDocument) -> list[vtk.vtkActor]:
    """Every label written on the board, on the face it is written on, reading the right
    way round from that face -- this is the one view where a label is a thing on the board
    being looked at rather than an annotation over a picture.

    Each is a flat decal with its tag baked in (``_label_decal``), unlit, as ink is. Without
    a Qt application the text falls back to vector glyphs on a separate tag.
    """
    board = doc.board
    actors: list[vtk.vtkActor] = []
    fallback_text = vtk.vtkAppendPolyData()
    fallback_tags = vtk.vtkAppendPolyData()
    fallen_back = False
    for note in doc.board_notes:
        frame, bottom = _board_note_frame(note, board)
        decal = _label_decal(note.text, note.size_mm)
        if decal is not None:
            texture, width, height = decal
            plane = vtk.vtkPlaneSource()
            plane.SetOrigin(-width / 2, -height / 2, 0.0)
            plane.SetPoint1(width / 2, -height / 2, 0.0)
            plane.SetPoint2(-width / 2, height / 2, 0.0)
            placed = vtk.vtkTransformPolyDataFilter()
            placed.SetTransform(frame)
            placed.SetInputConnection(plane.GetOutputPort())
            placed.Update()
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(placed.GetOutput())
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.SetTexture(texture)
            actor.GetProperty().LightingOff()
            actors.append(actor)
            continue
        fallen_back = True
        vector = vtk.vtkVectorText()
        vector.SetText(note.text)
        vector.Update()
        bounds = vector.GetOutput().GetBounds()
        text_w = max(bounds[1] - bounds[0], 1e-6) * note.size_mm
        tag = vtk.vtkCubeSource()
        tag.SetXLength(text_w + 0.8)
        tag.SetYLength(note.size_mm * 1.8)
        tag.SetZLength(0.02)
        placed_tag = vtk.vtkTransformPolyDataFilter()
        placed_tag.SetTransform(frame)
        placed_tag.SetInputConnection(tag.GetOutputPort())
        placed_tag.Update()
        fallback_tags.AddInputData(placed_tag.GetOutput())
        glyphs = vtk.vtkTransform()
        glyphs.DeepCopy(frame)
        # Proud of its tag, on whichever side of the board the tag faces out from.
        glyphs.Translate(0.0, 0.0, -_DECAL_PROUD_MM if bottom else _DECAL_PROUD_MM)
        glyphs.Scale(note.size_mm, note.size_mm, note.size_mm)
        glyphs.Translate(-(bounds[0] + bounds[1]) / 2, -(bounds[2] + bounds[3]) / 2, 0.0)
        placed = vtk.vtkTransformPolyDataFilter()
        placed.SetTransform(glyphs)
        placed.SetInputData(vector.GetOutput())
        placed.Update()
        fallback_text.AddInputData(placed.GetOutput())
    if fallen_back:
        for append, rgb in ((fallback_tags, BOARD_NOTE_TAG_RGB), (fallback_text, BOARD_NOTE_INK_RGB)):
            append.Update()
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(append.GetOutput())
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*rgb)
            _finish(actor.GetProperty(), INK)
            actors.append(actor)
    return actors


#: The tag a pin name on this board is printed on: the 2D view's, nearly black.
PIN_NAME_TAG_RGB = (0.07, 0.08, 0.09)


def build_pin_names(
    lookup: FootprintLookup,
    comp: Any,
    board: Board,
    labels: tuple[PinLabel, ...] | None = None,
) -> list[vtk.vtkActor]:
    """One part's pin names, where ``labels`` puts them -- ``bodies.lay_out_pin_names``'s
    answer for the part, or, left out, ``bodies.pin_labels``'s as if it stood alone: on a
    module's own board, or on this board beside the part. Laid out in world axes rather
    than turned with the part, so each reads upright from above however the part is turned
    or flipped -- the same place the 2D view prints them.

    Each name is a decal Qt draws (``_label_decal``), for the reason a board label is: a
    name somebody typed in their own language -- GİRİŞ, ÇIKIŞ -- has to come out as typed,
    and ``vtkVectorText`` drops every letter that is not ASCII. Without a Qt application,
    vector glyphs stand in.
    """
    footprint = lookup(comp.footprint_id)
    if footprint is None:
        return []
    if labels is None:
        labels = pin_labels(footprint, comp, board.pitch)
    if not labels:
        return []
    body = _world_body(lookup, comp, board)
    if body is None:
        return []
    where = {pin.number: xy for pin, xy in zip(footprint.pins, body.pins, strict=False)}
    on_module = labels[0].on_module
    if on_module:
        seat = float(footprint.body.dims.get("seat", MODULE_SEAT_SOCKETED_MM))
        lift = seat + MODULE_PCB_MM + _DECAL_PROUD_MM
        ink = _rgb(body.style.accent)
    else:
        # On its tag, above the pad rings a name runs across.
        lift = PAD_LIFT_MM + _DECAL_PROUD_MM
        ink = LEGEND_RGB

    actors: list[vtk.vtkActor] = []
    pad = PIN_NAME_TAG_PAD_MM
    for label in labels:
        decal = _label_decal(
            label.name,
            PIN_NAME_HEIGHT_MM,
            ink=ink,
            # A module's names are printed on its own board, which needs no tag; names on
            # THIS board need one, as in the 2D view: white ink over white pad rings is
            # unreadable.
            ground=None if on_module else PIN_NAME_TAG_RGB,
            bold=False,
            pad_mm=pad,
            tag_height_mm=PIN_NAME_TAG_HEIGHT_MM,
        )
        if decal is None:
            return _vector_pin_names(labels, where, comp, on_module, lift, ink)
        texture, width, height = decal
        # Narrowed to the room it was given, the tag with it.
        shown = min(max(width - 2 * pad, 1e-6), label.room)
        frame = _pin_name_frame(label, where[label.number], comp, shown, lift)
        plane = vtk.vtkPlaneSource()
        plane.SetOrigin(-pad, -height / 2, 0.0)
        plane.SetPoint1(shown + pad, -height / 2, 0.0)
        plane.SetPoint2(-pad, height / 2, 0.0)
        placed = vtk.vtkTransformPolyDataFilter()
        placed.SetTransform(frame)
        placed.SetInputConnection(plane.GetOutputPort())
        placed.Update()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(placed.GetOutput())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.SetTexture(texture)
        actor.GetProperty().LightingOff()
        actors.append(actor)
    return actors


def _pin_name_frame(
    label: PinLabel, pin_xy: tuple[float, float], comp: Any, shown: float, lift: float
) -> vtk.vtkTransform:
    """The transform from a pin name's own frame -- text from the origin along +x, centred
    on y -- to the world, where it starts ``label.start`` from its pin and reads upright."""
    px, py = pin_xy
    turned_x, turned_y = transform_offset(label.dx, label.dy, comp.rotation, comp.mirrored)
    wx, wy = turned_x, -turned_y  # rows run down, the world's y runs up
    frame = vtk.vtkTransform()
    if abs(wx) > abs(wy):
        # Kept upright: a name to the LEFT of its pin ends there rather than being turned
        # over to start there and read upside down.
        start = px + label.start if wx > 0 else px - label.start - shown
        frame.Translate(start, py, lift)
    else:
        frame.Translate(px, py + (label.start if wy > 0 else -label.start), lift)
        frame.RotateZ(90.0 if wy > 0 else -90.0)
    return frame


def _vector_pin_names(
    labels: tuple[PinLabel, ...],
    where: dict[str, tuple[float, float]],
    comp: Any,
    on_module: bool,
    lift: float,
    ink: tuple[float, float, float],
) -> list[vtk.vtkActor]:
    """``build_pin_names`` with no Qt to draw with: vector glyphs on a separate tag, ASCII
    only. One actor for the glyphs and one for the tags, whatever the count."""
    text_append = vtk.vtkAppendPolyData()
    tag_append = vtk.vtkAppendPolyData()
    for label in labels:
        vector = vtk.vtkVectorText()
        vector.SetText(label.name)
        vector.Update()
        bounds = vector.GetOutput().GetBounds()
        text_width = max(bounds[1] - bounds[0], 1e-6)
        scale = min(PIN_NAME_HEIGHT_MM, label.room / text_width)
        frame = _pin_name_frame(label, where[label.number], comp, text_width * scale, 0.0)
        if not on_module:
            tag = vtk.vtkCubeSource()
            tag.SetXLength(text_width * scale + 2 * PIN_NAME_TAG_PAD_MM)
            tag.SetYLength(PIN_NAME_TAG_HEIGHT_MM)
            tag.SetZLength(0.02)
            tag.SetCenter(text_width * scale / 2, 0.0, 0.0)
            placed_tag = vtk.vtkTransformPolyDataFilter()
            placed_tag.SetTransform(frame)
            placed_tag.SetInputConnection(tag.GetOutputPort())
            placed_tag.Update()
            tag_append.AddInputData(placed_tag.GetOutput())
        glyphs = vtk.vtkTransform()
        glyphs.DeepCopy(frame)
        glyphs.Scale(scale, scale, scale)
        glyphs.Translate(-bounds[0], -(bounds[2] + bounds[3]) / 2, 0.0)
        placed = vtk.vtkTransformPolyDataFilter()
        placed.SetTransform(glyphs)
        placed.SetInputData(vector.GetOutput())
        placed.Update()
        text_append.AddInputData(placed.GetOutput())
    text_append.Update()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(text_append.GetOutput())
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*ink)
    _finish(actor.GetProperty(), INK)
    actors = [actor]
    if on_module:
        actor.SetPosition(0.0, 0.0, lift)
        return actors
    # The glyphs proud of their tag.
    actor.SetPosition(0.0, 0.0, lift + _DECAL_PROUD_MM)
    tag_append.Update()
    tag_mapper = vtk.vtkPolyDataMapper()
    tag_mapper.SetInputData(tag_append.GetOutput())
    tag_actor = vtk.vtkActor()
    tag_actor.SetMapper(tag_mapper)
    tag_actor.SetPosition(0.0, 0.0, lift)
    tag_actor.GetProperty().SetColor(*PIN_NAME_TAG_RGB)
    _finish(tag_actor.GetProperty(), INK)
    actors.append(tag_actor)
    return actors


def _attach(mapper: Any, source: Any, *, glyph: bool = False) -> None:
    """Hand a mapper either a VTK source or a finished polydata.

    Most pieces are sources with a pipeline behind them, and a few are polydata built here
    -- the D-shaped TO-92 profile, the punched tile -- which have no output port to
    connect. One place knows the difference rather than every builder.
    """
    if hasattr(source, "GetOutputPort"):
        if glyph:
            mapper.SetSourceConnection(source.GetOutputPort())
        else:
            mapper.SetInputConnection(source.GetOutputPort())
    elif glyph:
        mapper.SetSourceData(source)
    else:
        mapper.SetInputData(source)


def _actor_for(piece: _Piece) -> vtk.vtkActor:
    actor = vtk.vtkActor()
    if piece.instances:
        points = vtk.vtkPoints()
        for x, y, z in piece.instances:
            points.InsertNextPoint(x, y, z)
        data = vtk.vtkPolyData()
        data.SetPoints(points)
        glyph = vtk.vtkGlyph3DMapper()
        glyph.SetInputData(data)
        _attach(glyph, piece.source, glyph=True)
        glyph.SetOrient(False)
        glyph.SetScaling(False)
        actor.SetMapper(glyph)
    else:
        mapper = vtk.vtkPolyDataMapper()
        _attach(mapper, piece.source)
        actor.SetMapper(mapper)
        actor.SetScale(*piece.scale)
        actor.SetOrientation(*piece.orientation)
        actor.SetPosition(*piece.position)
    prop = actor.GetProperty()
    prop.SetColor(*piece.rgb)
    _finish(prop, piece.material)
    prop.SetOpacity(piece.opacity)
    return actor


def _conductor_centreline(
    cond: Conductor,
    board: Board,
    run_z: float,
    joint_z: float,
    is_trace: bool,
) -> list[tuple[float, float, float]]:
    """The path a conductor's tube actually follows, in board mm.

    A SOLDER RUN LIES FLAT. It is fused to the copper along its whole length, so its
    centreline is the hole centres at one height and nothing else.

    A WIRE GOES INTO ITS HOLES. It was drawn as a stick floating parallel to the board and
    stopping in mid-air above each pad, with the fillet drawn at the stick's height rather
    than at the pad -- so a wire neither entered the board nor touched what it was soldered
    to. Real wire is bent down at each end and the joint is made where it meets the copper.
    So each end drops from the run height to the pad, over a short horizontal run-in: long
    enough to read as a bend rather than a staple, and never more than a fraction of the
    segment it is bending within, so a two-hole link does not turn into a V.

    This is also what keeps a wire lifted over an obstacle attached to the board at all --
    at one stacking level its ends are more than a bead's width above the pads.
    """
    flat = [(*_xy(board, hole), run_z) for hole in cond.path]
    if is_trace:
        # A point at every pad and TRACE_SAMPLES_PER_STEP - 1 between each pair, so
        # `_trace_swell` can bring the radius down and back up smoothly. Nothing else about
        # a run's path moves: it is fused to the copper along its whole length and goes
        # exactly where the pads are.
        if len(flat) < 2:
            return flat
        woven: list[tuple[float, float, float]] = [flat[0]]
        for previous, point in pairwise(flat):
            for step in range(1, TRACE_SAMPLES_PER_STEP):
                t = step / TRACE_SAMPLES_PER_STEP
                woven.append(
                    (
                        previous[0] + (point[0] - previous[0]) * t,
                        previous[1] + (point[1] - previous[1]) * t,
                        run_z,
                    )
                )
            woven.append(point)
        return woven
    if len(flat) < 2:
        return flat

    drop = abs(run_z - joint_z)
    out: list[tuple[float, float, float]] = []
    for end, inward in ((0, 1), (-1, -2)):
        x, y, _ = flat[end]
        ix, iy, _ = flat[inward]
        span = math.hypot(ix - x, iy - y)
        # SHORT, and kept near the pad. A bend as long as it is deep reads nicely and
        # sweeps a long way: a wire coming down from two stacking levels ramped almost
        # four millimetres across the board, through whatever was lying under it -- which
        # is two of the fifteen golden fixtures. Held inside a third of a pitch, the
        # descent stays over its own pad and its neighbours, where the only other thing
        # is something soldered to the same hole. Never longer than the drop either, or a
        # wire lying flat on the board acquires a bend it does not need.
        run_in = min(drop, board.pitch / 3, span * 0.35)
        t = (run_in / span) if span else 0.0
        elbow = (x + (ix - x) * t, y + (iy - y) * t, run_z)
        out = (
            [(x, y, joint_z), elbow, *flat[1:-1]]
            if end == 0
            else [*out, elbow, (x, y, joint_z)]
        )
    return _rounded(out, WIRE_BEND_RADIUS_MM)


def _rounded(
    points: list[tuple[float, float, float]], radius: float, steps: int = 5
) -> list[tuple[float, float, float]]:
    """A polyline with every corner bent round, as wire is: each corner replaced by a curve
    from ``radius`` before it to ``radius`` after it -- less where a leg is too short to
    give that much, never more than half a leg, so two bends cannot overlap. The ends stay
    exactly where they were: that is where the wire is soldered."""
    if len(points) < 3:
        return points
    out = [points[0]]
    for a, corner, b in zip(points, points[1:], points[2:], strict=False):
        into = [corner[i] - a[i] for i in range(3)]
        out_of = [b[i] - corner[i] for i in range(3)]
        len_in, len_out = math.hypot(*into), math.hypot(*out_of)
        if len_in == 0 or len_out == 0:
            continue
        cos = sum(into[i] * out_of[i] for i in range(3)) / (len_in * len_out)
        if cos > 0.999:
            out.append(corner)
            continue
        reach = min(radius, len_in / 2, len_out / 2)
        start = tuple(corner[i] - into[i] / len_in * reach for i in range(3))
        end = tuple(corner[i] + out_of[i] / len_out * reach for i in range(3))
        for step in range(steps + 1):
            t = step / steps
            # A quadratic curve with the corner as its control point: tangent to both legs.
            out.append(
                tuple(  # type: ignore[arg-type]
                    (1 - t) ** 2 * start[i] + 2 * (1 - t) * t * corner[i] + t**2 * end[i]
                    for i in range(3)
                )
            )
    out.append(points[-1])
    return out


def _trace_swell(cond: Conductor, centreline: list[tuple[float, float, float]]) -> list[float]:
    """How wide the run is at each point of its centreline, as a multiple of the ridge.

    ``_conductor_centreline`` gives a solder run one point per pad, and a tube through
    those is a constant ridge with no joints in it. The midpoints inserted here are what
    lets the radius come back DOWN between pads: full width where it is soldered, drawn in
    between, which is the silhouette of a run of solder along a row of pads and the reason
    somebody can count the joints on one.
    """
    del cond
    joint = 1.0 / TRACE_WAIST_RATIO
    swell = []
    for index in range(len(centreline)):
        # Full at a pad (phase 0), narrowest halfway to the next (phase 1/2), and a cosine
        # between -- the rounded outline of solder drawn from one joint into the next.
        phase = (index % TRACE_SAMPLES_PER_STEP) / TRACE_SAMPLES_PER_STEP
        swell.append(1.0 + (joint - 1.0) * (1.0 + math.cos(2 * math.pi * phase)) / 2)
    return swell


def build_conductor(
    cond: Conductor,
    board: Board,
    stack: int = 0,
    net_class: NetClass | None = None,
    signal_index: int = 0,
) -> list[vtk.vtkActor]:
    """One conductor's solids.

    ``stack`` separates conductors that share a layer. Everything on the solder side used
    to sit at one z per ``layer_z``, so two bare wires crossing were drawn INTERSECTING --
    occupying the same space, which is not a thing wire does and looked like a modelling
    error because it was one. A small per-conductor offset makes one pass over the other,
    which is what the board actually looks like.
    """
    is_trace = contacts_every_path_hole(cond)
    z = conductor_z(cond, board, stack)
    joint_z = pad_z(board, cond.side)
    centreline = _conductor_centreline(cond, board, z, joint_z, is_trace)
    swell = _trace_swell(cond, centreline) if is_trace else None

    insulated = cond.kind in ("insulated-wire", "top-jumper")
    radius = conductor_radius(cond)
    if insulated:
        # The sleeve stops short of each end and the tinned core runs on into the hole:
        # the sleeve along the trimmed centreline, the core along all of it.
        sleeve = _trimmed(centreline, WIRE_STRIP_MM)
        body = _tube_actor(sleeve, radius) if len(sleeve) > 1 else None
        core = _tube_actor(centreline, WIRE_CORE_RADIUS_MM)
        core.GetProperty().SetColor(*BARE_RGB)
        _finish(core.GetProperty(), BRIGHT_TIN)
        actors = [core]
        if body is not None:
            rgb = wire_rgb(cond, net_class, signal_index)
            body.GetProperty().SetColor(*rgb)
            _finish(body.GetProperty(), INSULATION)
            actors.append(body)
    else:
        actor = _tube_actor(centreline, radius, swell)
        if swell is not None:
            # Squashed about the copper, for TRACE_FLATTEN's reason.
            _flatten_about(actor, joint_z)
        rgb = (_own_rgb(cond) or SOLDER_RGB) if is_trace else wire_rgb(cond, net_class, signal_index)
        actor.GetProperty().SetColor(*rgb)
        # Solder is metal and it is ROUGH metal -- a broad soft sheen rather than the tight
        # glint tinned wire gives. Making it smooth is what once made a run look like wire,
        # which is the one thing it must not look like; leaving it matte is what made it
        # look like grey plumbing, which is not better. The difference is one number now.
        _finish(actor.GetProperty(), SOLDER_MAT if is_trace else BRIGHT_TIN)
        actors = [actor]

    # The distinction that matters: a trace is soldered at EVERY pad it crosses, a wire
    # only at its two ends. Render exactly that -- driven by the same
    # `contacts_every_path_hole` predicate the connectivity engine itself uses.
    #
    # A run's joints ALONG its length are in the tube above, because a run of solder is one
    # piece of metal. Its two ENDS still need a solid: a tube's cap is a flat disc, which at
    # a corner shows as a sliced-off face. At exactly the radius the tube already has there
    # and squashed as the run is, a sphere is tangent to it and the seam does not exist.
    #
    # A wire's two ends are fillets -- solder, on the ends of something that is not, and the
    # cone of it round each end is how you see where a wire is actually attached.
    ends = vtk.vtkPoints()
    for hole in (cond.path[0], cond.path[-1]):
        x, y = _xy(board, hole)
        # AT THE PAD, not at the conductor. A fillet is centred on the copper and wicks
        # into the hole; drawn at a lifted wire's own height it would hang in the air above
        # the pad it is supposedly made on.
        ends.InsertNextPoint(x, y, joint_z)
    end_data = vtk.vtkPolyData()
    end_data.SetPoints(ends)
    if is_trace:
        sphere = vtk.vtkSphereSource()
        sphere.SetRadius(radius)
        sphere.SetThetaResolution(BEAD_RESOLUTION)
        sphere.SetPhiResolution(BEAD_RESOLUTION)
        sphere.Update()
        cap: vtk.vtkPolyData = sphere.GetOutput()
    else:
        cap = _fillet_source(radius if not insulated else WIRE_CORE_RADIUS_MM, cond.side)
    glyph = vtk.vtkGlyph3DMapper()
    glyph.SetInputData(end_data)
    glyph.SetSourceData(cap)
    glyph.SetOrient(False)
    glyph.SetScaling(False)
    beads = vtk.vtkActor()
    beads.SetMapper(glyph)
    if is_trace:
        _flatten_about(beads, joint_z)
    beads.GetProperty().SetColor(*SOLDER_RGB)
    # The same material as the run it swells out of -- a joint and the solder leading into
    # it are one piece of metal, and two finishes would draw a seam that is not there.
    _finish(beads.GetProperty(), SOLDER_MAT)
    actors.append(beads)
    return actors


def _tube_actor(
    centreline: list[tuple[float, float, float]], radius: float, swell: list[float] | None = None
) -> vtk.vtkActor:
    """A tube along ``centreline``: ``radius`` throughout, or -- with ``swell`` -- that
    radius at the narrowest point and each point's multiple of it elsewhere."""
    points = vtk.vtkPoints()
    line = vtk.vtkPolyLine()
    line.GetPointIds().SetNumberOfIds(len(centreline))
    for i, (x, y, pz) in enumerate(centreline):
        points.InsertNextPoint(x, y, pz)
        line.GetPointIds().SetId(i, i)
    cells = vtk.vtkCellArray()
    cells.InsertNextCell(line)
    poly = vtk.vtkPolyData()
    poly.SetPoints(points)
    poly.SetLines(cells)
    if swell is not None:
        widths = vtk.vtkDoubleArray()
        widths.SetName("swell")
        for value in swell:
            widths.InsertNextValue(value)
        poly.GetPointData().SetScalars(widths)

    tube = vtk.vtkTubeFilter()
    tube.SetInputData(poly)
    # VTK scales the radius by scalar/min(scalar), so the radius set here is the value at
    # the NARROWEST point -- the bridge between two pads, for a run.
    tube.SetRadius(radius * TRACE_WAIST_RATIO if swell is not None else radius)
    tube.SetNumberOfSides(TUBE_SIDES)
    tube.CappingOn()
    if swell is not None:
        # ONE SURFACE for a solder run, swelling at each pad and drawing in between it.
        # The joints used to be spheres dropped on top of a constant tube, which meets it
        # in a hard crease all the way round and reads as a bead threaded on a wire -- two
        # objects where the board has one. A run of solder is a single fillet, and varying
        # the tube's own radius is what says so.
        tube.SetVaryRadiusToVaryRadiusByScalar()
        tube.SetRadiusFactor(1.0 / TRACE_WAIST_RATIO)

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(tube.GetOutputPort())
    # The swell scalars are geometry, not data. Left visible, VTK colour-maps them and a
    # run of solder comes out as a blue-to-cyan rainbow.
    mapper.ScalarVisibilityOff()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    return actor


def _flatten_about(actor: vtk.vtkActor, plane_z: float) -> None:
    """Squash an actor by ``TRACE_FLATTEN`` towards the plane ``z = plane_z`` -- the copper
    a run of solder is fused to -- leaving it where it is in x and y."""
    actor.SetOrigin(0.0, 0.0, plane_z)
    actor.SetScale(1.0, 1.0, TRACE_FLATTEN)


def _trimmed(
    centreline: list[tuple[float, float, float]], strip: float
) -> list[tuple[float, float, float]]:
    """``centreline`` with ``strip`` millimetres of its length taken off each end: where an
    insulated wire's sleeve stops and the stripped core begins. Empty when there is not
    that much wire."""
    lengths = [math.dist(a, b) for a, b in pairwise(centreline)]
    if sum(lengths) <= 2 * strip:
        return []

    def cut(points: list[tuple[float, float, float]], steps: list[float]) -> list[tuple[float, float, float]]:
        remaining = strip
        for index, length in enumerate(steps):
            if length > remaining:
                a, b = points[index], points[index + 1]
                t = remaining / length
                start = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
                return [start, *points[index + 1 :]]
            remaining -= length
        return []

    front = cut(centreline, lengths)
    back = cut(front[::-1], [math.dist(a, b) for a, b in pairwise(front[::-1])])
    return back[::-1]


@functools.lru_cache(maxsize=16)
def _fillet_source(lead_radius: float, side: BoardSide) -> vtk.vtkPolyData:
    """The solder round a lead where it comes through a pad on ``side``: a cone with a
    concave flank from ``SOLDER_FILLET_BASE_MM`` on the copper up to just over the lead,
    standing off the face it is made on -- down from the solder side, up from the top.

    Built once per size and face and shared: every wire end and every lead on a board is
    one of three or four of these, and each is a lathe, a sweep and a normals pass. Only
    ever handed to a glyph mapper as SOURCE DATA, which reads it and never changes it.
    """
    rise = -1.0 if side == "bottom" else 1.0
    # Ending AT the lead, so the lead or the wire running out of it closes the top: a
    # fillet that stopped wider than its lead showed a flat disc there, a stump with
    # something stuck in it.
    top = lead_radius
    base = SOLDER_FILLET_BASE_MM
    steps = 10
    profile = [(0.0, 0.0)]
    for index in range(steps + 1):
        t = index / steps
        profile.append((top + (base - top) * (1.0 - t) ** 2, rise * SOLDER_FILLET_HEIGHT_MM * t))
    profile.append((0.0, rise * SOLDER_FILLET_HEIGHT_MM))
    return _lathe(profile, resolution=BEAD_RESOLUTION + 8)


def build_joints(doc: PerfDocument, lookup: FootprintLookup) -> list[vtk.vtkActor]:
    """A fillet of solder round every lead where it comes through the solder side, in one
    instanced actor.

    The leads came out of bare rings: a board with every part fitted and nothing soldered,
    on the one view whose job is to show the solder side. Not drawn on a hole a mounting
    bore has taken or a finger that was never drilled -- a lead there is DRC's error to
    report, and a joint drawn on it would say it had been made.
    """
    board = doc.board
    dead = patched_holes(doc) | undrilled_holes(doc)
    z = pad_z(board, "bottom")
    points = vtk.vtkPoints()
    radius = LEAD_RADIUS_MM
    for comp in doc.components:
        footprint = lookup(comp.footprint_id)
        if footprint is None:
            continue
        radius = max(radius, footprint.lead_diameter / 2 if footprint.lead_diameter else 0.0)
        for _pin, hole in all_pin_holes(comp, footprint):
            if not (0 <= hole.col < board.cols and 0 <= hole.row < board.rows):
                continue
            if hole_key(hole) in dead:
                continue
            x, y = _xy(board, hole)
            points.InsertNextPoint(x, y, z)
    if points.GetNumberOfPoints() == 0:
        return []
    data = vtk.vtkPolyData()
    data.SetPoints(points)
    glyph = vtk.vtkGlyph3DMapper()
    glyph.SetInputData(data)
    glyph.SetSourceData(_fillet_source(min(radius, 0.4), "bottom"))
    glyph.SetOrient(False)
    glyph.SetScaling(False)
    actor = vtk.vtkActor()
    actor.SetMapper(glyph)
    actor.GetProperty().SetColor(*SOLDER_RGB)
    _finish(actor.GetProperty(), SOLDER_MAT)
    return [actor]


def _own_rgb(cond: Conductor) -> tuple[float, float, float] | None:
    """A conductor's own colour, read by the 2D view's reader (``view2d.explicit_colour``),
    or None. Reading it here as ``#rrggbb`` alone drew a wire the document called "red" in
    its net's colour while the 2D view drew it red."""
    from .view2d import explicit_colour

    colour = explicit_colour(getattr(cond, "color", None))
    return None if colour is None else (colour.redF(), colour.greenF(), colour.blueF())


def _insulation_rgb(net_class: NetClass | None, signal_index: int) -> tuple[float, float, float]:
    """An insulated wire's colour, from the same convention the 2D view and the cut list
    use -- so a wire is the same colour on screen, in 3D and on the list someone works
    from."""
    from .view2d import insulation_color

    colour = insulation_color(net_class, signal_index)
    return (colour.redF(), colour.greenF(), colour.blueF())


def wire_rgb(
    cond: Conductor, net_class: NetClass | None, signal_index: int
) -> tuple[float, float, float]:
    """The colour one wire is: its own if it names one, its sleeve's by the net's class if
    it wears one, bare tin otherwise. The STEP export asks this too
    (``ui/export_step``), so a wire is the same red in the view and in the CAD program."""
    own = _own_rgb(cond)
    if own is not None:
        return own
    if cond.kind in ("insulated-wire", "top-jumper"):
        return _insulation_rgb(net_class, signal_index)
    return BARE_RGB


def net_colouring(doc: PerfDocument) -> tuple[dict[str, NetClass], dict[str, int]]:
    """Each net's class, and each signal net's place in the colour cycle -- what
    :func:`wire_rgb` needs to know about the net a wire is on, worked out once a board."""
    net_class_by_id = {net.id: net.net_class for net in doc.nets}
    signal_index = {
        net.id: index
        for index, net in enumerate(n for n in doc.nets if n.net_class == "signal")
    }
    return net_class_by_id, signal_index


# --------------------------------------------------------------------------- scene


#: How far a part rises off the board in the exploded view, in mm. Well clear of the
#: tallest thing in the registry (a 20 mm TO-220), so no part floats inside its
#: neighbour, and the leads stay pointing at the holes they came out of.
EXPLODED_LIFT_MM: float = 26.0

#: What a dimmed actor's colour is multiplied by. Enough that the part a step is about is
#: unmistakable in a thumbnail; not so far that the rest of the board stops being legible
#: context, because a step image that does not show WHERE is not worth printing.
DIM_FACTOR: float = 0.42


#: Leader lines in the exploded view: thin, unlit, and darker than any part, so they
#: read as annotation rather than as wire.
LEADER_RGB: tuple[float, float, float] = (0.42, 0.45, 0.50)


def build_drop_lines(
    lookup: FootprintLookup, doc: PerfDocument, lift: float
) -> vtk.vtkActor | None:
    """A line from every lifted part down to the holes it drops into.

    Without these a vertical explosion is ambiguous, and measurably so: a part over the
    MIDDLE of the board projects onto the board from the standard three-quarter viewpoint
    and reads as sitting on it, while one near an edge reads as floating. Same lift, two
    different apparent meanings, decided by nothing but where the part happens to be.

    Lines fix it at any lift, and they are what the view is for (PLAN.md D7): the question
    an exploded view answers is not "what is on this board" — the assembled view answers
    that — but "which holes does THIS go in", and a leader line is the answer drawn.

    One actor for every line on the board. A part with no known footprint contributes
    nothing, as everywhere else.
    """
    if lift <= 0:
        return None

    points = vtk.vtkPoints()
    lines = vtk.vtkCellArray()
    for comp in doc.components:
        footprint = lookup(comp.footprint_id)
        if footprint is None:
            continue
        for _pin, hole in all_pin_holes(comp, footprint):
            x, y = _xy(doc.board, hole)
            first = points.InsertNextPoint(x, y, 0.0)
            second = points.InsertNextPoint(x, y, lift)
            lines.InsertNextCell(2)
            lines.InsertCellPoint(first)
            lines.InsertCellPoint(second)

    if points.GetNumberOfPoints() == 0:
        return None

    data = vtk.vtkPolyData()
    data.SetPoints(points)
    data.SetLines(lines)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(data)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    prop = actor.GetProperty()
    prop.SetColor(*LEADER_RGB)
    prop.SetLineWidth(1.0)
    # A leader is an ANNOTATION, not an object: it is drawn at its own colour whatever the
    # room is doing. ``SetLighting(False)`` says that in one call and keeps saying it under
    # PBR, where the ambient/diffuse pair this used to set is simply ignored.
    prop.SetLighting(False)
    return actor


def _lift(actor: vtk.vtkActor, dz: float) -> vtk.vtkActor:
    """Raise one actor off the board. Added to its position rather than assigned: a
    glyphed piece bakes its instances into the points and leaves the actor at the origin,
    while a solid piece has already been positioned."""
    if dz:
        x, y, z = actor.GetPosition()
        actor.SetPosition(x, y, z + dz)
    return actor


def _dim(actor: vtk.vtkActor) -> vtk.vtkActor:
    """Push an actor back so something else can come forward.

    Keeps its hue -- a dimmed resistor still reads as a resistor -- and ROUGHENS it, which
    is how a material is taken out of the foreground now that the parts are shaded as
    materials: a highlight on something that is not the subject is exactly where the eye
    goes, and roughness is the number that takes the highlight away without taking the
    shape with it.
    """
    prop = actor.GetProperty()
    prop.SetColor(*(channel * DIM_FACTOR for channel in prop.GetColor()))
    prop.SetRoughness(min(1.0, prop.GetRoughness() + DIM_ROUGHEN))
    return actor


#: What the subject of a step is tinted towards. A fixed colour rather than "the part's
#: own, but brighter": raising the brightness of a BLACK DIP against parts dimmed to
#: near-black leaves the two indistinguishable, which is exactly what the first attempt
#: produced. A step image has one job, and it cannot depend on the part having a light
#: colour to begin with.
HIGHLIGHT_RGB: tuple[float, float, float] = (0.44, 0.72, 1.0)

#: How far towards it. Short of 1 so the shape still shades and reads as a solid object
#: rather than a flat silhouette.
HIGHLIGHT_MIX: float = 0.75


def _pick_out(actor: vtk.vtkActor) -> vtk.vtkActor:
    """The one thing this step is about. The caption names the part; this says WHERE."""
    prop = actor.GetProperty()
    # Mixed in LINEAR light, because that is what the actor's colour already is by the
    # time this runs (``_finish`` converted it) -- mixing an sRGB constant into a linear
    # colour tints towards something much brighter than the constant names.
    prop.SetColor(
        *(
            channel * (1 - HIGHLIGHT_MIX) + _to_linear(target) * HIGHLIGHT_MIX
            for channel, target in zip(prop.GetColor(), HIGHLIGHT_RGB, strict=True)
        )
    )
    # Polished as well as tinted, for the opposite reason ``_dim`` roughens: the subject
    # of a step is the one thing in the picture allowed to catch the light.
    prop.SetRoughness(PICK_OUT_ROUGHNESS)
    return actor


def populate_renderer(
    ren: vtk.vtkRenderer,
    doc: PerfDocument,
    lookup: FootprintLookup,
    *,
    exploded_mm: float = 0.0,
    highlight: str | None = None,
    pin_names: bool = True,
    board_notes: bool = True,
    subject_actors: list[vtk.vtkActor] | None = None,
) -> dict[str, int]:
    """Rebuild the board's actors in an EXISTING renderer, leaving the camera alone.

    ``exploded_mm`` lifts every part off the board, so the holes each one drops into are
    visible at once (PLAN.md D7). ``highlight`` is a component or conductor id — the value
    ``guide.step_focus`` returns — and dims everything else, which is what turns a frame
    of the assembly sequence into an illustration of one step. ``subject_actors``, if
    given, is filled with the highlighted thing's own solids, which is what
    :func:`frame_step` frames on: where a part IS is what was just drawn, not a second
    answer worked out from the footprint.

    The BOARD is never dimmed, only the other parts and the copper. A step card says which
    holes a part goes in, and a reader who cannot see the holes has been given a picture
    of the answer with the question rubbed out.

    This separation is the whole point. The interactive view is refreshed after every
    command, and refreshing used to mean constructing a fresh renderer -- which meant
    ``ResetCamera`` plus a fixed elevation and azimuth. So the 3D viewpoint silently
    snapped back to its default the moment the user did anything: rotate the board, nudge a
    part, and the rotation was gone. The camera belongs to the person looking through it,
    and only an explicit request (opening the view, flipping the board, "Reset View") may
    move it -- see :func:`apply_default_camera`.
    """
    board = doc.board
    # Actors and 2D props only. Lights are not view props, so they survive -- which is what
    # makes this safe to call repeatedly without re-adding a light every time.
    ren.RemoveAllViewProps()

    for actor in build_substrate(doc):
        ren.AddActor(actor)
    # The board's own copper goes down before the pads, so a stripboard reads as strips
    # with holes in them rather than as a grid of islands that happen to line up.
    for actor in build_strips(doc):
        ren.AddActor(actor)
    # Copper face by face, because a single-sided board genuinely has none on top: the
    # component side is bare phenolic with drilled holes, which is most of what makes
    # those boards look and solder differently.
    for face in ("top", "bottom"):
        if board.single_sided and face == "top":
            continue
        ren.AddActor(build_pads(board, face, holes_without_grid_pad(doc, face) | cut_holes(doc)))
    # A finger has no bore, so it gets no wall either -- and neither does a position a
    # mounting bore's patch has taken over, where the plate is solid.
    ren.AddActor(build_drills(board, patched_holes(doc) | undrilled_holes(doc)))
    for actor in build_legend(doc):
        ren.AddActor(actor)
    if board_notes:
        for actor in build_board_notes(doc):
            ren.AddActor(actor)
    for actor in build_edge_connectors(doc):
        ren.AddActor(actor)
    for actor in build_mounting_holes(doc):
        ren.AddActor(actor)
    if exploded_mm <= 0:
        # Not in an exploded view: the parts are off the board there, and a joint round a
        # lead that is not in its hole is solder on nothing.
        for actor in build_joints(doc, lookup):
            ren.AddActor(actor)
    leaders = build_drop_lines(lookup, doc, exploded_mm)
    if leaders is not None:
        ren.AddActor(leaders)
    # Laid out for the whole board, as the 2D view lays them out: where one part's names
    # go depends on what stands beside it (bodies.lay_out_pin_names). Measured with the
    # 2D view's own measure, imported here as Qt is everywhere else in this module.
    printed = None
    if pin_names:
        from .scenetext import pin_name_width_mm

        printed = lay_out_pin_names(doc, lookup, pin_name_width_mm)
    for comp in doc.components:
        subject = highlight is not None and comp.id == highlight
        for actor in build_component(lookup, comp, board):
            _lift(actor, exploded_mm)
            if highlight is not None:
                (_pick_out if subject else _dim)(actor)
            if subject and subject_actors is not None:
                subject_actors.append(actor)
            ren.AddActor(actor)
        if printed is not None:
            # A module's names are on its own board and rise with it; a part's names on
            # this board stay on this board.
            footprint = lookup(comp.footprint_id)
            on_module = footprint is not None and footprint.body.archetype == "module-board"
            names = printed.labels.get(comp.id, ())
            for actor in build_pin_names(lookup, comp, board, names):
                _lift(actor, exploded_mm if on_module else 0.0)
                if highlight is not None:
                    (_pick_out if subject else _dim)(actor)
                ren.AddActor(actor)
    net_class_by_id, signal_index = net_colouring(doc)
    # How high each conductor has to sit to clear what it crosses -- from the engine, so
    # 2D and 3D cannot disagree about which wire passes over which. Not a running index:
    # see occupancy.stacking_layers.
    layers = stacking_layers(doc)
    for cond in doc.conductors:
        subject = highlight is not None and cond.id == highlight
        for actor in build_conductor(
            cond,
            board,
            stack=layers.get(cond.id, cond.layer_z),
            net_class=net_class_by_id.get(cond.net_id or ""),
            signal_index=signal_index.get(cond.net_id or "", 0),
        ):
            if highlight is not None:
                (_pick_out if subject else _dim)(actor)
            if subject and subject_actors is not None:
                subject_actors.append(actor)
            ren.AddActor(actor)

    ren.ResetCameraClippingRange()
    return {"actors": ren.GetActors().GetNumberOfItems(), "pads": board.cols * board.rows}


def apply_default_camera(
    ren: vtk.vtkRenderer, flipped: bool = False, across: bool = False
) -> None:
    """Frame the board from the standard three-quarter viewpoint.

    Called when the view is first shown, when the board is flipped, and by "Reset Camera" --
    never as a side effect of the document changing.

    The orientation is set ABSOLUTELY before the three-quarter tilt is applied, because
    ``Elevation`` and ``Azimuth`` are relative and ``ResetCamera`` preserves the current
    direction of view. Without the reset to a known axis, calling this after the user had
    orbited would re-frame the board while keeping their accumulated rotation and then tilt
    a further 32 degrees from wherever that left it -- so "Reset Camera" would move the view
    without resetting it, and would land somewhere different every time it was pressed.
    These three values are vtkCamera's own defaults, so a first call is unaffected.

    THE BOARD IS FITTED ON SCREEN, AFTER THE TILT, IN THE WINDOW'S OWN SHAPE. It used to be
    ``ResetCamera`` and then a fixed ``Zoom(1.35)``: that fits a bounding SPHERE by the
    vertical view angle alone, the zoom then cuts it to three quarters, and the tilt brings
    the near edge of a tall board towards the camera -- so every portrait board had its
    near edge off the bottom of the frame (atmega328-relay: corners at y -87..914 in a
    950 px window) and its far edge off the top when flipped. ``ResetCameraScreenSpace``
    fits what is actually drawn, as projected, to ``_FRAME_FILL`` of the viewport.

    It needs the viewport's size to do that, so a renderer with no window yet is only
    ``ResetCamera``-ed, which VTK leaves alone rather than guessing. Every caller that
    shows a picture therefore calls this once the window has its size: ``render_offscreen``
    and ``render_step_images`` after ``SetSize``, and the panel on its first real resize.

    ``across`` lays the board's columns up the screen instead of its rows, for a picture of
    a tall board in a wide frame: a 2 x 8 cm strip framed upright fills a fifth of a
    landscape animation and leaves the rest of it dark.
    """
    cam = ren.GetActiveCamera()
    cam.SetPosition(0.0, 0.0, 1.0)
    cam.SetFocalPoint(0.0, 0.0, 0.0)
    cam.SetViewUp(*((-1.0, 0.0, 0.0) if across else (0.0, 1.0, 0.0)))

    if flipped:
        cam.Elevation(180)
    cam.Elevation(-32)
    cam.Azimuth(18)
    cam.OrthogonalizeViewUp()
    ren.ResetCamera()
    if _has_viewport(ren):
        ren.ResetCameraScreenSpace(_FRAME_FILL)
    ren.ResetCameraClippingRange()


#: How much of the viewport the board fills once framed: enough margin that the orbit
#: handle is not the board's own corner, little enough that the parts are worth looking at.
_FRAME_FILL = 0.9


def _has_viewport(ren: vtk.vtkRenderer) -> bool:
    """Whether ``ren`` is in a window that has been given a size."""
    window = ren.GetRenderWindow()
    if window is None:
        return False
    width, height = window.GetSize()
    return bool(width > 1 and height > 1)


# ---------------------------------------------------------------------------
# The room, generated rather than shipped
# ---------------------------------------------------------------------------
#
# A PBR MATERIAL WITH NOTHING TO REFLECT IS A FLAT COLOUR. That is the half of the change
# that is easy to leave out: metallic/roughness describe how a surface answers its
# surroundings, and a scene lit only by two lamps has no surroundings -- so a tinned can
# comes back darker than it was under Phong rather than looking like metal. Image-based
# lighting gives every surface a whole environment to answer, and it is what puts the long
# soft highlight down a capacitor and the sheen across a solder-masked board.
#
# THE ENVIRONMENT IS BUILT, NOT DOWNLOADED, which is PLAN.md D6 applied to lighting rather
# than to geometry: no asset, no licence to inherit, nothing to ship and nothing to go
# missing from a frozen build. What it describes is the only room this view is ever set
# in -- somebody at a bench with a lamp over it -- so six small faces of gradient plus one
# bright rectangle overhead say all of it. The rectangle is the part that matters: a
# cylinder under a POINT light has a round dot on it and a cylinder under a softbox has a
# long streak, and the streak is what the eye reads as "photograph".
#
# Values run past 1.0 on purpose. The lamp has to be brighter than the room or there is
# nothing for a smooth surface to pick out, which is what an HDR environment is for, so
# the faces are float and not bytes.

#: Face size. IBL blurs this heavily to build its roughness mip chain, so detail here is
#: wasted; what matters is that the gradient is smooth and the lamp has soft edges.
_ENV_FACE_PX = 64

#: The room, in the texture's own frame: +Y is up, and ``SetEnvironmentUp`` below tells the
#: renderer that our world's up is +Z instead.
_ENV_SKY = (1.05, 1.10, 1.22)
_ENV_HORIZON = (0.60, 0.62, 0.68)
_ENV_FLOOR = (0.16, 0.16, 0.18)
#: The bench lamp. Wide and shallow, like a real softbox, so a can gets a streak.
_ENV_LAMP = 8.0
_ENV_LAMP_WIDE = 0.85
_ENV_LAMP_DEEP = 0.30

#: How finely VTK works out the DIFFUSE light from the room, which it does on the GPU before
#: a renderer's first frame. Its defaults -- 256 px a face, a sample every 0.05 rad, some
#: four thousand samples a pixel -- are sized for a photographed HDR environment, and this
#: room is 64 px of smooth gradient with one soft lamp in it. Diffuse light is the most
#: blurred thing in the scene; nothing it produces changes at a finer scale than this.
#:
#: MEASURED, AND IT WAS THE WHOLE OF THE SLOWDOWN ON A MACHINE WITHOUT A GPU. On llvmpipe the
#: first frame of ``dense.perf`` took 12.7 s at VTK's defaults and 0.5 s with no environment
#: at all; with these two it takes 1.4 s, and the guide's 33 step images 8.2 s instead of
#: 41.6. The macOS CI runner has no GPU either, and the same step images took it 820 s.
#: Rendered on a real GPU at 1400 x 950, the two settings differ from the defaults by at
#: most 3 levels in 255 on any pixel -- the same picture. The contact-shadow pass was
#: measured too and is not the cost.
_IRRADIANCE_PX = 32
_IRRADIANCE_STEP_RAD = 0.1

#: The other table VTK fills before the first frame: how a rough surface spreads light,
#: indexed by angle and roughness. It describes no room at all, only the shading model,
#: and 512 x 512 at 1024 samples a texel was most of what the irradiance change above left
#: behind. It is pure arithmetic, which llvmpipe vectorises and Apple's software renderer
#: does not: 2.6 s to 1.2 s for the first frame on single-threaded llvmpipe, but 102 s to
#: 24 s on the macOS CI runner. The table is a smooth function read with linear filtering,
#: and at 128 the rendered board is within 1 level in 255 of the one at 512 on every pixel.
_BRDF_TABLE_PX = 128


def _env_colour(x: float, y: float, z: float) -> tuple[float, float, float]:
    """What the room looks like in one direction. ``y`` is up in the texture's own frame."""
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / length, y / length, z / length
    if y >= 0.0:
        # Smoothstep from the horizon to the sky, so the gradient has no visible band in it.
        t = y * y * (3.0 - 2.0 * y)
        base = [h + (s - h) * t for h, s in zip(_ENV_HORIZON, _ENV_SKY, strict=True)]
    else:
        t = (-y) ** 0.6
        base = [h + (f - h) * t for h, f in zip(_ENV_HORIZON, _ENV_FLOOR, strict=True)]
    if y > 0.25:
        # An elliptical patch overhead, falling off smoothly rather than cut out: a hard
        # edge on a light source shows up as a hard edge in every reflection of it.
        d = math.sqrt((x / _ENV_LAMP_WIDE) ** 2 + (z / _ENV_LAMP_DEEP) ** 2)
        if d < 1.0:
            glow = (1.0 - d) ** 2 * _ENV_LAMP * min(1.0, (y - 0.25) / 0.35)
            base = [channel + glow for channel in base]
    return (base[0], base[1], base[2])


#: OpenGL's cube-map convention: +X, -X, +Y, -Y, +Z, -Z, and each face's own axes.
_ENV_FACES = (
    ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, -1.0, 0.0)),
    ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
    ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),
    ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    ((0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
)

_environment: vtk.vtkTexture | None = None


def environment_texture() -> vtk.vtkTexture:
    """The cube map above, built once and shared by every renderer in the process.

    Built once because it is the same room every time and filling six faces in Python is
    the one part of a rebuild that would be worth noticing -- a refresh happens on every
    edit, and this does not change between them.
    """
    global _environment
    if _environment is not None:
        return _environment
    texture = vtk.vtkTexture()
    texture.CubeMapOn()
    texture.InterpolateOn()
    texture.MipmapOn()
    # THE ONE CALL WITHOUT WHICH THIS IS A RAINBOW. A vtkTexture's default colour mode maps
    # scalars through a lookup table, and VTK's default table is the jet colormap -- so the
    # room came back as a spectrum and every metal part on the board reflected it. Direct
    # scalars says "these ARE the colours", which is the only reading a float environment
    # map has.
    texture.SetColorModeToDirectScalars()
    half = (_ENV_FACE_PX - 1) / 2.0
    for index, (forward, right, up) in enumerate(_ENV_FACES):
        image = vtk.vtkImageData()
        image.SetDimensions(_ENV_FACE_PX, _ENV_FACE_PX, 1)
        image.AllocateScalars(vtk.VTK_FLOAT, 3)
        for row in range(_ENV_FACE_PX):
            v = (row - half) / half
            for col in range(_ENV_FACE_PX):
                u = (col - half) / half
                rgb = _env_colour(
                    forward[0] + right[0] * u + up[0] * v,
                    forward[1] + right[1] * u + up[1] * v,
                    forward[2] + right[2] * u + up[2] * v,
                )
                for channel in range(3):
                    image.SetScalarComponentFromFloat(col, row, 0, channel, rgb[channel])
        texture.SetInputDataObject(index, image)
    _environment = texture
    return texture


def build_renderer(
    doc: PerfDocument,
    lookup: FootprintLookup,
    flipped: bool = False,
    *,
    exploded_mm: float = 0.0,
    highlight: str | None = None,
    pin_names: bool = True,
    board_notes: bool = True,
) -> tuple[vtk.vtkRenderer, dict[str, int]]:
    """A renderer with the board in it, framed and lit. For a first build or a one-off
    offscreen render; an interactive view refreshes with :func:`populate_renderer`."""
    ren = vtk.vtkRenderer()
    ren.SetBackground(0.09, 0.09, 0.11)
    stats = populate_renderer(
        ren,
        doc,
        lookup,
        exploded_mm=exploded_mm,
        highlight=highlight,
        pin_names=pin_names,
        board_notes=board_notes,
    )
    apply_default_camera(ren, flipped)

    apply_default_lighting(ren)
    apply_environment(ren)
    apply_contact_shadows(ren)
    return ren, stats


#: The environment variable that turns the two GPU-heavy parts of this view off.
#:
#: IMAGE-BASED LIGHTING AND THE AMBIENT-OCCLUSION PASS ARE THE ONLY THINGS HERE THAT ASK
#: THE DRIVER FOR ANYTHING UNUSUAL -- a float cube map with a prefiltered mip chain, and a
#: second render pass with its own framebuffers. Everything else in this module is
#: triangles and a colour. VTK does not raise when a driver cannot do something: it ends
#: the process (see ``offscreen_gl_available``, which exists for exactly that), so the one
#: honest thing to offer somebody whose machine goes down is a way to run without them.
#:
#: What is lost is the room and the contact shadows. What is kept is every material, every
#: borrowed package and both lamps, which is still a great deal more than the flat shading
#: this replaced.
#:
#:     PERFBOARD_STUDIO_SIMPLE_3D=1 perfboard-studio
SIMPLE_3D_ENV = "PERFBOARD_STUDIO_SIMPLE_3D"


def rich_shading_wanted() -> bool:
    """Whether to ask the driver for image-based lighting and contact shadows.

    Read from the environment on every call rather than cached, so a person can answer the
    question "is it this?" by setting a variable and starting the application again, which
    is the only tool somebody has for a crash that happens before anything is logged.
    """
    return os.environ.get(SIMPLE_3D_ENV, "").strip() not in ("1", "true", "yes", "on")


def apply_environment(ren: vtk.vtkRenderer) -> None:
    """Give the materials a room to reflect.

    Without this the PBR shading above is a downgrade rather than an upgrade: metallic and
    roughness describe how a surface answers its SURROUNDINGS, and two lamps in the void
    are not surroundings -- a tinned can under them comes back darker than it was under
    Phong, because a mirror pointed at nothing is black.

    ``SetEnvironmentUp`` is the call it is easy to leave out and hard to see the absence
    of: VTK's default frame is Y-up and this application's world is Z-up, so without it the
    bench lamp sits somewhere off to the side of the board and every part is lit from the
    wrong place -- consistently, which is what makes it look merely odd rather than broken.
    """
    if not rich_shading_wanted():
        return
    ren.SetEnvironmentTexture(environment_texture())
    ren.SetEnvironmentUp(0.0, 0.0, 1.0)
    ren.SetEnvironmentRight(1.0, 0.0, 0.0)
    ren.UseImageBasedLightingOn()
    # Sized for this room rather than for a photograph -- see _IRRADIANCE_PX.
    irradiance = ren.GetEnvMapIrradiance()
    irradiance.SetIrradianceSize(_IRRADIANCE_PX)
    irradiance.SetIrradianceStep(_IRRADIANCE_STEP_RAD)
    ren.GetEnvMapLookupTable().SetLUTSize(_BRDF_TABLE_PX)
    # VTK cannot project a FLOAT cube map onto spherical harmonics and says so, once per
    # render, on stderr. It falls back to the irradiance texture, which is what this wants
    # anyway -- so ask for that rather than let it warn its way there. The environment has
    # to be float: the bench lamp is brighter than white, and that is the whole point of it.
    ren.UseSphericalHarmonicsOff()


def apply_contact_shadows(ren: vtk.vtkRenderer) -> bool:
    """Darken the creases where one solid meets another. Says whether it took.

    THE THING THAT MAKES A PART SIT ON THE BOARD. Every solid here is lit as though nothing
    else were in the scene, so a DIP and the board under it were two objects at the same
    brightness meeting at a line -- which reads as a sticker, however good the material is.
    Screen-space ambient occlusion costs one pass and puts a soft shadow in every corner:
    under each part, inside each bore, along each solder fillet.

    The radius is in WORLD units, so it is millimetres here, and it is the whole setting:
    much under a pitch and the shadow hugs the outline too tightly to read, much over and
    a dense board turns into a grey wash. One hole's width is what a part actually casts
    onto a bench.

    Returns False rather than raising if the driver cannot do it: this is the one piece of
    the render that is a luxury, and a machine whose OpenGL is too old for it should get a
    board that looks slightly flatter rather than no board at all.

    THE SAME PASS CHAIN ENDS IN TONE MAPPING, because the room is brighter than a screen on
    purpose (``_ENV_SKY`` runs past 1.0 so that a smooth surface has a lamp to pick out)
    and nothing brought it back into range: a crystal can or a TO-220's tab seen from the
    side clipped to a flat white slab -- 17 861 pixels of it in a 480 x 360 close-up of an
    HC-49. An exponential curve at ``TONE_EXPOSURE`` takes that to none while moving the
    whole board's mean colour by under two levels in 255; Reinhard and the filmic curves
    were tried and darken the midtones -- the colours ``bodies.BODY_STYLES`` shares with
    the 2D view -- by 6 to 10 per cent. It rides with the occlusion because it is the same
    kind of luxury, a pass with its own framebuffer, and ``PERFBOARD_STUDIO_SIMPLE_3D``
    turns both off together.
    """
    if not rich_shading_wanted():
        return False
    try:
        occlusion = vtk.vtkSSAOPass()
        occlusion.SetDelegatePass(vtk.vtkRenderStepsPass())
        occlusion.SetRadius(CONTACT_SHADOW_MM)
        occlusion.SetBias(CONTACT_SHADOW_BIAS_MM)
        occlusion.SetKernelSize(CONTACT_SHADOW_SAMPLES)
        occlusion.BlurOn()
        tone = vtk.vtkToneMappingPass()
        tone.SetToneMappingType(vtk.vtkToneMappingPass.Exponential)
        tone.SetExposure(TONE_EXPOSURE)
        tone.SetDelegatePass(occlusion)
        ren.SetPass(tone)
    except (AttributeError, TypeError):  # pragma: no cover - driver-dependent
        return False
    return True


#: The exposure of the exponential tone curve -- see ``apply_contact_shadows``. Chosen so the
#: board's mean colour lands where it was without tone mapping (atmega328-relay: 64/76/70
#: before, 65/77/72 after), so what changes is the highlights and nothing else.
TONE_EXPOSURE = 1.15


def apply_default_lighting(ren: vtk.vtkRenderer) -> None:
    """Two lights, and they travel WITH THE CAMERA.

    They used to be nailed to world positions, one above the board and one below. That
    was already the second attempt -- with only the upper one, flipping to the solder side
    showed an almost black board -- and it was still wrong in the same way, just less
    obviously: the lower light was the deliberately dimmer FILL, so the face you turn the
    board over to inspect was the one lit by the weaker lamp, at a fixed angle that no
    longer had anything to do with where you were looking from. Solder came out a flat
    dark grey with no highlight on it, which is why a run of it read as grey plumbing
    rather than as metal, and why turning the board could take a conductor into shadow for
    no reason a viewer could see.

    A camera light is positioned relative to the viewpoint, so whichever face is towards
    you is the lit one, at a constant angle, however the board is turned -- which is also
    what somebody bent over a board with a lamp on the bench actually has. The key is
    offset up and to the left rather than dead-on: a headlight flattens everything it
    lights, and the shape of a solder fillet is the thing this view is for.
    """
    for existing in list(ren.GetLights()):
        ren.RemoveLight(existing)

    key = vtk.vtkLight()
    key.SetLightTypeToCameraLight()
    key.SetPosition(-0.45, 0.55, 1.0)  # relative to the camera, in its own frame
    key.SetFocalPoint(0.0, 0.0, 0.0)
    # Dimmer than they were, and deliberately: with ``apply_environment`` there is now a
    # whole room doing the general lighting, and lamps left at their old strength on top of
    # it blow out every light-coloured part. What these two are still for is DIRECTION --
    # the shape of a solder fillet, which an environment lights evenly and therefore
    # flattens.
    key.SetIntensity(0.78)
    ren.AddLight(key)

    fill = vtk.vtkLight()
    fill.SetLightTypeToCameraLight()
    fill.SetPosition(0.6, -0.4, 0.7)
    fill.SetFocalPoint(0.0, 0.0, 0.0)
    fill.SetIntensity(0.32)
    ren.AddLight(fill)


def trackball_style() -> vtk.vtkInteractorStyleTrackballCamera:
    """Drag-to-orbit, and stop when the pointer stops.

    Set explicitly because VTK's default is ``vtkInteractorStyleSwitch``, which can start in
    joystick mode: there, holding the button keeps the camera turning at a speed set by how
    far the pointer is from centre, so a small drag sends the board spinning. That reads as a
    broken control rather than a different one, and it is not something a user would think
    to go looking for a setting to change.
    """
    return vtk.vtkInteractorStyleTrackballCamera()


# ---------------------------------------------------------------------------
# Is there anything to render into
# ---------------------------------------------------------------------------

#: The argv flag that turns a run of this application into the probe below. It is not a
#: user-facing option and is not documented as one: it exists because a frozen build has
#: no separate Python to spawn, so the only interpreter available to ask the question in
#: a *different process* is this application itself.
PROBE_FLAG = "--probe-offscreen-gl"


def probe_offscreen_gl() -> int:
    """Open an offscreen window, render one frame, and report by exit status.

    Called in the child process; ``main`` routes ``PROBE_FLAG`` here before it touches
    Qt. The parent never calls this directly, because the failure it is looking for
    cannot be caught in the process it happens in.
    """
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetSize(16, 16)
    win.AddRenderer(vtk.vtkRenderer())
    win.Render()
    return 0


@functools.cache
def offscreen_gl_available() -> bool:
    """Whether this machine can render offscreen at all -- asked in a child process.

    VTK DOES NOT RAISE WHEN THERE IS NO USABLE OpenGL BEHIND AN OFFSCREEN WINDOW. It
    ends the process: on Windows an access violation, elsewhere an abort. So the
    ``except Exception`` around every render in this application, and the promise it
    encodes -- that a guide with no pictures is still a complete guide -- is unreachable
    in exactly the case it was written for. A virtual machine, a remote desktop session
    or an old driver does not raise; it takes the whole application down mid-export.

    The only way to catch that is to spend the crash somewhere it costs nothing, which
    means another process, which is what this is. One spawn per run, cached: the answer
    cannot change while the application is open.

    Timeouts and OSErrors answer False. A machine slow enough to take three minutes over
    a 16x16 frame is not one to render 29 step images on either.
    """
    if getattr(sys, "frozen", False):
        # A frozen build IS the interpreter, so it probes by running itself. sys.argv[0]
        # is not usable here -- it is the launcher script under some spawn methods.
        command = [sys.executable, PROBE_FLAG]
    else:
        command = [sys.executable, "-m", "perfboard_studio.ui.main", PROBE_FLAG]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - machine-specific
        return False
    return completed.returncode == 0


def render_offscreen(
    doc: PerfDocument,
    lookup: FootprintLookup,
    path: str,
    width: int = 1400,
    height: int = 950,
    flipped: bool = False,
    *,
    exploded_mm: float = 0.0,
    highlight: str | None = None,
) -> dict[str, int]:
    """Headless render. This is the path the build guide's step images take.

    Pair it with ``guide.document_at_step`` and ``guide.step_focus`` and one call is one
    step card's illustration: the board as it stands at that point in the build, with the
    thing that step asks for picked out of it.
    """
    ren, stats = build_renderer(
        doc, lookup, flipped=flipped, exploded_mm=exploded_mm, highlight=highlight
    )
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(ren)
    win.SetSize(width, height)
    # Framed again now that the window has a shape to frame it in -- see apply_default_camera.
    apply_default_camera(ren, flipped)
    win.Render()

    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(win)
    w2i.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(path)
    writer.SetInputConnection(w2i.GetOutputPort())
    writer.Write()
    return stats


def step_is_solder_side(doc: PerfDocument, focus: str) -> bool:
    """Which face a step's work happens on, given what it is about.

    A part goes in from the component side. A connection is made on whichever face its
    conductor lies on, which for everything except a top jumper is the solder side --
    so this is the difference between illustrating a step and photographing the back of
    the board it is behind.
    """
    for conductor in doc.conductors:
        if conductor.id == focus:
            return conductor.side == "bottom"
    return False


#: JPEG quality for the step images, measured on ``dense.perf`` at 560x370 (33 steps):
#:
#:     PNG        135.6 KB/image   guide.html 6378 KB
#:     JPEG q90    61.8 KB/image
#:     JPEG q82    47.0 KB/image   guide.html 2070 KB
#:     JPEG q70    35.6 KB/image
#:
#: The guide is one self-contained file meant to open on a phone, so its size is a
#: feature and not a detail -- and these are photographs of a lit 3D scene, the exact
#: content PNG is worst at. q82 keeps the pin-1 marks and the highlight colour clean;
#: below about q70 the JPEG rings around the thin leader lines in the exploded shots.
#: JPEG rather than WebP because this has to survive PyInstaller: vtkJPEGWriter is
#: linked into VTK, while Qt's WebP writer is an image-format plugin that has to be
#: collected into the bundle, and a missing plugin fails at the user's machine.
STEP_IMAGE_JPEG_QUALITY = 82


#: The least board a step picture shows round its subject, in millimetres along each side:
#: about a dozen holes at 2.54 mm, enough to count from a neighbour -- or from the legend
#: printed along the edge -- to the hole the card names. A part on its own fills the frame
#: and says nothing about WHERE it goes.
STEP_CONTEXT_MM = 30.0

#: VTK's bounds: ``(xmin, xmax, ymin, ymax, zmin, zmax)``.
type Bounds = tuple[float, float, float, float, float, float]


def step_frame_bounds(subject: Bounds, context_mm: float = STEP_CONTEXT_MM) -> Bounds:
    """The box a step picture is framed on: its subject, widened about its own centre to at
    least ``context_mm`` along each side of the board. Height is the subject's own, so a
    tall part is not cut off at the top.

    CENTRED EVEN AT AN EDGE, where part of the picture is then past the board. That strip
    is where the edge IS, and the edge is the other landmark counting starts from. Sliding
    the picture back over the board was tried -- each corner's ray cast to the board's
    plane and the camera moved until all four landed on board -- and it pushed a screw
    terminal standing on the top edge out of its own picture: a tall part's body projects
    past the patch of board under it, which is exactly the part such a slide cannot see.
    """
    framed = list(subject)
    for axis in (0, 1):
        lo, hi = subject[2 * axis], subject[2 * axis + 1]
        centre, half = (lo + hi) / 2, max(hi - lo, context_mm) / 2
        framed[2 * axis], framed[2 * axis + 1] = centre - half, centre + half
    return (framed[0], framed[1], framed[2], framed[3], framed[4], framed[5])


def frame_step(
    ren: vtk.vtkRenderer, whole_board: vtk.vtkCamera, subject: list[vtk.vtkActor]
) -> None:
    """Point the camera at one step: from ``whole_board``'s direction, close on ``subject``.

    The DIRECTION is the face's, worked out once on the finished board, so every step on a
    face is seen from the same place; only the distance and the aim change. Nothing to
    frame on, or a subject that would need the camera further off than the whole board,
    gets the whole board -- the camera never backs out past it.
    """
    camera = ren.GetActiveCamera()
    camera.DeepCopy(whole_board)
    boxes = [actor.GetBounds() for actor in subject]
    boxes = [box for box in boxes if box[0] <= box[1]]
    if boxes:
        union: Bounds = (
            min(box[0] for box in boxes),
            max(box[1] for box in boxes),
            min(box[2] for box in boxes),
            max(box[3] for box in boxes),
            min(box[4] for box in boxes),
            max(box[5] for box in boxes),
        )
        ren.ResetCameraScreenSpace(*step_frame_bounds(union), _FRAME_FILL)
        if camera.GetDistance() >= whole_board.GetDistance():
            camera.DeepCopy(whole_board)
    ren.ResetCameraClippingRange()


def render_step_images(
    doc: PerfDocument,
    guide: Guide,
    lookup: FootprintLookup,
    width: int = 560,
    height: int = 370,
    progress: Callable[[int, int], bool] | None = None,
) -> dict[str, bytes]:
    """One picture per build step (PLAN.md §7.2), keyed by ``guide.step_focus``.

    JPEG bytes rather than files, because that is what ``guide_export.guide_to_html``
    takes: it base64s them into the document, so the finished guide cannot acquire a
    dependency on a folder beside it. Base64 costs a third on top, which is the other
    reason the format matters here (see ``STEP_IMAGE_JPEG_QUALITY``).

    FROM THE SIDE THE WORK IS DONE ON. Most connections are made on the solder side, and
    photographed from the component side they are behind 1.6 mm of board -- the first
    version of this produced fourteen pictures of a board with nothing happening in them.
    So there are two cameras, and a step is shot from whichever face its subject is on,
    which is also the face the builder is looking at when they do it.

    CLOSE ON THE SUBJECT, FROM ONE DIRECTION PER FACE (:func:`frame_step`). The camera
    used to be framed on the finished board and left alone, so that flipping through the
    guide would read as one board being built rather than unrelated photographs -- and on
    a 9 x 15 cm board a resistor was then a few pixels of highlight, a picture that said
    nothing a builder could act on. The direction is still the face's, worked out once on
    the finished board, which is what kept the pages reading as one board; only the
    distance and the aim follow the step, with at least ``STEP_CONTEXT_MM`` round it
    (:func:`step_frame_bounds`).

    ONE render window, re-actored per step -- which is what ``populate_renderer`` exists
    for, and is the difference between half a second and a minute -- with the two face
    cameras worked out on the finished board up front and each step aimed from one of
    them. It used to be a window
    per face, and each window is a renderer that works out the room's lighting again
    before its first frame (see ``_IRRADIANCE_PX``), and again after the other one has
    drawn. That is cheap on a GPU and was most of the cost without one: ``dense.perf``'s 33
    steps took the macOS CI runner 181 s that way and take it 85 s this way. The drift was
    a bug as well as a cost -- a component-side step after the first flip came out up to 23
    levels in 255 away from the same step drawn on its own.

    ``progress`` is told ``(done, total)`` after every picture, and returning False stops:
    the set then comes back EMPTY rather than as some of the pictures, because a guide
    illustrated up to step 30 of 83 reads as a guide whose last steps went wrong.
    It is how the window keeps somebody informed through the minute a big board takes --
    the render stays on the thread that owns the GL context, which is the only one it can
    run on, and the caller pumps its events from here.
    """
    steps = all_steps(guide)
    if not steps:
        return {}

    ren, _stats = build_renderer(doc, lookup)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(ren)
    win.SetSize(width, height)
    # The window first: the cameras are fitted to its shape (see apply_default_camera).
    cameras: dict[bool, vtk.vtkCamera] = {}
    for flipped in (False, True):
        apply_default_camera(ren, flipped)
        camera = vtk.vtkCamera()
        camera.DeepCopy(ren.GetActiveCamera())
        cameras[flipped] = camera

    images: dict[str, bytes] = {}
    for index, step in enumerate(steps):
        focus = step_focus(step)
        subject: list[vtk.vtkActor] = []
        populate_renderer(
            ren,
            document_at_step(doc, guide, index),
            lookup,
            highlight=focus,
            subject_actors=subject,
        )
        frame_step(ren, cameras[step_is_solder_side(doc, focus)], subject)
        win.Render()
        grab = vtk.vtkWindowToImageFilter()
        grab.SetInput(win)
        grab.Update()
        writer = vtk.vtkJPEGWriter()
        writer.SetQuality(STEP_IMAGE_JPEG_QUALITY)
        writer.WriteToMemoryOn()
        writer.SetInputConnection(grab.GetOutputPort())
        writer.Write()
        jpeg = numpy_support.vtk_to_numpy(writer.GetResult())  # type: ignore[no-untyped-call]
        images[focus] = bytes(jpeg.tobytes())
        if progress is not None and not progress(index + 1, len(steps)):
            return {}
    return images
