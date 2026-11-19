"""Renaming a part carries the sheet with it (``commands.renamed_on_sheet``).

A drawn wire and a port's link name their pins by reference, as a net does. The rename
used to carry only the nets: R1 renamed R7 left every wire drawn to it naming R1, no net
held both its ends any more, and the sheet stopped drawing them -- each pin said by name
instead, with nothing to say why -- and every link to a ground or a supply was taken off.
"""

from __future__ import annotations

from perfboard_studio.command import CommandBus
from perfboard_studio.commands import UpdatePartPayload
from perfboard_studio.schematic import SchematicDrawing

from .test_sheet_ports import GROUND_AT
from .test_sheet_ports import _put as _put_port
from .test_sheet_tee import _bus, _drawing, _pin, _tee, _wire


def _rename(bus: CommandBus, was: str, now: str) -> None:
    (part,) = [p for p in bus.document.parts if p.ref == was]
    result = bus.dispatch("part.update", UpdatePartPayload(id=part.id, ref=now))
    assert result.ok, result.message


def _drawn(drawing: SchematicDrawing) -> list[tuple[tuple[str, ...], tuple[tuple[float, float], ...]]]:
    """Every drawn wire as its pins' numbers and its path -- what a rename must not move."""
    return sorted(
        (
            tuple(sorted(end.pin for end in wire.ends)),
            tuple((point.x, point.y) for point in wire.path),
        )
        for wire in drawing.wires
        if wire.ends is not None
    )


def test_a_renamed_part_keeps_the_wires_drawn_to_it() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    result, _at = _tee(bus, _pin("R3", "1"), (_pin("R1", "2"), _pin("R2", "1")))
    assert result.ok, result.message
    before = _drawing(bus)

    _rename(bus, "R1", "R7")
    after = _drawing(bus)

    assert _drawn(after) == _drawn(before)
    assert len(after.junctions) == len(before.junctions)
    assert not [label for label in after.labels if label.kind == "net"], "no pin said by name"
    assert {(w.a.component_ref, w.b.component_ref) for w in bus.document.sheet_wires} == {
        ("R7", "R2"), ("R3", "R7")
    }
    (tee,) = [w for w in bus.document.sheet_wires if w.tap is not None]
    assert tee.tap == _pin("R2", "1")


def test_a_renamed_part_keeps_its_links_to_a_ground() -> None:
    bus = _bus()
    _put_port(bus, "ground", "GND", (_pin("R1", "2"), _pin("R2", "2")), GROUND_AT)

    _rename(bus, "R1", "R7")

    (ground,) = bus.document.sheet_ports
    assert {link.pin for link in ground.links} == {_pin("R7", "2"), _pin("R2", "2")}
    assert len(_drawing(bus).rails) == 1, "one ground, and no glyph of its own at R7's pin"


def test_the_rename_and_the_drawing_are_one_undo_step() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    before = bus.document
    _rename(bus, "R1", "R7")
    assert bus.undo() and bus.document == before
