"""What schematic auto-layout makes of every example, as numbers a layout change answers to.

    python tools/schematic_scoreboard.py                   # every example board
    python tools/schematic_scoreboard.py atmega ne555      # examples whose name matches
    python tools/schematic_scoreboard.py --json out.json   # ...and keep the rows
    python tools/schematic_scoreboard.py --before old.json # before -> after, per board

The columns, per example:

  names   printed net labels a reader has to match up by eye
  wires   drawn signal wires
  cross   proper orthogonal crossings between wires of different nets
  bends   corners across all drawn wires
  length  total wire length in sheet millimetres
  area    sheet bounding area in square centimetres
  ov      symbol/symbol, label/label, and ref/value-over-body overlaps (must stay 0)
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from perfboard_studio import persist  # noqa: E402
from perfboard_studio.footprints import footprint_lookup  # noqa: E402
from perfboard_studio.model import PerfDocument  # noqa: E402
from perfboard_studio.schematic import (  # noqa: E402
    SchematicDrawing,
    _net_name_box,
    _part_label_box,
    build_schematic,
)
from perfboard_studio.schlayout import printed_names  # noqa: E402

COLUMNS = ("names", "wires", "cross", "bends", "length", "area", "ov")


def examples(names: tuple[str, ...] = ()) -> Iterator[tuple[str, PerfDocument]]:
    """(relative path, document) for every example board, or those matching ``names``."""
    for path in sorted((ROOT / "examples").glob("*.perf")):
        if names and not any(name in path.stem for name in names):
            continue
        doc = persist.deserialize_document(path.read_text(encoding="utf-8")).document
        yield path.relative_to(ROOT).as_posix(), dataclasses.replace(
            doc, sheet=(), sheet_wires=(), sheet_ports=()
        )


def _crossings(drawing: SchematicDrawing) -> int:
    """Proper orthogonal crossings between wire segments of different nets."""
    horiz: list[tuple[str, float, float, float]] = []
    vert: list[tuple[str, float, float, float]] = []
    for wire in drawing.wires:
        for start, end in itertools.pairwise(wire.path):
            if abs(start.y - end.y) < 1e-6 and abs(start.x - end.x) > 1e-6:
                horiz.append((wire.net_id, start.y, min(start.x, end.x), max(start.x, end.x)))
            elif abs(start.x - end.x) < 1e-6 and abs(start.y - end.y) > 1e-6:
                vert.append((wire.net_id, start.x, min(start.y, end.y), max(start.y, end.y)))
    count = 0
    eps = 1e-6
    for h_net, hy, hx0, hx1 in horiz:
        for v_net, vx, vy0, vy1 in vert:
            if h_net == v_net:
                continue
            if hx0 + eps < vx < hx1 - eps and vy0 + eps < hy < vy1 - eps:
                count += 1
    return count


def _overlaps(drawing: SchematicDrawing) -> int:
    """Count symbol/symbol, non-pin label/label, and ref/value-vs-body overlaps."""
    total = 0
    for idx, first in enumerate(drawing.symbols):
        for second in drawing.symbols[idx + 1 :]:
            if (
                first.at.x < second.at.x + second.width - 1e-9
                and second.at.x < first.at.x + first.width - 1e-9
                and first.at.y < second.at.y + second.height - 1e-9
                and second.at.y < first.at.y + first.height - 1e-9
            ):
                total += 1
    texts = []
    for label in drawing.labels:
        if label.kind == "pin":
            continue
        box = _net_name_box(label) if label.kind in ("net", "rail") else _part_label_box(label)
        if box is not None:
            texts.append((box, label))
    for idx, (box, label) in enumerate(texts):
        for other_box, _other in texts[idx + 1 :]:
            if (
                box[0] < other_box[2]
                and other_box[0] < box[2]
                and box[1] < other_box[3]
                and other_box[1] < box[3]
            ):
                total += 1
        if label.kind in ("ref", "value"):
            for sym in drawing.symbols:
                if (
                    sym.at.x < box[2]
                    and box[0] < sym.at.x + sym.width
                    and sym.at.y < box[3]
                    and box[1] < sym.at.y + sym.height
                ):
                    total += 1
    return total


def measure(drawing: SchematicDrawing) -> dict[str, Any]:
    """Every scoreboard column for one rendered ``SchematicDrawing``."""
    wire_mm = sum(
        abs(end.x - start.x) + abs(end.y - start.y)
        for wire in drawing.wires
        for start, end in itertools.pairwise(wire.path)
    )
    bends = sum(max(0, len(wire.path) - 2) for wire in drawing.wires)
    return {
        "names": printed_names(drawing),
        "wires": len(drawing.wires),
        "cross": _crossings(drawing),
        "bends": bends,
        "length": round(wire_mm, 1),
        "area": round(drawing.width * drawing.height / 100.0, 1),
        "ov": _overlaps(drawing),
    }


def score(
    names: tuple[str, ...] = (),
    *,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """One scoreboard row per example board."""
    lookup = footprint_lookup()
    rows: list[dict[str, Any]] = []
    for rel, doc in examples(names):
        drawing = build_schematic(doc, lookup)
        row = {"file": rel, **measure(drawing)}
        rows.append(row)
        if progress is not None:
            progress(row)
    return rows


def _cell(value: Any) -> str:
    return "-" if value is None else str(value)


def _line(row: dict[str, Any], before: dict[str, Any] | None = None) -> str:
    cells = []
    for column in COLUMNS:
        now = _cell(row[column])
        if before is not None and before.get(column) != row[column]:
            now = f"{_cell(before.get(column))}->{now}"
        cells.append(f"{now:>10}")
    return f"{Path(row['file']).stem:<22}" + "".join(cells)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("names", nargs="*", help="only examples whose file name has one of these")
    parser.add_argument("--json", type=Path, help="write the rows here")
    parser.add_argument("--before", type=Path, help="rows from an earlier run, to compare")
    args = parser.parse_args(argv)

    before: dict[str, dict[str, Any]] = {}
    if args.before:
        before = {r["file"]: r for r in json.loads(args.before.read_text("utf-8"))}
    print(f"{'example':<22}" + "".join(f"{c:>10}" for c in COLUMNS))

    def show(row: dict[str, Any]) -> None:
        print(_line(row, before.get(row["file"]) if before else None), flush=True)

    rows = score(tuple(args.names), progress=show)
    totals = {
        c: round(sum(r[c] for r in rows), 1) if c in ("length", "area") else sum(r[c] for r in rows)
        for c in COLUMNS
    }
    print(_line({"file": "TOTAL", **totals}))
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
