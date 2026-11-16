"""``net.merge``: one net joined into another, which is what labelling a wire with another
net's name means.

What is pinned: the net that stays keeps its id, name and class and gains the other's pins;
a current, voltage or face it does not declare comes from the net that went; the copper the
merged net claimed is the survivor's on every board; one undo puts both nets back; a supply
and its ground are refused by the predicate ERC reads; and on a wired example the board's
two pieces of copper show as a split net in LVS and a link in the ratsnest, never as a
board that silently matches.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    DESIGN_COMMANDS,
    MergeNetsPayload,
    UpdateNetPayload,
    create_standard_registry,
)
from perfboard_studio.footprints import get_footprint
from perfboard_studio.lvs import run_lvs
from perfboard_studio.model import PerfDocument, shorts_supplies
from perfboard_studio.ratsnest import net_ratsnest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _example(name: str) -> PerfDocument:
    text = (EXAMPLES / f"{name}.perf").read_text(encoding="utf-8")
    return persist.deserialize_document(text).document


def _bus(document: PerfDocument) -> CommandBus:
    return CommandBus(
        document, create_standard_registry(), CommandContext(next_id=create_id_generator(1000))
    )


def _net(document: PerfDocument, name: str):
    return next(net for net in document.nets if net.name == name)


def test_net_merge_is_a_command_on_the_design() -> None:
    assert "net.merge" in DESIGN_COMMANDS


def test_the_named_net_stays_and_takes_the_other_nets_pins_and_copper() -> None:
    bus = _bus(_example("ne555-astable"))
    before = bus.document
    out, led = _net(before, "OUT"), _net(before, "LED_A")
    led_copper = {c.id for c in before.conductors if c.net_id == led.id}
    assert led_copper

    result = bus.dispatch("net.merge", MergeNetsPayload(id=led.id, into=out.id))
    assert result.ok, result.message
    assert result.description == "Join net LED_A into OUT"
    after = bus.document
    assert all(net.id != led.id for net in after.nets)
    merged = _net(after, "OUT")
    assert (merged.id, merged.net_class) == (out.id, out.net_class)
    assert merged.nodes == out.nodes + led.nodes
    # The copper is where it was, and is the survivor's routing now.
    assert {c.id for c in after.conductors} == {c.id for c in before.conductors}
    assert {c.id for c in after.conductors if c.net_id == out.id} >= led_copper
    assert not any(c.net_id == led.id for c in after.conductors)

    bus.undo()
    assert bus.document == before


def test_a_field_the_survivor_leaves_unset_comes_from_the_net_that_went() -> None:
    bus = _bus(_example("ne555-astable"))
    out, led = _net(bus.document, "OUT"), _net(bus.document, "LED_A")
    assert bus.dispatch(
        "net.update", UpdateNetPayload(id=led.id, current_a=0.02, preferred_side="bottom")
    ).ok
    assert bus.dispatch("net.merge", MergeNetsPayload(id=led.id, into=out.id)).ok
    merged = _net(bus.document, "OUT")
    assert (merged.current_a, merged.preferred_side) == (0.02, "bottom")


def test_a_merged_net_the_board_does_not_join_is_an_open_not_a_match() -> None:
    """The board was wired for two nets. After the merge the two pieces of copper are one
    net the board does not yet join: LVS reports it, and the ratsnest draws the link still to
    make -- the same as any net half wired."""
    document = _example("ne555-astable")
    assert run_lvs(document, get_footprint).ok
    out, led = _net(document, "OUT"), _net(document, "LED_A")
    assert not net_ratsnest(document, get_footprint, out.id).links

    bus = _bus(document)
    assert bus.dispatch("net.merge", MergeNetsPayload(id=led.id, into=out.id)).ok
    lvs = run_lvs(bus.document, get_footprint)
    assert not lvs.ok
    assert any("OUT" in issue.net_names for issue in lvs.issues), lvs.issues
    links = net_ratsnest(bus.document, get_footprint, out.id)
    assert links is not None and links.links


@pytest.mark.parametrize(("gone", "kept"), [("GND", "VCC"), ("VCC", "GND")])
def test_a_supply_and_its_ground_are_never_joined(gone: str, kept: str) -> None:
    bus = _bus(_example("ne555-astable"))
    before = bus.document
    result = bus.dispatch(
        "net.merge",
        MergeNetsPayload(id=_net(before, gone).id, into=_net(before, kept).id),
    )
    assert not result.ok
    assert result.code == "two-supplies"
    assert result.message.startswith(f"{gone} and {kept} are a supply and a ground")
    assert "disconnect it from its net first" in result.message
    assert bus.document is before


def test_the_refusal_is_the_short_erc_reports() -> None:
    # One predicate: the classes ERC's supply-on-wrong-net calls a short are exactly the
    # pairs net.merge refuses, and nothing else is.
    classes = ("power", "ground", "signal")
    shorted = {(a, b) for a in classes for b in classes if shorts_supplies(a, b)}
    assert shorted == {("power", "ground"), ("ground", "power")}


def test_a_net_is_not_joined_into_itself() -> None:
    bus = _bus(_example("ne555-astable"))
    out = _net(bus.document, "OUT")
    result = bus.dispatch("net.merge", MergeNetsPayload(id=out.id, into=out.id))
    assert not result.ok and result.code == "same-net"


def test_copper_on_a_second_board_is_claimed_too() -> None:
    from perfboard_studio.model import ExtraBoard

    document = _example("ne555-astable")
    led = _net(document, "LED_A")
    moved = tuple(c for c in document.conductors if c.net_id == led.id)
    second = ExtraBoard(id="b2", name="", board=document.board, conductors=moved)
    bus = _bus(
        dataclasses.replace(
            document,
            conductors=tuple(c for c in document.conductors if c.net_id != led.id),
            boards=(second,),
        )
    )
    out = _net(bus.document, "OUT")
    assert bus.dispatch("net.merge", MergeNetsPayload(id=led.id, into=out.id)).ok
    (extra,) = bus.document.boards
    assert extra.conductors and all(c.net_id == out.id for c in extra.conductors)
