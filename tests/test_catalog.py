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
    assert legs["irf9540n"] == ("G", "D", "S")


def test_a_module_is_a_module_and_its_rows_are_where_its_source_measured_them() -> None:
    expected_rows_mm = {
        "esp32-devkitc": 25.4,
        "esp32-c3-devkitm-1": 22.86,
        "arduino-nano": 15.24,
        "raspberry-pi-pico": 17.78,
        "wemos-d1-mini": 22.86,
    }
    modules = [part for part in CATALOG if part.category == "module"]
    assert {part.id for part in modules} == set(expected_rows_mm)
    for part in modules:
        footprint = get_footprint(part.footprint_id)
        assert footprint is not None and footprint.body.archetype == "module-board"
        columns = sorted({pin.d_col for pin in footprint.pins})
        assert len(columns) == 2, part.id
        assert (columns[1] - columns[0]) * STANDARD_PITCH_MM == pytest.approx(
            expected_rows_mm[part.id]
        ), part.id
        assert part.check, f"{part.id}: a module's estimates have to be said"


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
    assert {part.id for part in search_catalog("esp32")} == {"esp32-devkitc", "esp32-c3-devkitm-1"}
    assert all(part.symbol == "pmos" for part in search_catalog("p-channel"))
    assert {part.category for part in search_catalog(category="regulator")} == {"regulator"}
    assert catalog_part("  BC547 ") is catalog_part("bc547")
    assert catalog_part("nothing-like-it") is None


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
