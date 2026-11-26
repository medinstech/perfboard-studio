"""The pinout card's facts and its layout (``pinfunctions``, ``pinout``).

The counts below are the maker's, read off the page each table names: a test that only
checked the tables against themselves would pass on a table copied wrong.
"""

from __future__ import annotations

from typing import get_args

import pytest

from perfboard_studio.catalog import CATALOG, catalog_part
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.pinfunctions import (
    _FUNCTIONS_WAITING,
    BOARD_MAP,
    FUNCTION_KINDS,
    MCU_DOCUMENTS,
    MCU_FUNCTIONS,
    MCU_WARNINGS,
    PIN_WARNINGS,
    FunctionKind,
    PinWarning,
    port_functions,
)
from perfboard_studio.pinout import pinout_card

LOOKUP = footprint_lookup()


def _pins_with(part_id: str, kind: str) -> dict[str, tuple[str, ...]]:
    """Pin name -> the labels of its functions of ``kind``, for the pins that have one."""
    card = pinout_card(part_id, LOOKUP)
    assert card is not None
    found = {}
    for pin in card.pins:
        labels = tuple(f.label for f in pin.functions if f.kind == kind)
        if labels:
            found[pin.name] = labels
    return found


def test_the_kind_and_warning_tuples_name_every_member() -> None:
    assert set(FUNCTION_KINDS) == set(get_args(FunctionKind))
    assert len(FUNCTION_KINDS) == len(set(FUNCTION_KINDS))
    assert set(PIN_WARNINGS) == set(get_args(PinWarning))


@pytest.mark.parametrize("part_id", sorted(BOARD_MAP))
def test_a_board_map_lines_up_with_the_parts_pins(part_id: str) -> None:
    part = catalog_part(part_id)
    assert part is not None
    mapped = BOARD_MAP[part_id]
    assert len(mapped.ports) == len(part.pin_names)
    table = MCU_FUNCTIONS[mapped.mcu]
    for port in mapped.ports:
        assert port is None or port in table, port
    names = {name for _, name in part.pin_names}
    assert set(mapped.warnings) <= names
    # Every card says what it was read from, its MCU's datasheet at least.
    assert mapped.mcu in MCU_DOCUMENTS


@pytest.mark.parametrize("part_id", sorted(BOARD_MAP))
def test_a_pin_that_is_no_port_is_a_supply_or_a_ground(part_id: str) -> None:
    part = catalog_part(part_id)
    assert part is not None
    roles = dict(part.pin_roles)
    for (number, name), port in zip(part.pin_names, BOARD_MAP[part_id].ports, strict=True):
        if port is None:
            assert roles[number] in ("power", "power-out", "ground"), name


def test_every_port_pin_the_chip_names_is_the_port_it_is_mapped_to() -> None:
    """A bare chip's catalogue names are its ports or their functions: the two must agree."""
    for part_id in ("atmega328p", "attiny85"):
        part = catalog_part(part_id)
        assert part is not None
        mapped = BOARD_MAP[part_id]
        for (_, name), port in zip(part.pin_names, mapped.ports, strict=True):
            if port is None:
                continue
            labels = {f.label for f in port_functions(mapped.mcu, port)}
            assert name == port or name in labels, (name, port)


def test_every_warning_names_a_real_port() -> None:
    for mcu, ports in MCU_WARNINGS.items():
        assert set(ports) <= set(MCU_FUNCTIONS[mcu])


def test_a_part_waiting_for_its_functions_is_a_catalogue_part_without_them() -> None:
    for part_id in _FUNCTIONS_WAITING:
        assert catalog_part(part_id) is not None, part_id
        assert part_id not in BOARD_MAP


# -- the maker's counts ------------------------------------------------------------------


def test_the_nano_has_the_arduino_pwm_adc_and_interrupt_pins() -> None:
    """Six PWM pins (D3, D5, D6, D9, D10, D11), eight analogue inputs, INT0/INT1 on D2/D3."""
    assert set(_pins_with("arduino-nano", "pwm")) == {"D3", "D5", "D6", "D9", "D10", "D11"}
    assert set(_pins_with("arduino-nano", "adc")) == {f"A{n}" for n in range(8)}
    assert _pins_with("arduino-nano", "int") == {"D2": ("INT0",), "D3": ("INT1",)}
    assert _pins_with("arduino-nano", "i2c") == {"A4": ("SDA",), "A5": ("SCL",)}
    assert _pins_with("arduino-nano", "spi") == {
        "D10": ("SS",), "D11": ("MOSI",), "D12": ("MISO",), "D13": ("SCK",)
    }
    assert _pins_with("arduino-nano", "uart") == {
        "D0/RX": ("RXD",), "D1/TX": ("TXD",), "D4": ("XCK",)
    }


def test_the_pro_mini_reads_the_same_chip_through_its_own_names() -> None:
    assert set(_pins_with("sparkfun-pro-mini", "pwm")) == {"D3", "D5", "D6", "D9", "D10", "D11"}
    # A4-A7 are on the pads the catalogue leaves out, so four analogue inputs are on the card.
    assert set(_pins_with("sparkfun-pro-mini", "adc")) == {"A0", "A1", "A2", "A3"}
    assert _pins_with("sparkfun-pro-mini", "uart")["TXO"] == ("TXD",)


def test_the_attiny85_has_the_datasheets_outputs_and_inputs() -> None:
    """Table 10-3: OC0A/OC0B/OC1A/OC1B and their complements, ADC0-ADC3, one INT0."""
    pwm = _pins_with("attiny85", "pwm")
    assert pwm == {
        "PB0": ("OC0A", "/OC1A"),
        "PB1": ("OC0B", "OC1A"),
        "PB3": ("/OC1B",),
        "PB4": ("OC1B",),
    }
    adc = _pins_with("attiny85", "adc")
    assert adc == {"RESET": ("ADC0",), "PB2": ("ADC1",), "PB4": ("ADC2",), "PB3": ("ADC3",)}
    assert _pins_with("attiny85", "int") == {"PB2": ("INT0",)}


def test_the_nanos_warnings_are_where_the_board_puts_them() -> None:
    card = pinout_card("arduino-nano", LOOKUP)
    assert card is not None
    warned = {pin.name: pin.warnings for pin in card.pins if pin.warnings}
    assert warned == {
        "D1/TX": ("upload-serial",),
        "D0/RX": ("upload-serial",),
        "RESET": ("reset-fuse",),
        "A7": ("analog-only",),
        "A6": ("analog-only",),
        "D13": ("led",),
    }
    assert card.warnings == ("reset-fuse", "analog-only", "led", "upload-serial")


# -- the layout ----------------------------------------------------------------------------


def test_a_dip_runs_down_its_left_side_and_back_up_its_right() -> None:
    card = pinout_card("atmega328p", LOOKUP)
    assert card is not None
    left = [pin.number for pin in sorted(card.pins, key=lambda p: p.y) if pin.side == "left"]
    right = [pin.number for pin in sorted(card.pins, key=lambda p: p.y) if pin.side == "right"]
    assert left == [str(n) for n in range(1, 15)]
    assert right == [str(n) for n in range(28, 14, -1)]
    assert card.mcu == "atmega328p" and card.mcu_name is None


def test_a_modules_labels_go_out_on_the_side_its_header_is_on() -> None:
    card = pinout_card("arduino-nano", LOOKUP)
    assert card is not None
    assert {pin.side for pin in card.pins if int(pin.number) % 2} == {"left"}
    assert {pin.side for pin in card.pins if not int(pin.number) % 2} == {"right"}
    assert card.mcu_name == "ATmega328P"
    assert card.logic is not None and card.logic.volts == "5 V"


def test_a_card_lists_only_the_kinds_it_uses_in_legend_order() -> None:
    card = pinout_card("attiny85", LOOKUP)
    assert card is not None
    used = {f.kind for pin in card.pins for f in pin.functions}
    assert set(card.kinds) == used
    assert list(card.kinds) == sorted(card.kinds, key=FUNCTION_KINDS.index)
    assert "uart" not in card.kinds  # the ATtiny85 has no UART


def test_a_part_with_names_and_no_chip_gets_a_plain_card() -> None:
    card = pinout_card("ne555", LOOKUP)
    assert card is not None
    assert card.mcu is None and card.kinds == () and card.warnings == ()
    assert [pin.name for pin in card.pins][:3] == ["GND", "TRIG", "OUT"]


def test_no_card_for_a_part_with_nothing_to_draw() -> None:
    assert pinout_card("no-such-part", LOOKUP) is None
    part = catalog_part("atmega328p")
    assert part is not None
    assert pinout_card(part, lambda _id: None) is None


def test_a_row_of_legs_sends_its_labels_below_one_to_a_step() -> None:
    """A TO-92's three legs share a row: left and right of its centre would put two of them
    on one line, so all three go out below."""
    card = pinout_card("bc547", LOOKUP)
    assert card is not None
    assert {pin.side for pin in card.pins} == {"below"}


def test_a_two_column_header_sends_one_column_each_way() -> None:
    """The nRF24L01's 2 x 4 header is at one end of its board, so both columns are left of
    its middle; the left column's labels go left and the right column's right."""
    card = pinout_card("nrf24l01", LOOKUP)
    assert card is not None
    left = {pin.name for pin in card.pins if pin.side == "left"}
    right = {pin.name for pin in card.pins if pin.side == "right"}
    assert left == {"GND", "CE", "SCK", "MISO"}
    assert right == {"VCC", "CSN", "MOSI", "IRQ"}


def test_two_rows_along_the_board_go_out_above_and_below() -> None:
    card = pinout_card("adafruit-pcf8574-qt", LOOKUP)
    assert card is not None
    above = sorted((pin for pin in card.pins if pin.side == "above"), key=lambda p: p.x)
    below = sorted((pin for pin in card.pins if pin.side == "below"), key=lambda p: p.x)
    assert [pin.name for pin in above][:3] == ["VIN", "P7", "P6"]
    assert [pin.name for pin in below] == ["VIN", "GND", "SCL", "SDA", "INT", "A0"]


def test_no_card_puts_two_labels_on_one_line() -> None:
    """Every card in the catalogue: on the left and on the right, one pin to a row."""
    for part in CATALOG:
        card = pinout_card(part, LOOKUP)
        if card is None:
            continue
        for side in ("left", "right"):
            ys = sorted(round(pin.y, 1) for pin in card.pins if pin.side == side)
            assert len(ys) == len(set(ys)), (part.id, side)
