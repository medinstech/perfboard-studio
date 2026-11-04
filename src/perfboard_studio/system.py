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

from collections.abc import Callable
from dataclasses import fields, replace

from .model import BoardId, Cable, CableEnd, ComponentInstance, ExtraBoard, Footprint, PerfDocument

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
        doc, boards=(), cables=(), **{name: getattr(extra, name) for name in BOARD_FIELDS}
    )


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
        return replace(seen, boards=doc.boards, cables=doc.cables)
    extra = extra_board(doc, board_id)
    changed = replace(extra, **{name: getattr(seen, name) for name in BOARD_FIELDS})
    return replace(
        seen,
        boards=tuple(changed if other.id == board_id else other for other in doc.boards),
        cables=doc.cables,
        **{name: getattr(doc, name) for name in BOARD_FIELDS},
    )


def shared_fields() -> tuple[str, ...]:
    """The document's fields that every board shares: everything that is not a board's
    own, nor the system's."""
    return tuple(
        f.name
        for f in fields(PerfDocument)
        if f.name not in BOARD_FIELDS and f.name not in SYSTEM_FIELDS
    )


def connector_of(doc: PerfDocument, end: CableEnd) -> ComponentInstance | None:
    """The part a cable end is fitted to, or ``None`` when that board has no such part (or
    there is no such board)."""
    if end.board not in board_ids(doc):
        return None
    return next(
        (c for c in board_document(doc, end.board).components if c.id == end.connector), None
    )


#: The gauges a cable wire may be given, as American Wire Gauge numbers.
CABLE_GAUGE_RANGE: tuple[int, int] = (10, 32)


def cable_problem(
    doc: PerfDocument, cable: Cable, lookup: Callable[[str], Footprint | None] | None = None
) -> str | None:
    """Why ``cable`` is not a cable this document can hold, or ``None``.

    The references have to resolve -- both ends a part placed on a board of this document
    -- and no pin can carry two wires, one lead to a hole as on a breadboard. These are
    REFUSED (CLAUDE.md: what makes the document whole is a command's), by ``cable.add`` and
    ``cable.update`` and by every board command whose result would leave a cable dangling.

    Whether a wire's pin is a pin of its part takes a footprint ``lookup``, which a command
    has none of (``net.connect`` does not ask it either), so it is asked only when one is
    given -- by DRC, which reports it. A wire joining two different NETS is not a problem
    here at all: the document is still whole, and DRC and LVS report it.
    """
    if not cable.ref.strip():
        return "A cable needs a reference, such as W1."
    if not cable.wires:
        return f"{cable.ref} has no wires; a cable carries at least one."
    if cable.length_mm is not None and not cable.length_mm > 0:
        return f"{cable.ref}'s length has to be more than nothing."
    ends: dict[str, tuple[ComponentInstance, set[str] | None]] = {}
    for side, end in (("a", cable.a), ("b", cable.b)):
        part = connector_of(doc, end)
        if part is None:
            return (
                f"{cable.ref}'s {side} end is fitted to a part that is not on board "
                f"{end.board!r}."
            )
        footprint = None if lookup is None else lookup(part.footprint_id)
        ends[side] = (part, None if footprint is None else {p.number for p in footprint.pins})
    if cable.a == cable.b:
        return f"{cable.ref} runs from a connector back to itself."
    for side in ("a", "b"):
        part, pins = ends[side]
        taken: set[str] = set()
        for wire in cable.wires:
            pin = wire.a_pin if side == "a" else wire.b_pin
            if pins is not None and pin not in pins:
                return f"{part.ref} has no pin {pin} for {cable.ref} to land on."
            if pin in taken:
                return f"Two wires of {cable.ref} land on {part.ref} pin {pin}."
            taken.add(pin)
    for wire in cable.wires:
        if wire.gauge_awg is not None and not (
            CABLE_GAUGE_RANGE[0] <= wire.gauge_awg <= CABLE_GAUGE_RANGE[1]
        ):
            return f"AWG {wire.gauge_awg} is not a gauge a cable here is made of."
    return None
