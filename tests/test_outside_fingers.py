"""Edge pads OUTSIDE the grid (``EdgeConnector.outside``), as the stock boards' strips are.

Every photograph of the stock boards with an edge strip -- the green double-sided 5 x 7 and
2 x 8, the phenolic 5 x 7 -- has its lettered grid run to its last row untouched and the
strip standing beyond it, in the border. A connector ON the holes stretches the outermost
row's pads out to the edge instead, undrilled. What is pinned: an outside strip leaves every
grid pad and hole as it is; its fingers lie in the border, inside the board and its inset,
short of the outermost pads by the gap; a bore cuts the fingers it touches; the field is
left out of the file when false and read back when true; and the command refuses one where
the border has no room.
"""

from __future__ import annotations

import dataclasses

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    DEFAULT_BOARD,
    AddEdgeConnectorPayload,
    SetBoardPayload,
    create_standard_registry,
)
from perfboard_studio.geometry import (
    OUTSIDE_FINGER_GAP_MM,
    STANDARD_PRESETS,
    board_from_preset,
    board_outline_mm,
    edge_connector_at,
    edge_connector_holes,
    edge_finger_rect,
    hole_key,
    hole_to_mm,
    holes_without_grid_pad,
    pad_extent_mm,
    surviving_finger_holes,
    undrilled_holes,
)
from perfboard_studio.mcp.session import BoardSession
from perfboard_studio.model import (
    DocumentMeta,
    EdgeConnector,
    HoleCoord,
    MountingHole,
    PerfDocument,
)

PRESET = next(p for p in STANDARD_PRESETS if p.name == "5 x 7 cm" and not p.single_sided)
BOARD = board_from_preset(PRESET, DEFAULT_BOARD)
STRIP = EdgeConnector(
    id="ec-top", edge="top", start=0, count=BOARD.cols, finger_width=1.6, inset_mm=0.5, outside=True
)


def _doc(*connectors: EdgeConnector, mounts: tuple[MountingHole, ...] = ()) -> PerfDocument:
    return dataclasses.replace(
        PerfDocument(meta=DocumentMeta(name="t", created="", modified=""), board=BOARD),
        edge_connectors=connectors,
        mounting_holes=mounts,
    )


def test_an_outside_strip_leaves_every_grid_pad_and_hole_as_it_is() -> None:
    doc = _doc(STRIP)
    row = {hole_key(hole) for hole in edge_connector_holes(STRIP, BOARD)}
    assert len(row) == BOARD.cols
    assert not row & holes_without_grid_pad(doc, "top")
    assert not row & holes_without_grid_pad(doc, "bottom")
    assert not row & undrilled_holes(doc)
    assert all(edge_connector_at(doc, HoleCoord(col, 0)) is None for col in range(BOARD.cols))


def test_its_fingers_lie_in_the_border_short_of_the_outermost_pads() -> None:
    outline = board_outline_mm(BOARD)
    _extent_x, extent_y = pad_extent_mm(BOARD)
    for hole in edge_connector_holes(STRIP, BOARD):
        rect = edge_finger_rect(STRIP, hole, BOARD)
        centre = hole_to_mm(hole, BOARD)
        assert rect.height > 0.5
        assert abs(rect.x + rect.width / 2 - centre.x) < 1e-9
        assert abs(rect.width - STRIP.finger_width) < 1e-9
        assert rect.y >= outline.y + STRIP.inset_mm - 1e-9
        assert rect.y + rect.height <= centre.y - extent_y / 2 - OUTSIDE_FINGER_GAP_MM + 1e-9


def test_a_bore_cuts_the_fingers_it_touches() -> None:
    first = edge_connector_holes(STRIP, BOARD)[0]
    rect = edge_finger_rect(STRIP, first, BOARD)
    over = MountingHole(
        id="mh",
        at=first,
        offset_x_mm=0.0,
        offset_y_mm=rect.y + rect.height / 2 - hole_to_mm(first, BOARD).y,
        diameter=1.0,
        head_diameter=2.0,
    )
    surviving = surviving_finger_holes(_doc(STRIP, mounts=(over,)), STRIP)
    assert first not in surviving
    assert len(surviving) == BOARD.cols - 1


def test_the_field_is_left_out_when_false_and_read_back_when_true() -> None:
    inside = dataclasses.replace(STRIP, id="ec-bottom", edge="bottom", outside=False)
    text = persist.serialize_document(_doc(STRIP, inside))
    assert text.count('"outside": true') == 1
    assert '"outside": false' not in text
    loaded = persist.parse_document_or_throw(text)
    assert {c.id: c.outside for c in loaded.edge_connectors} == {"ec-top": True, "ec-bottom": False}


def test_the_command_refuses_an_outside_strip_where_the_border_has_no_room() -> None:
    for board, accepted in ((DEFAULT_BOARD, False), (BOARD, True)):
        doc = PerfDocument(meta=DocumentMeta(name="t", created="", modified=""), board=board)
        bus = CommandBus(doc, create_standard_registry(), CommandContext(next_id=create_id_generator()))
        result = bus.dispatch(
            "edge-connector.add",
            AddEdgeConnectorPayload(edge="top", start=0, count=4, finger_width=1.6, outside=True),
        )
        assert result.ok is accepted, (board.border_y_mm, result.message)
        if accepted:
            assert bus.document.edge_connectors[0].outside
            assert not undrilled_holes(bus.document)


def test_a_border_taken_away_takes_the_strip_with_it() -> None:
    doc = _doc(STRIP)
    bus = CommandBus(doc, create_standard_registry(), CommandContext(next_id=create_id_generator()))
    thin = dataclasses.replace(BOARD, border_y_mm=0.0)
    result = bus.dispatch("board.set", SetBoardPayload(board=thin))
    assert not result.ok and result.code == "would-strand-edge-connector", result.message
    # Thinner on the OTHER axis is not this strip's business.
    assert bus.dispatch("board.set", SetBoardPayload(board=dataclasses.replace(BOARD, border_x_mm=0.0))).ok


def test_an_agent_can_lay_an_outside_strip_and_is_told_which_it_laid() -> None:
    session = BoardSession(document=_doc())
    assert session.add_edge_connector("top", 0, 6, 1.6, "bottom", outside=True)["ok"]
    assert session.add_edge_connector("bottom", 0, 6, 1.6, "bottom")["ok"]
    info = {c["edge"]: c for c in session.get_board_info()["edge_connectors"]}
    assert info["top"].get("outside") is True
    assert "outside" not in info["bottom"]
    assert info["top"]["holes"][0] == "A1"
