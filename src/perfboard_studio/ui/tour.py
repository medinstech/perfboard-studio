"""The getting-started tour: five presses of the next button, on a circuit already drawn.

THE TOUR TEACHES ONE GESTURE. Everything the application does from a drawn circuit to a
soldering guide is the header's next button pressed five times -- choose a board, place,
wire, check, open the guide -- and the tour is exactly that, said once: it opens the
example that is drawn and not built, lights the button, and says in a sentence what the
press will do and what the last one did. It never presses the button itself and has no
Next of its own, because the gesture is the thing being taught.

EACH STOP IS READ OFF THE WINDOW, not counted. Which sentence shows is decided by what the
next button would do now and whether the guide is open (``stop_for``), so a step done from
a menu, undone, or done twice still lands the tour on the right sentence -- a tour that
counts its own clicks is wrong the first time somebody does a step another way.

THE OVERLAY NEVER TAKES A CLICK. It dims the window around what it points at and is
transparent to the mouse, so the button under the spotlight is the real one and a part can
still be dragged where the sentence says it can. Only the bubble takes clicks: Skip, and
Finish at the end. It is offered on Home and in the Help menu, and never starts by itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme
from .i18n import t

#: How many stops the tour has, for the "2 / 5" in the bubble.
STOPS = 5
#: How often the tour looks at the window while it runs, in milliseconds. Polled rather than
#: wired to every signal that can change the next step: there are a dozen, and a tour that
#: missed one would sit on a sentence that is no longer true.
POLL_MS = 250


@dataclass(frozen=True, slots=True)
class Stop:
    """One sentence of the tour, and what it lights."""

    number: int
    text: str
    #: The object name of a panel to ring as well as the next button, or "".
    region: str
    last: bool = False


def stop_for(next_key: str, guide_open: bool) -> Stop:
    """The stop for a window whose next button would do ``next_key``."""
    if guide_open:
        return Stop(
            5,
            t("This is what you build from: the soldering order, lowest parts first. Tick a "
              "step and the next one lights up on the board. That's the whole app."),
            "dockGuide",
            last=True,
        )
    if next_key == "place":
        return Stop(
            2,
            t("Every board you can buy was tried with this circuit; the one chosen is the "
              "smallest that wires well. Next: Place on the Board."),
            "dockBoard",
        )
    if next_key == "route":
        return Stop(
            3,
            t("The parts are arranged for you. Drag any of them if you like. Next: "
              "Auto-wire."),
            "dockBoard",
        )
    if next_key in ("check", "build"):
        return Stop(
            4,
            t("Wired: solder traces first, a wire only where solder can't go. The checks ran "
              "by themselves; what they found is below. Next: open the build guide."),
            "dockDrc",
        )
    return Stop(
        1,
        t("The circuit is already drawn. This blue button is always your next step. Press "
          "it: Choose a Board."),
        "",
    )


class Spotlight(QWidget):
    """Dims the window except the holes it is given, and rings them. Takes no clicks."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("tourSpotlight")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.target = QRect()
        self.region = QRect()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.addRect(self.rect().toRectF())
        for hole in (self.target, self.region):
            if not hole.isNull():
                cut = QPainterPath()
                cut.addRoundedRect(hole.toRectF(), theme.RADIUS_LG, theme.RADIUS_LG)
                shade = shade.subtracted(cut)
        dim = QColor(theme.ACTIVE.bg_app)
        dim.setAlpha(150)
        painter.fillPath(shade, dim)
        accent = QColor(theme.colour("accent"))
        if not self.target.isNull():
            painter.setPen(QPen(accent, 2))
            painter.drawRoundedRect(self.target.toRectF(), theme.RADIUS_LG, theme.RADIUS_LG)
        if not self.region.isNull():
            pen = QPen(QColor(theme.colour("secondary")), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(self.region.toRectF(), theme.RADIUS_LG, theme.RADIUS_LG)


class Bubble(QFrame):
    """The sentence, where the tour is, and the way out."""

    def __init__(self, parent: QWidget, on_skip: Callable[[], None]) -> None:
        super().__init__(parent)
        self.setObjectName("tourBubble")
        theme.variant(self, "card")
        self.setFixedWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([theme.SPACE["lg"]] * 4))
        layout.setSpacing(theme.SPACE["md"])
        self.text = QLabel()
        self.text.setWordWrap(True)
        layout.addWidget(self.text)
        row = QHBoxLayout()
        self.count = QLabel()
        theme.tone(self.count, "tertiary")
        row.addWidget(self.count)
        row.addStretch(1)
        self.skip = QPushButton(t("Skip Tour"))
        theme.variant(self.skip, "link")
        self.skip.clicked.connect(lambda _checked=False: on_skip())
        row.addWidget(self.skip)
        self.finish = QPushButton(t("Finish"))
        theme.variant(self.finish, "primary")
        self.finish.clicked.connect(lambda _checked=False: on_skip())
        row.addWidget(self.finish)
        layout.addLayout(row)

    def show_stop(self, stop: Stop) -> None:
        self.text.setText(stop.text)
        self.count.setText(f"{stop.number} / {STOPS}")
        self.skip.setVisible(not stop.last)
        self.finish.setVisible(stop.last)
        self.adjustSize()


class Tour(QObject):
    """The tour over ``window``: started by ``start``, gone at Skip, Finish or Esc.

    ``next_button`` is the header's next button and ``next_key`` reads what it would do; the
    window's panels are found by their object names, so the tour imports no window."""

    def __init__(
        self,
        window: QWidget,
        next_button: QWidget,
        next_key: Callable[[], str],
        guide_open: Callable[[], bool],
    ) -> None:
        super().__init__(window)
        self._window = window
        self._next_button = next_button
        self._next_key = next_key
        self._guide_open = guide_open
        self.spotlight = Spotlight(window)
        self.bubble = Bubble(window, self.stop)
        self.stop_shown: Stop | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.update)
        window.installEventFilter(self)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        self.spotlight.show()
        self.bubble.show()
        self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()
        self._window.removeEventFilter(self)
        self.spotlight.hide()
        self.bubble.hide()
        self.spotlight.deleteLater()
        self.bubble.deleteLater()

    def update(self) -> None:
        """Read the window, show the stop it is at, and put the light where it belongs."""
        if not self.running:
            return
        stop = stop_for(self._next_key(), self._guide_open())
        if stop != self.stop_shown:
            self.stop_shown = stop
            self.bubble.show_stop(stop)
        self.spotlight.setGeometry(self._window.rect())
        target = self._rect_of(self._next_button) if not stop.last else QRect()
        region = self._rect_of(self._window.findChild(QWidget, stop.region)) if stop.region else QRect()
        pad = theme.SPACE["xs"]
        self.spotlight.target = target.adjusted(-pad, -pad, pad, pad) if not target.isNull() else target
        self.spotlight.region = region
        self.spotlight.raise_()
        self.spotlight.update()
        self._place_bubble(target if not target.isNull() else region)
        self.bubble.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Esc is left to the window, which gives it to a mode or a selection: a second claim
        # on it would make Qt drop both. Skip is in the bubble.
        if watched is self._window and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.update()
        return False

    def _rect_of(self, widget: QWidget | None) -> QRect:
        if widget is None or not widget.isVisible():
            return QRect()
        corner = widget.mapTo(self._window, QPoint(0, 0))
        return QRect(corner, widget.size())

    def _place_bubble(self, near: QRect) -> None:
        area = self._window.rect()
        # Its real size: a fixed-width frame's sizeHint does not know about the fixed width.
        self.bubble.adjustSize()
        size = self.bubble.size()
        gap = theme.SPACE["lg"]
        if near.isNull():
            x, y = area.center().x() - size.width() // 2, area.center().y() - size.height() // 2
        elif near.height() > area.height() // 2:
            # A tall panel at the side: the bubble beside it, facing in.
            x = near.left() - size.width() - gap
            y = near.top() + gap * 4
        else:
            # The next button, top right: the bubble under it, right edges aligned.
            x = near.right() - size.width()
            y = near.bottom() + gap
        x = max(area.left() + gap, min(x, area.right() - size.width() - gap))
        y = max(area.top() + gap, min(y, area.bottom() - size.height() - gap))
        self.bubble.move(x, y)
