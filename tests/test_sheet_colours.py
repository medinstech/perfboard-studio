"""What colour a lit net is on the sheet: its own, on a glow of the accent.

Sinan's dev3 try: selecting the regulator lit +5V, GND and VRAW, and a lit net was redrawn IN
the accent -- so the supply turned blue, the ground with it, and the sheet read as wired in
two blues. A lit net now keeps its class colour, heavier, over a glow (``viewsch.HALO_MM``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionGraphicsItem

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.schematic import build_schematic
from perfboard_studio.ui import viewsch

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "ne555-astable.perf"
SCALE = 8.0  # pixels per millimetre of sheet


@pytest.fixture(scope="module", autouse=True)
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def test_a_lit_net_says_its_name_where_the_sheet_does_not() -> None:
    """A wired net's name the sheet holds back (``schematic._worth_naming``) is drawn while
    the net is lit, so clicking a wire or a part on it says what it is called."""
    document = persist.deserialize_document(EXAMPLE.read_text(encoding="utf-8")).document
    drawing = build_schematic(document, footprint_lookup())
    assert drawing.quiet_names
    net_id, label = drawing.quiet_names[0]
    said: list[str] = []
    original = viewsch.draw_flag_label

    def spy(painter, at, text, *args, **kwargs):  # type: ignore[no-untyped-def]
        said.append(text)
        return original(painter, at, text, *args, **kwargs)

    viewsch.draw_flag_label = spy  # type: ignore[assignment]
    try:
        view = viewsch.SchematicView()
        view.set_drawing(drawing)
        item = view.item
        assert item is not None
        for lit in (False, True):
            said.clear()
            item.set_highlight([], {net_id} if lit else set())
            image = QImage(400, 300, QImage.Format.Format_RGB32)
            painter = QPainter(image)
            painter.scale(2.0, 2.0)
            item.paint(painter, QStyleOptionGraphicsItem(), None)
            painter.end()
            assert (label.text in said) == lit
    finally:
        viewsch.draw_flag_label = original  # type: ignore[assignment]


def _distance(a: QColor, b: QColor) -> int:
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())


def _rail_pixels(lit: bool) -> list[tuple[str, QColor]]:
    """The colour at the middle of every rail's longest run, the rail's net lit or not."""
    document = persist.deserialize_document(EXAMPLE.read_text(encoding="utf-8")).document
    drawing = build_schematic(document, footprint_lookup())
    view = viewsch.SchematicView()
    view.set_drawing(drawing)
    item = view.item
    assert item is not None
    if lit:
        item.set_highlight([], {rail.net_id for rail in drawing.rails})
    image = QImage(
        round(drawing.width * SCALE), round(drawing.height * SCALE), QImage.Format.Format_RGB32
    )
    image.fill(QColor(viewsch.SHEET))
    painter = QPainter(image)
    painter.scale(SCALE, SCALE)
    item.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()
    out = []
    for rail in drawing.rails:
        start, end = max(
            zip(rail.path, rail.path[1:], strict=False),
            key=lambda run: abs(run[1].x - run[0].x) + abs(run[1].y - run[0].y),
        )
        middle = QPointF((start.x + end.x) / 2 * SCALE, (start.y + end.y) / 2 * SCALE)
        out.append((rail.net_class, image.pixelColor(round(middle.x()), round(middle.y()))))
    return out


@pytest.mark.parametrize("lit", [False, True], ids=["unlit", "lit"])
def test_a_lit_net_keeps_its_class_colour(lit: bool) -> None:
    pixels = _rail_pixels(lit)
    assert {net_class for net_class, _ in pixels} == {"power", "ground"}
    highlight = QColor(viewsch.HIGHLIGHT)
    for net_class, colour in pixels:
        own = QColor(viewsch.POWER if net_class == "power" else viewsch.GROUND)
        assert _distance(colour, own) < 40, (net_class, colour.name())
        assert _distance(colour, own) < _distance(colour, highlight), (net_class, colour.name())
