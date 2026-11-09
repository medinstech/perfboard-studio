"""Stripboard: the board that arrives with its copper already joined up.

A pad-per-hole board is a grid of isolated islands and every connection is something you
ADD. Stripboard (Veroboard) is the opposite: whole rows of holes are already one strip of
copper, so the connections are already there and the design problem is deciding **where
to break them**. Everything else in this project is about adding copper; this module is
about copper that is subtracted.

TRACK CUTS. A drilled cut removes the pad at ``TrackCut.at``. A scored cut carries
both adjacent hole addresses and separates their copper while leaving both pads intact.
A pin in a drilled-out hole is soldered to nothing, which DRC reports.

WHAT A SEGMENT IS. One run of copper: the holes of one strip between two cuts, or between
a cut and the edge of the board. Two pins on the same segment are connected, and the
board did it, not the user. That is the whole of stripboard connectivity, and
``connectivity.py`` is where it is applied.

WHICH WAY THE STRIPS RUN is ``board.strip_axis``, and ``None`` means horizontal: the
stock is sold with the strips along the long side, and a board that declares nothing has
to behave like the board people actually buy rather than raising.

A BREADBOARD IS ASKED HERE TOO. Its clips are segments nobody can cut, so
:func:`segment_of` answers for it from ``breadboard.clip_of`` and :func:`cut_between`
never offers a cut on it -- which is how ``connectivity``, ``striproute`` and the placer,
all written against segments, take a breadboard without a line about plastic.

Pure and deterministic, like everything above ``ui/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .breadboard import clip_holes, clip_of, has_breadboard_pattern, is_solderable_breadboard
from .geometry import hole_key, is_inside_board
from .model import Board, HoleCoord, PerfDocument


@dataclass(frozen=True, slots=True)
class StripSegment:
    """One unbroken run of the board's own copper.

    ``index`` is the strip (the row for horizontal strips, the column for vertical ones)
    and ``ordinal`` counts segments along it from the top-left, so the pair identifies a
    segment without holding its holes -- which is what connectivity compares.
    """

    index: int
    ordinal: int
    holes: tuple[HoleCoord, ...]

    @property
    def id(self) -> tuple[int, int]:
        return (self.index, self.ordinal)

    @property
    def is_empty(self) -> bool:
        return not self.holes


#: How far apart along one strip two pins of different nets have to sit before the board
#: can be separated at all, in holes.
#:
#: The automatic planner chooses drilled cuts: to break the track between two
#: pins there has to BE a hole between them to put the drill in. Two pins in neighbouring
#: holes are joined by the board and no amount of routing changes that -- the fix is to
#: move a part, which is why ``placer.py`` reads this number as well as ``cut_between``
#: below. One fact, two consumers: an optimiser that packs parts into an arrangement its
#: own planner then refuses to wire is worse than no optimiser.
MIN_SEPARABLE_GAP = 2


def is_stripboard(board: Board) -> bool:
    return board.type == "stripboard"


def board_joins_holes(board: Board) -> bool:
    """Whether the board itself joins holes before anything is fitted: stripboard's strips
    and a breadboard's clips. On every other board each hole is an island."""
    return is_stripboard(board) or has_breadboard_pattern(board)


def strip_axis(board: Board) -> Literal["horizontal", "vertical"]:
    """Which way the strips run. ``None`` is horizontal -- see the module docstring."""
    return board.strip_axis or "horizontal"


def cut_holes(doc: PerfDocument) -> frozenset[str]:
    """Holes whose copper has been drilled away, as ``geometry.hole_key`` strings.

    Empty on any board that is not stripboard, so a caller does not have to ask first: a
    pad-per-hole board with a stray cut in its file (hand-edited, or converted from a
    stripboard) has no tracks for a cut to mean anything to.
    """
    if not is_stripboard(doc.board):
        return frozenset()
    return frozenset(
        hole_key(cut.at) for cut in doc.cuts
        if cut.to is None and is_inside_board(cut.at, doc.board)
    )


def strip_index(board: Board, hole: HoleCoord) -> int:
    """Which strip a hole is on: its row for horizontal strips, its column for vertical."""
    return hole.row if strip_axis(board) == "horizontal" else hole.col


def position_along(board: Board, hole: HoleCoord) -> int:
    """How far along its own strip a hole sits: its column for horizontal strips, its row
    for vertical ones. The other half of ``strip_index``, and what orders the pins on a
    strip when the planner walks them looking for two nets sharing one."""
    return hole.col if strip_axis(board) == "horizontal" else hole.row


def _strip_length(board: Board) -> int:
    return board.cols if strip_axis(board) == "horizontal" else board.rows


def _strip_count(board: Board) -> int:
    return board.rows if strip_axis(board) == "horizontal" else board.cols


def _hole_at(board: Board, index: int, position: int) -> HoleCoord:
    if strip_axis(board) == "horizontal":
        return HoleCoord(position, index)
    return HoleCoord(index, position)


def segment_of(doc: PerfDocument, hole: HoleCoord) -> tuple[int, int] | None:
    """The segment a hole belongs to, or None if it belongs to none.

    None means one of three things and they are all "this hole is not joined to anything
    by the board": the board is not stripboard, the hole is off it, or the copper there
    has been cut away.

    The ordinal is the number of cuts before this hole along its own strip, which makes
    it stable under adding a cut somewhere else on the board -- and cheap, since it never
    walks the strip.

    On a breadboard it is the clip under the hole, and None where there is no hole.
    """
    if has_breadboard_pattern(doc.board):
        return clip_of(doc.board, hole)
    if not is_stripboard(doc.board) or not is_inside_board(hole, doc.board):
        return None
    cuts = cut_holes(doc)
    if hole_key(hole) in cuts:
        return None

    board = doc.board
    index = strip_index(board, hole)
    position = position_along(board, hole)
    before = sum(
        1
        for cut in doc.cuts
        if is_inside_board(cut.at, board)
        and strip_index(board, cut.at) == index
        and min(position_along(board, cut.at), position_along(board, cut.to or cut.at)) < position
    )
    return (index, before)


def segments(doc: PerfDocument) -> tuple[StripSegment, ...]:
    """Every run of copper on the board, in reading order.

    For rendering and for the build guide. Connectivity does not use this -- it asks
    ``segment_of`` about the holes that actually carry something, because a 30 x 20 board
    has 600 holes and only a few dozen of them are soldered into.

    Empty on a solderless breadboard, whose clips are under the plastic and drawn as its
    print. On a SOLDERABLE one the clips are copper you can see, so each is a run: a column's
    five holes, or a whole rail. ``index`` and ``ordinal`` are the clip's own id there
    (``breadboard.clip_of``), which is unique on the board as a segment id has to be.
    """
    if is_solderable_breadboard(doc.board):
        runs: dict[tuple[int, int], list[HoleCoord]] = {}
        for col in range(doc.board.cols):
            for row in range(doc.board.rows):
                clip = clip_of(doc.board, HoleCoord(col, row))
                if clip is not None:
                    runs.setdefault(clip, []).append(HoleCoord(col, row))
        return tuple(
            StripSegment(index, ordinal, tuple(sorted(holes, key=lambda h: (h.row, h.col))))
            for (index, ordinal), holes in sorted(runs.items())
        )
    if not is_stripboard(doc.board):
        return ()

    board = doc.board
    cuts = cut_holes(doc)
    boundaries: dict[int, set[int]] = {}
    for cut in doc.cuts:
        if cut.to is not None:
            index = strip_index(board, cut.at)
            position = min(position_along(board, cut.at), position_along(board, cut.to))
            boundaries.setdefault(index, set()).add(position)
    out: list[StripSegment] = []
    for index in range(_strip_count(board)):
        ordinal = 0
        run: list[HoleCoord] = []
        for position in range(_strip_length(board)):
            if position - 1 in boundaries.get(index, set()):
                if run:
                    out.append(StripSegment(index, ordinal, tuple(run)))
                    run = []
                ordinal += 1
            hole = _hole_at(board, index, position)
            if hole_key(hole) in cuts:
                if run:
                    out.append(StripSegment(index, ordinal, tuple(run)))
                    run = []
                # A cut ends a segment whether or not one had started, so the ordinal
                # counts cuts rather than segments -- which is what segment_of computes
                # without walking, and the two have to agree.
                ordinal += 1
                continue
            run.append(hole)
        if run:
            out.append(StripSegment(index, ordinal, tuple(run)))
    return tuple(out)


def segment_holes(doc: PerfDocument, hole: HoleCoord) -> tuple[HoleCoord, ...]:
    """Every hole joined to this one by the board's own copper, including itself.

    Empty when the hole is cut, off the board, or the board has no strips.
    """
    if has_breadboard_pattern(doc.board):
        return clip_holes(doc.board, hole)
    id_ = segment_of(doc, hole)
    if id_ is None:
        return ()
    board = doc.board
    index = strip_index(board, hole)
    first = last = position_along(board, hole)
    while first > 0 and segment_of(doc, _hole_at(board, index, first - 1)) == id_:
        first -= 1
    while last + 1 < _strip_length(board) and segment_of(doc, _hole_at(board, index, last + 1)) == id_:
        last += 1
    return tuple(_hole_at(board, index, pos) for pos in range(first, last + 1))


def joined_by_board(doc: PerfDocument, a: HoleCoord, b: HoleCoord) -> bool:
    """Whether the BOARD joins these two holes, before anything was soldered."""
    id_a = segment_of(doc, a)
    return id_a is not None and id_a == segment_of(doc, b)


def cut_between(
    doc: PerfDocument,
    a: HoleCoord,
    b: HoleCoord,
    occupied: frozenset[str] = frozenset(),
) -> HoleCoord | None:
    """A free hole on the strip between two holes, to break the copper joining them.

    The answer to "these two pins are on the same track and belong to different nets".
    Returns None when they are not on one segment (nothing to cut), or when every hole
    between them is occupied -- which is a real dead end on stripboard and the reason
    placement matters more here than on a pad-per-hole board.

    ``occupied`` is hole keys a drill may not go through, which the caller has already:
    ``occupancy.build_occupancy(...).occupied_holes()`` is the usual source. Passing
    nothing means "the board is empty", which is true of a board with nothing on it and
    the caller's problem otherwise -- this module deliberately knows nothing about
    footprints.

    The hole nearest the MIDDLE is preferred: a cut hard against a pin is the one most
    likely to lift the neighbouring pad when it is drilled, and the middle of the run is
    also where a later part is least likely to want to sit.
    """
    if not is_stripboard(doc.board) or not joined_by_board(doc, a, b) or a == b:
        return None  # Nothing to cut, or -- on a breadboard -- nothing that CAN be cut.

    board = doc.board
    index = strip_index(board, a)
    lo, hi = sorted((position_along(board, a), position_along(board, b)))
    if hi - lo < MIN_SEPARABLE_GAP:
        return None  # Adjacent pins: there is no hole between them to drill out.

    middle = (lo + hi) / 2
    candidates = [
        _hole_at(board, index, position)
        for position in range(lo + 1, hi)
        if hole_key(_hole_at(board, index, position)) not in occupied
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda h: (abs(position_along(board, h) - middle), position_along(board, h)))

