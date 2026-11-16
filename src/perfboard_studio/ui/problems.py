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

import html
import re

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QWidget

from . import theme
from .i18n import counted, t

#: The bar's height, in logical pixels.
BAR_HEIGHT = 30

#: Between two facts on the bar.
FACT_GAP = "&nbsp;&nbsp;·&nbsp;&nbsp;"


def _plain(rich: str) -> str:
    """What a fact reads as, tags and entities gone: for measuring it, and for the tooltip."""
    return html.unescape(re.sub(r"<[^>]+>", "", rich))


class ProblemsBar(QWidget):
    """The drawer's handle: the badge and the counts, and a click to open or close it."""

    toggled = Signal(bool)
    #: Auto-wire, pressed beside the count of connections left to wire.
    wire_requested = Signal()

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
        # Given what is left of the bar rather than asking for its whole line: at 1366 px the
        # label ran under the board's edge and cut "Matches the circuit: 7 o" mid-word
        # (the newcomer walk). ``_fit_facts`` says what fits; the tooltip says the rest.
        self.facts.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        #: Each fact as (full, short), in the order they are dropped last to first.
        self._facts: list[tuple[str, str]] = []
        # Fitted whenever the label is given a new width: the bar's own resize comes
        # before the layout has passed the width on.
        self.facts.installEventFilter(self)
        layout.addWidget(self.facts, 1)
        # What to do about the count beside it: "3 to wire" was a fact with no way to act
        # on it, in a drawer Next kept opening (reach's walkthrough).
        self.wire = QToolButton()
        self.wire.setText(t("Auto-wire"))
        self.wire.setAutoRaise(True)
        self.wire.setToolTip(t("Wire the connections that are left, as Next does on Wiring."))
        self.wire.clicked.connect(self.wire_requested.emit)
        self.wire.hide()
        layout.addWidget(self.wire)
        self.where = QLabel()
        # As wide as it says, so the room left goes to the facts.
        self.where.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
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
        self,
        *,
        errors: int,
        warnings: int,
        to_wire: int,
        matched: int | None,
        nets: int,
        to_check: int = 0,
        to_review: int = 0,
        off_face: int = 0,
    ) -> None:
        """What the bar says. ``matched`` is None while there is nothing on the board to
        compare with the circuit. ``to_check`` is the findings the build guide makes a check
        at the bench of (``guide.is_bench_check``): counted beside what is left to wire,
        never in the badge, which is what is wrong. ``to_review`` is the wires worth a look
        (``wiringreview``): not wrong either, so not in the badge -- but not "No problems"
        over them, which is what Auto-wire finished on over wires lying across pins 44 times.
        With nothing wrong and nothing left to wire, wires worth a look are said under
        "Ready to build", in the plain colour and marked optional: an orange "Wiring to
        review" over six green ticks left a newcomer unsure whether the board was fine.
        ``off_face`` is the nets wired off the face they prefer (the drawer's Faces group):
        information, in the neutral colour, counted as nothing. Said only in the drawer, it
        was the fifth clause of a long status line and a group in a closed drawer, and a
        builder who set GND to the component side saw it come back underneath unexplained."""
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
        elif to_review and not to_wire:
            self.title.setText(theme.ink("✓", "success") + f" <b>{t('Ready to build')}</b>")
            self.badge.hide()
        else:
            self.title.setText(theme.ink("✓", "success") + f" <b>{t('No problems')}</b>")
            self.badge.hide()
        facts: list[tuple[str, str]] = []
        if to_wire:
            said = theme.ink("●", "warning") + " " + t("{count} to wire").format(count=to_wire)
            facts.append((said, said))
        if to_review:
            dot = theme.ink("●", "secondary") + " "
            facts.append((
                dot + counted(
                    to_review,
                    t("optional: {count} wire to look at"),
                    t("optional: {count} wires to look at"),
                ),
                dot + t("{count} to look at").format(count=to_review),
            ))
        if to_check:
            dot = theme.ink("●", "secondary") + " "
            facts.append((
                dot + t("{count} to check at the bench").format(count=to_check),
                dot + t("{count} at the bench").format(count=to_check),
            ))
        if off_face:
            said = theme.ink("●", "secondary") + " " + counted(
                off_face, t("{count} net off its face"), t("{count} nets off their face")
            )
            facts.append((said, said))
        if matched is not None and nets:
            facts.append((
                t("Matches the circuit: {matched} of {total} nets").format(
                    matched=matched, total=nets
                ),
                t("{matched}/{total} nets match").format(matched=matched, total=nets),
            ))
        self._facts = facts
        self.wire.setVisible(to_wire > 0)
        self._fit_facts()

    def facts_said(self) -> str:
        """Every fact in full, as the bar says them with room for all: what the label
        shows when it fits, whatever it was cut to."""
        return FACT_GAP.join(said for said, _ in self._facts)

    def _text_width(self, rich: str) -> int:
        return self.facts.fontMetrics().horizontalAdvance(_plain(rich))

    def _fit_facts(self) -> None:
        """The facts, as many as the label's width holds: each in full, then each short,
        then the last ones dropped. Whatever is shortened or dropped is in the tooltip."""
        room = self.facts.width()
        full = [said for said, _ in self._facts]
        short = [brief for _, brief in self._facts]
        chosen = short
        for candidate in (full, short):
            if self._text_width(FACT_GAP.join(candidate)) <= room:
                chosen = candidate
                break
        else:
            while len(chosen) > 1 and self._text_width(FACT_GAP.join(chosen)) > room:
                chosen = chosen[:-1]
        self.facts.setText(FACT_GAP.join(chosen))
        cut = chosen != full
        self.facts.setToolTip("\n".join(_plain(said) for said in full) if cut else "")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.facts and event.type() == QEvent.Type.Resize:
            self._fit_facts()
        return super().eventFilter(watched, event)

    def set_where(self, text: str) -> None:
        """The side being looked at and the board, at the bar's right end."""
        self.where.setText(text)
        self._fit_facts()
