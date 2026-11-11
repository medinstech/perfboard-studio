"""What is worth a look in the wiring: the Problems drawer's Wiring group.

Not DRC. A wire lying over a pin, or over where other copper ends, or stacked over many
others, is a board that works and is harder to build than it has to be -- a cost, not a
defect -- so it never counts as a problem, never blocks the Build step and never moves a
golden. It is said so the one bad wire can be found: Auto-wire used to finish on "No
problems" over a board with a wire lying across 44 pins.

The counts are the engine's (the wiring cost the autowire scoreboard reads), never a
second computation here: one fact, several askers, like the wire gauge.
"""

from __future__ import annotations

from dataclasses import dataclass

from perfboard_studio.model import HoleCoord, PerfDocument


@dataclass(frozen=True, slots=True)
class WiringNote:
    """One thing worth a look in the wiring, and the copper it is about."""

    #: Stable across rebuilds, so the drawer keeps the group open.
    key: str
    #: Said, in the window's language: "44 places a wire lies over a pin".
    title: str
    #: Selected on the board when the note is clicked.
    conductor_ids: tuple[str, ...]
    #: Shown on the board when the note is hovered.
    holes: tuple[HoleCoord, ...] = ()


def wiring_notes(document: PerfDocument, lookup: object) -> tuple[WiringNote, ...]:
    """What is worth a look in this board's wiring; nothing until the engine says."""
    del document, lookup
    return ()
