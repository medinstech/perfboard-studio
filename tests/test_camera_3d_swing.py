"""The 3D camera swings back to the standard view rather than cutting to it
(``view3d.pose_between``, ``MainWindow.on_reset_3d_camera``).

None of this needs a GL context: a ``vtkCamera`` is arithmetic, and the window's render
window is stood in for, so these run on every machine."""

from __future__ import annotations

import math

import pytest
from PySide6.QtWidgets import QApplication

from perfboard_studio.ui import motion

from .test_ui import _close, _load_dense, _settle_events, _window_on


@pytest.fixture(scope="module", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication(["perfboard-studio-tests"])


def _pose(direction, distance=100.0, up=(0.0, 1.0, 0.0), focal=(0.0, 0.0, 0.0), angle=30.0):
    from perfboard_studio.ui import view3d

    n = math.sqrt(sum(c * c for c in direction))
    return view3d.CameraPose(
        focal=focal,
        direction=tuple(c / n for c in direction),
        distance=distance,
        view_up=up,
        view_angle=angle,
    )


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_the_ends_of_a_swing_are_the_two_poses_exactly() -> None:
    from perfboard_studio.ui import view3d

    start = _pose((0.0, 0.0, 1.0))
    end = _pose((1.0, 0.0, 0.0), distance=250.0, focal=(5.0, 2.0, 0.0), angle=20.0)
    assert view3d.pose_between(start, end, 0.0) == start
    assert view3d.pose_between(start, end, 1.0) == end


def test_the_eye_goes_round_the_subject_not_through_it() -> None:
    from perfboard_studio.ui import view3d

    start = _pose((0.0, 0.0, 1.0))
    end = _pose((1.0, 0.0, 0.0))
    half = view3d.pose_between(start, end, 0.5)
    # Halfway round a quarter turn is the eighth: on the sphere, at 45 degrees to both.
    assert math.sqrt(_dot(half.direction, half.direction)) == pytest.approx(1.0)
    assert _dot(half.direction, start.direction) == pytest.approx(math.cos(math.pi / 4))
    assert _dot(half.direction, end.direction) == pytest.approx(math.cos(math.pi / 4))
    for step in range(11):
        pose = view3d.pose_between(start, end, step / 10)
        assert pose.distance == pytest.approx(100.0)
        # Up stays at right angles to the line of sight, as vtkCamera keeps it.
        assert _dot(pose.view_up, pose.direction) == pytest.approx(0.0, abs=1e-9)


def test_a_zoom_changes_by_the_same_ratio_every_frame() -> None:
    from perfboard_studio.ui import view3d

    start = _pose((0.0, 0.0, 1.0), distance=100.0)
    end = _pose((0.0, 0.0, 1.0), distance=400.0)
    assert view3d.pose_between(start, end, 0.5).distance == pytest.approx(200.0)
    assert view3d.pose_between(start, end, 0.25).distance == pytest.approx(100.0 * 4**0.25)


def test_turning_the_board_over_tumbles_it_over_the_top() -> None:
    """Opposite views have no one circle between them; the swing goes through ``up``,
    so the board tumbles over the top of the screen and the eye never meets it."""
    from perfboard_studio.ui import view3d

    start = _pose((0.0, 0.0, 1.0), up=(0.0, 1.0, 0.0))
    end = _pose((0.0, 0.0, -1.0), up=(0.0, -1.0, 0.0))
    half = view3d.pose_between(start, end, 0.5)
    assert half.direction == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)
    for step in range(11):
        pose = view3d.pose_between(start, end, step / 10)
        assert pose.distance == pytest.approx(100.0)
        assert math.sqrt(_dot(pose.direction, pose.direction)) == pytest.approx(1.0)


def test_a_pose_read_off_a_camera_puts_it_back_where_it_was() -> None:
    from vtkmodules.vtkRenderingCore import vtkCamera

    from perfboard_studio.ui import view3d

    cam = vtkCamera()
    cam.SetFocalPoint(12.0, -3.0, 1.5)
    cam.SetPosition(40.0, 20.0, 80.0)
    cam.SetViewUp(0.0, 0.0, 1.0)
    cam.OrthogonalizeViewUp()
    cam.SetViewAngle(25.0)
    pose = view3d.camera_pose(cam)

    other = vtkCamera()
    view3d.set_camera_pose(other, pose)
    assert other.GetFocalPoint() == pytest.approx(cam.GetFocalPoint())
    assert other.GetPosition() == pytest.approx(cam.GetPosition())
    assert other.GetViewUp() == pytest.approx(cam.GetViewUp())
    assert other.GetViewAngle() == pytest.approx(25.0)


class _RenderWindow:
    def __init__(self) -> None:
        self.renders = 0

    def Render(self) -> None:
        self.renders += 1


class _Panel:
    """The 3D widget as far as the camera's swing asks about it."""

    def __init__(self) -> None:
        self.window = _RenderWindow()

    def isVisible(self) -> bool:
        return True

    def GetRenderWindow(self) -> _RenderWindow:
        return self.window


def _window_with_a_camera(monkeypatch):
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.main import MainWindow

    monkeypatch.setattr(MainWindow, "_create_3d_widget", lambda self: None)
    document = _load_dense()
    window = _window_on(document)
    renderer, _stats = view3d.build_renderer(document, footprint_lookup())
    window._vtk_renderer = renderer
    window.vtk_widget = _Panel()
    return window, renderer.GetActiveCamera()


def _standard(window):
    from perfboard_studio.ui import view3d

    view3d.apply_default_camera(window._vtk_renderer, flipped=(window.side == "bottom"))
    return view3d.camera_pose(window._vtk_renderer.GetActiveCamera())


def test_reset_swings_the_camera_back_and_lands_on_the_standard_view(monkeypatch) -> None:
    from perfboard_studio.ui import view3d

    window, cam = _window_with_a_camera(monkeypatch)
    try:
        motion.set_reduced(False)
        standard = _standard(window)
        cam.Azimuth(80)
        cam.Elevation(25)
        cam.OrthogonalizeViewUp()
        orbited = view3d.camera_pose(cam)

        window.on_reset_3d_camera()
        assert window._camera_motion is not None
        # The first frame is where the camera stood, not where it is going.
        assert view3d.camera_pose(cam).direction == pytest.approx(orbited.direction)
        animation = window._camera_motion
        animation.setCurrentTime(animation.duration() // 2)
        midway = view3d.camera_pose(cam)
        assert midway.direction != pytest.approx(orbited.direction, abs=1e-3)
        assert midway.direction != pytest.approx(standard.direction, abs=1e-3)

        window._stop_3d_camera()
        landed = view3d.camera_pose(cam)
        assert landed.direction == pytest.approx(standard.direction, abs=1e-9)
        assert landed.focal == pytest.approx(standard.focal)
        assert landed.distance == pytest.approx(standard.distance)
        assert window._camera_motion is None
    finally:
        _close(window)


def test_a_hand_on_the_camera_stops_the_swing_where_it_stands(monkeypatch) -> None:
    from perfboard_studio.ui import view3d

    window, cam = _window_with_a_camera(monkeypatch)
    try:
        motion.set_reduced(False)
        cam.Azimuth(80)
        window.on_reset_3d_camera()
        animation = window._camera_motion
        assert animation is not None
        animation.setCurrentTime(animation.duration() // 3)
        held = view3d.camera_pose(cam)
        window._stop_3d_camera(land=False)
        _settle_events(QApplication)
        assert view3d.camera_pose(cam) == held
        assert window._camera_motion is None
    finally:
        _close(window)


def test_with_motion_reduced_reset_is_a_cut(monkeypatch) -> None:
    from perfboard_studio.ui import view3d

    window, cam = _window_with_a_camera(monkeypatch)
    try:
        motion.set_reduced(True)
        standard = _standard(window)
        cam.Azimuth(80)
        window.on_reset_3d_camera()
        assert window._camera_motion is None
        assert view3d.camera_pose(cam).direction == pytest.approx(standard.direction)
        assert window.vtk_widget.window.renders >= 1
    finally:
        _close(window)
