"""A solderable breadboard: the breadboard's holes and strips, in copper, soldered.

Two questions run through all of it (``breadboard.py``): the PATTERN -- which holes exist,
what joins them, what they are called -- is the solderless board's, and the PLASTIC --
nothing soldered, nothing drilled, leads held in clips -- is not. Every test here is one
side of that line, and the move a solderable breadboard is bought for, a working
breadboard's layout carried over hole for hole, is tested end to end.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from perfboard_studio.breadboard import (
    SIZES,
    breadboard,
    has_breadboard_pattern,
    is_breadboard,
    is_solderable_breadboard,
    missing_holes,
    pattern_board,
    rail_columns,
    size_of,
    solderable_breadboard,
)
from perfboard_studio.breadroute import plan_breadboard
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    AddEdgeConnectorPayload,
    AddMountingHolePayload,
    create_document_id_generator,
    create_empty_document,
    create_standard_registry,
    layout_on_a_solderable_breadboard,
)
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import board_size_mm, format_hole, parse_hole
from perfboard_studio.guide import GuideOptions, build_guide
from perfboard_studio.guide_export import guide_to_html
from perfboard_studio.lvs import run_lvs
from perfboard_studio.model import (
    DocumentMeta,
    HoleCoord,
    PerfDocument,
    SchematicPart,
    SolderTraceConductor,
)
from perfboard_studio.persist import deserialize_document, serialize_document
from perfboard_studio.placer import place_design
from perfboard_studio.stripboard import segments

REPO = Path(__file__).resolve().parents[1]
LOOKUP = footprint_lookup()
META = DocumentMeta(name="t", created="", modified="")


def _blank(board) -> PerfDocument:  # type: ignore[no-untyped-def]
    return dataclasses.replace(create_empty_document(META), board=board)


def _bus(doc: PerfDocument) -> CommandBus:
    return CommandBus(
        doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc))
    )


_ON_A_BREADBOARD: PerfDocument | None = None


def _working_breadboard() -> PerfDocument:
    """ne555-astable placed and wired on a half-size breadboard: a circuit that works there."""
    global _ON_A_BREADBOARD
    if _ON_A_BREADBOARD is None:
        loaded = deserialize_document((REPO / "examples" / "ne555-astable.perf").read_text(encoding="utf-8"))
        assert loaded.ok
        doc = loaded.document
        design = dataclasses.replace(
            doc, board=breadboard("400"), components=(), conductors=(), mounting_holes=(),
            edge_connectors=(), board_notes=(),
            parts=doc.parts + tuple(
                SchematicPart(id=c.id, ref=c.ref, value=c.value, footprint_id=c.footprint_id,
                              pin_names=c.pin_names, symbol=c.symbol)
                for c in doc.components
            ),
        )
        placed = place_design(design, LOOKUP)
        assert placed.unplaced == ()
        plan = plan_breadboard(placed.document, LOOKUP)
        assert plan.problems == ()
        _ON_A_BREADBOARD = plan.document
    return _ON_A_BREADBOARD


# ---------------------------------------------------------------------------
# The two questions
# ---------------------------------------------------------------------------


def test_the_two_kinds_share_the_pattern_and_not_the_plastic() -> None:
    plastic, copper = breadboard("830"), solderable_breadboard("830")
    assert has_breadboard_pattern(plastic) and has_breadboard_pattern(copper)
    assert is_breadboard(plastic) and not is_breadboard(copper)
    assert is_solderable_breadboard(copper) and not is_solderable_breadboard(plastic)
    assert missing_holes(plastic) == missing_holes(copper) != frozenset()
    for size in SIZES:
        assert size_of(solderable_breadboard(size)) == size_of(breadboard(size)) == size


def test_each_kind_brings_its_own_board() -> None:
    """Changing the kind changes the board under the holes: 8.5 mm of plastic with 0.8 mm
    clip openings becomes 1.6 mm of FR-4 drilled 0.042 in, and the half size comes out
    exactly the half-size Perma-Proto its border was taken from, 81 x 51 mm."""
    copper = pattern_board("solderable-breadboard", 30, 20)
    assert (copper.thickness, copper.drill_diameter, copper.material) == (1.6, 1.07, "FR4")
    assert breadboard("400").thickness == 8.5
    width, height = board_size_mm(copper)
    assert (round(width, 2), round(height, 2)) == (81.0, 51.0)
    with pytest.raises(ValueError):
        pattern_board("stripboard", 30, 20)


def test_its_holes_are_named_as_the_board_prints_them() -> None:
    board = solderable_breadboard("830")
    hole = parse_hole("e12", board)
    assert format_hole(hole, board) == "e12"
    assert format_hole(parse_hole("T+12", board), board) == "T+12"


def test_its_copper_is_the_clips() -> None:
    """Each five-hole clip and each rail is one run of copper, and the solderless board has
    none to draw: its clips are under the plastic."""
    doc = _blank(solderable_breadboard("400"))
    runs = segments(doc)
    assert len(runs) == 30 * 2 + 4
    assert sorted({len(run.holes) for run in runs}) == [5, 25]
    assert segments(_blank(breadboard("400"))) == ()


# ---------------------------------------------------------------------------
# The move it is bought for
# ---------------------------------------------------------------------------


def test_a_working_breadboard_moves_to_it_hole_for_hole() -> None:
    bb = _working_breadboard()
    sb = layout_on_a_solderable_breadboard(bb, META)
    assert is_solderable_breadboard(sb.board) and (sb.board.cols, sb.board.rows) == (30, 20)
    for field in ("components", "conductors", "nets", "parts", "sheet", "board_notes"):
        assert getattr(sb, field) == getattr(bb, field), field
    assert run_lvs(sb, LOOKUP).ok
    assert not [v for v in run_drc(sb, LOOKUP) if v.severity == "error"]


def test_only_a_solderless_breadboard_moves() -> None:
    with pytest.raises(ValueError):
        layout_on_a_solderable_breadboard(_blank(solderable_breadboard("400")), META)


# ---------------------------------------------------------------------------
# Soldered, drilled, guided with an iron
# ---------------------------------------------------------------------------


def test_solder_is_not_an_error_on_it() -> None:
    trace = SolderTraceConductor(
        id="t1", kind="solder-trace", path=(HoleCoord(0, 4), HoleCoord(0, 5)), net_id=None
    )
    rules = {
        board.type: {v.rule for v in run_drc(dataclasses.replace(_blank(board), conductors=(trace,)), LOOKUP)}
        for board in (breadboard("400"), solderable_breadboard("400"))
    }
    assert "not-on-breadboard" in rules["breadboard"]
    assert "not-on-breadboard" not in rules["solderable-breadboard"]


def test_it_takes_a_mounting_hole_and_no_fingers() -> None:
    bus = _bus(_blank(solderable_breadboard("830")))
    assert bus.dispatch("mounting-hole.add", AddMountingHolePayload(at=HoleCoord(30, 2))).ok
    refused = bus.dispatch("edge-connector.add", AddEdgeConnectorPayload(edge="left", start=0, count=4))
    assert not refused.ok and refused.code == "breadboard"
    plastic = _bus(_blank(breadboard("830")))
    assert not plastic.dispatch("mounting-hole.add", AddMountingHolePayload(at=HoleCoord(30, 2))).ok


def test_it_saves_and_opens() -> None:
    """Byte for byte, the file's own measure: it writes conductors in id order, so the
    document read back holds the same ones in another order."""
    sb = layout_on_a_solderable_breadboard(_working_breadboard(), META)
    text = serialize_document(sb)
    loaded = deserialize_document(text)
    assert loaded.ok and loaded.warnings == ()
    assert loaded.document.board == sb.board
    assert serialize_document(loaded.document) == text


def test_its_guide_is_a_soldering_guide_in_both_languages() -> None:
    sb = layout_on_a_solderable_breadboard(_working_breadboard(), META)
    english = build_guide(sb, LOOKUP)
    assert english.iron is not None
    assert english.phases[0].summary.startswith("Lay the board down with column 1 on the left")
    assert "Soldering guide · solderable breadboard, 400 points" in guide_to_html(english)
    turkish = build_guide(sb, LOOKUP, GuideOptions(language="tr"))
    assert turkish.phases[0].summary.startswith("Kartı 1. kolon solda")
    assert "Lehimleme rehberi · lehimlenebilir breadboard" in guide_to_html(turkish)
    # The solderless board's wording is nowhere in it.
    assert "pushed into" not in guide_to_html(english)


def test_an_agent_changing_the_kind_gets_the_kinds_board() -> None:
    from perfboard_studio.mcp.session import BoardSession

    session = BoardSession(document=_working_breadboard())
    result = session.set_board(board_type="solderable-breadboard")
    assert result["ok"], result
    board = session.document.board
    assert is_solderable_breadboard(board) and board.thickness == 1.6
    assert session.document.components == _working_breadboard().components


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def _app() -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication(["perfboard-studio-tests"])


def test_the_designer_asks_its_size_and_its_border() -> None:
    _app()
    from perfboard_studio.commands import DEFAULT_BOARD
    from tests.designer_support import choose_family, choose_size, designer_on, shown

    dialog = designer_on(DEFAULT_BOARD)
    choose_family(dialog, "solderable-breadboard")
    choose_size(dialog, "400")
    assert dialog.design().board == solderable_breadboard("400")
    dialog.border_x.setValue(6.0)
    assert dialog.design().board.border_x_mm == 6.0
    assert shown(dialog, "breadboard.border_x_mm") and not shown(dialog, "grid")
    choose_family(dialog, "breadboard")
    assert not shown(dialog, "breadboard.border_x_mm")


def test_in_2d_it_is_copper_where_the_pattern_has_holes_with_the_print_beside_it() -> None:
    _app()
    from perfboard_studio.geometry import holeless_positions
    from perfboard_studio.ui.view2d import BoardScene, BreadboardPrintItem, StripGridItem

    board = solderable_breadboard("400")
    scene = BoardScene(_blank(board), LOOKUP, side="top", show_rulers=True)
    assert scene.breadboard_item is None and scene.pad_grid is not None
    assert holeless_positions(board) <= scene.pad_grid.consumed
    kinds = {type(item) for item in scene.items()}
    assert {BreadboardPrintItem, StripGridItem} <= kinds
    assert scene.legend_is_readable()


def test_the_file_menu_moves_a_breadboard_and_nothing_else(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _app()
    from perfboard_studio.ui.main import MainWindow

    monkeypatch.setattr(MainWindow, "_offer_to_save", lambda self: True)
    window = MainWindow(_working_breadboard())
    try:
        assert window.act_layout_to_solderable.isEnabled()
        window.on_layout_to_solderable()
        moved = window.bus.document
        assert is_solderable_breadboard(moved.board)
        assert moved.components == _working_breadboard().components
        assert not window.act_layout_to_solderable.isEnabled()
    finally:
        window._saved_document = window.bus.document
        window.close()


def test_in_3d_it_is_drilled_only_where_the_pattern_has_holes() -> None:
    from perfboard_studio.ui import view3d

    board = solderable_breadboard("400")
    doc = _blank(board)
    glyphed = sorted(
        actor.GetMapper().GetInput().GetNumberOfPoints()
        for actor in view3d.build_substrate(doc)
        if actor.GetMapper().IsA("vtkGlyph3DMapper")
    )
    holes = board.cols * board.rows - len(missing_holes(board))
    # Both faces of every tile: drilled at the pattern's holes, solid everywhere else.
    assert glyphed == sorted([2 * holes, 2 * len(missing_holes(board))])
    # Its copper: a holed piece at every hole of every clip, and the rails carried across
    # the column each group of five leaves out -- the copper does not stop there.
    strips = view3d.build_strips(doc)
    pieces = sum(
        a.GetMapper().GetInput().GetNumberOfPoints()
        for a in strips
        if a.GetMapper().IsA("vtkGlyph3DMapper")
    )
    assert pieces == holes
    (bridges,) = [a for a in strips if not a.GetMapper().IsA("vtkGlyph3DMapper")]
    gaps_per_rail = max(rail_columns(board)) - min(rail_columns(board)) + 1 - len(rail_columns(board))
    assert bridges.GetMapper().GetInput().GetNumberOfPolys() == 4 * gaps_per_rail > 0
