"""The build guide in Turkish, held to the English it is translated from.

A translation table rots in two directions and this file watches both: a template the
guide can say with no Turkish (a Turkish guide with an English sentence in the middle of
it), and a Turkish entry for a template the guide no longer says (a translation that will
never appear, and that nothing else would ever mention). The keys the guide says are read
out of the SOURCE -- every literal handed to ``say`` -- and out of the tables it says them
from, never listed by hand here: a hand-kept list is the drift this file exists to catch.

Then it goes looking. Every board in the repository is built into a guide in both
languages and every sentence of the Turkish one is searched for English words the English
one also has, which is what an untranslated sentence looks like from the outside -- and is
the one check that does not trust the source scan to have seen every path.
"""

from __future__ import annotations

import ast
import dataclasses
import html
import re
import string
import typing
from pathlib import Path

import pytest

from perfboard_studio import guide as guide_module
from perfboard_studio import guide_export, model, persist
from perfboard_studio.footprints import footprint_lookup, standard_footprints
from perfboard_studio.guide import (
    PHASE_TITLES,
    Guide,
    GuideOptions,
    all_steps,
    build_guide,
    describe,
    step_focus,
)
from perfboard_studio.guide_export import bom_to_csv, cut_list_to_csv, guide_to_html, guide_to_json
from perfboard_studio.phrasebook import (
    ENGLISH,
    NAME_TEMPLATES,
    TURKISH,
    guide_language,
    matching_template,
    phrasebook,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "perfboard_studio"
ROOT = Path(__file__).resolve().parents[1]
BOARDS = sorted((ROOT / "tools" / "diffcheck" / "golden").glob("*.perf")) + sorted(
    (ROOT / "examples").glob("*.perf")
)

# ---------------------------------------------------------------------------
# What the guide says
# ---------------------------------------------------------------------------


def _said_literals(path: Path) -> set[str]:
    """Every template handed to ``say`` as a literal, either branch of a conditional."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        callee = node.func
        # ``say(...)`` in the guide; ``self(...)`` inside the phrasebook's own joiner.
        if getattr(callee, "id", None) not in ("say", "self"):
            continue
        first = node.args[0]
        for branch in (first.body, first.orelse) if isinstance(first, ast.IfExp) else (first,):
            if isinstance(branch, ast.Constant) and isinstance(branch.value, str):
                found.add(branch.value)
    return found


def _warning_codes() -> set[str]:
    """``GuideWarning(code=...)``: ids in the model, shown in words in the exported guide."""
    tree = ast.parse((SRC / "guide.py").read_text(encoding="utf-8"))
    return {
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "GuideWarning"
        for keyword in node.keywords
        if keyword.arg == "code" and isinstance(keyword.value, ast.Constant)
    }


def said_from_tables() -> set[str]:
    """What reaches ``say`` through a variable, read off the data that holds it."""
    spine = typing.get_type_hints(model.SpineSpec)["material"]
    return (
        set(PHASE_TITLES.values())
        | set(guide_module.PHASE_SUMMARIES.values())
        | set(guide_module.BREADBOARD_PHASE_TITLES.values())
        | set(guide_module.BREADBOARD_PHASE_SUMMARIES.values())
        | {iron.note for iron in guide_module.IRON_BY_MATERIAL.values()}
        | set(guide_module._PIN_NAME_MEANING.values())
        | set(guide_module._COMMON_LEG_MEANING.values())
        | set(guide_module._MARKED_LEAD_MEANING.values())
        | set(guide_module._DIODE_LEAD_MEANING.values())
        | set(guide_module._LEAD_NAME_MEANING.values())
        | set(guide_module.COLOR_BY_NET_CLASS.values())
        | set(guide_module.SIGNAL_COLORS)
        # A step's tag: its package family, or what its copper is made of.
        | set(typing.get_args(model.BodyArchetype))
        | {kind.replace("-", " ") for kind in typing.get_args(model.ConductorKind)}
        | {material.replace("-", " ") for material in typing.get_args(spine)}
        | set(typing.get_args(guide_module.CheckKind.__value__))
        # The four edges: where a terminal faces, where a strip of fingers runs.
        | set(typing.get_args(model.BoardEdge))
        | set(guide_export.CUT_LIST_COLUMNS)
        | set(guide_export.BOM_COLUMNS)
        | set(guide_export.WIRE_TABLE_COLUMNS)
        | _warning_codes()
        | set(NAME_TEMPLATES)
    )


def said() -> set[str]:
    literals = set().union(
        *(_said_literals(SRC / name) for name in ("guide.py", "guide_export.py", "phrasebook.py"))
    )
    return literals | said_from_tables()


def test_everything_the_guide_says_has_its_turkish() -> None:
    missing = sorted(said() - set(TURKISH))
    assert missing == [], f"the guide says these and has no Turkish for them: {missing}"


def test_the_turkish_names_nothing_the_guide_no_longer_says() -> None:
    stale = sorted(set(TURKISH) - said())
    assert stale == [], f"Turkish for templates the guide no longer says: {stale}"


def _fields(template: str) -> set[tuple[str, str]]:
    return {
        (name, spec) for _text, name, spec, _conversion in string.Formatter().parse(template)
        if name is not None
    }


def test_every_translation_fills_the_same_fields() -> None:
    """A field the Turkish drops is a hole address the reader never sees; one it invents
    is a KeyError at the bench. Same names AND the same format -- a milliohm printed to
    one place in English and to twelve in Turkish is a different measurement."""
    wrong = {
        key: (sorted(_fields(key)), sorted(_fields(value)))
        for key, value in TURKISH.items()
        if _fields(key) != _fields(value)
    }
    assert wrong == {}


def test_no_template_carries_markup() -> None:
    """The exporter puts a template's static words straight into HTML text and escapes
    only what it fills them with. So neither language may carry a character HTML reads as
    markup -- the hole spans and the A1 marker go in as fields, not as template text."""
    offending = [text for pair in TURKISH.items() for text in pair if set(text) & set("<>&")]
    assert offending == []


def test_the_progress_counter_is_safe_inside_a_script() -> None:
    """Its two words are spliced into the page's JavaScript as string literals."""
    for key in (" of ", " done"):
        assert not set(TURKISH[key]) & set("'\"\\\n")


def test_english_is_the_key_itself() -> None:
    for key in said():
        assert ENGLISH(key) == key


@pytest.mark.parametrize(
    ("code", "language"),
    [("tr", "tr"), ("tr_TR", "tr"), ("tr-TR", "tr"), ("TR", "tr"), ("en", "en"),
     ("en_US", "en"), ("de_DE", "en"), ("", "en"), (None, "en")],
)
def test_a_window_language_picks_a_guide_language(code: str | None, language: str) -> None:
    assert guide_language(code) == language


# ---------------------------------------------------------------------------
# Footprint names
# ---------------------------------------------------------------------------


def test_every_footprint_name_the_engine_writes_is_recognised() -> None:
    """The engine keeps its English names (they are in the footprint golden), so a name is
    recognised by its phrasing and re-said -- and a footprint added later in new words must
    fail here rather than turn up in English in a Turkish Parts panel and guide."""
    untemplated = sorted(
        footprint.name
        for footprint in standard_footprints().values()
        # A name with no word in it -- DIP-8, TO-220 -- is the same in every language.
        if matching_template(footprint.name) is None and re.search(r"[a-z]{3,}", footprint.name)
    )
    assert untemplated == []


def test_a_footprint_name_keeps_its_numbers() -> None:
    say = phrasebook("tr")
    assert say.footprint("Resistor (axial, 3-hole span)") == "Direnç (eksenel, 3 delik açıklık)"
    assert say.footprint("Pin header, 2x10") == "Pin başlığı, 2x10"
    assert say.footprint("DIP-8") == "DIP-8"
    assert say.footprint("one pin") == "one pin"


# ---------------------------------------------------------------------------
# The Turkish guide, built
# ---------------------------------------------------------------------------


def _load(path: Path) -> model.PerfDocument:
    result = persist.deserialize_document(path.read_text(encoding="utf-8"))
    assert result.ok, result.message
    return result.document


#: Fields of the guide's model that hold ids or the document's own data rather than
#: sentences. Identifiers stay identifiers in every language; a net called GND is GND.
_NOT_PROSE = frozenset(
    {"kind", "archetype", "conductor_kind", "net_class", "code", "colour", "material",
     "component_id", "conductor_id", "net_name", "ref", "value", "document_name",
     "footprint_name",
     # The face a conductor lies on, "top" or "bottom" -- the model's BoardSide, which is
     # what picks the way round its wire template is drawn.
     "side",
     # The board the guide is for, carried whole: its pad shape and strip axis are data.
     "board"}
)


def _prose(node: object) -> list[str]:
    """Every sentence in a guide's model, walked field by field."""
    if isinstance(node, str):
        return [node]
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return [
            text
            for field in dataclasses.fields(node)
            if field.name not in _NOT_PROSE
            for text in _prose(getattr(node, field.name))
        ]
    if isinstance(node, tuple | list):
        return [text for item in node for text in _prose(item)]
    return []


def _visible(page: str) -> str:
    """What a person reads on the exported page: no style, no script, no tags."""
    page = re.sub(r"<style>.*?</style>|<script>.*?</script>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


_WORD = re.compile(r"\b[a-z]{4,}\b")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text))


def _everything_read(guide: Guide) -> str:
    return "\n".join(
        [*_prose(guide), _visible(guide_to_html(guide)), cut_list_to_csv(guide), bom_to_csv(guide),
         describe(guide)]
    )


def _document_words(doc: model.PerfDocument) -> set[str]:
    """What the board itself is called -- parts, values, nets, footprints nobody named in
    the engine's words -- which the guide repeats in any language."""
    lookup = footprint_lookup()
    names: list[str] = [doc.meta.name]
    for component in doc.components:
        names += [component.ref, component.value, component.footprint_id]
        footprint = lookup(component.footprint_id)
        if footprint is not None and matching_template(footprint.name) is None:
            names.append(footprint.name)
    names += [net.name for net in doc.nets]
    return set().union(*(_words(name.lower()) for name in names))


#: Words the Turkish keeps on purpose, because the bench does: "flux", "jumper",
#: "datasheet", "netlist" are what a Turkish builder calls them.
#: Read with the fields taken out, or "{first}" and "{hole}" would excuse those words.
_KEPT_IN_TURKISH = set().union(
    *(_words(re.sub(r"\{[^}]*\}", " ", value)) for value in TURKISH.values())
)


def _leaks(doc: model.PerfDocument, lookup=None) -> list[str]:
    lookup = lookup or footprint_lookup()
    english = _words(_everything_read(build_guide(doc, lookup)))
    turkish = _words(_everything_read(build_guide(doc, lookup, GuideOptions(language="tr"))))
    return sorted((english & turkish) - _KEPT_IN_TURKISH - _document_words(doc))


@pytest.mark.parametrize("path", BOARDS, ids=lambda path: path.stem)
def test_a_turkish_guide_has_no_english_left_in_it(path: Path) -> None:
    """The search that does not trust the scan: a sentence built somewhere nobody thought
    to wrap shows up here as an English word both guides share."""
    assert _leaks(_load(path)) == []


def test_a_stripboard_guide_is_turkish_too() -> None:
    """The one kind of board none of the fixtures is: the tracks to cut and their probes."""
    from tests.test_stripboard import LOOKUP, _doc, _net, _pin

    doc = dataclasses.replace(
        _doc(cuts=(model.TrackCut(id="cut-1", at=model.HoleCoord(4, 2)),)),
        components=(_pin("R1", model.HoleCoord(1, 2)), _pin("R2", model.HoleCoord(7, 2))),
        nets=(_net("n1", "IN", ("R1", "1")), _net("n2", "OUT", ("R2", "1"))),
    )
    guide = build_guide(doc, LOOKUP, GuideOptions(language="tr"))
    assert guide.track_cuts[0].strip == "satır 3"
    assert "Önce bu şeritleri kes" in guide_to_html(guide)
    assert _leaks(doc, LOOKUP) == []


def test_a_translation_changes_the_words_and_nothing_else() -> None:
    """Same steps, same order, same checks, same wire: a guide in another language is the
    same build. The one thing that may move is the BOM's order, which is alphabetical by
    the package's name -- in the language it is read in."""
    doc = _load(ROOT / "examples" / "atmega328-relay.perf")
    english = build_guide(doc, footprint_lookup())
    turkish = build_guide(doc, footprint_lookup(), GuideOptions(language="tr"))
    assert [step_focus(s) for s in all_steps(english)] == [step_focus(s) for s in all_steps(turkish)]
    assert [len(p.checkpoints) for p in english.phases] == [len(p.checkpoints) for p in turkish.phases]
    assert [(c.kind, c.holes, c.pins, c.blocking) for p in english.phases for c in p.checkpoints] == [
        (c.kind, c.holes, c.pins, c.blocking) for p in turkish.phases for c in p.checkpoints
    ]
    assert english.cut_list == turkish.cut_list
    assert sorted(english.bom, key=lambda line: line.ref_designators) != [] and sorted(
        (line.ref_designators, line.quantity) for line in english.bom
    ) == sorted((line.ref_designators, line.quantity) for line in turkish.bom)
    assert turkish.language == "tr" and english.language == "en"


def test_the_exports_say_which_language_they_are_in() -> None:
    doc = _load(ROOT / "examples" / "ne555-astable.perf")
    turkish = build_guide(doc, footprint_lookup(), GuideOptions(language="tr"))
    english = build_guide(doc, footprint_lookup())
    assert '<html lang="tr">' in guide_to_html(turkish)
    assert '"language": "tr"' in guide_to_json(turkish)
    # English writes no language at all -- every English guide is still what it was.
    assert '"language"' not in guide_to_json(english)
    assert cut_list_to_csv(turkish).splitlines()[0].startswith("tür,net,nereden")
