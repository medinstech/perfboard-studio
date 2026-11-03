"""The legend laid out per edge, and a finger drawn by its shape.

The green 5 x 7 prints its letters along the top only and its numbers down both short
edges -- small, BETWEEN the grid and the edge strip, not outside it -- and its strip's pads
are stadiums; the phenolic board's are square. What is pinned: which edges a run is
printed on is the board's to say and otherwise what ``all_edges`` always said; the band a
run goes in is the wider of the two an outside strip leaves; both views take one layout;
and the new fields are left out of the file at their default.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, get_args

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    DEFAULT_BOARD,
    ApplyBoardPresetPayload,
    create_standard_registry,
)
from perfboard_studio.geometry import (
    OUTSIDE_FINGER_GAP_MM,
    STANDARD_PRESETS,
    board_edge_margin_mm,
    board_from_preset,
    hole_span_mm,
    legend_band_mm,
    legend_edges,
    legend_layout,
    outside_finger_room_mm,
    pad_extent_mm,
)
from perfboard_studio.model import (
    BoardLabels,
    DocumentMeta,
    EdgeConnector,
    FingerShape,
    PerfDocument,
)

META = DocumentMeta(name="t", created="", modified="")
PRESET = next(p for p in STANDARD_PRESETS if p.name == "5 x 7 cm" and not p.single_sided)
BOARD = board_from_preset(PRESET, DEFAULT_BOARD)
LABELS = BoardLabels(row_digits=2, all_edges=False)


def _doc(*connectors: EdgeConnector, labels: BoardLabels = LABELS) -> PerfDocument:
    return PerfDocument(
        meta=META, board=dataclasses.replace(BOARD, labels=labels), edge_connectors=connectors
    )


def _free(edge: str) -> float:
    axis = "horizontal" if edge in ("left", "right") else "vertical"
    extent_x, extent_y = pad_extent_mm(BOARD)
    return board_edge_margin_mm(BOARD, axis) - (extent_x if axis == "horizontal" else extent_y) / 2


def test_which_edges_is_the_boards_to_say_and_otherwise_what_all_edges_said() -> None:
    assert legend_edges(BoardLabels(all_edges=True)) == (("top", "bottom"), ("left", "right"))
    assert legend_edges(BoardLabels(all_edges=False)) == (("top",), ("left",))
    green = BoardLabels(all_edges=False, letter_edges="top", number_edges="both")
    assert legend_edges(green) == (("top",), ("left", "right"))
    assert legend_edges(dataclasses.replace(green, letter_edges="bottom")) == (
        ("bottom",), ("left", "right")
    )
    phenolic = BoardLabels(all_edges=False, letter_edges="top", number_edges="none")
    assert legend_edges(phenolic) == (("top",), ())
    assert legend_layout(_doc(labels=phenolic), phenolic).row_xs == ()


def test_a_run_goes_in_the_wider_band_an_outside_strip_leaves() -> None:
    # No strip: the whole bare strip, centred in it.
    centre, width = legend_band_mm(_doc(), "left")
    assert width == pytest.approx(_free("left")) and centre == pytest.approx(width / 2)
    # A strip on the holes leaves its inset.
    on_holes = EdgeConnector(id="e", edge="left", start=1, count=4, inset_mm=0.5)
    assert legend_band_mm(_doc(on_holes), "left") == pytest.approx((0.25, 0.5))
    # Outside and as long as the room: the gap to the pads is the thin one, so the inset.
    full = dataclasses.replace(on_holes, outside=True)
    assert legend_band_mm(_doc(full), "left")[1] == pytest.approx(0.5)
    assert OUTSIDE_FINGER_GAP_MM < 0.5
    # Outside and shorter: the band between the strip and the grid, where the green board
    # prints its numbers.
    room = outside_finger_room_mm(BOARD, "left", 0.4)
    short = dataclasses.replace(full, inset_mm=0.4, finger_length=room - 1.2)
    centre, width = legend_band_mm(_doc(short), "left")
    assert width == pytest.approx(1.2 + OUTSIDE_FINGER_GAP_MM)
    assert centre == pytest.approx(0.4 + (room - 1.2) + width / 2)
    # A strip on one edge says nothing about the other.
    assert legend_band_mm(_doc(short), "right")[1] == pytest.approx(_free("right"))


def test_numbers_land_between_the_grid_and_the_strip() -> None:
    room = outside_finger_room_mm(BOARD, "left", 0.4)
    strips = tuple(
        EdgeConnector(id=f"e-{edge}", edge=edge, start=1, count=BOARD.rows - 2, inset_mm=0.4,
                      finger_length=room - 1.2, outside=True, shape="stadium")
        for edge in ("left", "right")
    )
    labels = BoardLabels(row_digits=2, all_edges=False, letter_edges="top", number_edges="both")
    layout = legend_layout(_doc(*strips, labels=labels), labels)
    span_w, _span_h = hole_span_mm(BOARD)
    extent_x, _extent_y = pad_extent_mm(BOARD)
    left, right = layout.row_xs
    # Outside the pads, inside the strip's inner end.
    assert -(board_edge_margin_mm(BOARD, "horizontal") - 0.4 - (room - 1.2)) < left < -extent_x / 2
    assert span_w + extent_x / 2 < right
    assert right == pytest.approx(span_w - left)
    assert len(layout.column_ys) == 1 and layout.column_ys[0] < 0
    assert layout.height == pytest.approx(min(1.15, 0.6 * (1.2 + OUTSIDE_FINGER_GAP_MM)))


def test_both_views_take_the_one_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.footprints import footprint_lookup
    from perfboard_studio.ui import view2d, view3d

    QApplication.instance() or QApplication([])
    labels = BoardLabels(row_digits=2, all_edges=False, letter_edges="bottom", number_edges="right")
    doc = _doc(labels=labels)
    layout = legend_layout(doc, labels)
    letters: set[float] = set()
    numbers: set[float] = set()

    def record(painter: Any, centre: Any, text: str, height: float, **kwargs: Any) -> None:
        if kwargs.get("rotation_deg"):
            numbers.add(round(centre.x(), 6))
        else:
            letters.add(round(centre.y(), 6))

    monkeypatch.setattr(view2d, "draw_physical_label", record)
    item = view2d.BoardLegendItem(doc, labels, "top")
    image = QImage(10, 10, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    item.paint(painter, None)
    painter.end()
    assert letters == {round(layout.column_ys[0], 6)}
    assert numbers == {round(layout.row_xs[0], 6)}
    assert layout.column_ys[0] > 0 and layout.row_xs[0] > 0  # the bottom and the right
    assert view3d.build_legend(doc)  # builds from the same layout without complaint
    assert footprint_lookup is not None


def test_a_finger_is_drawn_by_its_shape() -> None:
    from perfboard_studio.ui.view2d import FINGER_CORNER

    assert set(FINGER_CORNER) == set(get_args(FingerShape))
    assert FINGER_CORNER["stadium"] == 0.5  # semicircular ends
    assert FINGER_CORNER["square"] < FINGER_CORNER["rounded"] < FINGER_CORNER["stadium"]


def test_the_new_fields_are_left_out_at_their_default_and_read_back() -> None:
    plain = persist.serialize_document(_doc(EdgeConnector(id="e", edge="left", start=1, count=4)))
    assert '"shape"' not in plain and '"letterEdges"' not in plain and '"numberEdges"' not in plain
    labels = BoardLabels(row_digits=2, all_edges=False, letter_edges="top", number_edges="both")
    stadium = EdgeConnector(id="e", edge="left", start=1, count=4, shape="stadium")
    text = persist.serialize_document(_doc(stadium, labels=labels))
    loaded = persist.parse_document_or_throw(text)
    assert loaded.edge_connectors[0].shape == "stadium"
    assert loaded.board.labels == labels
    with pytest.raises(ValueError, match="shape"):
        persist.parse_document_or_throw(text.replace('"stadium"', '"oval"'))


def test_a_preset_with_a_shape_nobody_draws_is_refused() -> None:
    bus = CommandBus(_doc(), create_standard_registry(), CommandContext(next_id=create_id_generator()))
    odd = EdgeConnector(id="e", edge="left", start=1, count=4, shape="oval")  # type: ignore[arg-type]
    result = bus.dispatch(
        "board.applyPreset",
        ApplyBoardPresetPayload(board=BOARD, edge_connectors=(odd,), mounting_holes=()),
    )
    assert not result.ok and result.code == "invalid-edge-connector", result.message
