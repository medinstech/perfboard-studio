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
