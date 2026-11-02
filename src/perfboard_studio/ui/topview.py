"""What a part looks like from straight above: named shapes in the footprint's local mm.

WHY THIS EXISTS. The 2D view drew a part from its archetype, and a DIP came out as a black
block as wide as its pin rows with grey circles on its edges -- nothing like the part on the
bench, where the body is narrower than the rows, each leg's shoulder is a metal tab running
out to its hole, and pin 1's end has a notch. Where KiCad has the package, its top view is
MEASURED from the very meshes the 3D view draws (``tools/make_topviews.py`` writes
``models/topviews.json``), so the two views cannot show two different parts. Where it has
not, the shapes are parametric and always inside ``footprints.body_extent``: the drawing
follows the geometry DRC measures, never the other way round.

WHAT A SHAPE IS. A role and a QPainterPath, in the footprint's own frame (pin 1 at the origin,
x along the columns, y down the rows), painted in the order given:

    body      the case's flat top           plastic        a second moulding
    flank     the case's sloped sides       metal          leads, tabs, a can top, a screw
    recess    a notch or vent in the case   metal-recess   a screw's slot, a can's vent
    marking   a band, a stripe

WHAT IS NOT HERE. How a role is inked, the light and the contact shadow are the painter's
(``view2d``), and the colours are ``bodies.BODY_STYLES`` as ever. A part's turn and mirror are
applied by whoever draws it, as for every other shape in local mm.

NOTHING HERE READS A FILE UNTIL IT IS ASKED FOR ONE, and a missing or unreadable data file
draws every part from the parametric shapes, as a missing mesh draws the generated body.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPolygonF

from perfboard_studio.footprints import body_extent
from perfboard_studio.model import Footprint, Mm

from . import partmodels

TOPVIEWS_PATH = partmodels.MODELS_DIR / "topviews.json"

#: Every role a shape may have, in the order a painter needs no other than the data's.
ROLES = ("body", "flank", "recess", "plastic", "metal", "metal-recess", "marking")


@dataclass
class TopView:
    """One footprint seen from above."""

    shapes: list[tuple[str, QPainterPath]] = field(default_factory=list)
    #: Everything that stands on the board, for a contact shadow.
    silhouette: QPainterPath = field(default_factory=QPainterPath)
    #: The case alone, to clip light to.
    body: QPainterPath = field(default_factory=QPainterPath)
    #: Where a chip's print goes, and whether it runs down the part rather than across.
    marking: QRectF | None = None
    marking_vertical: bool = False
    #: Pin centres the top view hides (under a TO-220, a can, a relay). The 2D view is what
    #: the part is soldered by, so a hidden pin is still marked.
    hidden_pins: tuple[tuple[float, float], ...] = ()
    #: Where the shapes came from: a KiCad package, or "parametric".
    source: str = "parametric"


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    try:
        loaded = json.loads(TOPVIEWS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _path(rings: Sequence[Sequence[float]]) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    for ring in rings:
        points = [QPointF(ring[i], ring[i + 1]) for i in range(0, len(ring) - 1, 2)]
        if len(points) >= 3:
            path.addPolygon(QPolygonF(points))
            path.closeSubpath()
    return path


def _measured(model_id: str) -> TopView | None:
    entry = _data().get(model_id)
    if not isinstance(entry, dict):
        return None
    view = TopView(source=str(entry.get("source", model_id)))
    for shape in entry.get("shapes", ()):
        role = shape.get("role")
        if role in ROLES:
            view.shapes.append((role, _path(shape.get("rings", ()))))
    view.silhouette = _path(entry.get("silhouette", ()))
    for role, path in view.shapes:
        if role in ("body", "flank", "recess"):
            view.body = view.body.united(path)
    return view


def _repeated(pieces: Sequence[tuple[TopView, float, float]], source: str) -> TopView:
    """Measured pieces put down at their pins: a header's pin at every hole, a terminal
    block's head, ways and tail -- the same repetition the 3D view draws."""
    view = TopView(source=source)
    for piece, x, y in pieces:
        view.shapes.extend((role, path.translated(x, y)) for role, path in piece.shapes)
        view.silhouette = view.silhouette.united(piece.silhouette.translated(x, y))
        view.body = view.body.united(piece.body.translated(x, y))
    return view


def _pins_mm(footprint: Footprint, pitch: Mm) -> list[tuple[float, float]]:
    return [(pin.d_col * pitch, pin.d_row * pitch) for pin in footprint.pins]


def _from_models(footprint: Footprint, pitch: Mm) -> TopView | None:
    arch = footprint.body.archetype
    pins = _pins_mm(footprint, pitch)
    if arch == "pin-header":
        pin = _measured("hdr-pin")
        return None if pin is None else _repeated([(pin, x, y) for x, y in pins], pin.source)
    whole = _measured(footprint.id)
    if whole is not None:
        return whole
    if arch in ("screw-terminal", "screw-terminal-vertical") and len(pins) >= 2:
        stem = partmodels.TERMINAL_HEAD if arch == "screw-terminal" else partmodels.VERTICAL_HEADER_HEAD
        prefix = stem.removesuffix("-head")
        head, way, tail = (_measured(f"{prefix}-{part}") for part in ("head", "way", "tail"))
        if head is None or way is None or tail is None:
            return None
        placed = [(head, *pins[0]), *((way, x, y) for x, y in pins[1:-1]), (tail, *pins[-1])]
        return _repeated(placed, head.source)
    return None


def _rect(left: float, top: float, width: float, height: float, radius: float = 0.0) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(left, top, width, height), radius, radius)
    return path


def _circle(cx: float, cy: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def _parametric(footprint: Footprint, pitch: Mm) -> TopView:
    """A package KiCad has no model of, drawn INSIDE ``body_extent``."""
    extent = body_extent(footprint, pitch)
    cx, cy, sx, sy = extent.centre_x, extent.centre_y, extent.size_x, extent.size_y
    left, top = cx - sx / 2, cy - sy / 2
    dims = footprint.body.dims
    pins = _pins_mm(footprint, pitch)
    view = TopView()
    arch = footprint.body.archetype
    if arch == "box-header":
        wall, slot = 1.0, float(dims.get("keySlot", 4.5))
        outer = _rect(left, top, sx, sy, 0.4)
        cavity = _rect(left + wall, top + wall, sx - 2 * wall, sy - 2 * wall, 0.2)
        key = _rect(cx - slot / 2, top + sy - wall - 0.05, slot, wall + 0.1)
        view.shapes = [("body", outer.subtracted(cavity).subtracted(key)), ("recess", cavity.united(key))]
        view.shapes += [("metal", _rect(x - 0.32, y - 0.32, 0.64, 0.64)) for x, y in pins]
        view.body = outer
    elif arch == "potentiometer":
        r = min(sx, sy) / 2
        view.shapes = [
            ("body", _circle(cx, cy, r)),
            ("metal", _circle(cx, cy, r * 0.59)),
            ("plastic", _circle(cx, cy, r * 0.375)),
            ("recess", _rect(cx - 0.5, cy - r * 0.375, 1.0, r * 0.75)),
        ]
        view.body = _circle(cx, cy, r)
    elif arch == "smd-adapter":
        adapter = _rect(left, top, sx, sy, 0.3)
        view.shapes = [("body", adapter)]
        view.shapes += [("metal", _circle(x, y, 0.85)) for x, y in pins]
        chip_l, chip_w = float(dims["chipLength"]), float(dims["chipWidth"])
        span, chip_pitch = float(dims["chipSpan"]), float(dims["chipPitch"])
        count = len(footprint.pins) // 2
        for i in range(count):
            y = cy - (count - 1) * chip_pitch / 2 + i * chip_pitch
            view.shapes.append(("metal", _rect(cx - span / 2, y - 0.2, span, 0.4)))
        view.shapes.append(("plastic", _rect(cx - chip_w / 2, cy - chip_l / 2, chip_w, chip_l, 0.15)))
        view.shapes.append(("recess", _circle(cx - chip_w / 2 + 0.6, cy - chip_l / 2 + 0.6, 0.3)))
        view.body = adapter
        view.marking = QRectF(cx - chip_w / 2 + 0.3, cy - chip_l / 2 + 0.3, chip_w - 0.6, chip_l - 0.6)
        view.marking_vertical = True
    else:
        outline = _rect(left, top, sx, sy, 0.3)
        view.shapes = [("body", outline)]
        view.body = outline
        if arch == "relay-box":
            view.marking = QRectF(left + 2, top + 2, sx - 4, sy - 4)
    for _role, path in view.shapes:
        view.silhouette = view.silhouette.united(path)
    return view


def _top_view(footprint: Footprint, pitch: Mm) -> TopView:
    view = _from_models(footprint, pitch) or _parametric(footprint, pitch)
    if footprint.body.archetype == "dip" and view.marking is None:
        box = view.body.boundingRect()
        view.marking = box.adjusted(1.2, 2.0, -1.2, -1.2)
        view.marking_vertical = True
    metal = QPainterPath()
    for role, path in view.shapes:
        if role in ("metal", "metal-recess"):
            metal = metal.united(path)
    view.hidden_pins = tuple(
        (x, y) for x, y in _pins_mm(footprint, pitch) if not metal.contains(QPointF(x, y))
    )
    return view


#: Per footprint id and pitch. Keyed on the id, not the footprint, because a footprint holds
#: a dict and is not hashable -- and an id IS one footprint: a generated id rebuilds the same
#: footprint every time it is asked for.
_CACHE: dict[tuple[str, Mm], TopView] = {}


def top_view(footprint: Footprint, pitch: Mm) -> TopView:
    """The footprint from above, measured where KiCad has the package and parametric where
    not. Cached per footprint and pitch; the paths are shared, so a caller transforms a copy
    (``QPainterPath`` is copy-on-write, and ``QTransform.map`` returns a new one)."""
    key = (footprint.id, pitch)
    view = _CACHE.get(key)
    if view is None:
        view = _CACHE[key] = _top_view(footprint, pitch)
    return view
