"""The window's one row of chrome: the menus, what is open and whether it is saved, the six
steps, undo and redo, and the button that does the next step.

THREE ROWS BECAME ONE. Above the board there were a menu bar, a toolbar of twenty-two
buttons and a step bar under it -- about 150 px of chrome, all of it the same grey and all of
it saying everything at once. What a person needs on screen all the time is shorter: where
the board stands and what to do next, and a way back from a mistake. Everything else is a
menu away, and every menu is behind the one button at the left (Alt still opens them by
letter, and Ctrl+K finds any command by name).

This is a QWidget laid into a toolbar row, as the step bar was (see "The window walks
through six steps" in docs/ARCHITECTURE.md for why a row and not a dock), and it imports
nothing of the window: the window hands it the menus, the actions and the step bar.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from . import icons
from .i18n import t
from .workflow import WorkflowBar

#: The header's height, in logical pixels: one row, the step dots and the next button
#: with a little air round them.
HEADER_HEIGHT = 46


class HeaderBar(QWidget):
    """☰ · the board's name · whether it is saved · the steps · undo, redo · next."""

    def __init__(
        self,
        steps: WorkflowBar,
        menus: Sequence[QMenu],
        *,
        undo: QAction,
        redo: QAction,
        save: QAction,
        search: QAction,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("header")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(HEADER_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 10, 0)
        layout.setSpacing(6)

        #: Every menu of the window, as submenus of one. The menu bar still holds them --
        #: it is kept, at no height, because it is what makes Alt+F open File -- and an
        #: action may sit in two menus at once.
        self.app_menu = QMenu(self)
        for menu in menus:
            self.app_menu.addMenu(menu)
        self.menu_button = QToolButton()
        self.menu_button.setObjectName("headerMenu")
        self.menu_button.setIcon(icons.icon("menu"))
        self.menu_button.setIconSize(QSize(icons.SIZE, icons.SIZE))
        self.menu_button.setAutoRaise(True)
        self.menu_button.setToolTip(t("Menus: File, Edit, View and the rest. Alt opens them too."))
        self.menu_button.clicked.connect(lambda: self.open_menu())
        layout.addWidget(self.menu_button)

        self.title = QLabel()
        self.title.setObjectName("headerTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title)
        # Which of several boards is in front, or System: the document's name stays the
        # title, and this says where in it the window is. Hidden on a board of one.
        self.place = QLabel()
        self.place.setObjectName("headerPlace")
        self.place.setTextFormat(Qt.TextFormat.PlainText)
        self.place.hide()
        layout.addWidget(self.place)
        # Not saved, said where the name is, and one click from being saved: the title
        # bar's bullet said it too, in a place nobody looks while working.
        self.unsaved = QToolButton()
        self.unsaved.setObjectName("headerUnsaved")
        self.unsaved.setText(t("Not saved"))
        self.unsaved.setToolTip(t("Save the board (Ctrl+S)."))
        self.unsaved.setAutoRaise(True)
        self.unsaved.setCursor(Qt.CursorShape.PointingHandCursor)
        self.unsaved.clicked.connect(save.trigger)
        self.unsaved.hide()
        layout.addWidget(self.unsaved)

        self.steps = steps
        layout.addWidget(steps, 1)

        # The way to every command by its name (``ui/palette.py``), where a person looks
        # for a search field: in the header, saying its key.
        self.search = QPushButton(icons.icon("search"), t("Search or run a command…"))
        self.search.setObjectName("headerSearch")
        self.search.setToolTip(t("Every command by its name, and any part or net (Ctrl+K)."))
        self.search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search.clicked.connect(search.trigger)
        layout.addWidget(self.search)

        self.undo_button = self._action_button(undo, "undo")
        self.redo_button = self._action_button(redo, "redo")
        layout.addWidget(self.undo_button)
        layout.addWidget(self.redo_button)
        layout.addSpacing(4)
        layout.addWidget(steps.next_button)

        # Styled by name in the one sheet (``theme.stylesheet``): #header, #headerTitle,
        # #headerUnsaved, and the steps as #workflowBar's buttons by their status.

    def minimumSizeHint(self) -> QSize:
        # Claims no width: a toolbar hides a widget that does not fit, and the steps shed
        # their words to fit instead (``WorkflowBar._fit``).
        return QSize(0, HEADER_HEIGHT)

    @staticmethod
    def _action_button(action: QAction, picture: str) -> QToolButton:
        button = QToolButton()
        button.setDefaultAction(action)
        button.setIcon(icons.icon(picture))
        button.setIconSize(QSize(icons.SIZE - 2, icons.SIZE - 2))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAutoRaise(True)
        return button

    def set_document(self, name: str, *, modified: bool, place: str | None = None) -> None:
        """The board's name, and whether what is on screen is what is on disk; ``place``,
        which of several boards is in front, or System."""
        self.title.setText(name)
        self.place.setText(f"›  {place}" if place else "")
        self.place.setVisible(bool(place))
        self.unsaved.setVisible(modified)

    def open_menu(self, menu: QMenu | None = None) -> QMenu:
        """Every menu under ☰ -- or one of them, opened straight away, for Alt+its letter
        -- dropped from the ☰ button, which is where a person looks for them."""
        shown = menu if menu is not None else self.app_menu
        corner = self.menu_button.mapToGlobal(QPoint(0, self.menu_button.height()))
        shown.popup(corner)
        return shown
