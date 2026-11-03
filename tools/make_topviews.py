"""Write what every borrowed package looks like from above: ``ui/models/topviews.json``.

WHY THIS EXISTS. The 2D view drew each part from its archetype -- a DIP was a black block
as wide as its pin rows, with grey circles on its edges -- and looked nothing like the part
on the bench. The 3D view has had the real shapes since the meshes arrived, and this is
those same meshes, seen from straight above: measured, not drawn by eye, so the two views
cannot show two different parts.

HOW. Each model is rasterised straight down onto a 0.02 mm grid with a z-buffer, so every
cell belongs to the piece someone looking down at the board would see there. The height map
then says three more things about the case: its flat top, its sloped sides, and what is cut
into it (a DIP's pin-1 notch). Grooves in metal (a screw's slot, a can's vent) are what is
lower than the metal round it. Each region is traced into polygons in the FOOTPRINT's local
millimetres -- pin 1 at the origin, x along the columns, y DOWN the rows -- and simplified
to a hundredth of a millimetre.

WHAT IT NEEDS. numpy and PySide6, and the meshes already in ``ui/models``; not KiCad. Run it
after ``import_kicad_models.py`` changes a mesh, and ``tests/test_topview.py`` fails if the
data and the meshes disagree.

    python tools/make_topviews.py            # write src/perfboard_studio/ui/models/topviews.json
    python tools/make_topviews.py --check    # verify only
    python tools/make_topviews.py --only <footprint id> ...   # re-measure these, keep the rest

THE LICENCE. The outlines are derived from the meshes, which are derived from KiCad's
CC-BY-SA library, so they live beside them under the same LICENSE and NOTICE.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from perfboard_studio.ui import partmodels  # noqa: E402

OUT = partmodels.MODELS_DIR / "topviews.json"

#: Grid cell, in millimetres: a twentieth of the narrowest feature that matters (a 0.5 mm lead).
CELL_MM = 0.02
#: Simplification tolerance, in millimetres: a little over one cell, so the staircase a grid
#: leaves on a slanted or curved edge is smoothed away and no feature a person could see is.
TOLERANCE_MM = 0.025
#: A case face below its top by more than this is not the top any more.
RELIEF_MM = 0.06
#: A recess is at least this wide; a narrower band below the top is the sloped side.
RECESS_MM = 0.6
#: A groove in metal is at least this much below the metal round it, within GROOVE_MM.
GROOVE_DEPTH_MM = 0.03
GROOVE_MM = 0.8

METALS = frozenset({"steel", "tinned", "plated", "gold", "copper", "aluminium", "nickel", "chrome", "brass"})


def read_ply(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Binary little-endian PLY as ``import_kicad_models.ply_bytes`` writes it."""
    data = path.read_bytes()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii").splitlines()
    vertices = next(int(line.split()[2]) for line in header if line.startswith("element vertex"))
    faces = next(int(line.split()[2]) for line in header if line.startswith("element face"))
    points = np.frombuffer(data, dtype="<f4", count=vertices * 3, offset=end).reshape(vertices, 3)
    records = np.frombuffer(data, dtype=np.uint8, count=faces * 13, offset=end + vertices * 12)
    records = records.reshape(faces, 13)
    if not (records[:, 0] == 3).all():
        raise ValueError(f"{path.name}: not all faces are triangles")
    return points.astype(np.float64), records[:, 1:].copy().view("<i4").reshape(faces, 3)


def role_of(piece: partmodels.ModelPiece) -> str:
    if piece.is_body:
        return "body"
    if piece.material in METALS:
        return "metal"
    return "marking"


def rasterise(model: partmodels.PartModel) -> tuple[list[Any], np.ndarray, np.ndarray, float, float]:
    """Every piece onto one grid, nearest-to-the-sky wins. Row 0 is the model's highest y,
    so rows run DOWN the board as the footprint's rows do."""
    meshes = []
    for piece in model.pieces:
        points, faces = read_ply(piece.path)
        if model.turn_deg or model.offset != (0.0, 0.0):
            xy = np.array([model.placed(x, y) for x, y in points[:, :2]])
            points = np.column_stack([xy, points[:, 2]])
        meshes.append((piece, points, faces))
    every = np.vstack([points for _piece, points, _faces in meshes])
    x0, y1 = every[:, 0].min() - 0.2, every[:, 1].max() + 0.2
    width = int(np.ceil((every[:, 0].max() + 0.2 - x0) / CELL_MM))
    height = int(np.ceil((y1 - (every[:, 1].min() - 0.2)) / CELL_MM))
    zbuf = np.full((height, width), -np.inf)
    label = np.full((height, width), -1, dtype=np.int32)
    for index, (_piece, points, faces) in enumerate(meshes):
        for triangle in points[faces]:
            xs = (triangle[:, 0] - x0) / CELL_MM
            ys = (y1 - triangle[:, 1]) / CELL_MM
            zs = triangle[:, 2]
            c0, c1 = max(int(np.floor(xs.min())), 0), min(int(np.ceil(xs.max())) + 1, width)
            r0, r1 = max(int(np.floor(ys.min())), 0), min(int(np.ceil(ys.max())) + 1, height)
            if c1 <= c0 or r1 <= r0:
                continue
            gx, gy = np.meshgrid(np.arange(c0, c1) + 0.5, np.arange(r0, r1) + 0.5)
            denom = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(denom) < 1e-12:
                continue
            l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / denom
            l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / denom
            l2 = 1 - l0 - l1
            inside = (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9)
            if not inside.any():
                continue
            z = l0 * zs[0] + l1 * zs[1] + l2 * zs[2]
            region_z = zbuf[r0:r1, c0:c1]
            region_l = label[r0:r1, c0:c1]
            closer = inside & (z > region_z)
            region_z[closer] = z[closer]
            region_l[closer] = index
    return meshes, label, zbuf, x0, y1


def _disk(radius_cells: int) -> list[tuple[int, int]]:
    r = radius_cells
    return [(dy, dx) for dy in range(-r, r + 1) for dx in range(-r, r + 1) if dx * dx + dy * dy <= r * r]


def _shift(image: np.ndarray, dy: int, dx: int, fill: Any) -> np.ndarray:
    out = np.full_like(image, fill)
    h, w = image.shape
    out[max(dy, 0) : h + min(dy, 0), max(dx, 0) : w + min(dx, 0)] = image[
        max(-dy, 0) : h + min(-dy, 0), max(-dx, 0) : w + min(-dx, 0)
    ]
    return out


def _erode(mask: np.ndarray, radius_cells: int) -> np.ndarray:
    out = mask.copy()
    for dy, dx in _disk(radius_cells):
        out &= _shift(mask, dy, dx, False)
    return out


def _dilate(mask: np.ndarray, radius_cells: int) -> np.ndarray:
    out = mask.copy()
    for dy, dx in _disk(radius_cells):
        out |= _shift(mask, dy, dx, False)
    return out


def _grey_close(height: np.ndarray, radius_cells: int) -> np.ndarray:
    grown = height.copy()
    for dy, dx in _disk(radius_cells):
        np.maximum(grown, _shift(height, dy, dx, -np.inf), out=grown)
    closed = grown.copy()
    for dy, dx in _disk(radius_cells):
        np.minimum(closed, _shift(grown, dy, dx, np.inf), out=closed)
    return closed


def _rings(mask: np.ndarray, x0: float, y1: float) -> list[list[float]]:
    """The mask's outline, as rings of footprint millimetres, by Qt's own region tracing
    and then simplified: QRegion holds the cells exactly, and ``simplified`` merges them
    into the boundary of their union."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QPainterPath, QRegion

    region = QRegion()
    for row in range(mask.shape[0]):
        line = mask[row]
        if not line.any():
            continue
        edges = np.flatnonzero(np.diff(np.concatenate([[0], line.astype(np.int8), [0]])))
        for start, stop in zip(edges[::2], edges[1::2], strict=True):
            region = region.united(QRect(int(start), row, int(stop - start), 1))
    path = QPainterPath()
    path.addRegion(region)
    path = path.simplified()
    rings = []
    for polygon in path.toSubpathPolygons():
        points = [(p.x() * CELL_MM + x0, p.y() * CELL_MM - y1) for p in polygon]
        points = _douglas_peucker(points, TOLERANCE_MM)
        if len(points) >= 3 and abs(_area(points)) > 4 * CELL_MM * CELL_MM:
            rings.append([round(c, 2) for point in points for c in point])
    return rings


def _area(points: list[tuple[float, float]]) -> float:
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True))


def _douglas_peucker(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    if len(points) < 4:
        return points
    closed = points[0] == points[-1]
    work = points[:-1] if closed else points
    keep = [False] * len(work)
    keep[0] = keep[-1] = True
    stack = [(0, len(work) - 1)]
    while stack:
        first, last = stack.pop()
        (ax, ay), (bx, by) = work[first], work[last]
        length = max(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5, 1e-12)
        best, at = 0.0, -1
        for i in range(first + 1, last):
            px, py = work[i]
            distance = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
            if distance > best:
                best, at = distance, i
        if at >= 0 and best > tolerance:
            keep[at] = True
            stack.extend([(first, at), (at, last)])
    return [p for p, k in zip(work, keep, strict=True) if k]


def top_view(model: partmodels.PartModel) -> dict[str, Any]:
    meshes, label, zbuf, x0, y1 = rasterise(model)
    shapes: list[tuple[float, str, list[list[float]], str | None]] = []
    recess_cells = max(1, round(RECESS_MM / CELL_MM / 2))
    groove_cells = max(1, round(GROOVE_MM / CELL_MM / 2))
    for index, (piece, _points, _faces) in enumerate(meshes):
        mask = label == index
        if not mask.any():
            continue
        mask = _erode(_dilate(mask, 1), 1)  # a cell's worth of closing: no seams
        top = float(zbuf[label == index].max())
        role = role_of(piece)
        if role == "body":
            below = mask & (zbuf < top - RELIEF_MM)
            recess = _dilate(_erode(below, recess_cells), recess_cells) & below
            shapes.append((top, "body", _rings(mask & ~below, x0, y1), None))
            shapes.append((top - 0.001, "flank", _rings(below & ~recess, x0, y1), None))
            shapes.append((top + 0.001, "recess", _rings(recess, x0, y1), None))
        else:
            # A marking keeps the colour the 3D view draws its piece in: an LCD's bezel and
            # its glass are two markings, and one ink for both made them one grey slab.
            ink = piece.color if role == "marking" else None
            shapes.append((top, role, _rings(mask, x0, y1), ink))
            if role == "metal":
                height = np.where(label == index, zbuf, top)
                groove = (_grey_close(height, groove_cells) - height > GROOVE_DEPTH_MM)
                groove &= _erode(mask, 4) & (label == index)
                if groove.sum() * CELL_MM * CELL_MM > 0.016:
                    shapes.append((top + 0.001, "metal-recess", _rings(groove, x0, y1), None))
    shapes = [shape for shape in shapes if shape[2]]
    shapes.sort(key=lambda shape: shape[0])
    every = _erode(_dilate(label >= 0, 1), 1)
    return {
        "source": model.source,
        "shapes": [
            {"role": role, **({"color": ink} if ink else {}), "rings": rings}
            for _top, role, rings, ink in shapes
        ],
        "silhouette": _rings(every, x0, y1),
    }


def build(only: frozenset[str] | None = None) -> dict[str, Any]:
    """Every footprint with a model, or with ``only`` just those re-measured and the rest
    kept from the file on disk -- for trying a part out in seconds rather than the minute
    and more the whole library takes. ``--check`` always measures all of them."""
    kept: dict[str, Any] = {}
    if only is not None and OUT.is_file():
        kept = json.loads(OUT.read_text(encoding="utf-8"))
    views: dict[str, Any] = {}
    for footprint_id in sorted(partmodels.known_footprints()):
        model = partmodels.model_for(footprint_id)
        if model is None:
            continue
        if only is None or footprint_id in only or footprint_id not in kept:
            views[footprint_id] = top_view(model)
        else:
            views[footprint_id] = kept[footprint_id]
    return views


def _ring_lines(rings: list[list[float]], indent: str) -> str:
    return f",\n{indent}".join(json.dumps(ring, separators=(",", ":")) for ring in rings)


def dump(views: dict[str, Any]) -> str:
    """One footprint per block and one ring per line: small, and a diff says which part moved."""
    lines = ["{"]
    for n, (footprint_id, view) in enumerate(sorted(views.items())):
        lines.append(f"  {json.dumps(footprint_id)}: {{")
        lines.append(f'   "source": {json.dumps(view["source"])},')
        lines.append('   "shapes": [')
        for i, shape in enumerate(view["shapes"]):
            comma = "," if i < len(view["shapes"]) - 1 else ""
            rings = _ring_lines(shape["rings"], "     ")
            ink = f', "color": {json.dumps(shape["color"])}' if "color" in shape else ""
            lines.append(f'    {{"role": {json.dumps(shape["role"])}{ink}, "rings": [\n     {rings}]}}{comma}')
        lines.append("   ],")
        lines.append(f'   "silhouette": [\n    {_ring_lines(view["silhouette"], "    ")}]')
        lines.append("  }" + ("," if n < len(views) - 1 else ""))
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify only, write nothing")
    parser.add_argument("--only", nargs="+", help="re-measure these footprint ids, keep the rest")
    args = parser.parse_args(argv)
    if args.check and args.only:
        parser.error("--check measures every part: drop --only")
    from PySide6.QtGui import QGuiApplication

    _app = QGuiApplication.instance() or QGuiApplication(["make_topviews"])
    text = dump(build(frozenset(args.only) if args.only else None))
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.name} is out of date: run tools/make_topviews.py")
            return 1
        print(f"{OUT.name} matches the meshes")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(text) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
