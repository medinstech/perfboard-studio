"""Who makes it: the Medinstech mark and name, in Home's corner and in About, a link home.

ONE PICTURE PER THEME, BAKED. The lockup (the mark and the wordmark side by side) is a
file per place and theme in ``assets/``, at 1x and 2x, rather than one drawing tinted at
run time: the dark one is not the light one recoloured but a white mark whose figure is
let through at 28%, the one picked from four rendered candidates, and the light one is the
blue lockup as it is printed. Home's is a size smaller and a shade quieter than About's.

The files are the company's trademark, not Apache-licensed code (NOTICE, "Trademarks"):
they are here so the application can say who makes it, and that is all they are for.

LAZY. Home is on screen at a blank start, and a start is paid for in breadth
(docs/ARCHITECTURE.md): the button takes its size at once, so nothing moves when the
picture arrives, and reads its files on the event loop's first turn after it is shown.

THE THEME IS READ FROM THE APPLICATION'S PALETTE, not from ``theme.ACTIVE``: ``theme.apply``
sets it, and a change to it swaps the picture, so it cannot be left showing the blue lockup
on a dark panel. Not the button's own palette: the stylesheet polishes that, and a
transparent button's says nothing about the panel under it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPalette, QShowEvent
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

from .i18n import t

#: Where a click goes.
URL = "https://www.medinstech.com"

ASSETS = Path(__file__).resolve().parent / "assets"

type Place = Literal["home", "about"]

#: The lockup's size in logical pixels, per place: the files are exactly this at 1x.
SIZES: dict[Place, QSize] = {"home": QSize(114, 18), "about": QSize(133, 22)}


def asset_paths(place: Place, dark: bool) -> tuple[Path, Path]:
    """The 1x and 2x files of one lockup."""
    stem = f"medinstech-{place}-{'dark' if dark else 'light'}"
    return ASSETS / f"{stem}.png", ASSETS / f"{stem}@2x.png"


def is_dark(palette: QPalette) -> bool:
    """A dark surface is one whose window colour is closer to black than to white."""
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def open_home_page() -> None:
    QDesktopServices.openUrl(QUrl(URL))


class BrandLink(QToolButton):
    """The lockup as a flat button: a pointing hand over it, and a click opens the site."""

    def __init__(self, place: Place, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("brandLink")
        self._place: Place = place
        #: Which theme's picture is showing, once one is; None until it is loaded.
        self._shown_dark: bool | None = None
        size = SIZES[place]
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip(t("Open www.medinstech.com"))
        self.setAccessibleName("Medinstech")
        self.setIconSize(size)
        self.setFixedSize(size.width() + 6, size.height() + 4)
        self.setStyleSheet(
            "QToolButton#brandLink { background: transparent; border: none; padding: 0px; }"
        )
        self.clicked.connect(open_home_page)

    @property
    def loaded(self) -> bool:
        return self._shown_dark is not None

    @property
    def shows_dark(self) -> bool | None:
        """True for the dark theme's picture, False for the light one's, None before."""
        return self._shown_dark

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self.loaded:
            QTimer.singleShot(0, self.load)

    def load(self) -> None:
        """Show the picture for the palette in force now, if it is not showing already."""
        dark = is_dark(QApplication.palette())
        if self._shown_dark is dark:
            return
        icon = QIcon()
        for path in asset_paths(self._place, dark):
            if path.exists():
                icon.addFile(str(path))
        self.setIcon(icon)
        self._shown_dark = dark

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        changed = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)
        if event.type() in changed and self.loaded:
            self.load()
