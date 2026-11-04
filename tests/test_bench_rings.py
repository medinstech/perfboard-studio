"""A bench check's rings are dim and under the parts; a problem's, and a picked one's, on top.

The NE555 example's one ``solder-trace-proximity`` finding is a gap the router accepted
knowingly, and the build guide checks it at the bench (``guide.is_bench_check``). The
window counts it apart from the problems -- and drew its two rings in danger red over every
part, where they sit under LED1's dome: two red circles stacked into an "8", telling the
opposite story from the bar under them. What is pinned: nothing of a bench check's rings
paints over LED1 unless the finding is picked in the drawer, picked it does, and a real
problem's rings are where they always were.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.drc import DrcViolation, run_drc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.guide import is_bench_check
from perfboard_studio.ui.view2d import (
    BENCH_RING,
    BENCH_RING_Z,
    RISK_RING,
    RISK_RING_Z,
    BoardScene,
    RiskRingsItem,
    hole_to_screen,
)

NE555 = Path(__file__).resolve().parents[1] / "examples" / "ne555-astable.perf"
PX_PER_MM = 20


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _scene() -> tuple[BoardScene, list[DrcViolation]]:
    doc = persist.parse_document_or_throw(NE555.read_text(encoding="utf-8"))
    lookup = footprint_lookup()
    scene = BoardScene(doc, lookup, side="top", show_ratsnest=False, show_rulers=False)
    return scene, run_drc(doc, lookup)


def _led_body(scene: BoardScene) -> QRectF:
    led = next(item for item in scene.component_items.values() if item.comp.ref == "LED1")
    return led.mapRectToScene(led._local_body_rect())


def _render(scene: BoardScene, region: QRectF) -> QImage:
    image = QImage(round(region.width() * PX_PER_MM), round(region.height() * PX_PER_MM), QImage.Format.Format_ARGB32)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), region)
    painter.end()
    return image


def _rings(scene: BoardScene) -> list[RiskRingsItem]:
    return [item for item in scene.items() if isinstance(item, RiskRingsItem)]


def test_the_ne555s_proximity_finding_is_a_bench_check_under_led1() -> None:
    """The case this is about, so the rest of the file is not passing on a board that no
    longer has it."""
    scene, violations = _scene()
    bench = [v for v in violations if is_bench_check(v)]
    assert bench, "ne555-astable has a bench check"
    body = _led_body(scene)
    under = [
        hole for v in bench for hole in v.holes
        if body.contains(hole_to_screen(hole, scene.document.board, "top"))
    ]
    assert under, "a bench check's hole is under LED1"


#: How far from LED1's centre its dome is, everywhere: a 5 mm LED's lens, inside the 6.15 mm
#: flange whose flat on the cathode side is where the board shows through.
DOME_MM = 2.3


def _on_the_dome(scene: BoardScene, image: QImage, region: QRectF) -> list[int]:
    """The pixels of ``image`` (a render of ``region``) that are LED1's dome."""
    centre = _led_body(scene).center()
    pixels = []
    for y in range(image.height()):
        for x in range(image.width()):
            sx = region.left() + (x + 0.5) / PX_PER_MM
            sy = region.top() + (y + 0.5) / PX_PER_MM
            if (sx - centre.x()) ** 2 + (sy - centre.y()) ** 2 <= DOME_MM**2:
                pixels.append(image.pixel(x, y))
    return pixels


def test_a_bench_checks_rings_paint_nothing_over_led1_until_it_is_picked() -> None:
    scene, violations = _scene()
    region = _led_body(scene)
    bare = _on_the_dome(scene, _render(scene, region), region)
    scene.set_violations(violations)
    assert _on_the_dome(scene, _render(scene, region), region) == bare, (
        "a ring printed over LED1 while nobody asked for it"
    )

    holes = [hole for v in violations if is_bench_check(v) for hole in v.holes]
    scene.set_focused_holes(holes)
    assert _on_the_dome(scene, _render(scene, region), region) != bare, (
        "picked in the drawer, its rings come up over the part"
    )
    scene.set_focused_holes([])
    assert _on_the_dome(scene, _render(scene, region), region) == bare


def test_a_bench_check_is_ringed_dim_under_the_parts_and_a_problem_red_over_them() -> None:
    scene, violations = _scene()
    led = next(item for item in scene.component_items.values() if item.comp.ref == "LED1")
    scene.set_violations(violations)
    (bench,) = _rings(scene)
    assert bench.colour == BENCH_RING and bench.zValue() == BENCH_RING_Z < led.zValue()

    # The same finding with one hole named is not a bench check, and is drawn as it always was.
    proximity = next(v for v in violations if is_bench_check(v))
    problem = dataclasses.replace(proximity, holes=proximity.holes[:1])
    assert not is_bench_check(problem)
    scene.set_violations([problem])
    (ring,) = _rings(scene)
    assert ring.colour == RISK_RING and ring.zValue() == RISK_RING_Z > led.zValue()
