"""The command bus as the board in front sees it.

The window shows one board of a system at a time, and everything in it that is about THE
board -- the 2D scene, the 3D view, the guide, DRC, placing and routing -- was written for a
document of one board and is right to be (docs/ARCHITECTURE.md, "Several boards are one
document, and each is seen alone"). So the window's bus is a :class:`BoardBus`: one
``CommandBus``, holding the whole system and its one undo stack, whose ``document`` is the
board in front's view (``system.board_document``) and whose ``dispatch`` sends a board's
command through ``board.on`` for that board. A design command (the nets, the sheet, the
design's parts) and a system command go to the document as they are. What reads the whole
system asks for ``system_document``.

With the first board in front -- every single-board document, always -- it is the bus it
extends: ``document`` is the document without its (empty) system fields and every command
goes in as it came.
"""

from __future__ import annotations

from typing import Any

from perfboard_studio.command import CommandBus, CommandContext, CommandRegistry, DispatchResult
from perfboard_studio.commands import OnBoardPayload, command_scope
from perfboard_studio.model import BoardId, PerfDocument
from perfboard_studio.system import FIRST_BOARD, board_document, board_ids


class BoardBus(CommandBus):
    """A ``CommandBus`` that shows one board of its system and routes commands to it."""

    def __init__(
        self,
        initial: PerfDocument,
        registry: CommandRegistry,
        ctx: CommandContext,
        board_id: BoardId = FIRST_BOARD,
    ) -> None:
        super().__init__(initial, registry, ctx)
        self._board_id = board_id
        self._view: tuple[PerfDocument, BoardId, PerfDocument] | None = None

    @property
    def board_id(self) -> BoardId:
        """The board in front. A board taken out of the system -- deleted, or its adding
        undone -- leaves the first board in front."""
        if self._board_id not in board_ids(self._document):
            return FIRST_BOARD
        return self._board_id

    def show(self, board_id: BoardId) -> None:
        """Put ``board_id`` in front. Raises ``KeyError`` for a board the system lacks."""
        if board_id not in board_ids(self._document):
            raise KeyError(board_id)
        self._board_id = board_id

    @property
    def document(self) -> PerfDocument:
        """The board in front, as a document of that board alone. Remembered for the system
        document it was made from, because the window asks for it a hundred times a
        refresh."""
        if not self._document.boards and not self._document.cables:
            # One board: the document itself, the very object -- so nothing that compares a
            # document by identity sees a single-board window change.
            return self._document
        board_id = self.board_id
        cached = self._view
        if cached is not None and cached[0] is self._document and cached[1] == board_id:
            return cached[2]
        view = board_document(self._document, board_id)
        self._view = (self._document, board_id, view)
        return view

    def dispatch(self, type_: str, payload: Any) -> DispatchResult:
        """A board's command on the board in front, through ``board.on`` when that is not
        the first; a design's or the system's on the document, as it came."""
        board_id = self.board_id
        if board_id == FIRST_BOARD or command_scope(type_) != "board":
            return super().dispatch(type_, payload)
        return super().dispatch(
            "board.on", OnBoardPayload(board=board_id, type=type_, payload=payload)
        )
