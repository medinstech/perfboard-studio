"""The build guide at the bench: one step at a time, large enough to read from across it.

ONE STEP FILLS THE PANEL. The guide was a dense tree -- every phase, step and check of the
build in one list a few hundred pixels wide -- which is the right shape for seeing the whole
build and the wrong one for doing it: at the bench, with an iron in one hand, what is wanted
is the step in front of you, where it goes, which way round, what to measure, and a button
big enough to hit that says "done". The tree is still there, one click away (Overview).

The card is the board as it stands at that step (``guide.document_at_step``), zoomed onto
the step's holes with the part selected -- seen from the solder side for a step done on the
solder side -- then the step in the guide's own words, its polarity, its holes, and the
phase's checks as Ω items to tick. Back and "Done, next" walk the build. A stripboard's
track cuts are steps here too, first, each with its own picture: they are the first thing
done and the one most often forgotten.

THE BUILD HAS AN END. The last step's button says "Done ✓", and pressing it shows what is
left rather than nothing at all -- it used to tick the step and stay where it was, still
saying "Done, next", which a builder pressed again and again waiting for the next step. The
ending says whether every step is ticked (and goes to the first one that is not), lists the
checks not ticked yet to tick there, and offers the export and Save. It ticks nothing on
the builder's behalf: a check is a measurement, and only the person holding the meter knows
whether it read what it should.

The ending lists the checks of EVERY phase, not only of those with a step. A step shows its
own phase's checks, and the last phase, "Closing up", has no step and every short test --
VCC against GND among them -- so a builder walking the bench never saw the one measurement
to make before power goes on.

THE HARNESS IS THE LAST PHASE. A system's cables (``harness.py``) are fitted once every
board is built -- to connectors already soldered -- and checked end to end before anything
is powered, so each cable is one more step after Closing up, under a phase of its own:
"9. Harness". Nine, because the guide's phases stop at eight and a check's tick is kept
under its phase's number (``check_key``): a harness check numbered 8 would have shared
Closing up's store. A cable's step is pictured on the finished board, at this board's end
of it, and its wires are listed by colour, end to end.

PRESENTATION ONLY. Every word of a step, its order and its checks are the guide's (the
engine's, in the guide's language); the window adds the frame. The ticks are the window's
one store of them (``MainWindow._done_steps``), so ticking here and in the overview cannot
disagree.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio.geometry import format_hole
from perfboard_studio.guide import (
    Checkpoint,
    ConductorStep,
    Guide,
    GuidePhase,
    GuideStep,
    PartStep,
    step_focus,
)
from perfboard_studio.guide_export import harness_end
from perfboard_studio.harness import HarnessCable, HarnessWire
from perfboard_studio.model import Board, HoleCoord
from perfboard_studio.phrasebook import Phrasebook, phrasebook

from . import theme
from .i18n import t

#: Read from across a bench: the step's title and its polarity. The two buttons' size
#: is the theme's (``theme.BENCH_PX``), because a size set on a button is lost to its rule.
TITLE_PX = 26
POLARITY_PX = 17


#: The harness's phase number on the bench: after the guide's last, Closing up (8).
HARNESS_PHASE = 9


@dataclass(frozen=True, slots=True)
class HarnessPhase:
    """The system's cables, as one more phase on the bench (see the module's note): what a
    phase is to the bench -- a number, a title, its checks -- and no more."""

    number: int
    title: str
    checkpoints: tuple[Checkpoint, ...]


type BenchPhase = GuidePhase | HarnessPhase


@dataclass(frozen=True, slots=True)
class BenchItem:
    """One thing done at the bench: a step of the guide, a stripboard's track cut, or a
    cable of the harness."""

    #: What the tick is kept under: the step's ``step_focus``, ``cut:col,row`` or
    #: ``cable:<id>``.
    key: str
    phase: BenchPhase
    title: str
    #: The step's index in the guide's flat list -- what the 3D slider and
    #: ``document_at_step`` count in -- or None for a cut, which comes before any part.
    step_index: int | None
    holes: tuple[HoleCoord, ...]
    #: Done from the solder side: a trace, a wire below, a cut. The picture is from there.
    solder_side: bool
    polarity: str | None
    #: What to read off the card besides the title: (what, value).
    facts: tuple[tuple[str, str], ...]
    notes: tuple[str, ...]
    #: The component to select in the picture, if the step is a part.
    component_id: str | None = None
    #: Done on the finished board -- a cable, fitted once every part is soldered: pictured
    #: as the board stands at the end, not at a step of its build.
    built: bool = False


def check_key(phase: BenchPhase, check: Checkpoint) -> str:
    """What a check's tick is kept under, beside the steps' in the same store."""
    return f"check:{phase.number}:{check.title}"


def bench_items(
    guide: Guide, steps: list[GuideStep], ends_here: Mapping[str, str] | None = None
) -> list[BenchItem]:
    """Everything done at the bench, in the guide's order: a stripboard's track cuts first,
    then every step of every phase, then each cable of the harness.

    ``ends_here`` is each cable's connector on this board, by cable id: where a cable's
    step is pictured. A cable with no end on this board is pictured as the whole board."""
    say = phrasebook(guide.language)
    board = guide.board
    items: list[BenchItem] = []
    index = {id(step): number for number, step in enumerate(steps)}
    for number, phase in enumerate(guide.phases):
        if number == 0:
            for cut in guide.track_cuts:
                items.append(
                    BenchItem(
                        key=f"cut:{cut.at.col},{cut.at.row}",
                        phase=phase,
                        title=f"{format_hole(cut.at, board)} · {cut.strip}",
                        step_index=None,
                        holes=(cut.at, *(cut.separates or ())),
                        solder_side=True,
                        polarity=None,
                        facts=(),
                        notes=(say("Cut these tracks first"),),
                    )
                )
        for step in phase.steps:
            items.append(_step_item(step, phase, index.get(id(step)), board))
    if guide.harness:
        harness = HarnessPhase(
            HARNESS_PHASE,
            say("Harness"),
            tuple(check for cable in guide.harness for check in cable.checkpoints),
        )
        parts = {
            step.component_id: step
            for phase in guide.phases
            for step in phase.steps
            if isinstance(step, PartStep)
        }
        for cable in guide.harness:
            connector = (ends_here or {}).get(cable.cable_id)
            items.append(_cable_item(cable, harness, parts.get(connector or ""), say))
    return items


def bench_phases(guide: Guide, items: Sequence[BenchItem]) -> list[BenchPhase]:
    """The guide's phases, then the harness's when ``items`` have one -- the very object
    the items carry, since the bench tells a phase by identity."""
    harness = next((item.phase for item in items if isinstance(item.phase, HarnessPhase)), None)
    return [*guide.phases, *([harness] if harness is not None else [])]


def _cut_said(wire: HarnessWire, say: Phrasebook) -> str:
    length = say("cut to fit") if wire.cut_mm is None else f"{wire.cut_mm:.0f} mm"
    return f"{length} · AWG {wire.awg}"


def _cable_item(
    cable: HarnessCable, phase: HarnessPhase, here: PartStep | None, say: Phrasebook
) -> BenchItem:
    """One cable: which connector goes to which, each wire by its colour from end to end,
    what to cut, and its steps -- the guide's own words, as the export gives them."""
    title = cable.ref
    if cable.wires:
        a, b = cable.wires[0].a, cable.wires[0].b
        title = f"{cable.ref} — {a.board} {a.ref} → {b.board} {b.ref}"
    facts = [
        (say(wire.colour), f"{harness_end(wire.a, say)} → {harness_end(wire.b, say)}")
        for wire in cable.wires
    ]
    cuts = list(dict.fromkeys(_cut_said(wire, say) for wire in cable.wires))
    if cuts:
        facts.append((t("Wire to cut"), ", ".join(cuts)))
    return BenchItem(
        key=f"cable:{cable.cable_id}",
        phase=phase,
        title=title,
        step_index=None,
        holes=tuple(hole for _pin, hole in here.pin_holes) if here is not None else (),
        solder_side=False,
        polarity=None,
        facts=tuple(facts),
        notes=(*cable.steps, *((cable.note,) if cable.note else ())),
        component_id=here.component_id if here is not None else None,
        built=True,
    )


def _step_item(step: GuideStep, phase: GuidePhase, index: int | None, board: Board) -> BenchItem:
    if isinstance(step, PartStep):
        holes = tuple(hole for _pin, hole in step.pin_holes)
        facts: tuple[tuple[str, str], ...] = (
            (t("Holes"), "  ".join(f"{pin}: {format_hole(hole, board)}" for pin, hole in step.pin_holes)),
            (t("Height"), f"{step.height_mm:.1f} mm"),
        )
        if step.cabled:
            # Its notes give each lead by name and hole ("VCC in C4"); pin numbers beside
            # them said the same holes a second time in a language the module does not use.
            facts = facts[1:]
        return BenchItem(
            key=step_focus(step), phase=phase, title=step.title, step_index=index,
            holes=holes, solder_side=False, polarity=step.polarity, facts=facts,
            notes=step.notes, component_id=step.component_id,
        )
    assert isinstance(step, ConductorStep)
    facts = ((t("Holes"), step.span),)
    if step.cut is not None:
        facts = (*facts, (t("Wire to cut"), f"{step.cut.cut_mm:.0f} mm · AWG {step.cut.awg}"))
    return BenchItem(
        key=step_focus(step), phase=phase, title=step.title, step_index=index,
        holes=step.path, solder_side=step.side == "bottom", polarity=None, facts=facts,
        notes=step.notes,
    )


# -- the phases, along the top ----------------------------------------------------------------


class PhaseBar(QWidget):
    """The build's phases as segments, as wide as each phase is long: the current one named
    in full, the others a coloured bar with their name on hover. Names in every segment
    wrapped to three lines in a narrow panel ("Uzun ve mekanik parçalar")."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self._phases: list[tuple[str, int]] = []
        self._current = -1

    def set_phases(self, phases: list[tuple[str, int]], current: int) -> None:
        self._phases, self._current = phases, current
        self.update()

    def _segments(self) -> list[QRectF]:
        if not self._phases:
            return []
        gap = 4.0
        name = self.fontMetrics().horizontalAdvance(self._phases[self._current][0]) + 24 if (
            0 <= self._current < len(self._phases)) else 0
        rest = sum(max(1, n) for i, (_t, n) in enumerate(self._phases) if i != self._current)
        free = max(0.0, self.width() - name - gap * (len(self._phases) - 1))
        x, out = 0.0, []
        for i, (_title, count) in enumerate(self._phases):
            width = float(name) if i == self._current else free * max(1, count) / max(1, rest)
            out.append(QRectF(x, 0, width, self.height()))
            x += width + gap
        return out

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        done = QColor(theme.colour("success"))
        here = QColor(theme.colour("accent"))
        ahead = QColor(theme.colour("tertiary"))
        for i, box in enumerate(self._segments()):
            colour = here if i == self._current else done if i < self._current else ahead
            if i == self._current:
                painter.setPen(Qt.PenStyle.NoPen)
                fill = QColor(colour)
                fill.setAlpha(46)
                painter.setBrush(fill)
                painter.drawRoundedRect(box, 6, 6)
                painter.setPen(colour)
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._phases[i][0])
            else:
                bar = QRectF(box.x(), box.center().y() - 3, box.width(), 6)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(colour)
                painter.drawRoundedRect(bar, 3, 3)
        painter.end()

    def phase_at(self, x: float) -> int:
        for i, box in enumerate(self._segments()):
            if box.left() <= x <= box.right():
                return i
        return -1

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        i = self.phase_at(event.position().x())
        self.setToolTip(self._phases[i][0] if 0 <= i < len(self._phases) else "")
        super().mouseMoveEvent(event)


# -- the card ------------------------------------------------------------------------------------


class BenchView(QWidget):
    """One step, large, with Back and "Done, next" under it.

    The window hands it the items (``set_items``), the ticks (``set_done``), and a
    ``picture`` callback for a step's picture; it says when the step shown changes
    (``moved``), when a tick changes (``ticked``), and when a chip is pressed."""

    moved = Signal(int)
    ticked = Signal(str, bool)
    overview_wanted = Signal()
    cut_list_wanted = Signal()
    track_cuts_wanted = Signal()
    export_wanted = Signal()
    save_wanted = Signal()

    PICTURE = QSize(560, 400)

    def __init__(self, picture: Callable[[BenchItem, QSize], QPixmap]) -> None:
        super().__init__()
        self._picture = picture
        self.items: list[BenchItem] = []
        self.done: set[str] = set()
        self.current = 0
        self._phases: list[BenchPhase] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE["xl"], theme.SPACE["lg"], theme.SPACE["xl"], theme.SPACE["lg"])
        root.setSpacing(theme.SPACE["lg"])

        self.phase_bar = PhaseBar()
        root.addWidget(self.phase_bar)
        # The counter and the chips in a box that turns into two rows in a narrow panel.
        top = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._top = top
        self.counter = QLabel()
        theme.tone(self.counter, "secondary")
        top.addWidget(self.counter)
        chips = QHBoxLayout()
        chips.addStretch(1)
        top.addLayout(chips)
        self.chips: dict[str, QToolButton] = {}
        for name, wanted, label in (
            ("cuts", self.cut_list_wanted, t("Cut list")),
            ("tracks", self.track_cuts_wanted, t("Track cuts")),
            ("overview", self.overview_wanted, t("Overview")),
        ):
            chip = QToolButton()
            chip.setText(label)
            chip.setAutoRaise(True)
            chip.clicked.connect(wanted.emit)
            chips.addWidget(chip)
            self.chips[name] = chip
        root.addLayout(top)

        # The step, or the ending once the last one is done (``show_ending``).
        self.card = QWidget()
        card = QVBoxLayout(self.card)
        card.setContentsMargins(0, 0, 0, 0)
        card.setSpacing(theme.SPACE["lg"])
        self.title = QLabel()
        self.title.setWordWrap(True)
        # Sizes in pixels, as the type scale is: the window's font is set in pixels, so a
        # point size reads -1 and scaling it did nothing.
        theme.size(self.title, TITLE_PX)
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        card.addWidget(self.title)

        # Picture beside the facts in a wide panel, above them in a narrow one
        # (``resizeEvent``): side by side, the bench held the guide's panel at 496 px.
        body = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._body = body
        body.setSpacing(theme.SPACE["xl"])
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumSize(QSize(160, 120))
        self.picture.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.picture, 3)
        side = QVBoxLayout()
        side.setSpacing(theme.SPACE["md"])
        self.polarity = QLabel()
        self.polarity.setWordWrap(True)
        theme.size(self.polarity, POLARITY_PX)
        bold = self.polarity.font()
        bold.setBold(True)
        self.polarity.setFont(bold)
        theme.tone(self.polarity, "warning")
        side.addWidget(self.polarity)
        self.facts = QGridLayout()
        self.facts.setHorizontalSpacing(theme.SPACE["md"])
        self.facts.setColumnStretch(1, 1)
        side.addLayout(self.facts)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        side.addWidget(self.notes)
        self.checks_title = QLabel(t("Checks for this phase"))
        cfont = self.checks_title.font()
        cfont.setBold(True)
        self.checks_title.setFont(cfont)
        side.addWidget(self.checks_title)
        # The checks scroll, and take the room left under the step's facts. In a column
        # they were a layout every row of which the panel had to hold: a phase of nine in a
        # 1280 x 720 window was nine rows drawn over one another (the release walkthrough).
        self.checks, self.checks_scroll = _scrolling()
        side.addWidget(self.checks_scroll, 1)
        body.addLayout(side, 2)
        card.addLayout(body, 1)
        self.ending = self._build_ending()
        self.pages = QStackedWidget()
        self.pages.addWidget(self.card)
        self.pages.addWidget(self.ending)
        root.addWidget(self.pages, 1)

        buttons = QHBoxLayout()
        self.back = QPushButton(t("◀  Back"))
        self.next = QPushButton(t("Done, next  ▶"))
        theme.variant(self.next, "primary")
        for button in (self.back, self.next):
            button.setMinimumHeight(64)
            button.setProperty("bench", True)
            theme.restyle(button)
            button.setAutoDefault(False)
        self.back.clicked.connect(self.go_back)
        self.next.clicked.connect(self.done_and_next)
        buttons.addWidget(self.back, 1)
        buttons.addWidget(self.next, 2)
        root.addLayout(buttons)

    def _build_ending(self) -> QWidget:
        ending = QWidget()
        column = QVBoxLayout(ending)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACE["lg"])
        self.ending_title = QLabel()
        self.ending_title.setWordWrap(True)
        theme.size(self.ending_title, TITLE_PX)
        font = self.ending_title.font()
        font.setBold(True)
        self.ending_title.setFont(font)
        column.addWidget(self.ending_title)
        self.go_to_first = QPushButton()
        self.go_to_first.setAutoDefault(False)
        self.go_to_first.clicked.connect(self._go_to_first_not_done)
        column.addWidget(self.go_to_first, 0, Qt.AlignmentFlag.AlignLeft)
        self.ending_said = QLabel()
        self.ending_said.setWordWrap(True)
        column.addWidget(self.ending_said)
        # A phase's checks under its name, scrolling: a small circuit has forty of them.
        self.ending_checks, self.ending_scroll = _scrolling()
        column.addWidget(self.ending_scroll, 1)
        # Save and the export side by side, as Back and Done are: one to a row, they took
        # the room the checks list scrolls in.
        row = QHBoxLayout()
        self.save_button = QPushButton(t("Save"))
        self.export_button = QPushButton(t("Export the Guide…"))
        theme.variant(self.export_button, "primary")
        for button, wanted, stretch in (
            (self.save_button, self.save_wanted, 1),
            (self.export_button, self.export_wanted, 2),
        ):
            button.setMinimumHeight(44)
            button.setAutoDefault(False)
            button.clicked.connect(wanted.emit)
            row.addWidget(button, stretch)
        column.addLayout(row)
        return ending

    #: Below this width the picture goes above the facts and the chips under the counter.
    NARROW = 640

    def resizeEvent(self, event: QResizeEvent) -> None:
        narrow = event.size().width() < self.NARROW
        self._body.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        )
        self._top.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        )
        super().resizeEvent(event)

    def minimumSizeHint(self) -> QSize:
        """As narrow as the stacked arrangement needs, which is what it turns into when it
        is narrow: the side-by-side one would hold the panel wide (``resizeEvent``)."""
        return QSize(280, 360)

    # -- what it shows --

    def set_items(self, items: list[BenchItem], phases: Sequence[BenchPhase], done: set[str],
                  cut_count: int, track_count: int) -> None:
        """A new build: start on the first item not ticked off -- where somebody coming back
        to the bench left off."""
        self.items, self._phases, self.done = items, list(phases), set(done)
        self.chips["cuts"].setVisible(cut_count > 0)
        self.chips["cuts"].setText(f"{t('Cut list')}  {cut_count}")
        self.chips["tracks"].setVisible(track_count > 0)
        self.chips["tracks"].setText(f"{t('Track cuts')}  {track_count}")
        first = next((i for i, item in enumerate(items) if item.key not in self.done), None)
        if first is None and items:
            # Every step ticked: somebody coming back to a finished board is at its end.
            self.current = len(items) - 1
            self.show_ending()
            return
        self.show_item(first or 0)

    def set_done(self, done: set[str]) -> None:
        self.done = set(done)
        self._fill_checks()
        if self.pages.currentWidget() is self.ending:
            self.show_ending()

    def show_item(self, index: int) -> None:
        if not self.items:
            self.title.setText("")
            self.picture.clear()
            self.back.setEnabled(False)
            self.next.setEnabled(False)
            return
        index = max(0, min(index, len(self.items) - 1))
        self.current = index
        item = self.items[index]
        self.pages.setCurrentWidget(self.card)
        self.counter.setText(t("Step {n} of {total}").format(n=index + 1, total=len(self.items)))
        self._show_phase(item.phase)
        self.title.setText(item.title)
        self.polarity.setText(f"⚠  {t('Polarity')}: {item.polarity}" if item.polarity else "")
        self.polarity.setVisible(bool(item.polarity))
        _empty(self.facts)
        for row, (what, value) in enumerate(item.facts):
            name = QLabel(what)
            theme.tone(name, "secondary")
            shown_value = QLabel(value)
            shown_value.setWordWrap(True)
            self.facts.addWidget(name, row, 0, Qt.AlignmentFlag.AlignTop)
            self.facts.addWidget(shown_value, row, 1)
        self.notes.setText("\n".join(f"•  {note}" for note in item.notes))
        self.notes.setVisible(bool(item.notes))
        self.picture.setPixmap(self._picture(item, self.PICTURE))
        self._fill_checks()
        self.back.setEnabled(index > 0)
        self.next.setEnabled(True)
        self.next.setVisible(True)
        last = index == len(self.items) - 1
        self.next.setText(t("Done  ✓") if last else t("Done, next  ▶"))
        self.moved.emit(index)

    def _shown_phases(self) -> list[BenchPhase]:
        return [p for p in self._phases if any(i.phase is p for i in self.items)]

    def _show_phase(self, phase: BenchPhase) -> None:
        shown = self._shown_phases()
        self.phase_bar.set_phases(
            [(f"{p.number}. {p.title}", sum(1 for i in self.items if i.phase is p)) for p in shown],
            next((n for n, p in enumerate(shown) if p is phase), -1),
        )

    def show_ending(self) -> None:
        """After the last step: what is left, and the export and Save. Nothing is ticked
        here that the builder did not tick."""
        if not self.items:
            return
        total = len(self.items)
        missing = [i for i, item in enumerate(self.items) if item.key not in self.done]
        self.counter.setText(t("{done} of {total} steps done").format(done=total - len(missing), total=total))
        self._show_phase(self.items[-1].phase)
        if not missing:
            self.ending_title.setText(t("Every step is done."))
        elif len(missing) == 1:
            self.ending_title.setText(t("1 step is not ticked yet"))
        else:
            self.ending_title.setText(t("{n} steps are not ticked yet").format(n=len(missing)))
        self.go_to_first.setVisible(bool(missing))
        if missing:
            self.go_to_first.setText(t("Go to Step {n}").format(n=missing[0] + 1))
        _empty(self.ending_checks)
        # Every phase's, including one with no step: see the module's note.
        checks = {check_key(phase, check): (phase, check) for phase in self._phases for check in phase.checkpoints}
        open_checks = [(key, phase, check) for key, (phase, check) in checks.items() if key not in self.done]
        if not checks:
            self.ending_said.setText("")
        elif not open_checks:
            self.ending_said.setText(t("Every check is ticked too."))
        else:
            self.ending_said.setText(
                t("Checks not ticked yet. Measure each with the board in front of you, and "
                  "tick it when it reads what it should.")
            )
            heading: BenchPhase | None = None
            for key, phase, check in open_checks:
                if phase is not heading:
                    heading = phase
                    name = QLabel(f"{phase.number}. {phase.title}")
                    name.setWordWrap(True)
                    bold = name.font()
                    bold.setBold(True)
                    name.setFont(bold)
                    self.ending_checks.addWidget(name)
                box = QCheckBox(f"Ω  {check.title}")
                box.setToolTip(f"{check.instruction}\n{check.expected}")
                box.toggled.connect(lambda on, k=key: self._tick(k, on))
                self.ending_checks.addWidget(box)
            self.ending_checks.addStretch(1)
        self.ending_said.setVisible(bool(checks))
        self.ending_scroll.setVisible(bool(open_checks))
        self.pages.setCurrentWidget(self.ending)
        self.back.setEnabled(True)
        self.next.setVisible(False)

    def _go_to_first_not_done(self) -> None:
        first = next((i for i, item in enumerate(self.items) if item.key not in self.done), None)
        if first is not None:
            self.show_item(first)

    def _fill_checks(self) -> None:
        _empty(self.checks)
        if not self.items:
            return
        phase = self.items[self.current].phase
        self.checks_title.setVisible(bool(phase.checkpoints))
        rows = 0
        for check in phase.checkpoints:
            key = check_key(phase, check)
            box = QCheckBox(f"Ω  {check.title}")
            box.setToolTip(f"{check.instruction}\n{check.expected}")
            box.setChecked(key in self.done)
            box.toggled.connect(lambda on, k=key: self._tick(k, on))
            self.checks.addWidget(box)
            rows = box.sizeHint().height() + self.checks.spacing()
        self.checks.addStretch(1)
        # Room for a few whichever way the panel is cut, and the scroll bar for the rest.
        self.checks_scroll.setMinimumHeight(min(len(phase.checkpoints), 3) * rows)

    # -- walking the build --

    def _tick(self, key: str, on: bool) -> None:
        if on:
            self.done.add(key)
        else:
            self.done.discard(key)
        self.ticked.emit(key, on)

    def done_and_next(self) -> None:
        """The step in front of you is done: ticked, and the next one shown -- or, after
        the last, the ending."""
        if not self.items:
            return
        item = self.items[self.current]
        if item.key not in self.done:
            self._tick(item.key, True)
        if self.current + 1 < len(self.items):
            self.show_item(self.current + 1)
        else:
            self.show_ending()

    def go_back(self) -> None:
        if self.pages.currentWidget() is self.ending:
            self.show_item(self.current)  # the last step, where the ending was reached from
        elif self.current > 0:
            self.show_item(self.current - 1)


def _empty(layout: QLayout) -> None:
    """Take every row out of ``layout``, and out of sight now.

    ``deleteLater`` alone left the old rows painted under the new ones until the event loop
    came round to deleting them -- the previous step's Holes and Height over a cable's
    wires, in a walkthrough that pumped events without going back to the loop."""
    while layout.count():
        taken = layout.takeAt(0)
        widget = taken.widget() if taken is not None else None
        if widget is not None:
            widget.hide()
            widget.deleteLater()


def _scrolling() -> tuple[QVBoxLayout, QScrollArea]:
    """A column of rows in a frameless scroll area: the layout to fill, and the area."""
    holder = QWidget()
    rows = QVBoxLayout(holder)
    rows.setContentsMargins(0, 0, 0, 0)
    rows.setSpacing(4)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(holder)
    return rows, area


def crop_around(
    holes: tuple[HoleCoord, ...], board: Board, side: str, size: QSize, to_scene: Callable[[HoleCoord], QPointF]
) -> QRectF:
    """The part of the board to show for a step: its holes with a margin, in the picture's
    proportions."""
    # No holes -- a cable with no end on this board -- is the whole board.
    corners = (HoleCoord(0, 0), HoleCoord(board.cols - 1, board.rows - 1))
    points = [to_scene(hole) for hole in holes or corners]
    xs, ys = [p.x() for p in points], [p.y() for p in points]
    margin = board.pitch * 3.5
    area = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).adjusted(
        -margin, -margin, margin, margin
    )
    aspect = size.width() / max(1, size.height())
    if area.width() / max(1e-6, area.height()) < aspect:
        grow = area.height() * aspect - area.width()
        area.adjust(-grow / 2, 0, grow / 2, 0)
    else:
        grow = area.width() / aspect - area.height()
        area.adjust(0, -grow / 2, 0, grow / 2)
    return area
