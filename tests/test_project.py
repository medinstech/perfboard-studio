"""Tests for what a project is (src/perfboard_studio/project.py) and for writing one
(src/perfboard_studio/ui/project.py).

The split the two modules are built on is the same one ``recovery.py`` and
``ui/autosave.py`` take, and it is what this file is organised around:

1. WHAT A PROJECT IS is a question about NAMES, so the first half hands strings to
   ``project.py`` and never touches a disk.

2. WRITING ONE has to survive the ordinary failures. A circuit with no parts has no sheet
   to draw and a machine with no offscreen GL has no step images -- so the second half is
   mostly about what happens when an export cannot be made, because a save that stops at
   the first of those is a save that stops working exactly as a project starts to have
   things in it.

3. THE DOCUMENT IS NOT ALLOWED TO SHARE A FAILURE WITH ANYTHING GENERATED. It is the only
   file in a project that cannot be rebuilt.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

# Before PySide6 is imported by anything below: two of the eight exports a project writes
# are drawn by Qt (the schematic PDF and PNG go through ui/export_schematic), so writing
# one needs a QGuiApplication -- and needs it to be able to start with no display. Same
# line, for the same reason, as the one at the top of test_ui.py.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.commands import create_empty_document
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import DocumentMeta, Net, NetNode, PerfDocument, SchematicPart
from perfboard_studio.project import (
    DOCUMENT_SUFFIX,
    EXPORTS,
    OUTPUT_DIR,
    document_in,
    is_project_dir,
    layout_for,
    project_name,
)
from perfboard_studio.ui.project import project_layout, write_project

GOLDEN = Path(__file__).resolve().parents[1] / "tools" / "diffcheck" / "golden"


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication(["perfboard-studio-tests"])
    yield app


def golden(name: str) -> PerfDocument:
    result = persist.deserialize_document((GOLDEN / f"{name}.perf").read_text(encoding="utf-8"))
    assert result.ok, result.message
    return result.document


# ---------------------------------------------------------------------------
# 1. What a project is called
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("NE555 Astable", "ne555-astable"),
        ("NE555 Astable (rev B)", "ne555-astable-rev-b"),
        ("  spaced  out  ", "spaced-out"),
        ("already-fine", "already-fine"),
        ("Bir Ön Yükselteç", "bir-n-y-kselte"),
        ("///", "board"),
        ("", "board"),
    ],
)
def test_a_project_name_is_something_you_could_have_typed(given: str, expected: str) -> None:
    """Lower case, ASCII, hyphens, never empty.

    Narrow on purpose: a project directory gets put in Dropbox, attached to an email,
    handed to a colleague on Windows and checked into git, and the intersection of what
    all of those tolerate is smaller than any one of them.
    """
    assert project_name(given) == expected


def test_a_project_name_never_ends_in_a_hyphen() -> None:
    """A trailing dot or hyphen is legal on Linux and silently dropped by Windows, which
    is how two projects end up sharing a directory."""
    assert not project_name("A very long name that will certainly be cut somewhere " * 3).endswith("-")


def test_a_name_is_short_enough_for_every_export_to_fit_beside_it() -> None:
    layout = layout_for(project_name("x" * 400) + DOCUMENT_SUFFIX)
    longest = max(len(name) for name in layout.exports())
    assert longest < 200


# ---------------------------------------------------------------------------
# 2. What a project holds
# ---------------------------------------------------------------------------


def test_a_folder_with_one_board_is_a_project_and_two_is_not() -> None:
    """A project is a directory built around a board. A directory with two boards in it
    is a folder of boards, and opening it would mean guessing which one was meant."""
    assert is_project_dir(["preamp.perf", "outputs", "netlist.net"])
    assert not is_project_dir(["preamp.perf", "old.perf"])
    assert not is_project_dir(["notes.txt"])

    assert document_in(["preamp.perf", "README.md"]) == "preamp.perf"
    assert document_in(["preamp.perf", "old.perf"]) is None


def test_the_exports_are_named_after_the_file_and_not_after_the_document() -> None:
    """Renaming the .perf and saving again renames its outputs to match, instead of
    leaving a set behind under the old name. ``meta.name`` is what the board calls itself
    and is free to differ."""
    layout = layout_for("preamp.perf")
    assert layout.document == "preamp.perf"
    assert all(name.startswith(f"{OUTPUT_DIR}/preamp-") for name in layout.exports())


def test_every_export_has_its_own_name() -> None:
    """Two specs sharing a suffix would mean one export silently overwriting another."""
    names = [spec.suffix for spec in EXPORTS]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# 3. Writing one
# ---------------------------------------------------------------------------


def test_a_project_save_writes_the_board_and_everything_it_can_generate(tmp_path: Path) -> None:
    document = golden("ne555")
    target = tmp_path / "ne555.perf"

    result = write_project(
        target,
        document,
        persist.serialize_document(document),
        footprint_lookup(),
        scene=None,
    )

    assert result.document.read_text(encoding="utf-8") == persist.serialize_document(document)
    written = {path.name for path in result.written}
    # Everything except the two that need a window: the 1:1 board sheets are printed from
    # the 2D scene, and no scene was handed over here.
    assert "ne555-guide.html" in written
    assert "ne555-bom.csv" in written
    assert "ne555-schematic.svg" in written
    assert all(path.parent.name == OUTPUT_DIR for path in result.written)


def test_the_board_sheets_are_skipped_and_named_when_there_is_no_view_to_print_from(
    tmp_path: Path,
) -> None:
    """Named rather than counted: each line is a file somebody may be looking for."""
    document = golden("ne555")
    result = write_project(
        tmp_path / "ne555.perf",
        document,
        persist.serialize_document(document),
        footprint_lookup(),
        scene=None,
    )
    skipped = dict(result.skipped)
    assert "ne555-board.pdf" in skipped
    assert "board view" in skipped["ne555-board.pdf"]


def test_a_design_with_nothing_drawn_yet_still_saves(tmp_path: Path) -> None:
    """The failure this has to survive. A project is made at the START of a circuit, when
    there is nothing to draw a sheet from -- and a save that raised there would be a save
    that stops working exactly when a project is created."""
    document = create_empty_document(
        DocumentMeta(name="new", created="2026-01-01T00:00:00Z", modified="2026-01-01T00:00:00Z")
    )
    result = write_project(
        tmp_path / "new.perf",
        document,
        persist.serialize_document(document),
        footprint_lookup(),
        scene=None,
    )

    assert result.document.exists()
    skipped = dict(result.skipped)
    assert "new-schematic.svg" in skipped
    assert "no parts" in skipped["new-schematic.svg"]
    # ...and the guide, which is about a board rather than a sheet, is still written.
    assert any(path.name == "new-guide.html" for path in result.written)


def test_a_part_that_is_only_in_the_design_reaches_the_exported_sheet(tmp_path: Path) -> None:
    """A project is saved while the circuit is still being drawn, so the sheet has to be
    of the DESIGN and not only of what is on the board."""
    document = create_empty_document(
        DocumentMeta(name="new", created="2026-01-01T00:00:00Z", modified="2026-01-01T00:00:00Z")
    )
    document = dataclasses.replace(
        document,
        parts=(
            SchematicPart(id="p1", ref="R1", value="10k", footprint_id="r-axial-3"),
            SchematicPart(id="p2", ref="R2", value="10k", footprint_id="r-axial-3"),
        ),
        nets=(
            Net(
                id="n1",
                name="OUT",
                nodes=(NetNode(component_ref="R1", pin="2"), NetNode(component_ref="R2", pin="1")),
                net_class="signal",
            ),
        ),
    )

    result = write_project(
        tmp_path / "new.perf",
        document,
        persist.serialize_document(document),
        footprint_lookup(),
        scene=None,
    )

    sheet = next(path for path in result.written if path.name == "new-schematic.svg")
    assert "R1" in sheet.read_text(encoding="utf-8")


def test_the_document_is_written_before_anything_that_could_fail(tmp_path: Path) -> None:
    """It is the only file in a project that cannot be regenerated, so it is not allowed
    to share a failure with the eight that can."""
    document = golden("sparse")
    target = tmp_path / "sparse.perf"
    outputs = tmp_path / OUTPUT_DIR
    # A FILE where the outputs directory has to go: mkdir cannot succeed, and every export
    # is therefore impossible.
    outputs.write_text("in the way", encoding="utf-8")

    result = write_project(
        target, document, persist.serialize_document(document), footprint_lookup(), scene=None
    )

    assert target.exists()
    assert result.written == ()
    assert len(result.skipped) == len(EXPORTS)


def test_a_document_that_cannot_be_written_raises_rather_than_reporting(tmp_path: Path) -> None:
    """The one failure that is not a report. If the board did not reach the disk the save
    did not happen, and the caller has to be told loudly enough to keep the window open."""
    document = golden("sparse")
    with pytest.raises(OSError):
        write_project(
            tmp_path / "no" / "such" / "folder" / "sparse.perf",
            document,
            persist.serialize_document(document),
            footprint_lookup(),
            scene=None,
        )


def test_saving_twice_replaces_the_generated_files_rather_than_adding_to_them(
    tmp_path: Path,
) -> None:
    """Everything under outputs/ is rewritten from the document, which is what makes it
    safe to delete and pointless to edit."""
    document = golden("ne555")
    target = tmp_path / "ne555.perf"
    text = persist.serialize_document(document)

    first = write_project(target, document, text, footprint_lookup(), scene=None)
    second = write_project(target, document, text, footprint_lookup(), scene=None)

    assert {p.name for p in first.written} == {p.name for p in second.written}
    assert len(list((tmp_path / OUTPUT_DIR).iterdir())) == len(second.written)


def test_the_layout_of_a_saved_project_matches_what_was_written(tmp_path: Path) -> None:
    """One description of a project's shape, and the writer is held to it."""
    document = golden("ne555")
    target = tmp_path / "preamp.perf"
    result = write_project(
        target, document, persist.serialize_document(document), footprint_lookup(), scene=None
    )

    layout = project_layout(target)
    expected = set(layout.exports())
    written = {f"{OUTPUT_DIR}/{path.name}" for path in result.written}
    skipped = {f"{OUTPUT_DIR}/{name}" for name, _why in result.skipped}
    assert written | skipped == expected
