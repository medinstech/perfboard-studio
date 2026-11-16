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

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.ui.home import (
    COLUMNS,
    WALKTHROUGH,
    Home,
    HomeExample,
    LastBoard,
    example_title,
)
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


def test_the_new_here_card_starts_the_tour(app) -> None:
    home = make(app)
    asked: list[str] = []
    home.startTour.connect(lambda: asked.append("tour"))
    home.walkthrough_button.click()
    assert asked == ["tour"]
    assert not home.walkthrough_card.isHidden()


def test_a_copy_without_the_walkthrough_example_offers_no_tour(app) -> None:
    others = [e for e in shipped() if e.path.stem != WALKTHROUGH]
    home = Home(others, LOOKUP)
    assert home.walkthrough_card.isHidden()


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


def test_a_circuit_not_yet_built_is_pictured_on_the_window_s_sheet_not_the_printer_s(app) -> None:
    """The release-candidate sitting asked why one card was a white page on a dark Home,
    and narrower than its neighbours: it was the SVG export, white because it goes to a
    printer. It is the sheet view's own painting now, on the theme's paper, and the card
    names its picture area so the stylesheet lays that paper across all of it."""
    from PySide6.QtGui import QColor

    from perfboard_studio.ui import theme

    home = make(app)
    home.show()
    for _ in range(50):
        app.processEvents()
        if all(not card.picture.pixmap().isNull() for card in home.cards):
            break
    home.close()
    sheets = [c for c in home.cards if c.picture.objectName() == "sheetPicture"]
    assert [c.example.path.stem for c in sheets] == ["ne555-blinker"]
    image = sheets[0].picture.pixmap().toImage()
    paper = QColor(theme.ACTIVE.sheet_paper).rgb()
    assert image.pixelColor(1, 1).rgb() == paper
    assert image.pixelColor(image.width() - 2, image.height() - 2).rgb() == paper


def test_the_board_opened_last_comes_forward_with_where_it_stands(app, tmp_path) -> None:
    """The window hands Home the last board with its steps and its next sentence; Home
    shows it large, with the step bar's six dots, leaves it out of the list beside it, and
    Continue opens it. The keyboard, which started on the list, moves to Continue."""
    from PySide6.QtCore import Qt

    from perfboard_studio.ui.workflow import STEP_ORDER, WorkflowFacts, workflow_steps

    document = persist.deserialize_document(
        (EXAMPLES / "nano-relay.perf").read_text(encoding="utf-8")
    ).document
    boards = [str(tmp_path / "relay.perf"), str(tmp_path / "supply.perf")]
    home = make(app, boards)
    home.show()
    home.focus_first()
    app.processEvents()
    assert home.last_card.isHidden()
    assert app.focusWidget() is home.recent_list
    steps = workflow_steps(
        WorkflowFacts(
            parts_off_board=0, parts_on_board=5, nets=4, board_label="", board_chosen=True,
            unrouted=3, drc_errors=0, drc_warnings=0, lvs_problems=0,
        )
    )
    home.set_last(LastBoard(Path(boards[0]), document, steps, "Join the pins on the board."))
    app.processEvents()
    assert not home.last_card.isHidden()
    assert home.last_hint.text() == "Join the pins on the board."
    assert not home.last_picture.pixmap().isNull()
    assert home.last_steps.layout().count() == 3 * len(STEP_ORDER) + 1
    listed = [home.recent_list.item(i).data(Qt.ItemDataRole.UserRole)
              for i in range(home.recent_list.count())]
    assert listed == [boards[1]]
    assert app.focusWidget() is home.continue_button
    opened: list[str] = []
    home.openRecent.connect(opened.append)
    home.continue_button.click()
    assert opened == [boards[0]]

    home.set_last(None)
    assert home.last_card.isHidden()
    assert home.recent_list.count() == 2
    home.close()


def test_with_the_only_board_forward_there_is_no_empty_list_under_it(app, tmp_path) -> None:
    board = str(tmp_path / "relay.perf")
    document = persist.deserialize_document(
        (EXAMPLES / "nano-relay.perf").read_text(encoding="utf-8")
    ).document
    home = make(app, [board])
    home.set_last(LastBoard(Path(board), document, (), ""))
    assert home.recent_list.isHidden() and home._recent_title.isHidden()


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
