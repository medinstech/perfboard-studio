"""What stands on a module the 3D view knows by name, and the plug in a vertical terminal.

A module's id says how big its board is and how tall its tallest part stands, and nothing
about what the parts are; ``ui/moduleart.py`` draws them for the modules it recognises by
the part's VALUE -- the two of the first real board, and the five the catalog offers.
Everything here holds the picture to the facts the checker uses: the parts stay on the
module's board and under its ``top`` (the height DRC measures), the module's pin names stop
short of them and are still left room to be read, they turn and flip with the part, and a
value or a board the layout was not drawn for keeps the plain block.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from perfboard_studio.catalog import CATALOG
from perfboard_studio.footprints import MODULE_PCB_MM, get_footprint
from perfboard_studio.model import ComponentInstance, HoleCoord
from perfboard_studio.ui.bodies import (
    PIN_NAME_HEIGHT_MM,
    PIN_NAME_MIN_SQUEEZE,
    pin_labels,
    placement_for,
)
from perfboard_studio.ui.moduleart import (
    LM2596_MODULE,
    MODULE_ARTS,
    NAME_ROOM_ENOUGH_MM,
    NANO_MODULE,
    SN65HVD230_MODULE,
    SPARKFUN_RED,
    TQFP32_BODY_MM,
    TQFP32_LEG_MM,
    TQFP32_LEGS_PER_SIDE,
    TQFP32_PITCH_MM,
    fit_module_art,
    outline,
    recognise_module,
)

#: The two modules of the first real board laid out with this program, as it has them.
BUCK = "mod-2x2-p16-r7-43.18x21.08x12-s5"
BUCK_NAMES = (("1", "IN+"), ("2", "OUT+"), ("3", "IN-"), ("4", "OUT-"))
CAN = "mod-6x1-p1-r1-16x14.5x3-s8.5-o0x6"
CAN_NAMES = (("1", "3V3"), ("2", "GND"), ("3", "CTX"), ("4", "CRX"), ("5", "CANH"), ("6", "CANL"))

#: Catalog modules drawn as the plain block ON PURPOSE, each with the reason. A layout is
#: measured from a drawing of what is on the board, and a layout guessed from a seller's
#: photograph would be a picture of parts that may not be there; the block claims nothing.
#: ``test_a_module_drawn_as_the_block_is_one_on_purpose`` fails if one of these gains a
#: layout, so the reason cannot outlive the fact, or leaves the catalog.
DRAWN_AS_THE_BLOCK: dict[str, str] = {
    "nrf24l01": (
        "no maker drawing exists; drawn as the envelope block, which claims nothing about the "
        "parts on it"
    ),
    "esp-01": (
        "no drawing of the parts on it exists, only Ai-Thinker's of its pins and board; drawn "
        "as the envelope block, which claims nothing about the parts on it"
    ),
}

#: The catalog's modules that are drawn as themselves, as choosing one places it: its
#: footprint, value and pin names.
CATALOG_MODULES = tuple(
    part for part in CATALOG if part.category == "module" and part.id not in DRAWN_AS_THE_BLOCK
)

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
        ("LM2596S modülü (7,0 V'a ayarlı)", "lm2596-module"),
        ("lm2596 buck", "lm2596-module"),
        ("LM2596S-ADJ", "lm2596-module"),
        ("SN65HVD230 modülü", "sn65hvd230"),
        ("CJMCU-230", "sn65hvd230"),
        ("VP230 CAN", "sn65hvd230"),
        ("ESP32 DevKitC (38 pin)", "esp32-devkitc"),
        ("ESP32-C3-DevKitM-1", "esp32-c3-devkitm-1"),
        ("Arduino_Nano_v3.x", "arduino-nano"),  # KiCad's symbol, which a netlist brings
        ("NANO V3.0 CH340", "arduino-nano"),
        ("Raspberry Pi Pico H", "raspberry-pi-pico"),
        ("D1 mini", "wemos-d1-mini"),
        ("Pololu A4988", "pololu-a4988"),
        ("Pololu DRV8825", "pololu-drv8825"),
        ("SparkFun TB6612FNG", "sparkfun-tb6612fng"),
        ("Pololu DRV8833", "pololu-drv8833"),
        ("Seeed XIAO ESP32C3", "seeed-xiao-esp32c3"),
        ("XIAO-ESP32C3", "seeed-xiao-esp32c3"),
    ],
)
def test_a_module_is_recognised_by_its_value(value: str, key: str) -> None:
    art = recognise_module(value)
    assert art is not None and art.key == key


@pytest.mark.parametrize(
    "value",
    [
        "",
        "MP1584",
        "10k",
        "Module",
        # The same footprint as one with a layout, and other parts on it.
        "Arduino Nano Every",
        "Arduino Nano 33 IoT",
        "Raspberry Pi Pico W",
        "Raspberry Pi Pico 2",
        "ESP32-S3-DevKitC-1",
        "ESP32-DevKitC-VE",
        "LOLIN D1 mini Pro",
        # Same pins, another board: the StepStick clones are not Pololu's layout.
        "A4988",
        "A4988 StepStick",
        "DRV8825",
        # The other XIAO boards share the footprint and not the parts.
        "XIAO ESP32S3",
        "XIAO RP2040",
    ],
)
def test_a_value_nobody_wrote_a_layout_for_is_not_guessed(value: str) -> None:
    assert recognise_module(value) is None


@pytest.mark.parametrize("part", CATALOG_MODULES, ids=lambda part: part.id)
def test_every_catalog_module_is_drawn_as_what_is_on_it(part) -> None:
    """Chosen from the catalog, a module is drawn as itself and not as the block: the one
    place a person picks a module by name is the one place it must be recognised."""
    art = recognise_module(part.placed_value)
    assert art is not None and art.key == part.id
    placed = fit_module_art(
        _footprint(part.footprint_id), _part(part.footprint_id, part.placed_value, part.pin_names), PITCH
    )
    assert placed is not None and len(placed) == len(art.parts)


def test_a_module_drawn_as_the_block_is_one_on_purpose() -> None:
    """Every exception is a catalog module, has its reason, and really is drawn as the block:
    a layout written for one later means the exception has to go, and says so here."""
    from perfboard_studio.ui import view3d

    modules = {part.id: part for part in CATALOG if part.category == "module"}
    assert set(DRAWN_AS_THE_BLOCK) <= set(modules), "an exception the catalog no longer has"
    for part_id, why in DRAWN_AS_THE_BLOCK.items():
        part = modules[part_id]
        assert why.strip(), part_id
        assert recognise_module(part.placed_value) is None, f"{part_id} has a layout now"
        _body, _fp, pieces = _board_and_pieces(part.footprint_id, part.placed_value, part.pin_names)
        assert len([piece for piece in pieces if piece.rgb == view3d._MODULE_BLOCK_RGB]) == 1


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


def _layouts():
    """Every layout on the footprint it was drawn for, with the names that part carries."""
    yield LM2596_MODULE, BUCK, BUCK_NAMES
    yield SN65HVD230_MODULE, CAN, CAN_NAMES
    for part in CATALOG_MODULES:
        art = recognise_module(part.placed_value)
        assert art is not None
        yield art, part.footprint_id, part.pin_names


def _cases():
    for art, footprint_id, names in _layouts():
        for rotation in TURNS:
            for mirrored in (False, True):
                yield art, footprint_id, names, rotation, mirrored


def _case_id(value) -> str:
    return value.key if hasattr(value, "key") else ""


def _bounds(part) -> tuple[float, float, float, float]:
    """What a placed part covers, as ``(x0, x1, y0, y1)``: its outline's box."""
    points = outline(part)
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return min(xs), max(xs), min(ys), max(ys)


def _polygon_meets_box(points, box) -> bool:
    """Whether a convex polygon and an axis-aligned box share any area -- separating axes,
    written here rather than borrowed from ``moduleart`` so the two are checked against
    each other and not against themselves."""
    x0, x1, y0, y1 = box
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    axes = [(1.0, 0.0), (0.0, 1.0)]
    for (ax, ay), (bx, by) in zip(points, (*points[1:], points[0]), strict=True):
        axes.append((ay - by, bx - ax))
    for nx, ny in axes:
        a = [x * nx + y * ny for x, y in points]
        b = [x * nx + y * ny for x, y in corners]
        if max(a) <= min(b) + 1e-9 or max(b) <= min(a) + 1e-9:
            return False
    return True


def test_every_layout_is_tested() -> None:
    assert {art.key for art, *_ in _cases()} == {art.key for art in MODULE_ARTS}


@pytest.mark.parametrize(
    ("art", "footprint_id", "names", "rotation", "mirrored"), list(_cases()), ids=_case_id
)
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
        x0, x1, y0, y1 = _bounds(part)
        assert left - 1e-9 <= x0 and x1 <= right + 1e-9, part
        assert up - 1e-9 <= y0 and y1 <= down + 1e-9, part
        assert 0 <= part.height <= top


@pytest.mark.parametrize(("art", "footprint_id", "names"), list(_layouts()), ids=_case_id)
def test_no_two_parts_on_a_module_stand_in_one_place(art, footprint_id: str, names) -> None:
    placed = fit_module_art(_footprint(footprint_id), _part(footprint_id, art.names[0], names), PITCH)
    assert placed is not None
    solid = [part for part in placed if part.kind != "silk"]
    for index, part in enumerate(solid):
        for other in solid[index + 1 :]:
            # A part that is not turned is its own box, so measuring the turned one against
            # it is exact.
            turned, square = (other, part) if other.diagonal else (part, other)
            assert not _polygon_meets_box(outline(turned), _bounds(square)), (part, other)


def test_a_part_taller_than_the_id_says_is_cut_to_it() -> None:
    low = "mod-2x2-p16-r7-43.18x21.08x8-s5"
    placed = fit_module_art(_footprint(low), _part(low, "LM2596", BUCK_NAMES), PITCH)
    assert placed is not None
    assert max(part.height for part in placed) == 8
    assert sum(part.kind == "can" for part in placed) == 2


def _strip(label) -> tuple[float, float, float, float]:
    """The strip a module's pin name is printed in: from its start to its room, its letters
    high and a fifth of a millimetre either side."""
    half = PIN_NAME_HEIGHT_MM / 2 + 0.2
    start, end = label.start, label.start + label.room
    xs = sorted((label.x + label.dx * start, label.x + label.dx * end))
    ys = sorted((label.y + label.dy * start, label.y + label.dy * end))
    return (
        xs[0] - (half if label.dx == 0 else 0),
        xs[1] + (half if label.dx == 0 else 0),
        ys[0] - (half if label.dy == 0 else 0),
        ys[1] + (half if label.dy == 0 else 0),
    )


@pytest.mark.parametrize(
    ("art", "footprint_id", "names", "rotation", "mirrored"), list(_cases()), ids=_case_id
)
def test_the_layout_leaves_the_pin_names_clear(
    art, footprint_id: str, names, rotation: int, mirrored: bool
) -> None:
    """The names run in from each pin across the module's board (``bodies.pin_labels``),
    as far as the room they are given. No part may stand on that strip, or the silkscreen
    the module carries is printed under a capacitor -- the turned chip of a Nano measured as
    the shape it is, which is not its box."""
    footprint = _footprint(footprint_id)
    component = _part(footprint_id, art.names[0], names, rotation, mirrored)
    placed = fit_module_art(footprint, component, PITCH)
    assert placed is not None
    labels = pin_labels(footprint, component, PITCH)
    assert labels and all(label.on_module for label in labels)
    for label in labels:
        if label.backed:
            # Printed over the parts on its own tag, by the layout's own say-so: the next
            # test holds that to the layouts that ask for it.
            continue
        strip = _strip(label)
        for part in placed:
            if part.kind == "silk":
                continue
            assert not _polygon_meets_box(outline(part), strip), (label.name, part)


#: How wide a pin name is printed, per letter, at its full width -- generous for a sans
#: face, which is what the views print in, so the test fails before a view squeezes harder.
LETTER_MM = 0.6 * PIN_NAME_HEIGHT_MM


@pytest.mark.parametrize(("art", "footprint_id", "names"), list(_layouts()), ids=_case_id)
def test_every_name_on_a_module_is_left_room_to_be_read(art, footprint_id: str, names) -> None:
    """Stopping a name at the first part in its way only helps if what is left can be read:
    each is printed no narrower than the views print a name anywhere, or is given
    ``NAME_ROOM_ENOUGH_MM`` where its name is long -- which is how a real devkit's
    silkscreen is printed too, small beside its pins."""
    footprint = _footprint(footprint_id)
    component = _part(footprint_id, art.names[0], names)
    for label in pin_labels(footprint, component, PITCH):
        wanted = PIN_NAME_MIN_SQUEEZE * LETTER_MM * len(label.name)
        assert label.room >= min(wanted, NAME_ROOM_ENOUGH_MM) - 1e-9, label


def test_a_layout_drawn_round_the_names_leaves_them_as_they_were() -> None:
    """The room a name is given changes only where a part stands in it: the two modules of
    the first real board, whose layouts were drawn round the strip, print every name as the
    plain block does."""
    for footprint_id, names, value in ((BUCK, BUCK_NAMES, "LM2596S"), (CAN, CAN_NAMES, "SN65HVD230")):
        footprint = _footprint(footprint_id)
        drawn = pin_labels(footprint, _part(footprint_id, value, names), PITCH)
        plain = pin_labels(footprint, _part(footprint_id, "a module", names), PITCH)
        assert drawn == plain


@pytest.mark.parametrize(("art", "footprint_id", "names"), list(_layouts()), ids=_case_id)
def test_names_go_over_the_parts_only_where_the_real_board_leaves_them_no_room(
    art, footprint_id: str, names
) -> None:
    """A layout that says its real parts stand where the names go has every name printed
    over them on a tag, at the length a plain block would give it -- and no other layout has
    one name so, because elsewhere a name stops at the first part in its way."""
    footprint = _footprint(footprint_id)
    drawn = pin_labels(footprint, _part(footprint_id, art.names[0], names), PITCH)
    assert {label.backed for label in drawn} == {art.names_over_parts}
    if art.names_over_parts:
        plain = pin_labels(footprint, _part(footprint_id, "a module", names), PITCH)
        assert [dataclasses.replace(label, backed=False) for label in drawn] == list(plain)


def test_a_name_over_the_parts_is_only_ever_on_a_module() -> None:
    """The tag is for a module whose parts cover its names: a part on this board prints its
    names beside it, on the tag it always had, and nothing about that is a backed name."""
    from perfboard_studio.catalog import catalog_part

    dht = catalog_part("dht22")
    assert dht is not None
    footprint = _footprint(dht.footprint_id)
    labels = pin_labels(footprint, _part(dht.footprint_id, dht.placed_value, dht.pin_names), PITCH)
    assert labels and not any(label.backed or label.on_module for label in labels)


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


NANO = next(part for part in CATALOG_MODULES if part.id == "arduino-nano")


def _nano_usb_y(names: tuple[tuple[str, str], ...]) -> float:
    """Where a Nano described with these pin names has its USB socket, down the rows."""
    placed = fit_module_art(
        _footprint(NANO.footprint_id), _part(NANO.footprint_id, "Arduino Nano", names), PITCH
    )
    assert placed is not None
    return next(part.y for part in placed if part.kind == "usb")


def test_a_devkit_described_from_its_other_end_is_turned_by_its_names() -> None:
    """A two-column module is drawn so its landmark pin is where the layout has it: a Nano
    whose names run the other way down its columns still has its socket at the D13 end,
    and one whose pins carry no names is drawn as the catalog lays it out."""
    centre_y = placement_for(_footprint(NANO.footprint_id), PITCH).centre_y
    unnamed = _nano_usb_y(())
    assert unnamed > centre_y  # as the catalog has it: USB at the bottom, by D12 and D13
    assert _nano_usb_y(NANO.pin_names) == pytest.approx(unnamed)

    # The same names numbered from the other end: pin 1 is now in D12's hole.
    rows = len(NANO.pin_names) // 2
    names = dict(NANO.pin_names)
    from_the_other_end = tuple(
        (str(2 * row + column + 1), names[str(2 * (rows - 1 - row) + column + 1)])
        for row in range(rows)
        for column in (0, 1)
    )
    assert _nano_usb_y(from_the_other_end) < centre_y


def test_a_nanos_chip_stands_on_its_corner() -> None:
    """Turned an eighth, with its legs stopping short of its corners: the shape the pin
    names stop at is the chip's, reaching out exactly as far as its corner legs do."""
    assert any(part.kind == "tqfp32" and part.diagonal for part in NANO_MODULE.parts)
    placed = fit_module_art(
        _footprint(NANO.footprint_id), _part(NANO.footprint_id, "Arduino Nano"), PITCH
    )
    assert placed is not None
    chip = next(part for part in placed if part.kind == "tqfp32")
    assert chip.diagonal
    points = outline(chip)
    assert len(points) == 8
    leg_reach = (TQFP32_LEGS_PER_SIDE - 1) / 2 * TQFP32_PITCH_MM + TQFP32_LEG_MM / 2
    corner_reach = (chip.size_x / 2 + leg_reach) * math.sqrt(0.5)
    assert max(abs(x - chip.x) for x, _y in points) == pytest.approx(corner_reach)
    assert max(abs(y - chip.y) for _x, y in points) == pytest.approx(corner_reach)


# ---------------------------------------------------------------------- in 2D


def _qt_app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _render_part(part_id: str):
    """One catalog module drawn by the 2D view alone, and what places its own frame in the
    picture. The scene is handed back too: the item dies with it."""
    _qt_app()
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QGraphicsScene

    from perfboard_studio.mcp.session import new_board
    from perfboard_studio.ui.view2d import ComponentItem

    part = next(p for p in CATALOG_MODULES if p.id == part_id)
    board = new_board(cols=40, rows=40).board
    component = _part(part.footprint_id, part.placed_value, part.pin_names)
    item = ComponentItem(component, _footprint(part.footprint_id), board, "top")
    scene = QGraphicsScene()
    scene.addItem(item)
    source = item.sceneBoundingRect()
    scale = 12.0
    image = QImage(int(source.width() * scale), int(source.height() * scale), QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), source)
    painter.end()
    return image, item, source, scale, component, scene


def _pixel_at(image, item, source, scale, component, x_mm: float, y_mm: float):
    from PySide6.QtCore import QPointF

    from perfboard_studio.ui.view2d import _local_offset_mm

    point = item.mapToScene(QPointF(*_local_offset_mm(x_mm, y_mm, component, "top")))
    return image.pixelColor(
        int((point.x() - source.left()) * scale), int((point.y() - source.top()) * scale)
    )


def test_the_2d_view_draws_what_is_on_a_recognised_module() -> None:
    """The block said nothing about which way round a module was, and the pin names stopped
    short of parts the 2D view did not show. A recognised module is its parts from above, in
    the colours the 3D view paints with (``ART_COLOURS``): the WROOM's steel can where the
    can is, and the board bare where nothing stands -- not the block across its middle."""
    from perfboard_studio.ui.moduleart import ART_COLOURS

    image, item, source, scale, component, _scene = _render_part("esp32-devkitc")
    assert item.art is not None
    can = next(part for part in item.art if part.kind == "rf-module")
    # The can's middle: from the far end's inset to where the antenna starts, along y.
    along = can.facing * (can.inset - can.antenna) / 2
    shield = _pixel_at(image, item, source, scale, component, can.x, can.y + along)
    expected = ART_COLOURS["shield"]
    assert (shield.red(), shield.green(), shield.blue()) == pytest.approx(
        (int(expected[1:3], 16), int(expected[3:5], 16), int(expected[5:7], 16)), abs=6
    )
    placement = placement_for(_footprint(component.footprint_id), PITCH)
    middle = _pixel_at(image, item, source, scale, component, placement.centre_x, placement.centre_y)
    assert middle.name() != "#1b1d22", "the block is still drawn across the module"


def test_a_module_board_is_the_colour_its_maker_makes_it() -> None:
    """A Pico is green and an Espressif devkit black; the rest keep the module style's blue.
    Only where the layout is drawn: a board coloured as a Pico is a board drawn as one."""
    from perfboard_studio.ui.moduleart import (
        ESPRESSIF_BLACK,
        PICO_MODULE,
        POLOLU_DRV8825_MODULE,
        board_colour_for,
    )

    colours = {
        part.id: board_colour_for(
            _footprint(part.footprint_id), _part(part.footprint_id, part.placed_value, part.pin_names), PITCH
        )
        for part in CATALOG_MODULES
    }
    assert colours == {
        "esp32-devkitc": ESPRESSIF_BLACK,
        "esp32-c3-devkitm-1": ESPRESSIF_BLACK,
        "arduino-nano": None,
        "raspberry-pi-pico": PICO_MODULE.board_colour,
        "wemos-d1-mini": None,
        "pololu-a4988": PICO_MODULE.board_colour,
        "pololu-drv8825": POLOLU_DRV8825_MODULE.board_colour,
        "seeed-xiao-esp32c3": ESPRESSIF_BLACK,
        "lm2596-module": None,  # the blue every seller's board is
        "sparkfun-tb6612fng": SPARKFUN_RED,
        "pololu-drv8833": PICO_MODULE.board_colour,
    }
    # A Pico named on a board the layout was not drawn for is not coloured as one.
    square = "mod-2x20-p7-r1-30x30x3.5-s8.5"
    assert board_colour_for(_footprint(square), _part(square, "Raspberry Pi Pico"), PITCH) is None


def test_the_2d_view_paints_a_pico_green() -> None:
    from PySide6.QtGui import QColor

    from perfboard_studio.ui.moduleart import PICO_MODULE

    image, item, source, scale, component, _scene = _render_part("raspberry-pi-pico")
    assert item.board_colour == PICO_MODULE.board_colour
    placement = placement_for(_footprint(component.footprint_id), PITCH)
    # Bare board, below everything on it: the board's own colour, give or take the sheen.
    bare = _pixel_at(image, item, source, scale, component, placement.centre_x, placement.centre_y + 20)
    green = QColor(PICO_MODULE.board_colour)
    assert bare.hue() == pytest.approx(green.hue(), abs=12)
    assert bare.green() > bare.red() + 40 and bare.green() > bare.blue() + 40


def test_a_module_nobody_wrote_a_layout_for_keeps_its_block_in_2d() -> None:
    _qt_app()
    from perfboard_studio.mcp.session import new_board
    from perfboard_studio.ui.view2d import ComponentItem

    board = new_board(cols=40, rows=40).board
    plain = ComponentItem(_part(BUCK, "step-down module", BUCK_NAMES), _footprint(BUCK), board, "top")
    assert plain.art is None
    buck = ComponentItem(_part(BUCK, "LM2596S", BUCK_NAMES), _footprint(BUCK), board, "top")
    assert buck.art is not None


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
    for part in CATALOG_MODULES:
        _body, _fp, pieces = _board_and_pieces(part.footprint_id, part.placed_value, part.pin_names)
        assert not [piece for piece in pieces if piece.rgb == view3d._MODULE_BLOCK_RGB], part.id


def test_3d_and_the_step_file_paint_a_pico_green() -> None:
    """The colour the 2D view paints a module's board, the 3D view and the STEP export
    paint it too: one answer, ``moduleart.board_colour_for``."""
    from perfboard_studio.model import PerfDocument
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.export_step import step_palette
    from perfboard_studio.ui.moduleart import PICO_MODULE

    pico = next(part for part in CATALOG_MODULES if part.id == "raspberry-pi-pico")
    _body, footprint, pieces = _board_and_pieces(pico.footprint_id, pico.placed_value, pico.pin_names)
    green = view3d._rgb(PICO_MODULE.board_colour)
    assert pieces[0].rgb == green  # the module's own board, first

    from perfboard_studio.mcp.session import new_board

    document: PerfDocument = new_board(cols=40, rows=40)
    component = _part(pico.footprint_id, pico.placed_value, pico.pin_names)
    palette = step_palette(document)
    assert palette.body_rgb(footprint, component) == pytest.approx(green)
    plain = _part(pico.footprint_id, "a module")
    assert palette.body_rgb(footprint, plain) == palette.body_rgb(footprint)


def test_every_kind_of_part_has_a_builder() -> None:
    from typing import get_args

    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.moduleart import ArtKind

    assert set(view3d._ART_BUILDERS) == set(get_args(ArtKind))
    used = {part.kind for art in MODULE_ARTS for part in art.parts}
    assert used <= set(get_args(ArtKind))


@pytest.mark.parametrize("rotation", TURNS)
@pytest.mark.parametrize("mirrored", [False, True])
def test_the_nanos_chip_is_drawn_on_its_corner(rotation: int, mirrored: bool) -> None:
    """The body and the legs are turned an eighth off the board's axes however the Nano
    is turned or flipped, and its pin-1 dot sits towards the end ``moduleart`` says."""
    from perfboard_studio.ui import view3d

    _body, _fp, pieces = _board_and_pieces(
        NANO.footprint_id, "Arduino Nano", NANO.pin_names, rotation, mirrored
    )
    turned = [
        piece
        for piece in pieces
        if not piece.instances and abs(piece.orientation[2] % 90.0 - 45.0) < 1e-6
    ]
    # The body and the legs, and the marking printed along a side.
    assert {piece.rgb for piece in turned} == {
        view3d._ART_EPOXY_RGB,
        view3d.LEAD_RGB,
        view3d._ART_INK_RGB,
    }
    # The legs reach out along the board's axes as far as the turned outline says --
    # measured on their points, since an actor's own bounds are the turned box of its box.
    legs = next(piece for piece in turned if piece.rgb == view3d.LEAD_RGB)
    matrix = view3d._actor_for(legs).GetMatrix()
    points = [
        matrix.MultiplyPoint((*legs.source.GetPoint(index), 1.0))
        for index in range(legs.source.GetNumberOfPoints())
    ]
    leg_reach = (TQFP32_LEGS_PER_SIDE - 1) / 2 * TQFP32_PITCH_MM + TQFP32_LEG_MM / 2
    corner_reach = (9.0 / 2 + leg_reach) * math.sqrt(0.5)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    assert (max(xs) - min(xs)) / 2 == pytest.approx(corner_reach, abs=1e-6)
    assert (max(ys) - min(ys)) / 2 == pytest.approx(corner_reach, abs=1e-6)
    # The pin-1 dot is on the corner away from the USB socket, as Arduino's drawing has it.
    chip = next(piece for piece in turned if piece.rgb == view3d._ART_EPOXY_RGB)
    usb = next(piece for piece in pieces if piece.rgb == view3d._ART_USB_RGB)
    dot = min(
        (piece for piece in pieces if piece.rgb == view3d._ART_DOT_RGB),
        key=lambda piece: math.dist(piece.position[:2], chip.position[:2]),
    )
    assert math.dist(dot.position[:2], chip.position[:2]) < TQFP32_BODY_MM / 2 * math.sqrt(2)
    to_dot = (dot.position[0] - chip.position[0], dot.position[1] - chip.position[1])
    to_usb = (usb.position[0] - chip.position[0], usb.position[1] - chip.position[1])
    assert to_dot[0] * to_usb[0] + to_dot[1] * to_usb[1] < 0


@pytest.mark.parametrize("rotation", TURNS)
@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize(
    ("footprint_id", "value", "names"),
    [
        (BUCK, "LM2596S", BUCK_NAMES),
        (CAN, "SN65HVD230", CAN_NAMES),
        *((part.footprint_id, part.placed_value, part.pin_names) for part in CATALOG_MODULES),
    ],
    ids=lambda value: value if isinstance(value, str) and not value.startswith("mod-") else "",
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
#
# A pluggable block on a vertical header: KiCad's Phoenix MSTBVA header, sliced into ways
# like the side-entry block, with the plug drawn from Phoenix's MSTB 2,5/..-ST-5,08 sizes
# standing in it.


def _vertical(ways: int = 3, rotation: int = 0, mirrored: bool = False, header: bool = True):
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.mcp.session import new_board
    from perfboard_studio.ui import view3d

    board = new_board(cols=40, rows=40).board
    component = _part(f"screw-terminal-{ways}-v", "", (), rotation, mirrored)
    body = view3d._world_body(footprint_lookup(), component, board)
    assert body is not None and body.screws is not None
    models = view3d.vertical_header_models() if header else None
    return body, view3d._vertical_terminal_pieces(body, comp=component, header=models)


def _across(body, point) -> float:
    """How far ``point`` is from the pin row, towards the screw face."""
    cx = sum(x for x, _y in body.pins) / len(body.pins)
    cy = sum(y for _x, y in body.pins) / len(body.pins)
    nx, ny = body.screws
    return (point[0] - cx) * nx + (point[1] - cy) * ny


def test_the_header_slices_are_one_way_each_and_meet() -> None:
    """Each slice has its own pin at the origin and they butt end to end, so a way at every
    pin between a head and a tail is the whole header -- and they are the size the plug is
    drawn to stand in."""
    from perfboard_studio.ui import partmodels, view3d

    models = partmodels.vertical_header_models()
    assert models is not None, "the vertical header slices are missing from ui/models/"
    spans = []
    for model in models:
        body = model.body
        assert body is not None and len(body.bounds) == 6
        x0, y0, z0, x1, y1, z1 = body.bounds
        spans.append((round(x0, 3), round(x1, 3)))
        assert (z0, z1) == (0.0, view3d._VERTICAL_HEADER_HEIGHT_MM)
        # The model's +y is against the row; the plug's frame runs across it the other way.
        assert (-y1, -y0) == (view3d._VERTICAL_HEADER_BACK_MM, view3d._VERTICAL_HEADER_FRONT_MM)
    end = view3d._VERTICAL_HEADER_END_MM
    assert spans == [(-end, 2.54), (-2.54, 2.54), (-2.54, end)]
    for stem in (
        partmodels.VERTICAL_HEADER_HEAD,
        partmodels.VERTICAL_HEADER_WAY,
        partmodels.VERTICAL_HEADER_TAIL,
    ):
        assert get_footprint(stem) is None  # parts of a package, not something to place


def test_the_header_is_as_long_as_the_footprint_says() -> None:
    from perfboard_studio.ui import view3d

    for ways in (2, 3, 6):
        body, pieces = _vertical(ways)
        footprint = _footprint(f"screw-terminal-{ways}-v")
        # The header's own slices: one per pin, each going down at its pin.
        nylon = [
            p
            for p in pieces
            if p.rgb == view3d._rgb(body.style.fill) and not p.instances and p.position[2] == 0.0
        ]
        assert len(nylon) == ways
        x0, x1, y0, y1, _z0, z1 = _union(view3d, nylon)
        along = (x1 - x0) if body.axis == "x" else (y1 - y0)
        assert along == pytest.approx(footprint.body.dims["length"], abs=1e-3)
        assert z1 == pytest.approx(view3d._VERTICAL_HEADER_HEIGHT_MM)


def _union(view3d, pieces) -> tuple[float, ...]:
    boxes = [view3d._actor_for(piece).GetBounds() for piece in pieces]
    return (
        min(b[0] for b in boxes),
        max(b[1] for b in boxes),
        min(b[2] for b in boxes),
        max(b[3] for b in boxes),
        min(b[4] for b in boxes),
        max(b[5] for b in boxes),
    )


@pytest.mark.parametrize("header", [True, False])
def test_the_plug_stands_in_the_header_with_no_gap(header: bool) -> None:
    """Its foot is down in the header's pocket and its body rests on the header's rim: the
    gap a slab standing on a narrower slab showed between the two is not there."""
    from perfboard_studio.ui import view3d

    body, pieces = _vertical(3, header=header)
    lift = 0.0 if header else view3d._LIFT
    rim = view3d._VERTICAL_HEADER_HEIGHT_MM + lift
    plug = [
        piece
        for piece in pieces
        if piece.rgb == view3d._rgb(body.style.fill) and not piece.instances and piece.position[2] > 0
    ]
    foot = min(plug, key=lambda piece: view3d._actor_for(piece).GetBounds()[4])
    x0, x1, y0, y1, z0, z1 = view3d._actor_for(foot).GetBounds()
    assert z1 == pytest.approx(rim)
    assert z0 >= view3d._VERTICAL_CAVITY_FLOOR_MM
    for corner in ((x0, y0), (x1, y1)):
        assert (
            view3d._VERTICAL_CAVITY_BACK_MM
            <= _across(body, corner)
            <= view3d._VERTICAL_CAVITY_FRONT_MM
        )
    # The body's underside is the rim, exactly.
    lows = sorted(view3d._actor_for(piece).GetBounds()[4] for piece in plug if piece is not foot)
    assert lows[0] == pytest.approx(rim)


@pytest.mark.parametrize("rotation", TURNS)
@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize("header", [True, False])
def test_a_vertical_terminals_screws_are_in_the_side_of_its_plug(
    rotation: int, mirrored: bool, header: bool
) -> None:
    """On a vertical header the plug stands on end: wires in from above, screws from the
    side -- the face ``VERTICAL_TERMINAL_SCREW_FACE`` names, turned with the part."""
    from perfboard_studio.geometry import transform_offset
    from perfboard_studio.ui import view3d

    body, pieces = _vertical(3, rotation, mirrored, header)
    fx, fy = transform_offset(*view3d.VERTICAL_TERMINAL_SCREW_FACE, rotation, mirrored)  # type: ignore[arg-type]
    assert body.screws == pytest.approx((fx, -fy))

    heads = [
        piece
        for piece in pieces
        if piece.rgb == view3d._TERMINAL_METAL_RGB and piece.material == view3d.STEEL
        and piece.instances
        and all(_across(body, point) > 0 for point in piece.instances)
    ]
    assert len(heads) == 1 and len(heads[0].instances) == 3
    front = body.across / 2 - view3d._PLUG_FACE_SETBACK_MM
    for (hx, hy, hz), (pin_x, pin_y) in zip(sorted(heads[0].instances), sorted(body.pins), strict=True):
        assert _across(body, (hx, hy)) == pytest.approx(front + view3d._DECAL_PROUD_MM)
        # Level with its own pin along the row, partway up the plug's body.
        nx, ny = body.screws
        assert abs((hx - pin_x) * ny - (hy - pin_y) * nx) < 1e-9
        assert view3d._VERTICAL_HEADER_HEIGHT_MM < hz < body.height


@pytest.mark.parametrize("rotation", TURNS)
@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize("header", [True, False])
def test_a_vertical_terminal_stays_inside_its_envelope(
    rotation: int, mirrored: bool, header: bool
) -> None:
    """Measured on the actors as built: the header's, the plug's and every mark on them.
    The screw face is set back by what its marks stand out, so nothing passes the box DRC
    and the placer measure."""
    from perfboard_studio.ui import view3d

    body, pieces = _vertical(3, rotation, mirrored, header)
    lift = 0.0 if header else view3d._LIFT
    for piece in pieces:
        x0, x1, y0, y1, _z0, z1 = view3d._actor_for(piece).GetBounds()
        assert z1 <= body.height + lift + 1e-6, piece
        assert body.x - body.size_x / 2 - 1e-6 <= x0 and x1 <= body.x + body.size_x / 2 + 1e-6
        assert body.y - body.size_y / 2 - 1e-6 <= y0 and y1 <= body.y + body.size_y / 2 + 1e-6


def test_the_board_draws_the_header_from_kicad() -> None:
    """Through ``_pieces_for``, as a board is drawn: the header's slices, not the fallback."""
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.mcp.session import new_board
    from perfboard_studio.ui import partmodels, view3d

    board = new_board(cols=40, rows=40).board
    lookup = footprint_lookup()
    component = _part("screw-terminal-3-v", "")
    body = view3d._world_body(lookup, component, board)
    footprint = lookup("screw-terminal-3-v")
    assert body is not None and footprint is not None
    pieces = view3d._pieces_for(body, footprint, component, board)
    models = partmodels.vertical_header_models()
    assert models is not None
    meshes = {id(view3d._mesh(str(piece.path))) for model in models for piece in model.pieces}
    assert meshes <= {id(piece.source) for piece in pieces}


def test_only_a_vertical_terminal_has_a_screw_face() -> None:
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.mcp.session import new_board
    from perfboard_studio.ui import view3d

    board = new_board(cols=40, rows=40).board
    lookup = footprint_lookup()
    for footprint_id in ("screw-terminal-3", "dip-8", BUCK):
        body = view3d._world_body(lookup, _part(footprint_id, ""), board)
        assert body is not None and body.screws is None
