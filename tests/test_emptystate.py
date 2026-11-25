"""What an empty panel says (ui/emptystate.py): the pattern, then each panel in the window."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

from perfboard_studio import persist
from perfboard_studio.model import PerfDocument
from perfboard_studio.ui.emptystate import EmptyOverlay, EmptyState

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def test_the_one_button_does_what_it_says() -> None:
    pressed: list[str] = []
    state = EmptyState(
        "Nothing here", "Two lines at most.",
        button=("Do It", lambda: pressed.append("button")),
        links=(("Or this", lambda: pressed.append("link")),),
    )
    assert state.button is not None
    state.button.click()
    state.links[0].click()
    assert pressed == ["button", "link"]


def test_an_empty_list_says_so_and_stops_once_it_has_a_row() -> None:
    tree = QTreeWidget()
    tree.resize(300, 200)
    overlay = EmptyOverlay.over_view(tree, EmptyState("No nets yet", "Join two pins."))
    assert not overlay.state.isHidden()
    tree.addTopLevelItem(QTreeWidgetItem(["GND"]))
    assert overlay.state.isHidden()
    tree.clear()
    assert not overlay.state.isHidden()
    assert overlay.state.geometry() == tree.viewport().rect()


def test_a_panel_with_more_than_one_reason_to_be_empty_can_change_its_words() -> None:
    state = EmptyState("A", "a", button=("Go", lambda: None))
    state.say("B", "b", button_shown=False)
    assert (state.title.text(), state.body.text()) == ("B", "b")
    assert state.button is not None and state.button.isHidden()



# -- an icon, and arriving rather than appearing ----------------------------------------


def _wait_for(done, timeout_ms: int) -> bool:  # type: ignore[no-untyped-def]
    from PySide6.QtTest import QTest

    for _ in range(timeout_ms // 10):
        if done():
            return True
        QTest.qWait(10)
    return bool(done())


def _shown_tree():  # type: ignore[no-untyped-def]
    tree = QTreeWidget()
    tree.resize(300, 240)
    tree.addTopLevelItem(QTreeWidgetItem(["GND"]))
    overlay = EmptyOverlay.over_view(tree, EmptyState("No nets yet", "Join two pins.", icon="connect"))
    tree.show()
    QApplication.processEvents()
    assert overlay.state.isHidden()
    return tree, overlay


def test_a_state_may_carry_its_panels_icon_over_the_title() -> None:
    from perfboard_studio.ui import theme

    with_icon = EmptyState("No nets yet", "Join two pins.", icon="connect")
    assert with_icon.badge is not None and with_icon.badge.name == "connect"
    layout = with_icon.layout()
    assert layout.indexOf(with_icon.badge) < layout.indexOf(with_icon.title)
    image = with_icon.badge.grab().toImage()
    middle = image.pixelColor(4, image.height() // 2 + 4)
    assert middle.name() == theme.ACTIVE.accent_subtle
    assert EmptyState("A", "a").badge is None


def test_a_panel_that_empties_on_screen_has_its_words_arrive() -> None:
    from PySide6.QtWidgets import QGraphicsOpacityEffect

    from perfboard_studio.ui import emptystate, motion

    tree, overlay = _shown_tree()
    try:
        motion.set_reduced(False)
        tree.clear()
        assert not overlay.state.isHidden()
        assert overlay.arriving()
        assert isinstance(overlay.state.graphicsEffect(), QGraphicsOpacityEffect)
        assert overlay.state.geometry().top() > 0  # below its place, rising
        assert overlay.state.geometry().top() <= emptystate.RISE_PX
        assert _wait_for(lambda: not overlay.arriving(), 2000)
        assert overlay.state.graphicsEffect() is None  # nothing left on the words at rest
        assert overlay.state.geometry() == tree.viewport().rect()
    finally:
        motion.reset()
        tree.close()


def test_with_motion_reduced_the_words_are_simply_there() -> None:
    from perfboard_studio.ui import motion

    tree, overlay = _shown_tree()
    try:
        motion.set_reduced(True)
        tree.clear()
        assert not overlay.arriving()
        assert overlay.state.graphicsEffect() is None
        assert overlay.state.geometry() == tree.viewport().rect()
    finally:
        motion.reset()
        tree.close()


def test_a_panel_not_yet_on_screen_does_not_animate() -> None:
    from perfboard_studio.ui import motion

    try:
        motion.set_reduced(False)
        tree = QTreeWidget()
        overlay = EmptyOverlay.over_view(tree, EmptyState("No nets yet", "Join two pins."))
        assert not overlay.arriving() and overlay.state.graphicsEffect() is None
    finally:
        motion.reset()


def test_a_row_arriving_mid_way_puts_the_words_away_cleanly() -> None:
    from perfboard_studio.ui import motion

    tree, overlay = _shown_tree()
    try:
        motion.set_reduced(False)
        tree.clear()
        assert overlay.arriving()
        tree.addTopLevelItem(QTreeWidgetItem(["VCC"]))
        assert overlay.state.isHidden()
        assert not overlay.arriving()
        assert overlay.state.graphicsEffect() is None
    finally:
        motion.reset()
        tree.close()

# -- in the window -----------------------------------------------------------------------


@pytest.fixture
def make_window(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import autosave as autosave_module
    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    monkeypatch.setattr(autosave_module, "default_directory", lambda: tmp_path / "recovery")
    made: list[main_module.MainWindow] = []

    def build(document: PerfDocument) -> main_module.MainWindow:
        window = main_module.MainWindow(document)
        window.show()
        QApplication.processEvents()
        made.append(window)
        return window

    yield build
    for window in made:
        window._saved_document = window.bus.document
        window.close()


def _example(name: str) -> PerfDocument:
    path = next(EXAMPLES.rglob(f"{name}.perf"))
    return persist.parse_document_or_throw(path.read_text(encoding="utf-8"))


def test_a_blank_document_says_what_each_panel_is_waiting_for(make_window) -> None:
    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta

    window = make_window(create_starter_document(DocumentMeta(name="blank", created="", modified="")))
    assert not window._nets_empty.state.isHidden()
    assert not window._parts_empty.state.isHidden()
    window.show_schematic()
    QApplication.processEvents()
    assert not window._sheet_empty.state.isHidden()
    assert window._sheet_empty.state.button is not None


def test_a_board_with_parts_says_nothing_of_the_kind(make_window) -> None:
    window = make_window(_example("ne555-astable"))
    assert window._nets_empty.state.isHidden()
    window.show_schematic()
    QApplication.processEvents()
    assert window._sheet_empty.state.isHidden()


def test_the_guide_offers_to_place_a_circuit_that_is_waiting(make_window) -> None:
    window = make_window(_example("ne555-blinker"))
    window.dock_guide.show()
    window._refresh_guide_panel()
    QApplication.processEvents()
    state = window._guide_empty.state
    assert not state.isHidden()
    assert state.button is not None and not state.button.isHidden()


def test_every_panel_in_the_window_shows_its_icon(make_window) -> None:
    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta

    window = make_window(create_starter_document(DocumentMeta(name="blank", created="", modified="")))
    overlays = (window._nets_empty, window._parts_empty, window._sheet_empty, window._guide_empty)
    names = [overlay.state.badge.name for overlay in overlays if overlay.state.badge is not None]
    assert names == ["connect", "sch-add", "schematic", "guide"]
