"""What moved in 0.23: a card for somebody who knew the window before it.

0.23 REARRANGED THE WINDOW. The menus went behind ☰, Board Setup into the board designer,
the part dialogs into Properties, the toolbar onto the canvas, and Autoroute became
Auto-wire. Somebody who knew 0.22 opens 0.23 and hunts for every one of them; somebody new
has nothing to unlearn. So the card is shown once, and only to the first: a short list of
old place → new place, each a link that shows the new place, and one button that puts it
away for good. Help ▸ What Moved in 0.23 brings it back.

WHO UPGRADED is read off the settings, because nothing else outlives a version: 0.23 is the
first to write the version that last ran (``LAST_VERSION_KEY``, as it closes), so a store with no version
in it and something an older window did write -- its geometry, a recent file, a part
placed -- is somebody upgrading, and an empty store is somebody new (``upgraded_from_before``).

NOT A BOX. It floats over the window like the tour's bubble and takes no keyboard: a modal
question on the first start of a new version is the thing people dismiss unread.
"""

from __future__ import annotations

import html
from collections.abc import Iterable

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from perfboard_studio.version import __version__

from . import theme
from .i18n import t

#: The version that last ran, written as the window closes, from 0.23 on.
LAST_VERSION_KEY = "session/lastVersion"
#: Whether this card has been shown: once, ever, for the 0.23 move.
MOVED_SHOWN_KEY = "whatsNew/moved023Shown"
#: The version the card is about: a store last run below it is an upgrade.
MOVED_IN = (0, 23)


def _minor(version: str) -> tuple[int, int] | None:
    """``(major, minor)`` of a version string, dev suffix and all; None for nonsense."""
    try:
        major, minor = version.split(".dev")[0].split(".")[:2]
        return int(major), int(minor)
    except ValueError:
        return None


def upgraded_from_before(
    settings: QSettings, used: Iterable[str], before: tuple[int, int] = MOVED_IN
) -> bool:
    """Whether the window last ran as a version below ``before``.

    A store with a version in it says so directly. One with none was written by 0.22 or
    earlier, which never wrote one -- if it was written at all: ``used`` are keys an older
    window leaves behind once somebody has worked in it, and a store with none of them is a
    first start."""
    last = settings.value(LAST_VERSION_KEY)
    if isinstance(last, str) and last:
        said = _minor(last)
        return said is not None and said < before
    return any(settings.contains(key) for key in used)


def note_this_version(settings: QSettings) -> None:
    settings.setValue(LAST_VERSION_KEY, __version__)


#: The rows, in the order somebody hunts for them: what it was called, where it is now.
MOVES = (
    "design-board",
    "properties",
    "tools",
    "auto-wire",
    "menus",
    "search",
)


def move_text(key: str) -> str:
    """One row's words. Each is its own ``t()`` call, for the catalogue's scanner."""
    if key == "design-board":
        return t("Board Setup… → Board ▸ Design the Board…")
    if key == "properties":
        return t("Part Properties → Properties, always open on the right")
    if key == "tools":
        return t("The toolbar → tools inside the Board panel")
    if key == "auto-wire":
        return t("Route ▸ Autoroute All Nets → Wiring ▸ Auto-wire Everything")
    if key == "menus":
        return t("The menu bar → ☰ at the top left, or Alt")
    return t("A command you can't find → Ctrl+K, by its name")


class MovedCard(QFrame):
    """The card: a title, a line, a link for each move, and the button that puts it away.

    It says which move was picked (``picked``) and that it was put away (``dismissed``);
    the window shows the place and remembers."""

    picked = Signal(str)
    dismissed = Signal()

    WIDTH = 380

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("movedCard")
        theme.variant(self, "card")
        theme.elevate(self)
        self.setFixedWidth(self.WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([theme.SPACE["lg"]] * 4))
        layout.setSpacing(theme.SPACE["sm"])
        self.title = QLabel(t("What moved in 0.23"))
        theme.size(self.title, theme.LEAD_PX)
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        layout.addWidget(self.title)
        self.intro = QLabel(t("The window is new. Click a line to see where it went."))
        self.intro.setWordWrap(True)
        theme.tone(self.intro, "secondary")
        layout.addWidget(self.intro)
        # Links in labels rather than link buttons: a button's words cannot wrap, and the
        # Turkish Route row ran off the card's edge.
        self.rows: dict[str, QLabel] = {}
        for key in MOVES:
            row = QLabel(f'<a href="{key}">{html.escape(move_text(key))}</a>')
            row.setTextFormat(Qt.TextFormat.RichText)
            row.setWordWrap(True)
            row.setOpenExternalLinks(False)
            row.linkActivated.connect(self.picked.emit)
            layout.addWidget(row)
            self.rows[key] = row
        layout.addSpacing(theme.SPACE["xs"])
        self.done = QPushButton(t("Got It"))
        theme.variant(self.done, "primary")
        self.done.clicked.connect(lambda _checked=False: self.dismissed.emit())
        layout.addWidget(self.done, 0, Qt.AlignmentFlag.AlignRight)
        self.adjustSize()
