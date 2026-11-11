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
from html import escape
from typing import Literal, TypeVar, cast

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QColor, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from perfboard_studio.breadboard import is_breadboard
from perfboard_studio.command import DispatchResult
from perfboard_studio.commands import (
    DeleteBoardPayload,
    DeleteCablePayload,
    LockComponentsPayload,
    MirrorComponentPayload,
    MoveComponentPayload,
    NewConductor,
    NewSolderTraceConductor,
    NewWireConductor,
    RenameBoardPayload,
    RenameDocumentPayload,
    ReplaceConductorsPayload,
    RotateComponentPayload,
    SetBodyClearancePayload,
    SetComponentSidePayload,
    SetHeightLimitPayload,
    UpdateBoardNotePayload,
    UpdateCablePayload,
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
    BoardId,
    BoardNote,
    BoardSide,
    Cable,
    CableEnd,
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
from perfboard_studio.system import (
    FIRST_BOARD,
    board_document,
    board_ids,
    board_title,
    connector_of,
    extra_board,
)
from perfboard_studio.wirecolour import net_colours

from . import theme
from .boardfeatures import FeatureEditor, FeaturesGroup
from .engine_text import say
from .i18n import counted, hole_grid, language, t
from .numberbox import NumberBox
from .partfields import PinoutEditor, note_editor, pinout_for_retyped_value
from .partnames import footprint_label
from .properties import describe
from .selection import NOTHING, Selection

#: The kinds read off the whole system rather than the board in front.
SYSTEM_KINDS = ("system", "system-board", "cable")

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
    #: Whether the board's holes and connectors open as they did last time, and where to
    #: say they were opened or closed: asked when the board's editor is first built.
    features_open: Callable[[], bool] = lambda: False
    features_opened: Callable[[bool], object] = lambda _on: None
    #: The whole system and the id of the board in front, for what is the system's rather
    #: than one board's: a board's own name among several, and System's editors. Left out,
    #: the document handed over is the only board there is.
    system: Callable[[], tuple[PerfDocument, BoardId]] | None = None
    #: A board of the system in front, as a double-click on it in System does.
    open_board: Callable[[BoardId], object] = lambda _board: None
    #: Add Board and Add Cable, as the Board menu has them.
    add_board: Callable[[], object] = lambda: None
    add_cable: Callable[[], object] = lambda: None
    #: The step bar's Next, as the step card's button does it.
    next_step: Callable[[], object] = lambda: None
    #: Something done to a whole net's copper from one piece of it -- "select", "redo" or
    #: "remove" -- as the piece's right-click menu does it.
    net_wiring: Callable[[str, str], object] = lambda _what, _net: None
    #: What a conductor lies across on its way, in a sentence ("" when nothing): the
    #: holes a wire passes over between its ends, and what is in them.
    lies_across: Callable[[str], str] = lambda _conductor: ""
    #: The styles one net's wiring can be redone in, (id, name), and the window's own.
    wiring_styles: Callable[[], tuple[tuple[str, str], ...]] = lambda: ()
    current_style: Callable[[], str] = lambda: ""
    #: One of the step card's wiring counts clicked, by its key: select what it counts.
    select_wiring: Callable[[str], object] = lambda _key: None
    #: Whether the window says where the work stands (``Inspector.set_step``): nothing
    #: selected is then the step, and the board's editor waits for Board Settings. Left out,
    #: nothing selected is the board, as it always was.
    shows_steps: bool = False


@dataclass(frozen=True, slots=True)
class StepNote:
    """Where the work stands, as the window's step bar says it: what Properties shows with
    nothing selected (``_StepCard``). Plain words, so the inspector needs nothing from the
    step bar's module."""

    #: 1 to 6, in the order the steps are done.
    number: int
    title: str
    #: The step bar's line under the step's name: "3 connections to wire".
    summary: str
    #: What to do now, in a sentence (``workflow.step_hint``).
    hint: str
    #: What the Next button says.
    action: str
    #: The wiring as it stands, once there is some: "53 wires, 1.2 m, 77 bends". "" before.
    wiring: str = ""
    #: What is worth a look in it, (key, said): each a link selecting the wires it counts.
    wiring_notes: tuple[tuple[str, str], ...] = ()


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
            if not self.hasFocus():
                # setText leaves the cursor at the end, and a name longer than the panel
                # then showed its tail: "lay Driver and Its Supply". The start is what
                # names it. Not while it is being typed in.
                self.setCursorPosition(0)
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


def value_placeholder(ref: str) -> str:
    """What an empty value field shows, by the reference's letters.

    A new resistor's value was a blank box whose one example named a chip; "e.g. 470,
    10k" says what a resistor's value looks like, as the guide's parts list prints it.
    """
    letters = ref.rstrip("0123456789?").upper()
    if letters == "R":
        return t("e.g. 470, 10k")
    if letters in ("RV", "VR"):
        return t("e.g. 10k")
    if letters == "C":
        return t("e.g. 100nF, 10µF")
    if letters == "L":
        return t("e.g. 10µH, 100µH")
    return "10k, 100nF, NE555…"


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


# -- nothing selected: the step, and the board a click away -------------------------------


class _StepCard(QWidget):
    """Nothing selected: where the work stands and what to do now, with the step's own
    action on a button and the board's settings one click away.

    THE BOARD'S EDITOR USED TO BE WHAT "NOTHING SELECTED" SHOWED, and on the first screen --
    a person about to draw their first circuit -- the right-hand panel opened on a height
    limit, the clearance between bodies, pads per hole and mounting holes (the newcomer
    walkthrough's third stall). The board is still the selection when nothing else is; its
    editor is what Board Settings opens, and what Rename Board and a mounting hole picked on
    the board open straight away.
    """

    def __init__(self, inspector: Inspector) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["md"])
        self.step = _fact()
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.summary = _fact()
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        # The wiring as Auto-wire left it, and what is worth a look in it, each count a
        # link to the wires it counts: said where it stays, not in one status line.
        self._inspector = inspector
        self.wiring = _fact()
        self.wiring_links = QWidget()
        self._links = QVBoxLayout(self.wiring_links)
        self._links.setContentsMargins(0, 0, 0, 0)
        self._links.setSpacing(0)
        self.next = QPushButton()
        theme.variant(self.next, "primary")
        self.next.clicked.connect(lambda: inspector.hooks.next_step())
        self.board_settings = QPushButton(t("Board Settings…"))
        theme.variant(self.board_settings, "link")
        self.board_settings.setToolTip(
            t("The board's name, its size and type, and what a case asks of it.")
        )
        self.board_settings.clicked.connect(inspector.open_board_settings)
        for widget in (
            self.step, self.title, self.summary, self.hint, self.wiring, self.wiring_links
        ):
            layout.addWidget(widget)
        layout.addWidget(self.next, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.board_settings, 0, Qt.AlignmentFlag.AlignLeft)

    def load(self, note: StepNote) -> None:
        self.step.setText(t("Step {number} of 6").format(number=note.number))
        # A step's name is the interface's own word, never something typed.
        self.title.setText(theme.heading(note.title))
        self.summary.setText(note.summary)
        self.hint.setText(note.hint)
        self.next.setText(note.action)
        self.wiring.setText(note.wiring)
        self.wiring.setVisible(bool(note.wiring))
        while self._links.count():
            item = self._links.takeAt(0)
            gone = item.widget() if item is not None else None
            if gone is not None:
                # Hidden now: out of the layout it is still drawn, at the width it was
                # last given, until the event loop gets round to deleting it.
                gone.hide()
                gone.deleteLater()
        for key, said in note.wiring_notes:
            # A label, not a link-styled button: a button does not wrap, and the longest
            # count ("14 places a wire lies over where other copper ends") widened the
            # whole panel, and the board beside it shifted.
            link = QLabel(f'<a href="{escape(key)}">{escape(said)}</a>')
            link.setTextFormat(Qt.TextFormat.RichText)
            link.setWordWrap(True)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
            link.setToolTip(t("Select these wires on the board."))
            link.linkActivated.connect(self._inspector.hooks.select_wiring)
            self._links.addWidget(link)
        self.wiring_links.setVisible(bool(note.wiring_notes))


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
        #: The board this editor names, when the document has several; None on one board,
        #: whose Name is the document's.
        self._board_id: BoardId | None = None
        form = _form()

        self.name = CommitLine(self._commit_name)
        self._document_tip = t(
            "The board's title, printed on the build guide, on the schematic and on "
            "the project folder. A board is named after its file when first saved."
        )
        self._board_tip = t(
            "This board's name among the others: on the strip, in System, on the harness "
            "and on its build guide. Left empty, it is called by its place."
        )
        self.name.setToolTip(self._document_tip)
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
        self.height_limit = NumberBox()
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
        self.body_clearance = NumberBox()
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
            system = self._inspector.system_and_board()
            if system is not None and len(board_ids(system[0])) > 1:
                # One of several: the board's own name, and its place when it has none --
                # what the strip and System call it (``system.board_title``).
                whole, board_id = system
                self._board_id = board_id
                self.name.show_value(own_board_name(whole, board_id))
                self.name.setPlaceholderText(place_name(whole, board_id))
                self.name.setToolTip(self._board_tip)
            else:
                self._board_id = None
                named = document.meta.name
                self.name.show_value("" if named == UNTITLED_NAME else named)
                self.name.setPlaceholderText(t("untitled"))
                self.name.setToolTip(self._document_tip)
            board = document.board
            kind = self.kind_name(board.type)
            words = [kind] if kind is not None else []
            # The size is one thing to read, so it wraps whole after the board's kind:
            # the narrow panel broke it as "28 ×" over "6 holes".
            size = hole_grid(board.cols, board.rows)
            words.append(size.replace(" ", "\u00a0"))
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
        if self._board_id is not None:
            # Empty is allowed: the board is called by its place again.
            return self._inspector.dispatch(
                "board.rename", RenameBoardPayload(board=self._board_id, name=typed)
            )
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


# -- the system: several boards and the cables between them ----------------------------------


def own_board_name(doc: PerfDocument, board_id: BoardId) -> str:
    """The name somebody gave a board, or "" when nobody did."""
    return doc.board_name if board_id == FIRST_BOARD else extra_board(doc, board_id).name


def place_name(doc: PerfDocument, board_id: BoardId) -> str:
    """What a board of several is called when nobody named it: "Board 2", by its place."""
    say = phrasebook(guide_language(language()))
    return say("Board {n}", n=board_ids(doc).index(board_id) + 1)


def _buttons(*buttons: QPushButton) -> QWidget:
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(theme.SPACE["sm"])
    for button in buttons:
        line.addWidget(button)
    line.addStretch(1)
    return row


class _SystemEditor(QWidget):
    """The system itself -- System in front, nothing picked on it: the document's name, what
    is in it, and the two ways to add to it."""

    def __init__(self, inspector: Inspector) -> None:
        super().__init__()
        self._inspector = inspector
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])
        self.title = QLabel(theme.heading(t("System")))
        self.title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.title)
        form = _form()
        self.name = CommitLine(self._commit_name)
        self.name.setPlaceholderText(t("untitled"))
        self.name.setToolTip(
            t("The name of the whole document: its file, its project and every board's guide.")
        )
        _add_field(form, t("Name"), self.name, self.name.problem)
        self.contents = _fact()
        form.addRow(t("Contents"), self.contents)
        layout.addLayout(form)
        self.add_board = QPushButton(t("Add Board"))
        self.add_board.clicked.connect(lambda: inspector.hooks.add_board())
        self.add_cable = QPushButton(t("Add Cable…"))
        self.add_cable.clicked.connect(lambda: inspector.hooks.add_cable())
        layout.addWidget(_buttons(self.add_board, self.add_cable))
        self.hint = _fact(t("Click a board or a cable to see it here."))
        layout.addWidget(self.hint)

    def load(self, system: PerfDocument) -> None:
        named = system.meta.name
        self.name.show_value("" if named == UNTITLED_NAME else named)
        boards = counted(len(board_ids(system)), t("{count} board"), t("{count} boards"))
        cables = counted(len(system.cables), t("{count} cable"), t("{count} cables"))
        self.contents.setText(f"{boards},  {cables}")

    def _commit_name(self, typed: str) -> str | None:
        if not typed:
            return None
        return self._inspector.dispatch("document.rename", RenameDocumentPayload(name=typed))


class _SystemBoardEditor(QWidget):
    """A board picked in System: its name, what it is, what is on it; open it, or take it
    out of the system (its parts back into the design, as ``board.delete`` does)."""

    def __init__(self, inspector: Inspector) -> None:
        super().__init__()
        self._inspector = inspector
        self._board_id: BoardId | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.title)
        form = _form()
        self.name = CommitLine(self._commit_name)
        self.name.setToolTip(
            t(
                "This board's name among the others: on the strip, in System, on the harness "
                "and on its build guide. Left empty, it is called by its place."
            )
        )
        _add_field(form, t("Name"), self.name, self.name.problem)
        self.summary = _fact()
        form.addRow(t("Board"), self.summary)
        self.contents = _fact()
        form.addRow(t("Contents"), self.contents)
        layout.addLayout(form)
        self.open = QPushButton(t("Open"))
        self.open.setToolTip(t("This board in front, to place and wire it."))
        self.open.clicked.connect(self._open)
        self.remove = QPushButton(t("Remove Board"))
        self.remove.setToolTip(
            t(
                "Take this board out of the document. Its parts go back to the design, wired "
                "as they were. A cable that reaches it has to be removed first."
            )
        )
        self.remove.clicked.connect(self._remove)
        layout.addWidget(_buttons(self.open, self.remove))
        self.problem = _Problem()
        layout.addWidget(self.problem)

    def load(self, system: PerfDocument, board_id: BoardId) -> None:
        if board_id != self._board_id:
            self.problem.show_problem("")
        self._board_id = board_id
        self.title.setText(theme.heading(board_title(system, board_id, language())))
        self.name.show_value(own_board_name(system, board_id))
        self.name.setPlaceholderText(place_name(system, board_id))
        view = board_document(system, board_id)
        board = view.board
        kind = _BoardEditor.kind_name(board.type)
        size = hole_grid(board.cols, board.rows)
        words = [kind] if kind is not None else []
        words.append(size.replace(" ", "\u00a0"))
        self.summary.setText(",  ".join(words))
        reaching = sum(1 for c in system.cables if board_id in (c.a.board, c.b.board))
        parts = counted(len(view.components), t("{count} part"), t("{count} parts"))
        cables = counted(reaching, t("{count} cable"), t("{count} cables"))
        self.contents.setText(f"{parts},  {cables}")
        # The first board is the document itself: board.delete refuses it, so it is not
        # offered.
        self.remove.setVisible(board_id != FIRST_BOARD)

    def _commit_name(self, typed: str) -> str | None:
        if self._board_id is None:
            return None
        return self._inspector.dispatch(
            "board.rename", RenameBoardPayload(board=self._board_id, name=typed)
        )

    def _open(self) -> None:
        if self._board_id is not None:
            self._inspector.hooks.open_board(self._board_id)

    def _remove(self) -> None:
        if self._board_id is not None:
            self.problem.show_problem(
                self._inspector.dispatch("board.delete", DeleteBoardPayload(board=self._board_id))
                or ""
            )


class _WireList(QWidget):
    """A cable's wires, a row each: a swatch painted in the insulation's colour -- the
    wire as on the bench, not the chrome, so it is a picture rather than a styled span --
    then pin to pin and the net."""

    SWATCH_PX = 10

    def __init__(self) -> None:
        super().__init__()
        self._rows = QVBoxLayout(self)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(theme.SPACE["xs"])
        self._said: list[str] = []

    def show_wires(self, lines: list[tuple[QColor, str]]) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._said = [said for _colour, said in lines] or [t("No wires")]
        if not lines:
            self._rows.addWidget(_fact(t("No wires")))
            return
        for colour, said in lines:
            row = QWidget()
            across = QHBoxLayout(row)
            across.setContentsMargins(0, 0, 0, 0)
            across.setSpacing(theme.SPACE["sm"])
            chip = QPixmap(self.SWATCH_PX, self.SWATCH_PX)
            chip.fill(colour)
            swatch = QLabel()
            swatch.setPixmap(chip)
            across.addWidget(swatch)
            words = _fact(said)
            words.setTextFormat(Qt.TextFormat.PlainText)
            across.addWidget(words, 1)
            self._rows.addWidget(row)

    def text(self) -> str:
        """What the rows say, a line each -- for a test, and for anyone reading it out."""
        return "\n".join(self._said)


class _CableEditor(QWidget):
    """A cable picked in System: its reference, its two ends, its wires pin to pin in the
    colours the harness cuts them in, its length and note; and Remove."""

    def __init__(self, inspector: Inspector) -> None:
        super().__init__()
        self._inspector = inspector
        self._cable: Cable | None = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["lg"])
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.title)
        form = _form()
        self.ref = CommitLine(self._commit_ref)
        self.ref.setPlaceholderText("W1, W2…")
        self.ref.setToolTip(t("What the harness and the cut list call this cable."))
        _add_field(form, t("Reference"), self.ref, self.ref.problem)
        self.a_end = _fact()
        form.addRow(t("From"), self.a_end)
        self.b_end = _fact()
        form.addRow(t("To"), self.b_end)
        self.wires = _WireList()
        form.addRow(t("Pin to pin"), self.wires)
        # 0 is "not given", as the height limit's 0 is "no limit": a spin box cannot be
        # empty, and no cable is 0 mm long.
        self.length = NumberBox()
        self.length.setRange(0.0, 10000.0)
        self.length.setDecimals(0)
        self.length.setSingleStep(10.0)
        self.length.setSuffix(" mm")
        self.length.setSpecialValueText(t("Not given"))
        self.length.setToolTip(
            t("How long to cut it, end to end; the guide adds what is stripped. Not given, the "
              "guide leaves the length to you.")
        )
        self.length_problem = _Problem()
        self.length.editingFinished.connect(self._commit_length)
        _add_field(form, t("Length"), self.length, self.length_problem)
        self.note = CommitLine(self._commit_note)
        self.note.setToolTip(t("Anything the builder should know about this cable."))
        _add_field(form, t("Note"), self.note, self.note.problem)
        layout.addLayout(form)
        self.remove = QPushButton(t("Remove Cable"))
        self.remove.clicked.connect(self._remove)
        layout.addWidget(_buttons(self.remove))
        self.problem = _Problem()
        layout.addWidget(self.problem)

    def load(self, system: PerfDocument, cable: Cable) -> None:
        if self._cable is None or cable.id != self._cable.id:
            self.problem.show_problem("")
        self._cable = cable
        self._loading = True
        try:
            self.title.setText(theme.heading(cable.ref))
            self.ref.show_value(cable.ref)
            self.a_end.setText(self._end(system, cable.a))
            self.b_end.setText(self._end(system, cable.b))
            self.wires.show_wires(self._wire_lines(system, cable))
            if not self.length.hasFocus():
                self.length.setValue(cable.length_mm or 0.0)
            self.note.show_value(cable.note)
        finally:
            self._loading = False

    @staticmethod
    def _end(system: PerfDocument, end: CableEnd) -> str:
        part = connector_of(system, end)
        board = board_title(system, end.board, language()) if end.board in board_ids(system) else end.board
        return f"{board}  ·  {part.ref if part is not None else end.connector}"

    @staticmethod
    def _wire_lines(system: PerfDocument, cable: Cable) -> list[tuple[QColor, str]]:
        """One line a wire: its insulation's colour, pin to pin, and its net."""
        from .view2d import named_insulation

        a_part, b_part = connector_of(system, cable.a), connector_of(system, cable.b)
        net_of = {(n.component_ref, n.pin): net for net in system.nets for n in net.nodes}
        colours = net_colours(system)
        lines = []
        for wire in cable.wires:
            net = (net_of.get((a_part.ref, wire.a_pin)) if a_part is not None else None) or (
                net_of.get((b_part.ref, wire.b_pin)) if b_part is not None else None
            )
            colour = wire.colour or (colours.get(net.id, "grey") if net is not None else "grey")
            said = f"{wire.a_pin} → {wire.b_pin}"
            if net is not None:
                said += f"  ·  {net.name}"
            lines.append((named_insulation(colour), said))
        return lines

    def _update(self, **changes: object) -> str | None:
        if self._cable is None:
            return None
        changed = dataclasses.replace(self._cable, **changes)  # type: ignore[arg-type]
        return self._inspector.dispatch("cable.update", UpdateCablePayload(cable=changed))

    def _commit_ref(self, typed: str) -> str | None:
        if not typed:
            return None
        return self._update(ref=typed)

    def _commit_note(self, typed: str) -> str | None:
        return self._update(note=typed)

    def _commit_length(self) -> None:
        if self._loading or self._cable is None:
            return
        value = self.length.value()
        wanted = None if value <= 0 else value
        if wanted == self._cable.length_mm:
            return
        self.length_problem.show_problem(self._update(length_mm=wanted) or "")

    def _remove(self) -> None:
        if self._cable is not None:
            self.problem.show_problem(
                self._inspector.dispatch("cable.delete", DeleteCablePayload(id=self._cable.id)) or ""
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

        # Which face it stands on, in the words a label's face is chosen in: a part under
        # the board is put in from underneath, turned over (Shift+M does the same).
        faces = QWidget()
        face_column = QVBoxLayout(faces)
        face_column.setContentsMargins(0, 0, 0, 0)
        face_column.setSpacing(2)
        self.face = QButtonGroup(self)
        self.face.setExclusive(True)
        self.face_buttons: dict[BoardSide, QCheckBox] = {}
        for value, label in _BoardNoteEditor.FACES:
            face_button = QCheckBox(t(label))
            self.face.addButton(face_button)
            self.face_buttons[value] = face_button
            face_button.clicked.connect(lambda _checked=False, v=value: self._commit_face(v))
            face_column.addWidget(face_button)
        faces.setToolTip(
            t("A part on the solder side is put in from underneath, turned over, so it is "
              "mirrored; its leads are soldered on the component side.")
        )
        self.face_problem = _Problem()
        _add_field(form, t("Face"), faces, self.face_problem)

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
            self.value.setPlaceholderText(value_placeholder(component.ref))
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
            # Under the board it is mirrored by being turned over; unmirrored there it is a
            # part nobody can put in, which the engine refuses.
            self.mirrored.setEnabled(component.side == "top")
            self.face_buttons[component.side].setChecked(True)
            self.face_buttons["bottom"].setEnabled(
                component.side == "bottom" or not is_breadboard(document.board)
            )
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
                                self.note_problem, self.face_problem):
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

    def _commit_face(self, side: BoardSide) -> None:
        component = self._component
        if self._loading or component is None or side == component.side:
            return
        problem = self._inspector.dispatch(
            "component.setSide", SetComponentSidePayload(id=component.id, side=side)
        )
        self.face_problem.show_problem(problem or "")
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
            self.value.setPlaceholderText(value_placeholder(part.ref))
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
        self.current = NumberBox()
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
        self.voltage = NumberBox()
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
        self.text_height = NumberBox()
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
        self.text_height = NumberBox()
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
        # What a wire passes over between its ends. "N1 → D1, 2 holes" was all a selected
        # wire said, about a wire lying over ten holes with pins in them.
        self.lies_across = _fact()
        form.addRow(t("Lies across"), self.lies_across)
        self._form = form
        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(_action_button(actions.route_selected))
        buttons.addStretch(1)
        buttons.addWidget(_action_button(actions.delete))
        layout.addLayout(buttons)
        # The piece's net, which is usually why a piece of copper was picked: the rest of
        # it, laid again, or taken up. Only the right-click menu offered these.
        self._net_id: str | None = None
        self.net_buttons = QWidget()
        column = QVBoxLayout(self.net_buttons)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.select_net = QToolButton()
        self.redo_net = QToolButton()
        self.remove_net = QToolButton()
        for what, button in (
            ("select", self.select_net), ("redo", self.redo_net), ("remove", self.remove_net)
        ):
            button.setAutoRaise(True)
            button.clicked.connect(lambda _checked=False, w=what: self._on_net_action(w))
            column.addWidget(button)
        layout.addWidget(self.net_buttons)
        # Redo in the window's style on a click, or in another from its arrow, for this
        # net only: the same choice its right-click menu offers.
        self.redo_styles = QMenu(self.redo_net)
        self.redo_styles.setToolTipsVisible(True)
        self.redo_styles.aboutToShow.connect(self._fill_redo_styles)
        self.redo_net.setMenu(self.redo_styles)
        self.redo_net.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

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
        self._net_id = net.id if net is not None else None
        self.net_buttons.setVisible(net is not None)
        if net is not None:
            self.select_net.setText(t("Select All of {net}").format(net=net.name))
            self.redo_net.setText(t("Redo Wiring of {net}").format(net=net.name))
            self.remove_net.setText(t("Remove Wiring of {net}").format(net=net.name))
        across = self._inspector.hooks.lies_across(conductor.id)
        self.lies_across.setText(across)
        self._form.setRowVisible(self.lies_across, bool(across))

    def _on_net_action(self, what: str) -> None:
        if self._net_id is not None:
            self._inspector.hooks.net_wiring(what, self._net_id)

    def _fill_redo_styles(self) -> None:
        self.redo_styles.clear()
        current = self._inspector.hooks.current_style()
        for style, label in self._inspector.hooks.wiring_styles():
            action = self.redo_styles.addAction(label)
            action.setCheckable(True)
            action.setChecked(style == current)
            action.triggered.connect(
                lambda _checked=False, s=style: self._on_net_action(f"redo:{s}")
            )

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


_Page = TypeVar("_Page", bound=QWidget)


class Inspector(QWidget):
    """The editors, one shown at a time, for whatever the panel says is selected.

    EACH EDITOR IS BUILT THE FIRST TIME IT IS ASKED FOR. Built together, the eleven of them
    were 120 ms of every start -- the part editor alone 40 -- for editors most sessions
    never open, and the start was 800 ms where 0.22.0's was 580 (ship's frozen-build
    measurement). Each is a property that builds its page into the column on first use."""

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
        self._actions = actions
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # Stacked by hand rather than in a QStackedWidget, which is as tall as its tallest
        # page: the board's three fields would sit over the part editor's empty height.
        self._column = layout
        self._built: dict[str, QWidget] = {}
        self.summary = _Summary()
        layout.addWidget(self.summary)
        self.summary.hide()
        layout.addStretch(1)
        self.shown: QWidget = self.summary
        #: Where the work stands, from the window (``set_step``); None until it first says.
        self._step: StepNote | None = None
        #: The board's editor asked for with nothing selected (``open_board_settings``),
        #: until something else is selected.
        self._board_settings = False

    def _page(self, key: str, make: Callable[[], _Page]) -> _Page:
        """The editor ``key``, built and put in the column, hidden, the first time."""
        page = self._built.get(key)
        if page is None:
            page = make()
            self._column.insertWidget(self._column.count() - 1, page)
            page.hide()
            self._built[key] = page
        return cast(_Page, page)

    def _board_editor(self) -> _BoardEditor:
        editor = _BoardEditor(self)
        editor.features.set_open(self.hooks.features_open())
        editor.features.opened.connect(self.hooks.features_opened)
        return editor

    @property
    def board_editor(self) -> _BoardEditor:
        return self._page("board", self._board_editor)

    @property
    def step_card(self) -> _StepCard:
        return self._page("step", lambda: _StepCard(self))

    def set_step(self, note: StepNote) -> None:
        """Where the work stands now; said again if the card is what is showing."""
        if note == self._step:
            return
        self._step = note
        if self.shown is self._built.get("step"):
            self.step_card.load(note)
        elif self._document is not None and self.selection.kind == "board":
            self._show()

    def open_board_settings(self) -> None:
        """The board's editor, with nothing selected: Board Settings on the step card."""
        self._board_settings = True
        self._show()

    @property
    def part_editor(self) -> _PartEditor:
        return self._page("part", lambda: _PartEditor(self, self._actions))

    @property
    def system_editor(self) -> _SystemEditor:
        return self._page("system", lambda: _SystemEditor(self))

    @property
    def system_board_editor(self) -> _SystemBoardEditor:
        return self._page("system-board", lambda: _SystemBoardEditor(self))

    @property
    def cable_editor(self) -> _CableEditor:
        return self._page("cable", lambda: _CableEditor(self))

    def system_and_board(self) -> tuple[PerfDocument, BoardId] | None:
        """The whole system and the board in front, when the window says; None otherwise."""
        system = self.hooks.system
        return system() if system is not None else None

    @property
    def design_part_editor(self) -> _DesignPartEditor:
        return self._page("design-part", lambda: _DesignPartEditor(self, self._actions))

    @property
    def parts_editor(self) -> _PartsEditor:
        return self._page("parts", lambda: _PartsEditor(self, self._actions))

    @property
    def placing_editor(self) -> _PlacingEditor:
        return self._page("placing", lambda: _PlacingEditor(self))

    @property
    def net_editor(self) -> _NetEditor:
        return self._page("net", lambda: _NetEditor(self, self._actions))

    @property
    def board_note_editor(self) -> _BoardNoteEditor:
        return self._page("board-note", lambda: _BoardNoteEditor(self, self._actions))

    @property
    def sheet_note_editor(self) -> _SheetNoteEditor:
        return self._page("sheet-note", lambda: _SheetNoteEditor(self))

    @property
    def conductor_editor(self) -> _ConductorEditor:
        return self._page("conductor", lambda: _ConductorEditor(self, self._actions))

    @property
    def feature_editor(self) -> FeatureEditor:
        return self._page("feature", lambda: FeatureEditor(self.dispatch))

    def dispatch(self, name: str, payload: object) -> str | None:
        """One command; why it was refused, in the window's language, or None."""
        result = self._dispatch(name, payload)
        return None if result.ok else say(result.message)

    def set_selection(self, selection: Selection) -> None:
        if selection.kind in ("mounting-hole", "edge-connector"):
            # The board's own features: the board's editor is where they are listed, so it
            # is what nothing selected shows after one.
            self._board_settings = True
        elif selection.kind != "board":
            self._board_settings = False
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
        system = self.system_and_board() if selection.kind in SYSTEM_KINDS else None
        if selection.kind == "board" and self.hooks.shows_steps and not self._board_settings:
            # Until the window first says where the work stands -- the first repaint, a
            # moment into a start -- the one-line summary stands in, rather than building
            # the board's editor for an instant nobody sees.
            if self._step is not None:
                self.step_card.load(self._step)
                page = self.step_card
        elif selection.kind == "board":
            self.board_editor.load(document)
            page = self.board_editor
        elif system is not None and selection.kind == "system":
            self.system_editor.load(system[0])
            page = self.system_editor
        elif system is not None and selection.kind == "system-board" and selection.ids:
            if selection.ids[0] in board_ids(system[0]):
                self.system_board_editor.load(system[0], selection.ids[0])
                page = self.system_board_editor
        elif system is not None and selection.kind == "cable" and selection.ids:
            cable = next((c for c in system[0].cables if c.id == selection.ids[0]), None)
            if cable is not None:
                self.cable_editor.load(system[0], cable)
                page = self.cable_editor
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
        if name == "name" and self.shown is self._built.get("step"):
            # Rename Board with nothing selected: the board's name is in its settings.
            self.open_board_settings()
        shown = self.shown
        # Matched on its type, so asking builds no editor that is not showing.
        if isinstance(shown, (_PartEditor, _DesignPartEditor)):
            fields = {"ref": shown.ref, "value": shown.value}
        elif isinstance(shown, (_PartsEditor, _PlacingEditor)):
            fields = {"value": shown.value}
        elif isinstance(shown, _NetEditor):
            fields = {"name": shown.name}
        elif isinstance(shown, (_BoardNoteEditor, _SheetNoteEditor)):
            fields = {"text": shown.text}
        elif isinstance(shown, (_BoardEditor, _SystemEditor, _SystemBoardEditor)):
            fields = {"name": shown.name}
        elif isinstance(shown, _CableEditor):
            fields = {"ref": shown.ref}
        field = fields.get(name)
        if field is None:
            return False
        field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        field.selectAll()
        return True
