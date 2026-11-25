"""Hover that eases (``ui/hover.py``): a tool button's wash fades in and out, a Home card
rises off the page, and both land at once with motion reduced."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton, QVBoxLayout, QWidget

from perfboard_studio.ui import hover, motion, theme


@pytest.fixture(scope="module", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication(["perfboard-studio-tests"])


def _wait_for(done, timeout_ms: int) -> bool:
    """Pump events until ``done()`` or the time is up (PySide6 has no ``qWaitFor``)."""
    for _ in range(timeout_ms // 10):
        if done():
            return True
        QTest.qWait(10)
    return bool(done())


def _send(widget: QWidget, kind: QEvent.Type) -> None:
    QApplication.sendEvent(widget, QEvent(kind))


def _fade_of(button: QToolButton):
    return button.findChild(hover._Fade)


def _host(child: QWidget) -> QWidget:
    host = QWidget()
    host.setStyleSheet(theme.stylesheet(theme.ACTIVE))
    layout = QVBoxLayout(host)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.addWidget(child)
    host.resize(220, 160)
    host.show()
    QApplication.processEvents()
    return host


def test_a_faded_button_hands_its_hover_to_the_wash() -> None:
    button = QToolButton()
    button.setFixedSize(40, 30)
    hover.fade(button)
    hover.fade(button)  # twice is once
    assert len(button.findChildren(hover._Fade)) == 1
    assert button.property("fade") is True
    sheet = theme.stylesheet(theme.ACTIVE)
    assert 'QToolButton[fade="true"]:hover { background: transparent; }' in sheet


def test_the_wash_comes_and_goes_at_once_with_motion_reduced() -> None:
    button = QToolButton()
    button.setFixedSize(40, 30)
    hover.fade(button)
    host = _host(button)
    try:
        assert motion.reduced()
        level = _fade_of(button).level
        _send(button, QEvent.Type.Enter)
        assert level.value == 1.0
        _send(button, QEvent.Type.Leave)
        assert level.value == 0.0
    finally:
        host.close()


def test_the_wash_eases_in_and_is_painted_under_the_button() -> None:
    button = QToolButton()
    button.setFixedSize(40, 30)
    hover.fade(button)
    host = _host(button)
    try:
        motion.set_reduced(False)
        level = _fade_of(button).level
        idle = button.grab().toImage().pixelColor(20, 3)
        _send(button, QEvent.Type.Enter)
        assert level.value < 1.0 and level._animation is not None  # on its way, not switched
        assert _wait_for(lambda: level.value == 1.0, 2000)
        washed = button.grab().toImage().pixelColor(20, 3)
        assert washed != idle
        assert washed.name() == QColor(theme.ACTIVE.bg_hover).name()
        _send(button, QEvent.Type.Hide)
        assert level.value == 0.0  # a hidden button keeps no hover for its return
    finally:
        host.close()


def _card() -> QPushButton:
    card = QPushButton("card")
    theme.variant(card, "card")
    card.setFixedSize(160, 100)
    hover.lift(card)
    return card


def _top_edge(host: QWidget, card: QPushButton) -> int:
    """The first row, down the card's middle, that is no longer the page's colour."""
    image = host.grab().toImage()
    x = card.geometry().center().x()
    page = image.pixelColor(x, 2)
    return next(y for y in range(image.height()) if image.pixelColor(x, y) != page)


def test_a_card_rises_off_the_page_under_the_pointer() -> None:
    card = _card()
    host = _host(card)
    try:
        lift = card.findChild(hover._Lift)
        resting = _top_edge(host, card)
        still = host.grab().toImage()
        assert card.graphicsEffect() is None  # nothing to paint at rest
        _send(card, QEvent.Type.Enter)
        assert lift.level.value == 1.0
        assert card.graphicsEffect() is not None
        QApplication.processEvents()
        # The card's top edge, drawn two pixels higher than it stood.
        raised = host.grab().toImage()
        x = card.geometry().center().x()
        up = round(hover.LIFT_PX)
        assert raised.pixelColor(x, resting - up) == still.pixelColor(x, resting)
        assert raised.pixelColor(x, resting - up) != still.pixelColor(x, resting - up)
        _send(card, QEvent.Type.Leave)
        assert lift.level.value == 0.0
        assert card.graphicsEffect() is None
        assert _top_edge(host, card) == resting
    finally:
        host.close()


def test_a_card_eases_up_and_settles_without_its_effect() -> None:
    card = _card()
    host = _host(card)
    try:
        motion.set_reduced(False)
        lift = card.findChild(hover._Lift)
        _send(card, QEvent.Type.Enter)
        assert lift.level.value < 1.0 and lift.level._animation is not None
        assert _wait_for(lambda: lift.level.value == 1.0, 2000)
        _send(card, QEvent.Type.Leave)
        assert lift.level._animation is not None
        assert _wait_for(lambda: lift.level.value == 0.0, 2000)
        assert card.graphicsEffect() is None
    finally:
        host.close()


def test_a_primary_button_sinks_a_pixel_when_pressed() -> None:
    sheet = theme.stylesheet(theme.ACTIVE)
    pressed = sheet.split('QPushButton[variant="primary"]:pressed {', 1)[1].split("}", 1)[0]
    sm = theme.SPACE["sm"]
    assert f"padding-top: {sm + 1}px;" in pressed
    assert f"padding-bottom: {sm - 1}px;" in pressed
