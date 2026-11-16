"""What the sheet says it could not draw (``SchematicDrawing.notes``) is English in the engine,
as every engine sentence is, and said in the window's language where it is shown: the sheet
panel's summary line. The walk found "GND: only one pin, so it is drawn as a stub" in English
in a Turkish window.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.commands import DisconnectPinsPayload
from perfboard_studio.footprints import get_footprint
from perfboard_studio.schematic import build_schematic
from perfboard_studio.ui.engine_text import say
from perfboard_studio.ui.i18n import language, set_language

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def turkish() -> Iterator[None]:
    before = language()
    set_language("tr")
    try:
        yield
    finally:
        set_language(before)


def _with_a_one_pin_net():
    """nano-relay with COIL taken down to one pin, so the sheet draws it as a stub."""
    from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
    from perfboard_studio.commands import create_standard_registry

    text = (EXAMPLES / "nano-relay.perf").read_text(encoding="utf-8")
    bus = CommandBus(
        persist.deserialize_document(text).document,
        create_standard_registry(),
        CommandContext(next_id=create_id_generator(1000)),
    )
    coil = next(net for net in bus.document.nets if net.name == "COIL")
    assert bus.dispatch(
        "net.disconnect", DisconnectPinsPayload(id=coil.id, nodes=coil.nodes[1:])
    ).ok
    return bus.document


def test_a_one_pin_net_is_said_in_turkish(turkish: None) -> None:
    notes = build_schematic(_with_a_one_pin_net(), get_footprint).notes
    assert "COIL: only one pin, so it is drawn as a stub" in notes
    said = say("COIL: only one pin, so it is drawn as a stub")
    assert said == "COIL: tek pini var, bu yüzden kısa bir uç olarak çizildi"


@pytest.mark.parametrize(
    "note",
    [
        "GND: no pin of this net could be drawn",
        "GND: U1 pin 7 is not on the sheet",
        "X9: wired by a net, but neither on the board nor in the design",
        "U3: footprint 'dip-99' is not in the registry",
        "U1: the netlist names pin(s) 9, 10, which dip-8 does not have",
        "U1: names pin(s) 9, which dip-8 does not have",
        "2 part(s) have no place on this sheet yet and are parked at the right-hand edge: R1, R2",
    ],
)
def test_every_note_the_sheet_makes_is_said(turkish: None, note: str) -> None:
    assert say(note) != note, note


def test_the_summary_line_says_the_notes_in_the_windows_language(turkish: None) -> None:
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui.main import MainWindow

    QApplication.instance() or QApplication([])
    window = MainWindow(_with_a_one_pin_net())
    try:
        window.show_schematic()
        window._refresh_schematic_panel()
        summary = window.schematic_summary.text()
        assert "COIL: tek pini var" in summary, summary
        assert "drawn as a stub" not in summary
    finally:
        window._mark_saved()
        window.close()
