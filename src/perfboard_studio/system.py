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

from dataclasses import fields, replace

from .model import BoardId, ExtraBoard, PerfDocument

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
        return replace(doc, boards=())
    extra = extra_board(doc, board_id)
    return replace(
        doc, boards=(), **{name: getattr(extra, name) for name in BOARD_FIELDS}
    )


def merge_board(doc: PerfDocument, board_id: BoardId, seen: PerfDocument) -> PerfDocument:
    """``doc`` with board ``board_id`` as ``seen`` has it.

    ``seen`` is what :func:`board_document` gave, after whatever was done to it. That
    board's own fields come from it, and so does the shared design -- a part placed on
    this board has left ``parts``, a net connected here is the system's net. Every other
    board is ``doc``'s, untouched.
    """
    if seen.boards:
        raise ValueError("a board's view of the system holds no other board")
    if board_id == FIRST_BOARD:
        return replace(seen, boards=doc.boards)
    extra = extra_board(doc, board_id)
    changed = replace(extra, **{name: getattr(seen, name) for name in BOARD_FIELDS})
    return replace(
        seen,
        boards=tuple(changed if other.id == board_id else other for other in doc.boards),
        **{name: getattr(doc, name) for name in BOARD_FIELDS},
    )


def shared_fields() -> tuple[str, ...]:
    """The document's fields that every board shares: everything that is not a board's
    own, nor the list of boards."""
    return tuple(
        f.name for f in fields(PerfDocument) if f.name not in BOARD_FIELDS and f.name != "boards"
    )
