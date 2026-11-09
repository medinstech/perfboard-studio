"""The MCP server on a document of several boards: select_board, add_board, add_cable and
get_system_info, and every board tool acting on the board in front.

What is pinned: a second board is added and put in front, and a part placed after that is on
it; a cable is laid by the connectors' references on their boards, refused when one pin
would carry two wires, and a crossed one is reported by the system's LVS rather than refused;
a board is found by its id or by what it is called; the status and the file are every
board's, and the guide of the board in front ends with the system's harness.
"""

from __future__ import annotations

import json

import pytest

from perfboard_studio import persist, system
from perfboard_studio.commands import DEFAULT_BOARD
from perfboard_studio.mcp.session import BoardSession, SessionError
from perfboard_studio.model import (
    ComponentInstance,
    DocumentMeta,
    HoleCoord,
    Net,
    NetNode,
    PerfDocument,
)


def _session() -> BoardSession:
    """One board with a header JA on GND and SIG, and the design wanting JB too."""
    ja = ComponentInstance(id="cmp-1", ref="JA", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    doc = PerfDocument(
        meta=DocumentMeta(name="Bench", created="", modified=""),
        board=DEFAULT_BOARD,
        components=(ja,),
        nets=(
            Net(id="n1", name="SIG", nodes=(NetNode("JA", "1"), NetNode("JB", "1"))),
            Net(id="n2", name="GND", nodes=(NetNode("JA", "2"), NetNode("JB", "2")), net_class="ground"),
        ),
    )
    return BoardSession(document=doc)


def _two_boards() -> BoardSession:
    session = _session()
    added = session.add_board("Remote")
    assert added["ok"] and session.system_document.boards[-1].name == "Remote", added
    placed = session.place_component("JB", "hdr-1x2", "C3")
    assert placed["ok"], placed
    return session


def test_a_board_added_is_in_front_and_a_part_placed_then_is_on_it() -> None:
    session = _two_boards()
    remote = session.system_document.boards[-1]
    assert [c.ref for c in remote.components] == ["JB"]
    assert [c.ref for c in session.system_document.components] == ["JA"], "the first board kept its own"
    assert session.get_status()["board_in_front"] == remote.id


def test_a_board_is_found_by_its_id_or_by_what_it_is_called() -> None:
    session = _two_boards()
    remote_id = session.system_document.boards[-1].id
    assert session.select_board("main")["board_in_front"] == system.FIRST_BOARD
    assert session.select_board("Board 1")["board_in_front"] == system.FIRST_BOARD
    assert session.select_board("Remote")["board_in_front"] == remote_id
    with pytest.raises(SessionError, match="Remote"):
        session.select_board("Nowhere")


def test_a_cable_is_laid_by_references_and_a_crossed_one_is_a_short() -> None:
    session = _two_boards()
    before = session.get_system_info()["lvs"]
    assert not before["ok"] and before["opens"] == 2
    twice = session.add_cable(
        "W1", "main", "JA", "Remote", "JB", [{"a_pin": "1", "b_pin": "1"}, {"a_pin": "1", "b_pin": "2"}]
    )
    assert not twice["ok"] and twice["code"] == "invalid-cable", twice
    crossed = session.add_cable(
        "W1", "main", "JA", "Remote", "JB", [{"a_pin": "1", "b_pin": "2"}, {"a_pin": "2", "b_pin": "1"}]
    )
    assert crossed["ok"], crossed
    info = session.get_system_info()
    assert info["cables"][0]["a"] == "Board 1 JA" and info["cables"][0]["b"] == "Remote JB"
    assert info["lvs"]["shorts"] >= 1 and not info["lvs"]["ok"]
    assert session.undo()["ok"]
    straight = session.add_cable(
        "W1", "main", "JA", "Remote", "JB",
        [{"a_pin": "1", "b_pin": "1", "colour": "red"}, {"a_pin": "2", "b_pin": "2"}],
        length_mm=150,
    )
    assert straight["ok"], straight
    assert session.get_system_info()["lvs"]["ok"]



def test_a_cable_shorter_than_its_ends_are_apart_in_the_row_is_said_and_is_not_a_fault() -> None:
    """``short_in_row`` names a cable whose length is less than the distance between its
    ends in the System's row, with both numbers; a cable cut to fit is never in it, and LVS
    does not move: the row is a picture, not where the boards will be."""
    session = _two_boards()
    wires = [{"a_pin": "1", "b_pin": "1"}, {"a_pin": "2", "b_pin": "2"}]
    assert session.add_cable("W1", "main", "JA", "Remote", "JB", wires, length_mm=20)["ok"]
    info = session.get_system_info()
    span = system.cable_span_mm(session.system_document, session.system_document.cables[0], session.lookup)
    assert span is not None and span > 20
    assert info["short_in_row"] == [{"ref": "W1", "length_mm": 20, "span_mm": round(span, 1)}]
    assert info["lvs"]["ok"]
    assert session.undo()["ok"]
    assert session.add_cable("W1", "main", "JA", "Remote", "JB", wires)["ok"]
    assert session.get_system_info()["short_in_row"] == []

def test_the_status_the_file_and_the_guide_are_the_systems(tmp_path) -> None:  # type: ignore[no-untyped-def]
    session = _two_boards()
    session.add_cable(
        "W1", "main", "JA", "Remote", "JB", [{"a_pin": "1", "b_pin": "1"}, {"a_pin": "2", "b_pin": "2"}], length_mm=150
    )
    status = session.get_status()
    assert status["components"] == 2 and status["cables"] == 1
    path = tmp_path / "bench.perf"
    assert session.save_document(str(path))["ok"]
    saved = persist.parse_document_or_throw(path.read_text(encoding="utf-8"))
    assert len(saved.boards) == 1 and len(saved.cables) == 1
    written = session.generate_guide(directory=str(tmp_path / "guide"))
    (json_path,) = [p for p in written["written"] if p.endswith(".json")]
    guide = json.loads(open(json_path, encoding="utf-8").read())  # noqa: SIM115
    assert [cable["ref"] for cable in guide["harness"]] == ["W1"]


def test_a_board_is_named_and_taken_out_and_its_parts_go_back_to_the_design() -> None:
    session = _two_boards()
    remote_id = session.system_document.boards[-1].id
    renamed = session.rename_board("Remote", "Sensor")
    assert renamed["ok"] and renamed["name"] == "Sensor", renamed
    assert session.rename_board("Sensor", "")["name"] == "Board 2"
    session.add_cable(
        "W1", "main", "JA", "Board 2", "JB", [{"a_pin": "1", "b_pin": "1"}, {"a_pin": "2", "b_pin": "2"}]
    )
    first = session.remove_board("main")
    assert not first["ok"] and first["code"] == "first-board", first
    reached = session.remove_board(remote_id)
    assert not reached["ok"] and reached["code"] == "cable-end" and "W1" in reached["message"], reached
    with pytest.raises(SessionError, match="W1"):
        session.remove_cable("W9")
    assert session.remove_cable("W1")["ok"]
    assert session.get_system_info()["cables"] == []
    removed = session.remove_board(remote_id)
    assert removed["ok"] and removed["parts_back_in_design"] == ["JB"], removed
    assert removed["board_in_front"] == system.FIRST_BOARD
    assert session.system_document.boards == ()
    assert "JB" in [p.ref for p in session.system_document.parts], "back in the design, not lost"
    # One undo step each: the board comes back with its part on it.
    assert session.undo()["ok"]
    assert [c.ref for c in session.system_document.boards[0].components] == ["JB"]


def test_a_part_moved_to_another_board_takes_its_copper_off_and_its_cable_follows() -> None:
    session = _two_boards()
    session.add_cable(
        "W1", "main", "JA", "Remote", "JB", [{"a_pin": "1", "b_pin": "1"}, {"a_pin": "2", "b_pin": "2"}]
    )
    session.select_board("main")
    pin_one = session.get_component("JA")["pins"][0]["hole"]
    wired = session.add_wire(pin_one, "J9")
    assert wired["ok"], wired
    remote_id = session.system_document.boards[-1].id
    moved = session.move_to_board("JA", "Remote", "H3")
    assert moved["ok"] and moved["from"] == "Board 1" and moved["to"] == "Remote", moved
    assert moved["conductors_removed"] == 1
    doc = session.system_document
    assert doc.components == () and doc.conductors == (), "nothing left ending in an empty hole"
    assert sorted(c.ref for c in doc.boards[0].components) == ["JA", "JB"]
    assert doc.cables[0].a.board == remote_id, "the cable fitted to JA went with it"
    assert session.undo()["ok"]
    assert [c.ref for c in session.system_document.components] == ["JA"]
    with pytest.raises(SessionError, match="JZ"):
        session.move_to_board("JZ", "Remote", "H3")


def test_the_circuit_checks_and_the_sheet_are_the_systems_whichever_board_is_in_front() -> None:
    """ERC, LVS and the schematic are about the circuit, so they read every board, as the
    window does. On the board in front alone, JA on the first board read as a part the
    design never defined, an unplaced part and a symbol "neither on the board nor in the
    design" -- three false findings an agent would go and fix."""
    session = _two_boards()
    laid = session.add_cable(
        "W1", "Board 1", "JA", "Remote", "JB",
        [{"a_pin": "1", "b_pin": "1"}, {"a_pin": "2", "b_pin": "2"}],
    )
    assert laid["ok"], laid
    seen = []
    for board in ("Board 1", "Remote"):
        assert session.select_board(board)["ok"]
        erc = session.run_erc()
        lvs = session.run_lvs()
        _png, sheet = session.render_schematic()
        assert not [f for f in erc["findings"] if f["rule"] == "part-not-defined"], erc
        assert lvs["matches_schematic"] and not lvs["issues"], lvs
        assert sheet["parts"] == 2 and not sheet["notes"], sheet
        seen.append((erc, lvs, sheet))
    assert seen[0] == seen[1]
