"""The six steps a board is built in, where this document stands on each, and the next one.

THE WINDOW HAD EVERY TOOL AND NO ORDER. Thirty-three buttons across two toolbars, a board and
a sheet stacked on each other, and nothing anywhere saying what comes after what: that the
circuit is drawn first, that a board is chosen before the parts go on it, that routing is
what joins them, that DRC is what says the result can be built, and that the guide and the
3D view are what it is built from. Every one of those steps existed. None of them was
findable from the one before it -- the answer to "what do I do now?" lived in a paragraph of
text over an empty board, and it stopped being shown the moment the board had a part on it.

So this is the order, measured off the document every time it changes, and one button that
does whichever step is next. It decides nothing about the document -- every step's action is
an existing command reached from where it already was -- which is why it can be pure: the
facts go in, the steps come out, and a test can hand it facts.

Six steps and not five, because choosing the board is a decision of its own. A perfboard is
bought before it is populated, and the moment between drawing the circuit and placing it is
the last one at which the size is still free (``boardfit.choose_board``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from .i18n import t
from .theme import ACCENT, BORDER, ERROR, OK, PANEL, PANEL_ALT, TEXT, TEXT_DIM, WARNING

type StepKey = Literal["circuit", "board", "place", "route", "check", "build"]

#: ``done``: nothing left to do here. ``current``: the step to do next. ``problem``: done
#: enough to go on from, and something in it is wrong (DRC errors, an open net). ``todo``:
#: after the current one.
type StepStatus = Literal["done", "current", "todo", "problem"]

#: In the order a board is built.
STEP_ORDER: tuple[StepKey, ...] = ("circuit", "board", "place", "route", "check", "build")


@dataclass(frozen=True, slots=True)
class WorkflowFacts:
    """What the steps are measured against. Everything is a count the window already has."""

    #: Parts in the design and not yet on the board (``doc.parts``).
    parts_off_board: int
    #: Parts on the board (``doc.components``).
    parts_on_board: int
    #: Nets that join at least two pins -- a net of one pin connects nothing.
    nets: int
    #: What the board is, for the step to say ("5 x 7 cm", "18 × 24").
    board_label: str
    #: Whether somebody has chosen this board, rather than it being the one a new document
    #: opens on. A board with parts on it has been chosen by definition.
    board_chosen: bool
    #: Connections the ratsnest still draws between placed pins.
    unrouted: int
    drc_errors: int
    drc_warnings: int
    #: LVS opens and shorts: the board is not the circuit.
    lvs_problems: int
    #: ERC errors: the circuit itself cannot work as drawn (``erc.py``). Warnings are
    #: counted for the step's line and never hold it back.
    erc_errors: int = 0
    erc_warnings: int = 0
    #: Of ``lvs_problems``, the shorts. A short is wrong however much is left to route; an
    #: open is only the wiring not being finished until the wiring is.
    lvs_shorts: int = 0
    #: Of ``drc_warnings``, pins that touch nothing yet (``pin-not-connected``) -- every pin of
    #: every net on a board just placed. The wiring's news until the wiring is done, as an
    #: open is: counted, they put seventeen warnings under Verify on a six-part board that
    #: nobody had done anything wrong to yet.
    drc_unwired: int = 0
    #: A stripboard: its strips join every net along them until the wiring cuts them, so a
    #: short there is also the wiring's news until the wiring is done.
    shorts_wait_for_wiring: bool = False
    #: Whether the build guide is in front of the user -- once it is, opening it again is
    #: not a next step (``build_action``).
    guide_showing: bool = False
    #: Whether the board has no file yet.
    untitled: bool = False
    #: A solderless breadboard, which is tried out before it is soldered on something else.
    solderless_breadboard: bool = False


#: What the Next button does once everything before Build is done.
type BuildAction = Literal["open-guide", "save", "to-perfboard", "export-guide"]


def build_action(facts: WorkflowFacts) -> BuildAction:
    """What comes after the build guide, which is the last step and never "done".

    THE BUTTON USED TO END IN A LOOP. "Open the Build Guide" was the next step for ever, and
    pressing it with the guide open raised the guide it was looking at -- while the board
    the whole walk produced sat untitled, and a breadboard that had just been checked had
    its way on to perfboard in the File menu only. So once the guide is in front: a board
    with no file is saved first, a checked breadboard goes on to a board to solder (File >
    New Board from This Design), and anything else exports the guide to take to the bench.
    """
    if not facts.guide_showing:
        return "open-guide"
    if facts.untitled:
        return "save"
    if facts.solderless_breadboard:
        return "to-perfboard"
    return "export-guide"


@dataclass(frozen=True, slots=True)
class StepState:
    key: StepKey
    status: StepStatus
    #: One short line under the step's name: what this document has for it.
    summary: str
    #: What the Next button says when this is the step it does: a verb, not the step.
    action: str


def step_title(key: StepKey) -> str:
    """The step's name, in the window's language."""
    return {
        "circuit": t("Circuit"),
        "board": t("Board"),
        "place": t("Placement"),
        "route": t("Wiring"),
        "check": t("Verify"),
        "build": t("Build"),
    }[key]


def step_action(key: StepKey, facts: WorkflowFacts | None = None) -> str:
    """What the Next button says when this step is the next one: a verb, not the step.

    The circuit's depends on what it has: with no parts the next thing is a part, and with
    parts and nothing joining them it is joining them -- "Add a Part" over eight parts and
    no nets sent people back to the one thing they had already done. And with an error in
    it, the next thing is reading what is wrong.
    """
    if key == "circuit" and facts is not None and facts.erc_errors:
        return t("See the Findings")
    if key == "circuit" and facts is not None and facts.parts_off_board + facts.parts_on_board:
        return t("Connect the Pins")
    return {
        "circuit": t("Add a Part…"),
        "board": t("Choose a Board…"),
        "place": t("Place on the Board"),
        "route": t("Autoroute"),
        "check": t("See the Findings"),
        "build": _build_label(build_action(facts) if facts is not None else "open-guide"),
    }[key]


def _build_label(action: BuildAction) -> str:
    return {
        "open-guide": t("Open the Build Guide"),
        "save": t("Save the Board…"),
        "to-perfboard": t("Take It to Perfboard…"),
        "export-guide": t("Export the Guide…"),
    }[action]


def step_tooltip(key: StepKey) -> str:
    return {
        "circuit": t(
            "What the board is: its parts and what joins them. Drawn on the sheet, or by "
            "placing parts on the board and connecting their pins. ERC checks it as it is "
            "drawn: a chip with no supply is an error before any board is chosen."
        ),
        "board": t(
            "Which perfboard it goes on. Chosen before the parts go down, while the size is "
            "still free: every stock size is tried with your circuit laid out on it."
        ),
        "place": t("Where each part goes. Arranged for you, then yours to move."),
        "route": t(
            "What joins the pins on the board: solder traces, wires and jumpers. Autoroute "
            "lays them; the Draw menu lays them by hand."
        ),
        "check": t(
            "Whether it can be built as drawn: design rules (DRC) and whether the board is "
            "the circuit (LVS)."
        ),
        "build": t("The soldering guide, step by step, with the board in 3D beside it."),
    }[key]


def _counted(count: int, one: str, many: str) -> str:
    """``one`` or ``many`` -- each already through ``t()`` -- with the count in it."""
    return (one if count == 1 else many).format(count=count)


def workflow_steps(facts: WorkflowFacts) -> tuple[StepState, ...]:
    """Every step's status and one line about it. The first step not done is ``current``."""
    parts = facts.parts_off_board + facts.parts_on_board
    # A circuit with an error in it is not drawn yet, whatever else is: an unpowered chip is
    # still unpowered on the finest board, and nothing downstream will say so.
    circuit_bad = parts > 0 and facts.erc_errors > 0
    circuit_done = parts > 0 and facts.nets > 0 and not circuit_bad
    board_done = facts.board_chosen or facts.parts_on_board > 0
    place_done = facts.parts_on_board > 0 and facts.parts_off_board == 0
    route_done = place_done and facts.unrouted == 0 and facts.nets > 0
    # Between placing the parts and routing them every net is open, and that is the Wiring
    # step's news: counted as a fault it turned Check red the moment a placement landed and
    # sent Next to the findings instead of to Autoroute. An open once nothing is left to
    # route is a board whose copper does not join what the ratsnest says it does.
    if route_done:
        lvs_errors = facts.lvs_problems
    else:
        lvs_errors = 0 if facts.shorts_wait_for_wiring else facts.lvs_shorts
    check_bad = facts.parts_on_board > 0 and (facts.drc_errors > 0 or lvs_errors > 0)
    check_done = route_done and not check_bad

    # Counted in words -- "1 part", "10 parts" -- where it said "10 part(s)": the bar is
    # on screen the whole time, and nobody writes "(s)". Two keys rather than one with a
    # bracket, so a language that does not inflect after a number says one word for both.
    part_count = _counted(parts, t("{count} part"), t("{count} parts"))
    if parts == 0:
        circuit = t("no parts yet")
    elif circuit_bad:
        errors = _counted(facts.erc_errors, t("{count} error"), t("{count} errors"))
        circuit = f"{part_count} · {errors}"
    else:
        circuit = f"{part_count} · {_counted(facts.nets, t('{count} net'), t('{count} nets'))}"
    if parts == 0:
        placed = t("nothing to place")
    else:
        placed = t("{placed}/{total} on the board").format(
            placed=facts.parts_on_board, total=parts
        )
    if facts.parts_on_board == 0 or facts.nets == 0:
        wired = t("nothing to wire yet")
    elif facts.unrouted:
        wired = _counted(
            facts.unrouted, t("{count} connection left"), t("{count} connections left")
        )
    else:
        wired = t("all joined")
    if facts.parts_on_board == 0:
        checked = t("nothing to check yet")
    else:
        warnings = facts.drc_warnings - (0 if route_done else facts.drc_unwired)
        errors = _counted(
            facts.drc_errors + lvs_errors, t("{count} error"), t("{count} errors")
        )
        checked = f"{errors} · {_counted(warnings, t('{count} warning'), t('{count} warnings'))}"

    done = {
        "circuit": circuit_done,
        "board": board_done,
        "place": place_done,
        "route": route_done,
        "check": check_done,
        "build": False,
    }
    summaries: dict[StepKey, str] = {
        "circuit": circuit,
        "board": facts.board_label,
        "place": placed,
        "route": wired,
        "check": checked,
        "build": t("guide · 3D"),
    }
    current = next((key for key in STEP_ORDER if not done[key]), "build")
    steps: list[StepState] = []
    for key in STEP_ORDER:
        status: StepStatus
        if (key == "check" and check_bad) or (key == "circuit" and circuit_bad):
            status = "problem"
        elif done[key]:
            status = "done"
        elif key == current:
            status = "current"
        else:
            status = "todo"
        steps.append(
            StepState(
                key=key, status=status, summary=summaries[key], action=step_action(key, facts)
            )
        )
    return tuple(steps)


def next_step(steps: tuple[StepState, ...]) -> StepKey:
    """The step the Next button does: a problem first, then the current one."""
    problem = next((step.key for step in steps if step.status == "problem"), None)
    if problem is not None:
        return problem
    return next((step.key for step in steps if step.status == "current"), "build")


# ---------------------------------------------------------------------------
# The widget
# ---------------------------------------------------------------------------

_STATUS_COLOUR: dict[StepStatus, str] = {
    "done": OK,
    "current": ACCENT,
    "problem": ERROR,
    "todo": TEXT_DIM,
}

_STATUS_MARK: dict[StepStatus, str] = {
    "done": "✓",
    "current": "●",
    "problem": "!",
    "todo": "○",
}


class WorkflowBar(QWidget):
    """The steps across the top of the window, and the button that does the next one.

    A step is a button because it is a place to go: pressing Circuit brings the sheet
    forward, Placement and Wiring the board, Check the findings, Build the guide and the 3D
    view -- which is what the two view-switching buttons and four shortcuts did, arranged in
    the order they are needed. What it SHOWS is where the document stands on it.
    """

    stepClicked = Signal(str)
    nextClicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowBar")
        # The width of the window: it sits alone in a toolbar row, and a toolbar gives an
        # expanding widget the room the row has.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Its own background painted, which a plain QWidget does not do for a stylesheet.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        # The bar decides how much it says from the width it is GIVEN (``_fit``), so the
        # layout must not turn the width of its fullest wording into a minimum for the
        # whole window: with it, a 1100 px window could not be made, and the main toolbar
        # above kept words it had no room for.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        #: How much each step says: its summary line too, only its name, or only its number.
        self._mode: Literal["full", "compact", "tiny"] = "full"
        self._fitting = False
        self.buttons: dict[StepKey, QToolButton] = {}
        for index, key in enumerate(STEP_ORDER):
            if index:
                arrow = QLabel("›")
                arrow.setStyleSheet(f"color: {TEXT_DIM}; font-size: 16px;")
                layout.addWidget(arrow)
            button = QToolButton()
            button.setObjectName(f"workflowStep_{key}")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setAutoRaise(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self.stepClicked.emit(k))
            layout.addWidget(button)
            self.buttons[key] = button
        layout.addStretch(1)
        self.next_button = QPushButton()
        self.next_button.setObjectName("workflowNext")
        self.next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_button.setDefault(False)
        self.next_button.setAutoDefault(False)
        self.next_button.clicked.connect(lambda: self.nextClicked.emit(self._next))
        layout.addWidget(self.next_button)
        self._next: StepKey = "circuit"
        self.steps: tuple[StepState, ...] = ()
        self.setStyleSheet(
            f"""
            QWidget#workflowBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
            QToolButton {{
                color: {TEXT}; padding: 3px 10px; border-radius: 6px; text-align: left;
            }}
            QToolButton:hover {{ background: {PANEL_ALT}; }}
            QPushButton#workflowNext {{
                background: {ACCENT}; color: white; font-weight: 600;
                border: none; border-radius: 6px; padding: 6px 16px;
            }}
            QPushButton#workflowNext:hover {{ background: #62aaff; }}
            """
        )

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def _label(self, number: int, step: StepState, mode: str) -> str:
        mark = _STATUS_MARK[step.status]
        if mode == "tiny":
            return f"{mark} {number}"
        if mode == "compact":
            return f"{mark} {number}. {step_title(step.key)}"
        return f"{mark} {number}. {step_title(step.key)}\n{step.summary}"

    def _write_labels(self, mode: str) -> None:
        for number, step in enumerate(self.steps, start=1):
            self.buttons[step.key].setText(self._label(number, step, mode))

    def _fit(self) -> None:
        """Say as much as the width allows: summaries, then names only, then numbers.

        Measured by writing each wording and asking the layout, fullest first, because the
        widths are the font's and the language's -- "Yönlendirme" is not "Wiring". What a
        step stops saying is still in its tooltip.
        """
        if self._fitting or not self.steps:
            return
        layout = self.layout()
        if layout is None:
            return
        self._fitting = True
        try:
            chosen: Literal["full", "compact", "tiny"] = "tiny"
            for mode in ("full", "compact", "tiny"):
                self._write_labels(mode)
                if layout.sizeHint().width() <= self.width():
                    chosen = mode
                    break
            self._write_labels(chosen)
            self._mode = chosen
        finally:
            self._fitting = False

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()

    def set_steps(self, steps: tuple[StepState, ...]) -> None:
        self.steps = steps
        for number, step in enumerate(steps, start=1):
            button = self.buttons[step.key]
            colour = _STATUS_COLOUR[step.status]
            weight = "600" if step.status in ("current", "problem") else "normal"
            button.setText(self._label(number, step, self._mode))
            button.setToolTip(
                f"<b>{step_title(step.key)}</b> — {step.summary}<br>{step_tooltip(step.key)}"
            )
            button.setStyleSheet(
                f"QToolButton {{ color: {colour}; font-weight: {weight}; }}"
                if step.status != "todo"
                else f"QToolButton {{ color: {TEXT_DIM}; }}"
            )
            button.setProperty("status", step.status)
        self._next = next_step(steps)
        label = next(step.action for step in steps if step.key == self._next)
        problem = any(step.status == "problem" for step in steps)
        self.next_button.setText(("⚠ " if problem else "") + label + "  →")
        self.next_button.setStyleSheet(
            f"QPushButton#workflowNext {{ background: {WARNING if problem else ACCENT}; }}"
        )
        self._fit()

    @property
    def next_key(self) -> StepKey:
        return self._next
