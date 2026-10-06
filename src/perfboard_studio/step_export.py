"""The finished board as a STEP file, for the CAD program its enclosure is drawn in.

**WHY STEP, AND WHY WRITTEN HERE.** The 3D view draws meshes, and a mesh imports into a
mechanical CAD program as thousands of triangles nobody can measure, cut a box round or
snap a screw boss to. STEP carries SOLIDS: a face is a plane, a hole is a cylinder with a
radius, and a mouse can pick either. That is the format an enclosure is designed against,
and it is what KiCad hands a mechanical engineer. VTK writes meshes and cannot write STEP,
and OpenCASCADE would be a hundred megabytes of dependency for a file that is, underneath,
a few kinds of text entity -- so this module writes ISO 10303-21 itself, under AP214
(``AUTOMOTIVE_DESIGN``), the protocol every mechanical CAD program reads, from three shapes:
a box, a cylinder and a plate with holes through it.

**WHAT IS IN IT.**

* **The board**, at ``board_outline_mm`` -- the substrate, border included -- with every
  drilled hole and every mounting bore cut through it as a real cylindrical face. A finger
  has no bore (``undrilled_holes``) and gets none here either.
* **Every part on the board, as the body DRC measures**: ``drc.placed_body_box`` for the
  outline and ``Footprint.body_height`` for the height, a vertical cylinder where the
  courtyard is round, a barrel lying along its leads for an axial part, a box otherwise.
  That is deliberately the ENVELOPE and not the shape: what an enclosure needs is the room
  each part takes, and these are the very numbers ``component-overhangs-edge`` and
  ``component-too-tall`` judged. A STEP that disagreed with them would let a lid be drawn
  round a board the checker had just called too tall for it.
* **Every lead**, down through its hole and ``LEAD_TRIM_MM`` past the solder side, because
  that is how far the board has to stand off whatever it is screwed to.

**WHAT IS NOT, AND WHY.** Copper and solder are tens of microns on a board nobody is going
to machine, and a pad as a solid is four faces times every hole on the board for nothing
an enclosure can use. The wiring lies flat on the board under the parts it joins. KiCad
leaves copper out of its STEP by default for the same reason. The 3D view and its mesh
export are where the board is LOOKED at.

**THE FRAME.** Millimetres, z up, the solder side on z = 0 and the board's corner at the
origin, so the whole board lies in the positive quadrant and its dimensions read straight
off the coordinates -- the frame a CAD program wants to place a board in. Seen from +z it
is the component side, A1 at the top left, exactly as the editor shows it.

**ONE PRODUCT PER PART.** The file is an assembly: the board and every part are products of
their own under one root, named by reference, so the CAD program's tree reads "Board, R1,
U1..." and a part can be hidden or measured by name. Every solid is written in the
assembly's own coordinates, so each placement is the identity -- there is nothing to get
wrong about a transform that does not move anything.

Pure, like every engine module: no clock and no filesystem. The time stamp the header
needs is passed in by the host, and the result is a string.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from .connectivity import FootprintLookup
from .drc import placed_body_box
from .footprints import LEAD_RADIUS_MM, LEAD_TRIM_MM, MIN_BODY_MM, body_extent
from .geometry import (
    all_pin_holes,
    board_outline_mm,
    hole_key,
    hole_to_mm,
    mounting_hole_centre_mm,
    undrilled_holes,
)
from .model import BodyArchetype, ComponentInstance, Footprint, HoleCoord, PerfDocument
from .version import __version__

type Vec = tuple[float, float, float]
type Rgb = tuple[float, float, float]

#: The archetypes whose courtyard is a circle (``footprints._circle_outline``), and so whose
#: envelope is a cylinder standing on the board. A box round a 10 mm can claims the four
#: corners of the box, which is exactly the room a part beside it needs.
ROUND_ARCHETYPES: frozenset[BodyArchetype] = frozenset(
    {"radial-electrolytic", "led-round", "potentiometer"}
)

#: The thinnest wall of board this file will leave between two holes, or between a hole and
#: the edge. Closer than that the two would share a wall a few hundredths thick -- a sliver
#: no drill leaves and a CAD kernel rejects as a degenerate face -- so the first hole keeps
#: its place and the second is not drilled. Bores are cut first, which is what makes a grid
#: hole under an M3 bore the one that gives way: the bore took it.
MIN_WEB_MM = 0.1

#: How closely a reading program may merge two points, in millimetres. OpenCASCADE's own
#: default; every coordinate below is written to a nanometre, well inside it.
UNCERTAINTY_MM = 1e-7


# ---------------------------------------------------------------------------
# What the file describes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Box:
    """An axis-aligned box from ``low`` to ``high``."""

    low: Vec
    high: Vec


@dataclass(frozen=True, slots=True)
class Cylinder:
    """A solid cylinder from the centre of one end, ``base``, along the unit ``axis``."""

    base: Vec
    axis: Vec
    length: float
    radius: float


@dataclass(frozen=True, slots=True)
class Plate:
    """A box drilled straight through along z: the board."""

    low: Vec
    high: Vec
    #: ``(x, y, radius)`` of every hole, none touching another or the edge.
    holes: tuple[tuple[float, float, float], ...]


type Shape = Box | Cylinder | Plate


@dataclass(frozen=True, slots=True)
class Solid:
    shape: Shape
    #: sRGB fractions, which is what a STEP colour is read as.
    rgb: Rgb


@dataclass(frozen=True, slots=True)
class ModelPart:
    """One product of the assembly: the board, or one part standing on it."""

    name: str
    solids: tuple[Solid, ...]


@dataclass(frozen=True, slots=True)
class Palette:
    """What each solid is coloured. The engine has no opinion about colour, so the window
    passes the one its own views use (``ui/export_step``) and a bare call gets neutral
    ones; ``body`` is asked per footprint, which is where a resistor and a DIP differ."""

    board: Rgb = (0.20, 0.42, 0.25)
    lead: Rgb = (0.78, 0.80, 0.84)
    part: Rgb = (0.30, 0.31, 0.34)
    body: Callable[[Footprint], Rgb] | None = None

    def body_rgb(self, footprint: Footprint) -> Rgb:
        return self.part if self.body is None else self.body(footprint)


# ---------------------------------------------------------------------------
# The board as solids
# ---------------------------------------------------------------------------


def board_model(
    doc: PerfDocument, lookup: FootprintLookup, palette: Palette | None = None
) -> tuple[ModelPart, ...]:
    """The board and every part on it as solids, in the file's frame -- see the module
    docstring for what is included and what is left out."""
    palette = palette or Palette()
    board = doc.board
    outline = board_outline_mm(board)
    width, depth, top = outline.width, outline.height, board.thickness

    def place(x: float, y: float) -> tuple[float, float]:
        # The holes count rows DOWN; the file's y runs up, so row 0 is at the far edge.
        return x - outline.x, outline.y + outline.height - y

    holes: list[tuple[float, float, float]] = []

    def drill(x: float, y: float, radius: float) -> bool:
        clear = (
            x - radius >= MIN_WEB_MM
            and y - radius >= MIN_WEB_MM
            and x + radius <= width - MIN_WEB_MM
            and y + radius <= depth - MIN_WEB_MM
            and all(
                math.hypot(x - hx, y - hy) >= radius + hr + MIN_WEB_MM for hx, hy, hr in holes
            )
        )
        if clear:
            holes.append((x, y, radius))
        return clear

    for mount in doc.mounting_holes:
        centre = mounting_hole_centre_mm(mount, board)
        drill(*place(centre.x, centre.y), mount.diameter / 2)
    undrilled = undrilled_holes(doc)
    drilled: set[str] = set()
    for row in range(board.rows):
        for col in range(board.cols):
            coord = HoleCoord(col, row)
            if hole_key(coord) in undrilled:
                continue
            centre = hole_to_mm(coord, board)
            if drill(*place(centre.x, centre.y), board.drill_diameter / 2):
                drilled.add(hole_key(coord))

    parts = [
        ModelPart(
            "Board",
            (Solid(Plate((0.0, 0.0, 0.0), (width, depth, top), tuple(holes)), palette.board),),
        )
    ]
    lead_radius = min(LEAD_RADIUS_MM, board.drill_diameter / 2 * 0.8)
    for comp in doc.components:
        footprint = lookup(comp.footprint_id)
        if footprint is None:
            continue
        solids = _part_solids(
            comp, footprint, doc, place, top, drilled, lead_radius, palette
        )
        parts.append(ModelPart(comp.ref or comp.id, solids))
    return tuple(parts)


def _part_solids(
    comp: ComponentInstance,
    footprint: Footprint,
    doc: PerfDocument,
    place: Callable[[float, float], tuple[float, float]],
    top: float,
    drilled: set[str],
    lead_radius: float,
    palette: Palette,
) -> tuple[Solid, ...]:
    board = doc.board
    min_x, max_x, min_y, max_y = placed_body_box(comp, footprint, board)
    x0, y1 = place(min_x, min_y)
    x1, y0 = place(max_x, max_y)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    height = footprint.body_height if footprint.body_height > 0 else MIN_BODY_MM
    rgb = palette.body_rgb(footprint)
    archetype = footprint.body.archetype

    pins = [
        place(centre.x, centre.y)
        for _pin, hole in all_pin_holes(comp, footprint)
        if hole_key(hole) in drilled
        for centre in [hole_to_mm(hole, board)]
    ]
    solids: list[Solid] = []

    def lead(base: Vec, axis: Vec, length: float) -> None:
        if length > 1e-6:
            solids.append(Solid(Cylinder(base, axis, length, lead_radius), palette.lead))

    if archetype == "axial-cylinder":
        # Lying along its leads, its top at the height DRC measures -- or resting on the
        # board, for a registry entry whose height is less than its own diameter.
        along_x = (body_extent(footprint, board.pitch).axis == "x") != (
            comp.rotation in (90, 270)
        )
        length, radius = (x1 - x0, (y1 - y0) / 2) if along_x else (y1 - y0, (x1 - x0) / 2)
        cz = top + max(height - radius, radius)
        base: Vec = (x0, cy, cz) if along_x else (cx, y0, cz)
        axis: Vec = (1.0, 0.0, 0.0) if along_x else (0.0, 1.0, 0.0)
        solids.append(Solid(Cylinder(base, axis, length, radius), rgb))
        low, high = (x0, x1) if along_x else (y0, y1)
        for px, py in pins:
            # Out from the end of the barrel to above the hole, then down through it.
            at = px if along_x else py
            end = high if at > high else low
            if not low <= at <= high:
                start = min(at, end)
                lead((start, py, cz) if along_x else (px, start, cz), axis, abs(at - end))
            lead((px, py, -LEAD_TRIM_MM), (0.0, 0.0, 1.0), cz + LEAD_TRIM_MM)
        return tuple(solids)

    if archetype in ROUND_ARCHETYPES:
        radius = min(x1 - x0, y1 - y0) / 2
        solids.append(Solid(Cylinder((cx, cy, top), (0.0, 0.0, 1.0), height, radius), rgb))
    else:
        solids.append(Solid(Box((x0, y0, top), (x1, y1, top + height)), rgb))
    for px, py in pins:
        lead((px, py, -LEAD_TRIM_MM), (0.0, 0.0, 1.0), top + LEAD_TRIM_MM)
    return tuple(solids)


# ---------------------------------------------------------------------------
# ISO 10303-21
# ---------------------------------------------------------------------------


def step_string(text: str) -> str:
    """A STEP string literal: quotes doubled, and everything outside printable ASCII in
    ISO 10303-21's own escape, because a STEP file is ASCII and "Röle" written as UTF-8
    arrives in a CAD program as two characters of mojibake."""
    out: list[str] = []
    wide: list[str] = []

    def flush() -> None:
        if wide:
            out.append("\\X2\\" + "".join(wide) + "\\X0\\")
            wide.clear()

    for char in text:
        code = ord(char)
        if 0x20 <= code < 0x7F:
            flush()
            out.append({"'": "''", "\\": "\\\\"}.get(char, char))
        elif code <= 0xFFFF:
            wide.append(f"{code:04X}")
        else:
            flush()
            out.append(f"\\X4\\{code:08X}\\X0\\")
    flush()
    return "'" + "".join(out) + "'"


def _real(value: float) -> str:
    """A REAL as STEP wants it: always with a point, never ``-0.``, to a nanometre."""
    text = f"{value:.9f}".rstrip("0")
    return "0." if text in ("0.", "-0.") else text


def _exponent(value: float) -> str:
    """A small REAL in exponent form, which ``_real`` would round to nothing: ``1.E-07``."""
    mantissa, exponent = f"{value:.0E}".split("E")
    return f"{mantissa}.E{exponent}"


class _Writer:
    """Entities numbered in the order they are written, each one referenced by ``#n``."""

    def __init__(self) -> None:
        self.entities: list[str] = []
        self._points: dict[Vec, str] = {}
        self._directions: dict[Vec, str] = {}
        self._styles: dict[Rgb, str] = {}

    def add(self, entity: str) -> str:
        self.entities.append(entity)
        return f"#{len(self.entities)}"

    def point(self, p: Vec) -> str:
        key = (float(_real(p[0])), float(_real(p[1])), float(_real(p[2])))
        if key not in self._points:
            self._points[key] = self.add(
                f"CARTESIAN_POINT('',({_real(p[0])},{_real(p[1])},{_real(p[2])}))"
            )
        return self._points[key]

    def direction(self, d: Vec) -> str:
        if d not in self._directions:
            self._directions[d] = self.add(
                f"DIRECTION('',({_real(d[0])},{_real(d[1])},{_real(d[2])}))"
            )
        return self._directions[d]

    def placement(self, origin: Vec, axis: Vec, ref: Vec) -> str:
        return self.add(
            f"AXIS2_PLACEMENT_3D('',{self.point(origin)},{self.direction(axis)},"
            f"{self.direction(ref)})"
        )

    def vertex(self, p: Vec) -> str:
        return self.add(f"VERTEX_POINT('',{self.point(p)})")

    def line_edge(self, start: str, end: str, a: Vec, b: Vec) -> str:
        span = _sub(b, a)
        vector = self.add(f"VECTOR('',{self.direction(_unit(span))},{_real(_norm(span))})")
        line = self.add(f"LINE('',{self.point(a)},{vector})")
        return self.add(f"EDGE_CURVE('',{start},{end},{line},.T.)")

    def circle_edge(self, vertex: str, centre: Vec, axis: Vec, ref: Vec, radius: float) -> str:
        circle = self.add(f"CIRCLE('',{self.placement(centre, axis, ref)},{_real(radius)})")
        return self.add(f"EDGE_CURVE('',{vertex},{vertex},{circle},.T.)")

    def loop(self, edges: list[tuple[str, bool]], *, outer: bool = False) -> str:
        oriented = ",".join(
            self.add(f"ORIENTED_EDGE('',*,*,{edge},{'.T.' if forward else '.F.'})")
            for edge, forward in edges
        )
        loop = self.add(f"EDGE_LOOP('',({oriented}))")
        return self.add(f"{'FACE_OUTER_BOUND' if outer else 'FACE_BOUND'}('',{loop},.T.)")

    def face(self, bounds: list[str], surface: str, same_sense: bool = True) -> str:
        return self.add(
            f"ADVANCED_FACE('',({','.join(bounds)}),{surface},{'.T.' if same_sense else '.F.'})"
        )

    def style(self, rgb: Rgb) -> str:
        """The presentation style for one colour, written once however many solids use it."""
        if rgb not in self._styles:
            colour = self.add(f"COLOUR_RGB('',{_real(rgb[0])},{_real(rgb[1])},{_real(rgb[2])})")
            fill = self.add(f"FILL_AREA_STYLE_COLOUR('',{colour})")
            area = self.add(f"FILL_AREA_STYLE('',({fill}))")
            surface = self.add(f"SURFACE_STYLE_FILL_AREA({area})")
            side = self.add(f"SURFACE_SIDE_STYLE('',({surface}))")
            usage = self.add(f"SURFACE_STYLE_USAGE(.BOTH.,{side})")
            self._styles[rgb] = self.add(f"PRESENTATION_STYLE_ASSIGNMENT(({usage}))")
        return self._styles[rgb]


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _unit(a: Vec) -> Vec:
    length = _norm(a)
    return (a[0] / length, a[1] / length, a[2] / length)


def _along(origin: Vec, axis: Vec, distance: float) -> Vec:
    return (
        origin[0] + axis[0] * distance,
        origin[1] + axis[1] * distance,
        origin[2] + axis[2] * distance,
    )


def _perpendicular(axis: Vec) -> Vec:
    """A unit vector at right angles to ``axis``: x for anything upright, z otherwise."""
    return (1.0, 0.0, 0.0) if abs(axis[2]) > 0.9 else (0.0, 0.0, 1.0)


#: The six faces of a box, each listed anticlockwise seen from OUTSIDE, as indices into
#: its corners numbered ``x + 2y + 4z`` (0 low, 1 high). Anticlockwise about the outward
#: normal is the whole of a face's orientation in STEP: get one backwards and the solid
#: has a hole in it, or reads inside out.
_BOX_FACES = (
    (0, 2, 3, 1),  # z low, normal -z
    (4, 5, 7, 6),  # z high, normal +z
    (0, 1, 5, 4),  # y low, normal -y
    (2, 6, 7, 3),  # y high, normal +y
    (0, 4, 6, 2),  # x low, normal -x
    (1, 3, 7, 5),  # x high, normal +x
)


def _corners(low: Vec, high: Vec) -> list[Vec]:
    return [
        (high[0] if i & 1 else low[0], high[1] if i & 2 else low[1], high[2] if i & 4 else low[2])
        for i in range(8)
    ]


def _box_faces(
    w: _Writer, low: Vec, high: Vec, inner: dict[int, list[str]] | None = None
) -> list[str]:
    """The six planar faces of a box, with any extra bounds -- the holes through a plate --
    added to the faces ``inner`` names by their index in ``_BOX_FACES``."""
    corners = _corners(low, high)
    vertices = [w.vertex(c) for c in corners]
    edges: dict[tuple[int, int], str] = {}
    faces: list[str] = []
    for index, ring in enumerate(_BOX_FACES):
        used: list[tuple[str, bool]] = []
        for a, b in zip(ring, ring[1:] + ring[:1], strict=True):
            key = (min(a, b), max(a, b))
            if key not in edges:
                edges[key] = w.line_edge(
                    vertices[key[0]], vertices[key[1]], corners[key[0]], corners[key[1]]
                )
            used.append((edges[key], a < b))
        p0, p1, p2 = corners[ring[0]], corners[ring[1]], corners[ring[3]]
        normal = _unit(_cross(_sub(p1, p0), _sub(p2, p0)))
        plane = w.add(f"PLANE('',{w.placement(p0, normal, _unit(_sub(p1, p0)))})")
        bounds = [w.loop(used, outer=True), *(inner or {}).get(index, [])]
        faces.append(w.face(bounds, plane))
    return faces


def _cylinder_faces(w: _Writer, cyl: Cylinder) -> list[str]:
    """Two flat ends and the curved side, with the seam STEP readers expect on it.

    A closed periodic face needs a seam -- an edge the side is cut along, used twice, once
    each way -- or OpenCASCADE has to invent one on the way in. Both circles start where
    the seam meets them.
    """
    axis = cyl.axis
    ref = _perpendicular(axis)
    far = _along(cyl.base, axis, cyl.length)
    near_vertex = w.vertex(_along(cyl.base, ref, cyl.radius))
    far_vertex = w.vertex(_along(far, ref, cyl.radius))
    near = w.circle_edge(near_vertex, cyl.base, axis, ref, cyl.radius)
    far_edge = w.circle_edge(far_vertex, far, axis, ref, cyl.radius)
    seam = w.line_edge(
        near_vertex,
        far_vertex,
        _along(cyl.base, ref, cyl.radius),
        _along(far, ref, cyl.radius),
    )
    back = (-axis[0], -axis[1], -axis[2])
    near_cap = w.add(f"PLANE('',{w.placement(cyl.base, back, ref)})")
    far_cap = w.add(f"PLANE('',{w.placement(far, axis, ref)})")
    side = w.add(
        f"CYLINDRICAL_SURFACE('',{w.placement(cyl.base, axis, ref)},{_real(cyl.radius)})"
    )
    return [
        w.face([w.loop([(near, False)], outer=True)], near_cap),
        w.face([w.loop([(far_edge, True)], outer=True)], far_cap),
        w.face([w.loop([(near, True), (seam, True), (far_edge, False), (seam, False)])], side),
    ]


def _plate_faces(w: _Writer, plate: Plate) -> list[str]:
    """A box with holes: each hole is a loop in the top and bottom faces and a cylindrical
    wall between them, whose face points INTO the hole -- away from the material -- which
    is what ``same_sense`` false says about a surface whose own normal points out of it."""
    up, ref = (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)
    z0, z1 = plate.low[2], plate.high[2]
    tops: list[str] = []
    bottoms: list[str] = []
    walls: list[str] = []
    for x, y, radius in plate.holes:
        foot, head = (x, y, z0), (x, y, z1)
        low_vertex = w.vertex((x + radius, y, z0))
        high_vertex = w.vertex((x + radius, y, z1))
        low = w.circle_edge(low_vertex, foot, up, ref, radius)
        high = w.circle_edge(high_vertex, head, up, ref, radius)
        seam = w.line_edge(low_vertex, high_vertex, (x + radius, y, z0), (x + radius, y, z1))
        # A hole runs clockwise round the face it is cut in, seen from outside: the top
        # face is seen from +z and the bottom from -z, so the two run opposite ways.
        tops.append(w.loop([(high, False)]))
        bottoms.append(w.loop([(low, True)]))
        wall = w.add(f"CYLINDRICAL_SURFACE('',{w.placement(foot, up, ref)},{_real(radius)})")
        walls.append(
            w.face([w.loop([(high, True), (seam, False), (low, False), (seam, True)])], wall, False)
        )
    return _box_faces(w, plate.low, plate.high, {0: bottoms, 1: tops}) + walls


def _solid(w: _Writer, name: str, shape: Shape) -> str:
    if isinstance(shape, Box):
        faces = _box_faces(w, shape.low, shape.high)
    elif isinstance(shape, Cylinder):
        faces = _cylinder_faces(w, shape)
    else:
        faces = _plate_faces(w, shape)
    shell = w.add(f"CLOSED_SHELL('',({','.join(faces)}))")
    return w.add(f"MANIFOLD_SOLID_BREP({step_string(name)},{shell})")


def model_to_step(
    parts: tuple[ModelPart, ...],
    *,
    name: str,
    timestamp: str,
    file_name: str = "",
) -> str:
    """The assembly as ISO 10303-21 text, AP214, millimetres.

    ``timestamp`` is the header's ISO 8601 time stamp and is the host's to give: the engine
    has no clock, and a test passes a fixed one so the output is the same every run.
    """
    w = _Writer()
    app = w.add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    w.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{app})")
    product_context = w.add(f"PRODUCT_CONTEXT('',{app},'mechanical')")
    definition_context = w.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',{app},'design')")
    length = w.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    angle = w.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    solid_angle = w.add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    uncertainty = w.add(
        f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE({_exponent(UNCERTAINTY_MM)}),{length},"
        "'distance_accuracy_value','confusion accuracy')"
    )

    def context() -> str:
        # One per representation, as the protocol has every reader expect: a placement
        # relates two representations, and two that shared one context would be one space.
        return w.add(
            f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(("
            f"{uncertainty})) GLOBAL_UNIT_ASSIGNED_CONTEXT(({length},{angle},{solid_angle})) "
            "REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY') )"
        )

    def product(title: str) -> tuple[str, str]:
        """A product and its definition; returns the definition and its shape."""
        quoted = step_string(title)
        made = w.add(f"PRODUCT({quoted},{quoted},'',({product_context}))")
        w.add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,({made}))")
        formation = w.add(f"PRODUCT_DEFINITION_FORMATION('','',{made})")
        definition = w.add(f"PRODUCT_DEFINITION('design','',{formation},{definition_context})")
        return definition, w.add(f"PRODUCT_DEFINITION_SHAPE('','',{definition})")

    origin = ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    root_definition, root_shape = product(name)
    root_origin = w.placement(*origin)
    root_rep = w.add(f"SHAPE_REPRESENTATION({step_string(name)},({root_origin}),{context()})")
    w.add(f"SHAPE_DEFINITION_REPRESENTATION({root_shape},{root_rep})")

    for index, part in enumerate(parts, start=1):
        definition, shape = product(part.name)
        part_context = context()
        part_origin = w.placement(*origin)
        items: list[tuple[str, Rgb]] = [
            (_solid(w, part.name, solid.shape), solid.rgb) for solid in part.solids
        ]
        rep = w.add(
            f"ADVANCED_BREP_SHAPE_REPRESENTATION({step_string(part.name)},({part_origin},"
            f"{','.join(item for item, _ in items)}),{part_context})"
        )
        w.add(f"SHAPE_DEFINITION_REPRESENTATION({shape},{rep})")
        styled = ",".join(
            w.add(f"STYLED_ITEM('color',({w.style(rgb)}),{item})") for item, rgb in items
        )
        w.add(
            f"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',({styled}),"
            f"{part_context})"
        )
        # Placed where it was built: the identity, from the part's origin to the root's.
        usage = w.add(
            f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('{index}',{step_string(part.name)},'',"
            f"{root_definition},{definition},$)"
        )
        placed = w.add(f"PRODUCT_DEFINITION_SHAPE('Placement','Placement of an item',{usage})")
        transform = w.add(f"ITEM_DEFINED_TRANSFORMATION('','',{part_origin},{root_origin})")
        relation = w.add(
            f"( REPRESENTATION_RELATIONSHIP('','',{rep},{root_rep}) "
            f"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION({transform}) "
            "SHAPE_REPRESENTATION_RELATIONSHIP() )"
        )
        w.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION({relation},{placed})")

    system = step_string(f"Perfboard Studio {__version__}")
    header = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        f"FILE_DESCRIPTION(({step_string(name)}),'2;1');\n"
        f"FILE_NAME({step_string(file_name)},{step_string(timestamp)},(''),(''),"
        f"{system},{system},'');\n"
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\n"
        "ENDSEC;\n"
    )
    body = "".join(f"#{n}={entity};\n" for n, entity in enumerate(w.entities, start=1))
    return f"{header}DATA;\n{body}ENDSEC;\nEND-ISO-10303-21;\n"


def document_to_step(
    doc: PerfDocument,
    lookup: FootprintLookup,
    *,
    timestamp: str,
    palette: Palette | None = None,
    file_name: str = "",
) -> str:
    """The board as a STEP file: :func:`board_model` written by :func:`model_to_step`."""
    return model_to_step(
        board_model(doc, lookup, palette),
        name=doc.meta.name or "board",
        timestamp=timestamp,
        file_name=file_name,
    )


__all__ = [
    "MIN_WEB_MM",
    "ROUND_ARCHETYPES",
    "Box",
    "Cylinder",
    "ModelPart",
    "Palette",
    "Plate",
    "Solid",
    "board_model",
    "document_to_step",
    "model_to_step",
    "step_string",
]
