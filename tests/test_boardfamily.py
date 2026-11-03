"""Board families (``boardfamily.py``): the products people buy, in the sizes they are sold.

What is pinned: every board of every catalogue family is one ``board.applyPreset`` accepts
and DRC finds nothing wrong with, bare; a board of a family is what the family says --
landscape, its strip outside the grid down the short edges and clear of the corner holes,
its legend and its printed size; a size sold without the strip has none; a custom size
keeps the family's border and round-trips between grid and millimetres; the refusal names
the field it is about; a saved family comes back as it went, and an unknown format is
refused rather than guessed at; and every vocabulary the designer offers can be read at run
time.
"""

from __future__ import annotations

import dataclasses
import json
from typing import get_args

import pytest

from perfboard_studio import boardfamily
from perfboard_studio.boardfamily import (
    FAMILIES,
    FAMILY_FORMAT,
    GREEN_DOUBLE_SIDED,
    PHENOLIC_SINGLE_SIDED,
    BoardFamily,
    EdgeStrip,
    board_for,
    family_from_json,
    family_problem,
    family_to_json,
    size_for_grid,
    size_for_mm,
)
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    DEFAULT_BOARD,
    ApplyBoardPresetPayload,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import (
    board_size_mm,
    edge_finger_rect,
    mounting_hole_centre_mm,
    surviving_finger_holes,
)
from perfboard_studio.model import DocumentMeta, HoleCoord

META = DocumentMeta(name="t", created="", modified="")
EVERY_SIZE = [
    pytest.param(family, size, id=f"{family.id}-{size.name}-{size.cols}x{size.rows}")
    for family in FAMILIES
    for size in family.sizes
]


def test_every_catalogue_family_passes_its_own_refusal() -> None:
    for family in FAMILIES:
        assert family_problem(family) is None, family.id
    assert len({family.id for family in FAMILIES}) == len(FAMILIES)


@pytest.mark.parametrize(("family", "size"), EVERY_SIZE)
def test_every_board_of_every_family_is_accepted_and_clean(family: BoardFamily, size: boardfamily.BoardSize) -> None:
    design = board_for(family, size, DEFAULT_BOARD)
    bus = CommandBus(
        create_empty_document(META), create_standard_registry(), CommandContext(next_id=create_id_generator())
    )
    result = bus.dispatch(
        "board.applyPreset",
        ApplyBoardPresetPayload(
            board=design.board,
            edge_connectors=design.edge_connectors,
            mounting_holes=design.mounting_holes,
        ),
    )
    assert result.ok, result.message
    doc = bus.document
    assert board_size_mm(doc.board) == pytest.approx((size.width_mm, size.height_mm))
    findings = run_drc(doc, footprint_lookup())
    assert not [v for v in findings if v.severity == "error"], findings
    # No bore takes a finger: the strip stops short of the corner holes.
    for connector in doc.edge_connectors:
        assert len(surviving_finger_holes(doc, connector)) == connector.count


def test_a_board_of_a_family_is_what_the_family_says() -> None:
    size = next(s for s in GREEN_DOUBLE_SIDED.sizes if (s.cols, s.rows) == (24, 18))
    design = board_for(GREEN_DOUBLE_SIDED, size, DEFAULT_BOARD)
    board = design.board
    assert (board.cols, board.rows) == (24, 18)  # landscape: the letters along the long edge
    assert [c.edge for c in design.edge_connectors] == ["left", "right"]
    assert all(c.outside and c.shape == "stadium" and c.count == 16 for c in design.edge_connectors)
    assert board.labels is not None
    assert (board.labels.letter_edges, board.labels.number_edges) == ("top", "both")
    assert [line.text for line in board.printed] == ["5cmX7cm"]
    assert (board.mask, board.finish) == (None, None)  # the material's look, said by nobody
    assert len(design.mounting_holes) == 4
    # The holes sit in the border beyond the strip's run: above its first finger on the
    # left edge, below its last.
    left = design.edge_connectors[0]
    first = edge_finger_rect(left, HoleCoord(0, left.start), board)
    last = edge_finger_rect(left, HoleCoord(0, left.start + left.count - 1), board)
    ys = sorted(mounting_hole_centre_mm(mount, board).y for mount in design.mounting_holes)
    assert ys[0] < first.y and ys[-1] > last.y + last.height
    phenolic = board_for(PHENOLIC_SINGLE_SIDED, PHENOLIC_SINGLE_SIDED.sizes[0], DEFAULT_BOARD)
    assert phenolic.board.single_sided and phenolic.board.material == "FR2"
    assert all(c.face == "bottom" and c.shape == "square" for c in phenolic.edge_connectors)
    assert phenolic.board.labels is not None and phenolic.board.labels.number_edges == "none"


def test_a_size_sold_without_the_strip_has_none() -> None:
    bare = [s for s in GREEN_DOUBLE_SIDED.sizes if not s.strip]
    assert bare
    for size in bare:
        assert board_for(GREEN_DOUBLE_SIDED, size, DEFAULT_BOARD).edge_connectors == ()


def test_a_custom_size_keeps_the_familys_border_and_round_trips() -> None:
    by_grid = size_for_grid(GREEN_DOUBLE_SIDED, 30, 20)
    first = GREEN_DOUBLE_SIDED.sizes[0]
    border = (first.width_mm - first.cols * 2.54) / 2
    assert by_grid.width_mm == pytest.approx(30 * 2.54 + 2 * border, abs=0.01)
    by_mm = size_for_mm(GREEN_DOUBLE_SIDED, by_grid.width_mm, by_grid.height_mm)
    assert (by_mm.cols, by_mm.rows) == (30, 20)
    assert family_problem(dataclasses.replace(GREEN_DOUBLE_SIDED, sizes=(by_grid,))) is None


def test_the_refusal_names_the_field_it_is_about() -> None:
    wide = dataclasses.replace(
        GREEN_DOUBLE_SIDED, strip=dataclasses.replace(GREEN_DOUBLE_SIDED.strip or EdgeStrip(), width_mm=3.0)
    )
    problem = family_problem(wide)
    assert problem is not None and problem[0] == "strip.width_mm"
    flush = dataclasses.replace(GREEN_DOUBLE_SIDED, sizes=(size_for_grid(GREEN_DOUBLE_SIDED, 10, 10),))
    flush = dataclasses.replace(
        flush, sizes=(dataclasses.replace(flush.sizes[0], width_mm=25.4, height_mm=25.4),)
    )
    problem = family_problem(flush)
    assert problem is not None and problem[0] == "sizes[0]", problem
    assert family_problem(dataclasses.replace(GREEN_DOUBLE_SIDED, sizes=()))[0] == "sizes"  # type: ignore[index]


def test_a_saved_family_comes_back_as_it_went() -> None:
    mine = dataclasses.replace(GREEN_DOUBLE_SIDED, id="user-mine", name="Mine", user=True, mask="black", finish="enig")
    text = family_to_json(mine)
    assert json.loads(text)["format"] == FAMILY_FORMAT
    assert family_from_json(text) == mine
    future = json.dumps({**json.loads(text), "format": FAMILY_FORMAT + 1})
    with pytest.raises(ValueError, match="format"):
        family_from_json(future)
    broken = json.dumps({**json.loads(text), "pitch_mm": 0})
    with pytest.raises(ValueError, match="pitch_mm"):
        family_from_json(broken)
    with pytest.raises(ValueError):
        family_from_json("not json")


def test_every_vocabulary_the_designer_offers_is_readable_at_run_time() -> None:
    from perfboard_studio.model import BoardFinish, BoardMask, FingerShape, LetterEdges, NumberEdges

    for alias, values in (
        (boardfamily.FamilyBoardType, boardfamily.FAMILY_BOARD_TYPES),
        (boardfamily.StripEdges, boardfamily.STRIP_EDGES),
        (FingerShape, boardfamily.STRIP_SHAPES),
        (LetterEdges, boardfamily.LETTER_EDGES),
        (NumberEdges, boardfamily.NUMBER_EDGES),
        (BoardMask, boardfamily.MASKS),
        (BoardFinish, boardfamily.FINISHES),
    ):
        assert get_args(alias) == values and values, alias
