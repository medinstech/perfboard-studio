"""A board as a picture: for the dialogs that choose one, before it is the board on screen.

THE BOARD WAS CHOSEN FROM WORDS. "5 x 7 cm · 18 × 24" in a combo box, and "fits, 29 %
full" in a list, while the thing being chosen is a physical object with finger strips down
two edges, a screw hole in each corner and a printed legend -- and, in the size question,
with the circuit laid out on it, which is the one fact that separates the size to buy from
the one that merely fits. Both dialogs now show it.

DRAWN BY THE BOARD VIEW ITSELF, not by a second painter. ``BoardScene`` is what the editor
shows and what the 1:1 print and the headless PNG render, so a preview built from it cannot
disagree with the board the user gets after pressing OK -- the fingers are where the view
will put them because it is the view putting them there.
"""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from perfboard_studio.boardfamily import BoardPreset
from perfboard_studio.command import CommandContext, CommandError
from perfboard_studio.commands import (
    PartPlacement,
    PlacePartsPayload,
    create_document_id_generator,
    document_on_preset,
    place_parts,
    preset_payload,
)
from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.geometry import board_outline_mm
from perfboard_studio.model import Board, BoardSide, PerfDocument
from perfboard_studio.placer import Arrangement

from .view2d import BoardScene


def render_board(
    document: PerfDocument, lookup: FootprintLookup, size: QSize, side: BoardSide = "top"
) -> QPixmap:
    """One side of ``document``'s board -- the component side unless asked -- fitted into
    ``size``, as the editor draws it, without the ruler, the ratsnest or anything else that
    is about editing. A single-sided board is worth seeing from ``"bottom"``: its component
    side has no copper at all, and its rings, edge pads and letters are on the other."""
    outline = board_outline_mm(document.board)
    scale = min(size.width() / outline.width, size.height() / outline.height)
    width, height = max(1, round(outline.width * scale)), max(1, round(outline.height * scale))
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    scene = BoardScene(
        document,
        lookup,
        side=side,
        show_ratsnest=False,
        show_rulers=False,
        show_pin_names=False,
        show_references=False,
    )
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(
        painter,
        QRectF(0, 0, width, height),
        QRectF(outline.x, outline.y, outline.width, outline.height),
        Qt.AspectRatioMode.KeepAspectRatio,
    )
    painter.end()
    return QPixmap.fromImage(image)


def with_board(
    document: PerfDocument, board: Board, preset: BoardPreset | None
) -> PerfDocument:
    """``document`` on ``board``, with the finger strips and corner holes a product comes
    with -- what ``board.applyPreset`` makes of it (``commands.document_on_preset``).

    A picture of a board the command would refuse -- a part already down that the smaller
    grid strands -- is still a picture of that board: it is drawn with the preset's features
    swapped in by hand, and the dialog says why it cannot be chosen.
    """
    if preset is None:
        return dataclasses.replace(document, board=board)
    try:
        return document_on_preset(document, preset, board)
    except CommandError:
        payload = preset_payload(preset, board)
        return dataclasses.replace(
            document,
            board=board,
            edge_connectors=payload.edge_connectors,
            mounting_holes=payload.mounting_holes,
        )


def with_arrangement(document: PerfDocument, arrangement: Arrangement) -> PerfDocument:
    """``document`` with its design parts put where ``arrangement`` says, through the real
    ``part.place`` -- so the picture is of the board placing would produce, not a guess."""
    if not arrangement.placements:
        return document
    payload = PlacePartsPayload(
        placements=tuple(
            PartPlacement(id=p.id, anchor=p.anchor, rotation=p.rotation)
            for p in arrangement.placements
        ),
        label="preview",
    )
    try:
        return place_parts.apply(
            document, payload, CommandContext(next_id=create_document_id_generator(document))
        )
    except CommandError:
        # A preview that cannot be drawn with the parts on it is drawn without them: the
        # board is still the answer to which board, and the list says what did not fit.
        return document
