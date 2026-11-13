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
#:  * ``sot23-5``     -- a SOT-23-5 regulator: three legs out of one long side and two out of
#:                       the ``facing`` side, 0.95 mm apart.
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
#:  * ``sma``         -- a moulded SMD diode (SMA, SOD-123), the cathode band at ``facing``;
#:                       with a ``colour``, a tantalum capacitor of that colour, its band
#:                       (the + end) a darker shade of it.
#:  * ``chip-r``      -- a 0805 resistor; ``chip-c`` the same size of ceramic capacitor.
#:  * ``pads``        -- an unfitted header: tinned rings round empty holes, 2.54 mm apart,
#:                       as many as fit the part's length and width.
#:  * ``silk``        -- printing on the module's own board, ``text`` and nothing else.
#:  * ``hole``        -- a mounting hole through the module's board, ``length`` across its
#:                       ring: bare board ``HOLE_EDGE_MM`` wide round it (a GY-521's), or a
#:                       plated ring ``inset`` wide in ``colour`` (an OLED module's).
#:  * ``oled``        -- an OLED panel's glass, its viewing area (``OLED_VIEW_MM``) black on
#:                       it and the ledge its driver is bonded to at the ``facing`` end.
#:  * ``flex``        -- the flexible printed circuit a panel's glass is wired out by, folded
#:                       round the module's edge: copper-coloured, its stiffener dark.
#:  * ``pcb-antenna`` -- an antenna printed on the module's own board: a meander of bare
#:                       copper, each stroke across ``width`` and ``pitch`` from the next.
#:  * ``hc49``        -- an HC-49/US crystal: a steel can with round ends, standing on the board.
#:  * ``fresnel``     -- a PIR sensor's Fresnel lens: its square foot ``length`` x ``width``
#:                       and the dome of ``FRESNEL_DOME_MM`` on it, its top ``height`` above
#:                       the module's board.
#:  * ``terminal``    -- a screw terminal block standing on the module: ``length`` from its
#:                       back to the face its wires go in by, at ``facing``; a screw on top
#:                       per way, the ways ``pitch`` apart across ``width``.
#:  * ``jst-sh``      -- a JST SH socket lying down (a STEMMA QT or Qwiic port): ``length``
#:                       is its housing, its mouth at the ``facing`` end; its contacts'
#:                       tails reach ``JST_SH_TAILS_MM`` out of the other end, only as
#:                       wide as the four of them, so they are drawn past the box. A
#:                       ``colour`` for a housing that is not natural nylon.
#:  * ``sot23-8``     -- a SOT-23-8 (TI's DCN), four gull-wing legs a side, drawn from
#:                       ``GULL_WING_LEGS`` as the TSSOP is.
#:  * ``msop10``      -- a 10-leg MSOP (TI's DGS: 3.0 mm body, 4.9 mm over the legs, five a
#:                       side 0.5 mm apart): the ADS1115's. Drawn from ``GULL_WING_LEGS`` too.
ArtKind = Literal[
    "can",
    "inductor",
    "to263",
    "sot223",
    "sot23",
    "sot23-5",
    # A SOT-363: a dual transistor, three legs out of each long side -- a level shifter's
    # pair of BSS138s.
    "sot363",
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
    # A 24-leg TSSOP (TI's PW outline, 7.8 x 4.4 mm body, 6.4 mm over the legs, legs 0.65 mm
    # apart): the TCA9548A's. Drawn as the TSSOP is, from ``GULL_WING_LEGS``.
    "tssop24",
    # A 16-leg SO (JEDEC MS-012: 9.9 x 3.9 mm body, legs 1.27 mm apart, 6.0 mm over the legs):
    # the HX711's. Drawn as the TSSOP is, from ``GULL_WING_LEGS``.
    "so16",
    # A SOT-23-8: TI's DCN (R-PDSO-G8), 3.0 x 1.75 mm, legs 0.65 mm apart -- an INA219's.
    "sot23-8",
    # A 10-leg MSOP (TI's DGS, 3.0 mm body): the ADS1115's.
    "msop10",
    # An electret microphone capsule seen from its front: a round metal can, its sound port
    # in the middle of the face. ``length`` is its diameter, ``height`` how far it stands.
    "capsule",
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
    "hole",
    "oled",
    "flex",
    "pcb-antenna",
    "hc49",
    "fresnel",
    "terminal",
    "jst-sh",
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
    # TI's PW drawing: a 6.4 mm span over a 4.4 mm body, twelve legs a side.
    "tssop24": (12, 0.65, 1.0),
    # MS-012: a 6.0 mm span over a 3.9 mm body, eight legs a side.
    "so16": (8, 1.27, 1.05),
    # TI's DCN drawing: a 3.00 mm span over a 1.75 mm body, at most.
    "sot23-8": (4, 0.65, 0.625),
    # TI's DGS drawing: a 4.90 mm span over a 3.00 mm body, five legs a side.
    "msop10": (5, 0.5, 0.95),
}

def gull_wing_dot(body_half: float) -> tuple[float, float, float]:
    """Where a gull-wing chip's pin-1 dot goes on a body ``body_half`` wide either side of
    its axis: ``(in from the end, in from the side, radius)``. In from the side by at most a
    share of the half-width, so a SOT-23-8's lands in its corner and not on its middle; one
    rule, so the 2D and the 3D dot are one dot."""
    return 0.75, min(0.6, body_half * 0.4), min(0.3, body_half * 0.25)


#: The chips whose builders print a pin-1 dot in a corner: at ``facing`` along the chip's
#: axis and at ``across`` across it (``ArtPart.across``).
PIN_ONE_KINDS: frozenset[str] = frozenset({"soic8", "qfn", "tqfp32", *GULL_WING_LEGS})

#: A SOT-23's legs, by kind: where each leaves the body's two long sides, as a share of the
#: body's length, ``(back, front)`` -- the front being the ``facing`` side. One table, so the
#: 2D view and the 3D builder draw the same legs; 0.33 of a 2.9 mm body is the 0.95 mm pitch.
SOT23_LEGS: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
    "sot23": ((-0.33, 0.33), (0.0,)),
    "sot23-5": ((-0.33, 0.0, 0.33), (-0.33, 0.33)),
    # A SOT-363 (SC-88): three legs a side, 0.65 mm apart along its 2.0 mm body.
    "sot363": ((-0.33, 0.0, 0.33), (-0.33, 0.0, 0.33)),
}

#: How much darker a tantalum's band is than its body, as ``QColor.darker`` takes it (190:
#: the colour divided by 1.9), which the 3D view divides its colour by too.
TANTALUM_BAND_SHADE = 190

#: The bare cut edge round a mounting hole, in millimetres.
HOLE_EDGE_MM = 0.12

#: A 0.96 inch 128 x 64 OLED panel's viewing area, across x along its own axis, and the
#: ledge at its ``facing`` end its driver chip is bonded to: Univision's UG-2864HSWEG01
#: drawing (a 26.70 x 19.26 x 1.45 mm panel, the area 23.74 x 12.86 mm). The ledge is the
#: 4.4 mm the calibrated photograph has between the area's border and the glass's edge.
OLED_VIEW_MM = (23.74, 12.86)
OLED_LEDGE_MM = 4.4

#: How wide a printed antenna's copper is: the ESP-01's and the nRF24's, measured on their
#: rectified photographs. How far apart its strokes are is the part's own ``pitch``.
PCB_ANTENNA_TRACE_MM = 0.45
#: The dome of a PIR sensor's Fresnel lens, across: the 23 mm every HC-SR501's sheet gives.
FRESNEL_DOME_MM = 23.0

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
    # A moulded tantalum's yellow, and the bare board's cut edge round a mounting hole and
    # the dark of the hole itself, as the GY-521 photograph has them.
    "tantalum": "#d8b45c",
    "hole-edge": "#d6d2c2",
    "hole": "#101114",
    # An OLED panel's glass and the black of its viewing area, the tinned ring round a
    # plated hole, and the flex circuit's polyimide and its stiffener.
    "glass": "#23262c",
    "oled-view": "#060709",
    "tin": "#c3c6ca",
    "flex": "#c98b2e",
    "flex-stiffener": "#17181b",
    # A PIR's Fresnel lens: milky white polyethylene.
    "fresnel": "#e6e6e1",
    # A screw terminal's blue polyamide (4UCON's drawing 19963 says blue) and its steel
    # screws; a JST SH socket's natural nylon, as a wire-to-board header's is.
    "terminal": "#2d63b4",
    "screw": "#c3c6ca",
    "jst": "#e9e4d4",
}

#: A screw terminal's wire mouth, per way: how wide, and from how high to how high up its
#: face; and how far across its screw head is -- 4UCON's drawing 19963 (the 3.5 mm
#: blocks Adafruit sells), measured on its front view and its top view.
TERMINAL_MOUTH_MM = (2.6, 0.6, 4.4)
TERMINAL_SCREW_MM = 3.0
#: A JST SH socket's contact tails, out of its back: how far they reach past the housing
#: (KiCad's SM04B-SRSS-TB model, 5.05 mm overall against its 4.25 mm housing), and how
#: far apart they are.
JST_SH_TAILS_MM = 0.8
JST_SH_PITCH_MM = 1.0

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
    #: For a ``pcb-antenna``: how far one stroke of its meander is from the next. For a
    #: ``terminal``: how far one way is from the next, which says how many ways it has.
    pitch: float = 0.0
    #: For a chip (``PIN_ONE_KINDS``): which side of its own axis pin 1 is on, as the dot on
    #: it shows in the source the layout was measured on -- +1 or -1 along ``v`` (along ``u``
    #: for a part along ``v``), in the layout as drawn. With ``facing`` that is the corner
    #: the dot goes in, and both turn with the layout. 0 where that source does not show the
    #: dot, and then none is drawn: a missing mark claims nothing, and a wrong one tells a
    #: builder the chip is turned. ``None`` only for a part with no pin 1, or one turned on
    #: its corner (``diagonal``), whose feature IS a corner.
    across: int | None = None


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
    #: For ``"header"``: how many rows the header has, along the board's edge -- an ESP-01's
    #: two rows of four. A layout for one row is never laid over two, nor two over one.
    rows: int = 1
    #: For ``"header"``: the end of ``u`` pin 1 is at, -1 or +1, the layout drawn as the real
    #: board is seen from above with its header along the top (``-v``). A GY-521 seen so has
    #: VCC, its pin 1, at the right.
    pin_one: int = -1


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
    pitch: float = 0.0
    #: Which side of its own axis a chip's pin 1 is on (``ArtPart.across``), turned onto the
    #: footprint: +1 or -1 along local y for a part along x, along local x for one along y.
    #: 0 draws no dot.
    across: int = 0


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
#: give (16 x 14.5 mm); the chip is TI's D package; the passives are 0805. Its chip has no
#: pin-1 dot: none of the sellers' photographs it was placed from is named here to read one
#: off.
SN65HVD230_MODULE = ModuleArt(
    key="sn65hvd230",
    names=("hvd230", "vp230", "cjmcu-230", "cjmcu230"),
    board=(16.0, 14.5),
    pins=6,
    frame="header",
    parts=(
        ArtPart("soic8", 0.0, 2.2, 4.9, 6.0, 1.6, facing=-1, text="VP230", across=0),
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
#: KiCad's ESP32-WROOM-32 model. Sellers' clones copy this board part for part. The USB
#: bridge's pin 1 is the corner its outline is chamfered at on Espressif's
#: esp32_devkitc_v4_pcb_layout: away from the USB socket, on the side of the header that
#: runs GND, 23, 22.
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
        ArtPart("qfn", 14.68, 0.2, 5.0, 5.0, 0.9, facing=-1, text="CP2102N", across=1),
        ArtPart("sot23", 15.71, 7.77, 2.4, 2.9, 1.1),
        ArtPart("led", 18.82, -4.65, 1.6, 0.8, 0.6, colour="#d83a32"),
        ArtPart("button", 23.67, -7.76, 4.7, 3.5, 2.0),
        ArtPart("usb", 24.65, 0.0, 5.0, 7.5, 2.5, facing=1),
        ArtPart("button", 23.67, 7.77, 4.7, 3.5, 2.0),
    ),
    source=(
        "Espressif esp32_devkitc_v4_dimensions (positions); KiCad ESP32-WROOM-32 model "
        "(the can and the antenna); Espressif esp32_devkitc_v4_pcb_layout (the bridge's pin 1)"
    ),
)

#: Espressif's ESP32-C3-DevKitM-1: the ESP32-C3-MINI-1 at the top, its antenna past the
#: board, the regulator under it, the RGB LED on IO8 and the USB bridge, two transistors
#: by the right-hand pins, and Boot and RST either side of the micro-USB socket. Positions
#: read off Espressif's DIMENSION_ESP32-C3-DEVKITM-1 drawing. The two buttons stand 0.5 mm
#: and the transistors 0.1 mm further in than the board has them: where the board has them,
#: the names beside those pins would be squeezed past reading. The USB bridge's pin 1 is
#: where Espressif's PCB_ESP32-C3-DEVKITM-1_V1 layout rings and chamfers U3: away from the
#: USB socket, on the side of the right-hand pins.
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
        ArtPart("qfn", 8.48, -2.18, 4.0, 4.0, 0.9, facing=-1, across=1),
        ArtPart("sot23", 11.84, 7.45, 2.4, 2.9, 1.1),
        ArtPart("led", 12.35, -8.18, 1.6, 0.8, 0.6, colour="#d83a32"),
        ArtPart("sma", 13.07, -4.53, 1.7, 1.25, 0.9, along_v=True),
        ArtPart("button", 18.4, -7.0, 4.6, 3.1, 2.0),
        ArtPart("usb", 19.65, 0.0, 5.0, 7.5, 2.5, facing=1),
        ArtPart("button", 18.4, 7.0, 4.6, 3.1, 2.0),
    ),
    source=(
        "Espressif DIMENSION_ESP32-C3-DEVKITM-1_V1 (positions); ESP32-C3-MINI-1 datasheet "
        "(the module); Espressif PCB_ESP32-C3-DEVKITM-1_V1 (the bridge's pin 1)"
    ),
)

#: Espressif's ESP32-S3-DevKitC-1 (v1.1): the ESP32-S3-WROOM-1 at the top with its antenna 6.3 mm
#: past the board, the regulator and the two auto-reset transistors under it, the RGB LED on
#: IO38, the USB bridge, and BOOT and RESET either side of the two micro-USB sockets (UART
#: left, USB right). Every position read off Espressif's DXF_ESP32-S3-DevKitC-1_V1.1
#: dimensions drawing, whose placement outlines are the parts' own; the module's 25.5 x 18 mm
#: is its datasheet's. The bridge's pin 1 is not marked on the drawing, so none is drawn. The
#: module is 18 mm across on rows 22.86 mm apart, which leaves under a millimetre beside each
#: pin for a name, so the names are printed over it.
S3_DEVKITC_MODULE = ModuleArt(
    key="esp32-s3-devkitc-1",
    board_colour=ESPRESSIF_BLACK,
    names=("s3-devkitc", "s3 devkitc", "s3_devkitc"),
    board=(69.4, 25.4),
    pins=44,
    frame="columns",
    landmark=("TX", -1, 1),
    names_over_parts=True,
    parts=(
        ArtPart("rf-module", -21.95, 0.05, 25.5, 18.0, 3.2, facing=-1, antenna=6.3, inset=1.0,
                text="ESP32-S3-WROOM-1"),
        ArtPart("sot223", -1.92, 0.81, 7.0, 6.5, 1.7, along_v=True, facing=-1),
        ArtPart("sma", -0.52, 6.4, 2.85, 1.48, 0.9),
        ArtPart("sot23", 5.37, -0.13, 2.4, 2.9, 1.1),
        ArtPart("led", 5.37, -5.2, 3.5, 3.5, 1.5),
        ArtPart("sot23", 5.37, 5.08, 2.4, 2.9, 1.1),
        ArtPart("qfn", 14.31, 0.89, 5.0, 5.0, 0.9, facing=-1, text="CP2102N", across=0),
        ArtPart("button", 20.49, -5.17, 3.05, 2.2, 1.5, along_v=True),
        ArtPart("button", 20.49, 5.21, 3.05, 2.2, 1.5, along_v=True),
        ArtPart("sma", 25.5, -2.26, 1.7, 1.25, 0.9, along_v=True),
        ArtPart("sma", 25.5, 2.18, 1.7, 1.25, 0.9, along_v=True),
        ArtPart("usb", 31.66, -6.7, 6.0, 7.4, 2.6, facing=1),
        ArtPart("usb", 31.66, 6.7, 6.0, 7.4, 2.6, facing=1),
    ),
    source=(
        "Espressif DXF_ESP32-S3-DevKitC-1_V1.1 dimensions drawing (positions); ESP32-S3-WROOM-1 "
        "datasheet (the module)"
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
#: beside the right-hand pins. Neither chip has a pin-1 dot: the model's RP2040 and flash are
#: plain boxes, with nothing to say which corner is pin 1.
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
        ArtPart("qfn", -5.75, -3.8, 3.0, 2.0, 0.6, across=0),
        ArtPart("qfn", 1.15, 0.0, 7.0, 7.0, 0.9, facing=-1, text="RP2-B2", across=0),
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
#: and not the layout, so they keep the block rather than wear Pololu's parts. The chip's
#: dot is in its corner nearest VMOT on the photograph.
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
        ArtPart("qfn", -1.11, -1.78, 5.0, 5.0, 0.9, along_v=True, text="4988", across=-1),
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
#: Pololu prints on the back, so they are printed over it. Its dot is at its end towards the
#: VMOT column, on its side towards the trimmer, on the photograph.
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
        ArtPart("tssop28", 3.13, -0.05, 9.7, 6.4, 1.2, along_v=True, across=-1),
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

#: The Seeed XIAO RP2040, USB-C at the top: the socket, the shield can over the chip, the
#: flash, the crystal and the regulator, the RESET and BOOT buttons with the RGB LED between
#: them along the far end, the red power LED and the three-colour user LED beside the socket.
#: Every position from Seeed's own KiCad board (XIAO RP2040 v1.3; ``u`` towards the far end
#: from the socket, ``v`` towards the 5V row), the can's from the pads it
#: is soldered to and its size from Seeed's photograph; what stands under the can is hidden by
#: it, as on the board. The socket stands 1.4 mm past the end (the board's silkscreen outline
#: of it); only what is over the board is drawn. The can covers the board where the names
#: would go, and Seeed prints them on the back.
XIAO_RP2040_MODULE = ModuleArt(
    key="seeed-xiao-rp2040",
    board_colour=ESPRESSIF_BLACK,
    names=("xiao rp2040", "xiao-rp2040", "xiao_rp2040"),
    board=(21.0, 17.78),
    pins=14,
    frame="columns",
    landmark=("5V", -1, 1),
    names_over_parts=True,
    parts=(
        ArtPart("usb", -7.56, 0.0, 5.88, 8.94, 3.2, facing=-1),
        ArtPart("led", -7.53, 5.67, 1.0, 1.0, 0.5, colour="#4a4540"),
        ArtPart("led", -5.21, 5.77, 1.0, 0.5, 0.35, along_v=True, colour="#e0402f"),
        ArtPart("shield", 2.14, 0.05, 10.6, 12.4, 1.2, text="XIAO RP2040"),
        ArtPart("button", 9.11, -4.06, 3.6, 2.0, 1.0, along_v=True),
        ArtPart("led", 9.11, 0.0, 2.4, 2.4, 0.8, colour="#e8e6df"),
        ArtPart("button", 9.11, 4.06, 3.6, 2.0, 1.0, along_v=True),
    ),
    source=(
        "Seeed XIAO RP2040 v1.3 KiCad board (every part's place); Seeed's photograph of "
        "the board (the shield can's size, and how far the socket overhangs)"
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
#: part with its band on the + end that tantalums mark. The chip's pin 1, U1's pad 1 on that
#: board, is at its corner towards VM and the left-hand pins.
SPARKFUN_TB6612_MODULE = ModuleArt(
    key="sparkfun-tb6612fng",
    board_colour=SPARKFUN_RED,
    names=("sparkfun tb6612",),
    board=(20.32, 20.32),
    pins=16,
    frame="columns",
    landmark=("VM", -1, -1),
    parts=(
        ArtPart("ssop24", 1.27, 0.0, 7.8, 7.6, 1.5, facing=-1, text="TB6612", across=-1),
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

#: SparkFun's Arduino Pro Mini 328 (DEV-11113/DEV-11114), read off SparkFun's own Eagle board
#: (Arduino-Pro-Mini.brd): the 0.7 x 1.3 inch board, its two rows of twelve 0.6 inch apart
#: and, on the top side, the ATmega328P turned on its corner with pin 1 at the corner towards
#: the FTDI header, the resonator beside it, the MIC5205 regulator, the two EIA 3216
#: tantalums (+ ends as the board's A pads have them), the 0603 parts, the red power LED, the
#: green one on D13, the reset button, and the pads with no header in them: FTDI along the
#: end, A4/A5 and A6/A7 inside the RAW row, off its grid. ``u`` runs from the D9/D10 end to the
#: FTDI end, ``v`` from the TXO row to the RAW row. Sizes are the packages' (the button and the
#: resonator their tDocu outlines, the pads their 1.7 mm rings).
SPARKFUN_PRO_MINI_MODULE = ModuleArt(
    key="sparkfun-pro-mini",
    board_colour=SPARKFUN_RED,
    names=("pro mini",),
    board=(33.02, 17.78),
    pins=24,
    frame="columns",
    landmark=("RAW", 1, -1),
    # SparkFun prints the names between the pins and the parts in a smaller hand than the
    # tags here, and C19 stands 0.02 mm short of the room "RST" needs: printed over.
    names_over_parts=True,
    parts=(
        ArtPart("tqfp32", -2.54, 0.0, 9.0, 9.0, 1.2, facing=1, diagonal=True,
                text="ATMEGA328P"),
        ArtPart("crystal", 2.51, 4.65, 3.2, 1.3, 0.9, colour="#d8cfb0"),
        ArtPart("sot23-5", 7.67, 0.0, 2.9, 2.8, 1.1, facing=-1),
        ArtPart("sma", 9.52, 4.19, 3.2, 1.6, 1.6, facing=-1),
        ArtPart("sma", 7.62, -4.32, 3.2, 1.6, 1.6, facing=1),
        ArtPart("chip-c", 3.91, 1.70, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", -9.27, -0.13, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", -14.45, 4.34, 1.6, 0.8, 0.8),
        ArtPart("chip-c", 12.70, -3.91, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-r", 10.16, 0.0, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("chip-r", -11.28, 4.34, 1.6, 0.8, 0.5),
        ArtPart("chip-r", -11.61, -4.83, 1.6, 0.8, 0.5),
        ArtPart("led", 5.36, -0.03, 1.6, 0.8, 0.6, along_v=True, colour="#d83a32"),
        ArtPart("led", -14.78, -4.83, 1.6, 0.8, 0.6, colour="#3fae49"),
        ArtPart("button", -13.84, -0.13, 5.08, 5.08, 1.5),
        ArtPart("pads", 15.24, 0.0, 1.7, 14.4, 0.0),
        ArtPart("pads", 2.67, -4.70, 4.24, 1.7, 0.0),
        ArtPart("pads", -7.75, -4.70, 4.24, 1.7, 0.0),
    ),
    source=(
        "SparkFun Arduino Pro Mini 328 Eagle board, github sparkfun/Arduino_Pro_Mini_328, "
        "Hardware/Arduino-Pro-Mini.brd, CC BY-SA 3.0 (the board, both rows, every top-side "
        "part's place, package and turn); Microchip 32A (the chip)"
    ),
)

#: SparkFun's Pro Micro (DEV-12640), read off SparkFun's own Eagle board (Hardware/v13
#: SparkFun_Pro_Micro.brd, whose header, nets and 0.7 x 1.3 inch outline Hardware/v20 repeats):
#: the ATmega32U4 in its QFN-44 on its corner with pin 1 towards the USB end, the 16 MHz crystal
#: at the far end, the MIC5219 regulator, the two tantalums either side of it, the resettable
#: fuse and the diode behind the USB socket, the 0603 parts and the three LEDs -- the red power
#: LED beside the tantalums, the green and the yellow at the far end. ``u`` runs from the D9/D10
#: end to the USB end, ``v`` from the TXO row to the RAW row. Sizes are the packages' (the
#: socket's from its reference outline: 5 x 7.8 mm, its mouth 0.9 mm past the board).
SPARKFUN_PRO_MICRO_MODULE = ModuleArt(
    key="sparkfun-pro-micro",
    board_colour=SPARKFUN_RED,
    names=("pro micro",),
    board=(33.9, 17.78),
    pins=24,
    frame="columns",
    landmark=("RAW", 1, -1),
    # SparkFun prints the names between the pins and the parts, smaller than the tags here, and
    # the tantalums and the 0603s stand 1.2 mm from the pins: printed over the parts, as the
    # Pro Mini's are.
    names_over_parts=True,
    parts=(
        ArtPart("qfn", -2.98, 0.0, 7.0, 7.0, 0.9, facing=1, diagonal=True, text="ATMEGA32U4"),
        ArtPart("crystal", -14.79, 0.0, 5.0, 3.2, 1.0, along_v=True, colour="#d8cfb0"),
        ArtPart("sot23-5", 4.90, -0.25, 2.9, 2.8, 1.1, facing=-1),
        ArtPart("sma", 4.90, 3.82, 3.2, 1.6, 1.6, facing=1, colour="#d8b45c"),
        ArtPart("sma", 4.85, -3.83, 3.2, 1.6, 1.6, facing=1, colour="#d8b45c"),
        ArtPart("chip-c", 7.81, 0.0, 3.2, 1.6, 0.9, along_v=True),
        ArtPart("sma", 9.62, 0.0, 2.5, 1.25, 1.0, along_v=True, facing=-1),
        ArtPart("chip-c", -9.08, 4.43, 1.6, 0.8, 0.8),
        ArtPart("chip-c", -8.82, -4.32, 1.6, 0.8, 0.8),
        ArtPart("chip-c", 1.61, -3.85, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", -12.12, -1.78, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", -12.12, 1.91, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", 1.19, 4.04, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", 8.08, -3.82, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-r", 9.55, 3.82, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("chip-r", 10.99, 3.81, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("chip-r", -15.17, -4.32, 1.6, 0.8, 0.5),
        ArtPart("chip-r", -15.17, 4.32, 1.6, 0.8, 0.5),
        ArtPart("chip-r", 9.54, -3.81, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("chip-r", 10.99, -3.81, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("led", 8.16, 3.82, 1.6, 0.8, 0.6, along_v=True, colour="#d83a32"),
        ArtPart("led", -12.12, -4.32, 1.6, 0.8, 0.6, colour="#3fae49"),
        ArtPart("led", -12.12, 4.32, 1.6, 0.8, 0.6, colour="#e3b92c"),
        ArtPart("usb", 14.45, 0.0, 5.0, 7.5, 2.6, facing=1),
    ),
    source=(
        "SparkFun Pro Micro Eagle board, github sparkfun/Pro_Micro, Hardware/v13/"
        "SparkFun_Pro_Micro.brd, CC BY-SA 3.0 (the board, both rows, every top-side part's "
        "place, package and turn; the diode's band from its package's silkscreen); "
        "Microchip's QFN-44 (the chip)"
    ),
)

#: SparkFun's Logic Level Converter - Bi-Directional (BOB-12009), read off SparkFun's own Eagle
#: board (Logic_Level_Bidirectional.brd): the 0.6 x 0.5 inch board, its two rows of six 0.4
#: inch apart, and on the top side a BSS138 per channel with its two 10k pull-ups, one towards
#: each row. ``u`` runs along the rows from HV1/LV1 to HV4/LV4, ``v`` from the LV row to the
#: HV row, as SparkFun's silkscreen reads. Each SOT-23 has its two legs (gate and source)
#: towards LV and its one (drain) towards HV, as the board's nets have them. Sizes are the
#: packages'; the tallest thing on it is the header pins' tips, 1.6 mm up, which is the
#: footprint's top.
SPARKFUN_LOGIC_LEVEL_MODULE = ModuleArt(
    key="sparkfun-logic-level-converter",
    board_colour=SPARKFUN_RED,
    names=("level converter",),
    board=(15.24, 12.70),
    pins=12,
    frame="columns",
    landmark=("HV1", -1, 1),
    # SparkFun prints each name in the strip between its pin and the 10k beside it, smaller
    # than the tags here: printed over the parts, as the Pro Mini's are.
    names_over_parts=True,
    parts=(
        ArtPart("sot23", -5.66, 0.1, 2.4, 2.9, 1.1, along_v=True, facing=1),
        ArtPart("sot23", -1.80, 0.1, 2.4, 2.9, 1.1, along_v=True, facing=1),
        ArtPart("sot23", 1.98, 0.1, 2.4, 2.9, 1.1, along_v=True, facing=1),
        ArtPart("sot23", 5.74, 0.1, 2.4, 2.9, 1.1, along_v=True, facing=1),
        ArtPart("chip-r", -5.66, -2.59, 1.6, 0.8, 0.5),
        ArtPart("chip-r", -1.78, -2.62, 1.6, 0.8, 0.5),
        ArtPart("chip-r", 1.98, -2.64, 1.6, 0.8, 0.5),
        ArtPart("chip-r", 5.64, -2.64, 1.6, 0.8, 0.5),
        ArtPart("chip-r", -5.61, 2.62, 1.6, 0.8, 0.5),
        ArtPart("chip-r", -1.91, 2.64, 1.6, 0.8, 0.5),
        ArtPart("chip-r", 1.80, 2.64, 1.6, 0.8, 0.5),
        ArtPart("chip-r", 5.61, 2.64, 1.6, 0.8, 0.5),
    ),
    source=(
        "SparkFun Logic Level Converter - Bi-Directional Eagle board, github "
        "sparkfun/Logic_Level_Bidirectional, Hardware/Logic_Level_Bidirectional.brd, CC BY-SA "
        "3.0 (the board, both rows, every top-side part's place, package and turn)"
    ),
)

#: Adafruit's boards: the blue its older ones are made in, sampled on Adafruit's own
#: photograph of its BME280 breakout, and the black of its STEMMA QT ones with their
#: gold-plated holes, as its photograph of the STEMMA QT INA219 shows them. Estimates, as
#: every colour here is.
ADAFRUIT_BLUE = "#0a64b2"
ADAFRUIT_BLACK = "#1c1d20"

#: Adafruit's TCA9548A I2C multiplexer, read off Adafruit's own Eagle board
#: (Adafruit-TCA9548A-I2C-Multiplexer-PCB, 'Adafruit TCA9548A'): the 0.7 x 1.2 inch board, its two
#: rows of twelve 0.6 inch apart and, on the top side, the TSSOP-24 with pin 1 at the corner
#: towards VIN and the controller's header, the 10k resistors of the address pins and the
#: reset, and the pull-up resistors, the bypass capacitor and the reset pull-up in a line
#: along the VIN end. The solder jumpers are not drawn. ``u`` runs from the channel-0 end to the VIN
#: end, ``v`` from the channel row to the VIN row. Sizes are the packages' (the chip TI's PW
#: package, the passives 0805), and the tallest thing on it is the header pins' tips, 1.6 mm up,
#: which is the footprint's top (the chip is 1.2 mm).
ADAFRUIT_TCA9548A_MODULE = ModuleArt(
    key="adafruit-tca9548a",
    board_colour=ADAFRUIT_BLUE,
    names=("tca9548a",),
    board=(30.48, 17.78),
    pins=24,
    frame="columns",
    landmark=("VIN", 1, 1),
    parts=(
        ArtPart("tssop24", 0.76, 0.0, 7.8, 6.4, 1.2, facing=1, text="TCA9548A", across=1),
        ArtPart("chip-r", 6.60, -2.92, 2.0, 1.25, 0.5),
        ArtPart("chip-r", 6.60, -0.89, 2.0, 1.25, 0.5),
        ArtPart("chip-c", 6.60, 1.02, 2.0, 1.25, 0.85),
        ArtPart("chip-r", 6.60, 3.05, 2.0, 1.25, 0.5),
        ArtPart("chip-r", -4.95, -1.91, 2.0, 1.25, 0.5),
        ArtPart("chip-r", -4.95, 0.13, 2.0, 1.25, 0.5),
        ArtPart("chip-r", -4.95, 2.03, 2.0, 1.25, 0.5),
    ),
    source=(
        "Adafruit TCA9548A Eagle board, github adafruit/Adafruit-TCA9548A-I2C-Multiplexer-PCB "
        "(the board, both rows, every top-side part's place, package and turn); TI TCA9548A "
        "PW package (the chip)"
    ),
)

#: Adafruit's ADS1115 (and ADS1015) breakout, product 1085, read off Adafruit's own Eagle
#: board for its STEMMA QT revision (ADS1X15-Breakout-Board-PCBs): the 25.4 x 17.78 mm board
#: with the I2C header (VIN first) and the analog one 12.7 mm apart, a STEMMA QT socket on each
#: short edge with its mouth outwards, the converter in TI's DGS MSOP-10 with its pin 1 towards
#: VIN, the ferrite beads and bypass capacitors of the analog supply, the pull-up array, the
#: power LED, and an M2.5 hole in each corner. The solder jumpers are not drawn. ``u`` runs
#: down the headers from the VIN end, ``v`` across from the I2C header to the analog one. Sizes
#: are the packages': the 0603 and 0805 parts, the resistor array as one 3.2 x 1.6 mm body.
ADAFRUIT_ADS1115_MODULE = ModuleArt(
    key="adafruit-ads1115",
    board_colour=ADAFRUIT_BLACK,
    names=("ads1115", "ads1015"),
    board=(25.4, 17.78),
    pins=12,
    frame="columns",
    landmark=("VIN", -1, -1),
    # The converter, the capacitors and the ferrites stand between the rows where a name
    # would go, and 12.7 mm leaves no room for both: the board is drawn as it is, and the
    # names go over its parts.
    names_over_parts=True,
    parts=(
        ArtPart("msop10", 0.25, 0.64, 3.0, 4.9, 1.1, along_v=True, facing=-1, across=1),
        ArtPart("chip-c", -4.57, 3.05, 2.0, 1.25, 0.85),
        ArtPart("chip-c", -4.45, -3.18, 2.0, 1.25, 0.85),
        ArtPart("chip-c", -4.57, 1.14, 1.6, 0.8, 0.45),
        ArtPart("chip-r", -4.70, -0.44, 1.6, 0.8, 0.5),
        ArtPart("chip-r", 4.89, 0.64, 1.6, 0.8, 0.5),
        ArtPart("chip-r", 0.0, -2.48, 3.2, 1.6, 0.6),
        ArtPart("chip-r", -7.11, 3.43, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("led", -9.14, 3.68, 1.6, 0.8, 0.5, colour="#3fae49"),
        ArtPart("jst-sh", -10.03, 0.0, 4.25, 6.0, 2.9, facing=-1),
        ArtPart("jst-sh", 10.03, 0.0, 4.25, 6.0, 2.9, facing=1),
        ArtPart("hole", -10.16, -6.35, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
        ArtPart("hole", 10.16, -6.35, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
        ArtPart("hole", -10.16, 6.35, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
        ArtPart("hole", 10.16, 6.35, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
    ),
    source=(
        "Adafruit ADS1115 STEMMA QT Eagle board, github adafruit/ADS1X15-Breakout-Board-PCBs, "
        "CC BY-SA (the board, both headers, every top-side part's place, package and turn); TI "
        "ADS1115 datasheet SBAS444, DGS (the chip); KiCad's JST SM04B-SRSS-TB model (the sockets)"
    ),
)

#: Adafruit's INA219 current sensor breakout, both revisions, read off Adafruit's own Eagle
#: boards (github adafruit/Adafruit-INA219-Current-Sensor-PCB) and seen from above with the
#: header along the top, VCC at the right (``pin_one``): the INA219 in TI's SOT-23-8 with its
#: pin 1 towards VCC and away from the header, its 10k pull-ups and decoupling, the 2512
#: shunt across the middle, and the blue 3.5 mm terminal block on the far edge, its wire
#: mouths outwards (4UCON's drawing 19963). The block and the header come loose in the bag
#: and are drawn fitted, the way the board goes onto a perfboard. The sizes are the
#: packages'.
#:
#: The original (four M2.5 holes, 25.4 x 22.24 mm). Its terminal block stands 0.26 mm past the
#: board's edge on Adafruit's board; drawn flush, since nothing is drawn past the body DRC
#: measures.
ADAFRUIT_INA219_MODULE = ModuleArt(
    key="adafruit-ina219",
    board_colour=ADAFRUIT_BLUE,
    names=("ina219",),
    excludes=("stemma", "qt"),
    board=(25.4, 22.24),
    pins=6,
    frame="header",
    pin_one=1,
    parts=(
        ArtPart("sot23-8", 0.0, -2.74, 3.0, 3.0, 1.45, facing=-1, across=1),
        ArtPart("chip-c", 8.69, -2.74, 2.0, 1.25, 0.85, along_v=True),
        ArtPart("chip-r", -5.59, -4.26, 2.0, 1.25, 0.5),
        ArtPart("chip-r", -5.59, -1.73, 2.0, 1.25, 0.5),
        ArtPart("chip-r", 6.15, -2.74, 2.0, 1.25, 0.5, along_v=True),
        ArtPart("chip-r", 3.81, -2.74, 2.0, 1.25, 0.5, along_v=True),
        ArtPart("chip-r", 0.0, 2.42, 6.35, 3.2, 0.6),
        ArtPart("terminal", -0.05, 7.62, 7.0, 7.0, 8.5, along_v=True, facing=1, pitch=3.5),
        ArtPart("hole", -10.16, -8.58, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["tin"]),
        ArtPart("hole", 10.16, -8.58, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["tin"]),
        ArtPart("hole", -10.16, 8.58, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["tin"]),
        ArtPart("hole", 10.16, 8.58, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["tin"]),
    ),
    source=(
        "Adafruit INA219 Eagle board, github adafruit/Adafruit-INA219-Current-Sensor-PCB, "
        "Adafruit_INA219_CurPowerMonitor.brd, CC BY-SA (the board, the header, every top-side "
        "part's place, package and turn); TI INA219 datasheet SBOS448G, DCN (the chip); 4UCON "
        "drawing 19963 (the terminal block)"
    ),
)

#: Adafruit's DRV8871 motor driver breakout, read off Adafruit's own Eagle board
#: (Adafruit-DRV8871-Breakout-PCB, 'Adafruit DRV8871') and checked on its photograph, seen from
#: above with the four-pin header along the top, IN2 at the right (``pin_one``): the driver in
#: its HSOP-8 with its pin 1 towards IN2, the bypass capacitor and the 63 V electrolytic by
#: it, the two blue 3.5 mm terminal blocks on the far edge (the motor's at the right, the power's
#: at the left, their mouths outwards) and an M2.5 hole at each end of the header. The current
#: limit resistor is not drawn. Sizes are the packages': the driver TI's DDA, the can the
#: 6.6 mm footprint's (its height is an estimate), the terminals 4UCON's drawing 19963.
ADAFRUIT_DRV8871_MODULE = ModuleArt(
    key="adafruit-drv8871",
    board_colour=ADAFRUIT_BLUE,
    names=("drv8871",),
    board=(20.32, 24.13),
    pins=4,
    frame="header",
    pin_one=1,
    parts=(
        ArtPart("soic8", 5.46, -1.14, 4.9, 6.0, 1.7, facing=1, across=-1),
        ArtPart("chip-c", 1.40, 0.38, 2.0, 1.25, 0.5, along_v=True),
        ArtPart("can", -4.32, -0.89, 6.6, 6.6, 7.7, facing=-1),
        ArtPart("terminal", 4.37, 8.35, 7.0, 7.0, 8.5, along_v=True, facing=1, pitch=3.5),
        ArtPart("terminal", -4.27, 8.35, 7.0, 7.0, 8.5, along_v=True, facing=1, pitch=3.5),
        ArtPart("hole", -7.62, -9.53, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["tin"]),
        ArtPart("hole", 7.62, -9.53, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["tin"]),
    ),
    source=(
        "Adafruit DRV8871 Eagle board, github adafruit/Adafruit-DRV8871-Breakout-PCB, "
        "'Adafruit DRV8871.brd', CC BY-SA (the board, the header, every top-side part's place, "
        "package and turn) and Adafruit's product photograph; TI DRV8871 datasheet, DDA (the "
        "driver); 4UCON drawing 19963 (the terminal blocks)"
    ),
)

#: Adafruit's electret microphone amplifiers, MAX4466 (product 1063) and MAX9814 (1713), read
#: off Adafruit's own Eagle boards and seen from the FRONT, the face the microphone capsule
#: stands on and the pin names are printed on: the amplifier and its passives are on the
#: back, which this view does not show. Header along the top, the first pin -- the one on the
#: left with the header at the bottom, as the front's silkscreen reads -- at the right
#: (``pin_one``). The capsule is Kingstate's / CUI's 9.7 mm one, 4.5 mm tall; the MAX4466's
#: carries a black foam windshield, the MAX9814's is bare mesh.
ADAFRUIT_MAX4466_MODULE = ModuleArt(
    key="adafruit-max4466",
    board_colour=ADAFRUIT_BLACK,
    names=("max4466",),
    board=(13.97, 21.59),
    pins=3,
    frame="header",
    pin_one=1,
    parts=(
        ArtPart("capsule", 0.0, 3.3, 9.7, 9.7, 4.5, colour="#09090b"),
        ArtPart("hole", -4.83, 8.51, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
        ArtPart("hole", 4.83, 8.51, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
    ),
    source=(
        "Adafruit MAX4466 Eagle board, github adafruit/Adafruit-MAX4466-Electret-Mic-Amplifier-"
        "PCBs, 'Adafruit MAX4466 Mic Amp.brd', CC BY-SA (the board, the header, the capsule's "
        "place and the mounting holes) and Adafruit's product photographs 1063-06 and 1063-07 "
        "(the front: capsule with its foam, the three pins' names)"
    ),
)

ADAFRUIT_MAX9814_MODULE = ModuleArt(
    key="adafruit-max9814",
    board_colour=ADAFRUIT_BLUE,
    names=("max9814",),
    board=(14.1, 25.4),
    pins=5,
    frame="header",
    pin_one=1,
    parts=(
        ArtPart("capsule", -0.06, 5.46, 9.7, 9.7, 4.5),
        ArtPart("hole", -5.02, 10.67, 3.0, 3.0, 0.0, inset=0.4, colour=ART_COLOURS["brass"]),
        ArtPart("hole", 5.02, 10.67, 3.0, 3.0, 0.0, inset=0.4, colour=ART_COLOURS["brass"]),
    ),
    source=(
        "Adafruit MAX9814 Eagle board, github adafruit/Adafruit-MAX9814-AGC-Microphone-PCB (the "
        "board, the header, the capsule's place and the mounting holes) and Adafruit's product "
        "photographs 1713-04 (the front) and 1713-05 (the back)"
    ),
)

#: SparkFun's Hall-effect current sensor breakout (BOB-08882, retired), read off SparkFun's own
#: Eagle board and seen from above with the four-pin header along the top, GND at the right
#: (``pin_one``): the ACS712 stands in the middle of the board with its pin 1 towards VCC and
#: away from the header, and the two large holes the load goes through are at the far end,
#: one each side. The board has no other part. The chip's size is the SO-8's.
SPARKFUN_ACS712_MODULE = ModuleArt(
    key="sparkfun-acs712",
    board_colour=SPARKFUN_RED,
    names=("sparkfun acs712",),
    board=(15.24, 21.59),
    pins=4,
    frame="header",
    pin_one=1,
    parts=(
        ArtPart("soic8", 0.0, -0.64, 4.9, 6.0, 1.75, facing=-1, text="ACS712", across=1),
        ArtPart("hole", -3.81, 6.99, 6.2, 6.2, 0.0, inset=1.2, colour=ART_COLOURS["brass"]),
        ArtPart("hole", 3.81, 6.99, 6.2, 6.2, 0.0, inset=1.2, colour=ART_COLOURS["brass"]),
    ),
    source=(
        "SparkFun's Eagle board for the ACS712 breakout, github sparkfun/Hall-Effect_Current_"
        "Sensor_Breakout-ACS712 v1.1: the outline, the chip's place and pad 1, the header and "
        "the two load holes' places and sizes"
    ),
)

#: Adafruit's SCD-40 / SCD-41 CO2 sensor breakout, read off Adafruit's own Eagle board
#: (Adafruit-SCD-4x-PCB, 'Adafruit SCD-41') and seen from above with the five-pin header along
#: the top, VIN at the right (``pin_one``): the regulator and its two 10 uF capacitors beside
#: the header, the level shifter's BSS138 and the pull-up array at the left, a STEMMA QT socket
#: on each side, mouth outwards, the power LED, and the sensor in the middle, Sensirion's
#: 10.1 x 10.1 x 6.5 mm package, which is the tallest thing on it. The solder jumpers are not
#: drawn. The sizes of the rest are the packages'.
ADAFRUIT_SCD4X_MODULE = ModuleArt(
    key="adafruit-scd4x",
    board_colour=ADAFRUIT_BLACK,
    names=("scd-4", "scd4"),
    board=(25.4, 22.86),
    pins=5,
    frame="header",
    pin_one=1,
    # The regulator and the capacitors stand a few millimetres from the header, where a
    # name would be printed: the board is drawn as it is, and the names go over its parts.
    names_over_parts=True,
    parts=(
        ArtPart("shield", 0.0, 0.76, 10.1, 10.1, 6.5),
        ArtPart("sot23-5", 6.99, -5.21, 2.9, 2.8, 1.1, along_v=True, facing=1),
        ArtPart("chip-c", 10.54, -5.08, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 3.43, -5.46, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 5.97, -1.27, 1.6, 0.8, 0.45, along_v=True),
        ArtPart("chip-c", -0.25, -5.97, 1.6, 0.8, 0.45),
        ArtPart("chip-c", 3.56, 6.86, 2.0, 1.25, 0.85),
        ArtPart("sot363", -7.11, -4.83, 2.0, 2.1, 0.95),
        ArtPart("chip-r", -7.62, 4.83, 3.2, 1.6, 0.6),
        ArtPart("jst-sh", -10.16, 0.0, 4.25, 6.0, 2.9, facing=-1),
        ArtPart("jst-sh", 10.16, 0.0, 4.25, 6.0, 2.9, facing=1),
        ArtPart("led", 10.80, 4.32, 1.6, 0.8, 0.5, colour="#3fae49"),
        ArtPart("chip-r", 10.80, 5.59, 1.6, 0.8, 0.5),
        ArtPart("hole", -10.16, -8.89, 3.6, 3.6, 0.0, inset=0.3, colour=ART_COLOURS["brass"]),
        ArtPart("hole", 10.16, -8.89, 3.6, 3.6, 0.0, inset=0.3, colour=ART_COLOURS["brass"]),
        ArtPart("hole", -10.16, 8.89, 3.6, 3.6, 0.0, inset=0.3, colour=ART_COLOURS["brass"]),
        ArtPart("hole", 10.16, 8.89, 3.6, 3.6, 0.0, inset=0.3, colour=ART_COLOURS["brass"]),
    ),
    source=(
        "Adafruit SCD-41 Eagle board, github adafruit/Adafruit-SCD-4x-PCB, 'Adafruit SCD-41.brd', "
        "CC BY-SA (the board, the header, every top-side part's place, package and turn); "
        "Sensirion's SCD41 product page, 10.1 x 10.1 x 6.5 mm (the sensor); KiCad's JST "
        "SM04B-SRSS-TB model (the sockets)"
    ),
)

#: The STEMMA QT revision (two M2.5 holes a side, 25.4 x 20.32 mm): a STEMMA QT socket on
#: each side, mouth outwards, a resistor array for the pull-ups, and the green power LED.
ADAFRUIT_INA219_QT_MODULE = ModuleArt(
    key="adafruit-ina219-stemma-qt",
    board_colour=ADAFRUIT_BLACK,
    names=("ina219 stemma", "ina219 qt"),
    board=(25.4, 20.32),
    pins=6,
    frame="header",
    pin_one=1,
    parts=(
        ArtPart("sot23-8", 0.0, -3.17, 3.0, 3.0, 1.45, facing=-1, across=1),
        ArtPart("chip-c", 2.54, -3.05, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", 4.32, -3.05, 2.0, 1.25, 1.25, along_v=True),
        # A 4 x 0603 resistor array: its terminals down its two long sides.
        ArtPart("chip-r", -3.81, -3.17, 1.6, 3.2, 0.5),
        ArtPart("chip-r", 0.0, 1.02, 6.35, 3.2, 0.6),
        ArtPart("terminal", 0.05, 6.45, 7.0, 7.0, 8.5, along_v=True, facing=1, pitch=3.5),
        ArtPart("jst-sh", -10.10, 0.0, 4.25, 6.0, 2.9, facing=-1),
        ArtPart("jst-sh", 10.10, 0.0, 4.25, 6.0, 2.9, facing=1),
        ArtPart("led", 9.14, 4.19, 1.6, 0.8, 0.6, along_v=True, colour="#3fae49"),
        ArtPart("chip-r", 7.11, 3.56, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("hole", -10.16, -7.62, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
        ArtPart("hole", 10.16, -7.62, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
        ArtPart("hole", -10.16, 7.62, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
        ArtPart("hole", 10.16, 7.62, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
    ),
    source=(
        "Adafruit INA219 STEMMA QT Eagle board, github adafruit/Adafruit-INA219-Current-Sensor-"
        "PCB, Adafruit INA219 STEMMA QT.brd, CC BY-SA (the board, the header, every top-side "
        "part's place, package and turn); TI INA219 datasheet SBOS448G, DCN (the chip); 4UCON "
        "drawing 19963 (the terminal block); KiCad's JST SM04B-SRSS-TB model (the sockets)"
    ),
)

#: Adafruit's BME280 (product 2652) and BMP280 (2651) breakouts as first made: one board for
#: both, 17.78 x 19.05 mm, read off Adafruit's own Eagle boards (github
#: adafruit/Adafruit-BME280-Breakout-PCB and Adafruit-BMP280-Breakout-PCB, CC BY-SA) and seen
#: from above with the seven-pin header along the top, VIN at the right (``pin_one``): the
#: sensor's lidded package in the middle, the MIC5225 regulator (its three legs towards the
#: header), the two BSS138s of the level shifter, the 0805 parts, the 1N4148 with its band
#: as the board's C pad has it, and the two M2 holes on the far edge, gold-plated as
#: Adafruit's photograph of the BME280 shows them. Sizes are the packages': Bosch's 2.5 x 2.5
#: mm BME280 and 2.0 x 2.5 mm BMP280 on the one footprint.
_ADAFRUIT_BOSCH_PARTS = (
    ArtPart("sot23-5", 6.48, -0.51, 2.8, 2.9, 1.1, along_v=True, facing=1),
    ArtPart("chip-c", 6.48, 2.54, 2.0, 1.25, 1.25),
    ArtPart("chip-c", 6.60, -3.68, 2.0, 1.25, 1.25),
    ArtPart("sot23", 0.76, -3.18, 2.4, 2.9, 1.1, along_v=True, facing=-1),
    ArtPart("sot23", -5.21, -2.79, 2.4, 2.9, 1.1, along_v=True, facing=-1),
    ArtPart("chip-r", -5.21, 0.0, 2.0, 1.25, 0.5),
    ArtPart("chip-r", 0.76, -0.51, 2.0, 1.25, 0.5),
    ArtPart("chip-r", 3.68, 1.52, 2.0, 1.25, 0.5, along_v=True),
    ArtPart("chip-r", 3.68, -2.92, 2.0, 1.25, 0.5, along_v=True),
    ArtPart("chip-r", -2.03, -2.92, 2.0, 1.25, 0.5, along_v=True),
    ArtPart("sma", -4.83, 1.90, 2.5, 1.25, 1.0, facing=-1),
    ArtPart("hole", 6.35, 6.99, 3.0, 3.0, 0.0, inset=0.4, colour=ART_COLOURS["brass"]),
    ArtPart("hole", -6.35, 6.99, 3.0, 3.0, 0.0, inset=0.4, colour=ART_COLOURS["brass"]),
)
_ADAFRUIT_BOSCH_SOURCE = (
    "Adafruit BME280 and BMP280 Eagle boards, github adafruit/Adafruit-BME280-Breakout-PCB "
    "and Adafruit-BMP280-Breakout-PCB, CC BY-SA (the board, the header, every top-side part's "
    "place, package and turn); Adafruit's photograph of the BME280 (the colours); Bosch "
    "BME280 and BMP280 datasheets (the sensor)"
)
ADAFRUIT_BME280_MODULE = ModuleArt(
    key="adafruit-bme280",
    board_colour=ADAFRUIT_BLUE,
    names=("bme280",),
    excludes=("gy", "stemma", "qt"),
    board=(17.78, 19.05),
    pins=7,
    frame="header",
    pin_one=1,
    parts=(ArtPart("crystal", 0.0, 2.92, 2.5, 2.5, 0.93), *_ADAFRUIT_BOSCH_PARTS),
    source=_ADAFRUIT_BOSCH_SOURCE,
)
ADAFRUIT_BMP280_MODULE = ModuleArt(
    key="adafruit-bmp280",
    board_colour=ADAFRUIT_BLUE,
    names=("bmp280",),
    excludes=("gy", "stemma", "qt"),
    board=(17.78, 19.05),
    pins=7,
    frame="header",
    pin_one=1,
    parts=(ArtPart("crystal", 0.0, 2.92, 2.5, 2.0, 0.95), *_ADAFRUIT_BOSCH_PARTS),
    source=_ADAFRUIT_BOSCH_SOURCE,
)

#: The BMP280's STEMMA QT board (25.4 x 17.78 mm), read off its Eagle board in the same repo
#: and seen the same way: the sensor in the middle, the AP2112K regulator, the dual BSS138 in
#: its SOT-363, a resistor array for the pull-ups, a STEMMA QT socket on each side and the
#: green power LED. The LED stands 0.15 mm further from its socket than the board has it:
#: the two packages' outlines overlap by that much on Adafruit's board.
ADAFRUIT_BMP280_QT_MODULE = ModuleArt(
    key="adafruit-bmp280-stemma-qt",
    board_colour=ADAFRUIT_BLACK,
    names=("bmp280 stemma", "bmp280 qt"),
    board=(25.4, 17.78),
    pins=7,
    frame="header",
    pin_one=1,
    parts=(
        ArtPart("crystal", 0.0, 0.0, 2.5, 2.0, 0.95, along_v=True),
        ArtPart("sot23-5", 4.83, 0.0, 2.8, 2.9, 1.1, along_v=True, facing=1),
        ArtPart("chip-c", 4.95, -3.18, 2.0, 1.25, 1.25),
        ArtPart("chip-c", 4.57, 3.30, 2.0, 1.25, 1.25),
        ArtPart("chip-c", 2.54, 0.03, 1.6, 0.8, 0.8, along_v=True),
        # A 4 x 0603 resistor array: its terminals down its two long sides.
        ArtPart("chip-r", -4.45, 2.54, 1.6, 3.2, 0.5, along_v=True),
        ArtPart("sot363", -4.19, -1.40, 2.1, 2.0, 1.0),
        ArtPart("jst-sh", -10.10, 0.0, 4.25, 6.0, 2.9, facing=-1),
        ArtPart("jst-sh", 10.10, 0.0, 4.25, 6.0, 2.9, facing=1),
        ArtPart("led", 9.14, 3.83, 1.6, 0.8, 0.6, along_v=True, colour="#3fae49"),
        ArtPart("chip-r", 7.11, 3.56, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("chip-r", -0.05, -3.10, 1.6, 0.8, 0.5),
        ArtPart("chip-r", 1.27, 2.41, 1.6, 0.8, 0.5),
        ArtPart("sma", 0.0, 4.06, 2.5, 1.25, 1.0, facing=-1),
        ArtPart("hole", -10.16, 6.35, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
        ArtPart("hole", 10.16, 6.35, 3.2, 3.2, 0.0, inset=0.35, colour=ART_COLOURS["brass"]),
    ),
    source=(
        "Adafruit BMP280 STEMMA QT Eagle board, github adafruit/Adafruit-BMP280-Breakout-PCB, "
        "CC BY-SA (the board, the header, every top-side part's place, package and turn); "
        "Adafruit's photograph of it (the colours); Bosch BMP280 datasheet (the sensor); KiCad's "
        "JST SM04B-SRSS-TB model (the sockets)"
    ),
)

#: The ESP32 DevKit V1 clones' black, as the photograph its layout was measured on shows
#: it. An estimate, as every colour here is.
DEVKIT_V1_BLACK = "#1e1f23"

#: The 30-pin "ESP32 DevKit V1" -- DOIT's board as its many clones make it. Nobody publishes
#: its board, so the board and its big parts were measured on Edwiyanto's photograph of one
#: (Wikimedia Commons, "ESP32 Dev Board.jpg", CC BY-SA 4.0), rectified to the board's plane
#: on 25 of its 30 pads (each within 0.1 mm of its place once fitted; the other five sit
#: under printed names): the 51.1 x 28.0 mm board, the four 2.8 mm holes, the CP2102 in its
#: 5 mm QFN, the AMS1117 in its SOT-223 (legs towards the D23 row), the micro-USB socket and
#: BOOT and EN either side of it -- to about half a millimetre, and clones differ by more. The
#: WROOM-32 is the DevKitC's, which is exact: its antenna end flush with the board's, its can
#: where the photograph has it. The socket stands 0.9 mm past the board on that one and is
#: drawn flush, since nothing is drawn past the body DRC measures; the module stands 0.5 mm
#: further from the D23 row than its can measured, to keep clear of the holes the photograph
#: shows open. The small parts are not drawn: at this accuracy, and with every clone placing
#: them its own way, they would be invented. ``u`` runs towards the antenna, ``v`` from the
#: D23 row to the EN row.
ESP32_DEVKIT_V1_MODULE = ModuleArt(
    key="esp32-devkit-v1",
    board_colour=DEVKIT_V1_BLACK,
    names=("devkit v1", "doit"),
    excludes=("devkitc", "s2", "s3", "c3", "c6", "36", "38"),
    board=(51.1, 28.0),
    pins=30,
    frame="columns",
    landmark=("EN", 1, 1),
    # The WROOM's can stands close beside the D23 row, so the names there would be shrunk to
    # fit while the rest of that row prints full size: printed over the parts instead, the
    # whole row at one size, as the Pololu boards' are.
    names_over_parts=True,
    parts=(
        ArtPart("rf-module", 12.72, -1.3, 25.5, 18.0, 3.1, facing=1, antenna=6.94, inset=1.0,
                text="ESP32-WROOM-32"),
        ArtPart("qfn", -13.41, -6.4, 5.0, 5.0, 0.9, across=0),
        ArtPart("sot223", -13.61, 3.9, 7.0, 6.5, 1.7, along_v=True, facing=-1),
        ArtPart("usb", -23.0, -1.32, 5.0, 7.5, 2.6, facing=-1),
        ArtPart("button", -22.6, -8.8, 4.0, 2.6, 2.0),
        ArtPart("button", -22.81, 7.05, 4.0, 2.6, 2.0),
        ArtPart("hole", 22.87, 11.76, 2.84, 2.84, 0.0),
        ArtPart("hole", 22.87, -11.76, 2.84, 2.84, 0.0),
        ArtPart("hole", -22.87, 11.76, 2.84, 2.84, 0.0),
        ArtPart("hole", -22.87, -11.76, 2.84, 2.84, 0.0),
    ),
    source=(
        "Edwiyanto's photograph, Wikimedia Commons, CC BY-SA 4.0 "
        "(https://commons.wikimedia.org/wiki/File:ESP32_Dev_Board.jpg), "
        "rectified on its pads at about 33.9 px/mm (the board, the holes, the big parts, to "
        "about 0.5 mm); the "
        "DevKitC layout (the WROOM-32)"
    ),
)

#: The NodeMCU board's black, as the NodeMCU team's photograph of it shows. An estimate, as
#: every colour here is.
NODEMCU_BLACK = "#232428"

#: The NodeMCU DevKit 1.0 -- the 0.9 inch "Amica" board, the NodeMCU team's own design --
#: read off its published Gerbers and PCB print (github nodemcu/nodemcu-devkit-v1.0, MIT):
#: the 25.4 x 48.26 mm board, its two rows of fifteen 0.9 inch apart, the ESP-12E flush with
#: the top edge, and below it the NCP1117 in its SOT-223, the 100 uF tantalum (its + end
#: up, as the silkscreen's bar and the team's photograph have it), the two S8050s of the
#: auto-reset, the row of 0402 parts, the blue LED, the CP2102 (its pin 1 where the
#: silkscreen's dot is), the Schottky from USB (band down), the micro-USB socket at the
#: bottom edge and the RST and FLASH buttons beside it (C&K PTS 820). Sizes are the
#: packages'. ``u`` runs up the board towards the antenna, ``v`` from the D0 row to the A0
#: row. R10 is marked not fitted in the bill of materials and is not drawn.
#:
#: Only the 0.9 inch board is this one: LoLin's wider "V3", rows 1.1 inch apart, is a board
#: of another size that the fit turns away, and is named out besides.
NODEMCU_MODULE = ModuleArt(
    key="nodemcu-devkit-1.0",
    board_colour=NODEMCU_BLACK,
    names=("nodemcu",),
    excludes=("lolin", "v3", "esp32", "esp-32"),
    board=(48.26, 25.4),
    pins=30,
    frame="columns",
    landmark=("A0", 1, 1),
    # The board prints each name along its edge beside the pin, in a hand much smaller than
    # the tags here, and the ESP-12E and the 0402 columns stand where the tags would go:
    # printed over the parts, as the Pro Mini's are.
    names_over_parts=True,
    parts=(
        ArtPart("rf-module", 12.08, 0.0, 24.0, 16.0, 3.2, facing=1, antenna=7.75, inset=2.0,
                text="ESP8266MOD"),
        ArtPart("chip-c", 17.55, 9.04, 1.0, 0.5, 0.5),
        ArtPart("chip-r", 14.67, 9.04, 1.0, 0.5, 0.35),
        ArtPart("chip-r", 11.79, 9.04, 1.0, 0.5, 0.35),
        ArtPart("chip-r", 8.97, -9.04, 1.0, 0.5, 0.35),
        ArtPart("chip-r", 6.08, -9.04, 1.0, 0.5, 0.35),
        ArtPart("chip-r", 3.20, -9.04, 1.0, 0.5, 0.35),
        ArtPart("chip-c", -1.92, 4.24, 1.0, 0.5, 0.5, along_v=True),
        ArtPart("sot223", -4.22, -1.30, 7.0, 6.5, 1.7, along_v=True, facing=1),
        ArtPart("sma", -4.22, 7.34, 3.5, 2.8, 1.9, facing=1, colour=ART_COLOURS["tantalum"]),
        ArtPart("chip-c", -5.79, 4.24, 2.0, 1.25, 1.25),
        ArtPart("sot23", -5.89, -7.33, 2.4, 2.9, 1.1, facing=1),
        ArtPart("chip-r", -9.51, 8.28, 1.0, 0.5, 0.35),
        ArtPart("chip-r", -9.51, 6.62, 1.0, 0.5, 0.35),
        ArtPart("chip-r", -9.51, 4.97, 1.0, 0.5, 0.35),
        ArtPart("chip-r", -9.51, 1.66, 1.0, 0.5, 0.35),
        ArtPart("chip-c", -9.51, 0.0, 1.0, 0.5, 0.5),
        ArtPart("chip-c", -9.51, -1.66, 1.0, 0.5, 0.5),
        ArtPart("chip-r", -9.51, -3.31, 1.0, 0.5, 0.35),
        ArtPart("chip-r", -9.51, -4.97, 1.0, 0.5, 0.35),
        ArtPart("chip-r", -9.51, -6.62, 1.0, 0.5, 0.35),
        ArtPart("chip-r", -9.51, -8.28, 1.0, 0.5, 0.35),
        ArtPart("led", -12.12, 4.09, 1.6, 0.8, 0.6, along_v=True, colour="#4a7fd8"),
        ArtPart("sot23", -13.24, -7.33, 2.4, 2.9, 1.1, facing=-1),
        ArtPart("qfn", -14.45, -1.19, 5.0, 5.0, 0.9, facing=1, text="CP2102", across=-1),
        ArtPart("sma", -14.36, 7.80, 2.5, 1.25, 0.95, facing=-1),
        ArtPart("chip-c", -14.84, 4.92, 1.0, 0.5, 0.5),
        ArtPart("chip-c", -14.84, 3.28, 1.0, 0.5, 0.5),
        ArtPart("button", -21.09, 6.22, 3.9, 2.9, 2.5),
        ArtPart("button", -21.09, -6.22, 3.9, 2.9, 2.5),
        ArtPart("usb", -21.63, 0.0, 5.0, 7.5, 2.6, facing=-1),
        ArtPart("hole", 21.84, 10.41, 3.16, 3.16, 0.0),
        ArtPart("hole", 21.84, -10.41, 3.16, 3.16, 0.0),
        ArtPart("hole", -21.84, 10.41, 3.16, 3.16, 0.0),
        ArtPart("hole", -21.84, -10.41, 3.16, 3.16, 0.0),
    ),
    source=(
        "NodeMCU DevKit 1.0 Gerbers (V3) and PCB print, github nodemcu/nodemcu-devkit-v1.0, "
        "MIT (the board, both rows, the holes, every top-side part's place and turn, the "
        "tantalum's, the diode's and the CP2102's marks); its bill of materials (the "
        "packages); its photograph (the board's colour, the tantalum's band); C&K PTS 820 "
        "(the buttons)"
    ),
)

#: Pololu's DRV8833 dual motor driver carrier (item 2130) as its own top-view pinout picture
#: has it: the 10 uF capacitor and the 180 ohm resistor along the top, the reverse-
#: protection MOSFET and its diode under them, the QFN in the middle, small capacitors and
#: resistors down the left, and the four pads for the sense resistors, unfitted, at the
#: bottom (bare copper, not drawn). Positions measured on that picture at 19.7 px/mm against
#: the 0.4 inch between its header rows; sizes are the packages' own (TI's RTY outline for
#: the chip). The parts stand close to the pins on both sides, and Pololu prints the names
#: on the back, so they are printed over the parts. The chip's dot is in its corner towards
#: AOUT1 on the picture, its marking upside down.
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
        ArtPart("qfn", 0.8, 0.51, 4.0, 4.0, 0.8, text="8833", across=1),
        ArtPart("chip-c", 3.85, -2.96, 1.6, 0.8, 0.8),
        ArtPart("chip-r", 7.31, -2.65, 1.6, 0.8, 0.45),
    ),
    source=(
        "Pololu item 2130: the top-view pinout picture (positions) and the dimension diagram "
        "(the 0.5 x 0.8 inch board); TI DRV8833 RTY package (the 4 x 4 mm chip)"
    ),
)

#: The GY-521 MPU-6050 breakout everybody sells, as it is seen from above with its header
#: along the top -- INT at the left, VCC at the right (``pin_one``): the 3.3 V regulator (a
#: SOT-23-5, its three legs towards the header) by VCC, the MPU-6050 in the middle with its
#: pin-1 dot in its corner towards VCC and the header,
#: the yellow tantalum beside it with its + end towards INT, a column of 0603 parts each side
#: of the chip, the power LED by AD0 and the two 3 mm mounting holes on the far edge. Measured
#: on Nevit Dilmen's straight-down photograph of one (Wikimedia Commons, CC BY-SA 3.0), scaled
#: by its header -- seven pitches between VCC and INT, 106.5 px/mm -- so a position is good
#: to about 0.1 mm; that board is 20.7 x 15.5 mm, within the sellers' 20 to 21.2 by 15.5 to
#: 16.4. The sizes are the packages' own: InvenSense's 4 x 4 x 0.9 mm QFN-24, a SOT-23-5, an
#: EIA 3216 (A case) tantalum, 0603 resistors, capacitors and LED.
GY521_MODULE = ModuleArt(
    key="gy-521",
    names=("gy-521", "gy521", "gy 521"),
    board=(20.7, 15.5),
    pins=8,
    frame="header",
    pin_one=1,
    parts=(
        ArtPart("sot23-5", 8.88, -0.10, 2.8, 2.9, 1.1, along_v=True, facing=1),
        ArtPart("chip-c", 8.71, 2.32, 1.6, 0.8, 0.8),
        ArtPart("chip-c", 6.68, -1.22, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-r", 5.30, -1.22, 1.6, 0.8, 0.45, along_v=True),
        ArtPart("chip-c", 5.35, 2.29, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-r", 4.00, -1.22, 1.6, 0.8, 0.45, along_v=True),
        ArtPart("chip-c", 4.05, 2.29, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("qfn", 0.40, 0.58, 4.0, 4.0, 0.9, facing=1, text="MPU-6050", across=-1),
        ArtPart("sma", 0.43, 4.79, 3.2, 1.6, 1.6, facing=-1, colour=ART_COLOURS["tantalum"]),
        ArtPart("chip-c", -3.55, -1.25, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", -3.55, 2.31, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-r", -4.99, -1.22, 1.6, 0.8, 0.45, along_v=True),
        ArtPart("chip-r", -4.99, 2.31, 1.6, 0.8, 0.45, along_v=True),
        ArtPart("led", -6.37, -1.21, 1.6, 0.8, 0.6, along_v=True),
        ArtPart("hole", 8.00, 5.08, 3.0, 3.0, 0.0),
        ArtPart("hole", -7.45, 5.08, 3.0, 3.0, 0.0),
        ArtPart("silk", 0.38, 6.70, 6.0, 1.1, 0.0, text="ITG/MPU"),
    ),
    source=(
        "Nevit Dilmen's photograph of a GY-521, Wikimedia Commons, CC BY-SA 3.0 "
        "(https://commons.wikimedia.org/wiki/File:GY-521_MPU-6050_Module_3_Axis_Gyroscope_"
        "%2B_Accelerometer_0487.jpg), calibrated on its header at 106.5 px/mm, positions to "
        "about 0.1 mm; InvenSense MPU-6050 QFN-24 (the chip), SOT-23-5, EIA 3216, 0603"
    ),
)

#: The 0.96 inch 128 x 64 SSD1306 OLED on its four-pin I2C header, sold everywhere and the
#: same board under either order of names: the header centred along the top edge, the panel's
#: glass over nearly the whole of the board with its ledge towards the bottom, the flex circuit
#: folded round the bottom edge in the middle and a plated 2 mm hole in each corner. Measured
#: on Turbospok's photograph of one (Wikimedia Commons, CC BY-SA 4.0), all but straight down
#: and scaled by its header -- three pitches between its first and last pin, 22.95 px/mm --
#: so a position is good to about 0.2 mm; that board is 27.15 mm square, within the 27.3 x
#: 27.8 sellers give. The panel is Univision's UG-2864HSWEG01 drawing (``OLED_VIEW_MM``).
SSD1306_MODULE = ModuleArt(
    key="ssd1306-oled",
    names=("ssd1306",),
    board=(27.15, 27.15),
    pins=4,
    frame="header",
    parts=(
        ArtPart("hole", -11.6, -11.7, 3.5, 3.5, 0.0, inset=0.75, colour=ART_COLOURS["tin"]),
        ArtPart("hole", 11.6, -11.7, 3.5, 3.5, 0.0, inset=0.75, colour=ART_COLOURS["tin"]),
        ArtPart("hole", -11.6, 11.8, 3.5, 3.5, 0.0, inset=0.75, colour=ART_COLOURS["tin"]),
        ArtPart("hole", 11.6, 11.8, 3.5, 3.5, 0.0, inset=0.75, colour=ART_COLOURS["tin"]),
        ArtPart("oled", 0.0, 0.1, 19.26, 26.7, 1.45, along_v=True, facing=1),
        ArtPart("flex", 0.0, 11.6, 3.6, 13.5, 0.2, along_v=True),
    ),
    source=(
        "Turbospok's photograph of an SSD1306 module, Wikimedia Commons, CC BY-SA 4.0 "
        "(https://commons.wikimedia.org/wiki/File:MicroSD_card_connected_to_Arduino_nano_with_"
        "OLED_display.jpg), calibrated on its header at 22.95 px/mm, positions to about 0.2 mm; "
        "Univision UG-2864HSWEG01 (the panel)"
    ),
)

#: Ai-Thinker's ESP-01, the black board: the ESP8266EX in the middle, its SPI flash in an
#: SOP-8 beside it, the 26 MHz crystal between the chip and the antenna printed across the
#: far end, and a scatter of small parts. Ai-Thinker draws the board, the antenna's 6.7 mm
#: and the pins (ESP-01/07/12 manual V1.3, figure 2.1) and not the parts, so they were measured
#: on SparkFun's photograph of one (Wikimedia Commons, CC BY 2.0), oblique and RECTIFIED: a
#: homography from the four corners of its board onto the drawn 14.4 x 24.7 mm, which puts
#: the header where figure 2.1 has it to 0.1 mm. A part's top stands up to 1.75 mm off that
#: plane, so a position is good to about 0.3 mm. Drawn with its header along the top, the
#: way the header frame is written: pin 1, GND, at the right of the row nearer the chip.
#: On that photograph the ESP8266EX's dot is in its corner towards the antenna and GND, and
#: the flash's, its marking upside down, in its corner towards the antenna and the board's
#: edge.
ESP01_MODULE = ModuleArt(
    key="esp-01",
    # Black, as both are sold: the black of Espressif's devkits, which reads the same.
    board_colour=ESPRESSIF_BLACK,
    names=("esp-01", "esp01", "esp 01"),
    excludes=("esp-01s", "esp-01m", "esp-01f"),
    board=(14.4, 24.7),
    pins=8,
    frame="header",
    rows=2,
    pin_one=1,
    parts=(
        ArtPart("qfn", 1.95, -1.45, 5.0, 5.0, 0.85, text="ESP8266EX", across=1),
        ArtPart("soic8", -4.6, -1.6, 5.0, 7.9, 1.75, facing=-1, text="25Q80", across=1),
        ArtPart("crystal", -0.35, 3.8, 2.5, 2.0, 0.6),
        ArtPart("pcb-antenna", 2.0, 9.1, 8.8, 5.9, 0.0, pitch=1.05),
        ArtPart("chip-c", 6.5, -2.6, 2.0, 1.25, 0.85, along_v=True),
        ArtPart("chip-c", 2.6, 3.9, 1.6, 0.8, 0.8),
        ArtPart("chip-r", 2.7, 2.95, 1.6, 0.8, 0.45),
        ArtPart("chip-c", 5.05, 1.9, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", 6.15, 3.9, 1.0, 0.5, 0.5, along_v=True),
        ArtPart("chip-r", 5.2, 4.05, 1.0, 0.5, 0.35, along_v=True),
        ArtPart("chip-c", 4.1, 4.0, 1.0, 0.5, 0.5, along_v=True),
        ArtPart("chip-r", -3.0, 4.05, 1.6, 0.8, 0.45),
        ArtPart("chip-c", -3.5, 5.4, 1.0, 0.5, 0.5, along_v=True),
        ArtPart("chip-c", -4.9, 5.45, 1.0, 0.5, 0.5, along_v=True),
        ArtPart("chip-r", -6.3, 5.45, 1.0, 0.5, 0.35, along_v=True),
        ArtPart("chip-c", 6.2, -10.05, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("silk", 0.6, 6.35, 8.0, 0.9, 0.0, text="AI-Cloud inside"),
    ),
    source=(
        "Ai-Thinker ESP-01/07/12 Series Modules User's Manual V1.3, figure 2.1 (the board, "
        "the antenna's zone, the pins); SparkFun's photograph of one, Wikimedia Commons, CC BY "
        "2.0 (https://commons.wikimedia.org/wiki/File:ESP-01.jpg), rectified onto the drawn "
        "board at 40 px/mm, positions to about 0.3 mm; Espressif ESP8266EX QFN-32 (the chip)"
    ),
)

#: The nRF24L01+ board everybody sells, black, with its antenna printed on the far end: the
#: chip in the middle, the 16 MHz crystal in an HC-49/US can along the edge away from pin 1,
#: its 1 Mohm resistor between them, a column of capacitors along the header's edge and a
#: cluster of the radio's matching parts by the antenna's feed. KiCad's
#: RF_Module:nRF24L01_Breakout draws the board and the header and not the parts, so they were
#: measured on Dmcole's photograph of one (Wikimedia Commons, CC BY-SA 3.0), oblique and
#: RECTIFIED onto that board by a homography from its four corners -- pin 1's square pad lands
#: on KiCad's -- so a part on the board is good to about 0.5 mm and the crystal, which stands
#: 3.6 mm and leans in the photograph, to about 1 mm. Its height is YXC's HC-49US drawing:
#: 11.5 x 4.5 x 3.6 +- 0.2 mm, the most of which the id's top now says. The chip has no
#: pin-1 dot: on that photograph its top is too dark to read a marking off.
NRF24_MODULE = ModuleArt(
    key="nrf24l01",
    # Black, as both are sold: the black of Espressif's devkits, which reads the same.
    board_colour=ESPRESSIF_BLACK,
    names=("nrf24l01", "nrf24"),
    excludes=("pa+lna", "pa-lna", "pa lna", "lna"),
    board=(15.25, 29.0),
    pins=8,
    frame="header",
    rows=2,
    pin_one=1,
    parts=(
        ArtPart("qfn", 1.42, -2.9, 4.0, 4.0, 0.85, text="24L01+", across=0),
        ArtPart("hc49", -5.22, -3.25, 11.5, 4.5, 3.6, along_v=True),
        ArtPart("chip-r", -1.97, -2.2, 2.0, 1.25, 0.6, along_v=True),
        ArtPart("chip-c", 6.03, -7.2, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 6.03, -5.2, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 6.03, -3.2, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 6.03, -1.2, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 1.42, 0.9, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 3.33, 2.6, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 0.03, 2.6, 2.0, 1.25, 0.85),
        ArtPart("chip-c", 3.62, 4.5, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-r", 1.62, 4.5, 1.6, 0.8, 0.45, along_v=True),
        ArtPart("chip-c", -0.38, 4.5, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", -2.38, 4.5, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", 6.22, 5.1, 1.6, 0.8, 0.8),
        ArtPart("chip-c", -5.28, 4.3, 2.0, 1.25, 0.85, along_v=True),
        ArtPart("chip-c", -5.28, -10.7, 2.0, 1.25, 0.85, along_v=True),
        ArtPart("pcb-antenna", 0.22, 10.1, 7.8, 8.2, 0.0, pitch=1.7),
    ),
    source=(
        "KiCad RF_Module:nRF24L01_Breakout (the board, the header); Dmcole's photograph of "
        "one, Wikimedia Commons, CC BY-SA 3.0 (https://commons.wikimedia.org/wiki/File:"
        "NRF24l01_Nordic_Semiconductor_radio.JPG), rectified onto that board at 32 px/mm, "
        "positions to about 0.5 mm; YXC HC-49US (the crystal); Nordic nRF24L01+ QFN-20 (the chip)"
    ),
)

#: The HC-SR501 PIR motion sensor, as it is seen from above standing on its pins with its
#: header along the top -- VCC at the left (``pin_one``), OUT, GND: the Fresnel lens's square
#: foot over the middle of the board and its dome on that, an M2 hole at each end, and the
#: three solder joints of the trigger jumper underneath, at the right-hand end towards the
#: far edge. TruSens' HC-SR501 sheet (Rapid 74-1108) draws the 32 x 24 mm board, the screws
#: 28 mm apart and the lens 23 mm across, and its straight-down photograph of the underside,
#: at 34 px/mm, puts the header 2.9 mm in from its long edge with its middle pin 0.7 mm
#: towards GND, and the jumper in the corner the top-side photograph has its joints. The lens
#: was measured on Nowforever's photograph of one (Wikimedia Commons, CC BY-SA 4.0), oblique
#: and RECTIFIED by a homography from the board's four corners, at 25 px/mm: its foot 23.6 mm
#: square, centred, the holes 28.2 mm apart, the jumper's joints 2.5 mm apart. The camera
#: solved from those same corners, which puts the two holes back where the photograph has
#: them, finds the dome's top 16.3 mm above the board -- a 4.8 mm foot and the 23 mm dome --
#: good to about 1 mm, and 24.66 mm overall less the 1.6 mm board and the 7 mm parts under it
#: says the same. The lens leaves its header no room for names, which the module prints on
#: its underside, so they are printed over it (``names_over_parts``).
HC_SR501_MODULE = ModuleArt(
    key="hc-sr501",
    names=("hc-sr501", "hc sr501", "hcsr501"),
    board=(32.0, 24.0),
    pins=3,
    frame="header",
    pin_one=-1,
    names_over_parts=True,
    parts=(
        ArtPart("fresnel", 0.0, 0.0, 23.6, 23.6, 16.3),
        ArtPart("hole", -14.0, 0.0, 2.0, 2.0, 0.0),
        ArtPart("hole", 14.0, 0.0, 2.0, 2.0, 0.0),
        ArtPart("pads", 14.4, 7.85, 7.6, 1.8, 0.0, along_v=True),
    ),
    source=(
        "TruSens HC-SR501 PIR Motion Detector sheet, Rapid 74-1108 (the 32 x 24 mm board, its "
        "M2 screws 28 mm apart, the 23 mm lens; its underside photographed at 34 px/mm: the "
        "header's place, VCC OUT GND); Nowforever's photograph of one, Wikimedia Commons, CC "
        "BY-SA 4.0 (https://commons.wikimedia.org/wiki/File:PIR_sensor_for_arduino.jpg), "
        "rectified onto that board at 25 px/mm, positions to about 0.3 mm, and the lens's "
        "height from the camera its corners solve, to about 1 mm"
    ),
)

#: SparkFun's HX711 Load Cell Amplifier breakout, read off SparkFun's own Eagle board
#: (SparkFun_HX711_Breakout.brd, the 1.2 x 0.9 inch board): the SO-16 in the middle, its pin 1
#: at the AVDD end and the VCC-side row of pins, the PNP transistor and the 100 ohm, 20k,
#: 8.2k resistors and the 3.3 uH bead of the analogue supply in a column by the A+ and A- row,
#: the 10 uF 1210 and 0.1 uF 0603 decoupling along the AVDD end, the bare pads of the
#: second load cell's B+ and B- header, and four 3.3 mm mounting holes. ``u`` runs from the
#: AVDD end to the GND end of the rows, ``v`` from the AVDD row to the VDD row. The jumper
#: pad SJ2 and the logo are on the back and not drawn. Sizes are the packages': the 1210 is
#: the board's tDocu 3.2 x 2.6 mm, the SO-16 JEDEC MS-012's.
SPARKFUN_HX711_MODULE = ModuleArt(
    key="sparkfun-hx711",
    board_colour=SPARKFUN_RED,
    names=("hx711",),
    board=(22.86, 30.48),
    pins=10,
    frame="columns",
    landmark=("AVDD", -1, -1),
    names_over_parts=True,
    parts=(
        ArtPart("so16", 0.0, 0.0, 9.9, 6.0, 1.75, facing=-1, across=-1, text="HX711"),
        ArtPart("sot23", -5.40, -6.40, 2.9, 2.4, 1.1, along_v=True, facing=-1),
        ArtPart("chip-r", 6.98, -6.35, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("chip-r", 5.08, -6.35, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("chip-c", 3.17, -6.35, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-r", 1.27, -6.35, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("chip-r", -0.63, -6.35, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("chip-r", -2.54, -6.35, 2.0, 1.25, 0.9, along_v=True),
        ArtPart("chip-c", 6.98, 0.0, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-r", -2.54, 6.35, 1.6, 0.8, 0.5, along_v=True),
        ArtPart("chip-c", -4.45, 6.35, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", -8.89, -7.62, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", -8.89, -3.18, 3.2, 2.6, 1.7, along_v=True),
        ArtPart("chip-c", -8.89, 2.54, 1.6, 0.8, 0.8, along_v=True),
        ArtPart("chip-c", -8.89, 7.24, 3.2, 2.6, 1.7, along_v=True),
        ArtPart("pads", 1.27, 6.35, 5.08, 1.7, 0.0),
        ArtPart("hole", 8.89, -12.70, 3.3, 3.3, 0.0),
        ArtPart("hole", 8.89, 12.70, 3.3, 3.3, 0.0),
        ArtPart("hole", -8.89, -12.70, 3.3, 3.3, 0.0),
        ArtPart("hole", -8.89, 12.70, 3.3, 3.3, 0.0),
    ),
    source=(
        "SparkFun HX711 Load Cell Amplifier breakout Eagle board (every part's position and "
        "package; the SJ2 jumper and the logos are on the back); JEDEC MS-012 (the SO-16)"
    ),
)

MODULE_ARTS: tuple[ModuleArt, ...] = (
    LM2596_MODULE,
    SN65HVD230_MODULE,
    DEVKITC_MODULE,
    ESP32_DEVKIT_V1_MODULE,
    C3_DEVKITM_MODULE,
    S3_DEVKITC_MODULE,
    NANO_MODULE,
    PICO_MODULE,
    D1_MINI_MODULE,
    NODEMCU_MODULE,
    POLOLU_A4988_MODULE,
    POLOLU_DRV8825_MODULE,
    XIAO_ESP32C3_MODULE,
    XIAO_RP2040_MODULE,
    SPARKFUN_TB6612_MODULE,
    SPARKFUN_PRO_MINI_MODULE,
    SPARKFUN_PRO_MICRO_MODULE,
    ADAFRUIT_TCA9548A_MODULE,
    ADAFRUIT_ADS1115_MODULE,
    SPARKFUN_LOGIC_LEVEL_MODULE,
    ADAFRUIT_INA219_QT_MODULE,
    ADAFRUIT_INA219_MODULE,
    ADAFRUIT_SCD4X_MODULE,
    ADAFRUIT_DRV8871_MODULE,
    ADAFRUIT_MAX4466_MODULE,
    ADAFRUIT_MAX9814_MODULE,
    SPARKFUN_ACS712_MODULE,
    ADAFRUIT_BMP280_QT_MODULE,
    ADAFRUIT_BME280_MODULE,
    ADAFRUIT_BMP280_MODULE,
    POLOLU_DRV8833_MODULE,
    GY521_MODULE,
    SSD1306_MODULE,
    ESP01_MODULE,
    NRF24_MODULE,
    HC_SR501_MODULE,
    SPARKFUN_HX711_MODULE,
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


#: How each frame's layouts are written down, as the sign of the map from the art's
#: ``(u, v)`` to the footprint's ``(x, y)`` (y down the rows) that lays the drawing over its
#: footprint as the real board lies: a buck module's and a header breakout's ``u`` runs to
#: the right and ``v`` down the page (+1), a devkit's ``u`` down its length and ``v`` across
#: it to the right (-1). ``_frame`` turns a layout and never mirrors it.
DRAWN_HANDEDNESS: dict[str, float] = {"power": 1.0, "header": 1.0, "columns": -1.0}

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
        u_along_x = max(xs) - min(xs) >= max(ys) - min(ys)
        if len(ys if u_along_x else xs) != art.rows:
            return None  # a layout for one row of pins is not one for two, nor two for one
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
        # Pin 1 is at the footprint's -x (or -y) end of its row, wherever the layout has it.
        sign_u = -float(art.pin_one)
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
    # A turn, never a mirror: flipping one axis alone draws the board's mirror image, which
    # is no board anybody makes -- and a footprint that asks for one has its board on the
    # wrong side of its pins, which is what the GY-521's had. The block claims nothing.
    if sign_u * sign_v * (1.0 if u_along_x else -1.0) != DRAWN_HANDEDNESS[art.frame]:
        return None
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
        # What is across the part is along the layout's other axis, and turns with it: a
        # layout turned half round puts pin 1 on the other side as well as at the other end.
        across = (part.across or 0) * int(sign_v if own_u else sign_u)
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
                pitch=part.pitch,
                across=across,
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


# -- a board that stands on its edge -----------------------------------------------------
#
# A module whose board stands up off this one on a right-angle header -- the HC-SR04, its
# transducers looking out across the board -- is not a module lying on a seat: its footprint
# is the box it fills (a ``generic-box``), and what is drawn in it is the board standing at
# the back of that box with its parts on its front face. The layout is in the BOARD's frame:
# ``u`` along it from its middle, ``w`` up it from its bottom edge, and a part's ``depth``
# out of its front face. ``fit_standing_board`` puts it in the footprint's frame -- x along
# the pins, y the way the front faces, z up from this board -- which both views draw from.

#: What stands on a standing board's front face.
#:  * ``transducer`` -- an ultrasonic transducer: an aluminium can, its axis out of the face,
#:                      its mesh at the front. ``length`` and ``height`` are its diameter.
#:  * ``crystal``    -- an HC-49 can lying on the face, its long side along the board.
#:  * ``hole``       -- a mounting hole through the board, ``length`` across.
StandingKind = Literal["transducer", "crystal", "hole"]


@dataclass(frozen=True, slots=True)
class StandingPart:
    """One part on a standing board's front face, in the board's own frame."""

    kind: StandingKind
    u: float
    w: float
    length: float
    height: float
    depth: float


@dataclass(frozen=True, slots=True)
class StandingBoard:
    """A module that stands on its edge: how to recognise it and what is on it."""

    key: str
    names: tuple[str, ...]
    #: The board, along it and up it, in millimetres.
    board: tuple[float, float]
    pins: int
    #: From the pin row to the board's back face: half the right-angle header's plastic,
    #: which stands against the back of the board with the pins down through it.
    behind: float
    thickness: float
    #: How far the board's bottom edge stands off this board.
    standoff: float
    #: The right-angle header's plastic, along the row, through it and up it.
    header: tuple[float, float, float]
    board_colour: str
    parts: tuple[StandingPart, ...]
    source: str


@dataclass(frozen=True, slots=True)
class PlacedStandingPart:
    """A standing board's part in the footprint's frame: its centre along x, how far out it
    reaches along y (``y0`` at the board's face to ``y1``), its centre up z, and its size
    along x and up z."""

    kind: StandingKind
    x: float
    y0: float
    y1: float
    z: float
    length: float
    height: float


@dataclass(frozen=True, slots=True)
class PlacedStanding:
    """A standing board in the footprint's frame (x along the row, y down the rows -- the
    way its front faces -- and z up from this board)."""

    #: The board: ``(x0, x1, y0, y1, z0, z1)``, ``y0`` its back face.
    board: tuple[float, float, float, float, float, float]
    #: The header's plastic, the same way round.
    header: tuple[float, float, float, float, float, float]
    parts: tuple[PlacedStandingPart, ...]
    board_colour: str
    #: Where the pins are along x, on the row at the header's middle.
    pins: tuple[float, ...] = ()


#: The HC-SR04 as Nevit Dilmen's straight-on photograph of its front has it (Wikimedia
#: Commons, CC BY-SA 3.0), scaled by its header -- 2.54 mm between pins, 27.8 px/mm -- which
#: makes its board 44.9 x 20.4 mm against ElecFreaks' 45 x 20: the transmitter left and the
#: receiver right, each a 16 mm can whose centre stands 10.6 mm up the board, 27.8 mm apart
#: (the cans' fronts stand 12 mm nearer the camera than the board, so their spacing is read
#: 4 % small of the photograph's, to about 0.5 mm), the 4 MHz crystal lying along the top edge
#: between them, and a mounting hole in each corner. Its header is a right-angle one, its
#: plastic against the BACK of the board (Suyash Dwivedi's photograph of the back), so the
#: pins stand 1.2 mm behind the board and the cans 12 mm out in front of it -- which is
#: where the footprint's box now stands too. How high the board's bottom edge stands off
#: this board is NOT measured: 2.5 mm, the rest of the 22.5 mm the footprint gives it.
HC_SR04_BOARD = StandingBoard(
    key="hc-sr04",
    names=("hc-sr04", "hcsr04", "hc sr04"),
    board=(45.0, 20.0),
    pins=4,
    behind=1.2,
    thickness=1.6,
    standoff=2.5,
    header=(10.16, 2.4, 2.5),
    board_colour="#1f6e86",
    parts=(
        StandingPart("transducer", -13.9, 10.6, 16.0, 16.0, 12.0),
        StandingPart("transducer", 13.9, 10.6, 16.0, 16.0, 12.0),
        StandingPart("crystal", -0.6, 17.75, 9.1, 3.9, 3.6),
        StandingPart("hole", -21.3, 1.3, 1.8, 1.8, 0.0),
        StandingPart("hole", 21.3, 1.3, 1.8, 1.8, 0.0),
        StandingPart("hole", -21.3, 18.6, 1.8, 1.8, 0.0),
        StandingPart("hole", 21.3, 18.6, 1.8, 1.8, 0.0),
    ),
    source=(
        "Nevit Dilmen's photograph of an HC-SR04's front, Wikimedia Commons, CC BY-SA 3.0 "
        "(https://commons.wikimedia.org/wiki/File:HC_SR04_Ultrasonic_sensor_1480322_3_4_HDR_"
        "Enhancer.jpg), calibrated on its header at 27.8 px/mm, positions to about 0.5 mm; "
        "Suyash Dwivedi's of its back (the header on the back); ElecFreaks' user guide (the "
        "45 x 20 mm board); Handsontec's (the cans standing 15 mm off it)"
    ),
)

STANDING_BOARDS: tuple[StandingBoard, ...] = (HC_SR04_BOARD,)


def recognise_standing_board(value: str) -> StandingBoard | None:
    """The standing board a part's value names, or ``None``."""
    text = value.casefold()
    return next((art for art in STANDING_BOARDS if any(name in text for name in art.names)), None)


def fit_standing_board(
    footprint: Footprint, component: ComponentInstance, pitch: float
) -> PlacedStanding | None:
    """A standing board in this footprint's box -- or ``None`` to draw the box: not a box, a
    value nobody wrote a layout for, pins not in one row along x, a box the board does not
    fit, or one facing the other way (whose front, seen from in front of it, would have pin
    1 on the right: the board's mirror image, which nobody makes)."""
    if footprint.body.archetype != "generic-box":
        return None
    art = recognise_standing_board(component.value)
    if art is None or len(footprint.pins) != art.pins:
        return None
    if len({pin.d_row for pin in footprint.pins}) != 1:
        return None
    dims = footprint.body.dims
    length = float(dims.get("width", 0.0))
    if length <= 0 or abs(length / art.board[0] - 1) > SIZE_TOLERANCE:
        return None
    offset = float(dims.get("offsetY", 0.0))
    if offset <= 0:
        return None
    # Never past the box DRC measures: it has to reach from the header's plastic behind the
    # pins to the front of the furthest part. A box the board does not fit -- the HC-SR04's
    # old one, 3.9 mm short in front -- keeps the plain box.
    reach = art.behind + art.thickness + max(part.depth for part in art.parts)
    depth = float(dims.get("depth", 0.0))
    tolerance = 0.06
    if offset + depth / 2 < reach - tolerance or offset - depth / 2 > -art.header[1] / 2 + tolerance:
        return None
    xs = [pin.d_col * pitch for pin in footprint.pins]
    middle = (min(xs) + max(xs)) / 2
    row = footprint.pins[0].d_row * pitch
    back = row + art.behind
    front = back + art.thickness
    half = length / 2
    header_x, header_y, header_z = art.header
    placed = tuple(
        PlacedStandingPart(
            kind=part.kind,
            x=middle + part.u * length / art.board[0],
            y0=front,
            y1=front + part.depth,
            z=art.standoff + part.w,
            length=part.length,
            height=part.height,
        )
        for part in art.parts
    )
    return PlacedStanding(
        board=(middle - half, middle + half, back, front, art.standoff, art.standoff + art.board[1]),
        header=(
            middle - header_x / 2, middle + header_x / 2,
            row - header_y / 2, row + header_y / 2,
            art.standoff, art.standoff + header_z,
        ),
        parts=placed,
        board_colour=art.board_colour,
        pins=tuple(xs),
    )


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
