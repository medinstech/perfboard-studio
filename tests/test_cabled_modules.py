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
