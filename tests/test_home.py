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
    assert home.new_button.text() == "Draw Your First Circuit"
    asked: list[str] = []
    home.newCircuit.connect(lambda: asked.append("new"))
    home.new_button.click()
    assert asked == ["new"]


def test_somebody_with_boards_sees_them_as_cards(app, tmp_path) -> None:
    boards = [str(tmp_path / "pedal.perf"), str(tmp_path / "supply.perf")]
    home = make(app, boards)
    assert home.first_run.isHidden()
    assert not home.returning.isHidden()
    assert home.new_button.text() == "New Circuit"
    assert [str(card.path) for card in home.recent_cards] == boards
    opened: list[str] = []
    home.openRecent.connect(opened.append)
    home.recent_cards[1].click()
    assert opened == [boards[1]]


def test_one_row_of_boards_and_the_rest_on_request(app, tmp_path) -> None:
    boards = [str(tmp_path / f"board-{n}.perf") for n in range(COLUMNS + 2)]
    home = make(app, boards)
    assert [card.isHidden() for card in home.recent_cards] == [False] * COLUMNS + [True] * 2
    assert not home.show_all_recent.isHidden()
    home.show_all_recent.click()
    assert not any(card.isHidden() for card in home.recent_cards)
    assert home.show_all_recent.isHidden()
    home.set_recent(boards[:COLUMNS])
    assert home.show_all_recent.isHidden()


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
    sheets = [c for c in home.cards if c.picture.on_paper]
    assert [c.example.path.stem for c in sheets] == ["ne555-blinker"]
    image = sheets[0].picture.pixmap().toImage()
    paper = QColor(theme.ACTIVE.sheet_paper).rgb()
    assert image.pixelColor(1, 1).rgb() == paper
    assert image.pixelColor(image.width() - 2, image.height() - 2).rgb() == paper
    # The frame around the drawing is the same paper, edge to edge under the rounded top.
    frame = sheets[0].picture.grab().toImage()
    for x, y in ((frame.width() // 2, 2), (2, frame.height() - 2), (frame.width() - 3, frame.height() // 2)):
        assert frame.pixelColor(x, y).rgb() == paper, (x, y)


def test_the_board_opened_last_comes_forward_with_where_it_stands(app, tmp_path) -> None:
    """The window hands Home the last board with its steps and its next sentence; Home
    shows it large, with the step bar's six dots on one line, leaves it out of the row
    under it, and Continue opens it. The keyboard, which started on the first board, moves
    to Continue."""
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
    assert app.focusWidget() is home.recent_cards[0]
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
    # A dot and a name for each step, and a rule between each two.
    assert home.last_steps.layout().count() == 3 * len(STEP_ORDER) - 1
    assert [str(card.path) for card in home.recent_cards] == [boards[1]]
    assert app.focusWidget() is home.continue_button
    opened: list[str] = []
    home.openRecent.connect(opened.append)
    home.continue_button.click()
    assert opened == [boards[0]]

    home.set_last(None)
    assert home.last_card.isHidden()
    assert [str(card.path) for card in home.recent_cards] == boards
    home.close()


def test_with_the_only_board_forward_there_is_no_empty_list_under_it(app, tmp_path) -> None:
    board = str(tmp_path / "relay.perf")
    document = persist.deserialize_document(
        (EXAMPLES / "nano-relay.perf").read_text(encoding="utf-8")
    ).document
    home = make(app, [board])
    home.set_last(LastBoard(Path(board), document, (), ""))
    assert home.returning.isHidden() and home.recent_cards == []
    assert home.nav_recent.isHidden(), "the sidebar has no place for a row that is not there"


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
    assert app.focusWidget() is home.new_button
    home.set_recent([str(tmp_path / "board.perf")])
    home.focus_first()
    app.processEvents()
    assert app.focusWidget() is home.recent_cards[0]
    home.close()


def _settle(app: QApplication, home: Home) -> None:
    """Show Home and run the turns its pictures take after the first frame."""
    home.show()
    for _ in range(80):
        app.processEvents()
        if not home._to_draw:
            break
    app.processEvents()


def test_the_sidebar_goes_to_each_place_on_the_page_and_lights_where_it_is(app, tmp_path) -> None:
    """Home, Recent and Examples scroll the page to their sections, Tour starts the tour,
    and the place lit is the one the page is scrolled to -- by a click or by hand."""
    home = make(app, [str(tmp_path / f"board-{n}.perf") for n in range(3)])
    home.resize(1366, 500)
    _settle(app, home)
    bar = home.scroller.verticalScrollBar()
    assert bar.maximum() > 0
    assert home.nav_home.isChecked()
    home.nav_examples.click()
    assert home.nav_examples.isChecked()
    assert bar.value() > 0
    top = home.examples_section.mapTo(home.page, home.examples_section.rect().topLeft()).y()
    assert bar.value() in (bar.maximum(), max(0, top - 24))
    home.nav_home.click()
    assert bar.value() == 0 and home.nav_home.isChecked()
    # By hand: the place follows the page.
    bar.setValue(bar.maximum())
    assert home.nav_examples.isChecked()
    bar.setValue(0)
    assert home.nav_home.isChecked()
    asked: list[str] = []
    home.startTour.connect(lambda: asked.append("tour"))
    home.nav_tour.click()
    assert asked == ["tour"]
    home.close()


def test_the_sidebar_names_only_places_that_are_there(app) -> None:
    home = make(app)
    assert home.nav_recent.isHidden(), "no boards yet"
    assert not home.nav_examples.isHidden() and not home.nav_tour.isHidden()
    bare = Home([e for e in shipped() if e.path.stem != WALKTHROUGH], LOOKUP)
    assert bare.nav_tour.isHidden(), "the tour runs on an example this copy lacks"
    assert Home([], LOOKUP).nav_examples.isHidden()


def test_the_sidebar_narrows_on_a_small_screen_and_four_cards_still_fit(app, tmp_path) -> None:
    home = make(app, [str(tmp_path / f"board-{n}.perf") for n in range(5)])
    for width, side in ((1920, 248), (1366, 200)):
        home.resize(width, 800)
        _settle(app, home)
        assert home.side.width() == side
        shown = [card for card in home.recent_cards if card.isVisible()]
        assert len(shown) == 4
        assert len({card.y() for card in shown}) == 1, "one row"
        assert all(card.width() >= 220 for card in shown), [card.width() for card in shown]
        widths = [card.width() for card in shown]
        assert max(widths) - min(widths) <= 1, widths
        assert home.scroller.horizontalScrollBar().maximum() == 0, "nothing widens the page"
    home.close()


def test_every_picture_is_one_frame(app, tmp_path) -> None:
    """A board's card and an example's are the same 16:10."""
    import shutil

    from perfboard_studio.ui.home import RATIO

    board = tmp_path / "relay.perf"
    shutil.copy(EXAMPLES / "nano-relay.perf", board)
    home = make(app, [str(board)])
    _settle(app, home)
    pictures = [home.recent_cards[0].picture, *(card.picture for card in home.cards[:COLUMNS])]
    assert not home.recent_cards[0].picture.pixmap().isNull()
    for picture in pictures:
        assert abs(picture.height() - picture.width() * RATIO) <= 1, picture.size()
    widths = [picture.width() for picture in pictures]
    assert max(widths) - min(widths) <= 1, widths
    home.close()


def test_enter_opens_the_board_opened_last_or_the_button_it_is_on(app, tmp_path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    document = persist.deserialize_document(
        (EXAMPLES / "nano-relay.perf").read_text(encoding="utf-8")
    ).document
    boards = [str(tmp_path / "relay.perf"), str(tmp_path / "supply.perf")]
    home = make(app, boards)
    _settle(app, home)
    home.set_last(LastBoard(Path(boards[0]), document, (), ""))
    opened: list[str] = []
    home.openRecent.connect(opened.append)
    home.setFocus()
    QTest.keyClick(home, Qt.Key.Key_Return)
    assert opened == [boards[0]]
    home.recent_cards[0].setFocus()
    QTest.keyClick(home.recent_cards[0], Qt.Key.Key_Return)
    assert opened == [boards[0], boards[1]]
    home.close()


def test_tab_goes_down_the_sidebar_then_continue_then_the_cards(app, tmp_path) -> None:
    document = persist.deserialize_document(
        (EXAMPLES / "nano-relay.perf").read_text(encoding="utf-8")
    ).document
    boards = [str(tmp_path / "relay.perf"), str(tmp_path / "supply.perf")]
    home = make(app, boards)
    _settle(app, home)
    home.set_last(LastBoard(Path(boards[0]), document, (), ""))
    order = []
    widget = home.new_button
    for _ in range(60):
        order.append(widget)
        widget = widget.nextInFocusChain()
        if widget is home.new_button:
            break
    position = {id(w): n for n, w in enumerate(order)}
    assert position[id(home.open_button)] < position[id(home.nav_home)] < position[id(home.show_at_start)]
    assert position[id(home.show_at_start)] < position[id(home.continue_button)]
    assert position[id(home.continue_button)] < position[id(home.recent_cards[0])]
    assert position[id(home.recent_cards[0])] < position[id(home.cards[0])]
    home.close()


def test_a_callback_after_the_first_frame_waits_for_it(app) -> None:
    """A zero timer set before a window is shown runs before its first frame; Home's own
    hook waits for the page to be painted, and after that runs on the next turn."""
    home = make(app)
    ran: list[str] = []
    home.after_first_frame(lambda: ran.append("first"))
    for _ in range(5):
        app.processEvents()
    assert ran == [], "not shown, not painted"
    home.show()
    for _ in range(20):
        app.processEvents()
        if ran:
            break
    assert ran == ["first"]
    home.after_first_frame(lambda: ran.append("later"))
    assert ran == ["first"]
    app.processEvents()
    assert ran == ["first", "later"]
    home.close()


def test_a_board_says_when_it_was_saved() -> None:
    import datetime

    from perfboard_studio.ui.home import saved_when

    here = Path(__file__)
    day = datetime.date.fromtimestamp(here.stat().st_mtime)
    assert saved_when(here, day) == "Saved today"
    assert saved_when(here, day + datetime.timedelta(days=1)) == "Saved yesterday"
    assert saved_when(here, day + datetime.timedelta(days=5)) == "Saved 5 days ago"
    assert saved_when(here, day + datetime.timedelta(days=45)) == f"Saved {day.isoformat()}"
    assert saved_when(here.parent / "no-such-board.perf") == ""


def test_the_page_is_a_blueprint_in_the_accent_made_once(app) -> None:
    from PySide6.QtGui import QColor

    from perfboard_studio.ui import theme
    from perfboard_studio.ui.home import GRID_MAJOR, blueprint_tile

    for tokens in theme.THEMES.values():
        for ratio in (1.0, 1.5, 2.0):
            tile = blueprint_tile(tokens, ratio)
            assert tile is blueprint_tile(tokens, ratio), "cached"
            assert round(tile.deviceIndependentSize().width()) == GRID_MAJOR
            image = tile.toImage()
            background = QColor(tokens.bg_app)
            line = image.pixelColor(0, image.height() // 2)
            assert line != background
            accent = QColor(tokens.accent)
            # Toward the accent, a few per cent of the way.
            for channel in ("red", "green", "blue"):
                there = getattr(accent, channel)() - getattr(background, channel)()
                went = getattr(line, channel)() - getattr(background, channel)()
                assert went * there >= 0 and abs(went) <= abs(there) * 0.1 + 1
