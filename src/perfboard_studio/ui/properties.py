"""The Properties panel: the shell on the right that shows whatever is selected.

ALWAYS OPEN, AND NEVER EMPTY. A part's value, its package, where pin 1 sits and which way it
turns were a modal dialog (F2) -- open it, change one thing, close it, see what happened --
and a board's size another. Here the selection's properties stand beside the board the whole
time, and with nothing selected the board itself is the selection, so the panel always has
something to say.

THE SHELL IS THIS FILE; THE CONTENT IS NOT. What a part, a net, a conductor or the board
offers to edit is the inspector's (``ui/inspector.py``), one editor per kind of selection,
written to the window's commands. This panel holds it in a scroll area under its caption, and
hands it the two things it needs: the selection, every time it changes (``set_selection``),
and the document, after every command (``refresh``). Until an inspector is put in
(``set_content``), a summary stands in: what is selected, said in one line.
"""

from __future__ import annotations

from html import escape
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from perfboard_studio.model import PerfDocument

from . import theme
from .i18n import t
from .selection import NOTHING, Selection

#: How wide the panel opens, in logical pixels: room for a label and a field side by side.
PANEL_WIDTH = 300


class PropertiesContent(Protocol):
    """What the panel hosts: a widget that shows a selection out of a document."""

    def set_selection(self, selection: Selection) -> None: ...

    def refresh(self, document: PerfDocument) -> None: ...


class _Summary(QWidget):
    """The stand-in content: the selection, said in one line, until an inspector is put in."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.line = QLabel()
        self.line.setWordWrap(True)
        theme.tone(self.line, "secondary")
        layout.addWidget(self.title)
        layout.addWidget(self.line)
        layout.addStretch(1)
        self._selection = NOTHING
        self._document: PerfDocument | None = None

    def set_selection(self, selection: Selection) -> None:
        self._selection = selection
        self._say()

    def refresh(self, document: PerfDocument) -> None:
        self._document = document
        self._say()

    def _say(self) -> None:
        document, selection = self._document, self._selection
        if document is None:
            return
        title, line = describe(selection, document)
        self.title.setText(theme.heading(escape(title)))
        self.line.setText(line)


def describe(selection: Selection, document: PerfDocument) -> tuple[str, str]:
    """A selection's name and one line about it, from the document alone."""
    kind, ids = selection.kind, selection.ids
    if kind == "part" and ids:
        part = next((c for c in document.components if c.id == ids[0]), None)
        if part is not None:
            return part.ref, part.value
    if kind == "design-part" and ids:
        design = next((p for p in document.parts if p.id == ids[0]), None)
        if design is not None:
            return design.ref, t("In the design, not on the board yet.")
    if kind in ("parts", "conductors", "mixed"):
        return t("{count} selected").format(count=len(ids)), ""
    if kind == "net" and ids:
        net = next((n for n in document.nets if n.id == ids[0]), None)
        if net is not None:
            return net.name, t("{count} pins").format(count=len(net.nodes))
    if kind == "placing":
        return t("Placing a part"), t("Click the board where pin 1 goes. Esc cancels.")
    board = document.board
    return document.meta.name, t("{cols} × {rows} holes").format(cols=board.cols, rows=board.rows)


class PropertiesPanel(QWidget):
    """The caption, and the content in a scroll area under it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("propertiesPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.caption = QLabel(t("Properties"))
        self.caption.setProperty("role", "caption")
        self.caption.setContentsMargins(theme.SPACE["xl"], theme.SPACE["lg"], theme.SPACE["xl"], 0)
        layout.addWidget(self.caption)
        self.scroller = QScrollArea()
        self.scroller.setWidgetResizable(True)
        self.scroller.setFrameShape(QFrame.Shape.NoFrame)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self._holder = QVBoxLayout(holder)
        # The content draws no outer margins of its own: these are the panel's.
        self._holder.setContentsMargins(
            theme.SPACE["xl"], theme.SPACE["md"], theme.SPACE["xl"], theme.SPACE["lg"]
        )
        self._holder.setSpacing(0)
        self.scroller.setWidget(holder)
        layout.addWidget(self.scroller, 1)
        self.selection = NOTHING
        self._document: PerfDocument | None = None
        self.content: QWidget = _Summary()
        self._holder.addWidget(self.content)

    def set_content(self, widget: QWidget) -> None:
        """Put the inspector in, in place of whatever was there. ``widget`` implements
        ``PropertiesContent``; it is handed the selection and the document at once."""
        self._holder.removeWidget(self.content)
        # Hidden NOW, deleted later: taken out of the layout it stays where it was drawn
        # until the event loop deletes it, and a loop that never gets round to it -- the
        # walkthrough's -- drew the first summary's "untitled · 18 × 24 holes" under every
        # editor after it, and pushed their right edges out of the panel.
        self.content.hide()
        self.content.deleteLater()
        self.content = widget
        self._holder.addWidget(widget)
        content: PropertiesContent = widget  # type: ignore[assignment]
        if self._document is not None:
            content.refresh(self._document)
        content.set_selection(self.selection)
        self._fit()

    def set_selection(self, selection: Selection) -> None:
        if selection == self.selection:
            return
        self.selection = selection
        content: PropertiesContent = self.content  # type: ignore[assignment]
        content.set_selection(selection)
        self._fit()

    def refresh(self, document: PerfDocument) -> None:
        self._document = document
        content: PropertiesContent = self.content  # type: ignore[assignment]
        content.refresh(document)
        self._fit()

    def _fit(self) -> None:
        """As wide as the editor showing needs, never narrower: a field cut off at the
        panel's right edge -- Change…, the 270° button and Delete were, at every window size
        -- is worse than a panel a few pixels wider. The editors are made to fit the width
        the panel opens at (``PANEL_WIDTH``); this is what holds when a language or a font
        makes one wider anyway."""
        margins = self._holder.contentsMargins()
        need = (
            self.content.minimumSizeHint().width()
            + margins.left()
            + margins.right()
            + 2 * self.scroller.frameWidth()
        )
        self.scroller.setMinimumWidth(max(0, need))
