"""How the sheet is drawn in the window: net names on flags, text outlined in the paper's
colour, bodies filled, and a pin's text only where it fits.

Chosen on 2026-10-28 from sheets rendered in both themes. Rendering only: where every symbol,
wire and label IS is the layout's (``schematic.py``), and the exported SVG and PDF, held by
the schematic goldens, are drawn from that and not from this.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF
from PySide6.QtWidgets import QApplication, QGraphicsScene

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.schematic import PIN_PITCH_MM, SchematicDrawing, build_schematic
from perfboard_studio.ui import viewsch

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _drawing(name: str) -> SchematicDrawing:
    doc = persist.parse_document_or_throw((EXAMPLES / f"{name}.perf").read_text(encoding="utf-8"))
    return build_schematic(doc, footprint_lookup())


def _paint(drawing: SchematicDrawing, px_per_mm: float) -> QImage:
    scene = QGraphicsScene()
    item = viewsch.SheetItem(drawing)
    scene.addItem(item)
    source = QRectF(0, 0, drawing.width, drawing.height)
    image = QImage(round(drawing.width * px_per_mm), round(drawing.height * px_per_mm), QImage.Format.Format_ARGB32)
    image.fill(QColor(viewsch.SHEET))
    painter = QPainter(image)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), source)
    painter.end()
    return image


def test_pin_text_is_drawn_only_where_it_fits() -> None:
    """Zoomed out on atmega328-relay the 28 pins of U1 are closer together than a line of
    text is tall, and every name and number over-printed the next into a grey bar."""
    height_px = 1 + viewsch.PIN_PX
    assert not viewsch.pin_text_fits(height_px / PIN_PITCH_MM / 2, viewsch.PIN_PX)
    assert viewsch.pin_text_fits(9.0, viewsch.PIN_PX)


@pytest.mark.parametrize("px_per_mm, expect_pins", [(2.0, False), (9.0, True)])
def test_the_sheet_says_each_label_its_own_way(monkeypatch, px_per_mm, expect_pins) -> None:  # type: ignore[no-untyped-def]
    flagged: list[str] = []
    outlined: list[str] = []
    monkeypatch.setattr(viewsch, "draw_flag_label", lambda painter, at, text, *a, **k: flagged.append(text))
    monkeypatch.setattr(viewsch, "draw_outlined_label", lambda painter, at, text, *a, **k: outlined.append(text))
    drawing = _drawing("atmega328-relay")
    _paint(drawing, px_per_mm)

    nets = [label.text for label in drawing.labels if label.kind == "net"]
    pins = [label.text for label in drawing.labels if label.kind == "pin"]
    others = [label.text for label in drawing.labels if label.kind in ("ref", "value", "rail")]
    assert nets and pins and others
    assert sorted(flagged) == sorted(nets), "every net's name on a flag, and nothing else"
    assert all(text in outlined for text in others)
    drawn_pins = [text for text in outlined if text in pins and text not in others]
    assert bool(drawn_pins) is expect_pins


def test_a_symbol_body_is_filled_and_an_arrowhead_is_not() -> None:
    drawing = _drawing("ne555-astable")
    chip = next(symbol for symbol in drawing.symbols if symbol.ref == "U1")
    body = max(
        (s for s in chip.shapes if s.kind == "polygon" and not s.filled),
        key=lambda s: QPolygonF([QPointF(p.x, p.y) for p in s.points]).boundingRect().width(),
    )
    box = QPolygonF([QPointF(p.x, p.y) for p in body.points]).boundingRect()
    px = 8.0
    image = _paint(drawing, px)
    # The middle of the 555's box, between its two columns of pin names: the body's tint.
    centre = image.pixelColor(
        round((chip.at.x + box.center().x()) * px), round((chip.at.y + box.center().y()) * px)
    )
    assert centre.name() == QColor(viewsch.BODY_FILL).name()

    arrowhead = QPolygonF([QPointF(0, 0), QPointF(1.0, 0.4), QPointF(0, 0.8), QPointF(0, 0)])
    rectangle = QPolygonF([QPointF(0, 0), QPointF(6, 0), QPointF(6, 3), QPointF(0, 3), QPointF(0, 0)])
    assert not viewsch._is_body(arrowhead)
    assert viewsch._is_body(rectangle)
