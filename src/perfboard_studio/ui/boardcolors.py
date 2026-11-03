"""Board colour schemes, shared by the 2D editor and the 3D view.

THE BOARD SAYS WHAT IT LOOKS LIKE. Its mask and its pads' finish are document fields
(``Board.mask``, ``Board.finish``), because they are the board you bought: designing for
the board in your hand means seeing that board, and a black ENIG board drawn green and tin
is not it. Each is left out of the file at its default -- the look its material is sold
with, ``geometry.board_mask`` / ``board_finish`` -- so every older file draws exactly as
it did.

THE VIEW MENU STILL OVERRIDES IT. It was the only way to say this once, and it stays as
"draw every board as ...": someone matching a screenshot to a board in another colour can,
without changing the document. ``choose(None)`` goes back to what the board says.

WHAT THE SCHEMES ARE. The colours perfboard is actually sold in. Green FR-4 and brown
phenolic are what the substrate genuinely looks like for those materials, so they are the
defaults per material; the rest are real products (the blue double-sided boards are
everywhere) and are offered because someone matching a screenshot to the board in their
hand should be able to.

Each scheme carries both views' colours together, so a board cannot be green in the
editor and blue in the 3D view -- which would undermine the one job the 3D view has,
letting someone check that what they are about to solder is what they meant.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from perfboard_studio.geometry import board_finish, board_mask
from perfboard_studio.model import Board, BoardFinish, BoardMask


@dataclass(frozen=True, slots=True)
class BreadboardColours:
    """A solderless breadboard, in both views: white plastic, dark openings, a groove, the
    rail lines and grey print. Not a ``BoardScheme``, because a scheme is a solder mask over
    copper and a breadboard has neither -- and not offered in the View menu, because every
    breadboard is this colour."""

    body: str = "#f3f2ee"
    edge: str = "#cbc8c0"
    hole: str = "#2e2d2b"
    hole_rim: str = "#d9d6ce"
    groove: str = "#dedbd3"
    print_ink: str = "#77746c"
    #: The line beside a rail, by the class of net the rail is for (``breadboard.RAIL_CLASS``).
    ground: str = "#2f63c0"
    power: str = "#d4373a"

    def rail_ink(self, net_class: str) -> str:
        return self.ground if net_class == "ground" else self.power


BREADBOARD = BreadboardColours()


@dataclass(frozen=True, slots=True)
class BoardScheme:
    """One board's appearance. ``key`` is stable; ``label`` is shown and translated."""

    key: str
    label: str
    #: 2D: substrate fill and its edge, as hex.
    fill: str
    edge: str
    #: 3D: the same substrate as linear RGB, which is what VTK wants.
    rgb: tuple[float, float, float]
    #: Silkscreen printed on the board -- the row and column labels real boards carry.
    silk: str
    #: THE COPPER, and it belongs to the scheme for the same reason the substrate does.
    #: It was one global gold for every board, which is right for the plated FR-4 boards
    #: and wrong for the cheap phenolic one, whose pads are BARE COPPER -- pink-brown,
    #: not yellow. A pertinax board wearing FR-4's gold pads is not the board anybody has
    #: in their hand, and the finish is one of the two things you notice first.
    pad: str
    #: The darker edge of a pad, and the lighter catch of light across it.
    pad_ring: str
    pad_sheen: str
    #: The same copper for the 3D view.
    pad_rgb: tuple[float, float, float]
    #: No mask: the substrate itself shows, and a board like that prints nothing in ink --
    #: its legend is ETCHED in the copper, the pads' metal (the phenolic 5 x 7's letters,
    #: photographed). Both views and the print draw its legend and printed lines in
    #: ``pad`` rather than white.
    etched: bool = False

    def legend_ink(self) -> str:
        """What the legend and the board's printed lines are drawn in, as hex."""
        return self.pad if self.etched else LEGEND_WHITE

    def legend_rgb(self) -> tuple[float, float, float]:
        """The same, for the 3D view."""
        return self.pad_rgb if self.etched else LEGEND_WHITE_RGB


#: Silkscreen ink, on every masked board: the 2D legend's #eef2f8 and the 3D view's.
LEGEND_WHITE = "#eef2f8"
LEGEND_WHITE_RGB = (0.92, 0.93, 0.95)


#: HASL: hot-air levelled SOLDER over copper, which is what the cheap masked prototyping
#: boards are finished with. Gold over nickel is what this said, and it is what the green,
#: blue and black boards were drawn with until somebody held one up against the screen:
#: on a photograph of the board itself the pads are neutral and light, at a blue/red ratio
#: of about 1.0, where gold's is 0.4. It is tin, not gold.
#:
#: Deliberately WARMER and LIGHTER than the grey a solder run is drawn in (`#b9bec6`,
#: view2d's conductor table). They are nearly the same metal on a real board, and telling
#: them apart is the one thing this whole application is about -- so the pad keeps a warm
#: cast and a dark ring, and the run stays cool and unringed.
_TINNED = ("#d4d2cc", "#85837c", "#efeee9", (0.831, 0.824, 0.800))

#: BARE copper, unmasked and unplated, which is what a phenolic board has: pale warm
#: metal rather than yellow gold.
#:
#: MEASURED, not chosen. Sampled off product photographs of the boards themselves, which
#: put the pads at hue 25-28 degrees and saturation around 0.35 -- warm, so copper and
#: not tin, but much paler and less saturated than the pink-brown this first guessed at.
_BARE_COPPER = ("#e2a877", "#a86a3c", "#f6d0aa", (0.886, 0.659, 0.467))

#: ENIG: gold over nickel, the finish of the better boards (a matte black one with gold
#: pads is the usual). MEASURED, off a product photograph of such a board: the pads'
#: gold pixels at hue 46 degrees, saturation 0.6, the quartiles of their value giving the
#: pad, its shaded ring and the catch of light.
_GOLD = ("#af943f", "#8b7938", "#c2a759", (0.686, 0.580, 0.247))

#: The copper of each finish. Lead-free HASL is the same tin to the eye.
_FINISH: dict[BoardFinish, tuple[str, str, str, tuple[float, float, float]]] = {
    "hasl": _TINNED,
    "lf-hasl": _TINNED,
    "bare-copper": _BARE_COPPER,
    "enig": _GOLD,
}

SCHEMES: tuple[BoardScheme, ...] = (
    # #257845, chosen on 2026-11-03 from three candidates rendered with a circuit on the
    # 5 x 7 board beside a photograph of it: the photograph's mask measures #19844e, the
    # green drawn until then was #2e6b3f, and this is halfway between them in HSV -- the
    # board in the hand, without its brightness drowning the parts on it.
    BoardScheme("green", "Green (FR-4)", "#257845", "#09170e", (0.13, 0.42, 0.24), "#e8f0ea", *_TINNED),
    BoardScheme("blue", "Blue", "#1f4e8c", "#0b1a2e", (0.10, 0.26, 0.50), "#e6edf7", *_TINNED),
    BoardScheme("black", "Black", "#232529", "#0a0b0d", (0.11, 0.12, 0.14), "#d8dbe0", *_TINNED),
    BoardScheme("red", "Red", "#8c2a26", "#2e0b0a", (0.50, 0.13, 0.12), "#f6e6e5", *_TINNED),
    BoardScheme("purple", "Purple", "#4a2a72", "#170d24", (0.26, 0.14, 0.42), "#ece4f6", *_TINNED),
    BoardScheme("white", "White", "#d8d6ce", "#a09c90", (0.84, 0.83, 0.79), "#3a3a36", *_TINNED),
    # Paper-phenolic, and ORANGE -- measured off photographs of the boards, which sample
    # at #c67a3f, #c17c58 and #bb7441 across three of them. It was briefly changed to a
    # brown on the reasoning that "pertinax is the colour of cardboard"; the boards say
    # otherwise, and this is the one colour in this file anybody can check.
    #
    # THE HUE IS STILL THE PHOTOGRAPHS'; the saturation is not. Drawn at the measured
    # #c47a41, a whole board of flat orange in a dark window was the loudest thing on the
    # screen, louder than every part on it -- an orange film capacitor all but vanished into
    # it. A photograph's board has grain, gloss and shadow breaking it up, and the screen's
    # has none. Chosen by looking at the candidates side by side (2026-10-16): the same 26
    # degrees at saturation 0.53 and value 0.68, which still reads as pertinaks.
    BoardScheme(
        "phenolic", "Orange (phenolic)", "#ad7a52", "#3a2410", (0.678, 0.478, 0.322), "#2c2115",
        *_BARE_COPPER, etched=True,
    ),
)

#: FR-4 with no mask: the glass-epoxy laminate itself, a pale translucent straw. NOT
#: measured -- no photograph of such a board has been held against it yet -- and not
#: offered in the View menu, where every entry is a board somebody sells; it is only what
#: a board saying ``mask: "none"`` on FR-4 is drawn as.
_BARE_FR4 = BoardScheme(
    "bare-fr4", "Bare FR-4", "#c8c08e", "#6e6847", (0.784, 0.753, 0.557), "#2e2b1d", *_TINNED,
    etched=True,
)

BY_KEY = {scheme.key: scheme for scheme in SCHEMES}

#: The scheme each mask is drawn with. A board with no mask shows its substrate, which
#: is the material's: phenolic's orange, or FR-4's own straw.
_MASK_SCHEME: dict[BoardMask, str] = {
    "green": "green",
    "blue": "blue",
    "black": "black",
    "red": "red",
    "purple": "purple",
    "white": "white",
}

_chosen: str | None = None


def choose(key: str | None) -> None:
    """Pick a scheme for every board, or ``None`` to go back to what each board says."""
    global _chosen
    _chosen = key if key in BY_KEY else None


def chosen_key() -> str | None:
    """The explicit choice, or None when each board decides."""
    return _chosen


def scheme_for(board: Board) -> BoardScheme:
    """The scheme in force for this board: the View menu's, if one is chosen, or else the
    board's own mask over its own finish.

    Takes the BOARD, not its material, so that nothing can draw a board without asking
    what it says it is.
    """
    if _chosen is not None:
        return BY_KEY[_chosen]
    mask = board_mask(board)
    if mask == "none":
        substrate = BY_KEY["phenolic"] if board.material in ("FR2", "FR1") else _BARE_FR4
    else:
        substrate = BY_KEY[_MASK_SCHEME[mask]]
    pad, ring, sheen, rgb = _FINISH[board_finish(board)]
    if (pad, ring, sheen, rgb) == (
        substrate.pad, substrate.pad_ring, substrate.pad_sheen, substrate.pad_rgb
    ):
        return substrate
    return dataclasses.replace(substrate, pad=pad, pad_ring=ring, pad_sheen=sheen, pad_rgb=rgb)


__all__ = [
    "BY_KEY",
    "SCHEMES",
    "BoardScheme",
    "choose",
    "chosen_key",
    "scheme_for",
]
