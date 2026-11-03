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
from PySide6.QtGui import QColor, QPainterPath
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
    for role, path, _ink in view.shapes:
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
BODY_PENDING: dict[str, str] = {}


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
    for role, path, _ink in view.shapes:
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


# -- every polarity mark reads at the window's opening zoom ---------------------------------

#: The window opens a board at about six pixels to the millimetre (``BoardView``'s starting
#: scale), and a mark has to be seen there without zooming in: forty pixels of it at least.
OPENING_PX_PER_MM = 6.0
MIN_MARK_PX = 40
#: Contrast of the mark's ink against the case it is printed on, as WCAG measures it for
#: anything that is not text: 3:1. A reversed electrolytic can burst.
MIN_MARK_CONTRAST = 3.0


def _luminance(colour: QColor) -> float:
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    return 0.2126 * linear(colour.redF()) + 0.7152 * linear(colour.greenF()) + 0.0722 * linear(colour.blueF())


def _contrast(a: QColor, b: QColor) -> float:
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _area(path: QPainterPath) -> float:
    total = 0.0
    for polygon in path.toFillPolygons():
        points = [polygon.at(i) for i in range(polygon.count())]
        total += abs(sum(p.x() * q.y() - q.x() * p.y() for p, q in zip(points, points[1:] + points[:1], strict=True))) / 2
    return total


def _marked_side(footprint_id: str) -> tuple[str, str] | None:
    """(the pin the mark is by, the other one), by pin number, or None where the part
    shows no mark from above."""
    footprint = get_footprint(footprint_id)
    assert footprint is not None
    archetype = footprint.body.archetype
    names = {pin.name: pin.number for pin in footprint.pins}
    if archetype == "radial-electrolytic":
        return names.get("-", "2"), names.get("+", "1")
    if archetype == "led-round":
        return names.get("K", "2"), names.get("A", "1")
    if archetype == "axial-cylinder":
        return "1", "2"
    if archetype == "axial-upright":
        # The band is round the cap at the top, which is over the pin the body stands on;
        # the cathode's lead comes down from there to pin 1.
        standing = footprint.body.dims.get("standsOnPin", 1.0)
        return None if standing == 1.0 else ("2", "1")
    return None


def _polarized_views() -> list[str]:
    return [
        footprint_id
        for footprint_id in _footprints_with_views()
        if (fp := get_footprint(footprint_id)) is not None
        and fp.polarized
        and len(fp.pins) == 2
        and topview.top_view(fp, PITCH).source != "parametric"
    ]


def test_the_polarized_parts_with_views_are_the_ones_expected() -> None:
    archetypes = {get_footprint(f).body.archetype for f in _polarized_views()}  # type: ignore[union-attr]
    assert {"radial-electrolytic", "led-round", "axial-cylinder", "axial-upright"} <= archetypes


@pytest.mark.parametrize("footprint_id", _polarized_views())
def test_every_polarity_mark_reads_at_the_opening_zoom(footprint_id: str) -> None:
    """Big enough to see at the opening zoom, inked in a colour that stands off the case,
    inside the case, and on the side it marks: the negative lead of an electrolytic, an
    LED's cathode, a diode's cathode end. A standing diode on its cathode shows nothing,
    because its band is down by the board."""
    from perfboard_studio.ui.bodies import style_for
    from perfboard_studio.ui.view2d import _role_colour

    footprint = get_footprint(footprint_id)
    assert footprint is not None
    view = topview.top_view(footprint, PITCH)
    side = _marked_side(footprint_id)
    if side is None:
        assert view.polarity.isEmpty(), footprint_id
        return
    mark = view.polarity
    assert _area(mark) * OPENING_PX_PER_MM**2 >= MIN_MARK_PX, (footprint_id, _area(mark))

    style = style_for(footprint)
    ink = QColor(style.accent)
    for role in ("body", "flank"):
        assert _contrast(ink, _role_colour(role, style)) >= MIN_MARK_CONTRAST, (footprint_id, role)

    allowed = view.silhouette.boundingRect().adjusted(-EDGE_MM, -EDGE_MM, EDGE_MM, EDGE_MM)
    assert allowed.contains(mark.boundingRect()), footprint_id

    pins = {pin.number: QPointF(pin.d_col * PITCH, pin.d_row * PITCH) for pin in footprint.pins}
    centre = mark.boundingRect().center()
    near, far = (pins[number] for number in side)
    distance = lambda point: (point.x() - centre.x()) ** 2 + (point.y() - centre.y()) ** 2  # noqa: E731
    assert distance(near) < distance(far), (footprint_id, side)


#: The 16 x 2 character LCD: a green board, a black bezel and its glass.
LCD = "box-16x1-p1-r1-80x36x15-o12.95x15.5"


@pytest.mark.parametrize("footprint_id", sorted(partmodels.known_footprints()))
def test_every_marking_is_inked_in_a_colour_its_own_model_has(footprint_id: str) -> None:
    """A marking's colour is its piece's, the one the 3D view draws it in -- never one the
    data made up, and never missing on a measured marking."""
    model = partmodels.model_for(footprint_id)
    footprint = get_footprint(footprint_id)
    if model is None or footprint is None:
        return
    colours = {piece.color for piece in model.pieces if not piece.is_body}
    for role, _path, ink in topview.top_view(footprint, PITCH).shapes:
        if role == "marking":
            assert ink in colours, (footprint_id, ink)
        else:
            assert ink is None, (footprint_id, role)


def test_an_lcds_bezel_and_glass_are_two_colours_in_2d_as_in_3d() -> None:
    """One accent for every marking drew the bezel and the glass as one grey slab."""
    from perfboard_studio.ui.bodies import style_for
    from perfboard_studio.ui.view2d import _role_colour

    footprint = get_footprint(LCD)
    assert footprint is not None
    view = topview.top_view(footprint, PITCH)
    inks = {ink for role, _path, ink in view.shapes if role == "marking"}
    # The black bezel and the yellow-green glass (and, through the board's holes round the
    # pins, a glimpse of the header's black plastic under it).
    assert {"#0f0f0f", "#b4c43a"} <= inks, inks
    style = style_for(footprint)
    assert _role_colour("marking", style, "#b4c43a") == QColor("#b4c43a")
    # A marking with no colour of its own (a parametric shape) is still the style's accent.
    assert _role_colour("marking", style, None) == QColor(style.accent)
