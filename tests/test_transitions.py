"""Wave 2 transitions: the command palette and the Problems drawer.

Every one of them asks ``motion`` first, so the suite (reduced) sees the end state at once;
the tests here turn motion on to watch the way there, then check the end state is exactly
the one the reduced path gives.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

from perfboard_studio.ui import motion
from perfboard_studio.ui.palette import DROP_PX, CommandPalette, Entry


@pytest.fixture(scope="module", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication(["perfboard-studio-tests"])


@pytest.fixture()
def moving() -> Iterator[None]:
    motion.set_reduced(False)
    try:
        yield
    finally:
        motion.reset()


def _palette() -> tuple[QWidget, CommandPalette]:
    host = QWidget()
    host.resize(1000, 700)
    palette = CommandPalette(host, lambda: [Entry("Fit Board", "View", "F", lambda: None)])
    host.show()
    return host, palette


def _shadow_alpha(palette: CommandPalette) -> int:
    shadow = palette.graphicsEffect()
    assert isinstance(shadow, QGraphicsDropShadowEffect)
    return shadow.color().alpha()


def test_the_palette_opens_in_place_when_motion_is_reduced() -> None:
    host, palette = _palette()
    try:
        full = _shadow_alpha(palette)
        palette.open()
        assert palette._opening is None
        assert palette.isVisible()
        landing = palette.pos()
        assert _shadow_alpha(palette) == full
        palette.close_palette()
        palette.open()
        assert palette.pos() == landing
    finally:
        host.close()


def test_the_palette_drops_into_place_and_lands_where_the_still_one_stands(moving) -> None:
    host, palette = _palette()
    try:
        full = _shadow_alpha(palette)
        palette.open()
        animation = palette._opening
        assert animation is not None
        landing_y = palette.y() + DROP_PX
        assert _shadow_alpha(palette) == 0
        # The field has the keyboard from the first frame: typing never waits on the drop.
        assert palette.field.hasFocus() or not host.isActiveWindow()
        animation.setCurrentTime(animation.duration() // 2)
        assert palette.y() < landing_y
        assert 0 < _shadow_alpha(palette) < full
        animation.setCurrentTime(animation.duration())
        assert palette.y() == landing_y
        assert _shadow_alpha(palette) == full
    finally:
        host.close()


def test_closing_mid_drop_leaves_the_palette_whole_for_next_time(moving) -> None:
    host, palette = _palette()
    try:
        full = _shadow_alpha(palette)
        palette.open()
        landing_y = palette.y() + DROP_PX
        palette.close_palette()
        assert palette._opening is None
        assert not palette.isVisible()
        assert _shadow_alpha(palette) == full
        motion.set_reduced(True)
        palette.open()
        assert palette.y() == landing_y
    finally:
        host.close()


def _finish(window) -> None:
    animation = window._drawer_motion
    assert animation is not None
    animation.setCurrentTime(animation.duration())
    QApplication.processEvents()


def test_the_problems_drawer_slides_to_the_heights_the_still_one_takes(monkeypatch) -> None:
    """Folding and opening with motion on pass through the heights between and land on
    the same two the reduced drawer jumps to: the bar, capped, and the opened height."""
    from perfboard_studio.ui.problems import BAR_HEIGHT

    from .test_ui import _close, _settle_events, _shown_window_without_3d

    window = _shown_window_without_3d(monkeypatch)
    try:
        window.set_problems_open(True)
        _settle_events(QApplication)
        assert window._drawer_motion is None
        opened = window.dock_drc.height()
        assert opened > BAR_HEIGHT

        motion.set_reduced(False)
        window.set_problems_open(False)
        animation = window._drawer_motion
        assert animation is not None
        # The list stays in view as it slides down; the caps go on only as it lands.
        assert window.drc_panel.maximumHeight() > 0
        animation.setCurrentTime(animation.duration() // 2)
        QApplication.processEvents()
        assert BAR_HEIGHT < window.dock_drc.height() < opened
        _finish(window)
        assert window._drawer_motion is None
        assert window.drc_panel.maximumHeight() == 0
        assert window.dock_drc.maximumHeight() == BAR_HEIGHT

        window.set_problems_open(True)
        QApplication.processEvents()
        assert window._drawer_motion is not None
        _finish(window)
        _settle_events(QApplication)
        assert window._drawer_motion is None
        assert window.dock_drc.height() == opened

        # Folded mid-slide: the slide open is dropped and the fold takes over from there.
        window.set_problems_open(False)
        window.set_problems_open(True)
        QApplication.processEvents()
        window.set_problems_open(False)
        _finish(window)
        assert window.dock_drc.maximumHeight() == BAR_HEIGHT
        assert not window.problems_bar.expanded
    finally:
        motion.reset()
        _close(window)


# -- the copper an Auto-wire lays ------------------------------------------------------


def _wired_window(monkeypatch):
    """A window on screen, on a board with copper on it, the 3D panel stubbed."""
    from perfboard_studio.ui.main import MainWindow

    from .test_ui import _load_dense, _settle_events, _window_on

    monkeypatch.setattr(MainWindow, "_create_3d_widget", lambda self: None)
    window = _window_on(_load_dense())
    window.resize(1600, 950)
    window.show()
    _settle_events(QApplication)
    assert window.view.isVisible()
    return window


def _opacities(scene, ids) -> list[float]:
    return [scene.conductor_items[cid].opacity() for cid in ids]


def test_new_copper_fades_in_one_conductor_after_another(monkeypatch, moving) -> None:
    from .test_ui import _close

    window = _wired_window(monkeypatch)
    try:
        scene = window.scene
        conductors = window.bus.document.conductors
        assert len(conductors) >= 3
        # What a route that laid the last three looks like to the window.
        laid = [c.id for c in conductors[-3:]]
        window._remember_wiring_before(conductors[:-3])
        assert scene.revealing
        assert scene._reveal_ids == tuple(laid)
        # The copper that was there already is not touched.
        assert all(o == 1.0 for o in _opacities(scene, [c.id for c in conductors[:-3]]))
        assert _opacities(scene, laid) == [0.0, 0.0, 0.0]
        # Partway: the first is further in than the last, in the plan's order.
        scene._reveal_at(scene._reveal_step_ms * 2 + 60)
        first, middle, last = _opacities(scene, laid)
        assert 1.0 >= first > middle > last >= 0.0
        # A rebuild in the middle keeps the reveal where it is, on the NEW items.
        assert scene._reveal is not None
        scene._reveal.setCurrentTime(100)
        before = _opacities(scene, laid)
        scene.set_document(window.bus.document)
        assert scene.revealing
        assert _opacities(scene, laid) == pytest.approx(before)
        # Over: every conductor at full strength, as the still window draws it.
        scene.stop_reveal()
        assert not scene.revealing
        assert all(o == 1.0 for o in _opacities(scene, [c.id for c in conductors]))
    finally:
        _close(window)


def test_new_copper_is_simply_there_when_motion_is_reduced(monkeypatch) -> None:
    from .test_ui import _close

    window = _wired_window(monkeypatch)
    try:
        conductors = window.bus.document.conductors
        window._remember_wiring_before(conductors[:-3])
        assert not window.scene.revealing
        assert all(o == 1.0 for o in _opacities(window.scene, [c.id for c in conductors]))
    finally:
        _close(window)


def test_the_reveal_runs_out_and_leaves_the_copper_whole(monkeypatch, moving) -> None:
    from PySide6.QtCore import QElapsedTimer

    from perfboard_studio.ui.view2d import REVEAL_SPAN_MS

    from .test_ui import _close

    window = _wired_window(monkeypatch)
    try:
        scene = window.scene
        conductors = window.bus.document.conductors
        window.scene.reveal_conductors([c.id for c in conductors])
        assert scene.revealing
        # However many conductors, the whole thing is over within the span.
        assert scene._reveal is not None and scene._reveal.duration() <= REVEAL_SPAN_MS
        clock = QElapsedTimer()
        clock.start()
        while scene.revealing and clock.elapsed() < REVEAL_SPAN_MS + 2000:
            QApplication.processEvents()
        assert not scene.revealing
        assert all(o == 1.0 for o in _opacities(scene, [c.id for c in conductors]))
    finally:
        _close(window)
