"""Which part a KiCad netlist's component is, on a perfboard -- and which of its legs is which.

WHAT WAS THROWN AWAY. A KiCad netlist says a great deal about each component: its value
("10k", "NE555P"), its footprint ("Package_TO_SOT_THT:TO-220-3_Vertical"), and, for every pin
in a net, what the symbol calls it ("C", "TRIG"). The importer kept the nets and threw the
rest away, and the parts it offered to place were guessed from the reference letter and the
number of pins in nets -- so a 7805 in a TO-220 ("U1", three pins) became a DIP-8, every
electrolytic a disc capacitor, and every part arrived with no value at all.

WHAT IS READ NOW, in order of how much it is trusted:

1. **The value, against the catalog.** "BC547B" is a BC547, "L7805CV" a 7805: the part comes
   with its package, its pin names and its schematic symbol -- when the KiCad footprint, if
   it names one this program can build, is the same package.
2. **The KiCad footprint name.** KiCad names its through-hole packages by their measurements
   -- ``R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal`` is a 6.3 x 2.5 mm body on
   10.16 mm, four holes -- so the footprint here is worked out rather than looked up. Only
   packages numbered alike in both libraries are mapped; a relay, a push button and a module
   are not, and say why.
3. **The reference letter and pin count**, as before, when neither says anything.

WHICH LEG IS WHICH. A netlist's pin numbers are the SYMBOL's, and they are not always the
part's. KiCad's LED symbol is pin 1 = cathode; this library's LEDs are pin 1 = anode, the long
leg. KiCad's generic ``Q_NPN_EBC`` with "BC547" typed in as its value says pin 1 is the
emitter; a BC547's pin 1 is its collector. Taken at its number, either is a board wired for
a part that does not exist -- and no check can see it, because the netlist IS what every
check is measured against. But the netlist also carries each pin's NAME, and the part here
has names too. Where every named pin matches exactly one pin of the part by name, the
netlist is renumbered to the part's own numbers, and the import says so. Where the names
cannot settle it -- duplicated, missing, or pointing two pins at one -- nothing is moved, and
a transistor or diode whose names disagree with the catalog's is reported instead.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from ..catalog import CATALOG, CatalogPart
from ..model import (
    ComponentInstance,
    Footprint,
    Net,
    NetNode,
    PartSymbol,
    PerfDocument,
    PinNames,
    SchematicPart,
    pin_name_of,
)
from .kicad import ImportedComponent, KicadNetlistImport

#: Where a suggestion came from, most trusted first.
type SuggestionSource = Literal["catalog", "kicad", "guess"]


@dataclass(frozen=True, slots=True)
class PartSuggestion:
    """What to place for one imported component that is not on the board yet."""

    ref: str
    footprint_id: str
    value: str
    source: SuggestionSource
    #: The catalog part, when the value named one and its package fits.
    part_id: str | None = None
    #: In the footprint's numbering -- after any renumbering -- and only what the footprint
    #: does not already call its pins.
    pin_names: PinNames = ()
    symbol: PartSymbol | None = None


@dataclass(frozen=True, slots=True)
class NetlistPlan:
    """A KiCad netlist made ready for this board."""

    #: The nets, with any component's pins renumbered to the part's own numbers.
    nets: tuple[Net, ...]
    #: For each component the netlist names that is not on the board, what to place.
    suggestions: dict[str, PartSuggestion]
    #: Per component, what the user has to know: a renumbering, a surface-mount footprint, a
    #: symbol that does not match the part. One sentence each.
    notes: dict[str, tuple[str, ...]]


# ---------------------------------------------------------------------------
# KiCad footprint name -> footprint id
# ---------------------------------------------------------------------------

#: One hole, in millimetres: the pitch every mapped package is measured against.
_PITCH_MM = 2.54

#: A can's height where KiCad's name gives only its diameter: what the registry's own
#: electrolytics are, and a typical height for the rest.
_CAN_HEIGHT_MM = {5.0: 11.0, 6.3: 11.0, 8.0: 11.5, 10.0: 12.5, 12.5: 20.0, 16.0: 25.0}

#: Axial diode bodies KiCad names by package only: length x diameter, from the JEDEC
#: outlines KiCad's own footprints are drawn to.
_DIODE_BODY_MM = {
    "DO-35": (3.5, 2.0),
    "DO-41": (5.2, 2.7),
    "DO-15": (7.6, 3.6),
    "DO-201": (9.5, 5.3),
    "DO-201AD": (9.5, 5.3),
    "DO-201AE": (9.5, 5.3),
    "P600": (9.1, 9.1),
}

#: Library prefixes and name fragments that mean a surface-mount part.
_SMD = re.compile(
    r"(^|[:_])(SMD|SOIC|SOP|SSOP|TSSOP|MSOP|QFN|DFN|QFP|LQFP|TQFP|SOT-2\d\d|SOT-23|SOD-\d|"
    r"D_SM[ABC]|\d{4}_\d{4}Metric|BGA|PowerPAK|DPAK|D2PAK|TO-252|TO-263)",
    re.IGNORECASE,
)


#: How far a lead may be bent to reach a hole. An axial lead is bent anyway and a pin is
#: not bent at all, so a third of a millimetre either way; a radial can's legs are splayed
#: or squeezed by a millimetre as a matter of course -- a 5 mm can on 2.0 mm goes in holes
#: 2.54 apart on every perfboard it has ever been soldered to.
_BEND_MM = 0.35
_RADIAL_BEND_MM = 1.0


def _holes(pitch_mm: float, bend_mm: float = _BEND_MM) -> int | None:
    """A lead spacing in holes, or None when it is not close to a whole number of them."""
    holes = max(round(pitch_mm / _PITCH_MM), 1)
    if abs(holes * _PITCH_MM - pitch_mm) > bend_mm:
        return None
    return holes


def _axial_resistor(m: re.Match[str]) -> list[str]:
    holes = _holes(float(m["pitch"]))
    if holes is None:
        return []
    # The registry's own resistor for that span first: it is the one with a borrowed model.
    exact = f"axial-{holes}h-{float(m['length']):g}x{float(m['diameter']):g}"
    return [f"r-axial-{holes}", exact]


def _diode(m: re.Match[str]) -> list[str]:
    package = m["package"].upper()
    holes = _holes(float(m["pitch"]))
    body = _DIODE_BODY_MM.get(package)
    if holes is None or body is None:
        return []
    registry = {("DO-41", 4): "d-do41", ("DO-35", 3): "d-do35"}.get((package, holes))
    exact = f"axial-{holes}h-{body[0]:g}x{body[1]:g}-pol"
    return [registry, exact] if registry else [exact]


def _electrolytic(m: re.Match[str]) -> list[str]:
    diameter = float(m["diameter"])
    holes = _holes(float(m["pitch"]), _RADIAL_BEND_MM)
    if holes is None:
        return []
    height = _CAN_HEIGHT_MM.get(diameter, round(diameter * 1.6, 1))
    return [f"c-elec-d{diameter:g}-p{holes}", f"c-elec-d{diameter:g}-p{holes}-h{height:g}"]


def _disc(m: re.Match[str]) -> list[str]:
    holes = _holes(float(m["pitch"]), _RADIAL_BEND_MM)
    if holes is None:
        return []
    exact = f"c-disc-d{float(m['diameter']):g}-p{holes}-t{float(m['width']):g}"
    return [exact, f"c-disc-p{holes}"]


def _film(m: re.Match[str]) -> list[str]:
    holes = _holes(float(m["pitch"]))
    if holes is None:
        return []
    length, width = float(m["length"]), float(m["width"])
    # KiCad's name has no height; a film box stands roughly twice as tall as it is thick.
    height = max(round(width * 1.8, 1), 5.0)
    return [f"c-film-{length:g}x{width:g}x{height:g}-p{holes}", f"c-film-p{holes}"]


def _dip(m: re.Match[str]) -> list[str]:
    row = float(m["row"])
    if abs(row - 7.62) < 0.01:
        return [f"dip-{int(m['pins'])}"]
    if abs(row - 15.24) < 0.01:
        return [f"dip-{int(m['pins'])}-wide"]
    return []


def _terminal(m: re.Match[str]) -> list[str]:
    if abs(float(m["pitch"]) - 5.08) > 0.05:
        return []
    ways = int(m["ways"])
    # KiCad's "Vertical" terminal takes its wires from above, as screw-terminal-N-v does.
    return [f"screw-terminal-{ways}-v" if m["orientation"] == "Vertical" else f"screw-terminal-{ways}"]


#: KiCad footprint name (the part after the library's colon) to candidate ids, best first.
#: Anchored at the start of the name; KiCad's variants (``_Socket``, ``_LongPads``,
#: ``_Clear``, ``_Wide``) follow what is matched and change nothing that matters here.
_KICAD_NAMES: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], list[str]]], ...] = (
    (
        re.compile(
            r"^R_Axial_DIN\d{4}_L(?P<length>[\d.]+)mm_D(?P<diameter>[\d.]+)mm_"
            r"P(?P<pitch>[\d.]+)mm_Horizontal"
        ),
        _axial_resistor,
    ),
    (
        re.compile(r"^D_(?P<package>DO-\d+[A-Z]*|P600)_[\w-]*?P(?P<pitch>[\d.]+)mm_Horizontal"),
        _diode,
    ),
    (re.compile(r"^CP_Radial_D(?P<diameter>[\d.]+)mm_P(?P<pitch>[\d.]+)mm"), _electrolytic),
    (
        re.compile(r"^C_Disc_D(?P<diameter>[\d.]+)mm_W(?P<width>[\d.]+)mm_P(?P<pitch>[\d.]+)mm"),
        _disc,
    ),
    (
        re.compile(r"^C_Rect_L(?P<length>[\d.]+)mm_W(?P<width>[\d.]+)mm_P(?P<pitch>[\d.]+)mm"),
        _film,
    ),
    (re.compile(r"^DIP-(?P<pins>\d+)_W(?P<row>[\d.]+)mm"), _dip),
    # KiCad counts columns first ("2x08" is two columns of eight), this library rows first
    # ("hdr-2x8" is two rows of eight); both number pin 2 across from pin 1.
    (
        re.compile(r"^Pin(?:Header|Socket)_(?P<a>\d+)x(?P<b>\d+)_P2\.54mm"),
        lambda m: [f"hdr-{int(m['a'])}x{int(m['b'])}"],
    ),
    (
        re.compile(r"^IDC-Header_2x(?P<n>\d+)_P2\.54mm_Vertical"),
        lambda m: [f"idc-2x{int(m['n'])}"],
    ),
    (
        re.compile(
            r"^(?:TerminalBlock|PhoenixContact)\S*?_1x(?P<ways>\d+)_P(?P<pitch>[\d.]+)mm"
            r"(?:_(?P<orientation>Horizontal|Vertical))?"
        ),
        _terminal,
    ),
    (
        re.compile(r"^TerminalBlock_bornier-(?P<ways>\d+)_P(?P<pitch>[\d.]+)mm(?P<orientation>)"),
        _terminal,
    ),
    (re.compile(r"^LED_D(?P<d>3|5|10)\.0mm"), lambda m: [f"led-{m['d']}mm"]),
    (re.compile(r"^TO-92"), lambda m: ["to92"]),
    (re.compile(r"^TO-220-3_Vertical"), lambda m: ["to220"]),
    (re.compile(r"^Crystal_HC49"), lambda m: ["xtal-hc49"]),
    # Numbered as KiCad numbers them -- pins 1 and 2 the switched pair -- so a netlist's
    # switch lands on them as drawn. See footprints.push_button_footprint.
    (re.compile(r"^SW_PUSH_6mm"), lambda m: ["sw-tactile-6x6"]),
    (re.compile(r"^SW_PUSH-12mm"), lambda m: ["sw-tactile-12x12"]),
)

#: Through-hole packages that are common and deliberately NOT mapped: their pins are
#: numbered differently here, or vary between makers, so a mapping would put pin 1 on the
#: wrong leg. Each says what to do instead.
_UNMAPPED: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^R_Axial\S*_Vertical"),
        "a resistor stood on end has no footprint here; it was laid flat",
    ),
    (
        re.compile(r"^Relay_"),
        "relay pinouts differ between makers; replace it with one that matches the relay in hand",
    ),
    (
        re.compile(r"^SW_PUSH"),
        "only the 6 mm and 12 mm four-leg push buttons are here; this one was guessed",
    ),
    (
        re.compile(r"^(Arduino|WEMOS|RaspberryPi|RPi_Pico|ESP32)", re.IGNORECASE),
        "a module's KiCad footprint numbers its pins down one side and up the other, this "
        "program's across; place it from the catalog and check its nets",
    ),
    (
        re.compile(r"^TO-220"),
        "only the upright three-leg TO-220 is here; a flat or five-leg one is not",
    ),
)


def kicad_footprint_ids(kicad_footprint: str) -> tuple[list[str], str]:
    """The footprint ids a KiCad footprint name maps to, best first, and a note.

    The ids are candidates, not yet checked against the library: the caller keeps the first
    one that builds. No ids with a note means the package is known and deliberately not
    mapped, or is surface-mount; no ids and no note means nothing here knows the name.
    """
    name = kicad_footprint.split(":", 1)[-1]
    if _SMD.search(kicad_footprint):
        return [], "its footprint is surface-mount, which a perfboard cannot take"
    for pattern, build in _KICAD_NAMES:
        match = pattern.match(name)
        if match is not None:
            return build(match), ""
    for pattern, why in _UNMAPPED:
        if pattern.match(name):
            return [], why
    return [], ""


# ---------------------------------------------------------------------------
# Value -> catalog part
# ---------------------------------------------------------------------------

#: What a maker puts in front of a regulator's number: an L7805 and an MC7805 are 7805s.
_MAKER_PREFIX = re.compile(r"^(lm|mc|ua|ka|l)(?=\d)")


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def catalog_part_for(value: str, lib_part: str | None = None) -> CatalogPart | None:
    """The catalog part a component's value -- or its symbol's name -- says it is.

    The part number as a prefix, longest first: "BC547B" is a BC547 and "NE555P" an NE555,
    tried with a maker's prefix on and off. What follows the number may not be another digit,
    so an LM350 is not an LM35. A quantity ("10k", "100n") matches nothing.
    """
    texts = [value]
    if lib_part:
        texts.append(lib_part.split(":", 1)[-1])
    by_length = sorted(CATALOG, key=lambda part: len(_normal(part.id)), reverse=True)
    for text in texts:
        normal = _normal(text)
        for form in dict.fromkeys((normal, _MAKER_PREFIX.sub("", normal))):
            for part in by_length:
                key = _normal(part.id)
                rest = form[len(key) :]
                if len(key) >= 4 and form.startswith(key) and not rest[:1].isdigit():
                    return part
    return None


# ---------------------------------------------------------------------------
# Reference letter -> footprint id (the old guess)
# ---------------------------------------------------------------------------

_GUESS_BY_PREFIX = {
    "R": "r-axial-3",
    "D": "d-do41",
    "LED": "led-5mm",
    "C": "c-disc-p2",
    "Q": "to92",
    "Y": "xtal-hc49",
    "RV": "pot-3",
    "SW": "sw-tactile-6x6",
    "K": "relay-spdt",
    "TB": "screw-terminal-2",
}


def guess_footprint_id(ref: str, pin_count: int) -> str:
    """A first guess at a footprint from a schematic reference and how many pins it uses.

    A guess, stated as one: the netlist knows the part is called "U3" and that three of its
    pins appear in nets, and when its footprint and value say nothing that is all there is to
    go on. It is enough to be useful -- a "R" with two pins really is an axial resistor -- and
    it is why the parts land somewhere obvious for the user to correct rather than being
    quietly treated as final.
    """
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    if letters == "K":
        # Five pins, and not an IC: the pin count alone made every relay a DIP-8.
        return _GUESS_BY_PREFIX["K"]
    if letters in ("U", "IC") or pin_count > 4:
        # An IC, sized to what the netlist actually uses, rounded up to a real DIP.
        for pins in (8, 14, 16, 18, 20, 24, 28, 40):
            if pin_count <= pins:
                return f"dip-{pins}"
        return "dip-40"
    if letters in ("J", "P", "CN"):
        return f"hdr-1x{max(pin_count, 1)}"
    if letters == "C" and pin_count == 2:
        return "c-disc-p2"
    return _GUESS_BY_PREFIX.get(letters, "r-axial-3")


# ---------------------------------------------------------------------------
# Which leg is which
# ---------------------------------------------------------------------------

#: The pin names a transistor, a MOSFET and a diode are wired by. Where the schematic and the
#: catalog disagree about one of these on the same pin and the names cannot put it right,
#: the board is wired for the wrong part -- said, since nothing else will.
_WIRED_BY = frozenset({"C", "B", "E", "G", "D", "S", "A", "K"})

#: A pin function that names nothing: KiCad's generic connector and passive pins.
_NAMELESS = re.compile(r"^(~|Pin_?\d+|P\d+|\d+|-|)$", re.IGNORECASE)


def schematic_pin_names(component: ImportedComponent) -> PinNames:
    """What the schematic's symbol calls this component's pins, where it says something -- a
    connector's "Pin_1" and a resistor's "~" do not."""
    return tuple(
        (pin, function) for pin, function in component.pin_functions if not _NAMELESS.match(function)
    )


def pin_renumbering(schematic: PinNames, part: PinNames, pins_in_nets: set[str]) -> dict[str, str]:
    """The schematic pins to move, and where: each named pin to the ONE pin of the part with
    the same name. Empty when nothing moves or when the names cannot settle it -- a name on
    two pins, two pins onto one, or a pin moved onto one the schematic still uses as itself."""
    theirs: dict[str, list[str]] = {}
    for pin, name in schematic:
        theirs.setdefault(name.upper(), []).append(pin)
    ours: dict[str, list[str]] = {}
    for number, name in part:
        ours.setdefault(name.upper(), []).append(number)
    mapping = {
        pins[0]: ours[name][0]
        for name, pins in theirs.items()
        if len(pins) == 1 and len(ours.get(name, ())) == 1
    }
    moved = {pin: to for pin, to in mapping.items() if pin != to}
    if not moved:
        return {}
    targets = list(mapping.values())
    if len(set(targets)) != len(targets):
        return {}
    staying = pins_in_nets - set(mapping)
    if staying & set(moved.values()):
        return {}
    return moved


#: What KiCad's own footprints call their pads, where that is not what the pins here are
#: called by the same numbers: read when the netlist carries no pin names of its own (an
#: older export, or one written by hand). KiCad's LED is pad 1 = cathode, the square pad;
#: this library's LED is pin 1 = anode, the long leg.
_KICAD_PAD_NAMES: tuple[tuple[re.Pattern[str], PinNames], ...] = (
    (re.compile(r"^LED_D\d"), (("1", "K"), ("2", "A"))),
)


def _kicad_pad_names(kicad_footprint: str | None) -> PinNames:
    name = (kicad_footprint or "").split(":", 1)[-1]
    return next((pads for pattern, pads in _KICAD_PAD_NAMES if pattern.match(name)), ())


def _part_names(footprint: Footprint, declared: PinNames) -> PinNames:
    """What a part calls its pins: what was declared for it over the footprint's own."""
    given = dict(declared)
    return tuple(
        (pin.number, given.get(pin.number) or pin.name or "")
        for pin in footprint.pins
        if given.get(pin.number) or pin.name
    )


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------


def _suggest(
    component: ImportedComponent, pins_used: int, lookup: Callable[[str], Footprint | None]
) -> tuple[PartSuggestion, list[str]]:
    """What to place for ``component``, before any renumbering, and what to say about it."""
    notes: list[str] = []
    from_kicad: str | None = None
    if component.footprint:
        candidates, note = kicad_footprint_ids(component.footprint)
        from_kicad = next((fid for fid in candidates if lookup(fid) is not None), None)
        if note:
            notes.append(note)
    part = catalog_part_for(component.value, component.lib_part)
    if part is not None and from_kicad is not None and from_kicad != part.footprint_id:
        # "BC547" on a TO-220 is not the catalog's BC547, and its pin names would be for the
        # wrong package: the footprint wins.
        part = None
    if part is not None:
        return (
            PartSuggestion(
                ref=component.ref,
                footprint_id=part.footprint_id,
                value=component.value or part.placed_value,
                source="catalog",
                part_id=part.id,
                pin_names=part.pin_names,
                symbol=part.symbol,
            ),
            notes,
        )
    if from_kicad is not None:
        return PartSuggestion(component.ref, from_kicad, component.value, "kicad"), notes
    guessed = guess_footprint_id(component.ref, pins_used)
    return PartSuggestion(component.ref, guessed, component.value, "guess"), notes


def plan_import(
    imported: KicadNetlistImport,
    document: PerfDocument,
    lookup: Callable[[str], Footprint | None],
) -> NetlistPlan:
    """What importing ``imported`` onto ``document`` means: the nets as this board's parts
    number their pins, and what to place for each component that is not on it yet."""
    pins_by_ref: dict[str, set[str]] = {}
    for net in imported.nets:
        for node in net.nodes:
            pins_by_ref.setdefault(node.component_ref, set()).add(node.pin)
    # On the board or in the design: either way its footprint and names are the user's.
    placed: dict[str, ComponentInstance | SchematicPart] = {
        **{part.ref: part for part in document.parts},
        **{component.ref: component for component in document.components},
    }

    suggestions: dict[str, PartSuggestion] = {}
    notes: dict[str, list[str]] = {}
    moves: dict[str, dict[str, str]] = {}
    for component in imported.components:
        ref = component.ref
        pins = pins_by_ref.get(ref, set())
        schematic = schematic_pin_names(component)
        said: list[str] = []
        suggestion: PartSuggestion | None = None
        if ref in placed:
            on_board = placed[ref]
            footprint = lookup(on_board.footprint_id)
            ours = (
                tuple((p.number, pin_name_of(on_board, p) or "") for p in footprint.pins)
                if footprint is not None
                else ()
            )
        else:
            suggestion, said = _suggest(component, len(pins), lookup)
            footprint = lookup(suggestion.footprint_id)
            ours = _part_names(footprint, suggestion.pin_names) if footprint is not None else ()
        ours = tuple((number, name) for number, name in ours if name)

        move = pin_renumbering(schematic, ours, pins)
        name_of = dict(schematic)
        our_names = {name.upper() for _number, name in ours}
        if not move and not any(name.upper() in our_names for _pin, name in schematic):
            # The schematic's names say nothing either way; what KiCad calls the pads of the
            # footprint it chose may.
            pads = _kicad_pad_names(component.footprint)
            move = pin_renumbering(pads, ours, pins)
            name_of = dict(pads)
        if move:
            moves[ref] = move
            what = ", ".join(
                f"{pin} ({name_of[pin]}) is its pin {to}" for pin, to in sorted(move.items())
            )
            said.append(f"pins renumbered to the part's own: {what}")
        elif suggestion is not None and suggestion.source == "catalog":
            part_says = dict(ours)
            wrong = [
                f"pin {pin} is {name} in the schematic but {part_says[pin]} on the part"
                for pin, name in schematic
                if pin in part_says
                and name.upper() in _WIRED_BY
                and part_says[pin].upper() in _WIRED_BY
                and name.upper() != part_says[pin].upper()
            ]
            if wrong:
                said.append("; ".join(wrong) + " -- the board would be wired for the wrong pinout")

        if suggestion is not None and footprint is not None:
            if suggestion.source != "catalog" and len(footprint.pins) >= 3:
                # A schematic's own names, on a part the catalog does not know: printed on the
                # board, in the part's numbering. Not on a two-legged part, whose polarity mark
                # already says which leg is which.
                own = {pin.number: pin.name for pin in footprint.pins}
                names = tuple(
                    (move.get(pin, pin), name)
                    for pin, name in schematic
                    if own.get(move.get(pin, pin)) != name
                )
                suggestion = replace(suggestion, pin_names=names)
            suggestions[ref] = suggestion
        if said:
            notes[ref] = said

    nets = tuple(
        replace(
            net,
            nodes=tuple(
                NetNode(node.component_ref, moves.get(node.component_ref, {}).get(node.pin, node.pin))
                for node in net.nodes
            ),
        )
        if any(node.component_ref in moves for node in net.nodes)
        else net
        for net in imported.nets
    )
    # Components the netlist's nets name but its component list does not: a hand-edited or
    # partial export. Guessed, as before, so they can still be placed.
    for ref, pins in sorted(pins_by_ref.items()):
        if ref not in placed and ref not in suggestions and not any(
            c.ref == ref for c in imported.components
        ):
            suggestions[ref] = PartSuggestion(ref, guess_footprint_id(ref, len(pins)), "", "guess")
    return NetlistPlan(
        nets=nets,
        suggestions=suggestions,
        notes={ref: tuple(lines) for ref, lines in notes.items()},
    )
