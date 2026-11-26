"""The build guide at the bench: assembly mode, one step at a time.

THE WINDOW BECOMES A WORKBENCH. With the guide in front, the editing panels step aside
(``AssemblyMode``) and the bench takes the window in three columns: every step of the build
down the left, ticked as it is done; the board in the middle, as it stands at the step,
cropped onto it with the hole names at its edges and each pin's hole called out; and on the
right what to do, in numbered sub-steps large enough to read from across the bench, with
which way round, what to look for and the phase's checks under it. Back and Done walk the
build, and so do the keys: Space is done, the arrows step. Chosen 2026-11-26 from three
candidates rendered on the NE555 board (the card put right, this, and a print-like sheet).

The guide was a dense tree first -- every phase, step and check of the build in one list a
few hundred pixels wide -- which is the right shape for seeing the whole build and the
wrong one for doing it. The tree is still there, one click away (Overview), and the rail
on the left is the build at a glance; a narrow panel hides the rail and shows a bar of the
phases instead, and a narrower one stacks the picture over the instruction.

EVERYTHING DONE AT THE BENCH IS AN ITEM, in the order it is done:

- phase 0's jobs (``guide.PhaseTask``): the board cut to size, its mounting holes drilled,
  hole A1 marked -- the summary always said them, and nothing could be ticked;
- a stripboard's track cuts, each with its own picture: the first thing done and the one
  most often forgotten;
- every step of every phase;
- the last phase's checks: its measurements together as one item -- every short test made
  with no power, a row each to tick -- then each look before power its own item, the ICs
  fitted on their pin 1 among them, and the power-up last. "Closing up" has no step, so a
  builder walking the bench never saw the one measurement to make before power goes on.
  Done on a check's own item is the builder saying it is right; a measurement is ticked on
  its row, and nothing else ticks one;
- each cable of a system's harness (``harness.py``), fitted once every board is built --
  to connectors already soldered -- and checked end to end before anything is powered,
  under a phase of its own: "9. Harness". Nine, because the guide's phases stop at eight and
  a check's tick is kept under its phase's number (``check_key``): a harness check numbered
  8 would have shared Closing up's store. A cable is pictured on the finished board, at this
  board's end of it.

THE BUILD HAS AN END. The last item's button says "Done ✓", and pressing it shows what is
left rather than nothing at all. The ending says whether every step is ticked (and goes to
the first one that is not), lists the checks not ticked yet to tick there -- of EVERY phase
-- and offers the export and Save. It ticks nothing on the builder's behalf: a check is a
measurement, and only the person holding the meter knows whether it read what it should.

PRESENTATION ONLY. Every word of a step, its order and its checks are the guide's (the
engine's, in the guide's language); the window adds the frame and the sub-steps it reads off
the step's facts. The ticks are the window's one store of them (``MainWindow._done_steps``),
so ticking here and in the overview cannot disagree. Every colour is read from the theme
when it is used, and ``refresh_theme`` reads them again: the bench follows a live switch.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Literal

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QDockWidget,
    QFrame,
    QGraphicsScene,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio.breadboard import has_breadboard_pattern, is_breadboard
from perfboard_studio.connectivity import FootprintLookup, PhysicalPinRef
from perfboard_studio.geometry import all_pin_holes, column_label, format_hole, row_label
from perfboard_studio.guide import (
    CONDUCTOR_WORDS,
    Checkpoint,
    ConductorStep,
    Guide,
    GuidePhase,
    GuideStep,
    PartStep,
    PhaseTask,
    TrackCutJob,
    step_focus,
)
from perfboard_studio.guide_export import harness_end
from perfboard_studio.harness import HarnessCable, HarnessWire
from perfboard_studio.model import Board, BoardSide, HoleCoord, PerfDocument, pin_name_of
from perfboard_studio.phrasebook import Phrasebook, phrasebook

from . import theme
from .i18n import t
from .view2d import hole_to_screen

#: The harness's phase number on the bench: after the guide's last, Closing up (8).
HARNESS_PHASE = 9

#: A part with more pins than this has only its pin 1 called out in the picture: a DIP-28's
#: every hole named was a picture of labels.
CALLOUT_PINS = 8


@dataclass(frozen=True, slots=True)
class HarnessPhase:
    """The system's cables, as one more phase on the bench (see the module's note): what a
    phase is to the bench -- a number, a title, its checks -- and no more."""

    number: int
    title: str
    checkpoints: tuple[Checkpoint, ...]


type BenchPhase = GuidePhase | HarnessPhase

type ItemKind = Literal["task", "cut", "part", "conductor", "measure", "check", "cable"]

#: What a meter reads, ticked as a row under an item rather than walked one by one: the
#: last phase's are one item of them all (see the module's note).
MEASUREMENTS = frozenset({"continuity", "isolation", "resistance"})


@dataclass(frozen=True, slots=True)
class BenchItem:
    """One thing done at the bench: a job of phase 0, a stripboard's track cut, a step of
    the guide, a check of the last phase, or a cable of the harness."""

    #: What the tick is kept under: ``task:<kind>``, ``cut:col,row``, the step's
    #: ``step_focus``, the check's ``check_key`` or ``cable:<id>``.
    key: str
    phase: BenchPhase
    #: The item in one line, as the overview's list says it.
    title: str
    #: The step's index in the guide's flat list -- what the 3D slider and
    #: ``document_at_step`` count in -- or None for anything that is not a step.
    step_index: int | None
    holes: tuple[HoleCoord, ...]
    #: Done from the solder side: a trace, a wire below, a cut. The picture is from there.
    solder_side: bool
    polarity: str | None
    #: What to read off the card besides the instruction: (what, value).
    facts: tuple[tuple[str, str], ...]
    notes: tuple[str, ...]
    #: The component to select in the picture, if the item is about one part.
    component_id: str | None = None
    #: Done on the finished board -- a cable, or a check made once every part is soldered:
    #: pictured as the board stands at the end, not at a step of its build.
    built: bool = False
    kind: ItemKind = "part"
    #: The large line at the top of the instruction ("R1  10k"), and the one under it (the
    #: package, in words). An empty headline is the title.
    headline: str = ""
    subline: str = ""
    #: The instruction as a paragraph -- a job's, a check's -- and as numbered sub-steps.
    said: str = ""
    how: tuple[str, ...] = ()
    #: What it should look or read like once done.
    expected: str = ""
    #: A check that must pass before power goes on.
    blocking: bool = False
    #: A part's reference and its pins' holes, which is how a check's probes, named by pin,
    #: are found on the board.
    ref: str = ""
    pin_holes: tuple[tuple[str, HoleCoord], ...] = ()
    board: Board | None = None

    @property
    def heading(self) -> str:
        return self.headline or self.title


def check_key(phase: BenchPhase, check: Checkpoint) -> str:
    """What a check's tick is kept under, beside the steps' in the same store."""
    return f"check:{phase.number}:{check.title}"


def bench_items(
    guide: Guide, steps: list[GuideStep], ends_here: Mapping[str, str] | None = None
) -> list[BenchItem]:
    """Everything done at the bench, in the guide's order (see the module's note).

    ``ends_here`` is each cable's connector on this board, by cable id: where a cable's
    step is pictured. A cable with no end on this board is pictured as the whole board."""
    say = phrasebook(guide.language)
    board = guide.board
    items: list[BenchItem] = []
    index = {id(step): number for number, step in enumerate(steps)}
    parts = {
        step.ref: step
        for phase in guide.phases
        for step in phase.steps
        if isinstance(step, PartStep)
    }
    last = guide.phases[-1] if guide.phases else None
    for number, phase in enumerate(guide.phases):
        if number == 0:
            items.extend(_task_item(task, phase, board) for task in phase.tasks)
            items.extend(_cut_item(cut, phase, board, say) for cut in guide.track_cuts)
        for step in phase.steps:
            items.append(_step_item(step, phase, index.get(id(step)), board, say))
        if phase is last and not phase.steps:
            if any(check.kind in MEASUREMENTS for check in phase.checkpoints):
                items.append(_measure_item(phase, board))
            items.extend(
                _check_item(check, phase, parts, board)
                for check in phase.checkpoints
                if check.kind not in MEASUREMENTS
            )
    if guide.harness:
        harness = HarnessPhase(
            HARNESS_PHASE,
            say("Harness"),
            tuple(check for cable in guide.harness for check in cable.checkpoints),
        )
        by_id = {step.component_id: step for step in parts.values()}
        for cable in guide.harness:
            connector = (ends_here or {}).get(cable.cable_id)
            items.append(_cable_item(cable, harness, by_id.get(connector or ""), say, board))
    return items


def bench_phases(guide: Guide, items: Sequence[BenchItem]) -> list[BenchPhase]:
    """The guide's phases, then the harness's when ``items`` have one -- the very object
    the items carry, since the bench tells a phase by identity."""
    harness = next((item.phase for item in items if isinstance(item.phase, HarnessPhase)), None)
    return [*guide.phases, *([harness] if harness is not None else [])]


def pin_names(
    document: PerfDocument, lookup: FootprintLookup, component_id: str
) -> dict[HoleCoord, str]:
    """What each of a part's leads is called, by the hole it goes in: its own name for it
    ("VCC", "K") where it has one, its number where it has not -- the callouts' words."""
    component = next((c for c in document.components if c.id == component_id), None)
    footprint = lookup(component.footprint_id) if component is not None else None
    if component is None or footprint is None:
        return {}
    return {
        hole: pin_name_of(component, pin) or str(pin.number)
        for pin, hole in all_pin_holes(component, footprint)
    }


# -- what each kind of item says --------------------------------------------------------------


def _bold(text: str) -> str:
    return f"<b>{text}</b>"


def _holes_said(holes: Sequence[HoleCoord], board: Board, most: int = 4) -> str:
    shown = "  ".join(_bold(format_hole(hole, board)) for hole in holes[:most])
    return shown + (" …" if len(holes) > most else "")


def _task_item(task: PhaseTask, phase: GuidePhase, board: Board) -> BenchItem:
    return BenchItem(
        key=f"task:{task.kind}", phase=phase, title=task.title, step_index=None,
        holes=task.holes, solder_side=False, polarity=None, facts=(), notes=(),
        kind="task", said=task.instruction, board=board,
    )


def _cut_item(cut: TrackCutJob, phase: GuidePhase, board: Board, say: Phrasebook) -> BenchItem:
    hole = format_hole(cut.at, board)
    return BenchItem(
        key=f"cut:{cut.at.col},{cut.at.row}", phase=phase, title=f"{hole} · {cut.strip}",
        step_index=None, holes=(cut.at, *(cut.separates or ())), solder_side=True,
        polarity=None, facts=(), notes=(say("Cut these tracks first"),), kind="cut",
        how=(
            t("Drill out the copper at {hole}, turning the bit by hand.").format(hole=_bold(hole)),
            t("Check with the meter that the strip is open across it."),
        ),
        board=board,
    )


def _measure_item(phase: GuidePhase, board: Board) -> BenchItem:
    """The last phase's measurements as one item, each a row to tick under it."""
    return BenchItem(
        key=f"measure:{phase.number}", phase=phase, title=t("Measure before power"),
        step_index=None, holes=(), solder_side=False, polarity=None, facts=(), notes=(),
        built=True, kind="measure",
        said=t("With no power on the board, measure each pair below and tick it when it reads "
               "what it should."),
        blocking=True, board=board,
    )


def _check_item(
    check: Checkpoint, phase: GuidePhase, parts: Mapping[str, PartStep], board: Board
) -> BenchItem:
    """One of the last phase's checks as an item of its own: where to put the probes is its
    picture, and the part it is about -- an IC fitted on its pin 1 -- is selected in it."""
    holes = check.holes or _pin_holes(check.pins, parts)
    refs = {pin.component_ref for pin in check.pins}
    part = parts.get(next(iter(refs))) if len(refs) == 1 else None
    return BenchItem(
        key=check_key(phase, check), phase=phase, title=check.title, step_index=None,
        holes=holes, solder_side=False, polarity=None, facts=(), notes=(),
        component_id=part.component_id if part is not None else None, built=True,
        kind="check", said=check.instruction, expected=check.expected,
        blocking=check.blocking, board=board,
    )


def _pin_holes(
    pins: Sequence[PhysicalPinRef], parts: Mapping[str, PartStep]
) -> tuple[HoleCoord, ...]:
    holes: list[HoleCoord] = []
    for ref in pins:
        part = parts.get(ref.component_ref)
        hole = next((at for pin, at in part.pin_holes if pin == ref.pin), None) if part else None
        if hole is not None:
            holes.append(hole)
    return tuple(holes)


def _cut_said(wire: HarnessWire, say: Phrasebook) -> str:
    length = say("cut to fit") if wire.cut_mm is None else f"{wire.cut_mm:.0f} mm"
    return f"{length} · AWG {wire.awg}"


def _cable_item(
    cable: HarnessCable, phase: HarnessPhase, here: PartStep | None, say: Phrasebook,
    board: Board,
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
        notes=(),
        component_id=here.component_id if here is not None else None,
        built=True,
        kind="cable",
        # Shown as rich text, as every sub-step is: the guide's words, escaped.
        how=tuple(escape(line) for line in (*cable.steps, *((cable.note,) if cable.note else ()))),
        board=board,
    )


def _step_item(
    step: GuideStep, phase: GuidePhase, index: int | None, board: Board, say: Phrasebook
) -> BenchItem:
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
            # A part on the solder side is fitted from there, and pictured from there.
            holes=holes, solder_side=step.side == "bottom", polarity=step.polarity, facts=facts,
            notes=step.notes, component_id=step.component_id, kind="part",
            headline=f"{step.ref}  {step.value}".strip(), subline=step.footprint_name,
            how=_part_how(step, board), ref=step.ref, pin_holes=step.pin_holes, board=board,
        )
    assert isinstance(step, ConductorStep)
    facts = ((t("Holes"), step.span),)
    if step.cut is not None:
        facts = (*facts, (t("Wire to cut"), f"{step.cut.cut_mm:.0f} mm · AWG {step.cut.awg}"))
    return BenchItem(
        key=step_focus(step), phase=phase, title=step.title, step_index=index,
        holes=step.path, solder_side=step.side == "bottom", polarity=None, facts=facts,
        notes=step.notes, kind="conductor", headline=step.net_name,
        subline=f"{_conductor_word(step, say)} · {step.span}",
        how=_conductor_how(step, board, say), board=board,
    )


def _conductor_word(step: ConductorStep, say: Phrasebook) -> str:
    return say(CONDUCTOR_WORDS[step.conductor_kind])


def _part_how(step: PartStep, board: Board) -> tuple[str, ...]:
    """A part's step, in the order the hands do it: bend, fit, solder."""
    holes = _holes_said([hole for _pin, hole in step.pin_holes], board)
    if is_breadboard(board):
        return (t("Press it into {holes}.").format(holes=holes),)
    how: list[str] = []
    if step.cabled:
        how.append(t("Bring each lead to its hole, as listed below."))
    else:
        if step.bend_template_mm:
            how.append(t("Bend the legs to {mm} mm apart.").format(mm=f"{step.bend_template_mm:.1f}"))
        if step.side == "bottom":
            how.append(t("Fit it from the solder side into {holes}.").format(holes=holes))
        else:
            how.append(t("Fit it from the component side into {holes}.").format(holes=holes))
    if step.side == "bottom":
        how.append(t("Solder each leg on the component side and trim it."))
    else:
        how.append(t("Turn the board over, solder each leg and trim it."))
    return tuple(how)


def _conductor_how(step: ConductorStep, board: Board, say: Phrasebook) -> tuple[str, ...]:
    """A connection, in the order the hands do it -- which depends on what it is made of."""
    if not step.path:
        return ()
    a, b = _bold(format_hole(step.path[0], board)), _bold(format_hole(step.path[-1], board))
    kind = step.conductor_kind
    if kind == "solder-trace":
        return (
            t("Tin the pads from {a} to {b}.").format(a=a, b=b),
            t("Run solder along them into one unbroken line."),
        )
    if kind == "solder-trace-wired":
        return (
            t("Lay a bare wire along the pads from {a} to {b}.").format(a=a, b=b),
            t("Solder it down at every pad it crosses."),
        )
    if kind == "lead-bend":
        return (
            t("Bend the leg along the pads from {a} to {b}.").format(a=a, b=b),
            t("Solder it down at every pad it crosses."),
        )
    how: list[str] = []
    cut = step.cut
    if cut is not None and cut.insulated:
        how.append(t("Cut {length} mm of AWG {awg} wire, {colour}, and strip {strip} mm off "
                     "each end.").format(length=f"{cut.cut_mm:.0f}", awg=cut.awg,
                                         colour=say(cut.colour), strip=f"{cut.strip_mm:g}"))
    elif cut is not None:
        how.append(t("Cut {length} mm of bare AWG {awg} wire.").format(
            length=f"{cut.cut_mm:.0f}", awg=cut.awg))
    how.append(t("Lay it from {a} to {b}, along the path in the picture.").format(a=a, b=b))
    how.append(t("Press both ends in.") if is_breadboard(board) else t("Solder both ends."))
    return tuple(how)


# -- the picture ------------------------------------------------------------------------------


def crop_around(
    holes: tuple[HoleCoord, ...], board: Board, side: str, size: QSize,
    to_scene: Callable[[HoleCoord], QPointF], margin: float = 3.5,
) -> QRectF:
    """The part of the board to show for a step: its holes with ``margin`` pitches round
    them, in the picture's proportions, slid back onto the board where it fits -- bare
    canvas beside a step at the edge was room the board could have had."""
    # No holes -- a cable with no end on this board -- is the whole board.
    corners = (HoleCoord(0, 0), HoleCoord(board.cols - 1, board.rows - 1))
    points = [to_scene(hole) for hole in holes or corners]
    xs, ys = [p.x() for p in points], [p.y() for p in points]
    pad = board.pitch * margin
    area = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).adjusted(
        -pad, -pad, pad, pad
    )
    # Never closer than a few parts' worth of board: one hole -- pin 1, A1 -- cropped to
    # its margin was a hole the size of the picture, and nothing round it to find it by.
    least = board.pitch * 12
    if area.width() < least:
        area.adjust(-(least - area.width()) / 2, 0, (least - area.width()) / 2, 0)
    aspect = size.width() / max(1, size.height())
    if area.width() / max(1e-6, area.height()) < aspect:
        grow = area.height() * aspect - area.width()
        area.adjust(-grow / 2, 0, grow / 2, 0)
    else:
        grow = area.width() / aspect - area.height()
        area.adjust(0, -grow / 2, 0, grow / 2)
    ends = [to_scene(hole) for hole in corners]
    edge = board.pitch * 0.8
    left, right = min(p.x() for p in ends) - edge, max(p.x() for p in ends) + edge
    top, bottom = min(p.y() for p in ends) - edge, max(p.y() for p in ends) + edge
    # Larger than the board one way: the board in the middle of it that way, so the bare
    # canvas is shared out on both sides rather than all left under the board.
    if area.width() <= right - left:
        if area.left() < left:
            area.moveLeft(left)
        if area.right() > right:
            area.moveRight(right)
    else:
        area.moveLeft((left + right - area.width()) / 2)
    if area.height() <= bottom - top:
        if area.top() < top:
            area.moveTop(top)
        if area.bottom() > bottom:
            area.moveBottom(bottom)
    else:
        area.moveTop((top + bottom - area.height()) / 2)
    return area


def step_pictures(
    scene: QGraphicsScene, board: Board, item: BenchItem, side: BoardSide, size: QSize,
    mini: QSize, ratio: float = 1.0, names: Mapping[HoleCoord, str] | None = None,
) -> tuple[QPixmap, QPixmap]:
    """The step's picture and the whole board beside it, from one scene.

    The picture is cropped onto the step, everything round it dimmed, the step's holes
    ringed with their names called out ("VCC · C4") and the hole names at its edges, the
    step's columns and rows lit -- a builder counting holes from A1 counts from the edge of
    the picture, not from a corner it does not show. The small one is the whole board with
    the step's place ringed: where on the board this is."""
    # A board that prints its own addresses (and every breadboard) is read off the board,
    # not off a ruler that would say the grid's.
    rulers = board.labels is None and not has_breadboard_pattern(board)
    picture = _render(scene, board, item, side, size, ratio, rulers=rulers, whole=False,
                      names=names or {})
    wide = round(mini.height() * (board.cols + 1) / max(1, board.rows + 1))
    small = QSize(max(48, min(mini.width(), wide)), mini.height())
    minimap = _render(scene, board, item, side, small, ratio, rulers=False, whole=True, names={})
    return picture, minimap


def _render(
    scene: QGraphicsScene, board: Board, item: BenchItem, side: BoardSide, size: QSize,
    ratio: float, *, rulers: bool, whole: bool, names: Mapping[HoleCoord, str],
) -> QPixmap:
    tokens = theme.ACTIVE
    pixmap = QPixmap(QSize(max(1, round(size.width() * ratio)), max(1, round(size.height() * ratio))))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    gutter_left, gutter_top = (32, 24) if rulers else (0, 0)
    target = QRectF(gutter_left, gutter_top, size.width() - gutter_left, size.height() - gutter_top)
    if target.width() < 8 or target.height() < 8:
        return pixmap

    def to_scene(hole: HoleCoord) -> QPointF:
        return hole_to_screen(hole, board, side)

    corners = tuple(
        HoleCoord(c, r) for c in (0, board.cols - 1) for r in (0, board.rows - 1)
    )
    holes = item.holes
    area = crop_around(corners if whole else holes, board, side, target.size().toSize(),
                       to_scene, margin=1.0 if whole else 3.5)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    frame = QPainterPath()
    frame.addRoundedRect(target, 8, 8)
    painter.setClipPath(frame)
    painter.fillRect(target, QColor(tokens.canvas))
    scene.render(painter, target, area)
    scale = target.width() / max(1e-6, area.width())

    def to_px(hole: HoleCoord) -> QPointF:
        at = to_scene(hole)
        return QPointF(target.x() + (at.x() - area.x()) * scale,
                       target.y() + (at.y() - area.y()) * scale)

    accent = QColor(tokens.accent)
    pitch_px = board.pitch * scale
    if holes:
        points = [to_px(hole) for hole in holes]
        pad = max(pitch_px * 1.1, 6.0)
        focus = QRectF(
            min(p.x() for p in points), min(p.y() for p in points),
            max(p.x() for p in points) - min(p.x() for p in points),
            max(p.y() for p in points) - min(p.y() for p in points),
        ).adjusted(-pad, -pad, pad, pad)
        if not focus.contains(target):
            everything = QPainterPath()
            everything.addRect(target)
            hole_ = QPainterPath()
            hole_.addRoundedRect(focus, 10, 10)
            shade = QColor(tokens.bg_app)
            shade.setAlpha(150 if tokens.name == "dark" else 130)
            painter.fillPath(everything.subtracted(hole_), shade)
        painter.setPen(QPen(accent, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(focus, 10, 10)
    if holes and not whole:
        _callouts(painter, item, board, to_px, pitch_px, names, target)
    painter.setClipping(False)
    if rulers:
        _rulers(painter, board, holes, to_px, target, gutter_left, gutter_top)
    painter.end()
    return pixmap


def _callouts(
    painter: QPainter, item: BenchItem, board: Board, to_px: Callable[[HoleCoord], QPointF],
    pitch_px: float, names: Mapping[HoleCoord, str], target: QRectF,
) -> None:
    """Each of the step's holes ringed and named: every pin of a small part, pin 1 of a
    large one, the two ends of anything else."""
    holes = list(item.holes)
    if item.component_id is not None:
        ends = holes if len(holes) <= CALLOUT_PINS else holes[:1]
    else:
        ends = list(dict.fromkeys([holes[0], holes[-1]]))
    tokens = theme.ACTIVE
    face = QFont(QGuiApplication.font())
    face.setPixelSize(13)
    face.setBold(True)
    painter.setFont(face)
    metrics = painter.fontMetrics()
    points = [to_px(hole) for hole in ends]
    cx = sum(p.x() for p in points) / len(points)
    cy = sum(p.y() for p in points) / len(points)
    # A column of pins is labelled to its sides; a row, or anything else, above and below.
    column = len(ends) > 2 and len({round(p.x()) for p in points}) <= 2
    ring = max(pitch_px * 0.33, 4.0)
    for hole, at in zip(ends, points, strict=True):
        text = format_hole(hole, board)
        name = names.get(hole)
        if name:
            text = f"{name} · {text}"
        width = metrics.horizontalAdvance(text) + 14
        if column:
            out = -1 if at.x() < cx else 1
            x = at.x() + out * (ring + 6) - (width if out < 0 else 0)
            box = QRectF(x, at.y() - 10, width, 20)
        else:
            out = -1 if at.y() <= cy else 1
            y = at.y() + out * (ring + 6) - (20 if out < 0 else 0)
            box = QRectF(at.x() - width / 2, y, width, 20)
        box.moveLeft(max(target.left() + 2, min(box.left(), target.right() - width - 2)))
        box.moveTop(max(target.top() + 2, min(box.top(), target.bottom() - 22)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens.accent))
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QColor(tokens.text_on_accent))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(tokens.text_on_accent), 2.5))
        painter.drawEllipse(at, ring, ring)
        painter.setPen(QPen(QColor(tokens.accent), 1.5))
        painter.drawEllipse(at, ring + 2, ring + 2)


def _rulers(
    painter: QPainter, board: Board, holes: Sequence[HoleCoord],
    to_px: Callable[[HoleCoord], QPointF], target: QRectF, gutter_left: int, gutter_top: int,
) -> None:
    """The columns' letters along the top and the rows' numbers down the side, the step's
    own lit."""
    tokens = theme.ACTIVE
    face = QFont(QGuiApplication.font())
    face.setPixelSize(12)
    painter.setFont(face)
    columns = {hole.col for hole in holes}
    rows = {hole.row for hole in holes}

    def label(box: QRectF, text: str, lit: bool) -> None:
        if lit:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.accent_subtle))
            painter.drawRoundedRect(box, 5, 5)
            painter.setPen(QColor(tokens.accent_text))
        else:
            painter.setPen(QColor(tokens.text_tertiary))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    for col in range(board.cols):
        x = to_px(HoleCoord(col, 0)).x()
        if target.left() + 4 <= x <= target.right() - 4:
            label(QRectF(x - 14, 1, 28, gutter_top - 5), column_label(col), col in columns)
    for row in range(board.rows):
        y = to_px(HoleCoord(0, row)).y()
        if target.top() + 4 <= y <= target.bottom() - 4:
            label(QRectF(1, y - 10, gutter_left - 6, 20), row_label(row), row in rows)


# -- the phases, along the top of a narrow bench ----------------------------------------------


class PhaseBar(QWidget):
    """The build's phases as segments, as wide as each phase is long: the current one named
    in full, the others a bar filled as far as they are ticked, their name on hover. Shown
    where the rail is not: a narrow bench."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        #: (name, items, items ticked) for each phase.
        self._phases: list[tuple[str, int, int]] = []
        self._current = -1

    def set_phases(self, phases: list[tuple[str, int, int]], current: int) -> None:
        self._phases, self._current = phases, current
        self.update()

    def _segments(self) -> list[QRectF]:
        if not self._phases:
            return []
        gap = 4.0
        name = self.fontMetrics().horizontalAdvance(self._phases[self._current][0]) + 24 if (
            0 <= self._current < len(self._phases)) else 0
        rest = sum(max(1, n) for i, (_t, n, _d) in enumerate(self._phases) if i != self._current)
        free = max(0.0, self.width() - name - gap * (len(self._phases) - 1))
        x, out = 0.0, []
        for i, (_title, count, _done) in enumerate(self._phases):
            width = float(name) if i == self._current else free * max(1, count) / max(1, rest)
            out.append(QRectF(x, 0, width, self.height()))
            x += width + gap
        return out

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tokens = theme.ACTIVE
        for i, box in enumerate(self._segments()):
            name, count, done = self._phases[i]
            painter.setPen(Qt.PenStyle.NoPen)
            if i == self._current:
                painter.setBrush(QColor(tokens.accent_subtle))
                painter.drawRoundedRect(box, 6, 6)
                painter.setPen(QColor(tokens.accent_text))
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, name)
                continue
            bar = QRectF(box.x(), box.center().y() - 3, box.width(), 6)
            painter.setBrush(QColor(tokens.bg_pressed))
            painter.drawRoundedRect(bar, 3, 3)
            if count and done:
                filled = QRectF(bar.x(), bar.y(), bar.width() * min(1.0, done / count), bar.height())
                painter.setBrush(QColor(tokens.success))
                painter.drawRoundedRect(filled, 3, 3)
        painter.end()

    def phase_at(self, x: float) -> int:
        for i, box in enumerate(self._segments()):
            if box.left() <= x <= box.right():
                return i
        return -1

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        i = self.phase_at(event.position().x())
        if 0 <= i < len(self._phases):
            name, count, done = self._phases[i]
            self.setToolTip(f"{name}  ·  {done}/{count}")
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)


class ProgressStrip(QWidget):
    """How much of the build is ticked, as a filled bar."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(8)
        self.fraction = 0.0

    def set_fraction(self, fraction: float) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        tokens = theme.ACTIVE
        whole = QRectF(self.rect())
        painter.setBrush(QColor(tokens.bg_pressed))
        painter.drawRoundedRect(whole, 4, 4)
        if self.fraction > 0:
            painter.setBrush(QColor(tokens.success))
            painter.drawRoundedRect(
                QRectF(0, 0, max(8.0, whole.width() * self.fraction), whole.height()), 4, 4
            )
        painter.end()


class _Picture(QLabel):
    """The step's picture: as large as its column, drawn again when the column is resized."""

    resized = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(QSize(200, 150))
        # Ignored: a pixmap as large as the label would otherwise hold the label at it, and
        # the bench could never be made smaller again.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.resized.emit()


# -- the bench ---------------------------------------------------------------------------------


#: What a step row in the rail keeps: its index into the items.
ROLE_ITEM = Qt.ItemDataRole.UserRole + 1


class BenchView(QWidget):
    """The bench: the steps, the board, the instruction, and Back and Done.

    The window hands it the items (``set_items``), the ticks (``set_done``), and a
    ``picture`` callback that draws an item's picture and the whole board at the sizes
    asked; it says when the item shown changes (``moved``), when a tick changes
    (``ticked``), and when a chip is pressed."""

    moved = Signal(int)
    ticked = Signal(str, bool)
    overview_wanted = Signal()
    cut_list_wanted = Signal()
    track_cuts_wanted = Signal()
    export_wanted = Signal()
    save_wanted = Signal()

    #: The picture's size before the bench has been laid out, and the whole board's.
    PICTURE = QSize(560, 400)
    MINIMAP = QSize(240, 96)
    #: At least this wide for the rail of steps, and for the picture beside the instruction.
    WIDE = 1100
    NARROW = 760
    PANE = 400

    def __init__(
        self, picture: Callable[[BenchItem, QSize, QSize], tuple[QPixmap, QPixmap]]
    ) -> None:
        super().__init__()
        self._picture = picture
        self.items: list[BenchItem] = []
        self.done: set[str] = set()
        self.current = 0
        self._phases: list[BenchPhase] = []
        self._drawn: tuple[str, int, int, str] | None = None
        # Its look is the theme's rules for these names (``theme.stylesheet``, "the build
        # guide's bench"), so a live switch of the theme recolours it with the rest.
        self.setObjectName("bench")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        root = QHBoxLayout(self)
        root.setContentsMargins(theme.SPACE["md"], theme.SPACE["md"], theme.SPACE["md"], theme.SPACE["md"])
        root.setSpacing(theme.SPACE["md"])
        self.rail = self._build_rail()
        root.addWidget(self.rail)

        # The step -- the board beside the instruction -- or the ending (``show_ending``).
        self.card = QWidget()
        card = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.card)
        self._body = card
        card.setContentsMargins(0, 0, 0, 0)
        card.setSpacing(theme.SPACE["md"])
        card.addWidget(self._build_stage(), 1)
        self.pane = self._build_pane()
        card.addWidget(self.pane)
        self.ending = self._build_ending()
        self.pages = QStackedWidget()
        self.pages.addWidget(self.card)
        self.pages.addWidget(self.ending)
        root.addWidget(self.pages, 1)

        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.setInterval(120)
        self._redraw.timeout.connect(self._draw_picture)
        self._fill_rail()

    # -- building --

    def _build_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("benchRail")
        rail.setFixedWidth(280)
        column = QVBoxLayout(rail)
        column.setContentsMargins(theme.SPACE["lg"], theme.SPACE["lg"], theme.SPACE["lg"], theme.SPACE["lg"])
        column.setSpacing(theme.SPACE["sm"])
        name = QLabel(t("Build"))
        name.setObjectName("benchRailTitle")
        column.addWidget(name)
        self.progress = ProgressStrip()
        column.addWidget(self.progress)
        self.progress_said = QLabel()
        theme.tone(self.progress_said, "secondary")
        column.addWidget(self.progress_said)
        self.steps = QListWidget()
        self.steps.setObjectName("benchSteps")
        # The keys walk the build, not the list (``keyPressEvent``).
        self.steps.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.steps.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.steps.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.steps.itemClicked.connect(self._on_rail_clicked)
        column.addWidget(self.steps, 1)
        return rail

    def _build_stage(self) -> QFrame:
        stage = QFrame()
        stage.setObjectName("benchStage")
        column = QVBoxLayout(stage)
        column.setContentsMargins(theme.SPACE["lg"], theme.SPACE["lg"], theme.SPACE["lg"], theme.SPACE["lg"])
        column.setSpacing(theme.SPACE["md"])
        # Which face is up, the counter and the chips, in a row that turns into two in a
        # narrow bench.
        top = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._top = top
        self.side = QLabel()
        self.side.setObjectName("benchSide")
        self.side.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        top.addWidget(self.side)
        top.addStretch(1)
        self.counter = QLabel()
        theme.tone(self.counter, "secondary")
        top.addWidget(self.counter)
        self.chips: dict[str, QToolButton] = {}
        for name, wanted, label in (
            ("cuts", self.cut_list_wanted, t("Cut list")),
            ("tracks", self.track_cuts_wanted, t("Track cuts")),
            ("overview", self.overview_wanted, t("Overview")),
        ):
            chip = QToolButton()
            chip.setText(label)
            chip.setAutoRaise(True)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.clicked.connect(wanted.emit)
            top.addWidget(chip)
            self.chips[name] = chip
        column.addLayout(top)
        self.phase_bar = PhaseBar()
        column.addWidget(self.phase_bar)
        self.picture = _Picture()
        self.picture.resized.connect(self._redraw_soon)
        column.addWidget(self.picture, 1)
        self.minimap = QLabel()
        self.minimap.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        column.addWidget(self.minimap)
        return stage

    def _build_pane(self) -> QFrame:
        pane = QFrame()
        pane.setObjectName("benchPane")
        pane.setFixedWidth(self.PANE)
        outer = QVBoxLayout(pane)
        outer.setContentsMargins(theme.SPACE["xl"], theme.SPACE["xl"], theme.SPACE["xl"], theme.SPACE["lg"])
        outer.setSpacing(theme.SPACE["md"])
        holder = QWidget()
        holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, theme.SPACE["sm"], 0)
        column.setSpacing(theme.SPACE["lg"])
        self.eyebrow = QLabel()
        self.eyebrow.setObjectName("benchEyebrow")
        self.eyebrow.setWordWrap(True)
        column.addWidget(self.eyebrow)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("benchTitle")
        self.title.setWordWrap(True)
        heading.addWidget(self.title)
        self.subline = QLabel()
        self.subline.setObjectName("benchSubline")
        self.subline.setWordWrap(True)
        heading.addWidget(self.subline)
        column.addLayout(heading)

        self.polarity_box = QFrame()
        self.polarity_box.setObjectName("benchPolarity")
        row = QHBoxLayout(self.polarity_box)
        row.setContentsMargins(theme.SPACE["lg"], theme.SPACE["md"], theme.SPACE["lg"], theme.SPACE["md"])
        row.setSpacing(theme.SPACE["lg"])
        icon = QLabel("⚠")
        icon.setObjectName("benchPolarityIcon")
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(2)
        caption = QLabel(t("Which way round"))
        caption.setObjectName("benchPolarityCaption")
        words.addWidget(caption)
        self.polarity = QLabel()
        self.polarity.setObjectName("benchPolarityText")
        self.polarity.setWordWrap(True)
        words.addWidget(self.polarity)
        row.addLayout(words, 1)
        column.addWidget(self.polarity_box)

        self.gate = QLabel(t("Do not power the board until this is right."))
        self.gate.setObjectName("benchGate")
        self.gate.setWordWrap(True)
        column.addWidget(self.gate)
        self.said = QLabel()
        self.said.setObjectName("benchSaid")
        self.said.setWordWrap(True)
        column.addWidget(self.said)
        self.how = QVBoxLayout()
        self.how.setSpacing(theme.SPACE["md"])
        column.addLayout(self.how)
        self.expected_caption = QLabel(t("What you should see"))
        self.expected_caption.setObjectName("benchCaption")
        column.addWidget(self.expected_caption)
        self.expected = QLabel()
        self.expected.setObjectName("benchExpected")
        self.expected.setWordWrap(True)
        column.addWidget(self.expected)
        self.notes = QLabel()
        self.notes.setObjectName("benchNotes")
        self.notes.setWordWrap(True)
        column.addWidget(self.notes)
        self.facts = QGridLayout()
        self.facts.setHorizontalSpacing(theme.SPACE["md"])
        self.facts.setColumnStretch(1, 1)
        column.addLayout(self.facts)
        self.checks_title = QLabel(t("Checks for this phase"))
        self.checks_title.setObjectName("benchCaption")
        column.addWidget(self.checks_title)
        self.checks = QVBoxLayout()
        self.checks.setSpacing(theme.SPACE["sm"])
        column.addLayout(self.checks)
        column.addStretch(1)
        # The whole instruction scrolls, the buttons under it stay: a phase of nine checks
        # in a 1280 x 720 window was nine rows drawn over one another (the release
        # walkthrough) when the checks were a layout every row of which had to fit.
        self.checks_scroll = QScrollArea()
        self.checks_scroll.setWidgetResizable(True)
        self.checks_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.checks_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.checks_scroll.setWidget(holder)
        self.checks_scroll.viewport().setAutoFillBackground(False)
        holder.setAutoFillBackground(False)
        outer.addWidget(self.checks_scroll, 1)

        buttons = QHBoxLayout()
        self.back = QPushButton(t("◀  Back"))
        self.next = QPushButton(t("Done, next  ▶"))
        theme.variant(self.next, "primary")
        for button in (self.back, self.next):
            button.setMinimumHeight(60)
            button.setProperty("bench", True)
            theme.restyle(button)
            button.setAutoDefault(False)
            # Space is Done wherever the focus is on the bench (``keyPressEvent``); a
            # focused Back would have taken it.
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.back.clicked.connect(self.go_back)
        self.next.clicked.connect(self.done_and_next)
        buttons.addWidget(self.back, 1)
        buttons.addWidget(self.next, 2)
        outer.addLayout(buttons)
        self.hint = QLabel(t("Space: done  ·  ← →: steps"))
        self.hint.setObjectName("benchHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.hint)
        return pane

    def _build_ending(self) -> QWidget:
        ending = QFrame()
        ending.setObjectName("benchStage")
        column = QVBoxLayout(ending)
        column.setContentsMargins(theme.SPACE["2xl"], theme.SPACE["xl"], theme.SPACE["2xl"], theme.SPACE["xl"])
        column.setSpacing(theme.SPACE["lg"])
        self.ending_title = QLabel()
        self.ending_title.setObjectName("benchTitle")
        self.ending_title.setWordWrap(True)
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
        # Back, Save and the export side by side, as Back and Done are.
        row = QHBoxLayout()
        self.ending_back = QPushButton(t("◀  Back"))
        self.save_button = QPushButton(t("Save"))
        self.export_button = QPushButton(t("Export the Guide…"))
        theme.variant(self.export_button, "primary")
        self.ending_back.clicked.connect(self.go_back)
        for button, wanted, stretch in (
            (self.ending_back, None, 1),
            (self.save_button, self.save_wanted, 1),
            (self.export_button, self.export_wanted, 2),
        ):
            button.setMinimumHeight(44)
            button.setAutoDefault(False)
            if wanted is not None:
                button.clicked.connect(wanted.emit)
            row.addWidget(button, stretch)
        column.addLayout(row)
        return ending

    # -- the shape of the bench --

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._arrange(event.size().width())
        super().resizeEvent(event)

    def _arrange(self, width: int) -> None:
        """The rail where there is room for it, the phase bar where there is not; the
        instruction under the picture in a narrow bench."""
        wide, narrow = width >= self.WIDE, width < self.NARROW
        self.rail.setVisible(wide)
        self.phase_bar.setVisible(not wide)
        self._body.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        )
        self._top.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        )
        if narrow:
            self.pane.setMinimumWidth(0)
            self.pane.setMaximumWidth(16777215)
        else:
            self.pane.setFixedWidth(self.PANE if wide else 340)

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
        self._drawn = None
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
        self._fill_rail()
        if self.pages.currentWidget() is self.ending:
            self.show_ending()

    def show_item(self, index: int) -> None:
        if not self.items:
            self.title.setText("")
            self.picture.clear()
            self.minimap.clear()
            self.steps.clear()
            self.back.setEnabled(False)
            self.next.setEnabled(False)
            return
        index = max(0, min(index, len(self.items) - 1))
        self.current = index
        item = self.items[index]
        self.pages.setCurrentWidget(self.card)
        self.counter.setText(t("Step {n} of {total}").format(n=index + 1, total=len(self.items)))
        self._show_phase(item.phase)
        self.side.setText(t("Solder side — turn the board over") if item.solder_side
                          else t("Component side"))
        self.side.setProperty("flipped", item.solder_side)
        theme.restyle(self.side)
        self.eyebrow.setText(f"{item.phase.number}. {item.phase.title}")
        self.title.setText(item.heading)
        self.subline.setText(item.subline)
        self.subline.setVisible(bool(item.subline))
        self.polarity.setText(item.polarity or "")
        self.polarity_box.setVisible(bool(item.polarity))
        self.gate.setVisible(item.blocking)
        self.said.setText(item.said)
        self.said.setVisible(bool(item.said))
        _empty(self.how)
        for number, text in enumerate(item.how, 1):
            self.how.addWidget(_numbered(number, text))
        self.expected.setText(item.expected)
        self.expected.setVisible(bool(item.expected))
        self.expected_caption.setVisible(bool(item.expected))
        self.notes.setText("\n".join(f"ⓘ  {note}" for note in item.notes))
        self.notes.setVisible(bool(item.notes))
        _empty(self.facts)
        for row, (what, value) in enumerate(item.facts):
            name = QLabel(what)
            theme.tone(name, "secondary")
            shown_value = QLabel(value)
            shown_value.setWordWrap(True)
            self.facts.addWidget(name, row, 0, Qt.AlignmentFlag.AlignTop)
            self.facts.addWidget(shown_value, row, 1)
        self._draw_picture()
        self._fill_checks()
        self._fill_rail()
        self.checks_scroll.verticalScrollBar().setValue(0)
        self.back.setEnabled(index > 0)
        self.next.setEnabled(True)
        self.next.setVisible(True)
        last = index == len(self.items) - 1
        self.next.setText(t("Done  ✓") if last else t("Done, next  ▶"))
        self.moved.emit(index)

    def refresh_theme(self) -> None:
        """Everything the bench paints itself, in the active theme: the rail's colours, the
        bars and the picture. Its rules are the theme's stylesheet's, which a switch
        replaces."""
        self.phase_bar.update()
        self.progress.update()
        self._fill_rail()
        if self.items and self.pages.currentWidget() is self.card and 0 <= self.current < len(self.items):
            self._drawn = None
            self._draw_picture()
        self.update()

    def _redraw_soon(self) -> None:
        if self.items and self.pages.currentWidget() is self.card:
            self._redraw.start()

    def _draw_picture(self) -> None:
        """The current item's picture at the size of its column, unless it is drawn at that
        size already."""
        if not self.items or not 0 <= self.current < len(self.items):
            return
        item = self.items[self.current]
        size = self.picture.size()
        if size.width() < 200 or size.height() < 150:
            size = self.PICTURE
        key = (item.key, size.width(), size.height(), theme.ACTIVE.name)
        if key == self._drawn:
            return
        picture, minimap = self._picture(item, size, self.MINIMAP)
        self._drawn = key
        self.picture.setPixmap(picture)
        self.minimap.setPixmap(minimap)

    def _shown_phases(self) -> list[BenchPhase]:
        return [p for p in self._phases if any(i.phase is p for i in self.items)]

    def _show_phase(self, phase: BenchPhase) -> None:
        shown = self._shown_phases()
        self.phase_bar.set_phases(
            [
                (
                    f"{p.number}. {p.title}",
                    sum(1 for i in self.items if i.phase is p),
                    sum(1 for i in self.items if i.phase is p and i.key in self.done),
                )
                for p in shown
            ],
            next((n for n, p in enumerate(shown) if p is phase), -1),
        )

    def _fill_rail(self) -> None:
        """Every phase with its items under it, each marked done, here, or to do."""
        if not hasattr(self, "steps"):
            return
        tokens = theme.ACTIVE
        quiet = self.steps.blockSignals(True)
        self.steps.clear()
        total = len(self.items)
        ticked = sum(1 for item in self.items if item.key in self.done)
        self.progress.set_fraction(ticked / total if total else 0.0)
        self.progress_said.setText(t("{done} of {total} steps done").format(done=ticked, total=total))
        here: QListWidgetItem | None = None
        heading_font = QFont(self.steps.font())
        heading_font.setBold(True)
        for phase in self._shown_phases():
            members = [(n, item) for n, item in enumerate(self.items) if item.phase is phase]
            finished = sum(1 for _n, item in members if item.key in self.done)
            complete = finished == len(members)
            head = QListWidgetItem(
                f"{'✓' if complete else phase.number}  {phase.title}   {finished}/{len(members)}"
            )
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            head.setFont(heading_font)
            head.setForeground(QBrush(QColor(
                tokens.success if complete else tokens.text if any(
                    n == self.current for n, _i in members) else tokens.text_secondary
            )))
            self.steps.addItem(head)
            for n, item in members:
                is_done = item.key in self.done
                mark = "✓" if is_done else "●" if n == self.current else "○"
                # A connection by its net and holes: a phase of them by net alone was a
                # column of "GND", "GND", "GND".
                shown = item.heading if item.kind == "part" else item.title
                row = QListWidgetItem(f"   {mark}   {shown}")
                row.setData(ROLE_ITEM, n)
                row.setToolTip(item.title)
                row.setForeground(QBrush(QColor(
                    tokens.text if n == self.current
                    else tokens.text_tertiary if is_done else tokens.text_secondary
                )))
                self.steps.addItem(row)
                if n == self.current:
                    here = row
        if here is not None and self.pages.currentWidget() is self.card:
            self.steps.setCurrentItem(here)
            self.steps.scrollToItem(here, QListWidget.ScrollHint.PositionAtCenter)
        else:
            self.steps.clearSelection()
        self.steps.blockSignals(quiet)

    def _on_rail_clicked(self, row: QListWidgetItem) -> None:
        index = row.data(ROLE_ITEM)
        if isinstance(index, int):
            self.show_item(index)

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
        self._fill_rail()
        self.back.setEnabled(True)
        self.next.setVisible(False)

    def _go_to_first_not_done(self) -> None:
        first = next((i for i, item in enumerate(self.items) if item.key not in self.done), None)
        if first is not None:
            self.show_item(first)

    def _probe_holes(self) -> dict[tuple[str, str], HoleCoord]:
        return {
            (item.ref, pin): hole
            for item in self.items
            if item.ref
            for pin, hole in item.pin_holes
        }

    def _fill_checks(self) -> None:
        """The phase's checks under the step, each with where the probes go and what it
        should read -- on the card, not in a tooltip. Not those that are items of their
        own, and none under such an item: it is the check."""
        _empty(self.checks)
        if not self.items:
            return
        item = self.items[self.current]
        phase = item.phase
        walked = {i.key for i in self.items}
        shown = [] if item.kind == "check" else [
            check for check in phase.checkpoints if check_key(phase, check) not in walked
        ]
        self.checks_title.setVisible(bool(shown))
        probes = self._probe_holes() if shown else {}
        for check in shown:
            key = check_key(phase, check)
            row = QFrame()
            row.setObjectName("benchCheck")
            row.setProperty("blocking", check.blocking)
            grid = QVBoxLayout(row)
            grid.setContentsMargins(theme.SPACE["md"], theme.SPACE["sm"], theme.SPACE["md"], theme.SPACE["sm"])
            grid.setSpacing(2)
            box = QCheckBox(f"Ω  {check.title}")
            box.setToolTip(f"{check.instruction}\n{check.expected}")
            box.setChecked(key in self.done)
            box.toggled.connect(lambda on, k=key: self._tick(k, on))
            grid.addWidget(box)
            holes = check.holes or tuple(
                probes[(pin.component_ref, pin.pin)]
                for pin in check.pins
                if (pin.component_ref, pin.pin) in probes
            )
            board = item.board
            where = " ↔ ".join(format_hole(hole, board) for hole in holes)
            detail = QLabel(f"{where}  ·  {check.expected}" if where else check.expected)
            detail.setObjectName("benchProbe")
            detail.setWordWrap(True)
            grid.addWidget(detail)
            self.checks.addWidget(row)

    # -- walking the build --

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Space (or Enter) is Done; the arrows step without ticking."""
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.pages.currentWidget() is self.card:
                self.done_and_next()
        elif key == Qt.Key.Key_Left:
            self.go_back()
        elif key == Qt.Key.Key_Right:
            if self.pages.currentWidget() is self.card and self.current + 1 < len(self.items):
                self.show_item(self.current + 1)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def _tick(self, key: str, on: bool) -> None:
        if on:
            self.done.add(key)
        else:
            self.done.discard(key)
        self.ticked.emit(key, on)
        self._fill_rail()

    def done_and_next(self) -> None:
        """The item in front of you is done: ticked, and the next one shown -- or, after
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


def _numbered(number: int, text: str) -> QWidget:
    """One sub-step: its number in a disc, and the words beside it."""
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(theme.SPACE["md"])
    disc = QLabel(str(number))
    disc.setObjectName("benchNumber")
    disc.setFixedSize(24, 24)
    disc.setAlignment(Qt.AlignmentFlag.AlignCenter)
    line.addWidget(disc, 0, Qt.AlignmentFlag.AlignTop)
    words = QLabel(text)
    words.setObjectName("benchHow")
    words.setTextFormat(Qt.TextFormat.RichText)
    words.setWordWrap(True)
    line.addWidget(words, 1)
    return row


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


# -- assembly mode ----------------------------------------------------------------------------


class AssemblyMode:
    """The editing panels step aside while the guide is in front, and come back as they
    were when it is not.

    Only when the guide is a tab among the views -- where it opens -- and not floating: a
    guide somebody dragged beside the board is a layout they chose, and hiding everything
    round it would take the board away. The panels hidden are those that were open; which
    of a tab group was in front is remembered too, because a group shown again puts its
    first tab in front, not the one that was.

    The window's layout is PHOTOGRAPHED before anything is hidden, and while the bench has
    the window that photograph is the layout (``photograph``): a session saved, or Home
    shown, in assembly mode keeps the panels somebody arranged, never a window of one
    panel. Home takes the photograph over (``hand_over``), because it hides every panel
    and puts the window back from it itself. The panels' visibility is decided after the
    event loop comes round, from where the guide actually is: a tab switch reports the old
    tab hidden before the new one shown.

    It keeps the window, never a function of it: a lambda holding the window outlived
    QApplication and crashed the interpreter at exit on CI's PySide6.
    """

    def __init__(
        self, window: QMainWindow, guide: QDockWidget, board: QDockWidget, state_version: int
    ) -> None:
        self._window = window
        self._guide = guide
        #: The views' group is the one the board stands in: the guide put in any other is a
        #: layout somebody chose, beside the board, and nothing steps aside for it.
        self._board = board
        self._version = state_version
        self._photo: QByteArray | None = None
        self._hidden: list[QDockWidget] = []
        self._fronts: list[QDockWidget] = []
        self._pending = False

    @property
    def active(self) -> bool:
        return self._photo is not None

    def follow(self, _visible: bool = True) -> None:
        """The guide's visibility changed: settle once the event loop comes round."""
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self.settle)

    def settle(self) -> None:
        self._pending = False
        guide = self._guide
        if guide.isVisible() and not guide.visibleRegion().isEmpty():
            self._enter()
        else:
            self._leave()

    def photograph(self) -> QByteArray:
        """The window's layout as somebody arranged it: the photograph while the panels are
        aside, the window as it is otherwise."""
        if self._photo is not None:
            return self._photo
        return self._window.saveState(self._version)

    def hand_over(self) -> QByteArray:
        """The photograph, for Home to put the window back from: assembly mode lets the
        panels go, and comes back when the guide is in front again."""
        photo = self.photograph()
        self._photo, self._hidden, self._fronts = None, [], []
        return photo

    def _enter(self) -> None:
        guide, window = self._guide, self._window
        if self.active or guide.isFloating():
            return
        group = [guide, *window.tabifiedDockWidgets(guide)]
        if self._board not in group:
            return
        others = [
            dock for dock in window.findChildren(QDockWidget)
            if dock not in group and not dock.isHidden() and not dock.isFloating()
        ]
        if not others:
            return
        self._photo = self._window.saveState(self._version)
        self._fronts = [dock for dock in others if not dock.visibleRegion().isEmpty()]
        self._hidden = others
        for dock in others:
            dock.hide()

    def _leave(self) -> None:
        if not self.active:
            return
        hidden, fronts = self._hidden, self._fronts
        self._photo, self._hidden, self._fronts = None, [], []
        for dock in hidden:
            dock.show()
        for dock in fronts:
            dock.raise_()
