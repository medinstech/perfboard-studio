"""The board's name: the title its guide, its schematic and its project carry.

Until this, nothing in the application could set it. Every document the window or the MCP
server created was ``DocumentMeta(name="untitled")`` for good, so every build guide and
every exported sheet anybody made went out titled "untitled". These pin the three routes
that now reach it -- the command, the first save, and the MCP arguments -- and that a name
somebody chose is never overwritten by the first-save rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    RenameDocumentPayload,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.mcp.session import BoardSession, new_board
from perfboard_studio.model import UNTITLED_NAME, DocumentMeta


def new_bus() -> CommandBus:
    return CommandBus(
        create_empty_document(DocumentMeta(name=UNTITLED_NAME, created="", modified="")),
        create_standard_registry(),
        CommandContext(next_id=create_id_generator()),
    )


def test_a_rename_is_a_command_that_undoes() -> None:
    bus = new_bus()
    result = bus.dispatch("document.rename", RenameDocumentPayload(name="  Relay driver  "))
    assert result.ok
    assert bus.document.meta.name == "Relay driver"
    assert bus.history()[-1] == "Name the board 'Relay driver'"
    bus.undo()
    assert bus.document.meta.name == UNTITLED_NAME


def test_a_blank_name_is_refused() -> None:
    bus = new_bus()
    result = bus.dispatch("document.rename", RenameDocumentPayload(name="   "))
    assert not result.ok and result.code == "empty-name"
    assert bus.document.meta.name == UNTITLED_NAME


def test_an_unnamed_board_takes_its_files_name_when_saved(tmp_path: Path) -> None:
    session = BoardSession()
    target = tmp_path / "relay-driver.perf"
    result = session.save_document(str(target))
    assert result["ok"] and result["name"] == "relay-driver"
    on_disk = persist.parse_document_or_throw(target.read_text(encoding="utf-8"))
    assert on_disk.meta.name == "relay-driver"
    # It went through the bus, so it is on the undo stack like any other edit.
    assert session.history()[-1] == "Name the board 'relay-driver'"


def test_a_board_somebody_named_keeps_its_name_whatever_the_file_is_called(
    tmp_path: Path,
) -> None:
    session = BoardSession(document=new_board(name="Manipulator plaket"))
    session.save_document(str(tmp_path / "v1.perf"))
    assert session.document.meta.name == "Manipulator plaket"
    assert session.history() == []


def test_save_can_name_the_board_explicitly(tmp_path: Path) -> None:
    session = BoardSession()
    result = session.save_document(str(tmp_path / "a.perf"), name="Logic rail switch")
    assert result["name"] == "Logic rail switch"
    # ...and a blank name means "no explicit name", not "rename to nothing".
    session.save_document(str(tmp_path / "b.perf"), name="  ")
    assert session.document.meta.name == "Logic rail switch"


def test_new_document_takes_a_name_and_falls_back_to_untitled() -> None:
    assert new_board(name="NE555").meta.name == "NE555"
    assert new_board(name="   ").meta.name == UNTITLED_NAME
    assert new_board().meta.name == UNTITLED_NAME


def test_the_mcp_tools_pass_the_name_through(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from perfboard_studio.mcp import server

    status = server.new_document(cols=10, rows=10, name="Via the server")
    assert status["document"] == "Via the server"
    saved = server.save_document(str(tmp_path / "x.perf"), name="Renamed on save")
    assert saved["name"] == "Renamed on save"
