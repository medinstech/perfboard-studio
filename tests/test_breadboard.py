"""A solderless breadboard: a fixed pattern of clips, read by everything that reads strips."""

from __future__ import annotations

import dataclasses
from itertools import pairwise

import pytest

from perfboard_studio.breadboard import (
    CLIP_DEPTH_MM,
    RAIL_GROUP,
    SIZES,
    breadboard,
    clip_holes,
    clip_of,
    has_hole,
    hole_name,
    missing_holes,
    parse_hole_name,
    rail_columns,
)
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    AddConductorPayload,
    AddEdgeConnectorPayload,
    AddMountingHolePayload,
    NewSolderTraceConductor,
    NewWireConductor,
    SetBoardPayload,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.connectivity import extract_physical_nets
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import get_footprint
from perfboard_studio.geometry import (
    all_pin_holes,
    format_hole,
    hole_key,
    hole_ref_to_coord,
    holeless_positions,
    parse_hole,
    unusable_holes,
)
from perfboard_studio.lvs import run_lvs
from perfboard_studio.mcp.session import BoardSession, SessionError
from perfboard_studio.model import (
    ComponentInstance,
    DocumentMeta,
    HoleCoord,
    MountingHole,
    Net,
    NetNode,
    PerfDocument,
)
from perfboard_studio.persist import deserialize_document, serialize_document
from perfboard_studio.stripboard import cut_between, joined_by_board, segment_holes

FULL = breadboard("830")
HALF = breadboard("400")
MINI = breadboard("170")


def _doc(board=FULL, *components: ComponentInstance, nets: tuple[Net, ...] = ()) -> PerfDocument:  # type: ignore[no-untyped-def]
    return PerfDocument(
        meta=DocumentMeta(name="t", created="2026-01-01T00:00:00Z", modified="2026-01-01T00:00:00Z"),
        board=board,
        components=components,
        nets=nets,
    )


def _dip(ref: str, at: HoleCoord, rotation: int = 270) -> ComponentInstance:
    return ComponentInstance(
        id=f"cmp-{ref}", ref=ref, value="NE555", footprint_id="dip-8", anchor=at,
        rotation=rotation, mirrored=False, locked=False,  # type: ignore[arg-type]
    )


def _bus(doc: PerfDocument) -> CommandBus:
    return CommandBus(
        doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc))
    )


# ---------------------------------------------------------------------------
# The pattern
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", sorted(SIZES))
def test_a_breadboard_has_as_many_holes_as_it_is_sold_with(size: str) -> None:
    """The size a breadboard is sold by IS its tie-point count, so the pattern either
    reproduces it or is wrong."""
    board = breadboard(size)
    assert board.cols * board.rows - len(missing_holes(board)) == int(size)


def test_the_full_size_rails_stand_where_the_mb102s_do() -> None:
    """Fifty holes per rail, columns 3 to 61, in fives with one column left out -- read
    off Fritzing's drawing of the 03MB102."""
    columns = sorted(rail_columns(FULL))
    assert len(columns) == 50
    assert columns[0] + 1 == 3 and columns[-1] + 1 == 61
    groups = [columns[i : i + RAIL_GROUP] for i in range(0, 50, RAIL_GROUP)]
    assert all(group == list(range(group[0], group[0] + RAIL_GROUP)) for group in groups)
    assert all(b[0] - a[-1] == 2 for a, b in pairwise(groups))


def test_the_half_size_rails_are_put_on_the_nearest_columns() -> None:
    """Twenty-five holes, columns 1 to 29: the 0.37-pitch offset of the drawing rounded
    to the grid, as the module docstring says."""
    columns = sorted(rail_columns(HALF))
    assert len(columns) == 25
    assert (columns[0] + 1, columns[-1] + 1) == (1, 29)


def test_a_dip_straddles_a_channel_three_pitches_wide() -> None:
    """Row e to row f is 0.3 inch, which is a DIP's row spacing -- the whole reason the
    channel exists. Nothing in between has a hole."""
    e = parse_hole_name(FULL, "e10")
    f = parse_hole_name(FULL, "f10")
    assert e is not None and f is not None
    assert e.row - f.row == 3
    assert not any(has_hole(FULL, HoleCoord(10 - 1, row)) for row in range(f.row + 1, e.row))


def test_a_mini_breadboard_has_no_rails() -> None:
    names = {hole_name(MINI, HoleCoord(c, r)) for c in range(MINI.cols) for r in range(MINI.rows)}
    assert not any(name.startswith(("T", "B")) for name in names if name is not None)


@pytest.mark.parametrize("size", sorted(SIZES))
def test_every_hole_is_named_as_the_board_prints_it_and_read_back(size: str) -> None:
    board = breadboard(size)
    names: set[str] = set()
    for row in range(board.rows):
        for col in range(board.cols):
            hole = HoleCoord(col, row)
            name = hole_name(board, hole)
            assert (name is None) == (not has_hole(board, hole))
            if name is None:
                continue
            assert parse_hole_name(board, name) == hole
            names.add(name)
    assert len(names) == int(size)


def test_a_breadboard_name_cannot_be_mistaken_for_a_grid_address() -> None:
    """A perfboard address is upper-case column letters and a row; a breadboard's is a
    lower-case row letter and a column, or a rail. Neither parser accepts the other."""
    for name in ("e12", "j1", "T+3", "B-61"):
        with pytest.raises(ValueError):
            hole_ref_to_coord(name)
    assert parse_hole_name(FULL, "E12") is None
    assert parse_hole_name(FULL, "T+1") is None  # column 1 has no rail hole on an MB102
    assert parse_hole_name(MINI, "T+3") is None
    assert parse_hole_name(FULL, "e64") is None


def test_five_holes_share_a_clip_and_a_rail_shares_one_down_the_board() -> None:
    e8 = parse_hole_name(FULL, "e8")
    assert e8 is not None
    assert [hole_name(FULL, h) for h in clip_holes(FULL, e8)] == ["e8", "d8", "c8", "b8", "a8"]
    rail = parse_hole_name(FULL, "T+3")
    assert rail is not None
    assert len(clip_holes(FULL, rail)) == 50
    f8 = parse_hole_name(FULL, "f8")
    assert f8 is not None and clip_of(FULL, f8) != clip_of(FULL, e8)


# ---------------------------------------------------------------------------
# What reads strips reads clips
# ---------------------------------------------------------------------------


def test_the_board_joins_a_clip_and_nothing_can_cut_it() -> None:
    doc = _doc()
    a, b = parse_hole_name(FULL, "a5"), parse_hole_name(FULL, "e5")
    assert a is not None and b is not None
    assert joined_by_board(doc, a, b)
    assert len(segment_holes(doc, a)) == 5
    assert cut_between(doc, a, b) is None


def test_a_dip_across_the_channel_has_eight_separate_pins() -> None:
    doc = _doc(FULL, _dip("U1", HoleCoord(10, 11)))
    assert [hole_name(FULL, h) for _, h in all_pin_holes(doc.components[0], get_footprint("dip-8"))] == [  # type: ignore[arg-type]
        "e11", "e12", "e13", "e14", "f14", "f13", "f12", "f11",
    ]
    nets = extract_physical_nets(doc, get_footprint)
    assert all(len(net.pins) == 1 for net in nets)


def test_a_dip_on_one_half_is_shorted_by_the_board_and_lvs_says_so() -> None:
    """Turned so its rows run down the columns, a DIP puts four pins in one clip. Nothing
    about that is a DRC finding -- the document is fine -- and it is exactly what LVS
    exists to say."""
    nets = (
        Net(id="n1", name="GND", nodes=(NetNode(component_ref="U1", pin="1"),)),
        Net(id="n2", name="TRIG", nodes=(NetNode(component_ref="U1", pin="2"),)),
    )
    doc = _doc(FULL, _dip("U1", HoleCoord(10, 11), rotation=0), nets=nets)
    joined = [sorted(p.pin for p in net.pins) for net in extract_physical_nets(doc, get_footprint)]
    assert ["1", "2", "3", "4"] in joined
    assert any(issue.kind == "short" for issue in run_lvs(doc, get_footprint).issues)


def test_a_jumper_end_in_an_empty_hole_reaches_the_lead_in_its_clip() -> None:
    """The clip grips whatever is pushed in from above, so a jumper's top-side end joins
    the pin three holes along -- where on stripboard only the copper side counts."""
    doc = _doc(FULL, _dip("U1", HoleCoord(10, 11)))
    a3 = parse_hole_name(FULL, "a11")  # e11 is pin 1's clip
    rail = parse_hole_name(FULL, "B-11")
    assert a3 is not None and rail is not None
    result = _bus(doc).dispatch(
        "conductor.add",
        AddConductorPayload(conductor=NewWireConductor(path=(a3, rail), kind="top-jumper", side="top")),
    )
    assert result.ok, result.message
    assert result.document is not None
    nets = extract_physical_nets(result.document, get_footprint)
    pin1 = next(net for net in nets if any(p.pin == "1" for p in net.pins))
    assert result.document.conductors[0].id in pin1.conductor_ids


# ---------------------------------------------------------------------------
# DRC
# ---------------------------------------------------------------------------


def test_a_pin_in_the_channel_is_an_error_and_every_planner_sees_the_same_holes() -> None:
    doc = _doc(FULL, _dip("U1", HoleCoord(10, 11), rotation=180))
    findings = [v for v in run_drc(doc, get_footprint) if v.rule == "no-hole"]
    assert len(findings) == 4
    assert holeless_positions(FULL) <= unusable_holes(doc)
    assert all(hole_key(h) in unusable_holes(doc) for f in findings for h in f.holes)


def test_solder_is_an_error_on_a_breadboard_and_a_jumper_is_not() -> None:
    a, b = parse_hole_name(FULL, "a5"), parse_hole_name(FULL, "a6")
    c = parse_hole_name(FULL, "a9")
    assert a is not None and b is not None and c is not None
    bus = _bus(_doc())
    assert bus.dispatch("conductor.add", AddConductorPayload(conductor=NewSolderTraceConductor(path=(a, b)))).ok
    assert bus.dispatch(
        "conductor.add",
        AddConductorPayload(conductor=NewWireConductor(path=(a, c), kind="insulated-wire", side="top")),
    ).ok
    rules = [v.rule for v in run_drc(bus.document, get_footprint)]
    assert rules.count("not-on-breadboard") == 1


def test_no_breadboard_rule_fires_on_any_other_board() -> None:
    doc = dataclasses.replace(_doc(FULL), board=dataclasses.replace(FULL, type="pad-per-hole"))
    assert holeless_positions(doc.board) == frozenset()
    assert not {"no-hole", "not-on-breadboard"} & {v.rule for v in run_drc(doc, get_footprint)}


# ---------------------------------------------------------------------------
# What a breadboard refuses
# ---------------------------------------------------------------------------


def test_a_breadboard_is_twenty_rows_or_twelve_at_the_standard_pitch() -> None:
    """Twenty or twelve, and one more for every pitch a wide channel adds -- up to 1.5 inch
    with rails (32 rows); fewer than twelve or more than that is no breadboard."""
    bus = _bus(_doc(dataclasses.replace(FULL, type="pad-per-hole")))
    for board in (
        dataclasses.replace(FULL, rows=11),
        dataclasses.replace(FULL, rows=33),
        dataclasses.replace(FULL, pitch=2.0),
    ):
        result = bus.dispatch("board.set", SetBoardPayload(board=board))
        assert not result.ok and result.code == "invalid-board"
    assert bus.dispatch("board.set", SetBoardPayload(board=HALF)).ok


def test_nothing_is_drilled_into_a_breadboard() -> None:
    bus = _bus(_doc())
    hole = parse_hole_name(FULL, "a5")
    assert hole is not None
    for type_, payload in (
        ("mounting-hole.add", AddMountingHolePayload(at=hole)),
        ("edge-connector.add", AddEdgeConnectorPayload(edge="top", start=0, count=4)),
    ):
        result = bus.dispatch(type_, payload)
        assert not result.ok and result.code == "breadboard"

    drilled = dataclasses.replace(
        _doc(dataclasses.replace(FULL, type="pad-per-hole")),
        mounting_holes=(MountingHole(id="mh1", at=hole),),
    )
    result = _bus(drilled).dispatch("board.set", SetBoardPayload(board=FULL))
    assert not result.ok and result.code == "breadboard"


def test_a_breadboard_survives_the_file_and_a_wrong_one_does_not_load() -> None:
    doc = _doc(HALF, _dip("U1", HoleCoord(10, 11)))
    loaded = deserialize_document(serialize_document(doc))
    assert loaded.ok
    assert loaded.document.board == HALF

    text = serialize_document(doc).replace('"rows": 20', '"rows": 11', 1)
    refused = deserialize_document(text)
    assert not refused.ok
    assert refused.code == "invalid-board"


# ---------------------------------------------------------------------------
# What a hole is called, everywhere
# ---------------------------------------------------------------------------


def test_a_hole_is_named_as_the_board_it_is_on_prints_it() -> None:
    e11 = HoleCoord(10, 11)
    assert format_hole(e11) == "K12"
    assert format_hole(e11, dataclasses.replace(FULL, type="pad-per-hole")) == "K12"
    assert format_hole(e11, FULL) == "e11"
    assert format_hole(HoleCoord(10, 9), FULL) == "column 11 (no hole)"
    assert format_hole(HoleCoord(-1, 3), FULL) == "(col -1, row 3)"


def test_a_breadboard_reads_only_its_own_names_in_either_case() -> None:
    """Everything the tool says about a breadboard is in its own names, so those are what
    it reads; a grid address beside them would make "A1" two different holes."""
    assert parse_hole("e11", FULL) == parse_hole("E11", FULL) == HoleCoord(10, 11)
    assert parse_hole("t+3", FULL) == parse_hole("T+3", FULL) == HoleCoord(2, 1)
    with pytest.raises(ValueError, match="row letter a-j"):
        parse_hole("K12", FULL)
    assert parse_hole("k12", dataclasses.replace(FULL, type="pad-per-hole")) == HoleCoord(10, 11)


def test_drc_names_a_breadboard_hole_as_the_board_prints_it() -> None:
    doc = _doc(FULL, _dip("U1", HoleCoord(10, 11), rotation=180))
    messages = [v.message for v in run_drc(doc, get_footprint) if v.rule == "no-hole"]
    assert messages and all("(no hole)" in m for m in messages)
    assert not any("K1" in m for m in messages)


def test_an_agent_places_and_reads_back_in_breadboard_names() -> None:
    session = BoardSession(document=_doc(FULL))
    result = session.place_component("U1", "dip-8", "e11", rotation=270)
    assert result["ok"], result
    assert session.document.components[0].anchor == HoleCoord(10, 11)
    assert session.check_heights()["parts"][0]["at"] == "e11"
    with pytest.raises(SessionError, match="row letter a-j"):
        session.place_component("U2", "dip-8", "K12", rotation=270)


def test_a_breadboard_leaves_as_step_with_its_own_holes_and_leads_in_their_clips() -> None:
    """The plate is drilled only where the pattern has a hole, and every lead ends inside
    the plastic -- the 3D view's depth (``CLIP_DEPTH_MM``) -- instead of below it."""
    from perfboard_studio.step_export import Cylinder, Plate, board_model

    doc = _doc(FULL, _dip("U1", HoleCoord(10, 11)))
    parts = board_model(doc, get_footprint)
    plate = next(s.shape for s in parts[0].solids if isinstance(s.shape, Plate))
    assert len(plate.holes) == 830
    leads = [
        s.shape for part in parts[1:] for s in part.solids
        if isinstance(s.shape, Cylinder) and s.shape.axis == (0.0, 0.0, 1.0)
    ]
    assert leads and all(lead.base[2] == pytest.approx(FULL.thickness - CLIP_DEPTH_MM) for lead in leads)
