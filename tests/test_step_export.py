"""The board as a STEP file (``step_export.py``).

Nothing on CI can open a STEP file, so the structure is checked here by reading the text
back: every reference resolves, every face's edge loop closes, and every closed shell uses
each of its edges exactly twice, once each way -- the property that makes a set of faces
a solid rather than a surface with a hole in it, and the one a hand-written B-rep gets
wrong first. The last test hands the file to OpenCASCADE, the kernel FreeCAD and KiCad read
STEP with, when it is installed (``pip install cadquery-ocp``); it is not a dependency.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.drc import placed_body_box
from perfboard_studio.footprints import (
    LEAD_TRIM_MM,
    footprint_lookup,
    get_footprint,
    standard_footprints,
)
from perfboard_studio.geometry import (
    all_pin_holes,
    board_outline_mm,
    hole_key,
    hole_to_mm,
    undrilled_holes,
)
from perfboard_studio.model import (
    HoleCoord,
    MountingHole,
    PerfDocument,
    WireConductor,
    contacts_every_path_hole,
)
from perfboard_studio.occupancy import stacking_layers
from perfboard_studio.step_export import (
    MIN_WEB_MM,
    ROUND_ARCHETYPES,
    SLEEVED_KINDS,
    WIRES_NAME,
    Box,
    Cylinder,
    Palette,
    Plate,
    board_model,
    document_to_step,
    step_string,
    wire_radius_mm,
)
from perfboard_studio.wiregauge import INSULATION_WALL_MM, awg_diameter_mm

ROOT = Path(__file__).resolve().parents[1]
BOARDS = sorted(
    [*(ROOT / "tools" / "diffcheck" / "golden").glob("*.perf"), *(ROOT / "examples").glob("*.perf")]
)
STAMP = "2026-10-06T12:00:00"


def _load(path: Path) -> PerfDocument:
    return persist.parse_document_or_throw(path.read_text(encoding="utf-8"))


def _example(name: str) -> PerfDocument:
    return _load(ROOT / "examples" / f"{name}.perf")


def _entities(text: str) -> dict[int, str]:
    data = text.split("DATA;\n", 1)[1].split("ENDSEC;", 1)[0]
    entities: dict[int, str] = {}
    for line in data.splitlines():
        match = re.fullmatch(r"#(\d+)=(.*);", line)
        assert match, f"not one entity per line: {line!r}"
        entities[int(match[1])] = match[2]
    return entities


def _refs(entity: str) -> list[int]:
    return [int(n) for n in re.findall(r"#(\d+)", entity)]


def _kind(entity: str) -> str:
    return entity.split("(", 1)[0]


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.stem)
def test_every_board_in_the_repository_is_a_well_formed_step_file(path: Path) -> None:
    text = document_to_step(_load(path), footprint_lookup(), timestamp=STAMP)

    assert text.isascii()
    assert text.startswith("ISO-10303-21;\nHEADER;\n")
    assert "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));" in text
    assert text.endswith("ENDSEC;\nEND-ISO-10303-21;\n")
    entities = _entities(text)
    assert sorted(entities) == list(range(1, len(entities) + 1))
    dangling = {ref for entity in entities.values() for ref in _refs(entity)} - set(entities)
    assert not dangling


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.stem)
def test_every_shell_is_closed_and_every_loop_joins_up(path: Path) -> None:
    """Each face's loop runs end to start, and each edge of a closed shell is used exactly
    twice, in opposite directions. Together that is a closed, consistently oriented
    surface: a solid, and one that is not inside out on half its faces."""
    entities = _entities(document_to_step(_load(path), footprint_lookup(), timestamp=STAMP))

    def ends(oriented: int) -> tuple[int, int]:
        edge, forward = _refs(entities[oriented])[0], entities[oriented].endswith(".T.)")
        start, end = _refs(entities[edge])[:2]
        return (start, end) if forward else (end, start)

    shells = [n for n, entity in entities.items() if _kind(entity) == "CLOSED_SHELL"]
    assert shells
    for shell in shells:
        uses: Counter[tuple[int, bool]] = Counter()
        for face in _refs(entities[shell]):
            assert _kind(entities[face]) == "ADVANCED_FACE"
            for bound in _refs(entities[face])[:-1]:
                loop = _refs(entities[bound])[0]
                oriented = _refs(entities[loop])
                for here, after in zip(oriented, oriented[1:] + oriented[:1], strict=True):
                    assert ends(here)[1] == ends(after)[0], f"loop #{loop} does not join up"
                    uses[(_refs(entities[here])[0], entities[here].endswith(".T.)"))] += 1
        edges = {edge for edge, _ in uses}
        for edge in edges:
            assert uses[(edge, True)] == 1 and uses[(edge, False)] == 1, (
                f"edge #{edge} of shell #{shell} is used {uses[(edge, True)]} time(s) forward "
                f"and {uses[(edge, False)]} back"
            )


def test_the_same_board_is_the_same_file() -> None:
    doc = _example("atmega328-relay")
    lookup = footprint_lookup()
    assert document_to_step(doc, lookup, timestamp=STAMP) == document_to_step(
        doc, lookup, timestamp=STAMP
    )


def test_the_assembly_names_the_board_and_every_part_by_reference() -> None:
    doc = _example("ne555-astable")
    entities = _entities(document_to_step(doc, footprint_lookup(), timestamp=STAMP))
    products = [
        re.match(r"PRODUCT\('(.*?)'", entity)[1]  # type: ignore[index]
        for entity in entities.values()
        if _kind(entity) == "PRODUCT"
    ]
    assert products == [doc.meta.name, "Board", *(c.ref for c in doc.components), WIRES_NAME]
    usages = [e for e in entities.values() if _kind(e) == "NEXT_ASSEMBLY_USAGE_OCCURRENCE"]
    assert len(usages) == len(products) - 1


def test_every_solid_is_coloured() -> None:
    entities = _entities(
        document_to_step(_example("nano-relay"), footprint_lookup(), timestamp=STAMP)
    )
    solids = {n for n, e in entities.items() if _kind(e) == "MANIFOLD_SOLID_BREP"}
    styled = {_refs(e)[-1] for e in entities.values() if _kind(e) == "STYLED_ITEM"}
    assert solids and solids == styled


def test_text_outside_ascii_is_escaped_rather_than_written() -> None:
    """A STEP file is ASCII; "Röle" written as UTF-8 arrives in a CAD program as mojibake."""
    assert step_string("Röle kartı") == "'R\\X2\\00F6\\X0\\le kart\\X2\\0131\\X0\\'"
    assert step_string("it's") == "'it''s'"
    assert step_string("a\\b") == "'a\\\\b'"
    assert step_string("ÇĞ") == "'\\X2\\00C7011E\\X0\\'"

    doc = _example("ne555-astable")
    doc = replace(doc, meta=replace(doc.meta, name="Zamanlayıcı kartı"))
    text = document_to_step(doc, footprint_lookup(), timestamp=STAMP)
    assert text.isascii()
    assert "Zamanlay\\X2\\0131\\X0\\c\\X2\\0131\\X0\\ kart\\X2\\0131\\X0\\" in text


# ---------------------------------------------------------------------------
# What it describes
# ---------------------------------------------------------------------------


def test_the_board_is_the_substrate_drilled_where_it_has_holes() -> None:
    doc = _example("atmega328-relay")
    board = doc.board
    plate = board_model(doc, footprint_lookup())[0].solids[0].shape
    assert isinstance(plate, Plate)

    outline = board_outline_mm(board)
    assert plate.low == (0.0, 0.0, 0.0)
    assert plate.high == (outline.width, outline.height, board.thickness)
    bores = [h for h in plate.holes if h[2] != board.drill_diameter / 2]
    assert len(bores) == len(doc.mounting_holes)
    grid = [h for h in plate.holes if h[2] == board.drill_diameter / 2]
    assert len(grid) <= board.cols * board.rows - len(undrilled_holes(doc))
    for index, (x, y, r) in enumerate(plate.holes):
        assert x - r >= MIN_WEB_MM and x + r <= outline.width - MIN_WEB_MM
        assert y - r >= MIN_WEB_MM and y + r <= outline.height - MIN_WEB_MM
        for x2, y2, r2 in plate.holes[index + 1 :]:
            assert math.hypot(x - x2, y - y2) >= r + r2 + MIN_WEB_MM


def test_a_bore_on_the_grid_takes_the_hole_under_it_and_spares_its_neighbours() -> None:
    doc = _example("ne555-astable")
    board = doc.board
    at = HoleCoord(2, 10)
    doc = replace(doc, mounting_holes=(MountingHole(id="m-test", at=at),))
    plate = board_model(doc, footprint_lookup())[0].solids[0].shape
    assert isinstance(plate, Plate)
    outline = board_outline_mm(board)

    def drilled(coord: HoleCoord) -> bool:
        centre = hole_to_mm(coord, board)
        x, y = centre.x - outline.x, outline.y + outline.height - centre.y
        return any(
            math.isclose(x, hx) and math.isclose(y, hy) and r == board.drill_diameter / 2
            for hx, hy, r in plate.holes
        )

    assert not drilled(at)
    # An M3 clearance hole is 3.2 mm across: the four holes a pitch away keep a wall.
    for d_col, d_row in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        assert drilled(HoleCoord(at.col + d_col, at.row + d_row))


def test_a_finger_is_not_drilled() -> None:
    doc = _example("lpb1-booster")
    undrilled = undrilled_holes(doc)
    assert undrilled
    plate = board_model(doc, footprint_lookup())[0].solids[0].shape
    assert isinstance(plate, Plate)
    grid = [h for h in plate.holes if h[2] == doc.board.drill_diameter / 2]
    assert len(grid) == doc.board.cols * doc.board.rows - len(undrilled)


@pytest.mark.parametrize("name", ["atmega328-relay", "nano-relay", "lm317-supply"])
def test_every_part_is_the_body_drc_measures(name: str) -> None:
    """The outline is ``drc.placed_body_box`` and the height ``Footprint.body_height`` --
    the numbers ``component-overhangs-edge`` and ``component-too-tall`` judged. An
    enclosure drawn round anything else could disagree with the checker about whether
    the board fits in it."""
    doc = _example(name)
    lookup = footprint_lookup()
    board = doc.board
    outline = board_outline_mm(board)
    parts = [part for part in board_model(doc, lookup)[1:] if part.name != WIRES_NAME]
    placed = [c for c in doc.components if lookup(c.footprint_id) is not None]
    assert [part.name for part in parts] == [c.ref for c in placed]

    for comp, part in zip(placed, parts, strict=True):
        footprint = lookup(comp.footprint_id)
        assert footprint is not None
        min_x, max_x, min_y, max_y = placed_body_box(comp, footprint, board)
        expected = (
            min_x - outline.x,
            outline.y + outline.height - max_y,
            max_x - outline.x,
            outline.y + outline.height - min_y,
        )
        body = part.solids[0].shape
        top = board.thickness + footprint.body_height
        if isinstance(body, Box):
            assert (body.low[0], body.low[1], body.high[0], body.high[1]) == pytest.approx(expected)
            assert body.low[2] == board.thickness
            assert body.high[2] == pytest.approx(top)
        else:
            assert isinstance(body, Cylinder)
            lows = [min(body.base[i], body.base[i] + body.axis[i] * body.length) for i in range(3)]
            highs = [max(body.base[i], body.base[i] + body.axis[i] * body.length) for i in range(3)]
            for i in range(3):
                if body.axis[i] == 0:
                    lows[i] -= body.radius
                    highs[i] += body.radius
            # A round body fits inside the box; a barrel fills it along its own length.
            assert lows[0] >= expected[0] - 1e-9 and highs[0] <= expected[2] + 1e-9
            assert lows[1] >= expected[1] - 1e-9 and highs[1] <= expected[3] + 1e-9
            if body.axis == (0.0, 0.0, 1.0):
                assert body.base[2] == board.thickness
                assert highs[2] == pytest.approx(top)
            else:
                # Lying down, resting on the board if the registry's height is less than
                # the barrel's own diameter.
                assert highs[2] == pytest.approx(max(top, board.thickness + 2 * body.radius))


def test_every_lead_goes_down_a_drilled_hole_and_out_past_the_solder_side() -> None:
    doc = _example("atmega328-relay")
    lookup = footprint_lookup()
    board = doc.board
    model = board_model(doc, lookup)
    plate = model[0].solids[0].shape
    assert isinstance(plate, Plate)
    holes = {(round(x, 6), round(y, 6)) for x, y, _r in plate.holes}

    upright = [
        solid.shape
        for part in model[1:]
        if part.name != WIRES_NAME
        for solid in part.solids[1:]
        if isinstance(solid.shape, Cylinder) and solid.shape.axis == (0.0, 0.0, 1.0)
    ]
    expected = sum(
        1
        for comp in doc.components
        if (footprint := lookup(comp.footprint_id)) is not None
        for _pin, hole in all_pin_holes(comp, footprint)
        if hole_key(hole) not in undrilled_holes(doc)
    )
    assert len(upright) == expected
    for lead in upright:
        assert (round(lead.base[0], 6), round(lead.base[1], 6)) in holes
        assert lead.base[2] == -LEAD_TRIM_MM
        assert lead.base[2] + lead.length >= board.thickness
        assert lead.radius < board.drill_diameter / 2


def test_the_round_bodies_are_the_round_courtyards() -> None:
    """A cylinder exactly where ``footprints._circle_outline`` drew the courtyard round."""
    for footprint in standard_footprints().values():
        round_courtyard = len(footprint.body_outline) > 4
        assert round_courtyard == (footprint.body.archetype in ROUND_ARCHETYPES), footprint.id


def test_the_palette_colours_each_part_from_its_own_footprint() -> None:
    doc = _example("ne555-astable")
    palette = Palette(
        board=(0.1, 0.2, 0.3),
        lead=(0.4, 0.5, 0.6),
        body=lambda fp: (0.9, 0.0, 0.0) if fp.body.archetype == "dip" else (0.0, 0.9, 0.0),
    )
    model = board_model(doc, footprint_lookup(), palette)
    assert model[0].solids[0].rgb == (0.1, 0.2, 0.3)
    for comp, part in zip(doc.components, model[1:-1], strict=True):
        dip = get_footprint(comp.footprint_id).body.archetype == "dip"  # type: ignore[union-attr]
        assert part.solids[0].rgb == ((0.9, 0.0, 0.0) if dip else (0.0, 0.9, 0.0))
        assert all(solid.rgb == (0.4, 0.5, 0.6) for solid in part.solids[1:])
    # Without a ``wire`` answer, a sleeve is ``sleeve`` and bare wire is ``lead``.
    assert model[-1].name == WIRES_NAME
    assert {solid.rgb for solid in model[-1].solids} <= {(0.4, 0.5, 0.6), palette.sleeve}


# ---------------------------------------------------------------------------
# The wiring
# ---------------------------------------------------------------------------


def _wire_runs(doc: PerfDocument) -> list[Cylinder]:
    model = board_model(doc, footprint_lookup())
    wires = [part for part in model if part.name == WIRES_NAME]
    return [
        solid.shape
        for part in wires
        for solid in part.solids
        if isinstance(solid.shape, Cylinder) and solid.shape.axis[2] == 0.0
    ]


def _covers(run: Cylinder, a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Whether ``run`` lies along a to b and spans it -- lengthened by at most its radius at
    either end, which is the elbow it shares with the run before or after it."""
    length = math.dist(a, b)
    along = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
    if not (math.isclose(run.axis[0], along[0]) and math.isclose(run.axis[1], along[1])):
        return False
    dx, dy = a[0] - run.base[0], a[1] - run.base[1]
    start = dx * along[0] + dy * along[1]
    beside = abs(dx * along[1] - dy * along[0])
    tail = run.length - (start + length)
    return beside < 1e-6 and -1e-6 <= start <= run.radius + 1e-6 and -1e-6 <= tail <= run.radius + 1e-6


def test_every_wire_lies_along_its_path_on_its_own_face_and_no_trace_is_drawn() -> None:
    """A wire run by run, centred a radius off the face it is laid on (more where it has
    to clear something), and a solder trace not at all: it is the copper."""
    doc = _example("nano-relay")
    board = doc.board
    outline = board_outline_mm(board)
    layers = stacking_layers(doc)
    wires = [c for c in doc.conductors if not contacts_every_path_hole(c)]
    assert wires and len(wires) < len(doc.conductors), "the fixture should have both"
    runs = _wire_runs(doc)
    assert len(runs) == sum(len(c.path) - 1 for c in wires)

    remaining = list(runs)
    for cond in wires:
        radius = wire_radius_mm(doc, cond)
        for a, b in zip(cond.path, cond.path[1:], strict=False):
            pa, pb = hole_to_mm(a, board), hole_to_mm(b, board)
            ax, ay = pa.x - outline.x, outline.y + outline.height - pa.y
            bx, by = pb.x - outline.x, outline.y + outline.height - pb.y
            match = next(run for run in remaining if _covers(run, (ax, ay), (bx, by)))
            remaining.remove(match)
            assert match.radius == radius
            if cond.side == "top":
                assert match.base[2] >= board.thickness + radius - 1e-9
            else:
                assert match.base[2] <= -radius + 1e-9
            if layers.get(cond.id, cond.layer_z) == 0:
                expected = board.thickness + radius if cond.side == "top" else -radius
                assert match.base[2] == pytest.approx(expected)
    assert not remaining


def test_a_wire_is_as_thick_as_the_gauge_it_is_cut_in_and_its_sleeve() -> None:
    """``cut_gauge_awg`` -- the gauge the cut list prints and DRC measures -- plus the
    sleeve, because the room a wire takes is what an enclosure is drawn round."""
    doc = _example("nano-relay")
    wires = [c for c in doc.conductors if isinstance(c, WireConductor)]
    assert {c.kind for c in wires} >= {"bare-wire", "insulated-wire"}
    heavy = tuple(replace(c, gauge_awg=18) if isinstance(c, WireConductor) else c for c in doc.conductors)
    doc = replace(doc, conductors=heavy)
    for cond in doc.conductors:
        if not isinstance(cond, WireConductor):
            continue
        sleeve = INSULATION_WALL_MM if cond.kind in SLEEVED_KINDS else 0.0
        assert wire_radius_mm(doc, cond) == pytest.approx(awg_diameter_mm(18) / 2 + sleeve)
    assert {run.radius for run in _wire_runs(doc)} <= {
        awg_diameter_mm(18) / 2,
        awg_diameter_mm(18) / 2 + INSULATION_WALL_MM,
    }


def _cross(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.stem)
def test_wires_that_cross_pass_over_one_another(path: Path) -> None:
    """Two runs whose paths cross in plan must be a whole radius-and-a-radius apart in
    height: two solids in one place is a modelling error whatever the picture looks like."""
    doc = _load(path)
    lookup = footprint_lookup()
    model = board_model(doc, lookup)
    wires = [part for part in model if part.name == WIRES_NAME]
    runs = [
        s.shape
        for part in wires
        for s in part.solids
        if isinstance(s.shape, Cylinder) and s.shape.axis[2] == 0.0
    ]

    def ends(run: Cylinder) -> tuple[tuple[float, float], tuple[float, float]]:
        # Without the radius each run is lengthened by at an elbow: the run before it and
        # the run after it are the same wire, and overlap there on purpose.
        near = run.radius
        far = run.length - run.radius
        return (
            (run.base[0] + run.axis[0] * near, run.base[1] + run.axis[1] * near),
            (run.base[0] + run.axis[0] * far, run.base[1] + run.axis[1] * far),
        )

    for index, first in enumerate(runs):
        a, b = ends(first)
        for second in runs[index + 1 :]:
            if (first.base[2] > 0) != (second.base[2] > 0):
                continue  # one on each face of the board
            c, d = ends(second)
            proper = (
                _cross(a, b, c) * _cross(a, b, d) < -1e-9
                and _cross(c, d, a) * _cross(c, d, b) < -1e-9
            )
            if proper:
                gap = abs(first.base[2] - second.base[2])
                assert gap >= first.radius + second.radius - 1e-9, (path.stem, first, second)


# ---------------------------------------------------------------------------
# A real reader, where one is installed
# ---------------------------------------------------------------------------


def test_opencascade_reads_every_solid_as_valid_and_the_board_to_its_volume(
    tmp_path: Path,
) -> None:
    """Skipped unless ``cadquery-ocp`` is installed: it is how this module was checked
    while it was written, and how it should be checked again after any change to the
    B-rep -- the shell test above cannot tell a solid from its inside-out twin."""
    pytest.importorskip("OCP")
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    doc = _example("atmega328-relay")
    target = tmp_path / "board.step"
    target.write_text(document_to_step(doc, footprint_lookup(), timestamp=STAMP), "ascii")
    reader = STEPControl_Reader()
    assert reader.ReadFile(str(target)) == IFSelect_RetDone
    reader.TransferRoots()
    shape = reader.OneShape()
    assert BRepCheck_Analyzer(shape).IsValid()

    volumes = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(explorer.Current(), props)
        volumes.append(props.Mass())
        explorer.Next()
    assert all(volume > 0 for volume in volumes)

    plate = board_model(doc, footprint_lookup())[0].solids[0].shape
    assert isinstance(plate, Plate)
    area = plate.high[0] * plate.high[1] - sum(math.pi * r * r for _x, _y, r in plate.holes)
    assert volumes[0] == pytest.approx(area * plate.high[2], rel=1e-6)
