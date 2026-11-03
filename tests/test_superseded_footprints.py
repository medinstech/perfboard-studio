"""A part on a footprint the catalog has replaced is said so, and still opens as it was.

The GY-521's footprint drew its board on the wrong side of its header -- the mirror image of
the real module, so one laid over the outline put VCC in INT's hole. The catalog places the
corrected id now, and a document saved with the old one opens exactly as it did: its pins
are where the builder put them, and moving them behind the builder's back is not a fix. DRC's
``superseded-footprint`` says what is wrong and the one step that fixes it, and it stays in
the Problems drawer until that step is taken.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from perfboard_studio.catalog import CATALOG, catalog_part
from perfboard_studio.commands import DEFAULT_BOARD
from perfboard_studio.drc import run_drc
from perfboard_studio.footprints import SUPERSEDED_FOOTPRINTS, footprint_lookup, get_footprint
from perfboard_studio.model import ComponentInstance, DocumentMeta, HoleCoord, PerfDocument
from perfboard_studio.persist import parse_document_or_throw, serialize_document

ROOT = Path(__file__).resolve().parents[1]
OLD_GY521 = "mod-8x1-p1-r1-21.2x16.4x1.5-s8.5-o0x6.7"


def _document(footprint_id: str) -> PerfDocument:
    part = catalog_part("gy-521")
    assert part is not None
    component = ComponentInstance(
        id="imu",
        ref="U4",
        value=part.placed_value,
        footprint_id=footprint_id,
        anchor=HoleCoord(col=4, row=12),
        pin_names=part.pin_names,
    )
    return PerfDocument(
        meta=DocumentMeta(name="imu", created="", modified=""),
        board=DEFAULT_BOARD,
        components=(component,),
    )


def test_a_gy521_on_its_old_footprint_is_said_to_be_on_it() -> None:
    findings = [v for v in run_drc(_document(OLD_GY521), footprint_lookup()) if v.rule == "superseded-footprint"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "warning"
    assert finding.component_ids == ("imu",)
    new_id, _why = SUPERSEDED_FOOTPRINTS[OLD_GY521]
    assert "U4" in finding.message and new_id in finding.message
    assert "VCC in INT's" in finding.message and "Change…" in finding.message


def test_a_gy521_on_the_catalogs_footprint_is_not() -> None:
    part = catalog_part("gy-521")
    assert part is not None and part.footprint_id == SUPERSEDED_FOOTPRINTS[OLD_GY521][0]
    assert not [v for v in run_drc(_document(part.footprint_id), footprint_lookup()) if v.rule == "superseded-footprint"]


def test_a_document_saved_on_the_old_footprint_still_opens_as_it_was() -> None:
    """Loaded, it keeps its id and its footprint: the same pads where they were, the board
    on the side it was drawn on."""
    text = serialize_document(_document(OLD_GY521))
    loaded = parse_document_or_throw(text)
    assert loaded.components[0].footprint_id == OLD_GY521
    assert serialize_document(loaded) == text
    old, new = get_footprint(OLD_GY521), get_footprint(SUPERSEDED_FOOTPRINTS[OLD_GY521][0])
    assert old is not None and new is not None
    # The fix moves nothing a wire is soldered to: the same pins, numbered the same.
    assert [(p.number, p.d_col, p.d_row) for p in old.pins] == [(p.number, p.d_col, p.d_row) for p in new.pins]


@pytest.mark.parametrize("old_id", sorted(SUPERSEDED_FOOTPRINTS))
def test_every_superseded_id_has_a_footprint_that_replaces_it(old_id: str) -> None:
    new_id, why = SUPERSEDED_FOOTPRINTS[old_id]
    assert get_footprint(old_id) is not None, "an old document must still open"
    assert get_footprint(new_id) is not None and new_id != old_id
    assert new_id not in SUPERSEDED_FOOTPRINTS, "a replacement that is replaced itself"
    assert why and not why.endswith(".")  # the end of a sentence the rule finishes


def test_nothing_the_catalog_places_is_superseded() -> None:
    assert [part.id for part in CATALOG if part.footprint_id in SUPERSEDED_FOOTPRINTS] == []


def test_no_fixture_or_example_names_a_superseded_footprint() -> None:
    """A golden fixture or an example on an old id would be a recorded divergence, not a
    quiet one: the day one does, this fails rather than the change going by unremarked."""
    documents = [
        path
        for folder in ("tools/diffcheck/golden", "examples", "tests")
        for path in (ROOT / folder).rglob("*.perf")
    ]
    assert len(documents) > 15
    named = [
        (path.relative_to(ROOT).as_posix(), old_id)
        for path in documents
        for old_id in SUPERSEDED_FOOTPRINTS
        if old_id in path.read_text(encoding="utf-8")
    ]
    assert named == []
