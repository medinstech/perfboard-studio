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

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, QPoint, Qt
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .i18n import t

#: How many rows the list shows before it scrolls, and how wide the palette stands.
VISIBLE_ROWS = 10
WIDTH = 620


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
    return exact + starts + words + inside


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
    """The field and the list, floating at the top of the window while it is open."""

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

    def close_palette(self) -> None:
        self.hide()
        parent = self.parentWidget()
        if parent is not None:
            parent.setFocus()

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
        Escape closes."""
        if watched is self.field and event.type() == QEvent.Type.KeyPress:
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
