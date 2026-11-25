"""The sheet's zoom limits and its fit: a fit shows the whole sheet even below the zoom-out
limit, and from there a zoom out does nothing and a zoom in works -- never the reverse."""

from __future__ import annotations

import dataclasses
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.schematic import build_schematic

from .test_ui import _load_dense


@pytest.fixture(scope="module", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication(["perfboard-studio-tests"])


def _fitted_below_the_floor():  # type: ignore[no-untyped-def]
    from perfboard_studio.ui.viewsch import SchematicView

    drawing = build_schematic(_load_dense(), footprint_lookup())
    view = SchematicView()
    view.resize(300, 300)
    view.show()
    QApplication.processEvents()
    view.set_drawing(dataclasses.replace(drawing, width=drawing.width * 4))
    view.fit()
    QApplication.processEvents()
    assert view.current_scale() < view.MIN_SCALE
    return view


def test_a_zoom_out_below_the_floor_does_nothing_rather_than_zooming_in() -> None:
    view = _fitted_below_the_floor()
    try:
        assert view._clamped_factor(1 / 1.18) == pytest.approx(1.0)
        before = view.current_scale()
        assert view._clamped_scale(before, 1 / 1.18) == pytest.approx(before)
    finally:
        view.close()


def test_a_zoom_in_below_the_floor_still_zooms_in() -> None:
    view = _fitted_below_the_floor()
    try:
        assert view._clamped_factor(1.18) == pytest.approx(1.18)
    finally:
        view.close()


def test_above_the_floor_the_limits_hold() -> None:
    from perfboard_studio.ui.viewsch import SchematicView

    view = SchematicView()
    assert view._clamped_scale(0.55, 0.5) == pytest.approx(SchematicView.MIN_SCALE)
    assert view._clamped_scale(50.0, 2.0) == pytest.approx(SchematicView.MAX_SCALE)
