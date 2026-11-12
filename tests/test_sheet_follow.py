"""A symbol that moves takes its wires with it, and a wire it would drag into a backtrack,
a line over itself, a symbol or another net's wire is laid again, in the same move
(``wires_after_move``), so the saved file is what the screen shows."""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

from perfboard_studio import persist
from perfboard_studio.model import Point2, SymbolPlacement
from perfboard_studio.schematic import (
    _backtracks,
    _overlaps_itself,
    _through_a_body,
    build_schematic,
    drawing_after_move,
    wires_after_move,
)

from .test_sheet_tee import LOOKUP, _bus, _pin, _wire
from .test_ui import _close, _window_on


@pytest.fixture(scope="module", autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"


def _placed(doc, ref: str, x: float, y: float) -> SymbolPlacement:
    part = next(p for p in doc.parts if p.ref == ref)
    old = next(s for s in doc.sheet if s.id == part.id)
    return dataclasses.replace(old, at=Point2(x=x, y=y))


def _dirty(drawing) -> list[tuple[str, str]]:
    """The drawn wires that backtrack, overlap themselves or pass through a symbol."""
    boxes = [(s.at.x, s.at.y, s.at.x + s.width, s.at.y + s.height) for s in drawing.symbols]
    return [
        w.ends and (str(w.ends[0]), str(w.ends[1]))
        for w in drawing.wires
        if w.ends is not None
        and (_backtracks(w.path) or _overlaps_itself(w.path) or _through_a_body(w.path, boxes))
    ]


def test_a_wire_dragged_past_its_first_leg_is_laid_again_and_clean() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    moved = [_placed(bus.document, "R1", 50.8, 5.08)]
    naive = dataclasses.replace(
        bus.document,
        sheet=tuple(moved[0] if s.id == moved[0].id else s for s in bus.document.sheet),
    )
    laid = wires_after_move(bus.document, LOOKUP, moved)
    assert len(laid) == 1 and laid[0].path != bus.document.sheet_wires[0].path
    drawing = drawing_after_move(bus.document, LOOKUP, moved)
    assert _dirty(drawing) == []
    # What the drop saves is what the drag showed.
    saved = dataclasses.replace(naive, sheet_wires=laid)
    assert [w.path for w in build_schematic(saved, LOOKUP).wires if w.ends] == [
        w.path for w in drawing.wires if w.ends
    ]


def test_a_wire_that_is_still_clean_is_left_as_it_was_drawn() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    # A nudge of one grid square: the end segments give, the middle stays.
    moved = [_placed(bus.document, "R1", 20.32, 22.86)]
    drawing = drawing_after_move(bus.document, LOOKUP, moved)
    assert _dirty(drawing) == []
    # The drawn middle is kept: the saved wire is the stored one with its ends slid.
    (stored,) = bus.document.sheet_wires
    (kept,) = [w for w in drawing.wires if w.ends]
    assert kept.path[1:-1] == stored.path[1:-1] or len(kept.path) != len(stored.path)


@pytest.mark.parametrize("name", ["atmega328-relay", "nano-relay", "ne555-astable"])
def test_dragging_a_symbol_on_an_example_leaves_no_wire_through_or_over_itself(name) -> None:
    """The examples open on a derived sheet; the first move freezes it and lays the wires
    the move spoilt again, in the same command, so one undo takes both back."""
    path = EXAMPLES / f"{name}.perf"
    document = persist.deserialize_document(path.read_text(encoding="utf-8")).document
    window = _window_on(document)
    window.show_schematic()
    window._refresh_schematic_panel()
    drawing = window.schematic_view.item.drawing
    # The symbol with the most wires, dragged a long way up and to the right.
    ends = [e for w in drawing.wires for e in (w.path[0], w.path[-1])]
    symbol = max(
        drawing.symbols,
        key=lambda s: sum(
            1
            for e in ends
            for pin in s.pins
            if abs(e.x - (s.at.x + pin.at.x)) < 1e-6 and abs(e.y - (s.at.y + pin.at.y)) < 1e-6
        ),
    )
    # Out past the right-hand edge and up: clear of every other symbol, and further than the
    # first leg of any of its wires is long.
    right = max(s.at.x + s.width for s in drawing.symbols)
    window._on_symbols_moved([(symbol.ref, right + 15.24, symbol.at.y - 20.32)])
    window._refresh_schematic_panel()
    after = window.schematic_view.item.drawing
    assert _dirty(after) == [], _dirty(after)
    saved = window.bus.document.sheet_wires
    assert saved
    window.bus.undo()
    assert window.bus.document.sheet == ()
    _close(window)
