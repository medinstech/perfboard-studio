"""Symbol bodies: what a part looks like on the sheet, drawn unturned.

``schematic.py`` places, turns, mirrors, wires and names the symbols; this module only
draws each one, as a builder ``(pins, footprint) -> SymbolBody`` in ``BUILDERS``, and
``schematic.py`` is the only module that imports it (re-exporting what the window, the
exporter and the tests read from there). The split is a seam for work on the bodies that
does not touch the layout, and it holds by these rules:

- A body is drawn unturned. Its origin (0, 0) is the top-left, and everything lies inside
  ``width`` x ``height``, which are whole grid steps. Pins point left or right; top and
  bottom are only for an IC's power and ground.
- Every pin's ``at`` is the free end of its lead, on the 2.54 mm grid measured from the
  origin. The layout snaps symbols to the grid, and the first edit of a sheet freezes it
  by snapping every symbol, so a pin off the grid would move on that edit.
- No text in a body except pin names, carried in ``SymbolPin.name``. The reference, the
  value and the net names are the layout's.

Pure like the rest of the engine: no clock, no RNG, no filesystem, no Qt.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

from .model import (
    BodyArchetype,
    Footprint,
    Mm,
    PartSymbol,
    PinRole,
    Point2,
    pin_number_sort_key,
)

# ---------------------------------------------------------------------------
# The grid a body is drawn on
# ---------------------------------------------------------------------------

#: Which way a pin's lead points out of its body.
type PinSide = Literal["left", "right", "top", "bottom"]

#: 0.1 inch. Schematics are drawn on this grid, KiCad's default is this grid, and every
#: coordinate this module emits is a multiple of it or a half of one.
GRID_MM: Mm = 2.54

#: Lead length between a symbol's body and the point a wire attaches to.
LEAD_MM: Mm = 2 * GRID_MM

#: Pin-to-pin spacing down the side of a multi-pin body.
PIN_PITCH_MM: Mm = 2 * GRID_MM

#: The height a net name is drawn at, in millimetres of sheet, and the average advance of
#: one character as a fraction of it.
#:
#: ONE FACT, TWO CONSUMERS. The LAYOUT has to know how much room a net name takes in
#: order to keep a wire out of it, and only a renderer knows the real size -- so the
#: exported sheet takes its size from here (``SheetInk.net_mm``) rather than naming its
#: own, and the panel, which draws text at a fixed PIXEL size on purpose, treats this as
#: the nominal it was always laid out against. The advance is an average over a
#: sans-serif's alphabet; it only has to be close, because the label search in
#: ``schematic`` steps in half grid squares and a net name is six characters. Here because
#: a box is as wide as its pin names, measured by the same advance (``pin_label_width``).
NET_LABEL_MM: Mm = 1.3
NET_LABEL_ADVANCE: float = 0.55

#: The height a pin number or pin name is drawn at, in millimetres of sheet.
#:
#: The same arrangement as ``NET_LABEL_MM``: a box WIDENS to fit the names its part
#: declares, so the layout has to know how much room a name takes, and the exported sheet
#: takes its size from here (``SheetInk.pin_mm``) rather than naming its own.
PIN_LABEL_MM: Mm = 1.0

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

#: Spelled with ``TypeAlias`` rather than PEP 695's ``type``, and it has to be: this name
#: is READ AT RUN TIME by ``get_args`` in ``test_schematic.py``, which asserts every kind
#: has a builder. A PEP 695 alias returns an empty tuple there, and the test would then
#: assert that an empty set equals an empty set -- the trap ``model.py`` documents five
#: times over.
SymbolKind: TypeAlias = Literal[  # noqa: UP040
    "resistor",
    "capacitor",
    "polarised-capacitor",
    "diode",
    "led",
    "crystal",
    "potentiometer",
    "switch",
    "relay",
    "ic",
    "connector",
    "box",
    # Drawn only when a part DECLARES itself one of these (``model.PartSymbol``); nothing
    # in the registry asks for them, because no package knows which of its legs is which.
    "zener",
    "fuse",
    "battery",
    "jack",
    "npn",
    "pnp",
    "nmos",
    "pmos",
    # The same claim, for parts whose leads the part's own NAMES settle.
    "regulator",
    "button",
    "buzzer",
    "inductor",
    "motor",
    "optocoupler",
]


@dataclass(frozen=True, slots=True)
class SymbolShape:
    """One primitive of a symbol body, in symbol-local millimetres.

    Three kinds and no more, because a schematic symbol is lines, closed shapes and
    circles -- and a renderer that has to handle a fourth is a renderer with an untested
    branch in it.
    """

    kind: Literal["polyline", "polygon", "circle"]
    #: ``polyline``/``polygon``: the vertices. ``circle``: one point, the centre.
    points: tuple[Point2, ...]
    #: ``circle`` only.
    radius: Mm = 0.0
    filled: bool = False


@dataclass(frozen=True, slots=True)
class SymbolPin:
    """One lead of a symbol. ``at`` is where a WIRE attaches, not where the body ends.

    ``side`` is which way the lead points OUT of the body, so a wire, a net label or a
    rail stub knows which direction to leave in. Every symbol is drawn with its pins left
    and right; the other two appear once a symbol has been turned a quarter, which is what
    ``schematic._orient_body`` does to it.
    """

    number: str
    name: str | None
    at: Point2
    side: PinSide


# ---------------------------------------------------------------------------
# Symbols, generated from the footprint registry
# ---------------------------------------------------------------------------
#
# The rule this section enforces, stated once: a symbol gets its real electrical shape only
# where the registry knows what each of its leads IS. Two leads plus a body archetype is
# enough to tell a resistor from a ceramic capacitor; a plus, a K or an A in a pin name is
# enough to know which way round a polarised part goes. Three leads on a TO-92 is not
# enough to know which one is the base, so a TO-92 is a box with numbered pins -- which is
# less pretty and does not lie.


@dataclass(frozen=True, slots=True)
class PinSpec:
    number: str
    name: str | None
    role: PinRole | None = None


@dataclass(frozen=True, slots=True)
class SymbolBody:
    shapes: tuple[SymbolShape, ...]
    pins: tuple[SymbolPin, ...]
    width: Mm
    height: Mm
    #: The sheet prints each pin's name just inside the body, at its lead, and the number
    #: on the lead outside. Only a body that leaves room for the names says so: the leads
    #: stop at the box and nothing is drawn through the text.
    names_inside: bool = False


def _p(x: Mm, y: Mm) -> Point2:
    return Point2(x=x, y=y)




def _pin_sort_key(number: str) -> tuple[int, float, str]:
    """Pin "10" after pin "9", and a lettered pin after every numbered one.

    A netlist may name a pin anything. Sorting the numbers as text puts pin 10 between 1
    and 2 and silently reorders half a DIP-16. The rule itself lives in ``model``, which
    orders a part's declared pin names by it; the two must never sort differently.
    """
    return pin_number_sort_key(number)


def _other_pin(pins: tuple[PinSpec, ...], number: str) -> str | None:
    for pin in pins:
        if pin.number != number:
            return pin.number
    return None


def _cathode_pin_number(pins: tuple[PinSpec, ...], polarized: bool) -> str | None:
    """Which lead is the cathode, by the rule ``guide._polarity_note`` already follows.

    Names first, convention second, and in that order deliberately: an LED has pin 1 as its
    ANODE and a diode has pin 1 as its cathode, so a rule that reads pin 1 without looking
    at the names draws one of the two backwards -- on the screen, and then on the bench.
    """
    for pin in pins:
        if pin.name == "K":
            return pin.number
    for pin in pins:
        if pin.name == "A":
            return _other_pin(pins, pin.number)
    if polarized and len(pins) == 2:
        # Unnamed but polarised: a diode, where pin 1 is the cathode by the convention this
        # registry and KiCad DO-41 both follow.
        return pins[0].number
    return None


def _positive_pin_number(pins: tuple[PinSpec, ...], polarized: bool) -> str | None:
    """Which lead of an electrolytic is the positive one. Names first, as above."""
    for pin in pins:
        if pin.name == "+":
            return pin.number
    for pin in pins:
        if pin.name == "-":
            return _other_pin(pins, pin.number)
    if polarized and len(pins) == 2:
        return pins[0].number
    return None


def _switch_poles(
    footprint: Footprint | None,
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """The two nodes of a four-legged tactile switch, as pin numbers, or ``None``.

    THE ONE THING A SWITCH PACKAGE DOES SAY ABOUT ITSELF. A 6 mm tactile switch has four
    legs in two pairs and the pair on each SIDE of the body is bonded together inside it --
    that is what the part IS, not what one manufacturer chose, which is exactly the
    difference from a TO-92's base. So this symbol may exist where a transistor's may not.

    Read off the footprint's own GEOMETRY rather than off pin numbers: a package that
    numbered its legs some other way gets a box instead of a lie, and the columns are what
    the physical part is bonded along.
    """
    if footprint is None or len(footprint.pins) != 4:
        return None
    columns = sorted({pin.d_col for pin in footprint.pins})
    if len(columns) != 2:
        return None
    left = tuple(pin.number for pin in footprint.pins if pin.d_col == columns[0])
    right = tuple(pin.number for pin in footprint.pins if pin.d_col == columns[1])
    if len(left) != 2 or len(right) != 2:
        return None
    return left, right


def _relay_sides(
    footprint: Footprint | None,
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """The coil's pins and the contact set's, as pin numbers, or ``None``.

    A PCB relay's coil is a PAIR of pins along one side of the body and its contacts are
    the several along the other; which side is which is the count, and that much is true of
    every relay this tool can hold a footprint for.

    WHICH CONTACT IS THE COMMON ONE IS NOT, and this deliberately does not say. Songle and
    Omron disagree about it on packages of the same outline, so the symbol draws the
    contacts as numbered leads out of a contact block rather than as a blade resting on one
    of them: a sheet that named the wrong pin COM is a board built normally-closed when it
    was meant to be normally-open, and it would look right the whole way.
    """
    if footprint is None or len(footprint.pins) < 4:
        return None
    columns = sorted({pin.d_col for pin in footprint.pins})
    if len(columns) != 2:
        return None
    sides = [
        tuple(pin.number for pin in footprint.pins if pin.d_col == column) for column in columns
    ]
    coils = [side for side in sides if len(side) == 2]
    if len(coils) != 1:
        # Both sides a pair, or neither: nothing here says which one is the winding.
        return None
    coil = coils[0]
    contacts = next(side for side in sides if side is not coil)
    return coil, contacts


# -- two-terminal geometry ---------------------------------------------------
#
# Every two-lead symbol is the same size and sits on the same axis, so a row of them lines
# up without the layout having to know what any of them is.

_TWO_W: Mm = 8 * GRID_MM
_TWO_H: Mm = 4 * GRID_MM
_AXIS: Mm = _TWO_H / 2


def _two_terminal_pins(
    pins: tuple[PinSpec, ...], left_number: str | None
) -> tuple[SymbolPin, ...]:
    """Pin 1 on the left unless ``left_number`` says otherwise.

    The polarity helpers return a pin NUMBER rather than a side, so this is where a part
    whose cathode is pin 2 gets DRAWN the other way round instead of being relabelled.
    """
    ordered = list(pins)
    if left_number is not None and len(ordered) == 2 and ordered[0].number != left_number:
        ordered.reverse()
    return (
        SymbolPin(number=ordered[0].number, name=ordered[0].name, at=_p(0.0, _AXIS), side="left"),
        SymbolPin(
            number=ordered[1].number, name=ordered[1].name, at=_p(_TWO_W, _AXIS), side="right"
        ),
    )


def _leads(x_left_end: Mm, x_right_start: Mm) -> tuple[SymbolShape, ...]:
    return (
        SymbolShape(kind="polyline", points=(_p(0.0, _AXIS), _p(x_left_end, _AXIS))),
        SymbolShape(kind="polyline", points=(_p(x_right_start, _AXIS), _p(_TWO_W, _AXIS))),
    )


def _resistor_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """The IEC rectangle rather than the zig-zag.

    Both are correct and the rectangle stays legible at the size a whole sheet is looked
    at, which is the size this one is looked at.
    """
    half = 0.75 * GRID_MM
    box = SymbolShape(
        kind="polygon",
        points=(
            _p(2 * GRID_MM, _AXIS - half),
            _p(6 * GRID_MM, _AXIS - half),
            _p(6 * GRID_MM, _AXIS + half),
            _p(2 * GRID_MM, _AXIS + half),
        ),
    )
    return SymbolBody(
        shapes=(*_leads(2 * GRID_MM, 6 * GRID_MM), box),
        pins=_two_terminal_pins(pins, None),
        width=_TWO_W,
        height=_TWO_H,
    )


def _capacitor_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    half = 1.3 * GRID_MM
    left_x, right_x = 3.6 * GRID_MM, 4.4 * GRID_MM
    plates = (
        SymbolShape(kind="polyline", points=(_p(left_x, _AXIS - half), _p(left_x, _AXIS + half))),
        SymbolShape(kind="polyline", points=(_p(right_x, _AXIS - half), _p(right_x, _AXIS + half))),
    )
    return SymbolBody(
        shapes=(*_leads(left_x, right_x), *plates),
        pins=_two_terminal_pins(pins, None),
        width=_TWO_W,
        height=_TWO_H,
    )


def _polarised_capacitor_body(
    pins: tuple[PinSpec, ...], footprint: Footprint | None
) -> SymbolBody:
    """Straight plate positive, curved plate negative, and a plus over the positive lead.

    The plus is the mark actually printed on the can, so the sheet and the part in the hand
    agree about which end is which.
    """
    half = 1.3 * GRID_MM
    straight_x, curve_x = 3.5 * GRID_MM, 4.6 * GRID_MM
    positive = _positive_pin_number(pins, footprint.polarized if footprint else True)
    curve_points: list[Point2] = []
    steps = 8
    for index in range(steps + 1):
        t = -1.0 + 2.0 * index / steps
        curve_points.append(_p(curve_x + 0.5 * GRID_MM * (1.0 - t * t), _AXIS + t * half))
    plus_x, plus_y = 2.4 * GRID_MM, _AXIS - 1.9 * GRID_MM
    arm = 0.35 * GRID_MM
    shapes = (
        *_leads(straight_x, curve_x),
        SymbolShape(
            kind="polyline", points=(_p(straight_x, _AXIS - half), _p(straight_x, _AXIS + half))
        ),
        SymbolShape(kind="polyline", points=tuple(curve_points)),
        SymbolShape(kind="polyline", points=(_p(plus_x - arm, plus_y), _p(plus_x + arm, plus_y))),
        SymbolShape(kind="polyline", points=(_p(plus_x, plus_y - arm), _p(plus_x, plus_y + arm))),
    )
    return SymbolBody(
        shapes=shapes, pins=_two_terminal_pins(pins, positive), width=_TWO_W, height=_TWO_H
    )


def _diode_shapes(*, cathode_left: bool) -> tuple[SymbolShape, ...]:
    half = 1.3 * GRID_MM
    near, far = 3.6 * GRID_MM, 5.2 * GRID_MM
    bar_x = near if cathode_left else far
    tip_x = near if cathode_left else far
    base_x = far if cathode_left else near
    return (
        *_leads(near, far),
        SymbolShape(kind="polyline", points=(_p(bar_x, _AXIS - half), _p(bar_x, _AXIS + half))),
        SymbolShape(
            kind="polygon",
            points=(_p(base_x, _AXIS - half), _p(base_x, _AXIS + half), _p(tip_x, _AXIS)),
        ),
    )


def _diode_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    cathode = _cathode_pin_number(pins, footprint.polarized if footprint else True)
    return SymbolBody(
        shapes=_diode_shapes(cathode_left=True),
        pins=_two_terminal_pins(pins, cathode),
        width=_TWO_W,
        height=_TWO_H,
    )


def _led_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """A diode with two arrows leaving it.

    The arrows are the whole difference between "this is a diode" and "this is the part
    that lights up", so they are drawn rather than implied by a colour.
    """
    cathode = _cathode_pin_number(pins, footprint.polarized if footprint else True)
    arrows: list[SymbolShape] = []
    # Kept inside the symbol's own box on purpose: the reference designator is drawn just
    # above that box, and an arrowhead poking out of it lands underneath the text.
    for offset in (0.0, 0.9 * GRID_MM):
        start = _p(4.0 * GRID_MM + offset, _AXIS - 1.1 * GRID_MM)
        end = _p(start.x + 0.6 * GRID_MM, start.y - 0.6 * GRID_MM)
        head = 0.3 * GRID_MM
        arrows.append(SymbolShape(kind="polyline", points=(start, end)))
        arrows.append(
            SymbolShape(
                kind="polygon",
                points=(
                    end,
                    _p(end.x - head * 2, end.y + head * 0.6),
                    _p(end.x - head * 0.6, end.y + head * 2),
                ),
                filled=True,
            )
        )
    return SymbolBody(
        shapes=(*_diode_shapes(cathode_left=True), *arrows),
        pins=_two_terminal_pins(pins, cathode),
        width=_TWO_W,
        height=_TWO_H,
    )


def _crystal_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    half = 1.3 * GRID_MM
    left_x, right_x = 3.2 * GRID_MM, 5.6 * GRID_MM
    slab = 0.9 * GRID_MM
    shapes = (
        *_leads(left_x, right_x),
        SymbolShape(kind="polyline", points=(_p(left_x, _AXIS - half), _p(left_x, _AXIS + half))),
        SymbolShape(kind="polyline", points=(_p(right_x, _AXIS - half), _p(right_x, _AXIS + half))),
        SymbolShape(
            kind="polygon",
            points=(
                _p(3.8 * GRID_MM, _AXIS - slab),
                _p(5.0 * GRID_MM, _AXIS - slab),
                _p(5.0 * GRID_MM, _AXIS + slab),
                _p(3.8 * GRID_MM, _AXIS + slab),
            ),
        ),
    )
    return SymbolBody(
        shapes=shapes, pins=_two_terminal_pins(pins, None), width=_TWO_W, height=_TWO_H
    )


def _potentiometer_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """A resistor with an arrow into it, pin 2 the wiper.

    THE ONE ASSUMPTION IN THIS FILE THE REGISTRY DOES NOT BACK. ``pot-3`` carries no pin
    names, and on a three-lead inline potentiometer the middle lead is the wiper --
    universally, on every part this tool models. It is written down here rather than left
    to be discovered, because it is the same shape of claim the module refuses to make
    about a TO-92 base; the difference is that this one has no counterexample.
    """
    height = 6 * GRID_MM
    axis = 4 * GRID_MM
    half = 0.75 * GRID_MM
    wiper_y = 1 * GRID_MM
    wiper_x = 4 * GRID_MM
    head = 0.45 * GRID_MM
    shapes = (
        SymbolShape(kind="polyline", points=(_p(0.0, axis), _p(2 * GRID_MM, axis))),
        SymbolShape(kind="polyline", points=(_p(6 * GRID_MM, axis), _p(_TWO_W, axis))),
        SymbolShape(
            kind="polygon",
            points=(
                _p(2 * GRID_MM, axis - half),
                _p(6 * GRID_MM, axis - half),
                _p(6 * GRID_MM, axis + half),
                _p(2 * GRID_MM, axis + half),
            ),
        ),
        SymbolShape(
            kind="polyline",
            points=(
                _p(_TWO_W, wiper_y),
                _p(wiper_x, wiper_y),
                _p(wiper_x, axis - half - head * 2),
            ),
        ),
        SymbolShape(
            kind="polygon",
            points=(
                _p(wiper_x - head, axis - half - head * 2),
                _p(wiper_x + head, axis - half - head * 2),
                _p(wiper_x, axis - half),
            ),
            filled=True,
        ),
    )
    by_number = {pin.number: pin for pin in pins}
    ends = [pin for pin in pins if pin.number != "2"]
    wiper = by_number.get("2", pins[-1])
    if len(ends) < 2:  # pragma: no cover - a 3-pin footprint always has two non-wiper pins
        ends = list(pins)
    drawn = (
        SymbolPin(number=ends[0].number, name=ends[0].name, at=_p(0.0, axis), side="left"),
        SymbolPin(number=wiper.number, name=wiper.name, at=_p(_TWO_W, wiper_y), side="right"),
        SymbolPin(number=ends[-1].number, name=ends[-1].name, at=_p(_TWO_W, axis), side="right"),
    )
    return SymbolBody(shapes=shapes, pins=drawn, width=_TWO_W, height=height)


def _switch_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """A momentary pushbutton: two terminals, a gap, and a plunger over it.

    Each terminal carries BOTH of its legs, joined by a bar, because they are one node
    inside the part -- see ``_switch_poles``. Drawing them as four separate leads would
    make somebody wire across a pair that is already shorted and wonder why the switch does
    nothing.
    """
    poles = _switch_poles(footprint)
    by_number = {pin.number: pin for pin in pins}
    assert poles is not None, "symbol_kind_for only asks for a switch it can read"
    height = 5 * GRID_MM
    axis = 2.5 * GRID_MM
    rows = (1.5 * GRID_MM, 3.5 * GRID_MM)
    # The two legs of a pole MEET at a point rather than being bridged by a bar. A bar plus
    # two leads draws three sides of a rectangle, which is the box this symbol exists to
    # stop being -- and a join is what "these are one node" looks like everywhere else on a
    # schematic.
    lead_ends = (1.0 * GRID_MM, 7.0 * GRID_MM)
    joins = (2.0 * GRID_MM, 6.0 * GRID_MM)
    gaps = (3.0 * GRID_MM, 5.0 * GRID_MM)
    plunger_y = axis - 1.2 * GRID_MM

    shapes: list[SymbolShape] = []
    drawn: list[SymbolPin] = []
    for side_index, numbers in enumerate(poles):
        edge_x = 0.0 if side_index == 0 else _TWO_W
        lead_end, join_x, gap_x = lead_ends[side_index], joins[side_index], gaps[side_index]
        for row_index, number in enumerate(numbers):
            y = rows[row_index]
            shapes.append(
                SymbolShape(
                    kind="polyline",
                    points=(_p(edge_x, y), _p(lead_end, y), _p(join_x, axis)),
                )
            )
            spec = by_number.get(number)
            drawn.append(
                SymbolPin(
                    number=number,
                    name=spec.name if spec is not None else None,
                    at=_p(edge_x, y),
                    side="left" if side_index == 0 else "right",
                )
            )
        shapes.append(SymbolShape(kind="polyline", points=(_p(join_x, axis), _p(gap_x, axis))))
        shapes.append(
            SymbolShape(kind="circle", points=(_p(gap_x, axis),), radius=0.3 * GRID_MM)
        )
    shapes.append(
        SymbolShape(
            kind="polyline",
            points=(_p(2.6 * GRID_MM, plunger_y), _p(5.4 * GRID_MM, plunger_y)),
        )
    )
    shapes.append(
        SymbolShape(
            kind="polyline",
            points=(_p(4 * GRID_MM, plunger_y), _p(4 * GRID_MM, plunger_y - 0.8 * GRID_MM)),
        )
    )
    return SymbolBody(
        shapes=tuple(shapes), pins=tuple(drawn), width=_TWO_W, height=height
    )


def _relay_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """A coil, a mechanical link, and a contact block with its leads numbered.

    The link is drawn as separate short strokes rather than one line, because a line
    between a coil and a contact set is what a WIRE looks like, and this is the one part of
    a relay symbol that must not read as copper. ``SymbolShape`` has no dash style and
    should not grow one for this: three segments are three segments in every renderer.

    The contact block stays a block for the reason ``_relay_sides`` gives -- naming the
    common pin is the claim that would put somebody's motor on the wrong throw.
    """
    sides = _relay_sides(footprint)
    assert sides is not None, "symbol_kind_for only asks for a relay it can read"
    coil_numbers, contact_numbers = sides
    by_number = {pin.number: pin for pin in pins}

    rows = max(len(contact_numbers), 2)
    height = (rows + 1) * PIN_PITCH_MM
    width = 12.5 * GRID_MM
    coil_left, coil_right = 2 * GRID_MM, 4.5 * GRID_MM
    block_left, block_right = 7 * GRID_MM, 10.5 * GRID_MM
    top, bottom = PIN_PITCH_MM / 2, height - PIN_PITCH_MM / 2

    coil_ys = (PIN_PITCH_MM, rows * PIN_PITCH_MM)
    shapes: list[SymbolShape] = [
        SymbolShape(
            kind="polygon",
            points=(
                _p(coil_left, coil_ys[0]),
                _p(coil_right, coil_ys[0]),
                _p(coil_right, coil_ys[1]),
                _p(coil_left, coil_ys[1]),
            ),
        ),
        SymbolShape(
            kind="polygon",
            points=(
                _p(block_left, top),
                _p(block_right, top),
                _p(block_right, bottom),
                _p(block_left, bottom),
            ),
        ),
    ]
    drawn: list[SymbolPin] = []
    for index, number in enumerate(coil_numbers):
        y = coil_ys[index]
        shapes.append(SymbolShape(kind="polyline", points=(_p(0.0, y), _p(coil_left, y))))
        spec = by_number.get(number)
        drawn.append(
            SymbolPin(
                number=number,
                name=spec.name if spec is not None else None,
                at=_p(0.0, y),
                side="left",
            )
        )
    for index, number in enumerate(contact_numbers):
        y = (index + 1) * PIN_PITCH_MM
        shapes.append(SymbolShape(kind="polyline", points=(_p(block_right, y), _p(width, y))))
        spec = by_number.get(number)
        drawn.append(
            SymbolPin(
                number=number,
                name=spec.name if spec is not None else None,
                at=_p(width, y),
                side="right",
            )
        )

    link_y = height / 2
    stroke = 0.35 * GRID_MM
    x = coil_right + 0.4 * GRID_MM
    while x + stroke <= block_left:
        shapes.append(SymbolShape(kind="polyline", points=(_p(x, link_y), _p(x + stroke, link_y))))
        x += stroke * 2

    return SymbolBody(
        shapes=tuple(shapes), pins=tuple(drawn), width=width, height=height
    )


# -- everything else is a box, and the box says what it knows -----------------


def _boxy_body(
    pins: tuple[PinSpec, ...],
    *,
    body_width: Mm,
    split: bool,
    dip_order: bool,
    notch: bool,
    name_inset: Mm | None = None,
) -> SymbolBody:
    """A rectangle with numbered pins down one or both sides.

    ``dip_order`` is the DIP numbering and not a style: pins 1..n/2 run down the left and
    the rest run UP the right, which is how the package is numbered and therefore the only
    ordering that lets someone read a pin off this sheet and find it on the part.
    """
    count = len(pins)
    if split:
        per_side = (count + 1) // 2
        left = list(pins[:per_side])
        right = list(pins[per_side:])
        if dip_order:
            right.reverse()
    else:
        left, right = list(pins), []

    rows = max(len(left), len(right), 1)
    height = (rows + 1) * PIN_PITCH_MM
    # A part that NAMES its pins gets a body wide enough to print the names inside it --
    # "GPIO21" does not fit where "21" did. Only then: a box whose pins carry no names is
    # exactly the width it always was, which is what keeps every frozen sheet unchanged.
    body_width = max(
        body_width,
        _named_body_width(
            left, right, _PIN_NAME_INSET_MM if name_inset is None else name_inset
        ),
    )
    width = LEAD_MM + body_width + (LEAD_MM if right else 0.0)
    body_left = LEAD_MM
    body_right = LEAD_MM + body_width
    top = PIN_PITCH_MM / 2
    bottom = height - PIN_PITCH_MM / 2

    shapes: list[SymbolShape] = [
        SymbolShape(
            kind="polygon",
            points=(
                _p(body_left, top),
                _p(body_right, top),
                _p(body_right, bottom),
                _p(body_left, bottom),
            ),
        )
    ]
    drawn: list[SymbolPin] = []
    for index, pin in enumerate(left):
        y = (index + 1) * PIN_PITCH_MM
        shapes.append(SymbolShape(kind="polyline", points=(_p(0.0, y), _p(body_left, y))))
        drawn.append(SymbolPin(number=pin.number, name=pin.name, at=_p(0.0, y), side="left"))
    for index, pin in enumerate(right):
        y = (index + 1) * PIN_PITCH_MM
        shapes.append(SymbolShape(kind="polyline", points=(_p(body_right, y), _p(width, y))))
        drawn.append(SymbolPin(number=pin.number, name=pin.name, at=_p(width, y), side="right"))
    if notch:
        # The pin-1 mark, in the place the package carries it.
        shapes.append(
            SymbolShape(
                kind="circle",
                points=(_p((body_left + body_right) / 2, top),),
                radius=0.5 * GRID_MM,
            )
        )
    return SymbolBody(
        shapes=tuple(shapes), pins=tuple(drawn), width=width, height=height
    )


#: How far a pin's name sits inside the body edge, and the least gap between a name on the
#: left and one on the right. The first is where ``_part_labels`` has always put a pin
#: number; the second is one grid square, because two names nearer than that read as one.
_PIN_NAME_INSET_MM: Mm = 0.5 * GRID_MM
_PIN_NAME_GAP_MM: Mm = GRID_MM

#: Where a CONNECTOR prints a pin's name: past the shroud line ``_connector_body`` draws
#: 1.4 grid squares into the body. A number fits in front of that line and always has; a
#: name starting in the same place runs straight through it, and "24V-L" reads as "24V-"
#: with a bar through the L.
_CONNECTOR_SHROUD_MM: Mm = 1.4 * GRID_MM
_CONNECTOR_NAME_INSET_MM: Mm = _CONNECTOR_SHROUD_MM + 0.4 * GRID_MM


def pin_label_width(text: str) -> Mm:
    """Roughly how wide a pin label is on paper, by the same average-advance estimate the
    net labels use. Close is enough: the answer is rounded up to whole grid squares."""
    return len(text) * PIN_LABEL_MM * NET_LABEL_ADVANCE


def _named_body_width(
    left: Sequence[PinSpec], right: Sequence[PinSpec], inset: Mm = _PIN_NAME_INSET_MM
) -> Mm:
    """The body width the longest names on each side need, or 0 when nothing is named.

    ``inset`` is where a name starts from the edge it belongs to; the far end keeps the
    ordinary inset, since nothing is drawn there but the body outline.
    """
    left_width = max((pin_label_width(pin.name) for pin in left if pin.name), default=0.0)
    right_width = max((pin_label_width(pin.name) for pin in right if pin.name), default=0.0)
    if not left_width and not right_width:
        return 0.0
    gap = _PIN_NAME_GAP_MM if left_width and right_width else 0.0
    needed = inset + _PIN_NAME_INSET_MM + left_width + gap + right_width
    return math.ceil(needed / GRID_MM - 1e-9) * GRID_MM


def _ic_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    if _has_functional_roles(pins):
        return functional_ic_body(pins)
    return _boxy_body(pins, body_width=8 * GRID_MM, split=True, dip_order=True, notch=True)


def _connector_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """Pins down one side however many there are.

    A header is a place wires leave the board, and splitting one across two sides of a box
    would draw the eight-way strip in your hand as two four-ways.
    """
    body = _boxy_body(
        pins,
        body_width=6 * GRID_MM,
        split=False,
        dip_order=False,
        notch=False,
        name_inset=_CONNECTOR_NAME_INSET_MM,
    )
    shroud = SymbolShape(
        kind="polyline",
        points=(
            _p(LEAD_MM + _CONNECTOR_SHROUD_MM, PIN_PITCH_MM / 2),
            _p(LEAD_MM + _CONNECTOR_SHROUD_MM, body.height - PIN_PITCH_MM / 2),
        ),
    )
    return SymbolBody(
        shapes=(*body.shapes, shroud), pins=body.pins, width=body.width, height=body.height
    )


def _box_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """The honest fallback: a TO-92, a TO-220, a part nothing in the document defines.

    Five pins or fewer go down one side, because a three-lead part with one pin on the left
    and two on the right invites the reader to see a transistor -- which is precisely the
    reading this box exists to avoid. A module or generic part that declares roles for every
    lead draws as a functional box instead.
    """
    if _has_functional_roles(pins):
        return functional_ic_body(pins)
    split = len(pins) > 5
    return _boxy_body(pins, body_width=6 * GRID_MM, split=split, dip_order=False, notch=False)


# -- what a part declares itself to be ----------------------------------------
#
# Every symbol below exists only because a PART said what it is (``model.PartSymbol``).
# The registry never asks for one: a DO-35 is a zener or a signal diode, a disc is a
# ceramic capacitor or a PTC fuse, and a three-legged package is anything at all. The
# person who chose the part knows, and for the transistors they also have to say which leg
# is which -- see ``DECLARED_SYMBOL_PINS``.

#: The pin NAMES a declared symbol needs before it can be drawn. A transistor symbol is a
#: claim about which leg is the base or the gate; drawing one from the declaration alone
#: would be making the claim the registry refuses to make, on the part's behalf and
#: without its datasheet. So a declared MOSFET whose leads are not named G, D and S stays a
#: box, and the sheet's notes say which names are missing.
DECLARED_SYMBOL_PINS: dict[PartSymbol, frozenset[str]] = {
    "npn": frozenset({"B", "C", "E"}),
    "pnp": frozenset({"B", "C", "E"}),
    "nmos": frozenset({"G", "D", "S"}),
    "pmos": frozenset({"G", "D", "S"}),
    "zener": frozenset(),
    "fuse": frozenset(),
    # Three lugs, the middle one the wiper, as ``_potentiometer_body`` already assumes of
    # every pot -- the declaration only says it IS one.
    "potentiometer": frozenset(),
    # Which leg is the anode is the one thing an LED symbol says, so it has to be named.
    "led": frozenset({"A", "K"}),
    # Which lead the long plate is on is what a cell symbol says, so the leads must be named.
    "battery": frozenset({"+", "-"}),
    # The centre pin is the plus and the sleeve the minus, so the leads must say which.
    "jack": frozenset({"+", "-"}),
    # The lead named + is the one the symbol marks, so the leads must say which.
    "buzzer": frozenset({"+", "-"}),
}

#: Declared symbols whose leads are found by NAME in a way a set of exact names cannot say:
#: a relay has COIL twice, a regulator's third lead is GND or ADJ or anything. Each rule gives
#: the reason a part cannot be drawn as that kind, or ``None`` when it can. A kind is in this
#: table or in ``DECLARED_SYMBOL_PINS``, never both, so no declaration is checked twice
#: (``test_part_pinout`` holds the two to that).
DECLARED_SYMBOL_RULES: dict[PartSymbol, Callable[[tuple[PinSpec, ...]], str | None]] = {}


def _rule(symbol: PartSymbol) -> Callable[
    [Callable[[tuple[PinSpec, ...]], str | None]], Callable[[tuple[PinSpec, ...]], str | None]
]:
    def register(
        check: Callable[[tuple[PinSpec, ...]], str | None],
    ) -> Callable[[tuple[PinSpec, ...]], str | None]:
        DECLARED_SYMBOL_RULES[symbol] = check
        return check

    return register


@_rule("regulator")
def _regulator_rule(pins: tuple[PinSpec, ...]) -> str | None:
    inp = _first_called(pins, *_REGULATOR_IN)
    out = _first_called(pins, *_REGULATOR_OUT)
    if len(pins) != 3 or inp is None or out is None or inp is out:
        return (
            "declared regulator, but a regulator symbol needs three pins, one named IN (or VIN) "
            "and one named OUT (or VOUT)"
        )
    return None


@_rule("relay")
def _relay_rule(pins: tuple[PinSpec, ...]) -> str | None:
    parsed = _relay_poles(pins)
    if isinstance(parsed, str):
        return f"declared relay, but a relay symbol {parsed}"
    return None


@_rule("switch")
def _switch_rule(pins: tuple[PinSpec, ...]) -> str | None:
    if len(pins) == 2:
        return None
    if len(pins) == 3 and _first_called(pins, "COM", "C") is not None:
        return None
    return "declared switch, but a switch has two leads, or three with the common one named COM"


@_rule("button")
def _button_rule(pins: tuple[PinSpec, ...]) -> str | None:
    return None if len(pins) == 2 else "declared button, but a button has two leads"


@_rule("inductor")
def _inductor_rule(pins: tuple[PinSpec, ...]) -> str | None:
    return None if len(pins) == 2 else "declared inductor, but an inductor has two leads"


@_rule("motor")
def _motor_rule(pins: tuple[PinSpec, ...]) -> str | None:
    return None if len(pins) == 2 else "declared motor, but a motor has two leads"


@_rule("optocoupler")
def _optocoupler_rule(pins: tuple[PinSpec, ...]) -> str | None:
    leads = {"A", "K", "C", "E"}
    names = {(p.name or "").upper() for p in pins}
    if not leads <= names or not names <= leads | {"B", "NC"} or len(names) != len(pins):
        return (
            "declared optocoupler, but an optocoupler symbol needs pins named A, K, C and E "
            "(and B or NC, if the part has them)"
        )
    return None


#: How many leads a declared symbol with no names to check must have.
_DECLARED_LEADS: dict[PartSymbol, int] = {"potentiometer": 3}


_LEAD_COUNT_WORDS: dict[int, str] = {2: "two", 3: "three"}


def declared_symbol_kind(
    symbol: PartSymbol, pins: tuple[PinSpec, ...], footprint: Footprint | None
) -> tuple[SymbolKind | None, str | None]:
    """The kind a declaration draws as, or ``(None, why not)``.

    The reason is phrased for the sheet's notes, after the reference -- "Q1: ..." -- because
    that is where somebody looks to find out why the MOSFET they declared is still a box.
    The caller finishes the sentence with what it drew instead, which is not always a box:
    a declared zener on an unpolarised axial falls back to the resistor it looks like.
    """
    rule = DECLARED_SYMBOL_RULES.get(symbol)
    if rule is not None:
        why_not = rule(pins)
        return (symbol, None) if why_not is None else (None, why_not)
    needed = DECLARED_SYMBOL_PINS[symbol]
    if needed:
        names = [pin.name for pin in pins]
        if len(pins) != len(needed) or set(names) != needed:
            wanted = ", ".join(sorted(needed))
            return None, (
                f"declared {symbol}, but a {symbol} symbol needs exactly {len(needed)} pins "
                f"named {wanted}"
            )
        return symbol, None
    leads = _DECLARED_LEADS.get(symbol, 2)
    if len(pins) != leads:
        return None, f"declared {symbol}, but a {symbol} has {_LEAD_COUNT_WORDS[leads]} leads"
    if symbol == "zener":
        polarised = footprint.polarized if footprint is not None else False
        if _cathode_pin_number(pins, polarised) is None:
            return None, (
                "declared zener, but nothing says which lead is the cathode "
                "(name the leads K and A)"
            )
    return symbol, None


def _zener_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """A diode whose bar is bent at both ends, cathode on the left like every diode here.

    The bends are the whole difference from a signal diode, and a signal diode where the
    circuit needs a zener is a gate driven to the full rail -- so they are drawn as two
    unmistakable strokes rather than a serif.
    """
    cathode = _cathode_pin_number(pins, footprint.polarized if footprint else False)
    half = 1.3 * GRID_MM
    near = 3.6 * GRID_MM
    wing_x, wing_y = 0.45 * GRID_MM, 0.35 * GRID_MM
    shapes = list(_diode_shapes(cathode_left=True))
    # The plain bar is the third shape _diode_shapes returns; replaced, not overdrawn.
    shapes[2] = SymbolShape(
        kind="polyline",
        points=(
            _p(near - wing_x, _AXIS - half - wing_y),
            _p(near, _AXIS - half),
            _p(near, _AXIS + half),
            _p(near + wing_x, _AXIS + half + wing_y),
        ),
    )
    return SymbolBody(
        shapes=tuple(shapes),
        pins=_two_terminal_pins(pins, cathode),
        width=_TWO_W,
        height=_TWO_H,
    )


def _fuse_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """The IEC fuse: the resistor's rectangle with the conductor running straight through.

    The line through the body is what says "this opens", and it is also the only thing
    telling it apart from the resistor it would otherwise be.
    """
    half = 0.75 * GRID_MM
    shapes = (
        SymbolShape(kind="polyline", points=(_p(0.0, _AXIS), _p(_TWO_W, _AXIS))),
        SymbolShape(
            kind="polygon",
            points=(
                _p(2 * GRID_MM, _AXIS - half),
                _p(6 * GRID_MM, _AXIS - half),
                _p(6 * GRID_MM, _AXIS + half),
                _p(2 * GRID_MM, _AXIS + half),
            ),
        ),
    )
    return SymbolBody(
        shapes=shapes, pins=_two_terminal_pins(pins, None), width=_TWO_W, height=_TWO_H
    )


def _battery_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """Two cells in a row: long plate positive, short plate negative, and a mark over each lead.

    The long plate is what says "this end is the plus", and the mark is what is moulded on a
    real cell, so the sheet and the clip in the hand agree about which lead is which. A
    battery here has its plus on the left whichever pin that is, as an electrolytic does.
    """
    positive = _positive_pin_number(pins, True)
    long_half, short_half = 1.3 * GRID_MM, 0.7 * GRID_MM
    plate = 0.22 * GRID_MM
    long_xs = (3.0 * GRID_MM, 4.6 * GRID_MM)
    short_xs = (3.8 * GRID_MM, 5.4 * GRID_MM)
    shapes: list[SymbolShape] = [
        SymbolShape(kind="polyline", points=(_p(0.0, _AXIS), _p(long_xs[0], _AXIS))),
        SymbolShape(kind="polyline", points=(_p(short_xs[0], _AXIS), _p(long_xs[1], _AXIS))),
        SymbolShape(kind="polyline", points=(_p(short_xs[1], _AXIS), _p(_TWO_W, _AXIS))),
    ]
    for x in long_xs:
        shapes.append(
            SymbolShape(kind="polyline", points=(_p(x, _AXIS - long_half), _p(x, _AXIS + long_half)))
        )
    for x in short_xs:
        shapes.append(
            SymbolShape(
                kind="polygon",
                points=(
                    _p(x - plate / 2, _AXIS - short_half),
                    _p(x + plate / 2, _AXIS - short_half),
                    _p(x + plate / 2, _AXIS + short_half),
                    _p(x - plate / 2, _AXIS + short_half),
                ),
                filled=True,
            )
        )
    arm = 0.35 * GRID_MM
    mark_y = _AXIS - 1.9 * GRID_MM
    plus_x, minus_x = 1.8 * GRID_MM, 6.6 * GRID_MM
    shapes.append(
        SymbolShape(kind="polyline", points=(_p(plus_x - arm, mark_y), _p(plus_x + arm, mark_y)))
    )
    shapes.append(
        SymbolShape(kind="polyline", points=(_p(plus_x, mark_y - arm), _p(plus_x, mark_y + arm)))
    )
    shapes.append(
        SymbolShape(kind="polyline", points=(_p(minus_x - arm, mark_y), _p(minus_x + arm, mark_y)))
    )
    return SymbolBody(
        shapes=tuple(shapes),
        pins=_two_terminal_pins(pins, positive),
        width=_TWO_W,
        height=_TWO_H,
    )


def _jack_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """A DC barrel jack in section: the centre pin reaching into the cup of the sleeve.

    Drawn here from what the part is, not copied from a symbol library: a housing, the pin
    as a filled bar entering from the left, and the sleeve as a half-round cup it sits in,
    with the plus on the pin side and the minus on the sleeve side. The marks over the
    leads say so on the sheet, because which way a jack is wired is the board's business
    and a reader should not have to find it in a table.
    """
    positive = _positive_pin_number(pins, True)
    half = 1.5 * GRID_MM
    pin_half = 0.18 * GRID_MM
    centre_x, radius = 4.6 * GRID_MM, 1.0 * GRID_MM
    cup: list[Point2] = []
    steps = 8
    for index in range(steps + 1):
        angle = -math.pi / 2 + math.pi * index / steps
        cup.append(_p(centre_x + radius * math.cos(angle), _AXIS + radius * math.sin(angle)))
    arm = 0.35 * GRID_MM
    mark_y = _AXIS - 0.9 * GRID_MM
    plus_x, minus_x = 0.9 * GRID_MM, 7.1 * GRID_MM
    shapes = (
        SymbolShape(kind="polyline", points=(_p(0.0, _AXIS), _p(2 * GRID_MM, _AXIS))),
        SymbolShape(
            kind="polygon",
            points=(
                _p(2 * GRID_MM, _AXIS - half),
                _p(6 * GRID_MM, _AXIS - half),
                _p(6 * GRID_MM, _AXIS + half),
                _p(2 * GRID_MM, _AXIS + half),
            ),
        ),
        SymbolShape(
            kind="polygon",
            points=(
                _p(2 * GRID_MM, _AXIS - pin_half),
                _p(4.4 * GRID_MM, _AXIS - pin_half),
                _p(4.4 * GRID_MM, _AXIS + pin_half),
                _p(2 * GRID_MM, _AXIS + pin_half),
            ),
            filled=True,
        ),
        SymbolShape(kind="polyline", points=tuple(cup)),
        SymbolShape(
            kind="polyline", points=(_p(centre_x + radius, _AXIS), _p(_TWO_W, _AXIS))
        ),
        SymbolShape(
            kind="polyline", points=(_p(plus_x - arm, mark_y), _p(plus_x + arm, mark_y))
        ),
        SymbolShape(
            kind="polyline", points=(_p(plus_x, mark_y - arm), _p(plus_x, mark_y + arm))
        ),
        SymbolShape(
            kind="polyline", points=(_p(minus_x - arm, mark_y), _p(minus_x + arm, mark_y))
        ),
    )
    return SymbolBody(
        shapes=shapes, pins=_two_terminal_pins(pins, positive), width=_TWO_W, height=_TWO_H
    )


# The transistors share one frame: the control lead on the left at mid-height, the two
# power leads on the right one above the other, the envelope circle between. Leads only on
# the left and right because that is how every symbol here leaves its body -- a wire goes
# out sideways into the channel beside its column -- and the potentiometer already puts
# one lead on the left and two on the right in the same way.
_TRANSISTOR_H: Mm = 6 * GRID_MM
_TRANSISTOR_AXIS: Mm = 3 * GRID_MM
_TRANSISTOR_TOP: Mm = 1 * GRID_MM
_TRANSISTOR_BOTTOM: Mm = 5 * GRID_MM


def _arrowhead(tip: Point2, towards_x: float, towards_y: float) -> SymbolShape:
    """A filled arrowhead at ``tip``, pointing along (``towards_x``, ``towards_y``)."""
    length = math.hypot(towards_x, towards_y)
    ux, uy = towards_x / length, towards_y / length
    back, spread = 0.55 * GRID_MM, 0.28 * GRID_MM
    base_x, base_y = tip.x - ux * back, tip.y - uy * back
    return SymbolShape(
        kind="polygon",
        points=(
            tip,
            _p(base_x - uy * spread, base_y + ux * spread),
            _p(base_x + uy * spread, base_y - ux * spread),
        ),
        filled=True,
    )


def _envelope() -> SymbolShape:
    return SymbolShape(
        kind="circle", points=(_p(4.5 * GRID_MM, _TRANSISTOR_AXIS),), radius=1.9 * GRID_MM
    )


def _named(pins: tuple[PinSpec, ...], name: str) -> PinSpec:
    """The lead with this name. ``declared_symbol_kind`` has already checked it exists."""
    return next(pin for pin in pins if pin.name == name)


def _transistor_pins(control: PinSpec, top: PinSpec, bottom: PinSpec) -> tuple[SymbolPin, ...]:
    return (
        SymbolPin(
            number=control.number, name=control.name, at=_p(0.0, _TRANSISTOR_AXIS), side="left"
        ),
        SymbolPin(number=top.number, name=top.name, at=_p(_TWO_W, _TRANSISTOR_TOP), side="right"),
        SymbolPin(
            number=bottom.number,
            name=bottom.name,
            at=_p(_TWO_W, _TRANSISTOR_BOTTOM),
            side="right",
        ),
    )


def _bjt_body(pins: tuple[PinSpec, ...], *, pnp: bool) -> SymbolBody:
    """Base on the left; the collector on top for an NPN and the emitter on top for a PNP.

    The conventional orientation for each -- conventional current runs DOWN the page
    through both -- and the arrow on the emitter is the only other difference: out of the
    transistor on an NPN, into it on a PNP.
    """
    bar_x, lead_x = 3.4 * GRID_MM, 5.4 * GRID_MM
    upper_y, lower_y = 2.5 * GRID_MM, 3.5 * GRID_MM
    upper_end, lower_end = 1.6 * GRID_MM, 4.4 * GRID_MM
    shapes: list[SymbolShape] = [
        _envelope(),
        SymbolShape(
            kind="polyline", points=(_p(0.0, _TRANSISTOR_AXIS), _p(bar_x, _TRANSISTOR_AXIS))
        ),
        SymbolShape(kind="polyline", points=(_p(bar_x, 1.9 * GRID_MM), _p(bar_x, 4.1 * GRID_MM))),
        SymbolShape(
            kind="polyline",
            points=(
                _p(bar_x, upper_y),
                _p(lead_x, upper_end),
                _p(lead_x, _TRANSISTOR_TOP),
                _p(_TWO_W, _TRANSISTOR_TOP),
            ),
        ),
        SymbolShape(
            kind="polyline",
            points=(
                _p(bar_x, lower_y),
                _p(lead_x, lower_end),
                _p(lead_x, _TRANSISTOR_BOTTOM),
                _p(_TWO_W, _TRANSISTOR_BOTTOM),
            ),
        ),
    ]
    if pnp:
        # Emitter on top, the arrow pointing IN, towards the base bar.
        dx, dy = bar_x - lead_x, upper_y - upper_end
        shapes.append(_arrowhead(_p(lead_x + dx * 0.6, upper_end + dy * 0.6), dx, dy))
        top, bottom = _named(pins, "E"), _named(pins, "C")
    else:
        # Emitter at the bottom, the arrow pointing OUT, away from the base bar.
        dx, dy = lead_x - bar_x, lower_end - lower_y
        shapes.append(_arrowhead(_p(bar_x + dx * 0.8, lower_y + dy * 0.8), dx, dy))
        top, bottom = _named(pins, "C"), _named(pins, "E")
    return SymbolBody(
        shapes=tuple(shapes),
        pins=_transistor_pins(_named(pins, "B"), top, bottom),
        width=_TWO_W,
        height=_TRANSISTOR_H,
    )


def _mosfet_body(pins: tuple[PinSpec, ...], *, p_channel: bool) -> SymbolBody:
    """An enhancement MOSFET: insulated gate, broken channel, body tied to the source.

    Drain on top for an N-channel and source on top for a P-channel -- the way each is
    drawn in the circuits it appears in, where a P-channel high-side switch has its source
    on the supply. The arrow on the body connection points INTO the channel on an
    N-channel and out of it on a P-channel.
    """
    gate_x, channel_x, lead_x = 3.0 * GRID_MM, 3.5 * GRID_MM, 5.4 * GRID_MM
    upper_y, lower_y = 1.9 * GRID_MM, 4.1 * GRID_MM
    source_y = upper_y if p_channel else lower_y
    shapes: list[SymbolShape] = [
        _envelope(),
        SymbolShape(
            kind="polyline", points=(_p(0.0, _TRANSISTOR_AXIS), _p(gate_x, _TRANSISTOR_AXIS))
        ),
        SymbolShape(kind="polyline", points=(_p(gate_x, 1.8 * GRID_MM), _p(gate_x, 4.2 * GRID_MM))),
    ]
    for low, high in ((1.5, 2.3), (2.6, 3.4), (3.7, 4.5)):
        shapes.append(
            SymbolShape(
                kind="polyline",
                points=(_p(channel_x, low * GRID_MM), _p(channel_x, high * GRID_MM)),
            )
        )
    shapes += [
        SymbolShape(
            kind="polyline",
            points=(
                _p(channel_x, upper_y),
                _p(lead_x, upper_y),
                _p(lead_x, _TRANSISTOR_TOP),
                _p(_TWO_W, _TRANSISTOR_TOP),
            ),
        ),
        SymbolShape(
            kind="polyline",
            points=(
                _p(channel_x, lower_y),
                _p(lead_x, lower_y),
                _p(lead_x, _TRANSISTOR_BOTTOM),
                _p(_TWO_W, _TRANSISTOR_BOTTOM),
            ),
        ),
        # The body connection: from the middle of the channel across to the source.
        SymbolShape(
            kind="polyline",
            points=(
                _p(channel_x, _TRANSISTOR_AXIS),
                _p(lead_x, _TRANSISTOR_AXIS),
                _p(lead_x, source_y),
            ),
        ),
    ]
    if p_channel:
        shapes.append(_arrowhead(_p(channel_x + 1.3 * GRID_MM, _TRANSISTOR_AXIS), 1.0, 0.0))
        top, bottom = _named(pins, "S"), _named(pins, "D")
    else:
        shapes.append(_arrowhead(_p(channel_x + 0.1 * GRID_MM, _TRANSISTOR_AXIS), -1.0, 0.0))
        top, bottom = _named(pins, "D"), _named(pins, "S")
    return SymbolBody(
        shapes=tuple(shapes),
        pins=_transistor_pins(_named(pins, "G"), top, bottom),
        width=_TWO_W,
        height=_TRANSISTOR_H,
    )


def _npn_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    return _bjt_body(pins, pnp=False)


def _pnp_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    return _bjt_body(pins, pnp=True)


def _nmos_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    return _mosfet_body(pins, p_channel=False)


def _pmos_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    return _mosfet_body(pins, p_channel=True)


# -- bodies that find their leads by NAME ---------------------------------------------------
#
# A regulator, a relay, a buzzer, an optocoupler: the package says nothing about which lead is
# which (a 7805 is IN GND OUT, an LM317 ADJ OUT IN and an LD1117 GND OUT IN in one TO-220), so
# every body below reads the NAME the part gives a lead and never its number. They are drawn
# in whole grid steps, which is why they are written in steps (``_g``) and not millimetres.


def _g(x: float, y: float) -> Point2:
    return Point2(x=x * GRID_MM, y=y * GRID_MM)


def _line(*coords: float) -> SymbolShape:
    """A polyline through (x0, y0, x1, y1, ...) in grid steps."""
    return SymbolShape(
        kind="polyline", points=tuple(_g(coords[i], coords[i + 1]) for i in range(0, len(coords), 2))
    )


def _poly(*coords: float, filled: bool = False) -> SymbolShape:
    return SymbolShape(
        kind="polygon",
        points=tuple(_g(coords[i], coords[i + 1]) for i in range(0, len(coords), 2)),
        filled=filled,
    )


def _ring(x: float, y: float, radius: float) -> SymbolShape:
    return SymbolShape(kind="circle", points=(_g(x, y),), radius=radius * GRID_MM)


def _rect(x0: float, y0: float, x1: float, y1: float) -> SymbolShape:
    return _poly(x0, y0, x1, y0, x1, y1, x0, y1)


def _arrowhead_at(tip: tuple[float, float], toward: tuple[float, float]) -> SymbolShape:
    """A filled head at ``tip`` (grid steps) pointing along ``toward``."""
    length = math.hypot(*toward)
    ux, uy = toward[0] / length, toward[1] / length
    bx, by = tip[0] - ux * 0.5, tip[1] - uy * 0.5
    return _poly(
        tip[0], tip[1], bx - uy * 0.25, by + ux * 0.25, bx + uy * 0.25, by - ux * 0.25, filled=True
    )


def _lead(spec: PinSpec, x: float, y: float, side: PinSide) -> SymbolPin:
    return SymbolPin(number=spec.number, name=spec.name, at=_g(x, y), side=side)


def _called(name: str | None, *words: str) -> bool:
    """Whether a pin's name is one of ``words``, any case."""
    return name is not None and name.upper() in words


def _first_called(pins: Sequence[PinSpec], *words: str) -> PinSpec | None:
    return next((p for p in pins if _called(p.name, *words)), None)


def _starts(name: str | None, prefix: str) -> bool:
    return name is not None and name.upper().startswith(prefix)


_REGULATOR_IN = ("IN", "VIN", "VI")
_REGULATOR_OUT = ("OUT", "VOUT", "VO")


def _regulator_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """Three terminals in a box: input left, output right, ground or adjust underneath.

    78xx reads IN, GND, OUT and the LM317 ADJ, OUT, IN; both draw the same -- the input and
    the output face their loads and the third lead goes where the return goes. Each lead is
    found by its NAME, never its number.
    """
    inp = _first_called(pins, *_REGULATOR_IN)
    out = _first_called(pins, *_REGULATOR_OUT)
    assert inp is not None and out is not None, "declared_symbol_kind only asks for a regulator it can read"
    ref = next(p for p in pins if p is not inp and p is not out)
    shapes = (_rect(2, 1, 8, 5), _line(0, 3, 2, 3), _line(8, 3, 10, 3), _line(5, 5, 5, 7))
    drawn = (_lead(inp, 0, 3, "left"), _lead(out, 10, 3, "right"), _lead(ref, 5, 7, "bottom"))
    return SymbolBody(shapes, drawn, 10 * GRID_MM, 7 * GRID_MM, names_inside=True)


def _relay_poles(
    pins: Sequence[PinSpec],
) -> tuple[list[PinSpec], list[tuple[PinSpec, PinSpec | None, PinSpec | None]]] | str:
    """The winding's two pins and each contact set as (COM, NO, NC), or why they cannot be read.

    A set starts at a COM and takes the NO and the NC named after it; a NO or NC named before
    any COM belongs to the first. Names only: Songle and Omron number the same outline
    differently, so a number says nothing about which contact is the common one.
    """
    coil = [p for p in pins if _starts(p.name, "COIL")]
    if len(coil) != 2:
        return "needs two pins named COIL"
    coms = [p for p in pins if _starts(p.name, "COM")]
    if not coms:
        return "needs a pin named COM"
    normally_open: dict[str, PinSpec] = {}
    normally_closed: dict[str, PinSpec] = {}
    current = coms[0]
    for p in pins:
        if p in coil:
            continue
        if _starts(p.name, "COM"):
            current = p
            continue
        if _starts(p.name, "NO"):
            held = normally_open
        elif _starts(p.name, "NC"):
            held = normally_closed
        else:
            return (
                f"does not know what pin {p.number} ({p.name or 'unnamed'}) is: "
                "name it COIL, COM, NO or NC"
            )
        if current.number in held:
            return "has two NO or two NC contacts under one COM"
        held[current.number] = p
    return coil, [(c, normally_open.get(c.number), normally_closed.get(c.number)) for c in coms]


def _relay_by_names(pins: tuple[PinSpec, ...]) -> SymbolBody:
    """A box with the coil on its left, the contacts on its right and a dashed link between.

    As many contact sets are stacked as there are COMs, one armature link running through all
    of them. The leads stop at the box and the sheet prints each pin's NAME just inside it, so
    the coil's strokes start after the names and the contacts end before them.
    """
    parsed = _relay_poles(pins)
    assert not isinstance(parsed, str), "declared_symbol_kind only asks for a relay it can read"
    coil, poles = parsed
    rows_per_pole = 6
    height = rows_per_pole * len(poles)
    body_r = 12
    mid = height / 2
    top, bottom = mid - 2, mid + 2
    shapes: list[SymbolShape] = [
        _rect(2, 0, body_r, height),
        _line(0, top, 2, top),
        _line(0, bottom, 2, bottom),
        # the coil: leads in from the names, a winding between them
        _line(3.9, top, 5, top, 5, mid - 1.1),
        _line(5, mid + 1.1, 5, bottom, 3.9, bottom),
        _rect(4.4, mid - 1.1, 5.6, mid + 1.1),
        _line(4.4, mid + 0.4, 5.6, mid - 0.4),
    ]
    drawn = [_lead(coil[0], 0, top, "left"), _lead(coil[1], 0, bottom, "left")]
    # the mechanical link, from the winding through every set: separate strokes, because a
    # line between a coil and a contact is what a WIRE looks like
    x = 5.9
    while x + 0.4 <= 9.1:
        shapes.append(_line(x, mid, x + 0.4, mid))
        x += 0.8
    pivot = 10.2
    for index, (com, no, nc) in enumerate(poles):
        y0 = index * rows_per_pole
        com_y = y0 + 3
        shapes += [_ring(pivot, com_y, 0.2), _line(body_r, com_y, body_r + 2, com_y)]
        if nc is not None:
            shapes += [
                _line(8, y0 + 1, pivot, y0 + 1),
                _ring(8, y0 + 1, 0.2),
                _line(body_r, y0 + 1, body_r + 2, y0 + 1),
            ]
            drawn.append(_lead(nc, body_r + 2, y0 + 1, "right"))
            blade_tip = (8.3, y0 + 1.3)
        else:
            blade_tip = (8.5, y0 + 1.7)
        if no is not None:
            shapes += [
                _line(8, y0 + 5, pivot, y0 + 5),
                _ring(8, y0 + 5, 0.2),
                _line(body_r, y0 + 5, body_r + 2, y0 + 5),
            ]
            drawn.append(_lead(no, body_r + 2, y0 + 5, "right"))
        shapes.append(_line(pivot, com_y, *blade_tip))
        drawn.append(_lead(com, body_r + 2, com_y, "right"))
    return SymbolBody(
        tuple(shapes), tuple(drawn), (body_r + 2) * GRID_MM, height * GRID_MM, names_inside=True
    )


def _relay_dispatch(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """Names first, the package second, as for a diode's cathode: a relay whose pins say COIL
    and COM is drawn from them; one that names nothing keeps the numbered contact block."""
    if not isinstance(_relay_poles(pins), str):
        return _relay_by_names(pins)
    return _relay_body(pins, footprint)


def _switch_spst(a: PinSpec, b: PinSpec) -> SymbolBody:
    """A toggle or slide switch with one throw: a raised blade between two contacts."""
    shapes = (
        _line(0, 2, 2.5, 2),
        _ring(2.5, 2, 0.2),
        _line(2.5, 2, 5.2, 0.9),
        _ring(5.5, 2, 0.2),
        _line(5.5, 2, 8, 2),
    )
    return SymbolBody(
        shapes, (_lead(a, 0, 2, "left"), _lead(b, 8, 2, "right")), 8 * GRID_MM, 4 * GRID_MM
    )


def _switch_spdt(com: PinSpec, up: PinSpec, down: PinSpec) -> SymbolBody:
    """A changeover switch: the common lead on the left, the blade resting on ``up``."""
    shapes = (
        _line(0, 3, 2.5, 3),
        _ring(2.5, 3, 0.2),
        _line(2.5, 3, 5.3, 1.3),
        _ring(5.5, 1, 0.2),
        _line(5.5, 1, 8, 1),
        _ring(5.5, 5, 0.2),
        _line(5.5, 5, 8, 5),
    )
    drawn = (_lead(com, 0, 3, "left"), _lead(up, 8, 1, "right"), _lead(down, 8, 5, "right"))
    return SymbolBody(shapes, drawn, 8 * GRID_MM, 6 * GRID_MM)


def _switch_dispatch(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """A four-legged tactile package keeps the bonded-pair pushbutton it always drew; two leads
    are a switch with one throw and three a changeover, the COM named and the blade resting on
    the contact named NC (or the first one when nothing is)."""
    if len(pins) == 4 and _switch_poles(footprint) is not None:
        return _switch_body(pins, footprint)
    if len(pins) == 2:
        return _switch_spst(pins[0], pins[1])
    com = _first_called(pins, "COM", "C") or pins[0]
    throws = [p for p in pins if p is not com]
    rested = _first_called(throws, "NC") or throws[0]
    other = next(p for p in throws if p is not rested)
    return _switch_spdt(com, rested, other)


def _button_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """A pushbutton: two contacts, a bridge held above them by a plunger."""
    shapes = (
        _line(0, 2, 2.5, 2),
        _ring(2.5, 2, 0.2),
        _ring(5.5, 2, 0.2),
        _line(5.5, 2, 8, 2),
        _line(2.2, 1, 5.8, 1),
        _line(4, 1, 4, 0.1),
        _line(3.4, 0.1, 4.6, 0.1),
    )
    return SymbolBody(
        shapes, (_lead(pins[0], 0, 2, "left"), _lead(pins[1], 8, 2, "right")), 8 * GRID_MM, 4 * GRID_MM
    )


def _buzzer_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """A loudspeaker: a magnet block and a cone, the lead named + on the top with its mark."""
    plus = _first_called(pins, "+") or pins[0]
    minus = next(p for p in pins if p is not plus)
    shapes = (
        _line(0, 1, 2.8, 1),
        _line(0, 3, 2.8, 3),
        _rect(2.8, 0.8, 4.1, 3.2),
        _poly(4.1, 1, 5.7, 0.2, 5.7, 3.8, 4.1, 3),
        _line(6.4, 1.2, 6.8, 2, 6.4, 2.8),
        _line(7.1, 0.8, 7.7, 2, 7.1, 3.2),
        _line(1.5, 0.15, 1.5, 0.75),
        _line(1.2, 0.45, 1.8, 0.45),
    )
    return SymbolBody(
        shapes, (_lead(plus, 0, 1, "left"), _lead(minus, 0, 3, "left")), 8 * GRID_MM, 4 * GRID_MM
    )


def _inductor_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """Four humps in a row: the coil."""
    shapes: list[SymbolShape] = [_line(0, 2, 2, 2), _line(6, 2, 8, 2)]
    for turn in range(4):
        cx = 2.5 + turn
        humps: list[float] = []
        for i in range(11):
            humps += [
                cx + 0.5 * math.cos(math.pi - math.pi * i / 10),
                2 - 0.6 * math.sin(math.pi * i / 10),
            ]
        shapes.append(_line(*humps))
    return SymbolBody(
        tuple(shapes),
        (_lead(pins[0], 0, 2, "left"), _lead(pins[1], 8, 2, "right")),
        8 * GRID_MM,
        4 * GRID_MM,
    )


def _motor_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """A circle with an M in it, the letter drawn as strokes so no text is needed."""
    shapes = (
        _line(0, 2, 2.4, 2),
        _line(5.6, 2, 8, 2),
        _ring(4, 2, 1.6),
        _line(3.3, 2.7, 3.3, 1.3, 4, 2.1, 4.7, 1.3, 4.7, 2.7),
    )
    return SymbolBody(
        shapes, (_lead(pins[0], 0, 2, "left"), _lead(pins[1], 8, 2, "right")), 8 * GRID_MM, 4 * GRID_MM
    )


def _optocoupler_body(pins: tuple[PinSpec, ...], footprint: Footprint | None) -> SymbolBody:
    """An LED looking at a phototransistor inside one box.

    A and K on the left, C and E on the right, the base (6-pin parts) between them. A pin the
    symbol has no use for (NC) is not drawn, like an unused lead on any other part. The leads
    stop at the box and the strokes inside start after the names the sheet prints there.
    """
    a, k, c, e = (_first_called(pins, name) for name in ("A", "K", "C", "E"))
    assert a and k and c and e, "declared_symbol_kind only asks for an optocoupler it can read"
    base = _first_called(pins, "B")
    shapes: list[SymbolShape] = [
        _rect(2, 0, 10, 6),
        _line(0, 1, 2, 1),
        _line(0, 5, 2, 5),
        _line(10, 1, 12, 1),
        _line(10, 5, 12, 5),
        # the LED, anode on top
        _line(3.2, 1, 3.5, 1, 3.5, 2),
        _poly(3.1, 2, 3.9, 2, 3.5, 3),
        _line(3.1, 3, 3.9, 3),
        _line(3.5, 3, 3.5, 5, 3.2, 5),
        # the light: two arrows from the LED to the transistor
        _line(4.3, 2.1, 5.6, 2.5),
        _arrowhead_at((5.8, 2.55), (1.3, 0.4)),
        _line(4.3, 3.0, 5.6, 3.4),
        _arrowhead_at((5.8, 3.45), (1.3, 0.4)),
        # the transistor: base bar, collector up, emitter down with its arrow
        _line(7, 2, 7, 4),
        _line(7, 2.6, 8.3, 1.7, 8.3, 1, 8.9, 1),
        _line(7, 3.4, 8.3, 4.3, 8.3, 5, 8.9, 5),
        _arrowhead_at((8.0, 4.1), (1.0, 0.7)),
    ]
    drawn = [
        _lead(a, 0, 1, "left"),
        _lead(k, 0, 5, "left"),
        _lead(c, 12, 1, "right"),
        _lead(e, 12, 5, "right"),
    ]
    if base is not None:
        shapes += [_line(7, 3, 8.9, 3), _line(10, 3, 12, 3)]
        drawn.append(_lead(base, 12, 3, "right"))
    return SymbolBody(tuple(shapes), tuple(drawn), 12 * GRID_MM, 6 * GRID_MM, names_inside=True)


# -- a functional IC or module from its pin roles ---------------------------------------------

_ROLE_LEFT: frozenset[PinRole] = frozenset({"in", "passive"})
_ROLE_RIGHT: frozenset[PinRole] = frozenset({"out"})
_ROLE_TOP: frozenset[PinRole] = frozenset({"power", "power-out"})
_ROLE_BOTTOM: frozenset[PinRole] = frozenset({"ground", "power-neg"})

#: Names the catalog gives a pin by its ALTERNATE function, keyed to the port it sits on. Used
#: to GROUP and ORDER only: what a pin prints on the sheet is still the part's own name.
ORDER_ALIASES: dict[str, str] = {
    "RXD": "PD0",
    "TXD": "PD1",
    "MOSI": "PB3",
    "MISO": "PB4",
    "SCK": "PB5",
    "XTAL1": "PB6",
    "XTAL2": "PB7",
}

_NAME_PARTS = re.compile(r"^([^\d/]*)(\d+)?(.*)$")
_LETTERED = re.compile(r"^([A-Z])[A-Z]'?$")

#: Real sans-serif capitals run ~0.68 em while ``pin_label_width`` counts 0.55 em; scaling by
#: this factor keeps left and right pin names clear of each other inside a functional box.
_FUNCTIONAL_LABEL_MARGIN: float = 1.25


def _order_name(pin: PinSpec) -> str:
    name = pin.name or pin.number
    return ORDER_ALIASES.get(name, name)


def _name_stem(name: str) -> str:
    """The name without its number or suffix: PB3 -> PB, IN1- -> IN, D1/TX -> D, QH' -> QH'."""
    match = _NAME_PARTS.match(name)
    assert match is not None
    return match.group(1) or name


def _name_root(name: str) -> str:
    """The family a name sorts in. Port letters and a lettered bank are one family each:
    PB, PC, PD read as P; QA..QH and QH' as Q. Everything else is its own stem."""
    stem = _name_stem(name)
    letters = _LETTERED.match(name)
    if letters is not None and not re.search(r"\d", name):
        return letters.group(1)
    if len(stem) == 2 and stem.isalpha() and stem.isupper() and re.search(r"\d", name):
        return stem[0]
    return stem


def _natural_name_key(name: str) -> tuple[str, int, str]:
    match = _NAME_PARTS.match(name)
    assert match is not None
    return (
        match.group(1),
        int(match.group(2)) if match.group(2) is not None else -1,
        match.group(3),
    )


def _side_of_role(role: PinRole) -> Literal["left", "right"] | None:
    if role in _ROLE_LEFT:
        return "left"
    if role in _ROLE_RIGHT:
        return "right"
    return None


def _has_functional_roles(pins: Sequence[PinSpec]) -> bool:
    """Whether every pin carries a declared role and at least one pin is connected."""
    return (
        bool(pins)
        and all(pin.role is not None for pin in pins)
        and any(pin.role != "nc" for pin in pins)
    )


def functional_ic_body(pins: Sequence[PinSpec]) -> SymbolBody:
    """A box that says what each pin DOES: inputs on the left, outputs on the right, supply on
    top and ground underneath. A pin whose role is ``io`` goes on whichever side keeps the
    columns even.

    A pin whose role is ``nc`` is not drawn, like an unused lead on any schematic.

    Pins are kept in FAMILIES by the name they share: D0..D13, IN1..IN7, PB0..PD7, QA..QH and
    QH'. A family sits on one side, in natural order (D2 before D10), so what belongs together
    reads together and OUTn faces INn; the family goes where most of its pins with a fixed role
    go (XTAL1 in, XTAL2 out: a crystal's two ends stay together). Families with no fixed-side
    votes are split between the two sides in order, at the point that makes the columns most
    even.
    """
    live = [pin for pin in pins if (pin.role or "io") != "nc"]
    top = [pin for pin in live if (pin.role or "io") in _ROLE_TOP]
    bottom = [pin for pin in live if (pin.role or "io") in _ROLE_BOTTOM]
    sided = [pin for pin in live if pin not in top and pin not in bottom]

    first_seen: dict[str, int] = {}
    root_of_stem: dict[str, str] = {}
    families: dict[str, list[PinSpec]] = {}
    for index, pin in enumerate(sided):
        key = _order_name(pin)
        stem = _name_stem(key)
        root = _name_root(key)
        first_seen.setdefault(root, index)
        root_of_stem.setdefault(stem, root)
        families.setdefault(stem, []).append(pin)

    def family_key(stem: str) -> tuple[int, str]:
        return first_seen[root_of_stem[stem]], stem

    left_families: list[str] = []
    right_families: list[str] = []
    free: list[str] = []
    for stem in sorted(families, key=family_key):
        votes = [_side_of_role(member.role or "io") for member in families[stem]]
        lefts, rights = votes.count("left"), votes.count("right")
        if lefts == 0 and rights == 0:
            free.append(stem)
        elif lefts >= rights:
            left_families.append(stem)
        else:
            right_families.append(stem)

    def rows(stems: Sequence[str]) -> int:
        return sum(len(families[stem]) for stem in stems)

    best_k = 0
    best_cost: int | None = None
    for k in range(len(free) + 1):
        cost = max(rows(left_families) + rows(free[:k]), rows(right_families) + rows(free[k:]))
        if best_cost is None or cost < best_cost:
            best_k, best_cost = k, cost
    left_families += free[:best_k]
    right_families += free[best_k:]

    def ordered(stems: Sequence[str]) -> list[PinSpec]:
        out: list[PinSpec] = []
        for stem in sorted(
            stems, key=lambda st: (first_seen[root_of_stem[st]], root_of_stem[st], st)
        ):
            out += sorted(families[stem], key=lambda member: _natural_name_key(_order_name(member)))
        return out

    left = ordered(left_families)
    right = ordered(right_families)

    rows_n = max(len(left), len(right), 1)
    pitch = 2
    lead = 2
    has_top, has_bottom = bool(top), bool(bottom)
    body_top = lead if has_top else 1
    # A supply or ground name sits just inside its horizontal edge: keep the first and last
    # side rows clear of it.
    pad_top = 1 if has_top else 0
    pad_bottom = 1 if has_bottom else 0
    body_bottom = body_top + pad_top + rows_n * pitch + pad_bottom
    height = body_bottom + (lead if has_bottom else 1)

    inset = 0.5
    left_w = (
        max(
            (pin_label_width(pin.name or pin.number) * _FUNCTIONAL_LABEL_MARGIN for pin in left),
            default=0.0,
        )
        / GRID_MM
    )
    right_w = (
        max(
            (pin_label_width(pin.name or pin.number) * _FUNCTIONAL_LABEL_MARGIN for pin in right),
            default=0.0,
        )
        / GRID_MM
    )
    edge_w = (
        max(
            (
                pin_label_width(pin.name or pin.number) * _FUNCTIONAL_LABEL_MARGIN
                for pin in (*top, *bottom)
            ),
            default=0.0,
        )
        / GRID_MM
    )
    gap = 1.0 if (left_w and right_w) else 0.0
    inner = math.ceil(inset * 2 + left_w + right_w + gap - 1e-9)
    edge_pins = max(len(top), len(bottom))
    inner = max(inner, 6, edge_pins * 2 + 2, math.ceil(edge_w + 1.0 - 1e-9))
    # Whole grid steps, and even so a centred supply or ground pin lands on a grid line.
    if inner % 2:
        inner += 1
    body_left = lead if left else 0
    body_right = body_left + inner
    width = body_right + (lead if right else 0)

    shapes: list[SymbolShape] = [_rect(body_left, body_top, body_right, body_bottom)]
    drawn: list[SymbolPin] = []
    for index, pin in enumerate(left):
        y = body_top + pad_top + pitch * (index + 1) - 1
        shapes.append(_line(0, y, body_left, y))
        drawn.append(_lead(pin, 0, y, "left"))
    for index, pin in enumerate(right):
        y = body_top + pad_top + pitch * (index + 1) - 1
        shapes.append(_line(body_right, y, width, y))
        drawn.append(_lead(pin, width, y, "right"))

    def spread(group: list[PinSpec], y_edge: float, y_end: float, side: PinSide) -> None:
        span = (len(group) - 1) * 2
        start = body_left + (inner - span) / 2
        for index, pin in enumerate(group):
            x = start + index * 2
            shapes.append(_line(x, y_edge, x, y_end))
            drawn.append(_lead(pin, x, y_end, side))

    if has_top:
        spread(top, body_top, 0, "top")
    if has_bottom:
        spread(bottom, body_bottom, height, "bottom")
    return SymbolBody(
        tuple(shapes), tuple(drawn), width * GRID_MM, height * GRID_MM, names_inside=True
    )


BUILDERS: dict[
    SymbolKind, Callable[[tuple[PinSpec, ...], Footprint | None], SymbolBody]
] = {
    "resistor": _resistor_body,
    "capacitor": _capacitor_body,
    "polarised-capacitor": _polarised_capacitor_body,
    "diode": _diode_body,
    "led": _led_body,
    "crystal": _crystal_body,
    "potentiometer": _potentiometer_body,
    "switch": _switch_dispatch,
    "relay": _relay_dispatch,
    "ic": _ic_body,
    "connector": _connector_body,
    "box": _box_body,
    "zener": _zener_body,
    "fuse": _fuse_body,
    "battery": _battery_body,
    "jack": _jack_body,
    "npn": _npn_body,
    "pnp": _pnp_body,
    "nmos": _nmos_body,
    "pmos": _pmos_body,
    "regulator": _regulator_body,
    "button": _button_body,
    "buzzer": _buzzer_body,
    "inductor": _inductor_body,
    "motor": _motor_body,
    "optocoupler": _optocoupler_body,
}

#: Which symbol an archetype asks for. ``test_schematic`` asserts this covers every member
#: of ``BodyArchetype``, so adding a body to the registry fails here rather than silently
#: drawing the new part as a box.
_KIND_BY_ARCHETYPE: dict[BodyArchetype, SymbolKind] = {
    "axial-cylinder": "resistor",  # ...or a diode, when the footprint says it is polarised
    "radial-electrolytic": "polarised-capacitor",
    "disc-ceramic": "capacitor",
    "box-film": "capacitor",
    "dip": "ic",
    "to92": "box",  # no E/B/C in the registry, so no transistor symbol
    "to220": "box",  # likewise, and the tab tells you nothing about the pinout either
    "led-round": "led",
    "pin-header": "connector",
    "screw-terminal": "connector",
    "potentiometer": "potentiometer",
    "tactile-switch": "switch",  # the legs on one side are bonded; see _switch_poles
    "crystal-hc49": "crystal",
    "relay-box": "relay",  # the coil is the pair of pins; the contacts stay numbered
    "generic-box": "box",
    "box-header": "connector",
    "wire-to-board": "connector",
    "screw-terminal-vertical": "connector",
    # A box whose pins carry the module's own names, when the part declares them.
    "module-board": "box",
    # A part off the board, drawn as what it IS when it says (``PartSymbol``) and as a box
    # with its lugs named otherwise: the pads are not the part, and a connector symbol would
    # draw a jack and a footswitch as the same row of pins.
    "flying-leads": "box",
    # Numbered as the DIP it stands in for, which is all an IC symbol reads.
    "smd-adapter": "ic",
    # The same resistor -- or diode -- stood on end: how it is fitted is not the circuit.
    "axial-upright": "resistor",
}

_TWO_TERMINAL_KINDS: frozenset[SymbolKind] = frozenset(
    {"resistor", "capacitor", "polarised-capacitor", "diode", "led", "crystal"}
)


def symbol_kind_for(footprint: Footprint | None, pin_count: int) -> SymbolKind:
    """Which symbol this part gets drawn as.

    The pin-count guards are not defensive noise. A two-terminal shape has exactly two
    places to attach a wire, so a footprint that grew a third pin must fall back to a box
    rather than have the extra lead silently dropped off the sheet.
    """
    if footprint is None:
        return "box"
    kind = _KIND_BY_ARCHETYPE[footprint.body.archetype]
    if kind == "resistor" and footprint.polarized:
        kind = "diode"
    if kind in _TWO_TERMINAL_KINDS and pin_count != 2:
        return "box"
    if kind == "potentiometer" and pin_count != 3:
        return "box"
    # The last two ask the PACKAGE whether it knows enough, rather than counting pins: a
    # switch is only a switch if its legs come in two bonded pairs, and a relay is only a
    # relay if one side of it is a two-pin winding. Neither helper will guess.
    if kind == "switch" and (_switch_poles(footprint) is None or pin_count != 4):
        return "box"
    if kind == "relay" and (_relay_sides(footprint) is None or pin_count != len(footprint.pins)):
        return "box"
    return kind
