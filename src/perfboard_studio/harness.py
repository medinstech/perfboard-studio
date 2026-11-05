"""The harness: what to cut, where each end goes and how to check it, for the cables between
the boards of a system.

The build guide is a board's (``guide.build_guide`` is handed one board's view, as every
single-board module is); a cable is the system's, so its part of the build is worked out
here, from the whole document, and comes after every board is built: a cable is fitted to
connectors that are already soldered, and checked end to end before the system sees power.
See docs/ARCHITECTURE.md, "Several boards are one document, and each is seen alone".

Every sentence goes through the guide's phrasebook (``phrasebook.py``), in the guide's
language, and every fact a sentence is built from is data first: the wire's colour is an id
said where it is shown, an address is never given a suffix, a board is called what
``system.board_title`` calls it.

Pure, like the rest of the engine: no clock, no filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from .connectivity import PhysicalPinRef
from .guide import DEFAULT_GUIDE_OPTIONS, Checkpoint, GuideOptions, net_colours
from .model import Cable, CableEnd, Mm, Net, PerfDocument, declared_pin_name
from .phrasebook import GuideLanguage, Phrasebook, phrasebook
from .system import board_title, connector_of
from .wiregauge import cut_gauge_awg


@dataclass(frozen=True, slots=True)
class HarnessEnd:
    """One end of one wire: the board, the connector on it and the pin it lands on."""

    board: str
    ref: str
    pin: str
    #: What the connector calls that pin, when the document says: "VIN", "GND".
    pin_name: str | None


@dataclass(frozen=True, slots=True)
class HarnessWire:
    """One wire of a cable, as the cut list and the "which end goes where" table give it."""

    a: HarnessEnd
    b: HarnessEnd
    #: The net its ``a`` end is on -- what the wire carries, if the cable is wired right.
    net_name: str
    #: What to cut: the cable's length and a stripped end at each end. ``None`` is "cut to
    #: fit", for a cable whose length nobody gave: how far apart the boards sit is a fact
    #: about the enclosure, and a guessed number in a cut list is worse than none.
    cut_mm: Mm | None
    strip_mm: Mm
    awg: int
    #: A colour id ("red"), said in words where it is shown.
    colour: str


@dataclass(frozen=True, slots=True)
class HarnessCable:
    cable_id: str
    ref: str
    length_mm: Mm | None
    wires: tuple[HarnessWire, ...]
    #: What to do, in order: cut, strip, fit the ends.
    steps: tuple[str, ...]
    #: Each wire end to end, then each pair of its wires on different nets kept apart --
    #: before the system is powered, so all of them block.
    checkpoints: tuple[Checkpoint, ...]
    note: str = ""


@dataclass(frozen=True, slots=True)
class Harness:
    cables: tuple[HarnessCable, ...]
    language: GuideLanguage = "en"

    @property
    def wire_count(self) -> int:
        return sum(len(cable.wires) for cable in self.cables)


def build_harness(
    doc: PerfDocument, options: GuideOptions = DEFAULT_GUIDE_OPTIONS
) -> Harness:
    """Every cable of ``doc``, in reference order, as the steps and checks that build it.

    ``doc`` is the whole system: a cable joins two boards, and only the system document has
    both. A document with no cable has an empty harness.
    """
    say = phrasebook(options.language)
    net_of = {
        (node.component_ref, node.pin): net for net in doc.nets for node in net.nodes
    }
    colours = net_colours(doc)
    cables = tuple(
        _cable(doc, cable, net_of, colours, options, say)
        for cable in sorted(doc.cables, key=lambda cable: (cable.ref, cable.id))
    )
    return Harness(cables=cables, language=options.language)


def _end(doc: PerfDocument, end: CableEnd, pin: str, language: GuideLanguage) -> HarnessEnd:
    part = connector_of(doc, end)
    assert part is not None, "a cable's ends resolve: persist and every command see to it"
    return HarnessEnd(
        board=board_title(doc, end.board, language),
        ref=part.ref,
        pin=pin,
        pin_name=declared_pin_name(part, pin),
    )


def _end_phrase(end: HarnessEnd, say: Phrasebook) -> str:
    """"Supply J2 pin 1", or "Supply J2 pin 1 (VOUT)" when the connector names the pin."""
    if end.pin_name:
        return say(
            "{board} {ref} pin {pin} ({name})",
            board=end.board, ref=end.ref, pin=end.pin, name=end.pin_name,
        )
    return say("{board} {ref} pin {pin}", board=end.board, ref=end.ref, pin=end.pin)


def _mm(value: Mm) -> str:
    return f"{value:g}"


def _cable(
    doc: PerfDocument,
    cable: Cable,
    net_of: dict[tuple[str, str], Net],
    colours: dict[str, str],
    options: GuideOptions,
    say: Phrasebook,
) -> HarnessCable:
    density = options.drc.max_wire_current_density_a_per_mm2
    strip = options.strip_length_mm
    wires: list[HarnessWire] = []
    for laid in cable.wires:
        a = _end(doc, cable.a, laid.a_pin, options.language)
        b = _end(doc, cable.b, laid.b_pin, options.language)
        net = net_of.get((a.ref, a.pin)) or net_of.get((b.ref, b.pin))
        wires.append(
            HarnessWire(
                a=a,
                b=b,
                net_name=net.name if net is not None else say("(unassigned)"),
                cut_mm=None if cable.length_mm is None else cable.length_mm + 2 * strip,
                strip_mm=strip,
                awg=cut_gauge_awg(laid.gauge_awg, net.current_a if net is not None else None, density),
                colour=laid.colour or (colours.get(net.id, "grey") if net is not None else "grey"),
            )
        )

    steps = [
        say(
            "Cut {count} wire(s) for {cable}, {length} mm each with the ends stripped.",
            count=len(wires), cable=cable.ref, length=_mm(cable.length_mm + 2 * strip),
        )
        if cable.length_mm is not None
        else say(
            "Cut {count} wire(s) for {cable}, long enough to reach between the boards as "
            "they will sit, and a little more.",
            count=len(wires), cable=cable.ref,
        ),
        say(
            "Strip {strip} mm at both ends of every wire and twist the strands.",
            strip=_mm(strip),
        ),
        *(
            say(
                "Fit the {colour} wire (AWG {awg}, {net}) from {a} to {b}.",
                colour=say(wire.colour), awg=wire.awg, net=wire.net_name,
                a=_end_phrase(wire.a, say), b=_end_phrase(wire.b, say),
            )
            for wire in wires
        ),
    ]

    checks: list[Checkpoint] = []
    for wire in wires:
        checks.append(
            Checkpoint(
                kind="continuity",
                title=say("{cable}: {net} end to end", cable=cable.ref, net=wire.net_name),
                instruction=say(
                    "Probe {a} and {b}.", a=_end_phrase(wire.a, say), b=_end_phrase(wire.b, say)
                ),
                expected=say(
                    "Continuous — they are both on net {net}.", net=wire.net_name
                ),
                pins=(PhysicalPinRef(wire.a.ref, wire.a.pin), PhysicalPinRef(wire.b.ref, wire.b.pin)),
                blocking=True,
            )
        )
    for first, second in pairwise(wires):
        if first.net_name == second.net_name:
            continue
        checks.append(
            Checkpoint(
                kind="isolation",
                title=say(
                    "{a} ↔ {b} must be open",
                    a=_end_phrase(first.a, say), b=_end_phrase(second.a, say),
                ),
                instruction=say(
                    "With {cable} fitted and nothing powered, measure resistance between "
                    "{a} and {b}.",
                    cable=cable.ref, a=_end_phrase(first.a, say), b=_end_phrase(second.a, say),
                ),
                expected=say(
                    "Open circuit: {first} and {second} are different nets. A beep is two "
                    "strands touching at a terminal.",
                    first=first.net_name, second=second.net_name,
                ),
                pins=(PhysicalPinRef(first.a.ref, first.a.pin), PhysicalPinRef(second.a.ref, second.a.pin)),
                blocking=True,
            )
        )
    return HarnessCable(
        cable_id=cable.id,
        ref=cable.ref,
        length_mm=cable.length_mm,
        wires=tuple(wires),
        steps=tuple(steps),
        checkpoints=tuple(checks),
        note=cable.note,
    )
