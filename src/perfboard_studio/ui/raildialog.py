"""Make This Strip a Rail: solder along one of a stock board's outside finger strips, and
the bridges that join it to the holes beside it.

The copper is the engine's to shape (``commands.rail_payload``, which MCP's ``add_rail``
dispatches too): the dialog only chooses the net, the two fingers the rail runs between,
which holes beside it are bridged onto it and, on a board with pads on both faces, the face.
The window lays it as one ``conductor.addMany``, one undo step.

A RAIL WITH NO BRIDGE CARRIES NOTHING, and the dialog says so rather than refusing it: the
copper is real and DRC names it, but a builder who unticked every bridge almost certainly
did not mean to solder a strip to nothing. The bridges a net's own pins stand beside are
ticked for it, because those are the holes a rail of that net is for.

Imports nothing of the window; the window opens it and reads what was chosen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio.command import CommandError
from perfboard_studio.commands import AddConductorsPayload, rail_payload
from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.geometry import (
    FingerCell,
    all_pin_holes,
    bridge_needs_spine,
    format_hole,
    hole_key,
    strip_cells,
)
from perfboard_studio.model import (
    BoardSide,
    HoleCoord,
    NetId,
    PerfDocument,
    contacts_every_path_hole,
    has_component_side_copper,
)

from . import theme
from .i18n import t

#: Which nets a rail is offered for first: a rail is how ground and power are run.
_CLASS_ORDER = {"ground": 0, "power": 1, "signal": 2}


def net_holes(doc: PerfDocument, lookup: FootprintLookup, net_id: NetId) -> set[str]:
    """The holes (``hole_key``) a net already reaches: its pins, and the holes its copper
    is soldered at."""
    net = next((n for n in doc.nets if n.id == net_id), None)
    if net is None:
        return set()
    by_ref = {c.ref: c for c in doc.components}
    wanted: dict[str, set[str]] = {}
    for node in net.nodes:
        wanted.setdefault(node.component_ref, set()).add(node.pin)
    found: set[str] = set()
    for ref, pins in wanted.items():
        component = by_ref.get(ref)
        footprint = lookup(component.footprint_id) if component is not None else None
        if component is None or footprint is None:
            continue
        for pin, hole in all_pin_holes(component, footprint):
            if pin.number in pins:
                found.add(hole_key(hole))
    for conductor in doc.conductors:
        if conductor.net_id != net_id or not conductor.path:
            continue
        touched = (
            conductor.path
            if contacts_every_path_hole(conductor)
            else (conductor.path[0], conductor.path[-1])
        )
        found.update(hole_key(h) for h in touched)
    return found


def rail_faces(doc: PerfDocument, connector_id: str) -> tuple[BoardSide, ...]:
    """The faces a rail on this strip may be laid on: the faces its fingers have copper on,
    and the component side only where the board has pads there too."""
    connector = next((c for c in doc.edge_connectors if c.id == connector_id), None)
    if connector is None:
        return ()
    faces: list[BoardSide] = []
    if connector.face in ("bottom", "both"):
        faces.append("bottom")
    if connector.face in ("top", "both") and has_component_side_copper(doc.board):
        faces.append("top")
    return tuple(faces)


class RailDialog(QDialog):
    """The net, the two fingers, the bridges and the face; the copper is ``payload()``."""

    def __init__(
        self,
        doc: PerfDocument,
        lookup: FootprintLookup,
        connector_id: str,
        *,
        face: BoardSide = "bottom",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Make This Strip a Rail"))
        self._doc = doc
        self._lookup = lookup
        self._cells: tuple[FingerCell, ...] = strip_cells(doc, connector_id)
        board = doc.board
        layout = QVBoxLayout(self)
        intro = QLabel(
            t(
                "Solder along the outside fingers, joined to the holes beside them by "
                "bridges: how ground and power are run on a stock board."
            ),
            self,
        )
        intro.setWordWrap(True)
        theme.tone(intro, "secondary")
        layout.addWidget(intro)
        form = QFormLayout()

        self.net = QComboBox(self)
        nets = sorted(doc.nets, key=lambda n: (_CLASS_ORDER.get(n.net_class, 3), n.name))
        for net in nets:
            self.net.addItem(net.name, net.id)
        self.net.addItem(t("No net"), None)
        form.addRow(t("Net"), self.net)

        self.start, self.end = QComboBox(self), QComboBox(self)
        for combo in (self.start, self.end):
            for index, cell in enumerate(self._cells):
                combo.addItem(format_hole(cell.cell, board), index)
        self.end.setCurrentIndex(max(0, len(self._cells) - 1))
        form.addRow(t("From"), self.start)
        form.addRow(t("To"), self.end)

        self.bridges = QListWidget(self)
        self.bridges.setMinimumHeight(140)
        form.addRow(t("Bridges"), self.bridges)

        self.face = QComboBox(self)
        faces = rail_faces(doc, connector_id)
        for each in faces:
            self.face.addItem(t("Solder Side") if each == "bottom" else t("Component Side"), each)
        self.face.setCurrentIndex(max(0, self.face.findData(face)))
        form.addRow(t("Face"), self.face)
        form.setRowVisible(self.face, len(faces) > 1)
        layout.addLayout(form)

        # Every stock board's gap from the last hole to its finger is wider than solder
        # spans, so each bridge is laid over a wire; said once, not on every line.
        self.spine_note = QLabel(
            t("Each bridge is laid over a wire: the gap to the finger is wider than solder spans."),
            self,
        )
        self.spine_note.setWordWrap(True)
        theme.tone(self.spine_note, "secondary")
        self.spine_note.setVisible(any(bridge_needs_spine(c, board) for c in self._cells))
        layout.addWidget(self.spine_note)
        self.warning = QLabel(self)
        self.warning.setWordWrap(True)
        theme.tone(self.warning, "warning")
        layout.addWidget(self.warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(t("Lay the Rail"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # The net a rail is usually for: ground, else the first supply, else the first net.
        self.net.setCurrentIndex(0)
        self._fill_bridges()
        self.net.currentIndexChanged.connect(lambda _i: self._fill_bridges())
        self.start.currentIndexChanged.connect(lambda _i: self._fill_bridges())
        self.end.currentIndexChanged.connect(lambda _i: self._fill_bridges())
        self.bridges.itemChanged.connect(lambda _item: self._update())

    def _span(self) -> list[FingerCell]:
        a, b = self.start.currentIndex(), self.end.currentIndex()
        if a < 0 or b < 0:
            return []
        low, high = min(a, b), max(a, b)
        return list(self._cells[low : high + 1])

    def _fill_bridges(self) -> None:
        """One line for each hole beside the span, ticked where the net already is."""
        board = self._doc.board
        net_id = self.net.currentData()
        reached = net_holes(self._doc, self._lookup, net_id) if net_id is not None else set()
        self.bridges.blockSignals(True)
        self.bridges.clear()
        for cell in self._span():
            item = QListWidgetItem(
                t("{hole} to {finger}").format(
                    hole=format_hole(cell.beside, board), finger=format_hole(cell.cell, board)
                )
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            on_net = hole_key(cell.beside) in reached
            item.setCheckState(Qt.CheckState.Checked if on_net else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, (cell.beside.col, cell.beside.row))
            self.bridges.addItem(item)
        self.bridges.blockSignals(False)
        self._update()

    def bridge_holes(self) -> list[tuple[int, int]]:
        """The (col, row) of every ticked bridge's hole, in order along the strip."""
        return [
            self.bridges.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.bridges.count())
            if self.bridges.item(i).checkState() == Qt.CheckState.Checked
        ]

    def set_bridges(self, holes: list[tuple[int, int]]) -> None:
        """Tick exactly these holes' bridges (by (col, row)), for a caller that knows."""
        wanted = set(holes)
        for i in range(self.bridges.count()):
            item = self.bridges.item(i)
            col_row = tuple(item.data(Qt.ItemDataRole.UserRole))
            item.setCheckState(
                Qt.CheckState.Checked if col_row in wanted else Qt.CheckState.Unchecked
            )

    def _update(self) -> None:
        if not hasattr(self, "ok"):
            return
        problem = ""
        try:
            self.payload()
        except CommandError as error:
            problem = rail_refusal(error)
        # No bridge is not refused by the engine -- an agent may lay the strip first and
        # bridge it after -- but from this dialog it is a rail that carries nothing, laid
        # and then reported by DRC straight away. The button waits for a bridge, and says
        # why where it waits.
        bridged = bool(self.bridge_holes())
        if problem:
            self.warning.setText(problem)
        elif not bridged:
            self.warning.setText(
                t("A rail with no bridge carries nothing: tick at least one bridge to lay it.")
            )
        else:
            self.warning.setText("")
        self.warning.setVisible(bool(self.warning.text()))
        self.ok.setEnabled(not problem and bridged)

    def span_said(self) -> str:
        """"A2/L–A9/L": the two fingers the rail runs between, as a message names them."""
        span = self._span()
        if not span:
            return ""
        board = self._doc.board
        start, end = span[0].cell, span[-1].cell
        if self.start.currentIndex() > self.end.currentIndex():
            start, end = end, start
        return f"{format_hole(start, board)}–{format_hole(end, board)}"

    def payload(self) -> AddConductorsPayload:
        """The rail as one ``conductor.addMany``. Raises ``CommandError`` as
        ``rail_payload`` does."""
        span = self._span()
        if not span:
            raise CommandError("not-a-rail", "A rail needs two fingers, or at least one bridge.")
        board = self._doc.board
        start, end = span[0].cell, span[-1].cell
        if self.start.currentIndex() > self.end.currentIndex():
            start, end = end, start
        face = self.face.currentData()
        return rail_payload(
            self._doc,
            start,
            end,
            bridges=[HoleCoord(col, row) for col, row in self.bridge_holes()],
            net_id=self.net.currentData(),
            side=face if face is not None else "bottom",
            label=t("Lay a rail {start}–{end}").format(
                start=format_hole(start, board), end=format_hole(end, board)
            ),
        )


def rail_refusal(error: CommandError) -> str:
    """A refused rail in the window's language. The one refusal the dialog's own choices
    can reach is a rail of one finger with no bridge; anything else is the engine's
    sentence, which names the holes."""
    if error.message == "A rail needs two fingers, or at least one bridge.":
        return t("A rail needs two fingers, or at least one bridge.")
    return error.message
