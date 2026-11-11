"""Rails: solder laid along a stock board's outside finger strip (0.25).

An outside finger is a CELL, a place one step past the grid (col -1, col cols, row -1,
row rows), and a rail is an ordinary solder run along the cells. That makes the grid's
coordinates negative for the first time in a document a command accepts, so this file
pins what that must not disturb as much as what it adds: a negative index into anything
kept as a list reads the far edge, silently.
"""

from __future__ import annotations

import dataclasses

import pytest

from perfboard_studio.boardfamily import STANDARD_PRESETS
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    AddConductorPayload,
    AddEdgeConnectorPayload,
    DeleteEdgeConnectorPayload,
    NewSolderTraceConductor,
    NewWireConductor,
    SetBoardPayload,
    create_document_id_generator,
    create_empty_document,
    create_standard_registry,
    document_on_preset,
)
from perfboard_studio.connectivity import extract_physical_nets
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import (
    edge_beside,
    finger_cell_mm,
    finger_cells,
    format_hole,
    hole_key,
    holeless_positions,
    holes_without_grid_pad,
    parse_hole,
    undrilled_holes,
)
from perfboard_studio.model import (
    Board,
    DocumentMeta,
    HoleCoord,
    PerfDocument,
    SolderTraceConductor,
    WireConductor,
)
from perfboard_studio.occupancy import build_occupancy
from perfboard_studio.router import (
    RouteRequest,
    _dead_hole_keys,
    _trace_blocked_holes,
    route_connection,
)
from perfboard_studio.stripboard import cut_holes

LOOKUP = footprint_lookup()
META = DocumentMeta(name="rails", created="", modified="")


def _preset(name: str, family: str):  # type: ignore[no-untyped-def]
    return next(p for p in STANDARD_PRESETS if p.name == name and p.family == family)


def _bus(doc: PerfDocument) -> CommandBus:
    return CommandBus(
        doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc))
    )


def _stock() -> PerfDocument:
    """The 5 x 7 cm double-sided board as sold, finger strips down both long sides, plus
    a strip along the top and the bottom so that row -1 and row ``rows`` have fingers too."""
    doc = document_on_preset(create_empty_document(META), _preset("5 x 7 cm", "double-sided-fr4"))
    bus = _bus(doc)
    for edge in ("top", "bottom"):
        result = bus.dispatch(
            "edge-connector.add",
            AddEdgeConnectorPayload(
                edge=edge, start=3, count=doc.board.cols - 6, finger_width=1.7,
                face="both", outside=True, id=f"ec-x-{edge}",
            ),
        )
        assert result.ok, result.message
    return bus.document


def _with(doc: PerfDocument, *specs: NewSolderTraceConductor | NewWireConductor) -> PerfDocument:
    bus = _bus(doc)
    for spec in specs:
        result = bus.dispatch("conductor.add", AddConductorPayload(conductor=spec))
        assert result.ok, result.message
    return bus.document


def _refusal(doc: PerfDocument, spec: NewSolderTraceConductor | NewWireConductor) -> str:
    result = _bus(doc).dispatch("conductor.add", AddConductorPayload(conductor=spec))
    assert not result.ok
    return result.code or ""


def H(col: int, row: int) -> HoleCoord:
    return HoleCoord(col, row)


# ---------------------------------------------------------------------------
# Which places are cells
# ---------------------------------------------------------------------------


def test_every_surviving_outside_finger_is_a_cell_one_step_past_its_hole() -> None:
    doc = _stock()
    cells = finger_cells(doc)
    board = doc.board
    assert cells, "the stock board's strips give cells"
    for key, cell in cells.items():
        assert key == hole_key(cell.cell)
        assert edge_beside(cell.cell, board) == (cell.beside, cell.connector.edge)
    # Down the long sides: every row but the ones the strip skips at the ends.
    left = sorted(c.cell.row for c in cells.values() if c.connector.edge == "left")
    strip = next(c for c in doc.edge_connectors if c.edge == "left")
    assert left == list(range(strip.start, strip.start + strip.count))


def test_a_cell_is_drawn_on_its_fingers_copper_wherever_the_strip_was_made() -> None:
    """The cell is an address: on the 9 x 15 cm board one pitch past the grid is 4 mm short
    of the copper, so a renderer asks ``finger_cell_mm``, never ``hole_to_mm``."""
    from perfboard_studio.geometry import edge_finger_rect

    for name in ("5 x 7 cm", "6 x 8 cm", "9 x 15 cm"):
        doc = document_on_preset(create_empty_document(META), _preset(name, "double-sided-fr4"))
        for cell in finger_cells(doc).values():
            at = finger_cell_mm(cell, doc.board)
            rect = edge_finger_rect(cell.connector, cell.beside, doc.board)
            assert rect.x < at.x < rect.x + rect.width
            assert rect.y < at.y < rect.y + rect.height


def test_a_path_point_is_on_the_finger_for_a_cell_and_the_hole_for_the_rest() -> None:
    """``path_point_mm`` is the one function 2D, 3D and the STEP export ask: a cell goes to
    its finger's copper, every other hole -- the bridge's other end, a hole one step past
    an edge with no finger beside it -- stays where ``hole_to_mm`` puts it."""
    from perfboard_studio.geometry import hole_to_mm, path_point_mm

    for name in ("5 x 7 cm", "9 x 15 cm"):
        doc = document_on_preset(create_empty_document(META), _preset(name, "double-sided-fr4"))
        board = doc.board
        cells = finger_cells(doc)
        cell = next(iter(cells.values()))
        assert path_point_mm(cell.cell, board, cells) == finger_cell_mm(cell, board)
        assert path_point_mm(cell.beside, board, cells) == hole_to_mm(cell.beside, board)
        # Off the grid with no finger there: the address's own point, as before.
        corner = H(-1, -1)
        assert hole_key(corner) not in cells
        assert path_point_mm(corner, board, cells) == hole_to_mm(corner, board)
        assert path_point_mm(cell.cell, board, {}) == hole_to_mm(cell.cell, board)


def test_the_window_and_an_agent_build_a_rail_from_one_function() -> None:
    """``commands.rail_payload`` is what the window's "make this strip a rail" and MCP's
    ``add_rail`` both dispatch, from the cells ``strip_cells`` lists in order."""
    from perfboard_studio.command import CommandError
    from perfboard_studio.commands import rail_payload
    from perfboard_studio.geometry import strip_cells
    from perfboard_studio.mcp.session import BoardSession

    doc = _stock()
    strip = strip_cells(doc, "ec-left")
    assert [c.cell.row for c in strip] == sorted(c.cell.row for c in strip)
    assert all(c.connector.id == "ec-left" for c in strip)
    assert {hole_key(c.cell) for c in strip} <= set(finger_cells(doc))
    assert strip_cells(doc, "no-such-strip") == ()
    first, last = strip[2], strip[10]
    payload = rail_payload(doc, first.cell, last.cell, bridges=[first.beside, last.beside])
    assert payload.label == f"Lay a rail {format_hole(first.cell, doc.board)}–{format_hole(last.cell, doc.board)}"
    bus = _bus(doc)
    assert bus.dispatch("conductor.addMany", payload).ok
    session = BoardSession(document=doc)
    assert session.add_rail(
        format_hole(first.cell, doc.board),
        format_hole(last.cell, doc.board),
        bridges=[format_hole(first.beside, doc.board), format_hole(last.beside, doc.board)],
    )["ok"]
    shape = [(c.kind, c.path, c.side) for c in bus.document.conductors]
    assert shape == [(c.kind, c.path, c.side) for c in session.document.conductors]
    with pytest.raises(CommandError) as refused:
        rail_payload(doc, first.cell, H(doc.board.cols, 5))
    assert refused.value.code == "not-a-rail"


def test_a_board_of_joined_holes_has_no_cells() -> None:
    doc = _stock()
    striped = dataclasses.replace(doc, board=dataclasses.replace(doc.board, type="stripboard"))
    assert finger_cells(striped) == {}


def test_a_finger_a_bore_took_is_not_a_cell() -> None:
    doc = _stock()
    assert doc.mounting_holes, "the stock board has its corner screws"
    without = dataclasses.replace(doc, mounting_holes=())
    assert set(finger_cells(doc)) <= set(finger_cells(without))


# ---------------------------------------------------------------------------
# Condition 4: what format_hole prints, parse_hole reads back
# ---------------------------------------------------------------------------


def test_a_finger_is_named_by_the_hole_beside_it_and_read_back() -> None:
    doc = _stock()
    board = doc.board
    assert format_hole(H(-1, 6), board) == "A7/L"
    assert format_hole(H(board.cols, 6), board).endswith("7/R")
    assert format_hole(H(4, -1), board) == "E1/T"
    assert format_hole(H(4, board.rows), board) == f"E{board.rows}/B"
    for cell in finger_cells(doc).values():
        text = format_hole(cell.cell, board)
        assert parse_hole(text, board) == cell.cell
        assert parse_hole(text.lower(), board) == cell.cell


@pytest.mark.parametrize("preset", [p for p in STANDARD_PRESETS], ids=lambda p: f"{p.family}-{p.name}")
def test_every_place_one_step_past_any_stock_grid_round_trips(preset) -> None:  # type: ignore[no-untyped-def]
    board = document_on_preset(create_empty_document(META), preset).board
    places = [H(-1, r) for r in range(board.rows)] + [H(board.cols, r) for r in range(board.rows)]
    places += [H(c, -1) for c in range(board.cols)] + [H(c, board.rows) for c in range(board.cols)]
    for place in places:
        assert parse_hole(format_hole(place, board), board) == place


def test_a_name_past_an_edge_must_be_beside_that_edge() -> None:
    board = _stock().board
    for text in ("B7/L", "A7/R", "E2/T", "E1/B", f"A{board.rows + 1}/L"):
        with pytest.raises(ValueError):
            parse_hole(text, board)


def test_a_corner_and_anything_further_out_keep_the_plain_coordinates() -> None:
    board = _stock().board
    assert format_hole(H(-1, -1), board) == "(col -1, row -1)"
    assert format_hole(H(-2, 3), board) == "(col -2, row 3)"
    assert format_hole(H(-1, 3)) == "(col -1, row 3)", "no board, no edge to name"


# ---------------------------------------------------------------------------
# Condition 2: off the board stays off the board
# ---------------------------------------------------------------------------


def test_solder_lies_on_a_finger_on_either_face_it_has_copper_on() -> None:
    doc = _stock()
    for side in ("bottom", "top"):
        railed = _with(
            doc,
            NewSolderTraceConductor(path=(H(0, 6), H(-1, 6), H(-1, 7), H(-1, 8)), side=side),
        )
        assert not [v for v in run_drc(railed, LOOKUP) if v.rule == "conductor-off-board"]


@pytest.mark.parametrize(
    ("kind", "side"),
    [("bare-wire", "bottom"), ("insulated-wire", "bottom"), ("top-jumper", "top")],
)
def test_a_wire_is_refused_a_finger_even_where_one_stands(kind: str, side: str) -> None:
    doc = _stock()
    spec = NewWireConductor(path=(H(0, 6), H(-1, 6)), kind=kind, side=side)  # type: ignore[arg-type]
    assert _refusal(doc, spec) == "not-on-finger"


def test_solder_is_refused_where_no_finger_stands() -> None:
    stock = _stock()
    strip = next(c for c in stock.edge_connectors if c.edge == "left")
    assert strip.start > 0, "the strip leaves the corner rows bare"
    blank = create_empty_document(META, stock.board)
    for doc, path in (
        (blank, (H(0, 6), H(-1, 6))),  # no strip on this board at all
        (stock, (H(0, 0), H(-1, 0))),  # beside the strip's end
        (stock, (H(-1, 0), H(-1, -1))),  # the corner
        (stock, (H(0, 6), H(-1, 6), H(-2, 6))),  # past the finger
    ):
        assert _refusal(doc, NewSolderTraceConductor(path=path)) == "off-board"


def test_solder_is_refused_a_face_the_finger_has_no_copper_on() -> None:
    stock = _stock()
    underneath = dataclasses.replace(
        stock,
        edge_connectors=tuple(dataclasses.replace(c, face="bottom") for c in stock.edge_connectors),
    )
    spec = NewSolderTraceConductor(path=(H(0, 6), H(-1, 6)), side="top")
    assert _refusal(underneath, spec) == "not-on-finger"
    _with(underneath, dataclasses.replace(spec, side="bottom"))


def test_drc_reports_a_wire_on_a_finger_and_solder_off_it_but_not_a_rail() -> None:
    """The other door: a file that holds them anyway still opens and is told."""
    stock = _stock()
    rail = SolderTraceConductor(id="rail", path=(H(0, 6), H(-1, 6), H(-1, 7)))
    wire = WireConductor(id="wire", path=(H(0, 9), H(-1, 9)))
    stray = SolderTraceConductor(id="stray", path=(H(0, 0), H(-1, 0)))
    doc = dataclasses.replace(stock, conductors=(rail, wire, stray))
    off = {v.conductor_ids[0]: v for v in run_drc(doc, LOOKUP) if v.rule == "conductor-off-board"}
    assert set(off) == {"wire", "stray"}
    assert off["wire"].holes == (H(-1, 9),)


# ---------------------------------------------------------------------------
# A finger has no hole, so no plating
# ---------------------------------------------------------------------------


def _net_of(doc: PerfDocument, conductor_id: str) -> int:
    nets = extract_physical_nets(doc, LOOKUP)
    return next(i for i, net in enumerate(nets) if conductor_id in net.conductor_ids)


def test_solder_on_a_fingers_two_faces_is_two_pieces_of_copper() -> None:
    stock = _stock()
    under = SolderTraceConductor(id="under", path=(H(0, 6), H(-1, 6)), side="bottom")
    over = SolderTraceConductor(id="over", path=(H(-1, 6), H(-1, 7)), side="top")
    doc = dataclasses.replace(stock, conductors=(under, over))
    assert _net_of(doc, "under") != _net_of(doc, "over")
    # ...where the same pair in a pinless grid hole is joined through its plating.
    under_grid = dataclasses.replace(under, path=(H(4, 6), H(5, 6)))
    over_grid = dataclasses.replace(over, path=(H(5, 6), H(5, 7)))
    joined = dataclasses.replace(stock, conductors=(under_grid, over_grid))
    assert _net_of(joined, "under") == _net_of(joined, "over")


# ---------------------------------------------------------------------------
# Condition 1: col -1 and row -1 are not the far edge
# ---------------------------------------------------------------------------


def _railed() -> tuple[PerfDocument, PerfDocument]:
    """The stock board, and the same board with a rail on col -1 and one on row -1."""
    stock = _stock()
    railed = _with(
        stock,
        NewSolderTraceConductor(path=(H(0, 6), H(-1, 6), H(-1, 7), H(-1, 8), H(-1, 9))),
        NewSolderTraceConductor(path=(H(5, 0), H(5, -1), H(6, -1), H(7, -1), H(8, -1))),
    )
    return stock, railed


def _far(board: Board) -> list[HoleCoord]:
    """The last column and the last row: what col -1 and row -1 index in a list."""
    return [H(board.cols - 1, r) for r in range(board.rows)] + [
        H(c, board.rows - 1) for c in range(board.cols)
    ]


def test_a_rail_off_the_near_edges_leaves_the_far_edges_occupancy_as_it_was() -> None:
    stock, railed = _railed()
    before = build_occupancy(stock, LOOKUP)
    after = build_occupancy(railed, LOOKUP)
    for hole in _far(stock.board):
        for side in ("top", "bottom"):
            assert after.conductors_at(hole, side) == before.conductors_at(hole, side)  # type: ignore[arg-type]
            assert after.is_copper_blocked(hole, side) == before.is_copper_blocked(hole, side)  # type: ignore[arg-type]
    # ...and the rails' own cells are occupied where they are.
    assert after.is_copper_blocked(H(-1, 7), "bottom")
    assert after.is_copper_blocked(H(6, -1), "bottom")


def test_a_rail_off_the_near_edges_leaves_the_routers_far_edges_as_they_were() -> None:
    stock, railed = _railed()
    far = {(h.col, h.row) for h in _far(stock.board)}
    far_keys = {hole_key(h) for h in _far(stock.board)}
    assert _trace_blocked_holes(railed) & far == _trace_blocked_holes(stock) & far
    assert _dead_hole_keys(railed) & far_keys == _dead_hole_keys(stock) & far_keys
    board = stock.board
    for request in (
        RouteRequest(from_=H(board.cols - 1, 4), to=H(board.cols - 1, 12)),
        RouteRequest(from_=H(3, board.rows - 1), to=H(14, board.rows - 1)),
    ):
        a = route_connection(stock, LOOKUP, request)
        b = route_connection(railed, LOOKUP, request)
        assert a.ok and b.ok
        assert a.best is not None and b.best is not None
        assert b.best.conductors == a.best.conductors


def test_a_rail_off_the_near_edges_leaves_drc_at_the_far_edges_as_it_was() -> None:
    stock, railed = _railed()
    far = set(_far(stock.board))

    def at_far(doc: PerfDocument) -> list[tuple[str, tuple[HoleCoord, ...]]]:
        return sorted(
            (v.rule, v.holes) for v in run_drc(doc, LOOKUP) if far & set(v.holes)
        )

    assert at_far(railed) == at_far(stock)
    assert not [v for v in run_drc(railed, LOOKUP) if v.rule == "conductor-off-board"]


def test_a_rail_off_the_near_edges_leaves_the_2d_pad_grid_as_it_was() -> None:
    """What ``view2d`` hands ``PadGridItem``: the holes drawn with no round pad."""
    stock, railed = _railed()

    def padless(doc: PerfDocument, side: str) -> frozenset[str]:
        return (
            holes_without_grid_pad(doc, side)  # type: ignore[arg-type]
            | undrilled_holes(doc)
            | cut_holes(doc)
            | holeless_positions(doc.board)
        )

    for side in ("top", "bottom"):
        assert padless(railed, side) == padless(stock, side)


# ---------------------------------------------------------------------------
# A change that takes a finger away from under a rail is refused
# ---------------------------------------------------------------------------


def test_a_strip_with_a_rail_on_it_cannot_be_deleted_from_under_it() -> None:
    _, railed = _railed()
    result = _bus(railed).dispatch("edge-connector.delete", DeleteEdgeConnectorPayload(id="ec-left"))
    assert not result.ok
    assert result.code == "would-strand-conductor"
    assert "A7/L" in (result.message or "")
    # The strip with no rail on it goes.
    result = _bus(railed).dispatch("edge-connector.delete", DeleteEdgeConnectorPayload(id="ec-right"))
    assert result.ok, result.message


def test_a_board_grown_past_a_rail_is_refused_and_one_grown_away_from_it_is_not() -> None:
    """Grown by a row, the bottom fingers' row would be a row of the grid and the rail on it
    a run nobody laid."""
    stock = _stock()
    bottom = _with(
        stock,
        NewSolderTraceConductor(
            path=(H(5, stock.board.rows - 1), H(5, stock.board.rows), H(6, stock.board.rows))
        ),
    )
    taller = dataclasses.replace(stock.board, rows=stock.board.rows + 1)
    result = _bus(bottom).dispatch("board.set", SetBoardPayload(board=taller))
    assert not result.ok
    assert result.code == "would-strand-conductor"
    assert f"F{stock.board.rows}/B" in (result.message or "")

    _, railed = _railed()
    wider = dataclasses.replace(railed.board, cols=railed.board.cols + 1)
    result = _bus(railed).dispatch("board.set", SetBoardPayload(board=wider))
    assert result.ok, result.message


def test_a_bore_drilled_into_a_railed_finger_is_refused_and_one_beside_the_rail_is_not() -> None:
    from perfboard_studio.commands import AddMountingHolePayload

    _, railed = _railed()

    def drill(row: int) -> tuple[bool, str]:
        result = _bus(railed).dispatch(
            "mounting-hole.add",
            AddMountingHolePayload(at=H(0, row), offset_x_mm=-2.54, diameter=2.2, head_diameter=4.0),
        )
        return result.ok, result.code or ""

    assert drill(8) == (False, "would-strand-conductor")
    assert drill(12) == (True, "")


# ---------------------------------------------------------------------------
# The router reaches a rail as it reaches a pin
# ---------------------------------------------------------------------------


def _left_rail(stock: PerfDocument, rows: range, side: str = "bottom") -> PerfDocument:
    """A rail down the left strip over ``rows``, bridged at its first row to A<first+1>."""
    first = rows[0]
    return _with(
        stock,
        NewSolderTraceConductor(
            path=(H(0, first), *(H(-1, r) for r in rows)), side=side  # type: ignore[arg-type]
        ),
    )


def _joined(doc: PerfDocument, a: HoleCoord, b: HoleCoord) -> bool:
    for net in extract_physical_nets(doc, LOOKUP):
        holes = {node.hole for node in net.nodes}
        if a in holes and b in holes:
            return True
    return False


def test_a_connection_to_a_railed_end_goes_to_the_nearest_finger_and_bridges_onto_it() -> None:
    from perfboard_studio.commands import AddConductorsPayload
    from perfboard_studio.geometry import bridge_needs_spine

    stock = _stock()
    strip = next(c for c in stock.edge_connectors if c.edge == "left")
    rows = range(strip.start, strip.start + strip.count)
    railed = _left_rail(stock, rows)
    start, end = H(2, rows[-1]), H(0, rows[0])

    result = route_connection(railed, LOOKUP, RouteRequest(from_=start, to=end))
    assert result.ok and result.best is not None
    bridge = result.best.conductors[-1]
    assert bridge.path == (H(0, rows[-1]), H(-1, rows[-1]))
    cell = finger_cells(railed)[hole_key(H(-1, rows[-1]))]
    assert bridge_needs_spine(cell, railed.board), "1.4 mm on this board: wider than solder spans"
    assert bridge.kind == "solder-trace-wired"
    assert "bridged onto the rail at A" in result.best.explanation

    bus = _bus(railed)
    applied = bus.dispatch("conductor.addMany", AddConductorsPayload(conductors=result.best.conductors))
    assert applied.ok, applied.message
    assert _joined(bus.document, start, end)


def test_a_pin_beside_the_rail_is_just_a_bridge() -> None:
    stock = _stock()
    railed = _left_rail(stock, range(3, 17))
    result = route_connection(railed, LOOKUP, RouteRequest(from_=H(0, 16), to=H(0, 3)))
    assert result.ok and result.best is not None
    assert [c.path for c in result.best.conductors] == [(H(0, 16), H(-1, 16))]
    # Five holes away, the trace down the column is cheaper than a wired bridge, and taken.
    near = route_connection(railed, LOOKUP, RouteRequest(from_=H(0, 8), to=H(0, 3)))
    assert near.best is not None and all(c.path[-1].col == 0 for c in near.best.conductors)


def test_a_rail_nothing_joins_to_the_connection_is_not_reached() -> None:
    """Never another net's rail: only the copper an end is physically on counts."""
    stock = _stock()
    railed = _left_rail(stock, range(3, 16))
    result = route_connection(railed, LOOKUP, RouteRequest(from_=H(2, 15), to=H(6, 2)))
    assert result.ok and result.best is not None
    assert all(c.path[-1].col >= 0 for c in result.best.conductors)


def test_a_rail_on_the_component_side_is_bridged_on_its_own_face() -> None:
    stock = _stock()
    rows = range(3, 16)
    railed = _left_rail(stock, rows, side="top")
    result = route_connection(railed, LOOKUP, RouteRequest(from_=H(2, 15), to=H(0, 3)))
    assert result.ok and result.best is not None
    bridge = result.best.conductors[-1]
    assert bridge.path[-1] == H(-1, 15) and bridge.side == "top"


# ---------------------------------------------------------------------------
# What DRC, the guide and an agent are told
# ---------------------------------------------------------------------------


def _rules(doc: PerfDocument, rule: str) -> list:  # type: ignore[type-arg]
    return [v for v in run_drc(doc, LOOKUP) if v.rule == rule]


def test_a_rail_no_bridge_joins_to_the_board_carries_nothing() -> None:
    stock = _stock()
    alone = _with(stock, NewSolderTraceConductor(path=(H(-1, 4), H(-1, 5), H(-1, 6))))
    found = _rules(alone, "rail-without-bridge")
    assert len(found) == 1 and found[0].severity == "warning"
    assert found[0].holes == (H(-1, 4), H(-1, 5), H(-1, 6))
    assert "A5/L" in found[0].message and "A7/L" in found[0].message
    assert not _rules(_left_rail(stock, range(4, 7)), "rail-without-bridge")


def test_plain_solder_across_a_gap_wider_than_it_spans_is_warned_and_a_spine_is_not() -> None:
    from perfboard_studio.model import SpineSpec

    stock = _stock()
    plain = _left_rail(stock, range(4, 9))  # bridged with plain solder: 1.4 mm
    found = _rules(plain, "solder-gap-needs-spine")
    assert len(found) == 1 and found[0].holes == (H(0, 4), H(-1, 4))
    wired = _with(
        stock,
        NewSolderTraceConductor(path=tuple(H(-1, r) for r in range(4, 9))),
        NewSolderTraceConductor(
            path=(H(0, 4), H(-1, 4)), kind="solder-trace-wired",
            spine=SpineSpec(material="tinned-copper", gauge=0.6),
        ),
    )
    # Finger to finger is 0.84 mm on this strip: plain solder spans it.
    assert not _rules(wired, "solder-gap-needs-spine")


def test_the_guide_says_once_what_a_fingers_address_is_and_keeps_its_suffix_off_it() -> None:
    from perfboard_studio.guide import ConductorStep, GuideOptions, build_guide

    railed = _left_rail(_stock(), range(4, 9))
    for language, said in (
        ("en", "A5/L is the finger on the left edge beside A5"),
        ("tr", "A5/L, sol kenarda A5 deliğinin yanındaki parmaktır"),
    ):
        guide = build_guide(railed, LOOKUP, GuideOptions(language=language))
        notes = [
            note
            for phase in guide.phases
            for step in phase.steps
            if isinstance(step, ConductorStep)
            for note in step.notes
            if said in note
        ]
        assert len(notes) == 1, (language, notes)
        # The railed strip is laid by a step; the other is still a connector to keep clear.
        connector = next(w for w in guide.warnings if w.code == "edge-connector")
        assert ("sol" if language == "tr" else "left") not in connector.message.split("(")[1]


def test_an_agent_lays_a_rail_with_its_bridges_as_one_step() -> None:
    from perfboard_studio.mcp.session import BoardSession, SessionError

    session = BoardSession(document=_stock())
    info = {c["id"]: c for c in session.get_board_info()["edge_connectors"]}
    assert "A2/L" in info["ec-left"]["fingers"]
    result = session.add_rail("A4/L", "A12/L", bridges=["A4", "A12"])
    assert result["ok"], result
    assert len(result["ids"]) == 3
    laid = {c.id: c for c in session.document.conductors}
    bridges = [laid[i] for i in result["ids"] if len(laid[i].path) == 2]
    assert {b.kind for b in bridges} == {"solder-trace-wired"}
    assert not _rules(session.document, "rail-without-bridge")
    assert not _rules(session.document, "solder-gap-needs-spine")
    assert _joined(session.document, H(0, 3), H(0, 11))
    for start, end, bridges_ in (
        ("A4/L", "X4/R", None),  # two edges
        ("A4", "A12", None),  # grid holes, not fingers
        ("A4/L", "A12/L", ["B5"]),  # not beside the rail
        ("A4/L", "A8/L", ["A12"]),  # beside the strip, not this rail
    ):
        with pytest.raises(SessionError):
            session.add_rail(start, end, bridges=bridges_)


def test_both_rail_warnings_are_said_in_turkish() -> None:
    """Neither rule fires on a board in the repository, so the every-board test never meets
    them: each is produced here and said through the panel's own path."""
    from perfboard_studio.ui.engine_text import finding_text, names_in
    from perfboard_studio.ui.i18n import language, set_language

    stock = _stock()
    alone = _with(stock, NewSolderTraceConductor(path=(H(-1, 4), H(-1, 5), H(-1, 6))))
    plain = _left_rail(stock, range(4, 9))
    found = [
        (doc, v)
        for doc, rule in ((alone, "rail-without-bridge"), (plain, "solder-gap-needs-spine"))
        for v in _rules(doc, rule)
    ]
    assert len(found) == 2
    before = language()
    try:
        for doc, v in found:
            names = names_in(doc, v.message, v.conductor_ids)
            set_language("en")
            english = finding_text(v.message, names)
            set_language("tr")
            turkish = finding_text(v.message, names)
            assert turkish != english, english
            assert "A5/L" in turkish or "A4" in turkish
    finally:
        set_language(before)


def test_a_long_rail_is_named_by_its_fingers() -> None:
    """``solder-trace-too-long`` names a conductor by its ends, and a rail's ends are fingers:
    "A3/L", which the guide and every other rule print, not the coordinate past the grid."""
    railed = _with(
        _stock(), NewSolderTraceConductor(path=tuple(H(-1, row) for row in range(2, 9)))
    )
    [long] = [v for v in run_drc(railed, LOOKUP) if v.rule == "solder-trace-too-long"]
    assert "(A3/L to A9/L)" in long.message, long.message
    assert "col -1" not in long.message
