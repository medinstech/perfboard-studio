"""The sheet's wire edits as the window carries them out: a wire reshaped, an end moved to
another pin, a cut that splits a net, and a label on a pin that is already wired.

What is pinned: a reshape on a sheet still being arranged freezes it in the same command, so
one undo puts the arranged sheet back -- on an example sheet too; a moved end and a cut say in the status bar which pins left and which went to a
net of their own; a new name on a wired pin names that pin's net, re-classed by the Nets
panel's rule; a name another net already has joins the pin's net to it (``net.merge``),
unless the two are a supply and its ground.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from perfboard_studio.commands import UpdateNetPayload
from perfboard_studio.model import NetNode
from perfboard_studio.schematic import build_schematic, moved_end, moved_run

from .test_sheet_cut import _chain, _wire_between
from .test_sheet_tee import _at, _bus, _drawing, _pin, _wire


@pytest.fixture(scope="module", autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window_for() -> Iterator:
    from perfboard_studio.ui.main import MainWindow

    opened = []

    def make(document):
        window = MainWindow(document)
        opened.append(window)
        return window

    yield make
    for window in opened:
        window._mark_saved()
        window.close()


def _ends(node: NetNode) -> tuple[str, str]:
    return node.component_ref, node.pin


def _derived_bus():
    """``test_sheet_tee._bus`` with nothing placed by hand: the sheet is still arranged."""
    from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
    from perfboard_studio.commands import (
        AddPartPayload,
        create_empty_document,
        create_standard_registry,
    )
    from perfboard_studio.model import DocumentMeta

    bus = CommandBus(
        create_empty_document(DocumentMeta(name="t", created="", modified="")),
        create_standard_registry(),
        CommandContext(next_id=create_id_generator()),
    )
    for ref in ("R1", "R2"):
        assert bus.dispatch("part.add", AddPartPayload(ref=ref, footprint_id="r-axial-3")).ok
    return bus


def test_a_reshape_on_a_sheet_still_arranged_freezes_it_in_the_same_undo_step(window_for) -> None:
    from perfboard_studio.commands import AddNetPayload
    from perfboard_studio.schematic import wires_as_drawn

    bus = _derived_bus()
    pins = (_pin("R1", "2"), _pin("R2", "1"))
    assert bus.dispatch("net.add", AddNetPayload(name="N1", nodes=pins)).ok
    assert not bus.document.sheet and not bus.document.sheet_wires
    window = window_for(bus.document)
    # The sheet in front, as it is under the hand that drags (``_refresh_schematic_panel``):
    # freezing reads the positions and the wires off the drawing on screen.
    document = window.bus.system_document
    drawing = build_schematic(document, window.lookup)
    window.schematic_view.set_unfrozen_wires(wires_as_drawn(drawing, document))
    window.schematic_view.set_drawing(drawing)
    (wire,) = wires_as_drawn(drawing, document)
    start = wire.path[0]
    new = moved_run(wire.path, 0, type(start)(x=start.x, y=start.y + 10.16))
    assert new != wire.path
    window._on_sheet_wire_reshaped(
        *_ends(wire.a), *_ends(wire.b), [(p.x, p.y) for p in new]
    )
    said = window.statusBar().currentMessage()
    assert "Reshape the wire from R2.1 to R1.2. " in said, said
    assert said.endswith("The sheet is drawn by hand from now on; Ctrl+Z takes it back."), said
    document = window.bus.system_document
    assert document.sheet, "the sheet was not frozen"
    (after,) = document.sheet_wires
    assert after.path == new
    labels = window.bus.history()
    assert len(labels) == 1  # the window's bus starts with no history
    assert labels[-1].startswith("Reshape the wire")
    window.on_undo()
    assert not window.bus.system_document.sheet
    assert not window.bus.system_document.sheet_wires


@pytest.mark.parametrize("name", ["atmega328-relay", "nano-relay"])
def test_one_undo_takes_the_first_edit_of_an_example_sheet_back_whole(window_for, name) -> None:
    """The walk's case: on an example sheet nobody has touched, dragging the middle of a
    wire freezes the sheet -- rails become stubs at their pins, names move -- and one Ctrl+Z
    has to put the sheet back as it was, not leave the frozen drawing behind it. A later edit
    is an ordinary step and says nothing about the sheet."""
    import pathlib

    from perfboard_studio import persist
    from perfboard_studio.schematic import wires_as_drawn

    golden = pathlib.Path(__file__).resolve().parent.parent / "examples" / f"{name}.perf"
    document = persist.deserialize_document(golden.read_text(encoding="utf-8")).document
    window = window_for(document)
    document = window.bus.system_document
    drawing = build_schematic(document, window.lookup)
    window.schematic_view.set_unfrozen_wires(wires_as_drawn(drawing, document))
    window.schematic_view.set_drawing(drawing)
    before = window.bus.system_document
    depth = len(window.bus.history())
    wire = max(wires_as_drawn(drawing, document), key=lambda w: len(w.path))
    index = len(wire.path) // 2 - 1
    start = wire.path[index]
    new = moved_run(wire.path, index, type(start)(x=start.x + 5.08, y=start.y + 5.08))

    window._on_sheet_wire_reshaped(*_ends(wire.a), *_ends(wire.b), [(p.x, p.y) for p in new])
    assert window.bus.system_document.sheet
    assert len(window.bus.history()) == depth + 1
    assert "drawn by hand from now on" in window.statusBar().currentMessage()

    window.on_undo()
    assert window.bus.system_document.sheet == before.sheet == ()
    assert window.bus.system_document.sheet_wires == before.sheet_wires
    assert window.bus.system_document.nets == before.nets
    assert len(window.bus.history()) == depth

    # Redone, it is the frozen, reshaped sheet again in one step; the next edit says nothing
    # about the sheet, which is the user's already.
    window.on_redo()
    assert window.bus.system_document.sheet
    stored = next(
        w for w in window.bus.system_document.sheet_wires if {w.a, w.b} == {wire.a, wire.b}
    )
    window._on_sheet_wire_reshaped(
        *_ends(stored.a), *_ends(stored.b), [(p.x, p.y) for p in stored.path]
    )
    assert "drawn by hand" not in window.statusBar().currentMessage()


def test_moving_an_end_says_which_pins_went_to_a_net_of_their_own(window_for) -> None:
    bus = _bus()
    _chain(bus, _pin("R1", "1"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1"))
    wire = _wire_between(bus, _pin("R2", "1"), _pin("R3", "1"))
    # The end on R2.1 is taken to R1.2, a pin on nothing: R1.1 and R2.1 are left on a wire
    # of their own, a piece of two, and GND stays with the three.
    stay, leaving = (wire.b, wire.a) if wire.a == _pin("R2", "1") else (wire.a, wire.b)
    path = wire.path if wire.a == stay else tuple(reversed(wire.path))
    to = _at(_drawing(bus), "R1", "2")
    window = window_for(bus.document)
    window._on_sheet_wire_end_moved(
        *_ends(wire.a),
        *_ends(wire.b),
        *_ends(leaving),
        "R1",
        "2",
        [(p.x, p.y) for p in moved_end(path, to)],
    )
    said = window.statusBar().currentMessage()
    assert "GND split in two: R1.1, R2.1 are now " in said, said
    assert said.endswith("Ctrl+Z brings the wire back.")
    nets = {net.name: {_ends(n) for n in net.nodes} for net in window.bus.system_document.nets}
    assert nets["GND"] == {("R1", "2"), ("R3", "1"), ("R4", "1")}


def test_a_cut_that_splits_a_net_says_where_the_pins_went(window_for, monkeypatch) -> None:
    from perfboard_studio.ui import main

    monkeypatch.setattr(main, "WIRE_DELETE", "cut")
    bus = _bus()
    _chain(bus, _pin("R1", "1"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1"))
    wire = _wire_between(bus, _pin("R2", "1"), _pin("R3", "1"))
    window = window_for(bus.document)
    window._on_sheet_wires_delete([(*_ends(wire.a), *_ends(wire.b))])
    said = window.statusBar().currentMessage()
    assert said.startswith("GND split in two: R3.1, R4.1 are now "), said


def test_a_new_name_on_a_wired_pin_names_its_net_and_classes_it(window_for) -> None:
    # The rail menu's "Connect R1.1 to GND" and the Label tool both end in
    # ``join_pin_to_net_named``; on a pin already on N1 the net is renamed, not left.
    bus = _bus()
    _wire(bus, _pin("R1", "1"), _pin("R2", "1"))
    (net,) = bus.document.nets
    assert net.net_class == "signal"
    window = window_for(bus.document)
    window.join_pin_to_net_named("R1", "1", "GND")
    (after,) = window.bus.system_document.nets
    assert (after.id, after.name, after.net_class) == (net.id, "GND", "ground")
    assert set(after.nodes) == set(net.nodes)


def test_a_name_another_net_has_joins_the_pins_net_to_it_in_one_step(window_for) -> None:
    """Labelling the R1.1 wire VCC is how most people put it on VCC: its net (N1) joins VCC
    whole, as one undo step, and the status line says which pins went."""
    bus = _bus()
    _wire(bus, _pin("R1", "1"), _pin("R2", "1"))
    _wire(bus, _pin("R3", "1"), _pin("R4", "1"))
    other = next(n for n in bus.document.nets if _pin("R3", "1") in n.nodes)
    assert bus.dispatch(
        "net.update", UpdateNetPayload(id=other.id, name="VCC", net_class="power")
    ).ok
    window = window_for(bus.document)
    before = window.bus.system_document.nets
    gone = next(n for n in before if _pin("R1", "1") in n.nodes)
    window.join_pin_to_net_named("R1", "1", "VCC")
    (vcc,) = window.bus.system_document.nets
    assert (vcc.id, vcc.name, vcc.net_class) == (other.id, "VCC", "power")
    assert set(vcc.nodes) == {_pin("R1", "1"), _pin("R2", "1"), _pin("R3", "1"), _pin("R4", "1")}
    said = window.statusBar().currentMessage()
    assert said.startswith(f"{gone.name} joined VCC: R1.1, R2.1 are on VCC now."), said
    assert said.endswith("Ctrl+Z separates them again."), said
    assert window.bus.history()[-1] == f"Join net {gone.name} into VCC"
    window.on_undo()
    assert window.bus.system_document.nets == before


def test_a_ground_name_on_a_supply_wire_is_refused_as_a_short(window_for) -> None:
    bus = _bus()
    _wire(bus, _pin("R1", "1"), _pin("R2", "1"))
    _wire(bus, _pin("R3", "1"), _pin("R4", "1"))
    supply = next(n for n in bus.document.nets if _pin("R1", "1") in n.nodes)
    ground = next(n for n in bus.document.nets if _pin("R3", "1") in n.nodes)
    assert bus.dispatch(
        "net.update", UpdateNetPayload(id=supply.id, name="VCC", net_class="power")
    ).ok
    assert bus.dispatch(
        "net.update", UpdateNetPayload(id=ground.id, name="GND", net_class="ground")
    ).ok
    window = window_for(bus.document)
    before = window.bus.system_document.nets
    window.join_pin_to_net_named("R1", "1", "GND")
    assert window.bus.system_document.nets == before
    said = window.statusBar().currentMessage()
    assert said.startswith("VCC and GND are a supply and a ground"), said


def test_the_label_dialog_opens_on_the_pins_own_net(window_for, monkeypatch) -> None:
    from perfboard_studio.ui import main

    bus = _bus()
    _wire(bus, _pin("R1", "1"), _pin("R2", "1"))
    _wire(bus, _pin("R3", "1"), _pin("R4", "1"))
    window = window_for(bus.document)
    asked: list[tuple[list[str], int]] = []

    def get_item(_parent, _title, _label, items, current, _editable):
        asked.append((list(items), current))
        return "", False

    monkeypatch.setattr(main.QInputDialog, "getItem", staticmethod(get_item))
    window.on_sheet_label("R3", "1")
    ((items, current),) = asked
    own = next(n.name for n in window.bus.system_document.nets if _pin("R3", "1") in n.nodes)
    assert items[current] == own


def test_a_cut_trunk_names_the_branch_that_went_with_it(window_for, monkeypatch) -> None:
    """A T's branch lands on its trunk, so cutting the trunk takes the branch too -- the rule
    stays, and the status line says so, and names the net that went."""
    from perfboard_studio.ui import main

    from .test_sheet_tee import _tee

    monkeypatch.setattr(main, "WIRE_DELETE", "cut")
    bus = _bus()
    _wire(bus, _pin("R1", "1"), _pin("R2", "1"))
    _tee(bus, _pin("R3", "1"), (_pin("R1", "1"), _pin("R2", "1")))
    (net,) = bus.document.nets
    trunk = _wire_between(bus, _pin("R1", "1"), _pin("R2", "1"))
    window = window_for(bus.document)
    window._on_sheet_wires_delete([(*_ends(trunk.a), *_ends(trunk.b))])
    said = window.statusBar().currentMessage()
    assert said.startswith("The branch from R3.1 went with it. "), said
    assert f"{net.name} is gone: " in said, said
    assert said.endswith("Ctrl+Z brings the wire back."), said
    assert not window.bus.system_document.nets


def test_cutting_the_coil_trunk_on_nano_relay_says_coil_went(window_for, monkeypatch) -> None:
    """The walk's case, on the example sheet nobody has frozen."""
    import pathlib

    from perfboard_studio import persist
    from perfboard_studio.schematic import wires_as_drawn
    from perfboard_studio.ui import main

    monkeypatch.setattr(main, "WIRE_DELETE", "cut")
    golden = pathlib.Path(__file__).resolve().parent.parent / "examples" / "nano-relay.perf"
    document = persist.deserialize_document(golden.read_text(encoding="utf-8")).document
    window = window_for(document)
    document = window.bus.system_document
    drawing = build_schematic(document, window.lookup)
    window.schematic_view.set_unfrozen_wires(wires_as_drawn(drawing, document))
    window.schematic_view.set_drawing(drawing)
    coil = next(net for net in document.nets if net.name == "COIL")
    drawn = wires_as_drawn(drawing, document)
    hosts = {frozenset((w.b, w.tap)) for w in drawn if w.tap is not None}
    trunk = next(
        w for w in drawn
        if w.tap is None and frozenset((w.a, w.b)) in hosts and w.a in coil.nodes
    )
    window._on_sheet_wires_delete([(*_ends(trunk.a), *_ends(trunk.b))])
    said = window.statusBar().currentMessage()
    assert "went with it." in said, said
    assert "COIL is gone: " in said, said
    assert all(net.name != "COIL" for net in window.bus.system_document.nets)
