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

SAID WHERE IT IS, NOT DUMPED. It was the whole menu tree in one list, and nothing in it said
where anything was. With nothing typed it is now a few sections -- the commands last run
from it, the files last opened, what the step bar's current step suggests -- and then each
menu as its own section; with something typed, what matches grouped by what it is
(``sections``), each group under a header, the group holding the best match first. Each row
has its icon on a tile, its menu path quieter beside its name and its key as keycaps; a
footer says which keys move, run and close.
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
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QHideEvent,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QShowEvent,
    QWindow,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import icons, motion, theme
from .i18n import t

#: How many rows the list shows before it scrolls, and how wide the palette stands.
VISIBLE_ROWS = 10
WIDTH = 680

#: The QAction property saying what an entry is when it is not a command: "example" for
#: an entry of Open Example, "file" for one of Open Recent. Grouped and iconned by it.
KIND = "paletteKind"

#: Between the menus in an entry's path: "File ▸ Export".
PATH_SEP = " \u25b8 "

#: How many of the commands last run from the palette it offers first.
RECENT_LIMIT = 5

#: Kinds that give way to a command, a part or a net matching as well (``rank``).
LATER_KINDS = {"example": 1, "file": 2}

#: The icon a row shows when its command has none of its own.
FALLBACK_ICONS = {
    "command": "more",
    "part": "sch-place",
    "net": "new-net",
    "example": "board",
    "file": "open",
}

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
    #: What it is remembered by among the commands last run (``recent``): its menu path and
    #: its name. Empty for what is not remembered -- a part, a net, a file.
    key: str = ""
    #: Offered under the step bar's current step, at the top of the empty palette.
    suggested: bool = False


def group_title(kind: str) -> str:
    """A group's header: what its entries are."""
    return {
        "command": t("Commands"),
        "part": t("Parts"),
        "net": t("Nets"),
        "example": t("Examples"),
        "file": t("Recent Files"),
    }.get(kind, t("Commands"))


def sections(
    entries: Sequence[Entry],
    typed: str,
    *,
    recent: Sequence[str] = (),
    suggested_title: str = "",
) -> list[tuple[str, list[Entry]]]:
    """What the palette lists, as (header, entries) in order.

    Typed: what matches, grouped by kind, the groups in the order of their best match -- so
    "R1" puts the parts first and "wire" the commands -- and ``rank``'s order inside each.
    Nothing typed: the commands last run (``recent``, newest first), the files last opened,
    what the current step suggests, each menu as its own section, then the examples, the
    parts and the nets. A section with nothing in it is left out.
    """
    if typed.strip():
        groups: dict[str, list[Entry]] = {}
        for entry in rank(entries, typed):
            groups.setdefault(entry.kind, []).append(entry)
        return [(group_title(kind), found) for kind, found in groups.items()]
    commands = [entry for entry in entries if entry.kind == "command"]
    remembered = {entry.key: entry for entry in commands if entry.key}
    listed: list[tuple[str, list[Entry]]] = [
        (t("Recent Commands"), [remembered[key] for key in recent if key in remembered][:RECENT_LIMIT]),
        (t("Recent Files"), [entry for entry in entries if entry.kind == "file"]),
        (suggested_title or t("Suggested"), [entry for entry in commands if entry.suggested]),
    ]
    menus: dict[str, list[Entry]] = {}
    for entry in commands:
        menus.setdefault(entry.where.split(PATH_SEP)[0], []).append(entry)
    listed.extend(menus.items())
    for kind in ("example", "part", "net"):
        listed.append((group_title(kind), [entry for entry in entries if entry.kind == kind]))
    return [(title, found) for title, found in listed if found]


def keycaps(keys: str) -> list[str]:
    """A shortcut as the keys pressed: "Ctrl+Shift+R" is Ctrl, Shift, R and "Ctrl++" is
    Ctrl, +. Only the first of several; a macOS "⌘R" stays one cap, as it is said."""
    first = keys.split(", ")[0].strip()
    if not first:
        return []
    caps: list[str] = []
    for part in first.replace("++", "+\0").split("+"):
        if part:
            caps.append("+" if part == "\0" else part)
    return caps


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
    # Inside a rank, a command before an example or a file the menus happen to list first:
    # "r" is Rotate and Redo before relay-and-supply.
    return [
        entry
        for found in (exact, starts, words, inside, described)
        for entry in sorted(found, key=lambda each: LATER_KINDS.get(each.kind, 0))
    ]


#: The row's own data roles: what is said after the name, and whether it is a header.
ROLE_SAID = Qt.ItemDataRole.UserRole + 1
ROLE_HEADER = Qt.ItemDataRole.UserRole + 2
ROLE_KEYS = Qt.ItemDataRole.UserRole + 3

#: Heights, in pixels: a row, a section's header, and the first header (no gap above it).
ROW_PX = 36
HEADER_PX = 30
TILE_PX = 24
CAP_PX = 18


def _cap_width(metrics: QFontMetrics, cap: str) -> int:
    return max(CAP_PX, metrics.horizontalAdvance(cap) + 10)


def _draw_cap(painter: QPainter, x: int, middle: int, cap: str) -> int:
    """One keycap with its left edge at ``x``; returns its right edge. The colours are the
    theme's as it is NOW, so a cap follows a theme switched while the window is open."""
    k = theme.ACTIVE
    width = _cap_width(painter.fontMetrics(), cap)
    box = QRectF(x, middle - CAP_PX / 2, width, CAP_PX)
    outline = QPainterPath()
    outline.addRoundedRect(box, theme.RADIUS_SM, theme.RADIUS_SM)
    painter.fillPath(outline, QColor(k.bg_subtle))
    painter.setPen(QPen(QColor(k.border_strong), 1))
    painter.drawPath(outline)
    # The key's lower edge, a little heavier: it reads as a key, not as a tag.
    painter.drawLine(int(box.left()) + 3, int(box.bottom()), int(box.right()) - 3, int(box.bottom()))
    painter.setPen(QColor(theme.colour("secondary", theme.ACTIVE)))
    painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), cap)
    return x + width


def _small(base: QFont, px: int, weight: QFont.Weight | None = None) -> QFont:
    font = QFont(base)
    font.setPixelSize(px)
    if weight is not None:
        font.setWeight(weight)
    return font


class _Row(QStyledItemDelegate):
    """A header, or a row: its icon on a tile, the name, its menu path quieter beside it and
    its key as keycaps at the right. Painted whole, because a style sheet cannot colour part
    of an item's text; every colour is read at paint time, so a row follows the theme."""

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        # No width of its own: a row is as wide as the list shows, scrollbar or not, so its
        # keycaps are never under the scrollbar and there is nothing to scroll sideways.
        if index.data(ROLE_HEADER):
            return QSize(1, HEADER_PX if index.row() else HEADER_PX - theme.SPACE["md"])
        return QSize(1, ROW_PX)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        k = theme.ACTIVE
        area = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if index.data(ROLE_HEADER):
            painter.setFont(_small(option.font, theme.CAPTION_PX, QFont.Weight.DemiBold))
            painter.setPen(QColor(theme.colour("tertiary", theme.ACTIVE)))
            painter.drawText(
                area.adjusted(theme.SPACE["lg"], 0, -theme.SPACE["lg"], -theme.SPACE["2xs"]),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
                str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
            )
            painter.restore()
            return
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        band = QRectF(area.adjusted(theme.SPACE["xs"], 1, -theme.SPACE["xs"], -1))
        if selected or hovered:
            shape = QPainterPath()
            shape.addRoundedRect(band, theme.RADIUS_MD, theme.RADIUS_MD)
            painter.fillPath(shape, QColor(k.accent_subtle if selected else k.bg_hover))
        middle = area.center().y()
        x = area.left() + theme.SPACE["lg"]
        tile = QRectF(x, middle - TILE_PX / 2, TILE_PX, TILE_PX)
        tile_shape = QPainterPath()
        tile_shape.addRoundedRect(tile, theme.RADIUS_MD, theme.RADIUS_MD)
        painter.fillPath(tile_shape, QColor(k.bg_raised if selected else k.bg_hover))
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            icon.paint(painter, tile.adjusted(5, 5, -5, -5).toRect())
        x += TILE_PX + theme.SPACE["md"] + 2
        right = area.right() - theme.SPACE["lg"]
        caps = keycaps(str(index.data(ROLE_KEYS) or ""))
        if caps:
            painter.setFont(_small(option.font, theme.CAPTION_PX - 1))
            metrics = painter.fontMetrics()
            width = sum(_cap_width(metrics, cap) for cap in caps) + theme.SPACE["xs"] * (len(caps) - 1)
            at = right - width
            for cap in caps:
                at = _draw_cap(painter, at, middle, cap) + theme.SPACE["xs"]
            right -= width + theme.SPACE["md"]
        room = max(0, right - x)
        painter.setFont(_small(option.font, theme.LEAD_PX))
        metrics = painter.fontMetrics()
        name = metrics.elidedText(
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""), Qt.TextElideMode.ElideRight, room
        )
        painter.setPen(QColor(theme.colour("text", theme.ACTIVE)))
        text_box = QRect(x, area.top(), room, area.height())
        painter.drawText(text_box, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)
        said = str(index.data(ROLE_SAID) or "")
        gap = metrics.horizontalAdvance(name) + theme.SPACE["md"] + 2
        if said and gap < room:
            painter.setFont(_small(option.font, theme.FONT_PX))
            quiet = painter.fontMetrics().elidedText(said, Qt.TextElideMode.ElideRight, room - gap)
            painter.setPen(QColor(theme.colour("tertiary", theme.ACTIVE)))
            painter.drawText(
                QRect(x + gap, area.top(), room - gap, area.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                quiet,
            )
        painter.restore()


class _Footer(QWidget):
    """Under the list: which keys move, run and close, and Run with its key at the right.
    Painted, so its colours are the theme's as it is when it is drawn."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(32)

    def paintEvent(self, event: QPaintEvent) -> None:
        k = theme.ACTIVE
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect())
        radius = theme.RADIUS_LG - 1
        shape = QPainterPath()
        shape.moveTo(area.topLeft())
        shape.lineTo(area.topRight())
        shape.lineTo(area.right(), area.bottom() - radius)
        shape.quadTo(area.bottomRight(), QPoint(int(area.right() - radius), int(area.bottom())))
        shape.lineTo(area.left() + radius, area.bottom())
        shape.quadTo(area.bottomLeft(), QPoint(int(area.left()), int(area.bottom() - radius)))
        shape.closeSubpath()
        painter.fillPath(shape, QColor(k.bg_subtle))
        painter.setPen(QPen(QColor(k.border), 1))
        painter.drawLine(int(area.left()), 0, int(area.right()), 0)
        middle = self.height() // 2
        caption = _small(self.font(), theme.CAPTION_PX)
        x = theme.SPACE["lg"]
        for cap, words in (("\u2191\u2193", t("to move")), ("\u21b5", t("to run")), ("Esc", t("to close"))):
            painter.setFont(_small(self.font(), theme.CAPTION_PX - 1))
            x = _draw_cap(painter, x, middle, cap) + theme.SPACE["sm"]
            painter.setFont(caption)
            painter.setPen(QColor(theme.colour("tertiary", theme.ACTIVE)))
            width = painter.fontMetrics().horizontalAdvance(words)
            painter.drawText(QRect(x, 0, width + 2, self.height()), int(Qt.AlignmentFlag.AlignVCenter), words)
            x += width + theme.SPACE["lg"] + theme.SPACE["xs"]
        painter.setFont(_small(self.font(), theme.CAPTION_PX - 1))
        cap_left = self.width() - theme.SPACE["lg"] - _cap_width(painter.fontMetrics(), "\u21b5")
        _draw_cap(painter, cap_left, middle, "\u21b5")
        painter.setFont(_small(self.font(), theme.CAPTION_PX, QFont.Weight.DemiBold))
        painter.setPen(QColor(theme.colour("text", theme.ACTIVE)))
        run = t("Run")
        width = painter.fontMetrics().horizontalAdvance(run)
        painter.drawText(
            QRect(cap_left - theme.SPACE["sm"] - width, 0, width + 2, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter),
            run,
        )
        painter.end()


class CommandPalette(QFrame):
    """The field and the list, floating at the top of the window while it is open.

    It goes away the way a palette does, not only the way it came: a click anywhere outside
    it (and the click still lands), Escape or ``SHORTCUT`` with the keyboard anywhere in it,
    or the window losing the foreground. It used to close only on Escape in the field, so a
    click on the board left it standing and Escape from the list did nothing. Those are
    watched through an application-wide event filter that is there only while it is open.
    """

    def __init__(
        self,
        parent: QWidget,
        entries: Callable[[], list[Entry]],
        *,
        recent: Callable[[], list[str]] | None = None,
        remember: Callable[[str], None] | None = None,
        suggested_title: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("commandPalette")
        self.setProperty("floating", True)
        theme.elevate(self)
        self._entries_now = entries
        self._recent_now = recent
        self._remember = remember
        self._suggested_title_now = suggested_title
        self._entries: list[Entry] = []
        self._recent: list[str] = []
        self._suggested_title = ""
        layout = QVBoxLayout(self)
        # One pixel in from the border, so the footer's fill meets it.
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(theme.SPACE["lg"] + 2, theme.SPACE["xs"], theme.SPACE["md"], theme.SPACE["xs"])
        top.setSpacing(theme.SPACE["xs"])
        self.magnifier = QLabel()
        self.magnifier.setPixmap(icons.icon("search").pixmap(18, 18))
        top.addWidget(self.magnifier)
        self.field = QLineEdit()
        self.field.setPlaceholderText(t("Type a command, a part or a net…"))
        self.field.textChanged.connect(self._refilter)
        self.field.installEventFilter(self)
        top.addWidget(self.field, 1)
        layout.addLayout(top)
        self.list = QListWidget()
        self.list.setItemDelegate(_Row(self.list))
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemActivated.connect(self._run_item)
        self.list.itemClicked.connect(self._run_item)
        layout.addWidget(self.list)
        self.footer = _Footer(self)
        layout.addWidget(self.footer)
        self.setFixedWidth(WIDTH)
        self._opening: QVariantAnimation | None = None
        self._watching = False
        self.hide()

    def paintEvent(self, event: QPaintEvent) -> None:
        """The frame as the theme draws it, and a hairline between the field and the list."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(QColor(theme.ACTIVE.border), 1))
        y = self.list.geometry().top() - 1
        painter.drawLine(1, y, self.width() - 2, y)
        painter.end()

    # -- opening and closing ---------------------------------------------------

    def open(self, kinds: frozenset[str] | None = None) -> None:
        """Ask for the entries afresh -- the document and what is enabled have moved on since
        last time -- and stand at the top of the window with the field ready. ``kinds``
        narrows it: Go to Part is the palette on the parts alone."""
        self._entries = [
            entry for entry in self._entries_now() if kinds is None or entry.kind in kinds
        ]
        self._recent = list(self._recent_now()) if self._recent_now is not None else []
        self._suggested_title = (
            self._suggested_title_now() if self._suggested_title_now is not None else ""
        )
        self.field.clear()
        self._refilter("")
        parent = self.parentWidget()
        if parent is not None:
            self.list.setFixedHeight(ROW_PX * VISIBLE_ROWS + 8)
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
        # The keyboard goes back to the window only if it was in here. On a click outside
        # it was, and still is (this runs before the press is delivered): the window takes it
        # here and the clicked widget takes it from the window as the press arrives.
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
        for title, found in sections(
            self._entries, typed, recent=self._recent, suggested_title=self._suggested_title
        ):
            header = QListWidgetItem(title)
            header.setData(ROLE_HEADER, True)
            # Not a row: the arrows step over it and a click on it runs nothing.
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(header)
            for entry in found:
                item = QListWidgetItem(entry.label)
                icon = entry.icon
                if icon is None or icon.isNull():
                    icon = icons.icon(FALLBACK_ICONS.get(entry.kind, "more"))
                item.setIcon(icon)
                # The menu it lives in, after the name and quieter than it; the key apart,
                # as keycaps (_Row).
                item.setData(ROLE_SAID, entry.where)
                item.setData(ROLE_KEYS, entry.keys)
                item.setToolTip(f"{entry.where}  ·  {entry.keys}" if entry.keys else entry.where)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self.list.addItem(item)
        self.list.scrollToTop()
        self._step_to(0, 1)

    def _is_row(self, row: int) -> bool:
        item = self.list.item(row)
        return item is not None and isinstance(item.data(Qt.ItemDataRole.UserRole), Entry)

    def _step_to(self, row: int, step: int) -> None:
        """Make the first row from ``row`` on, going ``step``, the current one -- a header
        is passed over. Nothing if there is none that way."""
        while 0 <= row < self.list.count():
            if self._is_row(row):
                self.list.setCurrentRow(row)
                return
            row += step

    def shown(self) -> list[Entry]:
        """The entries listed now, in order, without the headers."""
        return [
            self.list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.list.count())
            if self._is_row(row)
        ]

    def headers(self) -> list[str]:
        """The section headers listed now, in order."""
        return [
            self.list.item(row).text()
            for row in range(self.list.count())
            if self.list.item(row).data(ROLE_HEADER)
        ]

    def run_current(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self._run_item(item)

    def _run_item(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, Entry):
            return
        if entry.key and self._remember is not None:
            self._remember(entry.key)
        self.close_palette()
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
                self._step_to(self.list.currentRow() + step, step)
                return True
        return False
