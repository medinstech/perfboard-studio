"""What colour an LED shines, read from the part's value.

A part's value is the builder's own text -- "green", "LED 5mm yellow", "kırmızı" -- and
until it was read every round LED was drawn red, a green one included. The answer is a
colour NAME, never a shade: what red looks like on a dome is the view's business, and the
2D view, the 3D view, the part icons and the STEP export all ask here and choose their own
shade for the name.

The value is matched by whole words, so "infrared" is not red and "ordered" is nothing;
both languages the interface speaks are read, whichever the window is in, because the
value was typed once and the board is opened in either. A value that names two colours
(a bicolour LED) answers ``None``, as one that names none does: the caller keeps the dome
it always drew rather than guessing which of the two to show. Hangs off nothing at all --
a table and a lookup.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

LedColour = Literal[
    "red", "orange", "amber", "yellow", "green", "blue", "violet", "white", "warm-white"
]

#: Every colour ``led_colour`` can answer, warm to cool, then the whites.
LED_COLOURS: tuple[LedColour, ...] = (
    "red", "orange", "amber", "yellow", "green", "blue", "violet", "white", "warm-white",
)

#: Each colour's words, English and Turkish, folded as ``_fold`` folds a value: lower case,
#: Turkish letters to their ASCII base ("kırmızı" is "kirmizi"). A phrase of two words is
#: matched before either word alone, so "warm white" is never plain white.
LED_COLOUR_WORDS: dict[LedColour, tuple[str, ...]] = {
    "red": ("red", "kirmizi"),
    "orange": ("orange", "turuncu"),
    "amber": ("amber", "kehribar"),
    "yellow": ("yellow", "sari"),
    "green": ("green", "yesil"),
    "blue": ("blue", "mavi"),
    "violet": ("violet", "purple", "uv", "ultraviolet", "mor", "ultraviyole"),
    "white": ("white", "beyaz", "cool white", "soguk beyaz"),
    "warm-white": ("warm white", "warmwhite", "sicak beyaz"),
}

_PHRASES: dict[tuple[str, ...], LedColour] = {
    tuple(word.split()): colour
    for colour, words in LED_COLOUR_WORDS.items()
    for word in words
}
_LONGEST = max(len(phrase) for phrase in _PHRASES)

#: Turkish letters that have no decomposition to fall back on.
_TURKISH_ASCII = str.maketrans({"ı": "i", "İ": "i", "I": "i"})


def _fold(text: str) -> str:
    """``text`` lower-cased with its accents and Turkish letters reduced to ASCII.

    "I" folds to "i" before anything else, so "KIRMIZI" typed on an English keyboard and
    "kırmızı" typed on a Turkish one read the same. The marks NFKD splits off ("ş" is "s"
    and a cedilla) are then dropped.
    """
    decomposed = unicodedata.normalize("NFKD", text.translate(_TURKISH_ASCII).lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def led_colour(value: str | None) -> LedColour | None:
    """The colour ``value`` names an LED, or ``None`` when it names none or more than one.

    Whole words only, split at anything that is not a letter or a digit ("LED_RED",
    "5mm-green" and "Yeşil LED" all read). Longer phrases win over their words, so
    "warm white" is warm white and "cool white" is white.
    """
    if not value:
        return None
    words = re.findall(r"[a-z0-9]+", _fold(value))
    found: set[LedColour] = set()
    index = 0
    while index < len(words):
        for length in range(min(_LONGEST, len(words) - index), 0, -1):
            colour = _PHRASES.get(tuple(words[index : index + length]))
            if colour is not None:
                found.add(colour)
                index += length
                break
        else:
            index += 1
    return found.pop() if len(found) == 1 else None
