from dataclasses import replace
import json

import pytest

from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import AddCutPayload, create_document_id_generator, create_standard_registry
from perfboard_studio.guide import build_guide
from perfboard_studio.guide_export import guide_to_html
from perfboard_studio.model import Board, DocumentMeta, HoleCoord, PerfDocument, TrackCut
from perfboard_studio.persist import parse_document_or_throw, serialize_document
from perfboard_studio.stripboard import cut_holes, joined_by_board, segment_holes, segment_of, segments


def document(axis="horizontal"):
    board = Board(type="stripboard", cols=5, rows=5, pitch=2.54, thickness=1.6,
                  material="FR2", pad_diameter=1.9, drill_diameter=1.0, strip_axis=axis)
    return PerfDocument(meta=DocumentMeta(name="test", created="2026-01-01T00:00:00Z",
                                         modified="2026-01-01T00:00:00Z"), board=board)


@pytest.mark.parametrize("axis,a,b", [
    ("horizontal", HoleCoord(1, 2), HoleCoord(2, 2)),
    ("vertical", HoleCoord(2, 1), HoleCoord(2, 2)),
])
def test_between_cut_preserves_both_holes_and_splits_copper(axis, a, b):
    doc = replace(document(axis), cuts=(TrackCut(id="one", at=a, to=b),))
    assert cut_holes(doc) == frozenset()
    assert segment_of(doc, a) is not None and segment_of(doc, b) is not None
    assert not joined_by_board(doc, a, b)
    assert b not in segment_holes(doc, a)
    for segment in segments(doc):
        for hole in segment.holes:
            assert segment_of(doc, hole) == segment.id


def test_roundtrip_and_legacy_hole_cut():
    a, b = HoleCoord(1, 2), HoleCoord(2, 2)
    doc = replace(document(), cuts=(TrackCut(id="gap", at=a, to=b),
                                    TrackCut(id="old", at=HoleCoord(3, 1))))
    restored = parse_document_or_throw(serialize_document(doc))
    assert json.loads(serialize_document(doc))["formatVersion"] == 2
    assert json.loads(serialize_document(document()))["formatVersion"] == 1
    assert set(restored.cuts) == set(doc.cuts)
    assert segment_of(restored, HoleCoord(3, 1)) is None
    guide = build_guide(restored, lambda _name: None)
    gap = next(cut for cut in guide.track_cuts if cut.to is not None)
    assert gap.separates == (a, b)
    assert "B3" in guide_to_html(guide) and "C3" in guide_to_html(guide)


def test_command_rejects_wrong_axis_and_duplicate():
    doc = document()
    bus = CommandBus(doc, create_standard_registry(),
                     CommandContext(next_id=create_document_id_generator(doc)))
    a, b = HoleCoord(1, 2), HoleCoord(2, 2)
    assert bus.dispatch("cut.add", AddCutPayload(at=a, to=b)).ok
    assert not bus.dispatch("cut.add", AddCutPayload(at=b, to=a)).ok
    assert not bus.dispatch("cut.add", AddCutPayload(at=a, to=HoleCoord(1, 3))).ok
