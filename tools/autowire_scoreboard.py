"""What auto-wire makes of every board, as numbers a router change has to answer to.

    python tools/autowire_scoreboard.py                  # every example and golden board
    python tools/autowire_scoreboard.py atmega nano      # boards whose file name has one of these
    python tools/autowire_scoreboard.py --json out.json  # ...and keep the rows
    python tools/autowire_scoreboard.py --before old.json  # before -> after, per board

Each board of a system is wired on its own (``system.board_document``), stripped of its
copper and wired the way the window's Auto-wire does it: the best of the style sweep, wires
laid along the grid. ``--plain`` wires with the balanced style alone instead, which is what
``tests/test_autowire_scoreboard.py`` does to stay cheap.

The columns, per board:

  unr      connections auto-wire could not make
  err/warn DRC errors and warnings on the wired board
  wire     millimetres of wire (bare, insulated, top jumper)
  bends    corners in those wires
  trace    holes solder runs pass through
  level    the tallest stack of wires (``occupancy.stacking_layers``) -- each level is one
           more wire's thickness below the board, and nobody solders a tower of eight
  pin      holes a wire lies across (not its ends) where a pin is: its trimmed stub and its
           joint stand below the pad, so the wire has to be above them
  end      holes a wire lies across where another conductor ends and comes down to its pad
  loops    groups of wires each lying across another's end (``occupancy.stacking_loops``):
           soldered in no order, drawn apart by no stacking
  drawn    pairs of conductors whose 3D tubes go through each other away from a shared pad,
           measured on the centrelines and radii ``ui/view3d`` draws ("-" without the UI)
  s        seconds auto-wire took

Why each one is here, and why the test holds them to ceilings rather than values, is "Auto-
wire is held to a scoreboard" in docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import math
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from perfboard_studio import persist, system  # noqa: E402
from perfboard_studio.autoroute import (  # noqa: E402
    AutorouteOptions,
    plan_autoroute,
    plan_best_autoroute,
)
from perfboard_studio.connectivity import FootprintLookup  # noqa: E402
from perfboard_studio.drc import run_drc  # noqa: E402
from perfboard_studio.footprints import footprint_lookup  # noqa: E402
from perfboard_studio.geometry import hole_key, holes_under_line, path_length_mm  # noqa: E402
from perfboard_studio.model import (  # noqa: E402
    Conductor,
    PerfDocument,
    contacts_every_path_hole,
)
from perfboard_studio.occupancy import (  # noqa: E402
    build_occupancy,
    stacking_layers,
    stacking_loops,
)
from perfboard_studio.router import RouterOptions  # noqa: E402

COLUMNS = ("unr", "err", "warn", "wire", "bends", "trace", "level", "pin", "end", "loops", "drawn", "s")


def boards(names: tuple[str, ...] = ()) -> Iterator[tuple[str, str, PerfDocument]]:
    """(file, board id, the board alone) for every example and golden board, or the ones
    whose file name contains one of ``names``."""
    files = sorted((ROOT / "examples").rglob("*.perf")) + sorted(
        (ROOT / "tools" / "diffcheck" / "golden").glob("*.perf")
    )
    for path in files:
        if names and not any(name in path.stem for name in names):
            continue
        whole = persist.deserialize_document(path.read_text(encoding="utf-8")).document
        for board_id in system.board_ids(whole):
            rel = path.relative_to(ROOT).as_posix()
            yield rel, board_id, system.board_document(whole, board_id)


def autowire(
    doc: PerfDocument, lookup: FootprintLookup, *, plain: bool = False
) -> tuple[PerfDocument, int, str, float]:
    """The board wired from bare: (document, unrouted, style, seconds)."""
    bare = dataclasses.replace(doc, conductors=())
    options = AutorouteOptions(router=RouterOptions(wire_path="grid"))
    start = time.perf_counter()
    if plain:
        plan, style = plan_autoroute(bare, lookup, options), "balanced"
    else:
        best = plan_best_autoroute(bare, lookup, options)
        plan, style = best.plan, best.style
    return plan.document, plan.summary.links_unrouted, style, time.perf_counter() - start


def _is_wire(conductor: Conductor) -> bool:
    return not contacts_every_path_hole(conductor) and len(conductor.path) >= 2


def measure(
    doc: PerfDocument, lookup: FootprintLookup, *, drawn: bool = True
) -> dict[str, Any]:
    """Every column but ``unr`` and ``s``, on a wired board."""
    levels = stacking_layers(doc)
    occupancy = build_occupancy(doc, lookup)
    ends: dict[tuple[str, str], int] = {}
    for conductor in doc.conductors:
        if conductor.path:
            for end in {hole_key(conductor.path[0]), hole_key(conductor.path[-1])}:
                ends[(end, conductor.side)] = ends.get((end, conductor.side), 0) + 1
    pin = end = 0
    wire_mm = 0.0
    bends = trace = 0
    for conductor in doc.conductors:
        if contacts_every_path_hole(conductor):
            trace += len(conductor.path)
            continue
        if len(conductor.path) < 2:
            continue
        wire_mm += path_length_mm(conductor.path, doc.board)
        bends += max(0, len(conductor.path) - 2)
        own = {hole_key(conductor.path[0]), hole_key(conductor.path[-1])}
        across = {
            hole_key(hole): hole
            for start, stop in itertools.pairwise(conductor.path)
            for hole in holes_under_line(start, stop)
        }
        for key, hole in across.items():
            if key in own:
                continue
            pin += occupancy.pin_at(hole) is not None
            end += ends.get((key, conductor.side), 0) > 0
    findings = run_drc(doc, lookup)
    wires = [c for c in doc.conductors if _is_wire(c)]
    return {
        "err": sum(1 for f in findings if f.severity == "error"),
        "warn": sum(1 for f in findings if f.severity == "warning"),
        "wire": round(wire_mm, 1),
        "bends": bends,
        "trace": trace,
        "level": max((levels[c.id] for c in wires), default=0),
        "pin": pin,
        "end": end,
        "loops": len(stacking_loops(doc)),
        "drawn": len(drawn_collisions(doc, levels)) if drawn else None,
    }


def drawn_collisions(
    doc: PerfDocument, levels: dict[str, int] | None = None
) -> list[tuple[str, str]]:
    """Pairs of conductors on one face whose tubes, as ``ui/view3d`` builds them, are closer
    than their two radii away from any hole both are soldered into -- the measurement of
    ``tests/test_ui.py::test_no_two_conductors_are_drawn_in_the_same_place``, on any board."""
    from perfboard_studio.ui.view3d import (
        TRACE_WAIST_RATIO,
        _conductor_centreline,
        _trace_swell,
        _xy,
        conductor_radius,
        conductor_z,
        pad_z,
    )

    levels = stacking_layers(doc) if levels is None else levels

    def as_drawn(conductor: Conductor) -> tuple[list[Any], list[float]]:
        is_trace = contacts_every_path_hole(conductor)
        line = _conductor_centreline(
            conductor,
            doc.board,
            conductor_z(conductor, doc.board, levels[conductor.id]),
            pad_z(doc.board, conductor.side),
            is_trace,
        )
        if is_trace:
            waist = conductor_radius(conductor) * TRACE_WAIST_RATIO
            return line, [waist * value for value in _trace_swell(conductor, line)]
        return line, [conductor_radius(conductor)] * len(line)

    drawn = {c.id: as_drawn(c) for c in doc.conductors if len(c.path) >= 2}
    found: list[tuple[str, str]] = []
    for first, second in itertools.combinations([c for c in doc.conductors if c.id in drawn], 2):
        if first.side != second.side:
            continue
        shared = {hole_key(h) for h in first.path} & {hole_key(h) for h in second.path}
        joints = [
            _xy(doc.board, h) for h in (*first.path, *second.path) if hole_key(h) in shared
        ]
        line_a, radii_a = drawn[first.id]
        line_b, radii_b = drawn[second.id]
        if not _boxes_meet(_box(line_a, max(radii_a)), _box(line_b, max(radii_b))):
            continue
        if _collide(line_a, radii_a, line_b, radii_b, joints, doc.board.pad_diameter):
            found.append((first.id, second.id))
    return found


def _collide(
    line_a: list[Any],
    radii_a: list[float],
    line_b: list[Any],
    radii_b: list[float],
    joints: list[Any],
    reach: float,
) -> bool:
    boxes_b = [
        _box(line_b[j : j + 2], max(radii_b[j], radii_b[j + 1])) for j in range(len(line_b) - 1)
    ]
    for i in range(len(line_a) - 1):
        box_a = _box(line_a[i : i + 2], max(radii_a[i], radii_a[i + 1]))
        for j in range(len(line_b) - 1):
            if not _boxes_meet(box_a, boxes_b[j]):
                continue
            gap, where = _segment_gap(line_a[i], line_a[i + 1], line_b[j], line_b[j + 1])
            needed = max(radii_a[i], radii_a[i + 1]) + max(radii_b[j], radii_b[j + 1])
            if gap >= needed - 1e-9:
                continue
            if any(math.dist(where[:2], at) < reach for at in joints):
                continue
            return True
    return False


def _box(points: list[Any], pad: float) -> tuple[float, float, float, float, float, float]:
    """The box round some points, grown by ``pad`` -- a tube of that radius stays inside."""
    xs, ys, zs = zip(*points, strict=True)
    return (min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad, min(zs) - pad, max(zs) + pad)


def _boxes_meet(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return all(a[2 * k] <= b[2 * k + 1] and b[2 * k] <= a[2 * k + 1] for k in range(3))


def _segment_gap(
    p1: tuple[float, ...], p2: tuple[float, ...], q1: tuple[float, ...], q2: tuple[float, ...]
) -> tuple[float, tuple[float, ...]]:
    """Closest approach between two 3D segments, and where on the first it happens."""
    u = tuple(b - a for a, b in zip(p1, p2, strict=True))
    v = tuple(b - a for a, b in zip(q1, q2, strict=True))
    w = tuple(a - b for a, b in zip(p1, q1, strict=True))

    def dot(x: tuple[float, ...], y: tuple[float, ...]) -> float:
        return sum(a * b for a, b in zip(x, y, strict=True))

    a, b, c, d, e = dot(u, u), dot(u, v), dot(v, v), dot(u, w), dot(v, w)
    denominator = a * c - b * b
    if denominator < 1e-12:
        s_at, t_at = 0.0, (d / b if abs(b) > 1e-12 else 0.0)
    else:
        s_at, t_at = (b * e - c * d) / denominator, (a * e - b * d) / denominator
    s_at, t_at = min(1.0, max(0.0, s_at)), min(1.0, max(0.0, t_at))
    offset = tuple(w[i] + s_at * u[i] - t_at * v[i] for i in range(3))
    return math.sqrt(dot(offset, offset)), tuple(p1[i] + s_at * u[i] for i in range(3))


def score(
    names: tuple[str, ...] = (),
    *,
    plain: bool = False,
    drawn: bool = True,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """One row per board with parts: where it is, the style auto-wire chose, every column."""
    lookup = footprint_lookup()
    rows: list[dict[str, Any]] = []
    for rel, board_id, doc in boards(names):
        if not doc.components:
            continue
        wired, unrouted, style, seconds = autowire(doc, lookup, plain=plain)
        row = {
            "file": rel,
            "board": board_id,
            "style": style,
            "unr": unrouted,
            **measure(wired, lookup, drawn=drawn),
            "s": round(seconds, 2),
        }
        rows.append(row)
        if progress is not None:
            progress(row)
    return rows


def _name(row: dict[str, Any]) -> str:
    stem = Path(row["file"]).stem
    return stem if row["board"] == "main" else f"{stem}/{row['board']}"


def _cell(value: Any) -> str:
    return "-" if value is None else str(value)


def _line(row: dict[str, Any], before: dict[str, Any] | None = None) -> str:
    cells = []
    for column in COLUMNS:
        now = _cell(row[column])
        if before is not None and column != "s" and before.get(column) != row[column]:
            now = f"{_cell(before.get(column))}->{now}"
        cells.append(f"{now:>8}")
    return f"{_name(row):<30}{row['style']:<10}" + "".join(cells)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("names", nargs="*", help="only boards whose file name has one of these")
    parser.add_argument("--plain", action="store_true", help="balanced style alone, no sweep")
    parser.add_argument("--no-drawn", action="store_true", help="skip the 3D measurement")
    parser.add_argument("--json", type=Path, help="write the rows here")
    parser.add_argument("--before", type=Path, help="rows from an earlier run, to compare")
    args = parser.parse_args(argv)

    before: dict[tuple[str, str], dict[str, Any]] = {}
    if args.before:
        before = {(r["file"], r["board"]): r for r in json.loads(args.before.read_text("utf-8"))}
    print(f"{'board':<30}{'style':<10}" + "".join(f"{c:>8}" for c in COLUMNS))

    def show(row: dict[str, Any]) -> None:
        print(_line(row, before.get((row["file"], row["board"])) if before else None), flush=True)

    rows = score(tuple(args.names), plain=args.plain, drawn=not args.no_drawn, progress=show)
    totals = {
        c: round(sum(r[c] for r in rows if r[c] is not None), 2)
        for c in COLUMNS
        if c != "level"
    }
    totals["level"] = max((r["level"] for r in rows), default=0)
    print(_line({"file": "TOTAL", "board": "main", "style": "", **totals}))
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
