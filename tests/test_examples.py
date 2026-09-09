"""The shipped examples must stay buildable.

These are the boards the README points a stranger at, so "it opens" is not enough: an
example that loads but no longer passes its own checks is worse than no example, because
somebody following it will conclude the tool is wrong about their board too.

Deliberately cheap. Each `.perf` is loaded and checked, and nothing is re-placed or
re-routed -- `tools/build_examples.py` does that, takes about half a minute, and is run
by hand when an example is regenerated. What is asserted here is the property that has to
hold on every commit: the documents on disk are valid, they still match their schematics,
and they carry no design error.
"""

from __future__ import annotations

import pathlib

import pytest

from perfboard_studio import persist
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.guide import build_guide
from perfboard_studio.lvs import run_lvs
from perfboard_studio.parsers.kicad import parse_kicad_netlist

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
PERF_FILES = sorted(EXAMPLES.glob("*.perf"))
NET_FILES = sorted(EXAMPLES.glob("*.net"))


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
    """Warnings are allowed and expected -- the LM317 board carries an R5' proximity
    warning, which is the rule doing its job and becomes a checkpoint in the guide.
    An *error* is a board that cannot be built as drawn."""
    result = persist.deserialize_document(path.read_text(encoding="utf-8"))
    assert result.ok
    errors = [v for v in run_drc(result.document, footprint_lookup()) if v.severity == "error"]
    assert not errors, [f"{v.rule}: {v.message}" for v in errors]


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
    guide = build_guide(result.document, footprint_lookup())
    assert guide.total_steps > 0
    assert guide.checkpoint_count > 0


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
    one without the other noticing."""
    result = persist.deserialize_document(path.read_text(encoding="utf-8"))
    assert result.ok
    parsed = parse_kicad_netlist((EXAMPLES / f"{path.stem}.net").read_text(encoding="utf-8"))
    wanted = {node.component_ref for net in parsed.nets for node in net.nodes}
    placed = {component.ref for component in result.document.components}
    assert wanted <= placed, f"missing from the board: {sorted(wanted - placed)}"


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


def test_the_project_example_is_offered_a_stock_board_with_room_to_wire_it() -> None:
    """What the README's table promises: the smallest board that fits is NOT the one
    suggested, because a board packed to its last hole has nowhere to run a trace."""
    from perfboard_studio.placer import design_entries, recommended_board, suggest_boards

    document = _project_document()
    suggestions = suggest_boards(
        document.board, design_entries(document), document.nets, footprint_lookup()
    )
    best = recommended_board(suggestions)

    assert best is not None and best.roomy
    smallest_that_fits = next(s for s in suggestions if s.fits)
    assert smallest_that_fits.preset is not best.preset
    # ...and the boards too small for it are still shown, rather than the list quietly
    # starting halfway up.
    assert any(not s.fits for s in suggestions)


def test_the_project_example_places_routes_and_checks_out(tmp_path) -> None:
    """The walkthrough its README describes, run end to end.

    Slower than the rest of this file and worth it: this is the one test that exercises
    the order of work the application now recommends -- design, board, arrangement, route
    -- against a real circuit, and the four finished examples cannot, because they arrive
    already built.
    """
    from perfboard_studio.autoroute import plan_autoroute
    from perfboard_studio.command import CommandBus, CommandContext
    from perfboard_studio.commands import (
        ApplyBoardPresetPayload,
        PartPlacement,
        PlacePartsPayload,
        create_document_id_generator,
        create_standard_registry,
        place_parts,
    )
    from perfboard_studio.geometry import preset_edge_connectors, preset_mounting_holes
    from perfboard_studio.placer import (
        PlacementOptions,
        arrange_design,
        design_entries,
        plan_placement,
        recommended_board,
        suggest_boards,
    )

    lookup = footprint_lookup()
    document = _project_document()
    bus = CommandBus(
        document,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(document)),
    )

    best = recommended_board(
        suggest_boards(document.board, design_entries(document), document.nets, lookup)
    )
    assert best is not None
    assert bus.dispatch(
        "board.applyPreset",
        ApplyBoardPresetPayload(
            board=best.board,
            edge_connectors=preset_edge_connectors(best.preset, best.board),
            mounting_holes=preset_mounting_holes(best.preset, best.board),
        ),
    ).ok

    # Exactly what the window does behind the Place button: arrange, anneal on a preview,
    # commit the settled anchors as one part.place.
    arrangement = arrange_design(bus.document, lookup)
    assert arrangement.fits
    preview = place_parts.apply(
        bus.document,
        PlacePartsPayload(
            placements=tuple(
                PartPlacement(id=p.id, anchor=p.anchor, rotation=p.rotation)
                for p in arrangement.placements
            )
        ),
        CommandContext(next_id=create_document_id_generator(bus.document)),
    )
    settled = {c.id: c for c in plan_placement(preview, lookup, PlacementOptions(seed=0)).document.components}
    assert bus.dispatch(
        "part.place",
        PlacePartsPayload(
            placements=tuple(
                PartPlacement(
                    id=p.id, anchor=settled[p.id].anchor, rotation=settled[p.id].rotation
                )
                for p in arrangement.placements
            )
        ),
    ).ok

    placed = bus.document
    assert placed.parts == ()
    assert len(placed.components) == 10

    # The connectors are on the edge, which is the reason the arrangement exists.
    board = placed.board
    for ref in ("J1", "J2"):
        connector = next(c for c in placed.components if c.ref == ref)
        assert (
            min(
                connector.anchor.col,
                board.cols - 1 - connector.anchor.col,
                connector.anchor.row,
                board.rows - 1 - connector.anchor.row,
            )
            <= 1
        ), f"{ref} was not put on an edge"

    route = plan_autoroute(placed, lookup)
    assert route.summary.links_unrouted == 0
    assert bus.dispatch("conductor.addMany", route.payload()).ok

    built = bus.document
    errors = [v for v in run_drc(built, lookup) if v.severity == "error"]
    assert errors == [], [v.message for v in errors]
    assert run_lvs(built, lookup).ok
    assert build_guide(built, lookup).total_steps > 0
