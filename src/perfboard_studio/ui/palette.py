"""The command palette: Ctrl+K, type a few letters, Enter.

EVERY COMMAND, BY ITS NAME. The menus went behind one button to give the board its room, and
a menu walked from the top is where a command is hunted for, not found: four levels for
"Lay Wires Along the Grid". The palette lists every entry of every menu by the words it
already has, says which menu it lives in and its key, and runs it -- and a part or a net by
its name, which is what Go to Part was for. Nothing here is a second list of commands: the
window hands it the menus' own actions (``MainWindow._palette_entries``), so a command the
menus grey out is not offered, and one added to a menu is offered with no line here.

Ranked plainly, because what is typed is nearly always the start of a word: a name that
starts with it first, then one with a word that does, then one that only contains it; ties
in the order the menus list them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

from PySide6.QtCore import (
    QChildEvent,
    QEasingCurve,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QShowEvent,
    QWindow,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import motion, theme
from .i18n import t

#: How many rows the list shows before it scrolls, and how wide the palette stands.
VISIBLE_ROWS = 10
WIDTH = 620

#: The QAction property holding more words a command is found by, comma-separated, in the
#: window's language: what people call it that its name does not say.
ALSO = "paletteAlso"

#: The palette drops into place as it opens: this far, this long. Closing is immediate --
#: whatever was asked for runs at once, and nothing should stand between Enter and it.
DROP_PX = 10
OPEN_MS = 160

#: The key that opens the palette, and closes it again while it is open.
SHORTCUT = "Ctrl+K"


@dataclass(frozen=True, slots=True)
class Entry:
    """One thing the palette can do: what it is called, where it lives, its key."""

    label: str
    where: str
    keys: str
    run: Callable[[], None]
    icon: QIcon | None = None
    #: "command", "part" or "net": what Ctrl+G narrows the palette to (``open``).
    kind: str = "command"
    #: More words it is found by, after its own name and place: its tooltip and its
    #: synonyms (``ALSO``). "perfboard" did not find New Board from This Design, whose
    #: tooltip says "goes on to perfboard" (reach's walkthrough).
    also: str = ""


def rank(entries: Sequence[Entry], typed: str) -> list[Entry]:
    """The entries that match ``typed``, best first (see the module's last paragraph)."""
    needle = typed.strip().casefold()
    if not needle:
        return list(entries)
    # A name whose first word IS what was typed comes before one that merely starts with
    # it: "R1" is R1, not whichever of R10..R19 the document happens to list first.
    exact: list[Entry] = []
    starts: list[Entry] = []
    words: list[Entry] = []
    inside: list[Entry] = []
    described: list[Entry] = []
    for entry in entries:
        name = entry.label.casefold()
        first_word = name.split(maxsplit=1)[0] if name.strip() else ""
        if first_word == needle or name == needle:
            exact.append(entry)
        elif name.startswith(needle):
            starts.append(entry)
        # A hyphen parts words too: "wire" is the start of a word in "Auto-wire".
        elif any(word.startswith(needle) for word in name.replace("…", " ").replace("-", " ").split()):
            words.append(entry)
        elif needle in name or needle in entry.where.casefold():
            inside.append(entry)
        # Last: a word in what it DOES finds it, below everything its name finds.
        elif needle in entry.also.casefold():
            described.append(entry)
    return exact + starts + words + inside + described


#: The row's own data role for what is said after the name: its menu and its key.
ROLE_SAID = Qt.ItemDataRole.UserRole + 1


class _Row(QStyledItemDelegate):
    """A row: the name in the text colour, and its menu and key right-aligned and quieter.
    Painted, because a style sheet cannot colour part of an item's text; the colours are
    read at paint time, so the row follows the theme."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        view = QStyleOptionViewItem(option)
        self.initStyleOption(view, index)
        name = view.text
        view.text = ""
        style = view.widget.style() if view.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, view, painter, view.widget)
        area = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, view, view.widget)
        area = area.adjusted(theme.SPACE["xs"], 0, -theme.SPACE["sm"], 0)
        said = str(index.data(ROLE_SAID) or "")
        painter.save()
        if said:
            painter.setPen(QColor(theme.colour("tertiary")))
            painter.drawText(
                area, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), said
            )
            area = area.adjusted(0, 0, -(view.fontMetrics.horizontalAdvance(said) + theme.SPACE["lg"]), 0)
        painter.setPen(QColor(theme.colour("text")))
        elided = view.fontMetrics.elidedText(name, Qt.TextElideMode.ElideRight, area.width())
        painter.drawText(
            area, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), elided
        )
        painter.restore()


class CommandPalette(QFrame):
    """The field and the list, floating at the top of the window while it is open.

    It goes away the way a palette does, not only the way it came: a click anywhere outside
    it (and the click still lands), Escape or ``SHORTCUT`` with the keyboard anywhere in it,
    or the window losing the foreground. It used to close only on Escape in the field, so a
    click on the board left it standing and Escape from the list did nothing. Those are
    watched through an application-wide event filter that is there only while it is open.
    """

    def __init__(self, parent: QWidget, entries: Callable[[], list[Entry]]) -> None:
        super().__init__(parent)
        self.setObjectName("commandPalette")
        self.setProperty("floating", True)
        theme.elevate(self)
        self._entries_now = entries
        self._entries: list[Entry] = []
        layout = QVBoxLayout(self)
        margin = theme.SPACE["sm"]
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(theme.SPACE["xs"])
        self.field = QLineEdit()
        self.field.setPlaceholderText(t("Type a command, a part or a net…"))
        self.field.textChanged.connect(self._refilter)
        self.field.installEventFilter(self)
        layout.addWidget(self.field)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.setItemDelegate(_Row(self.list))
        self.list.itemActivated.connect(self._run_item)
        self.list.itemClicked.connect(self._run_item)
        layout.addWidget(self.list)
        self.setFixedWidth(WIDTH)
        self._opening: QVariantAnimation | None = None
        self._watching = False
        self.hide()

    # -- opening and closing ---------------------------------------------------

    def open(self, kinds: frozenset[str] | None = None) -> None:
        """Ask for the entries afresh -- the document and what is enabled have moved on since
        last time -- and stand at the top of the window with the field ready. ``kinds``
        narrows it: Go to Part is the palette on the parts alone."""
        self._entries = [
            entry for entry in self._entries_now() if kinds is None or entry.kind in kinds
        ]
        self.field.clear()
        self._refilter("")
        parent = self.parentWidget()
        if parent is not None:
            row = self.list.sizeHintForRow(0) if self.list.count() else 24
            self.list.setFixedHeight(max(row, 24) * VISIBLE_ROWS + 4)
            self.adjustSize()
            self.move(QPoint((parent.width() - self.width()) // 2, theme.SPACE["2xl"] * 3))
        self.show()
        self.raise_()
        self.field.setFocus()
        self._drop_in()

    def toggle(self, kinds: frozenset[str] | None = None) -> None:
        """Close it if it is open, open it if not: what its key does."""
        if self.isHidden():
            self.open(kinds)
        else:
            self.close_palette()

    def _drop_in(self) -> None:
        """Come down the last few pixels into place as the shadow under it deepens: the
        palette arrives over the canvas rather than appearing on it. The field has the
        keyboard from the first frame, so typing never waits on it."""
        self._stop_opening()
        ms = motion.duration(OPEN_MS)
        if ms <= 0:
            return
        landing = self.pos()
        shadow = self.graphicsEffect()
        full = shadow.color().alpha() if isinstance(shadow, QGraphicsDropShadowEffect) else 0
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(ms)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def step(value: object) -> None:
            progress = float(cast(float, value))
            self.move(landing.x(), landing.y() - round(DROP_PX * (1.0 - progress)))
            if isinstance(shadow, QGraphicsDropShadowEffect):
                colour = shadow.color()
                colour.setAlpha(round(full * progress))
                shadow.setColor(colour)

        animation.valueChanged.connect(step)
        animation.finished.connect(self._stop_opening)
        self._opening = animation
        step(0.0)
        animation.start()

    def _stop_opening(self) -> None:
        """Land at once, wherever the drop was: closed mid-way, opened again, or done."""
        animation, self._opening = self._opening, None
        if animation is None:
            return
        animation.stop()
        animation.setCurrentTime(animation.duration())

    def close_palette(self) -> None:
        self._stop_opening()
        # The keyboard goes back to the window only if it was in here: a click outside has
        # already given it to whatever was clicked, and taking it back would undo that.
        focus = QApplication.focusWidget()
        had_focus = focus is not None and (focus is self or self.isAncestorOf(focus))
        covered = self.geometry()
        effect = self.graphicsEffect()
        if effect is not None:
            covered = effect.boundingRectFor(QRectF(self.rect())).toAlignedRect().translated(self.pos())
        self.hide()
        parent = self.parentWidget()
        if parent is None:
            return
        # Painted away NOW, not when the event loop next comes round: what runs from the
        # palette -- an example opening, a plan -- can hold the loop for seconds, and the
        # palette's picture stood over the board all that time as if it had stayed open.
        parent.repaint(covered)
        if had_focus:
            parent.setFocus()

    # Shown and hidden rather than opened and closed: a window closed with the palette up
    # hides it too, and must not leave it listening to the rest of the application.
    def showEvent(self, event: QShowEvent) -> None:
        self._watch(True)
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self._watch(False)
        super().hideEvent(event)

    def _watch(self, on: bool) -> None:
        """Hear every click, key and deactivation in the application while open, and none
        of them once closed."""
        app = QApplication.instance()
        if app is None or on == self._watching:
            return
        if on:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)
        self._watching = on

    def _is_inside(self, watched: QObject) -> bool:
        return isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched))

    def _closes_on(self, watched: QObject, event: QEvent) -> bool:
        """Whether ``event``, on its way to ``watched``, is one the palette closes on."""
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            assert isinstance(event, QMouseEvent)
            # A popup of the palette's own -- the field's right-click menu -- is outside
            # its rectangle and still part of using it.
            if isinstance(watched, QWidget) and watched.window().windowType() == Qt.WindowType.Popup:
                return False
            if isinstance(watched, QWindow) and watched.type() == Qt.WindowType.Popup:
                return False
            at = self.mapFromGlobal(event.globalPosition().toPoint())
            return not self.rect().contains(at)
        if kind == QEvent.Type.WindowDeactivate:
            return watched is self.window()
        return False

    def _overtaken(self, watched: QObject, event: QEvent) -> bool:
        """Whether a sibling has just come to stand over the palette: one made after it
        opened -- a dock's tab bar is made when the panels are laid out again, as on leaving
        Home -- or one raised. Either way the palette goes back on top; it was raised once,
        at opening, and the "Build Guide" tab was painted over its top edge."""
        parent = self.parentWidget()
        if parent is None:
            return False
        kind = event.type()
        if kind == QEvent.Type.ChildAdded and watched is parent:
            assert isinstance(event, QChildEvent)
            child = event.child()
            return child is not self and child.isWidgetType()
        if kind == QEvent.Type.ZOrderChange and watched is not self:
            return isinstance(watched, QWidget) and watched.parentWidget() is parent
        return False

    def _is_closing_key(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key.Key_Escape and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            return True
        pressed = QKeySequence(event.keyCombination())
        return pressed.matches(QKeySequence(SHORTCUT)) == QKeySequence.SequenceMatch.ExactMatch

    # -- the list ----------------------------------------------------------------

    def _refilter(self, typed: str) -> None:
        self.list.clear()
        for entry in rank(self._entries, typed):
            item = QListWidgetItem(entry.label)
            if entry.icon is not None:
                item.setIcon(entry.icon)
            # The menu it lives in and its key, after the name and quieter than it (_Row).
            said = f"{entry.where}  ·  {entry.keys}" if entry.keys else entry.where
            item.setData(ROLE_SAID, said)
            item.setToolTip(said)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def shown(self) -> list[Entry]:
        """The entries listed now, in order."""
        return [
            self.list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.list.count())
        ]

    def run_current(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self._run_item(item)

    def _run_item(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        self.close_palette()
        if isinstance(entry, Entry):
            entry.run()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """The field keeps the keyboard; the arrows move through the list, Enter runs and
        Escape closes. Application-wide while open (``_watch``): a click outside closes it
        and goes on to what was clicked, Escape or ``SHORTCUT`` with the keyboard anywhere
        in it closes it, and so does the window losing the foreground."""
        if self.isHidden():
            return False
        kind = event.type()
        if self._overtaken(watched, event):
            self.raise_()
        if kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress) and self._is_inside(watched):
            assert isinstance(event, QKeyEvent)
            if self._is_closing_key(event):
                if kind == QEvent.Type.ShortcutOverride:
                    # Claimed, so the window's own Escape and Ctrl+K stand aside and the
                    # key comes here as a press.
                    event.accept()
                    return True
                self.close_palette()
                return True
        if self._closes_on(watched, event):
            self.close_palette()
            return False
        if watched is self.field and kind == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.close_palette()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.run_current()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                step = 1 if key == Qt.Key.Key_Down else -1
                row = max(0, min(self.list.count() - 1, self.list.currentRow() + step))
                self.list.setCurrentRow(row)
                return True
        return False
