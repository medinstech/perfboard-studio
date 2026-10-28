"""A body clearance: parts judged by their real bodies instead of their courtyards (#12).

``PerfDocument.body_clearance_mm`` is unset by default, and then rule 1 and the placer are
exactly what they were -- courtyards, half a pitch round every body and pin. Set, both judge
a pair by ``geometry.bodies_clash``: bodies closer than the clearance, round where the body
is round, or a pin under the other's body. What is pinned here: unset is not written and
changes nothing; the reporter's two TO-92s two rows apart fit at any clearance up to their
1.38 mm gap; a pin under another part's body is still in its way; a can is measured as the
circle it is; the setting survives a save, refuses what is not a clearance, travels with the
design to a new board and is said in Turkish; and the placer and DRC agree on every pair
across the library.
"""

from __future__ import annotations

import dataclasses
import random

import pytest

from perfboard_studio import persist
from perfboard_studio.commands import SetBodyClearancePayload, design_on_a_new_board
from perfboard_studio.drc import _check_component_body_overlap, run_drc
from perfboard_studio.footprints import (
    ROUND_BODY_ARCHETYPES,
    footprint_lookup,
    standard_footprints,
)
from perfboard_studio.geometry import body_gap_mm, is_axis_aligned_box
from perfboard_studio.mcp.session import BoardSession, new_board
from perfboard_studio.model import ComponentInstance, DocumentMeta, HoleCoord, PerfDocument
from perfboard_studio.placer import (
    DEFAULT_PLACEMENT_OPTIONS,
    PlacementOptions,
    PlacementWeights,
    _build_nets,
    _build_parts,
    _build_strips,
    _conflicts_by_part,
    _dead_hole_keys,
    _global_counts,
    _global_delta,
    _initial_state,
    _make_scorer,
    _propose,
    plan_placement,
)

REGISTRY = footprint_lookup()


def _session(*parts: tuple[str, str, str, int]) -> BoardSession:
    session = BoardSession(document=new_board(cols=40, rows=14, name="clearance"))
    for ref, footprint_id, at, rotation in parts:
        assert session.place_component(ref, footprint_id, at, rotation=rotation)["ok"]
    return session


def _to92s() -> BoardSession:
    """The reporter's pair: two TO-92s two rows apart, their bodies 1.38 mm apart."""
    return _session(("Q1", "to92", "C3", 0), ("Q2", "to92", "C5", 0))


def _overlaps(doc: PerfDocument) -> list[str]:
    return [v.message for v in run_drc(doc, REGISTRY) if v.rule == "component-body-overlap"]


def test_unset_is_the_courtyard_rule_and_is_not_written() -> None:
    session = _to92s()
    assert session.document.body_clearance_mm is None
    assert _overlaps(session.document) == [
        "Component Q1 (anchored at C3) and Q2 (anchored at C5) have overlapping body outlines."
    ]
    assert "bodyClearanceMm" not in persist.serialize_document(session.document)
    assert "body_clearance_mm" not in session.get_board_info()


@pytest.mark.parametrize("clearance", [0.0, 0.5, 1.0, 1.37])
def test_the_reporters_to92s_fit_at_any_clearance_up_to_their_gap(clearance: float) -> None:
    session = _to92s()
    assert session.set_body_clearance(clearance)["ok"]
    assert _overlaps(session.document) == []


def test_closer_than_the_clearance_says_how_far_apart_they_are() -> None:
    session = _to92s()
    assert session.set_body_clearance(1.5)["ok"]
    assert _overlaps(session.document) == [
        "Component Q1 (anchored at C3) and Q2 (anchored at C5) are 1.38 mm apart, closer than "
        "the 1.5 mm body clearance this design asks for."
    ]


def test_a_pin_under_another_parts_body_is_still_in_its_way() -> None:
    """What the courtyard's margin round each pin bought, and a body clearance alone would
    drop: a resistor whose lead goes into a hole under a DIP, its own body 0.66 mm clear."""
    session = _session(("U1", "dip-8", "F6", 0), ("R1", "r-axial-5", "H7", 0))
    assert session.set_body_clearance(0.0)["ok"]
    assert _overlaps(session.document) == [
        "Component R1 (anchored at H7) has a pin under the body of U1 (anchored at F6)."
    ]
    # Wider than the bodies' gap, and it is the gap that is reported.
    assert session.set_body_clearance(1.0)["ok"]
    [message] = _overlaps(session.document)
    assert "are 0.66 mm apart" in message


def test_overlapping_bodies_say_so() -> None:
    session = _session(("Q1", "to92", "C3", 0), ("Q2", "to92", "C4", 0))
    assert session.set_body_clearance(0.5)["ok"]
    assert _overlaps(session.document) == [
        "Component Q1 (anchored at C3) and Q2 (anchored at C4) have overlapping bodies."
    ]


def test_a_can_is_measured_as_the_circle_it_is() -> None:
    """A box clipping the corner of an 8 mm can is as far from it as the can really is: the
    diagonal to the circle, not to the circle's box. And the gap is the same either way
    round, to the bit, because the placer asks a pair both ways and DRC one."""
    can = (-4.0, 4.0, -4.0, 4.0)
    corner_box = (4.5, 6.0, 4.5, 6.0)
    boxes_say = body_gap_mm(can, False, corner_box, False)
    assert boxes_say == pytest.approx((0.5**2 * 2) ** 0.5)
    assert body_gap_mm(can, True, corner_box, False) == pytest.approx(4.5 * 2**0.5 - 4.0)
    rng = random.Random(3)
    for _ in range(2000):
        a = sorted(rng.uniform(-9, 9) for _ in range(2))
        b = sorted(rng.uniform(-9, 9) for _ in range(2))
        c = sorted(rng.uniform(-9, 9) for _ in range(2))
        d = sorted(rng.uniform(-9, 9) for _ in range(2))
        box_a = (a[0], a[1], b[0], b[1])
        box_b = (c[0], c[1], d[0], d[1])
        side = rng.uniform(0.5, 6)
        round_box = (c[0], c[0] + side, d[0], d[0] + side)
        for first, first_round, second, second_round in (
            (box_a, False, box_b, False),
            (box_a, False, round_box, True),
            ((a[0], a[0] + side, b[0], b[0] + side), True, round_box, True),
        ):
            assert body_gap_mm(first, first_round, second, second_round) == body_gap_mm(
                second, second_round, first, first_round
            )


def test_the_round_bodies_are_the_round_courtyards() -> None:
    """A document measured by bodies treats as round exactly the parts its courtyard rule
    measured as circles."""
    round_courtyards = {
        fp.body.archetype
        for fp in standard_footprints().values()
        if not is_axis_aligned_box(fp.body_outline)
    }
    assert round_courtyards == ROUND_BODY_ARCHETYPES


def test_a_clearance_is_saved_beside_the_height_limit_and_read_back() -> None:
    session = _to92s()
    assert session.set_height_limit(20.0)["ok"]
    assert session.set_body_clearance(0.5)["ok"]
    text = persist.serialize_document(session.document)
    assert '"heightLimitMm": 20,\n  "bodyClearanceMm": 0.5,' in text
    assert persist.parse_document_or_throw(text).body_clearance_mm == 0.5
    assert session.get_board_info()["body_clearance_mm"] == 0.5


@pytest.mark.parametrize("written", ["-1", "2.54", "40"])
def test_a_hand_edited_clearance_out_of_range_is_dropped_with_a_warning(written: str) -> None:
    session = _to92s()
    assert session.set_body_clearance(0.5)["ok"]
    text = persist.serialize_document(session.document).replace(
        '"bodyClearanceMm": 0.5', f'"bodyClearanceMm": {written}'
    )
    loaded = persist.deserialize_document(text)
    assert loaded.ok
    assert loaded.document.body_clearance_mm is None
    assert any("bodyClearanceMm" in warning for warning in loaded.warnings)


@pytest.mark.parametrize("value", [-0.1, 2.54, 3.0, float("nan"), "1", True])
def test_the_command_refuses_what_is_not_a_clearance(value: object) -> None:
    session = _to92s()
    result = session.bus.dispatch(
        "body-clearance.set", SetBodyClearancePayload(body_clearance_mm=value)  # type: ignore[arg-type]
    )
    assert not result.ok and result.code == "invalid-body-clearance"
    assert session.document.body_clearance_mm is None


def test_setting_and_clearing_it_are_each_one_undo_step() -> None:
    session = _to92s()
    bus = session.bus
    assert bus.dispatch("body-clearance.set", SetBodyClearancePayload(body_clearance_mm=0.5)).ok
    assert bus.dispatch("body-clearance.set", SetBodyClearancePayload(body_clearance_mm=None)).ok
    assert bus.document.body_clearance_mm is None
    bus.undo()
    assert bus.document.body_clearance_mm == 0.5
    bus.undo()
    assert bus.document.body_clearance_mm is None


def test_it_goes_with_the_design_to_a_new_board() -> None:
    """A rule about how this build is laid out, like the height limit -- not the stock."""
    session = _to92s()
    assert session.set_body_clearance(0.5)["ok"]
    moved = design_on_a_new_board(session.document, DocumentMeta(name="next", created="", modified=""))
    assert moved.body_clearance_mm == 0.5


def test_choosing_a_board_again_keeps_it() -> None:
    """Why it is on the document and not the board: Board Setup's products and every
    boardfit trial go through ``board.applyPreset``, which would have dropped a board field."""
    from perfboard_studio.commands import document_on_preset
    from perfboard_studio.geometry import STANDARD_PRESETS, board_from_preset

    session = _to92s()
    assert session.set_body_clearance(0.5)["ok"]
    for preset in STANDARD_PRESETS:
        board = board_from_preset(preset, session.document.board)
        assert document_on_preset(session.document, preset, board).body_clearance_mm == 0.5


def test_the_placer_names_the_same_parts_in_conflict() -> None:
    """``_conflicts_by_part``, which the window marks parts by, asks the same predicate."""
    session = _to92s()
    assert session.set_body_clearance(1.0)["ok"]
    assert _conflicts_by_part(session.document, REGISTRY) == {}
    assert session.set_body_clearance(1.5)["ok"]
    conflicts = _conflicts_by_part(session.document, REGISTRY)
    assert set(conflicts) == {c.id for c in session.document.components}


# ---------------------------------------------------------------------------
# The placer and DRC: one predicate
# ---------------------------------------------------------------------------

#: Four parts the probe is walked past: a DIP (a body with pins under nobody else's), a can
#: (round), a header (a courtyard that is its moulding) and a TO-92 (the reporter's).
_PARTNERS = (
    ("U1", "dip-8", HoleCoord(2, 3), 0),
    ("C1", "c-elec-d8-p3", HoleCoord(11, 5), 0),
    ("J1", "hdr-1x4", HoleCoord(20, 5), 0),
    ("Q1", "to92", HoleCoord(29, 5), 0),
)


def _part(ref: str, footprint_id: str, at: HoleCoord, rotation: int, mirrored: bool = False) -> ComponentInstance:
    return ComponentInstance(
        id=f"c-{ref}", ref=ref, value="", footprint_id=footprint_id, anchor=at,
        rotation=rotation, mirrored=mirrored,  # type: ignore[arg-type]
    )


def _scorer_for(doc: PerfDocument):
    parts = _build_parts(doc, REGISTRY)
    nets, nets_of, pin_nets = _build_nets(doc, parts)
    strips = _build_strips(doc, parts, pin_nets)
    state = _initial_state(doc, parts, strips)
    scorer = _make_scorer(
        doc.board, PlacementWeights(), nets, nets_of, strips, _dead_hole_keys(doc),
        doc.mounting_holes, doc.body_clearance_mm,
    )
    return state, scorer


@pytest.mark.parametrize("mirrored", (False, True))
@pytest.mark.parametrize("clearance", (0.0, 1.0))
def test_the_placer_and_drc_agree_on_every_body_at_a_clearance(
    clearance: float, mirrored: bool
) -> None:
    """Every registry footprint, at every rotation, walked along a row past a DIP, a can, a
    header and a TO-92: the placer's count of pairs in each other's way must be rule 1's
    count of findings, every time. Both build the same boxes and pins and ask
    ``geometry.bodies_clash``; this is what would notice one of them growing a second
    opinion -- or the placer's gate skipping a pair the predicate would have named."""
    blank = new_board(cols=40, rows=14, name="walk")
    partners = tuple(_part(ref, fid, at, rot) for ref, fid, at, rot in _PARTNERS)
    checked = clashing = 0
    for footprint_id in sorted(standard_footprints()):
        probe = _part("X1", footprint_id, HoleCoord(0, 7), 0, mirrored)
        doc = dataclasses.replace(blank, components=(*partners, probe), body_clearance_mm=clearance)
        state, scorer = _scorer_for(doc)
        position = len(state.parts) - 1
        for rot in range(4):
            for col in range(0, 37, 2):
                state.set_placement(position, col, 7, rot)
                moved = dataclasses.replace(probe, anchor=HoleCoord(col, 7), rotation=rot * 90)  # type: ignore[arg-type]
                placed = dataclasses.replace(doc, components=(*partners, moved))
                placer_count = scorer.full(state).overlap_pairs
                drc_count = len(_check_component_body_overlap(placed, REGISTRY))
                assert placer_count == drc_count, (footprint_id, rot, col)
                checked += 1
                clashing += drc_count > 0
    assert 0 < clashing < checked


def test_local_delta_matches_a_full_recompute_with_a_clearance() -> None:
    """The load-bearing local-delta test, on an example board measured by bodies, where the
    gate ``local`` skips pairs by is not the courtyard."""
    doc = persist.deserialize_document(
        (persist_path := _example("atmega328-relay")).read_text(encoding="utf-8")
    ).document
    assert persist_path.exists()
    doc = dataclasses.replace(doc, body_clearance_mm=0.5)
    weights = PlacementWeights()
    state, scorer = _scorer_for(doc)
    movable = [p for p, part in enumerate(state.parts) if part.movable]
    rng = random.Random(55)
    checked = 0
    for _ in range(500):
        proposal = _propose(rng, state, movable, 4, DEFAULT_PLACEMENT_OPTIONS)
        if proposal is None:
            continue
        positions, placements = proposal
        full_before = scorer.full(state).total(weights)
        local_before = scorer.local(state, positions)
        global_before = _global_counts(state)
        snapshot = tuple((state.col[p], state.row[p], state.rot[p]) for p in positions)
        for position, (col, row, rot) in zip(positions, placements, strict=True):
            state.set_placement(position, col, row, rot)
        tracked = (scorer.local(state, positions) - local_before) + _global_delta(
            state, global_before, weights
        )
        assert tracked == pytest.approx(scorer.full(state).total(weights) - full_before, abs=1e-9)
        for position, (col, row, rot) in zip(positions, snapshot, strict=True):
            state.set_placement(position, col, row, rot)
        checked += 1
    assert checked > 250


def _example(name: str):
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "examples" / f"{name}.perf"


def test_a_placement_with_a_clearance_is_one_drc_calls_legal() -> None:
    """The seam: plan_placement builds its scorer from the document, so a clearance set on
    the document is the one the placer packs to and the one DRC then checks."""
    doc = persist.deserialize_document(_example("lm317-supply").read_text(encoding="utf-8")).document
    doc = dataclasses.replace(doc, body_clearance_mm=0.3)
    plan = plan_placement(doc, REGISTRY, PlacementOptions(seed=0, restarts=1, score_with_router=False))
    assert plan.after.is_legal
    assert _overlaps(plan.document) == []


# ---------------------------------------------------------------------------
# What a Turkish window says
# ---------------------------------------------------------------------------


@pytest.fixture
def turkish():
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        yield
    finally:
        set_language(before)


def test_the_three_findings_are_said_in_turkish(turkish: None) -> None:
    from perfboard_studio.ui.engine_text import say_finding

    said = []
    session = _to92s()
    assert session.set_body_clearance(1.5)["ok"]
    said += [say_finding(m) for m in _overlaps(session.document)]
    session = _session(("Q1", "to92", "C3", 0), ("Q2", "to92", "C4", 0))
    assert session.set_body_clearance(0.5)["ok"]
    said += [say_finding(m) for m in _overlaps(session.document)]
    session = _session(("U1", "dip-8", "F6", 0), ("R1", "r-axial-5", "H7", 0))
    assert session.set_body_clearance(0.0)["ok"]
    said += [say_finding(m) for m in _overlaps(session.document)]
    assert said == [
        "Q1 (C3 deliğinde) ile Q2 (C5 deliğinde) arasında 1.38 mm var; bu tasarımın istediği "
        "1.5 mm gövde aralığından az.",
        "Q1 (C3 deliğinde) ile Q2 (C4 deliğinde) parçalarının gövdeleri üst üste biniyor.",
        "R1 parçasının (H7 deliğinde) bir bacağı U1 parçasının (F6 deliğinde) gövdesinin "
        "altında kalıyor.",
    ]


def test_the_undo_steps_are_said_in_turkish(turkish: None) -> None:
    from perfboard_studio.ui.engine_text import say

    bus = _to92s().bus
    results = [
        bus.dispatch("body-clearance.set", SetBodyClearancePayload(body_clearance_mm=value))
        for value in (0.5, None)
    ]
    assert [say(result.description) for result in results] == [
        "Parçaları gövdelerine göre ölç (0.5 mm aralık)",
        "Parçaları güvenlik paylarına göre ölç",
    ]
