"""``wiringstats.wiring_stats``: what each conductor costs the builder, and the board's totals.

The scoreboard, the window's wiring summary and a selected wire's Properties all read it, so
two things are held here: what each entry says on boards small enough to say it by hand, and
that every total on every board in the repository is the sum -- or the stack, the maximum --
of the entries, so a count and the wires it selects cannot disagree.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from perfboard_studio import persist, system
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import (
    Board,
    BodySpec,
    ComponentInstance,
    DocumentMeta,
    Footprint,
    FootprintPin,
    HoleCoord,
    PerfDocument,
    SolderTraceConductor,
    WireConductor,
)
from perfboard_studio.occupancy import stacking_layers, stacking_loops
from perfboard_studio.ratsnest import ratsnest, summarize
from perfboard_studio.wiringstats import wiring_stats

ROOT = Path(__file__).resolve().parents[1]
BOARDS = sorted((ROOT / "examples").rglob("*.perf")) + sorted(
    (ROOT / "tools" / "diffcheck" / "golden").glob("*.perf")
)

BOARD = Board(
    type="pad-per-hole",
    cols=20,
    rows=20,
    pitch=2.54,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.9,
    drill_diameter=0.8,
)
ONE_PIN = Footprint(
    id="fp1",
    name="fp1",
    pins=(FootprintPin(number="1", d_col=0, d_row=0),),
    body_outline=(),
    body_height=0,
    body=BodySpec(archetype="generic-box"),
    lead_diameter=0.5,
    polarized=False,
)


def h(col: int, row: int) -> HoleCoord:
    return HoleCoord(col=col, row=row)


def part(ref: str, at: HoleCoord) -> ComponentInstance:
    return ComponentInstance(
        id=ref.lower(), ref=ref, value="", footprint_id="fp1", anchor=at,
        rotation=0, mirrored=False, locked=False,
    )


def wire(cid: str, *path: HoleCoord, kind: str = "insulated-wire") -> WireConductor:
    side = "top" if kind == "top-jumper" else "bottom"
    return WireConductor(id=cid, path=path, kind=kind, side=side)  # type: ignore[arg-type]


def run(cid: str, *path: HoleCoord) -> SolderTraceConductor:
    return SolderTraceConductor(id=cid, path=path, buildup="normal", side="bottom")


def board(components: tuple[ComponentInstance, ...], conductors: tuple[object, ...]) -> PerfDocument:
    return PerfDocument(
        meta=DocumentMeta(name="t", created="2024-01-01T00:00:00.000Z", modified="2024-01-01T00:00:00.000Z"),
        board=BOARD,
        components=components,
        conductors=conductors,  # type: ignore[arg-type]
    )


LOOKUP = {"fp1": ONE_PIN}.get


def test_a_wire_says_what_it_lies_across() -> None:
    """W lies along row 4 across U1's pin at (5, 4) and the end of V at (7, 4), and over the
    solder run R; its own ends are not counted, and the run, soldered where it is, lies across
    nothing."""
    doc = board(
        (part("U1", h(5, 4)),),
        (
            wire("w", h(2, 4), h(10, 4)),
            wire("v", h(7, 4), h(7, 9)),
            run("r", h(9, 2), h(9, 3), h(9, 4), h(9, 5)),
        ),
    )

    stats = wiring_stats(doc, LOOKUP)
    w = stats.of("w")

    assert w is not None
    assert w.is_wire and w.over_pins == (h(5, 4),) and w.over_ends == (h(7, 4),)
    assert w.crosses == ("v", "r")
    assert w.length_mm == pytest.approx(8 * 2.54) and w.bends == 0 and w.pads == 0
    assert w.level == stacking_layers(doc, lookup=LOOKUP)["w"] >= 1
    r = stats.of("r")
    assert r is not None and not r.is_wire
    assert (r.pads, r.over_pins, r.over_ends, r.crosses) == (4, (), (), ("w",))
    assert stats.of("nope") is None


def test_a_junction_is_not_a_crossing() -> None:
    """Two runs meeting at a pad, and a wire ending on a run, are soldered together there."""
    doc = board(
        (),
        (
            run("a", h(1, 1), h(2, 1), h(3, 1)),
            run("b", h(3, 1), h(3, 2), h(3, 3)),
            wire("w", h(2, 1), h(2, 6), h(6, 6)),
        ),
    )

    stats = wiring_stats(doc, LOOKUP)

    assert [stats.of(c).crosses for c in ("a", "b", "w")] == [(), (), ()]  # type: ignore[union-attr]
    assert stats.of("w").bends == 1  # type: ignore[union-attr]


def test_a_conductor_on_the_other_face_is_neither_crossed_nor_an_end() -> None:
    doc = board(
        (),
        (wire("w", h(2, 4), h(10, 4)), wire("j", h(6, 4), h(6, 8), kind="top-jumper")),
    )

    stats = wiring_stats(doc, LOOKUP)

    assert stats.of("w").over_ends == () and stats.of("w").crosses == ()  # type: ignore[union-attr]


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.stem)
def test_every_total_is_its_entries(path: Path) -> None:
    lookup = footprint_lookup()
    whole = persist.deserialize_document(path.read_text(encoding="utf-8")).document
    for board_id in system.board_ids(whole):
        doc = system.board_document(whole, board_id)
        stats = wiring_stats(doc, lookup)
        wires = [c for c in stats.conductors if c.is_wire]

        assert [c.conductor_id for c in stats.conductors] == [c.id for c in doc.conductors]
        assert stats.wire_mm == pytest.approx(sum(c.length_mm for c in wires))
        assert stats.bends == sum(c.bends for c in wires)
        assert stats.over_pins == sum(len(c.over_pins) for c in wires)
        assert stats.over_ends == sum(len(c.over_ends) for c in wires)
        assert stats.max_level == max((c.level for c in wires), default=0)
        assert stats.trace_pads == sum(c.pads for c in stats.conductors)
        assert stats.loops == stacking_loops(doc)
        assert stats.unrouted == summarize(ratsnest(doc, lookup)).links
        for entry in stats.conductors:
            for other in entry.crosses:
                assert entry.conductor_id in stats.of(other).crosses  # type: ignore[union-attr]
        # Stripped of its copper, nothing lies across anything and every link is open.
        bare = wiring_stats(dataclasses.replace(doc, conductors=()), lookup)
        assert (bare.conductors, bare.wire_mm, bare.max_level) == ((), 0, 0)
