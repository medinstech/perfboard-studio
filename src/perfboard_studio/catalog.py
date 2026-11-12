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
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from .model import PartSymbol, PerfDocument, PinNames
from .system import references_in_use

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
    """The first unused reference with this prefix, across every board, the design and
    the cables -- a reference is unique across all of them (``commands.assert_ref_free``)."""
    used = references_in_use(document)
    index = 1
    while f"{prefix}{index}" in used:
        index += 1
    return f"{prefix}{index}"


#: What every module on a cable says last (``guide.plugs_in_on_a_cable``): its header's
#: order is the one documented, and the names are what count.
_CABLED_CHECK = (
    "Match each lead to the name printed beside the module's pins, not to its place: "
    "sellers' boards are not all wired in the same order."
)

#: The wire-to-board headers (``footprints.WIRE_TO_BOARD_FAMILIES``): JST XH, whose 2.50 mm
#: goes into a 0.1 in board's holes up to ``pins_on_the_grid`` pins, and the Molex KK 254 a
#: KF2510 is a copy of, on the grid's own pitch.
_XH_SUMMARY_TOP = "A 2.50 mm wire-to-board header for a crimped JST XH plug, from above. On a 2.54 mm board it goes in up to 4 pins"
_XH_SUMMARY_SIDE = "A 2.50 mm wire-to-board header for a crimped JST XH plug, from the side. On a 2.54 mm board it goes in up to 4 pins"
_XH_CHECK = "Its pins are 2.50 mm apart and the holes 2.54: press it in square and solder the two end pins first. The plug goes in one way round, so turned half round its first wire lands on the last pin."
_KK_SUMMARY = "A 2.54 mm wire-to-board header for a crimped Molex KK 254 or KF2510 plug, from above"
_KK_CHECK = "KF2510 headers are KK 254 clones and take the same plugs. The plug goes in one way round, so turned half round its first wire lands on the last pin."
_ON_THE_GRID = (
    "its 0.64 mm posts go into 1.0 mm holes 2.54 mm apart up to 4 pins "
    "(footprints.pins_on_the_grid)"
)
_XH_WORDS = ("JST", "XH", "JST-XH", "XH2.54", "XH2.5", "wire-to-board", "connector",
             "konnektör", "JST konnektör")
_KK_WORDS = ("Molex", "KK", "KK254", "KK 254", "KF2510", "2510", "wire-to-board",
             "connector", "konnektör")


# SparkFun's Arduino Pro Mini 328, its silkscreen read off its Eagle board, the FTDI end
# up: TXO down to 9 on one row, RAW down to 10 on the other (printed as bare numbers,
# named here D2 ... D13 as the Nano's are).
_PRO_MINI_LEFT = ("TXO", "RXI", "RST", "GND", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9")
_PRO_MINI_RIGHT = ("RAW", "GND", "RST", "VCC", "A3", "A2", "A1", "A0", "D13", "D12", "D11", "D10")


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
# The 30-pin ESP32 DevKit V1 as its silkscreen names the pins, the antenna end up: EN down
# to VIN on one row, D23 down to 3V3 on the other -- the order every clone keeps.
_DEVKIT_V1_LEFT = ("EN", "VP", "VN", "D34", "D35", "D32", "D33", "D25", "D26", "D27", "D14", "D12", "D13", "GND", "VIN")
_DEVKIT_V1_RIGHT = ("D23", "D22", "TX0", "RX0", "D21", "D19", "D18", "D5", "TX2", "RX2", "D4", "D2", "D15", "GND", "3V3")
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
# The NodeMCU DevKit 1.0, as its silkscreen and its schematic's IO CONN sheet name the
# pins, the antenna end up: A0 down to VIN on one row, D0 down to 3V3 on the other.
_NODEMCU_LEFT = ("A0", "RSV", "RSV", "SD3", "SD2", "SD1", "CMD", "SD0", "CLK", "GND", "3V3", "EN", "RST", "GND", "VIN")
_NODEMCU_RIGHT = ("D0", "D1", "D2", "D3", "D4", "3V3", "GND", "D5", "D6", "D7", "D8", "RX", "TX", "GND", "3V3")
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
#: on the board, so the one chosen is the one in hand. A module on its header, seated in a
#: female one 8.5 mm up, the four pins along one edge 2 mm in from it, as tall in all as the
#: box it replaced (``footprints.SUPERSEDED_FOOTPRINTS``); what is on it is measured on a
#: photograph of one (``ui/moduleart.py``).
_OLED_FOOTPRINT = "mod-4x1-p1-r1-27.3x27.8x2.1-s8.5-o0x12.45"
_OLED_SOURCE = (
    "The four names as the board prints them; the 27.3 x 27.8 mm board as sellers list it; "
    "the controller, Solomon Systech's SSD1306; on its header as a module, the 12.2 mm it "
    "stands an estimate"
)
_OLED_CHECK = (
    "Read the four names printed on yours: this board is sold with VCC and GND either way "
    "round, and the wrong way round kills it. Choose the entry with your order. The header "
    "is 1.45 mm in from the board's edge, measured on a photograph of one; how tall it "
    "stands in its socket is an estimate."
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
                _legs("+", "-"), value="9V", ref_prefix="BT", symbol="battery",
                source="Keystone 233 9 V battery snap: red and black 26 AWG leads, 6 in",
                check=(
                    "Red is +. If both leads of yours are one colour, find + with a meter on "
                    "the battery before soldering."
                ),
                aliases=(*_POWER_WORDS, "batarya", "PP3", "9V")),
    CatalogPart("battery-aa-holder", "AA battery holder", "power", "wire-2",
                "Two to four AA or AAA cells in series, on two leads",
                _legs("+", "-"), value="AA holder", ref_prefix="BT", symbol="battery",
                source="Keystone 2463 2 x AA holder: red and black 26 AWG leads, 150 mm",
                check=(
                    "Red is + and black is -. With no colours, measure across it with the "
                    "cells in."
                ),
                aliases=(*_POWER_WORDS, "batarya", "AAA")),
    CatalogPart("dc-jack-panel", "DC barrel jack 5.5 x 2.1 mm, panel mount", "power", "wire-2",
                "On the case, wired to the board from its centre pin and its sleeve",
                _legs("+", "-"), value="DC IN", symbol="jack",
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
    # Keystone's 20mm thru-hole holders sheet (datasheet.octopart.com/1026-Keystone-datasheet-
    # 10927550.pdf), the VERTICAL COMPACT drawing, Cat. No. 1067.
    CatalogPart("coin-holder-keystone-1067", "CR2032 coin cell holder, Keystone 1067 (vertical)",
                "power", "box-1x2-p1-r3-22.2x13.5x19.9",
                "Stands one 20 mm coin cell on edge: CR2032, CR2016, CL2025, DL2020",
                _legs("+", "-"), value="CR2032", ref_prefix="BT", symbol="battery",
                source=(
                    "Keystone Electronics' 20mm Thru-Hole Mount Coin Cell Holders sheet, the "
                    "VERTICAL COMPACT drawing, Cat. No. 1067: the body 22.2 mm wide and 19.9 mm "
                    "high, the two contact pins .300 in (7.6 mm) apart, 3 pitches here, in a "
                    "column through the middle of the body's width, one marked + and one - in "
                    "the Mounting Detail. The drawing's side view calls the body .531 in "
                    "and then 3.6 mm: the inches are used (13.5 mm), because the 7.6 mm "
                    "between the pins measures a little over half of that width on the same "
                    "drawing and 3.6 mm would be narrower than the pins' own spacing. The "
                    "holder's third leg, 1.57 mm round and 7.1 mm from the pin column, has no "
                    "hole on the 2.54 mm grid and is not drawn; this footprint is its two "
                    "contact pins"
                ),
                check=(
                    "The mounting leg sits 7.1 mm to one side of the pins and wants a hole of "
                    "its own, which the 2.54 mm grid does not have (the drawing gives 2.4 mm for "
                    "the pad and 1.57 mm for the leg): drill it. Match + and - to the marks "
                    "on the holder before soldering, not to the order here."
                ),
                aliases=(*_POWER_WORDS, "CR2032", "coin cell", "button cell", "düğme pil",
                         "pil yuvası")),
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
                "A power lead. Its cable plugs into this 2-pin header: + - from pin 1",
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
    CatalogPart("ky-009-rgb-led", "KY-009 RGB LED module, SMD (on a header)", "led", "hdr-1x4",
                "RGB LED on a small board, one pin per colour and a common ground. Its "
                "cable plugs into this 4-pin header: GND G R B from pin 1",
                _legs("GND", "G", "R", "B"), value="KY-009", ref_prefix="J",
                source=(
                    "Joy-IT SensorKit X40 manual (16.06.2017, CC BY-NC-SA 3.0), the "
                    "KY-009 Pinout page, pin names and order only: GND, LED Green, LED "
                    "Red, LED Blue"
                ),
                check=(
                    "Green comes before red here: the KY-016 puts red first, so the two "
                    "boards are not interchangeable on one header. The manual lists a "
                    "series resistor for each colour, 100 ohm for green and blue and 180 "
                    "ohm for red, at 3.3 V and at 5 V: look at your board for resistors "
                    "before driving it. "
                    + _CABLED_CHECK
                ),
                aliases=("KY-009 RGB LED", "RGB LED module", "SMD RGB module",
                         "RGB LED modülü",)),
    CatalogPart("ky-016-rgb-led", "KY-016 RGB LED module, 5 mm (on a header)", "led", "hdr-1x4",
                "RGB 5 mm LED on a small board, one pin per colour and a common ground. "
                "Its cable plugs into this 4-pin header: GND R G B from pin 1",
                _legs("GND", "R", "G", "B"), value="KY-016", ref_prefix="J",
                source=(
                    "Joy-IT SensorKit X40 manual (16.06.2017, CC BY-NC-SA 3.0), the "
                    "KY-016 Pinout page, pin names and order only: GND, LED Red, LED "
                    "Green, LED Blue"
                ),
                check=(
                    "Red comes before green here: the KY-009 puts green first, so the two "
                    "boards are not interchangeable on one header. The manual lists a "
                    "series resistor for each colour, 100 ohm for green and blue and 180 "
                    "ohm for red, at 3.3 V and at 5 V: look at your board for resistors "
                    "before driving it. "
                    + _CABLED_CHECK
                ),
                aliases=("KY-016 RGB LED", "RGB LED module", "5mm RGB module",
                         "RGB LED modülü",)),
    CatalogPart("ky-011-two-colour-led", "KY-011 / KY-029 two-colour LED module (on a header)", "led", "hdr-1x3",
                "Red and green LED on a small board, one pin per colour and a common "
                "ground. Its cable plugs into this 3-pin header: G R GND from pin 1",
                _legs("G", "R", "GND"), value="KY-011", ref_prefix="J",
                source=(
                    "Joy-IT SensorKit X40 manual (16.06.2017, CC BY-NC-SA 3.0), the "
                    "KY-011 and KY-029 Pinout pages, pin names and order only: LED Green, "
                    "LED Red, GND, the same on both"
                ),
                check=(
                    "KY-011 carries a 5 mm LED and KY-029 a 3 mm one; both are numbered "
                    "the same. For the KY-011 the manual gives a series resistor of 120 "
                    "ohm per colour at 3.3 V and 220 ohm per colour at 5 V: look at your "
                    "board for resistors before driving it. "
                    + _CABLED_CHECK
                ),
                aliases=("KY-011 two-colour LED", "KY-029 two-colour 3 mm LED",
                         "two-colour LED module", "red green LED module",
                         "iki renkli LED modülü",)),
    CatalogPart("ws2812b-strip", "WS2812B LED strip (on a header)", "led", "hdr-1x3",
                "Addressable RGB LED strip or ring. Its cable plugs into this 3-pin header: "
                "+5V DIN GND from pin 1",
                _legs("+5V", "DIN", "GND"), value="WS2812B", ref_prefix="J",
                source=(
                    "Worldsemi WS2812B datasheet (VDD, DIN, VSS; DOUT on to the next LED); the "
                    "strip's input pads 5V, DIN, GND, as Adafruit's NeoPixel Uberguide wires "
                    "them"
                ),
                check=(
                    "Its cable goes on the end its arrows point away from, DIN in. Adafruit puts "
                    "a 300 to 500 ohm resistor in DIN and 1000 uF across +5V and GND at the "
                    "strip. " + _CABLED_CHECK
                ),
                aliases=("NeoPixel", "WS2812", "addressable LED", "LED strip", "LED şerit",
                         "adreslenebilir LED")),
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
    # The pot every kit has, on the panel or the box's lid and wired to the board: the pads
    # its three wires land in (``wire-3``), declared a potentiometer so the sheet draws one.
    CatalogPart("pot-panel", "Potentiometer 16 mm, panel mount", "passive", "wire-3",
                "A panel pot off the board on its three wires: CCW end, wiper, CW end",
                _legs("CCW", "W", "CW"), "potentiometer", value="B10K", ref_prefix="RV",
                source=(
                    "Taiwan Alpha 16 mm metal shaft series (RV16): drawn in its full "
                    "counter-clockwise position, its travel runs from terminal 1 to terminal 3, "
                    "and terminal 2 is the wiper"
                ),
                check=(
                    "Seen from the shaft with its tags at the bottom, they are CCW, W and CW "
                    "from the left. If it turns the wrong way, swap the CCW and CW wires, not "
                    "the wiper. Put its value, printed as B10K or A10K, in the value: B is "
                    "linear, A is the log taper a volume control wants."
                ),
                aliases=("potentiometer", "pot", "volume", "knob", "WH148", "RV16",
                         "potansiyometre")),
    # The 9 mm pot of the kits, on the board with its shaft pointing up. Drawn at its LUGS,
    # not its frame: 10.6 mm across, so DRC measures what the board has to make room for.
    CatalogPart("rv09-pot", "RV09 potentiometer, 9 mm", "passive",
                "box-3x1-p1-r1-10.6x12.5x20-o0x-6.25",
                "Potentiometer with a 6 mm shaft standing 20 mm above the board: end, wiper, "
                "end, in a row of three pins",
                _legs("1", "W", "3"), "potentiometer", value="B10K", ref_prefix="RV",
                source=(
                    "Alps RK09K series drawing (Alps catalogue p.370, "
                    "mikrocontroller.net/attachment/74244/B400_ALPS-RK09K.pdf), read at high "
                    "zoom: pins 1, 2, 3 2.5 mm apart, the two lugs 10.6 mm outer to outer and "
                    "7 mm from the pin row, the frame 5.5 mm past the shaft's axis, the shaft "
                    "LM1 = 20 mm above the mounting surface, pins 3.2 mm and lugs 3.8 mm below "
                    "it. ASSUMPTION: the kit clones sold as RV09 follow the Alps RK09K pattern; "
                    "none of them publishes a drawing of its own, so measure yours against "
                    "this one. The 2.5 mm pin pitch against the board's 2.54 leaves the end "
                    "pins 0.04 mm off their holes, as the JST XH's does"
                ),
                check=(
                    "Snip the two lugs off flush with the frame before you solder it. They are "
                    "3.8 mm long against the pins' 3.2, so left on they hold the frame 0.6 mm "
                    "clear of the board and the pins stop short of the holes. The pins' 2.5 mm "
                    "pitch against the board's 2.54 puts the end pins 0.04 mm off their holes, "
                    "inside what a 1 mm hole has to spare. Its value is printed on it as B10K "
                    "or A10K: B is linear, A the log taper of a volume control."
                ),
                aliases=("potentiometer", "pot", "RV09", "RK09K", "9 mm pot", "volume",
                         "potansiyometre")),
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
    # The low-profile crystal that goes next to an ATmega or ATtiny on a perfboard, drawn at
    # Abracon's MAXIMA (11.5 x 5.0 x 3.5 mm) so DRC measures no smaller a part than the one in
    # the bag. NOT the tall HC-49/U of the ``xtal-hc49`` footprint: that can is 13.46 mm high.
    CatalogPart("crystal-hc49us", "Crystal, low can HC-49/S (HC-49/US)", "passive",
                "box-2x1-p2-r1-11.5x5x3.5",
                "Quartz crystal for a microcontroller's clock, the low can that comes in kits, "
                "3.5 mm tall, legs 4.88 mm apart",
                value="16MHz", ref_prefix="Y",
                source=(
                    "Abracon ABL series (HC49/US) datasheet, mechanical dimensions, read from "
                    "abracon.com/Resonators/ABL.pdf: can 11.5 mm long (10.3 mm without its "
                    "flange), 5.0 mm across, 3.5 mm high, legs 0.457 mm across and 4.88 +-0.20 "
                    "mm apart, 5.5 mm long at the least in bulk"
                ),
                check=(
                    "This is the LOW can, 3.5 mm tall, the one in most kits (HC-49/S, "
                    "HC-49/US); the tall HC-49/U, 13.46 mm, is the other entry. "
                    "Its legs are 4.88 mm apart against the board's 5.08 two holes over, so each "
                    "ends 0.10 mm off its hole, 0.20 mm at the drawing's worst, inside the "
                    "0.27 mm a 0.457 mm leg has to spare in a 1 mm hole. Its frequency is "
                    "printed on the can: put it in the value. Abracon sells an insulator tab "
                    "as an option, so a bare can is metal: keep it off bare copper."
                ),
                aliases=("crystal", "xtal", "quartz", "HC-49S", "HC49S", "16 MHz", "kristal")),

    # The TALL can, on the registry's ``xtal-hc49`` footprint: 13.46 mm high, standing on its
    # legs like a small tin. No maker drawing of it has been found: the can is the usual
    # published HC-49/U envelope and the footprint takes KiCad's HC-49/U model, so this is
    # the entry whose geometry a measurement of yours would settle.
    CatalogPart("crystal-hc49u", "Crystal, tall can HC-49/U", "passive", "xtal-hc49",
                "Quartz crystal for a microcontroller's clock, the tall can, 13.46 mm tall, "
                "legs 4.88 mm apart",
                value="16MHz", ref_prefix="Y",
                source=(
                    "The HC-49/U envelope as distributors print it (4.65 mm across, 13.46 mm "
                    "high) and KiCad's HC-49/U model for the 11.05 mm along its legs: some "
                    "makers print the length as 11.35 mm. No maker drawing was found, so "
                    "measure yours; the kit crystal is usually the low one, "
                    "``crystal-hc49us``"
                ),
                check=(
                    "This is the TALL can, 13.46 mm high. Most crystals in kits are the low one "
                    "(HC-49/S, HC-49/US), 3.5 mm: if yours is that, take the other entry. Its "
                    "legs are 4.88 mm apart against the board's 5.08 two holes over, so each "
                    "ends 0.10 mm off its hole. Its frequency is printed on the can: put it in "
                    "the value."
                ),
                aliases=("crystal", "xtal", "quartz", "HC-49", "HC49U", "tall crystal",
                         "16 MHz", "kristal")),
    # -- sensors ----------------------------------------------------------------------
    CatalogPart("lm35", "LM35", "sensor", "to92", "Temperature sensor, 10 mV per degree C",
                _legs("+VS", "VOUT", "GND"), ref_prefix="U",
                source=f"TI LM35 datasheet, LP package; {_TO92_ORDER}", check=_CHECK_LEGS),
    # The analog sensor of the official Arduino kit. Its datasheet draws the TO-92 from
    # BELOW, as the LM35's does, so the order is the same one read from the flat face.
    CatalogPart("tmp36", "TMP36", "sensor", "to92",
                "Temperature sensor, 750 mV at 25 degrees C and 10 mV for each degree, from "
                "2.7 V",
                _legs("+VS", "VOUT", "GND"), ref_prefix="U",
                source=(
                    "Analog Devices TMP35/36/37 datasheet (rev. F), figure 4: TO-92 seen from "
                    "below, pin 1 +VS, pin 2 VOUT, pin 3 GND; read from the copy at "
                    "dept.aem.umn.edu/~./faculty/flaten/ArduinoIntroSlides/Data Sheets/"
                    "TMP35_36_37.pdf, the maker's page being analog.com/TMP36; "
                    f"{_TO92_ORDER}"
                ),
                check=(
                    "It reads 500 mV at 0 degrees C and rises 10 mV a degree, so subtract the "
                    "500 mV before dividing by 10. Its datasheet draws the legs from below, so "
                    "from the left with the flat face towards you they are +VS, VOUT, GND. "
                    + _CHECK_LEGS
                ),
                aliases=("temperature sensor", "sıcaklık sensörü")),
    # The bare Vishay TCRT5000, an IR LED and a phototransistor in one housing. Its pins
    # are numbered here row by row, as a generated box's are: Vishay's footprint top view
    # has Coll. and A on one row and E and Cath. on the other, 5.5 mm across.
    CatalogPart("tcrt5000", "TCRT5000", "sensor", "box-2x2-p2-r1-10.3x5.9x7.2",
                "Reflective IR sensor: an IR LED and a phototransistor side by side, seeing 0.2 "
                "to 15 mm, best at 2.5",
                _legs("C", "A", "E", "K"), ref_prefix="U",
                source=(
                    "Vishay TCRT5000 datasheet (83760, rev 1.7): footprint top view, Coll. and A "
                    "on one row and E and Cath. on the other, 5.5 mm across and 2.54 along; "
                    "body 10.2 x 5.8 x 7 mm, +0.1/+0.1/+0.2; KiCad 10 "
                    "OptoDevice:Vishay_TCRT5000 for the model"
                ),
                check=(
                    "Its legs are 5.5 mm apart across and the holes 5.08: bend them in a little. "
                    "Its two snap-in clips are for 2.5 mm holes, so cut them off or let it stand "
                    "on them. The blue dome is the LED (A, K), which needs its series resistor; "
                    "the black one is the phototransistor (C, E)."
                ),
                aliases=("TCRT5000L", "reflective sensor", "IR sensor", "line sensor",
                         "line follower", "optical sensor", "kızılötesi sensör",
                         "çizgi sensörü")),
    CatalogPart("ds18b20", "DS18B20", "sensor", "to92",
                "Temperature sensor, 1-Wire, needs a 4.7k pull-up on DQ",
                _legs("GND", "DQ", "VDD"), ref_prefix="U",
                source=f"Analog Devices DS18B20 datasheet; {_TO92_ORDER}", check=_CHECK_LEGS,
                aliases=("one-wire",)),
    # The hall sensors come in Allegro's UA case, a flat 4.2 x 3.1 mm SIP with its legs
    # 1.27 mm apart: bent out to the grid and drawn as the TO-92 they are sold beside, a
    # little larger than they are, which is the side DRC can afford to be wrong on.
    CatalogPart("a3144", "A3144", "sensor", "to92",
                "Hall-effect switch: its open-collector output pulls low when a magnet comes "
                "close",
                _legs("VCC", "GND", "OUT"), ref_prefix="U",
                source=(
                    "Allegro A3141-A3144 datasheet (27621.6A), UA package: 1 supply, 2 ground, "
                    "3 output, seen from the branded face; Diodes AH1806-P in KiCad "
                    f"Sensor_Magnetic, the same three in the same order; {_TO92_ORDER}"
                ),
                check=(
                    "Its output only pulls low: give OUT a pull-up resistor to VCC. Only one "
                    "pole of a magnet switches it: if nothing happens, turn the magnet round. "
                    + _CHECK_LEGS
                ),
                aliases=("hall sensor", "magnet sensor", "3144", "KY-003", "hall sensörü")),
    CatalogPart("ss49e", "SS49E", "sensor", "to92",
                "Linear Hall-effect sensor: about 2.5 V with no field, about 1.8 mV per gauss "
                "at 5 V",
                _legs("VCC", "GND", "VOUT"), ref_prefix="U",
                source=(
                    "SS49E datasheet V2.00 (2008), 3-pin SIP (UA): 1 Vcc, 2 GND, 3 Vout, and "
                    "2.25 to 2.75 V out at no field; Allegro A1301xUA in KiCad "
                    f"Sensor_Magnetic, the same three in the same order; {_TO92_ORDER}"
                ),
                check=_CHECK_LEGS,
                aliases=("linear hall", "hall sensor", "magnetic field sensor", "49E", "KY-035",
                         "hall sensörü", "KY-024")),
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
    # wide as the board, as deep as it reaches -- the right-angle header's plastic 1.2 mm
    # behind the pins, the cans 12 mm out in front of the board (``moduleart.HC_SR04_BOARD``)
    # -- and 22.5 mm tall: the 20 mm board and 2.5 mm for its header's standoff, which is
    # not measured and errs on the tall side.
    CatalogPart("hc-sr04", "HC-SR04", "sensor", "box-4x1-p1-r1-45x16x22.5-o0x6.8",
                "Ultrasonic distance sensor, 2 cm to 4 m, 5 V; stands on its edge",
                _legs("VCC", "TRIG", "ECHO", "GND"), ref_prefix="U",
                source=(
                    "ElecFreaks HC-SR04 user guide: Vcc, Trig, Echo, GND left to right with "
                    "the transducers towards you; 45 x 20 x 15 mm; 5 V"
                ),
                check=(
                    "ECHO is a 5 V output: put a divider between it and a 3.3 V pin. The "
                    "transducers stand 12 mm out in front of the board and its header behind "
                    "it, as photographs of one show; how high the board stands on its pins is "
                    "an estimate."
                ),
                aliases=("ultrasonic", "sonar", "distance")),
    # The MPU-6050 board everybody sells: its eight names are printed on it and the same on
    # every one; nobody publishes a drawing of the board, so its size is the sellers'. VCC is
    # pin 1 at the anchor and the board stands ABOVE the row (``o0x-6.7``): seen from above,
    # a GY-521 with its header along the bottom edge reads VCC to INT left to right. Below
    # the row was its mirror image, and ``footprints.SUPERSEDED_FOOTPRINTS`` says so.
    # The PIR every kit has, on its three pins in a female header: its lens 16.3 mm over its
    # board, and its parts underneath clear of the board it plugs into.
    CatalogPart("hc-sr501", "HC-SR501 PIR motion sensor", "sensor",
                "mod-3x1-p1-r1-32x24x16.3-s8.5-o-0.7x9.2",
                "Passive infrared motion sensor: OUT goes to 3.3 V when something warm moves, "
                "for 5 s to 5 minutes",
                _legs("VCC", "OUT", "GND"), value="HC-SR501", ref_prefix="U",
                source=(
                    "TruSens HC-SR501 PIR Motion Detector sheet (Rapid 74-1108): +Power, "
                    "High/Low Output, GND on its underside, 5 to 20 V in and 3.3 V out, the "
                    "time 5 to 300 s; the board as moduleart's HC_SR501_MODULE measures it"
                ),
                check=(
                    "Feed it 5 to 20 V: below 5 V it does not work. Its two trimmers set how "
                    "long OUT stays high and how far it sees, 3 to 7 m, and its jumper whether "
                    "a new movement starts that time again (H) or not (L)."
                ),
                aliases=("PIR", "motion sensor", "SR501", "pyroelectric", "hareket sensörü")),
    # Adafruit's INA219 breakout, both revisions, read off Adafruit's own Eagle boards: the
    # same six pins in the same order, on boards of two sizes. The names are the nets the
    # header pads are on; the STEMMA QT board prints pin 1 as VIN.
    CatalogPart("adafruit-ina219", "Adafruit INA219 (original, 4 holes)", "sensor",
                "mod-6x1-p1-r1-25.4x22.24x8.5-s8.5-o-0.38x-8.33",
                "Current, voltage and power on I2C, through a 0.1 ohm shunt: up to 26 V and ±3.2 A",
                _legs("VCC", "GND", "SCL", "SDA", "VIN-", "VIN+"),
                value="Adafruit INA219", ref_prefix="U",
                source=(
                    "Adafruit INA219 Eagle board, Adafruit_INA219_CurPowerMonitor.brd (github "
                    "adafruit/Adafruit-INA219-Current-Sensor-PCB): the 25.4 x 22.24 mm board, the "
                    "header and the nets on it; TI INA219 datasheet SBOS448G (0x40 with A0 and A1 "
                    "low)"
                ),
                check=(
                    "VCC is the logic supply, 3 to 5 V. The current to measure goes in at VIN+ and "
                    "out at VIN-, on these pins or on the terminal block, which carries the same "
                    "two. Its address is 0x40 until A0 or A1 is bridged. Clones such as the purple "
                    "CJMCU-219 usually keep this header order; measure your board's size and header "
                    "position before placing. " + _MODULE_TOP
                ),
                aliases=("INA219", "INA219 module", "CJMCU-219", "current sensor", "power monitor")),
    CatalogPart("adafruit-ina219-stemma-qt", "Adafruit INA219 (STEMMA QT)", "sensor",
                "mod-6x1-p1-r1-25.4x20.32x8.5-s8.5-o0x-7.62",
                "Current, voltage and power on I2C, through a 0.1 ohm shunt: up to 26 V and ±3.2 A",
                _legs("VCC", "GND", "SCL", "SDA", "VIN-", "VIN+"),
                value="Adafruit INA219 STEMMA QT", ref_prefix="U",
                source=(
                    "Adafruit INA219 STEMMA QT Eagle board (github "
                    "adafruit/Adafruit-INA219-Current-Sensor-PCB): the 25.4 x 20.32 mm board, the "
                    "header and the nets on it; TI INA219 datasheet SBOS448G (0x40 with A0 and A1 "
                    "low)"
                ),
                check=(
                    "The board prints pin 1 as VIN: it is VCC, the logic supply, 3 to 5 V. The "
                    "current to measure goes in at VIN+ and out at VIN-, on these pins or on the "
                    "terminal block, which carries the same two. Its address is 0x40 until A0 or A1 "
                    "is bridged on the back, and the two STEMMA QT sockets carry the same I2C. " + _MODULE_TOP
                ),
                aliases=("INA219", "current sensor", "power monitor", "STEMMA QT", "Qwiic")),
    CatalogPart("gy-521", "GY-521 MPU-6050", "sensor", "mod-8x1-p1-r1-21.2x16.4x1.5-s8.5-o0x-6.7",
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
    # The epoxy-bead thermistor of the kits (MF52, as APR draws it), on its two wires. Its
    # drawing gives the bead's width D and thickness T as maxima and the bead-to-bump length
    # L1 as a maximum, and never says how high a builder leaves it: drawn at those maxima, so
    # DRC measures the largest part the datasheet allows.
    CatalogPart("ntc-mf52", "NTC thermistor (MF52 bead)", "sensor",
                "box-2x1-p1-r1-3.8x2.5x9.5",
                "Epoxy-bead thermistor, 10,000 ohm at 25 degrees C, its resistance falling as it "
                "warms",
                value="NTC", ref_prefix="RT",
                source=(
                    "APR MF52 datasheet, p.2 'Outlook and Dimension', model A (tinned steel "
                    "wire): bead at most 3.8 wide (D) and 2.5 thick (T), wires 0.5 +-0.1 mm "
                    "thick, 2.5 +-0.5 mm apart (F) and 12 mm long at least; the drawing is not to "
                    "scale and prints no bead length, so the 9.5 mm height is its L1 maximum "
                    "(bead end to the bump on the wires), an upper bound and not a seat. Model "
                    "E (2.8 mm, 2.0 +-0.5 mm apart) prints no thickness and is not drawn."
                ),
                check=(
                    "Its wires are 2.5 mm apart and the holes 2.54, inside the drawing's "
                    "+-0.5. The resistance and the B value are in its part number, not on the "
                    "bead: measure it, about 10 kohm at 25 degrees C. How high the bead stands "
                    "is yours to choose and it is drawn at the longest the datasheet allows, "
                    "9.5 mm; leave less wire above the board and it stands lower."
                ),
                aliases=("thermistor", "NTC", "MF52", "temperature sensor",
                         "termistör", "sıcaklık sensörü")),
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
                    "rows 15.24 mm apart. Drawn from KiCad's model of Lite-On's LTS-6760, the "
                    "same package pad for pad"
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
                    "rows 15.24 mm apart. Drawn from KiCad's model of Lite-On's LTS-6760, the "
                    "same package pad for pad"
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
    CatalogPart("lcd-1602-i2c", "LCD1602 with I2C backpack (on a header)", "display",
                "hdr-1x4",
                "16x2 character LCD driven over I2C by a PCF8574. Its cable plugs into this "
                "4-pin header: GND VCC SDA SCL from pin 1",
                _legs("GND", "VCC", "SDA", "SCL"), value="LCD1602 I2C", ref_prefix="J",
                source=(
                    "ShillehTek PCF8574 I2C adapter for 1602/2004 LCD manual (the header: GND, "
                    "VCC, SDA, SCL); NXP PCF8574 datasheet (addresses 0x20 to 0x27, 0x38 to "
                    "0x3F on the PCF8574A)"
                ),
                check=(
                    "It answers at 0x27 with a PCF8574 or 0x3F with a PCF8574A: try both if it "
                    "stays blank, and turn its contrast trimmer before deciding it is dead. "
                    + _CABLED_CHECK
                ),
                aliases=("I2C LCD", "LCD I2C", "PCF8574 backpack", "1602 I2C", "LCD backpack")),
    CatalogPart("max7219-matrix", "MAX7219 8x8 LED matrix module (on a header)", "display",
                "hdr-1x5",
                "8x8 LED matrix driven by a MAX7219. Its cable plugs into this 5-pin header: "
                "VCC GND DIN CS CLK from pin 1",
                _legs("VCC", "GND", "DIN", "CS", "CLK"), value="MAX7219 8x8", ref_prefix="J",
                source=(
                    "SunFounder Raphael kit, MAX7219 module (VCC, GND, DIN, CS, CLK; the left "
                    "header the input, the right one the output to the next module); Maxim "
                    "MAX7219 datasheet"
                ),
                check=(
                    "It has a header at each end: the cable goes on the one marked DIN, the "
                    "other is its output to the next matrix. " + _CABLED_CHECK
                ),
                aliases=("LED matrix", "dot matrix", "8x8 matrix", "FC-16", "LED matris")),
    CatalogPart("tm1637-display", "TM1637 4-digit display module (on a header)", "display",
                "hdr-1x4",
                "Four-digit 7-segment display driven by a TM1637. Its cable plugs into this "
                "4-pin header: CLK DIO VCC GND from pin 1",
                _legs("CLK", "DIO", "VCC", "GND"), value="TM1637", ref_prefix="J",
                source=(
                    "ProtoSupplies TM1637 4-Digit 7-Segment Display Module (DSP-6), module "
                    "connections: CLK, DIO, VCC, GND; Titan Micro TM1637 datasheet"
                ),
                check="CLK and DIO are not interchangeable. " + _CABLED_CHECK,
                aliases=("TM1637", "4 digit display", "clock display", "7-segment module")),
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
    # The optocoupler of the official Arduino kit: a PC817 with its base brought out.
    CatalogPart("4n35", "4N35", "ic", "dip-6",
                "Optocoupler with the transistor's base brought out, CTR over 100 %, 5000 V "
                "isolation",
                _legs("A", "K", "NC", "E", "C", "B"), ref_prefix="U",
                source=(
                    "Vishay 4N35 / 4N36 / 4N37 datasheet (81181, rev 1.2), page 1: top view, "
                    "pins 1 to 3 down the left (anode, cathode, no connection), 4 to 6 up the "
                    "right (emitter, collector, base)"
                ),
                check=(
                    "Pin 3 is not connected. Pin 6, the base, is brought out for those who "
                    "want it: leave it open if you do not."
                ),
                aliases=("opto-isolator", "optocoupler", "optokuplör")),
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
    # The two-ball tilt switch of every starter kit, standing cap-end down on its two leads.
    # Drawn at the datasheet's MAXIMA (5.2 +0.3 across, 11.5 +0.4 long), so DRC measures no
    # smaller a part than the one in the bag; its leads are 2.4 mm apart and the holes 2.54.
    CatalogPart("sw-520d", "SW-520D tilt switch", "switch", "box-2x1-p1-r1-5.5x5.5x11.9",
                "Ball tilt switch, 12 V contacts: closed while within about 45 degrees of "
                "upright with its leads down, open past that",
                value="SW-520D", ref_prefix="SW",
                source=(
                    "Bailin (Beelee) SW-520 datasheet, p.2: body 5.2 +0.3/-0.1 mm across and "
                    "11.5 +0.4/-0.1 long, leads 0.6 +-0.05 mm and 8 +-1 mm long, 2.4 mm apart "
                    "(no tolerance printed), the 12 V contact rating, and its ON and OFF angles "
                    "drawn at 10 and 45 degrees; the body is drawn square at those maxima"
                ),
                check=(
                    "Its leads are 2.4 mm apart and the holes 2.54, so each ends up 0.07 mm off "
                    "its hole, well inside the 0.2 mm a 0.6 mm lead has to spare in a 1 mm hole: "
                    "it goes in as it is. Sellers disagree on which way up it conducts, so tilt "
                    "yours over a multimeter before you solder it."
                ),
                aliases=("tilt", "ball switch", "tilt sensor", "SW520D", "SW-520",
                         "eğim sensörü", "eğim anahtarı", "top anahtar")),
    # -- relays
    # The 4 x 4 membrane keypad's ribbon ends in a 0.1 inch socket, so on the board it is the
    # header that socket goes on. Numbered as Parallax numbers it, right to left with the keys
    # facing you; its figure 1 says which lead is which row and column.
    CatalogPart("keypad-4x4", "4x4 membrane keypad (on a header)", "switch", "hdr-1x8",
                "Sixteen keys in four rows and four columns. Its cable plugs into this 8-pin "
                "header: C4 C3 C2 C1 R4 R3 R2 R1 from pin 1",
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
    # A module on a cable plugs into a header on the board, named as the module names its
    # leads (``guide.plugs_in_on_a_cable``); each is held to one sentence by
    # tests/test_cabled_modules.py. Its value is what it is sold as, a number and not a word,
    # because the guide says the value as written in either language: "KY-040 is not on this
    # board" reads in Turkish too, "KY-040 encoder" does not.
    CatalogPart("ky-023-joystick", "KY-023 joystick module (on a header)", "switch", "hdr-1x5",
                "Two-axis joystick that is also a switch when pressed. Its cable plugs into "
                "this 5-pin header: GND +5V VRx VRy SW from pin 1",
                _legs("GND", "+5V", "VRx", "VRy", "SW"), value="KY-023", ref_prefix="J",
                source=(
                    "components101 Joystick Module, pin configuration (pins 1 to 5); Joy-IT "
                    "SensorKit KY-023 (the signals: two pots and a button to ground)"
                ),
                check=(
                    "Feed +5V from the board's own logic supply: on a 3.3 V board, 3.3 V, or the "
                    "two pots read past the top of its ADC. " + _CABLED_CHECK
                ),
                aliases=("joystick", "thumbstick", "KY-023", "kumanda kolu")),
    CatalogPart("ky-040-encoder", "KY-040 rotary encoder module (on a header)", "switch",
                "hdr-1x5",
                "Rotary encoder that is also a switch when pressed. Its cable plugs into this "
                "5-pin header: CLK DT SW + GND from pin 1",
                _legs("CLK", "DT", "SW", "+", "GND"), value="KY-040", ref_prefix="J",
                source=(
                    "components101 KY-040 Rotary Encoder, pin configuration; Joy-IT SensorKit "
                    "KY-040 (CLK and DT the two phases, SW the button)"
                ),
                check=(
                    "+ only feeds its pull-ups: give it the board's logic voltage. "
                    + _CABLED_CHECK
                ),
                aliases=("rotary encoder", "encoder", "KY-040", "enkoder", "döner kodlayıcı")),
    # The bare encoder under the KY-040's board, with only its three encoder pins on the
    # grid: the push switch's D and E and the two pegs are 14.5 and 7.5 mm from them and fit
    # no hole. The courtyard is still the whole part, so DRC knows what they would touch.
    CatalogPart("ec11-encoder", "EC11 rotary encoder", "switch",
                "box-3x1-p1-r1-12.5x14.5x24.5-o0x-7.25",
                "Two-phase rotary encoder, shaft 20 mm above its frame: A and B pulse against "
                "the common C as it turns",
                _legs("A", "C", "B"), value="EC11", ref_prefix="SW",
                source=(
                    "Alps EC11 series drawing (Alps catalogue p.186, "
                    "f5kav.fr/wp-content/uploads/simple-file-list/F5RCT/Realisations/Squirrely/"
                    "Module-PLL/ALPS_EC11.pdf), read at high zoom: A, C, B 2.5 mm apart, the "
                    "switch's D and E 5 mm apart and 14.5 mm from them, the two pegs 12.5 mm "
                    "outer to outer and 7.5 mm from them, the frame 4.5 mm and the shaft a "
                    "further 20 mm above the mounting surface, every terminal 3.5 mm below it. "
                    "Only A, C and B are on the grid: the 2.5 mm pitch against the board's "
                    "2.54 leaves A and B 0.04 mm off their holes, as the JST XH's does; the "
                    "courtyard covers D, E and the pegs too"
                ),
                check=(
                    "Snip off the two pegs and the switch's D and E flush with the frame. D and "
                    "E sit 14.5 mm from the three pins, 0.74 mm off a row of holes, and the "
                    "pegs are as long as the pins (3.5 mm), so left on they would stand the "
                    "frame on the board and keep the pins out of the holes. If you want the "
                    "push switch, solder wires to the stubs of D and E by hand; the KY-040 is "
                    "the encoder with a switch ready to plug in. A and B are 0.04 mm off their "
                    "holes for the 2.5 mm against 2.54 pitch, inside what a 1 mm hole has to "
                    "spare."
                ),
                aliases=("rotary encoder", "encoder", "EC11", "enkoder", "döner kodlayıcı")),
    # The little slide switch of every kit and power board. Drawn at its FRAME (3.5 mm): the
    # lever's height above it is not on the Vimex drawing, so the 3D body stops at the frame.
    CatalogPart("ss-12d00", "SS-12D00 slide switch", "switch", "box-3x1-p1-r1-8.5x3.5x3.5",
                "Small slide switch, one pole two positions: the lever joins the middle pin "
                "to one end or the other",
                _legs("A", "COM", "B"), value="SS-12D00", ref_prefix="SW",
                source=(
                    "Vimex International drawing of the SS-12D00, 1P2T, dated 8 March 1999 "
                    "(vimex.com/switches/techdocs/SS12D00-tech.pdf): three pins 2.5 mm apart "
                    "with the common in the middle, the body 8.5 x 3.5 mm and its frame 3.5 "
                    "mm high, the pin tips 7.2 mm below the top of the frame, pins 0.5 x 0.3 "
                    "mm in holes of 0.9 mm, 30 V DC at 0.3 A. The lever stands above the "
                    "frame by a length the drawing leaves as a letter (it differs between "
                    "lever codes) so it is NOT counted in the height drawn here, and "
                    "component-too-tall cannot see it. The 2.5 mm pin pitch against the "
                    "board's 2.54 leaves the end pins 0.04 mm off their holes, as the "
                    "RV09's does. ASSUMPTION: the pin row is centred on the 8.5 x 3.5 mm "
                    "body. Another maker's listing (Sofng, on LCSC) gives 8.8 x 3.9 mm for "
                    "the same name"
                ),
                check=(
                    "Measure the lever's height and the body on yours: the lever is not in "
                    "the height DRC checks, so a lid or a panel above the switch is yours "
                    "to check, and other makers' SS-12D00s are a little larger than the "
                    "Vimex drawing. The 2.5 mm pin pitch against 2.54 puts the end pins "
                    "0.04 mm off their holes, inside what a 1 mm hole has to spare. Which "
                    "end the lever's first position joins is not something this part can "
                    "say: try the switch with a meter before you wire the two ends."
                ),
                aliases=("slide switch", "SS12D00", "SS-12D00", "SS12D00G3", "SPDT switch",
                         "1P2T switch", "kaydırmalı anahtar", "sürgülü anahtar")),
    # -- relays -----------------------------------------------------------------------
    CatalogPart("srd-05vdc-sl-c", "Songle SRD-05VDC-SL-C relay", "relay", "relay-srd",
                "SPDT relay, 5 V coil of 70 ohm, contacts 10 A at 125 V AC",
                _SRD_LEGS, value="SRD-05VDC-SL-C", source=_SRD_SOURCE, check=_SRD_CHECK),
    CatalogPart("srd-12vdc-sl-c", "Songle SRD-12VDC-SL-C relay", "relay", "relay-srd",
                "SPDT relay, 12 V coil of 400 ohm, contacts 10 A at 125 V AC",
                _SRD_LEGS, value="SRD-12VDC-SL-C", source=_SRD_SOURCE, check=_SRD_CHECK),
    # The one-channel relay board every kit has: a Songle cube, a transistor or an
    # optocoupler to drive it, and a screw terminal for what it switches. Its three control
    # pins are the header; the contacts stay on the module.
    CatalogPart("relay-module-1ch", "1-channel 5 V relay module (on a header)", "relay",
                "hdr-1x3",
                "A Songle SRD-05VDC relay and its driver on a small module. Its cable plugs into this "
                "3-pin header: VCC GND IN from pin 1",
                _legs("VCC", "GND", "IN"), value="SRD-05VDC", ref_prefix="J",
                source=(
                    "ShillehTek 1-channel 5 V relay module manual (control pins VCC, GND, IN; "
                    "outputs NO, COM, NC; active LOW; SONGLE SRD-05VDC-SL-C, 10 A 250 V AC)"
                ),
                check=(
                    "Most of these boards switch on when IN is pulled LOW. What the relay "
                    "switches goes to the module's own screw terminals, not to the perfboard. "
                    "Mains there needs proper insulation and spacing and is not a perfboard "
                    "job. " + _CABLED_CHECK
                ),
                aliases=("relay module", "relay board", "5V relay", "röle modülü", "röle kartı")),
    # -- connectors -------------------------------------------------------------------
    CatalogPart("jst-xh-2", "JST XH connector, 2-pin, top entry", "connector", "jst-xh-2",
                _XH_SUMMARY_TOP, value="B2B-XH-A", ref_prefix="J",
                source="KiCad 10 Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical and its model, after JST's eXH "
                       "drawing; " + _ON_THE_GRID,
                check=_XH_CHECK, aliases=_XH_WORDS),
    CatalogPart("jst-xh-2-side", "JST XH connector, 2-pin, side entry", "connector", "jst-xh-2-side",
                _XH_SUMMARY_SIDE, value="S2B-XH-A", ref_prefix="J",
                source="KiCad 10 Connector_JST:JST_XH_S2B-XH-A_1x02_P2.50mm_Horizontal and its model, after JST's eXH "
                       "drawing; " + _ON_THE_GRID,
                check=_XH_CHECK, aliases=_XH_WORDS),
    CatalogPart("jst-xh-3", "JST XH connector, 3-pin, top entry", "connector", "jst-xh-3",
                _XH_SUMMARY_TOP, value="B3B-XH-A", ref_prefix="J",
                source="KiCad 10 Connector_JST:JST_XH_B3B-XH-A_1x03_P2.50mm_Vertical and its model, after JST's eXH "
                       "drawing; " + _ON_THE_GRID,
                check=_XH_CHECK, aliases=_XH_WORDS),
    CatalogPart("jst-xh-3-side", "JST XH connector, 3-pin, side entry", "connector", "jst-xh-3-side",
                _XH_SUMMARY_SIDE, value="S3B-XH-A", ref_prefix="J",
                source="KiCad 10 Connector_JST:JST_XH_S3B-XH-A_1x03_P2.50mm_Horizontal and its model, after JST's eXH "
                       "drawing; " + _ON_THE_GRID,
                check=_XH_CHECK, aliases=_XH_WORDS),
    CatalogPart("jst-xh-4", "JST XH connector, 4-pin, top entry", "connector", "jst-xh-4",
                _XH_SUMMARY_TOP, value="B4B-XH-A", ref_prefix="J",
                source="KiCad 10 Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical and its model, after JST's eXH "
                       "drawing; " + _ON_THE_GRID,
                check=_XH_CHECK, aliases=_XH_WORDS),
    CatalogPart("jst-xh-4-side", "JST XH connector, 4-pin, side entry", "connector", "jst-xh-4-side",
                _XH_SUMMARY_SIDE, value="S4B-XH-A", ref_prefix="J",
                source="KiCad 10 Connector_JST:JST_XH_S4B-XH-A_1x04_P2.50mm_Horizontal and its model, after JST's eXH "
                       "drawing; " + _ON_THE_GRID,
                check=_XH_CHECK, aliases=_XH_WORDS),
    CatalogPart("kk254-2", "Molex KK 254 connector, 2-pin", "connector", "kk254-2",
                _KK_SUMMARY, value="22-27-2021", ref_prefix="J",
                source="KiCad 10 Connector_Molex:Molex_KK-254_AE-6410-02A_1x02_P2.54mm_Vertical "
                       "(Molex 22-27-2021); drawn from the 3-pin model cut into three",
                check=_KK_CHECK, aliases=(*_KK_WORDS, "KF2510-2A", "AE-6410-02A")),
    CatalogPart("kk254-3", "Molex KK 254 connector, 3-pin", "connector", "kk254-3",
                _KK_SUMMARY, value="22-27-2031", ref_prefix="J",
                source="KiCad 10 Connector_Molex:Molex_KK-254_AE-6410-03A_1x03_P2.54mm_Vertical "
                       "(Molex 22-27-2031); drawn from the 3-pin model cut into three",
                check=_KK_CHECK, aliases=(*_KK_WORDS, "KF2510-3A", "AE-6410-03A")),
    CatalogPart("kk254-4", "Molex KK 254 connector, 4-pin", "connector", "kk254-4",
                _KK_SUMMARY, value="22-27-2041", ref_prefix="J",
                source="KiCad 10 Connector_Molex:Molex_KK-254_AE-6410-04A_1x04_P2.54mm_Vertical "
                       "(Molex 22-27-2041); drawn from the 3-pin model cut into three",
                check=_KK_CHECK, aliases=(*_KK_WORDS, "KF2510-4A", "AE-6410-04A")),
    CatalogPart("kk254-5", "Molex KK 254 connector, 5-pin", "connector", "kk254-5",
                _KK_SUMMARY, value="22-27-2051", ref_prefix="J",
                source="KiCad 10 Connector_Molex:Molex_KK-254_AE-6410-05A_1x05_P2.54mm_Vertical "
                       "(Molex 22-27-2051); drawn from the 3-pin model cut into three",
                check=_KK_CHECK, aliases=(*_KK_WORDS, "KF2510-5A", "AE-6410-05A")),
    CatalogPart("kk254-6", "Molex KK 254 connector, 6-pin", "connector", "kk254-6",
                _KK_SUMMARY, value="22-27-2061", ref_prefix="J",
                source="KiCad 10 Connector_Molex:Molex_KK-254_AE-6410-06A_1x06_P2.54mm_Vertical "
                       "(Molex 22-27-2061); drawn from the 3-pin model cut into three",
                check=_KK_CHECK, aliases=(*_KK_WORDS, "KF2510-6A", "AE-6410-06A")),
    CatalogPart("kk254-8", "Molex KK 254 connector, 8-pin", "connector", "kk254-8",
                _KK_SUMMARY, value="22-27-2081", ref_prefix="J",
                source="KiCad 10 Connector_Molex:Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical "
                       "(Molex 22-27-2081); drawn from the 3-pin model cut into three",
                check=_KK_CHECK, aliases=(*_KK_WORDS, "KF2510-8A", "AE-6410-08A")),
    CatalogPart("servo-header", "Hobby servo (on a header)", "connector", "hdr-1x3",
                "A hobby servo such as the SG90. Its cable plugs into this 3-pin header: "
                "PWM + - from pin 1",
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
    # The motor in the Arduino starter kit and every toy: two wires to a part off the board.
    CatalogPart("dc-motor-130", "DC motor, 130 size, on two wires", "connector", "wire-2",
                "Small brushed motor off the board on two wires: swap them and it turns the "
                "other way",
                _legs("A", "B"), value="DC motor", ref_prefix="M",
                source=(
                    "Pololu's page for the Tamiya FA-130 (pololu.com/product/77/specs): at 3 V "
                    "it draws 150 mA unloaded and 2100 mA stalled. A brushed motor has no "
                    "polarity, so its two wires are A and B and either goes to either; the "
                    "130-size motors in kits are not all this motor and no drawing of them "
                    "was found, so only the wires are drawn"
                ),
                check=(
                    "Do not drive it from a pin: the FA-130 stalls at 2.1 A at 3 V, so put a "
                    "transistor or a motor driver between them, and a diode across the motor "
                    "with its banded end on the supply side. Measure yours stalled before you "
                    "choose the transistor: kit motors differ."
                ),
                aliases=("motor", "dc motor", "130 motor", "toy motor", "FA-130", "RF-130",
                         "elektrik motoru", "fırçalı motor")),
    CatalogPart("ds3231-rtc", "DS3231 RTC module, ZS-042 (on a header)", "connector",
                "hdr-1x6",
                "Real-time clock with a coin cell, on I2C. Its cable plugs into this 6-pin "
                "header: GND VCC SDA SCL SQW 32K from pin 1",
                _legs("GND", "VCC", "SDA", "SCL", "SQW", "32K"), value="DS3231 RTC",
                ref_prefix="J",
                source=(
                    "Cirkit Designer ZS-042 RTC module, pin table (1 GND, 2 VCC, 3 SDA, 4 SCL, "
                    "5 SQW, 6 32K); Maxim DS3231 datasheet (SQW the alarm and square-wave "
                    "output, 32K the 32 kHz one)"
                ),
                check=(
                    "Many ZS-042 boards charge their coin cell: fit an LIR2032, or take off the "
                    "charging diode before fitting a CR2032. " + _CABLED_CHECK
                ),
                aliases=("RTC", "real time clock", "DS3231", "ZS-042", "gerçek zamanlı saat")),
    CatalogPart("micro-sd-module", "Micro SD card module (on a header)", "connector", "hdr-1x6",
                "Micro SD card socket on SPI, with a 3.3 V regulator. Its cable plugs into "
                "this 6-pin header: GND VCC MISO MOSI SCK CS from pin 1",
                _legs("GND", "VCC", "MISO", "MOSI", "SCK", "CS"), value="Micro SD",
                ref_prefix="J",
                source=(
                    "components101 Micro SD Card Module, pin configuration (GND, VCC, MISO, "
                    "MOSI, SCK, CS); CircuitState, interfacing the Catalex module (its "
                    "regulator and level shifter)"
                ),
                check=(
                    "Its MISO is driven even when CS is high, so it shares the SPI bus badly "
                    "with other parts. " + _CABLED_CHECK
                ),
                aliases=("SD card", "micro SD", "TF card", "Catalex", "SD kart")),
    # Bluetooth serial modules on their carrier boards. The HC-05 is the one on the ZS-040
    # board with an EN pin where older boards had KEY; the HC-06 is the four-pin slave-only
    # one. Both run at 3.3 V inside, and their RXD is not 5 V tolerant.
    CatalogPart("ftdi-basic", "FTDI / USB-serial basic board (on a header)", "connector", "hdr-1x6",
                "USB to serial adapter for programming and logging. Its cable plugs into this "
                "6-pin header: GND CTS VCC TXO RXI DTR from pin 1",
                _legs("GND", "CTS", "VCC", "TXO", "RXI", "DTR"), value="FTDI BASIC",
                ref_prefix="J",
                source=(
                    "SparkFun FTDI Basic Breakout and Serial Basic Breakout, 1 x 6 header read "
                    "off their Eagle boards: GND, CTS, VCC, TXO, RXI, DTR, the order the Arduino "
                    "Pro Mini's programming header expects. The FTDI cable has RTS on the sixth "
                    "lead where these have DTR"
                ),
                check=(
                    "TXO goes to the controller's RX and RXI to its TX. Pick 3.3 V or 5 V on the "
                    "board's jumper before it is plugged into the target, and DTR goes to the "
                    "target's reset through a 100 nF capacitor. " + _CABLED_CHECK
                ),
                aliases=("FTDI", "FT232", "FT232RL", "CH340", "USB serial", "USB-serial", "UART",
                         "programmer", "seri adaptör", "USB seri")),
    CatalogPart("pca9685-servo-driver", "PCA9685 16-channel PWM driver (on a header)", "connector",
                "hdr-1x6",
                "16-channel 12-bit PWM driver on I2C, for servos and LEDs. Its cable plugs into "
                "this 6-pin header: V+ VCC SDA SCL OE GND from pin 1",
                _legs("V+", "VCC", "SDA", "SCL", "OE", "GND"), value="PCA9685",
                ref_prefix="J",
                source=(
                    "Adafruit 16-channel PWM/Servo board (rev C) Eagle board, the 1 x 6 header "
                    "along its short edge, numbered from the V+ end; its silkscreen reads the "
                    "other way, GND first. V+ is the servo supply, joined to the channels' middle "
                    "pins and to the screw terminal through a reverse-polarity MOSFET, and VCC "
                    "is the chip's 3.3 to 5 V"
                ),
                check=(
                    "V+ is the servo supply and is not the chip's VCC: bring each from its own "
                    "source, with the grounds joined. OE enables the outputs when low and "
                    "a 10k on the board holds it low, so it can be left unwired. The servo plugs are on the board's 16 channel headers, not on "
                    "this one. " + _CABLED_CHECK
                ),
                aliases=("PCA9685", "servo driver", "servo shield", "16 channel PWM", "PWM driver",
                         "servo sürücü")),
    CatalogPart("adafruit-bh1750", "Adafruit BH1750 light sensor (on a header)", "sensor",
                "hdr-1x6",
                "Light sensor, 1 to 65535 lux, on I2C. Its cable plugs into this 6-pin header: "
                "VIN 3Vo GND SCL SDA ADDR from pin 1",
                _legs("VIN", "3Vo", "GND", "SCL", "SDA", "ADDR"), value="BH1750",
                ref_prefix="J",
                source=(
                    "Adafruit's own Eagle board for its BH1750 breakout "
                    "(github.com/adafruit/Adafruit-BH1750-PCB), the 6-pin header JP1 along the "
                    "board's edge: pad 1 at VIN and every name read off its silkscreen, each "
                    "pad's net checked against the board's nets"
                ),
                check=(
                    "VIN takes 3 to 5 V by the board's silkscreen: a 3.3 V regulator makes the "
                    "sensor's supply, and 3Vo is that regulator's output, not a second input. "
                    "SCL and SDA go through level-shifting transistors, so the bus may run at "
                    "VIN's level. The silkscreen gives the default I2C address as 0x23: a "
                    "resistor on the board holds ADDR low, and the solder jumper beside it "
                    "ties ADDR to 3.3 V for the other address, so leave ADDR unwired for the "
                    "default. Other BH1750 boards carry a different header, so "
                    "compare the names printed on yours with these. " + _CABLED_CHECK
                ),
                aliases=("BH1750", "light sensor", "lux sensor", "GY-302", "ışık sensörü",
                         "lux")),
    CatalogPart("adafruit-aht20", "Adafruit AHT20 temperature and humidity sensor (on a header)",
                "sensor", "hdr-1x4",
                "Temperature and humidity sensor, on I2C. Its cable plugs into this 4-pin "
                "header: VIN GND SCL SDA from pin 1",
                _legs("VIN", "GND", "SCL", "SDA"), value="AHT20", ref_prefix="J",
                source=(
                    "Adafruit's own Eagle board for its AHT20 breakout "
                    "(github.com/adafruit/Adafruit-AHT20-PCB), the 4-pin header JP2: pad 1 at "
                    "VIN and every name read off its silkscreen, each pad's net checked against "
                    "the board's nets"
                ),
                check=(
                    "VIN takes 3 to 5 V by the board's silkscreen, and the board has no "
                    "regulator: the sensor's supply is VIN through a resistor and a capacitor, "
                    "and the pull-ups on SCL and SDA go to VIN, so the bus idles at VIN's "
                    "level. Other AHT20 boards carry a different header, so compare the names "
                    "printed on yours with these. " + _CABLED_CHECK
                ),
                aliases=("AHT20", "AHT10", "temperature sensor", "humidity sensor",
                         "sıcaklık nem sensörü", "nem sensörü")),
    CatalogPart("adafruit-vl53l0x", "Adafruit VL53L0X time-of-flight distance sensor (on a header)",
                "sensor", "hdr-1x7",
                "Laser distance sensor, about 30 to 1000 mm, on I2C. Its cable plugs into "
                "this 7-pin header: VIN 2v8 GND GPIO SHDN SCL SDA from pin 1",
                _legs("VIN", "2v8", "GND", "GPIO", "SHDN", "SCL", "SDA"), value="VL53L0X",
                ref_prefix="J",
                source=(
                    "Adafruit's own Eagle board for its VL53L0X breakout "
                    "(github.com/adafruit/Adafruit-VL53L0X-ToF-Distance-Sensor-PCB, 'Adafruit "
                    "VL53L0X'), the 7-pin header JP1: pad 1 at VIN and every name read off its "
                    "silkscreen, each pad's net checked against the board's nets. The silkscreen "
                    "gives the range as about 30 to 1000 mm"
                ),
                check=(
                    "VIN takes 3 to 5 V by the board's silkscreen: a 2.8 V regulator makes the "
                    "sensor's supply, and 2v8 is its output, not a second input. SCL and SDA "
                    "go through level-shifting transistors, so the bus may run at VIN's "
                    "level. SHDN is the sensor's XSHUT line, held high by a resistor on the "
                    "board: pull it low to switch the sensor off, or leave it unwired. GPIO is "
                    "the sensor's interrupt output and can stay unwired. Other VL53L0X boards "
                    "carry a different header, so compare the names printed on yours with "
                    "these. " + _CABLED_CHECK
                ),
                aliases=("VL53L0X", "ToF", "time of flight", "laser distance", "distance sensor",
                         "mesafe sensörü")),
    CatalogPart("hc-05","HC-05 Bluetooth module, ZS-040 (on a header)", "connector", "hdr-1x6",
                "Bluetooth serial module, master or slave, 3.3 V logic. Its cable plugs into "
                "this 6-pin header: STATE RXD TXD GND VCC EN from pin 1",
                _legs("STATE", "RXD", "TXD", "GND", "VCC", "EN"), value="HC-05", ref_prefix="J",
                source=(
                    "ProtoSupplies HC-05 ZS-040 Bluetooth module, 1 x 6 header (STATE, RXD, TXD, "
                    "GND, VCC, EN; VCC 3.6 to 6 V, the module 3.3 V inside, EN its AT mode)"
                ),
                check=(
                    "TXD goes to the controller's RX and RXD to its TX. RXD is 3.3 V logic: from "
                    "a 5 V board's TX, bring it down through a divider of 1k and 2k. EN and STATE "
                    "can be left unwired. " + _CABLED_CHECK
                ),
                aliases=("Bluetooth", "HC05", "ZS-040", "serial Bluetooth", "Bluetooth modülü")),
    CatalogPart("hc-06", "HC-06 Bluetooth module (on a header)", "connector", "hdr-1x4",
                "Bluetooth serial module, slave only, 3.3 V logic. Its cable plugs into this "
                "4-pin header: VCC GND TXD RXD from pin 1",
                _legs("VCC", "GND", "TXD", "RXD"), value="HC-06", ref_prefix="J",
                source=(
                    "eTechnophiles HC-06 pinout, 4-pin table (VCC, GND, TXD, RXD; RXD 3.3 V "
                    "tolerant, not 5 V)"
                ),
                check=(
                    "TXD goes to the controller's RX and RXD to its TX. RXD is 3.3 V logic: from "
                    "a 5 V board's TX, bring it down through a divider of 1k and 2k. "
                    + _CABLED_CHECK
                ),
                aliases=("Bluetooth", "HC06", "serial Bluetooth", "Bluetooth modülü")),
    # The common blue MAX485 board: the chip's two sides on two 4-pin headers at its two
    # ends, RO RE DE DI on one and VCC B A GND on the other, as the chip numbers them, with
    # A and B on a screw terminal as well. Here both are one header, in that order.
    CatalogPart("max485-module", "MAX485 RS-485 module (on a header)", "connector", "hdr-1x8",
                "TTL to RS-485 transceiver module, 5 V. Its cable plugs into this 8-pin header: "
                "RO RE DE DI VCC B A GND from pin 1",
                _legs("RO", "RE", "DE", "DI", "VCC", "B", "A", "GND"), value="MAX485",
                ref_prefix="J",
                source=(
                    "Maxim MAX485 datasheet, pin description (1 RO, 2 RE, 3 DE, 4 DI, 5 GND, 6 A, "
                    "7 B, 8 VCC, supply 4.75 to 5.25 V); Kunkune MAX485 TTL to RS-485 module (its "
                    "0.1 in pins VCC A B GND RO RE DE DI, A and B also on a 5.08 mm terminal)"
                ),
                check=(
                    "RE is on when low and DE when high: join them and drive both from one pin to "
                    "switch between listening and sending. A and B are the bus, on the module's "
                    "screw terminal too: A goes to A and B to B along it. " + _CABLED_CHECK
                ),
                aliases=("RS485", "RS-485", "MAX485", "Modbus", "TTL to RS485")),
    # The green ULN2003 board sold with the 28BYJ-48, as a wired header: no maker draws it and
    # sellers' boards come in four sizes (32 to 40.5 mm), so no body is drawn until somebody
    # measures one. The motor plugs into the board's own socket, not into this header.
    CatalogPart("uln2003-board", "ULN2003 stepper driver board (on a header)", "connector",
                "hdr-1x6",
                "Driver board for a 28BYJ-48 stepper. Its cable plugs into this 6-pin header: "
                "IN1 IN2 IN3 IN4 - + from pin 1",
                _legs("IN1", "IN2", "IN3", "IN4", "-", "+"), value="ULN2003 board",
                ref_prefix="J",
                source=(
                    "Makerguides / ProtoSupplies '4 Phase ULN2003 Stepper Motor Driver PCB' "
                    "sheet (inputs A to D, supply 5 to 12 V, 500 mA per output); the board has "
                    "no drawing, so no body is drawn and the header is the wires you run to it"
                ),
                check=(
                    "The four inputs are lettered A to D on the board and IN1 to IN4 under its "
                    "header; the supply is a separate pair of pins, 5 to 12 V, so give a 5 V "
                    "28BYJ-48 5 V and join the supply's - to your logic ground. The motor plugs "
                    "into the board's own white socket, not into this header. " + _CABLED_CHECK
                ),
                aliases=("stepper driver", "28BYJ-48", "ULN2003", "stepper motor board",
                         "step motoru sürücü", "step motor sürücüsü")),
    # The red dual H-bridge board of every robot kit. Its signal header is read off a seller's
    # labelled photograph (the arrows from ENA to ENB along the board's edge); no drawing of
    # the board exists, so nothing but the header is drawn.
    CatalogPart("l298n-board", "L298N dual motor driver board (on a header)", "connector",
                "hdr-1x6",
                "Dual H-bridge board for two DC motors. Its cable plugs into this 6-pin "
                "header: ENA IN1 IN2 IN3 IN4 ENB from pin 1",
                _legs("ENA", "IN1", "IN2", "IN3", "IN4", "ENB"), value="L298N board",
                ref_prefix="J",
                source=(
                    "ShillehTek's L298N page, its pinout photograph "
                    "(shillehtek.com/blogs/shillehtek-product-manuals/l298n-motor-driver-"
                    "controller-board-module-for-stepper-motor-dc-dual-h-bridge): the signal "
                    "header ENA, IN1, IN2, IN3, IN4, ENB from one end to the other, and "
                    "separate screw terminals for OUT1 to OUT4 and 12V, GND, 5V; and "
                    "docs.circuit.rocks/motors/l298n for the 12 V terminal's 5 to 35 V and the "
                    "5 V jumper. The board has no drawing, so no body is drawn and the header "
                    "is the wires you run to it"
                ),
                check=(
                    "ENA and ENB enable the two channels and IN1 and IN2, IN3 and IN4 set each "
                    "one's direction. The motors, the motor supply (the 12V terminal) and the "
                    "5V terminal are on the board's own screw terminals, not on this header: "
                    "join the supply's GND to your logic ground. With the motor supply above "
                    "12 V take off the board's 5V jumper and feed your logic separately. "
                    + _CABLED_CHECK
                ),
                aliases=("motor driver", "H-bridge", "L298N", "dc motor driver", "L298",
                         "motor sürücü", "motor sürücüsü")),
    # The blue RFID-RC522 board of the kits. Numbered from the VCC end, as the seller's photo
    # prints 1 to 8 over its header; the same row read from the other end is SDA first.
    CatalogPart("rc522-module", "RC522 RFID reader module (on a header)", "sensor", "hdr-1x8",
                "13.56 MHz RFID reader on SPI. Its cable plugs into this 8-pin header: 3.3V "
                "RST GND IRQ MISO MOSI SCK SDA from pin 1",
                _legs("3.3V", "RST", "GND", "IRQ", "MISO", "MOSI", "SCK", "SDA"),
                value="RC522", ref_prefix="J",
                source=(
                    "ShillehTek's RC522 manual (shillehtek.com/blogs/shillehtek-product-manuals/"
                    "rc522-rfid-reader-writer-module-13-56mhz-spi-kit-for-arduino-manual), its "
                    "pinout photograph with 1 to 8 printed over the header, and the components101 "
                    "RC522 pinout drawing, both numbering it VCC, RST, GND, IRQ, MISO, MOSI, SCK, "
                    "SDA; the board has no drawing, so no body is drawn and the header is the "
                    "wires you run to it"
                ),
                check=(
                    "Feed it 3.3 V, not 5 V: its supply pin is the one marked 3.3V. SDA is the "
                    "SPI chip select here, not an I2C data line; MISO is also marked SCL and "
                    "TX for the chip's other modes. IRQ may stay unconnected. Sellers print "
                    "the same row from the other end, SDA first: read the names, not the "
                    "place. " + _CABLED_CHECK
                ),
                aliases=("RFID", "RC522", "MFRC522", "RFID-RC522", "NFC", "card reader",
                         "kart okuyucu", "RFID okuyucu")),
    # An alias that is a KY number is written "KY-NNN <word>", never a bare "KY-NNN":
    # part_rank squeezes a part's names into one run of letters and digits, so two bare ones
    # side by side ("KY-010" "KY-012") spell "10k" and the part would answer a search for a
    # 10k resistor. A digit run followed by a word keeps that out; test_a_bare_ky_alias_is_never_next_to_another_ky_alias
    # reads them all.
    CatalogPart("sensor-board-3pin", "3-pin sensor board (S + -), on a header", "sensor", "hdr-1x3",
                "The small three-pin KY boards of a sensor kit: one signal pin, supply "
                "and ground. Its cable plugs into this 3-pin header: S + - from pin 1",
                _legs("S", "+", "-"), value="KY 3-pin", ref_prefix="J",
                source=(
                    "Joy-IT SensorKit X40 manual (16.06.2017, CC BY-NC-SA 3.0), the "
                    "Pinout page of each board, pin names and their order only: KY-001, "
                    "002, 003, 010, 017, 022, 033 and 035 number them Signal, +V, GND; "
                    "KY-004, 006, 012, 015, 018, 020, 021, 031 and 039 number them GND, "
                    "+V, Signal, the same three pins from the other end; the water level "
                    "sensor's S, - and + are Conrad's SE045 datasheet"
                ),
                check=(
                    "The manual numbers some of these boards S + - and others - + S, the "
                    "same three pins from the other end, so a board plugged straight into "
                    "a header must match its silkscreen. S is the signal: an output on a "
                    "sensor, an input on a buzzer. "
                    "A water level sensor prints its three pins - + S, as Conrad's SE045 "
                    "datasheet lists them, S being the signal pin. "
                    + _CABLED_CHECK
                ),
                aliases=("KY-001 temperature sensor", "KY-002 vibration switch",
                         "KY-003 hall sensor", "KY-004 button", "KY-006 passive buzzer",
                         "KY-010 light barrier", "KY-012 active buzzer",
                         "KY-015 temperature humidity sensor", "KY-017 tilt switch",
                         "KY-018 photoresistor", "KY-020 tilt switch", "KY-021 mini reed",
                         "KY-022 IR receiver", "KY-031 sensor (knock)", "KY-033 line tracking",
                         "KY-035 magnetic sensor", "KY-039 heartbeat sensor", "sensor module",
                         "photoresistor module", "hall module", "button module", "tilt module",
                         "reed module", "buzzer module", "IR receiver module",
                         "knock sensor module", "heartbeat sensor module",
                         "line tracking module", "light barrier module",
                         "vibration switch module", "sensör modülü",
                         "water level sensor", "water sensor module", "su seviye sensörü",)),
    CatalogPart("sensor-board-4pin", "4-pin sensor board (D0 + - A0), on a header", "sensor", "hdr-1x4",
                "The four-pin KY boards with a comparator and a sensitivity trimmer: a "
                "digital and an analog output. Its cable plugs into this 4-pin header: D0 "
                "+ - A0 from pin 1",
                _legs("D0", "+", "-", "A0"), value="KY 4-pin", ref_prefix="J",
                source=(
                    "Joy-IT SensorKit X40 manual (16.06.2017, CC BY-NC-SA 3.0), the "
                    "Pinout pages of KY-024, 025, 026, 028, 036, 037 and 038, pin names "
                    "and order only: digital signal, +V, GND, analog signal. The soil moisture, "
                    "rain and MQ-2 boards (components101.com/sensors/rain-drop-sensor-module, "
                    "components101.com/node/797, the Waveshare MQ-2 datasheet) carry the same "
                    "four outputs and supplies, in the orders the check gives"
                ),
                check=(
                    "The manual calls pin 1 the digital signal and pin 4 the analog "
                    "signal; your board may print other names for them. The digital "
                    "output comes from the on-board comparator, set with the trimmer; the "
                    "analog one is the sensor's own, and the manual says it reads "
                    "inverted: a stronger input is a lower voltage. "
                    "The soil moisture (FC-28, YL-69), rain (YL-83, FC-37) and MQ-2 gas "
                    "boards have the same four pins in other orders, and write the outputs "
                    "DO and AO or DOUT and AOUT: Components101 lists VCC GND D0 A0 for the "
                    "rain board and VCC GND DO AO for the soil one, and Waveshare's MQ-2 "
                    "datasheet lists DOUT AOUT GND VCC. "
                    + _CABLED_CHECK
                ),
                aliases=("KY-024 linear hall sensor", "KY-025 reed", "KY-026 flame sensor",
                         "KY-028 thermistor", "KY-036 metal touch", "KY-037 microphone",
                         "KY-038 sound sensor", "flame sensor module", "sound sensor module",
                         "microphone module", "linear hall module", "thermistor module",
                         "metal touch module", "ses sensörü modülü",
                         "FC-28 soil moisture", "YL-69 soil moisture", "soil moisture sensor",
                         "MQ-2 gas sensor", "gas sensor module", "YL-83 rain sensor",
                         "FC-37 rain sensor", "rain sensor module", "toprak nem sensörü",
                         "yağmur sensörü", "gaz sensörü",)),
    CatalogPart("ky-053-ads1115", "KY-053 ADS1115 ADC module (on a header)", "sensor", "hdr-1x10",
                "Four-input analog-to-digital converter board (ADS1115, 16 bit, I2C). Its "
                "cable plugs into this 10-pin header: VDD GND SCL SDA ADDR ALRT A0 A1 A2 "
                "A3 from pin 1",
                _legs("VDD", "GND", "SCL", "SDA", "ADDR", "ALRT", "A0", "A1", "A2", "A3"), value="KY-053", ref_prefix="J",
                source=(
                    "Joy-IT SensorKit X40 manual (16.06.2017, CC BY-NC-SA 3.0), the "
                    "KY-053 page, whose photograph of the board shows the labels printed "
                    "on it, read down its edge: VDD, GND, SCL, SDA, ADDR, ALRT, A0, A1, "
                    "A2, A3; the chip name and '16Bit I2C ADC' are as printed on the "
                    "board in that photograph"
                ),
                check=(
                    "The pins are in the order the manual's photograph shows them down "
                    "the board's edge, VDD at the top. ADDR and ALRT are not part of the "
                    "I2C wiring: connect the supply, SCL and SDA first. "
                    + _CABLED_CHECK
                ),
                aliases=("KY-053 ADS1115", "ADS1115 module", "16 bit ADC", "ADC module",)),
    CatalogPart("ky-051-level-shifter", "KY-051 level shifter module (on a header)", "ic", "hdr-2x6",
                "Four-channel voltage translator board with two supply sides, A and B. "
                "Its cable plugs into this 12-pin header: VCCb VCCa B1 A1 B2 A2 B3 A3 B4 "
                "A4 OE GND from pin 1",
                _legs("VCCb", "VCCa", "B1", "A1", "B2", "A2", "B3", "A3", "B4", "A4", "OE", "GND"), value="KY-051", ref_prefix="J",
                source=(
                    "Joy-IT SensorKit X40 manual (16.06.2017, CC BY-NC-SA 3.0), the "
                    "KY-051 page, whose photograph shows the labels printed on the board: "
                    "VCCb, B1, B2, B3, B4, OE down one side and VCCa, A1, A2, A3, A4, GND "
                    "down the other, with VCCa 1.2 to 3.6 V and VCCb 1.7 to 5.5 V, and "
                    "the text that VCCb must be higher than or equal to VCCa. The header "
                    "interleaves the two sides in pairs, the order is ours"
                ),
                check=(
                    "The real board has its two rows of six on opposite edges, so this "
                    "header is not its shape: it is only the twelve wires listed in "
                    "pairs, VCCb with VCCa, B1 with A1 and so on. Wire each by its label. "
                    "The board prints VCCa 1.2 to 3.6 V and VCCb 1.7 to 5.5 V, and the "
                    "manual says VCCb must be higher than or equal to VCCa. GND is on the "
                    "A side: join it to yours. "
                    + _CABLED_CHECK
                ),
                aliases=("KY-051 level shifter", "level converter", "voltage translator",
                         "seviye çevirici",)),
    # The cheap Bosch sensor boards most people buy, by the name printed on them. The purple
    # six-pin ones have no regulator and run on 3.3 V; the four-pin GY-BME280 has one.
    CatalogPart("gy-bmp280", "GY-BMP280 pressure sensor module (on a header)", "sensor",
                "hdr-1x6",
                "BMP280 pressure and temperature sensor, I2C or SPI, 3.3 V only. Its cable plugs "
                "into this 6-pin header: VCC GND SCL SDA CSB SDO from pin 1",
                _legs("VCC", "GND", "SCL", "SDA", "CSB", "SDO"), value="GY-BMP280",
                ref_prefix="J",
                source=(
                    "components101 GY-BMP280 module, pin configuration (1 VCC 3.3 V, 2 GND, 3 SCL, "
                    "4 SDA, 5 CSB, 6 SDO; CSB pulled up on the board for I2C, SDO open 0x76)"
                ),
                check=(
                    "It has no regulator: 3.3 V only. For I2C leave CSB unwired; its address is "
                    "0x76 with SDO unwired, 0x77 with SDO to VCC. " + _CABLED_CHECK
                ),
                aliases=("BMP280", "GY-BMP280-3.3", "barometer", "pressure sensor",
                         "basınç sensörü")),
    CatalogPart("gy-bme280", "GY-BME280 sensor module, 4-pin (on a header)", "sensor",
                "hdr-1x4",
                "BME280 pressure, humidity and temperature sensor on I2C, with a 3.3 V regulator "
                "for 3.3 or 5 V. Its cable plugs into this 4-pin header: VIN GND SCL SDA from "
                "pin 1",
                _legs("VIN", "GND", "SCL", "SDA"), value="GY-BME280", ref_prefix="J",
                source=(
                    "AZ-Delivery BME280 module datasheet (pins VIN, GND, SCL, SDA; an LM6206 3.3 V "
                    "regulator and a level translator, for 3.3 or 5 V)"
                ),
                check=(
                    "The six-pin GY-BME280-3.3 is another board, with no regulator: check which "
                    "one you have before giving it 5 V. " + _CABLED_CHECK
                ),
                aliases=("BME280", "humidity sensor", "pressure sensor", "nem sensörü",
                         "basınç sensörü")),
    CatalogPart("gy-bme280-3v3", "GY-BME280-3.3 sensor module, 6-pin (on a header)", "sensor",
                "hdr-1x6",
                "BME280 pressure, humidity and temperature sensor, I2C or SPI, 3.3 V only. Its "
                "cable plugs into this 6-pin header: VCC GND SCL SDA CSB SDO from pin 1",
                _legs("VCC", "GND", "SCL", "SDA", "CSB", "SDO"), value="GY-BME280-3.3",
                ref_prefix="J",
                source=(
                    "Robu GY-BME280-3.3 module (pins VCC, GND, SCL, SDA, CSB, SDO; CSB to VCC for "
                    "I2C, SDO to GND 0x76 or VCC 0x77; supply 1.71 to 3.6 V)"
                ),
                check=(
                    "It has no regulator: 3.3 V only. For I2C tie CSB to VCC; its address is 0x76 "
                    "with SDO to GND, 0x77 with SDO to VCC. " + _CABLED_CHECK
                ),
                aliases=("BME280", "humidity sensor", "pressure sensor", "nem sensörü",
                         "basınç sensörü")),
    # Adafruit's Bosch breakouts, read off Adafruit's own Eagle boards: the same seven pins
    # in the same order on all three, the names as the silkscreen prints them.
    CatalogPart("adafruit-bme280", "Adafruit BME280 (original)", "sensor",
                "mod-7x1-p1-r1-17.78x19.05x1.6-s8.5-o0x-6.99",
                "Temperature, humidity and pressure on I2C or SPI, 3 to 5 V",
                _legs("VIN", "3Vo", "GND", "SCK", "SDO", "SDI", "CS"),
                value="Adafruit BME280", ref_prefix="U",
                source=(
                    "Adafruit BME280 Eagle board (github adafruit/Adafruit-BME280-Breakout-PCB): "
                    "the 17.78 x 19.05 mm board, the header and the nets on it; Bosch BME280 "
                    "datasheet (0x76 or 0x77 by SDO)"
                ),
                check=(
                    "VIN takes 3 to 5 V and 3Vo gives out the board's 3.3 V. For I2C, SCK is SCL "
                    "and SDI is SDA, with CS left alone: the address is 0x77, or 0x76 with SDO to "
                    "GND. For SPI, SDO is the data out. " + _MODULE_TOP
                ),
                aliases=("BME280", "humidity sensor", "pressure sensor", "barometer", "weather")),
    CatalogPart("adafruit-bmp280", "Adafruit BMP280 (original)", "sensor",
                "mod-7x1-p1-r1-17.78x19.05x1.6-s8.5-o0x-6.99",
                "Temperature and pressure on I2C or SPI, 3 to 5 V",
                _legs("VIN", "3Vo", "GND", "SCK", "SDO", "SDI", "CS"),
                value="Adafruit BMP280", ref_prefix="U",
                source=(
                    "Adafruit BMP280 Eagle board (github adafruit/Adafruit-BMP280-Breakout-PCB): "
                    "the same board as the BME280's, the header and the nets on it; Bosch BMP280 "
                    "datasheet (0x76 or 0x77 by SDO)"
                ),
                check=(
                    "VIN takes 3 to 5 V and 3Vo gives out the board's 3.3 V. For I2C, SCK is SCL "
                    "and SDI is SDA, with CS left alone: the address is 0x77, or 0x76 with SDO to "
                    "GND. For SPI, SDO is the data out. " + _MODULE_TOP
                ),
                aliases=("BMP280", "pressure sensor", "barometer")),
    CatalogPart("adafruit-bmp280-stemma-qt", "Adafruit BMP280 (STEMMA QT)", "sensor",
                "mod-7x1-p1-r1-25.4x17.78x2.9-s8.5-o0x-6.35",
                "Temperature and pressure on I2C or SPI, 3 to 5 V",
                _legs("VIN", "3Vo", "GND", "SCK", "SDO", "SDI", "CS"),
                value="Adafruit BMP280 STEMMA QT", ref_prefix="U",
                source=(
                    "Adafruit BMP280 STEMMA QT Eagle board (github "
                    "adafruit/Adafruit-BMP280-Breakout-PCB): the 25.4 x 17.78 mm board, the header "
                    "and the nets on it; Bosch BMP280 datasheet"
                ),
                check=(
                    "VIN takes 3 to 5 V and 3Vo gives out the board's 3.3 V. For I2C, SCK is SCL "
                    "and SDI is SDA, with CS left alone: the address is 0x77, or 0x76 with SDO to "
                    "GND. For SPI, SDO is the data out. The two STEMMA QT sockets carry the same "
                    "I2C. " + _MODULE_TOP
                ),
                aliases=("BMP280", "pressure sensor", "barometer", "STEMMA QT", "Qwiic")),
    # -- sound ------------------------------------------------------------------------
    CatalogPart("buzzer-active-12mm", "Active buzzer 12 mm", "sound",
                "box-2x1-p3-r1-12x12x9.5",
                "Beeps on DC, 12 mm across and 9.5 mm tall, legs 7.6 mm apart",
                _legs("+", "-"), value="Buzzer",
                source=(
                    "KiCad Buzzer_Beeper:Buzzer_12x9.5RM7.6 (pad 1 is +, as Device:Buzzer "
                    "pin 1), and drawn from its model: the 12 mm square its round body sits in"
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
                    "Buzzer_Beeper:Buzzer_12x9.5RM7.6, and drawn as its model's can at 8.5 mm"
                ),
                check=(
                    "A PASSIVE buzzer is silent on DC: drive it with a square wave from a pin "
                    "(tone() on an Arduino). Its board shows underneath, which is how to tell "
                    "it from an active one."
                ),
                aliases=("speaker", "hoparlör", "beeper", "piezo")),
    # A bare piezo disc lives glued in a case or to a panel, never on the board: two wires.
    # Murata's number stands for the sized example; the lead colours are all the catalog says.
    CatalogPart("piezo-disc-7bb", "Piezo disc, 7BB-27-4, on two wires", "sound", "wire-2",
                "Bare piezo diaphragm off the board on two wires: it sounds from a tone on a "
                "pin and stays silent on DC",
                _legs("Red", "Black"), value="Piezo disc", ref_prefix="BZ",
                source=(
                    "Murata Piezoelectric Sound Components catalog P37E-24, the diaphragms "
                    "table (murata.com/-/media/webrenewal/support/faqs/products/sound/sounder/"
                    "char/sc0002/p37e.ashx?la=en): the 7BB-27-4 is 27.0 mm across on a brass "
                    "plate, 0.54 mm thick, resonant at 4.6 kHz, 200 ohm at most, 20 nF; the "
                    "L0 version has AWG32 lead wires 50 mm long, red and black in its "
                    "drawing, and the catalog marks no polarity. ASSUMPTION: the 27 mm disc "
                    "is the common one in kits; discs of 20 mm (7BB-20-6) and 35 mm "
                    "(7BB-35-3) exist, and nothing here says which yours is, so only its two "
                    "wires are drawn"
                ),
                check=(
                    "The leads are red and black and Murata's catalog marks no polarity: "
                    "either goes to either. A disc has no driver in it, so give it a tone "
                    "(tone() on an Arduino), not DC: Murata says to avoid DC across it for "
                    "long periods, and to put a 1 to 2 kohm resistor in series with the "
                    "driving pin. Never press on the middle of the disc, which cracks the "
                    "ceramic, and do not pull on its wires."
                ),
                aliases=("piezo disc", "7BB", "7BB-27-4", "piezo element", "piezo diaphragm")),
    # The reed switch inside the Joy-IT KY-021 and every door sensor, as a bare part. Two
    # legs on the axial generator at eight pitches: the glass is 14 mm and the legs leave it
    # 2 mm to bend, so the span is the next whole number of pitches past 18 mm.
    CatalogPart("reed-switch-glass", "Reed switch, glass, 14 mm", "sensor", "axial-8h-14x2.2",
                "Glass capsule that closes when a magnet comes near, 14 mm long, legs 20.32 mm "
                "apart: no polarity",
                _legs("1", "2"), value="Reed switch", ref_prefix="SW",
                source=(
                    "Standex-Meder KSK-1A66 series datasheet (standexdetect.com/wp-content/"
                    "uploads/sites/2/2025/09/datasheet-reed-switch-series-ksk-1a66.pdf): glass "
                    "14.0 mm long and 2.2 mm across at most, leads 0.5 mm across at most, 44.3 "
                    "mm overall at most, one normally open contact of 10 W, 150 V and 0.5 A. "
                    "ASSUMPTION: the bare reeds sold in kits are about this size; the family "
                    "runs from 7 to 21 mm of glass (MK23, KSK-1A52), so measure yours. Its two "
                    "legs have no polarity, and the 8-pitch span is a choice: the legs are "
                    "long enough to span less or more"
                ),
                check=(
                    "Bend the leads at least 2 mm from the glass, and clamp the lead with "
                    "pliers between the glass and the bend, and again when you solder: "
                    "Standex-Meder says mechanical and heat stress on the leads must be "
                    "kept off the glass, and that bending them changes the switch's "
                    "sensitivity, so test it with the magnet after it is soldered. A drop "
                    "from more than 30 cm can change it or destroy it. The holes are 8 "
                    "pitches (20.32 mm) apart for a 14 mm capsule, which leaves 3.16 mm of "
                    "lead at each end."
                ),
                aliases=("reed", "reed switch", "magnetic switch", "door sensor",
                         "manyetik anahtar", "KSK-1A66")),
    CatalogPart("ds1307-tiny-rtc", "DS1307 Tiny RTC module (on a header)", "connector",
                "hdr-1x7",
                "Real-time clock on I2C. Its cable plugs into this 7-pin header: SQ DS SCL "
                "SDA VCC GND BAT from pin 1",
                _legs("SQ", "DS", "SCL", "SDA", "VCC", "GND", "BAT"), value="Tiny RTC", ref_prefix="J",
                source=(
                    "iarduino.ru's datasheet for the module "
                    "(iarduino.ru/lib/758e34773ce55f85dcf04367a89b30d0.pdf): its photograph "
                    "of the board prints SQ, DS, SCL, SDA, VCC, GND, BAT beside the header, "
                    "and its table names them SQ the programmable square-wave output, DS "
                    "the main supply's plus through 3.3 kOhm, SCL the clock and SDA the "
                    "data line of I2C, VCC the main supply's plus, GND ground, BAT the "
                    "backup supply's plus, with the module powered at 5 V, the chip's VCC "
                    "at 4.5 to 5.5 V and its VBAT at 2.0 to 3.5 V. The datasheet draws no "
                    "header, so no body is drawn and the header is the wires you run to it"
                ),
                check=(
                    "Feed VCC 5 V: the datasheet gives the module 5 V and the chip 4.5 to "
                    "5.5 V on VCC, so this is not a 3.3 V board. BAT is the plus of the "
                    "backup cell, 2.0 to 3.5 V. The datasheet lists DS as the main supply's "
                    "plus through 3.3 kOhm, so it is not a signal: it is wired to the "
                    "supply, not to a pin. SQ is the programmable square-wave output. "
                    + _CABLED_CHECK
                ),
                aliases=(
                         "DS1307", "Tiny RTC", "real time clock", "RTC module",
                         "saat modülü", "gerçek zamanlı saat",
                         )),
    CatalogPart("tp4056-module", "TP4056 charger module with protection, on six wires", "connector",
                "wire-6",
                "Charges one lithium cell from a 5 V input and cuts the load off when the "
                "cell is flat or the load shorted: the cell on B, the load on OUT",
                _legs("IN+", "IN-", "OUT+", "OUT-", "B+", "B-"), value="TP4056", ref_prefix="U",
                source=(
                    "mischianti.org's TP4056 module page "
                    "(mischianti.org/tp4056-lipo-battery-charger-high-resolution-pinout-datasheet-and-specs/): "
                    "six pads in three pairs, IN+ and IN- for the 5 V input, B+ and B- for "
                    "the cell, OUT+ and OUT- for the load, the OUT pair switched by the "
                    "protection circuit and B- joined to the protection chip rather than "
                    "straight through to OUT-. The page does not say where the pads sit on "
                    "the board, and the module is a part off the board on wires, so only "
                    "its six wires are drawn. A plain TP4056 board without the protection "
                    "chips is not this part; that page does not describe its pads"
                ),
                check=(
                    "Put the load on OUT+ and OUT-, not on B+ and B-: the protection "
                    "switches OUT, so a load on B goes round it. OUT- is not the same wire "
                    "as B-: it is the protection's switch, and it opens on overdischarge "
                    "(2.4 V) or overcurrent (3 A); the page says a tripped module is often "
                    "reset by briefly applying the input. The input is recommended at 4.5 "
                    "to 5.5 V, 8 V at the very most."
                ),
                aliases=(
                         "TP4056", "lithium charger", "LiPo charger", "Li-ion charger",
                         "18650 charger", "battery charger module", "pil şarj modülü",
                         "lityum şarj",
                         )),
    CatalogPart("mt3608-boost", "MT3608 boost module, on four wires", "regulator",
                "wire-4",
                "Steps a voltage up: 2 to 24 V in, 5 to 28 V out, set with its trimmer",
                _legs("VIN+", "VIN-", "VOUT+", "VOUT-"), value="MT3608", ref_prefix="U",
                source=(
                    "Components101's MT3608 module page "
                    "(components101.com/modules/mt3608-2a-dc-dc-step-up-power-module), its "
                    "pin table: VIN+ the voltage input, VIN- ground, VOUT+ the voltage "
                    "output, VOUT- ground; input 2 to 24 V DC, output 5 to 28 V DC. The "
                    "page does not say where the pads sit, and the module is a part off the "
                    "board on wires, so only its four wires are drawn"
                ),
                check=(
                    "A boost converter's output must stay above its input: if turning the "
                    "trimmer changes nothing, the output equals the input, and a 12 V input "
                    "cannot give 9 V. Set the trimmer with the output unloaded and a meter "
                    "on VOUT+ and VOUT- before you connect what it feeds. Components101 "
                    "says the output must always be higher than the input, and its page "
                    "mentions no protection against a reversed input, so check VIN+ against "
                    "the supply's plus."
                ),
                aliases=(
                         "MT3608", "boost converter", "step up converter",
                         "voltage booster", "yükseltici", "gerilim yükseltici",
                         )),
    CatalogPart("xl6009-boost", "XL6009 boost module, on four wires", "regulator",
                "wire-4",
                "Steps a voltage up, with a 4 A limit: 3 to 32 V in, 5 to 35 V out, set with "
                "its trimmer",
                _legs("IN+", "IN-", "OUT+", "OUT-"), value="XL6009", ref_prefix="U",
                source=(
                    "Components101's XL6009 module page "
                    "(components101.com/modules/xl6009-dc-dc-step-down-voltage-regulator-module), "
                    "its pin table: IN+ the positive input, IN- ground, OUT+ the regulated "
                    "positive output, OUT- ground; input 3 to 32 V, output 5 to 35 V "
                    "(adjustable), 4 A at most. The page calls the module a step-down "
                    "converter in its address and in places and a step-up one elsewhere; the "
                    "table is the same either way, and the XL6009 modules sold as adjustable "
                    "4 A converters are boost ones. It does not say where the pads sit, and "
                    "the module is a part off the board on wires, so only its four wires "
                    "are drawn"
                ),
                check=(
                    "A boost converter's output must stay above its input: if turning the "
                    "trimmer changes nothing, the output equals the input, and a 12 V input "
                    "cannot give 9 V. Set the trimmer with the output unloaded and a meter on "
                    "OUT+ and OUT- before you connect what it feeds. Components101 recommends "
                    "a heat sink above 15 W of output, and its page mentions no protection "
                    "against a reversed input, so check IN+ against the supply's plus."
                ),
                aliases=(
                         "XL6009", "XL6009 boost", "4A boost", "boost 4A", "yükseltici 4A",
                         "XL6009 yükseltici",
                         )),
    CatalogPart("ams1117-33-module","AMS1117-3.3 regulator module, on three wires", "regulator",
                "wire-3",
                "Fixed 3.3 V linear regulator on a small board: 4.75 to 12 V in, 800 mA at "
                "most",
                _legs("VIN", "GND", "OUT"), value="AMS1117-3.3", ref_prefix="U",
                source=(
                    "ANMBEST's AMS1117-3.3 module manual "
                    "(manuals.plus/asin/B07CP4P5XJ.pdf): the pins VIN, GND and OUT, input "
                    "4.75 to 12 V, output 3.3 V fixed, 800 mA at most with a current limit "
                    "of 900 to 1500 mA, the board 8.6 x 12.33 mm with a row of two pins on "
                    "each side. The manual gives no pin pitch, so no body is drawn: the "
                    "three wires are the part's pads, the one GND serving input and output"
                ),
                check=(
                    "Its manual says a reversed input shorts the module: check VIN against "
                    "the supply's plus. It is a linear regulator, so what it drops from the "
                    "input is heat: 5 V in and 500 mA out is 0.85 W in the chip. Input and "
                    "output share the one GND."
                ),
                aliases=(
                         "AMS1117", "3.3V regulator", "3.3V module", "LDO module",
                         "regülatör modülü", "3.3 V regülatör",
                         )),
    CatalogPart("st7735-tft-18", "TFT 1.8 in ST7735 128x160 module (on a header)", "display",
                "hdr-1x8",
                "1.8 inch colour TFT, 128 x 160, on SPI. Its cable plugs into this 8-pin "
                "header: VCC GND CS RESET A0 SDA SCK LED from pin 1",
                _legs("VCC", "GND", "CS", "RESET", "A0", "SDA", "SCK", "LED"), value="ST7735 TFT", ref_prefix="J",
                source=(
                    "LCDWiki's page for the 1.8 inch SPI module ST7735S, SKU MSP1803 "
                    "(lcdwiki.com/1.8inch_SPI_Module_ST7735S_SKU:MSP1803), its pin table 1 "
                    "to 8: VCC, GND, CS, RESET, A0, SDA, SCK, LED, with VCC 3.3 to 5 V and "
                    "the logic IO 3.3 V (TTL). The page draws no header and does not say "
                    "the table is the order on the board, so no body is drawn and the "
                    "header is the wires you run to it"
                ),
                check=(
                    "The page gives the logic IO as 3.3 V (TTL), so a 5 V board wants level "
                    "shifting on CS, RESET, A0, SDA and SCK. CS and RESET are low-level "
                    "enable and low-level reset; A0 selects register (high) or data (low); "
                    "SDA is the SPI write-data line here, not I2C, and SCK its clock. LED "
                    "is the backlight: high lights it, and it says to tie 3.3 V to it for "
                    "always on. "
                    + _CABLED_CHECK
                ),
                aliases=(
                         "ST7735", "ST7735S", "TFT display", "1.8 TFT", "128x160 TFT",
                         "renkli ekran", "TFT ekran",
                         )),
    CatalogPart("adafruit-ili9341-tft", "Adafruit 2.8 in TFT touch breakout, ILI9341 (on a header)",
                "display", "hdr-1x20",
                "2.8 inch colour TFT, 240 x 320, with a resistive touchscreen and a microSD "
                "socket, on SPI. Its cable plugs into this 20-pin header: GND Vin 3Vo CLK MISO "
                "MOSI CS D/C RST Lite Y+ X+ Y- X- IM3 IM2 IM1 IM0 CCS CD from pin 1",
                _legs("GND", "Vin", "3Vo", "CLK", "MISO", "MOSI", "CS", "D/C", "RST", "Lite",
                      "Y+", "X+", "Y-", "X-", "IM3", "IM2", "IM1", "IM0", "CCS", "CD"),
                value="ILI9341 TFT", ref_prefix="J",
                source=(
                    "Adafruit's own Eagle board for the 2.8 inch TFT breakout "
                    "(github.com/adafruit/2.8-TFT-Breakout-PCB, 'Adafruit 2.8 TFT Breakout v2'), "
                    "the 20-pin SPI header JP2 along one short edge: pad 1 at the GND end and "
                    "every name read off that header's silkscreen, each pad's net checked "
                    "against the board's nets. The nets are named for the parallel interface, so "
                    "the pad marked CLK is on the net LCD_RS and D/C on LCD_WR: the ILI9341's "
                    "D/CX (SCL) and WRX (D/CX) pins, which change their job in SPI mode. The "
                    "board's second 20-pin header, JP1, is the 8-bit parallel one and is not "
                    "this part"
                ),
                check=(
                    "Vin takes 3 to 5 V and a 3.3 V regulator on the board makes 3Vo, which is "
                    "an output and not a second supply. CS, D/C, CLK, RST, MOSI and CCS go "
                    "through 74LVC245 level shifters on the board, so 3.3 V and 5 V logic both "
                    "do; MISO is a 3.3 V output. Lite is the base of the backlight's transistor: "
                    "high lights it, and tying it to Vin keeps it lit. X+, Y+, X- and Y- are the "
                    "resistive touchscreen's four wires, and CCS and CD the microSD socket's chip "
                    "select and card detect, which share CLK, MISO and MOSI. IM0 to IM3 are the "
                    "controller's interface-mode inputs, set by the solder jumpers beside them; "
                    "the board's silkscreen says to close IM1, IM2 and IM3 for SPI. Other "
                    "ILI9341 modules sold as 2.8 inch SPI carry a shorter header with other "
                    "names, so compare the names printed on the board with these before using "
                    "it. " + _CABLED_CHECK
                ),
                aliases=("ILI9341", "TFT touch", "TFT touchscreen", "2.8 TFT", "touchscreen",
                         "Adafruit 1770", "dokunmatik ekran", "dokunmatik TFT")),
    CatalogPart("nokia-5110","Nokia 5110 LCD module (on a header)", "display",
                "hdr-1x8",
                "84 x 48 monochrome LCD (PCD8544) on SPI. Its cable plugs into this 8-pin "
                "header: RST CE DC DIN CLK VCC LIGHT GND from pin 1",
                _legs("RST", "CE", "DC", "DIN", "CLK", "VCC", "LIGHT", "GND"), value="Nokia 5110", ref_prefix="J",
                source=(
                    "microcontrollerslab.com's Nokia 5110 pin table "
                    "(microcontrollerslab.com/nokia5110-lcd-pinout-arduino-interfacing-datasheet/), "
                    "numbered 1 to 8: RST, CE, DC, DIN, CLK, VCC, BL (backlight), GND, with "
                    "VCC 2.7 to 3.3 V; Espruino's PCD8544 page (espruino.com/PCD8544) names "
                    "the same eight pins, with LIGHT for the backlight, in the opposite "
                    "order in its wiring table. Neither draws the board, so no body is "
                    "drawn and the header is the wires you run to it"
                ),
                check=(
                    "Feed VCC 3.3 V: the first page gives 2.7 to 3.3 V, and neither page "
                    "says the signal pins tolerate 5 V, so a 5 V Arduino wants a divider or "
                    "level shifter on RST, CE, DC, DIN and CLK. The boards print the "
                    "backlight pin as LIGHT or BL, and the pages differ on it: Espruino "
                    "wires it to GND for backlight on, the other says it lights when "
                    "powered. Read your seller's note before you tie it. The second page "
                    "numbers the pins from the other end, GND first. "
                    + _CABLED_CHECK
                ),
                aliases=(
                         "Nokia 5110", "PCD8544", "Nokia LCD", "84x48 LCD", "Nokia ekran",
                         )),
    CatalogPart("ttp223-touch", "TTP223 touch module (on a header)", "sensor",
                "hdr-1x3",
                "Capacitive touch button on a 24 mm board: its output goes high while "
                "touched. Its cable plugs into this 3-pin header: GND VCC SIG from pin 1",
                _legs("GND", "VCC", "SIG"), value="TTP223", ref_prefix="J",
                source=(
                    "AZ-Delivery's TTP223B datasheet "
                    "(cdn.shopify.com/s/files/1/1509/1638/files/TTP223B_Touch_Sensor_Modul_Datenblatt_AZ-Delivery_Vertriebs_GmbH.pdf), "
                    "its pinout page printing GND, VCC, SIG down the edge of the 24 x 24 mm "
                    "board, 2.0 to 5.5 V, the output low until touched, a response of 60 ms "
                    "in fast mode and 220 ms in low power. The page draws no header, so no "
                    "body is drawn and the header is the wires you run to it"
                ),
                check=(
                    "In AZ-Delivery's datasheet the output is low until the body touches "
                    "the sensor and high while it does; with no touch for more than 12 s "
                    "the sensor falls into its low-power mode, where it answers in 220 ms "
                    "against 60 ms in fast mode. Other boards of the part may print its "
                    "three pins in another order. "
                    + _CABLED_CHECK
                ),
                aliases=(
                         "TTP223", "touch sensor", "capacitive touch", "touch button",
                         "dokunmatik sensör", "dokunmatik buton",
                         )),
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
    CatalogPart("esp32-devkit-v1", "ESP32 DevKit V1 (30-pin)", "module",
                "mod-2x15-p10-r1-28x51.1x3.2-s8.5-o-0.3x1.81",
                "ESP32-WROOM-32 dev board, 30 pins, rows 25.4 mm apart",
                _two_columns(_DEVKIT_V1_LEFT, _DEVKIT_V1_RIGHT), ref_prefix="U",
                value="ESP32 DevKit V1",
                source=(
                    "Four makers' KiCad footprints of it, which agree pin for pin (15 a row, the "
                    "rows 25.4 mm apart); the names as its silkscreen prints them; the 51.1 x 28.0 "
                    "mm board measured on Edwiyanto's photograph (Wikimedia Commons, CC BY-SA 4.0), "
                    "rectified on its pads"
                ),
                check=(
                    "Sold by many makers: the 30 pins and their order are fixed, the parts' places "
                    "vary from one to the next, and this drawing is one of them to about half a "
                    "millimetre. The 38-pin ESP32-DevKitC is a different board with its own entry: "
                    "count your pins. Its pins are 3.3 V; VIN takes 5 V. VP, VN, D34 and D35 are "
                    "inputs only, and nothing may hold D12 high as it starts (it sets the flash "
                    "voltage). " + _MODULE_TOP
                ),
                aliases=("ESP32 DOIT", "DOIT", "ESP-WROOM-32", "ESP32")),
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
    CatalogPart("sparkfun-pro-mini", "SparkFun Arduino Pro Mini 328", "module",
                "mod-2x12-p6-r1-17.78x33.02x2.5-s8.5-o0x-1.27",
                "ATmega328P board, 24 pins, rows 15.24 mm apart: 5 V at 16 MHz or 3.3 V at 8 MHz",
                _two_columns(_PRO_MINI_LEFT, _PRO_MINI_RIGHT), ref_prefix="U",
                value="Pro Mini 328",
                source=(
                    "SparkFun Arduino Pro Mini 328 Eagle board (github "
                    "sparkfun/Arduino_Pro_Mini_328, Hardware/Arduino-Pro-Mini.brd): the 0.7 x "
                    "1.3 inch board, both 12-pin rows 0.6 inch apart, the names printed beside "
                    "them and the nets they are on"
                ),
                check=(
                    "A4 and A5 (I2C) and A6 and A7 are on two pairs of pads inside the RAW "
                    "row, off the 0.1 inch grid: wire them on their own. The six pads at the "
                    "end are its FTDI programming header. RAW is the regulator's input and VCC "
                    "its output, 5 V or 3.3 V by the version. Clones share the 24 header "
                    "pins; A4–A7 and the FTDI pads may sit elsewhere, so wire those from the "
                    "board in your hand. " + _MODULE_TOP
                ),
                aliases=("Pro Mini", "Arduino Pro Mini", "DEV-11113", "DEV-11114",
                         "ATmega328P", "Arduino")),
    CatalogPart("sparkfun-logic-level-converter",
                "SparkFun Logic Level Converter - Bi-Directional", "module",
                "mod-6x2-p1-r4-15.24x12.7x1.6-s8.5",
                "Four channels between two logic levels, both ways: 12 pins, rows 10.16 mm apart",
                _legs("HV1", "HV2", "HV", "GND", "HV3", "HV4",
                      "LV1", "LV2", "LV", "GND", "LV3", "LV4"),
                value="Logic Level Converter", ref_prefix="U",
                source=(
                    "SparkFun Logic Level Converter - Bi-Directional Eagle board (github "
                    "sparkfun/Logic_Level_Bidirectional, Hardware/Logic_Level_Bidirectional"
                    ".brd): the 0.6 x 0.5 inch board, both 6-pin rows 0.4 inch apart, the "
                    "names printed beside them and the nets they are on"
                ),
                check=(
                    "HV takes the higher supply and LV the lower (5 V and 3.3 V, say), with "
                    "GND; then HV1 is LV1 at the other level, and so on for all four. Each "
                    "channel is a BSS138 with a 10k pull-up to each side, so a rising edge is "
                    "only as quick as that 10k makes it. " + _MODULE_TOP
                ),
                aliases=("level shifter", "level converter", "BOB-12009", "BSS138",
                         "3.3 V to 5 V", "I2C")),
    CatalogPart("raspberry-pi-pico", "Raspberry Pi Pico", "module",
                "mod-2x20-p7-r1-21x52.3x3.5-s8.5-o0x-0.65",
                "RP2040 board, 40 pins, rows 17.78 mm apart",
                _two_columns(_PICO_LEFT, _PICO_RIGHT), ref_prefix="U",
                source=(
                    "KiCad Module:RaspberryPi_Pico_Common_THT footprint; pin names from the "
                    "Raspberry Pi Pico datasheet pinout"
                ),
                check=_MODULE_TOP),
    CatalogPart("sparkfun-hx711", "SparkFun HX711 load cell amplifier", "module",
                "mod-2x5-p11-r1-30.48x22.86x2-s8.5",
                "24-bit ADC for a load cell, two 1 x 5 headers 27.94 mm apart",
                _two_columns(("AVDD", "GND", "A-", "A+", "GND"), ("VDD", "VCC", "DAT", "SCK", "GND")),
                ref_prefix="U", value="HX711",
                source=(
                    "SparkFun HX711 Load Cell Amplifier breakout, its Eagle board: 30.48 x 22.86 mm, "
                    "a 1 x 5 header down each side (left AVDD, GND, A-, A+, GND; right VDD, VCC, "
                    "DAT, SCK, GND) and a separate 2-pin B+ and B- header on the board's middle"
                ),
                check=(
                    "The load cell goes to A+ and A-, a second one to the 2-pin B+ and B- header, "
                    "which is off the pin grid. AVDD is made on the board from VCC and brought out "
                    "for the bridge; VCC and VDD are both inputs, so feed them from one supply. "
                    "The green HX711 boards sold under the same name carry a different header, so "
                    "compare the names printed on the board with these before using it. "
                    + _MODULE_TOP
                ),
                aliases=("HX711", "load cell", "loadcell", "scale", "weight", "yük hücresi",
                         "terazi")),
    CatalogPart("adafruit-rfm9x-lora", "Adafruit RFM9x LoRa radio breakout (on a header)",
                "connector", "hdr-1x9",
                "LoRa packet radio (RFM95W, 868 or 915 MHz) on SPI. Its cable plugs into this "
                "9-pin header: VIN GND EN G0 SCK MISO MOSI CS RST from pin 1",
                _legs("VIN", "GND", "EN", "G0", "SCK", "MISO", "MOSI", "CS", "RST"),
                value="RFM9x", ref_prefix="J",
                source=(
                    "Adafruit's own Eagle board for its RFM69 and LoRa radio breakouts "
                    "(github.com/adafruit/Adafruit-RFM-LoRa-Radio-Breakout-PCB, products "
                    "3070 to 3073, one board for the RFM69HCW and RFM95W radios), the 9-pin "
                    "header JP3 along the long edge: pad 1 at VIN and every name read off "
                    "the silkscreen, each pad's net checked against the board's nets. The "
                    "board's second header, a 5-pin one for the radio's G1 to G5, is not "
                    "this part, and neither is the antenna's u.FL or SMA pad"
                ),
                check=(
                    "VIN takes 3.3 to 5.5 V by the board's silkscreen: a 3.3 V regulator "
                    "makes the radio's supply, and EN is its enable, pulled up to VIN by a "
                    "resistor on the board, so leave it unwired to keep the radio on. SCK, "
                    "MOSI, CS and RST go through a level shifter on the board, so the "
                    "silkscreen calls the SPI logic 3 to 5 V safe, and CS and RST are held "
                    "high by resistors to VIN. MISO and G0 come straight from the radio at 3 V; "
                    "G0 is its DIO0 line. The radio needs an antenna for its band: at "
                    "868 or 915 MHz a quarter-wave wire is about 8 cm. The same board is "
                    "sold with an RFM69HCW radio, with this header, so check what is "
                    "printed on yours. " + _CABLED_CHECK
                ),
                aliases=("RFM95", "RFM9x", "RFM95W", "LoRa", "LoRa radio", "packet radio",
                         "uzun menzilli radyo")),
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
    CatalogPart("nodemcu-devkit-1.0", "NodeMCU DevKit 1.0 (ESP-12E)", "module",
                "mod-2x15-p9-r1-25.4x48.26x3.2-s8.5",
                "ESP8266 board, 30 pins, rows 22.86 mm apart",
                _two_columns(_NODEMCU_LEFT, _NODEMCU_RIGHT), ref_prefix="U",
                value="NodeMCU",
                source=(
                    "NodeMCU DevKit 1.0 Gerbers, PCB print and schematic (github "
                    "nodemcu/nodemcu-devkit-v1.0): the 25.4 x 48.26 mm board, both 15-pin rows 0.9 "
                    "inch apart, the names printed beside them and the schematic IO CONN sheet "
                    "behind them"
                ),
                check=(
                    "Its pins are 3.3 V logic. VIN is the 5 V rail: USB feeds it through a Schottky "
                    "diode, or feed it yourself. D3, D4 and D8 are GPIO0, GPIO2 and GPIO15, which "
                    "choose how it boots: nothing may hold D3 or D4 low, or D8 high, as it starts. "
                    "SD0 to SD3, CMD and CLK are the module's flash: leave them free. LoLin's wider "
                    "\"V3\", rows 27.94 mm apart, is another board. " + _MODULE_TOP
                ),
                aliases=("NodeMCU", "ESP8266", "ESP-12E", "Amica", "CP2102")),
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
                "mod-2x4-p1-r1-29x15.25x3.8-s8.5-o11.73x1.82",
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
                    "board. Its crystal stands 3.6 mm, the tallest thing on it."
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
                    "the same, on another board: it is drawn as the block."
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


@dataclass(frozen=True, slots=True)
class NotOffered:
    """A part somebody looks for and the library deliberately does not have: why, in one line
    the Library shows, and the catalog ids it offers instead."""

    reason: str
    instead: tuple[str, ...]


_XH_INSTEAD = ("jst-xh-2", "jst-xh-3", "jst-xh-4", "jst-xh-2-side", "jst-xh-3-side", "jst-xh-4-side")

#: The connector families that do not go into a 0.1 in board: (the series' word, its pitch
#: as sellers write it, what to say). A series is matched with "JST" beside it or with its
#: pitch -- "JST PH", "jst-ph", "PH2.0" -- never on its two letters alone, which "phone" and
#: "photo" begin with too.
NOT_OFFERED: tuple[tuple[str, str, NotOffered], ...] = (
    ("ph", "2.0", NotOffered(
        "JST PH is 2.0 mm a pin and does not go into a 0.1 in board's holes. A JST XH "
        "(2.5 mm) does, up to 4 pins.",
        _XH_INSTEAD,
    )),
    ("zh", "1.5", NotOffered(
        "JST ZH is 1.5 mm a pin and does not go into a 0.1 in board's holes. A JST XH "
        "(2.5 mm) does, up to 4 pins.",
        _XH_INSTEAD,
    )),
    ("sh", "1.0", NotOffered(
        "JST SH is 1.0 mm a pin, a surface-mount part that does not go into a 0.1 in board's "
        "holes. A JST XH (2.5 mm) does, up to 4 pins.",
        _XH_INSTEAD,
    )),
    ("vh", "3.96", NotOffered(
        "JST VH is 3.96 mm a pin, which no row of 0.1 in holes matches. For power, a 5.08 mm "
        "screw terminal or a JST XH does the job.",
        ("power-terminal-2", *_XH_INSTEAD),
    )),
)


def not_offered(query: str) -> NotOffered | None:
    """Why the library has nothing called ``query``, where it deliberately has not: a JST
    series on another pitch than a perfboard's. ``None`` for anything else -- "PH" alone,
    "phone", "photo", or a JST the library does have."""
    words = re.findall(r"[a-z]+|\d+(?:\.\d+)?", query.lower())
    for series, pitch, answer in NOT_OFFERED:
        if series not in words:
            continue
        if "jst" in words or pitch in words or pitch.rstrip("0").rstrip(".") in words:
            return answer
    return None


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


# ---------------------------------------------------------------------------
# How well a search finds something
# ---------------------------------------------------------------------------

#: Best first. A search ranks what it finds by WHERE it found it, because what somebody
#: typing "resistor" wants is the resistor, not the inductor whose summary says it lies
#: "flat like a resistor" nor the photoresistor whose name has the word inside another:
#:
#: * the name STARTS with what was typed -- "Resistor (axial, 4-hole span)", "LED, 5 mm";
#: * every word starts a word of its name, its kind or one of its aliases ("power" names
#:   "Power in, 2-pin header" and the power category, "switch" the tact switch);
#: * every word is somewhere in those, inside a word ("resistor" in "photoresistor");
#: * every word is only in what it SAYS about itself, its summary ("power" in a
#:   TIP31C's "NPN power, 100 V, 3 A", "led" inside a word of a Turkish summary).
RANK_NAME_STARTS = 0
RANK_NAMED = 1
RANK_IN_NAME = 2
RANK_SAID = 3


def search_rank(
    text: str,
    *,
    names: Sequence[str],
    said: Sequence[str] = (),
    numbers: Iterable[str] = (),
    fold: Callable[[str], str] = str.lower,
) -> int | None:
    """How well ``text`` finds a thing called ``names`` (its name first, then any other
    name, kind or alias it answers to, in either language) that says ``said`` about itself
    and carries ``numbers`` (a part number "LM358N" finds), as one of the ``RANK_*``, best
    lowest -- or None when some word of it finds nothing.

    THE ONE RANKING, for a catalog part (``part_rank``) and for a bare package alike, so the
    Parts tree, the package picker and the MCP server's ``list_catalog`` put the same thing
    first for the same words. An empty search finds everything, equally.
    """
    words = fold(text).split()
    if not words:
        return RANK_NAME_STARTS
    numbered = {_squeezed(fold(number)) for number in numbers}
    numbered = {number for number in numbered if len(number) >= 4}
    if names and fold(names[0]).startswith(" ".join(words)):
        return RANK_NAME_STARTS
    called = fold(" ".join(names))
    if _all_found(words, called, numbered, starts=True):
        return RANK_NAMED
    if _all_found(words, called, numbered, starts=False):
        return RANK_IN_NAME
    if _all_found(words, fold(" ".join((*names, *said))), numbered, starts=False):
        return RANK_SAID
    return None


def _all_found(words: Sequence[str], haystack: str, numbers: set[str], *, starts: bool) -> bool:
    squeezed = _squeezed(haystack)
    begins: set[int] = set()
    at = 0
    for token in haystack.split():
        begins.add(at)
        at += len(_squeezed(token))
    return all(
        _word_finds(word, haystack, squeezed, numbers, begins if starts else None) for word in words
    )


def part_rank(
    part: CatalogPart,
    text: str,
    *,
    names: Sequence[str] = (),
    said: Sequence[str] = (),
    fold: Callable[[str], str] = str.lower,
) -> int | None:
    """``search_rank`` for a catalog part: its name first, then its id, its kind and the
    words for it (``_CATEGORY_WORDS``), its aliases and any ``names`` the caller adds -- the
    window adds the name in its own language FIRST, so "direnç" starts "Direnç ..." -- and
    as what it says, its summary and any ``said`` (the summary in the window's language)."""
    kind = (part.category, *_CATEGORY_WORDS.get(part.category, ()))
    return search_rank(
        text,
        names=(*names, part.name, part.id, *kind, *part.aliases),
        said=(part.summary, *said),
        numbers=(part.id, part.placed_value),
        fold=fold,
    )


def search_catalog(text: str = "", category: CatalogCategory | None = None) -> list[CatalogPart]:
    """Parts every word of ``text`` finds, best first by ``part_rank``, each rank in catalog
    order."""
    ranked = [
        (rank, index, part)
        for index, part in enumerate(CATALOG)
        if (category is None or part.category == category)
        and (rank := part_rank(part, text)) is not None
    ]
    return [part for _rank, _index, part in sorted(ranked, key=lambda found: found[:2])]
