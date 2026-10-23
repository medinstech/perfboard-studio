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
from perfboard_studio.footprints import get_footprint
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
        "esp32-c3-devkitm-1": 22.86,
        "arduino-nano": 15.24,
        "raspberry-pi-pico": 17.78,
        "wemos-d1-mini": 22.86,
        "pololu-a4988": 12.7,
        "pololu-drv8825": 12.7,
        "seeed-xiao-esp32c3": 15.24,
        # The grid nearest Handsontec's 39.50 mm, which its check says: pads, not pins.
        "lm2596-module": 40.64,
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
        "esp32-devkitc", "esp32-c3-devkitm-1", "seeed-xiao-esp32c3"
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
    assert [part.id for part in search_catalog("relay")] == ["srd-05vdc-sl-c", "srd-12vdc-sl-c"]
    assert [part.id for part in search_catalog("SRD-05VDC-SL-C")] == ["srd-05vdc-sl-c"]
    # The 12 V one is the same package and the same legs.
    twelve = catalog_part("srd-12vdc-sl-c")
    assert twelve is not None
    assert (twelve.footprint_id, twelve.pin_names) == (relay.footprint_id, relay.pin_names)


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
