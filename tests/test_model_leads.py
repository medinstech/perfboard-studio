"""Every borrowed package stands on its own holes.

The 3D view exists to show which hole a lead goes in, and a borrowed KiCad model brings
its own legs down to the board surface -- so a model made on another pitch than its
footprint draws a part standing on nothing. The mapping in ``tools/import_kicad_models.py``
said it chose "by pitch first", and four entries had it wrong anyway: the TO-92 (KiCad's
1.27 mm inline model on a 2.54 mm footprint -- its middle leg stood between two holes),
the 3-hole disc capacitor (1.3 mm beside both holes), the tactile switch (up to 2 mm) and
the relay (another pinout altogether). Nothing measured it; this does.

It reads the shipped meshes and nothing else -- no KiCad, no STEP reader, no VTK -- so it
runs wherever the tests do. A lead's FOOT is where it was cut at the board surface
(``CUT_Z``): the converter caps the cut, so every lead leaves a small patch of vertices
there, one patch per lead.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from perfboard_studio.footprints import get_footprint
from perfboard_studio.model import STANDARD_PITCH_MM
from perfboard_studio.ui import partmodels

#: Where the converter cuts a model (``tools/import_kicad_models.CUT_Z``), and how close to
#: it a vertex has to be to be part of a foot.
CUT_Z = -0.05
FOOT_BAND = 0.01

#: How far a foot may stand from its hole's centre and still be IN the hole: the radius of
#: the smallest drill this application offers (0.8 mm). A crystal's 4.88 mm leads on the
#: 5.08 mm footprint are 0.2 mm out, and go in.
IN_THE_HOLE_MM = 0.4

#: Models of ONE pin, drawn by the renderer at every pin of their part: each has its own
#: pin at the origin (``partmodels.header_pin_model``, ``terminal_block_models``).
ONE_PIN_MODELS = frozenset(
    {
        partmodels.HEADER_PIN,
        partmodels.TERMINAL_HEAD,
        partmodels.TERMINAL_WAY,
        partmodels.TERMINAL_TAIL,
    }
)


def _vertices(path: Path) -> list[tuple[float, float, float]]:
    data = path.read_bytes()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii").splitlines()
    count = next(int(line.split()[2]) for line in header if line.startswith("element vertex"))
    return [struct.unpack_from("<3f", data, end + 12 * i) for i in range(count)]


#: Two cut vertices this close are the same lead. Above the widest lead's side (a terminal
#: block's 0.9 mm square pin, whose cut is four corners and nothing between) and below the
#: narrowest gap between two leads (a TO-92's, 1.5 mm at the board).
SAME_LEAD_MM = 1.2


def _feet(model: partmodels.PartModel) -> list[tuple[float, float]]:
    """The centre of every lead where it meets the board: the cut's vertices, joined into
    one patch wherever a chain of them runs less than ``SAME_LEAD_MM`` apart."""
    patches: list[list[tuple[float, float]]] = []
    for piece in model.pieces:
        if piece.material != "tinned":
            continue
        for x, y, z in _vertices(piece.path):
            if z > CUT_Z + FOOT_BAND:
                continue
            touching = [
                patch
                for patch in patches
                if any(math.hypot(px - x, py - y) < SAME_LEAD_MM for px, py in patch)
            ]
            joined = [(x, y)] + [point for patch in touching for point in patch]
            patches = [p for p in patches if all(p is not t for t in touching)] + [joined]
    return [
        (sum(p[0] for p in patch) / len(patch), sum(p[1] for p in patch) / len(patch))
        for patch in patches
    ]


def _holes(footprint_id: str) -> list[tuple[float, float]]:
    """The footprint's holes in the model's frame: pin 1 at the origin, x with the column,
    y against the row -- see ``view3d._model_pieces``."""
    if footprint_id in ONE_PIN_MODELS:
        return [(0.0, 0.0)]
    footprint = get_footprint(footprint_id)
    assert footprint is not None, f"{footprint_id} has a model but no footprint"
    return [(p.d_col * STANDARD_PITCH_MM, -p.d_row * STANDARD_PITCH_MM) for p in footprint.pins]


MODELLED = sorted(partmodels.known_footprints())


def test_there_are_models_to_measure() -> None:
    # An empty index would pass every case below by having none.
    assert len(MODELLED) > 30


@pytest.mark.parametrize("footprint_id", MODELLED)
def test_every_lead_goes_in_a_hole_and_every_hole_gets_a_lead(footprint_id: str) -> None:
    model = partmodels.model_for(footprint_id)
    assert model is not None
    feet = _feet(model)
    holes = _holes(footprint_id)
    assert feet, f"{footprint_id}: no lead reaches the board"
    for fx, fy in feet:
        nearest = min(math.hypot(hx - fx, hy - fy) for hx, hy in holes)
        assert nearest <= IN_THE_HOLE_MM, (
            f"{footprint_id} ({model.source}): a lead meets the board at "
            f"({fx:.2f}, {fy:.2f}), {nearest:.2f} mm from the nearest hole"
        )
    for hx, hy in holes:
        assert any(math.hypot(hx - fx, hy - fy) <= IN_THE_HOLE_MM for fx, fy in feet), (
            f"{footprint_id} ({model.source}): no lead goes in the hole at ({hx:.2f}, {hy:.2f})"
        )


def test_the_to92_is_the_model_with_its_legs_bent_to_the_grid() -> None:
    """The case this file was written for. KiCad has the TO-92 both ways -- as made (leads
    1.27 mm apart) and with its legs bent out to 2.54 mm -- and our footprint is the second."""
    model = partmodels.model_for("to92")
    assert model is not None
    assert model.source.endswith("TO-92_Inline_Wide")
    assert sorted(round(x, 2) for x, _y in _feet(model)) == [0.0, 2.54, 5.08]


def test_the_relay_is_drawn_as_its_own_footprint() -> None:
    """``relay-spdt`` is an on-grid approximation that no KiCad relay model shares a pinout
    with, so it has no model and the generated box -- its own footprint's size -- draws it."""
    assert partmodels.model_for("relay-spdt") is None
