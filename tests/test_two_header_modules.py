"""A module with two headers of different lengths (``mod2-``), and what each consumer of a
footprint does with a lattice cell that has no pin.

A PCF8574 QT board has a 6-pin and a 10-pin row 12.7 mm apart; an illuminated rotary
encoder a 3-pin and a 5-pin row 25.4 mm apart. ``mod-`` is one rectangular grid, so neither
could be said. ``mod2-<first>x<second>-r<rowStep>-...`` is two rows, the shorter centred
along the longer, numbered row by row -- and the footprint carries pins only where the
module has them, so everything that reads ``footprint.pins`` sees no phantom header.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from perfboard_studio.footprints import (
    MODULE_PCB_MM,
    get_footprint,
    module_footprint,
    two_header_module_footprint,
)
from perfboard_studio.mcp.session import BoardSession, new_board
from perfboard_studio.phrasebook import phrasebook
from perfboard_studio.ui.bodies import pin_labels

QT = "mod2-6x10-r5-25.4x17.78x3-s8.5-o0x-2.5"
ENCODER = "mod2-3x5-r10-27x20x12-s2.5"


# ------------------------------------------------------------------------ the footprint
def test_two_headers_are_laid_row_by_row_with_the_short_one_centred() -> None:
    footprint = get_footprint(QT)
    assert footprint is not None and footprint.id == QT
    assert footprint.body.archetype == "module-board"
    assert [(pin.number, pin.d_col, pin.d_row) for pin in footprint.pins] == (
        [(str(n), n + 1, 0) for n in range(1, 7)]
        + [(str(n), n - 7, 5) for n in range(7, 17)]
    )
    assert footprint.body_height == pytest.approx(8.5 + MODULE_PCB_MM + 3)
    assert footprint.body.dims["seat"] == 8.5 and footprint.body.dims["top"] == 3


def test_the_long_header_may_come_first() -> None:
    footprint = get_footprint("mod2-5x3-r10-27x20x12-s2.5")
    assert footprint is not None
    assert [(pin.number, pin.d_col, pin.d_row) for pin in footprint.pins] == [
        ("1", 0, 0), ("2", 1, 0), ("3", 2, 0), ("4", 3, 0), ("5", 4, 0),
        ("6", 1, 10), ("7", 2, 10), ("8", 3, 10),
    ]


def test_one_spelling_per_two_header_module() -> None:
    """Zero offset is left out; equal rows are the grid ``mod-`` already spells; a short
    row that cannot be centred on the lattice is refused rather than rounded."""
    assert get_footprint("mod2-6x10-r5-25.4x17.78x3-s8.5-o0x0") is None
    assert get_footprint("mod2-8x8-r5-25x18x3-s8.5") is None
    assert get_footprint("mod2-5x10-r5-25x18x3-s8.5") is None
    assert get_footprint("mod2-6x10-r0-25x18x3-s8.5") is None
    assert get_footprint("mod2-0x10-r5-25x18x3-s8.5") is None
    assert get_footprint("mod2-6x10-r5-25x18x3-s0") is None
    assert get_footprint("mod2-6x10-r5-25x18x3-s8.5-extra") is None
    built = two_header_module_footprint(
        first=6, second=10, row_step=5, width_mm=25.4, depth_mm=17.78, top_mm=3,
        seat_mm=8.5, offset_y_mm=-2.5,
    )
    assert built.id == QT and built == get_footprint(QT)


def test_the_name_says_both_lengths_and_is_said_in_turkish() -> None:
    footprint = get_footprint(QT)
    assert footprint is not None
    assert footprint.name == "Module, 6+10 pins, 25.4 x 17.78 mm, seated 8.5 mm up"
    assert phrasebook("en").footprint(footprint.name) == footprint.name
    assert phrasebook("tr").footprint(footprint.name) == (
        "Modül, 6+10 pin, 25.4 x 17.78 mm, 8.5 mm yukarıda"
    )


def test_the_courtyard_is_the_long_rows_box_like_a_full_grid() -> None:
    """The short row sits inside the long one's span, so the pins' bounding box -- which
    the courtyard is built from -- is the one a full 2 x 10 grid has."""
    full = module_footprint(
        cols=10, rows=2, row_step=5, width_mm=25.4, depth_mm=17.78, top_mm=3, seat_mm=8.5,
        offset_y_mm=-2.5,
    )
    two = get_footprint(QT)
    assert two is not None
    assert two.body_outline == full.body_outline
    assert two.body_height == full.body_height


# -------------------------------------------------------------- the engine's consumers
def _board(placements: dict[str, tuple[str, str]]) -> BoardSession:
    session = BoardSession(document=new_board(cols=30, rows=24))
    for ref, (footprint_id, hole) in placements.items():
        assert session.place_component(ref, footprint_id, hole)["ok"]
    return session


def test_drc_sees_no_pin_where_the_module_has_none() -> None:
    session = _board({"U1": (QT, "D5")})
    assert session.run_erc()["findings"] == []
    assert session.run_drc()["violations"] == []


def test_a_part_in_a_cell_the_short_header_leaves_empty_is_under_the_module() -> None:
    """The corner cell D5 has no pin, so a resistor standing on it is allowed -- and is
    still under the module's board, so DRC says to fit it first. One clear of the body
    (D13) is not mentioned."""
    session = _board({"U1": (QT, "D5"), "R2": ("r-axial-4", "D13")})
    assert session.place_component("R1", "r-axial-4", "D5", rotation=90)["ok"]
    under = [
        tuple(v["components"]) for v in session.run_drc()["violations"]
        if v["rule"] == "under-module"
    ]
    assert under == [("R1", "U1")]
    assert not any(v["rule"] == "body-overlap" for v in session.run_drc()["violations"])


def test_a_module_whose_board_runs_past_the_edge_is_reported() -> None:
    session = _board({"U1": (QT, "D1")})
    rules = {v["rule"] for v in session.run_drc()["violations"]}
    assert "component-overhangs-edge" in rules


def test_the_router_lays_wires_to_the_pins_the_module_has() -> None:
    session = _board({"U1": (QT, "D5"), "R1": ("r-axial-4", "D8"), "R2": ("r-axial-4", "D13")})
    assert session.create_net("N1", "signal", ["U1.1", "R1.1"])["ok"]
    assert session.create_net("N2", "signal", ["U1.16", "R2.1"])["ok"]
    assert session.create_net("N3", "signal", ["U1.7", "R1.2", "R2.2"])["ok"]
    routed = session.autoroute()
    assert routed["ok"] and routed["unrouted"] == 0
    assert session.run_lvs()["matches_schematic"] is True


def test_the_guide_fits_the_module_with_its_headers_first() -> None:
    session = _board({"U1": (QT, "D5")})
    guide = session.generate_guide()
    assert guide["part_steps"] == 1
    assert next(phase["title"] for phase in guide["phases"]) == "Tall and mechanical"


def test_the_step_file_has_a_lead_for_each_pin_the_module_has(tmp_path: Path) -> None:
    """Sixteen leads, not the twenty a full 2 x 10 grid would have: a hole with no pin is
    not drilled and has nothing in it."""
    two = _board({"U1": (QT, "D5")})
    full = _board({
        "U1": (
            module_footprint(
                cols=10, rows=2, row_step=5, width_mm=25.4, depth_mm=17.78, top_mm=3,
                seat_mm=8.5, offset_y_mm=-2.5,
            ).id,
            "D5",
        )
    })
    assert full.export_step(str(tmp_path / "full.step"))["solids"] - two.export_step(
        str(tmp_path / "two.step")
    )["solids"] == 4


# ------------------------------------------------------------------------ the views
def test_pin_names_are_printed_at_the_pins_there_are() -> None:
    session = _board({"U1": (QT, "D5")})
    footprint = session.lookup(QT)
    assert footprint is not None
    comp = session.document.components[0]
    named = replace(comp, pin_names=(("1", "A"), ("16", "Z")))
    labels = pin_labels(footprint, named, 2.54)
    assert sorted(label.number for label in labels) == ["1", "16"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_the_3d_module_stands_on_one_strip_per_header(rotation: int) -> None:
    from perfboard_studio.ui import view3d

    session = _board({"U1": (QT, "D5")})
    assert session.rotate_component("U1", rotation)["ok"]
    comp = session.document.components[0]
    footprint = session.lookup(QT)
    body = view3d._world_body(session.lookup, comp, session.document.board)
    assert footprint is not None and body is not None
    pieces = view3d._module_pieces(body, footprint, comp, session.document.board)
    strips = [p for p in pieces if p.rgb == view3d._HEADER_PLASTIC_RGB]
    # A 6-pin strip and a 10-pin strip -- no third, and no header under the empty cells.
    lengths = sorted(round(max(p.source.GetXLength(), p.source.GetYLength()) / 2.54) for p in strips)
    assert lengths == [6, 10]
    pins = next(p for p in pieces if p.instances)
    assert len(pins.instances) == 16


# --------------------------------------------------------------------- the catalog board
def test_the_pcf8574_qt_is_pinned_as_adafruits_board_is() -> None:
    """Adafruit's Eagle board: JP3 is the ten pads along one edge, '+' P7 to P0 '-' left to
    right, and JP1 the six VIN GND SCL SDA INT A0 along the other, centred on the ten."""
    from perfboard_studio.catalog import catalog_part

    part = catalog_part("adafruit-pcf8574-qt")
    assert part is not None
    footprint = get_footprint(part.footprint_id)
    assert footprint is not None
    at = {pin.number: (pin.d_col, pin.d_row) for pin in footprint.pins}
    names = dict(part.pin_names)
    assert len(part.pin_roles) == len(footprint.pins) == len(names) == 16
    ends = {names[number]: at[number] for number in ("2", "9", "11", "16")}
    assert ends == {"P7": (1, 0), "P0": (8, 0), "VIN": (2, 5), "A0": (7, 5)}
    assert (at["1"], at["10"]) == ((0, 0), (9, 0))
    assert dict(part.pin_roles)["16"] == "in" and dict(part.pin_roles)["15"] == "out"
