"""Home: the window before there is a board, and between boards.

IT REPLACES A DIALOG OVER A FULL EDITOR. The welcome dialog appeared after the window was
up, so the first thing a newcomer saw was eight menus, a row of tools named Trace, Spine
and Ratsnest, six steps and five panels -- and on top of them four buttons that looked the
same ("Draw a New Circuit", "New Project…", "Open a Board…", "Open Project…") and two lists
of file names. The first question it put was "project or board?", which means nothing in
the first minute. Home is the whole window instead, and offers one thing to do first.

ONE DOOR, THEN THE OTHERS, SMALLER. Drawing a circuit is the primary button; opening a file
is the secondary one; importing from KiCad is a link, because the application draws its
own circuits and KiCad is a side entrance. Projects are a choice for the second board and
live in the File menu.

THE EXAMPLES ARE PICTURES, drawn by the same code that draws them in the window
(``boardpreview.render_board``, and the sheet for the one that is drawn and not built), so
a card cannot show a board the example does not open into. They are painted one per turn of
the event loop after Home is on screen: seven boards drawn before the first frame would be
a second of nothing at every start.

THE WINDOW OWNS EVERYTHING ELSE. Home imports nothing from ``main``: it says what was asked
for through its signals, and the window opens the file, leaves Home and shows the editor.
Esc is the window's too -- it means "a blank board", which is the window's to make.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio import persist
from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.model import PerfDocument
from perfboard_studio.schematic import build_schematic
from perfboard_studio.schematic_export import drawing_to_svg
from perfboard_studio.system import board_document, board_ids
from perfboard_studio.version import __version__

from . import theme
from .boardpreview import render_board
from .export_schematic import svg_to_image
from .i18n import t


@dataclass(frozen=True, slots=True)
class HomeExample:
    """An example as Home lists it: its file, and the line the window wrote for it ("8 parts
    on a 2 × 8 cm board"). The window reads the documents for that line already; Home only
    needs the file again to draw its picture."""

    path: Path
    line: str


#: The unbuilt example, which the "new here" card opens: drawn, not placed, so the step
#: bar's next button has every step still to do.
WALKTHROUGH = "ne555-blinker"

#: How many example cards fit a row, and how many show to somebody who has boards of
#: their own (the rest are one click away).
COLUMNS = 4
#: The size each picture is drawn at, before the card scales it.
PICTURE = QSize(320, 180)


def _boards_side_by_side(document: PerfDocument, lookup: FootprintLookup) -> QPixmap:
    """Every board of a system in a row, each drawn as the window draws it -- the
    System view's row, without its bench -- fitted together into the card's picture."""
    gap = theme.SPACE["lg"]
    ids = board_ids(document)
    each = QSize(max(1, (PICTURE.width() - gap * (len(ids) - 1)) // len(ids)), PICTURE.height())
    pictures = [render_board(board_document(document, board_id), lookup, each) for board_id in ids]
    width = sum(picture.width() for picture in pictures) + gap * (len(pictures) - 1)
    height = max(picture.height() for picture in pictures)
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    x = 0
    for picture in pictures:
        painter.drawPixmap(x, (height - picture.height()) // 2, picture)
        x += picture.width() + gap
    painter.end()
    return QPixmap.fromImage(image)


def example_title(stem: str) -> str:
    """What an example is, in words: "ne555-astable" says nothing to somebody who has never
    heard of a 555. A stem this table does not know is shown as it is."""
    titles = {
        "ne555-blinker": t("A 555 blinker, drawn and not built"),
        "ne555-astable": t("555 LED flasher"),
        "lm317-supply": t("Adjustable supply (LM317)"),
        "arduino-io-shield": t("Arduino I/O shield"),
        "lpb1-booster": t("Guitar booster pedal"),
        "nano-relay": t("Arduino Nano relay switch"),
        "atmega328-relay": t("ATmega328 relay controller"),
        "relay-and-supply": t("Relay driver and its supply, two boards"),
    }
    return titles.get(stem, stem)


class ExampleCard(QPushButton):
    """One example: a button, so Tab reaches it and Enter opens it, laid out as a card."""

    def __init__(self, example: HomeExample, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.example = example
        self.setObjectName("exampleCard")
        theme.variant(self, "card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(example_title(example.path.stem))
        layout = QVBoxLayout(self)
        self.content = layout
        layout.setContentsMargins(0, 0, 0, theme.SPACE["md"])
        layout.setSpacing(theme.SPACE["2xs"])
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setFixedHeight(128)
        layout.addWidget(self.picture)
        title = QLabel(example_title(example.path.stem))
        title.setWordWrap(True)
        line = QLabel(example.line)
        line.setWordWrap(True)
        theme.tone(line, "secondary")
        for label in (title, line):
            label.setContentsMargins(theme.SPACE["lg"], 0, theme.SPACE["lg"], 0)
            layout.addWidget(label)
        if example.path.stem == WALKTHROUGH:
            chip = QLabel(t("Start here"))
            chip.setContentsMargins(theme.SPACE["lg"], 0, theme.SPACE["lg"], 0)
            theme.tone(chip, "accent")
            layout.addWidget(chip)
        layout.addStretch(1)
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_picture(self, pixmap: QPixmap) -> None:
        self.picture.setPixmap(
            pixmap.scaled(
                QSize(self.picture.width() or PICTURE.width(), self.picture.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class Home(QWidget):
    """What the window shows when there is no board yet: one door to start, the others,
    the examples, and -- for somebody who has boards already -- the last ones opened."""

    newCircuit = Signal()
    openFile = Signal()
    importNetlist = Signal()
    #: The getting-started tour (ui/tour.py), which opens the walkthrough example itself.
    startTour = Signal()
    #: An example's path, as a string.
    openExample = Signal(str)
    #: A recent board's path, as a string.
    openRecent = Signal(str)
    showAtStartChanged = Signal(bool)

    def __init__(
        self,
        examples: Sequence[HomeExample],
        lookup: FootprintLookup,
        parent: QWidget | None = None,
        *,
        has_walkthrough: bool | None = None,
    ) -> None:
        """``examples`` may come later, through ``set_examples``: reading every example for
        its line is most of what Home costs a blank start, so the window puts Home up with
        none and hands them over on the first turn of the event loop. ``has_walkthrough``
        says whether the tour's example is there before then (a file name, not a read), so
        the "new here" card is in place on the first frame rather than arriving after it.
        """
        super().__init__(parent)
        self.setObjectName("home")
        self._examples = list(examples)
        self._has_walkthrough = (
            any(e.path.stem == WALKTHROUGH for e in self._examples)
            if has_walkthrough is None
            else has_walkthrough
        )
        self._lookup = lookup
        self._recent: list[str] = []
        self._showing_all = False
        self._to_draw: list[ExampleCard] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        page = QWidget()
        scroll.setWidget(page)
        column = QVBoxLayout(page)
        column.setContentsMargins(
            theme.SPACE["2xl"] * 2, theme.SPACE["2xl"], theme.SPACE["2xl"] * 2, theme.SPACE["xl"]
        )
        column.setSpacing(theme.SPACE["xl"])

        name = QLabel(f"{theme.heading('Perfboard Studio')}  {theme.ink(__version__, 'tertiary')}")
        column.addWidget(name)

        # -- the first door, for somebody with nothing yet ------------------------------
        self.first_run = QWidget()
        hero = QHBoxLayout(self.first_run)
        hero.setContentsMargins(0, 0, 0, 0)
        hero.setSpacing(theme.SPACE["2xl"])
        pitch = QVBoxLayout()
        pitch.setSpacing(theme.SPACE["md"])
        title = QLabel(theme.heading(t("Design it on screen. Solder it from the guide.")))
        title.setWordWrap(True)
        lead = QLabel(
            t(
                "Draw the circuit. The app picks a board you can buy, lays the parts out "
                "and wires them, then writes the soldering steps for you."
            )
        )
        lead.setWordWrap(True)
        theme.size(lead, theme.LEAD_PX)
        theme.tone(lead, "secondary")
        pitch.addWidget(title)
        pitch.addWidget(lead)
        self.first_button = QPushButton(t("Draw Your First Circuit"))
        pitch.addLayout(self._doors(self.first_button))
        pitch.addStretch(1)
        hero.addLayout(pitch, 3)
        self.walkthrough_card = self._walkthrough_card()
        hero.addWidget(self.walkthrough_card, 2)
        column.addWidget(self.first_run)

        # -- the same doors, smaller, above the boards somebody already has ------------
        self.returning = QWidget()
        back = QVBoxLayout(self.returning)
        back.setContentsMargins(0, 0, 0, 0)
        back.setSpacing(theme.SPACE["md"])
        top = QHBoxLayout()
        welcome = QLabel(theme.heading(t("Welcome back")))
        top.addWidget(welcome, 1)
        self.new_button = QPushButton(t("New Circuit"))
        top.addLayout(self._doors(self.new_button))
        back.addLayout(top)
        heading = QHBoxLayout()
        heading.addWidget(QLabel(theme.heading(t("Recent"))))
        hint = QLabel(t("Enter opens the highlighted one."))
        theme.tone(hint, "tertiary")
        heading.addWidget(hint)
        heading.addStretch(1)
        back.addLayout(heading)
        self.recent_list = QListWidget()
        self.recent_list.setObjectName("homeRecent")
        self.recent_list.itemActivated.connect(self._open_recent)
        self.recent_list.itemDoubleClicked.connect(self._open_recent)
        back.addWidget(self.recent_list)
        column.addWidget(self.returning)

        # -- the examples ---------------------------------------------------------------
        heading = QHBoxLayout()
        self._examples_title = QLabel(theme.heading(t("Examples")))
        heading.addWidget(self._examples_title)
        self._examples_note = QLabel(
            t("Each opens as an untitled copy. Nothing you change touches the original.")
        )
        theme.tone(self._examples_note, "secondary")
        heading.addWidget(self._examples_note)
        heading.addStretch(1)
        self.show_all = QPushButton(t("Show All Examples"))
        theme.variant(self.show_all, "link")
        self.show_all.clicked.connect(self._reveal_all)
        heading.addWidget(self.show_all)
        column.addLayout(heading)
        self.grid = QGridLayout()
        self.grid.setSpacing(theme.SPACE["lg"])
        self.cards: list[ExampleCard] = []
        column.addLayout(self.grid)
        column.addStretch(1)

        self.show_at_start = QCheckBox(t("Start on the home page"))
        self.show_at_start.setChecked(True)
        self.show_at_start.toggled.connect(self.showAtStartChanged)
        column.addWidget(self.show_at_start)

        self.set_examples(self._examples)
        self.set_recent([])

    # -- what the window tells Home ----------------------------------------------------

    def set_examples(self, examples: Sequence[HomeExample]) -> None:
        """The example cards, made anew: one per example, in the order given. With none --
        an install from a wheel ships none, and the window hands them over a turn after
        Home first shows -- the heading says nothing rather than head an empty row."""
        # Nothing still queued to be drawn may be a card about to go.
        self._to_draw = []
        for card in self.cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self._examples = list(examples)
        self.cards = []
        for index, example in enumerate(self._examples):
            card = ExampleCard(example)
            card.clicked.connect(lambda _checked=False, p=example.path: self.openExample.emit(str(p)))
            self.grid.addWidget(card, index // COLUMNS, index % COLUMNS, Qt.AlignmentFlag.AlignTop)
            self.cards.append(card)
        # One height for every card, so a title that wraps does not stagger the row.
        tallest = max((card.content.sizeHint().height() for card in self.cards), default=0)
        for card in self.cards:
            card.setFixedHeight(tallest)
        for widget in (self._examples_title, self._examples_note):
            widget.setVisible(bool(self._examples))
        self._lay_out_cards()
        # Cards that arrive while Home is on screen are drawn as they would have been had
        # they been there when it was shown.
        if self.isVisible():
            self._draw_pictures()
    def set_recent(self, paths: Sequence[str]) -> None:
        """The boards opened last, newest first. With none, Home is the first-run page; with
        any, it leads with them and the examples shrink to a row."""
        self._recent = [str(p) for p in paths]
        self.recent_list.clear()
        for entry in self._recent:
            path = Path(entry)
            item = QListWidgetItem(f"{path.stem}    {path.parent}")
            item.setToolTip(entry)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.recent_list.addItem(item)
        if self._recent:
            self.recent_list.setCurrentRow(0)
            self.recent_list.setFixedHeight(
                min(len(self._recent), 6) * (self.recent_list.sizeHintForRow(0) + 2) + 4
            )
        returning = bool(self._recent)
        self.first_run.setVisible(not returning)
        self.returning.setVisible(returning)
        self._showing_all = not returning
        self._lay_out_cards()

    def set_show_at_start(self, on: bool) -> None:
        self.show_at_start.blockSignals(True)
        self.show_at_start.setChecked(on)
        self.show_at_start.blockSignals(False)

    def focus_first(self) -> None:
        """Where the keyboard starts: the last board, or the primary door."""
        if self._recent:
            self.recent_list.setFocus()
        else:
            self.first_button.setFocus()

    # -- Qt --------------------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._draw_pictures()

    def _draw_pictures(self) -> None:
        """Paint the cards still without a picture, one per turn of the event loop."""
        pending = bool(self._to_draw)
        self._to_draw = [card for card in self.cards if card.picture.pixmap().isNull()]
        # One chain of turns at a time: a second would draw the same card twice.
        if self._to_draw and not pending:
            QTimer.singleShot(0, self._draw_next)

    # -- inside ------------------------------------------------------------------------

    def _doors(self, primary: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE["md"])
        theme.variant(primary, "primary")
        primary.setToolTip(t("Start on the sheet: add parts and join their pins. The board comes after."))
        primary.clicked.connect(self.newCircuit)
        opener = QPushButton(t("Open…"))
        opener.setToolTip(t("A board you saved (.perf)."))
        opener.clicked.connect(self.openFile)
        importer = QPushButton(t("Import from KiCad…"))
        importer.setToolTip(t("A circuit drawn in KiCad: its parts and connections come in as the design."))
        theme.variant(importer, "link")
        importer.clicked.connect(self.importNetlist)
        row.addWidget(primary)
        row.addWidget(opener)
        row.addWidget(importer)
        row.addStretch(1)
        return row

    def _walkthrough_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("homeWalkthrough")
        theme.variant(card, "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(*([theme.SPACE["xl"]] * 4))
        layout.setSpacing(theme.SPACE["sm"])
        caption = QLabel(t("New here?"))
        theme.size(caption, theme.CAPTION_PX)
        theme.tone(caption, "secondary")
        heading = QLabel(theme.heading(t("Take the 1-minute tour")))
        body = QLabel(
            t(
                "Opens a circuit that is already drawn and walks through it: board, "
                "placement, wiring, checks, guide."
            )
        )
        body.setWordWrap(True)
        theme.tone(body, "secondary")
        self.walkthrough_button = QPushButton(t("Start the Tour"))
        if not self._has_walkthrough:
            card.hide()  # the tour runs on that example, and this copy has none
        self.walkthrough_button.clicked.connect(lambda _checked=False: self.startTour.emit())
        for widget in (caption, heading, body):
            layout.addWidget(widget)
        layout.addWidget(self.walkthrough_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return card

    def _lay_out_cards(self) -> None:
        shown = len(self.cards) if self._showing_all else COLUMNS
        for index, card in enumerate(self.cards):
            card.setVisible(index < shown)
        self.show_all.setVisible(len(self.cards) > shown)

    def _reveal_all(self) -> None:
        self._showing_all = True
        self._lay_out_cards()

    def _open_recent(self, item: QListWidgetItem) -> None:
        self.openRecent.emit(str(item.data(Qt.ItemDataRole.UserRole)))

    def _draw_next(self) -> None:
        if not self._to_draw:
            return
        card = self._to_draw.pop(0)
        pixmap = self._picture(card.example.path)
        if pixmap is not None:
            card.set_picture(pixmap)
        if self._to_draw:
            QTimer.singleShot(0, self._draw_next)

    def _picture(self, path: Path) -> QPixmap | None:
        """The board as the window will draw it, or -- for a circuit with nothing placed --
        its sheet. None when the file cannot be read: the card keeps its words."""
        try:
            result = persist.deserialize_document(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return None
        if not result.ok:
            return None
        document = result.document
        if len(board_ids(document)) > 1:
            return _boards_side_by_side(document, self._lookup)
        if document.components:
            return render_board(document, self._lookup, PICTURE)
        svg = drawing_to_svg(build_schematic(document, self._lookup), title=document.meta.name)
        return QPixmap.fromImage(svg_to_image(svg, px_per_mm=2.0, background=theme.ACTIVE.sheet_paper))
