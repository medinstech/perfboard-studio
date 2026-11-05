"""Wire-to-board headers: JST XH (top and side entry) and Molex KK 254 / KF2510.

What is pinned:

- the XH's pin count is the ARITHMETIC of its 2.50 mm pitch in the stock boards' 2.54 mm
  holes, not a number somebody chose: tied to every stock board family's drill, so a board
  drilled otherwise moves the limit with it;
- each footprint is its family's measured body, pin 1 at the origin on the grid;
- the catalog offers exactly the counts that go in, found by every name a buyer uses, in
  either language;
- a JST series that does not fit a perfboard is answered, not left as an empty search:
  ``catalog.not_offered``, matched on the series with "JST" or its pitch and never on two
  letters "phone" starts with too;
- the meshes: XH whole per count, KK 254 from three slices of the 3-pin one.
"""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from perfboard_studio.boardfamily import FAMILIES
from perfboard_studio.catalog import CATALOG, NOT_OFFERED, catalog_part, not_offered, search_catalog
from perfboard_studio.footprints import (
    STOCK_DRILL_MM,
    WIRE_TO_BOARD_FAMILIES,
    WIRE_TO_BOARD_POST_MM,
    get_footprint,
    pins_on_the_grid,
)
from perfboard_studio.model import STANDARD_PITCH_MM


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _drills() -> set[float]:
    return {family.drill_mm for family in FAMILIES}


def test_the_stock_drill_is_every_stock_boards() -> None:
    """``STOCK_DRILL_MM`` is what the families are sold with. A family drilled otherwise
    fails this, and with it the XH limit below, rather than drawing a part that does not go in."""
    assert _drills() == {STOCK_DRILL_MM}


def test_the_xh_count_is_the_arithmetic_of_its_pitch_in_the_holes() -> None:
    drill = min(_drills())
    post = WIRE_TO_BOARD_POST_MM
    # How far a square post may stand off a round hole's centre along the row.
    slack = math.sqrt((drill / 2) ** 2 - (post / 2) ** 2) - post / 2
    error = STANDARD_PITCH_MM - 2.50
    fits = [n for n in range(2, 12) if (n - 1) * error / 2 <= slack]
    assert max(fits) == pins_on_the_grid(2.50, drill) == 4
    for family in ("jst-xh", "jst-xh-side"):
        assert WIRE_TO_BOARD_FAMILIES[family].max_pins == max(fits)
    # Off by one either way it is the wrong answer, so the boundary is said in numbers.
    assert 3 * error / 2 <= slack < 4 * error / 2
    # A board drilled 1.1 mm would take seven: the limit is the hole's, not the part's.
    assert pins_on_the_grid(2.50, 1.1) == 7


def test_a_header_is_its_familys_measured_body_on_the_grid() -> None:
    for family, spec in WIRE_TO_BOARD_FAMILIES.items():
        for pins in range(spec.min_pins, spec.max_pins + 1):
            fid = f"jst-xh-{pins}-side" if family == "jst-xh-side" else f"{family}-{pins}"
            footprint = get_footprint(fid)
            assert footprint is not None, fid
            assert footprint.body.archetype == "wire-to-board"
            assert [(p.d_col, p.d_row) for p in footprint.pins] == [(i, 0) for i in range(pins)]
            dims = footprint.body.dims
            assert dims["length"] == pytest.approx(spec.pitch_mm * (pins - 1) + spec.end_mm)
            assert (dims["width"], dims["height"]) == (spec.depth_mm, spec.height_mm)
            assert footprint.body_height == spec.height_mm
    # Past the counts that go in there is no such part.
    for fid in ("jst-xh-1", "jst-xh-5", "jst-xh-5-side", "kk254-1", "kk254-17", "jst-xh-02"):
        assert get_footprint(fid) is None, fid


def test_the_catalog_offers_exactly_what_goes_in() -> None:
    xh = {part.id for part in CATALOG if part.footprint_id.startswith("jst-xh-")}
    limit = WIRE_TO_BOARD_FAMILIES["jst-xh"].max_pins
    assert xh == {f"jst-xh-{n}{side}" for n in range(2, limit + 1) for side in ("", "-side")}
    kk = {part.id for part in CATALOG if part.footprint_id.startswith("kk254-")}
    assert kk == {f"kk254-{n}" for n in (2, 3, 4, 5, 6, 8)}
    for part_id in xh | kk:
        part = catalog_part(part_id)
        assert part is not None and part.footprint_id == part_id and part.reference_prefix == "J"


@pytest.mark.parametrize(
    ("query", "family"),
    [
        ("JST", "jst-xh-"), ("XH", "jst-xh-"), ("JST XH", "jst-xh-"), ("XH2.54", "jst-xh-"),
        ("B3B-XH-A", "jst-xh-3"), ("konnektör", "jst-xh-"), ("JST konnektör", "jst-xh-"),
        ("KF2510", "kk254-"), ("Molex", "kk254-"), ("KK 254", "kk254-"), ("KF2510-4A", "kk254-4"),
        ("22-27-2061", "kk254-6"),
    ],
)
def test_search_finds_a_header_by_every_name_it_is_sold_by(query: str, family: str) -> None:
    found = search_catalog(query)
    assert found and found[0].id.startswith(family), (query, [p.id for p in found[:3]])


@pytest.mark.parametrize(
    "query", ["JST PH", "jst-ph", "PH2.0", "ph 2", "JST ZH", "zh1.5", "JST SH", "SH1.0", "JST VH", "VH3.96"]
)
def test_a_jst_that_does_not_fit_a_perfboard_is_answered(query: str) -> None:
    answer = not_offered(query)
    assert answer is not None, query
    assert answer.instead and all(catalog_part(part_id) is not None for part_id in answer.instead)


@pytest.mark.parametrize("query", ["PH", "phone", "photo", "SH", "shift register", "JST", "JST XH", "VH"])
def test_nothing_else_is_answered_as_not_offered(query: str) -> None:
    assert not_offered(query) is None, query


def test_every_not_offered_reason_names_its_series_and_an_offered_part() -> None:
    for series, pitch, answer in NOT_OFFERED:
        assert f"JST {series.upper()}" in answer.reason and pitch in answer.reason


def test_every_part_a_refused_family_offers_instead_is_in_the_catalog() -> None:
    """Walked over the table itself, not over the queries above: a family added to
    ``NOT_OFFERED`` with no query in that list is held to it too. The Library drops an id it
    cannot find, so a typo or a renamed part would otherwise shrink "Offered instead" to
    nothing without a word."""
    ids = {part.id for part in CATALOG}
    for series, _pitch, answer in NOT_OFFERED:
        assert answer.instead, series
        assert len(set(answer.instead)) == len(answer.instead), (series, answer.instead)
        missing = [part_id for part_id in answer.instead if part_id not in ids]
        assert not missing, (series, missing)


def test_a_jst_with_a_named_lead_and_a_value_plugs_in_on_a_cable() -> None:
    """A JST XH is where a module's cable latches on, as a pin header is: named, the guide
    says what plugs in and where each lead goes."""
    from perfboard_studio.guide import plugs_in_on_a_cable
    from perfboard_studio.model import ComponentInstance, HoleCoord

    footprint = get_footprint("jst-xh-3")
    assert footprint is not None
    plain = ComponentInstance(
        id="c1", ref="J1", value="", footprint_id="jst-xh-3", anchor=HoleCoord(2, 2)
    )
    assert not plugs_in_on_a_cable(plain, footprint)
    named = ComponentInstance(
        id="c1", ref="J1", value="Fan", footprint_id="jst-xh-3", anchor=HoleCoord(2, 2),
        pin_names=(("1", "GND"), ("2", "+12V"), ("3", "TACH")),
    )
    assert plugs_in_on_a_cable(named, footprint)


def test_xh_has_a_mesh_per_count_and_kk_is_drawn_from_three_slices() -> None:
    from perfboard_studio.ui import partmodels
    from perfboard_studio.ui.topview import top_view

    for pins in (2, 3, 4):
        for fid in (f"jst-xh-{pins}", f"jst-xh-{pins}-side"):
            assert partmodels.model_for(fid) is not None, fid
    for pins in range(2, 17):
        assert partmodels.wire_to_board_slices(f"kk254-{pins}") is not None
        footprint = get_footprint(f"kk254-{pins}")
        assert footprint is not None
        assert top_view(footprint, STANDARD_PITCH_MM).source != "parametric"
    assert partmodels.wire_to_board_slices("jst-xh-3") is None


def test_pin_1_is_marked_as_a_keyed_parts_is() -> None:
    """The housing takes its plug one way round, so pin 1 is drawn brighter, in 2D and 3D,
    as a DIP's is."""
    from perfboard_studio.ui.bodies import polarity_pin_offset

    for fid in ("jst-xh-2", "jst-xh-4-side", "kk254-8"):
        footprint = get_footprint(fid)
        assert footprint is not None
        assert polarity_pin_offset(footprint, STANDARD_PITCH_MM) == (0.0, 0.0), fid


def _mesh(path: object) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    import struct
    from pathlib import Path

    data = Path(str(path)).read_bytes()
    marker = b"end_header" + bytes([10])
    end = data.index(marker) + len(marker)
    head = data[:end].decode("ascii").splitlines()
    vertices = next(int(line.split()[2]) for line in head if line.startswith("element vertex"))
    count = next(int(line.split()[2]) for line in head if line.startswith("element face"))
    points = [struct.unpack_from("<3f", data, end + 12 * i) for i in range(vertices)]
    faces, at = [], end + 12 * vertices
    for _ in range(count):
        n = data[at]
        faces.append(struct.unpack_from(f"<{n}i", data, at + 1))
        at += 1 + 4 * n
    return points, faces


def _height_under(pieces: list, x: float, y: float) -> float | None:  # type: ignore[type-arg]
    """The highest point of the meshes straight over (x, y), in the mesh's own frame."""
    best = None
    for points, faces in pieces:
        for face in faces:
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = (points[i] for i in face[:3])
            d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(d) < 1e-12:
                continue
            l1 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / d
            l2 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / d
            if min(l1, l2, 1 - l1 - l2) < -1e-9:
                continue
            z = l1 * az + l2 * bz + (1 - l1 - l2) * cz
            best = z if best is None else max(best, z)
    return best


@pytest.mark.parametrize(
    ("footprint_id", "model_id"),
    [("jst-xh-2", "jst-xh-2"), ("jst-xh-3-side", "jst-xh-3-side"), ("kk254-4", "kk254-head")],
)
def test_pin_1s_mark_in_3d_lies_on_the_housings_top(footprint_id: str, model_id: str) -> None:
    """The meshes mark nothing, so ``view3d`` presses a dimple into the housing's top by pin
    1 (``markX``/``markY``). Placed by eye it floated: on a side entry's mouth, over a KK's
    sloping ramp. The disc it is drawn as lies wholly on the top, at the body's height."""
    from perfboard_studio.ui import partmodels

    footprint = get_footprint(footprint_id)
    model = partmodels.model_for(model_id)
    assert footprint is not None and model is not None
    pieces = [_mesh(piece.path) for piece in model.pieces if piece.is_body]
    x, y = footprint.body.dims["markX"], footprint.body.dims["markY"]
    for dx, dy in ((0, 0), (0.35, 0), (-0.35, 0), (0, 0.35), (0, -0.35)):
        # The mesh's y runs against the row: our +y is its -y.
        z = _height_under(pieces, x + dx, -(y + dy))
        assert z is not None and z == pytest.approx(footprint.body_height, abs=0.05), (dx, dy, z)
