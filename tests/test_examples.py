"""The shipped examples must stay buildable.

These are the boards the README points a stranger at, so "it opens" is not enough: an
example that loads but no longer passes its own checks is worse than no example, because
somebody following it will conclude the tool is wrong about their board too.

Deliberately cheap. Each `.perf` is loaded and checked, and nothing is re-placed or
re-routed -- `tools/build_examples.py` does that, takes about half a minute, and is run
by hand when an example is regenerated. What is asserted here is the property that has to
hold on every commit: the documents on disk are valid, they still match their schematics,
and they carry no design error.

An example of several boards (relay-and-supply) goes through the same tests: whatever is a
board's question -- DRC, the stock board, the pads, the guide -- is asked of every board in
it, each seen alone as the window sees the one in front, and LVS is the system's.
"""

from __future__ import annotations

import pathlib

import pytest

from perfboard_studio import persist
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.guide import build_guide
from perfboard_studio.lvs import run_lvs
from perfboard_studio.model import PerfDocument
from perfboard_studio.parsers.kicad import parse_kicad_netlist
from perfboard_studio.system import board_document, board_ids

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
PERF_FILES = sorted(EXAMPLES.glob("*.perf"))
NET_FILES = sorted(EXAMPLES.glob("*.net"))


def _boards(document: PerfDocument) -> list[tuple[str, PerfDocument]]:
    """Every board of ``document`` as the document of that board alone -- one for an
    example of one board, which is the document itself."""
    return [(board_id, board_document(document, board_id)) for board_id in board_ids(document)]


def test_every_netlist_has_a_board() -> None:
    """The two halves of an example ship together, or the README links to nothing."""
    assert {p.stem for p in NET_FILES} == {p.stem for p in PERF_FILES}
    assert len(PERF_FILES) >= 4


@pytest.mark.parametrize("path", PERF_FILES, ids=lambda p: p.stem)
def test_example_loads_without_warnings(path: pathlib.Path) -> None:
    result = persist.deserialize_document(path.read_text(encoding="utf-8"))
    assert result.ok, f"{path.name}: [{result.code}] {result.message}"
    # A warning here means a hand-edit that DRC will report -- legitimate in a user's
    # document (see validate_orthogonal_chain), never in one this repository ships.
    assert not result.warnings, f"{path.name}: {result.warnings}"


@pytest.mark.parametrize("path", PERF_FILES, ids=lambda p: p.stem)
def test_example_round_trips_byte_identical(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    result = persist.deserialize_document(text)
    assert result.ok
    assert persist.serialize_document(result.document) == text


@pytest.mark.parametrize("path", PERF_FILES, ids=lambda p: p.stem)
def test_example_has_no_drc_errors(path: pathlib.Path) -> None:
    """Warnings are allowed and expected -- four of the boards carry an R5' proximity
    warning (arduino-io-shield, atmega328-relay three times, lm317-supply and
    ne555-astable), a trace laid beside another net's pin, which is the rule doing its job
    and becomes a checkpoint in the guide. An *error* is a board that cannot be built as
    drawn."""
    result = persist.deserialize_document(path.read_text(encoding="utf-8"))
    assert result.ok
    for board_id, board in _boards(result.document):
        errors = [v for v in run_drc(board, footprint_lookup()) if v.severity == "error"]
        assert not errors, (board_id, [f"{v.rule}: {v.message}" for v in errors])


@pytest.mark.parametrize("path", PERF_FILES, ids=lambda p: p.stem)
def test_example_matches_its_schematic(path: pathlib.Path) -> None:
    result = persist.deserialize_document(path.read_text(encoding="utf-8"))
    assert result.ok
    lvs = run_lvs(result.document, footprint_lookup())
    assert lvs.ok, [f"{i.kind}: {i.message}" for i in lvs.issues]


@pytest.mark.parametrize("path", PERF_FILES, ids=lambda p: p.stem)
def test_example_produces_a_guide_with_checkpoints(path: pathlib.Path) -> None:
    """The guide is the point of the tool, and checkpoints are the point of the guide."""
    result = persist.deserialize_document(path.read_text(encoding="utf-8"))
    assert result.ok
    for board_id, board in _boards(result.document):
        guide = build_guide(board, footprint_lookup())
        assert guide.total_steps > 0, board_id
        assert guide.checkpoint_count > 0, board_id


@pytest.mark.parametrize("path", PERF_FILES, ids=lambda p: p.stem)
def test_example_is_on_a_board_somebody_sells(path: pathlib.Path) -> None:
    """The examples used to be on grids nobody stocks -- 32 x 22, 30 x 20, 24 x 18 -- which
    taught two wrong things at once: that perfboard comes in whatever size you like, and
    that the finger strips and corner screw holes a real board arrives with are somebody
    else's problem. They are not; a finger is solid copper with no bore, and the placer and
    the router had to learn that before these boards could carry one."""
    from perfboard_studio.boardfamily import STANDARD_PRESETS
    from perfboard_studio.geometry import board_size_mm

    whole = persist.deserialize_document(path.read_text(encoding="utf-8")).document
    for board_id, document in _boards(whole):
        board = document.board
        preset = next(
            (
                p
                for p in STANDARD_PRESETS
                if p.cols == board.cols
                and p.rows == board.rows
                and p.single_sided == board.single_sided
            ),
            None,
        )
        assert preset is not None, f"{board_id}: {board.cols}x{board.rows} is not stocked"

        # ...and it is that product to the tenth of a millimetre, not merely its hole count.
        width, height = board_size_mm(board)
        assert width == pytest.approx(preset.width_mm, abs=0.05)
        assert height == pytest.approx(preset.height_mm, abs=0.05)
        assert document.edge_connectors, f"{board_id}: a stocked board has its finger strips"


@pytest.mark.parametrize("path", PERF_FILES, ids=lambda p: p.stem)
def test_nothing_is_soldered_where_there_is_no_pad(path: pathlib.Path) -> None:
    """The property the examples exist to prove now that they carry real products: neither
    planner puts anything on a finger or on a hole a mounting bore has taken.

    Asserted separately from ``test_example_has_no_drc_errors`` even though DRC covers it,
    because that test would report a change here as one of a list and this one names it.
    The stock boards' strips stand outside the grid and their corner holes in the border, so
    most of them lose no hole at all; on a board whose border cannot hold a screw it is on
    the corner position, and the set is not empty.
    """
    from perfboard_studio.geometry import all_pin_holes, hole_key, unusable_holes

    whole = persist.deserialize_document(path.read_text(encoding="utf-8")).document
    lookup = footprint_lookup()
    for board_id, document in _boards(whole):
        dead = unusable_holes(document)
        assert document.edge_connectors or document.mounting_holes, (
            f"{board_id}: a stocked board arrives with its strips and its corner holes"
        )

        for component in document.components:
            footprint = lookup(component.footprint_id)
            if footprint is None:
                continue
            for pin, at in all_pin_holes(component, footprint):
                assert hole_key(at) not in dead, f"{component.ref} pin {pin.number} has no pad"

        for conductor in document.conductors:
            for at in conductor.path:
                assert hole_key(at) not in dead, f"{conductor.id} runs over a hole with no pad"


@pytest.mark.parametrize("path", NET_FILES, ids=lambda p: p.stem)
def test_netlist_parses(path: pathlib.Path) -> None:
    """Parses, and complains about nothing except the one thing every real export has.

    KiCad emits a net per unconnected pin (`unconnected-(U1-Pad4)`), and the importer
    skips them with a warning saying how many. That warning is the importer working, so
    it is allowed by name rather than by loosening the check to nothing.
    """
    parsed = parse_kicad_netlist(path.read_text(encoding="utf-8"))
    assert parsed.nets
    unexpected = [w for w in parsed.warnings if "unconnected net" not in w]
    assert not unexpected, unexpected


@pytest.mark.parametrize("path", PERF_FILES, ids=lambda p: p.stem)
def test_board_carries_every_part_the_netlist_names(path: pathlib.Path) -> None:
    """The `.perf` is built from the `.net` beside it, so a part cannot go missing from
    one without the other noticing. On several boards, on one of them."""
    from perfboard_studio.system import every_component

    result = persist.deserialize_document(path.read_text(encoding="utf-8"))
    assert result.ok
    parsed = parse_kicad_netlist((EXAMPLES / f"{path.stem}.net").read_text(encoding="utf-8"))
    wanted = {node.component_ref for net in parsed.nets for node in net.nodes}
    placed = {component.ref for component in every_component(result.document)}
    assert wanted <= placed, f"missing from the board: {sorted(wanted - placed)}"


# ---------------------------------------------------------------------------
# The example of several boards
# ---------------------------------------------------------------------------

SYSTEM_PERF = EXAMPLES / "relay-and-supply.perf"


def test_the_system_example_is_two_boards_and_the_cable_between_them() -> None:
    """What the README says it is: the relay driver and its 12 V supply, each on its own
    stock board, one two-wire cable from the supply's output to the relay's input, and the
    whole proven against one schematic -- every net that crosses carried by the cable."""
    from perfboard_studio.harness import build_harness
    from perfboard_studio.lvs import run_system_lvs
    from perfboard_studio.system import board_title, every_component

    document = persist.deserialize_document(SYSTEM_PERF.read_text(encoding="utf-8")).document
    lookup = footprint_lookup()
    assert [board_title(document, b) for b in board_ids(document)] == ["Relay driver", "Supply"]
    boards = dict(_boards(document))
    assert {c.ref for c in boards["supply"].components} >= {"U101", "J101", "J102"}
    assert {c.ref for c in boards["main"].components} >= {"A1", "K1", "J1"}
    assert document.parts == (), "every part is on a board"

    (cable,) = document.cables
    assert cable.ref == "W1"
    by_id = {c.id: c.ref for c in every_component(document)}
    assert (cable.a.board, by_id[cable.a.connector]) == ("supply", "J102")
    assert (cable.b.board, by_id[cable.b.connector]) == ("main", "J1")

    lvs = run_system_lvs(document, lookup)
    assert lvs.ok, [f"{i.kind}: {i.message}" for i in lvs.issues]
    assert lvs.uncabled == ()

    (harness,) = build_harness(document).cables
    assert harness.ref == "W1"
    assert sorted(wire.net_name for wire in harness.wires) == ["+12V", "GND"]
    assert harness.checkpoints, "the cable is checked before the system is powered"


def test_a_boards_guide_measures_only_what_is_on_it() -> None:
    """+12V and GND are on both boards. A continuity or isolation check on one board's
    guide names a pin on that board, never one at the other end of the cable -- the
    harness proves the cable. Chained through the other board, "C1.1 to C102.1" was a
    measurement nobody can make, and it hid the one between C1 and the next pin here that
    somebody can."""
    document = persist.deserialize_document(SYSTEM_PERF.read_text(encoding="utf-8")).document
    lookup = footprint_lookup()
    for board_id, board in _boards(document):
        here = {c.ref for c in board.components}
        for phase in build_guide(board, lookup).phases:
            for check in phase.checkpoints:
                away = [pin.component_ref for pin in check.pins if pin.component_ref not in here]
                assert away == [], (board_id, check.title)


# ---------------------------------------------------------------------------
# The project example: a design with nothing built yet
# ---------------------------------------------------------------------------
#
# The four above are finished boards, and what has to hold for them is that they still
# load, still match their schematics and carry no error. This one is the other end of the
# workflow -- a circuit drawn and not yet built -- so what has to hold is different, and
# every assertion below is about the walkthrough its README promises. An example whose
# README describes something the tool no longer does is worse than no example.

PROJECT = EXAMPLES / "ne555-blinker"
PROJECT_PERF = PROJECT / "ne555-blinker.perf"


def _project_document():
    result = persist.deserialize_document(PROJECT_PERF.read_text(encoding="utf-8"))
    assert result.ok, f"{PROJECT_PERF.name}: [{result.code}] {result.message}"
    assert not result.warnings, f"{PROJECT_PERF.name}: {result.warnings}"
    return result.document


def test_the_project_example_is_a_project() -> None:
    """A folder built around exactly one board, with the netlist it came from kept in it.
    The README tells somebody to open it with File > Open Project, and that refuses a
    folder holding two boards."""
    from perfboard_studio.project import document_in, is_project_dir

    names = [entry.name for entry in PROJECT.iterdir()]
    assert is_project_dir(names)
    assert document_in(names) == "ne555-blinker.perf"
    assert "netlist.net" in names


def test_the_project_example_round_trips_byte_identical() -> None:
    text = PROJECT_PERF.read_text(encoding="utf-8")
    assert persist.serialize_document(_project_document()) == text


def test_the_project_example_is_a_design_and_not_a_board() -> None:
    """The whole point of it. Every part is in doc.parts with no anchor, which is what
    makes "Place on the Board" the next thing to press -- and what makes the board-size
    question askable at all, since it is only asked while the board is still empty."""
    document = _project_document()
    assert document.components == ()
    assert document.conductors == ()
    assert len(document.parts) == 10
    assert len(document.nets) == 7


def test_every_part_in_the_project_example_has_a_footprint_the_library_has() -> None:
    lookup = footprint_lookup()
    unknown = [part.ref for part in _project_document().parts if lookup(part.footprint_id) is None]
    assert unknown == [], f"the registry does not have footprints for {unknown}"


def test_the_project_examples_sheet_draws_every_part() -> None:
    """An undefined symbol means a net names a part nothing defines. On a design example
    that is not a note in a panel, it is the circuit being wrong."""
    from perfboard_studio.schematic import build_schematic

    drawing = build_schematic(_project_document(), footprint_lookup())
    assert len(drawing.symbols) == 10
    assert [symbol.ref for symbol in drawing.symbols if symbol.undefined] == []
    assert drawing.rails, "ground and power should be drawn as rail glyphs"


def test_the_project_example_walks_from_a_design_to_a_checked_board() -> None:
    """The walkthrough its README describes, run end to end, as the window runs it: the
    board question TRIED on the design (``boardfit.choose_board``), the board it recommends
    applied, the placement that board was judged by committed, routed, checked.

    Slower than the rest of this file and worth it: this is the one test that exercises the
    order of work the application recommends -- design, board, placement, route -- against a
    real circuit, and the finished examples cannot, because they arrive already built. It
    tries one board below the reference rather than all four, which is the whole mechanism
    at a quarter of the time; ``tools/build_examples.py`` runs the full question.
    """
    from perfboard_studio.autoroute import AutorouteOptions, plan_autoroute
    from perfboard_studio.boardfit import BoardTrialOptions, choose_board
    from perfboard_studio.command import CommandBus, CommandContext
    from perfboard_studio.commands import (
        create_document_id_generator,
        create_standard_registry,
        preset_payload,
    )
    from perfboard_studio.geometry import hole_to_mm, substrate_edges_mm, transform_offset
    from perfboard_studio.placer import placement_inputs
    from perfboard_studio.router import RouterOptions

    lookup = footprint_lookup()
    document = _project_document()
    bus = CommandBus(
        document,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(document)),
    )

    choice = choose_board(document, lookup, options=BoardTrialOptions(max_smaller_boards=1))
    assert choice.complete and choice.reference is not None and choice.recommended is not None
    assert choice.verdicts[0].kind == "reference"
    assert len(choice.verdicts) == 2, "the reference, and the one board below it"
    # The smaller board is the answer whenever it builds as well as the roomy one.
    if choice.verdicts[1].accepted:
        assert choice.recommended.preset == choice.verdicts[1].preset

    chosen = choice.recommended
    assert bus.dispatch("board.applyPreset", preset_payload(chosen.preset, chosen.board)).ok
    verdict = choice.verdict_for(chosen.preset)
    assert verdict is not None and verdict.trial.document is not None
    assert placement_inputs(bus.document) == placement_inputs(verdict.trial.document)
    assert verdict.trial.placed is not None and verdict.trial.placed.unplaced == ()
    assert bus.dispatch("part.place", verdict.trial.placed.payload()).ok

    placed = bus.document
    assert placed.parts == ()
    assert len(placed.components) == 10

    # The connectors are on the edge, which is the reason the arrangement exists.
    #
    # Measured from the part's COURTYARD to the substrate edge, the way the placer's own
    # ``edge`` term measures it, and not from the anchor. The anchor is pin 1: a three-pin
    # header lying across the right-hand edge has its courtyard on the edge and its anchor
    # two holes in, and the anchor measure called that "not on an edge". "On" is within one
    # hole of the grid on that side, border included: the border differs per axis on a stock
    # board, and its outermost row along two edges is a finger strip nothing can stand on.
    board = placed.board
    edges = substrate_edges_mm(board)
    for ref in ("J1", "J2"):
        connector = next(c for c in placed.components if c.ref == ref)
        footprint = lookup(connector.footprint_id)
        assert footprint is not None
        corners = [
            transform_offset(point.x, point.y, connector.rotation, connector.mirrored)
            for point in footprint.body_outline
        ]
        anchor = hole_to_mm(connector.anchor, board)
        xs = [anchor.x + x for x, _ in corners]
        ys = [anchor.y + y for _, y in corners]
        clear_of_the_grid = (
            min(xs) - edges.min_x - board.border_x_mm,
            edges.max_x - max(xs) - board.border_x_mm,
            min(ys) - edges.min_y - board.border_y_mm,
            edges.max_y - max(ys) - board.border_y_mm,
        )
        inside = min(clear_of_the_grid)
        assert inside <= board.pitch, f"{ref} was not put on an edge ({inside:.2f} mm in)"

    # Routed as Ctrl+R routes, wires along the grid.
    route = plan_autoroute(placed, lookup, AutorouteOptions(router=RouterOptions(wire_path="grid")))
    assert route.summary.links_unrouted == 0
    assert bus.dispatch("conductor.addMany", route.payload()).ok

    built = bus.document
    errors = [v for v in run_drc(built, lookup) if v.severity == "error"]
    assert errors == [], [v.message for v in errors]
    assert run_lvs(built, lookup).ok
    assert build_guide(built, lookup).total_steps > 0
