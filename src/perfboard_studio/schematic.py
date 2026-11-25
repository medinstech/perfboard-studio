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
- **The sheet is arranged the way a person draws it, and a net between blocks is said by
  name** (``schlayout.arrange_sheet``): the chips are hubs, the parts their pins reach sit
  beside those pins, connectors at the edges, and each short connection is a wire laid by
  ``route_sheet_wire`` round every symbol's box, so no wire crosses a symbol. The first
  sheet put every symbol in a cell of a column/row grid and ran every wire in the channels
  between them; nothing crossed a symbol there either, but a chip's crystal and reset parts
  went wherever the grid had a free cell, joined to it by a pair of names. Wires still cross
  each other, which is what junction dots are for; that is a schematic, not a defect.

Everything is millimetres on a 2.54 mm grid, which is the grid schematics are drawn on and
the same scene unit ``ui/view2d.py`` already uses, so the renderer needs no scale factor.
Coordinates grow right and down, matching the rest of the application.
"""

from __future__ import annotations

import dataclasses
import heapq
import itertools
import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .connectivity import FootprintLookup
from .model import (
    ComponentInstance,
    LooseWire,
    Mm,
    Net,
    NetClass,
    NetId,
    NetNode,
    PerfDocument,
    Point2,
    Rotation,
    SchematicPart,
    SheetNoteKind,
    SheetPort,
    SheetPortKind,
    SheetWire,
    SymbolPlacement,
    net_named,
    pin_name_of,
    pin_roles_misfit,
    roles_misfit_phrase,
)
from .schsymbols import (
    _CONNECTOR_NAME_INSET_MM,
    BUILDERS,
    PinSpec,
    SymbolBody,
    _p,
    _pin_sort_key,
)

# Re-exported: the window, the exporter and the tests have always read these from here.
from .schsymbols import DECLARED_SYMBOL_PINS as DECLARED_SYMBOL_PINS
from .schsymbols import DECLARED_SYMBOL_RULES as DECLARED_SYMBOL_RULES
from .schsymbols import GRID_MM as GRID_MM
from .schsymbols import LEAD_MM as LEAD_MM
from .schsymbols import NET_LABEL_ADVANCE as NET_LABEL_ADVANCE
from .schsymbols import NET_LABEL_MM as NET_LABEL_MM
from .schsymbols import PIN_LABEL_MM as PIN_LABEL_MM
from .schsymbols import PIN_PITCH_MM as PIN_PITCH_MM
from .schsymbols import PinSide as PinSide
from .schsymbols import SymbolKind as SymbolKind
from .schsymbols import SymbolPin as SymbolPin
from .schsymbols import SymbolShape as SymbolShape
from .schsymbols import declared_symbol_kind as declared_symbol_kind
from .schsymbols import pin_label_width as pin_label_width
from .schsymbols import symbol_kind_for as symbol_kind_for
from .system import circuit_parts, every_component

# ---------------------------------------------------------------------------
# The sheet's units
# ---------------------------------------------------------------------------


#: One routing track. A channel carrying n of them is n of these wide, plus a margin.
TRACK_PITCH_MM: Mm = GRID_MM


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


#: The height a part's reference and its value are drawn at, in millimetres of sheet.
#:
#: The same arrangement again: the derived layout reserves a band above and below every
#: row of symbols for these two (``REF_BAND_MM``, ``VALUE_BAND_MM``), and the exported sheet takes its sizes
#: from here (``SheetInk.ref_mm`` / ``value_mm``) so the band was measured for the text
#: that is actually drawn in it.
REF_LABEL_MM: Mm = 1.7
VALUE_LABEL_MM: Mm = 1.4

#: The room above and below a row of symbols that belongs to the row's references and
#: values, and that no channel lane may use.
#:
#: WITHOUT IT A TRUNK RAN THROUGH THE TEXT. A row was exactly as tall as its tallest body,
#: and the first lane of the channel under it sat one grid step below that body -- which
#: is where the value is printed, 1.0 to 2.5 mm down. On a 555 drawn from a netlist the
#: trunks went through "NE555", "10nF" and "J1" in one sheet. A reference starts 3.6 mm
#: over its body, so a step above puts the last lane there at least 1.5 mm clear of it; a
#: step below puts the first lane under a value 2.6 mm clear.
#: ``test_no_trunk_runs_through_a_reference_or_a_value`` is the measurement.
#:
#: WHOLE GRID STEPS, BOTH OF THEM, and half a step under each row was tried: every row
#: after the first then started half a step off the grid, and the first edit -- which
#: freezes the sheet by snapping every symbol to the grid -- moved every one of them.
REF_BAND_MM: Mm = GRID_MM
VALUE_BAND_MM: Mm = GRID_MM


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

#: Half-side of the open square drawn on the dangling end of a free wire (``FreeWire``).
FREE_END_MM: Mm = 0.25 * GRID_MM


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


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
    #: For a wire somebody drew, the two pins that name it (``SheetWire.a`` and ``.b``):
    #: what a T drawn onto it says it lands on. ``None`` for everything the sheet derives.
    ends: tuple[NetNode, NetNode] | None = None


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

    AT THE PIN, ON BOTH KINDS OF SHEET (``_rail_at_pin``), AND UPRIGHT: a ground always
    points down and a supply always up, which is the convention a beginner reads a ground
    by -- three bars turned on their side did not read as one. Out of a pin on a symbol's
    side the stub runs out and then turns half a pin pitch, so the glyph stands in the gap
    between this row and the next and not on the next pin's lead (``_rail_outs``). The sheet
    drawn for you used to run every rail to a lane of its own between two rows, and the
    first edit, which freezes the sheet, drew them at the pin instead: every rail on the
    sheet changed shape under the user's first click. Now there is one shape, and freezing
    keeps it (``test_a_freeze_moves_no_rail``).
    """

    net_id: NetId
    net_name: str
    net_class: NetClass
    path: tuple[Point2, ...]
    at: Point2
    direction: Literal["down", "up"]
    #: The id of the ``SheetPort`` this glyph draws, when somebody put it down; None for
    #: the glyph the sheet draws at a pin nothing else is wired at.
    port: str | None = None


@dataclass(frozen=True, slots=True)
class PlacedPort:
    """Where a port somebody put down is on the drawing, for a click to find it: its glyph
    or its name, as ``box`` (x0, y0, x1, y1, sheet millimetres)."""

    id: str
    kind: SheetPortKind
    name: str
    at: Point2
    box: tuple[Mm, Mm, Mm, Mm]


@dataclass(frozen=True, slots=True)
class FreeWire:
    """A wire drawn on the sheet with an end on nothing (``model.LooseWire``).

    Joins no net. Its last point is always free; ``free_start`` is True when its first point
    is also on nothing (or what it started on has since gone). Both renderers draw an open
    square at each free end so a dangling wire is never mistaken for a finished connection.
    """

    id: str
    path: tuple[Point2, ...]
    free_start: bool = False
    net_class: NetClass = "signal"


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
    bold, a value dim, a net name small, a pin number smaller still. ``rail`` is a net name
    printed at a power glyph (``_rail_names``) -- drawn exactly as a net name,
    and a kind of its own because it names a glyph rather than a run, which is what every
    rule about where a net name sits relative to its wire is written about.
    """

    text: str
    at: Point2
    kind: Literal["ref", "value", "net", "pin", "rail"]
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
    #: A net touching a symbol with at least this many pins is said by NAME at each of its
    #: pins instead of being wired through the channels: a chip's every net run as a wire
    #: round it fills the sheet with a bus nobody can follow. 0 wires everything.
    name_nets_at: int = 12


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
    #: The name of each net drawn as a wire that ``labels`` does not name, with the net it
    #: belongs to: placed like the rest, and drawn by the panel only while that net is lit
    #: (``_worth_naming``). Never printed: the exports read ``labels`` alone.
    quiet_names: tuple[tuple[NetId, Label], ...] = ()
    #: The ports somebody put on a hand-drawn sheet (``SheetPort``), each drawn as a rail or
    #: a net's name in ``rails`` and ``labels`` like any other; this is where a click finds
    #: one. Empty on the sheet drawn for you.
    ports: tuple[PlacedPort, ...] = ()
    #: Wires drawn with an end on nothing (``LooseWire``). Empty on the sheet drawn for you.
    free_wires: tuple[FreeWire, ...] = ()
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

#: How far a glyph's bars reach into the box the layout cleared for them, across the stub
#: and along it alike: the ground's last bar sits at this much of the depth, and every bar
#: is at most this much of the half-width. A bar reaching the box's edge ends a tenth of a
#: grid from whatever runs in the next lane, and reads as touching it.
RAIL_BAR_REACH = 0.7


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


#: What a drawn wire's search pays, in grid steps. A step is one and a corner is
#: ``ROUTE_BEND_COST`` more, so of two routes as long the one with fewer corners wins: the
#: shortest L or Z that clears the symbols, wherever there is one. Crossing another net
#: square on costs ``ROUTE_CROSSING_COST`` -- it is what a crossing is and the sheet draws
#: no dot there, but a sheet with fewer reads more easily -- and each step within one grid
#: of another net's parallel run costs ``ROUTE_BESIDE_COST``, because lines packed side by
#: side read as one bundle and the eye loses which is which.
#:
#: Chosen on the NE555 a new user wires pin to pin, rendered at several settings: a
#: crossing at 1 left 31 crossings, at 6 it sent wires round the outside to save one, and
#: at 4 with a beside cost of 1 every run kept a grid clear of the next.
ROUTE_BEND_COST = 2.0
ROUTE_CROSSING_COST = 4.0
ROUTE_BESIDE_COST = 1.0
#: What the search keeps off while there is any other way, given up in this order and
#: only where no route exists without giving it up (``route_sheet_wire``):
#:
#: 1. a part's reference or value, and the grid point in front of another pin, where that
#:    pin's own wire has to leave -- a wire through either is clutter;
#: 2. another net's line, run along (two nets on one line) or met at a corner or an end (a
#:    T) -- either reads as a JOIN that is not there, so it is the last thing given up.
#:
#: Given up, each costs this much a time, so the route has as few as it can.
ROUTE_CLUTTER_COST = 4.0
ROUTE_OVERLAP_COST = 12.0
#: How far past the symbols the search may go, in grid steps, and how much it may look at
#: before it gives up and the wire is drawn as it always was.
ROUTE_MARGIN_STEPS = 8
ROUTE_MAX_VISITS = 40_000
#: A reference or value keeps this much of the sheet clear on the side of its point it
#: is printed on, a grid deep and this many grids wide a character: the panel's smallest
#: text at the zoom a fitted sheet opens at.
ROUTE_TEXT_GRIDS_PER_CHAR = 0.6

_STEP: dict[str, tuple[int, int]] = {
    "left": (-1, 0),
    "right": (1, 0),
    "top": (0, -1),
    "bottom": (0, 1),
}
_DIRECTIONS: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))

type Cell = tuple[int, int]


def _cell(point: Point2) -> Cell:
    return (round(point.x / GRID_MM), round(point.y / GRID_MM))


def _axis(step: tuple[int, int]) -> str:
    return "h" if step[1] == 0 else "v"


@dataclass(slots=True)
class _Sheet:
    """What a drawn wire's search keeps out of, a grid point at a time.

    ``other`` is every other net's lines (the axes they run on through a point) and
    ``nodes`` their corners and ends; ``own`` is the lines of the nets the new wire joins,
    which it may share. ``clutter`` is the points a reference or a value is printed over
    and the point in front of every pin but the wire's own two.

    ``level`` is how much has been given up (``ROUTE_CLUTTER_COST``): 0 nothing, 1 the
    clutter, 2 another net's line as well.
    """

    blocked: set[Cell]
    other: dict[Cell, set[str]]
    nodes: set[Cell]
    own: dict[Cell, set[str]]
    clutter: set[Cell]
    level: int = 0

    def through(self, at: Cell, step: tuple[int, int]) -> float | None:
        """The price of the wire running straight through ``at`` on ``step``'s axis, or
        None where that is not done at this level."""
        axis = _axis(step)
        price = 0.0
        if axis in self.other.get(at, ()) or at in self.nodes:
            if self.level < 2:
                return None
            price += ROUTE_OVERLAP_COST
        elif at in self.other:
            price += ROUTE_CROSSING_COST
        if at in self.clutter:
            if self.level < 1:
                return None
            price += ROUTE_CLUTTER_COST
        across = (step[1], step[0])
        for side in (1, -1):
            beside = (at[0] + side * across[0], at[1] + side * across[1])
            if axis in self.other.get(beside, ()):
                price += ROUTE_BESIDE_COST
        return price

    def corner(self, at: Cell) -> float | None:
        """The price of the wire turning at ``at``: a corner on another net's line is a T."""
        if at in self.other or at in self.nodes:
            return None if self.level < 2 else ROUTE_OVERLAP_COST
        return 0.0


def route_sheet_wire(
    drawing: SchematicDrawing, a: tuple[str, str], b: tuple[str, str]
) -> tuple[Point2, ...] | None:
    """A wire from pin ``a`` to pin ``b`` that crosses no symbol, as an orthogonal path in
    sheet millimetres from one pin to the other -- or None when there is none to find (a
    pin that is not on the sheet, or a sheet walled shut) and the caller draws its elbow.

    A WIRE DRAWN THROUGH A SYMBOL READS AS A SHORT. The wire tool drew two segments
    turning once, whatever was in the way, so a 555 blinker wired pin to pin had its lines
    running across R1, R2, C1 and J1. This searches the sheet's grid instead: out of each
    pin the way its lead points, round every symbol's box (edges included, so no line runs
    along the leads of another pin), the shortest it can with as few corners.

    A WIRE LAID ON ANOTHER NET'S LINE READS AS A JOIN, and so does one meeting it at a
    corner. The first version only priced running along another net's wire, and padded
    every box by a grid all round, which left one free track between symbols the layout
    had put three apart: the NE555 wired pin to pin had two nets on one line in nine
    places and its wires round the outside. Neither join is drawn now while any route
    exists without it, and the search gives things up in the order ``ROUTE_CLUTTER_COST``
    lists only where it has to.
    """
    pins: dict[tuple[str, str], tuple[Point2, str]] = {}
    for symbol in drawing.symbols:
        for pin in symbol.pins:
            pins[(symbol.ref, pin.number)] = (
                Point2(symbol.at.x + pin.at.x, symbol.at.y + pin.at.y),
                pin.side,
            )
    if a not in pins or b not in pins or a == b:
        return None
    (start, start_side), (end, end_side) = pins[a], pins[b]

    blocked: set[Cell] = set()
    lo_x = lo_y = math.inf
    hi_x = hi_y = -math.inf
    for symbol in drawing.symbols:
        # The box's own grid points, edges included, and no more.
        x0 = math.floor(symbol.at.x / GRID_MM + 1e-9)
        y0 = math.floor(symbol.at.y / GRID_MM + 1e-9)
        x1 = math.ceil((symbol.at.x + symbol.width) / GRID_MM - 1e-9)
        y1 = math.ceil((symbol.at.y + symbol.height) / GRID_MM - 1e-9)
        blocked.update((x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
        lo_x, lo_y, hi_x, hi_y = min(lo_x, x0), min(lo_y, y0), max(hi_x, x1), max(hi_y, y1)
    # Out of each pin the way its lead points, as far as it takes to clear its own box.
    leave = _clear_of(_cell(start), _STEP[start_side], blocked)
    arrive = _clear_of(_cell(end), _STEP[end_side], blocked)
    if leave is None or arrive is None:
        return None
    first, out = leave
    last, back = arrive
    bounds = (
        int(lo_x) - ROUTE_MARGIN_STEPS,
        int(lo_y) - ROUTE_MARGIN_STEPS,
        int(hi_x) + ROUTE_MARGIN_STEPS,
        int(hi_y) + ROUTE_MARGIN_STEPS,
    )
    sheet = _sheet_for(drawing, (start, end), blocked, pins, (a, b))

    leaving = _DIRECTIONS.index(_STEP[start_side])
    arriving = _DIRECTIONS.index((-_STEP[end_side][0], -_STEP[end_side][1]))
    found = None
    for level in (0, 1, 2):
        sheet.level = level
        # The stubs out of the two pins are not the search's to choose, but they are held
        # to the same rules: a stub on another net's line is a join as well.
        stubs = [sheet.through(c, _STEP[start_side]) for c in out[:-1]] + [
            sheet.through(c, _STEP[end_side]) for c in back[:-1]
        ]
        if any(price is None for price in stubs):
            continue
        found = _search(first, last, leaving, arriving, sheet, bounds)
        if found is not None:
            break
    if found is None:
        return None
    grid = [_cell(start), *out, *found, *reversed(back), _cell(end)]
    points = [Point2(x * GRID_MM, y * GRID_MM) for x, y in grid]
    # A pin sitting on a half-grid (a switch's legs) differs from its rounded cell on the
    # cross axis. Keep the exit and arrival runs strictly orthogonal by jogging at the first
    # clear column/row instead of bending the last segment diagonally into the pin.
    if len(points) >= 2:
        if start_side in ("left", "right") and abs(points[1].y - start.y) > 1e-6:
            points = [start, Point2(points[1].x, start.y), *points[1:]]
        elif start_side in ("top", "bottom") and abs(points[1].x - start.x) > 1e-6:
            points = [start, Point2(start.x, points[1].y), *points[1:]]
        else:
            points[0] = start
        if end_side in ("left", "right") and abs(points[-2].y - end.y) > 1e-6:
            points = [*points[:-1], Point2(points[-2].x, end.y), end]
        elif end_side in ("top", "bottom") and abs(points[-2].x - end.x) > 1e-6:
            points = [*points[:-1], Point2(end.x, points[-2].y), end]
        else:
            points[-1] = end
    else:
        points[0], points[-1] = start, end
    return _aligned(_corners_only(_tidy(points)))


def _sheet_for(
    drawing: SchematicDrawing,
    ends: tuple[Point2, Point2],
    blocked: set[Cell],
    pins: dict[tuple[str, str], tuple[Point2, str]],
    wired: tuple[tuple[str, str], tuple[str, str]],
) -> _Sheet:
    """Everything already on the sheet, sorted into what the new wire may share and what
    it keeps off.

    A pin carries no net on the sheet, so the new wire's nets are the ones whose lines END
    at one of its two pins -- a drawn wire, a name's stub or a rail's. A pin with nothing
    drawn at it yet adds no net, and then every line is somebody else's, which only makes
    the search keep further off.
    """

    def at_an_end(point: Point2) -> bool:
        return any(abs(point.x - e.x) < 1e-6 and abs(point.y - e.y) < 1e-6 for e in ends)

    lines: list[tuple[NetId, tuple[Point2, ...]]] = []
    for wire in drawing.wires:
        lines.append((wire.net_id, wire.path))
    for rail in drawing.rails:
        lines.append((rail.net_id, rail.path))
        lines.extend((rail.net_id, bar) for bar in rail_glyph_bars(rail))
    own_nets = {
        net for net, path in lines if path and (at_an_end(path[0]) or at_an_end(path[-1]))
    }
    other: dict[Cell, set[str]] = defaultdict(set)
    own: dict[Cell, set[str]] = defaultdict(set)
    nodes: set[Cell] = set()
    for net, path in lines:
        into = own if net in own_nets else other
        for p, q in itertools.pairwise(path):
            (px, py), (qx, qy) = _cell(p), _cell(q)
            if (px, py) == (qx, qy):
                continue
            axis = "h" if py == qy else "v"
            for step in range(max(abs(qx - px), abs(qy - py)) + 1):
                sx = px + (step if qx > px else -step if qx < px else 0)
                sy = py + (step if qy > py else -step if qy < py else 0)
                into[(sx, sy)].add(axis)
        if net not in own_nets:
            nodes.update(_cell(point) for point in _bends_and_ends(path))
    clutter = _text_cells(drawing)
    for key, (at, side) in pins.items():
        if key in wired:
            continue
        door = _clear_of(_cell(at), _STEP[side], blocked)
        if door is not None:
            clutter.add(door[0])
    return _Sheet(blocked=blocked, other=dict(other), nodes=nodes, own=dict(own), clutter=clutter)


def _text_cells(drawing: SchematicDrawing) -> set[Cell]:
    """The grid points a part's reference, value, or supply name is printed over.

    A reference or supply name prints above its point and a value below it (``viewsch``'s
    alignment), a grid deep and ``ROUTE_TEXT_GRIDS_PER_CHAR`` a character wide, from its
    anchor.
    """
    cells: set[Cell] = set()
    for label in drawing.labels:
        if label.kind not in ("ref", "value", "rail"):
            continue
        x, y = label.at.x / GRID_MM, label.at.y / GRID_MM
        width = len(label.text) * ROUTE_TEXT_GRIDS_PER_CHAR
        left = {"left": x, "centre": x - width / 2, "right": x - width}[label.anchor]
        top, bottom = (y - 1.0, y) if label.kind in ("ref", "rail") else (y, y + 1.0)
        for cx in range(math.ceil(left - 1e-9), math.floor(left + width + 1e-9) + 1):
            for cy in range(math.ceil(top - 1e-9), math.floor(bottom + 1e-9) + 1):
                cells.add((cx, cy))
    return cells


def _bends_and_ends(path: tuple[Point2, ...]) -> list[Point2]:
    """A path's two ends and every point where it turns."""
    if not path:
        return []
    kept = [path[0], path[-1]]
    for before, at, after in zip(path, path[1:], path[2:], strict=False):
        straight = (abs(before.x - at.x) < 1e-6 and abs(at.x - after.x) < 1e-6) or (
            abs(before.y - at.y) < 1e-6 and abs(at.y - after.y) < 1e-6
        )
        if not straight:
            kept.append(at)
    return kept


def _aligned(points: tuple[Point2, ...]) -> tuple[Point2, ...]:
    """Each corner on exactly the line of the point before it, and the last corner on the
    end's: a grid point and a pin's own coordinate differ in the last bit, and a wire that
    is orthogonal to the eye has to be orthogonal to ``==`` as well."""
    out = list(points)
    for index in range(1, len(out) - 1):
        a, b = out[index - 1], out[index]
        out[index] = Point2(b.x, a.y) if abs(a.y - b.y) < 1e-6 else Point2(a.x, b.y)
    if len(out) >= 3:
        b, end = out[-2], out[-1]
        out[-2] = Point2(b.x, end.y) if abs(b.y - end.y) < 1e-6 else Point2(end.x, b.y)
    return tuple(out)


def _corners_only(points: Sequence[Point2]) -> tuple[Point2, ...]:
    """The path's ends and its corners: a point on a straight run between two others says
    nothing, and a stored wire of one step per grid point would be a wire nobody can edit."""
    kept: list[Point2] = []
    for point in points:
        if len(kept) >= 2:
            a, b = kept[-2], kept[-1]
            if (abs(a.x - b.x) < 1e-9 and abs(b.x - point.x) < 1e-9) or (
                abs(a.y - b.y) < 1e-9 and abs(b.y - point.y) < 1e-9
            ):
                kept[-1] = point
                continue
        kept.append(point)
    return tuple(kept)


def _clear_of(
    at: Cell, step: tuple[int, int], blocked: set[Cell]
) -> tuple[Cell, list[Cell]] | None:
    """The first grid point out of a pin, the way its lead points, that is clear of every
    box, and the points on the way there (that point last)."""
    x, y = at
    passed: list[Cell] = []
    for _ in range(64):
        x, y = x + step[0], y + step[1]
        passed.append((x, y))
        if (x, y) not in blocked:
            return (x, y), passed
    return None


def _search(
    start: Cell,
    goal: Cell,
    leaving: int,
    arriving: int,
    sheet: _Sheet,
    bounds: tuple[int, int, int, int],
) -> list[Cell] | None:
    """A* over the grid with a corner cost: the points from ``start`` to ``goal``, both
    included, or None. The wire is already moving ``leaving`` at ``start`` (out of its pin)
    and has to be moving ``arriving`` at ``goal`` (into the other), so a turn at either is
    a corner like any other."""
    lo_x, lo_y, hi_x, hi_y = bounds
    blocked = sheet.blocked - {start, goal}

    def guess(x: int, y: int) -> float:
        return abs(goal[0] - x) + abs(goal[1] - y)

    begin = sheet.through(start, _DIRECTIONS[leaving])
    if begin is None:
        return None
    if start == goal:
        return [start] if leaving == arriving else None
    # (estimate, cost, tie, point, direction index)
    frontier: list[tuple[float, float, int, Cell, int]] = [
        (begin + guess(*start), begin, 0, start, leaving)
    ]
    best: dict[tuple[Cell, int], float] = {(start, leaving): begin}
    came: dict[tuple[Cell, int], tuple[Cell, int] | None] = {(start, leaving): None}
    tie = 0
    visits = 0
    while frontier:
        _estimate, cost, _tie, point, heading = heapq.heappop(frontier)
        if cost > best.get((point, heading), math.inf):
            continue
        if point == goal:
            path: list[Cell] = []
            state: tuple[Cell, int] | None = (point, heading)
            while state is not None:
                path.append(state[0])
                state = came[state]
            return path[::-1]
        visits += 1
        if visits > ROUTE_MAX_VISITS:
            return None
        for index, (dx, dy) in enumerate(_DIRECTIONS):
            if (dx, dy) == (-_DIRECTIONS[heading][0], -_DIRECTIONS[heading][1]):
                continue
            nxt = (point[0] + dx, point[1] + dy)
            if nxt in blocked or not (lo_x <= nxt[0] <= hi_x and lo_y <= nxt[1] <= hi_y):
                continue
            on = sheet.through(nxt, (dx, dy))
            if on is None:
                continue
            step_cost = 1.0 + on
            if index != heading:
                turn = sheet.corner(point)
                if turn is None:
                    continue
                step_cost += ROUTE_BEND_COST + turn
            moving = index
            if nxt == goal and index != arriving:
                # The goal is where the wire turns into its pin, unless it runs straight in.
                if (dx, dy) == (-_DIRECTIONS[arriving][0], -_DIRECTIONS[arriving][1]):
                    continue
                turn = sheet.corner(nxt)
                if turn is None:
                    continue
                step_cost += ROUTE_BEND_COST + turn
                moving = arriving
            total = cost + step_cost
            if total < best.get((nxt, moving), math.inf):
                best[(nxt, moving)] = total
                came[(nxt, moving)] = (point, heading)
                tie += 1
                heapq.heappush(frontier, (total + guess(*nxt), total, tie, nxt, moving))
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


def rail_glyph_box(rail: Rail) -> tuple[Mm, Mm, Mm, Mm]:
    """The box the layout clears for a rail's glyph: ``RAIL_GLYPH_MM`` either side of the
    stub and ``RAIL_GLYPH_DEPTH_MM`` past the anchor, the way the glyph points. The bars are
    drawn inside it (``rail_glyph_bars``); a name placed on the sheet keeps out of all of it,
    not just off the bars -- clear of the bars by a fraction of a millimetre, "OUT" on the
    NE555 read as written on U1's ground."""
    (along_x, along_y), (across_x, across_y) = _rail_axes(rail)
    corners = [
        (
            rail.at.x + along_x * RAIL_GLYPH_DEPTH_MM * deep + across_x * RAIL_GLYPH_MM * side,
            rail.at.y + along_y * RAIL_GLYPH_DEPTH_MM * deep + across_y * RAIL_GLYPH_MM * side,
        )
        for deep in (0.0, 1.0)
        for side in (-1.0, 1.0)
    ]
    return (
        min(x for x, _ in corners),
        min(y for _, y in corners),
        max(x for x, _ in corners),
        max(y for _, y in corners),
    )


def _rail_axes(rail: Rail) -> tuple[tuple[float, float], tuple[float, float]]:
    """The unit step the glyph points along, and the one across it."""
    return {"down": (0.0, 1.0), "up": (0.0, -1.0)}[rail.direction], (1.0, 0.0)


def rail_glyph_bars(rail: Rail) -> tuple[tuple[Point2, Point2], ...]:
    """The bars to draw at ``rail.at``: one for power, three shrinking ones for ground.

    ONE FACT, TWO RENDERERS. ``ui/viewsch.py`` paints these on screen and
    ``schematic_export.py`` writes them into an SVG that becomes the printed sheet. A glyph
    drawn one way in the panel and another on paper would be two answers to "which rail is
    this", which is the one question the glyph exists to answer.

    The bars stay inside the box the LAYOUT cleared -- ``RAIL_GLYPH_MM`` across the stub and
    ``RAIL_GLYPH_DEPTH_MM`` along it -- because that box is the only reason no wire is lying
    where they go; ``test_nothing_is_drawn_through_a_rail_glyph`` measures the layout half of
    that bargain. They use ``RAIL_BAR_REACH`` of the box rather than all of it, ACROSS the
    stub as well as along it: the next lane is one track pitch away and a bar reaching for it
    reads as touching. Across was the half left out -- a bar the box's whole width ended a
    tenth of a grid from the wire in the next vertical track, on every sheet with a rail, and
    J1's +V on the NE555 read as joined to the net beside it.

    A ground points down and a supply up, whichever way its pin does (``Rail``).
    """
    (along_x, along_y), (across_x, across_y) = _rail_axes(rail)
    reach = RAIL_GLYPH_MM * RAIL_BAR_REACH
    bars = ((1.0, 0.0),) if rail.net_class == "power" else _GROUND_BARS
    out = []
    for shrink, step in bars:
        centre_x = rail.at.x + along_x * RAIL_GLYPH_DEPTH_MM * step
        centre_y = rail.at.y + along_y * RAIL_GLYPH_DEPTH_MM * step
        half_x, half_y = across_x * reach * shrink, across_y * reach * shrink
        out.append(
            (
                Point2(x=centre_x - half_x, y=centre_y - half_y),
                Point2(x=centre_x + half_x, y=centre_y + half_y),
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Symbols, turned and flipped
# ---------------------------------------------------------------------------
#
# What each symbol's body looks like is ``schsymbols.py``. How a body is turned and
# flipped onto the sheet is here, beside the layout that places it.

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


def _orient_body(body: SymbolBody, rotation: Rotation, mirrored: bool) -> SymbolBody:
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
    return SymbolBody(
        shapes=shapes,
        pins=pins,
        width=height if turned_quarter else width,
        height=width if turned_quarter else height,
        names_inside=body.names_inside,
    )


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
    body: SymbolBody
    unplaced: bool
    undefined: bool
    col: int = 0
    row: int = 0
    x: Mm = 0.0
    y: Mm = 0.0

    def anchor_of(self, pin: SymbolPin) -> Point2:
        return Point2(x=self.x + pin.at.x, y=self.y + pin.at.y)


def _named_stub(name: str, side: PinSide) -> Mm:
    """How far a pin's stub runs when its net is said by name: under the whole name, when
    the name runs along the stub; a plain stub when the pin points up or down."""
    if side in ("top", "bottom"):
        return LABEL_STUB_MM
    return max(LABEL_STUB_MM, _text_width(name, NET_LABEL_MM) + 2 * NET_LABEL_INSET_MM)


def _said_at_pin(net: Net, anchor: Point2, side: PinSide) -> tuple[Wire, Label]:
    """A net said by NAME at a pin: a stub out of the pin, and the name on it.

    ONE way, for both kinds of sheet. The derived sheet says a chip's nets this way
    (``SchematicOptions.name_nets_at``) and the hand-drawn one says every net nobody drew a
    wire for, and freezing a sheet turns the first into the second -- so a name that sat
    differently on each would move under the user's hand on the first nudge. Beside a pin
    that points sideways the name runs along the stub, above it, starting by the pin, as a
    net name sits over every run on the sheet; the stub runs under the whole of it. Beside
    one that points up or down the name goes past the stub's end.
    """
    dx, dy = PIN_DIRECTION[side]
    stub = _named_stub(net.name, side)
    end = _p(anchor.x + dx * stub, anchor.y + dy * stub)
    wire = Wire(net_id=net.id, net_name=net.name, net_class=net.net_class, path=(anchor, end))
    if dy == 0:
        at = _p(anchor.x + dx * NET_LABEL_INSET_MM, anchor.y - NET_LABEL_CLEARANCE_MM)
    elif dy < 0:
        at = _p(end.x, end.y - NET_LABEL_CLEARANCE_MM)
    else:
        at = _p(end.x, end.y + NET_LABEL_CLEARANCE_MM + NET_LABEL_MM)
    anchor_side: Literal["left", "right", "centre"] = (
        "left" if dx > 0 else "right" if dx < 0 else "centre"
    )
    return wire, Label(text=net.name, at=at, kind="net", anchor=anchor_side)


def _up_to_grid(length: Mm) -> Mm:
    """``length`` made a whole number of grid steps, never shorter."""
    return math.ceil(length / GRID_MM - 1e-9) * GRID_MM


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
    # Every board's: the sheet is the design's, and a part on the second board is placed.
    placed_by_ref = {component.ref: component for component in every_component(doc)}
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
                PinSpec(number=pin.number, name=pin_name_of(owner, pin))
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
            # Roles that do not cover the package's pins exactly: the same line again, and
            # ERC's ``pin-roles-incomplete`` says it in the same words.
            misfit = pin_roles_misfit(
                owner.pin_roles if owner else (), (pin.number for pin in footprint.pins)
            )
            if misfit is not None:
                notes.append(f"{ref}: {roles_misfit_phrase(misfit)}, drawn as a numbered box")
            elif owner is not None and owner.pin_roles:
                # Roles for every pin and no other: what each pin does goes with its name,
                # and an IC or a module is drawn as the functional symbol they describe
                # (``schsymbols.functional_ic_body``). Stored since pinRoles and never handed
                # on, so every part that had them was still drawn as a numbered box.
                roles = dict(owner.pin_roles)
                specs = tuple(
                    dataclasses.replace(spec, role=roles[spec.number]) for spec in specs
                )
        else:
            # No footprint to ask, so the netlist is the only account of what pins exist.
            specs = tuple(
                PinSpec(number=number, name=None)
                for number in sorted(pins_named[ref], key=_pin_sort_key)
            )
        if not specs:
            specs = (PinSpec(number="1", name=None),)
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
            body=BUILDERS[kind](specs, footprint),
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
    to the thing it names.

    THEN BELOW THE WIRE, THEN WHEREVER FEWEST WIRES CROSS IT. It used to go straight back
    to the left-hand end when the band above was busy all the way along, and the left-hand
    end of a trunk is where the branches down to its pins leave it -- the busiest place on
    the run -- so eleven names on the fixtures sat with a wire through them. Below the wire
    is taken only with a clearance's worth of nothing under the text as well: a name with
    another net's run just beneath it reads as that run's name, and one sitting on a rail
    glyph's bar reads as underlined -- both were what the first version of this did. If
    neither band has room, the name stays ABOVE its wire where the fewest wires cross it,
    the left-most among equals.

    Deterministic by construction. The candidates are generated in one fixed order and the
    first best one wins, so the same document gives the same sheet -- which is what the
    golden dumps need and what stops the sheet rearranging itself between runs.
    """
    left, right = span
    above = wire_y - NET_LABEL_CLEARANCE_MM
    below = wire_y + NET_LABEL_CLEARANCE_MM + NET_LABEL_MM
    start = left + NET_LABEL_INSET_MM
    width = len(text) * NET_LABEL_MM * NET_LABEL_ADVANCE
    step = GRID_MM / 2
    positions = [start]
    while positions[-1] + step + width <= right:
        positions.append(positions[-1] + step)
    for x in positions:
        if _box_is_clear(_label_box(text, x, above), obstacles):
            return Point2(x=x, y=above)
    for x in positions:
        x0, y0, x1, y1 = _label_box(text, x, below)
        if _box_is_clear((x0, y0, x1, y1 + NET_LABEL_CLEARANCE_MM), obstacles):
            return Point2(x=x, y=below)
    best = min(positions, key=lambda x: _crossings(_label_box(text, x, above), obstacles))
    return Point2(x=best, y=above)


#: The symbols where a circuit leaves the board: what is wired to one of these is a name
#: somebody outside the board -- the cable, the panel, the next board -- goes by.
_WHERE_THE_BOARD_ENDS: frozenset[SymbolKind] = frozenset({"connector", "jack", "battery"})


def _worth_naming(net_pins: Sequence[tuple[str, SymbolPin]], symbols: Mapping[str, _Placed]) -> bool:
    """Whether a net drawn as a wire has its name printed over it.

    ONLY WHERE THE NAME SAYS SOMETHING THE WIRE DOES NOT. A wire already says which pins
    are joined; its name adds something only where the net leaves the board, at a header,
    a terminal, a jack or a part off the board, because there the name is what the cable
    and the other end are called. Every other wired net was named over its longest run
    too, and a sheet that names every wire reads nothing like KiCad's, where a net carries
    a label only where somebody put one: 39 names on atmega328-relay. A name
    held back is not lost: the panel prints it while its net is lit (``quiet_names``), and a
    net said by name at its pins is said there as before, because there the name IS the
    connection.
    """
    for ref, _ in net_pins:
        placed = symbols.get(ref)
        if placed is None:
            continue
        if placed.kind in _WHERE_THE_BOARD_ENDS:
            return True
        if placed.footprint_id is not None and placed.footprint_id.startswith("wire-"):
            return True
    return False


def _name_nets(
    nets: Sequence[Net],
    runs_of: Sequence[Wire],
    obstacles: list[tuple[Point2, Point2]],
    worth: Callable[[Net], bool] = lambda net: True,
) -> tuple[list[Label], list[tuple[NetId, Label]]]:
    """Each net's name, once, over its longest level run -- ONE RULE FOR BOTH KINDS OF SHEET.

    The derived sheet used to name a net over its trunk and the hand-drawn one over the
    longest wire somebody drew, with different things in the way of each, so the first click
    on a sheet froze it and moved names the user had not touched: 13 on four of the examples.
    Now both read the same thing off the drawing. A run is every level segment of the net's
    wires at one height that touch or overlap, merged -- the hand-drawn sheet holds a trunk
    as the pieces of the pin-to-pin wires laid along it, the derived one as one segment --
    and the longest wins, the highest and then the left-most among equals. The name goes on
    it by ``_net_label_at``, in the order ``nets`` gives (the netlist's), and each name placed
    is in the way of the next.

    ``runs_of`` is the wires a net may be named over: not a stub a name is said at, which
    is named already. ``obstacles`` is everything else in the way and grows by each name.

    Only a net ``worth`` naming is printed (``_worth_naming``); the rest are placed after
    all of those, by the same rule, and handed back apart as the names the panel shows
    while their net is lit. They do not grow ``obstacles``: one net is lit at a time, and
    a printed name must not move for a name nobody sees.
    """
    levels: dict[NetId, list[tuple[Mm, Mm, Mm]]] = {}
    for wire in runs_of:
        for start, end in _segments_of(wire.path):
            if abs(end.y - start.y) < 1e-9 and abs(end.x - start.x) > 1e-9:
                levels.setdefault(wire.net_id, []).append(
                    (round(start.y, 6), min(start.x, end.x), max(start.x, end.x))
                )
    def longest(net: Net) -> tuple[Mm, Mm, Mm] | None:
        merged: list[tuple[Mm, Mm, Mm]] = []
        for y, x0, x1 in sorted(levels.get(net.id, ())):
            if merged and merged[-1][0] == y and x0 <= merged[-1][2] + 1e-9:
                merged[-1] = (y, merged[-1][1], max(merged[-1][2], x1))
            else:
                merged.append((y, x0, x1))
        if not merged:
            return None
        return min(merged, key=lambda run: (-(run[2] - run[1]), run[0], run[1]))

    labels: list[Label] = []
    quiet: list[tuple[NetId, Label]] = []
    for net in nets:
        run = longest(net) if worth(net) else None
        if run is None:
            continue
        y, x0, x1 = run
        at = _net_label_at(net.name, (x0, x1), y, obstacles)
        labels.append(Label(text=net.name, at=at, kind="net", anchor="left"))
        obstacles.extend(_box_obstacle(_label_box(net.name, at.x, at.y)))
    for net in nets:
        run = None if worth(net) else longest(net)
        if run is None:
            continue
        y, x0, x1 = run
        at = _net_label_at(net.name, (x0, x1), y, obstacles)
        quiet.append((net.id, Label(text=net.name, at=at, kind="net", anchor="left")))
    return labels, quiet


def _names_in_the_way(
    wires: Sequence[Wire],
    rails: Sequence[Rail],
    part_labels: Sequence[Label],
    rail_names: Sequence[Label],
    pin_names: Sequence[Label],
) -> list[tuple[Point2, Point2]]:
    """What a net's name is kept off, on both kinds of sheet: every wire, every rail's stub
    and glyph, and every label already placed -- the parts', the supplies' and the names said
    at a pin.

    Text is in the way too. A net name used to be kept off the WIRES and nothing else, so
    three names looking for room near the same corner of an IC all found the same room and
    were printed on top of one another ("VCC", "THRESH" and "OUT" in one smudge), and a name
    could land on a part's value.
    """
    obstacles: list[tuple[Point2, Point2]] = []
    for wire in wires:
        obstacles.extend(_segments_of(wire.path))
    for rail in rails:
        obstacles.extend(_segments_of(rail.path))
        obstacles.extend(_box_obstacle(rail_glyph_box(rail)))
    for label in part_labels:
        box = _part_label_box(label)
        if box is not None:
            obstacles.extend(_box_obstacle(box))
    for label in (*rail_names, *pin_names):
        obstacles.extend(_box_obstacle(_net_name_box(label)))
    return obstacles


def _rail_names(rails: Sequence[Rail]) -> list[Label]:
    """The net's name over every power glyph.

    A power glyph is a bar on a stem and nothing else, so a sheet with a 5 V rail and a 12 V
    rail drew two identical bars, and which pin was on which supply could only be found by
    tracing the wires back to the connector -- the one question the glyph exists to answer
    (``rail_glyph_bars``). Every schematic prints the supply's name on its symbol.

    Clear of the bar by ``NET_LABEL_CLEARANCE_MM``. A stub that turned on its way out of
    the pin puts the name past the end of the bar, the way the stub went, centred on the bar:
    the glyph stands in the gap between two of a chip's rows, and a name over it would reach
    the row above (``_rail_reach`` makes the room beside it). A straight one puts it over a
    bar pointing up and under one pointing down. A ground glyph is left as it is: it already
    says GND.
    """
    labels: list[Label] = []
    for rail in rails:
        if rail.net_class != "power":
            continue
        x, y = rail.at.x, rail.at.y
        anchor: Literal["left", "centre", "right"] = "centre"
        turned = [q.x - p.x for p, q in itertools.pairwise(rail.path) if abs(q.x - p.x) > 1e-9]
        if turned:
            reach = RAIL_GLYPH_MM * RAIL_BAR_REACH + NET_LABEL_CLEARANCE_MM
            if turned[-1] < 0:
                at, anchor = Point2(x=x - reach, y=y + NET_LABEL_MM / 2), "right"
            else:
                at, anchor = Point2(x=x + reach, y=y + NET_LABEL_MM / 2), "left"
        elif rail.direction == "up":
            at = Point2(x=x, y=y - NET_LABEL_CLEARANCE_MM)
        else:
            at = Point2(x=x, y=y + NET_LABEL_CLEARANCE_MM + NET_LABEL_MM)
        labels.append(Label(text=rail.net_name, at=at, kind="rail", anchor=anchor))
    return labels


def _net_name_box(label: Label) -> tuple[Mm, Mm, Mm, Mm]:
    """``_label_box`` for a net name of any anchor: the text sits above its baseline."""
    width = _text_width(label.text, NET_LABEL_MM)
    left = {"left": label.at.x, "centre": label.at.x - width / 2, "right": label.at.x - width}
    return _label_box(label.text, left[label.anchor], label.at.y)


def _text_width(text: str, size: Mm) -> Mm:
    """About how wide ``text`` is at ``size`` -- the advance ``_label_box`` assumes."""
    return len(text) * size * NET_LABEL_ADVANCE


def _part_text_width(placed: _Placed, options: SchematicOptions) -> Mm:
    """The widest of a symbol's reference and value, as the layout reserves room for them."""
    widest = _text_width(placed.ref, REF_LABEL_MM)
    if options.show_values and placed.value:
        widest = max(widest, _text_width(placed.value, VALUE_LABEL_MM))
    return widest


def _part_label_box(label: Label) -> tuple[Mm, Mm, Mm, Mm] | None:
    """The rectangle a reference or a value occupies, read the way both renderers draw it:
    a reference sits ABOVE its point and a value BELOW it, anchored on ``label.anchor``.
    None for anything else -- pin text is inside or on its own symbol, where no net name goes."""
    if label.kind == "ref":
        size = REF_LABEL_MM
        top, bottom = label.at.y - size, label.at.y
    elif label.kind == "value":
        size = VALUE_LABEL_MM
        top, bottom = label.at.y, label.at.y + 1.2 * size
    else:
        return None
    width = _text_width(label.text, size)
    left = {"left": label.at.x, "centre": label.at.x - width / 2, "right": label.at.x - width}[
        label.anchor
    ]
    return left, top, left + width, bottom


def _box_obstacle(box: tuple[Mm, Mm, Mm, Mm]) -> tuple[tuple[Point2, Point2], ...]:
    """A rectangle as something ``_box_is_clear`` avoids: its diagonal.

    That test compares a segment's BOUNDING BOX with the candidate, so a diagonal stands
    for the whole rectangle, interior included -- four edges would let a shorter name sit
    inside a longer one without touching any of them.
    """
    x0, y0, x1, y1 = box
    return ((Point2(x=x0, y=y0), Point2(x=x1, y=y1)),)


def _crossings(
    box: tuple[Mm, Mm, Mm, Mm], obstacles: Sequence[tuple[Point2, Point2]]
) -> int:
    """How many of ``obstacles`` pass through ``box`` -- see ``_box_is_clear``."""
    return sum(1 for segment in obstacles if not _box_is_clear(box, (segment,)))


def build_schematic(
    doc: PerfDocument,
    lookup: FootprintLookup,
    options: SchematicOptions = DEFAULT_SCHEMATIC_OPTIONS,
) -> SchematicDrawing:
    """Draw the netlist.

    TWO KINDS OF SHEET, AND THE DOCUMENT DECIDES WHICH. With ``doc.sheet`` empty the whole
    drawing is derived: ``schlayout.arrange_sheet`` places every symbol and lays the short
    wires the way a person would, and that arrangement is then drawn exactly as a stored one
    is, so the same document always produces the same picture and freezing it moves nothing.
    With positions stored, the sheet is a
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
    ref_of.update({component.id: component.ref for component in every_component(doc)})
    placements = {
        ref_of[placement.id]: placement
        for placement in doc.sheet
        if placement.id in ref_of and ref_of[placement.id] in symbols
    }
    if placements:
        return _hand_drawn_sheet(doc, symbols, resolved, placements, options, notes, annotations)
    from .schlayout import arrange_sheet

    layout = arrange_sheet(doc, lookup, options)
    arranged_doc = dataclasses.replace(
        doc, sheet=layout.placements, sheet_wires=layout.wires
    )
    arranged_placements = {
        ref_of.get(placement.id, placement.id): placement
        for placement in layout.placements
        if ref_of.get(placement.id, placement.id) in symbols
    }
    return _hand_drawn_sheet(
        arranged_doc,
        symbols,
        resolved,
        arranged_placements,
        options,
        notes,
        annotations,
        derived=True,
    )


def wires_as_drawn(drawing: SchematicDrawing, doc: PerfDocument) -> tuple[SheetWire, ...]:
    """The wires of a DERIVED sheet as wires somebody drew: what freezing a sheet keeps.

    THE FIRST EDIT USED TO TAKE EVERY WIRE OFF THE SHEET. Moving one symbol freezes the
    sheet -- every symbol gets the position it is drawn at, so nothing jumps -- and a frozen
    sheet draws only the wires somebody drew, joining the rest by name. Nobody had drawn
    any, so the whole circuit turned into labels the moment a part was nudged, and read as
    every connection having been cut. The netlist was untouched; the drawing was not.

    So the freeze keeps the drawing too. A derived net is one trunk and a branch from each
    pin down to it, and that is exactly one wire and some T's: a wire between the two pins
    whose branches land at the trunk's ends, along both branches and the trunk between,
    and every other pin a T down its own branch onto that wire. The picture is the same
    line for line, and from then on a symbol that moves drags the ends of its wires with it
    (``_reanchored``), as it does on any sheet somebody drew.

    Rails are not wires on either kind of sheet, a one-pin net has nothing to join, and a
    pin standing on its own trunk has no branch to draw -- all three keep what the frozen
    sheet already gives them, a glyph, a stub and a name. Wires somebody already drew are
    theirs and are not returned.
    """
    anchors: dict[tuple[float, float], NetNode] = {}
    for symbol in drawing.symbols:
        for pin in symbol.pins:
            at = (symbol.at.x + pin.at.x, symbol.at.y + pin.at.y)
            anchors.setdefault(at, NetNode(component_ref=symbol.ref, pin=pin.number))
    existing = {frozenset((w.a, w.b)) for w in doc.sheet_wires}
    runs_of: dict[NetId, list[tuple[Point2, ...]]] = {}
    frozen: list[SheetWire] = []
    for wire in drawing.wires:
        if wire.ends is None:
            runs_of.setdefault(wire.net_id, []).append(wire.path)
        elif frozenset(wire.ends) not in existing:
            frozen.append(SheetWire(a=wire.ends[0], b=wire.ends[1], path=wire.path))
            existing.add(frozenset(wire.ends))

    for net in doc.nets:
        runs = runs_of.get(net.id)
        if not runs:
            continue
        nodes = set(net.nodes)
        branches: list[tuple[NetNode, tuple[Point2, ...]]] = []
        trunks: list[tuple[Point2, ...]] = []
        for path in runs:
            node = anchors.get((path[0].x, path[0].y))
            if node is not None and node in nodes:
                branches.append((node, path))
            else:
                trunks.append(path)
        if len(branches) < 2 or len(trunks) != 1:
            continue  # A stub, or not the trunk-and-branches shape this reads.
        # The two branches landing at the trunk's ends; the first of either among equals,
        # and two different pins even when every branch lands at the same place.
        first = min(range(len(branches)), key=lambda i: (branches[i][1][-1].x, i))
        last = max(
            (i for i in range(len(branches)) if i != first),
            key=lambda i: (branches[i][1][-1].x, -i),
        )
        (a, to_a), (b, to_b) = branches[first], branches[last]
        frozen.append(SheetWire(a=a, b=b, path=_tidy((*to_a, *reversed(to_b)))))
        for index, (node, path) in enumerate(branches):
            if index not in (first, last):
                frozen.append(SheetWire(a=node, b=b, path=path, tap=a))
    return tuple(frozen)


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

    # A PIN ON TWO NETS GETS ONE RAIL AT MOST. No command makes one ("duplicate-pin"); a
    # hand-edited file or an old one can, and every random fixture does. A rail is drawn at
    # its pin, out the way the pin points before it turns, and so is whatever else the pin
    # is on -- a second rail on top of the first, or a wire through its bars. So at such a
    # pin a wire or a name wins, and otherwise the first rail does; both kinds of sheet
    # decide it here, so a freeze still changes nothing, and the note says what was left out.
    wired = {
        (ref, pin.number) for item in resolved if not item.rail for ref, pin in item.pins
    }
    railed: set[tuple[str, str]] = set()
    kept: list[_ResolvedNet] = []
    for item in resolved:
        if not item.rail:
            kept.append(item)
            continue
        alone: list[tuple[str, SymbolPin]] = []
        for ref, pin in item.pins:
            key = (ref, pin.number)
            if key in wired or key in railed:
                notes.append(
                    f"{item.net.name}: {ref} pin {pin.number} is on another net too, "
                    f"so no rail is drawn there"
                )
                continue
            railed.add(key)
            alone.append((ref, pin))
        if alone:
            kept.append(dataclasses.replace(item, pins=tuple(alone)))
    return kept


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

#: How far a rail runs out of its pin, at the least: a net name's stub, so a chip's side
#: reads as one column of names and glyphs.
RAIL_STUB_MM: Mm = LABEL_STUB_MM

#: How far a rail out of a pin on a symbol's side turns, up for a supply and down for a
#: ground: half a pin pitch, so the glyph stands in the gap between its row and the next.
#: A ground's last bar then ends ``TRACK_PITCH_MM - RAIL_BAR_REACH * RAIL_GLYPH_DEPTH_MM``
#: from the next row's lead -- exactly the least gap any glyph keeps from another net's
#: line (``test_a_rail_glyph_keeps_clear_of_every_other_nets_line``).
RAIL_TURN_MM: Mm = PIN_PITCH_MM / 2


def _rail_at_pin(net: Net, anchor: Point2, side: PinSide, out: Mm = RAIL_STUB_MM) -> Rail:
    """A rail glyph on ``net`` at a pin, upright: a ground points down and a supply up.

    Out of a pin on a symbol's side, ``out`` along the pin's row and then ``RAIL_TURN_MM``
    up or down, the glyph on the end. Out of a pin pointing the glyph's own way,
    ``RAIL_STUB_MM`` straight on. Out of one pointing against it -- a ground on a top pin,
    only ever on a turned symbol -- one grid step past the stub, a grid step across, and
    back by one, so the glyph hangs beside the stub and not on it. ONE rule for both kinds
    of sheet, which is what lets the first edit freeze the sheet drawn for you without a
    rail changing shape (``Rail``); ``out`` comes from ``_rail_outs`` on both.
    """
    down = net.net_class != "power"
    turn = RAIL_TURN_MM if down else -RAIL_TURN_MM
    if side in ("left", "right"):
        step = -out if side == "left" else out
        bend = _p(anchor.x + step, anchor.y)
        path: tuple[Point2, ...] = (anchor, bend, _p(bend.x, anchor.y + turn))
    elif (side == "bottom") == down:
        path = (anchor, _p(anchor.x, anchor.y + (RAIL_STUB_MM if down else -RAIL_STUB_MM)))
    else:
        away = -1.0 if side == "top" else 1.0
        far = anchor.y + away * (RAIL_STUB_MM + GRID_MM)
        path = (
            anchor,
            _p(anchor.x, far),
            _p(anchor.x + GRID_MM, far),
            _p(anchor.x + GRID_MM, anchor.y + away * RAIL_STUB_MM),
        )
    return Rail(
        net_id=net.id,
        net_name=net.name,
        net_class=net.net_class,
        path=path,
        at=path[-1],
        direction="down" if down else "up",
    )


def _rail_outs(
    symbols: Mapping[str, _Placed],
    rails: Sequence[tuple[str, SymbolPin, NetClass]],
    said: Mapping[tuple[str, str], str],
) -> dict[tuple[str, str], Mm]:
    """How far each rail on a symbol's side runs out of its pin before it turns.

    ``RAIL_STUB_MM``, unless something else is in the gap the glyph turns into. A ground
    turns down into the gap over the next row, where that row's name is written when one
    is said at its pin (``said``, the name by pin): the ground runs out past the name. A
    supply turns up into the gap under the row above, where a ground from that row may
    already stand: the supply runs out a pin pitch past it. Both kinds of sheet ask this
    with the same pins, rails and names, so a freeze keeps every rail where it was.
    """
    def _neighbour(ref: str, pin: SymbolPin, rows: int) -> SymbolPin | None:
        for other in symbols[ref].body.pins:
            if (
                other.side == pin.side
                and abs(other.at.x - pin.at.x) < 1e-6
                and abs(other.at.y - (pin.at.y + rows * PIN_PITCH_MM)) < 1e-6
            ):
                return other
        return None

    half = RAIL_GLYPH_MM
    outs: dict[tuple[str, str], Mm] = {}
    kinds = {(ref, pin.number): net_class for ref, pin, net_class in rails}
    for ref, pin, net_class in rails:
        if pin.side not in ("left", "right") or net_class == "power":
            continue
        out = RAIL_STUB_MM
        below = _neighbour(ref, pin, 1)
        if below is not None and (ref, below.number) in said:
            name = said[(ref, below.number)]
            need = NET_LABEL_INSET_MM + _text_width(name, NET_LABEL_MM) + NET_LABEL_CLEARANCE_MM
            out = max(out, _up_to_grid(need + half))
        outs[(ref, pin.number)] = out
    for ref, pin, net_class in rails:
        if pin.side not in ("left", "right") or net_class != "power":
            continue
        out = RAIL_STUB_MM
        above = _neighbour(ref, pin, -1)
        if above is not None and kinds.get((ref, above.number), "power") != "power":
            out = outs[(ref, above.number)] + PIN_PITCH_MM
        outs[(ref, pin.number)] = out
    return outs


def _rail_reach(net: Net, out: Mm) -> Mm:
    """How far past its pin a rail on a symbol's side reaches along the pin's row: to the
    edge of the box kept for its glyph, or for a supply to the end of its name beside it."""
    reach = out + RAIL_GLYPH_MM
    if net.net_class == "power":
        reach = max(
            reach,
            out
            + RAIL_GLYPH_MM * RAIL_BAR_REACH
            + NET_LABEL_CLEARANCE_MM
            + _text_width(net.name, NET_LABEL_MM),
        )
    return reach

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
    fallback: Net | None = None
    for net in doc.nets:
        nodes = set(net.nodes)
        if wire.a in nodes and wire.b in nodes:
            if net.net_class == "signal":
                return net
            if fallback is None:
                fallback = net
    return fallback


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


_EPS = 1e-6


def _run_overlap(p: Point2, q: Point2, r: Point2, s: Point2) -> bool:
    """Whether two segments lie along one line and share more than a point of it."""
    if abs(p.y - q.y) < _EPS and abs(r.y - s.y) < _EPS and abs(p.y - r.y) < _EPS:
        lo = max(min(p.x, q.x), min(r.x, s.x))
        hi = min(max(p.x, q.x), max(r.x, s.x))
        return hi - lo > _EPS
    if abs(p.x - q.x) < _EPS and abs(r.x - s.x) < _EPS and abs(p.x - r.x) < _EPS:
        lo = max(min(p.y, q.y), min(r.y, s.y))
        hi = min(max(p.y, q.y), max(r.y, s.y))
        return hi - lo > _EPS
    return False


def _backtracks(path: Sequence[Point2]) -> bool:
    """A run that turns straight back on itself: the shape a wire takes when its end moves
    further than the first leg is long."""
    for a, b, c in itertools.zip_longest(path, path[1:], path[2:]):
        if b is None or c is None:
            break
        first_x, first_y = b.x - a.x, b.y - a.y
        then_x, then_y = c.x - b.x, c.y - b.y
        if abs(first_x * then_y - first_y * then_x) < _EPS and first_x * then_x + first_y * then_y < -_EPS:
            return True
    return False


def _overlaps_itself(path: Sequence[Point2]) -> bool:
    runs = list(itertools.pairwise(path))
    return any(
        _run_overlap(*runs[i], *runs[j])
        for i in range(len(runs))
        for j in range(i + 1, len(runs))
    )


def _through_a_body(path: Sequence[Point2], boxes: Sequence[tuple[Mm, Mm, Mm, Mm]]) -> bool:
    """Whether a run passes through the inside of a symbol's box. Running along its edge, or
    meeting it at a pin, is not through."""
    for a, b in itertools.pairwise(path):
        lo_x, hi_x, lo_y, hi_y = min(a.x, b.x), max(a.x, b.x), min(a.y, b.y), max(a.y, b.y)
        for x0, y0, x1, y1 in boxes:
            if hi_x > x0 + _EPS and lo_x < x1 - _EPS and hi_y > y0 + _EPS and lo_y < y1 - _EPS:
                return True
            # A run with no width (a straight one) inside the box on an axis is not a
            # rectangle to test, but it is through the body all the same.
            if abs(lo_y - hi_y) < _EPS and y0 + _EPS < lo_y < y1 - _EPS and hi_x > x0 + _EPS and lo_x < x1 - _EPS:
                return True
            if abs(lo_x - hi_x) < _EPS and x0 + _EPS < lo_x < x1 - _EPS and hi_y > y0 + _EPS and lo_y < y1 - _EPS:
                return True
    return False


def _on_another_nets_wire(
    path: Sequence[Point2], net_id: NetId, laid: Sequence[tuple[NetId, tuple[Point2, ...]]]
) -> bool:
    return any(
        _run_overlap(a, b, c, d)
        for other, run in laid
        if other != net_id
        for a, b in itertools.pairwise(path)
        for c, d in itertools.pairwise(run)
    )


def _spoils(
    path: Sequence[Point2],
    boxes: Sequence[tuple[Mm, Mm, Mm, Mm]],
    net_id: NetId,
    laid: Sequence[tuple[NetId, tuple[Point2, ...]]],
) -> bool:
    return (
        _backtracks(path)
        or _overlaps_itself(path)
        or _through_a_body(path, boxes)
        or _on_another_nets_wire(path, net_id, laid)
    )


def moved_end(path: Sequence[Point2], to: Point2) -> tuple[Point2, ...]:
    """The drawn path with its LAST point taken to ``to``, the run into it sliding so the
    wire stays square -- what a symbol moving does to its wires (``_reanchored``), for the
    end of one wire dragged onto another pin. Reverse a path to move its first point."""
    points = tuple(path)
    if len(points) < 2:
        return points
    return _reanchored(points, points[0], to)


def _square_tidy(points: Sequence[Point2]) -> tuple[Point2, ...]:
    """``_tidy``, and then every corner that does not turn taken out: a run that goes on in
    the same direction is one run. A point where the wire turns back on itself stays, since
    taking it out would make a run that overlaps itself into one that does not go as far."""
    out: list[Point2] = []
    for point in _tidy(points):
        if len(out) >= 2:
            before, middle = out[-2], out[-1]
            in_line = (
                abs(before.x - middle.x) < 1e-9 and abs(middle.x - point.x) < 1e-9
            ) or (abs(before.y - middle.y) < 1e-9 and abs(middle.y - point.y) < 1e-9)
            onward = (middle.x - before.x) * (point.x - middle.x) + (middle.y - before.y) * (
                point.y - middle.y
            ) > 0
            if in_line and onward:
                out[-1] = point
                continue
        out.append(point)
    return tuple(out)


def _runs_across(start: Point2, end: Point2) -> bool:
    return abs(start.y - end.y) < 1e-9


def moved_corner(path: Sequence[Point2], index: int, to: Point2) -> tuple[Point2, ...]:
    """The drawn path with its corner ``index`` dragged to ``to`` (snapped to the grid).

    THE ENDS STAY WHERE THEY ARE -- a pin, or the point a T lands on -- and every run stays
    across or down. A corner between two corners takes its neighbours' shared coordinate
    with it, so the runs either side slide rather than slant. A corner next to an end
    cannot move that end, so an elbow goes in instead, and the run out of the end keeps
    the direction it left in: a wire leaving a pin sideways still leaves it sideways.
    """
    points = list(path)
    if not 0 < index < len(points) - 1:
        return tuple(points)
    to = snap_to_grid(to)
    last = len(points) - 1
    before, here, after = points[index - 1], points[index], points[index + 1]

    def toward_end(end: Point2, corner: Point2, *, stubbed: bool) -> list[Point2]:
        """The points from the end ``end`` to the moved corner, leaving the end the way the
        run to ``corner`` left it: straight on to the elbow, or ``stubbed`` one square out
        first and round, which is the way that does not run back over itself when the
        corner went past the end's own line."""
        across = _runs_across(end, corner)
        if not stubbed:
            return [end, _p(to.x, end.y) if across else _p(end.x, to.y)]
        if across:
            out = _p(end.x + math.copysign(_STUB_MM, corner.x - end.x), end.y)
            return [end, out, _p(out.x, to.y)]
        out = _p(end.x, end.y + math.copysign(_STUB_MM, corner.y - end.y))
        return [end, out, _p(to.x, out.y)]

    def toward_corner(neighbour: Point2) -> Point2:
        # A corner between corners: it slides along with the moved one.
        return _p(neighbour.x, to.y) if _runs_across(neighbour, here) else _p(to.x, neighbour.y)

    heads = (
        [[*toward_end(before, here, stubbed=stubbed)] for stubbed in (False, True)]
        if index - 1 == 0
        else [[*points[: index - 1], toward_corner(before)]]
    )
    tails = (
        [list(reversed(toward_end(after, here, stubbed=stubbed))) for stubbed in (False, True)]
        if index + 1 == last
        else [[toward_corner(after), *points[index + 2 :]]]
    )
    candidates = [_square_tidy([*head, to, *tail]) for head in heads for tail in tails]
    return next((path for path in candidates if not _turns_back(path)), candidates[0])


def _turns_back(path: Sequence[Point2]) -> bool:
    """Whether the wire anywhere runs straight back the way it came."""
    return any(
        (b.x - a.x) * (c.x - b.x) + (b.y - a.y) * (c.y - b.y) < -1e-9
        and (
            (abs(a.x - b.x) < 1e-9 and abs(b.x - c.x) < 1e-9)
            or (abs(a.y - b.y) < 1e-9 and abs(b.y - c.y) < 1e-9)
        )
        for a, b, c in zip(path, path[1:], path[2:], strict=False)
    )


#: How much of a run stays put at an end the run is dragged away from: one grid square,
#: so the wire still leaves its pin the way the pin's lead points before it turns.
_STUB_MM: Mm = GRID_MM


def moved_run(path: Sequence[Point2], index: int, to: Point2) -> tuple[Point2, ...]:
    """The drawn path with its run ``index`` (from point ``index`` to the next) dragged
    sideways so that it passes through ``to``, snapped to the grid.

    A run slides only across itself -- along itself it would just be the same line. The
    corners at its two ends go with it, so the runs before and after grow or shrink. Where
    the run starts or ends at an END of the wire, that end stays where it is: one grid
    square of the run stays at it and turns to meet the run where it now is, so dragging
    the straight wire between two pins down makes a U rather than tearing it off them.
    """
    points = list(path)
    if not 0 <= index < len(points) - 1:
        return tuple(points)
    to = snap_to_grid(to)
    start, end = points[index], points[index + 1]
    across = _runs_across(start, end)
    if abs((to.y - start.y) if across else (to.x - start.x)) < 1e-9:
        return tuple(points)

    def shifted(point: Point2) -> Point2:
        return _p(point.x, to.y) if across else _p(to.x, point.y)

    last = len(points) - 1
    length = abs(end.x - start.x) + abs(end.y - start.y)
    fixed_ends = (index == 0) + (index + 1 == last)
    # A stub only where what is left of the run between the stubs is a square at least:
    # shorter, the two would meet and the wire would run out and straight back.
    step = _STUB_MM if length - fixed_ends * _STUB_MM >= _STUB_MM - 1e-9 else 0.0

    def stub(fixed: Point2, toward: Point2) -> list[Point2]:
        """Out of the end ``fixed`` along the run by ``step``, which may be nothing."""
        if step < 1e-9:
            return [fixed]
        ux = (toward.x - fixed.x) / length
        uy = (toward.y - fixed.y) / length
        return [fixed, _p(fixed.x + ux * step, fixed.y + uy * step)]

    head = points[:index]
    if index == 0:
        lead = stub(start, end)
        head = [*lead, shifted(lead[-1])]
    else:
        head.append(shifted(start))
    tail = points[index + 2 :]
    if index + 1 == last:
        trail = stub(end, start)
        tail = [shifted(trail[-1]), *reversed(trail)]
    else:
        tail = [shifted(end), *tail]
    return _square_tidy([*head, *tail])


def _hand_drawn_sheet(
    doc: PerfDocument,
    symbols: dict[str, _Placed],
    resolved: list[_ResolvedNet],
    placements: dict[str, SymbolPlacement],
    options: SchematicOptions,
    notes: list[str],
    annotations: tuple[Annotation, ...],
    *,
    derived: bool = False,
) -> SchematicDrawing:
    """Draw the sheet as it was arranged, and join by name whatever has no wire."""
    # -- where everything is, and which way round ---------------------------
    for ref, placed in symbols.items():
        placement = placements.get(ref)
        if placement is None:
            continue
        placed.body = _orient_body(placed.body, placement.rotation, placement.mirrored)
        placed.x, placed.y = placement.at.x, placement.at.y
    # The netlist was resolved against the bodies as they were made, unturned, and a rail or
    # a name said at a pin is put where ``resolved`` says the pin is: so each pin is read
    # again, by number, off the body as it is now turned. Without it a symbol stood upright
    # had VCC's rail start where its pin would be lying down, beside the body.
    turned = {ref: {pin.number: pin for pin in placed.body.pins} for ref, placed in symbols.items()}
    resolved = [
        dataclasses.replace(
            item,
            pins=tuple((ref, turned[ref].get(pin.number, pin)) for ref, pin in item.pins),
        )
        for item in resolved
    ]

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
    tees: list[Junction] = []
    # Pin to pin first, then each T onto the wire it lands on once that is drawn -- a T can
    # land on a T -- until a pass draws nothing more. What is left is a T whose wire is not
    # drawn (its net no longer holds both its ends); it goes to its pin instead, which is
    # still true: it joins that pin's net.
    drawn_paths: dict[frozenset[NetNode], tuple[Point2, ...]] = {}
    drawn_nets: dict[frozenset[NetNode], Net] = {}
    waiting = list(doc.sheet_wires)
    stalled = False
    provisional: SchematicDrawing | None = None
    while waiting:
        still: list[SheetWire] = []
        for wire in waiting:
            host = wire.host_pins
            host_path = drawn_paths.get(host) if host is not None else None
            if host is not None and host_path is None and not stalled:
                still.append(wire)
                continue
            net = _wire_net_of(doc, wire)
            if net is None:
                continue
            start = _pin_of(symbols, wire.a)
            if start is None:
                continue
            if host_path is not None:
                end, on_end = _laid_onto(wire.path[-1], host_path)
                if not on_end:
                    tees.append(Junction(net_id=net.id, at=end))
            else:
                pin_end = _pin_of(symbols, wire.b)
                if pin_end is None:
                    continue
                end = pin_end
                drawn_pins.add((wire.b.component_ref, wire.b.pin))
            path = _reanchored(wire.path, start, end)
            if wire.path[0] != start or wire.path[-1] != end:
                # AN END MOVED. A wire that is still clean keeps the middle it was drawn
                # with; one that backtracks, overlaps itself, runs through a symbol or lies
                # on another net's line is laid again, round the symbols, as it would be
                # drawn from scratch.
                boxes = [
                    (p.x, p.y, p.x + p.body.width, p.y + p.body.height)
                    for p in symbols.values()
                ]
                laid = [(w.net_id, w.path) for w in wires]

                if _spoils(path, boxes, net.id, laid):
                    relay = True
                    if host_path is not None:
                        # A T: across onto the wire it lands on, from the pin, at the
                        # point of that wire nearest the pin, turning once.
                        landing, _on_end = _laid_onto(start, host_path)
                        for corner in (_p(landing.x, start.y), _p(start.x, landing.y)):
                            candidate = _tidy((start, corner, landing))
                            if not _spoils(candidate, boxes, net.id, laid):
                                path = candidate
                                end = landing
                                relay = False
                                break
                        # No such turn is clear: go round the symbols to the pin the wire
                        # it lands on ends at, which is on that wire.
                        far = _pin_of(symbols, wire.b)
                        if relay and far is None:
                            relay = False
                    if relay:
                        if provisional is None:
                            provisional = _provisional_drawing(symbols, placements)
                        relaid = route_sheet_wire(
                            dataclasses.replace(provisional, wires=tuple(wires)),
                            (wire.a.component_ref, wire.a.pin),
                            (wire.b.component_ref, wire.b.pin),
                        )
                        if relaid is not None:
                            path = _tidy(relaid)
                            if host_path is not None:
                                end = path[-1]
                                if tees and tees[-1].at != end and not on_end:
                                    tees.pop()
            wires.append(
                Wire(
                    net_id=net.id,
                    net_name=net.name,
                    net_class=net.net_class,
                    path=path,
                    ends=(wire.a, wire.b),
                )
            )
            drawn_paths[frozenset((wire.a, wire.b))] = path
            drawn_nets[frozenset((wire.a, wire.b))] = net
            drawn_pins.add((wire.a.component_ref, wire.a.pin))
        if len(still) == len(waiting):
            stalled = True
        waiting = still

    # -- the ports somebody put down, and the wires to them --------------------
    rails: list[Rail] = []
    net_labels: list[Label] = []
    port_rails, port_labels, port_wires, ports = _ports_drawn(doc, symbols, drawn_pins)
    rails.extend(port_rails)
    net_labels.extend(port_labels)
    wires.extend(port_wires)
    # A net somebody named with a label is named where they put it, and nowhere else.
    labelled = {
        net.id
        for port in doc.sheet_ports
        if port.kind == "label" and (net := net_named(doc.nets, port.name)) is not None
    }

    # -- the wires with an end on nothing (LooseWire) --------------------------
    free_wires = _free_wires_drawn(doc, symbols, drawn_paths, drawn_nets, ports, tees)

    # -- and a name, or a rail glyph, on everything else ---------------------
    drawn_wires = list(wires)
    outs = _rail_outs(
        symbols,
        [
            (ref, pin, item.net.net_class)
            for item in resolved
            if item.rail
            for ref, pin in item.pins
            if (ref, pin.number) not in drawn_pins
        ],
        {
            (ref, pin.number): item.net.name
            for item in resolved
            if not item.rail and len(item.pins) > 1
            for ref, pin in item.pins
            if (ref, pin.number) not in drawn_pins
        },
    )
    for item in resolved:
        for ref, pin in item.pins:
            if (ref, pin.number) in drawn_pins:
                continue
            anchor = symbols[ref].anchor_of(pin)
            if item.rail:
                out = outs.get((ref, pin.number), RAIL_STUB_MM)
                rails.append(_rail_at_pin(item.net, anchor, pin.side, out))
                continue
            if len(item.pins) < 2:
                # One pin and nothing to join it to. Saying the name would claim a
                # connection to something; the derived sheet draws a stub here and says so
                # in the notes.
                if derived:
                    dx, dy = PIN_DIRECTION[pin.side]
                    wires.append(
                        Wire(
                            net_id=item.net.id,
                            net_name=item.net.name,
                            net_class=item.net.net_class,
                            path=(anchor, _p(anchor.x + dx * GRID_MM, anchor.y + dy * GRID_MM)),
                        )
                    )
                continue
            stub, said = _said_at_pin(item.net, anchor, pin.side)
            wires.append(stub)
            net_labels.append(said)

    # -- the name of every net somebody drew, once, over its longest run ------
    #
    # A wire says two pins are joined and not what the join is called, and the derived
    # sheet always said both: freezing it used to keep the lines and lose every name. The
    # name goes by the derived sheet's own rule, ``_name_nets``, so a freeze moves none.
    ordered = sorted(symbols.values(), key=lambda placed: _ref_sort_key(placed.ref))
    part_labels = _apply_label_offsets(_part_labels(ordered, options), placements)
    rail_names = _rail_names(rails)
    pins_of = {item.net.id: item.pins for item in resolved}
    named, quiet_names = _name_nets(
        [item.net for item in resolved if not item.rail and item.net.id not in labelled],
        drawn_wires,
        _names_in_the_way(wires, rails, part_labels, rail_names, net_labels),
        lambda net: _worth_naming(pins_of[net.id], symbols),
    )
    net_labels.extend(named)

    # -- dots where three or more ends of one net meet, and at every T ------
    junctions = tuple(sorted(
        set(_junctions_of(wires)) | set(tees), key=lambda j: (j.net_id, j.at.x, j.at.y)
    ))

    wired_pins = {(ref, pin.number) for item in resolved for ref, pin in item.pins}
    no_connects = [
        NoConnect(ref=ref, pin=pin.number, at=symbols[ref].anchor_of(pin))
        for ref in sorted(symbols, key=_ref_sort_key)
        for pin in symbols[ref].body.pins
        if (ref, pin.number) not in wired_pins
    ]

    width, height = _sheet_extent(
        ordered, wires, rails, no_connects, annotations, part_labels, free_wires
    )

    drawn = _symbols_drawn(ordered, placements, derived=derived)
    if parked:
        notes.append(
            f"{len(parked)} part(s) have no place on this sheet yet and are parked at the "
            f"right-hand edge: {', '.join(parked)}"
        )
    if free_wires:
        n_free = len(free_wires)
        notes.append(
            "1 wire on the sheet ends on nothing and joins no net"
            if n_free == 1
            else f"{n_free} wires on the sheet end on nothing and join no net"
        )
    return SchematicDrawing(
        symbols=drawn,
        wires=tuple(wires),
        rails=tuple(rails),
        junctions=junctions,
        no_connects=tuple(no_connects),
        labels=(*part_labels, *rail_names, *net_labels),
        quiet_names=tuple(quiet_names),
        ports=ports,
        free_wires=free_wires,
        annotations=annotations,
        width=width,
        height=height,
        notes=tuple(notes),
    )


def _free_wires_drawn(
    doc: PerfDocument,
    symbols: dict[str, _Placed],
    drawn_paths: Mapping[frozenset[NetNode], tuple[Point2, ...]],
    drawn_nets: Mapping[frozenset[NetNode], Net],
    ports: Sequence[PlacedPort],
    tees: list[Junction],
) -> tuple[FreeWire, ...]:
    """Every ``LooseWire`` reanchored onto whatever its first point starts on."""
    if not doc.sheet_loose_wires:
        return ()
    port_by_id = {port.id: port for port in ports}
    pin_net_class = {
        node: net.net_class for net in doc.nets for node in net.nodes
    }
    out: list[FreeWire] = []
    for loose in sorted(doc.sheet_loose_wires, key=lambda w: w.id):
        start: Point2 | None = None
        net_class: NetClass = "signal"
        if loose.pin is not None:
            start = _pin_of(symbols, loose.pin)
            net_class = pin_net_class.get(loose.pin, "signal")
        elif loose.on is not None:
            host_key = frozenset(loose.on)
            host_path = drawn_paths.get(host_key)
            if host_path is not None:
                landed, on_end = _laid_onto(loose.path[0], host_path)
                start = landed
                host_net = drawn_nets.get(host_key)
                if host_net is not None:
                    net_class = host_net.net_class
                    if not on_end:
                        tees.append(Junction(net_id=host_net.id, at=landed))
        elif loose.port is not None:
            port_obj = port_by_id.get(loose.port)
            if port_obj is not None:
                start = port_obj.at
                if port_obj.kind == "supply":
                    net_class = "power"
                elif port_obj.kind == "ground":
                    net_class = "ground"
                else:
                    net = net_named(doc.nets, port_obj.name)
                    if net is not None:
                        net_class = net.net_class
        if start is not None:
            path = _reanchored(loose.path, start, loose.path[-1])
            free_start = False
        else:
            path = loose.path
            free_start = True
        out.append(FreeWire(id=loose.id, path=path, free_start=free_start, net_class=net_class))
    return tuple(out)


def _ports_drawn(
    doc: PerfDocument,
    symbols: dict[str, _Placed],
    drawn_pins: set[tuple[str, str]],
) -> tuple[list[Rail], list[Label], list[Wire], tuple[PlacedPort, ...]]:
    """Every port on a hand-drawn sheet as the glyph or the name it is, and its wires.

    A LINK IS DRAWN ONLY WHILE ITS PIN IS ON THE NET ITS PORT NAMES, as a drawn wire is
    only while its two pins share one (``SheetWire``): the drawing never says a pin is on
    GND that the netlist does not put there. A pin a link is drawn to joins ``drawn_pins``,
    so it gets no glyph or name of its own -- two grounds on one pin read as two.

    A supply or a ground with one wire is drawn as the glyph at its pin always was, the
    wire its stem, so a glyph dragged off a pin is still the same glyph; with none or
    several, its stem is its own point and each wire runs to it.
    """
    rails: list[Rail] = []
    labels: list[Label] = []
    wires: list[Wire] = []
    placed: list[PlacedPort] = []
    for port in sorted(doc.sheet_ports, key=lambda port: port.id):
        net = net_named(doc.nets, port.name)
        net_class: NetClass = (
            "power" if port.kind == "supply"
            else "ground" if port.kind == "ground"
            else net.net_class if net is not None
            else "signal"
        )
        net_id = net.id if net is not None else ""
        paths: list[tuple[Point2, ...]] = []
        for link in port.links:
            if net is None or link.pin not in net.nodes:
                continue
            start = _pin_of(symbols, link.pin)
            if start is None:
                continue
            path = _reanchored(link.path, start, port.at)
            if port.kind != "label":
                path = _into_glyph(path, port.at, "up" if port.kind == "supply" else "down")
            paths.append(path)
            drawn_pins.add((link.pin.component_ref, link.pin.pin))
        glyph = port.kind != "label"
        stem = paths[0] if glyph and len(paths) == 1 else (port.at,)
        for path in paths:
            if path is stem:
                continue
            wires.append(Wire(net_id=net_id, net_name=port.name, net_class=net_class, path=path))
        if glyph:
            rail = Rail(
                net_id=net_id,
                net_name=port.name,
                net_class=net_class,
                path=stem,
                at=port.at,
                direction="up" if port.kind == "supply" else "down",
                port=port.id,
            )
            rails.append(rail)
            box = rail_glyph_box(rail)
        else:
            label = _port_label(port, paths)
            labels.append(label)
            box = _net_name_box(label)
        placed.append(PlacedPort(id=port.id, kind=port.kind, name=port.name, at=port.at, box=box))
    return rails, labels, wires, tuple(placed)


def port_stub(
    drawing: SchematicDrawing, kind: SheetPortKind, name: str, ref: str, number: str
) -> tuple[Point2, ...] | None:
    """The wire a port of ``kind`` put down on a pin is drawn with, from the pin to the
    port's point (the last one), or None for a pin not on the drawing.

    THE SHAPE THE SHEET ALREADY DRAWS THERE: a supply or a ground hangs off the pin as the
    glyph the sheet draws for a rail pin nothing is wired at (``_rail_at_pin``), and a name
    sits on the stub a net said at a pin has (``_said_at_pin``). Putting GND on a pin the
    sheet already showed on ground therefore changes nothing on screen but who owns it.
    """
    for symbol in drawing.symbols:
        if symbol.ref != ref:
            continue
        pin = next((pin for pin in symbol.pins if pin.number == number), None)
        if pin is None:
            return None
        anchor = _p(symbol.at.x + pin.at.x, symbol.at.y + pin.at.y)
        if kind == "label":
            dx, dy = PIN_DIRECTION[pin.side]
            stub = _named_stub(name, pin.side)
            return (anchor, _p(anchor.x + dx * stub, anchor.y + dy * stub))
        net = Net(
            id="",
            name=name,
            nodes=(),
            net_class="power" if kind == "supply" else "ground",
        )
        return _rail_at_pin(net, anchor, pin.side).path
    return None


def port_glyph(kind: SheetPortKind, name: str, at: Point2) -> Rail:
    """A supply or a ground glyph standing at ``at`` on no wire: what the port tool shows
    under the pointer before the click, drawn by the code that draws a placed one."""
    return Rail(
        net_id="",
        net_name=name,
        net_class="power" if kind == "supply" else "ground",
        path=(at,),
        at=at,
        direction="up" if kind == "supply" else "down",
    )


def _into_glyph(
    path: tuple[Point2, ...], at: Point2, direction: Literal["down", "up"]
) -> tuple[Point2, ...]:
    """A wire to a supply or a ground, ending as the glyph's stem: into ``at`` from the side
    away from the bars, below a supply's and above a ground's.

    A GLYPH IS NEVER WIRED THROUGH ITS BARS. A supply dragged under the pin it hangs from
    kept the wire it had, now arriving from above, and read as an upside-down T -- the
    glyph a ground is drawn with, on the wrong net. So the last run comes up (or down) into
    ``at`` from ``RAIL_TURN_MM`` out, the stem a glyph put on a pin is drawn with, and a
    wire in line with the bars goes round them one grid step to the side it came from.
    A wire already ending that way is left exactly as drawn.
    """
    away = 1.0 if direction == "up" else -1.0
    if len(path) < 2:
        return path
    before = path[-2]
    if abs(before.x - at.x) < _EPS and (before.y - at.y) * away > _EPS:
        return path
    foot = _p(at.x, at.y + away * RAIL_TURN_MM)
    body = list(path[:-1])
    last = body[-1]
    if (last.y - at.y) * away > _EPS:
        # Already on the open side: across under (or over) the glyph, then into it.
        tail = [_p(at.x, last.y), at]
    elif abs(last.x - at.x) >= GRID_MM - _EPS:
        # Clear of the bars: out to the stem's foot, then into it.
        tail = [_p(last.x, foot.y), foot, at]
    else:
        came = body[-2].x - at.x if len(body) > 1 else 0.0
        side = -1.0 if came < -_EPS else 1.0
        aside = at.x + side * GRID_MM
        tail = [_p(aside, last.y), _p(aside, foot.y), foot, at]
    return _unfolded([*body, *tail])


def _unfolded(points: Sequence[Point2]) -> tuple[Point2, ...]:
    """An orthogonal chain with every point that turns nowhere taken out, a run that doubles
    back on itself included: the corner it doubled back from is the one point dropped."""
    out: list[Point2] = []
    for point in _tidy(points):
        while len(out) >= 2 and (
            (abs(out[-2].x - out[-1].x) < _EPS and abs(out[-1].x - point.x) < _EPS)
            or (abs(out[-2].y - out[-1].y) < _EPS and abs(out[-1].y - point.y) < _EPS)
        ):
            out.pop()
        if not out or abs(out[-1].x - point.x) > _EPS or abs(out[-1].y - point.y) > _EPS:
            out.append(point)
    return tuple(out)


def _port_label(port: SheetPort, paths: Sequence[tuple[Point2, ...]]) -> Label:
    """A label port's name, on a flag at its point: running on the way its first wire came
    in, so it reads on from the wire as a name said at a pin does (``_said_at_pin``)."""
    leftward = False
    if paths and len(paths[0]) >= 2:
        before, end = paths[0][-2], paths[0][-1]
        leftward = end.x < before.x - 1e-9
    if leftward:
        at = _p(port.at.x - NET_LABEL_INSET_MM, port.at.y - NET_LABEL_CLEARANCE_MM)
        return Label(text=port.name, at=at, kind="net", anchor="right")
    at = _p(port.at.x + NET_LABEL_INSET_MM, port.at.y - NET_LABEL_CLEARANCE_MM)
    return Label(text=port.name, at=at, kind="net", anchor="left")


def _symbols_drawn(
    ordered: Sequence[_Placed],
    placements: dict[str, SymbolPlacement],
    *,
    derived: bool = False,
) -> tuple[Symbol, ...]:
    return tuple(
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
            positioned=False if derived else placed.ref in placements,
        )
        for placed in ordered
    )


def _provisional_drawing(
    symbols: dict[str, _Placed], placements: dict[str, SymbolPlacement]
) -> SchematicDrawing:
    """The sheet as far as ``route_sheet_wire`` needs it: the symbols where they are. The
    wires laid so far are put in by the caller."""
    ordered = sorted(symbols.values(), key=lambda placed: _ref_sort_key(placed.ref))
    return SchematicDrawing(symbols=_symbols_drawn(ordered, placements))


def _after_move(
    doc: PerfDocument,
    lookup: FootprintLookup,
    moved: Sequence[SymbolPlacement],
    frozen: Sequence[SheetWire],
) -> tuple[SchematicDrawing, dict[frozenset[NetNode], SheetWire]]:
    placed = {p.id: p for p in doc.sheet}
    old_by_id = dict(placed)
    placed.update({p.id: p for p in moved})
    # When two ends of one wire move together by the same grid shift (no rotation or mirror
    # change), carry the wire's intermediate corners by the same shift so a dragged group
    # keeps its internal wiring rigid instead of stretching each end separately.
    ref_by_id = {part.id: part.ref for part in circuit_parts(doc)}
    shifts: dict[str, tuple[Mm, Mm]] = {}
    for p in moved:
        old = old_by_id.get(p.id)
        ref = ref_by_id.get(p.id)
        if (
            old is not None
            and ref is not None
            and old.rotation == p.rotation
            and old.mirrored == p.mirrored
        ):
            dx, dy = p.at.x - old.at.x, p.at.y - old.at.y
            if abs(dx) > _EPS or abs(dy) > _EPS:
                shifts[ref] = (dx, dy)
    stored = {frozenset((w.a, w.b)): w for w in doc.sheet_wires}
    stored.update({frozenset((w.a, w.b)): w for w in frozen})
    if shifts:
        for key, wire in list(stored.items()):
            if wire.tap is not None:
                continue
            sa = shifts.get(wire.a.component_ref)
            sb = shifts.get(wire.b.component_ref)
            if sa is not None and sb is not None and abs(sa[0] - sb[0]) < _EPS and abs(sa[1] - sb[1]) < _EPS:
                dx, dy = sa
                stored[key] = dataclasses.replace(
                    wire, path=tuple(_p(pt.x + dx, pt.y + dy) for pt in wire.path)
                )
    after = dataclasses.replace(
        doc, sheet=tuple(placed.values()), sheet_wires=tuple(stored.values())
    )
    return build_schematic(after, lookup), stored


def drawing_after_move(
    doc: PerfDocument,
    lookup: FootprintLookup,
    moved: Sequence[SymbolPlacement],
    frozen: Sequence[SheetWire] = (),
) -> SchematicDrawing:
    """The sheet as it would be drawn with ``moved`` in place: what a drag shows while it
    is still going, from the same code that decides what the drop saves."""
    return _after_move(doc, lookup, moved, frozen)[0]


def wires_after_move(
    doc: PerfDocument,
    lookup: FootprintLookup,
    moved: Sequence[SymbolPlacement],
    frozen: Sequence[SheetWire] = (),
) -> tuple[SheetWire, ...]:
    """The wires a move of ``moved`` leaves, as the sheet draws them: what the window puts
    in the move's own ``wires`` so the saved file is what the screen shows.

    A symbol that moves takes its wires with it, and a wire it drags into a backtrack, a
    line over itself, a symbol or another net's wire is laid again
    (``_hand_drawn_sheet``). That is done in drawing, and this reads the answer off it:
    every wire (including T-branches) whose path the move changed. ``frozen`` is the derived
    sheet's wires when this move is the one freezing it (``wires_as_drawn``), which then
    come back too, changed or not -- they are not stored yet.
    """
    drawing, _stored = _after_move(doc, lookup, moved, frozen)
    original = {frozenset((w.a, w.b)): w for w in doc.sheet_wires}
    original.update({frozenset((w.a, w.b)): w for w in frozen})
    out: dict[frozenset[NetNode], SheetWire] = {
        frozenset((w.a, w.b)): w for w in frozen
    }
    for wire in drawing.wires:
        if wire.ends is None:
            continue
        key = frozenset(wire.ends)
        old = original.get(key)
        if old is None:
            continue
        if wire.path != old.path:
            out[key] = dataclasses.replace(old, path=wire.path)
    return tuple(out.values())


def loose_wires_after_move(
    doc: PerfDocument,
    lookup: FootprintLookup,
    moved: Sequence[SymbolPlacement],
    frozen: Sequence[SheetWire] = (),
) -> tuple[LooseWire, ...]:
    """The loose wires whose path a move of ``moved`` stretched, for ``MoveSymbolsPayload``."""
    if not doc.sheet_loose_wires:
        return ()
    drawing = _after_move(doc, lookup, moved, frozen)[0]
    by_id = {w.id: w for w in doc.sheet_loose_wires}
    changed: list[LooseWire] = []
    for fw in drawing.free_wires:
        old = by_id.get(fw.id)
        if old is not None and fw.path != old.path:
            changed.append(dataclasses.replace(old, path=fw.path))
    return tuple(changed)


def ports_after_move(
    doc: PerfDocument,
    lookup: FootprintLookup,
    moved: Sequence[SymbolPlacement],
    frozen: Sequence[SheetWire] = (),
) -> tuple[SheetPort, ...]:
    """The ports whose link paths a move of ``moved`` stretched, for ``MoveSymbolsPayload``."""
    if not doc.sheet_ports:
        return ()
    drawing = _after_move(doc, lookup, moved, frozen)[0]
    pin_pos: dict[tuple[str, str], Point2] = {
        (symbol.ref, pin.number): _p(symbol.at.x + pin.at.x, symbol.at.y + pin.at.y)
        for symbol in drawing.symbols
        for pin in symbol.pins
    }
    changed: list[SheetPort] = []
    for port in doc.sheet_ports:
        new_links = []
        any_changed = False
        for link in port.links:
            start = pin_pos.get((link.pin.component_ref, link.pin.pin))
            if start is None:
                new_links.append(link)
                continue
            path = _reanchored(link.path, start, port.at)
            if port.kind != "label":
                path = _into_glyph(path, port.at, "up" if port.kind == "supply" else "down")
            if path != link.path:
                any_changed = True
                new_links.append(dataclasses.replace(link, path=path))
            else:
                new_links.append(link)
        if any_changed:
            changed.append(dataclasses.replace(port, links=tuple(new_links)))
    return tuple(changed)


def _apply_label_offsets(
    labels: list[Label], placements: Mapping[str, SymbolPlacement]
) -> list[Label]:
    """Shift each symbol's ref and value labels by any hand-dragged offset stored on its
    ``SymbolPlacement``. Applied after ``_part_labels`` so default layouts stay untouched."""
    out: list[Label] = []
    current_ref: str | None = None
    for label in labels:
        if label.kind == "ref":
            current_ref = label.text
            pl = placements.get(current_ref)
            if pl is not None and pl.ref_offset is not None:
                off = pl.ref_offset
                label = dataclasses.replace(label, at=_p(label.at.x + off.x, label.at.y + off.y))
        elif label.kind == "value" and current_ref is not None:
            pl = placements.get(current_ref)
            if pl is not None and pl.value_offset is not None:
                off = pl.value_offset
                label = dataclasses.replace(label, at=_p(label.at.x + off.x, label.at.y + off.y))
        out.append(label)
    return out


def placed_part_labels(drawing: SchematicDrawing) -> list[tuple[str, Literal["ref", "value"], Label]]:
    """Every symbol reference and value label on ``drawing``, paired with its owning symbol ref."""
    out: list[tuple[str, Literal["ref", "value"], Label]] = []
    current_ref: str | None = None
    for label in drawing.labels:
        if label.kind == "ref":
            current_ref = label.text
            out.append((current_ref, "ref", label))
        elif label.kind == "value" and current_ref is not None:
            out.append((current_ref, "value", label))
    return out


_RENUMBER_PREFIX = re.compile(r"^([A-Za-z_]+?)(\d+)$")


def plan_sheet_renumber(
    doc: PerfDocument, lookup: FootprintLookup
) -> tuple[tuple[str, str], ...]:
    """Compute a left-to-right, top-to-bottom reference renumbering for every part on the
    sheet, grouped by its reference prefix (R, C, U, ...). Returns ``(part_id, new_ref)``
    pairs for ``part.renumber``."""
    drawing = build_schematic(doc, lookup)
    id_by_ref = {part.ref: part.id for part in circuit_parts(doc)}
    groups: dict[str, list[tuple[float, float, str, str]]] = defaultdict(list)
    for symbol in drawing.symbols:
        part_id = id_by_ref.get(symbol.ref)
        if part_id is None:
            continue
        match = _RENUMBER_PREFIX.match(symbol.ref)
        if not match:
            continue
        prefix = match.group(1)
        groups[prefix].append((symbol.at.y, symbol.at.x, symbol.ref, part_id))

    mapping: list[tuple[str, str]] = []
    for prefix in sorted(groups):
        ordered = sorted(
            groups[prefix],
            key=lambda item: (round(item[0] / GRID_MM), round(item[1] / GRID_MM), _ref_sort_key(item[2])),
        )
        for index, (_y, _x, _old_ref, part_id) in enumerate(ordered, start=1):
            mapping.append((part_id, f"{prefix}{index}"))
    return tuple(mapping)


def _laid_onto(point: Point2, path: Sequence[Point2]) -> tuple[Point2, bool]:
    """Where a T lands on the wire it branches off: the point of ``path`` nearest ``point``,
    and whether that is one of the wire's two ends -- where three lines meeting is a bend
    and a pin, not a T, and gets no dot of its own.

    Nearest rather than exact, because the wire moves: dragging a symbol drags the end runs
    of its wires, and a T that stayed at the point it was drawn at would be left beside the
    wire instead of on it.
    """
    best: tuple[float, Point2] | None = None
    for start, end in itertools.pairwise(path):
        dx, dy = end.x - start.x, end.y - start.y
        if dy == 0:
            # A run along an axis is answered exactly: the projection below lands a T
            # a last bit off the run it is on, which then bends the T's last corner by as
            # much -- invisible, and a wire that no longer meets its own junction dot.
            on = _p(min(max(point.x, min(start.x, end.x)), max(start.x, end.x)), start.y)
        elif dx == 0:
            on = _p(start.x, min(max(point.y, min(start.y, end.y)), max(start.y, end.y)))
        else:
            length = dx * dx + dy * dy
            t = ((point.x - start.x) * dx + (point.y - start.y) * dy) / length
            t = min(max(t, 0.0), 1.0)
            on = _p(start.x + t * dx, start.y + t * dy)
        distance = (on.x - point.x) ** 2 + (on.y - point.y) ** 2
        if best is None or distance < best[0]:
            best = (distance, on)
    if best is None:
        return point, False
    landed = best[1]
    return landed, landed in (path[0], path[-1])


def _pin_of(symbols: dict[str, _Placed], node: NetNode) -> Point2 | None:
    placed = symbols.get(node.component_ref)
    if placed is None:
        return None
    for pin in placed.body.pins:
        if pin.number == node.pin:
            return placed.anchor_of(pin)
    return None


def _junctions_of(wires: Sequence[Wire]) -> tuple[Junction, ...]:
    """A dot wherever three or more runs of one net meet at a point.

    THREE, NOT TWO, and that is the whole convention: two wires meeting end to end are one
    wire that turns a corner, and a dot there claims a join that is really a bend. A wire
    crossing another in the middle is an ordinary schematic crossing and carries no dot,
    which is what lets a reader tell the two apart.

    Counted on what is DRAWN, not on the wires' ends: one net's wires are taken together,
    cut at every corner and end any of them has, and a run two of them lie along is one
    run. The sheet drawn for you lays each connection pin to pin and lets one net's wires
    share a line, so a wire leaving the shared line is a T that no three ENDS ever meet at:
    counting ends left every such T without a dot (six on atmega328-relay, ten on
    lm317-supply), and a reader could not tell it from a crossing.
    """
    by_net: dict[NetId, list[tuple[Point2, ...]]] = defaultdict(list)
    for wire in wires:
        if len(wire.path) > 1:
            by_net[wire.net_id].append(wire.path)
    found: list[Junction] = []

    def key(point: Point2) -> tuple[float, float]:
        return round(point.x, 6), round(point.y, 6)

    for net_id in sorted(by_net):
        paths = by_net[net_id]
        corners = {key(point) for path in paths for point in path}
        runs: set[frozenset[tuple[float, float]]] = set()
        for path in paths:
            for a, b in itertools.pairwise(path):
                start, end = key(a), key(b)
                if start == end:
                    continue
                cuts = sorted(
                    (
                        point
                        for point in corners
                        if _strictly_between(start, end, point)
                    ),
                    key=lambda point: abs(point[0] - start[0]) + abs(point[1] - start[1]),
                )
                stops = [start, *cuts, end]
                runs.update(
                    frozenset((p, q)) for p, q in itertools.pairwise(stops)
                )
        degree: dict[tuple[float, float], int] = defaultdict(int)
        for run in runs:
            for point in run:
                degree[point] += 1
        found.extend(
            Junction(net_id=net_id, at=_p(x, y))
            for (x, y), count in sorted(degree.items())
            if count >= 3
        )
    return tuple(found)


def _strictly_between(
    start: tuple[float, float], end: tuple[float, float], point: tuple[float, float]
) -> bool:
    """Whether ``point`` lies on the segment from ``start`` to ``end``, not at either end."""
    if point in (start, end):
        return False
    (ax, ay), (bx, by), (px, py) = start, end, point
    if abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) > 1e-6:
        return False
    return (
        min(ax, bx) - 1e-6 <= px <= max(ax, bx) + 1e-6
        and min(ay, by) - 1e-6 <= py <= max(ay, by) + 1e-6
    )


def _part_labels(ordered: Sequence[_Placed], options: SchematicOptions) -> list[Label]:
    """The reference, the value and the pin numbers. One answer for both kinds of sheet."""
    labels: list[Label] = []
    for placed in ordered:
        centre = placed.x + placed.body.width / 2
        sides = {pin.side for pin in placed.body.pins}
        if (
            placed.body.pins
            and sides <= {"top", "bottom"}
            and placed.kind not in ("ic", "connector", "box", "relay")
            and not placed.body.names_inside
        ):
            # A part stood on end: its ends are where the wires join and the glyphs hang,
            # so the reference and the value go beside the body, as every schematic does.
            beside = placed.x + placed.body.width + 0.75 * GRID_MM
            middle = placed.y + placed.body.height / 2
            labels.append(
                Label(
                    text=placed.ref,
                    at=_p(beside, middle - 0.5 * GRID_MM),
                    kind="ref",
                    anchor="left",
                )
            )
            if options.show_values and placed.value:
                labels.append(
                    Label(
                        text=placed.value,
                        at=_p(beside, middle + 0.5 * GRID_MM),
                        kind="value",
                        anchor="left",
                    )
                )
            if options.show_pin_numbers and placed.kind in _TRANSISTOR_KINDS:
                labels.extend(_lead_number(placed, pin) for pin in placed.body.pins)
            continue
        top_lead = any(
            pin.side == "top" and abs(pin.at.x - placed.body.width / 2) < GRID_MM
            for pin in placed.body.pins
        )
        # Well clear of the box rather than snug to it: a reference is drawn at a fixed
        # PIXEL size, so how many millimetres of sheet it occupies grows as the view zooms
        # out -- and the one symbol with anything near its top edge is the LED.
        if top_lead and placed.kind == "ic":
            # A chip drawn by what its pins do has its supply on a lead out of the middle of
            # its top. Beyond the right-hand leads, where the LED's goes, the reference sat
            # past the output stubs and read as nobody's; above the box's own left edge,
            # level with the end of the supply lead, it is the chip's. Not lower: the lead's
            # height belongs to the symbol, and a label there is on its body.
            box_left = placed.x + (LEAD_MM if "left" in sides else 0.0)
            ref_at = _p(box_left, placed.y - 0.75 * GRID_MM)
        elif top_lead:
            ref_at = _p(placed.x + placed.body.width + 0.5 * GRID_MM, placed.y - 0.25 * GRID_MM)
        else:
            ref_at = _p(centre, placed.y - 0.75 * GRID_MM)
        labels.append(
            Label(
                text=placed.ref,
                at=ref_at,
                kind="ref",
                anchor="left" if top_lead else "centre",
            )
        )
        if options.show_values and placed.value:
            labels.append(
                Label(
                    text=placed.value,
                    at=_p(
                        placed.x + _value_centre_x(placed),
                        placed.y + placed.body.height + 0.4 * GRID_MM,
                    ),
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
        #
        # A body that leaves room for its names says so (``SymbolBody.names_inside``), and the
        # kinds that always did are listed because their bodies are unchanged.
        if placed.kind in ("ic", "connector", "box", "relay") or placed.body.names_inside:
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

#: How far a value moved aside keeps from the lead it was moved off, beyond its own half.
VALUE_LEAD_GAP_MM: Mm = 0.5 * GRID_MM


def _value_centre_x(placed: _Placed) -> Mm:
    """Where a symbol's value is centred, across from the body's left edge.

    Under the middle of the body, unless a lead leaves the bottom there: a regulator's
    ground, a turned box's bottom pin. The lead runs straight down through the value's
    line, so the value moves right, clear of the rightmost such lead. The rail symbol at
    the lead's end is a lead's length down, below the value's line, so only the lead
    itself is in the way.
    """
    centre = placed.body.width / 2
    half = _text_width(placed.value, VALUE_LABEL_MM) / 2 + VALUE_LEAD_GAP_MM
    under = [
        pin.at.x
        for pin in placed.body.pins
        if pin.side == "bottom" and centre - half < pin.at.x < centre + half
    ]
    if not under:
        return centre
    return max(under) + half


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
    part_labels: Sequence[Label] = (),
    free_wires: Sequence[FreeWire] = (),
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
    runs.extend(fw.path for fw in free_wires)
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
    for label in part_labels:
        box = _part_label_box(label)
        if box is not None:
            right = max(right, box[2])
            bottom = max(bottom, box[3])
    # A label's own width is not known here -- it is drawn at a size the renderer picks --
    # so the margin doubles as the room for a net name written at the right-hand edge.
    return right + 2 * MARGIN_MM, bottom + MARGIN_MM
