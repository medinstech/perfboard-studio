"""What a part looks like from straight above: named shapes in the footprint's local mm.

WHY THIS EXISTS. The 2D view drew a part from its archetype, and a DIP came out as a black
block as wide as its pin rows with grey circles on its edges -- nothing like the part on the
bench, where the body is narrower than the rows, each leg's shoulder is a metal tab running
out to its hole, and pin 1's end has a notch. Where KiCad has the package, its top view is
MEASURED from the very meshes the 3D view draws (``tools/make_topviews.py`` writes
``models/topviews.json``), so the two views cannot show two different parts. Where it has
not, the shapes are parametric and always inside ``footprints.body_extent``: the drawing
follows the geometry DRC measures, never the other way round.

WHAT A SHAPE IS. A role, a QPainterPath and an ink, in the footprint's own frame (pin 1 at
the origin, x along the columns, y down the rows), painted in the order given:

    body      the case's flat top           plastic        a second moulding
    flank     the case's sloped sides       metal          leads, tabs, a can top, a screw
    recess    a notch or vent in the case   metal-recess   a screw's slot, a can's vent
    marking   a band, a stripe

The ink is a measured marking's own colour -- the one the 3D view draws its piece in, so an
LCD's black bezel and its glass are two colours in both views -- and ``None`` for every
other shape.

WHAT IS NOT HERE. How a role is inked, the light and the contact shadow are the painter's
(``view2d``), and the colours are ``bodies.BODY_STYLES`` as ever. A part's turn and mirror are
applied by whoever draws it, as for every other shape in local mm.

NOTHING HERE READS A FILE UNTIL IT IS ASKED FOR ONE, and a missing or unreadable data file
draws every part from the parametric shapes, as a missing mesh draws the generated body.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPolygonF

from perfboard_studio.footprints import body_extent, standing_pin
from perfboard_studio.model import Footprint, Mm

from . import partmodels

TOPVIEWS_PATH = partmodels.MODELS_DIR / "topviews.json"

#: Every role a shape may have, in the order a painter needs no other than the data's.
ROLES = ("body", "flank", "recess", "plastic", "metal", "metal-recess", "marking")

#: A role, its outline, and the colour a measured marking was drawn in (else ``None``).
Shape = tuple[str, QPainterPath, str | None]


@dataclass
class TopView:
    """One footprint seen from above."""

    shapes: list[Shape] = field(default_factory=list)
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
    #: The part of the case that says which way round the part goes, for the painter to ink:
    #: an electrolytic's stripe, an LED's flat side, a diode's band (``_polarity``). Empty
    #: for a part that is the same either way round.
    polarity: QPainterPath = field(default_factory=QPainterPath)
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
            ink = shape.get("color")
            view.shapes.append(
                (role, _path(shape.get("rings", ())), ink if isinstance(ink, str) else None)
            )
    view.silhouette = _path(entry.get("silhouette", ()))
    for role, path, _ink in view.shapes:
        if role in ("body", "flank", "recess"):
            view.body = view.body.united(path)
    return view


def _repeated(pieces: Sequence[tuple[TopView, float, float]], source: str) -> TopView:
    """Measured pieces put down at their pins: a header's pin at every hole, a terminal
    block's head, ways and tail -- the same repetition the 3D view draws."""
    view = TopView(source=source)
    for piece, x, y in pieces:
        view.shapes.extend((role, path.translated(x, y), ink) for role, path, ink in piece.shapes)
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
        view.shapes = [
            ("body", outer.subtracted(cavity).subtracted(key), None),
            ("recess", cavity.united(key), None),
        ]
        view.shapes += [("metal", _rect(x - 0.32, y - 0.32, 0.64, 0.64), None) for x, y in pins]
        view.body = outer
    elif arch == "potentiometer":
        r = min(sx, sy) / 2
        view.shapes = [
            ("body", _circle(cx, cy, r), None),
            ("metal", _circle(cx, cy, r * 0.59), None),
            ("plastic", _circle(cx, cy, r * 0.375), None),
            ("recess", _rect(cx - 0.5, cy - r * 0.375, 1.0, r * 0.75), None),
        ]
        view.body = _circle(cx, cy, r)
    elif arch == "smd-adapter":
        adapter = _rect(left, top, sx, sy, 0.3)
        view.shapes = [("body", adapter, None)]
        view.shapes += [("metal", _circle(x, y, 0.85), None) for x, y in pins]
        chip_l, chip_w = float(dims["chipLength"]), float(dims["chipWidth"])
        span, chip_pitch = float(dims["chipSpan"]), float(dims["chipPitch"])
        count = len(footprint.pins) // 2
        for i in range(count):
            y = cy - (count - 1) * chip_pitch / 2 + i * chip_pitch
            view.shapes.append(("metal", _rect(cx - span / 2, y - 0.2, span, 0.4), None))
        view.shapes.append(
            ("plastic", _rect(cx - chip_w / 2, cy - chip_l / 2, chip_w, chip_l, 0.15), None)
        )
        view.shapes.append(("recess", _circle(cx - chip_w / 2 + 0.6, cy - chip_l / 2 + 0.6, 0.3), None))
        view.body = adapter
        view.marking = QRectF(cx - chip_w / 2 + 0.3, cy - chip_l / 2 + 0.3, chip_w - 0.6, chip_l - 0.6)
        view.marking_vertical = True
    else:
        outline = _rect(left, top, sx, sy, 0.3)
        view.shapes = [("body", outline, None)]
        view.body = outline
        if arch == "relay-box":
            view.marking = QRectF(left + 2, top + 2, sx - 4, sy - 4)
    for _role, path, _ink in view.shapes:
        view.silhouette = view.silhouette.united(path)
    return view


#: Half the angle of the stripe sector an electrolytic's ring is inked over, at least: a
#: printed stripe is a broad band down the sleeve, and seen from above it has to be more
#: than the sliver of it KiCad's model shows past the can's top.
STRIPE_HALF_ANGLE_DEG = 40.0
#: The same for the LED's flat side, on the outer rim of its flange: the flat is a chord,
#: and the eye reads the side it is on. Inked over the whole flange it made half the LED
#: pink; the rim reads as the edge it is.
FLAT_HALF_ANGLE_DEG = 45.0
#: Where the rim starts, as a share of the case's radius -- and never narrower than
#: ``FLAT_RIM_MIN_MM``, or a 3 mm LED's rim was a hairline at the opening zoom.
FLAT_RIM_SHARE = 0.8
FLAT_RIM_MIN_MM = 0.5
#: Where the ring round a standing diode's cap starts, as a share of its radius.
BAND_RING_SHARE = 0.7


def _wedge(centre: QPointF, towards: tuple[float, float], half_angle: float, reach: float) -> QPainterPath:
    """A pie slice from ``centre`` round the direction ``towards`` (local mm, y down)."""
    angle = math.degrees(math.atan2(-towards[1], towards[0]))  # Qt's arcs turn with y up.
    wedge = QPainterPath()
    wedge.moveTo(centre)
    wedge.arcTo(
        QRectF(centre.x() - reach, centre.y() - reach, 2 * reach, 2 * reach),
        angle - half_angle,
        2 * half_angle,
    )
    wedge.closeSubpath()
    return wedge


def _pin_mm(footprint: Footprint, pitch: Mm, *, name: str | None = None, number: str | None = None) -> tuple[float, float] | None:
    for pin in footprint.pins:
        if (name is not None and pin.name == name) or (number is not None and pin.number == number):
            return (pin.d_col * pitch, pin.d_row * pitch)
    return None


def _polarity(footprint: Footprint, view: TopView, pitch: Mm) -> QPainterPath:
    """Where a polarized part says which way round it goes, as a region of its measured case.

    A REVERSED ELECTROLYTIC CAN BURST, and seen from above the measured can is mostly its
    aluminium top: the stripe on its sleeve showed as a thin wedge in the ring round it. So
    the ring is inked over the sector towards the negative lead, at least
    ``STRIPE_HALF_ANGLE_DEG`` either side and wider where the model's own stripe is. An
    LED's flat side is the flange on its cathode's side; a diode's band is the band the
    model has, or one at the cathode end. Inside the case, so it is ink and not geometry.
    """
    # Simplified: the measured paths are odd-even rings, and a union of overlapping ones
    # leaves holes where two of them cover the same ground.
    case = view.body.simplified()
    if case.isEmpty() or not footprint.polarized:
        return QPainterPath()
    box = case.boundingRect()
    centre = box.center()
    reach = max(box.width(), box.height())
    marking = QPainterPath()
    for role, path, _ink in view.shapes:
        if role == "marking":
            marking = marking.united(path)
    archetype = footprint.body.archetype
    if archetype == "radial-electrolytic":
        negative = _pin_mm(footprint, pitch, name="-") or _pin_mm(footprint, pitch, number="2")
        if negative is None:
            return marking
        towards = (negative[0] - centre.x(), negative[1] - centre.y())
        half = STRIPE_HALF_ANGLE_DEG
        heading = math.atan2(towards[1], towards[0])
        for index in range(marking.elementCount()):
            point = marking.elementAt(index)
            off = math.atan2(point.y - centre.y(), point.x - centre.x()) - heading
            off = math.degrees((off + math.pi) % (2 * math.pi) - math.pi)
            if abs(off) < 90.0:
                half = max(half, abs(off))
        return case.united(marking).simplified().intersected(_wedge(centre, towards, half, reach))
    if archetype == "led-round":
        cathode = _pin_mm(footprint, pitch, name="K") or _pin_mm(footprint, pitch, number="2")
        if cathode is None:
            return QPainterPath()
        inner = QPainterPath()
        radius = max(box.width(), box.height()) / 2
        start = min(radius * FLAT_RIM_SHARE, radius - FLAT_RIM_MIN_MM)
        inner.addEllipse(centre, start, start)
        rim = case.subtracted(inner)
        towards = (cathode[0] - centre.x(), cathode[1] - centre.y())
        return rim.intersected(_wedge(centre, towards, FLAT_HALF_ANGLE_DEG, reach))
    if archetype == "axial-upright":
        # From above a diode stood on end is its end cap, and its band shows only when the
        # banded end -- the cathode, pin 1 -- is the one at the top: a ring round the cap.
        # Standing on pin 1, the band is down by the board, and nothing is drawn the part
        # does not show.
        stands = standing_pin(footprint)
        if stands is None or stands.number == "1":
            return QPainterPath()
        inner = QPainterPath()
        radius = max(box.width(), box.height()) / 2
        inner.addEllipse(centre, radius * BAND_RING_SHARE, radius * BAND_RING_SHARE)
        return case.subtracted(inner)
    if archetype == "axial-cylinder":
        if not marking.isEmpty():
            return marking
        cathode = _pin_mm(footprint, pitch, number="1")
        if cathode is None:
            return QPainterPath()
        band = QRectF(box)
        if box.width() >= box.height():
            band.setWidth(box.width() * 0.17)
            if cathode[0] > centre.x():
                band.moveRight(box.right())
        else:
            band.setHeight(box.height() * 0.17)
            if cathode[1] > centre.y():
                band.moveBottom(box.bottom())
        strip = QPainterPath()
        strip.addRect(band)
        return case.intersected(strip)
    return QPainterPath()


def _top_view(footprint: Footprint, pitch: Mm) -> TopView:
    view = _from_models(footprint, pitch) or _parametric(footprint, pitch)
    if footprint.body.archetype == "dip" and view.marking is None:
        box = view.body.boundingRect()
        if box.width() > box.height():
            # A DIP-4 -- an optocoupler's case, Sharp's PC817 6.5 x 4.58 -- is wider than it is
            # long, and its print runs across it: on its flat top, under the notch. The margins
            # a long DIP keeps for its notch and its far end left a PC817 1.7 mm of its 4.9 mm
            # case, and its name a third of a millimetre tall.
            flat = next((path.boundingRect() for role, path, _ink in view.shapes if role == "body"), box)
            notch = max(
                (path.boundingRect().bottom() for role, path, _ink in view.shapes if role == "recess"),
                default=flat.top(),
            )
            view.marking = QRectF(flat.left(), notch, flat.width(), flat.bottom() - notch)
        else:
            view.marking = box.adjusted(1.2, 2.0, -1.2, -1.2)
            view.marking_vertical = True
    metal = QPainterPath()
    for role, path, _ink in view.shapes:
        if role in ("metal", "metal-recess"):
            metal = metal.united(path)
    view.hidden_pins = tuple(
        (x, y) for x, y in _pins_mm(footprint, pitch) if not metal.contains(QPointF(x, y))
    )
    if view.source != "parametric":
        view.polarity = _polarity(footprint, view, pitch)
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
