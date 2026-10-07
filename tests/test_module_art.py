"""What stands on a module the 3D view knows by name, and the plug in a vertical terminal.

A module's id says how big its board is and how tall its tallest part stands, and nothing
about what the parts are; ``ui/moduleart.py`` draws them for the modules it recognises by
the part's VALUE. Everything here holds the picture to the facts the checker uses: the parts
stay on the module's board and under its ``top`` (the height DRC measures), they leave the
strip the module's pin names are printed in clear, they turn and flip with the part, and a
value or a board the layout was not drawn for keeps the plain block.
"""

from __future__ import annotations

import pytest

from perfboard_studio.footprints import MODULE_PCB_MM, get_footprint
from perfboard_studio.model import ComponentInstance, HoleCoord
from perfboard_studio.ui.bodies import PIN_NAME_HEIGHT_MM, pin_labels, placement_for
from perfboard_studio.ui.moduleart import (
    LM2596_MODULE,
    MODULE_ARTS,
    SN65HVD230_MODULE,
    fit_module_art,
    recognise_module,
)

#: The two modules of the first real board laid out with this program, as it has them.
BUCK = "mod-2x2-p16-r7-43.18x21.08x12-s5"
BUCK_NAMES = (("1", "IN+"), ("2", "OUT+"), ("3", "IN-"), ("4", "OUT-"))
CAN = "mod-6x1-p1-r1-16x14.5x3-s8.5-o0x6"
CAN_NAMES = (("1", "3V3"), ("2", "GND"), ("3", "CTX"), ("4", "CRX"), ("5", "CANH"), ("6", "CANL"))

PITCH = 2.54
TURNS = (0, 90, 180, 270)


def _part(
    footprint_id: str,
    value: str,
    names: tuple[tuple[str, str], ...] = (),
    rotation: int = 0,
    mirrored: bool = False,
) -> ComponentInstance:
    return ComponentInstance(
        id="part-1",
        ref="U1",
        value=value,
        footprint_id=footprint_id,
        anchor=HoleCoord(col=20, row=20),
        rotation=rotation,  # type: ignore[arg-type]
        mirrored=mirrored,
        pin_names=names,
    )


def _footprint(footprint_id: str):
    footprint = get_footprint(footprint_id)
    assert footprint is not None
    return footprint


# ---------------------------------------------------------------------- recognising one


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("LM2596S modülü (7,0 V'a ayarlı)", "lm2596"),
        ("lm2596 buck", "lm2596"),
        ("LM2596S-ADJ", "lm2596"),
        ("SN65HVD230 modülü", "sn65hvd230"),
        ("CJMCU-230", "sn65hvd230"),
        ("VP230 CAN", "sn65hvd230"),
    ],
)
def test_a_module_is_recognised_by_its_value(value: str, key: str) -> None:
    art = recognise_module(value)
    assert art is not None and art.key == key


@pytest.mark.parametrize("value", ["", "ESP32-DevKitC V4", "MP1584", "10k", "Module"])
def test_a_value_nobody_wrote_a_layout_for_is_not_guessed(value: str) -> None:
    assert recognise_module(value) is None


def test_the_plaket_modules_get_their_parts() -> None:
    buck = fit_module_art(_footprint(BUCK), _part(BUCK, "LM2596S modülü", BUCK_NAMES), PITCH)
    assert buck is not None
    assert sorted(part.kind for part in buck) == sorted(part.kind for part in LM2596_MODULE.parts)
    can = fit_module_art(_footprint(CAN), _part(CAN, "SN65HVD230 modülü", CAN_NAMES), PITCH)
    assert can is not None
    assert {part.kind for part in can} >= {"soic8", "chip-r", "chip-c"}


def test_a_layout_is_only_drawn_on_a_board_it_was_drawn_for() -> None:
    # Another shape of board: the layout would hang off it.
    square = "mod-2x2-p6-r6-20x20x12-s5"
    assert fit_module_art(_footprint(square), _part(square, "LM2596"), PITCH) is None
    # The right board with another number of pins.
    six = "mod-3x2-p8-r7-43.18x21.08x12-s5"
    assert fit_module_art(_footprint(six), _part(six, "LM2596"), PITCH) is None
    # A breakout's layout is for one row of pins along one edge.
    two_rows = "mod-3x2-p2-r5-16x14.5x3-s8.5"
    assert fit_module_art(_footprint(two_rows), _part(two_rows, "SN65HVD230"), PITCH) is None
    # Not a module at all.
    assert fit_module_art(_footprint("dip-8"), _part("dip-8", "LM2596"), PITCH) is None


def test_a_board_a_little_off_the_drawing_still_fits_and_stretches_the_layout() -> None:
    other = "mod-2x2-p16-r7-44x21.5x12-s5"
    placed = fit_module_art(_footprint(other), _part(other, "LM2596", BUCK_NAMES), PITCH)
    assert placed is not None


# ---------------------------------------------------------------------- what is drawn


def _rect(part) -> tuple[float, float, float, float]:
    return (
        part.x - part.size_x / 2,
        part.x + part.size_x / 2,
        part.y - part.size_y / 2,
        part.y + part.size_y / 2,
    )


def _cases():
    for art, footprint_id, names in (
        (LM2596_MODULE, BUCK, BUCK_NAMES),
        (SN65HVD230_MODULE, CAN, CAN_NAMES),
    ):
        for rotation in TURNS:
            for mirrored in (False, True):
                yield art, footprint_id, names, rotation, mirrored


def test_every_layout_is_tested() -> None:
    assert {art.key for art, *_ in _cases()} == {art.key for art in MODULE_ARTS}


@pytest.mark.parametrize(("art", "footprint_id", "names", "rotation", "mirrored"), list(_cases()))
def test_every_part_stands_on_the_module_and_under_its_top(
    art, footprint_id: str, names, rotation: int, mirrored: bool
) -> None:
    footprint = _footprint(footprint_id)
    placement = placement_for(footprint, PITCH)
    top = float(footprint.body.dims["top"])
    placed = fit_module_art(footprint, _part(footprint_id, art.names[0], names, rotation, mirrored), PITCH)
    assert placed is not None and len(placed) == len(art.parts)
    left = placement.centre_x - placement.size_x / 2
    right = placement.centre_x + placement.size_x / 2
    up = placement.centre_y - placement.size_y / 2
    down = placement.centre_y + placement.size_y / 2
    for part in placed:
        x0, x1, y0, y1 = _rect(part)
        assert left - 1e-9 <= x0 and x1 <= right + 1e-9, part
        assert up - 1e-9 <= y0 and y1 <= down + 1e-9, part
        assert 0 <= part.height <= top


def test_a_part_taller_than_the_id_says_is_cut_to_it() -> None:
    low = "mod-2x2-p16-r7-43.18x21.08x8-s5"
    placed = fit_module_art(_footprint(low), _part(low, "LM2596", BUCK_NAMES), PITCH)
    assert placed is not None
    assert max(part.height for part in placed) == 8
    assert sum(part.kind == "can" for part in placed) == 2


@pytest.mark.parametrize(("art", "footprint_id", "names", "rotation", "mirrored"), list(_cases()))
def test_the_layout_leaves_the_pin_names_clear(
    art, footprint_id: str, names, rotation: int, mirrored: bool
) -> None:
    """The names run in from each pin across the module's board (``bodies.pin_labels``),
    as far as the room they are given. No part may stand on that strip, or the silkscreen
    the module carries is printed under a capacitor."""
    footprint = _footprint(footprint_id)
    component = _part(footprint_id, art.names[0], names, rotation, mirrored)
    placed = fit_module_art(footprint, component, PITCH)
    assert placed is not None
    labels = pin_labels(footprint, component, PITCH)
    assert labels and all(label.on_module for label in labels)
    half = PIN_NAME_HEIGHT_MM / 2 + 0.2
    for label in labels:
        start, end = label.start, label.start + label.room
        xs = sorted((label.x + label.dx * start, label.x + label.dx * end))
        ys = sorted((label.y + label.dy * start, label.y + label.dy * end))
        strip = (
            xs[0] - (half if label.dx == 0 else 0),
            xs[1] + (half if label.dx == 0 else 0),
            ys[0] - (half if label.dy == 0 else 0),
            ys[1] + (half if label.dy == 0 else 0),
        )
        for part in placed:
            if part.kind == "silk":
                continue
            x0, x1, y0, y1 = _rect(part)
            overlaps = x0 < strip[1] and strip[0] < x1 and y0 < strip[3] and strip[2] < y1
            assert not overlaps, (label.name, part)


def test_the_regulator_is_at_the_end_the_input_pins_are() -> None:
    """Oriented by the pins' NAMES: a buck module described with IN on the right is drawn
    with its input can and regulator on the right."""
    footprint = _footprint(BUCK)
    centre = placement_for(footprint, PITCH).centre_x

    def regulator_x(names: tuple[tuple[str, str], ...]) -> float:
        placed = fit_module_art(footprint, _part(BUCK, "LM2596", names), PITCH)
        assert placed is not None
        return next(part.x for part in placed if part.kind == "to263")

    assert regulator_x(BUCK_NAMES) < centre
    swapped = (("1", "OUT+"), ("2", "IN+"), ("3", "OUT-"), ("4", "IN-"))
    assert regulator_x(swapped) > centre


def test_a_breakout_lies_away_from_its_header() -> None:
    """The chip sits on the board's side of the header, whichever side that is."""
    for footprint_id in (CAN, "mod-6x1-p1-r1-16x14.5x3-s8.5-o0x-6"):
        footprint = _footprint(footprint_id)
        placed = fit_module_art(footprint, _part(footprint_id, "SN65HVD230", CAN_NAMES), PITCH)
        assert placed is not None
        chip = next(part for part in placed if part.kind == "soic8")
        row_y = 0.0  # the header is the anchor's row
        centre_y = placement_for(footprint, PITCH).centre_y
        assert (chip.y - row_y) * (centre_y - row_y) > 0


# ---------------------------------------------------------------------- in 3D

vtk = pytest.importorskip("vtk")


def _board_and_pieces(footprint_id: str, value: str, names, rotation: int = 0, mirrored: bool = False):
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.mcp.session import new_board
    from perfboard_studio.ui import view3d

    board = new_board(cols=40, rows=40).board
    lookup = footprint_lookup()
    component = _part(footprint_id, value, names, rotation, mirrored)
    body = view3d._world_body(lookup, component, board)
    footprint = lookup(footprint_id)
    assert body is not None and footprint is not None
    return body, footprint, view3d._module_pieces(body, footprint, component, board)


def test_a_recognised_module_draws_its_parts_and_not_the_block() -> None:
    from perfboard_studio.ui import view3d

    _body, _fp, pieces = _board_and_pieces(BUCK, "LM2596S", BUCK_NAMES)
    assert not [piece for piece in pieces if piece.rgb == view3d._MODULE_BLOCK_RGB]
    _body, _fp, plain = _board_and_pieces(BUCK, "step-down module", BUCK_NAMES)
    assert len([piece for piece in plain if piece.rgb == view3d._MODULE_BLOCK_RGB]) == 1


@pytest.mark.parametrize("rotation", TURNS)
@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize(
    ("footprint_id", "value", "names"),
    [(BUCK, "LM2596S", BUCK_NAMES), (CAN, "SN65HVD230", CAN_NAMES)],
)
def test_what_is_drawn_stays_inside_the_envelope_drc_measures(
    footprint_id: str, value: str, names, rotation: int, mirrored: bool
) -> None:
    """Measured on the actors, as built: nothing past the module's board and nothing over
    the part's height but a mark standing its decal's tenth and a half proud."""
    from perfboard_studio.ui import view3d

    body, footprint, pieces = _board_and_pieces(footprint_id, value, names, rotation, mirrored)
    seat = float(footprint.body.dims["seat"])
    ceiling = footprint.body_height + view3d._DECAL_PROUD_MM + 1e-6
    for piece in pieces:
        x0, x1, y0, y1, z0, z1 = view3d._actor_for(piece).GetBounds()
        assert z1 <= ceiling, piece
        if z0 >= seat + MODULE_PCB_MM - 1e-6:  # on the module, not its pins or its posts
            assert body.x - body.size_x / 2 - 1e-6 <= x0 and x1 <= body.x + body.size_x / 2 + 1e-6
            assert body.y - body.size_y / 2 - 1e-6 <= y0 and y1 <= body.y + body.size_y / 2 + 1e-6


# ---------------------------------------------------------------------- a vertical terminal


@pytest.mark.parametrize("rotation", TURNS)
@pytest.mark.parametrize("mirrored", [False, True])
def test_a_vertical_terminals_screws_are_in_the_side_of_its_plug(rotation: int, mirrored: bool) -> None:
    """On a vertical header the plug stands on end: wires in from above, screws from the
    side -- the face ``VERTICAL_TERMINAL_SCREW_FACE`` names, turned with the part."""
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.geometry import transform_offset
    from perfboard_studio.mcp.session import new_board
    from perfboard_studio.ui import view3d

    board = new_board(cols=40, rows=40).board
    lookup = footprint_lookup()
    component = _part("screw-terminal-3-v", "", (), rotation, mirrored)
    body = view3d._world_body(lookup, component, board)
    assert body is not None and body.screws is not None
    fx, fy = transform_offset(*view3d.VERTICAL_TERMINAL_SCREW_FACE, rotation, mirrored)  # type: ignore[arg-type]
    assert body.screws == pytest.approx((fx, -fy))

    pieces = view3d._vertical_terminal_pieces(body)
    heads = [piece for piece in pieces if piece.rgb == view3d._rgb(body.style.accent)]
    assert len(heads) == 3
    nx, ny = body.screws
    for head, (pin_x, pin_y) in zip(heads, body.pins, strict=True):
        hx, hy, hz = head.position
        # Out on the screw face, level with its own pin, partway up the plug.
        assert (hx - pin_x) * nx + (hy - pin_y) * ny == pytest.approx(
            body.across / 2 + view3d._DECAL_PROUD_MM
        )
        assert abs((hx - pin_x) * ny - (hy - pin_y) * nx) < 1e-9
        assert view3d._VERTICAL_HEADER_HEIGHT_MM < hz < body.height

    # Everything inside the envelope but the marks standing proud of its faces.
    proud = view3d._DECAL_PROUD_MM + 0.3
    for piece in pieces:
        x0, x1, y0, y1, _z0, z1 = view3d._actor_for(piece).GetBounds()
        assert z1 <= body.height + view3d._LIFT + proud
        assert body.x - body.size_x / 2 - proud <= x0 and x1 <= body.x + body.size_x / 2 + proud
        assert body.y - body.size_y / 2 - proud <= y0 and y1 <= body.y + body.size_y / 2 + proud


def test_only_a_vertical_terminal_has_a_screw_face() -> None:
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.mcp.session import new_board
    from perfboard_studio.ui import view3d

    board = new_board(cols=40, rows=40).board
    lookup = footprint_lookup()
    for footprint_id in ("screw-terminal-3", "dip-8", BUCK):
        body = view3d._world_body(lookup, _part(footprint_id, ""), board)
        assert body is not None and body.screws is None
