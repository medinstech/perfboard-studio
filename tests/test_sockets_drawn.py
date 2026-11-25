"""Female headers and right-angle strips, drawn as what they are: a socket is all plastic
with a mouth over every pin, and a right-angle part is gold legs bent over, a moulding on
its side, and -- for a header -- pins on out past it. One rectangle to DRC, three things to
the eye (``bodies.RightAngle``)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from perfboard_studio.footprints import body_extent, footprint_lookup, get_footprint
from perfboard_studio.model import Board, ComponentInstance, DocumentMeta, HoleCoord, PerfDocument
from perfboard_studio.ui import view2d
from perfboard_studio.ui.bodies import placement_for, right_angle_for

PITCH = 2.54
RIGHT_ANGLED = ("hdr-1x6-ra", "hdr-2x5-ra", "skt-1x6-ra", "skt-2x5-ra")


@pytest.fixture(scope="module", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication(["perfboard-studio-tests"])


# --- where a right-angle part lies -------------------------------------------------------


def test_a_right_angle_header_lies_past_its_last_row() -> None:
    angle = right_angle_for(get_footprint("hdr-2x5-ra"), PITCH)
    assert angle is not None
    assert angle.rows == (0.0, PITCH)
    assert angle.near == pytest.approx(PITCH + 1.5)
    assert angle.far == pytest.approx(PITCH + 4.04)
    assert angle.reach == pytest.approx(PITCH + 10.04)
    assert angle.left == pytest.approx(-PITCH / 2)
    assert angle.right == pytest.approx(4 * PITCH + PITCH / 2)
    assert not angle.socket


def test_a_right_angle_socket_ends_at_its_far_face() -> None:
    angle = right_angle_for(get_footprint("skt-1x6-ra"), PITCH)
    assert angle is not None and angle.socket
    assert angle.reach == pytest.approx(angle.far)


@pytest.mark.parametrize("footprint_id", ("hdr-1x6", "skt-1x6", "skt-2x5", "dip-8"))
def test_a_part_that_stands_up_is_not_right_angled(footprint_id: str) -> None:
    assert right_angle_for(get_footprint(footprint_id), PITCH) is None


@pytest.mark.parametrize("footprint_id", RIGHT_ANGLED)
@pytest.mark.parametrize("pitch", (2.54, 2.0))
def test_what_is_drawn_is_inside_the_body_drc_measures(footprint_id: str, pitch: float) -> None:
    footprint = get_footprint(footprint_id)
    angle = right_angle_for(footprint, pitch)
    assert angle is not None
    extent = body_extent(footprint, pitch)
    top = extent.centre_y - extent.size_y / 2
    bottom = extent.centre_y + extent.size_y / 2
    left = extent.centre_x - extent.size_x / 2
    right = extent.centre_x + extent.size_x / 2
    assert left - 1e-6 <= angle.left and angle.right <= right + 1e-6
    assert top - 1e-6 <= angle.rows[0] - pitch / 2
    assert angle.reach <= bottom + 1e-6
    assert angle.rows[-1] < angle.near < angle.far <= angle.reach


# --- 2D ---------------------------------------------------------------------------------


@pytest.mark.parametrize("footprint_id", RIGHT_ANGLED)
def test_the_2d_body_is_the_moulding_not_the_whole_reach(footprint_id: str) -> None:
    footprint = get_footprint(footprint_id)
    angle = right_angle_for(footprint, PITCH)
    assert angle is not None
    path = view2d._body_path(footprint, placement_for(footprint, PITCH), None, PITCH)
    box = path.boundingRect()
    assert box.top() == pytest.approx(angle.near)
    assert box.bottom() == pytest.approx(angle.far)
    assert box.left() == pytest.approx(angle.left)
    assert box.right() == pytest.approx(angle.right)
    # The holes are not under black plastic: the legs over them are drawn as gold.
    for row in angle.rows:
        assert not path.contains(QPointF(0.0, row))


SCALE = 20.0  # px per mm
GOLD = QColor("#d4af37")


def _painted(paint) -> QImage:  # type: ignore[no-untyped-def]
    image = QImage(400, 400, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.translate(100, 100)
    painter.scale(SCALE, SCALE)
    paint(painter)
    painter.end()
    return image


def _at(image: QImage, x_mm: float, y_mm: float) -> QColor:
    return image.pixelColor(int(100 + x_mm * SCALE), int(100 + y_mm * SCALE))


def test_a_socket_has_a_dark_mouth_over_every_pin() -> None:
    footprint = get_footprint("skt-2x5")
    image = _painted(lambda p: view2d._paint_socket_mouths(p, footprint, PITCH, GOLD))
    edge = view2d.SOCKET_MOUTH_MM * 0.4
    for pin in footprint.pins:
        x, y = pin.d_col * PITCH, pin.d_row * PITCH
        assert _at(image, x + edge, y).lightness() < 80, pin  # the mouth
        assert _at(image, x, y).red() > _at(image, x, y).blue()  # the contact, gold
    assert _at(image, PITCH / 2, 0.0).lightness() == 255  # between two mouths, nothing


@pytest.mark.parametrize("footprint_id", ("hdr-1x6-ra", "skt-1x6-ra"))
def test_the_legs_are_gold_and_only_a_header_has_tips(footprint_id: str) -> None:
    footprint = get_footprint(footprint_id)
    angle = right_angle_for(footprint, PITCH)
    assert angle is not None
    image = _painted(lambda p: view2d._paint_right_angle_pins(p, footprint, angle, PITCH, GOLD))
    leg = _at(image, 0.0, (angle.rows[-1] + angle.near) / 2)
    assert leg.name() == GOLD.name()
    tip = _at(image, 0.0, angle.far + 1.0)
    if angle.socket:
        assert tip.lightness() == 255
    else:
        assert tip.name() == GOLD.name()


# --- 3D ---------------------------------------------------------------------------------

BOARD = Board(
    type="pad-per-hole",
    cols=40,
    rows=30,
    pitch=PITCH,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.9,
    drill_diameter=1.0,
)


def _pieces(footprint_id: str, rotation: int = 0, mirrored: bool = False):  # type: ignore[no-untyped-def]
    pytest.importorskip("vtk")
    from perfboard_studio.ui import view3d

    component = ComponentInstance(
        id="cmp-1",
        ref="J1",
        value="",
        footprint_id=footprint_id,
        anchor=HoleCoord(12, 12),
        rotation=rotation,  # type: ignore[arg-type]
        mirrored=mirrored,
    )
    document = PerfDocument(
        meta=DocumentMeta(name="t", created="", modified=""), board=BOARD, components=(component,)
    )
    body = view3d._world_body(footprint_lookup(), component, document.board)
    assert body is not None
    footprint = get_footprint(footprint_id)
    return view3d, body, view3d._pieces_for(body, footprint, component, document.board)


def test_a_socket_is_plastic_the_whole_height_with_a_mouth_on_every_pin() -> None:
    view3d, body, pieces = _pieces("skt-2x5")
    moulded = [p for p in pieces if p.material is view3d.MOULDED and not p.instances]
    assert len(moulded) == 1
    assert moulded[0].position[2] == pytest.approx(body.height / 2 + view3d._LIFT)
    mouths = [p for p in pieces if p.material is view3d.MOULDED and p.instances]
    assert mouths and len(mouths[0].instances) == len(body.pins)
    for z in {round(i[2], 6) for i in mouths[0].instances}:
        assert z > body.height  # on top of the plastic, not inside it


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
@pytest.mark.parametrize("mirrored", (False, True))
def test_a_right_angle_part_lies_away_from_its_pins_however_it_is_turned(
    rotation: int, mirrored: bool
) -> None:
    view3d, body, pieces = _pieces("hdr-2x5-ra", rotation, mirrored)
    ux, uy = view3d.right_angle_direction(body)
    mid_x = sum(x for x, _ in body.pins) / len(body.pins)
    mid_y = sum(y for _, y in body.pins) / len(body.pins)
    # The body DRC measures is on that side of the pins...
    assert (body.x - mid_x) * ux + (body.y - mid_y) * uy > 0
    # ...and so is the moulding that is built.
    moulding = next(p for p in pieces if p.material is view3d.MOULDED and not p.instances)
    assert (moulding.position[0] - mid_x) * ux + (moulding.position[1] - mid_y) * uy > PITCH


def test_a_two_row_right_angle_part_bends_each_row_at_its_own_level() -> None:
    view3d, _body, pieces = _pieces("hdr-2x5-ra")
    gold = [p for p in pieces if p.material is view3d.PLATED and p.instances]
    levels = {round(i[2], 3) for p in gold for i in p.instances if i[2] > view3d._LIFT + 0.5}
    # Two horizontal bars' levels, and the two legs' midpoints: four heights in all.
    assert len(levels) >= 3


def test_only_a_right_angle_socket_has_mouths_on_its_far_face() -> None:
    _view3d, _body, socket = _pieces("skt-1x6-ra")
    _view3d, _body, header = _pieces("hdr-1x6-ra")
    dark = (0.02, 0.02, 0.025)
    assert any(p.rgb == dark for p in socket)
    assert not any(p.rgb == dark for p in header)


# --- icons ------------------------------------------------------------------------------


def test_a_socket_and_the_right_angle_strips_each_have_their_own_picture() -> None:
    from perfboard_studio.ui.icons import PART_SIZE, part_icon

    ids = ("hdr-1x6", "skt-1x6", "hdr-1x6-ra", "skt-1x6-ra")
    images = [part_icon(get_footprint(i)).pixmap(PART_SIZE, PART_SIZE).toImage() for i in ids]
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            assert images[a] != images[b], (ids[a], ids[b])


# --- a cable on a right-angle part ------------------------------------------------------


def _cabled(a: str, b: str):  # type: ignore[no-untyped-def]
    """The System of ``test_system_readers``, its two headers swapped for ``a`` and ``b``."""
    import dataclasses

    from .test_system_readers import _system

    doc = _system()
    ja = dataclasses.replace(doc.components[0], footprint_id=a)
    remote = doc.boards[0]
    jb = dataclasses.replace(remote.components[0], footprint_id=b)
    return dataclasses.replace(
        doc,
        components=(ja, *doc.components[1:]),
        boards=(dataclasses.replace(remote, components=(jb, *remote.components[1:])),),
    )


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
def test_a_cable_leaves_a_right_angle_part_sideways_out_of_its_far_face(rotation: int) -> None:
    pytest.importorskip("vtk")
    import dataclasses

    from perfboard_studio import system
    from perfboard_studio.ui import view3d

    doc = _cabled("hdr-1x2-ra", "skt-1x2-ra")
    doc = dataclasses.replace(
        doc, components=(dataclasses.replace(doc.components[0], rotation=rotation), *doc.components[1:])
    )
    lookup = footprint_lookup()
    offsets = view3d._world_offsets(doc)
    for end, female in ((doc.cables[0].a, False), (doc.cables[0].b, True)):
        found = view3d._sockets(doc, lookup, end, offsets, 0.0)
        assert found is not None
        _ref, sockets = found
        part = view3d.connector_of(doc, end)
        assert part is not None
        board = system.board_document(doc, end.board).board
        body = view3d._world_body(lookup, part, board)
        assert body is not None
        ux, uy = view3d.right_angle_direction(body)
        dx, dy = offsets[end.board]
        edge = (body.x + dx) * ux + (body.y + dy) * uy + (body.size_x * abs(ux) + body.size_y * abs(uy)) / 2
        assert len(sockets) == 2
        for socket in sockets.values():
            assert socket.out == (ux, uy, 0.0)
            assert socket.at[2] < body.height + view3d._LIFT  # beside the moulding, not on it
            along = socket.at[0] * ux + socket.at[1] * uy
            if female:
                assert socket.shell is None
                assert along == pytest.approx(edge)  # in the mouth, on the far face
            else:
                assert socket.shell is not None
                assert along > edge  # the shell lies over the pin, out past its tip
    assert len(view3d.build_cables(doc, lookup)) == 2 + 2  # two wires, a shell on each header pin
