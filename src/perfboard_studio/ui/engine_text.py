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
from functools import cache

from perfboard_studio.guide import conductor_word
from perfboard_studio.phrasebook import guide_language

from .i18n import language, t

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
    "shape": r"line|rectangle|circle|text",
    "edge": r"left|right|top|bottom",
    # A perfboard address, a breadboard's own ("e12", "T+12" -- geometry.format_hole), a
    # breadboard position with no hole, or an off-board coordinate.
    "hole": r"[A-Z]+\d+|[a-j]\d+|[TB][+-]\d+|column \d+ \(no hole\)|\(col -?\d+, row -?\d+\)",
    "what": r"Paste|Duplicate",
    "ref": r"[^\s]+",
    "pin": r"[^\s]+\.[^\s]+",
    "material": r"FR\d",
}


@cache
def _compiled() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Each template as a pattern, built once: the literal parts escaped, each field its
    own named group."""
    built: list[tuple[str, re.Pattern[str]]] = []
    for template in TEMPLATES:
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
    if field == "netclass":
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
    return value


def _one(text: str) -> str | None:
    for template, pattern in _compiled():
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
