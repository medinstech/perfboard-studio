"""What an empty panel says: one pattern, so every one says it the same way.

A PANEL WITH NOTHING IN IT LOOKED BROKEN. The Nets panel was four column headings over
grey, the Part List the same, the guide said nothing until its Next button was pressed,
and the sheet's only word was a status line above an empty canvas. Somebody new could not
tell an empty panel from one that had failed to load, and nothing said how the panel would
come to have something in it.

THE PATTERN: a title, at most two lines, at most ONE button, and dim links for any other
door. The title says what will be here; the lines say how it gets here; the button, when
there is one, does the step that fills the panel -- the same command, under the same name,
as the next button at the top of the window, so a panel and the header never offer two
different ways to do one thing.

``EmptyOverlay`` lays an ``EmptyState`` over a widget and shows it exactly while that widget
has nothing to show. Over a list or a tree it follows the model's own signals, so a panel
never has to remember to say it is empty; over anything else the owner calls ``refresh``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme


class EmptyState(QWidget):
    """A title, a line or two, at most one button and a few links, centred."""

    def __init__(
        self,
        title: str,
        body: str,
        button: tuple[str, Callable[[], object]] | None = None,
        links: Sequence[tuple[str, Callable[[], object]]] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("emptyState")
        # Opaque, in the colour of what it covers: a guide with no part steps still has
        # its closing checks in the tree, and words drawn over rows are read as neither.
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([theme.SPACE["xl"]] * 4))
        layout.setSpacing(theme.SPACE["sm"])
        layout.addStretch(1)
        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        theme.size(self.title, theme.LEAD_PX)
        self.body = QLabel(body)
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setWordWrap(True)
        theme.tone(self.body, "secondary")
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        self.button: QPushButton | None = None
        if button is not None:
            label, action = button
            self.button = QPushButton(label)
            theme.variant(self.button, "primary")
            # Bound now: the links below reuse the name ``action``.
            self.button.clicked.connect(lambda _checked=False, a=action: a())
            layout.addSpacing(theme.SPACE["xs"])
            layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.links: list[QPushButton] = []
        if links:
            row = QHBoxLayout()
            row.addStretch(1)
            for label, action in links:
                link = QPushButton(label)
                theme.variant(link, "link")
                link.clicked.connect(lambda _checked=False, a=action: a())
                row.addWidget(link)
                self.links.append(link)
            row.addStretch(1)
            layout.addLayout(row)
        layout.addStretch(1)

    def say(self, title: str, body: str, button_shown: bool = True) -> None:
        """Change the words, for a panel whose emptiness has more than one cause."""
        self.title.setText(title)
        self.body.setText(body)
        if self.button is not None:
            self.button.setVisible(button_shown)


class EmptyOverlay(QObject):
    """Shows ``state`` over ``cover`` while ``is_empty()`` says there is nothing to show."""

    def __init__(self, cover: QWidget, state: EmptyState, is_empty: Callable[[], bool]) -> None:
        super().__init__(cover)
        self._cover = cover
        self._is_empty = is_empty
        self.state = state
        state.setParent(cover)
        cover.installEventFilter(self)
        self.refresh()

    @classmethod
    def over_view(cls, view: QAbstractItemView, state: EmptyState) -> EmptyOverlay:
        """Over a list or tree: empty while its model has no rows, kept up by the model."""
        model = view.model()
        overlay = cls(view.viewport(), state, lambda: model.rowCount() == 0)
        for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.layoutChanged):
            signal.connect(overlay.refresh)
        return overlay

    def refresh(self, *_args: object) -> None:
        empty = self._is_empty()
        self.state.setVisible(empty)
        if empty:
            self.state.setGeometry(self._cover.rect())
            self.state.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and self.state.isVisible():
            self.state.setGeometry(self._cover.rect())
        return False
