"""The System in 3D: every board in the System view's row, and the cables between them.

Building actors touches no GL context -- only a render does -- so none of these is marked
``requires_offscreen_gl``: they hold where the actors go and what colour, not a picture.
"""

from __future__ import annotations

import dataclasses
import math
import os
from itertools import pairwise

import numpy
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from perfboard_studio import system
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import all_pin_holes, board_outline_mm
from perfboard_studio.ui import view3d

from .test_gl import requires_offscreen_gl
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
    # Cut to fit, it hangs down to the bench between the boards, under the boards' tops.
    assert z0 < 0.0


def _ropes(doc, lookup, monkeypatch) -> list[tuple[view3d._Socket, view3d._Socket, list[tuple[float, float, float]]]]:  # type: ignore[no-untyped-def]
    """Each wire's centreline as ``build_cables`` draws it, with the sockets it runs between."""
    drawn: list[tuple[view3d._Socket, view3d._Socket, list[tuple[float, float, float]]]] = []
    rope = view3d._rope

    def spy(start, end, length_mm, ground):  # type: ignore[no-untyped-def]
        points = rope(start, end, length_mm, ground)
        drawn.append((start, end, points))
        return points

    monkeypatch.setattr(view3d, "_rope", spy)
    view3d.build_cables(doc, lookup)
    return drawn


def _length(points: list[tuple[float, float, float]]) -> float:
    return sum(math.dist(p, q) for p, q in pairwise(points))


@pytest.mark.parametrize("length_mm", [195.0, 400.0])
def test_a_cable_is_drawn_as_long_as_it_is(monkeypatch, length_mm: float) -> None:  # type: ignore[no-untyped-def]
    """The pick of three rendered shapes: a wire hangs under its own weight and is drawn
    exactly as long as the cable -- from the top of the shell over its pin to the top of the
    other, straight out of each, never through a board. The pins are 188 mm apart taut: 195 mm
    hangs between the boards, and 400 is more than hanging takes, so the wire lies on the
    bench and the rest of it bows out sideways there."""
    base = _system()
    doc = dataclasses.replace(base, cables=(dataclasses.replace(base.cables[0], length_mm=length_mm),))
    lookup = footprint_lookup()
    ground = view3d._ground(doc, None)
    ropes = _ropes(doc, lookup, monkeypatch)
    assert len(ropes) == 2
    for start, end, points in ropes:
        assert points[0] == pytest.approx(start.at) and points[-1] == pytest.approx(end.at)
        assert start.at[2] == pytest.approx(view3d.DUPONT_SHELL_LENGTH_MM, abs=3.0)
        # Straight up out of the shell before it turns.
        lead = points[: view3d._LEAD_NODES]
        assert [p[:2] for p in lead] == [pytest.approx(start.at[:2])] * len(lead)
        assert lead[-1][2] - start.at[2] == pytest.approx(view3d.CABLE_LEAD_MM * (len(lead) - 1) / len(lead))
        assert _length(points) == pytest.approx(length_mm, rel=0.01)
        xyz = numpy.array(points)
        assert (xyz[:, 2] >= ground.under(xyz[:, :2]) - 0.05).all()
    if length_mm == 400.0:
        # The slack went sideways -- off the boards by their nearest edges, behind them, and
        # not across Main's 75 mm of board the straight way would lie over.
        ys = [p[1] for _s, _e, points in ropes for p in points]
        assert max(ys) - min(ys) > 20.0
        for _s, _e, points in ropes:
            assert view3d._over_boards(numpy.array(points)[:, :2], ground) < 20.0


@pytest.mark.parametrize("length_mm", [None, 10.0, 195.0, 400.0])
def test_a_cable_goes_over_the_parts_and_never_into_one(monkeypatch, length_mm: float | None) -> None:  # type: ignore[no-untyped-def]
    """Drawn in the System, among every part's box: no point of a wire past its lead-outs is
    inside any of them -- it rests on a part, comes over its edge in a curve, and lies on the
    bench, but never passes through."""
    base = _system()
    doc = dataclasses.replace(base, cables=(dataclasses.replace(base.cables[0], length_mm=length_mm),))
    lookup = footprint_lookup()
    seen: list[tuple[list[tuple[float, float, float]], view3d._Ground]] = []
    rope = view3d._rope

    def spy(start, end, length, ground):  # type: ignore[no-untyped-def]
        points = rope(start, end, length, ground)
        seen.append((points, ground))
        return points

    monkeypatch.setattr(view3d, "_rope", spy)
    view3d.populate_system_renderer(view3d.vtk.vtkRenderer(), doc, lookup)
    assert len(seen) == 2
    k = view3d._LEAD_NODES
    for points, ground in seen:
        assert len(ground.boxes) > 10  # every part's box, not the substrates alone
        xyz = numpy.array(points)[k:-k]
        x, y, z = xyz[:, 0:1], xyz[:, 1:2], xyz[:, 2:3]
        b, e = ground.boxes, 0.05
        inside = (
            (x > b[:, 0] + e) & (x < b[:, 1] - e) & (y > b[:, 2] + e) & (y < b[:, 3] - e)
            & (z > b[:, 4] + e) & (z < b[:, 5] - e)
        )
        assert not inside.any(), xyz[inside.any(axis=1)][:3]


def test_the_camera_frames_the_boards_and_lets_a_long_cable_run_off() -> None:
    """Reset Camera fits the boards: a 400 mm cable's slack, out on the bench, frames
    exactly as no cable would, and is still drawn."""
    base = _system()
    doc = dataclasses.replace(base, cables=(dataclasses.replace(base.cables[0], length_mm=400.0),))
    lookup = footprint_lookup()
    ren = view3d.vtk.vtkRenderer()
    view3d.populate_system_renderer(ren, doc, lookup)
    view3d.apply_default_camera(ren)
    with_cable = ren.GetActiveCamera().GetFocalPoint(), ren.GetActiveCamera().GetDistance()
    cables = [actor for actor in view3d._actors(ren) if actor.GetObjectName() == view3d.CABLE_ACTOR_NAME]
    assert len(cables) == 2 + 4 and all(actor.GetVisibility() for actor in cables)
    bare = view3d.vtk.vtkRenderer()
    view3d.populate_system_renderer(bare, dataclasses.replace(doc, cables=()), lookup)
    view3d.apply_default_camera(bare)
    assert with_cable[0] == pytest.approx(bare.GetActiveCamera().GetFocalPoint())
    assert with_cable[1] == pytest.approx(bare.GetActiveCamera().GetDistance())


def test_a_cable_too_short_for_the_row_is_drawn_taut_in_its_own_colours(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A cable shorter than the way between its ends in the System's row is drawn taut along
    it and no longer -- not stretched to the length, and not red: the row is where the view
    put the boards, not where they will be, so a short cable there is a fact about the
    picture (``system.cables_short_in_row``), and the wires keep their colours."""
    base = _system()
    doc = dataclasses.replace(base, cables=(dataclasses.replace(base.cables[0], length_mm=10.0),))
    lookup = footprint_lookup()
    short = system.cables_short_in_row(doc, lookup)
    assert [(cable.ref, round(span, 1)) for cable, span in short] == [
        ("W1", round(system.cable_span_mm(doc, doc.cables[0], lookup) or 0.0, 1))
    ]
    ropes = _ropes(doc, lookup, monkeypatch)
    for start, end, points in ropes:
        # Never under the line between the two lead-outs' tops: taut, not hanging.
        assert min(p[2] for p in points) >= min(start.at[2], end.at[2]) - 0.05
        assert _length(points) > 10.0
    uncut = dataclasses.replace(base, cables=(dataclasses.replace(base.cables[0], length_mm=None),))
    assert system.cables_short_in_row(uncut, lookup) == []
    colours = [actor.GetProperty().GetColor() for actor in view3d.build_cables(doc, lookup)]
    assert colours == [actor.GetProperty().GetColor() for actor in view3d.build_cables(uncut, lookup)]


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
        # A cable shorter than the row's gap is said beside the counts, and counted nowhere.
        from perfboard_studio.commands import UpdateCablePayload

        cable = window.bus.system_document.cables[0]
        result = window.bus.dispatch(
            "cable.update", UpdateCablePayload(cable=dataclasses.replace(cable, length_mm=10.0))
        )
        assert result.ok, result.message
        window._refresh_problems_bar()
        where = window.problems_bar.where.text()
        assert "W1 is 10 mm; its ends are " in where and where.endswith(" mm apart in this row")
        window.bus.undo()
        window._refresh_problems_bar()
        assert "W1" not in window.problems_bar.where.text()

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


def test_every_solid_of_the_system_is_a_boards_or_a_cables() -> None:
    """What a click on the System can land on: every actor drawn belongs to the board it was
    drawn with -- its parts too, since on the System a board is what is picked -- or to the
    cable whose wire or shell it is. Nothing is left without an owner, and nothing is owned
    twice. Each board has one stand-in besides, which is never drawn: its plate is glyphed,
    and a ray cast cannot see a glyph (``view3d._board_stand_in``)."""
    doc = _system()
    ren = view3d.vtk.vtkRenderer()
    owners: dict = {}
    view3d.populate_system_renderer(ren, doc, footprint_lookup(), owners=owners)
    actors = view3d._actors(ren)
    stand_ins = {a: whose for a, whose in owners.items() if a.GetObjectName() == view3d.BOARD_STAND_IN_NAME}
    assert sorted(stand_ins.values()) == [("board", "b2"), ("board", "main")]
    assert not set(stand_ins) & set(actors)
    assert set(owners) - set(stand_ins) == set(actors)
    kinds: dict[tuple[str, str], int] = {}
    for kind, ident in owners.values():
        kinds[(kind, ident)] = kinds.get((kind, ident), 0) + 1
    assert set(kinds) == {("board", "main"), ("board", "b2"), ("cable", "cable-1")}
    assert kinds[("cable", "cable-1")] == 2 + 4  # two tubes and four DuPont shells
    for actor, (kind, _ident) in owners.items():
        assert (actor.GetObjectName() == view3d.CABLE_ACTOR_NAME) == (kind == "cable")


@requires_offscreen_gl
def test_a_click_on_the_system_names_the_board_or_the_cable_it_lands_on() -> None:
    """Through the renderer the window uses: on a board's middle, that board; on the middle
    of a cable's wire, where it lies on the bench between the boards, the cable; on the room,
    nothing."""
    doc = _system()
    owners: dict = {}
    ren = view3d.vtk.vtkRenderer()
    view3d.populate_system_renderer(ren, doc, footprint_lookup(), owners=owners)
    window = view3d.vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.AddRenderer(ren)
    window.SetSize(900, 700)
    view3d.apply_default_camera(ren)
    window.Render()

    def click(x: float, y: float, z: float):  # type: ignore[no-untyped-def]
        ren.SetWorldPoint(x, y, z, 1.0)
        ren.WorldToDisplay()
        px, py, _pz = ren.GetDisplayPoint()
        return view3d.owner_at(ren, owners, round(px), round(py))

    for board_id in ("main", "b2"):
        bounds = [a.GetBounds() for a, whose in owners.items() if whose == ("board", board_id)]
        # The middle of either board is a hole, which still picks the board it is in; half
        # a pitch off it is the plate.
        for nudge in (0.0, 1.27):
            x = (min(b[0] for b in bounds) + max(b[1] for b in bounds)) / 2 + nudge
            y = (min(b[2] for b in bounds) + max(b[3] for b in bounds)) / 2 + nudge
            assert click(x, y, 0.0) == ("board", board_id), nudge

    tube = next(
        a for a, whose in owners.items()
        if whose == ("cable", "cable-1") and a.GetMapper().GetInput().GetNumberOfPoints() > 500
    )
    points = numpy.array(
        [tube.GetMapper().GetInput().GetPoint(i) for i in range(tube.GetMapper().GetInput().GetNumberOfPoints())]
    )
    middle = (points[:, 0].min() + points[:, 0].max()) / 2
    near = points[numpy.abs(points[:, 0] - middle) < 1.0]
    x, y, z = near[near[:, 2].argmax()]
    assert click(x, y, z) == ("cable", "cable-1")

    assert view3d.owner_at(ren, owners, 3, 3) is None
