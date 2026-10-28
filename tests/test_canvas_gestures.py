"""What the pointer and the wheel mean on the two canvases, the board and the sheet.

Pinned here, against real Qt events sent to each view's viewport:

- a mouse wheel turning whole notches zooms, as it always did; anything finer -- a
  trackpad's two fingers -- pans, and Ctrl (a pinch, on Windows) zooms again;
- Space held turns the left button into the hand, on both canvases, so a laptop with no
  middle button can pan, and letting it go gives the left button back to selecting;
- the board and the sheet read a wheel event through one function
  (``canvasinput.wheel_intent``), so they cannot disagree about it.
"""

from __future__ import annotations

import os
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.schematic import build_schematic
from perfboard_studio.ui.canvasinput import NOTCH, WheelIntent, wheel_intent
from perfboard_studio.ui.view2d import BoardScene, BoardView
from perfboard_studio.ui.viewsch import SchematicView

GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "tools" / "diffcheck" / "golden" / "dense.perf"
LEFT = Qt.MouseButton.LeftButton
NONE = Qt.MouseButton.NoButton
NO_KEYS = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


@pytest.fixture(scope="module", autouse=True)
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication(["perfboard-studio-tests"])
    return app  # type: ignore[return-value]


def _wheel(
    angle: tuple[int, int] = (0, 0),
    pixels: tuple[int, int] = (0, 0),
    modifiers: Qt.KeyboardModifier = NO_KEYS,
    at: QPoint | None = None,
    phase: Qt.ScrollPhase = Qt.ScrollPhase.NoScrollPhase,
) -> QWheelEvent:
    point = QPointF(at if at is not None else QPoint(200, 150))
    return QWheelEvent(
        point, point, QPoint(*pixels), QPoint(*angle), NONE, modifiers, phase, False
    )


def _mouse(widget: QWidget, kind: QEvent.Type, at: QPoint, buttons: Qt.MouseButton) -> None:
    button = NONE if kind == QEvent.Type.MouseMove else LEFT
    QApplication.sendEvent(
        widget, QMouseEvent(kind, QPointF(at), QPointF(widget.mapToGlobal(at)), button, buttons, NO_KEYS)
    )


def _drag(widget: QWidget, start: QPoint, end: QPoint) -> None:
    _mouse(widget, QEvent.Type.MouseButtonPress, start, LEFT)
    for step in range(1, 6):
        _mouse(widget, QEvent.Type.MouseMove, start + (end - start) * step / 5, LEFT)
    _mouse(widget, QEvent.Type.MouseButtonRelease, end, NONE)


def _key(widget: QWidget, kind: QEvent.Type, key: Qt.Key) -> None:
    QApplication.sendEvent(widget, QKeyEvent(kind, key, NO_KEYS))


# -- the rule ------------------------------------------------------------------------------


def test_a_mouse_wheel_notch_zooms() -> None:
    assert wheel_intent(_wheel(angle=(0, NOTCH))) == WheelIntent(zoom_steps=1.0)
    assert wheel_intent(_wheel(angle=(0, -2 * NOTCH))) == WheelIntent(zoom_steps=-2.0)


def test_two_fingers_pan_whichever_way_the_platform_reports_them() -> None:
    """Pixel deltas (macOS, Wayland), a fraction of a notch (a Windows precision
    touchpad), a sideways component, or a scroll phase: each is a trackpad, and pans."""
    assert wheel_intent(_wheel(angle=(0, -30), pixels=(0, -12))) == WheelIntent(pan_y=-12.0)
    fraction = wheel_intent(_wheel(angle=(0, 48)))
    assert fraction.zoom_steps == 0 and fraction.pan_y > 0
    sideways = wheel_intent(_wheel(angle=(NOTCH, 0)))
    assert sideways.zoom_steps == 0 and sideways.pan_x > 0 and sideways.pan_y == 0
    phased = wheel_intent(_wheel(angle=(0, NOTCH), phase=Qt.ScrollPhase.ScrollUpdate))
    assert phased.zoom_steps == 0 and phased.pan_y > 0


def test_ctrl_zooms_from_anything_and_a_pinch_by_what_it_amounts_to() -> None:
    """Windows sends a trackpad pinch as Ctrl+wheel in small steps: each is a fraction of
    a notch's zoom, so a pinch adds up instead of racing."""
    assert wheel_intent(_wheel(angle=(0, NOTCH), modifiers=CTRL)) == WheelIntent(zoom_steps=1.0)
    assert wheel_intent(_wheel(angle=(0, 30), modifiers=CTRL)) == WheelIntent(zoom_steps=0.25)
    assert wheel_intent(_wheel(angle=(0, -12), pixels=(0, -5), modifiers=CTRL)).zoom_steps < 0


def test_shift_turns_the_wheel_sideways() -> None:
    intent = wheel_intent(_wheel(angle=(0, NOTCH), modifiers=SHIFT))
    assert intent.zoom_steps == 0 and intent.pan_y == 0 and intent.pan_x > 0


# -- the board -----------------------------------------------------------------------------


def _board_view() -> BoardView:
    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    view = BoardView(BoardScene(document, footprint_lookup(), side="top"))
    view.resize(500, 400)
    view.show()
    # Zoomed in, so there is somewhere to pan to.
    view.resetTransform()
    view.scale(20, 20)
    view.centerOn(view.sceneRect().center())
    QApplication.processEvents()
    return view


def _scroll(view: BoardView | SchematicView) -> tuple[int, int]:
    return view.horizontalScrollBar().value(), view.verticalScrollBar().value()


def test_two_fingers_pan_the_board_and_leave_its_zoom_alone() -> None:
    view = _board_view()
    try:
        scale, scroll = view.current_scale(), _scroll(view)
        QApplication.sendEvent(view.viewport(), _wheel(angle=(0, -40), pixels=(0, -40)))
        assert view.current_scale() == pytest.approx(scale)
        assert _scroll(view)[1] == scroll[1] + 40

        QApplication.sendEvent(view.viewport(), _wheel(angle=(0, NOTCH)))
        assert view.current_scale() == pytest.approx(scale * 1.15)
    finally:
        view.close()


def test_space_turns_the_left_button_into_the_hand_on_the_board() -> None:
    """And only while it is held: let go, and the same drag is a rubber band again."""
    view = _board_view()
    try:
        port = view.viewport()
        view.setFocus()
        before = _scroll(view)
        _key(view, QEvent.Type.KeyPress, Qt.Key.Key_Space)
        assert port.cursor().shape() == Qt.CursorShape.OpenHandCursor
        _drag(port, QPoint(300, 250), QPoint(200, 150))
        assert _scroll(view) == (before[0] + 100, before[1] + 100)
        assert not view.board_scene.selectedItems()
        _key(view, QEvent.Type.KeyRelease, Qt.Key.Key_Space)
        assert port.cursor().shape() == Qt.CursorShape.ArrowCursor

        panned = _scroll(view)
        _drag(port, QPoint(20, 20), QPoint(480, 380))
        assert _scroll(view) == panned
        assert view.board_scene.selectedItems()
    finally:
        view.close()


def test_a_pan_gives_an_armed_tool_its_cross_back() -> None:
    """A pan used to unset the cursor outright, so a part being placed lost its cross the
    first time the board was panned under it."""
    view = _board_view()
    try:
        view.board_scene.arm_measure(True)
        port = view.viewport()
        port.setCursor(Qt.CursorShape.CrossCursor)
        view.setFocus()
        _key(view, QEvent.Type.KeyPress, Qt.Key.Key_Space)
        _drag(port, QPoint(300, 250), QPoint(250, 200))
        _key(view, QEvent.Type.KeyRelease, Qt.Key.Key_Space)
        assert port.cursor().shape() == Qt.CursorShape.CrossCursor
        # The press that panned was not a measurement.
        assert view.board_scene.measure_from() is None
    finally:
        view.close()


def test_a_space_released_elsewhere_does_not_leave_the_board_panning() -> None:
    view = _board_view()
    try:
        view.setFocus()
        _key(view, QEvent.Type.KeyPress, Qt.Key.Key_Space)
        QApplication.sendEvent(view, QEvent(QEvent.Type.FocusOut))
        before = _scroll(view)
        _drag(view.viewport(), QPoint(20, 20), QPoint(480, 380))
        assert _scroll(view) == before
    finally:
        view.close()


# -- the sheet -----------------------------------------------------------------------------


def _sheet_view() -> SchematicView:
    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    view = SchematicView()
    view.resize(500, 400)
    view.show()
    view.set_drawing(build_schematic(document, footprint_lookup()))
    view.resetTransform()
    view.scale(12, 12)
    view._hand_over_framing()
    view.centerOn(view.sceneRect().center())
    QApplication.processEvents()
    return view


def test_two_fingers_pan_the_sheet_and_leave_its_zoom_alone() -> None:
    view = _sheet_view()
    try:
        scale, scroll = view.current_scale(), _scroll(view)
        QApplication.sendEvent(view.viewport(), _wheel(angle=(-36, 0), pixels=(-30, 0)))
        assert view.current_scale() == pytest.approx(scale)
        assert _scroll(view)[0] == scroll[0] + 30

        QApplication.sendEvent(view.viewport(), _wheel(angle=(0, NOTCH)))
        assert view.current_scale() == pytest.approx(scale * 1.18)
    finally:
        view.close()


def test_space_turns_the_left_button_into_the_hand_on_the_sheet() -> None:
    view = _sheet_view()
    try:
        view.setFocus()
        before = _scroll(view)
        _key(view, QEvent.Type.KeyPress, Qt.Key.Key_Space)
        assert view.cursor().shape() == Qt.CursorShape.OpenHandCursor
        _drag(view.viewport(), QPoint(300, 250), QPoint(220, 190))
        assert _scroll(view) == (before[0] + 80, before[1] + 60)
        assert view.selected_refs == []
        _key(view, QEvent.Type.KeyRelease, Qt.Key.Key_Space)
        assert view.cursor().shape() == Qt.CursorShape.ArrowCursor
    finally:
        view.close()

