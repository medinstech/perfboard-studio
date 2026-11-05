"""The strip at the top of the Board panel: the system, then each board, and a way to add one.

Shown only when the document has more than one board, so a single-board window does not
change by a pixel; adding the second board is in the Board menu and the palette until then.
Its own row inside the Board panel rather than beside the step bar, whose fit is chosen from
the width it is given (``workflow.WorkflowBar._fit``). The entry in front is underlined in
the accent, as the view tabs are. See "Several boards are one document, and each is seen
alone" in docs/ARCHITECTURE.md.

Imports nothing of the window: the window hands it the entries and listens to what is picked.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QTabBar, QToolButton, QWidget

from . import theme
from .i18n import t

#: The strip's own id for its first entry, which is not a board.
SYSTEM_ENTRY = "system"


class BoardStrip(QWidget):
    """``System | Controller · 6 x 8 cm | Supply · 3 x 7 cm`` and ``+ Add Board``."""

    #: A board's id, or :data:`SYSTEM_ENTRY`.
    picked = Signal(str)
    add_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("boardStrip")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 8, 0)
        row.setSpacing(4)
        self.tabs = QTabBar(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        tokens = theme.ACTIVE
        self.tabs.setStyleSheet(
            f"QTabBar::tab {{ padding: 5px 12px; color: {tokens.text_secondary};"
            f" border: none; border-bottom: 2px solid transparent; }}"
            f"QTabBar::tab:selected {{ color: {tokens.text};"
            f" border-bottom: 2px solid {tokens.accent}; }}"
        )
        self.tabs.currentChanged.connect(self._on_current)
        row.addWidget(self.tabs)
        row.addStretch(1)
        self.add = QToolButton(self)
        self.add.setText(t("+ Add Board"))
        self.add.setAutoRaise(True)
        self.add.clicked.connect(self.add_requested.emit)
        row.addWidget(self.add)
        self._ids: list[str] = []
        self._filling = False

    def set_entries(self, entries: Sequence[tuple[str, str]], current: str) -> None:
        """The boards as ``(id, label)``, in order, with ``current`` in front; the System
        entry is put first here. Rebuilt only when the entries changed, so a refresh that
        renames nothing does not repaint the strip."""
        wanted = [(SYSTEM_ENTRY, t("System")), *entries]
        ids = [entry_id for entry_id, _ in wanted]
        labels = [label for _, label in wanted]
        current_labels = [self.tabs.tabText(i) for i in range(self.tabs.count())]
        self._filling = True
        try:
            if ids != self._ids or labels != current_labels:
                while self.tabs.count():
                    self.tabs.removeTab(0)
                for index, (entry_id, label) in enumerate(wanted):
                    self.tabs.addTab(label)
                    if entry_id != SYSTEM_ENTRY:
                        self.tabs.setTabToolTip(index, t("The 3D View shows the board in front."))
                self._ids = ids
            if current in self._ids:
                self.tabs.setCurrentIndex(self._ids.index(current))
        finally:
            self._filling = False

    @property
    def current(self) -> str:
        index = self.tabs.currentIndex()
        return self._ids[index] if 0 <= index < len(self._ids) else SYSTEM_ENTRY

    def _on_current(self, index: int) -> None:
        if not self._filling and 0 <= index < len(self._ids):
            self.picked.emit(self._ids[index])
