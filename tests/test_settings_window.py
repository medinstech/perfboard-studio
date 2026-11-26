"""Settings (``ui/settings.py``): every preference in one window, none of them a copy.

Each row is the window's own action -- the one the menus, the Show button and the header's
sun and moon drive -- so these hold the rows to the actions both ways, the search to the
words a person remembers in either language, and the window to its job: one place, found
with Ctrl+, or from ☰, that survives the theme it switches.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QMenu, QPushButton, QWidgetAction

from perfboard_studio import persist
from perfboard_studio.ui import settings as settings_module
from perfboard_studio.ui.settings import (
    Category,
    Choice,
    Row,
    Segments,
    SettingsDialog,
    Swatches,
    Toggle,
    ToggleSwitch,
    fold,
    matches,
)

ROOT = Path(__file__).resolve().parents[1]


def _app() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication(["perfboard-studio-tests"])


def _window():  # type: ignore[no-untyped-def]
    from perfboard_studio.ui.main import MainWindow

    _app()
    loaded = persist.parse_document_or_throw(
        (ROOT / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    return MainWindow(loaded)


def _discard(window) -> None:  # type: ignore[no-untyped-def]
    """Close without the unsaved-work question, which waits forever offscreen."""
    dialog = window._settings_dialog
    if dialog is not None:
        dialog.reject()
    window._saved_document = window.bus.system_document
    window.close()


def _bound(rows: list[Row]) -> list[object]:
    """Every action a row drives, in the order the rows list them."""
    found: list[object] = []
    for row in rows:
        control = row.control
        if isinstance(control, Toggle):
            found.append(control.action)
        elif isinstance(control, (Choice, Swatches)):
            found.extend(control.actions.values())
    return found


# -- the search ----------------------------------------------------------------------


def test_the_search_folds_case_accents_and_both_is() -> None:
    assert fold("GÖRÜNÜM") == fold("görünüm") == fold("gorunum")
    assert fold("Işık") == fold("ISIK") == fold("ışık") == "isik"
    assert fold("İpucu") == "ipucu"
    assert fold("Tekerleği") == "tekerlegi"


def test_the_search_finds_a_row_by_its_words_in_either_language() -> None:
    _app()
    cats = [
        Category("general", "home", "Genel", ""),
        Category("wiring", "autoroute", "Kablolama", ""),
    ]
    action = QAction("x")
    wheel = Row("general", "Fare Tekerleği", "Tekerlekle yakınlaştırın.", Toggle(action),
                "Mouse Wheel trackpad scroll zoom")
    grid = Row("wiring", "Telleri Izgara Boyunca Döşe", "Teller delik sıraları boyunca.",
               Toggle(action), "Lay Wires Along the Grid")
    rows = [grid, wheel]
    assert matches(rows, cats, "tekerlek") == [wheel]
    assert matches(rows, cats, "wheel") == [wheel]
    assert matches(rows, cats, "TEKERLEGI") == [wheel]
    # Every word has to be found, anywhere in the row.
    assert matches(rows, cats, "wheel zoom") == [wheel]
    assert matches(rows, cats, "wheel grid") == []
    # The category's name finds its rows; the pages' order, not the list's.
    assert matches(rows, cats, "kablolama") == [grid]
    assert matches(rows, cats, "a") == [wheel, grid]
    assert matches(rows, cats, "   ") == []


def test_the_search_finds_the_other_languages_words_in_either_window() -> None:
    """The window is built in one language and a person types in the one they think in:
    "tema" in an English window found nothing, because only the hidden words were English
    in both. Every title, sentence and category is looked in as the catalogue says it in
    every language -- both ways, with no hidden words to help."""
    _app()
    from perfboard_studio.ui.i18n import TURKISH

    action = QAction("x")

    def window_in(say) -> tuple[list[Row], list[Category]]:  # type: ignore[no-untyped-def]
        cats = [Category("general", "home", say("General"), ""),
                Category("appearance", "sun", say("Appearance"), "")]
        rows = [
            Row("general", say("Mouse Wheel"),
                say("Zoom with the wheel, or scroll with it and zoom with Ctrl+wheel."),
                Toggle(action)),
            Row("appearance", say("Theme"), say("The window's colours. Changes at once."),
                Toggle(action)),
            Row("appearance", say("Reduce Motion"),
                say("Panels, menus and the board appear in place, without sliding or fading."),
                Toggle(action)),
        ]
        return rows, cats

    rows, cats = window_in(lambda english: english)
    wheel, theme_row, motion_row = rows
    assert matches(rows, cats, "tema") == [theme_row]
    assert matches(rows, cats, "tekerlek") == [wheel]
    assert matches(rows, cats, "hareket") == [motion_row]
    assert matches(rows, cats, "görünüş") == [theme_row, motion_row]

    rows, cats = window_in(lambda english: TURKISH[english])
    wheel, theme_row, motion_row = rows
    assert matches(rows, cats, "theme") == [theme_row]
    assert matches(rows, cats, "wheel") == [wheel]
    assert matches(rows, cats, "motion") == [motion_row]
    assert matches(rows, cats, "appearance") == [theme_row, motion_row]
    # A word of each language in one search is still every word found in one row.
    assert matches(rows, cats, "tema colours") == [theme_row]
    assert matches(rows, cats, "tema wheel") == []


def test_appearance_is_not_the_view_menus_word() -> None:
    """One word per concept: Settings' Appearance page is not the View menu."""
    from perfboard_studio.ui.i18n import TURKISH

    assert TURKISH["Appearance"] != TURKISH["&View"].replace("&", "")


# -- the window ----------------------------------------------------------------------


def test_every_row_is_one_of_the_windows_own_actions() -> None:
    window = _window()
    try:
        rows = window._settings_rows()
        bound = _bound(rows)
        expected = [
            *window.act_language.values(), window.act_start_on_home, *window.act_wheel.values(),
            *window.act_theme.values(), window.act_reduce_motion, *window.act_colour.values(),
            window.act_ratsnest, window.act_rulers, window.act_pin_names, window.act_values,
            window.act_board_labels, window.act_far_side, window.act_net_names,
            window.act_off_board,
            *window.act_style.values(), *window.act_crossing.values(), window.act_grid_wires,
            window.act_both_faces, window.act_autosave_file, window.act_auto_updates,
        ]
        assert bound == expected
        categories = {c.key for c in window._settings_categories()}
        assert {row.category for row in rows} <= categories
        assert all(row.title and row.why for row in rows)
    finally:
        _discard(window)


def test_ctrl_comma_opens_it_and_escape_puts_it_away() -> None:
    window = _window()
    try:
        assert window.act_settings.shortcut().toString() == "Ctrl+,"
        window.act_settings.trigger()
        dialog = window._settings_dialog
        assert isinstance(dialog, SettingsDialog) and dialog.isVisible()
        assert dialog.current_category() == "general"
        assert dialog.focusWidget() is dialog.search
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert not dialog.isVisible()
    finally:
        _discard(window)


def test_a_switch_and_its_action_say_the_same_thing_whichever_is_used() -> None:
    window = _window()
    try:
        dialog = window.on_settings("shown")
        page = dialog.pages.currentWidget()
        switch = next(
            s for s in page.findChildren(ToggleSwitch) if s._action is window.act_net_names
        )
        assert switch.isChecked() and window.act_net_names.isChecked()
        switch.click()
        assert not window.act_net_names.isChecked()
        assert not window.scene.show_net_names
        # And the other way: the menu item, the N key, the Show button all reach the switch.
        window.act_net_names.trigger()
        assert switch.isChecked()
    finally:
        _discard(window)


def test_a_choice_picks_through_the_action_its_menu_item_is() -> None:
    window = _window()
    try:
        dialog = window.on_settings("wiring")
        style = next(
            d for d in dialog.pages.currentWidget().findChildren(settings_module.Dropdown)
            if d._choice.actions is window.act_style
        )
        index = style.findData("wire")
        style.setCurrentIndex(index)
        style.activated.emit(index)
        assert window._routing_style == "wire"
        assert window.act_style["wire"].isChecked()
        window.act_style["balanced"].trigger()
        assert style.currentData() == "balanced"
    finally:
        _discard(window)


def test_the_search_shows_rows_from_every_category_and_gives_the_page_back() -> None:
    window = _window()
    try:
        dialog = window.on_settings("appearance")
        dialog.search.setText("wheel")
        assert dialog.shown_titles() == ["Mouse Wheel"]
        assert dialog.nav.selectedItems() == []
        # The Turkish word in the English window, which no row's hidden words say.
        dialog.search.setText("tema")
        assert dialog.shown_titles() == ["Theme"]
        dialog.search.setText("zzzz nothing")
        assert dialog.shown_titles() == []
        dialog.search.clear()
        assert dialog.current_category() == "appearance"
        assert "Theme" in dialog.shown_titles()
    finally:
        _discard(window)


def test_the_update_check_is_said_in_three_states() -> None:
    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui import updater

    window = _window()
    try:
        store = main_module.app_settings()
        assert updater.stored_preference(store) is None
        row = next(r for r in window._settings_rows() if isinstance(r.control, Toggle)
                   and r.control.action is window.act_auto_updates)
        # Never asked is not "off".
        assert settings_module.chip_of(row) == "Not chosen yet"
        window.act_auto_updates.trigger()
        assert updater.stored_preference(store) is True
        assert settings_module.chip_of(row) == ""
        window.act_auto_updates.trigger()
        assert updater.stored_preference(store) is False
        assert settings_module.chip_of(row) == ""
    finally:
        _discard(window)


def test_a_hidden_update_can_be_offered_again() -> None:
    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui import updater

    window = _window()
    try:
        store = main_module.app_settings()
        assert not [r for r in window._settings_rows() if r.title == "Hidden Update"]
        updater.remember_skip(store, "9.9.9")
        dialog = window.on_settings("files")
        assert "Hidden Update" in dialog.shown_titles()
        button = next(
            b for b in dialog.pages.currentWidget().findChildren(QPushButton)
            if b.objectName() == "settingsButton"
        )
        button.click()
        assert updater.skipped_version(store) == ""
        # The rows are asked for again, and the row has gone with what it was about.
        assert "Hidden Update" not in dialog.shown_titles()
        assert dialog.current_category() == "files"
    finally:
        _discard(window)


def test_start_on_home_is_homes_own_box() -> None:
    from perfboard_studio.ui import main as main_module

    window = _window()
    try:
        assert window.act_start_on_home.isChecked()
        window.act_start_on_home.trigger()
        assert main_module.app_settings().value(main_module.SHOW_WELCOME_KEY) in (False, "false")
    finally:
        _discard(window)


def test_pin_names_and_board_labels_are_remembered_like_the_other_show_items() -> None:
    window = _window()
    window.act_pin_names.setChecked(False)
    window.act_board_labels.setChecked(False)
    _discard(window)
    again = _window()
    try:
        assert not again.act_pin_names.isChecked()
        assert not again.act_board_labels.isChecked()
        assert again.act_ratsnest.isChecked()
    finally:
        _discard(again)


# -- the menus it took them from -----------------------------------------------------


def _texts(menu: QMenu) -> list[str]:
    return [a.text().replace("&", "") for a in menu.actions() if a.text()]


def test_view_has_no_preferences_left_and_says_its_groups() -> None:
    window = _window()
    try:
        view = next(m for m in window._top_menus if m.title() == "&View")
        texts = _texts(view)
        for gone in ("Language", "Theme", "Reduce Motion", "Board Colour", "Mouse Wheel"):
            assert gone not in texts
        assert texts[-1] == "Settings…"
        headings = [
            a.defaultWidget().text()
            for a in view.actions()
            if isinstance(a, QWidgetAction) and isinstance(a.defaultWidget(), QLabel)
        ]
        assert headings == ["GO TO", "PANELS", "CANVAS"]
        assert all(not a.isEnabled() for a in view.actions() if isinstance(a, QWidgetAction))
    finally:
        _discard(window)


def test_the_palette_still_finds_every_preference_by_name() -> None:
    window = _window()
    try:
        entries = window._palette_entries()
        settings_entries = [e for e in entries if e.where.startswith("Settings")]
        labels = " ".join(e.label for e in settings_entries)
        for word in ("Dark", "Light", "Reduce Motion", "English", "Start on Home", "Zooms"):
            assert word in labels
        # Settings itself is a command too, in View.
        assert any(e.label == "Settings…" for e in entries)
    finally:
        _discard(window)


def test_the_menu_button_opens_with_settings_search_and_the_last_boards() -> None:
    from perfboard_studio.ui import main as main_module

    examples = sorted((ROOT / "examples").glob("*.perf"))[:2]
    gone = ROOT / "examples" / "no-such-board.perf"
    main_module.app_settings().setValue(
        main_module.RECENT_FILES_KEY, [str(p) for p in (*examples, gone)]
    )
    window = _window()
    try:
        menu = window.header.app_menu
        actions = menu.actions()
        assert actions[0] is window.act_settings and actions[1] is window.act_palette
        menu.aboutToShow.emit()
        texts = [a.text() for a in menu.actions() if a.isVisible()]
        assert [p.name for p in examples] == [t for t in texts if t.endswith(".perf")]
        # Shown twice, the list is said once.
        menu.aboutToShow.emit()
        texts = [a.text() for a in menu.actions() if a.isVisible()]
        assert sum(t.endswith(".perf") for t in texts) == 2
        assert not window.act_settings.icon().isNull()
        assert all(not m.menuAction().icon().isNull() for m in window._top_menus)
    finally:
        _discard(window)


def test_the_theme_row_is_the_headers_sun_and_moon() -> None:
    window = _window()
    try:
        dialog = window.on_settings("appearance")
        segments = dialog.pages.currentWidget().findChildren(Segments)[0]
        assert segments._choice.actions is window.act_theme
    finally:
        _discard(window)


def test_a_live_theme_switch_recolours_the_open_window_and_leaves_it_open() -> None:
    from perfboard_studio.ui import theme

    window = _window()
    before = theme.ACTIVE.name
    other = "light" if before == "dark" else "dark"
    try:
        hole_text = window.label_hole.text()
        dialog = window.on_settings("appearance")
        segments = dialog.pages.currentWidget().findChildren(Segments)[0]
        segments._buttons[other].click()
        assert theme.ACTIVE.name == other
        # A pointer that has not been over the board yet is not said as "hole —".
        assert window.label_hole.text() == hole_text
        assert window.act_theme[other].isChecked()
        assert not window.act_theme[before].isChecked()
        assert dialog.isVisible() and dialog.current_category() == "appearance"
        sidebar = dialog.findChild(QFrame, "settingsSidebar")
        assert sidebar is not None
        pixel = sidebar.grab().toImage().pixelColor(2, 2)
        assert pixel.name() == theme.THEMES[other].bg_subtle.lower()
        # Switched from elsewhere -- the header's sun and moon -- the row follows.
        window.on_theme(before)
        assert segments._buttons[before].isChecked()
        assert not segments._buttons[other].isChecked()
        assert dialog.isVisible()
    finally:
        window.on_theme(before)
        _discard(window)
