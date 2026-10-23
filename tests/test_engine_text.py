"""Tests for the engine's sentences said in the window's language (ui/engine_text.py).

The load-bearing test is the session: a real document, a real run of nearly every command
and every planner, and every sentence they produced read back in Turkish. A ``describe``
added without a template is exactly a sentence that comes back unchanged, so that is what
fails -- the same drift ``test_i18n`` guards against for the interface's own strings.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.autoroute import describe as describe_route
from perfboard_studio.autoroute import describe_reroute, plan_autoroute, plan_reroute
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    AddBoardNotePayload,
    AddConductorPayload,
    AddEdgeConnectorPayload,
    AddMountingHolePayload,
    AddNetPayload,
    AddPartPayload,
    AddPartsPayload,
    AddSheetNotePayload,
    ApplyBoardPresetPayload,
    AutoSymbolsPayload,
    ConnectPinsPayload,
    DeleteBoardNotesPayload,
    DeleteConductorPayload,
    DeleteConductorsPayload,
    DeleteNetPayload,
    DeletePartPayload,
    DeleteSheetNotesPayload,
    DeleteSheetWiresPayload,
    DisconnectPinsPayload,
    DrawSheetWirePayload,
    ImportNetlistPayload,
    MirrorComponentPayload,
    MoveComponentPayload,
    MoveSymbolsPayload,
    PartPlacement,
    PlacePartsPayload,
    RenameDocumentPayload,
    RotateComponentPayload,
    SetBoardPayload,
    SetHeightLimitPayload,
    UnplaceComponentPayload,
    UpdateComponentPayload,
    UpdateNetPayload,
    UpdatePartPayload,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import STANDARD_PRESETS, board_from_preset
from perfboard_studio.model import HoleCoord, NetNode, Point2, SheetWire, SymbolPlacement
from perfboard_studio.placer import PlacementOptions, plan_placement
from perfboard_studio.placer import describe as describe_placement
from perfboard_studio.ui.engine_text import TEMPLATES, say
from perfboard_studio.ui.i18n import TURKISH, language, set_language

#: A realistic board to run the session on. Any example with an R1 does; this one because
#: its stock board (4 x 6 cm) has a border a finger can reach its hole across -- the NE555
#: moved to a 2 x 8 cm strip whose borders are too wide for the finger the session adds.
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "lm317-supply.perf"
LOOKUP = footprint_lookup()


@pytest.fixture
def turkish() -> Iterator[None]:
    before = language()
    set_language("tr")
    try:
        yield
    finally:
        set_language(before)


def _fields(template: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", template))


def test_every_template_is_in_the_catalogue_with_the_same_fields() -> None:
    """A template without a translation is a sentence that stays English; one whose
    translation dropped a field is a sentence that raises when it is shown."""
    for template in TEMPLATES:
        assert template in TURKISH, f"no Turkish for {template!r}"
        assert _fields(TURKISH[template]) == _fields(template), template


def test_no_two_templates_are_the_same() -> None:
    assert len(set(TEMPLATES)) == len(TEMPLATES)


def test_english_is_left_alone() -> None:
    before = language()
    set_language("en")
    try:
        assert say("Add R1 10k to the schematic") == "Add R1 10k to the schematic"
    finally:
        set_language(before)


def test_a_field_is_only_what_it_may_be(turkish: None) -> None:
    """"Add R1 10k to the schematic" is also "Add {kind} {start} to {end}" with a conductor
    called R1 -- unless a kind can only be one of the six, which is what keeps them apart."""
    assert say("Add R1 10k to the schematic") == "Şemaya R1 10k ekle"
    assert say("Add R1 to the schematic") == "Şemaya R1 ekle"
    assert say("Delete R1 and its 2 connection(s)") == "R1 parçasını ve 2 bağlantısını sil"
    assert say("Delete R1") == "R1 parçasını sil"
    assert say("Place R4 at C7") == "R4 parçasını C7 deliğine yerleştir"


def test_a_sentence_starts_with_a_capital_whatever_field_it_starts_with(turkish: None) -> None:
    """"sol kenara ..." opened a sentence in the undo menu. A clause inside a summary is
    left as it is: it follows a comma."""
    assert say("Add 4-finger edge connector on the left edge").startswith("Sol kenara")
    assert say("3 part(s) placed, about the same connection length").endswith(
        ", bağlantı uzunluğu hemen hemen aynı"
    )


def test_a_conductor_is_named_in_the_guides_own_words(turkish: None) -> None:
    """One vocabulary: the guide calls a bare wire "çıplak tel", and so does the undo menu."""
    from perfboard_studio.guide import conductor_word

    said = say("Add bare-wire C7 to C11")
    assert conductor_word("bare-wire", "tr") in said
    assert "C7" in said and "C11" in said


def test_a_summary_is_translated_clause_by_clause(turkish: None) -> None:
    said = say("14 connection(s) routed across 7/7 nets, 2 needed an insulated wire or jumper")
    assert said == "7/7 nette 14 bağlantı yönlendirildi, 2 tanesi izoleli tel ya da jumper istedi"
    # ...and a clause nobody has a template for stays as it came, beside the ones that do.
    assert say("3 part(s) placed, something new") == "3 parça yerleşti, something new"


# ---------------------------------------------------------------------------
# The session
# ---------------------------------------------------------------------------


def _session() -> list[str]:
    """What a working session says, in the engine's own English, command by command."""
    document = persist.deserialize_document(EXAMPLE.read_text(encoding="utf-8")).document
    bus = CommandBus(
        document,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(document)),
    )
    said: list[str] = []

    def run(kind: str, payload: object) -> None:
        result = bus.dispatch(kind, payload)
        assert result.ok, (kind, result.code, result.message)
        said.append(result.description)

    def component(ref: str):
        return next(c for c in bus.document.components if c.ref == ref)

    def part(ref: str):
        return next(p for p in bus.document.parts if p.ref == ref)

    def net(name: str):
        return next(n for n in bus.document.nets if n.name == name)

    # Copper, planned and committed the way the window does it.
    conductors = bus.document.conductors
    run("conductor.delete", DeleteConductorPayload(id=conductors[0].id))
    run(
        "conductor.deleteMany",
        DeleteConductorsPayload(ids=tuple(c.id for c in bus.document.conductors)),
    )
    routed = plan_autoroute(bus.document, LOOKUP)
    said.append(describe_route(routed))
    first = routed.conductors[0]
    run("conductor.add", AddConductorPayload(conductor=first))
    run("conductor.delete", DeleteConductorPayload(id=bus.document.conductors[-1].id))
    run("conductor.addMany", routed.payload())
    rerouted = plan_reroute(bus.document, LOOKUP)
    said.append(describe_reroute(rerouted))
    run("conductor.replace", rerouted.payload())
    placed = plan_placement(bus.document, LOOKUP, PlacementOptions(seed=0, iterations=200, restarts=1))
    said.append(describe_placement(placed))

    # Parts on the board.
    r1 = component("R1")
    run("component.move", MoveComponentPayload(id=r1.id, anchor=HoleCoord(1, 15)))
    run("component.rotate", RotateComponentPayload(id=r1.id, rotation=90))
    run("component.mirror", MirrorComponentPayload(id=r1.id, mirrored=True))
    run("component.mirror", MirrorComponentPayload(id=r1.id, mirrored=False))
    run("component.update", UpdateComponentPayload(id=r1.id, value="22k"))
    run("component.unplace", UnplaceComponentPayload(id=r1.id))
    run(
        "part.place",
        PlacePartsPayload(placements=(PartPlacement(id=r1.id, anchor=HoleCoord(1, 15), rotation=0),)),
    )

    # The design.
    run("part.add", AddPartPayload(ref="R9", footprint_id="r-axial-3", value="1k"))
    run("part.add", AddPartPayload(ref="R10", footprint_id="r-axial-3"))
    run(
        "part.addMany",
        AddPartsPayload(
            parts=(
                AddPartPayload(ref="R11", footprint_id="r-axial-3"),
                AddPartPayload(ref="R12", footprint_id="r-axial-3"),
            )
        ),
    )
    run("part.update", UpdatePartPayload(id=part("R9").id, value="2k"))
    run(
        "net.add",
        AddNetPayload(
            name="SENSE",
            nodes=(NetNode(component_ref="R9", pin="1"), NetNode(component_ref="R10", pin="1")),
        ),
    )
    run("net.add", AddNetPayload(name="SPARE"))
    run("net.connect", ConnectPinsPayload(id=net("SENSE").id, nodes=(NetNode("R11", "1"),)))
    run(
        "net.connect",
        ConnectPinsPayload(id=net("SENSE").id, nodes=(NetNode("R11", "2"), NetNode("R12", "1"))),
    )
    run("net.disconnect", DisconnectPinsPayload(id=net("SENSE").id, nodes=(NetNode("R11", "2"),)))
    run(
        "net.disconnect",
        DisconnectPinsPayload(
            id=net("SENSE").id, nodes=(NetNode("R10", "1"), NetNode("R11", "1"))
        ),
    )
    run("net.update", UpdateNetPayload(id=net("SENSE").id, name="SENSE2"))
    run("net.update", UpdateNetPayload(id=net("SENSE2").id, net_class="power"))
    run("net.delete", DeleteNetPayload(id=net("SPARE").id))
    run("part.delete", DeletePartPayload(id=part("R12").id))
    run("part.delete", DeletePartPayload(id=part("R10").id))
    run(
        "symbol.move",
        MoveSymbolsPayload(
            placements=(
                SymbolPlacement(id=part("R9").id, at=Point2(10.16, 10.16)),
                SymbolPlacement(id=part("R11").id, at=Point2(40.64, 10.16)),
            )
        ),
    )
    run(
        "symbol.move",
        MoveSymbolsPayload(placements=(SymbolPlacement(id=part("R9").id, at=Point2(12.7, 10.16)),)),
    )
    wire = SheetWire(
        a=NetNode("R9", "2"),
        b=NetNode("R11", "2"),
        path=(Point2(30.48, 15.24), Point2(40.64, 15.24)),
    )
    run("sheet.wire", DrawSheetWirePayload(wire=wire))
    run("sheet.wire.delete", DeleteSheetWiresPayload(wires=bus.document.sheet_wires))
    run("symbol.auto", AutoSymbolsPayload(ids=(part("R9").id,)))
    run("symbol.auto", AutoSymbolsPayload())
    run(
        "sheet.note.add",
        AddSheetNotePayload(kind="rectangle", at=Point2(0.0, 0.0), to=Point2(10.0, 10.0)),
    )
    run(
        "sheet.note.add",
        AddSheetNotePayload(kind="text", at=Point2(0.0, 0.0), to=Point2(0.0, 0.0), text="Input"),
    )
    run(
        "sheet.note.delete",
        DeleteSheetNotesPayload(ids=tuple(n.id for n in bus.document.sheet_notes)),
    )

    # The board itself.
    run("board.note.add", AddBoardNotePayload(text="IN", at=HoleCoord(1, 1)))
    run("board.note.delete", DeleteBoardNotesPayload(ids=tuple(n.id for n in bus.document.board_notes)))
    corner = bus.document.board
    run("mounting-hole.add", AddMountingHolePayload(at=HoleCoord(corner.cols - 1, corner.rows - 2)))
    run("height-limit.set", SetHeightLimitPayload(height_limit_mm=20.0))
    run("height-limit.set", SetHeightLimitPayload(height_limit_mm=None))
    run("document.rename", RenameDocumentPayload(name="Blinker"))
    board = bus.document.board
    run("board.set", SetBoardPayload(board=dataclasses.replace(board, material="FR2")))
    preset = next(p for p in STANDARD_PRESETS if p.cols >= board.cols and p.rows >= board.rows)
    run(
        "board.applyPreset",
        ApplyBoardPresetPayload(board=board_from_preset(preset, board)),
    )
    run(
        "edge-connector.add",
        AddEdgeConnectorPayload(edge="left", start=2, count=4),
    )
    run("netlist.import", ImportNetlistPayload(nets=bus.document.nets))
    return said


def test_everything_a_session_says_comes_out_in_turkish(turkish: None) -> None:
    said = _session()
    assert len(said) >= 40, "the session stopped short of what it is here to exercise"
    untranslated = [
        sentence
        for sentence in said
        if any(say(clause) == clause for clause in sentence.split(", ")) and say(sentence) == sentence
    ]
    assert untranslated == [], untranslated
    # ...and clause by clause, for the planners' summaries.
    leftover = [
        (sentence, clause)
        for sentence in said
        if say(sentence) != sentence
        for clause in say(sentence).split(", ")
        if clause in sentence.split(", ")
    ]
    assert leftover == [], leftover


def _explanations() -> list[str]:
    """What the planners and the router say about what they could NOT do, produced by
    running them on boards where they cannot -- not typed out, so a reworded message
    without a template fails here rather than reaching a Turkish window in English."""
    from perfboard_studio.breadroute import plan_breadboard
    from perfboard_studio.placer import summarize_changes
    from perfboard_studio.router import route_connection

    from .test_breadroute import FULL, TIMER, _part

    said: list[str] = []
    # Two nets in one clip, and a signal down the + rail.
    clipped = dataclasses.replace(
        TIMER, components=(_part("U1", "dip-8", "e11", rotation=0), *TIMER.components[1:])
    )
    said += [p.message for p in plan_breadboard(clipped, LOOKUP).problems]
    railed = dataclasses.replace(
        TIMER, components=(*TIMER.components[:2], _part("R2", "r-axial-4", "T+21"))
    )
    said += [p.message for p in plan_breadboard(railed, LOOKUP).problems]
    assert {"cannot-separate", "wrong-rail"} <= {
        p.code for d in (clipped, railed) for p in plan_breadboard(d, LOOKUP).problems
    }

    # Two pins sharing a strip with no hole between them to cut.
    doc = persist.deserialize_document(EXAMPLE.read_text(encoding="utf-8")).document
    strips = dataclasses.replace(doc.board, type="stripboard", strip_axis="horizontal")
    from perfboard_studio.striproute import plan_stripboard

    stripped = dataclasses.replace(doc, board=strips, conductors=(), cuts=(), edge_connectors=(), mounting_holes=())
    said += [p.message for p in plan_stripboard(stripped, LOOKUP).problems]

    # The placement dialog's list of moves, one turned and one not, and the "more" line.
    import types

    from perfboard_studio.placer import PlacementChange

    moves = types.SimpleNamespace(
        changes=[
            PlacementChange("c1", "C1", HoleCoord(0, 18), HoleCoord(4, 28), 0, 270),
            PlacementChange("r1", "R1", HoleCoord(1, 12), HoleCoord(3, 12), 90, 90),
            PlacementChange("r2", "R2", HoleCoord(2, 12), HoleCoord(5, 12), 90, 90),
        ]
    )
    said += summarize_changes(moves, limit=2, board=FULL)  # type: ignore[arg-type]

    # Two connections the router refuses outright.
    from perfboard_studio.router import RouteRequest

    said.append(route_connection(doc, LOOKUP, RouteRequest(from_=HoleCoord(1, 1), to=HoleCoord(1, 1))).reason or "")
    said.append(route_connection(doc, LOOKUP, RouteRequest(from_=HoleCoord(-1, 0), to=HoleCoord(1, 1))).reason or "")
    return [line for line in said if line]


def test_what_the_planners_could_not_do_comes_out_in_turkish(turkish: None) -> None:
    said = _explanations()
    assert len(said) >= 5, said
    untranslated = [line for line in said if say(line) == line]
    assert untranslated == [], untranslated



def test_the_refusals_a_person_meets_are_said_in_turkish(turkish: None) -> None:
    """A refusal reached the status bar as "[two-nets] U1.8 is on N1 ..." -- English in a
    Turkish window, behind a code nobody reading it has a use for. Each refusal here is
    produced by the real command, so a sentence reworded in the engine shows up as one that
    no longer matches its template, rather than as English nobody noticed."""
    result = persist.deserialize_document(EXAMPLE.read_text(encoding="utf-8"))
    bus = CommandBus(
        result.document,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(result.document)),
    )
    document = bus.document
    first, second = document.components[0], document.components[1]
    net_a, net_b = document.nets[0], document.nets[1]
    a, b = net_a.nodes[0], net_b.nodes[0]
    path = (Point2(x=0, y=0), Point2(x=5, y=0))
    refusals = [
        bus.dispatch("sheet.wire", DrawSheetWirePayload(wire=SheetWire(a=a, b=b, path=path))),
        bus.dispatch("part.add", AddPartPayload(ref=first.ref, footprint_id="r-axial-3")),
        bus.dispatch(
            "component.move", MoveComponentPayload(id=first.id, anchor=HoleCoord(col=500, row=2))
        ),
        bus.dispatch("net.connect", ConnectPinsPayload(id=net_a.id, nodes=(b,))),
        bus.dispatch("net.add", AddNetPayload(name=net_b.name)),
        bus.dispatch("net.update", UpdateNetPayload(id=net_a.id, name=net_b.name)),
    ]
    assert bus.dispatch(
        "component.update", UpdateComponentPayload(id=second.id, locked=True)
    ).ok
    refusals.append(
        bus.dispatch(
            "component.move", MoveComponentPayload(id=second.id, anchor=HoleCoord(col=1, row=1))
        )
    )
    for refusal in refusals:
        assert not refusal.ok
        assert say(refusal.message) != refusal.message, refusal.message


def test_a_finding_names_copper_by_its_ends() -> None:
    """"Top jumper cond-14 (d27 to c33) ... [axis-aligned bounding-box check]": the id is
    the document's handle and the bracket is the checker talking about itself. The panel
    shows the ends, and only for the ids the finding carries."""
    from perfboard_studio.ui.engine_text import finding_text

    said = finding_text(
        "Top jumper cond-14 (d27 to c33) passes under J1, which is 10 mm tall and covers c27 "
        "[axis-aligned bounding-box check]. Solder the jumper before fitting J1.",
        {"cond-14": "d27\u2013c33"},
    )
    assert said == (
        "Top jumper d27\u2013c33 passes under J1, which is 10 mm tall and covers c27. "
        "Solder the jumper before fitting J1."
    )
    # A bare id gets its ends, and an id that only starts the same is another conductor.
    assert finding_text("Solder trace cond-2 meets cond-21.", {"cond-2": "C1\u2013C4"}) == (
        "Solder trace C1\u2013C4 meets cond-21."
    )



def test_every_finding_template_is_in_the_catalogue_with_the_same_fields() -> None:
    from perfboard_studio.ui.engine_text import FINDING_TEMPLATES

    assert len(set(FINDING_TEMPLATES)) == len(FINDING_TEMPLATES)
    for template in FINDING_TEMPLATES:
        assert template in TURKISH, f"no Turkish for {template!r}"
        assert _fields(TURKISH[template]) == _fields(template), template


def test_every_finding_on_every_board_is_said_in_turkish(turkish: None) -> None:
    """Every DRC and LVS finding on every board in the repository, as the panel shows it:
    with its copper named by its ends, and in Turkish. A rule added, or a message reworded,
    without its template shows up here as the English it would have shown."""
    from perfboard_studio.drc import run_drc
    from perfboard_studio.lvs import run_lvs
    from perfboard_studio.ui.engine_text import finding_text, names_in

    root = Path(__file__).resolve().parents[1]
    boards = sorted((root / "tools" / "diffcheck" / "golden").glob("*.perf"))
    boards += sorted((root / "examples").rglob("*.perf"))
    untranslated: dict[str, str] = {}
    seen: set[str] = set()
    for path in boards:
        document = persist.deserialize_document(path.read_text(encoding="utf-8")).document
        for bare in (False, True):
            # And unrouted, where the findings are the ones a board just placed has.
            doc = dataclasses.replace(document, conductors=()) if bare else document
            drc = run_drc(doc, LOOKUP)
            violations = drc.violations if hasattr(drc, "violations") else drc
            lvs = run_lvs(doc, LOOKUP)
            found = [(v.rule, v.message, v.conductor_ids) for v in violations]
            found += [(i.kind, i.message, i.conductor_ids) for i in lvs.issues]
            for rule, message, conductor_ids in found:
                seen.add(rule)
                names = names_in(doc, message, conductor_ids)
                shown = finding_text(message, names)
                set_language("en")
                english = finding_text(message, names)
                set_language("tr")
                assert not re.search(r"\bcond-\d+|\bcmp-\d+", english), english
                if shown == english:
                    untranslated.setdefault(rule, english)
    assert not untranslated, untranslated
    # The boards reach most rules; the ones no board reaches are pinned by the template test.
    assert {"pin-not-connected", "solder-trace-proximity", "unrouted-net"} <= seen
