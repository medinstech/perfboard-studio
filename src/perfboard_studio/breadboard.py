"""Breadboard: the board whose connections are a pattern nobody can change.

A solderless breadboard is a block of plastic over rows of spring clips. Every lead pushed
into a hole is gripped by the clip under it, and every hole over one clip is joined to the
others: five holes across each half of a column, and a long run down each power rail.
Nothing is soldered and nothing can be cut, so the whole design problem is WHERE THINGS GO
-- two pins of different nets in one clip are shorted by the board, and no wire changes
that. It is stripboard's problem with the scissors taken away (see ``stripboard.py``,
whose segments this module supplies on a breadboard).

THE PATTERN IS THE BOARD'S SHAPE, not a document field. A breadboard is ``board.type ==
"breadboard"`` and its grid says the rest: 20 rows is a board with power rails, 12 rows is
one without, and the columns are the numbers printed along it. Nothing new goes in the
file, so the format does not move -- the same reason ``BodySpec`` keeps its numbers in an
id rather than a field.

WHAT THE PATTERN IS, MEASURED rather than remembered: Fritzing's drawing of the RSR
03MB102 (``core/breadboard2.fzp`` in fritzing-parts), the 830-point board sold in every
starter kit, read for hole positions and rail colours only (see ``docs/prior-art.md``).
Every hole sits on the 0.1 inch grid. From the top, with column 1 on the left:

    row  0      - rail   (blue line above it)
    row  1      + rail   (red line below it)
    rows 2-3    no holes
    rows 4-8    j i h g f      one clip per column
    rows 9-10   no holes       the channel a DIP straddles: 0.3 inch from e to f
    rows 11-15  e d c b a      one clip per column
    rows 16-17  no holes
    row  18     - rail   (blue line above it)
    row  19     + rail   (red line below it)

A board without rails is rows 4 to 15 alone. A rail is holes in groups of five with one
column left out between groups, as many groups as the board is long, centred: on 63
columns that is columns 3 to 61, which is where the MB102's fifty holes are. On Fritzing's
half-size board the rail holes sit 0.37 of a pitch off the columns; a hole here is a grid
position, so they are put on the nearest column, which is columns 1 to 29. Nobody reads a
rail hole by its number -- a lead goes "into the + rail" -- so the rounding costs nothing a
builder can see, and it is written here so nobody mistakes it for a measurement.

A SOLDERABLE BREADBOARD IS THE SAME PATTERN IN COPPER (``"solderable-breadboard"``): a
printed circuit board -- BusBoard's SB830, Adafruit's Perma-Proto and their copies -- whose
holes are where a breadboard's are and whose strips join the same five, sold so that a
circuit that works on the breadboard moves to it hole for hole and is soldered. So there
are two questions in this module and they must not be confused:
:func:`has_breadboard_pattern` is about the HOLES -- which exist, what joins them, what they
are called, the rails -- and is true of both; :func:`is_breadboard` is about the PLASTIC --
nothing soldered, nothing drilled, leads held in clips -- and is true only of the
solderless one. Everything that solders, drills, trims and is guided with an iron treats a
solderable breadboard as the soldered board it is.

What is modelled is the CORE every such board shares, chosen over any one maker's board
(2026-10-19): the solderless pattern below, in the same three lengths. Makers add their own
on top -- BusBoard's SB830 has two extra rails and two-hole pads down the channel, and is
47 mm wide, which puts its rails closer to the strips than the solderless grid does -- and
none of that is drawn. The border defaults to Adafruit's half-size Perma-Proto, 81 x 51 mm
over 30 x 20 holes, which is the solderless grid with no rows moved; a board with more
round it, or with mounting holes, is set in Board Setup like any other.

A WIDE CHANNEL is for the modules that do not fit the 0.3 inch one. An ESP32 devkit is
1000 mil across its pins, a Pico 700, and on an ordinary board the first leaves no hole
free beside any pin and the second two; so people print a body with the channel opened up
and move the clips of an ordinary board into it -- lhm0's wide-mcu-breadboard is the one
measured here (``docs/prior-art.md``). Everything but the channel is the ordinary board:
the same clips, the same rails, three pitches between a rail and the strip beside it. So
the channel is still THE BOARD'S SHAPE: every pitch it is wider than 0.3 inch is one more
row of grid, and the rows say how wide it is (:func:`channel_of`) -- 20 to 32 with rails,
12 to 19 without.

Some of those bodies keep the ordinary channel for part of their length, so a DIP can
still straddle it beside the module: lhm0 calls them "flex". That is the one thing the
grid cannot say, so it is the one field, ``Board.narrow_channel_cols``: how many columns,
counted from column 1, have the 0.3 inch channel with their two strips of clips moved in
to meet it. Each strip moves by half of what the channel lost. Where that is a whole
number of pitches the narrow part is exactly where the body has it -- lhm0's 900 mil flex
board, 9 against 3. Where it is not -- the 1000 mil one, 10 against 3 -- the body's narrow
strips stand half a pitch off the grid the rest of it is on, and a hole here is a grid
position, so the lower strip moves in by one row more than the upper and the narrow part
is drawn half a pitch (1.27 mm) above where it is. The clips, the names and every
connection are exact; only the picture is rounded, as the half-size board's rails are
above, and it is written here so nobody mistakes it for a measurement. A strip keeps its letters wherever it
is, so in the narrow part ``e`` is a different row of the grid from ``e`` in the wide
part -- which is why a letter is asked for by row AND column.

Pure and deterministic, and it imports nothing but the model: ``geometry`` asks this
module which positions have no hole and what a hole is called, so it cannot ask anything
of ``geometry`` in return.
"""

from __future__ import annotations

import functools
import re
from typing import Literal

from .model import STANDARD_PITCH_MM, Board, BoardType, HoleCoord, Mm, NetClass

#: Rows on a breadboard with power rails, and on one without, at the ordinary channel.
ROWS_WITH_RAILS = 20
ROWS_WITHOUT_RAILS = 12

#: The ordinary channel, from row e to row f, in pitches: 0.3 inch, what a DIP straddles.
STANDARD_CHANNEL = 3
#: The widest channel a board with rails may have, in pitches: 1.5 inch, room for any
#: module made. Without rails the rows run out first, at 10 (see :func:`channel_of`).
MAX_CHANNEL = 15
#: The channels the wide boards are printed for, in mil: the Nano, the Pico, a narrow and
#: a standard ESP32 devkit. The Board Setup list, not a limit -- any whole pitch will do.
WIDE_CHANNEL_MILS: tuple[int, ...] = (600, 700, 900, 1000)

#: Which of the four power rails a row is. "top" is the rail pair beside row j.
type Rail = Literal["top-", "top+", "bottom-", "bottom+"]

#: Which class of net each rail is FOR: what the line printed beside it says. A rail is
#: electrically just a long clip, and a signal can be run down one -- but everybody who
#: looks at the board reads the red line as the supply and the blue as ground, so a pin of
#: any other net standing in a rail is a board that lies about itself. The placer counts
#: it with the pairs nothing can separate, the planner reports it, and DRC warns about it
#: (``wrong-rail``); all three ask :func:`rail_takes`.
RAIL_CLASS: dict[Rail, NetClass] = {
    "top-": "ground",
    "top+": "power",
    "bottom-": "ground",
    "bottom+": "power",
}

#: What each row is, top to bottom, on a board with rails: a strip letter, a rail, or
#: None where the grid has no hole. Read off the MB102 -- see the module docstring.
_ROWS_WITH_RAILS: tuple[str | None, ...] = (
    "top-", "top+", None, None,
    "j", "i", "h", "g", "f",
    None, None,
    "e", "d", "c", "b", "a",
    None, None, "bottom-", "bottom+",
)
_ROWS_WITHOUT_RAILS: tuple[str | None, ...] = _ROWS_WITH_RAILS[4:16]
_UPPER = ("j", "i", "h", "g", "f")
_LOWER = ("e", "d", "c", "b", "a")

#: Holes in one group of a rail, and the columns left out between groups.
RAIL_GROUP = 5

#: How long a breadboard is, in columns, and how many rows it has: the three sizes sold.
#: The mini has no rails. Keyed on what the board is called, which is its tie-point count.
SIZES: dict[str, tuple[int, int]] = {
    "170": (17, ROWS_WITHOUT_RAILS),
    "400": (30, ROWS_WITH_RAILS),
    "830": (63, ROWS_WITH_RAILS),
}

#: How thick the block is, clips and all. BusBoard gives its BB830 as 8.5 mm.
THICKNESS_MM: Mm = 8.5

#: How deep a lead goes before its clip holds it. It stops there, inside the plastic,
#: rather than coming out of the underside to be trimmed -- one lead for the 3D view and
#: the STEP export alike, as ``footprints.LEAD_TRIM_MM`` is for a soldered board.
CLIP_DEPTH_MM: Mm = 4.0

#: The square opening a lead goes into, taken as a drill: a clip grips 0.3 to 0.8 mm leads.
#: ``wire-too-thick-for-hole`` reads it, which is the one rule that ever asks.
HOLE_MM: Mm = 0.8

#: A breadboard has no pad; the board model asks for one larger than the hole, and nothing
#: on a breadboard reads it.
_PAD_MM: Mm = 1.0

#: Plastic past the outermost hole centres beyond the usual half pitch, along the board
#: and across it. From BusBoard's 165.1 x 54.6 mm for the BB830 over the MB102's grid.
BORDER_X_MM: Mm = 2.54
BORDER_Y_MM: Mm = 1.9

#: A solderable breadboard is an ordinary 1.6 mm FR-4 board.
SOLDERABLE_THICKNESS_MM: Mm = 1.6
#: Drilled for IC legs and square header posts: BusBoard gives the SB830's as 0.042 in.
SOLDERABLE_HOLE_MM: Mm = 1.07
#: The copper round each hole, where it widens out of its strip.
SOLDERABLE_PAD_MM: Mm = 1.8
#: Board past the outermost hole centres beyond the usual half pitch: Adafruit's half-size
#: Perma-Proto, 81 x 51 mm over 30 x 20 holes (see the module docstring).
SOLDERABLE_BORDER_X_MM: Mm = 2.4
SOLDERABLE_BORDER_Y_MM: Mm = 0.1

#: Every board type laid out in the breadboard's pattern.
PATTERN_TYPES: frozenset[str] = frozenset({"breadboard", "solderable-breadboard"})


def is_breadboard(board: Board) -> bool:
    """A SOLDERLESS breadboard: plastic and clips, nothing soldered, nothing drilled."""
    return board.type == "breadboard"


def is_solderable_breadboard(board: Board) -> bool:
    return board.type == "solderable-breadboard"


def has_breadboard_pattern(board: Board) -> bool:
    """The breadboard's holes, joins and names: true of the solderless board and the
    solderable one alike. See the module docstring for the two questions."""
    return board.type in PATTERN_TYPES


def has_rails(board: Board) -> bool:
    return has_breadboard_pattern(board) and board.rows >= ROWS_WITH_RAILS


def channel_of(board: Board) -> int:
    """How far apart rows e and f are, in pitches, where the channel is widest: 3 on an
    ordinary board, one more for every row past 20 (with rails) or 12 (without)."""
    base = ROWS_WITH_RAILS if board.rows >= ROWS_WITH_RAILS else ROWS_WITHOUT_RAILS
    return STANDARD_CHANNEL + board.rows - base


def rows_for(channel: int, rails: bool = True) -> int:
    """The rows of a breadboard with this channel, in pitches -- :func:`channel_of`'s
    inverse."""
    return (ROWS_WITH_RAILS if rails else ROWS_WITHOUT_RAILS) + channel - STANDARD_CHANNEL


def board_problem(board: Board) -> str | None:
    """Why this cannot be a breadboard, or None if it can.

    One answer for ``board.set`` and for loading a file, which refuse the same things for
    the same reason (CLAUDE.md, "persist.py refuses at load what board.set refuses").
    """
    if not has_breadboard_pattern(board):
        if board.narrow_channel_cols:
            return "Only a breadboard has a channel to narrow; this board is not one."
        return None
    widest = rows_for(MAX_CHANNEL)
    if not ROWS_WITHOUT_RAILS <= board.rows <= widest:
        return (
            f"A breadboard has {ROWS_WITH_RAILS} rows with power rails or "
            f"{ROWS_WITHOUT_RAILS} without, and one more for every pitch its channel is wider "
            f"than 0.3 inch (up to {widest} rows); this one has {board.rows}."
        )
    if board.pitch != STANDARD_PITCH_MM:
        return f"A breadboard's holes are {STANDARD_PITCH_MM} mm apart; this one says {board.pitch}."
    if has_rails(board) and board.cols < RAIL_GROUP:
        return f"A breadboard with power rails needs at least {RAIL_GROUP} columns."
    narrow = board.narrow_channel_cols
    if narrow:
        channel = channel_of(board)
        if not 0 < narrow < board.cols:
            return (
                f"The narrow part of the channel must leave some of the {board.cols} columns "
                f"wide; it is {narrow}."
            )
        if channel == STANDARD_CHANNEL:
            return "The channel is 0.3 inch already; there is nothing to narrow."
    return None


def pattern_board(kind: BoardType, cols: int, rows: int, narrow_channel_cols: int = 0) -> Board:
    """A board of either breadboard kind, with that kind's thickness, holes and border.

    THE ONE PLACE those numbers are chosen by kind, because they follow the kind and not
    the grid: turning a solderless breadboard into a solderable one keeps every hole and
    changes 8.5 mm of plastic into 1.6 mm of FR-4. Every caller that changes a board's
    kind -- the window, the MCP server, the move from one to the other -- builds through
    here, so none of them is left carrying the other kind's drill.
    """
    if kind == "breadboard":
        thickness, pad, drill = THICKNESS_MM, _PAD_MM, HOLE_MM
        border_x, border_y = BORDER_X_MM, BORDER_Y_MM
    elif kind == "solderable-breadboard":
        thickness, pad, drill = SOLDERABLE_THICKNESS_MM, SOLDERABLE_PAD_MM, SOLDERABLE_HOLE_MM
        border_x, border_y = SOLDERABLE_BORDER_X_MM, SOLDERABLE_BORDER_Y_MM
    else:
        raise ValueError(f"{kind!r} is not laid out in the breadboard's pattern.")
    return Board(
        type=kind,
        cols=cols,
        rows=rows,
        pitch=STANDARD_PITCH_MM,
        thickness=thickness,
        material="FR4",
        pad_diameter=pad,
        drill_diameter=drill,
        border_x_mm=border_x,
        border_y_mm=border_y,
        narrow_channel_cols=narrow_channel_cols,
    )


def breadboard(size: str, channel: int = STANDARD_CHANNEL, narrow_channel_cols: int = 0) -> Board:
    """A breadboard of one of the ``SIZES``, its channel ``channel`` pitches across."""
    cols, rows = SIZES[size]
    return pattern_board(
        "breadboard", cols, rows + channel - STANDARD_CHANNEL, narrow_channel_cols
    )


def solderable_breadboard(size: str) -> Board:
    """A solderable breadboard of one of the ``SIZES``: the same holes, in copper."""
    return pattern_board("solderable-breadboard", *SIZES[size])


def size_of(board: Board) -> str | None:
    """Which of the ``SIZES`` a breadboard of either kind is, whatever its channel, or None."""
    if not has_breadboard_pattern(board):
        return None
    shape = (board.cols, board.rows - channel_of(board) + STANDARD_CHANNEL)
    return next((name for name, size in SIZES.items() if size == shape), None)


@functools.cache
def _layout(rails: bool, channel: int, moved_in: int, lower_moved_in: int | None = None) -> tuple[str | None, ...]:
    """What each row is, top to bottom, for a column whose channel is ``channel`` pitches
    and whose upper strip stands ``moved_in`` rows in from where the widest channel has it,
    the lower ``lower_moved_in`` (the same, unless told)."""
    lower = moved_in if lower_moved_in is None else lower_moved_in
    core = (None,) * moved_in + _UPPER + (None,) * (channel - 1) + _LOWER + (None,) * lower
    if not rails:
        return core
    return ("top-", "top+", None, None, *core, None, None, "bottom-", "bottom+")


def _roles(board: Board, col: int | None = None) -> tuple[str | None, ...]:
    """What each row is in this column; ``None`` asks about the wide part, which is every
    column of a board with no narrow part and where the rails and the print are read."""
    channel = channel_of(board)
    if col is not None and col < board.narrow_channel_cols:
        # The lower strip takes the odd row when the strips cannot move in by the same
        # amount, which leaves the narrow part drawn half a pitch high (row 0 is the top;
        # see the module docstring).
        lost = channel - STANDARD_CHANNEL
        return _layout(has_rails(board), STANDARD_CHANNEL, lost // 2, lost - lost // 2)
    return _layout(has_rails(board), channel, 0)


def _role(board: Board, row: int, col: int | None = None) -> str | None:
    roles = _roles(board, col)
    return roles[row] if 0 <= row < len(roles) else None


def rail_columns(board: Board) -> frozenset[int]:
    """The columns a rail has a hole in: groups of five, one column between, centred."""
    groups = (board.cols + 1) // (RAIL_GROUP + 1)
    span = groups * (RAIL_GROUP + 1) - 1
    first = (board.cols - span) // 2
    return frozenset(
        first + offset
        for offset in range(span)
        if offset % (RAIL_GROUP + 1) != RAIL_GROUP
    )


def channel_stretches(board: Board) -> tuple[tuple[int, int, int, int], ...]:
    """The channel down the middle as stretches of equal width: ``(first column, column
    past the last, row f, row e)`` for each. One on an ordinary board or a wide one, two
    where a wide channel narrows. What both views draw the groove from, so it is one shape."""
    narrow = board.narrow_channel_cols
    stretches = ((0, narrow), (narrow, board.cols)) if narrow else ((0, board.cols),)
    out: list[tuple[int, int, int, int]] = []
    for first, end in stretches:
        roles = _roles(board, first)
        out.append((first, end, roles.index("f"), roles.index("e")))
    return tuple(out)


def strip_letter(board: Board, row: int, col: int | None = None) -> str | None:
    """The letter printed beside a row of clips, or None for a rail or a row with no holes.

    In ``col``, because where the channel narrows its strips move; ``None`` is the wide
    part, which on a board that never narrows is every column."""
    role = _role(board, row, col)
    return role if role is not None and len(role) == 1 else None


def rail_of(board: Board, row: int) -> Rail | None:
    role = _role(board, row)
    if role in ("top-", "top+", "bottom-", "bottom+"):
        return role  # type: ignore[return-value]
    return None


def rail_takes(rail: Rail, net_class: NetClass | None) -> bool:
    """Whether a pin of a net of this class belongs in this rail. None is a pin no net
    declares, which belongs in none: it would be joined to the supply without anybody
    having asked for it."""
    return net_class == RAIL_CLASS[rail]


def has_hole(board: Board, hole: HoleCoord) -> bool:
    """Whether there is a hole at this grid position at all."""
    if not (0 <= hole.col < board.cols and 0 <= hole.row < board.rows):
        return False
    if strip_letter(board, hole.row, hole.col) is not None:
        return True
    return rail_of(board, hole.row) is not None and hole.col in rail_columns(board)


def missing_holes(board: Board) -> frozenset[HoleCoord]:
    """Every grid position on a breadboard that has no hole -- the channel, the gaps
    beside the rails, the columns a rail leaves out. Empty on any other board."""
    if not has_breadboard_pattern(board):
        return frozenset()
    return frozenset(
        HoleCoord(col, row)
        for row in range(board.rows)
        for col in range(board.cols)
        if not has_hole(board, HoleCoord(col, row))
    )


def clip_of(board: Board, hole: HoleCoord) -> tuple[int, int] | None:
    """The clip a hole is over, or None where there is no hole.

    A column's upper five holes are ``(col, 0)``, its lower five ``(col, 1)``, and a rail
    is ``(row, -1)``: unique on one board, which is all a segment id has to be.
    """
    if not has_breadboard_pattern(board) or not has_hole(board, hole):
        return None
    if rail_of(board, hole.row) is not None:
        return (hole.row, -1)
    letter = strip_letter(board, hole.row, hole.col)
    return (hole.col, 0 if letter is not None and letter >= "f" else 1)


def clip_holes(board: Board, hole: HoleCoord) -> tuple[HoleCoord, ...]:
    """Every hole over the same clip as this one, itself included; empty where there is
    no hole."""
    clip = clip_of(board, hole)
    if clip is None:
        return ()
    if clip[1] == -1:
        return tuple(HoleCoord(col, hole.row) for col in sorted(rail_columns(board)))
    return tuple(
        HoleCoord(hole.col, row)
        for row in range(board.rows)
        if clip_of(board, HoleCoord(hole.col, row)) == clip
    )


# ---------------------------------------------------------------------------
# What a hole is called
# ---------------------------------------------------------------------------

#: How a rail hole is written: the rail, then the column it stands beside.
_RAIL_PREFIX: dict[Rail, str] = {"top-": "T-", "top+": "T+", "bottom-": "B-", "bottom+": "B+"}
_PREFIX_RAIL: dict[str, Rail] = {prefix: rail for rail, prefix in _RAIL_PREFIX.items()}

_STRIP_NAME = re.compile(r"([a-j])([1-9][0-9]*)")
_RAIL_NAME = re.compile(r"([TB][+-])([1-9][0-9]*)")


def hole_name(board: Board, hole: HoleCoord) -> str | None:
    """A hole as the breadboard itself prints it: "e12", or "T+12" on a rail.

    The letter is the row's and the number the column's, the way round every breadboard
    prints them -- the opposite of a perfboard address, and lower case, so the two can
    never be mistaken for each other. None where there is no hole.
    """
    if not has_hole(board, hole):
        return None
    rail = rail_of(board, hole.row)
    if rail is not None:
        return f"{_RAIL_PREFIX[rail]}{hole.col + 1}"
    return f"{strip_letter(board, hole.row, hole.col)}{hole.col + 1}"


def parse_hole_name(board: Board, text: str) -> HoleCoord | None:
    """The inverse of :func:`hole_name`; None for anything that is not a hole here."""
    rows = _roles(board)
    found: HoleCoord | None = None
    if (match := _STRIP_NAME.fullmatch(text)) is not None:
        col = int(match.group(2)) - 1
        found = HoleCoord(col, _roles(board, col).index(match.group(1)))
    elif (match := _RAIL_NAME.fullmatch(text)) is not None:
        rail = _PREFIX_RAIL[match.group(1)]
        if rail not in rows:
            return None
        found = HoleCoord(int(match.group(2)) - 1, rows.index(rail))
    if found is None or not has_hole(board, found):
        return None
    return found

