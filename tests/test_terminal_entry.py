"""Which way a screw terminal's wires go in, and everything that now knows.

A terminal's wire enters through ONE long face, and until this existed the application drew
it as a box centred on its pins: nothing could tell a terminal whose mouth faced the board's
edge from one whose mouth was pressed against a capacitor. One fact now says which face it
is (``footprints.wire_entry`` / ``entry_corridor``), and four consumers read it -- DRC's
``terminal-entry-blocked``, the placer's two terms, the guide's orientation note and both
renderers. These tests pin the fact against the 3D mesh it was measured from, and pin every
consumer against the same fact, because a checker and an optimiser that disagree about which
way a part faces are worse than neither.
"""

from __future__ import annotations

import dataclasses
import random
from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.drc import DrcViolation, run_drc
from perfboard_studio.footprints import (
    WIRE_ENTRY_CLEARANCE_MM,
    body_extent,
    entry_corridor,
    footprint_lookup,
    get_footprint,
    standard_footprints,
    wire_entry,
)
from perfboard_studio.geometry import entry_side
from perfboard_studio.guide import build_guide
from perfboard_studio.model import (
    Board,
    ComponentInstance,
    DocumentMeta,
    HoleCoord,
    Net,
    NetNode,
    PerfDocument,
)
from perfboard_studio.placer import (
    DEFAULT_PLACEMENT_OPTIONS,
    ArrangeRequest,
    PlacementOptions,
    PlacementWeights,
    _build_nets,
    _build_parts,
    _build_strips,
    _dead_hole_keys,
    _global_counts,
    _global_delta,
    _initial_state,
    _make_scorer,
    _propose,
    arrange,
    describe,
    plan_placement,
)

REGISTRY: FootprintLookup = footprint_lookup()
ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "tools" / "diffcheck" / "golden"
MODELS_DIR = ROOT / "src" / "perfboard_studio" / "ui" / "models"

BOARD = Board(
    type="pad-per-hole",
    cols=40,
    rows=30,
    pitch=2.54,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.9,
    drill_diameter=1.0,
)


def part(
    ref: str, footprint_id: str, col: int, row: int, rotation: int = 0, mirrored: bool = False
) -> ComponentInstance:
    return ComponentInstance(
        id=f"cmp-{ref}",
        ref=ref,
        value="",
        footprint_id=footprint_id,
        anchor=HoleCoord(col, row),
        rotation=rotation,  # type: ignore[arg-type]
        mirrored=mirrored,
    )


def doc_of(*components: ComponentInstance, nets: tuple[Net, ...] = (), board: Board = BOARD) -> PerfDocument:
    return PerfDocument(
        meta=DocumentMeta(name="entry", created="", modified=""),
        board=board,
        components=components,
        nets=nets,
    )


def findings(doc: PerfDocument) -> list[DrcViolation]:
    return [v for v in run_drc(doc, REGISTRY) if v.rule == "terminal-entry-blocked"]


def _scorer_for(doc: PerfDocument, weights: PlacementWeights):
    parts = _build_parts(doc, REGISTRY)
    nets, nets_of, pin_nets = _build_nets(doc, parts)
    strips = _build_strips(doc, parts, pin_nets)
    state = _initial_state(doc, parts, strips)
    scorer = _make_scorer(doc.board, weights, nets, nets_of, strips, _dead_hole_keys(doc))
    return state, scorer


# ---------------------------------------------------------------------------
# The fact, and where it was measured
# ---------------------------------------------------------------------------


def test_only_a_screw_terminal_has_a_wire_entry() -> None:
    for footprint_id, footprint in standard_footprints().items():
        expected = (0, 1) if footprint.body.archetype == "screw-terminal" else None
        assert wire_entry(footprint) == expected, footprint_id
    # A terminal the registry does not ship is the same package, and faces the same way.
    generated = get_footprint("screw-terminal-6")
    assert generated is not None and wire_entry(generated) == (0, 1)


@pytest.mark.parametrize("ways", (2, 3))
def test_the_entry_is_the_face_the_borrowed_mesh_has_its_openings_on(ways: int) -> None:
    """The convention is MEASURED from the mesh both terminals are drawn with, and this is
    the measurement. The mouth of a Phoenix MKDS block is a row of openings a few tenths of
    a millimetre behind one face, at the wire channel's height; the other face is a plain
    step. In the model's frame that face is -y, and a model's y runs against the row, so it
    is this frame's +y -- which is what ``wire_entry`` says. A different mesh with its mouth
    the other way would fail here before it drew a terminal backwards."""
    vtk = pytest.importorskip("vtk")
    reader = vtk.vtkPLYReader()
    reader.SetFileName(str(MODELS_DIR / f"screw-terminal-{ways}.0.ply"))
    reader.Update()
    mesh = reader.GetOutput()
    points = [mesh.GetPoint(index) for index in range(mesh.GetNumberOfPoints())]
    front = min(point[1] for point in points)
    back = max(point[1] for point in points)

    def recessed(face_distance) -> int:
        return sum(1 for x, y, z in points if 2.0 < z < 6.0 and 0.2 < face_distance(y) < 1.0)

    behind_minus_y = recessed(lambda y: y - front)
    behind_plus_y = recessed(lambda y: back - y)
    assert behind_minus_y > 40 and behind_plus_y == 0
    assert get_footprint(f"screw-terminal-{ways}") is not None
    assert wire_entry(get_footprint(f"screw-terminal-{ways}")) == (0, 1)  # type: ignore[arg-type]


def test_the_corridor_stands_in_front_of_the_face_as_wide_as_the_body() -> None:
    footprint = get_footprint("screw-terminal-2")
    assert footprint is not None
    min_x, max_x, _min_y, max_y = body_extent(footprint, 2.54).box
    assert entry_corridor(footprint, 2.54) == (
        min_x,
        max_x,
        max_y,
        max_y + WIRE_ENTRY_CLEARANCE_MM,
    )
    resistor = get_footprint("r-axial-3")
    assert resistor is not None and entry_corridor(resistor, 2.54) is None


# ---------------------------------------------------------------------------
# DRC
# ---------------------------------------------------------------------------

#: Where a resistor lies to be squarely in front of, beside, and behind a 2-way terminal
#: anchored at (20, 15) and facing the way ``rotation`` turns it: offsets in holes, turned
#: with the terminal, from its body centre.
_FRONT, _BESIDE, _BEHIND = (0, 3), (-5, 0), (0, -3)


def _around(rotation: int, mirrored: bool, offset: tuple[int, int]) -> ComponentInstance:
    """A short resistor at ``offset`` from the terminal's middle, turned with it."""
    from perfboard_studio.geometry import transform_offset

    dx, dy = transform_offset(offset[0] + 1, offset[1], rotation, mirrored)  # the middle of 2 ways
    # r-axial-3 spans 3 holes; stand it across the offset so its body straddles the point.
    return part("R1", "r-axial-3", 20 + int(dx) - 1, 15 + int(dy))


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
@pytest.mark.parametrize("mirrored", (False, True))
def test_a_part_in_front_of_the_entry_is_reported_and_one_beside_or_behind_is_not(
    rotation: int, mirrored: bool
) -> None:
    terminal = part("J1", "screw-terminal-2", 20, 15, rotation, mirrored)
    footprint = get_footprint("screw-terminal-2")
    assert footprint is not None
    from perfboard_studio.geometry import transform_offset

    facing = entry_side(transform_offset(0, 1, rotation, mirrored))  # type: ignore[arg-type]

    blocked = findings(doc_of(terminal, _around(rotation, mirrored, _FRONT)))
    assert len(blocked) == 1
    assert blocked[0].severity == "warning"
    assert blocked[0].component_ids == ("cmp-J1", "cmp-R1")
    assert f"takes its wires in from the {facing}" in blocked[0].message

    assert findings(doc_of(terminal, _around(rotation, mirrored, _BESIDE))) == []
    assert findings(doc_of(terminal, _around(rotation, mirrored, _BEHIND))) == []


def test_a_terminal_facing_out_of_the_board_has_nothing_in_front_of_it() -> None:
    """Mouth over the bottom edge, a crowd behind it: clear, because what is behind a mouth
    is not in the wire's way."""
    terminal = part("J1", "screw-terminal-3", 10, BOARD.rows - 1)
    crowd = tuple(part(f"R{i}", "r-axial-3", 8 + 4 * i, BOARD.rows - 5) for i in range(3))
    assert findings(doc_of(terminal, *crowd)) == []


def test_a_part_just_past_the_corridor_is_clear() -> None:
    """Eight millimetres, and not a hair more: a resistor whose body starts beyond the
    corridor's depth is not in front of the mouth."""
    terminal = part("J1", "screw-terminal-2", 20, 10)
    footprint = get_footprint("screw-terminal-2")
    assert footprint is not None
    face = body_extent(footprint, 2.54).box[3]  # the mouth's face, below the pins
    rows_clear = 1
    while True:
        # r-axial-3's body is 2.5 mm thick, centred on its row.
        if rows_clear * 2.54 - 1.25 >= face + WIRE_ENTRY_CLEARANCE_MM:
            break
        rows_clear += 1
    assert findings(doc_of(terminal, part("R1", "r-axial-3", 20, 10 + rows_clear))) == []
    assert len(findings(doc_of(terminal, part("R1", "r-axial-3", 20, 10 + rows_clear - 1)))) == 1


def test_one_finding_names_every_part_in_the_way() -> None:
    terminal = part("J1", "screw-terminal-6", 10, 10)
    doc = doc_of(
        terminal,
        part("R1", "r-axial-3", 10, 13),
        part("R2", "r-axial-3", 18, 13),
        part("C1", "c-disc-p2", 15, 14),
    )
    found = findings(doc)
    assert len(found) == 1
    assert found[0].component_ids == ("cmp-J1", "cmp-C1", "cmp-R1", "cmp-R2")
    assert "C1, R1, R2 stand in front" in found[0].message


def test_a_terminal_with_a_pin_off_the_board_is_left_to_rule_2() -> None:
    doc = doc_of(part("J1", "screw-terminal-2", BOARD.cols - 1, 5), part("R1", "r-axial-3", 36, 8))
    assert any(v.rule == "component-off-board" for v in run_drc(doc, REGISTRY))
    assert findings(doc) == []


def test_the_entry_rule_fires_on_no_golden_fixture() -> None:
    """Why it can sit in PYTHON_ONLY_RULES without changing a single comparison: no fixture
    carries a screw terminal."""
    for path in sorted(GOLDEN_DIR.glob("*.perf")):
        result = persist.deserialize_document(path.read_text(encoding="utf-8"))
        assert result.ok
        assert findings(result.document) == [], path.name


# ---------------------------------------------------------------------------
# The placer
# ---------------------------------------------------------------------------


def test_the_placer_counts_the_pairs_drc_names() -> None:
    """One fact, two consumers: over a few hundred random boards, the placer's count of
    (terminal, obstacle) pairs is the number of obstacles DRC's findings name. Mirrored and
    turned terminals included, and more than one terminal, so a pair of terminals facing
    each other is counted from both sides."""
    rng = random.Random(1234)
    checked = blocked_total = 0
    for _ in range(300):
        components = [
            part(
                f"J{i}",
                rng.choice(("screw-terminal-2", "screw-terminal-3")),
                rng.randrange(2, BOARD.cols - 6),
                rng.randrange(2, BOARD.rows - 4),
                rng.choice((0, 90, 180, 270)),
                rng.random() < 0.3,
            )
            for i in range(2)
        ] + [
            part(f"R{i}", "r-axial-3", rng.randrange(1, BOARD.cols - 4), rng.randrange(1, BOARD.rows - 2),
                 rng.choice((0, 90)))
            for i in range(5)
        ]
        doc = doc_of(*components)
        state, scorer = _scorer_for(doc, PlacementWeights())
        placer_pairs = scorer.full(state).entry_blocked
        drc_pairs = sum(len(v.component_ids) - 1 for v in findings(doc))
        assert placer_pairs == drc_pairs
        checked += 1
        blocked_total += drc_pairs
    assert checked == 300 and blocked_total > 0


def test_local_delta_matches_a_full_recompute_with_live_entries() -> None:
    """The annealer's incremental arithmetic, on a board where both entry terms move with
    nearly every proposal."""
    weights = PlacementWeights()
    doc = doc_of(
        part("J1", "screw-terminal-3", 3, 5, rotation=270),
        part("J2", "screw-terminal-2", 20, 20),
        part("R1", "r-axial-3", 4, 9),
        part("R2", "r-axial-3", 20, 23),
        part("U1", "dip-8", 12, 10),
        nets=(
            Net(id="n1", name="A", nodes=(NetNode("J1", "1"), NetNode("R1", "1"), NetNode("U1", "2"))),
            Net(id="n2", name="B", nodes=(NetNode("J2", "2"), NetNode("R2", "2"), NetNode("U1", "7"))),
        ),
    )
    state, scorer = _scorer_for(doc, weights)
    start = scorer.full(state)
    assert start.entry_blocked >= 1 and start.entry_mm > 0  # both terms start out live
    movable = list(range(len(state.parts)))
    rng = random.Random(77)
    checked = 0
    for _ in range(400):
        proposal = _propose(rng, state, movable, 3, DEFAULT_PLACEMENT_OPTIONS)
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
        actual = scorer.full(state).total(weights) - full_before
        assert tracked == pytest.approx(actual, abs=1e-9)
        for position, (col, row, rot) in zip(positions, snapshot, strict=True):
            state.set_placement(position, col, row, rot)
        checked += 1
    assert checked > 200


def test_the_placer_turns_a_terminal_to_face_out_and_clears_its_mouth() -> None:
    """The board that asked for this: a terminal on the left edge with its mouth facing
    the board, and a resistor standing in front of it."""
    doc = doc_of(
        part("J1", "screw-terminal-2", 0, 10, rotation=270),
        part("R1", "r-axial-3", 4, 10, rotation=90),
        part("R2", "r-axial-3", 12, 12),
        nets=(
            Net(id="n1", name="A", nodes=(NetNode("J1", "1"), NetNode("R1", "1"))),
            Net(id="n2", name="B", nodes=(NetNode("J1", "2"), NetNode("R2", "1"))),
        ),
        board=dataclasses.replace(BOARD, cols=24, rows=16),
    )
    assert len(findings(doc)) == 1

    plan = plan_placement(
        doc, REGISTRY, PlacementOptions(iterations=3000, restarts=2, score_with_router=False)
    )
    assert plan.before.entry_blocked == 1
    assert plan.after.entry_blocked == 0
    assert findings(plan.document) == []
    # And facing out: the wire crosses little or no board to leave it.
    assert plan.after.entry_mm < plan.before.entry_mm
    assert plan.after.entry_mm <= 2.54
    assert "blocked wire entr(ies) cleared" in describe(plan)


def test_a_board_with_no_terminal_prices_nothing_new() -> None:
    doc = doc_of(part("R1", "r-axial-3", 3, 3), part("U1", "dip-8", 10, 5))
    state, scorer = _scorer_for(doc, PlacementWeights())
    cost = scorer.full(state)
    assert (cost.entry_blocked, cost.entry_mm) == (0, 0.0)


@pytest.mark.parametrize("mirrored", (False, True))
def test_the_arrangement_puts_each_terminals_mouth_out_of_its_edge(mirrored: bool) -> None:
    """Narrowness ties -- a terminal on end is as narrow facing left as facing right -- and
    the tie now goes to the rotation whose mouth faces out of the edge it is put on."""
    requests = [
        ArrangeRequest(id=f"cmp-J{i}", ref=f"J{i}", footprint_id="screw-terminal-3", mirrored=mirrored)
        for i in range(1, 5)
    ]
    arrangement = arrange(BOARD, requests, (), REGISTRY)
    assert arrangement.unplaced == ()
    for placed in arrangement.placements:
        component = dataclasses.replace(
            part(placed.ref, "screw-terminal-3", placed.anchor.col, placed.anchor.row, placed.rotation),
            mirrored=mirrored,
        )
        doc = doc_of(component)
        state, scorer = _scorer_for(doc, PlacementWeights())
        # Out of the edge it stands on: next to no board between the mouth and the outside.
        assert scorer.full(state).entry_mm <= 2.54, (placed.ref, placed.rotation)


# ---------------------------------------------------------------------------
# The guide and the renderers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rotation,side", ((0, "bottom"), (90, "left"), (180, "top"), (270, "right"))
)
def test_the_guide_says_which_edge_the_wires_come_in_from(rotation: int, side: str) -> None:
    doc = doc_of(part("J1", "screw-terminal-2", 20, 15, rotation))
    guide = build_guide(doc, REGISTRY)
    notes = [
        note
        for phase in guide.phases
        for step in phase.steps
        if getattr(step, "ref", None) == "J1"
        for note in getattr(step, "notes", ())
    ]
    assert any(f"wire entries face the {side} edge" in note for note in notes), notes


def test_a_generated_terminal_draws_its_openings_on_the_entry_face() -> None:
    """A six-way block has no borrowed mesh, so the generated body is what the 3D view
    shows -- and its openings have to be on the same face as the mesh's, or two terminals
    on one board would appear to face opposite ways."""
    pytest.importorskip("vtk")
    from perfboard_studio.ui import view3d

    component = part("J1", "screw-terminal-6", 10, 10, rotation=90)
    body = view3d._world_body(REGISTRY, component, BOARD)
    assert body is not None
    # Turned a quarter clockwise, the mouth faces left: world -x.
    assert body.entry == (-1.0, 0.0)
    pieces = view3d._wire_entry_pieces(body)
    assert len(pieces) == 6
    for piece, (pin_x, _pin_y) in zip(pieces, body.pins, strict=True):
        assert piece.position[0] < pin_x
    none = view3d._world_body(REGISTRY, part("R1", "r-axial-3", 3, 3), BOARD)
    assert none is not None and none.entry is None and view3d._wire_entry_pieces(none) == []


# ---------------------------------------------------------------------------
# On an edge and facing away from it
# ---------------------------------------------------------------------------
#
# ``terminal-entry-faces-in``: the half ``entry_run`` only preferred. Rotation 0 puts the
# mouth on local +y, which is the BOTTOM of the board, so a terminal on row 0 at rotation 0
# faces into the board and one on the last row faces out of it.


def faces_in(doc: PerfDocument) -> list[DrcViolation]:
    return [v for v in run_drc(doc, REGISTRY) if v.rule == "terminal-entry-faces-in"]


def test_a_terminal_on_an_edge_facing_into_the_board_is_reported() -> None:
    top_facing_in = part("J1", "screw-terminal-3", 10, 0, rotation=0)
    found = faces_in(doc_of(top_facing_in))
    assert len(found) == 1
    assert "stands on the top edge" in found[0].message
    assert "Turn J1 so its entries face the top edge" in found[0].message


@pytest.mark.parametrize(
    "col,row,rotation",
    [
        (10, 0, 180),  # top edge, facing up and out
        (10, BOARD.rows - 1, 0),  # bottom edge, facing down and out
        (15, 15, 0),  # the middle of the board: nothing says where its cable comes from
    ],
    ids=["top-facing-out", "bottom-facing-out", "mid-board"],
)
def test_a_terminal_facing_its_edge_or_in_the_middle_is_not(col: int, row: int, rotation: int) -> None:
    assert faces_in(doc_of(part("J1", "screw-terminal-3", col, row, rotation=rotation))) == []


def test_in_a_corner_either_edge_will_do() -> None:
    """On the top edge AND the left, facing up: it faces one of its edges, which is all a
    terminal in a corner can do."""
    corner = part("J1", "screw-terminal-2", 0, 0, rotation=180)
    assert faces_in(doc_of(corner)) == []


def test_one_hole_and_a_sliver_from_the_edge_is_still_on_it() -> None:
    """The case that set the reach at two pitches: a terminal a hole in from the edge,
    facing in, is on the edge to anybody looking at it. Far enough in, it is not."""
    assert len(faces_in(doc_of(part("J1", "screw-terminal-3", 10, 1, rotation=0)))) == 1
    assert faces_in(doc_of(part("J1", "screw-terminal-3", 10, 8, rotation=0))) == []


def test_the_placer_counts_what_drc_reports_facing_in() -> None:
    """One predicate, two consumers, over random boards with terminals near every edge."""
    rng = random.Random(4321)
    total = 0
    for _ in range(300):
        components = [
            part(
                f"J{i}",
                rng.choice(("screw-terminal-2", "screw-terminal-3")),
                rng.randrange(0, BOARD.cols - 6),
                rng.choice((0, 1, 2, 3, BOARD.rows - 3, BOARD.rows - 2, BOARD.rows - 1,
                            rng.randrange(0, BOARD.rows))),
                rng.choice((0, 90, 180, 270)),
                rng.random() < 0.3,
            )
            for i in range(3)
        ]
        doc = doc_of(*components)
        state, scorer = _scorer_for(doc, PlacementWeights())
        placer_count = scorer.full(state).entry_facing_in
        assert placer_count == len(faces_in(doc))
        total += placer_count
    assert total > 0


def test_the_placer_turns_an_edge_terminal_to_face_out() -> None:
    doc = doc_of(
        part("J1", "screw-terminal-2", 10, 0, rotation=0),
        part("R1", "r-axial-3", 10, 6),
        nets=(Net(id="n1", name="A", nodes=(NetNode("J1", "1"), NetNode("R1", "1"))),),
    )
    state, scorer = _scorer_for(doc, PlacementWeights())
    assert scorer.full(state).entry_facing_in == 1
    plan = plan_placement(doc, REGISTRY, PlacementOptions(seed=3))
    assert plan.after.entry_facing_in == 0
    assert "turned to face their edge" in describe(plan)


def test_the_facing_in_rule_fires_on_no_golden_fixture() -> None:
    for path in sorted(GOLDEN_DIR.glob("*.perf")):
        doc = persist.parse_document_or_throw(path.read_text(encoding="utf-8"))
        assert faces_in(doc) == [], path.name
