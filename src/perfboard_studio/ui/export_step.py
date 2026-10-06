"""The STEP export's host half: the views' colours, the clock and the file.

``step_export.py`` decides what the board IS as solids and writes it as text; it is an
engine module, so it has no clock to stamp the header with and no opinion about colour.
This gives it both -- the colours the 2D view, the 3D view and the guide already share
(``bodies.style_for``, ``boardcolors.scheme_for``), so a resistor is the same beige in the
CAD program it is in the editor -- and puts the result on disk. The window, the headless
run and a project save all come through here, which is what keeps the three files alike.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QColor

from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.model import Board, Footprint, PerfDocument
from perfboard_studio.step_export import Palette, Rgb, document_to_step

from .boardcolors import scheme_for
from .bodies import style_for
from .view3d import LEAD_RGB


def _rgb(colour: str) -> Rgb:
    parsed = QColor(colour)
    return (parsed.redF(), parsed.greenF(), parsed.blueF())


def _body_rgb(footprint: Footprint) -> Rgb:
    return _rgb(style_for(footprint).fill)


def step_palette(board: Board) -> Palette:
    """The colours the 3D view paints this board with, as sRGB -- what STEP reads."""
    return Palette(board=scheme_for(board.material).rgb, lead=LEAD_RGB, body=_body_rgb)


def export_step(doc: PerfDocument, lookup: FootprintLookup, path: Path) -> Path:
    """Write ``doc`` as a STEP file at ``path``. Raises ``OSError`` if it cannot be written.

    ASCII on purpose rather than by accident: ISO 10303-21 is an ASCII format, and
    ``step_export.step_string`` has already escaped every character outside it.
    """
    text = document_to_step(
        doc,
        lookup,
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        palette=step_palette(doc.board),
        file_name=path.name,
    )
    path.write_text(text, encoding="ascii", newline="\n")
    return path


__all__ = ["export_step", "step_palette"]
