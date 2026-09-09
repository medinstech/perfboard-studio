"""Writing a project to disk: the host half of ``project.py``.

``project.py`` says what a project contains and what every file in it is called, without
touching a filesystem. This is the part that has the disk, Qt's PDF writer and VTK -- the
same split as ``recovery.py`` against ``ui/autosave.py``.

**EVERY EXPORT FAILS ON ITS OWN.** A project save writes eight generated files and the
document, and any of them can be impossible for an ordinary reason: a circuit with no parts
yet has no schematic to draw, a machine with no offscreen GL has no step images, a board
with no netlist has nothing for LVS to check. A save that stopped at the first of those
would be a save that stops working exactly as a project starts to have things in it. So
each export is attempted, and the ones that could not be written come back NAMED, with the
reason, for the caller to say out loud.

**THE DOCUMENT IS WRITTEN FIRST AND SEPARATELY.** It is the only file in a project that
cannot be regenerated, so it is not allowed to share a failure with anything that can: if
the board cannot be written the save has failed and nothing else is attempted, and if it
can, the board is safe on disk whatever happens to the eight files after it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.guide import build_guide
from perfboard_studio.guide_export import bom_to_csv, cut_list_to_csv, guide_to_html, guide_to_json
from perfboard_studio.model import PerfDocument
from perfboard_studio.project import EXPORTS, OUTPUT_DIR, ExportSpec, ProjectLayout, layout_for
from perfboard_studio.schematic import build_schematic
from perfboard_studio.schematic_export import drawing_to_svg

from .export_pdf import export_pdf
from .export_schematic import SchematicRenderError, svg_to_pdf, svg_to_png


@dataclass(frozen=True, slots=True)
class ProjectWrite:
    """What a project save actually managed to do."""

    #: The document, always -- a write that did not get this far raises instead.
    document: Path
    #: Generated files, in the order :data:`project.EXPORTS` lists them.
    written: tuple[Path, ...]
    #: ``(file name, why)`` for each generated file that could not be written. Not an
    #: error: a circuit with no parts yet has no sheet to draw, and saying so is the whole
    #: of the right response.
    skipped: tuple[tuple[str, str], ...]

    @property
    def directory(self) -> Path:
        return self.document.parent


def project_layout(document_path: Path) -> ProjectLayout:
    """The layout of the project the document at this path belongs to."""
    return layout_for(document_path.name)


def write_project(
    document_path: Path,
    document: PerfDocument,
    document_text: str,
    lookup: FootprintLookup,
    scene: Any,
    step_images: Mapping[str, bytes] | None = None,
) -> ProjectWrite:
    """Write the document and every export that can be made, beside it.

    ``scene`` is the 2D board scene the 1:1 sheets are printed from, and ``step_images``
    the per-step 3D renders for the guide -- both supplied by the caller because both come
    from a window, and this module is not going to build one. Either may be absent; the
    exports that need them are then skipped and named.

    Raises ``OSError`` if the DOCUMENT cannot be written, and only then. Everything else is
    reported rather than raised.
    """
    layout = project_layout(document_path)
    document_path.write_text(document_text, encoding="utf-8")

    outputs = document_path.parent / OUTPUT_DIR
    written: list[Path] = []
    skipped: list[tuple[str, str]] = []
    try:
        outputs.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        # The board is already safe on disk, which is the point of writing it first.
        return ProjectWrite(
            document=document_path,
            written=(),
            skipped=tuple(
                (spec.name_for(layout.name), f"could not create {OUTPUT_DIR}/: {err}")
                for spec in EXPORTS
            ),
        )

    for spec, produce in _producers(document, lookup, scene, step_images or {}).items():
        target = outputs / spec.name_for(layout.name)
        try:
            result = produce(target)
        except _NothingToWrite as reason:
            skipped.append((target.name, str(reason)))
            continue
        except (OSError, SchematicRenderError, ValueError) as err:
            skipped.append((target.name, str(err)))
            continue
        written.append(result)

    return ProjectWrite(
        document=document_path, written=tuple(written), skipped=tuple(skipped)
    )


class _NothingToWrite(Exception):
    """This export has no subject yet, which is ordinary and not a failure."""


def _producers(
    document: PerfDocument,
    lookup: FootprintLookup,
    scene: Any,
    step_images: Mapping[str, bytes],
) -> dict[ExportSpec, Any]:
    """One writer per export, keyed by its spec.

    The guide and the sheet are each built ONCE and closed over, rather than rebuilt per
    file: ``build_guide`` runs DRC and LVS, and four files asking for it separately would
    pay for that four times and could in principle disagree.
    """
    guide = build_guide(document, lookup)
    drawing = build_schematic(document, lookup)
    svg = drawing_to_svg(drawing, title=document.meta.name) if drawing.symbols else None

    def board_pdf(target: Path) -> Path:
        if scene is None:
            raise _NothingToWrite("no board view to print from")
        return export_pdf(document.board, scene, target)

    def sheet_svg(target: Path) -> Path:
        if svg is None:
            raise _NothingToWrite("the design has no parts to draw yet")
        target.write_text(svg, encoding="utf-8")
        return target

    def sheet_pdf(target: Path) -> Path:
        if svg is None:
            raise _NothingToWrite("the design has no parts to draw yet")
        return svg_to_pdf(svg, target, title=document.meta.name)

    def sheet_png(target: Path) -> Path:
        if svg is None:
            raise _NothingToWrite("the design has no parts to draw yet")
        return svg_to_png(svg, target)

    def text_export(render: Any) -> Any:
        def write(target: Path) -> Path:
            target.write_text(render(), encoding="utf-8")
            return target

        return write

    by_suffix = {
        "-board.pdf": board_pdf,
        "-schematic.svg": sheet_svg,
        "-schematic.pdf": sheet_pdf,
        "-schematic.png": sheet_png,
        "-guide.html": text_export(lambda: guide_to_html(guide, dict(step_images))),
        "-bom.csv": text_export(lambda: bom_to_csv(guide)),
        "-cuts.csv": text_export(lambda: cut_list_to_csv(guide)),
        "-guide.json": text_export(lambda: guide_to_json(guide)),
    }
    return {spec: by_suffix[spec.suffix] for spec in EXPORTS}


__all__ = ["ProjectWrite", "project_layout", "write_project"]
