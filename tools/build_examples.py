"""Turn the example netlists into ready-to-open boards.

    python tools/build_examples.py            # rebuild every examples/*.perf
    python tools/build_examples.py --check     # verify only, write nothing

Each example ships twice: as the `.net` a schematic tool exports, and as the `.perf` that
importing, placing and routing it produces. The netlist alone would demonstrate the
importer; the board is what somebody wants to look at before installing anything.

The footprints are named here rather than left to ``ui.main.guess_footprint_id``, which
reads a reference designator and a pin count and can do no better than a first guess:
an LM317 is `U1` with three pins and guesses to a DIP-8, and a TO-220 regulator standing
in for an 8-pin DIP would make the heat-proximity rule and the 3D height check both
wrong. An example is the one place the answer should already be right.

Running this is also the closest thing the repository has to an end-to-end test of the
advertised workflow: import, place, route, check, export. It fails loudly if any example
stops routing cleanly, which is the point -- a broken example on the front page is worse
than no example.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from perfboard_studio import persist  # noqa: E402
from perfboard_studio.autoroute import plan_autoroute  # noqa: E402
from perfboard_studio.command import CommandBus, CommandContext  # noqa: E402
from perfboard_studio.commands import (  # noqa: E402
    AddBoardNotePayload,
    AddPartPayload,
    ImportNetlistPayload,
    PlaceBlockPayload,
    PlaceComponentPayload,
    create_document_id_generator,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.drc import placed_body_box, placed_entry, run_drc  # noqa: E402
from perfboard_studio.footprints import footprint_lookup  # noqa: E402
from perfboard_studio.geometry import (  # noqa: E402
    STANDARD_PRESETS,
    BoardFamily,
    BoardPreset,
    board_from_preset,
    board_note_anchor,
    hole_to_mm,
    mounting_hole_centre_mm,
    preset_edge_connectors,
    preset_mounting_holes,
    substrate_edges_mm,
    unusable_holes,
)
from perfboard_studio.guide import build_guide  # noqa: E402
from perfboard_studio.lvs import run_lvs  # noqa: E402
from perfboard_studio.model import Board, DocumentMeta, HoleCoord, PerfDocument  # noqa: E402
from perfboard_studio.netlist_import import import_placements  # noqa: E402
from perfboard_studio.parsers.kicad import parse_kicad_netlist  # noqa: E402
from perfboard_studio.parsers.kicad_parts import plan_import  # noqa: E402
from perfboard_studio.placer import (  # noqa: E402
    PlacementOptions,
    design_entries,
    plan_placement,
    recommended_board,
    suggest_boards,
)
from perfboard_studio.schematic import build_schematic  # noqa: E402

EXAMPLES = REPO_ROOT / "examples"

#: A fixed timestamp, because the engine has no clock and this script is a host. A real
#: date here would rewrite every example on every run and put the diff in the way of
#: whatever the commit was actually about.
STAMP = "2026-01-01T00:00:00Z"


class Example:
    """One example: its netlist, the BOARD PRODUCT to put it on, and what each part is.

    A product, not a hole count. Every example used to be on a grid nobody sells -- 32 x 22,
    30 x 20, 24 x 18 -- which quietly taught the wrong thing twice over: that a perfboard
    comes in whatever size you like, and that the finger strips and corner holes a real one
    arrives with are somebody else's problem. They are not: a finger is solid copper with no
    bore, and until the placer and the router were taught that (``geometry.unusable_holes``)
    putting these examples on real boards produced five DRC errors.

    ``preset`` is the name in ``geometry.STANDARD_PRESETS``, which is also what the size
    suggestion offers a user -- so every example ships on a board this application would
    have recommended for it, and on a board a supplier actually stocks.
    """

    def __init__(
        self,
        stem: str,
        title: str,
        preset: str,
        footprints: dict[str, str],
        family: BoardFamily = "double-sided-fr4",
        seed: int = 0,
        pin_names: dict[str, dict[str, str]] | None = None,
        labels: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.stem = stem
        self.title = title
        self.preset = preset
        #: Empty means the netlist is IMPORTED as a user imports one -- every part read for
        #: what it is by ``parsers.kicad_parts`` -- rather than told what each part is.
        self.footprints = footprints
        self.family = family
        self.seed = seed
        #: Names for pins the schematic leaves unnamed -- a terminal's "Pin_1" -- by ref.
        self.pin_names = pin_names or {}
        #: Words written on the board: (text, the ref it goes beside).
        self.labels = labels


CATALOGUE: tuple[Example, ...] = (
    Example(
        stem="ne555-astable",
        title="NE555 Astable",
        preset="4 x 6 cm",
        footprints={
            "U1": "dip-8",
            "R1": "r-axial-3",
            "R2": "r-axial-3",
            "R3": "r-axial-3",
            "C1": "c-elec-d5-p2",
            "C2": "c-disc-p2",
            "LED1": "led-5mm",
            "J1": "hdr-1x2",
        },
    ),
    Example(
        stem="lm317-supply",
        title="LM317 Adjustable Supply",
        preset="6 x 8 cm",
        footprints={
            # A TO-220 on its own, which is the whole reason this file names footprints:
            # the regulator is the hot part, and heat-proximity measures from its body
            # box. Guessed as a DIP-8 it would be neither the right shape nor the right
            # archetype, and the rule that matters most on this board would go quiet.
            "U1": "to220",
            "C1": "c-disc-p2",
            "C2": "c-elec-d5-p2",
            "C3": "c-elec-d6.3-p2",
            "R1": "r-axial-3",
            "R2": "r-axial-3",
            "RV1": "pot-3",
            "D1": "d-do41",
            "LED1": "led-5mm",
            "J1": "hdr-1x2",
            "J2": "hdr-1x2",
        },
    ),
    Example(
        stem="lpb1-booster",
        title="One-Transistor Guitar Booster",
        preset="7 x 9 cm",
        # FR-2 phenolic, deliberately: this is the board a pedal actually gets built on,
        # and it is the material whose pads lift. Choosing it here is what makes the
        # guide drop the iron temperature and DRC's pad-lifting rule speak up at all.
        family="single-sided-phenolic",
        footprints={
            "Q1": "to92",
            "R1": "r-axial-3",
            "R2": "r-axial-3",
            "R3": "r-axial-3",
            "R4": "r-axial-3",
            "C1": "c-film-p3",
            "C2": "c-elec-d5-p2",
            "C3": "c-elec-d6.3-p2",
            "RV1": "pot-3",
            "J1": "hdr-1x2",
            "J2": "hdr-1x2",
            "J3": "hdr-1x2",
        },
    ),
    Example(
        stem="arduino-io-shield",
        title="Arduino I/O Shield",
        preset="5 x 7 cm",
        footprints={
            "J1": "hdr-1x8",
            "J2": "hdr-1x6",
            "LED1": "led-5mm",
            "LED2": "led-5mm",
            "LED3": "led-5mm",
            "R1": "r-axial-3",
            "R2": "r-axial-3",
            "R3": "r-axial-3",
            "R4": "r-axial-3",
            "SW1": "sw-tactile",
            "C1": "c-disc-p2",
        },
    ),
    Example(
        stem="atmega328-relay",
        title="ATmega328 Relay Board",
        preset="9 x 15 cm",
        footprints={
            "U1": "dip-28",
            "U2": "to220",
            "K1": "relay-spdt",
            "Y1": "xtal-hc49",
            "Q1": "to92",
            "D1": "d-do41",
            "D2": "d-do35",
            "LED1": "led-5mm",
            "C1": "c-disc-p2",
            "C2": "c-disc-p2",
            "C3": "c-disc-p2",
            "C4": "c-disc-p2",
            "C5": "c-elec-d10-p3",
            "C6": "c-elec-d8-p3",
            "C7": "c-disc-p2",
            "R1": "r-axial-3",
            "R2": "r-axial-3",
            "R3": "r-axial-3",
            "RV1": "pot-3",
            "SW1": "sw-tactile",
            "J1": "screw-terminal-2",
            "J2": "screw-terminal-3",
            "J3": "hdr-1x6",
            "J4": "hdr-1x8",
        },
        # Swept, not picked: annealing is a random walk and the outcome genuinely varies.
        # Over six seeds this board came out between 742 and 788 of routed cost and between
        # 44 and 52 wires -- every one of them routing all 24 nets with no DRC error, which
        # is the reassuring half of that measurement. This is the cheapest of them.
        seed=5,
    ),
    Example(
        stem="nano-relay",
        title="Arduino Nano Relay Driver",
        # What Place on the Board recommends for it: 7 x 9 cm fits it at half full, past
        # the ratio that leaves room to wire.
        preset="9 x 15 cm",
        # No footprints: this one is imported the way a user imports a netlist, and it is
        # the example that shows what that reads -- the Nano, the BC547, the 1N4007 and the
        # 7805 come out of the catalog by their values, with their pin names; the rest by
        # their KiCad footprints; the Nano's pins, which KiCad numbers down one side and up
        # the other, renumbered by name; and the LED turned anode-first.
        footprints={},
        pin_names={
            "J1": {"1": "+12V", "2": "GND"},
            "J2": {"1": "COM", "2": "NO", "3": "NC"},
        },
        labels=(("12V IN", "J1"), ("LOAD", "J2")),
        # Swept like atmega328-relay's: seeds 0-7 all route clean, and 5 is the first with
        # the fewest wires and no terminal under a screw head.
        seed=5,
    ),
)


#: The parts of a board a preset does not decide: the pitch every one of these products
#: is drilled on, the substrate thickness, and the pad and drill diameters. Everything else
#: -- the grid, the material, whether it is single-sided, the border and the printed legend
#: -- comes from the product.
BASE_BOARD = Board(
    type="pad-per-hole",
    cols=60,
    rows=40,
    pitch=2.54,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.9,
    drill_diameter=0.8,
)


def _preset(example: Example) -> BoardPreset:
    for preset in STANDARD_PRESETS:
        if preset.name == example.preset and preset.family == example.family:
            return preset
    raise KeyError(f"no {example.family} preset called {example.preset!r}")


def _board(example: Example) -> Board:
    return board_from_preset(_preset(example), BASE_BOARD)


def build(example: Example, lookup, *, write: bool) -> bool:
    net_path = EXAMPLES / f"{example.stem}.net"
    parsed = parse_kicad_netlist(net_path.read_text(encoding="utf-8"))

    preset = _preset(example)
    board = _board(example)
    # The whole product, not just the grid: the finger strips down two edges and the screw
    # hole in each corner are what arrives in the envelope, and leaving them off would make
    # these examples boards nobody has. They are also the reason the placer and the router
    # had to learn about holes nothing can be soldered into -- see geometry.unusable_holes.
    document = replace(
        create_empty_document(
            DocumentMeta(name=example.title, created=STAMP, modified=STAMP), board
        ),
        edge_connectors=preset_edge_connectors(preset, board),
        mounting_holes=preset_mounting_holes(preset, board),
    )
    bus = CommandBus(
        document,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(document)),
    )

    # Parts first, then the netlist: importing nets that name a component which is not
    # on the board yet is legal but leaves the nets pointing at nothing, and the placer
    # would have no bodies to arrange.
    #
    # They go down in a column at the left edge and are immediately rearranged by the
    # placer, so the starting anchors only have to be legal, not good.
    if not example.footprints:
        if not _import_as_a_user_would(example, parsed, bus, lookup):
            return False
        return _finish(example, bus, lookup, preset, write=write)

    refs = sorted({node.component_ref for net in parsed.nets for node in net.nodes})
    missing = [ref for ref in refs if ref not in example.footprints]
    if missing:
        print(f"  {example.stem}: netlist names {missing} with no footprint in CATALOGUE")
        return False

    col, row = 0, 0
    for ref in refs:
        footprint_id = example.footprints[ref]
        footprint = lookup(footprint_id)
        if footprint is None:
            print(f"  {example.stem}: no such footprint {footprint_id!r} for {ref}")
            return False
        result = bus.dispatch(
            "component.place",
            PlaceComponentPayload(
                ref=ref,
                value=next(
                    (c.value or "" for c in parsed.components if c.ref == ref), ""
                ),
                footprint_id=footprint_id,
                anchor=HoleCoord(col, row),
                id=f"c-{ref.lower()}",
            ),
        )
        if not result.ok:
            print(f"  {example.stem}: placing {ref} refused [{result.code}] {result.message}")
            return False
        row += 3
        if row >= board.rows - 2:
            row = 0
            col += 4

    result = bus.dispatch("netlist.import", ImportNetlistPayload(nets=parsed.nets))
    if not result.ok:
        print(f"  {example.stem}: netlist import refused [{result.code}] {result.message}")
        return False
    return _finish(example, bus, lookup, preset, write=write)


def _import_as_a_user_would(example: Example, parsed, bus: CommandBus, lookup) -> bool:
    """File > Import KiCad Netlist and yes to placing the parts, without the dialogs."""
    plan = plan_import(parsed, bus.document, lookup)
    for ref, lines in sorted(plan.notes.items()):
        for line in lines:
            print(f"      {ref}: {line}")
    result = bus.dispatch("netlist.import", ImportNetlistPayload(nets=plan.nets))
    if not result.ok:
        print(f"  {example.stem}: netlist import refused [{result.code}] {result.message}")
        return False
    suggestions = [
        replace(
            suggestion,
            pin_names=tuple(example.pin_names[suggestion.ref].items()),
        )
        if suggestion.ref in example.pin_names
        else suggestion
        for suggestion in plan.suggestions.values()
    ]
    placements, left_out = import_placements(suggestions, bus.document, lookup)
    if left_out:
        print(f"  {example.stem}: no room for {left_out}")
        return False
    result = bus.dispatch(
        "block.place", PlaceBlockPayload(components=tuple(placements), label="import")
    )
    if not result.ok:
        print(f"  {example.stem}: placing refused [{result.code}] {result.message}")
        return False
    return True


def _finish(example: Example, bus: CommandBus, lookup, preset: BoardPreset, *, write: bool) -> bool:
    """Place, route, write on the board, check -- the same for every example."""
    plan = plan_placement(bus.document, lookup, PlacementOptions(seed=example.seed))
    if not plan.is_empty:
        result = bus.dispatch("component.moveMany", plan.payload())
        if not result.ok:
            print(f"  {example.stem}: placement refused [{result.code}] {result.message}")
            return False

    plan = plan_autoroute(bus.document, lookup)
    if not plan.is_empty:
        result = bus.dispatch("conductor.addMany", plan.payload())
        if not result.ok:
            print(f"  {example.stem}: routing refused [{result.code}] {result.message}")
            return False

    for text, ref in example.labels:
        spot = _free_spot_beside(bus.document, lookup, ref, text)
        if spot is None:
            print(f"  {example.stem}: no room to write {text!r} beside {ref}")
            return False
        at, dx, dy = spot
        result = bus.dispatch(
            "board.note.add",
            AddBoardNotePayload(text=text, at=at, offset_x_mm=dx, offset_y_mm=dy, size_mm=2.0),
        )
        if not result.ok:
            print(f"  {example.stem}: label refused [{result.code}] {result.message}")
            return False

    document = bus.document
    violations = run_drc(document, lookup)
    errors = [v for v in violations if v.severity == "error"]
    lvs = run_lvs(document, lookup)
    guide = build_guide(document, lookup)

    routing = plan.summary
    status = (
        f"  {example.stem:20} {preset.name:>10}  {len(document.components):2} parts  "
        f"{len(document.conductors):2} conductors  "
        f"{routing.nets_closed}/{routing.nets_considered} nets closed  "
        f"DRC {len(errors)} err / {len(violations) - len(errors)} warn  "
        f"LVS {'ok' if lvs.ok else 'MISMATCH'}  "
        f"{guide.total_steps} steps / {guide.checkpoint_count} checks"
    )
    print(status)

    ok = not errors and lvs.ok and routing.links_unrouted == 0
    if not ok:
        for v in errors[:5]:
            print(f"      DRC error {v.rule}: {v.message}")
        for issue in list(lvs.issues)[:5]:
            print(f"      LVS {issue.kind}: {issue.message}")
        if routing.links_unrouted:
            print(f"      {routing.links_unrouted} connection(s) not routed")

    if write and ok:
        # The modified stamp is the host's job, and this host is deterministic on
        # purpose -- see STAMP.
        document = replace(document, meta=replace(document.meta, modified=STAMP))
        # newline="\n" explicitly: .gitattributes stores every text file as LF, and the
        # default on Windows would write CRLF, so the file on disk would differ from the
        # file in the repository the moment it was committed.
        (EXAMPLES / f"{example.stem}.perf").write_text(
            persist.serialize_document(document), encoding="utf-8", newline="\n"
        )

    return ok


def _free_spot_beside(
    document: PerfDocument, lookup, ref: str, text: str, size_mm: float = 2.0
) -> tuple[HoleCoord, float, float] | None:
    """Where to write ``text`` beside part ``ref``: the nearest place to its body where the
    label clears every body, every terminal's mouth, the screw heads and the finger strips.
    Searched rather than placed by hand, because the placer decides where ``ref`` ends up."""
    board = document.board
    width = len(text) * size_mm * 0.8 + 1.0
    height = size_mm * 1.8
    boxes = []
    target = None
    for comp in document.components:
        footprint = lookup(comp.footprint_id)
        if footprint is None:
            continue
        box = placed_body_box(comp, footprint, board)
        boxes.append(box)
        entry = placed_entry(comp, footprint, board)
        if entry is not None:
            boxes.append(entry[0])
        if comp.ref == ref:
            target = ((box[0] + box[1]) / 2, (box[2] + box[3]) / 2)
    if target is None:
        return None
    for mount in document.mounting_holes:
        centre = mounting_hole_centre_mm(mount, board)
        r = mount.head_diameter / 2
        boxes.append((centre.x - r, centre.x + r, centre.y - r, centre.y + r))
    half = board.pitch / 2
    for key in unusable_holes(document):
        col, row = (int(part) for part in key.split(","))
        centre = hole_to_mm(HoleCoord(col, row), board)
        boxes.append((centre.x - half, centre.x + half, centre.y - half, centre.y + half))
    edges = substrate_edges_mm(board)
    step = board.pitch / 2
    candidates = []
    y = edges.min_y + height / 2
    while y <= edges.max_y - height / 2:
        x = edges.min_x + width / 2
        while x <= edges.max_x - width / 2:
            candidates.append(((x - target[0]) ** 2 + (y - target[1]) ** 2, x, y))
            x += step
        y += step
    for _distance, x, y in sorted(candidates):
        mine = (x - width / 2 - 0.5, x + width / 2 + 0.5, y - height / 2 - 0.5, y + height / 2 + 0.5)
        if any(
            mine[0] < box[1] and box[0] < mine[1] and mine[2] < box[3] and box[2] < mine[3]
            for box in boxes
        ):
            continue
        return board_note_anchor(x, y, board)
    return None


# ---------------------------------------------------------------------------
# The project example: a design with nothing on the board yet
# ---------------------------------------------------------------------------
#
# The four examples above are FINISHED boards -- placed, routed, checked -- which is what
# somebody wants to look at before installing anything. This one is the opposite end of
# the same workflow and there was no example of it: a circuit that has been drawn and not
# yet built, which is the state a project is actually in when the schematic panel is what
# you are looking at.
#
# It is a PROJECT (a folder) rather than a loose .perf, because that is what it is there to
# demonstrate: the board, the netlist it came from, and the outputs/ the tool writes, in
# one place. See project.py for why a project is a directory and the document inside it is
# still an ordinary .perf.

#: The project example's own folder, its document, and the netlist it is built from.
PROJECT_STEM = "ne555-blinker"
PROJECT_TITLE = "NE555 Blinker"

#: Deliberately a board nobody sells: 60 x 40 holes is the blank the application opens on,
#: and leaving the design on it is what gives "Place on the Board" a real question to ask.
#: The suggestion it makes -- the smallest stock board with room left to WIRE the circuit --
#: is the whole point of that step, and it cannot demonstrate itself on a board that is
#: already right.
PROJECT_BOARD = Board(
    type="pad-per-hole",
    cols=60,
    rows=40,
    pitch=2.54,
    thickness=1.6,
    material="FR4",
    pad_diameter=1.9,
    drill_diameter=1.0,
)

#: What each part in the netlist really is. Same argument as ``Example.footprints``: a
#: reference and a pin count is not enough to tell a potentiometer from a TO-92.
PROJECT_FOOTPRINTS = {
    "U1": "dip-8",
    "R1": "r-axial-3",
    "R2": "r-axial-3",
    "RV1": "pot-3",
    "C1": "c-elec-d5-p2",
    "C2": "c-disc-p2",
    "C3": "c-disc-p2",
    "LED1": "led-5mm",
    "J1": "screw-terminal-2",
    "J2": "hdr-1x3",
}


def build_project(lookup, *, write: bool) -> bool:
    """The design, in a project folder, with nothing placed.

    Stops where the other examples begin. Every part goes in through ``part.add`` -- which
    takes no anchor, because "where does this go" is the question placement answers -- and
    the netlist through ``netlist.import``, so the document that comes out is a circuit
    with no board yet. Opening it and pressing Place on the Board is the workflow this
    example exists to be the start of.
    """
    folder = EXAMPLES / PROJECT_STEM
    parsed = parse_kicad_netlist((folder / "netlist.net").read_text(encoding="utf-8"))

    document = create_empty_document(
        DocumentMeta(name=PROJECT_TITLE, created=STAMP, modified=STAMP), PROJECT_BOARD
    )
    bus = CommandBus(
        document,
        create_standard_registry(),
        CommandContext(next_id=create_document_id_generator(document)),
    )

    refs = sorted({node.component_ref for net in parsed.nets for node in net.nodes})
    missing = [ref for ref in refs if ref not in PROJECT_FOOTPRINTS]
    if missing:
        print(f"  {PROJECT_STEM}: netlist names {missing} with no footprint")
        return False

    for ref in refs:
        footprint_id = PROJECT_FOOTPRINTS[ref]
        if lookup(footprint_id) is None:
            print(f"  {PROJECT_STEM}: no such footprint {footprint_id!r} for {ref}")
            return False
        result = bus.dispatch(
            "part.add",
            AddPartPayload(
                ref=ref,
                footprint_id=footprint_id,
                value=next((c.value or "" for c in parsed.components if c.ref == ref), ""),
                id=f"p-{ref.lower()}",
            ),
        )
        if not result.ok:
            print(f"  {PROJECT_STEM}: adding {ref} refused [{result.code}] {result.message}")
            return False

    result = bus.dispatch("netlist.import", ImportNetlistPayload(nets=parsed.nets))
    if not result.ok:
        print(f"  {PROJECT_STEM}: netlist import refused [{result.code}] {result.message}")
        return False

    document = bus.document
    drawing = build_schematic(document, lookup)
    suggestions = suggest_boards(document.board, design_entries(document), document.nets, lookup)
    best = recommended_board(suggestions)

    print(
        f"  {PROJECT_STEM:20} {len(document.parts):2} parts  "
        f"{len(document.nets)} nets  "
        f"{len(drawing.symbols)} symbol(s) / {len(drawing.rails)} rail(s)  "
        f"suggests {best.preset.name if best else 'nothing'}"
    )

    # An undefined symbol means a net names a part nothing defines, which on a design
    # example is the whole circuit being wrong rather than a note in a panel.
    undefined = [symbol.ref for symbol in drawing.symbols if symbol.undefined]
    if undefined:
        print(f"      the sheet cannot draw {undefined}")
    ok = not undefined and best is not None and not document.components
    if not ok and best is None:
        print("      no stock board suits this circuit")

    if write and ok:
        document = replace(document, meta=replace(document.meta, modified=STAMP))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{PROJECT_STEM}.perf").write_text(
            persist.serialize_document(document), encoding="utf-8", newline="\n"
        )

    return ok


def main(argv: list[str]) -> int:
    write = "--check" not in argv
    lookup = footprint_lookup()
    print(f"{'building' if write else 'checking'} {len(CATALOGUE) + 1} examples\n")
    results = [build(example, lookup, write=write) for example in CATALOGUE]
    results.append(build_project(lookup, write=write))
    failed = results.count(False)
    print()
    if failed:
        print(f"{failed} of {len(results)} examples did NOT come out clean")
        return 1
    print(f"all {len(results)} examples route cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
