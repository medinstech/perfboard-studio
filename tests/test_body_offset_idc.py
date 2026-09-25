"""A body that is not centred on its pins, and the IDC box header.

Two things a generated id could not say until now, both found laying out the first real
board with this tool (the DELTA-ATLAS manipulator plaket):

- A breakout module whose header runs along one EDGE of its board. ``box-`` centred every
  body on its pins, so a 16 x 14.5 mm CAN transceiver board with its six pins along one
  side could only be described as reaching 14.5 mm past the header in BOTH directions --
  ``box-6x1-p1-r1-16x29x7`` -- claiming board it does not use, or else claiming too
  little on the side it does. ``-o<X>x<Y>`` moves the body, and zero is not written, so
  every id written before it still names the same part.
- A 2xN box header. ``hdr-2x8`` has the numbering and not the shroud: the courtyard is a
  pin wide where the real part is 9 mm, and there is no key slot -- which is the mark a
  ribbon cable's red stripe is lined up against.
"""

from __future__ import annotations

import pytest

from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import (
    GENERATED_ID_GRAMMAR,
    IDC_KEY_SLOT_MM,
    body_extent,
    box_header_footprint,
    footprint_lookup,
    generated_footprint,
    generic_box_footprint,
    get_footprint,
    pin_header_footprint,
    standard_footprints,
)
from perfboard_studio.geometry import transform_offset, turned_box
from perfboard_studio.guide import PHASE_BY_ARCHETYPE, _polarity_note
from perfboard_studio.model import (
    Board,
    ComponentInstance,
    DocumentMeta,
    HoleCoord,
    PerfDocument,
    Rotation,
)
from perfboard_studio.schematic import symbol_kind_for

LOOKUP = footprint_lookup()
#: The CAN transceiver breakout from the DELTA-ATLAS plaket: six pins along the top edge
#: of a 16 x 14.5 mm board, so the board's centre is 6 mm below the row of pins.
MODULE = "box-6x1-p1-r1-16x14.5x7-o0x6"


def _doc(*components: ComponentInstance, rows: int = 30) -> PerfDocument:
    board = Board(
        type="pad-per-hole", cols=30, rows=rows, pitch=2.54, thickness=1.6,
        material="FR4", pad_diameter=1.9, drill_diameter=1.0,
    )
    return PerfDocument(
        meta=DocumentMeta(name="t", created="", modified=""),
        board=board,
        components=components,
    )


def _part(ref: str, fp: str, col: int, row: int, rotation: Rotation = 0) -> ComponentInstance:
    return ComponentInstance(
        id=f"id-{ref}", ref=ref, value="", footprint_id=fp,
        anchor=HoleCoord(col, row), rotation=rotation,
    )


def _rules(doc: PerfDocument, rule: str) -> list[str]:
    return [v.message for v in run_drc(doc, LOOKUP) if v.rule == rule]


# ---------------------------------------------------------------------------
# The offset, in the grammar
# ---------------------------------------------------------------------------


def test_an_offset_body_has_one_spelling_and_zero_is_not_it() -> None:
    assert get_footprint(MODULE) is not None
    assert generic_box_footprint(
        cols=6, rows=1, width_mm=16, depth_mm=14.5, height_mm=7, offset_y_mm=6
    ).id == MODULE
    # Zero is the absence of the suffix: spelled out, it is a second name for one part.
    assert generated_footprint("box-6x1-p1-r1-16x14.5x7-o0x0") is None
    centred = get_footprint("box-6x1-p1-r1-16x14.5x7")
    assert centred is not None and "offsetX" not in centred.body.dims
    # Signed, at most two decimals, and bounded like every other millimetre in an id.
    assert get_footprint("box-6x1-p1-r1-16x14.5x7-o-1.25x6") is not None
    assert generated_footprint("box-6x1-p1-r1-16x14.5x7-o0x6.254") is None
    assert generated_footprint("box-6x1-p1-r1-16x14.5x7-o0x06") is None
    assert generated_footprint("box-6x1-p1-r1-16x14.5x7-o0x201") is None


def test_the_grammar_says_the_offset_and_the_box_header() -> None:
    """The one description of the grammar, which the MCP refusal and the docs read."""
    assert "-o<X>x<Y>" in GENERATED_ID_GRAMMAR
    assert "idc-2x<n>" in GENERATED_ID_GRAMMAR
    assert MODULE in GENERATED_ID_GRAMMAR


def test_the_offset_moves_the_body_and_the_courtyard_covers_it_and_the_pins() -> None:
    footprint = get_footprint(MODULE)
    assert footprint is not None
    extent = body_extent(footprint, 2.54)
    assert (extent.centre_x, extent.centre_y) == pytest.approx((6.35, 6.0))
    min_x, max_x, min_y, max_y = extent.box
    xs = [p.x for p in footprint.body_outline]
    ys = [p.y for p in footprint.body_outline]
    # The body is inside its courtyard...
    assert min(xs) <= min_x and max(xs) >= max_x
    assert min(ys) <= min_y and max(ys) >= max_y
    # ...and so is every pin, which sits on the body's top edge, not its centre.
    assert min(ys) < 0 < max(ys)
    # The side the body does NOT reach is not claimed: the courtyard stops half a pitch
    # past the pins there, where the centred 29 mm stand-in reached 14.5 mm.
    assert min(ys) == pytest.approx(-0.25 - 1.27 - 1.0, abs=0.3)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("mirrored", [False, True])
def test_the_offset_turns_with_the_part(rotation: Rotation, mirrored: bool) -> None:
    """The body stays where it is ON THE PART however the part is turned: its centre sits
    off the pins' centre by the offset, turned by exactly the transform the pins get --
    ``geometry.transform_offset``, the one rule both use."""
    footprint = get_footprint(MODULE)
    assert footprint is not None
    min_x, max_x, min_y, max_y = turned_box(body_extent(footprint, 2.54).box, rotation, mirrored)
    body_centre = ((min_x + max_x) / 2, (min_y + max_y) / 2)
    pins_centre = transform_offset(6.35, 0.0, rotation, mirrored)
    expected = transform_offset(6.35, 6.0, rotation, mirrored)
    assert body_centre == pytest.approx(expected)
    assert body_centre != pytest.approx(pins_centre)


def test_drc_sees_the_body_where_it_is_not_where_the_pins_are() -> None:
    """On the last row with the body reaching down, the module hangs off the board; turned
    half round it reaches up into the board and is clean. A centred body would have hung
    off by the same amount either way, which is what made the old stand-in wrong."""
    down = _doc(_part("U1", MODULE, 5, 29, 0))
    assert _rules(down, "component-overhangs-edge")
    up = _doc(_part("U1", MODULE, 10, 29, 180))
    assert not _rules(up, "component-overhangs-edge")


def test_overlap_is_measured_on_the_shifted_body() -> None:
    """Two modules whose pin rows are five holes apart: centred bodies 14.5 mm deep would
    already touch, shifted bodies reaching AWAY from each other do not -- and reaching
    TOWARDS each other they do."""
    apart = _doc(_part("U1", MODULE, 5, 10, 180), _part("U2", MODULE, 5, 15, 0))
    assert not _rules(apart, "component-body-overlap")
    towards = _doc(_part("U1", MODULE, 5, 10, 0), _part("U2", MODULE, 5, 15, 180))
    assert _rules(towards, "component-body-overlap")


# ---------------------------------------------------------------------------
# The IDC box header
# ---------------------------------------------------------------------------


def test_the_box_header_is_generated_not_shipped() -> None:
    """The registry is sixty-one parts and a golden fixture holds every one of them; a box
    header joins by id, so neither moves."""
    assert len(standard_footprints()) == 61
    assert not any(fp_id.startswith("idc-") for fp_id in standard_footprints())
    for per_row in (3, 5, 8, 20, 32):
        assert get_footprint(f"idc-2x{per_row}") is not None
    for bad in ("idc-2x2", "idc-2x33", "idc-1x8", "idc-2x08"):
        assert get_footprint(bad) is None


@pytest.mark.parametrize("per_row", [3, 5, 8, 20])
def test_the_box_header_is_numbered_exactly_as_the_pin_header_is(per_row: int) -> None:
    """A straight ribbon cable joins pin N to pin N only if both ends count the same way."""
    box = box_header_footprint(pins_per_row=per_row)
    plain = pin_header_footprint(rows=2, cols=per_row)
    assert [(p.number, p.d_col, p.d_row) for p in box.pins] == [
        (p.number, p.d_col, p.d_row) for p in plain.pins
    ]


def test_the_box_header_is_the_wurth_outline() -> None:
    """WR-BHD 61201621621 (2x8): pin to pin 17.78, length 27.98, 9.0 wide, 9.1 tall,
    4.5 mm key slot."""
    footprint = box_header_footprint(pins_per_row=8)
    assert footprint.body.archetype == "box-header"
    assert footprint.body.dims["length"] == pytest.approx(27.98)
    assert footprint.body.dims["width"] == pytest.approx(9.0)
    assert footprint.body_height == pytest.approx(9.1)
    assert footprint.body.dims["keySlot"] == IDC_KEY_SLOT_MM == 4.5
    extent = body_extent(footprint, 2.54)
    xs = [p.x for p in footprint.body_outline]
    ys = [p.y for p in footprint.body_outline]
    min_x, max_x, min_y, max_y = extent.box
    assert min(xs) <= min_x and max(xs) >= max_x and min(ys) <= min_y and max(ys) >= max_y


def test_the_box_header_is_a_connector_soldered_with_the_headers() -> None:
    footprint = box_header_footprint(pins_per_row=8)
    assert symbol_kind_for(footprint, 16) == "connector"
    assert PHASE_BY_ARCHETYPE["box-header"] == PHASE_BY_ARCHETYPE["pin-header"]


def test_the_guide_says_where_the_key_goes() -> None:
    """Soldered in half turned, the shroud takes the socket the wrong way round and every
    pin lands on its neighbour across the row."""
    footprint = box_header_footprint(pins_per_row=8)
    holes = tuple((p.number, HoleCoord(2 + p.d_col, 2 + p.d_row)) for p in footprint.pins)
    note = _polarity_note(footprint, holes)
    assert note is not None
    assert "Key slot" in note and "pin 1 in C3" in note and "red stripe" in note


def test_a_box_header_wants_the_edge_like_any_connector() -> None:
    from perfboard_studio.placer import EDGE_SEEKING_ARCHETYPES

    assert "box-header" in EDGE_SEEKING_ARCHETYPES
