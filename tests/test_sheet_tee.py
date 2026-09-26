"""A T on the sheet: a pin wired onto a wire already drawn (``SheetWire.tap``).

What is pinned: a T joins its pin to the net of the wire it lands on, and says nothing else
about the circuit; it round-trips through the file, and a sheet without one is written as it
always was; it is refused when there is no drawn wire to land on or when it would branch a
wire off itself; it is drawn ON its wire with a dot, and stays on it when either wire's
symbols move; rubbing out a wire takes the T's off it with it, in one undo step; and a T whose
wire is no longer drawn goes to its pin instead.
"""

from __future__ import annotations

import dataclasses
import itertools

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    AddPartPayload,
    DeleteSheetWiresPayload,
    DisconnectPinsPayload,
    DrawSheetWirePayload,
    MoveSymbolsPayload,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import DocumentMeta, NetNode, Point2, SheetWire, SymbolPlacement
from perfboard_studio.schematic import SchematicDrawing, build_schematic, pin_position

LOOKUP = footprint_lookup()


def _pin(ref: str, pin: str) -> NetNode:
    return NetNode(component_ref=ref, pin=pin)


def _bus() -> CommandBus:
    """R1 and R2 side by side, R3 and R4 below them, every symbol placed by hand."""
    bus = CommandBus(
        create_empty_document(DocumentMeta(name="t", created="", modified="")),
        create_standard_registry(),
        CommandContext(next_id=create_id_generator()),
    )
    for ref in ("R1", "R2", "R3", "R4"):
        assert bus.dispatch("part.add", AddPartPayload(ref=ref, footprint_id="r-axial-3")).ok
    ids = {part.ref: part.id for part in bus.document.parts}
    where = {"R1": (20.32, 20.32), "R2": (60.96, 20.32), "R3": (35.56, 40.64), "R4": (5.08, 50.8)}
    placed = MoveSymbolsPayload(
        placements=tuple(
            SymbolPlacement(id=ids[ref], at=Point2(x=x, y=y)) for ref, (x, y) in where.items()
        )
    )
    assert bus.dispatch("symbol.move", placed).ok
    return bus


def _drawing(bus: CommandBus) -> SchematicDrawing:
    return build_schematic(bus.document, LOOKUP)


def _at(drawing: SchematicDrawing, ref: str, pin: str) -> Point2:
    point = pin_position(drawing, ref, pin)
    assert point is not None
    return point


def _wire(bus: CommandBus, a: NetNode, b: NetNode) -> None:
    """A wire from pin to pin, turning once, horizontal first -- as the tool draws it."""
    drawing = _drawing(bus)
    start, end = _at(drawing, a.component_ref, a.pin), _at(drawing, b.component_ref, b.pin)
    path = (start, end) if start.y == end.y or start.x == end.x else (
        start, Point2(x=end.x, y=start.y), end
    )
    result = bus.dispatch("sheet.wire", DrawSheetWirePayload(wire=SheetWire(a=a, b=b, path=path)))
    assert result.ok, result.message


def _host_path(bus: CommandBus, ends: tuple[NetNode, NetNode]) -> tuple[Point2, ...]:
    return next(w.path for w in _drawing(bus).wires if w.ends == ends)


def _tee(bus: CommandBus, pin: NetNode, onto: tuple[NetNode, NetNode], fraction: float = 0.5):
    """A T from ``pin`` onto the drawn wire ``onto``, part of the way along its longest run,
    with its last run across the wire."""
    host = _host_path(bus, onto)
    runs = list(itertools.pairwise(host))
    start, end = max(runs, key=lambda r: abs(r[1].x - r[0].x) + abs(r[1].y - r[0].y))
    at = Point2(
        x=round(start.x + (end.x - start.x) * fraction, 2),
        y=round(start.y + (end.y - start.y) * fraction, 2),
    )
    source = _at(_drawing(bus), pin.component_ref, pin.pin)
    horizontal = start.y == end.y
    corner = Point2(x=at.x, y=source.y) if horizontal else Point2(x=source.x, y=at.y)
    wire = SheetWire(a=pin, b=onto[0], path=(source, corner, at), tap=onto[1])
    return bus.dispatch("sheet.wire", DrawSheetWirePayload(wire=wire)), at


def test_a_tee_joins_its_pin_to_the_net_of_the_wire_it_lands_on() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    result, at = _tee(bus, _pin("R3", "1"), (_pin("R1", "2"), _pin("R2", "1")))
    assert result.ok, result.message
    (net,) = bus.document.nets
    assert set(net.nodes) == {_pin("R1", "2"), _pin("R2", "1"), _pin("R3", "1")}
    assert "onto the wire from R1.2 to R2.1" in result.description

    drawing = _drawing(bus)
    branch = next(w for w in drawing.wires if w.ends == (_pin("R3", "1"), _pin("R1", "2")))
    assert branch.path[0] == _at(drawing, "R3", "1") and branch.path[-1] == at
    # A dot at the T, where one line meets another in the middle.
    assert any(j.at == at and j.net_id == net.id for j in drawing.junctions)
    # And R3.1 is drawn, so it is not also named by a label.
    assert not any(label.kind == "net" for label in drawing.labels)


def test_a_tee_round_trips_and_a_sheet_without_one_is_written_as_it_was() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    plain = persist.serialize_document(bus.document)
    assert '"tap"' not in plain
    _tee(bus, _pin("R3", "1"), (_pin("R1", "2"), _pin("R2", "1")))
    text = persist.serialize_document(bus.document)
    assert '"tap"' in text
    loaded = persist.parse_document_or_throw(text)
    assert loaded.sheet_wires == bus.document.sheet_wires
    assert persist.serialize_document(loaded) == text


def test_a_tee_needs_a_drawn_wire_that_is_not_its_own() -> None:
    bus = _bus()
    missing = _tee_onto_nothing(bus)
    assert not missing.ok and missing.code == "no-such-wire"
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    own = bus.dispatch(
        "sheet.wire",
        DrawSheetWirePayload(
            wire=SheetWire(
                a=_pin("R2", "1"),
                b=_pin("R1", "2"),
                path=(Point2(x=0.0, y=0.0), Point2(x=5.0, y=0.0)),
                tap=_pin("R2", "1"),
            )
        ),
    )
    assert not own.ok and own.code == "same-pin"


def _tee_onto_nothing(bus: CommandBus):  # type: ignore[no-untyped-def]
    wire = SheetWire(
        a=_pin("R3", "1"),
        b=_pin("R1", "2"),
        path=(Point2(x=0.0, y=0.0), Point2(x=5.0, y=0.0)),
        tap=_pin("R2", "1"),
    )
    return bus.dispatch("sheet.wire", DrawSheetWirePayload(wire=wire))


def test_a_tee_stays_on_its_wire_when_the_symbols_move() -> None:
    """A symbol drags only the end runs of its wires; a T in the middle of one stays put,
    and a T whose own pin moves still ends on the wire."""
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    _result, at = _tee(bus, _pin("R3", "1"), (_pin("R1", "2"), _pin("R2", "1")))
    ids = {part.ref: part.id for part in bus.document.parts}
    for ref, dx, dy in (("R3", 7.62, 5.08), ("R2", 0.0, 2.54), ("R1", -5.08, 0.0)):
        now = next(p for p in bus.document.sheet if p.id == ids[ref])
        moved = SymbolPlacement(id=now.id, at=Point2(x=now.at.x + dx, y=now.at.y + dy))
        assert bus.dispatch("symbol.move", MoveSymbolsPayload(placements=(moved,))).ok
        drawing = _drawing(bus)
        host = _host_path(bus, (_pin("R1", "2"), _pin("R2", "1")))
        branch = next(w for w in drawing.wires if w.ends == (_pin("R3", "1"), _pin("R1", "2")))
        tee = branch.path[-1]
        on_host = any(
            min(s.x, e.x) - 1e-9 <= tee.x <= max(s.x, e.x) + 1e-9
            and min(s.y, e.y) - 1e-9 <= tee.y <= max(s.y, e.y) + 1e-9
            for s, e in itertools.pairwise(host)
        )
        assert on_host, (ref, tee, host)
        assert branch.path[0] == _at(drawing, "R3", "1")
        for s, e in itertools.pairwise(branch.path):
            assert s.x == pytest.approx(e.x) or s.y == pytest.approx(e.y)
        # The T was in the middle of the wire, and only its end runs move.
        if ref != "R3":
            assert tee == at


def test_a_tee_can_land_on_a_tee() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    _tee(bus, _pin("R3", "1"), (_pin("R1", "2"), _pin("R2", "1")))
    result, at = _tee(bus, _pin("R4", "2"), (_pin("R3", "1"), _pin("R1", "2")), fraction=0.5)
    assert result.ok, result.message
    (net,) = bus.document.nets
    assert _pin("R4", "2") in net.nodes
    branch = next(w for w in _drawing(bus).wires if w.ends == (_pin("R4", "2"), _pin("R3", "1")))
    assert branch.path[-1] == at


def test_rubbing_out_a_wire_takes_the_tees_off_it_in_one_step() -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    _tee(bus, _pin("R3", "1"), (_pin("R1", "2"), _pin("R2", "1")))
    _tee(bus, _pin("R4", "2"), (_pin("R3", "1"), _pin("R1", "2")))
    before = bus.document.sheet_wires
    host = next(w for w in before if w.tap is None)
    result = bus.dispatch("sheet.wire.delete", DeleteSheetWiresPayload(wires=(host,)))
    assert result.ok and "2 branch(es)" in result.description
    assert bus.document.sheet_wires == ()
    # The circuit is left alone: rubbing out is about the drawing.
    assert len(bus.document.nets[0].nodes) == 4
    bus.undo()
    assert bus.document.sheet_wires == before


def test_a_tee_whose_wire_is_no_longer_drawn_goes_to_its_pin() -> None:
    """R2.1 leaves the net: the wire from R1.2 to R2.1 is no longer drawn, and a T onto it
    would be a branch off nothing -- but R3.1 is still joined to R1.2, so it is drawn to it."""
    bus = _bus()
    _wire(bus, _pin("R1", "2"), _pin("R2", "1"))
    _tee(bus, _pin("R3", "1"), (_pin("R1", "2"), _pin("R2", "1")))
    net = bus.document.nets[0]
    assert bus.dispatch(
        "net.disconnect", DisconnectPinsPayload(id=net.id, nodes=(_pin("R2", "1"),))
    ).ok
    drawing = _drawing(bus)
    assert not any(w.ends == (_pin("R1", "2"), _pin("R2", "1")) for w in drawing.wires)
    branch = next(w for w in drawing.wires if w.ends == (_pin("R3", "1"), _pin("R1", "2")))
    assert branch.path[-1] == _at(drawing, "R1", "2")
    assert not any(j.at == branch.path[-1] for j in drawing.junctions)


def test_the_old_file_without_taps_reads_the_same() -> None:
    """Every wire drawn before T's existed is pin to pin: ``tap`` defaults to None."""
    wire = SheetWire(a=_pin("R1", "1"), b=_pin("R2", "1"), path=(Point2(x=0, y=0), Point2(x=1, y=0)))
    assert wire.tap is None and wire.host_pins is None
    assert dataclasses.replace(wire, tap=_pin("R3", "1")).host_pins == frozenset(
        (_pin("R2", "1"), _pin("R3", "1"))
    )
