"""A search ranks what it finds by where it found it (``catalog.search_rank``).

The queries are the ones a walkthrough of the window got wrong: "resistor" listed an
inductor and a photoresistor above the resistor packages and a beginner took the LDR;
"power" put a TIP31C first and the power inputs sixth; Turkish "LED" put the AA battery
holder first. What is pinned, in English and in Turkish: a thing whose name starts with the
words comes first, then one they name word by word, then one with them inside a word of its
name, then one whose summary merely says them -- for a catalog part and a bare package
alike, since the tree and the picker list both.
"""

from __future__ import annotations

import pytest

from perfboard_studio.catalog import (
    RANK_IN_NAME,
    RANK_NAME_STARTS,
    RANK_NAMED,
    RANK_SAID,
    catalog_part,
    part_rank,
    search_catalog,
    search_rank,
)
from perfboard_studio.footprints import get_footprint
from perfboard_studio.phrasebook import phrasebook
from perfboard_studio.ui.i18n import TURKISH


def _package_rank(text: str, footprint_id: str, language: str = "en") -> int | None:
    footprint = get_footprint(footprint_id)
    assert footprint is not None
    name = phrasebook(language).footprint(footprint.name)
    return search_rank(text, names=(name, footprint.id), fold=_fold(language))


def _fold(language: str):  # type: ignore[no-untyped-def]
    if language == "tr":
        return lambda s: s.replace("I", "ı").replace("İ", "i").lower()
    return str.lower


def _part_rank(text: str, part_id: str, language: str = "en") -> int | None:
    part = catalog_part(part_id)
    assert part is not None
    if language == "tr":
        return part_rank(
            part,
            text,
            names=(TURKISH.get(part.name, part.name),),
            said=(TURKISH.get(part.summary, part.summary),),
            fold=_fold("tr"),
        )
    return part_rank(part, text)


@pytest.mark.parametrize(("query", "language"), [("resistor", "en"), ("direnç", "tr")])
def test_a_resistor_is_found_before_the_parts_that_only_mention_one(query: str, language: str) -> None:
    package = _package_rank(query, "r-axial-4", language)
    ldr = _part_rank(query, "gl5528", language)
    inductor = _part_rank(query, "bourns-78f101j", language)
    assert package == RANK_NAME_STARTS, package
    assert ldr is not None and package < ldr  # "photoresistor" / "fotodirenç"
    if inductor is not None:  # its summary says it lies like a resistor
        assert ldr <= inductor


@pytest.mark.parametrize(("query", "language"), [("power", "en"), ("güç", "tr")])
def test_power_finds_the_power_inputs_before_a_power_transistor(query: str, language: str) -> None:
    power_in = _part_rank(query, "power-header-2", language)
    tip31c = _part_rank(query, "tip31c", language)
    assert power_in == RANK_NAME_STARTS, power_in
    assert tip31c is None or tip31c > power_in


@pytest.mark.parametrize("language", ["en", "tr"])
def test_led_finds_an_led_before_anything_with_the_letters_in_a_word(language: str) -> None:
    led = _part_rank("LED", "led-5mm", language)
    holder = _part_rank("LED", "battery-aa-holder", language)
    assert led == RANK_NAME_STARTS, led
    assert holder is None or holder > led


def test_the_ranks_are_where_the_words_were_found() -> None:
    names = ("Power in, 2-pin header", "power-header-2", "power")
    assert search_rank("power in", names=names) == RANK_NAME_STARTS
    assert search_rank("header", names=names) == RANK_NAMED
    assert search_rank("ower", names=names) == RANK_IN_NAME
    assert search_rank("supply", names=names, said=("A supply's two leads",)) == RANK_SAID
    assert search_rank("relay", names=names) is None
    assert search_rank("", names=names) == RANK_NAME_STARTS
    # A part number finds its part whatever is on the end: "LM358N" is the LM358.
    lm358 = catalog_part("lm358")
    assert lm358 is not None and part_rank(lm358, "LM358N") is not None


def test_search_catalog_puts_the_best_first() -> None:
    found = [part.id for part in search_catalog("power")]
    assert found.index("power-header-2") < found.index("tip31c")
    assert search_catalog("resistor")[0].id == "gl5528"  # no catalog resistor: the LDR, then
