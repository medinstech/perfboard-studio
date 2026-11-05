"""Every reader of "the circuit" sees every board; every reader of "the board" sees one.

``system.board_document`` hands the single-board engine one board at a time, which is right
for DRC, the router, the renderers and the rest. It is wrong for anything that asks about
the CIRCUIT -- ERC, LVS, the sheet, the Parts list, a free reference, the step bar, the MCP
status -- because on one board's view a part on the second board is neither placed nor in
the design: it is a reference nothing defines. The first reader found that way was ERC,
which would have called every net reaching the second board "part-not-defined" and made
the guide refuse the build.

So each system reader is held here on a document of two boards, and the pattern that
produced the bug -- one function reading ``doc.components`` and ``doc.parts`` together --
is found by reading the sources: a new function that does it is either a system reader that
has to go through ``system.py`` or a board reader that says why in ``BOARD_READERS``.
docs/ARCHITECTURE.md, "Several boards are one document, and each is seen alone", has the
table.
"""

from __future__ import annotations

import ast
import dataclasses
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from perfboard_studio import persist, system
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    DEFAULT_BOARD,
    AddPartPayload,
    DeleteComponentPayload,
    UpdateComponentPayload,
    create_document_id_generator,
    create_standard_registry,
    design_on_a_new_board,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import (
    Cable,
    CableEnd,
    CableWire,
    ComponentInstance,
    DocumentMeta,
    ExtraBoard,
    HoleCoord,
    Net,
    NetNode,
    PerfDocument,
    SchematicPart,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "perfboard_studio"


def _system(*, wires: tuple[CableWire, ...] | None = (CableWire("1", "1"), CableWire("2", "2"))) -> PerfDocument:
    """Main holds JA and R1, Remote holds JB and R2; GND and SIG run from JA to JB through
    W1 (unless ``wires`` is None), and R9 waits in the design."""
    ja = ComponentInstance(id="cmp-1", ref="JA", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    r1 = ComponentInstance(id="cmp-2", ref="R1", value="1k", footprint_id="r-axial-4", anchor=HoleCoord(2, 6))
    jb = ComponentInstance(id="cmp-3", ref="JB", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    r2 = ComponentInstance(id="cmp-4", ref="R2", value="1k", footprint_id="r-axial-4", anchor=HoleCoord(2, 6))
    nets = (
        Net(id="n1", name="GND", nodes=(NetNode("JA", "2"), NetNode("JB", "2")), net_class="ground"),
        Net(id="n2", name="SIG", nodes=(NetNode("JA", "1"), NetNode("JB", "1"))),
    )
    cables = (
        ()
        if wires is None
        else (Cable(id="cable-1", ref="W1", a=CableEnd(system.FIRST_BOARD, "cmp-1"), b=CableEnd("b2", "cmp-3"), wires=wires),)
    )
    return PerfDocument(
        meta=DocumentMeta(name="Main", created="", modified=""),
        board_name="Main",
        board=DEFAULT_BOARD,
        components=(ja, r1),
        parts=(SchematicPart(id="part-1", ref="R9", value="10k", footprint_id="r-axial-4"),),
        nets=nets,
        boards=(ExtraBoard(id="b2", name="Remote", board=DEFAULT_BOARD, components=(jb, r2)),),
        cables=cables,
    )


def _bus(doc: PerfDocument) -> CommandBus:
    return CommandBus(doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc)))


# ---------------------------------------------------------------------------
# The engine's system readers
# ---------------------------------------------------------------------------


def test_erc_sees_a_part_on_the_second_board_as_defined() -> None:
    from perfboard_studio.erc import run_erc

    findings = run_erc(_system(), footprint_lookup())
    assert not [f for f in findings if f.rule == "part-not-defined"], [f.message for f in findings]


def test_a_cable_wire_on_a_pin_its_connector_lacks_is_pin_not_on_part() -> None:
    """Not refused -- only the registry knows a part's pins -- and said by ERC in the
    cable's own words, as a net naming a missing pin is."""
    from perfboard_studio.commands import UpdateCablePayload
    from perfboard_studio.erc import run_erc

    doc = _system()
    wrong = dataclasses.replace(doc.cables[0], wires=(CableWire("1", "1"), CableWire("2", "5")))
    bus = _bus(doc)
    result = bus.dispatch("cable.update", UpdateCablePayload(cable=wrong))
    assert result.ok, result.message
    findings = [f for f in run_erc(bus.document, footprint_lookup()) if f.rule == "pin-not-on-part"]
    assert len(findings) == 1 and findings[0].severity == "error"
    assert findings[0].message == "W1 lands on JB pin 5, which hdr-1x2 does not have."
    assert findings[0].refs == ("W1", "JB")


def test_lvs_of_a_system_is_whole_through_its_cable() -> None:
    from perfboard_studio.lvs import run_lvs

    result = run_lvs(_system(), footprint_lookup())
    kinds = [i.kind for i in result.issues]
    # R9 waits in the design and no net names it: nothing to say about it, and nothing
    # about JB being "unplaced" -- it is on Remote.
    assert "unplaced-component" not in kinds, [i.message for i in result.issues]
    assert not [i for i in result.issues if i.kind in ("open", "unrouted-net", "short")], [i.message for i in result.issues]


def test_lvs_says_a_part_on_no_board_once_and_a_split_net_by_its_boards() -> None:
    from perfboard_studio.lvs import run_lvs

    doc = _system(wires=None)
    doc = dataclasses.replace(
        doc, nets=(*doc.nets, Net(id="n3", name="BIAS", nodes=(NetNode("R1", "1"), NetNode("R9", "1"))))
    )
    result = run_lvs(doc, footprint_lookup())
    unplaced = [i for i in result.issues if i.kind == "unplaced-component"]
    assert len(unplaced) == 1 and "R9" in unplaced[0].message and "not placed on any board" in unplaced[0].message
    opens = {i.net_names[0]: i.message for i in result.issues if i.kind == "open"}
    assert set(opens) == {"GND", "SIG"}
    assert all("across Main and Remote" in m for m in opens.values()), opens
    assert not result.ok and result.summary.opens == 2


def test_a_boards_own_open_is_said_with_its_name_and_not_again_by_the_system() -> None:
    """GND joined on Main and between the boards, but its two pins on Remote are two
    islands there: the fix is to route Remote, so that is what is said, once."""
    from perfboard_studio.lvs import run_lvs

    doc = _system()
    remote = system.extra_board(doc, "b2")
    doc = dataclasses.replace(
        doc,
        nets=(Net(id="n1", name="GND", nodes=(NetNode("JA", "2"), NetNode("JB", "2"), NetNode("R2", "1")), net_class="ground"), doc.nets[1]),
        boards=(remote,),
    )
    result = run_lvs(doc, footprint_lookup())
    gnd = [i for i in result.issues if "GND" in i.net_names]
    assert len(gnd) == 1 and gnd[0].message.startswith("On Remote: "), [i.message for i in gnd]


def test_the_sheet_draws_a_part_on_the_second_board_as_placed() -> None:
    from perfboard_studio.schematic import build_schematic

    symbols = {s.ref: s for s in build_schematic(_system(), footprint_lookup()).symbols}
    assert {"JA", "JB", "R1", "R2", "R9"} <= set(symbols)
    assert not symbols["JB"].unplaced and not symbols["JB"].undefined
    assert symbols["R9"].unplaced


def test_a_free_reference_is_free_on_every_board() -> None:
    from perfboard_studio.catalog import free_reference
    from perfboard_studio.ui.view2d import next_reference

    doc = _system()
    assert free_reference(doc, "R") == "R3"
    assert next_reference(doc, "r-axial-4") == "R3"
    assert free_reference(doc, "W") == "W2", "a cable's reference is taken too"


def test_a_reference_on_the_second_board_is_refused_to_the_design() -> None:
    result = _bus(_system()).dispatch("part.add", AddPartPayload(ref="R2", value="", footprint_id="r-axial-4"))
    assert not result.ok and result.code == "duplicate-ref" and "Remote" in result.message


def test_a_command_on_the_document_itself_is_checked_against_the_system() -> None:
    """Dispatched without ``board.on`` -- the first board, as every host has always done --
    and still unable to take a cabled connector away or reuse a reference another board
    holds."""
    bus = _bus(_system())
    gone = bus.dispatch("component.delete", DeleteComponentPayload(id="cmp-1"))
    assert not gone.ok and gone.code == "cable-end" and "W1" in gone.message
    clash = bus.dispatch("component.update", UpdateComponentPayload(id="cmp-2", ref="R2"))
    assert not clash.ok and clash.code == "duplicate-ref", clash.message
    fine = bus.dispatch("component.update", UpdateComponentPayload(id="cmp-2", value="2k2"))
    assert fine.ok, fine.message


def test_a_duplicate_reference_a_file_opened_with_does_not_refuse_every_command() -> None:
    """A duplicated reference is a warning at load, on one board or several. The system
    check refuses only what a command makes."""
    doc = _system()
    remote = system.extra_board(doc, "b2")
    twin = dataclasses.replace(remote.components[1], ref="R1")
    doc = dataclasses.replace(doc, boards=(dataclasses.replace(remote, components=(remote.components[0], twin)),))
    result = _bus(doc).dispatch("component.update", UpdateComponentPayload(id="cmp-2", value="2k2"))
    assert result.ok, result.message


def test_the_circuit_goes_to_a_new_board_from_every_board() -> None:
    new = design_on_a_new_board(_system(), DocumentMeta(name="n", created="", modified=""))
    assert {p.ref for p in new.parts} == {"JA", "R1", "JB", "R2", "R9"}
    assert not new.boards and not new.cables and not new.components


def test_a_file_with_a_cable_that_is_not_whole_is_refused_at_load() -> None:
    doc = _system()
    twice = dataclasses.replace(doc.cables[0], wires=(CableWire("1", "1"), CableWire("1", "2")))
    text = persist.serialize_document(dataclasses.replace(doc, cables=(twice,)))
    result = persist.deserialize_document(text)
    assert not result.ok and result.code == "invalid-cable", result
    assert result.path == "cables[0]"


def test_the_mcp_status_counts_every_board_and_names_a_part_where_it_is() -> None:
    from perfboard_studio.mcp.session import BoardSession, SessionError

    session = BoardSession(document=_system())
    status = session.get_status()
    assert status["components"] == 4
    assert status["boards"] == [
        {"id": "main", "name": "Main", "components": 2},
        {"id": "b2", "name": "Remote", "components": 2},
    ]
    assert status["cables"] == 1
    assert {c["ref"]: c["board"] for c in session.list_components()} == {
        "JA": "Main", "R1": "Main", "JB": "Remote", "R2": "Remote"
    }
    with pytest.raises(SessionError, match="JB is on Remote"):
        session.get_component("JB")


def test_a_single_board_status_has_no_system_keys() -> None:
    from perfboard_studio.mcp.session import BoardSession

    one = dataclasses.replace(_system(wires=None), boards=())
    status = BoardSession(document=one).get_status()
    assert "boards" not in status and "cables" not in status
    assert all("board" not in c for c in BoardSession(document=one).list_components())


# ---------------------------------------------------------------------------
# The window's
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def test_the_parts_list_shows_the_second_boards_parts_as_placed(qapp) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui.partlist import PartListPanel

    panel = PartListPanel()
    panel.refresh(_system(), footprint_lookup())
    rows = {
        panel.tree.topLevelItem(i).text(0): panel.tree.topLevelItem(i)
        for i in range(panel.tree.topLevelItemCount())
    }
    assert set(rows) == {"JA", "R1", "JB", "R2", "R9"}
    assert rows["JB"].text(3).startswith("Remote: ")
    assert rows["JA"].text(3).startswith("Main: ")
    assert not rows["JB"].toolTip(0), "not greyed as waiting in the design"
    assert rows["R9"].toolTip(0)


def test_the_window_counts_reaches_and_names_the_second_boards_parts(qapp) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(_system())
    try:
        facts = window.workflow_facts()
        assert facts.parts_on_board == 4 and facts.parts_off_board == 1
        parts = {e.label.split()[0]: e for e in window._palette_entries() if e.kind == "part"}
        assert {"JA", "R1", "JB", "R2", "R9"} <= set(parts)
        assert parts["JB"].where.startswith("Remote")
        assert window._id_of("JB") == "cmp-3" and window._ref_of_id("cmp-3") == "JB"
        window.go_to_component("cmp-3")
        assert window.statusBar().currentMessage() == "JB is on another board: Remote."
        assert not [f for f in window._last_erc if f.rule == "part-not-defined"]
        assert window._last_lvs is not None and not [
            i for i in window._last_lvs.issues if i.kind == "unplaced-component" and "JB" in i.message
        ]
    finally:
        window.close()
        window.deleteLater()


# ---------------------------------------------------------------------------
# The pattern, found in the sources
# ---------------------------------------------------------------------------

#: The functions that read a document's ``components`` and ``parts`` together and are
#: right to read ONE board: each says why. Anything else that reads both is a reader of the
#: circuit, and reads it through ``system.py`` (``circuit_parts``, ``every_component``,
#: ``placed_components``, ``references_in_use``).
BOARD_READERS: dict[str, str] = {
    "commands.py::create_document_id_generator": "reads every board itself",
    "commands.py::_check_cable": "reads every board through board_document",
    "commands.py::_PlaceParts.apply": "moves parts between the design and THIS board",
    "commands.py::_UnplaceComponent.apply": "moves a part between THIS board and the design",
    "placer.py::_taken_cells": "the design arranged onto this board",
    "placer.py::design_entries": "the design arranged onto this board",
    "ui/inspector.py::Inspector._show": "the selection, which is on the board shown",
    "ui/properties.py::describe": "the selection, which is on the board shown",
    "ui/main.py::example_boards": "the shipped examples, one board each",
    "ui/main.py::MainWindow.on_choose_board": "which board the shown board is",
    "ui/main.py::MainWindow._refresh_empty_hint": "whether the board shown is empty",
    "ui/main.py::MainWindow._on_part_dropped": "lands on the board shown; another board's part is said first",
    "ui/main.py::MainWindow._on_schematic_part_activated": "Properties of the board shown; another board's part is said first",
    "ui/main.py::MainWindow.mount_off_board": "a part of the board shown",
    "ui/main.py::MainWindow.on_schematic_place_all": "places the design onto the board shown",
    "ui/main.py::MainWindow._refresh_guide_panel": "the guide of the board shown",
    "ui/main.py::MainWindow._selection_on_the_sheet": "a selection is of the board shown",
    "ui/main.py::MainWindow._add_symbol_entries": "the board shown; another board's part is said first",
    "ui/main.py::MainWindow.on_autoplace": "places onto the board shown",
    "ui/view2d.py::BoardView._landing_of": "what lands on the board shown",
}

_BOARD_OWN = {"components", "conductors", "cuts", "mounting_holes", "edge_connectors", "board_notes", "board"}


def _is_document(text: str) -> bool:
    last = text.split(".")[-1]
    return last in {"doc", "document", "_document", "_doc", "seen"} or text.endswith("document") or "board_document(" in text


def _readers_of_both() -> set[str]:
    found: set[str] = set()
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in {"system.py", "persist.py", "model.py"} or rel.startswith("parsers/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))

        def visit(node: ast.AST, stack: tuple[str, ...], rel: str = rel) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    visit(child, (*stack, child.name))
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    read: set[str] = set()
                    for inner in ast.walk(child):
                        if (
                            isinstance(inner, ast.Attribute)
                            and inner.attr in _BOARD_OWN | {"parts"}
                            and _is_document(ast.unparse(inner.value))
                        ):
                            read.add(inner.attr)
                    if "components" in read and "parts" in read:
                        found.add(f"{rel}::{'.'.join((*stack, child.name))}")
                    visit(child, (*stack, child.name))

        visit(tree, ())
    return found


def test_every_reader_of_the_whole_circuit_goes_through_system() -> None:
    """A function reading ``components`` and ``parts`` together is asking about every part
    of the circuit -- unless it is one of ``BOARD_READERS``, which says why it asks about
    one board. Nested functions are reported in their own right."""
    readers = _readers_of_both()
    unexplained = sorted(readers - set(BOARD_READERS))
    assert not unexplained, (
        "these read doc.components and doc.parts together: on a system that is the first "
        "board alone. Read the circuit through system.circuit_parts / every_component, or "
        f"add the function to BOARD_READERS with the reason it reads one board: {unexplained}"
    )
    stale = sorted(set(BOARD_READERS) - readers)
    assert not stale, f"BOARD_READERS names functions that no longer read both: {stale}"


# ---------------------------------------------------------------------------
# A board is called one thing everywhere
# ---------------------------------------------------------------------------


def _one_unnamed() -> PerfDocument:
    """Main named "Controller", the second board nobody named, and W1 not fitted, so LVS
    names both boards in its line."""
    doc = _system(wires=None)
    remote = dataclasses.replace(system.extra_board(doc, "b2"), name="")
    return dataclasses.replace(doc, board_name="Controller", boards=(remote,))


def test_an_unnamed_board_is_called_by_its_place_in_every_language() -> None:
    doc = _one_unnamed()
    assert system.board_title(doc, system.FIRST_BOARD) == "Controller"
    assert system.board_title(doc, "b2") == "Board 2"
    assert system.board_title(doc, "b2", "tr") == "Kart 2"
    alone = dataclasses.replace(doc, board_name="", boards=())
    assert system.board_title(alone, system.FIRST_BOARD) == "Main", "one board is the document"


def test_the_parts_list_lvs_and_mcp_call_a_board_the_same_thing() -> None:
    """The one name, asked of ``system.board_title`` by every reader that says one."""
    from perfboard_studio.lvs import run_lvs
    from perfboard_studio.mcp.session import BoardSession

    doc = _one_unnamed()
    opens = [i.message for i in run_lvs(doc, footprint_lookup()).issues if i.kind == "open"]
    assert opens and all("across Board 2 and Controller" in m for m in opens), opens
    session = BoardSession(document=doc)
    assert [b["name"] for b in session.get_status()["boards"]] == ["Controller", "Board 2"]
    assert {c["board"] for c in session.list_components()} == {"Controller", "Board 2"}


def test_the_parts_list_says_the_same_name(qapp) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui.partlist import PartListPanel

    panel = PartListPanel()
    panel.refresh(_one_unnamed(), footprint_lookup())
    positions = {
        panel.tree.topLevelItem(i).text(0): panel.tree.topLevelItem(i).text(3)
        for i in range(panel.tree.topLevelItemCount())
    }
    assert positions["JB"].startswith("Board 2: ") and positions["JA"].startswith("Controller: ")


def test_a_board_name_goes_through_the_file_only_when_there_is_one() -> None:
    doc = _one_unnamed()
    text = persist.serialize_document(doc)
    assert '"boardName": "Controller"' in text
    assert persist.parse_document_or_throw(text) == doc
    remote = text[text.index('"boards"'):]
    assert '"name"' not in remote.split('"board"')[0], "an unnamed board writes no name"
    one = dataclasses.replace(doc, board_name="", boards=(), cables=())
    assert '"boardName"' not in persist.serialize_document(one)


def test_the_window_shows_the_second_board_and_saves_the_whole_system(qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """With the second board in front the scene draws it alone and a move goes to it; the
    file written is still every board and the cable, and the window reads as saved."""
    from perfboard_studio.commands import MoveComponentPayload
    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(_system())
    try:
        window.bus.show("b2")
        window.on_bus_changed(window.bus.system_document, None)
        assert {c.ref for c in window.scene.document.components} == {"JB", "R2"}
        moved = window.bus.dispatch("component.move", MoveComponentPayload(id="cmp-4", anchor=HoleCoord(5, 8)))
        assert moved.ok and moved.description.endswith("on Remote"), moved.description
        assert next(c for c in window.scene.document.components if c.id == "cmp-4").anchor == HoleCoord(5, 8)
        path = tmp_path / "system.perf"
        assert window._save_to(path)
        saved = persist.parse_document_or_throw(path.read_text(encoding="utf-8"))
        # The file is stamped with the time it was written; everything else is the system.
        assert dataclasses.replace(saved, meta=window.bus.system_document.meta) == window.bus.system_document
        assert len(saved.boards) == 1 and saved.cables and {c.ref for c in saved.components} == {"JA", "R1"}
        assert not window.is_modified
    finally:
        window.close()
        window.deleteLater()


def test_the_board_strip_shows_only_with_a_second_board_and_switches_the_panel(qapp) -> None:  # type: ignore[no-untyped-def]
    """One board: no strip, and Add Board in the Board menu. Two: System and each board,
    the board picked in front of the scene, System behind its own entry saying the
    system's counts."""
    from perfboard_studio.ui.main import MainWindow

    one = MainWindow(dataclasses.replace(_system(wires=None), boards=()))
    try:
        assert one.board_strip.isHidden() and one.act_add_board.isEnabled()
    finally:
        one.close()
        one.deleteLater()

    window = MainWindow(_system())
    try:
        strip = window.board_strip
        assert not strip.isHidden()
        labels = [strip.tabs.tabText(i) for i in range(strip.tabs.count())]
        assert labels[0] == "System" and labels[1].startswith("Main  ·  ") and labels[2].startswith("Remote  ·  ")
        strip.tabs.setCurrentIndex(2)
        assert window.bus.board_id == "b2"
        assert {c.ref for c in window.scene.document.components} == {"JB", "R2"}
        strip.tabs.setCurrentIndex(0)
        assert window.board_stack.currentWidget() is window.system_view
        assert window.problems_bar.where.text() == "2 boards  ·  1 cable"
        window.system_view.board_opened.emit("main")
        assert window.bus.board_id == "main" and window.board_stack.currentWidget() is window.view
    finally:
        window.close()
        window.deleteLater()


def test_adding_a_board_puts_it_in_front_named_by_its_place(qapp) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(dataclasses.replace(_system(wires=None), boards=()))
    try:
        window.on_add_board()
        added = window.bus.system_document.boards[-1]
        assert added.name == "" and window.bus.board_id == added.id
        assert not window.board_strip.isHidden()
        labels = [window.board_strip.tabs.tabText(i) for i in range(window.board_strip.tabs.count())]
        assert labels[2].startswith("Board 2  ·  "), labels
        window.bus.undo()
        window.on_bus_changed(window.bus.system_document, None)
        assert window.board_strip.isHidden() and window.bus.board_id == "main"
    finally:
        window.close()
        window.deleteLater()


def test_what_moved_points_at_the_board_tools_with_the_board_in_front(qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With System in front, the "What moved" card's line for the board's tools puts the
    board in front before it rings them, rather than ringing where they were last laid out."""
    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(_system())
    try:
        rung: list[object] = []
        monkeypatch.setattr(type(window), "_point_at", lambda self, widget: rung.append(widget))
        window.board_strip.tabs.setCurrentIndex(0)
        assert window._system_in_front()
        window._show_moved("tools")
        assert not window._system_in_front() and window.board_stack.currentWidget() is window.view
        assert rung == [window.board_tools]
    finally:
        window.close()
        window.deleteLater()


def test_a_part_on_the_first_board_is_taken_off_with_the_second_in_front(qapp) -> None:  # type: ignore[no-untyped-def]
    """Take off the Board on a symbol names its part's board, whichever board is in front:
    the window's bus sends a bare board command to the board in front, so a part on the
    first board taken off with the second in front used to be "no component" there."""
    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(_system())
    try:
        window.bus.show("b2")
        window._remove_symbol("R1")
        assert "R1" in {p.ref for p in window.bus.system_document.parts}, window.statusBar().currentMessage()
        assert "R1" not in {c.ref for c in window.bus.system_document.components}
        # A cabled connector stays: the system refuses to leave W1 to nowhere, and says so.
        window._remove_symbol("JA")
        assert "W1" in window.statusBar().currentMessage()
    finally:
        # Edited and unsaved: closing would ask, and nobody answers offscreen.
        window._mark_saved()
        window.close()
        window.deleteLater()


def test_the_board_and_cable_steps_read_in_the_windows_language() -> None:
    """An undo step done on one board of several says which board, and the commands that
    make a system are said in Turkish like every other step -- a board nobody named as
    "Kart 2", not the engine's "Board 2"."""
    from perfboard_studio.ui import i18n
    from perfboard_studio.ui.engine_text import say

    before = i18n.language()
    i18n.set_language("tr")
    try:
        assert say("Take J1 off the board on Board 1") == "J1 parçasını karttan kaldır (Kart 1)"
        assert say("Move R1 to C7 on Remote") == "R1 parçasını C7 deliğine taşı (Remote)"
        assert say("Add a board") == "Kart ekle"
        assert say("Add the board 'Besleme'") == "'Besleme' kartını ekle"
        assert say("Unname Board 2") == "Kartın adını kaldır (Kart 2)"
        assert say("Remove the board 'Board 2'") == "Kartı çıkar (Kart 2)"
        assert say("Add the cable W1") == "W1 kablosunu ekle"
    finally:
        i18n.set_language(before)



def test_add_cable_pairs_the_wires_by_net_as_one_step(qapp) -> None:  # type: ignore[no-untyped-def]
    """Between JA on Main and JB on Remote, both on GND and SIG: two wires, by net, one undo
    step -- and the system's LVS is whole after it."""
    from perfboard_studio.lvs import run_lvs
    from perfboard_studio.model import CableEnd
    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(_system(wires=None))
    try:
        steps = len(window.bus.history())
        result = window.add_cable_between(CableEnd(system.FIRST_BOARD, "cmp-1"), CableEnd("b2", "cmp-3"))
        assert result.ok, result.message
        (cable,) = window.bus.system_document.cables
        assert cable.ref == "W1" and {(w.a_pin, w.b_pin) for w in cable.wires} == {("1", "1"), ("2", "2")}
        assert len(window.bus.history()) == steps + 1
        assert run_lvs(window.bus.system_document, footprint_lookup()).ok
        assert window.statusBar().currentMessage().endswith("Add the cable W1")
    finally:
        window._mark_saved()
        window.close()
        window.deleteLater()


def test_add_cable_opens_with_one_end_chosen_and_lays_what_it_shows(qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QDialog

    from perfboard_studio.model import CableEnd
    from perfboard_studio.ui import cabledialog
    from perfboard_studio.ui.main import MainWindow

    seen: list[object] = []

    def accept(self):  # type: ignore[no-untyped-def]
        seen.append((self.ends(), self.preview.text(), self.reference.text()))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(cabledialog.CableDialog, "exec", accept)
    window = MainWindow(_system(wires=None))
    try:
        window.on_add_cable(CableEnd("b2", "cmp-3"))
        ((ends, preview, reference),) = seen
        assert ends[0] == CableEnd("b2", "cmp-3"), "the end it was opened on"
        assert ends[1].board == system.FIRST_BOARD
        assert "2 wires, paired by net:" in preview and reference == "W1"
        assert len(window.bus.system_document.cables) == 1
    finally:
        window._mark_saved()
        window.close()
        window.deleteLater()


# ---------------------------------------------------------------------------
# A part moved to another board
# ---------------------------------------------------------------------------


def _with_wire_to_r1() -> PerfDocument:
    """``_system`` with a wire on Main from R1's first pin to an empty hole."""
    from perfboard_studio.model import WireConductor

    doc = _system()
    footprint = footprint_lookup()("r-axial-4")
    from perfboard_studio.geometry import all_pin_holes

    r1 = next(c for c in doc.components if c.ref == "R1")
    pin_hole = next(hole for _pin, hole in all_pin_holes(r1, footprint))
    wire = WireConductor(
        id="cond-1", kind="insulated-wire", side="top", path=(pin_hole, HoleCoord(pin_hole.col, pin_hole.row + 3))
    )
    return dataclasses.replace(doc, conductors=(wire,))


def test_a_part_moves_to_another_board_with_its_copper_as_one_step() -> None:
    from perfboard_studio.commands import MoveToBoardPayload
    from perfboard_studio.occupancy import conductors_touching

    doc = _with_wire_to_r1()
    bus = _bus(doc)
    copper = conductors_touching(system.board_document(doc), "cmp-2", footprint_lookup())
    assert copper == ("cond-1",)
    result = bus.dispatch("component.moveToBoard", MoveToBoardPayload("cmp-2", "b2", HoleCoord(8, 8), copper))
    assert result.ok, result.message
    assert result.description == "Move R1 to the board Remote, taking off 1 conductor that ran to it"
    after = bus.system_document
    assert "R1" not in {c.ref for c in after.components} and not after.conductors
    moved = next(c for c in system.extra_board(after, "b2").components if c.ref == "R1")
    assert moved.anchor == HoleCoord(8, 8) and moved.id == "cmp-2"
    bus.undo()
    assert bus.system_document == doc


def test_a_cabled_connector_takes_its_cable_end_with_it() -> None:
    from perfboard_studio.commands import MoveToBoardPayload

    doc = _system()
    bus = _bus(doc)
    result = bus.dispatch("component.moveToBoard", MoveToBoardPayload("cmp-1", "b2", HoleCoord(10, 2)))
    assert result.ok, result.message
    (cable,) = bus.system_document.cables
    assert cable.a.board == "b2" and cable.a.connector == "cmp-1"


def test_a_move_to_the_board_it_is_on_or_of_a_locked_part_is_refused() -> None:
    from perfboard_studio.commands import MoveToBoardPayload

    same = _bus(_system()).dispatch("component.moveToBoard", MoveToBoardPayload("cmp-2", system.FIRST_BOARD, HoleCoord(1, 1)))
    assert not same.ok and same.code == "same-board"
    doc = _system()
    locked = dataclasses.replace(doc, components=tuple(dataclasses.replace(c, locked=c.id == "cmp-2") for c in doc.components))
    refused = _bus(locked).dispatch("component.moveToBoard", MoveToBoardPayload("cmp-2", "b2", HoleCoord(1, 1)))
    assert not refused.ok and refused.code == "component-locked"


def test_dropping_another_boards_part_moves_it_here_and_the_menus_offer_it(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMenu

    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(_with_wire_to_r1())
    try:
        window.bus.show("b2")
        window.on_bus_changed(window.bus.system_document, None)
        window._on_part_dropped("R1", HoleCoord(9, 9))
        remote = system.extra_board(window.bus.system_document, "b2")
        assert "R1" in {c.ref for c in remote.components}, window.statusBar().currentMessage()
        assert not window.bus.system_document.conductors, "the wire that ran to it went with it"
        menu = QMenu()
        window._add_move_to_board(menu, "cmp-2")
        (submenu,) = [a.menu() for a in menu.actions() if a.menu() is not None]
        assert [a.text() for a in submenu.actions()] == ["Main"]
    finally:
        window._mark_saved()
        window.close()
        window.deleteLater()


def test_the_board_in_front_comes_back_with_its_file(qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Left on Remote, the file opens on Remote; a board that is no longer there is forgotten
    rather than refused, and a file never saved remembers nothing."""
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui.main import MainWindow

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    path = tmp_path / "bench.perf"
    path.write_text(persist.serialize_document(_system()), encoding="utf-8")
    first = MainWindow(_system(), path)
    try:
        first.board_strip.tabs.setCurrentIndex(2)
        assert first.bus.board_id == "b2"
    finally:
        first.close()
        first.deleteLater()
    again = MainWindow(persist.parse_document_or_throw(path.read_text(encoding="utf-8")), path)
    try:
        assert again.bus.board_id == "b2"
        assert again.board_strip.tabs.tabText(again.board_strip.tabs.currentIndex()).startswith("Remote")
    finally:
        again.close()
        again.deleteLater()
    store.setValue(main_module.board_in_front_key(path), "b9")
    gone = MainWindow(persist.parse_document_or_throw(path.read_text(encoding="utf-8")), path)
    try:
        assert gone.bus.board_id == system.FIRST_BOARD
    finally:
        gone.close()
        gone.deleteLater()



def test_a_new_part_takes_a_reference_free_in_the_whole_system(qapp) -> None:  # type: ignore[no-untyped-def]
    """With JB placed on Remote, a header placed on Main from the library is not offered JB
    -- nor anything another board holds -- and a pasted block's refs and ids are free in the
    system too."""
    from perfboard_studio.ui.clipboard import Block, paste_payload
    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(_system())
    try:
        assert window.bus.board_id == system.FIRST_BOARD
        window.scene.arm_placement("hdr-1x2")
        placed = window.scene.place_armed(HoleCoord(30, 30))
        window.scene.arm_placement(None)
        assert placed is not None and placed.ok, placed
        refs = [c.ref for c in window.bus.system_document.components]
        assert "JB" not in refs and len(set(refs)) == len(refs), refs
        jb = next(c for c in system.extra_board(window.bus.system_document, "b2").components if c.ref == "JB")
        paste = paste_payload(
            window.bus.document,
            Block(components=(jb,), conductors=()),
            HoleCoord(40, 40),
            system=window.bus.system_document,
        )
        held = {c.ref for c in system.every_component(window.bus.system_document)}
        held_ids = {c.id for c in system.every_component(window.bus.system_document)}
        for placement in paste.payload.components:
            assert placement.ref not in held and placement.id not in held_ids, placement
    finally:
        window._mark_saved()
        window.close()
        window.deleteLater()


def test_the_move_to_board_label_reads_whole_in_turkish() -> None:
    from perfboard_studio.ui import i18n
    from perfboard_studio.ui.engine_text import say

    before = i18n.language()
    i18n.set_language("tr")
    try:
        assert say("Move J1 to the board Board 2, taking off 4 conductors that ran to it") == (
            "J1 parçasını başka karta taşı: Kart 2, ona giden 4 iletken kaldırıldı"
        )
    finally:
        i18n.set_language(before)


def test_a_part_moved_away_stays_put_and_show_goes_to_it(qapp) -> None:  # type: ignore[no-untyped-def]
    """Moved off the board in front: the window stays, says which board needs wiring again,
    and Show puts the new board in front with the part picked."""
    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(_with_wire_to_r1())
    try:
        window.move_to_board("cmp-2", "b2")
        assert window.bus.board_id == system.FIRST_BOARD, "not followed"
        message = window.statusBar().currentMessage()
        assert message.endswith("Wire it again: Main."), message
        offer = window._status_offer
        assert offer is not None and not offer.isHidden() and offer.text() == "Show"
        offer.click()
        assert window.bus.board_id == "b2" and offer.isHidden()
        assert "cmp-2" in window.scene.selected_component_ids()
    finally:
        window._mark_saved()
        window.close()
        window.deleteLater()

