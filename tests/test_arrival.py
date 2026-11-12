"""Play lowers each part into its holes.

The drop is the stage's own business (``ui/arrival.py``: actors moved, nothing rebuilt per
frame); the window's part is when one starts and when it is finished early. What looks
right is a question for a render, the frame strip in the change that added this; what is
pinned here is the seams -- which moves of the slider arrive, which do not, what a new
input does to a drop in the air, and that the picture a drop ends on is the ordinary one.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.guide import PartStep
from perfboard_studio.ui import arrival

from .test_ui import _close, _load_dense, _window_on

vtk = pytest.importorskip("vtk")


@pytest.fixture(scope="session", autouse=True)
def _app():
    """The windows below need an application, and ``test_ui``'s own is autouse in ITS module
    only: this file alone would abort the process on the first widget."""
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


class _Actor:
    """Just what the animation asks of an actor."""

    def __init__(self, z: float, zmin: float) -> None:
        self.position = (1.0, 2.0, z)
        self.zmin = zmin

    def GetPosition(self) -> tuple[float, float, float]:
        return self.position

    def SetPosition(self, x: float, y: float, z: float) -> None:
        self.position = (x, y, z)

    def GetBounds(self) -> tuple[float, float, float, float, float, float]:
        return (0.0, 1.0, 0.0, 1.0, self.zmin, self.zmin + 5.0)


def test_a_part_starts_with_its_lowest_point_fifteen_millimetres_above_the_board() -> None:
    """The LOWEST point, because a lead tip under the board is the part's lowest: measuring
    from the body would start a long-legged part with its legs through the plate."""
    body, lead = _Actor(0.0, 1.6), _Actor(0.0, -3.0)
    lift = arrival.start_lift_mm([body, lead], board_top_z=1.6)
    assert lift == pytest.approx(1.6 + arrival.ARRIVAL_HEIGHT_MM + 3.0)
    assert arrival.start_lift_mm([], board_top_z=1.6) == 0.0


def test_the_drop_eases_out_and_lands_exactly_where_the_part_was() -> None:
    assert arrival.ease_out_cubic(0.0) == 0.0 and arrival.ease_out_cubic(1.0) == 1.0
    assert arrival.ease_out_cubic(0.5) > 0.5, "fast at first, gentle at the end"
    actors = [_Actor(4.0, 1.0), _Actor(7.0, 2.0)]
    drop = arrival.ArrivalAnimation()
    assert drop.start(actors, 10.0, lambda: None)
    assert [a.position[2] for a in actors] == [14.0, 17.0], "at the top, the same 10 mm up"
    drop.show(0.5)
    assert 4.0 < actors[0].position[2] < 14.0
    drop.show(1.0)
    assert [a.position for a in actors] == [(1.0, 2.0, 4.0), (1.0, 2.0, 7.0)]
    drop.cancel()


def test_a_drop_ends_with_a_signal_and_a_cancelled_one_does_not() -> None:
    landed: list[int] = []
    drop = arrival.ArrivalAnimation(duration_ms=20)
    drop.finished.connect(lambda: landed.append(1))
    renders: list[int] = []
    assert drop.start([_Actor(0.0, 0.0)], 5.0, lambda: renders.append(1))
    _pump_until(lambda: not drop.running)
    assert landed == [1] and renders, "a frame was asked for, and the landing was announced"

    assert drop.start([_Actor(0.0, 0.0)], 5.0, lambda: None)
    drop.cancel()
    _pump_until(lambda: False, seconds=0.1)
    assert landed == [1] and not drop.running, "cancelling lets go without a word"
    assert not drop.start([], 5.0, lambda: None), "nothing to lower, nothing runs"
    assert not drop.start([_Actor(0.0, 0.0)], 0.0, lambda: None), "already down"


def _pump_until(done, *, seconds: float = 3.0) -> None:
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end and not done():
        QCoreApplication.processEvents()
        time.sleep(0.005)


def test_the_arriving_part_has_no_solder_until_it_lands() -> None:
    """A fillet round a lead that is still in the air would say the joint was made. The
    part's solids -- and nothing of its neighbours' -- are what is reported to lower."""
    from perfboard_studio.guide import all_steps, build_guide, step_focus
    from perfboard_studio.ui import view3d

    doc = _load_dense()
    lookup = footprint_lookup()
    steps = all_steps(build_guide(doc, lookup))
    step = next(s for s in steps if isinstance(s, PartStep))
    focus = step_focus(step)

    plain, arriving, owners = vtk.vtkRenderer(), vtk.vtkRenderer(), {}
    lowered: list = []
    a = view3d.populate_renderer(plain, doc, lookup, highlight=focus)
    b = view3d.populate_renderer(
        arriving, doc, lookup, highlight=focus, arriving=lowered, owners=owners
    )
    assert lowered and {owners[actor] for actor in lowered} == {("component", focus)}
    assert b["actors"] == a["actors"], "the same actors, solder aside"
    assert _fillets(arriving) < _fillets(plain), "its leads have no fillet yet"


def _fillets(renderer) -> int:
    """How many solder fillets the renderer holds: the points of the instanced actor."""
    from perfboard_studio.ui import view3d

    count = 0
    for actor in renderer.GetActors():
        if actor.GetObjectName() == view3d.JOINTS_ACTOR_NAME:
            count += actor.GetMapper().GetInput().GetNumberOfPoints()
    return count


def _stage(monkeypatch):
    """A window with the build bar, a renderer the animation can move actors in, and a
    window that counts the frames it is asked for."""
    window = _window_on(_load_dense())
    window._3d_layout.addWidget(window._build_assembly_bar())
    frames: list[int] = []

    class _Win:
        def Render(self) -> None:
            frames.append(1)

    class _Widget:
        def GetRenderWindow(self) -> _Win:
            return _Win()

    window.vtk_widget = _Widget()
    window._vtk_renderer = vtk.vtkRenderer()
    monkeypatch.setattr(window.dock_3d, "isVisible", lambda: True)
    steps = window._assembly_steps()
    part_at = next(i for i, s in enumerate(steps) if isinstance(s, PartStep))
    # Standing on the step before the first part, so one step forward fits it.
    window._move_assembly(part_at, arrive=False)
    return window, frames, part_at


def _close_stage(window) -> None:
    window.vtk_widget = None
    window._vtk_renderer = None
    _close(window)


def test_a_step_forward_lowers_its_part_and_lands_it_as_the_ordinary_picture(monkeypatch) -> None:
    window, frames, _ = _stage(monkeypatch)
    window.step_assembly(1)
    drop = window._arrival
    assert drop is not None and drop.running
    in_the_air = _fillets(window._vtk_renderer)
    drop.duration_ms = 10
    _pump_until(lambda: not drop.running)
    assert frames, "the window was asked for frames while it came down"
    assert _fillets(window._vtk_renderer) > in_the_air, "on landing it is drawn again, soldered"
    _close_stage(window)


def test_a_step_back_a_drag_and_an_edit_are_instant(monkeypatch) -> None:
    window, _, part_at = _stage(monkeypatch)
    window.step_assembly(-1)
    assert window._arrival is None or not window._arrival.running
    window.assembly_slider.setValue(part_at + 1)  # a drag lands on the part's step
    assert window._arrival is None or not window._arrival.running
    window.step_assembly(1)
    assert window._arrival.running
    window._refresh_3d()  # an edit's redraw replaces the actors the drop was moving
    assert not window._arrival.running
    _close_stage(window)


def test_a_new_input_finishes_the_drop_in_the_air(monkeypatch) -> None:
    window, _, _ = _stage(monkeypatch)
    window.step_assembly(1)
    first = window._arrival
    assert first.running
    window.step_assembly(-1)
    assert not first.running, "stepping back landed it and went back"
    window.step_assembly(1)
    assert first.running
    window._finish_arrival()
    assert not first.running
    _close_stage(window)


def test_play_waits_for_the_drop_and_then_holds(monkeypatch) -> None:
    window, _, part_at = _stage(monkeypatch)
    window.act_play.setChecked(True)  # from the finished board: starts over at the bare one
    assert window._assembly_timer.interval() == window.ASSEMBLY_FRAME_MS
    window._move_assembly(part_at, arrive=False)
    window._assembly_timer.stop()  # it was this timer's firing that is being played out
    window._on_assembly_tick()
    assert window._arrival.running
    assert not window._assembly_timer.isActive(), "the drop is what Play waits for"
    window._arrival.duration_ms = 10
    _pump_until(lambda: not window._arrival.running)
    assert window._assembly_timer.interval() == window.ARRIVAL_HOLD_MS
    assert window._assembly_timer.isActive()
    window.act_play.setChecked(False)
    assert not window._assembly_timer.isActive()
    _close_stage(window)


def test_play_goes_on_when_a_redraw_replaces_the_part_that_was_coming_down(monkeypatch) -> None:
    """A redraw that is not a landing (an edit, the exploded view) cancels the drop without
    its signal, and Play was waiting for the signal: it stood still with its button down."""
    window, _, part_at = _stage(monkeypatch)
    window.act_play.setChecked(True)
    window._move_assembly(part_at, arrive=False)
    window._assembly_timer.stop()
    window._on_assembly_tick()
    assert window._arrival.running and not window._assembly_timer.isActive()
    window._refresh_3d()
    assert not window._arrival.running
    assert window._assembly_timer.isActive()
    window.act_play.setChecked(False)
    _close_stage(window)


def test_a_forward_step_over_a_running_drop_draws_once(monkeypatch) -> None:
    """The step that finishes a drop and moves the slider is ONE redraw, not the finishing
    one and then the new step's."""
    window, _, _ = _stage(monkeypatch)
    window.step_assembly(1)
    assert window._arrival.running
    draws: list[bool] = []
    real = type(window)._refresh_3d

    def counted(self, *, arrive=False):
        draws.append(arrive)
        return real(self, arrive=arrive)

    monkeypatch.setattr(type(window), "_refresh_3d", counted)
    window.step_assembly(1)
    assert len(draws) == 1
    _close_stage(window)


def test_pausing_lands_the_part_that_is_coming_down(monkeypatch) -> None:
    window, _, part_at = _stage(monkeypatch)
    window.act_play.setChecked(True)
    window._move_assembly(part_at, arrive=False)
    window._on_assembly_tick()
    assert window._arrival.running
    window.act_play.setChecked(False)
    assert not window._arrival.running
    _close_stage(window)


def test_the_exploded_view_has_nothing_to_lower(monkeypatch) -> None:
    window, _, _ = _stage(monkeypatch)
    window.act_exploded.setChecked(True)
    window.step_assembly(1)
    assert window._arrival is None or not window._arrival.running
    _close_stage(window)
