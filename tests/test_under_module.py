"""A part under a raised module is judged by its height (#12).

A module stands on header pins with its own board in the air -- 8.5 mm up on a female
header -- so a resistor lying under it is not in its way, though the two courtyards
overlap. What is pinned here: such a part draws a WARNING, ``under-module``, instead of rule
1's overlap ERROR, and only while it is low enough for the room under the board, clear of
the header mouldings and on the module's own face; a part beside the board, inside only the
courtyard's margin, is no finding at all; the placer counts and clears exactly the pairs DRC
names, over the whole library; and the build guide says it at the part's own step, in either
language.
"""

from __future__ import annotations

import dataclasses
import random

import pytest

from perfboard_studio.catalog import CATALOG
from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.drc import (
    _check_component_body_overlap,
    _check_under_module,
    courtyard_box,
    placed_body_box,
    run_drc,
)
from perfboard_studio.footprints import (
    MODULE_SEAT_SOLDERED_MM,
    UNDER_MODULE_CLEARANCE_MM,
    footprint_lookup,
    raised_board,
    standard_footprints,
)
from perfboard_studio.geometry import all_pin_holes, boxes_overlap
from perfboard_studio.guide import GuideOptions, PartStep, build_guide
from perfboard_studio.mcp.session import new_board
from perfboard_studio.model import ComponentInstance, HoleCoord, Net, NetNode, PerfDocument
from perfboard_studio.placer import (
    DEFAULT_PLACEMENT_OPTIONS,
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
    describe,
    plan_placement,
)

REGISTRY = footprint_lookup()

#: An Arduino Nano on female headers, as the catalogue and examples/nano-relay.perf have it:
#: two rows of fifteen pins six holes apart, its board 8.5 mm up.
NANO = "mod-2x15-p6-r1-17.78x45.72x4-s8.5-o0x1.27"
#: The same module soldered straight in on its pins' 2.5 mm spacer.
NANO_SOLDERED = "mod-2x15-p6-r1-17.78x45.72x4-s2.5-o0x1.27"

#: Its header rows are columns 10 and 16, rows 5 to 19; columns 11 to 15 are under its board.
MODULE_AT = HoleCoord(10, 5)


def _part(
    ref: str,
    footprint_id: str,
    col: int,
    row: int,
    rotation: int = 0,
    *,
    mirrored: bool = False,
    locked: bool = False,
) -> ComponentInstance:
    return ComponentInstance(
        id=f"c-{ref}",
        ref=ref,
        value="",
        footprint_id=footprint_id,
        anchor=HoleCoord(col, row),
        rotation=rotation,  # type: ignore[arg-type]
        mirrored=mirrored,
        locked=locked,
    )


def _doc(*parts: ComponentInstance, nets: tuple[Net, ...] = ()) -> PerfDocument:
    blank = new_board(cols=40, rows=40, name="under")
    return dataclasses.replace(blank, components=parts, nets=nets)


def _module(footprint_id: str = NANO, rotation: int = 0, **kw: bool) -> ComponentInstance:
    return _part("U1", footprint_id, MODULE_AT.col, MODULE_AT.row, rotation, **kw)


def _rules(doc: PerfDocument) -> list[str]:
    return [v.rule for v in run_drc(doc, REGISTRY) if v.rule in ("component-body-overlap", "under-module")]


def test_a_resistor_under_a_socketed_module_is_a_warning_not_an_overlap() -> None:
    """The reporter's board: a resistor lying between a Nano's header rows."""
    doc = _doc(_module(), _part("R1", "r-axial-3", 13, 8, 90))
    findings = [v for v in run_drc(doc, REGISTRY) if v.rule in ("component-body-overlap", "under-module")]
    assert [(v.rule, v.severity, v.component_ids) for v in findings] == [
        ("under-module", "warning", ("c-R1", "c-U1"))
    ]
    assert findings[0].message == (
        "R1 (2 mm tall) sits under U1, whose board is 8.5 mm up: fit it first; it cannot be "
        "reached afterwards without lifting the module."
    )


def test_the_finding_is_said_in_a_turkish_window() -> None:
    """No board in the repository has a part under a module, so the findings panel's
    every-board test never meets this finding; it is said here."""
    from perfboard_studio.ui.engine_text import say_finding
    from perfboard_studio.ui.i18n import language, set_language

    doc = _doc(_module(), _part("R1", "r-axial-3", 13, 8, 90))
    [finding] = [v for v in run_drc(doc, REGISTRY) if v.rule == "under-module"]
    before = language()
    set_language("tr")
    try:
        said = say_finding(finding.message)
    finally:
        set_language(before)
    assert said == (
        "R1 (2 mm boyunda) U1 modülünün altında kalıyor ve modülün kartı 8.5 mm yukarıda: önce "
        "onu tak, çünkü sonradan modülü çıkarmadan ona ulaşılamaz."
    )


@pytest.mark.parametrize(
    ("why", "doc"),
    [
        # 11.5 mm of electrolytic does not go under 7 mm of room.
        ("too tall", _doc(_module(), _part("C1", "c-elec-d8-p3", 13, 8, 90))),
        # The same resistor under the same module soldered on its 2.5 mm spacer.
        ("soldered", _doc(_module(NANO_SOLDERED), _part("R1", "r-axial-3", 13, 8, 90))),
        # Lying across the left header row: its body is on the moulding, however low.
        ("on a header", _doc(_module(), _part("R1", "r-axial-3", 8, 10))),
        # On the solder side it is the other side of the board, and rule 1 is as it was.
        ("other face", _doc(_module(), _part("R1", "r-axial-3", 13, 8, 90, mirrored=True))),
    ],
)
def test_what_does_not_fit_under_is_still_an_overlap(why: str, doc: PerfDocument) -> None:
    assert _rules(doc) == ["component-body-overlap"], why


def test_beside_the_board_inside_its_margin_is_no_finding() -> None:
    """Past the end of the module's board, inside its courtyard's margin: the courtyards
    overlap, nothing is over the resistor, and nothing is in its way."""
    module = _module()
    resistor = _part("R1", "r-axial-3", 12, 22)
    doc = _doc(module, resistor)
    module_fp, resistor_fp = REGISTRY(NANO), REGISTRY("r-axial-3")
    assert module_fp is not None and resistor_fp is not None
    yard_m = courtyard_box(module, module_fp, doc.board)
    yard_r = courtyard_box(resistor, resistor_fp, doc.board)
    assert yard_m is not None and yard_r is not None
    # Both boxes are (min x, min y, max x, max y) here; the resistor's top edge is inside.
    assert yard_r[1] < yard_m[3] and yard_r[0] < yard_m[2] and yard_m[0] < yard_r[2]
    assert not boxes_overlap(
        placed_body_box(resistor, resistor_fp, doc.board), placed_body_box(module, module_fp, doc.board)
    )
    assert _rules(doc) == []


def test_a_soldered_module_has_room_for_nothing_in_the_library() -> None:
    """Why ``under-module`` is a socketed module's rule in practice, and why the build guide
    can say "before it goes in" of every part it names: a module soldered on its spacer
    leaves a millimetre, and no package in the registry or the catalogue is that low. So a
    part the rule names is under a module that plugs in, and that goes in last."""
    room = MODULE_SEAT_SOLDERED_MM - UNDER_MODULE_CLEARANCE_MM
    ids = set(standard_footprints()) | {part.footprint_id for part in CATALOG}
    heights = {}
    for footprint_id in sorted(ids):
        footprint = REGISTRY(footprint_id)
        assert footprint is not None, footprint_id
        heights[footprint_id] = footprint.body_height
    assert min(heights.values()) > room, min(heights.items(), key=lambda item: item[1])


def _scorer_for(doc: PerfDocument, lookup: FootprintLookup, weights: PlacementWeights):
    parts = _build_parts(doc, lookup)
    nets, nets_of, pin_nets = _build_nets(doc, parts)
    strips = _build_strips(doc, parts, pin_nets)
    state = _initial_state(doc, parts, strips)
    scorer = _make_scorer(
        doc.board, weights, nets, nets_of, strips, _dead_hole_keys(doc), doc.mounting_holes
    )
    return state, scorer


#: Where the walk puts the module: far enough in that it stays on the board at any rotation.
WALK_AT = HoleCoord(20, 20)


def _walk(module: ComponentInstance) -> list[tuple[int, int]]:
    """Anchors across a placed module: every hole along the row through its middle and
    every other one along the column, from four holes outside its pins on each side."""
    footprint = REGISTRY(module.footprint_id)
    assert footprint is not None
    pins = [at for _pin, at in all_pin_holes(module, footprint)]
    cols = [at.col for at in pins]
    rows = [at.row for at in pins]
    mid_col, mid_row = (min(cols) + max(cols)) // 2, (min(rows) + max(rows)) // 2
    return [(col, mid_row) for col in range(min(cols) - 4, max(cols) + 5)] + [
        (mid_col, row) for row in range(min(rows) - 4, max(rows) + 5, 2)
    ]


@pytest.mark.parametrize("mirrored", (False, True))
@pytest.mark.parametrize("module_rotation", (0, 90))
def test_the_placer_and_drc_agree_on_every_body_under_a_module(
    mirrored: bool, module_rotation: int
) -> None:
    """One fact, two consumers, over the whole library -- the module twin of the screw-head
    walk in ``test_placer``.

    Every one of the registry footprints, at every rotation, walked across a socketed Nano
    -- turned and not -- along a row and along a column, from outside its board to right
    across its header rows: the placer's count of parts under the board must be the number
    of ``under-module`` findings, and its count of overlapping pairs the number of rule 1's,
    every time. Both read the same boxes and ask the same two predicates in ``geometry``,
    and this is what would notice one of them growing a second opinion. Mirrored as well,
    where the part is on the other face from the module and nothing fits under it.
    """
    module = _part("U1", NANO, WALK_AT.col, WALK_AT.row, module_rotation)
    anchors = _walk(module)
    checked = under = overlaps = 0
    for footprint_id in sorted(standard_footprints()):
        for rotation in (0, 90, 180, 270):
            for col, row in anchors:
                doc = _doc(module, _part("X1", footprint_id, col, row, rotation, mirrored=mirrored))
                state, scorer = _scorer_for(doc, REGISTRY, PlacementWeights())
                cost = scorer.full(state)
                drc_under = len(_check_under_module(doc, REGISTRY))
                drc_overlaps = len(_check_component_body_overlap(doc, REGISTRY))
                assert cost.under_module == drc_under, (footprint_id, rotation, col, row)
                assert cost.overlap_pairs == drc_overlaps, (footprint_id, rotation, col, row)
                checked += 1
                under += drc_under
                overlaps += drc_overlaps
    # Not vacuous: parts in its way at every turn, and parts under the board on its own face.
    assert 0 < overlaps < checked
    assert (under == 0) if mirrored else (0 < under < checked)


def test_local_delta_matches_a_full_recompute_around_a_module() -> None:
    """The load-bearing local-delta test on a board where the module terms are LIVE: low
    parts that fit under the Nano, a tall one that does not, moved in and out from under it
    and across its headers, and the module moved over them."""
    weights = PlacementWeights()
    doc = _doc(
        _module(),
        _part("R1", "r-axial-3", 13, 8, 90),
        _part("R2", "r-axial-3", 12, 14, 90),
        _part("D1", "d-do41", 2, 10),
        _part("C1", "c-elec-d8-p3", 20, 12, 90),
        nets=(
            Net(id="n1", name="SIG", net_class="signal", nodes=(
                NetNode(component_ref="U1", pin="3"), NetNode(component_ref="R1", pin="1"),
                NetNode(component_ref="D1", pin="1"),
            )),
            Net(id="n2", name="GND", net_class="ground", nodes=(
                NetNode(component_ref="U1", pin="4"), NetNode(component_ref="R2", pin="2"),
                NetNode(component_ref="C1", pin="2"),
            )),
        ),
    )
    state, scorer = _scorer_for(doc, REGISTRY, weights)
    assert scorer.full(state).under_module == 2  # the term starts out live
    movable = list(range(len(state.parts)))
    rng = random.Random(1212)

    checked = live = 0
    for _ in range(600):
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
        after = scorer.full(state)
        actual = after.total(weights) - full_before
        assert tracked == pytest.approx(actual, abs=1e-9)
        live += after.under_module > 0

        for position, (col, row, rot) in zip(positions, snapshot, strict=True):
            state.set_placement(position, col, row, rot)
        checked += 1

    assert checked > 300 and live > 0


def test_the_placer_moves_a_part_out_from_under_a_module() -> None:
    """Priced as a warning, so the placer does not hide a part on its own initiative: a
    resistor left under a locked Nano is moved out, and said to be."""
    doc = _doc(
        _module(locked=True),
        _part("R1", "r-axial-3", 13, 8, 90),
        nets=(
            Net(id="n1", name="SIG", net_class="signal", nodes=(
                NetNode(component_ref="U1", pin="3"), NetNode(component_ref="R1", pin="1"),
            )),
        ),
    )
    plan = plan_placement(doc, REGISTRY, PlacementOptions(seed=0, restarts=1, score_with_router=False))
    assert plan.before.under_module == 1 and plan.before.overlap_pairs == 0
    assert plan.after.under_module == 0 and plan.after.is_legal
    assert _rules(plan.document) == []
    assert "1 part(s) moved out from under a module" in describe(plan)


@pytest.mark.parametrize(
    ("language", "said"),
    [
        ("en", "This part sits under U1's board. Press it right down onto the board"),
        ("tr", "Bu parça U1 modülünün kartının altında kalıyor."),
    ],
)
def test_the_guide_says_it_at_the_step_of_the_part_underneath(language: str, said: str) -> None:
    doc = _doc(_module(), _part("R1", "r-axial-3", 13, 8, 90))
    guide = build_guide(doc, REGISTRY, GuideOptions(language=language))  # type: ignore[arg-type]
    steps = {s.ref: s for phase in guide.phases for s in phase.steps if isinstance(s, PartStep)}
    assert [note for note in steps["R1"].notes if note.startswith(said)]
    assert not [note for note in steps["U1"].notes if "U1" in note]
    order = [s.ref for phase in guide.phases for s in phase.steps if isinstance(s, PartStep)]
    assert order.index("R1") < order.index("U1")


def test_only_a_module_holds_a_board_up() -> None:
    """Every other part in the library has no raised board, so on a board without a module
    no pair is ever asked about one -- the placer's sums are the ones they always were."""
    raised = {fid for fid, fp in standard_footprints().items() if raised_board(fp, 2.54) is not None}
    assert raised == set()
    nano = REGISTRY(NANO)
    assert nano is not None
    board = raised_board(nano, 2.54)
    assert board is not None
    assert board.seat == 8.5 and board.headroom == 8.5 - UNDER_MODULE_CLEARANCE_MM
    assert len(board.headers) == 30
