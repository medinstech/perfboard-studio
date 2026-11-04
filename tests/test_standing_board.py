"""A module that stands on its edge (``moduleart.fit_standing_board``): the HC-SR04.

Its board stands up off this one on a right-angle header, the transducers looking out across
the board, so it is not a module lying on a seat: its footprint is the box it fills, and
what is drawn in that box is the board at the back of it with its parts out of its front.
Everything here holds the drawing to the box DRC measures: inside it at every turn and flip,
facing the way its pins are numbered for, and refused -- the plain box -- on a box the board
does not fit or one facing the other way, which would be the board's mirror image.
"""

from __future__ import annotations

import dataclasses

import pytest

from perfboard_studio.catalog import catalog_part
from perfboard_studio.footprints import body_extent, footprint_lookup, get_footprint
from perfboard_studio.model import ComponentInstance, HoleCoord
from perfboard_studio.ui.moduleart import HC_SR04_BOARD, fit_standing_board

PITCH = 2.54
HC_SR04 = "box-4x1-p1-r1-45x16x22.5-o0x6.8"
OLD_HC_SR04 = "box-4x1-p1-r1-45x15x22.5-o0x3.5"


def _part(footprint_id: str, value: str = "HC-SR04", rotation: int = 0, mirrored: bool = False):  # type: ignore[no-untyped-def]
    part = catalog_part("hc-sr04")
    assert part is not None
    return ComponentInstance(
        id="sonar", ref="U2", value=value, footprint_id=footprint_id, anchor=HoleCoord(col=20, row=20),
        rotation=rotation,  # type: ignore[arg-type]
        mirrored=mirrored, pin_names=part.pin_names,
    )


def _footprint(footprint_id: str):  # type: ignore[no-untyped-def]
    footprint = get_footprint(footprint_id)
    assert footprint is not None
    return footprint


def test_the_catalog_places_the_hc_sr04_on_the_box_its_board_fills() -> None:
    part = catalog_part("hc-sr04")
    assert part is not None and part.footprint_id == HC_SR04
    placed = fit_standing_board(_footprint(HC_SR04), _part(HC_SR04), PITCH)
    assert placed is not None
    _x0, _x1, y0, y1, _z0, _z1 = placed.board
    # The board stands just in front of the pins, the header's plastic behind them.
    assert y0 == pytest.approx(HC_SR04_BOARD.behind) and y1 == pytest.approx(y0 + 1.6)
    assert placed.header[2] < 0.0 < placed.header[3]
    cans = [p for p in placed.parts if p.kind == "transducer"]
    assert len(cans) == 2 and all(can.y0 == pytest.approx(y1) for can in cans)
    # The transmitter by VCC on the left, the receiver by GND on the right.
    assert cans[0].x < placed.pins[0] < placed.pins[-1] < cans[1].x


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("mirrored", [False, True])
def test_the_standing_board_stays_inside_the_box_drc_measures(rotation: int, mirrored: bool) -> None:
    """Measured on the actors, as built, at every turn and flip."""
    from perfboard_studio.mcp.session import new_board
    from perfboard_studio.ui import view3d

    board = new_board(cols=50, rows=50).board
    component = _part(HC_SR04, rotation=rotation, mirrored=mirrored)
    body = view3d._world_body(footprint_lookup(), component, board)
    placed = fit_standing_board(_footprint(HC_SR04), component, PITCH)
    assert body is not None and placed is not None
    pieces = view3d._standing_board_pieces(placed, component, board)
    assert pieces
    ceiling = _footprint(HC_SR04).body_height + 1e-6
    for piece in pieces:
        x0, x1, y0, y1, _z0, z1 = view3d._actor_for(piece).GetBounds()
        assert z1 <= ceiling, piece
        assert body.x - body.size_x / 2 - 1e-6 <= x0 and x1 <= body.x + body.size_x / 2 + 1e-6, piece
        assert body.y - body.size_y / 2 - 1e-6 <= y0 and y1 <= body.y + body.size_y / 2 + 1e-6, piece


def test_every_part_of_it_is_inside_the_footprints_box() -> None:
    footprint = _footprint(HC_SR04)
    placed = fit_standing_board(footprint, _part(HC_SR04), PITCH)
    assert placed is not None
    extent = body_extent(footprint, PITCH)
    left, right = extent.centre_x - extent.size_x / 2, extent.centre_x + extent.size_x / 2
    back, front = extent.centre_y - extent.size_y / 2, extent.centre_y + extent.size_y / 2
    tol = 1e-6
    for x0, x1, y0, y1, _z0, z1 in (placed.board, placed.header):
        assert left - tol <= x0 and x1 <= right + tol and back - tol <= y0 and y1 <= front + tol
        assert z1 <= footprint.body_height + tol
    for part in placed.parts:
        assert left - tol <= part.x - part.length / 2 and part.x + part.length / 2 <= right + tol
        assert back - tol <= part.y0 and part.y1 <= front + tol, part
        assert part.z + part.height / 2 <= footprint.body_height + tol, part


@pytest.mark.parametrize(
    ("footprint_id", "value"),
    [
        (HC_SR04, "ultrasonic sensor"),  # a value nobody wrote a layout for
        (OLD_HC_SR04, "HC-SR04"),  # the old box, 3.9 mm short in front
        ("box-4x1-p1-r1-45x16x22.5-o0x-6.8", "HC-SR04"),  # facing the other way: a mirror
        ("box-4x1-p1-r1-30x16x22.5-o0x6.8", "HC-SR04"),  # a board it is not
    ],
)
def test_a_box_the_board_does_not_fit_keeps_the_plain_box(footprint_id: str, value: str) -> None:
    assert fit_standing_board(_footprint(footprint_id), _part(footprint_id, value), PITCH) is None


def test_it_is_drawn_in_2d_as_the_standing_board_and_not_the_box() -> None:
    """The window's own item for the part carries the board, and paints without the box."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["perfboard-studio-tests"])
    assert app is not None
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.model import DocumentMeta, PerfDocument
    from perfboard_studio.ui.view2d import BoardScene, ComponentItem

    board = dataclasses.replace(DEFAULT_BOARD, cols=30, rows=20)
    component = dataclasses.replace(_part(HC_SR04), anchor=HoleCoord(col=10, row=4))
    doc = PerfDocument(meta=DocumentMeta(name="s", created="", modified=""), board=board, components=(component,))
    scene = BoardScene(doc, footprint_lookup(), side="top", show_ratsnest=False, show_rulers=False)
    items = [item for item in scene.items() if isinstance(item, ComponentItem)]
    assert len(items) == 1 and items[0].standing is not None
