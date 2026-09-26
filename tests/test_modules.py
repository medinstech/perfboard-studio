"""A module on header pins, and the pin names printed beside a part's pins.

A module (``mod-``) is a small board of its own standing on its pins: the id carries the
pins, the module's board, its seat and the height of what is on it, and nothing else
about it is stored. Pin names are printed where ``bodies.pin_labels`` says -- on a
module's own board, or on this board just outside any other part -- and the two views
must agree about that, or two pictures of one board say different things about which pin
is which.
"""

from __future__ import annotations

import pytest

from perfboard_studio.footprints import (
    GENERATED_ID_GRAMMAR,
    MODULE_PCB_MM,
    body_extent,
    get_footprint,
    module_footprint,
)
from perfboard_studio.guide import build_guide
from perfboard_studio.mcp.session import BoardSession, new_board
from perfboard_studio.model import ComponentInstance, HoleCoord
from perfboard_studio.ui.bodies import pin_labels, placement_for

DEVKITC = "mod-2x19-p10-r1-27.94x54.3x3.5-s8.5-o0x-3"


# ------------------------------------------------------------------------ the footprint


def test_a_module_id_is_its_own_definition_and_reads_back_the_same() -> None:
    footprint = get_footprint(DEVKITC)
    assert footprint is not None and footprint.id == DEVKITC
    assert footprint.body.archetype == "module-board"
    assert len(footprint.pins) == 38
    # Its board 8.5 mm up in a female header, 1.6 mm thick, 3.5 mm of parts on it.
    assert footprint.body_height == pytest.approx(8.5 + MODULE_PCB_MM + 3.5)
    assert footprint.body.dims["seat"] == 8.5 and footprint.body.dims["top"] == 3.5
    extent = body_extent(footprint, 2.54)
    assert (extent.size_x, extent.size_y) == (27.94, 54.3)
    assert extent.centre_y == pytest.approx(45.72 / 2 - 3.0)  # the antenna end is longer


def test_one_spelling_per_module() -> None:
    """Zero offset is spelled by leaving it out, and one row has no second step -- the
    rule every generated id keeps, so two ids can never mean one part."""
    assert get_footprint("mod-6x1-p1-r1-16x14.5x3-s8.5-o0x0") is None
    assert get_footprint("mod-6x1-p1-r3-16x14.5x3-s8.5") is None
    assert module_footprint(
        cols=6, rows=1, row_step=3, width_mm=16, depth_mm=14.5, top_mm=3, seat_mm=8.5
    ).id == "mod-6x1-p1-r1-16x14.5x3-s8.5"
    assert get_footprint("mod-2x2-p1-r1-10x10x3-s0") is None  # nothing sits at zero


def test_module_pins_are_numbered_row_by_row_like_a_box() -> None:
    footprint = get_footprint("mod-2x3-p6-r1-18x10x3-s8.5")
    assert footprint is not None
    assert [(pin.number, pin.d_col, pin.d_row) for pin in footprint.pins] == [
        ("1", 0, 0), ("2", 6, 0), ("3", 0, 1), ("4", 6, 1), ("5", 0, 2), ("6", 6, 2),
    ]


def test_the_grammar_says_how_to_ask_for_one() -> None:
    assert "mod-<cols>x<rows>" in GENERATED_ID_GRAMMAR


def test_the_guide_says_what_goes_in_first() -> None:
    """Socketed: the headers now, the module last. Soldered straight in: check before, it
    does not come out again."""
    for seat, words in (("8.5", "female header strips"), ("2.5", "cannot come out again")):
        session = BoardSession(document=new_board(cols=30, rows=20))
        assert session.place_component(
            "U1", f"mod-6x1-p1-r1-16x14.5x3-s{seat}-o0x6", "C4"
        )["ok"]
        guide = build_guide(session.document, session.lookup)
        notes = " ".join(
            note
            for phase in guide.phases
            for step in phase.steps
            for note in getattr(step, "notes", ())
        )
        assert words in notes, seat


# ------------------------------------------------------------------------ where names go


def _placed(footprint_id: str, names: dict[str, str], rotation: int = 0) -> ComponentInstance:
    return ComponentInstance(
        id="c1",
        ref="X1",
        value="",
        footprint_id=footprint_id,
        anchor=HoleCoord(5, 5),
        rotation=rotation,  # type: ignore[arg-type]
        pin_names=tuple(names.items()),
    )


def test_a_modules_names_run_into_its_own_board() -> None:
    footprint = get_footprint(DEVKITC)
    assert footprint is not None
    labels = pin_labels(footprint, _placed(DEVKITC, {"1": "3V3", "2": "GND"}), 2.54)
    assert [(label.name, label.dx, label.on_module) for label in labels] == [
        ("3V3", 1.0, True),  # the left column's run right, into the board
        ("GND", -1.0, True),  # the right column's run left
    ]


def test_anything_else_has_its_names_outside_it() -> None:
    """A DIP's down either side like a pinout drawing, starting past the body's edge."""
    footprint = get_footprint("dip-8")
    assert footprint is not None
    names = {"1": "GND", "8": "VCC"}
    labels = {label.name: label for label in pin_labels(footprint, _placed("dip-8", names), 2.54)}
    placement = placement_for(footprint, 2.54)
    assert labels["GND"].dx == -1.0 and labels["VCC"].dx == 1.0
    assert not labels["GND"].on_module
    # Pin 1 is on the body's left edge column; its name starts past the body.
    body_left = placement.centre_x - placement.size_x / 2
    assert labels["GND"].x - labels["GND"].start < body_left


def test_a_terminals_names_go_behind_it_not_across_its_mouth() -> None:
    """The mouth is local +y; the wires come in there, so the names go to -y."""
    footprint = get_footprint("screw-terminal-4")
    assert footprint is not None
    labels = pin_labels(footprint, _placed("screw-terminal-4", {"1": "CAN_H"}), 2.54)
    assert [(label.dx, label.dy) for label in labels] == [(0.0, -1.0)]


def test_only_declared_names_are_printed_off_a_module() -> None:
    """An LED's registry A and K on every LED on the board would be noise; a name somebody
    typed in is one they wanted to see."""
    footprint = get_footprint("led-5mm")
    assert footprint is not None
    assert pin_labels(footprint, _placed("led-5mm", {}), 2.54) == ()
    assert len(pin_labels(footprint, _placed("led-5mm", {"1": "A"}), 2.54)) == 1


# ------------------------------------------------------------------------ 3D

vtk = pytest.importorskip("vtk")


def _board_with(component_id: str, names: dict[str, str]):
    session = BoardSession(document=new_board(cols=40, rows=30))
    assert session.place_component("U1", component_id, "D5", pin_names=names)["ok"]
    return session


def test_a_devkit_stands_on_two_header_strips_with_its_pins_through_its_board() -> None:
    from perfboard_studio.ui import view3d

    session = _board_with(DEVKITC, {})
    comp = session.document.components[0]
    footprint = session.lookup(DEVKITC)
    body = view3d._world_body(session.lookup, comp, session.document.board)
    assert footprint is not None and body is not None
    pieces = view3d._module_pieces(body, footprint, comp, session.document.board)
    strips = [p for p in pieces if p.rgb == view3d._HEADER_PLASTIC_RGB]
    assert len(strips) == 2
    pcb = pieces[0]
    assert pcb.position[2] == pytest.approx(8.5 + MODULE_PCB_MM / 2)


def test_sparse_pins_stand_on_posts_not_on_a_strip() -> None:
    from perfboard_studio.ui import view3d

    session = _board_with("mod-4x1-p3-r1-40x10x3-s8.5", {})
    comp = session.document.components[0]
    footprint = session.lookup(comp.footprint_id)
    body = view3d._world_body(session.lookup, comp, session.document.board)
    assert footprint is not None and body is not None
    pieces = view3d._module_pieces(body, footprint, comp, session.document.board)
    assert len([p for p in pieces if p.rgb == view3d._HEADER_PLASTIC_RGB]) == 4


def test_pin_names_are_one_actor_and_the_view_can_leave_them_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without Qt, where the vector glyphs are all one actor. (With Qt each name is its own
    decal -- ``test_pin_name_layout``.)"""
    from perfboard_studio.ui import view3d

    monkeypatch.setattr(view3d, "_label_decal", lambda *args, **kwargs: None)
    session = _board_with(DEVKITC, {"1": "3V3", "2": "GND"})
    comp = session.document.components[0]
    assert len(view3d.build_pin_names(session.lookup, comp, session.document.board)) == 1

    on = vtk.vtkRenderer()
    off = vtk.vtkRenderer()
    view3d.populate_renderer(on, session.document, session.lookup)
    view3d.populate_renderer(off, session.document, session.lookup, pin_names=False)
    assert on.GetActors().GetNumberOfItems() == off.GetActors().GetNumberOfItems() + 1


def test_names_off_a_module_sit_on_a_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """White ink across white pad rings is unreadable, so a name on this board has a dark
    tag under it -- a second actor, where the glyphs are vector (no Qt)."""
    from perfboard_studio.ui import view3d

    monkeypatch.setattr(view3d, "_label_decal", lambda *args, **kwargs: None)
    session = BoardSession(document=new_board(cols=30, rows=20))
    assert session.place_component("", "", "E6", part="ne555")["ok"]
    comp = session.document.components[0]
    assert len(view3d.build_pin_names(session.lookup, comp, session.document.board)) == 2
