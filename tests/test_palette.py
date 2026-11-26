"""The command palette is put away the way a palette is (``ui/palette.py``).

It used to close only on Escape with the keyboard in its field, on Enter, or on running an
item: a click on the board left it standing over the board, and once the keyboard was in
the list Escape did nothing. These hold it to closing on a click outside (which still lands
on what was clicked), on Escape or Ctrl+K from anywhere in it, and on the window losing the
foreground -- and to listening to the application only while it is open.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QVBoxLayout, QWidget

from perfboard_studio.ui.palette import CommandPalette, Entry


def _app() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication(["perfboard-studio-tests"])


class _Host(QWidget):
    """A window with something to click below where the palette stands."""

    def __init__(self) -> None:
        super().__init__()
        self.resize(1000, 700)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        self.button = QPushButton("Below")
        self.clicks: list[str] = []
        self.button.clicked.connect(lambda: self.clicks.append("below"))
        layout.addWidget(self.button)
        self.other_field = QLineEdit()
        layout.addWidget(self.other_field)
        self.ran: list[str] = []
        self.commands = CommandPalette(
            self,
            lambda: [
                Entry("Fit Board", "View", "F", lambda: self.ran.append("fit")),
                Entry("Zoom In", "View", "+", lambda: self.ran.append("zoom")),
            ],
        )


def _open_host() -> _Host:
    _app()
    host = _Host()
    host.show()
    host.activateWindow()
    QTest.qWaitForWindowExposed(host)
    host.commands.open()
    assert host.commands.isVisible()
    return host


def test_a_click_outside_closes_it_and_still_lands() -> None:
    host = _open_host()
    try:
        QTest.mouseClick(host.button, Qt.MouseButton.LeftButton)
        assert host.commands.isHidden()
        assert host.clicks == ["below"]
        assert host.ran == []
    finally:
        host.close()


def test_a_click_outside_keeps_the_keyboard_where_it_was_given() -> None:
    """Closing hands the keyboard back to the window only when it was in the palette: a
    click on another field has already given it there."""
    host = _open_host()
    try:
        QTest.mouseClick(host.other_field, Qt.MouseButton.LeftButton)
        assert host.commands.isHidden()
        if QApplication.focusWidget() is not None:
            assert QApplication.focusWidget() is host.other_field
    finally:
        host.close()


def test_a_click_inside_leaves_it_open() -> None:
    host = _open_host()
    try:
        QTest.mouseClick(host.commands.field, Qt.MouseButton.LeftButton)
        QTest.mouseClick(host.commands, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        assert host.commands.isVisible()
    finally:
        host.close()


def test_escape_from_the_list_closes_it() -> None:
    host = _open_host()
    try:
        host.commands.list.setFocus()
        QTest.keyClick(host.commands.list, Qt.Key.Key_Escape)
        assert host.commands.isHidden()
        assert host.ran == []
    finally:
        host.close()


def test_escape_from_the_field_still_closes_it() -> None:
    host = _open_host()
    try:
        QTest.keyClick(host.commands.field, Qt.Key.Key_Escape)
        assert host.commands.isHidden()
    finally:
        host.close()


def test_ctrl_k_inside_closes_it() -> None:
    host = _open_host()
    try:
        QTest.keyClick(host.commands.field, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        assert host.commands.isHidden()
        host.commands.open()
        host.commands.list.setFocus()
        QTest.keyClick(host.commands.list, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        assert host.commands.isHidden()
    finally:
        host.close()


def test_the_window_losing_the_foreground_closes_it() -> None:
    host = _open_host()
    try:
        QApplication.sendEvent(host, QEvent(QEvent.Type.WindowDeactivate))
        assert host.commands.isHidden()
    finally:
        host.close()


def test_toggle_opens_and_closes() -> None:
    host = _open_host()
    try:
        host.commands.toggle()
        assert host.commands.isHidden()
        host.commands.toggle(frozenset({"command"}))
        assert host.commands.isVisible()
    finally:
        host.close()


def test_it_listens_to_the_application_only_while_open() -> None:
    """Closed, a click anywhere is none of its business; and a window closed with the
    palette up does not leave it listening either."""
    host = _open_host()
    try:
        assert host.commands._watching
        host.commands.close_palette()
        assert not host.commands._watching
        host.commands.open()
        assert host.commands._watching
        host.hide()
        assert not host.commands._watching
    finally:
        host.close()


def _discard(window) -> None:  # type: ignore[no-untyped-def]
    """Close without the unsaved-work question, which waits forever offscreen."""
    window._saved_document = window.bus.system_document
    window.close()


def test_the_windows_ctrl_k_and_go_to_part_put_it_away_again() -> None:
    from pathlib import Path

    from perfboard_studio import persist
    from perfboard_studio.ui.main import MainWindow

    _app()
    root = Path(__file__).resolve().parents[1]
    loaded = persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    window = MainWindow(loaded)
    try:
        palette = window.command_palette
        assert window.act_palette.shortcut().toString() == "Ctrl+K"
        window.act_palette.trigger()
        assert palette.isVisibleTo(window)
        window.act_palette.trigger()
        assert not palette.isVisibleTo(window)
        window.on_go_to_part()
        assert palette.isVisibleTo(window)
        assert {entry.kind for entry in palette.shown()} == {"part"}
        window.on_go_to_part()
        assert not palette.isVisibleTo(window)
    finally:
        _discard(window)
