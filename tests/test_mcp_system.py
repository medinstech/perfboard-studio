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
