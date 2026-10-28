"""What a wheel event means on a canvas: zoom, or pan, and by how much.

Shared by the board (``view2d.BoardView``) and the sheet (``viewsch.SchematicView``), so the
two canvases cannot disagree about a gesture -- the way their selection modifiers once did.

THE WHEEL ALWAYS ZOOMED, and on a laptop that left two fingers on a trackpad zooming the
board instead of moving it. The rule now:

- Ctrl+wheel zooms, from anything. Windows sends a trackpad pinch as exactly that.
- A TRACKPAD PANS, and a trackpad is recognised only by what only a trackpad sends: pixel
  deltas or a scroll phase. That is macOS, and Linux under libinput.
- A wheel zooms, by however far it turned -- a notch is a step, and a smooth or free-spin
  wheel's fraction of a notch is that fraction of a step.
- Shift+wheel, or a wheel tilted sideways, pans sideways.
- ``wheel_scrolls`` (View > Mouse Wheel > Scrolls) makes every wheel pan, and Ctrl zoom.

THE FIRST VERSION GUESSED, and guessed wrong for a common mouse. It read any delta that was
not a whole notch as a trackpad, which is what a Windows precision touchpad sends -- and also
what a Logitech MX-style smooth or free-spin wheel sends. Two mice, two behaviours, and no
way to tell why. What Qt 6.10 actually delivers on Windows was read in its source
(``qwindowspointerhandler.cpp``, ``translateMouseWheelEvent``): a touchpad's scrolling arrives
as WM_MOUSEWHEEL / WM_MOUSEHWHEEL exactly like a mouse's, handed on with a null pixel delta,
no scroll phase and no device of its own. Nothing tells the two apart there, so on Windows a
trackpad zooms like a wheel by default, and the View menu's choice is the way to make it pan.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent

#: One notch of an ordinary mouse wheel, in eighths of a degree (Qt's unit).
NOTCH = 120

#: Pixels panned per notch when a pan carries angle deltas only (a wheel told to scroll, or
#: tilted sideways). About three lines of text, which is what a notch scrolls in a document.
PIXELS_PER_NOTCH = 50.0


@dataclass(frozen=True, slots=True)
class WheelIntent:
    """``zoom_steps`` notches to zoom by (positive is in), or ``pan_x``/``pan_y`` pixels the
    content should move by (positive is right/down). At most one of the two is non-zero."""

    zoom_steps: float = 0.0
    pan_x: float = 0.0
    pan_y: float = 0.0


def is_trackpad(event: QWheelEvent) -> bool:
    """Whether the event says it came from a trackpad: pixel deltas or a scroll phase,
    which no mouse wheel sends. See the module docstring for why nothing else counts."""
    return not event.pixelDelta().isNull() or event.phase() != Qt.ScrollPhase.NoScrollPhase


def wheel_intent(event: QWheelEvent, wheel_scrolls: bool = False) -> WheelIntent:
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
    if wheel_scrolls or is_trackpad(event):
        return WheelIntent(pan_x=dx, pan_y=dy)
    if angle.y() == 0:
        # Tilted sideways: a wheel that means "across", not "closer".
        return WheelIntent(pan_x=dx)
    return WheelIntent(zoom_steps=angle.y() / NOTCH)
