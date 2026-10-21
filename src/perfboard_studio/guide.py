"""The soldering guide (PLAN.md Sec 7, milestone M5).

This is the module the project exists for. Every other part of the engine -- the
connectivity graph, the six conductor kinds, DRC's 0.6 mm proximity rule, LVS's
continuity and isolation lists, the router's own prose explanations -- produces material
that ends up here, turned into something a person can follow with an iron in one hand.

WHAT MAKES IT DIFFERENT FROM "SOLDER R1 HERE".

Three things, and they are the three PLAN.md Sec 3 named as the project's justification:

  IT SAYS WHERE. Every step names holes by address (``R3: C7 -> C11, 4 holes apart``),
  because that is how people talk about perfboard and it is the only unambiguous way to
  say where a part goes. The lead-bend pitch comes out of the same numbers.

  IT SAYS WHICH WAY ROUND. Polarity is read from the registry's own pin NAMES ('+', 'K',
  'A') rather than from a convention about pin 1, because the convention is not uniform:
  an electrolytic's pin 1 is its positive lead, an LED's pin 1 is its anode, and a
  diode's pin 1 is its cathode. Getting this backwards is the single commonest way a
  finished board turns out dead, so it is derived, never assumed.

  IT SAYS HOW TO CHECK. Each phase ends with measurements, and they are DERIVED, not
  generic advice. Continuity comes from the schematic's own nets. Isolation comes from
  DRC: every hole where a solder trace runs 0.6 mm from a different net (rule R5')
  becomes a specific probe -- "measure C7 to C8, must read open". So the risk the tool
  predicted and the measurement the user performs come from the same list, and the
  commonest perfboard failure is caught before the board is finished rather than after
  it does not work.

ORDERING (PLAN.md Sec 7.1). Nine phases, because a board is built in a physical order:
parts go in shortest-first (a tall part fitted early blocks the board from lying flat on
the bench while you solder the short ones), the solder side is done in blocks as each
group is fitted, long wires come after, and the ICs go in last -- heat and ESD.

WHAT IS NOT HERE, said plainly so nobody has to look for it: the picture on each step
card (PLAN.md Sec 7.2). It needs the renderer, so ``ui/view3d.render_step_images`` makes
it -- one per step, shot from the face the work is done on -- and the window, the MCP
server, ``--headless`` and a project save hand it to ``guide_export.guide_to_html``.
Without GL there is no picture, which is why the text steps here are written to stand on
their own. The 1:1 printable sheets (ui/export_pdf.py) are what a builder holds against
the board.

PURE AND DETERMINISTIC: no I/O, no clock, no randomness, no Qt. The same document always
produces the same guide, which is what makes it diffable, testable and safe to generate
from an agent. Rendering to HTML/CSV/JSON lives in guide_export.py; nothing here knows
what the output looks like.
"""

from __future__ import annotations

import colorsys
import dataclasses
import itertools
import math
from dataclasses import dataclass
from typing import Literal

from .breadboard import has_breadboard_pattern, has_rails, is_breadboard
from .connectivity import FootprintLookup, PhysicalPinRef
from .drc import DEFAULT_DRC_OPTIONS, DrcOptions, DrcViolation, run_drc, trace_electrical
from .erc import run_erc
from .footprints import adapter_package, flying_lead_length_mm, standing_pin, wire_entry
from .geometry import (
    all_pin_holes,
    column_label,
    edge_connector_holes,
    entry_side,
    flying_lead_side,
    format_hole,
    hole_to_mm,
    holeless_positions,
    is_inside_board,
    path_length_mm,
    row_label,
    transform_offset,
)
from .lvs import continuity_checks, isolation_checks, run_lvs
from .model import (
    Board,
    BoardMaterial,
    BoardSide,
    BodyArchetype,
    ComponentInstance,
    Conductor,
    ConductorId,
    ConductorKind,
    Footprint,
    FootprintPin,
    HoleCoord,
    Mm,
    Net,
    NetClass,
    PerfDocument,
    Rotation,
    SolderTraceConductor,
    WireConductor,
    contacts_every_path_hole,
    declared_pin_name,
    pin_name_of,
)
from .phrasebook import ENGLISH, GuideLanguage, Phrasebook, phrasebook
from .stripboard import is_stripboard, strip_axis
from .wiregauge import awg_diameter_mm, cut_gauge_awg, fits_hole

# ---------------------------------------------------------------------------
# Phases (PLAN.md Sec 7.1)
# ---------------------------------------------------------------------------

type PhaseNumber = Literal[0, 1, 2, 3, 4, 5, 6, 7, 8]

PHASE_TITLES: dict[PhaseNumber, str] = {
    0: "Preparation",
    1: "Lowest profile",
    2: "IC sockets",
    3: "Small bodies",
    4: "Medium bodies",
    5: "Tall and mechanical",
    6: "Solder side: traces and bare wire",
    7: "Long insulated wires",
    8: "Closing up",
}

PHASE_SUMMARIES: dict[PhaseNumber, str] = {
    0: "Cut the board, mark hole A1, and get the iron and the parts ready.",
    1: (
        "Anything that lies flat: axial resistors and diodes. These go first because a "
        "board with a tall part on it will not sit flat on the bench, and a part that "
        "cannot be pressed down solders at an angle."
    ),
    2: (
        "IC sockets. The ICs themselves go in at the very end -- heat and static are the "
        "two things that kill them, and both are avoidable by fitting them last."
    ),
    3: "Small bodies: ceramic and film capacitors, TO-92 transistors, LEDs.",
    4: "Medium bodies: electrolytics, TO-220 packages, crystals.",
    5: "Tall and mechanical: connectors, terminals, potentiometers, switches, relays.",
    6: (
        "Turn the board over. Solder traces and bare wire, worked one net at a time so "
        "each is finished and checked before the next crosses it."
    ),
    7: "Insulated wire, which may cross anything already on the solder side.",
    8: "Fit the ICs, run the final checks, and power up under current limit.",
}

#: A solderless breadboard is built in the same order, shortest first, with three
#: differences, and these are the phases they change. JUMPERS GO FIRST: a jumper lies flat
#: on the plastic, so it is the lowest thing on the board and nothing then has to be lifted
#: to reach the holes under it -- and a flat jumper may run beneath a part that stands over
#: it. THE ICS GO SECOND, across the groove, because there is no iron for them to fear and
#: they are what the rows around them are counted from. And there is no solder side, so
#: phase 6 is always empty and is not shown.
BREADBOARD_PHASE_TITLES: dict[PhaseNumber, str] = {
    **PHASE_TITLES,
    1: "Jumpers, then what lies flat",
    2: "ICs across the groove",
    7: "Wires to the parts off the board",
    8: "Checks and power",
}

BREADBOARD_PHASE_SUMMARIES: dict[PhaseNumber, str] = {
    **PHASE_SUMMARIES,
    1: (
        "The jumper wires first, laid flat on the plastic and pushed down into their holes, "
        "so nothing has to be lifted later to reach a hole under a part. Then the parts that "
        "lie flat: axial resistors and diodes."
    ),
    2: (
        "The ICs, each straddling the groove down the middle: one row of pins in row e, "
        "the other in row f. Touch something earthed before you pick one up."
    ),
    7: (
        "The wires to the parts off the board: into their holes here first, then to the "
        "parts themselves once they are mounted."
    ),
    8: "Run the final checks, and power up under current limit.",
}

#: Which phase a body goes in on a breadboard: a DIP, or a chip on its adapter, goes in
#: whole in phase 2 -- there is no socket to fit first. Everything else as on perfboard.
BREADBOARD_PHASE_BY_ARCHETYPE: dict[BodyArchetype, PhaseNumber] = {
    "dip": 2,
    "smd-adapter": 2,
}

#: How much of each end of a breadboard jumper is stripped: the bare end is what goes into
#: the clip, so it is the whole leg. A quarter of an inch, what the pre-cut kits are made
#: with, and enough to reach the clip under a 0.3 inch moulding.
BREADBOARD_STRIP_MM: Mm = 6.0

#: Which phase each kind of body belongs in. Ordered by how tall it stands, because that
#: is what decides whether the board still lies flat while the next part is soldered.
PHASE_BY_ARCHETYPE: dict[BodyArchetype, PhaseNumber] = {
    "axial-cylinder": 1,
    "dip": 2,
    "disc-ceramic": 3,
    "box-film": 3,
    "to92": 3,
    "led-round": 3,
    "radial-electrolytic": 4,
    "to220": 4,
    "crystal-hc49": 4,
    "pin-header": 5,
    "screw-terminal": 5,
    "potentiometer": 5,
    "tactile-switch": 5,
    "relay-box": 5,
    "generic-box": 5,
    "box-header": 5,
    "screw-terminal-vertical": 5,
    "module-board": 5,
    # It goes in as the DIP it stands in for: a socket in phase 2 if there is one, and the
    # chip -- already on its adapter -- with the other ICs at the end.
    "smd-adapter": 2,
    # The wires to a part off the board are long insulated wires, and go in with them: after
    # every part is down, so they are not in the way of the iron, and before the closing
    # checks, which power the board up through the very jack and switch they reach.
    "flying-leads": 7,
    # Stood on end, a resistor is as tall as an LED and a diode as a TO-92: the small
    # bodies, not the flat ones it would go in with lying down.
    "axial-upright": 3,
}

#: Conductor kinds done on the solder side in phase 6, and in phase 7.
PHASE_BY_CONDUCTOR: dict[ConductorKind, PhaseNumber] = {
    "lead-bend": 6,
    "solder-trace": 6,
    "solder-trace-wired": 6,
    "bare-wire": 6,
    "strip": 6,
    "insulated-wire": 7,
    "top-jumper": 7,
}

# ---------------------------------------------------------------------------
# Physical constants and conventions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IronSettings:
    """What to set the iron to, and how long a pad may be held.

    Material-dependent and not a preference. FR-2 phenolic paper -- the cheap brown
    "pertinaks" most perfboard sold in Turkey is made of -- lifts pads under sustained
    heat far more readily than FR-4, which is the same fact PLAN.md Sec 5.2 R5'' turns
    into a DRC warning.
    """

    temperature_c: int
    max_dwell_s: float
    note: str


IRON_BY_MATERIAL: dict[BoardMaterial, IronSettings] = {
    "FR4": IronSettings(
        temperature_c=350,
        max_dwell_s=3.0,
        note="FR-4 tolerates heat well; the limit here is the component, not the board.",
    ),
    "FR2": IronSettings(
        temperature_c=320,
        max_dwell_s=2.0,
        note=(
            "Phenolic paper board. Its pads lift easily -- work in short touches, let a "
            "pad cool before returning to it, and never drag heat along a long run in one "
            "pass."
        ),
    ),
    "FR1": IronSettings(
        temperature_c=320,
        max_dwell_s=2.0,
        note=(
            "Phenolic paper board. Its pads lift easily -- work in short touches, let a "
            "pad cool before returning to it, and never drag heat along a long run in one "
            "pass."
        ),
    ),
}

#: Insulation colour by net class, the convention every schematic reader already knows.
COLOR_BY_NET_CLASS: dict[NetClass, str] = {"power": "red", "ground": "black"}

#: Signal colours, cycled by net order so the same board always assigns the same colours.
SIGNAL_COLORS: tuple[str, ...] = (
    "yellow", "green", "blue", "white", "orange", "violet", "grey", "brown",
)

#: What a BARE wire's "colour" is: the metal, named as a spine's material is named. The
#: net's insulation colour belongs to insulation, and a bare wire has none -- "black AWG 24"
#: for a ground run of bare wire is a reel nobody owns.
BARE_WIRE_COLOUR = "tinned copper"

#: Every colour the guide can name, as ink: what a wire of that colour looks like on paper.
#: The stocked hookup-wire colours (``COLOR_BY_NET_CLASS`` and ``SIGNAL_COLORS``) and bare
#: wire's metal. Two consumers: ``stocked_colour`` measures a document's own colour against
#: the stocked ones, and the wire templates are drawn in it (``guide_export``).
WIRE_INK: dict[str, str] = {
    "red": "#d32f2f", "black": "#212121", "yellow": "#f2c418", "green": "#2e9d4f",
    "blue": "#1e6fd9", "white": "#f7f7f7", "orange": "#f07a18", "violet": "#8b4fd1",
    "grey": "#8d8d8d", "brown": "#7b4a23", BARE_WIRE_COLOUR: "#a9abae",
}

#: Other spellings of a stocked colour that a document may hold.
_COLOUR_ALIASES: dict[str, str] = {"gray": "grey", "purple": "violet"}


def stocked_colour(stored: str | None) -> str | None:
    """The hookup-wire colour a wire's OWN colour (``WireConductor.color``) asks for, or
    None when it has none and the net's convention decides.

    The document may hold a name ("red") or a hex ("#1e6fd9") -- the 2D view reads either,
    through ``QColor``. A stocked name is itself. A hex is the stocked colour it would be
    CALLED (:func:`_named_hue`), because the cut list is read at the bench, where "#1e6fd9"
    is no reel anybody owns and "blue" is. Any other word is printed as it was written:
    somebody chose it, and a guess at what "pink" should be instead would be the guide
    overruling the board. A ``#`` that is no colour at all is no choice either, and the
    convention decides, as it does in both views.
    """
    if not stored or not stored.strip():
        return None
    word = stored.strip()
    name = _COLOUR_ALIASES.get(word.lower(), word.lower())
    if name in WIRE_INK and name != BARE_WIRE_COLOUR:
        return name
    if not word.startswith("#"):
        return word
    rgb = _hex_rgb(word)
    return None if rgb is None else _named_hue(rgb)


def _hex_rgb(value: str) -> tuple[int, int, int] | None:
    """``#rrggbb`` or ``#rgb`` as three bytes, or None for anything else."""
    digits = value[1:] if value.startswith("#") else ""
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    if len(digits) != 6:
        return None
    try:
        return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
    except ValueError:
        return None


#: Where each hue ends, in degrees, going round from red. Wire is sold in a handful of
#: colours, so this is a question of what a colour is CALLED, and that is its hue: the
#: nearest stocked ink by RGB distance named CSS orange (#ffa500) "yellow".
_HUE_NAMES: tuple[tuple[float, str], ...] = (
    (15, "red"), (42, "orange"), (70, "yellow"), (170, "green"), (255, "blue"),
    (340, "violet"), (360, "red"),
)


def _named_hue(rgb: tuple[int, int, int]) -> str:
    """The stocked wire colour a colour would be called: black, grey or white when it has
    too little colour to have a hue, brown when it is a dark orange, else by its hue.
    Every ink in ``WIRE_INK`` comes back as its own name; a test holds that."""
    hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
    if value < 0.2:
        return "black"
    if saturation < 0.2:
        return "white" if value > 0.85 else "black" if value < 0.3 else "grey"
    degrees = hue * 360
    if 15 <= degrees < 42 and value < 0.7:
        return "brown"
    return next(name for end, name in _HUE_NAMES if degrees < end)


@dataclass(frozen=True, slots=True)
class GuideOptions:
    """Everything the guide's arithmetic needs that is not in the document."""

    #: Added at each end of a wire for the bend around the board edge, in mm.
    bend_allowance_mm: Mm = 3.0
    #: Insulation stripped at each end, in mm.
    strip_length_mm: Mm = 5.0
    #: Solder traces at least this many pads long get an end-to-end resistance check.
    #: Short traces are not worth probing: the expected value is below what a hand
    #: multimeter resolves, so a "measurement" would be a ritual rather than a test.
    resistance_check_min_pads: int = 5
    #: Tolerance band quoted with a computed resistance, as a fraction. Wide on purpose:
    #: the buildup estimate is a fillet-volume guess, and a check nobody can pass is worse
    #: than no check.
    resistance_tolerance: float = 0.5
    #: One count on the lowest range of the meter this guide asks the reader to bring --
    #: "a multimeter with a continuity buzzer" (see :func:`_tools`). A hand DMM's 200 ohm
    #: range resolves 0.1 ohm, and that is the number that decides which of the two
    #: resistance checks below a run gets.
    #:
    #: WHY THIS EXISTS. A pad count alone decided it, and the pad count was the wrong
    #: question: every resistance checkpoint the four shipped example boards produce comes
    #: out between 5.1 and 6.4 milliohms, a band ten to forty times BELOW one count of the
    #: instrument the same guide told the reader to fetch. So the tool printed "about
    #: 6.4 mohm (accept 3.2-9.6)" and hedged with "use four-wire mode if your meter has
    #: it" -- a step nobody following the guide could carry out, in the list that is the
    #: whole reason this application exists. A verification step that cannot be performed
    #: does not merely fail to help; it is what teaches somebody to stop trusting the
    #: other thirty-eight.
    meter_resolution_ohm: float = 0.1
    #: Cap on isolation pairs carried into the guide, matching lvs.isolation_checks.
    isolation_cap: int = 40
    drc: DrcOptions = DEFAULT_DRC_OPTIONS
    #: The language every sentence of the guide is written in (``phrasebook``). English by
    #: default, and English is the guide it always was, word for word -- which is what the
    #: guide golden holds it to.
    language: GuideLanguage = "en"


DEFAULT_GUIDE_OPTIONS = GuideOptions()


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PartStep:
    """Fit one component."""

    kind: Literal["part"]
    component_id: str
    ref: str
    value: str
    footprint_name: str
    archetype: BodyArchetype
    anchor: HoleCoord
    #: Pin number -> hole, in footprint pin order.
    pin_holes: tuple[tuple[str, HoleCoord], ...]
    #: "C7 -> C11, 4 holes apart", or just the hole for a single-pin part.
    span: str
    #: Lead pitch to bend to, for a part whose two leads sit in line. None otherwise.
    bend_template_mm: Mm | None
    rotation: Rotation
    mirrored: bool
    height_mm: Mm
    #: "Cathode (banded end) at D12" -- None when the part is symmetrical.
    polarity: str | None
    notes: tuple[str, ...]

    @property
    def title(self) -> str:
        value = f" {self.value}" if self.value else ""
        return f"{self.ref}{value} — {self.span}"


@dataclass(frozen=True, slots=True)
class RiskNote:
    """One R5' proximity risk: a place where solder can bridge to the wrong net."""

    hole: HoleCoord
    neighbour: HoleCoord
    message: str


@dataclass(frozen=True, slots=True)
class WireCut:
    """One length of wire to cut, for the cut list (PLAN.md Sec 7.3)."""

    conductor_id: ConductorId
    net_name: str
    from_hole: HoleCoord
    to_hole: HoleCoord
    #: Routed path length on the board.
    path_mm: Mm
    #: What to cut: path + both bends through the board + both stripped ends.
    cut_mm: Mm
    strip_mm: Mm
    awg: int
    #: Spelled the way the CSV header, the HTML table and the JSON key all spell it.
    #: One field, one spelling: the JSON key is this field's name.
    colour: str
    insulated: bool


@dataclass(frozen=True, slots=True)
class LeadCut:
    """One wire from a pad on the board to a part that is not on it (``flying-leads``).

    Its own list rather than a ``WireCut``, because a ``WireCut`` is a conductor with two
    holes and a path between them, and this has one hole and one lug: what joins the two is
    the wire itself, which is why the document holds no conductor for it.
    """

    component_id: str
    ref: str
    pin: str
    #: What the part calls that lead, when it says: "W", "T", "+".
    pin_name: str | None
    hole: HoleCoord
    net_name: str
    #: What to cut, when the footprint says (``wire-3-l150``). ``None`` is "cut to fit": how
    #: far it is to the panel is a fact about the enclosure, and a guessed number in a cut list
    #: is worse than none.
    cut_mm: Mm | None
    strip_mm: Mm
    awg: int
    colour: str


@dataclass(frozen=True, slots=True)
class TrackCutJob:
    """One track to break, for a stripboard build.

    These come FIRST, before a single part goes in, and not as a matter of taste: the cut
    is drilled through the hole from the copper side, and once a part is sitting over that
    hole there is no way to get a bit to it. A board where three cuts were forgotten is a
    board that comes apart again.

    ``separates`` names the two holes either side of the cut, which is what the isolation
    check in phase 0 measures between -- the only way to confirm a cut worked without
    holding it up to the light.
    """

    at: HoleCoord
    #: "row 3" or "column D", in the same words the board's own addresses use.
    strip: str
    separates: tuple[HoleCoord, HoleCoord] | None


@dataclass(frozen=True, slots=True)
class SpineCut:
    """One length of tinned wire laid along a solder trace as its spine."""

    conductor_id: ConductorId
    net_name: str
    pads: int
    length_mm: Mm
    gauge_mm: Mm
    material: str


@dataclass(frozen=True, slots=True)
class ConductorStep:
    """Make one connection."""

    kind: Literal["conductor"]
    conductor_id: ConductorId
    conductor_kind: ConductorKind
    #: The face it lies on. A wire's cut-and-bend template is drawn as seen from there
    #: (:func:`wire_template`), because a bent wire turned over is its own mirror image.
    side: BoardSide
    net_name: str
    net_class: NetClass
    #: "B12 -> K12, 10 pads" for a trace; "B3 -> P9" for a wire.
    span: str
    #: Every hole a trace crosses; a wire's two ends and the corners it bends round.
    path: tuple[HoleCoord, ...]
    #: The pads it is soldered to: every one along a trace, the two ends of a wire.
    pads: int
    length_mm: Mm
    #: Traces only: the electrical summary quoted back as an expectation.
    resistance_ohm: float | None
    drop_mv: float | None
    loss_mw: float | None
    spine: SpineCut | None
    cut: WireCut | None
    risks: tuple[RiskNote, ...]
    notes: tuple[str, ...]

    @property
    def title(self) -> str:
        return f"{self.net_name}: {self.span}"


type GuideStep = PartStep | ConductorStep


# ---------------------------------------------------------------------------
# Checkpoints -- the differentiator (PLAN.md Sec 7.5)
# ---------------------------------------------------------------------------

type CheckKind = Literal[
    "continuity",  # these two points must be joined
    "isolation",  # these two points must NOT be joined
    "resistance",  # this run should measure about this much
    "polarity",  # look at it before power
    "power-on",  # the procedure itself
]


@dataclass(frozen=True, slots=True)
class Checkpoint:
    kind: CheckKind
    title: str
    instruction: str
    expected: str
    #: Where to put the probes, when the check is a measurement.
    holes: tuple[HoleCoord, ...] = ()
    pins: tuple[PhysicalPinRef, ...] = ()
    #: True for checks that must pass before power is applied. Rendered as a hard gate.
    blocking: bool = False


# ---------------------------------------------------------------------------
# The guide
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BomLine:
    ref_designators: tuple[str, ...]
    value: str
    footprint_name: str
    quantity: int

    @property
    def refs(self) -> str:
        return ", ".join(self.ref_designators)


@dataclass(frozen=True, slots=True)
class GuidePhase:
    number: PhaseNumber
    title: str
    summary: str
    steps: tuple[GuideStep, ...]
    checkpoints: tuple[Checkpoint, ...]

    @property
    def is_empty(self) -> bool:
        return not self.steps and not self.checkpoints


@dataclass(frozen=True, slots=True)
class GuideWarning:
    """Something the guide could not do, said out loud rather than omitted.

    A build guide that quietly leaves out the connections it could not describe is worse
    than no guide: the user follows it to the end and has a board that does not work,
    with nothing to say which part was never covered.
    """

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Guide:
    board: Board
    document_name: str
    phases: tuple[GuidePhase, ...]
    bom: tuple[BomLine, ...]
    cut_list: tuple[WireCut, ...]
    spine_list: tuple[SpineCut, ...]
    #: Stripboard only, and empty on every other board: the tracks to break before
    #: anything is soldered.
    track_cuts: tuple[TrackCutJob, ...]
    #: None on a breadboard with nothing to solder -- see build_guide.
    iron: IronSettings | None
    tools: tuple[str, ...]
    warnings: tuple[GuideWarning, ...]
    #: Counts, for a summary line and for tests that care about coverage.
    part_steps: int
    conductor_steps: int
    checkpoint_count: int
    #: What every sentence above is written in. Carried so that an exporter writes its own
    #: words -- headings, table columns, the tags beside a step -- in the same language as
    #: the guide it is given, without being told twice.
    language: GuideLanguage = "en"
    #: The wires to the parts that are not on the board, one per lead. Empty on a board with
    #: none, and left out of every export then, so every guide written before there were any
    #: is what it was.
    lead_list: tuple[LeadCut, ...] = ()

    @property
    def total_steps(self) -> int:
        return self.part_steps + self.conductor_steps


# ---------------------------------------------------------------------------
# Building it
# ---------------------------------------------------------------------------


def build_guide(
    doc: PerfDocument,
    lookup: FootprintLookup,
    options: GuideOptions = DEFAULT_GUIDE_OPTIONS,
) -> Guide:
    """Turn a finished board into something someone can build from.

    Works on whatever the document has. A board with no netlist still gets part and
    conductor steps; it just cannot get continuity checks, because those are derived from
    schematic intent and there is none. Every such gap is reported in ``warnings`` rather
    than silently producing a shorter guide.
    """
    say = phrasebook(options.language)
    violations = run_drc(doc, lookup, options.drc)
    nets_by_id: dict[str, Net] = {net.id: net for net in doc.nets}
    color_by_net = net_colours(doc)

    part_steps = _part_steps(doc, lookup, violations, options, say)
    conductor_steps, cut_list, spine_list = _conductor_steps(
        doc, nets_by_id, color_by_net, violations, options, say
    )
    lead_list = _lead_cuts(doc, lookup, color_by_net, options, say)
    # A part off the board is wired after the copper, so a net reaching it is not finished
    # until its wires are in -- and a continuity check asked for before then fails for a
    # reason that is not a fault.
    #
    # On a breadboard EVERY part goes in after the copper -- the jumpers are phase 1 -- so
    # every part is late in that sense, and a check on a net waits for the parts it probes.
    # Only there: on perfboard the parts come first and the goldens hold that.
    breadboard = is_breadboard(doc.board)
    late_parts = {
        step.ref: phase
        for step, phase in part_steps
        if breadboard or step.archetype == "flying-leads"
    }

    adapters = _adapters(doc, lookup)
    titles = BREADBOARD_PHASE_TITLES if breadboard else PHASE_TITLES
    by_phase: dict[PhaseNumber, list[GuideStep]] = {n: [] for n in PHASE_TITLES}
    # The jumpers ahead of the flat parts that share phase 1 with them on a breadboard,
    # which is the whole reason they are in it.
    ordered: list[tuple[GuideStep, PhaseNumber]] = (
        [*conductor_steps, *part_steps] if breadboard else [*part_steps, *conductor_steps]
    )
    for step_in_order, step_phase in ordered:
        by_phase[step_phase].append(step_in_order)

    checkpoints = _checkpoints(
        doc, lookup, violations, conductor_steps, options, say, late_parts
    )
    track_cuts = _track_cuts(doc, say)
    checkpoints[0].extend(_cut_checks(track_cuts, say, board=doc.board))

    phases = tuple(
        GuidePhase(
            number=number,
            title=say(titles[number]),
            summary=_phase_summary(
                number, doc, say, off_board=bool(lead_list), adapters=adapters
            ),
            steps=tuple(by_phase[number]),
            checkpoints=tuple(checkpoints.get(number, ())),
        )
        for number in sorted(PHASE_TITLES)
    )

    # A breadboard is not soldered -- unless a chip has to go onto its adapter first, and
    # an adapter is an FR-4 board like any other.
    iron: IronSettings | None = (
        None if breadboard and not adapters else IRON_BY_MATERIAL[doc.board.material]
    )
    all_checks = sum(len(phase.checkpoints) for phase in phases)
    return Guide(
        board=doc.board,
        document_name=doc.meta.name,
        phases=phases,
        bom=_bom(doc, lookup, say),
        cut_list=tuple(cut_list),
        spine_list=tuple(spine_list),
        track_cuts=track_cuts,
        iron=None if iron is None else dataclasses.replace(iron, note=say(iron.note)),
        tools=_tools(doc, cut_list, spine_list, say, lead_list, adapters),
        warnings=_warnings(doc, lookup, violations, say),
        part_steps=len(part_steps),
        conductor_steps=len(conductor_steps),
        checkpoint_count=all_checks,
        language=options.language,
        lead_list=tuple(lead_list),
    )


def _adapters(doc: PerfDocument, lookup: FootprintLookup) -> tuple[tuple[str, str, int], ...]:
    """Every chip on a DIP adapter, as (reference, package, header pins), by reference."""
    found: list[tuple[str, str, int]] = []
    for component in doc.components:
        footprint = lookup(component.footprint_id)
        package = adapter_package(footprint) if footprint is not None else None
        if footprint is not None and package is not None:
            found.append((component.ref, package, len(footprint.pins)))
    return tuple(sorted(found))


def _phase_summary(
    number: PhaseNumber,
    doc: PerfDocument,
    say: Phrasebook,
    off_board: bool = False,
    adapters: tuple[tuple[str, str, int], ...] = (),
) -> str:
    """The phase's standing summary, with what the BOARD changes about it folded in.

    Phase 7 gains a sentence when parts off the board are wired in it (``off_board``).
    Phase 0 varies for a reason worth stating: every hole
    address in this guide is counted from a corner unless the board says otherwise, so
    "mark hole A1" is the step the whole document depends on. A board that prints its own
    A..Z / 01..NN legend has already done it, and telling somebody to mark a corner that
    is already labelled is how a guide starts feeling like it was not written for the
    board in front of them.
    """
    if is_breadboard(doc.board):
        return _breadboard_phase_summary(number, doc, say, adapters)
    if number == 7 and off_board:
        return say(PHASE_SUMMARIES[7]) + " " + say(
            "Then the wires to the parts off the board: into their pads here first, then "
            "to the parts themselves once they are mounted."
        )
    if number != 0:
        return say(PHASE_SUMMARIES[number])

    board = doc.board
    # A solderable breadboard comes at its size with every address printed on it, so there
    # is nothing to cut and no corner to mark -- only which way up to lay it, the same
    # sentence the solderless breadboard's guide opens on.
    pattern = has_breadboard_pattern(board)
    parts: list[str] = [] if pattern else [say("Cut the board")]
    if doc.mounting_holes:
        count = len(doc.mounting_holes)
        sizes = ", ".join(f"{d:g} mm" for d in sorted({m.diameter for m in doc.mounting_holes}))
        where = ", ".join(
            format_hole(m.at, board)
            for m in sorted(doc.mounting_holes, key=lambda m: (m.at.row, m.at.col))
        )
        # Parenthesised rather than run on with a dash: this clause sits inside a comma
        # list, and a second comma list beside it reads as one long ambiguous string.
        if count == 1:
            parts.append(
                say("drill the {count} mounting hole ({sizes} at {where})",
                    count=count, sizes=sizes, where=where)
            )
        else:
            parts.append(
                say("drill the {count} mounting holes ({sizes} at {where})",
                    count=count, sizes=sizes, where=where)
            )
    if not pattern:
        if board.labels is None:
            parts.append(say("mark hole A1"))
        else:
            parts.append(say("check which corner the board's printed A1 is in"))
    parts.append(say("get the iron and the parts ready"))

    if len(parts) > 1:
        summary = say("{items}, and {last}.", items=", ".join(parts[:-1]), last=parts[-1])
    else:
        summary = parts[0] + "."
    summary = summary[0].upper() + summary[1:]
    if pattern:
        summary = say(
            "Lay the board down with column 1 on the left and row j at the top: every "
            "address in this guide is printed on it, row letter first — e12 is row e, "
            "column 12."
        ) + " " + summary

    if doc.mounting_holes:
        # Its own sentence, because it is an instruction about ORDER rather than another
        # thing to do: swarf brushes off a bare board and digs out of a finished one, and
        # a board that still has to go in a vice should not have parts on it yet.
        summary += " " + say(
            "Drill before anything is soldered — the board can still go in a vice, and "
            "swarf brushes off a bare board instead of having to be picked out of a built one."
        )

    if adapters:
        # Here and not at the part's own step, which is in phase 2: soldering a 1.27 mm
        # pitch chip wants a clear bench and the finest tip, and a bridge between two of
        # its legs can only be seen and fixed while the adapter is still loose in the hand.
        summary += " " + say(
            "Solder the surface-mount chips onto their adapters first: {chips}. Line each "
            "chip's pin-1 dot up with the adapter's pin 1, tack one corner leg, check it "
            "is square, then do the rest with plenty of flux — and look along every leg "
            "under a magnifier for a bridge. Once the adapter is on the board, nobody can "
            "reach those legs.",
            chips=say.joined([
                say("{ref} ({package})", ref=ref, package=package)
                for ref, package, _ in adapters
            ]),
        )

    if board.pad_shape == "oblong" and board.pad_length is not None:
        row, column = say("along a row"), say("down a column")
        along = row if board.pad_axis == "horizontal" else column
        across = column if board.pad_axis == "horizontal" else row
        summary += " " + say(
            "This board's pads are oblong ({length:g} × {width:g} mm), so neighbouring pads "
            "{along} nearly touch while pads {across} are well clear. Solder flows between "
            "them far more easily in the first direction than the second — which is what "
            "makes the traces below quick, and what makes an accidental bridge {along} quick "
            "too.",
            length=board.pad_length,
            width=board.pad_diameter,
            along=along,
            across=across,
        )
    return summary


def _breadboard_phase_summary(
    number: PhaseNumber,
    doc: PerfDocument,
    say: Phrasebook,
    adapters: tuple[tuple[str, str, int], ...],
) -> str:
    """A breadboard's phase summary. Phase 0 is about which way round to lay it: every
    address in the guide is the one printed on the board, and they only match the board
    in front of you if it is the right way up."""
    if number != 0:
        return say(BREADBOARD_PHASE_SUMMARIES[number])
    summary = say(
        "Lay the breadboard down with column 1 on the left and row j at the top: every "
        "address in this guide is printed on it, row letter first — e12 is row e, "
        "column 12. Then get the parts ready."
    )
    if has_rails(doc.board):
        summary += " " + say(
            "On some boards each rail is broken in the middle — a gap in its red or blue "
            "line. If yours is, bridge the two halves of every rail with a short jumper "
            "before anything else."
        )
    if adapters:
        summary += " " + say(
            "Solder the surface-mount chips onto their adapters first: {chips}. Line each "
            "chip's pin-1 dot up with the adapter's pin 1, tack one corner leg, check it "
            "is square, then do the rest with plenty of flux — and look along every leg "
            "under a magnifier for a bridge. Once the adapter is on the board, nobody can "
            "reach those legs.",
            chips=say.joined([
                say("{ref} ({package})", ref=ref, package=package)
                for ref, package, _ in adapters
            ]),
        )
    return summary


# -- parts ------------------------------------------------------------------


def _part_steps(
    doc: PerfDocument,
    lookup: FootprintLookup,
    violations: list[DrcViolation],
    options: GuideOptions,
    say: Phrasebook,
) -> list[tuple[PartStep, PhaseNumber]]:
    """One step per placed component, in build order.

    Within a phase, shortest first and then by reference: the height rule is the one that
    matters physically, and the reference is what makes the order stable rather than
    dependent on document order.
    """
    extra_notes = _part_notes_from_drc(doc, violations, say)
    colours = net_colours(doc)
    net_by_pin = {(node.component_ref, node.pin): net for net in doc.nets for node in net.nodes}
    entries: list[tuple[PhaseNumber, Mm, str, PartStep]] = []
    for component in doc.components:
        footprint = lookup(component.footprint_id)
        if footprint is None:
            continue  # Reported as a warning; nothing can be said about where it goes.
        wires = {
            pin.number: (net.name, colours.get(net.id, "grey"))
            for pin in footprint.pins
            if (net := net_by_pin.get((component.ref, pin.number))) is not None
        }
        step = _part_step(
            component,
            footprint,
            doc.board,
            doc.height_limit_mm,
            extra_notes.get(component.id, ()),
            say,
            strip_mm=options.strip_length_mm,
            wires=wires,
        )
        phase = PHASE_BY_ARCHETYPE.get(footprint.body.archetype, 5)
        if is_breadboard(doc.board):
            phase = BREADBOARD_PHASE_BY_ARCHETYPE.get(footprint.body.archetype, phase)
        entries.append((phase, footprint.body_height, component.ref, step))

    entries.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
    return [(step, phase) for phase, _height, _ref, step in entries]


def _part_notes_from_drc(
    doc: PerfDocument, violations: list[DrcViolation], say: Phrasebook
) -> dict[str, tuple[str, ...]]:
    """The DRC findings that change how a part is FITTED, moved onto that part's step.

    Only the two that are instructions rather than complaints. Everything else DRC says
    is about the design and belongs in the warning list, not in the middle of a step
    somebody is following with an iron in their hand.
    """
    ref_by_id = {component.id: component.ref for component in doc.components}
    # A conductor id ("cond-7") is not something anybody at the bench can look up. Every
    # other line of the guide names copper by where it RUNS, so this one does too.
    path_by_id = {conductor.id: conductor.path for conductor in doc.conductors}
    notes: dict[str, list[str]] = {}

    for violation in violations:
        if violation.rule == "jumper-under-body" and violation.component_ids:
            wheres = [
                _conductor_where(path_by_id.get(conductor_id), say, board=doc.board)
                for conductor_id in violation.conductor_ids
            ]
            if is_breadboard(doc.board):
                # Every jumper on a breadboard is in phase 1 already; what is worth saying
                # is only that this part stands over one.
                note = say(
                    "The jumpers {wheres} run underneath this part. They went in first, in "
                    "phase 1; check they are pressed down flat before this goes over them.",
                    wheres=say.joined(wheres),
                )
            elif len(wheres) > 1:
                note = say(
                    "The top jumpers {wheres} run underneath this part, so they have to be "
                    "soldered first — they are in phase 1 for that reason. Check they are "
                    "down and lying flat before this goes in.",
                    wheres=say.joined(wheres),
                )
            else:
                note = say(
                    "The top jumper {where} runs underneath this part, so it has to be "
                    "soldered first — it is in phase 1 for that reason. Check it is down "
                    "and lying flat before this goes in.",
                    where=say.joined(wheres),
                )
            notes.setdefault(violation.component_ids[0], []).append(note)
        elif violation.rule == "heat-proximity" and len(violation.component_ids) == 2:
            source_ref = ref_by_id.get(violation.component_ids[0], say("the part next to it"))
            # On the part that suffers, not the one that gets hot: this is advice about
            # which capacitor to reach for, and it is only useful while fitting that one.
            notes.setdefault(violation.component_ids[1], []).append(
                say(
                    "{source} runs hot and sits close by. Fit a 105 °C-rated part here if you "
                    "have one — an 85 °C electrolytic beside a heatsink is the first thing on "
                    "the board to dry out.",
                    source=source_ref,
                )
            )

    return {component_id: tuple(lines) for component_id, lines in notes.items()}


def _conductor_where(path: tuple[HoleCoord, ...] | None, say: Phrasebook, *, board: Board | None) -> str:
    """A conductor named by its ends, for a message a person reads holding the board."""
    if not path:
        return say("on this board")
    return say("from {start} to {end}", start=format_hole(path[0], board), end=format_hole(path[-1], board))


def _part_step(
    component: ComponentInstance,
    footprint: Footprint,
    board: Board,
    height_limit_mm: Mm | None = None,
    extra_notes: tuple[str, ...] = (),
    say: Phrasebook = ENGLISH,
    strip_mm: Mm = 5.0,
    wires: dict[str, tuple[str, str]] | None = None,
) -> PartStep:
    holes = all_pin_holes(component, footprint)
    pin_holes = tuple((pin.number, at) for pin, at in holes)

    notes: list[str] = []
    off_board = footprint.body.archetype == "flying-leads"
    if off_board:
        notes.extend(
            _flying_lead_notes(component, footprint, holes, board, strip_mm, say, wires or {})
        )
    breadboard = is_breadboard(board)
    if breadboard and footprint.body.archetype in ("dip", "smd-adapter"):
        # No socket and no iron: the chip goes straight in, and what goes wrong is a leg
        # folded under the body instead of into its hole.
        first = min(holes, key=lambda held: (held[0].number != "1", held[0].number))[1]
        notes.append(say(
            "Across the groove, pin 1 in {hole}. Line both rows of legs up over their holes "
            "and press the body down evenly, so that no leg folds under it.",
            hole=format_hole(first, board),
        ))
    elif footprint.body.archetype == "dip":
        # The old wording told the reader to "leave it until phase 8", which is where the
        # IC goes in but is not where this step is: PHASE_BY_ARCHETYPE puts a DIP in phase
        # 2, the SOCKET phase. Say which of the two things happens now and which does not.
        notes.append(say(
            "Fit a socket here if you have one — this phase is the sockets. The IC "
            "itself does not go in until the closing checks in phase 8, socket or no "
            "socket: it is the last thing on the board that should meet an iron."
        ))
    package = adapter_package(footprint)
    if package is not None and breadboard:
        notes.append(say(
            "A {package} on its DIP adapter, which should already carry the chip (phase 0). "
            "From here on it is a DIP.",
            package=package,
        ))
    elif package is not None:
        # The chip went onto its adapter in phase 0 (``_phase_summary``); what is left is the
        # header, which is where an adapter goes crooked, and then it is a DIP like any other.
        notes.append(say(
            "A {package} on its DIP adapter, which should already carry the chip (phase 0). "
            "Solder the header pins to the adapter with their long ends pushed into a "
            "breadboard or into these holes, so they come out square and the right distance "
            "apart. From here on it is a DIP: fit a socket here if you have one, and the "
            "adapter itself goes in with the other ICs in phase 8.",
            package=package,
        ))
    stood = standing_pin(footprint)
    if stood is not None:
        notes.append(_standing_note(component, footprint, holes, stood, board, say))
    if component.mirrored and not breadboard:
        notes.append(say(
            "This part is mirrored: it goes in from the SOLDER side, not the component "
            "side. Check the pin order against the board before soldering."
        ))
    facing = wire_entry(footprint)
    if facing is not None:
        # A terminal block is the one part that goes in the same holes either way round and
        # is still wrong one way: its wires enter through one face, and a mouth soldered
        # facing the wrong way is a terminal nothing can be screwed into. Said in board
        # terms, from the same direction DRC and the placer turn with the part.
        side = entry_side(
            transform_offset(facing[0], facing[1], component.rotation, component.mirrored)
        )
        notes.append(say(
            "The wire entries face the {side} edge of the board — the screws on top, the "
            "openings towards the {side}. Check before pushing it in: it fits the holes "
            "either way round.",
            side=say(side),
        ) if breadboard else say(
            "The wire entries face the {side} edge of the board — the screws on top, the "
            "openings towards the {side}. Check before soldering: it fits the holes either "
            "way round.",
            side=say(side),
        ))
    if footprint.body.archetype == "screw-terminal-vertical":
        notes.append(say(
            "The wires go in from ABOVE: this is the header, and the screw plug is pushed "
            "down into it. Keep the space over it clear for the plug and a screwdriver."
        ))
    if footprint.body.archetype == "module-board" and breadboard:
        notes.append(say(
            "It plugs straight into the breadboard on its own pins: check its orientation "
            "against the pin names, line every pin up over its hole and press it down "
            "evenly."
        ))
    elif footprint.body.archetype == "module-board":
        seat = footprint.body.dims.get("seat", 0.0)
        if seat >= 5.0:
            notes.append(say(
                "Solder the female header strips here, not the module: it plugs in last, "
                "after the power-up checks, and can come out again. Seat each strip square "
                "on the board before soldering its end pins."
            ))
        else:
            notes.append(say(
                "Soldered straight in on its own pins, so it cannot come out again without "
                "desoldering every pin: check its orientation against the pin names first."
            ))
    if height_limit_mm is not None and footprint.body_height > height_limit_mm:
        notes.append(say(
            "{height:g} mm tall, and this build has {limit:g} mm of room. It will not fit "
            "as it stands — lay it down or swap it before you push it in.",
            height=footprint.body_height,
            limit=height_limit_mm,
        ) if breadboard else say(
            "{height:g} mm tall, and this build has {limit:g} mm of room. It will not fit "
            "as it stands — lay it down or swap it before you solder it in.",
            height=footprint.body_height,
            limit=height_limit_mm,
        ))
    elif footprint.body_height >= 10 and not off_board:
        # The guess, kept only for a board that has not said what it has to fit inside.
        # Once there is a real number the real number wins.
        notes.append(say(
            "{height:.0f} mm tall — check it clears anything meant to go over the board "
            "before you push it in.",
            height=footprint.body_height,
        ) if breadboard else say(
            "{height:.0f} mm tall — check it clears anything meant to go over the board "
            "before you solder it down.",
            height=footprint.body_height,
        ))
    notes.extend(extra_notes)

    return PartStep(
        kind="part",
        component_id=component.id,
        ref=component.ref,
        value=component.value,
        footprint_name=say.footprint(footprint.name),
        archetype=footprint.body.archetype,
        anchor=component.anchor,
        pin_holes=pin_holes,
        span=_wires_span(pin_holes, say, board=board) if off_board else _span_of(pin_holes, say, board=board),
        # Two pads in a row are not two leads to bend: the wires are cut, not formed. A part
        # stood on end is bent back over itself, which its own note says, not to a pitch.
        bend_template_mm=(
            None if off_board or stood is not None else _bend_template(pin_holes, board)
        ),
        rotation=component.rotation,
        mirrored=component.mirrored,
        height_mm=footprint.body_height,
        polarity=_polarity_note(footprint, pin_holes, component, say, board=board),
        notes=tuple(notes),
    )


def lead_marker(ref: str, pin: str, name: str | None) -> str:
    """What is written on a wire to a part off the board, where it leaves: "RV1·2", "J1·T".

    The marker a harness wire carries, and the same text in both views. The part's own name
    for the lead when it has one, its number otherwise; ids rather than words, so it is the
    same in every language.
    """
    return f"{ref}·{name or pin}"


def lead_end(ref: str, pin: str, name: str | None, say: Phrasebook = ENGLISH) -> str:
    """The far end of a wire to a part off the board: "RV1 pin 2", "RV1 pin 2 (W)".

    One phrasing for the step, the cut list and the HTML table, so the wire somebody cut
    from the list is named the way the step they are following names it.
    """
    if name:
        return say("{ref} pin {pin} ({name})", ref=ref, pin=pin, name=name)
    return say("{ref} pin {pin}", ref=ref, pin=pin)


def _flying_lead_notes(
    component: ComponentInstance,
    footprint: Footprint,
    holes: list[tuple[FootprintPin, HoleCoord]],
    board: Board,
    strip_mm: Mm,
    say: Phrasebook,
    wires: dict[str, tuple[str, str]],
) -> list[str]:
    """What fitting a part that is not on the board means: wires, and where each one goes.

    Pad by pad, because the one mistake this step can make is two wires swapped -- a pot
    that turns the wrong way, a jack with tip and sleeve crossed -- and it looks exactly
    right from the board. Each lead is named by what the part calls it when it says, and
    each wire by its net and the colour the cut list gives it (``wires``: pin -> net name,
    colour), which is the thing in the hand at the bench.
    """
    side = flying_lead_side([at for _pin, at in holes], board)
    notes = [
        say(
            "{ref} is not on this board: it is mounted off it, on the panel or in the "
            "enclosure, and these pads are where its wires land. Solder a wire into each pad "
            "from the component side and lead them all out over the {side} edge.",
            ref=component.ref,
            side=say(side),
        )
    ]
    pairs = []
    for pin, at in holes:
        lead = lead_end(component.ref, pin.number, pin_name_of(component, pin), say)
        wire = wires.get(pin.number)
        if wire is None:
            pairs.append(say("{hole} to {lead}", hole=format_hole(at, board), lead=lead))
        else:
            pairs.append(say(
                "{hole} to {lead} — {net}, {colour} wire",
                hole=format_hole(at, board),
                lead=lead,
                net=wire[0],
                colour=say(wire[1]),
            ))
    notes.append(say("Wire by wire: {pairs}.", pairs="; ".join(pairs)))
    length = flying_lead_length_mm(footprint)
    if length is not None:
        notes.append(say(
            "Cut each wire {length:g} mm and strip {strip:g} mm at both ends.",
            length=length,
            strip=strip_mm,
        ))
    else:
        notes.append(say(
            "Cut each wire long enough to reach {ref} where it is mounted, with enough slack "
            "to open the enclosure, and strip {strip:g} mm at both ends.",
            ref=component.ref,
            strip=strip_mm,
        ))
    return notes


def _wires_span(pin_holes: tuple[tuple[str, HoleCoord], ...], say: Phrasebook, *, board: Board | None) -> str:
    """Where the wires to a part off the board land: their row, and how many there are.

    Not ``_span_of``: "B16 → A16, 1 hole apart" is the pitch to bend two leads to, and these
    are wires, cut rather than bent.
    """
    if len(pin_holes) == 1:
        return say("{hole}, 1 wire", hole=format_hole(pin_holes[0][1], board))
    return say(
        "{start} → {end}, {count} wires",
        start=format_hole(pin_holes[0][1], board),
        end=format_hole(pin_holes[-1][1], board),
        count=len(pin_holes),
    )


def _span_of(pin_holes: tuple[tuple[str, HoleCoord], ...], say: Phrasebook = ENGLISH, *, board: Board | None) -> str:
    """Where the part sits, in the form that is useful for THAT part.

    Two leads get "C7 → C11, 4 holes apart", which is a thing you can set a pair of
    pliers to. A DIP gets the rectangle it occupies and its pin count, because pin 1 to
    pin 8 is a diagonal and "3 holes apart" would be a true statement that helps nobody.
    """
    if not pin_holes:
        return say("no pins")
    if len(pin_holes) == 1:
        return format_hole(pin_holes[0][1], board)

    cols = [at.col for _n, at in pin_holes]
    rows = [at.row for _n, at in pin_holes]
    if len(pin_holes) == 2:
        first, last = pin_holes[0][1], pin_holes[1][1]
        steps = max(max(cols) - min(cols), max(rows) - min(rows))
        if steps == 1:
            return say(
                "{start} → {end}, 1 hole apart",
                start=format_hole(first, board), end=format_hole(last, board),
            )
        return say(
            "{start} → {end}, {steps} holes apart",
            start=format_hole(first, board), end=format_hole(last, board), steps=steps,
        )

    corner_a = HoleCoord(min(cols), min(rows))
    corner_b = HoleCoord(max(cols), max(rows))
    pin_one = dict(pin_holes).get("1")
    if pin_one is None:
        return say(
            "{start} → {end}, {count} pins",
            start=format_hole(corner_a, board), end=format_hole(corner_b, board), count=len(pin_holes),
        )
    return say(
        "{start} → {end}, {count} pins with pin 1 at {hole}",
        start=format_hole(corner_a, board), end=format_hole(corner_b, board), count=len(pin_holes),
        hole=format_hole(pin_one, board),
    )


def _standing_note(
    component: ComponentInstance,
    footprint: Footprint,
    holes: list[tuple[FootprintPin, HoleCoord]],
    stood: FootprintPin,
    board: Board,
    say: Phrasebook,
) -> str:
    """How to fit an axial part stood on end: over which hole, and -- for a diode -- which
    end up. The banded end is the cathode, found by NAME as ``_polarity_note`` finds it and
    by pin 1 only for a polarised part nobody named, the registry's and KiCad's convention.
    Said as which end is up because that is what a hand holding the part can check; the
    cathode's own hole is in the polarity line beside it."""
    over = format_hole(next(at for pin, at in holes if pin.number == stood.number), board)
    other = next(
        (format_hole(at, board) for pin, at in holes if pin.number != stood.number), over
    )
    names = {pin.number: pin_name_of(component, pin) for pin in footprint.pins}
    cathode = next((number for number, name in names.items() if name == "K"), None)
    if cathode is None and "A" in names.values():
        cathode = next((number for number, name in names.items() if name != "A"), None)
    if cathode is None and footprint.polarized:
        cathode = "1"
    if cathode is None:
        return say(
            "Stand it on end over {hole} and bend the top lead back over and down into "
            "{other}.",
            hole=over,
            other=other,
        )
    if cathode == stood.number:
        return say(
            "Stand it on end over {hole}, the banded end down, and bend the top lead back "
            "over and down into {other}.",
            hole=over,
            other=other,
        )
    return say(
        "Stand it on end over {hole}, the banded end up, and bend the top lead back over "
        "and down into {other}.",
        hole=over,
        other=other,
    )


def _bend_template(pin_holes: tuple[tuple[str, HoleCoord], ...], board: Board) -> Mm | None:
    """The pitch to bend an axial part's leads to, in mm.

    Only for two-lead parts in a straight line -- the case where "bend the leads to
    10.16 mm" is a thing you can do with a pair of pliers and a ruler. A three-pin
    transistor has a fixed lead spread and nothing to bend to.
    """
    if len(pin_holes) != 2:
        return None
    a, b = pin_holes[0][1], pin_holes[1][1]
    if a.col != b.col and a.row != b.row:
        return None
    steps = abs(a.col - b.col) + abs(a.row - b.row)
    return steps * board.pitch if steps else None


#: Pin names the registry uses where the meaning is not obvious, mapped to what to say.
#: Read from the NAME, never inferred from pin 1: an electrolytic's pin 1 is '+', an
#: LED's pin 1 is 'A' (the anode), and a diode's pin 1 is its cathode. One convention
#: cannot cover all three, and guessing wrong here is what makes a finished board dead.
_PIN_NAME_MEANING: dict[str, str] = {
    "+": "Positive (long) lead",
    # Parenthesised, not dashed: _polarity_note appends " in <hole>" to each of these,
    # and a trailing dashed clause swallowed the address ("...printed stripe in Y3").
    "-": "Negative lead (the side with the printed stripe)",
    "A": "Anode (long lead)",
    "K": "Cathode (short lead, flat on the rim)",
}


#: What a three-legged part's declared lead names mean, for the orientation note. Only
#: ever read from names the PART declared -- the registry has none of these, which is the
#: whole reason a TO-92 used to get "check the package outline" and nothing better.
_LEAD_NAME_MEANING: dict[str, str] = {
    "G": "gate",
    "D": "drain",
    "S": "source",
    "B": "base",
    "C": "collector",
    "E": "emitter",
}


def _polarity_note(
    footprint: Footprint,
    pin_holes: tuple[tuple[str, HoleCoord], ...],
    component: ComponentInstance | None = None,
    say: Phrasebook = ENGLISH, *, board: Board | None,
) -> str | None:
    """How to orient this part, in words, or None if it does not matter.

    Names come from ``model.pin_name_of``: the part's own declared name first, the
    footprint's second -- so a diode on an unpolarised footprint whose leads were named K
    and A is oriented by the names like any other.
    """
    by_number = dict(pin_holes)

    named = []
    off_board = footprint.body.archetype == "flying-leads"
    for pin in footprint.pins:
        name = pin_name_of(component, pin)
        if name in _PIN_NAME_MEANING and pin.number in by_number:
            lead_said = say(_PIN_NAME_MEANING[name])
            where = format_hole(by_number[pin.number], board)
            if off_board:
                # Off the board the lead is not IN the hole -- the wire to it is.
                named.append(say("{lead}: the wire in {hole}", lead=lead_said, hole=where))
            else:
                named.append(say("{lead} in {hole}", lead=lead_said, hole=where))
    if named:
        return "; ".join(named)
    if off_board:
        return None

    if footprint.body.archetype in ("to92", "to220") and component is not None:
        # A three-legged package says nothing about which leg is which; the PART may.
        # When it has named every leg, that IS the orientation, leg by leg -- the one
        # instruction a TO-92 could never be given before, and the one mistake (base and
        # emitter swapped) that looks exactly right until the power is on.
        legs: list[str] = []
        for pin in footprint.pins:
            name = declared_pin_name(component, pin.number)
            hole = by_number.get(pin.number)
            if name is None or hole is None:
                legs = []
                break
            meaning = _LEAD_NAME_MEANING.get(name)
            said = f"{name} ({say(meaning)})" if meaning else name
            legs.append(say("{lead} in {hole}", lead=said, hole=format_hole(hole, board)))
        if legs:
            return say("{legs} — check against the part's datasheet", legs="; ".join(legs))

    if footprint.body.archetype == "dip":
        first = by_number.get("1")
        if first is None:
            return None
        return say(
            "Pin 1 (the notched end, marked with a dot) in {hole}", hole=format_hole(first, board)
        )

    if footprint.body.archetype == "smd-adapter":
        # Two marks to line up, not one: the chip's dot on the adapter's pin 1 was the
        # phase-0 job; this is the adapter's own "1" on the board's hole.
        first = by_number.get("1")
        if first is None:
            return None
        return say(
            "Pin 1 (the adapter's \"1\", beside the chip's dot) in {hole}",
            hole=format_hole(first, board),
        )

    if footprint.body.archetype == "box-header":
        # The shroud goes on one way round only as far as the CABLE is concerned: soldered
        # in turned half round, it takes the socket upside down and every pin lands on its
        # neighbour across the row. The key slot is in the wall beside pin 1's row.
        first = by_number.get("1")
        if first is not None:
            return say(
                "Key slot on the side of the pin-1 row; pin 1 in {hole} "
                "(the cable's red stripe goes to pin 1)",
                hole=format_hole(first, board),
            )

    if footprint.polarized:
        # Unnamed but polarized: a diode, where pin 1 is the cathode by the convention
        # this registry and KiCad's DO-41 both follow.
        first = by_number.get("1")
        if first is not None:
            return say("Cathode — the banded end — in {hole}", hole=format_hole(first, board))

    if footprint.body.archetype in ("to92", "to220"):
        first = by_number.get("1")
        if first is not None:
            return say(
                "Pin 1 in {hole}; check the package outline against the board",
                hole=format_hole(first, board),
            )
    return None


# -- conductors -------------------------------------------------------------


def _conductor_steps(
    doc: PerfDocument,
    nets_by_id: dict[str, Net],
    color_by_net: dict[str, str],
    violations: list[DrcViolation],
    options: GuideOptions,
    say: Phrasebook,
) -> tuple[list[tuple[ConductorStep, PhaseNumber]], list[WireCut], list[SpineCut]]:
    """One step per conductor, grouped by net and ordered ground, power, then signal.

    The same criticality order the router works in (PLAN.md Sec 6.2), for the same
    reason turned around: the rails are the connections everything else is measured
    against, so they want to exist and be verified first.
    """
    risks_by_conductor = _risks_by_conductor(violations, say, board=doc.board)
    trapped = trapped_jumper_ids(violations)
    class_order: dict[NetClass, int] = {"ground": 0, "power": 1, "signal": 2}

    entries: list[tuple[PhaseNumber, int, str, str, ConductorStep]] = []
    cut_list: list[WireCut] = []
    spine_list: list[SpineCut] = []

    for conductor in doc.conductors:
        net = nets_by_id.get(conductor.net_id) if conductor.net_id else None
        net_name = net.name if net is not None else say("(unassigned)")
        net_class: NetClass = net.net_class if net is not None else "signal"
        current_a = net.current_a if net is not None else None

        step = _conductor_step(
            conductor,
            doc.board,
            net_name,
            net_class,
            current_a,
            color_by_net.get(conductor.net_id or "", "grey"),
            risks_by_conductor.get(conductor.id, ()),
            options,
            say,
        )
        if step.cut is not None:
            cut_list.append(step.cut)
        if step.spine is not None:
            spine_list.append(step.spine)

        phase = PHASE_BY_CONDUCTOR.get(conductor.kind, 6)
        if is_breadboard(doc.board):
            phase = 1  # Flat on the plastic before any part: see BREADBOARD_PHASE_TITLES.
        elif conductor.id in trapped:
            # A top jumper normally goes in at phase 7, soldered to pins that are already
            # fitted. One that runs UNDER a part cannot: by phase 7 the part is on the
            # board and the wire has nowhere to go. So the ones DRC flagged move to phase
            # 1, which is where PLAN.md Sec 7.1 puts top-side jumpers in the first place,
            # and the rest stay where soldering to a fitted pin is easier.
            phase = 1
        entries.append((phase, class_order[net_class], net_name, conductor.id, step))

    entries.sort(key=lambda entry: (entry[0], entry[1], entry[2], entry[3]))
    return (
        [(step, phase) for phase, _order, _name, _id, step in entries],
        cut_list,
        spine_list,
    )


def _conductor_step(
    conductor: Conductor,
    board: Board,
    net_name: str,
    net_class: NetClass,
    current_a: float | None,
    color: str,
    risks: tuple[RiskNote, ...],
    options: GuideOptions,
    say: Phrasebook,
) -> ConductorStep:
    path = conductor.path
    # The pads it is SOLDERED to. A trace is joined at every hole it crosses; a wire only at
    # its two ends, and the points between are where it bends. Counting those as pads told
    # the builder a wire laid along the grid had "3 pads" or "4 pads" -- joints nobody
    # should make, on a wire that would then short whatever it lay across.
    pads = len(path) if contacts_every_path_hole(conductor) else min(len(path), 2)
    length_mm = path_length_mm(path, board)
    notes: list[str] = []

    resistance = drop_mv = loss_mw = None
    spine: SpineCut | None = None
    cut: WireCut | None = None

    if isinstance(conductor, SolderTraceConductor):
        electrical = trace_electrical(conductor, board, current_a, options.drc)
        resistance = electrical.resistance_ohm
        drop_mv = electrical.drop_v * 1000 if electrical.drop_v is not None else None
        loss_mw = electrical.loss_w * 1000 if electrical.loss_w is not None else None
        if conductor.spine is not None:
            spine = SpineCut(
                conductor_id=conductor.id,
                net_name=net_name,
                pads=pads,
                length_mm=length_mm,
                gauge_mm=conductor.spine.gauge,
                material=conductor.spine.material.replace("-", " "),
            )
            notes.append(say(
                "Lay the {gauge} mm {material} along the pads first and solder it at each "
                "one. Work in one direction and do not go back over a section that has "
                "cooled.",
                gauge=conductor.spine.gauge,
                material=say(spine.material),
            ))
        elif pads >= 3:
            notes.append(say(
                "Consider laying a lead offcut along these pads as a spine rather than "
                "building the run out of solder alone: it drops the resistance by roughly "
                "an order of magnitude and is far easier to make repeatable."
            ))
        # Tinning applies to every run; the flux sentence says "on a run this long" and
        # was appended to two-pad joints as well. Same threshold as the spine suggestion
        # above, so one run is either long or it is not.
        notes.append(say("Tin each pad lightly first, then join them."))
        if pads >= 3:
            notes.append(say("Flux is not optional on a run this long."))
    elif conductor.kind in ("bare-wire", "insulated-wire", "top-jumper"):
        insulated = conductor.kind != "bare-wire"
        stored_awg = conductor.gauge_awg if isinstance(conductor, WireConductor) else None
        # The wire's own colour, if the document gives it one, before the net's convention:
        # the 2D and 3D views already draw it, and a cut list that named another colour
        # had the builder cutting black for a wire the screen showed blue.
        stored_colour = conductor.color if isinstance(conductor, WireConductor) else None
        cut = _wire_cut(
            conductor.id,
            net_name,
            path,
            board,
            current_a,
            stored_awg,
            stocked_colour(stored_colour) or color,
            insulated,
            options,
        )
        if not fits_hole(cut.awg, board.drill_diameter):
            # DRC's wire-too-thick-for-hole says the same thing, from the same function; it
            # is repeated at the step because this is where the builder has the wire in hand.
            notes.append(say(
                "AWG {awg} is {copper:.2f} mm of copper and will not go through this board's "
                "{drill:g} mm holes. Lap-solder each end onto the face of its pad instead of "
                "passing it through.",
                awg=cut.awg,
                copper=awg_diameter_mm(cut.awg),
                drill=board.drill_diameter,
            ))
        if is_breadboard(board):
            notes.append(say(
                "Strip {strip:g} mm off each end, bend both ends straight down and push them "
                "into their holes until the insulation meets the plastic.",
                strip=cut.strip_mm,
            ))
        elif conductor.kind == "top-jumper":
            notes.append(say(
                "This one runs over the COMPONENT side, not the solder side. Keep it clear "
                "of anything that has to be reachable later."
            ))
        if conductor.kind == "bare-wire":
            notes.append(say(
                "Bare wire: it must not touch any other conductor along its length. Keep it "
                "flat against the board and check it against the neighbouring runs."
            ))
    elif conductor.kind == "lead-bend":
        notes.append(say(
            "No extra wire: bend the component's own lead over to reach the second hole, "
            "and solder both ends."
        ))

    return ConductorStep(
        kind="conductor",
        conductor_id=conductor.id,
        conductor_kind=conductor.kind,
        side=conductor.side,
        net_name=net_name,
        net_class=net_class,
        span=_conductor_span(conductor.kind, path, pads, say, board=board),
        path=path,
        pads=pads,
        length_mm=length_mm,
        resistance_ohm=resistance,
        drop_mv=drop_mv,
        loss_mw=loss_mw,
        spine=spine,
        cut=cut,
        risks=risks,
        notes=tuple(notes),
    )


def _conductor_span(
    kind: ConductorKind, path: tuple[HoleCoord, ...], pads: int, say: Phrasebook, *, board: Board | None
) -> str:
    if not path:
        return say("(empty path)")
    ends = f"{format_hole(path[0], board)} → {format_hole(path[-1], board)}"
    if kind in ("solder-trace", "solder-trace-wired", "strip"):
        return say("{ends}, {pads} pads", ends=ends, pads=pads)
    return ends


def _wire_cut(
    conductor_id: ConductorId,
    net_name: str,
    path: tuple[HoleCoord, ...],
    board: Board,
    current_a: float | None,
    stored_awg: int | None,
    colour: str,
    insulated: bool,
    options: GuideOptions,
) -> WireCut:
    """Cut length, per PLAN.md Sec 7.3.

    ``path + 2 x (board thickness + bend allowance) + 2 x strip length``. The board
    thickness is in there because the wire goes THROUGH the board at each end and has to
    turn over on the far side; leaving it out is how a cut list produces wires that are
    each 4 mm too short.
    """
    path_mm = path_length_mm(path, board)
    # Bare wire is not stripped, because there is nothing on it to strip. Charging it the
    # allowance anyway would pad every bare run by a centimetre.
    strip_mm = options.strip_length_mm if insulated else 0.0
    ends = 2 * (board.thickness + options.bend_allowance_mm) + 2 * strip_mm
    if is_breadboard(board):
        # A breadboard jumper does not go THROUGH anything: its stripped ends bend down
        # into the clips and that is the whole of them, so the wire is the path and two
        # legs -- not the path, two board thicknesses and two bends.
        strip_mm = BREADBOARD_STRIP_MM
        ends = 2 * strip_mm
    # The gauge the document names, if it names one; otherwise the one the current asks
    # for. Before this read the document, a wire stored as AWG 18 was printed as AWG 24.
    awg = cut_gauge_awg(stored_awg, current_a, options.drc.max_wire_current_density_a_per_mm2)
    return WireCut(
        conductor_id=conductor_id,
        net_name=net_name,
        from_hole=path[0],
        to_hole=path[-1],
        path_mm=path_mm,
        cut_mm=path_mm + ends,
        strip_mm=strip_mm,
        awg=awg,
        # The net's colour is an INSULATION colour, so it goes only where there is some.
        colour=colour if insulated else BARE_WIRE_COLOUR,
        insulated=insulated,
    )


def _lead_cuts(
    doc: PerfDocument,
    lookup: FootprintLookup,
    color_by_net: dict[str, str],
    options: GuideOptions,
    say: Phrasebook,
) -> list[LeadCut]:
    """One wire per lead of every part off the board, in the order their steps come.

    Gauge and colour are the answers every other wire on the board gets, from the same two
    places: the net's declared current through ``cut_gauge_awg``, and the net's colour --
    so the wire from the ground lug of a jack is black like every ground wire on the board.
    """
    net_by_pin: dict[tuple[str, str], Net] = {
        (node.component_ref, node.pin): net for net in doc.nets for node in net.nodes
    }
    density = options.drc.max_wire_current_density_a_per_mm2
    cuts: list[LeadCut] = []
    for component in sorted(doc.components, key=lambda c: c.ref):
        footprint = lookup(component.footprint_id)
        if footprint is None or footprint.body.archetype != "flying-leads":
            continue
        length = flying_lead_length_mm(footprint)
        for pin, at in all_pin_holes(component, footprint):
            net = net_by_pin.get((component.ref, pin.number))
            cuts.append(
                LeadCut(
                    component_id=component.id,
                    ref=component.ref,
                    pin=pin.number,
                    pin_name=pin_name_of(component, pin),
                    hole=at,
                    net_name=net.name if net is not None else say("(unassigned)"),
                    cut_mm=length,
                    strip_mm=options.strip_length_mm,
                    awg=cut_gauge_awg(None, net.current_a if net is not None else None, density),
                    colour=color_by_net.get(net.id, "grey") if net is not None else "grey",
                )
            )
    return cuts


# ---------------------------------------------------------------------------
# Wire templates: a wire's shape at 1:1, to cut, mark and bend it on
# ---------------------------------------------------------------------------

#: The widest a template is drawn, in mm: an A4 page less its print margins. A shape wider
#: than this is turned a quarter. No stock board (``geometry.STANDARD_PRESETS``, 9 x 15 cm
#: at most) has a wire too long for the page both ways, nor one that straightened is wider
#: than this -- so neither case is handled beyond the turn.
TEMPLATE_PAGE_WIDTH_MM: Mm = 180.0

#: Paper round a template's drawing, in mm, so its end holes have neighbours to count from.
TEMPLATE_MARGIN_MM: Mm = 3.0

#: What to do at a mark on a wire laid out straight: cut the insulation (``strip``), bend
#: it 90° down THROUGH the board at an end hole, or TURN it along the board at a corner.
type WireMarkKind = Literal["strip", "through", "turn"]


@dataclass(frozen=True, slots=True)
class WireMark:
    """One mark on a wire laid out straight, measured from its first tip."""

    at_mm: Mm
    kind: WireMarkKind


@dataclass(frozen=True, slots=True)
class WireTemplate:
    """A wire step's wire, laid out flat at 1:1, in millimetres on paper.

    ``shape`` runs tip, end hole, every corner, end hole, tip, with (0, 0) at the top left
    of ``width_mm`` x ``height_mm``. The two legs carry straight on from the path's end
    segments: bend them 90° down at the end holes and the rest stays flat on the board.
    Tip to tip it is the cut list's ``cut_mm`` exactly, because each leg IS the part of the
    cut that is not path -- through the board, turned over, stripped -- so the drawing and
    the number in the table cannot disagree.

    Drawn as seen from the face the wire lies on: a bent wire turned over is its own mirror
    image, and from the solder side the board is the mirror image of the component side.

    ``marks`` are the same wire straightened, which is what is cut and marked with a ruler
    before anything is bent -- read off the same points the shape is drawn from, so the
    two drawings of one wire cannot disagree about where it bends.
    """

    shape: tuple[tuple[Mm, Mm], ...]
    #: Indexes into ``shape`` where the wire bends: both end holes and every real corner.
    #: A point the path passes straight through is not a bend and gets no ring.
    bends: tuple[int, ...]
    #: The board's holes under the drawing, so a corner can be counted against them.
    holes: tuple[tuple[Mm, Mm], ...]
    width_mm: Mm
    height_mm: Mm
    marks: tuple[WireMark, ...]
    length_mm: Mm
    strip_mm: Mm
    seen_from: BoardSide
    #: Turned a quarter to fit the page (``TEMPLATE_PAGE_WIDTH_MM``) -- a turn, never a
    #: flip, so the bends still go the way they go on the board.
    turned: bool


def wire_template(step: ConductorStep, board: Board) -> WireTemplate | None:
    """The 1:1 pattern a wire step's wire is cut and bent to, or None for a step with no
    wire to cut (a solder trace, a lead bend)."""
    cut = step.cut
    if cut is None:
        return None
    # A hole repeated in a hand-edited path is a segment of no length and no direction.
    holes = [hole for hole, _ in itertools.groupby(step.path)]
    if len(holes) < 2:
        return None
    mirror = -1.0 if step.side == "bottom" else 1.0

    def on_paper(at: HoleCoord) -> tuple[Mm, Mm]:
        centre = hole_to_mm(at, board)
        return mirror * centre.x, centre.y

    path = [on_paper(at) for at in holes]
    leg = (cut.cut_mm - cut.path_mm) / 2

    def tip(end: tuple[Mm, Mm], inner: tuple[Mm, Mm]) -> tuple[Mm, Mm]:
        dx, dy = end[0] - inner[0], end[1] - inner[1]
        run = math.hypot(dx, dy)
        return end[0] + dx / run * leg, end[1] + dy / run * leg

    shape = [tip(path[0], path[1]), *path, tip(path[-1], path[-2])]
    along = [0.0]
    for a, b in itertools.pairwise(shape):
        along.append(along[-1] + math.dist(a, b))
    corners = [
        index
        for index in range(2, len(shape) - 2)
        if not _runs_straight_on(shape[index - 1], shape[index], shape[index + 1])
    ]
    bends = (1, *corners, len(shape) - 2)
    marks = [
        WireMark(along[index], "through" if index in (1, len(shape) - 2) else "turn")
        for index in bends
    ]
    if cut.strip_mm > 0:
        marks = [
            WireMark(cut.strip_mm, "strip"),
            *marks,
            WireMark(along[-1] - cut.strip_mm, "strip"),
        ]

    # The holes under the drawing: those within reach of the path, legs and margin
    # included, rather than every hole on the board for every wire.
    reach = math.ceil((leg + TEMPLATE_MARGIN_MM) / board.pitch)
    cols = [at.col for at in holes]
    rows = [at.row for at in holes]
    col_range = range(max(min(cols) - reach, 0), min(max(cols) + reach, board.cols - 1) + 1)
    row_range = range(max(min(rows) - reach, 0), min(max(rows) + reach, board.rows - 1) + 1)
    grid = [on_paper(HoleCoord(col, row)) for col in col_range for row in row_range]

    xs, ys = [x for x, _ in shape], [y for _, y in shape]
    wide, high = max(xs) - min(xs), max(ys) - min(ys)
    turned = wide > TEMPLATE_PAGE_WIDTH_MM and high < wide
    if turned:
        # A quarter turn on paper, (x, y) -> (-y, x): a rotation, never a reflection.
        shape = [(-y, x) for x, y in shape]
        grid = [(-y, x) for x, y in grid]
    m = TEMPLATE_MARGIN_MM
    left = min(x for x, _ in shape) - m
    top = min(y for _, y in shape) - m
    right = max(x for x, _ in shape) + m
    bottom = max(y for _, y in shape) + m
    return WireTemplate(
        shape=tuple((x - left, y - top) for x, y in shape),
        bends=bends,
        holes=tuple(
            (x - left, y - top) for x, y in grid if left < x < right and top < y < bottom
        ),
        width_mm=right - left,
        height_mm=bottom - top,
        marks=tuple(marks),
        length_mm=along[-1],
        strip_mm=cut.strip_mm,
        seen_from=step.side,
        turned=turned,
    )


def _runs_straight_on(a: tuple[Mm, Mm], b: tuple[Mm, Mm], c: tuple[Mm, Mm]) -> bool:
    """Whether a path passes straight through ``b`` -- a point somebody clicked on a
    straight run, which is not a bend and must not be marked as one."""
    cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
    forward = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
    return abs(cross) < 1e-9 and forward > 0


def net_colours(doc: PerfDocument) -> dict[str, str]:
    """Insulation colour per net id, by NAME: red for power, black for ground, then a cycle.

    Assigned by net order in the document so the same board always produces the same cut
    list -- a colour convention that changed between two runs would be worse than none. The
    cut list, the guide's steps and the board view's wire tooltips all read this, so the
    colour a wire is called on the screen is the colour it is called at the bench.
    """
    colors: dict[str, str] = {}
    signal_index = 0
    for net in doc.nets:
        fixed = COLOR_BY_NET_CLASS.get(net.net_class)
        if fixed is not None:
            colors[net.id] = fixed
        else:
            colors[net.id] = SIGNAL_COLORS[signal_index % len(SIGNAL_COLORS)]
            signal_index += 1
    return colors


def trapped_jumper_ids(violations: list[DrcViolation]) -> frozenset[ConductorId]:
    """Top jumpers DRC found running under a part, read off the rule rather than
    recomputed.

    Public because both the phase order and the part-step note need the same answer, and
    a guide that worked it out its own way would eventually schedule a jumper for after
    the part it has to go under while printing a note saying it must come first.
    """
    return frozenset(
        conductor_id
        for violation in violations
        if violation.rule == "jumper-under-body"
        for conductor_id in violation.conductor_ids
    )


def _risks_by_conductor(
    violations: list[DrcViolation], say: Phrasebook, *, board: Board | None
) -> dict[ConductorId, tuple[RiskNote, ...]]:
    """R5' proximity warnings, indexed by the trace that causes them.

    This is the join that makes PLAN.md Sec 7.5 work: the risk DRC predicts and the
    measurement the user performs come from one list, so they cannot drift apart.
    """
    by_conductor: dict[ConductorId, list[RiskNote]] = {}
    for violation in violations:
        if violation.rule != "solder-trace-proximity" or len(violation.holes) < 2:
            continue
        for conductor_id in violation.conductor_ids:
            by_conductor.setdefault(conductor_id, []).append(
                RiskNote(
                    hole=violation.holes[0],
                    neighbour=violation.holes[1],
                    message=say(
                        "{hole} sits about one pad gap from {neighbour}, which is on another "
                        "net. Do not let solder run across.",
                        hole=format_hole(violation.holes[0], board),
                        neighbour=format_hole(violation.holes[1], board),
                    ),
                )
            )
    return {key: tuple(value) for key, value in by_conductor.items()}


# -- checkpoints ------------------------------------------------------------


def _track_cuts(doc: PerfDocument, say: Phrasebook) -> tuple[TrackCutJob, ...]:
    """Every track to break, in reading order.

    Sorted by where they are rather than by when they were made, because they are done in
    one pass with the board on the bench and a drill bit in hand -- an order that follows
    the addresses is one that can be checked off without hunting.
    """
    if not is_stripboard(doc.board):
        return ()

    horizontal = strip_axis(doc.board) == "horizontal"
    jobs: list[TrackCutJob] = []
    for cut in sorted(doc.cuts, key=lambda c: (c.at.row, c.at.col)):
        if not is_inside_board(cut.at, doc.board):
            continue
        neighbours = (
            (HoleCoord(cut.at.col - 1, cut.at.row), HoleCoord(cut.at.col + 1, cut.at.row))
            if horizontal
            else (HoleCoord(cut.at.col, cut.at.row - 1), HoleCoord(cut.at.col, cut.at.row + 1))
        )
        on_board = all(is_inside_board(hole, doc.board) for hole in neighbours)
        jobs.append(
            TrackCutJob(
                at=cut.at,
                strip=(
                    say("row {label}", label=row_label(cut.at.row))
                    if horizontal
                    else say("column {label}", label=column_label(cut.at.col))
                ),
                separates=neighbours if on_board else None,
            )
        )
    return tuple(jobs)


def _cut_checks(cuts: tuple[TrackCutJob, ...], say: Phrasebook, *, board: Board | None) -> list[Checkpoint]:
    """One isolation probe per cut, before anything is soldered.

    Blocking, and the only checks in this guide that can be made on a bare board. A cut
    that did not go all the way through looks exactly like one that did -- the copper is
    0.035 mm thick and the swarf sits in the hole -- so the meter is the only way to know,
    and it is far cheaper to know now than after forty joints.
    """
    checks: list[Checkpoint] = []
    for cut in cuts:
        if cut.separates is None:
            continue
        left, right = cut.separates
        checks.append(
            Checkpoint(
                kind="isolation",
                title=say(
                    "{a} ↔ {b} must be open", a=format_hole(left, board), b=format_hole(right, board)
                ),
                instruction=say(
                    "After cutting the track at {cut}, measure resistance between {a} and {b}.",
                    cut=format_hole(cut.at, board), a=format_hole(left, board), b=format_hole(right, board),
                ),
                expected=say(
                    "Open circuit. Anything below a few hundred kΩ means copper is still "
                    "bridging the cut — clear it before soldering anything."
                ),
                holes=(left, right),
                blocking=True,
            )
        )
    return checks


def _checkpoints(
    doc: PerfDocument,
    lookup: FootprintLookup,
    violations: list[DrcViolation],
    conductor_steps: list[tuple[ConductorStep, PhaseNumber]],
    options: GuideOptions,
    say: Phrasebook,
    late_parts: dict[str, PhaseNumber] | None = None,
) -> dict[PhaseNumber, list[Checkpoint]]:
    """Every measurement, attached to the phase after which it can be made.

    A continuity check goes with the phase that finishes its net -- checking earlier
    would fail for a reason that is not a fault, and checking later buries the fault
    among a dozen others. Working out which phase that is is the only interesting part.
    """
    checks: dict[PhaseNumber, list[Checkpoint]] = {n: [] for n in PHASE_TITLES}

    # Isolation, from the R5' risks: each becomes a probe right after its trace is made.
    for step, phase in conductor_steps:
        for risk in step.risks:
            checks[phase].append(
                Checkpoint(
                    kind="isolation",
                    title=say(
                        "{a} ↔ {b} must be open",
                        a=format_hole(risk.hole, doc.board), b=format_hole(risk.neighbour, doc.board),
                    ),
                    instruction=say(
                        "With the trace for {net} finished, measure resistance between {a} "
                        "and {b}.",
                        net=step.net_name,
                        a=format_hole(risk.hole, doc.board),
                        b=format_hole(risk.neighbour, doc.board),
                    ),
                    expected=say(
                        "Open circuit. Any reading at all means solder has bridged them."
                    ),
                    holes=(risk.hole, risk.neighbour),
                )
            )

    # Continuity, from the schematic. Each goes with the phase that completes its net.
    last_phase_for_net = _last_phase_by_net(conductor_steps)
    for check in continuity_checks(doc):
        closing_phase = last_phase_for_net.get(check.net_name)
        if closing_phase is None:
            continue  # Nothing on the board builds this net; the LVS warning covers it.
        # A part wired in after the copper finishes the net itself (``late_parts``).
        for ref in (check.a.component_ref, check.b.component_ref):
            late = (late_parts or {}).get(ref)
            if late is not None and late > closing_phase:
                closing_phase = late
        checks[closing_phase].append(
            Checkpoint(
                kind="continuity",
                title=f"{check.a.component_ref}.{check.a.pin} ↔ {check.b.component_ref}.{check.b.pin}",
                instruction=say(
                    "Probe {a} and {b}.",
                    a=_pin_phrase(doc, check.a.component_ref, check.a.pin, say),
                    b=_pin_phrase(doc, check.b.component_ref, check.b.pin, say),
                ),
                expected=say(
                    "Continuous — they are both on net {net}.", net=check.net_name
                ),
                pins=(check.a, check.b),
            )
        )

    # End-to-end resistance on the long runs: catches a cold joint or a crack, which
    # continuity alone will happily read through.
    for step, phase in conductor_steps:
        if step.resistance_ohm is None or step.pads < options.resistance_check_min_pads:
            continue
        checks[phase].append(_resistance_check(step, options, say, board=doc.board))

    checks[8].extend(_closing_checks(doc, lookup, options, say))
    del violations
    return checks


def _resistance_check(
    step: ConductorStep, options: GuideOptions, say: Phrasebook, *, board: Board | None
) -> Checkpoint:
    """The end-to-end check on one run, in the form the reader's meter can carry out.

    Two forms, and which one a run gets is decided by ``meter_resolution_ohm`` -- because
    the useful question is not "how long is this run" but "can the person holding the
    meter tell a good one from a bad one".

    BELOW the meter's resolution, which is where nearly every real run lands: a number
    and a tolerance band are both inside the instrument's noise, so quoting them asks for
    a measurement nobody can make. What the same cheap meter CAN do is tell a dead short
    from a joint that is not one, and that is exactly the failure this check exists for --
    a cold joint or a cracked run reads in ohms, three orders of magnitude away, and is
    unmissable on any meter. So the check becomes the one that discriminates.

    ABOVE it -- a long pure-solder run on a big board, where a wire spine was declined --
    the number is worth quoting, because now the meter can actually resolve it and a run
    reading well over is one to go back to.

    ``resistance_ohm`` is unchanged either way and stays in the JSON export at full
    precision: this is about what to ASK somebody to do, not about what is known.
    """
    milliohm = (step.resistance_ohm or 0.0) * 1000
    span_from, span_to = format_hole(step.path[0], board), format_hole(step.path[-1], board)
    if (step.resistance_ohm or 0.0) >= options.meter_resolution_ohm:
        band = options.resistance_tolerance
        return Checkpoint(
            kind="resistance",
            title=say(
                "{net} run {span}: about {milliohm:.1f} mΩ end to end",
                net=step.net_name, span=step.span, milliohm=milliohm,
            ),
            instruction=say(
                "Measure between {start} and {end}. Subtract the reading with the probes "
                "touched together, or use four-wire mode if your meter has it.",
                start=span_from, end=span_to,
            ),
            expected=say(
                "About {milliohm:.1f} mΩ (accept {low:.1f}–{high:.1f} mΩ). Much higher "
                "means a cold joint or a crack in the run.",
                milliohm=milliohm,
                low=milliohm * (1 - band),
                high=milliohm * (1 + band),
            ),
            holes=(step.path[0], step.path[-1]),
        )
    return Checkpoint(
        kind="resistance",
        title=say(
            "{net} run {span} must read as a dead short", net=step.net_name, span=step.span
        ),
        instruction=say(
            "Measure between {start} and {end}, then touch the probes together and "
            "compare. A good run adds nothing you can read.",
            start=span_from, end=span_to,
        ),
        expected=say(
            "The same as your probes touched together, give or take one count. This run "
            "should be about {milliohm:.1f} mΩ, far below what a hand meter resolves — so "
            "any reading you can actually distinguish is a cold joint or a crack, not the "
            "copper.",
            milliohm=milliohm,
        ),
        holes=(step.path[0], step.path[-1]),
    )


def _last_phase_by_net(
    conductor_steps: list[tuple[ConductorStep, PhaseNumber]],
) -> dict[str, PhaseNumber]:
    last: dict[str, PhaseNumber] = {}
    for step, phase in conductor_steps:
        current = last.get(step.net_name)
        if current is None or phase > current:
            last[step.net_name] = phase
    return last


def _pin_phrase(doc: PerfDocument, ref: str, pin: str, say: Phrasebook) -> str:
    """"U1 pin 4", or "U1 pin 4 (GPIO21)" when the part names that pin.

    Only a DECLARED name is added, never the footprint's own: a probe on "D1 pin 1 (A)"
    tells nobody anything the polarity note has not, and every guide written before parts
    could name their pins would change under it. A name the part declares is the one
    thing a pin number on a forty-pin module cannot tell you.
    """
    component = next((c for c in doc.components if c.ref == ref), None)
    name = declared_pin_name(component, pin) if component is not None else None
    if name:
        return say("{ref} pin {pin} ({name})", ref=ref, pin=pin, name=name)
    return say("{ref} pin {pin}", ref=ref, pin=pin)


def _closing_checks(
    doc: PerfDocument, lookup: FootprintLookup, options: GuideOptions, say: Phrasebook
) -> list[Checkpoint]:
    """Phase 8: everything that must be true before power is applied."""
    checks: list[Checkpoint] = []

    for check in isolation_checks(doc)[: options.isolation_cap]:
        blocking = {check.net_a, check.net_b} and _is_power_pair(doc, check.net_a, check.net_b)
        checks.append(
            Checkpoint(
                kind="isolation",
                title=say("{a} ↔ {b} must be separate", a=check.net_a, b=check.net_b),
                instruction=say(
                    "Probe {a} ({net_a}) and {b} ({net_b}).",
                    a=_pin_phrase(doc, check.a.component_ref, check.a.pin, say),
                    net_a=check.net_a,
                    b=_pin_phrase(doc, check.b.component_ref, check.b.pin, say),
                    net_b=check.net_b,
                ),
                expected=say(
                    "Open, or at least the circuit's own resistance — never a short."
                ),
                pins=(check.a, check.b),
                blocking=bool(blocking),
            )
        )

    polarised = [
        component.ref
        for component in doc.components
        for footprint in [lookup(component.footprint_id)]
        if footprint is not None and footprint.polarized
    ]
    if polarised:
        checks.append(
            Checkpoint(
                kind="polarity",
                title=say("Polarity sweep before power"),
                instruction=say(
                    "Look at every polarised part once more and compare it against the "
                    "component-side sheet: {parts}.",
                    parts=", ".join(sorted(polarised)),
                ),
                expected=say(
                    "Every stripe, band and flat facing the way the sheet shows. A backwards "
                    "electrolytic fails loudly and a backwards diode fails silently."
                ),
                blocking=True,
            )
        )

    dips = [
        component.ref
        for component in doc.components
        for footprint in [lookup(component.footprint_id)]
        if footprint is not None and footprint.body.archetype == "dip"
    ]
    if dips:
        checks.append(
            Checkpoint(
                kind="polarity",
                title=say("Fit the ICs, pin 1 as shown"),
                # Plural agreement on the actual count, and "sockets" is not a fact:
                # nothing in the document records whether one was fitted, so the
                # sentence has to work for a board where none was.
                instruction=(
                    say(
                        "Only now put {parts} into its socket, or straight into the board "
                        "if you did not fit one, notch to the end the sheet marks. "
                        "Straighten the legs on a flat surface first.",
                        parts=", ".join(sorted(dips)),
                    )
                    if len(dips) == 1
                    else say(
                        "Only now put {parts} into their sockets, or straight into the board "
                        "if you did not fit one, notch to the end the sheet marks. "
                        "Straighten the legs on a flat surface first.",
                        parts=", ".join(sorted(dips)),
                    )
                ),
                expected=say("Every notch and dot pointing the same way as the sheet."),
                blocking=True,
            )
        )

    checks.append(
        Checkpoint(
            kind="power-on",
            title=say("First power-up, current limited"),
            instruction=say(
                "Set the supply to the circuit's voltage and the current limit to a little "
                "above what you expect it to draw. Watch the current as it comes up, and "
                "keep a hand on the switch."
            ),
            expected=say(
                "Current settles at roughly what you expected. If it runs into the limit, "
                "power down at once and go back to the isolation checks — something is "
                "bridged."
            ),
            blocking=True,
        )
    )
    return checks


def _is_power_pair(doc: PerfDocument, name_a: str, name_b: str) -> bool:
    classes = {net.name: net.net_class for net in doc.nets}
    pair = {classes.get(name_a), classes.get(name_b)}
    return "power" in pair and "ground" in pair


# -- supporting lists -------------------------------------------------------


def _bom(doc: PerfDocument, lookup: FootprintLookup, say: Phrasebook) -> tuple[BomLine, ...]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for component in doc.components:
        footprint = lookup(component.footprint_id)
        name = say.footprint(footprint.name) if footprint is not None else component.footprint_id
        grouped.setdefault((component.value, name), []).append(component.ref)

    lines = [
        BomLine(
            ref_designators=tuple(sorted(refs)),
            value=value,
            footprint_name=name,
            quantity=len(refs),
        )
        for (value, name), refs in grouped.items()
    ]
    lines.sort(key=lambda line: (line.footprint_name, line.value, line.ref_designators))
    return tuple(lines)


def _gauges(cuts: list[WireCut]) -> str:
    return ", ".join(str(awg) for awg in sorted({cut.awg for cut in cuts}))


def _tools(
    doc: PerfDocument,
    cuts: list[WireCut],
    spines: list[SpineCut],
    say: Phrasebook,
    leads: list[LeadCut] | None = None,
    adapters: tuple[tuple[str, str, int], ...] = (),
) -> tuple[str, ...]:
    """What to have on the bench, derived from what the board actually needs."""
    iron = IRON_BY_MATERIAL[doc.board.material]
    breadboard = is_breadboard(doc.board)
    tools = [] if breadboard and not adapters else [
        say(
            "Soldering iron with a fine tip, set to {temperature} °C",
            temperature=iron.temperature_c,
        ),
        say("60/40 or lead-free solder, 0.7–1.0 mm"),
        say("Flux — a pen or a small pot. Solder traces are not reliably makeable without it"),
    ]
    if breadboard:
        tools.insert(0, say(
            "A solderless breadboard, {points} points",
            points=doc.board.cols * doc.board.rows - len(holeless_positions(doc.board)),
        ))
    tools += [
        say("Side cutters and small pliers"),
        say("A multimeter with a continuity buzzer (every checkpoint below uses it)"),
    ]
    # Two reels, two lines: hookup wire comes in colours and bare wire is the metal, so one
    # line listing "black, tinned copper" sends nobody to the right drawer.
    hookup = [cut for cut in cuts if cut.insulated]
    bare = [cut for cut in cuts if not cut.insulated]
    leads = leads or []
    if hookup or leads:
        # Alphabetical in the language they are READ in, which is how somebody scans a
        # list of colours for the one they are holding. A wire to a part off the board is
        # hookup wire from the same reels, so it is counted here and not on a line of its own.
        gauges = ", ".join(
            str(awg) for awg in sorted({cut.awg for cut in hookup} | {lead.awg for lead in leads})
        )
        colours = ", ".join(
            sorted({say(cut.colour) for cut in hookup} | {say(lead.colour) for lead in leads})
        )
        metres = (
            sum(cut.cut_mm for cut in hookup) + sum(lead.cut_mm or 0.0 for lead in leads)
        ) / 1000
        if breadboard:
            # SOLID core, and it has to be said: a stranded wire frays in a clip instead of
            # going into it, and is the reel most people reach for first.
            tools.append(say(
                "Solid-core hookup wire, AWG {gauges} in {colours} — about {metres:.2f} m in "
                "total. Not stranded: a stranded end frays in the clip instead of going in.",
                gauges=gauges,
                colours=colours,
                metres=metres,
            ))
        elif any(lead.cut_mm is None for lead in leads):
            tools.append(say(
                "Hookup wire, AWG {gauges} in {colours} — about {metres:.2f} m, plus the "
                "wires to the parts off the board, cut to fit",
                gauges=gauges,
                colours=colours,
                metres=metres,
            ))
        else:
            tools.append(say(
                "Hookup wire, AWG {gauges} in {colours} — about {metres:.2f} m in total",
                gauges=gauges,
                colours=colours,
                metres=metres,
            ))
    if bare:
        tools.append(say(
            "Bare tinned copper wire, AWG {gauges} — about {metres:.2f} m in total",
            gauges=_gauges(bare),
            metres=sum(cut.cut_mm for cut in bare) / 1000,
        ))
    if hookup or leads:
        tools.append(say("Wire strippers"))
    if doc.mounting_holes:
        diameters = sorted({m.diameter for m in doc.mounting_holes})
        sizes = ", ".join(f"{d:g} mm" for d in diameters)
        if len(diameters) > 1:
            tools.append(say(
                "A drill and {sizes} bits for the mounting holes, plus a deburring tool or a "
                "larger bit turned by hand",
                sizes=sizes,
            ))
        else:
            tools.append(say(
                "A drill and {sizes} bit for the mounting holes, plus a deburring tool or a "
                "larger bit turned by hand",
                sizes=sizes,
            ))
    if spines:
        total_spine = sum(spine.length_mm for spine in spines)
        spine_gauges = sorted({spine.gauge_mm for spine in spines})
        tools.append(say(
            "Tinned copper wire for the trace spines, {gauges} — about {length:.0f} mm "
            "(component lead offcuts do the job just as well)",
            gauges=", ".join(f"{g:g} mm" for g in spine_gauges),
            length=total_spine,
        ))
    if adapters:
        tools.append(say(
            "For the chips on adapters: the adapter boards, {pins} male header pins "
            "(2.54 mm), and a magnifier to check the chips' legs for bridges",
            pins=sum(pins for _, _, pins in adapters),
        ))
    return tuple(tools)


def _warnings(
    doc: PerfDocument, lookup: FootprintLookup, violations: list[DrcViolation], say: Phrasebook
) -> tuple[GuideWarning, ...]:
    """Everything that makes this guide less than a complete description of the build."""
    warnings: list[GuideWarning] = []

    unknown = sorted(
        component.ref
        for component in doc.components
        if lookup(component.footprint_id) is None
    )
    if unknown:
        warnings.append(
            GuideWarning(
                code="unknown-footprint",
                message=say(
                    "No step was written for {parts}: their footprint is not in the library, "
                    "so this guide cannot say which holes they go in.",
                    parts=", ".join(unknown),
                ),
            )
        )

    if doc.edge_connectors:
        # Said out loud because nothing else in the guide will mention it. The fingers
        # are copper the board came with, so they generate no step -- and a builder who
        # never reads that they are there is a builder who solders a connector to the
        # wrong end of the board.
        runs = ", ".join(
            say(
                "{count} fingers on the {edge} edge from {hole}",
                count=connector.count,
                edge=say(connector.edge),
                hole=format_hole(edge_connector_holes(connector, doc.board)[0], doc.board),
            )
            for connector in doc.edge_connectors
            if edge_connector_holes(connector, doc.board)
        )
        warnings.append(
            GuideWarning(
                code="edge-connector",
                message=say(
                    "This board has edge-connector fingers ({runs}). No step below covers "
                    "them: they are part of the board, not something to make. Fit whatever "
                    "mates with them last, and keep the iron off them until then — a tinned "
                    "finger no longer fits a connector.",
                    runs=runs,
                ),
            )
        )

    if not doc.nets:
        warnings.append(
            GuideWarning(
                code="no-netlist",
                message=say(
                    "No netlist has been imported, so there are no continuity checks. The "
                    "steps describe what to build; nothing here can confirm it is the right "
                    "circuit. Import the schematic's netlist to get the verification half."
                ),
            )
        )
    else:
        # First, because it is about the circuit and everything after it about the board:
        # LVS proves the board is the circuit, and a circuit with an unpowered chip in it
        # passes LVS perfectly. Built as drawn, it is a dead board.
        circuit_errors = [f for f in run_erc(doc, lookup) if f.severity == "error"]
        if circuit_errors:
            warnings.append(
                GuideWarning(
                    code="erc-error",
                    message=say(
                        "{count} error(s) in the circuit itself ({parts}) — a chip or a "
                        "module with its supply or ground on nothing, a part drawn the wrong "
                        "way round, or a pin the part does not have. This guide builds the "
                        "circuit as drawn, those included: fix the circuit first.",
                        count=len(circuit_errors),
                        parts=", ".join(dict.fromkeys(r for f in circuit_errors for r in f.refs)),
                    ),
                )
            )
        lvs = run_lvs(doc, lookup)
        if lvs.summary.opens:
            warnings.append(
                GuideWarning(
                    code="lvs-open",
                    message=say(
                        "{count} net(s) are not fully connected on this board. Following this "
                        "guide will reproduce the board as it is, including those gaps — "
                        "route them first.",
                        count=lvs.summary.opens,
                    ),
                )
            )
        if lvs.summary.shorts:
            warnings.append(
                GuideWarning(
                    code="lvs-short",
                    message=say(
                        "{count} short(s) between nets the schematic keeps apart. Do not "
                        "build this board until they are gone.",
                        count=lvs.summary.shorts,
                    ),
                )
            )

    errors = [v for v in violations if v.severity == "error"]
    if errors:
        warnings.append(
            GuideWarning(
                code="drc-error",
                message=say(
                    "{count} DRC error(s) on this board — overlapping parts, crossing "
                    "conductors or pins sharing a hole. The steps below describe it anyway; "
                    "some of them will not be physically possible.",
                    count=len(errors),
                ),
            )
        )

    if not doc.conductors:
        warnings.append(
            GuideWarning(
                code="no-conductors",
                message=say(
                    "Nothing is routed yet, so this guide covers fitting the parts and "
                    "nothing else."
                ),
            )
        )
    return tuple(warnings)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def describe(guide: Guide) -> str:
    """One line for a status bar, in the guide's own language."""
    say = phrasebook(guide.language)
    phases = sum(1 for phase in guide.phases if not phase.is_empty)
    parts = [
        say(
            "{steps} step(s) across {phases} phase(s)",
            steps=guide.total_steps,
            phases=phases,
        ),
        say("{count} check(s)", count=guide.checkpoint_count),
    ]
    if guide.cut_list:
        parts.append(say("{count} wire(s) to cut", count=len(guide.cut_list)))
    if guide.lead_list:
        parts.append(
            say("{count} wire(s) to parts off the board", count=len(guide.lead_list))
        )
    if guide.warnings:
        parts.append(say("{count} warning(s)", count=len(guide.warnings)))
    return ", ".join(parts)


def conductor_word(kind: ConductorKind, language: GuideLanguage = "en") -> str:
    """What a conductor is made of, in words: "solder trace", "çıplak tel".

    One spelling for the tag beside a step in the exported guide and the step's line in the
    window's guide panel, which is why it is here and not in either of them.
    """
    return phrasebook(language)(kind.replace("-", " "))


def all_checkpoints(guide: Guide) -> tuple[Checkpoint, ...]:
    return tuple(check for phase in guide.phases for check in phase.checkpoints)


def all_steps(guide: Guide) -> tuple[GuideStep, ...]:
    return tuple(step for phase in guide.phases for step in phase.steps)


def step_focus(step: GuideStep) -> str:
    """What one step is ABOUT: a component id or a conductor id.

    The thing a step image highlights and an animation frame brings in. Both need it and
    neither should be reaching into the union to find out which kind it has.
    """
    return step.component_id if isinstance(step, PartStep) else step.conductor_id


def document_at_step(doc: PerfDocument, guide: Guide, step_index: int) -> PerfDocument:
    """``doc`` as the board actually stands once step ``step_index`` has been done.

    The board, its mechanical features and its schematic intent are unchanged -- they are
    what you started with. The parts and the copper are whatever the guide has told you to
    fit BY THAT POINT, in the guide's own order, which is not document order and is not
    the order the router produced: it is build order, lowest part first, jumpers before
    whatever stands on them.

    This is the one place that knows what "partly built" means, because both things that
    need it must agree. An assembly animation is these documents played in sequence; a
    step image is one of them with :func:`step_focus`'s part picked out. If the animation
    and the guide's illustrations each worked it out their own way, a board would
    eventually be drawn with a part that the step beside it has not asked for yet.

    ``step_index`` is clamped: below zero gives the bare board as it comes out of the
    envelope, and at or past the last step gives the finished article. Callers rendering a
    "before" frame and a "done" frame therefore need no special cases.

    Components the guide could not write a step for -- an unknown footprint, reported in
    ``guide.warnings`` -- never appear, at any index. A picture cannot honestly show a
    part in a hole the guide declined to name.
    """
    steps = all_steps(guide)
    done = steps[: max(0, min(step_index + 1, len(steps)))]

    fitted = {step.component_id for step in done if isinstance(step, PartStep)}
    laid = {step.conductor_id for step in done if isinstance(step, ConductorStep)}

    return dataclasses.replace(
        doc,
        components=tuple(c for c in doc.components if c.id in fitted),
        conductors=tuple(c for c in doc.conductors if c.id in laid),
    )
