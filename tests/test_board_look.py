"""The board's look on screen, and the 1:1 print that must not take it.

Chosen on 2026-10-28 from rendered looks: pads nothing lands in drawn quieter, bodies standing
on the board with a contact shadow and lit from the top left, a DIP's value on its top,
references outlined instead of plated, far-face copper quieter. The quiet pads, the shadow
and the light are for the eye on a screen. The 1:1 PDF is taped to the board in someone's
hand, so it shows every pad as the board has it and every part flat -- which is what most of
these hold.
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
from perfboard_studio.geometry import all_pin_holes, hole_key
from perfboard_studio.model import PerfDocument, contacts_every_path_hole
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


def test_a_pad_is_used_when_a_lead_a_run_or_a_wire_end_lands_in_it() -> None:
    doc = _example("atmega328-relay")
    used = view2d.used_holes(doc, LOOKUP)
    for comp in doc.components:
        footprint = LOOKUP(comp.footprint_id)
        assert footprint is not None
        for _pin, hole in all_pin_holes(comp, footprint):
            assert hole_key(hole) in used, comp.ref
    runs = [c for c in doc.conductors if contacts_every_path_hole(c) and len(c.path) > 2]
    wires = [c for c in doc.conductors if not contacts_every_path_hole(c) and len(c.path) > 2]
    assert runs and wires, "the example should have both, or this proves nothing"
    for run in runs:
        assert all(hole_key(hole) in used for hole in run.path)
    # A wire touches its two ends and only lies over the holes between them; a hole under
    # its middle that nothing else lands in stays quiet.
    pinned = {
        hole_key(hole)
        for comp in doc.components
        for _pin, hole in all_pin_holes(comp, LOOKUP(comp.footprint_id))  # type: ignore[arg-type]
    }
    soldered = {hole_key(h) for c in doc.conductors if contacts_every_path_hole(c) for h in c.path}
    ends = {hole_key(h) for c in doc.conductors for h in (c.path[0], c.path[-1]) if c.path}
    passed_over = {
        hole_key(h) for wire in wires for h in wire.path[1:-1]
    } - pinned - soldered - ends
    assert passed_over, "no wire passes over a hole nothing else uses"
    assert not passed_over & used


def test_the_screen_quiets_unused_pads_and_paper_does_not(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    asked: list[bool] = []
    real = view2d.PadGridItem._pad_for

    def record(item, long_px, quiet=False):  # type: ignore[no-untyped-def]
        asked.append(quiet)
        return real(item, long_px, quiet)

    monkeypatch.setattr(view2d.PadGridItem, "_pad_for", record)
    doc = _example("ne555-astable")

    _on_screen(view2d.BoardScene(doc, LOOKUP, side="top"))
    assert True in asked and False in asked

    asked.clear()
    _on_paper(doc, view2d.BoardScene(doc, LOOKUP, side="top"), tmp_path)
    assert asked, "the print drew no pads"
    assert True not in asked, "the 1:1 print quieted a pad"


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
