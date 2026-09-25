"""Labels written on the board: the words a builder would put there with a marker.

What is pinned: a board with no labels is byte for byte what it was before they existed;
a label round-trips through the file saying no more than it has to; the commands refuse a
label that could not be found again (empty, off the board) and undo like any other edit;
and nothing derives anything from a label -- DRC and LVS say the same with or without one.
"""

from __future__ import annotations

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    AddBoardNotePayload,
    DeleteBoardNotesPayload,
    SetBoardPayload,
    UpdateBoardNotePayload,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import board_note_anchor, board_note_centre_mm
from perfboard_studio.mcp.session import BoardSession, new_board
from perfboard_studio.model import BoardNote, DocumentMeta, HoleCoord


def _bus() -> CommandBus:
    return CommandBus(
        create_empty_document(DocumentMeta(name="t", created="", modified="")),
        create_standard_registry(),
        CommandContext(next_id=create_id_generator()),
    )


def test_a_board_without_labels_says_nothing_about_them() -> None:
    text = persist.serialize_document(_bus().document)
    assert "boardNotes" not in text


def test_a_label_round_trips_saying_only_what_it_has_to() -> None:
    bus = _bus()
    assert bus.dispatch("board.note.add", AddBoardNotePayload(text="MOTOR 24V", at=HoleCoord(3, 5))).ok
    assert bus.dispatch(
        "board.note.add",
        AddBoardNotePayload(
            text="ALT YÜZ", at=HoleCoord(8, 2), offset_x_mm=1.27, offset_y_mm=-0.5,
            size_mm=2.5, rotation=90, side="bottom",
        ),
    ).ok
    text = persist.serialize_document(bus.document)
    plain = next(n for n in bus.document.board_notes if n.text == "MOTOR 24V")
    full = next(n for n in bus.document.board_notes if n.text == "ALT YÜZ")
    # The plain one is three keys and its text.
    assert '"sizeMm": 1.5' not in text and '"side": "top"' not in text
    loaded = persist.parse_document_or_throw(text)
    assert loaded.board_notes == bus.document.board_notes
    assert persist.serialize_document(loaded) == text
    assert full.side == "bottom" and full.rotation == 90 and plain.offset_x_mm == 0.0


def test_a_label_has_something_in_it_and_is_on_the_board() -> None:
    bus = _bus()
    empty = bus.dispatch("board.note.add", AddBoardNotePayload(text="  ", at=HoleCoord(1, 1)))
    assert not empty.ok and empty.code == "empty-text"
    off = bus.dispatch("board.note.add", AddBoardNotePayload(text="X", at=HoleCoord(999, 1)))
    assert not off.ok
    small = bus.dispatch(
        "board.note.add", AddBoardNotePayload(text="X", at=HoleCoord(1, 1), size_mm=0)
    )
    assert not small.ok and small.code == "bad-size"


def test_editing_moving_and_deleting_a_label_undo_like_anything_else() -> None:
    bus = _bus()
    bus.dispatch("board.note.add", AddBoardNotePayload(text="CAN", at=HoleCoord(2, 2)))
    (note,) = bus.document.board_notes
    assert bus.dispatch(
        "board.note.update", UpdateBoardNotePayload(id=note.id, text="CAN →", rotation=90)
    ).ok
    assert bus.dispatch(
        "board.note.update",
        UpdateBoardNotePayload(id=note.id, at=HoleCoord(4, 4), offset_x_mm=0.5, offset_y_mm=0.0),
    ).ok
    moved = bus.document.board_notes[0]
    assert (moved.text, moved.rotation, moved.at, moved.offset_x_mm) == (
        "CAN →", 90, HoleCoord(4, 4), 0.5
    )
    same = bus.dispatch("board.note.update", UpdateBoardNotePayload(id=note.id, text="CAN →"))
    assert not same.ok and same.code == "nothing-to-do"
    assert bus.dispatch("board.note.delete", DeleteBoardNotesPayload(ids=(note.id,))).ok
    assert bus.document.board_notes == ()
    bus.undo()
    assert bus.document.board_notes == (moved,)


def test_shrinking_the_board_out_from_under_a_label_is_refused() -> None:
    """As it is for a mounting hole: a label that would fall off the board would be a label
    nobody can see and a later resize would bring back somewhere unexpected."""
    bus = _bus()
    board = bus.document.board
    bus.dispatch(
        "board.note.add",
        AddBoardNotePayload(text="EDGE", at=HoleCoord(board.cols - 1, board.rows - 1)),
    )
    import dataclasses

    smaller = dataclasses.replace(board, cols=board.cols - 2)
    result = bus.dispatch("board.set", SetBoardPayload(board=smaller))
    assert not result.ok and result.code == "would-strand-label"


def test_a_label_changes_nothing_any_check_says() -> None:
    session = BoardSession(document=new_board(cols=20, rows=12))
    session.place_component("R1", "r-axial-4", "C3")
    before = run_drc(session.document, footprint_lookup())
    session.add_board_label("R1 IS HERE", "C3")
    after = run_drc(session.document, footprint_lookup())
    assert before == after


def test_a_point_is_addressed_by_its_nearest_hole_and_an_offset() -> None:
    board = new_board(cols=10, rows=10).board
    at, dx, dy = board_note_anchor(5.3, 7.9, board)
    assert at == HoleCoord(2, 3) and (dx, dy) == (0.22, 0.28)
    # Out in the border: the nearest edge hole, and a bigger offset.
    at, dx, dy = board_note_anchor(-3.0, 1.0, board)
    assert at == HoleCoord(0, 0) and dx == -3.0
    note = BoardNote(id="n", text="x", at=HoleCoord(2, 3), offset_x_mm=0.22, offset_y_mm=0.28)
    centre = board_note_centre_mm(note, board)
    assert (round(centre.x, 2), round(centre.y, 2)) == (5.3, 7.9)


# ----------------------------------------------------------------- over MCP


def test_an_agent_can_write_on_the_board_and_take_it_back() -> None:
    session = BoardSession(document=new_board(cols=20, rows=12))
    result = session.add_board_label("MOTOR 24V", "D6", offset_x_mm=1.27, side="bottom")
    assert result["ok"]
    (label,) = session.get_board_info()["labels"]
    assert label == {
        "id": label["id"], "text": "MOTOR 24V", "at": "D6", "offset_mm": [1.27, 0.0],
        "side": "bottom",
    }
    assert session.remove_board_feature(label["id"])["ok"]
    assert "labels" not in session.get_board_info()
    refused = session.remove_board_feature("nothing")
    assert not refused["ok"] and "label" in refused["message"]


# ----------------------------------------------------------------- 3D

vtk = pytest.importorskip("vtk")


def test_labels_are_on_the_face_they_are_written_on() -> None:
    from perfboard_studio.ui import view3d

    session = BoardSession(document=new_board(cols=20, rows=12))
    session.add_board_label("UST", "D6")
    session.add_board_label("ALT", "D6", side="bottom")
    board = session.document.board
    zs = []
    for actor in view3d.build_board_notes(session.document):
        points = actor.GetMapper().GetInput().GetPoints()
        zs += [points.GetPoint(i)[2] for i in range(points.GetNumberOfPoints())]
    # Whatever the path -- a decal per label with Qt, glyphs and tags without -- nothing
    # sits IN a face, where it would fight the board for the same pixels.
    assert all(abs(z) > 0.1 and abs(z + board.thickness) > 0.1 for z in zs)
    assert any(z > 0 for z in zs) and any(z < -board.thickness for z in zs)

    renderer = vtk.vtkRenderer()
    with_labels = view3d.populate_renderer(renderer, session.document, session.lookup)
    count = renderer.GetActors().GetNumberOfItems()
    view3d.populate_renderer(renderer, session.document, session.lookup, board_notes=False)
    assert renderer.GetActors().GetNumberOfItems() < count
    assert with_labels is not None
