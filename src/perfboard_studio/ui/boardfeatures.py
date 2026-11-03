"""What a board has besides its grid -- mounting holes and edge connectors -- in Properties.

BOARD FEATURES WAS A DIALOG, and it retired into Properties: the board is "which board" in
the designer and "what this board has" here. The board's editor lists its holes and
connectors, each with Remove, and adds corner holes and an edge connector
(``FeaturesGroup``); a hole or a connector clicked on the board shows its own editor --
where it is, its size, Remove (``FeatureEditor``). The height limit and the body clearance
were the dialog's too, and are the board editor's own fields.

Every button is one command, dispatched as it is pressed, as the dialog did: each change is
its own undo step, which is what "undo that" means after a connector and then four holes,
and the board redraws beside it, which is how a corner hole is seen to land on a part.
What a board cannot take is not offered: no bore through a solderless breadboard, no
fingers on either kind of breadboard.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio.breadboard import has_breadboard_pattern, is_breadboard
from perfboard_studio.commands import (
    AddEdgeConnectorPayload,
    AddMountingHolesPayload,
    DeleteEdgeConnectorPayload,
    DeleteMountingHolePayload,
)
from perfboard_studio.geometry import (
    board_edge_margin_mm,
    edge_connector_holes,
    format_hole,
    pad_extent_mm,
)
from perfboard_studio.model import (
    Board,
    BoardEdge,
    EdgeConnector,
    HoleCoord,
    MountingHole,
    PerfDocument,
)

from . import theme
from .i18n import t

#: One command, by name and payload; answers why it was refused, in the window's language.
Dispatch = Callable[[str, object], str | None]

EDGES: tuple[BoardEdge, ...] = ("top", "bottom", "left", "right")


def edge_word(edge: BoardEdge) -> str:
    return {"top": t("Top"), "bottom": t("Bottom"), "left": t("Left"), "right": t("Right")}[edge]


def corner_offset_mm(board: Board, diameter: float) -> float:
    """How far diagonally OUT of the grid a corner mounting hole should sit.

    Real boards put their corner holes in the border, clear of every pad — look at any
    of them and the copper grid is untouched. That is only possible if the border is wide
    enough to take the bore; on a flush-cut board there is nowhere to go, and the hole
    has to land on the grid and eat the pads around it, which is what DRC then reports.

    Returns 0 when it will not fit, so the caller gets the old on-grid behaviour rather
    than a hole hanging off the edge of the board.
    """
    extent_x, extent_y = pad_extent_mm(board)
    # Far enough out that the bore misses the corner pad, measured on the diagonal.
    clears_pad = (max(extent_x, extent_y) / 2 + diameter / 2) / math.sqrt(2)
    # Near enough in that the bore stays on the substrate, on the tighter axis.
    stays_on_board = min(
        board_edge_margin_mm(board, "horizontal"), board_edge_margin_mm(board, "vertical")
    ) - diameter / 2 - 0.2
    if stays_on_board < clears_pad:
        return 0.0
    return round(stays_on_board, 3)


def hole_said(mount: MountingHole, board: Board) -> tuple[str, str]:
    """(where, how big) for a mounting hole. One in the border is OUTSIDE the hole it is
    addressed by -- "the hole outside A1", as ``MountingHole`` says -- and "A1" alone read
    as drilled through A1, where the stock boards' corner holes never are."""
    hole = format_hole(mount.at, board)
    outside = mount.offset_x_mm or mount.offset_y_mm
    where = t("outside {hole}").format(hole=hole) if outside else hole
    return where, t("⌀{drill} mm, {head} mm head").format(
        drill=f"{mount.diameter:g}", head=f"{mount.head_diameter:g}"
    )


def connector_said(connector: EdgeConnector, board: Board) -> tuple[str, str]:
    """(where, how big) for an edge connector: its edge and its first and last hole."""
    holes = edge_connector_holes(connector, board)
    where = edge_word(connector.edge)
    if holes:
        where += f", {format_hole(holes[0], board)}–{format_hole(holes[-1], board)}"
    return where, f"{connector.count} × {connector.finger_width:g} mm"


def _narrow(combo: QComboBox) -> None:
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(6)


def _remove_button() -> QToolButton:
    button = QToolButton()
    button.setText(t("Remove"))
    button.setAutoRaise(True)
    return button


class FeaturesGroup(QWidget):
    """The board's holes and connectors, each with Remove, and the two ways to add some."""

    def __init__(self, dispatch: Dispatch) -> None:
        super().__init__()
        self._dispatch = dispatch
        self._document: PerfDocument | None = None
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACE["sm"])
        heading = QLabel(theme.heading(t("Mounting holes and edge connectors")))
        heading.setTextFormat(Qt.TextFormat.RichText)
        column.addWidget(heading)
        self.heading = heading
        #: One line per feature, rebuilt with the document.
        self._rows = QVBoxLayout()
        self._rows.setSpacing(0)
        column.addLayout(self._rows)
        self.empty = QLabel(t("None yet."))
        theme.tone(self.empty, "secondary")
        column.addWidget(self.empty)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.mount_diameter = QDoubleSpinBox()
        self.mount_diameter.setRange(0.5, 12.0)
        self.mount_diameter.setSingleStep(0.1)
        self.mount_diameter.setDecimals(1)
        self.mount_diameter.setSuffix(" mm")
        self.mount_diameter.setValue(3.2)
        self.mount_inset = QSpinBox()
        self.mount_inset.setRange(0, 20)
        self.mount_inset.setValue(1)
        self.mount_inset.setToolTip(
            t("How many holes in from each corner; 0 uses the corner hole itself.")
        )
        self.add_corners = QPushButton(t("Add Corner Holes"))
        self.add_corners.clicked.connect(self._on_add_corners)
        form.addRow(t("Hole diameter"), self.mount_diameter)
        form.addRow(t("Inset from the edge (holes)"), self.mount_inset)
        form.addRow("", self.add_corners)

        self.edge = QComboBox()
        for edge in EDGES:
            self.edge.addItem(edge_word(edge), edge)
        self.edge.setCurrentIndex(1)
        # By the address it starts at, read off the board -- a column letter along the top
        # or bottom, a row number down a side, as the list says "Left, A2–A25". It was a
        # spin box from 0: the engine's index, which no other field in the window shows.
        self.finger_start = QComboBox()
        _narrow(self.finger_start)
        self.finger_count = QSpinBox()
        self.finger_count.setRange(1, 999)
        self.finger_count.setValue(8)
        self.add_connector = QPushButton(t("Add Edge Connector"))
        self.add_connector.clicked.connect(self._on_add_connector)
        form.addRow(t("Edge"), self.edge)
        form.addRow(t("First hole"), self.finger_start)
        form.addRow(t("Fingers"), self.finger_count)
        form.addRow("", self.add_connector)
        # As many fingers as the chosen edge has holes, so the default of eight on a board
        # five holes wide is not a refusal waiting to happen.
        self.edge.currentIndexChanged.connect(self._list_starts)
        self.finger_start.currentIndexChanged.connect(self._fit_fingers)
        column.addLayout(form)
        # None is a default: a push button in a form is pressed by clicking it, and Enter in
        # the diameter box once deleted the selected hole in the dialog this replaced.
        for button in (self.add_corners, self.add_connector):
            button.setAutoDefault(False)

        self.problem = QLabel()
        self.problem.setWordWrap(True)
        theme.tone(self.problem, "danger")
        self.problem.hide()
        column.addWidget(self.problem)

    # -- what the board has --

    def load(self, document: PerfDocument) -> None:
        self._document = document
        board = document.board
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for mount in document.mounting_holes:
            where, size = hole_said(mount, board)
            self._add_row(
                f"{t('Mounting hole')}  ·  {where}", size,
                lambda _checked=False, i=mount.id: self._run(
                    "mounting-hole.delete", DeleteMountingHolePayload(id=i)),
            )
        for connector in document.edge_connectors:
            where, size = connector_said(connector, board)
            self._add_row(
                f"{t('Edge connector')}  ·  {where}", size,
                lambda _checked=False, i=connector.id: self._run(
                    "edge-connector.delete", DeleteEdgeConnectorPayload(id=i)),
            )
        self.empty.setVisible(not document.mounting_holes and not document.edge_connectors)
        # What this board cannot take is not offered, rather than refused in words.
        drilled = not is_breadboard(board)
        self.add_corners.setEnabled(drilled)
        self.add_corners.setToolTip(
            "" if drilled else t("Nothing is drilled into a solderless breadboard.")
        )
        fingers = not has_breadboard_pattern(board)
        self.add_connector.setEnabled(fingers)
        self.add_connector.setToolTip(
            "" if fingers else t("A breadboard's edges are its rails, not fingers.")
        )
        self._list_starts()

    def rows(self) -> list[QWidget]:
        """The lines listed now, one per hole and connector, holes first."""
        found: list[QWidget] = []
        for index in range(self._rows.count()):
            item = self._rows.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None:
                found.append(widget)
        return found

    def _add_row(self, what: str, size: str, remove: Callable[..., None]) -> None:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        said = QLabel(f"{what}<br><span>{size}</span>")
        said.setTextFormat(Qt.TextFormat.RichText)
        said.setWordWrap(True)
        line.addWidget(said, 1)
        button = _remove_button()
        button.clicked.connect(remove)
        line.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        row.remove = button  # type: ignore[attr-defined]
        self._rows.addWidget(row)

    def _along(self) -> int:
        board = self._document.board if self._document is not None else None
        if board is None:
            return 0
        return board.cols if self.edge.currentData() in ("top", "bottom") else board.rows

    def _list_starts(self, *_args: object) -> None:
        """Where a connector on the chosen edge can start, by the address of its first
        finger's hole -- the engine's own (``edge_connector_holes``), so the field and the
        list below cannot disagree about which hole that is."""
        if self._document is None:
            return
        board = self._document.board
        edge = cast(BoardEdge, self.edge.currentData())
        kept = max(0, self.finger_start.currentData() or 0)
        self.finger_start.blockSignals(True)
        self.finger_start.clear()
        for start in range(self._along()):
            probe = EdgeConnector(id="probe", edge=edge, start=start, count=1)
            holes = edge_connector_holes(probe, board)
            self.finger_start.addItem(format_hole(holes[0], board) if holes else str(start + 1), start)
        self.finger_start.setCurrentIndex(min(kept, self.finger_start.count() - 1))
        self.finger_start.blockSignals(False)
        self._fit_fingers()

    def _fit_fingers(self, *_args: object) -> None:
        start = self.finger_start.currentData() or 0
        self.finger_count.setMaximum(max(1, self._along() - start))

    # -- what is done to it --

    def _run(self, name: str, payload: object) -> None:
        """One command; a refusal said under the group, in the window's language."""
        refused = self._dispatch(name, payload)
        self.problem.setText(refused or "")
        self.problem.setVisible(bool(refused))

    def _on_add_corners(self) -> None:
        if self._document is None:
            return
        board = self._document.board
        inset = self.mount_inset.value()
        far_col, far_row = board.cols - 1 - inset, board.rows - 1 - inset
        if far_col <= inset or far_row <= inset:
            self.problem.setText(t("That inset does not fit on this board."))
            self.problem.show()
            return
        corners = (
            HoleCoord(inset, inset),
            HoleCoord(far_col, inset),
            HoleCoord(inset, far_row),
            HoleCoord(far_col, far_row),
        )
        diameter = self.mount_diameter.value()
        offset = corner_offset_mm(board, diameter)
        self._run(
            "mounting-hole.addMany",
            AddMountingHolesPayload(
                ats=corners,
                # Signs put each hole outside its own corner rather than all four in the
                # same direction.
                offsets=tuple(
                    (
                        -offset if hole.col <= inset else offset,
                        -offset if hole.row <= inset else offset,
                    )
                    for hole in corners
                ),
                diameter=diameter,
                # A washer is roughly twice the bolt's clearance hole, which is the keepout
                # DRC warns about. Guessed rather than asked for: a person fitting an M3
                # screw does not want to be quizzed about it.
                head_diameter=round(diameter * 2, 2),
                label=f"Drill 4 corner mounting holes ({diameter:g} mm)",
            ),
        )

    def _on_add_connector(self) -> None:
        self._run(
            "edge-connector.add",
            AddEdgeConnectorPayload(
                edge=cast(BoardEdge, self.edge.currentData()),
                start=int(self.finger_start.currentData() or 0),
                count=self.finger_count.value(),
            ),
        )


class FeatureEditor(QWidget):
    """One mounting hole or one edge connector, chosen on the board: what it is, where, how
    big, and Remove -- so the list in the board's editor is not the only way to one."""

    def __init__(self, dispatch: Dispatch) -> None:
        super().__init__()
        self._dispatch = dispatch
        self._remove: tuple[str, object] | None = None
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACE["lg"])
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        column.addWidget(self.title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.where = QLabel()
        self.measure = QLabel()
        for fact in (self.where, self.measure):
            fact.setWordWrap(True)
            fact.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(t("Where"), self.where)
        form.addRow(t("Size"), self.measure)
        column.addLayout(form)
        self.remove = QPushButton(t("Remove"))
        self.remove.setAutoDefault(False)
        self.remove.clicked.connect(self._on_remove)
        column.addWidget(self.remove, 0, Qt.AlignmentFlag.AlignLeft)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        theme.tone(self.problem, "danger")
        self.problem.hide()
        column.addWidget(self.problem)

    def load_hole(self, document: PerfDocument, mount: MountingHole) -> None:
        self.title.setText(theme.heading(t("Mounting hole")))
        where, size = hole_said(mount, document.board)
        self.where.setText(where)
        self.measure.setText(size)
        self._remove = ("mounting-hole.delete", DeleteMountingHolePayload(id=mount.id))
        self.problem.hide()

    def load_connector(self, document: PerfDocument, connector: EdgeConnector) -> None:
        self.title.setText(theme.heading(t("Edge connector")))
        where, size = connector_said(connector, document.board)
        self.where.setText(where)
        self.measure.setText(size)
        self._remove = ("edge-connector.delete", DeleteEdgeConnectorPayload(id=connector.id))
        self.problem.hide()

    def _on_remove(self) -> None:
        if self._remove is None:
            return
        refused = self._dispatch(*self._remove)
        self.problem.setText(refused or "")
        self.problem.setVisible(bool(refused))
