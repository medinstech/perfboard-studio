"""The thing a part off the board is, drawn beside the board on the screen.

A battery on a clip, a pot on the panel, an e-stop, a display down a cable: the board holds
only the pads its wires land in, and the window draws the thing itself at its own size
beside the board, its wires running to it (View > Parts Off the Board). These tests pin
what that is allowed to touch -- one optional drawing position on the part
(``offBoardAt``), set by one command, left out of the file at its default and read by
nothing below the interface -- and what it draws: the right thing for each part, laid out
the same way every time, clear of the board and of each other, and on the screen only.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.catalog import CABLED, CATALOG, NOT_A_THING, catalog_part, stands_off_board
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    MoveComponentPayload,
    PlaceComponentPayload,
    PlaceOffBoardPayload,
    RotateComponentPayload,
    UpdateComponentPayload,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import HoleCoord, PerfDocument, Point2
from perfboard_studio.ui.offboard import BY_CATALOG_ID, Wanted, art_for, lay_out
from perfboard_studio.ui.view2d import BoardScene, print_scene

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "perfboard_studio"
NE555 = ROOT / "examples" / "ne555-astable.perf"
LOOKUP = footprint_lookup()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _bus(doc: PerfDocument) -> CommandBus:
    return CommandBus(doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc)))


def _place(
    bus: CommandBus,
    ref: str,
    part_id: str | None,
    at: tuple[int, int],
    *,
    rotation: int = 0,
    value: str | None = None,
    symbol: str | None = None,
    footprint: str | None = None,
) -> str:
    part = catalog_part(part_id) if part_id else None
    result = bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref=ref,
            value=value if value is not None else (part.placed_value if part else ""),
            footprint_id=footprint or (part.footprint_id if part else ""),
            anchor=HoleCoord(*at),
            rotation=rotation,  # type: ignore[arg-type]
            pin_names=part.pin_names if part else (),
            symbol=symbol if symbol is not None else (part.symbol if part else None),  # type: ignore[arg-type]
        ),
    )
    assert result.ok, result.message
    return next(c.id for c in bus.document.components if c.ref == ref)


def _bench() -> tuple[CommandBus, dict[str, str]]:
    """The NE555 example with seven things hung off its four edges."""
    bus = _bus(persist.parse_document_or_throw(NE555.read_text(encoding="utf-8")))
    cols, rows = bus.document.board.cols, bus.document.board.rows
    ids = {
        "BT1": _place(bus, "BT1", "battery-9v-clip", (1, 1), rotation=90),
        "M1": _place(bus, "M1", "dc-motor-130", (cols - 2, 2), rotation=90),
        "RV1": _place(bus, "RV1", "pot-panel", (3, rows - 1)),
        "S1": _place(bus, "S1", None, (cols - 6, rows - 1), value="E-STOP", symbol="button", footprint="wire-2"),
        "J5": _place(bus, "J5", "lcd-1602-i2c", (8, 0), rotation=90),
        "K2": _place(bus, "K2", "relay-module-1ch", (0, rows - 6)),
        "U9": _place(bus, "U9", "gy-bmp280", (cols - 1, 0), rotation=90),
    }
    return bus, ids


def _scene(doc: PerfDocument, bus: CommandBus | None = None, show: bool = True) -> BoardScene:
    _app()
    return BoardScene(doc, LOOKUP, side="top", bus=bus, show_off_board=show)


# -- the document: one optional field, one command ------------------------------------------


def test_the_position_survives_the_file_and_is_left_out_at_its_default() -> None:
    bus, ids = _bench()
    before = persist.serialize_document(bus.document)
    assert "offBoardAt" not in before
    assert bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["J5"], at=Point2(-40.5, 12.25))).ok
    text = persist.serialize_document(bus.document)
    assert text.count('"offBoardAt"') == 1
    again = persist.parse_document_or_throw(text)
    lcd = next(c for c in again.components if c.id == ids["J5"])
    assert lcd.off_board_at == Point2(-40.5, 12.25)
    assert persist.serialize_document(again) == text
    assert bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["J5"], at=None)).ok
    assert persist.serialize_document(bus.document) == before


def test_a_position_that_is_not_a_number_is_refused_at_load() -> None:
    bus, ids = _bench()
    assert bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["J5"], at=Point2(1.0, 2.0))).ok
    raw = json.loads(persist.serialize_document(bus.document))
    lcd = next(c for c in raw["components"] if c["id"] == ids["J5"])
    lcd["offBoardAt"]["x"] = "one"
    with pytest.raises(ValueError, match="offBoardAt"):
        persist.parse_document_or_throw(json.dumps(raw))


def test_the_command_is_one_undo_step_and_says_what_it_did() -> None:
    bus, ids = _bench()
    doc = bus.document
    result = bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["BT1"], at=Point2(-30.0, 5.0)))
    assert result.ok and result.description == "Move BT1 beside the board"
    bus.undo()
    assert bus.document == doc
    assert bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["BT1"], at=Point2(-30.0, 5.0))).ok
    back = bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["BT1"], at=None))
    assert back.ok and back.description == "Put BT1 back beside its wires"


def test_the_same_place_again_and_a_place_at_infinity_are_refused() -> None:
    bus, ids = _bench()
    assert bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["BT1"], at=Point2(-30.0, 5.0))).ok
    same = bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["BT1"], at=Point2(-30.0, 5.0)))
    assert not same.ok and same.code == "nothing-to-do"
    nowhere = bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["BT1"], at=Point2(math.inf, 0.0)))
    assert not nowhere.ok and nowhere.code == "invalid-value"
    unknown = bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id="cmp-404", at=None))
    assert not unknown.ok


def test_the_position_goes_with_the_part_through_a_move_a_turn_and_an_edit() -> None:
    bus, ids = _bench()
    at = Point2(-30.0, 5.0)
    assert bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["BT1"], at=at)).ok
    assert bus.dispatch("component.move", MoveComponentPayload(id=ids["BT1"], anchor=HoleCoord(1, 2))).ok
    assert bus.dispatch("component.rotate", RotateComponentPayload(id=ids["BT1"], rotation=180)).ok
    assert bus.dispatch("component.update", UpdateComponentPayload(id=ids["BT1"], value="9V block")).ok
    battery = next(c for c in bus.document.components if c.id == ids["BT1"])
    assert battery.off_board_at == at


def test_nothing_below_the_interface_reads_where_a_thing_is_drawn() -> None:
    """A drawing position, and nothing else: no rule, no route, no guide may move with it."""
    allowed = {SRC / "model.py", SRC / "persist.py", SRC / "commands.py"}
    readers = []
    for path in SRC.rglob("*.py"):
        if path in allowed or "ui" in path.relative_to(SRC).parts[:1]:
            continue
        if "off_board_at" in path.read_text(encoding="utf-8"):
            readers.append(str(path.relative_to(SRC)))
    assert readers == []
    tree = ast.parse((SRC / "commands.py").read_text(encoding="utf-8"))
    imported = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("ui" in module.split(".") for module in imported)


# -- what each part is drawn as ---------------------------------------------------------------


def test_every_thing_the_catalog_names_is_in_the_catalog() -> None:
    ids = {part.id for part in CATALOG}
    assert set(BY_CATALOG_ID) <= ids


def test_every_cabled_module_is_drawn_and_a_power_lead_is_not() -> None:
    cabled = [part for part in CATALOG if CABLED in part.summary]
    assert len(cabled) > 20
    for part in cabled:
        footprint = LOOKUP(part.footprint_id)
        assert footprint is not None
        comp = _component(part.id)
        art = art_for(comp, footprint)
        if part.id in NOT_A_THING:
            assert art is None, part.id
        else:
            assert art is not None, part.id


def test_a_part_on_the_board_is_drawn_on_the_board_alone() -> None:
    """A plain header could have anything on its other end, or nothing: only a part on wires,
    or a module the catalog says a cable plugs into, is drawn beside the board."""
    base = _component(None)
    for part in CATALOG:
        footprint = LOOKUP(part.footprint_id)
        if footprint is None or CABLED in part.summary:
            continue
        if footprint.body.archetype == "flying-leads":
            continue
        comp = dataclasses.replace(base, footprint_id=part.footprint_id, value=part.placed_value)
        assert art_for(comp, footprint) is None, part.id


def test_a_part_on_wires_is_known_by_its_value_then_its_symbol() -> None:
    footprint = LOOKUP("wire-2")
    assert footprint is not None
    estop = dataclasses.replace(_component(None), value="Emergency stop", symbol="button")
    button = dataclasses.replace(_component(None), value="START", symbol="button")
    mystery = dataclasses.replace(_component(None), value="Sensor X", symbol=None)
    assert art_for(estop, footprint).key == "estop"  # type: ignore[union-attr]
    assert art_for(button, footprint).key == "pushbutton"  # type: ignore[union-attr]
    assert art_for(mystery, footprint).key == "thing"  # type: ignore[union-attr]


def _component(part_id: str | None):  # type: ignore[no-untyped-def]
    # A thing with no picture of its own is drawn as a box with its name, measured in a
    # font -- and a QFont with no application aborts the process rather than raising.
    _app()
    bus, _ids = _bench()
    if part_id is None:
        return next(c for c in bus.document.components if c.ref == "S1")
    part = catalog_part(part_id)
    assert part is not None
    comp = bus.document.components[0]
    return dataclasses.replace(
        comp, footprint_id=part.footprint_id, value=part.placed_value, pin_names=part.pin_names, symbol=part.symbol
    )


# -- where they stand -------------------------------------------------------------------------


def _wanted() -> tuple[list[Wanted], QRectF]:
    outline = QRectF(0.0, 0.0, 60.0, 30.0)
    wanted = [
        Wanted("a", (30.0, 20.0), (QPointF(10.0, 0.0), QPointF(12.0, 0.0)), (0.0, -1.0), (0.0, 8.0)),
        Wanted("b", (30.0, 20.0), (QPointF(14.0, 0.0), QPointF(16.0, 0.0)), (0.0, -1.0), (0.0, 8.0)),
        Wanted("c", (20.0, 20.0), (QPointF(60.0, 15.0),), (1.0, 0.0), (-8.0, 0.0)),
    ]
    return wanted, outline


def test_things_stand_off_the_board_and_clear_of_each_other_the_same_way_every_time() -> None:
    _app()
    wanted, outline = _wanted()
    first = lay_out(wanted, outline, {})
    assert first == lay_out(wanted, outline, {})
    rects = list(first.values())
    for i, rect in enumerate(rects):
        assert not rect.intersects(outline)
        for other in rects[i + 1:]:
            assert not rect.intersects(other)


def test_a_thing_dragged_somewhere_stays_there_and_the_rest_make_room() -> None:
    _app()
    wanted, outline = _wanted()
    free = lay_out(wanted, outline, {})
    kept = {"b": free["a"].center()}
    placed = lay_out(wanted, outline, kept)
    assert placed["b"].center() == free["a"].center()
    assert not placed["a"].intersects(placed["b"])


# -- the scene --------------------------------------------------------------------------------


def test_only_the_window_draws_them() -> None:
    bus, _ids = _bench()
    _app()
    assert _scene(bus.document, show=False).off_board_items == {}
    assert print_scene(bus.document, LOOKUP, "top").off_board_items == {}
    assert BoardScene(bus.document, LOOKUP, side="top").off_board_items == {}
    bottom = BoardScene(bus.document, LOOKUP, side="bottom", show_off_board=True)
    assert bottom.off_board_items == {}


def test_the_window_draws_every_thing_and_frames_it() -> None:
    bus, ids = _bench()
    scene = _scene(bus.document)
    assert set(scene.off_board_items) == set(ids.values())
    for comp_id, thing in scene.off_board_items.items():
        assert scene.sceneRect().contains(thing.sceneBoundingRect())
        assert scene.component_items[comp_id].leads_carry_on
        assert thing.owner is scene.component_items[comp_id]


def test_the_toggle_takes_them_away_and_brings_them_back() -> None:
    bus, _ids = _bench()
    scene = _scene(bus.document, show=False)
    scene.set_show_off_board(True)
    assert len(scene.off_board_items) == 7
    scene.set_show_off_board(False)
    assert scene.off_board_items == {}
    assert not any(item.leads_carry_on for item in scene.component_items.values())


def test_a_click_on_a_thing_is_a_click_on_its_part() -> None:
    bus, ids = _bench()
    scene = _scene(bus.document)
    thing = scene.off_board_items[ids["J5"]]
    hit = scene.component_at(thing.scenePos())
    assert hit is scene.component_items[ids["J5"]]


def test_a_drop_is_one_command_and_the_thing_is_drawn_where_it_was_let_go() -> None:
    bus, ids = _bench()
    scene = _scene(bus.document, bus=bus)
    committed: list[object] = []
    scene.moveCommitted.connect(committed.append)
    thing = scene.off_board_items[ids["J5"]]
    assert thing.on_dropped is not None
    thing.on_dropped(ids["J5"], Point2(-60.0, -40.0))
    result = scene.commit_off_board_drop()
    assert result is not None and result.ok
    assert committed and bus.history()[-1] == "Move J5 beside the board"
    assert scene.commit_off_board_drop() is None
    scene.set_document(bus.document)
    moved = scene.off_board_items[ids["J5"]]
    assert (moved.pos().x(), moved.pos().y()) == (-60.0, -40.0)


# -- one predicate, two askers ---------------------------------------------------------------


def _every_board() -> list[Path]:
    return sorted([*(ROOT / "examples").glob("*.perf"), *(ROOT / "tools" / "diffcheck" / "golden").glob("*.perf")])


@pytest.mark.parametrize("path", _every_board(), ids=lambda p: p.name)
def test_what_the_window_draws_is_exactly_what_the_command_will_place(path: Path) -> None:
    """A thing on the screen the command refused to move, or a place the command kept for a
    thing nobody draws, is the two askers disagreeing. They read one predicate."""
    _app()
    doc = persist.parse_document_or_throw(path.read_text(encoding="utf-8"))
    bus = _bus(doc)
    scene = _scene(bus.document)
    for comp in scene.document.components:
        if comp.side != "top":
            continue
        footprint = LOOKUP(comp.footprint_id)
        drawn = comp.id in scene.off_board_items
        assert drawn == stands_off_board(comp, footprint), comp.ref
        result = bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=comp.id, at=Point2(-99.0, -99.0)))
        assert result.ok == drawn, (comp.ref, result.code, result.message)


def test_a_part_on_the_board_is_given_no_place_beside_it() -> None:
    bus, _ids = _bench()
    chip = next(c for c in bus.document.components if c.ref == "U1")
    refused = bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=chip.id, at=Point2(-30.0, 5.0)))
    assert not refused.ok and refused.code == "not-off-board"
    assert "on the board" in refused.message


def test_a_place_on_the_board_is_no_place_and_the_thing_is_laid_out_again() -> None:
    """Dropped onto the board, or the board grown under it since: drawn there it would hide
    the parts it stands on."""
    _app()
    wanted, outline = _wanted()
    free = lay_out(wanted, outline, {})
    placed = lay_out(wanted, outline, {"a": outline.center()})
    assert placed == free


def test_letting_go_where_it_already_was_is_no_command_and_no_error() -> None:
    bus, ids = _bench()
    assert bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=ids["J5"], at=Point2(-60.0, -40.0))).ok
    scene = _scene(bus.document, bus=bus)
    committed: list[object] = []
    scene.moveCommitted.connect(committed.append)
    before = bus.history()
    thing = scene.off_board_items[ids["J5"]]
    assert thing.on_dropped is not None
    thing.on_dropped(ids["J5"], Point2(-60.0, -40.0))
    assert scene.commit_off_board_drop() is None
    assert committed == [] and bus.history() == before


#: Every catalog part ``stands_off_board`` puts beside the board. Which modules are cabled is
#: read from a sentence in each one's summary, and the drawing and the command move together
#: when it changes -- so a summary reworded while polishing the catalog would drop a module
#: from both without a word. This list is what makes it say so.
STANDS_OFF_BOARD: frozenset[str] = frozenset({
    "adafruit-adxl345", "adafruit-aht20", "adafruit-apds9960", "adafruit-as5600", "adafruit-bh1750",
    "adafruit-bno055", "adafruit-ccs811", "adafruit-hmc5883l", "adafruit-ili9341-tft", "adafruit-lsm6ds3",
    "adafruit-max31855", "adafruit-max98357", "adafruit-mcp4725", "adafruit-mpr121", "adafruit-qmc5883p",
    "adafruit-rfm9x-lora", "adafruit-sht31", "adafruit-tcs34725", "adafruit-tmc2209", "adafruit-vl53l0x",
    "adafruit-vl53l1x", "ams1117-33-module", "battery-9v-clip", "battery-aa-holder", "dc-jack-panel",
    "dc-motor-130", "ds1307-tiny-rtc", "ds3231-rtc", "ftdi-basic", "gy-bme280", "gy-bme280-3v3", "gy-bmp280",
    "hc-05", "hc-06", "hc-12", "keypad-4x4", "ky-009-rgb-led", "ky-011-two-colour-led", "ky-016-rgb-led",
    "ky-023-joystick", "ky-040-encoder", "ky-051-level-shifter", "ky-053-ads1115", "l298n-board",
    "lcd-1602-i2c", "max485-module", "max7219-matrix", "micro-sd-module", "mt3608-boost", "nokia-5110",
    "pca9685-servo-driver", "piezo-disc-7bb", "pot-panel", "rc522-module", "relay-module-1ch",
    "sensor-board-3pin", "sensor-board-4pin", "servo-header", "sparkfun-ad8232", "sparkfun-max30105",
    "sparkfun-temt6000", "st7735-tft-18", "tm1637-display", "tp4056-module", "ttp223-touch",
    "uln2003-board", "ws2812b-strip", "xl6009-boost",
})


def test_which_catalog_parts_stand_beside_the_board_is_written_down() -> None:
    base = _component(None)
    found = set()
    for part in CATALOG:
        comp = dataclasses.replace(base, footprint_id=part.footprint_id, value=part.placed_value)
        if stands_off_board(comp, LOOKUP(part.footprint_id)):
            found.add(part.id)
    assert found == STANDS_OFF_BOARD
