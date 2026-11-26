"""The command palette is put away the way a palette is (``ui/palette.py``).

It used to close only on Escape with the keyboard in its field, on Enter, or on running an
item: a click on the board left it standing over the board, and once the keyboard was in
the list Escape did nothing. These hold it to closing on a click outside (which still lands
on what was clicked), on Escape or Ctrl+K from anywhere in it, and on the window losing the
foreground -- and to listening to the application only while it is open.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPushButton,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

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


def _host_with_toggler() -> tuple[_Host, QPushButton]:
    host = _open_host()
    toggler = QPushButton("Search", host)
    toggler.move(10, 10)
    toggler.show()
    toggler.clicked.connect(lambda: host.commands.toggle())
    host.commands.toggled_by(toggler)
    return host, toggler


def test_the_button_that_opens_it_closes_it() -> None:
    """The header's search: its press closed the palette as a click outside, and its click
    on the release opened it again, so it could not be put away from where it came."""
    host, toggler = _host_with_toggler()
    try:
        QTest.mouseClick(toggler, Qt.MouseButton.LeftButton)
        QTest.qWait(0)
        assert host.commands.isHidden()
        QTest.mouseClick(toggler, Qt.MouseButton.LeftButton)
        QTest.qWait(0)
        assert host.commands.isVisible()
    finally:
        host.close()


def test_a_press_on_the_button_dragged_off_does_not_eat_the_next_opening() -> None:
    host, toggler = _host_with_toggler()
    try:
        QTest.mousePress(toggler, Qt.MouseButton.LeftButton)
        assert host.commands.isHidden()
        QTest.mouseMove(toggler, QPoint(-50, -50))
        QTest.mouseRelease(toggler, Qt.MouseButton.LeftButton, pos=QPoint(-50, -50))
        QTest.qWait(0)
        host.commands.toggle()
        assert host.commands.isVisible()
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


def _on_top(host: _Host) -> bool:
    widgets = [child for child in host.children() if isinstance(child, QWidget)]
    return widgets[-1] is host.commands


def test_it_stays_over_a_tab_bar_made_after_it_opened() -> None:
    """A dock's tab bar is made when the panels are laid out again -- on leaving Home --
    and a widget made later stands over the ones before it: "Build Guide" was painted over
    the palette's top edge."""
    host = _open_host()
    try:
        bar = QTabBar(host)
        bar.addTab("Build Guide")
        bar.setGeometry(host.commands.geometry().adjusted(0, -10, 0, 0))
        bar.show()
        assert _on_top(host)
        host.button.raise_()
        assert _on_top(host)
    finally:
        host.close()


def test_it_is_painted_away_before_what_it_runs() -> None:
    """What runs from it -- an example opening -- can hold the event loop for seconds; the
    window must not still show the palette over the board meanwhile."""
    _app()
    host = _Host()
    # By its name, so it beats whatever theme an earlier test left on the application and
    # reaches no widget but the window itself.
    host.setObjectName("paintedAwayHost")
    host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    host.setStyleSheet("#paintedAwayHost { background: #ff00ff; }")
    seen: list[str] = []

    def look() -> None:
        image = host.screen().grabWindow(host.winId()).toImage()
        seen.append(QColor(image.pixel(host.commands.geometry().center())).name())

    host.commands._entries_now = lambda: [Entry("Open the example", "File", "", look)]
    host.show()
    QTest.qWaitForWindowExposed(host)
    try:
        host.commands.open()
        QTest.qWait(50)
        image = host.screen().grabWindow(host.winId()).toImage()
        assert QColor(image.pixel(host.commands.geometry().center())).name() != "#ff00ff"
        host.commands.run_current()
        assert seen == ["#ff00ff"]
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


# ---------------------------------------------------------------------------
# What it lists: sections with nothing typed, groups when something is
# ---------------------------------------------------------------------------


def _noop() -> None:
    pass


def _listing() -> list[Entry]:
    return [
        Entry("New Board", "File", "Ctrl+N", _noop, key="File/New Board"),
        Entry("Undo", "Edit", "Ctrl+Z", _noop, key="Edit/Undo"),
        Entry("Auto-wire Everything", "Wiring", "", _noop, key="Wiring/Auto-wire Everything",
              suggested=True),
        Entry("Fit Board", "View \u25b8 Zoom", "F", _noop, key="View \u25b8 Zoom/Fit Board"),
        Entry("ne555-astable", "File \u25b8 Open Example", "", _noop, kind="example"),
        Entry("lamp.perf", "C:/boards", "", _noop, kind="file"),
        Entry("R1  10k", "Part on the board", "", _noop, kind="part"),
        Entry("Rail", "Net", "", _noop, kind="net"),
    ]


def test_nothing_typed_lists_recent_then_suggested_then_each_menu() -> None:
    from perfboard_studio.ui.palette import sections

    listed = sections(_listing(), "", recent=["Edit/Undo", "gone/Missing"],
                      suggested_title="Suggested for Wiring")
    assert [title for title, _ in listed] == [
        "Recent Commands", "Recent Files", "Suggested for Wiring",
        "File", "Edit", "Wiring", "View", "Examples", "Parts", "Nets",
    ]
    by_title = dict(listed)
    # A remembered command that is no longer offered is passed over, not shown empty.
    assert [entry.label for entry in by_title["Recent Commands"]] == ["Undo"]
    assert [entry.label for entry in by_title["Suggested for Wiring"]] == ["Auto-wire Everything"]
    # A menu's section is its top level: a submenu's command is in its menu.
    assert [entry.label for entry in by_title["View"]] == ["Fit Board"]


def test_an_empty_section_is_left_out() -> None:
    from perfboard_studio.ui.palette import sections

    commands = [entry for entry in _listing() if entry.kind == "command" and not entry.suggested]
    titles = [title for title, _ in sections(commands, "")]
    assert titles == ["File", "Edit", "View"]


def test_typed_groups_by_kind_with_the_best_match_first() -> None:
    from perfboard_studio.ui.palette import sections

    listed = sections(_listing(), "r1")
    assert listed[0][0] == "Parts"
    # The names first, then what only says it where it lives (a folder, "on the board").
    listed = sections(_listing(), "board")
    assert [title for title, _ in listed] == ["Commands", "Parts", "Recent Files"]
    # rank's order inside the group, ties in the order the menus list them.
    assert [entry.label for entry in listed[0][1]] == ["New Board", "Fit Board"]
    listed = sections(_listing(), "ne555")
    assert [title for title, _ in listed] == ["Examples"]


def test_recent_commands_are_capped() -> None:
    from perfboard_studio.ui.palette import RECENT_LIMIT, sections

    many = [Entry(f"Do {n}", "Edit", "", _noop, key=f"Edit/Do {n}") for n in range(9)]
    listed = dict(sections(many, "", recent=[entry.key for entry in many]))
    assert len(listed["Recent Commands"]) == RECENT_LIMIT


def test_a_shortcut_is_said_as_keycaps() -> None:
    from perfboard_studio.ui.palette import keycaps

    assert keycaps("Ctrl+Shift+R") == ["Ctrl", "Shift", "R"]
    assert keycaps("Ctrl++") == ["Ctrl", "+"]
    assert keycaps("F") == ["F"]
    assert keycaps("Ctrl+K, Ctrl+G") == ["Ctrl", "K"]
    assert keycaps("") == []


def _sectioned_host(remembered: list[str]) -> _Host:
    host = _open_host()
    host.commands._entries_now = _listing
    host.commands._remember = remembered.append
    host.commands.close_palette()
    host.commands.open()
    return host


def test_a_header_is_not_a_row() -> None:
    from perfboard_studio.ui.palette import ROLE_HEADER

    host = _sectioned_host([])
    try:
        palette = host.commands
        header = palette.list.item(0)
        assert header.data(ROLE_HEADER)
        assert header.flags() == Qt.ItemFlag.NoItemFlags
        # The first ROW is current, not the header above it.
        assert palette.list.currentRow() == 1
        palette._run_item(header)
        assert palette.isVisible()
        # Every entry once, and the suggested one again in its menu, where it lives.
        assert len(palette.shown()) == len(_listing()) + 1
        assert palette.headers()[:3] == ["Recent Files", "Suggested", "File"]
    finally:
        host.close()


def test_the_arrows_step_over_the_headers() -> None:
    host = _sectioned_host([])
    try:
        palette = host.commands
        seen = []
        for _ in range(len(_listing()) + 3):
            seen.append(palette.list.currentItem().data(Qt.ItemDataRole.UserRole))
            QTest.keyClick(palette.field, Qt.Key.Key_Down)
        assert all(isinstance(entry, Entry) for entry in seen)
        # Down past the last row stays on it; Up from the first stays there too.
        assert seen[-1] is palette.shown()[-1]
        for _ in range(len(_listing()) + 3):
            QTest.keyClick(palette.field, Qt.Key.Key_Up)
        assert palette.list.currentItem().data(Qt.ItemDataRole.UserRole) is palette.shown()[0]
    finally:
        host.close()


def test_running_a_command_remembers_it_and_a_part_is_not() -> None:
    remembered: list[str] = []
    host = _sectioned_host(remembered)
    try:
        palette = host.commands
        palette.field.setText("undo")
        palette.run_current()
        assert remembered == ["Edit/Undo"]
        palette.open()
        palette.field.setText("r1")
        palette.run_current()
        assert remembered == ["Edit/Undo"]
    finally:
        host.close()


def test_the_window_remembers_what_was_run_and_suggests_for_its_step() -> None:
    from pathlib import Path

    from perfboard_studio import persist
    from perfboard_studio.ui.main import MainWindow
    from perfboard_studio.ui.workflow import step_title

    _app()
    root = Path(__file__).resolve().parents[1]
    loaded = persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    from perfboard_studio.ui import main as main_module

    examples = sorted((root / "examples").glob("*.perf"))[:2]
    gone = root / "examples" / "no-such-board.perf"
    main_module.app_settings().setValue(
        main_module.RECENT_FILES_KEY, [str(path) for path in (*examples, gone)]
    )
    window = MainWindow(loaded)
    try:
        palette = window.command_palette
        window.act_palette.trigger()
        # The files last opened, by name, and one that has gone away left out.
        assert "Recent Files" in palette.headers()
        assert [entry.label for entry in palette.shown() if entry.kind == "file"] == [
            path.name for path in examples
        ]
        step = window.workflow_bar.next_key
        title = f"Suggested for {step_title(step)}"
        assert title in palette.headers()
        assert "Recent Commands" not in palette.headers()
        palette.field.setText("Fit")
        chosen = palette.shown()[0]
        assert chosen.kind == "command" and chosen.key
        palette.run_current()
        assert window._palette_recent() == [chosen.key]
        window.act_palette.trigger()
        headers = palette.headers()
        assert headers[0] == "Recent Commands"
        assert palette.shown()[0].key == chosen.key
        palette.close_palette()
    finally:
        _discard(window)


def test_a_command_wins_a_tie_over_an_example_listed_before_it() -> None:
    from perfboard_studio.ui.palette import rank

    example = Entry("relay-and-supply", "File \u25b8 Open Example", "", _noop, kind="example")
    recent = Entry("rotary.perf", "C:/boards", "", _noop, kind="file")
    rotate = Entry("Rotate", "Edit", "R", _noop, key="Edit/Rotate")
    assert [entry.label for entry in rank([example, recent, rotate], "r")] == [
        "Rotate", "relay-and-supply", "rotary.perf",
    ]


def test_the_headers_search_opens_it_and_puts_it_away() -> None:
    from pathlib import Path

    from perfboard_studio import persist
    from perfboard_studio.ui.main import MainWindow

    _app()
    root = Path(__file__).resolve().parents[1]
    loaded = persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    window = MainWindow(loaded)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    window.show()
    QTest.qWaitForWindowExposed(window)
    try:
        palette = window.command_palette
        search = window.header.search
        QTest.mouseClick(search, Qt.MouseButton.LeftButton)
        QTest.qWait(0)
        assert palette.isVisibleTo(window)
        QTest.mouseClick(search, Qt.MouseButton.LeftButton)
        QTest.qWait(0)
        assert not palette.isVisibleTo(window)
    finally:
        _discard(window)
