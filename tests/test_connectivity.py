"""Tests for the connectivity engine (src/perfboard_studio/connectivity.py).

Two layers, in order of importance:

1. Golden differential tests: every board document under
   tools/diffcheck/golden/*.perf, run through extract_physical_nets(), must
   reproduce the `physicalNets` array of its *.expected.json byte-for-byte
   (same net ids, same node ordering, same pin ordering, same conductorIds).
   Those fixtures were dumped from the original TypeScript engine
   (packages/core/src/connectivity.ts) by tools/diffcheck/generate.mjs, so a
   match here is proof of equivalence, not just "my own idea of correct".

2. Hand-built unit tests translated from packages/core/src/connectivity.test.ts,
   isolating the specific semantics (rule a/b/c contact points, top/bottom
   bridging, determinism, unknown-footprint handling) that the golden tests
   would otherwise only exercise incidentally.

The `_load_golden` helper below is deliberately minimal, private test
scaffolding: it reads a *.perf JSON file straight into the model dataclasses
using only what connectivity.py actually reads (board, components,
conductors). It is NOT the real persistence layer -- persist.py (being
written separately) will supersede it, and nothing outside this test file
should depend on it.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from perfboard_studio.connectivity import (
    FootprintLookup,
    PhysicalNet,
    PhysicalNodeRef,
    PhysicalPinRef,
    are_pins_connected,
    extract_physical_nets,
    net_of_pin,
)
from perfboard_studio.geometry import all_pin_holes, hole_key
from perfboard_studio.lvs import run_lvs
from perfboard_studio.model import (
    Board,
    BoardSide,
    BodySpec,
    ComponentInstance,
    Conductor,
    DocumentMeta,
    EdgeConnector,
    Footprint,
    FootprintPin,
    HoleCoord,
    LeadBendConductor,
    MountingHole,
    Net,
    NetNode,
    PerfDocument,
    Point2,
    Rotation,
    SolderTraceConductor,
    SpineSpec,
    StripConductor,
    TrackCut,
    WireConductor,
    contacts_every_path_hole,
)

# ---------------------------------------------------------------------------
# Golden fixtures: minimal *.perf / footprints.expected.json readers.
#
# Scaffolding only -- see module docstring. Parses exactly the subset of the
# wire format connectivity.py consumes (board, components, conductors, and
# the standalone footprint registry); nets/cuts/meta beyond what PerfDocument
# requires are not needed and are left at their dataclass defaults.
# ---------------------------------------------------------------------------

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "tools" / "diffcheck" / "golden"

GOLDEN_CASE_NAMES: tuple[str, ...] = (
    "dense",
    "ne555",
    "sparse",
    *(f"random-{i:02d}" for i in range(1, 13)),
)


def _hole(raw: dict[str, Any]) -> HoleCoord:
    return HoleCoord(col=raw["col"], row=raw["row"])


def _board(raw: dict[str, Any]) -> Board:
    return Board(
        type=raw["type"],
        cols=raw["cols"],
        rows=raw["rows"],
        pitch=raw["pitch"],
        thickness=raw["thickness"],
        material=raw["material"],
        pad_diameter=raw["padDiameter"],
        drill_diameter=raw["drillDiameter"],
        strip_axis=raw.get("stripAxis"),
    )


def _component(raw: dict[str, Any]) -> ComponentInstance:
    return ComponentInstance(
        id=raw["id"],
        ref=raw["ref"],
        value=raw["value"],
        footprint_id=raw["footprintId"],
        anchor=_hole(raw["anchor"]),
        rotation=raw.get("rotation", 0),
        mirrored=raw.get("mirrored", False),
        locked=raw.get("locked", False),
    )


def _conductor(raw: dict[str, Any]) -> Conductor:
    kind = raw["kind"]
    path = tuple(_hole(h) for h in raw["path"])

    if kind in ("solder-trace", "solder-trace-wired"):
        spine_raw = raw.get("spine")
        spine = (
            SpineSpec(material=spine_raw["material"], gauge=spine_raw["gauge"])
            if spine_raw is not None
            else None
        )
        return SolderTraceConductor(
            id=raw["id"],
            path=path,
            buildup=raw.get("buildup", "normal"),
            spine=spine,
            net_id=raw.get("netId"),
            layer_z=raw.get("layerZ", 0),
            kind=kind,
            side="bottom",
        )
    if kind in ("bare-wire", "insulated-wire", "top-jumper"):
        return WireConductor(
            id=raw["id"],
            path=path,
            kind=kind,
            side=raw.get("side", "bottom"),
            gauge_awg=raw.get("gaugeAwg"),
            color=raw.get("color"),
            net_id=raw.get("netId"),
            layer_z=raw.get("layerZ", 0),
        )
    if kind == "lead-bend":
        return LeadBendConductor(
            id=raw["id"],
            path=path,
            component_id=raw["componentId"],
            pin_number=raw["pinNumber"],
            net_id=raw.get("netId"),
            layer_z=raw.get("layerZ", 0),
        )
    if kind == "strip":
        return StripConductor(
            id=raw["id"],
            path=path,
            net_id=raw.get("netId"),
            layer_z=raw.get("layerZ", 0),
            side=raw.get("side", "bottom"),
        )
    raise ValueError(f"Unknown conductor kind in golden fixture: {kind!r}")


def _document(raw: dict[str, Any]) -> PerfDocument:
    meta_raw = raw["meta"]
    return PerfDocument(
        meta=DocumentMeta(
            name=meta_raw["name"], created=meta_raw["created"], modified=meta_raw["modified"]
        ),
        board=_board(raw["board"]),
        components=tuple(_component(c) for c in raw.get("components", [])),
        conductors=tuple(_conductor(c) for c in raw.get("conductors", [])),
        format_version=raw.get("formatVersion", 1),
    )


def _footprint(raw: dict[str, Any]) -> Footprint:
    return Footprint(
        id=raw["id"],
        name=raw["name"],
        pins=tuple(
            FootprintPin(number=p["number"], d_col=p["dCol"], d_row=p["dRow"], name=p.get("name"))
            for p in raw["pins"]
        ),
        body_outline=tuple(Point2(x=p["x"], y=p["y"]) for p in raw["bodyOutline"]),
        body_height=raw["bodyHeight"],
        body=BodySpec(
            archetype=raw["body"]["archetype"],
            dims=raw["body"].get("dims", {}),
            color=raw["body"].get("color"),
        ),
        lead_diameter=raw["leadDiameter"],
        polarized=raw["polarized"],
    )


def _load_footprint_lookup() -> FootprintLookup:
    raw = json.loads((GOLDEN_DIR / "footprints.expected.json").read_text(encoding="utf-8"))
    registry = {footprint_id: _footprint(fp) for footprint_id, fp in raw.items()}
    return registry.get


def _load_golden(name: str) -> tuple[PerfDocument, list[dict[str, Any]]]:
    """Load one golden case: the board document and its expected physicalNets."""
    doc = _document(json.loads((GOLDEN_DIR / f"{name}.perf").read_text(encoding="utf-8")))
    expected = json.loads((GOLDEN_DIR / f"{name}.expected.json").read_text(encoding="utf-8"))
    return doc, expected["physicalNets"]


_FOOTPRINT_LOOKUP = _load_footprint_lookup()


def _net_to_jsonable(net: PhysicalNet) -> dict[str, Any]:
    return {
        "id": net.id,
        "nodes": [
            {"hole": {"col": n.hole.col, "row": n.hole.row}, "side": n.side} for n in net.nodes
        ],
        "pins": [{"componentRef": p.component_ref, "pin": p.pin} for p in net.pins],
        "conductorIds": list(net.conductor_ids),
    }


# ---------------------------------------------------------------------------
# THE deliverable: exact match against the TypeScript engine's output.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_name", GOLDEN_CASE_NAMES)
def test_matches_typescript_golden_physical_nets(case_name: str) -> None:
    doc, expected_nets = _load_golden(case_name)

    actual_nets = [_net_to_jsonable(n) for n in extract_physical_nets(doc, _FOOTPRINT_LOOKUP)]

    assert actual_nets == expected_nets, (
        f"physicalNets mismatch for golden case {case_name!r}: "
        f"got {len(actual_nets)} nets, expected {len(expected_nets)}"
    )


def test_golden_case_count_is_fifteen() -> None:
    """Sanity check on the fixture set itself: 15 documents, as the task specifies."""
    perf_files = sorted(GOLDEN_DIR.glob("*.perf"))
    assert len(perf_files) == 15
    assert {p.stem for p in perf_files} == set(GOLDEN_CASE_NAMES)


#: Joins this engine makes and the TypeScript one did not: each a physical fact the
#: original's model had no way to say. None of them is excluded from the comparison above,
#: because no fixture holds the case -- and that is a TEST rather than an assumption. The
#: day a regenerated fixture holds one, test_no_fixture_holds_a_join_the_original_did_not_make
#: fails, instead of the byte-for-byte comparison quietly agreeing with a different rule.
JOINED_BEYOND_TYPESCRIPT: dict[str, str] = {
    "top-and-bottom-at-a-pad": (
        "a conductor on the component side and copper on the solder side ending in one hole "
        "that has a pad and no pin are one joint (connectivity pass 2b). A jumper's end "
        "passes through the hole and is soldered underneath exactly like a component lead, "
        "so it joins its hole's two sides for the same reason a pin does. REVERSES the "
        "original's 'keeps a top-jumper from connecting the bottom side except through a "
        "pin' (connectivity.test.ts), which treated two identical physical objects "
        "differently and gave no reason anywhere"
    ),
}


def _pad_meetings(doc: PerfDocument, lookup: FootprintLookup) -> list[HoleCoord]:
    """The holes ``top-and-bottom-at-a-pad`` joins: a top conductor's contact and bottom copper
    in one hole, with no pin there to have joined them already."""

    def contacts(conductor: Conductor) -> tuple[HoleCoord, ...]:
        path = conductor.path
        if not path:
            return ()
        return path if contacts_every_path_hole(conductor) else (path[0], path[-1])

    pins: set[str] = set()
    for component in doc.components:
        footprint = lookup(component.footprint_id)
        if footprint is not None:
            pins.update(hole_key(at) for _pin, at in all_pin_holes(component, footprint))
    top = {hole_key(h): h for c in doc.conductors if c.side == "top" for h in contacts(c)}
    bottom = {hole_key(h) for c in doc.conductors if c.side == "bottom" for h in contacts(c)}
    return sorted(
        (h for key, h in top.items() if key in bottom and key not in pins),
        key=lambda h: (h.row, h.col),
    )


@pytest.mark.parametrize("case_name", GOLDEN_CASE_NAMES)
def test_no_fixture_holds_a_join_the_original_did_not_make(case_name: str) -> None:
    """Why ``JOINED_BEYOND_TYPESCRIPT`` excludes nothing: eleven top wires in these fixtures
    end in 22 holes without a pin, and none of those holes has copper from the solder side."""
    doc, _expected = _load_golden(case_name)

    assert _pad_meetings(doc, _FOOTPRINT_LOOKUP) == []


# ---------------------------------------------------------------------------
# Unit-test fixture builders, translated from connectivity.test.ts.
# ---------------------------------------------------------------------------


def hole(col: int, row: int) -> HoleCoord:
    return HoleCoord(col=col, row=row)


BOARD = Board(
    type="pad-per-hole",
    cols=40,
    rows=40,
    pitch=2.54,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.9,
    drill_diameter=0.8,
)


def one_pin_footprint(fp_id: str, d_col: int = 0, d_row: int = 0) -> Footprint:
    """A footprint with a single pin at the anchor (dCol=0, dRow=0) unless overridden."""
    return Footprint(
        id=fp_id,
        name=fp_id,
        pins=(FootprintPin(number="1", d_col=d_col, d_row=d_row),),
        body_outline=(),
        body_height=0,
        body=BodySpec(archetype="generic-box"),
        lead_diameter=0.5,
        polarized=False,
    )


def two_pin_footprint(
    fp_id: str, pin1: tuple[int, int], pin2: tuple[int, int]
) -> Footprint:
    return Footprint(
        id=fp_id,
        name=fp_id,
        pins=(
            FootprintPin(number="1", d_col=pin1[0], d_row=pin1[1]),
            FootprintPin(number="2", d_col=pin2[0], d_row=pin2[1]),
        ),
        body_outline=(),
        body_height=0,
        body=BodySpec(archetype="generic-box"),
        lead_diameter=0.5,
        polarized=False,
    )


def make_component(
    comp_id: str,
    ref: str,
    footprint_id: str,
    anchor: HoleCoord,
    rotation: Rotation = 0,
    mirrored: bool = False,
) -> ComponentInstance:
    return ComponentInstance(
        id=comp_id,
        ref=ref,
        value="",
        footprint_id=footprint_id,
        anchor=anchor,
        rotation=rotation,
        mirrored=mirrored,
        locked=False,
    )


def solder_trace(cond_id: str, path: tuple[HoleCoord, ...]) -> SolderTraceConductor:
    return SolderTraceConductor(id=cond_id, path=path, buildup="normal", side="bottom")


def bare_wire(
    cond_id: str, path: tuple[HoleCoord, ...], side: BoardSide = "bottom"
) -> WireConductor:
    return WireConductor(id=cond_id, path=path, kind="bare-wire", side=side)


def top_jumper(cond_id: str, path: tuple[HoleCoord, ...]) -> WireConductor:
    return WireConductor(id=cond_id, path=path, kind="top-jumper", side="top")


def strip_conductor(
    cond_id: str, path: tuple[HoleCoord, ...], side: BoardSide = "bottom"
) -> StripConductor:
    return StripConductor(id=cond_id, path=path, side=side)


def lead_bend(
    cond_id: str, path: tuple[HoleCoord, ...], component_id: str = "cmp-x", pin_number: str = "1"
) -> LeadBendConductor:
    return LeadBendConductor(
        id=cond_id, path=path, component_id=component_id, pin_number=pin_number
    )


def make_doc(
    components: tuple[ComponentInstance, ...], conductors: tuple[Conductor, ...]
) -> PerfDocument:
    return PerfDocument(
        meta=DocumentMeta(
            name="test", created="2024-01-01T00:00:00.000Z", modified="2024-01-01T00:00:00.000Z"
        ),
        board=BOARD,
        components=components,
        conductors=conductors,
    )


def make_lookup(footprints: tuple[Footprint, ...]) -> FootprintLookup:
    registry = {fp.id: fp for fp in footprints}
    return registry.get


def find_net_with_node(
    nets: list[PhysicalNet], node: PhysicalNodeRef
) -> PhysicalNet | None:
    for net in nets:
        for n in net.nodes:
            if n.hole.col == node.hole.col and n.hole.row == node.hole.row and n.side == node.side:
                return net
    return None


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_solder_trace_joins_adjacent_pads_leaving_unrelated_pad_separate() -> None:
    a, b, c = hole(0, 0), hole(1, 0), hole(5, 5)
    fp = one_pin_footprint("fp1")
    doc = make_doc(
        (
            make_component("c1", "R1", "fp1", a),
            make_component("c2", "R2", "fp1", b),
            make_component("c3", "R3", "fp1", c),
        ),
        (solder_trace("t1", (a, b)),),
    )
    lookup = make_lookup((fp,))

    net_a = net_of_pin(doc, lookup, PhysicalPinRef("R1", "1"))
    net_b = net_of_pin(doc, lookup, PhysicalPinRef("R2", "1"))
    net_c = net_of_pin(doc, lookup, PhysicalPinRef("R3", "1"))

    assert net_a is not None
    assert net_b is not None
    assert net_c is not None
    assert net_a.id == net_b.id
    assert net_a.id != net_c.id

    assert are_pins_connected(doc, lookup, PhysicalPinRef("R1", "1"), PhysicalPinRef("R2", "1"))
    assert not are_pins_connected(doc, lookup, PhysicalPinRef("R1", "1"), PhysicalPinRef("R3", "1"))


def test_solder_trace_connects_all_five_holes() -> None:
    path = tuple(hole(i, 0) for i in range(5))
    doc = make_doc((), (solder_trace("t1", path),))
    lookup = make_lookup(())

    nets = extract_physical_nets(doc, lookup)
    assert len(nets) == 1
    assert nets[0].nodes == tuple(PhysicalNodeRef(h, "bottom") for h in path)


def test_bare_wire_connects_only_endpoints_while_solder_trace_connects_everything() -> None:
    a, b, c = hole(0, 0), hole(1, 0), hole(2, 0)
    lookup = make_lookup(())

    # bare-wire: A and C connected. B is merely passed over, so it makes no contact
    # and is not a node at all -- it must never share a net with A or C.
    wire_doc = make_doc((), (bare_wire("w1", (a, b, c)),))
    wire_nets = extract_physical_nets(wire_doc, lookup)

    net_a = find_net_with_node(wire_nets, PhysicalNodeRef(a, "bottom"))
    net_b = find_net_with_node(wire_nets, PhysicalNodeRef(b, "bottom"))
    net_c = find_net_with_node(wire_nets, PhysicalNodeRef(c, "bottom"))

    assert net_a is not None
    assert net_c is not None
    assert net_a.id == net_c.id
    assert net_b is None
    assert len(wire_nets) == 1
    assert net_a.nodes == (PhysicalNodeRef(a, "bottom"), PhysicalNodeRef(c, "bottom"))

    # Same path, but as a solder-trace: every hole is a contact point.
    trace_doc = make_doc((), (solder_trace("t1", (a, b, c)),))
    trace_nets = extract_physical_nets(trace_doc, lookup)
    assert len(trace_nets) == 1
    assert trace_nets[0].nodes == (
        PhysicalNodeRef(a, "bottom"),
        PhysicalNodeRef(b, "bottom"),
        PhysicalNodeRef(c, "bottom"),
    )


def test_lead_bend_connects_only_its_endpoints() -> None:
    """Rule c also covers lead-bend: only path[0] and path[-1] make contact."""
    a, b, c = hole(0, 0), hole(1, 0), hole(2, 0)
    lookup = make_lookup(())

    doc = make_doc((), (lead_bend("lb1", (a, b, c)),))
    nets = extract_physical_nets(doc, lookup)

    net_a = find_net_with_node(nets, PhysicalNodeRef(a, "bottom"))
    net_b = find_net_with_node(nets, PhysicalNodeRef(b, "bottom"))
    net_c = find_net_with_node(nets, PhysicalNodeRef(c, "bottom"))

    assert net_a is not None
    assert net_c is not None
    assert net_a.id == net_c.id
    assert net_b is None


def test_strip_connects_every_hole_along_its_path() -> None:
    """Rule b also covers 'strip' (stripboard's pre-existing copper), not just
    solder-trace: every hole along the path is a contact, unioned consecutively."""
    a, b, c = hole(0, 0), hole(1, 0), hole(2, 0)
    doc = make_doc((), (strip_conductor("s1", (a, b, c)),))
    lookup = make_lookup(())

    nets = extract_physical_nets(doc, lookup)
    assert len(nets) == 1
    assert nets[0].nodes == (
        PhysicalNodeRef(a, "bottom"),
        PhysicalNodeRef(b, "bottom"),
        PhysicalNodeRef(c, "bottom"),
    )
    assert nets[0].conductor_ids == ("s1",)


def test_component_pin_bridges_top_and_bottom() -> None:
    a = hole(3, 3)
    fp = one_pin_footprint("fp1")
    doc = make_doc((make_component("c1", "U1", "fp1", a),), ())
    lookup = make_lookup((fp,))

    net = net_of_pin(doc, lookup, PhysicalPinRef("U1", "1"))
    assert net is not None
    assert net.nodes == (PhysicalNodeRef(a, "bottom"), PhysicalNodeRef(a, "top"))
    assert net.pins == (PhysicalPinRef("U1", "1"),)


def test_solder_trace_joins_both_components_pins_and_records_conductor_id() -> None:
    a, b = hole(0, 0), hole(1, 0)
    fp = one_pin_footprint("fp1")
    doc = make_doc(
        (make_component("c1", "U1", "fp1", a), make_component("c2", "U2", "fp1", b)),
        (solder_trace("t1", (a, b)),),
    )
    lookup = make_lookup((fp,))

    net = net_of_pin(doc, lookup, PhysicalPinRef("U1", "1"))
    assert net is not None
    assert net.pins == (PhysicalPinRef("U1", "1"), PhysicalPinRef("U2", "1"))
    assert net.conductor_ids == ("t1",)


def test_a_top_jumper_joins_the_bottom_side_at_its_pad_as_a_pin_does() -> None:
    """REVERSES the original's "keeps a top-jumper from connecting the bottom side except
    through a pin" (connectivity.test.ts), on its own board: top jumper A-B, solder trace
    A-C, no pin at A. A jumper's end passes through the hole and is soldered underneath
    exactly like a component lead, so it joins its hole's two sides for the same reason a
    pin does. The original treated the two identical physical objects differently and gave
    no reason anywhere. See JOINED_BEYOND_TYPESCRIPT."""
    a, b, c = hole(0, 0), hole(1, 0), hole(2, 0)
    doc = make_doc((), (top_jumper("j1", (a, b)), solder_trace("t1", (a, c))))
    lookup = make_lookup(())

    nets = extract_physical_nets(doc, lookup)
    net_top_a = find_net_with_node(nets, PhysicalNodeRef(a, "top"))
    net_bottom_a = find_net_with_node(nets, PhysicalNodeRef(a, "bottom"))

    assert net_top_a is not None
    assert net_bottom_a is not None
    assert net_top_a.id == net_bottom_a.id
    assert PhysicalNodeRef(b, "top") in net_top_a.nodes
    assert PhysicalNodeRef(c, "bottom") in net_top_a.nodes
    assert net_top_a.conductor_ids == ("j1", "t1")


def test_deterministic_across_repeats_and_input_reordering() -> None:
    a, b, c, d = hole(0, 0), hole(1, 0), hole(2, 0), hole(3, 3)
    fp = one_pin_footprint("fp1")
    components = (
        make_component("c1", "U1", "fp1", a),
        make_component("c2", "U2", "fp1", b),
        make_component("c3", "U3", "fp1", d),
    )
    conductors: tuple[Conductor, ...] = (
        solder_trace("t1", (a, b)),
        top_jumper("j1", (b, c)),
        strip_conductor("s1", (d,)),
    )
    doc = make_doc(components, conductors)
    lookup = make_lookup((fp,))

    first = extract_physical_nets(doc, lookup)
    second = extract_physical_nets(doc, lookup)
    assert second == first
    assert [n.id for n in second] == [n.id for n in first]

    reordered_doc = make_doc(tuple(reversed(components)), tuple(reversed(conductors)))
    reordered = extract_physical_nets(reordered_doc, lookup)
    assert reordered == first


def test_skips_components_with_unknown_footprint_instead_of_raising() -> None:
    fp = one_pin_footprint("fp1")
    known = make_component("c1", "R1", "fp1", hole(0, 0))
    unknown = make_component("c2", "X1", "does-not-exist", hole(9, 9))
    doc = make_doc((known, unknown), ())
    lookup = make_lookup((fp,))

    nets = extract_physical_nets(doc, lookup)  # must not raise

    assert not any(p.component_ref == "X1" for n in nets for p in n.pins)
    assert net_of_pin(doc, lookup, PhysicalPinRef("R1", "1")) is not None


def test_pin_holes_under_mirror_then_rotation() -> None:
    # pin1 at the anchor, pin2 offset by (dCol=2, dRow=0).
    fp = two_pin_footprint("fp2", (0, 0), (2, 0))
    anchor = hole(5, 5)
    # mirror first: (2,0) -> (-2,0); rotate 90 CW: (x,y)->(-y,x): (-2,0) -> (0,-2).
    expected_pin2_hole = hole(5, 3)
    doc = make_doc(
        (make_component("c1", "Q1", "fp2", anchor, rotation=90, mirrored=True),), ()
    )
    lookup = make_lookup((fp,))

    net1 = net_of_pin(doc, lookup, PhysicalPinRef("Q1", "1"))
    net2 = net_of_pin(doc, lookup, PhysicalPinRef("Q1", "2"))

    assert net1 is not None
    assert net2 is not None
    assert [n.hole for n in net1.nodes] == [anchor, anchor]
    assert [n.hole for n in net2.nodes] == [expected_pin2_hole, expected_pin2_hole]


# ---------------------------------------------------------------------------
# A pad is one joint, whichever side it is soldered from (JOINED_BEYOND_TYPESCRIPT)
# ---------------------------------------------------------------------------


def _jumper_between_two_traces(board: Board = BOARD) -> PerfDocument:
    """P1 -- trace -- C1, a top jumper from C1 to C5, C5 -- trace -- P2. The jumper's ends
    are pads only the traces use, so no lead is there to join the two sides."""
    return dataclasses.replace(
        make_doc(
            (
                make_component("c1", "P1", "fp1", hole(0, 0)),
                make_component("c2", "P2", "fp1", hole(0, 4)),
            ),
            (
                solder_trace("t1", (hole(0, 0), hole(1, 0), hole(2, 0))),
                top_jumper("j1", (hole(2, 0), hole(2, 4))),
                solder_trace("t2", (hole(2, 4), hole(1, 4), hole(0, 4))),
            ),
        ),
        board=board,
    )


def test_a_top_jumper_ending_on_a_traces_pad_joins_the_trace() -> None:
    """How a crossing is mended by hand: solder up to it, a jumper over the top, solder on.
    The jumper's ends go down through their holes onto the traces' pads. Only a lead used to
    join the two sides, so this board read as open, and the 15 fixtures never held one."""
    doc = _jumper_between_two_traces()
    lookup = make_lookup((one_pin_footprint("fp1"),))

    assert _pad_meetings(doc, lookup) == [hole(2, 0), hole(2, 4)]
    assert are_pins_connected(doc, lookup, PhysicalPinRef("P1", "1"), PhysicalPinRef("P2", "1"))


@pytest.mark.parametrize("taken", ["a bore", "an undrilled finger", "a stripboard cut"])
def test_nothing_joins_at_a_hole_with_no_copper(taken: str) -> None:
    """The pad is what joins the two sides, so where there is none -- a mounting bore took
    it, an edge-connector finger has no bore for the wire to go down, a cut drilled the strip
    away -- the jumper's end and the copper below it are joined by nothing."""
    lookup = make_lookup((one_pin_footprint("fp1"),))
    if taken == "a bore":
        doc = dataclasses.replace(
            _jumper_between_two_traces(), mounting_holes=(MountingHole(id="mh1", at=hole(2, 0)),)
        )
    elif taken == "an undrilled finger":
        doc = dataclasses.replace(
            _jumper_between_two_traces(),
            edge_connectors=(EdgeConnector(id="ec1", edge="top", start=2, count=1),),
        )
    else:
        # Strips run down the columns: the jumper's C5 end is on P2's column strip below the
        # cut, and C1 is in the cut itself, with the trace from P1 under it.
        board = dataclasses.replace(BOARD, type="stripboard", strip_axis="vertical")
        doc = dataclasses.replace(
            _jumper_between_two_traces(board),
            components=(
                make_component("c1", "P1", "fp1", hole(0, 0)),
                make_component("c2", "P2", "fp1", hole(2, 6)),
            ),
            conductors=(
                solder_trace("t1", (hole(0, 0), hole(1, 0), hole(2, 0))),
                top_jumper("j1", (hole(2, 0), hole(2, 4))),
            ),
            cuts=(TrackCut(id="cut-1", at=hole(2, 0)),),
        )
        uncut = dataclasses.replace(doc, cuts=())
        assert are_pins_connected(uncut, lookup, PhysicalPinRef("P1", "1"), PhysicalPinRef("P2", "1"))

    assert not are_pins_connected(doc, lookup, PhysicalPinRef("P1", "1"), PhysicalPinRef("P2", "1"))


def test_lvs_sees_a_short_made_at_a_pad_from_both_sides() -> None:
    """The half that builds a dead board: a top jumper landing on the pads of two nets'
    traces shorts them, and while only a lead joined the sides LVS passed it."""
    lookup = make_lookup((one_pin_footprint("fp1"),))
    doc = dataclasses.replace(
        make_doc(
            (
                make_component("c1", "P1", "fp1", hole(0, 0)),
                make_component("c2", "P2", "fp1", hole(0, 2)),
                make_component("c3", "P3", "fp1", hole(4, 4)),
                make_component("c4", "P4", "fp1", hole(6, 4)),
            ),
            (
                solder_trace("t1", (hole(0, 0), hole(0, 1), hole(0, 2))),
                solder_trace("t2", (hole(4, 4), hole(5, 4), hole(6, 4))),
                top_jumper("j1", (hole(0, 1), hole(5, 4))),
            ),
        ),
        nets=(
            Net(id="n1", name="A", nodes=(NetNode("P1", "1"), NetNode("P2", "1"))),
            Net(id="n2", name="B", nodes=(NetNode("P3", "1"), NetNode("P4", "1"))),
        ),
    )

    result = run_lvs(doc, lookup)
    assert result.summary.shorts == 1, [issue.message for issue in result.issues]
