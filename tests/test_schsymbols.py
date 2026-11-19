"""The symbol bodies that find their leads by NAME.

A body never reads a pin NUMBER to decide what a lead is: a 7805 is IN GND OUT, an LM317 ADJ
OUT IN and an LD1117 GND OUT IN, all in the same TO-220, and a template keyed on numbers
draws two of the three backwards.
"""

from __future__ import annotations

import math

import pytest

from perfboard_studio.catalog import CATALOG, catalog_part
from perfboard_studio.footprints import get_footprint
from perfboard_studio.schsymbols import (
    BUILDERS,
    DECLARED_SYMBOL_RULES,
    GRID_MM,
    PinSpec,
    SymbolBody,
    SymbolKind,
    declared_symbol_kind,
)


def specs(*names: str | None) -> tuple[PinSpec, ...]:
    return tuple(PinSpec(str(i + 1), name) for i, name in enumerate(names))


def catalog_specs(cid: str) -> tuple[PinSpec, ...]:
    return tuple(PinSpec(number, name) for number, name in catalog_part(cid).pin_names)


def steps(value: float) -> float:
    return value / GRID_MM


def assert_on_grid(body: SymbolBody, label: str, *, strokes: bool = True) -> None:
    """The body rules: whole-step size, every pin on the grid and inside, none on another.

    ``strokes`` also holds every stroke inside the box; the older declared bodies (a battery's
    plates) are not held to it here."""
    assert math.isclose(steps(body.width), round(steps(body.width))), label
    assert math.isclose(steps(body.height), round(steps(body.height))), label
    seen: set[tuple[float, float]] = set()
    for pin in body.pins:
        x, y = steps(pin.at.x), steps(pin.at.y)
        assert math.isclose(x, round(x), abs_tol=1e-9), f"{label}: pin {pin.number} off the grid in x"
        assert math.isclose(y, round(y), abs_tol=1e-9), f"{label}: pin {pin.number} off the grid in y"
        assert -1e-9 <= pin.at.x <= body.width + 1e-9, label
        assert -1e-9 <= pin.at.y <= body.height + 1e-9, label
        edge_ok = (
            (pin.side == "left" and math.isclose(pin.at.x, 0.0, abs_tol=1e-9))
            or (pin.side == "right" and math.isclose(pin.at.x, body.width, abs_tol=1e-9))
            or (pin.side == "top" and math.isclose(pin.at.y, 0.0, abs_tol=1e-9))
            or (pin.side == "bottom" and math.isclose(pin.at.y, body.height, abs_tol=1e-9))
        )
        assert edge_ok, f"{label}: pin {pin.number} ({pin.side}) is not on its box edge"
        point = (round(x), round(y))
        assert point not in seen, f"{label}: two pins on {point}"
        seen.add(point)
    for shape in body.shapes if strokes else ():
        for point in shape.points:
            assert -1e-9 <= point.x <= body.width + 1e-9, f"{label}: a stroke leaves the box"
            assert -1e-9 <= point.y <= body.height + 1e-9, f"{label}: a stroke leaves the box"


def side_of(body: SymbolBody, name: str) -> str:
    return next(p.side for p in body.pins if p.name == name)


# ---------------------------------------------------------------------------
# A regulator's leads are told apart by name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cid", "in_number", "out_number", "third_number", "third_name"),
    [
        ("7805", "1", "3", "2", "GND"),
        ("lm317t", "3", "2", "1", "ADJ"),
        ("ld1117v33", "3", "2", "1", "GND"),
    ],
)
def test_a_regulators_leads_follow_the_names_not_the_numbers(
    cid: str, in_number: str, out_number: str, third_number: str, third_name: str
) -> None:
    body = BUILDERS["regulator"](catalog_specs(cid), None)
    by_number = {p.number: p for p in body.pins}
    assert by_number[in_number].side == "left"
    assert by_number[out_number].side == "right"
    assert by_number[third_number].side == "bottom"
    assert by_number[third_number].name == third_name


def test_a_7805_and_an_lm317_put_the_same_numbers_on_different_sides() -> None:
    seven = {p.number: p.side for p in BUILDERS["regulator"](catalog_specs("7805"), None).pins}
    three = {p.number: p.side for p in BUILDERS["regulator"](catalog_specs("lm317t"), None).pins}
    assert seven == {"1": "left", "3": "right", "2": "bottom"}
    assert three == {"3": "left", "2": "right", "1": "bottom"}


def test_every_three_pin_catalog_regulator_declares_the_regulator_symbol() -> None:
    regulators = [part for part in CATALOG if part.category == "regulator"]
    declared_ids = {part.id for part in regulators if part.symbol == "regulator"}
    qualifying_ids = {
        part.id
        for part in regulators
        if DECLARED_SYMBOL_RULES["regulator"](
            tuple(PinSpec(number, name) for number, name in part.pin_names)
        )
        is None
    }
    assert declared_ids == qualifying_ids
    assert {"7805", "lm317t", "78l05", "ld1117v33", "ams1117-33-module"} <= declared_ids


# ---------------------------------------------------------------------------
# The relay: COIL twice, and as many contact sets as there are COMs
# ---------------------------------------------------------------------------


def test_a_relay_is_read_from_its_names_wherever_the_footprint_puts_them() -> None:
    # The SRD's own order: COM, COIL, NO, NC, COIL -- the winding is not the first two pins.
    body = BUILDERS["relay"](specs("COM", "COIL", "NO", "NC", "COIL"), None)
    assert [p.side for p in body.pins if p.name == "COIL"] == ["left", "left"]
    for name in ("COM", "NO", "NC"):
        assert side_of(body, name) == "right"
    assert body.names_inside


def test_two_contact_sets_are_two_stacked_sets() -> None:
    one = BUILDERS["relay"](specs("COIL", "COIL", "COM", "NO", "NC"), None)
    two = BUILDERS["relay"](specs("COIL", "COIL", "COM", "NO", "NC", "COM", "NO", "NC"), None)
    assert math.isclose(two.height, 2 * one.height)
    assert len(two.pins) == 8
    assert_on_grid(two, "DPDT relay")


def test_a_relay_that_names_nothing_keeps_the_numbered_contact_block() -> None:
    footprint = get_footprint("relay-spdt")
    assert footprint is not None
    unnamed = tuple(PinSpec(pin.number, None) for pin in footprint.pins)
    body = BUILDERS["relay"](unnamed, footprint)
    assert not body.names_inside
    assert {p.number for p in body.pins} == {pin.number for pin in footprint.pins}


# ---------------------------------------------------------------------------
# What a declaration needs
# ---------------------------------------------------------------------------


def declared(symbol: str, *names: str | None) -> tuple[SymbolKind | None, str | None]:
    return declared_symbol_kind(symbol, specs(*names), None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("symbol", "names"),
    [
        ("regulator", ("IN", "GND", "OUT")),
        ("regulator", ("ADJ", "VOUT", "VIN")),
        ("relay", ("COIL", "COIL", "COM", "NO")),
        ("relay", ("COM", "COIL", "NO", "NC", "COIL")),
        ("switch", (None, None)),
        ("switch", ("COM", "A", "B")),
        ("button", (None, None)),
        ("buzzer", ("+", "-")),
        ("inductor", (None, None)),
        ("motor", (None, None)),
        ("optocoupler", ("A", "K", "E", "C")),
        ("optocoupler", ("A", "K", "NC", "E", "C", "B")),
    ],
)
def test_a_part_that_names_what_the_symbol_needs_is_drawn_as_it(
    symbol: str, names: tuple[str | None, ...]
) -> None:
    assert declared(symbol, *names) == (symbol, None)


@pytest.mark.parametrize(
    ("symbol", "names"),
    [
        ("regulator", ("1", "2", "3")),
        ("regulator", ("IN", "OUT")),
        ("relay", (None, None, None, None)),
        ("relay", ("COIL", "COIL", "NO", "NC")),
        ("relay", ("COIL", "COIL", "COM", "NO", "NO")),
        ("relay", ("COIL", "COIL", "COM", "X")),
        ("switch", (None, None, None)),
        ("switch", (None,)),
        ("button", (None, None, None)),
        ("buzzer", (None, None)),
        ("inductor", (None,)),
        ("motor", (None, None, None)),
        ("optocoupler", ("1", "2", "3", "4")),
        ("optocoupler", ("A", "K", "C")),
    ],
)
def test_a_part_that_does_not_is_left_a_box_with_a_reason(
    symbol: str, names: tuple[str | None, ...]
) -> None:
    kind, why_not = declared(symbol, *names)
    assert kind is None
    assert why_not is not None and why_not.startswith(f"declared {symbol}")


# ---------------------------------------------------------------------------
# Every body follows the rules, and every catalog declaration can be drawn
# ---------------------------------------------------------------------------

BODIES: dict[str, tuple[SymbolKind, tuple[PinSpec, ...]]] = {
    "regulator": ("regulator", specs("IN", "GND", "OUT")),
    "relay SPDT": ("relay", specs("COIL", "COIL", "COM", "NO", "NC")),
    "relay SPST": ("relay", specs("COIL", "COIL", "COM", "NO")),
    "relay unnamed pole order": ("relay", specs("NO", "COIL", "COM", "NC", "COIL")),
    "switch SPST": ("switch", specs(None, None)),
    "switch SPDT": ("switch", specs("COM", "NO", "NC")),
    "button": ("button", specs(None, None)),
    "buzzer": ("buzzer", specs("+", "-")),
    "buzzer reversed": ("buzzer", specs("-", "+")),
    "inductor": ("inductor", specs(None, None)),
    "motor": ("motor", specs(None, None)),
    "opto 4": ("optocoupler", specs("A", "K", "E", "C")),
    "opto 6": ("optocoupler", specs("A", "K", "NC", "E", "C", "B")),
}


@pytest.mark.parametrize("label", sorted(BODIES))
def test_every_body_is_on_the_grid_inside_its_box_and_alone(label: str) -> None:
    kind, pins = BODIES[label]
    assert_on_grid(BUILDERS[kind](pins, None), label)


def test_a_buzzers_plus_lead_is_the_one_named_plus() -> None:
    forward = BUILDERS["buzzer"](specs("+", "-"), None)
    backward = BUILDERS["buzzer"](specs("-", "+"), None)
    top = lambda body: min(body.pins, key=lambda p: p.at.y).name  # noqa: E731
    assert top(forward) == top(backward) == "+"


def test_an_optocouplers_nc_is_not_drawn() -> None:
    body = BUILDERS["optocoupler"](specs("A", "K", "NC", "E", "C", "B"), None)
    assert {p.name for p in body.pins} == {"A", "K", "E", "C", "B"}


def test_every_rule_has_a_builder() -> None:
    assert set(DECLARED_SYMBOL_RULES) <= set(BUILDERS)


@pytest.mark.parametrize(
    "part", [part for part in CATALOG if part.symbol is not None], ids=lambda part: part.id
)
def test_every_declared_kind_is_drawn_for_every_catalog_part_that_declares_it(part) -> None:
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None
    named = dict(part.pin_names)
    pins = tuple(PinSpec(pin.number, named.get(pin.number)) for pin in footprint.pins)
    kind, why_not = declared_symbol_kind(part.symbol, pins, footprint)
    assert kind is not None, f"{part.id}: {why_not}"
    assert_on_grid(BUILDERS[kind](pins, footprint), part.id, strokes=False)
