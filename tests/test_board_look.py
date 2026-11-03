"""The board's look on screen, and the 1:1 print that must not take it.

Chosen on 2026-10-28 from rendered looks: bodies standing on the board with a contact shadow
and lit from the top left, a DIP's value on its top, references outlined instead of plated,
far-face copper quieter. The shadow and the light are for the eye on a screen. The 1:1 PDF
is taped to the board in someone's hand, so it shows every part flat -- which is what most
of these hold. Pads nothing landed in were drawn quieter on screen too, until the user chose
the board as it is in the hand (2026-11-03): every pad is tin on both.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import PerfDocument
from perfboard_studio.ui import view2d
from perfboard_studio.ui.export_pdf import export_pdf

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
LOOKUP = footprint_lookup()


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _example(name: str) -> PerfDocument:
    return persist.parse_document_or_throw((EXAMPLES / f"{name}.perf").read_text(encoding="utf-8"))


def _on_screen(scene: view2d.BoardScene) -> None:
    rect = scene.sceneRect()
    image = QImage(round(rect.width() * 8), round(rect.height() * 8), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), rect)
    painter.end()


def _on_paper(doc: PerfDocument, scene: view2d.BoardScene, tmp_path: Path) -> None:
    export_pdf(doc.board, scene, tmp_path / "board.pdf")


def _counting(paint, drawn: list[int]):  # type: ignore[no-untyped-def]
    """``PadGridItem.paint`` that records which pad image each hole was drawn with."""

    def wrapped(item, painter, option, widget=None):  # type: ignore[no-untyped-def]
        real = painter.drawPixmap

        class Recording:
            def __getattr__(self, name):  # type: ignore[no-untyped-def]
                return getattr(painter, name)

            def drawPixmap(self, target, pixmap, source):  # type: ignore[no-untyped-def]
                drawn.append(pixmap.cacheKey())
                return real(target, pixmap, source)

        return paint(item, Recording(), option, widget)

    return wrapped


def test_every_pad_is_drawn_alike_on_screen_and_on_paper(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A real board's pads are all tin, used or not, and so are these: one pad image for every
    hole, on screen as on the 1:1 print."""
    drawn: list[int] = []
    doc = _example("ne555-astable")
    for render in (
        lambda: _on_screen(view2d.BoardScene(doc, LOOKUP, side="top")),
        lambda: _on_paper(doc, view2d.BoardScene(doc, LOOKUP, side="top"), tmp_path),
    ):
        drawn.clear()
        monkeypatch.setattr(view2d.PadGridItem, "paint", _counting(view2d.PadGridItem.paint, drawn))
        render()
        monkeypatch.undo()
        assert drawn, "no pads were drawn"
        assert len(set(drawn)) == 1, "two kinds of pad on one board"


def test_shadows_and_light_are_for_the_screen_only(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    monkeypatch.setattr(view2d, "_paint_contact_shadow", lambda *a: calls.append("shadow"))
    monkeypatch.setattr(view2d, "_paint_body_light", lambda *a: calls.append("light"))
    doc = _example("ne555-astable")

    _on_screen(view2d.BoardScene(doc, LOOKUP, side="top"))
    assert "shadow" in calls and "light" in calls

    calls.clear()
    _on_paper(doc, view2d.BoardScene(doc, LOOKUP, side="top"), tmp_path)
    assert not calls, "the 1:1 print shaded a part"


def test_far_face_copper_is_quieter_on_screen_only(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    seen: list[tuple[bool, float]] = []
    real = view2d.ConductorItem._paint_conductor

    def record(item, painter):  # type: ignore[no-untyped-def]
        seen.append((item.is_far_side(), painter.opacity()))
        real(item, painter)

    monkeypatch.setattr(view2d.ConductorItem, "_paint_conductor", record)
    doc = _example("atmega328-relay")

    _on_screen(view2d.BoardScene(doc, LOOKUP, side="top"))
    far = {round(opacity, 2) for is_far, opacity in seen if is_far}
    near = {round(opacity, 2) for is_far, opacity in seen if not is_far}
    assert far == {view2d.FAR_SIDE_OPACITY}
    assert not near or near == {1.0}

    seen.clear()
    _on_paper(doc, view2d.BoardScene(doc, LOOKUP, side="top"), tmp_path)
    assert seen and {round(opacity, 2) for _far, opacity in seen} == {1.0}


def test_a_dip_says_its_value_on_its_top(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    marked: list[str] = []
    real = view2d._paint_top_marking

    def record(painter, footprint, placement, comp, rect=None):  # type: ignore[no-untyped-def]
        if footprint.body.archetype == "dip":
            marked.append(comp.ref)
        real(painter, footprint, placement, comp, rect)

    monkeypatch.setattr(view2d, "_paint_top_marking", record)
    doc = _example("atmega328-relay")
    _on_screen(view2d.BoardScene(doc, LOOKUP, side="top"))
    dips = {
        c.ref for c in doc.components
        if (fp := LOOKUP(c.footprint_id)) is not None and fp.body.archetype == "dip"
    }
    assert dips and set(marked) == dips


def test_references_are_outlined_on_screen_and_plated_on_paper(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    outlined: list[str] = []
    printed: list[str] = []
    real_outlined = view2d.draw_outlined_reference
    real_printed = view2d.draw_printed_reference

    def record_outlined(painter, anchor, reference, value, px, **kwargs):  # type: ignore[no-untyped-def]
        outlined.append(reference)
        real_outlined(painter, anchor, reference, value, px, **kwargs)

    def record_printed(painter, anchor, reference, *args, **kwargs):  # type: ignore[no-untyped-def]
        printed.append(reference)
        real_printed(painter, anchor, reference, *args, **kwargs)

    monkeypatch.setattr(view2d, "draw_outlined_reference", record_outlined)
    monkeypatch.setattr(view2d, "draw_printed_reference", record_printed)
    doc = _example("ne555-astable")
    refs = {c.ref for c in doc.components}

    _on_screen(view2d.BoardScene(doc, LOOKUP, side="top"))
    assert set(outlined) == refs and not printed

    outlined.clear()
    _on_paper(doc, view2d.BoardScene(doc, LOOKUP, side="top"), tmp_path)
    assert set(printed) == refs and not outlined
