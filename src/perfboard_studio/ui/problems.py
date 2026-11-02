"""The Problems drawer's bar: what the three checks found, in one line under the canvas.

THE FINDINGS WERE A PANEL ALWAYS OPEN, AND SIX CHIPS. A list 200 px tall sat under the board
whether it had anything to say or not -- four rows on a clean board -- and the status bar
carried ERC, DRC and LVS counts, the connections left to route and the side, each in its own
vocabulary ("DRC 0 err / 2 warn", "LVS 21/24 · 3 open · 0 short"). What a person needs while
working is one answer -- is anything wrong, and how much is left -- and the list only when
the answer is yes. So the panel folds to this bar: a badge with the count (red with an
error in it, amber with only warnings) or "No problems", how many connections are left to
wire, how many nets match the circuit, and which side and board this is. A click opens the
list above it (Ctrl+7 too), and the Check step opens it.

The counts are the window's to make, by the rules the step bar already uses -- a pin not
wired yet is work left, not a problem, while there is wiring left to do -- and are handed in
whole, so this widget decides nothing (``MainWindow._refresh_problems_bar``).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from . import theme
from .i18n import counted, t

#: The bar's height, in logical pixels.
BAR_HEIGHT = 30


class ProblemsBar(QWidget):
    """The drawer's handle: the badge and the counts, and a click to open or close it."""

    toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("problemsBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(BAR_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(t("Everything the three checks found, worst first (Ctrl+7)."))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 12, 0)
        layout.setSpacing(8)
        #: Whether the drawer is open to its list.
        self.expanded: bool = False
        self.errors = 0
        self.warnings = 0
        self.chevron = QToolButton()
        self.chevron.setAutoRaise(True)
        self.chevron.clicked.connect(lambda: self.set_expanded(not self.expanded, emit=True))
        layout.addWidget(self.chevron)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.title)
        self.badge = QLabel()
        self.badge.setObjectName("problemsBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.badge)
        layout.addSpacing(12)
        self.facts = QLabel()
        self.facts.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.facts)
        layout.addStretch(1)
        self.where = QLabel()
        layout.addWidget(self.where)
        self.set_expanded(False)
        self.set_counts(errors=0, warnings=0, to_wire=0, matched=None, nets=0)
        # Styled by name in the one sheet: #problemsBar, and #problemsBadge by its tone.

    def sizeHint(self) -> QSize:
        # The dock sizes its title bar from the hint, not from a fixed height: without this
        # the drawer folded to the 19 px its labels ask for and cut the bar off.
        return QSize(super().sizeHint().width(), BAR_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, BAR_HEIGHT)

    def set_expanded(self, on: bool, *, emit: bool = False) -> None:
        self.expanded = on
        self.chevron.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.UpArrow)
        if emit:
            self.toggled.emit(on)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_expanded(not self.expanded, emit=True)
        super().mouseReleaseEvent(event)

    def set_counts(
        self, *, errors: int, warnings: int, to_wire: int, matched: int | None, nets: int
    ) -> None:
        """What the bar says. ``matched`` is None while there is nothing on the board to
        compare with the circuit."""
        self.errors, self.warnings = errors, warnings
        total = errors + warnings
        if total:
            self.title.setText(f"<b>{t('Problems')}</b>")
            self.badge.setText(str(total))
            theme.tone(self.badge, "danger" if errors else "warning")
            self.badge.setToolTip(
                counted(errors, t("{count} error"), t("{count} errors"))
                + " · "
                + counted(warnings, t("{count} warning"), t("{count} warnings"))
            )
            self.badge.show()
        else:
            self.title.setText(theme.ink("✓", "success") + f" <b>{t('No problems')}</b>")
            self.badge.hide()
        facts = []
        if to_wire:
            facts.append(
                theme.ink("●", "warning") + " " + t("{count} to wire").format(count=to_wire)
            )
        if matched is not None and nets:
            facts.append(t("Matches the circuit: {matched} of {total} nets").format(
                matched=matched, total=nets
            ))
        self.facts.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(facts))

    def set_where(self, text: str) -> None:
        """The side being looked at and the board, at the bar's right end."""
        self.where.setText(text)
