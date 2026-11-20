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
from perfboard_studio.model import PinRole
from perfboard_studio.schsymbols import (
    BUILDERS,
    DECLARED_SYMBOL_RULES,
    GRID_MM,
    PinSpec,
    SymbolBody,
    SymbolKind,
    declared_symbol_kind,
    functional_ic_body,
    symbol_kind_for,
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


# ---------------------------------------------------------------------------
# Functional IC and module symbols from pin_roles
# ---------------------------------------------------------------------------


def _ic(*pairs: tuple[str | None, PinRole]) -> SymbolBody:
    return functional_ic_body(
        tuple(PinSpec(str(i + 1), name, role) for i, (name, role) in enumerate(pairs))
    )


def _where(body: SymbolBody) -> dict[str, tuple[float, float, str]]:
    """Each pin's name -> (x, y in grid steps, side)."""
    return {p.name: (steps(p.at.x), steps(p.at.y), p.side) for p in body.pins if p.name}


def test_a_bank_reads_in_order_and_the_prime_comes_last() -> None:
    names = ["QB", "QC", "QD", "QE", "QF", "QG", "QH", "QH'", "QA"]
    body = _ic(*((n, "out") for n in names), ("SER", "in"), ("VCC", "power"), ("GND", "ground"))
    right = sorted((p for p in body.pins if p.side == "right"), key=lambda p: p.at.y)
    assert [p.name for p in right] == ["QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH", "QH'"]
    assert_on_grid(body, "74HC595")


def test_an_output_faces_the_input_with_its_number() -> None:
    ins: list[tuple[str, PinRole]] = [(f"IN{n}", "in") for n in range(1, 8)]
    outs: list[tuple[str, PinRole]] = [(f"OUT{n}", "out") for n in range(7, 0, -1)]
    body = _ic(*ins, *outs, ("COM", "passive"), ("GND", "ground"))
    where = _where(body)
    for n in range(1, 8):
        assert where[f"IN{n}"][1] == where[f"OUT{n}"][1]
    assert where["COM"][1] > where["IN7"][1]
    assert_on_grid(body, "ULN2003A")


def test_numbers_sort_naturally_and_a_family_stays_together() -> None:
    pairs: list[tuple[str, PinRole]] = [(f"D{n}", "io") for n in (10, 2, 0, 9, 1, 13)] + [
        (f"A{n}", "in" if n > 5 else "io") for n in (7, 0, 6, 3)
    ]
    body = _ic(*pairs, ("GND", "ground"))
    for stem in ("D", "A"):
        side_pins = [p for p in body.pins if p.name and p.name[0] == stem]
        assert len({p.side for p in side_pins}) == 1
        ordered = [p.name for p in sorted(side_pins, key=lambda p: p.at.y) if p.name]
        assert ordered == sorted(ordered, key=lambda n: int(n[1:]))
    assert_on_grid(body, "natural-order")


def test_a_crystals_two_ends_stay_together() -> None:
    body = _ic(("XTAL1", "in"), ("XTAL2", "out"), ("PB0", "io"), ("PB1", "io"), ("VCC", "power"))
    where = _where(body)
    assert where["XTAL1"][2] == where["XTAL2"][2]
    assert abs(where["XTAL1"][1] - where["XTAL2"][1]) == 2
    assert_on_grid(body, "xtal")


def test_a_functional_ic_omits_nc_pins() -> None:
    body = _ic(("A", "in"), ("NC", "nc"), ("Y", "out"), ("VCC", "power"), ("GND", "ground"))
    assert {p.name for p in body.pins} == {"A", "Y", "VCC", "GND"}
    assert_on_grid(body, "nc-omitted")


def test_an_alternate_function_name_sorts_with_its_port_and_prints_as_itself() -> None:
    names = ["RXD", "TXD", "PD2", "PB0", "PB1", "PB2", "MOSI", "MISO", "SCK", "XTAL1", "XTAL2"]
    pairs: list[tuple[str, PinRole]] = [
        (n, "in" if n == "XTAL1" else ("out" if n == "XTAL2" else "io")) for n in names
    ]
    body = _ic(*pairs, ("VCC", "power"))
    b_names = {"PB0", "PB1", "PB2", "MOSI", "MISO", "SCK", "XTAL1", "XTAL2"}
    assert len({p.side for p in body.pins if p.name in b_names}) == 1
    port_b = [p.name for p in sorted(body.pins, key=lambda p: p.at.y) if p.name in b_names]
    assert port_b == ["PB0", "PB1", "PB2", "MOSI", "MISO", "SCK", "XTAL1", "XTAL2"]
    port_d = [p.name for p in sorted(body.pins, key=lambda p: p.at.y) if p.name in {"RXD", "TXD", "PD2"}]
    assert port_d == ["RXD", "TXD", "PD2"]
    assert_on_grid(body, "alt-fn-aliases")


def test_parts_without_complete_roles_keep_the_numbered_box_unchanged() -> None:
    plain_pins = specs("GND", "TRIG", "OUT", "RESET", "CTRL", "THR", "DIS", "VCC")
    partial_pins = (PinSpec("1", "GND", "ground"), *plain_pins[1:])
    all_nc = tuple(PinSpec(str(i + 1), "NC", "nc") for i in range(4))

    for kind in ("ic", "box"):
        plain = BUILDERS[kind](plain_pins, None)
        assert not plain.names_inside
        assert {p.side for p in plain.pins} <= {"left", "right"}
        assert BUILDERS[kind](partial_pins, None) == plain
        nc_box = BUILDERS[kind](all_nc, None)
        assert not nc_box.names_inside
        assert len(nc_box.pins) == 4


def test_functional_ic_handles_edge_shapes_and_mixed_case_names() -> None:
    mixed = _ic(("In1", "in"), ("Ch2", "out"), (None, "io"), ("VCC", "power"), ("GND", "ground"))
    assert_on_grid(mixed, "mixed-case-unnamed")
    right_only = _ic(("OUT1", "out"), ("OUT2", "out"), ("VCC", "power"), ("GND", "ground"))
    assert_on_grid(right_only, "right-only")
    assert {p.side for p in right_only.pins} == {"right", "top", "bottom"}
    rails_only = _ic(("VCC", "power"), ("GND", "ground"))
    assert_on_grid(rails_only, "rails-only")
    assert {p.side for p in rails_only.pins} == {"top", "bottom"}


@pytest.mark.parametrize(
    "part", [part for part in CATALOG if part.pin_roles], ids=lambda part: part.id
)
def test_every_catalog_part_with_pin_roles_draws_a_valid_functional_body(part) -> None:
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None
    named = dict(part.pin_names)
    roles = dict(part.pin_roles)
    pins = tuple(
        PinSpec(pin.number, named.get(pin.number), roles[pin.number]) for pin in footprint.pins
    )
    kind = symbol_kind_for(footprint, len(pins))
    body = BUILDERS[kind](pins, footprint) if kind in ("ic", "box") else functional_ic_body(pins)
    assert body.names_inside
    assert_on_grid(body, part.id)
    expected_live = {p.number for p in pins if p.role != "nc"}
    assert {p.number for p in body.pins} == expected_live
    for drawn in body.pins:
        role = roles[drawn.number]
        if role in ("power", "power-out"):
            assert drawn.side == "top", f"{part.id} pin {drawn.number} ({role})"
        elif role in ("ground", "power-neg"):
            assert drawn.side == "bottom", f"{part.id} pin {drawn.number} ({role})"
        else:
            assert drawn.side in ("left", "right"), f"{part.id} pin {drawn.number} ({role})"
