"""Pin names laid out against the whole board (``bodies.lay_out_pin_names``).

What is pinned: a part alone is printed exactly as ``pin_labels`` has it; a part in one row
turns its names round when the other side is clear; a name with too little room is
narrowed, and one with none is left off and reported -- never printed under a body, across
a terminal's mouth, over a screw head, past the edge of the board or over another name; and
the 3D view prints a name in Turkish as it was typed.

The first board laid out with this program is the case the layout was written for: two
terminals side by side, each one's names printed under the other's body.
"""

from __future__ import annotations

import os
import random

import pytest

from perfboard_studio.drc import placed_body_box, placed_entry
from perfboard_studio.geometry import mounting_hole_centre_mm, substrate_edges_mm
from perfboard_studio.mcp.session import BoardSession, new_board
from perfboard_studio.ui.bodies import (
    PIN_NAME_MIN_SQUEEZE,
    BoardBox,
    PrintedPinNames,
    _run_on_board,
    _tag_box,
    lay_out_pin_names,
    pin_labels,
)


def _measure(name: str) -> float:
    """A font-free measure: every character the same width."""
    return len(name) * 0.65


def _session(cols: int = 30, rows: int = 20) -> BoardSession:
    return BoardSession(document=new_board(cols=cols, rows=rows))


def _place(session: BoardSession, ref: str, footprint: str, hole: str, rotation: int = 0,
           names: dict[str, str] | None = None, part: str = "") -> str:
    result = session.place_component(
        ref, footprint, hole, rotation=rotation, pin_names=names, part=part
    )
    assert result["ok"], result
    return next(c.id for c in session.document.components if c.ref == (ref or c.ref))


def _laid_out(session: BoardSession) -> PrintedPinNames:
    return lay_out_pin_names(session.document, session.lookup, _measure)


def test_a_part_alone_is_printed_as_it_would_be_anyway() -> None:
    session = _session()
    comp_id = _place(session, "U1", "", "J10", part="ne555")
    comp = session.document.components[0]
    footprint = session.lookup(comp.footprint_id)
    assert footprint is not None
    printed = _laid_out(session)
    assert printed.labels[comp_id] == pin_labels(footprint, comp, session.document.board.pitch)
    assert printed.left_off == {}


def test_the_first_real_board_two_terminals_side_by_side() -> None:
    """The DELTA-ATLAS plaket's J1 and J6, where they stand on it. J6 feeds its wires from
    above, so its names may go either side and go to the clear one; J1's mouth faces the
    board's edge, so its names can only go behind it -- under J6 -- and are left off."""
    session = _session(cols=27, rows=35)
    j1 = _place(session, "J1", "screw-terminal-4", "Z10", rotation=270,
                names={"1": "CAN_H", "2": "CAN_L", "3": "CAN_GND", "4": "24V-L"})
    j6 = _place(session, "J6", "screw-terminal-3-v", "U10", rotation=270,
                names={"1": "INT_GATE", "2": "VMOT_SENSE", "3": "GND"})
    printed = _laid_out(session)

    j6_names = printed.labels[j6]
    assert len(j6_names) == 3 and j6 not in printed.left_off
    # Turned round, all three the same way.
    alone = pin_labels(session.lookup("screw-terminal-3-v"), session.document.components[1], 2.54)  # type: ignore[arg-type]
    assert {(n.dx, n.dy) for n in j6_names} == {(-alone[0].dx, -alone[0].dy)}

    # J1's top pin clears J6's body; the other three run straight into it.
    assert [n.name for n in printed.labels[j1]] == ["24V-L"]
    assert printed.left_off[j1] == (("1", "CAN_H"), ("2", "CAN_L"), ("3", "CAN_GND"))


def test_a_name_with_a_little_too_little_room_is_narrowed_and_with_none_left_off() -> None:
    """A one-pin header's name runs down the board. Resistors lying across its path three
    rows above and below leave it about four fifths of what it needs, either way: narrowed.
    Two rows away they leave it well under the squeeze limit: left off."""
    need = _measure("ABCDEFGH")
    for rows_away, fits in ((3, True), (2, False)):
        session = _session()
        header = _place(session, "J1", "hdr-1x1", "E6", names={"1": "ABCDEFGH"})
        # r-axial-4 spans four columns from its anchor, so C centres it on E.
        _place(session, "R1", "r-axial-4", f"C{6 + rows_away}")
        _place(session, "R2", "r-axial-4", f"C{6 - rows_away}")
        printed = _laid_out(session)
        if fits:
            (narrowed,) = printed.labels[header]
            assert need * PIN_NAME_MIN_SQUEEZE <= narrowed.room < need
            assert header not in printed.left_off
        else:
            assert header not in printed.labels
            assert printed.left_off[header] == (("1", "ABCDEFGH"),)


# ----------------------------------------------------------- nothing is printed under anything


def _obstacles(session: BoardSession, owner: str) -> list[BoardBox]:
    board = session.document.board
    boxes: list[BoardBox] = []
    for comp in session.document.components:
        if comp.id == owner:
            continue
        footprint = session.lookup(comp.footprint_id)
        assert footprint is not None
        boxes.append(placed_body_box(comp, footprint, board))
        entry = placed_entry(comp, footprint, board)
        if entry is not None:
            boxes.append(entry[0])
    for mount in session.document.mounting_holes:
        centre = mounting_hole_centre_mm(mount, board)
        r = max(mount.head_diameter, mount.diameter) / 2
        boxes.append((centre.x - r, centre.x + r, centre.y - r, centre.y + r))
    return boxes


def _overlap(a: BoardBox, b: BoardBox) -> bool:
    eps = 1e-6
    return a[0] < b[1] - eps and b[0] < a[1] - eps and a[2] < b[3] - eps and b[2] < a[3] - eps


PARTS = ["ne555", "lm358", "bc547", "irf9540n", "7805", "1n4007"]
TERMINALS = ["screw-terminal-2", "screw-terminal-4", "screw-terminal-3-v", "hdr-1x4"]


@pytest.mark.parametrize("seed", range(6))
def test_on_a_crowded_board_no_name_is_printed_under_anything(seed: int) -> None:
    rng = random.Random(seed)
    session = _session(cols=24, rows=18)
    session.add_mounting_hole("A1")
    for index in range(40):
        hole = f"{chr(ord('A') + rng.randrange(24))}{rng.randrange(1, 19)}"
        rotation = rng.choice([0, 90, 180, 270])
        if rng.random() < 0.5:
            session.place_component("", "", hole, rotation=rotation, part=rng.choice(PARTS))
        else:
            footprint = rng.choice(TERMINALS)
            packaged = session.lookup(footprint)
            assert packaged is not None
            names = {pin.number: f"SIG{index}_{pin.number}" for pin in packaged.pins}
            session.place_component(
                f"J{index}", footprint, hole, rotation=rotation, pin_names=names
            )
    board = session.document.board
    edges = substrate_edges_mm(board)
    printed = _laid_out(session)
    assert printed.labels, "the board should have something printed on it"

    tags: list[tuple[str, BoardBox]] = []
    for comp in session.document.components:
        for label in printed.labels.get(comp.id, ()):
            if label.on_module:
                continue
            box = _tag_box(
                _run_on_board(label, comp, board, 1.0),
                label.start,
                min(_measure(label.name), label.room),
            )
            assert edges.min_x <= box[0] and box[1] <= edges.max_x, (comp.ref, label.name)
            assert edges.min_y <= box[2] and box[3] <= edges.max_y, (comp.ref, label.name)
            for obstacle in _obstacles(session, comp.id):
                assert not _overlap(box, obstacle), (comp.ref, label.name, obstacle)
            tags.append((f"{comp.ref}.{label.number}", box))
    for i, (name_a, a) in enumerate(tags):
        for name_b, b in tags[i + 1 :]:
            assert not _overlap(a, b), (name_a, name_b)


# ------------------------------------------------------------------------- 2D


def test_the_editor_says_which_names_it_had_no_room_for() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.view2d import BoardScene

    _app = QApplication.instance() or QApplication(["perfboard-studio-tests"])
    session = _session(cols=27, rows=35)
    _place(session, "J1", "screw-terminal-4", "Z10", rotation=270,
           names={"1": "CAN_H", "2": "CAN_L", "3": "CAN_GND", "4": "24V-L"})
    _place(session, "J6", "screw-terminal-3-v", "U10", rotation=270,
           names={"1": "INT_GATE", "2": "VMOT_SENSE", "3": "GND"})
    scene = BoardScene(session.document, session.lookup, side="top")
    j1 = next(item for item in scene.component_items.values() if item.comp.ref == "J1")
    assert "CAN_GND" in j1.toolTip() and "24V-L" not in j1.toolTip()
    assert [label.name for label in j1.pin_names] == ["24V-L"]
    # And the item's bounds cover the names it prints, so a drag repaints them.
    j6 = next(item for item in scene.component_items.values() if item.comp.ref == "J6")
    assert j6.boundingRect().contains(j6._names_rect)
    scene.set_show_pin_names(False)
    j1 = next(item for item in scene.component_items.values() if item.comp.ref == "J1")
    assert "CAN_GND" not in j1.toolTip()


# ------------------------------------------------------------------------- 3D

vtk = pytest.importorskip("vtk")


def test_a_name_in_turkish_is_printed_as_typed_in_3d() -> None:
    """Drawn by Qt, as a board label is: a textured decal per name, which is how "GİRİŞ"
    comes out with its dots rather than as "GR"."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui import view3d

    _app = QApplication.instance() or QApplication(["perfboard-studio-tests"])
    session = _session()
    _place(session, "J1", "screw-terminal-2", "E5", names={"1": "GİRİŞ", "2": "ÇIKIŞ"})
    comp = session.document.components[0]
    actors = view3d.build_pin_names(session.lookup, comp, session.document.board)
    assert len(actors) == 2
    assert all(actor.GetTexture() is not None for actor in actors)
    # Laid flat on the board, above the pads, never in them.
    for actor in actors:
        bounds = actor.GetMapper().GetInput().GetBounds()
        assert bounds[4] == pytest.approx(bounds[5]) and bounds[4] > 0.1


def test_without_qt_vector_glyphs_stand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from perfboard_studio.ui import view3d

    monkeypatch.setattr(view3d, "_label_decal", lambda *args, **kwargs: None)
    session = _session()
    _place(session, "J1", "screw-terminal-2", "E5", names={"1": "IN", "2": "OUT"})
    comp = session.document.components[0]
    # One actor of glyphs, one of tags under them.
    assert len(view3d.build_pin_names(session.lookup, comp, session.document.board)) == 2


def test_3d_leaves_off_what_2d_leaves_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer lays the board out once and prints only what found room."""
    from perfboard_studio.ui import view3d

    monkeypatch.setattr(view3d, "_label_decal", lambda *args, **kwargs: None)
    seen: list[int] = []
    original = view3d.build_pin_names

    def counting(lookup, comp, board, labels=None):  # type: ignore[no-untyped-def]
        seen.append(len(labels or ()))
        return original(lookup, comp, board, labels)

    monkeypatch.setattr(view3d, "build_pin_names", counting)
    session = _session(cols=27, rows=35)
    _place(session, "J1", "screw-terminal-4", "Z10", rotation=270,
           names={"1": "CAN_H", "2": "CAN_L", "3": "CAN_GND", "4": "24V-L"})
    _place(session, "J6", "screw-terminal-3-v", "U10", rotation=270,
           names={"1": "INT_GATE", "2": "VMOT_SENSE", "3": "GND"})
    view3d.populate_renderer(vtk.vtkRenderer(), session.document, session.lookup)
    assert sorted(seen) == [1, 3]
