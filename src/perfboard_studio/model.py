"""Perfboard Studio domain model.

Ported from the original TypeScript engine. Two rules govern this file:

1. The document is IMMUTABLE. Every dataclass is frozen; mutations happen only by
   dispatching a Command (see command.py), which builds a new document with
   ``dataclasses.replace``. Nothing writes to a document in place.

2. The JSON wire format must stay byte-identical to what the TypeScript engine
   produced. Field names here are Python-cased, but persist.py maps them to the exact
   camelCase keys the .perf format uses. That is what lets the port be verified
   differentially against the old implementation rather than merely "tested".

The one idea worth carrying over above all others: a perfboard connection is not one
thing. There are six physically distinct ways to join two points, each with its own
constraints, costs and failure modes, and modelling that difference is what this whole
project rests on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

type Mm = float

#: Standard perfboard hole pitch.
STANDARD_PITCH_MM: Mm = 2.54

# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, order=True)
class HoleCoord:
    """A hole on the board grid, 0-indexed from the top-left.

    ``col`` grows to the right and ``row`` grows downward, matching both the canvas
    convention and the way a board reads when held component-side up.
    """

    col: int
    row: int


#: Human-facing hole address: column letters plus a 1-indexed row, e.g. "A1", "AC12".
#: This is the language the soldering guide speaks, so it is a first-class concept
#: rather than a formatting detail.
type HoleRef = str


@dataclass(frozen=True, slots=True)
class Point2:
    x: Mm
    y: Mm


#: Which physical face of the board something lives on.
#: 'top' is the component side, 'bottom' the solder side.
type BoardSide = Literal["top", "bottom"]

type Rotation = Literal[0, 90, 180, 270]

VALID_ROTATIONS: tuple[Rotation, ...] = (0, 90, 180, 270)

# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------

#: Which kind of board this is, and it decides what a connection IS: on pad-per-hole
#: every hole is an island and every connection is added, while on stripboard whole rows
#: arrive joined and the design is where the copper is BROKEN (see stripboard.py).
#: Spelled with ``TypeAlias`` for the same reason ``BoardMaterial`` below is: it is READ
#: AT RUN TIME, by the MCP server validating an agent's requested type against
#: ``get_args`` -- which returns an empty tuple for a PEP 695 alias, so every value would
#: be refused by a check that raises nothing.
BoardType: TypeAlias = Literal["pad-per-hole", "stripboard", "plain"]  # noqa: UP040

#: Substrate material. Not cosmetic: FR-2 phenolic paper (cheap "pertinaks") lifts pads
#: under sustained heat far more readily than FR-4, which bounds how long a pure solder
#: trace may be.
#: Spelled with ``TypeAlias`` rather than PEP 695's ``type``, and it has to be: this name
#: is READ AT RUN TIME. ``get_args`` of a ``type`` alias returns an empty tuple, and the
#: tests that check every member of it is handled -- every material offered in the dialog,
#: every archetype drawable, every conductor kind covered -- would then assert that an
#: empty set equals an empty set and pass while checking nothing.
BoardMaterial: TypeAlias = Literal["FR4", "FR2", "FR1"]  # noqa: UP040

#: One face, or both. Distinct from ``BoardSide``, which is always exactly one — a
#: silkscreen legend or a set of connector fingers is routinely printed on both.
type BoardFace = Literal["top", "bottom", "both"]

#: Pad outline. NOT cosmetic, for the same reason the pad diameter is not: the R5'
#: bridging risk that this whole tool is organised around is a function of the gap
#: between one pad's edge and the next one's, and an oblong pad has TWO different such
#: gaps — a small one along its long axis and a comfortable one across it. A board with
#: oblong pads is therefore easy to run a solder trace along and hard to run one across,
#: which is a real constraint on how it should be laid out. See
#: ``geometry.pad_extent_mm``.
type PadShape = Literal["round", "oblong"]

#: Which way an oblong pad's long axis points. "vertical" runs down a column (so
#: consecutive ROWS are the close pair), "horizontal" runs along a row.
type PadAxis = Literal["horizontal", "vertical"]


@dataclass(frozen=True, slots=True)
class BoardLabels:
    """Hole addresses printed on the substrate itself.

    The boards this models carry their own legend — ``A``..``Z`` along one edge,
    ``01``..``22`` down the other — and it is the same address space this tool speaks
    everywhere else (``geometry.column_label`` / ``row_label``), which is what makes it
    worth modelling rather than leaving to the editor's ruler. On a board with a printed
    legend the builder reads "C7" straight off the copper instead of counting holes from
    a corner, and the guide's preparation step stops having to tell them to mark A1.
    """

    #: Which face carries the print.
    face: BoardFace = "both"
    #: Zero-pad the row number to this many digits. 1 gives "7", matching a HoleRef
    #: exactly; 2 gives "07", which is what boards printing "01".."22" actually show.
    #: The addresses themselves never change — this is how the *board* renders one.
    row_digits: int = 1
    #: Print the legend on all four edges — letters along the top AND bottom, numbers
    #: down the left AND right — which is what the boards being modelled do. With one
    #: edge each, half the board is nearer the edge that does not carry its address,
    #: which is exactly where counting starts again.
    all_edges: bool = True


@dataclass(frozen=True, slots=True)
class Board:
    type: BoardType
    cols: int
    rows: int
    pitch: Mm
    thickness: Mm
    material: BoardMaterial
    #: Round pad: the diameter. Oblong pad: the SHORT axis, i.e. its width.
    pad_diameter: Mm
    drill_diameter: Mm
    #: Stripboard only: the axis the copper strips run along.
    strip_axis: Literal["horizontal", "vertical"] | None = None
    pad_shape: PadShape = "round"
    #: Oblong only: the long axis, which must exceed ``pad_diameter``. Required when
    #: ``pad_shape`` is "oblong" and meaningless otherwise.
    pad_length: Mm | None = None
    pad_axis: PadAxis = "vertical"
    #: Extra substrate beyond the usual half pitch, left/right and top/bottom.
    #:
    #: Zero on a plain board, which is cut flush half a pitch past the outermost hole
    #: centres. A board with a printed legend is NOT: at 2.54 mm pitch with 1.9 mm pads
    #: that half pitch leaves 0.32 mm of bare substrate, which is not room to print a
    #: character in, and the boards this models are physically wider at the edge for
    #: exactly that reason.
    #:
    #: TWO NUMBERS, NOT ONE, because real boards are not square about it: a 4 x 6 cm board
    #: with 20 x 14 holes carries about 4.6 mm of border on the edges with the numbers and
    #: the oblong pads, and about 2.2 mm on the edges with the letters. One figure would
    #: put the 1:1 printout several millimetres out on one axis, and that printout gets
    #: taped to the board.
    #:
    #: Anything that must land on a hole still measures from ``hole_span_mm``, which this
    #: deliberately does not touch — see the note there about mirroring.
    border_x_mm: Mm = 0.0
    border_y_mm: Mm = 0.0
    #: Copper on the solder side only, with plain drilled holes on the component side.
    #:
    #: The cheap brown/orange phenolic board. It is not a rendering detail: there is no
    #: pad to solder to on the component side at all, so nothing may be soldered there,
    #: and the pads lift more readily because there is no second annulus holding them on.
    single_sided: bool = False
    #: None when the board carries no printed legend, which is the common cheap board.
    labels: BoardLabels | None = None


# ---------------------------------------------------------------------------
# Mechanical features of the board itself
# ---------------------------------------------------------------------------

#: Which edge of the board something runs along. ``TypeAlias`` again, and again because
#: the MCP server reads its members at run time to tell an agent what the choices are.
BoardEdge: TypeAlias = Literal["top", "bottom", "left", "right"]  # noqa: UP040


@dataclass(frozen=True, slots=True)
class MountingHole:
    """A screw hole drilled through the board, addressed by the grid hole it replaces.

    Addressed by hole rather than by millimetres on purpose: every message and every
    measurement step in this system names a hole (PLAN.md §4.1), and "MH1 at A1" is
    something a builder can find where a coordinate pair is not.

    The bore is much wider than a pad, so it does not merely occupy its own hole — an M3
    clearance hole at 2.54 mm pitch eats the copper off its four orthogonal neighbours as
    well. Which holes those are is derived, once, by ``geometry.mounting_bore_consumes``,
    and it is why DRC has to be able to say that a pin has been placed on a pad that no
    longer exists.
    """

    id: str
    at: HoleCoord
    #: Millimetres from ``at``'s centre, which is how a hole gets to sit in the BORDER
    #: rather than on the grid. That is where these boards actually put their corner
    #: holes: outside the A column and the 01 row, eating no pads at all. Addressed by
    #: the nearest hole regardless, so "the hole outside A1" is still something a builder
    #: can find. Zero puts the bore on the grid, which destroys the pads around it.
    offset_x_mm: Mm = 0.0
    offset_y_mm: Mm = 0.0
    #: The drilled bore. 3.2 mm is an M3 clearance hole.
    diameter: Mm = 3.2
    #: Screw head or washer footprint. Nothing may sit under it on the component side,
    #: which is a separate and larger keepout than the bore's.
    head_diameter: Mm = 6.0


@dataclass(frozen=True, slots=True)
class EdgeConnector:
    """A run of elongated finger pads along one board edge.

    A finger is the pad of the hole it sits on, stretched out to the board edge and
    usually widened — more copper to take the mechanical load of a connector, and a
    target you can solder a shell or a ribbon to. It covers EXACTLY ONE HOLE, which is
    what makes this a purely physical feature: a finger is electrically its own pad and
    nothing more, so connectivity, LVS and the router are untouched by it. A true
    multi-hole card edge would join the rows it spans, and the format does not model one.

    ``finger_width`` must stay below the pitch. Two fingers as wide as the pitch are not
    two fingers, they are one piece of copper shorting two nets, and the model has no way
    to say that.
    """

    id: str
    edge: BoardEdge
    #: First column (top/bottom edge) or row (left/right edge) of the run, 0-indexed.
    start: int
    count: int
    #: Across the run. Wider than a pad, narrower than the pitch.
    finger_width: Mm = 2.0
    #: Inward from the BOARD EDGE, not from the hole. None means "as far as it should
    #: go": past its own hole by half a pitch, which is ``board_edge_margin_mm(board) +
    #: pitch / 2``. Left to be derived because the right answer depends on the board's
    #: border — a fixed length that reaches the hole on a flush-cut board stops short of
    #: it on one with a printed border, and a finger that does not include its own hole
    #: is not a finger.
    finger_length: Mm | None = None
    #: Bare substrate left between the finger's outer end and the board edge.
    #:
    #: Zero is a true card edge, where reaching the edge is the point. Anything else is
    #: what the prototyping boards actually do: the elongated pads stop short, and the
    #: strip left outside them is where the row numbers are printed. Without this the
    #: fingers swallow the whole border and the legend has nowhere to go.
    inset_mm: Mm = 0.0
    #: Both faces by default: these are plated through-hole pads like every other one on
    #: the board, just a different shape, so copper on one side only would be the odd
    #: case rather than the normal one.
    face: BoardFace = "both"


# ---------------------------------------------------------------------------
# Footprints and component bodies
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FootprintPin:
    number: str
    #: Hole offset from the component anchor, in grid steps (not mm).
    d_col: int
    d_row: int
    name: str | None = None


#: Spelled with ``TypeAlias`` rather than PEP 695's ``type``, and it has to be: this name
#: is READ AT RUN TIME. ``get_args`` of a ``type`` alias returns an empty tuple, and the
#: tests that check every member of it is handled -- every material offered in the dialog,
#: every archetype drawable, every conductor kind covered -- would then assert that an
#: empty set equals an empty set and pass while checking nothing.
BodyArchetype: TypeAlias = Literal[  # noqa: UP040
    "axial-cylinder",  # resistors, DO-41 diodes
    "radial-electrolytic",
    "disc-ceramic",
    "box-film",
    "dip",
    "to92",
    "to220",
    "led-round",
    "pin-header",
    "screw-terminal",
    "potentiometer",
    "tactile-switch",
    "crystal-hc49",
    "relay-box",
    "generic-box",
    # A 2xN IDC box header: the pin header's pins inside a shroud with a key slot, which
    # is what a ribbon cable plugs into and the one thing about it that says where pin 1 is.
    "box-header",
    # A screw terminal whose wires go in from ABOVE: a pluggable block on a vertical
    # (180 degree) header, the kind sold as "dik klemens". It has no side mouth, so nothing
    # has to stand clear in front of it and it can live in the middle of a board.
    "screw-terminal-vertical",
]

#: Archetypes that get hot enough to matter to a neighbour.
#:
#: Here rather than in the two modules that act on it, because "a TO-220 runs hot" is a
#: fact about the part and not a policy either of them owns. `placer.py` prices it into
#: the arrangement it searches for and `drc.py` reports it on the arrangement it is
#: given, and the two disagreeing would mean the optimiser working to avoid something the
#: checker never mentions -- or, worse, moving parts apart for a reason the user is never
#: told.
HEAT_SOURCE_ARCHETYPES: frozenset[BodyArchetype] = frozenset({"to220", "relay-box"})

#: Archetypes whose life is measurably shortened by sitting next to one. An electrolytic
#: loses electrolyte with temperature; the usual rule of thumb is halved life per 10 °C.
HEAT_SENSITIVE_ARCHETYPES: frozenset[BodyArchetype] = frozenset({"radial-electrolytic"})

#: Body-centre spacing below which a heat source starts costing its neighbour, in mm.
HEAT_CLEARANCE_MM: Mm = 12.0


def is_heat_pair(a: BodyArchetype, b: BodyArchetype) -> bool:
    """Whether one of these two archetypes cooks the other. Symmetric, by construction."""
    return (a in HEAT_SOURCE_ARCHETYPES and b in HEAT_SENSITIVE_ARCHETYPES) or (
        b in HEAT_SOURCE_ARCHETYPES and a in HEAT_SENSITIVE_ARCHETYPES
    )


@dataclass(frozen=True, slots=True)
class BodySpec:
    """Parameters for procedurally generating the 3D body.

    We generate roughly 25 body archetypes rather than shipping a mesh library, which
    keeps assets at zero, guarantees the 3D body agrees with the footprint, and avoids
    inheriting a share-alike asset licence.
    """

    archetype: BodyArchetype
    #: Archetype-specific dimensions in mm, e.g. {"length": 6.3, "diameter": 2.4}.
    dims: dict[str, Mm] = field(default_factory=dict)
    color: str | None = None


@dataclass(frozen=True, slots=True)
class Footprint:
    id: str
    name: str
    pins: tuple[FootprintPin, ...]
    #: Body outline in mm relative to the anchor hole centre. Used for courtyard DRC.
    body_outline: tuple[Point2, ...]
    #: Height above the board surface, for clearance DRC and 3D.
    body_height: Mm
    body: BodySpec
    lead_diameter: Mm
    polarized: bool


# ---------------------------------------------------------------------------
# Component instances
# ---------------------------------------------------------------------------

type ComponentId = str

#: What a part IS, when the package cannot say and the person who chose the part can.
#:
#: THE PINOUT IS A FACT ABOUT THE PART, NOT THE PACKAGE -- which is why a TO-92 is a box on
#: the sheet: BC547 and 2N3904 share the outline and disagree about which leg is the base,
#: and a TO-220 is a regulator, a transistor, a MOSFET and a bridge rectifier. The registry
#: refuses to guess, and that refusal is right for the registry. It is not a reason for the
#: DOCUMENT to stay silent: the person who put an IRF9540N on the board knows it is a
#: P-channel MOSFET and knows which lead is the gate, and until this existed there was
#: nowhere to write that down. So the claim moves to where the knowledge is, and the
#: schematic draws the real symbol only when the part says what it is AND names the leads
#: the symbol needs (``schematic.DECLARED_SYMBOL_PINS``) -- a declared transistor with
#: unnamed leads is still a box, with a note saying why.
#:
#: Two of these are not about a pinout at all. A zener in a DO-35 is the same package as a
#: signal diode and a PTC fuse is a disc, so the package draws them as a diode and as a
#: capacitor; the declaration is the only thing that can say otherwise.
#:
#: Spelled with ``TypeAlias`` because persist and the MCP server read it at run time with
#: ``get_args`` -- the trap this file documents above ``BodyArchetype``.
PartSymbol: TypeAlias = Literal[  # noqa: UP040
    "npn",
    "pnp",
    "nmos",
    "pmos",
    "zener",
    "fuse",
]

#: Pin number -> the name the part's datasheet gives that lead, in pin order.
#:
#: A tuple of pairs rather than a dict so an instance stays hashable and compares by value
#: like every other field in this file. ``normalized_pin_names`` is the one place the
#: order is decided.
type PinNames = tuple[tuple[str, str], ...]


def pin_number_sort_key(number: str) -> tuple[int, float, str]:
    """Pin "10" after pin "9", and a lettered pin after every numbered one.

    The order ``schematic`` draws pins in, stated here because the document now stores pin
    numbers of its own and has to keep them in SOME order: sorted as text, pin 10 lands
    between 1 and 2.
    """
    try:
        return (0, float(number), "")
    except ValueError:
        return (1, 0.0, number)


def normalized_pin_names(names: object) -> PinNames:
    """Declared pin names in canonical form: stripped, blank names dropped, pin order.

    Takes a mapping or a sequence of pairs, because both callers exist -- an agent hands a
    dict, a document already holds pairs. A BLANK NAME is dropped rather than refused:
    clearing one cell in a table of forty pins means "this one has no name", and a dialog
    answering that with an error would be arguing with the obvious reading. A blank pin
    NUMBER is a name attached to nothing, and raises ``ValueError``.
    """
    pairs: list[object]
    if isinstance(names, dict):
        pairs = list(names.items())
    elif isinstance(names, (list, tuple)):
        pairs = list(names)
    else:
        raise ValueError("Pin names are a mapping of pin number to name.")
    kept: dict[str, str] = {}
    for entry in pairs:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ValueError("Each pin name is a (pin number, name) pair.")
        number, name = entry
        if not isinstance(number, str) or not isinstance(name, str):
            raise ValueError("A pin number and a pin name are both text.")
        number, name = number.strip(), name.strip()
        if not number:
            raise ValueError(f"The name {name!r} is given to a pin with no number.")
        if name:
            kept[number] = name
    return tuple(sorted(kept.items(), key=lambda item: pin_number_sort_key(item[0])))


@dataclass(frozen=True, slots=True)
class ComponentInstance:
    id: ComponentId
    #: Designator, e.g. "R1". Matches the schematic netlist.
    ref: str
    value: str
    footprint_id: str
    #: Hole the footprint's origin sits on.
    anchor: HoleCoord
    rotation: Rotation = 0
    mirrored: bool = False
    locked: bool = False
    #: What this particular part calls its leads, over whatever the footprint calls them.
    #: Empty, the footprint's own names stand -- and the field is left out of the file.
    pin_names: PinNames = ()
    #: What this part is when its package cannot say. See ``PartSymbol``.
    symbol: PartSymbol | None = None


@dataclass(frozen=True, slots=True)
class SchematicPart:
    """A part the DESIGN has and the board has not yet: drawn, wired, not placed.

    This is what makes schematic-first capture possible — draw the circuit, then place it
    — and it is deliberately a SEPARATE list rather than a ``ComponentInstance`` with an
    optional anchor.

    EVERY MODULE DOWNSTREAM OF THE BOARD ITERATES ``doc.components`` AND IS RIGHT TO
    ASSUME EACH ONE HAS A POSITION. DRC, occupancy, connectivity, the router, the placer,
    the guide, the 1:1 PDF and both renderers — sixty-odd sites between them. An optional
    anchor would make every one of those responsible for remembering that a part might be
    nowhere, and the first one to forget would either crash or quietly treat the part as
    sitting at hole A1. Keeping the two lists apart means the board modules never see a
    part that is not on the board, and it costs one rule instead: a reference is unique
    across BOTH lists, which the commands enforce in one helper.

    It carries no rotation and no lock. Both are answers about a physical object on a
    board, and this is not on a board yet; they are chosen when it is placed. It DOES carry
    the pin names and the symbol, because those are answers about the part itself: the
    same on the sheet before placement as after it, and moved across by ``part.place``.
    """

    id: ComponentId
    ref: str
    value: str
    footprint_id: str
    pin_names: PinNames = ()
    symbol: PartSymbol | None = None


def declared_pin_name(part: ComponentInstance | SchematicPart, number: str) -> str | None:
    """The name this part declares for one of its leads, or ``None``."""
    for pin, name in part.pin_names:
        if pin == number:
            return name
    return None


def pin_name_of(
    part: ComponentInstance | SchematicPart | None, pin: FootprintPin
) -> str | None:
    """What a lead is called: the part's own name for it first, the footprint's second.

    THE ONE ANSWER to "what is this pin called", for the sheet, the guide and the MCP
    server alike. The declared name wins because it is the more specific fact: an LED's
    footprint says ``A`` and ``K`` and a part may say the same, but a TO-220's footprint
    says nothing and the part is the only source there is.
    """
    if part is not None:
        declared = declared_pin_name(part, pin.number)
        if declared is not None:
            return declared
    return pin.name


@dataclass(frozen=True, slots=True)
class SymbolPlacement:
    """Where one part's symbol sits on the sheet, and which way round it is.

    MILLIMETRES, AND THAT IS THE WHOLE OF IT. This used to be a CELL in a grid the layout
    owned, which is what let the sheet stay derived: wires ran only in the channels between
    cells, so no wire could cross a symbol. That guarantee is real and it is also the reason
    the sheet was not a schematic editor -- a symbol could be moved to another cell and
    nowhere else, it could not be turned, and a wire could not be drawn at all. A tool that
    can capture a circuit and cannot DRAW one is asking people to keep another one open
    beside it.

    So the sheet has two states, and which one a document is in is decided by whether this
    tuple is empty. Empty, the whole drawing is derived exactly as before, and every one of
    the fifteen golden fixtures serializes to the bytes it always did. Non-empty, the
    positions here are the sheet: every symbol has one, the layout arranges nothing, and
    what is not joined by a wire somebody drew is joined by a net LABEL, which is what a
    schematic does with a net too busy to draw.

    ``at`` is the top-left of the symbol's own box, on the sheet grid. ``rotation`` is
    clockwise and ``mirrored`` is applied before it, about the symbol's vertical centre --
    the same order ``ComponentInstance`` uses on the board, so the two never have to be
    reasoned about differently.

    Keyed on the part's ID rather than its reference, so it survives a rename -- and so it
    survives ``part.place`` and ``component.unplace``, which move a part between the two
    lists and keep the id.
    """

    id: ComponentId
    at: Point2
    rotation: Rotation = 0
    mirrored: bool = False


@dataclass(frozen=True, slots=True)
class SheetWire:
    """A wire somebody drew on the sheet, between two pins.

    THE CIRCUIT IS STILL ``doc.nets`` AND THIS IS ONLY HOW IT WAS DRAWN. A wire carries no
    net id: which net it belongs to is whichever net holds both of its ends, looked up
    every time. That is what keeps the netlist the one answer to "what is connected" --
    LVS, the router, the placer, the guide and the board all read ``doc.nets`` and none of
    them has to learn about geometry -- and it is what makes a wire left over from a
    connection somebody has since removed simply stop being drawn, instead of quietly
    asserting a join that no longer exists.

    Two pins and no more. A net drawn as three wires between four pins reads exactly like a
    net drawn as one branching run, and a branch point would need a fourth kind of endpoint
    -- a point on another wire -- that moves whenever either end does.

    ``path`` is the orthogonal chain between them, in sheet millimetres, first point at
    ``a`` and last at ``b``.
    """

    a: NetNode
    b: NetNode
    path: tuple[Point2, ...]


#: What a sheet note draws. Text, and the three shapes an annotation is made of -- which is
#: the same argument ``SymbolShape`` makes about having three kinds and no more.
type SheetNoteKind = Literal["text", "line", "rectangle", "circle"]

#: Every member of the above, spelled out. ``get_args`` returns an empty tuple for a PEP
#: 695 alias -- the trap ``BoardType`` and friends carry a ``noqa`` for -- so the run-time
#: list is written down and a test asserts the two agree.
SHEET_NOTE_KINDS: tuple[SheetNoteKind, ...] = ("text", "line", "rectangle", "circle")

#: Cap height a note's text is given when nobody has said otherwise. Here rather than in
#: ``persist`` so the default and the value the file omits are one number.
DEFAULT_NOTE_SIZE_MM: Mm = 3.5


@dataclass(frozen=True, slots=True)
class SheetNote:
    """Something on the sheet that is not the circuit: a caption, a box round a block.

    NOTHING DERIVES ANYTHING FROM THESE. They are not checked by DRC, they are not read by
    LVS, and no command refuses one for overlapping anything -- a note is a person writing
    on the drawing, and a drawing tool that argued with what was written on it would be
    worse than one with no notes at all.

    ``at`` and ``to`` are the two corners for ``rectangle`` and ``circle``, the two ends for
    ``line``, and both the same point for ``text``.
    """

    id: str
    kind: SheetNoteKind
    at: Point2
    to: Point2
    text: str = ""
    #: Cap height in millimetres of sheet, for ``text``. Millimetres and not points because
    #: everything else on this sheet is millimetres and the export is 1:1.
    size_mm: Mm = DEFAULT_NOTE_SIZE_MM


# ---------------------------------------------------------------------------
# Conductors# ---------------------------------------------------------------------------
# Conductors — the heart of the model
# ---------------------------------------------------------------------------

#: Spelled with ``TypeAlias`` rather than PEP 695's ``type``, and it has to be: this name
#: is READ AT RUN TIME. ``get_args`` of a ``type`` alias returns an empty tuple, and the
#: tests that check every member of it is handled -- every material offered in the dialog,
#: every archetype drawable, every conductor kind covered -- would then assert that an
#: empty set equals an empty set and pass while checking nothing.
ConductorKind: TypeAlias = Literal[  # noqa: UP040
    "lead-bend",  # a component lead bent to reach a nearby hole; effectively free
    "solder-trace",  # TR "lehim yolu": adjacent pads joined with solder alone
    "solder-trace-wired",  # the same, over a tinned-wire or lead-offcut spine
    "bare-wire",  # bare/tinned wire on the solder side; cannot cross other copper
    "insulated-wire",  # may cross other conductors, at a preparation cost
    "top-jumper",  # insulated jumper routed over the component side
    "strip",  # stripboard's pre-existing copper strip (v2)
]

type ConductorId = str

#: How much solder has been built up, which sets the effective cross-section.
type SolderBuildup = Literal["light", "normal", "heavy"]


@dataclass(frozen=True, slots=True)
class SpineSpec:
    material: Literal["tinned-copper", "lead-offcut"]
    gauge: Mm


@dataclass(frozen=True, slots=True)
class SolderTraceConductor:
    """Pads joined with solder, optionally over a wire spine.

    INVARIANT: consecutive entries in ``path`` must be 4-neighbours (orthogonally
    adjacent). Solder cannot reliably span a diagonal gap — at 2.54 mm pitch the
    orthogonal pad-edge gap is around 0.6 mm, while the diagonal one is nearer 1.7 mm.
    """

    id: ConductorId
    path: tuple[HoleCoord, ...]
    buildup: SolderBuildup = "normal"
    spine: SpineSpec | None = None
    net_id: NetId | None = None
    layer_z: int = 0
    kind: Literal["solder-trace", "solder-trace-wired"] = "solder-trace"
    side: Literal["bottom"] = "bottom"


@dataclass(frozen=True, slots=True)
class WireConductor:
    id: ConductorId
    path: tuple[HoleCoord, ...]
    kind: Literal["bare-wire", "insulated-wire", "top-jumper"] = "bare-wire"
    side: BoardSide = "bottom"
    gauge_awg: int | None = None
    #: Insulation colour, used by the cut list and the guide's colour convention.
    color: str | None = None
    net_id: NetId | None = None
    layer_z: int = 0


@dataclass(frozen=True, slots=True)
class LeadBendConductor:
    id: ConductorId
    path: tuple[HoleCoord, ...]
    component_id: ComponentId
    pin_number: str
    net_id: NetId | None = None
    layer_z: int = 0
    kind: Literal["lead-bend"] = "lead-bend"
    side: Literal["bottom"] = "bottom"


@dataclass(frozen=True, slots=True)
class StripConductor:
    id: ConductorId
    path: tuple[HoleCoord, ...]
    net_id: NetId | None = None
    layer_z: int = 0
    kind: Literal["strip"] = "strip"
    side: BoardSide = "bottom"


type Conductor = (
    SolderTraceConductor | WireConductor | LeadBendConductor | StripConductor
)


@dataclass(frozen=True, slots=True)
class TrackCut:
    """Stripboard track cut (v2)."""

    id: str
    at: HoleCoord


# ---------------------------------------------------------------------------
# Nets
# ---------------------------------------------------------------------------

type NetId = str

type NetClass = Literal["power", "ground", "signal"]


@dataclass(frozen=True, slots=True, order=True)
class NetNode:
    """A node in the schematic netlist: one pin of one component."""

    component_ref: str
    pin: str


@dataclass(frozen=True, slots=True)
class Net:
    """A net as declared by the schematic.

    This is the *intent*; what the board actually connects is derived from the
    conductors by the connectivity engine. Comparing the two is LVS.
    """

    id: NetId
    name: str
    nodes: tuple[NetNode, ...]
    net_class: NetClass = "signal"
    #: Expected current, if the user supplied it. Drives current-capacity DRC.
    current_a: float | None = None
    #: Nominal voltage, if supplied. Drives creepage DRC.
    voltage_v: float | None = None


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

#: Bumped whenever a migration is needed. Persisted in the project file.
DOCUMENT_FORMAT_VERSION = 1


#: What a document is called until somebody names it. A board is named after its file
#: the first time it is saved (``document.rename``, dispatched by the host), because
#: this is the title the build guide, the schematic and the project folder all print --
#: and every board anybody ever made in the application used to go out with it.
UNTITLED_NAME = "untitled"


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    name: str
    #: ISO 8601. Set by the host, never by the engine, which must stay deterministic.
    created: str
    modified: str


@dataclass(frozen=True, slots=True)
class PerfDocument:
    meta: DocumentMeta
    board: Board
    components: tuple[ComponentInstance, ...] = ()
    conductors: tuple[Conductor, ...] = ()
    cuts: tuple[TrackCut, ...] = ()
    #: Parts the design has and the board does not yet — see ``SchematicPart``. Empty on
    #: a board laid out the other way round, part first, which is still a supported way
    #: to work and the only one there used to be.
    parts: tuple[SchematicPart, ...] = ()
    #: Schematic intent, imported from a netlist or drawn on the schematic. Empty until
    #: one or the other has happened. THE ONE ANSWER to what is connected: the sheet's own
    #: geometry below says how a connection was drawn and never what it is.
    nets: tuple[Net, ...] = ()
    #: Sheet cells somebody has chosen for particular symbols — see ``SymbolPlacement``.
    #: Empty on every document the layout has been left to arrange, which is most of them,
    #: and empty is what the file then says by saying nothing. Non-empty, the sheet is
    #: drawn from these and from ``sheet_wires`` rather than laid out.
    sheet: tuple[SymbolPlacement, ...] = ()
    #: Wires somebody drew between two pins. Geometry only -- what is CONNECTED is still
    #: ``nets``, and a wire whose two pins are no longer on one net is simply not drawn.
    sheet_wires: tuple[SheetWire, ...] = ()
    #: Captions and boxes on the drawing. Nothing derives anything from them.
    sheet_notes: tuple[SheetNote, ...] = ()
    #: Mechanical features of the board. They sit on the document rather than on
    #: ``board`` — following ``cuts``, which is the same kind of thing — so that adding
    #: one is its own command and its own undo step instead of a wholesale board
    #: replacement.
    mounting_holes: tuple[MountingHole, ...] = ()
    edge_connectors: tuple[EdgeConnector, ...] = ()
    #: Clear height available above the component side, in mm — the inside of the case
    #: the finished board has to fit, measured from the board surface to whatever is
    #: over it. ``None`` means unconstrained, which is the honest default: most boards
    #: are built before anyone has chosen a box.
    #:
    #: On the document rather than on ``board`` because it is not a property of the
    #: stock you bought — the same 5 x 7 board goes in a slim case one week and a deep
    #: one the next. It is the one constraint in this file that only the third dimension
    #: can check: a part that is too tall looks exactly like a part that is not, from
    #: directly above.
    height_limit_mm: Mm | None = None
    format_version: int = DOCUMENT_FORMAT_VERSION


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def is_solder_trace(c: Conductor) -> bool:
    return c.kind in ("solder-trace", "solder-trace-wired")


def is_wire(c: Conductor) -> bool:
    return c.kind in ("bare-wire", "insulated-wire", "top-jumper")


def is_lead_bend(c: Conductor) -> bool:
    return c.kind == "lead-bend"


def is_crossing_blocked(c: Conductor) -> bool:
    """Conductors occupying the copper plane, which therefore cannot cross one another.

    Insulated wire and top jumpers are excluded: they may pass over.
    """
    return c.kind in ("solder-trace", "solder-trace-wired", "bare-wire", "lead-bend", "strip")


def contacts_every_path_hole(c: Conductor) -> bool:
    """Whether every hole along ``path`` is an electrical contact.

    A solder trace is soldered down at each pad it crosses. A wire is soldered only at
    its two endpoints and merely passes over the holes between. This single distinction
    is the crux of the connectivity engine, and getting it wrong silently produces a
    board that is wired differently from what the screen shows.
    """
    return c.kind in ("solder-trace", "solder-trace-wired", "strip")
