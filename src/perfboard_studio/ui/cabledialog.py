"""Add Cable: a connector on one board, a connector on another, and the wires between them
paired by net.

The wires are the design's to say, not the person's to type: a pin of each connector on the
same net takes a wire (``system.pair_by_net``), and what is not certain -- a net with no
counterpart, or on two pins of one connector -- is left unpaired and said under the pairing,
never guessed. The dialog only chooses the two ends, the cable's reference and its length;
the window lays it as one ``cable.add``, one undo step.

Imports nothing of the window; the window opens it and reads what was chosen.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.erc import KIND_BY_ARCHETYPE
from perfboard_studio.model import BoardId, CableEnd, ComponentInstance, PerfDocument
from perfboard_studio.system import (
    CablePairing,
    board_document,
    board_ids,
    board_title,
    connector_of,
    pair_by_net,
)

from .i18n import counted, language, t


def connectors_on(doc: PerfDocument, board_id: BoardId, lookup: FootprintLookup) -> list[ComponentInstance]:
    """The parts on a board a cable can be fitted to: its connectors -- headers, terminals,
    the pads a panel part's wires land in -- or every part, on a board that has none."""
    parts = sorted(board_document(doc, board_id).components, key=lambda c: c.ref)
    connectors = [
        c
        for c in parts
        if (fp := lookup(c.footprint_id)) is not None
        and KIND_BY_ARCHETYPE.get(fp.body.archetype) == "connector"
    ]
    return connectors or parts


class CableDialog(QDialog):
    """Two ends, a reference and a length; the wires shown as the design pairs them."""

    def __init__(
        self,
        doc: PerfDocument,
        lookup: FootprintLookup,
        reference: str,
        a: CableEnd | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Add Cable"))
        self._doc = doc
        self._lookup = lookup
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.a_board, self.a_part = QComboBox(self), QComboBox(self)
        self.b_board, self.b_part = QComboBox(self), QComboBox(self)
        for combo in (self.a_board, self.b_board):
            for board_id in board_ids(doc):
                combo.addItem(board_title(doc, board_id, language()), board_id)
        form.addRow(t("From"), self._pair(self.a_board, self.a_part))
        form.addRow(t("To"), self._pair(self.b_board, self.b_part))
        self.reference = QLineEdit(reference, self)
        form.addRow(t("Reference"), self.reference)
        self.length = QDoubleSpinBox(self)
        self.length.setRange(0, 10_000)
        self.length.setDecimals(0)
        self.length.setSuffix(" mm")
        self.length.setSpecialValueText(t("cut to fit"))
        form.addRow(t("Length"), self.length)
        layout.addLayout(form)
        self.preview = QLabel(self)
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(t("Add Cable"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.a_board.currentIndexChanged.connect(lambda _i: self._fill(self.a_board, self.a_part))
        self.b_board.currentIndexChanged.connect(lambda _i: self._fill(self.b_board, self.b_part))
        self.a_part.currentIndexChanged.connect(lambda _i: self._update())
        self.b_part.currentIndexChanged.connect(lambda _i: self._update())
        ids = board_ids(doc)
        start_a = a.board if a is not None else ids[0]
        self.a_board.setCurrentIndex(ids.index(start_a))
        self._fill(self.a_board, self.a_part)
        if a is not None:
            self.a_part.setCurrentIndex(max(0, self.a_part.findData(a.connector)))
        other = next((b for b in ids if b != start_a), ids[0])
        self.b_board.setCurrentIndex(ids.index(other))
        self._fill(self.b_board, self.b_part)
        self._update()

    @staticmethod
    def _pair(board: QComboBox, part: QComboBox) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(board)
        line.addWidget(part, 1)
        return row

    def _fill(self, board: QComboBox, part: QComboBox) -> None:
        part.blockSignals(True)
        part.clear()
        for component in connectors_on(self._doc, board.currentData(), self._lookup):
            part.addItem(f"{component.ref}  {component.value}".strip(), component.id)
        part.blockSignals(False)
        self._update()

    def ends(self) -> tuple[CableEnd, CableEnd] | None:
        a_id, b_id = self.a_part.currentData(), self.b_part.currentData()
        if a_id is None or b_id is None:
            return None
        return CableEnd(self.a_board.currentData(), a_id), CableEnd(self.b_board.currentData(), b_id)

    def pairing(self) -> CablePairing | None:
        ends = self.ends()
        return None if ends is None else pair_by_net(self._doc, *ends)

    def length_mm(self) -> float | None:
        return None if self.length.value() == 0 else self.length.value()

    def _update(self) -> None:
        if not hasattr(self, "preview"):
            return
        ends = self.ends()
        pairing = self.pairing()
        if ends is None or pairing is None or ends[0] == ends[1]:
            self.preview.setText(t("Choose a connector at each end."))
            self.ok.setEnabled(False)
            return
        a_part, b_part = connector_of(self._doc, ends[0]), connector_of(self._doc, ends[1])
        assert a_part is not None and b_part is not None
        lines = [counted(len(pairing.wires), t("{count} wire, paired by net:"), t("{count} wires, paired by net:"))]
        net_of = {(n.component_ref, n.pin): net.name for net in self._doc.nets for n in net.nodes}
        lines += [
            f"  {net_of.get((a_part.ref, w.a_pin), '?')}: {a_part.ref} {w.a_pin} → {b_part.ref} {w.b_pin}"
            for w in pairing.wires
        ]
        if pairing.unpaired:
            lines.append(t("Not paired:"))
            lines += [f"  {why}" for why in pairing.unpaired]
        self.preview.setText("\n".join(lines))
        self.ok.setEnabled(bool(pairing.wires) and bool(self.reference.text().strip()))
