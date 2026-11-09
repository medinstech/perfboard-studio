"""Several boards in one document, each seen alone.

A system is one document: the first board is the document's own top-level fields and every
other is an ``ExtraBoard`` in ``doc.boards``, all of them sharing one design (``parts``,
``nets``, the sheet). The rest of the engine knows ONE board -- DRC, the router, the placer,
stripboard, the guide, both renderers and the STEP export read ``doc.board`` and
``doc.components`` and are right to -- so it is never asked about another: it is handed
:func:`board_document`, the single-board document it already understands, and whatever it
changed goes back through :func:`merge_board`. See docs/ARCHITECTURE.md, "Several boards
are one document, and each is seen alone".

Hangs off ``model`` alone, and is pure: no clock, no filesystem.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, fields, replace

from .geometry import all_pin_holes, board_outline_mm
from .model import (
    BoardId,
    Cable,
    CableEnd,
    CableWire,
    ComponentInstance,
    ExtraBoard,
    Footprint,
    Mm,
    PerfDocument,
    SchematicPart,
)
from .phrasebook import guide_language, phrasebook

#: The first board's id: never written, because the first board is the document's own
#: top-level fields. No extra board may take it.
FIRST_BOARD: BoardId = "main"

#: The fields a board has of its own, on ``PerfDocument`` for the first board and on
#: ``ExtraBoard`` for every other. Everything else on the document is the shared design.
#: ``test_system`` holds both dataclasses to this list, so a field added to one is a field
#: somebody has to decide about.
BOARD_FIELDS: tuple[str, ...] = (
    "board",
    "components",
    "conductors",
    "cuts",
    "mounting_holes",
    "edge_connectors",
    "board_notes",
    "height_limit_mm",
    "body_clearance_mm",
)


#: The fields about the SYSTEM rather than any one board or the design: the other boards,
#: and the cables between them. A board's view holds none of them, and the merge takes
#: them back from the document, so no board command can change them.
SYSTEM_FIELDS: tuple[str, ...] = ("boards", "cables")

#: The first board's own name, which every other board keeps on ``ExtraBoard.name``: not
#: shared, and not a field a board command changes, so a view carries its board's stored
#: name and the merge leaves every name where it was. What a board is CALLED is
#: :func:`board_title`, asked of the whole document.
NAME_FIELD = "board_name"


def board_ids(doc: PerfDocument) -> tuple[BoardId, ...]:
    """Every board of the document, the first board first."""
    return (FIRST_BOARD, *(extra.id for extra in doc.boards))


def extra_board(doc: PerfDocument, board_id: BoardId) -> ExtraBoard:
    """The extra board ``board_id``. Raises ``KeyError`` for the first board's id or one
    the document does not have."""
    for extra in doc.boards:
        if extra.id == board_id:
            return extra
    raise KeyError(board_id)


def board_document(doc: PerfDocument, board_id: BoardId = FIRST_BOARD) -> PerfDocument:
    """Board ``board_id`` as a document of one board: its own fields, the shared design,
    and no other board -- exactly the document every single-board module expects."""
    if board_id == FIRST_BOARD:
        return replace(doc, boards=(), cables=())
    extra = extra_board(doc, board_id)
    return replace(
        doc,
        boards=(),
        cables=(),
        board_name=extra.name,
        **{name: getattr(extra, name) for name in BOARD_FIELDS},
    )


#: Millimetres of bench between two boards where a system is laid out in a row.
BOARD_GAP_MM: Mm = 25.0


def board_row(doc: PerfDocument, gap_mm: Mm = BOARD_GAP_MM) -> dict[BoardId, tuple[Mm, Mm]]:
    """Where each board's own frame -- ``geometry.hole_to_mm``'s, hole A1 at the origin and
    rows growing down -- sits when the system is laid out in a row: in the document's order,
    left to right, ``gap_mm`` between two substrates, every top edge on one line.

    The System view and the System's 3D both lay the boards out by it, so a board is in the
    same place in each. Nothing about it is saved: where a person may put a board is a later
    decision, and it would be the document's.
    """
    row: dict[BoardId, tuple[Mm, Mm]] = {}
    left = 0.0
    for board_id in board_ids(doc):
        outline = board_outline_mm(board_document(doc, board_id).board)
        row[board_id] = (left - outline.x, -outline.y)
        left += outline.width + gap_mm
    return row


def merge_board(doc: PerfDocument, board_id: BoardId, seen: PerfDocument) -> PerfDocument:
    """``doc`` with board ``board_id`` as ``seen`` has it.

    ``seen`` is what :func:`board_document` gave, after whatever was done to it. That
    board's own fields come from it, and so does the shared design -- a part placed on
    this board has left ``parts``, a net connected here is the system's net. Every other
    board is ``doc``'s, untouched.
    """
    if seen.boards or seen.cables:
        raise ValueError("a board's view of the system holds no other board and no cable")
    if board_id == FIRST_BOARD:
        return replace(seen, boards=doc.boards, cables=doc.cables, board_name=doc.board_name)
    extra = extra_board(doc, board_id)
    changed = replace(extra, **{name: getattr(seen, name) for name in BOARD_FIELDS})
    return replace(
        seen,
        boards=tuple(changed if other.id == board_id else other for other in doc.boards),
        cables=doc.cables,
        board_name=doc.board_name,
        **{name: getattr(doc, name) for name in BOARD_FIELDS},
    )


def shared_fields() -> tuple[str, ...]:
    """The document's fields that every board shares: everything that is not a board's
    own, nor the system's."""
    return tuple(
        f.name
        for f in fields(PerfDocument)
        if f.name not in BOARD_FIELDS and f.name not in SYSTEM_FIELDS and f.name != NAME_FIELD
    )


def placed_components(doc: PerfDocument) -> tuple[tuple[BoardId, ComponentInstance], ...]:
    """Every part placed on any board, with the board it is on: the first board's first,
    each board's in its own order. On one board, ``doc.components`` with ``"main"``."""
    return tuple(
        (board_id, component)
        for board_id in board_ids(doc)
        for component in board_document(doc, board_id).components
    )


def every_component(doc: PerfDocument) -> tuple[ComponentInstance, ...]:
    """Every part placed on any board of the document. What ``doc.components`` meant when
    a document had one board -- and still means, on a board's own view."""
    return tuple(component for _, component in placed_components(doc))


def circuit_parts(doc: PerfDocument) -> tuple[ComponentInstance | SchematicPart, ...]:
    """Every part of the circuit, wherever it is: placed on any board, then waiting in the
    design. The question ``(*doc.components, *doc.parts)`` asked on one board, and the one
    reader of it that has to see every board -- ERC, the sheet, the Parts list, a free
    reference -- asks here, so that a part on the second board is never "not defined"."""
    return (*every_component(doc), *doc.parts)


def board_of(doc: PerfDocument, component_id: str) -> BoardId | None:
    """The board a placed part is on, or ``None`` when no board has it (it is in the
    design, or nowhere)."""
    return next((b for b, c in placed_components(doc) if c.id == component_id), None)


def references_in_use(doc: PerfDocument) -> set[str]:
    """Every reference the document gives out: the parts on every board, the parts in the
    design and the cables. One namespace, because a net node is a ``(ref, pin)`` and a cable
    is listed by its reference beside the parts."""
    return {part.ref for part in circuit_parts(doc)} | {cable.ref for cable in doc.cables}


def board_title(doc: PerfDocument, board_id: BoardId, language: str = "en") -> str:
    """What a board is CALLED, everywhere -- the strip, the System view, the guide, LVS,
    the exports and the MCP server all ask this, so a board is one name in all of them.

    Its own name when somebody gave it one. Otherwise, in a document of several boards,
    its place among them, "Board 2", in ``language`` (the guide's phrasebook, so "Kart 2"
    in Turkish); and on a document of one board, the document's own name, which is all a
    board has ever been called there.
    """
    own = doc.board_name if board_id == FIRST_BOARD else extra_board(doc, board_id).name
    if own.strip():
        return own.strip()
    ids = board_ids(doc)
    if len(ids) == 1:
        return doc.meta.name
    say = phrasebook(guide_language(language))
    return say("Board {n}", n=ids.index(board_id) + 1)


def connector_of(doc: PerfDocument, end: CableEnd) -> ComponentInstance | None:
    """The part a cable end is fitted to, or ``None`` when that board has no such part (or
    there is no such board)."""
    if end.board not in board_ids(doc):
        return None
    return next(
        (c for c in board_document(doc, end.board).components if c.id == end.connector), None
    )


@dataclass(frozen=True, slots=True)
class CablePairing:
    """The wires a cable between two connectors takes, paired by net, and what was not."""

    wires: tuple[CableWire, ...]
    #: Why each pin left without a wire was left, one English sentence each (engine text).
    unpaired: tuple[str, ...]


def pair_by_net(doc: PerfDocument, a: CableEnd, b: CableEnd) -> CablePairing:
    """A cable's wires from the design itself: a pin of ``a`` and a pin of ``b`` on the same
    net take a wire between them, which is what the net says the cable is for.

    Only where it is certain. A net on one connector and not the other has nothing to pair
    with; a net on two pins of either has more than one way to go, and which pin goes to
    which is the person's to say. Both are left unpaired and said, never guessed: a guessed
    wire is a crossed cable nobody chose. A pin on no net takes no wire.
    """
    a_part = connector_of(doc, a)
    b_part = connector_of(doc, b)
    if a_part is None or b_part is None:
        return CablePairing((), ("A cable's two ends have to be parts placed on boards of this document.",))
    wires: list[CableWire] = []
    unpaired: list[str] = []
    for net in doc.nets:
        on_a = sorted({n.pin for n in net.nodes if n.component_ref == a_part.ref}, key=_pin_order)
        on_b = sorted({n.pin for n in net.nodes if n.component_ref == b_part.ref}, key=_pin_order)
        if not on_a and not on_b:
            continue
        if len(on_a) == 1 and len(on_b) == 1:
            wires.append(CableWire(a_pin=on_a[0], b_pin=on_b[0]))
        elif not on_b:
            unpaired.append(
                f"{a_part.ref} {_pins(on_a)} ({net.name}): {b_part.ref} has no pin on {net.name}."
            )
        elif not on_a:
            unpaired.append(
                f"{b_part.ref} {_pins(on_b)} ({net.name}): {a_part.ref} has no pin on {net.name}."
            )
        else:
            unpaired.append(
                f"{net.name} is on {a_part.ref} {_pins(on_a)} and {b_part.ref} {_pins(on_b)}: "
                f"which goes to which is yours to say."
            )
    wires.sort(key=lambda wire: _pin_order(wire.a_pin))
    return CablePairing(tuple(wires), tuple(unpaired))


def _pin_order(pin: str) -> tuple[int, str]:
    return (int(pin), "") if pin.isdigit() else (1_000_000, pin)


def _pins(pins: list[str]) -> str:
    return f"pin {pins[0]}" if len(pins) == 1 else "pins " + ", ".join(pins)


#: The gauges a cable wire may be given, as American Wire Gauge numbers.
CABLE_GAUGE_RANGE: tuple[int, int] = (10, 32)


def cable_problem(doc: PerfDocument, cable: Cable) -> str | None:
    """Why ``cable`` is not a cable this document can hold, or ``None``.

    The references have to resolve -- both ends a part placed on a board of this document
    -- and no pin can carry two wires, one lead to a hole as on a breadboard. These are
    REFUSED (CLAUDE.md: what makes the document whole is a command's), by ``cable.add`` and
    ``cable.update``, by every command whose result would leave a cable dangling, and by
    ``persist`` at load.

    Whether a wire's pin is a pin of its part is NOT asked here: it takes the footprint
    registry, which a command has none of and a file is opened under whatever version of
    it the reader has. ERC's ``pin-not-on-part`` reports it, as it does for a net naming a
    pin the part lacks. A wire joining two different NETS is not a problem here either: the
    document is still whole, and LVS reports it.
    """
    if not cable.ref.strip():
        return "A cable needs a reference, such as W1."
    if not cable.wires:
        return f"{cable.ref} has no wires; a cable carries at least one."
    if cable.length_mm is not None and not cable.length_mm > 0:
        return f"{cable.ref}'s length has to be more than nothing."
    ends: dict[str, ComponentInstance] = {}
    for side, end in (("a", cable.a), ("b", cable.b)):
        part = connector_of(doc, end)
        if part is None:
            return (
                f"{cable.ref}'s {side} end is fitted to a part that is not on board "
                f"{end.board!r}."
            )
        ends[side] = part
    if cable.a == cable.b:
        return f"{cable.ref} runs from a connector back to itself."
    for side in ("a", "b"):
        part = ends[side]
        taken: set[str] = set()
        for wire in cable.wires:
            pin = wire.a_pin if side == "a" else wire.b_pin
            if pin in taken:
                return f"Two wires of {cable.ref} land on {part.ref} pin {pin}."
            taken.add(pin)
    for wire in cable.wires:
        if wire.gauge_awg is not None and not (
            CABLE_GAUGE_RANGE[0] <= wire.gauge_awg <= CABLE_GAUGE_RANGE[1]
        ):
            return f"AWG {wire.gauge_awg} is not a gauge a cable here is made of."
    return None


def cable_span_mm(
    doc: PerfDocument, cable: Cable, lookup: Callable[[str], Footprint | None]
) -> Mm | None:
    """How far apart a cable's ends are in the System's row (:func:`board_row`): the longest
    straight run between the two pins of any one of its wires, hole centre to hole centre.
    ``None`` when an end or a pin cannot be found -- ``cable_problem`` and ERC say why.

    A fact about the PICTURE, not the build: the row is where the System view and its 3D
    put the boards, and it is not saved. That is why a cable shorter than this is said as
    information and never as a finding (docs/ARCHITECTURE.md, "Several boards are one
    document, and each is seen alone").
    """
    row = board_row(doc)
    points: list[dict[str, tuple[Mm, Mm]]] = []
    for end in (cable.a, cable.b):
        part = connector_of(doc, end)
        footprint = lookup(part.footprint_id) if part is not None else None
        if part is None or footprint is None:
            return None
        board = board_document(doc, end.board).board
        dx, dy = row[end.board]
        points.append(
            {
                pin.number: (dx + hole.col * board.pitch, dy + hole.row * board.pitch)
                for pin, hole in all_pin_holes(part, footprint)
            }
        )
    a_pins, b_pins = points
    spans = [
        math.dist(a_pins[wire.a_pin], b_pins[wire.b_pin])
        for wire in cable.wires
        if wire.a_pin in a_pins and wire.b_pin in b_pins
    ]
    return max(spans) if spans else None


def cables_short_in_row(
    doc: PerfDocument, lookup: Callable[[str], Footprint | None]
) -> list[tuple[Cable, Mm]]:
    """Every cable given a length shorter than its ends are apart in the System's row, with
    that distance -- what the 3D draws pulled straight, and the System says in words. A
    cable with no length is cut to fit and is never short."""
    short: list[tuple[Cable, Mm]] = []
    for cable in doc.cables:
        if cable.length_mm is None:
            continue
        span = cable_span_mm(doc, cable, lookup)
        if span is not None and cable.length_mm < span:
            short.append((cable, span))
    return short
