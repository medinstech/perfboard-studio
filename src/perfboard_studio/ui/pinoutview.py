"""A part's pinout card, in a window of its own, and the doors to it.

The card is ``pinout_export``'s page with the board view's drawing of the part in the
middle (``pinoutart``). It is painted from that SVG each time it is shown and again when the
palette changes, so it follows a theme switch. Save SVG writes the light card, for paper,
into the project's ``outputs/`` when there is one.

The doors are a right-click on a Library row or a Parts row (:func:`offer_pinout_on`) and the
link in Properties. Each asks the same question of a package and a value
(:func:`pinout_card_of`), so every part the catalogue has a card for gets one, placed or not.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..catalog import catalog_part, catalog_part_of
from ..connectivity import FootprintLookup
from ..model import PerfDocument
from ..phrasebook import GuideLanguage
from ..pinout import PinoutCard, pinout_card
from ..pinout_export import pinout_svg
from ..project import OUTPUT_DIR
from ..system import circuit_parts
from .i18n import t
from .partlist import REF
from .pinoutart import card_ink, part_art_svg


def pinout_card_of(
    footprint_id: str, value: str, lookup: FootprintLookup, *, catalog_id: str | None = None
) -> PinoutCard | None:
    """The card for the catalogue part with this package and value -- or the one named
    ``catalog_id``, as a Library row names it -- or ``None`` when there is none."""
    part = catalog_part(catalog_id) if catalog_id else catalog_part_of(footprint_id, value)
    return pinout_card(part, lookup) if part is not None else None


def card_of_part_row(
    item: QTreeWidgetItem, document: PerfDocument, lookup: FootprintLookup
) -> PinoutCard | None:
    """The card for a Parts row: a part placed on any board, or one still in the design."""
    # The Parts panel keeps the row's component or part id in its first column's user role.
    wanted = item.data(REF, Qt.ItemDataRole.UserRole)
    for part in circuit_parts(document):
        if part.id == wanted:
            return pinout_card_of(part.footprint_id, part.value, lookup)
    return None


def save_folder(document_path: Path | None) -> Path | None:
    """Where Save SVG starts: the project's ``outputs/`` when the board has one, else the
    board's own folder, else wherever the dialog would."""
    if document_path is None:
        return None
    outputs = document_path.parent / OUTPUT_DIR
    return outputs if outputs.is_dir() else document_path.parent


class _CardView(QWidget):
    """The card, painted from its SVG at its own size; made again when the palette is."""

    def __init__(
        self, card: PinoutCard, art: str | None, language: GuideLanguage,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._card = card
        self._art = art
        self._language = language
        self._renderer = QSvgRenderer(self)
        self._load()

    def svg(self) -> str:
        """The card as shown: in the window's colours, read now."""
        return pinout_svg(
            self._card, language=self._language, ink=card_ink(self.palette()), art=self._art
        )

    def _load(self) -> None:
        self._renderer.load(self.svg().encode("utf-8"))
        self.setFixedSize(self._renderer.defaultSize())
        self.update()

    def sizeHint(self) -> QSize:
        return self._renderer.defaultSize()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._load()
        super().changeEvent(event)

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._renderer.render(painter)
        painter.end()


class PinoutDialog(QDialog):
    """One part's pinout card, with Save SVG. Esc closes it, as any dialog's."""

    def __init__(
        self,
        card: PinoutCard,
        lookup: FootprintLookup,
        language: GuideLanguage,
        folder: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Pinout of {part}").format(part=card.title))
        self._card = card
        self._language = language
        self._folder = folder
        self.art = part_art_svg(card, lookup)
        self.view = _CardView(card, self.art, language)
        scroll = QScrollArea()
        scroll.setWidget(self.view)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(t("Close"))
        self.save = QPushButton(t("Save SVG…"))
        self.save.setToolTip(t("Saves the card on a white background, ready to print."))
        self.save.setAutoDefault(False)
        buttons.addButton(self.save, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        self.save.clicked.connect(lambda: self.on_save())
        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(buttons)
        hint = self.view.sizeHint()
        screen = self.screen().availableGeometry() if self.screen() is not None else None
        width, height = hint.width() + 48, hint.height() + 90
        if screen is not None:
            width = min(width, int(screen.width() * 0.9))
            height = min(height, int(screen.height() * 0.85))
        self.resize(width, height)

    def file_svg(self) -> str:
        """What Save SVG writes: the light card with the fonts any browser falls back on."""
        return pinout_svg(self._card, language=self._language, art=self.art)

    def default_path(self) -> Path:
        name = f"pinout-{self._card.part_id}.svg"
        return (self._folder / name) if self._folder is not None else Path(name)

    def on_save(self, path: Path | None = None) -> bool:
        if path is None:
            chosen, _selected = QFileDialog.getSaveFileName(
                self, t("Save SVG…"), str(self.default_path()), t("SVG pictures (*.svg)")
            )
            if not chosen:
                return False
            path = Path(chosen)
        if path.suffix.lower() != ".svg":
            path = path.with_suffix(".svg")
        try:
            path.write_text(self.file_svg(), encoding="utf-8", newline="\n")
        except OSError as err:
            QMessageBox.critical(
                self, t("Could not save the card"), str(err)
            )
            return False
        return True


def offer_pinout_on(
    tree: QTreeWidget,
    card_for: Callable[[QTreeWidgetItem], PinoutCard | None],
    show: Callable[[PinoutCard], object],
) -> None:
    """A right-click on a row of ``tree`` whose part has a card offers Show Pinout; a row
    with none offers nothing, rather than a menu item that cannot be pressed."""

    def menu_at(pos: QPoint) -> None:
        item = tree.itemAt(pos)
        card = card_for(item) if item is not None else None
        if card is None:
            return
        menu = QMenu(tree)
        action = menu.addAction(t("Show Pinout…"))
        action.triggered.connect(lambda: show(card))
        menu.popup(tree.viewport().mapToGlobal(pos))

    tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    tree.customContextMenuRequested.connect(menu_at)


__all__ = ["PinoutDialog", "card_of_part_row", "offer_pinout_on", "pinout_card_of", "save_folder"]
