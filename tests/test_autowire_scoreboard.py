"""Auto-wire answers to its scoreboard: what it makes of four boards may get better, never worse.

``tools/autowire_scoreboard.py`` measures every board; this holds four of them -- the
densest example, two that made the loops the router now refuses, and the golden NE555 -- to
CEILINGS, not to values. A router change that lowers a number passes, and is expected to
lower the ceiling here in the same commit; one that raises a number fails with the board
and the column named. Why ceilings, and why these columns, is "Auto-wire is held to a
scoreboard" in docs/ARCHITECTURE.md.

Wired with the balanced style alone (``--plain``), not the window's whole sweep, so the
four boards cost a few seconds rather than half a minute.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "autowire_scoreboard.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("autowire_scoreboard", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("autowire_scoreboard", module)
    spec.loader.exec_module(module)
    return module


#: Per board, the most each column may be. ``unr``, ``loops`` and ``drawn`` are zero
#: everywhere and stay so; the rest are what the router made of the board on the day the
#: ceiling was set, and come DOWN with the change that improves them.
CEILINGS: dict[str, dict[str, int]] = {
    "atmega328-relay": {"unr": 0, "loops": 0, "drawn": 0, "level": 6, "pin": 22, "end": 14},
    "arduino-io-shield": {"unr": 0, "loops": 0, "drawn": 0, "level": 2, "pin": 4, "end": 1},
    "nano-relay": {"unr": 0, "loops": 0, "drawn": 0, "level": 2, "pin": 4, "end": 1},
    "ne555": {"unr": 0, "loops": 0, "drawn": 0, "level": 1, "pin": 0, "end": 0},
}


@pytest.fixture(scope="module")
def rows() -> dict[str, dict[str, Any]]:
    tool = _tool()
    found = tool.score(tuple(CEILINGS), plain=True)
    return {Path(row["file"]).stem: row for row in found if Path(row["file"]).stem in CEILINGS}


@pytest.mark.parametrize("board", sorted(CEILINGS))
def test_auto_wire_does_no_worse_than_its_ceiling(rows: dict[str, dict[str, Any]], board: str) -> None:
    row = rows[board]
    over = {
        column: f"{row[column]} > {ceiling}"
        for column, ceiling in CEILINGS[board].items()
        if row[column] > ceiling
    }
    assert not over, f"{board}, auto-wired: {over} (the scoreboard's columns are in {TOOL.name})"


def test_every_ceiling_names_a_column_the_scoreboard_has() -> None:
    columns = set(_tool().COLUMNS)
    assert {c for ceiling in CEILINGS.values() for c in ceiling} <= columns
