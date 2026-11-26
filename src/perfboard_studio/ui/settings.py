"""Settings: every preference of the window in one place, with a search (Ctrl+,).

NOT A SECOND COPY OF THE PREFERENCES. Each row drives the ``QAction`` the menus, the
board's Show button and the header's sun and moon already drive, and listens to it -- so
whichever door a preference is changed through, every other door shows it at once, and
the code that applies and remembers it stays exactly where it was. A row that kept its own
state would be a fourth opinion about the theme, and the first time two of them disagreed
nobody could say which one the window was using.

WHY THERE IS ONE. Twelve preferences lived in four menus -- View held the theme, the
language, Reduce Motion, the board's colour and the wheel between the zoom and the panels
-- and somebody who used the application every day did not know Reduce Motion existed.
A menu is a list of verbs; a setting needs a sentence saying what it does, and room for a
search that finds it by the words a person remembers ("tekerlek", "wheel").

What is shown is decided by data (``Row``): the window says which rows exist, in which
category, with which action, and this module only lays them out and keeps them in step.
The rows are asked for again every time the window opens, so a row that exists only
sometimes (a hidden update) is simply there or not.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from perfboard_studio.ui import icons, motion, theme
from perfboard_studio.ui.i18n import t

SHORTCUT = "Ctrl+,"
#: Where the results of a search are shown: not a category, and never in the list.
RESULTS = "results"
SIDEBAR_PX = 240
SWITCH_W, SWITCH_H = 36, 20
SWATCH_PX = 24


# -- what the window says exists ---------------------------------------------------------


@dataclass(frozen=True)
class Category:
    key: str
    icon: str
    title: str
    #: One sentence under the page's title: what the page is about, and where it is kept.
    about: str


@dataclass(frozen=True)
class Toggle:
    """On or off: a checkable action."""

    action: QAction


@dataclass(frozen=True)
class Choice:
    """One of several: checkable actions of which the window keeps exactly one checked.
    Shown as a segmented control when the choices are short, a drop-down when not."""

    actions: Mapping[str, QAction]
    segmented: bool = False


@dataclass(frozen=True)
class Swatches:
    """One of several colours: ``colours`` gives each key its fill, and a key it does not
    name is "as the board says" -- drawn as an empty dot with a stroke through it."""

    actions: Mapping[str, QAction]
    colours: Mapping[str, str]


@dataclass(frozen=True)
class Button:
    """Something done rather than chosen. The rows are asked for again afterwards."""

    label: str
    run: Callable[[], None]


Control = Toggle | Choice | Swatches | Button


@dataclass(frozen=True)
class Row:
    category: str
    title: str
    #: One line: what it does, in the words of somebody who has not read the manual.
    why: str
    control: Control
    #: More words to be found by: the English title, the names it used to have.
    words: str = ""
    #: A short tag beside the title ("At next start"), or one worked out as it is shown.
    chip: str | Callable[[], str] = ""


def plain(text: str) -> str:
    """An action's text without its access-key ampersands."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def fold(text: str) -> str:
    """Text as a search compares it: no case, no accents, and Turkish's dotted and dotless
    i as one letter -- somebody typing "gorunum" on an English keyboard means Görünüm, and
    "ışık" and "isik" are one word to anybody who is not a spelling checker."""
    text = text.replace("İ", "i").replace("I", "i").replace("ı", "i")
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def chip_of(row: Row) -> str:
    return row.chip() if callable(row.chip) else row.chip


def matches(rows: Sequence[Row], categories: Sequence[Category], text: str) -> list[Row]:
    """The rows every word of ``text`` is found in -- title, sentence, the extra words, or
    the category's name -- in the order the pages list them."""
    words = fold(text).split()
    if not words:
        return []
    titles = {c.key: c.title for c in categories}
    order = {c.key: i for i, c in enumerate(categories)}
    found = []
    for row in rows:
        haystack = fold(" ".join((row.title, row.why, row.words, titles.get(row.category, ""))))
        if all(word in haystack for word in words):
            found.append(row)
    return sorted(found, key=lambda r: order.get(r.category, len(order)))


def section(menu: QMenu, title: str) -> QWidgetAction:
    """A quiet heading inside a menu, over the items it names.

    ``QMenu.addSection`` draws nothing under Fusion, which is what the application is
    drawn with. A disabled widget action is a heading the keyboard and the pointer pass
    over, and it has no text, so nothing that walks the menus for commands -- the
    palette, the shortcut card -- mistakes it for one.
    """
    label = QLabel(title.upper())
    label.setObjectName("menuSection")
    action = QWidgetAction(menu)
    action.setDefaultWidget(label)
    action.setEnabled(False)
    menu.addAction(action)
    return action


# -- the controls ------------------------------------------------------------------------


class Switch(QAbstractButton):
    """An on/off switch, drawn from the tokens as it is painted -- so a theme switched
    while the window is open is the switch's new colour on the next frame."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(SWITCH_W + 4, SWITCH_H + 4)
        self._at = 0.0
        self._slide = QVariantAnimation(self)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.valueChanged.connect(self._moved)
        self.toggled.connect(self._toggled)

    def sizeHint(self) -> QSize:
        return QSize(SWITCH_W + 4, SWITCH_H + 4)

    def setChecked(self, on: bool) -> None:
        """Set from the action without sliding: a state the window already had is not news."""
        if on == self.isChecked():
            return
        self.blockSignals(True)
        super().setChecked(on)
        self.blockSignals(False)
        self._slide.stop()
        self._at = 1.0 if on else 0.0
        self.update()

    def _toggled(self, on: bool) -> None:
        end = 1.0 if on else 0.0
        ms = motion.duration(140)
        if ms <= 0:
            self._at = end
            self.update()
            return
        self._slide.stop()
        self._slide.setDuration(ms)
        self._slide.setStartValue(self._at)
        self._slide.setEndValue(end)
        self._slide.start()

    def _moved(self, value: object) -> None:
        self._at = float(value)  # type: ignore[arg-type]
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        k = theme.ACTIVE
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(2, 2, SWITCH_W, SWITCH_H)
        if self.hasFocus():
            p.setPen(QPen(QColor(k.accent), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(-1.5, -1.5, 1.5, 1.5), 11.5, 11.5)
        off, on = QColor(k.border_strong), QColor(k.accent)
        mix = QColor.fromRgbF(
            off.redF() + (on.redF() - off.redF()) * self._at,
            off.greenF() + (on.greenF() - off.greenF()) * self._at,
            off.blueF() + (on.blueF() - off.blueF()) * self._at,
        )
        if not self.isEnabled():
            mix.setAlphaF(0.45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix)
        p.drawRoundedRect(track, SWITCH_H / 2, SWITCH_H / 2)
        knob = SWITCH_H - 4
        x = track.left() + 2 + (SWITCH_W - knob - 4) * self._at
        p.setBrush(QColor(k.text_on_accent))
        p.drawEllipse(QRectF(x, track.top() + 2, knob, knob))
        p.end()


class Segments(QFrame):
    """A few short choices side by side, one pressed."""

    def __init__(self, choice: Choice, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsSegments")
        self._choice = choice
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, action in choice.actions.items():
            button = QPushButton(plain(action.text()))
            button.setObjectName("settingsSegment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(button)
            layout.addWidget(button)
            self._buttons[key] = button
            button.clicked.connect(lambda _checked=False, a=action: _choose(a))
            action.toggled.connect(self.sync)
        self.sync()

    def sync(self, *_: object) -> None:
        for key, action in self._choice.actions.items():
            self._buttons[key].setChecked(action.isChecked())


class Dropdown(QComboBox):
    """One of several longer choices."""

    def __init__(self, choice: Choice, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsDropdown")
        self._choice = choice
        for key, action in choice.actions.items():
            self.addItem(plain(action.text()), key)
            self.setItemData(self.count() - 1, action.toolTip(), Qt.ItemDataRole.ToolTipRole)
            action.toggled.connect(self.sync)
        self.activated.connect(self._picked)
        self.sync()

    def _picked(self, index: int) -> None:
        _choose(self._choice.actions[str(self.itemData(index))])

    def sync(self, *_: object) -> None:
        for index in range(self.count()):
            if self._choice.actions[str(self.itemData(index))].isChecked():
                self.blockSignals(True)
                self.setCurrentIndex(index)
                self.blockSignals(False)
                return


class Swatch(QAbstractButton):
    """One colour to pick, ringed when it is the one chosen."""

    def __init__(self, fill: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fill = fill
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(SWATCH_PX + 6, SWATCH_PX + 6)

    def sizeHint(self) -> QSize:
        return QSize(SWATCH_PX + 6, SWATCH_PX + 6)

    def paintEvent(self, event: QPaintEvent) -> None:
        k = theme.ACTIVE
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dot = QRectF(3, 3, SWATCH_PX, SWATCH_PX)
        if self.isChecked() or self.hasFocus():
            p.setPen(QPen(QColor(k.accent), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(dot.adjusted(-2, -2, 2, 2))
        path = QPainterPath()
        path.addEllipse(dot.adjusted(1.5, 1.5, -1.5, -1.5))
        p.fillPath(path, QColor(self._fill or k.bg_subtle))
        p.setPen(QPen(QColor(k.border_strong), 1))
        p.drawPath(path)
        if self._fill is None:
            p.setPen(QPen(QColor(k.text_secondary), 1.4))
            p.drawLine(QPointF(dot.left() + 6, dot.bottom() - 6), QPointF(dot.right() - 6, dot.top() + 6))
        p.end()


class SwatchRow(QWidget):
    def __init__(self, swatches: Swatches, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._swatches = swatches
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._dots: dict[str, Swatch] = {}
        for key, action in swatches.actions.items():
            dot = Swatch(swatches.colours.get(key))
            dot.setToolTip(plain(action.text()))
            dot.setAccessibleName(plain(action.text()))
            dot.clicked.connect(lambda _checked=False, a=action: _choose(a))
            action.toggled.connect(self.sync)
            layout.addWidget(dot)
            self._dots[key] = dot
        self.sync()

    def sync(self, *_: object) -> None:
        for key, action in self._swatches.actions.items():
            self._dots[key].setChecked(action.isChecked())


class ToggleSwitch(Switch):
    """A switch bound to a checkable action, both ways."""

    def __init__(self, action: QAction, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._action = action
        self.setChecked(action.isChecked())
        self.setEnabled(action.isEnabled())
        self.clicked.connect(self._clicked)
        action.toggled.connect(self.setChecked)
        action.changed.connect(self.sync)

    def _clicked(self) -> None:
        if self.isChecked() != self._action.isChecked():
            self._action.trigger()
        # A handler that refused leaves the action as it was; so does the switch.
        self.setChecked(self._action.isChecked())

    def sync(self) -> None:
        self.setEnabled(self._action.isEnabled())
        self.setChecked(self._action.isChecked())


def _choose(action: QAction) -> None:
    """Pick one of a choice's actions the way its menu item would -- once. Triggering the
    one already checked would uncheck it before its handler checked it again."""
    if not action.isChecked():
        action.trigger()


# -- the window --------------------------------------------------------------------------


class SettingsDialog(QDialog):
    """The categories at the left with a search over them, the chosen page at the right."""

    def __init__(
        self,
        parent: QWidget,
        categories: Sequence[Category],
        rows: Callable[[], Sequence[Row]],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle(t("Settings"))
        self.setModal(True)
        self.resize(900, 620)
        self._categories = list(categories)
        self._rows_of = rows
        self._rows: list[Row] = []
        self._pages: dict[str, QScrollArea] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(SIDEBAR_PX)
        side = QVBoxLayout(sidebar)
        s = theme.SPACE
        side.setContentsMargins(s["lg"], s["xl"], s["lg"], s["lg"])
        side.setSpacing(s["md"])
        title = QLabel(t("Settings"))
        title.setObjectName("settingsTitle")
        side.addWidget(title)
        self.search = QLineEdit()
        self.search.setObjectName("settingsSearch")
        self.search.setPlaceholderText(t("Search settings…"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._searched)
        side.addWidget(self.search)
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setIconSize(QSize(icons.SIZE, icons.SIZE))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for category in self._categories:
            item = QListWidgetItem(icons.icon(category.icon), category.title)
            item.setData(Qt.ItemDataRole.UserRole, category.key)
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self._picked)
        side.addWidget(self.nav, 1)
        hint = QLabel(t("Ctrl+, opens Settings from anywhere."))
        hint.setObjectName("settingsHint")
        hint.setWordWrap(True)
        side.addWidget(hint)
        outer.addWidget(sidebar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("settingsPages")
        outer.addWidget(self.pages, 1)
        self.setTabOrder(self.search, self.nav)

    # -- opening ----------------------------------------------------------------------

    def open_at(self, category: str | None = None) -> None:
        """Show the window on ``category`` (or where it was), the rows asked for afresh."""
        self.rebuild()
        if category is not None:
            self.show_category(category)
        elif self.nav.currentRow() < 0:
            self.nav.setCurrentRow(0)
        self.search.clear()
        self.open()
        self.search.setFocus(Qt.FocusReason.OtherFocusReason)

    def rebuild(self) -> None:
        """Ask the window for its rows again and lay every page out from them."""
        shown = self.current_category()
        self._rows = list(self._rows_of())
        while (page := self.pages.widget(0)) is not None:
            self.pages.removeWidget(page)
            page.deleteLater()
        self._pages = {}
        for category in self._categories:
            rows = [row for row in self._rows if row.category == category.key]
            page = self._page(category.title, category.about, rows, captions=False)
            self._pages[category.key] = page
            self.pages.addWidget(page)
        if self.search.text().strip():
            self._searched(self.search.text())
        elif shown is not None and shown in self._pages:
            self.pages.setCurrentWidget(self._pages[shown])

    def show_category(self, key: str) -> None:
        for index in range(self.nav.count()):
            if self.nav.item(index).data(Qt.ItemDataRole.UserRole) == key:
                self.nav.setCurrentRow(index)
                self._picked(index)
                return

    def current_category(self) -> str | None:
        item = self.nav.currentItem()
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def rows(self) -> list[Row]:
        return list(self._rows)

    def sync(self) -> None:
        """Say every action's state again, for a change made with its signals blocked --
        the live theme switch sets the theme actions that way."""
        syncs: list[Callable[[], None]] = [
            *(w.sync for w in self.pages.findChildren(Segments)),
            *(w.sync for w in self.pages.findChildren(Dropdown)),
            *(w.sync for w in self.pages.findChildren(SwatchRow)),
            *(w.sync for w in self.pages.findChildren(ToggleSwitch)),
        ]
        for sync in syncs:
            sync()

    def shown_titles(self) -> list[str]:
        """The titles of the rows on the page in front, top to bottom: what a test reads."""
        page = self.pages.currentWidget()
        if page is None:
            return []
        return [
            label.text()
            for label in page.findChildren(QLabel, "settingsRowTitle")
            if not label.isHidden()
        ]

    # -- what happens -----------------------------------------------------------------

    def _picked(self, index: int) -> None:
        if index < 0:
            return
        key = str(self.nav.item(index).data(Qt.ItemDataRole.UserRole))
        if self.search.text():
            # A category chosen mid-search is a way out of the search.
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self._drop_results()
        page = self._pages.get(key)
        if page is not None:
            self.pages.setCurrentWidget(page)
            page.verticalScrollBar().setValue(0)

    def _searched(self, text: str) -> None:
        self._drop_results()
        if not text.strip():
            key = self.current_category()
            if key in self._pages:
                self.pages.setCurrentWidget(self._pages[key])
                current = self.nav.currentItem()
                if current is not None:
                    current.setSelected(True)
            return
        # The list says no category while the page is a search's: the results are from all.
        self.nav.blockSignals(True)
        self.nav.clearSelection()
        self.nav.blockSignals(False)
        found = matches(self._rows, self._categories, text)
        heading = t("Settings matching “{text}”").format(text=text.strip())
        about = (
            t("Nothing matches. Try another word, in English or Turkish.")
            if not found
            else ""
        )
        page = self._page(heading, about, found, captions=True)
        page.setProperty("settingsResults", True)
        self.pages.addWidget(page)
        self.pages.setCurrentWidget(page)

    def _drop_results(self) -> None:
        for index in range(self.pages.count() - 1, -1, -1):
            page = self.pages.widget(index)
            if page is not None and page.property("settingsResults"):
                self.pages.removeWidget(page)
                page.deleteLater()

    def _pressed(self, run: Callable[[], None]) -> None:
        run()
        self.rebuild()

    # -- laying out -------------------------------------------------------------------

    def _page(self, title: str, about: str, rows: Sequence[Row], *, captions: bool) -> QScrollArea:
        titles = {c.key: c.title for c in self._categories}
        body = QWidget()
        body.setObjectName("settingsBody")
        column = QVBoxLayout(body)
        s = theme.SPACE
        column.setContentsMargins(s["2xl"] + s["md"], s["xl"] + s["xs"], s["2xl"] + s["md"], s["xl"])
        column.setSpacing(0)
        heading = QLabel(title)
        heading.setObjectName("settingsHeading")
        heading.setWordWrap(True)
        column.addWidget(heading)
        if about:
            line = QLabel(about)
            line.setObjectName("settingsAbout")
            line.setWordWrap(True)
            # A label styled with a padding takes half an "x" of indent too, which set the
            # line 4 px in from the heading above it.
            line.setIndent(0)
            column.addWidget(line)
        column.addSpacing(s["md"])
        for index, row in enumerate(rows):
            caption = titles.get(row.category, "") if captions else ""
            column.addWidget(self._row(row, caption, last=index == len(rows) - 1))
        column.addStretch(1)
        area = QScrollArea()
        area.setObjectName("settingsPage")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(body)
        return area

    def _row(self, row: Row, caption: str, *, last: bool) -> QFrame:
        frame = QFrame()
        frame.setObjectName("settingsRow")
        frame.setProperty("last", last)
        grid = QGridLayout(frame)
        s = theme.SPACE
        grid.setContentsMargins(0, s["lg"], 0, s["lg"])
        grid.setHorizontalSpacing(s["2xl"])
        grid.setVerticalSpacing(s["2xs"])
        line = 0
        if caption:
            over = QLabel(caption.upper())
            over.setObjectName("settingsCaption")
            grid.addWidget(over, line, 0)
            line += 1
        head = QHBoxLayout()
        head.setSpacing(s["md"])
        name = QLabel(row.title)
        name.setObjectName("settingsRowTitle")
        head.addWidget(name)
        tag = chip_of(row)
        chip = QLabel(tag)
        chip.setObjectName("settingsChip")
        chip.setVisible(bool(tag))
        head.addWidget(chip)
        head.addStretch(1)
        grid.addLayout(head, line, 0)
        why = QLabel(row.why)
        why.setObjectName("settingsWhy")
        why.setWordWrap(True)
        grid.addWidget(why, line + 1, 0)
        control = self._control(row)
        control.setAccessibleName(row.title)
        control.setAccessibleDescription(row.why)
        grid.addWidget(
            control, 0, 1, line + 2, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        grid.setColumnStretch(0, 1)
        if callable(row.chip):
            refresh = _ChipRefresh(chip, row.chip, frame)
            for action in _actions_of(row.control):
                action.toggled.connect(refresh.refresh)
        return frame

    def _control(self, row: Row) -> QWidget:
        control = row.control
        if isinstance(control, Toggle):
            return ToggleSwitch(control.action)
        if isinstance(control, Choice):
            return Segments(control) if control.segmented else Dropdown(control)
        if isinstance(control, Swatches):
            return SwatchRow(control)
        button = QPushButton(control.label)
        button.setObjectName("settingsButton")
        button.clicked.connect(lambda _checked=False, run=control.run: self._pressed(run))
        return button


class _ChipRefresh(QWidget):
    """Says a row's tag again when its action changes ("Not chosen yet" goes once chosen).
    A QObject so the connection ends with the row."""

    def __init__(self, chip: QLabel, say: Callable[[], str], parent: QWidget) -> None:
        super().__init__(parent)
        self.hide()
        self._chip = chip
        self._say = say

    def refresh(self, *_: object) -> None:
        tag = self._say()
        self._chip.setText(tag)
        self._chip.setVisible(bool(tag))


def _actions_of(control: Control) -> list[QAction]:
    if isinstance(control, Toggle):
        return [control.action]
    if isinstance(control, (Choice, Swatches)):
        return list(control.actions.values())
    return []
