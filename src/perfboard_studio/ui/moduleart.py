"""What stands on a module's own board, for the modules the 3D view knows by name.

WHY THIS EXISTS. A module's id (``mod-2x2-p16-r7-43.18x21.08x12-s5``) carries its pins, its
board and the height of its tallest part, and nothing else -- so ``view3d._module_pieces``
stands one dark block that tall in the middle of the board. That is an honest envelope and
a picture of nothing: the first real board laid out with this program carried an LM2596S
step-down module and an SN65HVD230 CAN breakout, and in 3D they were the same blue slab
with a different-sized brick on it. A buck module is two cans, a big inductor, a regulator
and a blue trimmer, and that is how anybody looking at the bench finds it.

HOW A MODULE IS RECOGNISED: by the part's VALUE, the one thing the document says about what
the part IS -- the same way a resistor's colour code is read from its value
(``bodies.resistor_bands``), so the picture cannot disagree with the parts list. And only
when the id agrees with the drawing the layout was taken from: the same number of pins,
pins along the edges the module has them on, and a board within ``SIZE_TOLERANCE`` of the
reference. Anything else -- a value nobody wrote a layout for, an LM2596 on somebody's
own differently-shaped board -- keeps the block. A guessed layout on the wrong board would
be a picture of a part that is not there.

WHAT IS DRAWN STAYS INSIDE THE ENVELOPE DRC MEASURES. Every part is on the module's board,
and none stands taller than the id's ``top`` (``fit_module_art`` clamps it), so a recognised
module never looks taller or wider than ``component-too-tall`` and the overlap rules think
it is. The pin names the module's silkscreen carries (``bodies.pin_labels``) run in from its
pins, and the layouts leave that strip clear; ``tests/test_module_art.py`` measures both.

The layout is in the ART's frame -- ``u`` along the module, ``v`` across it, millimetres
from the board's centre -- and ``fit_module_art`` turns it into the footprint's own frame
(x along the columns, y down the rows, pin 1 at the origin), which both views already know
how to turn with the part. It knows nothing about VTK: ``view3d`` draws what comes back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from perfboard_studio.model import ComponentInstance, Footprint, pin_name_of

from .bodies import placement_for

#: What one part on a module's board is, which is what ``view3d`` draws it as.
#:
#:  * ``can``      -- an aluminium electrolytic standing up, its stripe on the ``facing`` side.
#:  * ``inductor`` -- a shielded power inductor: a dark square case with rounded corners.
#:  * ``to263``    -- a D2PAK regulator lying flat: tab behind, five legs out of the ``facing`` end.
#:  * ``trimpot``  -- a multi-turn 3296W trimmer, its brass screw at the ``facing`` end.
#:  * ``soic8``    -- an SO-8 chip, gull-wing legs down both long sides, pin 1 at ``facing``.
#:  * ``sma``      -- a moulded SMD diode (SMA), the cathode band at ``facing``.
#:  * ``chip-r``   -- a 0805 resistor; ``chip-c`` the same size of ceramic capacitor.
#:  * ``silk``     -- printing on the module's own board, ``text`` and nothing else.
ArtKind = Literal["can", "inductor", "to263", "trimpot", "soic8", "sma", "chip-r", "chip-c", "silk"]

#: How far a module's board may be from the reference a layout was drawn on, either way, as a
#: fraction. Wide enough for one maker's board against another's drawing of the same module
#: (LM2596 boards are sold from 43 x 20 to 44 x 21.5 mm), narrow enough that a layout is never
#: stretched over a board of another shape.
SIZE_TOLERANCE = 0.15


@dataclass(frozen=True, slots=True)
class ArtPart:
    """One part on a module's board, in the art's own frame."""

    kind: ArtKind
    #: Its centre, in millimetres from the board's centre: ``u`` along the art, ``v`` across.
    u: float
    v: float
    #: Along the part's own axis, across it, and how tall it stands off the module's board.
    #: The whole part: a regulator's length includes its tab and its legs.
    length: float
    width: float
    height: float
    #: Whether the part's own axis runs along ``v`` rather than ``u``.
    along_v: bool = False
    #: Which end of its own axis carries what makes it asymmetric -- a regulator's legs, a
    #: trimmer's screw, a diode's band, a chip's pin 1, the negative side of a can: +1 or -1.
    facing: int = 1
    #: What is printed on it (ASCII: ``vtkVectorText`` prints nothing else).
    text: str = ""


@dataclass(frozen=True, slots=True)
class ModuleArt:
    """A module the 3D view can draw: how to recognise it and what is on it."""

    #: Stable, for tests and nothing else.
    key: str
    #: Fragments of a part's value that name this module, lower case. Any one is enough.
    names: tuple[str, ...]
    #: The reference board the layout was drawn on, ``u`` x ``v``, in millimetres.
    board: tuple[float, float]
    pins: int
    #: How the art is laid against the pins. ``"power"``: ``u`` along the board's long side,
    #: the pins called IN at ``-u`` and the ones called ``+`` at ``-v``, as a buck module's
    #: silkscreen has them. ``"header"``: ``u`` along the single row of pins, which runs
    #: down the ``-v`` edge.
    frame: Literal["power", "header"]
    parts: tuple[ArtPart, ...]
    #: Where the layout and its sizes come from.
    source: str


@dataclass(frozen=True, slots=True)
class PlacedArt:
    """One part of a recognised module, in the footprint's own frame and millimetres: x
    along the columns, y down the rows, pin 1 at the origin. Each view turns it with the
    part, as it turns the body."""

    kind: ArtKind
    x: float
    y: float
    #: The part's extent along local x and local y, and its height off the module's board.
    size_x: float
    size_y: float
    height: float
    #: Whether its own axis runs along local x (``"x"``) or local y.
    axis: Literal["x", "y"]
    #: Which end of that axis its feature is at, +1 or -1 along it.
    facing: int
    text: str


# -- the layouts -------------------------------------------------------------------------
#
# Each is laid out from a dimension drawing and the photographs every seller uses, and the
# sizes are the parts' own datasheet sizes. Positions are what a person checks against the
# module in their hand; sizes are what makes each part read as itself, and they do not
# scale with the board.

#: The blue LM2596S step-down module sold everywhere: input can, the regulator in its D2PAK
#: with its legs towards the inductor, a 33 uH shielded inductor in the middle, the output
#: can, a Schottky diode under the inductor and the multi-turn trimmer along the output
#: edge. Board and pad positions from Handsontec's LM2596S drawing (43.18 x 21.08 mm, pads
#: 39.50 x 17.15 mm apart); cans 8 x 12 mm (220 uF / 35-50 V), inductor 12 x 12 x 7 mm,
#: trimmer Bourns 3296W (9.53 x 4.83 x 10.03 mm), D2PAK per TI's KTT drawing.
LM2596_MODULE = ModuleArt(
    key="lm2596",
    names=("lm2596",),
    board=(43.18, 21.08),
    pins=4,
    frame="power",
    parts=(
        # The two cans have their stripes towards the - rail, the IN- / OUT- edge.
        ArtPart("can", -13.0, -4.6, 8.0, 8.0, 12.0, along_v=True, facing=1),
        # TO-263-5: 1.3 mm of tab, a 9.2 mm body, 2.5 mm of legs towards +u.
        ArtPart("to263", -11.5, 5.2, 13.0, 10.1, 4.4, facing=1, text="LM2596S"),
        ArtPart("inductor", 1.5, -2.0, 12.0, 12.0, 7.0),
        ArtPart("sma", -0.9, 8.3, 4.3, 2.6, 2.2, facing=-1),
        ArtPart("can", 13.0, -4.6, 8.0, 8.0, 12.0, along_v=True, facing=1),
        ArtPart("trimpot", 12.0, 6.8, 9.5, 4.8, 10.0, facing=1),
        ArtPart("chip-r", 3.4, 7.6, 2.0, 1.25, 0.6, along_v=True),
        ArtPart("chip-r", 5.4, 7.6, 2.0, 1.25, 0.6, along_v=True),
        ArtPart("chip-c", -7.2, -5.6, 2.0, 1.25, 0.85, along_v=True),
    ),
    source=(
        "Handsontec LM2596S module drawing (board, pads); Bourns 3296 (trimmer); "
        "TI LM2596 KTT package (D2PAK); seller photographs (placement)"
    ),
)

#: The SN65HVD230 CAN transceiver breakout, sold as CJMCU-230 or "VP230 module": the SO-8
#: chip in the middle, its decoupling capacitors to one side and its slope resistor and the
#: 120 ohm terminator to the other, the header along one edge. The board is the size sellers
#: give (16 x 14.5 mm); the chip is TI's D package; the passives are 0805.
SN65HVD230_MODULE = ModuleArt(
    key="sn65hvd230",
    names=("hvd230", "vp230", "cjmcu-230", "cjmcu230"),
    board=(16.0, 14.5),
    pins=6,
    frame="header",
    parts=(
        ArtPart("soic8", 0.0, 2.2, 4.9, 6.0, 1.6, facing=-1, text="VP230"),
        ArtPart("chip-c", -5.6, -0.2, 2.0, 1.25, 0.85, along_v=True),
        ArtPart("chip-c", -5.6, 3.4, 2.0, 1.25, 0.85, along_v=True),
        ArtPart("chip-r", 5.6, -0.2, 2.0, 1.25, 0.6, along_v=True),
        ArtPart("chip-r", 5.6, 3.4, 2.0, 1.25, 0.6, along_v=True),
        ArtPart("silk", 0.0, 6.2, 9.0, 1.0, 0.0, text="SN65HVD230"),
    ),
    source="TI SN65HVD230 D package; seller photographs and board size (placement)",
)

#: Every module there is a layout for, in the order they are tried.
MODULE_ARTS: tuple[ModuleArt, ...] = (LM2596_MODULE, SN65HVD230_MODULE)


def recognise_module(value: str) -> ModuleArt | None:
    """The layout a part's value names, or ``None``. Says nothing about whether it fits."""
    text = value.casefold()
    for art in MODULE_ARTS:
        if any(name in text for name in art.names):
            return art
    return None


def _named(component: ComponentInstance, footprint: Footprint) -> list[tuple[str, str]]:
    """``(pin number, upper-case name)`` for every pin that has a name."""
    named = []
    for pin in footprint.pins:
        name = pin_name_of(component, pin)
        if name:
            named.append((pin.number, name.strip().upper()))
    return named


def _is_input(name: str) -> bool:
    return name.startswith(("IN", "VIN"))


def _is_output(name: str) -> bool:
    return name.startswith(("OUT", "VOUT"))


def _is_positive(name: str) -> bool:
    return name.endswith("+") or name in ("VIN", "VOUT", "IN", "OUT")


def fit_module_art(
    footprint: Footprint, component: ComponentInstance, pitch: float
) -> tuple[PlacedArt, ...] | None:
    """What stands on this module's board, in the footprint's frame -- or ``None`` to draw
    the block: not a module, a value nobody wrote a layout for, or a board the layout does
    not fit (see the module docstring)."""
    if footprint.body.archetype != "module-board":
        return None
    art = recognise_module(component.value)
    if art is None or len(footprint.pins) != art.pins:
        return None
    placement = placement_for(footprint, pitch)
    cx, cy = placement.centre_x, placement.centre_y
    top = float(footprint.body.dims.get("top", 0.0))
    if top <= 0:
        return None
    pins = {pin.number: (pin.d_col * pitch - cx, pin.d_row * pitch - cy) for pin in footprint.pins}

    # Which local axis ``u`` lies along, and which way each art axis points in it.
    if art.frame == "power":
        u_along_x = placement.size_x >= placement.size_y
    else:
        xs = [x for x, _y in pins.values()]
        ys = [y for _x, y in pins.values()]
        if max(ys) - min(ys) > 1e-6 and max(xs) - min(xs) > 1e-6:
            return None  # a header layout is for ONE row of pins
        u_along_x = max(xs) - min(xs) >= max(ys) - min(ys)

    def along(point: tuple[float, float]) -> tuple[float, float]:
        """A local offset from the board's centre, as (u, v) before any flip."""
        return (point[0], point[1]) if u_along_x else (point[1], point[0])

    sign_u = sign_v = 1.0
    if art.frame == "power":
        named = _named(component, footprint)
        inputs = [along(pins[number])[0] for number, name in named if _is_input(name)]
        outputs = [along(pins[number])[0] for number, name in named if _is_output(name)]
        positive = [along(pins[number])[1] for number, name in named if _is_positive(name)]
        if inputs and outputs and sum(inputs) / len(inputs) > sum(outputs) / len(outputs):
            sign_u = -1.0
        if positive and sum(positive) / len(positive) > 0:
            sign_v = -1.0
    else:
        row_v = sum(along(point)[1] for point in pins.values()) / len(pins)
        if row_v > 0:
            sign_v = -1.0

    span_u, span_v = (
        (placement.size_x, placement.size_y) if u_along_x else (placement.size_y, placement.size_x)
    )
    ref_u, ref_v = art.board
    if abs(span_u / ref_u - 1) > SIZE_TOLERANCE or abs(span_v / ref_v - 1) > SIZE_TOLERANCE:
        return None
    scale_u, scale_v = span_u / ref_u, span_v / ref_v

    placed: list[PlacedArt] = []
    for part in art.parts:
        u = part.u * scale_u * sign_u
        v = part.v * scale_v * sign_v
        own_u = not part.along_v  # the part's own axis lies along u
        size_u, size_v = (part.length, part.width) if own_u else (part.width, part.length)
        facing = part.facing * int(sign_u if own_u else sign_v)
        x, y = (cx + u, cy + v) if u_along_x else (cx + v, cy + u)
        size_x, size_y = (size_u, size_v) if u_along_x else (size_v, size_u)
        axis: Literal["x", "y"] = "x" if own_u == u_along_x else "y"
        placed.append(
            PlacedArt(
                kind=part.kind,
                x=x,
                y=y,
                size_x=size_x,
                size_y=size_y,
                # Never taller than the id says the tallest part is: that is the height DRC
                # measures, and the picture must not stand over it.
                height=min(part.height, top),
                axis=axis,
                facing=facing,
                text=part.text,
            )
        )
    return tuple(placed)
