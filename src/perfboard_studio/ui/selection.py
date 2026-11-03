"""What the Properties panel is showing: one selection, said as a kind and the ids in it.

The window derives it from wherever the selection was made -- the board, the sheet, the
Parts list, the Nets panel, or a library part armed for placing -- and hands it to the
panel, whose editors read everything else off the document. Nothing selected is the board
itself, so the panel always has something to show.

It lives on its own, below both, so the window that derives it and the panel that shows it
import one small thing instead of each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: ``board``: nothing selected, the board's own properties. ``part`` / ``parts``: one or
#: several parts on the board; ``design-part`` / ``design-parts``: in the design and not on
#: the board.
#: ``placing``: a library part armed for placing, whose id is its footprint id -- the part
#: about to be placed, so its value is typed where every other value is.
type SelectionKind = Literal[
    "board",
    "part",
    "parts",
    "design-part",
    "design-parts",
    "conductor",
    "conductors",
    "net",
    "board-note",
    "mounting-hole",
    "edge-connector",
    "sheet-note",
    "cut",
    "mixed",
    "placing",
]

#: Where the selection was made: a canvas, a side panel, or the library.
type SelectionSource = Literal["board", "sheet", "nets", "parts", "library"]


@dataclass(frozen=True, slots=True)
class Selection:
    kind: SelectionKind
    ids: tuple[str, ...] = ()
    source: SelectionSource = "board"


#: Nothing selected: the panel shows the board.
NOTHING = Selection("board")
