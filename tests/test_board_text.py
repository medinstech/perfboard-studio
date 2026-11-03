"""What a board is printed with besides its legend: ``Board.printed`` (``model.BoardText``).

The stock boards carry their size ("5cmX7cm") and a batch code in a border, a branded one
its maker's name along an edge. It is silkscreen, part of the board that was bought, so it
travels with the board. What is pinned: nothing printed writes the bytes it always did; a
line keeps its fields through the file and writes only those off their default; a line no
board can print is refused at load and by ``board.set`` in the same words; a line sits in
the border it names, turned on the side edges, sized to the strip; a legend letter under it
is left off; and both views draw it.
"""

from __future__ import annotations

import dataclasses
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from perfboard_studio import persist
from perfboard_studio.boardfamily import STANDARD_PRESETS, board_from_preset
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import DEFAULT_BOARD, SetBoardPayload, create_standard_registry
from perfboard_studio.geometry import (
    board_edge_margin_mm,
    board_outline_mm,
    board_text_placement,
    hole_span_mm,
    legend_strip_mm,
    printed_label_is_clear,
)
from perfboard_studio.model import BoardText, DocumentMeta, PerfDocument, Point2

META = DocumentMeta(name="t", created="", modified="")
PRESET = next(p for p in STANDARD_PRESETS if p.name == "5 x 7 cm" and not p.single_sided)
BOARD = board_from_preset(PRESET, DEFAULT_BOARD)


def _doc(*lines: BoardText) -> PerfDocument:
    return PerfDocument(meta=META, board=dataclasses.replace(BOARD, printed=lines))


def test_nothing_printed_writes_the_bytes_it_always_did() -> None:
    assert '"printed"' not in persist.serialize_document(_doc())


def test_a_line_keeps_its_fields_and_writes_only_those_off_their_default() -> None:
    plain = BoardText("5cmX7cm")
    turned = BoardText("SchmalzTech", edge="right", along=0.3, height_mm=1.0, face="bottom")
    text = persist.serialize_document(_doc(plain, turned))
    assert text.count('"along"') == 1 and text.count('"heightMm"') == 1
    assert '"face": "bottom"' in text and '"face": "top"' not in text
    assert persist.parse_document_or_throw(text).board.printed == (plain, turned)


@pytest.mark.parametrize(
    "line",
    [BoardText("  "), BoardText("x" * 41), BoardText("A", along=1.5), BoardText("A", height_mm=0.0)],
)
def test_a_line_no_board_can_print_is_refused_in_the_same_words(line: BoardText) -> None:
    bus = CommandBus(
        _doc(), create_standard_registry(), CommandContext(next_id=create_id_generator())
    )
    refused = bus.dispatch(
        "board.set", SetBoardPayload(board=dataclasses.replace(BOARD, printed=(line,)))
    )
    assert not refused.ok and refused.code == "invalid-board"
    good = persist.serialize_document(_doc(BoardText("PLACEHOLDER")))
    bad = good.replace('"text": "PLACEHOLDER"', f'"text": "{line.text}"')
    bad = bad.replace('"edge": "bottom"', '"edge": "bottom"' + (
        f',\n        "along": {line.along}' if line.along != 0.5 else ""
    ) + (f',\n        "heightMm": {line.height_mm}' if line.height_mm != 1.2 else ""))
    with pytest.raises(ValueError, match=re.escape(refused.message[:25])):
        persist.parse_document_or_throw(bad)


def test_a_line_sits_in_the_border_it_names_sized_to_the_strip() -> None:
    doc = _doc()
    outline = board_outline_mm(BOARD)
    span_w, span_h = hole_span_mm(BOARD)
    bottom = BoardText("5cmX7cm")
    centre, width, height, turn = board_text_placement(doc, bottom)
    assert turn == 0.0
    assert abs(centre.x - (outline.x + outline.width / 2)) < 1e-9
    strip = legend_strip_mm(doc, "vertical")
    margin = board_edge_margin_mm(BOARD, "vertical")
    # Below the last row's pads and above the edge, in the strip between them.
    assert span_h + margin - strip <= centre.y - height / 2
    assert centre.y + height / 2 <= span_h + margin
    assert width > height
    left = BoardText("LF-HASL", edge="left", along=0.25)
    at, box_w, box_h, turned = board_text_placement(doc, left)
    assert turned == -90.0 and box_h > box_w  # turned on its side
    assert at.x < 0 and abs(at.y - (outline.y + outline.height * 0.25)) < 1e-9
    right = board_text_placement(doc, dataclasses.replace(left, edge="right"))
    assert right[3] == 90.0 and right[0].x > span_w


def test_a_legend_letter_under_a_line_is_left_off() -> None:
    line = BoardText("WWW.EXAMPLE.COM", edge="top")
    doc = _doc(line)
    at, width, _height, _turn = board_text_placement(doc, line)
    assert not printed_label_is_clear(doc, at, 0.8, 0.8)
    assert printed_label_is_clear(_doc(), at, 0.8, 0.8)
    beside = Point2(at.x + width / 2 + 2.0, at.y)
    assert printed_label_is_clear(doc, beside, 0.8, 0.8)


def test_both_views_draw_it() -> None:
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.view2d import BoardScene, BoardTextItem

    QApplication.instance() or QApplication([])
    doc = _doc(BoardText("5cmX7cm"), BoardText("BACK", face="bottom"))
    for side in ("top", "bottom"):
        scene = BoardScene(doc, footprint_lookup(), side=side, show_ratsnest=False, show_rulers=False)
        assert sum(isinstance(item, BoardTextItem) for item in scene.items()) == 1
    plain = BoardScene(_doc(), footprint_lookup(), side="top", show_ratsnest=False, show_rulers=False)
    assert not any(isinstance(item, BoardTextItem) for item in plain.items())
    assert len(view3d.build_board_text(doc)) == 2
    assert view3d.build_board_text(_doc()) == []
