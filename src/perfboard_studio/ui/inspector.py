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
from typing import Literal

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
    NewConductor,
    NewSolderTraceConductor,
    NewWireConductor,
    RenameDocumentPayload,
    ReplaceConductorsPayload,
    RotateComponentPayload,
    SetBodyClearancePayload,
    SetHeightLimitPayload,
    UpdateBoardNotePayload,
    UpdateComponentPayload,
    UpdateComponentsPayload,
    UpdateNetPayload,
    UpdatePartPayload,
    UpdateSheetNotePayload,
    wire_side,
)
from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.footprints import SUPERSEDED_FOOTPRINTS
from perfboard_studio.geometry import format_hole, parse_hole
from perfboard_studio.guide import CABLED_MODULE, plugs_in_on_a_cable
from perfboard_studio.model import (
    UNTITLED_NAME,
    BoardNote,
    BoardSide,
    ComponentInstance,
    Conductor,
    Net,
    NetClass,
    PerfDocument,
    Rotation,
    SchematicPart,
    SheetNote,
)
from perfboard_studio.parsers.kicad import infer_net_class
from perfboard_studio.phrasebook import guide_language, phrasebook

from . import theme
from .boardfeatures import FeatureEditor, FeaturesGroup
from .engine_text import say
from .i18n import language, t
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
    design_board: Callable[[], object]
    #: Another package for a part still only in the design: the library, in a dialog.
    change_design_part: Callable[[str], object]


@dataclass(frozen=True, slots=True)
class InspectorActions:
    """The window's own actions the inspector puts buttons on, so a button, a menu entry
    and a key cannot disagree about what they do or when they can."""

    route_selected: QAction
    delete: QAction
    rotate: QAction
    mirror: QAction
    add_pins: QAction
    delete_net: QAction
    place_design: QAction
    remove_design: QAction


#: A net's classes: the value, the label a form shows with the reason attached, and the
#: accelerated one a menu shows. ONE table for the net editor and the sheet's Net Class
#: menu: a class only one of them knew would be one you could set and never see, or reach
#: without being told what it costs.
NET_CLASSES: tuple[tuple[NetClass, str, str], ...] = (
    ("signal", "Signal", "&Signal"),
    ("ground", "Ground — wired first, and wants a rail", "&Ground"),
    ("power", "Power — wired after ground, same reason", "&Power"),
)


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


def _narrow(combo: QComboBox) -> None:
    """A combo as wide as the panel lets it be, not as wide as its longest entry: "Potentiometer
    (three leads, the middle one the wiper)" made every part's editor wider than the panel."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(8)


def _action_button(action: QAction) -> QToolButton:
    button = QToolButton()
    button.setDefaultAction(action)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setAutoRaise(True)
    return button


# -- nothing selected: the board ----------------------------------------------------------


class _BoardEditor(QWidget):
    """The board itself: its name, what it is, and the two limits a case puts on it."""

    @staticmethod
    def kind_name(kind: str) -> str | None:
        """What a kind of board is called, in the words the board designer says it in.

        Literals in ``t()``, where Board Setup's table of whole lines used to be read: that
        table retired with it, and the catalogue scan took the four lines for unused --
        and the Turkish window said the board's kind in English.
        """
        return {
            "pad-per-hole": t("Pad per hole"),
            "stripboard": t("Stripboard"),
            "breadboard": t("Solderless breadboard"),
            "solderable-breadboard": t("Solderable breadboard"),
        }.get(kind)

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
        # A board nobody has named is stored as "untitled", which is data and stays
        # English; the field shows it empty with the word in the window's language, as the
        # header says it. In a Turkish window the header said "adsız" and this "untitled".
        self.name.setPlaceholderText(t("untitled"))
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
        self.change.clicked.connect(lambda: inspector.hooks.design_board())
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
        form.addRow(self.body_measure)  # the whole row: in the field column it was too wide
        _add_field(form, t("Body clearance"), self.body_clearance, self.clearance_problem)

        # What the board has besides its grid, where Board Features was a dialog
        # (``ui/boardfeatures.py``): its holes and connectors, Remove, and adding them.
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACE["xl"])
        column.addLayout(form)
        self.features = FeaturesGroup(inspector.dispatch)
        column.addWidget(self.features)

    def load(self, document: PerfDocument) -> None:
        self._document = document
        self._loading = True
        try:
            named = document.meta.name
            self.name.show_value("" if named == UNTITLED_NAME else named)
            board = document.board
            kind = self.kind_name(board.type)
            words = [kind] if kind is not None else []
            words.append(t("{cols} × {rows} holes").format(cols=board.cols, rows=board.rows))
            self.summary.setText(",  ".join(words))
            if not self.height_limit.hasFocus():
                self.height_limit.setValue(document.height_limit_mm or 0.0)
            clearance = document.body_clearance_mm
            self.body_measure.setChecked(clearance is not None)
            self.body_clearance.setEnabled(clearance is not None)
            if clearance is not None and not self.body_clearance.hasFocus():
                self.body_clearance.setValue(clearance)
            self.features.load(document)
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
        # A package the catalog has replaced (``footprints.SUPERSEDED_FOOTPRINTS``): said
        # here, and one press from the current one -- the same pins on the same holes, the
        # body where the real part's is. DRC says it too (``superseded-footprint``).
        self.older = QWidget()
        older_row = QHBoxLayout(self.older)
        older_row.setContentsMargins(0, 0, 0, 0)
        self.older_note = QLabel(t("An older package of this part."))
        self.older_note.setWordWrap(True)
        theme.tone(self.older_note, "warning")
        self.use_current = QPushButton(t("Use the Current Package"))
        self.use_current.setAutoDefault(False)
        self.use_current.clicked.connect(self._on_use_current)
        older_row.addWidget(self.older_note, 1)
        older_row.addWidget(self.use_current, 0, Qt.AlignmentFlag.AlignTop)
        package_column.addWidget(self.older)
        self.older_problem = _Problem()
        package_column.addWidget(self.older_problem)
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
        self.locked = QCheckBox(t("Locked"))
        self.locked.setToolTip(t("locked — Rearrange leaves it where it is"))
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

        # A header something plugs into on its cable says so, in the build guide's words
        # (``guide.CABLED_MODULE``): the module is not on the board, and the names below
        # are its leads.
        self.cabled = QLabel()
        self.cabled.setWordWrap(True)
        theme.tone(self.cabled, "secondary")
        self.cabled.hide()
        layout.addWidget(self.cabled)

        # What its leads are called and what it is, when its package cannot say: committed
        # as they are changed, each change one step.
        self.pinout = PinoutEditor()
        _narrow(self.pinout.symbol)
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

    def _on_use_current(self) -> None:
        component = self._component
        superseded = SUPERSEDED_FOOTPRINTS.get(component.footprint_id) if component else None
        if component is None or superseded is None:
            return
        self.older_problem.show_problem(
            self._inspector.dispatch(
                "component.update",
                UpdateComponentPayload(id=component.id, footprint_id=superseded[0]),
            )
            or ""
        )

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
            superseded = SUPERSEDED_FOOTPRINTS.get(component.footprint_id)
            self.older.setVisible(superseded is not None)
            self.use_current.setEnabled(not component.locked)
            if superseded is not None:
                # Why, in the engine's words: what was wrong with the package it is on.
                self.older_note.setToolTip(say(superseded[1]))
            if another:
                self.older_problem.show_problem("")
            self.pin1.show_value(format_hole(component.anchor, document.board))
            button = self.rotation.button(component.rotation)
            if button is not None:
                button.setChecked(True)
            self.mirrored.setChecked(component.mirrored)
            self.locked.setChecked(component.locked)
            self.facts.setText(
                f"{footprint.body_height:.1f} mm" if footprint is not None else "?"
            )
            cabled = footprint is not None and plugs_in_on_a_cable(component, footprint)
            self.cabled.setVisible(cabled)
            if cabled:
                say_it = phrasebook(guide_language(language()))
                self.cabled.setText(say_it(CABLED_MODULE, module=component.value.strip()))
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
        problem = self._inspector.dispatch(
            "component.rotate",
            RotateComponentPayload(id=component.id, rotation=_rotation(degrees)),
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


# -- one part still only in the design ------------------------------------------------------


class _DesignPartEditor(QWidget):
    """A part drawn on the sheet and not on the board yet: the same reference, value,
    package, pin names and note as a placed part, through ``part.update``, and where a
    placed part has its hole, "not on the board yet" and Place on the Board. Replaces the
    sheet's Edit a Part and Rename; Change... beside the package is the library still."""

    def __init__(self, inspector: Inspector, actions: InspectorActions) -> None:
        super().__init__()
        self._inspector = inspector
        self._part: SchematicPart | None = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.where = _fact(t("In the design, not on the board yet."))
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(self.title)
        heading.addWidget(self.where)
        layout.addLayout(heading)

        form = _form()
        self.ref = CommitLine(self._commit_ref)
        self.ref.setPlaceholderText("R1, C3, U2…")
        _add_field(form, t("Reference"), self.ref, self.ref.problem)
        self.value = CommitLine(self._commit_value)
        self.value.setPlaceholderText("10k, 100nF, NE555…")
        _add_field(form, t("Value"), self.value, self.value.problem)
        package = QWidget()
        package_row = QHBoxLayout(package)
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
        form.addRow(t("Package"), package)
        layout.addLayout(form)

        self.pinout = PinoutEditor()
        _narrow(self.pinout.symbol)
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
        buttons.addWidget(_action_button(actions.place_design))
        buttons.addStretch(1)
        buttons.addWidget(_action_button(actions.remove_design))
        layout.addLayout(buttons)

    def load(self, part: SchematicPart) -> None:
        another = self._part is None or self._part.id != part.id
        self._part = part
        footprint = self._inspector.lookup(part.footprint_id)
        self._loading = True
        try:
            self.title.setText(theme.heading(part.ref))
            self.ref.show_value(part.ref)
            self.value.show_value(part.value)
            name = footprint_label(footprint.name) if footprint is not None else part.footprint_id
            self.package.setText(f"{name}  ({part.footprint_id})")
            if another:
                self.pinout.say("")
                for problem in (self.pinout_problem, self.note_problem):
                    problem.show_problem("")
            editing_names = self.pinout.table.hasFocus() or self.pinout.symbol.hasFocus()
            if another or not editing_names:
                self.pinout.set_part(footprint, part.pin_names, part.symbol)
            if another or not self.note.hasFocus():
                self.note.setPlainText(part.note)
        finally:
            self._loading = False

    def _update(self, payload: UpdatePartPayload) -> str | None:
        return self._inspector.dispatch("part.update", payload)

    def _commit_ref(self, typed: str) -> str | None:
        part = self._part
        if part is None:
            return None
        if not typed:
            return t("Every part is identified by its reference, so it cannot be blank.")
        return self._update(UpdatePartPayload(id=part.id, ref=typed))

    def _commit_value(self, typed: str) -> str | None:
        """The value and the pinout it brings, in one step, as on a placed part."""
        part = self._part
        if part is None:
            return None
        footprint = self._inspector.lookup(part.footprint_id)
        self._loading = True
        try:
            self.pinout.follow_value(footprint, part.value, typed)
        finally:
            self._loading = False
        names, symbol = self.pinout.values()
        payload = UpdatePartPayload(id=part.id, value=typed)
        if names != part.pin_names:
            payload = dataclasses.replace(payload, pin_names=names)
        if symbol != part.symbol:
            payload = dataclasses.replace(payload, symbol=symbol)
        return self._update(payload)

    def _commit_pinout(self, *_args: object) -> None:
        part = self._part
        if self._loading or part is None:
            return
        names, symbol = self.pinout.values()
        if (names, symbol) == (part.pin_names, part.symbol):
            return
        payload = UpdatePartPayload(id=part.id)
        if names != part.pin_names:
            payload = dataclasses.replace(payload, pin_names=names)
        if symbol != part.symbol:
            payload = dataclasses.replace(payload, symbol=symbol)
        self.pinout_problem.show_problem(self._update(payload) or "")

    def _commit_note(self) -> None:
        part = self._part
        if self._loading or part is None:
            return
        typed = self.note.toPlainText().strip()
        if typed == part.note:
            return
        self.note_problem.show_problem(
            self._update(UpdatePartPayload(id=part.id, note=typed)) or ""
        )

    def _on_change_part(self) -> None:
        if self._part is not None:
            self._inspector.hooks.change_design_part(self._part.id)

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
        self.locked = QCheckBox(t("Locked"))
        self.locked.setToolTip(t("locked — Rearrange leaves it where it is"))
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


# -- a net ---------------------------------------------------------------------------------------


class _NetEditor(QWidget):
    """One net: its name, its class, and what it carries -- the only place a board can be
    told it is carrying two amps, which wakes DRC's current-capacity rule and picks the
    wire gauge on the build guide's cut list. Replaces NetDialog and Rename Net."""

    def __init__(self, inspector: Inspector, actions: InspectorActions) -> None:
        super().__init__()
        self._inspector = inspector
        self._net: Net | None = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.title)

        form = _form()
        self.name = CommitLine(self._commit_name)
        self.name.setPlaceholderText("GND, +5V, OUT…")
        _add_field(form, t("Name"), self.name, self.name.problem)

        classes = QWidget()
        class_row = QHBoxLayout(classes)
        class_row.setContentsMargins(0, 0, 0, 0)
        class_row.setSpacing(2)
        self.net_class = QButtonGroup(self)
        self.net_class.setExclusive(True)
        self._class_buttons: dict[NetClass, QToolButton] = {}
        for value, description, label in NET_CLASSES:
            button = QToolButton()
            button.setText(t(label).replace("&", ""))
            button.setToolTip(t(description))
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, v=value: self._commit_class(v))
            self.net_class.addButton(button)
            self._class_buttons[value] = button
            class_row.addWidget(button)
        self.class_problem = _Problem()
        _add_field(form, t("Class"), classes, self.class_problem)

        # Blank is "not stated", which is a different thing from zero.
        self.current = QDoubleSpinBox()
        self.current.setRange(0.0, 100.0)
        self.current.setDecimals(2)
        self.current.setSingleStep(0.1)
        self.current.setSuffix(" A")
        self.current.setSpecialValueText(t("not stated"))
        self.current.setToolTip(
            t(
                "Wakes DRC's current-capacity rule and picks the wire gauge on the build "
                "guide's cut list. Nothing else in the application can set it."
            )
        )
        self.current.editingFinished.connect(self._commit_current)
        self.current_problem = _Problem()
        _add_field(form, t("Current"), self.current, self.current_problem)

        # A -12 V rail is an ordinary value, which is why a voltage needs its own tick.
        voltage = QWidget()
        voltage_row = QHBoxLayout(voltage)
        voltage_row.setContentsMargins(0, 0, 0, 0)
        self.voltage_stated = QCheckBox(t("state a voltage"))
        self.voltage = QDoubleSpinBox()
        self.voltage.setRange(-1000.0, 1000.0)
        self.voltage.setDecimals(1)
        self.voltage.setSuffix(" V")
        self.voltage.setToolTip(
            t(
                "Wakes DRC's creepage rule above the mains threshold. A -12 V rail is an "
                "ordinary value here, which is why it needs its own tick rather than a zero."
            )
        )
        self.voltage_stated.toggled.connect(self._commit_voltage)
        self.voltage.editingFinished.connect(self._commit_voltage)
        voltage_row.addWidget(self.voltage_stated)
        voltage_row.addWidget(self.voltage, 1)
        self.voltage_problem = _Problem()
        _add_field(form, t("Voltage"), voltage, self.voltage_problem)

        self.pins = _fact()
        form.addRow(t("Pins"), self.pins)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(_action_button(actions.add_pins))
        buttons.addStretch(1)
        buttons.addWidget(_action_button(actions.delete_net))
        layout.addLayout(buttons)

    def load(self, document: PerfDocument, net: Net) -> None:
        another = self._net is None or self._net.id != net.id
        self._net = net
        self._loading = True
        try:
            self.title.setText(theme.heading(net.name))
            self.name.show_value(net.name)
            self._class_buttons[net.net_class].setChecked(True)
            if not self.current.hasFocus():
                self.current.setValue(net.current_a if net.current_a is not None else 0.0)
            self.voltage_stated.setChecked(net.voltage_v is not None)
            self.voltage.setEnabled(net.voltage_v is not None)
            if net.voltage_v is not None and not self.voltage.hasFocus():
                self.voltage.setValue(net.voltage_v)
            self.pins.setText(
                ", ".join(f"{node.component_ref}.{node.pin}" for node in net.nodes) or "—"
            )
            if another:
                for problem in (self.class_problem, self.current_problem,
                                self.voltage_problem):
                    problem.show_problem("")
        finally:
            self._loading = False

    def _update(self, payload: UpdateNetPayload) -> str | None:
        return self._inspector.dispatch("net.update", payload)

    def _commit_name(self, typed: str) -> str | None:
        """The name, and the class with it while the class still says only what the old
        name implied: N3 renamed GND becomes a ground net, and a GND somebody deliberately
        made a signal stays one when it is renamed AGND."""
        net = self._net
        if net is None:
            return None
        follows = net.net_class == infer_net_class(net.name)
        implied = infer_net_class(typed)
        return self._update(
            UpdateNetPayload(
                id=net.id,
                name=typed,
                net_class=implied if follows and implied != net.net_class else None,
            )
        )

    def _commit_class(self, value: NetClass) -> None:
        net = self._net
        if self._loading or net is None or value == net.net_class:
            return
        self.class_problem.show_problem(
            self._update(UpdateNetPayload(id=net.id, net_class=value)) or ""
        )

    def _commit_current(self) -> None:
        net = self._net
        if self._loading or net is None:
            return
        value = self.current.value()
        wanted = value if value > 0 else None
        if wanted == net.current_a:
            return
        self.current_problem.show_problem(
            self._update(UpdateNetPayload(id=net.id, current_a=wanted)) or ""
        )

    def _commit_voltage(self, *_args: object) -> None:
        net = self._net
        if self._loading or net is None:
            return
        stated = self.voltage_stated.isChecked()
        self.voltage.setEnabled(stated)
        wanted = self.voltage.value() if stated else None
        if wanted == net.voltage_v:
            return
        self.voltage_problem.show_problem(
            self._update(UpdateNetPayload(id=net.id, voltage_v=wanted)) or ""
        )


# -- a label written on the board -----------------------------------------------------------


def _rotation(degrees: int) -> Rotation:
    return 90 if degrees == 90 else 180 if degrees == 180 else 270 if degrees == 270 else 0


class _BoardNoteEditor(QWidget):
    """A label written on the board: what it says, how tall, which way and on which face.
    Replaces the Board Label dialog, and Add Label Here writes one and puts the keyboard in
    its text."""

    FACES: tuple[tuple[BoardSide, str], ...] = (
        ("top", "Component side (top)"),
        ("bottom", "Solder side (bottom)"),
    )

    def __init__(self, inspector: Inspector, actions: InspectorActions) -> None:
        super().__init__()
        self._inspector = inspector
        self._note: BoardNote | None = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])
        self.title = QLabel(theme.heading(t("Board Label")))
        self.title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.title)

        form = _form()
        self.text = CommitLine(self._commit_text)
        self.text.setPlaceholderText(t("What to write on the board: MOTOR 24V, CAN →…"))
        _add_field(form, t("Text"), self.text, self.text.problem)
        self.text_height = QDoubleSpinBox()
        self.text_height.setRange(0.5, 10.0)
        self.text_height.setSingleStep(0.25)
        self.text_height.setDecimals(2)
        self.text_height.setSuffix(" mm")
        self.text_height.editingFinished.connect(self._commit_size)
        self.size_problem = _Problem()
        _add_field(form, t("Height"), self.text_height, self.size_problem)

        turns = QWidget()
        turn_row = QHBoxLayout(turns)
        turn_row.setContentsMargins(0, 0, 0, 0)
        turn_row.setSpacing(2)
        self.rotation = QButtonGroup(self)
        self.rotation.setExclusive(True)
        for degrees in (0, 90, 180, 270):
            button = QToolButton()
            button.setText(f"{degrees}°")
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.rotation.addButton(button, degrees)
            turn_row.addWidget(button)
        self.rotation.idClicked.connect(self._commit_rotation)
        self.rotation_problem = _Problem()
        _add_field(form, t("Rotation"), turns, self.rotation_problem)

        faces = QWidget()
        face_column = QVBoxLayout(faces)
        face_column.setContentsMargins(0, 0, 0, 0)
        face_column.setSpacing(2)
        self.face = QButtonGroup(self)
        self.face.setExclusive(True)
        self._face_buttons: dict[BoardSide, QCheckBox] = {}
        for value, label in self.FACES:
            face_button = QCheckBox(t(label))
            self.face.addButton(face_button)
            self._face_buttons[value] = face_button
            face_button.clicked.connect(lambda _checked=False, v=value: self._commit_face(v))
            face_column.addWidget(face_button)
        faces.setToolTip(
            t("A label on the solder side is written where the wiring is checked, and reads "
              "the right way round from underneath.")
        )
        self.face_problem = _Problem()
        _add_field(form, t("Face"), faces, self.face_problem)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch(1)
        buttons.addWidget(_action_button(actions.delete))
        layout.addLayout(buttons)

    def load(self, note: BoardNote) -> None:
        another = self._note is None or self._note.id != note.id
        self._note = note
        self._loading = True
        try:
            self.text.show_value(note.text)
            if not self.text_height.hasFocus():
                self.text_height.setValue(note.size_mm)
            button = self.rotation.button(note.rotation)
            if button is not None:
                button.setChecked(True)
            self._face_buttons[note.side].setChecked(True)
            if another:
                for problem in (self.size_problem, self.rotation_problem, self.face_problem):
                    problem.show_problem("")
        finally:
            self._loading = False

    def _update(self, payload: UpdateBoardNotePayload) -> str | None:
        return self._inspector.dispatch("board.note.update", payload)

    def _commit_text(self, typed: str) -> str | None:
        note = self._note
        if note is None:
            return None
        return self._update(UpdateBoardNotePayload(id=note.id, text=typed))

    def _commit_size(self) -> None:
        note = self._note
        if self._loading or note is None or self.text_height.value() == note.size_mm:
            return
        self.size_problem.show_problem(
            self._update(UpdateBoardNotePayload(id=note.id, size_mm=self.text_height.value())) or ""
        )

    def _commit_rotation(self, degrees: int) -> None:
        note = self._note
        if self._loading or note is None or degrees == note.rotation:
            return
        self.rotation_problem.show_problem(
            self._update(UpdateBoardNotePayload(id=note.id, rotation=_rotation(degrees))) or ""
        )

    def _commit_face(self, side: BoardSide) -> None:
        note = self._note
        if self._loading or note is None or side == note.side:
            return
        self.face_problem.show_problem(
            self._update(UpdateBoardNotePayload(id=note.id, side=side)) or ""
        )


# -- something written or drawn on the sheet -------------------------------------------------


class _SheetNoteEditor(QWidget):
    """A note on the sheet: what a caption says and how tall it is written; a box, a line or
    a circle is said by name. The Text tool writes one saying "Text" and puts the keyboard
    here, in place of the dialog that asked first."""

    def __init__(self, inspector: Inspector) -> None:
        super().__init__()
        self._inspector = inspector
        self._note: SheetNote | None = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.title)
        form = _form()
        self.text = CommitLine(self._commit_text)
        _add_field(form, t("Text"), self.text, self.text.problem)
        self.text_height = QDoubleSpinBox()
        self.text_height.setRange(0.5, 20.0)
        self.text_height.setSingleStep(0.5)
        self.text_height.setDecimals(1)
        self.text_height.setSuffix(" mm")
        self.text_height.editingFinished.connect(self._commit_size)
        self.size_problem = _Problem()
        _add_field(form, t("Size"), self.text_height, self.size_problem)
        self._form = form
        layout.addLayout(form)

    def load(self, note: SheetNote) -> None:
        another = self._note is None or self._note.id != note.id
        self._note = note
        self._loading = True
        try:
            # Each said in the tool's own word, as the sheet's tools name them.
            kinds = {"text": t("Text"), "rectangle": t("Box"), "line": t("Line"),
                     "circle": t("Circle")}
            self.title.setText(theme.heading(kinds.get(note.kind, note.kind)))
            writing = note.kind == "text"
            for row in (0, 1):  # the text and its size: a box has neither
                self._form.setRowVisible(row, writing)
            self.text.show_value(note.text)
            if not self.text_height.hasFocus():
                self.text_height.setValue(note.size_mm)
            if another:
                self.size_problem.show_problem("")
        finally:
            self._loading = False

    def _commit_text(self, typed: str) -> str | None:
        note = self._note
        if note is None:
            return None
        return self._inspector.dispatch(
            "sheet.note.update", UpdateSheetNotePayload(id=note.id, text=typed)
        )

    def _commit_size(self) -> None:
        note = self._note
        if self._loading or note is None or self.text_height.value() == note.size_mm:
            return
        self.size_problem.show_problem(
            self._inspector.dispatch(
                "sheet.note.update",
                UpdateSheetNotePayload(id=note.id, size_mm=self.text_height.value()),
            )
            or ""
        )


# -- one conductor ---------------------------------------------------------------------------


class _ConductorEditor(QWidget):
    """One run of copper or wire: what it is, from where to where, over how many holes, and
    on which net. What the status bar said about a selected conductor, and more of it --
    it said only that one was selected, and Delete looked as if it acted on nothing.

    WHAT IT IS CAN CHANGE, among the kinds legal on its path: a solder trace and a
    reinforced one are the same run of pads, and a bare wire, an insulated one and a jumper
    over the parts the same two holes. One ``conductor.replace`` keeping the id, the path
    and the net -- so it stays selected and undoes in one step -- where it took deleting the
    run and drawing it again with another tool."""

    #: The kinds one run can be made into, by family.
    SOLDER: tuple[str, ...] = ("solder-trace", "solder-trace-wired")
    WIRE: tuple[str, ...] = ("bare-wire", "insulated-wire", "top-jumper")

    def __init__(self, inspector: Inspector, actions: InspectorActions) -> None:
        super().__init__()
        self._inspector = inspector
        self._document: PerfDocument | None = None
        self._conductor: Conductor | None = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.title)
        form = _form()
        # A combo, not a row of buttons: "Jumper Over the Parts" beside two more wire kinds
        # was wider than the panel.
        self.kind = QComboBox()
        self.kind.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.kind.setMinimumContentsLength(8)
        self._kind_words = {
            "solder-trace": t("&Solder Trace"),
            "solder-trace-wired": t("&Reinforced Solder Trace"),
            "bare-wire": t("&Bare Wire"),
            "insulated-wire": t("&Insulated Wire"),
            "top-jumper": t("&Jumper Over the Parts"),
        }
        self.kind.activated.connect(self._on_kind_chosen)
        self.kind_problem = _Problem()
        _add_field(form, t("Kind"), self.kind, self.kind_problem)
        self._kind_row = self.kind
        self.ends = _fact()
        form.addRow(t("Holes"), self.ends)
        self.net = _fact()
        form.addRow(t("Net"), self.net)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(_action_button(actions.route_selected))
        buttons.addStretch(1)
        buttons.addWidget(_action_button(actions.delete))
        layout.addLayout(buttons)

    @staticmethod
    def kind_of(conductor: Conductor) -> str:
        kind = str(getattr(conductor, "kind", "solder-trace"))
        if kind == "solder-trace" and getattr(conductor, "spine", None) is not None:
            return "solder-trace-wired"
        return kind

    def load(self, document: PerfDocument, conductor: Conductor) -> None:
        another = self._conductor is None or self._conductor.id != conductor.id
        self._document = document
        self._conductor = conductor
        kind = self.kind_of(conductor)
        family = self.SOLDER if kind in self.SOLDER else self.WIRE if kind in self.WIRE else ()
        self._loading = True
        try:
            self._kind_row.setVisible(bool(family))
            self.kind.clear()
            for each in family:
                self.kind.addItem(self._kind_words[each].replace("&", ""), each)
            self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
            if another:
                self.kind_problem.show_problem("")
        finally:
            self._loading = False
        # Each kind in the words its drawing tool has; asked here, in the window's language.
        words = {
            "solder-trace": t("&Solder Trace"),
            "solder-trace-wired": t("&Reinforced Solder Trace"),
            "bare-wire": t("&Bare Wire"),
            "insulated-wire": t("&Insulated Wire"),
            "top-jumper": t("&Jumper Over the Parts"),
            "lead-bend": t("Bent lead"),
            "strip": t("Copper strip"),
        }.get(kind, kind)
        self.title.setText(theme.heading(words.replace("&", "")))
        board = document.board
        path = conductor.path
        self.ends.setText(
            t("{start} → {end}, {count} holes").format(
                start=format_hole(path[0], board), end=format_hole(path[-1], board),
                count=len(path),
            )
            if path
            else "—"
        )
        net = next((n for n in document.nets if n.id == conductor.net_id), None)
        self.net.setText(net.name if net is not None else "—")

    def _on_kind_chosen(self, index: int) -> None:
        chosen = self.kind.itemData(index)
        if isinstance(chosen, str):
            self._commit_kind(chosen)

    def _commit_kind(self, kind: str) -> None:
        conductor, document = self._conductor, self._document
        if self._loading or conductor is None or document is None:
            return
        if kind == self.kind_of(conductor):
            return
        spec: NewConductor
        if kind in self.SOLDER:
            spec = NewSolderTraceConductor(
                path=conductor.path,
                kind="solder-trace-wired" if kind == "solder-trace-wired" else "solder-trace",
                net_id=conductor.net_id,
                layer_z=conductor.layer_z,
            )
        else:
            wire_kind: Literal["bare-wire", "insulated-wire", "top-jumper"] = (
                "insulated-wire" if kind == "insulated-wire"
                else "top-jumper" if kind == "top-jumper" else "bare-wire"
            )
            spec = NewWireConductor(
                path=conductor.path,
                kind=wire_kind,
                side=wire_side(wire_kind, document.board),
                gauge_awg=getattr(conductor, "gauge_awg", None),
                color=getattr(conductor, "color", None),
                net_id=conductor.net_id,
                layer_z=conductor.layer_z,
            )
        problem = self._inspector.dispatch(
            "conductor.replace",
            ReplaceConductorsPayload(
                remove_ids=(conductor.id,), conductors=(spec,), ids=(conductor.id,)
            ),
        )
        self.kind_problem.show_problem(problem or "")
        if problem:
            self.load(document, conductor)


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
        self.design_part_editor = _DesignPartEditor(self, actions)
        self.parts_editor = _PartsEditor(self, actions)
        self.placing_editor = _PlacingEditor(self)
        self.net_editor = _NetEditor(self, actions)
        self.board_note_editor = _BoardNoteEditor(self, actions)
        self.sheet_note_editor = _SheetNoteEditor(self)
        self.conductor_editor = _ConductorEditor(self, actions)
        self.feature_editor = FeatureEditor(self.dispatch)
        self.summary = _Summary()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # Stacked by hand rather than in a QStackedWidget, which is as tall as its tallest
        # page: the board's three fields would sit over the part editor's empty height.
        self._pages: tuple[QWidget, ...] = (
            self.board_editor, self.part_editor, self.design_part_editor,
            self.parts_editor, self.placing_editor,
            self.net_editor, self.board_note_editor, self.sheet_note_editor,
            self.conductor_editor, self.feature_editor, self.summary,
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
        if selection.kind in ("mounting-hole", "edge-connector"):
            # Chosen on the board: the board's list of them opens, for when it is shown next.
            self.board_editor.features.set_open(True, emit=True)
        if selection.kind == "board":
            self.board_editor.load(document)
            page = self.board_editor
        elif selection.kind == "part" and selection.ids:
            component = next((c for c in document.components if c.id == selection.ids[0]), None)
            if component is not None:
                self.part_editor.load(document, component)
                page = self.part_editor
        elif selection.kind == "design-part" and selection.ids:
            design = next((p for p in document.parts if p.id == selection.ids[0]), None)
            if design is not None:
                self.design_part_editor.load(design)
                page = self.design_part_editor
        elif selection.kind == "parts":
            chosen = set(selection.ids)
            components = tuple(c for c in document.components if c.id in chosen)
            if len(components) > 1:
                self.parts_editor.load(document, components)
                page = self.parts_editor
        elif selection.kind == "net" and selection.ids:
            net = next((n for n in document.nets if n.id == selection.ids[0]), None)
            if net is not None:
                self.net_editor.load(document, net)
                page = self.net_editor
        elif selection.kind == "board-note" and len(selection.ids) == 1:
            note = next((n for n in document.board_notes if n.id == selection.ids[0]), None)
            if note is not None:
                self.board_note_editor.load(note)
                page = self.board_note_editor
        elif selection.kind == "sheet-note" and len(selection.ids) == 1:
            written = next((n for n in document.sheet_notes if n.id == selection.ids[0]), None)
            if written is not None:
                self.sheet_note_editor.load(written)
                page = self.sheet_note_editor
        elif selection.kind == "conductor" and selection.ids:
            conductor = next((c for c in document.conductors if c.id == selection.ids[0]), None)
            if conductor is not None:
                self.conductor_editor.load(document, conductor)
                page = self.conductor_editor
        elif selection.kind == "mounting-hole" and selection.ids:
            mount = next((m for m in document.mounting_holes if m.id == selection.ids[0]), None)
            if mount is not None:
                self.feature_editor.load_hole(document, mount)
                page = self.feature_editor
        elif selection.kind == "edge-connector" and selection.ids:
            connector = next(
                (c for c in document.edge_connectors if c.id == selection.ids[0]), None
            )
            if connector is not None:
                self.feature_editor.load_connector(document, connector)
                page = self.feature_editor
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
        elif self.shown is self.design_part_editor:
            fields = {"ref": self.design_part_editor.ref, "value": self.design_part_editor.value}
        elif self.shown is self.parts_editor:
            fields = {"value": self.parts_editor.value}
        elif self.shown is self.placing_editor:
            fields = {"value": self.placing_editor.value}
        elif self.shown is self.net_editor:
            fields = {"name": self.net_editor.name}
        elif self.shown is self.board_note_editor:
            fields = {"text": self.board_note_editor.text}
        elif self.shown is self.sheet_note_editor:
            fields = {"text": self.sheet_note_editor.text}
        elif self.shown is self.board_editor:
            fields = {"name": self.board_editor.name}
        field = fields.get(name)
        if field is None:
            return False
        field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        field.selectAll()
        return True
