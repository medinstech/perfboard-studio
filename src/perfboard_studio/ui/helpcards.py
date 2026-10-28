"""Help that is reached from where the question is: F1 over a thing, Shift+F1, a glossary.

THE TOOLTIPS WERE DOING TWO JOBS. A tooltip is read in the half second a pointer rests on
a button, and it was also where the reasons lived -- "annealing is a random walk", "what
every golden fixture is routed with" -- so the one sentence a newcomer needed was the
fourth one. Help now has three doors and ONE TEXT behind them:

  - F1 shows a card for whatever is under the pointer: what it is, in plain words, with
    its technical name beside it.
  - Shift+F1 is Qt's own What's This mode, the "?" cursor: click anything to read the same
    card. It is ``QWidget.whatsThis``, so the two cannot disagree.
  - Help ▸ Glossary lists the words the window and the build guide lean on, searchable,
    in the window's language.

The texts are catalogue entries keyed on the English like every other string, so the
Turkish is held to them by ``test_i18n`` with no mechanism of its own. ``install`` hangs them
on the window's panels and tools by NAME -- a dock's object name, an action's attribute --
so this module never imports the window, and a panel that moves keeps its help.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QCursor, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .i18n import t


def card(title: str, body: str) -> str:
    """One help text: a plain name, then what it is. Rich text, because What's This shows
    rich text and the card shows the same string."""
    return f"{theme.heading(title)}<br>{body}"


def panel_help() -> dict[str, str]:
    """Each panel's card, by the dock's object name."""
    return {
        "dockParts": card(
            t("Library"),
            t("Every part you can add. Drag one onto the circuit or the board, or pick it and "
              "click where it goes. The filter finds a part by name, value or package."),
        ),
        "dockPartList": card(
            t("Parts"),
            t("What is in this design, with values: the list to buy from. Click one to find it "
              "on the board or the sheet."),
        ),
        "dockNets": card(
            t("Nets"),
            t("A net is a group of pins that must all be joined, like GND or +5V. The last "
              "column counts the connections in it still to wire; double-click a net to wire "
              "just that one."),
        ),
        "dockDrc": card(
            t("Problems"),
            t("What the three checks found. The circuit check (ERC) looks at the circuit "
              "itself, the board check (DRC) at whether the board can be built, and Matches "
              "circuit (LVS) at whether the copper joins what the circuit says. Click a row "
              "to see it on the board."),
        ),
        "dockBoard": card(
            t("Board"),
            t("The board from the parts side (Ctrl+1). Flip shows the solder side, where the "
              "traces and bare wires are. A hole is named like C7: column letter, row number."),
        ),
        "dockSchematic": card(
            t("Schematic"),
            t("The circuit as a drawing (Ctrl+2): the parts, and what connects to what. "
              "Clicking a symbol selects the same part on the board."),
        ),
        "dock3d": card(
            t("3D"),
            t("The board as it will look, parts and all (Ctrl+3). Drag to turn it: it is the "
              "quickest way to see a part that stands too tall or too close."),
        ),
        "dockGuide": card(
            t("Build Guide"),
            t("The soldering order, one step at a time: lowest parts first, ICs last. Tick a "
              "step as you finish it and the next one lights up on the board and in 3D."),
        ),
        "workflowNext": card(
            t("The next step"),
            t("Always the one thing to do next, from drawing the circuit to opening the build "
              "guide. Pressing it is the whole workflow; the menus hold the same commands."),
        ),
    }


def tool_help() -> dict[str, str]:
    """Each tool's card, by the window's attribute (``act_draw`` kinds as ``draw:<kind>``)."""
    return {
        "draw:solder-trace": card(
            t("Solder trace"),
            t("A line of solder joining neighbouring pads on the underside. It only goes "
              "straight from pad to pad: solder bridges the 0.6 mm gap to the next pad, not "
              "the 1.7 mm diagonal one."),
        ),
        "draw:solder-trace-wired": card(
            t("Reinforced solder trace"),
            t("Solder over a bare wire laid along the pads: about ten times less resistance, "
              "and long runs stop lifting pads. For power and ground."),
        ),
        "draw:bare-wire": card(
            t("Bare wire"),
            t("Uninsulated wire on the underside, soldered at its two ends. It may not cross "
              "other copper."),
        ),
        "draw:insulated-wire": card(
            t("Insulated wire"),
            t("Wire with insulation, on the underside. It can cross anything; stripping its "
              "ends is the cost."),
        ),
        "draw:top-jumper": card(
            t("Jumper over the parts"),
            t("An insulated wire on the parts' side, hopping over everything below. It takes "
              "room a part would use, so no part may stand on it."),
        ),
        "act_connect": card(
            t("Connect"),
            t("Click a pin, then the pin it joins. They become one net: the one either pin is "
              "on already, or a new one."),
        ),
        "act_autoroute": card(
            t("Auto-wire"),
            t("Lays solder traces, wires and jumpers for every connection still missing, in "
              "the style chosen under Wiring. It only adds: after moving parts, Redo All "
              "Wiring starts again from nothing."),
        ),
        "act_autoplace": card(
            t("Rearrange"),
            t("Moves the unlocked parts so their connections get shorter and more of them can "
              "be solder traces. It shows the result before applying it."),
        ),
        "act_ratsnest": card(
            t("Missing connections"),
            t("Dashed lines between pins the circuit joins and the board does not yet — "
              "KiCad calls them the ratsnest. They go as the wiring is laid."),
        ),
        "act_flip": card(
            t("Flip"),
            t("Turns the board over to the solder side and back, mirrored exactly as it is "
              "with the board in your hand."),
        ),
    }


def glossary() -> list[tuple[str, str]]:
    """The words the window and the guide lean on, said once each, in the window's language."""
    return [
        (t("Net"), t("A group of pins that must all be joined: GND, +5V, OUT.")),
        (t("Pin (leg)"), t("A part's leg, numbered as its datasheet numbers it.")),
        (t("Pad"), t("The copper ring round a hole, where a joint is soldered.")),
        (t("Hole address"), t("A hole named by its column letter and row number, like C7.")),
        (t("Package"), t("A part's body and leg spacing: TO-220, DIP-8, a 5 mm LED.")),
        (t("Reference"), t("A part's short name on the board and in the guide: R1, C3, U2.")),
        (t("Value"), t("What to buy: 10k, 100nF, NE555.")),
        (t("Solder trace"), t("A line of solder joining neighbouring pads, straight steps only.")),
        (t("Reinforced solder trace"), t("A solder trace laid over a bare wire, for power and ground.")),
        (t("Bare wire"), t("Uninsulated wire on the underside. It may not cross other copper.")),
        (t("Insulated wire"), t("Wire with insulation, on the underside. It may cross anything.")),
        (t("Jumper"), t("An insulated wire on the parts' side, over everything below.")),
        (t("Bent leg"), t("A part's own leg folded to a nearby hole: the cheapest connection.")),
        (t("Parts side"), t("The side the parts stand on.")),
        (t("Solder side"), t("The side the joints, traces and bare wires are on.")),
        (t("Stripboard"), t("A board whose rows are joined strips of copper, cut where they must stop.")),
        (t("Breadboard"), t("A plug-in board for trying a circuit with no solder.")),
        (t("Rail"), t("A long run for power or ground; on a breadboard, the edge rows.")),
        (t("Circuit check (ERC)"), t("Checks the circuit itself — power, polarity, pins left open — before any board.")),
        (t("Board check (DRC)"), t("Checks the board can be built: nothing overlaps, sits too close or hangs off the edge.")),
        (t("Matches circuit (LVS)"), t("Checks the copper joins exactly what the circuit says: nothing missing, nothing extra.")),
        (t("Missing connections"), t("Pins the circuit joins and the board does not yet, drawn as dashed lines (the ratsnest).")),
        (t("Netlist"), t("A circuit as a list of parts and what connects to what; KiCad writes one as a .net file.")),
        (t("Phenolic"), t("The brown paper-based board. Its pads lift easily, so the guide solders it cooler.")),
    ]


def install(window: QWidget, actions: Callable[[str], QAction | None]) -> None:
    """Hang every help text on the window: panels by their dock's object name, tools by
    the name ``actions`` resolves. A name the window does not have is skipped -- a panel
    a layout has removed has no help to show, and that is not an error."""
    for name, text in panel_help().items():
        target = window.findChild(QDockWidget, name)
        if target is not None:
            target.setWhatsThis(text)
            if target.widget() is not None:
                target.widget().setWhatsThis(text)
            continue
        widget = window.findChild(QWidget, name)
        if widget is not None:
            widget.setWhatsThis(text)
    for name, text in tool_help().items():
        action = actions(name)
        if action is not None:
            action.setWhatsThis(text)


def help_at(point: QPoint) -> str:
    """The help text for what is at ``point`` (global)."""
    return help_for(QApplication.widgetAt(point), point)


def help_for(widget: QWidget | None, point: QPoint) -> str:
    """The help text for ``widget`` under the pointer at ``point``: the action under the
    pointer on a tool bar, else the nearest widget, going outwards, that has one."""
    while widget is not None:
        if isinstance(widget, QToolBar):
            action = widget.actionAt(widget.mapFromGlobal(point))
            if action is not None and action.whatsThis():
                return action.whatsThis()
        if isinstance(widget, QToolButton) and widget.defaultAction() is not None:
            text = widget.defaultAction().whatsThis()
            if text:
                return text
        if widget.whatsThis():
            return widget.whatsThis()
        widget = widget.parentWidget()
    return ""


def general_help() -> str:
    """The card when the pointer is over nothing that has one."""
    return card(
        t("Help"),
        t("Point at a panel or a tool and press F1 to read what it is. Shift+F1 lets you "
          "click on anything instead. Help ▸ Glossary explains the words; Ctrl+/ lists the "
          "keyboard shortcuts."),
    )


class HelpCard(QFrame):
    """The F1 card: a small raised panel by the pointer, gone with Esc or a click elsewhere."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("helpCard")
        theme.variant(self, "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([theme.SPACE["lg"]] * 4))
        layout.setSpacing(theme.SPACE["sm"])
        self.text = QLabel(text)
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setMinimumWidth(320)
        self.text.setMaximumWidth(420)
        layout.addWidget(self.text)
        foot = QLabel(t("Help ▸ Glossary explains the words. Ctrl+/ lists the shortcuts."))
        foot.setWordWrap(True)
        theme.tone(foot, "tertiary")
        theme.size(foot, theme.CAPTION_PX)
        layout.addWidget(foot)

    def show_near(self, point: QPoint) -> None:
        self.adjustSize()
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(point.x() + 16, area.right() - self.width())
        y = min(point.y() + 16, area.bottom() - self.height())
        self.move(max(area.left(), x), max(area.top(), y))
        self.show()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F1):
            self.close()
            return
        super().keyPressEvent(event)


def show_card(parent: QWidget) -> HelpCard:
    """F1: the card for what is under the pointer, or the general one."""
    point = QCursor.pos()
    help_card = HelpCard(help_at(point) or general_help(), parent)
    help_card.show_near(point)
    return help_card


class GlossaryDialog(QDialog):
    """Help ▸ Glossary: every word, searchable, in the window's language."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Glossary"))
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(t("Find a word…"))
        self.filter.setClearButtonEnabled(True)
        layout.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([t("Word"), t("What it means")])
        self.tree.setRootIsDecorated(False)
        self.tree.setWordWrap(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for word, meaning in glossary():
            item = QTreeWidgetItem([word, meaning])
            item.setToolTip(1, meaning)
            self.tree.addTopLevelItem(item)
        layout.addWidget(self.tree, 1)
        self.filter.textChanged.connect(self._filter)

    def _filter(self, text: str) -> None:
        needle = text.casefold().strip()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item is None:
                continue
            words = f"{item.text(0)} {item.text(1)}".casefold()
            item.setHidden(bool(needle) and needle not in words)
