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
from collections.abc import Sequence

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QWidget

from . import theme
from .i18n import counted, t

#: The bar's height, in logical pixels.
BAR_HEIGHT = 30

#: Between two facts on the bar.
FACT_GAP = "&nbsp;&nbsp;·&nbsp;&nbsp;"


def advice(group: str, rule: str) -> str:
    """What to do about a finding, by the check it came from (``"drc"``, ``"lvs"`` or
    ``"erc"``) and its rule id, LVS kind or ERC code -- or ``""`` for one with no line.

    The finding's own sentence says what is wrong, in the engine's words, and stays as it
    is: it is what the MCP server and ``--headless`` print, and goldens compare it byte for
    byte. This is the window's second line under it, written for the person at the board:
    one step that makes the finding go away. Built at call time, like the rule titles, so
    it is said in the language the window was built in; ``tests/test_ui.py`` reads every
    rule, kind and code out of the engine and fails on one this table is silent about.
    """
    lines: dict[str, dict[str, str]] = {
        "drc": {
            "component-body-overlap": t(
                "Move one of the parts until their bodies no longer meet."),
            "component-off-board": t(
                "Move the part back onto the board, or make the board bigger under Properties."),
            "component-overhangs-edge": t(
                "Move or turn the part so its body stays over the board, or make sure the "
                "case has room for it."),
            "component-too-tall": t(
                "Lay the part down, choose a lower package, or use a taller case."),
            "conductor-crossing": t(
                "Redraw one of them, or make it an insulated wire so it can pass over the "
                "other."),
            "conductor-off-board": t(
                "Delete the copper past the edge and draw it again on the board."),
            "copper-at-covered-pin": t(
                "Lay the copper on the other face, where the pin's pad can be soldered."),
            "copper-under-body": t(
                "Lay the copper before fitting the part, or move it out from under the part."),
            "creepage-clearance": t(
                "Move the high-voltage copper at least one hole further from the other net."),
            "crossing-conductors": t(
                "Redraw one of them to go round the hole, or join the two nets if they are "
                "meant to be one."),
            "current-capacity": t(
                "Use a thicker wire, or put a wire under the solder; if the net's current was "
                "set too high, lower it."),
            "cut-track-conflict": t(
                "Move the part, or the cut, so that no pin lands where the strip is cut."),
            "duplicate-pin-hole": t(
                "Move one of the parts: a hole takes one pin."),
            "edge-connector-conflict": t(
                "Move the part off the edge finger, onto holes with pads."),
            "heat-proximity": t(
                "Move the part further from the hot one, or move the hot one to the edge."),
            "joint-under-body": t(
                "Move the part back to the component side, where its joints can be reached."),
            "jumper-under-body": t(
                "Fit the jumper before the part, or take it round the part."),
            "lead-bend-too-long": t(
                "Bend the leg across fewer holes, and use a wire for the rest of the way."),
            "mounting-hole-clearance": t(
                "Move the part out from under the screw head."),
            "mounting-hole-conflict": t(
                "Move the part so that no pin lands on the mounting hole."),
            "no-copper-on-face": t(
                "Lay it on the solder side, where the pads are."),
            "no-hole": t(
                "Move the part onto the breadboard's holes."),
            "not-on-breadboard": t(
                "Use a jumper wire on top instead: nothing is soldered on a breadboard."),
            "pad-lifting-risk": t(
                "Put a wire under the solder, or use a wire for the long stretch."),
            "pin-not-connected": t(
                "Wire the pin to its net, by hand or with Auto-wire."),
            "rail-without-bridge": t(
                "Bridge a finger to a hole of the board, or delete the solder on the fingers."),
            "solder-gap-needs-spine": t(
                "Put a wire under the solder across the gap, or use a wire."),
            "solder-trace-invalid-path": t(
                "Redraw the trace one hole at a time, with no diagonal step."),
            "solder-trace-proximity": t(
                "Leave an empty hole between the solder and the other net, or solder it with "
                "care and look for a bridge afterwards."),
            "solder-trace-too-long": t(
                "Use a wire for part of the run, or put a wire under the solder."),
            "superseded-footprint": t(
                "Choose the part again under Properties ▸ Change…; its pins stay where they are."),
            "terminal-entry-blocked": t(
                "Turn the terminal, or move what stands in front of its wire entries."),
            "terminal-entry-faces-in": t(
                "Turn the terminal so that its wire entries face the edge of the board."),
            "under-module": t(
                "Fit this part before the module, or move it out from under it."),
            "unknown-footprint": t(
                "Choose a package for the part under Properties ▸ Change…."),
            "wire-over-joint": t(
                "Use an insulated wire there, or take the bare wire round the joint."),
            "wire-too-thick-for-hole": t(
                "Use a thinner wire, or share the current between two wires."),
            "wrong-rail": t(
                "Move the pin to the rail its net belongs on."),
        },
        "lvs": {
            "open": t(
                "Join the pieces: draw the copper that is missing, or Redo Wiring on the net."),
            "short": t(
                "Find the copper that joins the two nets, and delete or move it."),
            "floating-conductor": t(
                "Delete the copper, or carry it on to the pin it was meant for."),
            "unplaced-component": t(
                "Place the part on the board from the Parts list."),
            "unknown-footprint": t(
                "Choose a package for the part under Properties ▸ Change…."),
            "unrouted-net": t(
                "Wire it, by hand or with Auto-wire."),
        },
        "erc": {
            "supply-unconnected": t(
                "Connect the power pin to its supply net on the sheet."),
            "supply-on-wrong-net": t(
                "Move the power pin to the right supply net."),
            "polarity-reversed": t(
                "Turn the part round on the sheet, or swap its two nets."),
            "pin-not-on-part": t(
                "Take the pin off the net, or choose the package that has it."),
            "no-power-entry": t(
                "Add the connector, battery or supply that brings power in."),
            "supply-pin-open": t(
                "Connect the other power pin as well."),
            "nc-pin-connected": t(
                "Take the “no connect” pin off its net."),
            "single-pin-net": t(
                "Connect the net to a second pin, or delete it."),
            "part-unconnected": t(
                "Wire the part into the circuit, or delete it."),
            "part-not-defined": t(
                "Add the part, or take its pins off the net."),
            "value-missing": t(
                "Give the part a value under Properties."),
            "pin-roles-incomplete": t(
                "These pin roles don't match this package. Give every pin of this package "
                "a role, and only those pins, or put the part back on the package they were "
                "written for. Until then it is drawn as a plain numbered box; nothing else "
                "about the part changes."),
        },
    }
    return lines.get(group, {}).get(rule, "")


#: Findings said in one tooltip on the board before the rest are counted: a hole in a
#: long run next to another net can be named by a finding of each trace, per pad.
TIP_FINDINGS = 3


def findings_tip(findings: Sequence[tuple[str, str]]) -> str:
    """Findings as a tooltip says them: each whole sentence -- the drawer's row cuts it off
    at the column's edge -- and then what to do about them, each step once. ``findings``
    is (sentence, what to do) pairs; either may be empty. Rich text, so Qt wraps it rather
    than drawing one line as wide as the screen."""
    sentences = list(dict.fromkeys(sentence for sentence, _ in findings if sentence))
    steps = list(dict.fromkeys(step for _, step in findings if step))
    said = "".join(f"<p>{html.escape(sentence)}</p>" for sentence in sentences[:TIP_FINDINGS])
    if len(sentences) > TIP_FINDINGS:
        more = len(sentences) - TIP_FINDINGS
        said += f"<p>{html.escape(t('…and {count} more').format(count=more))}</p>"
    if steps:
        said += (
            f"<p><b>{html.escape(t('What to do:'))}</b> "
            f"{html.escape(' '.join(steps))}</p>"
        )
    return said


def finding_tip(sentence: str, what_to_do: str = "") -> str:
    """One finding as a tooltip says it (``findings_tip``)."""
    return findings_tip([(sentence, what_to_do)])


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
        # Its room either side of the count, in the widget rather than the stylesheet: a
        # QLabel's size hint leaves the stylesheet's padding out, so the badge was as wide
        # as its digits under an 8 px radius -- a coloured sliver the count was cut off in
        # (the pre-RC walk, at every window size and in both languages).
        side = theme.SPACE["sm"]
        self.badge.setContentsMargins(side, 0, side, 0)
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
