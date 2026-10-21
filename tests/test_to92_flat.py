"""A TO-92's case is a D with its flat on local +y, in the 2D view and the 3D view alike --
and a mirrored borrowed package is not drawn inside out.

The flat is the only thing on a TO-92 that says which way round it goes. The 2D view drew an
ellipse, the 3D fallback chose the flat's side from the pin axis alone (backwards at 0 and
270 degrees), and only the borrowed KiCad mesh had it right. ``bodies.flat_face_profile`` is
now the one D both views draw, and these tests measure where the flat IS rather than trusting
the code that put it there.
"""

from __future__ import annotations

import os
from itertools import pairwise

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    DEFAULT_BOARD,
    PlaceComponentPayload,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.footprints import footprint_lookup, get_footprint
from perfboard_studio.model import DocumentMeta, HoleCoord, PerfDocument
from perfboard_studio.ui.bodies import flat_face_profile, placement_for

LOOKUP = footprint_lookup()

#: Where local +y -- a row further DOWN the footprint -- points in the 3D world (x with the
#: column, y up-negative) after a quarter turn CLOCKWISE seen from above, written out by hand
#: rather than computed: mirroring reflects local x and leaves local +y where it was.
WORLD_OF_LOCAL_PLUS_Y = {0: (0.0, -1.0), 90: (-1.0, 0.0), 180: (0.0, 1.0), 270: (1.0, 0.0)}


def _board_with(footprint_id: str, rotation: int = 0, mirrored: bool = False) -> PerfDocument:
    document = PerfDocument(meta=DocumentMeta(name="t", created="", modified=""), board=DEFAULT_BOARD)
    bus = CommandBus(
        document,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(document)),
    )
    result = bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref="Q1",
            value="",
            footprint_id=footprint_id,
            anchor=HoleCoord(12, 12),
            rotation=rotation,  # type: ignore[arg-type]
            mirrored=mirrored,
        ),
    )
    assert result.ok, result.message
    return bus.document


@pytest.mark.parametrize("keyed", [None, (0.0, 0.0)], ids=["unkeyed", "keyed"])
def test_a_to92_is_a_d_in_2d_with_its_flat_on_local_plus_y(keyed) -> None:  # type: ignore[no-untyped-def]
    """Round on local -y, cut flat on local +y, whatever ``keyed`` says: the flat is the
    moulding, so the solder-side shadow (drawn unkeyed) has it too. The painter turns and
    mirrors the footprint frame with the part, so the frame is all there is to check."""
    from perfboard_studio.ui.view2d import _body_path

    footprint = get_footprint("to92")
    assert footprint is not None
    placement = placement_for(footprint, DEFAULT_BOARD.pitch)
    profile = flat_face_profile(placement.size_x, placement.size_y)
    box = _body_path(footprint, placement, keyed).boundingRect()

    assert profile.flat < profile.radius, "a D, not a circle"
    assert box.width() == pytest.approx(2 * profile.radius, abs=1e-6)
    assert box.top() == pytest.approx(placement.centre_y - profile.radius, abs=1e-6)
    assert box.bottom() == pytest.approx(placement.centre_y + profile.flat, abs=1e-6)


@pytest.mark.parametrize("meshes", [True, False], ids=["mesh", "fallback"])
@pytest.mark.parametrize("mirrored", [False, True], ids=["plain", "mirrored"])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_a_to92s_flat_is_on_local_plus_y_in_3d_at_every_turn(  # type: ignore[no-untyped-def]
    rotation: int, mirrored: bool, meshes: bool, monkeypatch
) -> None:
    """Measured on the built solids: the case reaches less far from the pin row towards
    local +y than away from it, for KiCad's mesh and for the generated fallback, at every
    turn, mirrored or not."""
    from perfboard_studio.ui import partmodels, view3d

    if meshes and partmodels.model_for("to92") is None:
        pytest.skip("this build has no borrowed meshes")
    if not meshes:
        monkeypatch.setattr(partmodels, "_index", lambda: {})
    document = _board_with("to92", rotation, mirrored)
    component = document.components[0]
    body = view3d._world_body(LOOKUP, component, document.board)
    assert body is not None

    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for actor in view3d.build_component(LOOKUP, component, document.board):
        bounds = actor.GetBounds()
        if bounds[5] < 1.0:
            continue  # A lead in its hole, not the case.
        x0, x1 = min(x0, bounds[0]), max(x1, bounds[1])
        y0, y1 = min(y0, bounds[2]), max(y1, bounds[3])
    reach = {(1.0, 0.0): x1 - body.x, (-1.0, 0.0): body.x - x0, (0.0, 1.0): y1 - body.y, (0.0, -1.0): body.y - y0}

    towards = WORLD_OF_LOCAL_PLUS_Y[rotation]
    away = (-towards[0], -towards[1])
    assert reach[towards] < reach[away] - 0.4, (
        f"the flat should face {towards}: the case reaches {reach[towards]:.2f} mm that way "
        f"and {reach[away]:.2f} mm the other"
    )


def _determinant(actor) -> float:  # type: ignore[no-untyped-def]
    return float(actor.GetMatrix().Determinant())


def _winding_agrees_with_normals(data) -> float:  # type: ignore[no-untyped-def]
    """The fraction of triangles whose winding points the same way as their point normals:
    1.0 for a solid seen from outside, 0.0 for one turned inside out."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy

    normals = data.GetPointData().GetNormals()
    if normals is None or data.GetNumberOfPolys() == 0:
        return 1.0
    points = vtk_to_numpy(data.GetPoints().GetData())
    normal = vtk_to_numpy(normals)
    cells = vtk_to_numpy(data.GetPolys().GetConnectivityArray())
    offsets = vtk_to_numpy(data.GetPolys().GetOffsetsArray())
    agree = total = 0
    for start, end in pairwise(offsets):
        if end - start != 3:
            continue
        a, b, c = cells[start:end]
        face = np.cross(points[b] - points[a], points[c] - points[a])
        if np.linalg.norm(face) < 1e-12:
            continue
        total += 1
        agree += float(np.dot(face, normal[a] + normal[b] + normal[c])) > 0
    return agree / total if total else 1.0


def test_no_borrowed_package_is_drawn_inside_out_when_it_is_mirrored() -> None:
    """A mirrored part was an actor scaled by -1 in x, and a reflection reverses every
    triangle's winding: the camera saw back faces, two-sided lighting turned their normals
    round, and the part was lit from inside -- a mirrored TO-92 at 23 grey levels against 64.
    Now no actor reflects, and the reflected mesh still winds the way its normals point."""
    from perfboard_studio.ui import partmodels, view3d

    ids = sorted(id_ for id_ in partmodels._index() if get_footprint(id_) is not None)
    if not ids:
        pytest.skip("this build has no borrowed meshes")
    # And a terminal assembled from the three slices, which has no model of its own.
    ids.append("screw-terminal-4")
    for footprint_id in ids:
        for mirrored in (False, True):
            document = _board_with(footprint_id, rotation=90, mirrored=mirrored)
            for actor in view3d.build_component(LOOKUP, document.components[0], document.board):
                assert _determinant(actor) > 0, f"{footprint_id} mirrored={mirrored}: an actor reflects"
                mapper = actor.GetMapper()
                if not hasattr(mapper, "GetInput"):
                    continue
                mapper.Update()
                data = mapper.GetInput()
                if data is None or data.GetNumberOfPolys() < 20:
                    continue
                share = _winding_agrees_with_normals(data)
                assert share > 0.97, f"{footprint_id} mirrored={mirrored}: {share:.0%} of faces wind outward"
