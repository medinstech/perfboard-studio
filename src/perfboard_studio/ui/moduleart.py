"""What stands on a module's own board, for the modules the 3D view knows by name.

WHY THIS EXISTS. A module's id (``mod-2x2-p16-r7-43.18x21.08x12-s5``) carries its pins, its
board and the height of its tallest part, and nothing else -- so ``view3d._module_pieces``
stands one dark block that tall in the middle of the board. That is an honest envelope and
a picture of nothing: the first real board laid out with this program carried an LM2596S
step-down module and an SN65HVD230 CAN breakout, and in 3D they were the same blue slab
with a different-sized brick on it. A buck module is two cans, a big inductor, a regulator
and a blue trimmer, and that is how anybody looking at the bench finds it. The same goes for
the five modules the catalog offers (``catalog.py``): an ESP32 devkit is its WROOM can and
antenna, a Nano is the chip turned on its corner with the USB socket at one end, and those
are the modules most boards will carry.

HOW A MODULE IS RECOGNISED: by the part's VALUE, the one thing the document says about what
the part IS -- the same way a resistor's colour code is read from its value
(``bodies.resistor_bands``), so the picture cannot disagree with the parts list. And only
when the id agrees with the drawing the layout was taken from: the same number of pins,
pins along the edges the module has them on, and a board within ``SIZE_TOLERANCE`` of the
reference. Anything else -- a value nobody wrote a layout for, an LM2596 on somebody's
own differently-shaped board, a Nano Every on a classic Nano's footprint -- keeps the block.
A guessed layout on the wrong board would be a picture of a part that is not there.

WHAT IS DRAWN STAYS INSIDE THE ENVELOPE DRC MEASURES. Every part is on the module's board,
and none stands taller than the id's ``top`` (``fit_module_art`` clamps it), so a recognised
module never looks taller or wider than ``component-too-tall`` and the overlap rules think
it is.

THE PIN NAMES STOP AT THE FIRST PART IN THEIR WAY. The names the module's silkscreen
carries (``bodies.pin_labels``) run in from its pins across the board, and on a real devkit
the parts come closer to the pins than any fixed strip could allow: the WROOM can on an
ESP32 devkit is 18 mm wide between rows 25.4 mm apart. So a name runs until it meets a part
(``name_room``), and the layouts keep every name legible -- at no narrower than the views
print a name anywhere (``bodies.PIN_NAME_MIN_SQUEEZE``), or with at least
``NAME_ROOM_ENOUGH_MM``. A real board that puts a small part closer to its pins than that
is drawn with the part moved in, and its ``source`` says which. ``tests/test_module_art.py``
measures all of it.

The layout is in the ART's frame -- ``u`` along the module, ``v`` across it, millimetres
from the board's centre -- and ``fit_module_art`` turns it into the footprint's own frame
(x along the columns, y down the rows, pin 1 at the origin), which both views already know
how to turn with the part. It knows nothing about VTK or Qt: ``view3d`` stands what comes
back up, and ``view2d`` draws it from above, both in ``ART_COLOURS``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from perfboard_studio.model import ComponentInstance, Footprint, pin_name_of

from .bodies import PIN_NAME_HEIGHT_MM, placement_for

#: What one part on a module's board is, which is what ``view3d`` draws it as.
#:
#:  * ``can``         -- an aluminium electrolytic standing up, its stripe on the ``facing`` side.
#:  * ``inductor``    -- a shielded power inductor: a dark square case with rounded corners.
#:  * ``to263``       -- a D2PAK regulator lying flat: tab behind, five legs out of the ``facing`` end.
#:  * ``sot223``      -- a SOT-223 regulator lying flat: its wide tab behind, three legs out of
#:                       the ``facing`` side. ``length`` runs tab to leg tips.
#:  * ``sot23``       -- a SOT-23 transistor: two legs out of one long side and one out of the
#:                       ``facing`` side. ``length`` runs leg tip to leg tip.
#:  * ``trimpot``     -- a multi-turn 3296W trimmer, its brass screw at the ``facing`` end.
#:  * ``soic8``       -- an SO-8 chip, gull-wing legs down both long sides, pin 1 at ``facing``.
#:  * ``qfn``         -- a leadless chip (QFN, DFN, USON): a flat black square on its pads,
#:                       the pin-1 dot at the ``facing`` end.
#:  * ``tqfp32``      -- a 7 mm TQFP-32, eight gull-wing legs a side (``TQFP32_*``). ``length``
#:                       is leg tip to leg tip; the pin-1 dot is at the ``facing`` end.
#:  * ``rf-module``   -- a radio module (WROOM, MINI, ESP-12): its own dark board, the metal
#:                       shield can, and the printed antenna at the ``facing`` end.
#:  * ``usb``         -- a USB socket's metal shell, its mouth at the ``facing`` end.
#:  * ``button``      -- a tactile switch pressed from above: a body and a round cap.
#:  * ``side-button`` -- a tactile switch pressed from the side, its cap out of the ``facing`` end.
#:  * ``led``         -- a chip LED; ``colour`` is its lens, and a square one is an RGB LED.
#:  * ``crystal``     -- a crystal in a metal-lidded ceramic SMD package.
#:  * ``sma``         -- a moulded SMD diode (SMA, SOD-123), the cathode band at ``facing``.
#:  * ``chip-r``      -- a 0805 resistor; ``chip-c`` the same size of ceramic capacitor.
#:  * ``pads``        -- an unfitted header: tinned rings round empty holes, 2.54 mm apart,
#:                       as many as fit the part's length and width.
#:  * ``silk``        -- printing on the module's own board, ``text`` and nothing else.
ArtKind = Literal[
    "can",
    "inductor",
    "to263",
    "sot223",
    "sot23",
    "trimpot",
    # A single-turn SMD trimmer: a square plastic base and the round metal rotor on it, slot
    # and all -- not the blue multi-turn block a buck module has.
    "trimmer",
    "soic8",
    # A 28-leg TSSOP (HTSSOP's outline, 9.7 x 4.4 mm, legs 0.65 mm apart): the DRV8825's.
    "tssop28",
    # A 24-leg SSOP (Toshiba's SSOP24-P-300-0.65A, 7.8 x 5.6 mm, legs 0.65 mm apart): the
    # TB6612FNG's. Drawn as the TSSOP is, from ``GULL_WING_LEGS``.
    "ssop24",
    "qfn",
    "tqfp32",
    "rf-module",
    # A plain metal can soldered straight onto the module's board, over what it shields --
    # not a radio module's own board under its can.
    "shield",
    # A U.FL antenna socket: a small square base and the gold ring a lead clicks onto.
    "ufl",
    "usb",
    "button",
    "side-button",
    "led",
    "crystal",
    "sma",
    "chip-r",
    "chip-c",
    "pads",
    "silk",
]

#: What the parts on a module are made of, as the colours both views paint them in -- one
#: table, so a trimmer is the same blue in 2D as in 3D and a WROOM's can the same steel.
#: Picked as sRGB hex, like ``bodies.BODY_STYLES``; an electrolytic takes that table's own
#: colours instead, so a can on a buck module is the colour of the one beside it.
#: A TSSOP-28's legs: how many down each side, how far apart, and how far each reaches
#: past the moulding (the 6.4 mm span less the 4.4 mm body, halved) -- TI's PWP outline.
TSSOP28_LEGS_PER_SIDE = 14
TSSOP28_PITCH_MM = 0.65
TSSOP28_REACH_MM = 1.0

#: The chips with gull-wing legs down their two long sides, by kind: legs per side, how far
#: apart, and how far each reaches past the moulding. One table, so the 2D view and the 3D
#: builder draw a chip with the same legs. The SSOP-24's reach is the 7.6 mm span less the
#: 5.6 mm body, halved -- Toshiba's SSOP24-P-300-0.65A drawing.
GULL_WING_LEGS: dict[str, tuple[int, float, float]] = {
    "tssop28": (TSSOP28_LEGS_PER_SIDE, TSSOP28_PITCH_MM, TSSOP28_REACH_MM),
    "ssop24": (12, 0.65, 1.0),
}

ART_COLOURS: dict[str, str] = {
    "ferrite": "#2a2b2f",
    "ferrite-top": "#3a3b40",
    "epoxy": "#1d1e22",
    "trimmer": "#2f6fd0",
    "brass": "#c9a45a",
    "slot": "#4a3a1c",
    "resistor": "#17181b",
    "mlcc": "#b48c5a",
    "band": "#a9adb3",
    "ink": "#d9dce1",
    "dot": "#0b0c0e",
    "rf-board": "#15171d",
    "shield": "#c9cbce",
    "antenna": "#8c7440",
    "etch": "#5f6268",
    "usb": "#c4c6c9",
    "mouth": "#101113",
    "switch": "#2a2b2f",
    "frame": "#b9bcc0",
    "lens": "#e7e1cc",
    "package": "#efede6",
    "ceramic": "#d8cfb8",
    "trimmer-base": "#ece8dc",
    "rotor": "#b9bcc0",
}

#: How far a module's board may be from the reference a layout was drawn on, either way, as a
#: fraction. Wide enough for one maker's board against another's drawing of the same module
#: (LM2596 boards are sold from 43 x 20 to 44 x 21.5 mm), narrow enough that a layout is never
#: stretched over a board of another shape.
SIZE_TOLERANCE = 0.15

#: A TQFP-32: a 7 mm body, legs 0.8 mm apart and 0.37 mm wide, eight to a side (Microchip's
#: 32A package, which is the ATmega328P-AU's). One table for the shape ``view3d`` draws and
#: the corners ``outline`` leaves empty.
TQFP32_BODY_MM = 7.0
TQFP32_PITCH_MM = 0.8
TQFP32_LEG_MM = 0.37
TQFP32_LEGS_PER_SIDE = 8

#: A pin name stops this short of a part standing in its way -- the same gap
#: ``bodies.pin_labels`` leaves before the block an unrecognised module is drawn as.
NAME_CLEARANCE_MM = 0.3
#: How far either side of its pin's centre line a name is measured for a part in its way:
#: its letters and a fifth of a millimetre either side.
NAME_LANE_MM = PIN_NAME_HEIGHT_MM / 2 + 0.2
#: The room a layout must leave a long pin name, which no real devkit leaves enough of to
#: print one at full width: a little under the 1.9 mm a 16 mm ESP-12 leaves between itself
#: and the pins of a 25.6 mm D1 mini, the tightest board here.
NAME_ROOM_ENOUGH_MM = 1.5


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
    #: Turned on its corner: its own axis runs at 45 degrees to ``u``, the way the ATmega on
    #: a Nano is. Only a square part, so turning it a quarter more changes nothing.
    diagonal: bool = False
    #: A radio module's antenna: how much of its length, at ``facing``, the shield can
    #: leaves bare. And how far in from the module's sides and far end the can stands.
    antenna: float = 0.0
    inset: float = 0.0
    #: The colour a part is seen as where that varies between parts of one kind -- an LED's
    #: lens, a button's cap -- as ``#rrggbb``. Empty for the kind's own.
    colour: str = ""


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
    #: down the ``-v`` edge. ``"columns"``: ``u`` along two columns of pins, one down each
    #: long edge, as a devkit is drawn -- and turned so that ``landmark`` is where it says.
    frame: Literal["power", "header", "columns"]
    parts: tuple[ArtPart, ...]
    #: Where the layout and its sizes come from.
    source: str
    #: Fragments that name ANOTHER board of the same family -- a Nano Every, a Pico W --
    #: which shares the footprint and not the parts, and is drawn as the block.
    excludes: tuple[str, ...] = ()
    #: The module's own board, where it is not the blue most modules are made on: a Pico's
    #: is green, an Espressif devkit's black. Empty for the module style's own.
    board_colour: str = ""
    #: For ``"columns"``: a pin name, and the ends of ``u`` and ``v`` it is at, +1 or -1.
    #: The art is turned end for end, or side for side, until a pin of that name is there,
    #: so a module described from its other end is still drawn with its USB socket at the
    #: socket's end. A module whose pins carry no such name is drawn as the art has it.
    landmark: tuple[str, int, int] | None = None
    #: The real board's parts stand where its pin names would go -- a shield can, a chip
    #: across both rows -- and its maker prints the names on the back. Moving the parts in
    #: until the names fit would draw a board nobody makes, so its names are printed OVER
    #: the parts instead, each on its own tag (``bodies.PinLabel.backed``), at full length.
    names_over_parts: bool = False


@dataclass(frozen=True, slots=True)
class PlacedArt:
    """One part of a recognised module, in the footprint's own frame and millimetres: x
    along the columns, y down the rows, pin 1 at the origin. Each view turns it with the
    part, as it turns the body."""

    kind: ArtKind
    x: float
    y: float
    #: The part's extent along local x and local y, and its height off the module's board.
    #: For a part turned on its corner, its own length and width: ``outline`` is what it
    #: covers.
    size_x: float
    size_y: float
    height: float
    #: Whether its own axis runs along local x (``"x"``) or local y.
    axis: Literal["x", "y"]
    #: Which end of that axis its feature is at, +1 or -1 along it.
    facing: int
    text: str
    diagonal: bool = False
    antenna: float = 0.0
    inset: float = 0.0
    colour: str = ""


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
    key="lm2596-module",
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

# -- the catalog's modules ----------------------------------------------------------------

#: Espressif's devkits are made on black board -- a little lighter than black, so the dark
#: parts on it still stand apart from it, as they do under a bench lamp.
ESPRESSIF_BLACK = "#24262c"
#
# Each is in the catalog's own frame (``catalog.py``): its two pin columns running down the
# board, pin 1 at the top left, the board the catalog's footprint describes -- which takes in
# an antenna or a USB socket standing past the bare board, so a part flush with that edge is
# flush with the footprint's. ``u`` is down the columns and ``v`` across, from that board's
# centre.

#: Espressif's ESP32-DevKitC V4: the WROOM-32 at the top with its antenna 6 mm past the
#: board, the regulator and the USB bridge under it, the two auto-reset transistors by the
#: right-hand pins, and EN and Boot either side of the micro-USB socket. Positions read off
#: Espressif's esp32_devkitc_v4_dimensions drawing; the WROOM's can and antenna measured on
#: KiCad's ESP32-WROOM-32 model. Sellers' clones copy this board part for part.
DEVKITC_MODULE = ModuleArt(
    key="esp32-devkitc",
    board_colour=ESPRESSIF_BLACK,
    names=("devkitc",),
    excludes=("s2", "s3", "c3", "c6", "h2", "wrover", "devkitc-ve", "devkitc ve", "32u"),
    board=(54.3, 27.94),
    pins=38,
    frame="columns",
    landmark=("3V3", -1, -1),
    parts=(
        ArtPart("rf-module", -14.4, 0.0, 25.5, 18.0, 3.1, facing=-1, antenna=6.94, inset=1.0,
                text="ESP32-WROOM-32"),
        ArtPart("chip-c", 5.68, -8.0, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 5.68, -5.85, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 9.4, -5.85, 2.0, 1.25, 0.85),
        ArtPart("sot223", 7.67, 0.12, 7.0, 6.5, 1.7, along_v=True, facing=-1),
        ArtPart("sot23", 7.75, 7.77, 2.4, 2.9, 1.1),
        ArtPart("qfn", 14.68, 0.2, 5.0, 5.0, 0.9, facing=-1, text="CP2102N"),
        ArtPart("sot23", 15.71, 7.77, 2.4, 2.9, 1.1),
        ArtPart("led", 18.82, -4.65, 1.6, 0.8, 0.6, colour="#d83a32"),
        ArtPart("button", 23.67, -7.76, 4.7, 3.5, 2.0),
        ArtPart("usb", 24.65, 0.0, 5.0, 7.5, 2.5, facing=1),
        ArtPart("button", 23.67, 7.77, 4.7, 3.5, 2.0),
    ),
    source=(
        "Espressif esp32_devkitc_v4_dimensions (positions); KiCad ESP32-WROOM-32 model "
        "(the can and the antenna)"
    ),
)

#: Espressif's ESP32-C3-DevKitM-1: the ESP32-C3-MINI-1 at the top, its antenna past the
#: board, the regulator under it, the RGB LED on IO8 and the USB bridge, two transistors
#: by the right-hand pins, and Boot and RST either side of the micro-USB socket. Positions
#: read off Espressif's DIMENSION_ESP32-C3-DEVKITM-1 drawing. The two buttons stand 0.5 mm
#: and the transistors 0.1 mm further in than the board has them: where the board has them,
#: the names beside those pins would be squeezed past reading.
C3_DEVKITM_MODULE = ModuleArt(
    key="esp32-c3-devkitm-1",
    board_colour=ESPRESSIF_BLACK,
    names=("c3-devkitm", "c3 devkitm", "c3_devkitm"),
    board=(44.31, 25.4),
    pins=30,
    frame="columns",
    landmark=("IO19", 1, 1),
    parts=(
        ArtPart("rf-module", -13.85, 0.0, 16.6, 13.2, 2.4, facing=-1, antenna=5.4, inset=0.4,
                text="ESP32-C3-MINI-1"),
        ArtPart("sot223", 1.18, -0.83, 7.0, 6.5, 1.7, along_v=True, facing=-1),
        ArtPart("led", -0.44, 6.69, 3.5, 3.5, 1.5),
        ArtPart("sot23", 8.03, 7.45, 2.4, 2.9, 1.1),
        ArtPart("qfn", 8.48, -2.18, 4.0, 4.0, 0.9, facing=-1),
        ArtPart("sot23", 11.84, 7.45, 2.4, 2.9, 1.1),
        ArtPart("led", 12.35, -8.18, 1.6, 0.8, 0.6, colour="#d83a32"),
        ArtPart("sma", 13.07, -4.53, 1.7, 1.25, 0.9, along_v=True),
        ArtPart("button", 18.4, -7.0, 4.6, 3.1, 2.0),
        ArtPart("usb", 19.65, 0.0, 5.0, 7.5, 2.5, facing=1),
        ArtPart("button", 18.4, 7.0, 4.6, 3.1, 2.0),
    ),
    source=(
        "Espressif DIMENSION_ESP32-C3-DEVKITM-1_V1 (positions); ESP32-C3-MINI-1 datasheet "
        "(the module)"
    ),
)

#: The Arduino Nano: the unfitted ICSP header at the far end, the four LEDs (TX, RX, power,
#: L) across the board, the reset button, the ATmega328P turned on its corner and the mini-B
#: socket at the USB end. Positions read off the mechanical drawing in Arduino's A000005
#: datasheet, whose board is 43.2 mm with the pins centred on it; the catalog's footprint
#: is KiCad's, whose 45.72 mm takes in the socket standing past the board. The chip is
#: centred on a pin row, 1 mm short of where the drawing has it, so its corners stand in one
#: name's way on each side rather than two; the outer LEDs stand 0.2-0.3 mm in. Both keep
#: the pin names beside them readable.
NANO_MODULE = ModuleArt(
    key="arduino-nano",
    names=("nano",),
    excludes=("every", "33", "esp32", "rp2040", "matter", "r4", "nanovna"),
    board=(45.72, 17.78),
    pins=30,
    frame="columns",
    landmark=("D13", 1, 1),
    parts=(
        ArtPart("pads", -20.16, 0.0, 5.08, 7.62, 0.0),
        ArtPart("led", -8.61, -4.6, 2.0, 1.25, 0.8),
        ArtPart("led", -8.61, -2.12, 2.0, 1.25, 0.8),
        ArtPart("led", -8.61, 1.44, 2.0, 1.25, 0.8),
        ArtPart("led", -8.61, 4.6, 2.0, 1.25, 0.8),
        ArtPart("button", -3.78, 0.44, 4.12, 2.95, 2.0, along_v=True, colour="#efece4"),
        ArtPart("tqfp32", 3.81, 0.0, 9.0, 9.0, 1.2, facing=-1, diagonal=True,
                text="ATMEGA328P"),
        ArtPart("usb", 18.06, 0.0, 9.6, 7.7, 3.9, facing=1),
    ),
    source=(
        "Arduino A000005 datasheet, mechanical drawing (positions); Microchip 32A package "
        "(the chip)"
    ),
)

#: The Raspberry Pi Pico: the micro-USB socket and the LED at the top, BOOTSEL, the flash,
#: the regulator's inductors and diode, the RP2040 in the middle and its crystal under it.
#: Every position and size measured on KiCad's RaspberryPi_Pico model. The diode and one
#: inductor stand 0.5 and 0.7 mm in from where the model has them, clear of the names
#: beside the right-hand pins.
PICO_MODULE = ModuleArt(
    key="raspberry-pi-pico",
    board_colour="#2a7a40",
    names=("pico",),
    excludes=("pico w", "pico-w", "pico_w", "picow", "pico 2", "pico2", "pico-2", "esp32"),
    board=(52.3, 21.0),
    pins=40,
    frame="columns",
    landmark=("VBUS", -1, 1),
    parts=(
        ArtPart("usb", -23.08, 0.0, 5.06, 6.66, 2.45, facing=-1),
        ArtPart("led", -20.05, -5.7, 1.0, 0.8, 0.6, along_v=True, colour="#3fae49"),
        ArtPart("sma", -18.35, 5.5, 3.6, 1.66, 0.95),
        ArtPart("chip-c", -16.45, 2.9, 2.0, 1.25, 1.25, along_v=True),
        ArtPart("inductor", -13.95, 2.9, 2.5, 2.5, 0.75),
        ArtPart("inductor", -13.95, 5.3, 2.5, 2.0, 1.2),
        ArtPart("button", -12.85, -3.5, 4.26, 3.2, 2.5, colour="#f2f0ea"),
        ArtPart("chip-c", -11.45, 2.9, 2.0, 1.25, 1.25, along_v=True),
        ArtPart("qfn", -5.75, -3.8, 3.0, 2.0, 0.6),
        ArtPart("qfn", 1.15, 0.0, 7.0, 7.0, 0.9, facing=-1, text="RP2-B2"),
        ArtPart("crystal", 9.7, -2.3, 3.2, 2.5, 0.6, along_v=True),
    ),
    source="KiCad RaspberryPi_Pico model (every position and size)",
)

#: The WEMOS D1 mini as everybody has it -- the v2 and v3 boards and their clones: the
#: ESP-12F flush with the top edge and the reset button pressed from the left-hand edge.
#: The USB socket and the USB bridge are underneath. Board and the module's place from
#: KiCad's WEMOS_D1_mini_light model; the can and the antenna from its ESP-12E model.
D1_MINI_MODULE = ModuleArt(
    key="wemos-d1-mini",
    names=("d1 mini", "d1-mini", "d1_mini", "d1mini"),
    excludes=("pro", "lite", "light", "esp32", "c3", "s2"),
    board=(34.2, 25.6),
    pins=16,
    frame="columns",
    landmark=("5V", 1, 1),
    parts=(
        ArtPart("rf-module", -5.1, 0.0, 24.0, 16.0, 3.2, facing=-1, antenna=7.75, inset=2.0,
                text="ESP-12F"),
        ArtPart("side-button", 14.3, -11.5, 2.6, 4.0, 1.6, along_v=True, facing=-1),
    ),
    source=(
        "KiCad WEMOS_D1_mini_light model (board, the module's place) and ESP-12E model "
        "(the can and the antenna); LOLIN's D1 mini drawings (the reset button)"
    ),
)

#: Pololu's A4988 carrier (item 1182) as its own top-view photograph has it: the chip left of
#: middle, the two R068 sense resistors down the motor side, the motor supply's capacitor
#: across the top and the current-limit trimmer at the bottom. Positions measured on that
#: photograph at 59 px/mm against the 0.6 x 0.8 inch outline of its dimension diagram;
#: sizes are the packages' own. The chip and the sense resistors stand where the names
#: beside the pins would go -- Pololu prints them on the back -- so they are printed over
#: the parts (``names_over_parts``) and every part is where the photograph has it.
#:
#: Only "Pololu" names it. The red and green StepStick boards sold as "A4988" share the pins
#: and not the layout, so they keep the block rather than wear Pololu's parts.
POLOLU_A4988_MODULE = ModuleArt(
    key="pololu-a4988",
    board_colour=PICO_MODULE.board_colour,
    names=("pololu a4988",),
    board=(20.32, 15.24),
    pins=16,
    frame="columns",
    landmark=("VMOT", -1, 1),
    names_over_parts=True,
    parts=(
        ArtPart("chip-c", -8.31, 2.58, 4.2, 1.8, 1.25, along_v=True),
        ArtPart("chip-r", -5.2, 3.73, 3.2, 1.6, 0.55),
        ArtPart("qfn", -1.11, -1.78, 5.0, 5.0, 0.9, along_v=True, text="4988"),
        ArtPart("chip-r", 3.68, 3.73, 3.2, 1.6, 0.55),
        ArtPart("trimmer", 7.43, 1.23, 4.2, 3.1, 1.9, along_v=True),
    ),
    source=(
        "Pololu item 1182: the top-view photograph (positions) and the dimension diagram "
        "(the 0.6 x 0.8 inch board); Allegro A4988 ET package (the 5 x 5 mm QFN)"
    ),
)

#: Pololu's DRV8825 carrier (item 2133) as its own top-view photograph has it: the TSSOP
#: across the lower half, the current-limit trimmer, the two R100 sense resistors and the
#: motor supply's capacitor along the top, small capacitors either side. Positions measured
#: on that photograph at 46.7 px/mm against the 0.6 x 0.8 inch outline; sizes are the
#: packages' own (TI's PWP outline for the chip). The chip spans both rows of names, which
#: Pololu prints on the back, so they are printed over it.
POLOLU_DRV8825_MODULE = ModuleArt(
    key="pololu-drv8825",
    board_colour="#5f288c",
    names=("pololu drv8825",),
    board=(20.32, 15.24),
    pins=16,
    frame="columns",
    landmark=("VMOT", -1, 1),
    names_over_parts=True,
    parts=(
        ArtPart("trimmer", -7.66, -3.6, 3.8, 3.0, 1.9),
        ArtPart("chip-r", -7.47, -0.64, 3.2, 1.6, 0.55),
        ArtPart("chip-r", -7.47, 1.56, 3.2, 1.6, 0.55),
        ArtPart("chip-c", -7.69, 3.75, 3.2, 1.6, 1.25),
        ArtPart("chip-c", -4.05, -3.64, 2.0, 1.25, 0.85, along_v=True),
        ArtPart("chip-c", -2.66, -3.64, 2.0, 1.25, 0.85, along_v=True),
        ArtPart("chip-c", -3.08, 2.57, 2.0, 1.25, 0.85),
        ArtPart("chip-c", -3.08, 4.18, 2.0, 1.25, 0.85),
        ArtPart("tssop28", 3.13, -0.05, 9.7, 6.4, 1.2, along_v=True),
        ArtPart("chip-c", 9.01, -3.64, 2.0, 1.25, 0.85, along_v=True),
        ArtPart("chip-r", 9.01, -0.43, 1.6, 0.8, 0.45, along_v=True),
        ArtPart("chip-r", 9.01, 3.21, 1.6, 0.8, 0.45, along_v=True),
    ),
    source=(
        "Pololu item 2133: the top-view photograph (positions) and the dimension diagram "
        "(the 0.6 x 0.8 inch board); TI DRV8825 PWP package (the chip)"
    ),
)

#: The Seeed XIAO ESP32C3, USB-C at the top: the socket, the shield can over the chip, the
#: BOOT and RESET buttons and the U.FL antenna socket along the far end, the charge LED in
#: the corner. Every position from Seeed's own KiCad board (XIAO ESP32C3 v1.3) except the
#: can's, which the board does not carry and is measured on Seeed's photograph. The socket
#: stands 1.8 mm past the end of the board; only what is over the board is drawn. The can
#: covers the board where the names would go, and Seeed prints them on the back.
XIAO_ESP32C3_MODULE = ModuleArt(
    key="seeed-xiao-esp32c3",
    board_colour=ESPRESSIF_BLACK,
    names=("xiao esp32c3", "xiao esp32-c3", "xiao-esp32c3", "xiao_esp32c3"),
    board=(21.0, 17.78),
    pins=14,
    frame="columns",
    landmark=("5V", -1, 1),
    names_over_parts=True,
    parts=(
        ArtPart("usb", -7.7, 0.0, 5.6, 8.94, 3.2, facing=-1),
        ArtPart("led", -9.86, 5.72, 1.0, 0.5, 0.35, along_v=True, colour="#e0402f"),
        ArtPart("shield", 1.35, -0.09, 10.7, 12.5, 1.8, text="XIAO ESP32C3"),
        ArtPart("button", 8.95, -4.45, 3.6, 2.0, 1.0, along_v=True),
        ArtPart("ufl", 9.08, 0.0, 2.6, 2.6, 1.25),
        ArtPart("button", 8.95, 4.45, 3.6, 2.0, 1.0, along_v=True),
    ),
    source=(
        "Seeed XIAO ESP32C3 v1.3 KiCad board (every part's place); Seeed's photograph of "
        "the board (the shield can, and how far the socket overhangs)"
    ),
)

#: Every module there is a layout for, in the order they are tried.
#: SparkFun's red solder mask: its boards are red, and a blue block would be somebody else's.
SPARKFUN_RED = "#b8262b"

#: SparkFun's dual TB6612FNG motor driver (ROB-14451, v1.1c): the SSOP-24 in the middle with
#: its pin 1 towards VM, the two 0402 decoupling capacitors above it and the 10 uF tantalum
#: above them, its + end towards the left-hand pins. Every position and package read off
#: SparkFun's own Eagle board (SparkFun_Motor_Driver-TB6612FNG_v11c.brd); the chip's size is
#: Toshiba's SSOP24-P-300-0.65A drawing and the tantalum EIA 3528's, drawn as the moulded
#: part with its band on the + end that tantalums mark. The chip's pin 1 is at its top LEFT
#: on the real board; the builders put a chip's dot on one side of its axis only, so here it
#: is drawn at the top right -- the right end, the wrong side.
SPARKFUN_TB6612_MODULE = ModuleArt(
    key="sparkfun-tb6612fng",
    board_colour=SPARKFUN_RED,
    names=("sparkfun tb6612",),
    board=(20.32, 20.32),
    pins=16,
    frame="columns",
    landmark=("VM", -1, -1),
    parts=(
        ArtPart("ssop24", 1.27, 0.0, 7.8, 7.6, 1.5, facing=-1, text="TB6612"),
        ArtPart("chip-c", -3.81, 1.27, 1.0, 0.5, 0.5, along_v=True),
        ArtPart("chip-c", -3.81, -1.27, 1.0, 0.5, 0.5, along_v=True),
        ArtPart("sma", -6.35, 0.0, 3.5, 2.8, 1.9, along_v=True, facing=-1),
    ),
    source=(
        "SparkFun Motor Driver - Dual TB6612FNG v1.1c Eagle board (the 0.8 x 0.8 inch board, "
        "every part's position); Toshiba TB6612FNG SSOP24-P-300-0.65A (the chip); EIA 3528 "
        "(the tantalum)"
    ),
)

#: Pololu's DRV8833 dual motor driver carrier (item 2130) as its own top-view pinout picture
#: has it: the 10 uF capacitor and the 180 ohm resistor along the top, the reverse-
#: protection MOSFET and its diode under them, the QFN in the middle, small capacitors and
#: resistors down the left, and the four pads for the sense resistors, unfitted, at the
#: bottom (bare copper, not drawn). Positions measured on that picture at 19.7 px/mm against
#: the 0.4 inch between its header rows; sizes are the packages' own (TI's RTY outline for
#: the chip). The parts stand close to the pins on both sides, and Pololu prints the names
#: on the back, so they are printed over the parts.
POLOLU_DRV8833_MODULE = ModuleArt(
    key="pololu-drv8833",
    board_colour=PICO_MODULE.board_colour,
    names=("pololu drv8833",),
    board=(20.32, 12.7),
    pins=16,
    frame="columns",
    landmark=("VMM", -1, -1),
    names_over_parts=True,
    parts=(
        ArtPart("chip-c", -8.42, 1.6, 3.2, 1.6, 1.6, along_v=True),
        ArtPart("chip-r", -8.08, -2.27, 1.6, 0.8, 0.45, along_v=True),
        ArtPart("sma", -6.31, -1.42, 1.7, 1.25, 0.9, along_v=True),
        ArtPart("sot23", -5.49, 1.9, 2.4, 2.9, 1.1, along_v=True),
        ArtPart("chip-c", -4.71, -1.88, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-r", -3.17, 2.01, 1.6, 0.8, 0.45, along_v=True),
        ArtPart("chip-c", -0.34, -3.01, 1.6, 0.8, 0.8),
        ArtPart("qfn", 0.8, 0.51, 4.0, 4.0, 0.8, text="8833"),
        ArtPart("chip-c", 3.85, -2.96, 1.6, 0.8, 0.8),
        ArtPart("chip-r", 7.31, -2.65, 1.6, 0.8, 0.45),
    ),
    source=(
        "Pololu item 2130: the top-view pinout picture (positions) and the dimension diagram "
        "(the 0.5 x 0.8 inch board); TI DRV8833 RTY package (the 4 x 4 mm chip)"
    ),
)

MODULE_ARTS: tuple[ModuleArt, ...] = (
    LM2596_MODULE,
    SN65HVD230_MODULE,
    DEVKITC_MODULE,
    C3_DEVKITM_MODULE,
    NANO_MODULE,
    PICO_MODULE,
    D1_MINI_MODULE,
    POLOLU_A4988_MODULE,
    POLOLU_DRV8825_MODULE,
    XIAO_ESP32C3_MODULE,
    SPARKFUN_TB6612_MODULE,
    POLOLU_DRV8833_MODULE,
)


def recognise_module(value: str) -> ModuleArt | None:
    """The layout a part's value names, or ``None``. Says nothing about whether it fits."""
    text = value.casefold()
    for art in MODULE_ARTS:
        if any(name in text for name in art.names) and not any(
            other in text for other in art.excludes
        ):
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


#: Which local axis the art's ``u`` lies along, and which way ``u`` and ``v`` point there.
type _Frame = tuple[bool, float, float]


def _frame(
    art: ModuleArt,
    component: ComponentInstance,
    footprint: Footprint,
    pins: dict[str, tuple[float, float]],
    long_side_x: bool,
) -> _Frame | None:
    """How the art lies against these pins, or ``None`` when they are not laid out the way
    its frame needs. ``pins`` are offsets from the board's centre."""
    xs = {round(x, 6) for x, _y in pins.values()}
    ys = {round(y, 6) for _x, y in pins.values()}
    if art.frame == "power":
        u_along_x = long_side_x
    elif art.frame == "header":
        if len(xs) > 1 and len(ys) > 1:
            return None  # a header layout is for ONE row of pins
        u_along_x = max(xs) - min(xs) >= max(ys) - min(ys)
    else:
        # Two columns of pins, one down each long edge.
        if len(xs) == 2 and len(ys) != 2:
            u_along_x = False
        elif len(ys) == 2 and len(xs) != 2:
            u_along_x = True
        else:
            return None

    def along(point: tuple[float, float]) -> tuple[float, float]:
        """A local offset from the board's centre, as (u, v) before any flip."""
        return (point[0], point[1]) if u_along_x else (point[1], point[0])

    sign_u = sign_v = 1.0
    named = _named(component, footprint)
    if art.frame == "power":
        inputs = [along(pins[number])[0] for number, name in named if _is_input(name)]
        outputs = [along(pins[number])[0] for number, name in named if _is_output(name)]
        positive = [along(pins[number])[1] for number, name in named if _is_positive(name)]
        if inputs and outputs and sum(inputs) / len(inputs) > sum(outputs) / len(outputs):
            sign_u = -1.0
        if positive and sum(positive) / len(positive) > 0:
            sign_v = -1.0
    elif art.frame == "header":
        row_v = sum(along(point)[1] for point in pins.values()) / len(pins)
        if row_v > 0:
            sign_v = -1.0
    elif art.landmark is not None:
        name, end_u, end_v = art.landmark
        found = [along(pins[number]) for number, pin_name in named if pin_name == name.upper()]
        if len(found) == 1:
            u, v = found[0]
            sign_u = -1.0 if u * end_u < 0 else 1.0
            sign_v = -1.0 if v * end_v < 0 else 1.0
    return u_along_x, sign_u, sign_v


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
    frame = _frame(art, component, footprint, pins, placement.size_x >= placement.size_y)
    if frame is None:
        return None
    u_along_x, sign_u, sign_v = frame

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
                diagonal=part.diagonal,
                antenna=part.antenna,
                inset=part.inset,
                colour=part.colour,
            )
        )
    return tuple(placed)


def prints_names_over_parts(component: ComponentInstance) -> bool:
    """Whether the layout this part's value names prints its pin names over its parts
    (``ModuleArt.names_over_parts``). Asked only once ``fit_module_art`` has said it fits."""
    art = recognise_module(component.value)
    return art is not None and art.names_over_parts


def board_colour_for(
    footprint: Footprint, component: ComponentInstance, pitch: float
) -> str | None:
    """The colour of this module's own board, when that is not the module style's blue --
    or ``None``. Only where the layout itself is drawn: a board coloured as a Pico is a board
    drawn as one. Asked by both views and the STEP export, so the three agree."""
    art = recognise_module(component.value)
    if art is None or not art.board_colour:
        return None
    if fit_module_art(footprint, component, pitch) is None:
        return None
    return art.board_colour


# -- what a part covers ------------------------------------------------------------------


def tqfp32_corner(length: float) -> float:
    """How much of each corner of a TQFP-32's ``length``-square has no leg in it: a quad
    pack's legs stop short of its corners, and turned on its corner that is the whole
    difference between the chip and a square."""
    reach = (TQFP32_LEGS_PER_SIDE - 1) / 2 * TQFP32_PITCH_MM + TQFP32_LEG_MM / 2
    return max(length / 2 - reach, 0.0)


def outline(part: PlacedArt) -> tuple[tuple[float, float], ...]:
    """What ``part`` covers of the module's board, as a convex polygon in the footprint's
    frame: its rectangle, less the empty corners of a quad pack, turned on its corner if
    it stands that way. What the pin names stop at (``name_room``)."""
    half_x, half_y = part.size_x / 2, part.size_y / 2
    cut = tqfp32_corner(min(part.size_x, part.size_y)) if part.kind == "tqfp32" else 0.0
    if cut > 0:
        corners = [
            (half_x, half_y - cut), (half_x - cut, half_y), (-half_x + cut, half_y),
            (-half_x, half_y - cut), (-half_x, -half_y + cut), (-half_x + cut, -half_y),
            (half_x - cut, -half_y), (half_x, -half_y + cut),
        ]  # fmt: skip
    else:
        corners = [(half_x, half_y), (-half_x, half_y), (-half_x, -half_y), (half_x, -half_y)]
    if part.diagonal:
        turn = math.sqrt(0.5)
        corners = [((x - y) * turn, (x + y) * turn) for x, y in corners]
    return tuple((part.x + x, part.y + y) for x, y in corners)


def _within_lane(
    points: Sequence[tuple[float, float]], half: float
) -> list[tuple[float, float]]:
    """A convex polygon given as ``(along, across)`` points, cut to ``|across| <= half``."""
    kept = list(points)
    for sign in (1.0, -1.0):
        if not kept:
            break
        cut: list[tuple[float, float]] = []
        for index, (s0, t0) in enumerate(kept):
            s1, t1 = kept[(index + 1) % len(kept)]
            inside0, inside1 = sign * t0 <= half, sign * t1 <= half
            if inside0:
                cut.append((s0, t0))
            if inside0 != inside1:
                share = (sign * half - t0) / (t1 - t0)
                cut.append((s0 + (s1 - s0) * share, sign * half))
        kept = cut
    return kept


def name_room(
    parts: Sequence[PlacedArt], x: float, y: float, dx: float, dy: float, start: float
) -> float:
    """How far a pin name may run from ``start`` before it meets one of ``parts``, less
    ``NAME_CLEARANCE_MM``: the name of the pin at ``(x, y)``, running along ``(dx, dy)``
    across the module's board. Infinite when nothing stands in its lane; printing on the
    board (``silk``) stands in nothing's way."""
    room = math.inf
    for part in parts:
        if part.kind == "silk":
            continue
        # Along the name from its pin, and across it.
        local = [
            ((px - x) * dx + (py - y) * dy, (py - y) * dx - (px - x) * dy)
            for px, py in outline(part)
        ]
        lane = _within_lane(local, NAME_LANE_MM)
        if not lane:
            continue
        nearest = min(s for s, _t in lane)
        if max(s for s, _t in lane) <= start:
            continue  # between the pin and where its name starts: under the pad ring
        room = min(room, nearest - start - NAME_CLEARANCE_MM)
    return max(room, 0.0)
