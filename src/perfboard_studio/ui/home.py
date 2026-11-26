"""Home: the window before there is a board, and between boards.

IT REPLACES A DIALOG OVER A FULL EDITOR. The welcome dialog appeared after the window was
up, so the first thing a newcomer saw was eight menus, a row of tools named Trace, Spine
and Ratsnest, six steps and five panels -- and on top of them four buttons that looked the
same ("Draw a New Circuit", "New Project…", "Open a Board…", "Open Project…") and two lists
of file names. The first question it put was "project or board?", which means nothing in
the first minute. Home is the whole window instead, and offers one thing to do first.

A SIDEBAR FOR THE DOORS AND THE PLACES, A PAGE FOR THE BOARDS. Drawing a circuit is the
primary door; opening a file is the second, aligned with it; importing from KiCad is a
link, because the application draws its own circuits and KiCad is a side entrance. Under
them, the page's sections by name -- Home, Recent, Examples -- with the one the page is
scrolled to lit, and the tour. The sidebar narrows on a small screen rather than going.

ONE FRAME FOR A FIRST START AND EVERY START AFTER IT. Where the board opened last stands
as a banner, a first start has the same banner saying what the application does and
offering the tour, so Home does not change shape the day somebody saves their first board.

THE BOARD OPENED LAST COMES FORWARD, with where it stands -- the step bar's six dots, the
next thing to do -- and one button to go on with it. Where it stands is its checks, run
on its file by the window (``main.file_facts``) once Home is on screen
(``after_first_frame``); until then, and for a file that no longer opens, the boards are
the row of cards under it.

THE PICTURES ARE DRAWN, by the same code that draws them in the window
(``boardpreview.render_board``, and the sheet for a circuit drawn and not built), so a card
cannot show a board the file does not open into. Every one sits in one frame, 16:10, on a
backdrop washed with its own colour. They are painted one per turn of the event loop after
Home's first frame: a dozen boards drawn before it would be a second of nothing.

THE PAGE IS A BLUEPRINT: a faint grid in the accent, made once per theme and pixel ratio
as a tile and painted as a brush, on the page so it scrolls with the boards.

THE WINDOW OWNS EVERYTHING ELSE. Home imports nothing from ``main``: it says what was asked
for through its signals, and the window opens the file, leaves Home and shows the editor.
Esc is the window's too -- it means "a blank board", which is the window's to make.
"""

from __future__ import annotations

import datetime
import html
import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyleOptionGraphicsItem,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio import persist
from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.model import PerfDocument
from perfboard_studio.schematic import build_schematic
from perfboard_studio.system import board_document, board_ids
from perfboard_studio.version import __version__

from . import hover, theme, viewsch
from .boardpreview import render_board
from .brand import BrandLink
from .i18n import t
from .workflow import DOT_SIZE, StepState, step_dot, step_title


@dataclass(frozen=True, slots=True)
class HomeExample:
    """An example as Home lists it: its file, and the line the window wrote for it ("8 parts
    on a 2 × 8 cm board"). The window reads the documents for that line already; Home only
    needs the file again to draw its picture."""

    path: Path
    line: str


@dataclass(frozen=True, slots=True)
class LastBoard:
    """The board opened last, as Home offers to go on with it: its file, the document read
    from it (for its picture), the step bar's steps for it, and the one sentence that says
    what to do next. The window works it out -- the steps are its checks, on the file --
    and Home only shows it.

    ``open`` is the board open in the window right now, Home having been reached from File
    ▸ Home or the header's house: Continue goes back to it rather than reading it again, and
    the window says its ``name`` and whether it is ``modified``, since it may never have
    been saved (``path`` None)."""

    path: Path | None
    document: PerfDocument
    steps: tuple[StepState, ...]
    hint: str
    open: bool = False
    name: str = ""
    modified: bool = False


@dataclass(frozen=True, slots=True)
class UpdateStatus:
    """Where fetching and installing a release stands, as Home's update card says it.

    The default is "nothing done yet", where the card quotes the release's own summary.
    Otherwise ``headline`` is the state in a sentence ("The update was not installed."),
    ``detail`` the line under it, ``progress`` the bytes received and expected while a
    download runs, ``trouble`` that it went wrong, and ``reveal`` and ``cancel`` whether
    Show the File and Cancel can be pressed now. The window reads it off the strip
    (``MainWindow._update_status``), so the card and the strip cannot disagree."""

    headline: str = ""
    detail: str = ""
    progress: tuple[int, int] | None = None
    trouble: bool = False
    reveal: bool = False
    cancel: bool = False


#: The unbuilt example, which the tour opens: drawn, not placed, so the step bar's next
#: button has every step still to do.
WALKTHROUGH = "ne555-blinker"

#: How many cards make a row; a returning user sees one row of each, the rest on request.
COLUMNS = 4
#: Every picture's frame, height to width: a board's card, a sheet's, the banner's.
RATIO = 10 / 16
#: The size each card's picture is drawn at, before the frame fits it.
PICTURE = QSize(400, 250)
#: The banner's picture: the same frame, larger.
LAST_PICTURE = QSize(640, 400)
#: How far a picture's backdrop is washed toward the picture's own colour.
TINT = 0.16
#: The sidebar, and the narrower one below ``NARROW_BELOW`` px of window: at 1366 the
#: page keeps four cards abreast.
SIDE_WIDE = 248
SIDE_NARROW = 200
NARROW_BELOW = 1500
#: The page's column stops growing here, and centres, on a wide screen.
CONTENT_MAX = 1360
#: The blueprint: a minor line every 8 px and a major one every 40, washed from the page's
#: background toward the accent by this much (the minor lines by about half of it).
GRID_MINOR = 8
GRID_MAJOR = 40
GRID_WASH = 0.05


def _wash(base: QColor, toward: QColor, amount: float) -> QColor:
    return QColor(
        round(base.red() + (toward.red() - base.red()) * amount),
        round(base.green() + (toward.green() - base.green()) * amount),
        round(base.blue() + (toward.blue() - base.blue()) * amount),
    )


def _average(pixmap: QPixmap) -> QColor | None:
    """The picture's own colour: the mean of its opaque pixels, read off a 16 × 10 copy."""
    small = pixmap.toImage().scaled(
        16, 10, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    ).convertToFormat(QImage.Format.Format_ARGB32)
    red = green = blue = count = 0
    for y in range(small.height()):
        for x in range(small.width()):
            colour = small.pixelColor(x, y)
            if colour.alpha() > 200:
                red += colour.red()
                green += colour.green()
                blue += colour.blue()
                count += 1
    if not count:
        return None
    return QColor(round(red / count), round(green / count), round(blue / count))


_TILES: dict[tuple[str, float], QPixmap] = {}


def blueprint_tile(tokens: theme.Tokens, ratio: float) -> QPixmap:
    """One tile of the page's grid, made once per theme and pixel ratio. Drawn in device
    pixels, so a line is a whole number of them at every scale and never a blur."""
    key = (tokens.name, ratio)
    tile = _TILES.get(key)
    if tile is not None:
        return tile
    scale = max(1, round(ratio))
    size = round(GRID_MAJOR * ratio)
    background, accent = QColor(tokens.bg_app), QColor(tokens.accent)
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(background)
    painter = QPainter(image)
    minor = QPen(_wash(background, accent, GRID_WASH * 0.55))
    minor.setWidth(scale)
    painter.setPen(minor)
    for step in range(GRID_MINOR, GRID_MAJOR, GRID_MINOR):
        at = round(step * ratio)
        painter.drawLine(at, 0, at, size)
        painter.drawLine(0, at, size, at)
    major = QPen(_wash(background, accent, GRID_WASH))
    major.setWidth(scale)
    painter.setPen(major)
    painter.drawLine(0, 0, size, 0)
    painter.drawLine(0, 0, 0, size)
    painter.end()
    tile = QPixmap.fromImage(image)
    tile.setDevicePixelRatio(ratio)
    _TILES[key] = tile
    return tile


def _boards_side_by_side(
    document: PerfDocument, lookup: FootprintLookup, size: QSize = PICTURE
) -> QPixmap:
    """Every board of a system in a row, each drawn as the window draws it -- the
    System view's row, without its bench -- fitted together into the card's picture."""
    gap = theme.SPACE["lg"]
    ids = board_ids(document)
    each = QSize(max(1, (size.width() - gap * (len(ids) - 1)) // len(ids)), size.height())
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


def _sheet_picture(
    document: PerfDocument, lookup: FootprintLookup, size: QSize = PICTURE
) -> QPixmap | None:
    """The circuit's sheet as the window's sheet view paints it -- its own item, on its
    paper, in the theme's ink -- for a circuit with nothing placed yet.

    It was the SVG export, whose paper is white on purpose because it goes to a printer: a
    white rectangle glaring out of the dark page, narrower than the boards beside it (the
    release-candidate sitting asked why it was white). The export is unchanged; this is
    the view's picture, as a dragged symbol's is (``SchematicView._symbol_pixmap``), and
    the frame around it is the same paper (``FramedPicture``)."""
    drawing = build_schematic(document, lookup)
    sheet = QRectF(0.0, 0.0, drawing.width, drawing.height)
    if sheet.isEmpty():
        return None
    margin = theme.SPACE["md"]
    scale = min(
        (size.width() - 2 * margin) / sheet.width(),
        (size.height() - 2 * margin) / sheet.height(),
    )
    picture = QPixmap(
        round(sheet.width() * scale) + 2 * margin, round(sheet.height() * scale) + 2 * margin
    )
    picture.fill(QColor(viewsch.SHEET))
    painter = QPainter(picture)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(margin, margin)
    painter.scale(scale, scale)
    viewsch.SheetItem(drawing).paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()
    return picture


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


def saved_when(path: Path, today: datetime.date | None = None) -> str:
    """When ``path`` was last written, as a person says it: today, yesterday, so many days
    ago, or the date. Nothing for a file that cannot be asked."""
    try:
        day = datetime.date.fromtimestamp(path.stat().st_mtime)
    except (OSError, OverflowError, ValueError):
        return ""
    days = ((today or datetime.date.today()) - day).days
    if days <= 0:
        return t("Saved today")
    if days == 1:
        return t("Saved yesterday")
    if days < 30:
        return t("Saved {count} days ago").format(count=days)
    return t("Saved {date}").format(date=day.isoformat())


def _clear(widget: QWidget) -> QWidget:
    """A container that lets the page's grid show through it."""
    widget.setProperty("clear", True)
    return widget


def _caption(text: str) -> QLabel:
    """A banner's small line above its title, in the accent."""
    label = QLabel(text)
    label.setObjectName("homeCaption")
    return label


def _title(text: str, px: int) -> QLabel:
    label = QLabel(f'<span style="font-size:{px}px; font-weight:{theme.SEMIBOLD}">{text}</span>')
    label.setWordWrap(True)
    return label


class FramedPicture(QWidget):
    """A picture in Home's one frame: 16:10 at whatever width it is given, the board centred
    on a backdrop washed with the board's own colour -- the sheet's paper for a sheet -- and
    rounded where it meets its card's corners (the top of a card, the left of a banner)."""

    def __init__(self, rounded: Literal["top", "left"] = "top", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rounded = rounded
        self._source = QPixmap()
        self._on_paper = False
        self._average_colour: QColor | None = None
        self._backdrop = QColor(theme.ACTIVE.bg_subtle)
        self._scaled = QPixmap()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(round(PICTURE.width() * RATIO))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def sizeHint(self) -> QSize:
        return QSize(PICTURE.width(), self.height())

    def pixmap(self) -> QPixmap:
        """The picture as it was drawn, or a null pixmap before it is."""
        return self._source

    @property
    def on_paper(self) -> bool:
        return self._on_paper

    @property
    def backdrop(self) -> QColor:
        return QColor(self._backdrop)

    def set_picture(self, pixmap: QPixmap, *, on_paper: bool = False) -> None:
        self._source = pixmap
        self._on_paper = on_paper
        if on_paper:
            self._average_colour = None
            self._backdrop = QColor(theme.ACTIVE.sheet_paper)
        else:
            self._average_colour = _average(pixmap)
            base = QColor(theme.ACTIVE.bg_subtle)
            self._backdrop = (
                base if self._average_colour is None else _wash(base, self._average_colour, TINT)
            )
        self._scaled = QPixmap()
        self.update()

    def clear(self) -> None:
        self._source = QPixmap()
        self._on_paper = False
        self._average_colour = None
        self._backdrop = QColor(theme.ACTIVE.bg_subtle)
        self._scaled = QPixmap()
        self.update()

    def refresh_theme(self) -> None:
        """Recompute the card frame's backdrop for the active theme."""
        if self._source.isNull():
            self._backdrop = QColor(theme.ACTIVE.bg_subtle)
        elif self._on_paper:
            self._backdrop = QColor(theme.ACTIVE.sheet_paper)
        else:
            base = QColor(theme.ACTIVE.bg_subtle)
            self._backdrop = (
                base if self._average_colour is None else _wash(base, self._average_colour, TINT)
            )
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        height = round(self.width() * RATIO)
        if height != self.height():
            self.setFixedHeight(height)
        self._scaled = QPixmap()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        frame = QRectF(self.rect())
        radius = theme.RADIUS_LG - 1
        outline = QPainterPath()
        outline.addRoundedRect(frame, radius, radius)
        outline.setFillRule(Qt.FillRule.WindingFill)
        if self._rounded == "top":
            outline.addRect(QRectF(0, frame.height() / 2, frame.width(), frame.height() / 2))
        else:
            outline.addRect(QRectF(frame.width() / 2, 0, frame.width() / 2, frame.height()))
        painter.setClipPath(outline.simplified())
        painter.fillRect(frame, self._backdrop)
        if not self._source.isNull():
            ratio = self.devicePixelRatioF()
            pad = max(theme.SPACE["md"], round(self.width() * 0.045))
            room = QSize(max(1, self.width() - 2 * pad), max(1, self.height() - 2 * pad))
            if self._scaled.isNull() or self._scaled.devicePixelRatio() != ratio:
                self._scaled = self._source.scaled(
                    room * ratio,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._scaled.setDevicePixelRatio(ratio)
            shown = self._scaled.deviceIndependentSize()
            painter.drawPixmap(
                QPoint(
                    round((self.width() - shown.width()) / 2),
                    round((self.height() - shown.height()) / 2),
                ),
                self._scaled,
            )
        painter.end()


class _Card(QPushButton):
    """A board as a card: its picture in the frame, a title, and a line under it. A button,
    so Tab reaches it and Enter opens it."""

    path: Path

    def __init__(self, title: str, line: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("homeCard")
        theme.variant(self, "card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAccessibleName(title)
        layout = QVBoxLayout(self)
        self.content = layout
        layout.setContentsMargins(1, 1, 1, theme.SPACE["lg"])
        layout.setSpacing(theme.SPACE["2xs"])
        self.picture = FramedPicture("top")
        layout.addWidget(self.picture)
        layout.addSpacing(theme.SPACE["sm"])
        self.title = QLabel(f"<b>{html.escape(title)}</b>")
        self.title.setWordWrap(True)
        self.line = QLabel(line)
        self.line.setWordWrap(True)
        theme.tone(self.line, "secondary")
        for label in (self.title, self.line):
            label.setContentsMargins(theme.SPACE["lg"], 0, theme.SPACE["lg"], 0)
            layout.addWidget(label)

    def finish(self) -> None:
        self.content.addStretch(1)
        # Under the pointer the card rises off the page (``ui/hover.py``).
        hover.lift(self)
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_picture(self, pixmap: QPixmap, *, on_paper: bool = False) -> None:
        self.picture.set_picture(pixmap, on_paper=on_paper)


class ExampleCard(_Card):
    """One example."""

    def __init__(self, example: HomeExample, parent: QWidget | None = None) -> None:
        super().__init__(example_title(example.path.stem), example.line, parent)
        self.example = example
        self.path = example.path
        if example.path.stem == WALKTHROUGH:
            chip = QLabel(t("Start here"))
            chip.setContentsMargins(theme.SPACE["lg"], 0, theme.SPACE["lg"], 0)
            theme.tone(chip, "accent")
            self.content.addWidget(chip)
        self.finish()


class RecentCard(_Card):
    """One of the boards opened last: its name, and when it was saved and where."""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        when = saved_when(path)
        where = path.parent.name
        super().__init__(path.stem, "  ·  ".join(part for part in (when, where) if part), parent)
        self.path = path
        self.setToolTip(str(path))
        self.finish()


class _Blueprint(QWidget):
    """The page: the theme's background ruled as a blueprint, scrolling with what is on it."""

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(
            event.rect(), QBrush(blueprint_tile(theme.ACTIVE, self.devicePixelRatioF()))
        )
        painter.end()


class Home(QWidget):
    """What the window shows when there is no board yet: the doors, the board opened last
    and the others, and the examples."""

    newCircuit = Signal()
    openFile = Signal()
    importNetlist = Signal()
    #: The getting-started tour (ui/tour.py), which opens the walkthrough example itself.
    startTour = Signal()
    #: An example's path, as a string.
    openExample = Signal(str)
    #: A recent board's path, as a string.
    openRecent = Signal(str)
    #: Continue, or Esc, on the board still open behind Home: back to it as it was.
    resumeBoard = Signal()
    showAtStartChanged = Signal(bool)
    #: The update card's buttons. The window decides what the primary one does
    #: (download, or install and restart); Home only says it was pressed.
    updateNotesRequested = Signal()
    updateActionRequested = Signal()
    updateRevealRequested = Signal()
    updateCancelRequested = Signal()

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
        the tour is offered on the first frame rather than arriving after it.
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
        self._last: LastBoard | None = None
        self._showing_all = False
        self._showing_all_recent = False
        self._to_draw: list[tuple[FramedPicture, Path, QSize]] = []
        self._painted = False
        self._after_paint: list[Callable[[], None]] = []
        self._scrolling_to = False
        self._placeholders: dict[int, list[QWidget]] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # Built first, so Tab goes through the sidebar before the page.
        self.side = self._sidebar()
        outer.addWidget(self.side)
        self.scroller = QScrollArea()
        self.scroller.setWidgetResizable(True)
        self.scroller.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.scroller, 1)
        self.page = _Blueprint()
        self.page.setObjectName("homePage")
        self.page.installEventFilter(self)
        self.scroller.setWidget(self.page)
        centre = QHBoxLayout(self.page)
        centre.setContentsMargins(0, 0, 0, 0)
        centre.addStretch(1)
        self.column = _clear(QWidget())
        centre.addWidget(self.column, 100)
        centre.addStretch(1)
        column = QVBoxLayout(self.column)
        self._column_layout = column
        column.setSpacing(theme.SPACE["2xl"])

        self.welcome = QLabel()
        column.addWidget(self.welcome)
        self.update_card = self._update_card()
        column.addWidget(self.update_card)
        self.first_run = self._first_run_banner()
        column.addWidget(self.first_run)
        self.last_card = self._last_card()
        column.addWidget(self.last_card)

        # -- the boards opened last ----------------------------------------------------
        self.returning = _clear(QWidget())
        back = QVBoxLayout(self.returning)
        back.setContentsMargins(0, 0, 0, 0)
        back.setSpacing(theme.SPACE["lg"])
        heading = QHBoxLayout()
        self._recent_title = _title(t("Recent"), theme.LEAD_PX + 3)
        heading.addWidget(self._recent_title)
        heading.addStretch(1)
        self.show_all_recent = QPushButton(t("Show All"))
        theme.variant(self.show_all_recent, "link")
        self.show_all_recent.clicked.connect(self._reveal_all_recent)
        heading.addWidget(self.show_all_recent)
        back.addLayout(heading)
        self.recent_grid = QGridLayout()
        self.recent_grid.setSpacing(theme.SPACE["xl"])
        back.addLayout(self.recent_grid)
        self.recent_cards: list[RecentCard] = []
        column.addWidget(self.returning)

        # -- the examples ---------------------------------------------------------------
        self.examples_section = _clear(QWidget())
        section = QVBoxLayout(self.examples_section)
        section.setContentsMargins(0, 0, 0, 0)
        section.setSpacing(theme.SPACE["lg"])
        heading = QHBoxLayout()
        heading.setSpacing(theme.SPACE["lg"])
        self._examples_title = _title(t("Examples"), theme.LEAD_PX + 3)
        heading.addWidget(self._examples_title)
        self._examples_note = QLabel(
            t("Each opens as an untitled copy. Nothing you change touches the original.")
        )
        theme.tone(self._examples_note, "tertiary")
        # Wrapped, so a wider face (or a longer language) folds it rather than widen the page.
        self._examples_note.setWordWrap(True)
        heading.addWidget(self._examples_note, 1)
        self.show_all = QPushButton(t("Show All Examples"))
        theme.variant(self.show_all, "link")
        self.show_all.clicked.connect(self._reveal_all)
        heading.addWidget(self.show_all)
        section.addLayout(heading)
        self.grid = QGridLayout()
        self.grid.setSpacing(theme.SPACE["xl"])
        section.addLayout(self.grid)
        self.cards: list[ExampleCard] = []
        column.addWidget(self.examples_section)
        column.addStretch(1)

        self.scroller.verticalScrollBar().valueChanged.connect(self._follow_scroll)
        self._fit_to_width(1366)
        self.set_examples(self._examples)
        self.set_recent([])

    # -- what the window tells Home ----------------------------------------------------

    def set_update(
        self,
        version: str | None,
        *,
        summary: str = "",
        action: str = "",
        status: UpdateStatus | None = None,
    ) -> None:
        """The card that says a newer release exists, or none (``version`` ``None``).

        ``action`` is what the primary button does now: ``"download"``, ``"install"`` or
        ``""`` (nothing to press: a download is under way, or this build cannot install
        itself). What Changed is always there, because reading is always possible.

        ``status`` is where fetching and installing it stands, said under the headline in
        place of the release's summary: the card is the only notice over Home, so the
        progress, the file landed and a refusal are said here or nowhere.
        """
        if version is None:
            self.update_card.hide()
            return
        status = status or UpdateStatus()
        self.update_headline.setText(
            "<b>"
            + t("Perfboard Studio {new} is available — you have {old}.").format(
                new=html.escape(version), old=html.escape(__version__)
            )
            + "</b>"
        )
        self.update_status.setText(status.headline)
        self.update_status.setVisible(bool(status.headline))
        theme.tone(self.update_status, "danger" if status.trouble else "text")
        detail = status.detail if status.headline or status.progress else summary
        self.update_detail.setText(detail)
        self.update_detail.setVisible(bool(detail))
        if status.progress is not None:
            received, total = status.progress
            self.update_progress.setRange(0, max(total, 0))
            self.update_progress.setValue(max(received, 0))
        self.update_progress.setVisible(status.progress is not None)
        self.update_reveal.setVisible(status.reveal)
        self.update_cancel.setVisible(status.cancel)
        labels = {"download": t("Download"), "install": t("Install and Restart")}
        self.update_action.setVisible(action in labels)
        self.update_action.setText(labels.get(action, ""))
        self.update_card.show()

    def set_examples(self, examples: Sequence[HomeExample]) -> None:
        """The example cards, made anew: one per example, in the order given. With none --
        an install from a wheel ships none, and the window hands them over a turn after
        Home first shows -- the section says nothing rather than head an empty row."""
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
            self.grid.addWidget(card, index // COLUMNS, index % COLUMNS)
            self.cards.append(card)
        self.examples_section.setVisible(bool(self._examples))
        self.nav_examples.setVisible(bool(self._examples))
        self._lay_out_cards()
        self._chain_focus()
        # Cards that arrive while Home is on screen are drawn as they would have been had
        # they been there when it was shown.
        if self.isVisible():
            self._draw_pictures()

    def set_recent(self, paths: Sequence[str], *, returning: bool | None = None) -> None:
        """The boards opened last, newest first. With none, Home is the first-start page;
        with any, it leads with them and the examples shrink to a row -- or as
        ``returning`` says, for a window with a board open and nothing saved yet, whose
        Home is not a first start either. The last board's banner goes until ``set_last``
        says again which of them it is."""
        self._recent = [str(p) for p in paths]
        self._last = None
        self.last_card.hide()
        if returning is None:
            returning = bool(self._recent)
        self.first_run.setVisible(not returning)
        self.welcome.setText(
            theme.heading(t("Welcome back") if returning else t("Welcome to Perfboard Studio"))
        )
        theme.size(self.welcome, theme.TITLE_PX)
        self.new_button.setText(t("New Circuit") if returning else t("Draw Your First Circuit"))
        self._showing_all = not returning
        self._showing_all_recent = False
        self._fill_recent()
        self._lay_out_cards()
        if self.isVisible():
            self._draw_pictures()

    def set_last(self, last: LastBoard | None) -> None:
        """The board opened last, large, with where it stands and Continue; or, with
        ``None``, the row of boards alone. The row leaves out the board the banner is
        about, and the keyboard moves to Continue if it was on one of the boards."""
        self._last = last
        on_a_board = any(card.hasFocus() for card in self.recent_cards)
        if last is None:
            self.last_card.hide()
            self._fill_recent()
            return
        path = last.path
        called = last.name or (path.stem if path is not None else "")
        self.last_caption.setText(t("Open now") if last.open else t("Last opened"))
        self.last_name.setText(theme.heading(html.escape(called)))
        where = str(path) if path is not None else called
        self.last_name.setToolTip(where)
        when = t("Not saved") if last.modified else (saved_when(path) if path else "")
        folder = path.parent.name if path is not None else ""
        self.last_folder.setText("  ·  ".join(part for part in (when, folder) if part))
        self.last_card.setToolTip(where)
        drawn = self._picture_of_document(last.document, LAST_PICTURE)
        if drawn is not None:
            self.last_picture.set_picture(drawn[0], on_paper=drawn[1])
        else:
            self.last_picture.clear()
        self._fill_last_steps(last.steps)
        self.last_hint.setText(last.hint)
        self.last_card.show()
        self._fill_recent()
        if on_a_board or self.focusWidget() is None:
            self.continue_button.setFocus()

    def _fill_last_steps(self, steps: Sequence[StepState]) -> None:
        row = self._last_steps_row
        while row.count():
            item = row.takeAt(0)
            gone = item.widget() if item is not None else None
            if gone is not None:
                gone.hide()
                gone.setParent(None)
                gone.deleteLater()
        for number, step in enumerate(steps, start=1):
            dot = QLabel()
            dot.setPixmap(step_dot(number, step.status).pixmap(QSize(DOT_SIZE, DOT_SIZE)))
            name = QLabel(step_title(step.key))
            if step.status == "current":
                name.setText(f"<b>{html.escape(step_title(step.key))}</b>")
            elif step.status == "problem":
                theme.tone(name, "danger")
            else:
                theme.tone(name, "secondary" if step.status == "done" else "tertiary")
            row.addWidget(dot)
            row.addWidget(name)
            # The steps are one line from the first to the last: a rule between each two.
            if number < len(steps):
                rule = QFrame()
                rule.setObjectName("homeStepRule")
                rule.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                rule.setFixedHeight(1)
                rule.setMinimumWidth(theme.SPACE["sm"])
                row.addWidget(rule, 1)

    def refresh_theme(self) -> None:
        """Recolour Home's blueprint, card backdrops, sheet thumbnails and step dots live."""
        pictures: list[FramedPicture] = [
            self.walkthrough_picture,
            self.last_picture,
            *(card.picture for card in self.recent_cards),
            *(card.picture for card in self.cards),
        ]
        need_sheet_redraw = False
        for picture in pictures:
            if picture.on_paper and not picture.pixmap().isNull():
                if picture is self.last_picture and self._last is not None:
                    drawn = self._picture_of_document(self._last.document, LAST_PICTURE)
                    if drawn is not None:
                        picture.set_picture(drawn[0], on_paper=drawn[1])
                else:
                    picture.clear()
                    need_sheet_redraw = True
            else:
                picture.refresh_theme()
        if self._last is not None:
            self._fill_last_steps(self._last.steps)
        if self.brand.loaded:
            self.brand.load()
        if need_sheet_redraw and self.isVisible():
            self._draw_pictures()
        self.page.update()
        self.update()

    def set_show_at_start(self, on: bool) -> None:
        self.show_at_start.blockSignals(True)
        self.show_at_start.setChecked(on)
        self.show_at_start.blockSignals(False)

    def focus_first(self) -> None:
        """Where the keyboard starts: Continue, the first of the boards, or the first door."""
        if self._last is not None:
            self.continue_button.setFocus()
        elif self._shown_recent():
            self.recent_cards[0].setFocus()
        else:
            self.new_button.setFocus()

    def after_first_frame(self, callback: Callable[[], None]) -> None:
        """Run ``callback`` a turn after Home's page is first painted -- or on the next
        turn, if it has been. A zero timer set before the window is shown runs BEFORE its
        first frame, which is how the last board's checks once held that frame back."""
        if self._painted:
            QTimer.singleShot(0, self, callback)
        else:
            self._after_paint.append(callback)

    # -- Qt --------------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.page and event.type() == QEvent.Type.Paint and not self._painted:
            self._painted = True
            self.page.removeEventFilter(self)
            waiting, self._after_paint = self._after_paint, []
            for callback in waiting:
                QTimer.singleShot(0, self, callback)
        return False

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._draw_pictures()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_to_width(self.width())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Enter presses the button the keyboard is on -- a push button outside a dialog
        lets Enter go by -- and, on nothing in particular, opens the board opened last."""
        if event.key() == Qt.Key.Key_Escape and self._last is not None and self._last.open:
            # Home over a board left open is a step away from it, and Esc is the step back.
            self.resumeBoard.emit()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focused = self.focusWidget()
            if isinstance(focused, QPushButton) and self.isAncestorOf(focused):
                focused.click()
                return
            if self._last is not None:
                self._continue()
                return
        super().keyPressEvent(event)

    # -- inside ------------------------------------------------------------------------

    def _sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("homeSide")
        column = QVBoxLayout(side)
        column.setContentsMargins(
            theme.SPACE["xl"], theme.SPACE["2xl"], theme.SPACE["xl"], theme.SPACE["xl"]
        )
        column.setSpacing(theme.SPACE["sm"])
        self.new_button = QPushButton(t("New Circuit"))
        self.new_button.setObjectName("homeDoor")
        theme.variant(self.new_button, "primary")
        self.new_button.setToolTip(
            t("Start on the sheet: add parts and join their pins. The board comes after.")
        )
        self.new_button.clicked.connect(self.newCircuit)
        self.open_button = QPushButton(t("Open…"))
        self.open_button.setObjectName("homeDoor")
        self.open_button.setToolTip(t("A board you saved (.perf)."))
        self.open_button.clicked.connect(self.openFile)
        importer = QPushButton(t("Import from KiCad…"))
        importer.setToolTip(t("A circuit drawn in KiCad: its parts and connections come in as the design."))
        theme.variant(importer, "link")
        importer.clicked.connect(self.importNetlist)
        column.addWidget(self.new_button)
        column.addWidget(self.open_button)
        column.addWidget(importer, 0, Qt.AlignmentFlag.AlignLeft)
        column.addSpacing(theme.SPACE["xl"])

        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)

        def place(text: str, checkable: bool = True) -> QPushButton:
            button = QPushButton(text)
            button.setObjectName("homeNav")
            button.setCheckable(checkable)
            if checkable:
                self.nav.addButton(button)
            column.addWidget(button)
            return button

        self.nav_home = place(t("Home"))
        self.nav_recent = place(t("Recent"))
        self.nav_examples = place(t("Examples"))
        self.nav_tour = place(t("Tour"), checkable=False)
        self.nav_home.setChecked(True)
        self.nav_home.clicked.connect(lambda _checked=False: self._go_to(self.nav_home))
        self.nav_recent.clicked.connect(lambda _checked=False: self._go_to(self.nav_recent))
        self.nav_examples.clicked.connect(lambda _checked=False: self._go_to(self.nav_examples))
        self.nav_tour.clicked.connect(lambda _checked=False: self.startTour.emit())
        self.nav_tour.setVisible(self._has_walkthrough)
        column.addStretch(1)

        self.show_at_start = QCheckBox(t("Start on the home page"))
        self.show_at_start.setChecked(True)
        self.show_at_start.toggled.connect(self.showAtStartChanged)
        column.addWidget(self.show_at_start)
        version = QLabel(f"Perfboard Studio {__version__}")
        theme.size(version, theme.CAPTION_PX)
        theme.tone(version, "tertiary")
        column.addWidget(version)
        # Who makes it, in the corner under the version: the mark and the name, a link to
        # the site (``ui/brand.py``), quieter than anything above it.
        column.addSpacing(theme.SPACE["xs"])
        self.brand = BrandLink("home")
        column.addWidget(self.brand, 0, Qt.AlignmentFlag.AlignLeft)
        return side

    def _banner(self, name: str) -> tuple[QFrame, FramedPicture, QVBoxLayout]:
        """A wide card: a picture on the left, words on the right."""
        card = QFrame()
        card.setObjectName(name)
        theme.variant(card, "card")
        row = QHBoxLayout(card)
        row.setContentsMargins(1, 1, theme.SPACE["2xl"], 1)
        row.setSpacing(theme.SPACE["2xl"])
        picture = FramedPicture("left")
        row.addWidget(picture, 2)
        holder = _clear(QWidget())
        words = QVBoxLayout(holder)
        words.setContentsMargins(0, theme.SPACE["xl"], 0, theme.SPACE["xl"])
        words.setSpacing(theme.SPACE["sm"])
        words.addStretch(1)
        row.addWidget(holder, 3)
        return card, picture, words

    def _first_run_banner(self) -> QFrame:
        """Where the board opened last will stand: what the application does, and the tour
        on the circuit it opens, pictured."""
        card, self.walkthrough_picture, words = self._banner("homeFirstRun")
        words.addWidget(_caption(t("New here?")))
        words.addWidget(_title(t("Design it on screen. Solder it from the guide."), theme.TITLE_PX + 4))
        lead = QLabel(
            t(
                "Draw the circuit. The app picks a board you can buy, lays the parts out "
                "and wires them, then writes the soldering steps for you."
            )
        )
        lead.setWordWrap(True)
        theme.size(lead, theme.LEAD_PX)
        theme.tone(lead, "secondary")
        words.addWidget(lead)
        self.walkthrough_card = _clear(QWidget())
        tour = QVBoxLayout(self.walkthrough_card)
        tour.setContentsMargins(0, theme.SPACE["md"], 0, 0)
        tour.setSpacing(theme.SPACE["xs"])
        tour.addWidget(QLabel(f"<b>{html.escape(t('Take the 1-minute tour'))}</b>"))
        body = QLabel(
            t(
                "Opens a circuit that is already drawn and walks through it: board, "
                "placement, wiring, checks, guide."
            )
        )
        body.setWordWrap(True)
        theme.tone(body, "secondary")
        tour.addWidget(body)
        tour.addSpacing(theme.SPACE["sm"])
        self.walkthrough_button = QPushButton(t("Start the Tour"))
        theme.variant(self.walkthrough_button, "primary")
        self.walkthrough_button.clicked.connect(lambda _checked=False: self.startTour.emit())
        tour.addWidget(self.walkthrough_button, 0, Qt.AlignmentFlag.AlignLeft)
        words.addWidget(self.walkthrough_card)
        words.addStretch(1)
        if not self._has_walkthrough:
            # The tour runs on that example, and this copy has none.
            self.walkthrough_card.hide()
            self.walkthrough_picture.hide()
        return card

    def _update_card(self) -> QFrame:
        """A newer release exists: what it is, what changed, and the one button that acts."""
        card = QFrame()
        card.setObjectName("homeUpdate")
        row = QHBoxLayout(card)
        row.setContentsMargins(theme.SPACE["lg"], theme.SPACE["md"], theme.SPACE["md"], theme.SPACE["md"])
        row.setSpacing(theme.SPACE["md"])
        words = QVBoxLayout()
        words.setSpacing(theme.SPACE["2xs"])
        self.update_headline = QLabel()
        self.update_headline.setTextFormat(Qt.TextFormat.RichText)
        self.update_detail = QLabel()
        # The summary comes out of release notes off the network: text, never markup, and
        # wrapped so a long line cannot widen Home's column.
        self.update_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.update_detail.setWordWrap(True)
        theme.tone(self.update_detail, "secondary")
        # Where the download or the install stands, between the headline and the detail.
        # Words the strip says, so plain text like the summary.
        self.update_status = QLabel()
        self.update_status.setTextFormat(Qt.TextFormat.PlainText)
        self.update_status.setWordWrap(True)
        self.update_status.hide()
        self.update_progress = QProgressBar()
        self.update_progress.setTextVisible(False)
        self.update_progress.setFixedWidth(320)
        self.update_progress.hide()
        words.addWidget(self.update_headline)
        words.addWidget(self.update_status)
        words.addWidget(self.update_detail)
        # ALIGNED, and that is what keeps the column wide: a widget with a maximum width
        # caps the whole column of a vertical layout at it, and the buttons beside it took
        # the rest of a 1920 px card -- What Changed and Cancel each 490 px wide.
        words.addWidget(self.update_progress, 0, Qt.AlignmentFlag.AlignLeft)
        row.addLayout(words, 1)
        notes = QPushButton(t("What Changed"))
        notes.setToolTip(t("Read what this release changes."))
        notes.clicked.connect(self.updateNotesRequested)
        row.addWidget(notes)
        self.update_reveal = QPushButton(t("Show the File"))
        self.update_reveal.setToolTip(t("Open the folder the installer was saved in."))
        self.update_reveal.clicked.connect(self.updateRevealRequested)
        self.update_reveal.hide()
        row.addWidget(self.update_reveal)
        self.update_cancel = QPushButton(t("Cancel"))
        self.update_cancel.clicked.connect(self.updateCancelRequested)
        self.update_cancel.hide()
        row.addWidget(self.update_cancel)
        self.update_action = QPushButton()
        theme.variant(self.update_action, "primary")
        self.update_action.clicked.connect(self.updateActionRequested)
        row.addWidget(self.update_action)
        card.hide()
        return card

    def _last_card(self) -> QFrame:
        """The board opened last: its picture, its name, when it was saved and where, the
        six steps as one line, the next thing to do, and Continue. Empty until
        ``set_last``."""
        card, self.last_picture, words = self._banner("homeLast")
        self.last_caption = _caption(t("Last opened"))
        words.addWidget(self.last_caption)
        self.last_name = QLabel()
        self.last_folder = QLabel()
        self.last_folder.setTextFormat(Qt.TextFormat.PlainText)
        theme.tone(self.last_folder, "secondary")
        self.last_steps = _clear(QWidget())
        self.last_steps.setObjectName("homeLastSteps")
        self._last_steps_row = QHBoxLayout(self.last_steps)
        self._last_steps_row.setContentsMargins(0, theme.SPACE["sm"], 0, theme.SPACE["xs"])
        self._last_steps_row.setSpacing(theme.SPACE["xs"])
        self.last_hint = QLabel()
        self.last_hint.setWordWrap(True)
        theme.tone(self.last_hint, "secondary")
        self.continue_button = QPushButton(t("Continue"))
        theme.variant(self.continue_button, "primary")
        self.continue_button.clicked.connect(self._continue)
        for widget in (self.last_name, self.last_folder, self.last_steps, self.last_hint):
            words.addWidget(widget)
        words.addSpacing(theme.SPACE["sm"])
        words.addWidget(self.continue_button, 0, Qt.AlignmentFlag.AlignLeft)
        words.addStretch(1)
        card.hide()
        return card

    def _continue(self) -> None:
        if self._last is None:
            return
        if self._last.open:
            self.resumeBoard.emit()
        elif self._last.path is not None:
            self.openRecent.emit(str(self._last.path))

    def _shown_recent(self) -> list[str]:
        return [
            entry for entry in self._recent
            if self._last is None or Path(entry) != self._last.path
        ]

    def _fill_recent(self) -> None:
        """The row of boards, less the one the banner is about: up to a row of them, and
        Show All for the rest. With nothing left in it, it goes, and its place in the
        sidebar with it."""
        shown = self._shown_recent()
        kept = {card.path: card for card in self.recent_cards}
        self.recent_cards = []
        for card in kept.values():
            self.recent_grid.removeWidget(card)
        for entry in shown:
            if Path(entry) in kept:
                card = kept.pop(Path(entry))
            else:
                card = RecentCard(Path(entry))
                card.clicked.connect(lambda _checked=False, p=entry: self.openRecent.emit(p))
            self.recent_cards.append(card)
        for gone in kept.values():
            self._to_draw = [entry for entry in self._to_draw if entry[0] is not gone.picture]
            gone.deleteLater()
        for index, card in enumerate(self.recent_cards):
            self.recent_grid.addWidget(card, index // COLUMNS, index % COLUMNS)
            card.setVisible(self._showing_all_recent or index < COLUMNS)
        self._pad_row(self.recent_grid, len(self.recent_cards))
        self.show_all_recent.setVisible(
            not self._showing_all_recent and len(self.recent_cards) > COLUMNS
        )
        self.returning.setVisible(bool(self.recent_cards))
        self.nav_recent.setVisible(bool(self.recent_cards))
        self._chain_focus()

    def _pad_row(self, grid: QGridLayout, count: int) -> None:
        """Every column of a grid as wide as the others, however few cards are in it: an
        empty column has no gap beside it, so a row of one card would be a quarter of the
        page and not a quarter less the gaps. The empty places hold nothing visible."""
        for gone in self._placeholders.pop(id(grid), []):
            grid.removeWidget(gone)
            gone.deleteLater()
        kept = []
        for column in range(count, COLUMNS):
            place = _clear(QWidget())
            grid.addWidget(place, 0, column)
            kept.append(place)
        self._placeholders[id(grid)] = kept
        for column in range(COLUMNS):
            grid.setColumnStretch(column, 1)

    def _lay_out_cards(self) -> None:
        shown = len(self.cards) if self._showing_all else COLUMNS
        for index, card in enumerate(self.cards):
            card.setVisible(index < shown)
        self._pad_row(self.grid, len(self.cards))
        self.show_all.setVisible(len(self.cards) > shown)

    def _reveal_all(self) -> None:
        self._showing_all = True
        self._lay_out_cards()

    def _reveal_all_recent(self) -> None:
        self._showing_all_recent = True
        self._fill_recent()

    def _chain_focus(self) -> None:
        """Tab goes down the sidebar, then the page from the top: Continue, the boards, the
        examples -- not in the order the cards happened to be made."""
        chain: list[QWidget] = [
            self.new_button, self.open_button, self.nav_home, self.nav_recent,
            self.nav_examples, self.nav_tour, self.show_at_start, self.update_action,
            self.walkthrough_button, self.continue_button, *self.recent_cards,
            self.show_all_recent, *self.cards, self.show_all,
        ]
        for before, after in itertools.pairwise(chain):
            QWidget.setTabOrder(before, after)

    def _fit_to_width(self, width: int) -> None:
        """A narrower sidebar and margins below ``NARROW_BELOW``; a column that stops at
        ``CONTENT_MAX`` and centres above it."""
        narrow = width < NARROW_BELOW
        self.side.setFixedWidth(SIDE_NARROW if narrow else SIDE_WIDE)
        margin = theme.SPACE["2xl"] * (1 if narrow else 2) + (theme.SPACE["sm"] if narrow else 0)
        self._column_layout.setContentsMargins(margin, theme.SPACE["2xl"] + theme.SPACE["sm"], margin, theme.SPACE["2xl"])
        self.column.setMaximumWidth(CONTENT_MAX + 2 * margin)

    def _sections(self) -> list[tuple[QPushButton, int]]:
        """The sidebar's places and where each starts on the page, top first."""
        found = [(self.nav_home, 0)]
        for button, widget in (
            (self.nav_recent, self.returning),
            (self.nav_examples, self.examples_section),
        ):
            if not widget.isHidden():
                found.append((button, widget.mapTo(self.page, QPoint(0, 0)).y()))
        return found

    def _go_to(self, button: QPushButton) -> None:
        """Scroll to a place; it stays lit even where the page is too short to bring it to
        the top, until the page is scrolled by hand."""
        button.setChecked(True)
        target = next((top for place, top in self._sections() if place is button), 0)
        margin = theme.SPACE["2xl"]
        self._scrolling_to = True
        try:
            self.scroller.verticalScrollBar().setValue(max(0, target - margin))
        finally:
            self._scrolling_to = False

    def _follow_scroll(self, value: int) -> None:
        """The place the page is scrolled to is the one lit: the last whose start has
        reached the top of the page (give or take its margin), Home at the very top, and the
        last place of all at the very bottom, where a short one never reaches the top."""
        if self._scrolling_to:
            return
        sections = self._sections()
        bar = self.scroller.verticalScrollBar()
        if bar.maximum() > 0 and value >= bar.maximum():
            lit = sections[-1][0]
        else:
            line = value + 2 * theme.SPACE["2xl"]
            lit = [button for button, top in sections if top <= line][-1]
        lit.setChecked(True)

    def _draw_pictures(self) -> None:
        """Queue the pictures still not drawn -- the tour's circuit, the boards, the
        examples, top first -- and paint them one per turn once Home's first frame is up."""
        pending = bool(self._to_draw)
        queue: list[tuple[FramedPicture, Path, QSize]] = []
        if self._has_walkthrough and not self.first_run.isHidden():
            tour = next((e.path for e in self._examples if e.path.stem == WALKTHROUGH), None)
            if tour is not None and self.walkthrough_picture.pixmap().isNull():
                queue.append((self.walkthrough_picture, tour, LAST_PICTURE))
        cards: list[_Card] = [*self.recent_cards, *self.cards]
        queue += [
            (card.picture, card.path, PICTURE) for card in cards if card.picture.pixmap().isNull()
        ]
        self._to_draw = queue
        # One chain of turns at a time: a second would draw the same picture twice.
        if self._to_draw and not pending:
            self.after_first_frame(self._draw_next)

    def _draw_next(self) -> None:
        if not self._to_draw:
            return
        picture, path, size = self._to_draw.pop(0)
        drawn = self._picture_of(path, size)
        if drawn is not None:
            pixmap, on_paper = drawn
            picture.set_picture(pixmap, on_paper=on_paper)
        if self._to_draw:
            QTimer.singleShot(0, self, self._draw_next)

    def _picture(self, path: Path) -> QPixmap | None:
        """The board as the window will draw it, or -- for a circuit with nothing placed --
        its sheet. None when the file cannot be read: the card keeps its words."""
        drawn = self._picture_of(path)
        return drawn[0] if drawn is not None else None

    def _picture_of(self, path: Path, size: QSize = PICTURE) -> tuple[QPixmap, bool] | None:
        """``_picture``, and whether it is a sheet rather than a board."""
        try:
            result = persist.deserialize_document(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        if not result.ok:
            return None
        try:
            return self._picture_of_document(result.document, size)
        except Exception:  # a board Home only pictures is never an error on Home
            return None

    def _picture_of_document(
        self, document: PerfDocument, size: QSize = PICTURE
    ) -> tuple[QPixmap, bool] | None:
        """A document's picture at ``size``: every board in a row, the board, or -- with
        nothing placed -- the sheet (the bool)."""
        if len(board_ids(document)) > 1:
            return _boards_side_by_side(document, self._lookup, size), False
        if document.components:
            return render_board(document, self._lookup, size), False
        sheet = _sheet_picture(document, self._lookup, size)
        return (sheet, True) if sheet is not None else None

