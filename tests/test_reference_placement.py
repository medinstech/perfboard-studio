"""Where a part's reference is printed on screen, and how a round LED's leads show.

A reference is held at a pixel size and a board note is written in millimetres, so zoomed
out a reference outgrows the gap between them: on nano-relay J2's landed on the "LOAD"
written over it and read "LOJ2D". ``ComponentItem.reference_placement`` puts it over the
body, under it where over it is a note, and nowhere where both are -- the note is the
builder's own. Every example is held to it at every zoom the references are printed at.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples").glob("*.perf"))
#: The zooms a board is looked at between the references first being printed and close up.
ZOOMS = (3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 14.0, 20.0, 30.0, 40.0)


@pytest.fixture(scope="module", autouse=True)
def qapp() -> QApplication:
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])  # type: ignore[return-value]


def _scene(path: Path):  # type: ignore[no-untyped-def]
    from perfboard_studio.ui.view2d import BoardScene

    doc = persist.deserialize_document(path.read_text(encoding="utf-8")).document
    return BoardScene(doc, footprint_lookup(), side="top", show_ratsnest=False, show_rulers=False)


def test_an_example_has_board_notes_to_be_held_against() -> None:
    assert any(_scene(path).board_note_items for path in EXAMPLES)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.stem)
def test_no_reference_prints_on_a_board_note(path: Path) -> None:
    scene = _scene(path)
    for scale in ZOOMS:
        transform = QTransform.fromScale(scale, scale)
        for item in scene.component_items.values():
            notes = item._note_rects(transform)
            placement = item.reference_placement(transform)
            if placement is None:
                # Yielding is only for a reference with a note where it belongs.
                assert notes, (path.stem, item.comp.ref, scale)
                continue
            anchor, offset = placement
            plate = item.reference_rect(transform.map(anchor), offset)
            for note in notes:
                assert not plate.intersects(note), (path.stem, item.comp.ref, scale)
            if anchor != item.reference_anchor():
                # Moved under its part, it moved onto no pin name either.
                for name in item._pin_name_rects_on_screen(transform):
                    assert not plate.intersects(name), (path.stem, item.comp.ref, scale)


def test_nano_relays_j2_never_prints_on_its_load_note() -> None:
    """Close up J2's reference is over its terminal block, where it always was. At the zoom
    the guide's picture has the board at it would print on the "LOAD" over it, and under the
    block on K1's "NO": it yields there, and is in Properties."""
    scene = _scene(ROOT / "examples" / "nano-relay.perf")
    j2 = next(item for item in scene.component_items.values() if item.comp.ref == "J2")
    near = j2.reference_placement(QTransform.fromScale(40.0, 40.0))
    assert near is not None and near[0] == j2.reference_anchor()
    assert j2.reference_placement(QTransform.fromScale(5.0, 5.0)) is None


def test_a_round_leds_leads_are_quiet_and_its_plus_is_the_bright_one() -> None:
    """Under a 5 mm LED's dome its two leads were full-size rings with the die between them,
    and the three read as an "8". They are small marks now, the + (pin 1) still white and
    the other the dome's own colour, darker -- not the light grey ring of a pin elsewhere."""
    from perfboard_studio.geometry import all_pin_holes
    from perfboard_studio.ui.view2d import LED_LEAD_MARK_MM, PIN_MARKER, PIN_ONE, hole_to_screen

    scene = _scene(ROOT / "examples" / "nano-relay.perf")
    led = next(item for item in scene.component_items.values() if item.comp.ref == "D2")
    assert led.fp.body.archetype == "led-round"
    scale = 40.0
    rect = led.sceneBoundingRect().adjusted(-1, -1, 1, 1)
    image = QImage(int(rect.width() * scale), int(rect.height() * scale), QImage.Format.Format_ARGB32)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), rect)
    painter.end()

    def colour_at(point: QPointF) -> QColor:
        return image.pixelColor(int((point.x() - rect.left()) * scale), int((point.y() - rect.top()) * scale))

    holes = {pin.number: hole_to_screen(at, led.board, "top") for pin, at in all_pin_holes(led.comp, led.fp)}
    plus, other = colour_at(holes["1"]), colour_at(holes["2"])
    assert plus.lightness() > 200 and abs(plus.lightness() - PIN_ONE.lightness()) < 25
    assert other.lightness() < plus.lightness() - 100
    assert abs(other.lightness() - PIN_MARKER.lightness()) > 40
    # A mark, not a ring: just off the lead's middle by more than the mark is the dome.
    beside = colour_at(holes["1"] + QPointF(LED_LEAD_MARK_MM + 0.15, 0.0))
    assert beside.lightness() < plus.lightness() - 60
