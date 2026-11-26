"""What each pin of a microcontroller can do besides being a pin, read from its maker.

A pinout card answers the question a builder otherwise takes to a search engine: which pin
is PWM, which is the I2C clock, which one must not be pulled low at power-up. Those are
FACTS about the silicon, printed in the maker's "alternate port functions" table, and this
module holds them as data -- never as a picture of somebody else's card, whose layout and
colours are theirs.

**ONE FACT, ONE PLACE.** The functions belong to the MCU's PORTS, not to a board: PD3 is
INT1 and OC2B whether it is pin 5 of a bare ATmega328P or the pin an Arduino Nano prints
"D3" beside. So :data:`MCU_FUNCTIONS` is keyed by MCU and port, and :data:`BOARD_MAP` says,
for every catalogue part, which MCU it carries and which port each of its pins is. The
Nano, the Pro Mini and the bare chip read one table, and a mistake in it is made once.

**A SOURCE BESIDE EVERY TABLE**, as ``catalog.PIN_ROLES`` keeps one: each entry names the
document it was read from, and a part not read from its maker's document yet is listed in
:data:`_FUNCTIONS_WAITING` with what is missing, rather than filled from memory.

**WARNINGS ARE DATA, NOT PROSE.** A pin with an LED on it or a fuse behind it carries a
warning id (:data:`PinWarning`); the card says it in words where it is shown, through the
phrasebook, so the facts stay comparable and the words translatable.

Hangs off nothing at all -- tables and lookups, like ``ledcolour``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

#: What kind of thing a pin's alternate function is. The card groups and colours by kind,
#: and its legend lists only the kinds a card uses. ``TypeAlias`` because ``get_args``
#: reads it at run time (the legend's order and the completeness test).
FunctionKind: TypeAlias = Literal[  # noqa: UP040
    "pwm",  # a timer's compare output: analogWrite on an Arduino
    "adc",  # an analogue-to-digital converter input
    "int",  # an external interrupt with its own vector (INT0, INT1)
    "uart",  # asynchronous serial
    "spi",  # SPI, and the in-system programming pins that share it
    "i2c",  # I2C / TWI, and the USI's two-wire mode
    "timer",  # a timer's clock or capture input
    "comparator",  # the analogue comparator's inputs
    "clock",  # crystal, external clock in, system clock out
    "reset",  # the reset input
    "debug",  # an on-chip debugger's wire
    "ref",  # an analogue reference
    "dac",  # a digital-to-analogue converter output
    "touch",  # a capacitive touch sensor input
    "pcint",  # a pin-change interrupt: on every AVR port pin, so said once, not per pin
]

#: The order kinds are listed in, outward from the pin and down the legend.
FUNCTION_KINDS: tuple[FunctionKind, ...] = (
    "pwm", "adc", "dac", "touch", "int", "uart", "spi", "i2c", "timer", "comparator", "clock",
    "reset", "debug", "ref", "pcint",
)

#: Why a pin needs a second look before it is used. Said in words by the card.
PinWarning: TypeAlias = Literal[  # noqa: UP040
    "reset-fuse",  # the reset pin: an I/O only with the RSTDISBL fuse, which ends ISP
    "analog-only",  # an ADC input with no digital function at all
    "led",  # the board drives an LED from this pin
    "upload-serial",  # the board uploads sketches through this pin
    "strapping",  # sampled at reset to choose how the chip boots
    "input-only",  # an input with no output driver
    "flash",  # wired to the module's own flash: not for the circuit
    "adc2-wifi",  # an ADC2 channel, which the Wi-Fi driver takes while it runs
]

PIN_WARNINGS: tuple[PinWarning, ...] = (
    "reset-fuse", "analog-only", "led", "upload-serial", "strapping", "input-only", "flash",
    "adc2-wifi",
)


@dataclass(frozen=True, slots=True)
class PinFunction:
    """One alternate function: what kind it is, and the maker's own name for it."""

    kind: FunctionKind
    label: str


@dataclass(frozen=True, slots=True)
class LogicLevel:
    """What voltage a part's pins work at, and how much one pin may carry.

    ``volts`` is the logic level a builder wires to ("5 V", "3.3 V", "1.8-5.5 V" for a bare
    chip that runs at its supply); ``pin_max_ma`` the maker's absolute maximum per I/O pin.
    """

    volts: str
    pin_max_ma: float | None


#: What kind of document a card's facts were read from. A card names its documents, and
#: says the kind in its own language ("datasheet", "veri sayfası"); the title and the
#: maker's document number are names, the same in every language.
DocumentKind: TypeAlias = Literal["datasheet", "schematic", "user-guide", "board-file"]  # noqa: UP040

DOCUMENT_KINDS: tuple[DocumentKind, ...] = ("datasheet", "schematic", "user-guide", "board-file")


@dataclass(frozen=True, slots=True)
class Document:
    """A document a card was read from: "Microchip ATmega328P", a datasheet, "DS40002061B"."""

    kind: DocumentKind
    title: str
    number: str = ""


@dataclass(frozen=True, slots=True)
class BoardPins:
    """A catalogue part as an MCU's ports: which port each pin is, in pin order.

    ``ports`` lines up with the part's ``pin_names``; ``None`` is a pin that is no port
    (a supply, a ground, a regulator's input). ``warnings`` adds what the BOARD does to a
    pin -- an LED, an upload line -- to what the chip's own table says.
    """

    mcu: str
    ports: tuple[str | None, ...]
    logic: LogicLevel
    warnings: dict[str, tuple[PinWarning, ...]]
    #: What the port of each pin was read from; the MCU's own datasheet is added to it
    #: (:data:`MCU_DOCUMENTS`).
    documents: tuple[Document, ...]


def _f(spec: str) -> tuple[PinFunction, ...]:
    """``"pwm:OC2B int:INT1"`` as functions, in the order written."""
    functions = []
    for word in spec.split():
        kind, label = word.split(":", 1)
        assert kind in FUNCTION_KINDS, kind
        functions.append(PinFunction(kind, label))
    return tuple(functions)


def _ports(spec: str) -> tuple[str | None, ...]:
    """``"PD1 - PD0"`` as ports in pin order, ``-`` for a pin that is no port."""
    return tuple(None if word == "-" else word for word in spec.split())


# ---------------------------------------------------------------------------
# The chips
# ---------------------------------------------------------------------------

#: Every port's alternate functions, per MCU, in the order the maker's table lists them
#: (the card sorts by kind; this order is only what makes the table checkable against the
#: page it came from).
MCU_FUNCTIONS: dict[str, dict[str, tuple[PinFunction, ...]]] = {
    # Microchip ATmega328P datasheet DS40002061B, section 14.3 "Alternate Port Functions",
    # Tables 14-3 (Port B), 14-6 (Port C) and 14-9 (Port D), read pin by pin, and section
    # 1.1.9: ADC7:6 are analogue inputs on the TQFP and VQFN packages only, with no digital
    # function. KiCad 10's ATmega328P-P and -A symbols name the same functions on the same
    # pins. The PCINT numbers are the table's.
    "atmega328p": {
        "PB0": _f("timer:ICP1 clock:CLKO pcint:PCINT0"),
        "PB1": _f("pwm:OC1A pcint:PCINT1"),
        "PB2": _f("spi:SS pwm:OC1B pcint:PCINT2"),
        "PB3": _f("spi:MOSI pwm:OC2A pcint:PCINT3"),
        "PB4": _f("spi:MISO pcint:PCINT4"),
        "PB5": _f("spi:SCK pcint:PCINT5"),
        "PB6": _f("clock:XTAL1 clock:TOSC1 pcint:PCINT6"),
        "PB7": _f("clock:XTAL2 clock:TOSC2 pcint:PCINT7"),
        "PC0": _f("adc:ADC0 pcint:PCINT8"),
        "PC1": _f("adc:ADC1 pcint:PCINT9"),
        "PC2": _f("adc:ADC2 pcint:PCINT10"),
        "PC3": _f("adc:ADC3 pcint:PCINT11"),
        "PC4": _f("adc:ADC4 i2c:SDA pcint:PCINT12"),
        "PC5": _f("adc:ADC5 i2c:SCL pcint:PCINT13"),
        "PC6": _f("reset:RESET pcint:PCINT14"),
        "PD0": _f("uart:RXD pcint:PCINT16"),
        "PD1": _f("uart:TXD pcint:PCINT17"),
        "PD2": _f("int:INT0 pcint:PCINT18"),
        "PD3": _f("int:INT1 pwm:OC2B pcint:PCINT19"),
        "PD4": _f("uart:XCK timer:T0 pcint:PCINT20"),
        "PD5": _f("timer:T1 pwm:OC0B pcint:PCINT21"),
        "PD6": _f("comparator:AIN0 pwm:OC0A pcint:PCINT22"),
        "PD7": _f("comparator:AIN1 pcint:PCINT23"),
        "ADC6": _f("adc:ADC6"),
        "ADC7": _f("adc:ADC7"),
        "AREF": _f("ref:AREF"),
    },
    # Microchip ATtiny25/45/85 datasheet 2586Q, section 10.3.1, Table 10-3 "Port B Pins
    # Alternate Functions", and the pin configuration of section 1.1 (AREF on PB0). The
    # complementary outputs of Timer/Counter1 are written with a leading "/" as the
    # datasheet writes them over a bar.
    "attiny85": {
        "PB0": _f("spi:MOSI comparator:AIN0 pwm:OC0A pwm:/OC1A spi:DI i2c:SDA ref:AREF pcint:PCINT0"),
        "PB1": _f("spi:MISO comparator:AIN1 pwm:OC0B pwm:OC1A spi:DO pcint:PCINT1"),
        "PB2": _f("spi:SCK adc:ADC1 timer:T0 spi:USCK i2c:SCL int:INT0 pcint:PCINT2"),
        "PB3": _f("clock:XTAL1 clock:CLKI adc:ADC3 pwm:/OC1B pcint:PCINT3"),
        "PB4": _f("clock:XTAL2 clock:CLKO adc:ADC2 pwm:OC1B pcint:PCINT4"),
        "PB5": _f("reset:RESET debug:dW adc:ADC0 pcint:PCINT5"),
    },
    # Espressif ESP32 Series Datasheet v5.3, Table 2-1 "Pin Overview" and Table 4-6
    # "Peripheral Pin Configurations", read pin by pin: the ADC, touch and DAC channels, the
    # SPI and UART signals the IO MUX gives a pin of its own, the JTAG signals and the 32 kHz
    # crystal. LEFT OUT ON PURPOSE: RTC_GPIO numbers, the Ethernet MAC and the SD/SDIO
    # signals (a perfboard build uses none of them), and CLK_OUT. Table 4-6 routes PWM, I2C
    # and every UART "to any GPIO pins" through the GPIO matrix, so no pin carries those as
    # its own; the card says so once (:data:`ANY_PIN`). The flash pins (GPIO6-11) are listed
    # for what they are, so a card can say why not to use them.
    "esp32": {
        "GPIO36": _f("adc:ADC1_CH0"),
        "GPIO37": _f("adc:ADC1_CH1"),
        "GPIO38": _f("adc:ADC1_CH2"),
        "GPIO39": _f("adc:ADC1_CH3"),
        "GPIO34": _f("adc:ADC1_CH6"),
        "GPIO35": _f("adc:ADC1_CH7"),
        "GPIO32": _f("adc:ADC1_CH4 touch:TOUCH9 clock:32K_XP"),
        "GPIO33": _f("adc:ADC1_CH5 touch:TOUCH8 clock:32K_XN"),
        "GPIO25": _f("adc:ADC2_CH8 dac:DAC_1"),
        "GPIO26": _f("adc:ADC2_CH9 dac:DAC_2"),
        "GPIO27": _f("adc:ADC2_CH7 touch:TOUCH7"),
        "GPIO14": _f("adc:ADC2_CH6 touch:TOUCH6 spi:HSPICLK debug:MTMS"),
        "GPIO12": _f("adc:ADC2_CH5 touch:TOUCH5 spi:HSPIQ debug:MTDI"),
        "GPIO13": _f("adc:ADC2_CH4 touch:TOUCH4 spi:HSPID debug:MTCK"),
        "GPIO15": _f("adc:ADC2_CH3 touch:TOUCH3 spi:HSPICS0 debug:MTDO"),
        "GPIO2": _f("adc:ADC2_CH2 touch:TOUCH2 spi:HSPIWP"),
        "GPIO0": _f("adc:ADC2_CH1 touch:TOUCH1"),
        "GPIO4": _f("adc:ADC2_CH0 touch:TOUCH0 spi:HSPIHD"),
        "GPIO16": _f("uart:U2RXD"),
        "GPIO17": _f("uart:U2TXD"),
        "GPIO9": _f("uart:U1RXD spi:SPIHD"),
        "GPIO10": _f("uart:U1TXD spi:SPIWP"),
        "GPIO11": _f("spi:SPICS0"),
        "GPIO6": _f("spi:SPICLK"),
        "GPIO7": _f("spi:SPIQ"),
        "GPIO8": _f("spi:SPID"),
        "GPIO5": _f("spi:VSPICS0"),
        "GPIO18": _f("spi:VSPICLK"),
        "GPIO23": _f("spi:VSPID"),
        "GPIO19": _f("spi:VSPIQ"),
        "GPIO22": _f("spi:VSPIWP"),
        "GPIO21": _f("spi:VSPIHD"),
        "GPIO3": _f("uart:U0RXD"),
        "GPIO1": _f("uart:U0TXD"),
        "CHIP_PU": _f("reset:CHIP_PU"),
    },
}

#: Functions an MCU routes to ANY pin, through a matrix rather than its own wiring: said
#: once on the card instead of on every pin. ESP32 datasheet Table 4-6: the LED and motor
#: PWM, both I2C controllers and the three UARTs go to "any GPIO pins" (outputs to the
#: ones that can drive).
ANY_PIN: dict[str, tuple[FunctionKind, ...]] = {
    "esp32": ("pwm", "i2c", "uart"),
}

#: What a chip's own datasheet says to beware of on a port, whatever board it is on.
MCU_WARNINGS: dict[str, dict[str, tuple[PinWarning, ...]]] = {
    # ATmega328P section 1.1.5 and ATtiny85 section 10.3.1: the reset pin is an I/O only
    # when the RSTDISBL fuse is programmed, and the part is then no longer programmed
    # through it in-system. ATmega328P section 1.1.9: ADC6 and ADC7 have no digital function.
    "atmega328p": {"PC6": ("reset-fuse",), "ADC6": ("analog-only",), "ADC7": ("analog-only",)},
    "attiny85": {"PB5": ("reset-fuse",)},
    # ESP32 datasheet: Table 3-1 names the strapping pins (GPIO0, GPIO2, MTDI = GPIO12,
    # MTDO = GPIO15, GPIO5), section 2.3.1 the input-only pins (GPIO34-39) and the pins
    # "allocated for communication with in-package flash/PSRAM and NOT recommended for
    # other uses" (GPIO6-11, which a module wires to its flash). ESP-IDF's ADC oneshot
    # driver page: "ADC2 is also used by Wi-Fi", so an ADC2 read waits on the radio.
    "esp32": {
        "GPIO0": ("strapping", "adc2-wifi"),
        "GPIO2": ("strapping", "adc2-wifi"),
        "GPIO5": ("strapping",),
        "GPIO12": ("strapping", "adc2-wifi"),
        "GPIO15": ("strapping", "adc2-wifi"),
        "GPIO4": ("adc2-wifi",),
        "GPIO13": ("adc2-wifi",),
        "GPIO14": ("adc2-wifi",),
        "GPIO25": ("adc2-wifi",),
        "GPIO26": ("adc2-wifi",),
        "GPIO27": ("adc2-wifi",),
        **{f"GPIO{n}": ("input-only",) for n in range(34, 40)},
        **{f"GPIO{n}": ("flash",) for n in range(6, 12)},
    },
}

#: Each MCU's datasheet, the one its function table was read from.
MCU_DOCUMENTS: dict[str, Document] = {
    "atmega328p": Document("datasheet", "Microchip ATmega328P", "DS40002061B"),
    "attiny85": Document("datasheet", "Microchip ATtiny25/45/85", "2586Q"),
    "esp32": Document("datasheet", "Espressif ESP32", "v5.3"),
}

#: An MCU's name for one the catalogue does not carry as a part of its own: the ESP32 is
#: only ever on a module there. A chip the catalogue has is named by its catalogue entry.
MCU_NAMES: dict[str, str] = {
    "esp32": "ESP32",
}

#: The logic level and per-pin current of each chip: the operating voltage on its
#: datasheet's first page and the "DC Current per I/O Pin" absolute maximum (ATmega328P
#: DS40002061B: 1.8-5.5 V, section 29.1: 40 mA; ATtiny25/45/85 2586Q: 2.7-5.5 V, 1.8-5.5 V
#: for the V grade that a builder cannot tell from the catalogue's part, section 21.1: 40 mA).
_CHIP_LOGIC: dict[str, LogicLevel] = {
    "atmega328p": LogicLevel("1.8-5.5 V", 40.0),
    "attiny85": LogicLevel("2.7-5.5 V", 40.0),
}


# ---------------------------------------------------------------------------
# The parts in the catalogue
# ---------------------------------------------------------------------------

#: Every catalogue part with a card, as its MCU's ports in ``pin_names`` order.
BOARD_MAP: dict[str, BoardPins] = {
    # The bare chips: their DIP pin configuration (ATmega328P section 1.1, 28 PDIP;
    # ATtiny85 section 1.1, 8 PDIP), pin 1 first.
    "atmega328p": BoardPins(
        "atmega328p",
        _ports("PC6 PD0 PD1 PD2 PD3 PD4 - - PB6 PB7 PD5 PD6 PD7 PB0 PB1 PB2 PB3 PB4 PB5 - "
               "AREF - PC0 PC1 PC2 PC3 PC4 PC5"),
        _CHIP_LOGIC["atmega328p"], {}, (),
    ),
    "attiny85": BoardPins(
        "attiny85",
        _ports("PB5 PB3 PB4 - PB0 PB1 PB2 -"),
        _CHIP_LOGIC["attiny85"], {}, (),
    ),
    # Arduino Nano V3.3 schematic (docs.arduino.cc, the A000005 board), read net by net:
    # D0-D7 are PD0-PD7, D8-D13 are PB0-PB5, A0-A5 are PC0-PC5 and A6/A7 the TQFP's ADC6/ADC7;
    # both RESET pins are PC6. D0 and D1 reach the FT232RL USB bridge through 1 k resistors
    # (RP1), and D13 drives the yellow "L" LED through a 1 k resistor (RP2).
    "arduino-nano": BoardPins(
        "atmega328p",
        _ports("PD1 - PD0 - PC6 PC6 - - PD2 ADC7 PD3 ADC6 PD4 PC5 PD5 PC4 PD6 PC3 PD7 PC2 "
               "PB0 PC1 PB1 PC0 PB2 AREF PB3 - PB4 PB5"),
        LogicLevel("5 V", 40.0),
        {"D13": ("led",), "D0/RX": ("upload-serial",), "D1/TX": ("upload-serial",)},
        (Document("schematic", "Arduino Nano V3.3", "A000005"),),
    ),
    # SparkFun Arduino Pro Mini 328 Eagle board (github sparkfun/Arduino_Pro_Mini_328,
    # Hardware/Arduino-Pro-Mini.brd), its signals read pad by pad against the ATmega328P's
    # 32 TQFP pin configuration: TXO and RXI are PD1/PD0 and also the FTDI header's, D13 is
    # SCK (PB5) and drives the green LED through 330 R (R6, D3); A4/A5 and A6/A7 are on the
    # off-grid pads the catalogue leaves out. The 5 V board runs at 16 MHz, the 3.3 V one at
    # 8 MHz: the logic level is the board's VCC.
    "sparkfun-pro-mini": BoardPins(
        "atmega328p",
        _ports("PD1 - PD0 - PC6 PC6 - - PD2 PC3 PD3 PC2 PD4 PC1 PD5 PC0 PD6 PB5 PD7 PB4 "
               "PB0 PB3 PB1 PB2"),
        LogicLevel("5 V / 3.3 V", 40.0),
        {"D13": ("led",), "TXO": ("upload-serial",), "RXI": ("upload-serial",)},
        (Document("board-file", "SparkFun Arduino Pro Mini 328"),),
    ),
    # Espressif's ESP32-DevKitC V4 user guide, headers J2 and J3, pin by pin (VP is GPIO36,
    # VN GPIO39, EN is CHIP_PU, D2/D3/CMD and D1/D0/CLK are GPIO9/10/11 and GPIO8/7/6). TX
    # and RX are U0TXD/U0RXD, which the board's USB-to-UART bridge uploads through. Its note
    # [3]: GPIO16 and GPIO17 are free only on the WROOM and SOLO boards, which is the one the
    # catalogue carries. The logic is 3.3 V (datasheet Table 5-3: VIH is at most VDD + 0.3 V,
    # nothing on the chip is 5 V tolerant); the datasheet gives a TYPICAL 40 mA source per
    # pin and no maximum, so the card names none.
    "esp32-devkitc": BoardPins(
        "esp32",
        _ports("- - CHIP_PU GPIO23 GPIO36 GPIO22 GPIO39 GPIO1 GPIO34 GPIO3 GPIO35 GPIO21 "
               "GPIO32 - GPIO33 GPIO19 GPIO25 GPIO18 GPIO26 GPIO5 GPIO27 GPIO17 GPIO14 GPIO16 "
               "GPIO12 GPIO4 - GPIO0 GPIO13 GPIO2 GPIO9 GPIO15 GPIO10 GPIO8 GPIO11 GPIO7 - GPIO6"),
        LogicLevel("3.3 V", None),
        {"TX": ("upload-serial",), "RX": ("upload-serial",)},
        (Document("user-guide", "Espressif ESP32-DevKitC V4"),),
    ),
}

#: Parts that want a card and are not read from their maker's document yet, with what is
#: missing. A part here gets no functions rather than functions from memory.
_FUNCTIONS_WAITING: dict[str, str] = {
    "sparkfun-pro-micro": "ATmega32U4 datasheet alternate-function tables not read yet",
    "esp32-devkit-v1": "a maker's board schematic not found yet",
    "esp32-c3-devkitm-1": "Espressif ESP32-C3 datasheet not read yet",
    "esp32-s3-devkitc-1": "Espressif ESP32-S3 datasheet not read yet",
    "seeed-xiao-esp32c3": "Espressif ESP32-C3 datasheet not read yet",
    "esp32-cam": "AI-Thinker schematic not read yet",
    "nodemcu-devkit-1.0": "Espressif ESP8266EX datasheet not read yet",
    "wemos-d1-mini": "Espressif ESP8266EX datasheet not read yet",
    "esp-01": "Espressif ESP8266EX datasheet not read yet",
    "raspberry-pi-pico": "RP2040 datasheet GPIO function table not read yet",
    "seeed-xiao-rp2040": "RP2040 datasheet GPIO function table not read yet",
}


def board_pins(part_id: str) -> BoardPins | None:
    """The MCU behind a catalogue part, port by pin, or ``None`` for a part with none."""
    return BOARD_MAP.get(part_id)


def documents(part_id: str) -> tuple[Document, ...]:
    """What a part's card was read from: the board's documents, then its MCU's datasheet."""
    pins = BOARD_MAP.get(part_id)
    if pins is None:
        return ()
    chip = MCU_DOCUMENTS.get(pins.mcu)
    return pins.documents + ((chip,) if chip is not None and chip not in pins.documents else ())


def port_functions(mcu: str, port: str | None) -> tuple[PinFunction, ...]:
    """What ``port`` of ``mcu`` can do besides being a port; empty for no port."""
    if port is None:
        return ()
    return MCU_FUNCTIONS.get(mcu, {}).get(port, ())


def pin_warnings(part_id: str, pin_name: str, port: str | None) -> tuple[PinWarning, ...]:
    """The chip's warnings for ``port`` and the board's for ``pin_name``, in warning order."""
    pins = BOARD_MAP.get(part_id)
    if pins is None:
        return ()
    found = set(MCU_WARNINGS.get(pins.mcu, {}).get(port or "", ()))
    found.update(pins.warnings.get(pin_name, ()))
    return tuple(w for w in PIN_WARNINGS if w in found)
