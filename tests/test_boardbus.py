"""The window's bus shows the board in front and routes each command to where it belongs.

What is pinned: on one board it is the bus it extends, the very document and every command
as it came; with a second board in front its ``document`` is that board alone and its board
commands go through ``board.on`` -- one undo step, labelled with the board -- while a design
command and a system command go to the document; ``system_document`` is always the whole
system; and a board taken away leaves the first board in front.
"""

from __future__ import annotations

import dataclasses

import pytest

from perfboard_studio import system
from perfboard_studio.command import CommandContext
from perfboard_studio.commands import (
    DEFAULT_BOARD,
    AddNetPayload,
    DeleteBoardPayload,
    MoveComponentPayload,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.model import (
    ComponentInstance,
    DocumentMeta,
    ExtraBoard,
    HoleCoord,
    PerfDocument,
)
from perfboard_studio.ui.boardbus import BoardBus


def _doc(*, second: bool = True) -> PerfDocument:
    ja = ComponentInstance(id="cmp-1", ref="JA", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    jb = ComponentInstance(id="cmp-2", ref="JB", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    doc = PerfDocument(
        meta=DocumentMeta(name="Bench", created="", modified=""),
        board_name="Main",
        board=DEFAULT_BOARD,
        components=(ja,),
    )
    if second:
        doc = dataclasses.replace(doc, boards=(ExtraBoard(id="b2", name="Remote", board=DEFAULT_BOARD, components=(jb,)),))
    return doc


def _bus(doc: PerfDocument) -> BoardBus:
    return BoardBus(doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc)))


def test_on_one_board_it_is_the_bus_it_extends() -> None:
    doc = _doc(second=False)
    bus = _bus(doc)
    assert bus.document is doc is bus.system_document
    result = bus.dispatch("component.move", MoveComponentPayload(id="cmp-1", anchor=HoleCoord(3, 3)))
    assert result.ok and bus.history()[-1] == result.description
    assert not result.description.endswith("on Main"), "a single board's label is what it was"


def test_a_board_in_front_is_seen_alone_and_its_commands_go_to_it() -> None:
    doc = _doc()
    bus = _bus(doc)
    bus.show("b2")
    assert bus.document == system.board_document(doc, "b2")
    assert bus.system_document is doc
    moved = bus.dispatch("component.move", MoveComponentPayload(id="cmp-2", anchor=HoleCoord(4, 4)))
    assert moved.ok and moved.description.endswith("on Remote"), moved.description
    after = bus.system_document
    assert system.extra_board(after, "b2").components[0].anchor == HoleCoord(4, 4)
    assert after.components == doc.components, "the first board did not move"
    bus.undo()
    assert bus.system_document == doc


def test_a_design_command_and_a_system_command_go_to_the_document() -> None:
    bus = _bus(_doc())
    bus.show("b2")
    net = bus.dispatch("net.add", AddNetPayload(name="GND"))
    assert net.ok, net.message
    assert any(n.name == "GND" for n in bus.system_document.nets)
    gone = bus.dispatch("board.delete", DeleteBoardPayload(board="b2"))
    assert gone.ok, gone.message
    assert bus.board_id == system.FIRST_BOARD, "the board in front was taken away"
    assert bus.document is bus.system_document


def test_a_board_the_system_lacks_cannot_be_put_in_front() -> None:
    with pytest.raises(KeyError):
        _bus(_doc()).show("b9")
