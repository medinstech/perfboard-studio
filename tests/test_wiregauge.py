"""A wire's gauge: what it is, what it carries, and that DRC, the router and the guide agree.

``wiregauge.py`` exists so the three of them answer from one function. These tests pin the
arithmetic, then pin each consumer to it: DRC's ``current-capacity`` rule measuring a wire,
``wire-too-thick-for-hole``, the router writing the gauge for a net that declares a current,
and the cut list printing the gauge the document holds.
"""

from __future__ import annotations

import dataclasses

import pytest

from perfboard_studio.drc import DEFAULT_DRC_OPTIONS, DrcViolation, run_drc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.guide import build_guide
from perfboard_studio.mcp.session import BoardSession
from perfboard_studio.model import (
    Board,
    DocumentMeta,
    HoleCoord,
    Net,
    PerfDocument,
    WireConductor,
)
from perfboard_studio.wiregauge import (
    AWG_BY_CURRENT,
    HEAVIEST_AWG,
    STOCKED_AWG,
    awg_area_mm2,
    awg_diameter_mm,
    cut_gauge_awg,
    fits_hole,
    minimum_awg_for_current,
    wire_capacity_a,
    wire_gauge_for_current,
)

LOOKUP = footprint_lookup()


def hole(col: int, row: int) -> HoleCoord:
    return HoleCoord(col=col, row=row)


BOARD = Board(
    type="pad-per-hole",
    cols=30,
    rows=20,
    pitch=2.54,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.9,
    drill_diameter=1.0,
)


def doc_with_wire(
    *,
    current_a: float | None,
    gauge_awg: int | None,
    kind: str = "insulated-wire",
    board: Board = BOARD,
) -> PerfDocument:
    net = Net(id="n1", name="MOTOR", nodes=(), net_class="power", current_a=current_a)
    wire = WireConductor(
        id="w1",
        path=(hole(2, 2), hole(12, 2)),
        kind=kind,  # type: ignore[arg-type]
        side="top" if kind == "top-jumper" else "bottom",
        gauge_awg=gauge_awg,
        net_id="n1",
    )
    return PerfDocument(
        meta=DocumentMeta(
            name="t", created="2024-01-01T00:00:00.000Z", modified="2024-01-01T00:00:00.000Z"
        ),
        board=board,
        components=(),
        conductors=(wire,),
        nets=(net,),
    )


def findings(doc: PerfDocument, rule: str) -> list[DrcViolation]:
    return [v for v in run_drc(doc, LOOKUP) if v.rule == rule]


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("awg", "diameter_mm"),
    # The AWG definition's own values, as every wire table prints them.
    [(10, 2.588), (14, 1.628), (18, 1.024), (20, 0.812), (22, 0.644), (24, 0.511), (30, 0.255)],
)
def test_a_gauge_is_the_diameter_the_awg_definition_gives(awg: int, diameter_mm: float) -> None:
    assert awg_diameter_mm(awg) == pytest.approx(diameter_mm, abs=0.001)


def test_the_area_is_the_circle_of_that_diameter() -> None:
    assert awg_area_mm2(18) == pytest.approx(0.823, abs=0.001)


def test_the_guide_prints_what_it_always_printed_below_the_point_the_table_runs_out() -> None:
    """The old table was the answer to "which gauge" for every board that existed before a
    wire could be measured, and it is still the answer wherever it is enough."""
    for current, expected in [
        (None, 24),
        (0.0, 24),
        (1.49, 24),
        (1.5, 22),
        (2.99, 22),
        (3.0, 20),
        (4.99, 20),
        (5.0, 18),
        (8.0, 18),
    ]:
        assert wire_gauge_for_current(current) == expected, current


def test_past_the_table_the_current_chooses_a_heavier_wire_instead_of_stopping_at_awg_18() -> None:
    # 14 A is what three maxon drives at 4.43 A nominal draw; the table said AWG 18 for it.
    assert wire_gauge_for_current(9.0) == 16
    assert wire_gauge_for_current(14.0) == 14
    assert wire_gauge_for_current(30.0) == 12
    assert wire_gauge_for_current(45.0) == 10


def test_every_gauge_the_guide_can_choose_is_one_drc_accepts() -> None:
    """The whole point of one module: the cut list must never name a wire the rule rejects."""
    top = wire_capacity_a(HEAVIEST_AWG)
    current = 0.05
    while current <= top:
        assert wire_capacity_a(wire_gauge_for_current(current)) >= current, current
        current += 0.05


def test_every_row_of_the_comfortable_table_is_inside_the_capacity_it_is_measured_against() -> None:
    thresholds = [threshold for threshold, _gauge in AWG_BY_CURRENT]
    for (_threshold, gauge), upper in zip(AWG_BY_CURRENT[1:], thresholds[:-1], strict=True):
        # A row applies up to the next row's threshold.
        assert wire_capacity_a(gauge) >= upper, gauge


def test_a_current_no_stocked_wire_carries_has_no_minimum_gauge() -> None:
    assert minimum_awg_for_current(wire_capacity_a(HEAVIEST_AWG) + 1) is None
    # ...and the guide still names the heaviest, for DRC to report as too thin.
    assert wire_gauge_for_current(100.0) == HEAVIEST_AWG


def test_only_stocked_gauges_are_ever_chosen() -> None:
    for current in (0.1, 2.0, 4.0, 7.0, 11.0, 19.0, 33.0, 60.0):
        assert wire_gauge_for_current(current) in STOCKED_AWG


def test_the_gauge_the_document_names_wins_over_the_one_the_current_would_choose() -> None:
    assert cut_gauge_awg(30, 14.0) == 30
    assert cut_gauge_awg(None, 14.0) == 14
    assert cut_gauge_awg(None, None) == 24


def test_awg_18_does_not_go_through_a_one_millimetre_hole_and_awg_20_does() -> None:
    assert not fits_hole(18, 1.0)
    assert fits_hole(20, 1.0)
    assert fits_hole(18, 1.2)


# ---------------------------------------------------------------------------
# DRC rule 9 on a wire
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["insulated-wire", "bare-wire", "top-jumper"])
def test_a_wire_too_thin_for_its_nets_current_is_reported(kind: str) -> None:
    found = findings(doc_with_wire(current_a=14.0, gauge_awg=24, kind=kind), "current-capacity")
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert found[0].conductor_ids == ("w1",)
    message = found[0].message
    assert "AWG 24" in message
    assert "Use AWG 14 or heavier" in message
    # AWG 14 is 1.63 mm and this board is drilled 1.0 mm, which the advice has to say.
    assert "will not go through" in message


def test_a_wire_heavy_enough_for_its_nets_current_passes() -> None:
    assert findings(doc_with_wire(current_a=14.0, gauge_awg=14), "current-capacity") == []


def test_a_wire_on_a_net_that_declares_no_current_is_not_measured() -> None:
    assert findings(doc_with_wire(current_a=None, gauge_awg=30), "current-capacity") == []


def test_a_wire_with_no_stored_gauge_is_measured_at_the_gauge_the_cut_list_will_print() -> None:
    # 4 A with no gauge stored: the guide cuts AWG 20, which carries it.
    assert findings(doc_with_wire(current_a=4.0, gauge_awg=None), "current-capacity") == []
    # 60 A: the heaviest gauge this tool names does not carry it, and that is said.
    found = findings(doc_with_wire(current_a=60.0, gauge_awg=None), "current-capacity")
    assert len(found) == 1
    assert f"AWG {HEAVIEST_AWG}" in found[0].message
    assert "No hookup wire" in found[0].message


def test_the_wire_density_is_an_option_like_the_solder_one() -> None:
    doc = doc_with_wire(current_a=2.5, gauge_awg=22)
    assert findings(doc, "current-capacity") == []
    strict = dataclasses.replace(DEFAULT_DRC_OPTIONS, max_wire_current_density_a_per_mm2=5.0)
    assert [v for v in run_drc(doc, LOOKUP, strict) if v.rule == "current-capacity"] != []


# ---------------------------------------------------------------------------
# wire-too-thick-for-hole
# ---------------------------------------------------------------------------


def test_a_stored_gauge_wider_than_the_drill_is_reported() -> None:
    found = findings(doc_with_wire(current_a=None, gauge_awg=18), "wire-too-thick-for-hole")
    assert len(found) == 1
    assert found[0].holes == (hole(2, 2), hole(12, 2))
    assert "1.02 mm" in found[0].message and "1 mm" in found[0].message


def test_the_same_wire_fits_a_board_drilled_wider() -> None:
    wide = dataclasses.replace(BOARD, drill_diameter=1.2, pad_diameter=2.2)
    doc = doc_with_wire(current_a=None, gauge_awg=18, board=wide)
    assert findings(doc, "wire-too-thick-for-hole") == []


def test_a_gauge_chosen_by_the_current_is_checked_too_and_says_where_it_came_from() -> None:
    found = findings(doc_with_wire(current_a=14.0, gauge_awg=None), "wire-too-thick-for-hole")
    assert len(found) == 1
    assert "AWG 14 (the gauge the cut list names for 14.0 A)" in found[0].message


def test_an_ordinary_signal_wire_raises_nothing() -> None:
    assert findings(doc_with_wire(current_a=None, gauge_awg=None), "wire-too-thick-for-hole") == []
    assert findings(doc_with_wire(current_a=0.9, gauge_awg=None), "wire-too-thick-for-hole") == []


# ---------------------------------------------------------------------------
# The router writes the gauge; the guide prints the one the document holds
# ---------------------------------------------------------------------------


def _two_headers(current_a: float | None) -> BoardSession:
    session = BoardSession()
    session.set_board(cols=24, rows=12)
    session.add_part("J1", "screw-terminal-2")
    session.add_part("J2", "screw-terminal-2")
    session.create_net("MOTOR", "power", ["J1.1", "J2.1"], current_a=current_a)
    session.create_net("GND", "ground", ["J1.2", "J2.2"])
    session.place_parts([{"ref": "J1", "at": "B3"}, {"ref": "J2", "at": "S3"}])
    return session


def _wires(session: BoardSession, net_name: str) -> list[WireConductor]:
    net_id = next(net.id for net in session.document.nets if net.name == net_name)
    return [
        c
        for c in session.document.conductors
        if isinstance(c, WireConductor) and c.net_id == net_id
    ]


def test_the_router_writes_the_gauge_for_a_net_that_declares_a_current() -> None:
    session = _two_headers(current_a=14.0)
    result = session.autoroute(style="wire")
    assert result["ok"] and result["unrouted"] == 0
    motor = _wires(session, "MOTOR")
    assert motor, "the wire style should have laid at least one wire"
    assert {w.gauge_awg for w in motor} == {14}
    # The net that declares nothing is left exactly as it always was.
    assert {w.gauge_awg for w in _wires(session, "GND")} <= {None}


def test_a_net_outgrowing_the_gauge_it_was_routed_with_is_caught() -> None:
    session = _two_headers(current_a=0.9)
    session.autoroute(style="wire")
    assert {w.gauge_awg for w in _wires(session, "MOTOR")} == {24}
    assert [v for v in session.run_drc()["violations"] if v["rule"] == "current-capacity"] == []

    session.update_net("MOTOR", current_a=14.0)
    capacity = [v for v in session.run_drc()["violations"] if v["rule"] == "current-capacity"]
    assert capacity and all("AWG 24" in v["message"] for v in capacity)


def test_the_cut_list_prints_the_stored_gauge_and_says_when_it_will_not_go_through() -> None:
    guide = build_guide(doc_with_wire(current_a=None, gauge_awg=18), LOOKUP)
    (cut,) = guide.cut_list
    assert cut.awg == 18
    step = next(
        s
        for phase in guide.phases
        for s in phase.steps
        if getattr(s, "conductor_id", None) == "w1"
    )
    assert any("will not go" in note and "1 mm holes" in note for note in step.notes)


def test_the_cut_list_names_a_heavier_wire_for_a_heavy_current() -> None:
    guide = build_guide(doc_with_wire(current_a=14.0, gauge_awg=None), LOOKUP)
    assert [cut.awg for cut in guide.cut_list] == [14]


def test_a_stripboard_link_carries_the_gauge_too() -> None:
    session = BoardSession()
    session.set_board(cols=24, rows=12, board_type="stripboard", strip_axis="horizontal")
    session.add_part("J1", "screw-terminal-2")
    session.add_part("J2", "screw-terminal-2")
    session.create_net("MOTOR", "power", ["J1.1", "J2.1"], current_a=14.0)
    session.create_net("GND", "ground", ["J1.2", "J2.2"])
    session.place_parts([{"ref": "J1", "at": "B3"}, {"ref": "J2", "at": "S7"}])
    assert session.autoroute()["ok"]
    assert {w.gauge_awg for w in _wires(session, "MOTOR")} == {14}
    assert {w.gauge_awg for w in _wires(session, "GND")} == {None}
