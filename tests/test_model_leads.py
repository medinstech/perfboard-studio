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
#: pin at the origin (``partmodels.header_pin_model``, ``terminal_block_models``,
#: ``vertical_header_models``).
ONE_PIN_MODELS = frozenset(
    {
        partmodels.HEADER_PIN,
        partmodels.TERMINAL_HEAD,
        partmodels.TERMINAL_WAY,
        partmodels.TERMINAL_TAIL,
        partmodels.VERTICAL_HEADER_HEAD,
        partmodels.VERTICAL_HEADER_WAY,
        partmodels.VERTICAL_HEADER_TAIL,
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
        for vx, vy, z in _vertices(piece.path):
            if z > CUT_Z + FOOT_BAND:
                continue
            # An entry that is another one turned places the same files (partmodels).
            x, y = model.placed(vx, vy)
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


#: Models drawn WITHOUT their own legs (``Model.leads``), each with the reason: legs hidden
#: under the body that would land beside our holes, where the footprint's pads stay put so
#: no document moves. The leads through the board are ours, at those pads.
LEGS_UNDER_THE_BODY: dict[str, str] = {
    "relay-srd": "the SRD's blades are off the grid, under its base",
    "led-5mm-rgb": "the RGB LED's legs are 1.27 mm apart, under it as it sits on the board",
}


@pytest.mark.parametrize("footprint_id", sorted(LEGS_UNDER_THE_BODY))
def test_a_part_drawn_without_its_legs_sits_on_the_board_over_them(footprint_id: str) -> None:
    """No leg of its own, and its body down on the board, where the legs it has are hidden."""
    model = partmodels.model_for(footprint_id)
    assert model is not None and model.body is not None
    assert not [piece for piece in model.pieces if piece.material == "tinned"]
    assert model.body.bounds[2] <= 0.15, model.body.bounds


@pytest.mark.parametrize("footprint_id", [fid for fid in MODELLED if fid not in LEGS_UNDER_THE_BODY])
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


#: How far a display's lead may stand from its hole: a part made ON the grid, unbent.
ON_THE_HOLE_MM = 0.05


@pytest.mark.parametrize(
    "footprint_id",
    [
        # Winstar's WC1602A on KiCad's 1 x 16 header, merged in under it at import.
        "box-16x1-p1-r1-80x36x15-o12.95x15.5",
        # Kingbright's CA56-12EWA, KiCad's model of the catalog's own part.
        "box-2x6-p6-r1-19x50.3x8.1-ccw",
        # The SA56-11 and SC56-11, drawn from Lite-On's LTS-6760: borrowed from ANOTHER
        # maker's part on the strength of its being the same package, so this is what holds
        # it to our footprint pad for pad.
        "box-2x5-p6-r1-19.05x12.7x8-ccw",
    ],
)
def test_a_display_stands_exactly_on_its_own_footprint(footprint_id: str) -> None:
    """A display is made on the 2.54 mm grid, so its model stands on our holes exactly, one
    lead to a hole: a model that drifted from the footprint is caught here to the twentieth
    of a millimetre, not at the drill's 0.4."""
    model = partmodels.model_for(footprint_id)
    assert model is not None
    feet = _feet(model)
    holes = _holes(footprint_id)
    assert len(feet) == len(holes), (footprint_id, len(feet), len(holes))
    for hx, hy in holes:
        nearest = min(math.hypot(hx - fx, hy - fy) for fx, fy in feet)
        assert nearest <= ON_THE_HOLE_MM, (footprint_id, hx, hy, nearest)


def test_the_to92_is_the_model_with_its_legs_bent_to_the_grid() -> None:
    """The case this file was written for. KiCad has the TO-92 both ways -- as made (leads
    1.27 mm apart) and with its legs bent out to 2.54 mm -- and our footprint is the second."""
    model = partmodels.model_for("to92")
    assert model is not None
    assert model.source.endswith("TO-92_Inline_Wide")
    assert sorted(round(x, 2) for x, _y in _feet(model)) == [0.0, 2.54, 5.08]


@pytest.mark.parametrize("footprint_id", ["led-3mm", "led-5mm", "led-10mm"])
def test_an_leds_flat_is_on_its_cathode(footprint_id: str) -> None:
    """The flange's flat is how an LED says which way round it goes, and it is on the
    cathode. KiCad numbers the cathode pin 1 and we number the ANODE pin 1, so the model as
    it came stood its flat on the anode -- a board built from the picture has the LED in
    backwards. The flat is where the flange stops short, so it is the side of the case
    nearer the pins' midpoint."""
    model = partmodels.model_for(footprint_id)
    footprint = get_footprint(footprint_id)
    assert model is not None and footprint is not None
    body = model.body
    assert body is not None and len(body.bounds) == 6
    cathode = next(pin for pin in footprint.pins if pin.name == "K")
    cathode_x = cathode.d_col * STANDARD_PITCH_MM
    middle = sum(pin.d_col for pin in footprint.pins) / len(footprint.pins) * STANDARD_PITCH_MM
    x_min, x_max = body.bounds[0], body.bounds[3]
    reach_towards_cathode = x_max - middle if cathode_x > middle else middle - x_min
    reach_away = middle - x_min if cathode_x > middle else x_max - middle
    assert reach_towards_cathode < reach_away - 0.2, (x_min, x_max, cathode_x)


#: Axial parts whose model is knowingly longer than the footprint says, and why.
AXIAL_LENGTH_EXCEPTIONS = {
    # KiCad has no 6.3 mm (DIN0207) body at 12.70 mm, and the pitch comes first.
    "r-axial-5": "DIN0309 is the only body KiCad draws at 12.70 mm",
}


@pytest.mark.parametrize(
    "footprint_id",
    sorted(
        fid
        for fid in MODELLED
        if (fp := get_footprint(fid)) is not None and fp.body.archetype == "axial-cylinder"
    ),
)
def test_an_axial_models_barrel_is_the_length_its_footprint_says(footprint_id: str) -> None:
    """r-axial-6 is a 9 mm body and was drawn with KiCad's 6.3 mm one, while r-axial-5 --
    a 6.3 mm body -- has to borrow the 9 mm model: the two looked swapped on a board,
    with the right 9 mm model at r-axial-6's pitch sitting unused in the library."""
    if footprint_id in AXIAL_LENGTH_EXCEPTIONS:
        pytest.skip(AXIAL_LENGTH_EXCEPTIONS[footprint_id])
    model = partmodels.model_for(footprint_id)
    footprint = get_footprint(footprint_id)
    assert model is not None and model.body is not None and footprint is not None
    x0, _y0, _z0, x1, _y1, _z1 = model.body.bounds
    assert abs((x1 - x0) - float(footprint.body.dims["length"])) <= 1.5, model.source


def test_the_relay_is_drawn_as_its_own_footprint() -> None:
    """``relay-spdt`` is an on-grid approximation that no KiCad relay model shares a pinout
    with, so it has no model and the generated box -- its own footprint's size -- draws it."""
    assert partmodels.model_for("relay-spdt") is None


def test_the_passive_buzzer_is_the_active_ones_can_at_its_own_height() -> None:
    """CUI's CEM-1203(42) is the 12 mm can of KiCad's 9.5 mm buzzer, 8.5 mm tall: the same
    model scaled in height (``Model.height``), its legs still in their holes."""
    active = partmodels.model_for("box-2x1-p3-r1-12x12x9.5")
    passive = partmodels.model_for("box-2x1-p3-r1-12x12x8.5")
    footprint = get_footprint("box-2x1-p3-r1-12x12x8.5")
    assert active is not None and passive is not None and footprint is not None
    assert active.source == passive.source == "Buzzer_Beeper/Buzzer_12x9.5RM7.6"

    def top(model: partmodels.PartModel) -> float:
        return max(piece.bounds[5] for piece in model.pieces)

    assert top(passive) == pytest.approx(footprint.body_height)
    assert top(active) == pytest.approx(9.53, abs=0.01)


def test_the_dht22_is_the_dht11s_case_at_aosongs_size() -> None:
    """KiCad has the AM2302's footprint and not its case: it is the DHT11's grilled case
    scaled to Aosong's 15.1 x 7.7 x 25.1 mm drawing (``Model.case_size``), white, its body
    1.4 mm in front of its pins as its footprint has it, and its legs still in their holes."""
    dht11 = partmodels.model_for("box-4x1-p1-r1-12x5.5x15.5")
    dht22 = partmodels.model_for("box-4x1-p1-r1-15.1x7.7x25.1-o0x1.4")
    assert dht11 is not None and dht22 is not None and dht22.body is not None
    assert dht22.source == dht11.source == "Sensor/Aosong_DHT11_5.5x12.0_P2.54mm"
    x0, y0, z0, x1, y1, z1 = dht22.body.bounds
    assert (x1 - x0, y1 - y0, z1 - z0) == pytest.approx((15.1, 7.7, 25.1), abs=0.01)
    # The model's y runs up the board: 1.4 mm in front of the pins is y = -1.4 here.
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((3.81, -1.4), abs=0.01)
    assert dht22.body.color == "#e9e7e1"
