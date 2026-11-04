"""How the sheet is drawn in the window: net names on flags, text outlined in the paper's
colour, bodies filled, and a pin's text only where it fits.

Chosen on 2026-10-28 from sheets rendered in both themes. Rendering only: where every symbol,
wire and label IS is the layout's (``schematic.py``), and the exported SVG and PDF, held by
the schematic goldens, are drawn from that and not from this.
"""

from __future__ import annotations

import dataclasses
import itertools
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsScene

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.schematic import PIN_PITCH_MM, SchematicDrawing, build_schematic
from perfboard_studio.ui import viewsch
from perfboard_studio.ui.scenetext import label_plate_rect

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
    # Every name drawn is on a flag and nothing else is; zoomed out, a name with no room
    # waits for a closer zoom (``visible_labels``), close up every one is there.
    assert set(flagged) <= set(nets)
    assert not set(flagged) & set(outlined) - set(nets)
    if expect_pins:
        assert sorted(flagged) == sorted(nets)
    refs = [label.text for label in drawing.labels if label.kind == "ref"]
    assert all(text in outlined for text in refs)
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


def _sizes(px_per_mm: float) -> dict[str, int]:
    return {
        "ref": viewsch.label_px(viewsch.REF_LABEL_MM, viewsch.REF_PX, px_per_mm),
        "value": viewsch.label_px(viewsch.VALUE_LABEL_MM, viewsch.VALUE_PX, px_per_mm),
        "net": viewsch.label_px(viewsch.NET_LABEL_MM, viewsch.NET_PX, px_per_mm),
        "pin": viewsch.label_px(viewsch.PIN_LABEL_MM, viewsch.PIN_PX, px_per_mm),
    }


def _rects(drawing: SchematicDrawing, kept: list[int], px_per_mm: float) -> list[QRectF]:
    transform = QTransform.fromScale(px_per_mm, px_per_mm)
    sizes = _sizes(px_per_mm)
    rects = []
    for index in kept:
        label = drawing.labels[index]
        size = sizes["net"] if label.kind in ("net", "rail") else sizes[label.kind]
        rects.append(
            label_plate_rect(
                transform.map(viewsch._point(label.at)), label.text, size,
                viewsch.label_alignment(label), bold=label.kind in ("ref", "net"),
            )
        )
    return rects


@pytest.mark.parametrize("name", ["atmega328-relay", "ne555-astable", "nano-relay"])
def test_zoomed_out_no_label_prints_over_another(name: str) -> None:
    """The layout never overlaps two labels at their size on the sheet; zoomed out, text is
    held at a readable size two or three times that, and "VCC" landed on "VCC". The panel
    leaves out what would land on something already drawn."""
    drawing = _drawing(name)
    px = 2.5
    kept = viewsch.visible_labels(drawing.labels, QTransform.fromScale(px, px), _sizes(px))
    rects = _rects(drawing, kept, px)
    for first in range(len(rects)):
        for second in range(first + 1, len(rects)):
            assert not rects[first].intersects(rects[second]), (
                drawing.labels[kept[first]].text, drawing.labels[kept[second]].text
            )
    # Every part keeps its name: references go first.
    refs = {i for i, label in enumerate(drawing.labels) if label.kind == "ref"}
    assert refs <= set(kept)


@pytest.mark.parametrize("name", ["atmega328-relay", "ne555-astable", "nano-relay"])
def test_close_enough_every_label_comes_back(name: str) -> None:
    drawing = _drawing(name)
    px = 30.0
    kept = viewsch.visible_labels(drawing.labels, QTransform.fromScale(px, px), _sizes(px))
    named = [i for i, label in enumerate(drawing.labels) if label.kind != "pin"]
    assert sorted(kept) == named


def _arranged(path: Path) -> SchematicDrawing:
    doc = persist.parse_document_or_throw(path.read_text(encoding="utf-8"))
    return build_schematic(dataclasses.replace(doc, sheet=(), sheet_wires=()), footprint_lookup())


#: The zooms the examples' arranged sheets open at, fitted in a 1280 x 720 window (2.0 for
#: atmega328-relay up to 4.1 for the NE555), and two closer in.
FITTED_ZOOMS = (2.0, 2.7, 3.7, 4.1, 6.0, 10.0)


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.perf")), ids=lambda path: path.stem)
def test_zoomed_out_a_supply_name_moves_off_a_wire_rather_than_vanish(path: Path) -> None:
    """The layout keeps a power rail's name in the band over its bar, short of the next
    lane; held at a readable size zoomed out it reached into that lane, and the NE555
    arranged had a VCC printed across the wire running there.

    So at every zoom an example opens at, and a little closer: no supply name the panel
    draws meets a wire or another label, wherever it was moved to -- and every supply on
    the sheet is still named somewhere, because on a board with two rails (nano-relay's
    +12V and +5V) the name is all that tells them apart. Leaving every name out that met a
    wire showed none of the NE555's at the zoom it opens at."""
    drawing = _arranged(path)
    supplies = {label.text for label in drawing.labels if label.kind == "rail"}
    for px in FITTED_ZOOMS:
        transform = QTransform.fromScale(px, px)
        sizes = _sizes(px)
        places = viewsch.label_places(
            drawing.labels, transform, sizes,
            wires=[wire.path for wire in drawing.wires], rails=drawing.rails,
        )
        runs = [
            transform.mapRect(QRectF(viewsch._point(p), viewsch._point(q)).normalized())
            .adjusted(-0.5, -0.5, 0.5, 0.5)
            for wire in drawing.wires
            for p, q in itertools.pairwise(wire.path)
        ]
        plates = {}
        for index, (device, alignment) in places.items():
            label = drawing.labels[index]
            size = sizes["net"] if label.kind in ("net", "rail") else sizes[label.kind]
            plates[index] = label_plate_rect(
                device, label.text, size, alignment, bold=label.kind in ("ref", "net")
            )
        for index, plate in plates.items():
            if drawing.labels[index].kind != "rail":
                continue
            assert not any(plate.intersects(run) for run in runs), (drawing.labels[index].text, px)
            others = [other for key, other in plates.items() if key != index]
            assert not any(plate.intersects(other) for other in others), (
                drawing.labels[index].text, px
            )
        named = {drawing.labels[index].text for index in places if drawing.labels[index].kind == "rail"}
        assert named == supplies, (px, supplies - named)
