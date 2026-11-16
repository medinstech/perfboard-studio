"""A fitted sheet is clear of the bars laid over it, as a fitted board is.

The walk at 1366 x 768 found nano-relay's sheet fitted under the zoom and Arrange bar in the
bottom-right corner, with C3's wire under it where it could not be grabbed. The sheet's fit
now leaves the bars their room by the same function as the board's
(``view2d.overlay_room``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _settle(app) -> None:
    for _ in range(6):
        app.processEvents()


@pytest.mark.parametrize("size", [(1366, 768), (1920, 1080)])
@pytest.mark.parametrize("name", ["nano-relay", "atmega328-relay"])
def test_a_fitted_sheet_is_clear_of_the_bars_over_it(qapp, name, size) -> None:
    from PySide6.QtCore import QPoint, QRect, QRectF

    from perfboard_studio import persist
    from perfboard_studio.ui.main import MainWindow

    text = (EXAMPLES / f"{name}.perf").read_text(encoding="utf-8")
    window = MainWindow(persist.deserialize_document(text).document)
    try:
        window.resize(*size)
        window.show()
        window.show_schematic()
        window._refresh_schematic_panel()
        _settle(qapp)
        view = window.schematic_view
        view.fit()
        _settle(qapp)
        assert view.overlays, "the sheet's bars are not handed to its view"
        drawing = view.item.drawing
        sheet = view.mapFromScene(QRectF(0, 0, drawing.width, drawing.height)).boundingRect()
        for bar in view.overlays:
            assert bar.isVisible()
            corner = view.viewport().mapFromGlobal(bar.mapToGlobal(QPoint(0, 0)))
            box = QRect(corner, bar.size())
            assert not box.intersects(sheet), (bar.objectName(), box, sheet)
    finally:
        window._mark_saved()
        window.close()
