"""The Part List (#9): every part in a document, placed or not, as a list that leads to it.

The panel on its own first -- what it shows and in which order -- and then the window, which
is where it earns its place: a click goes to the part, the board's selection is marked in
the list, and a part that is only in the design opens the sheet.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.command import CommandContext
from perfboard_studio.commands import (
    UnplaceComponentPayload,
    create_document_id_generator,
    unplace_component,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import format_hole
from perfboard_studio.model import PerfDocument
from perfboard_studio.ui.partlist import (
    FOOTPRINT,
    POSITION,
    REF,
    STATE,
    PartListPanel,
    natural_key,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "ne555-astable.perf"
LOOKUP = footprint_lookup()


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _board() -> PerfDocument:
    return persist.parse_document_or_throw(EXAMPLE.read_text(encoding="utf-8"))


def _changed(doc: PerfDocument, which: str, **fields: object) -> PerfDocument:
    return dataclasses.replace(
        doc,
        components=tuple(
            dataclasses.replace(c, **fields) if c.ref == which else c  # type: ignore[arg-type]
            for c in doc.components
        ),
    )


def _unplaced(doc: PerfDocument, ref: str) -> PerfDocument:
    """``doc`` with ``ref`` taken off the board and back into the design."""
    component = next(c for c in doc.components if c.ref == ref)
    return unplace_component.apply(
        doc,
        UnplaceComponentPayload(id=component.id),
        CommandContext(next_id=create_document_id_generator(doc)),
    )


def _panel(doc: PerfDocument) -> PartListPanel:
    panel = PartListPanel()
    panel.refresh(doc, LOOKUP)
    return panel


def _row(panel: PartListPanel, ref: str):  # type: ignore[no-untyped-def]
    for index in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(index)
        if item is not None and item.text(REF) == ref:
            return item
    raise AssertionError(f"no row for {ref}")


# -- the panel ---------------------------------------------------------------------------


def test_references_sort_as_numbers_not_as_text() -> None:
    """R10 after R2: sorted as text it lands between R1 and R2, which on a board of forty
    parts is where nobody looks for it."""
    assert natural_key("R2") < natural_key("R10") < natural_key("R11")
    panel = _panel(_changed(_board(), "R3", ref="R10"))
    assert [row[REF] for row in panel.rows()] == [
        "C1", "C2", "J1", "LED1", "R1", "R2", "R10", "U1",
    ]


def test_a_placed_part_says_its_value_package_hole_and_how_it_stands() -> None:
    doc = _changed(_board(), "U1", locked=True)
    panel = _panel(doc)
    u1 = next(c for c in doc.components if c.ref == "U1")
    row = next(row for row in panel.rows() if row[REF] == "U1")
    assert row[1] == "NE555"
    footprint = LOOKUP(u1.footprint_id)
    assert footprint is not None and row[FOOTPRINT] == footprint.name
    assert row[POSITION] == format_hole(u1.anchor, doc.board)
    # In the order the status bar says it about a selected part.
    assert row[STATE] == f"{u1.rotation}°, locked"
    r1 = next(row for row in panel.rows() if row[REF] == "J1")
    assert r1[STATE] == ""


def test_a_part_still_in_the_design_is_listed_greyed_with_no_hole() -> None:
    """The parts the sheet has and the board does not were in no list at all."""
    panel = _panel(_unplaced(_board(), "R2"))
    refs = [row[REF] for row in panel.rows()]
    assert sorted(refs) == ["C1", "C2", "J1", "LED1", "R1", "R2", "R3", "U1"]
    row = next(row for row in panel.rows() if row[REF] == "R2")
    assert row[POSITION] == "—" and row[STATE] == ""
    item = _row(panel, "R2")
    assert item.toolTip(REF) == "In the design, not on the board yet."
    assert item.foreground(REF).color() != _row(panel, "R1").foreground(REF).color()
    # Sorted by position, the board is read top to bottom and the design comes last.
    panel.tree.sortByColumn(POSITION, Qt.SortOrder.AscendingOrder)
    assert [row[REF] for row in panel.rows()][-1] == "R2"


def test_the_filter_reads_every_column_and_the_package_id() -> None:
    panel = _panel(_board())
    panel.filter.setText("10k")
    assert [row[REF] for row in panel.rows()] == ["R1"]
    panel.filter.setText("dip-8")  # the id, which the shown name need not contain
    assert [row[REF] for row in panel.rows()] == ["U1"]
    panel.filter.setText("r")
    assert {"R1", "R2", "R3"} <= {row[REF] for row in panel.rows()}
    panel.filter.clear()
    assert len(panel.rows()) == 8


def test_the_board_selection_is_marked_and_a_design_part_never_is() -> None:
    doc = _unplaced(_board(), "R2")
    panel = _panel(doc)
    ids = {c.ref: c.id for c in doc.components}
    design_id = next(p.id for p in doc.parts if p.ref == "R2")
    panel.show_selected([ids["U1"], ids["C1"], design_id])
    assert sorted(panel.selected_ids()) == sorted([ids["U1"], ids["C1"]])
    panel.show_selected([])
    assert panel.selected_ids() == []


def test_a_click_names_the_part_and_says_which_list_it_is_in() -> None:
    doc = _unplaced(_board(), "R2")
    panel = _panel(doc)
    placed: list[str] = []
    designed: list[str] = []
    panel.componentChosen.connect(placed.append)
    panel.partChosen.connect(designed.append)
    panel.tree.itemClicked.emit(_row(panel, "U1"), 0)
    panel.tree.itemActivated.emit(_row(panel, "R2"), 0)
    assert placed == ["c-u1"]
    assert designed == [next(p.id for p in doc.parts if p.ref == "R2")]


def test_marking_the_board_selection_does_not_send_the_window_anywhere() -> None:
    """The list shows the board's selection, and a list that answered its own reflection
    would send the window to the part it had just been told about."""
    panel = _panel(_board())
    heard: list[str] = []
    panel.componentChosen.connect(heard.append)
    panel.show_selected(["c-u1"])
    panel.refresh(_board(), LOOKUP)
    assert heard == []


# -- in the window -----------------------------------------------------------------------


@pytest.fixture
def window(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import autosave as autosave_module
    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    monkeypatch.setattr(autosave_module, "default_directory", lambda: tmp_path / "recovery")
    made = main_module.MainWindow(_unplaced(_board(), "R2"))
    # Shown, because what decides whether the list is filled is Qt's notice that its tab
    # came to the front, and Qt sends none for a window that is not on screen.
    made.show()
    QApplication.processEvents()
    yield made
    made._saved_document = made.bus.document
    made.close()


def _bring_forward(window) -> None:  # type: ignore[no-untyped-def]
    window.dock_part_list.raise_()
    QApplication.processEvents()


def test_it_opens_as_a_tab_behind_nets_and_has_a_way_back(window) -> None:  # type: ignore[no-untyped-def]
    assert window.tabifiedDockWidgets(window.dock_nets) == [window.dock_part_list]
    assert window.dock_part_list.objectName() == "dockPartList"
    # Behind Nets, so nothing has been spent filling it.
    assert window._part_list_showing is False and window.part_list.rows() == []
    action = window.act_part_list_panel
    assert action.text() == "Show Part List"
    assert action.shortcut().toString() == "Ctrl+8"
    # Closed and opened again from the menu, it comes back IN FRONT: back behind Nets it
    # would be a menu item that seemed to do nothing.
    action.trigger()
    QApplication.processEvents()
    assert window.dock_part_list.isHidden()
    action.trigger()
    QApplication.processEvents()
    assert not window.dock_part_list.isHidden()
    assert window._part_list_showing is True
    assert len(window.part_list.rows()) == 8


def test_it_is_filled_when_it_comes_forward_and_not_before(window) -> None:  # type: ignore[no-untyped-def]
    r1 = next(c for c in window.bus.document.components if c.ref == "R1")
    window.bus.dispatch("component.unplace", UnplaceComponentPayload(id=r1.id))
    assert window._part_list_stale is True and window.part_list.rows() == []
    _bring_forward(window)
    assert window._part_list_stale is False
    row = next(row for row in window.part_list.rows() if row[REF] == "R1")
    assert row[POSITION] == "—"
    # In front, an edit shows at once: undo puts R1 back on its hole.
    window.bus.undo()
    row = next(row for row in window.part_list.rows() if row[REF] == "R1")
    assert row[POSITION] == format_hole(r1.anchor, window.bus.document.board)


def test_a_click_on_a_placed_part_selects_it_on_the_board(window) -> None:  # type: ignore[no-untyped-def]
    _bring_forward(window)
    u1 = next(c for c in window.bus.document.components if c.ref == "U1")
    window.part_list.tree.itemClicked.emit(_row(window.part_list, "U1"), 0)
    assert list(window.scene.selected_component_ids()) == [u1.id]
    assert window.statusBar().currentMessage() == (
        f"U1 at {format_hole(u1.anchor, window.bus.document.board)}"
    )
    assert window.part_list.selected_ids() == [u1.id]


def test_a_part_selected_on_the_board_is_marked_in_the_list(window) -> None:  # type: ignore[no-untyped-def]
    _bring_forward(window)
    ids = [c.id for c in window.bus.document.components if c.ref in ("C1", "LED1")]
    window.scene.select_components(ids)
    QApplication.processEvents()
    assert sorted(window.part_list.selected_ids()) == sorted(ids)
    window.scene.select_components([])
    QApplication.processEvents()
    assert window.part_list.selected_ids() == []


def test_a_part_still_in_the_design_opens_the_sheet_on_its_symbol(window) -> None:  # type: ignore[no-untyped-def]
    _bring_forward(window)
    window.part_list.tree.itemClicked.emit(_row(window.part_list, "R2"), 0)
    assert window.schematic_is_showing()
    assert window.schematic_view.selected_refs == ["R2"]
    assert window._schematic_ref == "R2"
    assert window.statusBar().currentMessage() == (
        "R2 is in the design, not on the board yet. Place on the Board puts it there."
    )


def test_resetting_the_layout_puts_it_back_behind_nets(window) -> None:  # type: ignore[no-untyped-def]
    window.dock_part_list.setFloating(True)
    window.dock_part_list.hide()
    window.on_reset_layout()
    QApplication.processEvents()
    assert not window.dock_part_list.isFloating() and not window.dock_part_list.isHidden()
    assert window.tabifiedDockWidgets(window.dock_nets) == [window.dock_part_list]
    assert window._part_list_showing is False
