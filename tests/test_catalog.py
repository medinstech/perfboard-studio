"""The catalog: real parts by name, each described completely enough to place.

What is pinned here is what would put a wrong board on somebody's bench without a word:
an entry whose names do not cover its package's pins, a transistor whose symbol cannot be
drawn because a leg is misnamed, a diode named backwards, a module whose rows are not the
distance apart its source measured -- and, the other way round, that placing from the
catalog leaves nothing in the document that depends on it.
"""

from __future__ import annotations

import dataclasses

import pytest

from perfboard_studio import persist
from perfboard_studio.catalog import (
    CATALOG,
    CATEGORY_ORDER,
    catalog_part,
    free_reference,
    part_matches,
    search_catalog,
)
from perfboard_studio.footprints import body_extent, get_footprint
from perfboard_studio.mcp.session import BoardSession, SessionError, new_board
from perfboard_studio.model import STANDARD_PITCH_MM
from perfboard_studio.schematic import DECLARED_SYMBOL_PINS


@pytest.mark.parametrize("part", CATALOG, ids=lambda part: part.id)
def test_every_entry_is_a_part_that_can_be_placed(part) -> None:
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None, f"{part.id}: {part.footprint_id} names no footprint"
    assert part.id == part.id.strip().lower() and " " not in part.id
    assert part.category in CATEGORY_ORDER
    assert part.reference_prefix.isalpha() and part.reference_prefix.isupper()
    assert part.summary and part.source, f"{part.id} says nothing about itself"
    if part.pin_names:
        # Every lead named, and nothing named that is not a lead: a name on a pin the
        # package does not have is a pinout copied from some other package.
        assert [number for number, _ in part.pin_names] == [pin.number for pin in footprint.pins]
    if part.symbol is not None:
        names = {name for _, name in part.pin_names}
        assert DECLARED_SYMBOL_PINS[part.symbol] <= names, (
            f"{part.id} is a {part.symbol} whose legs are not named "
            f"{sorted(DECLARED_SYMBOL_PINS[part.symbol])}, so it would be drawn as a box"
        )


def test_ids_are_unique() -> None:
    ids = [part.id for part in CATALOG]
    assert len(ids) == len(set(ids))


def test_a_diode_is_named_from_its_banded_end() -> None:
    """Pin 1 is the cathode, the banded end -- the registry's convention and KiCad's. A
    zener named the other way round is one soldered in backwards, and conducting."""
    for part in CATALOG:
        if part.category == "diode":
            assert dict(part.pin_names) == {"1": "K", "2": "A"}, part.id


def test_the_parts_whose_pinout_is_the_classic_trap_are_pinned_the_way_their_datasheets_say() -> None:
    """The ones people get wrong, spelled out: the same package, different legs."""
    legs = {part.id: tuple(name for _, name in part.pin_names) for part in CATALOG}
    assert legs["bc547"] == ("C", "B", "E")
    assert legs["2n2222a"] == ("E", "B", "C")  # the TO-92 one, not the metal can
    assert legs["2n7000"] == ("S", "G", "D")
    assert legs["bs170"] == ("D", "G", "S")  # the other way round from a 2N7000
    assert legs["7805"] == ("IN", "GND", "OUT")
    assert legs["7905"] == ("GND", "IN", "OUT")  # NOT a 7805's
    assert legs["lm317t"] == ("ADJ", "OUT", "IN")
    assert legs["78l05"] == ("OUT", "GND", "IN")
    assert legs["ld1117v33"] == ("GND", "OUT", "IN")  # NOT a 7805's either
    assert legs["mcp1700-3302"] == ("GND", "IN", "OUT")  # NOT a 78L05's
    assert legs["bc337"] == legs["bc327"] == ("C", "B", "E")
    assert legs["cd4017"][2] == "Q0"  # pin 3: the outputs are not in order
    assert (legs["74hc165"][6], legs["74hc165"][8]) == ("~QH", "QH")  # the one to read is 9
    assert legs["irf9540n"] == ("G", "D", "S")


def test_the_chips_whose_supply_is_not_at_the_corners_say_where_it_is() -> None:
    """A quad op-amp is fed on pins 4 and 11, and a split-supply one names its rails V+ and
    V- -- which is what lets ERC hold a TL072's negative rail to a net without asking it to
    be ground."""
    lm324 = dict(catalog_part("lm324").pin_names)  # type: ignore[union-attr]
    assert (lm324["4"], lm324["11"]) == ("VCC", "GND")
    tl072 = dict(catalog_part("tl072").pin_names)  # type: ignore[union-attr]
    assert (tl072["4"], tl072["8"]) == ("V-", "V+")
    max7219 = dict(catalog_part("max7219").pin_names)  # type: ignore[union-attr]
    assert (max7219["4"], max7219["9"], max7219["19"]) == ("GND", "GND", "V+")


def test_a_module_is_a_module_and_its_rows_are_where_its_source_measured_them() -> None:
    expected_rows_mm = {
        "esp32-devkitc": 25.4,
        # Four makers' footprints agree: the rows 1.0 inch apart.
        "esp32-devkit-v1": 25.4,
        "esp32-c3-devkitm-1": 22.86,
        "arduino-nano": 15.24,
        "raspberry-pi-pico": 17.78,
        "wemos-d1-mini": 22.86,
        "pololu-a4988": 12.7,
        "pololu-drv8825": 12.7,
        "seeed-xiao-esp32c3": 15.24,
        # The grid nearest Handsontec's 39.50 mm, which its check says: pads, not pins.
        "lm2596-module": 40.64,
        "sparkfun-tb6612fng": 15.24,
        # SparkFun's Eagle board: its rows at x = 1.27 and 16.51 mm, 0.6 inch apart.
        "sparkfun-pro-mini": 15.24,
        # SparkFun's Eagle board: its rows at y = 1.27 and 11.43 mm, 0.4 inch apart.
        "sparkfun-logic-level-converter": 10.16,
        # NodeMCU's Gerbers: its rows at x = +-11.43 mm, 0.9 inch apart.
        "nodemcu-devkit-1.0": 22.86,
        "pololu-drv8833": 10.16,
        # Two headers of four, side by side, at one end of the board.
        "nrf24l01": 2.54,
        # Two ROWS of four across the end of the board: Ai-Thinker's figure 2.1.
        "esp-01": 2.54,
    }
    modules = [part for part in CATALOG if part.category == "module"]
    assert {part.id for part in modules} == set(expected_rows_mm)
    for part in modules:
        footprint = get_footprint(part.footprint_id)
        assert footprint is not None and footprint.body.archetype == "module-board"
        columns = sorted({pin.d_col for pin in footprint.pins})
        rows = sorted({pin.d_row for pin in footprint.pins})
        # A devkit's two columns run down the board; a radio's two rows run across its end.
        lines = columns if len(columns) == 2 else rows
        assert len(lines) == 2, part.id
        assert (lines[1] - lines[0]) * STANDARD_PITCH_MM == pytest.approx(
            expected_rows_mm[part.id]
        ), part.id
        assert part.check, f"{part.id}: a module's estimates have to be said"


def test_the_oled_is_two_entries_because_it_is_sold_two_ways() -> None:
    """The four-pin OLED is sold with VCC and GND either way round, and the wrong way round
    kills it: two entries named by the order printed on the board, identical but for those
    two pins, and both found by "oled"."""
    first = catalog_part("ssd1306-i2c-gnd-vcc")
    second = catalog_part("ssd1306-i2c-vcc-gnd")
    assert first is not None and second is not None
    assert [name for _, name in first.pin_names] == ["GND", "VCC", "SCL", "SDA"]
    assert [name for _, name in second.pin_names] == ["VCC", "GND", "SCL", "SDA"]
    for part in (first, second):
        order = " ".join(name for _, name in part.pin_names)
        assert f"({order})" in part.name and "VCC and GND" in part.check
    assert first.footprint_id == second.footprint_id
    assert {part.id for part in search_catalog("oled")} == {first.id, second.id}


def test_the_lcd_and_the_ir_receiver_are_pinned_as_their_sources_have_them() -> None:
    """The 16 x 2 LCD as KiCad's WC1602A symbol numbers it, backlight last; the TSOP38238 as
    Vishay's datasheet does."""
    lcd = catalog_part("lcd-1602")
    ir = catalog_part("tsop38238")
    assert lcd is not None and ir is not None
    names = [name for _, name in lcd.pin_names]
    assert names[:6] == ["VSS", "VDD", "VO", "RS", "RW", "E"]
    assert names[6:14] == [f"D{bit}" for bit in range(8)] and names[14:] == ["A", "K"]
    assert [name for _, name in ir.pin_names] == ["OUT", "GND", "VS"]


def test_the_keypad_is_numbered_as_parallax_numbers_it() -> None:
    """Right to left with the keys facing you: pins 1-4 the columns from C4, 5-8 the rows
    from R4 -- so the leftmost lead is R1, as most tutorials wire it."""
    keypad = catalog_part("keypad-4x4")
    assert keypad is not None
    names = dict(keypad.pin_names)
    assert (names["1"], names["4"], names["5"], names["8"]) == ("C4", "C1", "R4", "R1")


def test_the_trimmer_is_a_pot_whose_middle_leg_is_the_wiper() -> None:
    trimmer = catalog_part("bourns-3296w")
    assert trimmer is not None and trimmer.symbol == "potentiometer"
    assert dict(trimmer.pin_names)["2"] == "W"


def test_the_hc_sr04_is_pinned_as_elecfreaks_prints_it() -> None:
    sensor = catalog_part("hc-sr04")
    assert sensor is not None and sensor.category == "sensor"
    assert [name for _, name in sensor.pin_names] == ["VCC", "TRIG", "ECHO", "GND"]
    assert search_catalog("ultrasonic") == [sensor]


def test_the_radios_are_pinned_as_their_sources_number_them() -> None:
    """The nRF24L01+'s 2 x 4 header as KiCad's breakout symbol has it, GND at pin 1; the
    ESP-01's two rows as Ai-Thinker's figure 2.1 and table 2.2 both have them."""
    nrf = catalog_part("nrf24l01")
    esp = catalog_part("esp-01")
    assert nrf is not None and esp is not None
    assert [name for _, name in nrf.pin_names] == [
        "GND", "VCC", "CE", "CSN", "SCK", "MOSI", "MISO", "IRQ"
    ]
    assert [name for _, name in esp.pin_names] == [
        "GND", "IO2", "IO0", "RXD", "TXD", "EN", "RST", "VCC"
    ]
    assert search_catalog("nrf24")[0] is nrf and search_catalog("ESP8266 wifi")[0] is esp


def test_the_devkitc_is_pinned_like_espressifs_own_tables() -> None:
    """J2 down the left from 3V3 to 5V, J3 down the right from GND to CLK, pin 1 at the
    top left: the numbering is row by row, so the left column is the odd pins."""
    part = catalog_part("esp32-devkitc")
    assert part is not None
    names = dict(part.pin_names)
    assert len(names) == 38
    assert (names["1"], names["2"]) == ("3V3", "GND")
    assert (names["37"], names["38"]) == ("5V", "CLK")
    # Row 14: J2.14 is GND on the left (27), J3.14 the boot pin IO0 on the right (28).
    assert (names["27"], names["28"]) == ("GND", "IO0")


def test_the_nano_right_column_runs_from_vin_to_d13() -> None:
    part = catalog_part("arduino-nano")
    assert part is not None
    names = dict(part.pin_names)
    assert (names["1"], names["2"]) == ("D1/TX", "VIN")
    assert (names["29"], names["30"]) == ("D12", "D13")


def test_search_matches_the_name_the_summary_and_the_kind() -> None:
    assert [part.id for part in search_catalog("bc547")] == ["bc547"]
    assert {part.id for part in search_catalog("esp32")} == {
        "esp32-devkitc", "esp32-devkit-v1", "esp32-c3-devkitm-1", "seeed-xiao-esp32c3"
    }
    assert all(part.symbol == "pmos" for part in search_catalog("p-channel"))
    assert {part.category for part in search_catalog(category="regulator")} == {"regulator"}
    assert catalog_part("  BC547 ") is catalog_part("bc547")
    assert catalog_part("nothing-like-it") is None


@pytest.mark.parametrize(
    ("typed", "found"),
    [
        # What is printed on the part or the bag: the number with a package letter, a
        # maker's prefix, or both.
        ("LM358N", "lm358"),
        ("NE555P", "ne555"),
        ("74HC595N", "74hc595"),
        ("SN74HC595N", "74hc595"),
        ("L7805CV", "7805"),
        ("LM7805", "7805"),
        ("BC547B", "bc547"),
        # ...or an ordering code after a hyphen, which may start with a digit.
        ("ATtiny85-20PU", "attiny85"),
        ("ATmega328P-PU", "atmega328p"),
        # Hyphens and spaces are not what anybody remembers about a word.
        ("opamp", "lm358"),
        ("op amp", "lm358"),
        ("5v regulator", "7805"),
        ("opto isolator", "pc817"),
        # Words a part is looked for by that its summary does not say.
        ("stepper", "uln2003a"),
        ("28BYJ-48", "uln2003a"),
        ("motor driver", "l293d"),
        ("ds18b20 one wire", "ds18b20"),
        ("attiny", "attiny85"),
        ("rtc", "ds1307"),
        ("led matrix", "max7219"),
        ("3.3V regulator", "ld1117v33"),
        ("LM1117T-3.3", "ld1117v33"),
        ("opamp", "tl072"),
        ("MCP1700-3302E/TO", "mcp1700-3302"),
        ("PCF8574AP", "pcf8574"),
        ("port expander", "mcp23017"),
        ("eeprom", "24lc256"),
        ("adc", "mcp3008"),
        # A first circuit drawn from nothing needs a way to bring power in, in either
        # language.
        ("battery", "battery-9v-clip"),
        ("9V", "battery-9v-clip"),
        ("pil", "battery-aa-holder"),
        ("jack", "dc-jack-panel"),
        ("power", "power-terminal-2"),
        ("supply", "power-header-2"),
        ("servo", "servo-header"),
        ("SG90", "servo-header"),
        ("buzzer", "buzzer-active-12mm"),
        # From the findability sweep: what a beginner types, in either language.
        ("microcontroller", "atmega328p"),
        ("mikrodenetleyici", "attiny85"),
        ("terminal block", "power-terminal-2"),
        ("batarya", "battery-aa-holder"),
        ("adaptör", "dc-jack-panel"),
        ("kızılötesi", "tsop38238"),
        ("voltaj regülatörü", "ld1117v33"),
        ("anahtar", "tact-6x6"),
        ("trimmer", "bourns-3296w"),
        ("trimpot", "bourns-3296w"),
        ("ldr", "gl5528"),
        ("ışık sensörü", "gl5528"),
        ("speaker", "buzzer-passive-12mm"),
        ("inductor", "bourns-78f101j"),
        ("bobin", "bourns-78f101j"),
        ("keypad", "keypad-4x4"),
        ("tuş takımı", "keypad-4x4"),
    ],
)
def test_a_part_is_found_by_what_somebody_would_type(typed, found) -> None:
    """Every one of these found nothing before the search learned to read a word the way
    a person types it."""
    assert found in [part.id for part in search_catalog(typed)]


@pytest.mark.parametrize("typed", ["LM350", "LM3580", "BC5470", "10k", "100n"])
def test_a_different_number_is_not_the_same_part(typed) -> None:
    """A package letter after the number is the same part; another DIGIT is another part --
    an LM350 is a regulator and not an LM35 -- and a quantity is no part at all."""
    assert search_catalog(typed) == []


def test_a_part_whose_name_says_it_comes_before_one_whose_summary_does() -> None:
    """"switch" is a push button's name and only a word in the 2N2222A's "switching"."""
    found = [part.id for part in search_catalog("switch")]
    assert found[:2] == ["tact-6x6", "tact-12x12"] and "2n2222a" in found[2:]
    # With nothing typed, nothing moves.
    assert search_catalog("") == list(CATALOG)


def test_a_name_is_named_from_the_start_of_a_word() -> None:
    """"led" is inside "SSD1306 OLED" and names no display: the LEDs come first, a plain
    one at their head, then the MAX7219's matrix module, "LED matrix" in its name, and the
    chip, whose alias it is, and the OLEDs only after them. And "voltage regulator" names
    the regulators by their kind, which no 7805's own words say."""
    led = [part.id for part in search_catalog("led")]
    assert led[0] == "led-3mm"
    leds = [part.id for part in CATALOG if part.category == "led"]
    assert led[: len(leds)] == leds
    assert led[len(leds) : len(leds) + 2] == ["max7219-matrix", "max7219"]
    assert {"ssd1306-i2c-gnd-vcc", "ssd1306-i2c-vcc-gnd"} <= set(led[len(leds) + 2 :])
    assert search_catalog("voltage regulator")[0].category == "regulator"


def test_the_window_can_hand_the_search_its_own_words_and_its_own_letters() -> None:
    """The Parts panel passes the summary and heading in its own language, and its own
    fold for the Turkish i."""
    lm358 = catalog_part("lm358")
    assert lm358 is not None
    assert not part_matches(lm358, "işlemsel")
    assert part_matches(lm358, "işlemsel yükselteç", also="Çift işlemsel yükselteç")
    # "ISI".lower() is "isi" and "ısı".lower() is "ısı": only the window's fold joins them.
    dotless = str.maketrans({"I": "i", "ı": "i", "İ": "i"})
    assert not part_matches(lm358, "ISI", also="ısı")
    assert part_matches(lm358, "ISI", also="ısı", fold=lambda text: text.translate(dotless).lower())


def test_power_comes_in_on_a_plus_and_a_minus_and_a_battery_is_off_the_board() -> None:
    """Every way in is named + and -, in that order, so the guide's polarity note and the
    net colours have something to read; a battery and a panel jack are the pads their leads
    land in (``footprints.off_board_mount``), and a battery is BT, not J."""
    for part in CATALOG:
        if part.category == "power":
            assert part.pin_names == (("1", "+"), ("2", "-")), part.id
    for part_id in ("battery-9v-clip", "battery-aa-holder", "dc-jack-panel"):
        part = catalog_part(part_id)
        assert part is not None and part.footprint_id.startswith("wire-")
    clip = catalog_part("battery-9v-clip")
    assert clip is not None and clip.reference_prefix == "BT"
    session = BoardSession(document=new_board(cols=30, rows=20))
    assert session.add_part("", "", part="battery-9v-clip")["ok"]
    assert session.add_part("", "", part="buzzer-active-12mm")["ok"]
    assert [part.ref for part in session.document.parts] == ["BT1", "BZ1"]


def test_a_servo_header_has_its_plus_in_the_middle() -> None:
    """As every hobby servo's plug has it: turned round, PWM and - swap, and nothing burns."""
    servo = catalog_part("servo-header")
    assert servo is not None and dict(servo.pin_names) == {"1": "PWM", "2": "+", "3": "-"}


def test_the_songle_relay_is_on_its_own_footprint_and_named_as_kicad_numbers_it() -> None:
    """The relay nearly every hobby board uses, on ``relay-srd`` and never on ``relay-spdt``,
    whose COM is somewhere else; and found by what is printed on it."""
    relay = catalog_part("srd-05vdc-sl-c")
    assert relay is not None and relay.footprint_id == "relay-srd"
    assert dict(relay.pin_names) == {"1": "COM", "2": "COIL", "3": "NO", "4": "NC", "5": "COIL"}
    assert relay.reference_prefix == "K"
    assert [part.id for part in search_catalog("relay")] == [
        "srd-05vdc-sl-c", "srd-12vdc-sl-c", "relay-module-1ch"
    ]
    # The one-channel module is that relay on a board, so it comes after it, never first.
    assert [part.id for part in search_catalog("SRD-05VDC-SL-C")] == [
        "srd-05vdc-sl-c", "relay-module-1ch"
    ]
    # The 12 V one is the same package and the same legs.
    twelve = catalog_part("srd-12vdc-sl-c")
    assert twelve is not None
    assert (twelve.footprint_id, twelve.pin_names) == (relay.footprint_id, relay.pin_names)


#: Each RGB LED's legs as its maker draws them: red, the common leg, then green and blue in
#: that maker's order -- Young Sun's and Fedy's green first, Kingbright's blue.
RGB_LEDS = {
    "rgb-led-5mm-cc": ("RA", "K", "GA", "BA"),
    "rgb-led-5mm-ca": ("RK", "A", "GK", "BK"),
    "rgb-led-5mm-cc-kingbright": ("RA", "K", "BA", "GA"),
    "rgb-led-5mm-ca-kingbright": ("RK", "A", "BK", "GK"),
}


@pytest.mark.parametrize("part_id", sorted(RGB_LEDS))
def test_an_rgb_led_says_its_leg_order_in_its_name(part_id: str) -> None:
    """A row that only said "RGB LED, common cathode" would be right for one maker and
    swap two colours for the other, so the order is printed in the name, letter for letter,
    and the guide sends the builder to the LONGEST leg for the common one -- the opposite
    of what "K" means on a two-legged LED."""
    from perfboard_studio.guide import _polarity_note

    led = catalog_part(part_id)
    assert led is not None and led.footprint_id == "led-5mm-rgb"
    names = RGB_LEDS[part_id]
    assert tuple(name for _, name in led.pin_names) == names
    common = names[1]
    assert led.name.endswith(f"(R {common} {names[2][0]} {names[3][0]})")
    assert ("common anode" in led.name) == (common == "A")

    session = BoardSession(document=new_board(cols=12, rows=8, name="rgb"))
    assert session.place_component("", "", "C3", part=part_id)["ok"]
    footprint = get_footprint("led-5mm-rgb")
    assert footprint is not None
    anchor = session.document.components[0].anchor
    holes = tuple(
        (pin.number, dataclasses.replace(anchor, col=anchor.col + pin.d_col))
        for pin in footprint.pins
    )
    note = _polarity_note(footprint, holes, session.document.components[0], board=None)
    kind = "anode" if common == "A" else "cathode"
    assert note == f"Red leg in C3; Common {kind} (the longest leg) in D3"


def test_a_plain_led_is_still_told_by_its_short_leg() -> None:
    """The two-legged LED's names keep the meaning they always had in the guide."""
    from perfboard_studio.guide import _polarity_note

    led = catalog_part("led-5mm")
    assert led is not None and dict(led.pin_names) == {"1": "A", "2": "K"}
    footprint = get_footprint("led-5mm")
    assert footprint is not None
    session = BoardSession(document=new_board(cols=12, rows=8, name="led"))
    assert session.place_component("", "", "C3", part="led-5mm")["ok"]
    anchor = session.document.components[0].anchor
    holes = (("1", anchor), ("2", dataclasses.replace(anchor, col=anchor.col + 1)))
    note = _polarity_note(footprint, holes, session.document.components[0], board=None)
    assert note == "Anode (long lead) in C3; Cathode (short lead, flat on the rim) in D3"


def test_a_4000_series_gate_is_not_pinned_like_a_74hc_one() -> None:
    """The mistake a 74HC00 drawn on a CD4011's pins makes: two of its four outputs are on
    the inside of the 4000-series package, pins 4 and 11, where the 74HC has an input."""
    outputs = {}
    for part_id in ("74hc00", "74hc08", "74hc32", "74hc86", "cd4011", "cd4093"):
        part = catalog_part(part_id)
        assert part is not None
        outputs[part_id] = {number for number, name in part.pin_names if name.endswith("Y")}
    assert outputs["74hc00"] == outputs["74hc08"] == outputs["74hc32"] == outputs["74hc86"]
    assert outputs["74hc00"] == {"3", "6", "8", "11"}
    assert outputs["cd4011"] == outputs["cd4093"] == {"3", "4", "10", "11"}


#: Kingbright's circuit diagrams, segment by segment: which pin lights it.
ONE_DIGIT = {"a": "7", "b": "6", "c": "4", "d": "2", "e": "1", "f": "9", "g": "10", "DP": "5"}
FOUR_DIGITS = {"a": "11", "b": "7", "c": "4", "d": "2", "e": "1", "f": "10", "g": "5", "DP": "3",
               "DIG1": "12", "DIG2": "9", "DIG3": "8", "DIG4": "6"}


@pytest.mark.parametrize(
    ("part_id", "segments", "common"),
    [
        ("sa56-11", ONE_DIGIT, ("CA", {"3", "8"})),
        ("sc56-11", ONE_DIGIT, ("CC", {"3", "8"})),
        ("ca56-12", FOUR_DIGITS, None),
        ("cc56-12", FOUR_DIGITS, None),
    ],
)
def test_a_seven_segment_display_lights_the_segment_its_datasheet_says(
    part_id: str, segments: dict[str, str], common: tuple[str, set[str]] | None
) -> None:
    """A segment on the wrong pin is a digit that shows the wrong number and looks right on
    the screen. Lower-case, as Kingbright prints them -- and so never read as an LED's "A"
    by the guide or ERC."""
    display = catalog_part(part_id)
    assert display is not None and display.footprint_id.endswith("-ccw")
    names = dict(display.pin_names)
    assert {name: number for number, name in names.items() if name in segments} == segments
    if common is not None:
        name, pins = common
        assert {number for number, said in names.items() if said == name} == pins
    assert set(names.values()) <= set(segments) | {"CA", "CC"}
    assert ("anode" in display.name) == part_id.startswith(("sa", "ca"))


def test_a_free_reference_counts_the_board_and_the_design() -> None:
    session = BoardSession(document=new_board(cols=20, rows=12))
    session.place_component("Q1", "to92", "C3")
    session.add_part("Q2", "to92")
    assert free_reference(session.document, "Q") == "Q3"
    assert free_reference(session.document, "U") == "U1"


# ----------------------------------------------------------------- through the session


def test_placing_a_catalog_part_fills_everything_in() -> None:
    session = BoardSession(document=new_board(cols=30, rows=20))
    assert session.place_component("", "", "C4", part="bc547")["ok"]
    assert session.place_component("", "", "J4", part="7805")["ok"]
    q1, u1 = session.document.components
    assert (q1.ref, q1.value, q1.footprint_id, q1.symbol) == ("Q1", "BC547", "to92", "npn")
    assert dict(q1.pin_names) == {"1": "C", "2": "B", "3": "E"}
    # A 7805 is a TO-220 and it is not a transistor.
    assert (u1.ref, u1.value, u1.symbol) == ("U1", "7805", None)


def test_anything_given_explicitly_wins_over_the_catalog() -> None:
    session = BoardSession(document=new_board(cols=30, rows=20))
    assert session.place_component(
        "T7", "", "C4", value="BC547B", pin_names={"2": "BASE"}, part="bc547"
    )["ok"]
    (part,) = session.document.components
    assert (part.ref, part.value) == ("T7", "BC547B")
    assert dict(part.pin_names) == {"2": "BASE"}


def test_a_catalog_part_can_go_in_the_design_before_the_board() -> None:
    session = BoardSession(document=new_board(cols=30, rows=20))
    assert session.add_part("", "", part="irf9540n")["ok"]
    (part,) = session.document.parts
    assert (part.ref, part.footprint_id, part.symbol) == ("Q1", "to220", "pmos")


def test_an_unknown_catalog_part_is_a_clear_error() -> None:
    session = BoardSession(document=new_board(cols=30, rows=20))
    with pytest.raises(SessionError, match="list_catalog"):
        session.place_component("", "", "C4", part="bc999")


def test_list_catalog_says_what_to_check_only_when_there_is_something() -> None:
    session = BoardSession()
    rows = {row["id"]: row for row in session.list_catalog()}
    assert len(rows) == len(CATALOG)
    assert "check" in rows["esp32-devkitc"] and "check" not in rows["ne555"]
    assert rows["bc547"]["pin_names"] == {"1": "C", "2": "B", "3": "E"}
    assert {row["category"] for row in session.list_catalog(category="module")} == {"module"}
    with pytest.raises(SessionError, match="category"):
        session.list_catalog(category="valves")


def test_nothing_in_the_document_refers_back_to_the_catalog() -> None:
    """A board built from the catalog is byte for byte the board built by hand: it opens
    the same on a machine whose catalog has never heard of the part, and an entry corrected
    later never silently changes a board already drawn."""
    from_catalog = BoardSession(document=new_board(cols=30, rows=20, name="x"))
    from_catalog.place_component("", "", "C4", part="bc547")
    by_hand = BoardSession(document=new_board(cols=30, rows=20, name="x"))
    by_hand.place_component(
        "Q1", "to92", "C4", value="BC547", pin_names={"1": "C", "2": "B", "3": "E"}, symbol="npn"
    )

    built, typed = from_catalog.document.components[0], by_hand.document.components[0]
    assert dataclasses.replace(built, id="c") == dataclasses.replace(typed, id="c")
    # And the file says nothing more than the part: no catalog id, nothing to resolve.
    text = persist.serialize_document(from_catalog.document)
    assert "bc547" not in text and "catalog" not in text


def test_the_thermistor_is_drawn_at_the_most_its_datasheet_allows_and_says_it_is_not_a_seat() -> None:
    """APR's MF52, model A: a bead at most 3.8 x 2.5 on wires 2.5 +-0.5 mm apart. Its drawing
    prints no bead length and is not to scale, so the height is the L1 maximum (9.5), and
    the note says it is a ceiling the builder lowers, not a seat the part sits in."""
    part = catalog_part("ntc-mf52")
    assert part is not None
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None
    assert [(pin.d_col, pin.d_row) for pin in footprint.pins] == [(0, 0), (1, 0)]
    extent = body_extent(footprint, STANDARD_PITCH_MM)
    assert (extent.size_x, extent.size_y) == (3.8, 2.5)
    assert footprint.body_height == 9.5
    assert abs(STANDARD_PITCH_MM - 2.5) <= 0.5, "the holes must be inside the drawing's tolerance"
    assert "yours to choose" in part.check and "not a seat" in part.source


def test_the_tilt_switch_is_drawn_at_its_datasheets_maxima_and_its_lead_arithmetic_is_true() -> None:
    """Bailin's SW-520D: 5.2 +0.3 across and 11.5 +0.4 long, leads 0.6 mm and 2.4 mm apart.
    The footprint carries the maxima, and what the catalog says about the 2.4 against the
    2.54 holes is checked here by doing the sum, not by repeating the sentence."""
    part = catalog_part("sw-520d")
    assert part is not None
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None
    assert [(pin.d_col, pin.d_row) for pin in footprint.pins] == [(0, 0), (1, 0)]
    extent = body_extent(footprint, STANDARD_PITCH_MM)
    assert (extent.size_x, extent.size_y) == (5.5, 5.5)
    assert footprint.body_height == 11.9
    off_by = (STANDARD_PITCH_MM - 2.4) / 2
    spare = (1.0 - 0.6) / 2
    assert round(off_by, 2) == 0.07 and off_by < spare
    assert "0.07 mm" in part.check and "0.2 mm" in part.check


def test_the_rv09_courtyard_covers_its_lugs_and_its_pin_arithmetic_is_true() -> None:
    """The Alps RK09K drawing the RV09 is drawn from: lugs 10.6 mm outer to outer, 2.1 mm
    deep, 7 mm from the pin row; the frame 5.5 mm past the shaft's axis; pins 2.5 mm apart.
    The footprint has to hold the whole of the part, lugs included, and the lug and pin
    lengths the check quotes have to be the ones that make its sentence true."""
    part = catalog_part("rv09-pot")
    assert part is not None
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None
    assert [(pin.d_col, pin.d_row) for pin in footprint.pins] == [(0, 0), (1, 0), (2, 0)]
    extent = body_extent(footprint, STANDARD_PITCH_MM)
    assert (extent.size_x, extent.size_y) == (10.6, 12.5)
    assert footprint.body_height == 20
    left = extent.centre_x - extent.size_x / 2
    right = extent.centre_x + extent.size_x / 2
    top = extent.centre_y - extent.size_y / 2
    bottom = extent.centre_y + extent.size_y / 2
    centre_x = STANDARD_PITCH_MM  # the middle pin, which is the pin row's centre
    for side in (-1, 1):
        edge = centre_x + side * 10.6 / 2
        assert left <= edge <= right
    assert top <= -7 - 2.1 / 2 and bottom >= -7 + 2.1 / 2
    assert top <= -(7 + 5.5) <= bottom
    # The lugs are longer than the pins, so left on they stand the frame off the board.
    assert pytest.approx(0.6) == 3.8 - 3.2
    assert abs(2 * 2.5 - 2 * STANDARD_PITCH_MM) == pytest.approx(0.08)
    assert "0.6 mm" in part.check and "0.04 mm" in part.check
    assert "ASSUMPTION" in part.source and "RK09K" in part.source


def test_the_ec11_courtyard_covers_its_switch_pins_and_pegs_that_fit_no_hole() -> None:
    """Alps EC11: only A, C, B are on the grid. D and E (5 mm apart, 14.5 mm out) and the
    two pegs (12.5 mm outer to outer, 7.5 mm out) fit no hole, so the courtyard has to hold
    them for DRC, and the arithmetic the check quotes has to come out as it says."""
    part = catalog_part("ec11-encoder")
    assert part is not None
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None
    assert [(pin.d_col, pin.d_row) for pin in footprint.pins] == [(0, 0), (1, 0), (2, 0)]
    assert [name for _, name in part.pin_names] == ["A", "C", "B"]
    extent = body_extent(footprint, STANDARD_PITCH_MM)
    assert (extent.size_x, extent.size_y) == (12.5, 14.5)
    assert footprint.body_height == 24.5
    left = extent.centre_x - extent.size_x / 2
    right = extent.centre_x + extent.size_x / 2
    top = extent.centre_y - extent.size_y / 2
    bottom = extent.centre_y + extent.size_y / 2
    centre_x = STANDARD_PITCH_MM
    assert left <= centre_x - 12.5 / 2 and centre_x + 12.5 / 2 <= right
    assert left <= centre_x - 5 / 2 and centre_x + 5 / 2 <= right
    assert top <= -14.5 and bottom >= -7.5
    # Neither D and E's row nor the pegs' land on a row of holes: that is why they are cut.
    assert min(abs(14.5 - n * STANDARD_PITCH_MM) for n in range(7)) > 0.2
    assert round(6 * STANDARD_PITCH_MM - 14.5, 2) == 0.74
    assert "0.74 mm" in part.check and "0.04 mm" in part.check
    assert "KY-040" in part.check


def _guide_notes(part_id: str, language: str) -> list[str]:
    """The notes of the one part step in a guide for a board with only this part on it."""
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.guide import DEFAULT_GUIDE_OPTIONS, PartStep, build_guide
    from perfboard_studio.model import ComponentInstance, DocumentMeta, HoleCoord, PerfDocument

    part = catalog_part(part_id)
    assert part is not None
    component = ComponentInstance(
        id="c1", ref="U1", value=part.placed_value, footprint_id=part.footprint_id,
        pin_names=part.pin_names, anchor=HoleCoord(8, 14),
    )
    doc = PerfDocument(
        meta=DocumentMeta(name="fitting", created="", modified=""),
        board=new_board(cols=30, rows=20).board, components=(component,),
    )
    options = dataclasses.replace(DEFAULT_GUIDE_OPTIONS, language=language)
    guide = build_guide(doc, footprint_lookup(), options)
    (step,) = [s for phase in guide.phases for s in phase.steps if isinstance(s, PartStep)]
    return list(step.notes)


@pytest.mark.parametrize(
    ("part_id", "english", "turkish"),
    [
        ("rv09-pot", "lugs on the sides of its frame are 3.8 mm long against the pins' 3.2 mm",
         "tırnak pinlerin 3.2 mm'sine karşılık 3.8 mm uzundur"),
        ("ec11-encoder", "D and E are 14.5 mm from the other pins, 0.74 mm off a row",
         "D ve E diğer pinlerden 14.5 mm uzaktadır, bir delik sırasından 0.74 mm"),
        ("sw-520d", "Its leads are 2.4 mm apart and the holes 2.54: each ends 0.07 mm off",
         "Bacakları 2.4 mm arayla durur, delikler 2.54 mm: her biri deliğinden 0.07 mm"),
    ],
)
def test_the_guide_says_what_to_do_to_these_parts_before_they_fit(
    part_id: str, english: str, turkish: str
) -> None:
    """One sentence each, with the footprint's own figures, in both languages -- and the
    other language's sentence does not leak into either."""
    in_english = _guide_notes(part_id, "en")
    in_turkish = _guide_notes(part_id, "tr")
    assert len([n for n in in_english if english in n]) == 1, in_english
    assert len([n for n in in_turkish if turkish in n]) == 1, in_turkish
    assert not [n for n in in_turkish if english in n]


def test_only_the_three_parts_that_need_it_have_a_fitting_note_and_each_is_a_catalog_part() -> None:
    from perfboard_studio.footprints import FITTING_NOTES, fitting_note

    ids = {"rv09-pot", "ec11-encoder", "sw-520d"}
    carried = {part.id for part in CATALOG if (fp := get_footprint(part.footprint_id)) and fitting_note(fp)}
    assert carried == ids
    assert set(FITTING_NOTES) == {catalog_part(i).footprint_id for i in ids}  # type: ignore[union-attr]


def test_the_fitting_note_figures_are_the_sums_the_catalog_check_does() -> None:
    from perfboard_studio.footprints import FITTING_NOTES

    def facts(part_id: str) -> dict[str, float]:
        part = catalog_part(part_id)
        assert part is not None
        return dict(FITTING_NOTES[part.footprint_id].facts)

    rv09 = facts("rv09-pot")
    assert round(rv09["lug"] - rv09["pin"], 2) == rv09["gap"]
    ec11 = facts("ec11-encoder")
    assert round(6 * STANDARD_PITCH_MM - ec11["out"], 2) == ec11["off"]
    sw = facts("sw-520d")
    assert round((sw["pitch"] - sw["lead"]) / 2, 2) == sw["off"]
    assert sw["pitch"] == STANDARD_PITCH_MM


def test_the_4n35_is_named_as_vishays_top_view_names_it() -> None:
    """Vishay 81181 page 1, top view: A, C, NC down the left (pins 1 to 3), E, C, B up the
    right (4 to 6), so the base sits across from the anode and NC across from the emitter."""
    part = catalog_part("4n35")
    assert part is not None
    assert dict(part.pin_names) == {
        "1": "A", "2": "K", "3": "NC", "4": "E", "5": "C", "6": "B"
    }
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None
    where = {pin.number: (pin.d_col, pin.d_row) for pin in footprint.pins}
    assert where["1"][1] == where["6"][1] and where["3"][1] == where["4"][1]
    assert where["1"][0] == where["2"][0] == where["3"][0] != where["4"][0]
    assert "81181" in part.source


def test_the_tmp36_is_pinned_like_the_lm35_and_its_offset_sum_is_true() -> None:
    """Analog Devices draws the TMP36's TO-92 from below -- +VS, VOUT, GND -- exactly as TI
    draws the LM35's, so the two read alike from the flat face; and 750 mV at 25 degrees on
    10 mV a degree is 500 mV at zero, the number the check tells the builder to subtract."""
    tmp36, lm35 = catalog_part("tmp36"), catalog_part("lm35")
    assert tmp36 is not None and lm35 is not None
    assert tmp36.footprint_id == lm35.footprint_id == "to92"
    assert tmp36.pin_names == lm35.pin_names
    assert [name for _, name in tmp36.pin_names] == ["+VS", "VOUT", "GND"]
    assert 750 - 25 * 10 == 500
    assert "500 mV" in tmp36.check and "from below" in tmp36.check


def test_the_hc49us_crystal_is_drawn_at_abracons_maxima_and_its_lead_arithmetic_is_true() -> None:
    """Abracon ABL: 11.5 x 5.0 x 3.5 mm, legs 0.457 mm and 4.88 +-0.20 mm apart. The two
    holes two columns over are 5.08 apart; the sums in the check are done here."""
    part = catalog_part("crystal-hc49us")
    assert part is not None
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None
    assert [(pin.d_col, pin.d_row) for pin in footprint.pins] == [(0, 0), (2, 0)]
    extent = body_extent(footprint, STANDARD_PITCH_MM)
    assert (extent.size_x, extent.size_y) == (11.5, 5.0)
    assert footprint.body_height == 3.5
    nominal = (2 * STANDARD_PITCH_MM - 4.88) / 2
    worst = (2 * STANDARD_PITCH_MM - (4.88 - 0.20)) / 2
    spare = (1.0 - 0.457) / 2
    assert round(nominal, 2) == 0.10 and round(worst, 2) == 0.20 and round(spare, 2) == 0.27
    assert worst < spare
    assert "0.10 mm" in part.check and "0.27 mm" in part.check
    # Not the tall can: that is the other footprint, and each entry says which is which.
    assert part.footprint_id != "xtal-hc49"
    assert "LOW can" in part.check and "HC-49/U" in part.check


def test_the_dc_motor_is_two_wires_off_the_board_and_its_figures_are_pololus() -> None:
    """Off the board, so only the pads its wires land in: the motor has no body to measure
    and no drawing was found for the kit ones. The stall figure the check warns with is the
    source's, in the unit the check uses."""
    part = catalog_part("dc-motor-130")
    assert part is not None
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None and footprint.body.archetype == "flying-leads"
    assert len(footprint.pins) == 2
    assert [name for _, name in part.pin_names] == ["A", "B"]
    assert "2100 mA" in part.source and 2100 / 1000 == 2.1 and "2.1 A" in part.check
    assert "dc-motor-130" in [found.id for found in search_catalog("motor")][:8]
    assert next(found.id for found in search_catalog("dc motor")) == "dc-motor-130"


def test_the_l298n_board_is_a_header_in_the_order_a_sellers_photo_labels_it() -> None:
    """No drawing of the board exists: only the signal header, from ENA at one end to ENB at
    the other as the seller's photograph labels it, and no body. The motor and supply
    terminals are the board's own and the check says so."""
    part = catalog_part("l298n-board")
    assert part is not None
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None and footprint.body.archetype == "pin-header"
    assert [name for _, name in part.pin_names] == ["ENA", "IN1", "IN2", "IN3", "IN4", "ENB"]
    assert "shillehtek.com" in part.source and "no drawing" in part.source
    assert "screw terminals" in part.check and "5V jumper" in part.check


def test_the_rc522_header_is_numbered_from_the_vcc_end_as_the_photo_prints_it() -> None:
    """Two pinout images, one row: 1 to 8 from the VCC end (the seller's photo prints the
    numbers over the header). The same row from the other end is the order a tutorial
    writes, and the check says so rather than leaving a builder to guess which end."""
    part = catalog_part("rc522-module")
    assert part is not None
    names = [name for _, name in part.pin_names]
    assert names == ["3.3V", "RST", "GND", "IRQ", "MISO", "MOSI", "SCK", "SDA"]
    assert names[::-1][0] == "SDA"  # the other end's first, which the check mentions
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None and len(footprint.pins) == 8
    assert "components101" in part.source and "shillehtek" in part.source
    assert "3.3 V, not 5 V" in part.check and "SDA first" in part.check


def test_the_tall_crystal_is_the_registrys_can_and_says_it_is_not_the_kit_one() -> None:
    """The HC-49/U is the footprint the registry already draws, 13.46 mm tall, and its entry
    says so in words, and sends the owner of the low kit crystal to the other one."""
    tall, low = catalog_part("crystal-hc49u"), catalog_part("crystal-hc49us")
    assert tall is not None and low is not None
    assert tall.footprint_id == "xtal-hc49"
    footprint = get_footprint(tall.footprint_id)
    assert footprint is not None and footprint.body_height == 13.46
    assert "TALL" in tall.check and "HC-49/US" in tall.check
    assert "No maker drawing" in tall.source
    assert footprint.body_height > (get_footprint(low.footprint_id) or footprint).body_height


def test_sensor_board_3pin_has_the_names_the_joy_it_manual_gives() -> None:
    """Pin names and order are the manual's (names only, no text copied); the source says so."""
    part = catalog_part("sensor-board-3pin")
    assert part is not None
    assert [name for _, name in part.pin_names] == ["S", "+", "-"]
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None and len(footprint.pins) == 3
    assert "Joy-IT SensorKit X40 manual" in part.source
    assert "+ - and others - + S" in part.check
    assert "silkscreen" in part.check
    assert part in search_catalog("KY-018")
    assert part in search_catalog("photoresistor module")
    assert part in search_catalog("KY-003")


def test_sensor_board_4pin_has_the_names_the_joy_it_manual_gives() -> None:
    """Pin names and order are the manual's (names only, no text copied); the source says so."""
    part = catalog_part("sensor-board-4pin")
    assert part is not None
    assert [name for _, name in part.pin_names] == ["D0", "+", "-", "A0"]
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None and len(footprint.pins) == 4
    assert "Joy-IT SensorKit X40 manual" in part.source
    assert "trimmer" in part.check
    assert "inverted" in part.check
    assert part in search_catalog("KY-026")
    assert part in search_catalog("KY-038")
    assert part in search_catalog("flame sensor module")


def test_ky_009_rgb_led_has_the_names_the_joy_it_manual_gives() -> None:
    """Pin names and order are the manual's (names only, no text copied); the source says so."""
    part = catalog_part("ky-009-rgb-led")
    assert part is not None
    assert [name for _, name in part.pin_names] == ["GND", "G", "R", "B"]
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None and len(footprint.pins) == 4
    assert "Joy-IT SensorKit X40 manual" in part.source
    assert "KY-016 puts red first" in part.check
    assert "180 ohm" in part.check
    assert part in search_catalog("KY-009")


def test_ky_016_rgb_led_has_the_names_the_joy_it_manual_gives() -> None:
    """Pin names and order are the manual's (names only, no text copied); the source says so."""
    part = catalog_part("ky-016-rgb-led")
    assert part is not None
    assert [name for _, name in part.pin_names] == ["GND", "R", "G", "B"]
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None and len(footprint.pins) == 4
    assert "Joy-IT SensorKit X40 manual" in part.source
    assert "KY-009 puts green first" in part.check
    assert "180 ohm" in part.check
    assert part in search_catalog("KY-016")


def test_ky_011_two_colour_led_has_the_names_the_joy_it_manual_gives() -> None:
    """Pin names and order are the manual's (names only, no text copied); the source says so."""
    part = catalog_part("ky-011-two-colour-led")
    assert part is not None
    assert [name for _, name in part.pin_names] == ["G", "R", "GND"]
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None and len(footprint.pins) == 3
    assert "Joy-IT SensorKit X40 manual" in part.source
    assert "KY-029" in part.check
    assert "220 ohm" in part.check
    assert part in search_catalog("KY-011")
    assert part in search_catalog("KY-029")
