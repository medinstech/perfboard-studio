"""A note on a part (#10): the builder's own reason for it, kept with the board.

What is pinned here: it is saved only when there is one, so a file without notes keeps
every byte it had; it goes where the part goes -- off the board, back on, copied and pasted;
an edit keeps it or clears it on purpose and never by accident; a lock does not cover it;
and the build guide says it at the part's own step, in either language.
"""

from __future__ import annotations

import pytest

from perfboard_studio import persist
from perfboard_studio.commands import UpdateComponentPayload
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.guide import GuideOptions, PartStep, build_guide
from perfboard_studio.mcp.session import BoardSession, new_board
from perfboard_studio.model import HoleCoord

REASON = "10R keeps the doorbell speaker under 190 mA"


def _session() -> BoardSession:
    session = BoardSession(document=new_board(cols=20, rows=10, name="notes"))
    assert session.place_component("R1", "r-axial-3", "B2")["ok"]
    return session


def _note_of(session: BoardSession, ref: str = "R1") -> str:
    part = next((c for c in session.document.components if c.ref == ref), None) or next(
        p for p in session.document.parts if p.ref == ref
    )
    return part.note


def test_a_note_is_saved_only_when_there_is_one() -> None:
    """The stripAxis rule: a part with no note writes no "note" key, which is how all
    fifteen fixtures keep their bytes, and a note that is there reads back as written."""
    session = _session()
    assert '"note"' not in persist.serialize_document(session.document)

    assert session.update_part("R1", note=REASON)["ok"]
    text = persist.serialize_document(session.document)
    assert f'"note": "{REASON}"' in text
    assert persist.parse_document_or_throw(text).components[0].note == REASON


def test_an_edit_keeps_a_note_unless_it_is_given_one() -> None:
    session = _session()
    assert session.update_part("R1", note=f"  {REASON}\n\n")["ok"]
    assert _note_of(session) == REASON  # the blank lines and spaces round it are not kept

    assert session.update_part("R1", value="10R")["ok"]
    assert _note_of(session) == REASON  # an edit that says nothing about it leaves it

    assert session.update_part("R1", note="")["ok"]
    assert _note_of(session) == ""


def test_a_locked_part_takes_a_note() -> None:
    """A lock is about where a part is; the note is about why it is there."""
    session = _session()
    component = session.document.components[0]
    assert session.bus.dispatch(
        "component.update", UpdateComponentPayload(id=component.id, locked=True)
    ).ok

    assert session.update_part("R1", note=REASON)["ok"]
    assert _note_of(session) == REASON


def test_a_note_is_text() -> None:
    session = _session()
    result = session.bus.dispatch(
        "component.update",
        UpdateComponentPayload(id=session.document.components[0].id, note=5),  # type: ignore[arg-type]
    )
    assert not result.ok and result.code == "invalid-note"


def test_the_note_goes_where_the_part_goes() -> None:
    """Off the board into the design and back, as the pin names and the symbol do."""
    session = _session()
    assert session.update_part("R1", note=REASON)["ok"]

    assert session.unplace_component("R1")["ok"]
    assert session.document.parts[0].note == REASON
    assert session.place_parts([{"ref": "R1", "at": "C4"}])["ok"]
    assert session.document.components[0].note == REASON


def test_a_copied_part_pastes_with_its_note() -> None:
    from perfboard_studio.ui.clipboard import block_from_json, block_to_json, paste_payload

    session = _session()
    assert session.update_part("R1", note=REASON)["ok"]
    component = session.document.components[0]

    block = block_from_json(block_to_json(session.document, [component.id]))
    assert block is not None
    paste = paste_payload(session.document, block, HoleCoord(2, 6))
    assert [placed.note for placed in paste.payload.components] == [REASON]


def test_mcp_says_a_note_only_where_there_is_one() -> None:
    session = _session()
    assert "note" not in session.get_component("R1")

    assert session.update_part("R1", note=REASON)["ok"]
    assert session.get_component("R1")["note"] == REASON
    assert session.unplace_component("R1")["ok"]
    [listed] = session.list_parts()["parts"]
    assert listed["note"] == REASON


@pytest.mark.parametrize(("language", "said"), [("en", f"Note: {REASON}"), ("tr", f"Not: {REASON}")])
def test_the_guide_says_the_note_at_the_parts_step(language: str, said: str) -> None:
    """First among the step's notes, in the guide's language around the builder's own
    words, which are theirs and are not translated."""
    session = _session()
    assert session.update_part("R1", note=REASON)["ok"]

    guide = build_guide(session.document, footprint_lookup(), GuideOptions(language=language))  # type: ignore[arg-type]
    [step] = [s for phase in guide.phases for s in phase.steps if isinstance(s, PartStep)]
    assert step.notes[0] == said
