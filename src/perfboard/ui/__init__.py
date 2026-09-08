"""Perfboard Studio desktop UI.

The real application, promoted from ``prototypes/qt/`` (see that directory's module
docstrings for the evaluation this grew out of). Unlike the prototype, nothing in this
package carries its own model: documents are the engine's ``PerfDocument``
(``perfboard.model``), loaded via ``perfboard.persist``, and every mutation is
dispatched through a ``perfboard.command.CommandBus`` rather than written in place.
That is what keeps undo/redo, DRC-after-every-change and a future agent-driven editor
all consistent with each other and with the CLI/MCP surface.
"""

from __future__ import annotations
