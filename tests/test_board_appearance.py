"""The board says what it looks like: ``Board.mask`` and ``Board.finish``.

They are the board you bought -- a matte black ENIG board, a green HASL one, bare phenolic
-- and designing for the board in your hand means seeing that board, so they travel with
the document. What is pinned: a board that says nothing draws as its material is sold and
writes the bytes it always did; a board that says something keeps it through the file and
is drawn so; a value nobody makes is refused at load and by ``board.set`` alike; applying
a preset takes the product's look; and the View menu's choice still overrides every board.
"""

from __future__ import annotations

import dataclasses
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import DEFAULT_BOARD, SetBoardPayload, create_standard_registry
from perfboard_studio.geometry import (
    STANDARD_PRESETS,
    board_finish,
    board_from_preset,
    board_mask,
)
from perfboard_studio.mcp.session import BoardSession
from perfboard_studio.model import Board, DocumentMeta, PerfDocument
from perfboard_studio.ui import boardcolors

META = DocumentMeta(name="t", created="", modified="")


def _doc(board: Board) -> PerfDocument:
    return PerfDocument(meta=META, board=board)


def test_a_board_that_says_nothing_is_drawn_as_its_material_is_sold() -> None:
    phenolic = dataclasses.replace(DEFAULT_BOARD, material="FR2")
    assert (board_mask(DEFAULT_BOARD), board_finish(DEFAULT_BOARD)) == ("green", "hasl")
    assert (board_mask(phenolic), board_finish(phenolic)) == ("none", "bare-copper")
    boardcolors.choose(None)
    assert boardcolors.scheme_for(DEFAULT_BOARD) is boardcolors.BY_KEY["green"]
    assert boardcolors.scheme_for(phenolic) is boardcolors.BY_KEY["phenolic"]


def test_it_writes_the_bytes_it_always_did() -> None:
    text = persist.serialize_document(_doc(DEFAULT_BOARD))
    assert '"mask"' not in text and '"finish"' not in text


def test_a_board_that_says_keeps_it_through_the_file() -> None:
    black = dataclasses.replace(DEFAULT_BOARD, mask="black", finish="enig")
    text = persist.serialize_document(_doc(black))
    assert '"mask": "black"' in text and '"finish": "enig"' in text
    loaded = persist.parse_document_or_throw(text).board
    assert (loaded.mask, loaded.finish) == ("black", "enig")


def test_and_is_drawn_so() -> None:
    boardcolors.choose(None)
    black = boardcolors.scheme_for(dataclasses.replace(DEFAULT_BOARD, mask="black", finish="enig"))
    assert black.fill == boardcolors.BY_KEY["black"].fill
    assert black.pad != boardcolors.BY_KEY["black"].pad  # gold, not the tin black is sold with
    red, green, blue = (int(black.pad[i : i + 2], 16) for i in (1, 3, 5))
    assert red > green > blue  # gold: warm, and saturated
    # A tinned phenolic board is orange with tin pads; a bare FR-4 one is its laminate.
    tinned = boardcolors.scheme_for(
        dataclasses.replace(DEFAULT_BOARD, material="FR2", finish="hasl")
    )
    assert tinned.fill == boardcolors.BY_KEY["phenolic"].fill
    assert tinned.pad == boardcolors.BY_KEY["green"].pad
    bare = boardcolors.scheme_for(dataclasses.replace(DEFAULT_BOARD, mask="none"))
    assert bare.fill not in {scheme.fill for scheme in boardcolors.SCHEMES}


def test_the_view_menu_still_overrides_every_board() -> None:
    try:
        boardcolors.choose("blue")
        black = dataclasses.replace(DEFAULT_BOARD, mask="black", finish="enig")
        assert boardcolors.scheme_for(black) is boardcolors.BY_KEY["blue"]
    finally:
        boardcolors.choose(None)


@pytest.mark.parametrize(("field", "value"), [("mask", "chartreuse"), ("finish", "osp")])
def test_a_look_nobody_makes_is_refused_at_load_and_by_the_command(field: str, value: str) -> None:
    text = persist.serialize_document(_doc(DEFAULT_BOARD))
    hacked = text.replace('"material": "FR4"', f'"material": "FR4",\n    "{field}": "{value}"', 1)
    assert hacked != text
    with pytest.raises(ValueError, match=f"board.{field}"):
        persist.parse_document_or_throw(hacked)
    bus = CommandBus(_doc(DEFAULT_BOARD), create_standard_registry(), CommandContext(next_id=create_id_generator()))
    result = bus.dispatch(
        "board.set", SetBoardPayload(board=dataclasses.replace(DEFAULT_BOARD, **{field: value}))
    )
    assert not result.ok and result.code == "invalid-board", result.message


def test_a_preset_brings_the_products_own_look() -> None:
    black = dataclasses.replace(DEFAULT_BOARD, mask="black", finish="enig")
    preset = next(p for p in STANDARD_PRESETS if p.name == "5 x 7 cm" and not p.single_sided)
    board = board_from_preset(preset, black)
    assert (board.mask, board.finish) == (None, None)


def test_an_agent_can_say_and_set_the_look() -> None:
    session = BoardSession(document=_doc(DEFAULT_BOARD))
    info = session.get_board_info()
    assert (info["mask"], info["finish"]) == ("green", "hasl")
    assert session.set_board(mask="black", finish="enig")["ok"]
    info = session.get_board_info()
    assert (info["mask"], info["finish"]) == ("black", "enig")
    assert session.document.board.cols == DEFAULT_BOARD.cols
