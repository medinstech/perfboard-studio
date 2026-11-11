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


def _load_doc():  # type: ignore[no-untyped-def]
    from .test_ui import _load_dense

    return _load_dense()
