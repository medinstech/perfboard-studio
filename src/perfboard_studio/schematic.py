"""The netlist, drawn: a schematic generated from the document, never stored in it.

The board answers "where does this go"; nothing in this application has ever answered
"what am I building". LVS says ``net VOUT is open`` and the ratsnest draws a line across
the copper, and both of those are statements about a net the user has no way to LOOK at.
This module is that view: it takes ``doc.nets`` -- the schematic's intent, the thing every
other module derives from -- and produces a drawing of it.

**It is generated unless somebody has drawn on it.** A KiCad netlist carries no symbol
positions, so on the way in there is nothing to read and the sheet has to be laid out from
the connections alone; that is what most of this module does. A document somebody has
arranged carries its own positions, and they are omitted from the file when empty, which is
what keeps the byte-for-byte format
(``test_persist.py::test_golden_round_trip_byte_identical``) intact for every document that
has not been drawn on. Either way: same document in, same drawing out -- pure, no clock, no
RNG, no filesystem, ties broken by reference and net id -- which is also what lets the
layout be compared against a golden file rather than looked at.

**THE CIRCUIT IS ``doc.nets``, AND THE SHEET IS ONLY HOW IT WAS DRAWN.** The design
itself — which parts exist (``doc.parts``), what they are, what is wired to what
(``doc.nets``) — is edited through the command bus like everything else, and that is the
one answer to what is connected: LVS, the router, the placer, the guide and the board all
read it and none of them knows anything about a sheet.

The DRAWING can be either derived or stored, and which one a document gets is decided by
whether ``doc.sheet`` is empty — see "The sheet somebody drew" below. Derived is the
default and is what every netlist import produces: a sheet nobody has touched is laid out
from the netlist every time, so there is nothing to keep in step. Stored is what a person
gets the moment they move, turn or wire anything, and it still adds no second answer about
connectivity, because a stored wire carries no net id.

THREE DECISIONS CARRY THE LEGIBILITY, AND EACH IS THE ONE THAT KEEPS IT FROM BEING A
HAIRBALL.

- **Ground and power become rail glyphs, not wires** (``SchematicOptions.rail_classes``).
  A GND net touching eleven pins drawn as wires is eleven lines crossing everything on the
  sheet; every schematic ever drawn hangs a ground symbol off the pin instead. The classes
  are already in the document -- ``Net.net_class``, which ``parsers.kicad.infer_net_class``
  fills in on import -- so this costs nothing and is the single largest difference between
  a readable sheet and an unreadable one.
- **A symbol is drawn only where the registry knows what every lead IS.** A resistor, a
  capacitor, a diode, an LED and a crystal get their real shapes, and polarity comes from
  the registry's own pin names (a plus, a ``K``, an ``A``) with pin 1 as the cathode for a
  polarised part that has none -- exactly the rule ``guide._polarity_note`` follows, and
  for the same reason: an LED's pin 1 is its anode and a diode's is its cathode, so a
  convention keyed on pin 1 alone draws one of the two backwards. Where the registry does
  not know -- a TO-92 has no E/B/C in it, a tactile switch no pole -- the part is a
  labelled box with numbered pins. Drawing a transistor symbol would assert a lead
  assignment nothing in this codebase holds.
- **Symbols sit in a column/row grid and wires run only in the channels between them**, so
  no wire can cross a symbol -- not as a tuning parameter, as a consequence of where the
  tracks are allowed to be. Verticals live in the channel between two columns, horizontal
  trunks in the channel between two rows, and each channel widens to fit the tracks
  assigned to it by a left-edge sweep. Wires still cross each other, which is what junction
  dots are for; that is a schematic, not a defect.

Everything is millimetres on a 2.54 mm grid, which is the grid schematics are drawn on and
the same scene unit ``ui/view2d.py`` already uses, so the renderer needs no scale factor.
Coordinates grow right and down, matching the rest of the application.
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict, deque
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

from .connectivity import FootprintLookup
from .model import (
    BodyArchetype,
    ComponentInstance,
    Footprint,
    Mm,
    Net,
    NetClass,
    NetId,
    NetNode,
    PartSymbol,
    PerfDocument,
    Point2,
    Rotation,
    SchematicPart,
    SheetNoteKind,
    SheetWire,
    SymbolPlacement,
    pin_name_of,
    pin_number_sort_key,
)

# ---------------------------------------------------------------------------
# The sheet's units
# ---------------------------------------------------------------------------

#: Which way a pin's lead points out of its body.
type PinSide = Literal["left", "right", "top", "bottom"]

#: 0.1 inch. Schematics are drawn on this grid, KiCad's default is this grid, and every
#: coordinate this module emits is a multiple of it or a half of one.
GRID_MM: Mm = 2.54

#: One routing track. A channel carrying n of them is n of these wide, plus a margin.
TRACK_PITCH_MM: Mm = GRID_MM

#: The narrowest a channel gets, whatever it has to carry. Wide enough for a rail glyph to
#: drop into and for two symbols not to touch.
MIN_CHANNEL_MM: Mm = 4 * GRID_MM

#: The room a rail glyph occupies at ``Rail.at``: half-width across the stub, and depth
#: along it past the anchor.
#:
#: ONE FACT, TWO CONSUMERS -- the shape this codebase uses for ``heat-proximity`` and for
#: ``stripboard.MIN_SEPARABLE_GAP``. The renderer draws the bars inside this box and the
#: layout keeps every other run out of it, so a renderer that drew a wider glyph would be
#: putting bars through wires the layout believed it had cleared.
#: ``test_nothing_is_drawn_through_a_rail_glyph`` measures the layout half.
#:
#: BOTH MUST STAY UNDER ``TRACK_PITCH_MM``, and that is what makes the guarantee cheap
#: rather than another allocation pass: two runs that were given different tracks are a
#: whole pitch apart, so a glyph smaller than a pitch cannot reach the neighbouring lane in
#: either direction. Everything on the SAME track already has a disjoint interval.
RAIL_GLYPH_MM: Mm = 0.9 * GRID_MM
RAIL_GLYPH_DEPTH_MM: Mm = 0.9 * GRID_MM

#: Blank border around the whole sheet.
MARGIN_MM: Mm = 4 * GRID_MM

#: Lead length between a symbol's body and the point a wire attaches to.
LEAD_MM: Mm = 2 * GRID_MM

#: Pin-to-pin spacing down the side of a multi-pin body.
PIN_PITCH_MM: Mm = 2 * GRID_MM

#: The height a net name is drawn at, in millimetres of sheet, and the average advance of
#: one character as a fraction of it.
#:
#: ONE FACT, TWO CONSUMERS again. The LAYOUT has to know how much room a net name takes in
#: order to keep a wire out of it, and only a renderer knows the real size -- so the
#: exported sheet takes its size from here (``SheetInk.net_mm``) rather than naming its
#: own, and the panel, which draws text at a fixed PIXEL size on purpose, treats this as
#: the nominal it was always laid out against. The advance is an average over a
#: sans-serif's alphabet; it only has to be close, because the search below steps in half
#: grid squares and a net name is six characters.
NET_LABEL_MM: Mm = 1.3
NET_LABEL_ADVANCE: float = 0.55

#: The height a pin number or pin name is drawn at, in millimetres of sheet.
#:
#: The same arrangement as ``NET_LABEL_MM``: a box WIDENS to fit the names its part
#: declares, so the layout has to know how much room a name takes, and the exported sheet
#: takes its size from here (``SheetInk.pin_mm``) rather than naming its own.
PIN_LABEL_MM: Mm = 1.0

#: How far a net name sits clear of the run it names, and how far past a branch it starts.
#:
#: The sheet used to place a net label AT its trunk, left-anchored: the baseline WAS the
#: wire's y and the x WAS the leftmost branch, so the line ran through every descender and
#: the branch ran up through the first letter. All 41 net labels across the fixtures in
#: this repository landed on a wire, which is 100% of them.
#:
#: ``NET_LABEL_CLEARANCE_MM + NET_LABEL_MM`` MUST STAY UNDER ``TRACK_PITCH_MM``, for the
#: reason ``RAIL_GLYPH_MM`` must: a label that reached into the neighbouring lane would be
#: sitting on a run the track allocator believed it had separated, and no amount of
#: searching along the trunk can move it out of a band that is too tall to fit.
#: ``test_a_net_label_cannot_reach_the_neighbouring_track`` is the measurement.
NET_LABEL_CLEARANCE_MM: Mm = 0.35 * GRID_MM
NET_LABEL_INSET_MM: Mm = 0.3 * GRID_MM

#: Half the diagonal of the cross drawn on a pin no net reaches. Small enough that a row
#: of them down an unused header reads as a row of marks rather than as hatching, and it
#: stays inside the lead so it cannot touch the body or a neighbouring pin.
NO_CONNECT_MM: Mm = 0.3 * GRID_MM


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

#: Spelled with ``TypeAlias`` rather than PEP 695's ``type``, and it has to be: this name
#: is READ AT RUN TIME by ``get_args`` in ``test_schematic.py``, which asserts every kind
#: has a builder. A PEP 695 alias returns an empty tuple there, and the test would then
#: assert that an empty set equals an empty set -- the trap ``model.py`` documents five
#: times over.
SymbolKind: TypeAlias = Literal[  # noqa: UP040
    "resistor",
    "capacitor",
    "polarised-capacitor",
    "diode",
    "led",
    "crystal",
    "potentiometer",
    "switch",
    "relay",
    "ic",
    "connector",
    "box",
    # Drawn only when a part DECLARES itself one of these (``model.PartSymbol``); nothing
    # in the registry asks for them, because no package knows which of its legs is which.
    "zener",
    "fuse",
    "npn",
    "pnp",
    "nmos",
    "pmos",
]


@dataclass(frozen=True, slots=True)
class SymbolShape:
    """One primitive of a symbol body, in symbol-local millimetres.

    Three kinds and no more, because a schematic symbol is lines, closed shapes and
    circles -- and a renderer that has to handle a fourth is a renderer with an untested
    branch in it.
    """

    kind: Literal["polyline", "polygon", "circle"]
    #: ``polyline``/``polygon``: the vertices. ``circle``: one point, the centre.
    points: tuple[Point2, ...]
    #: ``circle`` only.
    radius: Mm = 0.0
    filled: bool = False


@dataclass(frozen=True, slots=True)
class SymbolPin:
    """One lead of a symbol. ``at`` is where a WIRE attaches, not where the body ends.

    ``side`` is which way the lead points OUT of the body, so a wire, a net label or a
    rail stub knows which direction to leave in. Every symbol is drawn with its pins left
    and right; the other two appear once a symbol has been turned a quarter, which is what
    ``_orient_body`` does to it.
    """

    number: str
    name: str | None
    at: Point2
    side: PinSide


@dataclass(frozen=True, slots=True)
class Symbol:
    """One part on the sheet.

    ``at`` is the top-left of the symbol's own coordinate system in sheet millimetres, and
    every ``SymbolShape`` and ``SymbolPin`` inside it is relative to that -- so a renderer
    translates once and draws.
    """

    ref: str
    value: str
    kind: SymbolKind
    footprint_id: str | None
    at: Point2
    shapes: tuple[SymbolShape, ...]
    pins: tuple[SymbolPin, ...]
    width: Mm
    height: Mm
    #: In the design, not yet on the board. The ordinary state of every part on a
    #: schematic that has not been laid out, so it is counted rather than complained
    #: about -- see ``SchematicDrawing.notes``, which deliberately says nothing about it.
    unplaced: bool = False
    #: NOTHING defines this part -- neither the board nor the design. A net names it, so
    #: it is drawn, but its pins are whatever the netlist happened to mention and its
    #: footprint is a guess. That is a real hole in the design, unlike ``unplaced``, and
    #: it is what the dashed outline and the note are for.
    undefined: bool = False
    #: How the body was turned to get here, carried out so a renderer, an exporter and a
    #: rotate command all read the same answer rather than three of them recomputing it.
    #: Always 0 and False on a sheet the layout arranged -- the layout does not turn
    #: anything, because it chooses the positions and can always find an upright one.
    rotation: Rotation = 0
    mirrored: bool = False
    #: Whether this symbol's position is stored in the document (``model.SymbolPlacement``)
    #: rather than chosen by the layout. False for a part added to a hand-drawn sheet and
    #: parked at the edge until somebody puts it somewhere.
    positioned: bool = False


@dataclass(frozen=True, slots=True)
class Wire:
    """One orthogonal run of a signal net, in sheet millimetres.

    A net becomes one trunk plus one of these per pin rather than a single path, so every
    segment is independently checkable for orthogonality and a renderer can highlight a
    whole net by ``net_id`` without walking a tree.
    """

    net_id: NetId
    net_name: str
    net_class: NetClass
    path: tuple[Point2, ...]


@dataclass(frozen=True, slots=True)
class Junction:
    """A solid dot: three or more segments of one net meeting at a point.

    Only where a pin's vertical lands in the MIDDLE of its trunk. At either end the trunk
    simply turns the corner, and a dot there would claim a join that is really a bend.
    """

    net_id: NetId
    at: Point2


@dataclass(frozen=True, slots=True)
class Rail:
    """A ground or power glyph hanging off one pin, standing in for wires to every other.

    ``path`` is the stub from the pin to ``at``; the glyph is drawn at ``at`` pointing
    ``direction``. ``net_class`` picks the glyph: three shrinking bars for ground, a bar on
    a stem for power.

    ``at`` sits on a reserved track of a horizontal channel -- the same allocation the
    trunks come out of -- so no trunk can ever run along the line the bars are drawn on. A
    wire may still CROSS the stub, which is an ordinary schematic crossing and carries no
    dot; a wire lying along the glyph reads as part of it, which is not.
    """

    net_id: NetId
    net_name: str
    net_class: NetClass
    path: tuple[Point2, ...]
    at: Point2
    direction: Literal["down", "up"]


@dataclass(frozen=True, slots=True)
class NoConnect:
    """A cross on a pin that no net in the document reaches.

    A STATEMENT OF FACT, NOT OF INTENT, and that is the difference from KiCad's marker of
    the same shape. There, somebody places one to say "I meant to leave this open"; here
    nothing is placed by hand, so what this can honestly say is only that the netlist does
    not mention the pin. That is worth saying: without it an unwired pin is drawn as a
    plain lead ending in space, which is also what a pin whose wire the sheet failed to
    draw would look like, and a reader cannot tell those apart.

    It is not a defect and produces no note. Unused pins on a header are the ordinary case
    -- ten of the eleven parts on `arduino-io-shield` have one -- and LVS is where a
    connection that was supposed to exist gets reported.
    """

    ref: str
    pin: str
    at: Point2


@dataclass(frozen=True, slots=True)
class Label:
    """A piece of text with a place and a job.

    ``kind`` exists so the renderer can style text without parsing it: a reference reads
    bold, a value dim, a net name small, a pin number smaller still.
    """

    text: str
    at: Point2
    kind: Literal["ref", "value", "net", "pin"]
    anchor: Literal["left", "centre", "right"] = "left"


@dataclass(frozen=True, slots=True)
class Annotation:
    """A caption or a box somebody put on the drawing.

    Straight out of ``model.SheetNote`` with nothing added, because there is nothing to
    derive: a note is a person writing on the sheet. It is carried through the drawing
    rather than read from the document by each renderer so that the panel, the SVG writer
    and the PDF cannot disagree about what is on the page.
    """

    kind: SheetNoteKind
    at: Point2
    to: Point2
    text: str
    size_mm: Mm


@dataclass(frozen=True, slots=True)
class SchematicOptions:
    """What to draw, kept separate from how.

    ``rail_classes`` is the one worth changing: empty it and every ground pin gets a wire,
    which is occasionally what you want on a four-part circuit and never what you want on
    a thirty-part one.
    """

    rail_classes: frozenset[NetClass] = frozenset({"ground", "power"})
    #: A power net with fewer nodes than this stays a wire. Two is the convention -- a
    #: schematic uses the glyph however few pins the rail reaches -- and it is a number
    #: rather than a flag so a two-pin +5V can be made a visible wire when that is clearer.
    rail_min_nodes: int = 2
    show_values: bool = True
    show_pin_numbers: bool = True


DEFAULT_SCHEMATIC_OPTIONS = SchematicOptions()


@dataclass(frozen=True, slots=True)
class SchematicDrawing:
    """Everything on the sheet, plus what could not be put on it.

    ``notes`` is not decoration. A pin the netlist names and the footprint does not have,
    a part that is not on the board, a net with a single node -- each is a real defect that
    LVS also reports, and a drawing that silently omitted them would be a picture of a
    circuit nobody has.
    """

    symbols: tuple[Symbol, ...] = ()
    wires: tuple[Wire, ...] = ()
    rails: tuple[Rail, ...] = ()
    junctions: tuple[Junction, ...] = ()
    no_connects: tuple[NoConnect, ...] = ()
    labels: tuple[Label, ...] = ()
    #: Captions and boxes, in both kinds of sheet. Nothing derives anything from them.
    annotations: tuple[Annotation, ...] = ()
    width: Mm = 0.0
    height: Mm = 0.0
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# What a renderer has to be told
# ---------------------------------------------------------------------------

#: The bars of a ground glyph: how wide each is as a fraction of ``RAIL_GLYPH_MM``, and how
#: far along the stub it sits as a fraction of ``RAIL_GLYPH_DEPTH_MM``. Three shrinking bars
#: is the convention, and the shrinking is what makes the glyph read as a ground rather than
#: as three wires that happen to be stacked.
_GROUND_BARS: tuple[tuple[float, float], ...] = ((1.0, 0.0), (0.6, 0.35), (0.25, 0.70))


def symbol_at(drawing: SchematicDrawing, point: Point2) -> Symbol | None:
    """The symbol whose box contains ``point``, or None.

    Answered from the DRAWING's own output rather than by re-deriving anything, which is
    the rule ``cell_at`` followed before it: a second copy of "where is this symbol" is a
    second thing to keep in step.
    """
    for symbol in drawing.symbols:
        if (
            symbol.at.x <= point.x <= symbol.at.x + symbol.width
            and symbol.at.y <= point.y <= symbol.at.y + symbol.height
        ):
            return symbol
    return None


def pin_at(drawing: SchematicDrawing, point: Point2, within: Mm) -> tuple[str, str] | None:
    """The nearest pin within ``within`` millimetres, as ``(reference, pin number)``.

    NEAREST AND NOT FIRST, for the reason every picker in this codebase says: the pins of a
    DIP are one pitch apart, and taking whichever was built first would make half of them
    unreachable.
    """
    best: tuple[float, str, str] | None = None
    for symbol in drawing.symbols:
        for pin in symbol.pins:
            dx = point.x - (symbol.at.x + pin.at.x)
            dy = point.y - (symbol.at.y + pin.at.y)
            distance = math.hypot(dx, dy)
            if distance <= within and (best is None or distance < best[0]):
                best = (distance, symbol.ref, pin.number)
    return (best[1], best[2]) if best is not None else None


def pin_position(drawing: SchematicDrawing, ref: str, number: str) -> Point2 | None:
    """Where one pin's wire attaches, in sheet millimetres."""
    for symbol in drawing.symbols:
        if symbol.ref != ref:
            continue
        for pin in symbol.pins:
            if pin.number == number:
                return Point2(x=symbol.at.x + pin.at.x, y=symbol.at.y + pin.at.y)
    return None


def snap_to_grid(point: Point2) -> Point2:
    """The nearest grid intersection. The one place a sheet position is rounded.

    Everything a user puts on this sheet lands on ``GRID_MM``, which is what makes a wire
    drawn between two symbols meet their pins instead of missing by a tenth of a
    millimetre -- and what makes two symbols line up without anybody aiming.
    """
    return Point2(
        x=round(point.x / GRID_MM) * GRID_MM,
        y=round(point.y / GRID_MM) * GRID_MM,
    )


def no_connect_arms(mark: NoConnect) -> tuple[tuple[Point2, Point2], tuple[Point2, Point2]]:
    """The two strokes of the cross, so the panel and the exported sheet cannot disagree.

    The same arrangement as ``rail_glyph_bars``: the shape lives here, beside the layout
    that made room for it, and a renderer asks rather than deciding.
    """
    reach = NO_CONNECT_MM
    return (
        (
            Point2(x=mark.at.x - reach, y=mark.at.y - reach),
            Point2(x=mark.at.x + reach, y=mark.at.y + reach),
        ),
        (
            Point2(x=mark.at.x - reach, y=mark.at.y + reach),
            Point2(x=mark.at.x + reach, y=mark.at.y - reach),
        ),
    )


def rail_glyph_bars(rail: Rail) -> tuple[tuple[Point2, Point2], ...]:
    """The bars to draw at ``rail.at``: one for power, three shrinking ones for ground.

    ONE FACT, TWO RENDERERS. ``ui/viewsch.py`` paints these on screen and
    ``schematic_export.py`` writes them into an SVG that becomes the printed sheet. A glyph
    drawn one way in the panel and another on paper would be two answers to "which rail is
    this", which is the one question the glyph exists to answer.

    The bars stay inside the box the LAYOUT cleared -- ``RAIL_GLYPH_MM`` across the stub and
    ``RAIL_GLYPH_DEPTH_MM`` along it -- because that box is the only reason no wire is lying
    where they go; ``test_nothing_is_drawn_through_a_rail_glyph`` measures the layout half of
    that bargain. They use 0.7 of the depth rather than all of it: the next lane is one track
    pitch away and a bar reaching for it reads as touching.

    ``direction`` is honoured rather than assumed. Every ground rail this module emits points
    down and every power rail up, because ``rail_channel`` picks the channel from the net
    class -- so this is the reading that stays correct if that ever stops being true, not a
    case anybody has seen.
    """
    x, y = rail.at.x, rail.at.y
    if rail.net_class == "power":
        return ((Point2(x=x - RAIL_GLYPH_MM, y=y), Point2(x=x + RAIL_GLYPH_MM, y=y)),)
    sign = 1.0 if rail.direction == "down" else -1.0
    return tuple(
        (
            Point2(x=x - RAIL_GLYPH_MM * shrink, y=y + sign * RAIL_GLYPH_DEPTH_MM * step),
            Point2(x=x + RAIL_GLYPH_MM * shrink, y=y + sign * RAIL_GLYPH_DEPTH_MM * step),
        )
        for shrink, step in _GROUND_BARS
    )


# ---------------------------------------------------------------------------
# Symbols, generated from the footprint registry
# ---------------------------------------------------------------------------
#
# The rule this section enforces, stated once: a symbol gets its real electrical shape only
# where the registry knows what each of its leads IS. Two leads plus a body archetype is
# enough to tell a resistor from a ceramic capacitor; a plus, a K or an A in a pin name is
# enough to know which way round a polarised part goes. Three leads on a TO-92 is not
# enough to know which one is the base, so a TO-92 is a box with numbered pins -- which is
# less pretty and does not lie.


@dataclass(frozen=True, slots=True)
class _PinSpec:
    number: str
    name: str | None


@dataclass(frozen=True, slots=True)
class _SymbolBody:
    shapes: tuple[SymbolShape, ...]
    pins: tuple[SymbolPin, ...]
    width: Mm
    height: Mm


def _p(x: Mm, y: Mm) -> Point2:
    return Point2(x=x, y=y)


#: Which way round a pin points once its body has been turned or flipped. The keys are
#: the quarter turns clockwise; the values map a pin's original side onto its new one.
_SIDE_AFTER_TURN: dict[int, dict[PinSide, PinSide]] = {
    0: {"left": "left", "right": "right", "top": "top", "bottom": "bottom"},
    90: {"left": "top", "right": "bottom", "top": "right", "bottom": "left"},
    180: {"left": "right", "right": "left", "top": "bottom", "bottom": "top"},
    270: {"left": "bottom", "right": "top", "top": "left", "bottom": "right"},
}

_SIDE_MIRRORED: dict[PinSide, PinSide] = {
    "left": "right",
    "right": "left",
    "top": "top",
    "bottom": "bottom",
}

#: Which way a pin's wire leaves it, as a unit vector in sheet millimetres.
PIN_DIRECTION: dict[PinSide, tuple[float, float]] = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "top": (0.0, -1.0),
    "bottom": (0.0, 1.0),
}


def _orient_body(body: _SymbolBody, rotation: Rotation, mirrored: bool) -> _SymbolBody:
    """The same symbol, turned and flipped.

    MIRROR FIRST, THEN TURN, which is the order ``ComponentInstance`` uses on the board --
    two places in this application answer "which way round is this", and having them
    disagree would mean a part whose symbol and whose footprint are flipped differently
    from one another. The mirror is about the body's own vertical centre, so a DIP's pin 1
    moves to the other side and nothing leaves the box.

    Every shape and every pin is transformed, and the box swaps its width and height on a
    quarter turn. Nothing here knows what the symbol IS, which is the point: a resistor, a
    relay and a 40-pin box all turn by the same arithmetic.
    """
    if rotation == 0 and not mirrored:
        return body

    width, height = body.width, body.height

    def place(point: Point2) -> Point2:
        x, y = point.x, point.y
        if mirrored:
            x = width - x
        if rotation == 90:
            return _p(height - y, x)
        if rotation == 180:
            return _p(width - x, height - y)
        if rotation == 270:
            return _p(y, width - x)
        return _p(x, y)

    def side_of(side: PinSide) -> PinSide:
        turned = _SIDE_MIRRORED[side] if mirrored else side
        return _SIDE_AFTER_TURN[rotation][turned]

    shapes = tuple(
        SymbolShape(
            kind=shape.kind,
            points=tuple(place(point) for point in shape.points),
            radius=shape.radius,
            filled=shape.filled,
        )
        for shape in body.shapes
    )
    pins = tuple(
        SymbolPin(
            number=pin.number,
            name=pin.name,
            at=place(pin.at),
            side=side_of(pin.side),
        )
        for pin in body.pins
    )
    turned_quarter = rotation in (90, 270)
    return _SymbolBody(
        shapes=shapes,
        pins=pins,
        width=height if turned_quarter else width,
        height=width if turned_quarter else height,
    )


def _pin_sort_key(number: str) -> tuple[int, float, str]:
    """Pin "10" after pin "9", and a lettered pin after every numbered one.

    A netlist may name a pin anything. Sorting the numbers as text puts pin 10 between 1
    and 2 and silently reorders half a DIP-16. The rule itself lives in ``model``, which
    orders a part's declared pin names by it; the two must never sort differently.
    """
    return pin_number_sort_key(number)


def _other_pin(pins: tuple[_PinSpec, ...], number: str) -> str | None:
    for pin in pins:
        if pin.number != number:
            return pin.number
    return None


def _cathode_pin_number(pins: tuple[_PinSpec, ...], polarized: bool) -> str | None:
    """Which lead is the cathode, by the rule ``guide._polarity_note`` already follows.

    Names first, convention second, and in that order deliberately: an LED has pin 1 as its
    ANODE and a diode has pin 1 as its cathode, so a rule that reads pin 1 without looking
    at the names draws one of the two backwards -- on the screen, and then on the bench.
    """
    for pin in pins:
        if pin.name == "K":
            return pin.number
    for pin in pins:
        if pin.name == "A":
            return _other_pin(pins, pin.number)
    if polarized and len(pins) == 2:
        # Unnamed but polarised: a diode, where pin 1 is the cathode by the convention this
        # registry and KiCad DO-41 both follow.
        return pins[0].number
    return None


def _positive_pin_number(pins: tuple[_PinSpec, ...], polarized: bool) -> str | None:
    """Which lead of an electrolytic is the positive one. Names first, as above."""
    for pin in pins:
        if pin.name == "+":
            return pin.number
    for pin in pins:
        if pin.name == "-":
            return _other_pin(pins, pin.number)
    if polarized and len(pins) == 2:
        return pins[0].number
    return None


def _switch_poles(
    footprint: Footprint | None,
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """The two nodes of a four-legged tactile switch, as pin numbers, or ``None``.

    THE ONE THING A SWITCH PACKAGE DOES SAY ABOUT ITSELF. A 6 mm tactile switch has four
    legs in two pairs and the pair on each SIDE of the body is bonded together inside it --
    that is what the part IS, not what one manufacturer chose, which is exactly the
    difference from a TO-92's base. So this symbol may exist where a transistor's may not.

    Read off the footprint's own GEOMETRY rather than off pin numbers: a package that
    numbered its legs some other way gets a box instead of a lie, and the columns are what
    the physical part is bonded along.
    """
    if footprint is None or len(footprint.pins) != 4:
        return None
    columns = sorted({pin.d_col for pin in footprint.pins})
    if len(columns) != 2:
        return None
    left = tuple(pin.number for pin in footprint.pins if pin.d_col == columns[0])
    right = tuple(pin.number for pin in footprint.pins if pin.d_col == columns[1])
    if len(left) != 2 or len(right) != 2:
        return None
    return left, right


def _relay_sides(
    footprint: Footprint | None,
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """The coil's pins and the contact set's, as pin numbers, or ``None``.

    A PCB relay's coil is a PAIR of pins along one side of the body and its contacts are
    the several along the other; which side is which is the count, and that much is true of
    every relay this tool can hold a footprint for.

    WHICH CONTACT IS THE COMMON ONE IS NOT, and this deliberately does not say. Songle and
    Omron disagree about it on packages of the same outline, so the symbol draws the
    contacts as numbered leads out of a contact block rather than as a blade resting on one
    of them: a sheet that named the wrong pin COM is a board built normally-closed when it
    was meant to be normally-open, and it would look right the whole way.
    """
    if footprint is None or len(footprint.pins) < 4:
        return None
    columns = sorted({pin.d_col for pin in footprint.pins})
    if len(columns) != 2:
        return None
    sides = [
        tuple(pin.number for pin in footprint.pins if pin.d_col == column) for column in columns
    ]
    coils = [side for side in sides if len(side) == 2]
    if len(coils) != 1:
        # Both sides a pair, or neither: nothing here says which one is the winding.
        return None
    coil = coils[0]
    contacts = next(side for side in sides if side is not coil)
    return coil, contacts


# -- two-terminal geometry ---------------------------------------------------
#
# Every two-lead symbol is the same size and sits on the same axis, so a row of them lines
# up without the layout having to know what any of them is.

_TWO_W: Mm = 8 * GRID_MM
_TWO_H: Mm = 4 * GRID_MM
_AXIS: Mm = _TWO_H / 2


def _two_terminal_pins(
    pins: tuple[_PinSpec, ...], left_number: str | None
) -> tuple[SymbolPin, ...]:
    """Pin 1 on the left unless ``left_number`` says otherwise.

    The polarity helpers return a pin NUMBER rather than a side, so this is where a part
    whose cathode is pin 2 gets DRAWN the other way round instead of being relabelled.
    """
    ordered = list(pins)
    if left_number is not None and len(ordered) == 2 and ordered[0].number != left_number:
        ordered.reverse()
    return (
        SymbolPin(number=ordered[0].number, name=ordered[0].name, at=_p(0.0, _AXIS), side="left"),
        SymbolPin(
            number=ordered[1].number, name=ordered[1].name, at=_p(_TWO_W, _AXIS), side="right"
        ),
    )


def _leads(x_left_end: Mm, x_right_start: Mm) -> tuple[SymbolShape, ...]:
    return (
        SymbolShape(kind="polyline", points=(_p(0.0, _AXIS), _p(x_left_end, _AXIS))),
        SymbolShape(kind="polyline", points=(_p(x_right_start, _AXIS), _p(_TWO_W, _AXIS))),
    )


def _resistor_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    """The IEC rectangle rather than the zig-zag.

    Both are correct and the rectangle stays legible at the size a whole sheet is looked
    at, which is the size this one is looked at.
    """
    half = 0.75 * GRID_MM
    box = SymbolShape(
        kind="polygon",
        points=(
            _p(2 * GRID_MM, _AXIS - half),
            _p(6 * GRID_MM, _AXIS - half),
            _p(6 * GRID_MM, _AXIS + half),
            _p(2 * GRID_MM, _AXIS + half),
        ),
    )
    return _SymbolBody(
        shapes=(*_leads(2 * GRID_MM, 6 * GRID_MM), box),
        pins=_two_terminal_pins(pins, None),
        width=_TWO_W,
        height=_TWO_H,
    )


def _capacitor_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    half = 1.3 * GRID_MM
    left_x, right_x = 3.6 * GRID_MM, 4.4 * GRID_MM
    plates = (
        SymbolShape(kind="polyline", points=(_p(left_x, _AXIS - half), _p(left_x, _AXIS + half))),
        SymbolShape(kind="polyline", points=(_p(right_x, _AXIS - half), _p(right_x, _AXIS + half))),
    )
    return _SymbolBody(
        shapes=(*_leads(left_x, right_x), *plates),
        pins=_two_terminal_pins(pins, None),
        width=_TWO_W,
        height=_TWO_H,
    )


def _polarised_capacitor_body(
    pins: tuple[_PinSpec, ...], footprint: Footprint | None
) -> _SymbolBody:
    """Straight plate positive, curved plate negative, and a plus over the positive lead.

    The plus is the mark actually printed on the can, so the sheet and the part in the hand
    agree about which end is which.
    """
    half = 1.3 * GRID_MM
    straight_x, curve_x = 3.5 * GRID_MM, 4.6 * GRID_MM
    positive = _positive_pin_number(pins, footprint.polarized if footprint else True)
    curve_points: list[Point2] = []
    steps = 8
    for index in range(steps + 1):
        t = -1.0 + 2.0 * index / steps
        curve_points.append(_p(curve_x + 0.5 * GRID_MM * (1.0 - t * t), _AXIS + t * half))
    plus_x, plus_y = 2.4 * GRID_MM, _AXIS - 1.9 * GRID_MM
    arm = 0.35 * GRID_MM
    shapes = (
        *_leads(straight_x, curve_x),
        SymbolShape(
            kind="polyline", points=(_p(straight_x, _AXIS - half), _p(straight_x, _AXIS + half))
        ),
        SymbolShape(kind="polyline", points=tuple(curve_points)),
        SymbolShape(kind="polyline", points=(_p(plus_x - arm, plus_y), _p(plus_x + arm, plus_y))),
        SymbolShape(kind="polyline", points=(_p(plus_x, plus_y - arm), _p(plus_x, plus_y + arm))),
    )
    return _SymbolBody(
        shapes=shapes, pins=_two_terminal_pins(pins, positive), width=_TWO_W, height=_TWO_H
    )


def _diode_shapes(*, cathode_left: bool) -> tuple[SymbolShape, ...]:
    half = 1.3 * GRID_MM
    near, far = 3.6 * GRID_MM, 5.2 * GRID_MM
    bar_x = near if cathode_left else far
    tip_x = near if cathode_left else far
    base_x = far if cathode_left else near
    return (
        *_leads(near, far),
        SymbolShape(kind="polyline", points=(_p(bar_x, _AXIS - half), _p(bar_x, _AXIS + half))),
        SymbolShape(
            kind="polygon",
            points=(_p(base_x, _AXIS - half), _p(base_x, _AXIS + half), _p(tip_x, _AXIS)),
        ),
    )


def _diode_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    cathode = _cathode_pin_number(pins, footprint.polarized if footprint else True)
    return _SymbolBody(
        shapes=_diode_shapes(cathode_left=True),
        pins=_two_terminal_pins(pins, cathode),
        width=_TWO_W,
        height=_TWO_H,
    )


def _led_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    """A diode with two arrows leaving it.

    The arrows are the whole difference between "this is a diode" and "this is the part
    that lights up", so they are drawn rather than implied by a colour.
    """
    cathode = _cathode_pin_number(pins, footprint.polarized if footprint else True)
    arrows: list[SymbolShape] = []
    # Kept inside the symbol's own box on purpose: the reference designator is drawn just
    # above that box, and an arrowhead poking out of it lands underneath the text.
    for offset in (0.0, 0.9 * GRID_MM):
        start = _p(4.0 * GRID_MM + offset, _AXIS - 1.1 * GRID_MM)
        end = _p(start.x + 0.6 * GRID_MM, start.y - 0.6 * GRID_MM)
        head = 0.3 * GRID_MM
        arrows.append(SymbolShape(kind="polyline", points=(start, end)))
        arrows.append(
            SymbolShape(
                kind="polygon",
                points=(
                    end,
                    _p(end.x - head * 2, end.y + head * 0.6),
                    _p(end.x - head * 0.6, end.y + head * 2),
                ),
                filled=True,
            )
        )
    return _SymbolBody(
        shapes=(*_diode_shapes(cathode_left=True), *arrows),
        pins=_two_terminal_pins(pins, cathode),
        width=_TWO_W,
        height=_TWO_H,
    )


def _crystal_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    half = 1.3 * GRID_MM
    left_x, right_x = 3.2 * GRID_MM, 5.6 * GRID_MM
    slab = 0.9 * GRID_MM
    shapes = (
        *_leads(left_x, right_x),
        SymbolShape(kind="polyline", points=(_p(left_x, _AXIS - half), _p(left_x, _AXIS + half))),
        SymbolShape(kind="polyline", points=(_p(right_x, _AXIS - half), _p(right_x, _AXIS + half))),
        SymbolShape(
            kind="polygon",
            points=(
                _p(3.8 * GRID_MM, _AXIS - slab),
                _p(5.0 * GRID_MM, _AXIS - slab),
                _p(5.0 * GRID_MM, _AXIS + slab),
                _p(3.8 * GRID_MM, _AXIS + slab),
            ),
        ),
    )
    return _SymbolBody(
        shapes=shapes, pins=_two_terminal_pins(pins, None), width=_TWO_W, height=_TWO_H
    )


def _potentiometer_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    """A resistor with an arrow into it, pin 2 the wiper.

    THE ONE ASSUMPTION IN THIS FILE THE REGISTRY DOES NOT BACK. ``pot-3`` carries no pin
    names, and on a three-lead inline potentiometer the middle lead is the wiper --
    universally, on every part this tool models. It is written down here rather than left
    to be discovered, because it is the same shape of claim the module refuses to make
    about a TO-92 base; the difference is that this one has no counterexample.
    """
    height = 6 * GRID_MM
    axis = 4 * GRID_MM
    half = 0.75 * GRID_MM
    wiper_y = 1 * GRID_MM
    wiper_x = 4 * GRID_MM
    head = 0.45 * GRID_MM
    shapes = (
        SymbolShape(kind="polyline", points=(_p(0.0, axis), _p(2 * GRID_MM, axis))),
        SymbolShape(kind="polyline", points=(_p(6 * GRID_MM, axis), _p(_TWO_W, axis))),
        SymbolShape(
            kind="polygon",
            points=(
                _p(2 * GRID_MM, axis - half),
                _p(6 * GRID_MM, axis - half),
                _p(6 * GRID_MM, axis + half),
                _p(2 * GRID_MM, axis + half),
            ),
        ),
        SymbolShape(
            kind="polyline",
            points=(
                _p(_TWO_W, wiper_y),
                _p(wiper_x, wiper_y),
                _p(wiper_x, axis - half - head * 2),
            ),
        ),
        SymbolShape(
            kind="polygon",
            points=(
                _p(wiper_x - head, axis - half - head * 2),
                _p(wiper_x + head, axis - half - head * 2),
                _p(wiper_x, axis - half),
            ),
            filled=True,
        ),
    )
    by_number = {pin.number: pin for pin in pins}
    ends = [pin for pin in pins if pin.number != "2"]
    wiper = by_number.get("2", pins[-1])
    if len(ends) < 2:  # pragma: no cover - a 3-pin footprint always has two non-wiper pins
        ends = list(pins)
    drawn = (
        SymbolPin(number=ends[0].number, name=ends[0].name, at=_p(0.0, axis), side="left"),
        SymbolPin(number=wiper.number, name=wiper.name, at=_p(_TWO_W, wiper_y), side="right"),
        SymbolPin(number=ends[-1].number, name=ends[-1].name, at=_p(_TWO_W, axis), side="right"),
    )
    return _SymbolBody(shapes=shapes, pins=drawn, width=_TWO_W, height=height)


def _switch_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    """A momentary pushbutton: two terminals, a gap, and a plunger over it.

    Each terminal carries BOTH of its legs, joined by a bar, because they are one node
    inside the part -- see ``_switch_poles``. Drawing them as four separate leads would
    make somebody wire across a pair that is already shorted and wonder why the switch does
    nothing.
    """
    poles = _switch_poles(footprint)
    by_number = {pin.number: pin for pin in pins}
    assert poles is not None, "symbol_kind_for only asks for a switch it can read"
    height = 5 * GRID_MM
    axis = 2.5 * GRID_MM
    rows = (1.5 * GRID_MM, 3.5 * GRID_MM)
    # The two legs of a pole MEET at a point rather than being bridged by a bar. A bar plus
    # two leads draws three sides of a rectangle, which is the box this symbol exists to
    # stop being -- and a join is what "these are one node" looks like everywhere else on a
    # schematic.
    lead_ends = (1.0 * GRID_MM, 7.0 * GRID_MM)
    joins = (2.0 * GRID_MM, 6.0 * GRID_MM)
    gaps = (3.0 * GRID_MM, 5.0 * GRID_MM)
    plunger_y = axis - 1.2 * GRID_MM

    shapes: list[SymbolShape] = []
    drawn: list[SymbolPin] = []
    for side_index, numbers in enumerate(poles):
        edge_x = 0.0 if side_index == 0 else _TWO_W
        lead_end, join_x, gap_x = lead_ends[side_index], joins[side_index], gaps[side_index]
        for row_index, number in enumerate(numbers):
            y = rows[row_index]
            shapes.append(
                SymbolShape(
                    kind="polyline",
                    points=(_p(edge_x, y), _p(lead_end, y), _p(join_x, axis)),
                )
            )
            spec = by_number.get(number)
            drawn.append(
                SymbolPin(
                    number=number,
                    name=spec.name if spec is not None else None,
                    at=_p(edge_x, y),
                    side="left" if side_index == 0 else "right",
                )
            )
        shapes.append(SymbolShape(kind="polyline", points=(_p(join_x, axis), _p(gap_x, axis))))
        shapes.append(
            SymbolShape(kind="circle", points=(_p(gap_x, axis),), radius=0.3 * GRID_MM)
        )
    shapes.append(
        SymbolShape(
            kind="polyline",
            points=(_p(2.6 * GRID_MM, plunger_y), _p(5.4 * GRID_MM, plunger_y)),
        )
    )
    shapes.append(
        SymbolShape(
            kind="polyline",
            points=(_p(4 * GRID_MM, plunger_y), _p(4 * GRID_MM, plunger_y - 0.8 * GRID_MM)),
        )
    )
    return _SymbolBody(
        shapes=tuple(shapes), pins=tuple(drawn), width=_TWO_W, height=height
    )


def _relay_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    """A coil, a mechanical link, and a contact block with its leads numbered.

    The link is drawn as separate short strokes rather than one line, because a line
    between a coil and a contact set is what a WIRE looks like, and this is the one part of
    a relay symbol that must not read as copper. ``SymbolShape`` has no dash style and
    should not grow one for this: three segments are three segments in every renderer.

    The contact block stays a block for the reason ``_relay_sides`` gives -- naming the
    common pin is the claim that would put somebody's motor on the wrong throw.
    """
    sides = _relay_sides(footprint)
    assert sides is not None, "symbol_kind_for only asks for a relay it can read"
    coil_numbers, contact_numbers = sides
    by_number = {pin.number: pin for pin in pins}

    rows = max(len(contact_numbers), 2)
    height = (rows + 1) * PIN_PITCH_MM
    width = 12.5 * GRID_MM
    coil_left, coil_right = 2 * GRID_MM, 4.5 * GRID_MM
    block_left, block_right = 7 * GRID_MM, 10.5 * GRID_MM
    top, bottom = PIN_PITCH_MM / 2, height - PIN_PITCH_MM / 2

    coil_ys = (PIN_PITCH_MM, rows * PIN_PITCH_MM)
    shapes: list[SymbolShape] = [
        SymbolShape(
            kind="polygon",
            points=(
                _p(coil_left, coil_ys[0]),
                _p(coil_right, coil_ys[0]),
                _p(coil_right, coil_ys[1]),
                _p(coil_left, coil_ys[1]),
            ),
        ),
        SymbolShape(
            kind="polygon",
            points=(
                _p(block_left, top),
                _p(block_right, top),
                _p(block_right, bottom),
                _p(block_left, bottom),
            ),
        ),
    ]
    drawn: list[SymbolPin] = []
    for index, number in enumerate(coil_numbers):
        y = coil_ys[index]
        shapes.append(SymbolShape(kind="polyline", points=(_p(0.0, y), _p(coil_left, y))))
        spec = by_number.get(number)
        drawn.append(
            SymbolPin(
                number=number,
                name=spec.name if spec is not None else None,
                at=_p(0.0, y),
                side="left",
            )
        )
    for index, number in enumerate(contact_numbers):
        y = (index + 1) * PIN_PITCH_MM
        shapes.append(SymbolShape(kind="polyline", points=(_p(block_right, y), _p(width, y))))
        spec = by_number.get(number)
        drawn.append(
            SymbolPin(
                number=number,
                name=spec.name if spec is not None else None,
                at=_p(width, y),
                side="right",
            )
        )

    link_y = height / 2
    stroke = 0.35 * GRID_MM
    x = coil_right + 0.4 * GRID_MM
    while x + stroke <= block_left:
        shapes.append(SymbolShape(kind="polyline", points=(_p(x, link_y), _p(x + stroke, link_y))))
        x += stroke * 2

    return _SymbolBody(
        shapes=tuple(shapes), pins=tuple(drawn), width=width, height=height
    )


# -- everything else is a box, and the box says what it knows -----------------


def _boxy_body(
    pins: tuple[_PinSpec, ...],
    *,
    body_width: Mm,
    split: bool,
    dip_order: bool,
    notch: bool,
    name_inset: Mm | None = None,
) -> _SymbolBody:
    """A rectangle with numbered pins down one or both sides.

    ``dip_order`` is the DIP numbering and not a style: pins 1..n/2 run down the left and
    the rest run UP the right, which is how the package is numbered and therefore the only
    ordering that lets someone read a pin off this sheet and find it on the part.
    """
    count = len(pins)
    if split:
        per_side = (count + 1) // 2
        left = list(pins[:per_side])
        right = list(pins[per_side:])
        if dip_order:
            right.reverse()
    else:
        left, right = list(pins), []

    rows = max(len(left), len(right), 1)
    height = (rows + 1) * PIN_PITCH_MM
    # A part that NAMES its pins gets a body wide enough to print the names inside it --
    # "GPIO21" does not fit where "21" did. Only then: a box whose pins carry no names is
    # exactly the width it always was, which is what keeps every frozen sheet unchanged.
    body_width = max(
        body_width,
        _named_body_width(
            left, right, _PIN_NAME_INSET_MM if name_inset is None else name_inset
        ),
    )
    width = LEAD_MM + body_width + (LEAD_MM if right else 0.0)
    body_left = LEAD_MM
    body_right = LEAD_MM + body_width
    top = PIN_PITCH_MM / 2
    bottom = height - PIN_PITCH_MM / 2

    shapes: list[SymbolShape] = [
        SymbolShape(
            kind="polygon",
            points=(
                _p(body_left, top),
                _p(body_right, top),
                _p(body_right, bottom),
                _p(body_left, bottom),
            ),
        )
    ]
    drawn: list[SymbolPin] = []
    for index, pin in enumerate(left):
        y = (index + 1) * PIN_PITCH_MM
        shapes.append(SymbolShape(kind="polyline", points=(_p(0.0, y), _p(body_left, y))))
        drawn.append(SymbolPin(number=pin.number, name=pin.name, at=_p(0.0, y), side="left"))
    for index, pin in enumerate(right):
        y = (index + 1) * PIN_PITCH_MM
        shapes.append(SymbolShape(kind="polyline", points=(_p(body_right, y), _p(width, y))))
        drawn.append(SymbolPin(number=pin.number, name=pin.name, at=_p(width, y), side="right"))
    if notch:
        # The pin-1 mark, in the place the package carries it.
        shapes.append(
            SymbolShape(
                kind="circle",
                points=(_p((body_left + body_right) / 2, top),),
                radius=0.5 * GRID_MM,
            )
        )
    return _SymbolBody(
        shapes=tuple(shapes), pins=tuple(drawn), width=width, height=height
    )


#: How far a pin's name sits inside the body edge, and the least gap between a name on the
#: left and one on the right. The first is where ``_part_labels`` has always put a pin
#: number; the second is one grid square, because two names nearer than that read as one.
_PIN_NAME_INSET_MM: Mm = 0.5 * GRID_MM
_PIN_NAME_GAP_MM: Mm = GRID_MM

#: Where a CONNECTOR prints a pin's name: past the shroud line ``_connector_body`` draws
#: 1.4 grid squares into the body. A number fits in front of that line and always has; a
#: name starting in the same place runs straight through it, and "24V-L" reads as "24V-"
#: with a bar through the L.
_CONNECTOR_SHROUD_MM: Mm = 1.4 * GRID_MM
_CONNECTOR_NAME_INSET_MM: Mm = _CONNECTOR_SHROUD_MM + 0.4 * GRID_MM


def pin_label_width(text: str) -> Mm:
    """Roughly how wide a pin label is on paper, by the same average-advance estimate the
    net labels use. Close is enough: the answer is rounded up to whole grid squares."""
    return len(text) * PIN_LABEL_MM * NET_LABEL_ADVANCE


def _named_body_width(
    left: Sequence[_PinSpec], right: Sequence[_PinSpec], inset: Mm = _PIN_NAME_INSET_MM
) -> Mm:
    """The body width the longest names on each side need, or 0 when nothing is named.

    ``inset`` is where a name starts from the edge it belongs to; the far end keeps the
    ordinary inset, since nothing is drawn there but the body outline.
    """
    left_width = max((pin_label_width(pin.name) for pin in left if pin.name), default=0.0)
    right_width = max((pin_label_width(pin.name) for pin in right if pin.name), default=0.0)
    if not left_width and not right_width:
        return 0.0
    gap = _PIN_NAME_GAP_MM if left_width and right_width else 0.0
    needed = inset + _PIN_NAME_INSET_MM + left_width + gap + right_width
    return math.ceil(needed / GRID_MM - 1e-9) * GRID_MM


def _ic_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    return _boxy_body(pins, body_width=8 * GRID_MM, split=True, dip_order=True, notch=True)


def _connector_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    """Pins down one side however many there are.

    A header is a place wires leave the board, and splitting one across two sides of a box
    would draw the eight-way strip in your hand as two four-ways.
    """
    body = _boxy_body(
        pins,
        body_width=6 * GRID_MM,
        split=False,
        dip_order=False,
        notch=False,
        name_inset=_CONNECTOR_NAME_INSET_MM,
    )
    shroud = SymbolShape(
        kind="polyline",
        points=(
            _p(LEAD_MM + _CONNECTOR_SHROUD_MM, PIN_PITCH_MM / 2),
            _p(LEAD_MM + _CONNECTOR_SHROUD_MM, body.height - PIN_PITCH_MM / 2),
        ),
    )
    return _SymbolBody(
        shapes=(*body.shapes, shroud), pins=body.pins, width=body.width, height=body.height
    )


def _box_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    """The honest fallback: a TO-92, a TO-220, a part nothing in the document defines.

    Five pins or fewer go down one side, because a three-lead part with one pin on the left
    and two on the right invites the reader to see a transistor -- which is precisely the
    reading this box exists to avoid.
    """
    split = len(pins) > 5
    return _boxy_body(pins, body_width=6 * GRID_MM, split=split, dip_order=False, notch=False)


# -- what a part declares itself to be ----------------------------------------
#
# Every symbol below exists only because a PART said what it is (``model.PartSymbol``).
# The registry never asks for one: a DO-35 is a zener or a signal diode, a disc is a
# ceramic capacitor or a PTC fuse, and a three-legged package is anything at all. The
# person who chose the part knows, and for the transistors they also have to say which leg
# is which -- see ``DECLARED_SYMBOL_PINS``.

#: The pin NAMES a declared symbol needs before it can be drawn. A transistor symbol is a
#: claim about which leg is the base or the gate; drawing one from the declaration alone
#: would be making the claim the registry refuses to make, on the part's behalf and
#: without its datasheet. So a declared MOSFET whose leads are not named G, D and S stays a
#: box, and the sheet's notes say which names are missing.
DECLARED_SYMBOL_PINS: dict[PartSymbol, frozenset[str]] = {
    "npn": frozenset({"B", "C", "E"}),
    "pnp": frozenset({"B", "C", "E"}),
    "nmos": frozenset({"G", "D", "S"}),
    "pmos": frozenset({"G", "D", "S"}),
    "zener": frozenset(),
    "fuse": frozenset(),
}


def declared_symbol_kind(
    symbol: PartSymbol, pins: tuple[_PinSpec, ...], footprint: Footprint | None
) -> tuple[SymbolKind | None, str | None]:
    """The kind a declaration draws as, or ``(None, why not)``.

    The reason is phrased for the sheet's notes, after the reference -- "Q1: ..." -- because
    that is where somebody looks to find out why the MOSFET they declared is still a box.
    The caller finishes the sentence with what it drew instead, which is not always a box:
    a declared zener on an unpolarised axial falls back to the resistor it looks like.
    """
    needed = DECLARED_SYMBOL_PINS[symbol]
    if needed:
        names = [pin.name for pin in pins]
        if len(pins) != len(needed) or set(names) != needed:
            wanted = ", ".join(sorted(needed))
            return None, (
                f"declared {symbol}, but a {symbol} symbol needs exactly {len(needed)} pins "
                f"named {wanted}"
            )
        return symbol, None
    if len(pins) != 2:
        return None, f"declared {symbol}, but a {symbol} has two leads"
    if symbol == "zener":
        polarised = footprint.polarized if footprint is not None else False
        if _cathode_pin_number(pins, polarised) is None:
            return None, (
                "declared zener, but nothing says which lead is the cathode "
                "(name the leads K and A)"
            )
    return symbol, None


def _zener_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    """A diode whose bar is bent at both ends, cathode on the left like every diode here.

    The bends are the whole difference from a signal diode, and a signal diode where the
    circuit needs a zener is a gate driven to the full rail -- so they are drawn as two
    unmistakable strokes rather than a serif.
    """
    cathode = _cathode_pin_number(pins, footprint.polarized if footprint else False)
    half = 1.3 * GRID_MM
    near = 3.6 * GRID_MM
    wing_x, wing_y = 0.45 * GRID_MM, 0.35 * GRID_MM
    shapes = list(_diode_shapes(cathode_left=True))
    # The plain bar is the third shape _diode_shapes returns; replaced, not overdrawn.
    shapes[2] = SymbolShape(
        kind="polyline",
        points=(
            _p(near - wing_x, _AXIS - half - wing_y),
            _p(near, _AXIS - half),
            _p(near, _AXIS + half),
            _p(near + wing_x, _AXIS + half + wing_y),
        ),
    )
    return _SymbolBody(
        shapes=tuple(shapes),
        pins=_two_terminal_pins(pins, cathode),
        width=_TWO_W,
        height=_TWO_H,
    )


def _fuse_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    """The IEC fuse: the resistor's rectangle with the conductor running straight through.

    The line through the body is what says "this opens", and it is also the only thing
    telling it apart from the resistor it would otherwise be.
    """
    half = 0.75 * GRID_MM
    shapes = (
        SymbolShape(kind="polyline", points=(_p(0.0, _AXIS), _p(_TWO_W, _AXIS))),
        SymbolShape(
            kind="polygon",
            points=(
                _p(2 * GRID_MM, _AXIS - half),
                _p(6 * GRID_MM, _AXIS - half),
                _p(6 * GRID_MM, _AXIS + half),
                _p(2 * GRID_MM, _AXIS + half),
            ),
        ),
    )
    return _SymbolBody(
        shapes=shapes, pins=_two_terminal_pins(pins, None), width=_TWO_W, height=_TWO_H
    )


# The transistors share one frame: the control lead on the left at mid-height, the two
# power leads on the right one above the other, the envelope circle between. Leads only on
# the left and right because that is how every symbol here leaves its body -- a wire goes
# out sideways into the channel beside its column -- and the potentiometer already puts
# one lead on the left and two on the right in the same way.
_TRANSISTOR_H: Mm = 6 * GRID_MM
_TRANSISTOR_AXIS: Mm = 3 * GRID_MM
_TRANSISTOR_TOP: Mm = 1 * GRID_MM
_TRANSISTOR_BOTTOM: Mm = 5 * GRID_MM


def _arrowhead(tip: Point2, towards_x: float, towards_y: float) -> SymbolShape:
    """A filled arrowhead at ``tip``, pointing along (``towards_x``, ``towards_y``)."""
    length = math.hypot(towards_x, towards_y)
    ux, uy = towards_x / length, towards_y / length
    back, spread = 0.55 * GRID_MM, 0.28 * GRID_MM
    base_x, base_y = tip.x - ux * back, tip.y - uy * back
    return SymbolShape(
        kind="polygon",
        points=(
            tip,
            _p(base_x - uy * spread, base_y + ux * spread),
            _p(base_x + uy * spread, base_y - ux * spread),
        ),
        filled=True,
    )


def _envelope() -> SymbolShape:
    return SymbolShape(
        kind="circle", points=(_p(4.5 * GRID_MM, _TRANSISTOR_AXIS),), radius=1.9 * GRID_MM
    )


def _named(pins: tuple[_PinSpec, ...], name: str) -> _PinSpec:
    """The lead with this name. ``declared_symbol_kind`` has already checked it exists."""
    return next(pin for pin in pins if pin.name == name)


def _transistor_pins(control: _PinSpec, top: _PinSpec, bottom: _PinSpec) -> tuple[SymbolPin, ...]:
    return (
        SymbolPin(
            number=control.number, name=control.name, at=_p(0.0, _TRANSISTOR_AXIS), side="left"
        ),
        SymbolPin(number=top.number, name=top.name, at=_p(_TWO_W, _TRANSISTOR_TOP), side="right"),
        SymbolPin(
            number=bottom.number,
            name=bottom.name,
            at=_p(_TWO_W, _TRANSISTOR_BOTTOM),
            side="right",
        ),
    )


def _bjt_body(pins: tuple[_PinSpec, ...], *, pnp: bool) -> _SymbolBody:
    """Base on the left; the collector on top for an NPN and the emitter on top for a PNP.

    The conventional orientation for each -- conventional current runs DOWN the page
    through both -- and the arrow on the emitter is the only other difference: out of the
    transistor on an NPN, into it on a PNP.
    """
    bar_x, lead_x = 3.4 * GRID_MM, 5.4 * GRID_MM
    upper_y, lower_y = 2.5 * GRID_MM, 3.5 * GRID_MM
    upper_end, lower_end = 1.6 * GRID_MM, 4.4 * GRID_MM
    shapes: list[SymbolShape] = [
        _envelope(),
        SymbolShape(
            kind="polyline", points=(_p(0.0, _TRANSISTOR_AXIS), _p(bar_x, _TRANSISTOR_AXIS))
        ),
        SymbolShape(kind="polyline", points=(_p(bar_x, 1.9 * GRID_MM), _p(bar_x, 4.1 * GRID_MM))),
        SymbolShape(
            kind="polyline",
            points=(
                _p(bar_x, upper_y),
                _p(lead_x, upper_end),
                _p(lead_x, _TRANSISTOR_TOP),
                _p(_TWO_W, _TRANSISTOR_TOP),
            ),
        ),
        SymbolShape(
            kind="polyline",
            points=(
                _p(bar_x, lower_y),
                _p(lead_x, lower_end),
                _p(lead_x, _TRANSISTOR_BOTTOM),
                _p(_TWO_W, _TRANSISTOR_BOTTOM),
            ),
        ),
    ]
    if pnp:
        # Emitter on top, the arrow pointing IN, towards the base bar.
        dx, dy = bar_x - lead_x, upper_y - upper_end
        shapes.append(_arrowhead(_p(lead_x + dx * 0.6, upper_end + dy * 0.6), dx, dy))
        top, bottom = _named(pins, "E"), _named(pins, "C")
    else:
        # Emitter at the bottom, the arrow pointing OUT, away from the base bar.
        dx, dy = lead_x - bar_x, lower_end - lower_y
        shapes.append(_arrowhead(_p(bar_x + dx * 0.8, lower_y + dy * 0.8), dx, dy))
        top, bottom = _named(pins, "C"), _named(pins, "E")
    return _SymbolBody(
        shapes=tuple(shapes),
        pins=_transistor_pins(_named(pins, "B"), top, bottom),
        width=_TWO_W,
        height=_TRANSISTOR_H,
    )


def _mosfet_body(pins: tuple[_PinSpec, ...], *, p_channel: bool) -> _SymbolBody:
    """An enhancement MOSFET: insulated gate, broken channel, body tied to the source.

    Drain on top for an N-channel and source on top for a P-channel -- the way each is
    drawn in the circuits it appears in, where a P-channel high-side switch has its source
    on the supply. The arrow on the body connection points INTO the channel on an
    N-channel and out of it on a P-channel.
    """
    gate_x, channel_x, lead_x = 3.0 * GRID_MM, 3.5 * GRID_MM, 5.4 * GRID_MM
    upper_y, lower_y = 1.9 * GRID_MM, 4.1 * GRID_MM
    source_y = upper_y if p_channel else lower_y
    shapes: list[SymbolShape] = [
        _envelope(),
        SymbolShape(
            kind="polyline", points=(_p(0.0, _TRANSISTOR_AXIS), _p(gate_x, _TRANSISTOR_AXIS))
        ),
        SymbolShape(kind="polyline", points=(_p(gate_x, 1.8 * GRID_MM), _p(gate_x, 4.2 * GRID_MM))),
    ]
    for low, high in ((1.5, 2.3), (2.6, 3.4), (3.7, 4.5)):
        shapes.append(
            SymbolShape(
                kind="polyline",
                points=(_p(channel_x, low * GRID_MM), _p(channel_x, high * GRID_MM)),
            )
        )
    shapes += [
        SymbolShape(
            kind="polyline",
            points=(
                _p(channel_x, upper_y),
                _p(lead_x, upper_y),
                _p(lead_x, _TRANSISTOR_TOP),
                _p(_TWO_W, _TRANSISTOR_TOP),
            ),
        ),
        SymbolShape(
            kind="polyline",
            points=(
                _p(channel_x, lower_y),
                _p(lead_x, lower_y),
                _p(lead_x, _TRANSISTOR_BOTTOM),
                _p(_TWO_W, _TRANSISTOR_BOTTOM),
            ),
        ),
        # The body connection: from the middle of the channel across to the source.
        SymbolShape(
            kind="polyline",
            points=(
                _p(channel_x, _TRANSISTOR_AXIS),
                _p(lead_x, _TRANSISTOR_AXIS),
                _p(lead_x, source_y),
            ),
        ),
    ]
    if p_channel:
        shapes.append(_arrowhead(_p(channel_x + 1.3 * GRID_MM, _TRANSISTOR_AXIS), 1.0, 0.0))
        top, bottom = _named(pins, "S"), _named(pins, "D")
    else:
        shapes.append(_arrowhead(_p(channel_x + 0.1 * GRID_MM, _TRANSISTOR_AXIS), -1.0, 0.0))
        top, bottom = _named(pins, "D"), _named(pins, "S")
    return _SymbolBody(
        shapes=tuple(shapes),
        pins=_transistor_pins(_named(pins, "G"), top, bottom),
        width=_TWO_W,
        height=_TRANSISTOR_H,
    )


def _npn_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    return _bjt_body(pins, pnp=False)


def _pnp_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    return _bjt_body(pins, pnp=True)


def _nmos_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    return _mosfet_body(pins, p_channel=False)


def _pmos_body(pins: tuple[_PinSpec, ...], footprint: Footprint | None) -> _SymbolBody:
    return _mosfet_body(pins, p_channel=True)


_SYMBOL_BUILDERS: dict[
    SymbolKind, Callable[[tuple[_PinSpec, ...], Footprint | None], _SymbolBody]
] = {
    "resistor": _resistor_body,
    "capacitor": _capacitor_body,
    "polarised-capacitor": _polarised_capacitor_body,
    "diode": _diode_body,
    "led": _led_body,
    "crystal": _crystal_body,
    "potentiometer": _potentiometer_body,
    "switch": _switch_body,
    "relay": _relay_body,
    "ic": _ic_body,
    "connector": _connector_body,
    "box": _box_body,
    "zener": _zener_body,
    "fuse": _fuse_body,
    "npn": _npn_body,
    "pnp": _pnp_body,
    "nmos": _nmos_body,
    "pmos": _pmos_body,
}

#: Which symbol an archetype asks for. ``test_schematic`` asserts this covers every member
#: of ``BodyArchetype``, so adding a body to the registry fails here rather than silently
#: drawing the new part as a box.
_KIND_BY_ARCHETYPE: dict[BodyArchetype, SymbolKind] = {
    "axial-cylinder": "resistor",  # ...or a diode, when the footprint says it is polarised
    "radial-electrolytic": "polarised-capacitor",
    "disc-ceramic": "capacitor",
    "box-film": "capacitor",
    "dip": "ic",
    "to92": "box",  # no E/B/C in the registry, so no transistor symbol
    "to220": "box",  # likewise, and the tab tells you nothing about the pinout either
    "led-round": "led",
    "pin-header": "connector",
    "screw-terminal": "connector",
    "potentiometer": "potentiometer",
    "tactile-switch": "switch",  # the legs on one side are bonded; see _switch_poles
    "crystal-hc49": "crystal",
    "relay-box": "relay",  # the coil is the pair of pins; the contacts stay numbered
    "generic-box": "box",
    "box-header": "connector",
    "screw-terminal-vertical": "connector",
}

_TWO_TERMINAL_KINDS: frozenset[SymbolKind] = frozenset(
    {"resistor", "capacitor", "polarised-capacitor", "diode", "led", "crystal"}
)


def symbol_kind_for(footprint: Footprint | None, pin_count: int) -> SymbolKind:
    """Which symbol this part gets drawn as.

    The pin-count guards are not defensive noise. A two-terminal shape has exactly two
    places to attach a wire, so a footprint that grew a third pin must fall back to a box
    rather than have the extra lead silently dropped off the sheet.
    """
    if footprint is None:
        return "box"
    kind = _KIND_BY_ARCHETYPE[footprint.body.archetype]
    if kind == "resistor" and footprint.polarized:
        kind = "diode"
    if kind in _TWO_TERMINAL_KINDS and pin_count != 2:
        return "box"
    if kind == "potentiometer" and pin_count != 3:
        return "box"
    # The last two ask the PACKAGE whether it knows enough, rather than counting pins: a
    # switch is only a switch if its legs come in two bonded pairs, and a relay is only a
    # relay if one side of it is a two-pin winding. Neither helper will guess.
    if kind == "switch" and (_switch_poles(footprint) is None or pin_count != 4):
        return "box"
    if kind == "relay" and (_relay_sides(footprint) is None or pin_count != len(footprint.pins)):
        return "box"
    return kind


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
#
# Columns and rows for the symbols, channels between them for the wires, and nothing
# anywhere else. The whole reason a generated schematic can be read at all is that the two
# never share space:
#
#     channel 0   column 0   channel 1   column 1   channel 2
#   +-----------+----------+-----------+----------+-----------+
#   |           |   [R1]   |           |   [U1]   |           |  row 0
#   +-----------+----------+-----------+----------+-----------+  <- horizontal channel 1
#   |           |   [C1]   |           |   [R2]   |           |  row 1
#   +-----------+----------+-----------+----------+-----------+
#
# A pin leaves its symbol horizontally into the vertical channel beside its column; the
# wire runs down that channel to a horizontal trunk sitting in the channel between two
# rows; the trunk runs across to the other pins. Every segment is in a channel, so no
# segment can cross a symbol. Both kinds of channel widen to fit however many tracks a
# left-edge sweep says they need, which is why the sheet is sized last and not guessed.


def _ref_sort_key(ref: str) -> tuple[str, int, str]:
    """R2 before R10, and R before U. Sorting references as plain text does neither."""
    prefix_length = 0
    while prefix_length < len(ref) and ref[prefix_length].isalpha():
        prefix_length += 1
    prefix = ref[:prefix_length]
    digits = ""
    for character in ref[prefix_length:]:
        if not character.isdigit():
            break
        digits += character
    return (prefix.upper(), int(digits) if digits else -1, ref)


@dataclass(slots=True)
class _Placed:
    ref: str
    value: str
    kind: SymbolKind
    footprint_id: str | None
    body: _SymbolBody
    unplaced: bool
    undefined: bool
    col: int = 0
    row: int = 0
    x: Mm = 0.0
    y: Mm = 0.0

    def anchor_of(self, pin: SymbolPin) -> Point2:
        return Point2(x=self.x + pin.at.x, y=self.y + pin.at.y)


def _assign_tracks(intervals: Sequence[tuple[str, float, float]]) -> tuple[dict[str, int], int]:
    """The fewest parallel lanes a set of intervals needs, by the left-edge sweep.

    Two runs share a lane only when one finishes strictly before the other starts. Allowing
    them to touch would put two wires end to end on the same line, which reads as one wire
    and is the one mistake a schematic must not make.
    """
    ordered = sorted(intervals, key=lambda item: (item[1], item[2], item[0]))
    last_end: list[float] = []
    tracks: dict[str, int] = {}
    for key, low, high in ordered:
        for index, end in enumerate(last_end):
            if end < low:
                last_end[index] = high
                tracks[key] = index
                break
        else:
            tracks[key] = len(last_end)
            last_end.append(high)
    return tracks, len(last_end)


def _channel_size(track_count: int) -> Mm:
    return max(MIN_CHANNEL_MM, 2 * GRID_MM + max(0, track_count - 1) * TRACK_PITCH_MM)


def _is_rail(net: Net, options: SchematicOptions) -> bool:
    return net.net_class in options.rail_classes and len(net.nodes) >= options.rail_min_nodes


def _collect_symbols(
    doc: PerfDocument, lookup: FootprintLookup, notes: list[str]
) -> dict[str, _Placed]:
    """One symbol per reference the design defines OR the board carries OR a net names.

    All three, and each for its own reason. A part on the board is obvious. A part in
    ``doc.parts`` is the schematic-first case -- drawn and wired before anything has been
    laid out, which is the only state a circuit is in while it is being captured. A ref
    that only a net names is neither, and it is the one that is actually wrong: something
    is wired to a part nothing in the document defines. Drawing only the intersection
    would hide two of the three.

    A part's own definition -- its footprint and value -- comes from wherever it lives,
    so an unplaced resistor is drawn as a resistor rather than as a box with two pins.
    """
    placed_by_ref = {component.ref: component for component in doc.components}
    designed_by_ref = {part.ref: part for part in doc.parts}
    pins_named: dict[str, set[str]] = defaultdict(set)
    for net in doc.nets:
        for node in net.nodes:
            pins_named[node.component_ref].add(node.pin)

    refs = sorted(
        set(pins_named) | set(placed_by_ref) | set(designed_by_ref), key=_ref_sort_key
    )
    symbols: dict[str, _Placed] = {}
    for ref in refs:
        component = placed_by_ref.get(ref)
        part = designed_by_ref.get(ref)
        value = component.value if component is not None else (part.value if part else "")
        footprint_id = (
            component.footprint_id
            if component is not None
            else (part.footprint_id if part is not None else None)
        )
        footprint = lookup(footprint_id) if footprint_id is not None else None
        owner: ComponentInstance | SchematicPart | None = (
            component if component is not None else part
        )
        if footprint_id is not None and footprint is None:
            notes.append(f"{ref}: footprint {footprint_id!r} is not in the registry")
        if footprint is not None:
            specs = tuple(
                _PinSpec(number=pin.number, name=pin_name_of(owner, pin))
                for pin in footprint.pins
            )
            missing = sorted(
                pins_named[ref] - {pin.number for pin in footprint.pins}, key=_pin_sort_key
            )
            if missing:
                notes.append(
                    f"{ref}: the netlist names pin(s) {', '.join(missing)}, "
                    f"which {footprint.id} does not have"
                )
            # The same finding from the other direction: a name the PART gives a lead the
            # package does not have. Not refused by the command that stored it, for the
            # reason ``commands.checked_pin_names`` gives, so it is said here.
            unnamed = sorted(
                {number for number, _ in (owner.pin_names if owner else ())}
                - {pin.number for pin in footprint.pins},
                key=_pin_sort_key,
            )
            if unnamed:
                notes.append(
                    f"{ref}: names pin(s) {', '.join(unnamed)}, which {footprint.id} does not have"
                )
        else:
            # No footprint to ask, so the netlist is the only account of what pins exist.
            specs = tuple(
                _PinSpec(number=number, name=None)
                for number in sorted(pins_named[ref], key=_pin_sort_key)
            )
        if not specs:
            specs = (_PinSpec(number="1", name=None),)
        kind = symbol_kind_for(footprint, len(specs))
        if owner is not None and owner.symbol is not None:
            declared, why_not = declared_symbol_kind(owner.symbol, specs, footprint)
            if declared is not None:
                kind = declared
            elif why_not is not None:
                notes.append(f"{ref}: {why_not}; drawn as a {kind} instead")
        undefined = component is None and part is None
        symbols[ref] = _Placed(
            ref=ref,
            value=value,
            kind=kind,
            footprint_id=footprint_id,
            body=_SYMBOL_BUILDERS[kind](specs, footprint),
            unplaced=component is None,
            undefined=undefined,
        )
        if undefined:
            # NOT reported for a part that is merely unplaced: on a schematic being drawn
            # that is every part on the sheet, and a note per part would bury the ones
            # that mean something. This one means something -- a net is wired to a part
            # the document does not have.
            notes.append(
                f"{ref}: wired by a net, but neither on the board nor in the design"
            )
    return symbols


#: How much wider than tall a sheet wants its GRID OF CELLS to be.
#:
#: Not the sheet's aspect ratio and not a taste: it is the ratio between how much width a
#: column costs and how much height a row costs, and they are not the same. A symbol is
#: wide and short -- a resistor is 20 mm across and 6 mm tall -- and the horizontal channels
#: that carry the trunks sit between the ROWS, so a row costs far more height than a column
#: costs width. A square grid of cells therefore draws a sheet taller than it is wide, which
#: is what the ATmega example did: 24 symbols in a 5-tall grid came out 257 x 312 mm.
#:
#: Two is measured, over the six circuits this repository ships. Against a square grid it
#: takes the big sheet from 257 x 312 to 292 x 279 -- landscape rather than portrait, which
#: is the way a schematic is read and printed -- and the total area of all six down as well.
CELL_ASPECT = 2.0


def column_cap(group_size: int) -> int:
    """How many symbols belong in one column of a group of ``group_size``.

    ONE ANSWER, THREE CONSUMERS, which is the whole reason it is a function: a layer too
    tall is split at this (:func:`_split_tall_layers`), consecutive layers too thin are
    folded together up to it (:func:`_merge_thin_columns`), and the block of parts no net
    reaches is packed at it. Two of those disagreeing would produce a layout that splits a
    column and immediately merges it back, and the third is the one people notice.

    Never below three, so a small circuit is not spread into a strip.
    """
    return max(3, math.ceil(math.sqrt(group_size / CELL_ASPECT))) if group_size else 3


def _split_tall_layers(layers: list[list[str]], group_size: int) -> list[list[str]]:
    """Break a layer that is too tall to read into consecutive columns of its own.

    BFS DEPTH IS NOT A CONSTRAINT, IT IS A HINT. A layering that puts everything one hop
    from the root in one column is right about the distance and wrong about the shape: on
    the LM317 example ten of the eleven parts hang directly off U1, which drew a sheet
    three columns wide and ten rows tall -- 129 x 239 mm, nearly twice as tall as it was
    wide, on a circuit that fits comfortably across a page. Nothing was violated by that;
    a schematic has no precedence to respect, so a part moved one column further out only
    makes its own wire span one more channel.

    The cap is :func:`column_cap`, which every other decision about column height reads
    too. Chunks are consecutive in the reference order the layer already carries, which
    keeps R1 beside R2 rather than scattering a group of equals, and is deterministic for
    the reason everything here is.
    """
    cap = column_cap(group_size)
    out: list[list[str]] = []
    for layer in layers:
        for start in range(0, len(layer), cap):
            out.append(layer[start : start + cap])
    return out


def _merge_thin_columns(columns: list[list[str]], group_size: int) -> list[list[str]]:
    """Fold consecutive columns into one while they still fit under the height cap.

    THE OTHER HALF OF :func:`_split_tall_layers`, and the same sentence: BFS depth is not
    a constraint, it is a hint. That function breaks a layer too TALL to read; this one
    joins layers too THIN to be worth a column, and the second case is the one a real
    circuit produces. A signal chain -- U1 to R1 to Q1 to K1 to J2 -- is twelve hops deep
    and one part wide at every hop, which is a correct layering and a sheet half a metre
    long: the ATmega example came out 462 x 284 mm with 24 symbols in it, six of its twelve
    columns holding a single part.

    Nothing is violated by folding them. A schematic has no precedence to respect, and two
    parts in one column are two parts a channel away from each other rather than a column
    away -- which is where a decoupling capacitor belongs anyway.

    The cap is :func:`column_cap`, the one :func:`_split_tall_layers` splits at, so the
    two cannot disagree about how tall a column should be -- a layout that split a column
    and immediately merged it back would depend on which ran last. Merging is left to right
    and consecutive, which keeps the layering's order and is deterministic.
    """
    cap = column_cap(group_size)
    merged: list[list[str]] = []
    for column in columns:
        if merged and len(merged[-1]) + len(column) <= cap:
            merged[-1].extend(column)
        else:
            merged.append(list(column))
    return merged


def _assign_cells(
    symbols: dict[str, _Placed], adjacency: dict[str, set[str]]
) -> tuple[int, int]:
    """Put every symbol in a (column, row) cell and say how big the grid came out.

    Columns come from a breadth-first layering away from the most connected part, which on
    a perfboard circuit is almost always the IC everything hangs off; rows come from four
    barycentre sweeps, the standard crossing-reduction heuristic. Neither is clever. Both
    are deterministic, which is what a golden test needs and what stops the sheet
    rearranging itself when an unrelated net is edited.
    """
    order = sorted(symbols, key=_ref_sort_key)
    visited: set[str] = set()
    columns: list[list[str]] = []
    alone: list[str] = []

    for seed in order:
        if seed in visited:
            continue
        group: list[str] = []
        queue = deque([seed])
        visited.add(seed)
        while queue:
            ref = queue.popleft()
            group.append(ref)
            for neighbour in sorted(adjacency[ref], key=_ref_sort_key):
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append(neighbour)

        if len(group) == 1:
            # A part no signal net reaches -- a mounting pillar, a part only ground
            # touches, a part nothing touches at all. One column each would draw sixteen
            # of them as a sheet two feet wide, so they are gathered into a block below
            # and the layering never sees them.
            alone.append(group[0])
            continue

        root = min(group, key=lambda ref: (-len(adjacency[ref]), _ref_sort_key(ref)))
        depth: dict[str, int] = {root: 0}
        queue = deque([root])
        while queue:
            ref = queue.popleft()
            for neighbour in sorted(adjacency[ref], key=_ref_sort_key):
                if neighbour not in depth:
                    depth[neighbour] = depth[ref] + 1
                    queue.append(neighbour)

        local: list[list[str]] = [[] for _ in range(max(depth.values()) + 1)]
        for ref in sorted(group, key=_ref_sort_key):
            local[depth[ref]].append(ref)
        columns.extend(_split_tall_layers(local, len(group)))

    columns = _merge_thin_columns(columns, len(visited) - len(alone))
    _barycentre_sweeps(columns, adjacency)

    if alone:
        tall = max((len(column) for column in columns), default=0)
        per_column = max(tall, column_cap(len(alone)))
        for start in range(0, len(alone), per_column):
            columns.append(alone[start : start + per_column])

    rows = max((len(column) for column in columns), default=0)
    for index, column in enumerate(columns):
        offset = (rows - len(column)) // 2
        for position, ref in enumerate(column):
            symbols[ref].col = index
            symbols[ref].row = offset + position
    return len(columns), rows


def _barycentre_sweeps(
    columns: list[list[str]], adjacency: dict[str, set[str]], passes: int = 4
) -> None:
    """Reorder each column by the average position of its neighbours in the column beside
    it, alternating direction. Sorted in place; ties broken by reference so the result does
    not depend on sort stability alone."""
    position: dict[str, int] = {}
    for column in columns:
        for index, ref in enumerate(column):
            position[ref] = index

    for sweep in range(passes):
        forward = sweep % 2 == 0
        indices = (
            range(1, len(columns)) if forward else range(len(columns) - 2, -1, -1)
        )
        for index in indices:
            beside = set(columns[index - 1] if forward else columns[index + 1])
            if not beside:
                continue

            def barycentre(ref: str, beside: set[str] = beside) -> tuple[float, tuple[str, int, str]]:
                near = [position[other] for other in adjacency[ref] if other in beside]
                mean = sum(near) / len(near) if near else float(position[ref])
                return (mean, _ref_sort_key(ref))

            columns[index].sort(key=barycentre)
            for place, ref in enumerate(columns[index]):
                position[ref] = place


# ---------------------------------------------------------------------------
# The drawing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ResolvedNet:
    net: Net
    rail: bool
    #: (reference, pin) in the order the netlist gave them, deduplicated.
    pins: tuple[tuple[str, SymbolPin], ...]


def _tidy(points: Sequence[Point2]) -> tuple[Point2, ...]:
    """Drop repeated points so a run that turns nowhere is a straight line, not a corner."""
    cleaned: list[Point2] = []
    for point in points:
        if cleaned and abs(cleaned[-1].x - point.x) < 1e-9 and abs(cleaned[-1].y - point.y) < 1e-9:
            continue
        cleaned.append(point)
    return tuple(cleaned)


def _segments_of(path: tuple[Point2, ...]) -> Iterator[tuple[Point2, Point2]]:
    yield from itertools.pairwise(path)


def _label_box(text: str, x: Mm, baseline: Mm) -> tuple[Mm, Mm, Mm, Mm]:
    """The rectangle a net name occupies, given where its baseline goes.

    ``Label.at`` IS the baseline for a net name -- both renderers already read it that way
    -- so the clearance above the wire is baked into the point rather than applied twice,
    once here and once by whoever draws it.
    """
    width = len(text) * NET_LABEL_MM * NET_LABEL_ADVANCE
    return x, baseline - NET_LABEL_MM, x + width, baseline


def _box_is_clear(
    box: tuple[Mm, Mm, Mm, Mm], obstacles: Sequence[tuple[Point2, Point2]]
) -> bool:
    x0, y0, x1, y1 = box
    for start, end in obstacles:
        if max(start.x, end.x) < x0 or min(start.x, end.x) > x1:
            continue
        if max(start.y, end.y) < y0 or min(start.y, end.y) > y1:
            continue
        return False
    return True


def _net_label_at(
    text: str, span: tuple[Mm, Mm], wire_y: Mm, obstacles: Sequence[tuple[Point2, Point2]]
) -> Point2:
    """Where along its own run a net name can sit without a wire through it.

    A net name belongs at the left-hand end of the run it names, so that is the first
    thing tried and, on the fixtures here, where 29 of 41 of them stay. The rest slide
    RIGHT ALONG THE SAME RUN in half-grid steps until the band above the wire is clear --
    never to another wire, never off the run, so the name is still unambiguously attached
    to the thing it names. Failing that it goes back to the left end: a label that has to
    overlap something should overlap where a reader looks for it.

    Deterministic by construction. The candidates are generated left to right and the
    first clear one wins, so the same document gives the same sheet -- which is what the
    golden dumps need and what stops the sheet rearranging itself between runs.
    """
    left, right = span
    baseline = wire_y - NET_LABEL_CLEARANCE_MM
    start = left + NET_LABEL_INSET_MM
    width = len(text) * NET_LABEL_MM * NET_LABEL_ADVANCE
    step = GRID_MM / 2
    x = start
    while True:
        if _box_is_clear(_label_box(text, x, baseline), obstacles):
            return Point2(x=x, y=baseline)
        x += step
        if x + width > right:
            return Point2(x=start, y=baseline)


def build_schematic(
    doc: PerfDocument,
    lookup: FootprintLookup,
    options: SchematicOptions = DEFAULT_SCHEMATIC_OPTIONS,
) -> SchematicDrawing:
    """Draw the netlist.

    TWO KINDS OF SHEET, AND THE DOCUMENT DECIDES WHICH. With ``doc.sheet`` empty the whole
    drawing is derived, exactly as it always was: symbols laid out in a grid of cells and
    wires routed in the channels between them, so no wire can cross a symbol and the same
    document always produces the same picture. With positions stored, the sheet is a
    DRAWING somebody made -- every symbol sits where they put it, turned how they turned
    it, joined by the wires they drew, and what they did not draw a wire for is joined by
    NAME, with a label at the pin. That is not a fallback, it is what a schematic does with
    a net too busy to draw.

    The second kind exists because a tool that can capture a circuit and cannot draw one
    sends people back to KiCad. The first is still what every imported netlist, every fresh
    document and every press of Arrange produces, which is what keeps "open it and look at
    it" free.

    Works on whatever the document has. No netlist gives a sheet of unconnected symbols,
    which is a fair picture of a board nobody has declared anything about; no parts gives
    an empty sheet and says so in ``notes``.
    """
    notes: list[str] = []
    symbols = _collect_symbols(doc, lookup, notes)
    if not symbols:
        return SchematicDrawing(
            notes=("Nothing to draw: the document has no parts and no netlist.",)
        )

    annotations = tuple(
        Annotation(kind=n.kind, at=n.at, to=n.to, text=n.text, size_mm=n.size_mm)
        for n in doc.sheet_notes
    )
    resolved = _resolve_nets(doc, symbols, notes, options)

    # doc.sheet is keyed on the part's ID -- so a position survives a rename, and survives
    # a part moving between doc.parts and doc.components -- and everything from here on is
    # keyed on the reference, which is what the drawing speaks.
    ref_of = {part.id: part.ref for part in doc.parts}
    ref_of.update({component.id: component.ref for component in doc.components})
    placements = {
        ref_of[placement.id]: placement
        for placement in doc.sheet
        if placement.id in ref_of and ref_of[placement.id] in symbols
    }
    if placements:
        return _hand_drawn_sheet(doc, symbols, resolved, placements, options, notes, annotations)
    return _derived_sheet(symbols, resolved, options, notes, annotations)


def _resolve_nets(
    doc: PerfDocument,
    symbols: dict[str, _Placed],
    notes: list[str],
    options: SchematicOptions,
) -> list[_ResolvedNet]:
    """Every net, paired with the pins of it that are actually on the sheet.

    Both kinds of sheet need exactly this and neither should ask the question twice: a node
    naming a pin the footprint does not have is a note here and must not count as a
    connection anywhere downstream.
    """
    pin_index: dict[tuple[str, str], SymbolPin] = {}
    for ref, placed in symbols.items():
        for pin in placed.body.pins:
            pin_index[(ref, pin.number)] = pin

    resolved: list[_ResolvedNet] = []
    for net in doc.nets:
        seen: set[tuple[str, str]] = set()
        picked: list[tuple[str, SymbolPin]] = []
        for node in net.nodes:
            node_key = (node.component_ref, node.pin)
            if node_key in seen:
                continue
            seen.add(node_key)
            found = pin_index.get(node_key)
            if found is None:
                notes.append(
                    f"{net.name}: {node.component_ref} pin {node.pin} is not on the sheet"
                )
                continue
            picked.append((node.component_ref, found))
        if not picked:
            notes.append(f"{net.name}: no pin of this net could be drawn")
            continue
        if len(picked) == 1:
            notes.append(f"{net.name}: only one pin, so it is drawn as a stub")
        resolved.append(
            _ResolvedNet(net=net, rail=_is_rail(net, options), pins=tuple(picked))
        )

    return resolved


# ---------------------------------------------------------------------------
# The sheet somebody drew
# ---------------------------------------------------------------------------
#
# A DRAWING AND NOT A LAYOUT. Every symbol sits where it was put, turned how it was
# turned, and the wires are the ones somebody drew. Nothing here arranges anything, and
# that is the whole difference: the derived sheet is a picture OF the netlist, and this is
# a picture somebody made that the netlist agrees with.
#
# What is NOT drawn as a wire is drawn as a net LABEL at the pin, which is the part worth
# being clear about. It is not a fallback for wires nobody got round to: naming a net at
# the pin is how every schematic joins a bus, a clock or a reset line that would otherwise
# cross the whole page, and it is the second way of connecting that the sheet needs in
# order to be usable at all. Two pins carrying the same name are the same net -- which here
# is simply true, because the net is ``doc.nets`` and the label is printed FROM it.

#: How far a net label's stub runs out of the pin before the name is written.
LABEL_STUB_MM: Mm = 2 * GRID_MM

#: How far a rail glyph hangs off a pin nobody drew a wire to.
RAIL_STUB_MM: Mm = 3 * GRID_MM

#: The gap between symbols parked at the edge of a hand-drawn sheet, and between that
#: column and the drawing.
PARK_GAP_MM: Mm = 3 * GRID_MM


def _wire_net_of(doc: PerfDocument, wire: SheetWire) -> Net | None:
    """The net holding both ends of a drawn wire, if one still does.

    THE WIRE CARRIES NO NET ID, and this is why. A wire is geometry; what is CONNECTED is
    ``doc.nets``, and asking the netlist every time is what makes a wire left over from a
    connection somebody has since removed stop being drawn instead of quietly asserting a
    join that no longer exists. It is also what makes renaming a net cost nothing here.
    """
    for net in doc.nets:
        nodes = set(net.nodes)
        if wire.a in nodes and wire.b in nodes:
            return net
    return None


def _reanchored(path: tuple[Point2, ...], start: Point2, end: Point2) -> tuple[Point2, ...]:
    """The drawn path with its two ends moved onto the pins they belong to.

    A SYMBOL THAT MOVES TAKES ITS WIRES WITH IT, which is what every schematic editor does
    and what anybody dragging one expects. Only the two end segments give: the first point
    becomes the pin, and the point after it slides along whichever axis that segment ran on
    so the chain stays orthogonal. Everything in the middle is left exactly as drawn, so a
    route somebody took the trouble to lay out is not re-derived behind their back.
    """
    if len(path) < 3:
        # Nothing in the middle to preserve, and the two fixups below would fight over the
        # same point -- on a two-point path, ``points[0]`` and ``points[-2]`` are the same
        # element, so the second would undo the first. An elbow, horizontal first, which is
        # what the panel's own preview draws.
        if start.x == end.x or start.y == end.y:
            return (start, end)
        return (start, _p(end.x, start.y), end)
    points = list(path)
    if points[0] != start:
        horizontal = abs(points[1].y - points[0].y) < abs(points[1].x - points[0].x)
        points[1] = _p(points[1].x, start.y) if horizontal else _p(start.x, points[1].y)
        points[0] = start
    if points[-1] != end:
        horizontal = abs(points[-2].y - points[-1].y) < abs(points[-2].x - points[-1].x)
        points[-2] = _p(points[-2].x, end.y) if horizontal else _p(end.x, points[-2].y)
        points[-1] = end
    return _tidy(points)


def _hand_drawn_sheet(
    doc: PerfDocument,
    symbols: dict[str, _Placed],
    resolved: list[_ResolvedNet],
    placements: dict[str, SymbolPlacement],
    options: SchematicOptions,
    notes: list[str],
    annotations: tuple[Annotation, ...],
) -> SchematicDrawing:
    """Draw the sheet as it was arranged, and join by name whatever has no wire."""
    # -- where everything is, and which way round ---------------------------
    for ref, placed in symbols.items():
        placement = placements.get(ref)
        if placement is None:
            continue
        placed.body = _orient_body(placed.body, placement.rotation, placement.mirrored)
        placed.x, placed.y = placement.at.x, placement.at.y

    # A part added after the sheet was arranged has nowhere to be, so it is PARKED in a
    # column past the right-hand edge rather than dropped at the origin on top of whatever
    # is there. It is drawn, it is labelled, and moving it is one drag -- which is a better
    # answer than rearranging a sheet somebody laid out by hand in order to make room.
    parked = sorted((ref for ref in symbols if ref not in placements), key=_ref_sort_key)
    if parked:
        right = max(
            (placed.x + placed.body.width for ref, placed in symbols.items() if ref in placements),
            default=MARGIN_MM,
        )
        top = min(
            (placed.y for ref, placed in symbols.items() if ref in placements),
            default=MARGIN_MM,
        )
        cursor = top
        for ref in parked:
            placed = symbols[ref]
            placed.x = right + PARK_GAP_MM
            placed.y = cursor
            cursor += placed.body.height + PARK_GAP_MM

    # -- the wires somebody drew --------------------------------------------
    wires: list[Wire] = []
    drawn_pins: set[tuple[str, str]] = set()
    for wire in doc.sheet_wires:
        net = _wire_net_of(doc, wire)
        if net is None:
            continue
        start = _pin_of(symbols, wire.a)
        end = _pin_of(symbols, wire.b)
        if start is None or end is None:
            continue
        wires.append(
            Wire(
                net_id=net.id,
                net_name=net.name,
                net_class=net.net_class,
                path=_reanchored(wire.path, start, end),
            )
        )
        drawn_pins.add((wire.a.component_ref, wire.a.pin))
        drawn_pins.add((wire.b.component_ref, wire.b.pin))

    # -- and a name, or a rail glyph, on everything else ---------------------
    rails: list[Rail] = []
    net_labels: list[Label] = []
    for item in resolved:
        for ref, pin in item.pins:
            if (ref, pin.number) in drawn_pins:
                continue
            anchor = symbols[ref].anchor_of(pin)
            if item.rail:
                upward = item.net.net_class == "power"
                end = _p(anchor.x, anchor.y + (-RAIL_STUB_MM if upward else RAIL_STUB_MM))
                rails.append(
                    Rail(
                        net_id=item.net.id,
                        net_name=item.net.name,
                        net_class=item.net.net_class,
                        path=(anchor, end),
                        at=end,
                        direction="up" if upward else "down",
                    )
                )
                continue
            if len(item.pins) < 2:
                # One pin and nothing to join it to. Saying the name would claim a
                # connection to something; the derived sheet draws a stub here and says so
                # in the notes, and so does this.
                continue
            dx, dy = PIN_DIRECTION[pin.side]
            end = _p(anchor.x + dx * LABEL_STUB_MM, anchor.y + dy * LABEL_STUB_MM)
            wires.append(
                Wire(
                    net_id=item.net.id,
                    net_name=item.net.name,
                    net_class=item.net.net_class,
                    path=(anchor, end),
                )
            )
            net_labels.append(
                Label(
                    text=item.net.name,
                    at=end,
                    kind="net",
                    anchor="left" if dx > 0 else "right" if dx < 0 else "centre",
                )
            )

    # -- dots where three or more ends of one net meet ----------------------
    junctions = _junctions_of(wires)

    wired_pins = {(ref, pin.number) for item in resolved for ref, pin in item.pins}
    no_connects = [
        NoConnect(ref=ref, pin=pin.number, at=symbols[ref].anchor_of(pin))
        for ref in sorted(symbols, key=_ref_sort_key)
        for pin in symbols[ref].body.pins
        if (ref, pin.number) not in wired_pins
    ]

    ordered = sorted(symbols.values(), key=lambda placed: _ref_sort_key(placed.ref))
    part_labels = _part_labels(ordered, options)

    width, height = _sheet_extent(ordered, wires, rails, no_connects, annotations)

    drawn = tuple(
        Symbol(
            ref=placed.ref,
            value=placed.value,
            kind=placed.kind,
            footprint_id=placed.footprint_id,
            at=_p(placed.x, placed.y),
            shapes=placed.body.shapes,
            pins=placed.body.pins,
            width=placed.body.width,
            height=placed.body.height,
            unplaced=placed.unplaced,
            undefined=placed.undefined,
            rotation=placements[placed.ref].rotation if placed.ref in placements else 0,
            mirrored=placements[placed.ref].mirrored if placed.ref in placements else False,
            positioned=placed.ref in placements,
        )
        for placed in ordered
    )
    if parked:
        notes.append(
            f"{len(parked)} part(s) have no place on this sheet yet and are parked at the "
            f"right-hand edge: {', '.join(parked)}"
        )
    return SchematicDrawing(
        symbols=drawn,
        wires=tuple(wires),
        rails=tuple(rails),
        junctions=junctions,
        no_connects=tuple(no_connects),
        labels=(*part_labels, *net_labels),
        annotations=annotations,
        width=width,
        height=height,
        notes=tuple(notes),
    )


def _pin_of(symbols: dict[str, _Placed], node: NetNode) -> Point2 | None:
    placed = symbols.get(node.component_ref)
    if placed is None:
        return None
    for pin in placed.body.pins:
        if pin.number == node.pin:
            return placed.anchor_of(pin)
    return None


def _junctions_of(wires: Sequence[Wire]) -> tuple[Junction, ...]:
    """A dot where three or more ends of one net meet at a point.

    THREE, NOT TWO, and that is the whole convention: two wires meeting end to end are one
    wire that turns a corner, and a dot there claims a join that is really a bend. Counted
    from the ENDS only -- a wire crossing another in the middle is an ordinary schematic
    crossing and carries no dot, which is what lets a reader tell the two apart.
    """
    counts: dict[tuple[NetId, float, float], int] = defaultdict(int)
    for wire in wires:
        for end in (wire.path[0], wire.path[-1]):
            counts[(wire.net_id, end.x, end.y)] += 1
    return tuple(
        Junction(net_id=net_id, at=_p(x, y))
        for (net_id, x, y), count in sorted(counts.items())
        if count >= 3
    )


def _part_labels(ordered: Sequence[_Placed], options: SchematicOptions) -> list[Label]:
    """The reference, the value and the pin numbers. One answer for both kinds of sheet."""
    labels: list[Label] = []
    for placed in ordered:
        centre = placed.x + placed.body.width / 2
        # Well clear of the box rather than snug to it: a reference is drawn at a fixed
        # PIXEL size, so how many millimetres of sheet it occupies grows as the view zooms
        # out -- and the one symbol with anything near its top edge is the LED.
        labels.append(
            Label(
                text=placed.ref,
                at=_p(centre, placed.y - 0.75 * GRID_MM),
                kind="ref",
                anchor="centre",
            )
        )
        if options.show_values and placed.value:
            labels.append(
                Label(
                    text=placed.value,
                    at=_p(centre, placed.y + placed.body.height + 0.4 * GRID_MM),
                    kind="value",
                    anchor="centre",
                )
            )
        # A relay is numbered like a box because its contacts ARE numbered and nothing
        # else on the symbol says which is which -- that refusal is only honest if the
        # numbers are there to read. A switch deliberately is not: its two legs per side
        # are one node inside the part, so which of them a net lands on is a question about
        # holes and not about the circuit, and two labels at the join would sit on top of
        # the lines that say they are joined.
        #
        # A pin the part NAMES prints the name inside the body, where the number used to
        # be, and its number on the lead outside -- the arrangement every schematic uses,
        # and the only one where both fit. A box none of whose pins is named draws exactly
        # what it always did.
        if placed.kind in ("ic", "connector", "box", "relay"):
            for pin in placed.body.pins:
                inside = _inside_text(pin, options)
                if inside is None:
                    continue
                inset = LEAD_MM + 0.5 * GRID_MM
                if pin.name and placed.kind == "connector":
                    inset = LEAD_MM + _CONNECTOR_NAME_INSET_MM
                if pin.side == "left":
                    labels.append(
                        Label(
                            text=inside,
                            at=_p(placed.x + inset, placed.y + pin.at.y),
                            kind="pin",
                            anchor="left",
                        )
                    )
                elif pin.side == "right":
                    labels.append(
                        Label(
                            text=inside,
                            at=_p(placed.x + placed.body.width - inset, placed.y + pin.at.y),
                            kind="pin",
                            anchor="right",
                        )
                    )
                else:
                    # A turned symbol's pins run along the top or the bottom, where a
                    # number beside the lead would sit on the lead next to it. Centred over
                    # the lead instead, just inside the body.
                    inward = inset if pin.side == "top" else -inset
                    labels.append(
                        Label(
                            text=inside,
                            at=_p(placed.x + pin.at.x, placed.y + pin.at.y + inward),
                            kind="pin",
                            anchor="centre",
                        )
                    )
                if pin.name and options.show_pin_numbers:
                    labels.append(_lead_number(placed, pin))
        elif options.show_pin_numbers and placed.kind in _TRANSISTOR_KINDS:
            # Which PACKAGE leg is the gate is the question the declaration answered, and
            # the answer is only useful at the bench if the number is on the sheet: the
            # symbol says G, the board says pin 1.
            labels.extend(_lead_number(placed, pin) for pin in placed.body.pins)
    return labels


_TRANSISTOR_KINDS: frozenset[SymbolKind] = frozenset({"npn", "pnp", "nmos", "pmos"})


def _inside_text(pin: SymbolPin, options: SchematicOptions) -> str | None:
    """What a box prints inside its body at one pin: the name if it has one, else the number.

    On a TURNED box the pins are a pin pitch apart along the top or bottom edge, and a
    name centred over its lead that is wider than that pitch would sit on its neighbour.
    Such a name falls back to the number there -- turning the box back upright shows it.
    """
    if pin.name:
        if pin.side in ("top", "bottom") and pin_label_width(pin.name) > PIN_PITCH_MM - GRID_MM:
            return pin.number if options.show_pin_numbers else None
        return pin.name
    return pin.number if options.show_pin_numbers else None


def _lead_number(placed: _Placed, pin: SymbolPin) -> Label:
    """A pin's number on its lead, outside the body: below a sideways lead, beside an
    upright one. A grid square in from the end, so it never reaches the wire."""
    along, off = GRID_MM, 0.45 * GRID_MM
    x, y = placed.x + pin.at.x, placed.y + pin.at.y
    if pin.side == "left":
        return Label(text=pin.number, at=_p(x + along, y + off), kind="pin", anchor="centre")
    if pin.side == "right":
        return Label(text=pin.number, at=_p(x - along, y + off), kind="pin", anchor="centre")
    if pin.side == "top":
        return Label(text=pin.number, at=_p(x + off, y + along), kind="pin", anchor="left")
    return Label(text=pin.number, at=_p(x + off, y - along), kind="pin", anchor="left")


def _sheet_extent(
    ordered: Sequence[_Placed],
    wires: Sequence[Wire],
    rails: Sequence[Rail],
    no_connects: Sequence[NoConnect],
    annotations: Sequence[Annotation],
) -> tuple[Mm, Mm]:
    """How big the paper has to be. A margin past everything that is on it.

    The origin stays at zero rather than the drawing being shifted up against it: a symbol
    is where the document says it is, and a sheet that slid under the user because they
    deleted the top-left part would move everything they had lined up.
    """
    right = MARGIN_MM
    bottom = MARGIN_MM
    for placed in ordered:
        right = max(right, placed.x + placed.body.width)
        bottom = max(bottom, placed.y + placed.body.height)
    runs: list[tuple[Point2, ...]] = [wire.path for wire in wires]
    runs.extend(rail.path for rail in rails)
    for path in runs:
        for point in path:
            right = max(right, point.x)
            bottom = max(bottom, point.y)
    for mark in no_connects:
        right = max(right, mark.at.x)
        bottom = max(bottom, mark.at.y)
    for note in annotations:
        right = max(right, note.at.x, note.to.x)
        bottom = max(bottom, note.at.y, note.to.y)
    # A label's own width is not known here -- it is drawn at a size the renderer picks --
    # so the margin doubles as the room for a net name written at the right-hand edge.
    return right + 2 * MARGIN_MM, bottom + MARGIN_MM


def _derived_sheet(
    symbols: dict[str, _Placed],
    resolved: list[_ResolvedNet],
    options: SchematicOptions,
    notes: list[str],
    annotations: tuple[Annotation, ...],
) -> SchematicDrawing:
    """The sheet nobody has drawn on: cells, channels, and a routed picture of the netlist.

    This is the original ``build_schematic`` body, unchanged in what it produces. The three
    decisions it rests on are in the module docstring, and the one that matters most here
    is that symbols live in cells and wires live only in the channels between them -- which
    is why no wire crosses a symbol, as a consequence of where the tracks may be rather
    than as a tuning parameter.
    """
    # Rails are deliberately absent from the graph. A ground net touching every part would
    # make every part adjacent to every other, and the layering below would put the whole
    # circuit in two columns -- which is exactly the hairball the glyphs exist to prevent,
    # arriving by the back door.
    adjacency: dict[str, set[str]] = {ref: set() for ref in symbols}
    for item in resolved:
        if item.rail:
            continue
        touched = sorted({ref for ref, _ in item.pins}, key=_ref_sort_key)
        for first in range(len(touched)):
            for second in range(first + 1, len(touched)):
                adjacency[touched[first]].add(touched[second])
                adjacency[touched[second]].add(touched[first])

    ncols, nrows = _assign_cells(symbols, adjacency)

    column_width = [0.0] * ncols
    row_height = [0.0] * nrows
    for placed in symbols.values():
        column_width[placed.col] = max(column_width[placed.col], placed.body.width)
        row_height[placed.row] = max(row_height[placed.row], placed.body.height)

    # -- which channel each run belongs in ----------------------------------
    #
    # Rails take a lane out of the same pool the trunks do. A ground glyph is three
    # horizontal bars, so a trunk running along the line it is drawn on reads as part of
    # it -- and unlike a crossing, there is no convention that says otherwise. Reserving
    # the lane costs at most one extra track in a channel, and rails pack into it densely
    # because each claims a single column rather than a span.
    def _rail_key(net_id: NetId, ref: str, number: str) -> str:
        return f"rail\x1f{net_id}\x1f{ref}\x1f{number}"

    pin_channel: dict[tuple[NetId, str, str], int] = {}
    trunk_channel: dict[NetId, int] = {}
    rail_channel: dict[str, int] = {}
    horizontal_runs: dict[int, list[tuple[str, float, float]]] = defaultdict(list)
    for item in resolved:
        spanned: list[int] = []
        for ref, pin in item.pins:
            channel = symbols[ref].col if pin.side == "left" else symbols[ref].col + 1
            pin_channel[(item.net.id, ref, pin.number)] = channel
            spanned.append(channel)
        if item.rail:
            upward = item.net.net_class == "power"
            for ref, pin in item.pins:
                channel = symbols[ref].row if upward else symbols[ref].row + 1
                key = _rail_key(item.net.id, ref, pin.number)
                rail_channel[key] = channel
                lane = float(pin_channel[(item.net.id, ref, pin.number)])
                horizontal_runs[channel].append((key, lane, lane))
            continue
        if len(item.pins) < 2:
            continue
        mean_row = sum(symbols[ref].row for ref, _ in item.pins) / len(item.pins)
        channel = min(nrows, int(mean_row) + 1)
        trunk_channel[item.net.id] = channel
        horizontal_runs[channel].append(
            (item.net.id, float(min(spanned)), float(max(spanned)))
        )

    horizontal_track: dict[str, int] = {}
    horizontal_tracks = [0] * (nrows + 1)
    for channel, runs in horizontal_runs.items():
        assigned, count = _assign_tracks(runs)
        horizontal_track.update(assigned)
        horizontal_tracks[channel] = count

    # -- y, which depends only on the horizontal channels -------------------
    horizontal_gap = [_channel_size(count) for count in horizontal_tracks]
    cursor = MARGIN_MM
    horizontal_channel_y = [0.0] * (nrows + 1)
    row_y = [0.0] * nrows
    for index in range(nrows):
        horizontal_channel_y[index] = cursor
        cursor += horizontal_gap[index]
        row_y[index] = cursor
        cursor += row_height[index]
    horizontal_channel_y[nrows] = cursor
    cursor += horizontal_gap[nrows]
    height = cursor + MARGIN_MM

    for placed in symbols.values():
        placed.y = row_y[placed.row] + (row_height[placed.row] - placed.body.height) / 2

    def _lane_y(channel: int, key: str) -> Mm:
        return horizontal_channel_y[channel] + GRID_MM + horizontal_track[key] * TRACK_PITCH_MM

    trunk_y: dict[NetId, float] = {
        net_id: _lane_y(channel, net_id) for net_id, channel in trunk_channel.items()
    }
    rail_y: dict[str, float] = {
        key: _lane_y(channel, key) for key, channel in rail_channel.items()
    }

    # -- x, which needs the y above to know which verticals overlap ---------
    def _segment_key(net_id: NetId, ref: str, number: str) -> str:
        return f"{net_id}\x1f{ref}\x1f{number}"

    vertical_runs: dict[int, list[tuple[str, float, float]]] = defaultdict(list)
    for item in resolved:
        for ref, pin in item.pins:
            anchor_y = symbols[ref].anchor_of(pin).y
            run_key = _segment_key(item.net.id, ref, pin.number)
            if item.rail:
                # Padded PAST the anchor by the glyph's depth, so nothing else is given the
                # same track through the space the bars are drawn in.
                glyph = rail_y[_rail_key(item.net.id, ref, pin.number)]
                beyond = glyph + (
                    -RAIL_GLYPH_DEPTH_MM if glyph < anchor_y else RAIL_GLYPH_DEPTH_MM
                )
                low, high = min(anchor_y, beyond), max(anchor_y, beyond)
            elif len(item.pins) < 2:
                low = high = anchor_y
            else:
                other = trunk_y[item.net.id]
                low, high = min(anchor_y, other), max(anchor_y, other)
            vertical_runs[pin_channel[(item.net.id, ref, pin.number)]].append(
                (run_key, low, high)
            )

    vertical_track: dict[str, int] = {}
    vertical_tracks = [0] * (ncols + 1)
    for channel, runs in vertical_runs.items():
        assigned, count = _assign_tracks(runs)
        vertical_track.update(assigned)
        vertical_tracks[channel] = count

    vertical_gap = [_channel_size(count) for count in vertical_tracks]
    cursor = MARGIN_MM
    vertical_channel_x = [0.0] * (ncols + 1)
    column_x = [0.0] * ncols
    for index in range(ncols):
        vertical_channel_x[index] = cursor
        cursor += vertical_gap[index]
        column_x[index] = cursor
        cursor += column_width[index]
    vertical_channel_x[ncols] = cursor
    cursor += vertical_gap[ncols]
    width = cursor + MARGIN_MM

    for placed in symbols.values():
        placed.x = column_x[placed.col] + (column_width[placed.col] - placed.body.width) / 2

    def _track_x(net_id: NetId, ref: str, number: str) -> Mm:
        key = _segment_key(net_id, ref, number)
        channel = pin_channel[(net_id, ref, number)]
        return vertical_channel_x[channel] + GRID_MM + vertical_track[key] * TRACK_PITCH_MM

    # -- emit ----------------------------------------------------------------
    wires: list[Wire] = []
    rails: list[Rail] = []
    junctions: list[Junction] = []
    net_labels: list[Label] = []
    # (name, the run's x span, the run's y). Placing a net name needs every OTHER run on
    # the sheet to already exist, and half of them are emitted after this one.
    pending_labels: list[tuple[str, tuple[Mm, Mm], Mm]] = []

    for item in resolved:
        net = item.net
        if item.rail:
            for ref, pin in item.pins:
                anchor = symbols[ref].anchor_of(pin)
                x = _track_x(net.id, ref, pin.number)
                end_y = rail_y[_rail_key(net.id, ref, pin.number)]
                rails.append(
                    Rail(
                        net_id=net.id,
                        net_name=net.name,
                        net_class=net.net_class,
                        path=_tidy((anchor, Point2(x=x, y=anchor.y), Point2(x=x, y=end_y))),
                        at=Point2(x=x, y=end_y),
                        direction="up" if end_y < anchor.y else "down",
                    )
                )
            continue

        if len(item.pins) == 1:
            ref, pin = item.pins[0]
            anchor = symbols[ref].anchor_of(pin)
            x = _track_x(net.id, ref, pin.number)
            path = _tidy((anchor, Point2(x=x, y=anchor.y)))
            if len(path) > 1:
                wires.append(
                    Wire(
                        net_id=net.id, net_name=net.name, net_class=net.net_class, path=path
                    )
                )
            pending_labels.append(
                (net.name, (min(anchor.x, x), max(anchor.x, x)), anchor.y)
            )
            continue

        y = trunk_y[net.id]
        branch_x: list[Mm] = []
        for ref, pin in item.pins:
            anchor = symbols[ref].anchor_of(pin)
            x = _track_x(net.id, ref, pin.number)
            branch_x.append(x)
            path = _tidy((anchor, Point2(x=x, y=anchor.y), Point2(x=x, y=y)))
            if len(path) > 1:
                wires.append(
                    Wire(
                        net_id=net.id, net_name=net.name, net_class=net.net_class, path=path
                    )
                )
        left, right = min(branch_x), max(branch_x)
        wires.append(
            Wire(
                net_id=net.id,
                net_name=net.name,
                net_class=net.net_class,
                path=(Point2(x=left, y=y), Point2(x=right, y=y)),
            )
        )
        for x in branch_x:
            if left < x < right:
                junctions.append(Junction(net_id=net.id, at=Point2(x=x, y=y)))
        pending_labels.append((net.name, (left, right), y))

    # Every pin the netlist reaches, so the rest can be marked. Read off `resolved` rather
    # than off `doc.nets`, because a node naming a pin the footprint does not have was
    # already dropped with a note and must not count as a connection.
    wired_pins = {(ref, pin.number) for item in resolved for ref, pin in item.pins}
    no_connects: list[NoConnect] = []
    for ref in sorted(symbols, key=_ref_sort_key):
        placed = symbols[ref]
        for pin in placed.body.pins:
            if (ref, pin.number) not in wired_pins:
                no_connects.append(
                    NoConnect(ref=ref, pin=pin.number, at=placed.anchor_of(pin))
                )

    obstacles: list[tuple[Point2, Point2]] = []
    for wire in wires:
        obstacles.extend(_segments_of(wire.path))
    for rail in rails:
        obstacles.extend(_segments_of(rail.path))
        obstacles.extend(rail_glyph_bars(rail))
    for name, span, y in pending_labels:
        at = _net_label_at(name, span, y, obstacles)
        net_labels.append(Label(text=name, at=at, kind="net", anchor="left"))

    ordered = sorted(symbols.values(), key=lambda placed: _ref_sort_key(placed.ref))
    # The same call the hand-drawn sheet makes. A reference sitting a different
    # distance above its symbol depending on which kind of sheet it is on would be one
    # fact with two answers, and the exporters read whichever they were given.
    part_labels = _part_labels(ordered, options)

    drawn = tuple(
        Symbol(
            ref=placed.ref,
            value=placed.value,
            kind=placed.kind,
            footprint_id=placed.footprint_id,
            at=Point2(x=placed.x, y=placed.y),
            shapes=placed.body.shapes,
            pins=placed.body.pins,
            width=placed.body.width,
            height=placed.body.height,
            unplaced=placed.unplaced,
            undefined=placed.undefined,
        )
        for placed in ordered
    )

    return SchematicDrawing(
        symbols=drawn,
        wires=tuple(wires),
        rails=tuple(rails),
        junctions=tuple(junctions),
        no_connects=tuple(no_connects),
        labels=(*part_labels, *net_labels),
        annotations=annotations,
        width=width,
        height=height,
        notes=tuple(notes),
    )
