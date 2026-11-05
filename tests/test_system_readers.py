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
