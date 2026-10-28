"""The selection the Properties panel shows: a value, so the window can compare the one it
derives with the one already showing and leave the panel alone when nothing changed."""

from __future__ import annotations

from typing import get_args

from perfboard_studio.ui.selection import NOTHING, Selection, SelectionKind


def test_nothing_selected_is_the_board() -> None:
    assert NOTHING.kind == "board"
    assert NOTHING.ids == ()


def test_a_selection_is_a_value() -> None:
    one = Selection("part", ("c-1",))
    assert one == Selection("part", ("c-1",), "board")
    assert one != Selection("part", ("c-1",), "sheet")
    assert len({one, Selection("part", ("c-1",))}) == 1


def test_every_kind_the_panel_hosts_is_named() -> None:
    kinds = set(get_args(SelectionKind.__value__))
    assert {"board", "part", "parts", "design-part", "placing"} <= kinds
