"""The board designer: a real board family to start from, tweaked, seen as it will be.

STARTS FROM A BOARD SOMEBODY CAN BUY. Board Setup asked for a grid, a pitch and a border in
the abstract; the boards on the bench are products -- a green double-sided board with edge
pads and corner holes, a brown phenolic one with bare copper -- and a board is far quicker
to describe as "that one, but 6 x 8" than from nothing. So the families come first
(``boardfamily.FAMILIES``, parts' catalogue, and the user's own saved ones), and every
setting tweaks one: its size, its grid and pads, its edge pads, its corner holes, its
legend and text, its colour. The board beside the settings is drawn as each one changes,
by the board view itself (``boardpreview.render_board``), so the picture cannot disagree
with the board Use This Board gives.

THREE COLUMNS, chosen from two rendered candidates: the families on the left, the board in
the middle, every setting on the right at once -- a designer is tweak and look, and every
setting and its effect are on the screen together.

The engine decides; the dialog asks. ``boardfamily.family_problem`` is the one refusal, and
it is said under the field it names, which also holds Use This Board. Applying is the
window's (``apply``): one ``board.applyPreset``, one undo step, refused in words when a part
already on the board would be stranded.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio.boardfamily import (
    FAMILIES,
    FAMILY_BOARD_TYPES,
    FINISHES,
    LETTER_EDGES,
    MASKS,
    NUMBER_EDGES,
    STRIP_EDGES,
    STRIP_SHAPES,
    BoardDesign,
    BoardFamily,
    BoardSize,
    BreadboardSpec,
    CornerHoles,
    EdgeStrip,
    FamilyBoardType,
    Legend,
    board_for,
    family_from_json,
    family_problem,
    family_to_json,
    pattern_sizes,
    size_for_grid,
    size_for_mm,
)
from perfboard_studio.breadboard import (
    SOLDERABLE_BORDER_X_MM,
    SOLDERABLE_BORDER_Y_MM,
    STANDARD_CHANNEL,
    channel_of,
    size_of,
)
from perfboard_studio.commands import create_empty_document
from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.geometry import (
    MAX_LEGEND_DIGITS,
    corner_mounting_holes,
    legend_runs_text,
    parse_legend_runs,
)
from perfboard_studio.model import (
    AxisLegend,
    Board,
    BoardSide,
    DocumentMeta,
    EdgeConnector,
    MountingHole,
    PerfDocument,
)

from . import theme
from .boardpreview import render_board
from .engine_text import say
from .i18n import t

#: Where the user's own families are kept: in the settings, as the board colour is -- a
#: board somebody buys is not part of any one document.
USER_FAMILIES_KEY = "boardFamilies/user"

PREVIEW = QSize(560, 520)
THUMB = QSize(180, 120)

#: The kinds whose pattern is their size: a breadboard is sold as 830, 400 or 170 points
#: and never cut to measure, so its grid, pads and drill are the kind's, not a setting.
PATTERN_KINDS = frozenset({"breadboard", "solderable-breadboard"})

#: How many columns of a "-flex" body keep the ordinary channel: 39 of the 63, measured on
#: the bodies Board Setup offered by name -- a board somebody built is found in a list, not
#: in a spin box, and the spin box beside it is for a body of somebody's own.
FLEX_NARROW_COLS = 39


#: The id of the board that is open, offered first when no catalogue family makes it.
THIS_BOARD = "this-board"

Features = tuple[tuple[EdgeConnector, ...], tuple[MountingHole, ...]]


def family_name(family: BoardFamily) -> str:
    """A family in the window's language: a catalogue family by its id, a user's own by the
    name they gave it."""
    if family.user:
        return family.name
    return {
        THIS_BOARD: t("This board"),
        "double-sided-fr4": t("Green double-sided (FR-4, tinned)"),
        "single-sided-phenolic": t("Phenolic single-sided (bare copper)"),
        "breadboard": t("Solderless breadboard"),
        "breadboard-wide": t("Solderless breadboard, wide channel (ESP32 / modules)"),
        "solderable-breadboard": t("Solderable breadboard"),
    }.get(family.id, family.name)


def _words() -> dict[str, dict[str, str]]:
    """Each vocabulary's ids in words, asked when shown, in the window's language."""
    return {
        "type": {
            "pad-per-hole": t("Pad per hole"),
            "stripboard": t("Stripboard"),
            "breadboard": t("Solderless breadboard"),
            "solderable-breadboard": t("Solderable breadboard"),
        },
        # A breadboard's size by what it is called, and its channel by what straddles it:
        # Board Setup's own words, so a board chosen there is found here by the same name.
        "pattern_size": {
            "830": t("Full size · 830 points · 63 columns"),
            "400": t("Half size · 400 points · 30 columns"),
            "170": t("Mini · 170 points · 17 columns, no rails"),
        },
        "channel": {
            "300": t("300 mil · standard, a DIP straddles it"),
            "600": t("600 mil · Arduino Nano"),
            "700": t("700 mil · Raspberry Pi Pico"),
            "900": t("900 mil · narrow ESP32 devkit"),
            "900-flex": t("900 mil flex · 300 mil for columns 1–39"),
            "1000": t("1000 mil · ESP32 devkit"),
            "1000-flex": t("1000 mil flex · 300 mil for columns 1–39"),
        },
        "material": {
            "FR4": t("FR-4 — glass epoxy, the green kind. Tolerates heat well."),
            "FR2": t("FR-2 — phenolic paper (\"pertinaks\"), the brown kind. Pads lift easily."),
            "FR1": t("FR-1 — phenolic paper, as FR-2."),
        },
        "pad_shape": {
            "round": t("Round"),
            "oblong": t("Oblong — solder bridges easily along the long axis"),
        },
        "axis": {"vertical": t("Down a column"), "horizontal": t("Along a row")},
        "edges": {"short": t("The short edges"), "long": t("The long edges")},
        "shape": {"rounded": t("Rounded"), "stadium": t("Oblong"), "square": t("Square")},
        "letters": {
            "top": t("Along the top"), "bottom": t("Along the bottom"),
            "both": t("Top and bottom"), "none": t("Not printed"),
        },
        "numbers": {
            "left": t("Down the left"), "right": t("Down the right"),
            "both": t("Down both sides"), "none": t("Not printed"),
        },
        "mask": {
            "green": t("Green"), "blue": t("Blue"), "black": t("Black"), "red": t("Red"),
            "purple": t("Purple"), "white": t("White"), "none": t("No mask"),
        },
        "finish": {
            "hasl": t("Tinned (HASL)"), "lf-hasl": t("Tinned, lead-free"),
            "bare-copper": t("Bare copper"), "enig": t("Gold (ENIG)"),
        },
    }


def load_user_families(settings: QSettings) -> list[BoardFamily]:
    stored = settings.value(USER_FAMILIES_KEY, [])
    # The INI backend hands a one-item list back as the item itself.
    if isinstance(stored, str):
        texts = [stored]
    elif isinstance(stored, (list, tuple)):
        texts = [str(item) for item in stored]
    else:
        texts = []
    found: list[BoardFamily] = []
    for text in texts:
        try:
            found.append(family_from_json(str(text)))
        except (ValueError, KeyError, TypeError):
            continue  # a family saved by a newer build, or damaged: not offered
    return found


def store_user_families(settings: QSettings, families: list[BoardFamily]) -> None:
    if families:
        settings.setValue(USER_FAMILIES_KEY, [family_to_json(f) for f in families])
    else:
        settings.remove(USER_FAMILIES_KEY)


def _face(family: BoardFamily) -> BoardSide:
    """The side a family is shown from: a single-sided board from its copper, which is where
    its rings, edge pads and letters are -- its component side is bare phenolic."""
    return "bottom" if family.single_sided else "top"


def is_pattern(family: BoardFamily) -> bool:
    return family.type in PATTERN_KINDS


def _corner_holes_of(board: Board, holes: tuple[MountingHole, ...]) -> CornerHoles | None:
    """The corner holes ``holes`` are, when they are exactly a family's: one in each corner,
    where ``corner_mounting_holes`` puts them."""
    if not holes:
        return None
    first = holes[0]
    if corner_mounting_holes(board, first.diameter, first.head_diameter) != holes:
        return None
    return CornerHoles(diameter_mm=first.diameter, head_mm=first.head_diameter)


def _strips_of(connectors: tuple[EdgeConnector, ...]) -> tuple[EdgeStrip, ...]:
    """The finger strips ``connectors`` could be, to be tried: two alike, outside the grid.
    Which edges they run down is tried both ways rather than worked out."""
    if len(connectors) != 2:
        return ()
    first, second = connectors
    alike = ("start", "finger_width", "finger_length", "inset_mm", "face", "shape")
    if not (first.outside and second.outside) or any(
        getattr(first, name) != getattr(second, name) for name in alike
    ):
        return ()
    return tuple(
        EdgeStrip(
            edges=edges,
            shape=first.shape,
            width_mm=first.finger_width,
            length_mm=first.finger_length,
            inset_mm=first.inset_mm,
            skip_ends=first.start,
            face=first.face,
        )
        for edges in STRIP_EDGES
    )


def this_board(board: Board, features: Features) -> tuple[BoardFamily, BoardSize | None, Features]:
    """The board that is open as a family of one: (the family, its size, what it has that no
    family says).

    Board Setup opened on the board it was given; the designer does too, and "Use This
    Board" on it unchanged must change nothing. So its strips and corner holes are said as
    the family's when they are exactly what a family would make -- and when they are not
    (a connector or a hole added by hand), the family says none and they are kept as they
    are, beside whatever the family is changed to (``BoardDesigner._design_of``).
    """
    connectors, holes = features
    corner = _corner_holes_of(board, holes)
    # A type no family says -- "plain", which the original engine had -- is said as pad
    # per hole here and put back by ``_design_of``.
    kind: FamilyBoardType = board.type if board.type in FAMILY_BOARD_TYPES else "pad-per-hole"
    if kind in PATTERN_KINDS:
        spec = (
            BreadboardSpec(
                channel_mils=channel_of(board) * 100,
                narrow_channel_cols=board.narrow_channel_cols,
            )
            if kind == "breadboard"
            else BreadboardSpec(
                border_x_mm=None if board.border_x_mm == SOLDERABLE_BORDER_X_MM else board.border_x_mm,
                border_y_mm=None if board.border_y_mm == SOLDERABLE_BORDER_Y_MM else board.border_y_mm,
            )
        )
        name = size_of(board)
        # In no size it is sold in, it is offered none: kept as it is (``_design_of``).
        sizes = pattern_sizes(kind, spec) if name is not None else ()
        family = BoardFamily(
            id=THIS_BOARD, name="This board", type=kind, breadboard=spec,
            mask=board.mask, finish=board.finish, corner_holes=corner, sizes=sizes,
        )
        size = next((each for each in sizes if each.name == name), None)
    else:
        width = board.cols * board.pitch + 2 * board.border_x_mm
        height = board.rows * board.pitch + 2 * board.border_y_mm
        size = BoardSize(
            f"{round(width / 10, 1):g} x {round(height / 10, 1):g} cm",
            width, height, board.cols, board.rows,
        )
        labels = board.labels
        legend = None if labels is None else Legend(
            letter_edges=labels.letter_edges or ("both" if labels.all_edges else "top"),
            number_edges=labels.number_edges or ("both" if labels.all_edges else "left"),
            row_digits=labels.row_digits,
            face=labels.face,
            columns=labels.columns,
            rows=labels.rows,
        )
        family = BoardFamily(
            id=THIS_BOARD, name="This board", material=board.material,
            single_sided=board.single_sided, type=kind, strip_axis=board.strip_axis,
            mask=board.mask, finish=board.finish, pitch_mm=board.pitch,
            thickness_mm=board.thickness, pad_diameter_mm=board.pad_diameter,
            drill_mm=board.drill_diameter, pad_shape=board.pad_shape,
            pad_length_mm=board.pad_length, pad_axis=board.pad_axis, corner_holes=corner,
            legend=legend, sizes=(size,),
            # Said as it reads: a brace in it would be taken for the size's.
            printed=tuple(
                dataclasses.replace(line, text=line.text.replace("{", "{{").replace("}", "}}"))
                for line in board.printed
            ),
        )
        for strip in _strips_of(connectors):
            with_strip = dataclasses.replace(family, strip=strip)
            if board_for(with_strip, size, board).edge_connectors == connectors:
                family = with_strip
                break
    if size is not None and _made(family, size, board) == (connectors, holes):
        return family, size, ((), ())
    return dataclasses.replace(family, strip=None, corner_holes=None), size, features


def _made(family: BoardFamily, size: BoardSize, board: Board) -> Features:
    design = board_for(family, size, board)
    return design.edge_connectors, design.mounting_holes


def size_name(size: BoardSize, family: BoardFamily) -> str:
    """A size as the picker says it: its name and its grid, because a name repeats across
    the variants of one size -- 7 x 9 cm is sold as 31 x 26 and as 35 x 27. A size sold
    without the family's edge pads says so; a family with none says nothing. A breadboard
    is said by its points, as it is sold."""
    if is_pattern(family):
        return _words()["pattern_size"].get(size.name, size.name)
    extra = "" if size.strip or family.strip is None else f", {t('no edge connector')}"
    return f"{size.name}  ({size.cols} × {size.rows}{extra})"


def _first_size(family: BoardFamily) -> BoardSize | None:
    """The size a family opens on: its first, and a breadboard's biggest -- the full-size
    830 is the one on most benches, and the catalogue lists them smallest first."""
    if not family.sizes:
        return None
    if is_pattern(family):
        return max(family.sizes, key=lambda size: int(size.name) if size.name.isdigit() else 0)
    return family.sizes[0]


def _listed(family: BoardFamily) -> tuple[BoardSize, ...]:
    """A family's sizes in the order the picker lists them: a breadboard's biggest first, as
    Board Setup listed them."""
    if is_pattern(family):
        return tuple(sorted(
            family.sizes, key=lambda size: -int(size.name) if size.name.isdigit() else 0))
    return family.sizes


def _combo(words: dict[str, str], ids: tuple[str, ...]) -> QComboBox:
    """A choice in words, as wide as the column lets it be: a material's whole sentence made
    the settings wider than their column, and the right edge of every field was cut off."""
    combo = QComboBox()
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(10)
    for value in ids:
        combo.addItem(words.get(value, value), value)
        combo.setItemData(combo.count() - 1, words.get(value, value), Qt.ItemDataRole.ToolTipRole)
    return combo


def _mm(value: float, top: float = 500.0, decimals: int = 2) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0.0, top)
    box.setDecimals(decimals)
    box.setSuffix(" mm")
    box.setValue(value)
    return box


@dataclasses.dataclass(frozen=True)
class LegendAxisFields:
    """The fields that say how one axis of a legend is printed."""

    row: QWidget
    runs: QLineEdit
    every: QSpinBox
    digits: QSpinBox


class BoardDesigner(QDialog):
    """Families | the board | every setting. ``apply`` commits a design and answers why it
    was refused, or None; ``saved`` holds the user's families, kept by the window."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        base: Board,
        lookup: FootprintLookup,
        saved: list[BoardFamily],
        apply: Callable[[BoardDesign], str | None],
        features: Features = ((), ()),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Design the Board"))
        self.resize(1180, 820)
        self._base = base
        self._lookup = lookup
        self._apply = apply
        self.saved = list(saved)
        self._words = _words()
        self._loading = False
        #: The printed words as they read on the size shown: typed over, they replace the
        #: family's template; left alone, the template stays and follows the size.
        self._resolved = ""
        self._family: BoardFamily = FAMILIES[0]
        self._size: BoardSize = FAMILIES[0].sizes[0]
        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.setInterval(0)
        self._redraw.timeout.connect(self._show)

        root = QVBoxLayout(self)
        columns = QHBoxLayout()
        columns.setSpacing(theme.SPACE["xl"])

        # -- the families
        left = QVBoxLayout()
        left.addWidget(self._heading(t("Board families")))
        self.families = QListWidget()
        self.families.setFixedWidth(240)
        self.families.setIconSize(THUMB)
        self.families.setWordWrap(True)
        # The name UNDER its picture: beside a picture 180 px wide, "Green double-sided
        # (FR-4, tinned)" was four lines and cut.
        self.families.setViewMode(QListWidget.ViewMode.IconMode)
        self.families.setFlow(QListWidget.Flow.TopToBottom)
        self.families.setWrapping(False)
        self.families.setMovement(QListWidget.Movement.Static)
        self.families.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.families.setGridSize(QSize(220, THUMB.height() + 52))
        self.families.setSpacing(theme.SPACE["sm"])
        self.families.currentRowChanged.connect(self._on_family_chosen)
        left.addWidget(self.families, 1)
        columns.addLayout(left)

        # -- the board
        middle = QVBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText(t("A name for this board, to save it as your own"))
        middle.addWidget(self.name)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(QSize(320, 240))
        middle.addWidget(self.preview, 1)
        columns.addLayout(middle, 1)

        # -- every setting
        settings = QWidget()
        self._settings = QVBoxLayout(settings)
        self._settings.setContentsMargins(0, 0, theme.SPACE["md"], 0)
        self._problems: dict[str, QLabel] = {}
        self._rows: dict[str, tuple[QFormLayout, QWidget]] = {}
        self._sections: dict[str, tuple[QLabel, QFormLayout]] = {}
        self._build_settings()
        self._settings.addStretch(1)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(settings)
        # As wide as the settings need, never narrower: a fixed 380 px cut every field's right
        # edge off the moment a language or a font made one row wider.
        bar = scroller.verticalScrollBar().sizeHint().width()
        scroller.setMinimumWidth(max(380, settings.minimumSizeHint().width() + bar + 4))
        self._scroller = scroller
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        columns.addWidget(scroller)
        root.addLayout(columns, 1)

        # -- what to do with it
        self.refusal = QLabel()
        self.refusal.setWordWrap(True)
        theme.tone(self.refusal, "danger")
        self.refusal.hide()
        root.addWidget(self.refusal)
        buttons = QHBoxLayout()
        self.save = QPushButton(t("Save as My Board…"))
        self.save.setAutoDefault(False)
        self.save.clicked.connect(self._save_as_mine)
        buttons.addWidget(self.save)
        buttons.addStretch(1)
        cancel = QPushButton(t("Cancel"))
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.use = QPushButton(t("Use This Board"))
        theme.variant(self.use, "primary")
        self.use.clicked.connect(self._use)
        buttons.addWidget(self.use)
        root.addLayout(buttons)

        # Open on the board that is open: the catalogue family and size that make it
        # exactly, or else the board itself, first in the list as "This board".
        self._this: BoardFamily | None = None
        self._kept: Features = ((), ())
        row, size = self._opening(base, features)
        self._fill_families()
        self.families.setCurrentRow(row)
        if size is not None:
            listed = _listed(self._current_family())
            index = next(
                (i for i, each in enumerate(listed)
                 if each == size or (is_pattern(self._family) and each.name == size.name)),
                None,
            )
            if index is not None:
                self._on_stock_size(index)

    def _opening(self, board: Board, features: Features) -> tuple[int, BoardSize | None]:
        current = BoardDesign(board=board, edge_connectors=features[0], mounting_holes=features[1])
        for row, family in enumerate((*FAMILIES, *self.saved)):
            for each in family.sizes:
                if board_for(family, each, board) == current:
                    return row, each
        this, size, kept = this_board(board, features)
        self._this, self._kept = this, kept
        return 0, size

    def _everything(self) -> tuple[BoardFamily, ...]:
        """The families in the order they are listed: the board that is open first, when no
        catalogue family makes it, then the catalogue, then the user's own."""
        return (*((self._this,) if self._this is not None else ()), *FAMILIES, *self.saved)

    # -- building --

    @staticmethod
    def _heading(text: str) -> QLabel:
        shown = QLabel(theme.heading(text))
        shown.setTextFormat(Qt.TextFormat.RichText)
        return shown

    def _row(
        self, form: QFormLayout, label: str, field: QWidget, path: str = "", key: str = ""
    ) -> None:
        """A field, and under it the line that says why the family was refused there. The
        row is kept by ``path`` (or ``key`` when nothing is refused there) so it can be
        shown only where it means something."""
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(field)
        if path or key:
            self._rows[path or key] = (form, holder)
        if path:
            problem = QLabel()
            problem.setWordWrap(True)
            theme.tone(problem, "danger")
            problem.hide()
            column.addWidget(problem)
            self._problems[path] = problem
        form.addRow(label, holder)

    def _section(self, title: str, key: str) -> QFormLayout:
        heading = self._heading(title)
        self._settings.addWidget(heading)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._settings.addLayout(form)
        self._sections[key] = (heading, form)
        return form

    def _build_settings(self) -> None:
        w = self._words
        changed = self._changed

        size = self._section(t("Size"), "size")
        self.stock = QComboBox()
        self.stock.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.stock.setMinimumContentsLength(10)
        self.stock.activated.connect(self._on_stock_size)
        self._row(size, t("Stock size"), self.stock)
        grid = QWidget()
        grid_row = QHBoxLayout(grid)
        grid_row.setContentsMargins(0, 0, 0, 0)
        self.cols, self.rows = QSpinBox(), QSpinBox()
        for count in (self.cols, self.rows):
            count.setRange(2, 300)
            count.valueChanged.connect(self._on_grid)
        grid_row.addWidget(self.cols)
        grid_row.addWidget(QLabel("×"))
        grid_row.addWidget(self.rows)
        self._row(size, t("Holes"), grid, key="grid")
        outline = QWidget()
        outline_row = QHBoxLayout(outline)
        outline_row.setContentsMargins(0, 0, 0, 0)
        self.width_mm, self.height_mm = _mm(70.0, 1000.0, 1), _mm(50.0, 1000.0, 1)
        for box in (self.width_mm, self.height_mm):
            box.editingFinished.connect(self._on_outline)
        outline_row.addWidget(self.width_mm)
        outline_row.addWidget(QLabel("×"))
        outline_row.addWidget(self.height_mm)
        self._row(size, t("Size in mm"), outline, "sizes")
        # A breadboard's channel, and a wide one's narrow part (lhm0's "flex" bodies keep
        # the ordinary channel for their first columns, so a DIP still fits beside the
        # module); a solderable one's border, the one thing its makers differ in.
        self.channel = _combo(w["channel"], tuple(w["channel"]))
        self.channel.activated.connect(self._on_channel)
        self._row(size, t("Channel"), self.channel, "breadboard.channel_mils")
        self.narrow = QSpinBox()
        self.narrow.setRange(0, 400)
        self.narrow.setSpecialValueText(t("Wide all the way"))
        self.narrow.setSuffix(t(" columns"))
        self.narrow.setToolTip(
            t(
                "How many columns, from column 1, keep the ordinary 0.3 inch channel with "
                "their strips moved in to it, so a DIP still fits beside the module."
            )
        )
        self.narrow.valueChanged.connect(self._on_pattern)
        self._row(size, t("Narrow part"), self.narrow, "breadboard.narrow_channel_cols")
        self.border_x = _mm(SOLDERABLE_BORDER_X_MM, 30.0, 1)
        self.border_y = _mm(SOLDERABLE_BORDER_Y_MM, 30.0, 1)
        for box, label, path in (
            (self.border_x, t("Border, left and right"), "breadboard.border_x_mm"),
            (self.border_y, t("Border, top and bottom"), "breadboard.border_y_mm"),
        ):
            box.setSingleStep(0.1)
            box.editingFinished.connect(changed)
            self._row(size, label, box, path)

        pads = self._section(t("Grid and pads"), "grid")
        self.type = _combo(
            w["type"], tuple(kind for kind in FAMILY_BOARD_TYPES if kind not in PATTERN_KINDS)
        )
        self.type.activated.connect(self._on_kind)
        self._row(pads, t("Kind"), self.type, "type")
        self.strip_axis = _combo(w["axis"], ("horizontal", "vertical"))
        self.strip_axis.activated.connect(changed)
        self._row(pads, t("Strips run"), self.strip_axis, "strip_axis")
        self.material = _combo(w["material"], ("FR4", "FR2", "FR1"))
        self.material.activated.connect(changed)
        self._row(pads, t("Material"), self.material, "material")
        self.pitch = _mm(2.54, 10.0)
        self.pad = _mm(1.8, 10.0)
        self.drill = _mm(1.0, 10.0)
        for box, label, path in ((self.pitch, t("Pitch"), "pitch_mm"),
                                 (self.pad, t("Pad diameter"), "pad_diameter_mm"),
                                 (self.drill, t("Drill"), "drill_mm")):
            box.editingFinished.connect(changed)
            self._row(pads, label, box, path)
        self.pad_shape = _combo(w["pad_shape"], ("round", "oblong"))
        self.pad_shape.activated.connect(self._on_kind)
        self._row(pads, t("Pad shape"), self.pad_shape, "pad_shape")
        self.pad_length = _mm(2.4, 10.0)
        self.pad_length.editingFinished.connect(changed)
        self._row(pads, t("Pad length"), self.pad_length, "pad_length_mm")
        self.pad_axis = _combo(w["axis"], ("vertical", "horizontal"))
        self.pad_axis.activated.connect(changed)
        self._row(pads, t("Long axis"), self.pad_axis, "pad_axis")

        edge = self._section(t("Edge connector"), "edge")
        self.strip_on = QCheckBox(t("Edge connector along two edges"))
        self.strip_on.toggled.connect(changed)
        edge.addRow(self.strip_on)
        self.strip_edges = _combo(w["edges"], STRIP_EDGES)
        self.strip_shape = _combo(w["shape"], STRIP_SHAPES)
        for combo in (self.strip_edges, self.strip_shape):
            combo.activated.connect(changed)
        self._row(edge, t("Edges"), self.strip_edges, "strip.edges")
        self._row(edge, t("Shape"), self.strip_shape, "strip.shape")
        self.strip_width = _mm(1.6, 10.0)
        self.strip_width.editingFinished.connect(changed)
        self._row(edge, t("Width"), self.strip_width, "strip.width_mm")

        holes = self._section(t("Mounting holes"), "holes")
        self.holes_on = QCheckBox(t("A hole in each corner"))
        self.holes_on.toggled.connect(changed)
        holes.addRow(self.holes_on)
        self.hole_diameter = _mm(2.2, 10.0)
        self.hole_head = _mm(4.4, 20.0)
        for box in (self.hole_diameter, self.hole_head):
            box.editingFinished.connect(changed)
        self._row(holes, t("Diameter"), self.hole_diameter, "corner_holes.diameter_mm")
        self._row(holes, t("Screw head"), self.hole_head, "corner_holes.head_mm")

        legend = self._section(t("Legend and text"), "legend")
        self.letters = _combo(w["letters"], LETTER_EDGES)
        self.numbers = _combo(w["numbers"], NUMBER_EDGES)
        for combo in (self.letters, self.numbers):
            combo.activated.connect(self._on_kind)
        self._row(legend, t("Letters"), self.letters, "legend.letter_edges")
        self._row(legend, t("Numbers"), self.numbers, "legend.number_edges")
        self.row_digits = QSpinBox()
        self.row_digits.setRange(1, 4)
        self.row_digits.setToolTip(t('2 prints row 7 as "07", the way most such boards do.'))
        self.row_digits.valueChanged.connect(changed)
        self._row(legend, t("Row digits"), self.row_digits, "legend.row_digits")
        # A BOARD THAT COUNTS ITS OWN WAY (#13): A..Z and then A..P again, letters down the
        # side, numbers with every fifth marked. Empty prints the addresses. What is typed
        # is read by the engine (``parse_legend_runs``) and refused in its words.
        self.legend_columns = self._legend_axis(
            "A-Z, A-P",
            t(
                "What the board prints along its columns when that is not the addresses: "
                "runs of letters or of numbers from the first hole on. A-Z, A-P is A to Z "
                "and then A to P again. Left empty, the board prints the addresses."
            ),
        )
        self._row(legend, t("Columns printed as"), self.legend_columns.row, "legend.columns")
        self.legend_rows = self._legend_axis(
            "A-Z, 1-4",
            t(
                "What the board prints down its rows when that is not the addresses: runs "
                "of letters or of numbers from the first hole on. A-Z, 1-4 is A to Z and "
                "then 1 to 4. Left empty, the board prints the row numbers."
            ),
        )
        self._row(legend, t("Rows printed as"), self.legend_rows.row, "legend.rows")
        self.printed = QLineEdit()
        self.printed.editingFinished.connect(changed)
        self._row(legend, t("Printed on it"), self.printed, "printed")

        colour = self._section(t("Colour"), "colour")
        self.mask_kind = _combo(w["mask"], MASKS)
        self.finish = _combo(w["finish"], FINISHES)
        # First, the family's own word for itself: nothing said is the material's look --
        # green and tinned for FR-4, bare copper on phenolic -- and choosing green there
        # drew a phenolic board green.
        for combo in (self.mask_kind, self.finish):
            combo.insertItem(0, t("As the material is sold"), None)
        for combo in (self.mask_kind, self.finish):
            combo.activated.connect(changed)
        self._row(colour, t("Mask"), self.mask_kind, "mask")
        self._row(colour, t("Pad finish"), self.finish, "finish")

    def _legend_axis(self, example: str, tooltip: str) -> LegendAxisFields:
        """How one axis is printed: its runs on one line, how often and how padded under."""
        runs = QLineEdit()
        # The tool's own vocabulary, like "R1, C3, U2…": the same in every language.
        runs.setPlaceholderText(example)
        runs.setToolTip(tooltip)
        runs.editingFinished.connect(self._changed)
        runs.textChanged.connect(self._on_runs)
        every = QSpinBox()
        every.setRange(1, 20)
        every.setToolTip(
            t("Only every Nth hole carries a label: 5 is a board numbered 05, 10, 15 and so on.")
        )
        digits = QSpinBox()
        digits.setRange(1, MAX_LEGEND_DIGITS)
        digits.setToolTip(
            t("Numbers are padded to this many digits: 2 prints 5 as 05. Letters never are.")
        )
        for spin in (every, digits):
            spin.valueChanged.connect(self._changed)
        row = QWidget()
        column = QVBoxLayout(row)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(runs)
        line = QHBoxLayout()
        line.addWidget(QLabel(t("marked every")))
        line.addWidget(every)
        line.addWidget(QLabel(t("digits")))
        line.addWidget(digits)
        line.addStretch(1)
        column.addLayout(line)
        return LegendAxisFields(row, runs, every, digits)

    @staticmethod
    def _axis(fields: LegendAxisFields) -> AxisLegend | None:
        """What one axis prints, or None for the addresses -- and for text that does not
        read, which ``_show`` says under the field."""
        text = fields.runs.text().strip()
        if not text:
            return None
        try:
            runs = parse_legend_runs(text)
        except ValueError:
            return None
        return AxisLegend(runs=runs, every=fields.every.value(), digits=fields.digits.value())

    def _unreadable_runs(self) -> tuple[str, str] | None:
        """(path, why) for a run typed that does not read, while a legend is printed."""
        if is_pattern(self._family) or self._legend_off():
            return None
        for path, fields in (("legend.columns", self.legend_columns), ("legend.rows", self.legend_rows)):
            text = fields.runs.text().strip()
            if text:
                try:
                    parse_legend_runs(text)
                except ValueError as error:
                    return path, str(error)
        return None

    def _on_runs(self, *_args: object) -> None:
        """What the fields beside a run mean: nothing while it is empty, so they are greyed
        then; and Row digits pads the row NUMBERS, so it is asked only while the rows print
        them -- two "digits" for one axis left which one won to guesswork."""
        for fields in (self.legend_columns, self.legend_rows):
            typed = bool(fields.runs.text().strip())
            fields.every.setEnabled(typed)
            fields.digits.setEnabled(typed)
        self._only_what_means_something()
        self._changed()

    def _legend_off(self) -> bool:
        return (self.letters.currentData(), self.numbers.currentData()) == ("none", "none")

    def _fill_families(self) -> None:
        self.families.clear()
        for family in self._everything():
            item = QListWidgetItem(family_name(family))
            item.setToolTip(family_name(family))
            item.setIcon(self._thumb(family))
            item.setSizeHint(QSize(214, THUMB.height() + 48))
            self.families.addItem(item)

    def _thumb(self, family: BoardFamily) -> QPixmap:
        """The family's board, centred in a slot the same size for every family: drawn at
        its own shape, a breadboard sat at the top of its slot with its name far below."""
        size = _first_size(family) or self._size
        board = render_board(
            self._document(self._design_of(family, size)), self._lookup, THUMB, _face(family)
        )
        slot = QPixmap(THUMB)
        slot.fill(QColor(0, 0, 0, 0))
        painter = QPainter(slot)
        painter.drawPixmap(
            (THUMB.width() - board.width()) // 2, (THUMB.height() - board.height()) // 2, board
        )
        painter.end()
        return slot

    def _document(self, design: BoardDesign) -> PerfDocument:
        meta = DocumentMeta(name="preview", created="", modified="")
        return dataclasses.replace(
            create_empty_document(meta, design.board),
            edge_connectors=design.edge_connectors,
            mounting_holes=design.mounting_holes,
        )

    # -- reading and writing the fields --

    def _on_family_chosen(self, row: int) -> None:
        everything = self._everything()
        if not 0 <= row < len(everything):
            return
        family = everything[row]
        self._family = family
        self._size = _first_size(family) or self._size
        self._load(family, self._size)
        self.name.setText(family.name if family.user else "")
        self._redraw.start()

    def _load(self, family: BoardFamily, size: BoardSize) -> None:
        self._loading = True
        try:
            self.stock.clear()
            listed = _listed(family)
            for each in listed:
                self.stock.addItem(size_name(each, family))
            # A breadboard is not cut to measure: its sizes are all it comes in.
            if not is_pattern(family):
                self.stock.addItem(t("Your own size"))
            index = next(
                (i for i, each in enumerate(listed)
                 if each == size or (is_pattern(family) and each.name == size.name)),
                len(listed),
            )
            self.stock.setCurrentIndex(index)
            spec = family.breadboard or BreadboardSpec()
            key = str(spec.channel_mils)
            if spec.narrow_channel_cols == FLEX_NARROW_COLS and self.channel.findData(f"{key}-flex") >= 0:
                key = f"{key}-flex"
            self.channel.setCurrentIndex(max(0, self.channel.findData(key)))
            self.narrow.setValue(spec.narrow_channel_cols)
            self.border_x.setValue(
                SOLDERABLE_BORDER_X_MM if spec.border_x_mm is None else spec.border_x_mm)
            self.border_y.setValue(
                SOLDERABLE_BORDER_Y_MM if spec.border_y_mm is None else spec.border_y_mm)
            self.cols.setValue(size.cols)
            self.rows.setValue(size.rows)
            self.width_mm.setValue(size.width_mm)
            self.height_mm.setValue(size.height_mm)
            self.type.setCurrentIndex(max(0, self.type.findData(family.type)))
            self.strip_axis.setCurrentIndex(
                max(0, self.strip_axis.findData(family.strip_axis or "horizontal")))
            self.material.setCurrentIndex(max(0, self.material.findData(family.material)))
            self.pad_shape.setCurrentIndex(max(0, self.pad_shape.findData(family.pad_shape)))
            if family.pad_length_mm is not None:
                self.pad_length.setValue(family.pad_length_mm)
            self.pad_axis.setCurrentIndex(max(0, self.pad_axis.findData(family.pad_axis)))
            self.pitch.setValue(family.pitch_mm)
            self.pad.setValue(family.pad_diameter_mm)
            self.drill.setValue(family.drill_mm)
            strip = family.strip
            self.strip_on.setChecked(strip is not None)
            if strip is not None:
                self.strip_edges.setCurrentIndex(max(0, self.strip_edges.findData(strip.edges)))
                self.strip_shape.setCurrentIndex(max(0, self.strip_shape.findData(strip.shape)))
                self.strip_width.setValue(strip.width_mm)
            holes = family.corner_holes
            self.holes_on.setChecked(holes is not None)
            if holes is not None:
                self.hole_diameter.setValue(holes.diameter_mm)
                self.hole_head.setValue(holes.head_mm)
            legend = family.legend
            self.letters.setCurrentIndex(
                max(0, self.letters.findData(legend.letter_edges if legend else "none")))
            self.numbers.setCurrentIndex(
                max(0, self.numbers.findData(legend.number_edges if legend else "none")))
            self.row_digits.setValue(legend.row_digits if legend else 2)
            for fields, axis in ((self.legend_columns, legend.columns if legend else None),
                                 (self.legend_rows, legend.rows if legend else None)):
                fields.runs.setText(legend_runs_text(axis.runs) if axis else "")
                fields.every.setValue(axis.every if axis else 1)
                fields.digits.setValue(axis.digits if axis else 1)
            self._show_printed(family, size)
            self.mask_kind.setCurrentIndex(
                0 if family.mask is None else max(0, self.mask_kind.findData(family.mask)))
            self.finish.setCurrentIndex(
                0 if family.finish is None else max(0, self.finish.findData(family.finish)))
        finally:
            self._loading = False
        self._only_what_means_something()

    def _on_kind(self, *_args: object) -> None:
        self._only_what_means_something()
        self._changed()

    def _only_what_means_something(self) -> None:
        """Each setting shown only where it means something: which way the strips run on a
        stripboard alone, an oblong pad's length and axis on an oblong pad alone. A
        breadboard is its size and its channel -- its grid, pads, drill and print are the
        kind's, so none of that is offered -- and a solderable one its size and border; a
        solderless one is plastic, with no corner holes and no colour to choose."""
        kind = self._family.type
        pattern = kind in PATTERN_KINDS
        solderless = kind == "breadboard"
        sections = {
            "grid": not pattern,
            "edge": not pattern,
            "holes": not solderless,
            "legend": not pattern,
            "colour": not solderless,
        }
        for key, (heading, form) in self._sections.items():
            shown = sections.get(key, True)
            heading.setVisible(shown)
            for index in range(form.rowCount()):
                form.setRowVisible(index, shown)
        oblong = self.pad_shape.currentData() == "oblong"
        rows = {
            "grid": not pattern,
            "sizes": not pattern,
            "strip_axis": not pattern and self.type.currentData() == "stripboard",
            "pad_length_mm": not pattern and oblong,
            "pad_axis": not pattern and oblong,
            "breadboard.channel_mils": solderless,
            "breadboard.narrow_channel_cols": solderless and self._channel_mils() > STANDARD_CHANNEL * 100,
            "breadboard.border_x_mm": kind == "solderable-breadboard",
            "breadboard.border_y_mm": kind == "solderable-breadboard",
            "legend.row_digits": not pattern and not self._legend_off()
            and not self.legend_rows.runs.text().strip(),
            "legend.columns": not pattern and not self._legend_off(),
            "legend.rows": not pattern and not self._legend_off(),
        }
        for path, shown in rows.items():
            form, holder = self._rows[path]
            form.setRowVisible(holder, shown)

    def _channel_mils(self) -> int:
        return int(str(self.channel.currentData() or "300").split("-")[0])

    def _on_channel(self, *_args: object) -> None:
        """A flex body sets the narrow part to its own; a plain one makes it wide all the
        way. Either can still be changed by hand, for a body of somebody's own."""
        flex = str(self.channel.currentData()).endswith("-flex")
        self._loading = True
        try:
            self.narrow.setValue(FLEX_NARROW_COLS if flex else 0)
        finally:
            self._loading = False
        self._on_pattern()

    def _on_pattern(self, *_args: object) -> None:
        """The channel decides how many rows each size has, and which sizes can be made at
        all, so the sizes are asked again and the one shown is kept by its name."""
        if self._loading:
            return
        family = self._current_family()
        self._size = next(
            (each for each in family.sizes if each.name == self._size.name),
            family.sizes[0] if family.sizes else self._size,
        )
        self._load(family, self._size)
        self._redraw.start()

    def _show_printed(self, family: BoardFamily, size: BoardSize) -> None:
        """The words printed on the board as they read on THIS size, the template they come
        from on hover: "5cmX7cm", made from "{h}cmX{w}cm"."""
        template = family.printed[0].text if family.printed else ""
        resolved = template.replace("{w}", f"{size.width_mm / 10:g}").replace(
            "{h}", f"{size.height_mm / 10:g}")
        self.printed.setText(resolved)
        self._resolved = resolved
        self.printed.setToolTip(
            t("Made from {template}: the size in centimetres, as the board prints it.")
            .format(template=template) if "{" in template else ""
        )

    def _on_stock_size(self, index: int) -> None:
        family = self._current_family()
        listed = _listed(family)
        if 0 <= index < len(listed):
            self._size = listed[index]
            self._load(family, self._size)
        self._redraw.start()

    def _on_grid(self) -> None:
        if self._loading or is_pattern(self._family):
            return
        self._size = size_for_grid(self._current_family(), self.cols.value(), self.rows.value())
        self._load(self._current_family(), self._size)
        self._redraw.start()

    def _on_outline(self) -> None:
        if self._loading or is_pattern(self._family):
            return
        self._size = size_for_mm(
            self._current_family(), self.width_mm.value(), self.height_mm.value())
        self._load(self._current_family(), self._size)
        self._redraw.start()

    def _changed(self, *_args: object) -> None:
        if not self._loading:
            self._redraw.start()

    def _current_family(self) -> BoardFamily:
        """The family as the fields now say it."""
        if is_pattern(self._family):
            return self._pattern_family()
        base = self._family
        strip = (
            EdgeStrip(
                edges=self.strip_edges.currentData(),
                shape=self.strip_shape.currentData(),
                width_mm=self.strip_width.value(),
            )
            if self.strip_on.isChecked()
            else None
        )
        if strip is not None and base.strip is not None:
            strip = dataclasses.replace(
                base.strip, edges=strip.edges, shape=strip.shape, width_mm=strip.width_mm
            )
        holes = (
            CornerHoles(diameter_mm=self.hole_diameter.value(), head_mm=self.hole_head.value())
            if self.holes_on.isChecked()
            else None
        )
        letters, numbers = self.letters.currentData(), self.numbers.currentData()
        legend = (
            dataclasses.replace(base.legend or Legend(), letter_edges=letters, number_edges=numbers)
            if (letters, numbers) != ("none", "none")
            else None
        )
        printed = base.printed
        text = self.printed.text().strip()
        if printed and text and text != self._resolved:
            printed = (dataclasses.replace(printed[0], text=text), *printed[1:])
        legend = (
            dataclasses.replace(
                legend,
                row_digits=self.row_digits.value(),
                columns=self._axis(self.legend_columns),
                rows=self._axis(self.legend_rows),
            )
            if legend
            else None
        )
        oblong = self.pad_shape.currentData() == "oblong"
        stripboard = self.type.currentData() == "stripboard"
        return dataclasses.replace(
            base,
            type=self.type.currentData(),
            strip_axis=self.strip_axis.currentData() if stripboard else None,
            material=self.material.currentData(),
            pad_shape=self.pad_shape.currentData(),
            pad_length_mm=self.pad_length.value() if oblong else None,
            pad_axis=self.pad_axis.currentData(),
            pitch_mm=self.pitch.value(),
            pad_diameter_mm=self.pad.value(),
            drill_mm=self.drill.value(),
            strip=strip,
            corner_holes=holes,
            legend=legend,
            printed=printed,
            mask=self.mask_kind.currentData(),
            finish=self.finish.currentData(),
        )

    def _pattern_family(self) -> BoardFamily:
        """A breadboard family as the fields say it: its channel or its border, its corner
        holes and colour on a solderable one, and the sizes that can be made with them --
        a channel too wide for the mini leaves the mini out rather than refusing the full
        size the board is shown at. When none can be made, every size is kept, so the
        engine says why under the field that caused it."""
        base = self._family
        solderless = base.type == "breadboard"
        if solderless:
            channel = self._channel_mils()
            narrow = self.narrow.value() if channel > STANDARD_CHANNEL * 100 else 0
            spec: BreadboardSpec | None = BreadboardSpec(channel_mils=channel, narrow_channel_cols=narrow)
        else:
            x, y = self.border_x.value(), self.border_y.value()
            spec = BreadboardSpec(
                border_x_mm=None if x == SOLDERABLE_BORDER_X_MM else x,
                border_y_mm=None if y == SOLDERABLE_BORDER_Y_MM else y,
            )
            spec = None if spec == BreadboardSpec() else spec
        holes = (
            CornerHoles(diameter_mm=self.hole_diameter.value(), head_mm=self.hole_head.value())
            if not solderless and self.holes_on.isChecked()
            else None
        )
        family = dataclasses.replace(
            base,
            breadboard=spec,
            strip=None,
            corner_holes=holes,
            legend=None,
            printed=(),
            mask=None if solderless else self.mask_kind.currentData(),
            finish=None if solderless else self.finish.currentData(),
        )
        names = {size.name for size in base.sizes}
        named = [size for size in pattern_sizes(base.type, spec) if size.name in names]
        made = tuple(
            size for size in named
            if family_problem(dataclasses.replace(family, sizes=(size,))) is None
        )
        return dataclasses.replace(family, sizes=made or tuple(named))

    # -- the board, as it is now --

    def _show(self) -> None:
        family = self._current_family()
        for label in self._problems.values():
            label.hide()
        problem = self._unreadable_runs() or family_problem(family)
        self.use.setEnabled(problem is None)
        self.save.setEnabled(problem is None)
        if problem is not None:
            path, message = problem
            shown = self._problems.get(path) or self._problems.get(path.split(".")[0])
            target = shown if shown is not None else self.refusal
            target.setText(say(message))
            target.show()
            return
        self.refusal.hide()
        # Drawn at the size the label HAS: a picture wider than its label is cut at both
        # sides, and the border, the edge pads and the corner holes went with it.
        room = self.preview.contentsRect().size()
        if room.width() < 40 or room.height() < 40:
            room = PREVIEW
        self.preview.setPixmap(render_board(
            self._document(self.design()), self._lookup, room, _face(self._current_family())
        ))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._redraw.start()

    def design(self) -> BoardDesign:
        return self._design_of(self._current_family(), self._size)

    def _design_of(self, family: BoardFamily, size: BoardSize) -> BoardDesign:
        """``board_for``, and on the board that is open, what no family says kept as it is:
        the connectors and holes added by hand, and a legend's run round all four edges."""
        if family.id != THIS_BOARD:
            return board_for(family, size, self._base)
        if is_pattern(family) and size.name not in {each.name for each in family.sizes}:
            # A breadboard in no size it is sold in -- made by hand or by an agent: kept
            # exactly as it is, since no family can say it.
            return BoardDesign(self._base, *self._kept)
        design = board_for(family, size, self._base)
        board = design.board
        if self._base.type not in FAMILY_BOARD_TYPES and family.type == "pad-per-hole":
            board = dataclasses.replace(board, type=self._base.type)
        before, after = self._base.labels, board.labels
        if before is not None and after is not None and self._this is not None:
            said = self._this.legend
            if said is not None and (said.letter_edges, said.number_edges) == (
                after.letter_edges, after.number_edges):
                board = dataclasses.replace(board, labels=dataclasses.replace(
                    after, all_edges=before.all_edges, letter_edges=before.letter_edges,
                    number_edges=before.number_edges))
        connectors, holes = self._kept
        return BoardDesign(
            board, design.edge_connectors + connectors, design.mounting_holes + holes
        )

    # -- what to do with it --

    def _use(self) -> None:
        refused = self._apply(self.design())
        if refused:
            self.refusal.setText(refused)
            self.refusal.show()
            return
        self.accept()

    def _save_as_mine(self) -> None:
        name = self.name.text().strip()
        if not name:
            name, ok = QInputDialog.getText(self, t("Save as My Board…"), t("Name"))
            name = name.strip()
            if not ok or not name:
                return
        family = dataclasses.replace(
            self._current_family(), id=f"user-{len(self.saved) + 1}-{name.lower()}", name=name,
            user=True, sizes=(self._size, *[s for s in self._family.sizes if s != self._size]),
        )
        self.saved = [f for f in self.saved if f.name != name] + [family]
        self._fill_families()
        self.families.setCurrentRow(len(self._everything()) - 1)

