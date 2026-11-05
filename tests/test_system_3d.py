"""The System in 3D: every board in the System view's row, and the cables between them.

Building actors touches no GL context -- only a render does -- so none of these is marked
``requires_offscreen_gl``: they hold where the actors go and what colour, not a picture.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from perfboard_studio import system
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import all_pin_holes, board_outline_mm
from perfboard_studio.ui import view3d

from .test_system_readers import _system


@pytest.fixture(scope="module")
def qapp():  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _bounds(ren) -> tuple[float, ...]:  # type: ignore[no-untyped-def]
    return tuple(ren.ComputeVisiblePropBounds())


def test_the_system_is_each_board_as_drawn_alone_moved_along_the_row() -> None:
    """One way to draw a board: the System's 3D is each board's own drawing, moved by
    ``board_row``, and the cables -- nothing dropped, nothing drawn twice."""
    doc = _system()
    lookup = footprint_lookup()
    alone: dict[str, tuple[int, tuple[float, ...]]] = {}
    for board_id in system.board_ids(doc):
        ren = view3d.vtk.vtkRenderer()
        stats = view3d.populate_renderer(ren, system.board_document(doc, board_id), lookup)
        alone[board_id] = (stats["actors"], _bounds(ren))
    together = view3d.vtk.vtkRenderer()
    stats = view3d.populate_system_renderer(together, doc, lookup)
    cables = view3d.build_cables(doc, lookup)
    # Two wires between two pin headers: a tube each, and a DuPont shell at each end.
    assert len(cables) == 2 + 4
    assert stats["actors"] == sum(count for count, _b in alone.values()) + len(cables)
    # Each board moved by its place in the row -- and Remote, Main's twin, Main's width and
    # the bench further along.
    row = system.board_row(doc)
    width = board_outline_mm(doc.board).width
    x0, x1, y0, y1 = _bounds(together)[:4]
    assert x0 == pytest.approx(alone["main"][1][0] + row["main"][0])
    assert x1 == pytest.approx(alone["b2"][1][1] + row["b2"][0])
    assert row["b2"][0] - row["main"][0] == pytest.approx(width + system.BOARD_GAP_MM)
    assert (y0, y1) == pytest.approx((alone["main"][1][2] - row["main"][1], alone["main"][1][3] - row["main"][1]))


def test_a_cable_wire_runs_from_its_pin_to_its_pin_in_the_colour_it_is_cut_in() -> None:
    """W1's SIG wire leaves JA's pin 1 on Main and lands on JB's pin 1 on Remote, out of the
    DuPont shells on both, in yellow -- the first signal colour, the cut list's."""
    from PySide6.QtGui import QColor

    doc = _system()
    lookup = footprint_lookup()
    row = system.board_row(doc)
    header = lookup("hdr-1x2")
    assert header is not None

    def pin_one_x(board_id: str, ref: str) -> float:
        part = next(c for c in system.board_document(doc, board_id).components if c.ref == ref)
        hole = next(hole for pin, hole in all_pin_holes(part, header) if pin.number == "1")
        return hole.col * doc.board.pitch + row[board_id][0]

    def finished(rgb: tuple[float, float, float]) -> tuple[float, ...]:
        """The colour a wire of ``rgb`` is given once its material is applied."""
        piece = view3d._Piece(
            source=view3d._box(1.0, 1.0, 1.0), rgb=rgb, position=(0.0, 0.0, 0.0), material=view3d.INSULATION
        )
        return tuple(view3d._actor_for(piece).GetProperty().GetColor())

    yellow = QColor("#e2c541")
    actors = view3d.build_cables(doc, lookup)
    # A shell is 2.5 mm across; a wire runs from one board to the other.
    tubes = [actor for actor in actors if actor.GetBounds()[1] - actor.GetBounds()[0] > 10]
    assert len(tubes) == 2 and len(actors) - len(tubes) == 4
    sig = next(
        actor
        for actor in tubes
        if actor.GetProperty().GetColor()
        == pytest.approx(finished((yellow.redF(), yellow.greenF(), yellow.blueF())), abs=1e-3)
    )
    x0, x1, _y0, _y1, z0, _z1 = sig.GetBounds()
    radius = view3d.INSULATED_RADIUS_MM
    assert x0 == pytest.approx(pin_one_x("main", "JA") - radius, abs=0.1)
    assert x1 == pytest.approx(pin_one_x("b2", "JB") + radius, abs=0.1)
    # It starts at the top of the shell over the pin, not on the board.
    assert z0 == pytest.approx(view3d.DUPONT_SHELL_LENGTH_MM, abs=3.0)


def test_with_system_in_front_the_3d_panel_draws_every_board_and_frames_them(  # type: ignore[no-untyped-def]
    qapp, monkeypatch
) -> None:
    """Picking System puts every board and the cables in the 3D panel and frames them; an
    edit there leaves the camera where it was; picking a board puts it back alone, framed,
    and the assembly bar stood down for the System comes back."""
    from perfboard_studio.commands import MoveComponentPayload
    from perfboard_studio.model import HoleCoord
    from perfboard_studio.ui.boardstrip import SYSTEM_ENTRY
    from perfboard_studio.ui.main import MainWindow

    monkeypatch.setattr(MainWindow, "_create_3d_widget", lambda self: None)
    window = MainWindow(_system())

    class _RenderWindow:
        def Render(self) -> None:
            pass

    class _Widget:
        def GetRenderWindow(self) -> _RenderWindow:
            return _RenderWindow()

    try:
        window.vtk_widget = _Widget()
        window._vtk_renderer = view3d.vtk.vtkRenderer()
        bar = window._build_assembly_bar()
        window._3d_layout.addWidget(bar)
        window.show()
        window._raise_view(window.dock_3d)
        window._refresh_3d()
        ren = window._vtk_renderer
        one_board = ren.GetActors().GetNumberOfItems()
        assert window._3d_subject == system.FIRST_BOARD

        window.board_strip.tabs.setCurrentIndex(0)  # System
        window._refresh_3d()
        assert window._3d_subject == SYSTEM_ENTRY
        expected = view3d.populate_system_renderer(
            view3d.vtk.vtkRenderer(), window.bus.system_document, window.lookup
        )["actors"]
        assert ren.GetActors().GetNumberOfItems() == expected > 2 * one_board
        x0, x1 = _bounds(ren)[:2]
        assert ren.GetActiveCamera().GetFocalPoint()[0] == pytest.approx((x0 + x1) / 2, abs=1.0)
        assert not bar.isEnabled() and window._assembly_index() is None

        camera = ren.GetActiveCamera()
        camera.Azimuth(40)
        orbited = camera.GetPosition()
        result = window.bus.dispatch(
            "component.move", MoveComponentPayload(id="cmp-2", anchor=HoleCoord(4, 9))
        )
        assert result.ok, result.message
        window._refresh_3d()
        assert camera.GetPosition() == orbited

        window.board_strip.tabs.setCurrentIndex(1)  # Main
        window._refresh_3d()
        assert window._3d_subject == system.FIRST_BOARD
        assert ren.GetActors().GetNumberOfItems() == one_board
        assert camera.GetPosition() != orbited
        assert bar.isEnabled()
    finally:
        window._3d_refresh_timer.stop()
        window._mark_saved()
        window.close()
        window.deleteLater()
