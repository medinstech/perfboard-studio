"""What a project is on disk, decided without a filesystem.

The same split as ``recovery.py`` against ``ui/autosave.py`` and ``updates.py`` against
``ui/updater.py``, and for the same reason: every question worth getting right here is a
question about NAMES, so all of it is reachable from a test that hands it strings. What a
project contains, what each file is called, whether a directory is one, what to call a new
one -- none of that needs a disk. ``ui/project.py`` is the host: the reads, the writes and
the Qt-backed exports.

**A PROJECT IS A DIRECTORY, AND THE DOCUMENT INSIDE IT IS STILL AN ORDINARY ``.perf``.**
Not an archive, not a manifest, not a new file format. Three things follow from that and
each is the reason for it:

  - the byte-for-byte format does not move. ``test_persist.py`` asserts that every fixture
    re-serializes to the exact bytes on disk, and a project that wrapped or annotated the
    document would have had to touch it;
  - a project opens in this application by opening the ``.perf`` inside it, and it opens
    in a text editor, a diff and an agent's file tools the same way it always did. PLAN.md
    Sec 9.3 made the document agent-friendly on purpose, and a container would have taken
    that back;
  - anybody can throw the directory away and keep working. A project is a convenience for
    the files that BELONG TOGETHER, not a thing the document depends on.

**THE OUTPUTS ARE GENERATED AND SAY SO.** Everything under ``outputs/`` is rewritten from
the document every time the project is saved, so nothing in there is worth editing and
nothing in there is lost by deleting it. That is why they are in a subdirectory rather than
beside the board: a folder where half the files are yours and half are the tool's is a
folder nobody dares tidy.

**A PROJECT IS NOT REQUIRED.** ``File > Save`` on a bare ``.perf`` works exactly as it did.
This is for the point at which a board has a netlist, a build guide, a bill of materials
and three sheets to print, and they have started arriving in whatever directory the last
dialog happened to open in.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

#: Extension of the document a project is built around. The same one a loose board has.
DOCUMENT_SUFFIX = ".perf"

#: Everything the tool generates lives in here, and is rewritten wholesale on every save.
OUTPUT_DIR = "outputs"

#: Where an imported netlist is kept, so re-importing after a schematic change does not
#: mean finding the file again. An input, so NOT under ``outputs``.
NETLIST_NAME = "netlist.net"

#: What each generated file is, in the order a person meets them. The suffix is appended to
#: the project's own name, so a project called ``preamp`` gets ``preamp-guide.html``.
#:
#: The 1:1 board sheets and the schematic PDF are the two anybody prints, so they come
#: first; the CSVs are what gets opened in a spreadsheet or pasted into an order; the JSON
#: is for whatever comes next, and is the only one written for a machine rather than a
#: person.
ExportKind = Literal["board", "schematic", "guide", "table", "data"]


@dataclass(frozen=True, slots=True)
class ExportSpec:
    """One generated file: what it is called and what it is for."""

    suffix: str
    kind: ExportKind
    description: str

    def name_for(self, project: str) -> str:
        return f"{project}{self.suffix}"


EXPORTS: tuple[ExportSpec, ...] = (
    ExportSpec("-board.pdf", "board", "The board at 1:1, to hold against the real one"),
    ExportSpec("-schematic.svg", "schematic", "The circuit as a vector sheet"),
    ExportSpec("-schematic.pdf", "schematic", "The circuit, to print"),
    ExportSpec("-schematic.png", "schematic", "The circuit, to paste into a message"),
    ExportSpec("-guide.html", "guide", "The build guide, to follow at the bench"),
    ExportSpec("-bom.csv", "table", "What to buy"),
    ExportSpec("-cuts.csv", "table", "Every track cut, in the order they are made"),
    ExportSpec("-guide.json", "data", "The build guide, for another program"),
)


@dataclass(frozen=True, slots=True)
class ProjectLayout:
    """Every path a project has, relative to its own directory.

    Relative on purpose. A layout is a fact about the project's SHAPE, and joining it to
    somewhere on this machine is the host's job -- which is what lets the shape be tested
    without one, and what stops an absolute path from a different machine getting written
    into anything.
    """

    #: The project's name, which is also the stem of its document. See :func:`project_name`.
    name: str

    @property
    def document(self) -> str:
        return f"{self.name}{DOCUMENT_SUFFIX}"

    @property
    def outputs(self) -> str:
        return OUTPUT_DIR

    @property
    def netlist(self) -> str:
        return NETLIST_NAME

    def export(self, spec: ExportSpec) -> str:
        return f"{OUTPUT_DIR}/{spec.name_for(self.name)}"

    def exports(self) -> tuple[str, ...]:
        return tuple(self.export(spec) for spec in EXPORTS)


#: Characters a project name may keep. Everything else becomes a hyphen.
#:
#: Deliberately narrow rather than "whatever this filesystem accepts". A project directory
#: is a thing people put in Dropbox, attach to an email, hand to a colleague on Windows and
#: check into git, and the intersection of what all of those tolerate is smaller than any
#: one of them -- a colon is legal on Linux and unopenable on Windows, and a trailing dot
#: is legal on Linux and silently dropped on Windows.
_SAFE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"

#: What a project is called when the document has no usable name. Not "untitled": a
#: directory called ``untitled`` in a folder of projects is the one nobody can identify.
FALLBACK_NAME = "board"

#: Longest project name kept. Well inside every filesystem's limit once the longest export
#: suffix and the output directory are added on top of it.
MAX_NAME = 60


def project_name(document_name: str) -> str:
    """A project directory name from a document's own name.

    Lower case, ASCII, hyphen-separated, and never empty. A board called
    ``"NE555 Astable (rev B)"`` becomes ``ne555-astable-rev-b``, which is what somebody
    would have typed anyway and what survives being emailed to a stranger.
    """
    kept: list[str] = []
    for character in document_name.strip():
        kept.append(character if character in _SAFE else "-")
    slug = "-".join(part for part in "".join(kept).split("-") if part).lower()
    return (slug[:MAX_NAME].rstrip("-") or FALLBACK_NAME)


def is_project_dir(names: Iterable[str]) -> bool:
    """Whether a directory listing is a project.

    One question: is there exactly one ``.perf`` in it. A project is a directory built
    around a board, and a directory with two boards in it is a folder of boards -- opening
    it would mean guessing which one was meant, which is a guess no dialog should make on
    somebody's behalf.
    """
    return len([name for name in names if name.endswith(DOCUMENT_SUFFIX)]) == 1


def document_in(names: Iterable[str]) -> str | None:
    """The document a project directory is built around, or None if it is not a project."""
    documents = sorted(name for name in names if name.endswith(DOCUMENT_SUFFIX))
    return documents[0] if len(documents) == 1 else None


def layout_for(document_file_name: str) -> ProjectLayout:
    """The layout of the project a given document file belongs to.

    Taken from the FILE NAME rather than from ``meta.name``, and that is the whole of the
    rule: the exports sit next to the document and are named after it, so renaming the
    ``.perf`` and saving again renames its outputs to match instead of leaving a set behind
    under the old name. ``meta.name`` is what the board calls itself and is free to differ.
    """
    stem = document_file_name
    if stem.endswith(DOCUMENT_SUFFIX):
        stem = stem[: -len(DOCUMENT_SUFFIX)]
    return ProjectLayout(name=stem or FALLBACK_NAME)


__all__ = [
    "DOCUMENT_SUFFIX",
    "EXPORTS",
    "FALLBACK_NAME",
    "MAX_NAME",
    "NETLIST_NAME",
    "OUTPUT_DIR",
    "ExportKind",
    "ExportSpec",
    "ProjectLayout",
    "document_in",
    "is_project_dir",
    "layout_for",
    "project_name",
]
