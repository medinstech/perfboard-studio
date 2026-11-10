"""What a part says about itself, as fields: its pinout, its note, and the pinout a typed
value brings. Shared by the inspector (``ui/inspector.py``) and the window's part dialogs,
because they are the same questions about the same part, and answering them two ways would
be two chances to answer them differently.
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from perfboard_studio.catalog import CatalogPart
from perfboard_studio.model import Footprint, PartSymbol, PinNames, normalized_pin_names
from perfboard_studio.parsers.kicad_parts import catalog_part_for

from . import theme
from .i18n import t


def pinout_for_retyped_value(
    footprint_id: str | None, before: str, after: str, names: Mapping[str, str]
) -> CatalogPart | None:
    """The catalog part whose pinout a value typed in place of ``before`` brings, or None.

    A value that names a catalog part in the package the part already has brings that part's
    pin names when there are none yet -- "NE555" typed onto a DIP-8 -- and ALSO when the
    names there are exactly the catalog's pinout for the value being typed over. Those names
    were never anybody's declaration: they came with the old value, and they are wrong for
    the new one. BC547 to 2N3904 on one TO-92 was the case that found it: C-B-E stayed under
    a part that is E-B-C, and nothing downstream could tell, because a pinout is the one fact
    about a transistor that only the part knows.

    Names that differ from the old value's pinout were typed by somebody, and a value is not
    allowed to overwrite a declaration (``PinoutEditor.follow_value`` says so instead).
    """
    part = catalog_part_for(after)
    if part is None or footprint_id is None or part.footprint_id != footprint_id:
        return None
    if not names:
        return part
    previous = catalog_part_for(before)
    if previous is None or previous.footprint_id != footprint_id or previous.id == part.id:
        return None
    return part if dict(names) == dict(previous.pin_names) else None


class PinTable(QTableWidget):
    """The pin names: asks for a few rows' height, and takes whatever more it is given.

    Qt's table asks for 192 px whatever it holds, and Properties is a scroll area that
    makes its content as tall as that content ASKS to be at its width -- so in a 1280 x 720
    window a resistor's editor was 19 px taller than the panel, and its Auto-wire and
    Delete row sat half under the status bar (the release walkthrough). Asking for three
    rows, the editor fits; the table still expands into the room the panel has, and a
    40-pin module's scrolls inside it rather than pushing the panel's last row away."""

    #: The rows it asks room for. A 2-pin part asks for two.
    WANTED_ROWS = 3

    def sizeHint(self) -> QSize:
        rows = min(max(self.rowCount(), 1), self.WANTED_ROWS)
        height = (
            self.horizontalHeader().sizeHint().height()
            + rows * self.verticalHeader().defaultSectionSize()
            + 2 * self.frameWidth()
        )
        return QSize(super().sizeHint().width(), height)


class PinoutEditor(QWidget):
    """What a part is and what it calls its leads -- the two things its package cannot say.

    One widget in two dialogs (a placed part's properties, and adding or editing a part on
    the sheet), because they are the same question about the same part and answering it
    two ways would be two chances to answer it differently.

    The table has a row per footprint pin, the number fixed and the name editable. A pin
    the registry already names (an LED's A and K) shows that name greyed as a hint: typing
    over it declares a name, leaving it declares nothing. Only what was typed is stored.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.symbol = QComboBox()
        # In the order a person looks for them. ``None`` is "whatever the package draws",
        # which every part is until somebody says otherwise. Each label is its own t()
        # call rather than a table read through one, because the catalogue test finds a
        # translatable string by seeing it inside t() in the source.
        choices: tuple[tuple[PartSymbol | None, str], ...] = (
            (None, t("From the package")),
            ("npn", t("NPN transistor (names B, C, E)")),
            ("pnp", t("PNP transistor (names B, C, E)")),
            ("nmos", t("N-channel MOSFET (names G, D, S)")),
            ("pmos", t("P-channel MOSFET (names G, D, S)")),
            ("zener", t("Zener diode")),
            ("fuse", t("Fuse or PTC")),
            ("potentiometer", t("Potentiometer (three leads, the middle one the wiper)")),
            ("led", t("LED (names A, K)")),
            ("battery", t("Battery (names + and -)")),
            ("jack", t("DC jack (names + and -)")),
        )
        for value, label in choices:
            self.symbol.addItem(label, value)
        self.symbol.setToolTip(
            t(
                "What this part is, when its package cannot say. A transistor symbol is "
                "drawn only once its leads are named below, because which leg is the gate "
                "is a fact about the part, not the package."
            )
        )
        self.table = PinTable(0, 2)
        self.table.setHorizontalHeaderLabels([t("Pin"), t("Name")])
        self.table.verticalHeader().setVisible(False)
        # As wide as its heading: at Qt's default width the Turkish "Pin no" was cut to "Pin nc".
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setToolTip(
            t(
                "What the datasheet calls each lead. Printed on the schematic and in the "
                "soldering guide, so a module's pin reads as GPIO21 rather than 21."
            )
        )
        # What a value typed in the dialog did to the names below, said where the names are:
        # a pinout that changes under somebody's eyes without a word is one they may not
        # notice changed (``pinout_for_retyped_value``).
        self.note = QLabel()
        self.note.setWordWrap(True)
        theme.tone(self.note, "warning")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(t("Symbol"), self.symbol)
        form.addRow(t("Pin names"), self.table)
        form.addRow("", self.note)
        form.setRowVisible(self.note, False)
        self._form = form
        self.setLayout(form)
        self._hints: dict[str, str] = {}

    def set_part(self, footprint: Footprint | None, names: PinNames, symbol: PartSymbol | None) -> None:
        """Show one part's declaration against the pins its footprint has."""
        index = self.symbol.findData(symbol)
        self.symbol.setCurrentIndex(max(index, 0))
        self.set_footprint(footprint, dict(names))

    def say(self, text: str) -> None:
        """One line under the names about where they came from, or nothing."""
        self.note.setText(text)
        self._form.setRowVisible(self.note, bool(text))

    def follow_value(self, footprint: Footprint | None, before: str, after: str) -> None:
        """Bring the catalog's pinout for a value typed over ``before``, where that is safe.

        See ``pinout_for_retyped_value`` for when it is. When it is not because somebody
        typed the names, and the catalog pins the new value differently, the names stay and
        the difference is said out loud: a BC547's C-B-E kept under "2N3904", which is E-B-C,
        is a transistor soldered in backwards.
        """
        footprint_id = footprint.id if footprint is not None else None
        names = self.names_dict()
        part = pinout_for_retyped_value(footprint_id, before, after, names)
        if part is not None and names != dict(part.pin_names):
            self.set_part(footprint, part.pin_names, part.symbol)
            self.say(t("Pin names from the catalog's {part}.").format(part=part.name))
            return
        named = catalog_part_for(after)
        if (
            named is not None
            and named.footprint_id == footprint_id
            and names
            and names != dict(named.pin_names)
        ):
            self.say(
                t("These names were typed here and are kept. The catalog's {part} is {pins}.")
                .format(part=named.name, pins=" ".join(f"{n}={name}" for n, name in named.pin_names))
            )
        else:
            self.say("")

    def set_footprint(self, footprint: Footprint | None, names: dict[str, str] | None = None) -> None:
        """Rebuild the rows for a (possibly different) footprint, keeping typed names.

        A name typed for pin 3 survives the footprint changing to one that still has a pin
        3; one for a pin the new footprint lacks is dropped rather than kept invisibly.
        """
        kept = self.names_dict() if names is None else names
        self._hints = {}
        pins = footprint.pins if footprint is not None else ()
        self.table.setRowCount(len(pins))
        self.table.updateGeometry()
        for row, pin in enumerate(pins):
            number = QTableWidgetItem(pin.number)
            number.setFlags(number.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, number)
            name = QTableWidgetItem(kept.get(pin.number, ""))
            if pin.name and pin.number not in kept:
                name.setToolTip(t("The package calls this pin {name}.").format(name=pin.name))
                self._hints[pin.number] = pin.name
            self.table.setItem(row, 1, name)
        self.table.resizeColumnToContents(0)

    def names_dict(self) -> dict[str, str]:
        found: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            number = self.table.item(row, 0)
            name = self.table.item(row, 1)
            if number is not None and name is not None and name.text().strip():
                found[number.text()] = name.text().strip()
        return found

    def values(self) -> tuple[PinNames, PartSymbol | None]:
        """``(pin names, symbol)`` as the commands take them."""
        return normalized_pin_names(self.names_dict()), self.symbol.currentData()


def note_editor(text: str) -> QPlainTextEdit:
    """A part's note: the builder's own words, a few lines tall so the dialog does not grow
    with it. Tab leaves it rather than typing a tab, as every other field in the dialog."""
    editor = QPlainTextEdit(text)
    editor.setPlaceholderText(t("Why this part is here, for whoever builds or mends it later"))
    editor.setToolTip(
        t(
            "Saved with the board, shown when the pointer rests on the part, and printed at "
            "its step in the build guide."
        )
    )
    editor.setTabChangesFocus(True)
    editor.setMaximumHeight(editor.fontMetrics().lineSpacing() * 3 + 12)
    return editor
