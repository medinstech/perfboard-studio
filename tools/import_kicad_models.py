"""Turn KiCad's STEP models of through-hole packages into meshes this application draws.

WHY THIS EXISTS. PLAN.md D6 chose parametric generation for the 3D bodies, and the reasons
were good ones: zero assets, a body that cannot disagree with its own footprint, and no
share-alike licence inherited into an Apache-2.0 project. Two of the three still hold. The
third did not survive contact with the result: a potentiometer generated from a diameter
and a height is a disc with a peg on it, and no amount of shading makes that a
potentiometer. KiCad's library has the real ones, drawn by people who had the part in
front of them.

WHAT IS AND IS NOT TAKEN. Only the part of the model ABOVE the board, and only its shape:

  * **Leads are cut off at the board surface** and this application draws its own below it,
    because it already knows the board's thickness, where the copper is and how far past it
    a trimmed lead stands (``_through_hole_pieces``). A model's leads are drawn for a 1.6 mm
    board with untrimmed legs and would hang nine millimetres out of the solder side.
  * **Materials are not taken.** A KiCad model carries a colour per face; this keeps the
    colour and assigns one of ``view3d``'s own materials, because "what is this made of" is
    a question this application answers in one table for the 2D view, the 3D view and the
    guide's step images together.
  * **Position is not taken, because it is already right.** A KiCad through-hole model's
    origin is pin 1 and its axes run the way this application's world does -- x with the
    column, y against the row. That is not luck: both follow the footprint, and this
    project's own convention is written down as "the anchor is pin 1, at grid offset
    (0, 0)".

RUN IT WITH KiCad INSTALLED. It needs ``cadquery-ocp`` for the STEP reader -- 7.9.x:
8.0 dropped ``TDF_LabelSequence`` from the bindings, and the colour walk below needs it --
and a KiCad installation to read from; neither is a dependency of the application, and neither is
needed to run it -- the meshes are written into the source tree and shipped. A footprint
with no entry in ``MODELS`` below keeps the generated body, which is still the fallback for
every part and the whole answer for a generated id.

    python tools/import_kicad_models.py            # find KiCad, write src/.../ui/models/
    python tools/import_kicad_models.py --kicad "C:/Program Files/KiCad/9.0"

THE LICENCE. KiCad's libraries are CC-BY-SA 4.0 with an exception for designs made with
them. The meshes written here are derived from that library, so they carry their own
LICENSE and NOTICE beside them and are the only part of this repository that is not
Apache-2.0. Nothing else in the tree is affected: they are data, read at run time.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "src" / "perfboard_studio" / "ui" / "models"

#: How finely a curve is broken into flat pieces, in millimetres, and how far a facet may
#: turn. A 5 mm LED dome at 0.04 mm is smooth at every zoom this view reaches, and the
#: whole library comes to about a megabyte -- the models are small because the parts are.
DEFLECTION = 0.04
ANGULAR = 0.3

#: Everything below this is cut away and drawn by the application instead. Slightly under
#: the board surface rather than exactly on it, so a lead and the body it belongs to
#: overlap rather than meeting at a seam the renderer has to decide about.
CUT_Z = -0.05


@dataclass(frozen=True)
class Model:
    """One of our footprints, and the KiCad model that is the same physical package."""

    footprint: str
    library: str
    step: str
    #: Turn about z, in degrees, applied before anything else. KiCad draws a few packages
    #: along the other axis from the way our footprint numbers its pins.
    rotate: float = 0.0
    #: Move, in millimetres, after the turn. For a package whose model origin is its centre
    #: rather than its first pin.
    offset: tuple[float, float] = (0.0, 0.0)
    #: Colours whose material this package disagrees with. KiCad paints an LED's lens and a
    #: film capacitor's case the same dark red, and they are not the same stuff.
    materials: tuple[tuple[str, str], ...] = ()
    #: Keep only ``x0 <= x < x1`` of the model, in its own frame and before ``offset`` moves
    #: it -- one WAY of a terminal block rather than the whole block. See ``clip_x``.
    clip: tuple[float, float] | None = None
    #: Bend the model's bare leads onto our holes, as whoever fits the part bends its legs
    #: to the grid. For a package made on a pitch the grid does not have. See ``splay_leads``.
    splay: bool = False


#: WHICH KiCad PACKAGE IS THE SAME PART. Chosen by PITCH first and outline second: a model
#: whose leads are 5 mm apart dropped onto a footprint whose holes are 2.54 mm apart is a
#: part standing on nothing, and it is the mistake that looks like a rendering bug.
#:
#: It was made anyway, four times, because nothing measured it: the TO-92 was KiCad's
#: 1.27 mm ``TO-92_Inline`` on a footprint whose legs are 2.54 mm apart (its middle leg
#: stood between two holes), the 3-hole disc capacitor stood 1.3 mm beside both its holes,
#: the tactile switch's legs missed by up to 2 mm and the relay's model had another pinout
#: altogether. ``tests/test_model_leads.py`` now measures every lead against the hole it
#: goes in. Where KiCad has the part with its legs already bent to the grid, that model is
#: used (``TO-92_Inline_Wide``); where it has only the part as made, the legs are bent here
#: (``splay``); and a part whose model has another pinout has no model. The relay is that
#: last case: ``relay-spdt`` is an on-grid approximation (coil pins in one column, NO/COM/NC
#: in another) that neither KiCad's Songle/Sanyou SRD nor its CUI SR5 is, so it keeps the
#: generated box, which is its own footprint's size.
MODELS: tuple[Model, ...] = (
    # -- ICs ---------------------------------------------------------------
    Model("dip-8", "Package_DIP", "DIP-8_W7.62mm"),
    Model("dip-14", "Package_DIP", "DIP-14_W7.62mm"),
    Model("dip-16", "Package_DIP", "DIP-16_W7.62mm"),
    Model("dip-18", "Package_DIP", "DIP-18_W7.62mm"),
    Model("dip-20", "Package_DIP", "DIP-20_W7.62mm"),
    Model("dip-28", "Package_DIP", "DIP-28_W7.62mm"),
    Model("dip-40-wide", "Package_DIP", "DIP-40_W15.24mm"),
    # -- discretes ---------------------------------------------------------
    Model("r-axial-3", "Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal"),
    Model("r-axial-4", "Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"),
    Model("r-axial-5", "Resistor_THT", "R_Axial_DIN0309_L9.0mm_D3.2mm_P12.70mm_Horizontal"),
    Model("r-axial-6", "Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P15.24mm_Horizontal"),
    Model("d-do35", "Diode_THT", "D_DO-35_SOD27_P7.62mm_Horizontal"),
    Model("d-do41", "Diode_THT", "D_DO-41_SOD81_P10.16mm_Horizontal"),
    # -- capacitors --------------------------------------------------------
    # A radial can is made with its leads 2.5 or 5 mm apart and goes in holes two or three
    # apart, so the legs are bent out under it -- as they are on the board.
    Model("c-elec-d5-p2", "Capacitor_THT", "CP_Radial_D5.0mm_P2.50mm", offset=(1.29, 0.0),
          splay=True),
    Model("c-elec-d6.3-p2", "Capacitor_THT", "CP_Radial_D6.3mm_P2.50mm", offset=(1.29, 0.0),
          splay=True),
    Model("c-elec-d8-p3", "Capacitor_THT", "CP_Radial_D8.0mm_P5.00mm", offset=(1.31, 0.0),
          splay=True),
    Model("c-elec-d10-p3", "Capacitor_THT", "CP_Radial_D10.0mm_P5.00mm", offset=(1.31, 0.0),
          splay=True),
    Model("c-disc-p2", "Capacitor_THT", "C_Disc_D5.0mm_W2.5mm_P5.00mm"),
    # KiCad's 7.5 mm disc on a 7.5 mm pitch is the 5 mm thick one; ours is 2.5 mm thick.
    Model("c-disc-p3", "Capacitor_THT", "C_Disc_D7.5mm_W2.5mm_P5.00mm", offset=(1.31, 0.0),
          splay=True),
    Model("c-film-p2", "Capacitor_THT", "C_Rect_L7.0mm_W2.5mm_P5.00mm"),
    Model("c-film-p3", "Capacitor_THT", "C_Rect_L10.0mm_W2.5mm_P7.50mm_MKS4"),
    # -- everything with its own shape ------------------------------------
    # The WIDE one: legs bent out to 2.54 mm, which is what our footprint is. The inline
    # model is the part as made, legs 1.27 mm apart.
    Model("to92", "Package_TO_SOT_THT", "TO-92_Inline_Wide"),
    Model("to220", "Package_TO_SOT_THT", "TO-220-3_Vertical"),
    Model("led-3mm", "LED_THT", "LED_D3.0mm", materials=(("#720301", "lens"),)),
    Model("led-5mm", "LED_THT", "LED_D5.0mm", materials=(("#720301", "lens"),)),
    Model("led-10mm", "LED_THT", "LED_D10.0mm", materials=(("#720301", "lens"),)),
    Model("xtal-hc49", "Crystal", "Crystal_HC49-U_Vertical",
          materials=(("#2a2a2a", "steel"),)),
    # Legs 6.5 x 4.5 mm on a 5.08 x 2.54 mm footprint: the case is centred on the four holes,
    # as the footprint's courtyard is, and the legs bent in to them.
    Model("sw-tactile", "Button_Switch_THT", "SW_PUSH_6mm", offset=(-0.61, 0.98), splay=True),
    Model("screw-terminal-2", "TerminalBlock_Phoenix",
          "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"),
    Model("screw-terminal-3", "TerminalBlock_Phoenix",
          "TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal"),
    # -- a terminal block of any length, as three ways of the 3-way one -----
    #
    # A MKDS-1,5 block IS a repetition, like a header, and it was measured rather than
    # assumed (KiCad 10): the N-way model is an end plate and a first way, N - 2 identical
    # middle ways, and a last way. Cut out of the 3-way model, the head + (N - 2) middles +
    # tail agree with KiCad's own 4- to 16-way models colour by colour to the last square
    # micrometre of surface. Three slices (about 38 KB) draw every length; the thirteen
    # models from 4 to 16 ways would have been 1.5 MB, three quarters again of everything
    # else in this directory together. Each slice is moved so its own pin sits at the
    # origin, because the renderer puts one at every pin (``view3d._terminal_block_pieces``).
    Model("screw-terminal-head", "TerminalBlock_Phoenix",
          "TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal",
          clip=(-1000.0, 2.54)),
    Model("screw-terminal-way", "TerminalBlock_Phoenix",
          "TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal",
          clip=(2.54, 7.62), offset=(-5.08, 0.0)),
    Model("screw-terminal-tail", "TerminalBlock_Phoenix",
          "TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal",
          clip=(7.62, 1000.0), offset=(-10.16, 0.0)),
    # -- one pin of a header, drawn once per pin by the renderer -----------
    Model("hdr-pin", "Connector_PinHeader_2.54mm", "PinHeader_1x01_P2.54mm_Vertical"),
)

#: WHAT EACH OF KiCad'S COLOURS IS MADE OF. A table and not a heuristic, because the whole
#: library turns out to use THIRTEEN colours across every through-hole package in it -- and
#: a rule guessing from the numbers gets gold plating wrong (it is saturated, so every
#: "is it grey" test calls it plastic) while a table cannot. An unknown colour is reported
#: rather than assumed, so a model that introduces one is noticed instead of coming out
#: quietly matte.
MATERIALS: dict[str, str] = {
    "#aaaaaa": "tinned",  # uncoloured in the source: a bare lead
    "#a5a392": "steel",  # KiCad's metal grey: a tab, a can, a crimped rim
    "#050505": "moulded",  # black epoxy: an IC body, a sleeve, a diode
    "#04227c": "sleeve",  # an electrolytic's printed PVC
    "#6f6651": "steel",  # the aluminium top a can's relief cross is pressed into
    "#c07635": "ceramic",  # a resistor's body
    "#9e2705": "ceramic",  # a disc capacitor's dip coating
    "#186b2a": "gloss",  # a terminal block's nylon
    "#005b84": "moulded",  # the band printed on a diode
    "#c6c4a0": "moulded",  # a DO-41's body
    "#b58136": "plated",  # gold on a header pin
    "#2a2a2a": "moulded",  # the base a crystal can is set into
    "#720301": "gloss",  # a film capacitor's case -- an LED's lens overrides this
}


def hexed(rgb: tuple[int, int, int]) -> str:
    """One colour as ``#rrggbb``, the way ``index.json`` writes it."""
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def material_for(colour: str, overrides: dict[str, str]) -> str:
    return overrides.get(colour, MATERIALS.get(colour, "moulded"))


def _step_path(kicad: Path, model: Model) -> Path:
    return kicad / "share" / "kicad" / "3dmodels" / f"{model.library}.3dshapes" / f"{model.step}.step"


def find_kicad(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    roots = [
        Path(r"C:/Program Files/KiCad"),
        Path(r"C:/Program Files (x86)/KiCad"),
        Path("/usr/share/kicad").parent.parent,
        Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport").parent.parent,
    ]
    for root in roots:
        if not root.is_dir():
            continue
        versions = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
        for version in versions:
            if (version / "share" / "kicad" / "3dmodels").is_dir():
                return version
    raise SystemExit("No KiCad installation found. Pass --kicad.")


def _cut_and_mesh(shape: Any) -> Any:
    """Everything above the board, tessellated. The cut is a real solid intersection, so
    the result is closed and its cut face is capped -- a clipped surface with a hole in it
    renders as a part you can see the inside of."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    keep = BRepPrimAPI_MakeBox(gp_Pnt(-200.0, -200.0, CUT_Z), gp_Pnt(200.0, 200.0, 200.0)).Shape()
    common = BRepAlgoAPI_Common(shape, keep)
    common.Build()
    return common.Shape() if common.IsDone() else shape


def groups_of(path: Path, rotate: float, offset: tuple[float, float]) -> dict[tuple[int, int, int], tuple[list[Any], list[Any]]]:
    """Every face of a model, gathered by the colour KiCad gave it."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.Quantity import Quantity_Color
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    document = TDocStd_Document(TCollection_ExtendedString("kicad"))
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.ReadFile(str(path))
    reader.Transfer(document)
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colours = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    labels = TDF_LabelSequence()
    shapes.GetFreeShapes(labels)

    # THE TURN AND THE SHIFT ARE APPLIED TO THE POINTS, not to the shape. Transforming the
    # solid first produces NEW faces, and the colours live in the XCAF document keyed on the
    # ORIGINAL ones -- so every face came back uncoloured and a five-colour electrolytic
    # collapsed into one grey lump. Moving the vertices as they are read costs nothing and
    # leaves the document's faces alone.
    angle = rotate * 3.141592653589793 / 180.0
    turn_cos, turn_sin = math.cos(angle), math.sin(angle)

    def place(x: float, y: float) -> tuple[float, float]:
        return (
            x * turn_cos - y * turn_sin + offset[0],
            x * turn_sin + y * turn_cos + offset[1],
        )

    by_colour: dict[tuple[int, int, int], tuple[list[Any], list[Any]]] = {}
    for index in range(1, labels.Length() + 1):
        shape = shapes.GetShape_s(labels.Value(index))
        shape = _cut_and_mesh(shape)
        BRepMesh_IncrementalMesh(shape, DEFLECTION, False, ANGULAR, True)
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = TopoDS.Face_s(explorer.Current())
            explorer.Next()
            location = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(face, location)
            if triangulation is None:
                continue
            colour = Quantity_Color()
            key = (170, 170, 170)
            for kind in (XCAFDoc_ColorType.XCAFDoc_ColorSurf, XCAFDoc_ColorType.XCAFDoc_ColorGen):
                if colours.GetColor(face, kind, colour):
                    key = (
                        round(colour.Red() * 255),
                        round(colour.Green() * 255),
                        round(colour.Blue() * 255),
                    )
                    break
            points, faces = by_colour.setdefault(key, ([], []))
            base = len(points)
            transform = location.Transformation()
            for node in range(1, triangulation.NbNodes() + 1):
                where = triangulation.Node(node).Transformed(transform)
                x, y = place(where.X(), where.Y())
                points.append((x, y, where.Z()))
            flipped = face.Orientation() == TopAbs_REVERSED
            for number in range(1, triangulation.NbTriangles() + 1):
                a, b, c = triangulation.Triangle(number).Get()
                if flipped:
                    a, c = c, a
                faces.append((base + a - 1, base + b - 1, base + c - 1))
        # The cut solid is discarded here; nothing below the board survives into the mesh.
    return by_colour


def clip_x(
    points: list[Any], faces: list[Any], x0: float, x1: float
) -> tuple[list[Any], list[Any]]:
    """The triangles of one colour, cut to ``x0 <= x <= x1``.

    ON THE MESH, NOT THE SOLID, and that is not a shortcut. Cutting the STEP solid with a box
    makes NEW faces wherever the box splits one, and the colours live in the XCAF document
    keyed on the ORIGINAL faces: every face running the length of the block came back
    uncoloured, half a terminal's nylon turned lead-grey. Clipping the triangles after they
    have their colour keeps every one of them, and makes no cap at the cut -- neighbouring
    slices meet face to face, so a cap would only be a wall inside the part.

    A triangle lying IN a cut plane (the block's end face, against which the end plate sits)
    belongs to the slice that STARTS at that plane, never to both: counted twice it put
    110 mm² of extra nylon inside every block.
    """
    tolerance = 1e-6
    out_points: list[Any] = []
    out_faces: list[Any] = []
    shared: dict[tuple[float, float, float], int] = {}
    for triangle in faces:
        corners = [points[index] for index in triangle]
        xs = [corner[0] for corner in corners]
        if max(xs) - min(xs) < tolerance and (
            abs(xs[0] - x1) < tolerance and abs(xs[0] - x0) >= tolerance
        ):
            continue  # in the slice's far plane: the next slice's
        polygon = corners
        for plane, keep_above in ((x0, True), (x1, False)):
            clipped = []
            for i, a in enumerate(polygon):
                b = polygon[(i + 1) % len(polygon)]
                a_in = a[0] >= plane - tolerance if keep_above else a[0] <= plane + tolerance
                b_in = b[0] >= plane - tolerance if keep_above else b[0] <= plane + tolerance
                if a_in:
                    clipped.append(a)
                if a_in != b_in:
                    t = (plane - a[0]) / (b[0] - a[0])
                    clipped.append((plane, a[1] + t * (b[1] - a[1]), a[2] + t * (b[2] - a[2])))
            polygon = clipped
            if len(polygon) < 3:
                break
        if len(polygon) < 3:
            continue
        # Corners shared, as the tessellator shares them: a vertex per triangle corner
        # doubled the files for no difference anybody could see.
        indices = []
        for corner in polygon:
            key = (round(corner[0], 6), round(corner[1], 6), round(corner[2], 6))
            index = shared.get(key)
            if index is None:
                index = shared[key] = len(out_points)
                out_points.append(corner)
            indices.append(index)
        out_faces.extend(
            (indices[0], indices[k], indices[k + 1]) for k in range(1, len(indices) - 1)
        )
    return out_points, out_faces


#: How far above the cut a lead is sampled to find its foot. Well under the height of any
#: body's underside, so a lead's foot is never confused with the part it holds up.
_FOOT_BAND_MM = 0.3


def pin_positions(footprint_id: str) -> list[tuple[float, float]]:
    """Where our footprint's holes are, in the model's frame: pin 1 at the origin, x with
    the column and y against the row -- the frame ``partmodels`` places a mesh in."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.model import STANDARD_PITCH_MM

    footprint = get_footprint(footprint_id)
    if footprint is None:
        raise SystemExit(f"{footprint_id}: no such footprint")
    return [(p.d_col * STANDARD_PITCH_MM, -p.d_row * STANDARD_PITCH_MM) for p in footprint.pins]


def lead_feet(points: list[Any]) -> list[tuple[float, float]]:
    """Where each lead of a mesh meets the board: the centre of every separate patch of
    vertices within ``_FOOT_BAND_MM`` of the cut. Leads are millimetres apart and under a
    millimetre across, so a patch is one lead."""
    patches: list[list[tuple[float, float]]] = []
    for x, y, z in points:
        if z > CUT_Z + _FOOT_BAND_MM:
            continue
        for patch in patches:
            px = sum(p[0] for p in patch) / len(patch)
            py = sum(p[1] for p in patch) / len(patch)
            if math.hypot(px - x, py - y) < 1.0:
                patch.append((x, y))
                break
        else:
            patches.append([(x, y)])
    return [
        (sum(p[0] for p in patch) / len(patch), sum(p[1] for p in patch) / len(patch))
        for patch in patches
    ]


def splay_leads(
    groups: dict[Any, tuple[list[Any], list[Any]]], pins: list[tuple[float, float]]
) -> dict[Any, tuple[list[Any], list[Any]]]:
    """Every bare lead bent from where it leaves the part to the hole it goes in.

    A PART'S LEGS ARE NOT WHERE THE GRID IS, and on a perfboard nobody expects them to be:
    a 7.5 mm disc capacitor is made with its leads 5 mm apart and goes in holes 7.62 mm
    apart, so whoever fits it bends them. KiCad draws the part as made -- straight legs
    standing 1.3 mm beside our holes, which in a view that exists to show which hole a lead
    is in reads as the wrong footprint. This does what the builder does. Each lead keeps
    its top, where it leaves the body, as a hinge; its foot moves onto the nearest hole;
    and every point between leans in proportion to how far down the lead it is. The top
    staying put is what keeps the lead joined to whatever it came out of.

    Only the bare leads (``tinned``) move. Each foot goes to its nearest hole, and two feet
    wanting the same hole is a mapping that is wrong rather than one to bend into shape.
    """
    moved = dict(groups)
    for colour, (points, faces) in groups.items():
        if MATERIALS.get(hexed(colour)) != "tinned":
            continue
        feet = lead_feet(points)
        targets = [
            min(pins, key=lambda pin, fx=fx, fy=fy: math.hypot(pin[0] - fx, pin[1] - fy))
            for fx, fy in feet
        ]
        if len(set(targets)) != len(targets):
            raise SystemExit(f"two leads would go in one hole: feet {feet}, holes {targets}")
        owner = [
            min(range(len(feet)), key=lambda i, x=x, y=y: math.hypot(feet[i][0] - x, feet[i][1] - y))
            for x, y, _z in points
        ]
        tops = [
            max((p[2] for p, o in zip(points, owner, strict=True) if o == lead), default=CUT_Z)
            for lead in range(len(feet))
        ]
        bent = []
        for (x, y, z), lead in zip(points, owner, strict=True):
            top = tops[lead]
            share = 0.0 if top <= CUT_Z else min(1.0, max(0.0, (top - z) / (top - CUT_Z)))
            dx = targets[lead][0] - feet[lead][0]
            dy = targets[lead][1] - feet[lead][1]
            bent.append((x + dx * share, y + dy * share, z))
        moved[colour] = (bent, faces)
    return moved


def write_ply(path: Path, points: list[Any], faces: list[Any]) -> None:
    """Binary little-endian PLY, which is what ``vtkPLYReader`` wants and what a mesh tool
    on any platform can open if somebody wants to look at one."""
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        "comment Derived from the KiCad packages3D library, CC-BY-SA 4.0. See LICENSE.\n"
        f"element vertex {len(points)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        f"element face {len(faces)}\n"
        "property list uchar int vertex_indices\n"
        "end_header\n"
    )
    with path.open("wb") as handle:
        handle.write(header.encode("ascii"))
        for x, y, z in points:
            handle.write(struct.pack("<3f", x, y, z))
        for a, b, c in faces:
            handle.write(struct.pack("<B3i", 3, a, b, c))


def _fit(model: Model, groups: dict[Any, tuple[list[Any], list[Any]]]) -> str:
    """How the model's own size compares with the footprint's.

    THE ONE CHECK THAT KEEPS THE 3D VIEW A CHECKING TOOL. A generated body cannot disagree
    with its footprint because it is computed from it; a borrowed model can, and a part
    drawn two millimetres smaller than the courtyard DRC is measuring makes the picture and
    the rules two different accounts of the same board (PLAN.md 8.4). So the mapping is only
    allowed to name a model that IS the package the footprint describes, and this is what
    says whether it is -- printed for every entry rather than asserted, because "close
    enough" is a judgement about a physical part.
    """
    from perfboard_studio.footprints import get_footprint

    footprint = get_footprint(model.footprint)
    if footprint is None or not footprint.body_outline:
        return ""
    xs = [point.x for point in footprint.body_outline]
    ys = [point.y for point in footprint.body_outline]
    points = [point for group in groups.values() for point in group[0]]
    if not points:
        return ""
    model_x = max(p[0] for p in points) - min(p[0] for p in points)
    model_y = max(p[1] for p in points) - min(p[1] for p in points)
    return (
        f"courtyard {max(xs) - min(xs):5.1f} x {max(ys) - min(ys):5.1f}"
        f"  model {model_x:5.1f} x {model_y:5.1f}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad", help="A KiCad install directory, e.g. C:/Program Files/KiCad/9.0")
    parser.add_argument("--only", help="Convert one footprint id, for trying a mapping out")
    args = parser.parse_args(argv)

    kicad = find_kicad(args.kicad)
    print(f"KiCad: {kicad}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    index: dict[str, Any] = {}
    missing: list[str] = []
    for model in MODELS:
        if args.only and model.footprint != args.only:
            continue
        source = _step_path(kicad, model)
        if not source.is_file():
            missing.append(f"{model.footprint}: {source.name}")
            continue
        parts = []
        if model.clip is None:
            groups = groups_of(source, model.rotate, model.offset)
            if model.splay:
                groups = splay_leads(groups, pin_positions(model.footprint))
        else:
            # Clipped in the model's own frame, then moved: the cut positions are written
            # against the pins as KiCad places them.
            groups = {}
            for colour, (points, faces) in groups_of(source, model.rotate, (0.0, 0.0)).items():
                kept_points, kept_faces = clip_x(points, faces, *model.clip)
                dx, dy = model.offset
                groups[colour] = (
                    [(x + dx, y + dy, z) for x, y, z in kept_points],
                    kept_faces,
                )
        overrides = dict(model.materials)
        ordered = [item for item in sorted(groups.items(), key=lambda item: -len(item[1][1])) if item[1][1]]
        # THE BODY IS THE BIGGEST PIECE THAT IS NOT METAL, and it is worth naming because the
        # renderer paints it in OUR colour rather than KiCad's. `bodies.BODY_STYLES` is one
        # table for the 2D view, the 3D view and the guide's step images, and a red LED that
        # came out a different red in two of the three would give that up for a borrowed
        # mesh. Everything else -- leads, tabs, bands, the gold on a pin -- keeps the colour
        # the model was drawn with, because our table has no opinion about those.
        body_index = next(
            (
                index
                for index, (colour, _mesh) in enumerate(ordered)
                # The LIBRARY's classification, not the override: a crystal's can is the
                # body of the part and is also metal, and asking the overridden answer
                # would take the body role away from the one piece anybody looks at.
                if MATERIALS.get(hexed(colour), "moulded")
                not in ("tinned", "steel", "plated")
            ),
            None,
        )
        for order, (colour, (points, faces)) in enumerate(ordered):
            name = f"{model.footprint}.{order}.ply"
            write_ply(OUT_DIR / name, points, faces)
            hex_colour = hexed(colour)
            if hex_colour not in MATERIALS and hex_colour not in overrides:
                print(f"  UNKNOWN COLOUR {hex_colour} in {model.footprint}", file=sys.stderr)
            part = {
                "mesh": name,
                "color": hex_colour,
                "material": material_for(hex_colour, overrides),
                # What the piece actually measures. The renderer needs it to print a
                # resistor's colour code ON the borrowed barrel rather than at the size
                # OUR footprint says the barrel is -- the two differ, because a footprint
                # records a package family and a model records one part in it.
                "bounds": [
                    round(min(p[axis] for p in points), 4) if axis < 3 else 0.0
                    for axis in range(3)
                ]
                + [round(max(p[axis] for p in points), 4) for axis in range(3)],
            }
            if order == body_index:
                part["role"] = "body"
            parts.append(part)
        index[model.footprint] = {"source": f"{model.library}/{model.step}", "parts": parts}
        total = sum(len(faces) for _points, faces in groups.values())
        print(f"  {model.footprint:20} {len(parts)} part(s) {total:6} triangles  {_fit(model, groups)}")

    if args.only:
        existing = json.loads((OUT_DIR / "index.json").read_text(encoding="utf-8"))
        existing.update(index)
        index = existing
    (OUT_DIR / "index.json").write_text(
        json.dumps(index, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    for line in missing:
        print(f"  MISSING {line}", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
