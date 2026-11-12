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
button shows the one picked last and arms it on a click; the chevron beside its picture
opens the group -- as do a right-click and a press held down -- listing each tool with its
name, its key and a line on what it lays. Five conductor buttons that differed only in what
ran between two pads became two, and each keeps its own key (T, Shift+T, W, Shift+W, J).

A TOOL SAYS ITS NAME THE MOMENT THE POINTER IS ON IT (``names=True``). The rail is pictures
alone, and a picture was named only by a tooltip a second later: the builder could not tell
four of them apart, and hovered each in turn to find out. Now a pill beside the button says
the tool and its key at once, and stands in for the tooltip rather than adding to it -- two
labels saying one name, one late, is clutter. The group's list says the rest.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QContextMenuEvent,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme

#: How far a floating bar keeps from the canvas's edges, in logical pixels.
MARGIN = 12


#: How wide the chevron beside a group's picture is, in logical pixels.
CHEVRON = 8

#: How long a press is held before it opens a group instead of arming its tool.
HOLD_MS = 350


def with_chevron(icon: QIcon, size: int = icons.SIZE) -> QIcon:
    """``icon`` with a chevron beside it that says the button holds more than one tool.

    It was a triangle in the picture's corner, a fifth of the icon wide, and the builder did
    not see it: a group read as one tool, and the rest of it as not there at all."""
    width = size + CHEVRON
    pixmap = QPixmap(width * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    icon.paint(painter, 0, 0, size, size)
    pen = icons._pen(theme.colour("secondary"), 1.6)
    painter.setPen(pen)
    x, mid = size + 2.5, size / 2
    painter.drawPolyline([QPointF(x, mid - 4), QPointF(x + 4, mid), QPointF(x, mid + 4)])
    painter.end()
    return QIcon(pixmap)


def tool_name(action: QAction) -> str:
    """An action's name as a person reads it: no accelerator ampersand, no trailing dots."""
    text = action.text().replace("&&", "\0")
    return text.replace("&", "").replace("\0", "&").rstrip("…").rstrip(".")


def tool_key(action: QAction) -> str:
    """The key an action is on, as the platform writes it, or nothing."""
    shortcut = action.shortcut()
    return "" if shortcut.isEmpty() else shortcut.toString(QKeySequence.SequenceFormat.NativeText)


def _plain_label(text: str, role: theme.Role) -> QLabel:
    label = QLabel(text)
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    theme.tone(label, role)
    return label


class _FlyoutRow(QFrame):
    """One tool in a group's list: its picture, its name with a line on what it lays under
    it, and its key -- the three things the rail's picture could not say.

    A frame that clicks rather than a tool button: a QToolButton with a layout of its own
    inside a popup closed the popup the moment it was shown."""

    clicked = Signal()

    def __init__(self, action: QAction, picture: QIcon, note: str) -> None:
        super().__init__()
        self.action_ = action
        self._picture = picture
        self._armed = False
        self.setObjectName("toolFlyoutRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 8, 4)
        row.setSpacing(8)
        self.picture = QLabel()
        self.picture.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(self.picture, 0, Qt.AlignmentFlag.AlignTop)
        # Into the row before anything is put in it, and a label only ever HIDDEN: a label
        # shown before it has a parent is a window of its own, and one flashing up beside
        # the popup took the activation from it and closed it as it opened.
        words = QVBoxLayout()
        words.setSpacing(0)
        row.addLayout(words, 1)
        self.name = _plain_label(tool_name(action), "text")
        words.addWidget(self.name)
        self.note = _plain_label(note, "secondary")
        small = self.note.font()
        small.setPointSizeF(small.pointSizeF() * 0.9)
        self.note.setFont(small)
        words.addWidget(self.note)
        if not note:
            self.note.hide()
        self.key = _plain_label(tool_key(action), "tertiary")
        self.key.setObjectName("toolKey")
        row.addWidget(self.key, 0, Qt.AlignmentFlag.AlignTop)
        if not self.key.text():
            self.key.hide()
        self.refresh()

    def refresh(self) -> None:
        """In step with the action: lit while it is the tool armed, grey while the board
        cannot take it (bare wire on a breadboard)."""
        armed = self.action_.isChecked()
        self._armed = armed
        self.setProperty("armed", armed)
        theme.restyle(self)
        self.setEnabled(self.action_.isEnabled())
        state = QIcon.State.On if armed else QIcon.State.Off
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        self.picture.setPixmap(self._picture.pixmap(QSize(icons.SIZE, icons.SIZE), mode, state))
        role: theme.Role = "accent" if armed else ("text" if self.isEnabled() else "tertiary")
        theme.tone(self.name, role)

    def isChecked(self) -> bool:
        """Whether this row's tool is the one armed."""
        return self._armed

    def click(self) -> None:
        if self.isEnabled():
            self.clicked.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.click()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            return
        super().keyPressEvent(event)


class _ToolFlyout(QFrame):
    """A group's tools, listed beside its button: a popup, so a click anywhere else or
    Escape puts it away, and a click on a row arms that tool."""

    #: Room left round the card for its shadow, which a popup window would otherwise clip.
    SHADOW = 10

    def __init__(self, owner: _GroupButton) -> None:
        super().__init__(owner, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("toolFlyoutWindow")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.SHADOW, self.SHADOW, self.SHADOW, self.SHADOW)
        card = QFrame()
        card.setObjectName("toolFlyout")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setProperty("floating", True)
        theme.elevate(card)
        outer.addWidget(card)
        rows = QVBoxLayout(card)
        rows.setContentsMargins(4, 4, 4, 4)
        rows.setSpacing(1)
        self.rows: list[_FlyoutRow] = []
        for action in owner.tools:
            row = _FlyoutRow(action, owner.picture(action), owner.note(action))
            row.clicked.connect(lambda _checked=False, a=action: self._pick(a))
            rows.addWidget(row)
            self.rows.append(row)

    def open_beside(self, button: QToolButton) -> None:
        """Beside the bar ``button`` is on, its first row level with the button."""
        for row in self.rows:
            row.refresh()
        self.adjustSize()
        bar = button.parentWidget() or button
        x = bar.mapToGlobal(QPoint(bar.width(), 0)).x() + 6 - self.SHADOW
        y = button.mapToGlobal(QPoint(0, 0)).y() - 4 - self.SHADOW
        self.move(QPoint(x, y))
        self.show()
        focus = next((r for r in self.rows if r.isChecked()), None) or next(
            (r for r in self.rows if r.isEnabled()), None
        )
        if focus is not None:
            focus.setFocus(Qt.FocusReason.PopupFocusReason)

    def _pick(self, action: QAction) -> None:
        self.hide()
        # Picking the tool that is already armed keeps it armed: triggering a checked
        # action would put it down, which is not what choosing it from a list means.
        if action.isEnabled() and not action.isChecked():
            action.trigger()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.focusNextPrevChild(key == Qt.Key.Key_Down)
            return
        super().keyPressEvent(event)


class _GroupButton(QToolButton):
    """One button for a group of tools: shows the tool picked last and arms it on a click;
    the chevron beside its picture lists the whole group, as a right-click and a press held
    down do."""

    def __init__(
        self,
        actions: Sequence[QAction],
        pictures: dict[QAction, QIcon],
        notes: dict[QAction, str] | None = None,
    ) -> None:
        super().__init__()
        self._pictures = pictures
        self._notes = dict(notes or {})
        self.tools = tuple(actions)
        for action in actions:
            action.triggered.connect(lambda _checked=False, a=action: self.show_tool(a))
            action.changed.connect(self._skip_a_tool_that_cannot_apply)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(HOLD_MS)
        self._hold.timeout.connect(self._open_on_hold)
        self.flyout: _ToolFlyout | None = None
        self.show_tool(actions[0])
        self._skip_a_tool_that_cannot_apply()

    def picture(self, action: QAction) -> QIcon:
        return self._pictures.get(action, action.icon())

    def note(self, action: QAction) -> str:
        return self._notes.get(action, "")

    def show_tool(self, action: QAction) -> None:
        """Make ``action`` the one the button shows and arms."""
        # setDefaultAction ADDS the action to the button, and a tool button holding more
        # than one action draws a menu arrow and offers them on a held press itself -- a
        # second way into the group, under the chevron, once a second tool was picked.
        shown = self.defaultAction()
        self.setDefaultAction(action)
        if shown is not None and shown is not action:
            self.removeAction(shown)
        self._mark()

    def _mark(self) -> None:
        shown = self.defaultAction()
        if shown is not None:
            self.setIcon(with_chevron(self.picture(shown)))

    def actionEvent(self, event: QEvent) -> None:
        # A button takes its default action's icon back whenever the action changes -- on
        # every arming, since arming checks it -- and that dropped the chevron.
        super().actionEvent(event)  # type: ignore[arg-type]
        self._mark()

    def _skip_a_tool_that_cannot_apply(self) -> None:
        """Show a tool the board can take: on a breadboard the wire button is the
        insulated wire, because bare wire under a breadboard is not a thing."""
        shown = self.defaultAction()
        if shown is not None and shown.isEnabled():
            return
        usable = next((action for action in self.tools if action.isEnabled()), None)
        if usable is not None:
            self.show_tool(usable)

    def open_group(self) -> None:
        """List the group's tools beside the button."""
        self._hold.stop()
        if self.flyout is None:
            self.flyout = _ToolFlyout(self)
        self.flyout.open_beside(self)

    def _on_chevron(self, x: float) -> bool:
        return x >= self.width() - CHEVRON - 6

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_chevron(event.position().x()):
            event.accept()
            self.open_group()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._hold.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._hold.stop()
        super().mouseReleaseEvent(event)

    def _open_on_hold(self) -> None:
        if self.isDown():
            # Held, not clicked: the press opens the list and arms nothing.
            self.setDown(False)
            self.open_group()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        event.accept()
        self.open_group()


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
        names: bool = False,
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
        #: ``names``: each button says its tool and key in a pill beside it while the
        #: pointer is on it, in place of its tooltip (see the module's last paragraph).
        self._names = names
        self._keys: dict[QToolButton, str] = {}
        self.name_pill: QLabel | None = None
        if names:
            pill = QLabel(host)
            pill.setObjectName("toolName")
            pill.setProperty("floating", True)
            pill.setTextFormat(Qt.TextFormat.RichText)
            pill.setContentsMargins(8, 3, 8, 3)
            pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            pill.hide()
            self.name_pill = pill
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

    def _named(self, button: QToolButton, key: str = "") -> None:
        """Watch ``button`` for the pointer, to name it; ``key`` stands in for an action
        with no key of its own (the pointer, which Escape comes back to)."""
        if self._names:
            if key:
                self._keys[button] = key
            button.installEventFilter(self)

    def pill_text(self, button: QToolButton) -> str:
        """What the pill beside ``button`` says: its tool, and the key the tool is on."""
        action = button.defaultAction()
        if action is None:
            return ""
        key = tool_key(action) or self._keys.get(button, "")
        name = html.escape(tool_name(action))
        if not key:
            return name
        return f"{name}&nbsp;&nbsp;{theme.ink(html.escape(key), 'tertiary')}"

    def _show_name(self, button: QToolButton) -> None:
        pill = self.name_pill
        if pill is None:
            return
        text = self.pill_text(button)
        if not text:
            pill.hide()
            return
        pill.setText(text)
        pill.adjustSize()
        x = self.geometry().right() + 8
        y = self.y() + button.y() + (button.height() - pill.height()) // 2
        pill.move(x, y)
        pill.show()
        pill.raise_()

    def _hide_name(self) -> None:
        if self.name_pill is not None:
            self.name_pill.hide()

    def add_action(
        self,
        action: QAction,
        picture: QIcon | None = None,
        *,
        only_when_enabled: bool = False,
        key: str = "",
    ) -> QToolButton:
        """``action``'s button. ``only_when_enabled``: gone, not greyed, while the action
        cannot apply -- Cut Strip on a board with no strips is clutter, not information.
        ``key``: what the name pill gives as its key when the action has none."""
        button = self._button()
        button.setDefaultAction(action)
        if picture is not None:
            button.setIcon(picture)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._layout.addWidget(button)
        self.buttons.append(button)
        if only_when_enabled:
            self._follow_enabled(button, (action,))
        self._named(button, key)
        self.adjustSize()
        return button

    def add_group(
        self,
        actions: Sequence[QAction],
        pictures: dict[QAction, QIcon],
        notes: dict[QAction, str] | None = None,
    ) -> _GroupButton:
        """Several tools behind one button (see the module's first paragraphs), ``notes``
        saying in a line what each lays. Gone while none of them can apply: the solder
        tools on a solderless breadboard."""
        button = _GroupButton(actions, pictures, notes)
        button.setIconSize(QSize(icons.SIZE + CHEVRON, icons.SIZE))
        button.setAutoRaise(True)
        self._named(button)
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
        if isinstance(watched, QToolButton) and watched in self.buttons:
            kind = event.type()
            if kind == QEvent.Type.ToolTip:
                return True  # the pill has said it already
            if kind == QEvent.Type.Enter:
                self._show_name(watched)
            elif kind in (
                QEvent.Type.Leave,
                QEvent.Type.Hide,
                QEvent.Type.MouseButtonPress,
                QEvent.Type.ContextMenu,
            ):
                self._hide_name()
            return False
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
