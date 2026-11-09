"""A ``.perf`` is LF on every platform, whoever writes it.

``persist`` produces the bytes ``JSON.stringify(x, null, 2)`` does, and those have no carriage
return in them. ``Path.write_text`` with no ``newline`` translates every ``\\n`` to the
platform's separator, so on Windows every save -- the window's, autosave's and its backup, the
recovery record, a project folder's board and the MCP server's -- wrote CRLF: a file that did
not round-trip byte for byte, and a diff of every line when the same board was saved on two
machines. Exports are left alone; a CSV is CRLF by RFC 4180 anyway.

Each writer is driven here the way it runs, and the bytes on disk are read back.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from perfboard_studio import persist
from perfboard_studio.commands import MoveComponentPayload
from perfboard_studio.model import HoleCoord, PerfDocument

from .test_system_readers import _system

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _example() -> PerfDocument:
    return persist.parse_document_or_throw(
        (REPO / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )


def _assert_lf(path: Path) -> None:
    data = path.read_bytes()
    assert b"\n" in data, path
    assert b"\r" not in data, path


def test_the_window_saves_autosaves_and_backs_up_in_lf(qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui.main import MainWindow

    path = tmp_path / "board.perf"
    window = MainWindow(_system())
    try:
        window.current_path = path
        assert window._save_to(path)
        _assert_lf(path)
        saved = path.read_bytes()
        # Reopened, it is the same document; serialized again, the same bytes but the stamp.
        reopened = persist.parse_document_or_throw(saved.decode("utf-8"))
        assert reopened.boards == window.bus.system_document.boards

        # An autosave over the file keeps the last real save as .bak: both LF.
        window.bus.dispatch(
            "component.move", MoveComponentPayload(id="cmp-2", anchor=HoleCoord(4, 9))
        )
        window._on_autosave_tick()
        assert path.read_bytes() != saved
        _assert_lf(path)
        _assert_lf(tmp_path / "board.perf.bak")
        assert (tmp_path / "board.perf.bak").read_bytes() == saved
    finally:
        window._mark_saved()
        window.close()
        window.deleteLater()


def test_the_recovery_record_is_lf(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui.autosave import Autosave

    autosave = Autosave(tmp_path)
    assert autosave.write(persist.serialize_document(_example()), None)
    _assert_lf(autosave.path)


def test_a_project_folders_board_is_lf(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.ui.project import write_project

    document = _example()
    path = tmp_path / "board" / "board.perf"
    path.parent.mkdir()
    write_project(path, document, persist.serialize_document(document), footprint_lookup(), None)
    _assert_lf(path)


def test_the_mcp_server_saves_in_lf(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.mcp.session import BoardSession

    path = tmp_path / "agent.perf"
    session = BoardSession(document=_system())
    session.save_document(str(path))
    _assert_lf(path)
    # And it is exactly what persist wrote, but for the time it was saved at.
    written = persist.parse_document_or_throw(path.read_text(encoding="utf-8"))
    assert path.read_bytes().decode("utf-8") == persist.serialize_document(written)
