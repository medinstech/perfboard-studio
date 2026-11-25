"""The card a long run shows (``ui/plannercard.py``): still a progress dialog to everything
that holds one, laid out as a card, with a bar that moves and a clock that counts, and all
of it still with motion reduced."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QProgressDialog, QPushButton, QWidget

from perfboard_studio.ui import motion, plannercard, theme
from perfboard_studio.ui.plannercard import PlannerCard, SweepBar, elapsed_text

from .test_ui import _blank_window, _close


@pytest.fixture(scope="module", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication(["perfboard-studio-tests"])


@pytest.fixture(autouse=True)
def _motion_back():  # type: ignore[no-untyped-def]
    yield
    motion.reset()


def _wait_for(done, timeout_ms: int) -> bool:  # type: ignore[no-untyped-def]
    """Pump events until ``done()`` or the time is up (PySide6 has no ``qWaitFor``)."""
    for _ in range(timeout_ms // 10):
        if done():
            return True
        QTest.qWait(10)
    return bool(done())


def _parent() -> QWidget:
    parent = QWidget()
    parent.setStyleSheet(theme.stylesheet(theme.ACTIVE))
    parent.resize(900, 600)
    parent.show()
    return parent


def test_it_is_still_a_progress_dialog_to_whoever_holds_one() -> None:
    parent = _parent()
    try:
        card = PlannerCard("Routing…", "Cancel", 0, 0, parent)
        assert isinstance(card, QProgressDialog)
        assert card in parent.findChildren(QProgressDialog)
        card.show()
        QApplication.processEvents()
        assert card.labelText() == "Routing…"
        cancelled: list[bool] = []
        card.canceled.connect(lambda: cancelled.append(True))
        card.cancel_button.click()
        assert cancelled and card.wasCanceled()
    finally:
        parent.close()


def test_cancel_is_never_the_button_enter_presses() -> None:
    card = PlannerCard("Routing…", "Cancel", 0, 0)
    for button in card.findChildren(QPushButton):
        assert not button.isDefault() and not button.autoDefault()


def test_the_label_the_bar_and_cancel_sit_inside_the_card_one_under_the_other() -> None:
    parent = _parent()
    try:
        card = PlannerCard("Trying your circuit on a 7 × 9 cm board", "Cancel", 0, 0, parent)
        card.setWindowTitle("Working")
        card.show()
        QApplication.processEvents()
        inside = card.inner()
        label = card.findChild(QLabel)
        assert label is not None
        for widget in (label, card.bar, card.cancel_button):
            assert inside.contains(widget.geometry()), widget
        assert card.caption_rect().bottom() < label.geometry().top()
        assert label.geometry().bottom() < card.bar.geometry().top()
        assert card.bar.geometry().bottom() < card.cancel_button.geometry().top()
        assert card.bar.height() == plannercard.BAR_PX
    finally:
        parent.close()


def test_a_longer_label_makes_a_taller_card_rather_than_a_cut_one() -> None:
    card = PlannerCard("One line", "Cancel", 0, 0)
    short = card.sizeHint().height()
    card.setLabelText("A first line\nand a second\nand a third")
    assert card.sizeHint().height() > short
    assert card.size() == card.sizeHint()


def test_a_label_handed_in_later_is_laid_out_like_the_first() -> None:
    """The board question swaps in a label with a link (``_run_planner``'s ``aside``)."""
    parent = _parent()
    try:
        card = PlannerCard("Trying boards", "Cancel", 0, 0, parent)
        card.show()
        link = QLabel(card)
        card.setLabel(link)
        card.setLabelText("Trying boards<br><br><a href='aside'>Other Board…</a>")
        QApplication.processEvents()
        assert link.wordWrap()
        assert card.inner().contains(link.geometry())
        assert link.geometry().bottom() < card.bar.geometry().top()
    finally:
        parent.close()


def test_with_no_maximum_the_bar_glides_and_stops_when_the_card_goes() -> None:
    parent = _parent()
    try:
        motion.set_reduced(False)
        card = PlannerCard("Routing…", "Cancel", 0, 0, parent)
        card.show()
        assert card.bar.running()
        first = card.bar.phase
        assert _wait_for(lambda: card.bar.phase != first, 2000)
        run = card.bar.run_rect()
        assert 0 < run.width() <= card.bar.width() * plannercard.RUN_SHARE + 1
        card.close()
        assert not card.bar.running()
    finally:
        parent.close()


def test_with_motion_reduced_the_bar_is_still_and_a_value_lands_at_once() -> None:
    parent = _parent()
    try:
        motion.set_reduced(True)
        busy = PlannerCard("Routing…", "Cancel", 0, 0, parent)
        busy.show()
        assert not busy.bar.running()
        image = busy.bar.grab().toImage()
        assert image.pixelColor(image.width() // 2, 1).name() == theme.ACTIVE.accent_subtle
        busy.close()

        counted = PlannerCard("Drawing", "Skip", 0, 10, parent)
        counted.show()
        counted.setValue(4)
        assert counted.bar.shown == pytest.approx(0.4)
    finally:
        parent.close()


def test_a_value_eases_into_the_fill() -> None:
    parent = _parent()
    try:
        motion.set_reduced(False)
        card = PlannerCard("Drawing", "Skip", 0, 10, parent)
        card.show()
        QApplication.processEvents()
        card.setValue(5)
        assert card.bar.shown < 0.5  # on its way, not jumped
        assert _wait_for(lambda: card.bar.shown == pytest.approx(0.5), 2000)
    finally:
        parent.close()


def test_the_clock_says_seconds_then_minutes() -> None:
    assert elapsed_text(0) == "0 s"
    assert elapsed_text(12.7) == "12 s"
    assert elapsed_text(59.9) == "59 s"
    assert elapsed_text(65) == "1:05"
    assert elapsed_text(-3) == "0 s"


def test_the_clock_counts_from_when_the_card_was_made() -> None:
    parent = _parent()
    try:
        card = PlannerCard("Routing…", "Cancel", 0, 0, parent)
        card.started = time.monotonic() - 42
        card.show()
        assert card._clock.isActive()
        card.close()
        assert not card._clock.isActive()
    finally:
        parent.close()


def test_a_sweep_bar_with_a_maximum_is_not_busy() -> None:
    bar = SweepBar()
    bar.setRange(0, 0)
    assert bar.busy()
    bar.setRange(0, 8)
    bar.setValue(2)
    assert not bar.busy() and bar.fraction() == pytest.approx(0.25)


def test_the_window_runs_its_planners_under_the_card(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui import main as main_module

    monkeypatch.setattr(main_module.MainWindow, "PLANNER_GRACE_S", 0.0)
    window = _blank_window()
    try:
        seen: list[type] = []

        def work(_should_stop):  # type: ignore[no-untyped-def]
            deadline = time.monotonic() + 10
            while not seen and time.monotonic() < deadline:
                time.sleep(0.01)
            return "done"

        def look() -> None:
            seen.extend(type(d) for d in window.findChildren(QProgressDialog) if d.isVisible())
            if not seen:
                QTimer.singleShot(20, look)

        QTimer.singleShot(20, look)
        assert window._run_planner("Routing…", work) == "done"
        assert seen and all(kind is PlannerCard for kind in seen)
    finally:
        _close(window)
