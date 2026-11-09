"""A module on a cable, and the header on the board it plugs into.

A keypad, a servo, a joystick or an I2C display is not on the perfboard: its cable plugs into
a header that is. The catalog puts such a part on the header (``hdr-1xN``) with the header's
pins named as the module names its leads, so the builder must never wonder where the module
itself went. The Library says it -- the module, that its cable plugs into this header, and
in which order -- and so does the build guide, which knows only the document: a header whose
pins the part has named is where something plugs in, and its step names it, says it is off
the board and gives its leads pin by pin.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.catalog import CATALOG, CatalogPart, catalog_part
from perfboard_studio.footprints import footprint_lookup, get_footprint
from perfboard_studio.geometry import all_pin_holes, format_hole
from perfboard_studio.guide import DEFAULT_GUIDE_OPTIONS, PartStep, build_guide
from perfboard_studio.mcp.session import new_board
from perfboard_studio.model import ComponentInstance, DocumentMeta, HoleCoord, PerfDocument

ROOT = Path(__file__).resolve().parents[1]
LOOKUP = footprint_lookup()


def _on_a_header(part: CatalogPart) -> bool:
    footprint = get_footprint(part.footprint_id)
    return footprint is not None and footprint.body.archetype == "pin-header"


ON_A_HEADER = tuple(part for part in CATALOG if _on_a_header(part))


def _placed(part_id: str, *, ref: str = "J1") -> PerfDocument:
    part = catalog_part(part_id)
    assert part is not None
    component = ComponentInstance(
        id="c1",
        ref=ref,
        value=part.placed_value,
        footprint_id=part.footprint_id,
        pin_names=part.pin_names,
        anchor=HoleCoord(3, 3),
    )
    board = new_board(cols=30, rows=12).board
    return PerfDocument(
        meta=DocumentMeta(name="cabled", created="", modified=""), board=board, components=(component,)
    )


def _step(doc: PerfDocument, ref: str, language: str = "en") -> PartStep:
    options = dataclasses.replace(DEFAULT_GUIDE_OPTIONS, language=language)
    guide = build_guide(doc, LOOKUP, options)
    return next(
        step
        for phase in guide.phases
        for step in phase.steps
        if isinstance(step, PartStep) and step.ref == ref
    )


def test_the_catalog_has_parts_on_a_header() -> None:
    assert {"keypad-4x4", "servo-header", "power-header-2"} <= {part.id for part in ON_A_HEADER}


@pytest.mark.parametrize("part", ON_A_HEADER, ids=lambda part: part.id)
def test_a_part_on_a_header_says_what_plugs_in_on_a_cable_and_in_which_order(part: CatalogPart) -> None:
    """One sentence for every such entry, so the Library says it the same way each time:
    what it is, that its cable plugs into this header, and its leads from pin 1 -- the same
    names, in the same order, as the part puts on the pins."""
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None
    assert len(part.pin_names) == len(footprint.pins), part.id
    order = " ".join(name for _number, name in part.pin_names)
    assert part.summary.endswith(
        f"Its cable plugs into this {len(footprint.pins)}-pin header: {order} from pin 1"
    ), part.id
    assert "header" in part.name, part.id


@pytest.mark.parametrize("language", ["en", "tr"])
def test_the_guide_says_the_keypad_is_off_the_board_and_where_each_lead_goes(language: str) -> None:
    doc = _placed("keypad-4x4")
    step = _step(doc, "J1", language)
    component = doc.components[0]
    said = [note for note in step.notes if component.value in note]
    assert len(said) == 1, step.notes
    expected_off = "is not on this board" if language == "en" else "bu kartın üzerinde değil"
    assert expected_off in said[0]
    pin_by_pin = [note for note in step.notes if note.startswith(("Pin by pin:", "Pin pin:"))]
    assert len(pin_by_pin) == 1, step.notes
    note = pin_by_pin[0]
    # Every lead, by the name the part gives it, at the hole it goes on -- in pin order.
    footprint = LOOKUP(component.footprint_id)
    assert footprint is not None
    names = dict(component.pin_names)
    places = [
        (names[pin.number], format_hole(at, doc.board))
        for pin, at in all_pin_holes(component, footprint)
    ]
    joiner = " in " if language == "en" else " "
    positions = [note.index(f"{name}{joiner}{hole}") for name, hole in places]
    assert positions == sorted(positions)


def test_a_header_whose_pins_nobody_named_says_nothing_of_a_cable() -> None:
    """The NE555 golden's J1 is a bare two-pin header: no module is said to plug into it,
    which is why no guide golden moved."""
    doc = persist.parse_document_or_throw(
        (ROOT / "tools" / "diffcheck" / "golden" / "ne555.perf").read_text(encoding="utf-8")
    )
    header = next(c for c in doc.components if c.ref == "J1")
    assert not header.pin_names
    step = _step(doc, "J1")
    assert not [note for note in step.notes if "plugs into this header" in note]


def test_a_header_with_named_pins_and_no_value_is_not_said_to_be_off_the_board() -> None:
    """With no value the sentence would call the header itself the thing that is not on the
    board; the one rule (``plugs_in_on_a_cable``) asks for both, for the guide and Properties."""
    from perfboard_studio.guide import plugs_in_on_a_cable

    doc = _placed("keypad-4x4")
    component = doc.components[0]
    footprint = LOOKUP(component.footprint_id)
    assert footprint is not None
    assert plugs_in_on_a_cable(component, footprint)
    assert not plugs_in_on_a_cable(dataclasses.replace(component, value=" "), footprint)
    assert not plugs_in_on_a_cable(dataclasses.replace(component, pin_names=()), footprint)
    bare = dataclasses.replace(doc, components=(dataclasses.replace(component, value=""),))
    assert not [note for note in _step(bare, "J1").notes if "plugs into this header" in note]


def test_a_cabled_step_says_each_thing_once() -> None:
    """The pin-by-pin list is the step's one list of holes and its one word on which way
    round: no polarity line ("Positive lead in G4" for a header pin named +), and no
    numbered "pins 1:D4 2:E4" in the exported guide. A header nobody named keeps both."""
    from perfboard_studio.guide_export import guide_to_html

    doc = _placed("ky-040-encoder")
    step = _step(doc, "J1")
    assert step.cabled and step.polarity is None
    guide = build_guide(doc, LOOKUP, DEFAULT_GUIDE_OPTIONS)
    html = guide_to_html(guide)
    assert "Pin by pin: CLK in D4" in html
    assert "pins 1:" not in html
    bare = dataclasses.replace(
        doc, components=(dataclasses.replace(doc.components[0], pin_names=(), value=""),)
    )
    plain = _step(bare, "J1")
    assert not plain.cabled
    assert "pins 1:" in guide_to_html(build_guide(bare, LOOKUP, DEFAULT_GUIDE_OPTIONS))


def test_the_json_says_cabled_only_of_a_cabled_step() -> None:
    """``cabled`` is in a step's JSON only where it is true, so every guide written before it
    is byte for byte what it was -- the NE555 golden among them."""
    import json

    from perfboard_studio.guide_export import guide_to_json

    def part_steps(doc: PerfDocument) -> list[dict]:  # type: ignore[type-arg]
        data = json.loads(guide_to_json(build_guide(doc, LOOKUP, DEFAULT_GUIDE_OPTIONS)))
        return [step for phase in data["phases"] for step in phase["steps"] if step["kind"] == "part"]

    (cabled,) = part_steps(_placed("ky-040-encoder"))
    assert cabled["cabled"] is True
    golden = persist.parse_document_or_throw(
        (ROOT / "tools" / "diffcheck" / "golden" / "ne555.perf").read_text(encoding="utf-8")
    )
    assert all("cabled" not in step for step in part_steps(golden))


#: What each module on a cable is called on the board: what it is sold as, so the guide's
#: sentence reads the same in either language ("KY-040 bu kartın üzerinde değil").
SOLD_AS = {
    "ky-023-joystick": "KY-023",
    "ky-040-encoder": "KY-040",
    "lcd-1602-i2c": "LCD1602 I2C",
    "ds3231-rtc": "DS3231 RTC",
    "max7219-matrix": "MAX7219 8x8",
    "tm1637-display": "TM1637",
    "ws2812b-strip": "WS2812B",
    "micro-sd-module": "Micro SD",
    "hc-05": "HC-05",
    "hc-06": "HC-06",
    "max485-module": "MAX485",
    "gy-bmp280": "GY-BMP280",
    "gy-bme280": "GY-BME280",
    "gy-bme280-3v3": "GY-BME280-3.3",
    "relay-module-1ch": "SRD-05VDC",
    "uln2003-board": "ULN2003 board",
    "l298n-board": "L298N board",
    "rc522-module": "RC522",
}


@pytest.mark.parametrize("part_id", sorted(SOLD_AS))
def test_a_cabled_module_is_named_as_it_is_sold_in_either_language(part_id: str) -> None:
    part = catalog_part(part_id)
    assert part is not None and part.placed_value == SOLD_AS[part_id]
    step = _step(_placed(part_id), "J1", "tr")
    assert step.notes[0].startswith(f"{SOLD_AS[part_id]} bu kartın üzerinde değil")
