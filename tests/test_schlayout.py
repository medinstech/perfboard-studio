"""Tests for P6 schematic auto-layout (src/perfboard_studio/schlayout.py), the
``sheet.arrange`` command, and the schematic scoreboard ceilings."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    ArrangeSheetPayload,
    MoveSymbolsPayload,
    command_scope,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import DocumentMeta, PerfDocument, Point2, SheetNote, SymbolPlacement
from perfboard_studio.schematic import (
    _net_name_box,
    _part_label_box,
    build_schematic,
    snap_to_grid,
)
from perfboard_studio.schlayout import arrange_sheet, arranged, printed_names

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT / "examples"
EXAMPLES = sorted(EXAMPLES_DIR.glob("*.perf"))
REGISTRY = footprint_lookup()
TOOL = ROOT / "tools" / "schematic_scoreboard.py"


def _load(path: Path) -> PerfDocument:
    result = persist.deserialize_document(path.read_text(encoding="utf-8"))
    assert result.ok, result.message
    return result.document


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("schematic_scoreboard", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("schematic_scoreboard", module)
    spec.loader.exec_module(module)
    return module


#: Per example, the most each scoreboard column may be. ``ov`` stays 0 everywhere; the rest
#: are pinned to today's P6 numbers and move down with any layout improvement.
CEILINGS: dict[str, dict[str, float]] = {
    "arduino-io-shield": {"names": 4, "cross": 0, "bends": 19, "length": 405.0, "area": 330.0, "ov": 0},
    "atmega328-relay": {"names": 13, "cross": 4, "bends": 46, "length": 1320.0, "area": 990.0, "ov": 0},
    "lm317-supply": {"names": 2, "cross": 2, "bends": 31, "length": 655.0, "area": 290.0, "ov": 0},
    "lpb1-booster": {"names": 2, "cross": 1, "bends": 16, "length": 360.0, "area": 295.0, "ov": 0},
    "nano-relay": {"names": 3, "cross": 1, "bends": 17, "length": 400.0, "area": 770.0, "ov": 0},
    "ne555-astable": {"names": 0, "cross": 3, "bends": 16, "length": 335.0, "area": 245.0, "ov": 0},
    "relay-and-supply": {"names": 4, "cross": 1, "bends": 34, "length": 650.0, "area": 1260.0, "ov": 0},
}


@pytest.fixture(scope="module")
def scoreboard_rows() -> dict[str, dict[str, Any]]:
    tool = _tool()
    found = tool.score()
    return {Path(row["file"]).stem: row for row in found}


@pytest.mark.parametrize("board", sorted(CEILINGS))
def test_schematic_scoreboard_does_no_worse_than_its_ceiling(
    scoreboard_rows: dict[str, dict[str, Any]], board: str
) -> None:
    row = scoreboard_rows[board]
    over = {
        column: f"{row[column]} > {ceiling}"
        for column, ceiling in CEILINGS[board].items()
        if row[column] > ceiling
    }
    assert not over, f"{board}: {over} (see {TOOL.name})"


def test_every_scoreboard_ceiling_names_a_real_column() -> None:
    columns = set(_tool().COLUMNS)
    assert {c for ceiling in CEILINGS.values() for c in ceiling} <= columns


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
    clear of each other, and printed net names stay at 13."""
    doc = _load(EXAMPLES_DIR / "atmega328-relay.perf")
    after = build_schematic(arranged(doc, REGISTRY), REGISTRY)
    assert printed_names(after) <= 13

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


def test_sheet_arrange_command_whole_sheet_and_undo() -> None:
    """``sheet.arrange`` is a design command that populates editable placements, wires and
    ports in one undo step, preserves notes and nets, and round-trips cleanly on undo."""
    assert command_scope("sheet.arrange") == "design"
    note = SheetNote(
        id="note-1", kind="text", at=Point2(x=10.16, y=10.16), to=Point2(x=10.16, y=10.16), text="Keep"
    )
    doc = dataclasses.replace(_load(EXAMPLES_DIR / "ne555-astable.perf"), sheet_notes=(note,))
    bus = CommandBus(
        doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc))
    )

    result = bus.dispatch("sheet.arrange", ArrangeSheetPayload())
    assert result.ok, result.message
    assert result.description == "Arrange the sheet"
    assert bus.document.sheet
    assert bus.document.sheet_wires
    assert bus.document.sheet_ports
    assert bus.document.nets == doc.nets
    assert bus.document.sheet_notes == (note,)

    undone = bus.undo()
    assert undone is not None
    assert bus.document == doc


def test_sheet_arrange_command_subset_keeps_unselected_symbols() -> None:
    """Arranging a selected subset of symbols on a hand-drawn sheet leaves every unselected
    symbol where it was and undoes in one step."""
    doc = _load(EXAMPLES_DIR / "ne555-astable.perf")
    bus = CommandBus(
        doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc))
    )
    assert bus.dispatch("sheet.arrange", ArrangeSheetPayload()).ok
    # Move R1 and R2 far out of place while leaving U1, R3, LED1, J1, C1, C2 fixed.
    ids = {c.ref: c.id for c in doc.components}
    scrambled = (
        SymbolPlacement(id=ids["R1"], at=Point2(x=254.0, y=254.0)),
        SymbolPlacement(id=ids["R2"], at=Point2(x=304.8, y=254.0)),
    )
    assert bus.dispatch("symbol.move", MoveSymbolsPayload(placements=scrambled)).ok
    before_subset = bus.document
    unselected_ids = {cid for ref, cid in ids.items() if ref not in {"R1", "R2"}}
    before_unselected = {p.id: p for p in before_subset.sheet if p.id in unselected_ids}

    res = bus.dispatch("sheet.arrange", ArrangeSheetPayload(refs=("R1", "R2")))
    assert res.ok, res.message
    assert res.description == "Arrange 2 symbols on the sheet"
    after_unselected = {p.id: p for p in bus.document.sheet if p.id in unselected_ids}
    assert after_unselected == before_unselected
    assert bus.document.nets == doc.nets

    assert bus.undo() is not None
    assert bus.document == before_subset


def test_sheet_arrange_command_refuses_empty_sheet_or_unknown_ref() -> None:
    doc = _load(EXAMPLES_DIR / "ne555-astable.perf")
    bus = CommandBus(
        doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc))
    )
    bad = bus.dispatch("sheet.arrange", ArrangeSheetPayload(refs=("NO_SUCH_PART",)))
    assert not bad.ok and bad.code == "unknown-ref"

    empty = PerfDocument(
        meta=DocumentMeta(name="empty", created="", modified=""),
        board=doc.board,
        components=(),
        nets=(),
    )
    empty_bus = CommandBus(
        empty, create_standard_registry(), CommandContext(next_id=create_document_id_generator(empty))
    )
    nothing = empty_bus.dispatch("sheet.arrange", ArrangeSheetPayload())
    assert not nothing.ok and nothing.code == "nothing-to-do"
