"""Where a part's reference is printed on screen.

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

from PySide6.QtGui import QTransform
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
