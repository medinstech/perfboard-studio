"""Driving the board designer in a test: open it on a board, choose as a person would.

Board Setup's tests moved to the designer when it retired (``ui/designer.py``), and these
are the few verbs they share. Every one goes through the dialog's own handlers, so what is
tested is what a click does.
"""

from __future__ import annotations

from typing import Any

from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import Board, EdgeConnector, MountingHole


def designer_on(
    board: Board,
    features: tuple[tuple[EdgeConnector, ...], tuple[MountingHole, ...]] = ((), ()),
) -> Any:
    """The designer, opened on ``board`` with ``features``, applying nothing."""
    from perfboard_studio.ui.designer import BoardDesigner

    return BoardDesigner(
        None, base=board, lookup=footprint_lookup(), saved=[], apply=lambda _d: None,
        features=features,
    )


def shown(dialog: Any, path: str) -> bool:
    """Whether the designer's row for ``path`` is on show."""
    form, holder = dialog._rows[path]
    return bool(form.isRowVisible(holder))


def section_shown(dialog: Any, key: str) -> bool:
    return not dialog._sections[key][0].isHidden()


def choose_family(dialog: Any, family_id: str) -> None:
    """By id, among what the dialog lists: "This board" first when no catalogue family
    makes the board that is open."""
    dialog.families.setCurrentRow([f.id for f in dialog._everything()].index(family_id))


def choose_size(dialog: Any, name: str) -> None:
    """A size the picker lists, by its name: "400", "5 x 7 cm"."""
    from perfboard_studio.ui.designer import _listed

    listed = _listed(dialog._current_family())
    dialog._on_stock_size(next(i for i, size in enumerate(listed) if size.name == name))


def choose_channel(dialog: Any, key: str) -> None:
    """A breadboard's channel as the list offers it: "300", "1000", "900-flex"."""
    dialog.channel.setCurrentIndex(dialog.channel.findData(key))
    dialog._on_channel()


def choose_kind(dialog: Any, kind: str) -> None:
    dialog.type.setCurrentIndex(dialog.type.findData(kind))
    dialog._on_kind()
