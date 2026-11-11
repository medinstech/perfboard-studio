"""Copper on either face of a double-sided board (0.25).

A solder trace may lie on the component side of a board with pads there, and a net may
prefer a face. This file pins what the document holds and what the commands accept; the
router, DRC and the guide each test their own part where they live.
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    KEEP,
    AddConductorPayload,
    AddNetPayload,
    NewSolderTraceConductor,
    UpdateNetPayload,
    create_document_id_generator,
    create_standard_registry,
)
from perfboard_studio.model import (
    HoleCoord,
    PerfDocument,
    SolderTraceConductor,
    has_component_side_copper,
)
from perfboard_studio.ui.clipboard import _new_conductor

REPO = pathlib.Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO / "tools" / "diffcheck" / "golden"
NE555 = GOLDEN_DIR / "ne555.perf"


def _doc() -> PerfDocument:
    return persist.parse_document_or_throw(NE555.read_text(encoding="utf-8"))


def _bus(doc: PerfDocument) -> CommandBus:
    return CommandBus(
        doc, create_standard_registry(), CommandContext(next_id=create_document_id_generator(doc))
    )


def _free_run(doc: PerfDocument) -> tuple[HoleCoord, ...]:
    """Three holes in a row that nothing on the ne555 golden uses: the bottom row's end."""
    row = doc.board.rows - 1
    cols = doc.board.cols
    return tuple(HoleCoord(col, row) for col in range(cols - 3, cols))


def test_no_golden_fixture_has_copper_on_the_component_side() -> None:
    """Every fixture is a dump of the single-face engine, so none holds a top trace and
    every one keeps its bytes; the day a regenerated fixture holds one, this says so."""
    for path in sorted(GOLDEN_DIR.glob("*.perf")):
        doc = persist.parse_document_or_throw(path.read_text(encoding="utf-8"))
        assert not any(
            isinstance(c, SolderTraceConductor) and c.side == "top" for c in doc.conductors
        ), path.name
        assert all(n.preferred_side is None for n in doc.nets), path.name


def test_a_trace_on_the_component_side_is_laid_and_saved_as_it_is() -> None:
    doc = _doc()
    assert has_component_side_copper(doc.board)
    bus = _bus(doc)

    result = bus.dispatch(
        "conductor.add",
        AddConductorPayload(conductor=NewSolderTraceConductor(path=_free_run(doc), side="top")),
    )

    assert result.ok, result.message
    trace = bus.document.conductors[-1]
    assert isinstance(trace, SolderTraceConductor) and trace.side == "top"
    again = persist.parse_document_or_throw(persist.serialize_document(bus.document))
    assert again.conductors[-1] == trace
    assert '"side": "top"' in persist.serialize_document(bus.document)


@pytest.mark.parametrize(
    "change",
    [{"single_sided": True}, {"type": "stripboard"}, {"type": "plain"}, {"type": "breadboard"}],
    ids=["single-sided", "stripboard", "plain", "breadboard"],
)
def test_no_trace_is_laid_on_a_face_with_no_pads(change: dict[str, object]) -> None:
    doc = _doc()
    board = dataclasses.replace(doc.board, **change)  # type: ignore[arg-type]
    doc = dataclasses.replace(doc, board=board)
    assert not has_component_side_copper(board)

    result = _bus(doc).dispatch(
        "conductor.add",
        AddConductorPayload(conductor=NewSolderTraceConductor(path=_free_run(doc), side="top")),
    )

    assert not result.ok
    assert result.code == "no-copper-on-face"


def test_a_file_with_a_top_trace_on_a_single_sided_board_still_opens() -> None:
    """As a conductor off the board does: DRC reports it, the builder keeps their file."""
    doc = _doc()
    trace = SolderTraceConductor(id="t", path=_free_run(doc), side="top")
    doc = dataclasses.replace(
        doc,
        board=dataclasses.replace(doc.board, single_sided=True),
        conductors=(*doc.conductors, trace),
    )

    again = persist.parse_document_or_throw(persist.serialize_document(doc))

    assert again.conductors[-1] == trace


def test_a_nets_preferred_face_is_set_kept_and_cleared_and_left_out_of_the_file_at_none() -> None:
    doc = _doc()
    bus = _bus(doc)
    net = doc.nets[0]
    plain = persist.serialize_document(doc)
    assert "preferredSide" not in plain

    assert bus.dispatch("net.update", UpdateNetPayload(id=net.id, preferred_side="top")).ok
    assert bus.document.nets[0].preferred_side == "top"
    text = persist.serialize_document(bus.document)
    assert '"preferredSide": "top"' in text
    assert persist.parse_document_or_throw(text).nets[0].preferred_side == "top"

    assert bus.dispatch("net.update", UpdateNetPayload(id=net.id, name="RENAMED")).ok
    assert bus.document.nets[0].preferred_side == "top", "KEEP is the default"

    assert bus.dispatch("net.update", UpdateNetPayload(id=net.id, preferred_side=None)).ok
    assert bus.document.nets[0].preferred_side is None
    assert UpdateNetPayload(id=net.id).preferred_side is KEEP

    refused = bus.dispatch("net.update", UpdateNetPayload(id=net.id, preferred_side="left"))  # type: ignore[arg-type]
    assert not refused.ok and refused.code == "invalid-side"


def test_a_new_net_may_say_its_face() -> None:
    bus = _bus(_doc())

    assert bus.dispatch("net.add", AddNetPayload(name="RAIL", preferred_side="bottom")).ok

    assert bus.document.nets[-1].preferred_side == "bottom"


def test_a_copied_trace_keeps_its_face() -> None:
    trace = SolderTraceConductor(id="t", path=(HoleCoord(0, 0), HoleCoord(1, 0)), side="top")

    spec = _new_conductor(trace, trace.path, {})

    assert isinstance(spec, NewSolderTraceConductor) and spec.side == "top"
