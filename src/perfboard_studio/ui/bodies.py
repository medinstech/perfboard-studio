"""What each component archetype looks like, shared by the 2D and 3D views.

WHY THIS EXISTS AT ALL. The footprint library already describes every part properly:
``BodySpec.archetype`` says what kind of thing it is and ``BodySpec.dims`` gives its real
millimetre dimensions, for fifteen archetypes across sixty-one footprints. Both renderers
threw all of it away -- 3D extruded one grey cube per part and 2D filled one pale polygon --
so a DIP-8, a 10 mm electrolytic and a quarter-watt resistor were the same anonymous blob in
both views. Nothing was missing from the data; it simply was not being read.

THE OUTLINE IS NOT THE BODY. This is the specific mistake that made everything look wrong.
``Footprint.body_outline`` is the COURTYARD: a deliberately padded boundary around the pins
that DRC uses for overlap checks. For ``r-axial-3`` it spans 10.16 mm while the resistor
body is 5 mm long, so drawing the outline draws a box half again too big, with no leads and
no shape. The real body comes from ``dims`` and is centred on the pins -- which is what
:func:`placement_for` returns (worked out by ``footprints.body_extent``, which DRC reads
too), and why the parts now have leads with a body between them instead of a rectangle
covering both.

ONE TABLE, TWO RENDERERS. Colours live here rather than in either view so that a resistor is
the same beige in the editor, in the 3D view and in the build guide's step images. A part
that changed colour when the user turned the board over would undermine the one job the 3D
view has, which is to let someone check that what they are about to solder matches what they
meant (PLAN.md Sec 8.4).

NO ASSET LIBRARY, BY DECISION. PLAN.md's D6 fixes this as parametric generation: zero
assets, a body that cannot disagree with its own footprint, and no share-alike licence
inherited into an Apache-2.0 project (Sec 13 lists licence contamination as a high risk).
Everything here is derived from numbers already in the registry.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from perfboard_studio.drc import placed_body_box, placed_entry
from perfboard_studio.footprints import MIN_BODY_MM, body_extent, wire_entry
from perfboard_studio.geometry import (
    SubstrateEdges,
    board_note_centre_mm,
    hole_to_mm,
    mounting_hole_centre_mm,
    substrate_edges_mm,
    transform_offset,
)
from perfboard_studio.model import (
    Board,
    BodyArchetype,
    ComponentInstance,
    Footprint,
    PerfDocument,
    declared_pin_name,
    pin_name_of,
)

# ---------------------------------------------------------------------------
# Appearance
# ---------------------------------------------------------------------------

#: 2D silhouette shape. The 3D view builds a solid per archetype and does not use this.
type Silhouette = Literal["rect", "circle", "dcut", "rounded"]


@dataclass(frozen=True, slots=True)
class BodyStyle:
    """How one archetype is coloured, in both views."""

    fill: str
    edge: str
    #: Stripes, bands, polarity marks and pin-1 dots. Always readable against ``fill``.
    accent: str
    #: 3D shading hint: a metal can and a plastic case catch light very differently, and
    #: that difference is most of what makes a rendered board look like a board.
    metallic: bool = False
    #: A lens rather than a case. Drawn lighter in 2D and given a highlight in 3D.
    lens: bool = False


_PLASTIC_EDGE = "#0e0f13"

BODY_STYLES: dict[BodyArchetype, BodyStyle] = {
    # Axial parts split by polarity below -- a resistor and a DO-41 diode share an
    # archetype and look nothing alike.
    "axial-cylinder": BodyStyle(fill="#d9c9a1", edge="#7d6c46", accent="#3b2d18"),
    "radial-electrolytic": BodyStyle(fill="#1f2a44", edge="#0b1120", accent="#c9d2e0"),
    "disc-ceramic": BodyStyle(fill="#b9884a", edge="#6d4c25", accent="#2c1d0c"),
    "box-film": BodyStyle(fill="#c2652f", edge="#6f3617", accent="#f0e3d2"),
    "dip": BodyStyle(fill="#24262d", edge=_PLASTIC_EDGE, accent="#c3c8d2"),
    "to92": BodyStyle(fill="#26282e", edge=_PLASTIC_EDGE, accent="#c3c8d2"),
    "to220": BodyStyle(fill="#22242a", edge=_PLASTIC_EDGE, accent="#9aa3ad"),
    "led-round": BodyStyle(fill="#d6392f", edge="#7d1f18", accent="#ffd9d5", lens=True),
    "pin-header": BodyStyle(fill="#1c1e24", edge=_PLASTIC_EDGE, accent="#d8b45a"),
    "screw-terminal": BodyStyle(fill="#2f7d4f", edge="#164a2c", accent="#c8ccd2"),
    "potentiometer": BodyStyle(fill="#2b4f8f", edge="#14264a", accent="#b9c0ca"),
    "tactile-switch": BodyStyle(fill="#22242a", edge=_PLASTIC_EDGE, accent="#e6e2d6"),
    "crystal-hc49": BodyStyle(fill="#a8b0ba", edge="#5a626c", accent="#3a4048", metallic=True),
    "relay-box": BodyStyle(fill="#46566f", edge="#22303f", accent="#c8ccd2"),
    "generic-box": BodyStyle(fill="#6b7280", edge="#343a44", accent="#e6e8ec"),
    # The header's black and gold, because it IS a header -- inside a shroud.
    "box-header": BodyStyle(fill="#1c1e24", edge=_PLASTIC_EDGE, accent="#d8b45a"),
    # The same green as the side-entry terminal: it is the same family, plugged in upright.
    "screw-terminal-vertical": BodyStyle(fill="#2f7d4f", edge="#164a2c", accent="#c8ccd2"),
    # A module's own board: the blue solder mask most hobby modules are made in, with white
    # silkscreen -- the accent -- which is what its pin names are printed in.
    "module-board": BodyStyle(fill="#1f4f86", edge="#0e2b4d", accent="#eef2f7"),
}

#: A polarized axial part is a diode, not a resistor. Same archetype, different object.
_DIODE_STYLE = BodyStyle(fill="#1d1f24", edge=_PLASTIC_EDGE, accent="#e8ecf2")

_FALLBACK_STYLE = BODY_STYLES["generic-box"]


@dataclass(frozen=True, slots=True)
class Surface:
    """How a material catches light, for both views at once.

    ``BodyStyle`` already records WHAT a part is made of (``metallic``, ``lens``); this
    turns that into the numbers each renderer needs. It exists because the two facts had
    drifted apart: the 3D view read ``metallic`` in exactly one builder (``_box_pieces``)
    and every other archetype hardcoded a specular value -- including the HC-49 crystal,
    the one part in the registry that is literally a metal can and whose own flag was
    therefore being ignored by the code that draws it. The 2D view read neither flag at
    all, so a metal can and a plastic case differed only in hue.

    One table, two renderers (see the module docstring): a material that is changed here
    changes in the editor, in the 3D view and in the guide's step images together.
    """

    #: VTK specular reflectance and its exponent. Kept for the 2D view's gradient and
    #: for any renderer that has no PBR: they are a description of a HIGHLIGHT, which is
    #: all Phong has.
    specular: float
    specular_power: float
    #: 0..1, how strong a highlight the 2D view sweeps across the top of the body. Flat
    #: fill is what made every 2D part read as a sticker rather than an object.
    sheen: float
    #: WHAT THE THING IS MADE OF, for the 3D view's PBR shading, and the reason the render
    #: stopped looking like painted card. Two numbers rather than a highlight:
    #:
    #: ``metallic`` is 0 or 1 and nothing between -- a material either conducts and tints
    #: its own reflection or it does not -- and it is the single largest difference between
    #: a crystal can and a DIP. Phong has no way to say it at all, so a metal can was a grey
    #: plastic case with a brighter dot on it.
    #:
    #: ``roughness`` is what separates two parts of the SAME class on a bench: moulded
    #: epoxy scatters wide, a tinned can throws one long highlight down its length. It is
    #: also the number a person recognises without being told, which is why guessing at
    #: specular exponents never converged.
    metallic: float
    roughness: float


_PLASTIC_SURFACE = Surface(
    specular=0.18, specular_power=12.0, sheen=0.14, metallic=0.0, roughness=0.55
)
_METAL_SURFACE = Surface(
    specular=0.85, specular_power=50.0, sheen=0.40, metallic=1.0, roughness=0.30
)
#: A lens is brighter than metal and tighter than plastic: it is transmitting, not
#: reflecting, and the highlight is the thing that says "this is glass, not paint".
_LENS_SURFACE = Surface(
    specular=0.9, specular_power=70.0, sheen=0.55, metallic=0.0, roughness=0.06
)


def surface_for(style: BodyStyle) -> Surface:
    """The shading a style implies. ``lens`` wins over ``metallic``: a part is one or the
    other, and no archetype sets both."""
    if style.lens:
        return _LENS_SURFACE
    if style.metallic:
        return _METAL_SURFACE
    return _PLASTIC_SURFACE


def style_for(footprint: Footprint) -> BodyStyle:
    """The style for a footprint, honouring an explicit ``BodySpec.color`` override.

    The override replaces the fill only. A caller setting a colour is saying "this part is
    green", not "work out a whole new palette" -- so the edge and accent, which exist to
    stay legible against the fill, are left to the archetype.
    """
    archetype = footprint.body.archetype
    if archetype == "axial-cylinder" and footprint.polarized:
        base = _DIODE_STYLE
    else:
        base = BODY_STYLES.get(archetype, _FALLBACK_STYLE)
    override = footprint.body.color
    if override:
        return BodyStyle(
            fill=override,
            edge=base.edge,
            accent=base.accent,
            metallic=base.metallic,
            lens=base.lens,
        )
    return base


# ---------------------------------------------------------------------------
# Where the body actually sits
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BodyPlacement:
    """The physical body in component-local millimetres, before rotation or mirroring.

    Local space matches the footprint's own: +x is increasing column, +y increasing row,
    origin at the anchor pin. Both views apply the component's transform themselves, so
    nothing here needs to know about rotation.
    """

    silhouette: Silhouette
    #: Centre of the body, which is the centroid of the pin holes -- see placement_for.
    centre_x: float
    centre_y: float
    #: Extents in local x and y. Never zero: a body has to be drawable.
    size_x: float
    size_y: float
    #: Above the board surface.
    height: float
    #: The direction the part's leads run, so an axial body lies along its own wires and a
    #: 3D cylinder is turned the right way.
    axis: Literal["x", "y"]
    #: True when the part has a meaningful pin 1 / cathode / negative end to mark.
    polarized: bool

    @property
    def length(self) -> float:
        """The extent along ``axis``."""
        return self.size_x if self.axis == "x" else self.size_y

    @property
    def width(self) -> float:
        """The extent across ``axis``."""
        return self.size_y if self.axis == "x" else self.size_x


_SILHOUETTES: dict[BodyArchetype, Silhouette] = {
    "axial-cylinder": "rect",
    "radial-electrolytic": "circle",
    # A disc ceramic stands on edge, so from above it is a narrow rounded slab -- the disc
    # face is what you see from the SIDE, and drawing a circle in the top view would claim
    # it occupies twice the board it does.
    "disc-ceramic": "rounded",
    "box-film": "rect",
    "dip": "rect",
    "to92": "dcut",
    "to220": "rect",
    "led-round": "dcut",
    "pin-header": "rect",
    "screw-terminal": "rect",
    "potentiometer": "circle",
    "tactile-switch": "rect",
    "crystal-hc49": "rounded",
    "relay-box": "rounded",
    "generic-box": "rect",
    "box-header": "rect",
    "screw-terminal-vertical": "rect",
    "module-board": "rect",
}

#: Nothing is drawn thinner than this. The engine's floor for a body's width, re-exported
#: because the height below falls back to it too.
_MIN_MM = MIN_BODY_MM


def placement_for(footprint: Footprint, pitch: float) -> BodyPlacement:
    """The real body, centred on the part's pins, with what only a renderer needs added.

    The rectangle itself -- centre, size and the axis the leads run along -- is
    ``footprints.body_extent``, and it is not worked out a second time here. It used to be:
    this function WAS that arithmetic, until DRC needed to ask whether a body hangs past the
    edge of the board, and an engine rule cannot import the UI. So it moved, and the two
    renderers and the rule now read one answer. Everything its docstring says about centring
    on the pin centroid and about ``BODY_DIM_KEYS`` is true of what this returns.

    ``pitch`` converts the footprint's grid-step pin offsets to millimetres. Passed in
    rather than assumed to be 2.54, because ``Board.pitch`` is a field and a body placed on
    an assumed pitch would drift off its own pins on any board that sets it differently.
    """
    extent = body_extent(footprint, pitch)
    height = footprint.body_height or footprint.body.dims.get("height") or _MIN_MM
    return BodyPlacement(
        silhouette=_SILHOUETTES.get(footprint.body.archetype, "rect"),
        centre_x=extent.centre_x,
        centre_y=extent.centre_y,
        size_x=extent.size_x,
        size_y=extent.size_y,
        height=max(height, 0.6),
        axis=extent.axis,
        polarized=footprint.polarized,
    )


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Lead:
    """A visible lead from a pin hole to the edge of the body, in local mm."""

    from_x: float
    from_y: float
    to_x: float
    to_y: float


def leads_for(footprint: Footprint, placement: BodyPlacement, pitch: float) -> tuple[Lead, ...]:
    """Where a part's leads show between its pins and its body.

    Only for parts whose body is visibly smaller than their pin span -- a resistor bridging
    a three-hole span with a 5 mm body has a clear 2.5 mm of wire at each end, and drawing
    it is most of what makes the part read as a resistor rather than a block. Parts whose
    body already covers their pins (a DIP, a header) get none, and a can sits over its own
    leads so it gets none either.

    Each lead runs from the pin straight to the body edge along the part's axis, keeping the
    pin's own cross-axis position, so a part whose pins are not exactly on its centre line
    still gets leads that meet their pins.
    """
    if placement.silhouette == "circle" and footprint.body.archetype != "disc-ceramic":
        return ()

    leads: list[Lead] = []
    half_x = placement.size_x / 2
    half_y = placement.size_y / 2
    for pin in footprint.pins:
        pin_x, pin_y = pin.d_col * pitch, pin.d_row * pitch
        if placement.axis == "x":
            offset = pin_x - placement.centre_x
            if abs(offset) <= half_x + 0.05:
                continue  # The body already reaches this pin.
            edge_x = placement.centre_x + (half_x if offset > 0 else -half_x)
            leads.append(Lead(pin_x, pin_y, edge_x, pin_y))
        else:
            offset = pin_y - placement.centre_y
            if abs(offset) <= half_y + 0.05:
                continue
            edge_y = placement.centre_y + (half_y if offset > 0 else -half_y)
            leads.append(Lead(pin_x, pin_y, pin_x, edge_y))
    return tuple(leads)


# ---------------------------------------------------------------------------
# Polarity
# ---------------------------------------------------------------------------


#: Archetypes that are keyed even though the registry does not call them polarized. A DIP
#: has no electrical polarity -- which is what ``Footprint.polarized`` records -- and fitting
#: one backwards still destroys it, so its pin-1 dot must be drawn regardless.
_ALWAYS_KEYED: frozenset[BodyArchetype] = frozenset({"dip"})


def polarity_pin_offset(footprint: Footprint, pitch: float) -> tuple[float, float] | None:
    """Local mm of the pin that says which way round the part goes, or None if it is
    symmetrical.

    Always pin 1, whatever pin 1 happens to MEAN for that part. The registry names the pin
    where it is not obvious -- an electrolytic's pin 1 is '+', an LED's is 'A', the anode --
    and leaves it unnamed where the convention is settled, which for a diode makes pin 1 the
    cathode (the banded end, as KiCad's DO-41 has it).

    So this returns "which end is keyed", and each caller decides what to draw there: an
    axial band at pin 1 is a cathode stripe, an electrolytic's printed stripe goes on the
    OPPOSITE side because it marks the negative lead. Anything that has to state the
    polarity in words -- above all guide.py, where getting it backwards is exactly the
    failure the build guide exists to prevent -- must read the pin NAME rather than assume
    a meaning for pin 1.
    """
    if not footprint.polarized and footprint.body.archetype not in _ALWAYS_KEYED:
        return None
    for pin in footprint.pins:
        if pin.number == "1":
            return (pin.d_col * pitch, pin.d_row * pitch)
    return None


# ---------------------------------------------------------------------------
# The resistor colour code
# ---------------------------------------------------------------------------
#
# A resistor is the commonest part on almost any board, and until this existed every one
# of them was an anonymous beige blob in both views -- so "is the 10k in the right place"
# could not be answered by looking, which is the one job the 3D view has (PLAN.md Sec 8.4).
# The bands come from ``ComponentInstance.value``, which is already in the document, so
# nothing new is stored and nothing can disagree with the netlist.
#
# NEVER GUESS. A wrong band is worse than no band: someone would read it and fit the wrong
# part. So the parser is strict and returns None on anything it does not fully understand
# -- which is also what keeps a 100nF capacitor, a 2A fuse and an NE555 from being decoded
# as resistances by accident.

#: Digit colours, indexed by the digit. The multiplier band uses the same table.
_BAND_COLOURS: tuple[str, ...] = (
    "#141519",  # 0 black
    "#6b4423",  # 1 brown
    "#c62f2a",  # 2 red
    "#e2701f",  # 3 orange
    "#efc430",  # 4 yellow
    "#3c8f45",  # 5 green
    "#2062c4",  # 6 blue
    "#7a3fa3",  # 7 violet
    "#8f959d",  # 8 grey
    "#f2f4f8",  # 9 white
)
_BAND_GOLD = "#c9a227"
_BAND_SILVER = "#c6cad1"

#: `470`, `470R`, `4R7`, `10k`, `4k7`, `2.2k`, `1M`. The unit letter may stand in for the
#: decimal point, which is the whole reason this is not a float() call. Anything with a
#: letter outside this set -- `100nF`, `10uH`, `2A` -- fails to match and gets no bands.
_RESISTANCE_RE = re.compile(r"^(\d+)(?:[.,](\d+))?\s*([RKMG])?\s*(\d*)$", re.IGNORECASE)

_DECADE: dict[str, float] = {"R": 1.0, "K": 1e3, "M": 1e6, "G": 1e9}


def parse_resistance(value: str) -> float | None:
    """Ohms from a schematic value string, or None if it is not unambiguously a resistance.

    Lowercase ``m`` is read as MEGA rather than milli. That is the EDA convention every
    netlist this tool imports follows (`4m7` beside `4M7`), and a milliohm resistor is not
    a thing anyone fits to perfboard -- but it is the one deliberate ambiguity here, so it
    is written down rather than left to be discovered.
    """
    text = value.strip().rstrip("ΩΩ")  # Greek capital omega, and the ohm sign.
    for suffix in ("ohms", "ohm"):
        if text.lower().endswith(suffix):
            text = text[: -len(suffix)].strip()
    match = _RESISTANCE_RE.match(text)
    if match is None:
        return None
    whole, decimal, unit, trailing = match.groups()
    if decimal and trailing:
        return None  # `4.7k7` means nothing.
    if trailing and not unit:
        return None  # A bare `4 7` is not a value.
    mantissa = float(f"{whole}.{decimal or trailing or '0'}")
    ohms = mantissa * _DECADE[unit.upper()] if unit else mantissa
    return ohms if ohms > 0 else None


def resistance_bands(ohms: float) -> tuple[str, ...] | None:
    """The four printed bands for a resistance: two digits, a multiplier and a tolerance.

    Four rather than three because a real part has four and the fourth is the one at the
    end that tells you which way to read the other three. Gold, for the 5% that E24
    describes -- the series this is decoding.
    """
    if ohms <= 0 or not math.isfinite(ohms):
        return None
    exponent = math.floor(math.log10(ohms)) - 1
    mantissa = round(ohms / (10.0**exponent))
    if mantissa >= 100:  # 99.6 rounds to 100: carry it rather than emit a third digit.
        mantissa //= 10
        exponent += 1
    if exponent == -1:
        multiplier = _BAND_GOLD
    elif exponent == -2:
        multiplier = _BAND_SILVER
    elif 0 <= exponent < len(_BAND_COLOURS):
        multiplier = _BAND_COLOURS[exponent]
    else:
        return None  # Beyond what the code can print; no band beats a wrong band.
    tens, units = divmod(mantissa, 10)
    return (_BAND_COLOURS[tens], _BAND_COLOURS[units], multiplier, _BAND_GOLD)


def resistor_bands(footprint: Footprint, value: str) -> tuple[str, ...] | None:
    """The colour bands for a part, or None if it is not a resistor with a readable value.

    Gated on the footprint as well as the value: an axial body that IS polarized is a
    diode, which carries a cathode stripe instead and must never be given bands on top of
    it. ``style_for`` splits the same archetype the same way, for the same reason.
    """
    if footprint.body.archetype != "axial-cylinder" or footprint.polarized:
        return None
    ohms = parse_resistance(value)
    return None if ohms is None else resistance_bands(ohms)


__all__ = [
    "BODY_STYLES",
    "BodyPlacement",
    "BodyStyle",
    "Lead",
    "Silhouette",
    "Surface",
    "leads_for",
    "parse_resistance",
    "placement_for",
    "polarity_pin_offset",
    "resistance_bands",
    "resistor_bands",
    "style_for",
    "surface_for",
]


# ---------------------------------------------------------------------------
# Pin names beside the pins
# ---------------------------------------------------------------------------
#
# WHAT A BOARD IS WIRED BY. A screw terminal's four ways look the same, a devkit's thirty-
# eight pins look the same, and which one is 24V-L or GPIO4 is written nowhere on the board
# a person solders -- only in the part's pin names, which the sheet and the guide already
# print. So both views print them beside the pins as well, where they are needed, and one
# function decides where: the 2D view and the 3D view put each name in the same place, or
# the two pictures of one board would disagree about which pin is which.
#
# Where depends on what the part is. A MODULE has its names printed on its own board, as
# its silkscreen does: beside each pin, running in towards the middle. Anything else gets
# them on THIS board, just outside its body, running away from it -- a DIP's names down
# either side like a pinout drawing, a terminal's behind it rather than across its mouth.
# Only a part's DECLARED names are printed there: an LED's registry A and K on every LED
# would be noise, and a name somebody typed in is one they wanted seen.

#: Cap height of a printed pin name: silkscreen-sized, so it is millimetres, not pixels.
PIN_NAME_HEIGHT_MM = 0.9
#: On a module, how far from the pin's centre its name starts -- clear of the pad ring.
PIN_NAME_GAP_MM = 1.25
#: Off a module, how far past the body's edge a name starts, and never nearer the pin
#: than this -- a pad ring is 0.95 mm across its radius.
PIN_NAME_CLEAR_MM = 0.6
PIN_NAME_NEAREST_MM = 1.1
#: The longest a name is printed; longer ones are narrowed to fit.
PIN_NAME_MAX_MM = 6.0
#: How much of a module's board the block standing for its parts covers, each way. Both
#: views draw it this size, and a module's names stop short of it.
MODULE_BLOCK_FRACTION = 0.36
#: The smallest that block is drawn, so a tiny breakout still has something on it.
MODULE_BLOCK_MIN_MM = 3.0


def module_block_size(size_x: float, size_y: float) -> tuple[float, float]:
    """The block standing for what is on a module, centred on its board."""
    return (
        min(size_x, max(size_x * MODULE_BLOCK_FRACTION, MODULE_BLOCK_MIN_MM)),
        min(size_y, max(size_y * MODULE_BLOCK_FRACTION, MODULE_BLOCK_MIN_MM)),
    )


@dataclass(frozen=True, slots=True)
class PinLabel:
    """One pin's name and where it goes, in the footprint's own millimetres.

    Local like ``BodyPlacement``: +x along the columns, +y down the rows, pin 1 at the
    origin. Each view turns it with the part as it turns the body.
    """

    number: str
    name: str
    #: The pin's centre.
    x: float
    y: float
    #: Which way the name runs from its pin: one of (1, 0), (-1, 0), (0, 1), (0, -1).
    dx: float
    dy: float
    #: How far from the pin's centre the name starts, and the most it may run.
    start: float
    room: float
    #: On the module's own board rather than on this one.
    on_module: bool
    #: The name could run the other way just as well: the part's pins are in one row, so
    #: its body is as far away on both sides, and it has no mouth to keep clear. What
    #: ``lay_out_pin_names`` turns round when this side is taken.
    either_side: bool = False


def pin_labels(
    footprint: Footprint, component: ComponentInstance | None, pitch: float
) -> tuple[PinLabel, ...]:
    """Every named pin of a placed part, and where its name is printed."""
    if component is None or not footprint.pins:
        return ()
    placement = placement_for(footprint, pitch)
    module = footprint.body.archetype == "module-board"
    # Names run ACROSS the header rows: along a row each has one pitch of room, across it
    # has the width of the part.
    columns = {pin.d_col for pin in footprint.pins}
    rows = {pin.d_row for pin in footprint.pins}
    across_y = len(columns) >= len(rows)
    half = (placement.size_y if across_y else placement.size_x) / 2
    # A terminal's names go BEHIND it: in front is its mouth, where the wires are.
    entry = wire_entry(footprint)
    behind = None
    if entry is not None and not module:
        along_entry = entry[1] if across_y else entry[0]
        behind = -1.0 if along_entry > 0 else 1.0 if along_entry < 0 else None
    block = module_block_size(placement.size_x, placement.size_y)
    block_half = (block[1] if across_y else block[0]) / 2
    labels: list[PinLabel] = []
    for pin in footprint.pins:
        name = (
            pin_name_of(component, pin) if module else declared_pin_name(component, pin.number)
        )
        if not name:
            continue
        x, y = pin.d_col * pitch, pin.d_row * pitch
        toward = (placement.centre_y - y) if across_y else (placement.centre_x - x)
        either_side = False
        if module:
            sign = 1.0 if toward >= 0 else -1.0
            start = PIN_NAME_GAP_MM
            # Up to the block in the middle, which stands over anything printed under it.
            room = min(max(abs(toward) - start - block_half - 0.3, 2.0), PIN_NAME_MAX_MM)
        else:
            # Away from the body, starting just past its edge on that side.
            sign = behind if behind is not None else (-1.0 if toward > 1e-6 else 1.0)
            # The body's edge on that side: its half-size, less the pin's offset from its
            # centre towards that side (``toward`` points from the pin to the centre).
            start = max(half + sign * toward, 0.0) + PIN_NAME_CLEAR_MM
            start = max(start, PIN_NAME_NEAREST_MM)
            room = PIN_NAME_MAX_MM
            either_side = behind is None and abs(toward) <= 1e-6
        dx, dy = (0.0, sign) if across_y else (sign, 0.0)
        labels.append(
            PinLabel(pin.number, name, x, y, dx, dy, start, room, module, either_side)
        )
    return tuple(labels)


# WHEN THERE IS NO ROOM. ``pin_labels`` puts each part's names where they would go if the
# part were alone on the board, and on a real board it is not. The first one laid out with
# this program stood two terminals side by side, and each one's names ran under the other's
# body: printed, in both views, exactly where nobody could read them. So the names are laid
# out once more for the whole board. Each runs its own way until something stands in it --
# another part's body, the mouth of a terminal, a screw head, the edge of the board, a name
# already printed -- and then a part with its pins in one row prints them on its other side
# if that is clear; failing that a name is narrowed to the gap, while its letters still read
# as letters; and failing THAT it is left off, and the part says so, rather than being
# printed where it cannot be read.

#: A name narrowed further than this to fit a gap is left off instead.
PIN_NAME_MIN_SQUEEZE = 0.6
#: The dark tag a name on this board is printed on: how far it reaches past the ink at each
#: end, and how tall it is. Both views draw it this size, so it is what has to fit.
PIN_NAME_TAG_PAD_MM = 0.25
PIN_NAME_TAG_HEIGHT_MM = PIN_NAME_HEIGHT_MM * 1.7

#: ``(min_x, max_x, min_y, max_y)`` in the board's millimetres, rows growing downward.
type BoardBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class PrintedPinNames:
    """Every part's pin names as the rest of the board leaves room for them."""

    #: Per component id, the names to print -- turned, narrowed, or as ``pin_labels`` had
    #: them. A part with nothing to print has no entry.
    labels: dict[str, tuple[PinLabel, ...]]
    #: Per component id, the ``(number, name)`` of each pin whose name found no room.
    left_off: dict[str, tuple[tuple[str, str], ...]]


def lay_out_pin_names(
    document: PerfDocument,
    lookup: Callable[[str], Footprint | None],
    measure: Callable[[str], float],
) -> PrintedPinNames:
    """Every part's pin names, laid out against everything else on the board.

    ``measure`` is how long a name is printed, in millimetres, at ``PIN_NAME_HEIGHT_MM``:
    passed in, because only a view has a font to ask, and both views pass the same one so
    that they leave off the same names.
    """
    board = document.board
    edges = substrate_edges_mm(board)
    # Everything a name may not run under, by the part it belongs to.
    standing: list[tuple[str, BoardBox]] = []
    for comp in document.components:
        footprint = lookup(comp.footprint_id)
        if footprint is None:
            continue
        standing.append((comp.id, placed_body_box(comp, footprint, board)))
        entry = placed_entry(comp, footprint, board)
        if entry is not None:
            standing.append((comp.id, entry[0]))
    for mount in document.mounting_holes:
        centre = mounting_hole_centre_mm(mount, board)
        r = max(mount.head_diameter, mount.diameter) / 2
        standing.append(("", (centre.x - r, centre.x + r, centre.y - r, centre.y + r)))
    for note in document.board_notes:
        if note.side != "top":
            continue
        centre = board_note_centre_mm(note, board)
        # The box both views draw a label in: its text, set bold (a tenth wider than a pin
        # name's), and its tag round it.
        along = measure(note.text) * note.size_mm / PIN_NAME_HEIGHT_MM * 1.1 + 0.8
        across = note.size_mm * 1.8
        if note.rotation in (90, 270):
            along, across = across, along
        standing.append(
            ("", (centre.x - along / 2, centre.x + along / 2, centre.y - across / 2, centre.y + across / 2))
        )

    printed: list[BoardBox] = []
    labels: dict[str, tuple[PinLabel, ...]] = {}
    left_off: dict[str, tuple[tuple[str, str], ...]] = {}
    for comp in document.components:
        footprint = lookup(comp.footprint_id)
        if footprint is None:
            continue
        wanted = pin_labels(footprint, comp, board.pitch)
        if not wanted:
            continue
        if wanted[0].on_module:
            # On the module's own board, which nothing else stands on.
            labels[comp.id] = wanted
            continue
        others = [box for owner, box in standing if owner != comp.id]
        needs = [min(measure(label.name), label.room) for label in wanted]
        # Each pin's centre on the board and the way its name runs there, as ``pin_labels``
        # has it (1) and turned round (-1).
        runs = {
            turn: [_run_on_board(label, comp, board, turn) for label in wanted]
            for turn in (1.0, -1.0)
        }

        # A part in one row prints all its names on the same side: the side where more of
        # them fit, and the side ``pin_labels`` chose when that is a tie.
        turn = 1.0
        if all(label.either_side for label in wanted):
            fits = {
                way: sum(
                    _free_run(run, label.start, others + printed, edges) >= need
                    for label, need, run in zip(wanted, needs, runs[way], strict=True)
                )
                for way in (1.0, -1.0)
            }
            turn = -1.0 if fits[-1.0] > fits[1.0] else 1.0

        kept: list[PinLabel] = []
        dropped: list[tuple[str, str]] = []
        for label, need, run in zip(wanted, needs, runs[turn], strict=True):
            free = _free_run(run, label.start, others + printed, edges)
            if free >= need:
                room = min(label.room, free)
            elif free >= need * PIN_NAME_MIN_SQUEEZE:
                room = free
            else:
                dropped.append((label.number, label.name))
                continue
            kept.append(
                label
                if turn == 1.0 and room == label.room
                else replace(label, dx=label.dx * turn, dy=label.dy * turn, room=room)
            )
            printed.append(_tag_box(run, label.start, min(need, room)))
        if kept:
            labels[comp.id] = tuple(kept)
        if dropped:
            left_off[comp.id] = tuple(dropped)
    return PrintedPinNames(labels, left_off)


#: A pin's centre on the board, ``(x, y)`` mm, and the axis its name runs along there.
type BoardRun = tuple[float, float, int, int]


def _run_on_board(
    label: PinLabel, comp: ComponentInstance, board: Board, turn: float
) -> BoardRun:
    """Where ``label``'s pin is on the board and which way its name runs -- turned round
    when ``turn`` is -1 -- through the part's own placement transform."""
    anchor = hole_to_mm(comp.anchor, board)
    px, py = transform_offset(label.x, label.y, comp.rotation, comp.mirrored)
    ux, uy = transform_offset(label.dx * turn, label.dy * turn, comp.rotation, comp.mirrored)
    return anchor.x + px, anchor.y + py, round(ux), round(uy)


def _free_run(
    run: BoardRun, start: float, obstacles: list[BoardBox], edges: SubstrateEdges
) -> float:
    """How far a name starting ``start`` along ``run`` may go before its tag meets an
    obstacle or the edge of the board; zero when its start is covered already."""
    px, py, ux, uy = run
    begin = start - PIN_NAME_TAG_PAD_MM
    half = PIN_NAME_TAG_HEIGHT_MM / 2
    if ux:
        edge = (edges.max_x - px) if ux > 0 else (px - edges.min_x)
        low, high = edges.min_y, edges.max_y
        side = py
    else:
        edge = (edges.max_y - py) if uy > 0 else (py - edges.min_y)
        low, high = edges.min_x, edges.max_x
        side = px
    # A part hanging off the board (DRC says so) has pins off it, and a name beside one
    # would be printed on nothing.
    if side - half < low or side + half > high:
        return 0.0
    free = edge - PIN_NAME_TAG_PAD_MM - start
    for min_x, max_x, min_y, max_y in obstacles:
        if ux:
            near, far = (min_x - px, max_x - px) if ux > 0 else (px - max_x, px - min_x)
            across = (min_y - py, max_y - py)
        else:
            near, far = (min_y - py, max_y - py) if uy > 0 else (py - max_y, py - min_y)
            across = (min_x - px, max_x - px)
        if across[1] <= -half or across[0] >= half or far <= begin:
            continue
        if near <= begin:
            return 0.0
        free = min(free, near - PIN_NAME_TAG_PAD_MM - start)
    return max(free, 0.0)


def _tag_box(run: BoardRun, start: float, length: float) -> BoardBox:
    """The board box a printed name's tag covers."""
    px, py, ux, uy = run
    a = start - PIN_NAME_TAG_PAD_MM
    b = start + length + PIN_NAME_TAG_PAD_MM
    half = PIN_NAME_TAG_HEIGHT_MM / 2
    if ux:
        xs = (px + ux * a, px + ux * b)
        return min(xs), max(xs), py - half, py + half
    ys = (py + uy * a, py + uy * b)
    return px - half, px + half, min(ys), max(ys)
