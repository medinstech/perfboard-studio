"""The inspector: what the Properties panel shows for each kind of selection.

ONE EDITOR PER KIND, AND NO OK. A part's reference, value, package, where pin 1 sits, which
way it turns and what its leads are called were a modal dialog -- open it, change one thing,
press OK, see what happened -- and the board's name was another. Here each field is the
fact itself: it commits as ONE command when Enter is pressed or the field is left, Esc puts
back what the document says, and Undo is the cancel. A refusal is said under the field in
the bus's own words, never in a message box, and the field keeps what was typed so it can be
put right.

THE INSPECTOR HOLDS NO STATE. Every field is read back from the document the panel hands
over after every command (``refresh``), as the board and the sheet are redrawn -- so an undo,
an edit on the canvas or an agent's command shows here the moment it happens. The one
exception is a field somebody is typing in: it keeps what is typed until it is committed or
abandoned.

It never holds the window's bus, because the window replaces the bus when a file is opened:
it is handed a ``dispatch`` that goes through whichever bus the window has now, the footprint
lookup, and the few things that are not one command (``InspectorHooks``) -- choosing another
package and the board's own setup, which keep their dialogs for now.

The kinds without an editor yet are said in one line, as the panel's stand-in did.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio.command import DispatchResult
from perfboard_studio.commands import (
    LockComponentsPayload,
    MirrorComponentPayload,
    MoveComponentPayload,
    RenameDocumentPayload,
    RotateComponentPayload,
    SetBodyClearancePayload,
    SetHeightLimitPayload,
    UpdateComponentPayload,
    UpdateComponentsPayload,
)
from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.geometry import format_hole, parse_hole
from perfboard_studio.model import ComponentInstance, PerfDocument, Rotation

from . import theme
from .engine_text import say
from .i18n import t
from .partfields import PinoutEditor, note_editor, pinout_for_retyped_value
from .partnames import footprint_label
from .properties import describe
from .selection import NOTHING, Selection

#: Sends one command through the window's bus, whichever that is now.
Dispatch = Callable[[str, object], DispatchResult]


@dataclass(frozen=True, slots=True)
class InspectorHooks:
    """What the inspector asks the window for that is not one command."""

    #: Another package for a placed part: the library, in a dialog, for now.
    change_part: Callable[[str], object]
    #: The board's grid, type and material: its own dialog, because a new size can strand
    #: the parts on it.
    board_setup: Callable[[], object]


@dataclass(frozen=True, slots=True)
class InspectorActions:
    """The window's own actions the inspector puts buttons on, so a button, a menu entry
    and a key cannot disagree about what they do or when they can."""

    route_selected: QAction
    delete: QAction
    rotate: QAction
    mirror: QAction


# -- fields ---------------------------------------------------------------------------------


class _Problem(QLabel):
    """Why the field above was refused, in red; nothing while there is nothing to say."""

    def __init__(self) -> None:
        super().__init__()
        self.setWordWrap(True)
        theme.tone(self, "danger")
        self.hide()

    def show_problem(self, text: str) -> None:
        self.setText(text)
        self.setVisible(bool(text))


class CommitLine(QLineEdit):
    """A line that commits once: on Enter or on leaving it, and only if it changed.

    ``commit`` gets what was typed, stripped, and answers why it was refused or None. Esc
    puts back the document's value. While it holds a refused edit, a refresh does not
    overwrite it: what somebody typed is theirs to correct or abandon.
    """

    def __init__(self, commit: Callable[[str], str | None]) -> None:
        super().__init__()
        self._commit = commit
        self._shown = ""
        self.problem = _Problem()
        self.editingFinished.connect(self._finish)

    def show_value(self, value: str) -> None:
        self._shown = value
        if self.isModified():
            return
        if self.text() != value:
            self.setText(value)
        self.problem.show_problem("")

    def _finish(self) -> None:
        typed = self.text().strip()
        if typed == self._shown:
            self.setModified(False)
            self.problem.show_problem("")
            return
        # Not modified while the command runs, so the refresh it causes writes the
        # document's own spelling of what was typed back into the field.
        self.setModified(False)
        problem = self._commit(typed)
        if problem:
            self.setText(typed)
            self.setModified(True)
        self.problem.show_problem(problem or "")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and (self.isModified() or self.problem.isVisible()):
            self.setModified(False)
            self.setText(self._shown)
            self.problem.show_problem("")
            return
        super().keyPressEvent(event)


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(theme.SPACE["md"])
    form.setVerticalSpacing(theme.SPACE["sm"])
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    return form


def _add_field(form: QFormLayout, label: str, field: QWidget, problem: _Problem) -> None:
    """A field and, under it, the line that says why it was refused."""
    holder = QWidget()
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(2)
    column.addWidget(field)
    column.addWidget(problem)
    form.addRow(label, holder)


def _fact(text: str = "") -> QLabel:
    shown = QLabel(text)
    shown.setWordWrap(True)
    shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    theme.tone(shown, "secondary")
    return shown


def _action_button(action: QAction) -> QToolButton:
    button = QToolButton()
    button.setDefaultAction(action)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setAutoRaise(True)
    return button


# -- nothing selected: the board ----------------------------------------------------------


class _BoardEditor(QWidget):
    """The board itself: its name, what it is, and the two limits a case puts on it."""

    #: What each kind of board is called, in the words Board Setup offers it by: the part
    #: of its line before the dash.
    KINDS: ClassVar[dict[str, str]] = {
        "pad-per-hole": "Pad per hole — every hole is its own island",
        "stripboard": "Stripboard — whole rows joined; you cut the track to separate",
        "breadboard": "Breadboard — solderless; five holes to a clip, power on the rails",
        "solderable-breadboard": (
            "Solderable breadboard — the same holes and strips, in copper, soldered"
        ),
    }

    def __init__(self, inspector: Inspector) -> None:
        super().__init__()
        self._inspector = inspector
        self._document: PerfDocument | None = None
        self._loading = False
        form = _form()

        self.name = CommitLine(self._commit_name)
        self.name.setToolTip(
            t(
                "The board's title, printed on the build guide, on the schematic and on "
                "the project folder. A board is named after its file when first saved."
            )
        )
        _add_field(form, t("Name"), self.name, self.name.problem)

        board = QWidget()
        row = QHBoxLayout(board)
        row.setContentsMargins(0, 0, 0, 0)
        self.summary = _fact()
        self.change = QPushButton(t("Change…"))
        self.change.setToolTip(
            t(
                "Grid size and substrate. The material is not cosmetic: it decides the iron "
                "temperature the build guide gives and whether the pad-lifting rule applies."
            )
        )
        self.change.clicked.connect(lambda: inspector.hooks.board_setup())
        row.addWidget(self.summary, 1)
        row.addWidget(self.change, 0, Qt.AlignmentFlag.AlignTop)
        form.addRow(t("Board"), board)

        # 0 is "no limit", as in Board Features: with no case chosen there is no height
        # to be too tall for, and a spin box cannot be empty.
        self.height_limit = QDoubleSpinBox()
        self.height_limit.setRange(0.0, 200.0)
        self.height_limit.setSingleStep(1.0)
        self.height_limit.setDecimals(1)
        self.height_limit.setSpecialValueText(t("No limit"))
        self.height_limit.setSuffix(" mm")
        self.height_limit.setToolTip(
            t("Clear height inside the case, above the board. Taller parts are reported by DRC.")
        )
        self.height_problem = _Problem()
        self.height_limit.editingFinished.connect(self._commit_height)
        _add_field(form, t("Height limit"), self.height_limit, self.height_problem)

        # A box and a spin box, because 0 mm is a real clearance here.
        self.body_measure = QCheckBox(t("Measure between bodies"))
        self.body_measure.setToolTip(
            t(
                "Off, parts are kept apart by their courtyards (a half-pitch margin round "
                "each). On, by their real bodies plus this clearance — tighter, for a board "
                "where every hole counts."
            )
        )
        self.body_clearance = QDoubleSpinBox()
        self.body_clearance.setRange(0.0, 2.5)
        self.body_clearance.setSingleStep(0.1)
        self.body_clearance.setDecimals(2)
        self.body_clearance.setSuffix(" mm")
        self.body_clearance.setToolTip(
            t(
                "How far apart two parts' bodies must stand. A pin under another part's "
                "body is still in its way."
            )
        )
        self.clearance_problem = _Problem()
        self.body_measure.toggled.connect(self._commit_clearance)
        self.body_clearance.editingFinished.connect(self._commit_clearance)
        form.addRow("", self.body_measure)
        _add_field(form, t("Body clearance"), self.body_clearance, self.clearance_problem)

        self.setLayout(form)

    def load(self, document: PerfDocument) -> None:
        self._document = document
        self._loading = True
        try:
            self.name.show_value(document.meta.name)
            board = document.board
            kind = self.KINDS.get(board.type)
            words = [t(kind).split(" — ")[0]] if kind is not None else []
            words.append(t("{cols} × {rows} holes").format(cols=board.cols, rows=board.rows))
            self.summary.setText(",  ".join(words))
            if not self.height_limit.hasFocus():
                self.height_limit.setValue(document.height_limit_mm or 0.0)
            clearance = document.body_clearance_mm
            self.body_measure.setChecked(clearance is not None)
            self.body_clearance.setEnabled(clearance is not None)
            if clearance is not None and not self.body_clearance.hasFocus():
                self.body_clearance.setValue(clearance)
        finally:
            self._loading = False

    def _commit_name(self, typed: str) -> str | None:
        if not typed:
            return None
        return self._inspector.dispatch("document.rename", RenameDocumentPayload(name=typed))

    def _commit_height(self) -> None:
        document = self._document
        if self._loading or document is None:
            return
        value = self.height_limit.value()
        wanted = None if value <= 0 else value
        if wanted == document.height_limit_mm:
            return
        self.height_problem.show_problem(
            self._inspector.dispatch(
                "height-limit.set", SetHeightLimitPayload(height_limit_mm=wanted)
            )
            or ""
        )

    def _commit_clearance(self) -> None:
        document = self._document
        if self._loading or document is None:
            return
        measured = self.body_measure.isChecked()
        self.body_clearance.setEnabled(measured)
        wanted = self.body_clearance.value() if measured else None
        if wanted == document.body_clearance_mm:
            return
        self.clearance_problem.show_problem(
            self._inspector.dispatch(
                "body-clearance.set", SetBodyClearancePayload(body_clearance_mm=wanted)
            )
            or ""
        )


# -- one part on the board ------------------------------------------------------------------


class _PartEditor(QWidget):
    """One placed part: what it is called, what it is, where it sits, what its leads are
    called and why it is there. Replaces Part Properties and Rename Part."""

    ROTATIONS: tuple[Rotation, ...] = (0, 90, 180, 270)

    def __init__(self, inspector: Inspector, actions: InspectorActions) -> None:
        super().__init__()
        self._inspector = inspector
        self._component: ComponentInstance | None = None
        self._document: PerfDocument | None = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])

        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.title)

        form = _form()
        self.ref = CommitLine(self._commit_ref)
        self.ref.setPlaceholderText("R1, C3, U2…")
        self.ref.setToolTip(
            t(
                "The designator the schematic uses. Every net this part is wired into "
                "follows the new name, so a rename is safe at any point."
            )
        )
        _add_field(form, t("Reference"), self.ref, self.ref.problem)
        self.value = CommitLine(self._commit_value)
        self.value.setPlaceholderText("10k, 100nF, NE555…")
        self.value.setToolTip(
            t(
                "What the part actually is. This is the column the build guide's bill of "
                "materials groups on, so a blank one becomes a line you cannot order."
            )
        )
        _add_field(form, t("Value"), self.value, self.value.problem)

        # The package, and Change beside it: another package or another part on the same
        # holes and the same nets. Greyed on a locked part, with the reason under it.
        package = QWidget()
        package_column = QVBoxLayout(package)
        package_column.setContentsMargins(0, 0, 0, 0)
        package_column.setSpacing(2)
        package_row = QHBoxLayout()
        package_row.setContentsMargins(0, 0, 0, 0)
        self.package = _fact()
        self.change_part = QPushButton(t("Change…"))
        self.change_part.setToolTip(
            t("Another package or another part from the library, on the same holes and the "
              "same nets.")
        )
        self.change_part.clicked.connect(self._on_change_part)
        package_row.addWidget(self.package, 1)
        package_row.addWidget(self.change_part, 0, Qt.AlignmentFlag.AlignTop)
        package_column.addLayout(package_row)
        self.locked_note = QLabel(t("Locked: a new package would move its pins. Unlock it first."))
        self.locked_note.setWordWrap(True)
        theme.tone(self.locked_note, "warning")
        package_column.addWidget(self.locked_note)
        form.addRow(t("Package"), package)

        self.pin1 = CommitLine(self._commit_pin1)
        self.pin1.setToolTip(t("The hole pin 1 is in. Type another to move the part there."))
        _add_field(form, t("Pin 1 at"), self.pin1, self.pin1.problem)

        turns = QWidget()
        turn_row = QHBoxLayout(turns)
        turn_row.setContentsMargins(0, 0, 0, 0)
        turn_row.setSpacing(2)
        self.rotation = QButtonGroup(self)
        self.rotation.setExclusive(True)
        for degrees in self.ROTATIONS:
            button = QToolButton()
            button.setText(f"{degrees}°")
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.rotation.addButton(button, degrees)
            turn_row.addWidget(button)
        self.rotation_problem = _Problem()
        self.rotation.idClicked.connect(self._commit_rotation)
        _add_field(form, t("Rotation"), turns, self.rotation_problem)

        self.mirrored = QCheckBox(t("Mirrored"))
        self.mirrored.toggled.connect(self._commit_mirrored)
        self.locked = QCheckBox(t("locked — Rearrange leaves it where it is"))
        self.locked.toggled.connect(self._commit_locked)
        self.flags_problem = _Problem()
        flags = QWidget()
        flag_column = QVBoxLayout(flags)
        flag_column.setContentsMargins(0, 0, 0, 0)
        flag_column.setSpacing(2)
        flag_column.addWidget(self.mirrored)
        flag_column.addWidget(self.locked)
        flag_column.addWidget(self.flags_problem)
        form.addRow("", flags)

        self.facts = _fact()
        form.addRow(t("Height"), self.facts)
        layout.addLayout(form)

        # What its leads are called and what it is, when its package cannot say: committed
        # as they are changed, each change one step.
        self.pinout = PinoutEditor()
        self.pinout.symbol.currentIndexChanged.connect(self._commit_pinout)
        self.pinout.table.itemChanged.connect(self._commit_pinout)
        self.pinout_problem = _Problem()
        layout.addWidget(self.pinout)
        layout.addWidget(self.pinout_problem)

        notes = _form()
        self.note = note_editor("")
        self.note.installEventFilter(self)
        self.note_problem = _Problem()
        _add_field(notes, t("Note"), self.note, self.note_problem)
        layout.addLayout(notes)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(_action_button(actions.route_selected))
        buttons.addStretch(1)
        buttons.addWidget(_action_button(actions.delete))
        layout.addLayout(buttons)

    # -- reading the document --

    def load(self, document: PerfDocument, component: ComponentInstance) -> None:
        another = self._component is None or self._component.id != component.id
        self._document = document
        self._component = component
        footprint = self._inspector.lookup(component.footprint_id)
        self._loading = True
        try:
            self.title.setText(theme.heading(component.ref))
            self.ref.show_value(component.ref)
            self.value.show_value(component.value)
            name = footprint_label(footprint.name) if footprint is not None else component.footprint_id
            self.package.setText(f"{name}  ({component.footprint_id})")
            self.change_part.setEnabled(not component.locked)
            self.locked_note.setVisible(component.locked)
            self.pin1.show_value(format_hole(component.anchor, document.board))
            button = self.rotation.button(component.rotation)
            if button is not None:
                button.setChecked(True)
            self.mirrored.setChecked(component.mirrored)
            self.locked.setChecked(component.locked)
            self.facts.setText(
                f"{footprint.body_height:.1f} mm" if footprint is not None else "?"
            )
            if another:
                self.pinout.say("")
                for problem in (self.rotation_problem, self.flags_problem, self.pinout_problem,
                                self.note_problem):
                    problem.show_problem("")
            editing_names = self.pinout.table.hasFocus() or self.pinout.symbol.hasFocus()
            if another or not editing_names:
                self.pinout.set_part(footprint, component.pin_names, component.symbol)
            if not self.note.hasFocus() or another:
                self.note.setPlainText(component.note)
        finally:
            self._loading = False

    # -- committing --

    def _update(self, payload: UpdateComponentPayload) -> str | None:
        return self._inspector.dispatch("component.update", payload)

    def _commit_ref(self, typed: str) -> str | None:
        component = self._component
        if component is None:
            return None
        if not typed:
            return t("Every part is identified by its reference, so it cannot be blank.")
        return self._update(UpdateComponentPayload(id=component.id, ref=typed))

    def _commit_value(self, typed: str) -> str | None:
        """The value, and the pinout a value brings, in ONE step: BC547 typed over 2N3904
        on a TO-92 is the same transistor soldered the other way round otherwise."""
        component = self._component
        if component is None:
            return None
        footprint = self._inspector.lookup(component.footprint_id)
        self._loading = True
        try:
            self.pinout.follow_value(footprint, component.value, typed)
        finally:
            self._loading = False
        names, symbol = self.pinout.values()
        payload = UpdateComponentPayload(id=component.id, value=typed)
        if names != component.pin_names:
            payload = dataclasses.replace(payload, pin_names=names)
        if symbol != component.symbol:
            payload = dataclasses.replace(payload, symbol=symbol)
        return self._update(payload)

    def _commit_pin1(self, typed: str) -> str | None:
        component, document = self._component, self._document
        if component is None or document is None:
            return None
        try:
            hole = parse_hole(typed, document.board)
        except ValueError:
            return t("{hole} is not a hole on this board.").format(hole=typed)
        if hole == component.anchor:
            return None
        return self._inspector.dispatch(
            "component.move", MoveComponentPayload(id=component.id, anchor=hole)
        )

    def _commit_rotation(self, degrees: int) -> None:
        component = self._component
        if self._loading or component is None or degrees == component.rotation:
            return
        rotation: Rotation = 90 if degrees == 90 else 180 if degrees == 180 else 270 if degrees == 270 else 0
        problem = self._inspector.dispatch(
            "component.rotate", RotateComponentPayload(id=component.id, rotation=rotation)
        )
        self.rotation_problem.show_problem(problem or "")
        if problem:
            self._put_back()

    def _commit_mirrored(self, mirrored: bool) -> None:
        component = self._component
        if self._loading or component is None or mirrored == component.mirrored:
            return
        problem = self._inspector.dispatch(
            "component.mirror", MirrorComponentPayload(id=component.id, mirrored=mirrored)
        )
        self.flags_problem.show_problem(problem or "")
        if problem:
            self._put_back()

    def _commit_locked(self, locked: bool) -> None:
        component = self._component
        if self._loading or component is None or locked == component.locked:
            return
        problem = self._update(UpdateComponentPayload(id=component.id, locked=locked))
        self.flags_problem.show_problem(problem or "")
        if problem:
            self._put_back()

    def _commit_pinout(self, *_args: object) -> None:
        component = self._component
        if self._loading or component is None:
            return
        names, symbol = self.pinout.values()
        if (names, symbol) == (component.pin_names, component.symbol):
            return
        payload = UpdateComponentPayload(id=component.id)
        if names != component.pin_names:
            payload = dataclasses.replace(payload, pin_names=names)
        if symbol != component.symbol:
            payload = dataclasses.replace(payload, symbol=symbol)
        self.pinout_problem.show_problem(self._update(payload) or "")

    def _commit_note(self) -> None:
        component = self._component
        if self._loading or component is None:
            return
        typed = self.note.toPlainText().strip()
        if typed == component.note:
            return
        problem = self._update(UpdateComponentPayload(id=component.id, note=typed))
        self.note_problem.show_problem(problem or "")

    def _put_back(self) -> None:
        """A refused toggle shows the document's state again, not the one refused."""
        if self._document is not None and self._component is not None:
            self.load(self._document, self._component)

    def _on_change_part(self) -> None:
        if self._component is not None:
            self._inspector.hooks.change_part(self._component.id)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.note and event.type() == QEvent.Type.FocusOut:
            self._commit_note()
        return super().eventFilter(watched, event)


# -- several parts on the board --------------------------------------------------------------


class _PartsEditor(QWidget):
    """Several placed parts: one value typed once for all of them -- five resistors placed,
    then "10k" -- their lock, and what turns or removes them together. Each is ONE command
    (``component.updateMany``, ``component.lockMany`` and the window's own group Rotate,
    Mirror and Delete), so one undo step puts the whole edit back."""

    def __init__(self, inspector: Inspector, actions: InspectorActions) -> None:
        super().__init__()
        self._inspector = inspector
        self._components: tuple[ComponentInstance, ...] = ()
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.refs = _fact()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(self.title)
        heading.addWidget(self.refs)
        layout.addLayout(heading)

        form = _form()
        self.value = CommitLine(self._commit_value)
        self.value.setToolTip(
            t("Typed once, given to every part selected, as one step to undo.")
        )
        _add_field(form, t("Value"), self.value, self.value.problem)
        self.package = _fact()
        form.addRow(t("Package"), self.package)
        self._form = form
        # Three states: all locked, none, or some -- and a click locks them all, or, when
        # they all are, unlocks them all, which is what "lock these" means.
        self.locked = QCheckBox(t("locked — Rearrange leaves it where it is"))
        self.locked.setTristate(True)
        self.locked.clicked.connect(self._commit_locked)
        self.locked_problem = _Problem()
        flags = QWidget()
        flag_column = QVBoxLayout(flags)
        flag_column.setContentsMargins(0, 0, 0, 0)
        flag_column.setSpacing(2)
        flag_column.addWidget(self.locked)
        flag_column.addWidget(self.locked_problem)
        form.addRow("", flags)
        layout.addLayout(form)

        turns = QHBoxLayout()
        turns.setContentsMargins(0, 0, 0, 0)
        turns.addWidget(_action_button(actions.rotate))
        turns.addWidget(_action_button(actions.mirror))
        turns.addStretch(1)
        layout.addLayout(turns)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(_action_button(actions.route_selected))
        buttons.addStretch(1)
        buttons.addWidget(_action_button(actions.delete))
        layout.addLayout(buttons)

    def load(self, document: PerfDocument, components: tuple[ComponentInstance, ...]) -> None:
        another = {c.id for c in components} != {c.id for c in self._components}
        self._components = components
        self._loading = True
        try:
            self.title.setText(theme.heading(t("{count} selected").format(count=len(components))))
            self.refs.setText(", ".join(c.ref for c in components))
            values = {c.value for c in components}
            # "Mixed" where the values differ: typing sets all of them.
            self.value.setPlaceholderText(t("Mixed") if len(values) > 1 else "")
            self.value.show_value(next(iter(values)) if len(values) == 1 else "")
            if another and not self.value.isModified():
                self.value.problem.show_problem("")
            footprints = {c.footprint_id for c in components}
            footprint = (
                self._inspector.lookup(next(iter(footprints))) if len(footprints) == 1 else None
            )
            self.package.setText(
                f"{footprint_label(footprint.name)}  ({footprint.id})" if footprint else ""
            )
            self._form.setRowVisible(self.package, footprint is not None)
            locked = [c.locked for c in components]
            self.locked.setCheckState(
                Qt.CheckState.Checked
                if all(locked)
                else Qt.CheckState.Unchecked
                if not any(locked)
                else Qt.CheckState.PartiallyChecked
            )
            if another:
                self.locked_problem.show_problem("")
        finally:
            self._loading = False

    def _commit_value(self, typed: str) -> str | None:
        """One value for every part, and each part the pinout that value brings to ITS
        package, as typing it on that part alone would."""
        if not self._components or not typed:
            return None
        updates = []
        for component in self._components:
            update = UpdateComponentPayload(id=component.id, value=typed)
            part = pinout_for_retyped_value(
                component.footprint_id, component.value, typed, dict(component.pin_names)
            )
            if part is not None:
                if part.pin_names != component.pin_names:
                    update = dataclasses.replace(update, pin_names=part.pin_names)
                if part.symbol != component.symbol:
                    update = dataclasses.replace(update, symbol=part.symbol)
            updates.append(update)
        return self._inspector.dispatch(
            "component.updateMany", UpdateComponentsPayload(updates=tuple(updates))
        )

    def _commit_locked(self) -> None:
        if self._loading or not self._components:
            return
        locking = not all(c.locked for c in self._components)
        problem = self._inspector.dispatch(
            "component.lockMany",
            LockComponentsPayload(ids=tuple(c.id for c in self._components), locked=locking),
        )
        self.locked_problem.show_problem(problem or "")


# -- the part about to be placed --------------------------------------------------------------


class _PlacingEditor(QWidget):
    """A library part armed for placing: what it is, and the value each part placed from it
    gets. Typed once and kept, because a board is placed in runs -- five 10k resistors, then
    three 100nF -- and it is typed where every other value is. It was a field of its own
    under the library's filter, the most misread control in the window: it looked like a
    second search box. Not a command: it is the value the NEXT part is placed with."""

    def __init__(self, inspector: Inspector) -> None:
        super().__init__()
        self._inspector = inspector
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.line = _fact(t("Click the board where pin 1 goes. Esc cancels."))
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(self.title)
        heading.addWidget(self.line)
        layout.addLayout(heading)
        form = _form()
        self.value = QLineEdit()
        self.value.setPlaceholderText("10k, 100nF, NE555…")
        self.value.setClearButtonEnabled(True)
        self.value.setToolTip(
            t(
                "Given to each part as it is placed. Leave it blank and the part is placed "
                "without one; F2 sets it afterwards either way."
            )
        )
        form.addRow(t("Value"), self.value)
        layout.addLayout(form)

    def load(self, footprint_id: str) -> None:
        footprint = self._inspector.lookup(footprint_id)
        name = footprint_label(footprint.name) if footprint is not None else footprint_id
        self.title.setText(theme.heading(name))


# -- everything else, said in one line until it has an editor ----------------------------


class _Summary(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.line = _fact()
        layout.addWidget(self.title)
        layout.addWidget(self.line)

    def load(self, selection: Selection, document: PerfDocument) -> None:
        title, line = describe(selection, document)
        self.title.setText(theme.heading(title))
        self.line.setText(line)


# -- the inspector ----------------------------------------------------------------------------


class Inspector(QWidget):
    """The editors, one shown at a time, for whatever the panel says is selected."""

    def __init__(
        self,
        dispatch: Dispatch,
        lookup: FootprintLookup,
        hooks: InspectorHooks,
        actions: InspectorActions,
    ) -> None:
        super().__init__()
        self._dispatch = dispatch
        self.lookup = lookup
        self.hooks = hooks
        self._document: PerfDocument | None = None
        self.selection = NOTHING
        self.board_editor = _BoardEditor(self)
        self.part_editor = _PartEditor(self, actions)
        self.parts_editor = _PartsEditor(self, actions)
        self.placing_editor = _PlacingEditor(self)
        self.summary = _Summary()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # Stacked by hand rather than in a QStackedWidget, which is as tall as its tallest
        # page: the board's three fields would sit over the part editor's empty height.
        self._pages: tuple[QWidget, ...] = (
            self.board_editor, self.part_editor, self.parts_editor, self.placing_editor,
            self.summary,
        )
        for page in self._pages:
            layout.addWidget(page)
            page.hide()
        layout.addStretch(1)
        self.shown: QWidget = self.summary

    def dispatch(self, name: str, payload: object) -> str | None:
        """One command; why it was refused, in the window's language, or None."""
        result = self._dispatch(name, payload)
        return None if result.ok else say(result.message)

    def set_selection(self, selection: Selection) -> None:
        self.selection = selection
        self._show()

    def refresh(self, document: PerfDocument) -> None:
        self._document = document
        self._show()

    def _show(self) -> None:
        document = self._document
        if document is None:
            return
        selection = self.selection
        page: QWidget = self.summary
        if selection.kind == "board":
            self.board_editor.load(document)
            page = self.board_editor
        elif selection.kind == "part" and selection.ids:
            component = next((c for c in document.components if c.id == selection.ids[0]), None)
            if component is not None:
                self.part_editor.load(document, component)
                page = self.part_editor
        elif selection.kind == "parts":
            chosen = set(selection.ids)
            components = tuple(c for c in document.components if c.id in chosen)
            if len(components) > 1:
                self.parts_editor.load(document, components)
                page = self.parts_editor
        elif selection.kind == "placing" and selection.ids:
            self.placing_editor.load(selection.ids[0])
            page = self.placing_editor
        if page is self.summary:
            self.summary.load(selection, document)
        if page is not self.shown:
            self.shown.hide()
            page.show()
            self.shown = page

    def focus_field(self, name: str) -> bool:
        """Put the keyboard in one field of the editor showing, its text selected: F2 is
        the part's Reference, a double-click its Value, Rename Board the board's Name.
        False when the editor showing has no such field."""
        fields: dict[str, QLineEdit] = {}
        if self.shown is self.part_editor:
            fields = {"ref": self.part_editor.ref, "value": self.part_editor.value}
        elif self.shown is self.parts_editor:
            fields = {"value": self.parts_editor.value}
        elif self.shown is self.placing_editor:
            fields = {"value": self.placing_editor.value}
        elif self.shown is self.board_editor:
            fields = {"name": self.board_editor.name}
        field = fields.get(name)
        if field is None:
            return False
        field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        field.selectAll()
        return True
