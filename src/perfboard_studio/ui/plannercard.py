"""The card a long run shows while it works: what it is doing, how long it has taken, and
a way out.

IT WAS THE PLATFORM'S PROGRESS DIALOG, a title bar saying "Working" over a label, a
stylesheet bar and a Cancel button, every one of them where the dialog's own layout put
them. Nothing else in the window looked like it, and its bar, given no maximum, sat still on
the stylesheet's style: a run of twenty seconds looked the same at the first second as a
hang did at the twentieth.

:class:`PlannerCard` is still a ``QProgressDialog`` -- the label, the bar, Cancel, Escape,
``canceled`` and ``wasCanceled`` are the dialog's, and so is every caller and test that
holds one -- drawn as a card that floats over the window: a rounded surface with a soft
shadow under it, a caption with the time the run has taken so far, and a bar that says
"still working" by moving. The time is the honest half of a percentage: neither planner can
say how far it has got (``MainWindow._run_planner``), but it can say how long it has been,
and a clock that keeps counting is what tells a long run from a hung one.

With no maximum the bar is a short accent run that glides across the track and back in,
eased at both ends; with one, its fill eases to each new value rather than jumping. Both go
through ``motion``: reduced, the indeterminate bar is the whole track in a quiet accent,
still, and a value lands at once. The card fades in as it comes up.

On X11 a translucent window shows black where nothing is drawn unless a compositor runs,
and Qt cannot say whether one does: there the card is square and casts no shadow.
"""

from __future__ import annotations

import time

from PySide6.QtCore import (
    QEasingCurve,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QHideEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import QLabel, QProgressBar, QProgressDialog, QPushButton, QWidget

from . import motion, theme
from .i18n import t

#: The card's width: wide enough for a board trial's two-line label, narrow enough to read
#: as a card over the window rather than a second window.
CARD_WIDTH_PX = 400
#: The padding inside the card, and the margin round it the shadow is drawn in.
PAD_PX = theme.SPACE["xl"] + theme.SPACE["xs"]
SHADOW_PX = 14
#: The bar's thickness, and the share of the track the indeterminate run covers.
BAR_PX = 4
RUN_SHARE = 0.32
#: One pass of the indeterminate run across the track, and the time a value eases over.
SWEEP_MS = 1500
VALUE_MS = 260
#: How long the card takes to fade in.
FADE_IN_MS = 140


def elapsed_text(seconds: float) -> str:
    """How long a run has taken, as the caption says it: "12 s", then "1:05"."""
    whole = max(0, int(seconds))
    if whole < 60:
        return t("{seconds} s").format(seconds=whole)
    return f"{whole // 60}:{whole % 60:02d}"


def _translucent() -> bool:
    return QGuiApplication.platformName() != "xcb"


class SweepBar(QProgressBar):
    """The card's bar: a thin track, a gliding run with no maximum, an eased fill with one."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(BAR_PX)
        #: Where the run is along its pass, 0 to 1, while there is no maximum.
        self.phase = 0.0
        #: The fill as drawn, which eases towards ``value()``.
        self.shown = 0.0
        self._sweep: QVariantAnimation | None = None
        self._ease: QVariantAnimation | None = None
        self.valueChanged.connect(self._on_value)

    def busy(self) -> bool:
        return self.maximum() == self.minimum()

    def fraction(self) -> float:
        span = self.maximum() - self.minimum()
        if span <= 0:
            return 0.0
        return min(1.0, max(0.0, (self.value() - self.minimum()) / span))

    def start(self) -> None:
        """Set the run going, if there is no maximum and motion is not reduced."""
        if not self.busy() or not motion.enabled() or self._sweep is not None:
            return
        sweep = QVariantAnimation(self)
        sweep.setStartValue(0.0)
        sweep.setEndValue(1.0)
        sweep.setDuration(motion.duration(SWEEP_MS))
        sweep.setEasingCurve(QEasingCurve.Type.InOutCubic)
        sweep.setLoopCount(-1)
        sweep.valueChanged.connect(self._on_phase)
        self._sweep = sweep
        sweep.start()

    def stop(self) -> None:
        for animation in (self._sweep, self._ease):
            if animation is not None:
                animation.stop()
        self._sweep = None
        self._ease = None

    def running(self) -> bool:
        return self._sweep is not None

    def _on_phase(self, value: object) -> None:
        self.phase = float(value)  # type: ignore[arg-type]
        self.update()

    def _on_value(self, _value: int) -> None:
        target = self.fraction()
        if self._ease is not None:
            self._ease.stop()
            self._ease = None
        ms = motion.duration(VALUE_MS)
        if ms == 0 or not self.isVisible():
            self.shown = target
            self.update()
            return
        ease = QVariantAnimation(self)
        ease.setStartValue(self.shown)
        ease.setEndValue(target)
        ease.setDuration(ms)
        ease.setEasingCurve(QEasingCurve.Type.OutCubic)
        ease.valueChanged.connect(self._on_shown)
        self._ease = ease
        ease.start()

    def _on_shown(self, value: object) -> None:
        self.shown = float(value)  # type: ignore[arg-type]
        self.update()

    def run_rect(self) -> QRectF:
        """Where the indeterminate run is drawn: in from the left, across, and out."""
        width = float(self.width())
        run = width * RUN_SHARE
        left = -run + self.phase * (width + run)
        return QRectF(left, 0.0, run, float(self.height())).intersected(
            QRectF(0.0, 0.0, width, float(self.height()))
        )

    def paintEvent(self, _event: QPaintEvent) -> None:
        k = theme.ACTIVE
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self.height() / 2
        track = QRectF(self.rect())
        painter.setBrush(QColor(k.bg_subtle if self.busy() else k.border))
        painter.drawRoundedRect(track, radius, radius)
        if self.busy():
            if self.running():
                run = self.run_rect()
                if run.width() > 0:
                    painter.setBrush(QColor(k.accent))
                    painter.drawRoundedRect(run, radius, radius)
            else:
                painter.setBrush(QColor(k.accent_subtle))
                painter.drawRoundedRect(track, radius, radius)
        elif self.shown > 0:
            fill = QRectF(track)
            fill.setWidth(max(self.height(), track.width() * self.shown))
            painter.setBrush(QColor(k.accent))
            painter.drawRoundedRect(fill, radius, radius)
        painter.end()


class PlannerCard(QProgressDialog):
    """A ``QProgressDialog`` drawn as a card over the window; see the module's docstring."""

    def __init__(
        self,
        label: str,
        cancel: str,
        minimum: int,
        maximum: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(label, cancel, minimum, maximum, parent)
        self.setObjectName("plannerCard")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.shadow = SHADOW_PX if _translucent() else 0
        if self.shadow:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._label: QLabel | None = None
        self.bar = SweepBar()
        self.setBar(self.bar)
        self.setRange(minimum, maximum)
        # Last of the three: ``sizeHint`` and ``_place`` read it as "the card is built",
        # and the dialog asks for its size hint while it is being made.
        self.cancel_button = QPushButton(cancel)
        # Never the default: drawn in the accent, and pressed by an Enter meant for
        # something else. Escape still cancels.
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setDefault(False)
        self.setCancelButton(self.cancel_button)
        self.setLabel(QLabel())
        self.setLabelText(label)
        self.started = time.monotonic()
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)
        self._fade: QVariantAnimation | None = None

    # -- what the dialog lays out ------------------------------------------------------

    def setLabel(self, label: QLabel) -> None:
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        theme.size(label, theme.LEAD_PX)
        # Let go of the old one first: the dialog deletes it in here and asks for its size
        # hint as it does.
        self._label = None
        super().setLabel(label)
        self._label = label
        self._place()

    def inner(self) -> QRect:
        """The card itself: the window less the margin its shadow is drawn in."""
        pad = self.shadow
        return self.rect().adjusted(pad, pad, -pad, -pad)

    def caption_rect(self) -> QRect:
        card = self.inner()
        return QRect(
            card.left() + PAD_PX, card.top() + PAD_PX, card.width() - 2 * PAD_PX, theme.CAPTION_PX + 6
        )

    def _content_width(self) -> int:
        return CARD_WIDTH_PX - 2 * PAD_PX

    def _label_height(self) -> int:
        if self._label is None:
            return 0
        width = self._content_width()
        return max(self._label.heightForWidth(width), self._label.sizeHint().height())

    def sizeHint(self) -> QSize:
        if not hasattr(self, "cancel_button"):
            return super().sizeHint()
        gap = theme.SPACE["md"]
        button = self.cancel_button.sizeHint().height()
        height = (
            PAD_PX
            + self.caption_rect().height()
            + gap
            + self._label_height()
            + theme.SPACE["lg"]
            + BAR_PX
            + theme.SPACE["lg"]
            + button
            + PAD_PX
        )
        return QSize(CARD_WIDTH_PX + 2 * self.shadow, height + 2 * self.shadow)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _place(self) -> None:
        """Lay the label, the bar and Cancel out on the card. The dialog's own layout puts
        the label at the window's top edge, with no margin, and runs again on every resize."""
        if not hasattr(self, "cancel_button"):
            return
        card = self.inner()
        left = card.left() + PAD_PX
        width = card.width() - 2 * PAD_PX
        top = self.caption_rect().bottom() + 1 + theme.SPACE["md"]
        if self._label is not None:
            label_height = max(self._label.heightForWidth(width), self._label.sizeHint().height())
            self._label.setGeometry(left, top, width, label_height)
            top += label_height + theme.SPACE["lg"]
        self.bar.setGeometry(left, top, width, BAR_PX)
        size = self.cancel_button.sizeHint()
        self.cancel_button.setGeometry(
            card.right() + 1 - PAD_PX - size.width(),
            card.bottom() + 1 - PAD_PX - size.height(),
            size.width(),
            size.height(),
        )

    def setLabelText(self, text: str) -> None:
        super().setLabelText(text)
        if hasattr(self, "cancel_button"):
            wanted = self.sizeHint()
            if self.size() != wanted:
                self.resize(wanted)
            self._place()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place()

    # -- coming and going --------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        self.resize(self.sizeHint())
        parent = self.parentWidget()
        if parent is not None:
            centre = parent.mapToGlobal(parent.rect().center())
            self.move(centre.x() - self.width() // 2, centre.y() - self.height() // 2)
        super().showEvent(event)
        self._place()
        self.bar.start()
        self._clock.start()
        self._fade_in()

    def hideEvent(self, event: QHideEvent) -> None:
        self.bar.stop()
        self._clock.stop()
        if self._fade is not None:
            self._fade.stop()
            self._fade = None
        self.setWindowOpacity(1.0)
        super().hideEvent(event)

    def _fade_in(self) -> None:
        ms = motion.duration(FADE_IN_MS)
        if ms == 0:
            self.setWindowOpacity(1.0)
            return
        fade = QVariantAnimation(self)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setDuration(ms)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.valueChanged.connect(lambda value: self.setWindowOpacity(float(value)))
        self._fade = fade
        fade.start()

    def _tick(self) -> None:
        self.update(self.caption_rect())

    # -- drawing -----------------------------------------------------------------------

    def paintEvent(self, _event: QPaintEvent) -> None:
        k = theme.ACTIVE
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.inner())
        radius = float(theme.RADIUS_CARD) if self.shadow else 0.0
        if self.shadow:
            # Stacked rounded rectangles, faintest outermost, rather than a blur: the
            # shadow of hover's lifted cards, a little deeper because this one floats.
            steps = 7
            shade = QColor(0, 0, 0)
            painter.setPen(Qt.PenStyle.NoPen)
            for step in range(steps, 0, -1):
                grow = self.shadow * step / steps
                shade.setAlpha(max(1, int(k.shadow_alpha * 0.5 / steps)))
                painter.setBrush(shade)
                ring = card.adjusted(-grow * 0.8, -grow * 0.4, grow * 0.8, grow)
                painter.drawRoundedRect(ring, radius + grow, radius + grow)
        painter.setPen(QColor(k.border))
        painter.setBrush(QColor(k.bg_surface))
        painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        caption = self.caption_rect()
        face = painter.font()
        face.setPixelSize(theme.CAPTION_PX)
        face.setWeight(QFont.Weight.DemiBold)
        painter.setFont(face)
        painter.setPen(QColor(k.text_secondary))
        align = Qt.AlignmentFlag.AlignVCenter
        painter.drawText(caption, align | Qt.AlignmentFlag.AlignLeft, self.windowTitle())
        face.setWeight(QFont.Weight.Normal)
        painter.setFont(face)
        painter.setPen(QColor(k.text_tertiary))
        painter.drawText(
            caption, align | Qt.AlignmentFlag.AlignRight, elapsed_text(time.monotonic() - self.started)
        )
        painter.end()
