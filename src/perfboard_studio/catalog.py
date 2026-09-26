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
shows beside the part. A part whose pinout differs between makers is not in here at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .model import PartSymbol, PerfDocument, PinNames

#: What a part is, for grouping a list of them. Engine text; the interface translates the
#: group headings itself.
CatalogCategory = Literal[
    "transistor",
    "mosfet",
    "regulator",
    "diode",
    "protection",
    "sensor",
    "ic",
    "switch",
    "module",
]

#: The order the groups are shown in: the things a board is mostly made of first.
CATEGORY_ORDER: tuple[CatalogCategory, ...] = (
    "transistor",
    "mosfet",
    "regulator",
    "diode",
    "protection",
    "sensor",
    "ic",
    "switch",
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
    "protection": "F",
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

_SWITCH_LEGS = (
    "The two legs on one side are the switched pair; the two straight across are one "
    "strip. A meter on continuity says which: across reads shut before the button is "
    "pressed."
)

_MODULE_TOP = (
    "The height of what is on the board is an estimate, and so is its colour; the pins, "
    "the rows and the board outline are measured."
)


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
    # -- protection -------------------------------------------------------------------
    CatalogPart("ptc-radial", "PTC resettable fuse", "protection", "c-disc-d8-p2-t3",
                "Polymer PTC (polyfuse), radial, leads 5 mm apart",
                symbol="fuse", value="PTC", ref_prefix="F",
                source="Bourns MF-R series: radial, 5.1 mm lead spacing",
                check=(
                    "Its size grows with its hold current: if yours is larger than 8 mm, "
                    "describe it as a disc capacitor of its real size and mark it a fuse."
                )),
    # -- sensors ----------------------------------------------------------------------
    CatalogPart("lm35", "LM35", "sensor", "to92", "Temperature sensor, 10 mV per degree C",
                _legs("+VS", "VOUT", "GND"), ref_prefix="U",
                source=f"TI LM35 datasheet, LP package; {_TO92_ORDER}", check=_CHECK_LEGS),
    CatalogPart("ds18b20", "DS18B20", "sensor", "to92",
                "Temperature sensor, 1-Wire, needs a 4.7k pull-up on DQ",
                _legs("GND", "DQ", "VDD"), ref_prefix="U",
                source=f"Analog Devices DS18B20 datasheet; {_TO92_ORDER}", check=_CHECK_LEGS),
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
                ref_prefix="U", source="Broadcom 6N137 datasheet"),
    CatalogPart("pc817", "PC817", "ic", "dip-4", "Optocoupler, transistor output",
                _legs("A", "K", "E", "C"), ref_prefix="U", source="Sharp PC817 datasheet"),
    CatalogPart("mcp2551", "MCP2551", "ic", "dip-8", "CAN transceiver, 5 V, 1 Mbit/s",
                _legs("TXD", "VSS", "VDD", "RXD", "VREF", "CANL", "CANH", "RS"),
                ref_prefix="U", source="Microchip MCP2551 datasheet, PDIP"),
    CatalogPart("max485", "MAX485", "ic", "dip-8", "RS-485 transceiver, half duplex, 5 V",
                _legs("RO", "RE", "DE", "DI", "GND", "A", "B", "VCC"),
                ref_prefix="U", source="Analog Devices MAX485 datasheet, PDIP"),
    CatalogPart("74hc595", "74HC595", "ic", "dip-16", "8-bit shift register, latched outputs",
                _legs("QB", "QC", "QD", "QE", "QF", "QG", "QH", "GND",
                      "QH'", "SRCLR", "SRCLK", "RCLK", "OE", "SER", "QA", "VCC"),
                ref_prefix="U", source="TI SN74HC595 datasheet, N package"),
    CatalogPart("uln2003a", "ULN2003A", "ic", "dip-16",
                "Seven Darlington sinks, 50 V, 500 mA, with flyback diodes",
                _legs("IN1", "IN2", "IN3", "IN4", "IN5", "IN6", "IN7", "GND",
                      "COM", "OUT7", "OUT6", "OUT5", "OUT4", "OUT3", "OUT2", "OUT1"),
                ref_prefix="U", source="TI ULN2003A datasheet, N package"),
    CatalogPart("l293d", "L293D", "ic", "dip-16", "Dual H-bridge, 600 mA, with clamp diodes",
                _legs("EN12", "1A", "1Y", "GND", "GND", "2Y", "2A", "VCC2",
                      "EN34", "3A", "3Y", "GND", "GND", "4Y", "4A", "VCC1"),
                ref_prefix="U", source="TI L293D datasheet, NE package",
                check="The four GND pins are also its heatsink: solder them to a copper area."),
    CatalogPart("mcp2515", "MCP2515", "ic", "dip-18", "CAN controller, SPI",
                _legs("TXCAN", "RXCAN", "CLKOUT", "TX0RTS", "TX1RTS", "TX2RTS", "OSC2",
                      "OSC1", "VSS", "RX1BF", "RX0BF", "INT", "SCK", "SI", "SO", "CS",
                      "RESET", "VDD"),
                ref_prefix="U", source="Microchip MCP2515 datasheet, PDIP"),
    CatalogPart("74hc245", "74HC245", "ic", "dip-20",
                "Octal bus transceiver (74HCT245 for 3.3 V in, 5 V out)",
                _legs("DIR", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "GND",
                      "B8", "B7", "B6", "B5", "B4", "B3", "B2", "B1", "OE", "VCC"),
                ref_prefix="U", source="TI SN74HC245 datasheet, N package"),
    CatalogPart("atmega328p", "ATmega328P", "ic", "dip-28", "8-bit AVR, the Arduino Uno's",
                _legs("RESET", "RXD", "TXD", "PD2", "PD3", "PD4", "VCC", "GND", "XTAL1",
                      "XTAL2", "PD5", "PD6", "PD7", "PB0", "PB1", "PB2", "MOSI", "MISO",
                      "SCK", "AVCC", "AREF", "GND", "PC0", "PC1", "PC2", "PC3", "PC4", "PC5"),
                ref_prefix="U", source="Microchip ATmega328P datasheet, PDIP"),
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
    CatalogPart("wemos-d1-mini", "WEMOS D1 mini", "module",
                "mod-2x8-p9-r1-25.6x34.2x3.5-s8.5",
                "ESP8266 board, 16 pins, rows 22.86 mm apart",
                _two_columns(_D1_MINI_LEFT, _D1_MINI_RIGHT), ref_prefix="U",
                source="KiCad RF_Module:WEMOS_D1_mini_light footprint and WEMOS_D1_mini symbol",
                check=_MODULE_TOP),
)

_BY_ID: dict[str, CatalogPart] = {part.id: part for part in CATALOG}


def catalog_part(part_id: str) -> CatalogPart | None:
    """One part by its id, or ``None``."""
    return _BY_ID.get(part_id.strip().lower())


def search_catalog(text: str = "", category: CatalogCategory | None = None) -> list[CatalogPart]:
    """Parts whose id, name or summary contain every word of ``text``, in catalog order."""
    words = text.lower().split()
    found = []
    for part in CATALOG:
        if category is not None and part.category != category:
            continue
        haystack = f"{part.id} {part.name} {part.summary} {part.category}".lower()
        if all(word in haystack for word in words):
            found.append(part)
    return found
