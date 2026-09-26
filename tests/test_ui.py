"""Tests for perfboard_studio.ui.

Runs entirely headless (QT_QPA_PLATFORM=offscreen, set before PySide6 is imported) so
it works in CI with no display. The load-bearing tests here are the ones that would
catch the two failure modes this rewiring exists to prevent:

  - a UI-side model drifting from the engine (test_scene_item_counts_match_document,
    test_solder_trace_beads_every_hole_wire_fillets_ends): the scene must be built
    purely from a real PerfDocument and the engine's own contacts_every_path_hole
    predicate, never a re-derived copy of either.
  - a mutation that bypasses the command bus (test_drag_dispatches_component_move_*,
    test_undo_after_move_restores_previous_anchor, test_off_board_move_is_refused_*):
    every assertion here is against bus.document, never the scene's items, because the
    scene is only ever a view of that document.
  - the board being drawn backwards (test_hole_screen_round_trip_both_sides): mirroring
    must reflect about geometry.hole_span_mm, not board_size_mm (see the long comment
    on hole_span_mm in geometry.py and the one on hole_to_screen in view2d.py).
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import MoveComponentPayload, create_standard_registry
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import column_label
from perfboard_studio.model import (
    Board,
    HoleCoord,
    PerfDocument,
    SolderTraceConductor,
    WireConductor,
    contacts_every_path_hole,
)
from perfboard_studio.ui import scenetext, view2d
from perfboard_studio.ui.export_pdf import verify_scale
from perfboard_studio.ui.main import (
    ROLE_NET_ID,
    _rotation_after,
    guess_footprint_id,
    read_document_text,
    window_title,
)
from perfboard_studio.ui.view2d import (
    BoardScene,
    ComponentItem,
    ConductorItem,
    hole_to_screen,
    next_reference,
    screen_to_hole,
)
from perfboard_studio.version import __version__
from perfboard_studio.version import describe as describe_version

from .test_gl import requires_offscreen_gl

GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "tools" / "diffcheck" / "golden" / "dense.perf"


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication(["perfboard-studio-tests"])
    yield app


@pytest.fixture(autouse=True)
def _settings_in_a_temp_file(tmp_path, monkeypatch):
    """Keep the recent-file list AND the saved session out of the real user store.

    A test suite has no business writing into somebody's registry, and one that did would
    also make these tests depend on whatever ran before them -- including on the developer
    having opened a board that morning. Since the window now saves its layout on close,
    and every test here closes a window, this fixture is what stands between the suite and
    the developer's own window geometry.
    """
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "recent.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    yield store


@pytest.fixture(autouse=True)
def _recovery_in_a_temp_dir(tmp_path, monkeypatch):
    """Keep autosave records out of the real user data directory.

    The same argument as ``_settings_in_a_temp_file`` above and one step sharper: every
    window built here constructs an ``Autosave``, and closing one deletes its record, so
    without this the suite would be creating and unlinking files in the developer's own
    profile -- in the one directory whose whole purpose is to hold work that must not be
    lost.
    """
    from perfboard_studio.ui import autosave as autosave_module

    directory = tmp_path / "recovery"
    monkeypatch.setattr(autosave_module, "default_directory", lambda: directory)
    yield directory


def _load_dense() -> PerfDocument:
    text = GOLDEN.read_text(encoding="utf-8")
    result = persist.deserialize_document(text)
    assert result.ok, f"golden fixture failed to load: {result}"
    assert not result.warnings, f"unexpected warnings loading golden fixture: {result.warnings}"
    return result.document


def _golden_document(name: str) -> PerfDocument:
    """Any fixture from the golden set, for the tests that sweep all fifteen."""
    result = persist.deserialize_document(
        (GOLDEN.parent / f"{name}.perf").read_text(encoding="utf-8")
    )
    assert result.ok, f"{name}.perf failed to load: {result}"
    return result.document


def _new_bus(document: PerfDocument) -> CommandBus:
    return CommandBus(document, create_standard_registry(), CommandContext(next_id=create_id_generator()))


def _drag(scene: BoardScene, comp_id: str, new_anchor: HoleCoord) -> list:
    """Simulates a drag-and-release without synthesizing real Qt mouse events:
    ``setPos`` on an item with ItemSendsGeometryChanges set runs exactly the same
    ``itemChange`` snapping code a live drag would, and ``commit_pending_moves`` is the
    same method ``mouseReleaseEvent`` calls.
    """
    item = scene.component_items[comp_id]
    board = scene.document.board
    item.setPos(hole_to_screen(new_anchor, board, scene.side))
    return scene.commit_pending_moves()


# ---------------------------------------------------------------------------
# Scene built from the real document, not a parallel model
# ---------------------------------------------------------------------------


def test_scene_item_counts_match_document() -> None:
    doc = _load_dense()
    lookup = footprint_lookup()
    scene = BoardScene(doc, lookup, side="top")

    # dense.perf deliberately includes one component ("X11", footprint "c-disc-1")
    # whose footprint id is not in the standard registry -- test_drc.py, test_lvs.py
    # and test_connectivity.py all load this same fixture through this same
    # footprint_lookup() and rely on exactly this to exercise their own
    # unknown-footprint handling. The scene must skip it the same way DRC/LVS/
    # connectivity do (never render an item it has no footprint geometry for), so the
    # item count is checked against the RESOLVABLE components, not the raw count.
    resolvable = [c for c in doc.components if lookup(c.footprint_id) is not None]
    assert len(resolvable) < len(doc.components), "fixture no longer exercises the unknown-footprint case"

    assert len(scene.component_items) == len(resolvable)
    component_items = [it for it in scene.items() if isinstance(it, ComponentItem)]
    assert len(component_items) == len(resolvable)
    conductor_items = [it for it in scene.items() if isinstance(it, ConductorItem)]
    assert len(conductor_items) == len(doc.conductors)


# ---------------------------------------------------------------------------
# Every mutation through the command bus
# ---------------------------------------------------------------------------


def test_drag_dispatches_component_move_and_changes_document() -> None:
    doc = _load_dense()
    lookup = footprint_lookup()
    bus = _new_bus(doc)
    scene = BoardScene(bus.document, lookup, side="top", bus=bus)

    comp_id = doc.components[0].id
    original_anchor = doc.components[0].anchor
    new_anchor = HoleCoord(original_anchor.col + 1, original_anchor.row)

    results = _drag(scene, comp_id, new_anchor)

    assert len(results) == 1
    assert results[0].ok, results[0].message
    assert results[0].description  # human-readable, e.g. "Move X1 to U17"

    # Assert against the BUS's document, never the scene's items.
    moved = next(c for c in bus.document.components if c.id == comp_id)
    assert moved.anchor == new_anchor
    assert bus.document is not doc  # a new document, never a mutation of the old one
    original_still = next(c for c in doc.components if c.id == comp_id)
    assert original_still.anchor == original_anchor  # the old document is untouched


def test_undo_after_move_restores_previous_anchor() -> None:
    doc = _load_dense()
    lookup = footprint_lookup()
    bus = _new_bus(doc)
    scene = BoardScene(bus.document, lookup, side="top", bus=bus)

    comp_id = doc.components[0].id
    original_anchor = doc.components[0].anchor
    new_anchor = HoleCoord(original_anchor.col + 1, original_anchor.row)

    results = _drag(scene, comp_id, new_anchor)
    assert results[0].ok

    restored = bus.undo()
    moved_back = next(c for c in restored.components if c.id == comp_id)
    assert moved_back.anchor == original_anchor


def test_off_board_move_is_refused_and_document_unchanged() -> None:
    doc = _load_dense()
    bus = _new_bus(doc)
    comp_id = doc.components[0].id

    result = bus.dispatch("component.move", MoveComponentPayload(id=comp_id, anchor=HoleCoord(doc.board.cols + 5, 0)))

    assert result.ok is False
    assert result.code == "off-board"
    assert bus.document is doc  # completely unchanged: not even a fresh equal copy


@pytest.mark.parametrize("anchor", [HoleCoord(-3, 0), HoleCoord(0, -3), HoleCoord(-1, -1)])
def test_a_nudge_past_the_top_or_left_edge_is_refused_not_raised(anchor: HoleCoord) -> None:
    """The negative directions get their own case because they used to be the dangerous
    ones: the refusal message was formatted with the strict hole encoder, which rejects a
    negative column by design, so the check crashed on exactly what it exists to report.
    Arrow-key nudging makes single-step negative moves easy to reach, so it is pinned here
    as well as in test_commands.py.
    """
    doc = _load_dense()
    bus = _new_bus(doc)

    result = bus.dispatch("component.move", MoveComponentPayload(id=doc.components[0].id, anchor=anchor))

    assert result.ok is False
    assert result.code == "off-board"
    assert bus.document is doc


def test_locked_component_move_is_refused_via_the_bus() -> None:
    """The UI deliberately leaves locked components draggable (see the note in
    ComponentItem.__init__) so this refusal path is reachable and its message can be
    surfaced, rather than the item flags silently preventing the attempt.
    """
    doc = _load_dense()
    from dataclasses import replace

    target = doc.components[0]
    locked_components = tuple(replace(c, locked=True) if c.id == target.id else c for c in doc.components)
    locked_doc = replace(doc, components=locked_components)
    bus = _new_bus(locked_doc)

    new_anchor = HoleCoord(target.anchor.col + 1, target.anchor.row)
    result = bus.dispatch("component.move", MoveComponentPayload(id=target.id, anchor=new_anchor))

    assert result.ok is False
    assert result.code == "component-locked"
    assert bus.document is locked_doc


# ---------------------------------------------------------------------------
# Mirroring: the test that catches a board drawn backwards
# ---------------------------------------------------------------------------


def test_hole_screen_round_trip_both_sides() -> None:
    doc = _load_dense()
    board = doc.board
    for side in ("top", "bottom"):
        for col in range(board.cols):
            for row in range(board.rows):
                hole = HoleCoord(col, row)
                point = hole_to_screen(hole, board, side)
                assert screen_to_hole(point, board, side) == hole, f"{side} round-trip failed for {hole}"


def test_bottom_side_actually_reflects_about_hole_span_not_board_size() -> None:
    """A sharper version of the round-trip test: pins down that the reflection axis is
    hole_span_mm, not board_size_mm, by checking a concrete pair of holes rather than
    only checking self-consistency (a bug that reflects consistently about the WRONG
    axis would still pass a pure round-trip check).
    """
    from perfboard_studio.geometry import board_size_mm, hole_span_mm

    doc = _load_dense()
    board = doc.board
    span_w, _ = hole_span_mm(board)
    size_w, _ = board_size_mm(board)
    assert span_w != size_w  # the whole point: they differ by half a pitch

    first = hole_to_screen(HoleCoord(0, 5), board, "bottom")
    last = hole_to_screen(HoleCoord(board.cols - 1, 5), board, "bottom")
    assert first.x() == pytest.approx((board.cols - 1) * board.pitch)
    assert last.x() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 1:1 print scale
# ---------------------------------------------------------------------------


def test_scale_check_passes_exactly() -> None:
    doc = _load_dense()
    lookup = footprint_lookup()
    scene = BoardScene(doc, lookup, side="top")

    check = verify_scale(scene, doc.board)

    assert check.ok
    assert check.error_mm == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# The heart of the model: beads vs. fillets
# ---------------------------------------------------------------------------


def test_solder_trace_beads_every_hole_wire_fillets_ends_only() -> None:
    board = Board(
        type="pad-per-hole",
        cols=10,
        rows=10,
        pitch=2.54,
        thickness=1.6,
        material="FR4",
        pad_diameter=1.9,
        drill_diameter=1.0,
    )
    path = (HoleCoord(2, 2), HoleCoord(3, 2), HoleCoord(4, 2), HoleCoord(4, 3))
    trace = SolderTraceConductor(id="cond-t", path=path, buildup="normal")
    wire = WireConductor(id="cond-w", path=path, kind="bare-wire", side="bottom")

    trace_item = ConductorItem(trace, board, "top")
    wire_item = ConductorItem(wire, board, "top")

    assert len(trace_item.contact_points()) == len(path) == 4
    assert len(wire_item.contact_points()) == 2

    expected_ends = [hole_to_screen(path[0], board, "top"), hole_to_screen(path[-1], board, "top")]
    assert wire_item.contact_points() == expected_ends


# ---------------------------------------------------------------------------
# Labels: the failure mode here is SILENCE
# ---------------------------------------------------------------------------
#
# Qt draws nothing, and reports nothing, when a font ends up too small for its engine --
# and text on a millimetre-scaled painter is asked for in fractions of a point, which lands
# there easily. That is how the component references in this editor came to be specified,
# drawn, and invisible. So these tests do not check a colour or a position; they render and
# count marked pixels, because a label that fails to appear is the bug.


def _render_scene(scene: BoardScene, px_per_mm: int = 12) -> QImage:
    rect = scene.sceneRect()
    image = QImage(
        int(rect.width() * px_per_mm), int(rect.height() * px_per_mm), QImage.Format.Format_ARGB32
    )
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), rect)
    painter.end()
    return image


def _pixels_matching(image: QImage, colour: QColor, tolerance: int = 26) -> int:
    """Pixels close to `colour`. Antialiased text never lands on the exact value."""
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if (
                abs(pixel.red() - colour.red()) <= tolerance
                and abs(pixel.green() - colour.green()) <= tolerance
                and abs(pixel.blue() - colour.blue()) <= tolerance
            ):
                count += 1
    return count


@pytest.mark.skipif(
    QApplication.instance() is not None
    and QApplication.instance().platformName() == "offscreen"  # type: ignore[union-attr]
    and sys.platform == "win32",
    reason="Qt's offscreen plugin ships no font database on Windows, so no text can render; "
    "see main._default_headless_platform",
)
def test_hole_address_rulers_actually_draw_text() -> None:
    """The rulers are how a user finds the hole a DRC message or the build guide names, so
    'the item painted' is not the claim -- 'letters reached the pixels' is."""
    document = _load_dense()
    with_rulers = _render_scene(BoardScene(document, footprint_lookup(), show_rulers=True))
    without = _render_scene(BoardScene(document, footprint_lookup(), show_rulers=False))

    lit_with = _pixels_matching(with_rulers, view2d.RULER_TEXT_MAJOR) + _pixels_matching(
        with_rulers, view2d.RULER_TEXT
    )
    lit_without = _pixels_matching(without, view2d.RULER_TEXT_MAJOR) + _pixels_matching(
        without, view2d.RULER_TEXT
    )

    assert lit_with > lit_without + 200


@pytest.mark.skipif(
    QApplication.instance() is not None
    and QApplication.instance().platformName() == "offscreen"  # type: ignore[union-attr]
    and sys.platform == "win32",
    reason="Qt's offscreen plugin ships no font database on Windows; see "
    "main._default_headless_platform",
)
def test_component_reference_labels_actually_draw_text() -> None:
    document = _load_dense()
    scene = BoardScene(document, footprint_lookup(), show_rulers=False, show_ratsnest=False)

    image = _render_scene(scene)

    # REF_LABEL is a near-white used for nothing else on the board; the substrate, pads,
    # bodies and conductors are all well away from it.
    assert _pixels_matching(image, view2d.REF_LABEL, tolerance=12) > 100


def test_labels_hold_their_size_when_the_board_is_zoomed() -> None:
    """A ruler label is annotation, not a feature of the board: it must not grow with zoom.

    Checked through the helper's own measurement rather than by rendering twice, so the test
    states the property instead of comparing two pixel counts that could both be wrong.
    """
    at_low_zoom = scenetext.label_extent_mm(view2d.RULER_LABEL_PX, 3.0)
    at_high_zoom = scenetext.label_extent_mm(view2d.RULER_LABEL_PX, 30.0)

    # Ten times the zoom, a tenth of the board covered: constant on screen.
    assert at_low_zoom == pytest.approx(at_high_zoom * 10)


# ---------------------------------------------------------------------------
# Opening a bad path
# ---------------------------------------------------------------------------


def test_a_missing_file_is_reported_rather_than_raised(tmp_path: pathlib.Path) -> None:
    """A mistyped path is the most likely way anyone first meets this program, and a
    pathlib traceback tells them where Python gave up instead of what to fix."""
    text, problem = read_document_text(tmp_path / "nope.perf")

    assert text is None
    assert problem is not None
    assert "nope.perf" in problem


def test_a_directory_says_so_instead_of_permission_denied(tmp_path: pathlib.Path) -> None:
    """The OS reports a directory read as EACCES, which sends someone hunting for a
    permissions problem they do not have."""
    text, problem = read_document_text(tmp_path)

    assert text is None
    assert problem is not None
    assert "directory" in problem
    assert "ermission" not in problem


def test_a_readable_document_comes_back_as_text() -> None:
    text, problem = read_document_text(GOLDEN)

    assert problem is None
    assert text is not None and text.lstrip().startswith("{")


# ---------------------------------------------------------------------------
# The 3D camera belongs to the person looking through it
# ---------------------------------------------------------------------------


def test_refreshing_the_3d_view_does_not_move_the_camera() -> None:
    """Refreshing used to mean building a whole new renderer, which meant ResetCamera plus a
    fixed elevation and azimuth -- so the 3D viewpoint snapped back to default after every
    command. Orbit the board, nudge a part, and the orbit was gone.
    """
    from perfboard_studio.ui import view3d

    document = _load_dense()
    lookup = footprint_lookup()
    renderer, _stats = view3d.build_renderer(document, lookup)
    camera = renderer.GetActiveCamera()
    camera.Azimuth(55)
    camera.Elevation(20)
    orbited = camera.GetPosition()

    view3d.populate_renderer(renderer, document, lookup)

    assert renderer.GetActiveCamera().GetPosition() == orbited


def test_repopulating_replaces_the_actors_and_keeps_the_light() -> None:
    """The refresh has to actually refresh -- and must not stack up a fresh light per call,
    which is the trap in reusing a renderer instead of rebuilding one."""
    from perfboard_studio.ui import view3d

    document = _load_dense()
    lookup = footprint_lookup()
    renderer, _stats = view3d.build_renderer(document, lookup)
    first_actors = renderer.GetActors().GetNumberOfItems()
    lights = renderer.GetLights().GetNumberOfItems()

    view3d.populate_renderer(renderer, document, lookup)

    assert renderer.GetActors().GetNumberOfItems() == first_actors
    assert renderer.GetLights().GetNumberOfItems() == lights


# ---------------------------------------------------------------------------
# The board is shaded as materials, not as highlights
# ---------------------------------------------------------------------------
#
# There is deliberately no golden IMAGE for the 3D view, unlike the 2D one: VTK draws
# through the machine's own OpenGL, and a mean-colour comparison across three operating
# systems and whatever driver is installed would be a test that fails for reasons nobody
# can act on. What CAN be held still is every decision the render rests on, and each of
# the tests below is one bug that actually happened while it was being built.


def _all_props():
    from perfboard_studio.ui import view3d

    renderer, _stats = view3d.build_renderer(_load_dense(), footprint_lookup())
    actors = renderer.GetActors()
    actors.InitTraversal()
    return [actors.GetNextActor().GetProperty() for _ in range(actors.GetNumberOfItems())]


def test_every_actor_is_shaded_as_a_material_or_deliberately_unlit() -> None:
    """One scene, one lighting model. A leftover Phong actor beside PBR ones is not a
    slightly different finish -- the two answer light by different rules, and the leftover
    reads as a sticker stuck onto the picture. Only annotation is exempt, and it is exempt
    by being UNLIT rather than by being on the old model."""
    import vtkmodules.all as vtk

    stragglers = [
        prop
        for prop in _all_props()
        if prop.GetInterpolation() != vtk.VTK_PBR and prop.GetLighting()
    ]

    assert stragglers == []


def test_a_colour_reaches_the_shader_as_albedo_and_not_as_srgb() -> None:
    """The bug that washed out every part on the board at once. ``BODY_STYLES`` is picked
    as hex, which is sRGB; a physical shader multiplies ALBEDO, and the two differ by a
    gamma curve. A DIP's own #24262d is 0.14 one way and 0.017 the other, and handing over
    the first number renders black epoxy as mid grey."""
    import vtkmodules.all as vtk

    from perfboard_studio.ui import view3d

    prop = vtk.vtkProperty()
    prop.SetColor(0.14, 0.14, 0.14)

    view3d._finish(prop, view3d.MOULDED)

    assert prop.GetColor()[0] == pytest.approx(0.0168, abs=0.001)
    assert prop.GetInterpolation() == vtk.VTK_PBR


def test_a_material_is_metal_or_it_is_not() -> None:
    """``metallic`` is the one PBR input with no meaningful middle: a material either
    conducts and tints its own reflection or it does not. A table with 0.5 in it is a table
    somebody has started tuning by ear, which is what the whole change was to get away
    from."""
    from perfboard_studio.ui import view3d

    materials = {
        name: value
        for name, value in vars(view3d).items()
        if name.isupper() and isinstance(value, tuple) and len(value) == 2
        and all(isinstance(number, float) for number in value)
    }
    assert len(materials) >= 10, sorted(materials)
    for name, (metallic, roughness) in materials.items():
        assert metallic in (0.0, 1.0), f"{name} is {metallic} metallic"
        assert 0.0 < roughness <= 1.0, f"{name} is {roughness} rough"


def test_the_room_is_a_float_cube_map_read_as_colour() -> None:
    """Two mistakes in one call, and the second is spectacular. A vtkTexture's DEFAULT
    colour mode maps scalars through a lookup table, and VTK's default table is the jet
    colormap -- so the room came back as a rainbow and every metal part on the board
    reflected it. And the faces have to be FLOAT: the bench lamp is brighter than white,
    which is the entire reason a smooth surface has anything to pick out."""
    import vtkmodules.all as vtk

    from perfboard_studio.ui import view3d

    texture = view3d.environment_texture()

    assert texture.GetCubeMap()
    assert texture.GetColorMode() == vtk.VTK_COLOR_MODE_DIRECT_SCALARS
    faces = [texture.GetInputDataObject(index, 0) for index in range(6)]
    assert all(face is not None for face in faces)
    brightest = max(
        face.GetPointData().GetScalars().GetRange(component)[1]
        for face in faces
        for component in range(3)
    )
    assert brightest > 1.5, f"nothing in the room is brighter than white ({brightest})"


def test_the_room_is_built_once() -> None:
    """It is the same room every time and filling six faces in Python is the one part of a
    rebuild worth noticing -- and a refresh happens on every edit."""
    from perfboard_studio.ui import view3d

    assert view3d.environment_texture() is view3d.environment_texture()


def test_the_lamp_is_overhead_in_the_worlds_own_up() -> None:
    """The call that is easy to leave out and hard to see the absence of: VTK's environment
    frame is Y-up and this application's world is Z-up, so without saying so the bench lamp
    sits off to one side and every part is lit from the wrong place -- consistently, which
    makes it look odd rather than broken."""
    from perfboard_studio.ui import view3d

    renderer, _stats = view3d.build_renderer(_load_dense(), footprint_lookup())

    up = [0.0, 0.0, 0.0]
    renderer.GetEnvironmentUp(up)
    assert up == [0.0, 0.0, 1.0]
    assert renderer.GetUseImageBasedLighting()


def test_the_diffuse_light_is_worked_out_for_this_room_not_for_a_photograph(
    monkeypatch,
) -> None:
    """VTK precomputes the room's diffuse light before a renderer's first frame, at a size
    meant for a photographed HDR environment. On a machine with no GPU that one step was the
    whole of the 3D view's cost: 12.7 s a renderer on llvmpipe, and 820 s over the guide's
    step images on the macOS CI runner. The room is 64 px of smooth gradient, so the work
    is sized to it -- a picture within 3 levels in 255 of the default one."""
    import vtkmodules.all as vtk

    from perfboard_studio.ui import view3d

    monkeypatch.delenv(view3d.SIMPLE_3D_ENV, raising=False)
    renderer = vtk.vtkRenderer()

    def work(irradiance) -> float:
        # Pixels in a face, times samples per pixel (one every `step` radians, each way).
        return float(irradiance.GetIrradianceSize()) ** 2 / irradiance.GetIrradianceStep() ** 2

    vtk_default = work(renderer.GetEnvMapIrradiance())
    view3d.apply_environment(renderer)

    assert renderer.GetEnvMapIrradiance().GetIrradianceSize() <= view3d._ENV_FACE_PX
    assert work(renderer.GetEnvMapIrradiance()) * 100 < vtk_default


def test_contact_shadows_say_whether_they_took() -> None:
    """The one piece of the render that is a luxury. A machine whose OpenGL cannot do it
    should get a slightly flatter board, not no board -- so this reports rather than
    raises, and the report has to be true."""
    import vtkmodules.all as vtk

    from perfboard_studio.ui import view3d

    renderer = vtk.vtkRenderer()

    assert view3d.apply_contact_shadows(renderer) is True
    assert renderer.GetPass() is not None


def test_the_two_gpu_heavy_parts_can_be_turned_off(monkeypatch) -> None:
    """VTK does not raise when a driver cannot do something -- it ends the process, which
    is what ``offscreen_gl_available`` exists for. Image-based lighting and the occlusion
    pass are the only things in this view that ask for anything unusual, so the one honest
    thing to offer somebody whose machine goes down is a way to run without them. What is
    lost is the room and the contact shadows; every material and every borrowed package
    stays.
    """
    import vtkmodules.all as vtk

    from perfboard_studio.ui import view3d

    monkeypatch.setenv(view3d.SIMPLE_3D_ENV, "1")
    renderer = vtk.vtkRenderer()

    view3d.apply_environment(renderer)

    assert view3d.rich_shading_wanted() is False
    assert renderer.GetUseImageBasedLighting() is False
    assert view3d.apply_contact_shadows(renderer) is False
    assert renderer.GetPass() is None
    # The parts are still shaded as materials -- that is not the expensive half.
    prop = vtk.vtkProperty()
    prop.SetColor(0.5, 0.5, 0.5)
    view3d._finish(prop, view3d.STEEL)
    assert prop.GetInterpolation() == vtk.VTK_PBR


def test_dimming_a_part_takes_its_highlight_and_not_its_shape() -> None:
    """``_dim`` and ``_pick_out`` are a pair: a guide step darkens everything that is not
    its subject, and under PBR the way to push something back is to ROUGHEN it. Dropping
    the old specular did nothing at all once the parts were materials."""
    import vtkmodules.all as vtk

    from perfboard_studio.ui import view3d

    prop = vtk.vtkProperty()
    prop.SetColor(0.5, 0.5, 0.5)
    view3d._finish(prop, view3d.GLOSS)
    before = prop.GetRoughness()

    actor = vtk.vtkActor()
    actor.SetProperty(prop)
    view3d._dim(actor)

    assert prop.GetRoughness() > before
    assert prop.GetColor()[0] < 0.5


# ---------------------------------------------------------------------------
# Packages borrowed from KiCad, and the rules that keep them honest
# ---------------------------------------------------------------------------
#
# PLAN.md D6 chose parametric generation and gave three reasons. Two are untouched; the
# third -- that a generated body cannot disagree with its footprint -- is what these tests
# are for, because a borrowed one CAN. See ui/partmodels.py.


def _one_part_board(footprint_id: str, ref: str = "U1", col: int = 4, row: int = 4):
    from perfboard_studio.command import CommandBus, CommandContext
    from perfboard_studio.commands import (
        DEFAULT_BOARD,
        PlaceComponentPayload,
        create_document_id_generator,
        create_standard_registry,
    )
    from perfboard_studio.model import DocumentMeta, HoleCoord, PerfDocument

    document = PerfDocument(
        meta=DocumentMeta(name="one", created="", modified=""), board=DEFAULT_BOARD
    )
    bus = CommandBus(
        document,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(document)),
    )
    result = bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref=ref, footprint_id=footprint_id, value="", anchor=HoleCoord(col, row)
        ),
    )
    assert result.ok, result.message
    return bus.document


def test_a_package_with_a_model_is_drawn_from_it_and_one_without_is_generated() -> None:
    """The fallback is the whole reason borrowing is safe: a footprint nobody mapped, or a
    part asked for by a generated id, draws exactly as it did before."""
    from perfboard_studio.ui import partmodels

    assert partmodels.model_for("dip-8") is not None
    assert partmodels.model_for("box-4x2-p1-r3-15x10x8") is None
    assert partmodels.model_for(None) is None


def test_every_mesh_the_index_names_is_actually_there() -> None:
    """An index entry with no file behind it is a part that raises when somebody looks at
    it, and only that part -- which is the kind of thing a render test would find on one
    board and miss on the next."""
    from perfboard_studio.ui import partmodels

    missing = [
        piece.mesh
        for model in partmodels._index().values()
        for piece in model.pieces
        if not piece.path.is_file()
    ]
    assert missing == []


def test_a_borrowed_package_stops_at_the_board_surface() -> None:
    """THE RULE THAT LETS THE LEADS STAY OURS. A KiCad model's legs are drawn untrimmed for
    a 1.6 mm board and would hang nine millimetres out of the solder side; the converter
    cuts everything below the surface, and this application draws the rest from the board's
    own thickness."""
    from perfboard_studio.ui import partmodels, view3d

    deepest = 0.0
    for model in partmodels._index().values():
        for piece in model.pieces:
            bounds = view3d._mesh(str(piece.path)).GetBounds()
            deepest = min(deepest, bounds[4])
    assert deepest > -0.2, f"a borrowed mesh reaches {deepest:.2f} mm below the board"


def test_a_borrowed_package_sits_on_the_hole_it_was_placed_on() -> None:
    """A KiCad through-hole model's origin is pin 1 and so is this application's anchor.
    Nothing is measured or fitted; if the two conventions ever disagree, every borrowed
    part on every board is offset by the same amount and nothing else says so."""
    from perfboard_studio.ui import partmodels

    # Checked on every model rather than on one, because the claim is about the CONVENTION:
    # pin 1 at the origin, the package running +x with the column and -y against the row.
    # A model that broke it would be offset by its own length and nothing else would say so.
    wrong = []
    for footprint_id, model in sorted(partmodels._index().items()):
        boxes = [piece.bounds for piece in model.pieces if len(piece.bounds) == 6]
        if not boxes:
            continue
        low_x, low_y = min(b[0] for b in boxes), min(b[1] for b in boxes)
        high_x, high_y = max(b[3] for b in boxes), max(b[4] for b in boxes)
        # The origin has to be INSIDE the package, because the origin is pin 1 and a pin is
        # part of the part. A model placed by its CENTRE instead -- which is how a good many
        # surface-mount ones are drawn -- puts the origin outside, and that is the failure
        # this catches: it would offset the whole package by half its own length.
        if not (low_x <= 0.5 <= high_x and low_y <= 0.5 and high_y >= -0.5):
            wrong.append((footprint_id, [round(v, 2) for v in (low_x, low_y, high_x, high_y)]))
    assert wrong == []


def test_a_borrowed_body_is_painted_from_our_own_table() -> None:
    """``bodies.BODY_STYLES`` is one table for the 2D view, the 3D view and the guide's step
    images. A red LED coming out a different red in two of the three would be giving that
    up for a borrowed mesh, so the body piece takes the style's fill and only the leads,
    tabs and bands keep the colour they were drawn with."""
    from perfboard_studio.footprints import standard_footprints
    from perfboard_studio.ui import partmodels, view3d
    from perfboard_studio.ui.bodies import style_for

    model = partmodels.model_for("led-5mm")
    assert model is not None and model.body is not None
    fill = style_for(standard_footprints()["led-5mm"]).fill

    document = _one_part_board("led-5mm", ref="D1")
    actors = view3d.build_component(footprint_lookup(), document.components[0], document.board)
    wanted = tuple(view3d._to_linear(c) for c in view3d._rgb(fill))

    assert any(
        actor.GetProperty().GetColor() == pytest.approx(wanted, abs=1e-6) for actor in actors
    )


def test_a_borrowed_resistor_still_shows_its_colour_code() -> None:
    """KiCad has no way to know what value a part is and this application does. The barrel
    comes from the model and the bands from the document, printed at the BORROWED barrel's
    size -- a footprint describes a package family and a model is one part in it, so
    printing at the footprint's size puts the bands inside the body and they vanish."""
    from perfboard_studio.command import CommandBus, CommandContext
    from perfboard_studio.commands import (
        DEFAULT_BOARD,
        PlaceComponentPayload,
        create_document_id_generator,
        create_standard_registry,
    )
    from perfboard_studio.model import DocumentMeta, HoleCoord, PerfDocument
    from perfboard_studio.ui import partmodels, view3d

    document = PerfDocument(
        meta=DocumentMeta(name="r", created="", modified=""), board=DEFAULT_BOARD
    )
    bus = CommandBus(
        document,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(document)),
    )
    assert bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref="R1", footprint_id="r-axial-3", value="10k", anchor=HoleCoord(4, 4)
        ),
    ).ok
    component = bus.document.components[0]

    body = view3d._world_body(footprint_lookup(), component, DEFAULT_BOARD)
    assert body is not None and body.bands
    model = partmodels.model_for("r-axial-3")
    assert model is not None
    barrel = view3d._barrel_of(model)
    assert barrel is not None
    radius, _z, _along = barrel

    # The bands have to be printed OUTSIDE the barrel they are printed on.
    assert radius > body.across / 2, "the borrowed barrel is not the footprint's"
    marks = view3d._axial_markings(body, barrel)
    assert len(marks) == len(body.bands)
    for mark in marks:
        assert mark.source.GetRadius() > radius


def test_every_material_the_index_names_is_one_this_module_has() -> None:
    """The index is written by a tool that is not run here. A material it names and the
    renderer does not have is a part shaded as plastic without anything saying so."""
    from perfboard_studio.ui import partmodels, view3d

    named = {piece.material for model in partmodels._index().values() for piece in model.pieces}

    assert named <= set(view3d.MODEL_MATERIALS), sorted(named - set(view3d.MODEL_MATERIALS))


def test_a_board_still_renders_with_no_models_at_all(monkeypatch) -> None:
    """A build that shipped without the meshes draws a complete board rather than refusing
    to draw one -- which is what makes the borrowed packages an improvement rather than a
    requirement, and what the whole fallback exists for."""
    from perfboard_studio.ui import partmodels, view3d

    def triangles(actors):
        total = 0
        for actor in actors:
            data = actor.GetMapper().GetInput()
            total += data.GetNumberOfCells() if data is not None else 0
        return total

    document = _one_part_board("dip-8")
    borrowed = triangles(
        view3d.build_component(footprint_lookup(), document.components[0], document.board)
    )
    monkeypatch.setattr(partmodels, "_index", lambda: {})

    actors = view3d.build_component(footprint_lookup(), document.components[0], document.board)

    assert actors
    # A borrowed DIP is a real package with gull-wing leads and a moulded notch; the
    # generated one is a chamfered box. Both are a whole part, and they are not the same
    # thing -- which is the point of the fallback still being there.
    assert triangles(actors) < borrowed / 2


def test_the_borrowed_meshes_carry_their_own_licence() -> None:
    """They are the only part of this distribution that is not Apache-2.0, and CC-BY-SA is
    a licence you may redistribute under precisely BECAUSE the attribution travels with the
    files. A directory that lost these is a directory nobody may ship."""
    from perfboard_studio.ui import partmodels

    licence = partmodels.MODELS_DIR / "LICENSE"
    notice = partmodels.MODELS_DIR / "NOTICE.md"

    assert licence.is_file() and notice.is_file()
    text = licence.read_text(encoding="utf-8")
    assert "CC-BY-SA 4.0" in text
    assert "kicad-packages3D" in notice.read_text(encoding="utf-8")


def test_apply_default_camera_is_the_only_thing_that_reframes() -> None:
    from perfboard_studio.ui import view3d

    document = _load_dense()
    lookup = footprint_lookup()
    renderer, _stats = view3d.build_renderer(document, lookup)
    default = renderer.GetActiveCamera().GetPosition()
    renderer.GetActiveCamera().Azimuth(90)
    assert renderer.GetActiveCamera().GetPosition() != default

    view3d.apply_default_camera(renderer)

    assert renderer.GetActiveCamera().GetPosition() == pytest.approx(default)


# ---------------------------------------------------------------------------
# Selection survives the rebuild every command causes
# ---------------------------------------------------------------------------


def test_selection_survives_a_document_change() -> None:
    """Every command rebuilds the scene. Without this, a part is deselected the moment it is
    acted on -- so pressing rotate twice would rotate once and then appear to do nothing."""
    document = _load_dense()
    bus = _new_bus(document)
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    comp_id = next(iter(scene.component_items))
    scene.select_components([comp_id])
    assert scene.selected_component_ids() == (comp_id,)

    scene.set_document(bus.document)

    assert scene.selected_component_ids() == (comp_id,)


def test_rebuilding_does_not_touch_items_qt_has_already_destroyed() -> None:
    """scene.clear() destroys the C++ items and emits selectionChanged while doing it. If the
    handler can still see the old dict it raises "Internal C++ object already deleted", which
    surfaced as a traceback on the very first rotate."""
    document = _load_dense()
    scene = BoardScene(document, footprint_lookup(), side="top")
    scene.select_components(list(scene.component_items)[:2])

    scene.set_document(document)  # would raise before the fix
    scene.set_side("bottom")
    scene.set_side("top")

    assert len(scene.component_items) > 0


# ---------------------------------------------------------------------------
# Rotation wrapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "delta", "expected"),
    [(0, 90, 90), (270, 90, 0), (0, -90, 270), (180, -90, 90), (90, 180, 270)],
)
def test_rotation_wraps_to_a_legal_value(current: int, delta: int, expected: int) -> None:
    """component.rotate refuses anything outside 0/90/180/270, so the wrap has to happen
    before dispatch rather than being discovered as a rejected command."""
    assert _rotation_after(current, delta) == expected  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Nudging the selection
# ---------------------------------------------------------------------------


def test_arrow_nudge_moves_through_the_command_bus() -> None:
    """A nudge is a component.move, the same command a drag ends in -- so it undoes and
    journals identically, and an agent watching the board sees it the same way."""
    document = _load_dense()
    bus = _new_bus(document)
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    comp_id = next(iter(scene.component_items))
    before = next(c for c in bus.document.components if c.id == comp_id).anchor
    scene.select_components([comp_id])

    results = scene.nudge_selection(2, -1)

    assert len(results) == 1 and results[0].ok, results[0].message
    after = next(c for c in bus.document.components if c.id == comp_id).anchor
    assert (after.col, after.row) == (before.col + 2, before.row - 1)
    assert len(bus.journal()) == 1
    bus.undo()
    assert next(c for c in bus.document.components if c.id == comp_id).anchor == before


def test_nudging_several_parts_is_one_command_and_one_undo_step() -> None:
    """Several selected parts nudged together are ONE ``component.moveMany``.

    Two things this guards. The historical one: the first dispatch rebuilds the scene and
    destroys every item, so a loop that both read items and dispatched was reading
    destroyed C++ objects from its second iteration on. The current one: a group moved by
    one gesture is one decision, so it is one undo step -- five parts used to take five
    Ctrl+Z presses to put back.
    """
    document = _load_dense()
    bus = _new_bus(document)
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    ids = list(scene.component_items)[:4]
    before = {c.id: c.anchor for c in bus.document.components if c.id in ids}
    scene.select_components(ids)

    results = scene.nudge_selection(0, 1)

    assert len(results) == 1 and results[0].ok, results
    assert len(bus.journal()) == 1
    for comp in bus.document.components:
        if comp.id in ids:
            assert (comp.anchor.col, comp.anchor.row) == (before[comp.id].col, before[comp.id].row + 1)
    bus.undo()
    assert {c.id: c.anchor for c in bus.document.components if c.id in ids} == before


def test_nudging_with_no_selection_does_nothing() -> None:
    document = _load_dense()
    bus = _new_bus(document)
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)

    assert scene.nudge_selection(1, 0) == []
    assert bus.journal() == ()


# ---------------------------------------------------------------------------
# Placing a part: previously impossible from the window at all
# ---------------------------------------------------------------------------


def _blank_bus() -> CommandBus:
    from perfboard_studio.commands import create_empty_document
    from perfboard_studio.model import DocumentMeta

    document = create_empty_document(
        DocumentMeta(name="t", created="2024-01-01T00:00:00.000Z", modified="2024-01-01T00:00:00.000Z")
    )
    return _new_bus(document)


def test_placing_from_the_library_goes_through_the_command_bus() -> None:
    """Sixty-one footprints and component.place both existed with nothing able to reach either,
    so a part could not be added to a board at all."""
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_placement("r-axial-3")

    result = scene.place_armed(HoleCoord(3, 3))

    assert result is not None and result.ok, result
    assert len(bus.document.components) == 1
    placed = bus.document.components[0]
    assert (placed.ref, placed.footprint_id, placed.anchor) == ("R1", "r-axial-3", HoleCoord(3, 3))
    bus.undo()
    assert bus.document.components == ()


def test_references_count_up_and_follow_the_part_kind() -> None:
    """R for a resistor, D for a diode, U for a DIP -- and the next free number, counted from
    the board rather than a hidden counter so undo and delete cannot desynchronise it."""
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)

    scene.arm_placement("r-axial-3")
    scene.place_armed(HoleCoord(1, 1))
    scene.place_armed(HoleCoord(1, 5))
    scene.arm_placement("d-do41")
    scene.place_armed(HoleCoord(1, 9))
    scene.arm_placement("dip-8")
    scene.place_armed(HoleCoord(10, 1))

    assert [c.ref for c in bus.document.components] == ["R1", "R2", "D1", "U1"]


def test_a_reference_freed_by_undo_is_reused() -> None:
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_placement("r-axial-3")
    scene.place_armed(HoleCoord(1, 1))
    scene.place_armed(HoleCoord(1, 5))
    bus.undo()
    scene.set_document(bus.document)

    assert next_reference(bus.document, "r-axial-3") == "R2"


def test_placement_stays_armed_so_several_parts_can_go_down() -> None:
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_placement("r-axial-3")

    scene.place_armed(HoleCoord(1, 1))

    assert scene.armed_footprint_id == "r-axial-3"


def test_disarming_removes_the_ghost() -> None:
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_placement("dip-8")
    assert any(isinstance(i, view2d.PlacementGhostItem) for i in scene.items())

    scene.arm_placement(None)

    assert not any(isinstance(i, view2d.PlacementGhostItem) for i in scene.items())
    assert scene.place_armed(HoleCoord(2, 2)) is None


def test_an_overlapping_placement_is_reported_not_refused() -> None:
    """Two pins in one hole is a legal document that describes a board you do not want, which
    makes it DRC's business rather than a command's. The ghost warns; the click still lands."""
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_placement("r-axial-3")
    scene.place_armed(HoleCoord(3, 3))
    scene.set_document(bus.document)

    result = scene.place_armed(HoleCoord(3, 3))

    assert result is not None and result.ok
    assert scene.last_placement_overlapped is True


def test_a_placement_off_the_board_is_refused_by_the_bus() -> None:
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_placement("dip-8")

    result = scene.place_armed(HoleCoord(-2, 0))

    assert result is not None and result.ok is False
    assert result.code == "off-board"


# ---------------------------------------------------------------------------
# A part's value: the one document field no human could reach
# ---------------------------------------------------------------------------


def test_a_part_is_placed_with_the_value_the_parts_panel_carries() -> None:
    """Every placement used to hard-code value="", so a board built in the window produced
    a bill of materials that said "Resistor x 4" where it meant "10k x 4"."""
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.placement_value = "10k"
    scene.arm_placement("r-axial-3")

    scene.place_armed(HoleCoord(3, 3))

    assert bus.document.components[0].value == "10k"


def test_the_placement_value_outlives_one_placement() -> None:
    """Five resistors of the same value is the case; retyping it between each is not."""
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.placement_value = "100nF"
    scene.arm_placement("c-disc-p2")

    scene.place_armed(HoleCoord(1, 1))
    scene.set_document(bus.document)
    scene.place_armed(HoleCoord(1, 5))

    assert [c.value for c in bus.document.components] == ["100nF", "100nF"]


def test_double_clicking_a_part_asks_the_host_to_open_it() -> None:
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_placement("dip-8")
    scene.place_armed(HoleCoord(4, 4))
    scene.arm_placement(None)
    scene.set_document(bus.document)
    placed = bus.document.components[0]
    seen: list[str] = []
    scene.componentActivated.connect(seen.append)

    item = scene.component_items[placed.id]
    assert scene.component_at(item.pos()) is item
    scene.mouseDoubleClickEvent(_double_click_at(item.pos()))

    assert seen == [placed.id]


def test_a_double_click_while_a_mode_is_armed_opens_nothing() -> None:
    """Every mode gives the first click of the pair a meaning of its own, so a dialog on
    top of it would interrupt the tool with a window nobody asked for."""
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_placement("dip-8")
    scene.place_armed(HoleCoord(4, 4))
    scene.set_document(bus.document)
    seen: list[str] = []
    scene.componentActivated.connect(seen.append)

    scene.arm_drawing("bare-wire")
    item = scene.component_items[bus.document.components[0].id]
    scene.mouseDoubleClickEvent(_double_click_at(item.pos()))

    assert seen == []


def _double_click_at(pos: QPointF):
    """A left double-click at a scene position, as Qt would deliver it."""
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    event = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    event.setScenePos(pos)
    event.setButton(Qt.MouseButton.LeftButton)
    return event


def test_properties_edits_ref_value_and_lock_in_one_undo_step(monkeypatch) -> None:
    """One press of OK is one edit, however many fields it changed."""
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    before = len(window.bus.history())

    monkeypatch.setattr(
        main_module.ComponentDialog, "exec", lambda self: main_module.QDialog.DialogCode.Accepted
    )
    monkeypatch.setattr(main_module.ComponentDialog, "values", lambda self: ("RENAMED", "4k7", True))
    window.on_component_properties(component.id)

    edited = next(c for c in window.bus.document.components if c.id == component.id)
    assert (edited.ref, edited.value, edited.locked) == ("RENAMED", "4k7", True)
    assert len(window.bus.history()) == before + 1
    _close(window)


def test_properties_that_changed_nothing_writes_no_history(monkeypatch) -> None:
    """An undo entry for a dialog somebody opened and closed is an undo entry that lies."""
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    before = len(window.bus.history())

    monkeypatch.setattr(
        main_module.ComponentDialog, "exec", lambda self: main_module.QDialog.DialogCode.Accepted
    )
    monkeypatch.setattr(
        main_module.ComponentDialog,
        "values",
        lambda self: (component.ref, component.value, component.locked),
    )
    window.on_component_properties(component.id)

    assert len(window.bus.history()) == before
    _close(window)


def test_a_duplicate_reference_is_refused_and_said_out_loud(monkeypatch) -> None:
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    first, second = window.bus.document.components[0], window.bus.document.components[1]
    warned: list[str] = []

    monkeypatch.setattr(
        main_module.ComponentDialog, "exec", lambda self: main_module.QDialog.DialogCode.Accepted
    )
    monkeypatch.setattr(main_module.ComponentDialog, "values", lambda self: (second.ref, "", False))
    monkeypatch.setattr(
        main_module.QMessageBox, "warning", lambda *args, **kwargs: warned.append(args[2])
    )
    window.on_component_properties(first.id)

    assert [c.ref for c in window.bus.document.components][:2] == [first.ref, second.ref]
    assert warned and "duplicate-ref" in warned[0]
    _close(window)


def test_properties_is_offered_for_one_part_and_not_for_three() -> None:
    window = _window_on(_load_dense())
    ids = [c.id for c in window.bus.document.components]

    window.scene.select_components(ids[:1])
    assert window.act_properties.isEnabled() is True

    window.scene.select_components(ids[:3])
    assert window.act_properties.isEnabled() is False
    _close(window)


@pytest.mark.parametrize(
    ("ref", "pins", "expected"),
    [
        ("R7", 2, "r-axial-3"),
        ("D2", 2, "d-do41"),
        ("LED1", 2, "led-5mm"),
        ("C4", 2, "c-disc-p2"),
        ("Q1", 3, "to92"),
        ("U1", 8, "dip-8"),
        ("U2", 10, "dip-14"),
        ("J3", 4, "hdr-1x4"),
    ],
)
def test_footprint_guesses_from_a_netlist_reference(ref: str, pins: int, expected: str) -> None:
    """A netlist's footprint field names a KiCad library part, which says nothing about this
    registry -- so the reference letter and the pin count the netlist reveals are all there is
    to go on. Enough to be useful, and stated as a guess."""
    assert guess_footprint_id(ref, pins) == expected


# ---------------------------------------------------------------------------
# Version reporting
# ---------------------------------------------------------------------------


def test_window_title_names_the_build_the_document_and_whether_it_is_saved() -> None:
    assert window_title() == f"Perfboard Studio {__version__} — untitled"
    assert window_title(pathlib.Path("a/b/ne555.perf")) == f"Perfboard Studio {__version__} — ne555.perf"
    # The unsaved marker leads, so it is visible before the title is elided.
    assert window_title(pathlib.Path("x/ne555.perf"), modified=True).startswith("• Perfboard Studio")


def test_version_flag_answers_without_starting_qt(monkeypatch, capsys) -> None:
    """--version has to work on a machine where the GUI cannot start.

    That is precisely when someone is asked which version they have, so main() answers it
    before touching QApplication -- and this test proves the ordering by making any attempt
    to construct one fail loudly.
    """
    import perfboard_studio.ui.main as main_module

    def refuse(*args, **kwargs):
        raise AssertionError("--version must not construct a QApplication")

    monkeypatch.setattr(main_module, "QApplication", refuse)
    monkeypatch.setattr(sys, "argv", ["perfboard-studio", "--version"])

    assert main_module.main() == 0
    assert __version__ in capsys.readouterr().out


def test_version_line_is_pasteable_ascii() -> None:
    """A Windows console at cp1252 turns a typographic separator into a question mark,
    which then travels into a bug report as evidence of a bug that is not there."""
    describe_version().encode("ascii")


# ---------------------------------------------------------------------------
# Auto-place
# ---------------------------------------------------------------------------


def _window_on(doc):
    from perfboard_studio.ui.main import MainWindow

    return MainWindow(doc)


def _close(window) -> None:
    """Close a test window without tripping the unsaved-work guard.

    The guard opens a real modal dialog, which in a headless test run waits forever --
    which is a reasonable thing for it to do and the reason the tests say explicitly
    that they are discarding, rather than the suite quietly never exercising it.
    """
    window._saved_document = window.bus.document
    window.close()


def test_the_cyclic_collector_is_held_off_while_a_planner_runs() -> None:
    """THE ONE PLACE THIS APPLICATION RUNS PYTHON ON TWO THREADS AT ONCE, and the reason
    it crashed.

    ``_run_planner`` pumps Qt on the UI thread while the planner allocates hard on a
    worker. Python's cyclic collector runs on whichever thread trips the threshold -- so it
    runs on the PLANNER, and finalises whatever it finds, including PySide wrappers whose
    C++ objects the UI thread is at that instant painting with. The process does not raise;
    it dies. Forty rounds of "move a part, autoroute" crashed in about half the runs, and
    ``faulthandler`` put the worker inside a dataclass ``__init__`` marked
    *Garbage-collecting* with the main thread inside the board's ``paint``.

    So this pins both halves: off while the worker runs, and back ON afterwards -- a
    collector left disabled would be a memory leak traded for a crash.
    """
    import gc

    window = _window_on(_load_dense())
    seen: list[bool] = []

    window._run_planner("planning", lambda _should_stop: seen.append(gc.isenabled()))

    assert seen == [False], "the collector was live while the planner thread ran"
    assert gc.isenabled(), "the collector was never turned back on"
    _close(window)


def test_a_planner_that_raises_still_turns_the_collector_back_on() -> None:
    """The failure path is the one that matters: an exception here used to leave the
    window disabled, and would now leave the collector off for the rest of the session."""
    import gc

    window = _window_on(_load_dense())

    def boom(_should_stop):
        raise RuntimeError("planner gave up")

    with pytest.raises(RuntimeError):
        window._run_planner("boom", boom)

    assert gc.isenabled()
    assert window.isEnabled()
    _close(window)


def test_autoplace_asks_before_moving_the_users_board(monkeypatch) -> None:
    """Routing adds copper to a board the user arranged; placement MOVES it. So the
    confirmation is not a formality, and cancelling has to leave the document alone."""
    window = _window_on(_load_dense())
    before = window.bus.document

    monkeypatch.setattr(window, "_confirm_placement", lambda plan, ms: False)
    window.on_autoplace()

    assert window.bus.document is before
    window.close()


def test_autoplace_commits_through_the_bus_as_one_undo_step(monkeypatch) -> None:
    window = _window_on(_load_dense())
    before = window.bus.document

    monkeypatch.setattr(window, "_confirm_placement", lambda plan, ms: True)
    window.on_autoplace()

    assert window.bus.document is not before
    assert window.bus.document.components != before.components
    window.bus.undo()
    assert window.bus.document.components == before.components
    window.close()


def test_reroll_advances_the_seed(monkeypatch) -> None:
    """Annealing is a random walk, so "try again" has to actually try something else."""
    window = _window_on(_load_dense())
    monkeypatch.setattr(window, "_confirm_placement", lambda plan, ms: False)

    window.on_autoplace()
    assert window._place_seed == 0
    window.on_autoplace(reroll=True)
    assert window._place_seed == 1
    window.close()


def test_autoplace_on_an_empty_board_says_so_rather_than_running(monkeypatch) -> None:
    from perfboard_studio.commands import create_empty_document
    from perfboard_studio.model import DocumentMeta

    window = _window_on(
        create_empty_document(
            DocumentMeta(name="t", created="2024-01-01T00:00:00.000Z", modified="2024-01-01T00:00:00.000Z")
        )
    )
    called = []
    monkeypatch.setattr(window, "_confirm_placement", lambda plan, ms: called.append(1) or True)

    window.on_autoplace()

    assert called == []
    assert "empty" in window.statusBar().currentMessage()
    window.close()


# ---------------------------------------------------------------------------
# Build guide export
# ---------------------------------------------------------------------------


@requires_offscreen_gl  # on_export_guide renders a step image per step
def test_exporting_the_guide_writes_all_four_files(tmp_path, monkeypatch) -> None:
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    window.current_path = tmp_path / "board.perf"

    monkeypatch.setattr(
        "perfboard_studio.ui.main.QMessageBox.warning", lambda *args, **kwargs: None
    )
    # The export ends by offering to open what it wrote, which is a modal dialog: in a
    # headless run it waits for a click that never comes. Its own behaviour is checked by
    # test_the_export_offers_to_open_what_it_wrote below.
    monkeypatch.setattr(main_module.MainWindow, "_offer_to_open", lambda self, written: None)
    window.on_export_guide()

    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["board_bom.csv", "board_cut_list.csv", "board_guide.html", "board_guide.json"]
    assert "<!doctype html>" in (tmp_path / "board_guide.html").read_text(encoding="utf-8")
    window.close()


@requires_offscreen_gl  # same export path, so the same step images
def test_guide_gaps_are_reported_in_a_dialog_not_only_the_status_bar(tmp_path, monkeypatch) -> None:
    """Each warning says the guide describes less than the whole build. A user who misses
    that follows the steps to the end and finds the board does not work."""
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    window.current_path = tmp_path / "board.perf"

    shown: list[str] = []
    monkeypatch.setattr(
        "perfboard_studio.ui.main.QMessageBox.warning",
        lambda parent, title, text, *args, **kwargs: shown.append(text),
    )
    monkeypatch.setattr(main_module.MainWindow, "_offer_to_open", lambda self, written: None)
    window.on_export_guide()

    assert shown and "could not cover" in shown[0]
    window.close()


def test_the_export_offers_to_open_what_it_wrote(tmp_path, monkeypatch) -> None:
    """The export used to end at a line in the status bar naming a file in a directory
    the user then had to go and find."""
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    guide_html = tmp_path / "board_guide.html"
    guide_html.write_text("<!doctype html>", encoding="utf-8")

    opened: list[str] = []
    monkeypatch.setattr(main_module.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    # Answer the dialog with its first button, which is "Open the Guide".
    monkeypatch.setattr(
        main_module.QMessageBox, "exec", lambda self: self.setDefaultButton(self.buttons()[0])
    )
    monkeypatch.setattr(
        main_module.QMessageBox, "clickedButton", lambda self: self.buttons()[0]
    )
    window._offer_to_open([guide_html, tmp_path / "board_bom.csv"])

    assert [pathlib.Path(o) for o in opened] == [guide_html]
    _close(window)


# ---------------------------------------------------------------------------
# The build guide, in the window
# ---------------------------------------------------------------------------


def test_the_guide_panel_lists_every_step_the_slider_counts() -> None:
    """Two views of one list. Building it twice would let them disagree about how many
    steps there are while showing the same board."""
    from perfboard_studio.ui.main import ROLE_STEP_INDEX

    window = _window_on(_load_dense())
    window.dock_guide.show()
    window._refresh_guide_panel()

    listed = []
    for i in range(window.guide_tree.topLevelItemCount()):
        phase = window.guide_tree.topLevelItem(i)
        for j in range(phase.childCount()):
            index = phase.child(j).data(0, ROLE_STEP_INDEX)
            if index is not None:
                listed.append(index)

    assert listed == list(range(len(window._assembly_steps())))
    _close(window)


def test_picking_a_step_shows_it_on_the_board() -> None:
    """"Fit R7, C7 to C11" is an instruction; the same step with those two pads lit up on
    the board in front of you is an answer."""
    from perfboard_studio.guide import PartStep
    from perfboard_studio.ui.main import ROLE_STEP_INDEX

    window = _window_on(_load_dense())
    window.dock_guide.show()
    window._refresh_guide_panel()
    steps = window._assembly_steps()
    part_index = next(i for i, s in enumerate(steps) if isinstance(s, PartStep))

    leaf = _guide_leaf_for(window, part_index, ROLE_STEP_INDEX)
    leaf.setSelected(True)

    assert window.scene.selected_component_ids() == (steps[part_index].component_id,)
    _close(window)


def _guide_leaf_for(window, index, role):
    tree = window.guide_tree
    for i in range(tree.topLevelItemCount()):
        phase = tree.topLevelItem(i)
        for j in range(phase.childCount()):
            if phase.child(j).data(0, role) == index:
                return phase.child(j)
    raise AssertionError(f"no leaf for step {index}")


def test_a_closed_guide_panel_costs_nothing() -> None:
    """Building a guide runs DRC and LVS. Paying for that on every edit to fill a panel
    nobody has open is the mistake the 3D dock already avoids."""
    window = _window_on(_load_dense())
    assert window.dock_guide.isVisible() is False
    assert window._guide_stale is True

    window.guide_tree.clear()
    window.on_bus_changed(window.bus.document, None)

    assert window.guide_tree.topLevelItemCount() == 0
    _close(window)


# ---------------------------------------------------------------------------
# The solder side
# ---------------------------------------------------------------------------


def test_the_solder_side_shows_where_a_part_is_without_drawing_the_part() -> None:
    """You can see a part through the board, and on the solder side you need to: "is
    there room for this wire" and "which pad belongs to the chip" are questions asked
    from that side. But drawing the body as seen from above is how somebody solders a
    board backwards, so the footprint is hatched and carries none of the component-side
    marks."""
    from perfboard_studio.ui.view2d import _paint_body_shadow

    doc = _load_dense()
    bottom = BoardScene(doc, footprint_lookup(), side="bottom")
    top = BoardScene(doc, footprint_lookup(), side="top")

    assert len(bottom.component_items) == len(top.component_items)
    assert callable(_paint_body_shadow)


def test_the_solder_side_body_shadow_ignores_the_polarity_key() -> None:
    """A cathode band and a pin-1 notch are moulded into the TOP of a part. Showing them
    from below would be inventing a view that does not exist."""
    import inspect

    from perfboard_studio.ui import view2d

    source = inspect.getsource(view2d._paint_body_shadow)
    assert "_body_path(footprint, placement, None)" in source


# ---------------------------------------------------------------------------
# The resistor colour code, in both views
# ---------------------------------------------------------------------------


def _ne555_document() -> PerfDocument:
    """The fixture with real part values on it. dense.perf's are synthetic ("v12"), which
    is useful for the opposite check and useless for this one."""
    text = (GOLDEN.parent / "ne555.perf").read_text(encoding="utf-8")
    result = persist.deserialize_document(text)
    assert result.ok, f"golden fixture failed to load: {result}"
    return result.document


def test_a_resistors_bands_reach_actual_pixels_in_the_2d_view() -> None:
    """End to end rather than by inspection: the value is in the document, the scene is
    built from it, and the band colours have to come out the other side. A silently broken
    hand-off here would leave every resistor beige again with nothing failing."""
    doc = _ne555_document()
    scene = BoardScene(doc, footprint_lookup(), side="top")

    image = QImage(1400, 1000, QImage.Format.Format_ARGB32)
    image.fill(QColor("#101014"))
    painter = QPainter(image)
    scene.render(painter)
    painter.end()

    present = {image.pixelColor(x, y).name() for x in range(1400) for y in range(1000)}
    # R1 is 10k: brown, black, orange. The orange multiplier band is the one that says
    # which decade it is, and is the difference between 10k and 100 R.
    assert "#6b4423" in present, "no brown band"
    assert "#e2701f" in present, "no orange band"
    assert "#c9a227" in present, "no gold tolerance band"


def test_a_part_whose_value_is_not_a_resistance_is_left_unmarked() -> None:
    """dense.perf's values are placeholders ("v12", "v5") on real axial footprints. Bands
    decoded from those would be pure invention printed on a part someone then fits."""
    doc = _load_dense()
    lookup = footprint_lookup()

    for comp in doc.components:
        footprint = lookup(comp.footprint_id)
        if footprint is None:
            continue
        assert view2d.resistor_bands(footprint, comp.value) is None, comp.ref


def test_both_views_band_a_resistor_from_the_same_source() -> None:
    """One table, two renderers. If these ever disagreed, a board would read as one part
    in the editor and another in the 3D view -- and the 3D view exists to be checked
    against the editor."""
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.bodies import resistor_bands

    doc = _ne555_document()
    lookup = footprint_lookup()
    resistor = next(c for c in doc.components if c.ref == "R1")
    footprint = lookup(resistor.footprint_id)
    assert footprint is not None

    body = view3d._world_body(lookup, resistor, doc.board)

    assert body is not None
    assert body.bands == resistor_bands(footprint, resistor.value)
    assert body.bands  # ...and it is not merely two empty tuples agreeing with each other.


# ---------------------------------------------------------------------------
# Conductor appearance
# ---------------------------------------------------------------------------


def test_insulated_wire_takes_its_nets_colour_from_the_build_guides_convention() -> None:
    """The screen and the cut list a person works from must not disagree about which
    wire is which."""
    from perfboard_studio.guide import COLOR_BY_NET_CLASS
    from perfboard_studio.ui.view2d import _INSULATION_SCREEN, insulation_color

    assert insulation_color("power", 0) == _INSULATION_SCREEN[COLOR_BY_NET_CLASS["power"]]
    assert insulation_color("ground", 0) == _INSULATION_SCREEN[COLOR_BY_NET_CLASS["ground"]]
    # Signals cycle, and two different signals are told apart.
    assert insulation_color("signal", 0) != insulation_color("signal", 1)
    # Every name the guide can emit has a screen colour, or a wire would silently fall
    # back to grey and stop matching its own cut-list row.
    from perfboard_studio.guide import SIGNAL_COLORS

    for name in (*SIGNAL_COLORS, *COLOR_BY_NET_CLASS.values()):
        assert name in _INSULATION_SCREEN, name


def test_no_conductor_is_drawn_in_the_error_colour() -> None:
    """Red means "this is wrong" -- the DRC outline and the R5' risk ring. Every
    insulated wire used to be red as well, so a completely correct board looked alarming
    and a real risk had nothing to stand out against."""
    from perfboard_studio.ui.view2d import CONDUCTOR_STYLE, ERROR_OUTLINE, RISK_RING

    for kind, (colour, _width, _dashed) in CONDUCTOR_STYLE.items():
        assert colour.name() != ERROR_OUTLINE.name(), kind
        assert colour.name() != RISK_RING.name(), kind


def test_solder_beads_sit_inside_the_pad_rather_than_over_it() -> None:
    """Solder fills a pad; it does not replace it. A bead wider than the pad hides the
    very thing being soldered to, which is what made a routed board read as a diagram of
    coloured bars with a board somewhere underneath."""
    from perfboard_studio.ui.view2d import CONDUCTOR_STYLE

    board = _load_dense().board
    for kind in ("solder-trace", "solder-trace-wired", "bare-wire", "insulated-wire"):
        width = CONDUCTOR_STYLE[kind][1]
        assert width < board.pad_diameter, kind


# ---------------------------------------------------------------------------
# The file, watched (PLAN.md §9.3)
#
# The point of a diffable project file is that an agent which only writes files still
# works. The window is the participant that has to notice -- otherwise the board on
# screen goes quietly stale and the next save overwrites everything the agent did.
# ---------------------------------------------------------------------------


def _write(path: pathlib.Path, doc: PerfDocument) -> None:
    path.write_text(persist.serialize_document(doc), encoding="utf-8")


def test_an_unmodified_window_reloads_when_the_file_changes_underneath_it(tmp_path) -> None:
    from perfboard_studio.commands import MoveComponentPayload

    path = tmp_path / "board.perf"
    doc = _load_dense()
    _write(path, doc)
    window = _window_on(doc)
    window.current_path = path
    window._disk_text = path.read_text(encoding="utf-8")

    # Somebody else edits the file: an agent, an editor, a git checkout.
    edited = _new_bus(doc)
    first = doc.components[0]
    edited.dispatch("component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(9, 9)))
    _write(path, edited.document)

    window._reload_if_changed()

    moved = next(c for c in window.bus.document.components if c.id == first.id)
    assert moved.anchor == HoleCoord(9, 9)
    assert window.is_modified is False
    _close(window)


def test_a_window_with_unsaved_work_is_never_reloaded_behind_the_users_back(tmp_path) -> None:
    """The one outcome that must not happen. The file and the window have both moved and
    only the person in front of it can say which is right."""
    from perfboard_studio.commands import MoveComponentPayload

    path = tmp_path / "board.perf"
    doc = _load_dense()
    _write(path, doc)
    window = _window_on(doc)
    window.current_path = path
    window._disk_text = path.read_text(encoding="utf-8")
    first = window.bus.document.components[0]
    window.bus.dispatch("component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(3, 3)))

    edited = _new_bus(doc)
    edited.dispatch("component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(9, 9)))
    _write(path, edited.document)

    window._reload_if_changed()

    kept = next(c for c in window.bus.document.components if c.id == first.id)
    assert kept.anchor == HoleCoord(3, 3), "the user's unsaved edit survived"
    assert "changed on disk" in window.statusBar().currentMessage()
    _close(window)


def test_saving_does_not_make_the_window_reload_itself(tmp_path) -> None:
    """A save changes the file, and a window that reloaded after every one would throw
    away its own undo history for nothing."""
    from perfboard_studio.commands import MoveComponentPayload

    path = tmp_path / "board.perf"
    window = _window_on(_load_dense())
    window.current_path = path
    first = window.bus.document.components[0]
    window.bus.dispatch("component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(3, 3)))
    window._save_to(path)
    before = window.bus.document

    window._reload_if_changed()

    assert window.bus.document is before
    assert window.bus.can_undo() is True
    _close(window)


# ---------------------------------------------------------------------------
# Finding a part
# ---------------------------------------------------------------------------


def test_a_part_can_be_found_by_reference_value_or_footprint() -> None:
    """Which of the three somebody remembers depends on why they are looking: "R37" from
    a DRC message, "10k" from the schematic, "TO-220" from the pile on the bench."""
    from perfboard_studio.ui.main import GoToPartDialog

    doc = _load_dense()
    dialog = GoToPartDialog(doc.components, footprint_lookup())
    everything = dialog.list.count()

    first = doc.components[0]
    dialog.filter.setText(first.ref)
    assert 0 < dialog.list.count() < everything
    assert dialog.chosen_id() is not None

    dialog.filter.setText("no such part anywhere")
    assert dialog.list.count() == 0
    assert dialog.chosen_id() is None


def test_going_to_a_part_selects_it_and_moves_the_view() -> None:
    window = _window_on(_load_dense())
    target = window.bus.document.components[-1]

    window.go_to_component(target.id)

    assert window.scene.selected_component_ids() == (target.id,)
    assert target.ref in window.statusBar().currentMessage()
    _close(window)


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------


def test_measuring_reports_three_different_distances() -> None:
    """They are three answers, not one rounded three ways: holes across is what a
    footprint is written in, mm is what a lead-bending jig is set to, and steps is how
    much solder trace it would take -- a diagonal is two steps of copper, not 1.4."""
    from perfboard_studio.ui.view2d import describe_span

    doc = _load_dense()

    text = describe_span(view2d.HoleCoord(2, 6), view2d.HoleCoord(6, 8), doc.board)

    assert "C7" in text and "G9" in text
    assert "5 × 3 holes" in text
    assert "11.36 mm" in text  # sqrt(4^2 + 2^2) * 2.54
    assert "6 step(s)" in text


def test_measuring_the_same_hole_twice_is_not_a_measurement() -> None:
    from perfboard_studio.ui.view2d import describe_span

    doc = _load_dense()

    assert "same hole" in describe_span(
        view2d.HoleCoord(4, 4), view2d.HoleCoord(4, 4), doc.board
    )


def test_the_measuring_tool_takes_two_clicks_and_stays_armed() -> None:
    """Measuring one distance is almost never what somebody is doing -- they are
    comparing several -- so it does not disarm itself after each answer."""
    doc = _load_dense()
    scene = BoardScene(doc, footprint_lookup(), side="top")
    said: list[str] = []
    scene.measured.connect(said.append)

    scene.arm_measure(True)
    scene.measure_click(view2d.HoleCoord(1, 1))
    scene.measure_click(view2d.HoleCoord(1, 5))

    assert "5 holes" in said[-1] and "10.16 mm" in said[-1]
    assert scene.measure_armed is True
    assert scene.measure_from() is None, "and it is ready for the next pair"


def test_measuring_arms_no_other_mode_and_escape_ends_it() -> None:
    """Every board mode is exclusive: a click has to mean one thing."""
    doc = _load_dense()
    scene = BoardScene(doc, footprint_lookup(), side="top")

    scene.arm_drawing("bare-wire")
    scene.arm_measure(True)
    assert scene.armed_draw_kind is None

    scene.arm_drawing("bare-wire")
    assert scene.measure_armed is False

    scene.arm_measure(True)
    scene.leave_mode()
    assert scene.measure_armed is False


def test_measuring_changes_nothing_on_the_board() -> None:
    """The one tool that is not an edit. It has no bus dispatch to make."""
    doc = _load_dense()
    bus = _new_bus(doc)
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)

    scene.arm_measure(True)
    scene.measure_click(view2d.HoleCoord(2, 2))
    scene.measure_click(view2d.HoleCoord(9, 9))

    assert bus.document is doc
    assert bus.can_undo() is False


# ---------------------------------------------------------------------------
# Copy, paste, duplicate
#
# What a block IS is tested in tests/test_clipboard.py, which needs no window. These
# three are the seam: the real system clipboard, and the selection the window reads.
# ---------------------------------------------------------------------------


def test_copy_then_paste_puts_a_second_copy_of_the_part_on_the_board() -> None:
    from PySide6.QtWidgets import QApplication

    window = _window_on(_load_dense())
    before = len(window.bus.document.components)
    first = window.bus.document.components[0]
    window.scene.select_components([first.id])

    window.on_copy()
    assert "perfboard-studio-block" in QApplication.clipboard().text()
    window.on_paste()

    assert len(window.bus.document.components) == before + 1
    pasted = window.bus.document.components[-1]
    assert pasted.footprint_id == first.footprint_id
    assert pasted.ref != first.ref, "a copy of R1 is not R1"
    assert pasted.anchor != first.anchor, "and it is not underneath it either"
    _close(window)


def test_nothing_on_the_clipboard_is_an_ordinary_answer_rather_than_a_crash() -> None:
    """The clipboard usually holds whatever was copied last, in another application."""
    from PySide6.QtWidgets import QApplication

    window = _window_on(_load_dense())
    QApplication.clipboard().setText("https://example.com/")
    before = window.bus.document

    window.on_paste()

    assert window.bus.document is before
    assert "clipboard" in window.statusBar().currentMessage()
    _close(window)


def test_duplicate_leaves_the_system_clipboard_alone() -> None:
    """Duplicating a part is a board operation. It has no business throwing away what
    somebody copied in another application to use in a minute."""
    from PySide6.QtWidgets import QApplication

    window = _window_on(_load_dense())
    QApplication.clipboard().setText("something the user still wants")
    window.scene.select_components([window.bus.document.components[0].id])
    before = len(window.bus.document.components)

    window.on_duplicate()

    assert len(window.bus.document.components) == before + 1
    assert QApplication.clipboard().text() == "something the user still wants"
    _close(window)


def test_a_paste_selects_what_it_pasted() -> None:
    """So the very next thing -- a drag, R, M -- lands on the new block rather than on
    whatever happened to be selected when it was copied."""
    window = _window_on(_load_dense())
    first = window.bus.document.components[0]
    window.scene.select_components([first.id])

    window.on_duplicate()

    pasted = window.bus.document.components[-1]
    assert window.scene.selected_component_ids() == (pasted.id,)
    _close(window)


# ---------------------------------------------------------------------------
# Unsaved work
# ---------------------------------------------------------------------------


def test_a_fresh_window_is_not_modified() -> None:
    window = _window_on(_load_dense())
    assert window.is_modified is False
    assert "•" not in window.windowTitle()
    _close(window)


def test_any_command_marks_the_board_modified() -> None:
    from perfboard_studio.commands import MoveComponentPayload

    window = _window_on(_load_dense())
    first = window.bus.document.components[0]
    window.bus.dispatch(
        "component.move", MoveComponentPayload(id=first.id, anchor=view2d.HoleCoord(5, 5))
    )

    assert window.is_modified is True
    assert window.windowTitle().startswith("•")
    _close(window)


def test_undoing_back_to_the_saved_state_reads_as_unmodified() -> None:
    """Identity, not equality: undo restores the very document object that was saved, so
    "I undid everything" correctly stops nagging."""
    from perfboard_studio.commands import MoveComponentPayload

    window = _window_on(_load_dense())
    first = window.bus.document.components[0]
    window.bus.dispatch(
        "component.move", MoveComponentPayload(id=first.id, anchor=view2d.HoleCoord(5, 5))
    )
    assert window.is_modified

    window.bus.undo()

    assert window.is_modified is False
    _close(window)


def test_closing_with_unsaved_work_asks_and_can_be_cancelled(monkeypatch) -> None:
    """The last thing standing between an hour of layout and the X button."""
    from PySide6.QtGui import QCloseEvent

    from perfboard_studio.commands import MoveComponentPayload

    window = _window_on(_load_dense())
    first = window.bus.document.components[0]
    window.bus.dispatch(
        "component.move", MoveComponentPayload(id=first.id, anchor=view2d.HoleCoord(5, 5))
    )

    monkeypatch.setattr(window, "_offer_to_save", lambda: False)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()

    monkeypatch.setattr(window, "_offer_to_save", lambda: True)
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
    _close(window)


def test_an_unmodified_board_closes_without_a_prompt(monkeypatch) -> None:
    window = _window_on(_load_dense())
    asked = []
    monkeypatch.setattr(
        "perfboard_studio.ui.main.QMessageBox.exec", lambda self: asked.append(1) or 0
    )
    assert window._offer_to_save() is True
    assert asked == []
    _close(window)


def test_saving_clears_the_modified_marker(tmp_path) -> None:
    from perfboard_studio.commands import MoveComponentPayload

    window = _window_on(_load_dense())
    first = window.bus.document.components[0]
    window.bus.dispatch(
        "component.move", MoveComponentPayload(id=first.id, anchor=view2d.HoleCoord(5, 5))
    )
    window.current_path = tmp_path / "b.perf"
    window.on_save()

    assert window.is_modified is False
    assert (tmp_path / "b.perf").exists()
    _close(window)


# ---------------------------------------------------------------------------
# Board setup -- the first thing that can reach board.set
# ---------------------------------------------------------------------------


def test_board_setup_dialog_round_trips_a_board() -> None:
    from perfboard_studio.ui.main import BoardSetupDialog

    doc = _load_dense()
    dialog = BoardSetupDialog(doc.board)
    assert dialog.board() == doc.board

    dialog.cols.setValue(40)
    dialog.material.setCurrentIndex(dialog.material.findData("FR2"))
    changed = dialog.board()
    assert changed.cols == 40
    assert changed.material == "FR2"
    # Pitch and pad geometry are not the dialog's business and must survive untouched.
    assert changed.pitch == doc.board.pitch
    assert changed.pad_diameter == doc.board.pad_diameter


def test_board_setup_asks_which_product_and_folds_the_rest_away() -> None:
    """A perfboard is bought, not specified: the dialog is the list of things a supplier
    stocks, and the five fields a product already decides are behind Advanced."""
    from perfboard_studio.geometry import STANDARD_PRESETS, board_from_preset
    from perfboard_studio.ui.main import BoardSetupDialog

    stock = next(p for p in STANDARD_PRESETS if p.name == "4 x 6 cm" and not p.single_sided)
    board = board_from_preset(stock, _load_dense().board)
    dialog = BoardSetupDialog(board)

    # ...and it opens showing which product this already is, rather than "Custom size".
    assert dialog.preset.currentData() == stock.key
    assert not dialog.advanced_toggle.isChecked()
    dialog.deleteLater()


def test_board_setup_opens_expanded_on_a_board_nobody_sells() -> None:
    """Then those fields are the only thing describing the board, and hiding them behind a
    disclosure arrow would hide the board."""
    from perfboard_studio.ui.main import BoardSetupDialog

    doc = _load_dense()  # 40 x 28 is not a size anybody stocks
    dialog = BoardSetupDialog(doc.board)

    assert dialog.advanced_toggle.isChecked()
    dialog.deleteLater()


def test_choosing_a_custom_size_opens_the_fields_it_is_asking_for() -> None:
    """Picking "Custom size" and being shown no numbers is the dialog asking a question
    and hiding the answer."""
    from perfboard_studio.geometry import STANDARD_PRESETS, board_from_preset
    from perfboard_studio.ui.main import BoardSetupDialog

    stock = next(p for p in STANDARD_PRESETS if p.name == "4 x 6 cm" and not p.single_sided)
    dialog = BoardSetupDialog(board_from_preset(stock, _load_dense().board))
    assert not dialog.advanced_toggle.isChecked()

    dialog.preset.setCurrentIndex(dialog.preset.findData(""))

    assert dialog.advanced_toggle.isChecked()
    dialog.deleteLater()


def test_showing_a_board_that_is_already_a_product_is_not_choosing_one() -> None:
    """``_preset`` means "a product was picked from the list", which is what tells the
    caller to rebuild the finger strips and corner holes that come with it. Re-opening
    Board Setup on a 14 x 20 board is not a request to have its connectors rebuilt."""
    from perfboard_studio.geometry import STANDARD_PRESETS, board_from_preset
    from perfboard_studio.ui.main import BoardSetupDialog

    stock = next(p for p in STANDARD_PRESETS if p.name == "4 x 6 cm" and not p.single_sided)
    dialog = BoardSetupDialog(board_from_preset(stock, _load_dense().board))

    assert dialog.preset_features() is None
    dialog.deleteLater()


def test_which_way_the_strips_run_is_only_asked_of_a_stripboard() -> None:
    """Hidden rather than greyed out: a disabled row still costs a line and still has to
    be read past to find out it does not apply."""
    from perfboard_studio.ui.main import BoardSetupDialog

    dialog = BoardSetupDialog(_load_dense().board)
    assert dialog.strip_axis.isHidden()

    dialog.board_type.setCurrentIndex(dialog.board_type.findData("stripboard"))
    assert not dialog.strip_axis.isHidden()
    dialog.deleteLater()


def test_every_board_material_is_offered() -> None:
    """FR-2 in particular: it is the board most perfboard is actually sold as, and the
    only one where the pad-lifting rule and the derated iron temperature apply."""
    from typing import get_args

    from perfboard_studio.model import BoardMaterial
    from perfboard_studio.ui.main import BoardSetupDialog

    offered = {value for value, _label in BoardSetupDialog.MATERIALS}
    assert offered == set(get_args(BoardMaterial))


def test_shrinking_the_board_under_a_part_is_refused_not_silently_applied(monkeypatch) -> None:
    from perfboard_studio.commands import SetBoardPayload

    window = _window_on(_load_dense())
    tiny = dataclasses.replace(window.bus.document.board, cols=3, rows=3)
    result = window.bus.dispatch("board.set", SetBoardPayload(board=tiny))

    assert result.ok is False
    assert window.bus.document.board.cols != 3
    _close(window)


# ---------------------------------------------------------------------------
# Drawing conductors by hand
# ---------------------------------------------------------------------------


def _drawing_scene():
    """A scene over a small board with a bus, ready to draw on."""
    from perfboard_studio.commands import create_empty_document
    from perfboard_studio.model import DocumentMeta

    doc = create_empty_document(
        DocumentMeta(name="t", created="2024-01-01T00:00:00.000Z", modified="2024-01-01T00:00:00.000Z")
    )
    bus = _new_bus(doc)
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    return scene, bus


def test_a_wire_is_two_clicks_and_commits_itself() -> None:
    scene, bus = _drawing_scene()
    scene.arm_drawing("insulated-wire")

    assert scene.draw_click(view2d.HoleCoord(2, 2)) is None  # First click starts it.
    result = scene.draw_click(view2d.HoleCoord(9, 6))

    assert result is not None and result.ok, result
    conductor = bus.document.conductors[0]
    assert conductor.kind == "insulated-wire"
    assert conductor.path == (view2d.HoleCoord(2, 2), view2d.HoleCoord(9, 6))
    assert scene.armed_draw_kind is None  # Disarmed once committed.


def test_a_solder_trace_is_a_chain_and_commits_on_request() -> None:
    scene, bus = _drawing_scene()
    scene.arm_drawing("solder-trace")

    for col in range(2, 6):
        scene.draw_click(view2d.HoleCoord(col, 4))
    assert not bus.document.conductors  # Still being drawn.

    result = scene.commit_drawing()

    assert result is not None and result.ok, result
    assert len(bus.document.conductors[0].path) == 4


def test_a_diagonal_step_is_refused_before_the_click_lands() -> None:
    """Solder spans the 0.6 mm gap to the next pad and not the 1.7 mm diagonal one. The
    command knows that; the preview has to know it too, or the tool looks broken when a
    click does nothing."""
    scene, bus = _drawing_scene()
    scene.arm_drawing("solder-trace")
    scene.draw_click(view2d.HoleCoord(4, 4))

    assert scene.draw_click(view2d.HoleCoord(5, 5)) is None
    scene.commit_drawing()
    assert not bus.document.conductors  # One hole is not a conductor.


def test_a_wire_may_go_diagonally_because_a_wire_physically_can() -> None:
    scene, bus = _drawing_scene()
    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(4, 4))
    result = scene.draw_click(view2d.HoleCoord(7, 9))
    assert result is not None and result.ok
    assert bus.document.conductors[0].path[-1] == view2d.HoleCoord(7, 9)


def test_escape_abandons_a_half_drawn_trace() -> None:
    scene, bus = _drawing_scene()
    scene.arm_drawing("solder-trace")
    scene.draw_click(view2d.HoleCoord(2, 2))
    scene.draw_click(view2d.HoleCoord(3, 2))

    scene.arm_drawing(None)

    assert not bus.document.conductors
    assert scene.armed_draw_kind is None


def test_a_hand_drawn_conductor_takes_a_net_only_when_it_is_unambiguous() -> None:
    """Copper with no net claim is what rip-up-and-reroute and the stale cleanup both
    promise never to touch, so a connection the tool cannot interpret is also one it will
    never quietly remove."""
    from perfboard_studio.commands import PlaceComponentPayload
    from perfboard_studio.model import Net, NetNode

    scene, bus = _drawing_scene()
    bus.dispatch(
        "component.place",
        PlaceComponentPayload(ref="R1", value="", footprint_id="r-axial-4", anchor=view2d.HoleCoord(2, 2)),
    )
    bus.dispatch(
        "component.place",
        PlaceComponentPayload(ref="R2", value="", footprint_id="r-axial-4", anchor=view2d.HoleCoord(9, 2)),
    )
    from perfboard_studio.commands import ImportNetlistPayload

    bus.dispatch(
        "netlist.import",
        ImportNetlistPayload(
            nets=(
                Net(
                    id="n1",
                    name="SIG",
                    nodes=(NetNode(component_ref="R1", pin="1"), NetNode(component_ref="R2", pin="1")),
                ),
            )
        ),
    )
    scene.set_document(bus.document)

    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(2, 2))
    scene.draw_click(view2d.HoleCoord(9, 2))
    assert bus.document.conductors[-1].net_id == "n1"

    # ...and an end on no pin at all leaves it unassigned rather than guessing.
    scene.set_document(bus.document)
    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(4, 10))
    scene.draw_click(view2d.HoleCoord(8, 10))
    assert bus.document.conductors[-1].net_id is None


def test_conductors_can_be_selected_and_deleted() -> None:
    scene, bus = _drawing_scene()
    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(2, 2))
    scene.draw_click(view2d.HoleCoord(8, 2))
    scene.set_document(bus.document)

    items = [i for i in scene.items() if isinstance(i, view2d.ConductorItem)]
    assert len(items) == 1
    items[0].setSelected(True)

    assert scene.selected_conductor_ids() == (bus.document.conductors[0].id,)


def test_a_conductor_is_pickable_along_its_length_not_by_its_bounding_box() -> None:
    """Two wires crossing at an angle share a bounding rect the size of the board between
    them; picking by that rect would select whichever happened to be on top."""
    scene, bus = _drawing_scene()
    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(2, 2))
    scene.draw_click(view2d.HoleCoord(20, 20))
    scene.set_document(bus.document)

    item = next(i for i in scene.items() if isinstance(i, view2d.ConductorItem))
    on_the_wire = view2d.hole_to_screen(view2d.HoleCoord(11, 11), bus.document.board, "top")
    off_the_wire = view2d.hole_to_screen(view2d.HoleCoord(20, 2), bus.document.board, "top")

    assert item.shape().contains(item.mapFromScene(on_the_wire))
    assert not item.shape().contains(item.mapFromScene(off_the_wire))


# ---------------------------------------------------------------------------
# Performance and long-running work
# ---------------------------------------------------------------------------


def test_the_pad_grid_reuses_one_rasterised_pad() -> None:
    """Every pad on a board is identical by definition, so rasterising 6000 of them is
    6000 times more work than necessary. Blitting one pre-rendered pad took a 100x60
    board from 8.9 to 62 frames a second."""
    from PySide6.QtGui import QPixmap

    doc = _load_dense()
    grid = view2d.PadGridItem(doc.board, "top")

    first = grid._pad_for(12.0)
    assert isinstance(first, QPixmap)
    assert first.width() > 0
    # Same zoom, same pixmap object: no re-rasterising between frames.
    assert grid._pad_for(12.0) is first
    # A nearby zoom falls in the same bucket, so a smooth zoom does not thrash the cache.
    assert grid._pad_for(13.0) is first
    # A very different zoom does get its own.
    assert grid._pad_for(60.0) is not first


def test_the_pad_pixmap_is_bounded_however_far_you_zoom() -> None:
    doc = _load_dense()
    grid = view2d.PadGridItem(doc.board, "top")
    assert grid._pad_for(100000.0).width() <= 256


def test_a_planner_runs_off_the_ui_thread_and_can_be_cancelled() -> None:
    """Auto-place takes about a second, and it used to take it on the UI thread behind a
    wait cursor -- so the window stopped repainting and looked hung for exactly as long as
    the useful work took."""
    window = _window_on(_load_dense())
    seen: list[bool] = []

    def work(should_stop):
        seen.append(callable(should_stop))
        return "done"

    assert window._run_planner("test", work) == "done"
    assert seen == [True]
    _close(window)


def test_a_planner_exception_surfaces_on_the_ui_thread() -> None:
    """Swallowed on the worker thread it would look like a silent no-op."""
    window = _window_on(_load_dense())

    def boom(_should_stop):
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        window._run_planner("test", boom)
    _close(window)


def test_the_window_is_re_enabled_even_when_the_planner_fails() -> None:
    window = _window_on(_load_dense())

    def boom(_should_stop):
        raise ValueError("nope")

    with pytest.raises(ValueError):
        window._run_planner("test", boom)
    assert window.isEnabled()
    _close(window)


def test_placement_stopped_early_still_returns_a_legal_placement() -> None:
    """Cancelling asks the planner to stop and hand back its best result so far. Stopping
    early yields a worse placement, never an invalid one."""
    from perfboard_studio.placer import PlacementOptions, plan_placement

    doc = _load_dense()
    plan = plan_placement(
        doc,
        footprint_lookup(),
        PlacementOptions(iterations=40000, restarts=4, score_with_router=False),
        should_stop=lambda: True,
    )
    assert plan.after.is_legal
    assert plan.after.total(plan.weights) <= plan.before.total(plan.weights) + 1e-9


def test_the_cursor_hole_readout_tracks_the_pointer() -> None:
    window = _window_on(_load_dense())

    window._on_hovered_hole(2, 6)
    assert "C7" in window.label_hole.text()

    window._on_hovered_hole(-1, 0)
    assert "—" in window.label_hole.text()
    _close(window)


# ---------------------------------------------------------------------------
# The 3D board
# ---------------------------------------------------------------------------


def test_the_board_has_holes_from_underneath() -> None:
    """The substrate was one solid cube with pads only on top, so turning the board over
    showed a blank slab -- on the very view whose job is checking the solder side."""
    from perfboard_studio.ui import view3d

    doc = _load_dense()
    # Copper on both faces, at opposite sides of the substrate, and a bore through it.
    assert view3d.pad_z(doc.board, "top") > 0 > view3d.pad_z(doc.board, "bottom")
    assert view3d.pad_z(doc.board, "bottom") < -doc.board.thickness
    assert view3d.build_drills(doc.board) is not None
    assert view3d.build_pads(doc.board, "bottom") is not None


def test_the_legend_on_the_underside_reads_the_right_way_round() -> None:
    """Ink on the bottom face, looked at from underneath, has to read normally. Both
    faces were built from one set of glyphs at two different depths, so turning the board
    over in 3D showed the addresses written backwards.

    Reflected about the HOLE SPAN, the axis everything else mirrors about, so A stays on
    the hole A names. Checked on the geometry rather than on pixels: the two faces must
    span the same width, and the bottom one must put A where the top one puts the last
    column.
    """
    import dataclasses

    from perfboard_studio.model import BoardLabels
    from perfboard_studio.ui import view3d

    doc = _load_dense()
    board = dataclasses.replace(
        doc.board, cols=6, rows=4, labels=BoardLabels(row_digits=2)
    )
    doc = dataclasses.replace(doc, board=board, components=(), conductors=())
    span_w = (board.cols - 1) * board.pitch

    top, bottom = view3d.build_legend(doc)

    def points(actor: object) -> set[tuple[float, float]]:
        data = actor.GetMapper().GetInput()  # type: ignore[attr-defined]
        return {
            (round(data.GetPoint(i)[0], 3), round(data.GetPoint(i)[1], 3))
            for i in range(data.GetNumberOfPoints())
        }

    top_points = points(top)
    bottom_points = points(bottom)
    reflected = {(round(span_w - x, 3), y) for x, y in top_points}

    assert bottom_points == reflected
    # Not a vacuous assertion: A and R are different shapes, so an unreflected copy is a
    # genuinely different point set. This is the comparison that fails if the flip goes.
    assert bottom_points != top_points


def test_the_exploded_view_lifts_the_parts_and_leaves_the_board_alone() -> None:
    """PLAN.md D7. The board is what the parts come off; lifting that too would just be
    moving the camera.

    Measured on the PARTS, not on the scene bounds: the leader lines reach the full lift
    whether or not anything rose with them, so a bounds check passes on a view where every
    part is still flat on the board.
    """
    import vtk

    from perfboard_studio.ui import view3d

    doc = _load_dense()
    lookup = footprint_lookup()
    lift = view3d.EXPLODED_LIFT_MM

    for comp in doc.components:
        actors = view3d.build_component(lookup, comp, doc.board)
        for actor in actors:
            before = actor.GetBounds()[4]
            view3d._lift(actor, lift)
            assert actor.GetBounds()[4] == pytest.approx(before + lift)

    flat = vtk.vtkRenderer()
    view3d.populate_renderer(flat, doc, lookup)
    blown = vtk.vtkRenderer()
    view3d.populate_renderer(blown, doc, lookup, exploded_mm=lift)

    # The substrate's underside is the lowest thing in either scene and has not moved.
    assert _lowest(blown) == pytest.approx(_lowest(flat))


def test_every_exploded_part_has_a_line_down_to_its_own_holes() -> None:
    """Without them a vertical explosion is ambiguous: a part over the MIDDLE of the board
    projects onto it from the standard viewpoint and reads as sitting on it, while an
    identical part near an edge reads as floating. The line is the answer to the question
    the view exists to ask -- which holes does this one go in."""
    from perfboard_studio.geometry import all_pin_holes
    from perfboard_studio.ui import view3d

    doc = _load_dense()
    lookup = footprint_lookup()
    lift = view3d.EXPLODED_LIFT_MM
    leaders = view3d.build_drop_lines(lookup, doc, lift)
    assert leaders is not None

    pins = sum(
        len(all_pin_holes(c, lookup(c.footprint_id)))
        for c in doc.components
        if lookup(c.footprint_id) is not None
    )
    data = leaders.GetMapper().GetInput()
    assert data.GetNumberOfLines() == pins, "one leader per pin hole"

    bounds = data.GetBounds()
    assert bounds[4] == pytest.approx(0.0)
    assert bounds[5] == pytest.approx(lift), "the lines must reach the parts they belong to"

    assert view3d.build_drop_lines(lookup, doc, 0.0) is None, "nothing to lead to"


def test_highlighting_a_step_dims_the_other_parts_but_never_the_board() -> None:
    """A step card says which holes a part goes in. Dimming the board with everything else
    would be printing the answer with the question rubbed out."""
    import vtk

    from perfboard_studio.ui import view3d

    doc = _load_dense()
    lookup = footprint_lookup()
    subject = doc.components[0]

    plain = vtk.vtkRenderer()
    view3d.populate_renderer(plain, doc, lookup)
    picked = vtk.vtkRenderer()
    view3d.populate_renderer(picked, doc, lookup, highlight=subject.id)

    # The substrate is built first either way, so position 0 is comparable.
    assert _actor_colours(picked)[0] == _actor_colours(plain)[0], "the board was dimmed"
    assert _actor_colours(picked) != _actor_colours(plain), "nothing was dimmed at all"

    others = view3d.build_component(lookup, doc.components[1], doc.board)
    before = others[0].GetProperty().GetColor()
    view3d._dim(others[0])
    after = others[0].GetProperty().GetColor()
    assert all(a < b for a, b in zip(after, before, strict=True) if b > 0)
    assert after != before


def _highest(ren: object) -> float:
    return ren.ComputeVisiblePropBounds()[5]  # type: ignore[attr-defined]


def _lowest(ren: object) -> float:
    return ren.ComputeVisiblePropBounds()[4]  # type: ignore[attr-defined]


def _actor_colours(ren: object) -> list[tuple[float, float, float]]:
    actors = ren.GetActors()  # type: ignore[attr-defined]
    actors.InitTraversal()
    return [
        actors.GetNextActor().GetProperty().GetColor()
        for _ in range(actors.GetNumberOfItems())
    ]


@requires_offscreen_gl
def test_every_step_gets_a_picture_of_its_own() -> None:
    """PLAN.md §7.2. Keyed by guide.step_focus, which is what guide_export looks them up
    by, so a mismatch here shows as a guide with no illustrations rather than a crash."""
    from perfboard_studio.guide import all_steps, build_guide, step_focus
    from perfboard_studio.ui import view3d

    doc = _load_dense()
    lookup = footprint_lookup()
    guide = build_guide(doc, lookup)

    images = view3d.render_step_images(doc, guide, lookup, width=200, height=140)

    assert set(images) == {step_focus(step) for step in all_steps(guide)}
    # JPEG, and the guide's size is why: these are photographs of a lit 3D scene, which
    # PNG stores at ~136 KB each against JPEG's 47 KB, and every one of them is base64ed
    # into a single file somebody opens on a phone.
    assert all(shot.startswith(b"\xff\xd8\xff") for shot in images.values())


@requires_offscreen_gl
def test_a_step_looks_the_same_whichever_face_was_drawn_before_it(monkeypatch) -> None:
    """The step images used to come from two windows, one a face, sharing one room. Drawing
    the solder side made the component window work its lighting out again, and every
    component-side step after the first flip came out up to 23 levels in 255 away from the
    same step drawn on its own. That second precompute, and the one for the second window,
    were also most of the cost on a machine with no GPU. So: one renderer, two cameras."""
    import numpy as np
    import vtkmodules.all as vtk

    from perfboard_studio.guide import all_steps, build_guide, document_at_step, step_focus
    from perfboard_studio.ui import view3d

    doc = _load_dense()
    lookup = footprint_lookup()
    guide = build_guide(doc, lookup)
    steps = all_steps(guide)
    size = (160, 106)

    built = []
    build_renderer = view3d.build_renderer
    monkeypatch.setattr(
        view3d, "build_renderer", lambda *a, **k: built.append(a) or build_renderer(*a, **k)
    )
    images = view3d.render_step_images(doc, guide, lookup, *size)
    monkeypatch.undo()
    assert len(built) == 1

    sides = [view3d.step_is_solder_side(doc, step_focus(step)) for step in steps]
    index = next(i for i in range(1, len(steps)) if sides[i - 1] and not sides[i])
    focus = step_focus(steps[index])
    ren, _stats = view3d.build_renderer(doc, lookup)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(ren)
    win.SetSize(*size)
    view3d.populate_renderer(ren, document_at_step(doc, guide, index), lookup, highlight=focus)
    win.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    writer = vtk.vtkJPEGWriter()
    writer.SetQuality(view3d.STEP_IMAGE_JPEG_QUALITY)
    writer.WriteToMemoryOn()
    writer.SetInputConnection(grab.GetOutputPort())
    writer.Write()
    alone = bytes(view3d.numpy_support.vtk_to_numpy(writer.GetResult()).tobytes())

    def pixels(jpeg: bytes) -> np.ndarray:
        image = QImage.fromData(jpeg, "JPG").convertToFormat(QImage.Format.Format_RGB888)
        rows = np.frombuffer(image.constBits(), np.uint8).reshape(
            image.height(), image.bytesPerLine()
        )
        return rows[:, : image.width() * 3].astype(int)

    worst = int(np.abs(pixels(images[focus]) - pixels(alone)).max())
    assert worst <= 2, f"step {index} differs from itself drawn alone by {worst} levels"


def test_a_connection_is_photographed_from_the_side_it_is_made_on() -> None:
    """The fault this exists to prevent: almost every connection is made on the solder
    side, and shot from the component side it is behind 1.6 mm of board. The first version
    of the step images produced fourteen pictures of a board with nothing happening."""
    from perfboard_studio.guide import all_steps, build_guide, step_focus
    from perfboard_studio.ui import view3d

    doc = _load_dense()
    guide = build_guide(doc, footprint_lookup())
    side_of = {c.id: c.side for c in doc.conductors}

    seen_bottom = False
    for step in all_steps(guide):
        focus = step_focus(step)
        expected = side_of.get(focus) == "bottom"
        assert view3d.step_is_solder_side(doc, focus) is expected
        seen_bottom |= expected

    assert seen_bottom, "this fixture is meant to have solder-side connections"
    # ...and the other way too, or the test would pass on a rule that always said True.
    assert any(c.side == "top" for c in doc.conductors), "and top-side ones"


def test_a_part_is_always_photographed_from_the_component_side() -> None:
    """Parts go in from the top, whatever else is on the board."""
    from perfboard_studio.ui import view3d

    doc = _load_dense()

    assert not any(view3d.step_is_solder_side(doc, c.id) for c in doc.components)


def test_solder_and_wire_are_not_the_same_grey() -> None:
    """PLAN.md Sec 8.3 makes telling them apart at a glance a requirement of this view.
    They were (0.72, 0.74, 0.77) and (0.85, 0.87, 0.89) -- the same grey."""
    from perfboard_studio.ui.view3d import BARE_RGB, SOLDER_RGB

    difference = sum(abs(a - b) for a, b in zip(SOLDER_RGB, BARE_RGB, strict=True))
    assert difference > 0.5, "solder and tinned wire are still indistinguishable"


def test_a_solder_run_is_the_size_of_a_solder_run() -> None:
    """It has to bridge the gap to the next pad -- that is what a run IS -- and it has to
    leave the pad it is soldered to visible, or the view stops answering "which pads is
    this run on".

    Both ends of that were wrong at 0.34 mm: under half a real run, and thinner than the
    bead drawn at every pad, so the silhouette came out as balls on a stick.
    """
    from perfboard_studio.geometry import pad_edge_gap_mm
    from perfboard_studio.ui.view3d import TRACE_JOINT_RADIUS_MM, TRACE_WAIST_RATIO

    board = _load_dense().board
    joint = 2 * TRACE_JOINT_RADIUS_MM
    bridge = joint * TRACE_WAIST_RATIO

    assert bridge > pad_edge_gap_mm(board, "horizontal"), "too thin to bridge to the next pad"
    assert joint < board.pad_diameter, "a joint this wide hides the pad it is made on"
    assert TRACE_WAIST_RATIO < 1.0, "a run with no narrowing has no countable joints"
    assert TRACE_WAIST_RATIO > 0.4, "a run pinched this hard is beads threaded on a string"


def test_one_stacking_step_clears_the_widest_pair_that_can_cross() -> None:
    """A wire can cross a solder run, so the step has to clear those two together --
    the widest pair there is. Derived rather than chosen; see STACK_STEP_MM."""
    from perfboard_studio.ui.view3d import (
        BARE_WIRE_RADIUS_MM,
        INSULATED_RADIUS_MM,
        STACK_STEP_MM,
        TRACE_JOINT_RADIUS_MM,
    )

    radii = (TRACE_JOINT_RADIUS_MM, BARE_WIRE_RADIUS_MM, INSULATED_RADIUS_MM)
    widest_pair = sum(sorted(radii)[-2:])

    assert widest_pair < STACK_STEP_MM, "a step that leaves two crossing tubes overlapping"


def test_a_run_is_in_the_surface_and_a_wire_is_on_it() -> None:
    """The distinction PLAN.md Sec 8.3 makes a requirement, put into the geometry rather
    than left to the colour.

    Solder wets the copper: a run stands as a half-round ridge over the pad plane, so its
    centreline IS that plane and only its outer half shows. A wire lies on the board and
    touches along one line, so its centreline is a radius clear. Both used to be a radius
    clear, which is why a joint drawn at the run's own height sat behind the pad it was
    made on and slid off it from any oblique angle.
    """
    from perfboard_studio.ui.view3d import conductor_radius, conductor_z, pad_z

    board = _load_dense().board
    run = SolderTraceConductor(id="t1", path=(HoleCoord(2, 2), HoleCoord(6, 2)))
    wire = WireConductor(id="w1", path=(HoleCoord(2, 4), HoleCoord(9, 4)), kind="bare-wire")
    copper = pad_z(board, "bottom")

    assert conductor_z(run, board, 0) == pytest.approx(copper)
    assert conductor_z(wire, board, 0) == pytest.approx(copper - conductor_radius(wire))


def test_a_wire_goes_down_into_the_holes_it_is_soldered_into() -> None:
    """It was a stick floating parallel to the board, stopping in mid-air over each pad --
    so it neither entered the board nor reached what it was soldered to. Worse once a wire
    could be lifted over another: at one stacking level its ends hang a millimetre above
    the copper.

    A run does NOT do this. It is fused to the copper along its whole length, so it goes
    exactly where the pads are and nowhere else.
    """
    from perfboard_studio.ui.view3d import _conductor_centreline, conductor_z, pad_z

    board = _load_dense().board
    copper = pad_z(board, "bottom")

    wire = WireConductor(id="w1", path=(HoleCoord(2, 4), HoleCoord(9, 4)), kind="bare-wire")
    run_z = conductor_z(wire, board, 1)
    line = _conductor_centreline(wire, board, run_z, copper, is_trace=False)
    assert line[0][2] == pytest.approx(copper), "the wire has to reach its pad"
    assert line[-1][2] == pytest.approx(copper)
    assert any(point[2] == pytest.approx(run_z) for point in line), "and clear it in between"
    assert len(line) > len(wire.path), "a drop with no run-in is a staple, not a bend"

    trace = SolderTraceConductor(id="t1", path=tuple(HoleCoord(c, 2) for c in range(2, 6)))
    flat = _conductor_centreline(trace, board, copper, copper, is_trace=True)
    assert {round(point[2], 9) for point in flat} == {round(copper, 9)}


def test_a_run_swells_where_it_is_soldered_and_draws_in_between() -> None:
    """One surface, not a tube with spheres dropped on it -- those meet in a hard crease
    all the way round and read as beads threaded on a wire. The swell is what makes the
    joints countable, and counting joints along a run against the real board is what
    somebody following the build guide does.
    """
    from perfboard_studio.ui.view3d import _conductor_centreline, _trace_swell, pad_z

    board = _load_dense().board
    copper = pad_z(board, "bottom")
    trace = SolderTraceConductor(id="t1", path=tuple(HoleCoord(c, 2) for c in range(2, 6)))

    line = _conductor_centreline(trace, board, copper, copper, is_trace=True)
    swell = _trace_swell(trace, line)

    assert len(swell) == len(line)
    assert len(line) == 2 * len(trace.path) - 1, "a point at each pad and one between"
    # Widest exactly at the pads, narrowest exactly between them.
    at_pads = swell[0::2]
    between = swell[1::2]
    assert len(at_pads) == len(trace.path)
    assert min(at_pads) > max(between)


def _segment_gap(p1, p2, q1, q2):
    """Closest approach between two 3D segments, and where on the first it happens."""
    import math

    def sub(a, b):
        return tuple(x - y for x, y in zip(a, b, strict=True))

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))

    u, v, w = sub(p2, p1), sub(q2, q1), sub(p1, q1)
    a, b, c, d, e = dot(u, u), dot(u, v), dot(v, v), dot(u, w), dot(v, w)
    denominator = a * c - b * b
    if denominator < 1e-12:
        s_at, t_at = 0.0, (d / b if abs(b) > 1e-12 else 0.0)
    else:
        s_at = (b * e - c * d) / denominator
        t_at = (a * e - b * d) / denominator
    s_at = min(1.0, max(0.0, s_at))
    t_at = min(1.0, max(0.0, t_at))
    offset = tuple(w[i] + s_at * u[i] - t_at * v[i] for i in range(3))
    where = tuple(p1[i] + s_at * u[i] for i in range(3))
    return math.sqrt(dot(offset, offset)), where


def _as_drawn(cond, board, level):
    """The centreline and per-point radius view3d actually tubes this conductor at."""
    from perfboard_studio.model import contacts_every_path_hole
    from perfboard_studio.ui.view3d import (
        TRACE_WAIST_RATIO,
        _conductor_centreline,
        _trace_swell,
        conductor_radius,
        conductor_z,
        pad_z,
    )

    is_trace = contacts_every_path_hole(cond)
    line = _conductor_centreline(
        cond, board, conductor_z(cond, board, level), pad_z(board, cond.side), is_trace
    )
    if is_trace:
        waist = conductor_radius(cond) * TRACE_WAIST_RATIO
        return line, [waist * value for value in _trace_swell(cond, line)]
    return line, [conductor_radius(cond)] * len(line)


@pytest.mark.parametrize("case", sorted(p.stem for p in GOLDEN.parent.glob("*.perf")))
def test_no_two_conductors_are_drawn_in_the_same_place(case: str) -> None:
    """THE test for this view, and the one that found every remaining fault in it.

    Two pieces of copper cannot occupy one space. Squinting at a render does not settle
    whether they do -- so this walks the centrelines `view3d` builds and the radii it
    tubes them at, and measures. Anything closer than the two radii added together is two
    solids in one place, and it is a bug however good the picture looks from the default
    camera.

    Soldered into ONE HOLE is not that: two conductors meeting at a pad become one joint,
    which is why closeness within a pad's reach of a shared hole is excluded. Everywhere
    else the finding is real, and running this over the fifteen fixtures is what turned up
    both of the ones nothing else had:

    * `stacking_layers` returned a level and `conductor_z` added the document's own
      `layer_z` to it AGAIN, so a pair the stacker had deliberately separated -- one at
      layer_z 1 and stack 0, the other at layer_z 0 and stack 1 -- came out at the same
      height and was drawn straight through. Four fixtures had that pair.
    * A wire's descent into its pad ramped as far as it dropped, so one coming down two
      stacking levels swept almost four millimetres across the board, through whatever was
      lying under it.
    """
    import itertools
    import math

    from perfboard_studio.geometry import hole_key
    from perfboard_studio.occupancy import stacking_layers
    from perfboard_studio.ui.view3d import _xy

    doc = _golden_document(case)
    if len(doc.conductors) < 2:
        pytest.skip(f"{case} has nothing to collide")
    levels = stacking_layers(doc)
    drawn = {c.id: _as_drawn(c, doc.board, levels[c.id]) for c in doc.conductors}

    for first, second in itertools.combinations(doc.conductors, 2):
        if first.side != second.side:
            continue  # a board's thickness is between them
        shared = {hole_key(h) for h in first.path} & {hole_key(h) for h in second.path}
        joints = [
            _xy(doc.board, hole)
            for hole in (*first.path, *second.path)
            if hole_key(hole) in shared
        ]
        line_a, radii_a = drawn[first.id]
        line_b, radii_b = drawn[second.id]
        for i in range(len(line_a) - 1):
            for j in range(len(line_b) - 1):
                gap, where = _segment_gap(line_a[i], line_a[i + 1], line_b[j], line_b[j + 1])
                needed = max(radii_a[i], radii_a[i + 1]) + max(radii_b[j], radii_b[j + 1])
                if gap >= needed - 1e-9:
                    continue
                if any(math.dist(where[:2], at) < doc.board.pad_diameter for at in joints):
                    continue  # soldered into the same hole: one joint, not two solids
                pytest.fail(
                    f"{case}: {first.id} ({first.kind}) and {second.id} ({second.kind}) are "
                    f"{needed - gap:.2f} mm inside each other at "
                    f"({where[0]:.1f}, {where[1]:.1f}, {where[2]:.1f}), sharing no pad there"
                )


def test_the_lights_travel_with_the_camera() -> None:
    """They were nailed to world positions, one above the board and one below -- and the
    lower one was the deliberately dimmer FILL, so the solder side, the face you turn the
    board over to inspect, was lit by the weaker lamp at an angle unrelated to where you
    were looking from. Solder came out flat and dark, which is most of why a run of it
    read as grey plumbing rather than metal.

    A camera light keeps whichever face is towards you the lit one, however the board is
    turned. Asserted on the renderer because the failure is invisible in every test that
    does not actually look at a picture.
    """
    import vtk

    from perfboard_studio.ui.view3d import build_renderer

    ren, _stats = build_renderer(_load_dense(), footprint_lookup())
    lights = list(ren.GetLights())

    assert len(lights) == 2, "a key and a fill"
    for light in lights:
        assert light.GetLightType() == vtk.VTK_LIGHT_TYPE_CAMERA_LIGHT, (
            "a world-positioned light leaves one face of the board in the dark"
        )
    assert max(light.GetIntensity() for light in lights) > min(
        light.GetIntensity() for light in lights
    ), "a key and a fill of equal strength is a headlight, and a headlight is flat"


def test_one_stacking_step_actually_clears_a_tube_of_the_one_below() -> None:
    """Two wires crossing were drawn intersecting, which is not a thing wire does -- and
    the first fix for it did not fix it.

    The step was 0.08 mm, against tubes drawn at a 0.42 mm radius: a tenth of what two of
    them need before they stop overlapping, so crossing wires went on interpenetrating
    exactly as before. Meanwhile the level was a running index over every conductor on the
    board, so the offset still accumulated -- 4.47 mm off a board 1.6 mm thick on the
    dense fixture. It bought levitation and no clearance.

    The step is derived from the radii now, which only became affordable once
    `occupancy.stacking_layers` stopped lifting conductors that cross nothing.
    """
    from perfboard_studio.ui.view3d import INSULATED_RADIUS_MM, STACK_STEP_MM, conductor_z

    doc = _load_dense()
    wire = WireConductor(id="w1", path=(HoleCoord(2, 2), HoleCoord(9, 9)), kind="bare-wire")

    assert STACK_STEP_MM > 2 * INSULATED_RADIUS_MM, "a step that does not clear the tube"
    step = abs(conductor_z(wire, doc.board, 1) - conductor_z(wire, doc.board, 0))
    assert step == pytest.approx(STACK_STEP_MM)
    # Solder-side copper stays clear of the substrate however deep the stack goes.
    assert conductor_z(wire, doc.board, 12) < -doc.board.thickness


def test_the_two_views_agree_about_which_wire_passes_over_which() -> None:
    """Both read `occupancy.stacking_layers`, so they cannot drift. The 2D view used to
    put every solder-side conductor at one z, which left the answer to scene order -- and
    scene order is not what the 3D view is looking at."""
    from perfboard_studio.occupancy import stacking_layers
    from perfboard_studio.ui.view2d import BoardScene, ConductorItem

    doc = _load_dense()
    layers = stacking_layers(doc)
    scene = BoardScene(doc, footprint_lookup())

    drawn = {
        item.conductor.id: item
        for item in scene.items()
        if isinstance(item, ConductorItem)
    }
    assert drawn, "the fixture has conductors"
    for cid, item in drawn.items():
        assert item.stack == layers[cid]
    # And the order on screen follows it: a lifted wire is painted over the one it crosses.
    lifted = [cid for cid, level in layers.items() if level > 0]
    assert lifted, "the dense fixture has a crossing"
    for cid in lifted:
        assert drawn[cid].zValue() > drawn[next(iter(k for k in layers if layers[k] == 0))].zValue()


# ---------------------------------------------------------------------------
# Board colour
# ---------------------------------------------------------------------------


def test_both_views_take_their_board_colour_from_one_scheme() -> None:
    """Green in the editor and blue in 3D would undermine the one job the 3D view has."""
    from perfboard_studio.ui import boardcolors

    try:
        boardcolors.choose("blue")
        blue = boardcolors.scheme_for("FR4")
        assert blue.key == "blue"
        # The 2D hex and the 3D linear RGB describe the same colour.
        expected = (int(blue.fill[1:3], 16) / 255, int(blue.fill[3:5], 16) / 255,
                    int(blue.fill[5:7], 16) / 255)
        assert all(abs(a - b) < 0.06 for a, b in zip(blue.rgb, expected, strict=True))
    finally:
        boardcolors.choose(None)


def test_the_material_decides_until_someone_chooses() -> None:
    """FR-2 is the brown phenolic board, and the build guide derates the iron for exactly
    that material -- the two should agree on sight."""
    from perfboard_studio.ui import boardcolors

    boardcolors.choose(None)
    assert boardcolors.scheme_for("FR4").key == "green"
    assert boardcolors.scheme_for("FR2").key == "phenolic"


def test_every_material_has_a_default_scheme() -> None:
    from typing import get_args

    from perfboard_studio.model import BoardMaterial
    from perfboard_studio.ui import boardcolors

    for material in get_args(BoardMaterial):
        assert material in boardcolors.DEFAULT_FOR_MATERIAL
        assert boardcolors.DEFAULT_FOR_MATERIAL[material] in boardcolors.BY_KEY


def test_an_unknown_colour_falls_back_to_the_material() -> None:
    from perfboard_studio.ui import boardcolors

    try:
        boardcolors.choose("chartreuse")
        assert boardcolors.chosen_key() is None
        assert boardcolors.scheme_for("FR4").key == "green"
    finally:
        boardcolors.choose(None)


# ---------------------------------------------------------------------------
# Board features in the editor: oblong pads, the printed legend, mounting holes
# ---------------------------------------------------------------------------


def _blank_document():
    from perfboard_studio.commands import create_empty_document
    from perfboard_studio.model import DocumentMeta

    return create_empty_document(
        DocumentMeta(
            name="t", created="2026-01-01T00:00:00.000Z", modified="2026-01-01T00:00:00.000Z"
        )
    )


def _featured_document():
    """A board using all three: oblong pads, a printed legend, a corner hole, a connector."""
    from perfboard_studio.commands import DEFAULT_BOARD, create_empty_document
    from perfboard_studio.model import BoardLabels, DocumentMeta, EdgeConnector, MountingHole

    board = dataclasses.replace(
        DEFAULT_BOARD,
        cols=14,
        rows=10,
        pad_shape="oblong",
        pad_length=2.25,
        border_x_mm=2.0, border_y_mm=2.0,
        labels=BoardLabels(row_digits=2),
    )
    doc = create_empty_document(
        DocumentMeta(name="features", created="2026-01-01", modified="2026-01-01"), board
    )
    return dataclasses.replace(
        doc,
        mounting_holes=(MountingHole(id="mh-1", at=HoleCoord(1, 1)),),
                # An inset, as the real boards have: the fingers stop short of the edge and the
        # strip left outside them is where the row legend is printed.
        edge_connectors=(EdgeConnector(id="ec-1", edge="bottom", start=3, count=5, inset_mm=1.6),),
    )


def test_the_pad_grid_leaves_out_the_pads_a_mounting_bore_removed() -> None:
    """Drawing copper where the bore took it away would show a pad to solder to that is
    not there -- which is precisely what the DRC rule exists to stop someone finding out
    with an iron in hand."""
    doc = _featured_document()
    with_hole = BoardScene(doc, footprint_lookup(), show_rulers=False)
    without = BoardScene(
        dataclasses.replace(doc, mounting_holes=()), footprint_lookup(), show_rulers=False
    )
    _render_scene(with_hole)
    _render_scene(without)

    assert with_hole.pad_grid is not None and without.pad_grid is not None
    # The bore at B2 eats its own pad and its four orthogonal neighbours.
    assert without.pad_grid.drawn - with_hole.pad_grid.drawn == 5


def test_the_scene_carries_the_board_features_it_is_given() -> None:
    from perfboard_studio.ui.view2d import BoardLegendItem, EdgeConnectorItem, MountingHoleItem

    scene = BoardScene(_featured_document(), footprint_lookup(), show_rulers=False)
    kinds = {type(item) for item in scene.items()}
    assert BoardLegendItem in kinds
    assert MountingHoleItem in kinds
    assert EdgeConnectorItem in kinds


def test_a_plain_board_draws_no_legend() -> None:
    from perfboard_studio.ui.view2d import BoardLegendItem

    scene = BoardScene(_load_dense(), footprint_lookup(), show_rulers=False)
    assert BoardLegendItem not in {type(item) for item in scene.items()}


def _legend_labels_drawn(doc, monkeypatch):
    """Every label the legend lays down, as (text, centre, height_mm, max_width_mm).

    Asserted on instead of pixels ON PURPOSE. The legend is silkscreen, so it is sized in
    millimetres and comes out around 14 device pixels at the editor's usual zoom -- and on
    a Qt platform with no font database (this one; see the skips above) nothing is drawn
    at that size at all, silently. A pixel test there passes or fails on whether Qt
    happens to have fonts, which is not the thing worth testing. Where each label is put
    and how big it is *is*: getting that wrong is what buries the legend under the first
    row of pads, which is the bug this pair of tests exists to catch.
    """
    drawn: list[tuple[str, QPointF, float, float | None]] = []
    real = view2d.draw_physical_label

    # **kwargs, not a copied signature: a shim that has to be kept in step with the real
    # function will one day not be, and the failure mode is a TypeError raised inside
    # QGraphicsItem.paint -- which leaves the QPainter open and crashes the NEXT test
    # with an access violation, a long way from the cause.
    def record(painter, centre, text, height_mm, *args, **kwargs):
        drawn.append((text, QPointF(centre), height_mm, kwargs.get("max_width_mm")))
        return real(painter, centre, text, height_mm, *args, **kwargs)

    monkeypatch.setattr(view2d, "draw_physical_label", record)
    _render_scene(BoardScene(doc, footprint_lookup(), show_rulers=False, show_ratsnest=False))
    return drawn


def test_the_printed_legend_lays_down_every_address_on_all_four_edges(monkeypatch) -> None:
    """Letters along the top AND bottom, numbers down the left AND right, as these boards
    are printed. With one edge each, the far half of the board is nearest the edge that
    does not carry its address."""
    doc = _featured_document()
    board = doc.board
    drawn = _legend_labels_drawn(doc, monkeypatch)

    letters = [text for text, _c, _h, _w in drawn if text.isalpha()]
    numbers = [text for text, _c, _h, _w in drawn if text.isdigit()]
    assert len(letters) == board.cols * 2
    assert len(numbers) == board.rows * 2
    assert set(letters) == {column_label(col) for col in range(board.cols)}
    # row_digits=2, so the board prints "01" where the guide says row 1 -- the same
    # address, set the way these boards set it.
    assert "01" in numbers
    assert "10" in numbers


def test_a_plain_board_lays_down_no_legend(monkeypatch) -> None:
    assert _legend_labels_drawn(_load_dense(), monkeypatch) == []


def test_the_legend_is_printed_in_the_border_and_not_over_the_pads(monkeypatch) -> None:
    """The reason ``border_mm`` exists. Half a pitch past the outer holes leaves 0.32 mm
    of bare substrate at 2.54 mm pitch, which is not room for a character -- it would be
    drawn under the first row of pads and never seen."""
    from perfboard_studio.geometry import board_edge_margin_mm, hole_span_mm, pad_extent_mm

    doc = _featured_document()
    board = doc.board
    margin_x = board_edge_margin_mm(board, "horizontal")
    margin_y = board_edge_margin_mm(board, "vertical")
    extent_x, extent_y = pad_extent_mm(board)
    span_w, span_h = hole_span_mm(board)

    def within(low: float, high: float, value: float, half: float) -> bool:
        return low < value - half and value + half < high

    for text, centre, height_mm, _max_width in _legend_labels_drawn(doc, monkeypatch):
        # A letter is upright, so its cap height runs DOWN the strip; a number is turned
        # on its side, so its cap height runs ACROSS it. Each has to sit inside the bare
        # substrate between the outer pads and the board edge, on one of the two edges
        # that carry it.
        if text.isalpha():
            top = within(-margin_y, -extent_y / 2, centre.y(), height_mm / 2)
            bottom = within(span_h + extent_y / 2, span_h + margin_y, centre.y(), height_mm / 2)
            assert top or bottom, f"column letter {text} is not in a top/bottom border strip"
        else:
            left = within(-margin_x, -extent_x / 2, centre.x(), height_mm / 2)
            right = within(span_w + extent_x / 2, span_w + margin_x, centre.x(), height_mm / 2)
            assert left or right, f"row number {text} is not in a left/right border strip"


def test_a_legend_on_a_finger_edge_is_printed_outside_the_fingers(monkeypatch) -> None:
    """Ink goes on the substrate and copper goes on top of it, so a label printed where a
    finger is does not come out faint — it does not come out at all.

    The position used to be measured OUT FROM THE PAD, which is right until the copper on
    that edge is an elongated finger reaching most of the way to the board edge. The board
    this application now opens on has fingers along two entire edges, so every column
    letter was being printed underneath one and the board came up with numbers and no
    letters. The test above does not catch it: its band runs from the grid pad to the
    board edge, and the middle of a finger is inside that band.
    """
    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.geometry import board_edge_margin_mm, hole_span_mm, legend_strip_mm
    from perfboard_studio.model import DocumentMeta

    doc = create_starter_document(DocumentMeta(name="t", created="", modified=""))
    assert doc.board.labels is not None, "the board this opens on prints its own addresses"
    assert {c.edge for c in doc.edge_connectors} == {"top", "bottom"}, "wrong board for this test"

    margin_y = board_edge_margin_mm(doc.board, "vertical")
    inset = legend_strip_mm(doc, "vertical")
    _span_w, span_h = hole_span_mm(doc.board)

    letters = [
        (text, centre, height)
        for text, centre, height, _w in _legend_labels_drawn(doc, monkeypatch)
        if text.isalpha()
    ]
    assert len(letters) == doc.board.cols * 2, "the letters are not being laid down at all"

    for text, centre, height in letters:
        near = -margin_y < centre.y() - height / 2 and centre.y() + height / 2 < -margin_y + inset
        far = (
            span_h + margin_y - inset < centre.y() - height / 2
            and centre.y() + height / 2 < span_h + margin_y
        )
        assert near or far, f"column letter {text} is printed under a connector finger"


def test_board_setup_dialog_round_trips_the_new_board_fields() -> None:
    from perfboard_studio.model import BoardLabels
    from perfboard_studio.ui.main import BoardSetupDialog

    board = _featured_document().board
    dialog = BoardSetupDialog(board)
    assert dialog.board() == board

    dialog.pad_shape.setCurrentIndex(dialog.pad_shape.findData("round"))
    dialog.legend.setChecked(False)
    plain = dialog.board()
    assert plain.pad_shape == "round"
    # The length is dropped with the shape: a round board carrying a pad length would put
    # a field in the file describing nothing.
    assert plain.pad_length is None
    assert plain.labels is None

    dialog.legend.setChecked(True)
    dialog.row_digits.setValue(3)
    assert dialog.board().labels == BoardLabels(row_digits=3)


def test_the_dialog_cannot_produce_an_oblong_pad_the_bus_would_refuse() -> None:
    """A dialog whose only exit is an error message is a worse dialog than one that
    cannot produce the error."""
    from perfboard_studio.commands import DEFAULT_BOARD, SetBoardPayload
    from perfboard_studio.ui.main import BoardSetupDialog

    dialog = BoardSetupDialog(DEFAULT_BOARD)
    dialog.pad_shape.setCurrentIndex(dialog.pad_shape.findData("oblong"))
    dialog.pad_length.setValue(0.5)  # narrower than the 1.9 mm pad width

    bus = _new_bus(_blank_document())
    assert bus.dispatch("board.set", SetBoardPayload(board=dialog.board())).ok


def test_board_features_dialog_adds_four_corner_holes_as_one_undo_step() -> None:
    from perfboard_studio.ui.main import BoardFeaturesDialog

    bus = _new_bus(_blank_document())
    dialog = BoardFeaturesDialog(bus)
    dialog.mount_inset.setValue(1)
    dialog._on_add_corners()

    assert len(bus.document.mounting_holes) == 4
    assert dialog.tree.topLevelItemCount() == 4
    bus.undo()
    assert bus.document.mounting_holes == ()


def test_board_features_dialog_reports_a_refusal_instead_of_swallowing_it() -> None:
    from perfboard_studio.ui.main import BoardFeaturesDialog

    bus = _new_bus(_blank_document())
    dialog = BoardFeaturesDialog(bus)
    dialog.mount_inset.setValue(999)
    dialog._on_add_corners()

    assert bus.document.mounting_holes == ()
    assert dialog.note.text() != ""


def test_board_features_dialog_removes_the_selected_feature() -> None:
    from perfboard_studio.ui.main import BoardFeaturesDialog

    bus = _new_bus(_featured_document())
    dialog = BoardFeaturesDialog(bus)
    assert dialog.tree.topLevelItemCount() == 2

    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
    dialog._on_remove()

    assert bus.document.mounting_holes == ()
    assert len(bus.document.edge_connectors) == 1
    assert dialog.tree.topLevelItemCount() == 1


# ---------------------------------------------------------------------------
# Assembly playback
# ---------------------------------------------------------------------------


def test_the_two_ends_of_the_assembly_slider_mean_different_things() -> None:
    """The bare board and the finished board are the two states somebody actually asks
    for, and they are not the same state. The first version returned -1 for both, so the
    left-hand end of the slider drew a complete board.
    """
    from perfboard_studio.ui.main import assembly_step_for

    assert assembly_step_for(0, 5) == -1, "nothing fitted yet, and no step to highlight"
    assert assembly_step_for(5, 5) is None, "the finished board, as the panel normally is"
    assert assembly_step_for(6, 5) is None, "and past the end is still the finished board"


def test_the_slider_counts_things_fitted_not_steps_done() -> None:
    """Value 1 is "one thing on the board", which is step 0 having just been done."""
    from perfboard_studio.ui.main import assembly_step_for

    assert [assembly_step_for(v, 4) for v in (0, 1, 2, 3, 4)] == [-1, 0, 1, 2, None]


def test_each_slider_position_shows_what_its_caption_claims() -> None:
    """The property the whole thing rests on: at position N the board carries N things,
    and the step being highlighted is the one that put the last of them there."""
    from perfboard_studio.guide import all_steps, build_guide, document_at_step, step_focus
    from perfboard_studio.ui.main import assembly_step_for

    doc = _load_dense()
    guide = build_guide(doc, footprint_lookup())
    steps = all_steps(guide)
    maximum = len(steps)

    for value in range(maximum + 1):
        index = assembly_step_for(value, maximum)
        if index is None:
            continue
        shown = document_at_step(doc, guide, index)
        assert len(shown.components) + len(shown.conductors) == value
        if index >= 0:
            present = {c.id for c in shown.components} | {c.id for c in shown.conductors}
            assert step_focus(steps[index]) in present


# ---------------------------------------------------------------------------
# Naming a net by clicking its pins
#
# The engine has had nets since the first commit and only a KiCad netlist could put one
# in a document, so on a tool for wiring four parts on a scrap of perfboard there was no
# ratsnest, and so no autoroute, LVS or continuity check, without opening a schematic
# capture package first.
# ---------------------------------------------------------------------------


def _bus_with_a_part_and_a_net() -> CommandBus:
    from perfboard_studio.commands import (
        AddNetPayload,
        PlaceComponentPayload,
        create_empty_document,
    )
    from perfboard_studio.model import DocumentMeta

    stamp = "2026-01-01T00:00:00.000Z"
    meta = DocumentMeta(name="t", created=stamp, modified=stamp)
    bus = _new_bus(create_empty_document(meta))
    bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref="R1", value="10k", footprint_id="r-axial-5", anchor=HoleCoord(2, 2)
        ),
    )
    bus.dispatch("net.add", AddNetPayload(name="GND", net_class="ground"))
    return bus


def test_clicking_pins_adds_them_to_the_net_as_one_command() -> None:
    bus = _bus_with_a_part_and_a_net()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)

    scene.arm_net_pins("net-1")
    scene.net_pin_click(HoleCoord(2, 2))
    result = scene.commit_net_pins()

    assert result is not None and result.ok, result
    assert bus.document.nets[0].nodes[0].component_ref == "R1"
    # One command for the session: the undo has to take the whole net back, not a pin.
    bus.undo()
    assert bus.document.nets[0].nodes == ()


def test_a_click_that_cannot_count_says_why_instead_of_being_dropped() -> None:
    """A silently ignored click is indistinguishable from a tool that has stopped
    working, which is why every refusal the command would make is made per click."""
    bus = _bus_with_a_part_and_a_net()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    reasons: list[str] = []
    scene.netPinRejected.connect(reasons.append)

    scene.arm_net_pins("net-1")
    scene.net_pin_click(HoleCoord(20, 20))  # empty hole
    scene.net_pin_click(HoleCoord(2, 2))
    scene.net_pin_click(HoleCoord(2, 2))  # the same pin twice

    assert scene.picked_pins() == (("R1", "1"),)
    assert len(reasons) == 2
    assert "No component pin" in reasons[0]
    assert "already on the list" in reasons[1]


def test_a_pin_another_net_already_has_is_refused_at_the_click() -> None:
    from perfboard_studio.commands import AddNetPayload, ConnectPinsPayload
    from perfboard_studio.model import NetNode

    bus = _bus_with_a_part_and_a_net()
    bus.dispatch(
        "net.connect", ConnectPinsPayload(id="net-1", nodes=(NetNode("R1", "1"),))
    )
    bus.dispatch("net.add", AddNetPayload(name="+5V", net_class="power"))
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    reasons: list[str] = []
    scene.netPinRejected.connect(reasons.append)

    scene.arm_net_pins("net-2")
    scene.net_pin_click(HoleCoord(2, 2))

    assert scene.picked_pins() == ()
    assert "GND" in reasons[0]


def test_committing_nothing_is_a_cancel_rather_than_an_empty_command() -> None:
    bus = _bus_with_a_part_and_a_net()
    before = bus.document
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)

    scene.arm_net_pins("net-1")
    assert scene.commit_net_pins() is None
    assert bus.document is before
    assert scene.armed_net_id is None


def test_arming_a_drawing_tool_ends_a_pin_session() -> None:
    """The three board modes are mutually exclusive: a click has to mean one thing."""
    bus = _bus_with_a_part_and_a_net()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)

    scene.arm_net_pins("net-1")
    scene.arm_drawing("bare-wire")

    assert scene.armed_net_id is None


def test_a_rebuild_mid_session_keeps_the_pins_already_picked() -> None:
    """Every command rebuilds the scene, and a half-collected net whose markers vanished
    would read as the clicks having been lost."""
    bus = _bus_with_a_part_and_a_net()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)

    scene.arm_net_pins("net-1")
    scene.net_pin_click(HoleCoord(2, 2))
    scene.set_document(bus.document)

    assert scene.armed_net_id == "net-1"
    assert scene.picked_pins() == (("R1", "1"),)
    assert any(isinstance(item, view2d.PickedPinsItem) for item in scene.items())


def test_arming_an_unknown_net_collects_nothing() -> None:
    bus = _bus_with_a_part_and_a_net()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)

    scene.arm_net_pins("net-does-not-exist")

    assert scene.armed_net_id is None


# ---------------------------------------------------------------------------
# The Net menu and the Nets panel
# ---------------------------------------------------------------------------


class _StubNetDialog:
    """Stands in for NetDialog, which is modal and would wait forever headless."""

    values_to_return: tuple = ("GND", "ground", None, None)
    accepted = True
    #: How many times exec() accepts before it rejects, or None for "always". A refused
    #: net brings the form back, so a stub that always accepted would never let go.
    accept_times: int | None = None
    opened = 0

    def __init__(self, *args, **kwargs) -> None:
        type(self).opened += 1

    def exec(self) -> int:
        from PySide6.QtWidgets import QDialog

        accepted = self.accepted
        if self.accept_times is not None:
            accepted = accepted and type(self).opened <= self.accept_times
        return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

    def values(self) -> tuple:
        return self.values_to_return


def test_new_net_creates_it_and_goes_straight_into_picking_its_pins(monkeypatch) -> None:
    """Naming a net and then hunting for the command that fills it would be two decisions
    where the user made one, and an empty net does nothing for anybody."""
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    monkeypatch.setattr(main_module, "NetDialog", _StubNetDialog)
    _StubNetDialog.values_to_return = ("HAND-WIRED", "signal", None, None)

    window.on_new_net()

    net = next(n for n in window.bus.document.nets if n.name == "HAND-WIRED")
    assert window.scene.armed_net_id == net.id
    window.scene.arm_net_pins(None)
    _close(window)


def test_a_refused_new_net_leaves_the_document_alone(monkeypatch) -> None:
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    existing = window.bus.document.nets[0].name
    monkeypatch.setattr(main_module, "NetDialog", _StubNetDialog)
    _StubNetDialog.values_to_return = (existing, "signal", None, None)
    _StubNetDialog.accept_times = 1
    _StubNetDialog.opened = 0
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    before = window.bus.document

    window.on_new_net()

    assert window.bus.document is before
    _StubNetDialog.accept_times = None
    _close(window)


def test_the_nets_panel_lists_each_nets_pins_so_they_can_be_taken_off_it() -> None:
    """The panel was a readout; a pin has to be visible to be selected, and selectable to
    be disconnected."""
    window = _window_on(_load_dense())
    tree = window.nets_tree

    first = tree.topLevelItem(0)
    assert first is not None
    net = next(n for n in window.bus.document.nets if n.id == first.data(0, ROLE_NET_ID))
    assert first.childCount() == len(net.nodes)

    pin_row = first.child(0)
    assert pin_row is not None
    first.setExpanded(True)
    pin_row.setSelected(True)
    assert window._selected_pins() == ((net.id, net.nodes[0].component_ref, net.nodes[0].pin),)

    window.on_disconnect_pins()

    after = next(n for n in window.bus.document.nets if n.id == net.id)
    assert after.nodes == net.nodes[1:]
    _close(window)


def test_the_panel_keeps_a_net_open_across_the_command_that_empties_a_row() -> None:
    """Expansion is restored for the same reason selection is: the rows are rebuilt after
    every command, and a net opened to take a pin off it must not close as it is taken."""
    window = _window_on(_load_dense())
    first = window.nets_tree.topLevelItem(0)
    assert first is not None
    net_id = first.data(0, ROLE_NET_ID)
    first.setExpanded(True)
    pin_row = first.child(0)
    assert pin_row is not None
    pin_row.setSelected(True)

    window.on_disconnect_pins()

    reopened = next(
        window.nets_tree.topLevelItem(i)
        for i in range(window.nets_tree.topLevelItemCount())
        if window.nets_tree.topLevelItem(i).data(0, ROLE_NET_ID) == net_id
    )
    assert reopened.isExpanded()
    _close(window)


def test_deleting_a_net_keeps_its_copper_and_releases_the_claim(monkeypatch) -> None:

    from perfboard_studio.commands import AddConductorPayload, NewSolderTraceConductor

    window = _window_on(_load_dense())
    net = window.bus.document.nets[0]
    window.bus.dispatch(
        "conductor.add",
        AddConductorPayload(
            conductor=NewSolderTraceConductor(
                path=(HoleCoord(0, 0), HoleCoord(1, 0)), net_id=net.id
            )
        ),
    )
    conductors_before = len(window.bus.document.conductors)
    window._select_net(net.id)
    # The confirmation puts Cancel under Enter and carries the verb on its button, so it
    # is a box of the window's own rather than QMessageBox.question -- stubbed as such.
    monkeypatch.setattr(type(window), "_confirm", lambda self, *a, **k: True)

    window.on_delete_net()

    assert all(n.id != net.id for n in window.bus.document.nets)
    assert len(window.bus.document.conductors) == conductors_before
    assert all(c.net_id != net.id for c in window.bus.document.conductors)
    _close(window)




# ---------------------------------------------------------------------------
# Telling the user what state the board is in
#
# Placing, drawing and picking pins all arm a mode in which a click means something
# other than what it usually means, and the only place any of them said so was the
# status bar -- the bottom edge of a window a metre wide, while the cursor is in the
# middle of the board. A mode nobody can see is indistinguishable from an application
# that has stopped responding.
# ---------------------------------------------------------------------------


def test_the_armed_mode_is_named_over_the_board() -> None:
    window = _window_on(_load_dense())

    window.scene.arm_placement("r-axial-5")

    assert not window.view.mode_banner.isHidden()
    assert "Placing" in window.view.mode_banner.text()
    window.scene.arm_placement(None)
    assert window.view.mode_banner.isHidden()
    _close(window)


def test_the_banner_follows_the_pins_as_they_are_picked() -> None:
    from perfboard_studio.commands import AddNetPayload
    from perfboard_studio.geometry import all_pin_holes

    window = _window_on(_load_dense())
    window.bus.dispatch("net.add", AddNetPayload(name="HAND", net_class="ground"))
    net = next(n for n in window.bus.document.nets if n.name == "HAND")
    taken = {(node.component_ref, node.pin) for n in window.bus.document.nets for node in n.nodes}
    free = next(
        hole
        for comp in window.bus.document.components
        if (fp := window.lookup(comp.footprint_id)) is not None
        for pin, hole in all_pin_holes(comp, fp)
        if (comp.ref, pin.number) not in taken
    )

    window.scene.arm_net_pins(net.id)
    assert "HAND" in window.view.mode_banner.text()
    window.scene.net_pin_click(free)

    assert "." in window.view.mode_banner.text()  # the pin it just took, "R1.2"
    window.scene.commit_net_pins()
    assert window.view.mode_banner.isHidden()
    _close(window)


def test_an_empty_board_says_what_to_do_with_itself() -> None:
    """The application opens on a blank 5 x 7, and every route, check and export needs
    something on it first."""
    from perfboard_studio.commands import PlaceComponentPayload, create_starter_document
    from perfboard_studio.model import DocumentMeta

    stamp = "2026-01-01T00:00:00.000Z"
    meta = DocumentMeta(name="t", created=stamp, modified=stamp)
    window = _window_on(create_starter_document(meta))

    assert not window.view.empty_hint.isHidden()

    window.bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref="R1", value="10k", footprint_id="r-axial-5", anchor=HoleCoord(2, 2)
        ),
    )

    assert window.view.empty_hint.isHidden()
    _close(window)


def test_the_guidance_gets_out_of_the_way_of_a_mode() -> None:
    """Somebody mid-mode is plainly not stuck, and two blocks of text over one board is
    one too many."""
    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta

    stamp = "2026-01-01T00:00:00.000Z"
    meta = DocumentMeta(name="t", created=stamp, modified=stamp)
    window = _window_on(create_starter_document(meta))
    assert not window.view.empty_hint.isHidden()

    window.scene.arm_placement("r-axial-5")

    assert window.view.empty_hint.isHidden()
    window.scene.arm_placement(None)
    assert not window.view.empty_hint.isHidden()
    _close(window)


def test_the_overlays_never_eat_a_click() -> None:
    """They sit over the board, and the whole point of a mode is that the next click
    reaches the board. An overlay that swallowed the click it was describing would be
    worse than no overlay at all."""
    from PySide6.QtCore import Qt as QtCore_Qt

    window = _window_on(_load_dense())

    for overlay in (window.view.mode_banner, window.view.empty_hint):
        assert overlay.testAttribute(QtCore_Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    _close(window)


# ---------------------------------------------------------------------------
# The findings panel
# ---------------------------------------------------------------------------


def _drc_group(window, key):
    for i in range(window.drc_tree.topLevelItemCount()):
        root = window.drc_tree.topLevelItem(i)
        for j in range(root.childCount()):
            if root.child(j).data(0, _finding_key_role()) == key:
                return root.child(j)
    return None


def _finding_key_role():
    from perfboard_studio.ui.main import ROLE_FINDING_KEY

    return ROLE_FINDING_KEY


def test_an_expanded_rule_stays_expanded_across_an_edit() -> None:
    """The panel rebuilt from clear() on every command, so working through a rule meant
    re-expanding it after every attempt to fix what the rule was complaining about."""
    window = _window_on(_load_dense())
    rule = next(
        key
        for key in (
            f"drc:{v.rule}" for v in window._last_violations
        )
    )
    _drc_group(window, rule).setExpanded(True)

    window.on_bus_changed(window.bus.document, None)

    assert _drc_group(window, rule).isExpanded() is True
    _close(window)


def test_a_rule_that_gained_a_violation_still_restores_by_name() -> None:
    """Remembering row indices would restore the wrong groups exactly when the list
    changed, which is the only time it matters."""
    window = _window_on(_load_dense())
    keys = [
        f"drc:{v.rule}" for v in window._last_violations
    ]
    last = sorted(set(keys))[-1]
    _drc_group(window, last).setExpanded(True)

    assert last in window._expanded_drc_keys()
    _close(window)


def test_the_findings_can_be_filtered_down_to_one_rule() -> None:
    """A board mid-layout carries a hundred proximity warnings, and "show me the errors"
    is how anybody reads a list that long."""
    window = _window_on(_load_dense())
    rules = {v.rule for v in window._last_violations}
    assert len(rules) > 1, "the fixture needs more than one rule for this to mean anything"
    wanted = sorted(rules)[0]

    window.drc_filter.setText(wanted)

    shown = {
        window.drc_tree.topLevelItem(0).child(j).text(0).split(" ")[0]
        for j in range(window.drc_tree.topLevelItem(0).childCount())
    }
    assert shown == {wanted}
    _close(window)


def _board_with_a_corner_bore() -> PerfDocument:
    from perfboard_studio.model import DocumentMeta, MountingHole

    board = Board(
        type="pad-per-hole", cols=16, rows=12, pitch=2.54, thickness=1.6,
        material="FR4", pad_diameter=1.9, drill_diameter=0.8,
    )
    return PerfDocument(
        meta=DocumentMeta(name="t", created="2024-01-01T00:00:00.000Z",
                          modified="2024-01-01T00:00:00.000Z"),
        board=board,
        mounting_holes=(MountingHole(id="m1", at=HoleCoord(col=2, row=2), diameter=3.2),),
    )


def test_the_ghost_goes_red_over_a_mounting_bore() -> None:
    """The bore has destroyed the pad, so there is nothing there to solder a lead into --
    DRC has always called that an error, and the ghost stayed green right up to the click.
    """
    from perfboard_studio.geometry import consumed_holes, hole_key

    doc = _board_with_a_corner_bore()
    bus = _new_bus(doc)
    scene = BoardScene(doc, footprint_lookup(), side="top", bus=bus)
    scene.arm_placement("r-axial-3")

    consumed = consumed_holes(doc)
    dead = next(
        HoleCoord(col=c, row=r)
        for c in range(doc.board.cols)
        for r in range(doc.board.rows)
        if hole_key(HoleCoord(col=c, row=r)) in consumed
    )

    assert scene.placement_lands_on_nothing(dead) is True
    assert scene._placement_blocked(dead) is True
    # ...and somewhere with a pad is still fine, or the check would just say no to
    # everything.
    assert scene.placement_lands_on_nothing(HoleCoord(col=10, row=8)) is False


def test_a_part_dropped_on_a_bore_says_so_rather_than_only_placing_it() -> None:
    from perfboard_studio.geometry import consumed_holes, hole_key

    window = _window_on(_board_with_a_corner_bore())
    window.scene.arm_placement("r-axial-3")
    consumed = consumed_holes(window.bus.document)
    dead = next(
        HoleCoord(col=c, row=r)
        for c in range(window.bus.document.board.cols)
        for r in range(window.bus.document.board.rows)
        if hole_key(HoleCoord(col=c, row=r)) in consumed
    )

    window.scene.place_armed(dead)

    assert window.scene.last_placement_on_a_dead_hole is True
    assert "no pad" in window.statusBar().currentMessage()
    # DRC is still the authority and still calls it an error.
    assert any(v.rule == "mounting-hole-conflict" for v in window._last_violations)
    _close(window)


def test_the_blank_board_guidance_stops_once_a_part_has_ever_been_placed() -> None:
    """It is for the first launch. Repeating it forever is the application explaining its
    own front door to somebody who has been through it a hundred times -- and there is
    nowhere to click it away, because the block is transparent to the mouse by design."""
    from perfboard_studio.model import DocumentMeta

    blank = PerfDocument(
        meta=DocumentMeta(name="t", created="2024-01-01T00:00:00.000Z",
                          modified="2024-01-01T00:00:00.000Z"),
        board=Board(type="pad-per-hole", cols=16, rows=12, pitch=2.54, thickness=1.6,
                    material="FR4", pad_diameter=1.9, drill_diameter=0.8),
    )

    first = _window_on(blank)
    assert first.view.empty_hint.isHidden() is False
    first.scene.arm_placement("r-axial-3")
    first.scene.place_armed(HoleCoord(col=4, row=4))
    _close(first)

    second = _window_on(blank)
    assert second.view.empty_hint.isHidden() is True
    _close(second)


def _two_traces_side_by_side() -> PerfDocument:
    """Two solder traces on neighbouring rows, on different nets. The commonest shape on
    a routed perfboard, and the one the rule stopped objecting to."""
    from perfboard_studio.model import ComponentInstance, DocumentMeta, Net, NetNode

    board = Board(
        type="pad-per-hole", cols=20, rows=12, pitch=2.54, thickness=1.6,
        material="FR4", pad_diameter=1.9, drill_diameter=0.8,
    )

    def trace(cid: str, net_id: str, row: int) -> SolderTraceConductor:
        return SolderTraceConductor(
            id=cid, kind="solder-trace", side="bottom", net_id=net_id,
            path=tuple(HoleCoord(col=c, row=row) for c in range(2, 10)),
        )

    def part(ref: str, row: int) -> ComponentInstance:
        return ComponentInstance(
            id=f"cmp-{ref}", ref=ref, value="", footprint_id="r-axial-3",
            anchor=HoleCoord(col=2, row=row),
        )

    return PerfDocument(
        meta=DocumentMeta(name="t", created="2024-01-01T00:00:00.000Z",
                          modified="2024-01-01T00:00:00.000Z"),
        board=board,
        components=(part("R1", 3), part("R2", 4)),
        nets=(
            Net(id="n1", name="A", net_class="signal",
                nodes=(NetNode(component_ref="R1", pin="1"),)),
            Net(id="n2", name="B", net_class="signal",
                nodes=(NetNode(component_ref="R2", pin="1"),)),
        ),
        conductors=(trace("t1", "n1", 3), trace("t2", "n2", 4)),
    )


def test_two_traces_side_by_side_are_not_the_panel_any_more() -> None:
    """Eight pads of ordinary parallel routing used to put SIXTEEN copies of one sentence
    in the panel -- once per pad per trace, since both runs can see the same 0.6 mm gap --
    and scrolled everything else off the bottom.

    The panel gathering them was the first answer, and it was a workaround for the wrong
    layer: the rule was objecting to how dense perfboard is built. It now reports a
    physical pair ONCE, and only where the neighbour is a PIN -- see the rule's docstring
    in drc.py for why a run beside a run is a different kind of risk from a run beside a
    part somebody soldered three phases ago. What is left on this fixture is the two
    places a run passes the other part's pin, which is the real thing.
    """
    window = _window_on(_two_traces_side_by_side())

    proximity = _drc_group(window, "drc:solder-trace-proximity")
    assert proximity is not None, "a run still passes a pin here"
    findings = sum(proximity.child(i).childCount() or 1 for i in range(proximity.childCount()))

    assert findings == 2, "the two runs passing each other's pins, and nothing else"
    _close(window)


def _trace_along_a_dip() -> PerfDocument:
    """A solder run down the column beside a DIP-14's pin row: seven pins of another net,
    each one an orthogonal neighbour. The shape the panel's gathering is actually for."""
    from perfboard_studio.model import ComponentInstance, DocumentMeta, Net, NetNode

    board = Board(
        type="pad-per-hole", cols=20, rows=16, pitch=2.54, thickness=1.6,
        material="FR4", pad_diameter=1.9, drill_diameter=0.8,
    )
    return PerfDocument(
        meta=DocumentMeta(name="t", created="2024-01-01T00:00:00.000Z",
                          modified="2024-01-01T00:00:00.000Z"),
        board=board,
        components=(
            ComponentInstance(
                id="cmp-U1", ref="U1", value="", footprint_id="dip-14",
                anchor=HoleCoord(col=4, row=3),
            ),
        ),
        nets=(
            Net(id="n1", name="A", net_class="signal",
                nodes=(NetNode(component_ref="U1", pin="8"),)),
            Net(id="n2", name="B", net_class="signal",
                nodes=tuple(
                    NetNode(component_ref="U1", pin=str(n)) for n in range(1, 8)
                )),
        ),
        conductors=(
            SolderTraceConductor(
                id="t1", kind="solder-trace", side="bottom", net_id="n1",
                path=tuple(HoleCoord(col=5, row=r) for r in range(3, 10)),
            ),
        ),
    )


def test_a_run_past_a_row_of_pins_is_one_row_with_every_pad_underneath() -> None:
    """What the gathering is for, now that the noisy case is gone from the engine.

    Seven pins of one net down the side of a DIP, and a run passing every one of them:
    seven findings that are one sentence about one run, which is a row in the panel with
    all seven still reachable one level down. Nothing is dropped -- that was the whole
    point of gathering rather than capping.
    """
    window = _window_on(_trace_along_a_dip())

    proximity = _drc_group(window, "drc:solder-trace-proximity")
    assert proximity is not None, "the fixture should trip the proximity rule"
    findings = sum(proximity.child(i).childCount() or 1 for i in range(proximity.childCount()))

    assert proximity.childCount() == 1, "one row: one run"
    assert findings == 7, "and every pad still reachable underneath"
    assert "–" in proximity.child(0).text(0), "named by where it runs"
    _close(window)


def test_a_severity_has_the_same_colour_in_the_tree_as_on_the_status_bar() -> None:
    from perfboard_studio.ui.theme import ERROR, WARNING

    window = _window_on(_load_dense())
    root = window.drc_tree.topLevelItem(0)
    by_rule = {v.rule: v.severity for v in window._last_violations}

    for j in range(root.childCount()):
        item = root.child(j)
        rule = item.text(0).split(" ")[0]
        expected = ERROR if by_rule[rule] == "error" else WARNING
        assert item.foreground(0).color().name() == expected, rule
    _close(window)


# ---------------------------------------------------------------------------
# Files dropped on the window
# ---------------------------------------------------------------------------


#: Mime payloads the drop events below point at. QDropEvent does NOT take ownership of
#: its QMimeData, so without a Python reference the object is collected while the event
#: still holds a pointer to it -- and the handler reads freed memory, which on Windows is
#: an access violation rather than an exception.
_DROPPED_MIME: list = []


def _drop_of(*paths):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDropEvent

    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    _DROPPED_MIME.append(data)
    return QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_a_board_dropped_on_the_window_opens_it(tmp_path) -> None:
    """The gesture everyone tries first with a file, and nothing happened -- which reads
    as the application refusing that kind of file rather than refusing drops."""
    window = _window_on(_load_dense())
    board = tmp_path / "dropped.perf"
    board.write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    window._saved_document = window.bus.document  # nothing unsaved, so no guard dialog

    window.dropEvent(_drop_of(board))

    assert window.current_path == board
    _close(window)


def test_a_netlist_dropped_on_the_window_is_imported(tmp_path, monkeypatch) -> None:
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    netlist = tmp_path / "circuit.net"
    netlist.write_text("(export (version D))", encoding="utf-8")
    imported: list = []
    monkeypatch.setattr(
        main_module.MainWindow, "import_netlist_from", lambda self, path: imported.append(path)
    )

    window.dropEvent(_drop_of(netlist))

    assert imported == [netlist]
    _close(window)


def test_a_drop_this_window_cannot_open_is_declined(tmp_path) -> None:
    window = _window_on(_load_dense())
    before = window.current_path

    window.dropEvent(_drop_of(tmp_path / "holiday.jpg"))
    # ...and five boards at once is an instruction this window cannot carry out; picking
    # one at random would be a worse answer than declining.
    window.dropEvent(_drop_of(tmp_path / "a.perf", tmp_path / "b.perf"))

    assert window.current_path == before
    _close(window)


# ---------------------------------------------------------------------------
# Right-click
# ---------------------------------------------------------------------------


def _menu_labels(menu) -> list[str]:
    return [a.text().replace("&", "") for a in menu.actions() if not a.isSeparator()]


def test_right_clicking_a_part_offers_what_can_be_done_to_it() -> None:
    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    item = window.scene.component_items[component.id]
    pos = window.view.mapFromScene(item.pos())

    menu = window.board_menu(pos)

    assert "Properties…" in _menu_labels(menu)
    assert "Rotate Clockwise" in _menu_labels(menu)
    # ...and selected it, so the menu is about the part that was clicked.
    assert window.scene.selected_component_ids() == (component.id,)
    _close(window)


def test_right_clicking_bare_board_offers_what_can_be_done_to_the_board() -> None:
    window = _window_on(_load_dense())
    window.scene.select_components([])

    labels = _menu_labels(window.board_menu(QPoint(2, 2)))

    assert "Paste" in labels and "Board Setup…" in labels
    assert "Rotate Clockwise" not in labels
    _close(window)


def test_the_context_menu_holds_the_same_actions_as_the_menu_bar() -> None:
    """A second list of what can be done to a part is a second list free to disagree with
    the first about which of them are available."""
    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    item = window.scene.component_items[component.id]

    menu = window.board_menu(window.view.mapFromScene(item.pos()))

    assert window.act_properties in menu.actions()
    assert window.act_delete in menu.actions()
    _close(window)


def test_a_right_click_that_finished_a_trace_does_not_also_open_a_menu() -> None:
    """Right-click already means "finish" on this board, and Windows delivers the
    context-menu event after the release -- by which time the mode is gone and a menu
    built on "is a mode armed" would appear on top of the trace just committed."""
    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_drawing("solder-trace")
    scene.draw_click(HoleCoord(2, 2))
    scene.draw_click(HoleCoord(3, 2))

    scene.mousePressEvent(_press_at(QPointF(0, 0), Qt.MouseButton.RightButton))

    assert scene.armed_draw_kind is None, "the right-click should have finished the trace"
    assert scene.take_consumed_right_click() is True
    assert scene.take_consumed_right_click() is False, "the answer is spent once read"


def _press_at(pos: QPointF, button):
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    event = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    event.setScenePos(pos)
    event.setButton(button)
    return event


def test_the_findings_can_be_copied_out_as_text() -> None:
    """A DRC message is what somebody pastes into a forum post asking why their board
    does not work."""
    from PySide6.QtWidgets import QApplication as QApp

    window = _window_on(_load_dense())

    window._copy_all_findings()

    copied = QApp.clipboard().text()
    assert copied
    assert any(v.message in copied for v in window._last_violations)
    _close(window)


# ---------------------------------------------------------------------------
# What the window remembers between runs
# ---------------------------------------------------------------------------


def test_a_closed_window_hands_its_layout_to_the_next_one() -> None:
    """Every one of these used to reset on launch, so the people who use the tool most
    re-arranged it most."""
    from perfboard_studio.ui.boardcolors import choose as choose_colour
    from perfboard_studio.ui.boardcolors import chosen_key
    from perfboard_studio.ui.main import BOARD_COLOUR_KEY, GEOMETRY_KEY, app_settings

    first = _window_on(_load_dense())
    first.act_ratsnest.setChecked(False)
    first.act_hatch.setChecked(False)
    first.on_board_colour("blue")
    first.on_routing_style("solder")
    _close(first)

    assert app_settings().value(GEOMETRY_KEY) is not None
    assert app_settings().value(BOARD_COLOUR_KEY) == "blue"

    # The chosen scheme is module state and would still be blue in this process whatever
    # the store said, so it is put back first: otherwise this test passes with the restore
    # deleted, which is the one thing it exists to check.
    choose_colour(None)
    second = _window_on(_load_dense())
    assert second.act_ratsnest.isChecked() is False
    assert second.scene.show_ratsnest is False
    assert second.act_hatch.isChecked() is False
    assert chosen_key() == "blue"
    assert second._routing_style == "solder"
    assert second.act_style["solder"].isChecked() is True
    _close(second)
    choose_colour(None)


def test_a_close_the_user_backed_out_of_records_nothing(monkeypatch) -> None:
    """A window that is still open has not been left, and its layout is not a decision."""
    from perfboard_studio.ui.main import GEOMETRY_KEY, MainWindow, app_settings

    window = _window_on(_load_dense())
    monkeypatch.setattr(MainWindow, "_offer_to_save", lambda self: False)

    window.close()

    assert app_settings().value(GEOMETRY_KEY) is None
    monkeypatch.undo()
    _close(window)


def test_the_3d_panel_starts_closed_however_it_was_left() -> None:
    """Restoring it open would build VTK's whole pipeline during startup to show a board
    nobody has looked at yet. Its size still comes back with the rest of the layout."""
    first = _window_on(_load_dense())
    first.dock_3d.show()
    _close(first)

    second = _window_on(_load_dense())
    assert second.dock_3d.isVisible() is False
    assert second.vtk_widget is None
    _close(second)


def test_choosing_a_language_records_it_for_the_next_start(monkeypatch) -> None:
    """Applied at the next start rather than live: every label in the window was
    translated once as it was built, and the widgets a rebuild missed would be exactly
    the ones nobody would notice had stayed English."""
    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui.main import LANGUAGE_KEY, app_settings

    window = _window_on(_load_dense())
    told: list[str] = []
    monkeypatch.setattr(
        main_module.QMessageBox, "information", lambda *args, **kwargs: told.append(args[1])
    )

    window.on_language("tr")

    assert app_settings().value(LANGUAGE_KEY) == "tr"
    assert window.act_language["tr"].isChecked() is True
    assert window.act_language["en"].isChecked() is False
    assert told, "a change that only happens next time has to say so"
    _close(window)


def test_a_tick_survives_the_ini_backends_idea_of_a_boolean(tmp_path) -> None:
    """QSettings is not one format: the registry keeps a bool a bool, the INI backend
    writes the string "true" -- and "false" is truthy, so a plain bool() would restore
    every toggle to on and the bug would never show on Windows."""
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui.main import _stored_bool

    store = QSettings(str(tmp_path / "probe.ini"), QSettings.Format.IniFormat)
    for written, expected in (("false", False), ("true", True), (False, False), (True, True)):
        store.setValue("probe", written)
        assert _stored_bool(store, "probe", True) is expected, written
    assert _stored_bool(store, "never/written", True) is True


# ---------------------------------------------------------------------------
# The files you were last working on
# ---------------------------------------------------------------------------


def test_opening_a_document_puts_it_on_the_recent_list(tmp_path) -> None:
    window = _window_on(_load_dense())
    board = tmp_path / "board.perf"
    board.write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")

    window._load_path(board)

    assert window._recent_paths() == [str(board.resolve())]
    assert next(a.text() for a in window.menu_recent.actions()).endswith("board.perf")
    _close(window)


def test_the_recent_list_moves_a_repeat_to_the_top_rather_than_listing_it_twice(
    tmp_path,
) -> None:
    window = _window_on(_load_dense())
    first = tmp_path / "one.perf"
    second = tmp_path / "two.perf"
    for path in (first, second):
        path.write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")

    window._remember_path(first)
    window._remember_path(second)
    window._remember_path(first)

    assert window._recent_paths() == [str(first.resolve()), str(second.resolve())]
    _close(window)


def test_the_recent_list_is_capped(tmp_path) -> None:
    window = _window_on(_load_dense())
    for index in range(window.RECENT_LIMIT + 3):
        path = tmp_path / f"b{index}.perf"
        path.write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
        window._remember_path(path)

    assert len(window._recent_paths()) == window.RECENT_LIMIT
    _close(window)


def test_a_file_that_has_gone_away_is_left_out_of_the_menu(tmp_path) -> None:
    """Skipped rather than shown greyed out: a list of names that no longer open anything
    is a list you stop reading."""
    window = _window_on(_load_dense())
    path = tmp_path / "gone.perf"
    path.write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    window._remember_path(path)
    path.unlink()

    window._refresh_recent_menu()

    labels = [a.text() for a in window.menu_recent.actions()]
    assert not any("gone.perf" in label for label in labels)
    _close(window)


def test_clearing_the_recent_list_empties_the_menu(tmp_path) -> None:
    window = _window_on(_load_dense())
    path = tmp_path / "one.perf"
    path.write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    window._remember_path(path)

    window.on_clear_recent()

    assert window._recent_paths() == []
    assert [a.text() for a in window.menu_recent.actions()] == ["(nothing yet)"]
    _close(window)


def test_undo_and_redo_say_whether_there_is_anything_to_do(tmp_path) -> None:
    """The bus has always known both; the window simply never asked, so an undo at the
    bottom of the stack looked identical to one that worked."""
    from perfboard_studio.commands import AddNetPayload

    window = _window_on(_load_dense())
    assert window.act_undo.isEnabled() is False
    assert window.act_redo.isEnabled() is False

    window.bus.dispatch("net.add", AddNetPayload(name="HAND"))
    assert window.act_undo.isEnabled() is True
    assert "HAND" in window.act_undo.toolTip()

    window.bus.undo()
    assert window.act_undo.isEnabled() is False
    assert window.act_redo.isEnabled() is True
    _close(window)


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------


def test_the_nets_panel_filters_by_name_and_by_pin() -> None:
    """Half the time the question is "what is U1 pin 3 on", not "where is GND"."""
    window = _window_on(_load_dense())
    all_rows = window.nets_tree.topLevelItemCount()
    assert all_rows > 1

    window.nets_filter.setText("gnd")
    named = [
        window.nets_tree.topLevelItem(i).text(0)
        for i in range(window.nets_tree.topLevelItemCount())
    ]
    assert named and all("gnd" in name.lower() for name in named)

    node = window.bus.document.nets[0].nodes[0]
    window.nets_filter.setText(f"{node.component_ref}.{node.pin}")
    assert window.nets_tree.topLevelItemCount() == 1

    window.nets_filter.clear()
    assert window.nets_tree.topLevelItemCount() == all_rows
    _close(window)


def test_a_part_whose_name_the_dock_cannot_fit_carries_it_in_a_tooltip() -> None:
    window = _window_on(_load_dense())
    tree = window.library_tree
    group = tree.topLevelItem(0)
    assert group is not None and group.childCount()
    leaf = group.child(0)

    assert leaf.text(0) in leaf.toolTip(0)
    _close(window)


# ---------------------------------------------------------------------------
# The shortcut card
# ---------------------------------------------------------------------------


def test_the_shortcut_card_is_read_off_the_real_menu_bar() -> None:
    """A hand-kept list goes stale the first time an action moves, and a stale shortcut
    card teaches something that no longer works."""
    from perfboard_studio.ui.main import ShortcutsDialog

    window = _window_on(_load_dense())

    listed = ShortcutsDialog.menu_shortcuts(window._menus)
    flat = {label: keys for _menu, rows in listed for label, keys in rows}

    assert flat["Save"] == window.act_save.shortcut().toString()
    assert flat["Autoroute All Nets"] == "Ctrl+R"
    assert "Rotate Clockwise" in flat
    # Read from the menu, so an action with no binding must not appear at all.
    assert "Finish Adding Pins" not in flat
    _close(window)


def test_no_two_actions_claim_the_same_shortcut() -> None:
    """Two actions on one binding means one of them cannot be reached, and Qt reports it
    only as an "ambiguous shortcut overload" at the moment it is pressed."""
    from perfboard_studio.ui.main import ShortcutsDialog

    window = _window_on(_load_dense())

    seen: dict[str, str] = {}
    clashes = []
    for _menu, rows in ShortcutsDialog.menu_shortcuts(window._menus):
        for label, keys in rows:
            if keys in seen:
                clashes.append(f"{keys}: {seen[keys]} and {label}")
            seen[keys] = label

    assert clashes == [], f"shortcuts claimed twice: {clashes}"
    _close(window)


def test_the_board_gestures_are_listed_because_no_menu_carries_them() -> None:
    """Middle-drag to pan, right-click to finish a run, arrows to nudge: none of them is
    an action anywhere, so until this dialog the only way to find out was the source."""
    from perfboard_studio.ui.main import ShortcutsDialog

    gestures = dict((keys, what) for keys, what in ShortcutsDialog.BOARD_GESTURES)

    assert "Middle-drag" in gestures
    assert "Esc" in gestures
    assert "Arrow keys" in gestures


def test_the_menus_survive_a_garbage_collection() -> None:
    """QMenuBar.addMenu hands Python a QMenu it believes it owns, so a menu held only by a
    local in the builder can be destroyed the moment that method returns -- leaving a menu
    bar of actions pointing at freed menus. Found by the shortcut card, which was the
    first thing ever to walk the menus after building them."""
    import gc

    window = _window_on(_load_dense())

    gc.collect()

    assert window.act_save.shortcut().toString() == "Ctrl+S"
    assert all(menu.actions() is not None for menu in window._menus)
    _close(window)


# ---------------------------------------------------------------------------
# Joining two pins in two clicks
#
# Declaring a net, filling it and routing it is the honest model, and it was also four
# steps deep in two menus before a single pin could be joined to anything. Most of the
# time nobody is thinking "I shall declare a net"; they are pointing at two legs.
# ---------------------------------------------------------------------------


def _hole_of(window, ref: str, pin: str) -> HoleCoord:
    from perfboard_studio.geometry import all_pin_holes

    comp = next(c for c in window.bus.document.components if c.ref == ref)
    footprint = window.lookup(comp.footprint_id)
    return next(hole for p, hole in all_pin_holes(comp, footprint) if p.number == pin)


def _free_pins(window) -> list[tuple[str, str]]:
    """Pins on the board that no net has claimed."""
    from perfboard_studio.geometry import all_pin_holes

    taken = {(n.component_ref, n.pin) for net in window.bus.document.nets for n in net.nodes}
    return [
        (comp.ref, pin.number)
        for comp in window.bus.document.components
        if (footprint := window.lookup(comp.footprint_id)) is not None
        for pin, _hole in all_pin_holes(comp, footprint)
        if (comp.ref, pin.number) not in taken
    ]


def test_two_free_pins_get_a_net_of_their_own() -> None:
    window = _window_on(_load_dense())
    first, second = _free_pins(window)[:2]

    window.scene.arm_connect(True)
    window.scene.connect_click(_hole_of(window, *first))
    result = window.scene.connect_click(_hole_of(window, *second))

    assert result is not None and result.ok, result
    made = window.bus.document.nets[-1]
    assert made.name == "N1"
    assert {(n.component_ref, n.pin) for n in made.nodes} == {first, second}
    _close(window)


def test_a_pin_joined_to_a_pin_on_a_net_joins_that_net() -> None:
    """What a person pointing at a leg and then at a rail means."""
    window = _window_on(_load_dense())
    net = next(n for n in window.bus.document.nets if n.nodes)
    on_net = (net.nodes[0].component_ref, net.nodes[0].pin)
    free = _free_pins(window)[0]
    before = len(window.bus.document.nets)

    window.scene.arm_connect(True)
    window.scene.connect_click(_hole_of(window, *free))
    result = window.scene.connect_click(_hole_of(window, *on_net))

    assert result is not None and result.ok, result
    assert len(window.bus.document.nets) == before  # joined, not invented
    after = next(n for n in window.bus.document.nets if n.id == net.id)
    assert free in {(n.component_ref, n.pin) for n in after.nodes}
    _close(window)


def _pin_by_holding_net(window) -> dict[str, tuple[str, str]]:
    """One pin per net, keyed by the net that EFFECTIVELY holds it.

    First net wins, matching the connectivity engine and LVS -- dense.perf has a pin named
    by two nets, which is a document the net commands would now refuse and a file from
    before they existed is still allowed to contain.
    """
    holder: dict[tuple[str, str], str] = {}
    for net in window.bus.document.nets:
        for node in net.nodes:
            holder.setdefault((node.component_ref, node.pin), net.name)
    by_net: dict[str, tuple[str, str]] = {}
    for pin, name in holder.items():
        by_net.setdefault(name, pin)
    return by_net


def test_two_pins_on_different_nets_are_refused_with_both_named() -> None:
    """Merging two nets is a change to the circuit, not something two clicks may do."""
    window = _window_on(_load_dense())
    reasons: list[str] = []
    window.scene.netPinRejected.connect(reasons.append)
    (name_a, pin_a), (name_b, pin_b) = list(_pin_by_holding_net(window).items())[:2]
    before = window.bus.document

    window.scene.arm_connect(True)
    window.scene.connect_click(_hole_of(window, *pin_a))
    result = window.scene.connect_click(_hole_of(window, *pin_b))

    assert result is None
    assert window.bus.document is before
    assert name_a in reasons[-1] and name_b in reasons[-1]
    _close(window)


def test_two_pins_already_on_one_net_say_so_rather_than_dispatching() -> None:
    window = _window_on(_load_dense())
    reasons: list[str] = []
    window.scene.netPinRejected.connect(reasons.append)
    net = next(n for n in window.bus.document.nets if len(n.nodes) >= 2)
    before = window.bus.document

    window.scene.arm_connect(True)
    window.scene.connect_click(_hole_of(window, net.nodes[0].component_ref, net.nodes[0].pin))
    window.scene.connect_click(_hole_of(window, net.nodes[1].component_ref, net.nodes[1].pin))

    assert window.bus.document is before
    assert net.name in reasons[-1]
    _close(window)


def test_the_tool_stays_armed_so_connections_can_be_chained() -> None:
    """A board is a list of connections, not one, and re-arming between each of them is
    the friction this tool exists to remove."""
    window = _window_on(_load_dense())
    a, b, c = _free_pins(window)[:3]

    window.scene.arm_connect(True)
    window.scene.connect_click(_hole_of(window, *a))
    window.scene.connect_click(_hole_of(window, *b))
    assert window.scene.connect_armed
    assert window.scene.connect_from() is None  # ready for the next pair, not mid-pair

    window.scene.connect_click(_hole_of(window, *c))
    result = window.scene.connect_click(_hole_of(window, *a))

    assert result is not None and result.ok, result
    assert len(window.bus.document.nets[-1].nodes) == 3
    _close(window)


def test_a_refused_pair_does_not_leave_the_first_pin_armed() -> None:
    """Otherwise the next click joins something the user has stopped thinking about."""
    window = _window_on(_load_dense())

    pins = list(_pin_by_holding_net(window).values())[:2]

    window.scene.arm_connect(True)
    window.scene.connect_click(_hole_of(window, *pins[0]))
    window.scene.connect_click(_hole_of(window, *pins[1]))

    assert window.scene.connect_from() is None
    _close(window)


def test_clicking_an_empty_hole_while_connecting_says_so() -> None:
    window = _window_on(_load_dense())
    reasons: list[str] = []
    window.scene.netPinRejected.connect(reasons.append)

    window.scene.arm_connect(True)
    window.scene.connect_click(HoleCoord(0, 0))

    assert reasons and "No component pin" in reasons[0]
    assert window.scene.connect_from() is None
    _close(window)


def test_arming_another_board_tool_ends_a_connection_in_progress() -> None:
    window = _window_on(_load_dense())
    window.scene.arm_connect(True)
    window.scene.connect_click(_hole_of(window, *_free_pins(window)[0]))

    window.scene.arm_drawing("bare-wire")

    assert window.scene.connect_armed is False
    assert window.scene.connect_from() is None
    _close(window)


def test_the_automatic_net_name_counts_from_the_document() -> None:
    """Like next_reference, and for the same reason: a hidden counter would disagree with
    the document after an undo and the bus would refuse the name for an invisible reason."""
    from perfboard_studio.commands import AddNetPayload
    from perfboard_studio.ui.view2d import next_net_name

    window = _window_on(_load_dense())
    assert next_net_name(window.bus.document) == "N1"

    window.bus.dispatch("net.add", AddNetPayload(name="N1"))
    assert next_net_name(window.bus.document) == "N2"

    window.bus.undo()
    assert next_net_name(window.bus.document) == "N1"
    _close(window)


# ---------------------------------------------------------------------------
# The toolbar
# ---------------------------------------------------------------------------


def test_every_tool_on_the_bar_has_a_picture_and_a_short_label() -> None:
    """A toolbar of eleven identical grey rectangles is one people read left to right
    every time, which is how the tools ended up being hunted for in the menus instead."""
    window = _window_on(_load_dense())

    tools = [a for a in window.toolbar.actions() if not a.isSeparator()]

    assert len(tools) >= 15
    for action in tools:
        assert not action.icon().isNull(), f"{action.text()} has no icon"
        assert action.iconText(), f"{action.text()} has no button label"
        assert len(action.iconText()) <= 12, f"{action.iconText()} is too long for a button"
    _close(window)


def test_the_menus_keep_the_full_wording_the_buttons_abbreviate() -> None:
    """Qt draws iconText on a toolbar and text in a menu, so the short label must not
    have overwritten the exact one."""
    window = _window_on(_load_dense())

    assert window.act_autoroute.iconText() == "Autoroute"
    assert "All Nets" in window.act_autoroute.text()
    _close(window)


def test_an_unknown_icon_is_empty_rather_than_an_exception() -> None:
    """A missing picture is a cosmetic fault; taking the window down over one would not
    be."""
    from perfboard_studio.ui.icons import icon

    assert icon("no-such-icon").isNull()
    assert not icon("connect").isNull()


def test_every_icon_in_the_set_draws() -> None:
    """They are drawn with QPainter at import-independent sizes, so a broken path shows up
    as an empty pixmap rather than an error anywhere."""
    from perfboard_studio.ui.icons import DRAWINGS, icon

    for name in DRAWINGS:
        assert not icon(name).isNull(), name
        assert not icon(name).pixmap(22, 22).isNull(), name


# ---------------------------------------------------------------------------
# Pictures of the parts
# ---------------------------------------------------------------------------


def test_every_archetype_the_model_has_can_be_drawn() -> None:
    """A part with no picture in a list of pictures reads as a broken row, so the model
    gaining an archetype has to fail here rather than ship a blank."""
    import typing

    from perfboard_studio.model import BodyArchetype
    from perfboard_studio.ui.icons import PART_DRAWINGS

    declared = set(typing.get_args(BodyArchetype))
    # axial-cylinder is drawn by the polarity-aware path rather than the plain table,
    # because a resistor and a DO-41 diode share the archetype and look nothing alike.
    assert declared - set(PART_DRAWINGS) == {"axial-cylinder"}


def test_every_footprint_in_the_library_gets_a_picture() -> None:
    from perfboard_studio.footprints import standard_footprints
    from perfboard_studio.ui.icons import PART_SIZE, part_icon

    for footprint in standard_footprints().values():
        drawn = part_icon(footprint)
        assert not drawn.isNull(), footprint.id
        assert not drawn.pixmap(PART_SIZE, PART_SIZE).isNull(), footprint.id


def test_a_part_is_drawn_in_the_colour_the_board_draws_it() -> None:
    """The whole point of the pictures: picking an electrolytic from the list and finding
    it on the board is recognition rather than reading. A second palette here would drift
    from the first the moment either was touched."""
    from perfboard_studio.footprints import standard_footprints
    from perfboard_studio.ui.bodies import style_for
    from perfboard_studio.ui.icons import part_icon

    electrolytic = next(
        f for f in standard_footprints().values() if f.body.archetype == "radial-electrolytic"
    )
    image = part_icon(electrolytic).pixmap(40, 40).toImage()
    fill = QColor(style_for(electrolytic).fill)

    hits = sum(
        1
        for x in range(image.width())
        for y in range(image.height())
        if QColor(image.pixel(x, y)) == fill
    )
    assert hits > 40, "the body colour is not what is being drawn"


def test_the_same_part_is_only_drawn_once() -> None:
    """Sixty-one footprints across fifteen archetypes; the list is rebuilt on every
    keystroke in the filter box."""
    from perfboard_studio.footprints import standard_footprints
    from perfboard_studio.ui.icons import part_icon

    resistors = [
        f for f in standard_footprints().values() if f.body.archetype == "axial-cylinder"
    ][:2]

    assert part_icon(resistors[0]) is part_icon(resistors[0])
    if len(resistors) > 1 and resistors[0].polarized == resistors[1].polarized:
        assert part_icon(resistors[0]) is part_icon(resistors[1])


def test_the_parts_panel_shows_a_picture_on_every_row() -> None:
    window = _window_on(_load_dense())
    tree = window.library_tree

    groups = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    assert groups
    for group in groups:
        assert not group.icon(0).isNull(), group.text(0)
        for index in range(group.childCount()):
            assert not group.child(index).icon(0).isNull(), group.child(index).text(0)
    _close(window)


# ---------------------------------------------------------------------------
# Escape leaves the mode. From anywhere. Every mode.
#
# Reported: placing a part could not be cancelled with Escape. It was bound to the Draw
# menu's stop entry, which cancelled drawing, pin-picking and connecting -- and not
# placement. Being a WINDOW shortcut it also fires before the scene sees the key, so the
# scene's own Escape handling for placement was unreachable in the running application
# while the hint under the parts list said "Esc cancels" the whole time.
# ---------------------------------------------------------------------------


def _press_escape(window, focus_on) -> None:
    """A real Escape, through the shortcut machinery, from a real focus.

    Not window.on_stop_tool(): the bug was entirely about which of them the key reaches,
    so a test that called the handler directly would have passed against the broken build.
    """
    from PySide6.QtCore import Qt as QtCore_Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    window.show()
    focus_on.setFocus()
    QApplication.processEvents()
    QTest.keyClick(focus_on, QtCore_Qt.Key.Key_Escape)
    QApplication.processEvents()


def test_escape_cancels_placing_a_part_from_the_parts_list() -> None:
    """The reported bug, at the focus a user actually has: they picked the part from the
    list, so the list is what has the keyboard."""
    window = _window_on(_load_dense())
    window.scene.arm_placement("r-axial-5")
    assert window.scene.armed_footprint_id == "r-axial-5"

    _press_escape(window, window.library_tree)

    assert window.scene.armed_footprint_id is None
    _close(window)


def test_escape_cancels_drawing_from_a_filter_box() -> None:
    window = _window_on(_load_dense())
    window.scene.arm_drawing("bare-wire")

    _press_escape(window, window.library_filter)

    assert window.scene.armed_draw_kind is None
    _close(window)


def test_escape_cancels_connecting() -> None:
    window = _window_on(_load_dense())
    window.scene.arm_connect(True)

    _press_escape(window, window.view)

    assert window.scene.connect_armed is False
    _close(window)


def test_escape_cancels_a_pin_session_without_committing_it() -> None:
    from perfboard_studio.commands import AddNetPayload

    window = _window_on(_load_dense())
    window.bus.dispatch("net.add", AddNetPayload(name="HAND"))
    net = next(n for n in window.bus.document.nets if n.name == "HAND")
    window.scene.arm_net_pins(net.id)
    window.scene.net_pin_click(_hole_of(window, *_free_pins(window)[0]))
    before = window.bus.document

    _press_escape(window, window.view)

    assert window.scene.armed_net_id is None
    assert window.bus.document is before, "Escape must abandon the session, not commit it"
    _close(window)


def test_leaving_a_mode_is_one_method_rather_than_four_call_sites() -> None:
    """The window's shortcut and the scene's key handler both call this, so they cannot
    end up cancelling different sets of things -- which is how placement got left out."""
    window = _window_on(_load_dense())
    window.scene.arm_placement("r-axial-5")
    assert window.scene.in_a_mode

    window.scene.leave_mode()

    assert not window.scene.in_a_mode
    assert window.scene.armed_footprint_id is None
    assert window.scene.armed_draw_kind is None
    assert window.scene.armed_net_id is None
    assert window.scene.connect_armed is False
    _close(window)


def test_the_board_reports_being_in_a_mode_for_each_of_the_four() -> None:
    from perfboard_studio.commands import AddNetPayload

    window = _window_on(_load_dense())
    window.bus.dispatch("net.add", AddNetPayload(name="HAND"))
    net = next(n for n in window.bus.document.nets if n.name == "HAND")
    assert not window.scene.in_a_mode

    for arm in (
        lambda: window.scene.arm_placement("r-axial-5"),
        lambda: window.scene.arm_drawing("bare-wire"),
        lambda: window.scene.arm_net_pins(net.id),
        lambda: window.scene.arm_connect(True),
    ):
        arm()
        assert window.scene.in_a_mode
        window.scene.leave_mode()
        assert not window.scene.in_a_mode
    _close(window)


# ---------------------------------------------------------------------------
# Copper on the face you are not looking at
# ---------------------------------------------------------------------------


def test_a_conductor_knows_which_face_it_is_on_relative_to_the_view() -> None:
    """The board is opaque. Copper on the far face drawn solid says "this is in front of
    you", which is the same misreading the hatched body shadow exists to prevent -- and the
    one that gets a board soldered on the wrong side."""
    doc = _load_dense()
    top = BoardScene(doc, footprint_lookup(), side="top")
    bottom = BoardScene(doc, footprint_lookup(), side="bottom")

    def far(scene: BoardScene) -> set[str]:
        return {
            item.conductor_id
            for item in scene.items()
            if isinstance(item, ConductorItem) and item.is_far_side()
        }

    solder_side = {c.id for c in doc.conductors if c.side == "bottom"}
    assert solder_side, "the fixture has no solder-side copper, so this proves nothing"
    # Seen from the component side every solder-side run is on the far face, and turning
    # the board over swaps exactly that: nothing is on the far side of both views at once.
    assert far(top) == solder_side
    assert far(top) & far(bottom) == set()


def test_hatching_the_far_side_can_be_turned_off() -> None:
    """A fixed rule would be wrong: someone tracing a dense solder side may want to see it
    plainly. On by default because the default has to be the reading that cannot mislead."""
    doc = _load_dense()
    scene = BoardScene(doc, footprint_lookup(), side="top")
    assert scene.hatch_far_side is True

    scene.set_hatch_far_side(False)

    items = [item for item in scene.items() if isinstance(item, ConductorItem)]
    assert items
    assert all(item.hatch_far_side is False for item in items)


def test_a_hatched_conductor_still_marks_every_joint() -> None:
    """Where copper is soldered down does not change with the face you look from -- the hole
    goes through the board -- and it is what someone counts pads against. The beads must
    survive the far-side treatment, or the heart of the model goes with them."""
    doc = _load_dense()
    scene = BoardScene(doc, footprint_lookup(), side="top")

    traces = [
        item
        for item in scene.items()
        if isinstance(item, ConductorItem)
        and item.is_far_side()
        and contacts_every_path_hole(item.conductor)
    ]
    assert traces, "no far-side solder trace in the fixture"
    for item in traces:
        assert len(item.contact_points()) == len(item.conductor.path)


# ---------------------------------------------------------------------------
# The schematic panel
# ---------------------------------------------------------------------------
#
# The engine side is tested in test_schematic.py, which is where the layout properties
# live. What is left for here is the half that only exists in the window: that the panel
# fills itself only while open, that the sheet is actually painted, and that clicking on it
# moves the same selection the board and the Nets dock already share. Cross-probing is the
# reason the panel is in the window rather than an exported file, so it is the part worth
# holding still.


def _move_symbol(window, ref: str, x: float, y: float) -> None:
    """Drag one symbol to a place on the sheet, the way the view reports one.

    Through the window's own handler rather than by building a SymbolPlacement, because the
    interesting half is what it does to the OTHER symbols: the first move freezes every one
    of them where the drawing already had it.
    """
    window._refresh_schematic_panel()
    window._on_symbols_moved([(ref, x, y)])
    window._refresh_schematic_panel()


def _open_schematic(doc):
    window = _window_on(doc)
    window.show_schematic()
    return window


def test_a_symbol_dragged_onto_the_board_places_that_one_part() -> None:
    """The other half of "Place on the Board": that button moves the WHOLE design, and
    until now there was no way to put down one part from the sheet at all -- double-clicking
    a symbol opened its properties."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    _keep_the_board(window)
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")

    window._on_part_dropped("R1", HoleCoord(5, 5))

    placed = {c.ref: c.anchor for c in window.bus.document.components}
    assert placed == {"R1": HoleCoord(5, 5)}
    assert [p.ref for p in window.bus.document.parts] == ["R2"]
    _close(window)


def test_dragging_a_symbol_whose_part_is_already_down_moves_it() -> None:
    """Two commands behind one gesture, and which one it is depends on which list the part
    is in -- the same split Remove already makes. Dragging a symbol whose part is already
    on the board can only mean "put it here instead"."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    _keep_the_board(window)
    _add(window, "R1", "r-axial-3")
    window._on_part_dropped("R1", HoleCoord(4, 4))

    window._on_part_dropped("R1", HoleCoord(9, 7))

    assert window.bus.document.parts == ()
    assert [c.anchor for c in window.bus.document.components] == [HoleCoord(9, 7)]
    _close(window)


def test_a_drop_the_board_refuses_says_so_rather_than_half_placing() -> None:
    """The command checks the hole, not the view: a second opinion in the view is a second
    thing to keep in step with what the bus actually allows."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    _keep_the_board(window)
    _add(window, "U1", "dip-28")

    window._on_part_dropped("U1", HoleCoord(-4, -4))

    assert window.bus.document.components == ()
    assert [p.ref for p in window.bus.document.parts] == ["U1"]
    assert window.statusBar().currentMessage()
    _close(window)


def test_a_row_dragged_out_of_the_parts_panel_carries_a_footprint() -> None:
    """Its own format, not plain text: a board must not accept an arbitrary string dropped
    on it, and a FOOTPRINT is a different drop from a PART -- one is component.place and a
    new reference, the other is a part that already exists moving to a hole."""
    from PySide6.QtCore import QMimeData

    from perfboard_studio.ui.view2d import FOOTPRINT_MIME, PART_MIME

    window = _blank_window()
    data = QMimeData()
    data.setData(FOOTPRINT_MIME, b"r-axial-3")
    data.setText("r-axial-3")

    assert window.view._dropped_footprint_from(data) == "r-axial-3"
    # ...and it is not mistaken for a symbol dragged off the sheet.
    assert window.view._dropped_ref_from(data) is None
    assert not data.hasFormat(PART_MIME)
    _close(window)


def test_a_footprint_dropped_on_the_board_places_that_part() -> None:
    """Dragging is what everybody tries first and it did nothing at all: the only way to
    put a part down was to pick it in the list and then click the board."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    window.library_value.setText("10k")

    window._on_footprint_dropped("r-axial-3", HoleCoord(6, 4))

    placed = window.bus.document.components
    assert [(c.footprint_id, c.anchor, c.value) for c in placed] == [
        ("r-axial-3", HoleCoord(6, 4), "10k")
    ]
    # ...and the part stays armed, so a run of them can be clicked down afterwards.
    assert window.scene.armed_footprint_id == "r-axial-3"
    _close(window)


def test_a_dropped_footprint_the_library_does_not_list_is_still_placed() -> None:
    """A generated id carries its own dimensions and is not in the tree, so arming it by
    selecting a row cannot work. It is armed directly instead."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()

    window._on_footprint_dropped("box-4x2-p1-r3-15x10x8", HoleCoord(3, 3))

    assert [c.footprint_id for c in window.bus.document.components] == [
        "box-4x2-p1-r3-15x10x8"
    ]
    _close(window)


def test_pressing_a_symbol_and_moving_drags_it_about_the_sheet() -> None:
    """The gesture the sheet documented and never had: _maybe_start_drag existed, and
    nothing in the view ever recorded a press or called it -- so a symbol could not be
    dragged to another place, and could not be dragged onto the board either."""
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent

    window = _open_schematic(_golden_document("ne555"))
    view = window.schematic_view
    symbol = next(s for s in view.item.drawing.symbols if s.ref == "R1")
    centre = view.mapFromScene(
        QPointF(symbol.at.x + symbol.width / 2, symbol.at.y + symbol.height / 2)
    )
    moved: list = []
    view.symbolsMoved.connect(moved.append)

    def mouse(kind, pos):
        return QMouseEvent(
            kind,
            QPointF(pos),
            QPointF(pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    view.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, centre))

    assert view._press_ref == "R1"
    assert view.selected_refs == ["R1"]

    view.mouseMoveEvent(mouse(QEvent.Type.MouseMove, centre + QPoint(60, 40)))

    # Nothing is committed while the button is down: the ghost is a PICTURE of the edit.
    assert view.item.drag_offset is not None
    assert window.bus.document.sheet == ()

    view.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, centre + QPoint(60, 40)))

    assert moved and moved[0][0][0] == "R1"
    _close(window)


def test_letting_go_outside_the_sheet_hands_the_part_to_the_board() -> None:
    """ONE GESTURE, TWO DESTINATIONS, decided by where the pointer goes. Anything else
    would mean two ways to pick a symbol up."""
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent

    window = _open_schematic(_golden_document("ne555"))
    view = window.schematic_view
    view.resize(400, 300)
    symbol = next(s for s in view.item.drawing.symbols if s.ref == "R1")
    centre = view.mapFromScene(
        QPointF(symbol.at.x + symbol.width / 2, symbol.at.y + symbol.height / 2)
    )
    moved: list = []
    view.symbolsMoved.connect(moved.append)

    def mouse(kind, pos):
        return QMouseEvent(
            kind,
            QPointF(pos),
            QPointF(pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    view.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, centre))
    # Past the edge of the panel: the in-sheet move becomes a Qt drag, which is what lands
    # it on a hole when it is dropped on the board.
    view.mouseMoveEvent(mouse(QEvent.Type.MouseMove, QPoint(-40, 20)))

    assert view._press_ref is None
    assert view.item.drag_offset is None
    assert not moved
    _close(window)


def test_a_press_that_does_not_move_far_enough_is_not_a_drag() -> None:
    """A click on a symbol to select it always carries a pixel or two of drift with it."""
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent

    window = _open_schematic(_golden_document("ne555"))
    view = window.schematic_view
    symbol = next(s for s in view.item.drawing.symbols if s.ref == "R1")
    centre = view.mapFromScene(
        QPointF(symbol.at.x + symbol.width / 2, symbol.at.y + symbol.height / 2)
    )

    def mouse(kind, pos):
        return QMouseEvent(
            kind,
            QPointF(pos),
            QPointF(pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    view.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, centre))
    view.mouseMoveEvent(mouse(QEvent.Type.MouseMove, centre + QPoint(1, 1)))

    assert view._press_ref == "R1"
    _close(window)


def test_a_dragged_part_carries_its_reference_in_a_format_of_its_own() -> None:
    """Its own MIME type rather than plain text: a board must not accept an arbitrary
    string dropped on it, and Qt only offers a target the formats the source declared."""
    from PySide6.QtCore import QMimeData

    from perfboard_studio.ui.view2d import PART_MIME

    window = _open_schematic(_golden_document("ne555"))
    data = QMimeData()
    data.setText("nonsense")

    assert not data.hasFormat(PART_MIME)
    assert window.view._dropped_ref_from(data) is None

    data.setData(PART_MIME, b"R1")
    data.setText("R1")
    assert window.view._dropped_ref_from(data) == "R1"
    _close(window)


def test_the_board_and_the_sheet_are_both_panels() -> None:
    """They were a central widget and a tab beside it -- the one pair in the window that
    could not be arranged. Side by side, stacked, floated or closed is now a drag, and Qt
    remembers wherever it was left."""
    window = _window_on(_golden_document("ne555"))

    assert window.dock_board.widget() is window.view
    assert window.dock_schematic.widget() is window.schematic_page
    # Stacked on one another to start with, so the pair opens looking like the tabs it
    # replaces...
    assert window.dock_schematic in window.tabifiedDockWidgets(window.dock_board)
    # ...and the board is the one in front.
    assert window.schematic_is_showing() is False
    _close(window)


def test_a_tabbed_panel_drops_its_own_title_bar() -> None:
    """Qt draws both: the tab bar for the group, and under it the current dock's title --
    the same word twice, on two rows, above a view that wanted the height."""
    window = _window_on(_golden_document("ne555"))

    assert window.dock_board.titleBarWidget() is not None

    window.dock_schematic.setFloating(True)
    window._on_view_dock_moved()

    # ...and back the moment it is the only handle the panel has.
    assert window.dock_schematic.titleBarWidget() is None
    _close(window)


def test_the_sheet_floats_into_a_window_and_comes_back() -> None:
    """Somebody who wants both at once gets two real windows to put side by side. It is
    the dock's own state and nothing else: the panel used to be reparented into a widget
    built for the purpose and handed back on close, none of which could be undone by
    dragging."""
    window = _open_schematic(_golden_document("ne555"))
    view = window.schematic_view

    window.on_schematic_float()

    assert window.dock_schematic.isFloating()
    assert window.schematic_view is view  # ...and the same view, moved
    assert window.schematic_is_showing()

    window.on_schematic_float()

    assert not window.dock_schematic.isFloating()
    assert window.schematic_is_showing()
    _close(window)


def test_closing_every_view_says_which_button_brings_one_back() -> None:
    """A dock can be closed and two of the closable ones are now the board and the sheet,
    so a blank grey window is reachable in one click -- the single screen in this
    application where nothing at all says what to do."""
    window = _window_on(_golden_document("ne555"))
    hint = window.centralWidget()

    assert hint is not None and hint.maximumSize().width() == 0

    for dock in (window.dock_board, window.dock_schematic, window.dock_3d, window.dock_guide):
        dock.hide()

    assert hint.maximumSize().width() > 0
    assert "Ctrl+1" in window.central_hint.text()

    window.show_board()

    assert hint.maximumSize().width() == 0
    _close(window)


def test_the_sheet_is_drawn_on_a_grid() -> None:
    """A schematic without one is a drawing floating in the dark: nothing says how big the
    sheet is, nothing says whether two symbols line up, and a pan has no landmarks."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from perfboard_studio.schematic import GRID_MM

    window = _open_schematic(_golden_document("ne555"))
    view = window.schematic_view

    # Painted at a zoom where a square is comfortably wider than the cutoff.
    view.resetTransform()
    view.scale(4.0, 4.0)
    image = QImage(200, 200, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    view.drawBackground(painter, QRectF(0.0, 0.0, 10 * GRID_MM, 10 * GRID_MM))
    painter.end()

    colours = {image.pixel(x, y) for x in range(0, 200, 3) for y in range(0, 200, 3)}
    assert len(colours) > 1, "the background came out one flat colour"
    _close(window)


def test_the_grid_gives_up_before_it_becomes_a_grey_wash() -> None:
    """A grid finer than the eye can separate is not a grid. At a fit-to-window zoom on a
    big sheet, 2.54 mm is exactly that."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    window = _open_schematic(_golden_document("ne555"))
    view = window.schematic_view

    view.resetTransform()
    view.scale(0.05, 0.05)  # far past MIN_GRID_PX for both the minor and the major line
    image = QImage(120, 120, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    view.drawBackground(painter, QRectF(0.0, 0.0, 2000.0, 2000.0))
    painter.end()

    colours = {image.pixel(x, y) for x in range(0, 120, 2) for y in range(0, 120, 2)}
    assert len(colours) == 1, "the grid was still drawn where it cannot be read"
    _close(window)


def test_a_schematic_tab_nobody_has_selected_costs_nothing() -> None:
    """Same rule as the guide and 3D docks: a view nobody is looking at builds nothing.
    build_schematic lays out a whole sheet, and paying for that on every keystroke to fill
    a tab behind the board is the mistake both of those already avoid."""
    window = _window_on(_golden_document("ne555"))
    assert window.schematic_is_showing() is False
    assert window._schematic_stale is True

    window.on_bus_changed(window.bus.document, None)

    assert window.schematic_view.item is None
    _close(window)


def test_opening_the_panel_draws_every_part_the_netlist_or_the_board_has() -> None:
    doc = _golden_document("ne555")
    window = _open_schematic(doc)

    assert window.schematic_view.item is not None
    drawn = {symbol.ref for symbol in window.schematic_view.item.drawing.symbols}
    expected = {component.ref for component in doc.components}
    expected |= {node.component_ref for net in doc.nets for node in net.nodes}
    assert drawn == expected
    _close(window)


def test_the_sheet_actually_puts_ink_on_the_panel() -> None:
    """Renders the item and counts what is not the sheet colour.

    Shapes only -- no text is asserted on, because Qt's offscreen plugin ships no font
    database on Windows (see the skipif guards above) and a symbol body is drawn with
    polygons either way. A sheet that painted nothing would still have passed every
    structural test in test_schematic.py.
    """
    from perfboard_studio.ui.viewsch import SHEET

    window = _open_schematic(_golden_document("ne555"))
    item = window.schematic_view.item
    drawing = item.drawing

    image = QImage(600, 600, QImage.Format.Format_ARGB32)
    image.fill(QColor(SHEET))
    painter = QPainter(image)
    painter.scale(600 / drawing.width, 600 / drawing.height)
    item.paint(painter, None, None)
    painter.end()

    assert _pixels_matching(image, QColor(SHEET)) < 600 * 600, "nothing was drawn"
    _close(window)


def test_clicking_a_symbol_selects_that_part_on_the_board() -> None:
    """The whole reason the sheet is in the window and not an exported file."""
    doc = _golden_document("ne555")
    window = _open_schematic(doc)
    part = doc.components[0]

    window._on_schematic_part_clicked(part.ref)

    assert window.scene.selected_component_ids() == (part.id,)
    _close(window)


def test_clicking_a_part_the_board_has_not_got_says_so_instead_of_selecting_nothing() -> None:
    doc = _golden_document("ne555")
    window = _open_schematic(doc)

    window._on_schematic_part_clicked("U404")

    assert window.scene.selected_component_ids() == ()
    assert "U404" in window.statusBar().currentMessage()
    _close(window)


def test_clicking_a_wire_selects_its_net_in_the_nets_dock() -> None:
    """Routed through the dock deliberately: that selection already drives the board and
    the sheet, so one path means the three cannot disagree about what is selected."""
    doc = _golden_document("ne555")
    window = _open_schematic(doc)
    wire = window.schematic_view.item.drawing.wires[0]

    window._on_schematic_net_clicked(wire.net_id)

    assert window._selected_net_ids() == (wire.net_id,)
    assert wire.net_id in window.schematic_view.item.highlight_nets
    _close(window)


def test_selecting_a_part_on_the_board_lights_up_its_symbol() -> None:
    doc = _golden_document("ne555")
    window = _open_schematic(doc)
    part = doc.components[0]

    window.scene.select_components([part.id])
    window._refresh_selection_state()

    assert part.ref in window.schematic_view.item.highlight_refs
    _close(window)


def test_a_redraw_does_not_move_the_view() -> None:
    """The rule view3d.populate_renderer follows about the camera, for the same reason:
    editing one net must not throw away the part of the sheet somebody was looking at."""
    window = _open_schematic(_golden_document("ne555"))
    window.schematic_view.scale(2.0, 2.0)
    before = window.schematic_view.transform()

    window._refresh_schematic_panel()

    assert window.schematic_view.transform() == before
    _close(window)


def test_a_redraw_keeps_the_highlight() -> None:
    """The panel holds no state of its own, so the highlight has to survive being handed a
    new drawing -- otherwise every edit silently clears the selection on one view only."""
    doc = _golden_document("ne555")
    window = _open_schematic(doc)
    part = doc.components[0]
    window.scene.select_components([part.id])
    window._refresh_selection_state()

    window._refresh_schematic_panel()

    assert part.ref in window.schematic_view.item.highlight_refs
    _close(window)


def test_the_cursor_describes_what_it_is_over() -> None:
    doc = _golden_document("ne555")
    window = _open_schematic(doc)
    view = window.schematic_view
    symbol = view.item.drawing.symbols[0]

    over_symbol = QPointF(symbol.at.x + symbol.width / 2, symbol.at.y + symbol.height / 2)
    described = view.describe(over_symbol)
    assert symbol.ref in described
    assert view.describe(QPointF(-500.0, -500.0)) == ""

    wire = view.item.drawing.wires[0]
    midpoint = QPointF(
        (wire.path[0].x + wire.path[1].x) / 2, (wire.path[0].y + wire.path[1].y) / 2
    )
    assert view.describe(midpoint) == wire.net_name
    _close(window)


def test_the_panel_names_the_rails_it_drew_instead_of_leaving_them_unexplained() -> None:
    """Somebody who does not know the convention will look for the ground wires and not
    find any, so the summary says where they went."""
    window = _open_schematic(_golden_document("ne555"))

    assert "rail symbol" in window.schematic_summary.text()
    _close(window)


# ---------------------------------------------------------------------------
# Drawing the circuit first, and going from there to the board
# ---------------------------------------------------------------------------
#
# The order every other EDA tool works in, and the one this application could not do:
# every route a part had into a document ended in `component.place`, which needs a hole.
# The engine side is in test_commands.py; what is left for here is the flow -- add, wire,
# place -- driven through the same handlers the buttons are wired to.


def _blank_window():
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.model import DocumentMeta

    document = PerfDocument(
        meta=DocumentMeta(name="blank", created="", modified=""), board=DEFAULT_BOARD
    )
    window = _window_on(document)
    window.show_schematic()
    return window


def _add(window, ref, footprint_id, value=""):
    from perfboard_studio.commands import AddPartPayload

    result = window.bus.dispatch(
        "part.add", AddPartPayload(ref=ref, footprint_id=footprint_id, value=value)
    )
    assert result.ok, result.message
    window._refresh_schematic_panel()


def test_a_circuit_can_be_drawn_before_the_board_has_anything_on_it() -> None:
    window = _blank_window()
    _add(window, "U1", "dip-8", "NE555")
    _add(window, "R1", "r-axial-3", "10k")

    drawn = {symbol.ref: symbol for symbol in window.schematic_view.item.drawing.symbols}

    assert set(drawn) == {"U1", "R1"}
    assert window.bus.document.components == ()
    # Drawn as themselves, from their own footprints -- not as boxes with whatever pins a
    # netlist happened to mention, because there is no netlist yet.
    assert drawn["U1"].kind == "ic" and len(drawn["U1"].pins) == 8
    assert drawn["R1"].kind == "resistor"
    assert all(symbol.unplaced and not symbol.undefined for symbol in drawn.values())
    _close(window)


def test_the_panel_counts_what_is_not_on_the_board_yet() -> None:
    """A progress line, not a warning: while a circuit is being drawn every part is
    unplaced, and it is the question the Place button answers."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")

    assert "not on the board yet" in window.schematic_summary.text()
    _close(window)


def test_clicking_two_pins_wires_them_and_leaves_a_line_saying_so() -> None:
    """Through the VIEW's own handler, which is where the gesture lives: a wire tool that
    joined two pins and drew nothing would be a connect tool with a pencil icon."""
    window = _blank_window()
    _add(window, "U1", "dip-8")
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    view = window.schematic_view

    window.on_sheet_tool("wire")
    view._wire_click(("R1", "2"))
    assert view.pending_pin == ("R1", "2")
    view._wire_click(("U1", "6"))

    assert len(window.bus.document.nets) == 1
    assert len(window.bus.document.sheet_wires) == 1
    assert view.pending_pin is None

    # A third pin joins the net that already exists rather than starting another.
    window._refresh_schematic_panel()
    view._wire_click(("R2", "1"))
    view._wire_click(("U1", "6"))

    assert len(window.bus.document.nets) == 1
    assert len(window.bus.document.nets[0].nodes) == 3
    assert len(window.bus.document.sheet_wires) == 2
    _close(window)


def test_a_drawn_wire_turns_once_and_always_the_same_way() -> None:
    """A wire tool that picked its corner by whichever leg was longer would flip the route
    while the pointer moved, which makes it impossible to aim."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    view = window.schematic_view
    window.on_sheet_tool("wire")

    view._wire_click(("R1", "2"))
    view._wire_click(("R2", "1"))

    wire = window.bus.document.sheet_wires[0]
    assert 2 <= len(wire.path) <= 3
    # Every segment is orthogonal, which is what "a schematic" means.
    for start, end in zip(wire.path, wire.path[1:], strict=False):
        assert start.x == end.x or start.y == end.y
    _close(window)


def test_clicking_the_same_pin_twice_cancels_instead_of_wiring_it_to_itself() -> None:
    window = _blank_window()
    _add(window, "R1", "r-axial-3")

    window.on_sheet_tool("wire")
    window.schematic_view._wire_click(("R1", "2"))
    window.schematic_view._wire_click(("R1", "2"))

    assert window.bus.document.nets == ()
    assert window.schematic_view.pending_pin is None
    _close(window)


def test_wiring_two_pins_that_are_already_on_different_nets_is_refused() -> None:
    """Merging two nets is a change to the circuit, not to two clicks -- and the refusal
    reads the same here as on the board, because both come from ``plan_pin_join``."""
    from perfboard_studio.commands import AddNetPayload
    from perfboard_studio.model import NetNode

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    window.bus.dispatch("net.add", AddNetPayload(name="A", nodes=(NetNode("R1", "1"),)))
    window.bus.dispatch("net.add", AddNetPayload(name="B", nodes=(NetNode("R2", "1"),)))
    window._refresh_schematic_panel()

    window.on_sheet_tool("wire")
    window.schematic_view._wire_click(("R1", "1"))
    window.schematic_view._wire_click(("R2", "1"))

    assert len(window.bus.document.nets) == 2
    assert window.bus.document.sheet_wires == ()
    assert "disconnect one of the pins first" in window.statusBar().currentMessage()
    _close(window)


def test_a_missed_click_while_wiring_cancels_the_half_made_pair() -> None:
    """Otherwise a stale first pin joins itself to whatever is clicked three gestures
    later, which is a connection nobody asked for and nobody saw made."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    window.on_schematic_wire_mode(True)
    window._on_schematic_pin_clicked("R1", "2")

    far_away = QPointF(window.schematic_view.mapFromScene(QPointF(-400.0, -400.0)))
    window.schematic_view.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            far_away,
            far_away,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )

    assert window.schematic_view.pending_pin is None
    _close(window)


def _keep_the_board(window) -> None:
    """Answer the board-size question with "keep the one I have".

    Stubbed on the METHOD, not on the dialog, for the reason ``_confirm`` is: a test that
    reaches past the window into QDialog is a test that breaks when the question is asked
    a different way, and this is the question, whatever it looks like.
    """
    type(window)._offer_a_board_size = lambda self, document: True


def test_place_on_the_board_arranges_the_whole_design_in_one_undo_step() -> None:
    window = _blank_window()
    _keep_the_board(window)
    _add(window, "U1", "dip-8")
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")

    window.on_schematic_place_all()

    assert window.bus.document.parts == ()
    assert {c.ref for c in window.bus.document.components} == {"U1", "R1", "R2"}
    # Arranged, not dropped in a grid: the button does the whole job now, and says what
    # the next step is rather than what the missing one was.
    assert "Ctrl+R" in window.statusBar().currentMessage()

    window.bus.undo()
    assert len(window.bus.document.parts) == 3
    assert window.bus.document.components == ()
    _close(window)


def test_placing_a_design_leaves_the_parts_already_on_the_board_alone() -> None:
    """Putting a design on the board is not the moment to rearrange what somebody has
    already positioned. That is auto-place, and it is a gesture they ask for by name."""
    window = _blank_window()
    _keep_the_board(window)
    _add(window, "U1", "dip-8")
    window.on_schematic_place_all()
    settled = {c.ref: (c.anchor, c.rotation) for c in window.bus.document.components}

    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    window.on_schematic_place_all()

    after = {c.ref: (c.anchor, c.rotation) for c in window.bus.document.components}
    assert after["U1"] == settled["U1"]
    assert {"R1", "R2"} <= set(after)
    _close(window)


def test_a_connector_in_the_design_is_placed_on_the_edge_of_the_board() -> None:
    """The whole reason the button arranges rather than laying a grid: a header dropped
    in the middle of a board is a header nothing can be plugged into."""
    window = _blank_window()
    _keep_the_board(window)
    _add(window, "J1", "hdr-1x4")
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")

    window.on_schematic_place_all()

    board = window.bus.document.board
    header = next(c for c in window.bus.document.components if c.ref == "J1")
    assert (
        min(
            header.anchor.col,
            board.cols - 1 - header.anchor.col,
            header.anchor.row,
            board.rows - 1 - header.anchor.row,
        )
        <= 1
    )
    _close(window)


def test_the_board_size_dialog_offers_the_stock_sizes_and_the_board_you_have() -> None:
    """Built and read without exec(): the question is which board, and the answer is a
    row in a list, so neither needs an event loop to be tested."""
    from perfboard_studio.geometry import STANDARD_PRESETS
    from perfboard_studio.model import SchematicPart
    from perfboard_studio.placer import design_entries, recommended_board, suggest_boards
    from perfboard_studio.ui.main import BoardSizeDialog

    window = _blank_window()
    document = window.bus.document
    parts = tuple(
        SchematicPart(id=f"p{i}", ref=f"U{i}", value="", footprint_id="dip-8")
        for i in range(4)
    )
    document = dataclasses.replace(document, parts=parts)
    suggestions = suggest_boards(
        document.board, design_entries(document), document.nets, window.lookup
    )
    best = recommended_board(suggestions)
    dialog = BoardSizeDialog(suggestions, document.board, best, window)

    # Row 0 is always "keep the board I have", and it answers with None.
    dialog.choices.setCurrentRow(0)
    assert dialog.chosen() is None
    # ...and the recommendation is preselected, on a board a supplier stocks.
    assert best is not None
    assert best.preset in {entry for entry in STANDARD_PRESETS}
    _close(window)


def test_placing_with_nothing_left_in_the_design_says_so_rather_than_doing_nothing() -> None:
    window = _blank_window()
    _keep_the_board(window)

    window.on_schematic_place_all()

    assert "already on the board" in window.statusBar().currentMessage()
    _close(window)


def test_remove_deletes_a_part_in_the_design_and_unplaces_one_on_the_board() -> None:
    """Two actions behind one button, and the difference is which list the part is in.
    Somebody clicking Remove on a placed part means "wrong hole", not "delete the
    circuit around it"."""
    window = _blank_window()
    _keep_the_board(window)
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    window.on_schematic_place_all()
    window._refresh_schematic_panel()

    window._on_schematic_part_clicked("R1")
    window.on_schematic_remove()

    assert [p.ref for p in window.bus.document.parts] == ["R1"]
    assert {c.ref for c in window.bus.document.components} == {"R2"}

    # Now it is in the design, so the same button deletes it.
    window._on_schematic_part_clicked("R1")
    window.on_schematic_remove()

    assert window.bus.document.parts == ()
    _close(window)


def test_a_part_only_in_the_design_can_still_be_selected_on_the_sheet() -> None:
    """It has no board item to click, and it is the part somebody drawing a circuit is
    working with -- so the panel keeps a reference of its own."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")

    window._on_schematic_part_clicked("R1")

    assert window._schematic_ref == "R1"
    assert "R1" in window.schematic_view.item.highlight_refs
    assert window.act_sch_delete.isEnabled()
    _close(window)


def test_escape_leaves_the_wiring_tool_the_way_it_leaves_every_other_mode() -> None:
    """The status bar says "Esc cancels" while wiring, so Escape has to actually do it.

    Escape is a WINDOW shortcut and fires wherever the focus is, so it goes through
    on_stop_tool rather than through the panel -- the same route the board's modes take.
    """
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    window.on_sheet_tool("wire")
    window._on_schematic_pin_clicked("R1", "2")

    window.on_stop_tool()

    assert not window.act_sheet_tool["wire"].isChecked()
    assert window.schematic_view.wiring is False
    assert window.schematic_view.pending_pin is None
    _close(window)


def test_the_suggested_reference_counts_the_design_as_well_as_the_board() -> None:
    """Otherwise the dialog offers R1 to somebody who has just drawn R1, and the bus
    refuses it for a reason nothing on screen explains."""
    from perfboard_studio.ui.view2d import next_reference

    window = _blank_window()
    _add(window, "R1", "r-axial-3")

    assert next_reference(window.bus.document, "r-axial-3") == "R2"
    _close(window)


# ---------------------------------------------------------------------------
# Editing the circuit by right-clicking the thing that is wrong
# ---------------------------------------------------------------------------
#
# Every command here already existed. What is new is the door: a net was renamed by
# finding it in a tree of twenty names, and a pin was taken off one by expanding that
# net and selecting the pin inside it. The sheet is where you can SEE that VOUT is
# wired to the wrong leg, so it is where the menu belongs.
#
# The tests below are about the wiring between a click and a command -- which entry
# appears over what, and which document it acts on. What each command DOES is tested
# where the command is.


def _sheet_at(window, x: float, y: float):
    """A viewport position over a point on the sheet, in scene millimetres.

    The transform is reset first so one scene millimetre is one pixel: a fitted view of a
    400 mm sheet in an unshown offscreen widget can be a few millimetres to the pixel,
    which is wider than the 1.2 mm a pin is picked within.
    """
    from PySide6.QtCore import QPointF

    window.schematic_view.resetTransform()
    return window.schematic_view.mapFromScene(QPointF(x, y))


def _over(window, ref: str):
    """A viewport position over the middle of a symbol."""
    symbol = next(s for s in window.schematic_view.item.drawing.symbols if s.ref == ref)
    return _sheet_at(
        window, symbol.at.x + symbol.width / 2, symbol.at.y + symbol.height / 2
    )


def _labels(menu) -> list[str]:
    return [action.text() for action in menu.actions() if action.text()]


def _entry(menu, fragment: str):
    found = [a for a in menu.actions() if fragment in a.text()]
    assert len(found) == 1, f"{fragment!r} in {[a.text() for a in menu.actions()]}"
    return found[0]


def _wire(window, name: str, *nodes, net_class="signal") -> str:
    from perfboard_studio.commands import AddNetPayload
    from perfboard_studio.model import NetNode

    result = window.bus.dispatch(
        "net.add",
        AddNetPayload(
            name=name,
            net_class=net_class,
            nodes=tuple(NetNode(component_ref=r, pin=p) for r, p in nodes),
        ),
    )
    assert result.ok, result.message
    window._refresh_schematic_panel()
    return next(n.id for n in window.bus.document.nets if n.name == name)


def test_a_right_click_on_a_symbol_offers_the_part() -> None:
    window = _blank_window()
    _add(window, "R1", "r-axial-3", "10k")

    labels = _labels(window.sheet_menu(_over(window, "R1")))

    assert labels == [
        "&Properties…",
        "Re&name…",
        "D&uplicate",
        "&Remove from the Design",
    ]
    _close(window)


def test_a_placed_part_is_taken_off_the_board_and_a_drawn_one_is_deleted() -> None:
    """The one entry that differs between the two lists, and the difference is the whole
    reason ``on_schematic_remove`` is two actions behind one button: "I put this in the
    wrong hole" must not delete the circuit around it."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    _keep_the_board(window)
    _add(window, "R1", "r-axial-3")
    window._on_part_dropped("R1", HoleCoord(5, 5))
    window._refresh_schematic_panel()

    assert "Take &off the Board" in _labels(window.sheet_menu(_over(window, "R1")))
    _close(window)


def test_a_right_click_on_bare_sheet_offers_the_sheet() -> None:
    window = _blank_window()
    _add(window, "R1", "r-axial-3")

    labels = _labels(window.sheet_menu(_sheet_at(window, -120.0, -120.0)))

    assert labels == ["&Add Part…", "Arran&ge the Sheet", "&Fit the Sheet"]
    _close(window)


def test_the_menu_acts_on_the_symbol_it_was_opened_over_not_on_the_selection() -> None:
    """``board_menu``'s rule, and it matters more here: Remove reads the panel's own
    reference, so a menu that left it pointing at the last thing clicked would delete
    something else entirely."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    window._on_schematic_part_clicked("R1")

    _entry(window.sheet_menu(_over(window, "R2")), "Remove").trigger()

    assert [part.ref for part in window.bus.document.parts] == ["R1"]
    _close(window)


def test_a_reference_only_a_net_names_offers_nothing_to_do() -> None:
    """A symbol can be drawn for a part nothing defines -- that is what the dashed outline
    is. Offering five entries that would each refuse says less than one that explains."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _wire(window, "OUT", ("R1", "1"), ("U9", "3"))

    labels = _labels(window.sheet_menu(_over(window, "U9")))

    assert labels == ["U9 is named by a net and is not in the design."]
    _close(window)


def test_renaming_a_symbol_from_the_sheet_carries_its_nets(monkeypatch) -> None:
    """The only reason a rename is safe to offer in two clicks. R1 wired into six nets and
    relabelled R7 used to come out connected to nothing."""
    from PySide6.QtWidgets import QInputDialog

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _wire(window, "OUT", ("R1", "1"))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("R7", True))

    _entry(window.sheet_menu(_over(window, "R1")), "name…").trigger()

    assert [part.ref for part in window.bus.document.parts] == ["R7"]
    assert [node.component_ref for node in window.bus.document.nets[0].nodes] == ["R7"]
    _close(window)


def test_a_rename_nobody_finished_changes_nothing(monkeypatch) -> None:
    from PySide6.QtWidgets import QInputDialog

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    before = window.bus.document
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("R7", False))

    window._rename_symbol("R1")

    assert window.bus.document is before
    _close(window)


def test_duplicating_a_part_copies_what_it_is_and_not_what_it_is_wired_to() -> None:
    """``ui/clipboard``'s call about a pasted block's net claim, one part at a time: a copy
    of R1 is not R1, and putting it on R1's nets would tell LVS the design has a part it
    has never heard of wired in parallel with one it has."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3", "10k")
    _wire(window, "OUT", ("R1", "1"))

    _entry(window.sheet_menu(_over(window, "R1")), "uplicate").trigger()

    made = {part.ref: part for part in window.bus.document.parts}
    assert set(made) == {"R1", "R2"}
    assert made["R2"].footprint_id == "r-axial-3" and made["R2"].value == "10k"
    assert [node.component_ref for node in window.bus.document.nets[0].nodes] == ["R1"]
    _close(window)


def test_a_duplicate_of_a_placed_part_lands_in_the_design() -> None:
    """The copy has no position and nothing here is entitled to guess one."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    _keep_the_board(window)
    _add(window, "U1", "dip-8")
    window._on_part_dropped("U1", HoleCoord(4, 4))
    window._refresh_schematic_panel()

    window._duplicate_symbol("U1")

    assert [c.ref for c in window.bus.document.components] == ["U1"]
    assert [part.ref for part in window.bus.document.parts] == ["U2"]
    _close(window)


def test_only_a_symbol_somebody_moved_is_offered_back_to_the_layout() -> None:
    """On every other symbol the entry would do nothing and say so."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")

    assert "&Arrange This Symbol" not in _labels(window.sheet_menu(_over(window, "R1")))

    _move_symbol(window, "R1", 50.8, 25.4)

    assert "&Arrange This Symbol" in _labels(window.sheet_menu(_over(window, "R1")))
    _close(window)


def test_moving_one_symbol_gives_every_symbol_a_place() -> None:
    """THE FIRST EDIT FREEZES THE SHEET, and it has to: a layout that arranged twenty
    symbols around the one somebody had placed would move the twenty every time the one
    moved. One command, so it is one undo step."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    before = {
        s.ref: (s.at.x, s.at.y) for s in window.schematic_view.item.drawing.symbols
    }

    _move_symbol(window, "R1", 50.8, 25.4)

    placed = {p.id for p in window.bus.document.sheet}
    assert placed == {p.id for p in window.bus.document.parts}
    after = {s.ref: (s.at.x, s.at.y) for s in window.schematic_view.item.drawing.symbols}
    assert after["R1"] == (50.8, 25.4)
    # ...and nothing else moved, which is the whole point of freezing them all at once.
    assert after["R2"] == before["R2"]
    _close(window)


def test_turning_a_symbol_is_the_same_command_as_moving_one() -> None:
    """A position and an orientation are one fact about a symbol. Two commands would mean
    a rotate that could land between the two halves of a move on the undo stack."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    window.schematic_view.set_selection(["R1"])

    window.on_schematic_rotate(1)

    placement = next(p for p in window.bus.document.sheet)
    assert placement.rotation == 90
    window.on_schematic_rotate(1)
    assert next(p for p in window.bus.document.sheet).rotation == 180
    _close(window)


def test_flipping_a_symbol_swaps_which_way_its_pins_face() -> None:
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    window.schematic_view.set_selection(["R1"])

    window.on_schematic_mirror()

    assert next(p for p in window.bus.document.sheet).mirrored is True
    _close(window)


def test_arranging_one_symbol_leaves_the_others_where_they_were_put() -> None:
    """Undoing one bad drag must not undo an afternoon of good ones."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    _move_symbol(window, "R1", 50.8, 25.4)
    _move_symbol(window, "R2", 76.2, 25.4)
    kept = next(p.id for p in window.bus.document.parts if p.ref == "R2")

    _entry(window.sheet_menu(_over(window, "R1")), "Arrange This Symbol").trigger()

    assert [placement.id for placement in window.bus.document.sheet] == [kept]
    _close(window)


def test_a_wire_drawn_on_the_sheet_joins_the_pins_and_stays_drawn() -> None:
    """Both halves or neither: dragging from one pin to another joins them and leaves a
    line saying so, and an undo that took back one and kept the other would be a lie about
    what just happened."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")

    window._on_sheet_wire_drawn("R1", "2", "R2", "1", [(0.0, 0.0), (10.16, 0.0)])

    document = window.bus.document
    assert len(document.sheet_wires) == 1
    joined = {
        frozenset((n.component_ref, n.pin) for n in net.nodes) for net in document.nets
    }
    assert any({("R1", "2"), ("R2", "1")} <= pair for pair in joined)
    # ...and one undo takes back the wire AND the connection, because they were one command.
    window.bus.undo()
    assert window.bus.document.sheet_wires == ()
    _close(window)


def test_drawing_a_wire_on_a_sheet_nobody_has_touched_fixes_the_layout_first() -> None:
    """Storing a line between two points the layout is still free to move would be storing
    a line that is wrong the next time anything is added."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    assert window.bus.document.sheet == ()

    window._on_sheet_wire_drawn("R1", "2", "R2", "1", [(0.0, 0.0), (10.16, 0.0)])

    assert len(window.bus.document.sheet) == 2
    _close(window)


def test_a_drawn_wire_can_be_rubbed_out_without_disconnecting_anything() -> None:
    """A wire is how a join was DRAWN. Deleting the picture of a join is not the same
    decision as taking a pin off a net -- rubbed out, the two pins stay connected and the
    sheet goes back to saying so by name."""
    from perfboard_studio.model import Point2

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    window._on_sheet_wire_drawn("R1", "2", "R2", "1", [(0.0, 0.0), (10.16, 0.0)])
    window._refresh_schematic_panel()
    wire = window.bus.document.sheet_wires[0]
    nets_before = window.bus.document.nets

    # The menu finds it by where the click landed, the same distance the panel picks with.
    assert window._drawn_wire_at(Point2(x=wire.path[0].x, y=wire.path[0].y)) == wire
    window._rub_out_wire(wire)

    assert window.bus.document.sheet_wires == ()
    assert window.bus.document.nets == nets_before
    _close(window)


def test_a_click_on_bare_sheet_is_offered_no_wire_to_rub_out() -> None:
    from perfboard_studio.model import Point2

    window = _blank_window()
    _add(window, "R1", "r-axial-3")

    assert window._drawn_wire_at(Point2(x=999.0, y=999.0)) is None
    _close(window)


def test_a_selection_on_the_sheet_survives_the_redraw_a_command_causes() -> None:
    """The drawing is rebuilt after every command. A selection that vanished each time
    would mean turning a symbol twice took two clicks on it."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    window.schematic_view.set_selection(["R1"])

    window.on_schematic_rotate(1)
    window._refresh_schematic_panel()

    assert window.schematic_view.selected_refs == ["R1"]
    assert window.schematic_view.item.selected_refs == frozenset({"R1"})
    # ...and a second turn lands on the same symbol.
    window.on_schematic_rotate(1)
    assert next(p for p in window.bus.document.sheet if p.rotation).rotation == 180
    _close(window)


def test_an_arrow_key_nudges_the_selection_one_grid_square() -> None:
    """The same command a drag ends in, so it undoes and redoes as one thing -- the rule
    the board's own nudge follows."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    from perfboard_studio.schematic import GRID_MM

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    view = window.schematic_view
    view.set_selection(["R1"])
    before = next(s for s in view.item.drawing.symbols if s.ref == "R1").at.x

    view.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    )
    window._refresh_schematic_panel()

    after = next(s for s in view.item.drawing.symbols if s.ref == "R1").at.x
    assert round(after - before, 6) == round(GRID_MM, 6)
    _close(window)


def test_a_note_is_put_on_the_sheet_and_taken_off_it() -> None:
    window = _blank_window()
    _add(window, "R1", "r-axial-3")

    window.on_sheet_note_drawn("rectangle", 0.0, 0.0, 25.4, 12.7)

    assert [n.kind for n in window.bus.document.sheet_notes] == ["rectangle"]
    window._refresh_schematic_panel()
    assert len(window.schematic_view.item.drawing.annotations) == 1

    window.schematic_view.set_selection([], [0])
    window.on_sheet_delete()

    assert window.bus.document.sheet_notes == ()
    _close(window)


def test_a_part_dropped_on_the_sheet_joins_the_design_where_it_landed() -> None:
    """part.add and not component.place: the board is not involved, which is the whole
    point of drawing a circuit before laying one out."""
    window = _blank_window()

    window._on_sheet_footprint_dropped("r-axial-3", 50.8, 25.4)

    assert [p.footprint_id for p in window.bus.document.parts] == ["r-axial-3"]
    assert window.bus.document.components == ()
    placement = next(p for p in window.bus.document.sheet)
    assert (placement.at.x, placement.at.y) == (50.8, 25.4)
    _close(window)


def test_a_right_click_on_a_wire_offers_the_net() -> None:
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    _wire(window, "OUT", ("R1", "1"), ("R2", "2"))
    wire = window.schematic_view.item.drawing.wires[0]
    middle = wire.path[len(wire.path) // 2]

    labels = _labels(window.sheet_menu(_sheet_at(window, middle.x, middle.y)))

    assert labels == ["Re&name Net…", "Net &Class", "&Edit Net…", "De&lete Net"]
    _close(window)


def test_the_class_submenu_offers_exactly_what_the_net_dialog_does() -> None:
    """One table, two consumers (``NetDialog.NET_CLASSES``). A class only the dialog knew
    about would be one you could set and never see; one only the menu knew about would be
    one you could reach without being told what it costs."""
    from PySide6.QtWidgets import QMenu

    from perfboard_studio.ui.main import NetDialog

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    net_id = _wire(window, "OUT", ("R1", "1"))
    menu = QMenu()

    window._add_net_entries(menu, net_id)

    submenu = _entry(menu, "Class").menu()
    assert [a.text() for a in submenu.actions()] == [
        row[2] for row in NetDialog.NET_CLASSES
    ]
    # The one it already is, ticked -- otherwise the menu is a list of three things to do
    # rather than a statement of what this net is.
    assert [a.isChecked() for a in submenu.actions()] == [True, False, False]
    _close(window)


def test_making_a_net_a_ground_draws_it_as_a_rail() -> None:
    """The class is not a label on this sheet. A ground net becomes rail glyphs and is
    kept out of the layering graph that decides the columns -- so this entry changes what
    the drawing looks like, which is why it is worth reaching from the drawing."""
    from PySide6.QtWidgets import QMenu

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    net_id = _wire(window, "GND", ("R1", "1"), ("R2", "1"))
    menu = QMenu()
    window._add_net_entries(menu, net_id)

    next(a for a in _entry(menu, "Class").menu().actions() if "Ground" in a.text()).trigger()
    window._refresh_schematic_panel()

    assert [net.net_class for net in window.bus.document.nets] == ["ground"]
    drawing = window.schematic_view.item.drawing
    assert [rail.net_name for rail in drawing.rails] == ["GND", "GND"]
    assert drawing.wires == ()
    _close(window)


def test_renaming_a_net_from_the_sheet_keeps_its_pins(monkeypatch) -> None:
    from PySide6.QtWidgets import QInputDialog, QMenu

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    net_id = _wire(window, "OUT", ("R1", "1"))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("VOUT", True))
    menu = QMenu()
    window._add_net_entries(menu, net_id)

    _entry(menu, "name Net").trigger()

    net = window.bus.document.nets[0]
    assert net.name == "VOUT"
    assert [node.component_ref for node in net.nodes] == ["R1"]
    _close(window)


def test_a_pin_on_a_net_can_be_taken_off_it_from_the_sheet() -> None:
    """The one entry with no other door on this sheet, and the one you ask for while
    looking at the pin that is wired to the wrong thing."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    _wire(window, "OUT", ("R1", "1"), ("R2", "2"))
    symbol = next(s for s in window.schematic_view.item.drawing.symbols if s.ref == "R1")
    pin = next(p for p in symbol.pins if p.number == "1")

    menu = window.sheet_menu(
        _sheet_at(window, symbol.at.x + pin.at.x, symbol.at.y + pin.at.y)
    )
    entry = _entry(menu, "Disconnect")
    assert entry.text() == "&Disconnect R1.1 from OUT"
    entry.trigger()

    assert [node.component_ref for node in window.bus.document.nets[0].nodes] == ["R2"]
    _close(window)


def test_a_pin_on_no_net_is_offered_no_way_off_one() -> None:
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    symbol = next(s for s in window.schematic_view.item.drawing.symbols if s.ref == "R1")
    pin = next(p for p in symbol.pins if p.number == "1")

    labels = _labels(
        window.sheet_menu(_sheet_at(window, symbol.at.x + pin.at.x, symbol.at.y + pin.at.y))
    )

    assert not any("Disconnect" in label for label in labels)
    _close(window)


def test_a_right_click_while_wiring_cancels_the_pair_instead_of_opening_a_menu() -> None:
    """The board's rule about a mode owning the click. A menu here would open over the pin
    somebody was aiming at and leave the pending pin armed underneath it."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    window.on_sheet_tool("wire")
    window._on_schematic_pin_clicked("R1", "1")
    asked: list[QPoint] = []
    window.schematic_view.contextMenuRequested.connect(asked.append)

    window.schematic_view.contextMenuEvent(
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(4, 4), QPoint(4, 4))
    )

    assert asked == []
    assert window.schematic_view.pending_pin is None
    _close(window)


# ---------------------------------------------------------------------------
# A part the library does not have
# ---------------------------------------------------------------------------
#
# Sixty-one footprints is a good library and not every part anybody owns. What the dialog
# produces is an ID that carries its own dimensions, so nothing is stored and the part
# travels with the board -- and the property everything below is about is that the id it
# builds is one the ENGINE reads back as the same part. A dialog that produced an id the
# grammar could not parse would not fail: it would put a part in the document that vanishes
# the next time the file is opened.


def _custom_document():
    """A board holding one part the library has never heard of."""
    from perfboard_studio.model import (
        Board,
        ComponentInstance,
        DocumentMeta,
        HoleCoord,
        PerfDocument,
    )

    board = Board(
        type="pad-per-hole", cols=30, rows=20, pitch=2.54, thickness=1.6,
        material="FR4", pad_diameter=1.9, drill_diameter=0.8,
    )
    return PerfDocument(
        meta=DocumentMeta(name="odd", created="", modified=""),
        board=board,
        components=(
            ComponentInstance(
                id="c1", ref="M1", value="sensor",
                footprint_id="box-4x2-p1-r3-15x10x8",
                anchor=HoleCoord(col=5, row=5),
            ),
        ),
    )


def test_every_family_in_the_dialog_builds_an_id_the_engine_reads_back() -> None:
    """The one property the whole feature rests on, checked family by family.

    The dialog never spells an id: it calls the engine's own generator and shows what came
    back. This walks every family at its defaults and asserts the round trip, so a family
    wired to the wrong generator -- or given a default outside what the grammar accepts --
    fails here rather than by putting an unreadable part in somebody's document.
    """
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.main import CustomPartDialog

    dialog = CustomPartDialog()
    assert dialog.family.count() >= 9
    for index in range(dialog.family.count()):
        dialog.family.setCurrentIndex(index)
        footprint = dialog.chosen()
        assert footprint is not None, dialog.family.itemText(index)
        assert get_footprint(footprint.id) == footprint, footprint.id
        assert dialog.identifier.text() == footprint.id
    dialog.deleteLater()


def test_the_dialog_refuses_a_combination_that_is_not_a_part() -> None:
    """A DIP has an even pin count, and the spin box cannot know that -- the generator
    does. Refused HERE, with the number that caused it still on screen, rather than three
    steps later as a footprint nothing recognises."""
    from PySide6.QtWidgets import QDialogButtonBox

    from perfboard_studio.ui.main import CustomPartDialog

    dialog = CustomPartDialog()
    dip = next(
        index
        for index in range(dialog.family.count())
        if "DIP" in dialog.family.itemText(index)
    )
    dialog.family.setCurrentIndex(dip)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    dialog._widgets["pins"].setValue(20)
    assert dialog.chosen() is not None
    assert ok is not None and ok.isEnabled()

    dialog._widgets["pins"].setValue(21)
    assert dialog.chosen() is None
    assert not ok.isEnabled()
    assert dialog.identifier.text() == ""
    dialog.deleteLater()


def test_the_parts_dock_offers_the_custom_parts_this_board_already_uses() -> None:
    """Opening somebody else's board has to show its parts.

    Derived from the document rather than remembered, which is the whole point of putting
    the dimensions in the id: a file using a custom part is already carrying the definition,
    so there is nothing this window could have been told and nothing to install.
    """
    window = _window_on(_custom_document())
    try:
        custom = window.custom_footprints()
        assert "box-4x2-p1-r3-15x10x8" in custom
        assert len(custom["box-4x2-p1-r3-15x10x8"].pins) == 8

        from perfboard_studio.ui.main import ROLE_FOOTPRINT_ID

        labels = []
        tree = window.library_tree
        for index in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(index)
            for child in range(group.childCount()):
                labels.append(group.child(child).data(0, ROLE_FOOTPRINT_ID))
        assert "box-4x2-p1-r3-15x10x8" in labels
    finally:
        _close(window)


def test_a_custom_part_can_be_placed_and_shows_up_on_the_board() -> None:
    """The end of it: a part the library does not have, on the board, drawn.

    The scene is built from the document through the same lookup everything else uses, so
    a footprint that only resolved in the dialog would leave a part on the board with no
    pads under it.
    """
    window = _window_on(_custom_document())
    try:
        drawn = [
            item for item in window.scene.items() if isinstance(item, ComponentItem)
        ]
        assert [item.comp.ref for item in drawn] == ["M1"]
        # Eight pads under it, because the lookup resolved the id rather than
        # shrugging: a part with no footprint is drawn as a marker with no pins.
        assert len(drawn[0].fp.pins) == 8
    finally:
        _close(window)


def test_editing_a_custom_part_does_not_turn_it_into_a_resistor() -> None:
    """``select_footprint`` puts a part the library does not have into its own list first.

    Without that the properties dialog opens on whatever happens to be first and pressing
    OK changes the part -- silently, into something with two pins where there were eight.
    """
    from perfboard_studio.ui.main import AddPartDialog

    document = _custom_document()
    dialog = AddPartDialog(document)
    dialog.select_footprint("box-4x2-p1-r3-15x10x8")
    assert dialog.chosen_footprint_id() == "box-4x2-p1-r3-15x10x8"
    dialog.deleteLater()
def _dirty(window) -> None:
    """Move a part, so the window differs from what is on disk.

    Through the bus like everything else here, because ``is_modified`` compares the
    document by IDENTITY -- and a command is the only thing that makes a new one.
    """
    component = window.bus.document.components[0]
    anchor = HoleCoord(component.anchor.col + 1, component.anchor.row)
    result = window.bus.dispatch(
        "component.move", MoveComponentPayload(id=component.id, anchor=anchor)
    )
    assert result.ok, result.message


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------
#
# The file watcher already refuses to reload over unsaved edits, because losing somebody's
# work to a background event is the one outcome that must not happen. This is the other
# half of that sentence: the process can stop without asking anybody.


def test_building_a_window_saves_nothing(_recovery_in_a_temp_dir) -> None:
    """The same rule the update check follows, and for a related reason: a suite that
    builds a great many windows has no business leaving a great many files in somebody's
    profile. The timer is started by ``main()``, not by a constructor."""
    window = _window_on(_load_dense())
    try:
        assert not _recovery_in_a_temp_dir.exists()
        assert not window._autosave_timer.isActive()
    finally:
        _close(window)


def test_a_tick_writes_the_board_only_when_there_is_something_to_lose() -> None:
    """Unmodified means the file on disk already has it, and a record then says something
    untrue: that there was unsaved work. The next start would offer it back."""
    window = _window_on(_load_dense())
    try:
        window._on_autosave_tick()
        assert not window._autosave.written

        _dirty(window)
        window._on_autosave_tick()
        assert window._autosave.written
        assert window._autosave.path.exists()
    finally:
        _close(window)


def test_a_tick_tidies_up_after_the_work_stops_being_unsaved() -> None:
    """Undo your way back to where you started and there is nothing to recover any more."""
    window = _window_on(_load_dense())
    try:
        _dirty(window)
        window._on_autosave_tick()
        assert window._autosave.path.exists()

        window.on_undo()
        window._on_autosave_tick()
        assert not window._autosave.path.exists()
    finally:
        _close(window)


def test_saving_removes_the_recovery_record(tmp_path) -> None:
    """A record's existence means "there was unsaved work". After a save there is not."""
    window = _window_on(_load_dense())
    try:
        _dirty(window)
        window._on_autosave_tick()
        assert window._autosave.path.exists()

        window._save_to(tmp_path / "board.perf")
        assert not window._autosave.path.exists()
    finally:
        _close(window)


def test_closing_cleanly_removes_the_recovery_record() -> None:
    """Either the work was saved or the user said discard, and both are decisions. Leaving
    the record would ask them the same question again at the next start."""
    window = _window_on(_load_dense())
    _dirty(window)
    window._on_autosave_tick()
    path = window._autosave.path
    assert path.exists()

    _close(window)
    assert not path.exists()


def test_a_recovered_board_arrives_unsaved_and_pointed_at_its_own_file(tmp_path) -> None:
    """Recovering is not opening. The document did not come from the file it names, so
    saying it did would be the one lie that matters here: the title would show no marker,
    closing would not ask, and the next crash would take it again."""
    from perfboard_studio.recovery import RecoveryRecord

    board = tmp_path / "amp.perf"
    text = persist.serialize_document(_load_dense())
    board.write_text("a different, older board", encoding="utf-8")

    window = _window_on(_load_dense())
    try:
        record = RecoveryRecord(
            session="gone", document_path=str(board),
            saved_at="2026-08-31T14:00:00.000Z", version="0.9.0", document=text,
        )
        assert window._load_recovered(record) is True

        assert window.current_path == board
        assert window.is_modified, "a recovered board has not been saved anywhere"
        assert len(window.bus.document.components) == len(_load_dense().components)
        # THE FILE IS UNTOUCHED. Recovery offers work; it does not write any.
        assert board.read_text(encoding="utf-8") == "a different, older board"
    finally:
        _close(window)


def test_a_record_the_file_already_has_is_dropped_without_asking(tmp_path) -> None:
    """The save landed and the crash beat the deletion to it. There is no decision here, so
    there is no question -- and the record goes, rather than being offered every start."""
    from perfboard_studio.recovery import RecoveryRecord, format_record
    from perfboard_studio.ui.autosave import Autosave

    board = tmp_path / "amp.perf"
    text = persist.serialize_document(_load_dense())
    board.write_text(text, encoding="utf-8")

    window = _window_on(_load_dense())
    try:
        directory = window._autosave.directory
        directory.mkdir(parents=True, exist_ok=True)
        stale = directory / "gone.perfrecover"
        stale.write_text(
            format_record(
                RecoveryRecord(
                    session="gone", document_path=str(board),
                    saved_at="2026-08-31T14:00:00.000Z", version="0.9.0", document=text,
                )
            ),
            encoding="utf-8",
        )
        assert len(Autosave(directory).records()) == 1

        # No dialog is reached, so no monkeypatching is needed: a message box here would
        # hang the run, which is itself the assertion.
        window.offer_recovery()
        assert not stale.exists()
    finally:
        _close(window)
def _answer_recovery(monkeypatch, label: str) -> list[str]:
    """Press one of the recovery dialog's buttons without a person.

    BY LABEL, not by position. Qt lays a message box out in the platform's own button
    order, so an index would be testing this machine's conventions rather than the
    branch -- and would pass on one operating system while pressing Discard on another.
    """
    from PySide6.QtWidgets import QMessageBox

    offered: list[str] = []

    def fake_exec(self):
        offered.extend(button.text() for button in self.buttons())
        self._chosen = next(b for b in self.buttons() if b.text() == label)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self._chosen)
    return offered


def _leave_a_record(window, board: pathlib.Path, document_text: str) -> pathlib.Path:
    """A record from a session that did not come back, for ``board``."""
    from perfboard_studio.recovery import RecoveryRecord, format_record

    directory = window._autosave.directory
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "gone.perfrecover"
    path.write_text(
        format_record(
            RecoveryRecord(
                session="gone",
                document_path=str(board),
                saved_at="2099-01-01T00:00:00.000Z",
                version="0.9.0",
                document=document_text,
            )
        ),
        encoding="utf-8",
    )
    return path


def test_accepting_the_offer_opens_the_recovered_board_and_leaves_the_file_alone(
    tmp_path, monkeypatch
) -> None:
    """The whole gesture, end to end: work is found, offered, opened -- and the file it
    came from is exactly as it was until the user saves."""
    board = tmp_path / "amp.perf"
    board.write_text("an older board that never parsed", encoding="utf-8")
    recovered = persist.serialize_document(_load_dense())

    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta

    window = _window_on(
        create_starter_document(DocumentMeta(name="untitled", created="", modified=""))
    )
    try:
        record_path = _leave_a_record(window, board, recovered)
        offered = _answer_recovery(monkeypatch, "Open the Recovered Board")

        window.offer_recovery()

        assert sorted(offered) == ["Decide Later", "Discard It", "Open the Recovered Board"]
        assert window.current_path == board
        assert window.is_modified
        assert len(window.bus.document.components) == len(_load_dense().components)
        assert board.read_text(encoding="utf-8") == "an older board that never parsed"
        # Handed over. Keeping it would offer the same board again next time, on top of
        # whatever the user does with it now.
        assert not record_path.exists()
    finally:
        _close(window)


def test_deciding_later_destroys_nothing(tmp_path, monkeypatch) -> None:
    """The default answer, and it has to be the one that cannot lose anything: the board
    stays where it is and the question comes back at the next start."""
    board = tmp_path / "amp.perf"
    board.write_text("an older board", encoding="utf-8")

    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta

    window = _window_on(
        create_starter_document(DocumentMeta(name="untitled", created="", modified=""))
    )
    try:
        record_path = _leave_a_record(window, board, persist.serialize_document(_load_dense()))
        started_with = window.bus.document
        _answer_recovery(monkeypatch, "Decide Later")

        window.offer_recovery()

        assert record_path.exists()
        assert window.bus.document is started_with
        assert board.read_text(encoding="utf-8") == "an older board"
    finally:
        _close(window)


def test_discarding_the_offer_takes_the_record_and_nothing_else(
    tmp_path, monkeypatch
) -> None:
    board = tmp_path / "amp.perf"
    board.write_text("an older board", encoding="utf-8")

    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta

    window = _window_on(
        create_starter_document(DocumentMeta(name="untitled", created="", modified=""))
    )
    try:
        record_path = _leave_a_record(window, board, persist.serialize_document(_load_dense()))
        started_with = window.bus.document
        _answer_recovery(monkeypatch, "Discard It")

        window.offer_recovery()

        assert not record_path.exists()
        assert window.bus.document is started_with
        assert board.read_text(encoding="utf-8") == "an older board"
    finally:
        _close(window)


# ---------------------------------------------------------------------------
# Modes surviving a rebuild, and the two sides agreeing about the keyboard
# ---------------------------------------------------------------------------
#
# Every command rebuilds the scene, and so does a flip and a colour change. A mode is
# state the rebuild must carry across; its marker on the board is only a picture of it.
# Each test here is a thing that was wrong: an item the rebuild destroyed and the mode
# still held a wrapper for, or a picture the rebuild threw away and never redrew.


def test_measuring_survives_a_flip() -> None:
    """The measurement marker is destroyed by clear() like every other item. The mode
    forgot to forget it, so the next click -- or the next arming of ANY tool, all of
    which disarm measuring first -- raised from removeItem and left every tool dead."""
    document = _load_dense()
    bus = _new_bus(document)
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_measure(True)
    scene.measure_click(HoleCoord(2, 2))

    scene.set_side("bottom")  # a rebuild in the middle of a measurement

    scene.measure_click(HoleCoord(5, 2))  # raised RuntimeError before the fix
    scene.leave_mode()
    assert not scene.in_a_mode


def test_picking_a_part_disarms_the_drawing_tool() -> None:
    """The board modes are mutually exclusive. Arming a footprint mid-trace used to leave
    both armed: the ghost followed the pointer while every click still extended the trace."""
    document = _load_dense()
    bus = _new_bus(document)
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_drawing("solder-trace")
    scene.draw_click(HoleCoord(1, 1))

    scene.arm_placement("r-axial-3")

    assert scene.armed_draw_kind is None
    assert scene.armed_footprint_id == "r-axial-3"


def test_a_half_drawn_conductor_survives_a_rebuild() -> None:
    """The drawn path is state; the preview is its picture. A flip two clicks into a trace
    used to drop the picture and keep the path, so Enter committed an invisible chain."""
    from perfboard_studio.ui.view2d import DrawPreviewItem

    document = _load_dense()
    bus = _new_bus(document)
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    scene.arm_drawing("solder-trace")
    scene.draw_click(HoleCoord(1, 1))
    scene.draw_click(HoleCoord(2, 1))

    scene.set_side("bottom")

    previews = [item for item in scene.items() if isinstance(item, DrawPreviewItem)]
    assert len(previews) == 1
    assert previews[0].path == [HoleCoord(1, 1), HoleCoord(2, 1)]
    assert scene.armed_draw_kind == "solder-trace"


def test_the_ghost_comes_back_under_the_pointer_after_a_placement() -> None:
    """A fresh ghost starts at the origin, and placing a part rebuilds the scene -- so the
    ghost for the NEXT part appeared at A1 until the pointer was jogged, at exactly the
    moment it was being lined up."""
    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta
    from perfboard_studio.ui.main import MainWindow

    # A window, because the rebuild after a command is the window's doing.
    window = MainWindow(create_starter_document(DocumentMeta(name="t", created="", modified="")))
    try:
        scene = window.scene
        board = scene.document.board
        scene.arm_placement("r-axial-3")
        scene.hover_at(hole_to_screen(HoleCoord(8, 8), board, "top"))
        ghost_before = scene._ghost

        result = scene.place_armed(HoleCoord(8, 8))

        assert result is not None and result.ok, result
        assert scene._ghost is not None and scene._ghost is not ghost_before
        assert scene._ghost.anchor == HoleCoord(8, 8)
    finally:
        _close(window)


def test_arrow_keys_follow_the_screen_on_the_solder_side() -> None:
    """Right means "to the right of where it is on screen". The solder side is mirrored,
    so on that side a step to the right is one column DOWN in the document -- which the
    keys used to get backwards, while a drag got it right."""
    from PySide6.QtGui import QKeyEvent

    document = _load_dense()
    bus = _new_bus(document)
    scene = BoardScene(bus.document, footprint_lookup(), side="bottom", bus=bus)
    comp_id = next(iter(scene.component_items))
    before = next(c for c in bus.document.components if c.id == comp_id).anchor
    scene.select_components([comp_id])

    scene.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))

    after = next(c for c in bus.document.components if c.id == comp_id).anchor
    assert after.col == before.col - 1
    board = bus.document.board
    assert hole_to_screen(after, board, "bottom").x() > hole_to_screen(before, board, "bottom").x()


def test_conductor_selection_survives_a_rebuild() -> None:
    """Parts have always been re-selected by id after the rebuild every command causes.
    Conductors were not, so a trace selected to be deleted was deselected by whatever
    unrelated edit came first."""
    document = _load_dense()
    bus = _new_bus(document)
    scene = BoardScene(bus.document, footprint_lookup(), side="top", bus=bus)
    conductor = next(item for item in scene.items() if isinstance(item, ConductorItem))
    conductor.setSelected(True)
    wanted = conductor.conductor_id

    other = next(iter(scene.component_items))
    scene.select_components([other])  # a part selection, then a command that rebuilds
    conductor.setSelected(True)
    scene.nudge_selection(1, 0)

    assert scene.selected_conductor_ids() == (wanted,)


def test_the_ghost_is_mirrored_on_the_solder_side() -> None:
    """The anchor is mirrored by hole_to_screen on the solder side and the pins have to be
    mirrored with it. They were painted at their raw offsets, so a DIP's ghost showed its
    pins running one way while the placement put them the other."""
    from perfboard_studio.ui.view2d import PlacementGhostItem

    document = _load_dense()
    board = document.board
    footprint = footprint_lookup()("r-axial-3")
    assert footprint is not None
    far_pin = max(footprint.pins, key=lambda p: p.d_col)
    assert far_pin.d_col > 0

    def pin_dot_x(side: str) -> float:
        ghost = PlacementGhostItem(footprint, board, side)  # type: ignore[arg-type]
        size = 400
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        painter.translate(size / 2, size / 2)
        painter.scale(8, 8)
        ghost.paint(painter, None)
        painter.end()
        # The far pin's dot: the darkest pixels on the row through the pins, away from
        # the anchor at the centre.
        y = size // 2
        xs = [x for x in range(size) if QColor(image.pixel(x, y)).lightness() < 200 and abs(x - size / 2) > 20]
        return sum(xs) / len(xs) - size / 2

    assert pin_dot_x("top") > 0
    assert pin_dot_x("bottom") < 0


def test_zoom_lands_on_the_limit_rather_than_stopping_short_of_it() -> None:
    """The last notch before a limit used to do nothing, so the zoom stopped one step
    short of its own bound and the wheel appeared to have died."""
    from perfboard_studio.ui.view2d import MAX_SCALE, MIN_SCALE, BoardView

    document = _load_dense()
    scene = BoardScene(document, footprint_lookup(), side="top")
    view = BoardView(scene)
    view.resetTransform()
    view.scale(MAX_SCALE * 0.95, MAX_SCALE * 0.95)

    view.zoom_by(1.25)
    assert view.current_scale() == pytest.approx(MAX_SCALE)

    view.resetTransform()
    view.scale(MIN_SCALE * 1.05, MIN_SCALE * 1.05)
    view.zoom_by(0.5)
    assert view.current_scale() == pytest.approx(MIN_SCALE)


def test_a_fit_stays_inside_the_zoom_range() -> None:
    """A fit that lands outside the range leaves every wheel step outside it too, so the
    wheel is dead in both directions. Two pads framed in a large viewport did that."""
    from perfboard_studio.ui.view2d import MAX_SCALE, BoardView

    document = _load_dense()
    scene = BoardScene(document, footprint_lookup(), side="top")
    view = BoardView(scene)
    view.resize(1600, 1200)
    view.show()

    view.center_on_holes([HoleCoord(3, 3), HoleCoord(4, 3)], document.board, "top")

    assert view.current_scale() <= MAX_SCALE
    view.close()


def test_leaving_the_view_clears_the_hovered_hole() -> None:
    """The status bar kept naming the hole the pointer left the board over, and Paste
    from the menu still landed there."""
    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(_load_dense())
    try:
        board = window.bus.document.board
        window.scene.hover_at(hole_to_screen(HoleCoord(4, 4), board, "top"))
        assert window._hovered_hole == HoleCoord(4, 4)

        window.view.leaveEvent(QEvent(QEvent.Type.Leave))

        assert window._hovered_hole == HoleCoord(-1, -1)
    finally:
        _close(window)



# ---------------------------------------------------------------------------
# The window's own rough edges: what an action is enabled for, what a flip keeps,
# what a question puts under Enter
# ---------------------------------------------------------------------------


def _first_conductor_item(window) -> ConductorItem:
    return next(item for item in window.scene.items() if isinstance(item, ConductorItem))


def test_delete_is_live_for_a_conductor_on_its_own(monkeypatch) -> None:
    """A single bad route is the whole reason conductors are selectable, and the menu
    item was greyed out for exactly that selection."""
    window = _window_on(_load_dense())
    try:
        conductor = _first_conductor_item(window)
        conductor.setSelected(True)
        window._refresh_selection_state()

        assert window.act_delete.isEnabled()
        assert "1" in window.label_selection.text()

        monkeypatch.setattr(type(window), "_confirm", lambda self, *a, **k: True)
        wanted = conductor.conductor_id
        window.on_delete_selection()
        assert all(c.id != wanted for c in window.bus.document.conductors)
    finally:
        _close(window)


def test_deleting_a_mixed_selection_takes_the_conductors_too(monkeypatch) -> None:
    """A rubber band that took a part and the two traces on it used to delete the part
    and keep the traces without a word."""
    window = _window_on(_load_dense())
    try:
        conductor = _first_conductor_item(window)
        conductor.setSelected(True)
        comp_id = next(iter(window.scene.component_items))
        window.scene.component_items[comp_id].setSelected(True)
        monkeypatch.setattr(type(window), "_confirm", lambda self, *a, **k: True)
        wanted = conductor.conductor_id

        window.on_delete_selection()

        assert all(c.id != comp_id for c in window.bus.document.components)
        assert all(c.id != wanted for c in window.bus.document.conductors)
    finally:
        _close(window)


def test_a_confirmation_puts_cancel_under_enter(monkeypatch) -> None:
    """QMessageBox.question with no buttons named put Yes under Enter, so a delete
    answered by reflex was a delete."""
    from PySide6.QtWidgets import QMessageBox

    window = _window_on(_load_dense())
    seen: dict[str, str] = {}

    def fake_exec(self):
        seen["default"] = self.defaultButton().text()
        seen["buttons"] = "|".join(b.text() for b in self.buttons())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)
    try:
        assert window._confirm("Delete parts", "Delete R1?", "Delete") is False
        assert seen["default"] == "Cancel"
        assert "Delete" in seen["buttons"]
    finally:
        _close(window)


def test_flipping_keeps_the_view_on_the_same_part_of_the_board() -> None:
    """The scene is mirrored about the hole span's midpoint, so a flip while zoomed in on
    the left edge used to show the right edge."""
    from perfboard_studio.geometry import hole_span_mm

    window = _window_on(_load_dense())
    try:
        window.resize(1200, 800)
        window.show()
        QApplication.processEvents()
        board = window.bus.document.board
        span_w, _ = hole_span_mm(board)
        view = window.view
        view.resetTransform()
        view.scale(20, 20)
        view.centerOn(QPointF(5.0, 30.0))
        QApplication.processEvents()
        before = view.mapToScene(view.viewport().rect().center())

        window.on_flip_board()
        QApplication.processEvents()

        after = view.mapToScene(view.viewport().rect().center())
        assert abs(after.x() - (span_w - before.x())) < board.pitch
        assert abs(after.y() - before.y()) < board.pitch
    finally:
        _close(window)


def test_undo_and_redo_name_the_command_in_the_menu() -> None:
    window = _window_on(_load_dense())
    try:
        first = window.bus.document.components[0]
        window.bus.dispatch("component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(3, 3)))
        assert first.ref in window.act_undo.text()
        window.on_undo()
        assert first.ref in window.act_redo.text()
        assert first.ref not in window.act_undo.text()
    finally:
        _close(window)


def test_save_is_enabled_only_when_there_is_something_to_save(tmp_path) -> None:
    """Ctrl+S on an unmodified board rewrote the file -- a new modified stamp, a new
    mtime -- for nothing."""
    from perfboard_studio.ui.main import MainWindow

    board = tmp_path / "b.perf"
    board.write_text(persist.serialize_document(_load_dense()), encoding="utf-8")
    window = MainWindow(_load_dense(), board)
    try:
        assert not window.act_save.isEnabled()
        first = window.bus.document.components[0]
        window.bus.dispatch("component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(3, 3)))
        assert window.act_save.isEnabled()
    finally:
        _close(window)
    untitled = _window_on(_load_dense())
    try:
        assert untitled.act_save.isEnabled(), "an untitled board can always be saved somewhere"
    finally:
        _close(untitled)


def test_escape_leaves_the_status_bar_alone_when_there_is_nothing_to_leave() -> None:
    """Escape pressed out of reflex used to wipe the routing summary, posted with no
    timeout so it could be read."""
    window = _window_on(_load_dense())
    try:
        window.statusBar().showMessage("4 connections routed", 0)
        window.on_stop_tool()
        assert window.statusBar().currentMessage() == "4 connections routed"

        window.scene.arm_placement("r-axial-3")
        window.on_stop_tool()
        assert window.statusBar().currentMessage() == ""
        assert not window.scene.in_a_mode
    finally:
        _close(window)


def test_board_features_remove_needs_a_chosen_row() -> None:
    """With nothing picked the button used to delete the first row, chosen for the user."""
    from perfboard_studio.commands import AddMountingHolesPayload
    from perfboard_studio.ui.main import BoardFeaturesDialog

    window = _window_on(_load_dense())
    try:
        window.bus.dispatch("mounting-hole.addMany", AddMountingHolesPayload(ats=(HoleCoord(1, 1),)))
        dialog = BoardFeaturesDialog(window.bus, window)
        assert dialog.tree.topLevelItemCount() >= 1
        assert not dialog.act_remove.isEnabled()
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
        assert dialog.act_remove.isEnabled()
    finally:
        _close(window)


def test_the_window_will_not_close_under_a_running_planner() -> None:
    window = _window_on(_load_dense())
    window.show()
    QApplication.processEvents()
    try:
        window._planner_running = True
        window.close()
        assert window.isVisible()
    finally:
        window._planner_running = False
        _close(window)


def test_a_file_change_waits_for_a_running_planner(tmp_path) -> None:
    """The planner captured the document it is planning against; swapping the bus under
    it would commit that plan into a different board."""
    from perfboard_studio.ui.main import MainWindow

    board = tmp_path / "b.perf"
    board.write_text(persist.serialize_document(_load_dense()), encoding="utf-8")
    window = MainWindow(_load_dense(), board)
    try:
        window._planner_running = True
        started_with = window.bus
        board.write_text(persist.serialize_document(_load_dense()) + "\n", encoding="utf-8")
        window._reload_if_changed()
        assert window.bus is started_with
        assert window._watch_timer.isActive()
    finally:
        window._planner_running = False
        _close(window)


def test_a_recovery_record_that_will_not_parse_is_dropped_rather_than_offered_forever(
    tmp_path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta

    board = tmp_path / "amp.perf"
    board.write_text("an older board", encoding="utf-8")
    window = _window_on(create_starter_document(DocumentMeta(name="untitled", created="", modified="")))
    complaints: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda parent, title, text, *a, **k: complaints.append(text))
    )
    try:
        record_path = _leave_a_record(window, board, "this is not a board")
        _answer_recovery(monkeypatch, "Open the Recovered Board")

        window.offer_recovery()

        assert complaints, "the failure to open it is still said"
        assert not record_path.exists()
    finally:
        _close(window)


def test_the_autosave_warning_outlives_the_next_status_message(monkeypatch) -> None:
    """A status message is replaced by the next command's description within seconds;
    a recovery file that cannot be written is a condition, and it stays on screen until
    it can be."""
    window = _window_on(_load_dense())
    try:
        first = window.bus.document.components[0]
        window.bus.dispatch("component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(3, 3)))
        monkeypatch.setattr(window._autosave, "write", lambda text, path: False)
        window._on_autosave_tick()
        assert window.label_warning.text()

        window.statusBar().showMessage("Move R1 to C3")
        assert window.label_warning.text()

        monkeypatch.setattr(window._autosave, "write", lambda text, path: True)
        window._on_autosave_tick()
        assert window.label_warning.text() == ""
    finally:
        _close(window)


def test_a_truncated_netlist_is_reported_in_a_dialog_not_a_traceback(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    said: list[str] = []
    for kind in ("critical", "warning"):
        monkeypatch.setattr(
            QMessageBox, kind, staticmethod(lambda parent, title, text, *a, **k: said.append(text))
        )
    netlist = tmp_path / "broken.net"
    netlist.write_text('(export (version "E")', encoding="utf-8")
    window = _window_on(_load_dense())
    try:
        window.import_netlist_from(netlist)  # raised SExprSyntaxError before the fix
        assert said, "the failure is reported"
    finally:
        _close(window)


def test_an_imported_netlist_places_real_parts_with_their_values(tmp_path, monkeypatch) -> None:
    """The window places what ``parsers.kicad_parts`` read -- the catalog's BC547 with its
    value and pin names, the LED renumbered anode to pin 1 -- as one undo step, and says what
    it renumbered."""
    from PySide6.QtWidgets import QMessageBox

    from perfboard_studio.commands import create_empty_document
    from perfboard_studio.model import DocumentMeta

    from .test_kicad_parts import NETLIST

    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda parent, title, text, *a, **k: shown.append(text)),
    )
    netlist = tmp_path / "t.net"
    netlist.write_text(NETLIST, encoding="utf-8")
    doc = create_empty_document(DocumentMeta(name="t", created="", modified=""))
    window = _window_on(doc)
    try:
        window.import_netlist_from(netlist)
        parts = {c.ref: c for c in window.bus.document.components}
        assert parts["Q1"].value == "BC547" and parts["Q1"].footprint_id == "to92"
        assert dict(parts["Q1"].pin_names)["1"] == "C"
        assert parts["U2"].footprint_id == "to220"
        led = next(n for n in window.bus.document.nets if n.name == "+5V")
        assert ("D1", "1") in {(node.component_ref, node.pin) for node in led.nodes}
        assert any("Q1: pins renumbered" in text for text in shown)
        window.bus.undo()
        assert window.bus.document.components == ()
    finally:
        _close(window)


def test_right_clicking_a_conductor_offers_to_delete_it() -> None:
    """The menu used to offer the bare-board list over a trace, with no way to delete the
    trace from it."""
    window = _window_on(_load_dense())
    window.resize(1200, 800)
    window.show()
    QApplication.processEvents()
    try:
        window.view.fit_board()
        conductor = _first_conductor_item(window)
        board = window.bus.document.board
        where = hole_to_screen(conductor.conductor.path[0], board, "top")
        pos = window.view.mapFromScene(where)

        menu = window.board_menu(pos)

        assert conductor.isSelected()
        assert window.act_delete in menu.actions()
        assert window.act_properties not in menu.actions()
    finally:
        _close(window)


def test_a_refused_new_net_is_said_in_a_dialog_and_the_form_comes_back(monkeypatch) -> None:
    """A duplicate name refused into the status bar threw away everything typed."""
    from PySide6.QtWidgets import QMessageBox

    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    existing = window.bus.document.nets[0].name
    monkeypatch.setattr(main_module, "NetDialog", _StubNetDialog)
    _StubNetDialog.values_to_return = (existing, "signal", None, None)
    _StubNetDialog.accept_times = 1
    _StubNetDialog.opened = 0
    warned: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda parent, title, text, *a, **k: warned.append(text))
    )
    before = window.bus.document
    try:
        window.on_new_net()

        assert window.bus.document is before
        assert warned and "duplicate-net-name" in warned[0]
        assert _StubNetDialog.opened == 2, "the form is offered again, filled in"
    finally:
        _StubNetDialog.accept_times = None
        _close(window)


# ---------------------------------------------------------------------------
# Holes that read as holes, and leads that go down them
# ---------------------------------------------------------------------------
#
# Two things a photograph of the 3D view showed and no test could: every hole was a black
# cap standing ABOVE its own pad, so the board read as a grid of buttons rather than as
# perfboard; and every part hovered over the holes it is meant to be soldered into,
# because a lead stopped in mid-air at the pin position and a DIP had no pins at all.
# Neither is visible from the default camera, which is why both survived so long.


def test_a_hole_is_drawn_under_the_copper_and_not_over_it() -> None:
    """The bore has to be visible through the pad's hole from either face WITHOUT
    standing above the metal around it -- a cap proud of the copper occludes the pads on
    the rows behind it at every grazing angle, which is what made holes look plugged."""
    from perfboard_studio.ui import view3d

    board = _load_dense().board
    top, bottom = view3d.bore_span_z(board)

    assert 0.0 < top < view3d.pad_z(board, "top"), "under the top copper, over the substrate"
    assert view3d.pad_z(board, "bottom") < bottom < -board.thickness, "and the same underneath"


def test_every_archetype_puts_a_lead_through_every_one_of_its_holes() -> None:
    """One footprint per archetype, because the failure was per-builder.

    The lead has to start above the board and end past the far copper: that is what makes
    a part look soldered INTO the board rather than resting on top of it, and it is the
    only evidence the solder side has that anything came through at all.
    """
    from perfboard_studio.footprints import standard_footprints
    from perfboard_studio.model import ComponentInstance
    from perfboard_studio.ui import view3d

    board = _load_dense().board
    lookup = footprint_lookup()
    one_per_archetype: dict[str, str] = {}
    for footprint_id, footprint in sorted(standard_footprints().items()):
        one_per_archetype.setdefault(footprint.body.archetype, footprint_id)

    for archetype, footprint_id in sorted(one_per_archetype.items()):
        comp = ComponentInstance(
            id="c1", ref="X1", value="", footprint_id=footprint_id, anchor=HoleCoord(4, 4)
        )
        body = view3d._world_body(lookup, comp, board)
        assert body is not None, footprint_id
        footprint = lookup(footprint_id)
        assert footprint is not None
        builder = view3d._BUILDERS.get(archetype, view3d._box_pieces)

        leads = [
            piece
            for piece in builder(body)
            if piece.instances and piece.rgb == view3d.LEAD_RGB
        ]

        assert len(leads) == 1, f"{archetype}: expected one instanced lead piece"
        lead = leads[0]
        assert len(lead.instances) == len(body.pins), f"{archetype}: a lead per pin"
        # The source is built upright and glyphed at each pin, so its own bounds give the
        # length and the instance z gives where the middle of it sits. Updated first: a
        # source that has never been asked for its output reports VTK's "no bounds yet"
        # sentinel, which reads as a lead an inch below the board.
        lead.source.Update()
        low, high = lead.source.GetOutput().GetBounds()[4:6]
        centre_z = lead.instances[0][2]
        assert centre_z + high > view3d.pad_z(board, "top"), f"{archetype}: starts above the board"
        assert centre_z + low < view3d.pad_z(board, "bottom"), f"{archetype}: comes out the other side"


def test_a_lead_is_thin_enough_to_fit_the_hole_it_goes_down() -> None:
    """A lead wider than the drill would be a part that cannot be fitted, drawn as one
    that has been."""
    from perfboard_studio.model import ComponentInstance
    from perfboard_studio.ui import view3d

    board = _load_dense().board
    comp = ComponentInstance(
        id="c1", ref="R1", value="10k", footprint_id="r-axial-5", anchor=HoleCoord(4, 4)
    )
    body = view3d._world_body(footprint_lookup(), comp, board)
    assert body is not None

    lead = next(p for p in view3d._axial_pieces(body) if p.instances)
    lead.source.Update()
    bounds = lead.source.GetOutput().GetBounds()

    assert bounds[1] - bounds[0] < board.drill_diameter, "the lead fits the drilled hole"


# ---------------------------------------------------------------------------
# The board has holes in it
# ---------------------------------------------------------------------------
#
# The substrate was one solid cube and every hole was a dark cylinder laid over it. A
# photograph of the view showed what that is: a mark printed on the board, not something
# you can push a lead through. The plate is punched now, and these are the properties
# that make the punching correct rather than merely present.


def test_the_plate_is_punched_at_every_drilled_hole() -> None:
    """One tile per hole, and the tile has the drill taken out of the middle of it."""
    from perfboard_studio.ui import view3d

    board = _load_dense().board
    tile = view3d._tile_with_hole(board)

    points = [tile.GetPoint(index) for index in range(tile.GetNumberOfPoints())]
    reaches = sorted(round((x**2 + y**2) ** 0.5, 6) for x, y, _z in points)
    assert reaches[0] == pytest.approx(board.drill_diameter / 2), "the hole is the drill"
    assert reaches[-1] == pytest.approx(board.pitch / 2 * 2**0.5), "and the tile is a pitch square"


def test_a_tile_covers_exactly_one_pitch_so_the_surface_is_watertight() -> None:
    """Tiles are laid one per hole. A tile smaller than the pitch leaves a slot between
    every pair of holes; a larger one overlaps its neighbour and z-fights it."""
    from perfboard_studio.ui import view3d

    board = _load_dense().board
    bounds = view3d._tile_with_hole(board).GetBounds()

    assert bounds[1] - bounds[0] == pytest.approx(board.pitch)
    assert bounds[3] - bounds[2] == pytest.approx(board.pitch)


def test_a_flush_cut_board_has_no_border_and_a_bordered_one_does() -> None:
    from perfboard_studio.geometry import STANDARD_PRESETS, board_from_preset
    from perfboard_studio.ui import view3d

    flush = _load_dense().board
    assert flush.border_x_mm == 0 and flush.border_y_mm == 0
    assert view3d._border_rects(flush) == [], "no strip to draw, and no sliver either"

    preset = next(p for p in STANDARD_PRESETS if not p.single_sided and p.cols >= 20)
    bordered = board_from_preset(preset, flush)
    if bordered.border_x_mm or bordered.border_y_mm:
        rects = view3d._border_rects(bordered)
        assert rects, "the printed border is part of the board and has to be drawn"
        x0, y0, x1, y1 = view3d.board_outline_rect(bordered)
        for rx0, ry0, rx1, ry1 in rects:
            assert x0 - 1e-9 <= rx0 < rx1 <= x1 + 1e-9
            assert y0 - 1e-9 <= ry0 < ry1 <= y1 + 1e-9


def test_a_mounting_bore_is_drawn_where_its_offset_puts_it() -> None:
    """The offset is what lets a corner hole sit in the border, and this view was reading
    the hole address alone -- so every corner bore was drawn back on the grid, in the
    middle of four pads that are perfectly intact."""
    from perfboard_studio.geometry import mounting_hole_centre_mm
    from perfboard_studio.model import MountingHole
    from perfboard_studio.ui import view3d

    document = _load_dense()
    mount = MountingHole(
        id="mh-1", at=HoleCoord(0, 0), offset_x_mm=-2.1, offset_y_mm=-2.1, diameter=3.2
    )
    document = dataclasses.replace(document, mounting_holes=(mount,))

    bore = view3d._mounting_bores(document)[0]

    centre = mounting_hole_centre_mm(mount, document.board)
    assert (bore.x, bore.y) == pytest.approx((centre.x, -centre.y))
    assert bore.radius == pytest.approx(mount.diameter / 2)


def test_a_bore_takes_exactly_the_tiles_whose_copper_it_ate() -> None:
    """One bore, one answer. The patch of plate laid over the hole covers the tiles the
    bore reaches into, and those are the holes ``consumed_holes`` reports the copper gone
    from -- so the renderer and DRC cannot disagree about which pads a screw destroyed."""
    from perfboard_studio.geometry import consumed_holes
    from perfboard_studio.model import MountingHole
    from perfboard_studio.ui import view3d

    document = _load_dense()
    document = dataclasses.replace(
        document, mounting_holes=(MountingHole(id="mh-1", at=HoleCoord(4, 4), diameter=3.2),)
    )

    assert view3d.patched_holes(document) == consumed_holes(document)


def test_taking_a_rectangle_out_of_another_leaves_the_rest_of_it() -> None:
    """The printed border is drawn as rectangles and a bore in it has to be cut out of
    them. Pure arithmetic, and the one part of the plate that is not glyphed."""
    from perfboard_studio.ui import view3d

    whole = (0.0, 0.0, 10.0, 10.0)
    assert view3d._rect_without(whole, (20.0, 20.0, 30.0, 30.0)) == [whole], "no overlap"
    assert view3d._rect_without(whole, (-1.0, -1.0, 11.0, 11.0)) == [], "swallowed whole"

    pieces = view3d._rect_without(whole, (4.0, 4.0, 6.0, 6.0))

    assert len(pieces) == 4, "a hole in the middle leaves a frame of four"
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in pieces)
    assert area == pytest.approx(100.0 - 4.0)


def test_every_part_stands_exactly_as_tall_as_its_footprint_says() -> None:
    """VTK scales BEFORE it orients, and that turn maps a source's own z onto world y.

    So a scale written to flatten an upright can flattens its LENGTH instead: the crystal
    came out a quarter short with its domed cap floating in the air above it, and nothing
    said so -- the render looked like a part, just not that part. Height is the one number
    a reader of this view is checking against a case, so it is worth measuring rather than
    squinting at.
    """
    from perfboard_studio.footprints import standard_footprints
    from perfboard_studio.model import ComponentInstance
    from perfboard_studio.ui import view3d

    board = _load_dense().board
    lookup = footprint_lookup()
    one_per: dict[str, str] = {}
    for footprint_id, footprint in sorted(standard_footprints().items()):
        one_per.setdefault(footprint.body.archetype, footprint_id)

    for archetype, footprint_id in sorted(one_per.items()):
        comp = ComponentInstance(
            id="c1", ref="X1", value="", footprint_id=footprint_id, anchor=HoleCoord(6, 6)
        )
        body = view3d._world_body(lookup, comp, board)
        assert body is not None
        pieces = view3d._BUILDERS.get(archetype, view3d._box_pieces)(body)

        top = max(_piece_top(piece) for piece in pieces)

        assert top == pytest.approx(body.height + view3d._LIFT, abs=0.3), archetype


def _piece_top(piece) -> float:
    """The highest point one piece reaches, instanced or not."""
    from perfboard_studio.ui import view3d

    actor = view3d._actor_for(piece)
    actor.GetMapper().Update()
    if piece.instances:
        piece.source.Update() if hasattr(piece.source, "Update") else None
        data = piece.source.GetOutput() if hasattr(piece.source, "GetOutput") else piece.source
        return max(z for _x, _y, z in piece.instances) + data.GetBounds()[5]
    return float(actor.GetBounds()[5])


# ---------------------------------------------------------------------------
# The two views draw the same board
# ---------------------------------------------------------------------------
#
# "The 2D and the 3D board should look the same, and be right." They did not: a corner
# mounting hole was drawn on the grid in 2D and in the border in 3D, and the copper in 3D
# was clipped to a flat yellow that the 2D view never paints.


def test_a_mounting_hole_is_drawn_where_its_offset_puts_it_in_2d_too() -> None:
    """The offset is what lets a corner hole sit in the BORDER. view2d read the hole
    ADDRESS alone, so it drew every corner bore back on the grid -- a whole pad's width
    from where the 3D view and DRC both put it. CLAUDE.md has said not to do that since
    the feature was written."""
    from perfboard_studio.geometry import mounting_hole_centre_mm
    from perfboard_studio.model import MountingHole
    from perfboard_studio.ui.view2d import MountingHoleItem, mm_to_screen

    board = _load_dense().board
    mount = MountingHole(
        id="mh-1", at=HoleCoord(0, 0), offset_x_mm=-2.11, offset_y_mm=-2.11, diameter=2.2
    )

    for side in ("top", "bottom"):
        item = MountingHoleItem(mount, board, side)  # type: ignore[arg-type]
        centre = mounting_hole_centre_mm(mount, board)
        expected = mm_to_screen(centre.x, centre.y, board, side)  # type: ignore[arg-type]

        assert item._centre() == expected
        assert item._centre() != hole_to_screen(mount.at, board, side), "not the grid hole"


def test_a_bore_in_the_border_leaves_the_holes_beside_it_alone() -> None:
    """The patch of plate laid over a bore takes whole tiles, and the first version grew
    it OUT to tile edges -- so a corner hole sitting in the border swallowed the tile
    beside it, and the board came out with a blind hole next to every screw: pad drawn,
    no hole through it."""
    from perfboard_studio.geometry import consumed_holes
    from perfboard_studio.model import MountingHole
    from perfboard_studio.ui import view3d

    document = _load_dense()
    corner = MountingHole(
        id="mh-1", at=HoleCoord(0, 0), offset_x_mm=-2.11, offset_y_mm=-2.11, diameter=2.2
    )
    document = dataclasses.replace(document, mounting_holes=(corner,))

    assert consumed_holes(document) == frozenset(), "it eats no copper, so it eats no tile"
    assert view3d.patched_holes(document) == frozenset()


@requires_offscreen_gl
def test_the_board_s_copper_is_never_blown_out(tmp_path) -> None:
    """VTK's default specular POWER is 1.0, which is not a highlight: it adds the specular
    term flat across the whole surface. A pad carrying 0.4 of it rendered a fifth brighter
    than its own colour and clipped -- measured at (255, 255, 125) against the `#c8a951`
    the 2D view paints from the same table. Clipping does not just shift the hue, it
    flattens the shading off the metal, which is what made the 3D board a grid of flat
    yellow rings.
    """
    from PySide6.QtGui import QImage

    from perfboard_studio.ui import view3d

    out = tmp_path / "board.png"
    view3d.render_offscreen(_load_dense(), footprint_lookup(), str(out), width=700, height=500)
    image = QImage(str(out))
    assert not image.isNull()

    blown = 0
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.red() >= 254 and colour.green() >= 254 and colour.blue() < 200:
                blown += 1

    assert blown == 0, f"{blown} pixels of copper clipped to flat yellow"


# ---------------------------------------------------------------------------
# What a bore destroys, both views agree about
# ---------------------------------------------------------------------------
#
# A mounting hole drilled beside the edge strip left the finger it went through drawn
# intact, in both views: a 3.2 mm hole sitting on top of a contact the board no longer
# has. The legend had the matching hole in it -- ink printed where the substrate had been
# drilled away.


def _board_with_a_bore_through_a_finger():
    """A board whose corner bore is drilled through an edge-connector finger."""
    from perfboard_studio.commands import DEFAULT_BOARD, create_empty_document
    from perfboard_studio.geometry import (
        STANDARD_PRESETS,
        board_from_preset,
        preset_edge_connectors,
    )
    from perfboard_studio.model import DocumentMeta, MountingHole

    preset = next(p for p in STANDARD_PRESETS if p.cols == 34 and p.rows == 58 and not p.single_sided)
    board = board_from_preset(preset, DEFAULT_BOARD)
    document = create_empty_document(DocumentMeta(name="b", created="", modified=""), board)
    return dataclasses.replace(
        document,
        edge_connectors=preset_edge_connectors(preset, board),
        # One hole in from the corner, which is what Board Features offers by default, and
        # a 3.2 mm bore reaches the finger row from there.
        mounting_holes=(
            MountingHole(id="mh-1", at=HoleCoord(1, board.rows - 2), diameter=3.2, head_diameter=6.0),
        ),
    )


def test_a_bore_through_a_finger_takes_the_finger_with_it() -> None:
    """A bore does not distinguish between the two shapes of copper it destroys."""
    from perfboard_studio.geometry import (
        consumed_holes,
        edge_connector_holes,
        hole_key,
        surviving_finger_holes,
    )

    document = _board_with_a_bore_through_a_finger()
    connector = next(c for c in document.edge_connectors if c.edge == "bottom")

    all_fingers = edge_connector_holes(connector, document.board)
    left = surviving_finger_holes(document, connector)

    gone = [hole for hole in all_fingers if hole not in left]
    assert gone, "this bore is meant to reach the finger row"
    assert all(hole_key(hole) in consumed_holes(document) for hole in gone)
    assert len(left) == len(all_fingers) - len(gone)


def test_both_views_draw_the_same_surviving_fingers() -> None:
    """The 2D item and the 3D builder ask one function, so they cannot disagree about
    which contacts the board still has."""
    from perfboard_studio.geometry import surviving_finger_holes
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.view2d import BoardScene, EdgeConnectorItem

    document = _board_with_a_bore_through_a_finger()
    connector = next(c for c in document.edge_connectors if c.edge == "bottom")
    expected = surviving_finger_holes(document, connector)

    scene = BoardScene(document, footprint_lookup(), side="top")
    items = [item for item in scene.items() if isinstance(item, EdgeConnectorItem)]
    assert items, "the board has connectors"
    assert all(item.document is document for item in items), "the item asks the document"

    actors = view3d.build_edge_connectors(document)
    assert actors, "and 3D draws them too"
    assert expected, "with at least one finger left"


def test_no_letter_is_printed_where_a_bore_was_drilled() -> None:
    """Ink goes ON the substrate, and a mounting hole takes the substrate away -- so the
    label under one is not faint, it is absent, which is what a real board shows."""
    from perfboard_studio.geometry import printed_label_is_clear
    from perfboard_studio.model import MountingHole, Point2

    document = _load_dense()
    board = document.board
    where = Point2(4 * board.pitch, -1.2)  # a column letter's spot, above the first row
    assert printed_label_is_clear(document, where, board.pitch * 0.9, 1.0)

    drilled = dataclasses.replace(
        document,
        mounting_holes=(
            MountingHole(
                id="mh-1", at=HoleCoord(4, 0), offset_x_mm=0.0, offset_y_mm=-1.2, diameter=3.2
            ),
        ),
    )

    assert not printed_label_is_clear(drilled, where, board.pitch * 0.9, 1.0)
    # ...and a letter well away from it is untouched.
    assert printed_label_is_clear(drilled, Point2(12 * board.pitch, -1.2), board.pitch * 0.9, 1.0)


# ---------------------------------------------------------------------------
# Projects, and autosave that writes the file itself
# ---------------------------------------------------------------------------


def test_save_project_writes_the_board_and_the_generated_files_beside_it(tmp_path) -> None:
    """One gesture for the board and everything made from it. The generated half lands in
    outputs/ so a folder where half the files are yours and half are the tool's does not
    become a folder nobody dares tidy."""
    window = _window_on(_load_dense())
    window.current_path = tmp_path / "dense.perf"

    assert window.on_save_project()

    assert (tmp_path / "dense.perf").exists()
    outputs = tmp_path / "outputs"
    assert outputs.is_dir()
    names = {path.name for path in outputs.iterdir()}
    assert "dense-guide.html" in names
    assert "dense-bom.csv" in names
    _close(window)


def test_save_project_leaves_the_window_unmodified_and_in_the_recent_list(tmp_path) -> None:
    window = _window_on(_load_dense())
    window.current_path = tmp_path / "dense.perf"

    window.on_save_project()

    assert not window.is_modified
    assert str(tmp_path / "dense.perf") in window._recent_paths()
    _close(window)


def test_opening_a_folder_with_two_boards_in_it_is_refused(tmp_path, monkeypatch) -> None:
    """A project is a folder built around ONE board. Guessing which of two was meant is a
    guess that opens the wrong board on the day it matters."""
    (tmp_path / "one.perf").write_text("{}", encoding="utf-8")
    (tmp_path / "two.perf").write_text("{}", encoding="utf-8")
    window = _blank_window()
    monkeypatch.setattr(
        "perfboard_studio.ui.main.QFileDialog.getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(tmp_path)),
    )
    warned: list[str] = []
    monkeypatch.setattr(
        "perfboard_studio.ui.main.QMessageBox.warning",
        staticmethod(lambda *args, **kwargs: warned.append(args[1])),
    )

    window.on_open_project()

    assert warned
    assert window.current_path is None
    _close(window)


def test_opening_a_project_opens_the_board_inside_it(tmp_path, monkeypatch) -> None:
    board = tmp_path / "preamp.perf"
    board.write_text(GOLDEN.read_text(encoding='utf-8'), encoding="utf-8")
    (tmp_path / "outputs").mkdir()
    window = _blank_window()
    monkeypatch.setattr(
        "perfboard_studio.ui.main.QFileDialog.getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(tmp_path)),
    )

    window.on_open_project()

    assert window.current_path == board
    assert window.bus.document.components
    _close(window)


def test_autosave_writes_the_file_itself_and_keeps_the_last_real_save_as_bak(
    tmp_path,
) -> None:
    """The whole safety of writing over somebody's document without being told to.

    The backup holds what the user last chose to keep, not what autosave last happened to
    write -- so it is taken once per real save and not once per tick. Refreshing it every
    half minute would mean that half a minute after a mistake there was nothing left to go
    back to, which is the failure this exists to protect against.
    """
    path = tmp_path / "board.perf"
    window = _window_on(_load_dense())
    window.current_path = path
    assert window._save_to(path)
    saved = path.read_text(encoding="utf-8")

    window.bus.dispatch(
        "component.move",
        MoveComponentPayload(id=window.bus.document.components[0].id, anchor=HoleCoord(1, 1)),
    )
    window._on_autosave_tick()

    assert path.read_text(encoding="utf-8") != saved
    assert (tmp_path / "board.perf.bak").read_text(encoding="utf-8") == saved
    assert not window.is_modified

    # A second tick must not overwrite the backup with what autosave just wrote.
    window.bus.dispatch(
        "component.move",
        MoveComponentPayload(id=window.bus.document.components[1].id, anchor=HoleCoord(2, 2)),
    )
    window._on_autosave_tick()
    assert (tmp_path / "board.perf.bak").read_text(encoding="utf-8") == saved
    _close(window)


def test_autosave_writes_nothing_of_the_users_when_it_is_switched_off(tmp_path) -> None:
    path = tmp_path / "board.perf"
    window = _window_on(_load_dense())
    window.current_path = path
    window._save_to(path)
    saved = path.read_text(encoding="utf-8")
    window.on_autosave_to_file_toggled(False)

    window.bus.dispatch(
        "component.move",
        MoveComponentPayload(id=window.bus.document.components[0].id, anchor=HoleCoord(1, 1)),
    )
    window._on_autosave_tick()

    assert path.read_text(encoding="utf-8") == saved
    assert window.is_modified  # ...and the crash record is what protects it instead.
    _close(window)


def test_autosave_never_touches_a_board_that_has_no_file(tmp_path) -> None:
    """The board with the most to lose is the one that has never been saved, and it has
    nowhere to be written. That is the recovery record's job, and it keeps it."""
    window = _window_on(_load_dense())
    assert window.current_path is None

    window.bus.dispatch(
        "component.move",
        MoveComponentPayload(id=window.bus.document.components[0].id, anchor=HoleCoord(1, 1)),
    )
    window._on_autosave_tick()

    assert window.is_modified
    assert window._autosave.written
    _close(window)


def test_the_welcome_dialog_is_not_offered_over_a_board(tmp_path) -> None:
    """It is about what to do FIRST, and there is no first left once there is a board on
    the screen -- a document opened from the command line, or handed back by recovery."""
    window = _window_on(_load_dense())
    shown: list[int] = []
    monkeypatch_exec(window, shown)

    window.offer_welcome()

    assert shown == []
    _close(window)


def monkeypatch_exec(window, shown: list[int]) -> None:
    """Count the times a welcome dialog would have been shown, without showing one."""
    import perfboard_studio.ui.main as main_module

    class _Counted(main_module.WelcomeDialog):
        def exec(self) -> int:
            shown.append(1)
            return 0

    main_module.WelcomeDialog = _Counted  # type: ignore[misc]


def test_a_project_name_becomes_the_folder_and_the_document(tmp_path, monkeypatch) -> None:
    """New Project makes the directory, saves the board into it immediately and starts in
    the schematic. A board with a home has somewhere to autosave to and something to put
    in the recent list; an untitled one has neither until it is saved."""
    window = _blank_window()
    monkeypatch.setattr(
        "perfboard_studio.ui.main.QInputDialog.getText",
        staticmethod(lambda *args, **kwargs: ("NE555 Astable", True)),
    )
    monkeypatch.setattr(
        "perfboard_studio.ui.main.QFileDialog.getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(tmp_path)),
    )
    import perfboard_studio.ui.main as main_module

    monkeypatch.setattr(
        "perfboard_studio.ui.main.BoardSetupDialog.exec",
        lambda self: int(main_module.QDialog.DialogCode.Accepted),
    )

    window.on_new_project()

    folder = tmp_path / "ne555-astable"
    assert (folder / "ne555-astable.perf").is_file()
    assert window.current_path == folder / "ne555-astable.perf"
    assert not window.is_modified
    assert window.schematic_is_showing()
    _close(window)


# ---------------------------------------------------------------------------
# What a part says about itself
# ---------------------------------------------------------------------------


def test_the_pinout_editor_shows_and_returns_a_declaration() -> None:
    """A row per footprint pin, the declared names in them, and back out in normal form."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.main import PinoutEditor

    editor = PinoutEditor()
    editor.set_part(get_footprint("to220"), (("1", "G"), ("2", "D"), ("3", "S")), "pmos")
    assert editor.table.rowCount() == 3
    assert editor.values() == ((("1", "G"), ("2", "D"), ("3", "S")), "pmos")
    editor.deleteLater()


def test_the_pinout_editor_keeps_typed_names_across_a_footprint_change() -> None:
    """Pin 3 survives a footprint that still has a pin 3; pin 5 does not survive one that
    has three pins, rather than being kept where nothing shows it."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.main import PinoutEditor

    editor = PinoutEditor()
    editor.set_part(get_footprint("dip-8"), (("3", "VCC"), ("5", "Vref")), None)
    editor.set_footprint(get_footprint("to92"))
    assert editor.values() == ((("3", "VCC"),), None)
    editor.deleteLater()


def test_a_registry_pin_name_is_a_hint_not_a_declaration() -> None:
    """An LED's A and K are the footprint's; leaving them untouched declares nothing, so
    nothing is written to the part and nothing changes in the file."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.main import PinoutEditor

    editor = PinoutEditor()
    editor.set_part(get_footprint("led-5mm"), (), None)
    assert editor.values() == ((), None)
    editor.deleteLater()


def test_properties_writes_a_declaration_in_the_same_undo_step(monkeypatch) -> None:
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    before = len(window.bus.history())
    monkeypatch.setattr(
        main_module.ComponentDialog, "exec", lambda self: main_module.QDialog.DialogCode.Accepted
    )
    monkeypatch.setattr(
        main_module.ComponentDialog, "values", lambda self: (component.ref, "BC547", False)
    )
    monkeypatch.setattr(
        main_module.ComponentDialog,
        "pinout",
        lambda self: ((("1", "C"), ("2", "B"), ("3", "E")), "npn"),
    )
    window.on_component_properties(component.id)

    edited = next(c for c in window.bus.document.components if c.id == component.id)
    assert edited.value == "BC547"
    assert (edited.pin_names, edited.symbol) == ((("1", "C"), ("2", "B"), ("3", "E")), "npn")
    assert len(window.bus.history()) == before + 1
    _close(window)


# ---------------------------------------------------------------------------
# The board's name
# ---------------------------------------------------------------------------


def test_saving_an_unnamed_board_names_it_after_its_file(tmp_path) -> None:
    from perfboard_studio.model import UNTITLED_NAME

    window = _window_on(dataclasses.replace(
        _load_dense(),
        meta=dataclasses.replace(_load_dense().meta, name=UNTITLED_NAME),
    ))
    target = tmp_path / "logic-rail.perf"
    assert window._save_to(target)
    assert window.bus.document.meta.name == "logic-rail"
    assert '"name": "logic-rail"' in target.read_text(encoding="utf-8")
    # Saved means saved: the rename happened before the write, not after it.
    assert not window.is_modified
    _close(window)


def test_a_named_board_is_not_renamed_by_saving(tmp_path) -> None:
    window = _window_on(_load_dense())
    before = window.bus.document.meta.name
    assert before != "untitled"
    assert window._save_to(tmp_path / "elsewhere.perf")
    assert window.bus.document.meta.name == before
    _close(window)


def test_rename_board_asks_and_renames_in_one_undo_step(monkeypatch) -> None:
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    before = len(window.bus.history())
    monkeypatch.setattr(
        main_module.QInputDialog, "getText", lambda *args, **kwargs: ("Plaket v1", True)
    )
    window.on_rename_board()
    assert window.bus.document.meta.name == "Plaket v1"
    assert len(window.bus.history()) == before + 1
    # Cancelled, or unchanged: nothing on the undo stack.
    monkeypatch.setattr(
        main_module.QInputDialog, "getText", lambda *args, **kwargs: ("Plaket v1", True)
    )
    window.on_rename_board()
    assert len(window.bus.history()) == before + 1
    _close(window)


# ---------------------------------------------------------------------------
# A body off its pins, and the IDC box header
# ---------------------------------------------------------------------------


def test_the_custom_part_dialog_writes_a_body_offset_and_an_idc_header() -> None:
    """Both through the engine's own generators, and both read back by the lookup."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.main import CustomPartDialog

    dialog = CustomPartDialog()
    rect = next(
        i for i in range(dialog.family.count()) if dialog.family.itemText(i) == "Any rectangular part"
    )
    dialog.family.setCurrentIndex(rect)
    for key, value in (("cols", 6), ("rows", 1), ("width", 16), ("depth", 14.5), ("height", 7)):
        dialog._widgets[key].setValue(value)
    assert dialog.chosen() is not None and "-o" not in dialog.chosen().id
    dialog._widgets["offset_y"].setValue(6)
    assert dialog.identifier.text() == "box-6x1-p1-r1-16x14.5x7-o0x6"
    assert get_footprint(dialog.identifier.text()) == dialog.chosen()

    idc = next(i for i in range(dialog.family.count()) if "IDC" in dialog.family.itemText(i))
    dialog.family.setCurrentIndex(idc)
    assert dialog.identifier.text() == "idc-2x8"
    dialog.deleteLater()


def _idc_body(rotation: int):
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.model import ComponentInstance
    from perfboard_studio.ui import view3d

    comp = ComponentInstance(
        id="c1", ref="J1", value="", footprint_id="idc-2x8", anchor=HoleCoord(8, 8),
        rotation=rotation,
    )
    body = view3d._world_body(footprint_lookup(), comp, _load_dense().board)
    assert body is not None
    return body


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_a_box_header_has_its_key_slot_in_the_wall_beside_pin_1(rotation: int) -> None:
    """The slot is the part: the wall on the pin-1 row is two pieces with a gap, the other
    three walls are whole -- and it stays on pin 1's side however the part is turned."""
    from perfboard_studio.ui import view3d

    body = _idc_body(rotation)
    pieces = view3d._box_header_pieces(body)
    walls = [p for p in pieces if not p.instances and p.position[2] > 2.0]
    assert len(walls) == 5  # three whole walls and the keyed one in two
    pin1, pin2 = body.pins[0], body.pins[1]
    towards = (pin1[0] - pin2[0], pin1[1] - pin2[1])
    keyed = [
        wall for wall in walls
        if (wall.position[0] - body.x) * towards[0] + (wall.position[1] - body.y) * towards[1] > 1.0
    ]
    assert len(keyed) == 2


def test_a_box_header_stands_as_tall_as_its_footprint_with_a_lead_per_pin() -> None:
    from perfboard_studio.ui import view3d

    body = _idc_body(0)
    pieces = view3d._box_header_pieces(body)
    top = max(_piece_top(piece) for piece in pieces)
    assert top == pytest.approx(body.height + view3d._LIFT, abs=0.3)
    leads = [p for p in pieces if p.instances and p.rgb == view3d.LEAD_RGB]
    assert len(leads) == 1 and len(leads[0].instances) == len(body.pins) == 16


def test_a_board_with_an_offset_module_and_a_box_header_draws() -> None:
    """Both on the board, drawn from the same lookup: 2D items with their pads under them,
    and the 3D scene builds without a builder falling back to a plain box."""
    import dataclasses

    from perfboard_studio.model import ComponentInstance

    document = dataclasses.replace(
        _custom_document(),
        components=(
            ComponentInstance(
                id="c1", ref="U1", value="SN65HVD230",
                footprint_id="box-6x1-p1-r1-16x14.5x7-o0x6", anchor=HoleCoord(col=3, row=3),
            ),
            ComponentInstance(
                id="c2", ref="J1", value="CN12", footprint_id="idc-2x8",
                anchor=HoleCoord(col=10, row=14),
            ),
        ),
    )
    window = _window_on(document)
    try:
        drawn = sorted(
            (item.comp.ref, len(item.fp.pins))
            for item in window.scene.items()
            if isinstance(item, ComponentItem)
        )
        assert drawn == [("J1", 16), ("U1", 6)]
    finally:
        _close(window)


# ---------------------------------------------------------------------------
# The catalog in the Parts panel, the module wizard, and pin names on the board
# ---------------------------------------------------------------------------


def _catalog_leaf(window, catalog_id: str):
    from perfboard_studio.ui.main import ROLE_CATALOG_ID

    tree = window.library_tree
    for index in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(index)
        for child in range(group.childCount()):
            leaf = group.child(child)
            if leaf.data(0, ROLE_CATALOG_ID) == catalog_id:
                return leaf
    return None


def test_the_parts_panel_lists_real_parts_and_places_them_described() -> None:
    """Picking BC547 places a BC547: value, pin names, symbol, and a Q reference -- the
    whole of what the catalog says, through the same arming a package uses."""
    window = _blank_window()
    try:
        leaf = _catalog_leaf(window, "bc547")
        assert leaf is not None
        window.library_tree.setCurrentItem(leaf)
        assert window.library_value.text() == "BC547"
        result = window.scene.place_armed(HoleCoord(4, 4))
        assert result is not None and result.ok
        (part,) = window.bus.document.components
        assert (part.ref, part.value, part.footprint_id, part.symbol) == (
            "Q1", "BC547", "to92", "npn"
        )
        assert dict(part.pin_names) == {"1": "C", "2": "B", "3": "E"}

        # A 7805 is a TO-220 and it is not a transistor.
        window.library_tree.setCurrentItem(_catalog_leaf(window, "7805"))
        window.scene.place_armed(HoleCoord(10, 4))
        assert window.bus.document.components[-1].ref == "U1"
    finally:
        _close(window)


def test_a_bare_package_picked_after_a_catalog_part_is_a_bare_package() -> None:
    """The catalog's value, names and symbol go back out -- a TO-92 picked after a BC547 is
    not quietly a BC547 -- but a value the user typed stays, as it always has."""
    from perfboard_studio.ui.main import ROLE_CATALOG_ID, ROLE_FOOTPRINT_ID

    window = _blank_window()
    try:
        window.library_tree.setCurrentItem(_catalog_leaf(window, "bc547"))
        tree = window.library_tree
        bare = None
        for index in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(index)
            for child in range(group.childCount()):
                leaf = group.child(child)
                if leaf.data(0, ROLE_FOOTPRINT_ID) == "to92" and not leaf.data(0, ROLE_CATALOG_ID):
                    bare = leaf
        assert bare is not None
        tree.setCurrentItem(bare)
        assert window.library_value.text() == ""
        assert window.scene.placement_pin_names == () and window.scene.placement_symbol is None
        window.scene.place_armed(HoleCoord(4, 4))
        (part,) = window.bus.document.components
        assert (part.value, part.pin_names, part.symbol) == ("", (), None)

        window.library_value.setText("2N3904")
        tree.setCurrentItem(_catalog_leaf(window, "bc557"))
        tree.setCurrentItem(bare)
        assert window.library_value.text() == ""  # the catalog's BC557 went back out
        window.library_value.setText("mine")
        tree.setCurrentItem(bare)
        assert window.library_value.text() == "mine"
    finally:
        _close(window)


def test_the_filter_finds_a_part_by_what_it_is() -> None:
    window = _blank_window()
    try:
        window.library_filter.setText("p-channel")
        assert _catalog_leaf(window, "irf9540n") is not None
        assert _catalog_leaf(window, "bc547") is None
    finally:
        _close(window)


def test_the_module_wizard_describes_a_module_and_its_pin_names() -> None:
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.main import CustomPartDialog

    dialog = CustomPartDialog()
    module = next(
        i for i in range(dialog.family.count()) if "Module" in dialog.family.itemText(i)
    )
    dialog.family.setCurrentIndex(module)
    assert dialog.pin_names_edit.isVisibleTo(dialog)
    for key, value in (("cols", 1), ("rows", 6), ("width", 16), ("depth", 14.5), ("top", 3)):
        dialog._widgets[key].setValue(value)
    dialog._widgets["offset_x"].setValue(6)
    footprint = dialog.chosen()
    assert footprint is not None
    assert footprint.id == "mod-1x6-p1-r1-16x14.5x3-s8.5-o6x0"
    assert get_footprint(footprint.id) == footprint

    dialog.pin_names_edit.setPlainText("3V3 GND CTX CRX")
    assert "4 name(s) for 6 pin(s)" in dialog.summary.text()
    dialog.pin_names_edit.setPlainText("3V3, GND, CTX, CRX, CAN H, CAN L")
    assert dict(dialog.chosen_pin_names()) == {
        "1": "3V3", "2": "GND", "3": "CTX", "4": "CRX", "5": "CAN H", "6": "CAN L",
    }

    dialog._widgets["socketed"].setChecked(False)
    assert dialog.chosen() is not None and dialog.chosen().id.endswith("-s2.5-o6x0")

    other = next(i for i in range(dialog.family.count()) if "DIP" in dialog.family.itemText(i))
    dialog.family.setCurrentIndex(other)
    assert not dialog.pin_names_edit.isVisibleTo(dialog)
    assert dialog.chosen_pin_names() == ()
    dialog.deleteLater()


def test_pin_names_can_be_turned_off_on_the_board() -> None:
    window = _blank_window()
    try:
        window.library_tree.setCurrentItem(_catalog_leaf(window, "ne555"))
        window.scene.place_armed(HoleCoord(6, 6))
        drawn = [item for item in window.scene.items() if isinstance(item, ComponentItem)]
        assert drawn and all(item.show_pin_names for item in drawn)
        window.act_pin_names.setChecked(False)
        drawn = [item for item in window.scene.items() if isinstance(item, ComponentItem)]
        assert drawn and not any(item.show_pin_names for item in drawn)
    finally:
        _close(window)


def test_a_board_with_pin_names_draws_them() -> None:
    """Rendered, not just built: the names are painted at 0.9 mm, and a board with them
    has ink beside the NE555 that a board without them does not."""
    from perfboard_studio.mcp.session import BoardSession, new_board

    with_names = BoardSession(document=new_board(cols=20, rows=12))
    with_names.place_component("", "", "H4", part="ne555")
    without = BoardSession(document=new_board(cols=20, rows=12))
    without.place_component("U1", "dip-8", "H4")
    named, _ = with_names.render_2d(px_per_mm=12)
    plain, _ = without.render_2d(px_per_mm=12)
    assert named != plain


# ---------------------------------------------------------------------------
# Labels written on the board
# ---------------------------------------------------------------------------


def _label_items(window):
    from perfboard_studio.ui.view2d import BoardNoteItem

    return [item for item in window.scene.items() if isinstance(item, BoardNoteItem)]


def test_a_label_is_written_where_it_is_asked_for_and_can_be_hidden() -> None:
    window = _blank_window()
    try:
        pitch = window.bus.document.board.pitch
        result = window.add_board_label("MOTOR 24V", QPointF(3 * pitch + 0.5, 5 * pitch))
        assert result.ok
        (note,) = window.bus.document.board_notes
        assert (note.at, note.offset_x_mm, note.offset_y_mm) == (HoleCoord(3, 5), 0.5, 0.0)
        assert len(_label_items(window)) == 1
        window.act_board_labels.setChecked(False)
        assert _label_items(window) == []
        window.act_board_labels.setChecked(True)
        assert len(_label_items(window)) == 1
    finally:
        _close(window)


def test_a_dragged_label_lands_where_it_was_dropped() -> None:
    window = _blank_window()
    try:
        pitch = window.bus.document.board.pitch
        window.add_board_label("CAN", QPointF(2 * pitch, 2 * pitch))
        (item,) = _label_items(window)
        item.setPos(QPointF(6 * pitch + 1.0, 4 * pitch - 0.5))
        results = window.scene.commit_pending_moves()
        assert results and all(r.ok for r in results)
        (note,) = window.bus.document.board_notes
        assert (note.at, note.offset_x_mm, note.offset_y_mm) == (HoleCoord(6, 4), 1.0, -0.5)
    finally:
        _close(window)


def test_delete_takes_a_label_without_asking() -> None:
    """Words, and Undo brings them back -- no question in the way."""
    window = _blank_window()
    try:
        window.add_board_label("X", QPointF(10.0, 10.0))
        (item,) = _label_items(window)
        item.setSelected(True)
        assert window.act_delete.isEnabled()
        window.on_delete_selection()
        assert window.bus.document.board_notes == ()
        window.bus.undo()
        assert len(window.bus.document.board_notes) == 1
    finally:
        _close(window)


def test_the_right_click_menu_knows_a_label() -> None:
    window = _blank_window()
    try:
        window.add_board_label("GND", QPointF(10.0, 10.0))
        on_label = window.view.mapFromScene(QPointF(10.0, 10.0))
        texts = [action.text() for action in window.board_menu(on_label).actions()]
        assert "Edit Label…" in texts
        window.scene.clearSelection()
        bare = window.view.mapFromScene(QPointF(40.0, 40.0))
        texts = [action.text() for action in window.board_menu(bare).actions()]
        assert "Add Label Here…" in texts
    finally:
        _close(window)


def test_a_label_on_the_solder_side_is_seen_from_the_solder_side() -> None:
    window = _blank_window()
    try:
        window.add_board_label("ALT", QPointF(10.0, 10.0), side="bottom")
        assert _label_items(window) == []
        window.scene.set_side("bottom")
        assert len(_label_items(window)) == 1
    finally:
        _close(window)
