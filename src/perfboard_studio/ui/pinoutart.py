"""The middle of a pinout card: the part as the board view draws it, alone.

``pinout_export`` is the engine's and imports no Qt, so it cannot draw a part the way the
board view does. This draws it here -- the very ``ComponentItem`` the board shows, with
its module art and its KiCad top view -- into an SVG document whose viewBox is the card's
frame in millimetres, and the engine places that text in the card as it is (``art``).

THE PART IS DRAWN ALONE: on no board, in no scene of the board's. A card is about the
part, and a perfboard's substrate, holes and pad rings behind it read as part of it. So
the item stands in a bare ``QGraphicsScene`` with no background, and a bare chip leaves
out the lead ends the board view paints in its holes: from above it is its body and its
legs. A module keeps its own pins, which are part of its own board.

Colours of the card itself come from the palette at paint time (:func:`card_ink`), so a
card shown in the window follows a theme switch.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, QSize
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import QApplication, QGraphicsScene

from ..catalog import catalog_part
from ..connectivity import FootprintLookup
from ..model import Board, ComponentInstance, HoleCoord
from ..pinout import CARD_PITCH_MM, PinoutCard
from ..pinout_export import PINOUT_DARK, PINOUT_LIGHT, PinoutInk
from .view2d import ComponentItem

#: SVG user units per millimetre of the art: QSvgGenerator writes coordinates as
#: integers in places, so the drawing is made at ten units a millimetre and the viewBox
#: says so.
UNITS_PER_MM = 10.0

#: The board the part is "on": only its pitch is read, and no part of it is drawn.
_BOARD = Board(
    type="pad-per-hole",
    cols=60,
    rows=60,
    pitch=CARD_PITCH_MM,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.9,
    drill_diameter=0.8,
)


class _PartAlone(ComponentItem):
    """The board view's part, without the lead ends it paints into a board's holes when
    it is a bare chip."""

    paints_pin_ends = True

    def _paint_pin_ends(self, painter: QPainter, keyed: tuple[float, float] | None) -> None:
        if self.paints_pin_ends:
            super()._paint_pin_ends(painter, keyed)


def part_art_svg(card: PinoutCard, lookup: FootprintLookup) -> str | None:
    """The part on ``card`` drawn from above as an SVG document, its viewBox the card's
    frame in millimetres; ``None`` when the catalogue or ``lookup`` does not know it."""
    part = catalog_part(card.part_id)
    if part is None:
        return None
    footprint = lookup(part.footprint_id)
    if footprint is None:
        return None
    component = ComponentInstance(
        id="pinout",
        ref="",
        value=part.value or part.name,
        footprint_id=part.footprint_id,
        anchor=HoleCoord(0, 0),
    )
    item = _PartAlone(component, footprint, _BOARD, "top", show_pin_names=False)
    item.show_reference = False
    item.paints_pin_ends = not card.numbered_by_maker
    item.setAcceptHoverEvents(False)
    scene = QGraphicsScene()
    scene.addItem(item)

    x0, x1, y0, y1 = card.frame
    width, height = (x1 - x0) * UNITS_PER_MM, (y1 - y0) * UNITS_PER_MM
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    generator = QSvgGenerator()
    generator.setOutputDevice(buffer)
    generator.setSize(QSize(round(width), round(height)))
    generator.setViewBox(QRectF(0, 0, width, height))
    painter = QPainter(generator)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(painter, QRectF(0, 0, width, height), QRectF(x0, y0, x1 - x0, y1 - y0))
    painter.end()
    scene.removeItem(item)
    return bytes(data.data()).decode("utf-8")


def card_ink(palette: QPalette | None = None) -> PinoutInk:
    """The card's colours for the theme the window is in NOW, and the one family QtSvg
    reads (it parses no list of fallbacks).

    Read from the application's palette, as ``brand`` reads it, not from ``theme.ACTIVE``:
    ``theme.apply`` sets the palette, so a card painted after a theme switch is painted in
    the new one."""
    palette = palette if palette is not None else QApplication.palette()
    window = palette.color(QPalette.ColorRole.Window)
    base = PINOUT_DARK if window.lightnessF() < 0.5 else PINOUT_LIGHT
    return replace(
        base,
        background=window.name(),
        text=palette.color(QPalette.ColorRole.WindowText).name(),
        muted=palette.color(QPalette.ColorRole.PlaceholderText).name(),
        font_family="Segoe UI",
        mono_family="Consolas",
    )


__all__ = ["UNITS_PER_MM", "card_ink", "part_art_svg"]
