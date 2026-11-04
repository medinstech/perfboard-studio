"""Several boards in one document, each seen alone (``system.py``).

What is pinned: which fields are a board's own and which the design's, so a field added to
the document is a field somebody has to decide about; a board's view is exactly the
single-board document the engine already reads, and merging it back unchanged gives the
document back unchanged, for every board; a change made through one board's view leaves
every other board as it was; and a document of several boards goes through the file and
comes back equal, while a board alone writes exactly the bytes it always did (the golden
round trip in ``test_persist`` is the full proof of that).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from perfboard_studio import persist, system
from perfboard_studio.model import (
    ExtraBoard,
    HoleCoord,
    LeadBendConductor,
    PerfDocument,
)

REPO = Path(__file__).resolve().parents[1]


def _example(name: str) -> PerfDocument:
    return persist.parse_document_or_throw((REPO / "examples" / f"{name}.perf").read_text(encoding="utf-8"))


def _as_extra(doc: PerfDocument, board_id: str, name: str) -> ExtraBoard:
    """``doc``'s board as an extra board, its component and conductor ids and references
    prefixed so they cannot meet the first board's: one id space across the document."""

    def conductor(c):  # type: ignore[no-untyped-def]
        changed = dataclasses.replace(c, id=f"{board_id}-{c.id}")
        if isinstance(c, LeadBendConductor):
            changed = dataclasses.replace(changed, component_id=f"{board_id}-{c.component_id}")
        return changed

    return ExtraBoard(
        id=board_id,
        name=name,
        board=doc.board,
        components=tuple(
            dataclasses.replace(c, id=f"{board_id}-{c.id}", ref=f"{board_id.upper()}{c.ref}")
            for c in doc.components
        ),
        conductors=tuple(conductor(c) for c in doc.conductors),
        cuts=doc.cuts,
        mounting_holes=doc.mounting_holes,
        edge_connectors=doc.edge_connectors,
        board_notes=doc.board_notes,
        height_limit_mm=doc.height_limit_mm,
        body_clearance_mm=doc.body_clearance_mm,
    )


def _system() -> PerfDocument:
    """lm317-supply as the first board, nano-relay and ne555-astable after it."""
    first = _example("lm317-supply")
    return dataclasses.replace(
        first,
        boards=(
            _as_extra(_example("nano-relay"), "b2", "Controller"),
            _as_extra(_example("ne555-astable"), "b3", "Blinker"),
        ),
    )


def test_every_field_is_a_boards_own_or_the_designs() -> None:
    """An extra board has exactly the first board's own fields, and everything else on the
    document is shared. A field added to either is caught here, because it has to be
    decided which it is -- a board's own field left out of ``BOARD_FIELDS`` would be the
    first board's value on every board's view."""
    document_fields = {f.name for f in dataclasses.fields(PerfDocument)}
    extra_fields = {f.name for f in dataclasses.fields(ExtraBoard)} - {"id", "name"}
    assert extra_fields == set(system.BOARD_FIELDS)
    assert set(system.BOARD_FIELDS) <= document_fields
    assert set(system.shared_fields()) == {
        "meta", "parts", "nets", "sheet", "sheet_wires", "sheet_notes", "format_version",
    }


def test_a_boards_view_is_a_document_of_that_board_alone() -> None:
    doc = _system()
    assert system.board_ids(doc) == (system.FIRST_BOARD, "b2", "b3")
    for board_id in system.board_ids(doc):
        seen = system.board_document(doc, board_id)
        assert seen.boards == ()
        for name in system.shared_fields():
            assert getattr(seen, name) == getattr(doc, name)
        own = doc if board_id == system.FIRST_BOARD else system.extra_board(doc, board_id)
        for name in system.BOARD_FIELDS:
            assert getattr(seen, name) == getattr(own, name), (board_id, name)


@pytest.mark.parametrize("board_id", [system.FIRST_BOARD, "b2", "b3"])
def test_merging_a_view_back_unchanged_gives_the_document_back(board_id: str) -> None:
    doc = _system()
    assert system.merge_board(doc, board_id, system.board_document(doc, board_id)) == doc


@pytest.mark.parametrize("board_id", [system.FIRST_BOARD, "b2", "b3"])
def test_a_change_to_one_board_leaves_every_other_board_as_it_was(board_id: str) -> None:
    """Move every part of one board by a hole and rename the document: the board's own
    fields change, the shared field changes for every board, and no other board moves."""
    doc = _system()
    seen = system.board_document(doc, board_id)
    moved = dataclasses.replace(
        seen,
        meta=dataclasses.replace(seen.meta, name="renamed"),
        components=tuple(
            dataclasses.replace(c, anchor=HoleCoord(c.anchor.col + 1, c.anchor.row))
            for c in seen.components
        ),
    )
    merged = system.merge_board(doc, board_id, moved)
    assert merged.meta.name == "renamed"
    for other in system.board_ids(doc):
        view = system.board_document(merged, other)
        if other == board_id:
            assert view.components == moved.components
        else:
            assert view.components == system.board_document(doc, other).components
            for name in system.BOARD_FIELDS:
                assert getattr(view, name) == getattr(system.board_document(doc, other), name)


def test_a_view_that_holds_another_board_is_refused() -> None:
    doc = _system()
    with pytest.raises(ValueError):
        system.merge_board(doc, system.FIRST_BOARD, doc)


def test_a_document_of_several_boards_goes_through_the_file_and_back() -> None:
    doc = _system()
    text = persist.serialize_document(doc)
    assert text.count('"boards"') == 1
    back = persist.parse_document_or_throw(text)
    assert back.boards == doc.boards
    assert system.board_document(back) == system.board_document(doc)
    assert persist.serialize_document(back) == text


def test_a_board_alone_writes_no_boards_key() -> None:
    doc = _example("ne555-astable")
    assert '"boards"' not in persist.serialize_document(doc)


def test_ids_are_one_space_across_every_board() -> None:
    """Two boards holding one component id, a board taking another's id, or the first
    board's own id: refused at load, as two components sharing an id on one board are."""
    doc = _system()
    clash = dataclasses.replace(
        doc,
        boards=(
            doc.boards[0],
            dataclasses.replace(doc.boards[1], components=(doc.components[0],)),
        ),
    )
    result = persist.deserialize_document(persist.serialize_document(clash))
    assert not result.ok and result.code == "duplicate-id"
    for taken in ("b2", system.FIRST_BOARD):
        twice = dataclasses.replace(doc, boards=(doc.boards[0], dataclasses.replace(doc.boards[1], id=taken)))
        result = persist.deserialize_document(persist.serialize_document(twice))
        assert not result.ok and result.code == "duplicate-id", taken
