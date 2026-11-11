"""How solder looks in 3D: what its buildup and its spine do to the drawn solids."""

from __future__ import annotations

import dataclasses

import pytest

from perfboard_studio.model import (
    Board,
    HoleCoord,
    SolderTraceConductor,
    SpineSpec,
    WireConductor,
)
from perfboard_studio.ui import view3d


def _board() -> Board:
    from .test_ui import _load_dense

    return _load_dense().board


def _run(buildup: str = "normal", wired: bool = False) -> SolderTraceConductor:
    return SolderTraceConductor(
        id="r1",
        path=tuple(HoleCoord(col=c, row=4) for c in range(3, 9)),
        buildup=buildup,  # type: ignore[arg-type]
        kind="solder-trace-wired" if wired else "solder-trace",
        spine=SpineSpec(material="tinned-copper", gauge=0.6) if wired else None,
    )


def test_a_runs_width_and_height_follow_its_buildup() -> None:
    light, normal, heavy = (view3d.conductor_radius(_run(b)) for b in ("light", "normal", "heavy"))
    assert light < normal < heavy
    assert normal == pytest.approx(view3d.TRACE_JOINT_RADIUS_MM)
    # Mild: a heavy joint still sits inside its pad, or the copper that says which pads the
    # run is soldered to is hidden.
    board = _board()
    assert 2 * heavy < board.pad_diameter


def test_the_stacking_step_clears_the_tallest_run() -> None:
    """A heavy run stands higher than a normal one, and a wire lifted over it by one step
    must still clear it."""
    tallest = max(w * h for w, h in view3d.TRACE_BUILDUP.values())
    run = view3d.TRACE_JOINT_RADIUS_MM * view3d.TRACE_FLATTEN * tallest
    assert run + view3d.INSULATED_RADIUS_MM < view3d.STACK_STEP_MM


def test_only_a_wired_run_has_a_spine() -> None:
    board = _board()
    plain = view3d.build_conductor(_run(), board)
    wired = view3d.build_conductor(_run(wired=True), board)
    assert len(wired) == len(plain) + 1


@pytest.mark.parametrize("side", ["bottom", "top"])
def test_a_spine_stands_out_of_the_face_its_run_is_on(side: str) -> None:
    board = _board()
    run = dataclasses.replace(_run(wired=True), side=side)  # type: ignore[type-var]
    spine = view3d.build_conductor(run, board)[-1]
    zmin, zmax = spine.GetBounds()[4:6]
    centre = (zmin + zmax) / 2
    pad = view3d.pad_z(board, side)  # type: ignore[arg-type]
    if side == "bottom":
        assert centre < pad
    else:
        assert centre > pad
    # and it runs past the run's own end pads
    x0, x1 = spine.GetBounds()[0:2]
    first, last = (view3d._xy(board, h)[0] for h in (run.path[0], run.path[-1]))
    assert x0 < min(first, last) and x1 > max(first, last)


@pytest.mark.parametrize("buildup", ["light", "normal", "heavy"])
def test_a_spine_shows_in_the_waists_and_never_stands_above_a_joint(buildup: str) -> None:
    """Solder over a wire: the wire is above the bridge between two pads, so it shows
    there, and below the dome on a pad, so it does not run along the top of the solder."""
    board = _board()
    run = _run(buildup, wired=True)
    spine = view3d.build_conductor(run, board)[-1]
    pad = view3d.pad_z(board, "bottom")
    reaches = pad - spine.GetBounds()[4]  # how far below the pad the spine's far side is
    width, height = view3d.TRACE_BUILDUP[buildup]
    dome = view3d.TRACE_JOINT_RADIUS_MM * width * view3d.TRACE_FLATTEN * height
    bridge = dome * view3d.TRACE_WAIST_RATIO
    assert bridge < reaches < dome


def _wire(kind: str = "insulated-wire", side: str = "bottom") -> WireConductor:
    return WireConductor(
        id="w1",
        path=(HoleCoord(col=2, row=4), HoleCoord(col=9, row=4)),
        kind=kind,  # type: ignore[arg-type]
        side=side,  # type: ignore[arg-type]
    )


def test_a_hookup_wires_copper_goes_on_into_its_hole_past_the_sleeve() -> None:
    board = _board()
    core, sleeve, *_rest = view3d.build_conductor(_wire(), board)
    pad = view3d.pad_z(board, "bottom")
    # Past the pad, into the board (up in z on the solder side, where the board is)...
    assert core.GetBounds()[5] > pad + view3d.WIRE_IN_HOLE_MM - view3d.WIRE_CORE_RADIUS_MM
    # ...and the sleeve is shorter than the core at both ends: stripped.
    assert sleeve.GetBounds()[0] > core.GetBounds()[0] + view3d.WIRE_STRIP_MM - 0.5
    assert sleeve.GetBounds()[1] < core.GetBounds()[1] - view3d.WIRE_STRIP_MM + 0.5


def test_a_short_wire_keeps_a_sleeve() -> None:
    """Two millimetres stripped at each end would leave nothing of a link between two
    neighbouring holes; a third of its length is the most that is stripped."""
    board = _board()
    short = WireConductor(
        id="w2", path=(HoleCoord(col=2, row=4), HoleCoord(col=3, row=4)), kind="insulated-wire"
    )
    assert len(view3d.build_conductor(short, board)) == 3  # core, sleeve, fillets


@pytest.mark.parametrize("side", ["bottom", "top"])
def test_a_wire_stands_off_the_face_it_is_on_and_arcs_away_from_it(side: str) -> None:
    board = _board()
    wire = _wire(side=side)
    pad = view3d.pad_z(board, side)  # type: ignore[arg-type]
    sign = -1.0 if side == "bottom" else 1.0
    z = view3d.conductor_z(wire, board, 0)
    assert sign * (z - pad) == pytest.approx(view3d.HOOKUP_RADIUS_MM + view3d.WIRE_LIFT_MM)
    line = view3d._conductor_centreline(wire, board, z, pad, False)
    heights = [sign * (point[2] - pad) for point in line]
    assert heights[0] == pytest.approx(0.0) and heights[-1] == pytest.approx(0.0)
    assert max(heights) > sign * (z - pad), "a long wire bows up in the middle"
    assert max(heights) <= sign * (z - pad) + view3d.WIRE_ARC_MAX_MM + 1e-9


def test_a_jumper_arcs_more_than_a_wire_and_two_crossing_still_clear() -> None:
    board = _board()
    wire, jumper = _wire(), _wire("top-jumper")
    rise = {}
    for cond in (wire, jumper):
        z = view3d.conductor_z(cond, board, 0)
        pad = view3d.pad_z(board, "bottom")
        line = view3d._conductor_centreline(cond, board, z, pad, False)
        rise[cond.kind] = max(abs(p[2] - pad) for p in line) - abs(z - pad)
    assert rise["top-jumper"] > rise["insulated-wire"]
    # One step clears the highest bow of the lower wire: two radii and a margin remain.
    most = max(view3d.WIRE_ARC_MAX_MM, view3d.JUMPER_ARC_MAX_MM)
    assert view3d.STACK_STEP_MM - most >= 2 * view3d.HOOKUP_RADIUS_MM + 0.1


def test_the_contact_shadows_are_one_unpickable_actor_and_a_run_throws_none() -> None:
    from perfboard_studio.model import PerfDocument

    doc = _load_doc()
    shadows = view3d.build_wire_shadows(doc)
    assert shadows is not None and not shadows.GetPickable()
    runs_only = dataclasses.replace(
        doc, conductors=tuple(c for c in doc.conductors if isinstance(c, SolderTraceConductor))
    )
    assert isinstance(runs_only, PerfDocument)
    assert view3d.build_wire_shadows(runs_only) is None


@pytest.mark.parametrize("preset", ["5 x 7 cm", "6 x 8 cm", "9 x 15 cm"])
def test_solder_on_an_outside_finger_is_drawn_on_the_fingers_copper(preset: str) -> None:
    """A finger is a place one step past the grid, and that address is on its copper on one
    stock board, in the gap beside it on another and 4 mm short on a third. The run is drawn
    where ``geometry.path_point_mm`` says -- the middle of the copper -- and not at the address."""
    from perfboard_studio.boardfamily import STANDARD_PRESETS
    from perfboard_studio.commands import create_empty_document, document_on_preset
    from perfboard_studio.geometry import edge_finger_rect, finger_cells
    from perfboard_studio.model import DocumentMeta

    doc = document_on_preset(
        create_empty_document(DocumentMeta(name="rails", created="", modified="")),
        next(p for p in STANDARD_PRESETS if p.name == preset and p.family == "double-sided-fr4"),
    )
    cells = finger_cells(doc)
    left = sorted((c for c in cells.values() if c.connector.edge == "left"), key=lambda c: c.cell.row)[:3]
    assert len(left) == 3
    run = SolderTraceConductor(id="rail", path=tuple(c.cell for c in left))
    board = doc.board
    rect = edge_finger_rect(left[0].connector, left[0].beside, board)
    for actor in view3d.build_conductor(run, board, cells=cells):
        x0, x1 = actor.GetBounds()[0:2]
        # the run stands over the finger's copper, not out in the border beside it
        assert x0 > rect.x - 0.7 * board.pitch and x1 < rect.x + rect.width + 0.7 * board.pitch
        assert x0 < rect.x + rect.width / 2 < x1


def _load_doc():  # type: ignore[no-untyped-def]
    from .test_ui import _load_dense

    return _load_dense()


def _via_scene():  # type: ignore[no-untyped-def]
    """A run that only ENDS at a hole (``plain``) and a component-side run meeting a
    solder-side run in a pinless hole (``via``), on a blank board."""
    from perfboard_studio.commands import create_empty_document
    from perfboard_studio.model import DocumentMeta

    h = HoleCoord
    plain, via = h(col=3, row=4), h(col=9, row=4)
    doc = create_empty_document(DocumentMeta(name="via", created="", modified=""))
    doc = dataclasses.replace(
        doc,
        conductors=(
            SolderTraceConductor(id="a", path=(h(col=3, row=2), h(col=3, row=3), plain), side="top"),
            SolderTraceConductor(id="b", path=(h(col=9, row=2), h(col=9, row=3), via), side="top"),
            SolderTraceConductor(id="c", path=(via, h(col=10, row=4), h(col=11, row=4)), side="bottom"),
        ),
    )
    return doc, plain, via


def _glyph_points(actor):  # type: ignore[no-untyped-def]
    points = actor.GetMapper().GetInputDataObject(0, 0).GetPoints()
    return [points.GetPoint(i) for i in range(points.GetNumberOfPoints())]


def test_a_via_gets_a_plug_and_a_rim_on_each_face_and_a_plain_run_end_gets_none() -> None:
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.occupancy import build_occupancy
    from perfboard_studio.wiringstats import vias

    doc, plain, via = _via_scene()
    board = doc.board
    found = vias(doc, build_occupancy(doc, footprint_lookup()))
    assert found == (via,)

    plug, rim = view3d.build_via_marks(board, found)
    here = (round(via.col * board.pitch, 3), round(-via.row * board.pitch, 3))
    there = (round(plain.col * board.pitch, 3), round(-plain.row * board.pitch, 3))
    for actor in (plug, rim):
        points = _glyph_points(actor)
        assert len(points) == 2  # one per face, for the one via
        assert {(round(x, 3), round(y, 3)) for x, y, _ in points} == {here}
        # One on each face: the plug's centre stands out of its face, the rim lies on the copper.
        assert sorted(z > -board.thickness / 2 for _, _, z in points) == [False, True]
        assert there not in {(round(x, 3), round(y, 3)) for x, y, _ in points}


def test_a_board_with_no_via_gets_no_marks() -> None:
    doc, _plain, _via = _via_scene()
    assert view3d.build_via_marks(doc.board, ()) == []


def test_the_scene_marks_the_engines_vias_and_only_those() -> None:
    import vtk

    from perfboard_studio.footprints import footprint_lookup

    doc, _plain, _via = _via_scene()
    lookup = footprint_lookup()
    # Without the solder-side run, the same hole is only where a run ends.
    without = dataclasses.replace(doc, conductors=doc.conductors[:2])
    marked, unmarked = vtk.vtkRenderer(), vtk.vtkRenderer()
    view3d.populate_renderer(marked, doc, lookup)
    view3d.populate_renderer(unmarked, without, lookup)
    from_run = len(view3d.build_conductor(doc.conductors[2], doc.board))
    # The plug and the rim, besides the solder-side run's own actors.
    assert marked.GetActors().GetNumberOfItems() - unmarked.GetActors().GetNumberOfItems() == 2 + from_run
