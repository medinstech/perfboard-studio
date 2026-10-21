"""A breadboard with a wide channel, for the modules that do not fit the 0.3 inch one --
measured off lhm0's wide-mcu-breadboard, and narrowing to the ordinary channel for part of
its length where the board does."""

from __future__ import annotations

import dataclasses
import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from perfboard_studio.breadboard import (
    STANDARD_CHANNEL,
    board_problem,
    breadboard,
    channel_of,
    channel_stretches,
    clip_holes,
    clip_of,
    has_hole,
    has_rails,
    hole_name,
    missing_holes,
    parse_hole_name,
    rail_columns,
    rail_of,
    rows_for,
    size_of,
)
from perfboard_studio.breadroute import plan_breadboard
from perfboard_studio.catalog import catalog_part
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    SetBoardPayload,
    create_document_id_generator,
    create_standard_registry,
    layout_on_a_solderable_breadboard,
)
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import footprint_lookup, get_footprint
from perfboard_studio.geometry import all_pin_holes
from perfboard_studio.lvs import run_lvs
from perfboard_studio.mcp.session import BoardSession, SessionError
from perfboard_studio.model import (
    DocumentMeta,
    HoleCoord,
    Net,
    NetNode,
    PerfDocument,
    SchematicPart,
)
from perfboard_studio.persist import deserialize_document, serialize_document
from perfboard_studio.placer import place_design

META = DocumentMeta(name="t", created="2026-01-01T00:00:00Z", modified="2026-01-01T00:00:00Z")
FULL = breadboard("830")
#: lhm0's top_ESP32_1000mil: a standard ESP32 devkit's 1000 mil, the whole length.
WIDE_1000 = breadboard("830", channel=10)
#: lhm0's top_ESP32_900mil_flex2: 900 mil for the right-hand 24 columns, 300 mil for the
#: 39 from column 1, so a DIP still straddles the channel beside the module.
FLEX_900 = breadboard("830", channel=9, narrow_channel_cols=39)
#: lhm0's top_ESP32_1000mil_flex2: the same, at 1000 mil. Its narrow part is half a pitch
#: off the grid the rest of it is on, and is drawn half a pitch high.
FLEX_1000 = breadboard("830", channel=10, narrow_channel_cols=39)


def _doc(board, **fields) -> PerfDocument:  # type: ignore[no-untyped-def]
    return PerfDocument(meta=META, board=board, **fields)


# ---------------------------------------------------------------------------
# The pattern, as measured
# ---------------------------------------------------------------------------

#: The openings in lhm0's three STL bodies, found by rasterising each one's top face and
#: taking the centre of every hole in it, then put on the 0.1 inch grid -- all 830 of each
#: land exactly on it, but for the 1000 mil flex body's narrow part, half a pitch off it.
#: Across the board, in pitches from its centre line: the strip rows, by the columns
#: (1-based) they run along. The rails are the ordinary board's, two rows each side, three
#: pitches outside the outer strip row and 50 holes in groups of five.
MEASURED = {
    "1000": (WIDE_1000, [((1, 63), (5, 6, 7, 8, 9))], (12, 13)),
    "900-flex2": (
        FLEX_900,
        [((1, 39), (1.5, 2.5, 3.5, 4.5, 5.5)), ((40, 63), (4.5, 5.5, 6.5, 7.5, 8.5))],
        (11.5, 12.5),
    ),
    "1000-flex2": (
        FLEX_1000,
        [((1, 39), (1.5, 2.5, 3.5, 4.5, 5.5)), ((40, 63), (5, 6, 7, 8, 9))],
        (12, 13),
    ),
}


@pytest.mark.parametrize("name", sorted(MEASURED))
def test_the_wide_patterns_are_the_ones_measured_off_the_printed_bodies(name: str) -> None:
    board, strips, rails = MEASURED[name]
    centre = (board.rows - 1) / 2

    def row(at: float) -> int:
        # A position half a row off the grid goes up the board, to the lower row number:
        # the rounding the module docstring writes down. Every other one is exact.
        return math.floor(at + 1e-9)

    expected: set[tuple[int, int]] = set()
    for (first, last), offsets in strips:
        for col in range(first - 1, last):
            for offset in offsets:
                expected |= {(col, row(centre - offset)), (col, row(centre + offset))}
    for offset in rails:
        for col in rail_columns(FULL):
            expected |= {(col, row(centre - offset)), (col, row(centre + offset))}
    holes = {(c, r) for r in range(board.rows) for c in range(board.cols) if has_hole(board, HoleCoord(c, r))}
    assert holes == expected
    # The same tie points as the board the clips came out of.
    assert len(holes) == 830 and size_of(board) == "830"
    assert rail_columns(board) == rail_columns(FULL)


def test_a_channel_is_a_row_of_grid_per_pitch() -> None:
    assert (FULL.rows, channel_of(FULL)) == (20, STANDARD_CHANNEL)
    assert (WIDE_1000.rows, channel_of(WIDE_1000)) == (27, 10)
    assert (FLEX_900.rows, channel_of(FLEX_900)) == (26, 9)
    assert has_rails(WIDE_1000) and has_rails(FLEX_900)
    mini = breadboard("170", channel=10)
    assert (mini.rows, channel_of(mini), has_rails(mini)) == (19, 10, False)
    for channel in range(3, 16):
        assert channel_of(dataclasses.replace(FULL, rows=rows_for(channel))) == channel


@pytest.mark.parametrize("board", [FULL, WIDE_1000, FLEX_900, breadboard("170", channel=7)], ids=str)
def test_every_hole_is_named_once_and_every_strip_is_five_holes_in_one_column(board) -> None:  # type: ignore[no-untyped-def]
    names: set[str] = set()
    for row in range(board.rows):
        for col in range(board.cols):
            hole = HoleCoord(col, row)
            name = hole_name(board, hole)
            if name is None:
                assert clip_of(board, hole) is None
                continue
            assert name not in names and parse_hole_name(board, name) == hole
            names.add(name)
            if rail_of(board, row) is None:
                clip = clip_holes(board, hole)
                assert len(clip) == 5 and {h.col for h in clip} == {col}
    assert len(names) == board.cols * board.rows - len(missing_holes(board))


def test_where_the_channel_narrows_a_strip_keeps_its_letters_on_other_rows() -> None:
    """e and f meet across 300 mil in the narrow part and 900 mil in the wide one, so the
    same letter is two rows of grid -- which is why a letter is asked for by column too."""
    narrow, wide = parse_hole_name(FLEX_900, "e39"), parse_hole_name(FLEX_900, "e40")
    assert narrow is not None and wide is not None and narrow.row == wide.row - 3
    stretches = channel_stretches(FLEX_900)
    assert [(first, end, e - f) for first, end, f, e in stretches] == [(0, 39, 3), (39, 63, 9)]
    assert [(first, end, e - f) for first, end, f, e in channel_stretches(WIDE_1000)] == [(0, 63, 10)]


def test_a_narrowing_by_an_odd_number_of_pitches_is_drawn_half_a_pitch_high() -> None:
    """1000 mil to 300 is seven pitches, three and a half each side: the lower strip moves
    in four rows and the upper three, so the narrow channel's middle is half a row above
    the wide one's. Its clips are still five holes, one column each, and named."""
    (_, _, f_narrow, e_narrow), (_, _, f_wide, e_wide) = channel_stretches(FLEX_1000)
    assert e_narrow - f_narrow == STANDARD_CHANNEL
    assert (f_narrow + e_narrow) / 2 == (f_wide + e_wide) / 2 - 0.5
    assert board_problem(FLEX_1000) is None


# ---------------------------------------------------------------------------
# What is refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("board", "says"),
    [
        (breadboard("830", narrow_channel_cols=10), "nothing to narrow"),
        (breadboard("830", channel=9, narrow_channel_cols=63), "leave some"),
        (dataclasses.replace(FULL, type="pad-per-hole", narrow_channel_cols=5), "Only a breadboard"),
        (dataclasses.replace(FULL, rows=rows_for(16)), "rows"),
    ],
)
def test_a_channel_that_cannot_be_on_the_grid_is_refused(board, says: str) -> None:  # type: ignore[no-untyped-def]
    """A narrow part that is not part of the board, a channel with nothing to narrow, a
    narrowing on a board with no channel, and a channel wider than any module."""
    problem = board_problem(board)
    assert problem is not None and says in problem
    bus = CommandBus(_doc(FULL), create_standard_registry(), CommandContext(next_id=create_document_id_generator(_doc(FULL))))
    result = bus.dispatch("board.set", SetBoardPayload(board=board))
    assert not result.ok and result.code == "invalid-board"


def test_a_wide_board_survives_the_file_and_an_ordinary_one_writes_nothing_new() -> None:
    for board in (WIDE_1000, FLEX_900):
        text = serialize_document(_doc(board))
        loaded = deserialize_document(text)
        assert loaded.ok and loaded.document.board == board
        assert ('"narrowChannelCols": 39' in text) == bool(board.narrow_channel_cols)
    assert "narrowChannelCols" not in serialize_document(_doc(FULL))
    bad = serialize_document(_doc(FLEX_900)).replace('"narrowChannelCols": 39', '"narrowChannelCols": 70')
    refused = deserialize_document(bad)
    assert not refused.ok and refused.code == "invalid-board"


def test_the_layout_moves_to_a_solderable_board_with_its_channel() -> None:
    moved = layout_on_a_solderable_breadboard(_doc(FLEX_900), META)
    assert moved.board.type == "solderable-breadboard"
    assert (moved.board.rows, moved.board.narrow_channel_cols) == (FLEX_900.rows, 39)


# ---------------------------------------------------------------------------
# A module across it, placed and wired
# ---------------------------------------------------------------------------


def _node(ref: str, pin: str) -> NetNode:
    return NetNode(component_ref=ref, pin=pin)


def _design(board, module: str, with_dip: bool) -> PerfDocument:  # type: ignore[no-untyped-def]
    part = catalog_part(module)
    assert part is not None
    parts = [
        SchematicPart(id="p-U1", ref="U1", value=part.name, footprint_id=part.footprint_id),
        SchematicPart(id="p-R1", ref="R1", value="330", footprint_id="r-axial-4"),
        SchematicPart(id="p-D1", ref="D1", value="LED", footprint_id="led-5mm"),
    ]
    nets = [
        Net(id="io", name="GPIO", nodes=(_node("U1", "5"), _node("R1", "1"))),
        Net(id="a", name="LEDA", nodes=(_node("R1", "2"), _node("D1", "1"))),
        Net(id="gnd", name="GND", nodes=(_node("U1", "14"), _node("D1", "2")), net_class="ground"),
    ]
    if with_dip:
        parts.append(SchematicPart(id="p-U2", ref="U2", value="NE555", footprint_id="dip-8"))
        nets[2] = dataclasses.replace(nets[2], nodes=(*nets[2].nodes, _node("U2", "1")))
        nets += [
            Net(id="vcc", name="3V3", nodes=(_node("U1", "1"), _node("U2", "8"), _node("U2", "4")), net_class="power"),
            Net(id="trig", name="TRIG", nodes=(_node("U1", "6"), _node("U2", "2"))),
        ]
    return _doc(board, parts=tuple(parts), nets=tuple(nets))


@pytest.mark.parametrize(
    ("board", "module", "with_dip"),
    [
        (WIDE_1000, "esp32-devkitc", False),
        (FLEX_900, "esp32-c3-devkitm-1", True),
        (FLEX_1000, "esp32-devkitc", True),
    ],
    ids=["1000-devkitc", "900-flex2-c3-and-a-555", "1000-flex2-devkitc-and-a-555"],
)
def test_a_devkit_goes_across_the_channel_and_the_board_is_the_circuit(board, module: str, with_dip: bool) -> None:  # type: ignore[no-untyped-def]
    """Place on the Board, then the planner: the module straddles the wide channel with a
    row of pins either side of it, and on the flex board the 555 straddles the narrow one."""
    placed = place_design(_design(board, module, with_dip), get_footprint)
    assert placed.unplaced == ()
    plan = plan_breadboard(placed.document, get_footprint)
    assert plan.problems == ()
    assert run_lvs(plan.document, get_footprint).ok
    assert not [v for v in run_drc(plan.document, get_footprint) if v.severity == "error"]
    module_part = next(c for c in plan.document.components if c.ref == "U1")
    holes = [h for _, h in all_pin_holes(module_part, get_footprint(module_part.footprint_id))]  # type: ignore[arg-type]
    halves = {clip_of(board, h)[1] for h in holes}  # type: ignore[index]
    assert halves == {0, 1}, "a row of pins either side of the channel"
    if with_dip:
        dip = next(c for c in plan.document.components if c.ref == "U2")
        assert all(h.col < board.narrow_channel_cols for _, h in all_pin_holes(dip, get_footprint("dip-8")))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# For an agent, and in the window
# ---------------------------------------------------------------------------


def test_an_agent_asks_for_a_wide_channel_in_mil() -> None:
    session = BoardSession(document=_doc(FULL))
    assert session.set_board(channel_mil=1000)["ok"]
    assert session.document.board == WIDE_1000
    info = session.get_board_info()
    assert (info["channel_mil"], info["rails"]) == (1000, True) and "narrow_channel_cols" not in info
    assert session.set_board(channel_mil=900, narrow_channel_cols=39)["ok"]
    assert session.document.board == FLEX_900
    assert session.get_board_info()["narrow_channel_cols"] == 39
    assert session.set_board(channel_mil=1000)["ok"]  # the 39 narrow columns kept
    assert session.document.board == FLEX_1000
    with pytest.raises(SessionError):
        session.set_board(channel_mil=950)
    with pytest.raises(SessionError):
        BoardSession(document=_doc(dataclasses.replace(FULL, type="pad-per-hole", rows=20))).set_board(channel_mil=1000)


def test_a_board_without_rails_is_refused_a_channel_it_would_be_read_back_as_another() -> None:
    """Past 1000 mil a railless board has the rows of an ordinary one with rails: 1100 mil
    asked of the mini came back as 300 mil and four rails nobody asked for."""
    mini = breadboard("170")
    assert channel_of(dataclasses.replace(mini, rows=rows_for(10, rails=False))) == 10
    with pytest.raises(ValueError):
        rows_for(11, rails=False)
    with pytest.raises(ValueError):
        breadboard("170", channel=11)
    session = BoardSession(document=_doc(mini))
    with pytest.raises(SessionError):
        session.set_board(channel_mil=1100)
    assert session.document.board == mini


def _app() -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication(["perfboard-studio-tests"])


def test_board_setup_asks_a_breadboard_its_channel_and_where_it_narrows() -> None:
    _app()
    from perfboard_studio.ui.main import BoardSetupDialog

    dialog = BoardSetupDialog(FULL)
    form = dialog._chosen
    assert form.isRowVisible(dialog.breadboard_channel) and not form.isRowVisible(dialog.narrow_channel)
    dialog.breadboard_channel.setCurrentIndex(dialog.breadboard_channel.findData("1000"))
    assert dialog.board() == WIDE_1000
    assert form.isRowVisible(dialog.narrow_channel)
    # A flex body is found by name in the list, which sets its narrow part.
    for key, board in (("900-flex", FLEX_900), ("1000-flex", FLEX_1000)):
        dialog.breadboard_channel.setCurrentIndex(dialog.breadboard_channel.findData(key))
        assert dialog.narrow_channel.value() == 39 and dialog.board() == board
        reopened = BoardSetupDialog(board)
        assert reopened.breadboard_channel.currentData() == key and reopened.board() == board
    # ...and a plain choice after it is wide all the way again; the box still takes any count.
    dialog.breadboard_channel.setCurrentIndex(dialog.breadboard_channel.findData("900"))
    assert dialog.board() == breadboard("830", channel=9)
    dialog.narrow_channel.setValue(20)
    assert dialog.board() == breadboard("830", channel=9, narrow_channel_cols=20)


@pytest.mark.parametrize("kind", ["pad-per-hole", "stripboard"])
def test_board_setup_turns_a_flex_breadboard_into_a_board_with_no_channel(kind: str) -> None:
    """The narrow part goes with the breadboard: carried onto a perfboard it is a board
    board.set refuses, and the dialog had no row left to clear it in."""
    _app()
    from perfboard_studio.ui.main import BoardSetupDialog

    dialog = BoardSetupDialog(FLEX_900)
    dialog.board_type.setCurrentIndex(dialog.board_type.findData(kind))
    board = dialog.board()
    assert board.type == kind and board.narrow_channel_cols == 0
    bus = CommandBus(_doc(FLEX_900), create_standard_registry(), CommandContext(next_id=create_document_id_generator(_doc(FLEX_900))))
    assert bus.dispatch("board.set", SetBoardPayload(board=board)).ok


def test_the_groove_is_drawn_as_wide_as_the_channel_in_both_views() -> None:
    _app()
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.view2d import BREADBOARD_GROOVE_MM, BoardScene, breadboard_groove_rects

    standard = breadboard_groove_rects(FULL, "top")
    assert len(standard) == 1 and standard[0].height() == pytest.approx(BREADBOARD_GROOVE_MM)
    flex = breadboard_groove_rects(FLEX_900, "top")
    assert [round(r.height(), 2) for r in flex] == [BREADBOARD_GROOVE_MM, round(BREADBOARD_GROOVE_MM + 6 * 2.54, 2)]
    assert flex[0].right() == pytest.approx(flex[1].left())
    for side in ("top", "bottom"):
        rects = breadboard_groove_rects(FLEX_900, side)  # type: ignore[arg-type]
        assert sum(r.width() for r in rects) == pytest.approx(standard[0].width())

    lookup = footprint_lookup()
    for board in (WIDE_1000, FLEX_900):
        scene = BoardScene(_doc(board), lookup, side="top", show_rulers=True)
        from PySide6.QtGui import QImage, QPainter

        image = QImage(800, 300, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        scene.render(painter)
        painter.end()
        assert scene.breadboard_item is not None and scene.breadboard_item.drawn == 830
        actors = view3d.build_breadboard(_doc(board))
        glyphed = sorted(
            a.GetMapper().GetInput().GetNumberOfPoints() for a in actors if a.GetMapper().IsA("vtkGlyph3DMapper")
        )
        assert glyphed == sorted([830, 830, board.cols * board.rows - 830])
