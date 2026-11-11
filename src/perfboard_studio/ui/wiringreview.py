"""What is worth a look in the wiring: the Problems drawer's Wiring group, and the counts
the step card keeps after Auto-wire.

Not DRC. A wire lying over a pin, or over where other copper ends, or stacked over many
others, is a board that works and is harder to build than it has to be -- a cost, not a
defect -- so it never counts as a problem, never blocks the Build step and never moves a
golden. It is said so the one bad wire can be found: Auto-wire used to finish on "No
problems" over a board with a wire lying across 44 pins.

The counts are the engine's (``wiringstats``, the numbers the autowire scoreboard holds the
router to), never a second computation here: one fact, several askers, like the wire
gauge. Each note's count is the engine's total, and the wires it selects are the entries
that total is summed from, so the two cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

from perfboard_studio.model import HoleCoord
from perfboard_studio.wiringstats import WiringStats

from .i18n import counted, language, t

#: A wire this many wires clear of the board is worth a look: each step is one more wire it
#: has to be laid over, in order, and soldered past. Two is any crossing of a crossing;
#: three is where a stack starts to be the hard part of the board.
DEEP_STACK = 3


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


def wiring_notes(stats: WiringStats) -> tuple[WiringNote, ...]:
    """What is worth a look in this board's wiring, worst kind first."""
    wires = [entry for entry in stats.conductors if entry.is_wire]
    notes: list[WiringNote] = []

    loops = [cid for loop in stats.loops for cid in loop]
    if loops:
        # First: no order of laying them works, which is not true of anything below.
        notes.append(
            WiringNote(
                key="loops",
                title=counted(
                    len(stats.loops),
                    t("{count} ring of wires, each over another's end: none can go in first"),
                    t("{count} rings of wires, each over another's end: none can go in first"),
                ),
                conductor_ids=tuple(dict.fromkeys(loops)),
            )
        )
    over_pins = [entry for entry in wires if entry.over_pins]
    if over_pins:
        notes.append(
            WiringNote(
                key="over-pins",
                title=counted(
                    stats.over_pins,
                    t("{count} place a wire lies over a pin"),
                    t("{count} places a wire lies over a pin"),
                ),
                conductor_ids=tuple(entry.conductor_id for entry in over_pins),
                holes=tuple(hole for entry in over_pins for hole in entry.over_pins),
            )
        )
    over_ends = [entry for entry in wires if entry.over_ends]
    if over_ends:
        notes.append(
            WiringNote(
                key="over-ends",
                title=counted(
                    stats.over_ends,
                    t("{count} place a wire lies over where other copper ends"),
                    t("{count} places a wire lies over where other copper ends"),
                ),
                conductor_ids=tuple(entry.conductor_id for entry in over_ends),
                holes=tuple(hole for entry in over_ends for hole in entry.over_ends),
            )
        )
    deep = [entry for entry in wires if entry.level >= DEEP_STACK]
    if deep:
        notes.append(
            WiringNote(
                key="stacked",
                title=counted(
                    len(deep),
                    t("{count} wire stacked three or more deep"),
                    t("{count} wires stacked three or more deep"),
                ),
                conductor_ids=tuple(entry.conductor_id for entry in deep),
            )
        )
    return tuple(notes)


def wiring_summary(stats: WiringStats) -> str:
    """The wiring in one line, "53 wires, 1.2 m, 77 bends · 12 solder traces"; "" with no
    copper on the board."""
    wires = sum(1 for entry in stats.conductors if entry.is_wire)
    runs = sum(1 for entry in stats.conductors if entry.pads)
    said: list[str] = []
    if wires:
        said.append(
            ", ".join(
                (
                    counted(wires, t("{count} wire"), t("{count} wires")),
                    length_said(stats.wire_mm),
                    counted(stats.bends, t("{count} bend"), t("{count} bends")),
                )
            )
        )
    if runs:
        said.append(counted(runs, t("{count} solder trace"), t("{count} solder traces")))
    return "  ·  ".join(said)


def length_said(mm: float) -> str:
    """A length of wire as it is cut from the reel: millimetres up to a metre, then metres
    to one decimal, with the decimal mark the window's language writes."""
    if mm < 1000:
        return f"{mm:.0f} mm"
    metres = f"{mm / 1000:.1f}"
    return f"{metres.replace('.', ',') if language() == 'tr' else metres} m"
