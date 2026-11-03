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
from PySide6.QtGui import QPixmap, QResizeEvent
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
    CornerHoles,
    EdgeStrip,
    Legend,
    board_for,
    family_from_json,
    family_problem,
    family_to_json,
    size_for_grid,
    size_for_mm,
)
from perfboard_studio.commands import create_empty_document
from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.model import Board, BoardSide, DocumentMeta, PerfDocument

from . import theme
from .boardpreview import render_board
from .engine_text import say
from .i18n import t

#: Where the user's own families are kept: in the settings, as the board colour is -- a
#: board somebody buys is not part of any one document.
USER_FAMILIES_KEY = "boardFamilies/user"

PREVIEW = QSize(560, 520)
THUMB = QSize(180, 120)


def family_name(family: BoardFamily) -> str:
    """A family in the window's language: a catalogue family by its id, a user's own by the
    name they gave it."""
    if family.user:
        return family.name
    return {
        "double-sided-fr4": t("Green double-sided (FR-4, tinned)"),
        "single-sided-phenolic": t("Phenolic single-sided (bare copper)"),
    }.get(family.id, family.name)


def _words() -> dict[str, dict[str, str]]:
    """Each vocabulary's ids in words, asked when shown, in the window's language."""
    return {
        "type": {
            "pad-per-hole": t("Pad per hole"),
            "stripboard": t("Stripboard"),
            "solderable-breadboard": t("Solderable breadboard"),
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
        "shape": {"rounded": t("Rounded"), "stadium": t("Stadium"), "square": t("Square")},
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


def size_name(size: BoardSize, family: BoardFamily) -> str:
    """A size as the picker says it: its name and its grid, because a name repeats across
    the variants of one size -- 7 x 9 cm is sold as 31 x 26 and as 35 x 27. A size sold
    without the family's edge pads says so; a family with none says nothing."""
    extra = "" if size.strip or family.strip is None else f", {t('no edge pads')}"
    return f"{size.name}  ({size.cols} × {size.rows}{extra})"


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

        self._fill_families()
        self.families.setCurrentRow(0)

    # -- building --

    @staticmethod
    def _heading(text: str) -> QLabel:
        shown = QLabel(theme.heading(text))
        shown.setTextFormat(Qt.TextFormat.RichText)
        return shown

    def _row(self, form: QFormLayout, label: str, field: QWidget, path: str = "") -> None:
        """A field, and under it the line that says why the family was refused there."""
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(field)
        if path:
            self._rows[path] = (form, holder)
            problem = QLabel()
            problem.setWordWrap(True)
            theme.tone(problem, "danger")
            problem.hide()
            column.addWidget(problem)
            self._problems[path] = problem
        form.addRow(label, holder)

    def _section(self, title: str) -> QFormLayout:
        self._settings.addWidget(self._heading(title))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._settings.addLayout(form)
        return form

    def _build_settings(self) -> None:
        w = self._words
        changed = self._changed

        size = self._section(t("Size"))
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
        self._row(size, t("Holes"), grid)
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

        pads = self._section(t("Grid and pads"))
        self.type = _combo(w["type"], FAMILY_BOARD_TYPES)
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

        edge = self._section(t("Edge pads"))
        self.strip_on = QCheckBox(t("Edge pads along two edges"))
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

        holes = self._section(t("Mounting holes"))
        self.holes_on = QCheckBox(t("A hole in each corner"))
        self.holes_on.toggled.connect(changed)
        holes.addRow(self.holes_on)
        self.hole_diameter = _mm(2.2, 10.0)
        self.hole_head = _mm(4.4, 20.0)
        for box in (self.hole_diameter, self.hole_head):
            box.editingFinished.connect(changed)
        self._row(holes, t("Diameter"), self.hole_diameter, "corner_holes.diameter_mm")
        self._row(holes, t("Screw head"), self.hole_head, "corner_holes.head_mm")

        legend = self._section(t("Legend and text"))
        self.letters = _combo(w["letters"], LETTER_EDGES)
        self.numbers = _combo(w["numbers"], NUMBER_EDGES)
        for combo in (self.letters, self.numbers):
            combo.activated.connect(changed)
        self._row(legend, t("Letters"), self.letters, "legend.letter_edges")
        self._row(legend, t("Numbers"), self.numbers, "legend.number_edges")
        self.row_digits = QSpinBox()
        self.row_digits.setRange(1, 4)
        self.row_digits.setToolTip(t('2 prints row 7 as "07", the way most such boards do.'))
        self.row_digits.valueChanged.connect(changed)
        self._row(legend, t("Row digits"), self.row_digits, "legend.row_digits")
        self.printed = QLineEdit()
        self.printed.editingFinished.connect(changed)
        self._row(legend, t("Printed on it"), self.printed, "printed")

        colour = self._section(t("Colour"))
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
        self._row(colour, t("Finish"), self.finish, "finish")

    def _fill_families(self) -> None:
        self.families.clear()
        for family in (*FAMILIES, *self.saved):
            item = QListWidgetItem(family_name(family))
            item.setToolTip(family_name(family))
            item.setIcon(self._thumb(family))
            item.setSizeHint(QSize(214, THUMB.height() + 48))
            self.families.addItem(item)

    def _thumb(self, family: BoardFamily) -> QPixmap:
        size = family.sizes[0] if family.sizes else self._size
        return render_board(
            self._document(board_for(family, size, self._base)), self._lookup, THUMB,
            _face(family),
        )

    def _document(self, design: BoardDesign) -> PerfDocument:
        meta = DocumentMeta(name="preview", created="", modified="")
        return dataclasses.replace(
            create_empty_document(meta, design.board),
            edge_connectors=design.edge_connectors,
            mounting_holes=design.mounting_holes,
        )

    # -- reading and writing the fields --

    def _on_family_chosen(self, row: int) -> None:
        everything = (*FAMILIES, *self.saved)
        if not 0 <= row < len(everything):
            return
        family = everything[row]
        self._family = family
        self._size = family.sizes[0] if family.sizes else self._size
        self._load(family, self._size)
        self.name.setText(family.name if family.user else "")
        self._redraw.start()

    def _load(self, family: BoardFamily, size: BoardSize) -> None:
        self._loading = True
        try:
            self.stock.clear()
            for each in family.sizes:
                self.stock.addItem(size_name(each, family))
            self.stock.addItem(t("Your own size"))
            index = family.sizes.index(size) if size in family.sizes else len(family.sizes)
            self.stock.setCurrentIndex(index)
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
        stripboard alone, an oblong pad's length and axis on an oblong pad alone."""
        stripboard = self.type.currentData() == "stripboard"
        oblong = self.pad_shape.currentData() == "oblong"
        for path, shown in (("strip_axis", stripboard), ("pad_length_mm", oblong),
                            ("pad_axis", oblong)):
            form, holder = self._rows[path]
            form.setRowVisible(holder, shown)

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
        if 0 <= index < len(self._family.sizes):
            self._size = self._family.sizes[index]
            self._load(self._current_family(), self._size)
        self._redraw.start()

    def _on_grid(self) -> None:
        if self._loading:
            return
        self._size = size_for_grid(self._current_family(), self.cols.value(), self.rows.value())
        self._load(self._current_family(), self._size)
        self._redraw.start()

    def _on_outline(self) -> None:
        if self._loading:
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
            dataclasses.replace(legend, row_digits=self.row_digits.value()) if legend else None
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

    # -- the board, as it is now --

    def _show(self) -> None:
        family = self._current_family()
        for label in self._problems.values():
            label.hide()
        problem = family_problem(family)
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
        return board_for(self._current_family(), self._size, self._base)

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
        self.families.setCurrentRow(len(FAMILIES) + len(self.saved) - 1)

