"""led_colour: the colour an LED's value names, in either language the interface speaks."""

from __future__ import annotations

import pytest

from perfboard_studio.ledcolour import LED_COLOUR_WORDS, LED_COLOURS, led_colour


@pytest.mark.parametrize(
    ("value", "colour"),
    [
        ("red", "red"),
        ("Red", "red"),
        ("LED 5mm green", "green"),
        ("LED_RED", "red"),
        ("5mm-yellow", "yellow"),
        ("blue LED", "blue"),
        ("orange", "orange"),
        ("Amber 3mm", "amber"),
        ("UV LED", "violet"),
        ("purple", "violet"),
        ("white", "white"),
        ("cool white", "white"),
        ("warm white", "warm-white"),
        ("Warm-White 5mm", "warm-white"),
        ("kırmızı", "red"),
        ("KIRMIZI", "red"),
        ("Kırmızı LED", "red"),
        ("yeşil", "green"),
        ("YEŞİL", "green"),
        ("sarı", "yellow"),
        ("mavi", "blue"),
        ("turuncu", "orange"),
        ("beyaz", "white"),
        ("sıcak beyaz", "warm-white"),
        ("SICAK BEYAZ", "warm-white"),
        ("mor", "violet"),
    ],
)
def test_a_value_that_names_a_colour_answers_it(value: str, colour: str) -> None:
    assert led_colour(value) == colour


@pytest.mark.parametrize(
    "value",
    ["", None, "LED", "5mm", "infrared", "IR LED", "ordered", "shred", "bluetooth", "RGB"],
)
def test_a_value_that_names_no_colour_answers_none(value: str | None) -> None:
    """Whole words only: "infrared" holds "red" and is not red."""
    assert led_colour(value) is None


@pytest.mark.parametrize("value", ["red/green bicolour", "kırmızı-yeşil", "white blue"])
def test_a_value_that_names_two_colours_answers_none(value: str) -> None:
    """A bicolour LED keeps the dome the view always drew rather than half a guess."""
    assert led_colour(value) is None


def test_warm_white_with_white_again_is_still_one_colour() -> None:
    """The phrase is consumed whole, so its "white" is not counted a second time."""
    assert led_colour("warm white, white leads") is None  # warm-white and white: two
    assert led_colour("warm white LED") == "warm-white"


def test_a_colour_named_twice_is_one_colour() -> None:
    assert led_colour("red LED, red lens") == "red"
    assert led_colour("Red / kırmızı") == "red"


def test_every_colour_has_words_in_both_languages_and_is_listed() -> None:
    assert set(LED_COLOUR_WORDS) == set(LED_COLOURS)
    for colour, words in LED_COLOUR_WORDS.items():
        assert len(words) >= 2, colour
        for word in words:
            # Every word is stored folded, or the lookup could never meet it.
            assert word == word.lower() and word.isascii(), word
            assert led_colour(word) == colour, word


def test_no_word_belongs_to_two_colours() -> None:
    seen: dict[str, str] = {}
    for colour, words in LED_COLOUR_WORDS.items():
        for word in words:
            assert seen.setdefault(word, colour) == colour, word
