"""The board's look on screen, and the 1:1 print that must not take it.

Chosen on 2026-10-28 from rendered looks: bodies standing on the board with a contact shadow
and lit from the top left, a DIP's value on its top, references outlined instead of plated,
far-face copper quieter. The shadow and the light are for the eye on a screen. The 1:1 PDF
is taped to the board in someone's hand, so it shows every part flat -- which is what most
of these hold. Pads nothing landed in were drawn quieter on screen too, until the user chose
the board as it is in the hand (2026-11-03): every pad is tin on both.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QTransform
from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import PerfDocument
from perfboard_studio.ui import view2d
from perfboard_studio.ui.export_pdf import export_pdf

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
LOOKUP = footprint_lookup()


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _example(name: str) -> PerfDocument:
    return persist.parse_document_or_throw((EXAMPLES / f"{name}.perf").read_text(encoding="utf-8"))


def _on_screen(scene: view2d.BoardScene) -> None:
    rect = scene.sceneRect()
    image = QImage(round(rect.width() * 8), round(rect.height() * 8), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), rect)
    painter.end()


def _on_paper(doc: PerfDocument, scene: view2d.BoardScene, tmp_path: Path) -> None:
    export_pdf(doc.board, scene, tmp_path / "board.pdf")


def _counting(paint, drawn: list[int]):  # type: ignore[no-untyped-def]
    """``PadGridItem.paint`` that records which pad image each hole was drawn with."""

    def wrapped(item, painter, option, widget=None):  # type: ignore[no-untyped-def]
        real = painter.drawPixmap

        class Recording:
            def __getattr__(self, name):  # type: ignore[no-untyped-def]
                return getattr(painter, name)

            def drawPixmap(self, target, pixmap, source):  # type: ignore[no-untyped-def]
                drawn.append(pixmap.cacheKey())
                return real(target, pixmap, source)

        return paint(item, Recording(), option, widget)

    return wrapped


def test_every_pad_is_drawn_alike_on_screen_and_on_paper(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A real board's pads are all tin, used or not, and so are these: one pad image for every
    hole, on screen as on the 1:1 print."""
    drawn: list[int] = []
    doc = _example("ne555-astable")
    for render in (
        lambda: _on_screen(view2d.BoardScene(doc, LOOKUP, side="top")),
        lambda: _on_paper(doc, view2d.BoardScene(doc, LOOKUP, side="top"), tmp_path),
    ):
        drawn.clear()
        monkeypatch.setattr(view2d.PadGridItem, "paint", _counting(view2d.PadGridItem.paint, drawn))
        render()
        monkeypatch.undo()
        assert drawn, "no pads were drawn"
        assert len(set(drawn)) == 1, "two kinds of pad on one board"


def test_shadows_and_light_are_for_the_screen_only(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    monkeypatch.setattr(view2d, "_paint_contact_shadow", lambda *a: calls.append("shadow"))
    monkeypatch.setattr(view2d, "_paint_body_light", lambda *a: calls.append("light"))
    doc = _example("ne555-astable")

    _on_screen(view2d.BoardScene(doc, LOOKUP, side="top"))
    assert "shadow" in calls and "light" in calls

    calls.clear()
    _on_paper(doc, view2d.BoardScene(doc, LOOKUP, side="top"), tmp_path)
    assert not calls, "the 1:1 print shaded a part"


def test_far_face_copper_is_quieter_on_screen_only(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    seen: list[tuple[bool, float]] = []
    real = view2d.ConductorItem._paint_conductor

    def record(item, painter):  # type: ignore[no-untyped-def]
        seen.append((item.is_far_side(), painter.opacity()))
        real(item, painter)

    monkeypatch.setattr(view2d.ConductorItem, "_paint_conductor", record)
    doc = _example("atmega328-relay")

    _on_screen(view2d.BoardScene(doc, LOOKUP, side="top"))
    far = {round(opacity, 2) for is_far, opacity in seen if is_far}
    near = {round(opacity, 2) for is_far, opacity in seen if not is_far}
    assert far == {view2d.FAR_SIDE_OPACITY}
    assert not near or near == {1.0}

    seen.clear()
    _on_paper(doc, view2d.BoardScene(doc, LOOKUP, side="top"), tmp_path)
    assert seen and {round(opacity, 2) for _far, opacity in seen} == {1.0}


def test_a_dip_says_its_value_on_its_top(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    marked: list[str] = []
    real = view2d._paint_top_marking

    def record(painter, footprint, placement, comp, *rest):  # type: ignore[no-untyped-def]
        if footprint.body.archetype == "dip":
            marked.append(comp.ref)
        real(painter, footprint, placement, comp, *rest)

    monkeypatch.setattr(view2d, "_paint_top_marking", record)
    doc = _example("atmega328-relay")
    _on_screen(view2d.BoardScene(doc, LOOKUP, side="top"))
    dips = {
        c.ref for c in doc.components
        if (fp := LOOKUP(c.footprint_id)) is not None and fp.body.archetype == "dip"
    }
    assert dips and set(marked) == dips


def test_a_relay_a_crystal_and_a_pot_carry_their_value_and_a_transistor_does_not(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Chosen 2026-11-23 from rendered candidates: what a part's top really carries is
    printed on it. A TO-92's and a TO-220's print is on their front face, which a view from
    above does not see, so they stay blank. The case is the document's, but a DIP's."""
    printed: list[str] = []
    real = view2d.draw_physical_label
    real_marking = view2d._paint_top_marking
    # A DIP's number is lasered into the moulding (``_paint_laser_text``), the rest printed.
    real_laser = view2d._paint_laser_text

    def marking(painter, footprint, placement, comp, *rest):  # type: ignore[no-untyped-def]
        def record(painter, centre, text, height_mm, *args, **kwargs):  # type: ignore[no-untyped-def]
            printed.append(text)
            return real(painter, centre, text, height_mm, *args, **kwargs)

        def laser(painter, text, *args):  # type: ignore[no-untyped-def]
            printed.append(text)
            return real_laser(painter, text, *args)

        monkeypatch.setattr(view2d, "draw_physical_label", record)
        monkeypatch.setattr(view2d, "_paint_laser_text", laser)
        try:
            real_marking(painter, footprint, placement, comp, *rest)
        finally:
            monkeypatch.setattr(view2d, "draw_physical_label", real)
            monkeypatch.setattr(view2d, "_paint_laser_text", real_laser)

    monkeypatch.setattr(view2d, "_paint_top_marking", marking)
    _on_screen(view2d.BoardScene(_example("atmega328-relay"), LOOKUP, side="top"))

    assert "SRD-05VDC-SL-C" in printed, "K1, the relay"
    assert "16MHz" in printed, "Y1, the crystal, in its own case"
    assert "10k" in printed, "RV1, the pot"
    assert "ATMEGA328P-PU" in printed, "U1 still, in capitals"
    assert "BC547" not in printed and "L7805" not in printed


def test_a_chip_on_the_first_row_prints_its_names_on_itself_not_over_the_letters() -> None:
    """Chosen 2026-11-23 from rendered candidates. atmega328-relay's U1 stands on the first
    row, and its names ran across the column letters printed above it, H to T. A name now
    stops short of the band the legend is printed in, and a DIP's that finds no room there
    is printed on the chip, running in from its pin -- none is left off -- while the chip's
    own print moves into the half of it they leave free."""
    scene = view2d.BoardScene(_example("atmega328-relay"), LOOKUP, side="top")
    u1 = next(item for item in scene.component_items.values() if item.comp.ref == "U1")
    assert scene.legend_item is not None
    letters = scene.legend_item.label_rects()
    names = [u1.mapRectToScene(rect) for rect in u1.pin_name_rects()]
    assert names and not [name for name in names if any(name.intersects(r) for r in letters)]
    # The short names, whatever the font: how wide XTAL1 is printed depends on one, and
    # Qt's offscreen plugin on Windows has none (see test_ui's skipif guards).
    on_top = {label.name for label in u1.pin_names if label.on_body}
    assert {"PB0", "PD7", "PD6", "PD5", "GND", "VCC", "PD4", "TXD", "RXD"} <= on_top
    placement = view2d.placement_for(u1.fp, scene.document.board.pitch)
    strip = view2d._marking_gap(view2d._body_rect(placement), u1.pin_names)
    assert strip is not None, "ATMEGA328P-PU is still printed"
    assert strip.height() >= view2d.TOP_MARKING_MM * 1.2 or strip.width() >= view2d.TOP_MARKING_MM * 1.2


def test_an_address_a_part_stands_on_is_said_again_outside_the_board() -> None:
    """J2 stands on the row numbers beside it and RV1 on the ones across the board: each
    hidden address is drawn where the ruler would draw it, and only those -- the rest the
    board says itself. Outside the outline, so never on the 1:1 print."""
    doc = _example("atmega328-relay")
    scene = view2d.BoardScene(doc, LOOKUP, side="top")
    assert scene.legend_echo is not None
    hidden = scene.legend_echo.hidden(QTransform())
    rows = [text for _centre, text, rotation in hidden if rotation]
    assert {"05", "06", "07", "08"} <= set(rows), rows
    assert "A" not in {text for _centre, text, rotation in hidden if not rotation}
    assert scene.legend_item is not None
    assert len(hidden) < len(scene.legend_item.label_rects()) / 4, "only what is hidden"
    _on_screen(scene)

    # A board printing no addresses has the ruler instead, and nothing to say again.
    bare = dataclasses.replace(doc, board=dataclasses.replace(doc.board, labels=None))
    assert view2d.BoardScene(bare, LOOKUP, side="top").legend_echo is None


def test_echoed_legend_and_ruler_labels_stay_outside_the_board_at_low_zoom() -> None:
    """#10: draw_label aligns inside a box centred on the anchor, so LegendEchoItem and
    HoleRulerItem must use AlignLeft/AlignRight/AlignTop/AlignBottom in draw_label's terms
    with a device-pixel gap (RULER_GAP_PX). Verified on the pixels at 6 px/mm."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    doc = _example("atmega328-relay")
    outline = view2d._outline_rect(doc.board)
    px_per_mm = 6.0
    pad_mm = 10.0
    src = outline.adjusted(-pad_mm, -pad_mm, pad_mm, pad_mm)
    width = round(src.width() * px_per_mm)
    height = round(src.height() * px_per_mm)
    left_edge = round((outline.left() - src.left()) * px_per_mm)
    right_edge = round((outline.right() - src.left()) * px_per_mm)
    top_edge = round((outline.top() - src.top()) * px_per_mm)
    bottom_edge = round((outline.bottom() - src.top()) * px_per_mm)

    def render_only(scene: view2d.BoardScene, target: object) -> QImage:
        scene.setBackgroundBrush(QColor(255, 255, 255))
        for item in scene.items():
            item.setVisible(item is target)
        img = QImage(width, height, QImage.Format.Format_ARGB32)
        img.fill(QColor(255, 255, 255))
        painter = QPainter(img)
        scene.render(painter, QRectF(0, 0, width, height), src)
        painter.end()
        return img

    # 1. LegendEchoItem: left and right echoed row numbers stay strictly outside the outline.
    scene = view2d.BoardScene(doc, LOOKUP, side="top")
    assert scene.legend_echo is not None
    # Pre-populate hidden() while all components are visible, then render only LegendEchoItem.
    scene.legend_echo._hidden = (
        px_per_mm,
        scene.legend_echo.hidden(QTransform.fromScale(px_per_mm, px_per_mm)),
    )
    echo_img = render_only(scene, scene.legend_echo)
    ink = [
        (x, y)
        for y in range(height)
        for x in range(width)
        if echo_img.pixelColor(x, y).red() < 240
    ]
    assert ink, "LegendEchoItem drew no pixels"
    inside = [
        (x, y)
        for x, y in ink
        if left_edge - 2 <= x <= right_edge + 2 and top_edge - 2 <= y <= bottom_edge + 2
    ]
    assert inside == [], f"echoed legend ink overlapped board edge/interior: {inside[:10]}"
    left_xs = [x for x, _y in ink if x < left_edge]
    assert left_xs and max(left_xs) <= left_edge - 4, (max(left_xs) if left_xs else None, left_edge)

    # 2. HoleRulerItem on an unlabelled board: column/row labels stay strictly outside.
    bare = dataclasses.replace(doc, board=dataclasses.replace(doc.board, labels=None))
    bare_scene = view2d.BoardScene(bare, LOOKUP, side="top")
    ruler = next(i for i in bare_scene.items() if isinstance(i, view2d.HoleRulerItem))
    ruler_img = render_only(bare_scene, ruler)
    ruler_ink = [
        (x, y)
        for y in range(height)
        for x in range(width)
        if ruler_img.pixelColor(x, y).red() < 240
    ]
    assert ruler_ink, "HoleRulerItem drew no pixels"
    ruler_inside = [
        (x, y)
        for x, y in ruler_ink
        if left_edge - 2 <= x <= right_edge + 2 and top_edge - 2 <= y <= bottom_edge + 2
    ]
    assert ruler_inside == [], f"ruler ink overlapped board edge/interior: {ruler_inside[:10]}"


def test_a_name_with_nowhere_else_to_go_still_crosses_the_legend() -> None:
    """Only a DIP has a top to print a name on. nano-relay's J2 stands on the first column
    with its names behind it, where the row numbers are: kept off the legend they were
    lost, so they cross it after all, and the numbers they hide are said outside."""
    scene = view2d.BoardScene(_example("nano-relay"), LOOKUP, side="top")
    j2 = next(item for item in scene.component_items.values() if item.comp.ref == "J2")
    assert {label.name for label in j2.pin_names} == {"COM", "NO", "NC"}
    assert scene.legend_echo is not None
    rows = {text for _centre, text, rotation in scene.legend_echo.hidden(QTransform()) if rotation}
    assert {"08", "10", "12"} <= rows, rows


def test_a_relay_is_a_case_with_square_shoulders() -> None:
    from perfboard_studio.ui.bodies import placement_for

    relay = LOOKUP("relay-spdt")
    assert relay is not None
    assert placement_for(relay, 2.54).silhouette == "rect"


def test_references_are_outlined_on_screen_and_plated_on_paper(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    outlined: list[str] = []
    printed: list[str] = []
    real_outlined = view2d.draw_outlined_reference
    real_printed = view2d.draw_printed_reference

    def record_outlined(painter, anchor, reference, value, px, **kwargs):  # type: ignore[no-untyped-def]
        outlined.append(reference)
        real_outlined(painter, anchor, reference, value, px, **kwargs)

    def record_printed(painter, anchor, reference, *args, **kwargs):  # type: ignore[no-untyped-def]
        printed.append(reference)
        real_printed(painter, anchor, reference, *args, **kwargs)

    monkeypatch.setattr(view2d, "draw_outlined_reference", record_outlined)
    monkeypatch.setattr(view2d, "draw_printed_reference", record_printed)
    doc = _example("ne555-astable")
    refs = {c.ref for c in doc.components}

    _on_screen(view2d.BoardScene(doc, LOOKUP, side="top"))
    assert set(outlined) == refs and not printed

    outlined.clear()
    _on_paper(doc, view2d.BoardScene(doc, LOOKUP, side="top"), tmp_path)
    assert set(printed) == refs and not outlined


# ------------------------------------------------------------------ solder and wire, lit
#
# Chosen on 2026-11-11 from rendered candidates, on both faces ("lit ridge"): a run is a
# ridge with a domed joint on every pad, a wire is a tinned round or a sleeve over one. All
# of it is for the eye, so the print keeps the flat copper it always had.


def _with_conductors(name: str, conductors) -> PerfDocument:  # type: ignore[no-untyped-def]
    import dataclasses

    return dataclasses.replace(_example(name), conductors=tuple(conductors))


def _run(cid: str, row: int, **fields):  # type: ignore[no-untyped-def]
    from perfboard_studio.model import HoleCoord, SolderTraceConductor

    path = tuple(HoleCoord(col=c, row=row) for c in range(2, 8))
    return SolderTraceConductor(id=cid, path=path, **fields)


def test_lit_copper_is_for_the_screen_only(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    real = view2d.ConductorItem._paint_lit

    def record(item, *args):  # type: ignore[no-untyped-def]
        calls.append(item.conductor.id)
        real(item, *args)

    monkeypatch.setattr(view2d.ConductorItem, "_paint_lit", record)
    doc = _with_conductors("ne555-astable", [_run("a", 1, side="bottom")])

    _on_screen(view2d.BoardScene(doc, LOOKUP, side="bottom"))
    assert calls == ["a"]

    calls.clear()
    _on_screen(view2d.BoardScene(doc, LOOKUP, side="top"))
    assert not calls, "copper on the far face is a band, not a ridge"

    _on_paper(doc, view2d.BoardScene(doc, LOOKUP, side="bottom"), tmp_path)
    assert not calls, "the 1:1 print drew a ridge"


def test_a_runs_width_follows_its_buildup_on_screen(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    widths: dict[str, float] = {}
    real = view2d._stroke_pen
    current: list[str] = []
    real_paint = view2d.ConductorItem._paint_lit

    def paint(item, *args):  # type: ignore[no-untyped-def]
        current[:] = [item.conductor.id]
        real_paint(item, *args)

    def pen(colour, width):  # type: ignore[no-untyped-def]
        if colour == view2d.RUN_SCREEN_COLOUR:
            widths[current[0]] = width
        return real(colour, width)

    monkeypatch.setattr(view2d.ConductorItem, "_paint_lit", paint)
    monkeypatch.setattr(view2d, "_stroke_pen", pen)
    doc = _with_conductors(
        "ne555-astable",
        [
            _run("light", 1, side="bottom", buildup="light"),
            _run("normal", 3, side="bottom", buildup="normal"),
            _run("heavy", 5, side="bottom", buildup="heavy"),
        ],
    )
    _on_screen(view2d.BoardScene(doc, LOOKUP, side="bottom"))
    base = view2d.CONDUCTOR_STYLE["solder-trace"][1]
    assert widths["light"] < widths["normal"] < widths["heavy"]
    assert widths["normal"] == pytest.approx(base)
    assert widths["heavy"] == pytest.approx(base * view2d.RUN_BUILDUP_WIDTH["heavy"])


def test_a_wired_run_shows_its_spine_through_the_solder_on_screen() -> None:
    from perfboard_studio.model import SpineSpec

    plain = _run("p", 1, side="bottom")
    wired = _run(
        "w", 1, side="bottom", kind="solder-trace-wired", spine=SpineSpec(material="tinned-copper", gauge=0.6)
    )
    spine = view2d.SPINE_CORE
    middle = {}
    for name, conductor in (("plain", plain), ("wired", wired)):
        doc = _with_conductors("ne555-astable", [conductor])
        scene = view2d.BoardScene(doc, LOOKUP, side="bottom", show_ratsnest=False, show_rulers=False)
        item = next(i for i in scene.items() if isinstance(i, view2d.ConductorItem))
        pts = item._points()
        rect = scene.sceneRect()
        scale = 20
        image = QImage(round(rect.width() * scale), round(rect.height() * scale), QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        scene.render(painter, QRectF(0, 0, image.width(), image.height()), rect)
        painter.end()
        # halfway between two pads, where only the run itself is under the pixel
        a, b = pts[2], pts[3]
        x = (a.x() + b.x()) / 2 - rect.x()
        y = (a.y() + b.y()) / 2 - rect.y()
        middle[name] = image.pixelColor(round(x * scale), round(y * scale))

    def distance(c) -> int:  # type: ignore[no-untyped-def]
        return abs(c.red() - spine.red()) + abs(c.green() - spine.green()) + abs(c.blue() - spine.blue())

    assert distance(middle["wired"]) < 40
    assert distance(middle["plain"]) > 120


def test_a_sleeve_is_stripped_back_at_both_ends() -> None:
    from PySide6.QtCore import QPointF

    line = [QPointF(0, 0), QPointF(5, 0), QPointF(5, 4)]
    sleeve = view2d._trimmed(line, 0.9)
    assert sleeve[0] == QPointF(0.9, 0)
    assert sleeve[-1] == QPointF(5, 3.1)
    assert view2d._trimmed([QPointF(0, 0), QPointF(1.5, 0)], 0.9) == [], "no sleeve left"


def _paint_at(scene: view2d.BoardScene, px_per_mm: float) -> None:
    rect = scene.sceneRect()
    image = QImage(round(rect.width() * 6), round(rect.height() * 6), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    painter.scale(px_per_mm / 6, px_per_mm / 6)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), rect)
    painter.end()


def test_a_modules_art_is_cached_per_zoom_and_stretched_while_the_zoom_moves() -> None:
    """Chosen 2026-11-26: the illustrated art costs a few hundred gradients a part, so a
    module is rasterised once per zoom (``ArtCache``). A new zoom is first served from the
    image already held, stretched, and the scene is asked to paint again once it settles,
    when the second sight of that zoom fills the image afresh."""
    scene = view2d.BoardScene(_example("nano-relay"), LOOKUP, side="top")
    module = next(
        item for item in scene.component_items.values()
        if item.fp.body.archetype == "module-board" and item.art
    )
    cache = module.art_cache
    _paint_at(scene, 6)
    assert cache._image is None, "a scale seen once is painted directly"
    _paint_at(scene, 6)
    held = cache._image
    assert held is not None and not cache.stale
    _paint_at(scene, 6.6)
    assert cache.stale and cache._image is held, "a new zoom is the held image, stretched"
    assert scene.art_refresh.isActive(), "and the scene paints again when the zoom settles"
    _paint_at(scene, 6.6)
    assert cache._image is not held and not cache.stale


def test_a_modules_art_is_never_cached_on_paper(tmp_path: Path) -> None:
    """The 1:1 sheet is vectors as it always was: no raster of a module reaches it."""
    doc = _example("nano-relay")
    scene = view2d.BoardScene(doc, LOOKUP, side="top")
    export_pdf(doc.board, scene, tmp_path / "board.pdf")
    export_pdf(doc.board, scene, tmp_path / "board.pdf")
    assert all(item.art_cache._image is None for item in scene.component_items.values())
