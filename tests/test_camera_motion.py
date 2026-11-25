"""Tests for smooth 2D camera flight and cosmetic target spotlight pulse."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import HoleCoord
from perfboard_studio.ui import motion
from perfboard_studio.ui.view2d import BoardScene, BoardView, print_scene
from perfboard_studio.ui.viewsch import SchematicView


def _app() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication([])


def _load_ne555():
    root = Path(__file__).resolve().parents[1]
    return persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )


def test_board_camera_flight_and_pulse_snap_under_reduced_motion() -> None:
    _app()
    assert motion.reduced() is True
    doc = _load_ne555()
    scene = BoardScene(doc, footprint_lookup(), side="top")
    view = BoardView(scene)
    view.resize(700, 500)
    view.show()
    try:
        view.fit_board(animate=False)
        fit_scale = view.current_scale()
        view.center_on_holes([HoleCoord(4, 4)], doc.board, "top")
        assert not view._camera.is_running
        assert not view._pulse.active
        assert view.current_scale() > fit_scale

        view.fit_board(animate=True)
        assert not view._camera.is_running
        assert view._fitted is True
    finally:
        view.close()


def test_board_camera_flies_smoothly_pulses_and_cancels_on_manual_input() -> None:
    _app()
    motion.set_reduced(False)
    doc = _load_ne555()
    scene = BoardScene(doc, footprint_lookup(), side="top")
    view = BoardView(scene)
    view.resize(700, 500)
    view.show()
    try:
        view.fit_board(animate=False)
        start_scale = view.current_scale()
        view.center_on_holes([HoleCoord(4, 4)], doc.board, "top")
        assert view._camera.is_running
        assert view._pulse.active

        QTest.qWait(90)
        mid_scale = view.current_scale()
        assert mid_scale > start_scale

        # Manual navigation cancels an in-flight camera immediately.
        view._pan_by(12.0, 0.0)
        assert not view._camera.is_running

        # Animated fit lands cleanly and restores _fitted = True on completion.
        view.fit_board(animate=True)
        assert view._camera.is_running
        assert view._fitted is False
        for _ in range(30):
            QTest.qWait(20)
            if not view._camera.is_running:
                break
        assert not view._camera.is_running
        assert view._fitted is True
    finally:
        view.close()
        motion.reset()


def test_spotlight_pulse_never_renders_on_print_scene() -> None:
    _app()
    motion.set_reduced(False)
    doc = _load_ne555()
    lookup = footprint_lookup()
    scene = BoardScene(doc, lookup, side="top")
    view = BoardView(scene)
    view.resize(600, 400)
    view.show()
    try:
        view.look_at(QPointF(20.0, 20.0), pulse=True)
        assert view._pulse.active
        # Print scenes render BoardScene directly without BoardView foreground pulses.
        paper = print_scene(doc, lookup, "top")
        img = QImage(200, 200, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        paper.render(painter)
        painter.end()
        assert not img.isNull()
    finally:
        view.close()
        motion.reset()


def test_schematic_view_camera_flight_and_focus_symbol() -> None:
    from perfboard_studio.schematic import build_schematic

    _app()
    motion.set_reduced(False)
    doc = _load_ne555()
    drawing = build_schematic(doc, footprint_lookup())
    view = SchematicView()
    view.resize(700, 500)
    view.show()
    try:
        view.set_drawing(drawing)
        view.fit(animate=False)
        view.zoom_by(1.5)
        assert view._camera.is_running
        for _ in range(25):
            QTest.qWait(15)
            if not view._camera.is_running:
                break
        assert not view._camera.is_running

        view.focus_symbol("U1")
        assert view._pulse.active
        view.fit(animate=True)
        assert view._camera.is_running
        for _ in range(30):
            QTest.qWait(20)
            if not view._camera.is_running:
                break
        assert not view._camera.is_running
        assert view._fitted is True and view._user_framed is False
    finally:
        view.close()
        motion.reset()
