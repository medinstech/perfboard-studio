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
import itertools
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
from perfboard_studio.geometry import column_label, format_hole
from perfboard_studio.model import (
    Board,
    ComponentInstance,
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


def test_no_colour_is_spelled_as_an_eight_digit_string() -> None:
    """Qt reads "#rrggbbaa" as #AARRGGBB, so "#000000b4" is a fully transparent blue: the
    terminal openings were first drawn invisible that way, and a header's pin outline,
    "#00000060", stayed invisible until this looked. Give the alpha to QColor(r, g, b, a)."""
    import re

    ui = pathlib.Path(view2d.__file__).resolve().parent
    trap = re.compile(r"QColor\(\s*[\"']#[0-9A-Fa-f]{8}[\"']")
    found = [
        f"{path.name}:{number}"
        for path in sorted(ui.glob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if trap.search(line)
    ]
    assert found == []


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
    # ...ending in the tone curve that keeps bare metal from clipping to a white slab, with
    # the occlusion under it.
    chain = renderer.GetPass()
    assert isinstance(chain, vtk.vtkToneMappingPass)
    assert chain.GetToneMappingType() == vtk.vtkToneMappingPass.Exponential
    assert isinstance(chain.GetDelegatePass(), vtk.vtkSSAOPass)


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


def test_a_part_off_the_board_is_drawn_as_its_wires_leaving_over_the_nearest_edge() -> None:
    """No body -- the part is on the panel -- and both views draw the same wires:
    ``geometry.flying_lead_routes``, from the pads over the nearest edge and past it. In 2D
    the item's bounds must hold the wires too, or a drag leaves them smeared behind it."""
    from perfboard_studio.geometry import flying_lead_routes, substrate_edges_mm
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.view2d import FLYING_LEAD_PAST_EDGE_MM, ComponentItem

    document = _one_part_board("wire-3", ref="RV1", col=10, row=0)
    component = document.components[0]
    footprint = footprint_lookup()("wire-3")
    assert footprint is not None
    top_edge = substrate_edges_mm(document.board).min_y

    item = ComponentItem(component, footprint, document.board, "top")
    routes = item._flying_lead_routes()
    assert len(routes) == 3
    origin = item.pos()
    for _number, points in routes:
        # Straight up and past the top edge, by as much as the scene's margin can show.
        assert all(point.x() == pytest.approx(points[0].x()) for point in points)
        assert points[-1].y() + origin.y() == pytest.approx(top_edge - FLYING_LEAD_PAST_EDGE_MM)
        assert all(item.boundingRect().contains(point) for point in points)
    # The solder side shows the pads and nothing leaving them: the wires are on the far face.
    assert ComponentItem(component, footprint, document.board, "bottom")._flying_lead_routes() == []

    # 3D lays the same wire: its plan is the 2D route, only longer past the edge.
    body = view3d._world_body(footprint_lookup(), component, document.board)
    assert body is not None
    plan = dict(flying_lead_routes(component, footprint, document.board, 0.0))
    for number, path in view3d._flying_lead_paths(body, footprint, component, document.board):
        assert (path[2][0], -path[2][1]) == pytest.approx((plan[number][-1].x, plan[number][-1].y))

    black = (0.1, 0.1, 0.1)
    actors = view3d.build_component(
        footprint_lookup(), component, document.board, {"1": black}
    )
    assert max(actor.GetBounds()[3] for actor in actors) > -top_edge + 5
    # The colour reaches the shader as albedo, not as the sRGB it was picked in.
    wanted = tuple(view3d._to_linear(c) for c in black)
    assert any(actor.GetProperty().GetColor() == pytest.approx(wanted) for actor in actors)


def test_a_wire_to_a_part_off_the_board_says_where_it_goes() -> None:
    """In both views each wire carries its marker -- "RV1·2" -- at the same place past the
    edge, and the 2D tooltip lists every wire as the guide's step does: pad, the lead at the
    other end, its net and the colour it is cut in."""
    from PySide6.QtCore import QPointF

    from perfboard_studio.command import CommandBus, CommandContext
    from perfboard_studio.commands import (
        AddNetPayload,
        create_document_id_generator,
        create_standard_registry,
    )
    from perfboard_studio.geometry import FLYING_LEAD_MARKER_MM, substrate_edges_mm
    from perfboard_studio.model import NetNode
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.view2d import BoardScene

    document = _one_part_board("wire-3", ref="RV1", col=10, row=0)
    component = document.components[0]
    bus = CommandBus(
        document,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(document)),
    )
    assert bus.dispatch(
        "net.add",
        AddNetPayload(
            name="GND", net_class="ground", nodes=(NetNode(component_ref="RV1", pin="1"),)
        ),
    ).ok
    document = bus.document

    scene = BoardScene(document, footprint_lookup(), side="top")
    item = scene.component_items[component.id]
    markers = item._lead_markers()
    assert [marker[0] for marker in markers] == ["RV1·1", "RV1·2", "RV1·3"]
    top = substrate_edges_mm(document.board).min_y
    for _text, centre, across, _direction in markers:
        assert not across  # the wires run up the screen, so the text does too
        assert (centre + item.pos()).y() == pytest.approx(top - FLYING_LEAD_MARKER_MM)
    tip = item.toolTip()
    assert "K1 → RV1 pin 1 · GND · black" in tip
    assert "L1 → RV1 pin 2" in tip
    assert isinstance(markers[0][1], QPointF)

    # 3D: a sleeve per wire and, with Qt to draw it, its print on top.
    actors = view3d.build_component(footprint_lookup(), component, document.board)
    sleeves = [
        actor
        for actor in actors
        if actor.GetProperty().GetColor()
        == pytest.approx(tuple(view3d._to_linear(c) for c in view3d.FLYING_LEAD_MARKER_RGB))
    ]
    printed = [actor for actor in actors if actor.GetTexture() is not None]
    assert len(sleeves) == 3 and len(printed) == 3


def test_wires_in_line_with_their_edge_are_laid_side_by_side() -> None:
    """A row of pads pointing at the edge it leaves over: seen from above, every wire would
    lie on the ones nearer the edge. Each steps into its own lane instead, more than a
    jacket's width from the next, in 2D and 3D alike."""
    from perfboard_studio.ui import view3d

    document = _one_part_board("wire-3", ref="J1", col=0, row=10)
    component = document.components[0]
    footprint = footprint_lookup()("wire-3")
    assert footprint is not None
    body = view3d._world_body(footprint_lookup(), component, document.board)
    assert body is not None
    paths = dict(view3d._flying_lead_paths(body, footprint, component, document.board))
    # Leaving over the left edge, each wire's run along the board is at its own height on
    # the board -- its lane -- and the lanes are further apart than two jackets are wide.
    lanes = sorted(paths[number][-2][1] for number in ("1", "2", "3"))
    assert all(b - a > 2 * view3d.INSULATED_RADIUS_MM for a, b in itertools.pairwise(lanes))


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
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui import partmodels

    # Checked on every model rather than on one, because the claim is about the CONVENTION:
    # pin 1 at the origin, the package running +x with the column and -y against the row.
    # A model that broke it would be offset by its own length and nothing else would say so.
    # A package whose pin 1 is outside it on purpose: the 5 mm RGB LED stands over four holes
    # 7.62 mm across, its legs fanned out under it to the board's pitch and not drawn
    # (``Model.leads``). Its origin is still pin 1, so the middle of its pins is inside it --
    # placed by its centre, it would be 3.8 mm off them.
    pin_one_outside = {"led-5mm-rgb"}
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
        on_pin_one = low_x <= 0.5 <= high_x and low_y <= 0.5 and high_y >= -0.5
        if footprint_id in pin_one_outside:
            footprint = get_footprint(footprint_id)
            assert footprint is not None
            middle_x = sum(pin.d_col for pin in footprint.pins) / len(footprint.pins) * 2.54
            middle_y = -sum(pin.d_row for pin in footprint.pins) / len(footprint.pins) * 2.54
            on_its_pins = low_x <= middle_x <= high_x and low_y <= middle_y <= high_y
            if on_pin_one or not on_its_pins:
                wrong.append((footprint_id, [round(v, 2) for v in (low_x, low_y, high_x, high_y)]))
        elif not on_pin_one:
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
    size -- a footprint describes a package family at its largest and a model is one part in
    it, so bands printed at the footprint's size would stand off a 9 mm resistor's barrel
    (3.6 mm across where KiCad's DIN0309 is 3.2), and at a smaller one would vanish in it."""
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
            ref="R1", footprint_id="r-axial-6", value="10k", anchor=HoleCoord(4, 4)
        ),
    ).ok
    component = bus.document.components[0]

    body = view3d._world_body(footprint_lookup(), component, DEFAULT_BOARD)
    assert body is not None and body.bands
    model = partmodels.model_for("r-axial-6")
    assert model is not None
    barrel = view3d._barrel_of(model)
    assert barrel is not None
    radius, _z, _along = barrel

    # The bands have to be printed ON the barrel they are printed on: just outside it, and
    # inside the footprint's larger one.
    assert radius < body.across / 2, "the borrowed barrel is not the footprint's"
    marks = view3d._axial_markings(body, barrel)
    assert len(marks) == len(body.bands)
    for mark in marks:
        assert radius < mark.source.GetRadius() < body.across / 2


def _placed(footprint_id: str) -> ComponentInstance:
    """One part at D5, on the default board."""
    return ComponentInstance(
        id="c1",
        ref="X1",
        value="",
        footprint_id=footprint_id,
        anchor=HoleCoord(4, 4),
        rotation=0,
        mirrored=False,
        locked=False,
    )


@pytest.mark.parametrize("footprint_id", ["d-do41", "d-do35"])
def test_a_borrowed_diode_has_one_cathode_band_in_the_colour_2d_draws(footprint_id: str) -> None:
    """The KiCad mesh already has its band, where the real part has it, and another was
    printed at the very end of the barrel: two bands, one of them in KiCad's colour."""
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.ui import partmodels, view3d

    lookup = footprint_lookup()
    component = _placed(footprint_id)
    body = view3d._world_body(lookup, component, DEFAULT_BOARD)
    footprint = lookup(footprint_id)
    model = partmodels.model_for(footprint_id)
    assert body is not None and footprint is not None and model is not None

    pieces = view3d._pieces_for(body, footprint, component, DEFAULT_BOARD)

    colours = [piece.rgb for piece in pieces]
    assert colours.count(view3d._rgb(body.style.accent)) == 1
    kicad_band = next(p.color for p in model.pieces if view3d._is_marking(p))
    assert view3d._rgb(kicad_band) not in colours


def test_an_electrolytics_stripe_is_printed_in_the_colour_2d_draws_it_and_not_as_metal() -> None:
    """KiCad's minus stripe was taken for the aluminium top and shaded as dull khaki steel.
    It is print on the sleeve: sleeve material, the style's accent -- and the minus signs
    KiCad draws down it keep their own colour, or painting the stripe would erase them."""
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.ui import partmodels, view3d

    lookup = footprint_lookup()
    component = _placed("c-elec-d8-p3")
    body = view3d._world_body(lookup, component, DEFAULT_BOARD)
    footprint = lookup("c-elec-d8-p3")
    model = partmodels.model_for("c-elec-d8-p3")
    assert body is not None and footprint is not None and model is not None

    stripe = view3d._polarity_mark(model)
    assert stripe is not None and stripe.material == "sleeve"
    pieces = view3d._pieces_for(body, footprint, component, DEFAULT_BOARD)

    colours = [piece.rgb for piece in pieces]
    accent = view3d._rgb(body.style.accent)
    # The level faces the 2D's mark lands on are painted in the accent too, from above
    # (``_painted_from_above``): the sleeve's shoulder and the stripe's own top. Of the
    # pieces that are whole parts of the model, the stripe is the one in the accent.
    from_above = {id(painted) for painted, _rest in view3d._FROM_ABOVE.values() if painted is not None}
    whole = [piece for piece in pieces if id(piece.source) not in from_above]
    assert [piece.rgb for piece in whole].count(accent) == 1
    assert all(piece.material == view3d.SLEEVE for piece in pieces if piece.rgb == accent)
    signs = [p for p in model.pieces if view3d._is_marking(p) and p is not stripe]
    assert signs and all(view3d._rgb(p.color) in colours for p in signs)


def test_a_header_pin_goes_through_the_board() -> None:
    """Every other part shows its leads trimmed on the solder side; a header's borrowed pin
    is cut at the board surface, and nothing drew the rest of it."""
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.ui import view3d

    lookup = footprint_lookup()
    component = _placed("hdr-1x8")
    body = view3d._world_body(lookup, component, DEFAULT_BOARD)
    footprint = lookup("hdr-1x8")
    assert body is not None and footprint is not None

    pieces = view3d._pieces_for(body, footprint, component, DEFAULT_BOARD)

    below = [
        piece
        for piece in pieces
        if len(piece.instances) == 8 and all(z < 0 for _x, _y, z in piece.instances)
    ]
    assert below, "no pin continues below the board's top face"


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


@requires_offscreen_gl
@pytest.mark.parametrize(
    ("board", "size"),
    [
        ("examples/atmega328-relay.perf", (1400, 950)),  # portrait board, landscape window
        ("tools/diffcheck/golden/dense.perf", (600, 900)),  # landscape board, tall panel
    ],
)
@pytest.mark.parametrize("flipped", [False, True])
def test_the_default_camera_keeps_the_whole_board_in_the_frame(
    board: str, size: tuple[int, int], flipped: bool
) -> None:
    """It used to fit a bounding sphere, zoom in by a fixed 1.35 and then tilt, in a window
    it had not been given yet: every portrait board lost its near edge off the bottom of the
    frame (atmega328-relay's corners landed at y -87..914 in 950 px), and its far edge off
    the top when flipped. Measured by projecting the substrate's four corners."""
    import vtk

    from perfboard_studio.geometry import board_outline_mm
    from perfboard_studio.ui import view3d

    root = pathlib.Path(__file__).resolve().parents[1]
    document = persist.parse_document_or_throw((root / board).read_text(encoding="utf-8"))
    renderer, _stats = view3d.build_renderer(document, footprint_lookup(), flipped=flipped)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.AddRenderer(renderer)
    window.SetSize(*size)
    view3d.apply_default_camera(renderer, flipped)
    window.Render()

    outline = board_outline_mm(document.board)
    point = vtk.vtkCoordinate()
    point.SetCoordinateSystemToWorld()
    xs: list[float] = []
    ys: list[float] = []
    for x in (outline.x, outline.x + outline.width):
        for y in (-outline.y, -(outline.y + outline.height)):
            point.SetValue(x, y, 0.0)
            px, py = point.GetComputedDoubleDisplayValue(renderer)
            xs.append(px)
            ys.append(py)
    window.Finalize()

    width, height = size
    assert min(xs) >= 0 and max(xs) <= width, (xs, size)
    assert min(ys) >= 0 and max(ys) <= height, (ys, size)
    # ...and not fitted by making it tiny: it fills most of whichever side limits it.
    assert max((max(xs) - min(xs)) / width, (max(ys) - min(ys)) / height) > 0.6


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


def test_each_field_in_properties_is_one_undo_step() -> None:
    """No OK: every field is the fact, committed as one command when it is left."""
    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    before = len(window.bus.history())
    editor = _inspect(window, component.id)

    _type_into(editor.ref, "RENAMED")
    _type_into(editor.value, "4k7")
    editor.locked.setChecked(True)

    edited = next(c for c in window.bus.document.components if c.id == component.id)
    assert (edited.ref, edited.value, edited.locked) == ("RENAMED", "4k7", True)
    assert len(window.bus.history()) == before + 3
    # Read back from the document, and still the same part's editor.
    assert window.inspector.shown is editor and editor.ref.text() == "RENAMED"
    _close(window)


def _inspect(window, component_id: str):
    """Select one part on the board and hand back the inspector's part editor."""
    window.scene.select_components([component_id])
    window._refresh_properties()
    editor = window.inspector.part_editor
    assert window.inspector.shown is editor
    return editor


def _type_into(field, text: str) -> None:
    """What typing ``text`` and pressing Enter does to a CommitLine."""
    field.setText(text)
    field.setModified(True)
    field.editingFinished.emit()


def test_properties_that_changed_nothing_writes_no_history() -> None:
    """An undo entry for a field somebody entered and left is an undo entry that lies."""
    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    before = len(window.bus.history())
    editor = _inspect(window, component.id)

    _type_into(editor.ref, component.ref)
    _type_into(editor.value, f"  {component.value} ")
    editor.note.setFocus()
    editor._commit_note()

    assert len(window.bus.history()) == before
    _close(window)


def test_a_duplicate_reference_is_refused_and_said_out_loud(monkeypatch) -> None:
    """Under the field, in words, naming the reference -- never a message box, and the
    typed reference stays in the field to be put right; Esc puts the part's own back."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    first, second = window.bus.document.components[0], window.bus.document.components[1]
    boxes: list = []
    monkeypatch.setattr(main_module.QMessageBox, "warning", lambda *a, **k: boxes.append(a))
    editor = _inspect(window, first.id)

    _type_into(editor.ref, second.ref)

    assert [c.ref for c in window.bus.document.components][:2] == [first.ref, second.ref]
    said = editor.ref.problem.text()
    assert not editor.ref.problem.isHidden() and second.ref in said
    assert "duplicate-ref" not in said and boxes == []
    assert editor.ref.text() == second.ref
    window.properties.refresh(window.bus.document)  # an unrelated redraw keeps the typing
    assert editor.ref.text() == second.ref

    editor.ref.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert editor.ref.text() == first.ref and editor.ref.problem.isHidden()
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
    # The whole system, which is what the window asks about: with several boards the bus's
    # ``document`` is only the board in front, and a window closed on it waited forever.
    window._saved_document = window.bus.system_document
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

    monkeypatch.setattr(window, "_confirm_placement", lambda plan: False)
    window.on_autoplace()

    assert window.bus.document is before
    window.close()


def test_autoplace_commits_through_the_bus_as_one_undo_step(monkeypatch) -> None:
    window = _window_on(_load_dense())
    before = window.bus.document

    monkeypatch.setattr(window, "_confirm_placement", lambda plan: True)
    window.on_autoplace()

    assert window.bus.document is not before
    assert window.bus.document.components != before.components
    window.bus.undo()
    assert window.bus.document.components == before.components
    window.close()


def test_every_press_of_auto_place_searches_from_a_new_seed(monkeypatch) -> None:
    """Annealing is a random walk, so pressing it again has to actually try something else.
    It did not: the same seed on the same board is the same answer, so a second press ran
    for seconds and reported the placement the first had -- which reads as a button that
    has stopped working."""
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    monkeypatch.setattr(window, "_confirm_placement", lambda plan: False)
    seeds: list[int] = []
    real = main_module.plan_placement
    monkeypatch.setattr(
        main_module,
        "plan_placement",
        lambda doc, lookup, options, should_stop=None, mapper=None: (
            seeds.append(options.seed)
            or real(doc, lookup, options, should_stop=should_stop, mapper=mapper)
        ),
    )

    window.on_autoplace()
    window.on_autoplace()
    assert seeds == [0, 1]
    window.close()


def test_autoroute_on_a_finished_board_routes_it_again(monkeypatch) -> None:
    """Nothing left to ADD used to mean nothing happened -- so changing the connection
    style and pressing Autoroute did nothing at all. It plans the board's routing again
    with the settings as they are, asking first because it rips copper up; and when that
    comes out exactly as it is, it says so rather than asking to swap copper for itself."""
    from pathlib import Path

    from perfboard_studio.persist import deserialize_document

    doc = deserialize_document(
        (Path(__file__).resolve().parents[1] / "examples" / "lm317-supply.perf").read_text(
            encoding="utf-8"
        )
    ).document
    window = _window_on(doc)
    asked: list[str] = []
    monkeypatch.setattr(
        type(window), "_confirm", lambda self, title, body, verb: asked.append(body) or True
    )
    # The example is routed exactly as the window routes it by default, so the style has
    # to change for the answer to -- which is the case this test is about.
    window.on_routing_style("solder")

    window.on_autoroute_all()
    assert len(asked) == 1, "a board already routed is routed again, after asking"
    routed = window.bus.document.conductors

    window.on_autoroute_all()
    assert len(asked) == 1, "the same copper again is not a question"
    assert window.bus.document.conductors == routed
    assert "exactly as it is" in window.statusBar().currentMessage()

    window.on_routing_style("wire")
    window.on_autoroute_all()
    assert len(asked) == 2 and window.bus.document.conductors != routed
    _close(window)


def test_autoplace_on_an_empty_board_says_so_rather_than_running(monkeypatch) -> None:
    from perfboard_studio.commands import create_empty_document
    from perfboard_studio.model import DocumentMeta

    window = _window_on(
        create_empty_document(
            DocumentMeta(name="t", created="2024-01-01T00:00:00.000Z", modified="2024-01-01T00:00:00.000Z")
        )
    )
    called = []
    monkeypatch.setattr(window, "_confirm_placement", lambda plan: called.append(1) or True)

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
    monkeypatch.setattr(main_module.MainWindow, "_offer_to_open", lambda self, written, **kwargs: None)
    # The export asks where to write; this answers with what it suggests.
    monkeypatch.setattr(
        main_module.MainWindow,
        "_ask_where_to_export",
        lambda self, title, suggested, file_filter: tmp_path / suggested,
    )
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
    monkeypatch.setattr(main_module.MainWindow, "_offer_to_open", lambda self, written, **kwargs: None)
    # The export asks where to write; this answers with what it suggests.
    monkeypatch.setattr(
        main_module.MainWindow,
        "_ask_where_to_export",
        lambda self, title, suggested, file_filter: tmp_path / suggested,
    )
    window.on_export_guide()

    assert shown and "could not cover" in shown[0]
    window.close()


@requires_offscreen_gl  # the render is stubbed, but the scanner reads on_export_guide
def test_the_step_pictures_are_counted_and_can_be_skipped(tmp_path, monkeypatch) -> None:
    """They take about forty seconds on atmega328-relay and used to be a wait cursor and
    nothing else, which Windows calls "Not Responding". The render reports after every
    picture; skipping writes the guide without pictures rather than with some of them, and
    the window is handed back either way."""
    from PySide6.QtWidgets import QProgressDialog

    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui import view3d

    window = _window_on(_load_dense())
    window.current_path = tmp_path / "board.perf"
    monkeypatch.setattr(main_module.MainWindow, "PLANNER_GRACE_S", 0.0)
    monkeypatch.setattr(view3d, "offscreen_gl_available", lambda: True)
    monkeypatch.setattr(
        "perfboard_studio.ui.main.QMessageBox.warning", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(main_module.MainWindow, "_offer_to_open", lambda self, written, **kwargs: None)
    monkeypatch.setattr(
        main_module.MainWindow,
        "_ask_where_to_export",
        lambda self, title, suggested, file_filter: tmp_path / suggested,
    )
    seen: list[tuple[int, int]] = []
    guarded: list[bool] = []

    def fake_render(document, guide, lookup, *, progress):
        for done in (1, 2, 3):
            seen.append((done, 3))
            guarded.append(window._planner_running and not window.isEnabled())
            if done == 2:
                next(iter(window.findChildren(QProgressDialog))).cancel()
            if not progress(done, 3):
                return {}
        return {"never": b""}

    monkeypatch.setattr(view3d, "render_step_images", fake_render)

    window.on_export_guide()

    assert seen == [(1, 3), (2, 3)]
    assert all(guarded)
    html = (tmp_path / "board_guide.html").read_text(encoding="utf-8")
    assert "data:image/jpeg" not in html
    assert window.isEnabled() and not window._planner_running
    _close(window)


@requires_offscreen_gl  # cancelled before any render, but the scanner reads on_export_guide
def test_every_export_asks_where_and_suggests_what_it_used_to_write(tmp_path, monkeypatch) -> None:
    """They wrote fixed names beside the board without a word, overwriting what was there,
    behind menu items whose "…" promised a question. The suggestion is the old name, so
    accepting it does exactly what the menu always did; cancelling writes nothing."""
    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui import view3d

    window = _window_on(_load_dense())
    window.current_path = tmp_path / "board.perf"
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_module.MainWindow,
        "_ask_where_to_export",
        lambda self, title, suggested, file_filter: asked.append((suggested, file_filter)) or None,
    )
    monkeypatch.setattr(view3d, "offscreen_gl_available", lambda: True)

    window.on_export_pdf()
    window.on_export_3d_png()
    window.on_export_guide()
    window.on_export_schematic()
    window.on_export_step()

    assert [name for name, _filter in asked] == [
        "board_component_side.pdf",
        "board.png",
        "board_guide.html",
        "board_schematic.pdf",
        "board.step",
    ]
    assert list(tmp_path.iterdir()) == [], "a cancelled export wrote something"
    _close(window)


def test_the_step_model_is_written_where_asked_and_needs_no_gl(tmp_path, monkeypatch) -> None:
    """Nothing in it renders, so it is not behind the GL guard the snapshot is: a machine
    that cannot draw the 3D view can still hand the board to a CAD program. A name typed
    without an extension gets the one the filter promised."""
    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui import view3d

    window = _window_on(_golden_document("ne555"))
    monkeypatch.setattr(view3d, "offscreen_gl_available", lambda: False)
    monkeypatch.setattr(
        main_module.MainWindow,
        "_ask_where_to_export",
        lambda self, title, suggested, file_filter: tmp_path / "timer",
    )

    window.on_export_step()

    assert [p.name for p in tmp_path.iterdir()] == ["timer.step"]
    text = (tmp_path / "timer.step").read_text(encoding="ascii")
    assert text.startswith("ISO-10303-21;")
    assert "FILE_NAME('timer.step'" in text
    assert "PRODUCT('U1','U1'" in text
    _close(window)


def test_an_export_under_a_name_of_ones_own_writes_its_companions_beside_it(
    tmp_path, monkeypatch
) -> None:
    from perfboard_studio.ui import main as main_module

    window = _window_on(_golden_document("ne555"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(
        main_module.MainWindow,
        "_ask_where_to_export",
        lambda self, title, suggested, file_filter: elsewhere / "timer.pdf",
    )
    monkeypatch.setattr(
        main_module.MainWindow, "_offer_to_open", lambda self, written, **kwargs: None
    )

    window.on_export_schematic()

    assert sorted(p.name for p in elsewhere.iterdir()) == ["timer.pdf", "timer.png", "timer.svg"]
    _close(window)


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
    window._raise_view(window.dock_guide)
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
    window._raise_view(window.dock_guide)
    window._refresh_guide_panel()
    steps = window._assembly_steps()
    part_index = next(i for i, s in enumerate(steps) if isinstance(s, PartStep))

    leaf = _guide_leaf_for(window, part_index, ROLE_STEP_INDEX)
    leaf.setSelected(True)

    assert window.scene.selected_component_ids() == (steps[part_index].component_id,)
    _close(window)


def test_the_guide_panel_says_where_once() -> None:
    """A step read "R1 240 — J21 → J18, 3 holes apart" beside a Where column saying
    "J21 → J18, 3 holes apart" again -- and in a dock a third of the window wide, "R1…"
    and the repeat were all anybody could read. Now: the part first, its holes once."""
    from perfboard_studio.guide import PartStep
    from perfboard_studio.ui.main import ROLE_STEP_INDEX

    window = _window_on(_load_dense())
    window._raise_view(window.dock_guide)
    window._refresh_guide_panel()
    steps = window._assembly_steps()
    try:
        for index, step in enumerate(steps):
            line = _guide_leaf_for(window, index, ROLE_STEP_INDEX).text(0)
            if isinstance(step, PartStep):
                assert line.startswith(f"{step.ref} {step.value}".strip()), line
                # Two leads are named end to end; a wider part by where its pin 1 is.
                pins = dict(step.pin_holes)
                named = pins["1"] if len(pins) > 2 else step.pin_holes[0][1]
            else:
                assert line.startswith(f"{step.net_name} · "), line
                named = step.path[0]
            assert format_hole(named) in line, line
            assert line.count("→") <= 1, line
    finally:
        _close(window)


def test_the_guide_panel_says_what_the_guide_says() -> None:
    """The panel translates nothing of its own: its summary is ``guide.describe`` and its
    headings the guide's own phase titles, from the one guide the window builds in its own
    language. It used to keep a copy of both in the interface catalogue, from when the
    guide could only be English -- two tables for one set of words."""
    from perfboard_studio.guide import describe

    window = _window_on(_example_document("atmega328-relay"))
    try:
        window._raise_view(window.dock_guide)
        window._refresh_guide_panel()
        guide = window.current_guide()
        assert window.guide_summary.text() == describe(guide)
        headings = [
            window.guide_tree.topLevelItem(i).text(0)
            for i in range(window.guide_tree.topLevelItemCount())
        ]
        assert [heading.split(" (")[0] for heading in headings] == [
            f"{phase.number}. {phase.title}" for phase in guide.phases if not phase.is_empty
        ]
    finally:
        _close(window)


def _menu_tooltips(window) -> list[tuple[str, str]]:
    """(text, tooltip) for every action in every menu, depth first, in menu order.

    The actions are held while their submenus are read -- see
    test_a_view_is_put_away_from_the_panels_submenu for what happens otherwise."""
    found: list[tuple[str, str]] = []
    held: list = []

    def walk(menu) -> None:
        actions = menu.actions()
        held.append(actions)
        for action in actions:
            if action.isSeparator():
                continue
            found.append((action.text(), action.toolTip()))
            if action.menu() is not None:
                walk(action.menu())

    tops = window.menuBar().actions()
    held.append(tops)
    for top in tops:
        if top.menu() is not None:
            walk(top.menu())
    return found


def test_no_menu_tooltip_is_left_in_english_in_turkish() -> None:
    """The literal scan in test_i18n reads ``setToolTip("...")``, and a tooltip handed over
    as a VARIABLE out of a table slipped past it: the Draw menu's five tools and the
    routing styles' five explained themselves in English in a Turkish window, for as long
    as the tables had existed. This asks the window instead of the source -- every tooltip
    somebody wrote on purpose, in both languages, side by side."""
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    try:
        set_language("en")
        english_window = _window_on(_load_dense())
        english = _menu_tooltips(english_window)
        set_language("tr")
        turkish_window = _window_on(_load_dense())
        turkish = _menu_tooltips(turkish_window)
    finally:
        set_language(before)
    try:
        assert len(english) == len(turkish)
        left_in_english = [
            tip
            for (text, tip), (_tr_text, tr_tip) in zip(english, turkish, strict=True)
            # Written on purpose: Qt's default tooltip is the text itself. Prose only --
            # a file name in Open Recent is the same in every language.
            if tip != text.replace("&", "") and " " in tip and tip == tr_tip
        ]
        assert left_in_english == [], left_in_english
    finally:
        _close(english_window)
        _close(turkish_window)


def test_in_turkish_qt_says_its_own_buttons_in_turkish() -> None:
    """Every dialog asked its question in Turkish and offered "OK" and "Cancel" under it:
    ``t()`` translates what this application writes, and the standard buttons are Qt's.
    Qt ships their translation; ``main()`` loads the one for the chosen language."""
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from perfboard_studio.ui.i18n import language, set_language
    from perfboard_studio.ui.main import _install_qt_translations

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    before = language()
    set_language("tr")
    translator = _install_qt_translations(app)
    try:
        assert translator is not None, "PySide6 ships qtbase_tr.qm; it was not found"
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        texts = {button.text().replace("&", "") for button in buttons.buttons()}
        assert texts == {"Tamam", "İptal"}, texts
        buttons.deleteLater()
    finally:
        if translator is not None:
            app.removeTranslator(translator)
        set_language(before)
    set_language("en")
    try:
        assert _install_qt_translations(app) is None, "English needs no translator"
    finally:
        set_language(before)


def test_in_turkish_the_undo_menu_says_what_it_undoes_in_turkish() -> None:
    """"Geri Al Place and arrange 8 part(s) from the schematic": the one sentence saying
    what just happened was the one sentence left in English. Descriptions are said in the
    window's language where they are shown (ui/engine_text.py)."""
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        window = _blank_window()
        try:
            _add(window, "R1", "r-axial-3", "10k")
            assert "Şemaya R1 10k ekle" in window.act_undo.text()
            assert "schematic" not in window.act_undo.text()
            assert window.statusBar().currentMessage() in ("", "Yapıldı: Şemaya R1 10k ekle")
        finally:
            _close(window)
    finally:
        set_language(before)


def test_in_turkish_the_guide_panel_is_in_turkish() -> None:
    """The panel is interface, even though the guide it lists is written by the engine.
    Phase headings and the summary were English in an otherwise Turkish window."""
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        window = _window_on(_load_dense())
        try:
            window._raise_view(window.dock_guide)
            window._refresh_guide_panel()
            headings = [
                window.guide_tree.topLevelItem(i).text(0)
                for i in range(window.guide_tree.topLevelItemCount())
            ]
            assert any("Lehim yüzü" in heading for heading in headings), headings
            assert "adım" in window.guide_summary.text()
            assert "step(s)" not in window.guide_summary.text()
            # ...and so is the guide under them: a step's copper and a check's verdict.
            lines = [
                window.guide_tree.topLevelItem(i).child(j).text(0)
                for i in range(window.guide_tree.topLevelItemCount())
                for j in range(window.guide_tree.topLevelItem(i).childCount())
            ]
            assert any("lehim yolu" in line for line in lines), lines
            assert any("olmalı" in line for line in lines), lines
            assert window.current_guide().language == "tr"
        finally:
            _close(window)
    finally:
        set_language(before)


@requires_offscreen_gl  # nothing is rendered, but the scanner reads on_export_guide
def test_a_turkish_window_exports_a_turkish_guide(tmp_path, monkeypatch) -> None:
    """The file a Turkish builder prints is the guide in their language -- the same one
    the panel beside the board lists, not the English it used to be."""
    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.i18n import language, set_language

    monkeypatch.setattr(view3d, "offscreen_gl_available", lambda: False)
    monkeypatch.setattr("perfboard_studio.ui.main.QMessageBox.warning", lambda *a, **k: None)
    monkeypatch.setattr(main_module.MainWindow, "_offer_to_open", lambda self, written, **kwargs: None)
    monkeypatch.setattr(
        main_module.MainWindow,
        "_ask_where_to_export",
        lambda self, title, suggested, file_filter: tmp_path / suggested,
    )
    before = language()
    set_language("tr")
    try:
        window = _window_on(_example_document("ne555-astable"))
        window.current_path = tmp_path / "board.perf"
        try:
            window.on_export_guide()
        finally:
            _close(window)
    finally:
        set_language(before)
    page = (tmp_path / "board_guide.html").read_text(encoding="utf-8")
    assert '<html lang="tr">' in page and "Aşama 1" in page
    assert (tmp_path / "board_cut_list.csv").read_text(encoding="utf-8").startswith("tür,")


def _example_document(stem: str) -> PerfDocument:
    root = pathlib.Path(__file__).resolve().parents[1]
    result = persist.deserialize_document(
        (root / "examples" / f"{stem}.perf").read_text(encoding="utf-8")
    )
    assert result.ok
    return result.document


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


def test_a_wire_on_screen_is_the_colour_the_saved_board_draws_it() -> None:
    """The 2D view numbered the signal nets in the order they were made, and a board opened
    from its .perf has them in the file's order, sorted by id -- so the wire a builder saw
    yellow before saving was another colour after reopening, and the cut list printed from
    either session disagreed with the other's screen. The guide's half is
    ``test_guide.test_a_wire_is_the_colour_the_saved_board_calls_it``."""
    from .test_guide import eleven_signal_nets_in_the_order_they_were_made, reopened

    doc = eleven_signal_nets_in_the_order_they_were_made()
    lookup = footprint_lookup()

    def on_screen(board: PerfDocument) -> dict[str, str]:
        scene = BoardScene(board, lookup, side="top")
        return {
            item.conductor.id: item._colour().name()
            for item in scene.items()
            if isinstance(item, ConductorItem)
        }

    assert on_screen(doc) == on_screen(reopened(doc))


def test_a_wire_in_3d_and_in_step_is_the_colour_the_saved_board_paints_it() -> None:
    """The 3D view and the STEP export number the signal nets through
    ``view3d.net_colouring``, which walked them in the order they were made."""
    from perfboard_studio.ui import view3d

    from .test_guide import eleven_signal_nets_in_the_order_they_were_made, reopened

    doc = eleven_signal_nets_in_the_order_they_were_made()

    def painted(board: PerfDocument) -> dict[str, tuple[float, float, float]]:
        net_class, signal_index = view3d.net_colouring(board)
        return {
            c.id: view3d.wire_rgb(c, net_class.get(c.net_id or ""), signal_index.get(c.net_id or "", 0))
            for c in board.conductors
        }

    assert painted(doc) == painted(reopened(doc))


def test_a_wire_s_own_colour_is_drawn_the_same_in_both_views() -> None:
    """The 3D view read a wire's own colour only as #rrggbb, so one the document called
    "red" was red on the board and its net's colour in 3D. Both views now read it through
    view2d.explicit_colour, and what no reader understands falls back to the net's colour in
    both, rather than the 2D view painting an invalid QColor -- black."""
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.view2d import explicit_colour

    board = _load_dense().board
    path = (HoleCoord(1, 1), HoleCoord(5, 1))

    def sleeve(color: str | None) -> tuple[float, float, float]:
        wire = WireConductor(id="w", path=path, kind="insulated-wire", color=color)
        # The tinned core first, then the sleeve over it; the solids at the ends follow.
        return view3d.build_conductor(wire, board, net_class="signal")[1].GetProperty().GetColor()

    for value, hex_name in (("red", "#ff0000"), ("Blue", "#0000ff"), ("#1e90ff", "#1e90ff")):
        colour = explicit_colour(value)
        assert colour is not None and colour.name() == hex_name
        expected = [view3d._to_linear(c) for c in (colour.redF(), colour.greenF(), colour.blueF())]
        assert sleeve(value) == pytest.approx(expected)

    assert explicit_colour("#12") is None and explicit_colour(" ") is None
    assert sleeve("#12") == sleeve(None)


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
    a DRC message, "10k" from the schematic, "TO-220" from the pile on the bench. Go to
    Part is the command palette on the parts alone."""
    from perfboard_studio.ui.partnames import footprint_label

    window = _window_on(_load_dense())
    try:
        window.on_go_to_part()
        palette = window.command_palette
        everything = palette.list.count()
        assert everything == len(window.bus.document.components) + len(window.bus.document.parts)

        first = window.bus.document.components[0]
        palette.field.setText(first.ref)
        assert 0 < palette.list.count() < everything
        palette.field.setText(first.value)
        assert palette.list.count() > 0
        footprint = window.lookup(first.footprint_id)
        palette.field.setText(footprint_label(footprint.name))
        assert palette.list.count() > 0

        palette.field.setText("no such part anywhere")
        assert palette.list.count() == 0
        palette.close_palette()
    finally:
        _close(window)


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
    assert "6 steps by trace" in text


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


def test_the_designer_round_trips_a_board() -> None:
    """Opened on a board nobody sells, the designer makes exactly that board -- and changes
    what it is told to, and nothing else."""
    from tests.designer_support import designer_on

    doc = _load_dense()
    dialog = designer_on(doc.board)
    assert dialog.design().board == doc.board

    dialog.cols.setValue(40)
    dialog.material.setCurrentIndex(dialog.material.findData("FR2"))
    changed = dialog.design().board
    assert changed.cols == 40
    assert changed.material == "FR2"
    assert changed.pitch == doc.board.pitch
    assert changed.pad_diameter == doc.board.pad_diameter


def test_the_designer_opens_on_the_product_a_board_is() -> None:
    """A perfboard is bought, not specified: a stock 4 x 6 opens as that product, in its
    family at its size -- and showing it is not choosing it, so Use rebuilds nothing."""
    from perfboard_studio.boardfamily import (
        STANDARD_PRESETS,
        board_from_preset,
        preset_edge_connectors,
        preset_mounting_holes,
    )
    from tests.designer_support import designer_on

    stock = next(p for p in STANDARD_PRESETS if p.name == "4 x 6 cm" and not p.single_sided)
    board = board_from_preset(stock, _load_dense().board)
    features = (preset_edge_connectors(stock, board), preset_mounting_holes(stock, board))
    dialog = designer_on(board, features)
    assert dialog._this is None and dialog._family.id == "double-sided-fr4"
    assert dialog.stock.currentText().startswith("4 x 6")
    design = dialog.design()
    assert (design.board, design.edge_connectors, design.mounting_holes) == (board, *features)


def test_the_designer_opens_on_this_board_when_nobody_sells_it() -> None:
    """Then its own fields are the only thing describing it: it is first in the list as
    "This board", with its grid and its size in millimetres to change."""
    from tests.designer_support import designer_on, shown

    doc = _load_dense()  # 40 x 28 is not a size anybody stocks
    dialog = designer_on(doc.board)
    assert dialog._this is not None and dialog.families.currentRow() == 0
    assert dialog.families.item(0).text() == "This board"
    assert shown(dialog, "grid") and shown(dialog, "sizes")
    assert (dialog.cols.value(), dialog.rows.value()) == (doc.board.cols, doc.board.rows)


def test_which_way_the_strips_run_is_only_asked_of_a_stripboard() -> None:
    """Hidden rather than greyed out: a disabled row still costs a line and still has to
    be read past to find out it does not apply."""
    from tests.designer_support import choose_kind, designer_on, shown

    dialog = designer_on(_load_dense().board)
    assert not shown(dialog, "strip_axis")
    choose_kind(dialog, "stripboard")
    assert shown(dialog, "strip_axis")
    assert dialog.design().board.strip_axis in ("horizontal", "vertical")


def test_every_board_material_is_offered() -> None:
    """FR-2 in particular: it is the board most perfboard is actually sold as, and the
    only one where the pad-lifting rule and the derated iron temperature apply."""
    from typing import get_args

    from perfboard_studio.model import BoardMaterial
    from tests.designer_support import designer_on

    dialog = designer_on(_load_dense().board)
    offered = {dialog.material.itemData(i) for i in range(dialog.material.count())}
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


def test_a_wire_finishes_on_enter_and_keeps_the_tool() -> None:
    scene, bus = _drawing_scene()
    scene.arm_drawing("insulated-wire")

    assert scene.draw_click(view2d.HoleCoord(2, 2)) is None  # First click starts it.
    assert scene.draw_click(view2d.HoleCoord(9, 6)) is None  # ...and it takes a corner.
    result = scene.commit_drawing()

    assert result is not None and result.ok, result
    conductor = bus.document.conductors[0]
    assert conductor.kind == "insulated-wire"
    assert conductor.path == (
        view2d.HoleCoord(2, 2), view2d.HoleCoord(9, 2), view2d.HoleCoord(9, 6)
    )
    assert conductor.side == "bottom"
    # Still armed for the next wire, with nothing drawn: copper is laid in a series.
    assert scene.armed_draw_kind == "insulated-wire"
    assert scene.drawn_path == ()


def test_a_top_jumper_drawn_by_hand_runs_over_the_component_side() -> None:
    """The kind says where it goes. The window left a hand-drawn top jumper at the
    payload's default, the solder side, so 3D drew it under the board and DRC judged it
    against the solder side's copper -- while the router and an agent laid the same jumper
    on top. All three ask commands.wire_side now."""
    from perfboard_studio.commands import wire_side

    scene, bus = _drawing_scene()
    scene.arm_drawing("top-jumper")
    scene.draw_click(view2d.HoleCoord(2, 2))
    result = scene.draw_click(view2d.HoleCoord(9, 6))

    assert result is not None and result.ok, result
    assert bus.document.conductors[0].side == "top"
    board = bus.document.board
    assert [wire_side(k, board) for k in ("top-jumper", "insulated-wire", "bare-wire")] == [
        "top", "bottom", "bottom",
    ]


def test_a_solder_trace_is_a_chain_and_commits_on_request() -> None:
    scene, bus = _drawing_scene()
    scene.arm_drawing("solder-trace")

    for col in range(2, 6):
        scene.draw_click(view2d.HoleCoord(col, 4))
    assert not bus.document.conductors  # Still being drawn.

    result = scene.commit_drawing()

    assert result is not None and result.ok, result
    assert len(bus.document.conductors[0].path) == 4


def test_a_diagonal_click_is_a_run_round_the_corner_never_a_diagonal_step() -> None:
    """Solder spans the 0.6 mm gap to the next pad and not the 1.7 mm diagonal one. A
    click diagonally away used to be refused; now it is a run along the row and down the
    column, through the corner pad -- and the copper still never steps diagonally."""
    from perfboard_studio.geometry import validate_orthogonal_chain

    scene, bus = _drawing_scene()
    scene.arm_drawing("solder-trace")
    scene.draw_click(view2d.HoleCoord(4, 4))
    assert scene.draw_click(view2d.HoleCoord(5, 5)) is None
    result = scene.commit_drawing()

    assert result is not None and result.ok, result
    path = bus.document.conductors[0].path
    assert path == (view2d.HoleCoord(4, 4), view2d.HoleCoord(5, 4), view2d.HoleCoord(5, 5))
    assert validate_orthogonal_chain(path).ok


def test_a_drawn_wire_turns_its_corner_the_other_way_on_slash() -> None:
    """Off a row, a wire is an L along the grid -- row first, or column first after ``/``
    -- because that is how a wire is laid on a board and how the router lays one."""
    scene, bus = _drawing_scene()
    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(4, 4))
    scene.flip_draw_corner()
    scene.draw_click(view2d.HoleCoord(7, 9))
    result = scene.commit_drawing()
    assert result is not None and result.ok
    assert bus.document.conductors[0].path == (
        view2d.HoleCoord(4, 4), view2d.HoleCoord(4, 9), view2d.HoleCoord(7, 9)
    )


def test_a_wire_may_still_go_diagonally_where_its_corner_is_dragged() -> None:
    """A wire physically can: a corner put down off the grid's lines stays there."""
    path = (view2d.HoleCoord(4, 4), view2d.HoleCoord(7, 4), view2d.HoleCoord(7, 9))
    assert view2d.reshaped_path("bare-wire", path, 1, view2d.HoleCoord(5, 6)) == (
        view2d.HoleCoord(4, 4), view2d.HoleCoord(5, 6), view2d.HoleCoord(7, 9)
    )


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
    scene.commit_drawing()
    assert bus.document.conductors[-1].net_id == "n1"

    # ...and an end on no pin at all leaves it unassigned rather than guessing.
    scene.set_document(bus.document)
    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(4, 10))
    scene.draw_click(view2d.HoleCoord(8, 10))
    scene.commit_drawing()
    assert bus.document.conductors[-1].net_id is None


def test_conductors_can_be_selected_and_deleted() -> None:
    scene, bus = _drawing_scene()
    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(2, 2))
    scene.draw_click(view2d.HoleCoord(8, 2))
    scene.commit_drawing()
    scene.set_document(bus.document)

    items = [i for i in scene.items() if isinstance(i, view2d.ConductorItem)]
    assert len(items) == 1
    items[0].setSelected(True)

    assert scene.selected_conductor_ids() == (bus.document.conductors[0].id,)


def test_a_conductor_is_pickable_along_its_length_not_by_its_bounding_box() -> None:
    """A wire with a corner has a bounding rect the size of the board between its ends;
    picking by that rect would select whichever happened to be on top."""
    scene, bus = _drawing_scene()
    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(2, 2))
    scene.draw_click(view2d.HoleCoord(20, 20))
    scene.commit_drawing()
    scene.set_document(bus.document)

    item = next(i for i in scene.items() if isinstance(i, view2d.ConductorItem))
    on_the_wire = view2d.hole_to_screen(view2d.HoleCoord(20, 11), bus.document.board, "top")
    off_the_wire = view2d.hole_to_screen(view2d.HoleCoord(11, 11), bus.document.board, "top")

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

    Each GLYPH is reflected about its own centre, and nothing else moves: A stays under the
    hole A names, on both faces. The whole legend used to be reflected about the hole span
    as well, on top of the camera turning the board over, which mirrored it twice -- the
    underside's column A carried "AH". Checked on the geometry rather than on pixels.
    """
    import dataclasses

    from perfboard_studio.model import BoardLabels
    from perfboard_studio.ui import view3d

    doc = _load_dense()
    board = dataclasses.replace(
        # One edge, so no row number stands beside the columns this looks at.
        doc.board, cols=6, rows=4, labels=BoardLabels(row_digits=2, all_edges=False)
    )
    doc = dataclasses.replace(doc, board=board, components=(), conductors=())

    top, bottom = view3d.build_legend(doc)

    def glyph(actor: object, col: int) -> set[tuple[float, float]]:
        """The points of the column letter printed above ``col``, along the top edge."""
        data = actor.GetMapper().GetInput()  # type: ignore[attr-defined]
        found = [data.GetPoint(i)[:2] for i in range(data.GetNumberOfPoints())]
        top_edge = max(y for _x, y in found) - 1.5
        centre = col * board.pitch
        return {
            (round(x, 3), round(y, 3))
            for x, y in found
            if y > top_edge and abs(x - centre) < board.pitch * 0.45
        }

    # B and F are asymmetric, so a glyph left unreflected is a different point set, and a
    # legend reflected about the span puts E's points over B and A's over F instead.
    for col in (1, board.cols - 1):
        centre = col * board.pitch
        printed = glyph(top, col)
        assert printed
        assert glyph(bottom, col) == {(round(2 * centre - x, 3), y) for x, y in printed}


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
def test_the_step_pictures_report_as_they_go_and_stop_when_told() -> None:
    """Stopped part-way, the set comes back EMPTY: a guide illustrated up to step 2 of 30
    reads as a guide whose last steps went wrong."""
    from perfboard_studio.guide import all_steps, build_guide
    from perfboard_studio.ui import view3d

    doc = _load_dense()
    lookup = footprint_lookup()
    guide = build_guide(doc, lookup)
    total = len(all_steps(guide))
    told: list[tuple[int, int]] = []

    def progress(done: int, of: int) -> bool:
        told.append((done, of))
        return done < 2

    images = view3d.render_step_images(doc, guide, lookup, 120, 80, progress=progress)

    assert told == [(1, total), (2, total)]
    assert images == {}


def test_a_step_frame_is_its_subject_with_board_enough_to_count_from() -> None:
    """Framed on the whole board, a resistor on a 9 x 15 cm board was a few pixels of
    highlight. Framed on itself, it would say nothing about where it goes. So: the subject,
    widened about its own centre to STEP_CONTEXT_MM across the board, its height its own."""
    from perfboard_studio.ui.view3d import STEP_CONTEXT_MM, step_frame_bounds

    resistor = step_frame_bounds((70.0, 80.0, -50.0, -46.0, -1.0, 4.0))
    half = STEP_CONTEXT_MM / 2
    assert resistor == pytest.approx((75 - half, 75 + half, -48 - half, -48 + half, -1.0, 4.0))

    long_wire = step_frame_bounds((10.0, 120.0, -45.0, -44.0, -2.0, -1.0))
    assert long_wire[:2] == pytest.approx((10.0, 120.0))
    assert long_wire[3] - long_wire[2] == pytest.approx(STEP_CONTEXT_MM)


@requires_offscreen_gl
def test_a_step_picture_comes_in_on_its_subject_and_never_backs_out_past_the_board() -> None:
    """The direction is the face's and only the distance and the aim follow the step, so
    the pages still read as one board; nothing to frame on, or something bigger than the
    board, gets the whole board."""
    import vtkmodules.all as vtk

    from perfboard_studio.guide import all_steps, build_guide, step_focus
    from perfboard_studio.ui import view3d

    doc = _load_dense()
    lookup = footprint_lookup()
    focus = step_focus(all_steps(build_guide(doc, lookup))[0])
    ren, _stats = view3d.build_renderer(doc, lookup)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(ren)
    win.SetSize(160, 106)
    view3d.apply_default_camera(ren, False)
    whole_board = vtk.vtkCamera()
    whole_board.DeepCopy(ren.GetActiveCamera())

    subject: list = []
    view3d.populate_renderer(ren, doc, lookup, highlight=focus, subject_actors=subject)
    assert subject
    view3d.frame_step(ren, whole_board, subject)
    camera = ren.GetActiveCamera()
    assert camera.GetDistance() < whole_board.GetDistance()
    assert camera.GetDirectionOfProjection() == pytest.approx(
        whole_board.GetDirectionOfProjection()
    )

    view3d.frame_step(ren, whole_board, [])
    assert camera.GetPosition() == pytest.approx(whole_board.GetPosition())

    huge = vtk.vtkActor()
    huge.SetMapper(vtk.vtkPolyDataMapper())
    cube = vtk.vtkCubeSource()
    cube.SetBounds(-1e4, 1e4, -1e4, 1e4, 0.0, 1.0)
    huge.GetMapper().SetInputConnection(cube.GetOutputPort())
    ren.AddActor(huge)
    view3d.frame_step(ren, whole_board, [huge])
    assert camera.GetPosition() == pytest.approx(whole_board.GetPosition())


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
    # Framed in the window's shape and then on the step, as render_step_images frames it (a
    # component-side step).
    view3d.apply_default_camera(ren, False)
    whole_board = vtk.vtkCamera()
    whole_board.DeepCopy(ren.GetActiveCamera())
    subject: list = []
    view3d.populate_renderer(
        ren, document_at_step(doc, guide, index), lookup, highlight=focus, subject_actors=subject
    )
    view3d.frame_step(ren, whole_board, subject)
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
    # Wet tin made solder a lighter grey (0.68 -> 0.80) and the gap with the wire's tin
    # 0.68 -> 0.32; what keeps them apart is now also the section (a squashed run with a
    # joint at every pad against a round wire) and the sheen (0.24 against 0.12).
    assert difference > 0.3, "solder and tinned wire are still indistinguishable"


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
        TRACE_FLATTEN,
        TRACE_JOINT_RADIUS_MM,
    )

    # How far each stands off its centreline UPWARD, which is the direction a step lifts:
    # a run is squashed about the copper it is fused to (TRACE_FLATTEN).
    radii = (TRACE_JOINT_RADIUS_MM * TRACE_FLATTEN, BARE_WIRE_RADIUS_MM, INSULATED_RADIUS_MM)
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
    from perfboard_studio.ui.view3d import WIRE_LIFT_MM, conductor_radius, conductor_z, pad_z

    board = _load_dense().board
    run = SolderTraceConductor(id="t1", path=(HoleCoord(2, 2), HoleCoord(6, 2)))
    wire = WireConductor(id="w1", path=(HoleCoord(2, 4), HoleCoord(9, 4)), kind="bare-wire")
    copper = pad_z(board, "bottom")

    assert conductor_z(run, board, 0) == pytest.approx(copper)
    # A wire stands WIRE_LIFT_MM clear of the copper as well as its own radius off it.
    assert conductor_z(wire, board, 0) == pytest.approx(copper - conductor_radius(wire) - WIRE_LIFT_MM)


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
    # ...and rise to the height it runs at (a hand-bent wire bows a little higher in the
    # middle, so "at least", never "exactly").
    assert max(abs(point[2] - copper) for point in line) >= abs(run_z - copper) - 1e-9, (
        "and clear it in between"
    )
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

    from perfboard_studio.ui.view3d import TRACE_SAMPLES_PER_STEP

    line = _conductor_centreline(trace, board, copper, copper, is_trace=True)
    swell = _trace_swell(trace, line)

    samples = TRACE_SAMPLES_PER_STEP
    assert len(swell) == len(line)
    assert len(line) == samples * (len(trace.path) - 1) + 1, "a pad, then points between"
    # Widest exactly at the pads, narrowest exactly halfway between them...
    at_pads = swell[0::samples]
    halfway = swell[samples // 2 :: samples]
    assert len(at_pads) == len(trace.path)
    assert min(at_pads) == max(swell) and max(halfway) == min(swell)
    # ...and never a corner in between: the width falls to the waist and rises again.
    first_step = swell[: samples + 1]
    assert first_step[: samples // 2 + 1] == sorted(first_step[: samples // 2 + 1], reverse=True)
    assert first_step[samples // 2 :] == sorted(first_step[samples // 2 :])


def test_every_lead_on_the_solder_side_is_soldered() -> None:
    """The leads came out of bare rings -- a board with every part fitted and nothing
    soldered, on the one view whose job is to show the solder side. One fillet at every
    pin hole, and none where a mounting bore has taken the pad."""
    import dataclasses

    from perfboard_studio.geometry import all_pin_holes
    from perfboard_studio.model import MountingHole
    from perfboard_studio.ui.view3d import build_joints

    doc = _load_dense()
    lookup = footprint_lookup()
    holes = {
        (hole.col, hole.row)
        for comp in doc.components
        if (fp := lookup(comp.footprint_id)) is not None
        for _pin, hole in all_pin_holes(comp, fp)
        if 0 <= hole.col < doc.board.cols and 0 <= hole.row < doc.board.rows
    }
    (actor,) = build_joints(doc, lookup)
    assert actor.GetMapper().GetInput().GetNumberOfPoints() == len(holes)

    col, row = sorted(holes)[0]
    bored = dataclasses.replace(
        doc, mounting_holes=(MountingHole(id="mh1", at=HoleCoord(col, row)),)
    )
    (fewer,) = build_joints(bored, lookup)
    assert fewer.GetMapper().GetInput().GetNumberOfPoints() < len(holes)


def test_a_fillet_is_a_closed_cone_standing_off_the_face_it_is_made_on() -> None:
    import vtkmodules.all as vtk

    from perfboard_studio.ui.view3d import (
        LEAD_TRIM_MM,
        SOLDER_FILLET_BASE_MM,
        SOLDER_FILLET_HEIGHT_MM,
        _fillet_source,
    )

    below = _fillet_source(0.3, "bottom").GetBounds()
    above = _fillet_source(0.3, "top").GetBounds()
    assert below[5] == pytest.approx(0.0) and below[4] == pytest.approx(-SOLDER_FILLET_HEIGHT_MM)
    assert above[4] == pytest.approx(0.0) and above[5] == pytest.approx(SOLDER_FILLET_HEIGHT_MM)
    assert below[1] == pytest.approx(SOLDER_FILLET_BASE_MM, abs=0.01)
    # A trimmed lead stands proud of its joint, as a cut one does.
    assert LEAD_TRIM_MM > SOLDER_FILLET_HEIGHT_MM

    welded = vtk.vtkCleanPolyData()
    welded.SetInputData(_fillet_source(0.3, "bottom"))
    welded.ToleranceIsAbsoluteOn()
    welded.SetAbsoluteTolerance(1e-6)
    edges = vtk.vtkFeatureEdges()
    edges.SetInputConnection(welded.GetOutputPort())
    edges.BoundaryEdgesOn()
    edges.FeatureEdgesOff()
    edges.NonManifoldEdgesOff()
    edges.ManifoldEdgesOff()
    edges.Update()
    assert edges.GetOutput().GetNumberOfCells() == 0


def test_an_insulated_wire_is_stripped_at_both_ends() -> None:
    """A sleeve running right into the joint was a coloured capsule on two pads."""
    import itertools
    import math

    from perfboard_studio.ui.view3d import WIRE_STRIP_MM, _trimmed

    line = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (5.0, 5.0, 0.0)]
    sleeve = _trimmed(line, WIRE_STRIP_MM)
    length = sum(math.dist(a, b) for a, b in itertools.pairwise(line))
    kept = sum(math.dist(a, b) for a, b in itertools.pairwise(sleeve))
    assert kept == pytest.approx(length - 2 * WIRE_STRIP_MM)
    assert sleeve[0] == pytest.approx((WIRE_STRIP_MM, 0.0, 0.0))
    assert sleeve[-1] == pytest.approx((5.0, 5.0 - WIRE_STRIP_MM, 0.0))
    assert _trimmed([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)], WIRE_STRIP_MM) == []


def test_a_wire_is_bent_round_its_corners_and_ends_where_it_is_soldered() -> None:
    """A 90-degree mitre in a tube reads as plumbing; wire is bent over a finger."""
    import math

    from perfboard_studio.ui.view3d import WIRE_BEND_RADIUS_MM, _rounded

    corner = (5.0, 0.0, 0.0)
    line = [(0.0, 0.0, 0.0), corner, (5.0, 5.0, 0.0)]
    bent = _rounded(line, WIRE_BEND_RADIUS_MM)
    assert bent[0] == line[0] and bent[-1] == line[-1]
    assert corner not in bent, "the corner is replaced by the bend"
    assert min(math.dist(point, corner) for point in bent) > 0.1
    assert all(
        math.dist(point, corner) <= WIRE_BEND_RADIUS_MM + 1e-9
        for point in bent[1:-1]
    ), "and the bend stays within its radius of where the corner was"
    straight = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
    assert _rounded(straight, WIRE_BEND_RADIUS_MM) == straight


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
    levels = stacking_layers(doc, lookup=footprint_lookup())
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
    layers = stacking_layers(doc, lookup=footprint_lookup())
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
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.ui import boardcolors

    try:
        boardcolors.choose("blue")
        blue = boardcolors.scheme_for(DEFAULT_BOARD)
        assert blue.key == "blue"
        # The 2D hex and the 3D linear RGB describe the same colour.
        expected = (int(blue.fill[1:3], 16) / 255, int(blue.fill[3:5], 16) / 255,
                    int(blue.fill[5:7], 16) / 255)
        assert all(abs(a - b) < 0.06 for a, b in zip(blue.rgb, expected, strict=True))
    finally:
        boardcolors.choose(None)


def test_the_board_decides_until_someone_chooses() -> None:
    """FR-2 is the brown phenolic board, and the build guide derates the iron for exactly
    that material -- the two should agree on sight. A board that says nothing about its
    mask is drawn as its material is sold."""
    import dataclasses

    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.ui import boardcolors

    boardcolors.choose(None)
    assert boardcolors.scheme_for(DEFAULT_BOARD).key == "green"
    phenolic = dataclasses.replace(DEFAULT_BOARD, material="FR2")
    assert boardcolors.scheme_for(phenolic).key == "phenolic"


def test_an_unknown_colour_falls_back_to_the_board() -> None:
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.ui import boardcolors

    try:
        boardcolors.choose("chartreuse")
        assert boardcolors.chosen_key() is None
        assert boardcolors.scheme_for(DEFAULT_BOARD).key == "green"
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
    # A chip's top marking is physical ink too, but it is the part's, not the board's.
    monkeypatch.setattr(view2d, "_paint_top_marking", lambda *args: None)
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
    finger is does not come out faint -- it does not come out at all.

    The position used to be measured OUT FROM THE PAD, which is right until the copper on
    that edge is a finger reaching most of the way to the board edge: every column letter
    of the board this opens on was printed under one, and it came up with numbers and no
    letters. The board it opens on now carries its strips OUTSIDE the grid down its short
    edges, with the row numbers printed small between the grid and the strip, as the
    photographed board does -- so the claim is the general one: no label the legend lays
    down is under any finger, letters or numbers.
    """
    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.geometry import (
        edge_connector_holes,
        edge_finger_rect,
        legend_ink_width_mm,
    )
    from perfboard_studio.model import DocumentMeta

    doc = create_starter_document(DocumentMeta(name="t", created="", modified=""))
    board = doc.board
    assert board.labels is not None, "the board this opens on prints its own addresses"
    assert doc.edge_connectors and all(c.outside for c in doc.edge_connectors), (
        "wrong board for this test"
    )

    drawn = _legend_labels_drawn(doc, monkeypatch)
    letters = [d for d in drawn if d[0].isalpha()]
    numbers = [d for d in drawn if d[0].isdigit()]
    assert letters and numbers, "the letters or the numbers are not being laid down at all"

    fingers = [
        edge_finger_rect(connector, hole, board)
        for connector in doc.edge_connectors
        for hole in edge_connector_holes(connector, board)
    ]
    for text, centre, height, max_width in drawn:
        ink = legend_ink_width_mm(text, height, max_width or board.pitch * 0.9)
        # A number is turned on its side, so its box is too.
        width, tall = (ink, height) if text.isalpha() else (height, ink)
        for rect in fingers:
            assert not (
                abs(centre.x() - (rect.x + rect.width / 2)) * 2 < width + rect.width
                and abs(centre.y() - (rect.y + rect.height / 2)) * 2 < tall + rect.height
            ), f"{text} is printed under a connector finger"


def test_the_designer_round_trips_the_new_board_fields() -> None:
    from tests.designer_support import designer_on

    document = _featured_document()
    board = document.board
    dialog = designer_on(board, (document.edge_connectors, document.mounting_holes))
    assert dialog.design().board == board

    dialog.pad_shape.setCurrentIndex(dialog.pad_shape.findData("round"))
    for combo in (dialog.letters, dialog.numbers):
        combo.setCurrentIndex(combo.findData("none"))
    dialog._on_kind()
    plain = dialog.design().board
    assert plain.pad_shape == "round"
    # The length is dropped with the shape: a round board carrying a pad length would put
    # a field in the file describing nothing.
    assert plain.pad_length is None
    assert plain.labels is None

    dialog.letters.setCurrentIndex(dialog.letters.findData("top"))
    dialog._on_kind()
    dialog.row_digits.setValue(3)
    labels = dialog.design().board.labels
    assert labels is not None and labels.row_digits == 3


def test_the_designer_cannot_produce_an_oblong_pad_the_bus_would_refuse() -> None:
    """A dialog whose only exit is an error message is a worse dialog than one that
    cannot produce the error: either it holds Use This Board and says why, or the board it
    gives is one the bus takes."""
    from perfboard_studio.commands import DEFAULT_BOARD, SetBoardPayload
    from tests.designer_support import designer_on

    dialog = designer_on(DEFAULT_BOARD)
    dialog.pad_shape.setCurrentIndex(dialog.pad_shape.findData("oblong"))
    dialog._on_kind()
    dialog.pad_length.setValue(0.5)  # narrower than the 1.9 mm pad width
    dialog._show()
    if dialog.use.isEnabled():
        bus = _new_bus(_blank_document())
        assert bus.dispatch("board.set", SetBoardPayload(board=dialog.design().board)).ok
    else:
        assert any(not label.isHidden() for label in dialog._problems.values()) or (
            not dialog.refusal.isHidden())


def _board_features(window):
    """The board's holes and connectors in Properties, where Board Features was a dialog:
    nothing selected, and Board Settings on the step card pressed."""
    window.scene.clearSelection()
    window._selection_from = "board"
    window._refresh_properties()
    window.inspector.step_card.board_settings.click()
    assert window.inspector.shown is window.inspector.board_editor
    features = window.inspector.board_editor.features
    features.set_open(True)  # closed by default: these tests are about what is inside
    return features


def test_the_boards_features_add_four_corner_holes_as_one_undo_step() -> None:
    window = _window_on(_blank_document())
    try:
        features = _board_features(window)
        features.mount_inset.setValue(1)
        features.add_corners.click()
        assert len(window.bus.document.mounting_holes) == 4
        assert len(_board_features(window).rows()) == 4
        window.on_undo()
        assert window.bus.document.mounting_holes == ()
    finally:
        _close(window)


def test_the_boards_features_say_a_refusal_instead_of_swallowing_it() -> None:
    window = _window_on(_blank_document())
    try:
        features = _board_features(window)
        features.mount_inset.setValue(20)
        features.add_corners.click()
        assert window.bus.document.mounting_holes == ()
        assert features.problem.text() and not features.problem.isHidden()
    finally:
        _close(window)


def test_each_feature_in_the_list_removes_itself() -> None:
    window = _window_on(_featured_document())
    try:
        features = _board_features(window)
        assert len(features.rows()) == 2
        features.rows()[0].remove.click()  # the hole: holes are listed first
        assert window.bus.document.mounting_holes == ()
        assert len(window.bus.document.edge_connectors) == 1
        assert len(_board_features(window).rows()) == 1
    finally:
        _close(window)


def test_enter_in_the_boards_features_removes_nothing() -> None:
    """Qt made the first push button Board Features' default, and that was Remove: Enter
    typed into the hole-diameter box deleted whichever feature was selected."""
    from PySide6.QtTest import QTest

    window = _window_on(_featured_document())
    window.show()
    try:
        features = _board_features(window)
        features.mount_diameter.setFocus()
        QTest.keyClick(features.mount_diameter, Qt.Key.Key_Return)
        assert len(window.bus.document.mounting_holes) == 1
        assert len(window.bus.document.edge_connectors) == 1
    finally:
        _close(window)


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


def test_the_build_steps_forward_and_back_one_at_a_time() -> None:
    """Playing is for watching; somebody following the build at the bench wants the next
    step when they have done this one. Each arrow goes as far as there is to go, and a step
    asked for stops the playing rather than racing it."""
    window = _window_on(_load_dense())
    # What opening the 3D view adds under it, held by the panel as it is there.
    window._3d_layout.addWidget(window._build_assembly_bar())
    slider = window.assembly_slider
    end = slider.maximum()

    assert slider.value() == end  # the finished board
    assert window.act_step_back.isEnabled() and not window.act_step_next.isEnabled()

    window.act_step_back.click()
    assert slider.value() == end - 1  # the last step, picked out
    window.act_step_next.click()
    assert slider.value() == end

    window.act_play.setChecked(True)  # from the finished board, playing starts over
    assert slider.value() == 0
    assert not window.act_step_back.isEnabled() and window.act_step_next.isEnabled()
    window.act_step_next.click()
    assert slider.value() == 1
    assert not window.act_play.isChecked()

    window.step_assembly(-5)
    assert slider.value() == 0
    _close(window)


def test_stepping_the_3d_view_brings_the_guide_to_the_same_step() -> None:
    """The guide moves the 3D view when a row is picked; the other way round, the guide's
    row follows the step being shown -- without selecting that step's parts on the board,
    which nobody asked for by stepping."""
    from perfboard_studio.ui.main import ROLE_STEP_INDEX

    window = _window_on(_load_dense())
    window._raise_view(window.dock_guide)
    window._refresh_guide_panel()
    window._3d_layout.addWidget(window._build_assembly_bar())
    selected_before = window.scene.selected_component_ids()

    window.act_step_back.click()
    window.act_step_back.click()

    rows = window.guide_tree.selectedItems()
    last = len(window._assembly_steps()) - 1
    assert [row.data(0, ROLE_STEP_INDEX) for row in rows] == [last - 1]
    assert window.scene.selected_component_ids() == selected_before

    window.step_assembly(10)  # the finished board: no step to point at
    assert window.guide_tree.selectedItems() == []
    _close(window)


def test_a_click_in_3d_goes_through_the_sheets_doors(monkeypatch) -> None:
    """A part clicked in 3D is selected on the board and the guide goes to the step that
    fits it; a conductor clicked lights its net; the board or the room puts the selection
    down. What the click LANDED on is ``view3d.owner_at``'s question, measured with GL in
    test_3d_picking -- here it is stood in for, and the window's half is what is asked."""
    from perfboard_studio import persist
    from perfboard_studio.guide import PartStep
    from perfboard_studio.ui import view3d
    from perfboard_studio.ui.main import ROLE_STEP_INDEX

    # A real board, whose copper joins real pins -- with the nets the router wrote on its
    # wires taken off, as copper laid by hand carries none: the net is then the one the
    # copper wires up, read the way LVS reads it, and it must be the same answer.
    root = pathlib.Path(__file__).resolve().parents[1]
    routed = persist.deserialize_document(
        (root / "examples" / "nano-relay.perf").read_text(encoding="utf-8")
    ).document
    assert routed is not None
    written = {c.id: c.net_id for c in routed.conductors}
    document = dataclasses.replace(
        routed,
        conductors=tuple(dataclasses.replace(c, net_id=None) for c in routed.conductors),
    )
    window = _window_on(document)
    window._raise_view(window.dock_guide)
    window._refresh_guide_panel()
    window._vtk_renderer = object()  # stands for the live renderer; owner_at is stubbed
    landed: list = [None]
    monkeypatch.setattr(view3d, "owner_at", lambda _ren, _owners, _x, _y: landed[0])

    part = next(
        step for step in window._assembly_steps() if isinstance(step, PartStep)
    ).component_id
    landed[0] = ("component", part)
    window.pick_in_3d(10, 10)
    assert window.scene.selected_component_ids() == (part,)
    rows = window.guide_tree.selectedItems()
    assert len(rows) == 1
    step = window._assembly_steps()[rows[0].data(0, ROLE_STEP_INDEX)]
    assert isinstance(step, PartStep) and step.component_id == part

    wire = window.bus.document.conductors[0]
    net = window._net_of_conductor(wire.id)
    assert net is not None and net == written[wire.id]
    window.scene.clearSelection()
    landed[0] = ("conductor", wire.id)
    window.pick_in_3d(10, 10)
    assert tuple(window._selected_net_ids()) == (net,)

    landed[0] = ("component", part)
    window.pick_in_3d(10, 10)
    landed[0] = None
    window.pick_in_3d(10, 10)
    assert window.scene.selected_component_ids() == ()
    _close(window)


def test_what_is_selected_on_the_board_is_tinted_in_3d() -> None:
    """The 3D view is the third view of the same selection: a part selected on the board
    is picked out in the actors already built, and given back when it is let go."""
    vtk = pytest.importorskip("vtk")

    window = _window_on(_load_dense())
    part = window.bus.document.components[0]
    chosen, other = vtk.vtkActor(), vtk.vtkActor()
    window._3d_owners = {chosen: ("component", part.id), other: ("component", "someone-else")}
    window.vtk_widget = object()  # built; not on screen, so no frame is asked for

    window.go_to_component(part.id)
    assert chosen in window._3d_tinted and other not in window._3d_tinted

    window.scene.clearSelection()
    assert window._3d_tinted == {}
    window.vtk_widget = None
    _close(window)


def _guide_window_on_a_file(tmp_path):
    """A window on a board that has a file, with its build guide open."""
    from perfboard_studio.ui.main import MainWindow

    path = tmp_path / "board.perf"
    path.write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    window = MainWindow(_load_dense(), path)
    window._raise_view(window.dock_guide)
    window._refresh_guide_panel()
    return window, path


def _tick(window, number: int):
    from PySide6.QtCore import Qt

    leaf = window._guide_leaves()[number]
    leaf.setCheckState(0, Qt.CheckState.Checked)
    return leaf


def test_a_step_ticked_off_is_remembered_for_that_board(tmp_path) -> None:
    """At the bench, the guide says where the build has got: a tick is kept for the board's
    file in the settings, under what the step is ABOUT rather than its number, so it is
    still there in the next window on the same file. It is not an edit: the board is not
    modified and nothing joins the undo stack."""
    from PySide6.QtCore import Qt

    from perfboard_studio.ui.main import ROLE_STEP_FOCUS, MainWindow

    window, path = _guide_window_on_a_file(tmp_path)
    document = window.bus.document
    leaf = _tick(window, 1)
    focus = leaf.data(0, ROLE_STEP_FOCUS)

    assert window._done_steps() == {focus}
    assert window.bus.document is document and not window.bus.can_undo()
    assert not window.is_modified
    total = len(window._guide_leaves())
    assert f"1 of {total} steps done" in window.guide_summary.text()
    window._refresh_guide_panel()  # rebuilt, as every edit rebuilds it
    assert window._guide_leaves()[1].checkState(0) == Qt.CheckState.Checked
    _close(window)

    again = MainWindow(_load_dense(), path)
    again._raise_view(again.dock_guide)
    again._refresh_guide_panel()
    ticked = [leaf for leaf in again._guide_leaves() if leaf.checkState(0) == Qt.CheckState.Checked]
    assert [leaf.data(0, ROLE_STEP_FOCUS) for leaf in ticked] == [focus]
    _close(again)


def test_an_unsaved_boards_ticks_go_with_it_to_its_file(tmp_path) -> None:
    """A board with no file keeps its ticks in the window; once it has one -- saved, or
    saved under a new name -- they are that file's."""
    from perfboard_studio.ui.main import ROLE_STEP_FOCUS

    window = _window_on(_load_dense())
    window._raise_view(window.dock_guide)
    window._refresh_guide_panel()
    focus = _tick(window, 0).data(0, ROLE_STEP_FOCUS)

    window.current_path = tmp_path / "first.perf"
    assert window._done_steps() == {focus}
    assert window._unsaved_progress == set()

    window._carry_progress(tmp_path / "first.perf", tmp_path / "second.perf")
    window.current_path = tmp_path / "second.perf"
    assert window._done_steps() == {focus}
    _close(window)


def test_next_step_to_do_picks_the_first_step_without_a_tick(tmp_path) -> None:
    """Coming back to the bench: the first step not done, picked -- which shows it on the
    board, and in 3D when the 3D view is open."""
    from perfboard_studio.guide import PartStep

    window, _path = _guide_window_on_a_file(tmp_path)
    _tick(window, 0)
    _tick(window, 1)

    window.act_next_step.trigger()

    rows = window.guide_tree.selectedItems()
    assert rows == [window._guide_leaves()[2]]
    step = window._assembly_steps()[2]
    if isinstance(step, PartStep):
        assert window.scene.selected_component_ids() == (step.component_id,)
    _close(window)


def test_clearing_the_progress_asks_first(tmp_path, monkeypatch) -> None:
    """Every tick on the board, taken off -- asked first, with Cancel under Enter."""
    from perfboard_studio.ui.main import MainWindow

    window, _path = _guide_window_on_a_file(tmp_path)
    _tick(window, 0)
    _tick(window, 3)

    monkeypatch.setattr(MainWindow, "_confirm", lambda self, *_args: False)
    window.act_clear_progress.trigger()
    assert len(window._done_steps()) == 2

    monkeypatch.setattr(MainWindow, "_confirm", lambda self, *_args: True)
    window.act_clear_progress.trigger()
    assert window._done_steps() == set()
    assert not window.act_clear_progress.isEnabled()
    _close(window)


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


def _inspect_net(window, net_id: str):
    window._select_net(net_id)
    editor = window.inspector.net_editor
    assert window.inspector.shown is editor
    return editor


def test_new_net_creates_it_and_goes_straight_into_picking_its_pins() -> None:
    """Naming a net and then hunting for the command that fills it would be two decisions
    where the user made one. No form first: the net under its next free name, shown in
    Properties to be renamed, and the board picking its pins."""
    window = _window_on(_load_dense())
    before = {n.id for n in window.bus.document.nets}
    window.on_new_net()
    (net,) = [n for n in window.bus.document.nets if n.id not in before]
    assert window.scene.armed_net_id == net.id
    assert window.inspector.shown is window.inspector.net_editor
    assert window.inspector.net_editor.name.text() == net.name
    _type_into(window.inspector.net_editor.name, "HAND-WIRED")
    assert next(n for n in window.bus.document.nets if n.id == net.id).name == "HAND-WIRED"
    window.scene.arm_net_pins(None)
    _close(window)


def test_a_net_name_already_taken_is_refused_under_the_field(monkeypatch) -> None:
    """A duplicate name refused into the status bar threw away everything typed, and then a
    dialog brought the form back; here the name stays typed, with the reason under it."""
    from perfboard_studio.ui import main as main_module

    window = _window_on(_load_dense())
    first, second = window.bus.document.nets[:2]
    boxes: list = []
    monkeypatch.setattr(main_module.QMessageBox, "warning", lambda *a, **k: boxes.append(a))
    editor = _inspect_net(window, first.id)
    before = window.bus.document
    _type_into(editor.name, second.name)
    assert window.bus.document is before
    said = editor.name.problem.text()
    assert second.name in said and "duplicate-net-name" not in said and boxes == []
    assert editor.name.text() == second.name
    _close(window)


def test_a_net_typed_as_gnd_is_a_ground_net_unless_somebody_says_otherwise() -> None:
    """A GND left a "signal" is drawn as wires to every part on the sheet instead of as
    ground symbols. The name picks the class while the class still says only what the old
    name implied; once somebody picks a class, a rename leaves it alone."""
    window = _window_on(_load_dense())
    net = next(n for n in window.bus.document.nets if n.net_class == "signal")
    editor = _inspect_net(window, net.id)

    def now():
        return next(n for n in window.bus.document.nets if n.id == net.id)

    # Names no other net on dense.perf has: a taken one is refused, which is another test.
    _type_into(editor.name, "VCC_AUX")
    assert now().net_class == "power"
    _type_into(editor.name, "SIG_AUX")
    assert now().net_class == "signal"

    editor._class_buttons["ground"].click()  # a deliberate choice
    assert now().net_class == "ground"
    _type_into(editor.name, "VCC_AUX")
    assert now().net_class == "ground"
    _close(window)


def test_a_nets_current_and_voltage_are_set_in_properties() -> None:
    """The only place a board can be told what a net carries: blank is "not stated",
    which is a different thing from zero, and a -12 V rail is an ordinary value."""
    window = _window_on(_load_dense())
    net = window.bus.document.nets[0]
    editor = _inspect_net(window, net.id)

    def now():
        return next(n for n in window.bus.document.nets if n.id == net.id)

    editor.current.setValue(2.0)
    editor.current.editingFinished.emit()
    assert now().current_a == 2.0
    editor.voltage.setValue(-12.0)
    editor.voltage_stated.setChecked(True)
    assert now().voltage_v == -12.0
    editor.current.setValue(0.0)
    editor.current.editingFinished.emit()
    editor.voltage_stated.setChecked(False)
    assert (now().current_a, now().voltage_v) == (None, None)
    _close(window)


def test_the_designer_with_nothing_changed_is_the_board_it_was() -> None:
    """Board Setup's OK with nothing touched once rewrote the border on five of the six
    examples, and put an undo step, a dirty title and a bigger board behind a dialog nobody
    used. The designer opened on any board in the repository -- the examples, the goldens
    -- makes that board and its edge connector and holes, exactly."""
    from perfboard_studio.ui.main import example_boards
    from tests.designer_support import designer_on

    root = pathlib.Path(__file__).resolve().parents[1]
    paths = [path for path, _title in example_boards()]
    paths += sorted((root / "tools" / "diffcheck" / "golden").glob("*.perf"))
    assert len(paths) > 15
    for path in paths:
        doc = persist.parse_document_or_throw(path.read_text(encoding="utf-8"))
        dialog = designer_on(doc.board, (doc.edge_connectors, doc.mounting_holes))
        design = dialog.design()
        assert design.board == doc.board, path.name
        assert design.edge_connectors == doc.edge_connectors, path.name
        assert design.mounting_holes == doc.mounting_holes, path.name
        dialog.deleteLater()


def test_use_this_board_unchanged_changes_nothing(monkeypatch) -> None:
    """Opened from the window and used as it opened: no undo step, the same document, and
    the board counts as chosen."""
    from perfboard_studio.ui import designer as designer_module

    root = pathlib.Path(__file__).resolve().parents[1]
    document = persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    window = _window_on(document)
    try:
        before = (window.bus.document, len(window.bus.history()))

        def use(dialog) -> int:
            dialog._use()
            return int(dialog.result())

        monkeypatch.setattr(designer_module.BoardDesigner, "exec", use)
        assert window.on_design_board()
        assert (window.bus.document, len(window.bus.history())) == before
        assert not window.is_modified and window._board_chosen
    finally:
        _close(window)


def test_every_board_setup_field_has_a_home_in_the_designer() -> None:
    """Board Setup retired into the designer. Each of its questions is asked there, of the
    board it means something for -- the field named, and shown on that board."""
    from perfboard_studio.breadboard import breadboard, solderable_breadboard
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.model import BoardLabels
    from tests.designer_support import designer_on, shown

    stripboard = dataclasses.replace(DEFAULT_BOARD, type="stripboard", strip_axis="horizontal")
    oblong = dataclasses.replace(DEFAULT_BOARD, pad_shape="oblong", pad_length=2.4)
    homes = {
        # Board Setup's field: (the designer's row, a board it is asked of)
        "preset": ("stock", None),
        "board_type": ("type", DEFAULT_BOARD),
        "strip_axis": ("strip_axis", stripboard),
        "breadboard_size": ("stock", None),
        "breadboard_channel": ("breadboard.channel_mils", breadboard("830")),
        "narrow_channel": ("breadboard.narrow_channel_cols", breadboard("830", channel=9)),
        "border_x": ("breadboard.border_x_mm", solderable_breadboard("830")),
        "border_y": ("breadboard.border_y_mm", solderable_breadboard("830")),
        "cols": ("grid", DEFAULT_BOARD),
        "rows": ("grid", DEFAULT_BOARD),
        "material": ("material", DEFAULT_BOARD),
        "pad_shape": ("pad_shape", DEFAULT_BOARD),
        "pad_length": ("pad_length_mm", oblong),
        "pad_axis": ("pad_axis", oblong),
        "legend": ("legend.letter_edges", _load_dense().board),
        "row_digits": ("legend.row_digits", dataclasses.replace(
            DEFAULT_BOARD, labels=BoardLabels(row_digits=2))),
        "legend_columns": ("legend.columns", dataclasses.replace(
            DEFAULT_BOARD, labels=BoardLabels(row_digits=2))),
        "legend_rows": ("legend.rows", dataclasses.replace(
            DEFAULT_BOARD, labels=BoardLabels(row_digits=2))),
    }
    for field, (row, board) in homes.items():
        if board is None:
            continue  # the stock list: a combo above the rows, on every family
        dialog = designer_on(board)
        assert row in dialog._rows, field
        assert shown(dialog, row), (field, row)
        dialog.deleteLater()


def test_the_box_button_arms_the_shape_it_shows() -> None:
    """After Line was picked from its menu the button said Line and pressing it drew a
    box; and the box itself was not on the menu to change back to."""
    window = _window_on(_load_dense())
    try:
        box = window.act_sheet_tool["rectangle"]
        window.on_sheet_tool("line")
        assert box.text() == "Line" and box.isChecked()
        window.on_sheet_tool("select")
        box.trigger()
        assert window.schematic_view.tool == "line"
        menu = box.menu()
        assert menu is not None
        labels = [action.text() for action in menu.actions()]
        assert labels == ["Box", "Line", "Circle"]
        menu.actions()[0].trigger()
        assert box.text() == "Box" and window.schematic_view.tool == "rectangle"
    finally:
        _close(window)


def test_renaming_a_net_to_gnd_makes_it_a_ground_net() -> None:
    """The sheet's auto-named N3, renamed GND from its wire's menu, was a signal called GND:
    drawn as wires, routed last. Renamed by the dialog's rule -- only while the class still
    says what the old name implied."""
    window = _window_on(_load_dense())
    net = next(n for n in window.bus.document.nets if n.net_class == "signal")
    window._rename_net(net.id)
    name = window.inspector.net_editor.name
    _type_into(name, "GND2")
    renamed = next(n for n in window.bus.document.nets if n.id == net.id)
    assert (renamed.name, renamed.net_class) == ("GND2", "signal")  # GND2 names no class

    _type_into(name, "VCC_AUX")
    renamed = next(n for n in window.bus.document.nets if n.id == net.id)
    assert (renamed.name, renamed.net_class) == ("VCC_AUX", "power")
    _close(window)


def test_a_net_of_parts_not_yet_placed_is_not_done() -> None:
    """A circuit freshly drawn, or imported, listed every net as "done": nothing was left to
    route because nothing was placed. It says so now, and the class column speaks the
    window's language rather than the engine's ids."""
    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        _add(window, "R2", "r-axial-3")
        _wire(window, "OUT", ("R1", "1"), ("R2", "2"))
        window._refresh_nets_panel(window._last_ratsnest)
        row = window.nets_tree.topLevelItem(0)
        assert row is not None
        assert row.text(3) == "not placed"
        assert row.text(1) == "signal"
        # ...and is not drawn in the green that means done.
        from perfboard_studio.ui.theme import OK

        assert row.foreground(3).color().name() != QColor(OK).name()
    finally:
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


def test_re_routing_asks_through_the_box_with_cancel_under_enter(monkeypatch) -> None:
    """It rips up copper, and it asked with QMessageBox.question and Yes under Enter -- the
    one destructive question in the window that did not go through _confirm."""
    from perfboard_studio.ui import i18n

    root = pathlib.Path(__file__).resolve().parents[1]
    document = persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    window = _window_on(document)
    asked: list[str] = []
    monkeypatch.setattr(
        type(window), "_confirm", lambda self, title, body, verb: asked.append(verb) or False
    )
    # Something other than the example's own routing, or there is nothing to ask about:
    # the examples are routed as the window routes by default.
    window.on_routing_style("solder")

    window.on_reroute(None)

    assert asked == [i18n.t("Redo Wiring")]
    assert window.bus.document is document or window.bus.document.conductors == document.conductors
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


def test_an_empty_board_under_a_drawn_circuit_says_how_the_parts_get_to_it() -> None:
    """A circuit drawn on the sheet, or imported, over a board with nothing on it: the next
    step is two panels away, so the board says so -- every time, not only on a first start
    (``_has_placed_a_part`` retires the first-start guidance, and must not retire this)."""
    window = _blank_window()
    try:
        window._has_placed_a_part = True
        _add(window, "R1", "r-axial-3")
        window._refresh_empty_hint()
        assert not window.view.empty_hint.isHidden()
        assert "1" in window.view.empty_hint.text()
        assert "Place on the Board" in window.view.empty_hint.text()
    finally:
        _close(window)


def test_no_part_is_drawn_over_another_parts_reference() -> None:
    """Each part printed its own reference, so it sat at the part's place in the stacking
    order and the next part along was drawn over it: on the dense fixture "X12" came out
    as "X1" and "X5" as "X". One layer above every part prints them all -- and follows a
    part that is dragged or selected."""
    from PySide6.QtCore import QPointF

    window = _window_on(_load_dense())
    try:
        scene = window.scene
        layer = scene.reference_layer
        assert layer is not None
        parts = list(scene.component_items.values())
        assert parts
        assert all(layer.zValue() > item.zValue() for item in parts)
        item = parts[0]
        before = item.reference_anchor()
        item.setPos(item.pos() + QPointF(scene.document.board.pitch, 0.0))
        assert item.reference_anchor().x() > before.x()
        # A rebuild -- any command -- must not leave the layer a dead wrapper.
        window.on_flip_board()
        window.on_flip_board()
        assert scene.reference_layer is not None and scene.reference_layer.scene() is scene
    finally:
        _close(window)


def test_the_empty_board_names_the_key_that_really_opens_the_schematic() -> None:
    """It said Ctrl+5, which is the Parts panel, for as long as the panels have been
    numbered. A key written into prose is a second copy of the shortcut; this holds the two
    together."""
    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta

    stamp = "2026-01-01T00:00:00.000Z"
    window = _window_on(create_starter_document(DocumentMeta(name="t", created=stamp, modified=stamp)))

    key = window.act_show_schematic.shortcut().toString()
    assert key
    assert f"({key})" in window.view.empty_hint.text()
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


def _findings_root(window, key):
    """A group at the top of the findings -- "ERC", "DRC" or "LVS" -- by its key, not by
    where it is: ERC came in above the other two."""
    for i in range(window.drc_tree.topLevelItemCount()):
        root = window.drc_tree.topLevelItem(i)
        if root.data(0, _finding_key_role()) == key:
            return root
    raise AssertionError(f"no {key} group in the findings")


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

    # The row says what the rule is about; its id -- what was typed -- is in the tooltip.
    drc = _findings_root(window, "DRC")
    shown = {drc.child(j).toolTip(0) for j in range(drc.childCount())}
    assert shown == {wanted}
    _close(window)


def test_every_rule_and_every_lvs_finding_has_a_title_in_words() -> None:
    """The panel listed "component-body-overlap (error)". Read off the engine's own source
    and types, so a new rule without a title is a failure here rather than an id on screen."""
    import re
    from typing import get_args

    from perfboard_studio import drc, erc, lvs
    from perfboard_studio.ui.main import _erc_title, _lvs_title, _rule_title

    source = pathlib.Path(drc.__file__).read_text(encoding="utf-8")
    rules = set(re.findall(r'rule="([a-z0-9-]+)"', source))
    assert len(rules) > 20
    assert [rule for rule in sorted(rules) if _rule_title(rule) == rule] == []
    kinds = get_args(lvs.LvsIssueKind.__value__)
    assert kinds
    assert [kind for kind in kinds if _lvs_title(kind) == kind] == []
    assert [rule for rule in erc.RULES if _erc_title(rule) == rule] == []


def test_a_finding_row_says_what_is_wrong_and_keeps_the_rule_id() -> None:
    from perfboard_studio.ui.main import _rule_title

    window = _window_on(_load_dense())
    rule = sorted({v.rule for v in window._last_violations})[0]
    row = _drc_group(window, f"drc:{rule}")

    assert row.text(0).startswith(_rule_title(rule))
    assert rule not in row.text(0)
    assert row.toolTip(0) == rule
    _close(window)


def test_the_problems_bar_opens_the_list_it_counts() -> None:
    """"DRC 3 err" in the corner said something was wrong and gave no way to find out
    what, and the list itself stood 200 px tall under the board with four rows on a clean
    one. The list folds to its bar now: a click on the bar -- or Ctrl+7 -- opens it, and
    folds it again, and folded it takes no more than the bar's height from the views."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.problems import BAR_HEIGHT

    window = _window_on(_load_dense())
    window.show()
    try:
        bar = window.problems_bar
        assert window.dock_drc.titleBarWidget() is bar
        assert not bar.expanded and window.drc_panel.maximumHeight() == 0
        assert window.dock_drc.maximumHeight() == BAR_HEIGHT

        def click() -> None:
            release = QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(200, 10),
                QPointF(200, 10),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(bar, release)
            QApplication.processEvents()

        click()
        assert bar.expanded and window.drc_panel.maximumHeight() > BAR_HEIGHT
        assert window.act_drc_panel.isChecked()
        click()
        assert not bar.expanded
        window.act_drc_panel.trigger()  # Ctrl+7
        assert bar.expanded
        assert window.act_drc_panel.shortcut().toString() == "Ctrl+7"
        # Nothing on the bar is a timing: that is for whoever is tuning DRC.
        import re

        assert not re.search(r"\d\s*ms", bar.facts.text() + bar.title.text())
    finally:
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
    """...and a pin waiting for its wiring, which the bar does not count while there are
    connections left to route, is dimmed in the tree, as the bar dims those connections."""
    from perfboard_studio.ratsnest import summarize
    from perfboard_studio.ui.main import UNWIRED_RULES
    from perfboard_studio.ui.theme import ERROR, TEXT_DIM, WARNING

    window = _window_on(_load_dense())
    root = _findings_root(window, "DRC")
    by_rule = {v.rule: v.severity for v in window._last_violations}
    wiring = summarize(window._last_ratsnest).links > 0

    from perfboard_studio.guide import is_bench_check

    bench = {v.rule for v in window._last_violations if is_bench_check(v)}
    for j in range(root.childCount()):
        item = root.child(j)
        rule = item.toolTip(0)  # the row is in words; the rule's id is its tooltip
        expected = ERROR if by_rule[rule] == "error" else WARNING
        if wiring and rule in UNWIRED_RULES:
            expected = TEXT_DIM
        if rule in bench:  # counted apart on the bar, in its quiet colour (guide.is_bench_check)
            expected = TEXT_DIM
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

    assert "Paste" in labels and "Design the Board…" in labels
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

    assert len(bus.document.conductors) == 1, "the right-click should have finished the trace"
    assert scene.drawn_path == () and scene.armed_draw_kind == "solder-trace"
    assert scene.take_consumed_right_click() is True
    assert scene.take_consumed_right_click() is False, "the answer is spent once read"


def _press_at(pos: QPointF, button):
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    event = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    event.setScenePos(pos)
    event.setButton(button)
    return event


# ---------------------------------------------------------------------------
# What a click on the board picks
# ---------------------------------------------------------------------------


def _board_with(components=(), conductors=()) -> PerfDocument:
    return dataclasses.replace(
        _blank_document(), components=tuple(components), conductors=tuple(conductors)
    )


def _resistor(ref: str, anchor: HoleCoord) -> ComponentInstance:
    return ComponentInstance(
        id=f"c-{ref}", ref=ref, value="10k", footprint_id="r-axial-3", anchor=anchor
    )


def _shown_view(scene):
    from perfboard_studio.ui.view2d import BoardView

    view = BoardView(scene)
    view.resize(1200, 900)
    view.show()
    view.fitInView(scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
    QApplication.processEvents()
    return view


def _click(view, scene_pos: QPointF) -> None:
    from PySide6.QtTest import QTest

    QTest.mouseClick(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        view.mapFromScene(scene_pos),
    )


def _midpoint(conductor, board, side) -> QPointF:
    p, q = (hole_to_screen(h, board, side) for h in conductor.path)
    return QPointF((p.x() + q.x()) / 2, (p.y() + q.y()) / 2)


#: A bare wire on the solder side between R1's pins, under its body -- and one a row below,
#: outside the body and its courtyard but inside the hit area the part used to have.
_UNDER = WireConductor(
    id="under", path=(HoleCoord(6, 8), HoleCoord(7, 8)), kind="bare-wire", side="bottom"
)
_BESIDE = WireConductor(
    id="beside", path=(HoleCoord(6, 9), HoleCoord(7, 9)), kind="bare-wire", side="bottom"
)


@pytest.mark.parametrize("side", ["top", "bottom"])
def test_each_of_three_parts_two_rows_apart_is_picked_by_a_click_on_its_own_body(side) -> None:
    """A part's hit area was its padded courtyard and a strip for a reference label it no
    longer paints -- 13 mm tall on a 2 mm resistor -- so with three of them two rows apart a
    click on R1's body selected R2, and one on R2's selected R3. Pin 1 is in it too: an axial
    part's leads stand outside its body, and a part is dragged from pin 1."""
    doc = _board_with(_resistor(f"R{i}", HoleCoord(5, 6 + 2 * i)) for i in (1, 2, 3))
    scene = BoardScene(doc, footprint_lookup(), side=side)
    view = _shown_view(scene)
    try:
        for comp in doc.components:
            pin_1 = hole_to_screen(comp.anchor, doc.board, side)
            pin_2 = hole_to_screen(HoleCoord(comp.anchor.col + 3, comp.anchor.row), doc.board, side)
            body = QPointF((pin_1.x() + pin_2.x()) / 2, pin_1.y())
            scene.clearSelection()
            _click(view, body)
            assert scene.selected_component_ids() == (comp.id,), comp.ref
            assert scene.component_at(body) is scene.component_items[comp.id]
            scene.clearSelection()
            _click(view, pin_1)
            assert scene.selected_component_ids() == (comp.id,), f"{comp.ref} by pin 1"
    finally:
        view.close()


def test_a_click_on_a_printed_reference_picks_its_part_at_any_zoom_it_is_printed_at() -> None:
    """The hit area lost the strip that once stood for the reference, and with it the most
    obvious thing to click on a crowded board: the name. The plate is measured as the layer
    prints it, so it follows the zoom -- and where no name is printed there is none to hit."""
    from perfboard_studio.ui.view2d import (
        REF_LABEL_ALIGN,
        REF_LABEL_OFFSET,
        REF_LABEL_PX,
        label_plate_rect,
    )

    doc = _board_with([_resistor("R1", HoleCoord(5, 8))])
    scene = BoardScene(doc, footprint_lookup())
    view = _shown_view(scene)
    item = scene.component_items["c-R1"]
    try:
        for zoom in (4.0, 9.0, 25.0):
            view.resetTransform()
            view.scale(zoom, zoom)
            view.centerOn(item.reference_anchor())
            QApplication.processEvents()
            transform = view.transform()
            plate = label_plate_rect(
                transform.map(item.reference_anchor()), "R1", REF_LABEL_PX,
                REF_LABEL_ALIGN, bold=True, offset=REF_LABEL_OFFSET,
            )
            on_label = transform.inverted()[0].map(plate.center())
            above = transform.inverted()[0].map(QPointF(plate.center().x(), plate.top() - 4))
            assert item.shape().contains(item.mapFromScene(on_label))
            assert not item._hit_shape.contains(item.mapFromScene(on_label)), "not the body"

            scene.clearSelection()
            _click(view, on_label)
            assert scene.selected_component_ids() == ("c-R1",), zoom
            scene.clearSelection()
            _click(view, above)
            assert scene.selected_component_ids() == (), zoom

        view.resetTransform()
        view.scale(2.0, 2.0)  # Too far out for a name to be printed.
        QApplication.processEvents()
        assert item.shape().boundingRect() == item._hit_shape.boundingRect()
    finally:
        view.close()


def test_copper_on_the_face_being_looked_at_is_drawn_over_the_parts() -> None:
    """From the solder side the parts are only shadows of what stands on the other face, and
    the copper is what is being worked on. It sat under the parts from both faces."""
    jumper = WireConductor(
        id="jumper", path=(HoleCoord(2, 2), HoleCoord(2, 6)), kind="top-jumper", side="top"
    )
    doc = _board_with([_resistor("R1", HoleCoord(5, 8))], [_UNDER, jumper])
    for side in ("top", "bottom"):
        scene = BoardScene(doc, footprint_lookup(), side=side)
        part = scene.component_items["c-R1"].zValue()
        for item in scene.conductor_items.values():
            if item.conductor.side == side:
                assert item.zValue() > part, (side, item.conductor.id)
            else:
                assert item.zValue() < part, (side, item.conductor.id)
        # A lead comes up THROUGH its joint, so from the solder side the lead ends -- pin 1
        # among them -- are painted over the copper, not under the fillets landing on them.
        layer = scene.lead_ends_layer
        if side == "bottom":
            assert layer is not None
            assert all(layer.zValue() > c.zValue() for c in scene.conductor_items.values())
            assert layer.acceptedMouseButtons() == Qt.MouseButton.NoButton
        else:
            assert layer is None


def test_solder_side_copper_under_a_part_is_picked_from_the_solder_side() -> None:
    """On the shipped examples most of the solder-side copper could not be clicked from
    either face: it lay under some part's hit area, and parts were drawn over it. From the
    component side the part does stand over the run beneath it, so that click is the part's
    -- but the run beside it is the run's from both faces."""
    doc = _board_with([_resistor("R1", HoleCoord(5, 8))], [_UNDER, _BESIDE])
    board = doc.board

    bottom = BoardScene(doc, footprint_lookup(), side="bottom")
    view = _shown_view(bottom)
    try:
        for conductor in (_UNDER, _BESIDE):
            bottom.clearSelection()
            _click(view, _midpoint(conductor, board, "bottom"))
            assert bottom.selected_conductor_ids() == (conductor.id,), conductor.id
        # Off the copper, the part is still the part.
        bottom.clearSelection()
        _click(view, hole_to_screen(HoleCoord(5, 8), board, "bottom"))
        assert bottom.selected_component_ids() == ("c-R1",)
    finally:
        view.close()

    top = BoardScene(doc, footprint_lookup(), side="top")
    view = _shown_view(top)
    try:
        _click(view, _midpoint(_UNDER, board, "top"))
        assert top.selected_component_ids() == ("c-R1",)
        top.clearSelection()
        _click(view, _midpoint(_BESIDE, board, "top"))
        assert top.selected_conductor_ids() == ("beside",)
    finally:
        view.close()


def test_a_right_click_on_copper_drawn_over_a_part_is_about_the_copper() -> None:
    """The menu follows the click. It asked for the part first wherever the part's outline
    reached, so a right-click on a run from the solder side offered to rotate the resistor
    on the other face rather than to delete the run under the pointer."""
    window = _window_on(_board_with([_resistor("R1", HoleCoord(5, 8))], [_UNDER]))
    try:
        window.on_flip_board()
        board = window.bus.document.board
        # Zoomed in, so a scene point survives the round trip through whole pixels.
        window.view.resetTransform()
        window.view.scale(20.0, 20.0)

        menu = window.board_menu(window.view.mapFromScene(_midpoint(_UNDER, board, "bottom")))
        assert window.scene.selected_conductor_ids() == ("under",)
        assert window.scene.selected_component_ids() == ()
        assert window.act_delete in menu.actions()
        assert window.act_properties not in menu.actions()

        pin_1 = hole_to_screen(HoleCoord(5, 8), board, "bottom")
        menu = window.board_menu(window.view.mapFromScene(pin_1))
        assert window.scene.selected_component_ids() == ("c-R1",)
        assert window.act_properties in menu.actions()
    finally:
        _close(window)


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

    window = _window_on(_unpowered_555())
    window._copy_all_findings()
    assert QApp.clipboard().text().startswith(
        "erc error supply-unconnected: U1 pin 8 (VCC) is connected to nothing"
    )
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
    first.act_far_side.setChecked(False)
    first.act_values.setChecked(True)
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
    assert second.act_far_side.isChecked() is False
    assert second.scene.show_far_side is False
    assert second.act_values.isChecked() is True
    assert second.scene.show_values is True
    assert chosen_key() == "blue"
    assert second._routing_style == "solder"
    assert second.act_style["solder"].isChecked() is True
    _close(second)
    choose_colour(None)


def test_the_window_lays_wires_along_the_grid_and_remembers_when_it_should_not() -> None:
    """On in the window, off in the engine: the engine's default is what every golden route
    records, and square wires are what somebody building the board wants handed to them.
    It is how a wire is laid, not which primitive, so it reaches the "best" sweep too."""
    first = _window_on(_load_dense())
    assert first.act_grid_wires.isChecked()
    assert first._autoroute_options().router.wire_path == "grid"
    first.on_routing_style("best")
    assert first._autoroute_options().router.wire_path == "grid"

    first.act_grid_wires.setChecked(False)
    assert first._autoroute_options().router.wire_path == "straight"
    _close(first)

    second = _window_on(_load_dense())
    assert second.act_grid_wires.isChecked() is False
    assert second._autoroute_options().router.wire_path == "straight"
    _close(second)


def test_the_window_can_route_with_no_wire_at_all_and_remembers_it() -> None:
    """Route > Crossings. A short jumper over a crossing is the default, as it is in the
    engine; "never use wire" reaches every style and the "best" sweep, because like the
    wire path it is a judgement about the builder rather than part of a style."""
    first = _window_on(_load_dense())
    assert first.act_crossing["hop"].isChecked()
    assert first._autoroute_options().router.crossing_policy == "hop"

    first.act_crossing["refuse"].trigger()
    assert first.act_crossing["refuse"].isChecked()
    assert not first.act_crossing["hop"].isChecked()
    for style in ("solder", "best"):
        first.on_routing_style(style)
        assert first._autoroute_options().router.crossing_policy == "refuse"
    _close(first)

    second = _window_on(_load_dense())
    assert second.act_crossing["refuse"].isChecked()
    assert second._autoroute_options().router.crossing_policy == "refuse"
    _close(second)


def test_autorouting_from_the_window_lays_no_diagonal_wire() -> None:
    """End to end, through the same planner the Route menu runs."""
    from perfboard_studio.autoroute import plan_autoroute

    root = pathlib.Path(__file__).resolve().parents[1]
    document = persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    stripped = dataclasses.replace(document, conductors=())
    window = _window_on(stripped)

    plan = plan_autoroute(stripped, window.lookup, window._autoroute_options())

    wires = [c for c in plan.document.conductors if c.kind in ("bare-wire", "insulated-wire")]
    assert wires
    for conductor in wires:
        assert all(a.col == b.col or a.row == b.row for a, b in itertools.pairwise(conductor.path))
    _close(window)


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


def test_the_3d_panel_stops_painting_on_screen_only_where_that_hangs() -> None:
    """On macOS from Qt 6.10 a paint-on-screen VTK widget renders, is exposed by its own
    render, and renders again, and the window never answers. Showing it takes a real Cocoa
    window, which a suite on the offscreen platform never has, so the change is held to
    exactly where it was measured: every other setup keeps the panel it always drew."""
    from perfboard_studio.ui.main import vtk_paints_on_screen

    assert vtk_paints_on_screen("darwin", "6.9.3")
    for hangs in ("6.10.0", "6.11.1", "7.0.0"):
        assert not vtk_paints_on_screen("darwin", hangs)
    for platform in ("win32", "linux"):
        assert vtk_paints_on_screen(platform, "6.11.1")


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


def test_the_examples_open_as_untitled_copies() -> None:
    """Nothing in the window pointed at the boards that ship with it. They open UNTITLED:
    the file lives inside the application, and saving over it would change the example
    for everybody, or be lost with the folder a packaged build unpacks for one run."""
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.main import examples_dir

    folder = examples_dir()
    assert folder is not None and (folder / "ne555-astable.perf").is_file()
    window = _window_on(_load_dense())
    window._saved_document = window.bus.document  # nothing to offer to save
    names = [action.text() for action in window.menu_examples.actions()]
    assert "ne555-astable" in names

    window.on_open_example(folder / "ne555-astable.perf")
    QApplication.processEvents()

    assert window.current_path is None
    assert window.bus.document.components
    assert window.board_is_showing()
    assert not window.isWindowModified()
    _close(window)


def test_the_boards_tools_float_on_the_board() -> None:
    """They were a row of fifteen buttons across the window, wider than a laptop screen,
    that came and went with the board panel. They are on the board now: the pointer,
    Connect, two groups for the solder and the wire tools, Cut Strip and Measure down the
    left, and Show, Flip, zoom and Fit in the bottom-right corner. Each button IS its menu
    action, so a key, a menu and a button cannot disagree about what is armed."""
    from PySide6.QtWidgets import QToolBar

    window = _window_on(_load_dense())
    try:
        assert not {"viewsToolbar", "boardToolbar"} & {
            bar.objectName() for bar in window.findChildren(QToolBar)
        }
        assert window.board_tools.parent() is window.view
        assert window.board_view_tools.parent() is window.view
        on_tools = [button.defaultAction() for button in window.board_tools.buttons]
        assert on_tools[:2] == [window.act_select_tool, window.act_connect]
        assert window.act_measure in on_tools and window.act_cut in on_tools
        assert window.act_draw["solder-trace"] in on_tools
        assert window.act_draw["bare-wire"] in on_tools
        corner = [button.defaultAction() for button in window.board_view_tools.buttons]
        for action in (window.act_flip, window.act_zoom_in, window.act_zoom_out, window.act_fit):
            assert action in corner
        shown = window.board_view_tools.buttons[0].menu().actions()
        assert window.act_ratsnest in shown and window.act_values in shown
    finally:
        _close(window)


def test_tools_that_are_one_idea_share_a_button_that_shows_the_one_picked() -> None:
    """Five conductor buttons that differed only in what ran between two pads became two:
    solder, and wire. The button arms the tool it shows, offers the rest from its menu,
    and shows whichever was picked last -- by the menu, the key or the button."""
    window = _window_on(_load_dense())
    try:
        wires = window.wire_tools
        assert wires.group_menu.actions() == [
            window.act_draw["bare-wire"],
            window.act_draw["insulated-wire"],
            window.act_draw["top-jumper"],
        ]
        assert wires.defaultAction() is window.act_draw["bare-wire"]
        window.act_draw["insulated-wire"].trigger()
        assert wires.defaultAction() is window.act_draw["insulated-wire"]
        assert window.act_draw["insulated-wire"].isChecked()
        assert not window.act_select_tool.isChecked()
        window.on_stop_tool()
        assert window.act_select_tool.isChecked()
        assert window.act_draw["top-jumper"].shortcut().toString() == "J"
        solder = window.solder_tools.group_menu.actions()
        assert solder == [window.act_draw["solder-trace"], window.act_draw["solder-trace-wired"]]
    finally:
        _close(window)


def test_a_tool_the_board_cannot_take_leaves_the_board() -> None:
    """Cut Strip on a perfboard, solder on a solderless breadboard: a greyed button for a
    tool that cannot apply is clutter, not information. Cut Strip is there on a stripboard
    only; a group whose every tool is out goes; a group whose shown tool is out shows one
    that is in -- the insulated wire, on a breadboard, rather than a bare wire that is not
    a thing there."""
    example = _example_document("ne555-astable")
    window = _window_on(example)
    try:
        tools = window.board_tools
        assert not window.cut_tool.isVisibleTo(tools)
        for kind in ("solder-trace", "solder-trace-wired", "bare-wire"):
            window.act_draw[kind].setEnabled(False)
        assert not window.solder_tools.isVisibleTo(tools)
        assert window.wire_tools.isVisibleTo(tools)
        assert window.wire_tools.defaultAction() is window.act_draw["insulated-wire"]
        window.act_draw["solder-trace"].setEnabled(True)
        assert window.solder_tools.isVisibleTo(tools)
    finally:
        _close(window)

    strips = dataclasses.replace(
        example,
        board=dataclasses.replace(example.board, type="stripboard", strip_axis="horizontal"),
        conductors=(),
    )
    window = _window_on(strips)
    try:
        assert window.cut_tool.isVisibleTo(window.board_tools)
        assert window.cut_tool.defaultAction() is window.act_cut
    finally:
        _close(window)


def test_a_narrow_window_keeps_every_board_tool_on_screen() -> None:
    """At 1280 px the old toolbar's view switches went behind its overflow arrow, and it
    shed words to keep the rest. On the canvas every tool keeps its place at any width the
    window can be, and the side panels keep room for the names they list."""
    from PySide6.QtWidgets import QApplication

    window = _window_on(_load_dense())
    window.show()
    window.resize(1100, 700)
    for _ in range(10):
        QApplication.processEvents()
    for bar in (window.board_tools, window.board_view_tools):
        for button in bar.buttons:
            if button.defaultAction() is window.act_cut:
                continue  # a stripboard's tool, not on this board
            assert button.isVisibleTo(window), button.toolTip()
        assert window.view.rect().contains(bar.geometry())
    assert window.dock_nets.widget().minimumWidth() >= window.SIDE_PANEL_MIN_WIDTH
    assert window.dock_library.widget().minimumWidth() >= window.SIDE_PANEL_MIN_WIDTH
    _close(window)


def test_a_board_opened_after_a_blank_launch_comes_up_on_the_board(tmp_path) -> None:
    """A blank launch puts the schematic up, which is right for a design with nothing in
    it -- and nothing put the board back, so the first example anybody opened came up as
    its schematic, with the board behind a tab. Side by side, the board is simply there."""
    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.model import DocumentMeta

    stamp = "2026-01-01T00:00:00.000Z"
    window = _window_on(create_starter_document(DocumentMeta(name="t", created=stamp, modified=stamp)))
    window._open_the_schematic_on_an_empty_design()
    assert window.schematic_is_showing()
    board = tmp_path / "board.perf"
    board.write_text(GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")

    window._load_path(board)

    assert window.board_is_showing()
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
    assert flat["Auto-wire Everything"] == "Ctrl+R"
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

    gestures = dict((keys, what) for keys, what in ShortcutsDialog.board_gestures())

    assert "Middle-drag" in gestures
    assert "Esc" in gestures
    assert "Arrow keys" in gestures


def test_the_board_gestures_are_said_in_the_windows_language() -> None:
    """They were a table built when the module loaded, before any language was chosen, so
    the Turkish card listed every gesture in English under a Turkish heading."""
    from perfboard_studio.ui.i18n import set_language
    from perfboard_studio.ui.main import ShortcutsDialog

    english = ShortcutsDialog.board_gestures()
    set_language("tr")
    try:
        turkish = ShortcutsDialog.board_gestures()
    finally:
        set_language("en")
    assert all(said != meant for (_, said), (_, meant) in zip(turkish, english, strict=True))


def test_a_filter_finds_a_turkish_word_whatever_its_i() -> None:
    """``str.lower`` keeps a combining dot on "İ" and makes "I" an ordinary i, so typing
    "iletken" never found "İletkenler kesişiyor" and "ısı" never found "Isı kaynağı"."""
    from perfboard_studio.ui.main import _folded

    assert _folded("iletken") in _folded("İletkenler kesişiyor")
    assert _folded("ısı") in _folded("Isı kaynağı fazla yakın")
    assert _folded("insulated") in _folded("INSULATED wire")


def test_each_language_is_offered_by_its_own_name() -> None:
    """The menu said "İngilizce" in Turkish: somebody who cannot read the language the
    window is in has to find the one they can by its own name."""
    window = _window_on(_load_dense())
    try:
        assert window.act_language["en"].text() == "English"
        assert window.act_language["tr"].text() == "Türkçe"
    finally:
        _close(window)


def test_auto_place_on_a_design_with_nothing_placed_points_at_place_on_the_board() -> None:
    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        window.on_autoplace()
        message = window.statusBar().currentMessage()
        assert "Place on the Board" in message and "empty" not in message
    finally:
        _close(window)


def test_next_step_on_a_guide_with_no_steps_does_not_say_every_step_is_done() -> None:
    window = _blank_window()
    try:
        window.on_next_step_to_do()
        assert "Every step is done" not in window.statusBar().currentMessage()
    finally:
        _close(window)


def test_the_boards_features_offer_only_what_the_board_can_take() -> None:
    from perfboard_studio.breadboard import breadboard

    window = _window_on(dataclasses.replace(_blank_document(), board=breadboard("400")))
    try:
        features = _board_features(window)
        assert not features.add_corners.isEnabled()
        assert not features.add_connector.isEnabled()
    finally:
        _close(window)

    narrow = dataclasses.replace(_blank_document().board, cols=5)
    window = _window_on(dataclasses.replace(_blank_document(), board=narrow))
    try:
        features = _board_features(window)
        features.edge.setCurrentIndex(features.edge.findData("bottom"))
        assert features.finger_count.maximum() <= 5
    finally:
        _close(window)


def test_a_catalog_parts_holding_note_is_said_in_the_windows_language() -> None:
    """The citation is a name and stays one; the note after it is the one instruction on the
    line -- which leg is which -- and it was English under a Turkish summary."""
    from perfboard_studio.catalog import CATALOG
    from perfboard_studio.ui.i18n import set_language
    from perfboard_studio.ui.main import _source_said

    part = next(p for p in CATALOG if p.id == "bc547")
    set_language("tr")
    try:
        said = _source_said(part.source)
    finally:
        set_language("en")
    citation = part.source.split("; ")[0]
    assert said.startswith(citation + "; ") and "flat face" not in said
    assert _source_said(part.source) == part.source


def test_a_status_message_cut_short_is_whole_on_hover() -> None:
    window = _window_on(_load_dense())
    try:
        message = "55 connections wired, 13 needed an insulated wire, 1 pad to measure"
        window.statusBar().showMessage(message)
        assert window.statusBar().toolTip() == message
    finally:
        _close(window)


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


def test_every_tool_on_the_board_has_a_picture_and_says_what_it_does() -> None:
    """A row of identical grey rectangles is one people read left to right every time,
    which is how the tools ended up being hunted for in the menus. On the board the buttons
    are pictures alone, so each one has its picture and says, on hover, what it does."""
    window = _window_on(_load_dense())
    try:
        buttons = [*window.board_tools.buttons, *window.board_view_tools.buttons]
        assert len(buttons) >= 10
        for button in buttons:
            action = button.defaultAction()
            assert not button.icon().isNull(), button.toolTip()
            said = (action.toolTip() if action is not None else "") or button.toolTip()
            assert said, f"{action.text() if action is not None else button} says nothing"
    finally:
        _close(window)


def test_the_boards_tools_are_on_screen_only_with_the_board(monkeypatch) -> None:
    """With the sheet in front, the old bar still offered five conductor tools and a
    Rotate that turned whatever was selected on the BOARD. The tools are the board's own
    now, so they are on screen exactly when it is -- and the menus and keys keep every one
    of them either way."""
    from PySide6.QtWidgets import QApplication

    window = _shown_window_without_3d(monkeypatch)
    try:
        window.show_board()
        _settle_events(QApplication)
        assert window.board_is_showing() and window.board_tools.isVisible()

        # Children of the board's own view: behind the sheet's tab, floated or closed,
        # they go where the board goes.
        assert window.board_tools.parent() is window.view
        window.show_schematic()
        _settle_events(QApplication)
        assert not window.board_is_showing()
        assert window.act_autoroute.isEnabled(), "the menu entry must still work"
        assert not window.header_strip.isHidden()

        window.act_board_panel.trigger()  # closed
        _settle_events(QApplication)
        assert not window.board_tools.isVisible()

        window.show_board()
        _settle_events(QApplication)
        assert window.board_tools.isVisible()
    finally:
        _close(window)


def test_opening_a_panel_in_the_other_group_leaves_this_one_in_front(monkeypatch) -> None:
    """Which panel was in front was once ONE variable for the whole window, which has more
    than one place a panel can stand. Opening the guide made it "the one in front", so the
    board, still showing in a tab group of its own, read as behind until somebody clicked
    the tab that was already open. Kept per group -- for a guide moved off by hand."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    window = _shown_window_without_3d(monkeypatch)
    try:
        # The guide out of the views' group, into the left column's.
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, window.dock_guide)
        window.tabifyDockWidget(window.dock_nets, window.dock_guide)
        window.show_board()
        _settle_events(QApplication)
        window.act_show_guide.trigger()
        _settle_events(QApplication)
        assert window.dock_guide not in window.tabifiedDockWidgets(window.dock_board)
        assert window.board_is_showing()

        window.show_schematic()
        window.act_show_guide.trigger()
        _settle_events(QApplication)
        assert window.schematic_is_showing()
        assert not window.board_is_showing()

        # Within a group, the one brought forward still puts the other behind.
        window.show_board()
        _settle_events(QApplication)
        assert window.board_is_showing() and not window.schematic_is_showing()
    finally:
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
    # The two axial archetypes are drawn by the polarity-aware path rather than the plain
    # table, because a resistor and a DO-41 diode share each and look nothing alike.
    assert declared - set(PART_DRAWINGS) == {"axial-cylinder", "axial-upright"}


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


def test_auto_wire_says_when_what_it_laid_is_on_the_face_not_in_view() -> None:
    """"3 connections wired" over a board that looked the same as before, because the
    wires went under it: the status line says where they are and how to see them."""
    from perfboard_studio.commands import AddConductorPayload, NewWireConductor

    window = _blank_window()
    try:
        assert window.scene.side == "top"
        assert window._far_side_note(set()) == ""
        assert window.bus.dispatch(
            "conductor.add",
            AddConductorPayload(
                conductor=NewWireConductor(path=(HoleCoord(1, 1), HoleCoord(4, 1)))
            ),
        ).ok
        note = window._far_side_note(set())
        assert "1 on the solder side" in note and "Ctrl+F" in note
        assert window._far_side_note({c.id for c in window.bus.document.conductors}) == ""
        window.on_flip_board()
        assert window._far_side_note(set()) == "", "seen from the solder side, it is in view"
    finally:
        _close(window)


def test_the_far_side_can_be_turned_off_but_not_what_is_being_looked_for() -> None:
    """On by default: Auto-wire lays its wires on the solder side, and a component side
    that hides them looks the same before and after it. Off, the far face is out of the way
    -- drawn nowhere and clicked nowhere -- except a wire selected or a net lit, which is
    somebody looking for exactly that copper."""
    doc = _load_dense()
    scene = BoardScene(doc, footprint_lookup(), side="top")
    assert scene.show_far_side is True
    far = [i for i in scene.conductor_items.values() if i.is_far_side()]
    near = [i for i in scene.conductor_items.values() if not i.is_far_side()]
    assert far and near
    assert not any(item.is_hidden_on_screen() for item in far)

    scene.set_show_far_side(False)

    far = [i for i in scene.conductor_items.values() if i.is_far_side()]
    near = [i for i in scene.conductor_items.values() if not i.is_far_side()]
    assert all(item.is_hidden_on_screen() and item.shape().isEmpty() for item in far)
    assert not any(item.is_hidden_on_screen() for item in near)
    far[0].set_net_lit(True)
    assert not far[0].is_hidden_on_screen()
    far[1].setSelected(True)
    assert not far[1].is_hidden_on_screen() and not far[1].shape().isEmpty()


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


def test_selecting_a_net_lights_its_copper_not_only_its_ratsnest() -> None:
    """On a finished board there is no ratsnest left, so choosing GND in the Nets panel
    changed nothing anybody could see. Judged by what the copper actually joins: a wire
    drawn by hand carries no net id, and it is lit if it lands on the net's pins."""
    from perfboard_studio.commands import AddConductorPayload, NewWireConductor
    from perfboard_studio.geometry import all_pin_holes

    root = pathlib.Path(__file__).resolve().parents[1]
    document = persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    window = _window_on(document)
    gnd = next(net for net in document.nets if net.name == "GND")
    node = gnd.nodes[0]
    part = next(c for c in document.components if c.ref == node.component_ref)
    footprint = footprint_lookup()(part.footprint_id)
    assert footprint is not None
    pin_hole = next(
        hole for pin, hole in all_pin_holes(part, footprint) if pin.number == node.pin
    )
    free = HoleCoord(pin_hole.col, document.board.rows - 1)
    assert window.bus.dispatch(
        "conductor.add",
        AddConductorPayload(conductor=NewWireConductor(path=(pin_hole, free), net_id=None)),
    ).ok
    drawn = window.bus.document.conductors[-1]
    assert drawn.net_id is None

    window.scene.set_highlighted_nets([gnd.id])

    lit = {cid for cid, item in window.scene.conductor_items.items() if item.net_lit}
    assert drawn.id in lit
    assert {c.id for c in window.bus.document.conductors if c.net_id == gnd.id} <= lit
    assert lit != set(window.scene.conductor_items), "every net lit up, not one"
    # A rebuild keeps it lit; clearing the selection puts it out.
    window.scene.set_document(window.bus.document)
    assert window.scene.conductor_items[drawn.id].net_lit
    window.scene.set_highlighted_nets([])
    assert not any(item.net_lit for item in window.scene.conductor_items.values())
    _close(window)


def test_far_side_copper_reads_as_a_band_not_just_hatch_strokes() -> None:
    """Hatch alone is thin strokes over a busy grid of pads, and zoomed out -- where
    somebody looks to see what joins what -- it thinned to nothing on the component side,
    which is the side the editor opens on. The screen draws a solid dimmed band with a dark
    edge: every pixel along the run is tinted."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter

    from perfboard_studio.commands import DEFAULT_BOARD

    wire = WireConductor(id="w", path=(HoleCoord(2, 3), HoleCoord(8, 3)), side="bottom")
    item = ConductorItem(wire, DEFAULT_BOARD, "top")
    assert item.is_far_side()

    pitch = DEFAULT_BOARD.pitch
    px_per_mm = 20
    image = QImage(int(12 * pitch * px_per_mm), int(7 * pitch * px_per_mm), QImage.Format.Format_ARGB32)
    image.fill(QColor("#2e6b3a"))
    painter = QPainter(image)
    painter.scale(px_per_mm, px_per_mm)
    item.paint(painter, None)
    painter.end()

    start = view2d.hole_to_screen(HoleCoord(2, 3), DEFAULT_BOARD, "top")
    end = view2d.hole_to_screen(HoleCoord(8, 3), DEFAULT_BOARD, "top")
    samples = [
        QPointF(start.x() + (end.x() - start.x()) * f / 100, start.y())
        for f in range(15, 86)  # between the two end joints, along the centreline
    ]
    background = QColor("#2e6b3a").rgb()
    tinted = sum(
        image.pixel(int(p.x() * px_per_mm), int(p.y() * px_per_mm)) != background for p in samples
    )
    assert tinted / len(samples) > 0.95


def test_a_bent_wired_run_on_the_far_face_is_a_line_not_a_filled_triangle() -> None:
    """The far face's joints are drawn with a brush, and the wired run's spine core was
    stroked after them with that brush still set: Qt closed the bent spine and filled it,
    and a wired run turning a corner on the far face became a solid triangle across every
    hole inside the bend."""
    from PySide6.QtGui import QColor, QImage, QPainter

    from perfboard_studio.commands import DEFAULT_BOARD

    path = tuple(HoleCoord(c, 3) for c in range(2, 7)) + tuple(
        HoleCoord(6, r) for r in range(4, 8)
    )
    run = SolderTraceConductor(id="t", path=path, kind="solder-trace-wired", side="bottom")
    item = ConductorItem(run, DEFAULT_BOARD, "top")
    assert item.is_far_side()

    px_per_mm = 20
    pitch = DEFAULT_BOARD.pitch
    image = QImage(int(12 * pitch * px_per_mm), int(11 * pitch * px_per_mm), QImage.Format.Format_ARGB32)
    image.fill(QColor("#2e6b3a"))
    painter = QPainter(image)
    painter.scale(px_per_mm, px_per_mm)
    item.paint(painter, None)
    painter.end()

    # Inside the bend: a pitch and a half from the run's first leg, a pitch from its second.
    a = view2d.hole_to_screen(HoleCoord(5, 4), DEFAULT_BOARD, "top")
    b = view2d.hole_to_screen(HoleCoord(5, 5), DEFAULT_BOARD, "top")
    inside = ((a.x() + b.x()) / 2 * px_per_mm, (a.y() + b.y()) / 2 * px_per_mm)
    assert image.pixel(int(inside[0]), int(inside[1])) == QColor("#2e6b3a").rgb()
    # ...and the run itself is still drawn, on its corner.
    corner = view2d.hole_to_screen(HoleCoord(6, 3), DEFAULT_BOARD, "top")
    assert image.pixel(int(corner.x() * px_per_mm), int(corner.y() * px_per_mm)) != (
        QColor("#2e6b3a").rgb()
    )


def _board_with_a_via() -> PerfDocument:
    """A run on the component side from C4 to E4, and a wire on the solder side from E4 to
    E8: E4 is a via, C4 is a plain end."""
    from perfboard_studio.commands import create_empty_document
    from perfboard_studio.model import DocumentMeta, has_component_side_copper

    doc = create_empty_document(DocumentMeta(name="via", created="", modified=""))
    assert has_component_side_copper(doc.board)
    run = SolderTraceConductor(
        id="t", path=tuple(HoleCoord(c, 3) for c in range(2, 5)), side="top"
    )
    wire = WireConductor(id="w", path=(HoleCoord(4, 3), HoleCoord(4, 7)), side="bottom")
    return dataclasses.replace(doc, conductors=(run, wire))


@pytest.mark.parametrize("side", ["top", "bottom"])
def test_a_via_is_marked_in_2d_from_either_face_and_a_plain_end_is_not(side: str) -> None:
    doc = _board_with_a_via()
    scene = BoardScene(doc, lambda _f: None, side=side)  # type: ignore[arg-type]
    assert [mark.hole for mark in scene.via_items] == [HoleCoord(4, 3)]
    assert scene.via_items[0].pos() == view2d.hole_to_screen(HoleCoord(4, 3), doc.board, side)

    # The ring is drawn where the via is: amber on its circle, in both views.
    px_per_mm = 12
    image = _render_scene(scene, px_per_mm)
    rect = scene.sceneRect()
    centre = view2d.hole_to_screen(HoleCoord(4, 3), doc.board, side)

    def at(dx: float, dy: float):  # -> QColor
        x = (centre.x() + dx - rect.x()) * px_per_mm
        y = (centre.y() + dy - rect.y()) * px_per_mm
        return image.pixelColor(int(x), int(y))

    ring = at(0, -view2d.VIA_RING_RADIUS_MM)
    assert abs(ring.red() - 0xD9) < 40 and abs(ring.blue() - 0x2B) < 50, ring.name()
    dot = at(0, 0)
    assert dot.lightness() > 200, dot.name()

    # A run with no other copper at its end, and a wire on one face, are no via.
    plain = dataclasses.replace(doc, conductors=doc.conductors[:1])
    assert BoardScene(plain, lambda _f: None, side=side).via_items == []  # type: ignore[arg-type]


def test_the_1to1_sheet_has_no_via_marks_and_both_printers_build_it_one_way() -> None:
    import inspect

    from perfboard_studio.ui import headless
    from perfboard_studio.ui.main import MainWindow

    doc = _board_with_a_via()
    for side in ("top", "bottom"):
        sheet = view2d.print_scene(doc, lambda _f: None, side)  # type: ignore[arg-type]
        assert sheet.via_items == [] and not sheet.show_ratsnest and not sheet.show_rulers

    window = MainWindow(doc)
    try:
        assert window.scene.via_items, "the screen marks the via"
        assert window._export_scene(doc, "top").via_items == []
    finally:
        window._saved_document = window.bus.system_document
        window.close()
    # The headless sheets come from the same function, not a second list of options.
    source = inspect.getsource(headless)
    assert source.count("print_scene(doc, lookup,") == 2
    assert "show_ratsnest=False" not in source


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


@pytest.mark.skipif(
    QApplication.instance() is not None
    and QApplication.instance().platformName() == "offscreen"  # type: ignore[union-attr]
    and sys.platform == "win32",
    reason="Qt's offscreen plugin ships no font database on Windows; see "
    "main._default_headless_platform",
)
@pytest.mark.parametrize(
    ("kind", "anchor", "right", "above"),
    [
        ("net", "left", True, True),  # a net name starts at its point, which is its baseline
        ("ref", "centre", None, True),  # a reference sits above its point
        ("value", "centre", None, False),  # a value below it
        ("pin", "left", True, None),  # a pin number beside its lead, centred on the point
        ("pin", "right", False, None),
    ],
)
def test_the_panel_puts_a_label_where_the_export_does(
    kind: str, anchor: str, right: bool | None, above: bool | None
) -> None:
    """The panel read ``Label.anchor`` as Qt words, but ``draw_label`` aligns inside a box
    centred on the point, so every label came out in the opposite quadrant from the one the
    layout kept clear and the export draws in: net names over the wires, "XTAL1" hanging off
    the sheet's left edge. Measured on the pixels, where the text actually lands."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    from perfboard_studio.model import Point2
    from perfboard_studio.schematic import Label
    from perfboard_studio.ui.scenetext import draw_label
    from perfboard_studio.ui.viewsch import label_alignment

    label = Label(text="XTAL1", at=Point2(x=0.0, y=0.0), kind=kind, anchor=anchor)
    image = QImage(400, 400, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QPen(QColor("black")))
    draw_label(painter, QPointF(200, 200), label.text, 20, label_alignment(label))
    painter.end()
    xs = [x for y in range(400) for x in range(400) if image.pixelColor(x, y).red() < 128]
    ys = [y for y in range(400) for x in range(400) if image.pixelColor(x, y).red() < 128]
    assert xs, "no text reached the pixels"

    if right is True:
        assert min(xs) >= 197
    elif right is False:
        assert max(xs) <= 203
    else:
        assert min(xs) < 200 < max(xs)
    if above is True:
        assert max(ys) <= 203
    elif above is False:
        assert min(ys) >= 197
    else:
        assert min(ys) < 200 < max(ys)


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


def test_moving_a_symbol_keeps_the_wires_on_the_sheet_and_one_undo_takes_them_back() -> None:
    """The report was "moving a part on the schematic cuts every connection". It did not
    touch the netlist, but it took every wire off the page: the first move froze the sheet,
    and a frozen sheet draws only the wires somebody drew. The freeze now keeps them, in
    the same command -- so one undo puts the sheet back to the layout, wires and all."""
    from pathlib import Path

    from perfboard_studio.persist import deserialize_document

    doc = deserialize_document(
        (Path(__file__).resolve().parents[1] / "examples" / "lm317-supply.perf").read_text(
            encoding="utf-8"
        )
    ).document
    window = _open_schematic(doc)
    window._refresh_schematic_panel()
    before = window.schematic_view.item.drawing
    derived_wires = len([w for w in before.wires if len(w.path) > 1])
    symbol = before.symbols[0]

    _move_symbol(window, symbol.ref, symbol.at.x + 5.08, symbol.at.y)

    after = window.schematic_view.item.drawing
    assert window.bus.document.sheet_wires, "the freeze kept the drawing's wires"
    assert window.bus.document.nets == doc.nets
    assert all(wire.ends is not None for wire in after.wires), "no pin turned into a label"
    assert derived_wires > 0
    window.bus.undo()
    assert not window.bus.document.sheet and not window.bus.document.sheet_wires
    _close(window)


def test_a_symbol_dragged_onto_the_board_places_that_one_part(monkeypatch) -> None:
    """The other half of "Place on the Board": that button moves the WHOLE design, and
    until now there was no way to put down one part from the sheet at all -- double-clicking
    a symbol opened its properties."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    _keep_the_board(window, monkeypatch)
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")

    window._on_part_dropped("R1", HoleCoord(5, 5))

    placed = {c.ref: c.anchor for c in window.bus.document.components}
    assert placed == {"R1": HoleCoord(5, 5)}
    assert [p.ref for p in window.bus.document.parts] == ["R2"]
    _close(window)


def test_dragging_a_symbol_whose_part_is_already_down_moves_it(monkeypatch) -> None:
    """Two commands behind one gesture, and which one it is depends on which list the part
    is in -- the same split Remove already makes. Dragging a symbol whose part is already
    on the board can only mean "put it here instead"."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    _keep_the_board(window, monkeypatch)
    _add(window, "R1", "r-axial-3")
    window._on_part_dropped("R1", HoleCoord(4, 4))

    window._on_part_dropped("R1", HoleCoord(9, 7))

    assert window.bus.document.parts == ()
    assert [c.anchor for c in window.bus.document.components] == [HoleCoord(9, 7)]
    _close(window)


def test_a_drop_the_board_refuses_says_so_rather_than_half_placing(monkeypatch) -> None:
    """The command checks the hole, not the view: a second opinion in the view is a second
    thing to keep in step with what the bus actually allows."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    _keep_the_board(window, monkeypatch)
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


def _drag_over_board(window, fmt: str, payload: str, hole):
    """A drag moving over the board with ``payload`` on board hole ``hole``, as Qt delivers
    one: the view's own handler, handed the event."""
    from PySide6.QtCore import QMimeData, Qt
    from PySide6.QtGui import QDragMoveEvent

    from perfboard_studio.ui.view2d import hole_to_screen

    data = QMimeData()
    data.setData(fmt, payload.encode("utf-8"))
    data.setText(payload)
    scene = window.scene
    point = window.view.mapFromScene(hole_to_screen(hole, scene.document.board, scene.side))
    event = QDragMoveEvent(
        point, Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.view.dragMoveEvent(event)
    return scene._drop_ghost


def test_a_part_dragged_over_the_board_is_drawn_where_it_will_land() -> None:
    """The report was "its shadow on the board does not look right". There was none: a drop
    showed only the list's icon, at a fixed size and CENTRED on the pointer, while the drop
    puts the part's first pin in the hole under it -- so the picture was neither where the
    part landed nor its size. Now the ghost a part picked from the list gets is drawn there,
    red where it cannot go."""
    from perfboard_studio.model import HoleCoord
    from perfboard_studio.ui.view2d import FOOTPRINT_MIME

    window = _blank_window()
    ghost = _drag_over_board(window, FOOTPRINT_MIME, "dip-8", HoleCoord(6, 4))
    assert ghost is not None
    assert ghost.anchor == HoleCoord(6, 4), "pin 1 in the hole under the pointer, as a drop"
    assert not ghost.blocked
    window._on_footprint_dropped("dip-8", HoleCoord(6, 4))

    blocked = _drag_over_board(window, FOOTPRINT_MIME, "dip-8", HoleCoord(6, 4))
    assert blocked is not None and blocked.blocked, "red over a part already there"
    window.scene.clear_drop_ghost()
    assert window.scene._drop_ghost is None
    _close(window)


def test_a_placed_part_dragged_from_the_sheet_is_ghosted_the_way_round_it_is() -> None:
    """A part already on the board keeps its orientation when it is dragged back onto it
    (``component.move``), so its ghost is turned as it is -- and its own holes are not in
    its way."""
    from pathlib import Path

    from perfboard_studio.persist import deserialize_document
    from perfboard_studio.ui.view2d import PART_MIME

    doc = deserialize_document(
        (Path(__file__).resolve().parents[1] / "examples" / "nano-relay.perf").read_text(
            encoding="utf-8"
        )
    ).document
    turned = next((c for c in doc.components if c.rotation), None)
    assert turned is not None, "the example no longer turns any part"
    window = _window_on(doc)

    ghost = _drag_over_board(window, PART_MIME, turned.ref, turned.anchor)
    assert ghost is not None
    assert (ghost.part_rotation, ghost.part_mirrored) == (int(turned.rotation), turned.mirrored)
    assert not ghost.blocked, "a part is not in its own way"
    _close(window)


def test_a_dragged_picture_travels_beside_the_pointer() -> None:
    """Under the pointer it covered the holes the drop was aimed at, and the ghost too."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPixmap

    from perfboard_studio.ui.view2d import DRAG_PICTURE_OFFSET_PX, picture_beside_the_pointer

    picture = QPixmap(40, 30)
    picture.fill(QColor("#ff0000"))
    carried = picture_beside_the_pointer(picture).toImage()
    assert (carried.width(), carried.height()) == (40 + DRAG_PICTURE_OFFSET_PX, 30 + DRAG_PICTURE_OFFSET_PX)
    assert carried.pixelColor(0, 0).alpha() == 0, "nothing at the hot spot"
    assert carried.pixelColor(DRAG_PICTURE_OFFSET_PX + 5, DRAG_PICTURE_OFFSET_PX + 5) == QColor(
        Qt.GlobalColor.red
    )


def test_a_footprint_dropped_on_the_board_places_that_part() -> None:
    """Dragging is what everybody tries first and it did nothing at all: the only way to
    put a part down was to pick it in the list and then click the board."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    window.placing_value.setText("10k")

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


def test_the_board_and_the_sheet_are_both_panels(monkeypatch) -> None:
    """They were a central widget and a tab beside it -- the one pair in the window that
    could not be arranged. Tabbed, side by side, floated or closed is a drag now, and Qt
    remembers wherever it was left. They open as tabs, the board in front."""
    from PySide6.QtWidgets import QApplication

    window = _shown_window_without_3d(monkeypatch)

    # The Board panel holds the strip of boards over the view; on one board the strip is
    # hidden, so the panel is the view as it always was.
    assert window.dock_board.isAncestorOf(window.view) and window.board_strip.isHidden()
    assert window.dock_schematic.widget() is window.schematic_page
    assert window.board_is_showing()
    assert not window.dock_schematic.isHidden() and window.schematic_is_showing() is False

    window.show_schematic()
    _settle_events(QApplication)
    assert window.dock_schematic in window.tabifiedDockWidgets(window.dock_board)
    assert window.schematic_is_showing() and not window.board_is_showing()
    _close(window)


def test_the_views_are_tabs_over_the_canvas_and_side_by_side_is_a_drag(monkeypatch) -> None:
    """Board, sheet, 3D and guide open as tabs on top of the canvas, every one with its tab
    from the first start, the board in front: side by side, a second view cost the board
    half its width. Pulled beside the board, a view still shares the middle evenly."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QTabWidget

    window = _shown_window_without_3d(monkeypatch)
    width = window.width()
    group = set(window.tabifiedDockWidgets(window.dock_board))
    assert group == {window.dock_schematic, window.dock_3d, window.dock_guide}
    assert all(not dock.isHidden() for dock in window._view_docks())
    assert window.tabPosition(Qt.DockWidgetArea.RightDockWidgetArea) == QTabWidget.TabPosition.North
    assert window.board_is_showing()

    window.act_show_3d.trigger()
    _settle_events(QApplication)
    assert not window.board_is_showing()
    assert window.width() == width

    # Beside the board, by hand: the row shares itself out.
    window.removeDockWidget(window.dock_schematic)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, window.dock_schematic)
    window.splitDockWidget(window.dock_drc, window.dock_schematic, Qt.Orientation.Horizontal)
    window.dock_schematic.show()
    window.show_board()
    _settle_events(QApplication)
    window._share_the_middle()
    _settle_events(QApplication)
    assert window.board_is_showing() and window.schematic_is_showing()
    assert window.width() == width
    _close(window)


def _shown_window_without_3d(monkeypatch, width: int = 1600):
    """A window on screen -- Qt counts a panel into a tab group only once it is -- with the
    3D panel's contents stubbed, because a shown 3D panel builds VTK's pipeline."""
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.main import MainWindow

    monkeypatch.setattr(MainWindow, "_create_3d_widget", lambda self: None)
    window = _window_on(_golden_document("ne555"))
    window.resize(width, 950)
    window.show()
    _settle_events(QApplication)
    return window


def _settle_events(application, rounds: int = 25) -> None:
    for _ in range(rounds):
        application.processEvents()


def _the_views_stand_in_a_row(window) -> bool:
    views = [dock for dock in window._views() if not dock.isHidden()]
    if any(other in views for dock in views for other in window.tabifiedDockWidgets(dock)):
        return False
    xs = [dock.x() for dock in views]
    return xs == sorted(xs) and len(set(xs)) == len(xs)


def test_resetting_the_layout_on_screen_builds_no_3d(monkeypatch) -> None:
    """Every view joins the tab group on Reset the Panel Layout, and on its way in the 3D
    view passed through "in front" -- which, in a window on screen, built VTK's whole
    pipeline for a board nobody had asked to see in 3D, and offscreen aborted the process.
    The board ends in front, and the 3D view is built when it is clicked."""
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.main import MainWindow

    built: list[bool] = []
    monkeypatch.setattr(MainWindow, "_create_3d_widget", lambda self: built.append(True))
    window = _window_on(_golden_document("ne555"))
    try:
        window.resize(1600, 950)
        window.show()
        _settle_events(QApplication)
        window.on_reset_layout()
        _settle_events(QApplication)
        assert built == []
        assert window.board_is_showing()
        assert window.dock_3d in window.tabifiedDockWidgets(window.dock_board)
    finally:
        _close(window)


def test_every_view_open_does_not_grow_the_window(monkeypatch) -> None:
    """Room for a view is ASKED of its neighbours, never demanded: held at its width while
    three views stood beside it, the guide pushed a 1600 px window out to 2110. As tabs
    they share one place, and opening each in turn leaves the window as it was."""
    from PySide6.QtWidgets import QApplication

    window = _shown_window_without_3d(monkeypatch)
    for action in (window.act_show_schematic, window.act_show_3d, window.act_show_guide):
        action.trigger()
        _settle_events(QApplication)
        assert window.width() == 1600
    assert window.dock_guide.width() >= window.PANEL_OPEN_MIN_WIDTH
    _close(window)


def test_a_panel_that_opens_as_a_strip_is_given_room() -> None:
    """Shut on start, the guide was never given the opening proportions, and Qt opened it
    as narrow as it would go: every step cut to its first few letters."""
    from PySide6.QtWidgets import QApplication

    window = _window_on(_golden_document("ne555"))
    window.resize(1600, 950)
    window.show()
    for _ in range(10):
        QApplication.processEvents()

    window.act_show_guide.trigger()
    for _ in range(20):
        QApplication.processEvents()

    assert window.dock_guide.width() >= window.PANEL_OPEN_MIN_WIDTH
    # ...and let go of afterwards: the room is a starting point, not a cage. (Qt clamps
    # an unbounded maximum to its own ceiling, so the question is only whether it is held.)
    assert window.dock_guide.maximumWidth() > window.LAYOUT_RIGHT_WIDTH
    assert window.dock_guide.minimumWidth() < window.PANEL_OPEN_MIN_WIDTH
    _close(window)


def test_the_view_buttons_bring_a_view_forward_and_never_put_it_away() -> None:
    """They were the docks' toggleViewActions, lit while a panel was OPEN. The board and
    the sheet start stacked in one tab group, so both were lit, and pressing Board to get to
    the board closed it; Ctrl+1, labelled "Show Board", did the same."""
    window = _window_on(_golden_document("ne555"))
    window.show_schematic()
    assert window.schematic_is_showing()

    window.act_show_board.trigger()

    assert not window.dock_board.isHidden()
    assert window.board_is_showing()
    assert not window.dock_schematic.isHidden(), "bringing one forward closed the other"

    # Pressed again, in front already: still there.
    window.act_show_board.trigger()
    assert not window.dock_board.isHidden()

    window.act_show_schematic.trigger()
    assert window.schematic_is_showing()
    assert window.act_show_board.shortcut().toString() == "Ctrl+1"
    assert window.act_show_schematic.shortcut().toString() == "Ctrl+2"
    assert not window.act_show_board.isCheckable()
    _close(window)


def test_a_view_is_put_away_from_the_panels_submenu() -> None:
    """Closing did not go away with the buttons: it is a switch that says which views are
    open, and a tabbed view has no title bar of its own to close it from."""
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui import i18n

    window = _window_on(_golden_document("ne555"))
    # The actions are HELD, not walked as temporaries. Under PySide6 6.10 the wrapper
    # ``QAction.menu()`` hands back dies with the action's own wrapper, and the dead one
    # stays cached for that menu: collecting the submenus out of a comprehension left a
    # list of menus every one of which raised "already deleted" -- while the menus
    # themselves were alive and well in the window.
    tops = window.menuBar().actions()
    entries = [entry for top in tops if top.menu() is not None for entry in top.menu().actions()]
    panels = next(
        entry.menu()
        for entry in entries
        if entry.menu() is not None and entry.menu().title() == i18n.t("Panels")
    )
    toggles = panels.actions()
    assert window.act_board_panel in toggles and window.act_schematic in toggles
    assert all(toggle.isCheckable() for toggle in toggles)
    # A dock's switch says whether it is VISIBLE, which a window never shown is not -- and
    # the sheet is shut on start, so it is opened first.
    window.show()
    window.show_schematic()
    QApplication.processEvents()
    assert window.act_schematic.isChecked()

    window.act_schematic.trigger()

    assert window.dock_schematic.isHidden()
    _close(window)


def test_a_tabbed_panel_drops_its_own_title_bar() -> None:
    """Qt draws both: the tab bar for the group, and under it the current dock's title --
    the same word twice, on two rows, above a view that wanted the height. The views open
    as tabs, without it; pulled out on their own, they get it back."""
    window = _window_on(_golden_document("ne555"))
    assert window.dock_schematic in window.tabifiedDockWidgets(window.dock_board)
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
    editing one net must not throw away the part of the sheet somebody was looking at.
    Zoomed through the gesture a person makes: a fitted sheet is fitted again on a redraw
    (it may have grown), and a sheet that did not grow comes back exactly where it was."""
    window = _open_schematic(_golden_document("ne555"))
    view = window.schematic_view
    fitted = view.transform()
    window._refresh_schematic_panel()
    assert view.transform() == fitted

    view.zoom_by(2.0)
    before = view.transform()

    window._refresh_schematic_panel()

    assert view.transform() == before
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


# ---------------------------------------------------------------------------
# The step bar (ui/workflow.py) in the window
# ---------------------------------------------------------------------------


def test_the_step_bar_follows_the_document() -> None:
    window = _blank_window()
    try:
        assert window.workflow_bar.next_key == "circuit"
        _add(window, "R1", "r-axial-3")
        _add(window, "R2", "r-axial-3")
        from perfboard_studio.commands import AddNetPayload
        from perfboard_studio.model import NetNode

        result = window.bus.dispatch(
            "net.add",
            AddNetPayload(
                name="A",
                nodes=(NetNode(component_ref="R1", pin="2"), NetNode(component_ref="R2", pin="1")),
            ),
        )
        assert result.ok
        assert window.workflow_bar.next_key == "board"
        board_button = window.workflow_bar.buttons["board"]
        assert board_button.property("status") == "current"
    finally:
        _close(window)


def _unpowered_555() -> PerfDocument:
    """A 555 from the catalog in the design, its output and ground wired and its VCC on
    nothing -- the circuit LVS would pass and the guide would build. A terminal on its
    ground is the way power comes in, so the one thing wrong with it is the VCC."""
    from perfboard_studio.catalog import catalog_part
    from perfboard_studio.commands import create_empty_document
    from perfboard_studio.model import DocumentMeta, Net, NetNode, SchematicPart

    entry = catalog_part("ne555")
    assert entry is not None
    parts = (
        SchematicPart(
            id="u1", ref="U1", value=entry.placed_value, footprint_id=entry.footprint_id,
            pin_names=entry.pin_names,
        ),
        SchematicPart(id="r1", ref="R1", value="1k", footprint_id="r-axial-3"),
        SchematicPart(id="c1", ref="C1", value="100n", footprint_id="c-disc-p2"),
        SchematicPart(id="j1", ref="J1", value="9V IN", footprint_id="screw-terminal-2"),
    )
    nets = (
        Net(id="n1", name="OUT", nodes=(NetNode("U1", "3"), NetNode("R1", "1"))),
        Net(
            id="n2", name="GND", nodes=(NetNode("U1", "1"), NetNode("C1", "2"), NetNode("J1", "2")),
            net_class="ground",
        ),
    )
    blank = create_empty_document(DocumentMeta(name="t", created="", modified=""))
    return dataclasses.replace(blank, parts=parts, nets=nets)


def test_a_circuit_error_comes_first_in_the_findings_and_is_where_next_goes() -> None:
    """Before any board: the findings open on the circuit's group, the status bar counts
    it, the Circuit step is the problem, and Next opens what is wrong beside the sheet --
    and connecting the pin clears all four."""
    from perfboard_studio.commands import AddNetPayload
    from perfboard_studio.model import NetNode
    from perfboard_studio.ui.main import _erc_title

    window = _window_on(_unpowered_555())
    try:
        root = window.drc_tree.topLevelItem(0)
        assert root.data(0, _finding_key_role()) == "ERC"
        assert root.isExpanded(), "an error in the circuit is shown, not folded away"
        group = _drc_group(window, "erc:supply-unconnected")
        assert group is not None
        assert group.text(0).startswith(_erc_title("supply-unconnected"))
        assert group.toolTip(0) == "supply-unconnected"
        errors_before = window.problems_bar.errors
        assert errors_before >= 1
        assert window.workflow_bar.next_key == "circuit"
        assert window.workflow_bar.buttons["circuit"].property("status") == "problem"

        window.set_problems_open(False)
        window.on_workflow_next("circuit")
        assert window.problems_bar.expanded
        assert window.schematic_is_showing()
        group = _drc_group(window, "erc:supply-unconnected")
        assert group.isExpanded()

        # The finding is about a part in the design: clicking it points at U1 on the sheet.
        window._on_drc_item_clicked(group.child(0), 0)
        assert window._schematic_ref == "U1"

        result = window.bus.dispatch(
            "net.add",
            AddNetPayload(
                name="+9V", net_class="power",
                nodes=(NetNode("U1", "8"), NetNode("C1", "1")),
            ),
        )
        assert result.ok
        assert _drc_group(window, "erc:supply-unconnected") is None
        assert window.problems_bar.errors == errors_before - 1
        assert window.workflow_bar.next_key == "board"
    finally:
        _close(window)


def test_the_next_button_goes_on_past_the_open_guide(tmp_path, monkeypatch) -> None:
    """With everything checked and the guide in front, Next saves a board that has no file
    and then exports the guide -- it used to raise the guide it was looking at, for ever."""
    from perfboard_studio.ui import main as main_module

    example = pathlib.Path(__file__).resolve().parent.parent / "examples" / "ne555-astable.perf"
    result = persist.deserialize_document(example.read_text(encoding="utf-8"))
    window = _window_on(result.document)
    try:
        assert window.workflow_bar.next_key == "build"
        assert window.workflow_bar.next_button.text().startswith("Open the Build Guide")
        window._raise_view(window.dock_guide)
        window._on_guide_visibility_changed(True)
        assert window.workflow_bar.next_button.text().startswith("Save the Board…")

        saved: list[bool] = []

        def save(self) -> bool:
            saved.append(True)
            self.current_path = tmp_path / "blinker.perf"
            return self._save_to(self.current_path)

        monkeypatch.setattr(main_module.MainWindow, "on_save", save)
        window.on_workflow_next("build")
        assert saved and window.current_path == tmp_path / "blinker.perf"
        assert window.workflow_bar.next_button.text().startswith("Export the Guide…")

        exported: list[bool] = []
        monkeypatch.setattr(
            main_module.MainWindow, "on_export_guide", lambda self: exported.append(True)
        )
        window.on_workflow_next("build")
        assert exported
    finally:
        _close(window)


def test_after_the_guide_the_bar_says_ready_and_a_cancelled_save_is_not_asked_again(
    monkeypatch,
) -> None:
    from perfboard_studio.ui import main as main_module

    example = pathlib.Path(__file__).resolve().parent.parent / "examples" / "ne555-astable.perf"
    result = persist.deserialize_document(example.read_text(encoding="utf-8"))
    window = _window_on(result.document)
    try:
        def build_status() -> str:
            facts = window.workflow_facts()
            return next(s.status for s in main_module.workflow_steps(facts) if s.key == "build")

        assert build_status() == "current"
        window._raise_view(window.dock_guide)
        window._on_guide_visibility_changed(True)
        assert build_status() == "done"
        bar = window.workflow_bar
        build = next(step for step in bar.steps if step.key == "build")
        assert bar._label(build, "full") == "Build · ready to build"
        assert window.workflow_bar.next_button.text().startswith("Save the Board…")

        monkeypatch.setattr(main_module.MainWindow, "on_save", lambda self: False)
        window.on_workflow_next("build")
        assert window.current_path is None
        assert window.workflow_bar.next_button.text().startswith("Export the Guide…")
        # Away from the guide and back, it is still ready, and still not asking.
        window.show_board()
        window._on_guide_visibility_changed(False)
        assert build_status() == "done"
    finally:
        _close(window)


def test_the_step_bar_counts_every_board_of_a_system() -> None:
    """The bar said the first board's size and the board in front's connections and
    findings: on a system it is every board's, and a board not in front is checked once
    and not again until it changes."""
    from perfboard_studio.drc import run_drc
    from perfboard_studio.ratsnest import ratsnest, summarize
    from perfboard_studio.system import board_document, board_ids

    example = pathlib.Path(__file__).resolve().parent.parent / "examples" / "relay-and-supply.perf"
    result = persist.deserialize_document(example.read_text(encoding="utf-8"))
    document = result.document
    ids = board_ids(document)
    assert len(ids) == 2
    window = _window_on(document)
    try:
        system = window.bus.system_document
        boards = [board_document(system, board_id) for board_id in ids]
        links = sum(summarize(ratsnest(b, window.lookup)).links for b in boards)
        errors = sum(
            1 for b in boards for v in run_drc(b, window.lookup) if v.severity == "error"
        )
        facts = window.workflow_facts()
        assert facts.board_label.startswith("2 boards"), facts.board_label
        assert facts.unrouted == links
        assert facts.drc_errors == errors
        other = next(b for b in ids if b != window._shown_board)
        checked = window._other_boards_checked[other]
        window.workflow_facts()
        assert window._other_boards_checked[other] is checked, "checked again unchanged"
    finally:
        _close(window)


def test_a_pin_with_an_error_and_a_warning_is_an_error_and_says_both() -> None:
    from perfboard_studio.erc import ErcFinding
    from perfboard_studio.model import NetNode
    from perfboard_studio.ui.viewsch import finding_marks

    pin = NetNode("U1", "8")
    pins, parts = finding_marks(
        (
            ErcFinding("single-pin-net", "warning", "alone", refs=("U1",), pins=(pin,)),
            ErcFinding("supply-unconnected", "error", "unpowered", refs=("U1",), pins=(pin,)),
            ErcFinding("part-unconnected", "warning", "joined to nothing", refs=("R3",)),
        )
    )
    assert pins == {("U1", "8"): ("error", ("alone", "unpowered"))}
    # A finding that names no pin is about the whole part, and is ringed on the part.
    assert parts == {"R3": ("warning", ("joined to nothing",))}


def test_the_sheet_rings_the_pin_erc_is_about_and_its_tooltip_says_why() -> None:
    """The findings panel says U1 pin 8; the sheet is where somebody drawing the circuit is
    looking, so the pin is ringed there and hovering it says what is wrong -- and the ring
    goes the moment the pin is connected."""
    from perfboard_studio.commands import AddNetPayload
    from perfboard_studio.model import NetNode
    from perfboard_studio.ui.viewsch import pin_anchor

    window = _open_schematic(_unpowered_555())
    try:
        item = window.schematic_view.item
        assert item is not None
        assert item.pin_marks == {
            ("U1", "8"): (
                "error",
                ("U1 pin 8 (VCC) is connected to nothing, so the chip is not powered.",),
            )
        }
        anchor = pin_anchor(item.drawing, "U1", "8")
        assert anchor is not None
        assert "so the chip is not powered" in window.schematic_view.describe(anchor)

        result = window.bus.dispatch(
            "net.add",
            AddNetPayload(
                name="+9V", net_class="power",
                nodes=(NetNode("U1", "8"), NetNode("C1", "1")),
            ),
        )
        assert result.ok
        item = window.schematic_view.item
        assert item is not None and item.pin_marks == {} and item.part_marks == {}
        assert "not powered" not in window.schematic_view.describe(anchor)
    finally:
        _close(window)


def test_placing_after_choosing_a_board_does_not_ask_again(monkeypatch) -> None:
    """The Board step and the placement both ask which board; asked once at the step, the
    placement uses the answer rather than putting the same question up a second time."""
    from perfboard_studio.ui import main as main_module

    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        asked: list[bool] = []

        def offer(self, document, always=False):
            asked.append(always)
            return True

        monkeypatch.setattr(main_module.MainWindow, "_offer_a_board_size", offer)
        window.show_schematic()
        window.on_choose_board()
        assert asked == [True]
        assert window._board_chosen
        # The board just chosen is shown, not left behind the sheet until Place.
        assert window.board_is_showing() and not window.schematic_is_showing()

        monkeypatch.setattr(
            main_module.MainWindow, "_run_planner", lambda self, label, work: None
        )
        window.on_schematic_place_all()
        assert asked == [True], "placing asked about the board a second time"
    finally:
        _close(window)


def test_after_place_and_auto_wire_properties_shows_the_step_not_the_last_part(
    monkeypatch,
) -> None:
    """The part last added on the sheet stayed selected through Place and Auto-wire, and
    Properties went on describing it as if it were what had just been done."""
    from perfboard_studio.ui import main as main_module

    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        for step, action in (("place", "on_schematic_place_all"), ("route", "on_autoroute_all")):
            monkeypatch.setattr(main_module.MainWindow, action, lambda self: None)
            window.schematic_view.set_selection(["R1"])
            window._selection_from = "sheet"
            window._refresh_properties()
            assert window.inspector.shown is not window.inspector.step_card
            window.on_workflow_next(step)
            assert window.inspector.shown is window.inspector.step_card, step
    finally:
        _close(window)


def test_cancelling_the_board_question_leaves_the_sheet_in_front(monkeypatch) -> None:
    """Only a board actually chosen brings the board in front; Cancel changes nothing."""
    from perfboard_studio.ui import main as main_module

    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        monkeypatch.setattr(
            main_module.MainWindow, "_offer_a_board_size", lambda self, document, always=False: False
        )
        window.show_schematic()
        window.on_choose_board()
        assert not window._board_chosen
        assert window.schematic_is_showing()
    finally:
        _close(window)


def test_each_step_goes_where_it_is_done() -> None:
    window = _blank_window()
    try:
        window.on_workflow_step("circuit")
        assert window.schematic_is_showing()
        window.on_workflow_step("place")
        assert window.board_is_showing()
        window.on_workflow_step("check")
        assert window.problems_bar.expanded
    finally:
        _close(window)


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


def test_a_drawn_wire_goes_round_the_parts_and_always_the_same_way() -> None:
    """A drawn wire turned once, horizontal first, whatever was in the way: from R1's
    right-hand pin to R2's left-hand one below it, that ran straight back through R1. It is
    routed round the symbols now (``schematic.route_sheet_wire``), still orthogonal, and the
    same route every time -- a tool whose route flipped as the pointer moved could not be
    aimed."""
    from perfboard_studio.schematic import route_sheet_wire

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    view = window.schematic_view
    window.on_sheet_tool("wire")

    view._wire_click(("R1", "2"))
    view._wire_click(("R2", "1"))

    wire = window.bus.document.sheet_wires[0]
    # Every segment is orthogonal, which is what "a schematic" means.
    for start, end in itertools.pairwise(wire.path):
        assert start.x == end.x or start.y == end.y
    drawing = view.item.drawing
    for symbol in drawing.symbols:
        x0, y0 = symbol.at.x, symbol.at.y
        x1, y1 = x0 + symbol.width, y0 + symbol.height
        for start, end in itertools.pairwise(wire.path[1:-1]):
            mid = ((start.x + end.x) / 2, (start.y + end.y) / 2)
            assert not (x0 < mid[0] < x1 and y0 < mid[1] < y1), f"through {symbol.ref}"
    routed = route_sheet_wire(drawing, ("R1", "2"), ("R2", "1"))
    assert routed is not None and route_sheet_wire(drawing, ("R1", "2"), ("R2", "1")) == routed
    _close(window)


def _middle_of_drawn_wire(view):
    """A point in the middle of the longest run of the one wire somebody drew."""
    wire = next(w for w in view.item.drawing.wires if w.ends is not None)
    runs = list(zip(wire.path, wire.path[1:], strict=False))
    start, end = max(runs, key=lambda r: abs(r[1].x - r[0].x) + abs(r[1].y - r[0].y))
    return QPointF((start.x + end.x) / 2, (start.y + end.y) / 2), wire.ends


def test_a_pin_clicked_then_a_wire_branches_off_it_in_a_t() -> None:
    """The wire tool, pin first: the second click lands on a drawn wire, and the pin joins
    that wire's net with a line ending ON it -- not three wires from pin to pin."""
    window = _blank_window()
    for ref in ("R1", "R2", "R3"):
        _add(window, ref, "r-axial-3")
    view = window.schematic_view
    window.on_sheet_tool("wire")
    view._wire_click(("R1", "2"))
    view._wire_click(("R2", "1"))
    window._refresh_schematic_panel()

    middle, ends = _middle_of_drawn_wire(view)
    tee = view.tee_at(middle)
    assert tee is not None and tee.ends == ends
    view._wire_click(("R3", "1"))
    view._tee_click(tee)

    document = window.bus.document
    (net,) = document.nets
    assert {(n.component_ref, n.pin) for n in net.nodes} == {("R1", "2"), ("R2", "1"), ("R3", "1")}
    branch = next(w for w in document.sheet_wires if w.tap is not None)
    assert branch.a.component_ref == "R3" and branch.host_pins == frozenset(ends)
    # The last run crosses the wire rather than lying along it.
    last_start, last_end = branch.path[-2], branch.path[-1]
    run_horizontal = last_start.y == last_end.y
    wire_horizontal = tee.horizontal
    assert run_horizontal != wire_horizontal or len(branch.path) == 2
    window._refresh_schematic_panel()
    assert any(j.at == branch.path[-1] for j in view.item.drawing.junctions)
    _close(window)


def test_a_wire_clicked_then_a_pin_is_the_same_t() -> None:
    window = _blank_window()
    for ref in ("R1", "R2", "R3"):
        _add(window, ref, "r-axial-3")
    view = window.schematic_view
    window.on_sheet_tool("wire")
    view._wire_click(("R1", "2"))
    view._wire_click(("R2", "1"))
    window._refresh_schematic_panel()

    middle, _ends = _middle_of_drawn_wire(view)
    view._tee_click(view.tee_at(middle))
    assert view.pending_tee is not None
    assert "click the pin that branches off it" in window.statusBar().currentMessage()
    view._wire_click(("R3", "1"))

    assert view.pending_tee is None
    assert any(w.tap is not None for w in window.bus.document.sheet_wires)
    assert len(window.bus.document.nets[0].nodes) == 3
    _close(window)


def test_a_net_label_stub_is_not_a_wire_to_branch_off() -> None:
    """Only a wire somebody drew is stored; a label's stub is the sheet's shorthand, and a
    T onto it would land on nothing."""
    from perfboard_studio.commands import AddNetPayload
    from perfboard_studio.model import NetNode

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    window.bus.dispatch(
        "net.add",
        AddNetPayload(name="CLK", nodes=(NetNode("R1", "1"), NetNode("R2", "1"))),
    )
    window.on_sheet_tool("wire")
    window._refresh_schematic_panel()
    view = window.schematic_view
    stub = next(w for w in view.item.drawing.wires if w.ends is None)
    middle = QPointF(
        (stub.path[0].x + stub.path[-1].x) / 2, (stub.path[0].y + stub.path[-1].y) / 2
    )
    assert view.tee_at(middle) is None
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


def _keep_the_board(window, monkeypatch) -> None:
    """Answer the board-size question with "keep the one I have".

    Stubbed on the METHOD, not on the dialog, for the reason ``_confirm`` is: a test that
    reaches past the window into QDialog is a test that breaks when the question is asked
    a different way, and this is the question, whatever it looks like.

    Through ``monkeypatch``, so it is undone when the test ends. It used to be assigned to
    the class, and every test after the first to call it got the stub whether it asked or
    not -- a stub with no ``always``, which the Board step passes.
    """
    monkeypatch.setattr(
        type(window), "_offer_a_board_size", lambda self, document, always=False: True
    )


def test_place_on_the_board_arranges_the_whole_design_in_one_undo_step(monkeypatch) -> None:
    window = _blank_window()
    _keep_the_board(window, monkeypatch)
    _add(window, "U1", "dip-8")
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")

    window.on_schematic_place_all()

    assert window.bus.document.parts == ()
    assert {c.ref for c in window.bus.document.components} == {"U1", "R1", "R2"}
    # Arranged, not dropped in a grid: the button does the whole job now, and says what
    # the next step is rather than what the missing one was.
    said = window.statusBar().currentMessage()
    assert "Ctrl+R" in said
    # What was done, as done -- the undo label alone read as an order -- and no "seed",
    # which is the placer's word, not a builder's.
    assert said.startswith("Done: "), said
    assert "seed" not in said

    window.bus.undo()
    assert len(window.bus.document.parts) == 3
    assert window.bus.document.components == ()
    _close(window)


def test_placing_a_design_leaves_the_parts_already_on_the_board_alone(monkeypatch) -> None:
    """Putting a design on the board is not the moment to rearrange what somebody has
    already positioned. That is auto-place, and it is a gesture they ask for by name."""
    window = _blank_window()
    _keep_the_board(window, monkeypatch)
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


def test_a_connector_in_the_design_is_placed_on_the_edge_of_the_board(monkeypatch) -> None:
    """The whole reason the button arranges rather than laying a grid: a header dropped
    in the middle of a board is a header nothing can be plugged into."""
    window = _blank_window()
    _keep_the_board(window, monkeypatch)
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
    from perfboard_studio.boardfamily import STANDARD_PRESETS
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


def test_the_board_size_dialog_shows_each_board_with_the_circuit_on_it() -> None:
    """"fits, 29 % full" is a number; the picture says HOW -- a packed corner of a big
    board and a full small one read the same as percentages. Given the document, every
    row is the board with the design arranged on it, drawn by the board view."""
    from perfboard_studio.model import SchematicPart
    from perfboard_studio.placer import design_entries, recommended_board, suggest_boards
    from perfboard_studio.ui.main import BoardSizeDialog

    window = _blank_window()
    try:
        document = dataclasses.replace(
            window.bus.document,
            parts=tuple(
                SchematicPart(id=f"p{i}", ref=f"R{i}", value="10k", footprint_id="r-axial-4")
                for i in range(3)
            ),
        )
        suggestions = suggest_boards(
            document.board, design_entries(document), document.nets, window.lookup
        )
        dialog = BoardSizeDialog(
            suggestions,
            document.board,
            recommended_board(suggestions),
            window,
            document=document,
            lookup=window.lookup,
        )
        assert dialog.choices.count() == len(suggestions) + 1
        for row in range(dialog.choices.count()):
            item = dialog.choices.item(row)
            assert item is not None and not item.icon().isNull(), item.text()
        dialog.deleteLater()
    finally:
        _close(window)


# -- the board question, tried rather than estimated (boardfit) ---------------------------


def _verdict(document, name, kind, *, ratio=1.0, unplaced=(), new_warnings=(), unrouted=0, errors=0):
    """A board trial's verdict without running one: the dialog is about what a verdict SAYS."""
    from perfboard_studio.boardfamily import STANDARD_PRESETS, board_from_preset
    from perfboard_studio.boardfit import PLACEMENT_WARNING_RULES, BoardTrial, BoardVerdict
    from perfboard_studio.placer import Arrangement, BoardSuggestion, DesignPlacement

    preset = next(p for p in STANDARD_PRESETS if p.name == name and not p.single_sided)
    board = board_from_preset(preset, document.board)
    on = dataclasses.replace(document, board=board)
    suggestion = BoardSuggestion(preset, board, Arrangement((), (), 1, board.cols * board.rows))
    trial = BoardTrial(
        suggestion=suggestion,
        document=on,
        placed=DesignPlacement((), unplaced, (), on, None),
        unplaced=unplaced,
        unrouted=unrouted,
        route_cost=100.0 * ratio,
        drc_errors=errors,
        warnings=tuple(0 for _ in PLACEMENT_WARNING_RULES),
    )
    return BoardVerdict(trial, kind, ratio, new_warnings)


def test_every_verdict_has_words_in_the_board_question() -> None:
    """A row says what its trial found in words, never as the verdict's id -- and every kind
    ``boardfit`` can give has some, which is what this reads ``get_args`` for."""
    from typing import get_args

    from perfboard_studio.boardfit import VerdictKind
    from perfboard_studio.ui.main import _verdict_note

    window = _blank_window()
    try:
        for kind in get_args(VerdictKind):
            note = _verdict_note(
                _verdict(window.bus.document, "5 x 7 cm", kind, ratio=1.1, unplaced=("U1",),
                         new_warnings=("heat-proximity",), unrouted=2, errors=1)
            )
            assert note and note != kind, (kind, note)
            if "-" in kind:
                assert kind not in note, (kind, note)
        warned = _verdict_note(
            _verdict(window.bus.document, "5 x 7 cm", "new-warnings", new_warnings=("heat-proximity",))
        )
        assert "heat-proximity" not in warned, "a rule is named in words, as the DRC panel does"
    finally:
        _close(window)


def test_the_board_question_says_what_each_trial_found() -> None:
    """A tried board shows the placement it was judged by and what the trial found; the
    star is on the recommendation; a board that could not take the design is greyed, and
    one that builds worse is not -- it is a board somebody may still want."""
    from perfboard_studio.placer import suggest_boards
    from perfboard_studio.ui.main import BoardSizeDialog

    window = _blank_window()
    try:
        document = window.bus.document
        suggestions = suggest_boards(document.board, [], document.nets, window.lookup)
        by_name = {s.preset.name: s for s in suggestions}
        verdicts = (
            _verdict(document, "6 x 8 cm", "reference"),
            _verdict(document, "5 x 7 cm", "accepted", ratio=1.04),
            _verdict(document, "4 x 6 cm", "dearer", ratio=1.31),
            _verdict(document, "3 x 7 cm", "too-small", unplaced=("U1", "R1")),
        )
        dialog = BoardSizeDialog(
            suggestions,
            document.board,
            by_name["5 x 7 cm"],
            window,
            document=document,
            lookup=window.lookup,
            verdicts=verdicts,
            complete=False,
        )
        rows = {
            dialog.choices.item(row).text().split("\n")[0].replace("★ ", ""): dialog.choices.item(row)
            for row in range(dialog.choices.count())
        }
        text = {name: item.text() for name, item in rows.items()}
        suggested = next(name for name in text if "5 x 7 cm" in name)
        assert "★" in dialog.choices.item(dialog.choices.currentRow()).text()
        assert "5 x 7 cm" in dialog.choices.item(dialog.choices.currentRow()).text()
        assert "104" in text[suggested]
        dearer = next(item for name, item in rows.items() if name == "4 x 6 cm")
        small = next(item for name, item in rows.items() if name == "3 x 7 cm")
        assert "131" in dearer.text() and dearer.flags() & Qt.ItemFlag.ItemIsEnabled
        assert not small.flags() & Qt.ItemFlag.ItemIsEnabled
        for row in range(dialog.choices.count()):
            item = dialog.choices.item(row)
            assert not item.icon().isNull(), item.text()
        dialog.deleteLater()
    finally:
        _close(window)


def _choice(document, *, complete=True, tried=("6 x 8 cm", "5 x 7 cm")):
    from perfboard_studio.boardfit import BoardChoice
    from perfboard_studio.placer import suggest_boards

    suggestions = tuple(suggest_boards(document.board, [], document.nets, footprint_lookup()))
    verdicts = tuple(
        _verdict(document, name, "reference" if index == 0 else "accepted")
        for index, name in enumerate(tried)
    )
    recommended = next(s for s in suggestions if s.preset.name == tried[-1])
    reference = next(s for s in suggestions if s.preset.name == tried[0])
    return BoardChoice(suggestions, reference, verdicts, recommended, complete)


def test_the_boards_are_tried_off_the_ui_thread_and_named_as_they_are(monkeypatch) -> None:
    """Twenty seconds on a big design, so it goes through ``_run_planner`` -- the worker
    thread, the Cancel button, the collector held off -- and the progress label names the
    board being tried, read back from what the worker last set."""
    from perfboard_studio.ui import main as main_module

    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        document = window.bus.document
        labels: list[str] = []

        def planner(self, label, work, **_):
            labels.append(label())
            result = work(lambda: False)
            labels.append(label())
            return result

        def choose(doc, lookup_, suggestions, should_stop=None, on_trial=None, **_):
            for suggestion in suggestions[:2]:
                on_trial(suggestion.preset)
            return _choice(doc)

        monkeypatch.setattr(main_module.MainWindow, "_run_planner", planner)
        monkeypatch.setattr(main_module, "choose_board", choose)
        suggestions = main_module.suggest_boards(document.board, [], document.nets, window.lookup)
        choice = window._board_choice(document, suggestions)

        assert choice.recommended is not None
        assert "smaller boards" in labels[0]
        assert suggestions[1].preset.name in labels[1]
    finally:
        _close(window)


def test_a_design_is_judged_once_until_it_changes_and_a_cancelled_judgement_is_not_kept(
    monkeypatch,
) -> None:
    from perfboard_studio.ui import main as main_module

    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        runs: list[bool] = []
        complete = [True]

        def choose(doc, lookup_, suggestions, **_):
            runs.append(True)
            return _choice(doc, complete=complete[0])

        monkeypatch.setattr(
            main_module.MainWindow, "_run_planner", lambda self, label, work, **_: work(lambda: False)
        )
        monkeypatch.setattr(main_module, "choose_board", choose)
        suggestions = main_module.suggest_boards(
            window.bus.document.board, [], window.bus.document.nets, window.lookup
        )

        window._board_choice(window.bus.document, suggestions)
        window._board_choice(window.bus.document, suggestions)
        assert len(runs) == 1, "the same design is not tried twice"

        _add(window, "R2", "r-axial-3")
        window._board_choice(window.bus.document, suggestions)
        assert len(runs) == 2, "a changed design is a new question"

        complete[0] = False
        _add(window, "R3", "r-axial-3")
        window._board_choice(window.bus.document, suggestions)
        window._board_choice(window.bus.document, suggestions)
        assert len(runs) == 4, "a search that was stopped is allowed to finish next time"
    finally:
        _close(window)


def _tried_on_a_board(window, monkeypatch):
    """A design big enough that its roomy board is not the smallest one -- so there is a
    smaller board to try -- tried for real through the Board step, the recommended board
    chosen in the dialog."""
    from perfboard_studio.ui import main as main_module

    _add(window, "U1", "dip-14")
    for ref in ("R1", "R2", "R3"):
        _add(window, ref, "r-axial-4")
    _add(window, "C1", "c-elec-d5-p2")

    monkeypatch.setattr(
        main_module.MainWindow, "_run_planner", lambda self, label, work, **_: work(lambda: False)
    )
    monkeypatch.setattr(
        main_module.MainWindow,
        "_ask_which_board",
        lambda self, choice, document: (True, choice.recommended),
    )
    window.on_choose_board()
    assert window._board_chosen


def test_placing_after_choosing_a_tried_board_commits_what_was_tried(monkeypatch) -> None:
    """WHAT WAS JUDGED IS WHAT LANDS: the trial already placed the design on the board the
    user chose, so Place on the Board commits that placement -- instantly, and without the
    chance of a second anneal coming out differently from the picture just approved."""
    from perfboard_studio.ui import main as main_module

    window = _blank_window()
    try:
        _tried_on_a_board(window, monkeypatch)
        tried = window._placement_ready
        assert tried is not None
        expected = {c.ref: (c.anchor, c.rotation) for c in tried[1].document.components}

        def no_planning(self, label, work):
            raise AssertionError("the placement was worked out again")

        monkeypatch.setattr(main_module.MainWindow, "_run_planner", no_planning)
        before = len(window.bus.history())
        window.on_schematic_place_all()

        placed = {c.ref: (c.anchor, c.rotation) for c in window.bus.document.components}
        assert placed == expected
        assert len(window.bus.history()) == before + 1
        assert window._placement_ready is None, "used once"
    finally:
        _close(window)


def test_an_edit_after_the_trial_throws_the_tried_placement_away(monkeypatch) -> None:
    from perfboard_studio.ui import main as main_module

    window = _blank_window()
    try:
        _tried_on_a_board(window, monkeypatch)
        _add(window, "R9", "r-axial-3")

        planned: list[bool] = []

        def planner(self, label, work):
            planned.append(True)
            return work(lambda: False)

        monkeypatch.setattr(main_module.MainWindow, "_run_planner", planner)
        window.on_schematic_place_all()

        assert planned == [True], "a design that changed is placed afresh"
        assert {c.ref for c in window.bus.document.components} == {"U1", "R1", "R2", "R3", "C1", "R9"}
    finally:
        _close(window)


def test_the_designer_draws_the_board_it_describes() -> None:
    """A product is recognised by looking at it. Picking a size redraws the picture beside
    the settings, edge connector and corner holes included."""
    from tests.designer_support import choose_family, designer_on

    window = _blank_window()
    try:
        dialog = designer_on(window.bus.document.board)
        dialog._show()
        first = dialog.preview.pixmap().toImage()
        assert not first.isNull()
        choose_family(dialog, "double-sided-fr4")
        # The biggest sold with its edge connector: some sizes come without one.
        sizes = dialog._current_family().sizes
        biggest = max((i for i, size in enumerate(sizes) if size.strip),
                      key=lambda i: sizes[i].cols * sizes[i].rows)
        dialog._on_stock_size(biggest)
        dialog._show()
        assert dialog.design().edge_connectors
        assert dialog.preview.pixmap().toImage() != first
        dialog.deleteLater()
    finally:
        _close(window)


def test_placing_with_nothing_left_in_the_design_says_so_rather_than_doing_nothing(monkeypatch) -> None:
    window = _blank_window()
    _keep_the_board(window, monkeypatch)

    window.on_schematic_place_all()

    assert "already on the board" in window.statusBar().currentMessage()
    _close(window)


def test_remove_deletes_a_part_in_the_design_and_unplaces_one_on_the_board(monkeypatch) -> None:
    """Two actions behind one button, and the difference is which list the part is in.
    Somebody clicking Remove on a placed part means "wrong hole", not "delete the
    circuit around it"."""
    window = _blank_window()
    _keep_the_board(window, monkeypatch)
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
        "&Mount on the Panel",
        "&Remove from the Design",
    ]
    _close(window)


def test_mounting_a_symbol_on_the_panel_is_one_step_that_keeps_what_it_is() -> None:
    """The sheet's door to taking a part off the board: an LED becomes two pads that still
    know which is the anode and a symbol that is still an LED, in one undo step -- and a part
    already off the board is not offered it again."""
    window = _blank_window()
    _add(window, "LED1", "led-5mm", "red")
    steps = len(window.bus.history())

    assert window.mount_off_board("LED1")
    part = next(p for p in window.bus.document.parts if p.ref == "LED1")
    assert part.footprint_id == "wire-2"
    assert part.pin_names == (("1", "A"), ("2", "K"))
    assert part.symbol == "led"
    assert len(window.bus.history()) == steps + 1
    window._refresh_schematic_panel()
    assert "&Mount on the Panel" not in _labels(window.sheet_menu(_over(window, "LED1")))
    _close(window)


def test_a_placed_part_is_taken_off_the_board_and_a_drawn_one_is_deleted(monkeypatch) -> None:
    """The one entry that differs between the two lists, and the difference is the whole
    reason ``on_schematic_remove`` is two actions behind one button: "I put this in the
    wrong hole" must not delete the circuit around it."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    _keep_the_board(window, monkeypatch)
    _add(window, "R1", "r-axial-3")
    window._on_part_dropped("R1", HoleCoord(5, 5))
    window._refresh_schematic_panel()

    assert "Take &off the Board" in _labels(window.sheet_menu(_over(window, "R1")))
    _close(window)


def test_a_right_click_on_bare_sheet_offers_the_sheet() -> None:
    window = _blank_window()
    _add(window, "R1", "r-axial-3")

    labels = _labels(window.sheet_menu(_sheet_at(window, -120.0, -120.0)))

    assert labels == ["&Add Part…", "Arran&ge the Sheet", "Fit the S&heet"]
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


def test_renaming_a_symbol_from_the_sheet_carries_its_nets() -> None:
    """The only reason a rename is safe to offer in two clicks. R1 wired into six nets and
    relabelled R7 used to come out connected to nothing. Rename is the Reference field."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _wire(window, "OUT", ("R1", "1"))

    _entry(window.sheet_menu(_over(window, "R1")), "name…").trigger()
    _type_into(window.inspector.design_part_editor.ref, "R7")

    assert [part.ref for part in window.bus.document.parts] == ["R7"]
    assert [node.component_ref for node in window.bus.document.nets[0].nodes] == ["R7"]
    _close(window)


def test_a_rename_nobody_finished_changes_nothing() -> None:
    """Rename puts the keyboard in the Reference; leaving it as it was writes nothing."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    before = window.bus.document
    window._rename_symbol("R1")
    editor = window.inspector.design_part_editor
    assert window.inspector.shown is editor
    _type_into(editor.ref, "R1")
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


def test_a_duplicate_of_a_placed_part_lands_in_the_design(monkeypatch) -> None:
    """The copy has no position and nothing here is entitled to guess one."""
    from perfboard_studio.model import HoleCoord

    window = _blank_window()
    _keep_the_board(window, monkeypatch)
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


def test_r_turns_whatever_is_selected_in_the_view_with_the_keyboard() -> None:
    """R was the board's Rotate and the sheet's Turn at once. With a part selected on the
    board and the schematic panel open, both were live, Qt called the key ambiguous and
    fired neither: R did nothing anywhere. Pressed through the real shortcut machinery,
    from a real focus, because the bug was entirely about which of them the key reached."""
    from PySide6.QtCore import Qt as QtCore_Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    window = _window_on(_load_dense())
    window.show()
    window.show_schematic()
    on_board, on_sheet = window.bus.document.components[:2]
    window.scene.select_components([on_board.id])
    window.schematic_view.set_selection([on_sheet.ref])
    QApplication.processEvents()

    def rotation_of(component_id: str) -> int:
        return next(c.rotation for c in window.bus.document.components if c.id == component_id)

    window.schematic_view.setFocus()
    QApplication.processEvents()
    QTest.keyClick(window.schematic_view, QtCore_Qt.Key.Key_R)
    QApplication.processEvents()

    turned = {p.id: p.rotation for p in window.bus.document.sheet}
    assert turned.get(on_sheet.id) == 90, "R on the sheet did not turn its selected symbol"
    assert rotation_of(on_board.id) == on_board.rotation, "R on the sheet turned a board part"

    window.view.setFocus()
    QApplication.processEvents()
    QTest.keyClick(window.view, QtCore_Qt.Key.Key_R)
    QApplication.processEvents()

    assert rotation_of(on_board.id) != on_board.rotation, "R on the board did nothing"
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


def _click_sheet(window, point) -> None:
    """A left click on the sheet at a point in sheet millimetres, through the viewport."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    view = window.schematic_view
    at = view.mapFromScene(QPointF(point.x, point.y))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)


def _open_point_on(view, path):
    """The middle of the first segment of a wire that no symbol's box covers, so a click
    there is a click on the wire."""
    from perfboard_studio.model import Point2

    for start, end in __import__("itertools").pairwise(path):
        at = Point2(x=(start.x + end.x) / 2, y=(start.y + end.y) / 2)
        covered = any(
            s.at.x <= at.x <= s.at.x + s.width and s.at.y <= at.y <= s.at.y + s.height
            for s in view.item.drawing.symbols
        )
        if not covered:
            return at
    raise AssertionError("every segment of the wire is under a symbol")


def _press_delete(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(window.schematic_view, Qt.Key.Key_Delete)


def test_a_drawn_wire_is_selected_by_a_click_and_rubbed_out_by_delete() -> None:
    """A click on a wire used to select its NET and nothing else, so no wire could be
    deleted. Now it is the wire that is selected -- the net is still lit -- and Delete
    takes the wire off and, a two-pin net having no other wire, the net with it."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    _add(window, "R2", "r-axial-3")
    window._on_sheet_wire_drawn("R1", "2", "R2", "1", [(0.0, 0.0), (10.16, 0.0)])
    window._refresh_schematic_panel()
    view = window.schematic_view
    nets_before = window.bus.document.nets
    (ends, path) = view.wire_runs()[0]
    middle = _open_point_on(view, path)

    _click_sheet(window, middle)
    assert view.selected_wire == ends
    assert view.item.selected_wire_path == path

    _press_delete(window)
    assert window.bus.document.sheet_wires == ()
    assert window.bus.document.nets == ()
    window.bus.undo()
    assert len(window.bus.document.sheet_wires) == 1
    assert window.bus.document.nets == nets_before
    _close(window)


@pytest.mark.parametrize("name", ["atmega328-relay", "nano-relay", "ne555-astable"])
def test_a_wire_on_an_example_sheet_nobody_has_frozen_can_be_selected_and_deleted(name) -> None:
    """The derived sheet draws wires that are not stored. Clicking one selects it all the
    same, and Delete freezes the sheet (its own undo step, as drawing a wire does) and
    then rubs the line out; the circuit is untouched."""
    import pathlib

    from perfboard_studio import persist

    golden = pathlib.Path(__file__).resolve().parent.parent / "examples" / f"{name}.perf"
    document = persist.deserialize_document(golden.read_text(encoding="utf-8")).document
    window = _window_on(document)
    window.show_schematic()
    window._refresh_schematic_panel()
    view = window.schematic_view
    assert window.bus.document.sheet == ()
    assert view.unfrozen_wires
    nets_before = window.bus.document.nets
    ends, path = view.wire_runs()[0]
    middle = _open_point_on(view, path)

    _click_sheet(window, middle)
    assert view.selected_wire == ends

    _press_delete(window)
    assert window.bus.document.sheet  # frozen
    assert not any((w.a, w.b) == ends for w in window.bus.document.sheet_wires)
    # The pin only that wire joined has left its net; every other connection is as it was.
    assert len(window.bus.document.nets) <= len(nets_before)
    assert sum(len(n.nodes) for n in window.bus.document.nets) < sum(
        len(n.nodes) for n in nets_before
    )
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

    # Net Face only where the board has pads on the component side, as the blank board does.
    assert labels == ["Re&name Net…", "Net &Class", "Net &Face", "&Edit Net…", "De&lete Net"]
    _close(window)


def test_the_class_submenu_offers_exactly_what_the_net_dialog_does() -> None:
    """One table, two consumers (``inspector.NET_CLASSES``). A class only the editor knew
    about would be one you could set and never see; one only the menu knew about would be
    one you could reach without being told what it costs."""
    from PySide6.QtWidgets import QMenu

    from perfboard_studio.ui.inspector import NET_CLASSES

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    net_id = _wire(window, "OUT", ("R1", "1"))
    menu = QMenu()

    window._add_net_entries(menu, net_id)

    submenu = _entry(menu, "Class").menu()
    assert [a.text() for a in submenu.actions()] == [
        row[2] for row in NET_CLASSES
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


def test_renaming_a_net_from_the_sheet_keeps_its_pins() -> None:
    """Rename Net on the wire's menu is the net's Name in Properties."""
    from PySide6.QtWidgets import QMenu

    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    net_id = _wire(window, "OUT", ("R1", "1"))
    menu = QMenu()
    window._add_net_entries(menu, net_id)

    _entry(menu, "name Net").trigger()
    assert window.inspector.shown is window.inspector.net_editor
    _type_into(window.inspector.net_editor.name, "VOUT")

    net = window.bus.document.nets[0]
    assert net.name == "VOUT"
    assert [node.component_ref for node in net.nodes] == ["R1"]
    _close(window)


def test_a_fitted_sheet_stays_fitted_while_the_panel_finds_its_size() -> None:
    """The first fit happened while the panel was small, and nothing fitted it again: the
    555 opened at under 3 px/mm in a panel with room for 5, all its text at the pixel floor
    and bigger than the room the layout had cleared. Until somebody zooms, a new size is a
    new fit; after they have, their view is theirs."""
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.schematic import build_schematic
    from perfboard_studio.ui.viewsch import SchematicView

    view = SchematicView()
    try:
        view.resize(300, 200)
        view.show()
        QApplication.processEvents()
        view.set_drawing(build_schematic(_load_dense(), footprint_lookup()))
        small = view.current_scale()
        view.resize(1200, 800)
        QApplication.processEvents()
        assert view.current_scale() > small * 2

        view.zoom_by(1.5)
        chosen = view.current_scale()
        view.resize(600, 400)
        QApplication.processEvents()
        assert view.current_scale() == chosen

        view.fit()
        view.resize(1200, 800)
        QApplication.processEvents()
        assert view.current_scale() != chosen
    finally:
        view.close()
        view.deleteLater()


def test_a_fitted_sheet_does_not_fit_itself_for_ever() -> None:
    """Paste on the sheet hung the window. The scene is the sheet plus a pad, so a fit of
    the sheet brought an as-needed scroll bar in; the bar was a resize, the resize fitted
    again, the scene fitted, the bar went, and round -- over 8000 fits in 50 ms in a 300 px
    panel with nobody touching it. A fitted sheet has no bars; a zoom brings them back and
    is not undone by them; and a sheet that grows while fitted is fitted again, or the new
    part would be off the edge of a view with nothing to scroll it by."""
    import dataclasses

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.schematic import build_schematic
    from perfboard_studio.ui.viewsch import SchematicView

    class Counting(SchematicView):
        fits = 0

        def fit(self) -> None:
            self.fits += 1
            # A fuse: the loop runs inside one processEvents, so a regression would hang
            # the suite rather than fail it. Past a hundred, stop fitting and let it count.
            if self.fits < 100:
                super().fit()

    off, needed = Qt.ScrollBarPolicy.ScrollBarAlwaysOff, Qt.ScrollBarPolicy.ScrollBarAsNeeded
    drawing = build_schematic(_load_dense(), footprint_lookup())
    view = Counting()
    try:
        view.resize(300, 300)
        view.show()
        QApplication.processEvents()
        view.set_drawing(drawing)
        view.fits = 0
        for _ in range(20):
            QApplication.processEvents()
        assert view.fits <= 1
        assert view.horizontalScrollBarPolicy() == view.verticalScrollBarPolicy() == off

        wider = dataclasses.replace(drawing, width=drawing.width * 2)
        view.set_drawing(wider)
        QApplication.processEvents()
        shown = view.mapToScene(view.viewport().rect()).boundingRect()
        assert shown.right() >= wider.width and shown.bottom() >= wider.height

        view.zoom_by(1.5)
        chosen = view.current_scale()
        QApplication.processEvents()
        assert view.horizontalScrollBarPolicy() == view.verticalScrollBarPolicy() == needed
        assert view.current_scale() == chosen
    finally:
        view.close()
        view.deleteLater()


def _wire_view():
    """A shown sheet of two resistors and nothing joining them, the wire tool armed, at a
    zoom a fitted sheet really has -- where the old 1.2 mm pick was five pixels."""
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.commands import AddPartPayload
    from perfboard_studio.schematic import build_schematic
    from perfboard_studio.ui.viewsch import SchematicView

    window = _blank_window()
    for ref in ("R1", "R2"):
        assert window.bus.dispatch(
            "part.add", AddPartPayload(ref=ref, footprint_id="r-axial-3")
        ).ok
    view = SchematicView()
    view.resize(900, 600)
    view.show()
    QApplication.processEvents()
    view.set_drawing(build_schematic(window.bus.document, footprint_lookup()))
    view.set_tool("wire")
    QApplication.processEvents()
    return window, view


def _pin_on_screen(view, ref: str, number: str):
    from PySide6.QtCore import QPointF

    symbol = next(s for s in view.item.drawing.symbols if s.ref == ref)
    pin = next(p for p in symbol.pins if p.number == number)
    return view.mapFromScene(QPointF(symbol.at.x + pin.at.x, symbol.at.y + pin.at.y))


def _send_mouse(view, kind: str, pos, pressed: bool = False) -> None:
    """A mouse event delivered straight to the sheet's viewport. QTest's own moves go
    through the platform's cursor, and a move with no button held is not delivered at all
    when the cursor is already where it is being sent -- which, in a suite, depends on
    whichever test ran before."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    types = {
        "move": QEvent.Type.MouseMove,
        "press": QEvent.Type.MouseButtonPress,
        "release": QEvent.Type.MouseButtonRelease,
    }
    left = Qt.MouseButton.LeftButton
    button = Qt.MouseButton.NoButton if kind == "move" else left
    held = left if (pressed or kind == "press") else Qt.MouseButton.NoButton
    local = QPointF(pos)
    event = QMouseEvent(
        types[kind], local, view.viewport().mapToGlobal(local), button, held,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.viewport(), event)


def test_a_wire_can_be_dragged_from_pin_to_pin_or_clicked() -> None:
    """The wire tool took two CLICKS and nothing else: a drag from one pin to another --
    what everybody tries first -- took the first pin on the press and did nothing on the
    release. Both are a wire now, and a pin is a target of at least a few pixels whatever
    the zoom, with the one the pointer is over ringed before the click."""
    from PySide6.QtCore import QPoint

    window, view = _wire_view()
    drawn: list[tuple] = []
    view.wireDrawn.connect(lambda *args: drawn.append(args[:4]))
    try:
        start = _pin_on_screen(view, "R1", "2")
        end = _pin_on_screen(view, "R2", "1")
        # Off by a few pixels, as a hand is.
        near = QPoint(3, 2)
        _send_mouse(view, "move", end + near)
        assert view.item.hover_pin == ("R2", "1")

        _send_mouse(view, "press", start + near)
        _send_mouse(view, "move", end + near, pressed=True)
        _send_mouse(view, "release", end + near)
        assert drawn == [("R1", "2", "R2", "1")]

        for point in (start, end):
            _send_mouse(view, "press", point)
            _send_mouse(view, "release", point)
        assert drawn[-1] == ("R1", "2", "R2", "1") and len(drawn) == 2

        view.set_tool("select")
        assert view.item.hover_pin is None

        # The target is a few pixels whatever the zoom, and never so wide that it reaches
        # past the next pin of a DIP by more than the nearest-wins rule can settle.
        from perfboard_studio.ui.viewsch import PIN_PICK_MAX_MM, PIN_PICK_MM

        view.resetTransform()
        view.scale(4.0, 4.0)
        assert view.pin_pick_radius() == PIN_PICK_MAX_MM
        view.resetTransform()
        view.scale(40.0, 40.0)
        assert view.pin_pick_radius() == PIN_PICK_MM
    finally:
        view.close()
        view.deleteLater()
        _close(window)


def test_a_drag_from_a_pin_in_select_draws_a_wire_and_leaves_the_part_where_it_is() -> None:
    """In Select a press on a pin and a drag moved the PART, where what a pointer on a pin
    means is nearly always a wire. It draws the wire now, as the wire tool's drag does, and
    Select stays Select; a click on the pin still selects its symbol, and a drag from it to
    nothing draws nothing."""
    from PySide6.QtCore import QPoint

    window, view = _wire_view()
    drawn: list[tuple] = []
    moved: list[list] = []
    view.wireDrawn.connect(lambda *args: drawn.append(args[:4]))
    view.symbolsMoved.connect(moved.append)
    try:
        view.set_tool("select")
        start = _pin_on_screen(view, "R1", "2")
        end = _pin_on_screen(view, "R2", "1")

        _send_mouse(view, "press", start)
        _send_mouse(view, "move", start + QPoint(20, 0), pressed=True)
        _send_mouse(view, "move", end, pressed=True)
        _send_mouse(view, "release", end)
        assert drawn == [("R1", "2", "R2", "1")]
        assert moved == [], "the part did not move"
        assert view.tool == "select" and view.pending_pin is None

        _send_mouse(view, "press", start)
        _send_mouse(view, "release", start)
        assert view.selected_refs == ["R1"] and len(drawn) == 1

        nowhere = start + QPoint(0, 120)
        _send_mouse(view, "press", start)
        _send_mouse(view, "move", nowhere, pressed=True)
        _send_mouse(view, "release", nowhere)
        assert len(drawn) == 1 and moved == [] and view.pending_pin is None
    finally:
        view.close()
        view.deleteLater()
        _close(window)


def test_c_arms_connect_on_whichever_canvas_has_the_keyboard() -> None:
    """The board's Connect had C and the sheet's had no key at all; one key cannot be two
    actions (Qt answers an ambiguous shortcut by doing nothing), so C is Connect on the
    canvas with the keyboard, as Select All and Fit are."""
    from PySide6.QtWidgets import QApplication

    window = _window_on(_load_dense())
    try:
        window.show()
        window.show_schematic()
        window.schematic_view.setFocus()
        QApplication.processEvents()
        if not window.schematic_view.hasFocus():
            pytest.skip("the platform gives no widget the keyboard here")
        window.act_connect.trigger()
        assert window.schematic_view.tool == "wire"
        assert not window.scene.connect_armed and not window.act_connect.isChecked()
        window.act_connect.trigger()
        assert window.schematic_view.tool == "select"

        window.view.setFocus()
        QApplication.processEvents()
        window.act_connect.trigger()
        assert window.scene.connect_armed and window.schematic_view.tool == "select"
    finally:
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


def test_a_free_pin_goes_to_ground_or_a_supply_in_one_click() -> None:
    """Ground and power had no door on the sheet: a rail glyph is drawn from a net named
    GND, and making one meant the Label tool and typing it. A pin on nothing now offers the
    document's own rails by name, and GND and +5V when it has none of that kind -- and a net
    made that way is classed by its name, so it IS a rail."""
    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        _add(window, "R2", "r-axial-3")

        def menu_at(ref: str, number: str):
            symbol = next(s for s in window.schematic_view.item.drawing.symbols if s.ref == ref)
            pin = next(p for p in symbol.pins if p.number == number)
            return window.sheet_menu(
                _sheet_at(window, symbol.at.x + pin.at.x, symbol.at.y + pin.at.y)
            )

        menu = menu_at("R1", "1")
        labels = _labels(menu)
        assert "Connect R1.1 to GND" in labels
        assert "Connect R1.1 to +5V" in labels
        _entry(menu, "to GND").trigger()
        gnd = next(n for n in window.bus.document.nets if n.name == "GND")
        assert gnd.net_class == "ground"

        # The rail that now exists is offered by name, and no second default is invented.
        labels = _labels(menu_at("R2", "2"))
        assert labels.count("Connect R2.2 to GND") == 1
        _entry(menu_at("R2", "2"), "to GND").trigger()
        gnd = next(n for n in window.bus.document.nets if n.name == "GND")
        assert {node.component_ref for node in gnd.nodes} == {"R1", "R2"}
        assert any(rail.net_name == "GND" for rail in window.schematic_view.item.drawing.rails)
    finally:
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


def test_adding_a_555_from_the_dialog_brings_its_pin_names() -> None:
    """The dialog offered the sixty-one PACKAGES, a crystal first and Y1 in the reference,
    while the Parts panel beside it had the catalog. The catalog comes first in the package
    picker, and a catalog part chosen there brings its value and pin names with its
    package; a bare package keeps the part's value and the names of the pins it still has."""
    from perfboard_studio.ui.main import ROLE_CATALOG_ID, MainWindow, PackagePicker

    picker = PackagePicker(_load_dense())
    # Unfiltered, nothing is chosen for the user.
    assert picker.chosen_footprint_id() is None
    picker.filter.setText("555")
    item = picker.tree.currentItem()
    assert item is not None and item.data(0, ROLE_CATALOG_ID) == "ne555"
    assert picker.chosen_footprint_id() == "dip-8"
    part = picker.chosen_catalog_part()
    value, names, _symbol = MainWindow._what_a_package_brings("dip-8", part, "", (), None)
    assert value == "NE555" and dict(names)["3"] == "OUT"
    # A bare package: the value stays, and only the names of pins it still has.
    kept = MainWindow._what_a_package_brings(
        "r-axial-4", None, "10k", (("1", "A"), ("2", "B"), ("3", "C")), None
    )
    assert kept == ("10k", (("1", "A"), ("2", "B")), None)
    picker.deleteLater()


def test_editing_a_custom_part_does_not_turn_it_into_a_resistor() -> None:
    """``select_footprint`` puts a part the library does not have into its own list first.

    Without that the properties dialog opens on whatever happens to be first and pressing
    OK changes the part -- silently, into something with two pins where there were eight.
    """
    from perfboard_studio.ui.main import PackagePicker

    document = _custom_document()
    dialog = PackagePicker(document)
    dialog.select_footprint("box-4x2-p1-r3-15x10x8")
    assert dialog.chosen_footprint_id() == "box-4x2-p1-r3-15x10x8"
    dialog.deleteLater()


def test_work_left_to_do_is_not_shown_as_wrong() -> None:
    """A part still in the design and a net not wired yet are the steps ahead, and the step
    bar says so -- while the findings put the first in red under the Circuit step and the
    status bar turned red the moment a placement landed. Both now wait, as the bar does,
    until there is something actually wrong."""
    from perfboard_studio.commands import UnplaceComponentPayload
    from perfboard_studio.ui.main import ROLE_FINDING_KEY
    from perfboard_studio.ui.theme import TEXT_DIM

    window = _window_on(dataclasses.replace(_load_dense(), conductors=()))
    assert window._last_lvs is not None and window._last_lvs.summary.opens > 0
    # Not one of the opens is a problem on the bar while there is wiring left to do.
    drc_errors = sum(1 for v in window._last_violations if v.severity == "error")
    erc_errors = sum(1 for f in window._last_erc if f.severity == "error")
    assert window.problems_bar.errors == drc_errors + erc_errors

    # A part the netlist names, or LVS has nothing to say about where it is.
    wired = window.bus.document.nets[0].nodes[0].component_ref
    component = next(c for c in window.bus.document.components if c.ref == wired)
    result = window.bus.dispatch("component.unplace", UnplaceComponentPayload(id=component.id))
    assert result.ok, result.message
    tree = window.drc_tree
    kinds = {}
    for index in range(tree.topLevelItemCount()):
        root = tree.topLevelItem(index)
        for row in range(root.childCount()):
            child = root.child(row)
            kinds[child.data(0, ROLE_FINDING_KEY)] = child.foreground(0).color().name()
    # In the dimmed colour the status bar gives the connections left to route: amber said
    # "look at this" about a board that was merely not finished yet.
    assert kinds["lvs:unplaced-component"] == TEXT_DIM.lower(), kinds
    assert kinds["lvs:unrouted-net"] == TEXT_DIM.lower(), kinds
    _close(window)


def test_add_a_part_is_the_library_and_enter_puts_it_on_the_sheet() -> None:
    """Add Part was a modal copy of the Library. It is the Library: its search focused, the
    sheet in front; Enter puts the part on the sheet as one undo step and Properties shows
    it, and the search is still there for the next part."""
    from perfboard_studio.ui.main import ROLE_FOOTPRINT_ID

    window = _blank_window()
    try:
        before = len(window.bus.history())
        window.on_schematic_add_part()
        assert window._is_in_front(window.dock_schematic)
        window.library_filter.setText("resistor")

        def first_part():
            tree = window.library_tree
            for index in range(tree.topLevelItemCount()):
                group = tree.topLevelItem(index)
                for row in range(group.childCount()):
                    if group.child(row).data(0, ROLE_FOOTPRINT_ID):
                        return group.child(row)
            raise AssertionError("no part in the filtered library")

        window._on_library_item_activated(first_part())
        window._on_library_item_activated(first_part())
        refs = [p.ref for p in window.bus.document.parts]
        assert len(refs) == 2 and len(set(refs)) == 2
        assert len(window.bus.history()) == before + 2
        assert window.inspector.shown is window.inspector.design_part_editor
        assert window.inspector.design_part_editor.ref.text() == refs[-1]
        assert window.scene.armed_footprint_id is None
    finally:
        _close(window)

def test_the_findings_panel_names_copper_by_where_it_runs() -> None:
    """Fourteen findings on the dense fixture name a conductor by its id ("Solder trace
    cond-21 passes through C13"), which nothing at the bench can look up."""
    import re

    window = _window_on(_load_dense())
    texts: list[str] = []

    def walk(item) -> None:
        texts.append(item.text(1))
        for row in range(item.childCount()):
            walk(item.child(row))

    for index in range(window.drc_tree.topLevelItemCount()):
        walk(window.drc_tree.topLevelItem(index))
    assert any("–" in text for text in texts)
    assert not [text for text in texts if re.search(r"\bcond-\d+", text)]
    _close(window)


def test_enter_takes_the_part_the_filter_names() -> None:
    """The catalog comes first in the list and is searched by what a part does as well as
    by its name, so "LED" put the MAX7219 -- an LED display driver -- ahead of every LED,
    and Enter added a 24-pin chip to somebody's blinker."""
    from perfboard_studio.ui.main import PackagePicker

    dialog = PackagePicker(_load_dense())
    dialog.filter.setText("LED")
    chosen = dialog.chosen_footprint_id()
    assert chosen is not None and chosen.startswith("led-"), chosen
    # A search that names nothing still takes the first match rather than nothing.
    dialog.filter.setText("op amp")
    assert dialog.chosen_footprint_id() is not None
    dialog.deleteLater()


def test_enter_takes_the_row_the_text_names_earliest() -> None:
    """"header" names the pin header four letters in, and "Power in, 2-pin header" sixteen:
    the one somebody typing it wants is the pin header."""
    from perfboard_studio.ui.main import ROLE_FOOTPRINT_ID, PackagePicker, named_choice

    dialog = PackagePicker(_load_dense())
    dialog.filter.setText("header")
    item = dialog.tree.currentItem()
    assert item is not None and str(item.data(0, ROLE_FOOTPRINT_ID)).startswith("hdr-1x"), item.text(0)
    dialog.deleteLater()
    assert named_choice("header", [("Power in, 2-pin header", None), ("Pin header, 1x2", None)]) == 1
    assert named_choice("LED", [("SSD1306 OLED 0.96in", None), ("LED, 3 mm round", None)]) == 1


def test_a_catalog_part_is_named_by_its_aliases_when_no_label_names_it() -> None:
    """"anahtar" is in no label: the tact switch is named by its alias. An alias counts only
    after every label, since it is matched inside words."""
    from perfboard_studio.catalog import catalog_part
    from perfboard_studio.ui.main import named_choice

    switch = catalog_part("tact-6x6")
    assert switch is not None
    switch = dataclasses.replace(switch, aliases=(*switch.aliases, "anahtar"))
    rows = [("BC547", catalog_part("bc547")), ("Tactile switch 6x6 mm", switch)]
    assert named_choice("anahtar", rows) == 1
    # Named by a label beats named by an alias.
    assert named_choice("switch", [("Tactile switch 6x6 mm", switch), ("Switch, 4-pin", None)]) == 1


def test_a_name_is_named_by_a_word_or_the_start_of_one() -> None:
    """"LED" is inside "SSD1306 OLED", and Enter on "LED" took the display: the text has to
    be a word of the name, or the start of one, for the row to count as named."""
    from perfboard_studio.ui.main import typed_names

    assert typed_names("LED", "LED, 5 mm round")
    assert typed_names("led", "LED, 3 mm yuvarlak")
    assert not typed_names("LED", "SSD1306 OLED 0.96in I2C")
    assert typed_names("ATtiny", "ATtiny85")
    assert typed_names("switch", "Tactile switch 6x6 mm")
    assert typed_names("dip-8", "DIP-8")
    assert not typed_names("  ", "LED, 5 mm round")


def test_the_part_list_counts_sizes_as_numbers() -> None:
    """By string order "LED, 10 mm" came first, so "LED" and Enter gave a 10 mm LED, and a
    1x10 header stood between the 1x1 and the 1x2."""
    from perfboard_studio.ui.main import ROLE_FOOTPRINT_ID, PackagePicker

    dialog = PackagePicker(_load_dense())
    dialog.filter.setText("LED")
    assert dialog.chosen_footprint_id() == "led-3mm"
    dialog.filter.setText("header, 1x")
    ids = [leaf.data(0, ROLE_FOOTPRINT_ID) for leaf in dialog._leaves()]
    assert ids[:3] == ["hdr-1x1", "hdr-1x2", "hdr-1x3"]
    assert ids.index("hdr-1x9") < ids.index("hdr-1x10")
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
        # Said in Properties, which is where a selection is said now.
        window._refresh_properties()
        assert window.inspector.shown is window.inspector.conductor_editor
        assert "→" in window.inspector.conductor_editor.ends.text()

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
        seen["default variant"] = str(self.defaultButton().property("variant") or "")
        seen["buttons"] = "|".join(b.text() for b in self.buttons())
        seen["danger"] = "|".join(
            b.text() for b in self.buttons() if b.property("variant") == "danger"
        )
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)
    try:
        assert window._confirm("Delete parts", "Delete R1?", "Delete") is False
        assert seen["default"] == "Cancel"
        assert "Delete" in seen["buttons"]
        # The verb is drawn as destructive, and only the verb: Enter's Cancel keeps the
        # accent it has as the default (picked 2026-11-03, candidate D).
        assert seen["danger"] == "Delete"
        assert seen["default variant"] == ""
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


def test_the_3d_panel_follows_the_last_edit_of_a_burst_not_every_one(monkeypatch) -> None:
    """Re-actoring the 3D board costs about a third of a second on atmega328-relay, and an
    arrow key held down is a move every keyboard repeat -- so every nudge used to wait for
    the 3D panel. Three quick edits are one redraw, after they stop."""
    import time

    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.main import MainWindow

    window = _window_on(_load_dense())
    redraws: list[int] = []
    monkeypatch.setattr(MainWindow, "_3d_is_live", lambda self: True)
    monkeypatch.setattr(MainWindow, "_refresh_3d", lambda self: redraws.append(1))
    part = window.bus.document.components[0]

    for col in (3, 4, 5):
        window.bus.dispatch(
            "component.move", MoveComponentPayload(id=part.id, anchor=HoleCoord(col, 3))
        )
    assert redraws == []

    deadline = time.perf_counter() + 2.0
    while not redraws and time.perf_counter() < deadline:
        QApplication.processEvents()
    assert redraws == [1]

    window.bus.dispatch("component.move", MoveComponentPayload(id=part.id, anchor=HoleCoord(6, 3)))
    _close(window)
    assert not window._3d_refresh_timer.isActive(), "a redraw was left waiting on a closed window"


def test_the_undo_button_keeps_its_one_word() -> None:
    """The menu names the command; the toolbar button used to as well, and grew to "Undo
    Autoroute 7 nets (14 connections)", shoving every button after it along the bar."""
    from perfboard_studio.ui import i18n

    window = _window_on(_load_dense())
    try:
        first = window.bus.document.components[0]
        window.bus.dispatch("component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(3, 3)))
        assert first.ref in window.act_undo.text()
        assert first.ref in window.act_undo.toolTip()
        assert window.act_undo.iconText() == i18n.t("&Undo").replace("&", "")
        window.on_undo()
        assert window.act_redo.iconText() == i18n.t("&Redo").replace("&", "")
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


def test_a_hole_chosen_on_the_board_is_its_own_editor_with_remove() -> None:
    """The list is not the only way to a hole: clicked on the board, it is what Properties
    shows -- where it is, its size -- and Remove takes it off, one undo step."""
    from perfboard_studio.commands import AddMountingHolesPayload

    window = _window_on(_load_dense())
    try:
        window.bus.dispatch("mounting-hole.addMany", AddMountingHolesPayload(ats=(HoleCoord(1, 1),)))
        (mount,) = window.bus.document.mounting_holes
        window.scene.mount_items[mount.id].setSelected(True)
        window._selection_from = "board"
        window._refresh_properties()
        editor = window.inspector.feature_editor
        assert window.inspector.shown is editor
        assert editor.where.text() == "B2"
        editor.remove.click()
        assert window.bus.document.mounting_holes == ()
    finally:
        _close(window)


def test_a_connector_is_chosen_by_its_fingers_and_nowhere_else() -> None:
    """Its bounding rectangle is the whole board: chosen by that, every click on the board
    would have chosen the connector."""
    from perfboard_studio.ui.selection import Selection

    window = _window_on(_featured_document())
    try:
        (connector,) = window.bus.document.edge_connectors
        item = window.scene.connector_items[connector.id]
        middle = item.boundingRect().center()
        assert not item.shape().contains(middle)
        finger = item._fingers()[0][0].center()
        assert item.shape().contains(finger)
        item.setSelected(True)
        assert window._board_selection() == Selection("edge-connector", (connector.id,))
        window._selection_from = "board"
        window._refresh_properties()
        assert window.inspector.shown is window.inspector.feature_editor
    finally:
        _close(window)


def test_board_features_in_the_menu_shows_them_in_properties() -> None:
    from perfboard_studio.ui import main as main_module

    assert not hasattr(main_module, "BoardFeaturesDialog")
    window = _window_on(_featured_document())
    try:
        window.on_board_features()
        assert window.inspector.shown is window.inspector.board_editor
        assert len(window.inspector.board_editor.features.rows()) == 2
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


def test_an_imported_netlist_puts_real_parts_in_the_design_with_their_values(
    tmp_path, monkeypatch
) -> None:
    """The window adds what ``parsers.kicad_parts`` read -- the catalog's BC547 with its
    value and pin names, the LED renumbered anode to pin 1 -- to the DESIGN, as one undo
    step, and says what it renumbered. Not to the board: that is what choosing a board and
    placing are for, and a netlist used to skip both by landing on whatever board the
    document happened to open on."""
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
        assert window.bus.document.components == ()
        parts = {p.ref: p for p in window.bus.document.parts}
        assert parts["Q1"].value == "BC547" and parts["Q1"].footprint_id == "to92"
        assert dict(parts["Q1"].pin_names)["1"] == "C"
        assert parts["U2"].footprint_id == "to220"
        led = next(n for n in window.bus.document.nets if n.name == "+5V")
        assert ("D1", "1") in {(node.component_ref, node.pin) for node in led.nodes}
        assert any("Q1: pins renumbered" in text for text in shown)
        assert window.schematic_is_showing()
        assert window.workflow_bar.next_key == "board"
        window.bus.undo()
        assert window.bus.document.parts == ()
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
    from perfboard_studio.boardfamily import STANDARD_PRESETS, board_from_preset
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


def _generated_body(footprint_id: str, value: str, rotation: int = 0):
    """A part's body in world space, on the dense board, as the 3D view builds it."""
    from perfboard_studio.model import ComponentInstance
    from perfboard_studio.ui import view3d

    comp = ComponentInstance(
        id="c1",
        ref="X1",
        value=value,
        footprint_id=footprint_id,
        anchor=HoleCoord(8, 8),
        rotation=rotation,
    )
    body = view3d._world_body(footprint_lookup(), comp, _load_dense().board)
    assert body is not None
    return body


def _piece_bounds(piece) -> tuple[float, ...]:
    from perfboard_studio.ui import view3d

    actor = view3d._actor_for(piece)
    actor.GetMapper().Update()
    return tuple(actor.GetBounds())


@pytest.mark.parametrize(
    ("footprint_id", "value", "printed"),
    [
        ("relay-spdt", "SRD-12VDC-SL-C", "SRD-12VDC-SL-C"),
        ("pot-3", " 10k ", "10k"),
        # Whole in the 2D's font, which has the letter. Where Qt draws no letters -- its
        # offscreen plugin on Windows has no fonts -- the stand-in vtkVectorText has ASCII
        # alone and would print "Rle 12V", so it is left off (view3d.can_print).
        ("relay-spdt", "R\u00f6le 12V", None),
        ("pot-3", "", ""),
        # A DIP's print is its manufacturer's, and nothing the document knows.
        ("dip-8", "NE555", ""),
    ],
)
def test_a_relay_and_a_potentiometer_carry_their_value_in_print(
    footprint_id: str, value: str, printed: str | None
) -> None:
    from perfboard_studio.ui import view3d

    if printed is None:
        printed = value if view3d.can_print(value) else ""
    assert _generated_body(footprint_id, value).marking == printed


@pytest.mark.parametrize("rotation", [0, 90])
def test_a_relay_is_printed_along_its_long_side_on_top_of_its_case(rotation: int) -> None:
    from perfboard_studio.ui import view3d

    body = _generated_body("relay-spdt", "SRD-12VDC-SL-C", rotation)
    pieces = view3d._relay_pieces(body)
    ink = [piece for piece in pieces if piece.material == view3d.INK]
    assert len(ink) == 1, "one line of print"
    x0, x1, y0, y1, z0, _z1 = _piece_bounds(ink[0])
    across_x, across_y = x1 - x0, y1 - y0
    assert (across_x > across_y) == (body.axis == "x"), "the print runs along the long side"
    assert max(across_x, across_y) <= body.along, "and fits on it"
    assert z0 == pytest.approx(body.height + view3d._LIFT, abs=0.05), "on the top face"

    blank = view3d._relay_pieces(_generated_body("relay-spdt", ""))
    assert not [piece for piece in blank if piece.material == view3d.INK]


def test_a_relay_case_stands_on_its_feet_off_the_board() -> None:
    """The dark line under the case is what says it is standing on something."""
    from perfboard_studio.ui import view3d

    body = _generated_body("relay-spdt", "")
    case = view3d._relay_pieces(body)[0]
    assert _piece_bounds(case)[4] == pytest.approx(
        view3d._LIFT + view3d.RELAY_STANDOFF_MM, abs=1e-6
    )


def test_a_potentiometer_keeps_to_its_own_footprint() -> None:
    """The bushing, the shaft and the tabs are detail on the part, not more part: nothing
    reaches past the body a hair more than the tabs' own thickness, and the shaft stands on
    the centre, where the knob goes."""
    from perfboard_studio.ui import view3d

    body = _generated_body("pot-3", "10k")
    radius = min(body.size_x, body.size_y) / 2
    solids = [piece for piece in view3d._pot_pieces(body) if not piece.instances]
    assert len(solids) >= 5, "housing, cover, bushing, shaft, slot"
    for piece in solids:
        x0, x1, y0, y1, _z0, _z1 = _piece_bounds(piece)
        for corner_x in (x0, x1):
            for corner_y in (y0, y1):
                assert abs(corner_x - body.x) <= radius + 0.45
                assert abs(corner_y - body.y) <= radius + 0.45
    shaft = max(solids, key=lambda piece: _piece_bounds(piece)[5])
    x0, x1, y0, y1, _z0, z1 = _piece_bounds(shaft)
    assert (x0 + x1) / 2 == pytest.approx(body.x, abs=0.05)
    assert (y0 + y1) / 2 == pytest.approx(body.y, abs=0.05)
    assert z1 == pytest.approx(body.height + view3d._LIFT, abs=0.05)


def test_a_turned_part_is_closed_at_both_ends() -> None:
    """A profile that stops short of the axis sweeps into a tube with no top, which draws
    the inside of a bushing where its end should be."""
    import vtkmodules.all as vtk

    from perfboard_studio.ui import view3d

    # Welded first: the normals split the surface at every crease and the sweep does not
    # join its last column of points to its first, and neither of those is a hole.
    welded = vtk.vtkCleanPolyData()
    welded.SetInputData(view3d._lathe(view3d._threaded_profile(3.5, 2.2), resolution=24))
    welded.ToleranceIsAbsoluteOn()
    welded.SetAbsoluteTolerance(1e-6)
    edges = vtk.vtkFeatureEdges()
    edges.SetInputConnection(welded.GetOutputPort())
    edges.BoundaryEdgesOn()
    edges.FeatureEdgesOff()
    edges.NonManifoldEdgesOff()
    edges.ManifoldEdgesOff()
    edges.Update()
    assert edges.GetOutput().GetNumberOfCells() == 0


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
    from where the 3D view and DRC both put it. docs/ARCHITECTURE.md says not to do that,
    and has since the feature was written."""
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
    """A board whose corner bore is drilled through an edge-connector finger: a 9 x 15 cm
    board with a strip laid ON its bottom row. (The stock boards' strips stand outside the
    grid and clear of their corner holes, so the case is made here on purpose.)"""
    from perfboard_studio.boardfamily import STANDARD_PRESETS, board_from_preset
    from perfboard_studio.commands import DEFAULT_BOARD, create_empty_document
    from perfboard_studio.model import DocumentMeta, EdgeConnector, MountingHole

    preset = next(p for p in STANDARD_PRESETS if p.name == "9 x 15 cm" and not p.single_sided)
    board = board_from_preset(preset, DEFAULT_BOARD)
    document = create_empty_document(DocumentMeta(name="b", created="", modified=""), board)
    return dataclasses.replace(
        document,
        edge_connectors=(
            EdgeConnector(id="ec-bottom", edge="bottom", start=0, count=board.cols, inset_mm=1.5),
        ),
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


def test_autosave_never_writes_over_a_file_somebody_else_changed(tmp_path) -> None:
    """A window with unsaved edits does not reload when the file changes underneath it,
    and autosave must not then settle the question by writing over the other version: an
    agent's or an editor's change would vanish without anyone choosing it. The edit is
    kept in the recovery record instead, and the window says why."""
    path = tmp_path / "board.perf"
    window = _window_on(_load_dense())
    window.current_path = path
    assert window._save_to(path)

    edited = _new_bus(window.bus.document)
    edited.dispatch(
        "component.move",
        MoveComponentPayload(id=edited.document.components[0].id, anchor=HoleCoord(9, 9)),
    )
    _write(path, edited.document)
    theirs = path.read_text(encoding="utf-8")

    window.bus.dispatch(
        "component.move",
        MoveComponentPayload(id=window.bus.document.components[1].id, anchor=HoleCoord(2, 2)),
    )
    window._on_autosave_tick()

    assert path.read_text(encoding="utf-8") == theirs
    assert window.is_modified
    assert window._autosave.written
    assert "changed on disk" in window.statusBar().currentMessage()
    _close(window)


def test_autosave_leaves_a_recovered_boards_file_alone_until_it_is_saved(tmp_path) -> None:
    """Recovery touches nothing on disk until the user saves, and autosave must not do it
    for them half a minute later. A recovered board names its file without having come
    from it, so there is no deliberate save of it to back up -- autosave used to write it
    over the file with no .bak at all and mark the window saved. Ctrl+S still does."""
    from perfboard_studio.recovery import RecoveryRecord

    board = tmp_path / "amp.perf"
    board.write_text("a different, older board", encoding="utf-8")
    window = _window_on(_load_dense())
    try:
        record = RecoveryRecord(
            session="gone", document_path=str(board),
            saved_at="2026-08-31T14:00:00.000Z", version="0.9.0",
            document=persist.serialize_document(_load_dense()),
        )
        assert window._load_recovered(record) is True
        window._on_autosave_tick()

        assert board.read_text(encoding="utf-8") == "a different, older board"
        assert not (tmp_path / "amp.perf.bak").exists()
        assert window.is_modified
        assert window._autosave.written, "the recovery record still holds the work"

        assert window._save_to(board)
        assert persist.deserialize_document(board.read_text(encoding="utf-8")).ok
    finally:
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


def test_home_is_not_offered_over_a_board() -> None:
    """Home is about what to do FIRST, and there is no first left once there is a board on
    the screen -- a document opened from the command line, or handed back by recovery."""
    window = _window_on(_load_dense())
    try:
        window.offer_home()
        assert not window.home_is_showing()
    finally:
        _close(window)


def test_home_starts_a_circuit_or_opens_an_example(monkeypatch) -> None:
    """Every door on Home is a command the window already had, taken once Home has gone:
    the first starts a circuit on the sheet, an example opens as an untitled copy, the
    tour starts the tour, and "show at start" is the setting it always was."""
    import perfboard_studio.ui.main as main_module

    examples = main_module.example_boards()
    assert examples, "the examples folder is part of the repository"
    assert examples[0][0].stem == "ne555-blinker"

    window = _blank_window()
    try:
        added: list[bool] = []
        opened: list[object] = []
        toured: list[bool] = []
        monkeypatch.setattr(
            main_module.MainWindow, "on_schematic_add_part", lambda self: added.append(True)
        )
        monkeypatch.setattr(
            main_module.MainWindow, "on_open_example", lambda self, path: opened.append(path)
        )
        monkeypatch.setattr(main_module.MainWindow, "start_tour", lambda self: toured.append(True))

        window.offer_home()
        assert window.home_is_showing()
        home = window._home_page
        assert home is not None
        home.newCircuit.emit()
        assert not window.home_is_showing()
        assert window.schematic_is_showing() and added == [True]

        window.offer_home()
        home.openExample.emit(str(examples[1][0]))
        assert not window.home_is_showing() and opened == [examples[1][0]]

        window.offer_home()
        home.startTour.emit()
        assert not window.home_is_showing() and toured == [True]

        window.offer_home()
        home.showAtStartChanged.emit(False)
        window.leave_home()
        window.offer_home()
        assert not window.home_is_showing(), "switched off, it is not offered"
    finally:
        _close(window)


def test_escape_leaves_home() -> None:
    """Escape leaves any mode the window is in, and Home is the first of them."""
    window = _blank_window()
    try:
        window.offer_home()
        assert window.home_is_showing()
        window.on_stop_tool()
        assert not window.home_is_showing()
    finally:
        _close(window)


def test_a_board_the_question_offered_is_never_refused_over_copper_left_on_the_old_one(
    monkeypatch,
) -> None:
    """A board trial judges a board with the copper stripped, so the question offered a
    smaller board the command then refused over a wire still on the old one -- "Conductor
    cond-133 passes through L23" in a bare warning. Now the window says how much will not
    fit and takes it up with the board, one undo step; declined, nothing changes."""
    import perfboard_studio.ui.main as main_module
    from perfboard_studio.boardfamily import STANDARD_PRESETS, board_from_preset
    from perfboard_studio.boardfit import BoardChoice
    from perfboard_studio.commands import UnplaceComponentPayload
    from perfboard_studio.placer import BoardSuggestion

    window = _window_on(_example_document("atmega328-relay"))
    try:
        for component in window.bus.document.components:
            window.bus.dispatch("component.unplace", UnplaceComponentPayload(id=component.id))
        before = window.bus.document
        smaller = next(p for p in STANDARD_PRESETS if not p.single_sided and p.name == "6 x 8 cm")
        chosen = BoardSuggestion(smaller, board_from_preset(smaller, before.board), None)
        choice = BoardChoice((chosen,), chosen, (), chosen, True)
        warned: list[str] = []
        monkeypatch.setattr(
            main_module.QMessageBox, "warning", lambda *args: warned.append(str(args[2]))
        )
        asked: list[str] = []
        answer = [False]

        def confirm(self, title, body, verb):
            asked.append(body)
            return answer[0]

        monkeypatch.setattr(type(window), "_confirm", confirm)

        assert not window._use_board(choice, chosen)
        assert window.bus.document is before, "declined, the board is as it was"
        assert len(asked) == 1 and "conductors" in asked[0]

        answer[0] = True
        assert window._use_board(choice, chosen)
        assert not warned, "never a bare refusal for a board the question offered"
        assert window.bus.document.board.cols == chosen.board.cols
        assert len(window.bus.document.conductors) < len(before.conductors)
        window.bus.undo()
        assert window.bus.document == before, "one Ctrl+Z puts the board and its copper back"
    finally:
        _close(window)


def test_a_document_opened_through_any_door_takes_home_away() -> None:
    """Home's cards leave Home before they open anything, but the menu bar is still there
    under it: File > Examples, Ctrl+O, Ctrl+N and the command palette all opened a board
    BEHIND Home, which stayed in front of it with nothing saying a board had arrived."""
    import perfboard_studio.ui.main as main_module

    examples = main_module.example_boards()
    window = _blank_window()
    try:
        window.offer_home()
        assert window.home_is_showing()
        window.on_open_example(examples[1][0])
        assert not window.home_is_showing(), "an example from File > Examples"
        assert window.board_is_showing(), "and the board it opened is the one in front"

        window._saved_document = window.bus.system_document
        window._mark_saved()
        window.show_home(window._make_home())
        assert window.home_is_showing()
        window.on_new()
        assert not window.home_is_showing(), "a new board from Ctrl+N"
    finally:
        _close(window)


def test_home_stands_in_front_of_the_whole_window_and_leaves_it_as_it_was(monkeypatch) -> None:
    """Home is the whole window: no panel, no header, no status bar around it. Leaving it
    puts back exactly what was there, and a window closed while it shows saves the panels
    it covered, not a window of nothing."""
    from PySide6.QtWidgets import QApplication, QDockWidget, QLabel

    from perfboard_studio.ui.main import WINDOW_STATE_KEY, app_settings

    window = _shown_window_without_3d(monkeypatch)
    try:
        window.show_schematic()
        _settle_events(QApplication)
        open_before = {d.objectName() for d in window.findChildren(QDockWidget) if not d.isHidden()}
        window.show_home(QLabel("home"))
        _settle_events(QApplication)
        assert window.home_is_showing()
        assert window.centralWidget().maximumWidth() > 0
        assert all(d.isHidden() for d in window.findChildren(QDockWidget))
        assert window.header_strip.isHidden() and window.statusBar().isHidden()

        covered = window._layout_before_home
        window._save_session()  # what a close while Home shows would keep
        assert app_settings().value(WINDOW_STATE_KEY) == covered

        window.leave_home()
        _settle_events(QApplication)
        assert not window.home_is_showing()
        assert not window.header_strip.isHidden() and not window.statusBar().isHidden()
        open_after = {d.objectName() for d in window.findChildren(QDockWidget) if not d.isHidden()}
        assert open_after == open_before
        assert window.is_showing(window.dock_schematic)
        assert window.centralWidget().maximumWidth() == 0
        window.leave_home()  # again: nothing
        assert not window.home_is_showing()
    finally:
        _close(window)


def test_home_before_the_first_showing_still_gets_the_opening_proportions(monkeypatch) -> None:
    """Home is put up before the window is first shown, so the opening proportions -- the
    sidebar 300 px, the board the rest -- could not be pinned then: they are pinned when
    Home goes. Without that the sidebar took 1318 px of a 1600 px window."""
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.main import MainWindow

    monkeypatch.setattr(MainWindow, "_create_3d_widget", lambda self: None)
    window = _blank_window()
    try:
        window.offer_home()
        window.resize(1600, 950)
        window.show()
        _settle_events(QApplication)
        window.leave_home()
        _settle_events(QApplication, rounds=60)
        assert window.dock_library.width() < 600
        # Measured on the view in front: one behind its tab keeps whatever width it last had.
        front = window.dock_schematic if window.schematic_is_showing() else window.dock_board
        assert front.width() > 800
    finally:
        _close(window)


def test_a_project_name_becomes_the_folder_and_the_document(tmp_path, monkeypatch) -> None:
    """New Project makes the directory, saves the board into it immediately and starts in
    the schematic. A board with a home has somewhere to autosave to and something to put
    in the recent list; an untitled one has neither until it is saved.

    And it asks no board: that is the Board step's, once there is a circuit to try on it.
    It used to ask here too, and a breadboard chosen in New Project was chosen again."""
    window = _blank_window()
    monkeypatch.setattr(
        "perfboard_studio.ui.main.MainWindow._ask_name",
        lambda self, *args, **kwargs: ("NE555 Astable", True),
    )
    monkeypatch.setattr(
        "perfboard_studio.ui.main.QFileDialog.getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(tmp_path)),
    )
    import perfboard_studio.ui.main as main_module

    asked: list[str] = []
    from perfboard_studio.ui import designer as designer_module

    monkeypatch.setattr(
        designer_module.BoardDesigner,
        "exec",
        lambda self: asked.append("board") or int(main_module.QDialog.DialogCode.Accepted),
    )

    window.on_new_project()

    folder = tmp_path / "ne555-astable"
    assert (folder / "ne555-astable.perf").is_file()
    assert window.current_path == folder / "ne555-astable.perf"
    assert not window.is_modified
    assert window.schematic_is_showing()
    assert asked == []
    assert window.workflow_bar.buttons["board"].property("status") == "todo"
    _close(window)


def test_the_board_question_has_a_way_to_the_other_kinds_of_board(monkeypatch) -> None:
    """A breadboard or a stripboard is not a stock perfboard size, and New Project no longer
    asks which kind: Other Board, beside the stock sizes, goes to the board designer, and what it
    set up is the board kept."""
    import perfboard_studio.ui.main as main_module
    from perfboard_studio.boardfit import BoardChoice
    from perfboard_studio.placer import recommended_board, suggest_boards
    from perfboard_studio.ui.main import BoardSizeDialog, design_entries

    window = _blank_window()
    document = window.bus.document
    suggestions = suggest_boards(
        document.board, design_entries(document), document.nets, window.lookup
    )
    reference = recommended_board(suggestions) if suggestions else None
    choice = BoardChoice(tuple(suggestions), reference, (), reference, False)
    set_up: list[bool] = []
    monkeypatch.setattr(main_module.MainWindow, "on_design_board", lambda self: set_up.append(True) or True)
    monkeypatch.setattr(BoardSizeDialog, "exec", lambda self: BoardSizeDialog.OTHER_BOARD)
    assert window._ask_which_board(choice, document) == (True, None)
    assert set_up == [True]
    _close(window)


# ---------------------------------------------------------------------------
# What a part says about itself
# ---------------------------------------------------------------------------


def test_the_pinout_editor_shows_and_returns_a_declaration() -> None:
    """A row per footprint pin, the declared names in them, and back out in normal form."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.partfields import PinoutEditor

    editor = PinoutEditor()
    editor.set_part(get_footprint("to220"), (("1", "G"), ("2", "D"), ("3", "S")), "pmos")
    assert editor.table.rowCount() == 3
    assert editor.values() == ((("1", "G"), ("2", "D"), ("3", "S")), "pmos")
    editor.deleteLater()


def test_the_pinout_editor_keeps_typed_names_across_a_footprint_change() -> None:
    """Pin 3 survives a footprint that still has a pin 3; pin 5 does not survive one that
    has three pins, rather than being kept where nothing shows it."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.partfields import PinoutEditor

    editor = PinoutEditor()
    editor.set_part(get_footprint("dip-8"), (("3", "VCC"), ("5", "Vref")), None)
    editor.set_footprint(get_footprint("to92"))
    assert editor.values() == ((("3", "VCC"),), None)
    editor.deleteLater()


def test_a_registry_pin_name_is_a_hint_not_a_declaration() -> None:
    """An LED's A and K are the footprint's; leaving them untouched declares nothing, so
    nothing is written to the part and nothing changes in the file."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.partfields import PinoutEditor

    editor = PinoutEditor()
    editor.set_part(get_footprint("led-5mm"), (), None)
    assert editor.values() == ((), None)
    editor.deleteLater()


def test_properties_writes_a_declaration_in_the_same_undo_step() -> None:
    """A value that names a catalog part in the part's package brings its pinout, in the
    same step as the value: BC547 typed onto a TO-92 is C-B-E and an NPN at once."""
    from perfboard_studio.commands import UpdateComponentPayload

    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    assert window.bus.dispatch(
        "component.update", UpdateComponentPayload(id=component.id, footprint_id="to92")
    ).ok
    before = len(window.bus.history())
    editor = _inspect(window, component.id)

    _type_into(editor.value, "BC547")

    edited = next(c for c in window.bus.document.components if c.id == component.id)
    assert edited.value == "BC547"
    assert (edited.pin_names, edited.symbol) == (BC547_PINS, "npn")
    assert len(window.bus.history()) == before + 1
    _close(window)


BC547_PINS = (("1", "C"), ("2", "B"), ("3", "E"))
N2N3904_PINS = (("1", "E"), ("2", "B"), ("3", "C"))


def test_a_value_typed_over_a_catalog_part_takes_the_pinout_that_came_with_it() -> None:
    """BC547 to 2N3904 on one TO-92: the C-B-E the BC547 brought is wrong under a part
    that is E-B-C, so the new value's pinout replaces it. Names somebody TYPED are a
    declaration, and stay; so does everything when the package or the part does not change."""
    from perfboard_studio.ui.partfields import pinout_for_retyped_value

    def follows(before: str, after: str, names: dict[str, str], footprint: str = "to92"):
        part = pinout_for_retyped_value(footprint, before, after, names)
        return part.id if part is not None else None

    assert follows("BC547", "2N3904", dict(BC547_PINS)) == "2n3904"
    # Nothing named yet: the value brings its pinout, as it always did.
    assert follows("", "2N3904", {}) == "2n3904"
    # Typed by somebody: not the old value's pinout, so not the value's to replace.
    assert follows("BC547", "2N3904", {"1": "C", "2": "B", "3": "EMITTER"}) is None
    # The same part under another spelling, or a value that is no catalog part.
    assert follows("BC547", "BC547B", dict(BC547_PINS)) is None
    assert follows("BC547", "10k", dict(BC547_PINS)) is None
    # A part in another package is not this one, whatever its name.
    assert follows("BC547", "NE555", dict(BC547_PINS)) is None


def test_part_properties_follows_a_retyped_value_and_says_so() -> None:
    from perfboard_studio.commands import UpdateComponentPayload

    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    assert window.bus.dispatch(
        "component.update",
        UpdateComponentPayload(
            id=component.id, footprint_id="to92", value="BC547", pin_names=BC547_PINS,
            symbol="npn",
        ),
    ).ok
    editor = _inspect(window, component.id)
    assert editor.pinout.note.text() == ""
    _type_into(editor.value, "2N3904")
    edited = next(c for c in window.bus.document.components if c.id == component.id)
    assert (edited.pin_names, edited.symbol) == (N2N3904_PINS, "npn")
    assert "2N3904" in editor.pinout.note.text()

    # A pinout somebody typed is kept, and the catalog's other answer is said beside it.
    typed = (("1", "C"), ("2", "B"), ("3", "EMIT"))
    assert window.bus.dispatch(
        "component.update", UpdateComponentPayload(id=component.id, pin_names=typed)
    ).ok
    _type_into(editor.value, "BC547")
    _type_into(editor.value, "2N3904")
    kept = next(c for c in window.bus.document.components if c.id == component.id)
    assert kept.pin_names == typed
    assert "1=E 2=B 3=C" in editor.pinout.note.text()
    _close(window)


def test_editing_a_design_part_follows_a_retyped_value_too() -> None:
    """BC547 to 2N3904 on a TO-92 still only in the design: its pinout follows, in
    Properties as on a placed part."""
    from perfboard_studio.commands import AddPartPayload

    window = _blank_window()
    try:
        assert window.bus.dispatch(
            "part.add",
            AddPartPayload(
                ref="Q1", footprint_id="to92", value="BC547", pin_names=BC547_PINS, symbol="npn"
            ),
        ).ok
        window._show_symbol_in_properties("Q1")
        editor = window.inspector.design_part_editor
        _type_into(editor.value, "2N3904")
        part = window.bus.document.parts[0]
        assert (part.pin_names, part.symbol) == (N2N3904_PINS, "npn")
    finally:
        _close(window)


def _choose_in_change_part(monkeypatch, footprint_id: str, seen: list | None = None) -> None:
    """Stand in for a person picking ``footprint_id`` in the package picker."""
    from perfboard_studio.ui import main as main_module

    def pick(dialog):
        if seen is not None:
            seen.append(dialog)
        dialog.select_footprint(footprint_id)
        return main_module.QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_module.PackagePicker, "exec", pick)


def test_change_part_puts_another_package_on_the_same_holes(monkeypatch) -> None:
    """A 5 mm LED that should have been 3 mm meant delete, add and wire again. Now it is one
    ``component.update``: one undo step, the same id, pin 1 in the same hole, the same nets
    -- and the lead bends bent for the old pins said to go, and gone."""
    from perfboard_studio.model import LeadBendConductor

    dense = _load_dense()
    led = next(c for c in dense.components if c.footprint_id == "led-5mm")
    bend = LeadBendConductor(
        id="cond-bend", path=(led.anchor, HoleCoord(led.anchor.col, led.anchor.row + 1)),
        component_id=led.id, pin_number="1",
    )
    window = _window_on(dataclasses.replace(dense, conductors=(*dense.conductors, bend)))
    nets_before = window.bus.document.nets
    before = len(window.bus.history())
    seen: list = []
    _choose_in_change_part(monkeypatch, "led-3mm", seen)

    assert window.on_change_part(led.id)
    changed = next(c for c in window.bus.document.components if c.id == led.id)
    assert (changed.footprint_id, changed.anchor, changed.ref, changed.value) == (
        "led-3mm", led.anchor, led.ref, led.value
    )
    assert window.bus.document.nets == nets_before
    assert len(window.bus.history()) == before + 1
    assert "cond-bend" not in {c.id for c in window.bus.document.conductors}
    # Said before OK, not discovered after it.
    assert "lead bend" in seen[0].notice.text() and not seen[0].notice.isHidden()
    _close(window)


def test_a_locked_part_says_why_it_cannot_change(monkeypatch) -> None:
    """The command refuses a locked part a new package; the window says so where the
    choice is offered rather than after a dialog the user filled in."""
    from perfboard_studio.commands import UpdateComponentPayload

    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    assert window.bus.dispatch(
        "component.update", UpdateComponentPayload(id=component.id, locked=True)
    ).ok
    locked = next(c for c in window.bus.document.components if c.id == component.id)

    editor = _inspect(window, locked.id)
    assert not editor.change_part.isEnabled()
    assert not editor.locked_note.isHidden()

    assert not window.act_change_part.isEnabled()
    assert locked.ref in window.act_change_part.toolTip()
    asked: list = []
    _choose_in_change_part(monkeypatch, "to92", asked)
    assert not window.on_change_part(locked.id)
    assert asked == []
    assert locked.ref in window.statusBar().currentMessage()
    _close(window)


def test_change_in_properties_puts_another_package_on_the_part(monkeypatch) -> None:
    """Change… beside the package is Change Part, for this part: the same holes and nets."""
    window = _window_on(_load_dense())
    component = next(c for c in window.bus.document.components if c.footprint_id == "r-axial-4")
    editor = _inspect(window, component.id)
    _choose_in_change_part(monkeypatch, "r-axial-5")
    editor.change_part.click()
    changed = next(c for c in window.bus.document.components if c.id == component.id)
    assert (changed.footprint_id, changed.anchor) == ("r-axial-5", component.anchor)
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


def test_file_dialogs_never_start_in_the_folder_the_process_started_in(
    tmp_path, monkeypatch, _settings_in_a_temp_file
) -> None:
    """From the Start menu the process starts in the folder the application is installed
    in, and Save As used to propose ``board.perf`` there. A board with no file starts
    beside the board opened last, else in the user's documents, named after itself."""
    from perfboard_studio.model import UNTITLED_NAME
    from perfboard_studio.ui import main as main_module

    install = tmp_path / "Program Files" / "Perfboard Studio"
    install.mkdir(parents=True)
    monkeypatch.chdir(install)
    documents = tmp_path / "Documents"
    documents.mkdir()
    monkeypatch.setattr(
        main_module.QStandardPaths, "writableLocation", lambda _where: str(documents)
    )
    asked: list[str] = []

    def ask(*args, **kwargs):
        asked.append(args[2])
        return ("", "")

    monkeypatch.setattr(main_module.QFileDialog, "getSaveFileName", ask)
    monkeypatch.setattr(main_module.QFileDialog, "getOpenFileName", ask)

    dense = _load_dense()
    window = _window_on(dataclasses.replace(
        dense, meta=dataclasses.replace(dense.meta, name="NE555 Astable")
    ))
    assert window.current_path is None
    window.on_save_as()
    assert asked[-1] == str(documents / "ne555-astable.perf")
    untitled = _window_on(dataclasses.replace(
        dense, meta=dataclasses.replace(dense.meta, name=UNTITLED_NAME)
    ))
    untitled.on_save_as()
    assert asked[-1] == str(documents / "board.perf")
    _close(untitled)

    # A board opened before says where this person keeps boards.
    boards = tmp_path / "boards"
    boards.mkdir()
    (boards / "old.perf").write_text("{}", encoding="utf-8")
    _settings_in_a_temp_file.setValue(main_module.RECENT_FILES_KEY, [str(boards / "old.perf")])
    window._mark_saved()
    window.on_open()
    window.on_import_netlist()
    assert asked[-2:] == [str(boards), str(boards)]
    assert not any(entry.startswith(str(install)) for entry in asked)
    _close(window)


def test_the_first_project_goes_in_the_documents_folder(
    tmp_path, monkeypatch, _settings_in_a_temp_file
) -> None:
    """Every file dialog started in the user's documents but New Project's, which asked
    where the project should go from the home folder -- beside AppData and the dotfiles."""
    from perfboard_studio.ui import main as main_module

    documents = tmp_path / "Documents"
    documents.mkdir()
    monkeypatch.setattr(
        main_module.QStandardPaths, "writableLocation", lambda _where: str(documents)
    )
    monkeypatch.setattr(
        main_module.MainWindow, "_ask_name", lambda self, *args, **kwargs: ("Blinker", True)
    )
    started: list[str] = []
    monkeypatch.setattr(
        main_module.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: started.append(args[2]) or ""),
    )
    window = _blank_window()
    try:
        window.on_new_project()
        assert started == [str(documents)]
    finally:
        _close(window)


def test_a_named_board_is_not_renamed_by_saving(tmp_path) -> None:
    window = _window_on(_load_dense())
    before = window.bus.document.meta.name
    assert before != "untitled"
    assert window._save_to(tmp_path / "elsewhere.perf")
    assert window.bus.document.meta.name == before
    _close(window)


def test_rename_board_is_the_boards_name_in_properties() -> None:
    """Rename Board lets the selection go and puts the keyboard in the board's Name;
    a name is one undo step, and the same name again is none."""
    window = _window_on(_load_dense())
    window.scene.select_components([window.bus.document.components[0].id])
    before = len(window.bus.history())
    window.on_rename_board()
    editor = window.inspector.board_editor
    assert window.inspector.shown is editor
    _type_into(editor.name, "Plaket v1")
    assert window.bus.document.meta.name == "Plaket v1"
    assert len(window.bus.history()) == before + 1
    _type_into(editor.name, "Plaket v1")
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


def test_every_package_family_has_a_heading_in_the_parts_panel() -> None:
    """A package group was headed by its archetype's id with the hyphens taken out --
    "axial cylinder", "box film", "to92" -- in both languages."""
    from typing import get_args

    from perfboard_studio.model import BodyArchetype
    from perfboard_studio.ui.main import _archetype_headings

    assert set(_archetype_headings()) == set(get_args(BodyArchetype))


def test_no_package_group_is_named_like_a_catalog_group() -> None:
    """"LEDs" was two headings side by side in the Library, the catalog's and the package
    family's, and so was "Relays" -- in both languages. A family named like a category
    says it is the package ("LED packages", "LED kılıfları")."""
    from perfboard_studio.ui.i18n import language, set_language
    from perfboard_studio.ui.main import _archetype_headings, _catalog_headings

    before = language()
    try:
        for code in ("en", "tr"):
            set_language(code)
            catalog = {name.casefold() for name in _catalog_headings().values()}
            clashes = sorted(
                name for name in _archetype_headings().values() if name.casefold() in catalog
            )
            assert clashes == [], f"{code}: {clashes}"
    finally:
        set_language(before)


def test_the_parts_panel_names_its_packages_in_turkish() -> None:
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        window = _blank_window()
        try:
            tree = window.library_tree
            groups = {tree.topLevelItem(i).text(0): tree.topLevelItem(i)
                      for i in range(tree.topLevelItemCount())}
            assert "axial cylinder" not in groups
            axial = groups["Eksenel dirençler ve diyotlar"]
            names = [axial.child(i).text(0) for i in range(axial.childCount())]
            assert "Direnç (eksenel, 3 delik açıklık)" in names
            # And the filter finds a part by its Turkish name as well as its English one.
            window.library_filter.setText("direnç")
            assert tree.topLevelItemCount() > 0
        finally:
            _close(window)
    finally:
        set_language(before)


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
        assert window.placing_value.text() == "BC547"
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
        assert window.placing_value.text() == ""
        assert window.scene.placement_pin_names == () and window.scene.placement_symbol is None
        window.scene.place_armed(HoleCoord(4, 4))
        (part,) = window.bus.document.components
        assert (part.value, part.pin_names, part.symbol) == ("", (), None)

        window.placing_value.setText("2N3904")
        tree.setCurrentItem(_catalog_leaf(window, "bc557"))
        tree.setCurrentItem(bare)
        assert window.placing_value.text() == ""  # the catalog's BC557 went back out
        window.placing_value.setText("mine")
        tree.setCurrentItem(bare)
        assert window.placing_value.text() == "mine"
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


def test_every_catalog_category_has_a_heading_and_power_is_found_from_nothing() -> None:
    """A category with no heading is a KeyError the moment the panel fills. And a first
    circuit drawn from nothing -- a 555 blinker -- has to be able to find its battery."""
    from perfboard_studio.catalog import CATEGORY_ORDER
    from perfboard_studio.ui.main import _catalog_headings

    assert set(_catalog_headings()) == set(CATEGORY_ORDER)
    window = _blank_window()
    try:
        for typed, part_id in (("battery", "battery-9v-clip"), ("jack", "dc-jack-panel")):
            window.library_filter.setText(typed)
            assert _catalog_leaf(window, part_id) is not None, typed
    finally:
        _close(window)


def test_the_filter_reads_words_the_way_the_catalog_search_does() -> None:
    """The panel asks ``catalog.part_matches``, the same question ``list_catalog`` asks: it
    used to look for the whole text as one piece, so "op amp" found nothing here while the
    MCP server found the LM358, and a number with its package letter on found nothing at all."""
    window = _blank_window()
    try:
        for typed, part_id in (("LM358N", "lm358"), ("op amp", "lm358"), ("28BYJ-48", "uln2003a")):
            window.library_filter.setText(typed)
            assert _catalog_leaf(window, part_id) is not None, typed
            assert _catalog_leaf(window, "bc547") is None, typed
    finally:
        _close(window)


def test_in_turkish_the_catalog_says_what_a_part_is_in_turkish() -> None:
    """The tooltip under a Turkish parts list, and the filter, in the user's language."""
    from perfboard_studio.catalog import catalog_part
    from perfboard_studio.ui.i18n import language, set_language
    from perfboard_studio.ui.main import _catalog_tooltip

    before = language()
    set_language("tr")
    try:
        part = catalog_part("7805")
        assert part is not None
        tip = _catalog_tooltip(part)
        assert "Lineer regülatör" in tip and "Tırnak toprağa bağlıdır" in tip
        window = _blank_window()
        try:
            window.library_filter.setText("regülatör")
            assert _catalog_leaf(window, "7805") is not None
            assert _catalog_leaf(window, "bc547") is None
        finally:
            _close(window)
    finally:
        set_language(before)


def test_in_turkish_a_part_named_for_what_it_is_is_named_in_turkish() -> None:
    """"Tactile switch 6x6 mm" sat in English beside the package row "Tact buton, 4 pin". A
    name that describes the part is said in the window's language, and found by it; a part
    NUMBER is printed as it is on the part."""
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        window = _blank_window()
        try:
            window.library_filter.setText("buton")
            switch = _catalog_leaf(window, "tact-6x6")
            assert switch is not None and switch.text(0) == "Tact buton 6×6 mm"
            window.library_filter.setText("BC547")
            transistor = _catalog_leaf(window, "bc547")
            assert transistor is not None and transistor.text(0) == "BC547"
        finally:
            _close(window)
    finally:
        set_language(before)


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
    assert "4 names for 6 pins." in dialog.summary.text()
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


def test_a_label_dragged_past_the_edge_stays_on_the_board() -> None:
    """Held at the edge, not let go past it: the command would refuse a label off the board
    and send it back to where the drag began."""
    window = _blank_window()
    try:
        board = window.bus.document.board
        window.add_board_label("EDGE", QPointF(2 * board.pitch, 2 * board.pitch))
        (item,) = _label_items(window)
        item.setPos(QPointF(-50.0, board.rows * board.pitch + 50.0))
        results = window.scene.commit_pending_moves()
        assert results and all(r.ok for r in results)
        (note,) = window.bus.document.board_notes
        assert note.at == HoleCoord(0, board.rows - 1)
        assert note.offset_x_mm < 0 and note.offset_y_mm > 0
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



def test_the_status_bar_does_not_count_pins_waiting_for_their_wiring() -> None:
    """The step bar's rule, on the status bar: pins that touch nothing while connections are
    left to route are not counted as warnings there either."""
    from perfboard_studio.ratsnest import summarize

    window = _window_on(dataclasses.replace(_load_dense(), conductors=()))
    try:
        assert summarize(window._last_ratsnest).links > 0
        unwired = window.workflow_facts().drc_unwired
        assert unwired > 0
        warnings = sum(1 for v in window._last_violations if v.severity == "warning")
        erc_warnings = sum(1 for f in window._last_erc if f.severity == "warning")
        assert window.problems_bar.warnings == warnings - unwired + erc_warnings
    finally:
        _close(window)


def test_the_findings_do_not_call_pins_waiting_for_their_wiring_violations() -> None:
    """The bar read "DRC 0 err / 0 warn" over a placed, unrouted NE555 while the findings
    said "28 violation(s)" over "Pin connected to nothing (warning)" in amber. While there
    is wiring left to do, those pins are counted apart, said as the work left to do, dimmed
    as LVS's unwired nets are and listed after anything wrong; once nothing is left to
    route, a pin touching nothing is a warning again."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.lvs import run_lvs
    from perfboard_studio.model import Net, NetNode
    from perfboard_studio.ratsnest import summarize
    from perfboard_studio.ui.theme import TEXT_DIM, WARNING

    window = _window_on(dataclasses.replace(_load_dense(), conductors=()))
    try:
        assert summarize(window._last_ratsnest).links > 0
        unwired = window.workflow_facts().drc_unwired
        assert unwired > 0
        root = _findings_root(window, "DRC")
        wrong = len(window._last_violations) - unwired
        # Real plurals: "1 problem", "28 pins" (i18n.counted).
        problems = f"{wrong} problem" + ("" if wrong == 1 else "s")
        pins = f"{unwired} pin" + ("" if unwired == 1 else "s")
        assert root.text(1) == f"{problems} · {pins} not wired yet"
        group = _drc_group(window, "drc:pin-not-connected")
        assert group is not None
        assert (group.text(0), group.text(1)) == ("Pin not wired yet", str(unwired))
        dimmed = group.foreground(0).color().name()
        assert dimmed == TEXT_DIM.lower()
        assert dimmed == _drc_group(window, "lvs:unrouted-net").foreground(0).color().name()
        last = root.child(root.childCount() - 1)
        assert last.data(0, _finding_key_role()) == "drc:pin-not-connected"
    finally:
        _close(window)

    # Routed, with one pin a net names and nothing touches: that is a finding about the board.
    doc = _example_document("ne555-astable")
    named = {(node.component_ref, node.pin) for net in doc.nets for node in net.nodes}
    lone = next(
        (component.ref, pin.number)
        for component in doc.components
        if (footprint := get_footprint(component.footprint_id)) is not None
        for pin in footprint.pins
        if (component.ref, pin.number) not in named
    )
    doc = dataclasses.replace(
        doc, nets=(*doc.nets, Net(id="net-lone", name="LONE", nodes=(NetNode(*lone),)))
    )
    window = _window_on(doc)
    try:
        assert summarize(window._last_ratsnest).links == 0
        group = _drc_group(window, "drc:pin-not-connected")
        assert group is not None
        assert group.text(0).endswith("(warning)")
        assert group.foreground(0).color().name() == WARNING.lower()
        from perfboard_studio.guide import is_bench_check

        bench = sum(1 for v in window._last_violations if is_bench_check(v))
        wrong = len(window._last_violations) - bench
        assert _findings_root(window, "DRC").text(1) == (
            f"{wrong} problem" + ("" if wrong == 1 else "s")
            + (f" · {bench} to check at the bench" if bench else "")
        )
    finally:
        _close(window)

    # An open is an unrouted net some of whose pins are already joined (``lvs.py``): the
    # same work left to do, so it waits in the same colour, by the bar's own rule.
    doc = _example_document("ne555-astable")
    opened = None
    for conductor in doc.conductors:
        rest = tuple(c for c in doc.conductors if c is not conductor)
        candidate = dataclasses.replace(doc, conductors=rest)
        if any(issue.kind == "open" for issue in run_lvs(candidate, get_footprint).issues):
            opened = candidate
            break
    assert opened is not None, "one conductor taken away should leave a net in pieces"
    window = _window_on(opened)
    try:
        assert summarize(window._last_ratsnest).links > 0
        group = _drc_group(window, "lvs:open")
        assert group is not None
        assert group.foreground(0).color().name() == TEXT_DIM.lower()
    finally:
        _close(window)


def _a_short(doc: PerfDocument) -> PerfDocument:
    """``doc`` with an insulated wire from a pin of its first net to a pin of its second."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.geometry import pin_hole
    from perfboard_studio.model import WireConductor

    def hole(node):
        component = next(c for c in doc.components if c.ref == node.component_ref)
        footprint = get_footprint(component.footprint_id)
        assert footprint is not None
        return pin_hole(component, footprint, node.pin)

    a, b = hole(doc.nets[0].nodes[0]), hole(doc.nets[1].nodes[0])
    wire = WireConductor(id="w-short", path=(a, b), kind="insulated-wire")
    return dataclasses.replace(doc, conductors=(*doc.conductors, wire))


def test_the_findings_and_the_status_bar_colour_a_finding_by_one_rule() -> None:
    """The panel said "28 violation(s)" in amber under a bar reading "DRC 0 err / 0 warn",
    and an open was red in the panel and grey on the bar: two rules for one finding, which
    drifted. Both read ``work_left`` now, and this holds them to it on boards wired not at
    all, partly, fully, open, shorted, and on stripboard with its strips uncut: the bar
    counts as errors and warnings exactly the panel's red and amber rows, and its LVS
    colour is the colour the panel gives the opens and shorts."""
    from perfboard_studio.ratsnest import summarize
    from perfboard_studio.ui.theme import ERROR, OK, TEXT_DIM, WARNING

    example = _example_document("ne555-astable")
    strips = dataclasses.replace(
        example,
        board=dataclasses.replace(example.board, type="stripboard", strip_axis="horizontal"),
        conductors=(),
    )
    states = {
        "partly wired": _load_dense(),
        "not wired": dataclasses.replace(_load_dense(), conductors=()),
        "wired": example,
        "open": dataclasses.replace(example, conductors=example.conductors[1:]),
        "shorted": _a_short(example),
        "strips uncut": strips,
    }
    seen: set[tuple[str, str]] = set()
    for state, doc in states.items():
        window = _window_on(doc)
        try:
            wiring = summarize(window._last_ratsnest).links > 0
            drc = _findings_root(window, "DRC")
            counted = {ERROR.lower(): 0, WARNING.lower(): 0, TEXT_DIM.lower(): 0}
            for row in range(drc.childCount()):
                group = drc.child(row)
                counted[group.foreground(0).color().name()] += int(group.text(1))
            bar = window.problems_bar
            erc_errors = sum(1 for f in window._last_erc if f.severity == "error")
            erc_warnings = len(window._last_erc) - erc_errors
            assert bar.warnings == counted[WARNING.lower()] + erc_warnings, (state, counted)

            lvs = _findings_root(window, "LVS")
            colours = {}
            for row in range(lvs.childCount()):
                group = lvs.child(row)
                colours[group.toolTip(0)] = group.foreground(0).color().name()
            under = {colours[kind] for kind in ("open", "short", "unrouted-net") if kind in colours}
            assert len(under) <= 1, (state, colours)
            # The bar counts LVS's findings as errors exactly when the tree paints them red.
            lvs_red = next(iter(under), OK.lower()) == ERROR.lower()
            drc_and_erc = counted[ERROR.lower()] + erc_errors
            if lvs_red:
                assert bar.errors > drc_and_erc, (state, colours)
            else:
                assert bar.errors == drc_and_erc, (state, colours)
            seen |= {(kind, "wiring" if wiring else "wired") for kind in colours}
        finally:
            _close(window)
    # Every state the rule tells apart was reached, or the test would pass on less.
    for reached in [("open", "wiring"), ("short", "wiring"), ("short", "wired")]:
        assert reached in seen, (reached, sorted(seen))


def test_what_routing_says_carries_no_timing(monkeypatch) -> None:
    """"6/6 nets routed… (91 ms)": how long the router took is a number for whoever tunes
    it, not for somebody reading whether their board is wired -- which is why the DRC count
    lost its milliseconds to a tooltip. Perfboard and stripboard both."""
    import re

    example = _example_document("ne555-astable")
    strips = dataclasses.replace(
        example,
        board=dataclasses.replace(example.board, type="stripboard", strip_axis="horizontal"),
        conductors=(),
    )
    # What could not be routed is said in a dialog, which would wait for a click forever.
    monkeypatch.setattr("perfboard_studio.ui.main.QMessageBox.information", lambda *args, **kwargs: None)
    for doc in (_golden_document("ne555"), strips):
        window = _window_on(doc)
        try:
            window.on_autoroute_all()
            said = window.statusBar().currentMessage()
            assert said, doc.board.type
            assert not re.search(r"\d ms\b", said), said
        finally:
            _close(window)


def _routed_on_stripboard(monkeypatch):
    """ne555-astable on a stripboard, planned by the window: a board with tracks to cut."""
    # A problem the planner had is said in a dialog, which would wait for a click forever.
    monkeypatch.setattr("perfboard_studio.ui.main.QMessageBox.information", lambda *args, **kwargs: None)
    example = _example_document("ne555-astable")
    strips = dataclasses.replace(
        example,
        board=dataclasses.replace(example.board, type="stripboard", strip_axis="horizontal"),
        conductors=(),
    )
    window = _window_on(strips)
    window.on_autoroute_all()
    assert window.bus.document.cuts, "the planner should have cut a track"
    window._raise_view(window.dock_guide)
    window._refresh_guide_panel()
    return window


def _guide_rows(window):
    from perfboard_studio.ui.main import QTreeWidgetItemIterator

    found = QTreeWidgetItemIterator(window.guide_tree)
    rows = []
    while found.value() is not None:
        rows.append(found.value())
        found += 1
    return rows


def test_the_guide_panel_says_to_cut_the_tracks_first(monkeypatch, _settings_in_a_temp_file) -> None:
    """The export has a table of the tracks to cut, and the window's guide had nothing:
    the cuts were there only as "I11 ↔ K11 must be open" checks, and Next Step to Do went
    straight past them to the first resistor -- a board built from the window kept every
    strip whole. They are the first rows of Preparation now, ticked like steps, and the
    first place Next Step to Do stops."""
    from perfboard_studio.ui.main import ROLE_STEP_FOCUS

    window = _routed_on_stripboard(monkeypatch)
    try:
        guide = window.current_guide()
        assert guide.track_cuts
        heading = next(row for row in _guide_rows(window) if row.text(0).startswith("Cut these tracks first"))
        assert heading.text(0) == f"Cut these tracks first ({len(guide.track_cuts)})"
        # Open, not folded away: the first build of this opened the heading before it was
        # in the tree, and Qt keeps such an item shut.
        assert heading.isExpanded()
        assert not any(heading.child(i).isHidden() for i in range(heading.childCount()))
        assert "copper side" in heading.toolTip(0)
        cuts = [heading.child(i) for i in range(heading.childCount())]
        assert [row.text(0).split(" · ")[0] for row in cuts] == [
            format_hole(cut.at, window.bus.document.board) for cut in guide.track_cuts
        ]
        assert "to cut" in window.guide_summary.text() and "track" in window.guide_summary.text()
        # A cut's check says how to measure it, one hover away.
        check = next(row for row in _guide_rows(window) if "must be open" in row.text(0))
        assert "measure resistance" in check.toolTip(0)

        window.on_next_step_to_do()
        assert window.guide_tree.currentItem().text(0) == cuts[0].text(0)

        # Every cut ticked: Next Step to Do moves on to the first part, and the cuts stay
        # ticked across a rebuild of the panel.
        for row in cuts:
            row.setCheckState(0, Qt.CheckState.Checked)
        assert heading.text(0).endswith(f"({len(cuts)}/{len(cuts)})")
        window._refresh_guide_panel()
        window.on_next_step_to_do()
        picked = window.guide_tree.currentItem()
        assert not str(picked.data(0, ROLE_STEP_FOCUS)).startswith("cut:")
        assert picked.data(0, ROLE_STEP_FOCUS) is not None
    finally:
        _close(window)


def test_the_tracks_to_cut_are_said_in_turkish_in_a_turkish_window(
    monkeypatch, _settings_in_a_temp_file
) -> None:
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        window = _routed_on_stripboard(monkeypatch)
        try:
            texts = [row.text(0) for row in _guide_rows(window)]
            heading = next(row for row in _guide_rows(window) if row.text(0).startswith("Önce bu şeritleri kes"))
            assert "bakır" in heading.toolTip(0), heading.toolTip(0)
            assert not any(text.startswith("Cut these") for text in texts)
            assert "kesilecek" in window.guide_summary.text() and "şerit" in window.guide_summary.text()
        finally:
            _close(window)
    finally:
        set_language(before)


@pytest.mark.parametrize("footprint_id", ["led-3mm", "led-5mm", "led-10mm"])
def test_an_leds_flat_is_on_its_cathode_in_2d_too(footprint_id: str) -> None:
    """The 2D twin of ``test_model_leads::test_an_leds_flat_is_on_its_cathode``. The flat
    was cut on pin 1's side, which on an LED is the ANODE, so the board view, the guide's
    step images and the 1:1 print had it the other way round from the 3D view and the part:
    an LED fitted from the picture went in backwards."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.bodies import placement_for, polarity_pin_offset
    from perfboard_studio.ui.view2d import _body_path, _body_rect

    footprint = get_footprint(footprint_id)
    assert footprint is not None
    pitch = 2.54
    placement = placement_for(footprint, pitch)
    keyed = polarity_pin_offset(footprint, pitch)
    assert keyed is not None
    circle = _body_rect(placement)
    flat = _body_path(footprint, placement, keyed, pitch).boundingRect()
    cathode = next(pin for pin in footprint.pins if pin.name == "K")
    assert cathode.d_col * pitch > placement.centre_x, "the cathode is pin 2, to the right"
    # Cut on the cathode's side, and only there.
    assert flat.right() < circle.right() - 0.1
    assert flat.left() == pytest.approx(circle.left())


def test_an_rgb_leds_flat_is_beside_its_red_leg() -> None:
    """Kingbright's and Fedy's drawings put an RGB LED's flat beside red, pin 1, whatever the
    common leg is -- an anode on one LED and a cathode on the next."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.bodies import placement_for, polarity_pin_offset
    from perfboard_studio.ui.view2d import _body_path, _body_rect

    footprint = get_footprint("led-5mm-rgb")
    assert footprint is not None and footprint.pins[0].name == "R"
    pitch = 2.54
    placement = placement_for(footprint, pitch)
    keyed = polarity_pin_offset(footprint, pitch)
    assert keyed is not None and keyed[0] < placement.centre_x
    circle = _body_rect(placement)
    flat = _body_path(footprint, placement, keyed, pitch).boundingRect()
    assert flat.left() > circle.left() + 0.1
    assert flat.right() == pytest.approx(circle.right())


def test_the_sheets_text_is_read_where_the_sheet_opens() -> None:
    """A typical sheet opens at 3 to 5 px/mm, where its pin names were drawn 6 px tall and
    its references 8: nothing on it could be read without zooming in first. The floors are
    13/11/11/10 px (reference, value, net, pin), chosen on 2026-10-28 from sheets rendered
    side by side in both themes; they were 11/10/10/9 before."""
    from perfboard_studio.schematic import (
        NET_LABEL_MM,
        PIN_LABEL_MM,
        REF_LABEL_MM,
        VALUE_LABEL_MM,
    )
    from perfboard_studio.ui.viewsch import NET_PX, PIN_PX, REF_PX, VALUE_PX, label_px

    assert (REF_PX, VALUE_PX, NET_PX, PIN_PX) == (13, 11, 11, 10)
    for scale in (3.0, 4.0, 5.0):
        sizes = [
            label_px(REF_LABEL_MM, REF_PX, scale),
            label_px(VALUE_LABEL_MM, VALUE_PX, scale),
            label_px(NET_LABEL_MM, NET_PX, scale),
            label_px(PIN_LABEL_MM, PIN_PX, scale),
        ]
        assert min(sizes) >= 10, (scale, sizes)
    # Zoomed in, text is still its sheet size: the floor is a floor, not a fixed size.
    assert label_px(REF_LABEL_MM, REF_PX, 20.0) == round(REF_LABEL_MM * 20.0)


def test_a_check_is_marked_as_a_measurement_not_as_passed(
    monkeypatch, _settings_in_a_temp_file
) -> None:
    """A check was a green tick -- "passed", in the colour of a clean board -- before
    anything had been measured. It is an ohm sign in the accent colour, in bold when it
    must pass before power goes on, on a stripboard's cut checks and a perfboard's
    continuity checks alike."""
    from perfboard_studio.guide import all_checkpoints
    from perfboard_studio.ui import theme

    window = _routed_on_stripboard(monkeypatch)
    try:
        checks = {check.title: check for check in all_checkpoints(window.current_guide())}
        rows = [row for row in _guide_rows(window) if row.text(0).startswith("Ω ")]
        assert len(rows) == len(checks)
        assert not any(row.text(0).startswith("✓") for row in _guide_rows(window))
        blocking = set()
        for row in rows:
            check = checks[row.text(0).removeprefix("Ω ")]
            assert row.foreground(0).color().name() == theme.colour("accent"), row.text(0)
            assert row.font(0).bold() == check.blocking, row.text(0)
            blocking.add(check.blocking)
        assert blocking == {True, False}, "both kinds should be on this board"
    finally:
        _close(window)


def _take_the_dialogs_link(window, taken: list[str], tries: int = 200) -> None:
    """Click the link in the planner's progress dialog once it is up, polling for it."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLabel, QProgressDialog

    for dialog in window.findChildren(QProgressDialog):
        for label in dialog.findChildren(QLabel):
            if "<a " in label.text():
                taken.append(label.text())
                label.linkActivated.emit("aside")
                return
    if tries:
        QTimer.singleShot(25, lambda: _take_the_dialogs_link(window, taken, tries - 1))


def test_other_board_is_offered_while_the_boards_are_tried(monkeypatch) -> None:
    """Somebody holding a stripboard sat through every perfboard trial -- 8.6 s on the
    blinker -- before the dialog with Other Board came up, and then threw its verdicts away.
    The trial's own dialog offers it now: taken, the trial stops, the designer opens, no
    perfboard question is asked and nothing is remembered as judged."""
    import time

    from PySide6.QtCore import QTimer

    from perfboard_studio.ui import main as main_module

    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        stopped: list[bool] = []

        def choose(doc, lookup_, suggestions, should_stop=None, **_):
            deadline = time.monotonic() + 10
            while not should_stop() and time.monotonic() < deadline:
                time.sleep(0.01)
            stopped.append(should_stop())
            return _choice(doc, complete=False)

        asked: list[int] = []
        setup: list[int] = []
        monkeypatch.setattr(main_module, "choose_board", choose)
        monkeypatch.setattr(
            type(window), "_ask_which_board", lambda self, choice, doc: asked.append(1) or (True, None)
        )
        monkeypatch.setattr(type(window), "on_design_board", lambda self: setup.append(1) or True)

        taken: list[str] = []
        QTimer.singleShot(25, lambda: _take_the_dialogs_link(window, taken))
        assert window._offer_a_board_size(window.bus.document, always=True)

        assert taken and "Other Board…" in taken[0], "the link is on the trial's dialog"
        assert stopped == [True], "taking it stops the trial"
        assert setup == [1] and asked == [], "the designer, and no perfboard question"
        assert window._judged is None
        assert not window._planner_took_aside or setup, "only ever read straight after"
    finally:
        _close(window)


def test_only_the_board_question_offers_a_way_aside(monkeypatch) -> None:
    """Any other planner's dialog is as it was: Cancel, and no link in its label."""
    import time

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLabel, QProgressDialog

    window = _blank_window()
    try:
        seen: list[str] = []

        def look() -> None:
            for dialog in window.findChildren(QProgressDialog):
                seen.extend(label.text() for label in dialog.findChildren(QLabel))

        QTimer.singleShot(700, look)

        def work(should_stop):
            deadline = time.monotonic() + 1.2
            while not should_stop() and time.monotonic() < deadline:
                time.sleep(0.01)
            return "done"

        assert window._run_planner("Routing…", work) == "done"
        assert seen, "the dialog was up"
        assert not any("<a " in text for text in seen), seen
        assert not window._planner_took_aside
    finally:
        _close(window)


def test_part_values_are_printed_after_their_references() -> None:
    """#11: View > Show Part Values prints each part's value after its reference, on the
    reference's own plate -- "R1 10k" -- where the reference already is: over the body,
    never on a pin row or a pin name. Off by default, and nothing is printed for a part
    with no value."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        assert not window.act_values.isChecked() and not window.scene.show_values
        items = list(window.scene.component_items.values())
        assert all(item.shown_value() == "" for item in items)

        window.act_values.setChecked(True)
        assert window.scene.show_values
        for item in items:
            assert item.shown_value() == item.comp.value.strip(), item.comp.ref
        assert any(item.shown_value() for item in items)

        window.act_values.setChecked(False)
        assert all(item.shown_value() == "" for item in items)
    finally:
        _close(window)


def test_a_value_shares_its_references_plate() -> None:
    """One plate, one line: the value starts after the reference and both are inside the
    plate, which is centred where the reference alone would be."""
    from PySide6.QtCore import QPointF

    from perfboard_studio.ui.scenetext import reference_plate

    anchor = QPointF(200.0, 100.0)
    alone, _, _ = reference_plate(anchor, "R1", "", 12)
    plate, ref_box, value_box = reference_plate(anchor, "R1", "10k", 12)
    assert plate.width() > alone.width()
    assert value_box.left() >= ref_box.right()
    assert plate.contains(ref_box) and plate.contains(value_box)
    # Above the anchor, as the reference stands above its body.
    assert plate.bottom() <= anchor.y() + 1.0
    assert abs(plate.center().x() - anchor.x()) < 1.0
    assert abs(alone.center().x() - anchor.x()) < 1.0


def test_the_print_draws_references_and_values_in_millimetres(monkeypatch, tmp_path) -> None:
    """Drawn into the 1:1 PDF, a reference held its 12 pixels -- 12 dots of a 600 dpi
    printer, half a millimetre, beside pin names printed at 0.9 mm. Paper gets them in
    millimetres, with each value after its reference when the view shows values (#11)."""
    from perfboard_studio.ui import view2d
    from perfboard_studio.ui.export_pdf import export_pdf

    printed: list[tuple[str, str, float]] = []
    on_screen: list[str] = []
    real = view2d.draw_printed_reference

    def record_print(painter, anchor, reference, value, height_mm, value_mm, gap_mm, **kwargs):
        printed.append((reference, value, height_mm))
        real(painter, anchor, reference, value, height_mm, value_mm, gap_mm, **kwargs)

    monkeypatch.setattr(view2d, "draw_printed_reference", record_print)
    monkeypatch.setattr(view2d, "draw_label", lambda *a, **k: on_screen.append(a[2]))
    monkeypatch.setattr(view2d, "draw_outlined_reference", lambda *a, **k: on_screen.append(a[2]))

    doc = _example_document("ne555-astable")
    window = _window_on(doc)
    try:
        window.act_values.setChecked(True)
        scene = window._export_scene(doc, "top")
        export_pdf(doc.board, scene, tmp_path / "board.pdf")
    finally:
        _close(window)

    by_ref = {reference: (value, height) for reference, value, height in printed}
    for component in doc.components:
        assert component.ref in by_ref, component.ref
        value, height = by_ref[component.ref]
        assert value == component.value.strip()
        assert height >= 1.0, "a reference on paper is at least a millimetre tall"
    assert not [ref for ref in on_screen if ref in by_ref], "no screen-sized label on paper"


def test_a_stacked_side_panel_says_its_name_once() -> None:
    """The library, the Part List and the Nets open as one sidebar of three tabs, and Qt
    drew each one's own title under its tab: "Nets" on the tab and "Nets" again on a row
    below it. Stacked, a side panel has no title bar, as a stacked view has none; pulled
    out on its own it gets it back."""
    from PySide6.QtCore import Qt

    window = _blank_window()
    try:
        assert set(window.tabifiedDockWidgets(window.dock_library)) == {
            window.dock_part_list, window.dock_nets,
        }
        for dock in (window.dock_library, window.dock_nets, window.dock_part_list):
            assert dock.titleBarWidget() is not None
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, window.dock_part_list)
        window._sync_dock_titlebars()
        assert window.dock_part_list not in window.tabifiedDockWidgets(window.dock_nets)
        assert window.dock_part_list.titleBarWidget() is None
        assert window.dock_nets.titleBarWidget() is not None
    finally:
        _close(window)


def test_a_parts_note_goes_through_part_properties_even_on_a_locked_part() -> None:
    """A lock is about where a part is, and the note is about why it is there: the note
    stays editable on a locked part, and is committed when the field is left."""
    from perfboard_studio.commands import UpdateComponentPayload

    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    assert window.bus.dispatch(
        "component.update", UpdateComponentPayload(id=component.id, locked=True, note="old")
    ).ok
    editor = _inspect(window, component.id)
    assert editor.note.toPlainText() == "old"
    assert editor.note.isEnabled() and not editor.note.isReadOnly()
    assert not editor.change_part.isEnabled()

    editor.note.setPlainText("  10R keeps the speaker under 190 mA \n")
    editor._commit_note()
    edited = next(c for c in window.bus.document.components if c.id == component.id)
    assert edited.note == "10R keeps the speaker under 190 mA"
    assert edited.locked
    _close(window)


def test_a_parts_note_is_on_its_tooltip_after_a_blank_line_and_cut_when_long() -> None:
    from perfboard_studio.commands import UpdateComponentPayload
    from perfboard_studio.ui.view2d import NOTE_TOOLTIP_CHARS

    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    long_note = "x" * (NOTE_TOOLTIP_CHARS + 50)
    for note, shown in (("why it is here", "\n\nwhy it is here"), (long_note, "…")):
        assert window.bus.dispatch(
            "component.update", UpdateComponentPayload(id=component.id, note=note)
        ).ok
        tip = window.scene.component_items[component.id].toolTip()
        assert tip.endswith(shown), tip[-80:]
        assert len(tip.split("\n\n")[-1]) <= NOTE_TOOLTIP_CHARS
    _close(window)


def test_the_note_field_is_called_not_in_turkish() -> None:
    from PySide6.QtWidgets import QFormLayout, QLabel

    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        window = _window_on(_load_dense())
        editor = _inspect(window, window.bus.document.components[0].id)
        labels = {label.text() for label in editor.findChildren(QLabel)}
        assert "Not" in labels and "Note" not in labels
        assert any(isinstance(item, QFormLayout) for item in editor.findChildren(QFormLayout))
        _close(window)
    finally:
        set_language(before)


def test_the_sheets_edit_a_part_edits_a_design_parts_note() -> None:
    """A part drawn and not yet placed has its note too, edited where every field of it is:
    Properties."""
    from perfboard_studio.commands import AddPartPayload

    window = _window_on(_load_dense())
    assert window.bus.dispatch(
        "part.add", AddPartPayload(ref="R99", footprint_id="r-axial-3", value="1k", note="old")
    ).ok
    part = next(p for p in window.bus.document.parts if p.ref == "R99")
    window._show_symbol_in_properties("R99")
    editor = window.inspector.design_part_editor
    assert editor.note.toPlainText() == "old"
    editor.note.setPlainText("new reason")
    editor._commit_note()
    assert next(p for p in window.bus.document.parts if p.id == part.id).note == "new reason"
    _close(window)


def test_a_board_designed_from_the_menu_is_a_board_chosen(monkeypatch) -> None:
    """A stripboard set up by hand from the Board menu, and Place on the Board then asked
    "Which board is this going on?" as if nobody had chosen one: only the Board step marked
    the board chosen. A board designed and used is chosen, from either door."""
    from perfboard_studio.ui import designer as designer_module
    from perfboard_studio.ui import main as main_module
    from tests.designer_support import choose_kind

    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        _add(window, "R2", "r-axial-3")

        def to_stripboard(dialog) -> int:
            choose_kind(dialog, "stripboard")
            dialog._use()
            return int(dialog.result())

        monkeypatch.setattr(designer_module.BoardDesigner, "exec", to_stripboard)
        asked: list[bool] = []
        monkeypatch.setattr(
            main_module.MainWindow,
            "_offer_a_board_size",
            lambda self, document, always=False: asked.append(always) or True,
        )
        assert window.on_design_board()
        assert window.bus.document.board.type == "stripboard"
        assert window._board_chosen
        window.on_schematic_place_all()
        assert asked == [], "the board question was asked again"
        assert window.bus.document.components
    finally:
        _close(window)


def test_change_part_says_where_the_last_pin_lands_for_the_package_picked(monkeypatch) -> None:
    """Change Part said only "Pin 1 stays in D14": a longer resistor's other leg landed on a
    joint or another part's hole with nothing in the dialog to say so. It says where the last
    pin of the package picked lands, as it is picked, and that the wiring is checked again."""
    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.geometry import format_hole, pin_hole
    from perfboard_studio.ui import main as main_module

    window = _window_on(_example_document("ne555-astable"))
    try:
        resistor = next(c for c in window.bus.document.components if c.ref.startswith("R"))
        board = window.bus.document.board
        said: list[str] = []

        def look(dialog):
            said.append(dialog.notice.text())
            dialog.select_footprint("r-axial-4")
            said.append(dialog.notice.text())
            return int(main_module.QDialog.DialogCode.Rejected)

        monkeypatch.setattr(main_module.PackagePicker, "exec", look)
        window.on_change_part(resistor.id)
        longer = get_footprint("r-axial-4")
        lands = format_hole(pin_hole(resistor, longer, longer.pins[-1].number), board)
        assert said[1] != said[0], "the note follows the package picked"
        assert f"Pin {longer.pins[-1].number} lands in {lands}." in said[1], said[1]
        assert "checked again" in said[1]
    finally:
        _close(window)


def test_a_cancelled_board_trial_says_so_on_the_status_bar(monkeypatch) -> None:
    """Cancel on the board trial left the bar saying whatever it said before, over a
    question showing only the boards tried so far. It says the trial was cancelled, and
    after how many boards."""
    from perfboard_studio.boardfit import BoardChoice
    from perfboard_studio.ui import main as main_module

    window = _blank_window()
    try:
        _add(window, "R1", "r-axial-3")
        document = window.bus.document
        suggestions = main_module.suggest_boards(document.board, [], document.nets, window.lookup)
        part_way = _choice(document, complete=False)
        monkeypatch.setattr(
            main_module.MainWindow, "_run_planner", lambda self, label, work, **_: part_way
        )
        window._board_choice(document, suggestions)
        assert "cancelled after 2 boards" in window.statusBar().currentMessage()

        reference = part_way.reference
        nothing = BoardChoice(part_way.suggestions, reference, (), reference, False)
        monkeypatch.setattr(
            main_module.MainWindow, "_run_planner", lambda self, label, work, **_: nothing
        )
        window._board_choice(document, suggestions)
        assert "Cancelled before a board was tried" in window.statusBar().currentMessage()
    finally:
        _close(window)


def test_the_board_editor_sets_and_clears_the_body_clearance() -> None:
    """#12: off is the courtyard rule, on is the bodies that far apart. The board's editor
    shows what the document says; the box sets it and, cleared, takes it off -- as Board
    Features did before it retired into Properties."""
    window = _window_on(_blank_document())
    try:
        _board_features(window)
        editor = window.inspector.board_editor
        assert not editor.body_measure.isChecked() and not editor.body_clearance.isEnabled()

        editor.body_clearance.setValue(0.8)
        editor.body_measure.setChecked(True)
        assert window.bus.document.body_clearance_mm == 0.8
        assert editor.body_clearance.isEnabled()

        editor.body_measure.setChecked(False)
        assert window.bus.document.body_clearance_mm is None
        assert not editor.body_clearance.isEnabled()
    finally:
        _close(window)


def test_the_body_clearance_row_is_in_turkish() -> None:
    from PySide6.QtWidgets import QLabel

    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        window = _window_on(_blank_document())
        try:
            _board_features(window)
            editor = window.inspector.board_editor
            assert editor.body_measure.text() == "Gövdeler arasını ölç"
            assert "Gövde aralığı" in {label.text() for label in editor.findChildren(QLabel)}
        finally:
            _close(window)
    finally:
        set_language(before)


def _reachable_from(window, root) -> set:
    """Every action a person can reach by opening ``root`` and its submenus.

    Submenus are found by matching each menu's own action, not through ``QAction.menu()``,
    which hands PySide an owning wrapper and deletes the submenu when it is dropped."""
    import shiboken6
    from PySide6.QtWidgets import QMenu

    menus = {shiboken6.getCppPointer(m.menuAction())[0]: m for m in window.findChildren(QMenu)}
    seen: set = set()
    stack, opened = [root], set()
    while stack:
        menu = stack.pop()
        opened.add(menu)
        for action in menu.actions():
            seen.add(action)
            sub = menus.get(shiboken6.getCppPointer(action)[0])
            if sub is not None and sub not in opened:
                stack.append(sub)
    return seen


def test_the_header_is_one_row_with_every_menu_behind_its_button() -> None:
    """A menu bar, a toolbar for the document and a step bar were three rows of chrome
    above the board. One row now: the menus behind ☰, the steps and Next in it, undo and
    redo beside them. The menu bar is kept at no height, because Alt+F is its."""
    from PySide6.QtWidgets import QToolBar

    window = _window_on(_load_dense())
    try:
        names = {bar.objectName() for bar in window.findChildren(QToolBar)}
        assert "headerToolbar" in names
        assert not {"mainToolbar", "workflowToolbar"} & names
        assert window.menuBar().maximumHeight() == 0
        held = [action.text() for action in window.header.app_menu.actions()]
        assert held == [menu.title() for menu in window._top_menus]
        assert held == [action.text() for action in window.menuBar().actions()]
        assert window.header.undo_button.defaultAction() is window.act_undo
        assert window.header.redo_button.defaultAction() is window.act_redo
        assert window.workflow_bar.next_button.parent() is window.header
        assert window.workflow_bar.parent() is window.header
    finally:
        _close(window)


#: Every action that was on a toolbar in 0.22, the checklist of the redesign's IA: a slice
#: that takes a bar away must leave each one somewhere a person can still reach it.
def _old_toolbar_actions(window) -> list:
    return [
        window.act_save, window.act_undo, window.act_redo,
        window.act_board_panel, window.act_schematic, window.act_3d, window.act_guide_panel,
        window.act_connect, window.act_new_net,
        *(window.act_draw[kind] for kind in (
            "solder-trace", "solder-trace-wired", "bare-wire", "insulated-wire", "top-jumper",
        )),
        window.act_autoplace, window.act_autoroute,
        window.act_rotate_cw, window.act_mirror, window.act_delete,
        window.act_flip, window.act_ratsnest, window.act_fit,
    ]


#: Every action on the sheet panel's own row in 0.22, the same checklist for the sheet. Its
#: Export was File ▸ Export Schematic under another name, and is that entry now.
def _old_sheet_row_actions(window) -> list:
    return [
        window.act_sch_add,
        *(window.act_sheet_tool[name] for name in ("select", "wire", "label", "text", "rectangle")),
        window.act_sch_rotate, window.act_sch_mirror, window.act_sch_delete,
        window.act_sch_auto, window.act_sch_fit, window.act_sch_place, window.act_sch_float,
        window.act_export_schematic,
    ]


def test_every_action_the_old_toolbars_had_is_behind_the_menu_button() -> None:
    """The toolbars go, and nothing on them goes with them: every one of their actions is
    in a menu under ☰ (and so in Ctrl+K, which lists the menus) -- the window's row and
    the sheet's own row both."""
    window = _window_on(_load_dense())
    try:
        reachable = _reachable_from(window, window.header.app_menu)
        old = [*_old_toolbar_actions(window), *_old_sheet_row_actions(window)]
        missing = [a.text() for a in old if a not in reachable]
        assert not missing, f"no longer reachable from the menus: {missing}"
    finally:
        _close(window)


def test_every_action_the_old_toolbars_had_has_a_place_on_screen() -> None:
    """Behind ☰ is not enough for a tool somebody reaches for all day: each of the old
    bars' actions has a place on screen as well -- the header, the board's own tools and
    their groups, the corner of the board, or a view's tab."""
    window = _window_on(_load_dense())
    try:
        on_screen = {window.header.undo_button.defaultAction(),
                     window.header.redo_button.defaultAction()}
        bars = (window.board_tools, window.board_view_tools, window.selection_bar,
                window.sheet_tools, window.sheet_view_tools, window.sheet_selection_bar)
        for bar in bars:
            for button in bar.buttons:
                on_screen.add(button.defaultAction())
                if button.menu() is not None:
                    on_screen.update(button.menu().actions())
        on_screen.update((window.act_board_panel, window.act_schematic, window.act_3d,
                          window.act_guide_panel))  # the views' tabs
        # Save is "Not saved" in the header, there when there is something to save.
        on_screen.add(window.act_save)
        # One-off commands are not tools: they are the header's Next when they are the
        # next step (Place on the Board, Rearrange, Auto-wire), a part is added from the
        # Library, a net from the Nets panel, the sheet floats by dragging its tab, and the
        # sheet's export is File's.
        elsewhere = {window.act_new_net, window.act_autoplace, window.act_autoroute,
                     window.act_sch_add, window.act_sch_place, window.act_sch_float,
                     window.act_export_schematic}
        old = [*_old_toolbar_actions(window), *_old_sheet_row_actions(window)]
        missing = [a.text() for a in old if a not in on_screen and a not in elsewhere]
        assert not missing, f"no place on screen for: {missing}"
        assert {window.workflow_bar.buttons[key] for key in ("place", "route")}
    finally:
        _close(window)


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="macOS has no Alt+letter menu access: Option+letter types a character, and the "
    "menus are the system menu bar's",
)
def test_alt_and_a_letter_drop_that_menu_and_alt_alone_opens_the_button() -> None:
    """The menus moved behind ☰, and Alt kept working: Alt+F drops File (the menu bar is
    still there, at no height, at the top-left where ☰ is), and Alt by itself -- which put
    an invisible menu bar into its keyboard mode with nothing on screen to say so -- opens
    ☰ instead."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    window = _window_on(_load_dense())
    try:
        window.show()
        window.activateWindow()
        QTest.qWaitForWindowActive(window)
        QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
        _settle_events(QApplication)
        assert QApplication.activePopupWidget() is window._top_menus[0]
        window._top_menus[0].close()
        _settle_events(QApplication)

        window._alt_opened_the_menu_bar()  # where Alt by itself ends up
        _settle_events(QApplication)
        assert QApplication.activePopupWidget() is window.header.app_menu
        window.header.app_menu.close()
    finally:
        _close(window)


def test_the_header_says_the_boards_name_and_that_it_is_not_saved() -> None:
    """Unsaved was a bullet in the title bar, which nobody looks at while working. The
    header says it beside the board's name, and one click saves."""
    window = _window_on(_load_dense())
    try:
        header = window.header
        assert header.title.text() == window._document_name()
        assert not header.unsaved.isVisibleTo(header)
        first = window.bus.document.components[0]
        window.bus.dispatch(
            "component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(3, 3))
        )
        assert header.unsaved.isVisibleTo(header)
        assert header.unsaved.text() == "Not saved"
        window._mark_saved()
        assert not header.unsaved.isVisibleTo(header)
    finally:
        _close(window)


def test_a_bar_stands_over_the_selected_parts(monkeypatch) -> None:
    """Rotate, mirror and delete were buttons on a row a metre from the part, and lock and
    "route these nets" two menus deep. Over the selection they are where the eye already
    is: the bar comes with a selection, stands above it (below, at the top edge), follows
    the view as it moves, and goes while a tool is armed -- a bar of part actions over a
    board being drawn on is in the way."""
    from PySide6.QtWidgets import QApplication

    window = _shown_window_without_3d(monkeypatch)
    try:
        window.show_board()
        _settle_events(QApplication)
        bar = window.selection_bar
        assert bar.parent() is window.view
        assert not bar.isVisible()
        actions = [button.defaultAction() for button in bar.buttons]
        assert actions[:3] == [window.act_rotate_cw, window.act_mirror, window.act_lock]
        assert window.act_route_selected in actions and window.act_delete in actions
        assert actions[-1] is window.act_selection_more

        part = window.bus.document.components[0]
        window.scene.select_components([part.id])
        _settle_events(QApplication)
        assert bar.isVisible()
        over = window._selection_rect()
        assert over is not None
        assert bar.geometry().bottom() < over.top() or bar.geometry().top() > over.bottom()

        before = bar.pos()
        window.on_zoom(1.25)
        _settle_events(QApplication)
        moved = window._selection_rect()
        assert moved is not None and moved != over
        assert bar.pos() != before, "the bar follows the part as the view changes"

        window.act_draw["bare-wire"].trigger()
        _settle_events(QApplication)
        assert not bar.isVisible()
        window.on_stop_tool()
        window.scene.select_components([])
        _settle_events(QApplication)
        assert not bar.isVisible()
    finally:
        _close(window)


def test_the_dots_on_the_selection_bar_offer_what_a_right_click_does(monkeypatch) -> None:
    """The rest of what a part can be told to do is behind the dots: the same menu a
    right-click on it builds, from the same actions."""
    from PySide6.QtWidgets import QApplication, QMenu

    window = _shown_window_without_3d(monkeypatch)
    try:
        window.show_board()
        part = window.bus.document.components[0]
        window.scene.select_components([part.id])
        _settle_events(QApplication)
        shown: list[QMenu] = []
        monkeypatch.setattr(QMenu, "popup", lambda menu, *_args: shown.append(menu))
        window.act_selection_more.trigger()
        assert shown, "the dots open a menu"
        offered = shown[0].actions()
        assert window.act_properties in offered and window.act_change_part in offered
    finally:
        _close(window)


def test_properties_stand_down_the_right_and_cannot_be_closed(monkeypatch) -> None:
    """Always open, the whole height of the window, beside the views: with nothing selected
    the board is the selection, so there is never nothing to show and nothing to close it
    for."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDockWidget

    window = _shown_window_without_3d(monkeypatch)
    try:
        dock = window.dock_properties
        assert dock.objectName() == "dockProperties"
        assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
        assert not dock.features() & QDockWidget.DockWidgetFeature.DockWidgetClosable
        assert not dock.isHidden()
        _settle_events(QApplication)
        assert dock.x() > window.dock_board.x() + window.dock_board.width() - 2
        assert dock.height() >= window.dock_board.height()
        assert window.properties.selection.kind == "board"
    finally:
        _close(window)


def test_properties_follow_the_selection_from_the_board_the_sheet_and_the_library() -> None:
    """One selection, said once: a part selected on the board, several, a part picked on
    the sheet, a library part armed for placing -- and the board again when nothing is."""
    window = _window_on(_load_dense())
    try:
        first, second = window.bus.document.components[:2]
        window.scene.select_components([first.id])
        assert window.properties.selection.kind == "part"
        assert window.properties.selection.ids == (first.id,)
        window.scene.select_components([first.id, second.id])
        assert window.properties.selection.kind == "parts"
        window.scene.select_components([])
        assert window.properties.selection.kind == "board"

        # As a click on the sheet does: the view's selection, then its signal.
        window.schematic_view.set_selection([second.ref])
        window.schematic_view.selectionChanged.emit([second.ref])
        assert window.properties.selection == window._current_selection()
        assert window.properties.selection.ids == (second.id,)
        assert window.properties.selection.source == "sheet"
        window.schematic_view.set_selection([])
        window.schematic_view.selectionChanged.emit([])

        window._on_placement_armed("r-axial-4")
        assert window.properties.selection.kind == "placing"
        assert window.properties.selection.ids == ("r-axial-4",)
        window._on_placement_armed("")
        assert window.properties.selection.kind == "board"
    finally:
        _close(window)


def test_the_inspector_is_put_in_and_handed_the_selection_and_the_document() -> None:
    """The shell is the window's; what it shows is the inspector's. Put in with
    set_content, it is handed the document and the selection at once, then every change
    of either -- the two calls agreed with the inspector."""
    from PySide6.QtWidgets import QWidget

    class _Inspector(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.selections: list[object] = []
            self.documents: list[object] = []

        def set_selection(self, selection: object) -> None:
            self.selections.append(selection)

        def refresh(self, document: object) -> None:
            self.documents.append(document)

    window = _window_on(_load_dense())
    try:
        inspector = _Inspector()
        window.properties.set_content(inspector)
        assert inspector.documents and inspector.documents[-1] is window.bus.document
        assert inspector.selections and inspector.selections[-1].kind == "board"
        first = window.bus.document.components[0]
        window.scene.select_components([first.id])
        assert inspector.selections[-1].ids == (first.id,)
        window.bus.dispatch(
            "component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(3, 3))
        )
        assert inspector.documents[-1] is window.bus.document
    finally:
        _close(window)


def test_a_library_group_cut_short_says_its_name_in_full() -> None:
    """At the sidebar's width the longer groups are cut -- "Regulators an…", in Turkish
    "Regülatörler v…" -- so each says its name in full on hover, as its parts already did."""
    window = _window_on(_load_dense())
    try:
        tree = window.library_tree
        groups = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        assert groups
        for group in groups:
            # The name in full on its first line; a package family says what a package
            # is on the next.
            assert group.toolTip(0).splitlines()[0] == group.text(0), group.text(0)
    finally:
        _close(window)


def test_the_palette_ranks_a_name_that_starts_with_what_was_typed_first() -> None:
    """What is typed is nearly always the start of a word: a name that starts with it
    first, then a name with a word that does, then one that only contains it."""
    from perfboard_studio.ui.palette import Entry, rank

    def entry(label: str) -> Entry:
        return Entry(label=label, where="", keys="", run=lambda: None)

    entries = [entry("Show Missing Connections"), entry("Auto-wire Everything"), entry("Draw")]
    assert [e.label for e in rank(entries, "auto")] == ["Auto-wire Everything"]
    assert [e.label for e in rank(entries, "miss")] == ["Show Missing Connections"]
    assert [e.label for e in rank(entries, "ra")] == ["Draw"]
    # A hyphen parts words: "wire" starts a word of "Auto-wire".
    assert [e.label for e in rank(entries, "wire")] == ["Auto-wire Everything"]
    assert rank(entries, "") == entries


def test_the_palette_offers_every_menu_command_and_runs_it() -> None:
    """Ctrl+K lists every enabled entry of every menu under the menu button by its own
    words, with where it lives and its key, and Enter runs the one picked."""
    window = _window_on(_load_dense())
    try:
        assert window.act_palette.shortcut().toString() == "Ctrl+K"
        window.act_palette.trigger()
        palette = window.command_palette
        assert palette.isVisibleTo(window)
        labels = [e.label for e in palette.shown()]
        assert any(label.startswith("Auto-wire Everything") for label in labels)
        assert any(label.startswith("Show Missing Connections") for label in labels)

        before = window.act_ratsnest.isChecked()
        palette.field.setText("show missing")
        first = palette.shown()[0]
        assert first.label.startswith("Show Missing Connections")
        from PySide6.QtGui import QKeySequence

        # Said as the platform says it -- "⌘E" on macOS -- as the palette shows it.
        native = QKeySequence.SequenceFormat.NativeText
        assert first.keys == window.act_ratsnest.shortcut().toString(native)
        palette.run_current()
        assert window.act_ratsnest.isChecked() is not before
        assert not palette.isVisibleTo(window)
    finally:
        _close(window)


def test_the_palette_finds_a_part_and_a_net_by_name() -> None:
    """Go to Part, in the same field: a part's reference selects it on the board, and a
    net's name selects it in the Nets panel."""
    window = _window_on(_load_dense())
    try:
        part = window.bus.document.components[0]
        window.command_palette.open()
        window.command_palette.field.setText(part.ref)
        shown = window.command_palette.shown()
        assert shown[0].label.split()[0] == part.ref
        window.command_palette.run_current()
        assert list(window.scene.selected_component_ids()) == [part.id]

        net = window.bus.document.nets[0]
        window.command_palette.open()
        window.command_palette.field.setText(net.name)
        chosen = next(e for e in window.command_palette.shown() if e.label == net.name)
        chosen.run()
        selected = window.nets_tree.selectedItems()
        assert selected and selected[0].text(0) == net.name
    finally:
        _close(window)


def test_a_part_dragged_onto_a_hole_with_no_pad_says_so_when_it_lands() -> None:
    """Moved so a pin lands on a finger, a part went red while it moved and then landed with
    "Done" and nothing else -- the router was the next thing to mention it. It lands, as a
    placement there does (the board is legal, DRC calls it an error), and it says so as a
    placement there does, and stays marked."""
    import dataclasses

    from perfboard_studio.geometry import edge_connector_holes
    from perfboard_studio.model import EdgeConnector

    document = _load_dense()
    board = document.board
    strip = EdgeConnector(id="ec-bottom", edge="bottom", start=0, count=board.cols)
    document = dataclasses.replace(document, edge_connectors=(strip,))
    window = _window_on(document)
    try:
        finger = edge_connector_holes(strip, board)[0]
        part = next(
            c for c in window.bus.document.components
            if window.scene.component_items.get(c.id) is not None
        )
        item = window.scene.component_items[part.id]
        pin_offset = next(
            (at.col - part.anchor.col, at.row - part.anchor.row)
            for _pin, at in all_pin_holes_of(part, window.lookup)
        )
        item.pending_anchor = HoleCoord(finger.col - pin_offset[0], finger.row - pin_offset[1])
        results = window.scene.commit_pending_moves()
        assert results and all(r.ok for r in results)
        assert window.scene.last_move_on_a_dead_hole
        assert "no pad there" in window.statusBar().currentMessage()
        assert window.scene.component_items[part.id].has_error
    finally:
        _close(window)


def all_pin_holes_of(component, lookup):
    from perfboard_studio.geometry import all_pin_holes

    footprint = lookup(component.footprint_id)
    return all_pin_holes(component, footprint) if footprint is not None else ()


def test_a_reference_typed_whole_is_that_part_before_the_ones_it_starts() -> None:
    """Go to Part: "X1" is X1 even where the document lists X10..X16 before it -- the dense
    board keeps them in that order -- rather than whichever of them came first."""
    import dataclasses

    document = _load_dense()
    first = next(c for c in document.components if c.ref == "X1")
    others = tuple(c for c in document.components if c.ref != "X1")
    window = _window_on(dataclasses.replace(document, components=(*others, first)))
    try:
        window.on_go_to_part()
        window.command_palette.field.setText("X1")
        shown = window.command_palette.shown()
        assert shown[0].label.split()[0] == "X1"
        assert [e.label.split()[0] for e in shown[1:4]] == ["X10", "X11", "X12"]
        window.command_palette.run_current()
        assert list(window.scene.selected_component_ids()) == [first.id]
    finally:
        _close(window)


def test_escape_closes_the_palette_and_the_header_opens_it() -> None:
    """Escape leaves the palette before it leaves anything else, and the header's search
    field is the palette's other door."""
    window = _window_on(_load_dense())
    try:
        window.header.search.click()
        assert window.command_palette.isVisibleTo(window)
        window.on_stop_tool()
        assert not window.command_palette.isVisibleTo(window)
    finally:
        _close(window)


def test_the_sheets_tools_float_on_the_sheet() -> None:
    """The sheet had a row of fifteen buttons across its panel: a second toolbar in a
    window that had just lost its first. Its tools float on the sheet now, as the board's
    float on the board -- the shape button holding the three shapes -- with Arrange, the
    sheet's own zoom and Fit in the corner; everything else is the Schematic menu's."""
    from PySide6.QtWidgets import QToolBar

    window = _window_on(_load_dense())
    try:
        assert "schematicToolbar" not in {b.objectName() for b in window.findChildren(QToolBar)}
        assert window.sheet_tools.parent() is window.schematic_view
        tools = [button.defaultAction() for button in window.sheet_tools.buttons]
        assert tools == [window.act_sheet_tool[n] for n in ("select", "wire", "label", "text", "rectangle")]
        shapes = window.act_sheet_tool["rectangle"].menu()
        assert shapes is not None and len(shapes.actions()) == 3
        corner = [button.defaultAction() for button in window.sheet_view_tools.buttons]
        assert window.act_sch_auto in corner and window.act_sch_fit in corner
        assert window.act_sch_zoom_in in corner and window.act_sch_zoom_out in corner
        on_menu = window.menu_circuit.actions()
        for action in (window.act_sch_add, window.act_sch_rotate, window.act_sch_float):
            assert action in on_menu, action.text()
        assert window.act_sch_place in window.menu_board.actions()
    finally:
        _close(window)


def test_a_bar_stands_over_the_selected_symbols(monkeypatch) -> None:
    """The board's selection bar, on the sheet: Turn, Flip, Remove and the right-click's
    dots over the selected symbols, and gone while a drawing tool is armed."""
    from PySide6.QtWidgets import QApplication

    window = _shown_window_without_3d(monkeypatch)
    try:
        window.show_schematic()
        _settle_events(QApplication)
        bar = window.sheet_selection_bar
        actions = [button.defaultAction() for button in bar.buttons]
        assert actions[:2] == [window.act_sch_rotate, window.act_sch_mirror]
        assert window.act_sch_delete in actions and actions[-1] is window.act_sheet_more
        assert not bar.isVisible()

        ref = window.bus.document.components[0].ref
        window.schematic_view.set_selection([ref])
        window.schematic_view.viewport().update()
        _settle_events(QApplication)
        assert bar.isVisible()

        window.on_sheet_tool("wire")
        window.schematic_view.viewport().update()
        _settle_events(QApplication)
        assert not bar.isVisible()
    finally:
        _close(window)


def test_properties_describe_the_selection_where_it_was_last_made() -> None:
    """C1 picked on the sheet with a part still selected on the board behind it: the board
    came first, and Properties described the board's. The selection is the one the window
    was last given, in either view; several symbols on the sheet are a selection too."""
    window = _window_on(_load_dense())
    try:
        board_part, sheet_part, other = window.bus.document.components[:3]
        window.scene.select_components([board_part.id])
        assert window.properties.selection.ids == (board_part.id,)

        sheet = window.schematic_view
        sheet.set_selection([sheet_part.ref])
        sheet.selectionChanged.emit([sheet_part.ref])
        chosen = window.properties.selection
        assert (chosen.kind, chosen.ids, chosen.source) == ("part", (sheet_part.id,), "sheet")

        sheet.set_selection([sheet_part.ref, other.ref])
        sheet.selectionChanged.emit([sheet_part.ref, other.ref])
        assert window.properties.selection.kind == "parts"
        assert set(window.properties.selection.ids) == {sheet_part.id, other.id}

        window.scene.select_components([])  # back on the board: a click on bare board,
        window.scene.select_components([board_part.id])  # then on a part
        assert window.properties.selection.ids == (board_part.id,)
        assert window.properties.selection.source == "board"
    finally:
        _close(window)


def test_the_guides_controls_are_in_its_corner() -> None:
    """The guide was the one panel left with a row of push buttons under it -- Next Step to
    Do, Clear Progress, Export -- while every view's tools had gone onto the view. They are
    a cluster in its corner now, built on actions like the rest, Export being File's own."""
    from PySide6.QtWidgets import QPushButton

    from perfboard_studio.ui.i18n import t

    window = _window_on(_load_dense())
    try:
        panel = window.guide_overview  # the list's corner; the bench has its own buttons
        # The empty guide's own button (Place on the Board) is the empty state's, and stays.
        old_row = {t("Next Step to Do"), t("Clear Progress"), t("Export the Guide…")}
        left = [b.text() for b in panel.findChildren(QPushButton) if b.text() in old_row]
        assert not left, f"left on the guide: {left}"
        assert window.guide_tools.parent() is panel
        actions = [button.defaultAction() for button in window.guide_tools.buttons]
        assert actions == [window.act_next_step, window.act_clear_progress, window.act_guide]
    finally:
        _close(window)


def test_the_3d_views_controls_are_at_its_foot() -> None:
    """The 3D view had a toolbar of its own over it for two buttons. They join the playback
    along its foot: not floating over the view as the board's do, because the 3D view is a
    native OpenGL window and Qt cannot paint a widget over one."""
    from PySide6.QtWidgets import QToolBar, QToolButton

    window = _window_on(_load_dense())
    try:
        bar = window._build_assembly_bar()
        window._3d_layout.addWidget(bar)
        on_bar = {button.defaultAction() for button in bar.findChildren(QToolButton)}
        assert window.act_exploded in on_bar and window.act_reset_3d in on_bar
        assert "view3dToolbar" not in {b.objectName() for b in window.findChildren(QToolBar)}
    finally:
        _close(window)


def test_a_group_button_says_it_holds_more(monkeypatch) -> None:
    """The corner triangle is small: the tip says a press held down offers the rest, and
    still names the tool the button arms."""
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent

    from perfboard_studio.ui import canvastools
    from perfboard_studio.ui.i18n import t

    shown: list[str] = []
    monkeypatch.setattr(
        canvastools.QToolTip, "showText", lambda _at, text, *_rest: shown.append(text)
    )
    window = _window_on(_load_dense())
    try:
        button = window.wire_tools
        button.event(QHelpEvent(QEvent.Type.ToolTip, QPoint(2, 2), QPoint(2, 2)))
        assert shown == [button.defaultAction().toolTip() + t(" (hold for more)")]
    finally:
        _close(window)


def test_the_menus_follow_the_steps() -> None:
    """Nine menus -- Draw, Place, Net and Schematic among them -- and four plausible homes
    for Place on the Board. Seven now, the middle three the step bar's first stages: the
    sheet and the nets are the circuit's, setting up and placing are the board's, and a
    trace drawn by hand is wiring as much as one laid by Auto-wire."""
    from perfboard_studio.ui.i18n import t

    window = _window_on(_load_dense())
    try:
        assert [m.title() for m in window._top_menus] == [
            t(name) for name in ("&File", "&Edit", "&Circuit", "&Board", "&Wiring", "&View",
                                 "&Help")
        ]
        circuit = window.menu_circuit.actions()
        assert circuit[0] is window.act_sch_add and window.act_connect in circuit
        assert window.act_design_board in window.menu_board.actions()
        wiring = _reachable_from(window, window._top_menus[4])
        assert window.act_cut in wiring and window.act_autoroute in wiring
        assert window.act_guide in window.menu_export.actions()
        # One Show menu: the View menu's submenu is the one the board's corner opens.
        assert window.act_ratsnest in window.menu_show.actions()
        assert window.menu_show in window._menus
    finally:
        _close(window)


def _letters_in_clash(window) -> list[str]:
    """Every menu under ☰ in which two entries claim the same Alt letter."""
    from collections import Counter

    import shiboken6
    from PySide6.QtWidgets import QMenu

    menus = {shiboken6.getCppPointer(m.menuAction())[0]: m for m in window.findChildren(QMenu)}
    found: list[str] = []
    stack, opened = [window.header.app_menu], set()
    while stack:
        menu = stack.pop()
        opened.add(menu)
        letters = []
        for action in menu.actions():
            if action.isSeparator() or not action.isVisible():
                continue
            text = action.text().replace("&&", "")
            if "&" in text:
                letters.append(text.split("&", 1)[1][0].lower())
            sub = menus.get(shiboken6.getCppPointer(action)[0])
            if sub is not None and sub not in opened:
                stack.append(sub)
        found += [f"{menu.title()}: {x}" for x, n in Counter(letters).items() if n > 1]
    return found


def test_no_two_entries_of_a_menu_share_a_letter_in_either_language() -> None:
    """The catalogue's test checks the groups it lists, in Turkish; this one opens every
    menu the window has, in both languages. It found nine menus with a letter claimed
    twice in English and three in Turkish -- Alt+the letter reaches whichever comes first,
    and the other never."""
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    try:
        for code in ("en", "tr"):
            set_language(code)
            window = _window_on(_load_dense())
            try:
                assert _letters_in_clash(window) == [], code
            finally:
                _close(window)
    finally:
        set_language(before)


def test_f2_and_a_double_click_put_the_keyboard_in_the_part_in_properties() -> None:
    """Part Properties is the panel: F2 is the selected part's Reference, a double-click on
    a part its Value -- the field somebody double-clicking a resistor came to change."""
    window = _window_on(_load_dense())
    first, second = window.bus.document.components[:2]
    window.scene.select_components([first.id])
    focused: list[str] = []
    window.inspector.focus_field = lambda name: focused.append(name) or True
    window.act_properties.trigger()
    assert focused == ["ref"]
    window.scene.componentActivated.emit(second.id)
    assert focused == ["ref", "value"]
    assert window.properties.selection.ids == (second.id,)
    _close(window)


def test_a_part_turns_flips_and_moves_from_properties() -> None:
    from perfboard_studio.geometry import format_hole

    window = _window_on(_load_dense())
    component = next(c for c in window.bus.document.components if not c.locked)
    editor = _inspect(window, component.id)
    turn = 90 if component.rotation != 90 else 180
    editor.rotation.button(turn).click()
    editor.mirrored.click()
    moved = next(c for c in window.bus.document.components if c.id == component.id)
    assert (moved.rotation, moved.mirrored) == (turn, not component.mirrored)
    assert editor.rotation.checkedId() == turn

    _type_into(editor.pin1, "nowhere")
    assert "nowhere" in editor.pin1.problem.text()
    _type_into(editor.pin1, "A1")
    after = next(c for c in window.bus.document.components if c.id == component.id)
    if after.anchor != moved.anchor:  # placed: pin 1 is where it was asked to be
        assert format_hole(after.anchor, window.bus.document.board) == "A1"
    else:  # refused: said under the field, in the bus's words
        assert editor.pin1.problem.text()
    _close(window)


def test_the_step_is_what_properties_shows_with_nothing_selected() -> None:
    """Nothing selected is where the work stands and what to do now -- the board's settings
    opened on a height limit and pads per hole for somebody about to draw their first
    circuit -- and the board's editor is one click away, until something else is picked."""
    window = _window_on(_load_dense())
    window.scene.clearSelection()
    window._refresh_properties()
    card = window.inspector.step_card
    assert window.inspector.shown is card
    bar = window.workflow_bar
    assert bar.next_button.text().endswith(card.next.text())
    assert "Height" not in card.hint.text()
    card.board_settings.click()
    editor = window.inspector.board_editor
    assert window.inspector.shown is editor
    board = window.bus.document.board
    assert f"{board.cols} × {board.rows}" in editor.summary.text()  # wraps whole
    editor.height_limit.setValue(12.5)
    editor.height_limit.editingFinished.emit()
    assert window.bus.document.height_limit_mm == 12.5
    editor.body_measure.setChecked(True)
    assert window.bus.document.body_clearance_mm is not None
    assert window.inspector.shown is editor, "an edit in the board's settings keeps them open"
    part = window.bus.document.components[0]
    window.scene.select_components([part.id])
    window._refresh_properties()
    window.scene.clearSelection()
    window._refresh_properties()
    assert window.inspector.shown is card, "picking something else puts the step back"
    _close(window)


def test_tabbing_through_properties_keeps_the_part_in_the_panel() -> None:
    """The board empties its selection while it redraws after a command; the panel is told
    the selection once the redraw is done, so it never shows the board in between -- which
    would take the keyboard out of the field Tab had just moved to."""
    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    editor = _inspect(window, component.id)
    shown: list = []
    real = window.inspector.set_selection
    window.inspector.set_selection = lambda sel: (shown.append(sel.kind), real(sel))[1]
    window.properties.selection = None  # so the panel passes every selection on
    _type_into(editor.value, "4k7")
    assert "board" not in shown and window.inspector.shown is editor
    _close(window)


def _drawn(window, count: int) -> list:
    """The first ``count`` parts the board draws: dense.perf has one whose package does not
    exist (c-disc-1), which is on no canvas and so in no selection."""
    return [c for c in window.bus.document.components if c.id in window.scene.component_items][:count]


def _inspect_several(window, ids):
    window.scene.select_components(list(ids))
    window._refresh_properties()
    editor = window.inspector.parts_editor
    assert window.inspector.shown is editor
    return editor


def test_one_value_for_several_parts_is_one_step_even_with_one_locked() -> None:
    """Five resistors placed, then "10k" typed once: one command, one undo step. A lock is
    about where a part is, so a locked one among them takes the value too."""
    from perfboard_studio.commands import UpdateComponentPayload

    window = _window_on(_load_dense())
    chosen = [c.id for c in _drawn(window, 3)]
    assert window.bus.dispatch(
        "component.update", UpdateComponentPayload(id=chosen[1], locked=True)
    ).ok
    before = len(window.bus.history())
    editor = _inspect_several(window, chosen)
    _type_into(editor.value, "10k")
    values = {c.value for c in window.bus.document.components if c.id in chosen}
    assert values == {"10k"}
    assert len(window.bus.history()) == before + 1
    assert editor.value.text() == "10k" and window.inspector.shown is editor
    window.bus.undo()
    assert {c.value for c in window.bus.document.components if c.id in chosen} != {"10k"}
    _close(window)


def test_several_parts_with_different_values_say_mixed() -> None:
    from perfboard_studio.ui.i18n import t

    window = _window_on(_load_dense())
    components = _drawn(window, 99)
    first = components[0]
    other = next(c for c in components if c.value != first.value)
    editor = _inspect_several(window, [first.id, other.id])
    assert editor.value.text() == "" and editor.value.placeholderText() == t("Mixed")
    assert first.ref in editor.refs.text() and other.ref in editor.refs.text()
    _close(window)


def test_locking_several_parts_from_properties_is_one_step() -> None:
    """Some locked: the box shows both; a click locks them all, and with all locked a click
    unlocks them all -- each one step."""
    from PySide6.QtCore import Qt

    from perfboard_studio.commands import UpdateComponentPayload

    window = _window_on(_load_dense())
    chosen = [c.id for c in _drawn(window, 3)]
    assert window.bus.dispatch(
        "component.update", UpdateComponentPayload(id=chosen[0], locked=True)
    ).ok
    editor = _inspect_several(window, chosen)
    assert editor.locked.checkState() == Qt.CheckState.PartiallyChecked
    before = len(window.bus.history())
    editor.locked.click()
    assert all(c.locked for c in window.bus.document.components if c.id in chosen)
    assert editor.locked.checkState() == Qt.CheckState.Checked
    editor.locked.click()
    assert not any(c.locked for c in window.bus.document.components if c.id in chosen)
    assert len(window.bus.history()) == before + 2
    _close(window)


def test_the_value_for_the_parts_placed_next_is_typed_in_properties() -> None:
    """The library's own value box was the most misread control in the window -- it read
    as a second search field. A part armed for placing is what Properties shows, and its
    Value is the value each part placed from it gets."""
    from PySide6.QtWidgets import QLineEdit

    window = _window_on(_load_dense())
    library = window.dock_library.widget()
    assert window.placing_value not in library.findChildren(QLineEdit)
    window.scene.arm_placement("r-axial-4")
    window._refresh_properties()
    assert window.inspector.shown is window.inspector.placing_editor
    window.placing_value.setText("10k")
    assert window.scene.placement_value == "10k"
    _close(window)


def test_add_label_writes_one_and_puts_the_keyboard_in_its_text() -> None:
    """No form first: the label is written, selected, and its own fields are in Properties
    -- text, height, rotation and face -- each change one step."""
    from perfboard_studio.ui.i18n import t

    window = _window_on(_load_dense())
    before = {n.id for n in window.bus.document.board_notes}
    focused: list[str] = []
    real = window.inspector.focus_field
    window.inspector.focus_field = lambda name: (focused.append(name), real(name))[1]
    window.on_add_board_label()
    (note,) = [n for n in window.bus.document.board_notes if n.id not in before]
    assert note.text == t("Label")
    editor = window.inspector.board_note_editor
    assert window.inspector.shown is editor and focused == ["text"]

    def now():
        return next(n for n in window.bus.document.board_notes if n.id == note.id)

    steps = len(window.bus.history())
    _type_into(editor.text, "MOTOR 24V")
    editor.rotation.button(90).click()
    editor._face_buttons["bottom"].click()
    editor.text_height.setValue(3.0)
    editor.text_height.editingFinished.emit()
    assert (now().text, now().rotation, now().side, now().size_mm) == (
        "MOTOR 24V", 90, "bottom", 3.0
    )
    assert len(window.bus.history()) == steps + 4
    _close(window)


def test_editing_a_label_selects_it_in_properties() -> None:
    """A double-click on a label, or Edit Label on its right-click, is the label in
    Properties -- the dialog it used to open is gone."""
    from PySide6.QtCore import QPointF

    window = _window_on(_load_dense())
    assert window.add_board_label("CAN", QPointF(0, 0)).ok
    note = window.bus.document.board_notes[-1]
    window.scene.clearSelection()
    window.scene.boardNoteActivated.emit(note.id)
    assert window.scene.selected_board_note_ids() == (note.id,)
    assert window.inspector.shown is window.inspector.board_note_editor
    assert window.inspector.board_note_editor.text.text() == "CAN"
    _close(window)


def test_the_text_tool_writes_and_puts_the_keyboard_in_properties() -> None:
    """The Text tool asked what to write in a dialog first. It writes "Text" where it was
    clicked, selects it, and its words and size are the note's own fields in Properties."""
    from perfboard_studio.ui.i18n import t

    window = _window_on(_load_dense())
    before = len(window.bus.document.sheet_notes)
    window.on_sheet_note_drawn("text", 10.0, 10.0, 10.0, 10.0)
    assert len(window.bus.document.sheet_notes) == before + 1
    note = window.bus.document.sheet_notes[-1]
    assert note.text == t("Text")
    editor = window.inspector.sheet_note_editor
    assert window.inspector.shown is editor
    _type_into(editor.text, "POWER STAGE")
    edited = next(n for n in window.bus.document.sheet_notes if n.id == note.id)
    assert edited.text == "POWER STAGE"
    _close(window)



def test_a_part_only_in_the_design_is_edited_in_properties() -> None:
    """Drawn on the sheet and not placed: its reference, value, pin names and note in
    Properties through ``part.update``, and "not on the board yet" where a placed part has
    its hole. A double-click on it puts the keyboard in its Value."""
    window = _blank_window()
    _add(window, "R1", "r-axial-3")
    part = window.bus.document.parts[0]
    focused: list[str] = []
    real = window.inspector.focus_field
    window.inspector.focus_field = lambda name: (focused.append(name), real(name))[1]
    window._on_schematic_part_activated("R1")
    editor = window.inspector.design_part_editor
    assert window.inspector.shown is editor and focused == ["value"]
    steps = len(window.bus.history())
    _type_into(editor.value, "4k7")
    _type_into(editor.ref, "R5")
    editor.note.setPlainText("pull-down")
    editor._commit_note()
    edited = next(p for p in window.bus.document.parts if p.id == part.id)
    assert (edited.value, edited.ref, edited.note) == ("4k7", "R5", "pull-down")
    assert len(window.bus.history()) == steps + 3
    _close(window)



def test_an_empty_value_shows_what_a_value_of_that_kind_looks_like() -> None:
    """A new resistor's value was a blank box whose one example named a chip."""
    from perfboard_studio.ui.inspector import value_placeholder

    assert value_placeholder("R4") == "e.g. 470, 10k"
    assert value_placeholder("RV1") == "e.g. 10k"
    assert value_placeholder("C12") == "e.g. 100nF, 10µF"
    assert value_placeholder("L1") == "e.g. 10µH, 100µH"
    assert value_placeholder("U1") == "10k, 100nF, NE555…"
    assert value_placeholder("R?") == "e.g. 470, 10k"

    example = pathlib.Path(__file__).resolve().parent.parent / "examples" / "ne555-astable.perf"
    window = _window_on(persist.deserialize_document(example.read_text(encoding="utf-8")).document)
    try:
        resistor = next(c for c in window.bus.document.components if c.ref.startswith("R"))
        window.scene.select_components([resistor.id])
        window._refresh_selection_state()
        assert window.inspector.part_editor.value.placeholderText() == "e.g. 470, 10k"
    finally:
        _close(window)


def test_the_status_bar_no_longer_repeats_the_selection() -> None:
    """(c) The bar said the selected part's reference, value, package, hole and turn in a
    line nobody could act on; Properties shows all of it, editable."""
    from PySide6.QtWidgets import QLabel

    window = _window_on(_load_dense())
    component = window.bus.document.components[0]
    window.scene.select_components([component.id])
    window._refresh_selection_state()
    bar_text = " ".join(label.text() for label in window.statusBar().findChildren(QLabel))
    assert component.ref not in bar_text
    assert not hasattr(window, "label_selection")
    assert window.inspector.part_editor.ref.text() == component.ref
    _close(window)


def test_every_number_in_the_window_has_a_decimal_point() -> None:
    """A spin box wrote "2,28 mm" on a Turkish Windows while the sentence under it, the
    engine's, said "0.64 mm". The window writes numbers the engine's way, whatever the
    machine's locale and in either language."""
    from PySide6.QtCore import QLocale
    from PySide6.QtWidgets import QDoubleSpinBox

    before = QLocale()
    QLocale.setDefault(QLocale(QLocale.Language.Turkish, QLocale.Country.Turkey))
    try:
        window = _window_on(_load_dense())
        box = QDoubleSpinBox()
        box.setDecimals(2)
        box.setValue(2.28)
        assert box.text() == "2.28"
        box.deleteLater()
        # A field IN the window, which takes the window's locale: the window was made under
        # the machine's before the format was set, and every field in it wrote "0,00".
        field = window.inspector.board_editor.body_clearance
        assert field.locale().decimalPoint() == "."
        assert "," not in field.text()
        _close(window)
    finally:
        QLocale.setDefault(before)


def _takes_a_comma(box) -> bool:
    """Whether "2,5" typed into ``box`` reads 2.5, with room made for it: the question is
    the comma, not the field's own range, nor whether it is enabled for what is selected."""
    from PySide6.QtTest import QTest

    box.setEnabled(True)
    box.setReadOnly(False)
    box.setRange(min(box.minimum(), 0.0), max(box.maximum(), 100.0))
    box.setDecimals(max(box.decimals(), 1))
    box.lineEdit().selectAll()
    QTest.keyClicks(box.lineEdit(), "2,5")
    return box.cleanText() == "2.5"


def test_a_comma_typed_into_a_number_field_is_a_decimal_point() -> None:
    """The fields write "2.28", and a Turkish hand types "2,28" anyway: the comma is taken
    as the point it means, rather than swallowed into 228 -- and only by a number field
    (``ui/numberbox.py``), so a plain one is the control that says the test can tell."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDoubleSpinBox

    from perfboard_studio.ui.numberbox import NumberBox

    window = _window_on(_load_dense())
    try:
        box = NumberBox()
        box.setDecimals(2)
        box.setRange(0.0, 100.0)
        box.lineEdit().selectAll()
        QTest.keyClicks(box, "2,28")
        box.interpretText()
        assert box.value() == 2.28
        assert _takes_a_comma(NumberBox())
        assert not _takes_a_comma(QDoubleSpinBox())
    finally:
        _close(window)


def test_no_number_field_is_made_as_a_plain_double_spin_box() -> None:
    """The comma is taken by each field (``NumberBox``), no longer by one filter on the whole
    application, which ran on every event the window had to catch a key typed into one kind
    of widget. A field made as a plain ``QDoubleSpinBox`` would turn 2,28 into 228 without
    a word -- so none is made anywhere in the interface but inside ``NumberBox`` itself."""
    import ast

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "perfboard_studio"
    found = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "numberbox.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = node.func
                name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
                if name == "QDoubleSpinBox":
                    found.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not found, f"make these NumberBox (ui/numberbox.py): {found}"


def test_every_number_field_the_window_can_show_takes_a_comma() -> None:
    """Every number field the window can make, typed into: the Inspector's editors (built
    the first time each is wanted, so each is asked for here), the board's holes and
    connectors, the board designer and the custom part's dimensions in every family."""
    from PySide6.QtWidgets import QDoubleSpinBox

    from perfboard_studio.ui.inspector import Inspector
    from perfboard_studio.ui.main import CustomPartDialog
    from tests.designer_support import designer_on

    window = _window_on(_load_dense())
    try:
        inspector = window.inspector
        editors = [
            name for name, member in vars(Inspector).items()
            if isinstance(member, property) and name.endswith("_editor")
        ]
        assert len(editors) >= 10, editors
        for name in editors:
            getattr(inspector, name)
        boxes = {id(box): (f"inspector.{box.objectName() or type(box.parent()).__name__}", box)
                 for box in inspector.findChildren(QDoubleSpinBox)}
        assert len(boxes) >= 6

        designer = designer_on(window.bus.document.board)
        for box in designer.findChildren(QDoubleSpinBox):
            boxes[id(box)] = ("designer", box)

        refused = [where for where, box in boxes.values() if not _takes_a_comma(box)]
        # The custom part's fields are made anew for each family, so each is typed into
        # while its family is the one chosen.
        custom = CustomPartDialog(window)
        asked = 0
        for index in range(custom.family.count()):
            custom.family.setCurrentIndex(index)
            for box in custom.findChildren(QDoubleSpinBox):
                asked += 1
                if not _takes_a_comma(box):
                    refused.append(f"custom part {custom.family.itemText(index)}")
        assert asked, "the custom part has dimensions in some family"
        # Add Cable's length.
        from perfboard_studio.footprints import footprint_lookup
        from perfboard_studio.ui.cabledialog import CableDialog
        from tests.test_system_readers import _system

        cable = CableDialog(_system(), footprint_lookup(), "W2")
        lengths = cable.findChildren(QDoubleSpinBox)
        assert lengths, "Add Cable has a length"
        refused += ["add cable" for box in lengths if not _takes_a_comma(box)]
        assert not refused, refused
        designer.deleteLater()
        custom.deleteLater()
        cable.deleteLater()
    finally:
        _close(window)


def test_a_wire_becomes_another_kind_of_wire_in_one_step() -> None:
    """A bare wire that should have been insulated took deleting it and drawing it again.
    It is one ``conductor.replace`` from Properties, keeping its id, path and net -- so it
    stays selected -- and a wire is offered only the wire kinds, a trace only the traces."""
    from perfboard_studio.model import WireConductor

    window = _window_on(_load_dense())
    try:
        wire = next(c for c in window.bus.document.conductors if isinstance(c, WireConductor))
        window.scene.clearSelection()
        _select_conductor(window, wire.id)
        window._refresh_properties()
        editor = window.inspector.conductor_editor
        assert window.inspector.shown is editor
        assert editor.kind.findData("solder-trace") < 0
        other = "insulated-wire" if wire.kind != "insulated-wire" else "bare-wire"
        steps = len(window.bus.history())
        editor._commit_kind(other)
        now = next(c for c in window.bus.document.conductors if c.id == wire.id)
        assert (now.kind, now.path, now.net_id) == (other, wire.path, wire.net_id)
        assert len(window.bus.history()) == steps + 1
        assert wire.id in set(window.scene.selected_conductor_ids())
    finally:
        _close(window)


def _select_conductor(window, conductor_id: str) -> None:
    from perfboard_studio.ui.view2d import ConductorItem

    for item in window.scene.items():
        if isinstance(item, ConductorItem) and item.conductor_id == conductor_id:
            item.setSelected(True)
            return
    raise AssertionError(f"no item for {conductor_id}")


@pytest.mark.parametrize("width", [1600, 1280, 900])
def test_the_package_picker_opens_beside_properties_and_on_the_screen(width: int) -> None:
    """To the left of Properties, never over it -- the field it came from is in it -- and
    never off the screen, however narrow the window."""
    from PySide6.QtCore import QRect, QSize

    from perfboard_studio.ui.main import picker_position

    screen = QRect(0, 0, width, 800)
    panel = QRect(width - 300, 60, 300, 700)
    size = QSize(360, 420)
    at = picker_position(panel, size, screen)
    opened = QRect(at, size)
    assert screen.contains(opened), (width, opened)
    if width >= 900:
        assert not opened.intersects(panel), (width, opened)


def _add_wire(window, path, kind):
    from perfboard_studio.commands import AddConductorPayload, NewWireConductor, wire_side

    result = window.bus.dispatch(
        "conductor.add",
        AddConductorPayload(
            conductor=NewWireConductor(
                path=path, kind=kind, side=wire_side(kind, window.bus.document.board)
            )
        ),
    )
    assert result.ok, result.message
    return window.bus.document.conductors[-1]


def _rules(window) -> set[str]:
    return {v.rule for v in window._last_violations}


def test_a_wire_made_bare_where_it_crosses_bare_copper_is_found_at_once() -> None:
    """Insulated wire may cross; bare may not. Made bare in Properties, the crossing is a
    finding the moment the switch is made, not at the next edit."""
    window = _blank_window()
    try:
        _add_wire(window, (HoleCoord(2, 5), HoleCoord(8, 5)), "bare-wire")
        crossing = _add_wire(window, (HoleCoord(5, 2), HoleCoord(5, 8)), "insulated-wire")
        assert "conductor-crossing" not in _rules(window)
        _select_conductor(window, crossing.id)
        window._refresh_properties()
        window.inspector.conductor_editor._commit_kind("bare-wire")
        assert next(c for c in window.bus.document.conductors if c.id == crossing.id).kind == (
            "bare-wire"
        )
        assert "conductor-crossing" in _rules(window)
    finally:
        _close(window)


def test_a_wire_made_a_top_jumper_under_a_body_is_found_at_once() -> None:
    """Under a DIP's body a wire on the solder side is fine; a jumper over the parts runs
    into the body. Made a jumper in Properties, DRC says so straight away."""
    from perfboard_studio.commands import PlaceComponentPayload

    window = _blank_window()
    try:
        assert window.bus.dispatch(
            "component.place",
            PlaceComponentPayload(ref="U1", value="NE555", footprint_id="dip-8",
                                  anchor=HoleCoord(10, 10)),
        ).ok
        under = _add_wire(window, (HoleCoord(11, 8), HoleCoord(11, 15)), "bare-wire")
        assert "jumper-under-body" not in _rules(window)
        _select_conductor(window, under.id)
        window._refresh_properties()
        window.inspector.conductor_editor._commit_kind("top-jumper")
        assert "jumper-under-body" in _rules(window)
    finally:
        _close(window)


def test_a_kind_switch_never_drops_the_run() -> None:
    """Through every kind of wire and back, the run is there with its id, path and net
    after each switch; and a switch the bus refuses leaves it as it was, with the reason
    under the field."""
    from perfboard_studio.commands import ReplaceConductorsPayload

    window = _blank_window()
    try:
        run = _add_wire(window, (HoleCoord(2, 2), HoleCoord(9, 2)), "bare-wire")
        _select_conductor(window, run.id)
        window._refresh_properties()
        editor = window.inspector.conductor_editor
        for kind in ("insulated-wire", "top-jumper", "bare-wire"):
            editor._commit_kind(kind)
            now = next(c for c in window.bus.document.conductors if c.id == run.id)
            assert (now.kind, now.path) == (kind, run.path)

        def refuse(name, payload):
            return window.bus.dispatch(
                "conductor.replace",
                ReplaceConductorsPayload(remove_ids=("no-such-run",), conductors=()),
            )

        window.inspector._dispatch = refuse
        editor._commit_kind("insulated-wire")
        now = next(c for c in window.bus.document.conductors if c.id == run.id)
        assert now.kind == "bare-wire"
        assert editor.kind_problem.text() and not editor.kind_problem.isHidden()
        assert editor.kind.currentData() == "bare-wire"
    finally:
        _close(window)


@pytest.mark.parametrize("language", ["en", "tr"])
def test_every_editor_in_properties_fits_its_panel(language: str) -> None:
    """At 1280 and 1600 alike Change…, the 270° button and Delete were cut off the panel's
    right edge. The panel asks for the width the editor showing needs, so nothing is cut
    off whatever the language or the font -- measured against the editor itself, because
    the offscreen test font is not the one on screen."""
    from perfboard_studio.ui.i18n import language as current
    from perfboard_studio.ui.i18n import set_language

    before = current()
    set_language(language)
    try:
        window = _window_on(_load_dense())
        component = next(c for c in window.bus.document.components
                         if c.id in window.scene.component_items)
        net = window.bus.document.nets[0]
        panel = window.properties
        for show in (
            lambda: window.scene.clearSelection(),
            lambda: window.scene.select_components([component.id]),
            lambda: window._select_net(net.id),
        ):
            show()
            window._refresh_properties()
            editor = window.inspector.shown
            need = editor.minimumSizeHint().width()
            assert panel.scroller.minimumWidth() >= need, (type(editor).__name__, need)
        _close(window)
    finally:
        set_language(before)


def _every_editor(window):
    """Each editor Properties has, shown in turn: (its name, how to show it)."""
    document = window.bus.document
    drawn = [c for c in document.components if c.id in window.scene.component_items]
    yield "board", lambda: window.scene.clearSelection()
    yield "part", lambda: window.scene.select_components([drawn[0].id])
    yield "parts", lambda: window.scene.select_components([drawn[0].id, drawn[1].id])
    yield "net", lambda: window._select_net(document.nets[0].id)

    def conductor() -> None:
        window.scene.clearSelection()
        _first_conductor_item(window).setSelected(True)
        window._refresh_selection_state()

    yield "conductor", conductor
    yield "placing", lambda: window.scene.arm_placement("dip-8")

    def design_part() -> None:
        window.scene.arm_placement(None)
        window._show_symbol_in_properties(window._add_part_to_design("dip-8"))

    yield "design part", design_part
    yield "board note", lambda: window.on_add_board_label()
    yield "sheet note", lambda: window.on_sheet_note_drawn("text", 10.0, 10.0, 10.0, 10.0)


@pytest.mark.parametrize("language", ["en", "tr"])
def test_every_editor_fits_a_1440_by_900_window_with_nothing_under_it(language: str) -> None:
    """The walkthrough, at 1440 x 900: the first summary drawn under every editor after it
    -- "untitled · 18 × 24 holes" -- and right edges cut off. Shown, at that size, every
    editor in turn: nothing in it reaches past the panel's visible width, and it is the
    only thing in the panel."""
    from PySide6.QtWidgets import QWidget

    from perfboard_studio.ui.i18n import language as current
    from perfboard_studio.ui.i18n import set_language

    before = current()
    set_language(language)
    try:
        window = _window_on(_load_dense())
        window.resize(1440, 900)
        window.show()
        QApplication.processEvents()
        panel = window.properties
        holder = panel.scroller.widget()
        for name, show in _every_editor(window):
            show()
            window._refresh_properties()
            QApplication.processEvents()
            editor = window.inspector.shown
            shown = [
                child for child in holder.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
                if not child.isHidden()
            ]
            assert shown == [window.inspector], (name, [type(c).__name__ for c in shown])
            viewport = panel.scroller.viewport()
            right = viewport.width() + 1
            for child in editor.findChildren(QWidget):
                if not child.isVisible() or child.width() <= 0:
                    continue
                edge = child.mapTo(viewport, child.rect().topRight()).x()
                assert edge <= right, (name, type(child).__name__, edge, right)
        _close(window)
    finally:
        set_language(before)


def test_new_board_starts_a_blank_design_without_asking_about_a_board(monkeypatch) -> None:
    """Board Setup came first, before there was a circuit to try on any board, and the
    Board step asked again. New Board is a blank design with the sheet in front."""
    from perfboard_studio.ui import designer as designer_module

    window = _window_on(_load_dense())
    try:
        asked: list[str] = []
        monkeypatch.setattr(
            designer_module.BoardDesigner, "exec", lambda self: asked.append("board") or 0
        )
        monkeypatch.setattr(type(window), "_offer_to_save", lambda self: True)
        window.on_new()
        document = window.bus.document
        assert asked == []
        assert not document.components and not document.parts
        assert window._is_in_front(window.dock_schematic)
    finally:
        _close(window)


def test_redoing_the_wiring_of_moved_nets_is_asked_once(monkeypatch) -> None:
    """Redo Their Wiring on the moved-nets question opened a second box asking to redo the
    wiring, with the counts the first one lacked. One box now, with the count on it."""
    from PySide6.QtWidgets import QMessageBox

    window = _window_on(_load_dense())
    try:
        from perfboard_studio.commands import AddConductorPayload, NewWireConductor

        net = window.bus.document.nets[0]
        assert window.bus.dispatch(
            "conductor.add",
            AddConductorPayload(conductor=NewWireConductor(
                path=(HoleCoord(1, 1), HoleCoord(1, 4)), kind="insulated-wire", net_id=net.id
            )),
        ).ok
        document = window.bus.document
        stale = {net.id}
        window._nets_from_old_layout = set(stale)
        shown: list[str] = []
        confirmed: list[str] = []

        def answer(self) -> int:
            shown.append(self.text())
            return 0

        def redo_clicked(self):
            return next(b for b in self.buttons() if b.text() == window_t("Redo Their Wiring…"))

        from perfboard_studio.ui.i18n import t as window_t

        monkeypatch.setattr(QMessageBox, "exec", answer)
        monkeypatch.setattr(QMessageBox, "clickedButton", redo_clicked)
        monkeypatch.setattr(
            type(window), "_confirm", lambda self, *a, **k: confirmed.append("asked") or True
        )
        removed = sum(1 for c in document.conductors if c.net_id in stale)
        window._route(None)
        assert len(shown) == 1 and str(removed) in shown[0]
        assert confirmed == [], "the second box is gone"
    finally:
        _close(window)


def _bench(window):
    window._raise_view(window.dock_guide)
    window._refresh_guide_panel()
    return window.bench


def test_the_guide_opens_on_the_bench_at_the_first_step_not_done() -> None:
    """One step at a time, large: the guide opens on the bench, at the step somebody coming
    back to it left off -- the first one not ticked."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        bench = _bench(window)
        assert window.guide_pages.currentWidget() is bench
        first = bench.items[0]
        window._on_bench_ticked(first.key, True)
        bench.set_items(bench.items, bench._phases, window._done_steps(), 0, 0)
        assert bench.current == 1
        assert bench.title.text() == bench.items[1].title
        assert not bench.picture.pixmap().isNull()
    finally:
        _close(window)


def test_done_next_ticks_the_step_and_the_list_agrees() -> None:
    """One store of ticks: Done-next on the bench ticks the list's row, and a row ticked in
    the list is done on the bench."""
    from PySide6.QtCore import Qt

    from perfboard_studio.ui.main import ROLE_STEP_FOCUS

    window = _window_on(_example_document("ne555-astable"))
    try:
        bench = _bench(window)
        item = bench.items[bench.current]
        bench.next.click()
        assert item.key in window._done_steps()
        assert bench.current == bench.items.index(item) + 1
        row = next(leaf for leaf in window._guide_leaves()
                   if leaf.data(0, ROLE_STEP_FOCUS) == item.key)
        assert row.checkState(0) == Qt.CheckState.Checked
        other = next(leaf for leaf in window._guide_leaves()
                     if leaf.checkState(0) != Qt.CheckState.Checked)
        other.setCheckState(0, Qt.CheckState.Checked)
        assert other.data(0, ROLE_STEP_FOCUS) in bench.done
        bench.back.click()
        assert bench.items[bench.current] is item
    finally:
        _close(window)


def test_a_stripboards_track_cuts_are_the_first_bench_steps() -> None:
    """The cuts come before any part and are the most often forgotten: on the bench each is
    a step of its own, first, pictured from the copper side."""
    from perfboard_studio.striproute import plan_stripboard

    example = _example_document("ne555-astable")
    strips = dataclasses.replace(
        example,
        board=dataclasses.replace(example.board, type="stripboard", strip_axis="horizontal"),
        conductors=(),
    )
    window = _window_on(strips)
    try:
        plan = plan_stripboard(window.bus.document, window.lookup)
        assert window.bus.dispatch("stripboard.apply", plan.payload()).ok
        bench = _bench(window)
        cuts = window.current_guide().track_cuts
        assert cuts
        firsts = bench.items[: len(cuts)]
        assert all(item.key.startswith("cut:") and item.solder_side for item in firsts)
        assert all(item.step_index is None for item in firsts)
        assert bench.items[0].title.split(" ·")[0]
        assert bench.chips["tracks"].isVisibleTo(bench)
    finally:
        _close(window)


def test_a_solder_side_step_is_pictured_from_the_solder_side(monkeypatch) -> None:
    """The picture is the board as it stands at the step, from the side the step is done on:
    a trace or a bare wire below the board is drawn from below."""
    from perfboard_studio.ui import main as main_module

    window = _window_on(_example_document("ne555-astable"))
    try:
        bench = _bench(window)
        seen: list[str] = []
        real = main_module.BoardScene

        def scene(document, lookup, *, side, **kwargs):
            seen.append(side)
            return real(document, lookup, side=side, **kwargs)

        monkeypatch.setattr(main_module, "BoardScene", scene)
        below = next(i for i, item in enumerate(bench.items) if item.solder_side)
        above = next(i for i, item in enumerate(bench.items) if not item.solder_side)
        bench.show_item(below)
        bench.show_item(above)
        assert seen == ["bottom", "top"]
    finally:
        _close(window)


def test_the_phase_bar_names_the_current_phase_in_full_and_the_others_on_hover() -> None:
    """Every phase's name in its own segment wrapped to three lines in a narrow panel. The
    current one is named; the others are a bar with their name on hover."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        bench = _bench(window)
        bar = bench.phase_bar
        names = [name for name, _count in bar._phases]
        assert 0 <= bar._current < len(names)
        assert bench.items[bench.current].phase.title in names[bar._current]
        bar.resize(900, 30)
        other = next(i for i in range(len(names)) if i != bar._current)
        middle = bar._segments()[other].center().x()
        assert bar.phase_at(middle) == other
    finally:
        _close(window)


def test_a_check_ticked_on_the_bench_is_kept_with_the_steps() -> None:
    """The phase's checks are Ω items to tick on the bench, kept in the one store."""
    from PySide6.QtWidgets import QCheckBox

    from perfboard_studio.ui.benchguide import check_key

    window = _window_on(_example_document("ne555-astable"))
    try:
        bench = _bench(window)
        with_checks = next(i for i, item in enumerate(bench.items) if item.phase.checkpoints)
        bench.show_item(with_checks)
        phase = bench.items[with_checks].phase
        boxes = [b for b in bench.findChildren(QCheckBox) if b.text().startswith("Ω")]
        assert boxes
        boxes[0].setChecked(True)
        assert check_key(phase, phase.checkpoints[0]) in window._done_steps()
    finally:
        _close(window)


def _moved_off_its_copper(stem: str, by: int):
    """A routed example with its first part moved ``by`` holes to the right, and the window
    on it with the board chosen -- the walkthrough's board after a drag."""
    from perfboard_studio.commands import MoveComponentPayload
    from perfboard_studio.model import HoleCoord

    root = pathlib.Path(__file__).resolve().parents[1]
    document = persist.parse_document_or_throw(
        (root / "examples" / f"{stem}.perf").read_text(encoding="utf-8")
    )
    window = _window_on(document)
    window._board_chosen = True
    part = next(c for c in document.components if not c.locked)
    moved = window.bus.dispatch(
        "component.move",
        MoveComponentPayload(id=part.id, anchor=HoleCoord(part.anchor.col + by, part.anchor.row)),
    )
    assert moved.ok
    QApplication.processEvents()
    window._refresh_workflow()
    return window


def test_next_after_a_move_wires_rather_than_loops_on_show_problems(monkeypatch) -> None:
    """A part moved off its copper: a connection to wire and a short where its pin landed.
    Next said Show Problems, opened a drawer that could not wire anything, and said it
    again. The short is still red on the bar; Next is Auto-wire."""
    from perfboard_studio.ui.workflow import workflow_steps

    window = _moved_off_its_copper("ne555-astable", 2)
    try:
        steps = {step.key: step.status for step in workflow_steps(window.workflow_facts())}
        assert steps["route"] == "current" and steps["check"] == "problem"
        assert window.workflow_bar.next_key == "route"
        assert "Auto-wire" in window.workflow_bar.next_button.text()
        routed: list[object] = []
        monkeypatch.setattr(type(window), "_route", lambda self, only_net_ids=None: routed.append(only_net_ids))
        window.on_workflow_next(window.workflow_bar.next_key)
        assert routed == [None]
    finally:
        _close(window)


def test_once_the_drawer_is_open_next_goes_from_problem_to_problem() -> None:
    """Everything wired and a part overlapping another: Next opens the drawer, and then goes
    to each problem in it in turn rather than opening what is open."""
    from perfboard_studio.ui.main import ROLE_COMPONENT_IDS, ROLE_HOLES

    window = _moved_off_its_copper("lm317-supply", 2)
    try:
        assert window.workflow_bar.next_key == "check"
        assert window.workflow_bar.next_button.text().endswith("Show Problems")
        window.on_workflow_next("check")
        assert window.problems_bar.expanded
        assert window.workflow_bar.next_button.text().endswith("Next Problem")
        window.on_workflow_next("check")
        first = window.drc_tree.currentItem()
        assert first is not None and first.childCount() == 0
        assert first.data(0, ROLE_HOLES) or first.data(0, ROLE_COMPONENT_IDS)
    finally:
        _close(window)


def test_the_drawer_offers_auto_wire_beside_what_is_left_to_wire(monkeypatch) -> None:
    """"3 to wire" was a fact with nothing to press beside it."""
    window = _moved_off_its_copper("ne555-astable", 2)
    try:
        window._refresh_problems_bar()
        assert not window.problems_bar.wire.isHidden()
        routed: list[object] = []
        monkeypatch.setattr(type(window), "_route", lambda self, only_net_ids=None: routed.append(only_net_ids))
        window.problems_bar.wire.click()
        assert routed == [None]
    finally:
        _close(window)


def test_the_wiring_step_offers_auto_wire_and_does_nothing_by_itself(monkeypatch) -> None:
    """Pressing a step changes nothing; the Wiring step with connections left now offers
    Auto-wire under it, where it used to show the board and stop."""
    window = _moved_off_its_copper("ne555-astable", 2)
    try:
        routed: list[object] = []
        monkeypatch.setattr(type(window), "_route", lambda self, only_net_ids=None: routed.append(only_net_ids))
        window.on_workflow_step("route")
        assert routed == []
        offer = window._wire_offer
        [wire] = offer.actions()
        assert wire.text() == "Auto-wire 1 Connection"
        wire.trigger()
        assert routed == [None]
        offer.close()
    finally:
        _close(window)


def test_a_finding_can_be_gone_to_and_its_connections_wired(monkeypatch) -> None:
    """A finding's own menu says what can be done about it before offering to copy it."""
    window = _moved_off_its_copper("lm317-supply", 5)
    try:
        window.set_problems_open(True)
        assert window._go_to_next_problem()
        item = window.drc_tree.currentItem()
        rect = window.drc_tree.visualItemRect(item)
        labels = _menu_labels(window.drc_menu(rect.center()))
        assert labels[0] == "Go to It"
        assert "Copy This Problem" in labels
    finally:
        _close(window)


def test_enter_in_the_library_search_puts_the_first_part_on_the_sheet() -> None:
    """The status line said "Enter puts it on the sheet" and Enter in the search did
    nothing: it puts the first part the search lists there, as the package picker does."""
    from perfboard_studio.ui.main import ROLE_FOOTPRINT_ID

    window = _blank_window()
    try:
        window.on_schematic_add_part()
        window.library_filter.setText("resistor")
        before = len(window.bus.document.parts)
        window.library_filter.returnPressed.emit()
        assert len(window.bus.document.parts) == before + 1
        chosen = window.library_tree.currentItem()
        assert chosen is not None and chosen.data(0, ROLE_FOOTPRINT_ID)
    finally:
        _close(window)


def test_enter_with_nothing_found_says_so() -> None:
    window = _blank_window()
    try:
        window.on_schematic_add_part()
        window.library_filter.setText("zzzz-no-such-part")
        before = len(window.bus.document.parts)
        window.library_filter.returnPressed.emit()
        assert len(window.bus.document.parts) == before
        assert window.statusBar().currentMessage() == "No part in the Library matches that."
    finally:
        _close(window)


def test_the_boards_own_parts_are_searched_like_every_other() -> None:
    """A custom part's group listed above every search, whatever was typed."""
    from PySide6.QtWidgets import QTreeWidget

    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.main import populate_part_tree

    dip = get_footprint("dip-8")
    assert dip is not None
    custom = {"custom-dip": dip}
    tree = QTreeWidget()

    def groups(text: str) -> list[str]:
        populate_part_tree(tree, text, custom)
        return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]

    assert groups("")[0] == "This board"
    assert "This board" not in groups("resistor")
    assert "This board" in groups("dip")
    # First, as for any search: a catalog part may also say "this" and "board" (the relay
    # module's summary and its "relay board"), and is listed below it.
    assert groups("this board")[0] == "This board"


@pytest.mark.parametrize(
    ("language", "typed"),
    [("en", "perfboard"), ("en", "move to"), ("tr", "delikli"), ("tr", "taşı")],
)
def test_the_palette_finds_the_way_from_a_breadboard_to_perfboard(language: str, typed: str) -> None:
    """New Board from This Design was found only by "new board": its tooltip says it is how
    a breadboard goes on to perfboard, and that is what people type."""
    from perfboard_studio.ui.i18n import language as current
    from perfboard_studio.ui.i18n import set_language, t
    from perfboard_studio.ui.palette import rank

    before = current()
    set_language(language)
    try:
        window = _window_on(_load_dense())
        try:
            wanted = t("New Board from This &Design…").replace("&", "")
            found = [entry.label for entry in rank(window._palette_entries(), typed)]
            assert wanted in found, (typed, found[:8])
        finally:
            _close(window)
    finally:
        set_language(before)


def test_a_word_in_what_a_command_does_ranks_below_its_name() -> None:
    from perfboard_studio.ui.palette import Entry, rank

    def entry(label: str, also: str = "") -> Entry:
        return Entry(label=label, where="", keys="", run=lambda: None, also=also)

    named = entry("Perfboard Settings")
    described = entry("New Board from This Design…", also="goes on to perfboard")
    assert [e.label for e in rank([described, named], "perfboard")] == [
        "Perfboard Settings", "New Board from This Design…"]


def test_what_auto_wire_could_not_do_is_in_problems_not_a_box(monkeypatch) -> None:
    """A box listed twelve connections and had to be closed before any could be looked at.
    They are a group in the Problems drawer now, each a click from where it is, until the
    board changes."""
    from perfboard_studio.autoroute import UnroutedLink
    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui.main import ROLE_FINDING_KEY, ROLE_HOLES

    window = _moved_off_its_copper("ne555-astable", 2)
    try:
        boxes: list[object] = []
        monkeypatch.setattr(
            main_module.QMessageBox, "information", lambda *args, **kwargs: boxes.append(args)
        )
        link = next(link for entry in window._last_ratsnest for link in entry.links)
        window._report_unrouted_items([UnroutedLink(link=link, reason="no room")])
        assert boxes == []
        assert window.problems_bar.expanded
        tops = [window.drc_tree.topLevelItem(i) for i in range(window.drc_tree.topLevelItemCount())]
        assert tops[0].data(0, ROLE_FINDING_KEY) == "ERC", "the circuit's first, still"
        [group] = [top for top in tops if top.data(0, ROLE_FINDING_KEY) == "WIRING"]
        assert group.childCount() == 1
        assert group.child(0).data(0, ROLE_HOLES) == (link.from_, link.to)
        assert "could not be wired" in window.statusBar().currentMessage()
        window.on_undo()
        QApplication.processEvents()
        tops = [window.drc_tree.topLevelItem(i).data(0, ROLE_FINDING_KEY)
                for i in range(window.drc_tree.topLevelItemCount())]
        assert "WIRING" not in tops, "said of a board that is not there any more"
    finally:
        _close(window)


@pytest.mark.parametrize("language", ["en", "tr"])
def test_the_librarys_names_have_the_room_at_the_default_sidebar_width(language: str) -> None:
    """The Pins column took half the Library -- the stretched name column and the last
    section split the width -- and "AA battery holder" was "AA battery h…". The count is
    as wide as it needs, and every name says itself in full on hover."""
    from perfboard_studio.ui.i18n import language as current
    from perfboard_studio.ui.i18n import set_language

    before = current()
    set_language(language)
    try:
        window = _blank_window()
        try:
            window.resize(1440, 900)
            window.show()
            window.on_schematic_add_part()
            window.library_filter.setText("power" if language == "en" else "güç")
            QApplication.processEvents()
            tree = window.library_tree
            metrics = tree.fontMetrics()
            pins = tree.headerItem().text(1)
            need = max(metrics.horizontalAdvance(pins), metrics.horizontalAdvance("888")) + 32
            assert tree.columnWidth(1) <= need, (tree.columnWidth(1), need)
            assert tree.columnWidth(0) >= tree.viewport().width() - tree.columnWidth(1) - 2
            leaves = [
                tree.topLevelItem(i).child(j)
                for i in range(tree.topLevelItemCount())
                for j in range(tree.topLevelItem(i).childCount())
            ]
            assert leaves
            for leaf in leaves:
                assert leaf.text(0) in leaf.toolTip(0), leaf.text(0)
        finally:
            _close(window)
    finally:
        set_language(before)


def _first_found(text: str) -> tuple[str, str]:
    """(the first group, its first part) the Library lists for ``text``."""
    from PySide6.QtWidgets import QTreeWidget

    from perfboard_studio.ui.main import populate_part_tree

    tree = QTreeWidget()
    tree.setColumnCount(2)
    populate_part_tree(tree, text, {})
    group = tree.topLevelItem(0)
    assert group is not None, text
    return group.text(0), group.child(0).text(0)


@pytest.mark.parametrize(
    ("language", "typed", "group", "first"),
    [
        ("en", "resistor", None, "Resistor"),
        ("en", "power", "Power in", None),
        ("tr", "direnç", None, "Direnç"),
        ("tr", "LED", "LED'ler", None),
    ],
)
def test_what_a_search_finds_best_comes_first(language, typed, group, first) -> None:
    """reach's walkthrough: "resistor" listed the inductor and the LDR before the resistor,
    "power" the TIP31C before the power-in terminal, and Turkish "LED" the AA battery
    holder first. One ranking, parts' (``catalog.search_rank``), for the Library and the
    package picker: the leaves of a group best first, and the groups by their best."""
    from perfboard_studio.ui.i18n import set_language

    set_language(language)
    try:
        found_group, found_first = _first_found(typed)
        if group is not None:
            assert found_group == group, (typed, found_group, found_first)
        if first is not None:
            assert found_first.startswith(first), (typed, found_group, found_first)
    finally:
        set_language("en")


def test_with_nothing_typed_the_library_is_in_its_own_order() -> None:
    """Every rank is the same with nothing typed: the catalog's order, packages after."""
    from PySide6.QtWidgets import QTreeWidget

    from perfboard_studio.catalog import CATEGORY_ORDER
    from perfboard_studio.ui.main import _catalog_headings, populate_part_tree

    tree = QTreeWidget()
    tree.setColumnCount(2)
    populate_part_tree(tree, "", {})
    headings = _catalog_headings()
    listed = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    catalog = [headings[c] for c in CATEGORY_ORDER if headings[c] in listed]
    assert listed[: len(catalog)] == catalog


def _designer(window, monkeypatch, act):
    """Open the board designer and do ``act`` to it in place of a person."""
    from perfboard_studio.ui import designer as designer_module

    seen: list = []

    def run(dialog) -> int:
        seen.append(dialog)
        act(dialog)
        return int(dialog.result())

    monkeypatch.setattr(designer_module.BoardDesigner, "exec", run)
    window.on_design_board()
    return seen[0]


def test_the_designer_puts_a_stock_board_on_in_one_step(monkeypatch) -> None:
    """A green 5 x 7 cm board from the catalogue: its grid, its edge pads and its corner
    holes, as ONE board.applyPreset -- one undo step."""
    window = _blank_window()
    try:
        before = len(window.bus.history())

        def choose(dialog) -> None:
            _choose_family(dialog, "double-sided-fr4")
            index = next(i for i in range(dialog.stock.count())
                         if dialog.stock.itemText(i).startswith("5 x 7"))
            dialog._on_stock_size(index)
            dialog._use()

        _designer(window, monkeypatch, choose)
        document = window.bus.document
        assert (document.board.cols, document.board.rows) == (24, 18)
        assert document.edge_connectors and document.mounting_holes
        assert len(window.bus.history()) == before + 1
    finally:
        _close(window)


def test_the_designer_says_a_problem_under_its_field_and_holds_use(monkeypatch) -> None:
    """The engine's one refusal, said where it applies: a drill wider than its pad."""
    window = _blank_window()
    try:
        def wrong(dialog) -> None:
            dialog.drill.setValue(dialog.pad.value() + 1.0)
            dialog._show()

        dialog = _designer(window, monkeypatch, wrong)
        shown = [path for path, label in dialog._problems.items() if not label.isHidden()]
        assert shown, "the refusal is under a field"
        assert not dialog.use.isEnabled()
    finally:
        _close(window)


def test_a_board_saved_as_mine_is_offered_next_time(monkeypatch) -> None:
    """Saved in the settings, as the board colour is: the next designer lists it after the
    catalogue, by the name it was given, and says it in that name in any language."""
    from perfboard_studio.boardfamily import FAMILIES
    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui.designer import family_name, load_user_families

    window = _blank_window()
    try:
        def save(dialog) -> None:
            dialog.name.setText("Bench 6x8")
            dialog._save_as_mine()

        _designer(window, monkeypatch, save)
        mine = load_user_families(main_module.app_settings())
        assert [f.name for f in mine][-1:] == ["Bench 6x8"]
        assert mine[-1].user and family_name(mine[-1]) == "Bench 6x8"

        def look(dialog) -> None:
            this = 1 if dialog._this is not None else 0
            assert dialog.families.count() == this + len(FAMILIES) + len(mine)

        _designer(window, monkeypatch, look)
    finally:
        _close(window)


def test_a_family_and_its_words_are_said_in_the_windows_language() -> None:
    """A catalogue family by its id through the catalogue; every vocabulary in words."""
    from perfboard_studio.boardfamily import FAMILIES
    from perfboard_studio.ui.designer import _words, family_name
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        names = [family_name(f) for f in FAMILIES]
        assert all(name != f.name for name, f in zip(names, FAMILIES, strict=True))
        for vocabulary in _words().values():
            for value, word in vocabulary.items():
                assert word and word != value, f"{value} is shown as its id"
    finally:
        set_language(before)


def test_the_designers_settings_fit_their_column(monkeypatch) -> None:
    """A material's whole sentence in a combo made the settings wider than their column, and
    every field's right edge was cut off: the column asks for no more than it is given."""
    window = _blank_window()
    try:
        def look(dialog) -> None:
            scroller = dialog._scroller
            settings = scroller.widget()
            bar = scroller.verticalScrollBar().sizeHint().width()
            for row in range(dialog.families.count()):
                dialog.families.setCurrentRow(row)
                need = settings.minimumSizeHint().width() + bar
                assert scroller.minimumWidth() >= need, (row, need, scroller.minimumWidth())

        _designer(window, monkeypatch, look)
    finally:
        _close(window)


def _shown(dialog, path: str) -> bool:
    """Whether the designer's row for ``path`` is on show."""
    form, holder = dialog._rows[path]
    return form.isRowVisible(holder)


def _choose_family(dialog, family_id: str) -> None:
    """By id, among what the dialog lists: "This board" comes first when no catalogue
    family makes the board that is open."""
    dialog.families.setCurrentRow([f.id for f in dialog._everything()].index(family_id))


def test_a_breadboard_is_chosen_by_its_size_and_its_channel(monkeypatch) -> None:
    """Board Setup's breadboard questions, in the designer: the size by its points, biggest
    first, the channel by what straddles it, a flex body's narrow part -- and nothing a
    breadboard's kind decides: no grid, pads, edge pads, corner holes, print or colour."""
    from perfboard_studio.breadboard import channel_of

    window = _blank_window()
    try:
        def choose(dialog) -> None:
            _choose_family(dialog, "breadboard")
            assert dialog.stock.itemText(0).startswith("Full size · 830")
            assert dialog.stock.count() == 3, "sold in its sizes, not cut to measure"
            assert _shown(dialog, "breadboard.channel_mils")
            for path in ("grid", "sizes", "breadboard.narrow_channel_cols",
                         "breadboard.border_x_mm", "pitch_mm", "strip.edges", "mask"):
                assert not _shown(dialog, path), path
            for key in ("grid", "edge", "holes", "legend", "colour"):
                assert dialog._sections[key][0].isHidden(), key
            dialog.channel.setCurrentIndex(dialog.channel.findData("1000-flex"))
            dialog._on_channel()
            assert dialog.narrow.value() == 39 and _shown(dialog, "breadboard.narrow_channel_cols")
            # The 400 and the mini cannot keep 39 columns narrow: only what can be made.
            assert [dialog.stock.itemText(i) for i in range(dialog.stock.count())] == [
                "Full size · 830 points · 63 columns"]
            dialog._use()

        _designer(window, monkeypatch, choose)
        board = window.bus.document.board
        assert (board.type, board.cols, channel_of(board), board.narrow_channel_cols) == (
            "breadboard", 63, 10, 39)
    finally:
        _close(window)


def test_a_solderable_breadboard_is_asked_its_size_and_its_border(monkeypatch) -> None:
    """Its border is where its makers differ, so it is asked; its channel is the ordinary
    one, so it is not. Corner holes and colour are a copper board's to choose."""
    window = _blank_window()
    try:
        def choose(dialog) -> None:
            _choose_family(dialog, "solderable-breadboard")
            assert _shown(dialog, "breadboard.border_x_mm") and _shown(dialog, "breadboard.border_y_mm")
            assert not _shown(dialog, "breadboard.channel_mils")
            assert not dialog._sections["holes"][0].isHidden()
            assert not dialog._sections["colour"][0].isHidden()
            dialog.border_x.setValue(3.0)
            dialog._use()

        _designer(window, monkeypatch, choose)
        board = window.bus.document.board
        assert (board.type, board.cols, board.border_x_mm) == ("solderable-breadboard", 63, 3.0)
    finally:
        _close(window)


def test_leaving_a_breadboard_brings_its_settings_back(monkeypatch) -> None:
    """Every section a breadboard hides is back on the next perfboard, and the kind is
    offered there again -- with no breadboard in it, which is a family of its own."""
    window = _blank_window()
    try:
        def look(dialog) -> None:
            _choose_family(dialog, "breadboard")
            _choose_family(dialog, "double-sided-fr4")
            for key in ("grid", "edge", "holes", "legend", "colour"):
                assert not dialog._sections[key][0].isHidden(), key
            assert _shown(dialog, "grid") and _shown(dialog, "type")
            assert not _shown(dialog, "breadboard.channel_mils")
            kinds = {dialog.type.itemData(i) for i in range(dialog.type.count())}
            assert kinds == {"pad-per-hole", "stripboard"}

        _designer(window, monkeypatch, look)
    finally:
        _close(window)


def test_the_designers_fields_start_at_one_edge_in_every_section() -> None:
    """Each section's form sized its own label column, so the fields' left edge zig-zagged
    from group to group. One column for all; and the grid's two counts share their row as
    the size in millimetres does."""
    from PySide6.QtWidgets import QFormLayout, QLabel

    from perfboard_studio.ui.i18n import set_language
    from tests.designer_support import designer_on

    set_language("tr")
    try:
        dialog = designer_on(_load_dense().board)
        dialog.resize(1180, 820)
        dialog.show()
        QApplication.processEvents()
        lefts = set()
        for _heading, form in dialog._sections.values():
            for row in range(form.rowCount()):
                label = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if label is None or field is None or not isinstance(label.widget(), QLabel):
                    continue
                if field.widget() is not None and field.widget().isVisible():
                    lefts.add(field.widget().mapTo(dialog, field.widget().rect().topLeft()).x())
        assert len(lefts) == 1, sorted(lefts)
        assert abs(dialog.cols.width() - dialog.rows.width()) <= 2
        dialog.close()
    finally:
        set_language("en")


def test_the_material_is_short_in_its_field_and_said_in_full_on_hover() -> None:
    """The sentence in the closed box was cut off at the column's width."""
    from PySide6.QtCore import Qt

    from tests.designer_support import designer_on

    dialog = designer_on(_load_dense().board)
    dialog.material.setCurrentIndex(dialog.material.findData("FR4"))
    assert dialog.material.currentText() == "FR-4 (glass epoxy)"
    said = dialog.material.itemData(dialog.material.currentIndex(), Qt.ItemDataRole.ToolTipRole)
    assert said.startswith("FR-4 — glass epoxy") and dialog.material.toolTip() == said


def test_the_boards_kind_in_properties_is_said_in_the_windows_language() -> None:
    """Board Setup's table of whole lines was where these were read from; it retired, the
    catalogue scan took the lines for unused, and a Turkish window said "Pad per hole"."""
    from perfboard_studio.ui.i18n import set_language

    set_language("tr")
    try:
        window = _window_on(_load_dense())
        try:
            window.scene.clearSelection()
            window._refresh_properties()
            # With nothing selected Properties says the step; the board is one click on.
            window.inspector.open_board_settings()
            assert window.inspector.board_editor.summary.text().startswith("Delik başına ped")
        finally:
            _close(window)
    finally:
        set_language("en")


def test_a_border_hole_is_said_to_be_outside_its_hole() -> None:
    """The stock boards' corner holes sit in the border, and "A1" read as drilled through A1:
    one with an offset is outside the hole it is addressed by."""
    from perfboard_studio.model import MountingHole
    from perfboard_studio.ui.boardfeatures import hole_said
    from perfboard_studio.ui.i18n import set_language

    board = _blank_document().board
    on_grid = MountingHole(id="mh-1", at=HoleCoord(0, 0))
    in_border = MountingHole(id="mh-2", at=HoleCoord(0, 0), offset_x_mm=-1.2, offset_y_mm=-1.2)
    assert hole_said(on_grid, board)[0] == "A1"
    assert hole_said(in_border, board)[0] == "outside A1"
    set_language("tr")
    try:
        # No suffix on the address: the word beside it carries it.
        assert hole_said(in_border, board)[0] == "A1 deliğinin dışında"
    finally:
        set_language("en")


def test_the_first_finger_is_chosen_by_its_address() -> None:
    """A spin box from 0 was the engine's index; the field lists the holes the edge has, by
    the address the list beside it says them in."""
    window = _window_on(_blank_document())
    try:
        features = _board_features(window)
        features.edge.setCurrentIndex(features.edge.findData("bottom"))
        board = window.bus.document.board
        assert features.finger_start.count() == board.cols
        assert features.finger_start.itemText(0).startswith("A")
        features.finger_start.setCurrentIndex(2)
        features.finger_count.setValue(3)
        features.add_connector.click()
        (connector,) = window.bus.document.edge_connectors
        assert (connector.start, connector.count) == (2, 3)
        features.edge.setCurrentIndex(features.edge.findData("left"))
        assert features.finger_start.count() == board.rows
    finally:
        _close(window)


def test_fit_leaves_the_floating_bars_their_room() -> None:
    """Fitted to the viewport, the board's top-left corner was under the tool rail and a
    corner hole chosen there half hidden by it (lead's R2 review). A fit keeps the board
    clear of the rail and of the view bar."""
    from PySide6.QtCore import QRect

    window = _window_on(_load_dense())
    try:
        window.resize(1440, 900)
        window.show()
        window.show_board()
        # Fitted at the layout the window settles on. With no fonts -- the CI runner's
        # offscreen platform -- the docks lay themselves out again a few passes after the
        # first showing (Properties' minimum width grows), and the Windows runner on
        # PySide6 6.12 did it after the fit: the board panel gave up 18 px and a board
        # fitted to the wider panel met the tool rail. Keeping a fit through a resize is
        # its own change (BoardView, after 0.23).
        _settle_events(QApplication)
        view = window.view
        view.fit_board()
        _settle_events(QApplication)
        board = view.mapFromScene(view.sceneRect()).boundingRect()
        for bar in view.overlays:
            assert bar.isVisible()
            corner = view.viewport().mapFromGlobal(bar.mapToGlobal(QPoint(0, 0)))
            box = QRect(corner, bar.size())
            assert not box.intersects(board), (bar.objectName(), box, board)
    finally:
        _close(window)


def test_a_chosen_holes_fields_change_it_in_place() -> None:
    """Its editor is fields now, not facts and a Remove: each one update, one undo step,
    and a refusal said under them with the hole unchanged."""
    from perfboard_studio.commands import AddMountingHolesPayload

    window = _window_on(_load_dense())
    try:
        window.bus.dispatch("mounting-hole.addMany", AddMountingHolesPayload(ats=(HoleCoord(1, 1),)))
        (mount,) = window.bus.document.mounting_holes
        window.scene.mount_items[mount.id].setSelected(True)
        window._selection_from = "board"
        window._refresh_properties()
        editor = window.inspector.feature_editor
        steps = len(window.bus.history())
        editor.diameter.setValue(2.5)
        editor.diameter.editingFinished.emit()
        assert window.bus.document.mounting_holes[0].diameter == 2.5
        assert len(window.bus.history()) == steps + 1
        editor.where.setText("D4")
        editor.where.editingFinished.emit()
        assert window.bus.document.mounting_holes[0].at == HoleCoord(3, 3)
        head = window.bus.document.mounting_holes[0].head_diameter
        editor.head.setValue(1.0)  # smaller than the bore: add refuses it, so update does
        editor.head.editingFinished.emit()
        assert window.bus.document.mounting_holes[0].head_diameter == head
        assert editor.problem.text() and not editor.problem.isHidden()
    finally:
        _close(window)


def test_a_chosen_connectors_fields_move_it_in_place() -> None:
    window = _window_on(_featured_document())
    try:
        (connector,) = window.bus.document.edge_connectors
        window.scene.connector_items[connector.id].setSelected(True)
        window._selection_from = "board"
        window._refresh_properties()
        editor = window.inspector.feature_editor
        assert editor.connector_fields.isVisibleTo(editor) and not editor.hole_fields.isVisibleTo(editor)
        editor.first.setCurrentIndex(editor.first.findData(1))
        editor.first.activated.emit(editor.first.currentIndex())
        assert window.bus.document.edge_connectors[0].start == 1
        editor.fingers.setValue(4)
        editor.fingers.editingFinished.emit()
        assert window.bus.document.edge_connectors[0].count == 4
    finally:
        _close(window)


def test_the_boards_features_ask_no_more_room_than_the_board_editor() -> None:
    """The group's heading on one line asked 612 px; Properties took it and the board view
    lost a third of a 1600 px window. It wraps, as its labels do."""
    window = _window_on(_blank_document())
    try:
        editor = window.inspector.board_editor
        features = editor.features
        others = max(
            child.minimumSizeHint().width()
            for child in (editor.name, editor.body_measure, editor.height_limit)
        )
        assert features.minimumSizeHint().width() <= others, (
            features.minimumSizeHint().width(), others)
    finally:
        _close(window)


def test_the_librarys_own_group_is_said_in_turkish() -> None:
    """Capitalised as every other group and as the designer says it: "Bu kart"."""
    from PySide6.QtWidgets import QTreeWidget

    from perfboard_studio.footprints import get_footprint
    from perfboard_studio.ui.i18n import set_language
    from perfboard_studio.ui.main import populate_part_tree

    dip = get_footprint("dip-8")
    assert dip is not None
    set_language("tr")
    try:
        tree = QTreeWidget()
        tree.setColumnCount(2)
        populate_part_tree(tree, "", {"custom-dip": dip})
        assert tree.topLevelItem(0).text(0) == "Bu kart"
    finally:
        set_language("en")


def _on_the_old_gy521():
    from perfboard_studio.catalog import catalog_part
    from perfboard_studio.model import ComponentInstance

    part = catalog_part("gy-521")
    assert part is not None
    component = ComponentInstance(
        id="imu", ref="U4", value=part.placed_value,
        footprint_id="mod-8x1-p1-r1-21.2x16.4x1.5-s8.5-o0x6.7",
        anchor=HoleCoord(col=4, row=12), pin_names=part.pin_names,
    )
    return _window_on(dataclasses.replace(_blank_document(), components=(component,)))


def test_a_part_on_a_replaced_package_is_one_press_from_the_current_one() -> None:
    """parts' superseded-footprint finding told the builder to choose the part again under
    Change...; its Properties say so and do it, the same pins on the same holes, one step."""
    from perfboard_studio.footprints import SUPERSEDED_FOOTPRINTS

    window = _on_the_old_gy521()
    try:
        window.scene.select_components(["imu"])
        window._refresh_properties()
        editor = window.inspector.part_editor
        assert not editor.older.isHidden()
        before = window.bus.document.components[0]
        steps = len(window.bus.history())
        editor.use_current.click()
        after = window.bus.document.components[0]
        assert after.footprint_id == SUPERSEDED_FOOTPRINTS[before.footprint_id][0]
        assert (after.anchor, after.pin_names) == (before.anchor, before.pin_names)
        assert len(window.bus.history()) == steps + 1
        window._refresh_properties()
        assert editor.older.isHidden()
    finally:
        _close(window)


def test_the_older_package_finding_offers_the_current_one() -> None:
    from perfboard_studio.footprints import SUPERSEDED_FOOTPRINTS
    from perfboard_studio.ui.main import ROLE_FINDING_KEY

    window = _on_the_old_gy521()
    try:
        tree = window.drc_tree
        found = None
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            for j in range(top.childCount()):
                if str(top.child(j).data(0, ROLE_FINDING_KEY)).startswith("drc:superseded-footprint"):
                    found = top.child(j)
        assert found is not None, "the rule's row"
        assert window._superseded_for(found) == ("imu",)
        window._use_current_packages(window._superseded_for(found))
        (component,) = window.bus.document.components
        assert component.footprint_id not in SUPERSEDED_FOOTPRINTS
    finally:
        _close(window)


def test_a_shipped_example_opens_with_no_problem_and_its_bench_check_listed() -> None:
    """ne555-astable opened on an orange "Problems 1": an R5' gap the router accepted and
    the guide checks at the bench. The badge is what is wrong; the gap is counted beside
    "to wire", and listed in a group of its own with its go-to."""
    from perfboard_studio.ui.main import ROLE_FINDING_KEY, ROLE_HOLES

    root = pathlib.Path(__file__).resolve().parents[1]
    document = persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    window = _window_on(document)
    try:
        bar = window.problems_bar
        assert bar.badge.isHidden() and bar.errors == 0 and bar.warnings == 0
        assert "1 to check at the bench" in bar.facts.text()
        groups = [
            window.drc_tree.topLevelItem(i).child(j)
            for i in range(window.drc_tree.topLevelItemCount())
            for j in range(window.drc_tree.topLevelItem(i).childCount())
        ]
        (bench,) = [g for g in groups if g.data(0, ROLE_FINDING_KEY) == "drc:solder-trace-proximity"]
        assert bench.text(0) == "To check at the bench"
        leaf = bench.child(0)
        while leaf.childCount():
            leaf = leaf.child(0)
        assert leaf.data(0, ROLE_HOLES)
        # The Check step says what is wrong too: nothing.
        from perfboard_studio.ui.workflow import workflow_steps

        check = next(s for s in workflow_steps(window.workflow_facts()) if s.key == "check")
        assert check.status == "done"
    finally:
        _close(window)


def test_a_bench_check_picked_in_the_drawer_rings_its_holes_over_the_parts() -> None:
    """The drawer is how a bench check is gone to: picking it, or pointing at its row, brings
    its rings up over the parts (``BoardScene.set_focused_holes``); picking nothing, or a
    row with no holes, puts them back under (``tests/test_bench_rings.py``)."""
    from perfboard_studio.ui.main import ROLE_FINDING_KEY, ROLE_HOLES

    root = pathlib.Path(__file__).resolve().parents[1]
    document = persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    window = _window_on(document)
    try:
        groups = [
            window.drc_tree.topLevelItem(i).child(j)
            for i in range(window.drc_tree.topLevelItemCount())
            for j in range(window.drc_tree.topLevelItem(i).childCount())
        ]
        (bench,) = [g for g in groups if g.data(0, ROLE_FINDING_KEY) == "drc:solder-trace-proximity"]
        leaf = bench.child(0)
        while leaf.childCount():
            leaf = leaf.child(0)
        assert leaf.data(0, ROLE_HOLES)
        assert window.scene._focus_item is None, "nothing picked, nothing over the parts"
        window.drc_tree.setCurrentItem(leaf)
        assert window.scene._focus_item is not None
        assert {(h.col, h.row) for h in window.scene._focus_item.holes} == {
            (h.col, h.row) for h in leaf.data(0, ROLE_HOLES)
        }
        window.drc_tree.setCurrentItem(bench.parent())
        assert window.scene._focus_item is None
    finally:
        _close(window)



def test_the_boards_features_are_one_line_until_asked_for(monkeypatch, tmp_path) -> None:
    """Open, the group was the whole panel with nothing selected -- every user's first view
    of Properties and the README's front picture. Closed by default, it says how many in one
    line; the menu and a hole chosen on the board open it, and open or closed is kept."""
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui.main import FEATURES_OPEN_KEY, _stored_bool

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    window = _window_on(_featured_document())
    try:
        window.scene.clearSelection()
        window._refresh_properties()
        window.inspector.open_board_settings()  # nothing selected shows the step
        features = window.inspector.board_editor.features
        assert not features.is_open() and features.body.isHidden()
        assert features.summary.text() == "1 mounting hole  ·  1 edge connector"

        window.on_board_features()
        assert features.is_open() and not features.body.isHidden()
        assert _stored_bool(store, FEATURES_OPEN_KEY, False) is True

        features.toggle.click()  # closed by hand, and remembered so
        assert not features.is_open()
        assert _stored_bool(store, FEATURES_OPEN_KEY, True) is False

        (mount,) = window.bus.document.mounting_holes
        window.scene.mount_items[mount.id].setSelected(True)
        window._selection_from = "board"
        window._refresh_properties()
        assert features.is_open(), "a hole chosen on the board opens the board's list"
    finally:
        _close(window)

    window = _window_on(_featured_document())
    try:
        assert window.inspector.board_editor.features.is_open(), "kept for the next window"
    finally:
        _close(window)


def test_a_board_with_no_features_says_so_in_one_line() -> None:
    window = _window_on(_blank_document())
    try:
        features = window.inspector.board_editor.features
        window.scene.clearSelection()
        window._refresh_properties()
        window.inspector.open_board_settings()  # nothing selected shows the step
        assert features.summary.text() == "No mounting holes or edge connectors"
    finally:
        _close(window)


def test_the_designer_opens_no_bigger_than_the_screen(monkeypatch) -> None:
    """At 1180 x 820 on a 1280 x 720 laptop its Use This Board was below the screen."""
    from PySide6.QtCore import QRect

    from perfboard_studio.ui import designer as designer_module

    class _Screen:
        def availableGeometry(self) -> QRect:
            return QRect(0, 0, 1280, 680)

    window = _blank_window()
    try:
        monkeypatch.setattr(type(window), "screen", lambda self: _Screen())
        size = designer_module._opening_size(window)
        assert size.width() <= 1280 - 40 and size.height() <= 680 - 60
        roomy = type("Roomy", (), {"availableGeometry": lambda self: QRect(0, 0, 2560, 1440)})()
        monkeypatch.setattr(type(window), "screen", lambda self: roomy)
        assert designer_module._opening_size(window) == designer_module.OPENING
    finally:
        _close(window)


def test_the_last_step_ends_the_build_and_ticks_no_check_for_the_builder(monkeypatch) -> None:
    """The last step's button said "Done, next" and did nothing: the release walkthrough
    pressed it at 23 of 23 with nowhere to go. It says "Done ✓", and after it the ending
    lists the checks not ticked -- unticked, because only the builder measured them -- and
    offers the export and Save."""
    from PySide6.QtWidgets import QCheckBox

    from perfboard_studio.ui.benchguide import check_key

    window = _window_on(_example_document("ne555-astable"))
    try:
        bench = _bench(window)
        for _ in range(len(bench.items) - 1):
            assert bench.next.text() == "Done, next  ▶"
            bench.next.click()
        assert bench.current == len(bench.items) - 1
        assert bench.next.text() == "Done  ✓"
        bench.next.click()
        assert bench.pages.currentWidget() is bench.ending
        assert not bench.next.isVisibleTo(bench)
        assert bench.ending_title.text() == "Every step is done."
        assert bench.go_to_first.isHidden()
        done = window._done_steps()
        assert all(item.key in done for item in bench.items)
        phases = window.current_guide().phases
        checks = list(dict.fromkeys(check_key(p, c) for p in phases for c in p.checkpoints))
        assert checks and not any(key in done for key in checks), "a check ticked for the builder"
        boxes = [b for b in bench.ending.findChildren(QCheckBox) if not b.isHidden()]
        assert len(boxes) == len(checks) and not any(b.isChecked() for b in boxes)
        # The last phase has no step and every short test: the bench showed none of them.
        closing = phases[-1]
        assert closing.checkpoints and not any(item.phase is closing for item in bench.items)
        assert any(b.text() == f"Ω  {closing.checkpoints[0].title}" for b in boxes)
        boxes[0].setChecked(True)
        assert checks[0] in window._done_steps()

        asked: list[str] = []
        monkeypatch.setattr(window, "on_export_guide", lambda: asked.append("export"))
        monkeypatch.setattr(window, "on_save", lambda: asked.append("save") or True)
        bench.export_button.click()
        bench.save_button.click()
        assert asked == ["export", "save"]

        window._refresh_guide_panel()
        assert bench.pages.currentWidget() is bench.ending, "a finished board reopens at its end"
        bench.back.click()
        assert bench.pages.currentWidget() is bench.card
        assert bench.current == len(bench.items) - 1 and bench.next.isVisibleTo(bench)
    finally:
        _close(window)


def test_an_ending_with_steps_skipped_goes_to_the_first() -> None:
    window = _window_on(_example_document("ne555-astable"))
    try:
        bench = _bench(window)
        bench.show_item(len(bench.items) - 1)
        bench.next.click()
        assert bench.pages.currentWidget() is bench.ending
        skipped = len(bench.items) - 1
        assert bench.ending_title.text() == f"{skipped} steps are not ticked yet"
        assert bench.counter.text() == f"1 of {len(bench.items)} steps done"
        assert not bench.go_to_first.isHidden() and bench.go_to_first.text() == "Go to Step 1"
        bench.go_to_first.click()
        assert bench.pages.currentWidget() is bench.card and bench.current == 0
    finally:
        _close(window)


def test_a_phases_checks_scroll_in_a_short_narrow_panel() -> None:
    """At 1280 x 720 the guide's panel is narrow and short, and a phase of nine checks was
    nine rows drawn over one another. They scroll, each row its full height."""
    import itertools

    from PySide6.QtWidgets import QCheckBox

    window = _window_on(_example_document("ne555-astable"))
    try:
        bench = _bench(window)
        most = max(range(len(bench.items)), key=lambda i: len(bench.items[i].phase.checkpoints))
        bench.show_item(most)
        window.resize(1280, 720)
        window.show()
        QApplication.processEvents()
        bench.checks.activate()
        laid = (bench.checks.itemAt(i).widget() for i in range(bench.checks.count()))
        boxes = [b for b in laid if isinstance(b, QCheckBox)]
        assert len(boxes) >= 5
        for box in boxes:
            assert box.height() >= box.sizeHint().height(), "a check squeezed under its own height"
        tops = [b.y() for b in boxes]
        assert all(b - a >= boxes[0].sizeHint().height() for a, b in itertools.pairwise(tops))
        assert bench.checks_scroll.verticalScrollBar().maximum() > 0
        assert bench.checks_scroll.height() >= 2 * boxes[0].sizeHint().height()
    finally:
        _close(window)


def test_a_long_step_leaves_the_3d_slider_its_groove() -> None:
    """Beside the guide at a third of the window, the step's label held its whole line and
    the slider got only its handle. The label ends in an ellipsis, the line in its tip."""
    from PySide6.QtWidgets import QLabel

    window = _window_on(_load_dense())
    try:
        bar = window._build_assembly_bar()
        window._3d_layout.addWidget(bar)
        window.act_step_back.click()
        label = window.assembly_label
        line = label.text()
        assert line.startswith(f"{len(window._assembly_steps())}/") and label.toolTip() == line
        bar.setParent(None)
        bar.resize(476, 40)
        bar.show()
        QApplication.processEvents()
        bar.layout().activate()
        assert window.assembly_slider.width() >= 96
        assert label.width() < label.fontMetrics().horizontalAdvance(line), "nothing to elide"
        assert QLabel.text(label).endswith("…")
        bar.resize(1600, 40)
        QApplication.processEvents()
        bar.layout().activate()
        assert QLabel.text(label) == line, "the whole line where there is room"
        bar.close()
    finally:
        _close(window)


def test_a_narrow_step_bar_keeps_the_name_of_the_step_to_do() -> None:
    """At 1280 x 720 every step's name did not fit and the bar went straight to six dots.
    Before it gives up every name it keeps the one step it is there to name."""
    from perfboard_studio.ui.workflow import step_title

    window = _window_on(_blank_document())
    try:
        bar = window.workflow_bar
        doing = next(s for s in bar.steps if s.status in ("current", "problem"))
        widths = {}
        for mode in ("full", "compact", "current", "tiny"):
            bar._write_labels(mode)
            widths[mode] = bar.layout().sizeHint().width()
        assert widths["full"] >= widths["compact"] > widths["current"] > widths["tiny"]
        bar.resize(widths["current"] + 2, bar.height())
        bar._fit()
        assert bar._mode == "current"
        assert bar.buttons[doing.key].text() == step_title(doing.key)
        assert all(bar.buttons[s.key].text() == "" for s in bar.steps if s is not doing)
        bar.resize(widths["tiny"] + 2, bar.height())
        bar._fit()
        assert bar._mode == "tiny"
    finally:
        _close(window)


def test_a_parts_editor_fits_a_720_px_window_with_its_last_row_showing() -> None:
    """At 1280 x 720 a resistor's editor was 19 px taller than Properties, because the pin
    names asked for Qt's 192 px: the Auto-wire and Delete row sat half under the status
    bar. The table asks for its rows, up to three, and the editor fits."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        window.resize(1280, 720)
        window.show()
        part = next(c for c in window.bus.document.components if c.ref == "R1")
        window.scene.select_components([part.id])
        window._selection_from = "board"
        window._refresh_properties()
        QApplication.processEvents()
        editor = window.inspector.shown
        table = editor.pinout.table
        rows = table.rowCount()
        assert 0 < rows <= table.WANTED_ROWS
        assert table.sizeHint().height() < 192
        scroller = window.properties.scroller
        need = scroller.widget().heightForWidth(scroller.viewport().width())
        assert need <= scroller.viewport().height() or need < 0, (need, scroller.viewport().height())
    finally:
        _close(window)


@requires_offscreen_gl  # the render is stubbed, but the scanner reads on_export_guide
def test_a_boards_edge_fingers_are_a_note_beside_the_files_not_a_gap(tmp_path, monkeypatch) -> None:
    """A stock board's fingers came up as "The guide has gaps" on every export. They are a
    note: said in the written box's details. A real gap still stops the export."""
    from perfboard_studio.commands import DeleteConductorsPayload
    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui import view3d

    monkeypatch.setattr(view3d, "offscreen_gl_available", lambda: False)
    warned: list[str] = []
    monkeypatch.setattr(
        "perfboard_studio.ui.main.QMessageBox.warning",
        lambda parent, title, text, *args, **kwargs: warned.append(text),
    )
    offered: list[list[str] | None] = []
    monkeypatch.setattr(
        main_module.MainWindow, "_offer_to_open",
        lambda self, written, notes=None, **kwargs: offered.append(notes),
    )
    monkeypatch.setattr(
        main_module.MainWindow,
        "_ask_where_to_export",
        lambda self, title, suggested, file_filter: tmp_path / suggested,
    )
    window = _window_on(_example_document("ne555-astable"))
    window.current_path = tmp_path / "board.perf"
    try:
        assert window.bus.document.edge_connectors, "the example is a stock board with fingers"
        window.on_export_guide()
        assert warned == [], "a note is not a gap"
        assert offered and offered[-1] and "edge" in offered[-1][0]

        ids = tuple(c.id for c in window.bus.document.conductors)
        assert window.bus.dispatch("conductor.deleteMany", DeleteConductorsPayload(ids=ids)).ok
        assert not window.bus.document.conductors
        window.on_export_guide()
        assert warned and "could not cover" in warned[0]
    finally:
        _close(window)


def test_the_sheets_arrange_says_its_name() -> None:
    """An unlabelled icon among the zooms, Arrange was the way to tidy a hand-wired sheet
    nobody new found. It says its name beside the icon; the menu keeps its longer one."""
    from PySide6.QtCore import Qt

    window = _window_on(_load_dense())
    try:
        button = window.sheet_arrange_button
        assert button.defaultAction() is window.act_sch_auto
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        assert button.text() == "Arrange"
        assert window.act_sch_auto.text() == "Arran&ge the Sheet"
    finally:
        _close(window)


def _hand_wired_sheet(window, wires: int = 3, skip: int = 0) -> None:
    """The NE555's sheet frozen where the layout put it, as the window freezes one, and
    ``wires`` of its connections drawn pin to pin, after the first ``skip``."""
    from perfboard_studio.commands import DrawSheetWirePayload, MoveSymbolsPayload
    from perfboard_studio.model import Point2, SheetWire
    from perfboard_studio.schematic import build_schematic, pin_position

    if not window.bus.document.sheet:
        placements = window._sheet_placements({})
        assert window.bus.dispatch("symbol.move", MoveSymbolsPayload(placements=placements)).ok
    for net in [n for n in window.bus.document.nets if len(n.nodes) >= 2][skip:skip + wires]:
        a, b = net.nodes[0], net.nodes[1]
        drawing = build_schematic(window.bus.document, window.lookup)
        start = pin_position(drawing, a.component_ref, a.pin)
        end = pin_position(drawing, b.component_ref, b.pin)
        assert start is not None and end is not None
        path = (start, end) if start.y == end.y or start.x == end.x else (
            start, Point2(x=end.x, y=start.y), end
        )
        result = window.bus.dispatch("sheet.wire", DrawSheetWirePayload(wire=SheetWire(a=a, b=b, path=path)))
        assert result.ok, result.message


def test_a_tangled_hand_wired_sheet_is_offered_arrange_once(monkeypatch, tmp_path) -> None:
    """The NE555 drawn before any net existed was 1397 mm of wire and 28 crossings; Arrange
    makes it 457 mm and 4, and nobody new found it. A hand-wired sheet Arrange would make
    much shorter is offered it in one line over the sheet -- once per document, ever."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QLabel

    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    monkeypatch.setattr(main_module, "sheet_arrange_gain", lambda drawn, arranged: (1000.0, 300.0))
    document = _example_document("ne555-astable")
    window = _window_on(document)
    try:
        window.show_schematic()
        hint = window.sheet_arrange_hint
        assert hint.isHidden(), "a sheet the layout draws has nothing to arrange"
        _hand_wired_sheet(window, wires=2)
        window._refresh_schematic_panel()
        assert hint.isHidden(), "two wires are not yet a tangle"
        _hand_wired_sheet(window, wires=1, skip=2)
        window._refresh_schematic_panel()
        assert not hint.isHidden()
        assert "every connection stays" in hint.findChild(QLabel).text()
        window.sheet_arrange_hint_close.click()
        assert hint.isHidden()
        window._refresh_schematic_panel()
        assert hint.isHidden(), "closed is closed"
    finally:
        _close(window)

    window = _window_on(document)
    try:
        window.show_schematic()
        _hand_wired_sheet(window)
        window._refresh_schematic_panel()
        assert window.sheet_arrange_hint.isHidden(), "once per document, not once per window"
    finally:
        _close(window)


def test_the_hints_arrange_arranges_and_the_hint_goes(monkeypatch, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    window = _window_on(_example_document("ne555-astable"))
    try:
        window.show_schematic()
        monkeypatch.setattr(main_module, "sheet_arrange_gain", lambda drawn, arranged: (1000.0, 900.0))
        _hand_wired_sheet(window)
        window._refresh_schematic_panel()
        assert window.sheet_arrange_hint.isHidden(), "not offered where it would hardly help"

        monkeypatch.setattr(main_module, "sheet_arrange_gain", lambda drawn, arranged: (1000.0, 300.0))
        _hand_wired_sheet(window, wires=1, skip=3)
        window._refresh_schematic_panel()
        hint = window.sheet_arrange_hint
        assert not hint.isHidden()
        button = next(b for b in hint.buttons if b.defaultAction() is window.act_sch_auto)
        nets = window.bus.document.nets
        button.click()
        assert hint.isHidden()
        assert not window.bus.document.sheet and not window.bus.document.sheet_wires
        assert window.bus.document.nets == nets, "every connection stays"
    finally:
        _close(window)


def test_the_arrange_measure_is_the_wire_on_the_sheet() -> None:
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.schematic import build_schematic
    from perfboard_studio.ui.main import sheet_arrange_gain

    drawing = build_schematic(_example_document("ne555-astable"), footprint_lookup())
    drawn, arranged = sheet_arrange_gain(drawing, drawing)
    assert drawn == arranged > 0


def test_the_arrange_hint_wraps_to_the_room_beside_the_sheets_tools() -> None:
    """Beside the 3D view the sheet is a third of the window: the hint's words wrap to the
    room right of the tools down the sheet's left, rather than covering them."""
    window = _window_on(_load_dense())
    try:
        hint = window.sheet_arrange_hint
        sheet = window.schematic_view
        sheet.resize(476, 500)
        hint.place()
        assert hint.words.maximumWidth() <= 476 - hint.KEPT or hint.words.maximumWidth() == 160
        assert hint.x() >= window.sheet_tools.geometry().right() - 1 or hint.words.maximumWidth() == 160
        sheet.resize(1400, 800)
        hint.place()
        assert hint.words.maximumWidth() == hint.WIDEST
    finally:
        _close(window)


def _cabled_document():
    """The KY-040 encoder on the header its cable plugs into, as the catalog places it."""
    from perfboard_studio.catalog import catalog_part
    from perfboard_studio.mcp.session import new_board
    from perfboard_studio.model import ComponentInstance, DocumentMeta, HoleCoord, PerfDocument

    part = catalog_part("ky-040-encoder")
    assert part is not None
    component = ComponentInstance(
        id="c1", ref="J1", value=part.placed_value, footprint_id=part.footprint_id,
        pin_names=part.pin_names, anchor=HoleCoord(3, 3),
    )
    return PerfDocument(
        meta=DocumentMeta(name="cabled", created="", modified=""),
        board=new_board(cols=30, rows=12).board, components=(component,),
    )


def test_a_cabled_part_says_in_properties_that_it_plugs_in_on_its_cable() -> None:
    """The guide's step says the module is not on the board; Properties says it in the same
    words, in the window's language, and says nothing of the kind for a plain part."""
    from perfboard_studio.guide import CABLED_MODULE
    from perfboard_studio.ui.i18n import language, set_language

    for code in ("en", "tr"):
        before = language()
        set_language(code)
        try:
            window = _window_on(_cabled_document())
            try:
                component = window.bus.document.components[0]
                window.scene.select_components([component.id])
                window._selection_from = "board"
                window._refresh_properties()
                editor = window.inspector.shown
                assert not editor.cabled.isHidden()
                said = editor.cabled.text()
                assert component.value.strip() in said
                if code == "en":
                    assert said == CABLED_MODULE.format(module=component.value.strip())
                else:
                    assert "kablo" in said.lower() and "is not on this board" not in said
            finally:
                _close(window)
        finally:
            set_language(before)

    window = _window_on(_example_document("ne555-astable"))
    try:
        part = next(c for c in window.bus.document.components if c.ref == "R1")
        window.scene.select_components([part.id])
        window._selection_from = "board"
        window._refresh_properties()
        assert window.inspector.shown.cabled.isHidden()
    finally:
        _close(window)


def test_a_cabled_step_on_the_bench_gives_its_leads_once() -> None:
    """Its notes give each lead by name and hole; the numbered Holes row said the same holes
    again by pin number, which the module does not use."""
    from perfboard_studio.ui.i18n import t

    window = _window_on(_cabled_document())
    try:
        bench = _bench(window)
        (item,) = [i for i in bench.items if i.component_id == "c1"]
        assert t("Holes") not in {what for what, _value in item.facts}
        assert any("VCC" in note or "GND" in note for note in item.notes)
    finally:
        _close(window)


def test_an_unnamed_boards_name_field_says_untitled_in_the_windows_language() -> None:
    """The document stores "untitled"; a Turkish window's header said "adsız" and its Name
    field "untitled". The field is empty with the word as its placeholder, and a name typed
    into it is the board's name."""
    from perfboard_studio.model import UNTITLED_NAME
    from perfboard_studio.ui.i18n import language, set_language

    unnamed = _blank_document()
    unnamed = dataclasses.replace(unnamed, meta=dataclasses.replace(unnamed.meta, name=UNTITLED_NAME))
    before = language()
    set_language("tr")
    try:
        window = _window_on(unnamed)
        # With nothing selected Properties says the step; the board's editor is built
        # when it is opened, in the window's language.
        window.inspector.open_board_settings()
    finally:
        set_language(before)
    try:
        window.scene.clearSelection()
        window._refresh_properties()
        field = window.inspector.board_editor.name
        assert field.text() == "" and field.placeholderText() == "adsız"
        field.setText("Zamanlayıcı")
        field.setModified(True)
        field.editingFinished.emit()
        assert window.bus.document.meta.name == "Zamanlayıcı"
        assert field.text() == "Zamanlayıcı"
    finally:
        _close(window)


def test_the_inspector_builds_an_editor_the_first_time_it_is_shown() -> None:
    """Built together, the eleven editors were 120 ms of every start for editors most
    sessions never open. A window starts with the board's and the placing value's only."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        built = set(window.inspector._built)
        assert built <= {"step", "placing"}, built
        part = next(c for c in window.bus.document.components if c.ref == "R1")
        window.scene.select_components([part.id])
        window._selection_from = "board"
        window._refresh_properties()
        assert "part" in window.inspector._built
        assert window.inspector.shown is window.inspector.part_editor
        assert window.inspector.focus_field("ref")
    finally:
        _close(window)


def test_a_real_start_fills_properties_once_the_window_is_up() -> None:
    """At a real start Properties is filled by a zero timer after the window is shown: it
    was 50 to 80 ms of the first frame. Anything that asks first fills it then."""
    from perfboard_studio.ui.main import MainWindow

    window = MainWindow(_example_document("ne555-astable"), defer_properties=True)
    try:
        assert not window._properties_filled
        assert window.properties.content is not window.inspector
        QApplication.processEvents()
        assert window._properties_filled and window.properties.content is window.inspector
        assert window.inspector.shown is window.inspector.step_card
    finally:
        _close(window)

    window = MainWindow(_example_document("ne555-astable"), defer_properties=True)
    try:
        window.scene.clearSelection()
        window._refresh_properties()
        assert window.properties.content is window.inspector, "asked first, filled then"
    finally:
        _close(window)


def test_a_library_search_that_finds_nothing_says_so_and_names_custom_part() -> None:
    """The tree went blank and said nothing. A search that finds nothing says so under the
    box, and names Custom Part… -- the answer to "my part is not here" nobody new knew."""
    window = _window_on(_blank_document())
    try:
        note = window.library_note
        assert note.isHidden()
        window.library_filter.setText("zzqx-no-such-part")
        assert window.library_tree.topLevelItemCount() == 0
        assert not note.isHidden()
        assert note.text() == (
            "No part matches “zzqx-no-such-part”. Try a shorter word, or describe the part "
            "with Custom Part…"
        )
        window.library_filter.setText("resistor")
        assert window.library_tree.topLevelItemCount() > 0 and note.isHidden()
        window.library_filter.clear()
        assert note.isHidden()
    finally:
        _close(window)


def test_who_upgraded_is_read_off_the_settings(tmp_path) -> None:
    """0.22 never wrote the version that ran; what it did write says it was used."""
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import whatsnew
    from perfboard_studio.ui.main import GEOMETRY_KEY

    def store(name: str) -> QSettings:
        return QSettings(str(tmp_path / f"{name}.ini"), QSettings.Format.IniFormat)

    used = (GEOMETRY_KEY,)
    assert not whatsnew.upgraded_from_before(store("fresh"), used), "a first start"
    old = store("old")
    old.setValue(GEOMETRY_KEY, b"x")
    assert whatsnew.upgraded_from_before(old, used), "0.22 left its geometry and no version"
    for version, upgraded in (("0.22.0", True), ("0.21.3", True), ("0.23.0.dev0", False),
                              ("0.23.0", False), ("0.24.1", False), ("nonsense", False)):
        said = store(version)
        said.setValue(whatsnew.LAST_VERSION_KEY, version)
        assert whatsnew.upgraded_from_before(said, used) is upgraded, version


def test_what_moved_is_shown_once_to_an_upgrader_and_never_to_somebody_new(monkeypatch, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import main as main_module
    from perfboard_studio.ui import whatsnew

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)

    window = _window_on(_blank_document())  # an empty store: somebody new
    try:
        window.consider_moved_card()
        assert window.moved_card is None
    finally:
        _close(window)

    fresh = QSettings(str(tmp_path / "old.ini"), QSettings.Format.IniFormat)
    fresh.setValue(main_module.GEOMETRY_KEY, b"0.22 was here")
    monkeypatch.setattr(main_module, "app_settings", lambda: fresh)
    window = _window_on(_blank_document())
    try:
        window.consider_moved_card()
        card = window.moved_card
        assert card is not None and not card.isHidden()
        assert "Board Setup… → Board ▸ Design the Board…" in card.rows["design-board"].text()
        card.done.click()
        assert card.isHidden()
    finally:
        _close(window)
    assert fresh.value(whatsnew.LAST_VERSION_KEY), "written down as the window closed"

    window = _window_on(_blank_document())
    try:
        window.consider_moved_card()
        assert window.moved_card is None, "never twice"
        window.on_whats_moved()  # Help brings it back
        assert window.moved_card is not None and not window.moved_card.isHidden()
    finally:
        _close(window)


def test_a_line_of_what_moved_shows_the_place(monkeypatch) -> None:
    window = _window_on(_blank_document())
    try:
        window.on_whats_moved()
        card = window.moved_card
        card.rows["properties"].linkActivated.emit("properties")
        assert window._pointer is not None and not window._pointer.isHidden()
        assert window.dock_properties.isVisibleTo(window) or not window.dock_properties.isHidden()
        opened: list[str] = []
        monkeypatch.setattr(window.command_palette, "open", lambda: opened.append("search"))
        monkeypatch.setattr(type(window), "on_design_board", lambda self: opened.append("design") or False)
        card.rows["search"].linkActivated.emit("search")
        card.rows["design-board"].linkActivated.emit("design-board")
        assert opened == ["search", "design"]
    finally:
        _close(window)


def test_what_moved_waits_for_home(monkeypatch, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "old.ini"), QSettings.Format.IniFormat)
    store.setValue(main_module.GEOMETRY_KEY, b"0.22 was here")
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    window = _window_on(_blank_document())
    try:
        window.show_home(window._make_home())
        window.consider_moved_card()
        assert window.moved_card is None, "not over Home"
        window.leave_home()
        assert window.moved_card is not None and not window.moved_card.isHidden()
    finally:
        _close(window)


def test_a_family_the_library_leaves_out_says_why_and_offers_what_fits() -> None:
    """JST PH is 2.0 mm a pin and goes into no 0.1 in board: somebody typing it is told so
    under the filter, and the XH connectors that do fit are offered at the top."""
    from perfboard_studio.catalog import not_offered
    from perfboard_studio.ui.main import ROLE_CATALOG_ID

    window = _window_on(_blank_document())
    try:
        refused = not_offered("JST PH")
        assert refused is not None
        window.library_filter.setText("JST PH")
        note = window.library_note
        assert not note.isHidden() and note.text() == refused.reason
        top = window.library_tree.topLevelItem(0)
        assert top.text(0) == "Offered instead"
        offered = [top.child(i).data(0, ROLE_CATALOG_ID) for i in range(top.childCount())]
        assert offered == list(refused.instead)
        assert top.isExpanded()

        window.library_filter.setText("photo")  # "ph" alone is not the family
        assert window.library_tree.topLevelItem(0) is None or (
            window.library_tree.topLevelItem(0).text(0) != "Offered instead"
        )
        assert "JST" not in note.text()
    finally:
        _close(window)


def test_the_reason_a_family_is_left_out_is_said_in_turkish() -> None:
    from perfboard_studio.catalog import not_offered
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        window = _window_on(_blank_document())
    finally:
        set_language(before)
    try:
        set_language("tr")
        window.library_filter.setText("JST PH")
        refused = not_offered("JST PH")
        assert refused is not None
        assert window.library_note.text() not in ("", refused.reason)
        assert window.library_tree.topLevelItem(0).text(0) == "Bunun yerine önerilenler"
    finally:
        set_language(before)
        _close(window)


def test_the_board_size_in_properties_wraps_whole() -> None:
    """The narrow Properties panel broke the board line as "Pad per hole, 28 ×" over
    "6 holes" -- in the README's first shot. The size is one thing to read, so only the
    break after the board's kind is left to wrap at, in either language."""
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    for lang, word in (("en", "holes"), ("tr", "delik")):
        set_language(lang)
        try:
            window = _window_on(_load_dense())
            try:
                window.scene.clearSelection()
                window._refresh_properties()
                # With nothing selected Properties says the step; the board is one click on.
                window.inspector.open_board_settings()
                text = window.inspector.board_editor.summary.text()
                size = text.rsplit(",", 1)[-1].lstrip(" ")
                assert size.endswith(word) and "\u00a0×\u00a0" in size, (lang, text)
                assert " " not in size, (lang, text)
            finally:
                _close(window)
        finally:
            set_language(before)


def test_a_bench_steps_rows_leave_with_it() -> None:
    """The previous step's facts stayed painted under the next step's until the event loop
    came round to deleting them -- Holes and Height over a cable's wires, in ship's
    walkthrough. They are out of sight the moment the next step is shown, and so are its
    checks."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        bench = _bench(window)
        bench.show_item(0)
        facts = [bench.facts.itemAt(i).widget() for i in range(bench.facts.count())]
        checks = [bench.checks.itemAt(i).widget() for i in range(bench.checks.count())]
        old = [widget for widget in (*facts, *checks) if widget is not None]
        assert old
        bench.show_item(1)
        assert all(widget.isHidden() for widget in old)
    finally:
        _close(window)


def test_a_fitted_board_stays_fitted_until_somebody_zooms_or_pans() -> None:
    """A fit was good for the size it was made at: a panel dragged wider or the docks laid
    out again left the board where it was, and it slid under the tool rail (ship's
    multiboard run). A resize fits it again -- until the person zooms or pans, and then it
    stays where they put it."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QAbstractSlider

    window = _window_on(_load_dense())
    try:
        window.resize(1440, 900)
        window.show()
        window.show_board()
        QApplication.processEvents()
        view = window.view

        def settle() -> None:
            for _ in range(5):
                QApplication.processEvents()

        def clear_of_the_bars() -> bool:
            board = view.mapFromScene(view.sceneRect()).boundingRect()
            for bar in view.overlays:
                corner = view.viewport().mapFromGlobal(bar.mapToGlobal(QPoint(0, 0)))
                if QRect(corner, bar.size()).intersects(board):
                    return False
            return True

        def fits_its_room() -> bool:
            """What a fit made just now at this size would be -- not the first fit's scale:
            the docks do not hand back the width they took when the window narrowed."""
            kept = view.current_scale()
            view.fit_board()
            return view.current_scale() == pytest.approx(kept) and clear_of_the_bars()

        view.fit_board()
        settle()
        for width, height in ((1100, 900), (1100, 700)):
            before = view.viewport().size()
            window.resize(width, height)
            settle()
            assert view.viewport().size() != before, (width, height)
            assert fits_its_room(), (width, height)

        view.zoom_by(1.15)
        zoomed = view.current_scale()
        window.resize(1100, 900)
        settle()
        assert view.current_scale() == pytest.approx(zoomed), "a zoom of theirs is kept"

        for navigate in (
            lambda: view._pan_by(30, 0),
            lambda: view.horizontalScrollBar().triggerAction(
                QAbstractSlider.SliderAction.SliderSingleStepAdd
            ),
            lambda: window.go_to_component(window.bus.document.components[0].id),
        ):
            view.fit_board()
            assert view._fitted
            navigate()
            assert not view._fitted
    finally:
        _close(window)


def test_a_start_builds_neither_the_guide_nor_the_help_and_imports_no_designer() -> None:
    """What a start leaves for later (docs/ARCHITECTURE.md, "A start is paid for in
    breadth"): the Build Guide's panel, built when it first comes in front; the help texts,
    hung when help is first asked for; the board designer, imported when it first opens.
    In a process of its own, because every other test here has imported everything."""
    import subprocess
    import sys

    probe = (
        "import os, sys, tempfile\n"
        "os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
        "from pathlib import Path\n"
        "from PySide6.QtCore import QSettings\n"
        "from PySide6.QtWidgets import QApplication\n"
        "import perfboard_studio.ui.main as m\n"
        "from perfboard_studio.ui import autosave\n"
        "tmp = Path(tempfile.mkdtemp())\n"
        "store = QSettings(str(tmp / 's.ini'), QSettings.Format.IniFormat)\n"
        "m.app_settings = lambda: store\n"
        "autosave.default_directory = lambda: tmp\n"
        "app = QApplication([])\n"
        "doc = m.create_starter_document(m.DocumentMeta(name='x', created='', modified=''))\n"
        "w = m.MainWindow(doc, None, defer_properties=True)\n"
        "w.offer_home()\n"
        "print(w.guide_built, 'perfboard_studio.ui.designer' in sys.modules,\n"
        "      'perfboard_studio.ui.helpcards' in sys.modules, flush=True)\n"
        "os._exit(0)\n"
    )
    root = pathlib.Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=120
    )
    assert out.stdout.split() == ["False", "False", "False"], out.stdout + out.stderr


def test_the_guide_is_built_when_it_comes_in_front_and_works_as_it_did() -> None:
    """The guide's panel is made the first time it is wanted, and is then the panel it
    always was: in the dock, its corner on the list, filled for the board in front."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        assert not window.guide_built
        assert window.act_next_step is not None and window.act_clear_progress is not None
        window._raise_view(window.dock_guide)
        assert window.guide_built
        assert window.dock_guide.widget() is window.guide_pages
        assert window.guide_tools.parent() is window.guide_overview
        assert window.guide_tree.topLevelItemCount() > 0
        assert window.bench.items
    finally:
        _close(window)


def _cabled_system():
    """Main's JA and Remote's JB, SIG on pin 1 and GND on pin 2 of both, joined by W1:
    ``tests/test_harness.py``'s system."""
    from perfboard_studio import system
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.model import (
        Cable,
        CableEnd,
        CableWire,
        ComponentInstance,
        DocumentMeta,
        ExtraBoard,
        HoleCoord,
        Net,
        NetNode,
        PerfDocument,
    )

    ja = ComponentInstance(id="cmp-1", ref="JA", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    jb = ComponentInstance(id="cmp-2", ref="JB", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    return PerfDocument(
        meta=DocumentMeta(name="Bench", created="", modified=""),
        board_name="Main",
        board=DEFAULT_BOARD,
        components=(ja,),
        nets=(
            Net(id="n1", name="SIG", nodes=(NetNode("JA", "1"), NetNode("JB", "1"))),
            Net(id="n2", name="GND", nodes=(NetNode("JA", "2"), NetNode("JB", "2")), net_class="ground"),
        ),
        boards=(ExtraBoard(id="b2", name="Remote", board=DEFAULT_BOARD, components=(jb,)),),
        cables=(
            Cable(
                id="cable-1",
                ref="W1",
                a=CableEnd(system.FIRST_BOARD, "cmp-1"),
                b=CableEnd("b2", "cmp-2"),
                wires=(CableWire("1", "1"), CableWire("2", "2")),
                length_mm=150,
            ),
        ),
    )


def test_each_cable_is_a_bench_step_after_closing_up() -> None:
    """A cable is fitted once every board is built and checked before power: on the bench
    it is one more step, under "9. Harness", pictured on the finished board at this
    board's connector, its wires by colour end to end -- and its checks keyed under 9, not
    8, which is Closing up's."""
    from perfboard_studio.ui.benchguide import HARNESS_PHASE, HarnessPhase, check_key

    window = _window_on(_cabled_system())
    try:
        bench = _bench(window)
        cable = bench.items[-1]
        assert cable.key == "cable:cable-1" and cable.built
        assert cable.title == "W1 — Main JA → Remote JB"
        assert isinstance(cable.phase, HarnessPhase)
        assert (cable.phase.number, cable.phase.title) == (HARNESS_PHASE, "Harness")
        assert bench._phases[-1] is cable.phase
        assert cable.component_id == "cmp-1" and len(cable.holes) == 2
        ends = [value for _what, value in cable.facts]
        assert "Main JA pin 1 → Remote JB pin 1" in ends
        assert "Main JA pin 2 → Remote JB pin 2" in ends
        assert cable.notes and cable.phase.checkpoints
        keys = {check_key(cable.phase, check) for check in cable.phase.checkpoints}
        assert all(key.startswith("check:9:") for key in keys)
        closing = {check_key(p, c) for p in bench._phases[:-1] for c in p.checkpoints}
        assert not keys & closing

        bench.show_item(len(bench.items) - 1)
        assert bench.title.text() == cable.title
        assert not bench.picture.pixmap().isNull()
        assert window.scene.selected_component_ids() == ("cmp-1",)
        bench.next.click()  # the last step: the ending lists the harness's checks under 9
        headings = [
            bench.ending_checks.itemAt(i).widget().text()
            for i in range(bench.ending_checks.count())
            if bench.ending_checks.itemAt(i).widget() is not None
        ]
        assert "9. Harness" in headings
    finally:
        _close(window)


def test_the_harness_step_is_said_in_the_guides_language() -> None:
    from perfboard_studio.ui.i18n import language, set_language

    before = language()
    set_language("tr")
    try:
        window = _window_on(_cabled_system())
        try:
            from perfboard_studio.phrasebook import phrasebook

            cable = _bench(window).items[-1]
            assert cable.phase.title == "Kablo demeti"
            say = phrasebook("tr")
            (wires,) = [c.wires for c in window.current_guide().harness]
            colours = {say(wire.colour) for wire in wires}
            assert colours and colours <= {what for what, _value in cable.facts}
            assert ("Kesilecek tel", "150 mm · AWG 24") in cable.facts or any(
                what == "Kesilecek tel" for what, _value in cable.facts
            )
        finally:
            _close(window)
    finally:
        set_language(before)


def test_home_is_handed_its_examples_once_the_window_is_up() -> None:
    """Reading every example for its line was most of what Home cost a blank start: Home
    goes up with its doors and the tour's card, and the examples come on the next turn of
    the event loop -- the same examples, in the same order."""
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.main import example_boards

    window = _blank_window()
    try:
        window.offer_home()
        home = window._home_page
        assert home is not None and window.home_is_showing()
        assert home.cards == []
        assert not home.walkthrough_card.isHidden()
        _settle_events(QApplication, rounds=3)
        assert [card.example.path for card in home.cards] == [p for p, _ in example_boards()]
    finally:
        _close(window)


def _commit(field, text: str) -> None:
    """Type ``text`` into a Properties line and leave it, as a person does."""
    field.setText(text)
    field.setModified(True)
    field.editingFinished.emit()


def test_system_in_front_shows_the_system_and_a_click_shows_a_board_or_a_cable() -> None:
    """With System in front, Properties is the system's -- its name, what it holds, Add
    Board and Add Cable -- and a click on System picks a board or a cable for it, each with
    its own editor; a click on the bare bench, or a pick the document no longer has, is the
    system again."""
    from perfboard_studio.ui.selection import Selection
    from tests.test_system_readers import _system

    window = _window_on(_system())
    try:
        inspector = window.inspector
        window.board_strip.tabs.setCurrentIndex(0)
        assert window._system_in_front()
        assert window._current_selection() == Selection("system")
        assert inspector.shown is inspector.system_editor
        assert inspector.system_editor.name.text() == "Main"
        assert inspector.system_editor.contents.text() == "2 boards,  1 cable"

        window.system_view.board_clicked.emit("b2")
        board = inspector.system_board_editor
        assert inspector.shown is board and board.name.text() == "Remote"
        assert window.system_view.selected == ("board", "b2")
        # Rename Board names the board picked on System, as it names the board in front.
        window.on_rename_board()
        assert inspector.shown is board and board.name.selectedText() == "Remote"
        _commit(board.name, "Far")
        system = window.bus.system_document
        assert system.boards[0].name == "Far" and system.meta.name == "Main"
        assert window.board_strip.tabs.tabText(2).startswith("Far  ·  ")
        # A cable reaches it: removing the board is refused, and said.
        board.remove.click()
        assert board.problem.isVisibleTo(board) and "W1" in board.problem.text()
        assert len(window.bus.system_document.boards) == 1

        window.system_view.cable_clicked.emit("cable-1")
        cable = inspector.cable_editor
        assert inspector.shown is cable and cable.ref.text() == "W1"
        assert "1 → 1" in cable.wires.text() and "GND" in cable.wires.text()
        cable.length.setValue(300.0)
        cable.length.editingFinished.emit()
        assert window.bus.system_document.cables[0].length_mm == 300.0
        _commit(cable.ref, "W7")
        assert window.bus.system_document.cables[0].ref == "W7"
        cable.remove.click()
        assert window.bus.system_document.cables == ()
        # The cable is gone, so the pick is: Properties is the system's again.
        assert inspector.shown is inspector.system_editor
        assert window.system_view.selected is None

        window.system_view.board_clicked.emit("b2")
        inspector.system_board_editor.remove.click()
        assert window.bus.system_document.boards == ()
        assert {"JB", "R2"} <= {p.ref for p in window.bus.system_document.parts}
        # One board left: no strip, no System, and Properties is that board's step.
        assert not window._system_in_front() and window.board_strip.isHidden()
        assert inspector.shown is inspector.step_card

        window.bus.undo()
        window.on_bus_changed(window.bus.system_document, None)
        window.board_strip.tabs.setCurrentIndex(0)
        window.system_view.board_clicked.emit("main")
        assert not inspector.system_board_editor.remove.isVisibleTo(inspector.system_board_editor)
        window.system_view.cleared.emit()
        assert inspector.shown is inspector.system_editor
    finally:
        _close(window)


def test_a_click_on_system_picks_what_is_under_it() -> None:
    """A board under the pointer is that board; a wire under it is its cable, even over a
    board -- and the area under a cable's sag is not the cable, though an open curve's own
    shape says it is."""
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest

    from tests.test_system_readers import _system

    window = _window_on(_system())
    try:
        window.resize(1280, 800)
        window.show()
        window.board_strip.tabs.setCurrentIndex(0)
        _settle_events(QApplication, rounds=3)
        view = window.system_view
        frame = view._frames["b2"]
        inside = view.mapFromScene(frame.sceneBoundingRect().center())
        assert view.picked_at(QPointF(inside)) == ("board", "b2")
        wire, _pen = view._outlines["cable-1"][0]
        on_it = view.mapFromScene(wire.path().pointAtPercent(0.5))
        assert view.picked_at(QPointF(on_it)) == ("cable", "cable-1")
        # Inside the curve's sag, between its ends and well clear of the wire: what the
        # path item's own shape claims, and what a click must not take for the cable.
        a, low = wire.path().pointAtPercent(0.0), wire.path().pointAtPercent(0.5)
        sagged = QPointF(low.x(), (a.y() + low.y()) / 2)
        assert wire.shape().contains(sagged)
        assert view.picked_at(QPointF(view.mapFromScene(sagged))) != ("cable", "cable-1")

        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=on_it)
        assert window.inspector.shown is window.inspector.cable_editor
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=inside)
        assert window.inspector.shown is window.inspector.system_board_editor
    finally:
        _close(window)


def test_the_header_says_which_board_is_in_front_or_system() -> None:
    """The document's name is the header's title, and beside it, on a document of several
    boards, which one is in front -- or System; on one board, nothing beside it."""
    import dataclasses

    from tests.test_system_readers import _system

    one = _window_on(dataclasses.replace(_system(wires=None), boards=()))
    try:
        assert one.header.place.isHidden()
    finally:
        _close(one)

    window = _window_on(_system())
    try:
        header = window.header
        assert header.title.text() == "Main"
        assert not header.place.isHidden() and header.place.text() == "›  Main"
        window.board_strip.tabs.setCurrentIndex(2)
        assert header.place.text() == "›  Remote"
        window.board_strip.tabs.setCurrentIndex(0)
        assert header.place.text() == "›  System" and header.title.text() == "Main"
    finally:
        _close(window)


def test_a_boards_name_in_properties_is_its_own_among_several() -> None:
    """On a board of several, Properties' Name is that board's (``board.rename``), shown
    empty with its place when nobody named it -- and the document keeps its own name."""
    from tests.test_system_readers import _system

    window = _window_on(_system())
    try:
        window.board_strip.tabs.setCurrentIndex(2)
        window.scene.clearSelection()
        window._refresh_properties()
        window.inspector.step_card.board_settings.click()
        editor = window.inspector.board_editor
        assert window.inspector.shown is editor and editor.name.text() == "Remote"
        _commit(editor.name, "Far")
        assert window.bus.system_document.boards[0].name == "Far"
        assert window.bus.system_document.meta.name == "Main"
        _commit(editor.name, "")
        assert window.bus.system_document.boards[0].name == ""
        assert editor.name.text() == "" and editor.name.placeholderText() == "Board 2"
        assert window.header.place.text() == "›  Board 2"
    finally:
        _close(window)


def test_an_empty_extra_board_says_how_parts_reach_it() -> None:
    """A board added to the system says what to do with it every time it is empty -- not
    the first start's words about drawing the circuit, which this person has done."""
    from tests.test_system_readers import _system

    window = _window_on(_system())
    try:
        window._has_placed_a_part = True
        window.on_add_board()
        hint = window.view.empty_hint
        assert not hint.isHidden()
        assert "Board 3 has nothing on it yet" in hint.text()
        assert "Move to Board" in hint.text() and "Add Cable" in hint.text()
    finally:
        _close(window)



def test_an_example_of_several_boards_is_counted_drawn_and_opened_whole() -> None:
    """The two-board example's card counts every part on both boards, its picture is both
    boards side by side, and it opens on System -- counted from its first board it said 14
    parts of its 25, and its picture showed one board of two."""
    from perfboard_studio.ui.home import PICTURE, Home
    from perfboard_studio.ui.main import example_boards

    found = {path.stem: (path, line) for path, line in example_boards()}
    path, line = found["relay-and-supply"]
    assert line.startswith("25 parts on 2 boards"), line

    window = _blank_window()
    try:
        home = Home([], window.lookup)
        one = home._picture(found["ne555-astable"][0])
        both = home._picture(path)
        assert one is not None and both is not None
        assert both.width() <= PICTURE.width() and both.height() <= PICTURE.height()
        # Two boards of one size in a row: wider than tall, unlike one 6 x 8 cm board.
        assert both.width() > 1.5 * both.height()
        home.deleteLater()

        window.on_open_example(path)
        assert window._system_in_front()
        assert window.header.place.text() == "›  System"
        assert window.inspector.shown is window.inspector.system_editor
    finally:
        _close(window)


# -- a part on the solder side ------------------------------------------------------------


def _ne555():
    example = pathlib.Path(__file__).resolve().parent.parent / "examples" / "ne555-astable.perf"
    return persist.deserialize_document(example.read_text(encoding="utf-8")).document


def test_shift_m_turns_a_part_over_onto_the_solder_side_and_back() -> None:
    window = _window_on(_ne555())
    try:
        assert window.act_side.shortcut().toString() == "Shift+M"
        part = next(c for c in window.bus.document.components if c.ref == "U1")
        window.scene.select_components([part.id])
        window._refresh_selection_state()
        assert window.act_side.isEnabled()
        assert window.act_side.text() == "Move to &Solder Side"
        window.act_side.trigger()
        moved = next(c for c in window.bus.document.components if c.id == part.id)
        assert (moved.side, moved.mirrored) == ("bottom", True)
        # A DIP has no turn that keeps its pins on their nets, and the label says so.
        assert window.bus.history()[-1] == (
            "Move U1 to Solder Side: its rows of pins swapped sides, so its wiring needs redoing"
        )
        # ...and so does the status line, where somebody is looking.
        assert window.statusBar().currentMessage() == window.bus.history()[-1]
        window.scene.select_components([part.id])
        window._refresh_selection_state()
        assert window.act_side.text() == "Move to Component &Side"
        # Mirror on a part turned over says why, and changes nothing.
        steps = len(window.bus.history())
        window.on_mirror_selection()
        assert len(window.bus.history()) == steps
        assert "Shift+M" in window.statusBar().currentMessage()
        window.act_side.trigger()
        back = next(c for c in window.bus.document.components if c.id == part.id)
        assert (back.side, back.mirrored) == ("top", False)
    finally:
        _close(window)


def test_a_group_goes_over_in_one_step() -> None:
    window = _window_on(_ne555())
    try:
        ids = [c.id for c in window.bus.document.components[:3]]
        window.scene.select_components(ids)
        window._refresh_selection_state()
        steps = len(window.bus.history())
        window.on_side_selection()
        assert len(window.bus.history()) == steps + 1
        assert all(
            c.side == "bottom" for c in window.bus.document.components if c.id in ids
        )
        window.bus.undo()
        assert all(c.side == "top" for c in window.bus.document.components)
    finally:
        _close(window)


def test_properties_puts_a_part_on_either_face() -> None:
    window = _window_on(_ne555())
    try:
        part = next(c for c in window.bus.document.components if c.ref == "R1")
        window.scene.select_components([part.id])
        window._refresh_selection_state()
        editor = window.inspector.part_editor
        assert editor.face_buttons["top"].isChecked()
        assert editor.mirrored.isEnabled()
        editor.face_buttons["bottom"].click()
        moved = next(c for c in window.bus.document.components if c.id == part.id)
        assert moved.side == "bottom"
        assert editor.face_buttons["bottom"].isChecked()
        assert not editor.mirrored.isEnabled(), "turned over is mirrored; nothing to untick"
    finally:
        _close(window)


def test_a_part_placed_on_the_turned_over_board_goes_on_the_solder_side() -> None:
    from perfboard_studio.breadboard import breadboard

    bus = _blank_bus()
    scene = BoardScene(bus.document, footprint_lookup(), side="bottom", bus=bus)
    scene.arm_placement("r-axial-3")
    result = scene.place_armed(HoleCoord(3, 3))
    assert result is not None and result.ok, result
    placed = bus.document.components[0]
    assert (placed.side, placed.mirrored) == ("bottom", True)

    # A solderless breadboard has no underside: the part goes on top, as before.
    bread = _new_bus(dataclasses.replace(bus.document, board=breadboard("830"), components=()))
    scene = BoardScene(bread.document, footprint_lookup(), side="bottom", bus=bread)
    assert scene.placing_face() == "top"


def test_a_part_under_the_board_is_a_shadow_from_above_and_the_part_from_below() -> None:
    from perfboard_studio.commands import SetComponentSidePayload

    bus = _new_bus(_ne555())
    part = next(c for c in bus.document.components if c.ref == "U1")
    assert bus.dispatch("component.setSide", SetComponentSidePayload(id=part.id, side="bottom")).ok
    top = BoardScene(bus.document, footprint_lookup(), side="top")
    bottom = BoardScene(bus.document, footprint_lookup(), side="bottom")
    assert not top.component_items[part.id].faces_the_viewer()
    assert bottom.component_items[part.id].faces_the_viewer()
    others = [i for cid, i in bottom.component_items.items() if cid != part.id]
    assert others and not any(i.faces_the_viewer() for i in others)
    # Its value reads the right way from below: the two reflections cancel.
    under = bottom.component_items[part.id].comp
    assert view2d._ink_frame(under, from_below=True)[1] is False
    assert view2d._ink_frame(under, from_below=False)[1] is True


def test_the_guide_says_a_part_goes_on_the_solder_side() -> None:
    from perfboard_studio.commands import SetComponentSidePayload

    window = _window_on(_ne555())
    try:
        part = next(c for c in window.bus.document.components if c.ref == "U1")
        window.bus.dispatch("component.setSide", SetComponentSidePayload(id=part.id, side="bottom"))
        guide = window.current_guide()
        lines = [
            main_module_step_line(step, guide.language)
            for phase in guide.phases for step in phase.steps
            if getattr(step, "component_id", None) == part.id
        ]
        assert lines and lines[0].endswith("· solder side")
    finally:
        _close(window)


def main_module_step_line(step, language):
    from perfboard_studio.ui.main import _step_line

    return _step_line(step, language)


def test_a_board_that_is_no_stock_board_is_said_in_holes() -> None:
    """A board not on a preset was "60 × 40" with no unit in the step bar, the status bar,
    the board question and the board strip -- beside "5 x 7 cm" it read as millimetres."""
    from perfboard_studio.ui.i18n import hole_grid, language, set_language
    from perfboard_studio.ui.main import _board_size_name

    document = _blank_document()
    document = dataclasses.replace(
        document, board=dataclasses.replace(document.board, cols=60, rows=40)
    )
    assert _board_size_name(document.board) == "60 × 40 holes"
    window = _window_on(document)
    try:
        assert window.workflow_facts().board_label == "60 × 40 holes"
    finally:
        _close(window)
    before = language()
    set_language("tr")
    try:
        assert hole_grid(60, 40) == "60 × 40 delik"
    finally:
        set_language(before)


def test_a_long_name_shows_its_start() -> None:
    """System's Name field showed "lay Driver and Its Supply": setText leaves the cursor at
    the end, so a name longer than the field scrolled its start away."""
    from perfboard_studio.ui.main import example_boards

    path = next(path for path, _line in example_boards() if path.stem == "relay-and-supply")
    window = _blank_window()
    try:
        window.on_open_example(path)
        assert window._system_in_front()
        name = window.inspector.system_editor.name
        assert name.text() == "Relay Driver and Its Supply"
        assert name.cursorPosition() == 0
    finally:
        _close(window)


def test_a_group_turned_over_says_how_many_need_rewiring() -> None:
    """A resistor turned over keeps its holes; a DIP swaps its rows. Over a group the status
    line counts the ones whose wiring needs redoing, and over parts that all keep their
    holes it says only that they moved."""
    window = _window_on(_ne555())
    try:
        parts = {c.ref: c for c in window.bus.document.components}
        resistors = [ref for ref in parts if ref.startswith("R")][:2]
        window.scene.select_components([parts[ref].id for ref in resistors])
        window._refresh_selection_state()
        window.on_side_selection()
        assert window.statusBar().currentMessage().startswith("Moved 2 parts to the solder side")
        window.bus.undo()

        window.scene.select_components([parts[ref].id for ref in [*resistors, "U1"]])
        window._refresh_selection_state()
        window.on_side_selection()
        message = window.statusBar().currentMessage()
        assert message.startswith("1 of 3 parts changed holes: its wiring needs redoing"), message
        assert "Moved 3 parts to the solder side" in message
    finally:
        _close(window)


def _relay_and_supply():
    from perfboard_studio.ui.main import example_boards

    return next(path for path, _line in example_boards() if path.stem == "relay-and-supply")


def test_the_library_search_is_cleared_when_another_document_opens() -> None:
    window = _blank_window()
    try:
        window.library_filter.setText("9V")
        window.on_open_example(_relay_and_supply())
        assert window.library_filter.text() == ""
    finally:
        _close(window)


def test_an_empty_board_of_a_system_is_said_and_next_shows_it() -> None:
    from perfboard_studio.system import board_ids

    window = _blank_window()
    try:
        window.on_open_example(_relay_and_supply())
        assert window.workflow_facts().empty_board == ""
        window.on_add_board()
        third = window.bus.board_id
        facts = window.workflow_facts()
        assert facts.empty_board == "Board 3"
        window._on_board_picked(board_ids(window.bus.system_document)[0])
        assert window.workflow_bar.next_key == "place"
        window.on_workflow_next("place")
        assert window.bus.board_id == third
    finally:
        _close(window)


def test_turning_a_part_over_with_the_guide_in_front_keeps_it_selected() -> None:
    """The guide rebuilt by the edit put its own step's part on the board, and Properties
    described D1 while R1 had just been turned over."""
    window = _window_on(_ne555())
    try:
        window._raise_view(window.dock_guide)
        assert window.bench.items
        part = next(c for c in window.bus.document.components if c.ref == "R1")
        window.scene.select_components([part.id])
        window._refresh_selection_state()
        window.act_side.trigger()
        assert [c.ref for c in window._selected_components()] == ["R1"]
    finally:
        _close(window)


def test_an_example_opens_with_its_names_in_the_windows_language() -> None:
    """A Turkish window opened the two-board example on boards called "Relay driver" and
    "Supply"; an English one keeps the names the file has."""
    from perfboard_studio.system import board_ids, board_title
    from perfboard_studio.ui.i18n import language, set_language

    window = _blank_window()
    try:
        window.on_open_example(_relay_and_supply())
        document = window.bus.system_document
        assert document.meta.name == "Relay Driver and Its Supply"
        assert [board_title(document, b) for b in board_ids(document)] == ["Relay driver", "Supply"]
    finally:
        _close(window)
    before = language()
    set_language("tr")
    try:
        window = _blank_window()
        try:
            window.on_open_example(_relay_and_supply())
            document = window.bus.system_document
            assert document.meta.name == "Röle Sürücüsü ve Beslemesi"
            assert [board_title(document, b) for b in board_ids(document)] == [
                "Röle sürücüsü",
                "Besleme",
            ]
            assert not window.is_modified
        finally:
            _close(window)
    finally:
        set_language(before)


# -- copper drawn by hand: what it would do, said before and after -----------------------------


def _hole(window, ref: str):
    from perfboard_studio.geometry import parse_hole

    hole = parse_hole(ref, window.bus.document.board)
    assert hole is not None, ref
    return hole


def _hover_hole(window, ref: str) -> None:
    window.scene.hover_at(hole_to_screen(_hole(window, ref), window.bus.document.board, window.scene.side))


def test_a_run_through_another_nets_pad_turns_red_and_the_banner_says_why() -> None:
    """F1 → F3 on ne555 runs through F2, LED1's GND leg. It used to be a thin grey line to
    the click and "Done" after it; the short was the Problems count going up by one."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        window.on_draw_mode("solder-trace", True)
        window.scene.draw_click(_hole(window, "F1"))
        _hover_hole(window, "F3")

        preview = window.scene._draw_preview
        assert preview is not None and preview.problem is not None
        assert preview.problem.severity == "error"
        assert format_hole(preview.problem.hole, window.bus.document.board) == "F2"
        banner = window.view.mode_banner.text()
        assert "F2" in banner and "LED_A" in banner and "GND" in banner and "short" in banner

        window.scene.draw_click(_hole(window, "F3"))
        assert window.scene.commit_drawing() is not None
        status = window.statusBar().currentMessage()
        assert "short" in status and "F2" in status and "Ctrl+Z" in status, status
        # The tool stays for the next piece, and the banner is back to how to use it.
        assert window.scene.armed_draw_kind == "solder-trace"
        assert "short" not in window.view.mode_banner.text()
    finally:
        _close(window)


def test_copper_drawn_on_from_a_wires_end_joins_that_wires_net_and_says_so() -> None:
    """G6 is the end of a GND wire, not a pin. The old rule claimed a net only between two
    pins of it, so this wire went in on no net -- skipped by Redo Wiring, and never said."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        window.on_draw_mode("bare-wire", True)
        window.scene.draw_click(_hole(window, "G6"))
        window.scene.draw_click(_hole(window, "F2"))
        result = window.scene.commit_drawing()

        assert result is not None and result.ok
        drawn = window.bus.document.conductors[-1]
        gnd = next(net.id for net in window.bus.document.nets if net.name == "GND")
        assert drawn.net_id == gnd
        assert window.statusBar().currentMessage().endswith("G6 → F2: on GND")
        assert window.scene.armed_draw_kind == "bare-wire"
    finally:
        _close(window)


def test_the_drawing_hint_goes_with_the_tool() -> None:
    window = _window_on(_example_document("ne555-astable"))
    try:
        window.on_draw_mode("solder-trace", True)
        assert window.statusBar().currentMessage().startswith("Drawing")
        window.scene.leave_mode()
        assert window.statusBar().currentMessage() == ""
    finally:
        _close(window)


def test_copper_is_deleted_without_a_question_and_the_status_offers_it_back() -> None:
    window = _window_on(_example_document("ne555-astable"))
    asked: list[str] = []
    original = type(window)._confirm
    type(window)._confirm = lambda self, title, body, verb: asked.append(title) or False
    try:
        _select_conductor(window, "cond-13")
        window.on_delete_selection()

        assert asked == []
        assert "cond-13" not in {c.id for c in window.bus.document.conductors}
        status = window.statusBar().currentMessage()
        assert "F1 → I1" in status and "Ctrl+Z" in status, status
    finally:
        type(window)._confirm = original
        _close(window)


def test_picking_a_net_in_the_panel_puts_the_boards_selection_down() -> None:
    """Delete took a run picked on the board a minute before, while Properties showed the
    net picked in the panel since."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        _select_conductor(window, "cond-8")
        thresh = next(net.id for net in window.bus.document.nets if net.name == "THRESH")
        row = next(
            item
            for i in range(window.nets_tree.topLevelItemCount())
            if (item := window.nets_tree.topLevelItem(i)) is not None
            and item.data(0, ROLE_NET_ID) == thresh
        )
        window.nets_tree.setCurrentItem(row)

        assert window.scene.selected_conductor_ids() == ()
        assert window._selected_net_ids() == (thresh,)
    finally:
        _close(window)


def test_remove_wiring_takes_up_one_nets_copper_as_one_step() -> None:
    window = _window_on(_example_document("ne555-astable"))
    try:
        document = window.bus.document
        thresh = next(net.id for net in document.nets if net.name == "THRESH")
        claimed = {c.id for c in document.conductors if c.net_id == thresh}
        assert claimed
        _select_conductor(window, "cond-8")

        menu = window.board_menu(
            window.view.mapFromScene(window.scene.conductor_items["cond-8"].boundingRect().center())
        )
        texts = [a.text() for a in menu.actions()]
        assert {"Select All of THRESH", "Redo Wiring of THRESH", "Remove Wiring of THRESH"} <= set(texts)

        window._remove_wiring((thresh,))
        left = {c.id for c in window.bus.document.conductors}
        assert not claimed & left
        assert window.bus.history()[-1] == "Remove the wiring of THRESH"
    finally:
        _close(window)


def test_redo_wiring_of_the_selection_takes_a_selected_conductors_net() -> None:
    window = _window_on(_example_document("ne555-astable"))
    asked: list[tuple[str, ...] | None] = []
    try:
        window.on_reroute = lambda net_ids, *a, **k: asked.append(net_ids)
        _select_conductor(window, "cond-8")
        window.on_reroute_selection()

        thresh = next(net.id for net in window.bus.document.nets if net.name == "THRESH")
        assert asked == [(thresh,)]
    finally:
        _close(window)


# -- copper drawn by hand: corners, carrying a run on, handles, picking, progress ----------------


def test_a_wires_path_keeps_only_the_corners_that_are_corners() -> None:
    H = view2d.HoleCoord
    assert view2d._straightened([H(2, 2), H(3, 2), H(3, 2), H(5, 2), H(5, 4)]) == (
        H(2, 2), H(5, 2), H(5, 4)
    )


def test_a_dragged_end_reshapes_each_kind_by_its_own_rule() -> None:
    """A run's end shortens to a pad it has or runs on along the grid, and its middle has
    no handle; a wire's end lays its last leg again, and its corner goes where it is put."""
    H = view2d.HoleCoord
    run = (H(5, 0), H(6, 0), H(7, 0), H(8, 0))
    assert view2d.reshaped_path("solder-trace", run, 3, H(6, 0)) == (H(5, 0), H(6, 0))
    assert view2d.reshaped_path("solder-trace", run, 3, H(8, 2)) == (*run, H(8, 1), H(8, 2))
    assert view2d.reshaped_path("solder-trace", run, 1, H(6, 3)) is None
    assert view2d.reshaped_path("solder-trace", run, 0, H(8, 0)) is None, "a run ends on itself"

    wire = (H(2, 2), H(6, 2), H(6, 5))
    assert view2d.reshaped_path("bare-wire", wire, 2, H(9, 7)) == (H(2, 2), H(9, 2), H(9, 7))
    assert view2d.reshaped_path("bare-wire", wire, 0, H(2, 4)) == (H(2, 4), H(2, 2), H(6, 2), H(6, 5))
    assert view2d.reshaped_path("top-jumper", (H(2, 2), H(6, 2)), 1, H(7, 4)) == (H(2, 2), H(7, 4))


def test_a_run_drawn_on_from_its_end_is_the_same_run_longer() -> None:
    """THRESH's run ends at L6. Drawing on from there made a second, separate run on no
    net; now it is the same run longer, in one setPath, one undo step."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        before = len(window.bus.document.conductors)
        window.on_draw_mode("solder-trace", True)
        window.scene.draw_click(_hole(window, "L6"))
        assert window.scene.continuing == "cond-8"
        window.scene.draw_click(_hole(window, "L5"))
        result = window.scene.commit_drawing()

        assert result is not None and result.ok, result
        document = window.bus.document
        assert len(document.conductors) == before
        run = next(c for c in document.conductors if c.id == "cond-8")
        assert [format_hole(h, document.board) for h in run.path] == ["I6", "J6", "K6", "L6", "L5"]
        assert window.statusBar().currentMessage().startswith("Extended solder trace I6 → L5: on THRESH")

        window.bus.undo()
        run = next(c for c in window.bus.document.conductors if c.id == "cond-8")
        assert [format_hole(h, document.board) for h in run.path] == ["I6", "J6", "K6", "L6"]
    finally:
        _close(window)


def test_a_wire_is_never_carried_on_from_its_end() -> None:
    """A wire touches only its ends: carried on, its old end would become a corner lying
    over the hole, and whatever was soldered there would come off it."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        window.on_draw_mode("bare-wire", True)
        window.scene.draw_click(_hole(window, "N4"))
        assert window.scene.continuing is None
        assert window.scene.drawn_path == (_hole(window, "N4"),)
    finally:
        _close(window)


def test_a_selected_wire_has_a_handle_on_every_corner_and_a_run_on_its_ends() -> None:
    window = _window_on(_example_document("ne555-astable"))
    try:
        _select_conductor(window, "cond-2")
        assert [h.index for h in window.scene._handles] == [0, 1, 2]
        window.scene.clearSelection()
        _select_conductor(window, "cond-8")
        assert [h.index for h in window.scene._handles] == [0, 3]
        window.scene.clearSelection()
        assert window.scene._handles == []
    finally:
        _close(window)


def test_a_handle_dragged_is_one_setpath_checked_as_it_moves() -> None:
    """Put down, a handle is one step Ctrl+Z takes back."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        _select_conductor(window, "cond-8")
        steps = len(window.bus.history())
        assert window.scene.begin_reshape(3)
        window.scene.reshape_to(_hole(window, "L5"))
        assert window.scene.reshaping

        result = window.scene.finish_reshape()
        assert result is not None and result.ok, result
        assert not window.scene.reshaping
        document = window.bus.document
        run = next(c for c in document.conductors if c.id == "cond-8")
        assert [format_hole(h, document.board) for h in run.path] == ["I6", "J6", "K6", "L6", "L5"]
        assert len(window.bus.history()) == steps + 1
        assert window.statusBar().currentMessage().startswith("Reshaped solder trace I6 → L5")
    finally:
        _close(window)


def test_a_handle_over_a_short_says_so_in_the_drag_banner() -> None:
    """LED_A's run, F1 → I1, dragged down from F1 through F2 -- GND's wire end -- says what
    it would do where a part's drag says it, and Esc leaves the copper where it was."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        _select_conductor(window, "cond-13")
        assert window.scene.begin_reshape(0)
        window.scene.reshape_to(_hole(window, "F3"))
        banner = window.view.drag_banner
        assert banner.isVisibleTo(window.view) and "short" in banner.text(), banner.text()
        # At F2, the pad the drag brought in -- not F1, the run's own end it was moved from.
        assert banner.text().startswith("F2"), banner.text()
        assert window.scene.cancel_reshape()
        assert not banner.isVisibleTo(window.view)
        run = next(c for c in window.bus.document.conductors if c.id == "cond-13")
        assert len(run.path) == 4
    finally:
        _close(window)


def test_a_click_where_copper_lies_on_copper_takes_the_next_one_each_time() -> None:
    """A run and a wire along one row: the one on top was all a click could reach, and
    Delete then took the wrong one."""
    scene, bus = _drawing_scene()
    for kind in ("solder-trace", "bare-wire"):
        scene.arm_drawing(kind)
        scene.draw_click(view2d.HoleCoord(2, 2))
        scene.draw_click(view2d.HoleCoord(6, 2))
        assert scene.commit_drawing() is not None
    scene.arm_drawing(None)
    scene.set_document(bus.document)
    told: list[tuple[int, int]] = []
    scene.pickCycled.connect(lambda which, count: told.append((which, count)))

    at = view2d.hole_to_screen(view2d.HoleCoord(4, 2), bus.document.board, "top")
    picks = []
    for _ in range(3):
        assert scene.cycle_pick(at)
        picks.append(scene.selected_conductor_ids())
    assert picks[0] != picks[1] and picks[2] == picks[0]
    assert {p[0] for p in picks} == {c.id for c in bus.document.conductors}
    assert told == [(1, 2), (2, 2), (1, 2)]

    # Nothing, or one conductor, under the click is an ordinary click, left to Qt.
    lone = view2d.hole_to_screen(view2d.HoleCoord(2, 8), bus.document.board, "top")
    assert not scene.cycle_pick(lone)


def test_the_banner_says_where_the_copper_has_got_to_and_how_to_finish() -> None:
    import dataclasses

    from perfboard_studio.commands import create_empty_document
    from perfboard_studio.model import DocumentMeta

    doc = create_empty_document(
        DocumentMeta(name="t", created="2024-01-01T00:00:00.000Z", modified="2024-01-01T00:00:00.000Z")
    )
    doc = dataclasses.replace(doc, board=dataclasses.replace(doc.board, material="FR2"))
    window = _window_on(doc)
    try:
        window.on_draw_mode("solder-trace", True)
        window.scene.draw_click(view2d.HoleCoord(1, 1))
        window.scene.hover_at(view2d.hole_to_screen(view2d.HoleCoord(4, 1), doc.board, "top"))
        banner = window.view.mode_banner.text()
        assert "B2 → E2" in banner and "4 pads" in banner and "Enter" in banner, banner
        assert "Shift+T" not in banner

        window.scene.hover_at(view2d.hole_to_screen(view2d.HoleCoord(9, 1), doc.board, "top"))
        banner = window.view.mode_banner.text()
        assert "9 pads" in banner and "Shift+T" in banner, banner

        window.on_draw_mode("bare-wire", True)
        window.scene.draw_click(view2d.HoleCoord(1, 4))
        window.scene.hover_at(view2d.hole_to_screen(view2d.HoleCoord(5, 4), doc.board, "top"))
        assert "mm" in window.view.mode_banner.text()
    finally:
        _close(window)


def test_a_wire_finishes_on_a_second_click_on_its_last_hole() -> None:
    scene, bus = _drawing_scene()
    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(2, 2))
    scene.draw_click(view2d.HoleCoord(6, 5))
    result = scene.draw_click(view2d.HoleCoord(6, 5))
    assert result is not None and result.ok
    assert bus.document.conductors[0].path[-1] == view2d.HoleCoord(6, 5)


def test_a_step_with_a_corner_is_drawn_as_a_line_not_filled() -> None:
    """The dashed step to the pointer was drawn with the joints' brush still set, so a step
    with a corner -- every wire off a row -- filled its triangle white."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    scene, bus = _drawing_scene()
    board = bus.document.board
    scene.arm_drawing("bare-wire")
    scene.draw_click(view2d.HoleCoord(2, 8))
    scene.hover_at(view2d.hole_to_screen(view2d.HoleCoord(8, 2), board, "top"))
    preview = scene._draw_preview
    assert preview is not None and preview.run == [view2d.HoleCoord(8, 8), view2d.HoleCoord(8, 2)]

    area = QRectF(
        view2d.hole_to_screen(view2d.HoleCoord(1, 1), board, "top"),
        view2d.hole_to_screen(view2d.HoleCoord(9, 9), board, "top"),
    )
    image = QImage(400, 400, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.scale(400 / area.width(), 400 / area.height())
    painter.translate(-area.topLeft())
    preview.paint(painter, None)
    painter.end()

    def at(col: int, row: int) -> int:
        p = view2d.hole_to_screen(view2d.HoleCoord(col, row), board, "top") - area.topLeft()
        return image.pixelColor(
            int(p.x() * 400 / area.width()), int(p.y() * 400 / area.height())
        ).alpha()

    assert at(8, 5) > 0, "the leg is drawn"
    assert at(6, 6) == 0, "inside the L is not"



def test_copper_drawn_exactly_over_copper_is_not_laid_and_says_what_is_there() -> None:
    """F1 → I1 drawn again over LED_A's run gave two identical runs, and nothing was said.
    From its end, the tool now carries that run on; from its middle, G1 → H1 is a stretch
    of pads it already solders."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        before = window.bus.document.conductors
        steps = len(window.bus.history())
        window.on_draw_mode("solder-trace", True)
        window.scene.draw_click(_hole(window, "G1"))
        assert window.scene.continuing is None
        _hover_hole(window, "H1")
        assert "already lies here" in window.view.mode_banner.text(), window.view.mode_banner.text()

        window.scene.draw_click(_hole(window, "H1"))
        assert window.scene.commit_drawing() is None
        assert window.bus.document.conductors == before
        assert len(window.bus.history()) == steps
        assert window.statusBar().currentMessage() == (
            "Already joined by solder trace F1 → I1: nothing added"
        )
        assert window.scene.armed_draw_kind == "solder-trace"
    finally:
        _close(window)


def test_a_wire_in_properties_offers_its_nets_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select All, Redo Wiring and Remove Wiring of a wire's net were on its right-click
    menu only; Properties, where a picked wire is shown, offered Auto-wire and Delete."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        document = window.bus.document
        wire = next(c for c in document.conductors if c.net_id is not None)
        net = next(n for n in document.nets if n.id == wire.net_id)
        window.scene.clearSelection()
        _select_conductor(window, wire.id)
        window._refresh_properties()
        editor = window.inspector.conductor_editor
        assert window.inspector.shown is editor
        assert not editor.net_buttons.isHidden()
        assert editor.redo_net.text() == f"Redo Wiring of {net.name}"

        editor.select_net.click()
        on_net = {c.id for c in window.bus.document.conductors if c.net_id == net.id}
        assert set(window.scene.selected_conductor_ids()) == on_net

        window.scene.clearSelection()
        _select_conductor(window, wire.id)
        window._refresh_properties()
        steps = len(window.bus.history())
        editor.remove_net.click()
        assert not any(c.net_id == net.id for c in window.bus.document.conductors)
        assert len(window.bus.history()) == steps + 1

        window.act_undo.trigger()
        # Redo goes through the same question the menu's does; declined, nothing moves.
        monkeypatch.setattr(type(window), "_confirm", lambda self, title, body, verb: False)
        window.scene.clearSelection()
        _select_conductor(window, wire.id)
        window._refresh_properties()
        window.inspector.conductor_editor.redo_net.click()
        assert window.bus.document.conductors == document.conductors
    finally:
        _close(window)


def test_wiring_worth_a_look_is_a_group_that_selects_its_wires_and_is_not_no_problems() -> None:
    """Auto-wire finished on "No problems" over wires lying across pins 44 times. What the
    engine says is worth a look is its own group in the drawer, each row selecting its
    wires, and the bar says there is wiring to review rather than that all is well --
    without counting it as a problem."""
    from perfboard_studio.ui.wiringreview import WiringNote

    window = _window_on(_example_document("ne555-astable"))
    try:
        # With nothing worth a look, the bar says so plainly.
        window._last_wiring = ()
        window._refresh_drc_panel(window._last_violations, window._last_lvs)
        window._refresh_problems_bar()
        assert window.problems_bar.badge.isHidden()
        assert "No problems" in window.problems_bar.title.text()
        wires = tuple(c.id for c in window.bus.document.conductors[:2])
        window._last_wiring = (
            WiringNote(key="over-pins", title="2 places a wire lies over a pin", conductor_ids=wires),
        )
        window._refresh_drc_panel(window._last_violations, window._last_lvs)
        window._refresh_problems_bar()

        assert "Wiring to review" in window.problems_bar.title.text()
        assert window.problems_bar.badge.isHidden()
        assert "2 wires to look at" in window.problems_bar.facts.text()
        tree = window.drc_tree
        group = next(
            tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
            if tree.topLevelItem(i).text(0) == "Wiring"
        )
        assert group.text(1) == "2 wires to look at"
        row = group.child(0)
        assert row.text(1) == "2 places a wire lies over a pin"
        window._on_drc_item_clicked(row, 1)
        assert set(window.scene.selected_conductor_ids()) == set(wires)
    finally:
        _close(window)


def test_a_finding_about_copper_alone_selects_the_copper() -> None:
    """Clicking a finding showed its holes and selected its parts; one about a wire and
    no part selected nothing, so the wire it named was still a hunt."""
    from perfboard_studio.drc import DrcViolation

    window = _window_on(_example_document("ne555-astable"))
    try:
        wire = window.bus.document.conductors[0]
        finding = DrcViolation(
            rule="conductor-crossing", severity="warning", message="m",
            holes=(wire.path[0],), component_ids=(), conductor_ids=(wire.id,),
        )
        window.scene.clearSelection()
        window._on_drc_item_clicked(window._drc_leaf(finding), 1)
        assert set(window.scene.selected_conductor_ids()) == {wire.id}
    finally:
        _close(window)


def test_one_nets_wiring_is_redone_in_a_style_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redone in the board's style, a net came back with the same bad wire: the only way to
    another answer was to change the style for everything. Redo Wiring of {net} is a menu
    of the styles, the board's checked; another applies to that net alone, is said in the
    question and the status, and leaves the Wiring Style menu as it was."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        document = window.bus.document
        thresh = next(net.id for net in document.nets if net.name == "THRESH")
        _select_conductor(window, "cond-8")
        menu = window.board_menu(
            window.view.mapFromScene(window.scene.conductor_items["cond-8"].boundingRect().center())
        )
        redo = next(a for a in menu.actions() if a.text() == "Redo Wiring of THRESH")
        styles = redo.menu()
        assert styles is not None
        names = [a.text() for a in styles.actions()]
        assert len(names) == 4 and "Solder trace where possible" in names
        assert [a.text() for a in styles.actions() if a.isChecked()] == ["Balanced"]

        bodies: list[str] = []
        monkeypatch.setattr(
            type(window), "_confirm", lambda self, title, body, verb: bodies.append(body) or True
        )
        solder = next(a for a in styles.actions() if a.text() == "Solder trace where possible")
        solder.trigger()
        assert window._routing_style == "balanced"
        assert window.act_style["balanced"].isChecked()
        assert bodies and "“Solder trace where possible”, for these nets only" in bodies[0]
        assert "for these nets only" in window.statusBar().currentMessage()
        others = [c for c in document.conductors if c.net_id != thresh]
        now = window.bus.document.conductors
        assert [c for c in now if c.net_id != thresh] == others
        assert [c for c in now if c.net_id == thresh] != [
            c for c in document.conductors if c.net_id == thresh
        ]
    finally:
        _close(window)


def test_redo_wiring_says_how_much_of_the_copper_it_actually_changes() -> None:
    """"15 old conductors removed, 15 conductors now" was all the question said about a
    plan that moved one wire's corner and laid every other piece back where it was."""
    from types import SimpleNamespace

    from perfboard_studio.model import HoleCoord
    from perfboard_studio.ui.main import _copper_change

    def piece(kind: str, *holes: tuple[int, int]) -> SimpleNamespace:
        return SimpleNamespace(kind=kind, side="bottom", path=tuple(HoleCoord(c, r) for c, r in holes))

    old = [piece("bare-wire", (1, 1), (5, 1)), piece("bare-wire", (5, 1), (5, 4)), piece("solder-trace", (1, 2), (2, 2))]
    new = [piece("bare-wire", (5, 1), (1, 1)), piece("bare-wire", (5, 1), (6, 1), (6, 4)), piece("solder-trace", (1, 2), (2, 2))]
    assert _copper_change(old, new) == (2, 1, 1)
    assert _copper_change(old, old) == (3, 0, 0)
    assert _copper_change(old, []) == (0, 3, 0)


def test_the_wiring_before_a_redo_is_drawn_over_todays_and_survives_a_flip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+Z was the only way to see what a route changed, and it took the new wiring
    away to show it. Compare With Before draws the copper as it was, dashed, over the
    copper now -- through a flip, which rebuilds the scene -- and a new document has
    nothing to compare with."""
    window = _window_on(_example_document("ne555-astable"))
    try:
        assert not window.act_compare_before.isEnabled()
        thresh = next(net.id for net in window.bus.document.nets if net.name == "THRESH")
        was = window.bus.document.conductors
        monkeypatch.setattr(type(window), "_confirm", lambda self, title, body, verb: True)
        window.on_reroute((thresh,), style="solder")
        assert window.bus.document.conductors != was
        assert window.act_compare_before.isEnabled()
        assert not window.scene.showing_before

        window.act_compare_before.trigger()
        assert window.scene.showing_before
        assert window.scene._before_item is not None
        assert "Dashed" in window.statusBar().currentMessage()
        window.act_flip.trigger()
        assert window.scene._before_item is not None
        assert window.scene._before_item.scene() is window.scene

        window.act_compare_before.trigger()
        assert not window.scene.showing_before
        assert window.scene._before_item is None

        window.act_compare_before.trigger()
        window._new_bus(window.bus.system_document)
        assert not window.act_compare_before.isEnabled()
        assert not window.act_compare_before.isChecked()
        assert not window.scene.showing_before
    finally:
        _close(window)


def test_every_wiring_menu_item_says_what_it_does() -> None:
    """Auto-wire Everything, Auto-wire the Selection, the two style menus, Redo Wiring of
    the Selection and Remove Out-of-Date Wiring had no tooltip but their own names, in a
    menu that did not show tooltips anyway."""
    from PySide6.QtWidgets import QMenu

    window = _window_on(_example_document("ne555-astable"))
    try:
        menu = window.act_autoroute.parent()
        assert isinstance(menu, QMenu) and menu.toolTipsVisible()
        for action in menu.actions():
            if action.isSeparator():
                continue
            name = action.text().replace("&", "")
            assert action.toolTip() and action.toolTip() != name, name
    finally:
        _close(window)


@pytest.mark.parametrize("stem", ["atmega328-relay", "nano-relay", "ne555-astable"])
def test_the_wiring_notes_are_the_engines_counts_over_the_wires_they_are_summed_from(
    stem: str,
) -> None:
    """The drawer's Wiring group counts what the autowire scoreboard counts, and selects
    exactly the wires the count is summed from: one fact, several askers."""
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.ui.wiringreview import DEEP_STACK, wiring_notes, wiring_summary
    from perfboard_studio.wiringstats import wiring_stats

    stats = wiring_stats(_example_document(stem), footprint_lookup())
    notes = {note.key: note for note in wiring_notes(stats)}
    wires = [entry for entry in stats.conductors if entry.is_wire]
    expected = {
        "over-pins": (stats.over_pins, [e.conductor_id for e in wires if e.over_pins]),
        "over-ends": (stats.over_ends, [e.conductor_id for e in wires if e.over_ends]),
        "stacked": (
            sum(1 for e in wires if e.level >= DEEP_STACK),
            [e.conductor_id for e in wires if e.level >= DEEP_STACK],
        ),
        "loops": (len(stats.loops), [cid for loop in stats.loops for cid in loop]),
    }
    for key, (count, ids) in expected.items():
        if not count:
            assert key not in notes, key
            continue
        assert notes[key].title.startswith(f"{count} "), notes[key].title
        assert list(notes[key].conductor_ids) == list(dict.fromkeys(ids))
    assert wiring_summary(stats).startswith(f"{len(wires)} wires, ")
    if stem == "atmega328-relay":
        assert {"over-pins", "over-ends"} <= notes.keys(), "the board the friction was found on"


def test_a_wire_in_properties_says_what_it_lies_across() -> None:
    """Properties said "Insulated Wire · N1 → D1, 2 holes" of a wire lying across ten holes
    nine wires up. It names the pins it lies over, as the guide names them, and the rest in
    counts -- the engine's entry for that wire. A solder trace is soldered to all it passes,
    and has no such row."""
    import re

    window = _window_on(_example_document("atmega328-relay"))
    try:
        stats = window._last_wiring_stats
        assert stats is not None
        entry = max(
            (e for e in stats.conductors if e.is_wire), key=lambda e: len(e.over_pins)
        )
        assert entry.over_pins
        window.scene.clearSelection()
        _select_conductor(window, entry.conductor_id)
        window._refresh_properties()
        editor = window.inspector.conductor_editor
        assert editor._form.isRowVisible(editor.lies_across)
        said = editor.lies_across.text()
        assert said.startswith(f"{len(entry.over_pins)} pin")
        assert re.search(r"\b[A-Z]+\d+\.\w+", said), said  # U1.3, not a hole address
        if entry.crosses:
            assert f"{len(entry.crosses)} crossing" in said

        trace = next(e for e in stats.conductors if e.pads)
        window.scene.clearSelection()
        _select_conductor(window, trace.conductor_id)
        window._refresh_properties()
        assert not editor._form.isRowVisible(editor.lies_across)
    finally:
        _close(window)


def test_the_step_card_keeps_the_wiring_and_a_count_selects_its_wires() -> None:
    """After Auto-wire the only account of the wiring was one status line the next message
    overwrote. With nothing selected Properties keeps it -- wires, length, bends -- and each
    count worth a look is a link that selects the wires it counts."""
    window = _window_on(_example_document("atmega328-relay"))
    try:
        window.scene.clearSelection()
        window._refresh_properties()
        card = window.inspector.step_card
        assert window.inspector.shown is card
        assert not card.wiring.isHidden()
        assert card.wiring.text().startswith("53 wires, ")
        links = [
            card._links.itemAt(i).widget() for i in range(card._links.count())
        ]
        over_pins = next(n for n in window._last_wiring if n.key == "over-pins")
        link = next(w for w in links if over_pins.title in w.text())
        link.linkActivated.emit(over_pins.key)
        assert set(window.scene.selected_conductor_ids()) == set(over_pins.conductor_ids)
        assert window.statusBar().currentMessage() == over_pins.title
    finally:
        _close(window)

    # Nothing wired yet, nothing said.
    window = _window_on(_example_document("atmega328-relay"))
    try:
        from perfboard_studio.commands import DeleteConductorsPayload

        ids = tuple(c.id for c in window.bus.document.conductors)
        assert window.bus.dispatch("conductor.deleteMany", DeleteConductorsPayload(ids=ids)).ok
        window.scene.clearSelection()
        window._refresh_properties()
        card = window.inspector.step_card
        assert card.wiring.isHidden() and card.wiring_links.isHidden()
    finally:
        _close(window)


def test_auto_wires_status_line_counts_what_the_step_card_counts() -> None:
    """"55 connections wired across 24/24 nets, 24 needed an insulated wire or jumper, 2
    wiring orders tried" sat under a card saying "53 wires · 5 solder traces" of the same
    board: two counts of one thing in two vocabularies, one of them the planner's working.
    The line says what was laid in the card's words, and keeps what is left to act on."""
    from perfboard_studio.autoroute import AutoroutePlan, AutorouteSummary

    window = _window_on(_example_document("atmega328-relay"))
    try:
        plan = AutoroutePlan(
            document=window.bus.document,
            conductors=(),
            nets=(),
            summary=AutorouteSummary(
                nets_considered=24, nets_closed=23, links_routed=55, links_unrouted=1,
                total_cost=0.0, fallback_links=24, risk_holes=2, passes=2,
            ),
            label="",
        )
        window.scene.clearSelection()
        window._refresh_properties()
        card = window.inspector.step_card.wiring.text()
        assert card.startswith("53 wires, ")
        # Everything on the board counts as just laid when nothing was there before.
        said = window._wired_said(plan, set())
        assert said == f"23 of 24 nets wired: {card}  ·  1 connection could not be wired"
        # What is left to check at the bench is the drawer's count, in the drawer's words
        # -- never the planner's "2 pads to measure for isolation" beside it.
        from perfboard_studio.drc import DrcViolation

        bench = DrcViolation(
            rule="solder-trace-proximity", severity="warning", message="",
            holes=(HoleCoord(1, 1), HoleCoord(2, 1)),
        )
        window._last_violations = (*window._last_violations, bench)
        assert window._wired_said(plan, set()) == f"{said}  ·  1 to check at the bench"
        assert "orders" not in said and "insulated" not in said
        # Only what this run laid is counted: nothing new, no wiring said.
        everything = {c.id for c in window.bus.document.conductors}
        assert window._wired_said(plan, everything).startswith("23 of 24 nets wired  ·  ")
    finally:
        _close(window)


def test_no_dock_separator_is_left_lying_over_the_problems_list(monkeypatch) -> None:
    """A line cut through the drawer's third row, "Board check (DRC)", whatever was in it.
    It was a separator handle of Qt's own: the window's panels are tabbed together before
    their layout is restored, and ``restoreState`` keeps one handle of that first layout,
    visible, where the column's edge was. The drawer opened over it and the handle, which
    nothing moves any more, painted itself across the list."""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QApplication, QWidget

    window = _shown_window_without_3d(monkeypatch, width=1440)
    try:
        window.set_problems_open(True)
        _settle_events(QApplication)
        viewport = window.drc_tree.viewport()
        assert viewport.isVisible() and viewport.height() > 40
        listed = QRect(viewport.mapTo(window, QPoint(0, 0)), viewport.size())
        stray = [
            QRect(handle.mapTo(window, QPoint(0, 0)), handle.size())
            for handle in window.findChildren(QWidget, "qt_qmainwindow_extended_splitter")
            if handle.isVisible()
        ]
        assert not [rect for rect in stray if rect.intersects(listed)], stray
        # The handles that ARE the layout's are still there to be dragged.
        assert any(rect.width() > rect.height() for rect in stray)
        assert any(rect.height() > rect.width() for rect in stray)
    finally:
        _close(window)


def test_a_wires_net_is_wired_again_without_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redone in any style, a net came back with the same bad wire: planning is
    deterministic. Redo Wiring Without This Wire, on the wire's right-click menu and in its
    Properties, keeps the new plan off the holes it lay across, says so in the question and
    the status, and is one undo step. A solder trace has no such entry."""
    from perfboard_studio.autoroute import holes_to_avoid
    from perfboard_studio.geometry import hole_key, holes_under_line

    window = _window_on(_example_document("atmega328-relay"))
    try:
        stats = window._last_wiring_stats
        assert stats is not None
        entry = max(
            (e for e in stats.conductors if e.is_wire), key=lambda e: len(e.over_pins)
        )
        document = window.bus.document
        wire = next(c for c in document.conductors if c.id == entry.conductor_id)
        assert wire.net_id is not None
        avoid = {hole_key(h) for h in holes_to_avoid(document, window.lookup, wire.id)}
        assert avoid

        window.scene.clearSelection()
        _select_conductor(window, wire.id)
        window._refresh_properties()
        editor = window.inspector.conductor_editor
        assert not editor.redo_without.isHidden()
        # A point on the wire with no part under it: a part under the pointer gets the menu.
        outline = window.scene.conductor_items[wire.id].shape()
        on_wire = next(
            point
            for point in (outline.pointAtPercent(i / 200) for i in range(201))
            if window.scene.component_at(point) is None
            and window.scene.conductor_at(point) is window.scene.conductor_items[wire.id]
        )
        menu = window.board_menu(window.view.mapFromScene(on_wire))
        assert "Redo Wiring Without This Wire" in [a.text() for a in menu.actions()]

        bodies: list[str] = []

        def answer(self, title, body, verb):
            bodies.append(body)
            return True

        monkeypatch.setattr(type(window), "_confirm", answer)
        steps = len(window.bus.history())
        editor.redo_without.click()
        assert bodies and "Without the wire " in bodies[-1]
        after = window.bus.document
        assert wire.id not in {c.id for c in after.conductors}
        assert len(window.bus.history()) == steps + 1
        assert "Without the wire " in window.statusBar().currentMessage()
        laid = [c for c in after.conductors if c.net_id == wire.net_id]
        for conductor in laid:
            ends = {hole_key(conductor.path[0]), hole_key(conductor.path[-1])}
            for start, stop in zip(conductor.path, conductor.path[1:], strict=False):
                for hole in holes_under_line(start, stop):
                    key = hole_key(hole)
                    assert key in ends or key not in avoid, (conductor.id, key)

        # A solder trace is soldered to what it passes: nothing to keep clear of.
        window.act_undo.trigger()
        stats = window._last_wiring_stats
        assert stats is not None
        trace = next(e for e in stats.conductors if e.pads)
        assert not window._can_redo_without(trace.conductor_id)
        window.scene.clearSelection()
        _select_conductor(window, trace.conductor_id)
        window._refresh_properties()
        assert window.inspector.conductor_editor.redo_without.isHidden()
    finally:
        _close(window)


def test_trying_every_style_says_which_it_is_wiring_and_stops_between_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"Wiring with every style…" sat over four styles wired one after another, and Cancel
    did nothing until the last. The label names the style being wired, Cancel stops between
    styles and keeps the best of those wired, and the status says how many it chose from."""
    from perfboard_studio.commands import DeleteConductorsPayload
    from perfboard_studio.ui.main import MainWindow

    labels: list[str] = []

    def run(self, label, work, stopped=None, aside=None):
        labels.append(label() if callable(label) else label)

        def should_stop() -> bool:
            labels.append(label() if callable(label) else label)
            return True  # Cancel pressed while the first style was wired.

        return work(should_stop)

    monkeypatch.setattr(MainWindow, "_run_planner", run)
    window = _window_on(_example_document("ne555-astable"))
    try:
        ids = tuple(c.id for c in window.bus.document.conductors)
        assert window.bus.dispatch("conductor.deleteMany", DeleteConductorsPayload(ids=ids)).ok
        window.act_style["best"].trigger()
        assert window._routing_style == "best"
        window.on_autoroute_all()
        from perfboard_studio.autoroute import ALL_ROUTING_STYLES

        first = dict(window.wiring_styles())[ALL_ROUTING_STYLES[0]]
        total = len(ALL_ROUTING_STYLES)
        assert labels[0] == "Wiring with every style…"
        assert labels[1] == f"Wiring in “{first}” (1 of {total})…", labels
        assert window.bus.document.conductors, "the best of what was wired is kept"
        assert f"stopped after 1 of {total} styles" in window.statusBar().currentMessage()
    finally:
        _close(window)


def test_a_planner_nobody_cancels_never_says_it_is_stopping(monkeypatch: pytest.MonkeyPatch) -> None:
    """A finished run's dialog said "Stopping, and keeping the best found so far…" as it
    closed: ``QProgressDialog.close`` emits ``canceled``, and the window's Cancel handler
    took that for a press. A run nobody stopped says nothing about stopping; one that is
    stopped still does."""
    import time

    from PySide6.QtWidgets import QProgressDialog

    from perfboard_studio.ui.main import MainWindow

    said: list[str] = []
    original = QProgressDialog.setLabelText

    def spy(self, text):
        said.append(text)
        original(self, text)

    monkeypatch.setattr(QProgressDialog, "setLabelText", spy)
    monkeypatch.setattr(MainWindow, "PLANNER_GRACE_S", 0.0)
    window = _window_on(_example_document("ne555-astable"))
    try:
        def work(should_stop):
            time.sleep(0.3)
            return "done"

        assert window._run_planner("Working on it…", work) == "done"
        assert not [text for text in said if "Stopping" in text], said

        # Pressed, it is said.
        said.clear()

        def stopped_work(should_stop):
            deadline = time.perf_counter() + 5
            while not should_stop() and time.perf_counter() < deadline:
                time.sleep(0.02)
            return "kept"

        from PySide6.QtCore import QTimer

        def press() -> None:
            dialog = next(
                (d for d in window.findChildren(QProgressDialog) if d.isVisible()), None
            )
            if dialog is None:
                QTimer.singleShot(20, press)
            else:
                # What its Cancel button does: emit ``canceled`` (``cancel()`` does not).
                dialog.canceled.emit()

        QTimer.singleShot(50, press)
        assert window._run_planner("Working on it…", stopped_work) == "kept"
        assert [text for text in said if "Stopping" in text], said
    finally:
        _close(window)


def test_the_step_card_offers_every_style_when_the_wiring_has_something_worth_a_look(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trying every style is not the default -- on most boards it costs seconds and finds
    what Balanced found -- so the card offers it where it can matter: under the counts of
    what is worth a look. Taken, the best of them replaces the nets' copper as one undo
    step, asked first; taken again, it says the wiring is already the best and asks
    nothing."""
    from perfboard_studio.commands import DeleteConductorsPayload

    asked: list[str] = []

    def answer(self, title, body, verb):
        asked.append(title)
        return True

    window = _window_on(_example_document("arduino-io-shield"))
    monkeypatch.setattr(type(window), "_confirm", answer)
    try:
        ids = tuple(c.id for c in window.bus.document.conductors)
        assert window.bus.dispatch("conductor.deleteMany", DeleteConductorsPayload(ids=ids)).ok
        assert window._routing_style == "balanced"
        window.on_autoroute_all()
        assert window._last_wiring, "the board this was measured on has wires worth a look"
        window.scene.clearSelection()
        window._refresh_properties()
        card = window.inspector.step_card
        offers = [
            card._links.itemAt(i).widget()
            for i in range(card._links.count())
            if 'href="try"' in card._links.itemAt(i).widget().text()
        ]
        assert len(offers) == 1 and "Try every wiring style" in offers[0].text()

        steps = len(window.bus.history())
        offers[0].linkActivated.emit("try")
        assert asked and asked[-1].startswith("Wire the board in “")
        assert len(window.bus.history()) == steps + 1
        assert "beat 3 other styles" in window.statusBar().currentMessage()

        asked.clear()
        window.on_try_every_style()
        assert not asked
        assert "nothing changed" in window.statusBar().currentMessage()

        # Trying every style already: nothing to offer.
        window.act_style["best"].trigger()
        window.scene.clearSelection()
        window._refresh_properties()
        card = window.inspector.step_card
        assert not any(
            'href="try"' in card._links.itemAt(i).widget().text()
            for i in range(card._links.count())
        )
    finally:
        _close(window)


def _single_sided(document):
    return dataclasses.replace(
        document, board=dataclasses.replace(document.board, single_sided=True)
    )


def test_a_nets_face_is_chosen_in_its_properties_and_its_menus() -> None:
    """Which face Auto-wire lays a net on (``Net.preferred_side``): three buttons in the
    net's Properties and a Net Face submenu wherever the net's own menu is, each one undo
    step, and none of it on a board with no pads on the component side."""
    from PySide6.QtWidgets import QMenu

    from perfboard_studio.ui.i18n import t
    from perfboard_studio.ui.inspector import NET_FACES

    document = _example_document("atmega328-relay")
    window = _window_on(document)
    try:
        gnd = next(n for n in window.bus.document.nets if n.net_class == "ground")
        editor = _inspect_net(window, gnd.id)
        assert window.inspector.net_editor._form.isRowVisible(editor._face_row)
        assert editor._face_buttons[None].isChecked()
        steps = len(window.bus.history())
        editor._face_buttons["top"].click()
        net = next(n for n in window.bus.document.nets if n.id == gnd.id)
        assert net.preferred_side == "top"
        assert len(window.bus.history()) == steps + 1
        assert editor._face_buttons["top"].isChecked()

        menu = QMenu()
        faces = window._net_face_menu(gnd.id, menu)
        assert faces is not None
        labels = [a.text() for a in faces.actions()]
        assert labels == [t(row[2]) for row in NET_FACES]
        checked = [a.text() for a in faces.actions() if a.isChecked()]
        assert checked == [t("&Component Side")]
        faces.actions()[2].trigger()
        net = next(n for n in window.bus.document.nets if n.id == gnd.id)
        assert net.preferred_side == "bottom"
        assert "applies the next time you auto-wire" in window.statusBar().currentMessage()
        # The sheet's net menu has it too, beside Net Class.
        entries = QMenu()
        window._add_net_entries(entries, gnd.id)
        assert t("Net &Face") in [a.text() for a in entries.actions()]
        window.act_undo.trigger()
        window.act_undo.trigger()
        net = next(n for n in window.bus.document.nets if n.id == gnd.id)
        assert net.preferred_side is None
    finally:
        _close(window)

    window = _window_on(_single_sided(document))
    try:
        gnd = next(n for n in window.bus.document.nets if n.net_class == "ground")
        editor = _inspect_net(window, gnd.id)
        assert not window.inspector.net_editor._form.isRowVisible(editor._face_row)
        assert window._net_face_menu(gnd.id, QMenu()) is None
    finally:
        _close(window)


def test_a_net_on_the_component_side_is_wired_there_without_both_faces() -> None:
    """The seam: the Face the window sets reaches the router through the window's own
    options. atmega328-relay's GND preferring the component side lays copper there and
    changes face through vias with Wire on Both Faces off -- the per-net choice is the more
    explicit intent and does not wait for the global one."""
    from perfboard_studio.autoroute import plan_reroute
    from perfboard_studio.commands import UpdateNetPayload
    from perfboard_studio.wiringstats import wiring_stats

    window = _window_on(_example_document("atmega328-relay"))
    try:
        assert not window.act_both_faces.isChecked()
        assert window._autoroute_options().router.faces == "solder"
        gnd = next(n for n in window.bus.document.nets if n.net_class == "ground")

        def sides() -> list[str]:
            plan = plan_reroute(
                window.bus.document, window.lookup, only_net_ids=(gnd.id,),
                options=window._autoroute_options(),
            )
            return [c.side for c in plan.document.conductors if c.net_id == gnd.id]

        assert "top" not in sides()
        window.bus.dispatch("net.update", UpdateNetPayload(id=gnd.id, preferred_side="top"))
        assert "top" in sides()
        plan = plan_reroute(
            window.bus.document, window.lookup, only_net_ids=(gnd.id,),
            options=window._autoroute_options(),
        )
        assert wiring_stats(plan.document, window.lookup).vias
    finally:
        _close(window)


def test_wire_on_both_faces_reaches_the_router_and_is_remembered() -> None:
    """Wiring ▸ Wire on Both Faces: off by default, as the engine's default and every golden
    route are; a setting of the window, never of the document; it reaches the "best" sweep
    like the grid setting; and greyed out on a board with nothing on the component side."""
    from perfboard_studio.ui.i18n import t

    document = _example_document("atmega328-relay")
    first = _window_on(document)
    try:
        assert first.act_both_faces.isEnabled()
        assert not first.act_both_faces.isChecked()
        first.act_both_faces.setChecked(True)
        assert first._autoroute_options().router.faces == "both"
        first.on_routing_style("best")
        assert first._autoroute_options().router.faces == "both"
        # Nothing of it is written into the board.
        assert first.bus.document.nets == document.nets
    finally:
        _close(first)

    second = _window_on(document)
    try:
        assert second.act_both_faces.isChecked()
        assert second._autoroute_options().router.faces == "both"
        second.act_both_faces.setChecked(False)
        assert second._autoroute_options().router.faces == "solder"
    finally:
        _close(second)

    single = _window_on(_single_sided(document))
    try:
        assert not single.act_both_faces.isEnabled()
        assert single.act_both_faces.toolTip() == t(
            "This board has no copper on the component side."
        )
    finally:
        _close(single)


def test_auto_wire_says_when_wire_on_both_faces_laid_nothing_on_the_component_side() -> None:
    """On every example board the router finds nothing shorter on the component side, so
    Wire on Both Faces turned on gave the same board and not a word. Now the status line
    says it laid nothing there and what does put a net there; off, or with a net that
    asked for the face and a face note to say why, it says nothing of the kind."""
    from perfboard_studio.ui.i18n import t

    unused = t(
        "Wire on Both Faces laid nothing on the component side, where no net came out "
        "shorter: a net's Face set to Component Side puts it there"
    )
    bare = dataclasses.replace(_example_document("ne555-astable"), conductors=())
    for both in (False, True):
        window = _window_on(bare)
        try:
            window.act_both_faces.setChecked(both)
            window.on_autoroute_all()
            assert window.bus.document.conductors
            assert not any(c.side == "top" for c in window.bus.document.conductors)
            assert (unused in window.statusBar().currentMessage()) is both
        finally:
            _close(window)

    shield = _example_document("arduino-io-shield")
    asked = dataclasses.replace(
        shield,
        conductors=(),
        nets=tuple(
            dataclasses.replace(n, preferred_side="top" if n.name == "GND" else None)
            for n in shield.nets
        ),
    )
    window = _window_on(asked)
    try:
        window.act_both_faces.setChecked(True)
        window.on_autoroute_all()
        said = window.statusBar().currentMessage()
        assert unused not in said, "the face note says why, and one reason is enough"
        assert "Problems" in said or t("Problems") in said
    finally:
        _close(window)


def test_auto_wire_says_a_net_wired_off_its_face_as_information_not_a_problem() -> None:
    """The shield's GND set to the component side comes back wired underneath: every GND
    pin there is under J2's plastic. The window says so -- on the status line and in a
    Faces group of the Problems drawer -- and counts it as nothing: a preference is a price,
    never a rule."""
    from perfboard_studio.ui import theme
    from perfboard_studio.ui.engine_text import say
    from perfboard_studio.ui.i18n import counted, t
    from perfboard_studio.ui.main import ROLE_FINDING_KEY

    shield = _example_document("arduino-io-shield")
    bare = dataclasses.replace(
        shield,
        conductors=(),
        nets=tuple(
            dataclasses.replace(n, preferred_side="top" if n.name == "GND" else None)
            for n in shield.nets
        ),
    )
    window = _window_on(bare)
    try:
        window.act_both_faces.setChecked(True)
        window.on_autoroute_all()
        said_of, notes = window._face_notes
        assert said_of is window.bus.document
        [note] = notes
        assert (note.net_name, note.reason, note.covered_by) == ("GND", "covered", ("J2",))
        # The engine's own note, from the document the plan was made FROM.
        assert window.bus.document.conductors
        assert counted(
            1,
            t("{count} net wired off the face it prefers: why is in Problems"),
            t("{count} nets wired off the face they prefer: why is in Problems"),
        ) in window.statusBar().currentMessage()

        tree = window.drc_tree
        groups = {
            tree.topLevelItem(i).data(0, ROLE_FINDING_KEY): tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())
        }
        faces = groups["FACES"]
        assert faces.text(0) == t("Faces")
        assert [faces.child(i).text(1) for i in range(faces.childCount())] == [say(note.message)]

        # A click on the row lights the net.
        window._on_drc_item_clicked(faces.child(0), 1)
        assert note.net_id in window._selected_net_ids()

        # On the bar, in the neutral colour beside the facts, and counted as nothing: the
        # badge reads the same with the note and without it.
        off = counted(1, t("{count} net off its face"), t("{count} nets off their face"))
        assert off in window.problems_bar.facts.text()
        assert theme.ink("●", "secondary") + " " + off in window.problems_bar.facts.text()
        counts: list[dict] = []
        real_set_counts = window.problems_bar.set_counts
        window.problems_bar.set_counts = lambda **kw: counts.append(kw)  # type: ignore[method-assign]
        window._refresh_problems_bar()
        window._face_notes = (None, ())
        window._refresh_problems_bar()
        assert (counts[0].pop("off_face"), counts[1].pop("off_face")) == (1, 0)
        assert counts[0] == counts[1]
        window.problems_bar.set_counts = real_set_counts  # type: ignore[method-assign]
        window._refresh_problems_bar()
        assert off not in window.problems_bar.facts.text()
        # ...and the group goes with the note.
        window._refresh_drc_panel(window._last_violations, window._last_lvs)
        assert all(
            tree.topLevelItem(i).data(0, ROLE_FINDING_KEY) != "FACES"
            for i in range(tree.topLevelItemCount())
        )
    finally:
        _close(window)


@pytest.mark.parametrize("gnd_copper", ["kept", "none"])
def test_redo_wiring_of_one_net_says_it_is_off_its_face_as_auto_wire_does(
    monkeypatch, gnd_copper: str
) -> None:
    """Set GND to the component side on the wired shield and redo GND alone: it comes back
    underneath, exactly where it was, for the same reason Auto-wire's did (J2's plastic) --
    the case that most needs the why, since nothing on the board moved -- and is told so the
    same way: the status line and the Faces group."""
    from perfboard_studio.commands import UpdateNetPayload
    from perfboard_studio.ui.i18n import counted, t
    from perfboard_studio.ui.main import ROLE_FINDING_KEY

    shield = _example_document("arduino-io-shield")
    gnd = next(n for n in shield.nets if n.name == "GND")
    if gnd_copper == "none":
        # The other road through on_reroute: copper is laid, not found unchanged.
        shield = dataclasses.replace(
            shield, conductors=tuple(c for c in shield.conductors if c.net_id != gnd.id)
        )
    window = _window_on(shield)
    monkeypatch.setattr(type(window), "_confirm", lambda self, title, body, verb: True)
    try:
        window.act_both_faces.setChecked(True)
        window.bus.dispatch("net.update", UpdateNetPayload(id=gnd.id, preferred_side="top"))
        window.on_reroute((gnd.id,))

        said_of, notes = window._face_notes
        assert said_of is window.bus.document
        [note] = notes
        assert (note.net_name, note.reason, note.covered_by) == ("GND", "covered", ("J2",))
        assert counted(
            1,
            t("{count} net wired off the face it prefers: why is in Problems"),
            t("{count} nets wired off the face they prefer: why is in Problems"),
        ) in window.statusBar().currentMessage()
        tree = window.drc_tree
        assert any(
            tree.topLevelItem(i).data(0, ROLE_FINDING_KEY) == "FACES"
            for i in range(tree.topLevelItemCount())
        )
    finally:
        _close(window)


def test_vias_are_counted_on_the_card_in_the_status_line_and_on_the_copper() -> None:
    """A via is one more hole to fill and check, so the wiring says how many there are:
    the step card's line, Auto-wire's status line (the ones it just made) and the
    Properties of every piece of copper that meets the other face at one."""
    from perfboard_studio.commands import DeleteConductorsPayload, UpdateNetPayload
    from perfboard_studio.ui.i18n import counted, t
    from perfboard_studio.ui.wiringreview import wiring_summary

    window = _window_on(_example_document("atmega328-relay"))
    try:
        gnd = next(n for n in window.bus.document.nets if n.net_class == "ground")
        window.bus.dispatch("net.update", UpdateNetPayload(id=gnd.id, preferred_side="top"))
        window.bus.dispatch(
            "conductor.deleteMany",
            DeleteConductorsPayload(
                ids=tuple(c.id for c in window.bus.document.conductors if c.net_id == gnd.id)
            ),
        )
        before = {c.id for c in window.bus.document.conductors}
        window._route(only_net_ids=(gnd.id,))
        stats = window._last_wiring_stats
        assert stats is not None and stats.vias
        assert wiring_summary(stats).endswith(
            counted(len(stats.vias), t("{count} via"), t("{count} vias"))
        )
        assert t("{count} via").format(count=1).split()[-1] in window.statusBar().currentMessage()

        via = stats.vias[0]
        meets = [
            c for c in window.bus.document.conductors
            if c.id not in before and c.side == "top" and any(
                (h.col, h.row) == (via.col, via.row) for h in c.path
            )
        ]
        assert meets
        window.scene.clearSelection()
        _select_conductor(window, meets[0].id)
        window._refresh_properties()
        editor = window.inspector.conductor_editor
        assert editor._form.isRowVisible(editor.joins_other_face)
        assert format_hole(via, window.bus.document.board) in editor.joins_other_face.text()
    finally:
        _close(window)


def test_solder_on_an_outside_finger_is_drawn_on_the_finger_in_2d() -> None:
    """A rail's cells are addresses one step past the grid; the finger is wherever its strip
    was made -- on the 9 x 15 cm board nearly 6 mm from that point. The 2D view draws every
    cell of the path on the finger's copper, on both faces, mirrored for the solder side
    about the hole span as every hole is, and leaves the bridge's hole where the hole is."""
    from perfboard_studio.boardfamily import STANDARD_PRESETS
    from perfboard_studio.commands import (
        create_empty_document,
        document_on_preset,
        rail_payload,
    )
    from perfboard_studio.geometry import (
        finger_cell_mm,
        finger_cells,
        hole_key,
        hole_span_mm,
        hole_to_mm,
        strip_cells,
    )
    from perfboard_studio.model import DocumentMeta

    preset = next(
        p for p in STANDARD_PRESETS if p.name == "9 x 15 cm" and p.family == "double-sided-fr4"
    )
    document = document_on_preset(
        create_empty_document(DocumentMeta(name="rails", created="", modified="")), preset
    )
    strip = strip_cells(document, "ec-left")
    first, last = strip[0], strip[-1]
    window = _window_on(document)
    try:
        result = window.bus.dispatch(
            "conductor.addMany",
            rail_payload(window.bus.document, first.cell, last.cell, bridges=[first.beside]),
        )
        assert result.ok, result.message
        board = window.bus.document.board
        cells = finger_cells(window.bus.document)
        span_w, _span_h = hole_span_mm(board)
        for side in ("top", "bottom"):
            if window.scene.side != side:
                window.on_flip_board()
            drawn = 0
            for conductor in window.bus.document.conductors:
                points = window.scene.conductor_items[conductor.id]._points()
                for hole, point in zip(conductor.path, points, strict=True):
                    cell = cells.get(hole_key(hole))
                    at = finger_cell_mm(cell, board) if cell else hole_to_mm(hole, board)
                    x = span_w - at.x if side == "bottom" else at.x
                    assert (point.x(), point.y()) == pytest.approx((x, at.y)), (side, hole)
                    drawn += cell is not None
            assert drawn >= len(strip)
        # Where the cell would be, one pitch past the grid, is not where it is drawn.
        assert abs(finger_cell_mm(first, board).x - hole_to_mm(first.cell, board).x) > 2
    finally:
        _close(window)


def test_hand_solder_is_drawn_on_the_face_draw_on_names_never_the_one_in_view() -> None:
    """Draw on: Solder Side | Component Side, under the banner while a solder tool is armed
    on a board with pads on both faces. The solder side at every start, whichever face the
    window looks at; one choice for both solder tools; a run on the other face is not
    carried on from its end; and turned over to the solder side with the component side
    chosen, the banner says the copper goes on the far face. Wires keep their kind's face,
    and a board with pads on one face has no choice to make."""
    from perfboard_studio.boardfamily import STANDARD_PRESETS
    from perfboard_studio.commands import create_empty_document, document_on_preset
    from perfboard_studio.model import DocumentMeta, HoleCoord
    from perfboard_studio.ui.i18n import t

    def board(family: str) -> PerfDocument:
        preset = next(p for p in STANDARD_PRESETS if p.name == "5 x 7 cm" and p.family == family)
        return document_on_preset(
            create_empty_document(DocumentMeta(name="faces", created="", modified="")), preset
        )

    def draw(window, kind: str, *holes: HoleCoord):  # type: ignore[no-untyped-def]
        window.on_draw_mode(kind, True)
        result = None
        for hole in holes:
            result = window.scene.draw_click(hole)
        if result is None:  # A jumper is laid by its second click.
            result = window.scene.commit_drawing()
        assert result is not None and result.ok, result
        return next(c for c in window.bus.document.conductors if c.path[0] == holes[0])

    far = t("the copper goes on the far face: Ctrl+F turns the board over")
    window = _window_on(board("double-sided-fr4"))
    try:
        assert window.scene.side == "top"
        assert window.draw_face_bar.isHidden()
        window.on_draw_mode("solder-trace", True)
        assert not window.draw_face_bar.isHidden()
        assert window.act_draw_face["bottom"].isChecked()
        # Looking at the component side, a run still goes underneath unless asked.
        assert draw(window, "solder-trace", HoleCoord(2, 2), HoleCoord(5, 2)).side == "bottom"
        window.act_draw_face["top"].trigger()
        assert window.scene.solder_draw_face == "top"
        top_run = draw(window, "solder-trace", HoleCoord(2, 4), HoleCoord(5, 4))
        assert top_run.side == "top"
        # Made a reinforced run in its Properties, it stays on the face it was on.
        window.on_draw_mode("solder-trace", False)
        _select_conductor(window, top_run.id)
        window._refresh_properties()
        window.inspector.conductor_editor._commit_kind("solder-trace-wired")
        remade = next(
            c for c in window.bus.document.conductors if c.path[0] == HoleCoord(2, 4)
        )
        assert (remade.kind, remade.side) == ("solder-trace-wired", "top")
        # One choice for both solder tools.
        assert draw(
            window, "solder-trace-wired", HoleCoord(2, 6), HoleCoord(6, 6)
        ).side == "top"
        # A run underneath ends at C3, but it is on the other face: a new run starts there.
        window.on_draw_mode("solder-trace", True)
        window.scene.draw_click(HoleCoord(5, 2))
        assert window.scene.continuing is None
        window.on_draw_mode("solder-trace", False)
        # Turned over: the far-face note, for the component side only.
        window.on_draw_mode("solder-trace", True)
        assert far not in window._mode_text()
        window.on_flip_board()
        assert window.scene.side == "bottom"
        assert far in window._mode_text()
        window.act_draw_face["bottom"].trigger()
        assert far not in window._mode_text()
        # The wires are not on the choice, and the bar is not there for them.
        window.act_draw_face["top"].trigger()
        window.on_draw_mode("bare-wire", True)
        assert window.draw_face_bar.isHidden()
        assert draw(window, "bare-wire", HoleCoord(8, 2), HoleCoord(8, 6)).side == "bottom"
        assert draw(window, "top-jumper", HoleCoord(10, 2), HoleCoord(10, 6)).side == "top"
        window.on_draw_mode("bare-wire", False)
        assert window.draw_face_bar.isHidden()
    finally:
        _close(window)

    # For the session only: the next window starts on the solder side.
    window = _window_on(board("double-sided-fr4"))
    try:
        assert window.scene.solder_draw_face == "bottom"
        assert window.act_draw_face["bottom"].isChecked()
    finally:
        _close(window)

    window = _window_on(board("single-sided-phenolic"))
    try:
        window.on_draw_mode("solder-trace", True)
        assert window.draw_face_bar.isHidden()
        window.scene.draw_face = "top"
        assert draw(window, "solder-trace", HoleCoord(2, 2), HoleCoord(5, 2)).side == "bottom"
    finally:
        _close(window)


def test_a_banner_too_long_for_the_board_is_wrapped_every_time_it_is_placed() -> None:
    """The banner is one line when it fits and wraps to the room when it does not. Fixed
    to the room on one pass, it came back on the next at exactly that width -- never wider
    than the room -- so it was left unwrapped and cut off at both ends: every mouse move
    while drawing places it again."""
    window = _window_on(_example_document("atmega328-relay"))
    try:
        view = window.view
        text = "a long line of what the armed tool does " * 12
        for _ in range(3):
            view.show_mode(text)
            banner = view.mode_banner
            assert banner.wordWrap()
            assert banner.width() <= view.viewport().width()
            assert banner.height() > banner.fontMetrics().height() * 2
        # And a short one goes back to one line, at its own width.
        view.show_mode("Measuring")
        assert not view.mode_banner.wordWrap()
        assert view.mode_banner.width() < view.viewport().width() // 2
    finally:
        _close(window)


def test_make_this_strip_a_rail_from_the_strips_own_menu() -> None:
    """Right-click an outside finger strip: Make This Strip a Rail… opens a dialog with the
    net (ground first), the two fingers and the bridges -- ticked where the net already
    reaches the hole beside -- and lays the rail and its bridges as ONE undo step, through
    the same ``rail_payload`` MCP's ``add_rail`` dispatches. No bridge is allowed but said."""
    from perfboard_studio.boardfamily import STANDARD_PRESETS
    from perfboard_studio.commands import (
        AddConductorPayload,
        AddNetPayload,
        NewSolderTraceConductor,
        create_empty_document,
        document_on_preset,
    )
    from perfboard_studio.geometry import finger_cells, strip_cells
    from perfboard_studio.model import DocumentMeta, HoleCoord
    from perfboard_studio.ui.i18n import t
    from perfboard_studio.ui.raildialog import RailDialog
    from perfboard_studio.ui.view2d import path_point_to_screen

    preset = next(
        p for p in STANDARD_PRESETS if p.name == "5 x 7 cm" and p.family == "double-sided-fr4"
    )
    document = document_on_preset(
        create_empty_document(DocumentMeta(name="rail", created="", modified="")), preset
    )
    window = _window_on(document)
    try:
        bus = window.bus
        assert bus.dispatch("net.add", AddNetPayload(name="SIG")).ok
        assert bus.dispatch("net.add", AddNetPayload(name="GND", net_class="ground")).ok
        gnd = next(n for n in bus.document.nets if n.name == "GND")
        strip = strip_cells(bus.document, "ec-left")
        second = strip[1]
        # Ground copper already at the hole beside the second finger.
        beside = second.beside
        assert bus.dispatch(
            "conductor.add",
            AddConductorPayload(
                conductor=NewSolderTraceConductor(
                    path=(beside, HoleCoord(beside.col + 1, beside.row)), net_id=gnd.id
                )
            ),
        ).ok

        # The strip's own right-click menu offers it; the bare board beside it does not.
        board = bus.document.board
        on_finger = path_point_to_screen(
            second.cell, board, window.scene.side, finger_cells(bus.document)
        )
        menu = window.board_menu(window.view.mapFromScene(on_finger))
        assert t("Make This Strip a Rail…") in [a.text() for a in menu.actions()]
        middle = window.view.mapFromScene(window.scene.sceneRect().center())
        assert t("Make This Strip a Rail…") not in [
            a.text() for a in window.board_menu(middle).actions()
        ]

        dialog = RailDialog(bus.document, window.lookup, "ec-left", face="bottom")
        assert dialog.net.currentData() == gnd.id
        assert (dialog.start.currentIndex(), dialog.end.currentIndex()) == (0, len(strip) - 1)
        assert dialog.bridge_holes() == [(beside.col, beside.row)]
        assert not dialog.warning.isVisibleTo(dialog)
        dialog.set_bridges([])
        assert dialog.warning.text() == t(
            "A rail with no bridge carries nothing: tick at least one bridge to lay it."
        )
        assert not dialog.ok.isEnabled(), "a rail that carries nothing waits for a bridge"
        dialog.set_bridges([(beside.col, beside.row)])
        assert dialog.ok.isEnabled() and not dialog.warning.isVisibleTo(dialog)
        dialog.set_bridges([])
        # One finger and no bridge is not a rail at all.
        dialog.end.setCurrentIndex(0)
        assert not dialog.ok.isEnabled()
        dialog.end.setCurrentIndex(len(strip) - 1)
        first, last = strip[0], strip[-1]
        dialog.set_bridges([(first.beside.col, first.beside.row), (beside.col, beside.row)])

        steps = len(bus.history())
        before = len(bus.document.conductors)
        window._ask_rail = lambda _c: (dialog.payload(), dialog.span_said())  # type: ignore[method-assign]
        window.on_make_rail("ec-left")
        laid = bus.document.conductors[before:]
        assert len(bus.history()) == steps + 1
        assert len(laid) == 3  # The rail and two bridges.
        assert all(c.net_id == gnd.id and c.side == "bottom" for c in laid)
        assert {laid[0].path[0], laid[0].path[-1]} == {first.cell, last.cell}
        assert dialog.span_said() in window.statusBar().currentMessage()
        window.act_undo.trigger()
        assert len(bus.document.conductors) == before
    finally:
        _close(window)
