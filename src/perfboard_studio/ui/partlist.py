"""The parts in the document, as a list: what the Nets panel is for nets (#9).

The Parts panel is the LIBRARY -- what could go on a board -- so finding what IS on one meant
Go to Part by name. This lists every part the document has: the ones on the board with
where they stand, and the ones still only in the design, greyed. A click on a placed part
goes through the window's ``go_to_component``, the door the DRC panel and the sheet already
use, so the board, the sheet and the 3D view stay one selection; a click on a part still in
the design brings the sheet forward with that symbol selected.

It holds no state of its own beyond what it shows: ``refresh`` rebuilds it from a document,
and the window calls that only while the panel is in front (the guide's and the sheet's
rule), because a list rebuilt on every edit nobody is looking at is time spent for nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.geometry import format_hole
from perfboard_studio.model import ComponentInstance, PerfDocument, SchematicPart

from .i18n import t
from .partnames import footprint_label
from .theme import TEXT_DIM

#: Where each column is. The order a person reads a part in: what it is called, what it
#: is, what it looks like, where it is, and anything unusual about how it stands.
REF, VALUE, FOOTPRINT, POSITION, STATE = range(5)

#: Which document list a row came from, kept on the row so a click knows which door to use.
PLACED, IN_DESIGN = "placed", "design"

_ID = Qt.ItemDataRole.UserRole
_KIND = Qt.ItemDataRole.UserRole + 1
_SORT = Qt.ItemDataRole.UserRole + 2

_NUMBER = re.compile(r"(\d+)")


def natural_key(text: str) -> tuple[tuple[int, int | str], ...]:
    """``R2`` before ``R10``: every run of digits compared as a number, everything else as
    text, case ignored."""
    return tuple(
        (0, int(piece)) if piece.isdigit() else (1, piece.casefold())
        for piece in _NUMBER.split(text)
        if piece
    )


class _Row(QTreeWidgetItem):
    """A row that sorts by the key each column keeps, not by the text it shows."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else REF
        mine = self.data(column, _SORT)
        theirs = other.data(column, _SORT)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return bool(mine < theirs)


class PartListPanel(QWidget):
    """Every part in a document, filterable and sortable by any column."""

    #: A placed part was clicked: its component id.
    componentChosen = Signal(str)
    #: A part still in the design was clicked: its id.
    partChosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.filter = QLineEdit()
        # The Go to Part dialog's own words: one filter over the same parts, said once.
        self.filter.setPlaceholderText(t("Filter parts…  (R37, 10k, TO-220, C7)"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _text: self._apply_filter())
        layout.addWidget(self.filter)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            [t("Reference"), t("Value"), t("Footprint"), t("Position"), t("State")]
        )
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        # ONE ROW AT A TIME under the mouse, because a click goes to one part: a list that
        # let Ctrl pick three and then sent the window to the last of them would be offering
        # a selection it throws away. The board's own multiple selection is still SHOWN
        # here (:meth:`show_selected`) -- the mode governs only what a person can click.
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(REF, Qt.SortOrder.AscendingOrder)
        header = self.tree.header()
        header.setSectionResizeMode(FOOTPRINT, QHeaderView.ResizeMode.Stretch)
        for column in (REF, VALUE, POSITION, STATE):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        # A CLICK, not a selection change: the board's selection is shown here too, and a
        # list that answered its own reflection would send the window to the part it had
        # just been told about. Activation is Enter, for whoever walks it with the keys.
        self.tree.itemClicked.connect(self._chosen)
        self.tree.itemActivated.connect(self._chosen)
        layout.addWidget(self.tree)

    # -- filling ----------------------------------------------------------------------

    def refresh(self, document: PerfDocument, lookup: FootprintLookup) -> None:
        """Rebuild the list from ``document``, keeping the sort, the filter and what was
        selected."""
        selected = {item.data(REF, _ID) for item in self.tree.selectedItems()}
        sorting = self.tree.isSortingEnabled()
        self.tree.setSortingEnabled(False)
        blocked = self.tree.blockSignals(True)
        try:
            self.tree.clear()
            for component in document.components:
                self.tree.addTopLevelItem(self._placed_row(component, document, lookup))
            for part in document.parts:
                self.tree.addTopLevelItem(self._design_row(part, lookup))
        finally:
            self.tree.blockSignals(blocked)
        self.tree.setSortingEnabled(sorting)
        self._select(selected)
        self._apply_filter()

    def _placed_row(
        self, component: ComponentInstance, document: PerfDocument, lookup: FootprintLookup
    ) -> _Row:
        anchor = component.anchor
        return self._row(
            component.id,
            PLACED,
            component.ref,
            component.value,
            component.footprint_id,
            lookup,
            format_hole(anchor, document.board),
            # Placed parts first, then by row and column: down the board as it is read.
            (0, anchor.row, anchor.col),
            _state_words(component),
        )

    def _design_row(self, part: SchematicPart, lookup: FootprintLookup) -> _Row:
        row = self._row(
            part.id, IN_DESIGN, part.ref, part.value, part.footprint_id, lookup, "—", (1, 0, 0), ""
        )
        dim = QBrush(QColor(TEXT_DIM))
        for column in range(self.tree.columnCount()):
            row.setForeground(column, dim)
        row.setToolTip(REF, t("In the design, not on the board yet."))
        return row

    def _row(
        self,
        ident: str,
        kind: str,
        ref: str,
        value: str,
        footprint_id: str,
        lookup: FootprintLookup,
        position: str,
        position_key: tuple[int, int, int],
        state: str,
    ) -> _Row:
        # Said the way the library and the guide say it, and the id under the mouse: the
        # id is what a file and an agent use, and a filter on "dip" should find a DIP-8
        # whichever of the two the person happens to know.
        footprint = lookup(footprint_id)
        shown = footprint_label(footprint.name) if footprint is not None else footprint_id
        row = _Row([ref, value, shown, position, state])
        row.setData(REF, _ID, ident)
        row.setData(REF, _KIND, kind)
        row.setData(FOOTPRINT, _ID, footprint_id)
        row.setToolTip(FOOTPRINT, footprint_id)
        row.setData(REF, _SORT, natural_key(ref))
        row.setData(VALUE, _SORT, natural_key(value))
        row.setData(FOOTPRINT, _SORT, shown.casefold())
        row.setData(POSITION, _SORT, position_key)
        row.setData(STATE, _SORT, state.casefold())
        return row

    # -- what the window tells it ------------------------------------------------------

    def show_selected(self, component_ids: Iterable[str]) -> None:
        """Mark the placed parts the board has selected, and nothing else. A part still in
        the design cannot be selected on the board, so only a click here marks one; an empty
        board selection clears the list's."""
        self._select(set(component_ids), placed_only=True)

    def _select(self, ids: set[str], placed_only: bool = False) -> None:
        blocked = self.tree.blockSignals(True)
        try:
            self.tree.clearSelection()
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                if item is None or item.data(REF, _ID) not in ids:
                    continue
                if placed_only and item.data(REF, _KIND) != PLACED:
                    continue
                item.setSelected(True)
                self.tree.scrollToItem(item)
        finally:
            self.tree.blockSignals(blocked)

    # -- what it tells the window ------------------------------------------------------

    def _chosen(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        ident = item.data(REF, _ID)
        if not isinstance(ident, str):
            return
        if item.data(REF, _KIND) == PLACED:
            self.componentChosen.emit(ident)
        else:
            self.partChosen.emit(ident)

    def _apply_filter(self) -> None:
        """Hide every row none of whose columns holds what was typed, case ignored."""
        needle = self.filter.text().strip().casefold()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is None:
                continue
            said = [item.text(column) for column in range(self.tree.columnCount())]
            said.append(str(item.data(FOOTPRINT, _ID) or ""))
            item.setHidden(bool(needle) and not any(needle in text.casefold() for text in said))

    def rows(self) -> list[tuple[str, ...]]:
        """What the list shows, top to bottom and hidden rows left out: for tests, and for
        anybody asking what the panel says without reading widgets."""
        shown: list[tuple[str, ...]] = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and not item.isHidden():
                shown.append(tuple(item.text(column) for column in range(self.tree.columnCount())))
        return shown

    def selected_ids(self) -> list[str]:
        """The ids of the rows marked, in the order they are shown."""
        marked = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.isSelected():
                marked.append(str(item.data(REF, _ID)))
        return marked


def _state_words(component: ComponentInstance) -> str:
    """What is unusual about how a part stands, in the order the status bar says it about a
    selected part: turned, mirrored, locked."""
    words: list[str] = []
    if component.rotation:
        words.append(f"{component.rotation}°")
    if component.mirrored:
        words.append(t("mirrored"))
    if component.locked:
        words.append(t("locked"))
    return ", ".join(words)
