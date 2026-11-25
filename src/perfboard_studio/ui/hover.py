"""Hover that eases instead of snapping: a button's wash fades in, and a card lifts.

A stylesheet's ``:hover`` is a switch -- the background is there or it is not -- and over a
row of swatches or the header's buttons the pointer passing along them reads as flicker.
:func:`fade` gives a tool button the same wash, eased over ``HOVER_FADE_MS``: the stylesheet
stands its own hover down for a button marked ``fade`` (``theme``), and the wash is painted
under the button's own drawing, so the icon, the checked colour and the pressed colour stay
the stylesheet's.

:func:`lift` raises a card off the page while the pointer is on it: two pixels up and a
soft shadow under it (``LIFT_PX``, ``LIFT_MS``). Only a card the pointer is on carries the
effect; it is taken off again once the card has settled, so a page of cards costs nothing
to paint at rest. The shadow is a few stacked rounded rectangles rather than a blur, which
is a cost per frame a hover animation should not pay.

Both go through ``motion``: with motion reduced they land at once, and nothing is left
running.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsEffect, QToolButton, QWidget

from . import motion, theme

#: How long a button's hover wash takes to come and go.
HOVER_FADE_MS = 120
#: How long a card takes to rise, and how far it goes.
LIFT_MS = 120
LIFT_PX = 2.0
#: The shadow under a raised card: how far below it falls, how far it spreads, and in how
#: many steps the spread is drawn.
SHADOW_DROP_PX = 6.0
SHADOW_SPREAD_PX = 10.0
SHADOW_STEPS = 6


class _Level(QObject):
    """A level from 0 to 1 that eases towards where it is sent, for one widget."""

    def __init__(self, widget: QWidget, ms: int, changed: Callable[[float], None]) -> None:
        super().__init__(widget)
        self._widget = widget
        self._ms = ms
        self._changed = changed
        self.value = 0.0
        self.target = 0.0
        self._animation: QVariantAnimation | None = None

    def go(self, target: float) -> None:
        if target == self.target and (self._animation is not None or self.value == target):
            return
        self.target = target
        self._halt()
        # A level halfway there takes half as long to get back.
        ms = motion.duration(round(self._ms * abs(target - self.value)))
        if ms <= 0 or not self._widget.isVisible():
            self._set(target)
            return
        animation = QVariantAnimation(self)
        animation.setStartValue(self.value)
        animation.setEndValue(target)
        animation.setDuration(ms)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(lambda value: self._set(float(cast(float, value))))
        animation.finished.connect(self._halt)
        self._animation = animation
        animation.start()

    def snap(self, target: float) -> None:
        self.target = target
        self._halt()
        self._set(target)

    def _halt(self) -> None:
        animation, self._animation = self._animation, None
        if animation is not None:
            animation.stop()
            animation.deleteLater()

    def _set(self, value: float) -> None:
        self.value = value
        self._changed(value)


class _Fade(QObject):
    """The eased hover wash of one tool button (:func:`fade`)."""

    def __init__(self, button: QToolButton) -> None:
        super().__init__(button)
        self._button = button
        self.level = _Level(button, HOVER_FADE_MS, lambda _value: button.update())
        button.setProperty("fade", True)
        theme.restyle(button)
        button.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Enter:
            self.level.go(1.0)
        elif kind == QEvent.Type.Leave:
            self.level.go(0.0)
        elif kind == QEvent.Type.Hide:
            self.level.snap(0.0)
        elif kind == QEvent.Type.Paint and self.level.value > 0.0 and self._button.isEnabled():
            # Under the button's own drawing: the paint event is still on its way to it.
            colour = QColor(theme.ACTIVE.bg_hover)
            colour.setAlphaF(colour.alphaF() * min(1.0, self.level.value))
            painter = QPainter(self._button)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawRoundedRect(
                QRectF(self._button.rect()), theme.RADIUS_SM, theme.RADIUS_SM
            )
            painter.end()
        return False


def fade(button: QToolButton) -> None:
    """Give ``button`` a hover wash that eases in and out instead of switching."""
    if button.findChild(_Fade) is None:
        _Fade(button)


class _LiftEffect(QGraphicsEffect):
    """The card drawn ``level`` of the way up, over a shadow as soft as it is high."""

    def __init__(self, card: QWidget, level: _Level) -> None:
        super().__init__(card)
        self._level = level

    def boundingRectFor(self, rect: QRectF | QRect) -> QRectF:
        spread = SHADOW_SPREAD_PX
        return QRectF(rect).adjusted(-spread, -LIFT_PX - 1.0, spread, SHADOW_DROP_PX + spread)

    def draw(self, painter: QPainter) -> None:
        level = max(0.0, min(1.0, self._level.value))
        rect = self.sourceBoundingRect(Qt.CoordinateSystem.LogicalCoordinates)
        if level > 0.0:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            # Stacked, each a little wider and fainter: dark close under the card, gone at
            # the edge of the spread.
            alpha = theme.ACTIVE.shadow_alpha * level / SHADOW_STEPS
            drop = SHADOW_DROP_PX * level
            for step in range(SHADOW_STEPS):
                grow = SHADOW_SPREAD_PX * level * (step + 1) / SHADOW_STEPS
                painter.setBrush(QColor(0, 0, 0, max(1, round(alpha * 0.8))))
                radius = theme.RADIUS_LG + grow
                painter.drawRoundedRect(
                    rect.adjusted(-grow * 0.6, drop - grow * 0.4, grow * 0.6, drop + grow * 0.6),
                    radius,
                    radius,
                )
            painter.restore()
        pixmap = self.sourcePixmap(
            Qt.CoordinateSystem.LogicalCoordinates, mode=QGraphicsEffect.PixmapPadMode.NoPad
        )
        painter.drawPixmap(QPointF(rect.x(), rect.y() - LIFT_PX * level), pixmap)


class _Lift(QObject):
    """The rise of one card under the pointer (:func:`lift`)."""

    def __init__(self, card: QWidget) -> None:
        super().__init__(card)
        self._card = card
        self._effect: _LiftEffect | None = None
        self.level = _Level(card, LIFT_MS, self._changed)
        card.installEventFilter(self)

    @property
    def raised(self) -> bool:
        return self._effect is not None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Enter and self._card.isEnabled():
            self.level.go(1.0)
        elif kind == QEvent.Type.Leave:
            self.level.go(0.0)
        elif kind == QEvent.Type.Hide:
            self.level.snap(0.0)
        return False

    def _changed(self, value: float) -> None:
        if value <= 0.0:
            if self._effect is not None:
                self._effect = None
                # None takes the effect off and deletes it; the stubs do not say so.
                self._card.setGraphicsEffect(cast(QGraphicsEffect, None))
            return
        if self._effect is None:
            self._effect = _LiftEffect(self._card, self.level)
            self._card.setGraphicsEffect(self._effect)
        else:
            self._effect.update()


def lift(card: QWidget) -> None:
    """Raise ``card`` off the page while the pointer is on it."""
    if card.findChild(_Lift) is None:
        _Lift(card)
