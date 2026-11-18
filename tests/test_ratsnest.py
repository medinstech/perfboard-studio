"""Tests for the ratsnest (src/perfboard_studio/ratsnest.py).

The property that carries the module is that links are counted over PHYSICAL GROUPS,
not over pins: routing part of a net has to shrink the remaining work, and a closed net
has to report zero. Everything else here guards the details that make the result usable
as an autorouter work list -- shortest crossing chosen, spanning-tree size exact,
unlocatable pins reported rather than dropped, and byte-stable ordering.

The fixture helpers mirror the hand-built ones in tests/test_lvs.py rather than importing
them: these are small enough that a local, obvious definition beats a cross-test
dependency, and the two files are free to diverge as each grows.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.connectivity import FootprintLookup, PhysicalPinRef
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import format_hole
from perfboard_studio.model import (
    Board,
    BodySpec,
    ComponentInstance,
    Conductor,
    DocumentMeta,
    Footprint,
    FootprintPin,
    HoleCoord,
    Net,
    NetClass,
    NetNode,
    PerfDocument,
    SolderTraceConductor,
    WireConductor,
)
from perfboard_studio.ratsnest import (
    RatsnestLine,
    all_links,
    net_ratsnest,
    ratsnest,
    ratsnest_lines,
    summarize,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BOARD = Board(
    type="pad-per-hole",
    cols=40,
    rows=40,
    pitch=2.54,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.9,
    drill_diameter=0.8,
)


def hole(col: int, row: int) -> HoleCoord:
    return HoleCoord(col=col, row=row)


def one_pin_footprint(fp_id: str) -> Footprint:
    return Footprint(
        id=fp_id,
        name=fp_id,
        pins=(FootprintPin(number="1", d_col=0, d_row=0),),
        body_outline=(),
        body_height=0,
        body=BodySpec(archetype="generic-box"),
        lead_diameter=0.5,
        polarized=False,
    )


def two_pin_footprint(fp_id: str, span: int = 3) -> Footprint:
    return Footprint(
        id=fp_id,
        name=fp_id,
        pins=(
            FootprintPin(number="1", d_col=0, d_row=0),
            FootprintPin(number="2", d_col=span, d_row=0),
        ),
        body_outline=(),
        body_height=0,
        body=BodySpec(archetype="generic-box"),
        lead_diameter=0.5,
        polarized=False,
    )


def make_component(
    comp_id: str, ref: str, footprint_id: str, anchor: HoleCoord
) -> ComponentInstance:
    return ComponentInstance(
        id=comp_id, ref=ref, value="", footprint_id=footprint_id, anchor=anchor, locked=False
    )


def solder_trace(cond_id: str, path: tuple[HoleCoord, ...]) -> SolderTraceConductor:
    return SolderTraceConductor(id=cond_id, path=path, buildup="normal", side="bottom")


def net(net_id: str, name: str, net_class: NetClass, refs: tuple[tuple[str, str], ...]) -> Net:
    return Net(
        id=net_id,
        name=name,
        nodes=tuple(NetNode(component_ref=r, pin=p) for r, p in refs),
        net_class=net_class,
    )


def make_doc(
    components: tuple[ComponentInstance, ...] = (),
    conductors: tuple[Conductor, ...] = (),
    nets: tuple[Net, ...] = (),
) -> PerfDocument:
    return PerfDocument(
        meta=DocumentMeta(
            name="test", created="2024-01-01T00:00:00.000Z", modified="2024-01-01T00:00:00.000Z"
        ),
        board=BOARD,
        components=components,
        conductors=conductors,
        nets=nets,
    )


def make_lookup(footprints: tuple[Footprint, ...]) -> FootprintLookup:
    registry = {fp.id: fp for fp in footprints}
    return registry.get


def pin(ref: str, number: str) -> PhysicalPinRef:
    return PhysicalPinRef(component_ref=ref, pin=number)


# A row of four single-pin parts at columns 0, 4, 8, 12 on row 0, all on one net.
FOUR_PIN_LOOKUP = make_lookup((one_pin_footprint("fp1"),))
FOUR_PIN_COMPONENTS = (
    make_component("c1", "R1", "fp1", hole(0, 0)),
    make_component("c2", "R2", "fp1", hole(4, 0)),
    make_component("c3", "R3", "fp1", hole(8, 0)),
    make_component("c4", "R4", "fp1", hole(12, 0)),
)
FOUR_PIN_NET = net(
    "n1", "SIG", "signal", (("R1", "1"), ("R2", "1"), ("R3", "1"), ("R4", "1"))
)


# ---------------------------------------------------------------------------
# Spanning-tree size: the whole point of grouping
# ---------------------------------------------------------------------------


def test_unrouted_four_pin_net_needs_three_links_not_six() -> None:
    """A spanning tree, not the full cross product: n pins need n-1 connections."""
    doc = make_doc(components=FOUR_PIN_COMPONENTS, nets=(FOUR_PIN_NET,))

    nets = ratsnest(doc, FOUR_PIN_LOOKUP)

    assert len(nets) == 1
    assert len(nets[0].links) == 3
    assert nets[0].group_count == 4


def test_routing_two_pins_together_removes_one_link() -> None:
    """The count tracks real progress: joining R1 to R2 leaves two connections."""
    trace = solder_trace("t1", tuple(hole(col, 0) for col in range(0, 5)))
    doc = make_doc(components=FOUR_PIN_COMPONENTS, conductors=(trace,), nets=(FOUR_PIN_NET,))

    nets = ratsnest(doc, FOUR_PIN_LOOKUP)

    assert nets[0].group_count == 3
    assert len(nets[0].links) == 2
    # ...and neither remaining link proposes the pair that is already joined.
    joined = {pin("R1", "1"), pin("R2", "1")}
    assert not any({link.a, link.b} == joined for link in nets[0].links)


def test_fully_routed_net_has_no_links_and_reports_closed() -> None:
    trace = solder_trace("t1", tuple(hole(col, 0) for col in range(0, 13)))
    doc = make_doc(components=FOUR_PIN_COMPONENTS, conductors=(trace,), nets=(FOUR_PIN_NET,))

    nets = ratsnest(doc, FOUR_PIN_LOOKUP)

    assert nets[0].links == ()
    assert nets[0].group_count == 1
    assert summarize(nets).closed_nets == 1


def test_a_nets_own_component_pins_count_as_already_connected() -> None:
    """Two pins of one part are not joined by the part -- but two parts wired end to end
    are, and the ratsnest has to see that through the component rather than only through
    conductors."""
    lookup = make_lookup((two_pin_footprint("fp2"),))
    components = (
        make_component("c1", "R1", "fp2", hole(0, 0)),
        make_component("c2", "R2", "fp2", hole(0, 4)),
    )
    # R1 pin2 (3,0) and R2 pin2 (3,4) wired together.
    wire = WireConductor(id="w1", path=(hole(3, 0), hole(3, 4)), kind="bare-wire", side="bottom")
    nets_decl = (net("n1", "SIG", "signal", (("R1", "2"), ("R2", "2"))),)
    doc = make_doc(components=components, conductors=(wire,), nets=nets_decl)

    assert ratsnest(doc, lookup)[0].links == ()


# ---------------------------------------------------------------------------
# Which crossing gets chosen
# ---------------------------------------------------------------------------


def test_links_connect_nearest_neighbours_rather_than_a_star_from_one_pin() -> None:
    """Prim's over the groups: the chain follows the row, so no link spans the board
    when a shorter crossing exists."""
    doc = make_doc(components=FOUR_PIN_COMPONENTS, nets=(FOUR_PIN_NET,))

    links = ratsnest(doc, FOUR_PIN_LOOKUP)[0].links

    spans = sorted(abs(link.to.col - link.from_.col) for link in links)
    assert spans == [4, 4, 4]


def test_link_length_is_millimetres_not_holes() -> None:
    doc = make_doc(components=FOUR_PIN_COMPONENTS, nets=(FOUR_PIN_NET,))

    link = ratsnest(doc, FOUR_PIN_LOOKUP)[0].links[0]

    assert link.length_mm == 4 * BOARD.pitch


def test_link_carries_the_schematic_net_identity_for_the_router_to_tag_copper_with() -> None:
    doc = make_doc(components=FOUR_PIN_COMPONENTS, nets=(FOUR_PIN_NET,))

    link = ratsnest(doc, FOUR_PIN_LOOKUP)[0].links[0]

    assert (link.net_id, link.net_name, link.net_class) == ("n1", "SIG", "signal")


def test_chooses_the_closest_pin_pair_between_two_multi_pin_groups() -> None:
    """Each group holds two pins; the crossing must be between the two facing ones."""
    lookup = make_lookup((two_pin_footprint("fp2"),))
    components = (
        make_component("c1", "R1", "fp2", hole(0, 0)),   # pins at 0,0 and 3,0
        make_component("c2", "R2", "fp2", hole(10, 0)),  # pins at 10,0 and 13,0
    )
    # Wire each part's own two pins into one group, so both groups have two members.
    conductors = (
        WireConductor(id="w1", path=(hole(0, 0), hole(3, 0)), kind="insulated-wire", side="bottom"),
        WireConductor(
            id="w2", path=(hole(10, 0), hole(13, 0)), kind="insulated-wire", side="bottom"
        ),
    )
    nets_decl = (
        net("n1", "SIG", "signal", (("R1", "1"), ("R1", "2"), ("R2", "1"), ("R2", "2"))),
    )
    doc = make_doc(components=components, conductors=conductors, nets=nets_decl)

    links = ratsnest(doc, lookup)[0].links

    assert len(links) == 1
    # R1 pin 2 (col 3) to R2 pin 1 (col 10) -- the 7-hole gap, not the 13-hole one.
    assert (links[0].a, links[0].b) == (pin("R1", "2"), pin("R2", "1"))


# ---------------------------------------------------------------------------
# Pins that are not on the board
# ---------------------------------------------------------------------------


def test_unplaced_component_pins_are_reported_not_dropped() -> None:
    nets_decl = (net("n1", "SIG", "signal", (("R1", "1"), ("NOPE", "1"))),)
    doc = make_doc(components=(FOUR_PIN_COMPONENTS[0],), nets=nets_decl)

    result = ratsnest(doc, FOUR_PIN_LOOKUP)[0]

    assert result.unresolved_pins == (pin("NOPE", "1"),)
    assert result.links == ()  # One locatable pin: nothing to route yet.
    assert summarize(ratsnest(doc, FOUR_PIN_LOOKUP)).unresolved_pins == 1


def test_unknown_footprint_pins_are_unresolved() -> None:
    components = (make_component("c1", "R1", "missing-fp", hole(0, 0)), FOUR_PIN_COMPONENTS[1])
    nets_decl = (net("n1", "SIG", "signal", (("R1", "1"), ("R2", "1"))),)
    doc = make_doc(components=components, nets=nets_decl)

    result = ratsnest(doc, FOUR_PIN_LOOKUP)[0]

    assert result.unresolved_pins == (pin("R1", "1"),)
    assert result.links == ()


def test_pin_number_the_footprint_does_not_have_is_unresolved() -> None:
    nets_decl = (net("n1", "SIG", "signal", (("R1", "1"), ("R1", "7"))),)
    doc = make_doc(components=(FOUR_PIN_COMPONENTS[0],), nets=nets_decl)

    assert ratsnest(doc, FOUR_PIN_LOOKUP)[0].unresolved_pins == (pin("R1", "7"),)


# ---------------------------------------------------------------------------
# Shape of the result
# ---------------------------------------------------------------------------


def test_closed_nets_are_still_returned_so_totals_can_be_shown() -> None:
    trace = solder_trace("t1", tuple(hole(col, 0) for col in range(0, 13)))
    open_net = net("n2", "OTHER", "signal", (("R1", "1"), ("R4", "1")))
    doc = make_doc(
        components=FOUR_PIN_COMPONENTS, conductors=(trace,), nets=(FOUR_PIN_NET, open_net)
    )

    nets = ratsnest(doc, FOUR_PIN_LOOKUP)

    assert len(nets) == 2
    assert [n.net_id for n in nets] == ["n1", "n2"]  # doc.nets order preserved


def test_summary_totals_add_up() -> None:
    doc = make_doc(components=FOUR_PIN_COMPONENTS, nets=(FOUR_PIN_NET,))

    nets = ratsnest(doc, FOUR_PIN_LOOKUP)
    summary = summarize(nets)

    assert summary.nets == 1
    assert summary.closed_nets == 0
    assert summary.links == 3
    assert summary.total_length_mm == sum(link.length_mm for link in all_links(nets))


def test_deterministic_across_repeated_runs_and_component_reordering() -> None:
    doc = make_doc(components=FOUR_PIN_COMPONENTS, nets=(FOUR_PIN_NET,))
    shuffled = make_doc(components=tuple(reversed(FOUR_PIN_COMPONENTS)), nets=(FOUR_PIN_NET,))

    first = ratsnest(doc, FOUR_PIN_LOOKUP)
    again = ratsnest(doc, FOUR_PIN_LOOKUP)
    reordered = ratsnest(shuffled, FOUR_PIN_LOOKUP)

    assert first == again
    assert first == reordered


def test_a_net_with_no_declared_pins_produces_nothing() -> None:
    doc = make_doc(components=FOUR_PIN_COMPONENTS, nets=(net("n1", "EMPTY", "signal", ()),))

    result = ratsnest(doc, FOUR_PIN_LOOKUP)[0]

    assert (result.links, result.group_count, result.unresolved_pins) == ((), 0, ())
    assert summarize((result,)).closed_nets == 0  # No pins is not "closed".


_BOARDS = sorted((Path(__file__).resolve().parents[1] / "examples").glob("*.perf")) + sorted(
    (Path(__file__).resolve().parents[1] / "tools" / "diffcheck" / "golden").glob("*.perf")
)


@pytest.mark.parametrize("path", _BOARDS, ids=lambda path: path.stem)
def test_one_net_is_what_the_whole_board_says_about_it(path: Path) -> None:
    """The autorouter asks for one net at a time, after every connection it lays. The
    answer has to be the whole-board answer's entry for that net, link for link -- on the
    boards as they are routed and as they are before anything is."""
    doc = persist.deserialize_document(path.read_text(encoding="utf-8")).document
    lookup = footprint_lookup()
    for board in (doc, dataclasses.replace(doc, conductors=())):
        whole = ratsnest(board, lookup)
        assert whole, "a board with no nets would prove nothing"
        for entry in whole:
            assert net_ratsnest(board, lookup, entry.net_id) == entry
    assert net_ratsnest(doc, lookup, "no-such-net") is None


# ---------------------------------------------------------------------------
# The lines the board view draws
# ---------------------------------------------------------------------------


def _ends(line: RatsnestLine) -> set[tuple[int, int]]:
    return {(line.from_.col, line.from_.row), (line.to.col, line.to.row)}


def test_a_line_ends_at_a_wires_free_end_not_at_the_pad_the_wire_reaches() -> None:
    """Sinan's board: a wire ran from C7's pad down to R2's, and its top end was dragged two
    holes off C7. The link still runs pad to pad -- that is where a router starts -- but the
    line drawn points from C7 to the wire's free end, the nearest copper of the net."""
    components = (
        make_component("c1", "R1", "fp1", hole(5, 0)),
        make_component("c2", "R2", "fp1", hole(5, 12)),
    )
    wire = WireConductor(id="w1", path=(hole(5, 2), hole(5, 12)), kind="insulated-wire", side="bottom")
    doc = make_doc(
        components=components,
        conductors=(wire,),
        nets=(net("n1", "RESET", "signal", (("R1", "1"), ("R2", "1"))),),
    )

    (link,) = ratsnest(doc, FOUR_PIN_LOOKUP)[0].links
    (line,) = ratsnest_lines(doc, FOUR_PIN_LOOKUP)

    assert {(link.from_.col, link.from_.row), (link.to.col, link.to.row)} == {(5, 0), (5, 12)}
    assert _ends(line) == {(5, 0), (5, 2)}
    assert line.length_mm == 2 * BOARD.pitch
    assert (line.net_id, line.net_name, line.net_class) == ("n1", "RESET", "signal")


def test_a_line_never_ends_on_a_hole_a_wire_only_lies_over() -> None:
    """A wire touches its two ends; the bend between them is over a hole, not in it."""
    components = (
        make_component("c1", "R1", "fp1", hole(0, 5)),
        make_component("c2", "R2", "fp1", hole(10, 0)),
    )
    wire = WireConductor(
        id="w1", path=(hole(10, 0), hole(10, 5), hole(20, 5)), kind="bare-wire", side="bottom"
    )
    doc = make_doc(
        components=components,
        conductors=(wire,),
        nets=(net("n1", "SIG", "signal", (("R1", "1"), ("R2", "1"))),),
    )

    (line,) = ratsnest_lines(doc, FOUR_PIN_LOOKUP)

    # (10, 5) is 10 holes from R1 and would be nearest, but nothing is soldered there.
    assert _ends(line) == {(0, 5), (10, 0)}


def test_a_line_may_end_anywhere_along_a_solder_run() -> None:
    """A solder trace is soldered at every pad it crosses, so its middle is copper too."""
    components = (
        make_component("c1", "R1", "fp1", hole(5, 3)),
        make_component("c2", "R2", "fp1", hole(10, 0)),
    )
    trace = solder_trace("t1", tuple(hole(col, 0) for col in range(10, 1, -1)))
    doc = make_doc(
        components=components,
        conductors=(trace,),
        nets=(net("n1", "SIG", "signal", (("R1", "1"), ("R2", "1"))),),
    )

    (line,) = ratsnest_lines(doc, FOUR_PIN_LOOKUP)

    assert _ends(line) == {(5, 3), (5, 0)}
    assert line.length_mm == 3 * BOARD.pitch


def test_a_closed_net_draws_no_line() -> None:
    trace = solder_trace("t1", tuple(hole(col, 0) for col in range(0, 13)))
    doc = make_doc(components=FOUR_PIN_COMPONENTS, conductors=(trace,), nets=(FOUR_PIN_NET,))

    assert ratsnest_lines(doc, FOUR_PIN_LOOKUP) == ()


@pytest.mark.parametrize("path", _BOARDS, ids=lambda path: path.stem)
def test_the_board_draws_one_line_per_link_and_with_no_copper_exactly_the_links(
    path: Path,
) -> None:
    """The lines are the links with their ends moved to copper, never more or fewer of them,
    so the "N left" readout and what is drawn agree. With no conductors on the board a
    group's only copper is its pins, and every line is then its link, end for end."""
    doc = persist.deserialize_document(path.read_text(encoding="utf-8")).document
    lookup = footprint_lookup()
    for board, bare in ((doc, False), (dataclasses.replace(doc, conductors=()), True)):
        nets = ratsnest(board, lookup)
        lines = ratsnest_lines(board, lookup)
        assert [line.net_id for line in lines] == [link.net_id for link in all_links(nets)]
        for link, line in zip(all_links(nets), lines, strict=True):
            assert line.length_mm <= link.length_mm + 1e-9
            if bare:
                assert (line.from_, line.to, line.length_mm) == (link.from_, link.to, link.length_mm)


def test_sinans_dragged_wire_on_the_atmega_relay_example() -> None:
    """The board in the report: the RESET wire's C7 end (U8) dragged to U10."""
    path = Path(__file__).resolve().parents[1] / "examples" / "atmega328-relay.perf"
    doc = persist.deserialize_document(path.read_text(encoding="utf-8")).document
    lookup = footprint_lookup()
    conductors = tuple(
        dataclasses.replace(c, path=(hole(c.path[0].col, c.path[0].row + 2), *c.path[1:]))
        if c.id == "cond-30"
        else c
        for c in doc.conductors
    )
    dragged = dataclasses.replace(doc, conductors=conductors)

    (link,) = all_links(ratsnest(dragged, lookup))
    (line,) = ratsnest_lines(dragged, lookup)

    board = dragged.board
    assert {format_hole(link.from_, board), format_hole(link.to, board)} == {"U8", "U21"}
    assert {format_hole(line.from_, board), format_hole(line.to, board)} == {"U8", "U10"}
