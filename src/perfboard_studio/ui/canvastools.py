"""Tools that float on the canvas they work on.

THE TOOLS LEFT THE TOOLBAR FOR THE BOARD. On a row across the window they were fifteen
buttons that meant something only while the board was in front -- so the row came and went
as the views did (``_sync_toolbars_to_view``), and with the sheet beside the board it offered
Rotate and Mirror for whichever of the two had been clicked last. Laid on the canvas they
belong to, a tool is where it acts: the board's drawing tools over the board, the sheet's
over the sheet, and nothing has to decide which row is showing.

Two kinds of thing go on a canvas and they are kept apart, as every drawing program keeps
them: the TOOLS, which arm a mode -- one at a time, Escape back to the pointer -- in a bar
down the left; and the VIEW, which changes how the canvas is looked at and never what is on
it -- what is shown, which side, how near -- in a cluster in the bottom-right corner. A
one-off command (route everything, place everything) is not a tool and is on neither: it is
the header's Next button when it is the next step, and a menu entry and a Ctrl+K entry
always.

TOOLS THAT ARE ONE IDEA SHARE A BUTTON (``add_group``). Solder trace and reinforced trace
are both solder; bare wire, insulated wire and a jumper over the parts are all a wire. The
button shows the one picked last, arms it on a click, and offers the rest when held or
right-clicked -- with the small triangle in its corner that says there are more. Five
conductor buttons that differed only in what ran between two pads became two, and each
keeps its own key (T, Shift+T, W, Shift+W, J).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QAction, QColor, QContextMenuEvent, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme

#: How far a floating bar keeps from the canvas's edges, in logical pixels.
MARGIN = 12


def with_more_mark(icon: QIcon, size: int = icons.SIZE) -> QIcon:
    """``icon`` with the small triangle in its bottom-right corner that says the button
    holds more than one tool."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    icon.paint(painter, 0, 0, size, size)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.colour("secondary")))
    mark = size * 0.28
    painter.drawPolygon(
        QPolygonF([QPointF(size, size - mark), QPointF(size, size), QPointF(size - mark, size)])
    )
    painter.end()
    return QIcon(pixmap)


class _GroupButton(QToolButton):
    """One button for a group of tools: shows the tool picked last, arms it on a click,
    and offers every tool of the group when held -- or right-clicked, which is quicker
    than holding and is what a person tries when a button looks as if it has more."""

    def __init__(self, actions: Sequence[QAction], pictures: dict[QAction, QIcon]) -> None:
        super().__init__()
        self._pictures = pictures
        self.group_menu = QMenu(self)
        self.group_menu.setToolTipsVisible(True)
        for action in actions:
            self.group_menu.addAction(action)
            action.triggered.connect(lambda _checked=False, a=action: self.show_tool(a))
        self.setMenu(self.group_menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        self._actions = tuple(actions)
        for action in actions:
            action.changed.connect(self._skip_a_tool_that_cannot_apply)
        self.show_tool(actions[0])
        self._skip_a_tool_that_cannot_apply()

    def show_tool(self, action: QAction) -> None:
        """Make ``action`` the one the button shows and arms."""
        self.setDefaultAction(action)
        self.setIcon(with_more_mark(self._pictures[action]))

    def _skip_a_tool_that_cannot_apply(self) -> None:
        """Show a tool the board can take: on a breadboard the wire button is the
        insulated wire, because bare wire under a breadboard is not a thing."""
        shown = self.defaultAction()
        if shown is not None and shown.isEnabled():
            return
        usable = next((action for action in self._actions if action.isEnabled()), None)
        if usable is not None:
            self.show_tool(usable)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.group_menu.popup(event.globalPos())


class FloatingBar(QFrame):
    """A rounded bar of buttons laid over a canvas, kept in one corner of it as the canvas
    is resized. A child of the canvas's own widget, so it moves, hides and floats with the
    panel the canvas is in, and needs nothing from the window to stay where it is."""

    def __init__(
        self,
        host: QWidget,
        corner: Qt.Corner | None,
        *,
        vertical: bool,
        name: str,
    ) -> None:
        super().__init__(host)
        self.setObjectName(name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._host = host
        #: The corner it keeps to, or None for a bar that follows a rectangle (``follow``).
        self._corner = corner
        self._over: QRect | None = None
        #: For a bar that follows something: where that something is now, asked again
        #: whenever ``_watched`` repaints (``track``).
        self._source: Callable[[], QRect | None] | None = None
        self._watched: QWidget | None = None
        layout: QBoxLayout = QVBoxLayout(self) if vertical else QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._layout = layout
        self._vertical = vertical
        #: The buttons in the order they were added, each with what it does.
        self.buttons: list[QToolButton] = []
        # Raised over the canvas, as the one sheet styles anything that floats; the shadow
        # is the theme's, because a style sheet cannot draw one.
        self.setProperty("floating", True)
        theme.elevate(self)
        host.installEventFilter(self)

    def _button(self) -> QToolButton:
        button = QToolButton()
        button.setIconSize(QSize(icons.SIZE, icons.SIZE))
        button.setAutoRaise(True)
        return button

    def add_action(
        self, action: QAction, picture: QIcon | None = None, *, only_when_enabled: bool = False
    ) -> QToolButton:
        """``action``'s button. ``only_when_enabled``: gone, not greyed, while the action
        cannot apply -- Cut Strip on a board with no strips is clutter, not information."""
        button = self._button()
        button.setDefaultAction(action)
        if picture is not None:
            button.setIcon(picture)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._layout.addWidget(button)
        self.buttons.append(button)
        if only_when_enabled:
            self._follow_enabled(button, (action,))
        self.adjustSize()
        return button

    def add_group(self, actions: Sequence[QAction], pictures: dict[QAction, QIcon]) -> QToolButton:
        """Several tools behind one button (see the module's last paragraph). Gone while
        none of them can apply: the solder tools on a solderless breadboard."""
        button = _GroupButton(actions, pictures)
        button.setIconSize(QSize(icons.SIZE, icons.SIZE))
        button.setAutoRaise(True)
        self._layout.addWidget(button)
        self.buttons.append(button)
        self._follow_enabled(button, tuple(actions))
        self.adjustSize()
        return button

    def _follow_enabled(self, button: QToolButton, actions: tuple[QAction, ...]) -> None:
        def sync() -> None:
            wanted = any(action.isEnabled() for action in actions)
            if button.isVisibleTo(self) != wanted:
                button.setVisible(wanted)
                self.place()

        for action in actions:
            action.changed.connect(sync)
        button.setVisible(any(action.isEnabled() for action in actions))

    def add_menu(self, picture: QIcon, menu: QMenu, tip: str, text: str = "") -> QToolButton:
        """A button that only opens ``menu``: the canvas's Show ▾."""
        button = self._button()
        button.setIcon(picture)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolTip(tip)
        if text:
            button.setText(text)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._layout.addWidget(button)
        self.buttons.append(button)
        self.adjustSize()
        return button

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)
        self.adjustSize()

    def add_separator(self) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine if self._vertical else QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setFixedSize(QSize(22, 1) if self._vertical else QSize(1, 22))
        self._layout.addWidget(line, 0, Qt.AlignmentFlag.AlignCenter)
        self.adjustSize()

    def track(self, source: Callable[[], QRect | None], watched: QWidget) -> None:
        """Follow whatever ``source`` says, asked again every time ``watched`` repaints.

        A repaint is the one notice every way of changing the view sends -- a scroll, the
        wheel, a pinch, Fit, a part moved by a command -- so following it keeps the bar over
        the selection without a hook in each of them."""
        self._source = source
        self._watched = watched
        watched.installEventFilter(self)

    def follow(self, rect: QRect | None) -> None:
        """Stand over ``rect`` (in the canvas's coordinates), or go away for None."""
        self._over = rect
        if rect is None:
            self.hide()
            return
        self.place()
        self.show()

    def place(self) -> None:
        """Into its corner of the canvas, above whatever the canvas draws -- or, for a bar
        that follows something, centred over it, and under it when there is no room above."""
        self.adjustSize()
        width, height = self._host.width(), self._host.height()
        if self._corner is None:
            if self._over is None:
                return
            gap = 8
            x = self._over.center().x() - self.width() // 2
            y = self._over.top() - self.height() - gap
            if y < MARGIN:
                y = self._over.bottom() + gap
            x = max(MARGIN, min(x, width - self.width() - MARGIN))
            y = max(MARGIN, min(y, height - self.height() - MARGIN))
            self.move(QPoint(x, y))
            self.raise_()
            return
        left = self._corner in (Qt.Corner.TopLeftCorner, Qt.Corner.BottomLeftCorner)
        top = self._corner in (Qt.Corner.TopLeftCorner, Qt.Corner.TopRightCorner)
        x = MARGIN if left else max(MARGIN, width - self.width() - MARGIN)
        y = MARGIN if top else max(MARGIN, height - self.height() - MARGIN)
        self.move(QPoint(x, y))
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._host and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.place()
        elif (
            watched is self._watched
            and self._source is not None
            and event.type() == QEvent.Type.Paint
        ):
            rect = self._source()
            if rect != self._over or (rect is not None and self.isHidden()):
                self.follow(rect)
        return False
