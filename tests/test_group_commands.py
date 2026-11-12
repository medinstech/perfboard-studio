"""Several parts turned, flipped, updated, locked or deleted as ONE command
(``component.rotateMany``, ``mirrorMany``, ``updateMany``, ``lockMany``, ``deleteMany``).

What is pinned: each is ``component.moveMany``'s shape -- one gesture, one undo step,
all-or-nothing, a locked part refusing the whole group by name, an empty group and a part
named twice refused -- and each member does exactly what its single command does, so a
group of one is that command.
"""

from __future__ import annotations

import pathlib

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    DeleteComponentPayload,
    DeleteComponentsPayload,
    LockComponentsPayload,
    MirrorComponentPayload,
    MirrorComponentsPayload,
    RotateComponentPayload,
    RotateComponentsPayload,
    UpdateComponentPayload,
    UpdateComponentsPayload,
    create_standard_registry,
)
from perfboard_studio.model import PerfDocument

GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "tools" / "diffcheck" / "golden" / "dense.perf"


def _bus() -> CommandBus:
    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    return CommandBus(document, create_standard_registry(), CommandContext(next_id=create_id_generator()))


def _unlocked(document: PerfDocument, count: int) -> list[str]:
    ids = [c.id for c in document.components if not c.locked][:count]
    assert len(ids) == count
    return ids


def _by_id(document: PerfDocument, component_id: str):  # type: ignore[no-untyped-def]
    return next(c for c in document.components if c.id == component_id)


def test_a_group_turned_together_is_one_undo_step() -> None:
    bus = _bus()
    before = bus.document
    ids = _unlocked(before, 3)
    result = bus.dispatch(
        "component.rotateMany",
        RotateComponentsPayload(rotations=tuple(RotateComponentPayload(id=i, rotation=90) for i in ids)),
    )
    assert result.ok, result
    assert all(_by_id(bus.document, i).rotation == 90 for i in ids)
    assert bus.history() == ("Rotate 3 components",)
    bus.undo()
    assert bus.document == before


def test_flip_update_and_delete_are_one_step_each() -> None:
    bus = _bus()
    ids = _unlocked(bus.document, 2)
    steps = [
        ("component.mirrorMany", MirrorComponentsPayload(mirrors=tuple(MirrorComponentPayload(id=i, mirrored=True) for i in ids))),
        ("component.updateMany", UpdateComponentsPayload(updates=tuple(UpdateComponentPayload(id=i, value="10k") for i in ids))),
        ("component.deleteMany", DeleteComponentsPayload(ids=tuple(ids))),
    ]
    for kind, payload in steps:
        assert bus.dispatch(kind, payload).ok
    assert len(bus.history()) == 3
    assert not any(c.id in ids for c in bus.document.components)
    bus.undo()
    assert all(_by_id(bus.document, i).value == "10k" and _by_id(bus.document, i).mirrored for i in ids)


def test_a_locked_part_refuses_the_whole_group_by_name() -> None:
    bus = _bus()
    first, second = _unlocked(bus.document, 2)
    assert bus.dispatch("component.update", UpdateComponentPayload(id=second, locked=True)).ok
    before = bus.document
    result = bus.dispatch(
        "component.rotateMany",
        RotateComponentsPayload(
            rotations=(RotateComponentPayload(id=first, rotation=90), RotateComponentPayload(id=second, rotation=90))
        ),
    )
    assert not result.ok
    assert result.code == "component-locked"
    assert _by_id(before, second).ref in result.message
    assert bus.document is before  # Not even the first one turned.


@pytest.mark.parametrize(
    "kind, payload",
    [
        ("component.rotateMany", RotateComponentsPayload(rotations=())),
        ("component.mirrorMany", MirrorComponentsPayload(mirrors=())),
        ("component.updateMany", UpdateComponentsPayload(updates=())),
        ("component.lockMany", LockComponentsPayload(ids=(), locked=True)),
        ("component.deleteMany", DeleteComponentsPayload(ids=())),
    ],
)
def test_an_empty_group_is_refused_rather_than_put_on_the_undo_stack(kind: str, payload: object) -> None:
    bus = _bus()
    result = bus.dispatch(kind, payload)
    assert not result.ok and result.code == "nothing-to-do"
    assert not bus.history()


def test_a_part_named_twice_is_refused() -> None:
    bus = _bus()
    (only,) = _unlocked(bus.document, 1)
    result = bus.dispatch("component.deleteMany", DeleteComponentsPayload(ids=(only, only)))
    assert not result.ok and result.code == "duplicate-component"


def test_a_group_of_one_is_the_single_command() -> None:
    """Each member goes through the single command itself, so the two cannot disagree."""
    (only,) = _unlocked(_bus().document, 1)
    pairs = [
        ("component.rotate", RotateComponentPayload(id=only, rotation=270),
         "component.rotateMany", RotateComponentsPayload(rotations=(RotateComponentPayload(id=only, rotation=270),))),
        ("component.mirror", MirrorComponentPayload(id=only, mirrored=True),
         "component.mirrorMany", MirrorComponentsPayload(mirrors=(MirrorComponentPayload(id=only, mirrored=True),))),
        ("component.update", UpdateComponentPayload(id=only, value="4k7", locked=True),
         "component.updateMany", UpdateComponentsPayload(updates=(UpdateComponentPayload(id=only, value="4k7", locked=True),))),
        ("component.delete", DeleteComponentPayload(id=only),
         "component.deleteMany", DeleteComponentsPayload(ids=(only,))),
    ]
    for single, single_payload, group, group_payload in pairs:
        one, many = _bus(), _bus()
        assert one.dispatch(single, single_payload).ok
        assert many.dispatch(group, group_payload).ok
        assert one.document == many.document, group


def test_parts_and_the_copper_selected_with_them_go_in_one_step() -> None:
    bus = _bus()
    before = bus.document
    ids = _unlocked(before, 2)
    copper = tuple(c.id for c in before.conductors[:2])
    result = bus.dispatch("component.deleteMany", DeleteComponentsPayload(ids=tuple(ids), conductor_ids=copper))
    assert result.ok, result
    assert not any(c.id in copper for c in bus.document.conductors)
    assert bus.history() == ("Delete 2 components and 2 conductors",)
    bus.undo()
    assert bus.document == before


def test_a_mixed_selection_is_locked_to_one_state_in_one_step() -> None:
    """"Lock these" with one already locked locks the rest, in one step; and a lock is the
    one thing a locked part does not refuse, or nothing locked could ever be unlocked."""
    bus = _bus()
    first, second, third = _unlocked(bus.document, 3)
    assert bus.dispatch("component.update", UpdateComponentPayload(id=second, locked=True)).ok
    before = bus.document
    assert bus.dispatch("component.lockMany", LockComponentsPayload(ids=(first, second, third), locked=True)).ok
    assert all(_by_id(bus.document, i).locked for i in (first, second, third))
    assert bus.history()[-1] == "Lock 3 components"
    assert bus.dispatch("component.lockMany", LockComponentsPayload(ids=(first, second, third), locked=False)).ok
    assert not any(_by_id(bus.document, i).locked for i in (first, second, third))
    assert bus.history()[-1] == "Unlock 3 components"
    bus.undo()
    bus.undo()
    assert bus.document == before
