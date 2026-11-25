"""Non-blocking floating toast notifications stacked in the bottom-right of the window.

Toasts carry brief operational feedback (saved, wired, arranged, reduced motion toggled)
with an optional single action button wired to an existing command (such as Undo or Show
Problems). Destructive confirmations and error dialogs stay modal on ``MainWindow._confirm``
and ``QMessageBox``; toasts never replace a question the user must answer.

Painting note: Qt permits only one ``QGraphicsEffect`` per widget, so ``ToastCard`` paints
both its soft multi-layer shadow and its animated ``opacity`` property directly in
``paintEvent`` rather than stacking a drop-shadow effect with an opacity effect.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QEnterEvent, QFont, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from . import motion, theme
from .i18n import t

type ToastKind = Literal["info", "success", "warning", "danger"]

#: Maximum simultaneous floating toasts; a new arrival evicts the oldest.
MAX_VISIBLE = 3

#: Animation durations (ms), collapsed to 0 under Reduce Motion.
_ENTER_MS = 200
_EXIT_MS = 160
_REFLOW_MS = 180

#: Shadow padding reserved around the painted card inside ``ToastCard``'s geometry.
_SHADOW_PAD = 8
_SLIDE_OFFSET_PX = 14


def _semantic_hex(kind: ToastKind) -> tuple[str, str]:
    """(accent_hex, subtle_hex) for the toast's semantic stripe and badge."""
    tokens = theme.ACTIVE
    return {
        "info": (tokens.accent, tokens.accent_subtle),
        "success": (tokens.success, tokens.success_subtle),
        "warning": (tokens.warning, tokens.warning_subtle),
        "danger": (tokens.danger, tokens.danger_subtle),
    }[kind]


class _StatusGlyph(QWidget):
    """Crisp 18x18 painted semantic mark (tick, i, !, ×) matching the step bar's style."""

    def __init__(self, kind: ToastKind, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind: ToastKind = kind
        self.setFixedSize(18, 18)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent_hex, subtle_hex = _semantic_hex(self._kind)
        accent = QColor(accent_hex)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(subtle_hex))
        painter.drawEllipse(QRectF(0.5, 0.5, 17.0, 17.0))
        if self._kind == "success":
            pen = QPen(accent, 1.9)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline([QPointF(5.2, 9.4), QPointF(8.0, 12.2), QPointF(13.0, 6.2)])
        else:
            font = QFont()
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(accent)
            glyph = "i" if self._kind == "info" else "!"
            painter.drawText(QRectF(0, 0, 18, 18), Qt.AlignmentFlag.AlignCenter, glyph)
        painter.end()


class ToastCard(QWidget):
    """One floating notification pill with a semantic stripe, optional action, and close button."""

    closed = Signal(object)

    def __init__(
        self,
        message: str,
        *,
        kind: ToastKind = "info",
        duration_ms: int = 4200,
        action_label: str | None = None,
        action: Callable[[], object] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toastCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._kind: ToastKind = kind
        self._message = message
        self._opacity = 1.0
        self._dismissing = False
        self._hovered = False
        self._remaining_ms = max(0, duration_ms)
        self._anim: QParallelAnimationGroup | None = None
        self._slide_anim: QPropertyAnimation | None = None

        layout = QHBoxLayout(self)
        # Extra left margin clears the 3px semantic stripe inside the painted card.
        layout.setContentsMargins(
            _SHADOW_PAD + 14, _SHADOW_PAD + 8, _SHADOW_PAD + 8, _SHADOW_PAD + 8
        )
        layout.setSpacing(10)

        self._glyph = _StatusGlyph(kind, self)
        layout.addWidget(self._glyph, 0, Qt.AlignmentFlag.AlignVCenter)

        self.label = QLabel(message, self)
        self.label.setObjectName("toastMessage")
        self.label.setWordWrap(True)
        max_text_w = 240 if (action_label and action is not None) else 280
        text_w = self.label.fontMetrics().horizontalAdvance(message)
        if text_w <= max_text_w:
            self.label.setWordWrap(False)
        else:
            self.label.setFixedWidth(max_text_w)
        self.label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.label, 1, Qt.AlignmentFlag.AlignVCenter)

        self.action_button: QPushButton | None = None
        if action_label and action is not None:
            btn = QPushButton(action_label, self)
            btn.setObjectName("toastAction")
            btn.setProperty("toastKind", kind)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFlat(True)

            def _trigger() -> None:
                action()
                self.dismiss()

            btn.clicked.connect(_trigger)
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
            self.action_button = btn

        self.close_button = QToolButton(self)
        self.close_button.setObjectName("toastClose")
        self.close_button.setText("×")
        self.close_button.setToolTip(t("Dismiss"))
        self.close_button.setAutoRaise(True)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFixedSize(20, 20)
        self.close_button.clicked.connect(self.dismiss)
        layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        if self._remaining_ms > 0:
            self._timer.start(self._remaining_ms)

        self.adjustSize()

    @property
    def kind(self) -> ToastKind:
        return self._kind

    @property
    def message(self) -> str:
        return self._message

    @property
    def is_dismissing(self) -> bool:
        return self._dismissing

    def _get_card_opacity(self) -> float:
        return self._opacity

    def _set_card_opacity(self, value: float) -> None:
        clamped = max(0.0, min(1.0, float(value)))
        if clamped != self._opacity:
            self._opacity = clamped
            self.update()

    card_opacity = Property(float, _get_card_opacity, _set_card_opacity)

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hovered = True
        if self._timer.isActive():
            self._remaining_ms = max(0, self._timer.remainingTime())
            self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        if not self._dismissing and self._remaining_ms > 0:
            self._timer.start(max(self._remaining_ms, 1200))
        super().leaveEvent(event)

    def present_at(self, target: QPoint) -> None:
        """Show the toast at ``target``, sliding in from below when motion is enabled."""
        dur = motion.duration(_ENTER_MS)
        if dur <= 0:
            self._opacity = 1.0
            self.move(target)
            self.show()
            self.raise_()
            return
        start = QPoint(target.x(), target.y() + _SLIDE_OFFSET_PX)
        self._opacity = 0.0
        self.move(start)
        self.show()
        self.raise_()

        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"card_opacity", group)
        fade.setDuration(dur)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        slide = QPropertyAnimation(self, b"pos", group)
        slide.setDuration(dur)
        slide.setStartValue(start)
        slide.setEndValue(target)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(fade)
        group.addAnimation(slide)

        def _done() -> None:
            self._opacity = 1.0
            self._anim = None
            self.update()

        group.finished.connect(_done)
        self._anim = group
        group.start()

    def move_to(self, target: QPoint, *, animate: bool = True) -> None:
        """Reposition an existing toast (for stack reflow or parent resize)."""
        if self._dismissing:
            return
        if self._slide_anim is not None:
            self._slide_anim.stop()
            self._slide_anim = None
        dur = motion.duration(_REFLOW_MS) if animate else 0
        if dur <= 0 or self.pos() == target:
            self.move(target)
            return
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(dur)
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: setattr(self, "_slide_anim", None))
        self._slide_anim = anim
        anim.start()

    def dismiss(self, *, immediate: bool = False) -> None:
        if self._dismissing:
            return
        self._dismissing = True
        self._timer.stop()
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        if self._slide_anim is not None:
            self._slide_anim.stop()
            self._slide_anim = None
        dur = 0 if immediate else motion.duration(_EXIT_MS)
        if dur <= 0:
            self._finish_close()
            return
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"card_opacity", group)
        fade.setDuration(dur)
        fade.setStartValue(self._opacity)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InCubic)
        slide = QPropertyAnimation(self, b"pos", group)
        slide.setDuration(dur)
        slide.setStartValue(self.pos())
        slide.setEndValue(QPoint(self.x(), self.y() + 8))
        slide.setEasingCurve(QEasingCurve.Type.InCubic)
        group.addAnimation(fade)
        group.addAnimation(slide)
        group.finished.connect(self._finish_close)
        self._anim = group
        group.start()

    def _finish_close(self) -> None:
        self._anim = None
        self.hide()
        self.closed.emit(self)
        self.deleteLater()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        tokens = theme.ACTIVE
        card_rect = QRectF(
            _SHADOW_PAD,
            _SHADOW_PAD,
            self.width() - 2 * _SHADOW_PAD,
            self.height() - 2 * _SHADOW_PAD,
        )
        radius = float(theme.RADIUS_LG)

        # Multi-layer soft shadow painted directly (avoids QGraphicsEffect stacking).
        shadow_alpha = tokens.shadow_alpha / 255.0
        for spread, dy, weight in ((5.0, 3.0, 0.16), (2.5, 1.5, 0.24)):
            shadow = QColor(0, 0, 0)
            shadow.setAlphaF(min(1.0, shadow_alpha * weight))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shadow)
            painter.drawRoundedRect(
                card_rect.adjusted(-spread, -spread + dy, spread, spread + dy),
                radius + spread * 0.5,
                radius + spread * 0.5,
            )

        # Card body + semantic left stripe clipped cleanly to the rounded silhouette.
        card_path = QPainterPath()
        card_path.addRoundedRect(card_rect, radius, radius)
        painter.save()
        painter.setClipPath(card_path)
        painter.fillPath(card_path, QColor(tokens.bg_raised))
        accent_hex, _ = _semantic_hex(self._kind)
        painter.fillRect(
            QRectF(card_rect.left(), card_rect.top(), 3.5, card_rect.height()),
            QColor(accent_hex),
        )
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(tokens.border_strong), 1.0))
        painter.drawRoundedRect(card_rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        painter.end()


class ToastHost(QObject):
    """Positions and stacks up to ``MAX_VISIBLE`` floating ``ToastCard``s on a parent window."""

    def __init__(
        self,
        parent: QWidget,
        *,
        bottom_clearance: Callable[[], int] | None = None,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._bottom_clearance = bottom_clearance
        self._cards: list[ToastCard] = []
        parent.installEventFilter(self)

    @property
    def cards(self) -> tuple[ToastCard, ...]:
        return tuple(c for c in self._cards if not c.is_dismissing)

    def show_toast(
        self,
        message: str,
        *,
        kind: ToastKind = "info",
        duration_ms: int = 4200,
        action_label: str | None = None,
        action: Callable[[], object] | None = None,
    ) -> ToastCard:
        active = [c for c in self._cards if not c.is_dismissing]
        while len(active) >= MAX_VISIBLE:
            oldest = active.pop(0)
            oldest.dismiss(immediate=True)
        card = ToastCard(
            message,
            kind=kind,
            duration_ms=duration_ms,
            action_label=action_label,
            action=action,
            parent=self._parent,
        )
        card.closed.connect(self._on_card_closed)
        self._cards.append(card)
        targets = self._layout_targets()
        for existing, pos in targets:
            if existing is card:
                card.present_at(pos)
            else:
                existing.move_to(pos, animate=True)
        return card

    def clear(self) -> None:
        for card in list(self._cards):
            card.dismiss(immediate=True)
        self._cards.clear()

    def reposition(self, *, animate: bool = False) -> None:
        for card, pos in self._layout_targets():
            card.move_to(pos, animate=animate)

    def _on_card_closed(self, card: object) -> None:
        if isinstance(card, ToastCard) and card in self._cards:
            self._cards.remove(card)
        self.reposition(animate=True)

    def _layout_targets(self) -> list[tuple[ToastCard, QPoint]]:
        active = [c for c in self._cards if not c.is_dismissing]
        if not active:
            return []
        right_margin = 16
        gap = 6
        clearance = self._bottom_clearance() if self._bottom_clearance is not None else 16
        y_bottom = self._parent.height() - clearance
        placements: list[tuple[ToastCard, QPoint]] = []
        # Newest toast sits closest to the bottom edge; older ones stack cleanly above it.
        for card in reversed(active):
            card.adjustSize()
            w = min(card.sizeHint().width(), max(220, self._parent.width() - 32))
            h = card.sizeHint().height()
            if card.width() != w or card.height() != h:
                card.resize(w, h)
            x = max(8, self._parent.width() - right_margin - w + _SHADOW_PAD)
            y = max(8, y_bottom - h + _SHADOW_PAD)
            placements.append((card, QPoint(x, y)))
            y_bottom = y - gap + _SHADOW_PAD
        placements.reverse()
        return placements

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._parent and event.type() == QEvent.Type.Resize:
            self.reposition(animate=False)
        return super().eventFilter(watched, event)
