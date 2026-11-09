"""Help reached from where the question is (ui/helpcards.py): F1, What's This, the glossary.

One text behind three doors, so the tests hold the doors to the text: every card names a
panel or a tool the window really has, F1 finds the card of what is under the pointer, and
the keys are where the menus say.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from perfboard_studio.ui import helpcards
from perfboard_studio.ui.i18n import language, set_language


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


@pytest.fixture
def window(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta
    from perfboard_studio.ui import autosave as autosave_module
    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    monkeypatch.setattr(autosave_module, "default_directory", lambda: tmp_path / "recovery")
    made = main_module.MainWindow(
        create_starter_document(DocumentMeta(name="help", created="", modified=""))
    )
    yield made
    made._saved_document = made.bus.document
    made.close()


def test_every_card_is_hung_on_something_the_window_has(window) -> None:
    """A panel renamed or a tool removed would leave its card unread: name it here.

    The cards are hung when help is first asked for (``_hang_help``), and the guide's
    corner is there once its panel is (``_build_guide_dock``), so both are asked for."""
    from PySide6.QtWidgets import QDockWidget

    assert window.guide_tools is not None
    window._hang_help()
    for name, text in helpcards.panel_help().items():
        found = window.findChild(QDockWidget, name) or window.findChild(QWidget, name)
        assert found is not None, f"no panel called {name}"
        assert found.whatsThis() == text
    for name, text in helpcards.tool_help().items():
        action = window._help_action(name)
        assert action is not None, f"no tool called {name}"
        assert action.whatsThis() == text


def test_f1_reads_the_card_of_what_is_under_the_pointer() -> None:
    outer = QWidget()
    outer.setWhatsThis("outer card")
    inner = QLabel("inside", outer)
    QVBoxLayout(outer).addWidget(inner)
    assert helpcards.help_for(inner, QPoint()) == "outer card"
    inner.setWhatsThis("inner card")
    assert helpcards.help_for(inner, QPoint()) == "inner card"
    assert helpcards.help_for(None, QPoint()) == ""


def test_f1_is_help_and_the_shortcuts_moved_to_ctrl_slash(window) -> None:
    keys = {
        action.shortcut().toString(): action.text().replace("&", "")
        for action in window.findChildren(type(window.act_connect))
        if not action.shortcut().isEmpty()
    }
    assert keys["F1"] == "Help for What's Under the Pointer"
    assert keys["Shift+F1"] == "What's This?"
    assert keys["Ctrl+/"] == "Keyboard Shortcuts…"


def test_the_glossary_finds_a_word_in_either_column() -> None:
    dialog = helpcards.GlossaryDialog()
    rows = dialog.tree.topLevelItemCount()
    assert rows == len(helpcards.glossary())
    dialog.filter.setText("ratsnest")
    shown = [dialog.tree.topLevelItem(i) for i in range(rows)
             if not dialog.tree.topLevelItem(i).isHidden()]
    assert shown and all("ratsnest" in f"{i.text(0)} {i.text(1)}".lower() for i in shown)
    dialog.filter.setText("")
    assert all(not dialog.tree.topLevelItem(i).isHidden() for i in range(rows))


def test_each_word_is_explained_once() -> None:
    words = [word for word, _meaning in helpcards.glossary()]
    assert len(words) == len(set(words))


def test_the_glossary_is_said_in_the_window_s_language() -> None:
    before = language()
    try:
        set_language("tr")
        words = dict(helpcards.glossary())
        assert "Ped" in words
        assert words["Ped"].startswith("Deliğin")
    finally:
        set_language(before)


def test_help_is_hung_when_it_is_first_asked_for(window) -> None:
    """Not as the window is built -- the texts were a few milliseconds of every start --
    but the moment F1 or What's This is pressed, so neither ever finds a tool without one."""
    from PySide6.QtWidgets import QApplication, QWhatsThis

    assert window.act_connect.whatsThis() == ""
    whats_this = next(a for a in window.findChildren(type(window.act_connect))
                      if a.shortcut().toString() == "Shift+F1")
    whats_this.trigger()
    try:
        assert window.act_connect.whatsThis() == helpcards.tool_help()["act_connect"]
    finally:
        QWhatsThis.leaveWhatsThisMode()
        QApplication.processEvents()
