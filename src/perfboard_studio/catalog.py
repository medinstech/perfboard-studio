"""Real parts by the name on the bag: a package, what its leads are called, what it is.

THE GAP THIS CLOSES. The library is sixty-one PACKAGES, and a package is not a part: a TO-92
is a BC547 or a 2N7000 or a 78L05, and which leg is the base -- the one fact that decides
whether the board works -- is a fact about the part, not the package. Since parts learned
to carry their own pin names and symbol, every one of them could be described properly,
but only by somebody who already knew the pinout and typed it in, part by part. The first
real board laid out with this tool had its BC547s, its P-FET and its CAN breakout described
that way in a script; the next person to want a BC547 would have had to look it all up
again.

So this is a list of the parts a perfboard is actually built from, each one already
described: the package it comes in, what its datasheet calls each lead, the symbol it is
drawn as, the value it goes on the bill as, and the letter its reference takes.

WHAT IT IS NOT: a library the document depends on. Choosing ``bc547`` places an ordinary
component -- footprint ``to92``, value ``BC547``, pin names ``C B E``, symbol ``npn`` --
exactly as if all of that had been typed in. Nothing in the document refers back to this
file, so a board opens the same on a machine whose catalog has never heard of the part, and
an entry corrected here never silently changes a board already drawn. That is the same
argument that made a custom footprint an id carrying its own parameters rather than an
entry in a user library (``footprints.GENERATED_ID_GRAMMAR``).

HOW MUCH TO TRUST AN ENTRY. Every pinout is a datasheet's, and ``source`` says whose.
Pins 1-2-3 of a TO-92 are left to right with the flat face towards you and the legs down;
of a TO-220, left to right looking at the printed face with the tab behind -- the order the
footprints number them in, and KiCad's. A module's dimensions are measured from a drawing
(``source``), and anything that varies between suppliers or could not be measured -- a
clone's board, the height of what is on it -- is said in ``check``, which the interface
shows beside the part. A part whose pinout differs between makers is not in here at all,
or is in once per pinout with the order in its name: the two OLEDs, the RGB LEDs.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .model import PartSymbol, PerfDocument, PinNames

#: What a part is, for grouping a list of them. Engine text; the interface translates the
#: group headings itself.
CatalogCategory = Literal[
    "transistor",
    "mosfet",
    "regulator",
    "power",
    "diode",
    "led",
    "protection",
    "passive",
    "sensor",
    "display",
    "ic",
    "switch",
    "relay",
    "connector",
    "sound",
    "module",
]

#: The order the groups are shown in: the things a board is mostly made of first.
CATEGORY_ORDER: tuple[CatalogCategory, ...] = (
    "transistor",
    "mosfet",
    "regulator",
    # Beside the regulators: how the supply gets onto the board in the first place, which a
    # first circuit drawn from nothing has no other way to find.
    "power",
    "diode",
    "led",
    "protection",
    "passive",
    "sensor",
    "display",
    "ic",
    "switch",
    "relay",
    "connector",
    "sound",
    "module",
)


@dataclass(frozen=True, slots=True)
class CatalogPart:
    """One real part, described completely enough to place."""

    #: Lower-case, stable: what an agent and a test ask for (``bc547``).
    id: str
    #: What is printed on it, and what a person searches for.
    name: str
    category: CatalogCategory
    #: A registry id or a generated one (``mod-...``, ``c-disc-...``); either way the
    #: document stores it and nothing else from here.
    footprint_id: str
    #: One line: what it is and the numbers that choose it.
    summary: str
    pin_names: PinNames = ()
    symbol: PartSymbol | None = None
    #: What goes on the bill. Empty means the name.
    value: str = ""
    #: The reference letter, when the package's own would be wrong -- a 7805 is a TO-220
    #: and it is not a transistor. Empty means the package's.
    ref_prefix: str = ""
    #: Where the pinout and any measurement come from.
    source: str = ""
    #: What to check on the part in hand, when something about it varies. Shown to the user.
    check: str = ""
    #: Words somebody looks for it by that its name and summary do not say: "stepper" for
    #: the chip a 28BYJ-48 hangs off. Searched, never shown.
    aliases: tuple[str, ...] = ()

    @property
    def placed_value(self) -> str:
        return self.value or self.name

    @property
    def reference_prefix(self) -> str:
        """The letter its reference takes: its own, or its kind's."""
        return self.ref_prefix or _PREFIX_BY_CATEGORY.get(self.category, "U")


#: A category's reference letter, where the package's would be wrong or there is none.
_PREFIX_BY_CATEGORY: dict[str, str] = {
    "transistor": "Q",
    "mosfet": "Q",
    "diode": "D",
    "led": "D",
    "protection": "F",
    "power": "J",
    "relay": "K",
    "connector": "J",
    "sound": "BZ",
}


def free_reference(document: PerfDocument, prefix: str) -> str:
    """The first unused reference with this prefix, across the board AND the design --
    a reference is unique across both lists (``commands.assert_ref_free``)."""
    used = {component.ref for component in document.components}
    used |= {part.ref for part in document.parts}
    index = 1
    while f"{prefix}{index}" in used:
        index += 1
    return f"{prefix}{index}"


def _legs(*names: str) -> PinNames:
    """Pin names in pin order: ``_legs("C", "B", "E")`` is 1=C, 2=B, 3=E."""
    return tuple((str(index + 1), name) for index, name in enumerate(names))


def _two_columns(left: tuple[str, ...], right: tuple[str, ...]) -> PinNames:
    """A module's names, from its two columns read top to bottom, in the numbering
    ``footprints.module_footprint`` gives a 2 x N module: row by row, left then right."""
    if len(left) != len(right):
        raise ValueError("both columns of a module have the same number of pins")
    pairs: list[tuple[str, str]] = []
    for row, (lhs, rhs) in enumerate(zip(left, right, strict=True)):
        pairs.append((str(2 * row + 1), lhs))
        pairs.append((str(2 * row + 2), rhs))
    return tuple(pairs)


_TO92_ORDER = "TO-92 legs 1-2-3 left to right, flat face towards you, legs down"
_TO220_ORDER = "TO-220 legs 1-2-3 left to right, printed face towards you, tab behind"
_CHECK_LEGS = "Check the legs against the datasheet of the part you have before soldering."
_DIODE = _legs("K", "A")  # pin 1 is the banded end: the registry's and KiCad's convention
#: Four two-input gates and six inverters, as TI names a 74HC's pins.
_QUAD_GATE = _legs("1A", "1B", "1Y", "2A", "2B", "2Y", "GND",
                   "3Y", "3A", "3B", "4Y", "4A", "4B", "VCC")
_HEX_INVERTER = _legs("1A", "1Y", "2A", "2Y", "3A", "3Y", "GND",
                      "4Y", "4A", "5Y", "5A", "6Y", "6A", "VCC")
#: The 4000 series' quad gate is pinned differently from the 74HC's: its second and fourth
#: outputs are on the inside, pins 4 and 11.
_QUAD_GATE_4000 = _legs("1A", "1B", "1Y", "2Y", "2A", "2B", "VSS",
                        "3A", "3B", "3Y", "4Y", "4A", "4B", "VDD")
_CD4000_NAMES = (
    "TI's letters A to M renamed gate by gate: 1 and 2 drive 3, 5 and 6 drive 4, 8 and 9 "
    "drive 10, 12 and 13 drive 11"
)
_UNUSED_INPUTS = (
    "Tie every unused input to the supply or to ground: a CMOS input left open picks up "
    "noise, draws current and switches at random."
)
_LED_CHECK = (
    "The longer leg is the anode; the flat on the rim is on the cathode's side. It needs a "
    "resistor in series: about 330 ohm from 5 V."
)
_RGB_CHECK = (
    "Makers do not agree where green and blue go, so before soldering touch a 3 V coin cell "
    "across the longest leg and each of the others (+ to the longest on a common anode, - "
    "on a common cathode) and see which colour lights. Each colour needs its own resistor. "
    "The legs leave the lens 1.27 mm apart: fan them out to the four holes."
)

# -- modules --------------------------------------------------------------------------
#
# Each is laid out as it is usually drawn: its two pin columns running DOWN the board, the
# USB end or the antenna at the top, pin 1 at the top left. Positions and board outlines
# are KiCad's own footprint for the module (Module.pretty, RF_Module.pretty) except where a
# source says otherwise; names are KiCad's symbol for it, with its overbar markup dropped.
# The seat is a female header (8.5 mm): a devkit is fitted so it can come out again.

_DEVKITC_LEFT = (
    "3V3", "EN", "VP", "VN", "IO34", "IO35", "IO32", "IO33", "IO25", "IO26",
    "IO27", "IO14", "IO12", "GND", "IO13", "D2", "D3", "CMD", "5V",
)  # fmt: skip
_DEVKITC_RIGHT = (
    "GND", "IO23", "IO22", "TX", "RX", "IO21", "GND", "IO19", "IO18", "IO5",
    "IO17", "IO16", "IO4", "IO0", "IO2", "IO15", "D1", "D0", "CLK",
)  # fmt: skip
_NANO_LEFT = (
    "D1/TX", "D0/RX", "RESET", "GND", "D2", "D3", "D4", "D5", "D6", "D7",
    "D8", "D9", "D10", "D11", "D12",
)  # fmt: skip
_NANO_RIGHT = (
    "VIN", "GND", "RESET", "+5V", "A7", "A6", "A5", "A4", "A3", "A2",
    "A1", "A0", "AREF", "3V3", "D13",
)  # fmt: skip
_PICO_LEFT = (
    "GP0", "GP1", "GND", "GP2", "GP3", "GP4", "GP5", "GND", "GP6", "GP7",
    "GP8", "GP9", "GND", "GP10", "GP11", "GP12", "GP13", "GND", "GP14", "GP15",
)  # fmt: skip
_PICO_RIGHT = (
    "VBUS", "VSYS", "GND", "3V3_EN", "3V3", "ADC_VREF", "GP28", "AGND", "GP27", "GP26",
    "RUN", "GP22", "GND", "GP21", "GP20", "GP19", "GP18", "GND", "GP17", "GP16",
)  # fmt: skip
_D1_MINI_LEFT = ("RST", "A0", "D0", "SCK/D5", "MISO/D6", "MOSI/D7", "CS/D8", "3V3")
_D1_MINI_RIGHT = ("TX", "RX", "SCL/D1", "SDA/D2", "D3", "D4", "GND", "5V")
_C3_DEVKITM_LEFT = (
    "GND", "3V3", "3V3", "IO2", "IO3", "GND", "RST", "GND", "IO0", "IO1",
    "IO10", "GND", "5V", "5V", "GND",
)  # fmt: skip
_C3_DEVKITM_RIGHT = (
    "GND", "TX", "RX", "GND", "IO9", "IO8", "GND", "IO7", "IO6", "IO5",
    "IO4", "GND", "IO18", "IO19", "GND",
)  # fmt: skip

# Pololu's own top view: the logic pins down the left, the motor and supply pins down the
# right with VMOT at the top -- KiCad's Pololu_Breakout footprint is the same board turned
# half round. Names are KiCad's Driver_Motor:Pololu_Breakout_A4988, overbars dropped.
_POLOLU_A4988_LEFT = ("ENABLE", "MS1", "MS2", "MS3", "RESET", "SLEEP", "STEP", "DIR")
_POLOLU_A4988_RIGHT = ("VMOT", "GND", "2B", "2A", "1A", "1B", "VDD", "GND")
# The same board with the DRV8825 on it, named from Driver_Motor:Pololu_Breakout_DRV8825.
_POLOLU_DRV8825_LEFT = ("EN", "M0", "M1", "M2", "RST", "SLP", "STEP", "DIR")
_POLOLU_DRV8825_RIGHT = ("VMOT", "GND", "B2", "B1", "A1", "A2", "FLT", "GND")
# The USB-C end at the top, as Seeed's own pinout draws it; read off the nets of the two
# header rows on Seeed's KiCad board, functions from its pin map.
_XIAO_LEFT = ("D0", "D1", "D2", "D3", "D4/SDA", "D5/SCL", "D6/TX")
_XIAO_RIGHT = ("5V", "GND", "3V3", "D10/MOSI", "D9/MISO", "D8/SCK", "D7/RX")
# SparkFun's dual TB6612FNG board, its silkscreen upright: the motor side down the left,
# the logic down the right, read off the nets of the two header rows on its Eagle board.
_TB6612_LEFT = ("VM", "VCC", "GND", "A01", "A02", "B02", "B01", "GND")
_TB6612_RIGHT = ("PWMA", "AIN2", "AIN1", "STBY", "BIN1", "BIN2", "PWMB", "GND")
# Pololu's DRV8833 carrier from the top, as its pinout picture has it; the board prints the
# names on its back, with SLP and FLT for nSLEEP and nFAULT.
_DRV8833_LEFT = ("GND", "VMM", "BIN1", "BIN2", "AIN2", "AIN1", "SLP", "FLT")
_DRV8833_RIGHT = ("GND", "VIN", "BOUT1", "BOUT2", "AOUT2", "AOUT1", "AISEN", "BISEN")

_SWITCH_LEGS = (
    "The two legs on one side are the switched pair; the two straight across are one "
    "strip. A meter on continuity says which: across reads shut before the button is "
    "pressed."
)

#: The Songle SRD relays: one package for every coil voltage, numbered as KiCad's SANYOU SRD
#: footprint (``footprints.srd_relay_footprint``).
_SRD_LEGS = _legs("COM", "COIL", "NO", "NC", "COIL")
_SRD_SOURCE = (
    "Songle SRD datasheet: coil data, contact rating, the 19.1 x 15.5 x 15.3 mm body, its "
    "drilling and wiring diagram; numbered as KiCad Relay_SPDT_SANYOU_SRD_Series_Form_C"
)
_SRD_CHECK = (
    "Its legs are off the 2.54 mm grid and bend to the holes drawn: about 0.5 mm for COM, "
    "0.9 mm for a coil leg, 1.1 mm for a contact leg. With the coil off, NC reads shut to "
    "COM: check that with a meter before soldering."
)

_MODULE_TOP = (
    "The height of what is on the board is an estimate, and so is its colour; the pins, "
    "the rows and the board outline are measured."
)

#: The 0.96 inch 128 x 64 OLED on its four-pin I2C board, which is sold with its supply pins
#: in either order -- and swapped supply pins kill it. Two entries named by the order printed
#: on the board, so the one chosen is the one in hand. A box, not a module: nobody publishes
#: a drawing of the board, so nothing is drawn on it but the room it takes, seated in a
#: female header: the four pins along one edge, 2 mm in from it.
_OLED_FOOTPRINT = "box-4x1-p1-r1-27.3x27.8x12.2-o0x11.9"
_OLED_SOURCE = (
    "The four names as the board prints them; the 27.3 x 27.8 mm board as sellers list it; "
    "the controller, Solomon Systech's SSD1306"
)
_OLED_CHECK = (
    "Read the four names printed on yours: this board is sold with VCC and GND either way "
    "round, and the wrong way round kills it. Choose the entry with your order. Where the "
    "pins sit on the board and how tall it stands in its header are estimates."
)

#: Kingbright's 0.56 inch 7-segment displays: a block over two rows of pins 0.6 inch apart,
#: numbered as a DIP is (``-ccw``) and centred on the block, as KiCad's
#: Display_7Segment:CA56-12EWA has the four-digit one.
_DIGIT_FOOTPRINT = "box-2x5-p6-r1-19.05x12.7x8-ccw"
_FOUR_DIGITS_FOOTPRINT = "box-2x6-p6-r1-19x50.3x8.1-ccw"
_FOUR_DIGITS_PINS = (
    "segments a 11, b 7, c 4, d 2, e 1, f 10, g 5, DP 3; digits 12, 9, 8, 6 from the left; "
    "50.3 x 19 x 8.1 mm, the rows 15.24 mm apart"
)
_DIGIT_ALIASES = ("7-segment", "seven segment", "digit", "gösterge")
_DIGIT_CHECK = (
    "Pin 1 is at the bottom left with the digit upright and its decimal point at the bottom "
    "right. Each segment needs its own resistor. Unbranded 0.56 inch digits are usually "
    "pinned the same, but not always: light one segment with a 3 V coin cell before soldering."
)
_FOUR_DIGITS_CHECK = (
    "The digits share their segment pins, so they are lit one at a time, faster than the eye "
    "can follow: a resistor on each segment pin, and each digit's DIG pin switched in turn, "
    "through a transistor, since one digit carries all its segments' current. Unbranded "
    "four-digit displays are usually pinned the same, but not always: light one segment with "
    "a 3 V coin cell before soldering."
)

#: Off the board: what the leads of a battery or a panel jack are soldered into, one pad
#: each (``footprints.off_board_mount``). Every word a beginner looks for power by.
_POWER_WORDS = ("power", "supply", "battery", "pil", "besleme")


CATALOG: tuple[CatalogPart, ...] = (
    # -- bipolar transistors ----------------------------------------------------------
    CatalogPart("bc547", "BC547", "transistor", "to92", "NPN, 45 V, 100 mA, general purpose",
                _legs("C", "B", "E"), "npn", source=f"onsemi BC546/D; {_TO92_ORDER}",
                check=_CHECK_LEGS),
    CatalogPart("bc548", "BC548", "transistor", "to92", "NPN, 30 V, 100 mA, general purpose",
                _legs("C", "B", "E"), "npn", source=f"onsemi BC546/D; {_TO92_ORDER}",
                check=_CHECK_LEGS),
    CatalogPart("bc557", "BC557", "transistor", "to92", "PNP, 45 V, 100 mA, general purpose",
                _legs("C", "B", "E"), "pnp", source=f"onsemi BC556/D; {_TO92_ORDER}",
                check=_CHECK_LEGS),
    CatalogPart("bc558", "BC558", "transistor", "to92", "PNP, 30 V, 100 mA, general purpose",
                _legs("C", "B", "E"), "pnp", source=f"onsemi BC556/D; {_TO92_ORDER}",
                check=_CHECK_LEGS),
    CatalogPart("bc337", "BC337", "transistor", "to92", "NPN, 45 V, 800 mA, switching",
                _legs("C", "B", "E"), "npn", source=f"onsemi BC337/D; {_TO92_ORDER}",
                check=_CHECK_LEGS),
    CatalogPart("bc327", "BC327", "transistor", "to92", "PNP, 45 V, 800 mA, switching",
                _legs("C", "B", "E"), "pnp", source=f"onsemi BC327/D; {_TO92_ORDER}",
                check=_CHECK_LEGS),
    CatalogPart("2n2222a", "2N2222A", "transistor", "to92",
                "NPN, 40 V, 600 mA, switching (plastic TO-92, sold as PN2222A)",
                _legs("E", "B", "C"), "npn", source=f"onsemi P2N2222A/D; {_TO92_ORDER}",
                check="The metal-can (TO-18) 2N2222 is pinned differently. " + _CHECK_LEGS),
    CatalogPart("2n3904", "2N3904", "transistor", "to92", "NPN, 40 V, 200 mA, general purpose",
                _legs("E", "B", "C"), "npn", source=f"onsemi 2N3903/D; {_TO92_ORDER}",
                check=_CHECK_LEGS),
    CatalogPart("2n3906", "2N3906", "transistor", "to92", "PNP, 40 V, 200 mA, general purpose",
                _legs("E", "B", "C"), "pnp", source=f"onsemi 2N3906/D; {_TO92_ORDER}",
                check=_CHECK_LEGS),
    CatalogPart("tip120", "TIP120", "transistor", "to220", "NPN Darlington, 60 V, 5 A",
                _legs("B", "C", "E"), "npn", source=f"onsemi TIP120/D; {_TO220_ORDER}",
                check="The tab is the collector. " + _CHECK_LEGS),
    CatalogPart("tip122", "TIP122", "transistor", "to220", "NPN Darlington, 100 V, 5 A",
                _legs("B", "C", "E"), "npn", source=f"onsemi TIP120/D; {_TO220_ORDER}",
                check="The tab is the collector. " + _CHECK_LEGS),
    CatalogPart("tip127", "TIP127", "transistor", "to220", "PNP Darlington, 100 V, 5 A",
                _legs("B", "C", "E"), "pnp", source=f"onsemi TIP125/D; {_TO220_ORDER}",
                check="The tab is the collector. " + _CHECK_LEGS),
    CatalogPart("tip31c", "TIP31C", "transistor", "to220", "NPN power, 100 V, 3 A",
                _legs("B", "C", "E"), "npn", source=f"onsemi TIP31A/D; {_TO220_ORDER}",
                check="The tab is the collector. " + _CHECK_LEGS),
    CatalogPart("tip41c", "TIP41C", "transistor", "to220", "NPN power, 100 V, 6 A",
                _legs("B", "C", "E"), "npn", source=f"onsemi TIP41A/D; {_TO220_ORDER}",
                check="The tab is the collector. " + _CHECK_LEGS),
    # -- MOSFETs ----------------------------------------------------------------------
    CatalogPart("2n7000", "2N7000", "mosfet", "to92", "N-channel, 60 V, 200 mA, small signal",
                _legs("S", "G", "D"), "nmos", source=f"onsemi 2N7000/D; {_TO92_ORDER}",
                check=_CHECK_LEGS),
    CatalogPart("bs170", "BS170", "mosfet", "to92", "N-channel, 60 V, 500 mA, small signal",
                _legs("D", "G", "S"), "nmos", source=f"onsemi BS170/D; {_TO92_ORDER}",
                check="Pinned the other way round from the 2N7000. " + _CHECK_LEGS),
    CatalogPart("irf540n", "IRF540N", "mosfet", "to220", "N-channel, 100 V, 33 A, 10 V gate",
                _legs("G", "D", "S"), "nmos", source=f"Infineon IRF540N; {_TO220_ORDER}",
                check="The tab is the drain."),
    CatalogPart("irfz44n", "IRFZ44N", "mosfet", "to220", "N-channel, 55 V, 49 A, 10 V gate",
                _legs("G", "D", "S"), "nmos", source=f"Infineon IRFZ44N; {_TO220_ORDER}",
                check="The tab is the drain. Not fully on from a 3.3 V or 5 V pin."),
    CatalogPart("irlz44n", "IRLZ44N", "mosfet", "to220",
                "N-channel, 55 V, 47 A, logic-level gate (on from 5 V)",
                _legs("G", "D", "S"), "nmos", source=f"Infineon IRLZ44N; {_TO220_ORDER}",
                check="The tab is the drain."),
    CatalogPart("irf520n", "IRF520N", "mosfet", "to220", "N-channel, 100 V, 9.7 A, 10 V gate",
                _legs("G", "D", "S"), "nmos", source=f"Infineon IRF520N; {_TO220_ORDER}",
                check="The tab is the drain."),
    CatalogPart("irf3205", "IRF3205", "mosfet", "to220", "N-channel, 55 V, 110 A, 10 V gate",
                _legs("G", "D", "S"), "nmos", source=f"Infineon IRF3205; {_TO220_ORDER}",
                check="The tab is the drain."),
    CatalogPart("irf9540n", "IRF9540N", "mosfet", "to220", "P-channel, -100 V, -23 A",
                _legs("G", "D", "S"), "pmos", source=f"Infineon IRF9540N; {_TO220_ORDER}",
                check="The tab is the drain. A high-side switch: source to the supply."),
    CatalogPart("irf4905", "IRF4905", "mosfet", "to220", "P-channel, -55 V, -74 A",
                _legs("G", "D", "S"), "pmos", source=f"Infineon IRF4905; {_TO220_ORDER}",
                check="The tab is the drain. A high-side switch: source to the supply."),
    CatalogPart("irf9z34n", "IRF9Z34N", "mosfet", "to220", "P-channel, -55 V, -19 A",
                _legs("G", "D", "S"), "pmos", source=f"Infineon IRF9Z34N; {_TO220_ORDER}",
                check="The tab is the drain. A high-side switch: source to the supply."),
    # -- regulators and references ----------------------------------------------------
    CatalogPart("7805", "7805", "regulator", "to220", "Linear regulator, +5 V, 1.5 A",
                _legs("IN", "GND", "OUT"), ref_prefix="U",
                source=f"ST L78 datasheet; {_TO220_ORDER}",
                check="The tab is ground. Needs 0.33 uF on the input and 0.1 uF on the output."),
    CatalogPart("7809", "7809", "regulator", "to220", "Linear regulator, +9 V, 1.5 A",
                _legs("IN", "GND", "OUT"), ref_prefix="U",
                source=f"ST L78 datasheet; {_TO220_ORDER}", check="The tab is ground."),
    CatalogPart("7812", "7812", "regulator", "to220", "Linear regulator, +12 V, 1.5 A",
                _legs("IN", "GND", "OUT"), ref_prefix="U",
                source=f"ST L78 datasheet; {_TO220_ORDER}", check="The tab is ground."),
    CatalogPart("7905", "7905", "regulator", "to220", "Linear regulator, -5 V, 1.5 A",
                _legs("GND", "IN", "OUT"), ref_prefix="U",
                source=f"ST L79 datasheet; {_TO220_ORDER}",
                check="NOT pinned like a 7805: the tab is the INPUT."),
    CatalogPart("lm317t", "LM317T", "regulator", "to220",
                "Adjustable regulator, +1.25 to +37 V, 1.5 A",
                _legs("ADJ", "OUT", "IN"), ref_prefix="U",
                source=f"TI LM317 datasheet; {_TO220_ORDER}", check="The tab is the output."),
    CatalogPart("lm337t", "LM337T", "regulator", "to220",
                "Adjustable regulator, -1.25 to -37 V, 1.5 A",
                _legs("ADJ", "IN", "OUT"), ref_prefix="U",
                source=f"TI LM337 datasheet; {_TO220_ORDER}",
                check="NOT pinned like an LM317: the tab is the INPUT."),
    CatalogPart("78l05", "78L05", "regulator", "to92", "Linear regulator, +5 V, 100 mA",
                _legs("OUT", "GND", "IN"), ref_prefix="U",
                source=f"TI LM78L datasheet; {_TO92_ORDER}", check=_CHECK_LEGS),
    CatalogPart("mcp1700-3302", "MCP1700-3302E/TO", "regulator", "to92",
                "Low-dropout regulator, +3.3 V, 250 mA, 1.6 uA quiescent",
                _legs("GND", "IN", "OUT"), value="MCP1700-3.3", ref_prefix="U",
                source=f"Microchip MCP1700 datasheet, TO-92; {_TO92_ORDER}",
                check=(
                    "NOT pinned like a 78L05: GND, IN, OUT. Its input is 6 V at most, and it "
                    "needs 1 uF on both sides."
                ),
                aliases=("3.3 V regulator",)),
    CatalogPart("ld1117v33", "LD1117V33", "regulator", "to220",
                "Low-dropout regulator, +3.3 V, 800 mA",
                _legs("GND", "OUT", "IN"), ref_prefix="U",
                source=f"ST LD1117 datasheet, TO-220; {_TO220_ORDER}",
                check=(
                    "NOT pinned like a 7805: GND, OUT, IN, and the tab is the output. It needs "
                    "10 uF on the output to stay stable. The LM1117T-3.3 is pinned the same."
                ),
                aliases=("3.3 V regulator", "LM1117T-3.3")),
    # -- power in ---------------------------------------------------------------------
    CatalogPart("battery-9v-clip", "9 V battery clip", "power", "wire-2",
                "PP3 snap on two leads, for a 9 V battery",
                _legs("+", "-"), value="9V", ref_prefix="BT",
                source="Keystone 233 9 V battery snap: red and black 26 AWG leads, 6 in",
                check=(
                    "Red is +. If both leads of yours are one colour, find + with a meter on "
                    "the battery before soldering."
                ),
                aliases=(*_POWER_WORDS, "batarya", "PP3", "9V")),
    CatalogPart("battery-aa-holder", "AA battery holder", "power", "wire-2",
                "Two to four AA or AAA cells in series, on two leads",
                _legs("+", "-"), value="AA holder", ref_prefix="BT",
                source="Keystone 2463 2 x AA holder: red and black 26 AWG leads, 150 mm",
                check=(
                    "Red is + and black is -. With no colours, measure across it with the "
                    "cells in."
                ),
                aliases=(*_POWER_WORDS, "batarya", "AAA")),
    CatalogPart("dc-jack-panel", "DC barrel jack 5.5 x 2.1 mm, panel mount", "power", "wire-2",
                "On the case, wired to the board from its centre pin and its sleeve",
                _legs("+", "-"), value="DC IN",
                source=(
                    "IEC 60130-10 type A plug, 5.5 mm outside and 2.1 mm pin; the jack's "
                    "centre pin is pin 1 here and its sleeve pin 2"
                ),
                check=(
                    "Centre-positive is the usual way and not a rule: the symbol on the "
                    "adapter says which. A third lug, if yours has one, is a switch and stays "
                    "unconnected here."
                ),
                aliases=(*_POWER_WORDS, "jack", "adapter", "adaptör")),
    CatalogPart("power-terminal-2", "Power in, 2-way screw terminal", "power",
                "screw-terminal-2", "Two wires in under screws, named + and -",
                _legs("+", "-"), value="DC IN",
                source=(
                    "Phoenix Contact MKDS 1,5/ 2-5,08, the terminal screw-terminal-2 is drawn "
                    "from; which way is + is the board's choice, not the terminal's"
                ),
                check="Print + and - beside it: the terminal itself does not say.",
                aliases=(*_POWER_WORDS, "terminal block")),
    CatalogPart("power-header-2", "Power in, 2-pin header", "power", "hdr-1x2",
                "Two header pins named + and -, for a lead that plugs on",
                _legs("+", "-"), value="DC IN",
                source="2.54 mm pin header; which way is + is the board's choice",
                check="Print + and - beside it: the header itself does not say.",
                aliases=_POWER_WORDS),
    CatalogPart("tl431", "TL431", "regulator", "to92",
                "Adjustable shunt reference, 2.5 to 36 V",
                _legs("REF", "A", "K"), ref_prefix="U",
                source=f"TI TL431 datasheet, LP package; {_TO92_ORDER}", check=_CHECK_LEGS),
    # -- diodes -----------------------------------------------------------------------
    CatalogPart("1n4148", "1N4148", "diode", "d-do35", "Small-signal diode, 100 V, 200 mA",
                _DIODE, source="Vishay 1N4148; cathode is the banded end"),
    CatalogPart("1n4007", "1N4007", "diode", "d-do41", "Rectifier, 1000 V, 1 A",
                _DIODE, source="Vishay 1N4001; cathode is the banded end"),
    CatalogPart("1n5819", "1N5819", "diode", "d-do41", "Schottky, 40 V, 1 A",
                _DIODE, source="Vishay 1N5817; cathode is the banded end"),
    CatalogPart("bzx55c3v3", "BZX55C3V3", "diode", "d-do35", "Zener, 3.3 V, 0.5 W",
                _DIODE, "zener", value="3V3", source="Vishay BZX55; cathode is the banded end"),
    CatalogPart("bzx55c5v1", "BZX55C5V1", "diode", "d-do35", "Zener, 5.1 V, 0.5 W",
                _DIODE, "zener", value="5V1", source="Vishay BZX55; cathode is the banded end"),
    CatalogPart("bzx55c12", "BZX55C12", "diode", "d-do35",
                "Zener, 12 V, 0.5 W (a MOSFET gate clamp)",
                _DIODE, "zener", value="12V", source="Vishay BZX55; cathode is the banded end"),
    CatalogPart("bzx55c15", "BZX55C15", "diode", "d-do35",
                "Zener, 15 V, 0.5 W (a MOSFET gate clamp)",
                _DIODE, "zener", value="15V", source="Vishay BZX55; cathode is the banded end"),
    # -- LEDs -------------------------------------------------------------------------
    # The plain ones first, smallest first as the library lists them, and on the library's
    # own footprints: "LED" and Enter in Add a Part takes the first row the word names,
    # and that has to be an LED everybody means rather than a four-legged one.
    CatalogPart("led-3mm", "LED 3 mm", "led", "led-3mm",
                "The small indicator LED, any colour; legs 2.54 mm apart",
                _legs("A", "K"), "led", value="LED",
                source=(
                    "Kingbright WP710A10ID datasheet: the cathode is the shorter lead, on the "
                    "flat of the rim; leads 2.54 mm apart"
                ),
                check=_LED_CHECK, aliases=("indicator", "light", "ışık")),
    CatalogPart("led-5mm", "LED 5 mm", "led", "led-5mm",
                "The standard indicator LED, any colour; legs 2.54 mm apart",
                _legs("A", "K"), "led", value="LED",
                source=(
                    "Kingbright WP7113ID datasheet: the cathode is the shorter lead, on the "
                    "flat of the rim; leads 2.54 mm apart"
                ),
                check=_LED_CHECK, aliases=("indicator", "light", "ışık")),
    # Two makers, two orders for green and blue, so the order is in the name, as the two
    # OLEDs' supply pins are. The common leg's names are KiCad's (LED_RKGB and its kin).
    CatalogPart("rgb-led-5mm-cc", "RGB LED 5 mm, common cathode (R K G B)", "led",
                "led-5mm-rgb",
                "Red, green and blue in one lens, the three cathodes on the longest leg",
                _legs("RA", "K", "GA", "BA"), value="RGB LED",
                source=(
                    "Young Sun YSL-R596CR3G4B5W-F12 datasheet (the one SparkFun sells as "
                    "COM-09264): 1 red, 2 common cathode (the longest leg), 3 green, 4 blue"
                ),
                check=_RGB_CHECK, aliases=("RGB", "tri-colour")),
    CatalogPart("rgb-led-5mm-ca", "RGB LED 5 mm, common anode (R A G B)", "led",
                "led-5mm-rgb",
                "Red, green and blue in one lens, the three anodes on the longest leg",
                _legs("RK", "A", "GK", "BK"), value="RGB LED",
                source=(
                    "Fedy FD-5WSRGB-A datasheet (the one Adafruit sells as #159): red, the "
                    "common anode (the longest leg), green, blue in a row. Its note misprints "
                    "the fourth leg's colour as '2:Y'; blue by elimination, and where Young "
                    "Sun puts blue on its common-cathode twin"
                ),
                check=_RGB_CHECK, aliases=("RGB", "tri-colour")),
    CatalogPart("rgb-led-5mm-cc-kingbright", "RGB LED 5 mm, common cathode, Kingbright (R K B G)",
                "led", "led-5mm-rgb",
                "Red, blue and green in one lens, the three cathodes on the longest leg",
                _legs("RA", "K", "BA", "GA"), value="RGB LED",
                source=(
                    "Kingbright L-154A4SUREQBFZGEW and L-154A4SUREQBFZGC datasheets: 1 red, "
                    "2 common cathode (the longest leg), 3 blue, 4 green, 1.27 mm apart"
                ),
                check=_RGB_CHECK,
                aliases=("RGB", "L-154A4SUREQBFZGEW", "L-154A4SUREQBFZGC")),
    CatalogPart("rgb-led-5mm-ca-kingbright", "RGB LED 5 mm, common anode, Kingbright (R A B G)",
                "led", "led-5mm-rgb",
                "Red, blue and green in one lens, the three anodes on the longest leg",
                _legs("RK", "A", "BK", "GK"), value="RGB LED",
                source=(
                    "Kingbright WP154A4SEJ3VBDZGW/CA datasheet: 1 red, 2 common anode (the "
                    "longest leg), 3 blue, 4 green, 1.27 mm apart"
                ),
                check=_RGB_CHECK, aliases=("RGB", "WP154A4SEJ3VBDZGW/CA")),
    # -- protection -------------------------------------------------------------------
    CatalogPart("ptc-radial", "PTC resettable fuse", "protection", "c-disc-d8-p2-t3",
                "Polymer PTC (polyfuse), radial, leads 5 mm apart",
                symbol="fuse", value="PTC", ref_prefix="F",
                source="Bourns MF-R series: radial, 5.1 mm lead spacing",
                check=(
                    "Its size grows with its hold current: if yours is larger than 8 mm, "
                    "describe it as a disc capacitor of its real size and mark it a fuse."
                )),
    # -- passives ---------------------------------------------------------------------
    CatalogPart("bourns-3296w", "Bourns 3296W trimmer", "passive",
                "box-3x1-p1-r1-9.53x4.83x11.05",
                "Multi-turn trimmer potentiometer, 25 turns, adjusted from the top",
                _legs("1", "W", "3"), "potentiometer", value="3296W", ref_prefix="RV",
                source=(
                    "Bourns 3296 datasheet: terminals 1, 2 (the wiper) and 3, 2.54 mm apart, the "
                    "W body 9.53 x 4.83 mm; its height with the screw from KiCad's "
                    "Potentiometer_Bourns_3296W_Vertical model"
                ),
                check=(
                    "Its resistance is printed on it in three digits: 103 is 10 kohm, 502 is "
                    "5 kohm. Put that in the value."
                ),
                aliases=("trimmer", "trimpot", "potentiometer", "potansiyometre", "preset")),
    CatalogPart("bourns-78f101j", "Bourns 78F101J axial inductor", "passive",
                "axial-4h-7.11x2.79",
                "100 uH RF choke, 165 mA, laid flat like a resistor",
                value="100uH", ref_prefix="L",
                source=(
                    "Bourns 78F series: the 78F101J's body 2.79 mm across and 7.11 mm long, "
                    "100 uH, 165 mA, 4.1 ohm"
                ),
                check="A larger inductance in this series is a larger body: measure yours.",
                aliases=("inductor", "choke", "bobin", "endüktans")),
    # -- sensors ----------------------------------------------------------------------
    CatalogPart("lm35", "LM35", "sensor", "to92", "Temperature sensor, 10 mV per degree C",
                _legs("+VS", "VOUT", "GND"), ref_prefix="U",
                source=f"TI LM35 datasheet, LP package; {_TO92_ORDER}", check=_CHECK_LEGS),
    CatalogPart("ds18b20", "DS18B20", "sensor", "to92",
                "Temperature sensor, 1-Wire, needs a 4.7k pull-up on DQ",
                _legs("GND", "DQ", "VDD"), ref_prefix="U",
                source=f"Analog Devices DS18B20 datasheet; {_TO92_ORDER}", check=_CHECK_LEGS,
                aliases=("one-wire",)),
    # The bare sensors, four legs in a row on 2.54 mm and the body standing on them: a box
    # with the legs along its width, as wide and as thick as the sensor and as tall.
    CatalogPart("dht11", "DHT11", "sensor", "box-4x1-p1-r1-12x5.5x15.5",
                "Humidity and temperature sensor, 20-90 %RH, 0-50 degrees C, single wire",
                _legs("VDD", "DATA", "NC", "GND"), ref_prefix="U",
                source=(
                    "Aosong DHT11 datasheet (pins 1-4 left to right, grille towards you; a 5k "
                    "pull-up on DATA); body 15.5 x 12 x 5.5 mm, Adafruit 386; the legs "
                    "centred in its thickness, KiCad Sensor:Aosong_DHT11_5.5x12.0_P2.54mm"
                ),
                check=(
                    "Also sold on a small board with three pins, in more than one order: on "
                    "one of those, go by what the board itself has printed beside each pin."
                )),
    CatalogPart("dht22", "DHT22 (AM2302)", "sensor", "box-4x1-p1-r1-15.1x7.7x25.1-o0x1.4",
                "Humidity and temperature sensor, 0-100 %RH, -40 to 80 degrees C, single wire",
                _legs("VDD", "DATA", "NC", "GND"), value="DHT22", ref_prefix="U",
                source=(
                    "Aosong DHT22 datasheet: body 15.1 x 25.1 x 7.7 mm, pins 1-4 left to "
                    "right; how far the legs stand from its front, KiCad "
                    "Sensor:ASAIR_AM2302_P2.54mm_Vertical"
                ),
                check=(
                    "KiCad's AM2302 symbol calls pin 3 GND; Aosong's datasheet says it is not "
                    "connected, and so does this. Also sold on a small board with three pins: "
                    "on one of those, go by what the board itself has printed."
                )),
    # Its board stands up on its four pins, the transducers facing down the rows: a box as
    # wide as the board, as deep as the transducers stand out, as tall as it stands.
    CatalogPart("hc-sr04", "HC-SR04", "sensor", "box-4x1-p1-r1-45x15x22.5-o0x3.5",
                "Ultrasonic distance sensor, 2 cm to 4 m, 5 V; stands on its edge",
                _legs("VCC", "TRIG", "ECHO", "GND"), ref_prefix="U",
                source=(
                    "ElecFreaks HC-SR04 user guide: Vcc, Trig, Echo, GND left to right with "
                    "the transducers towards you; 45 x 20 x 15 mm; 5 V"
                ),
                check=(
                    "ECHO is a 5 V output: put a divider between it and a 3.3 V pin. How far "
                    "the transducers stand in front of the pins, and how high the board sits "
                    "on them, are estimates."
                ),
                aliases=("ultrasonic", "sonar", "distance")),
    # The MPU-6050 board everybody sells: its eight names are printed on it and the same on
    # every one; nobody publishes a drawing of the board, so its size is the sellers'.
    CatalogPart("gy-521", "GY-521 MPU-6050", "sensor", "mod-8x1-p1-r1-21.2x16.4x1.5-s8.5-o0x6.7",
                "Accelerometer and gyroscope, three axes each, on I2C",
                _legs("VCC", "GND", "SCL", "SDA", "XDA", "XCL", "AD0", "INT"), ref_prefix="U",
                source=(
                    "The eight names as the board prints them; the 21.2 x 16.4 mm board as "
                    "sellers list it; the chip, InvenSense's MPU-6050 (I2C address 0x68 with AD0 "
                    "low, 0x69 high)"
                ),
                check=(
                    "VCC takes 3.3 to 5 V: the board has its own 3.3 V regulator. XDA and XCL are "
                    "for a second sensor and can stay open. Sellers give the board as 20 to 21.2 "
                    "by 15.5 to 16.4 mm: where the header sits on it and how tall its parts "
                    "stand are estimates."
                ),
                aliases=("MPU6050", "accelerometer", "gyroscope", "IMU", "ivmeölçer", "jiroskop")),
    # The receiver's body stands on its three legs with its dome facing down the rows, as
    # KiCad's model of Vishay's MINICAST package has it.
    CatalogPart("tsop38238", "TSOP38238", "sensor", "box-3x1-p1-r1-5.92x4.8x10.35-o0x1",
                "IR receiver for 38 kHz remote controls, 2.5 to 5.5 V",
                _legs("OUT", "GND", "VS"), ref_prefix="U",
                source=(
                    "Vishay TSOP382 datasheet: 1 OUT, 2 GND, 3 VS; the MINICAST body as KiCad "
                    "OptoDevice:Vishay_MINICAST-3Pin and its model measure it"
                ),
                check=(
                    "The VS1838B in kits is usually pinned the same, OUT, GND, VCC from the "
                    "left with the dome towards you, but not always: check yours."
                ),
                aliases=("infrared", "IR receiver", "remote", "VS1838B", "kızılötesi")),
    # A light-dependent resistor standing on its legs, as KiCad's model of the 5 x 4.1 mm
    # cell has it; its legs are 3 mm apart and bend in to holes one apart.
    CatalogPart("gl5528", "GL5528 photoresistor (LDR)", "sensor", "box-2x1-p1-r1-5x4.1x4",
                "Light-dependent resistor: 10 to 20 kohm at 10 lux, 1 Mohm in the dark",
                value="GL5528", ref_prefix="R",
                source=(
                    "Senba GL55 series datasheet (the GL5528's resistances); the 5 x 4.1 mm "
                    "cell and its height from KiCad's R_LDR_5.0x4.1mm_P3mm_Vertical model"
                ),
                check=(
                    "Its legs are 3 mm apart: bend each a quarter of a millimetre in to the "
                    "holes drawn. Either way round works."
                ),
                aliases=("ldr", "photoresistor", "light sensor", "ışık sensörü", "fotodirenç")),
    # -- displays ---------------------------------------------------------------------
    CatalogPart("ssd1306-i2c-gnd-vcc", "SSD1306 OLED 0.96in I2C (GND VCC SCL SDA)", "display",
                _OLED_FOOTPRINT, "128 x 64 OLED on I2C, pins printed GND, VCC, SCL, SDA",
                _legs("GND", "VCC", "SCL", "SDA"), value="SSD1306 OLED", ref_prefix="U",
                source=_OLED_SOURCE, check=_OLED_CHECK, aliases=("oled", "display", "screen")),
    CatalogPart("ssd1306-i2c-vcc-gnd", "SSD1306 OLED 0.96in I2C (VCC GND SCL SDA)", "display",
                _OLED_FOOTPRINT, "128 x 64 OLED on I2C, pins printed VCC, GND, SCL, SDA",
                _legs("VCC", "GND", "SCL", "SDA"), value="SSD1306 OLED", ref_prefix="U",
                source=_OLED_SOURCE, check=_OLED_CHECK, aliases=("oled", "display", "screen")),
    # The classic 16 x 2 on its 1 x 16 header, pin 1 at the left of the top edge, standing
    # on its own pins as KiCad's model of Winstar's WC1602A stands.
    CatalogPart("lcd-1602", "16x2 character LCD (HD44780)", "display",
                "box-16x1-p1-r1-80x36x15-o12.95x15.5",
                "Two lines of 16 characters, 5 V, on a 16-pin header",
                _legs("VSS", "VDD", "VO", "RS", "RW", "E", "D0", "D1", "D2", "D3", "D4", "D5",
                      "D6", "D7", "A", "K"),
                value="LCD 16x2", ref_prefix="U",
                source=(
                    "KiCad Display:WC1602A footprint and Display_Character:WC1602A symbol "
                    "(Winstar WC1602A: the 80 x 36 mm module, the header, the names), and the "
                    "15 mm it stands from KiCad's WC1602A model"
                ),
                check=(
                    "VO sets the contrast: a 10k pot across VDD and VSS with its wiper on VO. A "
                    "and K are the backlight. A few modules put those two before pin 1: count "
                    "from the pin marked 1. On an I2C backpack it is a different part."
                ),
                aliases=("1602", "HD44780", "character display")),
    # Kingbright's 0.56 inch digits are pinned like a DIP under a block, which is what
    # ``-ccw`` says: on the board the pins run down one column and back up the other, and
    # the part reads upright turned so that pin 1 is at its bottom left.
    CatalogPart("sa56-11", "SA56-11 7-segment digit (common anode)", "display",
                _DIGIT_FOOTPRINT, "One 0.56 inch digit, common anode, decimal point at the right",
                _legs("e", "d", "CA", "c", "DP", "b", "a", "CA", "f", "g"),
                value="SA56-11", ref_prefix="U",
                source=(
                    "Kingbright SA56-11EWA and SA56-11GWA datasheets: 1 e, 2 d, 3 and 8 the "
                    "common anode, 4 c, 5 DP, 6 b, 7 a, 9 f, 10 g; 12.7 x 19.05 x 8 mm, the "
                    "rows 15.24 mm apart"
                ),
                check=_DIGIT_CHECK,
                aliases=(*_DIGIT_ALIASES, "SA56-11EWA", "SA56-11GWA")),
    CatalogPart("sc56-11", "SC56-11 7-segment digit (common cathode)", "display",
                _DIGIT_FOOTPRINT,
                "One 0.56 inch digit, common cathode, decimal point at the right",
                _legs("e", "d", "CC", "c", "DP", "b", "a", "CC", "f", "g"),
                value="SC56-11", ref_prefix="U",
                source=(
                    "Kingbright SC56-11EWA and SC56-11GWA datasheets: 1 e, 2 d, 3 and 8 the "
                    "common cathode, 4 c, 5 DP, 6 b, 7 a, 9 f, 10 g; 12.7 x 19.05 x 8 mm, the "
                    "rows 15.24 mm apart"
                ),
                check=_DIGIT_CHECK,
                aliases=(*_DIGIT_ALIASES, "SC56-11EWA", "SC56-11GWA")),
    CatalogPart("ca56-12", "CA56-12 4-digit 7-segment (common anode)", "display",
                _FOUR_DIGITS_FOOTPRINT,
                "Four 0.56 inch digits, lit in turn: one common anode per digit",
                _legs("e", "d", "DP", "c", "g", "DIG4", "b", "DIG3", "DIG2", "f", "a", "DIG1"),
                value="CA56-12", ref_prefix="U",
                source=f"Kingbright CA56-12EWA datasheet: {_FOUR_DIGITS_PINS}",
                check=_FOUR_DIGITS_CHECK,
                aliases=(*_DIGIT_ALIASES, "CA56-12EWA")),
    CatalogPart("cc56-12", "CC56-12 4-digit 7-segment (common cathode)", "display",
                _FOUR_DIGITS_FOOTPRINT,
                "Four 0.56 inch digits, lit in turn: one common cathode per digit",
                _legs("e", "d", "DP", "c", "g", "DIG4", "b", "DIG3", "DIG2", "f", "a", "DIG1"),
                value="CC56-12", ref_prefix="U",
                source=f"Kingbright CC56-12EWA datasheet: {_FOUR_DIGITS_PINS}",
                check=_FOUR_DIGITS_CHECK,
                aliases=(*_DIGIT_ALIASES, "CC56-12EWA")),
    # -- integrated circuits ------------------------------------------------------------
    CatalogPart("ne555", "NE555", "ic", "dip-8", "Timer",
                _legs("GND", "TRIG", "OUT", "RESET", "CTRL", "THR", "DIS", "VCC"),
                ref_prefix="U", source="TI NE555 datasheet, P package"),
    CatalogPart("lm358", "LM358", "ic", "dip-8", "Dual op-amp, single supply",
                _legs("OUT1", "IN1-", "IN1+", "GND", "IN2+", "IN2-", "OUT2", "VCC"),
                ref_prefix="U", source="TI LM358 datasheet, P package"),
    CatalogPart("lm393", "LM393", "ic", "dip-8", "Dual comparator, open-collector outputs",
                _legs("OUT1", "IN1-", "IN1+", "GND", "IN2+", "IN2-", "OUT2", "VCC"),
                ref_prefix="U", source="TI LM393 datasheet, P package"),
    CatalogPart("6n137", "6N137", "ic", "dip-8", "High-speed optocoupler, 10 Mbit/s",
                _legs("NC", "A", "K", "NC", "GND", "VO", "VE", "VCC"),
                ref_prefix="U", source="Broadcom 6N137 datasheet",
                aliases=("opto-isolator",)),
    CatalogPart("pc817", "PC817", "ic", "dip-4", "Optocoupler, transistor output",
                _legs("A", "K", "E", "C"), ref_prefix="U", source="Sharp PC817 datasheet",
                aliases=("opto-isolator",)),
    CatalogPart("mcp2551", "MCP2551", "ic", "dip-8", "CAN transceiver, 5 V, 1 Mbit/s",
                _legs("TXD", "VSS", "VDD", "RXD", "VREF", "CANL", "CANH", "RS"),
                ref_prefix="U", source="Microchip MCP2551 datasheet, PDIP"),
    CatalogPart("max485", "MAX485", "ic", "dip-8", "RS-485 transceiver, half duplex, 5 V",
                _legs("RO", "RE", "DE", "DI", "GND", "A", "B", "VCC"),
                ref_prefix="U", source="Analog Devices MAX485 datasheet, PDIP"),
    CatalogPart("tl072", "TL072", "ic", "dip-8",
                "Dual JFET-input op-amp, low noise, for a split supply",
                _legs("OUT1", "IN1-", "IN1+", "V-", "IN2+", "IN2-", "OUT2", "V+"),
                ref_prefix="U", source="TI TL07x datasheet, P package",
                check=(
                    "Not a rail-to-rail part: on one low supply its inputs and its output cannot "
                    "come near either rail. The LM358 is the single-supply one."
                )),
    CatalogPart("lm386", "LM386", "ic", "dip-8",
                "Audio power amplifier, 0.3 to 1 W, gain 20 to 200",
                _legs("GAIN", "IN-", "IN+", "GND", "VOUT", "VS", "BYPASS", "GAIN"),
                ref_prefix="U", source="TI LM386 datasheet, P package",
                check=(
                    "Pins 1 and 8 are both GAIN: left open the gain is 20, and 10 uF between "
                    "them makes it 200."
                )),
    CatalogPart("attiny85", "ATtiny85", "ic", "dip-8", "8-bit AVR, 8 kB flash, five I/O pins",
                _legs("RESET", "PB3", "PB4", "GND", "PB0", "PB1", "PB2", "VCC"),
                ref_prefix="U", source="Microchip ATtiny25/45/85 datasheet, PDIP",
                aliases=("microcontroller", "mikrodenetleyici")),
    CatalogPart("ds1307", "DS1307", "ic", "dip-8",
                "Real-time clock, I2C, with battery backup, 5 V",
                _legs("X1", "X2", "VBAT", "GND", "SDA", "SCL", "SQW/OUT", "VCC"),
                ref_prefix="U", source="Analog Devices DS1307 datasheet, PDIP",
                check=(
                    "X1 and X2 take a 32.768 kHz crystal made for 12.5 pF. With no coin cell, "
                    "VBAT goes to GND."
                ),
                aliases=("RTC",)),
    CatalogPart("24lc256", "24LC256", "ic", "dip-8", "EEPROM, 256 kbit (32 kB), I2C",
                _legs("A0", "A1", "A2", "VSS", "SDA", "SCL", "WP", "VCC"),
                ref_prefix="U", source="Microchip 24AA256/24LC256 datasheet, PDIP",
                check="WP to VSS lets it be written; A0-A2 set its address."),
    CatalogPart("lm324", "LM324", "ic", "dip-14", "Quad op-amp, single supply",
                _legs("OUT1", "IN1-", "IN1+", "VCC", "IN2+", "IN2-", "OUT2",
                      "OUT3", "IN3-", "IN3+", "GND", "IN4+", "IN4-", "OUT4"),
                ref_prefix="U", source="TI LM324 datasheet, N package",
                check="VCC is pin 4 and GND pin 11, not the corners."),
    CatalogPart("74hc165", "74HC165", "ic", "dip-16", "8-bit shift register, parallel in, serial out",
                _legs("SH/LD", "CLK", "E", "F", "G", "H", "~QH", "GND",
                      "QH", "SER", "A", "B", "C", "D", "CLKINH", "VCC"),
                ref_prefix="U", source="TI SN74HC165 datasheet, N package",
                check=(
                    "Pin 7 is QH inverted. The output to read, and to chain the next one from, "
                    "is pin 9."
                )),
    CatalogPart("cd4017", "CD4017", "ic", "dip-16", "Decade counter with ten decoded outputs",
                _legs("Q5", "Q1", "Q0", "Q2", "Q6", "Q7", "Q3", "VSS",
                      "Q8", "Q4", "Q9", "COUT", "INH", "CLK", "RESET", "VDD"),
                ref_prefix="U", source="TI CD4017B datasheet, E package",
                check="The outputs are not in order round the package: Q0 is pin 3."),
    CatalogPart("pcf8574", "PCF8574", "ic", "dip-16",
                "8-bit I/O expander, I2C (the chip on an LCD's I2C backpack)",
                _legs("A0", "A1", "A2", "P0", "P1", "P2", "P3", "VSS",
                      "P4", "P5", "P6", "P7", "INT", "SCL", "SDA", "VDD"),
                ref_prefix="U", source="NXP PCF8574/PCF8574A datasheet, DIP16",
                check=(
                    "The PCF8574A is pinned the same and answers at another address "
                    "(0x38-0x3F, not 0x20-0x27)."
                ),
                aliases=("port expander",)),
    CatalogPart("mcp3008", "MCP3008", "ic", "dip-16", "8-channel 10-bit ADC, SPI",
                _legs("CH0", "CH1", "CH2", "CH3", "CH4", "CH5", "CH6", "CH7",
                      "DGND", "CS/SHDN", "DIN", "DOUT", "CLK", "AGND", "VREF", "VDD"),
                ref_prefix="U", source="Microchip MCP3004/3008 datasheet, PDIP",
                aliases=("analog to digital",)),
    CatalogPart("74hc595", "74HC595", "ic", "dip-16", "8-bit shift register, latched outputs",
                _legs("QB", "QC", "QD", "QE", "QF", "QG", "QH", "GND",
                      "QH'", "SRCLR", "SRCLK", "RCLK", "OE", "SER", "QA", "VCC"),
                ref_prefix="U", source="TI SN74HC595 datasheet, N package"),
    CatalogPart("uln2003a", "ULN2003A", "ic", "dip-16",
                "Seven Darlington sinks, 50 V, 500 mA, with flyback diodes",
                _legs("IN1", "IN2", "IN3", "IN4", "IN5", "IN6", "IN7", "GND",
                      "COM", "OUT7", "OUT6", "OUT5", "OUT4", "OUT3", "OUT2", "OUT1"),
                ref_prefix="U", source="TI ULN2003A datasheet, N package",
                aliases=("stepper", "28BYJ-48")),
    CatalogPart("l293d", "L293D", "ic", "dip-16", "Dual H-bridge, 600 mA, with clamp diodes",
                _legs("EN12", "1A", "1Y", "GND", "GND", "2Y", "2A", "VCC2",
                      "EN34", "3A", "3Y", "GND", "GND", "4Y", "4A", "VCC1"),
                ref_prefix="U", source="TI L293D datasheet, NE package",
                aliases=("motor driver",),
                check="The four GND pins are also its heatsink: solder them to a copper area."),
    CatalogPart("mcp2515", "MCP2515", "ic", "dip-18", "CAN controller, SPI",
                _legs("TXCAN", "RXCAN", "CLKOUT", "TX0RTS", "TX1RTS", "TX2RTS", "OSC2",
                      "OSC1", "VSS", "RX1BF", "RX0BF", "INT", "SCK", "SI", "SO", "CS",
                      "RESET", "VDD"),
                ref_prefix="U", source="Microchip MCP2515 datasheet, PDIP"),
    CatalogPart("uln2803a", "ULN2803A", "ic", "dip-18",
                "Eight Darlington sinks, 50 V, 500 mA, with flyback diodes",
                _legs("IN1", "IN2", "IN3", "IN4", "IN5", "IN6", "IN7", "IN8", "GND",
                      "COM", "OUT8", "OUT7", "OUT6", "OUT5", "OUT4", "OUT3", "OUT2", "OUT1"),
                ref_prefix="U", source="TI ULN2803A datasheet, N package"),
    CatalogPart("74hc245", "74HC245", "ic", "dip-20",
                "Octal bus transceiver (74HCT245 for 3.3 V in, 5 V out)",
                _legs("DIR", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "GND",
                      "B8", "B7", "B6", "B5", "B4", "B3", "B2", "B1", "OE", "VCC"),
                ref_prefix="U", source="TI SN74HC245 datasheet, N package"),
    CatalogPart("max7219", "MAX7219", "ic", "dip-24",
                "LED display driver: eight 7-segment digits or an 8 x 8 matrix, serial in",
                _legs("DIN", "DIG0", "DIG4", "GND", "DIG6", "DIG2", "DIG3", "DIG7", "GND",
                      "DIG5", "DIG1", "LOAD", "CLK", "SEGA", "SEGF", "SEGB", "SEGG", "ISET",
                      "V+", "SEGC", "SEGE", "SEGDP", "SEGD", "DOUT"),
                ref_prefix="U",
                source="Analog Devices MAX7219/MAX7221 datasheet, 24-pin narrow PDIP (0.3 inch)",
                check=(
                    "Both GND pins have to be wired. A resistor from ISET to V+, 9.53k or more, "
                    "sets the segment current."
                ),
                aliases=("LED matrix", "seven segment")),
    CatalogPart("atmega328p", "ATmega328P", "ic", "dip-28", "8-bit AVR, the Arduino Uno's",
                _legs("RESET", "RXD", "TXD", "PD2", "PD3", "PD4", "VCC", "GND", "XTAL1",
                      "XTAL2", "PD5", "PD6", "PD7", "PB0", "PB1", "PB2", "MOSI", "MISO",
                      "SCK", "AVCC", "AREF", "GND", "PC0", "PC1", "PC2", "PC3", "PC4", "PC5"),
                ref_prefix="U", source="Microchip ATmega328P datasheet, PDIP",
                aliases=("microcontroller", "mikrodenetleyici")),
    CatalogPart("mcp23017", "MCP23017", "ic", "dip-28", "16-bit I/O expander, I2C",
                _legs("GPB0", "GPB1", "GPB2", "GPB3", "GPB4", "GPB5", "GPB6", "GPB7",
                      "VDD", "VSS", "NC", "SCL", "SDA", "NC", "A0", "A1", "A2", "RESET",
                      "INTB", "INTA", "GPA0", "GPA1", "GPA2", "GPA3", "GPA4", "GPA5", "GPA6",
                      "GPA7"),
                ref_prefix="U", source="Microchip MCP23017 datasheet DS20001952, SP package",
                check=(
                    "RESET has no pull-up of its own: tie it to VDD or the chip stays in reset. "
                    "GPA7 and GPB7 are outputs only."
                ),
                aliases=("port expander",)),
    # The 74HC gates and the 4000 series: pinned by TI, and named gate by gate, 1A and 1B
    # into 1Y, as TI names the 74HC ones (KiCad's units group the same pins the same way).
    CatalogPart("74hc00", "74HC00", "ic", "dip-14", "Quad 2-input NAND gate",
                _QUAD_GATE, ref_prefix="U", source="TI SN74HC00 datasheet, N package",
                check=_UNUSED_INPUTS, aliases=("nand", "logic gate", "mantık kapısı")),
    CatalogPart("74hc04", "74HC04", "ic", "dip-14", "Hex inverter",
                _HEX_INVERTER, ref_prefix="U", source="TI SN74HC04 datasheet, N package",
                check=_UNUSED_INPUTS, aliases=("not", "inverter", "logic gate", "mantık kapısı")),
    CatalogPart("74hc08", "74HC08", "ic", "dip-14", "Quad 2-input AND gate",
                _QUAD_GATE, ref_prefix="U", source="TI SN74HC08 datasheet, N package",
                check=_UNUSED_INPUTS, aliases=("and", "logic gate", "mantık kapısı")),
    CatalogPart("74hc14", "74HC14", "ic", "dip-14",
                "Hex inverter with Schmitt-trigger inputs: debouncing, slow edges, oscillators",
                _HEX_INVERTER, ref_prefix="U", source="TI SN74HC14 datasheet, N package",
                check=_UNUSED_INPUTS, aliases=("schmitt", "inverter", "debounce")),
    CatalogPart("74hc32", "74HC32", "ic", "dip-14", "Quad 2-input OR gate",
                _QUAD_GATE, ref_prefix="U", source="TI SN74HC32 datasheet, N package",
                check=_UNUSED_INPUTS, aliases=("or", "logic gate", "mantık kapısı")),
    CatalogPart("74hc86", "74HC86", "ic", "dip-14", "Quad 2-input XOR gate",
                _QUAD_GATE, ref_prefix="U", source="TI SN74HC86 datasheet, N package",
                check=_UNUSED_INPUTS, aliases=("xor", "logic gate", "mantık kapısı")),
    CatalogPart("74hc138", "74HC138", "ic", "dip-16",
                "3-to-8 line decoder, the chosen output goes low",
                _legs("A", "B", "C", "~G2A", "~G2B", "G1", "Y7", "GND",
                      "Y6", "Y5", "Y4", "Y3", "Y2", "Y1", "Y0", "VCC"),
                ref_prefix="U", source="TI SN74HC138 datasheet, N package",
                check=(
                    "An output is chosen only while G1 is high and G2A and G2B are both low: "
                    "tie them so, or every output stays high. The outputs are not in order "
                    "round the package: Y0 is pin 15 and Y7 pin 7."
                ),
                aliases=("decoder", "demultiplexer")),
    CatalogPart("74hc4051", "74HC4051", "ic", "dip-16",
                "8-channel analogue multiplexer: one common pin to any of eight",
                _legs("A4", "A6", "COM", "A7", "A5", "~E", "VEE", "GND",
                      "S2", "S1", "S0", "A3", "A0", "A1", "A2", "VCC"),
                ref_prefix="U", source="TI CD74HC4051 datasheet, E package",
                check=(
                    "VEE (pin 7) goes to GND unless the signals swing below ground, and E (pin "
                    "6) low turns the switch on. The channels are not in order round the "
                    "package: A0 is pin 13."
                ),
                aliases=("multiplexer", "mux", "analog")),
    CatalogPart("cd4011", "CD4011B", "ic", "dip-14", "Quad 2-input NAND gate, 3 to 18 V",
                _QUAD_GATE_4000, ref_prefix="U",
                source=f"TI CD4011B datasheet, E package; {_CD4000_NAMES}",
                check=_UNUSED_INPUTS, aliases=("4011", "nand", "logic gate", "mantık kapısı")),
    CatalogPart("cd4093", "CD4093B", "ic", "dip-14",
                "Quad 2-input NAND with Schmitt-trigger inputs, 3 to 18 V",
                _QUAD_GATE_4000, ref_prefix="U",
                source=f"TI CD4093B datasheet, E package; {_CD4000_NAMES}",
                check=_UNUSED_INPUTS, aliases=("4093", "nand", "schmitt")),
    CatalogPart("cd4013", "CD4013B", "ic", "dip-14",
                "Dual D flip-flop with set and reset, 3 to 18 V",
                _legs("Q1", "~Q1", "CLK1", "RESET1", "D1", "SET1", "VSS",
                      "SET2", "D2", "RESET2", "CLK2", "~Q2", "Q2", "VDD"),
                ref_prefix="U", source="TI CD4013B datasheet, E package",
                check=(
                    "SET and RESET are active high: tie both low on a flip-flop that should "
                    "clock. Wire Q-bar back to D and it divides its clock by two."
                ),
                aliases=("4013", "flip-flop", "divider")),
    CatalogPart("cd4060", "CD4060B", "ic", "dip-16",
                "14-stage binary counter with its own oscillator, 3 to 18 V",
                _legs("Q12", "Q13", "Q14", "Q6", "Q5", "Q7", "Q4", "VSS",
                      "PHO", "~PHO", "PHI", "RESET", "Q9", "Q8", "Q10", "VDD"),
                ref_prefix="U",
                source=(
                    "TI CD4060B datasheet, E package: 9 phi-O, 10 phi-O bar, 11 phi-I. KiCad's "
                    "4060, drawn from ST's M74HC4060, puts the bar on pin 9 instead; the pins "
                    "are the same pins"
                ),
                check=(
                    "An RC or a crystal on pins 9, 10 and 11 makes the clock (TI's figures 12 "
                    "and 13). Q1 to Q3 and Q11 are not brought out: Q4 is the first output. "
                    "RESET is active high: tie it low to count."
                ),
                aliases=("4060", "counter", "oscillator", "divider")),
    CatalogPart("cd4066", "CD4066B", "ic", "dip-14", "Quad analogue switch, 3 to 18 V",
                _legs("A1", "A2", "B2", "B1", "CTLB", "CTLC", "VSS",
                      "C1", "C2", "D2", "D1", "CTLD", "CTLA", "VDD"),
                ref_prefix="U",
                source=(
                    "TI CD4066B datasheet, N package; each switch's two ends named 1 (TI's "
                    "IN/OUT) and 2 (OUT/IN), and CTL its control"
                ),
                check=(
                    "A switch is on while its CTL pin is high. The signal has to stay between "
                    "VSS and VDD."
                ),
                aliases=("4066", "analog", "bilateral")),
    CatalogPart("ne5532", "NE5532", "ic", "dip-8",
                "Dual low-noise op-amp for audio, for a split supply",
                _legs("OUT1", "IN1-", "IN1+", "V-", "IN2+", "IN2-", "OUT2", "V+"),
                ref_prefix="U", source="TI NE5532 datasheet, P package",
                check=(
                    "Not a rail-to-rail part, and it wants about 10 V across it at least: on "
                    "one 5 V supply the LM358 is the one to use."
                )),
    CatalogPart("lm741", "LM741", "ic", "dip-8",
                "The classic single op-amp, for a split supply",
                _legs("NULL1", "IN-", "IN+", "V-", "NULL2", "OUT", "V+", "NC"),
                ref_prefix="U", source="TI LM741 datasheet, P package",
                check=(
                    "Pins 1 and 5 are for a 10k offset-trim pot and can stay open; pin 8 is "
                    "not connected. It needs a split supply of about +-5 V or more."
                )),
    CatalogPart("lm339", "LM339", "ic", "dip-14",
                "Quad comparator, open-collector outputs, single supply",
                _legs("OUT2", "OUT1", "VCC", "IN1-", "IN1+", "IN2-", "IN2+",
                      "IN3-", "IN3+", "IN4-", "IN4+", "GND", "OUT4", "OUT3"),
                ref_prefix="U", source="TI LM339 datasheet, N package",
                check=(
                    "VCC is pin 3 and GND pin 12, and OUT1 is pin 2, not 1. The outputs only "
                    "pull down: each one needs a pull-up resistor."
                )),
    CatalogPart("lm311", "LM311", "ic", "dip-8",
                "Comparator with an open-collector output and its emitter on a pin",
                _legs("EMIT", "IN+", "IN-", "V-", "BAL", "BAL/STRB", "COL", "V+"),
                ref_prefix="U", source="TI LM311 datasheet, P package",
                check=(
                    "For a logic output put pin 1 (the emitter) on ground and a pull-up on pin 7 "
                    "(the collector). V- is pin 4: on one supply, ground it too."
                )),
    # -- modules ----------------------------------------------------------------------
    # -- switches ----------------------------------------------------------
    # A push button's four legs are two strips of metal, and which two legs are one strip is
    # the whole of how it is wired: A and A are joined inside, B and B are joined inside,
    # and pressing it joins A to B. Numbered as KiCad's SW_PUSH footprints (pins 1 and 2 the
    # switched pair), so a netlist's switch lands on them as drawn.
    CatalogPart("tact-6x6", "Tactile switch 6x6 mm", "switch", "sw-tactile-6x6",
                "Momentary push button, legs 6.5 x 4.5 mm",
                (("1", "A"), ("2", "B"), ("3", "A"), ("4", "B")), ref_prefix="SW",
                value="6x6 tactile",
                source="Omron B3F datasheet terminal arrangement; KiCad Button_Switch_THT:SW_PUSH_6mm",
                check=_SWITCH_LEGS),
    CatalogPart("tact-12x12", "Tactile switch 12x12 mm", "switch", "sw-tactile-12x12",
                "Momentary push button, legs 12.5 x 5.0 mm",
                (("1", "A"), ("2", "B"), ("3", "A"), ("4", "B")), ref_prefix="SW",
                value="12x12 tactile",
                source="KiCad Button_Switch_THT:SW_PUSH-12mm and the Wuerth 430476085716 model",
                check=_SWITCH_LEGS),
    # -- relays
    # The 4 x 4 membrane keypad's ribbon ends in a 0.1 inch socket, so on the board it is the
    # header that socket goes on. Numbered as Parallax numbers it, right to left with the keys
    # facing you; its figure 1 says which lead is which row and column.
    CatalogPart("keypad-4x4", "4x4 membrane keypad (on a header)", "switch", "hdr-1x8",
                "Sixteen keys in four rows and four columns, eight leads",
                _legs("C4", "C3", "C2", "C1", "R4", "R3", "R2", "R1"),
                value="4x4 keypad", ref_prefix="J",
                source=(
                    "Parallax 4x4 Matrix Membrane Keypad (#27899) datasheet v1.2, figure 1: "
                    "pins 1 to 4 the columns from the A-B-C-D column, 5 to 8 the rows from the "
                    "bottom row"
                ),
                check=(
                    "Seen from the front its leftmost lead is R1 and its rightmost C4. Other "
                    "makers' keypads are usually wired the same: test one key with a meter "
                    "before trusting a clone."
                ),
                aliases=("keypad", "tuş takımı", "membrane", "matrix keypad")),
    # -- relays -----------------------------------------------------------------------
    CatalogPart("srd-05vdc-sl-c", "Songle SRD-05VDC-SL-C relay", "relay", "relay-srd",
                "SPDT relay, 5 V coil of 70 ohm, contacts 10 A at 125 V AC",
                _SRD_LEGS, value="SRD-05VDC-SL-C", source=_SRD_SOURCE, check=_SRD_CHECK),
    CatalogPart("srd-12vdc-sl-c", "Songle SRD-12VDC-SL-C relay", "relay", "relay-srd",
                "SPDT relay, 12 V coil of 400 ohm, contacts 10 A at 125 V AC",
                _SRD_LEGS, value="SRD-12VDC-SL-C", source=_SRD_SOURCE, check=_SRD_CHECK),
    # -- connectors -------------------------------------------------------------------
    CatalogPart("servo-header", "Servo header", "connector", "hdr-1x3",
                "Three header pins for a hobby servo's plug: PWM, + in the middle, -",
                _legs("PWM", "+", "-"), value="SERVO",
                source=(
                    "TowerPro SG90 datasheet: orange PWM, red +, brown -, the + in the middle "
                    "as on Futaba, Hitec and JR plugs"
                ),
                check=(
                    "Turned round, PWM and - swap and the servo does nothing. Feed it from its "
                    "own 5 V, not from a board's regulator pin."
                ),
                aliases=("servo", "SG90", "motor")),
    # -- sound ------------------------------------------------------------------------
    CatalogPart("buzzer-active-12mm", "Active buzzer 12 mm", "sound",
                "box-2x1-p3-r1-12x12x9.5",
                "Beeps on DC, 12 mm across and 9.5 mm tall, legs 7.6 mm apart",
                _legs("+", "-"), value="Buzzer",
                source=(
                    "KiCad Buzzer_Beeper:Buzzer_12x9.5RM7.6 (pad 1 is +, as Device:Buzzer "
                    "pin 1); drawn as the 12 mm square its round body sits in"
                ),
                check=(
                    "An ACTIVE buzzer is sealed underneath; a PASSIVE one shows its board "
                    "there and needs a tone, not DC. The longer leg, under the + on top, is +."
                ),
                aliases=("beeper", "piezo", "alarm")),
    CatalogPart("buzzer-passive-12mm", "Passive buzzer 12 mm", "sound",
                "box-2x1-p3-r1-12x12x8.5",
                "Sounds only when driven with a tone, 12 mm across, legs 7.6 mm apart",
                _legs("+", "-"), value="Passive buzzer", ref_prefix="BZ",
                source=(
                    "CUI CEM-1203(42) magnetic transducer: 12 mm across and 8.5 mm tall, "
                    "externally driven at 2048 Hz from 3 to 5 V; the legs as KiCad's "
                    "Buzzer_Beeper:Buzzer_12x9.5RM7.6"
                ),
                check=(
                    "A PASSIVE buzzer is silent on DC: drive it with a square wave from a pin "
                    "(tone() on an Arduino). Its board shows underneath, which is how to tell "
                    "it from an active one."
                ),
                aliases=("speaker", "hoparlör", "beeper", "piezo")),
    CatalogPart("esp32-devkitc", "ESP32-DevKitC V4", "module",
                "mod-2x19-p10-r1-27.94x54.3x3.5-s8.5-o0x-3",
                "ESP32-WROOM-32 dev board, 38 pins, rows 25.4 mm apart",
                _two_columns(_DEVKITC_LEFT, _DEVKITC_RIGHT), ref_prefix="U",
                source=(
                    "Espressif ESP32-DevKitC V4 user guide (J2/J3 pin tables) and "
                    "esp32_devkitc_v4_dimensions.dxf: board 27.94 x 48.26 mm, module "
                    "antenna 6.04 mm past it, pin rows 25.4 mm apart"
                ),
                check=(
                    "Clones called 'ESP32 DevKit' come with 30 or 38 pins and more than one "
                    "row spacing: count your pins and measure across the rows. "
                    + _MODULE_TOP
                )),
    CatalogPart("esp32-c3-devkitm-1", "ESP32-C3-DevKitM-1", "module",
                "mod-2x15-p9-r1-25.4x44.31x3.5-s8.5-o0x-2.7",
                "ESP32-C3 dev board, 30 pins, rows 22.86 mm apart",
                _two_columns(_C3_DEVKITM_LEFT, _C3_DEVKITM_RIGHT), ref_prefix="U",
                source="KiCad RF_Module:ESP32-C3-DevKitM-1 footprint and symbol",
                check=_MODULE_TOP),
    CatalogPart("arduino-nano", "Arduino Nano", "module",
                "mod-2x15-p6-r1-17.78x45.72x4-s8.5-o0x1.27",
                "ATmega328P board, 30 pins, rows 15.24 mm apart",
                _two_columns(_NANO_LEFT, _NANO_RIGHT), ref_prefix="U",
                source="KiCad Module:Arduino_Nano footprint and MCU_Module:Arduino_Nano_v3.x",
                check="The 6-pin ICSP header, if fitted, stands taller. " + _MODULE_TOP),
    CatalogPart("raspberry-pi-pico", "Raspberry Pi Pico", "module",
                "mod-2x20-p7-r1-21x52.3x3.5-s8.5-o0x-0.65",
                "RP2040 board, 40 pins, rows 17.78 mm apart",
                _two_columns(_PICO_LEFT, _PICO_RIGHT), ref_prefix="U",
                source=(
                    "KiCad Module:RaspberryPi_Pico_Common_THT footprint; pin names from the "
                    "Raspberry Pi Pico datasheet pinout"
                ),
                check=_MODULE_TOP),
    CatalogPart("pololu-a4988", "Pololu A4988 carrier", "module",
                "mod-2x8-p5-r1-15.24x20.32x2-s8.5",
                "Stepper motor driver, 8-35 V, 1 A per coil (2 A with cooling), rows 12.7 mm apart",
                _two_columns(_POLOLU_A4988_LEFT, _POLOLU_A4988_RIGHT), ref_prefix="U",
                value="Pololu A4988",
                source=(
                    "Pololu item 1182: 0.6 x 0.8 inch board and its pinout from the dimension "
                    "diagram, voltages and currents from its specifications; pin positions "
                    "KiCad Module:Pololu_Breakout-16_15.2x20.3mm"
                ),
                check=(
                    "Set the current limit with the trimmer before a motor is connected. The "
                    "red and green StepStick boards sold as A4988 have these pins and not "
                    "this layout. " + _MODULE_TOP
                )),
    CatalogPart("pololu-drv8825", "Pololu DRV8825 carrier", "module",
                "mod-2x8-p5-r1-15.24x20.32x2-s8.5",
                "Stepper motor driver, 8.2-45 V, 1.5 A per coil (2.2 A with cooling), rows "
                "12.7 mm apart",
                _two_columns(_POLOLU_DRV8825_LEFT, _POLOLU_DRV8825_RIGHT), ref_prefix="U",
                value="Pololu DRV8825",
                source=(
                    "Pololu item 2133: 0.6 x 0.8 inch board and its pinout from the dimension "
                    "diagram, voltages and currents from its specifications; pin positions "
                    "KiCad Module:Pololu_Breakout-16_15.2x20.3mm"
                ),
                check="Set the current limit with the trimmer before a motor is connected. "
                + _MODULE_TOP),
    CatalogPart("seeed-xiao-esp32c3", "Seeed XIAO ESP32C3", "module",
                "mod-2x7-p6-r1-17.78x21x3.2-s8.5",
                "ESP32-C3 board, 14 pins, rows 15.24 mm apart",
                _two_columns(_XIAO_LEFT, _XIAO_RIGHT), ref_prefix="U", value="XIAO ESP32C3",
                source=(
                    "Seeed XIAO ESP32C3 v1.3 KiCad board: the 21 x 17.78 mm outline, the "
                    "header rows and their nets; pin functions from Seeed's pin map"
                ),
                check="The USB-C socket stands about 1.8 mm past the end of the board. "
                + _MODULE_TOP),
    CatalogPart("wemos-d1-mini", "WEMOS D1 mini", "module",
                "mod-2x8-p9-r1-25.6x34.2x3.5-s8.5",
                "ESP8266 board, 16 pins, rows 22.86 mm apart",
                _two_columns(_D1_MINI_LEFT, _D1_MINI_RIGHT), ref_prefix="U",
                source="KiCad RF_Module:WEMOS_D1_mini_light footprint and WEMOS_D1_mini symbol",
                check=_MODULE_TOP),
    # Two radios nobody publishes a drawing of the parts on, so they are drawn as the plain
    # block (tests/test_module_art.py names them): the pins and the board are measured, what
    # stands on the board is not claimed.
    CatalogPart("nrf24l01", "nRF24L01+ module", "module",
                "mod-2x4-p1-r1-29x15.25x2-s8.5-o11.73x1.82",
                "2.4 GHz radio on SPI, 1.9 to 3.6 V, the board with its antenna printed on it",
                _two_columns(("GND", "CE", "SCK", "MISO"), ("VCC", "CSN", "MOSI", "IRQ")),
                value="nRF24L01+", ref_prefix="U",
                source=(
                    "KiCad RF_Module:nRF24L01_Breakout footprint (the 2 x 4 header and the 29 x "
                    "15.25 mm board) and RF:NRF24L01_Breakout symbol (the names)"
                ),
                check=(
                    "VCC is 3.3 V at most -- 5 V kills it -- though its inputs take 5 V logic. The "
                    "version with an amplifier and an antenna socket has these pins on a longer "
                    "board. Drawn as a plain block: what stands on its board is not drawn, only "
                    "the room it takes."
                ),
                aliases=("radio", "wireless", "2.4 GHz")),
    CatalogPart("esp-01", "ESP-01 (ESP8266 module)", "module",
                "mod-4x2-p1-r1-14.4x24.7x2-s8.5-o-0.11x-9.58",
                "Wi-Fi on an ESP8266, 3.3 V: serial, two GPIOs, enable and reset on 8 pins",
                _legs("GND", "IO2", "IO0", "RXD", "TXD", "EN", "RST", "VCC"),
                value="ESP-01", ref_prefix="U",
                source=(
                    "Ai-Thinker ESP-01/07/12 Series Modules User's Manual V1.3: figure 2.1 (the "
                    "pins and the 14.4 x 24.7 mm board) and table 2.2 (the names), which agree "
                    "pin for pin, as does the numbering of KiCad RF_Module:ESP-01"
                ),
                check=(
                    "3.3 V only. EN (CH_PD) must be high for it to run, and IO0 low as it starts "
                    "puts it in download mode (Ai-Thinker's table 2.3). The ESP-01S is pinned "
                    "the same. Drawn as a plain block: what stands on its board is not drawn, "
                    "only the room it takes."
                ),
                aliases=("ESP-01S", "ESP8266", "wifi")),
    # Pads, not header pins, at the four corners: IN on one end and OUT on the other, + on
    # the trimmer's side. Its layout in ``ui/moduleart.py`` is Handsontec's drawing.
    CatalogPart("lm2596-module", "LM2596 buck module", "module",
                "mod-2x2-p16-r7-43.18x21.08x12-s5",
                "Step-down converter on the LM2596: up to 40 V in, from 1.25 V out, set by "
                "its trimmer",
                (("1", "IN+"), ("2", "OUT+"), ("3", "IN-"), ("4", "OUT-")),
                value="LM2596 module", ref_prefix="U",
                source=(
                    "Handsontec LM2596S module drawing: board 43.18 x 21.08 mm, pads 39.50 x "
                    "17.15 mm apart; TI LM2596 datasheet: 40 V in, 1.23 to 37 V out, 3 A"
                ),
                check=(
                    "Its pads are 39.5 x 17.15 mm apart, not on the 2.54 mm grid: stand it on "
                    "pins bent about 0.6 mm to the holes drawn, or wire it. Set the output "
                    "with the trimmer before anything is connected to it; its input "
                    "capacitor's rating, often 35 V, is its real limit."
                ),
                aliases=("buck", "step-down", "DC-DC", "voltage regulator")),
    CatalogPart("sparkfun-tb6612fng", "SparkFun TB6612FNG motor driver", "module",
                "mod-2x8-p6-r1-20.32x20.32x2-s8.5",
                "Two DC motors, 2.5 to 13.5 V, 1 A each (3.2 A peak), rows 15.24 mm apart",
                _two_columns(_TB6612_LEFT, _TB6612_RIGHT), ref_prefix="U",
                value="SparkFun TB6612FNG",
                source=(
                    "SparkFun Motor Driver - Dual TB6612FNG v1.1c Eagle board: the 0.8 x 0.8 "
                    "inch board, the header rows and their nets; Toshiba TB6612FNG datasheet: "
                    "VM 2.5 to 13.5 V, VCC 2.7 to 5.5 V, 1 A per channel, 3.2 A peak"
                ),
                check=(
                    "STBY is pulled low inside the chip: drive it high or neither motor turns. "
                    "VCC is the logic's supply, 2.7 to 5.5 V; VM is the motors'. " + _MODULE_TOP
                ),
                aliases=("motor driver", "H-bridge", "DC motor")),
    CatalogPart("pololu-drv8833", "Pololu DRV8833 carrier", "module",
                "mod-2x8-p4-r1-12.7x20.32x2-s8.5",
                "Two DC motors or one stepper, 2.7 to 10.8 V, 1.2 A per channel (2 A peak), "
                "rows 10.16 mm apart",
                _two_columns(_DRV8833_LEFT, _DRV8833_RIGHT), ref_prefix="U",
                value="Pololu DRV8833",
                source=(
                    "Pololu item 2130: the 0.5 x 0.8 inch board from the dimension diagram, "
                    "the pins from the pinout picture, voltages and currents from its "
                    "specifications"
                ),
                check=(
                    "VMM is the motor supply after the board's reverse-protection MOSFET: an "
                    "output, not a second input. AISEN and BISEN are joined to GND on the board "
                    "until the traces are cut for sense resistors. " + _MODULE_TOP
                ),
                aliases=("motor driver", "H-bridge", "DC motor", "stepper")),
)

_BY_ID: dict[str, CatalogPart] = {part.id: part for part in CATALOG}


def catalog_part(part_id: str) -> CatalogPart | None:
    """One part by its id, or ``None``."""
    return _BY_ID.get(part_id.strip().lower())


#: A maker's letters in front of a part number, as a bag or a value prints them: SN74HC595N
#: is TI's 74HC595 and L7805CV is ST's 7805. The importer's list (``parsers.kicad_parts``)
#: and TI's SN, which a search box meets more often than a netlist does.
_MAKER_PREFIX = re.compile(r"^(?:sn|lm|mc|ua|ka|l)(?=\d)")


def _squeezed(text: str) -> str:
    """Letters and digits only: "HC-SR04", "hc sr04" and "HCSR04" are one word, and
    "+3.3 V" is "33v"."""
    return re.sub(r"[\W_]+", "", text)


def part_matches(
    part: CatalogPart,
    text: str,
    *,
    also: str = "",
    fold: Callable[[str], str] = str.lower,
) -> bool:
    """Whether every word of ``text`` finds this part -- the one answer for the MCP
    server's ``list_catalog`` and the window's Parts panel, which passes the summary and
    the heading in its own language as ``also`` and its own ``fold`` for the Turkish i.

    A word finds a part three ways, because a search box is typed by somebody holding the
    part or reading a parts list:

    * it is IN what the part says about itself -- id, name, kind, aliases, summary;
    * it is in there once punctuation and spaces are taken out of both, so "opamp" finds
      "op-amp" and "5v" finds "+5 V";
    * it is the part's NUMBER with a package or a maker's letters on: "LM358N", "NE555P",
      "SN74HC595N". What follows the number may not be another digit, so an LM350 is not
      an LM35 -- the importer's rule (``parsers.kicad_parts.catalog_part_for``).
    """
    return _finds(part, text, (part.summary, also), fold)


def names_part(part: CatalogPart, text: str, *, fold: Callable[[str], str] = str.lower) -> bool:
    """Whether every word of ``text`` finds this part in what it is CALLED -- id, name, kind
    and aliases -- and not only in what its summary says about it. "switch" names a push
    button and is merely a word in a 2N2222A's "switching", and the button is what somebody
    typing it wants first.

    A word names a part only from the START of one of those words: "led" is inside "SSD1306
    OLED" and names no display, the rule the Add a Part dialog's Enter keeps
    (``ui.main.typed_names``)."""
    return _finds(part, text, (), fold, starts=True)


#: Words for a kind of part that its parts' names and summaries do not say: nothing in a
#: 7805's "Linear regulator, +5 V" says VOLTAGE regulator, which is what is typed.
_CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "regulator": ("voltage regulator", "voltaj regülatörü"),
    # A push button is a "Tact buton" in Turkish and an "anahtar" to somebody looking for
    # one, which is also the word in a switching transistor's Turkish summary.
    "switch": ("anahtar",),
}


def _finds(
    part: CatalogPart,
    text: str,
    said: tuple[str, ...],
    fold: Callable[[str], str],
    *,
    starts: bool = False,
) -> bool:
    words = fold(text).split()
    if not words:
        return True
    kind = (part.category, *_CATEGORY_WORDS.get(part.category, ()))
    haystack = fold(" ".join((part.id, part.name, *kind, *part.aliases, *said)))
    squeezed = _squeezed(haystack)
    # Where each word of the haystack begins once it is squeezed, for ``starts``.
    begins: set[int] = set()
    at = 0
    for token in haystack.split():
        begins.add(at)
        at += len(_squeezed(token))
    numbers = {_squeezed(fold(number)) for number in (part.id, part.placed_value)}
    numbers = {number for number in numbers if len(number) >= 4}
    return all(
        _word_finds(word, haystack, squeezed, numbers, begins if starts else None)
        for word in words
    )


def _word_finds(
    word: str, haystack: str, squeezed: str, numbers: set[str], begins: set[int] | None
) -> bool:
    if begins is None:
        if word in haystack:
            return True
    elif re.search(rf"(?<!\w){re.escape(word)}", haystack):
        return True
    plain = _squeezed(word)
    # A word that is all punctuation -- a lone "-" -- says nothing to look for.
    if not plain:
        return True
    if begins is None:
        if plain in squeezed:
            return True
    elif any(squeezed.startswith(plain, index) for index in begins):
        return True
    # An ordering code after a hyphen is the same part: ATtiny85-20PU is an ATtiny85, whose
    # "20" would otherwise read as more of its number.
    ordered = re.split(r"[\W_]+", word.strip("-"), maxsplit=1)[0]
    for form in dict.fromkeys((plain, _MAKER_PREFIX.sub("", plain), ordered)):
        for number in numbers:
            if form.startswith(number) and not form[len(number) : len(number) + 1].isdigit():
                return True
    return False


def search_catalog(text: str = "", category: CatalogCategory | None = None) -> list[CatalogPart]:
    """Parts every word of ``text`` finds (``part_matches``): those it NAMES first
    (``names_part``), then the rest, each in catalog order."""
    found = [
        part
        for part in CATALOG
        if (category is None or part.category == category) and part_matches(part, text)
    ]
    return sorted(found, key=lambda part: not names_part(part, text))
