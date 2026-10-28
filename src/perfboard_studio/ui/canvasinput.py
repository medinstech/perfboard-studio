"""What a wheel event means on a canvas: zoom, or pan, and by how much.

Shared by the board (``view2d.BoardView``) and the sheet (``viewsch.SchematicView``), so the
two canvases cannot disagree about a gesture -- the way their selection modifiers once did.

THE WHEEL ALWAYS ZOOMED, and on a laptop that left nothing to pan with. Two fingers on a
trackpad arrive as wheel events, so a vertical swipe zoomed and a sideways one zoomed OUT,
and with no middle button the scrollbars were the only way across a board. The rule now is
the one design tools use:

- Ctrl+wheel zooms, from anything. Windows sends a trackpad pinch as exactly that.
- A mouse wheel turning whole notches zooms, as it always did here (and does in KiCad).
- Anything finer -- a trackpad's pixel deltas, a scroll phase, a sideways component, or a
  vertical delta that is not a whole notch -- pans by the distance the fingers moved.
- Shift+wheel pans sideways.

A high-resolution mouse wheel that reports fractions of a notch is read as a trackpad and
pans; Ctrl+wheel still zooms it. That is the price of telling the two apart on Windows,
where a precision touchpad hands Qt no pixel deltas and no device type of its own -- only
angle deltas that are not multiples of 120.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent

#: One notch of an ordinary mouse wheel, in eighths of a degree (Qt's unit).
NOTCH = 120

#: Pixels panned per notch when a pan carries angle deltas only (Windows trackpads). About
#: three lines of text, which is what a notch scrolls in a document.
PIXELS_PER_NOTCH = 50.0


@dataclass(frozen=True, slots=True)
class WheelIntent:
    """``zoom_steps`` notches to zoom by (positive is in), or ``pan_x``/``pan_y`` pixels the
    content should move by (positive is right/down). Exactly one of the two is non-zero."""

    zoom_steps: float = 0.0
    pan_x: float = 0.0
    pan_y: float = 0.0


def wheel_intent(event: QWheelEvent) -> WheelIntent:
    """Read one wheel event as a zoom or a pan. See the module docstring for the rule."""
    angle = event.angleDelta()
    pixels = event.pixelDelta()
    modifiers = event.modifiers()
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        # A pinch, or Ctrl with the wheel: zoom by whatever the gesture amounts to, so a
        # pinch's many small events add up to about what a notch does.
        delta = angle.y() or angle.x()
        return WheelIntent(zoom_steps=delta / NOTCH)

    if not pixels.isNull():
        dx, dy = float(pixels.x()), float(pixels.y())
    else:
        dx = angle.x() / NOTCH * PIXELS_PER_NOTCH
        dy = angle.y() / NOTCH * PIXELS_PER_NOTCH
    if modifiers & Qt.KeyboardModifier.ShiftModifier and dx == 0:
        # Shift turns a vertical wheel sideways. Some platforms swap the axes themselves
        # before Qt sees the event, which is why this only fills an empty x.
        return WheelIntent(pan_x=dy)

    trackpad = (
        not pixels.isNull()
        or event.phase() != Qt.ScrollPhase.NoScrollPhase
        or angle.x() != 0
        or angle.y() % NOTCH != 0
    )
    if trackpad:
        return WheelIntent(pan_x=dx, pan_y=dy)
    return WheelIntent(zoom_steps=angle.y() / NOTCH)
