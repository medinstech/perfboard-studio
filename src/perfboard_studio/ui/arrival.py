"""What Play shows of a step arriving: a part coming down into its holes, a run or a wire
laid from its first hole to its last.

Playing the build used to be a slideshow -- every step the whole board was drawn again with
the new part simply there. Now the part arrives: it starts above the board and is lowered
onto its holes, easing out as it lands, so what is being fitted and where it goes are the
motion rather than a caption.

THIS MOVES ACTORS; IT DOES NOT REBUILD THEM. ``view3d.populate_renderer`` draws the step
once, with the new part's solids reported as ``arriving``; the animation sets their
positions and asks for a render, about 4-15 ms a frame on software GL. A 40-step board costs
what a 4-step one does, because nothing is constructed per frame. The part's solder fillets
are left off until it lands, and the window draws the step again once it has -- one more
populate -- so the finished picture is exactly the ordinary one and cannot drift from it.

A conductor is the one thing that IS rebuilt per frame -- its own solids and nothing else, a
tube through a few points, with ``build_conductor(reveal=)`` -- because a line growing along
a path has no cheaper form than the line.

Timing is the wall clock, not a frame count: a slow frame makes the drop choppier, never
longer, and Play's pace does not depend on the machine.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal

from . import motion

#: How long one drop takes. Noticeable on purpose: a drop a third of this read as a part
#: that was merely there.
ARRIVAL_MS = 700

#: How long laying a conductor takes per millimetre of it, within these bounds: a two-hole
#: link is a flick, a long wire is not a crawl.
DRAW_MS_PER_MM = 30
DRAW_MIN_MS = 350
DRAW_MAX_MS = 900

#: How high the part's lowest point starts above the board's component face.
ARRIVAL_HEIGHT_MM = 15.0

#: How long one pulse of the rings round a conductor's two ends takes while it is laid, and how
#: long they fade over once it has landed. The fade is NOT part of the step: Play's hold after a
#: landing is ``MainWindow.ARRIVAL_HOLD_MS`` (200), and a fade no longer than it costs Play
#: nothing -- it ends as the next step begins.
MARK_PULSE_MS = 450
MARK_FADE_MS = 200

#: The gap between frames. 16 ms is a display's rate; a render that takes longer simply
#: runs back to back.
FRAME_MS = 16


def ease_out_cubic(progress: float) -> float:
    """Fast at first and gentle at the end: a part set down, not dropped."""
    return 1.0 - (1.0 - progress) ** 3


def start_lift_mm(actors: Sequence[Any], board_top_z: float) -> float:
    """How far above its place the part starts, so that its LOWEST point -- a lead tip
    under the board counts -- is :data:`ARRIVAL_HEIGHT_MM` above ``board_top_z``."""
    if not actors:
        return 0.0
    lowest: float = min(actor.GetBounds()[4] for actor in actors)
    return max(0.0, board_top_z + ARRIVAL_HEIGHT_MM - lowest)


def draw_duration_ms(length_mm: float) -> int:
    return int(max(DRAW_MIN_MS, min(DRAW_MAX_MS, DRAW_MS_PER_MM * length_mm)))


def ease_out_quad(progress: float) -> float:
    """Quick off the mark and easing at the end: a line is visible from the first frames,
    where an ease-in left a tenth of the time with nothing to see."""
    return 1.0 - (1.0 - progress) ** 2


class ArrivalAnimation(QObject):
    """One step arriving at a time, driven by a timer and finished by a signal."""

    #: The part has landed. Not emitted for a drop that was cancelled.
    finished = Signal()

    def __init__(self, parent: QObject | None = None, *, duration_ms: int = ARRIVAL_MS) -> None:
        super().__init__(parent)
        self.duration_ms = duration_ms
        #: How long the running animation takes: ``duration_ms`` for a drop, the
        #: conductor's own for a drawing. Zero until one starts.
        self._span_ms = 0
        self._actors: list[Any] = []
        self._base: list[tuple[float, float, float]] = []
        self._lift = 0.0
        self._apply: Callable[[float], None] = self._lower
        self._render: Callable[[], None] = lambda: None
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._on_frame)
        #: The rings of a conductor that has landed, fading. A second timer, because the fade
        #: is not the step: ``running`` (what the window asks, and what it cancels) is the
        #: drawing alone, and Play goes on to the next step while the rings are still fading.
        self._marks_pending: tuple[Any, Callable[[float, float], list[Any]], float] | None = None
        self._rings: list[Any] = []
        self._ring_ren: Any = None
        self._fade_render: Callable[[], None] = lambda: None
        self._fade_clock = QElapsedTimer()
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(FRAME_MS)
        self._fade_timer.timeout.connect(self._on_fade_frame)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(
        self,
        actors: Sequence[Any],
        lift_mm: float,
        render: Callable[[], None],
    ) -> bool:
        """Set the part at the top of its drop and begin. False -- and nothing runs -- when
        there is nothing to lower."""
        self.cancel()
        if motion.reduced() or not actors or lift_mm <= 0 or self.duration_ms <= 0:
            return False
        self._actors = list(actors)
        self._base = [actor.GetPosition() for actor in self._actors]
        self._lift = lift_mm
        self._apply = self._lower
        self._render = render
        self.show(0.0)
        self._clock.start()
        self._timer.start()
        return True

    def start_drawing(
        self,
        ren: Any,
        drawing: Any,
        render: Callable[[], None],
        *,
        duration_ms: int | None = None,
    ) -> bool:
        """Take the conductor's whole drawing out of ``ren`` and lay it again from its first
        hole (``drawing`` is a ``view3d.DrawOn``). False, and nothing is touched, when
        there is nothing to draw."""
        self.cancel()
        length = float(drawing.length_mm)
        span = draw_duration_ms(length) if duration_ms is None else duration_ms
        if motion.reduced() or length <= 0 or span <= 0:
            return False
        for actor in drawing.actors:
            ren.RemoveActor(actor)
        laid: list[Any] = []
        rings: list[Any] = []
        marks = getattr(drawing, "marks", None)

        def apply(progress: float) -> None:
            for actor in (*laid, *rings):
                ren.RemoveActor(actor)
            progress = max(0.0, progress)
            laid[:] = drawing.build(ease_out_quad(min(1.0, progress)))
            # Rings on both ends from the first frame, pulsing, until it has landed.
            rings[:] = marks(progress * span / MARK_PULSE_MS, 1.0) if marks is not None else []
            for actor in (*laid, *rings):
                ren.AddActor(actor)

        self._apply = apply
        self._render = render
        self._span_ms = span
        self._marks_pending = (ren, marks, span / MARK_PULSE_MS) if marks is not None else None
        self._fade_render = render
        self.show(0.0)
        self._clock.start()
        self._timer.start()
        return True

    def show(self, progress: float) -> None:
        """Put the step ``progress`` (0 = not there, 1 = in place) of the way in. Also what a
        test calls, to look at a frame without waiting for it."""
        self._apply(progress)

    def _lower(self, progress: float) -> None:
        remaining = self._lift * (1.0 - ease_out_cubic(max(0.0, min(1.0, progress))))
        for actor, (x, y, z) in zip(self._actors, self._base, strict=True):
            actor.SetPosition(x, y, z + remaining)

    def cancel(self) -> None:
        """Stop and let go of the actors, without a signal. For when they are about to be
        thrown away: every redraw of the view replaces them, and a timer still moving the
        old ones would be moving nothing."""
        self._timer.stop()
        self._stop_fade()
        self._marks_pending = None
        self._actors = []
        self._base = []
        self._span_ms = 0

    def _on_frame(self) -> None:
        progress = self._clock.elapsed() / (self._span_ms or self.duration_ms)
        self.show(progress)
        self._render()
        if progress >= 1.0:
            pending = self._marks_pending
            self._timer.stop()
            self.cancel()
            # The window answers this by drawing the step again, which takes the rings out
            # with everything else; they are put back after it, and fade.
            self.finished.emit()
            if pending is not None and not self._timer.isActive():
                self._start_fade(*pending)

    def _start_fade(
        self, ren: Any, marks: Callable[[float, float], list[Any]], end_phase: float
    ) -> None:
        self._stop_fade()
        self._rings = marks(end_phase, 1.0)
        for ring in self._rings:
            ren.AddActor(ring)
        self._ring_ren = ren
        self._fade_clock.start()
        self._fade_timer.start()

    def _stop_fade(self) -> None:
        self._fade_timer.stop()
        ren, rings = self._ring_ren, self._rings
        self._ring_ren, self._rings = None, []
        if ren is not None:
            for ring in rings:
                ren.RemoveActor(ring)

    @property
    def fading(self) -> bool:
        return self._fade_timer.isActive()

    def show_fade(self, progress: float) -> None:
        """The rings ``progress`` (0 = whole, 1 = gone) of the way through fading. Also what a
        test calls. Stops by itself when the scene has been drawn again without them."""
        ren = self._ring_ren
        if ren is None or not self._rings or not ren.HasViewProp(self._rings[0]):
            self._stop_fade()
            return
        for ring in self._rings:
            ring.GetProperty().SetOpacity(max(0.0, 1.0 - progress))

    def _on_fade_frame(self) -> None:
        progress = self._fade_clock.elapsed() / MARK_FADE_MS
        self.show_fade(progress)
        if self._ring_ren is None:
            return
        if progress >= 1.0:
            self._stop_fade()
        self._fade_render()
