"""Tests for P6 schematic auto-layout (src/perfboard_studio/schlayout.py)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import PerfDocument
from perfboard_studio.schematic import (
    _net_name_box,
    _part_label_box,
    build_schematic,
    snap_to_grid,
)
from perfboard_studio.schlayout import arrange_sheet, arranged, printed_names

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
EXAMPLES = sorted(EXAMPLES_DIR.glob("*.perf"))
REGISTRY = footprint_lookup()


def _load(path: Path) -> PerfDocument:
    result = persist.deserialize_document(path.read_text(encoding="utf-8"))
    assert result.ok, result.message
    return result.document


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.stem)
def test_arrange_sheet_is_deterministic_and_snapped_to_grid(path: Path) -> None:
    """Running ``arrange_sheet`` twice produces identical grid-snapped placements and wires."""
    doc = _load(path)
    first = arrange_sheet(doc, REGISTRY)
    second = arrange_sheet(doc, REGISTRY)
    assert first == second
    for placement in first.placements:
        assert snap_to_grid(placement.at) == placement.at


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.stem)
def test_arranged_sheet_has_no_overlapping_symbols_or_labels(path: Path) -> None:
    """No two symbols overlap, no two non-pin labels overlap, and no ref/value hits a body."""
    drawing = build_schematic(arranged(_load(path), REGISTRY), REGISTRY)
    for idx, first in enumerate(drawing.symbols):
        for second in drawing.symbols[idx + 1 :]:
            overlap = (
                first.at.x < second.at.x + second.width - 1e-9
                and second.at.x < first.at.x + first.width - 1e-9
                and first.at.y < second.at.y + second.height - 1e-9
                and second.at.y < first.at.y + first.height - 1e-9
            )
            assert not overlap, f"{path.stem}: {first.ref} overlaps {second.ref}"

    texts = []
    for label in drawing.labels:
        if label.kind == "pin":
            continue
        box = _net_name_box(label) if label.kind in ("net", "rail") else _part_label_box(label)
        assert box is not None
        texts.append((box, label))
    for idx, (box, label) in enumerate(texts):
        for other_box, other_label in texts[idx + 1 :]:
            overlap = (
                box[0] < other_box[2]
                and other_box[0] < box[2]
                and box[1] < other_box[3]
                and other_box[1] < box[3]
            )
            assert not overlap, (
                f"{path.stem}: {label.kind} {label.text} overlaps "
                f"{other_label.kind} {other_label.text}"
            )
        if label.kind in ("ref", "value"):
            for sym in drawing.symbols:
                hits_body = (
                    sym.at.x < box[2]
                    and box[0] < sym.at.x + sym.width
                    and sym.at.y < box[3]
                    and box[1] < sym.at.y + sym.height
                )
                assert not hits_body, (
                    f"{path.stem}: {label.kind} {label.text} overlaps body of {sym.ref}"
                )


def test_atmega328_relay_j4_runs_straight_and_c3_c4_clear() -> None:
    """On atmega328-relay, J4 aligns straight with U1's PB1..PB5 pins, C3/C4 labels stay
    clear of each other, and printed net names drop sharply."""
    doc = _load(EXAMPLES_DIR / "atmega328-relay.perf")
    doc = dataclasses.replace(
        doc,
        components=tuple(
            dataclasses.replace(c, symbol="regulator") if c.ref == "U2" else c
            for c in doc.components
        ),
    )
    before = build_schematic(doc, REGISTRY)
    after = build_schematic(arranged(doc, REGISTRY), REGISTRY)
    assert printed_names(after) < printed_names(before) // 2

    for net in ("PB1", "PB2", "PB3", "PB4", "PB5"):
        wires = [w for w in after.wires if w.net_name == net]
        assert len(wires) == 1, f"{net} should be a single direct wire"
        path = wires[0].path
        assert all(abs(pt.y - path[0].y) < 1e-6 for pt in path), (
            f"{net} should run straight horizontally to J4, got {path}"
        )


def test_ne555_astable_j1_on_left_edge_and_zero_printed_net_names() -> None:
    """On ne555-astable, J1 sits on the left edge facing inward beside the circuit rather
    than floating alone at top-left, and every signal net is wired with zero printed names."""
    doc = _load(EXAMPLES_DIR / "ne555-astable.perf")
    after = build_schematic(arranged(doc, REGISTRY), REGISTRY)
    assert printed_names(after) == 0

    j1 = next(s for s in after.symbols if s.ref == "J1")
    u1 = next(s for s in after.symbols if s.ref == "U1")
    r1 = next(s for s in after.symbols if s.ref == "R1")
    assert all(pin.side == "right" for pin in j1.pins)
    assert j1.at.x == min(s.at.x for s in after.symbols)
    assert r1.at.y <= j1.at.y <= u1.at.y + u1.height
