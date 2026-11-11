"""How solder looks in 3D: what its buildup and its spine do to the drawn solids."""

from __future__ import annotations

import dataclasses

import pytest

from perfboard_studio.model import (
    Board,
    HoleCoord,
    SolderTraceConductor,
    SpineSpec,
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
