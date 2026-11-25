"""What an empty panel says: one pattern, so every one says it the same way.

A PANEL WITH NOTHING IN IT LOOKED BROKEN. The Nets panel was four column headings over
grey, the Part List the same, the guide said nothing until its Next button was pressed,
and the sheet's only word was a status line above an empty canvas. Somebody new could not
tell an empty panel from one that had failed to load, and nothing said how the panel would
come to have something in it.

THE PATTERN: a title, at most two lines, at most ONE button, and dim links for any other
door. The title says what will be here; the lines say how it gets here; the button, when
there is one, does the step that fills the panel -- the same command, under the same name,
as the next button at the top of the window, so a panel and the header never offer two
different ways to do one thing.

``EmptyOverlay`` lays an ``EmptyState`` over a widget and shows it exactly while that widget
has nothing to show. Over a list or a tree it follows the model's own signals, so a panel
never has to remember to say it is empty; over anything else the owner calls ``refresh``.

A state may carry the panel's own icon over its title, in a soft accent disc: the picture
the panel's button or menu item already shows, so the empty panel and the way to it look
alike. And a panel that BECOMES empty while it is on screen -- the last net deleted, the
board's parts all taken off -- has its words fade in and rise a few pixels into place
(``ARRIVE_MS``, ``RISE_PX``) rather than replace the rows in one frame, which read as the
panel failing. Through ``motion``: reduced, or a panel not yet shown, the words are simply
there.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QIcon, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGraphicsEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, motion, theme

#: How long an empty state takes to arrive, and how far below its place it starts.
ARRIVE_MS = 220
RISE_PX = 8
#: The disc an empty state's icon sits in, and the icon in it.
BADGE_PX = 52
BADGE_ICON_PX = 26


class Badge(QWidget):
    """A panel's icon in a soft accent disc, over an empty state's title."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.setFixedSize(BADGE_PX, BADGE_PX)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.ACTIVE.accent_subtle))
        painter.drawEllipse(QRectF(self.rect()))
        side = BADGE_ICON_PX
        corner = (BADGE_PX - side) // 2
        # The icon's "on" picture: drawn in the accent, as a checked tool is.
        picture = icons.icon(self.name).pixmap(QSize(side, side), QIcon.Mode.Normal, QIcon.State.On)
        painter.drawPixmap(corner, corner, side, side, picture)
        painter.end()


class EmptyState(QWidget):
    """A title, a line or two, at most one button and a few links, centred."""

    def __init__(
        self,
        title: str,
        body: str,
        button: tuple[str, Callable[[], object]] | None = None,
        links: Sequence[tuple[str, Callable[[], object]]] = (),
        parent: QWidget | None = None,
        icon: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("emptyState")
        # Opaque, in the colour of what it covers: a guide with no part steps still has
        # its closing checks in the tree, and words drawn over rows are read as neither.
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([theme.SPACE["xl"]] * 4))
        layout.setSpacing(theme.SPACE["sm"])
        layout.addStretch(1)
        self.badge: Badge | None = None
        if icon is not None:
            self.badge = Badge(icon)
            layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignHCenter)
            layout.addSpacing(theme.SPACE["xs"])
        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        theme.size(self.title, theme.LEAD_PX)
        self.body = QLabel(body)
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setWordWrap(True)
        theme.tone(self.body, "secondary")
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        self.button: QPushButton | None = None
        if button is not None:
            label, action = button
            self.button = QPushButton(label)
            theme.variant(self.button, "primary")
            # Bound now: the links below reuse the name ``action``.
            self.button.clicked.connect(lambda _checked=False, a=action: a())
            layout.addSpacing(theme.SPACE["xs"])
            layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.links: list[QPushButton] = []
        if links:
            row = QHBoxLayout()
            row.addStretch(1)
            for label, action in links:
                link = QPushButton(label)
                theme.variant(link, "link")
                link.clicked.connect(lambda _checked=False, a=action: a())
                row.addWidget(link)
                self.links.append(link)
            row.addStretch(1)
            layout.addLayout(row)
        layout.addStretch(1)

    def say(self, title: str, body: str, button_shown: bool = True) -> None:
        """Change the words, for a panel whose emptiness has more than one cause."""
        self.title.setText(title)
        self.body.setText(body)
        if self.button is not None:
            self.button.setVisible(button_shown)


class EmptyOverlay(QObject):
    """Shows ``state`` over ``cover`` while ``is_empty()`` says there is nothing to show."""

    def __init__(self, cover: QWidget, state: EmptyState, is_empty: Callable[[], bool]) -> None:
        super().__init__(cover)
        self._cover = cover
        self._is_empty = is_empty
        self.state = state
        #: The arrival under way, if one is: a level from 0 (below, clear) to 1 (in place).
        self._arrival: QVariantAnimation | None = None
        self._level = 1.0
        state.setParent(cover)
        cover.installEventFilter(self)
        self.refresh()

    @classmethod
    def over_view(cls, view: QAbstractItemView, state: EmptyState) -> EmptyOverlay:
        """Over a list or tree: empty while its model has no rows, kept up by the model."""
        model = view.model()
        overlay = cls(view.viewport(), state, lambda: model.rowCount() == 0)
        for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.layoutChanged):
            signal.connect(overlay.refresh)
        return overlay

    def refresh(self, *_args: object) -> None:
        empty = self._is_empty()
        arriving = empty and self.state.isHidden() and self._cover.isVisible()
        self.state.setVisible(empty)
        if not empty:
            self._settle()
            return
        self.state.raise_()
        if arriving:
            self._arrive()
        else:
            self._place()

    def arriving(self) -> bool:
        """Whether the words are still on their way in."""
        return self._arrival is not None

    def _place(self) -> None:
        rise = round((1.0 - self._level) * RISE_PX)
        self.state.setGeometry(self._cover.rect().translated(0, rise))

    def _arrive(self) -> None:
        ms = motion.duration(ARRIVE_MS)
        if ms == 0:
            self._settle()
            return
        self._settle()
        fade = QGraphicsOpacityEffect(self.state)
        fade.setOpacity(0.0)
        self.state.setGraphicsEffect(fade)
        arrival = QVariantAnimation(self)
        arrival.setStartValue(0.0)
        arrival.setEndValue(1.0)
        arrival.setDuration(ms)
        arrival.setEasingCurve(QEasingCurve.Type.OutCubic)
        arrival.valueChanged.connect(self._step)
        arrival.finished.connect(self._settle)
        self._arrival = arrival
        self._level = 0.0
        self._place()
        arrival.start()

    def _step(self, value: object) -> None:
        self._level = float(cast(float, value))
        effect = self.state.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(self._level)
        self._place()

    def _settle(self) -> None:
        """In place and opaque, with nothing running and no effect left on the words: an
        opacity effect renders its widget through a pixmap for as long as it is set."""
        if self._arrival is not None:
            self._arrival.stop()
            self._arrival = None
        self._level = 1.0
        if self.state.graphicsEffect() is not None:
            self.state.setGraphicsEffect(cast(QGraphicsEffect, None))
        if self.state.isVisible():
            self._place()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and self.state.isVisible():
            self._place()
        return False
