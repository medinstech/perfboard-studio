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

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction, QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from . import icons, theme
from .i18n import t
from .workflow import WorkflowBar

#: The header's height, in logical pixels: one row, the step dots and the next button
#: with a little air round them.
HEADER_HEIGHT = 46


class HeaderBar(QWidget):
    """☰ · the board's name · whether it is saved · the steps · undo, redo · next."""

    #: The update pill was clicked: the window opens the release's notes, with the one
    #: action that is possible right now (download, or install and restart).
    updateRequested = Signal()
    #: The house left of the board's name: Home, with the board left open behind it.
    homeRequested = Signal()

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
        # What the window last said, kept so that leaving Home says it again (``set_home``).
        self._on_home = False
        self._modified = False
        self._version: str | None = None
        #: What ☰ opens over Home, if the window gives one (``set_home``).
        self.home_menu: QMenu | None = None

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

        # The way back to Home once a board is open, as the first step of a path to the
        # board's name: "Home › ATmega328 Relay Board". Home came up at a start and never
        # again -- the dev3 sitting opened a board and found no way back to the page with
        # the others on it short of closing the window. In words, not a house alone: the
        # same sitting looked past an icon for something it wanted (the far side's copper).
        self.home_button = QToolButton()
        self.home_button.setObjectName("headerHome")
        self.home_button.setIcon(icons.icon("home"))
        self.home_button.setIconSize(QSize(icons.SIZE - 2, icons.SIZE - 2))
        self.home_button.setText(t("Home"))
        self.home_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.home_button.setAutoRaise(True)
        self.home_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.home_button.setToolTip(
            t("Home: your boards and the examples. This board stays open (Alt+Home).")
        )
        self.home_button.clicked.connect(self.homeRequested)
        layout.addWidget(self.home_button)
        self.crumb = QLabel("›")
        self.crumb.setObjectName("headerPlace")
        layout.addWidget(self.crumb)

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
        # Over Home the steps go, and this holds the search to the right instead.
        self.gap = QWidget()
        self.gap.setObjectName("headerGap")
        self.gap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.gap.hide()
        layout.addWidget(self.gap, 1)

        # A newer release exists. Beside the search because that is where the eye is while
        # working; hidden until the window says so (``set_update``).
        self.update_pill = QPushButton()
        self.update_pill.setObjectName("headerUpdate")
        self.update_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_pill.clicked.connect(self.updateRequested)
        self.update_pill.hide()
        layout.addWidget(self.update_pill)

        # The way to every command by its name (``ui/palette.py``), where a person looks
        # for a search field: in the header, saying its key.
        self._search_words = t("Search or run a command…")
        self.search = QPushButton(icons.icon("search"), self._search_words)
        self.search.setObjectName("headerSearch")
        self._fitting = False
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

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_search()

    def _fit_search(self) -> None:
        """The search's words go before the current step's name does.

        The step bar sheds its words as the header narrows (``WorkflowBar._fit``), and its
        last is the name of the step you are on -- the only place the bar says where you
        are. With Home › before the board's name, a 1366 px window in Turkish lost "Montaj"
        while the search still said "Komut arayın ya da çalıştırın…" across 230 px. Below
        that width the search is the magnifier alone; Ctrl+K and its tooltip still say it.
        """
        if self._fitting or self._on_home:
            return
        layout = self.layout()
        if layout is None:
            return
        self._fitting = True
        try:
            self._narrow_search(False)
            layout.setGeometry(self.rect())
            if self.steps.fit_mode == "tiny":
                self._narrow_search(True)
                layout.setGeometry(self.rect())
        finally:
            self._fitting = False

    def _narrow_search(self, narrow: bool) -> None:
        if bool(self.search.property("narrow")) == narrow:
            return
        self.search.setText("" if narrow else self._search_words)
        self.search.setProperty("narrow", narrow)
        theme.restyle(self.search)

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
        self.place.setVisible(bool(place) and not self._on_home)
        self._modified = modified
        self.unsaved.setVisible(modified and not self._on_home)
        # A longer name, "Not saved" or a board's place take room from the steps.
        self._fit_search()

    def set_update(self, version: str | None) -> None:
        """The pill for release ``version``, or none (``None``: nothing newer, or hidden)."""
        self._version = version
        if version is None:
            self.update_pill.hide()
            return
        self.update_pill.setText("●  " + t("Update {version}").format(version=version))
        self.update_pill.setToolTip(
            t("Perfboard Studio {version} is available. Click to read what changed.").format(
                version=version
            )
        )
        self.update_pill.setVisible(not self._on_home)

    def set_home(self, on: bool) -> None:
        """Over Home, ☰ and the search stay where they are over the board, and nothing about
        a board does: no name, steps, undo or next step, since Home is not a board. The pill
        stands down too, because Home's own card says the release.

        Home used to take the whole header away, and with it every menu: Check for Updates
        could only be reached by opening an example first (the release-candidate sitting)."""
        self._on_home = on
        for widget in (self.home_button, self.crumb, self.title, self.steps,
                       self.undo_button, self.redo_button, self.steps.next_button):
            widget.setVisible(not on)
        self.gap.setVisible(on)
        self.place.setVisible(bool(self.place.text()) and not on)
        self.unsaved.setVisible(self._modified and not on)
        self.update_pill.setVisible(self._version is not None and not on)
        # Over Home the steps are gone and the search has the room; off it, it fits again.
        if on:
            self._narrow_search(False)
        else:
            self._fit_search()

    def open_menu(self, menu: QMenu | None = None) -> QMenu:
        """Every menu under ☰ -- or one of them, opened straight away, for Alt+its letter
        -- dropped from the ☰ button, which is where a person looks for them. Over Home,
        ☰ is ``home_menu``."""
        if menu is not None:
            shown = menu
        elif self._on_home and self.home_menu is not None:
            shown = self.home_menu
        else:
            shown = self.app_menu
        corner = self.menu_button.mapToGlobal(QPoint(0, self.menu_button.height()))
        shown.popup(corner)
        return shown
