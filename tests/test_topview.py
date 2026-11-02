"""A part from straight above (``ui/topview.py``, ``models/topviews.json``).

What is pinned: the data was measured from the meshes that are shipped, and names the KiCad
package each was measured from; every case it describes stands inside the body DRC measures
(the drawing follows DRC's geometry, never the other way round); every pin is either visible
as metal or marked; a header and a terminal block of any length are drawn from their pieces;
and with no data file at all every part is still drawn, from parametric shapes inside its
body.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication

from perfboard_studio.footprints import body_extent, get_footprint, standard_footprints
from perfboard_studio.ui import partmodels, topview

PITCH = 2.54
#: A case may meet DRC's body exactly; this is the rasteriser's own resolution, and no more.
EDGE_MM = 0.06
CASE_ROLES = ("body", "flank", "recess", "plastic", "marking")


@pytest.fixture(scope="module", autouse=True)
def qapp() -> QApplication:
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])  # type: ignore[return-value]


def _case(view: topview.TopView) -> QRectF:
    case = QPainterPath()
    for role, path in view.shapes:
        if role in CASE_ROLES:
            case = case.united(path)
    return case.boundingRect()


def _extent_rect(footprint_id: str) -> QRectF:
    extent = body_extent(get_footprint(footprint_id), PITCH)  # type: ignore[arg-type]
    return QRectF(
        extent.centre_x - extent.size_x / 2,
        extent.centre_y - extent.size_y / 2,
        extent.size_x,
        extent.size_y,
    )


def _footprints_with_views() -> list[str]:
    ids = set(standard_footprints()) | {
        footprint_id for footprint_id in partmodels.known_footprints() if get_footprint(footprint_id)
    }
    return sorted(ids)


#: Cases the BODY has not caught up with yet, by name. Each is a body DRC measures in the
#: wrong place, not a picture to trim, and each is strict so it asks to be unmarked the day
#: the body moves.
BODY_PENDING = {
    "to220": (
        "KiCad's TO-220 case stands 0.93 mm behind its pin row, tab at the back, and DRC's box "
        "is still centred on the row. The offsetY that fixes it (branch parts-to220) waits for "
        "breadboard placement to be robust: with it, nano-relay's relay is left off an 830 "
        "breadboard at seed 0."
    ),
}


def _cases() -> list[object]:
    return [
        pytest.param(footprint_id, marks=pytest.mark.xfail(strict=True, reason=BODY_PENDING[footprint_id]))
        if footprint_id in BODY_PENDING
        else footprint_id
        for footprint_id in _footprints_with_views()
    ]


def test_the_data_names_the_package_each_model_was_measured_from() -> None:
    """A mesh re-imported from another KiCad package (r-axial-5 was) leaves the data
    describing the old one, and this is where that shows: re-run tools/make_topviews.py."""
    data = topview._data()
    for footprint_id in partmodels.known_footprints():
        model = partmodels.model_for(footprint_id)
        if model is None:
            continue
        assert footprint_id in data, f"{footprint_id} has a model and no top view"
        assert data[footprint_id]["source"] == model.source, footprint_id


@pytest.mark.parametrize("footprint_id", _cases())
def test_every_case_stands_inside_the_body_drc_measures(footprint_id: str) -> None:
    footprint = get_footprint(footprint_id)
    assert footprint is not None
    drawn = _case(topview.top_view(footprint, PITCH))
    allowed = _extent_rect(footprint_id).adjusted(-EDGE_MM, -EDGE_MM, EDGE_MM, EDGE_MM)
    assert allowed.contains(drawn), (
        f"{footprint_id}: the case {drawn.width():.2f} x {drawn.height():.2f} mm at "
        f"({drawn.left():.2f}, {drawn.top():.2f}) leaves DRC's body "
        f"{allowed.width():.2f} x {allowed.height():.2f}"
    )


@pytest.mark.parametrize("footprint_id", _footprints_with_views())
def test_every_pin_shows_as_metal_or_is_marked(footprint_id: str) -> None:
    """The view is what the part is soldered by: no hole may disappear under a body."""
    footprint = get_footprint(footprint_id)
    assert footprint is not None
    view = topview.top_view(footprint, PITCH)
    metal = QPainterPath()
    for role, path in view.shapes:
        if role in ("metal", "metal-recess"):
            metal = metal.united(path)
    for pin in footprint.pins:
        at = (pin.d_col * PITCH, pin.d_row * PITCH)
        assert metal.contains(QPointF(*at)) or at in view.hidden_pins, (footprint_id, pin.number)


def test_a_dip_is_narrower_than_its_rows_and_its_legs_reach_the_holes() -> None:
    """The user's complaint, measured: the body of a DIP-8 is 6.35 mm across rows 7.62 mm
    apart, and the metal of each leg runs out from under it to the hole."""
    view = topview.top_view(get_footprint("dip-8"), PITCH)  # type: ignore[arg-type]
    case = _case(view)
    assert 6.1 < case.width() < 6.7
    assert view.source.startswith("Package_DIP/DIP-8")
    assert not view.hidden_pins


@pytest.mark.parametrize("footprint_id", ["hdr-1x7", "hdr-2x13", "screw-terminal-5", "screw-terminal-4-v"])
def test_a_repeated_package_of_any_length_is_drawn_from_its_pieces(footprint_id: str) -> None:
    footprint = get_footprint(footprint_id)
    assert footprint is not None
    view = topview.top_view(footprint, PITCH)
    assert view.source != "parametric", footprint_id
    allowed = _extent_rect(footprint_id).adjusted(-EDGE_MM, -EDGE_MM, EDGE_MM, EDGE_MM)
    assert allowed.contains(_case(view)), footprint_id


def test_with_no_data_every_part_is_still_drawn_inside_its_body(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(topview, "TOPVIEWS_PATH", tmp_path / "missing.json")
    topview._data.cache_clear()
    monkeypatch.setattr(topview, "_CACHE", {})
    try:
        for footprint_id in sorted(standard_footprints()):
            footprint = get_footprint(footprint_id)
            assert footprint is not None
            view = topview.top_view(footprint, PITCH)
            assert view.source == "parametric"
            assert view.shapes, footprint_id
            allowed = _extent_rect(footprint_id).adjusted(-EDGE_MM, -EDGE_MM, EDGE_MM, EDGE_MM)
            assert allowed.contains(_case(view)), footprint_id
    finally:
        topview._data.cache_clear()


def test_the_data_is_what_the_tool_would_write_for_a_small_part() -> None:
    """One model re-measured here, so a hand edit or a stale file fails without the full
    minute the tool takes over all of them (``make_topviews.py --check`` does the rest)."""
    import importlib.util
    import pathlib

    tool = pathlib.Path(__file__).resolve().parents[1] / "tools" / "make_topviews.py"
    spec = importlib.util.spec_from_file_location("make_topviews", tool)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = partmodels.model_for("to92")
    assert model is not None
    assert module.top_view(model) == topview._data()["to92"]
