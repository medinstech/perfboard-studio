"""The harness: the cables between a system's boards, as the guide's last steps.

What is pinned: each wire is cut to the cable's length plus a stripped end at each end, or
"to fit" when the cable has no length; it is the colour and the gauge every other wire of
its net gets, unless the cable says; each end is named by its board, its connector and its
pin; every wire is checked end to end and every pair of neighbouring wires on different
nets kept apart, all before power; and the whole of it is said in the guide's language,
calling each board what every other reader calls it.
"""

from __future__ import annotations

import dataclasses

from perfboard_studio import system
from perfboard_studio.commands import DEFAULT_BOARD
from perfboard_studio.guide import GuideOptions
from perfboard_studio.harness import build_harness
from perfboard_studio.model import (
    Cable,
    CableEnd,
    CableWire,
    ComponentInstance,
    DocumentMeta,
    ExtraBoard,
    HoleCoord,
    Net,
    NetNode,
    PerfDocument,
)


def _system(**cable_changes: object) -> PerfDocument:
    """Main's JA and Remote's JB, GND on pin 2 and SIG on pin 1 of both, joined by W1."""
    ja = ComponentInstance(id="cmp-1", ref="JA", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    jb = ComponentInstance(id="cmp-2", ref="JB", value="", footprint_id="hdr-1x2", anchor=HoleCoord(2, 2))
    cable = Cable(
        id="cable-1",
        ref="W1",
        a=CableEnd(system.FIRST_BOARD, "cmp-1"),
        b=CableEnd("b2", "cmp-2"),
        wires=(CableWire("1", "1"), CableWire("2", "2")),
        length_mm=150,
    )
    return PerfDocument(
        meta=DocumentMeta(name="Bench", created="", modified=""),
        board_name="Main",
        board=DEFAULT_BOARD,
        components=(ja,),
        nets=(
            Net(id="n1", name="SIG", nodes=(NetNode("JA", "1"), NetNode("JB", "1"))),
            Net(id="n2", name="GND", nodes=(NetNode("JA", "2"), NetNode("JB", "2")), net_class="ground"),
        ),
        boards=(ExtraBoard(id="b2", name="Remote", board=DEFAULT_BOARD, components=(jb,)),),
        cables=(dataclasses.replace(cable, **cable_changes),),  # type: ignore[arg-type]
    )


def test_a_document_with_no_cable_has_no_harness() -> None:
    doc = dataclasses.replace(_system(), cables=())
    assert build_harness(doc).cables == ()


def test_each_wire_is_cut_to_the_cable_and_said_end_to_end() -> None:
    harness = build_harness(_system())
    (cable,) = harness.cables
    assert cable.ref == "W1" and harness.wire_count == 2
    sig, gnd = cable.wires
    assert sig.cut_mm == gnd.cut_mm == 150 + 2 * GuideOptions().strip_length_mm
    assert gnd.colour == "black", "a ground wire is black, as every ground wire on a board is"
    assert (sig.a.board, sig.a.ref, sig.a.pin) == ("Main", "JA", "1")
    assert (sig.b.board, sig.b.ref, sig.b.pin) == ("Remote", "JB", "1")
    assert sig.net_name == "SIG" and gnd.net_name == "GND"
    assert cable.steps[0] == "Cut 2 wire(s) for W1, 160 mm each with the ends stripped."
    assert "from Main JA pin 2 to Remote JB pin 2" in cable.steps[-1]


def test_every_wire_is_checked_end_to_end_and_kept_apart_before_power() -> None:
    (cable,) = build_harness(_system()).cables
    kinds = [check.kind for check in cable.checkpoints]
    assert kinds == ["continuity", "continuity", "isolation"]
    assert all(check.blocking for check in cable.checkpoints)
    assert cable.checkpoints[0].instruction == "Probe Main JA pin 1 and Remote JB pin 1."
    assert "SIG and GND are different nets" in cable.checkpoints[2].expected


def test_a_cable_with_no_length_is_cut_to_fit() -> None:
    (cable,) = build_harness(_system(length_mm=None)).cables
    assert all(wire.cut_mm is None for wire in cable.wires)
    assert "long enough to reach between the boards" in cable.steps[0]


def test_a_cables_own_colour_and_gauge_win() -> None:
    wires = (CableWire("1", "1", colour="white", gauge_awg=18), CableWire("2", "2"))
    (cable,) = build_harness(_system(wires=wires)).cables
    assert (cable.wires[0].colour, cable.wires[0].awg) == ("white", 18)
    assert cable.wires[1].awg == 24, "no current declared, no gauge stored: the guide's AWG 24"


def test_the_harness_is_said_in_turkish_and_calls_a_board_what_lvs_does() -> None:
    """One name everywhere: the unnamed second board is "Kart 2" in the harness's Turkish
    and "Board 2" in its English, exactly what ``system.board_title`` and LVS's lines say."""
    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.lvs import run_lvs

    doc = _system()
    doc = dataclasses.replace(doc, boards=(dataclasses.replace(doc.boards[0], name=""),))
    (english,) = build_harness(doc).cables
    (turkish,) = build_harness(doc, GuideOptions(language="tr")).cables
    assert english.wires[0].b.board == system.board_title(doc, "b2") == "Board 2"
    assert turkish.wires[0].b.board == system.board_title(doc, "b2", "tr") == "Kart 2"
    assert turkish.steps[0] == "W1 için 2 tel kesin; soyulacak uçlarıyla birlikte her biri 160 mm olsun."
    assert "siyah teli" in turkish.steps[-1]
    unwired = dataclasses.replace(doc, cables=())
    opens = [i.message for i in run_lvs(unwired, footprint_lookup()).issues if i.kind == "open"]
    assert opens and all("Board 2" in message for message in opens)
