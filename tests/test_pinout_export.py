"""The pinout card as an SVG page (``pinout_export``): what is drawn, and what is said."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from perfboard_studio.catalog import CATALOG
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.pinout import PinoutCard, pinout_card
from perfboard_studio.pinout_export import (
    GROUP_OF,
    PINOUT_DARK,
    PINOUT_LIGHT,
    WARNING_WORDS,
    pinout_svg,
    shown_functions,
)

LOOKUP = footprint_lookup()
SVG = "{http://www.w3.org/2000/svg}"


def _card(part_id: str) -> PinoutCard:
    card = pinout_card(part_id, LOOKUP)
    assert card is not None
    return card


def _cards() -> list[PinoutCard]:
    return [c for c in (pinout_card(p, LOOKUP) for p in CATALOG) if c is not None]


def _texts(svg: str) -> list[str]:
    return [e.text or "" for e in ET.fromstring(svg).iter(f"{SVG}text")]


def test_every_card_in_the_catalogue_is_a_well_formed_tiny_svg() -> None:
    """Every part with pin names makes a card, in both languages and both inks, that an
    XML parser reads and that leans on nothing SVG Tiny -- what QtSvg renders -- lacks."""
    cards = _cards()
    assert len(cards) > 20
    for card in cards:
        for language in ("en", "tr"):
            for ink in (PINOUT_LIGHT, PINOUT_DARK):
                svg = pinout_svg(card, language=language, ink=ink)
                root = ET.fromstring(svg)
                assert root.get("baseProfile") == "tiny"
                assert "dominant-baseline" not in svg
                assert "<image" not in svg


def test_every_pin_is_named_on_its_card() -> None:
    for card in _cards():
        texts = _texts(pinout_svg(card))
        for pin in card.pins:
            assert pin.name in texts, (card.part_id, pin.name)


def test_the_esp32s_strapping_pins_are_exactly_the_five_the_datasheet_names() -> None:
    """ESP32 datasheet section 2.4: GPIO0, 2, 5, 12 and 15 are read at reset."""
    card = _card("esp32-devkitc")
    strapping = {p.port for p in card.pins if "strapping" in p.warnings}
    assert strapping == {"GPIO0", "GPIO2", "GPIO5", "GPIO12", "GPIO15"}


def test_the_esp32s_input_only_pins_are_34_to_39() -> None:
    card = _card("esp32-devkitc")
    found = {p.port for p in card.pins if "input-only" in p.warnings}
    # 37 and 38 are not brought out on a DevKitC.
    assert found == {"GPIO34", "GPIO35", "GPIO36", "GPIO39"}


def test_a_pin_with_two_warnings_gets_two_triangles_not_one_reading_25() -> None:
    """IO12 is both a strapping pin and an ADC2 channel: two numbered triangles side by
    side, where one triangle used to carry both numbers run together."""
    card = _card("esp32-devkitc")
    io12 = next(p for p in card.pins if p.name == "IO12")
    assert len(io12.warnings) == 2
    svg = pinout_svg(card)
    on_pins = sum(len(p.warnings) for p in card.pins)
    assert svg.count("<polygon") == on_pins + len(card.warnings)
    # Every triangle carries one warning's number, never two run together.
    triangle_numbers = re.findall(r'font-size="8.5"[^>]*>([^<]*)</text>', svg)
    assert len(triangle_numbers) == on_pins + len(card.warnings)
    assert set(triangle_numbers) == {str(i) for i in range(1, len(card.warnings) + 1)}


def test_a_module_card_says_its_pad_numbers_are_the_apps() -> None:
    """A module's pad numbers are the footprint's count, not what its maker prints, so the
    card frames them and says so; a bare chip's are the maker's and need no note."""
    nano = " ".join(_texts(pinout_svg(_card("arduino-nano"))))
    chip = " ".join(_texts(pinout_svg(_card("attiny85"))))
    assert "app's pad numbers" in nano
    assert "app's pad numbers" not in chip


def test_a_board_names_its_chip_under_its_title() -> None:
    texts = _texts(pinout_svg(_card("esp32-devkitc")))
    assert any(t.split("·")[0].strip() == "ESP32" for t in texts)
    texts = _texts(pinout_svg(_card("arduino-nano")))
    assert any(t.split("·")[0].strip() == "ATmega328P" for t in texts)


def test_a_chip_and_its_names_are_not_repeated_as_functions() -> None:
    """A function that only repeats the pin's name or port is left off its chips, and a
    kind said once for the whole card (PCINT) is on no pin."""
    for card in _cards():
        for pin in card.pins:
            for function in shown_functions(pin):
                assert function.label not in (pin.name, pin.port)
                assert GROUP_OF[function.kind] is not None


def test_a_turkish_card_says_its_warnings_in_turkish() -> None:
    card = _card("esp32-devkitc")
    english = " ".join(_texts(pinout_svg(card, language="en")))
    turkish = " ".join(_texts(pinout_svg(card, language="tr")))
    for warning in card.warnings:
        assert WARNING_WORDS[warning] in english
        assert WARNING_WORDS[warning] not in turkish
    assert "Yalnızca giriş" in turkish
    # The maker's names are the same in both.
    assert "IO12" in turkish and "ADC2_CH5" in turkish


ART = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<svg width="100" height="60" viewBox="0 0 100 60" xmlns="http://www.w3.org/2000/svg" '
    'version="1.2" baseProfile="tiny"><title>Qt SVG Document</title>'
    '<desc>Generated with Qt</desc><defs><linearGradient id="g"/></defs>'
    '<g><rect x="1" y="2" width="3" height="4" fill="#123456"/></g></svg>'
)


def test_the_art_is_placed_in_the_frame_as_it_is() -> None:
    """The window hands in the part drawn by the board view; the card keeps its drawing and
    its definitions, drops its root, title and description, and scales its viewBox onto
    the frame."""
    card = _card("attiny85")
    svg = pinout_svg(card, art=ART)
    root = ET.fromstring(svg)
    assert '<rect x="1" y="2" width="3" height="4" fill="#123456"/>' in svg
    assert '<linearGradient id="g"/>' in svg
    assert "Qt SVG Document" not in svg and "Generated with Qt" not in svg
    assert svg.count("<svg") == 1
    group = re.search(r'<g transform="translate\(([-\d.]+) ([-\d.]+)\) scale\(([\d.e-]+) ([\d.e-]+)\)', svg)
    assert group is not None
    x0, x1, y0, y1 = card.frame
    mm = 11.0
    assert float(group.group(3)) == pytest.approx((x1 - x0) * mm / 100, rel=1e-4)
    assert float(group.group(4)) == pytest.approx((y1 - y0) * mm / 60, rel=1e-4)
    assert root is not None


def test_the_plain_body_and_the_art_lay_the_labels_out_alike() -> None:
    """With art or without, every label is where it was: the two differ in the middle."""
    card = _card("arduino-nano")
    plain = pinout_svg(card)
    drawn = pinout_svg(card, art=ART)
    labels = re.compile(r'<text x="[^"]+" y="[^"]+"[^>]*>(?:D\d+|A\d|VIN|GND|RX0|TX1)</text>')
    assert labels.findall(plain) == labels.findall(drawn)


def test_art_that_is_not_an_svg_is_refused() -> None:
    with pytest.raises(ValueError):
        pinout_svg(_card("attiny85"), art="<g/>")


def test_two_triangles_read_in_rising_order_on_either_side() -> None:
    """IO12 is on the left and IO0 on the right; both read "2 5" left to right."""
    card = _card("esp32-devkitc")
    svg = pinout_svg(card)
    triangles = re.findall(
        r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*font-size="8.5"[^>]*>(\d+)</text>', svg
    )
    for name in ("IO12", "IO0", "IO2", "IO15"):
        pin = next(p for p in card.pins if p.name == name)
        assert len(pin.warnings) == 2
        x, y = _label_at(svg, name)
        # On its own row, the two nearest its name: the row's other side is another pin.
        row = sorted(
            ((float(tx), int(n)) for tx, ty, n in triangles if abs(float(ty) - y) < 1),
            key=lambda found: abs(found[0] - x),
        )[:2]
        assert [n for _x, n in sorted(row)] == [2, 5], name


def _label_at(svg: str, name: str) -> tuple[float, float]:
    found = re.search(rf'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*>{name}</text>', svg)
    assert found is not None
    return float(found.group(1)), float(found.group(2))


def test_a_card_with_nothing_to_say_below_its_part_has_no_rule_over_an_empty_foot() -> None:
    # The frame is the one stroke in the border colour; the foot's rule is the second.
    border = f'stroke="{PINOUT_LIGHT.border}"'
    assert pinout_svg(_card("ne555")).count(border) == 1
    assert pinout_svg(_card("atmega328p")).count(border) == 2
