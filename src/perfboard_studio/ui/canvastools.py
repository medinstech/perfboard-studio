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

EVERY TOOL HAS A BUTTON OF ITS OWN, AND A HAIRLINE KEEPS THE KINDS APART
(``add_separator``). The five conductors were once two buttons, solder and wire, each showing
the tool picked last with the rest behind a chevron, a right-click or a press held down.
It saved three buttons' height and hid what a rail is for: the builder at the window looked
for the insulated wire and the jumper and did not find them, and a press held a moment long
opened a list where a click was meant to arm. A run whose every tool the board cannot take
goes with its hairline (``_tidy``), so a solderless breadboard shows no empty run.

A TOOL SAYS ITS NAME THE MOMENT THE POINTER IS ON IT (``names=True``). The rail is pictures
alone, and a picture was named only by a tooltip a second later: the builder could not tell
four of them apart, and hovered each in turn to find out. Now a pill beside the button says
the tool and its key at once, and stands in for the tooltip rather than adding to it -- two
labels saying one name, one late, is clutter. A conductor's pill says under its name, in a
line, what it lays (``note``).
"""

from __future__ import annotations

import html
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme

#: How far a floating bar keeps from the canvas's edges, in logical pixels.
MARGIN = 12



def tool_name(action: QAction) -> str:
    """An action's name as a person reads it: no accelerator ampersand, no trailing dots."""
    text = action.text().replace("&&", "\0")
    return text.replace("&", "").replace("\0", "&").rstrip("…").rstrip(".")


def tool_key(action: QAction) -> str:
    """The key an action is on, as the platform writes it, or nothing."""
    shortcut = action.shortcut()
    return "" if shortcut.isEmpty() else shortcut.toString(QKeySequence.SequenceFormat.NativeText)


class TwoWaySwitch(QFrame):
    """A checkable action said as its two answers side by side, the one in force marked:
    the board pill's [Both Faces | This Face].

    A menu entry with a tick says what is on only to somebody who opens the menu; two words
    on the board say it to anybody looking at the board, and either is one click. The action
    stays the one truth -- its menu entry, its stored setting and this switch all follow it."""

    def __init__(
        self, action: QAction, on: tuple[str, str], off: tuple[str, str], *, name: str
    ) -> None:
        """``on`` and ``off`` are each a word and its tooltip: what the switch says for the
        action checked, and for it not."""
        super().__init__()
        self.setObjectName(name)
        self.setProperty("switch", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        self._action = action
        self.on_button = self._side(row, *on, value=True)
        self.off_button = self._side(row, *off, value=False)
        action.toggled.connect(self._sync)
        action.changed.connect(self._sync)
        self._sync()

    def _side(self, row: QHBoxLayout, text: str, tip: str, *, value: bool) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tip)
        button.setCheckable(True)
        button.setAutoRaise(True)
        # One of a row of choices: the theme marks the chosen one (``segment``).
        button.setProperty("segment", True)
        button.clicked.connect(lambda _checked=False: self._choose(value))
        row.addWidget(button)
        return button

    def _choose(self, value: bool) -> None:
        if self._action.isEnabled():
            self._action.setChecked(value)
        # A click on the answer already in force leaves it marked, not unmarked.
        self._sync()

    def _sync(self, *_: object) -> None:
        on = self._action.isChecked()
        self.on_button.setChecked(on)
        self.off_button.setChecked(not on)
        self.setEnabled(self._action.isEnabled())


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
        #: The hairlines between kinds, which go when the run they close has nothing in it.
        self._separators: list[QFrame] = []
        #: What the bar gives up, in order, when the canvas is too small for all of it
        #: (``when_narrow``).
        self._narrowing: list[Callable[[bool], None]] = []
        #: ``names``: each button says its tool and key in a pill beside it while the
        #: pointer is on it, in place of its tooltip (see the module's last paragraph).
        self._names = names
        self._keys: dict[QToolButton, str] = {}
        self._notes: dict[QToolButton, str] = {}
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

    def _named(self, button: QToolButton, key: str = "", note: str = "") -> None:
        """Watch ``button`` for the pointer, to name it; ``key`` stands in for an action
        with no key of its own (the pointer, which Escape comes back to), and ``note`` is
        a line under the name on what the tool lays."""
        if self._names:
            if key:
                self._keys[button] = key
            if note:
                self._notes[button] = note
            button.installEventFilter(self)

    def pill_text(self, button: QToolButton) -> str:
        """What the pill beside ``button`` says: its tool, and the key the tool is on."""
        action = button.defaultAction()
        if action is None:
            return ""
        key = tool_key(action) or self._keys.get(button, "")
        said = html.escape(tool_name(action))
        if key:
            said += f"&nbsp;&nbsp;{theme.ink(html.escape(key), 'tertiary')}"
        note = self._notes.get(button, "")
        if note:
            said += "<br>" + theme.ink(html.escape(note), "secondary")
        return said

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
        note: str = "",
    ) -> QToolButton:
        """``action``'s button. ``only_when_enabled``: gone, not greyed, while the action
        cannot apply -- Cut Strip on a board with no strips is clutter, not information.
        ``key``: what the name pill gives as its key when the action has none; ``note``:
        what it says under the name."""
        button = self._button()
        button.setDefaultAction(action)
        if picture is not None:
            button.setIcon(picture)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._layout.addWidget(button)
        self.buttons.append(button)
        if only_when_enabled:
            self._follow_enabled(button, (action,))
        self._named(button, key, note)
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
        line.setProperty("separator", True)
        line.setFrameShape(QFrame.Shape.NoFrame)
        line.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        line.setFixedSize(QSize(22, 1) if self._vertical else QSize(1, 22))
        self._layout.addWidget(line, 0, Qt.AlignmentFlag.AlignCenter)
        self._separators.append(line)
        self.adjustSize()

    def when_narrow(self, step: Callable[[bool], None]) -> None:
        """``step(True)`` gives something up when the bar is longer than its canvas has
        room for, and ``step(False)`` takes it back; the steps are taken in the order they
        were given, each only while the bar still does not fit -- as the header sheds its
        words before the step bar loses a step's name."""
        self._narrowing.append(step)

    def _fit(self) -> None:
        if not self._narrowing:
            return
        room = (self._host.height() if self._vertical else self._host.width()) - 2 * MARGIN

        def length() -> int:
            hint = self.sizeHint()
            return hint.height() if self._vertical else hint.width()

        for step in self._narrowing:
            step(False)
        for step in self._narrowing:
            if length() <= room:
                break
            step(True)

    def _tidy(self) -> None:
        """A hairline only between two kinds that are both there: one closing a run whose
        every button is gone goes too, as does one with nothing after it."""
        # A hairline is held back until a button after it shows; a second one while it is
        # held back, or one before any button, is a run with nothing in it.
        pending: QFrame | None = None
        seen = False
        for index in range(self._layout.count()):
            item = self._layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is None:
                continue
            if widget in self._separators:
                if seen and pending is None:
                    pending = widget
                else:
                    widget.setVisible(False)
            elif widget.isVisibleTo(self):
                if pending is not None:
                    pending.setVisible(True)
                    pending = None
                seen = True
        if pending is not None:
            pending.setVisible(False)

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
        if self._corner is not None:
            self._fit()
        self._tidy()
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
