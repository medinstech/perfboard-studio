"""A part's pinout card: every pin where its pad is, with what the pin can do.

``pinfunctions`` holds the facts; this module lays them out, and ``pinout_export`` draws
the result. The split is ``schematic`` / ``schematic_export``'s, for the same reason: what
is on the card is a question with a right answer, and a test can ask it without parsing
an SVG.

**THE PINS ARE WHERE THE PADS ARE.** A card drawn from a datasheet's idealised box is one
more thing to translate before the iron goes in. This one is drawn from the FOOTPRINT the
part is placed with, seen from the component side: a DIP runs down its left side and back
up its right, a Nano's two headers are its two columns, and the pin a builder counts to on
the card is the pin they count to on the board. Each pin's labels go out on the side its
pad is on, so nothing crosses the body. Where two pins on one side share a row, their
labels would be drawn over each other: a header of two columns then sends one column's
labels each way, and a TO-92's three legs, a screw terminal or a header lying along the
board send them above and below instead (:func:`_sides`).

**A CARD SAYS ONLY WHAT IT USES.** Its legend is the kinds of function and the warnings
that appear on it, nothing else; a part with names and roles but no MCU behind it still
gets a card -- its names, where they are -- and a part with no pin names gets none.

Pure: the catalogue, the footprints and the function tables in, a frozen card out.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Literal

from .catalog import CatalogPart, catalog_part
from .connectivity import FootprintLookup
from .footprints import body_extent
from .model import PinRole
from .pinfunctions import (
    ANY_PIN,
    FUNCTION_KINDS,
    MCU_NAMES,
    PIN_WARNINGS,
    Document,
    FunctionKind,
    LogicLevel,
    PinFunction,
    PinWarning,
    board_pins,
    documents,
    pin_warnings,
    port_functions,
)

#: A card is laid out on the board's own grid: pad positions are millimetres at this
#: pitch, the pitch every catalogue part's pins are on.
CARD_PITCH_MM = 2.54

#: How far past its centre a pad reaches, for the frame: a 1.8 mm pad and a little air.
PAD_REACH_MM = 1.0

Side = Literal["left", "right", "above", "below"]

#: Two pads closer than this in y are on one row.
SAME_ROW_MM = 0.5


@dataclass(frozen=True, slots=True)
class PinoutPin:
    """One pin on the card."""

    number: str
    #: What the board or the chip prints beside it ("D3", "PB2", "GND").
    name: str
    #: The MCU port behind it ("PD3"), or ``None`` for a pin that is no port.
    port: str | None
    role: PinRole | None
    #: The pad's centre, millimetres from pin 1, seen from the component side.
    x: float
    y: float
    #: Which side of the body its labels go out on.
    side: Side
    #: Its alternate functions, in :data:`FUNCTION_KINDS` order.
    functions: tuple[PinFunction, ...]
    warnings: tuple[PinWarning, ...]


@dataclass(frozen=True, slots=True)
class PinoutCard:
    part_id: str
    #: The part as the catalogue names it ("Arduino Nano").
    title: str
    #: The MCU's catalogue id when the part has one behind it, else ``None``.
    mcu: str | None
    #: The MCU's own name ("ATmega328P") for a board that carries one, else ``None``.
    mcu_name: str | None
    logic: LogicLevel | None
    #: The body seen from above, ``(min_x, max_x, min_y, max_y)`` in the pins' millimetres.
    body: tuple[float, float, float, float]
    pins: tuple[PinoutPin, ...]
    #: The kinds of function on the card, in :data:`FUNCTION_KINDS` order: its legend.
    kinds: tuple[FunctionKind, ...]
    #: The warnings on the card, in :data:`PIN_WARNINGS` order.
    warnings: tuple[PinWarning, ...]
    #: Kinds the MCU routes to any pin (``pinfunctions.ANY_PIN``): said once, not per pin.
    any_pin: tuple[FunctionKind, ...]
    #: Whether the numbers are the maker's: a bare chip's pads are its pin numbers, while a
    #: module's are the footprint's own count, which is not what the board's maker prints.
    numbered_by_maker: bool
    #: The box the middle of the card is drawn in, ``(min_x, max_x, min_y, max_y)``: the body
    #: and every pad, so a drawing of the part from above fits it whole.
    frame: tuple[float, float, float, float]
    #: What the ports and the functions were read from (``pinfunctions.documents``).
    documents: tuple[Document, ...]


def _side(x: float, centre_x: float) -> Side:
    """Left of the body's centre line goes out left; on it or right of it, right."""
    return "left" if x < centre_x - 1e-6 else "right"


def _collide(pins: list[PinoutPin]) -> bool:
    """Whether two pins whose labels go out on one side share a row."""
    for side in ("left", "right"):
        ys = sorted(p.y for p in pins if p.side == side)
        if any(b - a < SAME_ROW_MM for a, b in pairwise(ys)):
            return True
    return False


def _lines(values: list[float]) -> list[float]:
    """The distinct rows (or columns) ``values`` fall on."""
    found: list[float] = []
    for value in sorted(values):
        if not found or value - found[-1] >= SAME_ROW_MM:
            found.append(value)
    return found


def _sides(pins: list[PinoutPin]) -> list[PinoutPin]:
    """Left and right of the body's centre line, unless two pins on one side share a row.

    Then a header of two columns -- an nRF24L01's 2 x 4 at one end of its board -- sends its
    left column's labels left and its right column's right, as every pinout of one does;
    anything else goes out above and below, the top row's labels above and every other
    row's below, one pin to a step.
    """
    if not _collide(pins):
        return pins
    columns = _lines([p.x for p in pins])
    if len(columns) == 2:
        split = (columns[0] + columns[1]) / 2
        paired = [replace(p, side="left" if p.x < split else "right") for p in pins]
        if not _collide(paired):
            return paired
    top = min(p.y for p in pins)
    single_row = len(_lines([p.y for p in pins])) == 1
    return [
        replace(p, side="above" if not single_row and p.y - top < SAME_ROW_MM else "below")
        for p in pins
    ]


def _kind_order(function: PinFunction) -> int:
    return FUNCTION_KINDS.index(function.kind)


def pinout_card(part: CatalogPart | str, lookup: FootprintLookup) -> PinoutCard | None:
    """The card for a catalogue part, or ``None`` when there is nothing to draw.

    ``None`` for a part the catalogue does not have, one with no pin names, and one whose
    footprint ``lookup`` does not know.
    """
    if isinstance(part, str):
        found = catalog_part(part)
        if found is None:
            return None
        part = found
    if not part.pin_names:
        return None
    footprint = lookup(part.footprint_id)
    if footprint is None:
        return None

    names = dict(part.pin_names)
    roles = dict(part.pin_roles)
    mapped = board_pins(part.id)
    ports: dict[str, str | None] = {}
    if mapped is not None:
        ports = {
            number: port
            for (number, _), port in zip(part.pin_names, mapped.ports, strict=True)
        }

    extent = body_extent(footprint, CARD_PITCH_MM)
    pins: list[PinoutPin] = []
    for pad in footprint.pins:
        x = pad.d_col * CARD_PITCH_MM
        y = pad.d_row * CARD_PITCH_MM
        name = names.get(pad.number, pad.name or pad.number)
        port = ports.get(pad.number)
        functions: tuple[PinFunction, ...] = ()
        if mapped is not None:
            functions = tuple(sorted(port_functions(mapped.mcu, port), key=_kind_order))
        pins.append(
            PinoutPin(
                number=pad.number,
                name=name,
                port=port,
                role=roles.get(pad.number),
                x=x,
                y=y,
                side=_side(x, extent.centre_x),
                functions=functions,
                warnings=pin_warnings(part.id, name, port),
            )
        )

    pins = _sides(pins)
    used_kinds = {f.kind for pin in pins for f in pin.functions}
    used_warnings = {w for pin in pins for w in pin.warnings}
    mcu_name: str | None = None
    if mapped is not None and mapped.mcu != part.id:
        chip = catalog_part(mapped.mcu)
        mcu_name = chip.name if chip is not None else MCU_NAMES.get(mapped.mcu, mapped.mcu)
    min_x, max_x, min_y, max_y = extent.box
    frame = (
        min(min_x, *(p.x - PAD_REACH_MM for p in pins)),
        max(max_x, *(p.x + PAD_REACH_MM for p in pins)),
        min(min_y, *(p.y - PAD_REACH_MM for p in pins)),
        max(max_y, *(p.y + PAD_REACH_MM for p in pins)),
    )
    return PinoutCard(
        part_id=part.id,
        title=part.name,
        mcu=mapped.mcu if mapped is not None else None,
        mcu_name=mcu_name,
        logic=mapped.logic if mapped is not None else None,
        body=extent.box,
        pins=tuple(pins),
        kinds=tuple(k for k in FUNCTION_KINDS if k in used_kinds),
        warnings=tuple(w for w in PIN_WARNINGS if w in used_warnings),
        any_pin=ANY_PIN.get(mapped.mcu, ()) if mapped is not None else (),
        numbered_by_maker=part.category != "module",
        frame=frame,
        documents=documents(part.id),
    )
