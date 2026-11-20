"""Phase 5: Selection, clipboard/paste/duplicate, align/distribute, renumber, movable text offsets, mirror keys."""

from __future__ import annotations

import os

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    AddLooseWirePayload,
    AddPartPayload,
    AddSheetNotePayload,
    AddSheetPortPayload,
    AlignSheetPayload,
    DrawSheetWirePayload,
    MoveSymbolsPayload,
    PasteSheetPart,
    PasteSheetPayload,
    RenumberPartsPayload,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import (
    DocumentMeta,
    LooseWire,
    NetNode,
    Point2,
    PortLink,
    SheetNote,
    SheetPort,
    SheetWire,
    SymbolPlacement,
)
from perfboard_studio.schematic import (
    GRID_MM,
    build_schematic,
    pin_position,
    placed_part_labels,
    plan_sheet_renumber,
)
from perfboard_studio.ui.sheet_clipboard import sheet_block_from_json, sheet_block_to_json

LOOKUP = footprint_lookup()


def _pin(ref: str, pin: str) -> NetNode:
    return NetNode(component_ref=ref, pin=pin)


def _p(x: float, y: float) -> Point2:
    return Point2(x=x, y=y)


def _bus() -> CommandBus:
    bus = CommandBus(
        create_empty_document(DocumentMeta(name="p5", created="", modified="")),
        create_standard_registry(),
        CommandContext(next_id=create_id_generator()),
    )
    for ref, val in (("R7", "10k"), ("R2", "4k7"), ("C5", "100nF")):
        assert bus.dispatch(
            "part.add", AddPartPayload(ref=ref, footprint_id="r-axial-3", value=val)
        ).ok
    ids = {part.ref: part.id for part in bus.document.parts}
    placed = MoveSymbolsPayload(
        placements=(
            SymbolPlacement(id=ids["R7"], at=_p(60.96, 20.32)),
            SymbolPlacement(id=ids["R2"], at=_p(20.32, 20.32)),
            SymbolPlacement(id=ids["C5"], at=_p(40.64, 45.72)),
        )
    )
    assert bus.dispatch("symbol.move", placed).ok
    return bus


# ---------------------------------------------------------------------------
# Movable ref / value text offsets (model, persist, schematic)
# ---------------------------------------------------------------------------


def test_label_offsets_omit_at_default_and_round_trip_when_set() -> None:
    bus = _bus()
    raw_default = persist.serialize_document(bus.document)
    assert '"refOffset"' not in raw_default
    assert '"valueOffset"' not in raw_default

    # Zero offset is also omitted.
    pl0 = bus.document.sheet[0]
    assert bus.dispatch(
        "symbol.move",
        MoveSymbolsPayload(
            placements=(
                SymbolPlacement(
                    id=pl0.id,
                    at=pl0.at,
                    ref_offset=_p(0.0, 0.0),
                    value_offset=_p(0.0, 0.0),
                ),
            )
        ),
    ).ok
    raw_zero = persist.serialize_document(bus.document)
    assert '"refOffset"' not in raw_zero and '"valueOffset"' not in raw_zero

    before_drawing = build_schematic(bus.document, LOOKUP)
    before_labels = {
        (ref, kind): label.at for ref, kind, label in placed_part_labels(before_drawing)
    }

    # Non-zero offset shifts the rendered labels and round-trips cleanly.
    r7 = next(p for p in bus.document.parts if p.ref == "R7")
    r7_pl = next(pl for pl in bus.document.sheet if pl.id == r7.id)
    assert bus.dispatch(
        "symbol.move",
        MoveSymbolsPayload(
            placements=(
                SymbolPlacement(
                    id=r7.id,
                    at=r7_pl.at,
                    ref_offset=_p(5.08, -2.54),
                    value_offset=_p(-2.54, 5.08),
                ),
            )
        ),
    ).ok

    text = persist.serialize_document(bus.document)
    assert '"refOffset"' in text and '"valueOffset"' in text
    reopened = persist.parse_document_or_throw(text)
    assert set(reopened.sheet) == set(bus.document.sheet)
    assert persist.serialize_document(reopened) == text

    after_drawing = build_schematic(reopened, LOOKUP)
    after_labels = {
        (ref, kind): label.at for ref, kind, label in placed_part_labels(after_drawing)
    }
    assert after_labels[("R7", "ref")] == _p(
        round(before_labels[("R7", "ref")].x + 5.08, 6),
        round(before_labels[("R7", "ref")].y - 2.54, 6),
    )
    assert after_labels[("R7", "value")] == _p(
        round(before_labels[("R7", "value")].x - 2.54, 6),
        round(before_labels[("R7", "value")].y + 5.08, 6),
    )
    # Other symbols' labels did not move.
    assert after_labels[("R2", "ref")] == before_labels[("R2", "ref")]


# ---------------------------------------------------------------------------
# Sheet copy / paste / duplicate (sheet.paste)
# ---------------------------------------------------------------------------


def test_sheet_paste_allocates_next_refs_and_remaps_wires_ports_loose_and_notes() -> None:
    bus = _bus()
    drawing = build_schematic(bus.document, LOOKUP)
    p22 = pin_position(drawing, "R2", "2")
    p71 = pin_position(drawing, "R7", "1")
    p21 = pin_position(drawing, "R2", "1")
    assert p22 is not None and p71 is not None and p21 is not None

    # Wire R2.2 -> R7.1, hang GND port on R2.1, add a loose wire off R7.2, and add a note.
    assert bus.dispatch(
        "sheet.wire",
        DrawSheetWirePayload(wire=SheetWire(a=_pin("R2", "2"), b=_pin("R7", "1"), path=(p22, p71))),
    ).ok
    gnd_at = _p(p21.x - 5.08, p21.y + 5.08)
    assert bus.dispatch(
        "sheet.port.add",
        AddSheetPortPayload(
            kind="ground",
            name="GND",
            at=gnd_at,
            links=(PortLink(pin=_pin("R2", "1"), path=(p21, _p(gnd_at.x, p21.y), gnd_at)),),
        ),
    ).ok
    p72 = pin_position(drawing, "R7", "2")
    assert p72 is not None
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(path=(p72, _p(p72.x + 5.08, p72.y)), pin=_pin("R7", "2")),
    ).ok
    assert bus.dispatch(
        "sheet.note.add",
        AddSheetNotePayload(kind="text", at=_p(20.32, 10.16), to=_p(20.32, 10.16), text="stage"),
    ).ok

    # Serialize selection (R2, R7 + note 0) via sheet_clipboard and paste with an offset.
    drawing = build_schematic(bus.document, LOOKUP)
    clip = sheet_block_to_json(bus.document, drawing, refs=["R2", "R7"], note_indices=[0])
    payload = sheet_block_from_json(clip, offset=_p(0.0, 20.32))
    assert payload is not None

    before = bus.document
    res = bus.dispatch("sheet.paste", payload)
    assert res.ok, res.message

    # Allocated next free refs: R2 -> R3, R7 -> R8.
    refs = {p.ref for p in bus.document.parts}
    assert {"R2", "R7", "C5", "R3", "R8"} == refs
    # New local signal wire connects R3.2 -> R8.1 on its own new net.
    assert any(
        w.a == _pin("R3", "2") and w.b == _pin("R8", "1") for w in bus.document.sheet_wires
    )
    # Pasted GND port joined R3.1 onto the document's existing GND net.
    gnd_net = next(n for n in bus.document.nets if n.name == "GND")
    assert _pin("R2", "1") in gnd_net.nodes and _pin("R3", "1") in gnd_net.nodes
    # Loose wire remapped to R8.2 and shifted down by 20.32 mm.
    assert any(
        lw.pin == _pin("R8", "2") and lw.path[0].y == pytest.approx(p72.y + 20.32)
        for lw in bus.document.sheet_loose_wires
    )
    # Note duplicated and shifted.
    assert len(bus.document.sheet_notes) == 2

    # One undo reverts the entire paste atomically.
    assert bus.undo() and bus.document == before


def test_sheet_paste_empty_is_refused() -> None:
    bus = _bus()
    res = bus.dispatch("sheet.paste", PasteSheetPayload())
    assert not res.ok and res.code == "empty-batch"


def test_sheet_paste_direct_payload_preserves_offsets_and_skips_taken_refs() -> None:
    bus = _bus()
    assert bus.dispatch("part.add", AddPartPayload(ref="R8", footprint_id="r-axial-3")).ok
    payload = PasteSheetPayload(
        parts=(
            PasteSheetPart(
                source_ref="R7",
                footprint_id="r-axial-3",
                at=_p(10.16, 10.16),
                ref_offset=_p(2.54, 0.0),
            ),
        ),
        loose_wires=(LooseWire(id="x", path=(_p(0.0, 0.0), _p(5.08, 0.0))),),
        ports=(SheetPort(id="p", kind="supply", name="+5V", at=_p(10.16, 5.08)),),
        notes=(SheetNote(id="n", kind="line", at=_p(0.0, 0.0), to=_p(10.16, 0.0)),),
        offset=_p(5.08, 5.08),
    )
    assert bus.dispatch("sheet.paste", payload).ok
    # R8 already existed, so R7 -> R9!
    r9 = next(p for p in bus.document.parts if p.ref == "R9")
    r9_pl = next(pl for pl in bus.document.sheet if pl.id == r9.id)
    assert r9_pl.at == _p(15.24, 15.24)
    assert r9_pl.ref_offset == _p(2.54, 0.0)


# ---------------------------------------------------------------------------
# Align & distribute (sheet.align)
# ---------------------------------------------------------------------------


def test_sheet_align_edges_and_distribute_in_one_undo_step() -> None:
    bus = _bus()
    ids = {p.ref: p.id for p in bus.document.parts}
    # Put symbols at varied x/y: R2=(20.32, 20.32), C5=(40.64, 45.72), R7=(60.96, 30.48)
    assert bus.dispatch(
        "symbol.move",
        MoveSymbolsPayload(
            placements=(
                SymbolPlacement(id=ids["R2"], at=_p(20.32, 20.32)),
                SymbolPlacement(id=ids["C5"], at=_p(35.56, 45.72)),
                SymbolPlacement(id=ids["R7"], at=_p(71.12, 30.48)),
            )
        ),
    ).ok

    # Align top -> all three move to y=20.32 in one undo step.
    before = bus.document
    assert bus.dispatch(
        "sheet.align",
        AlignSheetPayload(mode="top", ids=(ids["R2"], ids["C5"], ids["R7"])),
    ).ok
    ys = {pl.id: pl.at.y for pl in bus.document.sheet}
    assert ys == {ids["R2"]: 20.32, ids["C5"]: 20.32, ids["R7"]: 20.32}
    assert bus.undo() and bus.document == before

    # Align left -> all three move to x=20.32.
    assert bus.dispatch(
        "sheet.align",
        AlignSheetPayload(mode="left", ids=(ids["R2"], ids["C5"], ids["R7"])),
    ).ok
    assert {pl.at.x for pl in bus.document.sheet} == {20.32}
    assert bus.undo()

    # Align right with widths -> right edges match.
    sizes = ((ids["R2"], _p(20.32, 10.16)), (ids["R7"], _p(10.16, 10.16)))
    assert bus.dispatch(
        "sheet.align",
        AlignSheetPayload(mode="right", ids=(ids["R2"], ids["R7"]), sizes=sizes),
    ).ok
    by_id = {pl.id: pl.at.x for pl in bus.document.sheet}
    assert by_id[ids["R2"]] + 20.32 == pytest.approx(by_id[ids["R7"]] + 10.16)
    assert bus.undo()

    # Distribute horizontally -> middle symbol C5 moves halfway between 20.32 and 71.12 (=45.72).
    assert bus.dispatch(
        "sheet.align",
        AlignSheetPayload(mode="distribute-h", ids=(ids["R2"], ids["C5"], ids["R7"])),
    ).ok
    by_id = {pl.id: pl.at.x for pl in bus.document.sheet}
    assert by_id[ids["R2"]] == pytest.approx(20.32)
    assert by_id[ids["C5"]] == pytest.approx(45.72)
    assert by_id[ids["R7"]] == pytest.approx(71.12)

    # Distribute with fewer than 3 items refused.
    bad = bus.dispatch(
        "sheet.align",
        AlignSheetPayload(mode="distribute-v", ids=(ids["R2"], ids["R7"])),
    )
    assert not bad.ok and bad.code == "too-few-items"


# ---------------------------------------------------------------------------
# Renumber references (part.renumber + plan_sheet_renumber)
# ---------------------------------------------------------------------------


def test_part_renumber_left_to_right_top_to_bottom_handles_swaps_and_sheet_refs() -> None:
    bus = _bus()
    # Add R1 to the RIGHT of R7 so R2 (left), R7 (middle), R1 (right) must swap cleanly to R1, R2, R3!
    assert bus.dispatch("part.add", AddPartPayload(ref="R1", footprint_id="r-axial-3")).ok
    ids = {p.ref: p.id for p in bus.document.parts}
    assert bus.dispatch(
        "symbol.move",
        MoveSymbolsPayload(
            placements=(
                SymbolPlacement(id=ids["R2"], at=_p(20.32, 20.32)),
                SymbolPlacement(id=ids["R7"], at=_p(50.80, 20.32)),
                SymbolPlacement(id=ids["R1"], at=_p(81.28, 20.32)),
                SymbolPlacement(id=ids["C5"], at=_p(20.32, 45.72)),
            )
        ),
    ).ok
    drawing = build_schematic(bus.document, LOOKUP)
    p22 = pin_position(drawing, "R2", "2")
    p71 = pin_position(drawing, "R7", "1")
    p11 = pin_position(drawing, "R1", "1")
    assert p22 is not None and p71 is not None and p11 is not None

    assert bus.dispatch(
        "sheet.wire",
        DrawSheetWirePayload(wire=SheetWire(a=_pin("R2", "2"), b=_pin("R7", "1"), path=(p22, p71))),
    ).ok
    assert bus.dispatch(
        "sheet.port.add",
        AddSheetPortPayload(
            kind="ground",
            name="GND",
            at=_p(p11.x, p11.y + 5.08),
            links=(PortLink(pin=_pin("R1", "1"), path=(p11, _p(p11.x, p11.y + 5.08))),),
        ),
    ).ok
    assert bus.dispatch(
        "sheet.loose.add",
        AddLooseWirePayload(
            path=(_p(45.72, p22.y), _p(45.72, p22.y + 5.08)),
            on=(_pin("R2", "2"), _pin("R7", "1")),
        ),
    ).ok

    mapping = plan_sheet_renumber(bus.document, LOOKUP)
    mapped_dict = dict(mapping)
    assert mapped_dict[ids["R2"]] == "R1"
    assert mapped_dict[ids["R7"]] == "R2"
    assert mapped_dict[ids["R1"]] == "R3"
    assert mapped_dict[ids["C5"]] == "C1"

    before = bus.document
    res = bus.dispatch("part.renumber", RenumberPartsPayload(mapping=mapping))
    assert res.ok, res.message

    refs_by_id = {p.id: p.ref for p in bus.document.parts}
    assert refs_by_id[ids["R2"]] == "R1"
    assert refs_by_id[ids["R7"]] == "R2"
    assert refs_by_id[ids["R1"]] == "R3"
    assert refs_by_id[ids["C5"]] == "C1"
    # Wire, port link, loose wire, and nets all carried across the swap!
    assert bus.document.sheet_wires[0].a == _pin("R1", "2")
    assert bus.document.sheet_wires[0].b == _pin("R2", "1")
    assert bus.document.sheet_ports[0].links[0].pin == _pin("R3", "1")
    assert bus.document.sheet_loose_wires[0].on == (_pin("R1", "2"), _pin("R2", "1"))
    assert any(
        _pin("R1", "2") in n.nodes and _pin("R2", "1") in n.nodes for n in bus.document.nets
    )

    # Single undo restores everything.
    assert bus.undo() and bus.document == before


def test_part_renumber_refuses_duplicate_refs() -> None:
    bus = _bus()
    ids = {p.ref: p.id for p in bus.document.parts}
    res = bus.dispatch(
        "part.renumber",
        RenumberPartsPayload(mapping=((ids["R7"], "R2"),)),
    )
    assert not res.ok and res.code == "duplicate-ref"


# ---------------------------------------------------------------------------
# Offscreen UI tests (clipboard, duplicate, align, renumber, label drag,
# Shift-click additive select, Ctrl+A, X/Y mirror keys)
# ---------------------------------------------------------------------------


def _ensure_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _send_mouse(view, kind: str, scene_pt, *, modifiers=None, pressed: bool = False) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    types = {
        "move": QEvent.Type.MouseMove,
        "press": QEvent.Type.MouseButtonPress,
        "release": QEvent.Type.MouseButtonRelease,
    }
    mods = Qt.KeyboardModifier.NoModifier if modifiers is None else modifiers
    left = Qt.MouseButton.LeftButton
    ev_btn = Qt.MouseButton.NoButton if kind == "move" else left
    held = left if (pressed or kind == "press") else Qt.MouseButton.NoButton
    pos = QPointF(view.mapFromScene(scene_pt))
    event = QMouseEvent(
        types[kind], pos, view.viewport().mapToGlobal(pos), ev_btn, held, mods
    )
    QApplication.sendEvent(view.viewport(), event)


def _send_key(view, key, modifiers=None) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    mods = Qt.KeyboardModifier.NoModifier if modifiers is None else modifiers
    event = QKeyEvent(QEvent.Type.KeyPress, key, mods)
    QApplication.sendEvent(view, event)


def _sheet_window():
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.main import MainWindow

    _ensure_qt()
    doc = create_empty_document(DocumentMeta(name="p5-ui", created="", modified=""))
    window = MainWindow(doc)
    window.resize(1100, 760)
    window.show()
    window.show_schematic()
    QApplication.processEvents()
    for ref, val in (("R7", "10k"), ("R2", "4k7")):
        assert window.bus.dispatch(
            "part.add", AddPartPayload(ref=ref, footprint_id="r-axial-3", value=val)
        ).ok
    ids = {p.ref: p.id for p in window.bus.document.parts}
    assert window.bus.dispatch(
        "symbol.move",
        MoveSymbolsPayload(
            placements=(
                SymbolPlacement(id=ids["R2"], at=_p(20.32, 20.32)),
                SymbolPlacement(id=ids["R7"], at=_p(60.96, 30.48)),
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


def test_ui_shift_select_ctrl_a_duplicate_copy_paste_cut_and_mirror_xy() -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    window = _sheet_window()
    view = window.schematic_view
    try:
        r2 = next(s for s in view.item.drawing.symbols if s.ref == "R2")
        r7 = next(s for s in view.item.drawing.symbols if s.ref == "R7")
        r2_mid = QPointF(r2.at.x + r2.width / 2, r2.at.y + r2.height / 2)
        r7_mid = QPointF(r7.at.x + r7.width / 2, r7.at.y + r7.height / 2)

        # Click R2, then Shift-click R7 -> additive selection.
        _send_mouse(view, "press", r2_mid)
        _send_mouse(view, "release", r2_mid)
        assert view.selected_refs == ["R2"]
        _send_mouse(view, "press", r7_mid, modifiers=Qt.KeyboardModifier.ShiftModifier)
        _send_mouse(view, "release", r7_mid, modifiers=Qt.KeyboardModifier.ShiftModifier)
        assert set(view.selected_refs) == {"R2", "R7"}

        # Clear then Ctrl+A selects all.
        view.set_selection([])
        _send_key(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert set(view.selected_refs) == {"R2", "R7"}

        # Mirror X and Mirror Y keys on R2.
        view.set_selection(["R2"])
        _send_key(view, Qt.Key.Key_X)
        QApplication.processEvents()
        r2_pl = next(
            pl for pl in window.bus.document.sheet if pl.id == window._id_of("R2")
        )
        assert r2_pl.mirrored is True and r2_pl.rotation == 0

        _send_key(view, Qt.Key.Key_Y)
        QApplication.processEvents()
        r2_pl = next(
            pl for pl in window.bus.document.sheet if pl.id == window._id_of("R2")
        )
        assert r2_pl.mirrored is False and r2_pl.rotation == 180

        # Ctrl+D duplicates R7 -> creates R8 in one undo step.
        view.set_selection(["R7"])
        hist_before = len(window.bus.history())
        _send_key(view, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
        assert len(window.bus.history()) == hist_before + 1
        assert {p.ref for p in window.bus.document.parts} == {"R2", "R7", "R8"}

        # Ctrl+C + Ctrl+V pastes R8 -> creates R9.
        view.set_selection(["R8"])
        _send_key(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        _send_key(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
        assert {p.ref for p in window.bus.document.parts} == {"R2", "R7", "R8", "R9"}

        # Ctrl+X cuts R9.
        view.set_selection(["R9"])
        _send_key(view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
        assert {p.ref for p in window.bus.document.parts} == {"R2", "R7", "R8"}
    finally:
        _close_window(window)


def test_ui_label_drag_align_and_renumber() -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    window = _sheet_window()
    view = window.schematic_view
    try:
        # 1. Drag R2's ref label up by 2 grid squares -> persists ref_offset on SymbolPlacement.
        r2_ref_label = next(
            label for ref, kind, label in placed_part_labels(view.item.drawing)
            if ref == "R2" and kind == "ref"
        )
        start = QPointF(r2_ref_label.at.x, r2_ref_label.at.y - 0.5)
        end = QPointF(start.x() + 2 * GRID_MM, start.y() - 2 * GRID_MM)
        _send_mouse(view, "press", start)
        _send_mouse(view, "move", end, pressed=True)
        _send_mouse(view, "release", end)
        QApplication.processEvents()

        r2_pl = next(
            pl for pl in window.bus.document.sheet if pl.id == window._id_of("R2")
        )
        assert r2_pl.ref_offset is not None
        assert r2_pl.ref_offset.x == pytest.approx(2 * GRID_MM)
        assert r2_pl.ref_offset.y == pytest.approx(-2 * GRID_MM)

        # 2. Align R2 and R7 top -> both share y=20.32 in one undo step.
        view.set_selection(["R2", "R7"])
        window.on_sheet_align("top")
        QApplication.processEvents()
        assert {pl.at.y for pl in window.bus.document.sheet} == {20.32}

        # 3. Renumber sheet -> R2 (left) becomes R1, R7 (right) becomes R2.
        window.on_sheet_renumber()
        QApplication.processEvents()
        assert {p.ref for p in window.bus.document.parts} == {"R1", "R2"}
    finally:
        _close_window(window)
