"""Board families: the kinds of board people buy, and the sizes each is sold in.

A stock board is not a size. It is a PRODUCT -- a green double-sided board with a stadium
strip down its short edges, bare corner holes in its border, letters along the top and
small numbers between the grid and the strip, "5cmX7cm" in the bottom border -- and the
same product comes in eight sizes. Saying that once per product, rather than once per
size, is what this module is for: a ``BoardFamily`` is the product, a ``BoardSize`` one
board of it, and ``board_for`` makes the board, its strips and its screw holes that the
existing ``board.applyPreset`` command puts on the document in one undo step.

A user's own board is the same dataclass (``user=True``), round-tripped through
``family_to_json`` / ``family_from_json``. Both are pure: the HOST stores the text.

Pure like the rest of the engine: no clock, no file, no Qt. Above ``geometry`` (it asks
it for the corner bores and the strip's room) and below ``commands``.

Everything a family says is measured off a photograph of the board or read off a
supplier's listing, and says which. A grid count two suppliers disagree on is two
``BoardSize`` variants of one size, not one guess.
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, get_args

from .geometry import (
    MAX_LEGEND_DIGITS,
    OUTSIDE_FINGER_MIN_MM,
    board_text_problem,
    corner_mounting_holes,
    outside_finger_room_mm,
)
from .model import (
    Board,
    BoardEdge,
    BoardFace,
    BoardFinish,
    BoardLabels,
    BoardMask,
    BoardMaterial,
    BoardText,
    EdgeConnector,
    FingerShape,
    LetterEdges,
    Mm,
    MountingHole,
    NumberEdges,
    PadAxis,
    PadShape,
)
from .persist import PAD_SHAPES

# ---------------------------------------------------------------------------
# Vocabularies -- ``TypeAlias`` so that ``get_args`` reads them at run time (model.py)
# ---------------------------------------------------------------------------

#: The board types a family can be. A solderless breadboard is not: it is one product in
#: one pattern, chosen as a board type of its own.
FamilyBoardType: TypeAlias = Literal[  # noqa: UP040
    "pad-per-hole", "stripboard", "solderable-breadboard"
]
#: Which pair of edges carries the strip: the short ones (every photographed board) or
#: the long ones.
StripEdges: TypeAlias = Literal["short", "long"]  # noqa: UP040

FAMILY_BOARD_TYPES: tuple[FamilyBoardType, ...] = get_args(FamilyBoardType)
STRIP_EDGES: tuple[StripEdges, ...] = get_args(StripEdges)
STRIP_SHAPES: tuple[FingerShape, ...] = get_args(FingerShape)
LETTER_EDGES: tuple[LetterEdges, ...] = get_args(LetterEdges)
NUMBER_EDGES: tuple[NumberEdges, ...] = get_args(NumberEdges)
MASKS: tuple[BoardMask, ...] = get_args(BoardMask)
FINISHES: tuple[BoardFinish, ...] = get_args(BoardFinish)

#: The version of ``family_to_json``'s text. A saved family carries it from the first
#: version, so one saved today still loads once the family grows a field.
FAMILY_FORMAT = 1


# ---------------------------------------------------------------------------
# The family
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoardSize:
    """One board a family is sold as: its advertised size and its grid. LANDSCAPE -- the
    columns, which carry the letters, run along the longer edge, as on every photographed
    board -- unless a custom size says otherwise."""

    name: str
    width_mm: Mm
    height_mm: Mm
    cols: int
    rows: int
    #: False for a size sold without the family's strip: a grid that runs so close to the
    #: edge that there is no border for one. Every such count here is the one this
    #: application shipped, whose strips stood ON the outermost holes.
    strip: bool = True


@dataclass(frozen=True, slots=True)
class EdgeStrip:
    """The finger strip down a pair of edges, always OUTSIDE the grid
    (``EdgeConnector.outside``), which is where the stock boards have it."""

    edges: StripEdges = "short"
    shape: FingerShape = "rounded"
    #: Across the run, one finger per grid position.
    width_mm: Mm = 1.6
    #: In from the edge, less the inset; None reaches to the gap before the pads.
    length_mm: Mm | None = None
    inset_mm: Mm = 0.4
    #: Grid positions at each end of the run with no finger: beside the corner holes.
    skip_ends: int = 1
    face: BoardFace = "both"


@dataclass(frozen=True, slots=True)
class CornerHoles:
    """A bare screw hole in each corner, in the border where it holds one."""

    diameter_mm: Mm = 2.2
    head_mm: Mm = 4.4


@dataclass(frozen=True, slots=True)
class Legend:
    """The hole addresses the board prints. Which band of an edge they go in is derived
    (``geometry.legend_band_mm``), not said."""

    letter_edges: LetterEdges = "top"
    number_edges: NumberEdges = "left"
    row_digits: int = 2
    face: BoardFace = "both"


@dataclass(frozen=True, slots=True)
class BoardFamily:
    """A kind of board people buy, in every size it is sold in. See the module note."""

    id: str
    name: str
    material: BoardMaterial = "FR4"
    single_sided: bool = False
    type: FamilyBoardType = "pad-per-hole"
    #: A stripboard's strips; None on every other type.
    strip_axis: Literal["horizontal", "vertical"] | None = None
    mask: BoardMask | None = None
    finish: BoardFinish | None = None
    pitch_mm: Mm = 2.54
    thickness_mm: Mm = 1.6
    pad_diameter_mm: Mm = 1.8
    drill_mm: Mm = 1.0
    pad_shape: PadShape = "round"
    pad_length_mm: Mm | None = None
    pad_axis: PadAxis = "vertical"
    strip: EdgeStrip | None = None
    corner_holes: CornerHoles | None = None
    legend: Legend | None = None
    #: Lines printed in the border. ``{w}`` and ``{h}`` say the size in whole centimetres.
    printed: tuple[BoardText, ...] = ()
    sizes: tuple[BoardSize, ...] = ()
    #: A board somebody made in the designer, not one of the catalogue's.
    user: bool = False


@dataclass(frozen=True, slots=True)
class BoardDesign:
    """What ``board.applyPreset`` puts on the document for one board of a family."""

    board: Board
    edge_connectors: tuple[EdgeConnector, ...]
    mounting_holes: tuple[MountingHole, ...]


# ---------------------------------------------------------------------------
# Making one board of a family
# ---------------------------------------------------------------------------


def _cm(mm: Mm) -> str:
    return f"{mm / 10:g}"


def strip_edges_of(size: BoardSize, strip: EdgeStrip) -> tuple[BoardEdge, BoardEdge]:
    """The two board edges a strip runs down on this size: the short ones are the left and
    right of a landscape board, the top and bottom of a portrait one."""
    landscape = size.width_mm >= size.height_mm
    sides: tuple[BoardEdge, BoardEdge] = ("left", "right")
    ends: tuple[BoardEdge, BoardEdge] = ("top", "bottom")
    if strip.edges == "short":
        return sides if landscape else ends
    return ends if landscape else sides


def board_for(family: BoardFamily, size: BoardSize, base: Board) -> BoardDesign:
    """One board of ``family`` in ``size``: ``base`` made into it, with its strips and its
    corner holes."""
    board = family_board(family, size, base)
    connectors, mounts = family_features(family, size, board)
    return BoardDesign(board=board, edge_connectors=connectors, mounting_holes=mounts)


def family_board(family: BoardFamily, size: BoardSize, base: Board) -> Board:
    """The board alone. The border is solved from the size and the grid, so the outline is
    exactly the advertised size, and clamped at zero for a grid wider than the size."""
    border_x = max(0.0, (size.width_mm - size.cols * family.pitch_mm) / 2)
    border_y = max(0.0, (size.height_mm - size.rows * family.pitch_mm) / 2)
    legend = family.legend
    board = dataclasses.replace(
        base,
        type=family.type,
        cols=size.cols,
        rows=size.rows,
        pitch=family.pitch_mm,
        thickness=family.thickness_mm,
        material=family.material,
        pad_diameter=family.pad_diameter_mm,
        drill_diameter=family.drill_mm,
        strip_axis=family.strip_axis if family.type == "stripboard" else None,
        pad_shape=family.pad_shape,
        pad_length=family.pad_length_mm if family.pad_shape == "oblong" else None,
        pad_axis=family.pad_axis,
        border_x_mm=round(border_x, 4),
        border_y_mm=round(border_y, 4),
        single_sided=family.single_sided,
        labels=(
            None
            if legend is None
            else BoardLabels(
                face=legend.face,
                row_digits=legend.row_digits,
                all_edges=False,
                letter_edges=legend.letter_edges,
                number_edges=legend.number_edges,
            )
        ),
        narrow_channel_cols=0,
        mask=family.mask,
        finish=family.finish,
        printed=tuple(
            dataclasses.replace(
                line, text=line.text.format(w=_cm(size.width_mm), h=_cm(size.height_mm))
            )
            for line in family.printed
        ),
    )
    return board


def family_features(
    family: BoardFamily, size: BoardSize, board: Board
) -> tuple[tuple[EdgeConnector, ...], tuple[MountingHole, ...]]:
    """(the strips, the corner holes) ``family`` is sold with in ``size``, on ``board``.

    Asked of the board as it IS rather than rebuilt, so a stock board laid over somebody's
    own pads (``board_from_preset``) gets its strips measured against those pads."""
    holes = family.corner_holes
    mounts = (
        () if holes is None else corner_mounting_holes(board, holes.diameter_mm, holes.head_mm)
    )
    connectors: tuple[EdgeConnector, ...] = ()
    if family.strip is not None and size.strip:
        strip = family.strip
        connectors = tuple(
            EdgeConnector(
                id=f"ec-{edge}",
                edge=edge,
                start=strip.skip_ends,
                count=(board.rows if edge in ("left", "right") else board.cols) - 2 * strip.skip_ends,
                finger_width=strip.width_mm,
                finger_length=strip.length_mm,
                inset_mm=strip.inset_mm,
                face="bottom" if family.single_sided else strip.face,
                outside=True,
                shape=strip.shape,
            )
            for edge in strip_edges_of(size, strip)
        )
    return connectors, mounts


def family_border_mm(family: BoardFamily) -> tuple[Mm, Mm]:
    """The border a custom size of this family keeps, (across, down): its first size's, so a
    board made to measure is the same product cut to another length. 1 mm, a board cut
    flush, for a family that lists no size."""
    if not family.sizes:
        return (1.0, 1.0)
    first = family.sizes[0]
    return (
        max(0.0, (first.width_mm - first.cols * family.pitch_mm) / 2),
        max(0.0, (first.height_mm - first.rows * family.pitch_mm) / 2),
    )


def size_for_grid(family: BoardFamily, cols: int, rows: int) -> BoardSize:
    """A board of this family with this grid, its border the family's."""
    border_x, border_y = family_border_mm(family)
    width = round(cols * family.pitch_mm + 2 * border_x, 2)
    height = round(rows * family.pitch_mm + 2 * border_y, 2)
    return BoardSize(f"{_cm(width)} x {_cm(height)} cm", width, height, cols, rows)


def size_for_mm(family: BoardFamily, width_mm: Mm, height_mm: Mm) -> BoardSize:
    """A board of this family cut to this size: the largest grid that keeps the family's
    border, the border then solved from what is left."""
    border_x, border_y = family_border_mm(family)
    cols = max(1, math.floor((width_mm - 2 * border_x) / family.pitch_mm + 1e-9))
    rows = max(1, math.floor((height_mm - 2 * border_y) / family.pitch_mm + 1e-9))
    return BoardSize(f"{_cm(width_mm)} x {_cm(height_mm)} cm", width_mm, height_mm, cols, rows)


# ---------------------------------------------------------------------------
# The one refusal
# ---------------------------------------------------------------------------


def family_problem(family: BoardFamily) -> tuple[str, str] | None:
    """(the attribute it is about, why) for a family no board can be made of, or None.

    The attribute is a path into the dataclass ("strip.width_mm", "sizes[2]"), so the
    designer can say the refusal under the field that caused it. Engine English, like the
    bus's messages, translated where it is shown.
    """
    if not family.id.strip():
        return ("id", "A board family needs an id.")
    if not family.name.strip():
        return ("name", "A board family needs a name.")
    for attr, value, allowed in (
        ("type", family.type, FAMILY_BOARD_TYPES),
        ("material", family.material, get_args(BoardMaterial)),
        ("mask", family.mask, (None, *MASKS)),
        ("finish", family.finish, (None, *FINISHES)),
        # Not ``get_args(PadShape)``: it is a PEP 695 alias, whose ``get_args`` is empty.
        ("pad_shape", family.pad_shape, PAD_SHAPES),
    ):
        if value not in allowed:
            return (attr, f"{value!r} is not one of: {', '.join(str(a) for a in allowed if a)}.")
    if family.type == "stripboard" and family.strip_axis not in ("horizontal", "vertical"):
        return ("strip_axis", "A stripboard's strips run horizontally or vertically.")
    if not family.pitch_mm > 0:
        return ("pitch_mm", "The pitch must be more than 0 mm.")
    if not 0 < family.drill_mm < family.pad_diameter_mm:
        return ("drill_mm", "The drill must be over 0 mm and smaller than the pad.")
    if family.pad_diameter_mm >= family.pitch_mm:
        return ("pad_diameter_mm", "A pad as wide as the pitch touches the next one.")
    if family.pad_shape == "oblong" and not (
        family.pad_length_mm is not None and family.pad_length_mm > family.pad_diameter_mm
    ):
        return ("pad_length_mm", "An oblong pad is longer than it is wide.")
    if family.strip is not None:
        strip = family.strip
        if family.type == "solderable-breadboard":
            return ("strip", "A breadboard's pattern runs to its edges; it has no edge strip.")
        if strip.edges not in STRIP_EDGES:
            return ("strip.edges", f"{strip.edges!r} is not one of: {', '.join(STRIP_EDGES)}.")
        if strip.shape not in STRIP_SHAPES:
            return ("strip.shape", f"{strip.shape!r} is not one of: {', '.join(STRIP_SHAPES)}.")
        if not 0 < strip.width_mm < family.pitch_mm:
            return ("strip.width_mm", "A finger is over 0 mm wide and narrower than the pitch.")
        if strip.length_mm is not None and not strip.length_mm > 0:
            return ("strip.length_mm", "A finger is longer than 0 mm.")
        if strip.inset_mm < 0:
            return ("strip.inset_mm", "A strip's inset cannot be negative.")
        if strip.skip_ends < 0:
            return ("strip.skip_ends", "A strip cannot leave fewer than no positions bare.")
    if family.corner_holes is not None:
        holes = family.corner_holes
        if not holes.diameter_mm > 0:
            return ("corner_holes.diameter_mm", "A corner hole is wider than 0 mm.")
        if holes.head_mm < holes.diameter_mm:
            return ("corner_holes.head_mm", "A screw head is at least as wide as its hole.")
    if family.legend is not None:
        legend = family.legend
        if legend.letter_edges not in LETTER_EDGES:
            return ("legend.letter_edges", f"{legend.letter_edges!r} is not one of: {', '.join(LETTER_EDGES)}.")
        if legend.number_edges not in NUMBER_EDGES:
            return ("legend.number_edges", f"{legend.number_edges!r} is not one of: {', '.join(NUMBER_EDGES)}.")
        if not 1 <= legend.row_digits <= MAX_LEGEND_DIGITS:
            return (
                "legend.row_digits",
                f"A printed row number is padded to between 1 and {MAX_LEGEND_DIGITS} digits.",
            )
    if not family.sizes:
        return ("sizes", "A board family is sold in at least one size.")
    for index, size in enumerate(family.sizes):
        where = f"sizes[{index}]"
        if size.cols < 1 or size.rows < 1:
            return (where, f"{size.name} needs at least one column and one row.")
        if size.cols * family.pitch_mm > size.width_mm + 1e-9 or size.rows * family.pitch_mm > size.height_mm + 1e-9:
            return (where, f"{size.cols} x {size.rows} holes do not fit on {size.name}.")
        design = board_for(family, size, _PROBE_BOARD)
        if family.strip is not None and size.strip:
            for connector in design.edge_connectors:
                if connector.count < 1:
                    return (where, f"{size.name} is too short for a strip that skips {family.strip.skip_ends} at each end.")
                room = outside_finger_room_mm(design.board, connector.edge, connector.inset_mm)
                if room < OUTSIDE_FINGER_MIN_MM:
                    return (
                        where,
                        f"{size.name}'s {connector.edge} border leaves {max(0.0, room):.2f} mm for "
                        f"the strip, under the {OUTSIDE_FINGER_MIN_MM:g} mm a finger needs.",
                    )
        if (problem := board_text_problem(design.board)) is not None:
            return ("printed", problem)
    return None


#: What a family's sizes are tried on when only the family is in question: every field a
#: family sets is set by ``board_for``, so the probe's own values never show.
_PROBE_BOARD = Board(
    type="pad-per-hole",
    cols=1,
    rows=1,
    pitch=2.54,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.8,
    drill_diameter=1.0,
)


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


def _sizes(*rows: tuple[str, float, float, int, int] | tuple[str, float, float, int, int, bool]) -> tuple[BoardSize, ...]:
    return tuple(BoardSize(*row) for row in rows)


#: The green double-sided "universal PCB": FR-4, plated through, tinned, green mask. Read
#: off a product photograph of the 5 x 7 and one of the 2 x 8 (a stadium pad beside each
#: row down both short edges, about 1.7 mm across and 3 mm long, 0.4 mm in from the edge;
#: bare corner holes in the border; letters along one long edge, the row numbers small
#: between the grid and the strip on both short edges; "5cmX7cm" in the bottom border).
#:
#: The grids are the suppliers' listings: 2 x 8 is 28 x 6 (168 holes), 3 x 7 24 x 10 (240),
#: 4 x 6 20 x 14 (280), 5 x 7 24 x 18 (432), 6 x 8 27 x 22 (594), 9 x 15 52 x 34. Where the
#: listings disagree with the count this application shipped, that count is a second
#: variant of the same size, so a board somebody bought either way is offered.
GREEN_DOUBLE_SIDED = BoardFamily(
    id="double-sided-fr4",
    name="Green double-sided (FR-4, tinned)",
    material="FR4",
    pad_diameter_mm=1.9,
    drill_mm=1.0,
    strip=EdgeStrip(edges="short", shape="stadium", width_mm=1.7, length_mm=3.0, inset_mm=0.4),
    corner_holes=CornerHoles(diameter_mm=2.2, head_mm=4.4),
    legend=Legend(letter_edges="top", number_edges="both", row_digits=2),
    printed=(BoardText("{h}cmX{w}cm", edge="bottom"),),
    sizes=_sizes(
        ("2 x 8 cm", 80.0, 20.0, 28, 6),
        ("2 x 8 cm", 80.0, 20.0, 30, 5, False),
        ("3 x 7 cm", 70.0, 30.0, 24, 10),
        ("4 x 6 cm", 60.0, 40.0, 20, 14),
        ("5 x 7 cm", 70.0, 50.0, 24, 18),
        ("6 x 8 cm", 80.0, 60.0, 27, 22),
        ("6 x 8 cm", 80.0, 60.0, 30, 22, False),
        ("7 x 9 cm", 90.0, 70.0, 31, 26),
        ("7 x 9 cm", 90.0, 70.0, 35, 27, False),
        ("9 x 15 cm", 150.0, 90.0, 52, 34),
        ("9 x 15 cm", 150.0, 90.0, 58, 34, False),
        # The large boards, at the grids this application shipped: none of them leaves a
        # border a strip fits in, and no listing gave another count.
        ("12 x 18 cm", 180.0, 120.0, 70, 46, False),
        ("15 x 20 cm", 200.0, 150.0, 78, 58, False),
        ("20 x 30 cm", 300.0, 200.0, 118, 78, False),
    ),
)

#: The phenolic single-sided board: paper phenolic, copper on one face, bare, no mask. Read
#: off a product photograph of the 5 x 7 (a square pad beside each column along both short
#: edges, on the copper side; bare corner holes in the border; letters down one long edge
#: and no numbers). 24 x 18 is the suppliers' 5 x 7 (432 holes); 26 x 18 is what this
#: application shipped.
PHENOLIC_SINGLE_SIDED = BoardFamily(
    id="single-sided-phenolic",
    name="Phenolic single-sided (bare copper)",
    material="FR2",
    single_sided=True,
    pad_diameter_mm=1.9,
    drill_mm=1.0,
    strip=EdgeStrip(edges="short", shape="square", width_mm=1.9, length_mm=1.9, inset_mm=0.4, face="bottom"),
    corner_holes=CornerHoles(diameter_mm=2.5, head_mm=5.0),
    legend=Legend(letter_edges="top", number_edges="none", row_digits=2, face="bottom"),
    sizes=_sizes(
        ("5 x 7 cm", 70.0, 50.0, 24, 18),
        ("5 x 7 cm", 70.0, 50.0, 26, 18, False),
        ("7 x 9 cm", 90.0, 70.0, 35, 27, False),
        ("9 x 15 cm", 150.0, 90.0, 58, 34, False),
        ("15 x 20 cm", 200.0, 150.0, 78, 58, False),
    ),
)

#: Every family the designer offers before somebody makes their own.
FAMILIES: tuple[BoardFamily, ...] = (GREEN_DOUBLE_SIDED, PHENOLIC_SINGLE_SIDED)

_BY_ID = {family.id: family for family in FAMILIES}


def family_by_id(family_id: str) -> BoardFamily:
    """The catalogue family with this id. Raises ``KeyError`` naming the ids there are."""
    try:
        return _BY_ID[family_id]
    except KeyError:
        raise KeyError(f"No board family {family_id!r}; there are {', '.join(_BY_ID)}.") from None


# ---------------------------------------------------------------------------
# The stock boards: a catalogue family in one of its sizes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoardPreset:
    """One stock board: a catalogue family in a size it is sold. What the board chooser
    lists, what the board trials try (``placer.suggest_boards``, ``boardfit``) and what
    ``commands.preset_payload`` puts on the document.

    Perfboard is bought as "a 5 by 7", and the listing quotes the centimetres; the grid is
    what fits once the border is taken off, and the border is DERIVED, so the outline is
    the advertised size to the tenth of a millimetre -- which matters because the 1:1 print
    gets taped onto the physical board.
    """

    family: str
    size: BoardSize

    @property
    def product(self) -> BoardFamily:
        return family_by_id(self.family)

    @property
    def name(self) -> str:
        return self.size.name

    @property
    def width_mm(self) -> Mm:
        return self.size.width_mm

    @property
    def height_mm(self) -> Mm:
        return self.size.height_mm

    @property
    def cols(self) -> int:
        return self.size.cols

    @property
    def rows(self) -> int:
        return self.size.rows

    @property
    def single_sided(self) -> bool:
        return self.product.single_sided

    @property
    def material(self) -> BoardMaterial:
        return self.product.material

    @property
    def key(self) -> str:
        """Unique among the presets: two variants of one size differ in their grid."""
        return f"{self.width_mm:g}x{self.height_mm:g}-{self.cols}x{self.rows}-{self.family}"


def stock_sizes(family: BoardFamily) -> tuple[BoardSize, ...]:
    """The size a supplier means by each name: the first listed. The others are variants,
    offered where a board is designed rather than where one is chosen."""
    seen: set[str] = set()
    sizes: list[BoardSize] = []
    for size in family.sizes:
        if size.name not in seen:
            seen.add(size.name)
            sizes.append(size)
    return tuple(sizes)


#: The boards every prototyping supplier stocks, in both families: the catalogue's stock
#: sizes. What changes a board here is a family's entry, not this line.
STANDARD_PRESETS: tuple[BoardPreset, ...] = tuple(
    BoardPreset(family.id, size) for family in FAMILIES for size in stock_sizes(family)
)


def board_from_preset(preset: BoardPreset, base: Board) -> Board:
    """``base`` made into a stock board: the product's grid, border, legend, look and
    print, over what a stock board has never decided -- the board TYPE (a stripboard
    stays one) and the pads, drill and thickness of the board it replaces. A family's own
    pads are the designer's to apply (``board_for``)."""
    made = family_board(preset.product, preset.size, base)
    return dataclasses.replace(
        made,
        type=base.type,
        strip_axis=base.strip_axis,
        thickness=base.thickness,
        pad_diameter=base.pad_diameter,
        drill_diameter=base.drill_diameter,
        # The pads on these boards are round; the strip is the edge connectors, never a
        # board-wide pad shape.
        pad_shape="round",
        pad_length=None,
    )


def preset_edge_connectors(preset: BoardPreset, board: Board) -> tuple[EdgeConnector, ...]:
    """The strips a stock board is sold with, on ``board`` (``family_features``)."""
    return family_features(preset.product, preset.size, board)[0]


def preset_mounting_holes(preset: BoardPreset, board: Board) -> tuple[MountingHole, ...]:
    """The corner holes a stock board is sold with, on ``board``: in the border where it
    holds one, as every photograph of these boards has them -- the phenolic one included,
    which this application used to give none -- else at the corner position
    (``geometry.corner_mounting_holes``)."""
    return family_features(preset.product, preset.size, board)[1]


# ---------------------------------------------------------------------------
# A saved family
# ---------------------------------------------------------------------------


def family_to_json(family: BoardFamily) -> str:
    """The family as text, for the host to keep. Carries ``FAMILY_FORMAT`` from the first
    version on."""
    return json.dumps({"format": FAMILY_FORMAT, **_plain(dataclasses.asdict(family))}, indent=2)


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def family_from_json(text: str) -> BoardFamily:
    """The family ``family_to_json`` wrote. Raises ``ValueError`` on text that is not one,
    on a format this build does not know, and on a family ``family_problem`` refuses."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not a saved board family: {exc.msg}.") from exc
    if not isinstance(raw, dict):
        raise ValueError("Not a saved board family.")
    if raw.get("format") != FAMILY_FORMAT:
        raise ValueError(
            f"A board family saved in format {raw.get('format')!r}; this build reads "
            f"format {FAMILY_FORMAT}."
        )
    try:
        family = BoardFamily(
            **{
                **{key: value for key, value in raw.items() if key not in _NESTED and key != "format"},
                "strip": None if raw.get("strip") is None else EdgeStrip(**raw["strip"]),
                "corner_holes": (
                    None if raw.get("corner_holes") is None else CornerHoles(**raw["corner_holes"])
                ),
                "legend": None if raw.get("legend") is None else Legend(**raw["legend"]),
                "printed": tuple(BoardText(**line) for line in raw.get("printed", ())),
                "sizes": tuple(BoardSize(**size) for size in raw.get("sizes", ())),
            }
        )
    except TypeError as exc:
        raise ValueError(f"Not a saved board family: {exc}.") from exc
    if (problem := family_problem(family)) is not None:
        raise ValueError(f"{problem[0]}: {problem[1]}")
    return family


_NESTED = frozenset({"strip", "corner_holes", "legend", "printed", "sizes"})


__all__ = [
    "FAMILIES",
    "FAMILY_BOARD_TYPES",
    "FAMILY_FORMAT",
    "FINISHES",
    "GREEN_DOUBLE_SIDED",
    "LETTER_EDGES",
    "MASKS",
    "NUMBER_EDGES",
    "PHENOLIC_SINGLE_SIDED",
    "STANDARD_PRESETS",
    "STRIP_EDGES",
    "STRIP_SHAPES",
    "BoardDesign",
    "BoardFamily",
    "BoardPreset",
    "BoardSize",
    "CornerHoles",
    "EdgeStrip",
    "FamilyBoardType",
    "Legend",
    "StripEdges",
    "board_for",
    "board_from_preset",
    "family_board",
    "family_border_mm",
    "family_by_id",
    "family_features",
    "family_from_json",
    "family_problem",
    "family_to_json",
    "preset_edge_connectors",
    "preset_mounting_holes",
    "size_for_grid",
    "size_for_mm",
    "stock_sizes",
    "strip_edges_of",
]
