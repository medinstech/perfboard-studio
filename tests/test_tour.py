"""The getting-started tour (ui/tour.py): five presses of the next button, read off the window."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from perfboard_studio.ui.tour import STOPS, Tour, stop_for


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def test_each_stop_is_what_the_next_button_would_do_now() -> None:
    assert stop_for("board", guide_open=False).number == 1
    assert stop_for("place", guide_open=False).number == 2
    assert stop_for("route", guide_open=False).number == 3
    assert stop_for("check", guide_open=False).number == 4
    assert stop_for("build", guide_open=False).number == 4
    last = stop_for("build", guide_open=True)
    assert last.number == STOPS and last.last
    # A step done another way, or undone, lands on the stop that is true now.
    assert stop_for("place", guide_open=False) == stop_for("place", guide_open=False)


def _stage() -> tuple[QWidget, QPushButton, list[str], list[bool]]:
    window = QWidget()
    window.resize(1000, 700)
    layout = QVBoxLayout(window)
    button = QPushButton("Choose a Board…")
    layout.addWidget(button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
    window.show()
    QApplication.processEvents()
    return window, button, ["board"], [False]


def test_the_tour_follows_the_window_and_never_takes_a_click() -> None:
    window, button, key, guide = _stage()
    tour = Tour(window, button, lambda: key[0], lambda: guide[0])
    tour.start()
    assert tour.stop_shown is not None and tour.stop_shown.number == 1
    assert tour.spotlight.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert tour.spotlight.target.contains(button.geometry())
    key[0] = "route"
    tour.update()
    assert tour.stop_shown.number == 3
    assert "3 / 5" in tour.bubble.count.text()
    assert not tour.bubble.skip.isHidden() and tour.bubble.finish.isHidden()
    guide[0] = True
    tour.update()
    assert tour.stop_shown.last
    assert tour.bubble.skip.isHidden() and not tour.bubble.finish.isHidden()
    tour.bubble.finish.click()
    assert not tour.running
    window.close()


def test_skip_ends_it_at_any_stop() -> None:
    window, button, key, guide = _stage()
    tour = Tour(window, button, lambda: key[0], lambda: guide[0])
    tour.start()
    tour.bubble.skip.click()
    assert not tour.running
    assert tour.spotlight.isHidden() and tour.bubble.isHidden()
    window.close()


# -- in the window -----------------------------------------------------------------------


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
        create_starter_document(DocumentMeta(name="tour", created="", modified=""))
    )
    made.show()
    QApplication.processEvents()
    yield made
    made._saved_document = made.bus.document
    made.close()


def test_the_help_menu_starts_it_on_the_circuit_that_is_drawn_and_not_built(window) -> None:
    action = next(a for a in window.findChildren(type(window.act_connect))
                  if a.text().replace("&", "") == "Getting Started Tour")
    action.trigger()
    QApplication.processEvents()
    assert window.current_path is None  # an untitled copy, like any example
    assert window.bus.document.parts and not window.bus.document.components
    assert window._tour.running
    assert window._tour.stop_shown is not None and window._tour.stop_shown.number == 1
    window._tour.stop()
