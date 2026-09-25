"""A screw terminal of any length, drawn from three slices of KiCad's 3-way block.

A MKDS-1,5 block is a repetition -- an end plate and a first way, N - 2 identical middle
ways, a last way -- and ``tools/import_kicad_models.py`` measured it against KiCad's own
2- to 16-way models before relying on it. That measurement needs KiCad and a STEP reader,
so it is not repeated here. What IS repeated is the half of it that the shipped files can
answer on their own: the three slices, assembled, are the 2-way and 3-way models this
directory already ships, colour by colour. If a reconversion ever cut the slices at the
wrong place, or moved one off its pin, this is where it would show -- rather than as a
terminal with a seam in it on somebody's board.
"""

from __future__ import annotations

import dataclasses

import pytest

from perfboard_studio.footprints import footprint_lookup, get_footprint
from perfboard_studio.model import (
    Board,
    ComponentInstance,
    DocumentMeta,
    HoleCoord,
    PerfDocument,
)

vtk = pytest.importorskip("vtk")

from perfboard_studio.ui import partmodels, view3d  # noqa: E402

PITCH = 5.08  # the block's pitch: two holes of the standard grid

BOARD = Board(
    type="pad-per-hole",
    cols=40,
    rows=30,
    pitch=2.54,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.9,
    drill_diameter=1.0,
)


def _slices() -> tuple[partmodels.PartModel, partmodels.PartModel, partmodels.PartModel]:
    blocks = partmodels.terminal_block_models()
    assert blocks is not None, "the terminal slices are missing from ui/models/"
    return blocks


def _surface(model: partmodels.PartModel, shift: float) -> dict[str, tuple[float, tuple[float, ...]]]:
    """Per colour: surface area, and x/y/z bounds with the slice moved ``shift`` along x."""
    out: dict[str, tuple[float, tuple[float, ...]]] = {}
    for piece in model.pieces:
        mesh = view3d._mesh(str(piece.path))
        mass = vtk.vtkMassProperties()
        triangles = vtk.vtkTriangleFilter()
        triangles.SetInputData(mesh)
        mass.SetInputConnection(triangles.GetOutputPort())
        mass.Update()
        x0, x1, y0, y1, z0, z1 = mesh.GetBounds()
        out[piece.color] = (mass.GetSurfaceArea(), (x0 + shift, x1 + shift, y0, y1, z0, z1))
    return out


def _assembled(ways: int) -> dict[str, tuple[float, tuple[float, ...]]]:
    """head at pin 1, a way at every pin between, tail at the last -- summed per colour."""
    head, way, tail = _slices()
    placed = [(head, 0.0)] + [(way, k * PITCH) for k in range(1, ways - 1)]
    placed.append((tail, (ways - 1) * PITCH))
    total: dict[str, tuple[float, tuple[float, ...]]] = {}
    for model, shift in placed:
        for colour, (area, box) in _surface(model, shift).items():
            if colour not in total:
                total[colour] = (area, box)
                continue
            seen_area, seen = total[colour]
            total[colour] = (
                seen_area + area,
                (min(seen[0], box[0]), max(seen[1], box[1]), min(seen[2], box[2]),
                 max(seen[3], box[3]), min(seen[4], box[4]), max(seen[5], box[5])),
            )
    return total


@pytest.mark.parametrize("ways", (2, 3))
def test_the_slices_assembled_are_the_block_this_directory_ships(ways: int) -> None:
    """Head + (N - 2) ways + tail against the whole 2- and 3-way models, colour by colour:
    the same surface, to a few square micrometres, and the same extent."""
    whole = partmodels.model_for(f"screw-terminal-{ways}")
    assert whole is not None
    expected = _surface(whole, 0.0)
    got = _assembled(ways)
    assert set(got) == set(expected)
    for colour, (area, box) in expected.items():
        assert got[colour][0] == pytest.approx(area, rel=1e-5), colour
        assert got[colour][1] == pytest.approx(box, abs=1e-3), colour


@pytest.mark.parametrize("stem", ("screw-terminal-head", "screw-terminal-way", "screw-terminal-tail"))
def test_every_slice_has_its_wire_entry_on_the_minus_y_face(stem: str) -> None:
    """The same measurement ``test_terminal_entry`` makes on the whole blocks, per way: the
    openings sit a few tenths of a millimetre behind the -y face at the wire channel's
    height, and nothing does behind +y. A slice cut from the wrong face -- or flipped -- would
    draw a terminal with its mouth on the side the rules say is its back."""
    model = partmodels.model_for(stem)
    assert model is not None and model.body is not None
    mesh = view3d._mesh(str(model.body.path))
    points = [mesh.GetPoint(index) for index in range(mesh.GetNumberOfPoints())]
    front = min(point[1] for point in points)
    back = max(point[1] for point in points)

    def recessed(face_distance) -> int:
        return sum(1 for _x, y, z in points if 2.0 < z < 6.0 and 0.2 < face_distance(y) < 1.0)

    assert recessed(lambda y: y - front) > 10
    assert recessed(lambda y: back - y) == 0


def _slice_ids() -> set[int]:
    """The three slices' cached meshes, by identity -- a VTK object is not hashable."""
    return {id(view3d._mesh(str(piece.path))) for model in _slices() for piece in model.pieces}


def _pieces(footprint_id: str, rotation: int = 0, mirrored: bool = False):
    component = ComponentInstance(
        id="cmp-1",
        ref="J1",
        value="",
        footprint_id=footprint_id,
        anchor=HoleCoord(12, 12),
        rotation=rotation,  # type: ignore[arg-type]
        mirrored=mirrored,
    )
    document = PerfDocument(
        meta=DocumentMeta(name="t", created="", modified=""), board=BOARD, components=(component,)
    )
    lookup = footprint_lookup()
    body = view3d._world_body(lookup, component, document.board)
    assert body is not None
    footprint = get_footprint(footprint_id)
    return body, view3d._pieces_for(body, footprint, component, document.board)


@pytest.mark.parametrize("ways", (4, 6, 16))
def test_a_terminal_with_no_model_of_its_own_is_built_from_the_slices(ways: int) -> None:
    """``screw-terminal-4``, ``-6``: generated ids no single model could be named for. They
    used to be a flat box with the openings and screws painted on; now a head, N - 2 ways and
    a tail, each at its own pin -- and none of the generated body's painted openings."""
    head, way, tail = _slices()
    body, pieces = _pieces(f"screw-terminal-{ways}")
    sources = [piece.source for piece in pieces]
    for model, count in ((head, 1), (way, ways - 2), (tail, 1)):
        for piece in model.pieces:
            assert sum(1 for s in sources if s is view3d._mesh(str(piece.path))) == count
    # The generated body's openings are near-black glossy boxes; a meshed block has none.
    dark = view3d._rgb("#121212")
    assert not any(piece.rgb == dark for piece in pieces)
    # Every slice stands on a pin, and every pin has one.
    slice_ids = _slice_ids()
    placed = {
        (round(p.position[0], 6), round(p.position[1], 6))
        for p in pieces
        if id(p.source) in slice_ids
    }
    assert placed == {(round(x, 6), round(y, 6)) for x, y in body.pins}


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
@pytest.mark.parametrize("mirrored", (False, True))
def test_a_turned_or_mirrored_block_puts_its_head_on_pin_one(rotation: int, mirrored: bool) -> None:
    """The head carries the end plate, so it is the one slice whose place shows: it has to be
    on pin 1 whichever way the part was turned, and every slice takes the part's own turn and
    mirror -- as a whole package does in ``_model_pieces``."""
    head, _way, tail = _slices()
    body, pieces = _pieces("screw-terminal-5", rotation, mirrored)
    head_mesh = view3d._mesh(str(head.pieces[0].path))
    tail_mesh = view3d._mesh(str(tail.pieces[0].path))
    head_piece = next(p for p in pieces if p.source is head_mesh)
    tail_piece = next(p for p in pieces if p.source is tail_mesh)
    assert head_piece.position[:2] == pytest.approx(body.pins[0])
    assert tail_piece.position[:2] == pytest.approx(body.pins[-1])
    slice_ids = _slice_ids()
    meshed = [p for p in pieces if id(p.source) in slice_ids]
    assert meshed and all(p.orientation == (0.0, 0.0, -float(rotation)) for p in meshed)
    expected_scale = (-1.0, 1.0, 1.0) if mirrored else (1.0, 1.0, 1.0)
    assert head_piece.scale == expected_scale


def test_the_two_and_three_way_blocks_keep_their_own_models() -> None:
    """The whole models stay the answer where they exist: nothing about a 2- or 3-way block
    moved, so no render golden did."""
    for ways in (2, 3):
        whole = partmodels.model_for(f"screw-terminal-{ways}")
        assert whole is not None
        _body, pieces = _pieces(f"screw-terminal-{ways}")
        whole_ids = {id(view3d._mesh(str(piece.path))) for piece in whole.pieces}
        assert {id(p.source) for p in pieces} >= whole_ids
        assert not {id(p.source) for p in pieces} & _slice_ids()


def test_without_the_slices_a_long_terminal_is_the_generated_body_again(monkeypatch) -> None:
    """The fallback every borrowed shape keeps: a build without the meshes still draws the
    terminal, as the block it always was."""
    monkeypatch.setattr(view3d, "terminal_block_models", lambda: None)
    _body, pieces = _pieces("screw-terminal-6")
    assert any(piece.rgb == view3d._rgb("#121212") for piece in pieces)


def test_the_slices_are_not_footprints() -> None:
    """They are parts of a package, like the header pin -- not something a board can place."""
    for stem in (partmodels.TERMINAL_HEAD, partmodels.TERMINAL_WAY, partmodels.TERMINAL_TAIL):
        assert get_footprint(stem) is None
    assert dataclasses.is_dataclass(partmodels.PartModel)
