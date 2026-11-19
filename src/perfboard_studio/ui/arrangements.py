"""The arrangements Rearrange found, as cards over the board: the board as it is first,
then each arrangement, every one wired and counted the same way.

ONE ANSWER WAS NOT ENOUGH. Rearrange used to put one placement in a message box and ask
"Move the Parts?", and the only way to see another was to say no and run it again -- with
the first gone for good. The placer already wires several arrangements to choose between
(``placer.plan_placements``), so the window shows the ones worth seeing side by side and lets
each be looked at on the board itself before anything changes.

A CARD IS PREVIEWED ON THE REAL CANVAS, NOT IN A THUMBNAIL. The thumbnail picks it out; the
board under the strip shows it at full size, with its copper, behind a dashed frame and a
line that says the board has not changed yet. Nothing is dispatched until Apply, so a card
looked at and left costs no undo step.

The strip sits in the Board panel's column, over the view, so it pushes the board down
rather than covering it -- the floating tools stay where they are. It imports nothing of the
window: the window hands it cards and listens to what is picked. See "Placement is arranged
first and annealed second" in docs/ARCHITECTURE.md for where the cards come from.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QMouseEvent, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio.model import ConductorKind
from perfboard_studio.placer import (
    PlacementAlternative,
    PlacementAlternatives,
    WiredAlternative,
)

from . import theme
from .i18n import counted, t

#: The size each card's picture is fitted into, in pixels.
PICTURE_SIZE = QSize(208, 80)

#: The kinds a card counts together. Three words a builder knows rather than six: a
#: reinforced run is still a solder run, a jumper on top is still an insulated wire, and a
#: bent lead is bare wire soldered at its two ends like any other.
#: Each group says its count in words written out at the call, so the catalogue's check
#: reads them.
KIND_GROUPS: tuple[tuple[tuple[ConductorKind, ...], Callable[[int], str]], ...] = (
    (
        ("solder-trace", "solder-trace-wired"),
        lambda n: counted(n, t("{count} solder run"), t("{count} solder runs")),
    ),
    (
        ("insulated-wire", "top-jumper"),
        lambda n: counted(n, t("{count} insulated wire"), t("{count} insulated wires")),
    ),
    (
        ("bare-wire", "lead-bend"),
        lambda n: counted(n, t("{count} bare wire"), t("{count} bare wires")),
    ),
)


#: Arrangements kept on the cards, the board as it is aside. Nine keys pick a card, and a
#: row longer than that is a list nobody compares.
MAX_ARRANGEMENTS = 6


@dataclass(frozen=True, slots=True)
class Offer:
    """What Rearrange found, kept for as long as the board is the one it was found for:
    ``key`` is ``placer.placement_inputs`` of that board, so any edit makes it miss.

    ``alternatives`` is the placer's, ranked -- merged across runs by
    ``placer.merge_alternatives``, which keeps every plan the same object -- and ``wiring``
    is each one's wiring by ``id`` of its plan, None where the search stopped before wiring
    it or the board is not wired this way. Keyed by the plan because a merge renumbers the
    alternatives and keeps the plans."""

    key: object
    alternatives: PlacementAlternatives
    wiring: Mapping[int, WiredAlternative | None]

    @property
    def entries(self) -> tuple[tuple[PlacementAlternative, WiredAlternative | None], ...]:
        """In the order the cards show them: the board as it is first, wherever it ranked,
        because it is what every other card is compared with; then the rest, best first."""
        ranked = self.alternatives.alternatives
        ordered = [a for a in ranked if a.is_baseline] + [a for a in ranked if not a.is_baseline]
        return tuple((a, self.wiring.get(id(a.plan))) for a in ordered)

    @property
    def baseline(self) -> tuple[PlacementAlternative, WiredAlternative | None]:
        return self.entries[0]

    @property
    def candidates(self) -> tuple[tuple[PlacementAlternative, WiredAlternative | None], ...]:
        return self.entries[1:]

    def unwired(self) -> tuple[PlacementAlternative, ...]:
        """The arrangements with no wiring yet, in rank order."""
        return tuple(
            a for a in self.alternatives.alternatives if self.wiring.get(id(a.plan)) is None
        )


@dataclass(frozen=True, slots=True)
class Card:
    """What one card shows: made by the window (``MainWindow._show_arrangements``), drawn
    by :class:`ArrangementCard`."""

    title: str
    recommended: bool
    is_baseline: bool
    picture: QPixmap
    #: Lines under the title, each with the role its colour says.
    lines: tuple[tuple[str, theme.Role], ...]
    #: What moves where, for the pointer resting on the card.
    detail: str = ""


def wiring_line(wired: WiredAlternative) -> str:
    """"3 solder runs · 6 insulated wires", from the counts the placer made."""
    by_kind = dict(wired.conductors_by_kind)
    said = []
    for kinds, say_count in KIND_GROUPS:
        count = sum(by_kind.get(kind, 0) for kind in kinds)
        if count:
            said.append(say_count(count))
    return " · ".join(said) if said else t("No wiring")


def card_lines(
    alternative: PlacementAlternative, wired: WiredAlternative | None, *, wires_cards: bool
) -> tuple[tuple[str, theme.Role], ...]:
    """Connections made, the wiring by kind, what moves, and what cannot be built --
    the same four facts on every card, so two cards are read by comparing lines.

    ``wires_cards`` is False on a board whose copper is cut rather than laid, where the
    cards are compared by the placer alone and the board is wired after one is chosen."""
    lines: list[tuple[str, theme.Role]] = []
    if wired is None:
        lines.append(
            (
                t("Not wired: the search was stopped first")
                if wires_cards
                else t("Wired after you choose it"),
                "tertiary",
            )
        )
    elif wired.stats.unrouted:
        lines.append(
            (
                counted(
                    wired.stats.unrouted,
                    t("{count} connection not made"),
                    t("{count} connections not made"),
                ),
                "danger",
            )
        )
    else:
        lines.append((t("Every connection made"), "success"))
    if wired is not None:
        lines.append((wiring_line(wired), "secondary"))
    if alternative.is_baseline:
        lines.append((t("Parts stay where they are"), "secondary"))
    else:
        lines.append(
            (counted(alternative.moved, t("{count} part moves"), t("{count} parts move")), "secondary")
        )
    warnings = alternative.plan.after.physical_warnings
    if warnings:
        lines.append(
            (
                counted(warnings, t("{count} part hard to build"), t("{count} parts hard to build")),
                "warning",
            )
        )
    return tuple(lines)


class ArrangementCard(QFrame):
    """One arrangement: its picture, its name and its four lines. A click picks it."""

    clicked = Signal()

    def __init__(self, card: Card, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("arrangementCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(PICTURE_SIZE.width() + 24)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 8)
        column.setSpacing(3)
        picture = QLabel(self)
        picture.setPixmap(card.picture)
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        picture.setFixedHeight(PICTURE_SIZE.height())
        column.addWidget(picture)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = QLabel(card.title, self)
        self.title.setObjectName("arrangementTitle")
        head.addWidget(self.title)
        if card.recommended:
            badge = QLabel(t("Recommended"), self)
            badge.setObjectName("arrangementBadge")
            head.addWidget(badge)
        head.addStretch(1)
        column.addLayout(head)
        self.lines: list[QLabel] = []
        for text, role in card.lines:
            line = QLabel(text, self)
            line.setWordWrap(True)
            theme.tone(line, role)
            column.addWidget(line)
            self.lines.append(line)
        column.addStretch(1)
        self.set_current(False)

    def set_current(self, current: bool) -> None:
        self.setProperty("current", "true" if current else "false")
        theme.restyle(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class ArrangementStrip(QFrame):
    """The cards in a row, a line saying what is on the board below, and the way out.

    ``picked`` carries a card's index; the window decides what that shows. Apply, Try Other
    Arrangements and Close are requests too: the strip holds no document."""

    picked = Signal(int)
    apply_requested = Signal()
    more_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("arrangements")
        # Never taller than what is in it: the height it does not take is the board's.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.cards: list[ArrangementCard] = []
        #: Where the board as it is stands among the cards; Back picks it.
        self.baseline_index = 0
        self._current = -1
        self._keys: list[QShortcut] = []
        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 8)
        column.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        heading = QLabel(t("Arrangements"), self)
        heading.setObjectName("arrangementsHeading")
        top.addWidget(heading)
        self.hint = QLabel(self)
        theme.tone(self.hint, "secondary")
        top.addWidget(self.hint, 1)
        self.more = QPushButton(t("Try Other Arrangements"), self)
        self.more.setToolTip(
            t(
                "Search again from another starting point and add what it finds to these "
                "cards. Nothing found before is lost."
            )
        )
        self.more.clicked.connect(self.more_requested.emit)
        top.addWidget(self.more)
        self.close_button = QPushButton(t("Close"), self)
        self.close_button.setToolTip(
            t("Put the cards away and keep the board as it is. Rearrange brings them back.")
        )
        self.close_button.clicked.connect(self.close_requested.emit)
        top.addWidget(self.close_button)
        column.addLayout(top)

        self.cards_scroll = QScrollArea(self)
        self.cards_scroll.setObjectName("arrangementsScroll")
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.row_host = QWidget()
        self.row_host.setProperty("clear", "true")
        self.row = QHBoxLayout(self.row_host)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)
        self.row.addStretch(1)
        self.cards_scroll.setWidget(self.row_host)
        column.addWidget(self.cards_scroll)

        self.banner = QFrame(self)
        self.banner.setObjectName("arrangementBanner")
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(12, 4, 6, 4)
        banner_row.setSpacing(8)
        self.banner_text = QLabel(self.banner)
        self.banner_text.setWordWrap(True)
        banner_row.addWidget(self.banner_text, 1)
        self.back = QPushButton(t("Back to Your Board"), self.banner)
        self.back.setToolTip(t("Show the board as it is again (Esc)."))
        self.back.clicked.connect(lambda: self.picked.emit(self.baseline_index))
        banner_row.addWidget(self.back)
        self.apply = QPushButton(t("Apply This Arrangement"), self.banner)
        theme.variant(self.apply, "primary")
        self.apply.clicked.connect(self.apply_requested.emit)
        banner_row.addWidget(self.apply)
        column.addWidget(self.banner)

    # -- filling ---------------------------------------------------------------------

    def set_cards(self, cards: Sequence[Card]) -> None:
        """Show ``cards`` in order, none of them current yet."""
        for old in self.cards:
            self.row.removeWidget(old)
            old.deleteLater()
        self.cards = []
        for index, card in enumerate(cards):
            widget = ArrangementCard(card, self.row_host)
            widget.clicked.connect(lambda i=index: self.picked.emit(i))
            key = t("Show it on the board ({key}).").format(key=index + 1) if index < 9 else ""
            widget.setToolTip("\n\n".join(part for part in (key, card.detail) if part))
            self.row.insertWidget(index, widget)
            self.cards.append(widget)
            if card.is_baseline:
                self.baseline_index = index
        self._current = -1
        shown = min(len(cards), 9)
        self.hint.setText(
            t("Each one was wired and compared. Click one to see it on the board (1–{last}).").format(
                last=shown
            )
        )
        # Tall enough for the cards, never taller: the board under the strip is the point.
        self.cards_scroll.setFixedHeight(
            max((shown.sizeHint().height() for shown in self.cards), default=0)
            + self.cards_scroll.horizontalScrollBar().sizeHint().height()
        )

    def set_current(self, index: int, banner: str, can_apply: bool) -> None:
        """Mark card ``index`` as the one on the board, and say so in the banner. On the
        board as it is, the banner has nothing to apply and nothing to go back from."""
        self._current = index
        for position, card in enumerate(self.cards):
            card.set_current(position == index)
        if 0 <= index < len(self.cards):
            self.cards_scroll.ensureWidgetVisible(self.cards[index])
        self.banner_text.setText(banner)
        previewing = index != self.baseline_index
        self.banner.setProperty("preview", "true" if previewing else "false")
        theme.restyle(self.banner)
        self.back.setVisible(previewing)
        self.apply.setVisible(previewing)
        self.apply.setEnabled(previewing and can_apply)

    @property
    def current(self) -> int:
        return self._current

    def install_keys(self, host: QWidget) -> None:
        """1 to 9 pick a card while the keyboard is anywhere in ``host`` -- the Board panel,
        never a text field elsewhere, where a digit is a digit."""
        for number in range(1, 10):
            key = QShortcut(QKeySequence(str(number)), host)
            key.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            key.activated.connect(lambda i=number - 1: self._key(i))
            self._keys.append(key)

    def _key(self, index: int) -> None:
        if self.isVisible() and index < len(self.cards):
            self.picked.emit(index)
