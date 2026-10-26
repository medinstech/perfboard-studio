"""The README is written twice, in English and in Turkish, and the two must not drift.

A translation cannot be checked for meaning, but it can be checked for SHAPE, and drift has
a shape: a section added to one language and not the other is a heading, a table row, a code
block and a handful of identifiers that exist on one side only. So the two are held to the
same headings at the same levels, the same number of code blocks and table rows, and the
same inline code spans -- every `autoroute`, `version.py` and `.perf` -- counted, because a
command, a file name or a flag is spelled the same in every language and is exactly what a
paragraph nobody translated is made of.

Prose is free. A Turkish sentence may be ordered however Turkish grammar needs, split or
joined; what it may not do is lose, gain or rename the thing it is about.

It found two things on its first run. The Turkish README still called the whole project
Apache-2.0: the licence section had grown a paragraph about the CC-BY-SA meshes in 0.12.0,
in English only. And its "İki yüz" jump link pointed at an anchor no heading had.

Only the README is in two languages. ``docs/`` is English on purpose -- its readers are
developers and agents, and three pages kept in two languages cost more than they give -- so
there is nothing there to compare, and only its in-page links are checked.

``CLAUDE.md`` is held to two things more, because every agent session loads it whole and
loads ``docs/ARCHITECTURE.md`` not at all. It grew a section per feature to 159 000
characters and was split: what every change has to keep stayed, the record of why
everything else is the way it is moved, and CLAUDE.md ends with a list of every section
there by what somebody is about to touch. A size that only grows and a list that only
drifts are both silent, so both are tested.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
README_TR = REPO_ROOT / "README.tr.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
ARCHITECTURE = REPO_ROOT / "docs" / "ARCHITECTURE.md"

#: What CLAUDE.md may grow to. It was split to 31 000; a new section belongs in
#: docs/ARCHITECTURE.md, with one line in CLAUDE.md's list saying when to read it.
CLAUDE_MD_BUDGET = 40_000

FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
SPAN = re.compile(r"`([^`]+)`")
HEADING = re.compile(r"^(#{1,6}) (.+)$", re.MULTILINE)
TABLE_ROW = re.compile(r"^(?:> )?\|", re.MULTILINE)
ANCHOR_LINK = re.compile(r"\]\(#([^)]+)\)")


def _prose(text: str) -> str:
    """The page with its fenced blocks taken out, which is where inline spans live."""
    return FENCE.sub("", text)


def _spans(text: str) -> Counter[str]:
    # A span may be wrapped across a line break, and where it breaks is the prose's business.
    return Counter(" ".join(span.split()) for span in SPAN.findall(_prose(text)))


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation gone, spaces to hyphens.

    Letters, digits, marks, ``_`` and ``-`` survive, as they do in GitHub's slugger -- and the
    marks matter in Turkish: a heading that starts with "İ" lower-cases to "i" plus U+0307,
    which GitHub KEEPS, so its anchor carries a dot nobody can see and no link typed by hand
    reaches it. A regex word class would drop the mark and pass a link GitHub cannot follow.
    """
    text = re.sub(r"[`*]", "", heading).lower()
    kept = (
        c for c in text if c.isalnum() or c in "_- " or unicodedata.category(c).startswith("M")
    )
    return "".join(kept).replace(" ", "-")


def test_the_two_readmes_have_the_same_shape() -> None:
    en = README.read_text(encoding="utf-8")
    tr = README_TR.read_text(encoding="utf-8")

    levels = [len(hashes) for hashes, _ in HEADING.findall(_prose(en))]
    assert levels == [len(hashes) for hashes, _ in HEADING.findall(_prose(tr))], (
        "the headings differ: a section is in one language and not the other"
    )
    assert len(FENCE.findall(en)) == len(FENCE.findall(tr)), "a code block is missing"
    assert len(TABLE_ROW.findall(_prose(en))) == len(TABLE_ROW.findall(_prose(tr))), (
        "a table row is missing"
    )

    en_spans, tr_spans = _spans(en), _spans(tr)
    assert en_spans == tr_spans, (
        f"only in {README.name}: {sorted((en_spans - tr_spans).elements())}; "
        f"only in {README_TR.name}: {sorted((tr_spans - en_spans).elements())}"
    )


@pytest.mark.parametrize(
    "page",
    [README, README_TR, CLAUDE_MD, *sorted((REPO_ROOT / "docs").glob("*.md"))],
    ids=lambda p: p.name,
)
def test_every_link_within_a_page_lands_on_a_heading(page: Path) -> None:
    """A translated heading moves its anchor, and a link nobody re-pointed goes to the top
    of the page without a word."""
    text = page.read_text(encoding="utf-8")
    anchors = {_slug(title) for _, title in HEADING.findall(_prose(text))}
    for target in ANCHOR_LINK.findall(text):
        assert target in anchors, f"{page.name} links to #{target}, which is no heading"


def _links_into(text: str, page: str) -> list[str]:
    """The anchors of every link from ``text`` to a heading on ``page``."""
    return re.findall(rf"\]\({re.escape(page)}#([^)]+)\)", _prose(text))


def test_claude_md_lists_every_section_of_the_architecture() -> None:
    """The list at the end of CLAUDE.md is how an agent learns that a section exists at all,
    so a section added to ARCHITECTURE.md and not listed is one nobody reads before breaking
    what it describes; and a listed one that was renamed sends an agent after nothing."""
    claude = CLAUDE_MD.read_text(encoding="utf-8")
    architecture = ARCHITECTURE.read_text(encoding="utf-8")

    sections = {_slug(t) for hashes, t in HEADING.findall(_prose(architecture)) if hashes == "##"}
    listed = set(_links_into(claude, "docs/ARCHITECTURE.md"))
    assert not sections - listed, f"CLAUDE.md does not list: {sorted(sections - listed)}"
    assert not listed - sections, f"CLAUDE.md lists what is not there: {sorted(listed - sections)}"

    # ...and the foundations ARCHITECTURE.md sends its reader back to are still in CLAUDE.md.
    kept = {_slug(title) for _, title in HEADING.findall(_prose(claude))}
    for target in _links_into(architecture, "../CLAUDE.md"):
        assert target in kept, f"ARCHITECTURE.md links to CLAUDE.md#{target}, which is no heading"


def test_the_readmes_count_the_mcp_tools_as_docs_mcp_does() -> None:
    """docs/MCP.md's count is held to the server by tests/test_mcp.py, and nothing held the
    READMEs to docs/MCP.md: they still said 54 tools when it said 57. Twice each, and the
    second was spelled out -- "Fifty-four tools" -- which no pattern reads, so a README
    writes its counts of tools in digits."""
    mcp_doc = (REPO_ROOT / "docs" / "MCP.md").read_text(encoding="utf-8")
    stated = re.search(r"^(\d+) tools,", mcp_doc, re.MULTILINE)
    assert stated, "docs/MCP.md no longer states its tool count as 'N tools,'"
    for page in (README, README_TR):
        counts = re.findall(r"(\d+) (?:MCP )?tool", page.read_text(encoding="utf-8"))
        assert counts, f"{page.name} no longer counts the MCP tools"
        assert set(counts) == {stated.group(1)}, f"{page.name} says {counts}"


def test_claude_md_names_every_rule_the_original_never_had() -> None:
    """CLAUDE.md names PYTHON_ONLY_RULES one by one -- the DRC rules the differential proof
    leaves out because the TypeScript engine never had them -- and an agent reads that list
    to know what the fixtures do not cover. It fell two behind the test's own set
    (``wrong-rail``, ``under-module``) with nothing to say so. Read out of test_drc.py's
    source rather than imported, so this file stays free of the engine."""
    import ast

    source = (REPO_ROOT / "tests" / "test_drc.py").read_text(encoding="utf-8")
    assigned = next(
        node.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "PYTHON_ONLY_RULES" for t in node.targets)
    )
    assert isinstance(assigned, ast.Call), "PYTHON_ONLY_RULES is no longer frozenset(...)"
    rules = set(ast.literal_eval(assigned.args[0]))

    claude = CLAUDE_MD.read_text(encoding="utf-8")
    start = claude.index("- `PYTHON_ONLY_RULES`")
    end = claude.index("there is nothing for a fixture to record", start)
    named = set(re.findall(r"`([a-z][a-z0-9-]+)`", claude[start:end]))
    assert named == rules, (
        f"CLAUDE.md does not name {sorted(rules - named)}; "
        f"it names {sorted(named - rules)}, which are not in PYTHON_ONLY_RULES"
    )


def test_claude_md_stays_small_enough_to_load_into_every_session() -> None:
    size = len(CLAUDE_MD.read_text(encoding="utf-8"))
    assert size <= CLAUDE_MD_BUDGET, (
        f"CLAUDE.md is {size} characters; move a section to docs/ARCHITECTURE.md and list it"
    )
