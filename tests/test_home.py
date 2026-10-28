"""Home: the page a first start opens on, and the one between boards.

Home on its own -- which door is primary, what a returning user sees first, that every
example has a name and a picture and opens itself -- because the window only wires the
signals to commands it already has.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.ui.home import COLUMNS, WALKTHROUGH, Home, HomeExample, example_title
from perfboard_studio.ui.i18n import language, set_language

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
LOOKUP = footprint_lookup()


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def shipped() -> list[HomeExample]:
    """Every example the repository ships, the way ``main.example_boards`` finds them."""
    found = sorted(EXAMPLES.glob("*.perf"))
    found += [inner for folder in sorted(p for p in EXAMPLES.iterdir() if p.is_dir())
              for inner in sorted(folder.glob("*.perf"))]
    return [HomeExample(path, f"line for {path.stem}") for path in found]


def make(app: QApplication, recent: list[str] | None = None) -> Home:
    home = Home(shipped(), LOOKUP)
    home.set_recent(recent or [])
    home.resize(1280, 800)
    return home


def test_a_first_start_offers_one_door_first(app) -> None:
    home = make(app)
    assert not home.first_run.isHidden()
    assert home.returning.isHidden()
    asked: list[str] = []
    home.newCircuit.connect(lambda: asked.append("new"))
    home.first_button.click()
    assert asked == ["new"]


def test_somebody_with_boards_sees_the_last_one_first(app, tmp_path) -> None:
    boards = [str(tmp_path / "pedal.perf"), str(tmp_path / "supply.perf")]
    home = make(app, boards)
    assert home.first_run.isHidden()
    assert not home.returning.isHidden()
    assert home.recent_list.count() == 2
    assert home.recent_list.currentRow() == 0
    opened: list[str] = []
    home.openRecent.connect(opened.append)
    home.recent_list.itemActivated.emit(home.recent_list.item(0))
    assert opened == [boards[0]]


def test_every_example_has_a_name_and_opens_itself(app) -> None:
    home = make(app)
    assert len(home.cards) == len(shipped())
    for card in home.cards:
        assert card.accessibleName() != card.example.path.stem, card.example.path
    opened: list[str] = []
    home.openExample.connect(opened.append)
    home.cards[1].click()
    assert opened == [str(home.cards[1].example.path)]


def test_a_returning_user_gets_one_row_of_examples_and_the_rest_on_request(app, tmp_path) -> None:
    home = make(app, [str(tmp_path / "board.perf")])
    visible = [card for card in home.cards if not card.isHidden()]
    assert len(visible) == COLUMNS
    home.show_all.click()
    assert all(not card.isHidden() for card in home.cards)


def test_the_new_here_card_opens_the_circuit_that_is_drawn_and_not_built(app) -> None:
    home = make(app)
    opened: list[str] = []
    home.openExample.connect(opened.append)
    home.walkthrough_button.click()
    assert Path(opened[0]).stem == WALKTHROUGH


def test_the_pictures_are_drawn_after_home_is_on_screen(app) -> None:
    home = make(app)
    assert all(card.picture.pixmap().isNull() for card in home.cards)
    home.show()
    for _ in range(50):
        app.processEvents()
        if all(not card.picture.pixmap().isNull() for card in home.cards):
            break
    home.close()
    assert all(not card.picture.pixmap().isNull() for card in home.cards)


def test_the_start_up_box_says_what_it_does(app) -> None:
    home = make(app)
    said: list[bool] = []
    home.showAtStartChanged.connect(said.append)
    home.show_at_start.setChecked(False)
    home.set_show_at_start(True)  # the window's own setting: no signal back
    assert said == [False]
    assert home.show_at_start.isChecked()


def test_an_example_title_is_said_in_the_window_s_language() -> None:
    before = language()
    try:
        set_language("tr")
        assert example_title("ne555-astable") == "555 LED flaşör"
        assert example_title("somebody-elses-board") == "somebody-elses-board"
    finally:
        set_language(before)


def test_the_keyboard_starts_on_the_primary_door_or_the_last_board(app, tmp_path) -> None:
    home = make(app)
    home.show()
    home.focus_first()
    app.processEvents()
    assert app.focusWidget() is home.first_button
    home.set_recent([str(tmp_path / "board.perf")])
    home.focus_first()
    app.processEvents()
    assert app.focusWidget() is home.recent_list
    home.close()
