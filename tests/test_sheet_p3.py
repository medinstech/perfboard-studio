"""P3: Free (loose) wires and KiCad-style G-stretch on the schematic sheet."""

from __future__ import annotations

import os

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    AddLooseWirePayload,
    AddPartPayload,
    AddSheetPortPayload,
    AutoSymbolsPayload,
    DeleteLooseWiresPayload,
    DrawSheetWirePayload,
    ExtendLooseWirePayload,
    MoveSymbolsPayload,
    ReconnectSheetWirePayload,
    ReshapeLooseWirePayload,
    UpdatePartPayload,
    create_document_id_generator,
    create_empty_document,
    create_standard_registry,
    design_on_a_new_board,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import (
    DocumentMeta,
    NetNode,
    Point2,
    PortLink,
    SheetWire,
    SymbolPlacement,
)
from perfboard_studio.schematic import (
    GRID_MM,
    SchematicDrawing,
    build_schematic,
    loose_wires_after_move,
    pin_position,
    ports_after_move,
    wires_after_move,
)
from perfboard_studio.schematic_export import drawing_to_svg

LOOKUP = footprint_lookup()


def _pin(ref: str, pin: str) -> NetNode:
    return NetNode(component_ref=ref, pin=pin)


def _p(x: float, y: float) -> Point2:
    return Point2(x=x, y=y)


def _bus() -> CommandBus:
    """R1, R2, R3 placed by hand on the sheet."""
    bus = CommandBus(
        create_empty_document(DocumentMeta(name="p3", created="", modified="")),
        create_standard_registry(),
        CommandContext(next_id=create_id_generator()),
    )
    for ref in ("R1", "R2", "R3"):
        assert bus.dispatch("part.add", AddPartPayload(ref=ref, footprint_id="r-axial-3")).ok
    ids = {part.ref: part.id for part in bus.document.parts}
    where = {"R1": (20.32, 20.32), "R2": (60.96, 20.32), "R3": (40.64, 45.72)}
    placed = MoveSymbolsPayload(
        placements=tuple(
            SymbolPlacement(id=ids[ref], at=_p(x, y)) for ref, (x, y) in where.items()
        )
    )
    assert bus.dispatch("symbol.move", placed).ok
    return bus


def _drawing(bus: CommandBus) -> SchematicDrawing:
    return build_schematic(bus.document, LOOKUP)


def _pin_at(bus: CommandBus, ref: str, pin: str) -> Point2:
    pos = pin_position(_drawing(bus), ref, pin)
    assert pos is not None
    return pos


def _ortho(start: Point2, end: Point2) -> tuple[Point2, ...]:
    if abs(start.x - end.x) < 1e-6 or abs(start.y - end.y) < 1e-6:
        return (start, end)
    return (start, _p(end.x, start.y), end)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_loose_wire_round_trip_and_omission_when_empty() -> None:
    bus = _bus()
    raw_empty = persist.serialize_document(bus.document)
    assert '"sheetLooseWires"' not in raw_empty

    # Connect R1.2 -> R2.1 and add a GND port so we can anchor all 4 LooseWire kinds.
    p12 = _pin_at(bus, "R1", "2")
    p21 = _pin_at(bus, "R2", "1")
    assert bus.dispatch(
        "sheet.wire",
        DrawSheetWirePayload(wire=SheetWire(a=_pin("R1", "2"), b=_pin("R2", "1"), path=(p12, p21))),
    ).ok
    gnd_at = _p(20.32, 40.64)
    assert bus.dispatch(
        "sheet.port.add", AddSheetPortPayload(kind="ground", name="GND", at=gnd_at)
    ).ok
    port_id = bus.document.sheet_ports[0].id

    p11 = _pin_at(bus, "R1", "1")
    mid = _p(50.80, p12.y)
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(path=(p11, _p(p11.x - 10.16, p11.y)), pin=_pin("R1", "1")),
    ).ok
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(
            path=(mid, _p(mid.x, mid.y + 10.16)), on=(_pin("R1", "2"), _pin("R2", "1"))
        ),
    ).ok
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(path=(gnd_at, _p(gnd_at.x + 10.16, gnd_at.y)), port=port_id),
    ).ok
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(path=(_p(10.16, 10.16), _p(20.32, 10.16))),
    ).ok

    text = persist.serialize_document(bus.document)
    assert '"sheetLooseWires"' in text
    reopened = persist.parse_document_or_throw(text)
    assert reopened == bus.document
    assert persist.serialize_document(reopened) == text

    # Reopened document seeds id generator past existing loose-* ids.
    seeded = CommandBus(
        reopened,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(reopened)),
    )
    res = seeded.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(path=(_p(5.08, 5.08), _p(15.24, 5.08))),
    )
    assert res.ok, res.message
    assert len(seeded.document.sheet_loose_wires) == 5


def test_loose_wire_parse_validation() -> None:
    bus = _bus()
    base = persist.serialize_document(bus.document)

    # Two start anchors refused.
    import json

    data = json.loads(base)
    data["sheetLooseWires"] = [
        {
            "id": "loose-1",
            "path": [{"x": 0, "y": 0}, {"x": 5.08, "y": 0}],
            "pin": {"componentRef": "R1", "pin": "1"},
            "port": "port-1",
        }
    ]
    with pytest.raises(ValueError, match="one thing at most"):
        persist.parse_document_or_throw(json.dumps(data))

    # Too few points refused.
    data["sheetLooseWires"] = [{"id": "loose-1", "path": [{"x": 0, "y": 0}]}]
    with pytest.raises(ValueError, match="at least two points"):
        persist.parse_document_or_throw(json.dumps(data))

    # Duplicate ids refused.
    data["sheetLooseWires"] = [
        {"id": "loose-1", "path": [{"x": 0, "y": 0}, {"x": 5.08, "y": 0}]},
        {"id": "loose-1", "path": [{"x": 0, "y": 5.08}, {"x": 5.08, "y": 5.08}]},
    ]
    with pytest.raises(ValueError, match="share the id"):
        persist.parse_document_or_throw(json.dumps(data))


# ---------------------------------------------------------------------------
# Commands & Undo
# ---------------------------------------------------------------------------


def test_loose_wire_add_reshape_delete_never_touches_nets() -> None:
    bus = _bus()
    p12 = _pin_at(bus, "R1", "2")
    end = _p(p12.x + 10.16, p12.y)
    res = bus.dispatch("sheet.loose.add", AddLooseWirePayload(path=(p12, end), pin=_pin("R1", "2")))
    assert res.ok, res.message
    assert bus.document.nets == ()
    assert len(bus.document.sheet_loose_wires) == 1
    lid = bus.document.sheet_loose_wires[0].id

    # Diagonal rejected.
    bad = bus.dispatch(
        "sheet.loose.reshape",
        ReshapeLooseWirePayload(id=lid, path=(p12, _p(end.x + 2.54, end.y + 2.54))),
    )
    assert not bad.ok and bad.code == "diagonal-wire"

    # Orthogonal reshape + undo.
    bent = (p12, _p(end.x, p12.y), _p(end.x, p12.y + 5.08))
    assert bus.dispatch("sheet.loose.reshape", ReshapeLooseWirePayload(id=lid, path=bent)).ok
    assert bus.document.sheet_loose_wires[0].path == bent
    assert bus.undo()
    assert bus.document.sheet_loose_wires[0].path == (p12, end)
    assert bus.redo()

    # Delete + undo.
    assert bus.dispatch("sheet.loose.delete", DeleteLooseWiresPayload(ids=(lid,))).ok
    assert bus.document.sheet_loose_wires == ()
    assert bus.undo()
    assert len(bus.document.sheet_loose_wires) == 1


def test_extending_loose_wire_onto_pin_wire_or_port_joins_in_one_undo_step() -> None:
    bus = _bus()
    p12 = _pin_at(bus, "R1", "2")
    p21 = _pin_at(bus, "R2", "1")
    p31 = _pin_at(bus, "R3", "1")
    p32 = _pin_at(bus, "R3", "2")

    # 1. Pin-started loose wire extended onto second pin -> SheetWire + Net in one undo.
    mid = _p(p12.x + 10.16, p12.y)
    assert bus.dispatch("sheet.loose.add", AddLooseWirePayload(path=(p12, mid), pin=_pin("R1", "2"))).ok
    lid = bus.document.sheet_loose_wires[0].id
    before_extend = bus.document
    res = bus.dispatch(
        "sheet.loose.extend",
        ExtendLooseWirePayload(id=lid, path=(p12, p21), to_pin=_pin("R2", "1")),
    )
    assert res.ok, res.message
    assert bus.document.sheet_loose_wires == ()
    assert len(bus.document.sheet_wires) == 1
    assert len(bus.document.nets) == 1
    assert set(bus.document.nets[0].nodes) == {_pin("R1", "2"), _pin("R2", "1")}
    assert bus.undo() and bus.document == before_extend
    assert bus.redo()

    # 2. Pin-started loose wire extended onto drawn wire -> T-branch in one undo.
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(path=(p31, _p(p31.x, p31.y - 5.08)), pin=_pin("R3", "1")),
    ).ok
    lid_t = bus.document.sheet_loose_wires[0].id
    tap_pt = _p(p31.x, p12.y)
    assert bus.dispatch(
        "sheet.loose.extend",
        ExtendLooseWirePayload(
            id=lid_t, path=(p31, tap_pt), to_on=(_pin("R1", "2"), _pin("R2", "1"))
        ),
    ).ok
    assert bus.document.sheet_loose_wires == ()
    assert len(bus.document.sheet_wires) == 2
    assert set(bus.document.nets[0].nodes) == {_pin("R1", "2"), _pin("R2", "1"), _pin("R3", "1")}

    # 3. Port-started loose wire extended onto pin -> PortLink + GND net in one undo.
    gnd_at = _p(p32.x + 10.16, p32.y)
    assert bus.dispatch(
        "sheet.port.add", AddSheetPortPayload(kind="ground", name="GND", at=gnd_at)
    ).ok
    port_id = bus.document.sheet_ports[0].id
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(path=(gnd_at, _p(gnd_at.x - 5.08, gnd_at.y)), port=port_id),
    ).ok
    lid_p = bus.document.sheet_loose_wires[0].id
    assert bus.dispatch(
        "sheet.loose.extend",
        ExtendLooseWirePayload(id=lid_p, path=(gnd_at, p32), to_pin=_pin("R3", "2")),
    ).ok
    assert bus.document.sheet_loose_wires == ()
    assert len(bus.document.sheet_ports[0].links) == 1
    assert bus.document.sheet_ports[0].links[0].pin == _pin("R3", "2")
    assert any(n.name == "GND" and _pin("R3", "2") in n.nodes for n in bus.document.nets)


def test_extending_bare_sheet_loose_wire_anchors_first_end() -> None:
    bus = _bus()
    p12 = _pin_at(bus, "R1", "2")
    start = _p(p12.x + 10.16, p12.y)
    assert bus.dispatch(
        "sheet.loose.add", AddLooseWirePayload(path=(start, _p(start.x - 5.08, start.y)))
    ).ok
    lid = bus.document.sheet_loose_wires[0].id
    assert bus.dispatch(
        "sheet.loose.extend",
        ExtendLooseWirePayload(id=lid, path=(start, p12), to_pin=_pin("R1", "2")),
    ).ok
    (lw,) = bus.document.sheet_loose_wires
    assert lw.pin == _pin("R1", "2")
    assert lw.path == (p12, start)
    assert bus.document.nets == ()


def test_rename_reconnect_auto_and_new_board_handle_loose_wires() -> None:
    bus = _bus()
    p12 = _pin_at(bus, "R1", "2")
    p21 = _pin_at(bus, "R2", "1")
    p31 = _pin_at(bus, "R3", "1")
    assert bus.dispatch(
        "sheet.wire",
        DrawSheetWirePayload(wire=SheetWire(a=_pin("R1", "2"), b=_pin("R2", "1"), path=(p12, p21))),
    ).ok
    mid = _p(50.80, p12.y)
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(path=(p12, _p(p12.x, p12.y + 5.08)), pin=_pin("R1", "2")),
    ).ok
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(
            path=(mid, _p(mid.x, mid.y + 5.08)), on=(_pin("R1", "2"), _pin("R2", "1"))
        ),
    ).ok

    # Rename R1 -> R7 carries both loose.pin and loose.on.
    r1 = next(p for p in bus.document.parts if p.ref == "R1")
    assert bus.dispatch("part.update", UpdatePartPayload(id=r1.id, ref="R7")).ok
    pins = {w.pin for w in bus.document.sheet_loose_wires if w.pin is not None}
    ons = {w.on for w in bus.document.sheet_loose_wires if w.on is not None}
    assert pins == {_pin("R7", "2")}
    assert ons == {(_pin("R7", "2"), _pin("R2", "1"))}

    # Reconnect R2.1 -> R3.1 carries loose.on.
    assert bus.dispatch(
        "sheet.wire.reconnect",
        ReconnectSheetWirePayload(
            a=_pin("R7", "2"),
            b=_pin("R2", "1"),
            end=_pin("R2", "1"),
            to=_pin("R3", "1"),
            path=_ortho(p12, p31),
        ),
    ).ok
    ons_after = {w.on for w in bus.document.sheet_loose_wires if w.on is not None}
    assert ons_after == {(_pin("R7", "2"), _pin("R3", "1"))}

    # design_on_a_new_board preserves loose wires.
    carried = design_on_a_new_board(bus.document, DocumentMeta(name="copy", created="", modified=""))
    assert carried.sheet_loose_wires == bus.document.sheet_loose_wires

    # Whole-sheet symbol.auto clears loose wires.
    assert bus.dispatch("symbol.auto", AutoSymbolsPayload()).ok
    assert bus.document.sheet_loose_wires == ()


# ---------------------------------------------------------------------------
# Schematic drawing, SVG export & move stretching
# ---------------------------------------------------------------------------


def test_schematic_draws_free_wires_junctions_notes_and_svg() -> None:
    bus = _bus()
    p12 = _pin_at(bus, "R1", "2")
    p21 = _pin_at(bus, "R2", "1")
    assert bus.dispatch(
        "sheet.wire",
        DrawSheetWirePayload(wire=SheetWire(a=_pin("R1", "2"), b=_pin("R2", "1"), path=(p12, p21))),
    ).ok
    mid = _p(50.80, p12.y)
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(
            path=(mid, _p(mid.x, mid.y + 10.16)), on=(_pin("R1", "2"), _pin("R2", "1"))
        ),
    ).ok
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(path=(_p(10.16, 10.16), _p(10.16, 15.24))),
    ).ok

    drawing = _drawing(bus)
    assert len(drawing.free_wires) == 2
    by_free_start = {fw.free_start: fw for fw in drawing.free_wires}
    assert False in by_free_start and True in by_free_start
    # Tee onto host wire middle produces a junction dot.
    assert any(j.at == mid for j in drawing.junctions)
    assert any("end on nothing" in note for note in drawing.notes)

    svg = drawing_to_svg(drawing)
    assert "<rect " in svg
    assert "end on nothing" in svg


def test_moving_symbol_stretches_wires_tees_loose_wires_and_port_links_in_one_step() -> None:
    bus = _bus()
    p11 = _pin_at(bus, "R1", "1")
    p12 = _pin_at(bus, "R1", "2")
    p21 = _pin_at(bus, "R2", "1")
    p31 = _pin_at(bus, "R3", "1")

    # Wire R1.2 -> R2.1 with an elbow, plus a T from R3.1 onto it, plus a loose wire off R1.1,
    # plus a GND port linked to R1.1.
    elbow_path = (p12, _p(50.80, p12.y), _p(50.80, p21.y), p21)
    assert bus.dispatch(
        "sheet.wire",
        DrawSheetWirePayload(wire=SheetWire(a=_pin("R1", "2"), b=_pin("R2", "1"), path=elbow_path)),
    ).ok
    assert bus.dispatch(
        "sheet.wire",
        DrawSheetWirePayload(
            wire=SheetWire(
                a=_pin("R3", "1"),
                b=_pin("R1", "2"),
                tap=_pin("R2", "1"),
                path=(p31, _p(50.80, p31.y), _p(50.80, p12.y)),
            )
        ),
    ).ok
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(
            path=(p11, _p(p11.x - 5.08, p11.y), _p(p11.x - 5.08, p11.y + 5.08)),
            pin=_pin("R1", "1"),
        ),
    ).ok
    gnd_at = _p(p11.x - 5.08, p11.y + 15.24)
    assert bus.dispatch(
        "sheet.port.add",
        AddSheetPortPayload(
            kind="ground",
            name="GND",
            at=gnd_at,
            links=(PortLink(pin=_pin("R1", "1"), path=(p11, _p(gnd_at.x, p11.y), gnd_at)),),
        ),
    ).ok

    r1_place = next(p for p in bus.document.sheet if p.id == bus.document.parts[0].id)
    moved_r1 = SymbolPlacement(
        id=r1_place.id,
        at=_p(r1_place.at.x, r1_place.at.y + 2 * GRID_MM),
        rotation=r1_place.rotation,
        mirrored=r1_place.mirrored,
    )
    stretched_wires = wires_after_move(bus.document, LOOKUP, (moved_r1,))
    stretched_loose = loose_wires_after_move(bus.document, LOOKUP, (moved_r1,))
    stretched_ports = ports_after_move(bus.document, LOOKUP, (moved_r1,))

    assert stretched_wires
    assert len(stretched_loose) == 1
    assert len(stretched_ports) == 1

    before = bus.document
    res = bus.dispatch(
        "symbol.move",
        MoveSymbolsPayload(
            placements=(moved_r1,),
            wires=stretched_wires,
            loose_wires=stretched_loose,
            ports=stretched_ports,
        ),
    )
    assert res.ok, res.message
    new_p11 = _pin_at(bus, "R1", "1")
    new_p12 = _pin_at(bus, "R1", "2")
    assert new_p12.y == pytest.approx(p12.y + 2 * GRID_MM)
    # Main wire stretched cleanly to new R1.2 while staying on R2.1.
    main_wire = next(w for w in bus.document.sheet_wires if w.tap is None)
    assert main_wire.path[0] == new_p12 and main_wire.path[-1] == p21
    # Loose wire stretched cleanly to new R1.1 while keeping its free end fixed.
    assert bus.document.sheet_loose_wires[0].path[0] == new_p11
    assert bus.document.sheet_loose_wires[0].path[-1] == _p(p11.x - 5.08, p11.y + 5.08)
    # Port link stretched cleanly to new R1.1 while keeping GND port fixed.
    assert bus.document.sheet_ports[0].links[0].path[0] == new_p11
    assert bus.document.sheet_ports[0].links[0].path[-1] == gnd_at

    # One undo restores symbol and every wire together.
    assert bus.undo() and bus.document == before


def test_moving_two_wired_symbols_together_translates_wire_rigidly() -> None:
    bus = _bus()
    p12 = _pin_at(bus, "R1", "2")
    p21 = _pin_at(bus, "R2", "1")
    u_path = (p12, _p(p12.x + 5.08, p12.y), _p(p12.x + 5.08, p12.y - 5.08), _p(p21.x - 5.08, p12.y - 5.08), _p(p21.x - 5.08, p21.y), p21)
    assert bus.dispatch(
        "sheet.wire",
        DrawSheetWirePayload(wire=SheetWire(a=_pin("R1", "2"), b=_pin("R2", "1"), path=u_path)),
    ).ok

    r1_id, r2_id = bus.document.parts[0].id, bus.document.parts[1].id
    dx, dy = 2 * GRID_MM, 3 * GRID_MM
    moved = tuple(
        SymbolPlacement(id=p.id, at=_p(p.at.x + dx, p.at.y + dy))
        for p in bus.document.sheet
        if p.id in (r1_id, r2_id)
    )
    stretched = wires_after_move(bus.document, LOOKUP, moved)
    assert len(stretched) == 1
    expected = tuple(_p(round(pt.x + dx, 6), round(pt.y + dy, 6)) for pt in u_path)
    assert stretched[0].path == expected


# ---------------------------------------------------------------------------
# Offscreen UI tests (free wires + KiCad-style G-stretch)
# ---------------------------------------------------------------------------


def _ensure_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _send_mouse(view, kind: str, scene_pt, button=None, pressed: bool = False) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    types = {
        "move": QEvent.Type.MouseMove,
        "press": QEvent.Type.MouseButtonPress,
        "release": QEvent.Type.MouseButtonRelease,
        "dblclick": QEvent.Type.MouseButtonDblClick,
    }
    btn = Qt.MouseButton.LeftButton if button is None else button
    ev_btn = Qt.MouseButton.NoButton if kind == "move" else btn
    held = btn if (pressed or kind in ("press", "dblclick")) else Qt.MouseButton.NoButton
    pos = QPointF(view.mapFromScene(scene_pt))
    event = QMouseEvent(
        types[kind],
        pos,
        view.viewport().mapToGlobal(pos),
        ev_btn,
        held,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.viewport(), event)


def _send_key(view, key) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view, event)


def _sheet_window():
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.main import MainWindow

    _ensure_qt()
    doc = create_empty_document(DocumentMeta(name="p3-ui", created="", modified=""))
    window = MainWindow(doc)
    window.resize(1100, 760)
    window.show()
    window.show_schematic()
    QApplication.processEvents()
    for ref in ("R1", "R2"):
        assert window.bus.dispatch("part.add", AddPartPayload(ref=ref, footprint_id="r-axial-3")).ok
    ids = {p.ref: p.id for p in window.bus.document.parts}
    assert window.bus.dispatch(
        "symbol.move",
        MoveSymbolsPayload(
            placements=(
                SymbolPlacement(id=ids["R1"], at=_p(20.32, 20.32)),
                SymbolPlacement(id=ids["R2"], at=_p(60.96, 20.32)),
            )
        ),
    ).ok
    window._refresh_schematic_panel()
    QApplication.processEvents()
    return window


def _close_window(window) -> None:
    from PySide6.QtWidgets import QApplication

    window._saved_document = window.bus.system_document
    window.close()
    window.deleteLater()
    QApplication.processEvents()


def test_ui_free_wire_draw_double_click_extend_and_delete() -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    window = _sheet_window()
    view = window.schematic_view
    try:
        drawing = view.item.drawing
        p12 = pin_position(drawing, "R1", "2")
        p21 = pin_position(drawing, "R2", "1")
        assert p12 is not None and p21 is not None

        # Draw a loose wire from R1.2 to a bare-sheet corner via double-click.
        view.set_tool("wire")
        corner = QPointF(p12.x + 10.16, p12.y)
        _send_mouse(view, "press", QPointF(p12.x, p12.y))
        _send_mouse(view, "release", QPointF(p12.x, p12.y))
        _send_mouse(view, "move", corner)
        _send_mouse(view, "press", corner)
        _send_mouse(view, "release", corner)
        _send_mouse(view, "dblclick", corner)
        QApplication.processEvents()

        assert len(window.bus.document.sheet_loose_wires) == 1
        assert window.bus.document.nets == ()
        assert len(view.item.drawing.free_wires) == 1

        # Pick up the dangling end in Wire tool and land it on R2.1 -> joins net in one step.
        _send_mouse(view, "press", corner)
        _send_mouse(view, "release", corner)
        assert view.pending_loose is not None
        _send_mouse(view, "move", QPointF(p21.x, p21.y))
        _send_mouse(view, "press", QPointF(p21.x, p21.y))
        _send_mouse(view, "release", QPointF(p21.x, p21.y))
        QApplication.processEvents()

        assert window.bus.document.sheet_loose_wires == ()
        assert len(window.bus.document.sheet_wires) == 1
        assert len(window.bus.document.nets) == 1

        # Undo restores the loose wire and disconnects the net.
        assert window.bus.undo()
        QApplication.processEvents()
        assert len(window.bus.document.sheet_loose_wires) == 1
        assert window.bus.document.nets == ()

        # Select the loose wire and press Delete.
        view.set_tool("select")
        mid = QPointF(p12.x + 5.08, p12.y)
        _send_mouse(view, "press", mid)
        _send_mouse(view, "release", mid)
        assert view.selected_loose is not None
        _send_key(view, Qt.Key.Key_Delete)
        QApplication.processEvents()
        assert window.bus.document.sheet_loose_wires == ()
    finally:
        _close_window(window)


def test_ui_g_stretch_moves_symbol_and_stretches_attached_wires_in_one_undo() -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    window = _sheet_window()
    view = window.schematic_view
    try:
        drawing = view.item.drawing
        p12 = pin_position(drawing, "R1", "2")
        p21 = pin_position(drawing, "R2", "1")
        p11 = pin_position(drawing, "R1", "1")
        assert p12 is not None and p21 is not None and p11 is not None

        assert window.bus.dispatch(
            "sheet.wire",
            DrawSheetWirePayload(
                wire=SheetWire(a=_pin("R1", "2"), b=_pin("R2", "1"), path=(p12, p21))
            ),
        ).ok
        assert window.bus.dispatch(
            "sheet.loose.add",
            AddLooseWirePayload(
                path=(p11, _p(p11.x - 5.08, p11.y)), pin=_pin("R1", "1")
            ),
        ).ok
        window._refresh_schematic_panel()
        QApplication.processEvents()

        r1_sym = next(s for s in view.item.drawing.symbols if s.ref == "R1")
        r1_centre = QPointF(r1_sym.at.x + r1_sym.width / 2, r1_sym.at.y + r1_sym.height / 2)

        # Hover over R1, press G to grab (without selecting first!), move down 2 grid steps,
        # then press Escape to verify cancel leaves document untouched.
        _send_mouse(view, "move", r1_centre)
        _send_key(view, Qt.Key.Key_G)
        assert view._grabbing
        _send_mouse(view, "move", QPointF(r1_centre.x(), r1_centre.y() + 2 * GRID_MM))
        assert view.item.drag_offset == QPointF(0.0, 2 * GRID_MM)
        assert view.item.live_drawing is not None
        _send_key(view, Qt.Key.Key_Escape)
        assert not view._grabbing
        assert window.bus.document.sheet_wires[0].path == (p12, p21)

        # Now press G again, move down 3 grid steps, and left-click to commit in ONE undo step.
        history_before = len(window.bus.history())
        _send_mouse(view, "move", r1_centre)
        _send_key(view, Qt.Key.Key_G)
        assert view._grabbing
        target = QPointF(r1_centre.x(), r1_centre.y() + 3 * GRID_MM)
        _send_mouse(view, "move", target)
        _send_mouse(view, "press", target)
        _send_mouse(view, "release", target)
        QApplication.processEvents()

        assert not view._grabbing
        assert len(window.bus.history()) == history_before + 1
        new_p12 = pin_position(view.item.drawing, "R1", "2")
        new_p11 = pin_position(view.item.drawing, "R1", "1")
        assert new_p12 is not None and new_p11 is not None
        assert new_p12.y == pytest.approx(p12.y + 3 * GRID_MM)
        assert window.bus.document.sheet_wires[0].path[0] == new_p12
        assert window.bus.document.sheet_wires[0].path[-1] == p21
        assert window.bus.document.sheet_loose_wires[0].path[0] == new_p11

        # One undo puts R1, its wire, and its loose wire all back.
        assert window.bus.undo()
        QApplication.processEvents()
        assert window.bus.document.sheet_wires[0].path == (p12, p21)
        assert window.bus.document.sheet_loose_wires[0].path == (p11, _p(p11.x - 5.08, p11.y))
    finally:
        _close_window(window)


def test_ui_bare_sheet_free_wire_enter_and_keyboard_g_stretch() -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    window = _sheet_window()
    view = window.schematic_view
    try:
        # 1. Start a wire on bare sheet, add a corner, press Enter -> double-free LooseWire.
        view.set_tool("wire")
        a = QPointF(10.16, 40.64)
        b = QPointF(25.40, 40.64)
        _send_mouse(view, "press", a)
        _send_mouse(view, "release", a)
        assert view.pending_free is not None
        _send_mouse(view, "move", b)
        _send_mouse(view, "press", b)
        _send_mouse(view, "release", b)
        _send_key(view, Qt.Key.Key_Return)
        QApplication.processEvents()

        assert len(window.bus.document.sheet_loose_wires) == 1
        lw = window.bus.document.sheet_loose_wires[0]
        assert lw.pin is None and lw.on is None and lw.port is None
        assert view.item.drawing.free_wires[0].free_start is True

        # 2. Select R2, press G, nudge right with arrow key, press Enter to commit.
        view.set_tool("select")
        r2_before = next(s for s in view.item.drawing.symbols if s.ref == "R2").at
        view.set_selection(["R2"])
        _send_key(view, Qt.Key.Key_G)
        assert view._grabbing
        _send_key(view, Qt.Key.Key_Right)
        _send_key(view, Qt.Key.Key_Down)
        _send_key(view, Qt.Key.Key_Return)
        QApplication.processEvents()

        assert not view._grabbing
        r2_after = next(s for s in view.item.drawing.symbols if s.ref == "R2").at
        assert r2_after.x == pytest.approx(r2_before.x + GRID_MM)
        assert r2_after.y == pytest.approx(r2_before.y + GRID_MM)
    finally:
        _close_window(window)
