"""The header over Home (``ui/header.py``): the application's name, the search in the middle,
Home's quick actions and the theme, and how the row fits a narrow window."""

from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from perfboard_studio.ui import icons

from .test_ui import _close, _load_dense, _settle_events, _window_on


@pytest.fixture(scope="module", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication(["perfboard-studio-tests"])


def _text_measures() -> bool:
    """Qt's offscreen plugin ships no font database on Windows, so every glyph measures as a
    box and a label is far wider than it ever is on screen (see ``test_ui``'s skips). A test
    that asks whether WORDS fit asks only where text has real widths."""
    app = QApplication.instance()
    return not (sys.platform == "win32" and app is not None and app.platformName() == "offscreen")


def _home_window(monkeypatch, width: int):
    from perfboard_studio.ui.main import MainWindow

    monkeypatch.setattr(MainWindow, "_create_3d_widget", lambda self: None)
    window = _window_on(_load_dense())
    window.resize(width, 820)
    window.show()
    window.on_home()
    _settle_events(QApplication)
    return window


def _shown(header) -> list[QWidget]:
    layout = header.layout()
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    return [
        w for w in widgets
        if w is not None and not w.isHidden() and w.objectName() != "headerGap"
    ]


def _nothing_overlaps(header) -> None:
    rects: list[tuple[str, QRect]] = [(w.objectName(), w.geometry()) for w in _shown(header)]
    for name, rect in rects:
        assert rect.right() < header.width(), f"{name} runs past the header's end"
        assert rect.left() >= 0
    for i, (a, ra) in enumerate(rects):
        for b, rb in rects[i + 1:]:
            assert not ra.intersects(rb), f"{a} overlaps {b}"


def test_over_home_the_row_names_the_application_and_centres_the_search(monkeypatch) -> None:
    window = _home_window(monkeypatch, 1380)
    try:
        header = window.header
        assert not header.app_icon.isHidden() and not header.app_name.isHidden()
        assert header.app_name.text() == "Perfboard Studio"
        assert [b.isHidden() for b in header.quick_buttons] == [False, False, False]
        assert not header.theme_button.isHidden()
        if _text_measures():
            assert all(
                b.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                for b in header.quick_buttons
            )
        centre = header.search.geometry().center().x()
        assert abs(centre - header.width() // 2) <= 2
        _nothing_overlaps(header)
    finally:
        _close(window)


def test_over_a_board_the_icon_stays_and_home_s_actions_go(monkeypatch) -> None:
    window = _home_window(monkeypatch, 1380)
    try:
        window.leave_home()
        _settle_events(QApplication)
        header = window.header
        assert not header.app_icon.isHidden()
        assert header.app_name.isHidden()  # the steps need the room
        assert all(b.isHidden() for b in header.quick_buttons)
        assert header.theme_button.isHidden()
        assert not header.steps.isHidden()
        window.on_home()
        _settle_events(QApplication)
        assert not header.app_name.isHidden()
        assert all(not b.isHidden() for b in header.quick_buttons)
    finally:
        _close(window)


@pytest.mark.parametrize("width", [1000, 860, 700, 560])
def test_a_narrow_row_sheds_words_before_anything_overlaps(monkeypatch, width) -> None:
    window = _home_window(monkeypatch, width)
    try:
        header = window.header
        _nothing_overlaps(header)
        if width <= 560 or not _text_measures():
            assert all(
                b.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
                for b in header.quick_buttons
            )
            # Every word a button lost is still its tooltip.
            assert all(b.toolTip() for b in header.quick_buttons)
        if width == 1000:
            assert abs(header.search.geometry().center().x() - header.width() // 2) <= 2
    finally:
        _close(window)


def test_the_theme_button_runs_the_view_menu_s_choice(monkeypatch) -> None:
    from perfboard_studio.ui import main as main_module

    told: list[str] = []
    monkeypatch.setattr(
        main_module.QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: told.append(args[1]) or QMessageBox.StandardButton.Ok),
    )
    window = _home_window(monkeypatch, 1380)
    try:
        header = window.header
        start = header.chosen_theme()
        assert start in ("dark", "light")
        other = "light" if start == "dark" else "dark"
        expected = icons.icon("sun" if start == "dark" else "moon")
        assert header.theme_button.icon().cacheKey() == expected.cacheKey()
        assert other in header.theme_button.toolTip().lower()
        header.theme_button.click()
        # The View menu's tick moved: the button and the menu are one choice.
        assert window.act_theme[other].isChecked()
        assert not window.act_theme[start].isChecked()
        assert header.chosen_theme() == other
        assert len(told) == 1  # the same "from the next start" note the menu gives
        assert start in header.theme_button.toolTip().lower()
    finally:
        _close(window)


def test_home_s_quick_actions_send_home_s_own_signals(monkeypatch) -> None:
    window = _home_window(monkeypatch, 1380)
    try:
        sent: list[str] = []

        class _Door:
            def __init__(self, name: str) -> None:
                self.name = name

            def emit(self) -> None:
                sent.append(self.name)

        class _Home:
            newCircuit = _Door("newCircuit")
            openFile = _Door("openFile")
            startTour = _Door("startTour")

        real = window._home_page
        window._home_page = _Home()
        try:
            for button in window.header.quick_buttons:
                button.click()
        finally:
            window._home_page = real
        assert sent == ["newCircuit", "openFile", "startTour"]
    finally:
        _close(window)


def test_homes_quick_actions_and_the_theme_switch_ease_their_hover_like_the_rest(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui import hover

    window = _home_window(monkeypatch, 1380)
    try:
        header = window.header
        for button in (*header.quick_buttons, header.theme_button, header.home_button):
            assert button.property("fade") is True, button.objectName()
            assert button.findChild(hover._Fade) is not None
    finally:
        _close(window)
