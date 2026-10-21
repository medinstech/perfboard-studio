"""A resistor or a diode stood on end: one part, modelled as what it is everywhere.

The lying axial part is a barrel between its two holes, as tall as it is thick. Stood on
end over one hole it is three or four times as tall, its body is over ONE pin, its far lead
is bent back over the top, and it goes in with the small bodies rather than the flat ones.
These tests hold every consumer to that: the id, the body box, the height KiCad's models
measure, DRC, the guide, both views, the STEP file and the importer.
"""

from __future__ import annotations

import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    PlaceComponentPayload,
    SetHeightLimitPayload,
    create_standard_registry,
)
from perfboard_studio.drc import placed_body_box, run_drc
from perfboard_studio.footprints import (
    GENERATED_ID_GRAMMAR,
    UPRIGHT_DIODE_STANDOFF_MM,
    UPRIGHT_LOOP_MEASURED_MM,
    UPRIGHT_RESISTOR_STANDOFF_MM,
    body_extent,
    footprint_lookup,
    get_footprint,
    standard_footprints,
    standing_pin,
    upright_body_span,
)
from perfboard_studio.geometry import all_pin_holes, hole_to_mm
from perfboard_studio.guide import GuideOptions, PartStep, build_guide
from perfboard_studio.model import Board, DocumentMeta, HoleCoord, PerfDocument
from perfboard_studio.parsers.kicad_parts import kicad_footprint_ids

LOOKUP = footprint_lookup()

RESISTOR = "axial-1h-6.3x2.5-v"
DIODE_CATHODE_DOWN = "axial-1h-5.2x2.7-pol-v"
DIODE_CATHODE_UP = "axial-1h-5.2x2.7-pol-v2"


def _board(pitch: float = 2.54) -> Board:
    return Board(
        type="pad-per-hole", cols=30, rows=20, pitch=pitch, thickness=1.6,
        material="FR4", pad_diameter=1.9, drill_diameter=0.8,
    )


def _bus(pitch: float = 2.54) -> CommandBus:
    document = PerfDocument(
        meta=DocumentMeta(name="standing", created="", modified=""), board=_board(pitch)
    )
    return CommandBus(document, create_standard_registry(), CommandContext(next_id=create_id_generator()))


def _place(
    bus: CommandBus,
    ref: str,
    footprint_id: str,
    col: int,
    row: int,
    rotation: int = 0,
    mirrored: bool = False,
    value: str = "",
) -> None:
    result = bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref=ref,
            value=value,
            footprint_id=footprint_id,
            anchor=HoleCoord(col=col, row=row),
            rotation=rotation,  # type: ignore[arg-type]
            mirrored=mirrored,
        ),
    )
    assert result.ok, result.message


# ---------------------------------------------------------------------------
# The id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fid", "pin"),
    [
        ("axial-1h-6.3x2.5-v", "1"),
        ("axial-1h-6.3x2.5-v2", "2"),
        ("axial-2h-4x2-pol-v", "1"),
        ("axial-1h-5.2x2.7-pol-v2", "2"),
    ],
)
def test_a_standing_part_is_asked_for_by_its_id_and_stands_on_the_pin_it_says(
    fid: str, pin: str
) -> None:
    footprint = get_footprint(fid)
    assert footprint is not None and footprint.id == fid
    assert footprint.body.archetype == "axial-upright"
    stood = standing_pin(footprint)
    assert stood is not None and stood.number == pin
    # The pins do not move: pin 1 is the anchor whichever pin the body is over.
    first = footprint.pins[0]
    assert (first.number, first.d_col, first.d_row) == ("1", 0, 0)


@pytest.mark.parametrize(
    "fid",
    ["axial-1h-6.3x2.5-v1", "axial-1h-6.3x2.5-v3", "axial-1h-6.3x2.5-v0", "axial-1h-6.3x2.5-V",
     "axial-1h-6.3x2.5-v-pol", "axial-1h-6.3x2.5-v2-v"],
)
def test_one_spelling_per_standing_part(fid: str) -> None:
    """Standing on pin 1 is spelled "-v", never "-v1"; there is no third pin to stand on,
    and the polarity comes before the mounting."""
    assert get_footprint(fid) is None


def test_the_lying_part_and_the_library_are_what_they_were() -> None:
    lying = get_footprint("axial-1h-6.3x2.5")
    assert lying is not None and lying.body.archetype == "axial-cylinder"
    assert lying.body_height == 2.5
    assert len(standard_footprints()) == 61
    assert not any(f.body.archetype == "axial-upright" for f in standard_footprints().values())


def test_the_grammar_says_how_to_stand_one_up() -> None:
    assert "[-v|-v2]" in GENERATED_ID_GRAMMAR
    assert "axial-1h-6.3x2.5-v" in GENERATED_ID_GRAMMAR


# ---------------------------------------------------------------------------
# Where the body is, and how tall
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pitch", [2.54, 2.0, 3.0])
@pytest.mark.parametrize("fid", [RESISTOR, DIODE_CATHODE_UP, "axial-3h-6.3x2.5-v2"])
def test_the_body_is_over_its_pin_at_the_boards_own_pitch(fid: str, pitch: float) -> None:
    """Not on the pins' centroid, and not by a millimetre offset that would drift off the
    hole on a board whose pitch is not 2.54."""
    footprint = get_footprint(fid)
    assert footprint is not None
    stood = standing_pin(footprint)
    assert stood is not None
    extent = body_extent(footprint, pitch)
    assert (extent.centre_x, extent.centre_y) == (stood.d_col * pitch, stood.d_row * pitch)
    diameter = footprint.body.dims["diameter"]
    assert (extent.size_x, extent.size_y) == (diameter, diameter)


@pytest.mark.parametrize("fid", [RESISTOR, DIODE_CATHODE_DOWN, DIODE_CATHODE_UP, "axial-4h-9x3.2-v2"])
def test_the_courtyard_holds_the_standing_body_and_both_pins(fid: str) -> None:
    footprint = get_footprint(fid)
    assert footprint is not None
    xs = [p.x for p in footprint.body_outline]
    ys = [p.y for p in footprint.body_outline]
    min_x, max_x, min_y, max_y = body_extent(footprint, 2.54).box
    assert min(xs) < min_x and max(xs) > max_x and min(ys) < min_y and max(ys) > max_y
    for pin in footprint.pins:
        assert min(xs) < pin.d_col * 2.54 < max(xs)


#: KiCad 10's own models, `*_Vertical*.step`, measured on the exact B-rep with OpenCASCADE:
#: the top of the bent-over lead. The numbers in footprints.py's "Stood on end".
KICAD_TOPS = [
    ("axial-1h-3.6x1.6-v", 6.60),  # R_Axial_DIN0204
    ("axial-1h-6.3x2.5-v", 9.50),  # R_Axial_DIN0207
    ("axial-1h-9x3.2-v", 12.40),  # R_Axial_DIN0309
    ("axial-1h-4x2-pol-v", 5.75),  # D_DO-35_SOD27, its model 4.0 long
    ("axial-1h-5.2x2.7-pol-v", 7.40),  # D_DO-41_SOD81
]


@pytest.mark.parametrize(("fid", "measured"), KICAD_TOPS)
def test_a_standing_part_is_as_tall_as_kicads_model_of_it(fid: str, measured: float) -> None:
    footprint = get_footprint(fid)
    assert footprint is not None
    # Exactly, now that a size KiCad models takes its own measured loop: a borrowed mesh of
    # it is held inside this height with no tolerance (test_axial_upright_meshes).
    assert footprint.body_height == pytest.approx(measured, abs=1e-9)


def test_the_loop_is_measured_where_kicad_has_the_size_and_a_straight_line_elsewhere() -> None:
    """A size KiCad models takes its own loop, exactly; between two, the straight line
    joining them; past either end, the end segment carried on -- and over the whole range
    of diameters an id accepts, never below zero."""
    from perfboard_studio.footprints import _MAX_BODY_MM, upright_loop_mm

    for polarized, points in UPRIGHT_LOOP_MEASURED_MM.items():
        for diameter, loop in points:
            assert upright_loop_mm(diameter, polarized) == loop
        (d0, l0), (d1, l1) = points[0], points[1]
        assert upright_loop_mm((d0 + d1) / 2, polarized) == pytest.approx((l0 + l1) / 2)
        below = d0 - 0.5
        assert upright_loop_mm(below, polarized) == pytest.approx(l0 - 0.5 * (l1 - l0) / (d1 - d0))
        (dn1, ln1), (dn, ln) = points[-2], points[-1]
        assert upright_loop_mm(dn + 1.0, polarized) == pytest.approx(ln + (ln - ln1) / (dn - dn1))
        assert upright_loop_mm(0.1, polarized) > 0 and upright_loop_mm(_MAX_BODY_MM, polarized) > 0


def test_the_height_is_the_standoff_the_body_and_the_loop() -> None:
    resistor = get_footprint(RESISTOR)
    diode = get_footprint(DIODE_CATHODE_UP)
    assert resistor is not None and diode is not None
    assert resistor.body_height == pytest.approx(UPRIGHT_RESISTOR_STANDOFF_MM + 6.3 + 2.2)
    assert diode.body_height == pytest.approx(UPRIGHT_DIODE_STANDOFF_MM + 5.2 + 1.7)
    assert upright_body_span(resistor) == pytest.approx((1.0, 7.3))
    lying = get_footprint("axial-1h-6.3x2.5")
    assert lying is not None and upright_body_span(lying) == (0.0, lying.body_height)


# ---------------------------------------------------------------------------
# DRC, the guide
# ---------------------------------------------------------------------------


def test_drc_measures_a_standing_part_at_the_height_it_stands() -> None:
    """Under a 5 mm lid the lying resistor fits and the same resistor stood on end does not."""
    bus = _bus()
    _place(bus, "R1", "axial-1h-6.3x2.5", 4, 4)
    _place(bus, "R2", RESISTOR, 12, 4)
    assert bus.dispatch("height-limit.set", SetHeightLimitPayload(height_limit_mm=5.0)).ok
    too_tall = [v for v in run_drc(bus.document, LOOKUP) if v.rule == "component-too-tall"]
    refs = {c.id: c.ref for c in bus.document.components}
    assert [refs[cid] for v in too_tall for cid in v.component_ids] == ["R2"]


def _part_step(document: PerfDocument, ref: str, language: str = "en") -> tuple[int, PartStep]:
    guide = build_guide(document, LOOKUP, GuideOptions(language=language))  # type: ignore[arg-type]
    for phase in guide.phases:
        for step in phase.steps:
            if isinstance(step, PartStep) and step.ref == ref:
                return phase.number, step
    raise AssertionError(f"no step for {ref}")


def test_the_guide_fits_it_with_the_small_bodies_and_says_how_to_bend_it() -> None:
    bus = _bus()
    _place(bus, "R1", RESISTOR, 4, 4, value="10k")
    _place(bus, "D1", DIODE_CATHODE_DOWN, 4, 8)
    _place(bus, "D2", DIODE_CATHODE_UP, 4, 12)
    _place(bus, "R9", "axial-1h-6.3x2.5", 12, 4)

    phase, resistor = _part_step(bus.document, "R1")
    assert phase == 3
    assert resistor.bend_template_mm is None, "it is bent back over itself, not to a pitch"
    assert resistor.height_mm == pytest.approx(9.5)
    assert any(
        note.startswith("Stand it on end over E5 and bend the top lead back over and down into F5")
        for note in resistor.notes
    ), resistor.notes
    assert _part_step(bus.document, "R9")[0] == 1

    _, down = _part_step(bus.document, "D1")
    _, up = _part_step(bus.document, "D2")
    assert any("Stand it on end over E9, the banded end down" in n for n in down.notes), down.notes
    assert any("Stand it on end over F13, the banded end up" in n for n in up.notes), up.notes
    # The cathode's hole is said as it is for any diode -- pin 1, wherever the body is.
    assert down.polarity == "Cathode — the banded end — in E9"
    assert up.polarity == "Cathode — the banded end — in E13"


def test_a_long_part_stood_on_end_goes_in_with_the_bodies_as_tall_as_it_is() -> None:
    """Its kind does not fix a standing part's height: its body's LENGTH does. A DIN0207
    stands among the LEDs; one twice as long is taller than every small body and would be
    fitted before the electrolytics it then stops the board lying flat for. The thresholds
    are the tallest standard bodies of phases 3 and 4, measured off the library."""
    from perfboard_studio.footprints import standard_footprints
    from perfboard_studio.guide import PHASE_BY_ARCHETYPE

    def tallest(phase: int) -> float:
        return max(
            fp.body_height for fp in standard_footprints().values()
            if PHASE_BY_ARCHETYPE.get(fp.body.archetype) == phase
        )

    bus = _bus()
    _place(bus, "R1", RESISTOR, 4, 4)
    _place(bus, "R2", "axial-2h-15x5-v", 4, 8)
    _place(bus, "R3", "axial-3h-25x6-v", 4, 12)
    heights = {ref: _part_step(bus.document, ref)[1].height_mm for ref in ("R1", "R2", "R3")}
    assert heights["R1"] <= tallest(3) < heights["R2"] <= tallest(4) < heights["R3"]
    assert [_part_step(bus.document, ref)[0] for ref in ("R1", "R2", "R3")] == [3, 4, 5]


def test_the_guide_says_it_in_turkish_too() -> None:
    bus = _bus()
    _place(bus, "D2", DIODE_CATHODE_UP, 4, 12)
    _, step = _part_step(bus.document, "D2", "tr")
    assert any("bantlı ucu üstte kalacak şekilde dik oturt" in n for n in step.notes), step.notes
    assert step.footprint_name.startswith("Eksenel, 2. pinin üstünde dik")


# ---------------------------------------------------------------------------
# Both views and the STEP file agree about where the body is
# ---------------------------------------------------------------------------

TURNS = [(r, m) for r in (0, 90, 180, 270) for m in (False, True)]


def _standing_hole(document: PerfDocument) -> tuple[float, float]:
    comp = document.components[0]
    footprint = LOOKUP(comp.footprint_id)
    assert footprint is not None
    stood = standing_pin(footprint)
    hole = next(h for p, h in all_pin_holes(comp, footprint) if stood is not None and p.number == stood.number)
    centre = hole_to_mm(hole, document.board)
    return centre.x, centre.y


@pytest.mark.parametrize(("rotation", "mirrored"), TURNS)
def test_drc_the_3d_view_and_the_step_file_put_the_body_over_one_hole(
    rotation: int, mirrored: bool
) -> None:
    from perfboard_studio.step_export import Cylinder, board_model
    from perfboard_studio.ui import view3d

    bus = _bus()
    _place(bus, "D1", DIODE_CATHODE_UP, 10, 8, rotation, mirrored)
    document = bus.document
    comp = document.components[0]
    footprint = LOOKUP(comp.footprint_id)
    assert footprint is not None
    hole_x, hole_y = _standing_hole(document)

    min_x, max_x, min_y, max_y = placed_body_box(comp, footprint, document.board)
    assert ((min_x + max_x) / 2, (min_y + max_y) / 2) == pytest.approx((hole_x, hole_y))

    body = view3d._world_body(LOOKUP, comp, document.board)
    assert body is not None
    # The 3D world counts rows up-negative from the first hole.
    first = hole_to_mm(HoleCoord(0, 0), document.board)
    assert (body.x, body.y) == pytest.approx((hole_x - first.x, -(hole_y - first.y)))
    assert body.standing == pytest.approx(upright_body_span(footprint))

    actors = view3d.build_component(LOOKUP, comp, document.board)
    tops = [actor.GetBounds()[5] for actor in actors]
    # The bent-over lead is the top of the part, at the height DRC measured: KiCad's model of
    # this package sits on the board as every borrowed mesh does, and the generated body (a
    # size KiCad has no model of) _LIFT above it, as every generated body does.
    assert footprint.body_height - 0.02 <= max(tops) <= footprint.body_height + view3d._LIFT + 0.02

    part = next(p for p in board_model(document, LOOKUP)[1:] if p.name == "D1")
    envelope = part.solids[0].shape
    assert isinstance(envelope, Cylinder) and envelope.axis == (0.0, 0.0, 1.0)
    assert envelope.base[2] == document.board.thickness
    assert envelope.length == pytest.approx(footprint.body_height)
    assert envelope.radius == pytest.approx(2.7 / 2)
    # Every lead in the file goes down a hole; the crossing at the top is the only one that
    # does not stand upright.
    leads = [s.shape for s in part.solids[1:] if isinstance(s.shape, Cylinder)]
    assert sum(lead.axis == (0.0, 0.0, 1.0) for lead in leads) == 2
    assert sum(lead.axis[2] == 0.0 for lead in leads) == 1
    tallest = max(lead.base[2] + lead.length * lead.axis[2] + lead.radius for lead in leads)
    assert tallest == pytest.approx(document.board.thickness + footprint.body_height)


def test_the_2d_view_draws_it_as_its_end_with_one_lead_running_to_the_other_hole() -> None:
    from perfboard_studio.ui.bodies import leads_for, placement_for, resistor_bands, style_for

    resistor = get_footprint(RESISTOR)
    diode = get_footprint(DIODE_CATHODE_UP)
    assert resistor is not None and diode is not None
    placement = placement_for(resistor, 2.54)
    assert placement.silhouette == "circle"
    leads = leads_for(resistor, placement, 2.54)
    assert len(leads) == 1
    assert (leads[0].from_x, leads[0].to_x) == pytest.approx((2.54, 1.25))
    # Still a resistor and a diode: the same bands to print, the same black diode.
    assert resistor_bands(resistor, "10k") is not None
    assert resistor_bands(diode, "10k") is None
    assert style_for(diode) == style_for(get_footprint("d-do41"))  # type: ignore[arg-type]


def test_the_2d_view_paints_a_standing_part_on_both_faces() -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.view2d import BoardScene

    QApplication.instance() or QApplication(["perfboard-studio-tests"])
    bus = _bus()
    _place(bus, "R1", RESISTOR, 4, 4, value="10k")
    _place(bus, "D1", DIODE_CATHODE_UP, 8, 4, rotation=90)
    for side in ("top", "bottom"):
        scene = BoardScene(bus.document, LOOKUP, side=side)  # type: ignore[arg-type]
        image = QImage(400, 300, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        scene.render(painter)
        painter.end()


def test_the_3d_band_is_at_the_cathode_end() -> None:
    """Standing on its cathode the band is at the bottom; cathode up, at the top."""
    from perfboard_studio.ui import view3d

    bands = {}
    for fid in (DIODE_CATHODE_DOWN, DIODE_CATHODE_UP):
        bus = _bus()
        _place(bus, "D1", fid, 10, 8)
        comp = bus.document.components[0]
        body = view3d._world_body(LOOKUP, comp, bus.document.board)
        assert body is not None
        accent = view3d._rgb(body.style.accent)
        pieces = view3d._axial_upright_pieces(body)
        band = [piece for piece in pieces if piece.rgb == accent]
        assert len(band) == 1
        bands[fid] = band[0].position[2]
    bottom, top = upright_body_span(get_footprint(DIODE_CATHODE_UP))  # type: ignore[arg-type]
    middle = view3d._LIFT + (bottom + top) / 2
    assert bands[DIODE_CATHODE_DOWN] < middle < bands[DIODE_CATHODE_UP]


# ---------------------------------------------------------------------------
# What comes in from KiCad
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kicad", "expected"),
    [
        ("Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P2.54mm_Vertical", "axial-1h-6.3x2.5-v"),
        ("Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P5.08mm_Vertical", "axial-2h-6.3x2.5-v"),
        ("Diode_THT:D_DO-41_SOD81_P2.54mm_Vertical_AnodeUp", "axial-1h-5.2x2.7-pol-v"),
        ("Diode_THT:D_DO-41_SOD81_P5.08mm_Vertical_CathodeUp", "axial-2h-5.2x2.7-pol-v2"),
        # KiCad spelled it with a K before version 7.
        ("Diode_THT:D_DO-35_SOD27_P2.54mm_Vertical_KathodeUp", "axial-1h-4x2-pol-v2"),
    ],
)
def test_kicads_standing_parts_come_in_standing(kicad: str, expected: str) -> None:
    """Pad 1 is a KiCad diode's cathode. Anode up, the cathode is under the body, which
    stands over pad 1; cathode up, over pad 2 -- where KiCad's own models put the barrel."""
    ids, note = kicad_footprint_ids(kicad)
    assert ids == [expected] and note == ""
    assert get_footprint(expected) is not None


def test_a_standing_part_whose_lead_misses_the_grid_is_still_laid_flat_and_says_so() -> None:
    for kicad in (
        "Resistor_THT:R_Axial_DIN0204_L3.6mm_D1.6mm_P1.90mm_Vertical",
        "Diode_THT:D_DO-35_SOD27_P3.81mm_Vertical_AnodeUp",
    ):
        ids, note = kicad_footprint_ids(kicad)
        assert ids == [] and "laid flat" in note


def test_the_custom_part_dialog_stands_one_up() -> None:
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.main import _custom_families

    QApplication.instance() or QApplication(["perfboard-studio-tests"])
    axial = next(f for f in _custom_families() if "Axial" in f.label)
    values = {"span": 1.0, "length": 6.3, "diameter": 2.5, "polarized": 1.0}
    built = {mount: axial.build({**values, "mount": float(mount)}).id for mount in (0, 1, 2)}
    assert built == {0: "axial-1h-6.3x2.5-pol", 1: "axial-1h-6.3x2.5-pol-v", 2: "axial-1h-6.3x2.5-pol-v2"}
    # A diode's standoff and loop, on a body the size of a quarter-watt resistor's: 2.5 mm
    # across is between the DO-35's 2.0 and the DO-41's 2.7, so the loop is between theirs.
    from perfboard_studio.footprints import upright_loop_mm

    assert 1.25 < upright_loop_mm(2.5, True) < 1.7
    assert math.isclose(get_footprint(built[2]).body_height, 0.5 + 6.3 + upright_loop_mm(2.5, True))  # type: ignore[union-attr]
