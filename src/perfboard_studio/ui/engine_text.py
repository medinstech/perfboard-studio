"""What the engine says about what it did, in the window's language.

A COMMAND DESCRIBES ITSELF IN ENGLISH, and has to. ``describe`` is the undo-stack label, the
line a replayed journal prints, the text an agent reads back from the MCP server -- and the
engine has no language of its own (CLAUDE.md, "i18n"). So in a Turkish window the status bar
said "Add J1 PWR to the schematic" and the Edit menu offered "Geri Al Place and arrange 8
part(s) from the schematic": every other word on the screen Turkish, and the one sentence
saying what just happened not.

The sentence is translated where it is SHOWN, which is the guide's arrangement turned round:
the guide builds its sentences from facts and so translates as it builds; a description is
already built, so it is recognised. ``TEMPLATES`` is every sentence the commands, the
planners and this window's own labels produce, as an English template whose fields are the
parts that vary; the catalogue in ``i18n`` holds each template's Turkish with the same
fields. ``say`` finds the template a sentence was made from and fills the Turkish one in.

Three things keep it honest:

- **A field says what it may contain** (``_FIELDS``): a count is digits, a hole is an
  address, a conductor kind is one of the six. Without that "Add R1 10k to the schematic"
  would be read as a conductor called R1 laid from 10k to "the schematic".
- **The more specific template comes first.** "Delete R1 and its 3 connection(s)" is also
  "Delete {ref}" with a very long reference; order is what separates them.
- **A planner's summary is clauses joined by ", "**, and one that matches no template
  whole is translated clause by clause. Anything still unrecognised is shown as it came:
  a half-English line is a worse sentence than a whole one, but it is never a wrong one.

``test_i18n`` holds the catalogue to these templates in both directions, and
``test_engine_text`` runs a session of real commands and fails on any description that
comes out untranslated -- which is what a new ``describe`` without a template looks like.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from functools import cache

from perfboard_studio.geometry import format_hole
from perfboard_studio.guide import conductor_word
from perfboard_studio.model import PerfDocument
from perfboard_studio.phrasebook import guide_language

from .i18n import language, t
from .partnames import footprint_label

#: Every sentence recognised, most specific first within a family. English, and the key.
TEMPLATES: tuple[str, ...] = (
    # -- parts on the board -------------------------------------------------------------
    "Place {parts} part(s) and {links} connection(s)",
    "Place and arrange {count} part(s) from the schematic",
    "Place {count} part(s) on the board",
    "Place {ref} at {hole}",
    "Move {count} component(s)",
    "Move {count} symbol(s) on the sheet",
    "Move {count} symbols on the sheet",
    "Move {ref} on the sheet",
    "Add {ref} to the sheet at ({x}, {y})",
    "Move {ref} to {hole}",
    "Rotate {ref} to {degrees} degrees",
    "Unmirror {ref}",
    "Mirror {ref}",
    "Take {ref} off the board",
    "Paste {parts} part(s) and {links} connection(s)",
    "Paste {parts} part(s)",
    "Paste {links} connection(s)",
    "{what} at {hole}",
    "Auto-place {count} component(s)",
    "Auto-place (no change)",
    # -- the design ----------------------------------------------------------------------
    "Add {count} imported part(s)",
    "Add {count} part(s) to the schematic",
    "Add {ref} {value} to the schematic",
    "Add {ref} to the schematic",
    "Delete {ref} and its {count} connection(s)",
    "Turn {count} symbol(s) on the sheet",
    "Flip {count} symbol(s) on the sheet",
    "Lay {count} symbol(s) out automatically",
    "Lay the whole sheet out automatically",
    "Wire {a} onto the wire from {b} to {c}",
    "Wire {a} to {b}",
    "Rub out {count} wire(s) on the sheet and {branches} branch(es) off it",
    "Rub out {count} wire(s) on the sheet",
    "Rub out the wire from {a} to {b} and {branches} branch(es) off it",
    "Rub out the wire from {a} to {b}",
    "Draw a {shape} on the sheet",
    "Write “{text}” on the sheet",
    "Edit a note on the sheet",
    "Delete {count} note(s) from the sheet",
    # -- nets ------------------------------------------------------------------------------
    "Import netlist ({count} nets)",
    "Add {netclass} net {name} with {count} pin(s)",
    "Add {netclass} net {name}",
    "Rename net {old} to {new}",
    "Update net {name}",
    "Make {name} a {netclass} net",
    "Delete net {name} ({count} conductor(s) keep their copper)",
    "Delete net {name}",
    "Connect {count} pins to {net}",
    "Connect {pin} to {net}",
    "Disconnect {count} pins from {net}",
    "Disconnect {pin} from {net}",
    # -- copper ----------------------------------------------------------------------------
    "Add {kind} {start} to {end}",
    "Add {kind}",
    "Add {count} conductor(s)",
    "Reroute conductor {id}",
    "Delete {kind} {id}",
    "Delete {count} conductor(s)",
    "Remove {count} stale conductor(s)",
    "Replace {removed} conductor(s) with {added}",
    "Route {net} ({count} connection)",
    "Route {net} ({count} connections)",
    "Autoroute {nets} nets ({count} connection)",
    "Autoroute {nets} nets ({count} connections)",
    "Autoroute (no matching nets)",
    "Autoroute (no netlist imported)",
    "Re-route {count} net(s)",
    "Re-route {net}",
    "Autoroute stripboard: {cuts} cut(s), {links} link(s)",
    "Cut track at {hole}",
    "Cut {cuts} track(s) and fit {links} link(s)",
    "Autoroute breadboard: {count} jumper(s)",
    "Fit {count} jumper(s)",
    "Remove cut {id}",
    # -- the board itself -------------------------------------------------------------------
    "Set board to {cols}x{rows} {material}",
    "Use a {cols}x{rows} {material} board",
    "Use a {points}-point breadboard",
    "Use a {points}-point solderable breadboard",
    "Use a {preset} board",
    "Drill 4 corner mounting holes ({mm} mm)",
    "Drill {mm} mm mounting hole at {hole}",
    "Drill {count} mounting holes",
    "Remove mounting hole {id}",
    "Add {count}-finger edge connector on the {edge} edge",
    "Remove edge connector {id}",
    "Limit build height to {mm} mm",
    "Remove the build height limit",
    "Name the board {name}",
    "Write “{text}” on the board at {hole}",
    "Edit a label on the board",
    "Delete {count} label(s) from the board",
    # -- deleting a part: after every more specific "Delete ..." -----------------------------
    "Delete {ref}",
    "Update {ref}",
    # -- what the planners report, clause by clause ------------------------------------------
    "Placement unchanged ({movable} movable part(s), {moves} moves tried) — nothing found "
    "would be cheaper to build than the board you have ({cost} against {other})",
    "Placement unchanged ({movable} movable part(s), {moves} moves tried)",
    "{count} part(s) placed",
    "{count} turned",
    "~{mm} mm less connection length",
    "~{mm} mm more connection length",
    "about the same connection length",
    "{count} overlap(s) cleared",
    "{count} part(s) brought back over the board",
    "{count} blocked wire entr(ies) cleared",
    "{count} terminal(s) turned to face their edge",
    "{count} hot pair(s) moved apart",
    "{count} part(s) moved out from under a screw head",
    "routing cost {cost}",
    "{made} connection(s) routed across {closed}/{considered} nets",
    "{count} could NOT be routed",
    "{count} needed an insulated wire or jumper",
    "{count} pad(s) to measure for isolation",
    "{count} ordering passes",
    "Nothing to re-route",
    "{count} old conductor(s) ripped up",
    "{count} connection(s) re-routed",
    "{count} conductor(s) now",
    "Nothing to do: every net is already right on this board.",
    "{count} cut(s)",
    "{count} link(s)",
    "{count} jumper(s)",
    "{count} problem(s)",
    # -- what the planners and the router could not do, where it is explained -------------
    "{ref}: {hole} -> {to}, turned to {degrees} deg",
    "{ref}: {hole} -> {to}",
    "... and {count} more",
    "{pin} ({net}) and {pin_b} ({net_b}) share the strip through {hole} and there is no free hole between them to cut. Move one of the parts.",
    "{pin} ({net}) and {pin_b} ({net_b}) are in one clip, {hole} and {hole_b}: the breadboard joins them and nothing can be cut. Move one of the parts.",
    "{count} pin(s) of {net} could not be found on the board: the part is not placed, its footprint is not in the library, or the netlist names a pin the footprint does not have. Nothing was linked to them.",
    "{count} part(s) of {net} stand where the breadboard has no hole, so nothing was linked to them. Move them onto the holes.",
    "{pin} is in the {edge} {sign} rail at {hole}, which is for {netclass}, and this is a pin no net declares. Move the part off the rail.",
    "{pin} is in the {edge} {sign} rail at {hole}, which is for {netclass}, and this is a {netclass_b} net. Move the part off the rail.",
    "Part of {net} (at {holes}) cannot be reached: every hole of its clip already has a lead in it. Move a part so its clip has a hole free for a jumper.",
    "No route found from {hole} to {to}. No wire is allowed by the current crossing policy, so only a solder trace was tried.",
    "No route found from {hole} to {to}. Every strategy was blocked — try moving a part, or allow a top jumper.",
    "{hole} has no pad to solder to — a mounting bore or an edge-connector finger is there. Move the part.",
    "Endpoint is outside the board.",
    "Start and end are the same hole.",
    "The router found no route.",
    "Skipped {count} unconnected nets",
    "Skipped {count} unconnected net",
    # -- what a command says when it refuses: the ones a person meets in the window --------
    "{a} is on {net_a} and {b} is on {net_b}. Joining two nets is a change to the circuit — disconnect one of the pins first.",
    "{ref} is locked.",
    'A component with ref "{ref}" is on the board.',
    'A schematic part with ref "{ref}" is already in the design. Place that one instead, or give this a different reference.',
    'A component with ref "{ref}" already exists.',
    "Anchor for {ref} {hole} is outside the {cols}x{rows} board.",
    'Renaming to "{ref}" would put {pins} on two nets at once, because something already wired those pins under that reference.',
    '{pin} already belongs to net "{net}". Disconnect it from there first -- a pin can only be on one net.',
    '{pin} is already on net "{net}".',
    'A net called "{name}" already exists.',
    "A net needs a name.",
    "A part needs a reference designator.",
    "A component needs a non-empty reference.",
    "{a} and {b} are not on one net, so there is no connection between them to draw.",
    "A wire has to go between two different pins.",
    "{a} is an end of that wire already; a branch has to come from another pin.",
    "No wire is drawn from {a} to {b} to branch off.",
    "The wire from {a} to {b} no longer joins one net, so it is not drawn and nothing can branch off it.",
    "The track at {hole} is already cut.",
    "There is already a mounting hole at {hole}.",
    "A breadboard has no tracks to cut; its clips are fixed.",
    "{listed} would fall outside a {cols}x{rows} board.",
    "A board needs a name; it cannot be blank.",
    "A text note needs something in it.",
    "A label with nothing in it is an invisible thing on the board that still has to be found to be deleted.",
    'Net "{name}" does not have pin(s) {pins}.',
    # -- a board's own printed numbering (geometry.parse_legend_runs), as Board Setup
    # says why OK is held off
    "A printed legend needs at least one run, such as A-Z or 1-60.",
    '"{piece}" is not a run: it needs a first label, as in A-Z.',
    "{first}–{last} cannot be printed: it counts backwards.",
    "{first}–{last} cannot be printed: a run is capital letters to capital letters (A–Z) "
    "or a number to a number (1–60), one kind to a run.",
)

#: Every DRC and LVS finding as the findings panel shows it in English, after
#: ``finding_text`` has named the copper and the parts: the key ``say_finding`` says
#: it by. A rule added to drc.py or lvs.py without a line here is shown in English,
#: which ``test_engine_text`` notices across every board in the repository.
FINDING_TEMPLATES: tuple[str, ...] = (
    '{ref} uses footprint "{footprint_id}", which is not in the library and cannot be generated, so it cannot be drawn or built.',
    'Component {ref} (anchored at {hole}) and {ref_b} (anchored at {hole_b}) have overlapping body outlines.',
    'Component {ref} is {whole} off the board: {count} of its {total} pin hole(s) fall outside the {cols}x{rows} grid (e.g. {hole}).',
    'Component {ref} (anchored at {hole}) hangs {mm} mm past the {edges} of the board: its pins are in holes but part of its body is over nothing. {advice}',
    'The part is larger than the board in that direction.',
    'Moving it {count} hole(s) in from the {edges} clears it; a part overhanging on purpose -- a TO-220 reaching a heatsink off the edge -- can stay.',
    'Screw terminal {ref} (anchored at {hole}) takes its wires in from the {side}, and {names} {verb} in front of the entries ({ref_b} {mm} mm from them; a wire needs {mm_b} mm clear to go in straight). Turn {ref_c} to face a clear side -- a board edge is best -- or move what is in the way.',
    'Screw terminal {ref} (anchored at {hole}) stands on the {on} edge{plural} of the board but takes its wires in from the {side}: every wire has to come in from outside and double back over the board to reach it. Turn {ref_b} so its entries face the {edge} edge.',
    'Hole {hole} has more than one component pin landing on it: {names}.',
    '{ref} ({archetype}, at {hole}) sits {mm} mm from {ref_b} ({archetype_b}, at {hole_b}), inside the {mm_b} mm heat clearance. An electrolytic loses roughly half its rated life for every 10 °C it runs hotter — move it, turn the tab away, or expect to replace it.',
    '{ref} ({footprint}, at {hole}) stands {mm} mm above the board, over the {mm_b} mm of clear height this build declares. Lay it down, choose a lower-profile part, or raise the limit if the case turned out to be deeper.',
    '{ref} extends under the {mm} mm screw head of mounting hole {mount} at {hole}. The screw cannot be fitted without pressing on the part.',
    "Pin {pin_no} of {ref} (net '{net}') is not connected to anything: no conductor touches it and it shares no hole with another pin.",
    '{ref} pin {pin_no} sits at {hole}, where mounting hole {mount} has removed the pad. There is nothing there to solder to — move the part, or move the mounting hole.',
    '{ref} pin {pin_no} sits at {hole}, which is part of edge connector {connector}. A finger is solid copper with no hole through it, so the lead cannot be fitted there — move the part, or shorten the connector.',
    '{ref} pin {pin_no} is at {hole}, where the breadboard has no hole — move the part onto the holes.',
    '{ref} pin {pin_no} sits at {hole}, where the track has been cut. The cut took the pad with it, so there is nothing there to solder to — move the part, or move the cut.',
    '{ref} pin {pin_no} is in the {rail} {sign} rail at {hole}, which is for {railclass}, and it is on {netwhat}. It works, but the board then says {sign_b} over it — move the part off the rail.',
    'Conductor {wire} is {whole} off the board: {count} of its {total} hole(s) fall outside the {cols}x{rows} grid (e.g. {hole}).',
    'Conductor {wire} ({kind}) and conductor {wire_b} ({kind_b}) cross each other near {hole} on the {face} side, between holes rather than at one. Neither kind can cross: on perfboard they would touch and short. Reroute one of them, or make it an insulated wire — which may cross — or let the router lay an insulated hop just over the crossing.',
    'Conductor {wire} ({kind}) and conductor {wire_b} ({kind_b}) both occupy hole {hole} on the {face} side without being part of the same electrical net — this is a physical short. Reroute one of them, or replace it with an insulated conductor that can safely cross.',
    'Solder trace {wire} has an invalid path: {reason}',
    'Conductor {wire} is a {kind} on the {face} side; on a solderless breadboard nothing is soldered and nothing runs underneath — use a jumper wire.',
    "Pure solder trace {wire} spans {count} pads on {board_material} (phenolic) board — beyond the {limit}-pad threshold. Phenolic pads lift under sustained soldering heat far more readily than FR-4; add a wire spine ('solder-trace-wired') or split the run.",
    "Pure solder trace {wire} spans {count} pads, beyond the {limit}-pad feasibility threshold. Long pure-solder runs are mechanically unreliable and hard to reflow evenly; consider a wire spine ('solder-trace-wired').",
    "{wirekind} {wire} is AWG {awg}{why}, {dia} mm of copper, and this board's holes are drilled {drill} mm: its ends will not go through them. Lap-solder it onto the pad faces instead, or bring this current onto the board on a terminal rated for it.",
    'Lead bend on {ref} pin {pin_no} spans {count} holes ({hole} to {hole_b}), beyond the {limit}-hole reliability threshold. A long bent lead is mechanically fragile — use a wire instead.',
    'Conductor {wire} is soldered at {hole}, where mounting hole {mount} has removed the pad.',
    'Conductor {wire} is soldered at {hole}, which is part of edge connector {connector} and has no hole through it.',
    'Conductor {wire} ends at {hole}, where the breadboard has no hole.',
    'Conductor {wire} is soldered at {hole}, where the track has been cut and the pad is gone.',
    'Top jumper {wire} passes under {ref}, which is {height} and covers {hole}. Solder the jumper before fitting {ref_b}, or the part has to come off to reach it.',
    '{wirekind} {wire} lies across {hole}, where {soldered} is soldered on another net. The netlist joins a wire only at its ends, but bare copper resting on a solder joint is a short at the bench. Route it clear of {hole_b}, or use insulated wire, which may pass over.',
    'Solder trace {wire} passes through {hole}, whose orthogonal neighbour {hole_b} belongs to a different net (~{mm} mm of copper-to-copper gap {direction} on this board). Dragging solder along the trace risks bridging the two nets — the most common way a perfboard build fails. Verify clearance between {hole_c} and {hole_d} before soldering.',
    "High voltage: net '{net}' ({volts} V) conductor {wire} runs through {hole}, directly next to {hole_b} on a different net. 2.54 mm hole spacing is near the practical creepage limit above {limit} V — increase clearance (skip a row/column) or reroute before building.",
    'Conductor(s) {wires} form an isolated island at {holes} with no component pin attached -- likely a stray solder trace, wire or bridge left over from editing.',
    'CRITICAL SHORT (power tied to ground): {where} ties together schematic nets {netnames} -- pins {pins}. This is almost certainly a solder bridge; separate the pads and re-measure isolation before applying power.',
    'SHORT: {where} ties together schematic nets {netnames} -- pins {pins}. This is almost certainly a solder bridge; separate the pads and re-measure isolation before applying power.',
    "Net '{net}' references pin(s) {pins}, but component(s) {refs} are not placed on the board.",
    "Net '{net}' references pin(s) {pins} on component(s) {refs}, whose footprint could not be resolved.",
    "Net '{net}' is unrouted: all {count} of its pins are present on the board but none of them are connected to each other yet.",
    "Net '{net}' is open: its pins are split across {count} separate physical connections instead of one -- {groups}.",
    "Net '{net}' declares {amps} A but solder trace {wire} ({buildup} buildup{spine}) has an estimated cross-section of {area} mm² (~{cap} A capacity at {density} A/mm²) — inadequate. Estimated resistance ~{mohm} mΩ over {length} mm, giving a ~{mv} mV drop at rated current.{recommendation}",
    "Net '{net}' declares {amps} A but {wirelabel} {wire} {stated} {area} mm² (~{cap} A capacity at {density} A/mm²) — inadequate.{gauge_advice}",
    'No hookup wire up to AWG {awg} carries that: split it across parallel runs, or bring this current onto the board on a terminal rated for it.',
    'Use AWG {awg} or heavier.',
    "Use AWG {awg} or heavier. AWG {awg_b} is {dia} mm of copper and will not go through this board's {drill} mm holes, so it has to be lap-soldered onto the pads or the current brought in on a terminal.",
)

_CONDUCTOR_KINDS = (
    "solder-trace-wired",
    "solder-trace",
    "bare-wire",
    "insulated-wire",
    "top-jumper",
    "lead-bend",
)

#: What each field may be. Anything not named here is any text at all, shortest first.
_FIELDS: dict[str, str] = {
    **{
        name: r"\d+"
        for name in (
            "count", "parts", "links", "cuts", "nets", "made", "closed", "considered",
            "removed", "added", "branches", "movable", "moves", "degrees", "cols", "rows",
            "cost", "other",
        )
    },
    "mm": r"-?\d+(?:\.\d+)?",
    "kind": "|".join(_CONDUCTOR_KINDS),
    "netclass": r"signal|ground|power",
    "netclass_b": r"signal|ground|power",
    "sign": r"[+-]",
    "shape": r"line|rectangle|circle|text",
    "edge": r"left|right|top|bottom",
    # A perfboard address, a breadboard's own ("e12", "T+12" -- geometry.format_hole), a
    # breadboard position with no hole, or an off-board coordinate.
    "hole": r"[A-Z]+\d+|[a-j]\d+|[TB][+-]\d+|column \d+ \(no hole\)|\(col -?\d+, row -?\d+\)",
    "what": r"Paste|Duplicate",
    "ref": r"[^\s]+",
    "pin": r"[^\s]+\.[^\s]+",
    "material": r"FR\d",
    # -- what a finding is built from (FINDING_TEMPLATES) --------------------------------
    "wire": r"\S+",
    "wire_b": r"\S+",
    "ref_b": r"[^\s]+",
    "ref_c": r"[^\s]+",
    "pin_no": r"[^\s]+",
    "kind_b": "|".join(_CONDUCTOR_KINDS),
    "whole": r"entirely|partly",
    "verb": r"stands|stand",
    "face": r"top|bottom",
    "side": r"left|right|top|bottom",
    "edges": r"(?:left|right|top|bottom)(?: and (?:left|right|top|bottom))* edges?",
    "on": r"(?:left|right|top|bottom)(?: and (?:left|right|top|bottom))*",
    "plural": r"s?",
    "direction": r"along the row|down the column",
    "rail": r"top|bottom",
    "railclass": r"signal|ground|power",
    "sign_b": r"[+-]",
    "netwhat": r"no net|a (?:signal|ground|power) net",
    "height": r"\d+(?:\.\d+)? mm tall|a part",
    "wirekind": r"Insulated wire|Bare wire|Top jumper|Bent lead",
    "why": r"(?: \(the gauge the cut list names for [^)]* A\))?",
    "where": r"the physical connection at .+?|an unaddressable physical connection",
    "advice": r".+",
    "reason": r".+",
    "groups": r".+",
    "buildup": r"light|normal|heavy",
    "spine": r"(?: \+ \S+ mm \S+ spine)?",
    "recommendation": r"(?: Adding a wire spine typically cuts this resistance by roughly an order of magnitude\.)?",
    "wirelabel": r"insulated wire|bare wire|top jumper",
    "stated": r"is AWG \d+,|would be cut in AWG \d+, the heaviest gauge this tool names,",
    "gauge_advice": r"(?: .+)?",
}


@cache
def _compiled() -> tuple[tuple[str, re.Pattern[str]], ...]:
    return _compile(TEMPLATES)


@cache
def _compiled_findings() -> tuple[tuple[str, re.Pattern[str]], ...]:
    return _compile(FINDING_TEMPLATES)


def _compile(templates: tuple[str, ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Each template as a pattern: the literal parts escaped, each field its own named
    group."""
    built: list[tuple[str, re.Pattern[str]]] = []
    for template in templates:
        pattern = ""
        cursor = 0
        for match in re.finditer(r"\{(\w+)\}", template):
            pattern += re.escape(template[cursor : match.start()])
            name = match.group(1)
            pattern += f"(?P<{name}>{_FIELDS.get(name, '.+?')})"
            cursor = match.end()
        pattern += re.escape(template[cursor:])
        built.append((template, re.compile(pattern)))
    return tuple(built)


def net_class_word(net_class: str) -> str:
    """A net's class as the window's language says it."""
    return {"signal": t("signal"), "ground": t("ground"), "power": t("power")}.get(
        net_class, net_class
    )


def _word(field: str, value: str) -> str:
    """A field's value, said in the window's language where it is a word and not a name."""
    if field == "kind":
        return conductor_word(value, guide_language(language()))  # type: ignore[arg-type]
    if field.startswith("netclass"):
        return net_class_word(value)
    if field == "shape":
        return {
            "line": t("line"), "rectangle": t("rectangle"), "circle": t("circle"),
            "text": t("text"),
        }[value]
    if field == "edge":
        return {"left": t("left"), "right": t("right"), "top": t("top"), "bottom": t("bottom")}[
            value
        ]
    if field == "what":
        return {"Paste": t("paste"), "Duplicate": t("duplicate")}[value]
    return _finding_word(field, value)


#: How a wire's kind is called in a finding, back to the id the guide's words are kept by.
_WIRE_KINDS = {
    "insulated wire": "insulated-wire",
    "bare wire": "bare-wire",
    "top jumper": "top-jumper",
    "bent lead": "lead-bend",
}


def _finding_word(field: str, value: str) -> str:
    """The words a DRC or LVS finding is built from, said in the window's language."""
    if field == "kind_b":
        return conductor_word(value, guide_language(language()))  # type: ignore[arg-type]
    if field in ("side", "rail"):
        return t(value)
    if field in ("whole", "verb", "direction"):
        # Each word its own t() call: the catalogue test finds a translated string by
        # seeing it inside t() in the source.
        return {
            "entirely": t("entirely"),
            "partly": t("partly"),
            "stands": t("stands"),
            "stand": t("stand"),
            "along the row": t("along the row"),
            "down the column": t("down the column"),
        }[value]
    if field == "face":
        return t("component side") if value == "top" else t("solder side")
    if field == "edges":
        words = " ve ".join(t(word) for word in re.findall(r"left|right|top|bottom", value))
        if value.endswith(" edges"):
            return t("{edges} edges, said from them").format(edges=words)
        return t("{edge} edge, said from it").format(edge=words)
    if field == "on":
        return " ve ".join(t(word) for word in re.findall(r"left|right|top|bottom", value))
    if field == "plural":
        return t("on the edge: several") if value else t("on the edge: one")
    if field == "railclass":
        return net_class_word(value)
    if field == "netwhat":
        named = re.fullmatch(r"a (\w+) net", value)
        if named is None:
            return t("on no net")
        return t("on a {netclass} net").format(netclass=net_class_word(named.group(1)))
    if field == "height":
        tall = re.fullmatch(r"(\S+) mm tall", value)
        if tall is None:
            return t("a part whose height is not known")
        return t("{mm} mm tall").format(mm=tall.group(1))
    if field == "wirekind":
        kind = _WIRE_KINDS[value.lower()]
        return conductor_word(kind, guide_language(language()))  # type: ignore[arg-type]
    if field == "why":
        amps = re.search(r"for (.+) A\)", value)
        if amps is None:
            return value
        return " " + t("(the gauge the cut list names for {amps} A)").format(amps=amps.group(1))
    if field == "where":
        at = value.removeprefix("the physical connection at ")
        if at == value:
            return t("an unaddressable physical connection")
        return t("the physical connection at {hole}").format(hole=at)
    if field == "soldered":
        end = re.fullmatch(r"the end of (.+) (\S+–\S+)", value)
        if end is None:
            return value
        kind = end.group(1).replace(" ", "-")
        return t("the end of {kind} {wire}").format(
            kind=conductor_word(kind, guide_language(language())),  # type: ignore[arg-type]
            wire=end.group(2),
        )
    if field == "footprint":
        return footprint_label(value)
    if field == "buildup":
        return {
            "light": t("light buildup"),
            "normal": t("normal buildup"),
            "heavy": t("heavy buildup"),
        }[value]
    if field == "spine":
        spine = re.fullmatch(r" \+ (\S+) mm (\S+) spine", value)
        if spine is None:
            return value
        return t(" + {mm} mm {material} spine").format(mm=spine.group(1), material=spine.group(2))
    if field == "recommendation":
        return (
            t(" Adding a wire spine typically cuts this resistance by roughly an order of magnitude.")
            if value
            else value
        )
    if field == "wirelabel":
        return conductor_word(value.replace(" ", "-"), guide_language(language()))  # type: ignore[arg-type]
    if field == "stated":
        heaviest = re.fullmatch(r"would be cut in AWG (\d+), the heaviest gauge this tool names,", value)
        if heaviest is not None:
            return t("would be cut in AWG {awg}, the heaviest gauge this tool names,").format(
                awg=heaviest.group(1)
            )
        return t("is AWG {awg},").format(awg=value.removeprefix("is AWG ").removesuffix(","))
    if field == "gauge_advice":
        said = _match(value.strip(), _compiled_findings()) if value else None
        return " " + said if said is not None else value
    if field == "advice":
        return _match(value, _compiled_findings()) or value
    return value


def _one(text: str) -> str | None:
    return _match(text, _compiled())


def _match(text: str, compiled: tuple[tuple[str, re.Pattern[str]], ...]) -> str | None:
    for template, pattern in compiled:
        found = pattern.fullmatch(text)
        if found is None:
            continue
        translated = t(template)
        if translated == template:
            return None
        fields = {name: _word(name, value) for name, value in found.groupdict().items()}
        return translated.format(**fields)
    return None


def _capitalised(sentence: str) -> str:
    """A whole sentence starts with a capital, whatever field the translation starts with:
    "sol kenara ..." is "Sol kenara ...". In Turkish, where i's capital is İ."""
    first = sentence[:1]
    if not first.islower():
        return sentence
    return ("İ" if first == "i" else first.upper()) + sentence[1:]


#: What a checker says about its own method, in brackets at the end of a clause: true, and
#: about the checker rather than the board.
_CHECKER_NOTE = re.compile(r" \[[a-z -]+ check\]")


#: An id as ``CommandContext.next_id`` makes one: a word, a hyphen, a number.
_GENERATED_ID = re.compile(r"[a-z]+-\d+")


def names_in(
    document: PerfDocument, message: str, conductor_ids: Sequence[str] = ()
) -> dict[str, str]:
    """What each document id a finding names is called: a conductor by its two ends, a part
    by its reference -- the ids the finding carries and the ones only its words name (the
    end of another wire, the part a lead bend belongs to)."""
    names: dict[str, str] = {}
    for conductor in document.conductors:
        if conductor.path and (conductor.id in conductor_ids or conductor.id in message):
            names[conductor.id] = (
                f"{format_hole(conductor.path[0], document.board)}\u2013"
                f"{format_hole(conductor.path[-1], document.board)}"
            )
    for component in document.components:
        # The same, and more to the point here: a bare "c1" is what a breadboard hole is
        # called.
        if _GENERATED_ID.fullmatch(component.id) and component.id in message:
            names[component.id] = component.ref
    return names


def finding_text(message: str, names: Mapping[str, str]) -> str:
    """A DRC or LVS finding as the findings panel shows it, in the window's language.

    A finding about a wire names it "cond-14 (d27 to c33)" -- the id is the document's
    handle for it, which DRC and an agent need and nobody at the bench can look up; the
    ends were added beside it for that reason. The panel shows the ends alone ("d27-c33")
    and a part by its reference, from ``names`` (the window's map from an id in the message
    to what it is called), drops what the checker says about its own method
    ("[axis-aligned bounding-box check]"), and says the sentence in the window's language
    (``say_finding``).

    The finding itself is untouched: its message is compared byte for byte by the goldens
    and read in English by an agent, so this is a way of SHOWING it, kept in the window.
    """
    for document_id, name in names.items():
        # The id, and the "(A to B)" that names a conductor beside it -- and nothing else in
        # brackets: "cond-3 (bare-wire)" keeps its kind. An id as the document makes them
        # ("cond-14", "cmp-3") is renamed wherever it stands; any other only with its ends
        # beside it, because a hand-made one may be a word -- a conductor called "bridge"
        # would otherwise be put in place of "bridge" in the sentence as well.
        ends = r"(?: \([^()]* to [^()]*\))" + ("?" if _GENERATED_ID.fullmatch(document_id) else "")
        message = re.sub(
            rf"\b{re.escape(document_id)}\b{ends}",
            # Literal: a backslash in the replacement would read as a group reference.
            name.replace("\\", "\\\\"),
            message,
        )
    return say_finding(_CHECKER_NOTE.sub("", message))


def say_finding(text: str) -> str:
    """A finding, already in the panel's English (``finding_text``), in the window's language.

    WHOLE SENTENCES ONLY, unlike ``say``: a finding that no template recognises -- a rule
    added since, or a message reworded -- is shown as it came rather than broken into
    clauses, half of which might happen to match a command's words.
    """
    if language() == "en" or not text:
        return text
    whole = _match(text, _compiled_findings())
    return _capitalised(whole) if whole is not None else text


def say(text: str) -> str:
    """``text``, an engine sentence, in the window's language -- or as it came, unrecognised."""
    if language() == "en" or not text:
        return text
    whole = _one(text)
    if whole is not None:
        return _capitalised(whole)
    if ", " not in text:
        return text
    clauses = text.split(", ")
    said = [_one(clause) for clause in clauses]
    if not any(said):
        return text
    return ", ".join(s if s is not None else c for s, c in zip(said, clauses, strict=True))
