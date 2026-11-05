"""Several boards in one document, each seen alone (``system.py``).

What is pinned: which fields are a board's own and which the design's, so a field added to
the document is a field somebody has to decide about; a board's view is exactly the
single-board document the engine already reads, and merging it back unchanged gives the
document back unchanged, for every board; a change made through one board's view leaves
every other board as it was; and a document of several boards goes through the file and
comes back equal, while a board alone writes exactly the bytes it always did (the golden
round trip in ``test_persist`` is the full proof of that).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from perfboard_studio import persist, system
from perfboard_studio.model import (
    ExtraBoard,
    HoleCoord,
    LeadBendConductor,
    PerfDocument,
)

REPO = Path(__file__).resolve().parents[1]


def _example(name: str) -> PerfDocument:
    return persist.parse_document_or_throw((REPO / "examples" / f"{name}.perf").read_text(encoding="utf-8"))


def _as_extra(doc: PerfDocument, board_id: str, name: str) -> ExtraBoard:
    """``doc``'s board as an extra board, its component and conductor ids and references
    prefixed so they cannot meet the first board's: one id space across the document."""

    def conductor(c):  # type: ignore[no-untyped-def]
        changed = dataclasses.replace(c, id=f"{board_id}-{c.id}")
        if isinstance(c, LeadBendConductor):
            changed = dataclasses.replace(changed, component_id=f"{board_id}-{c.component_id}")
        return changed

    return ExtraBoard(
        id=board_id,
        name=name,
        board=doc.board,
        components=tuple(
            dataclasses.replace(c, id=f"{board_id}-{c.id}", ref=f"{board_id.upper()}{c.ref}")
            for c in doc.components
        ),
        conductors=tuple(conductor(c) for c in doc.conductors),
        cuts=doc.cuts,
        mounting_holes=doc.mounting_holes,
        edge_connectors=doc.edge_connectors,
        board_notes=doc.board_notes,
        height_limit_mm=doc.height_limit_mm,
        body_clearance_mm=doc.body_clearance_mm,
    )


def _system() -> PerfDocument:
    """lm317-supply as the first board, nano-relay and ne555-astable after it."""
    first = _example("lm317-supply")
    return dataclasses.replace(
        first,
        boards=(
            _as_extra(_example("nano-relay"), "b2", "Controller"),
            _as_extra(_example("ne555-astable"), "b3", "Blinker"),
        ),
    )


def test_every_field_is_a_boards_own_or_the_designs() -> None:
    """An extra board has exactly the first board's own fields, and everything else on the
    document is shared. A field added to either is caught here, because it has to be
    decided which it is -- a board's own field left out of ``BOARD_FIELDS`` would be the
    first board's value on every board's view."""
    document_fields = {f.name for f in dataclasses.fields(PerfDocument)}
    extra_fields = {f.name for f in dataclasses.fields(ExtraBoard)} - {"id", "name"}
    assert extra_fields == set(system.BOARD_FIELDS)
    assert set(system.BOARD_FIELDS) <= document_fields
    assert set(system.shared_fields()) == {
        "meta", "parts", "nets", "sheet", "sheet_wires", "sheet_notes", "format_version",
    }


def test_a_boards_view_is_a_document_of_that_board_alone() -> None:
    doc = _system()
    assert system.board_ids(doc) == (system.FIRST_BOARD, "b2", "b3")
    for board_id in system.board_ids(doc):
        seen = system.board_document(doc, board_id)
        assert seen.boards == ()
        for name in system.shared_fields():
            assert getattr(seen, name) == getattr(doc, name)
        own = doc if board_id == system.FIRST_BOARD else system.extra_board(doc, board_id)
        for name in system.BOARD_FIELDS:
            assert getattr(seen, name) == getattr(own, name), (board_id, name)


@pytest.mark.parametrize("board_id", [system.FIRST_BOARD, "b2", "b3"])
def test_merging_a_view_back_unchanged_gives_the_document_back(board_id: str) -> None:
    doc = _system()
    assert system.merge_board(doc, board_id, system.board_document(doc, board_id)) == doc


@pytest.mark.parametrize("board_id", [system.FIRST_BOARD, "b2", "b3"])
def test_a_change_to_one_board_leaves_every_other_board_as_it_was(board_id: str) -> None:
    """Move every part of one board by a hole and rename the document: the board's own
    fields change, the shared field changes for every board, and no other board moves."""
    doc = _system()
    seen = system.board_document(doc, board_id)
    moved = dataclasses.replace(
        seen,
        meta=dataclasses.replace(seen.meta, name="renamed"),
        components=tuple(
            dataclasses.replace(c, anchor=HoleCoord(c.anchor.col + 1, c.anchor.row))
            for c in seen.components
        ),
    )
    merged = system.merge_board(doc, board_id, moved)
    assert merged.meta.name == "renamed"
    for other in system.board_ids(doc):
        view = system.board_document(merged, other)
        if other == board_id:
            assert view.components == moved.components
        else:
            assert view.components == system.board_document(doc, other).components
            for name in system.BOARD_FIELDS:
                assert getattr(view, name) == getattr(system.board_document(doc, other), name)


def test_a_view_that_holds_another_board_is_refused() -> None:
    doc = _system()
    with pytest.raises(ValueError):
        system.merge_board(doc, system.FIRST_BOARD, doc)


def test_a_document_of_several_boards_goes_through_the_file_and_back() -> None:
    doc = _system()
    text = persist.serialize_document(doc)
    assert text.count('"boards"') == 1
    back = persist.parse_document_or_throw(text)
    assert back.boards == doc.boards
    assert system.board_document(back) == system.board_document(doc)
    assert persist.serialize_document(back) == text


def test_a_board_alone_writes_no_boards_key() -> None:
    doc = _example("ne555-astable")
    assert '"boards"' not in persist.serialize_document(doc)


def test_ids_are_one_space_across_every_board() -> None:
    """Two boards holding one component id, a board taking another's id, or the first
    board's own id: refused at load, as two components sharing an id on one board are."""
    doc = _system()
    clash = dataclasses.replace(
        doc,
        boards=(
            doc.boards[0],
            dataclasses.replace(doc.boards[1], components=(doc.components[0],)),
        ),
    )
    result = persist.deserialize_document(persist.serialize_document(clash))
    assert not result.ok and result.code == "duplicate-id"
    for taken in ("b2", system.FIRST_BOARD):
        twice = dataclasses.replace(doc, boards=(doc.boards[0], dataclasses.replace(doc.boards[1], id=taken)))
        result = persist.deserialize_document(persist.serialize_document(twice))
        assert not result.ok and result.code == "duplicate-id", taken


# ---------------------------------------------------------------------------
# The commands: board.on, board.add, board.rename, board.delete
# ---------------------------------------------------------------------------


def _bus(doc: PerfDocument):  # type: ignore[no-untyped-def]
    from perfboard_studio.command import CommandBus, CommandContext
    from perfboard_studio.commands import create_document_id_generator, create_standard_registry

    return CommandBus(doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc)))


def test_a_board_command_done_on_one_board_moves_that_board_alone() -> None:
    """``board.on`` hands any board command the board's own view and merges it back: the
    second board's part moves, the first board and the third do not, and one undo puts it
    back -- one step on the one stack, whichever board it was on."""
    from perfboard_studio.commands import MoveComponentPayload, OnBoardPayload

    doc = _system()
    bus = _bus(doc)
    part = system.extra_board(doc, "b2").components[0]
    to = HoleCoord(part.anchor.col, part.anchor.row + 1)
    result = bus.dispatch(
        "board.on", OnBoardPayload(board="b2", type="component.move", payload=MoveComponentPayload(id=part.id, anchor=to))
    )
    assert result.ok, result.message
    after = bus.document
    assert next(c for c in system.extra_board(after, "b2").components if c.id == part.id).anchor == to
    assert system.board_document(after) == system.board_document(doc)
    assert system.extra_board(after, "b3") == system.extra_board(doc, "b3")
    assert result.description.endswith("on Controller"), result.description
    assert bus.undo() == doc


def test_a_reference_another_board_holds_is_refused() -> None:
    """No board can see another's references, so the system checks them after the merge:
    placing an R1 on the second board while the first holds R1 is refused."""
    from perfboard_studio.commands import OnBoardPayload, PlaceComponentPayload

    doc = _system()
    taken = doc.components[0].ref
    result = _bus(doc).dispatch(
        "board.on",
        OnBoardPayload(
            board="b2",
            type="component.place",
            payload=PlaceComponentPayload(ref=taken, value="", footprint_id="r-axial-3", anchor=HoleCoord(1, 1)),
        ),
    )
    assert not result.ok and result.code == "duplicate-ref"


def test_a_new_id_on_any_board_is_new_to_the_whole_document() -> None:
    """The id generator reads every board: an id generated after a reopen is held by no
    board of the system."""
    from perfboard_studio.commands import create_document_id_generator

    doc = _system()
    held = {
        item.id
        for board_id in system.board_ids(doc)
        for seen in (system.board_document(doc, board_id),)
        for items in (seen.components, seen.conductors, seen.cuts, seen.mounting_holes, seen.edge_connectors, seen.board_notes)
        for item in items
    } | {extra.id for extra in doc.boards}
    next_id = create_document_id_generator(doc)
    for prefix in ("cmp", "cond", "cut", "mh", "ec", "label", "board"):
        assert next_id(prefix) not in held, prefix


def test_boards_are_added_named_and_taken_out_with_their_parts_kept_in_the_design() -> None:
    from perfboard_studio.commands import AddBoardPayload, DeleteBoardPayload, RenameBoardPayload

    doc = _system()
    bus = _bus(doc)
    assert bus.dispatch("board.add", AddBoardPayload(board=doc.board, name="Spare")).ok
    added = bus.document.boards[-1]
    assert added.name == "Spare" and added.id not in {"b2", "b3", system.FIRST_BOARD}
    assert bus.dispatch("board.rename", RenameBoardPayload(board=added.id, name="Panel")).ok
    assert system.extra_board(bus.document, added.id).name == "Panel"
    unnamed = bus.dispatch("board.add", AddBoardPayload(board=doc.board, name="  "))
    assert unnamed.ok and bus.document.boards[-1].name == "", "blank is a board nobody named yet"
    assert system.board_title(bus.document, bus.document.boards[-1].id) == "Board 5"

    nets_before = bus.document.nets
    leaving = system.extra_board(bus.document, "b2")
    assert bus.dispatch("board.delete", DeleteBoardPayload(board="b2")).ok
    after = bus.document
    assert "b2" not in system.board_ids(after)
    assert {c.ref for c in leaving.components} <= {p.ref for p in after.parts}, "its parts are in the design"
    assert after.nets == nets_before, "and wired as they were"
    first = bus.dispatch("board.delete", DeleteBoardPayload(board=system.FIRST_BOARD))
    assert not first.ok and first.code == "first-board"


def test_only_board_commands_are_done_on_a_board() -> None:
    from perfboard_studio.commands import AddBoardPayload, OnBoardPayload

    doc = _system()
    bus = _bus(doc)
    nested = bus.dispatch(
        "board.on", OnBoardPayload(board="b2", type="board.add", payload=AddBoardPayload(board=doc.board, name="x"))
    )
    assert not nested.ok and nested.code == "unknown-command"
    nowhere = bus.dispatch("board.on", OnBoardPayload(board="b9", type="document.rename", payload=None))
    assert not nowhere.ok and nowhere.code == "unknown-board"


# ---------------------------------------------------------------------------
# Cables
# ---------------------------------------------------------------------------


def _ends(doc: PerfDocument):  # type: ignore[no-untyped-def]
    """The supply's DC OUT (J2, the first board) and the controller's 12V IN (its J1)."""
    from perfboard_studio.model import CableEnd

    supply_out = next(c for c in doc.components if c.ref == "J2")
    controller_in = next(c for c in system.extra_board(doc, "b2").components if c.ref == "B2J1")
    return CableEnd(system.FIRST_BOARD, supply_out.id), CableEnd("b2", controller_in.id)


def _cable(doc: PerfDocument, **changes):  # type: ignore[no-untyped-def]
    from perfboard_studio.model import Cable, CableWire

    a, b = _ends(doc)
    cable = Cable(
        id="", ref="W1", a=a, b=b,
        wires=(CableWire("1", "1", colour="red", gauge_awg=22), CableWire("2", "2", colour="black")),
        length_mm=150,
    )
    return dataclasses.replace(cable, **changes)


def test_a_cable_joins_two_connectors_and_goes_through_the_file() -> None:
    from perfboard_studio.commands import AddCablePayload

    doc = _system()
    bus = _bus(doc)
    result = bus.dispatch("cable.add", AddCablePayload(cable=_cable(doc)))
    assert result.ok, result.message
    cable = bus.document.cables[0]
    assert cable.id.startswith("cable-") and cable.ref == "W1"
    text = persist.serialize_document(bus.document)
    back = persist.parse_document_or_throw(text)
    assert back.cables == bus.document.cables
    assert persist.serialize_document(back) == text
    assert system.board_document(back).cables == (), "a board's view holds no cable"


@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"wires": ()}, "no wires"),
        ({"ref": " "}, "needs a reference"),
        ({"length_mm": 0}, "more than nothing"),
    ],
)
def test_a_cable_that_is_not_whole_is_refused(changes, why) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.commands import AddCablePayload

    doc = _system()
    result = _bus(doc).dispatch("cable.add", AddCablePayload(cable=_cable(doc, **changes)))
    assert not result.ok and result.code == "invalid-cable" and why in result.message


def test_a_cable_to_nowhere_or_onto_one_pin_twice_is_refused() -> None:
    from perfboard_studio.commands import AddCablePayload
    from perfboard_studio.model import CableEnd, CableWire

    doc = _system()
    a, b = _ends(doc)
    bus = _bus(doc)
    for cable in (
        _cable(doc, b=CableEnd("b9", b.connector)),
        _cable(doc, b=CableEnd("b3", b.connector)),
        _cable(doc, b=a),
        _cable(doc, wires=(CableWire("1", "1"), CableWire("1", "2"))),
    ):
        result = bus.dispatch("cable.add", AddCablePayload(cable=cable))
        assert not result.ok and result.code == "invalid-cable", result.message
    taken = bus.dispatch("cable.add", AddCablePayload(cable=_cable(doc, ref=doc.components[0].ref)))
    assert not taken.ok and taken.code == "duplicate-ref"


def test_a_wire_between_two_different_nets_is_not_refused() -> None:
    """Joining two nets is a mistake in the design, not a broken document: DRC and LVS say
    it. Only what makes the document whole is a command's to refuse."""
    from perfboard_studio.commands import AddCablePayload
    from perfboard_studio.model import CableWire

    doc = _system()
    crossed = _cable(doc, wires=(CableWire("1", "2"), CableWire("2", "1")))
    assert _bus(doc).dispatch("cable.add", AddCablePayload(cable=crossed)).ok


def test_a_board_command_cannot_leave_a_cable_to_nowhere() -> None:
    """Delete the connector a cable is fitted to, or take its board out, and the cable would
    reach nothing: both refused, naming the cable."""
    from perfboard_studio.commands import (
        AddCablePayload,
        DeleteBoardPayload,
        DeleteComponentPayload,
        OnBoardPayload,
        UnplaceComponentPayload,
    )

    doc = _system()
    bus = _bus(doc)
    assert bus.dispatch("cable.add", AddCablePayload(cable=_cable(doc))).ok
    _, b = _ends(doc)
    for type_, payload in (
        ("component.delete", DeleteComponentPayload(id=b.connector)),
        ("component.unplace", UnplaceComponentPayload(id=b.connector)),
    ):
        result = bus.dispatch("board.on", OnBoardPayload(board="b2", type=type_, payload=payload))
        assert not result.ok and result.code == "cable-end" and "W1" in result.message, type_
    gone = bus.dispatch("board.delete", DeleteBoardPayload(board="b2"))
    assert not gone.ok and gone.code == "cable-end" and "W1" in gone.message


def test_a_file_whose_cable_reaches_a_missing_part_is_refused() -> None:
    from perfboard_studio.model import CableEnd

    doc = _system()
    broken = dataclasses.replace(doc, cables=(_cable(doc, id="cable-1", b=CableEnd("b2", "nothing")),))
    result = persist.deserialize_document(persist.serialize_document(broken))
    assert not result.ok and result.code == "unknown-reference"


# ---------------------------------------------------------------------------
# LVS through the cables
# ---------------------------------------------------------------------------


def _two_headers(wires):  # type: ignore[no-untyped-def]
    """Two boards with a 2-pin header each, GND on pin 2 and SIG on pin 1 of both, joined
    by a cable with ``wires`` (or none)."""
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.model import (
        Cable,
        CableEnd,
        ComponentInstance,
        DocumentMeta,
        Net,
        NetNode,
    )

    header_a = ComponentInstance(id="cmp-1", ref="JA", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    header_b = ComponentInstance(id="cmp-2", ref="JB", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    nets = (
        Net(id="n1", name="GND", nodes=(NetNode("JA", "2"), NetNode("JB", "2")), net_class="ground"),
        Net(id="n2", name="SIG", nodes=(NetNode("JA", "1"), NetNode("JB", "1"))),
    )
    cables = (
        ()
        if wires is None
        else (Cable(id="cable-1", ref="W1", a=CableEnd(system.FIRST_BOARD, "cmp-1"), b=CableEnd("b2", "cmp-2"), wires=wires),)
    )
    return PerfDocument(
        meta=DocumentMeta(name="Main", created="", modified=""),
        board_name="Main",
        board=DEFAULT_BOARD,
        components=(header_a,),
        nets=nets,
        boards=(ExtraBoard(id="b2", name="Remote", board=DEFAULT_BOARD, components=(header_b,)),),
        cables=cables,
    )


def test_a_net_across_two_boards_is_open_until_a_cable_carries_it() -> None:
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.lvs import run_system_lvs

    result = run_system_lvs(_two_headers(None), footprint_lookup())
    assert not result.ok
    opens = [issue for issue in result.issues if issue.kind == "open"]
    assert {issue.net_names[0] for issue in opens} == {"GND", "SIG"}
    assert all("across Main and Remote" in issue.message and "cable wire" in issue.message for issue in opens)


def test_a_cable_wired_straight_makes_the_system_whole() -> None:
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.lvs import run_system_lvs
    from perfboard_studio.model import CableWire

    result = run_system_lvs(_two_headers((CableWire("1", "1"), CableWire("2", "2"))), footprint_lookup())
    assert result.ok, [i.message for i in result.issues]
    assert result.matched_nets == result.nets == 2


def test_a_cable_wired_across_is_a_short() -> None:
    """Pin 1 to pin 2 and pin 2 to pin 1: the document is whole (nothing refuses it), and
    LVS says what it is."""
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.lvs import run_system_lvs
    from perfboard_studio.model import CableWire

    result = run_system_lvs(_two_headers((CableWire("1", "2"), CableWire("2", "1"))), footprint_lookup())
    shorts = [issue for issue in result.issues if issue.kind == "short"]
    assert shorts and set(shorts[0].net_names) == {"GND", "SIG"}


# ---------------------------------------------------------------------------
# Whose a command is
# ---------------------------------------------------------------------------


def test_every_command_is_the_systems_the_designs_or_a_boards() -> None:
    """``command_scope`` places every registered command, and the two named sets hold only
    commands that exist: a command added to the bus, or renamed, is one somebody has to
    place -- the window sends a design command to the document and a board's through
    ``board.on``, and a command placed wrong is one done to the wrong thing."""
    from perfboard_studio.commands import DESIGN_COMMANDS, STANDARD_COMMANDS, SYSTEM_COMMANDS

    registered = {definition.type for definition in STANDARD_COMMANDS}
    assert registered >= SYSTEM_COMMANDS and registered >= DESIGN_COMMANDS
    assert not SYSTEM_COMMANDS & DESIGN_COMMANDS
    # The boards and cables, and the one command that spans two boards.
    assert {t for t in registered if t.startswith(("board.", "cable."))} - {
        "board.set", "board.applyPreset", "board.note.add", "board.note.delete", "board.note.update"
    } | {"component.moveToBoard"} == SYSTEM_COMMANDS
    assert {t for t in registered if t.startswith(("net.", "sheet.", "symbol."))} <= DESIGN_COMMANDS


def test_a_design_command_is_refused_on_a_board() -> None:
    """On one board's view a symbol whose part is on another board belongs to nobody, so the
    sheet, the nets and the design's parts are done on the document, never through
    ``board.on``."""
    from perfboard_studio.commands import AddPartPayload, OnBoardPayload

    result = _bus(_system()).dispatch(
        "board.on",
        OnBoardPayload(board="b2", type="part.add", payload=AddPartPayload(ref="R99", value="", footprint_id="r-axial-4")),
    )
    assert not result.ok and result.code == "unknown-command" and "design" in result.message


# ---------------------------------------------------------------------------
# A cable's wires, paired by net
# ---------------------------------------------------------------------------


def _headers(nets):  # type: ignore[no-untyped-def]
    """JA on the first board and JB (3 pins) on the second, with ``nets`` between them."""
    from perfboard_studio.commands import DEFAULT_BOARD
    from perfboard_studio.model import ComponentInstance, DocumentMeta, Net, NetNode

    ja = ComponentInstance(id="cmp-1", ref="JA", value="", footprint_id="hdr-1x3", anchor=HoleCoord(2, 2))
    jb = ComponentInstance(id="cmp-2", ref="JB", value="", footprint_id="hdr-1x3", anchor=HoleCoord(2, 2))
    return PerfDocument(
        meta=DocumentMeta(name="Bench", created="", modified=""),
        board=DEFAULT_BOARD,
        components=(ja,),
        nets=tuple(
            Net(id=f"n{i}", name=name, nodes=tuple(NetNode(ref, pin) for ref, pin in pins))
            for i, (name, pins) in enumerate(nets)
        ),
        boards=(ExtraBoard(id="b2", name="Remote", board=DEFAULT_BOARD, components=(jb,)),),
    )


def test_a_cable_pairs_each_net_one_pin_to_one_pin() -> None:
    from perfboard_studio.model import CableEnd, CableWire

    doc = _headers([("GND", [("JA", "2"), ("JB", "1")]), ("SIG", [("JA", "1"), ("JB", "3")])])
    pairing = system.pair_by_net(doc, CableEnd(system.FIRST_BOARD, "cmp-1"), CableEnd("b2", "cmp-2"))
    assert pairing.wires == (CableWire("1", "3"), CableWire("2", "1")), "by net, not by pin number"
    assert pairing.unpaired == ()


def test_what_is_not_certain_is_left_unpaired_and_said() -> None:
    """A net with no counterpart, and a net on two pins of one connector: neither guessed."""
    from perfboard_studio.model import CableEnd

    doc = _headers([
        ("GND", [("JA", "1"), ("JA", "2"), ("JB", "1")]),
        ("SENSE", [("JA", "3")]),
        ("SIG", [("JB", "3"), ("JA", "9")]),
    ])
    pairing = system.pair_by_net(doc, CableEnd(system.FIRST_BOARD, "cmp-1"), CableEnd("b2", "cmp-2"))
    assert [(w.a_pin, w.b_pin) for w in pairing.wires] == [("9", "3")]
    assert any("GND is on JA pins 1, 2 and JB pin 1" in why for why in pairing.unpaired), pairing.unpaired
    assert "JA pin 3 (SENSE): JB has no pin on SENSE." in pairing.unpaired, pairing.unpaired
