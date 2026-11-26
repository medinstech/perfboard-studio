"""The middle of a pinout card, drawn by the board view's own part (``ui/pinoutart``)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.pinout import PinoutCard, pinout_card
from perfboard_studio.pinout_export import PINOUT_LIGHT, pinout_svg
from perfboard_studio.ui import view2d
from perfboard_studio.ui.moduleart import ART_COLOURS
from perfboard_studio.ui.pinoutart import UNITS_PER_MM, card_ink, part_art_svg
from perfboard_studio.ui.pinoutview import (
    PinoutDialog,
    card_of_part_row,
    offer_pinout_on,
    save_folder,
)

LOOKUP = footprint_lookup()


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _card(part_id: str) -> PinoutCard:
    card = pinout_card(part_id, LOOKUP)
    assert card is not None
    return card


@pytest.mark.parametrize("part_id", ["arduino-nano", "esp32-devkitc", "attiny85"])
def test_the_art_is_vector_and_its_viewbox_is_the_frame(part_id: str) -> None:
    card = _card(part_id)
    art = part_art_svg(card, LOOKUP)
    assert art is not None
    assert "<image" not in art
    x0, x1, y0, y1 = card.frame
    box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', art)
    assert box is not None
    assert float(box.group(1)) == pytest.approx((x1 - x0) * UNITS_PER_MM, abs=0.1)
    assert float(box.group(2)) == pytest.approx((y1 - y0) * UNITS_PER_MM, abs=0.1)
    # The engine takes it as it is.
    assert "<svg" in pinout_svg(card, art=art)


def _fills(svg: str) -> set[str]:
    return {f.lower() for f in re.findall(r'fill="(#[0-9a-fA-F]{6})"', svg)}


def test_a_bare_chip_is_its_body_and_legs_with_no_board_behind_it() -> None:
    """Sinan: no perfboard under the part. Nothing of the board is drawn -- no substrate,
    no pad, no hole -- and a bare chip leaves out the lead ends the board view paints into
    its holes, which on a card read as pad rings."""
    art = part_art_svg(_card("attiny85"), LOOKUP)
    assert art is not None
    fills = _fills(art)
    assert view2d.PIN_MARKER.name() not in fills
    assert view2d.PIN_ONE.name() not in fills
    # No canvas either: past the legs the drawing is transparent, the card's own ground.
    renderer = QSvgRenderer(art.encode("utf-8"))
    image = QImage(renderer.defaultSize(), QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    assert image.pixelColor(0, image.height() // 2).alpha() == 0
    assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() == 255


def test_a_module_keeps_its_own_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An illustrated module paints its own plated holes, a header pin's tip in solder in
    each; one drawn without illustrated art still has the board view's pin ends. Every
    module the catalogue sells is illustrated, so the plain one is the Nano with its
    layout taken away."""
    nano = part_art_svg(_card("arduino-nano"), LOOKUP)
    assert nano is not None
    assert {ART_COLOURS["pin-tip"], ART_COLOURS["solder"]} <= _fills(nano)
    assert view2d.PIN_MARKER.name() not in _fills(nano)
    monkeypatch.setattr(view2d, "fit_module_art", lambda *_args, **_kwargs: None)
    plain = part_art_svg(_card("arduino-nano"), LOOKUP)
    assert plain is not None
    assert view2d.PIN_MARKER.name() in _fills(plain)
    assert ART_COLOURS["pin-tip"] not in _fills(plain)


def test_every_module_on_a_card_is_drawn_as_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card's part is the board view's drawing, so a module the board view draws as
    itself is drawn so on its card too -- a layout turned by a pin's name needs the names."""
    from perfboard_studio.catalog import CATALOG
    from perfboard_studio.ui.moduleart import recognise_module

    real = view2d.fit_module_art
    fitted: list[bool] = []
    monkeypatch.setattr(
        view2d, "fit_module_art", lambda *a, **k: fitted.append(real(*a, **k) is not None) or real(*a, **k)
    )
    for part in CATALOG:
        footprint = LOOKUP(part.footprint_id)
        if footprint is None or footprint.body.archetype != "module-board":
            continue
        if recognise_module(part.value or part.name) is None:
            continue
        card = pinout_card(part.id, LOOKUP)
        if card is None:
            continue
        fitted.clear()
        assert part_art_svg(card, LOOKUP) is not None, part.id
        assert fitted and fitted[-1], part.id


def test_a_pinout_card_shows_the_boards_own_pin_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card names the pins round the part, so the part in its middle is the board as it
    is, its silkscreen names and all (``ArtPart.under_names``)."""
    real = view2d.fit_module_art
    fitted: list[tuple[str, ...]] = []

    def fit(*args, **kwargs):  # type: ignore[no-untyped-def]
        placed = real(*args, **kwargs)
        fitted.append(tuple(part.text for part in placed or ()))
        return placed

    monkeypatch.setattr(view2d, "fit_module_art", fit)
    assert part_art_svg(_card("adafruit-pcf8574-qt"), LOOKUP) is not None
    assert fitted and {"PCF8574", "P7", "VIN"} <= set(fitted[-1])


def test_the_cards_ink_follows_the_palette_it_is_painted_under() -> None:
    """Read at paint time from the palette ``theme.apply`` sets, so a card painted after a
    theme switch is in the new theme."""
    light, dark = QPalette(), QPalette()
    light.setColor(QPalette.ColorRole.Window, QColor("#fafafa"))
    light.setColor(QPalette.ColorRole.WindowText, QColor("#111111"))
    dark.setColor(QPalette.ColorRole.Window, QColor("#1b1e25"))
    dark.setColor(QPalette.ColorRole.WindowText, QColor("#eeeeee"))
    assert card_ink(light).background == "#fafafa"
    assert card_ink(light).text == "#111111"
    assert card_ink(dark).background == "#1b1e25"
    assert card_ink(dark).kinds != card_ink(light).kinds
    # QtSvg parses no list of families.
    assert "," not in card_ink(light).font_family


# -- the window ------------------------------------------------------------------------

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_the_dialog_saves_the_light_card_where_the_project_keeps_its_outputs(
    tmp_path: Path,
) -> None:
    board = tmp_path / "relay.perf"
    board.write_text("", encoding="utf-8")
    assert save_folder(board) == tmp_path
    (tmp_path / "outputs").mkdir()
    assert save_folder(board) == tmp_path / "outputs"
    assert save_folder(None) is None

    dialog = PinoutDialog(_card("arduino-nano"), LOOKUP, "tr", save_folder(board))
    assert dialog.default_path() == tmp_path / "outputs" / "pinout-arduino-nano.svg"
    assert dialog.on_save(tmp_path / "outputs" / "nano")
    written = (tmp_path / "outputs" / "nano.svg").read_text(encoding="utf-8")
    assert "üstten görünüş" in written
    # The file is the light card, whatever the window's theme, with the browser fonts.
    assert PINOUT_LIGHT.background in written
    assert "Segoe UI', " in written
    dialog.deleteLater()


def test_the_dialog_repaints_its_card_when_the_palette_changes() -> None:
    dialog = PinoutDialog(_card("attiny85"), LOOKUP, "en", None)
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor("#1b1e25"))
    dialog.view.setPalette(dark)
    assert 'fill="#1b1e25"' in dialog.view.svg()
    light = QPalette()
    light.setColor(QPalette.ColorRole.Window, QColor("#fbfbfc"))
    dialog.view.setPalette(light)
    assert 'fill="#fbfbfc"' in dialog.view.svg()
    dialog.deleteLater()


def test_a_right_click_menu_is_freed_when_it_closes() -> None:
    """Each right-click makes its menu; closed, it goes, rather than one per click staying
    parented to the tree for as long as the tree lives."""
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

    tree = QTreeWidget()
    QTreeWidgetItem(tree, ["U1"])
    tree.show()
    QApplication.processEvents()
    shown: list[str] = []
    offer_pinout_on(tree, lambda item: _card("attiny85"), lambda card: shown.append(card.part_id))
    pos = tree.visualItemRect(tree.topLevelItem(0)).center()
    for _ in range(3):
        tree.customContextMenuRequested.emit(QPoint(pos))
        menus = tree.findChildren(QMenu)
        assert len(menus) == 1
        menus[0].close()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert tree.findChildren(QMenu) == []
    tree.customContextMenuRequested.emit(QPoint(pos))
    tree.findChildren(QMenu)[0].actions()[0].trigger()
    assert shown == ["attiny85"]
    tree.findChildren(QMenu)[0].close()
    tree.deleteLater()


def test_escape_closes_the_dialog() -> None:
    dialog = PinoutDialog(_card("attiny85"), LOOKUP, "en", None)
    dialog.show()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.deleteLater()


def test_a_parts_row_and_properties_find_the_card_of_a_placed_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from perfboard_studio import persist
    from perfboard_studio.ui.main import MainWindow

    doc = persist.deserialize_document(
        (EXAMPLES / "nano-relay.perf").read_text(encoding="utf-8")
    ).document
    window = MainWindow(doc)
    shown: list[str] = []
    monkeypatch.setattr(PinoutDialog, "exec", lambda self: shown.append(self._card.part_id) or 0)
    try:
        nano = next(c for c in window.bus.document.components if c.ref == "A1")
        resistor = next(c for c in window.bus.document.components if c.ref.startswith("R"))
        window.part_list.refresh(window.bus.system_document, window.lookup)
        rows = {
            window.part_list.tree.topLevelItem(i).text(0): window.part_list.tree.topLevelItem(i)
            for i in range(window.part_list.tree.topLevelItemCount())
        }
        card = card_of_part_row(rows["A1"], window.bus.system_document, window.lookup)
        assert card is not None and card.part_id == "arduino-nano"
        assert card_of_part_row(rows[resistor.ref], window.bus.system_document, window.lookup) is None

        window.scene.select_components([nano.id])
        window._refresh_properties()
        editor = window.inspector.part_editor
        assert not editor.pinout_card.isHidden()
        editor.pinout_card.linkActivated.emit("pinout")
        assert shown == ["arduino-nano"]

        window.scene.select_components([resistor.id])
        window._refresh_properties()
        assert editor.pinout_card.isHidden()
    finally:
        window._saved_document = window.bus.system_document
        window.close()
