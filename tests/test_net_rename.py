"""``commands.rename_net_payload``: one rule for whether a rename moves a net's class, read
by the Nets panel and by a label on the sheet."""

from __future__ import annotations

from perfboard_studio.commands import rename_net_payload
from perfboard_studio.model import Net, NetNode


def _net(name: str, net_class: str) -> Net:
    return Net(id="n1", name=name, net_class=net_class, nodes=(NetNode("R1", "1"),))  # type: ignore[arg-type]


def test_a_net_whose_class_followed_its_name_follows_the_new_one() -> None:
    payload = rename_net_payload(_net("N3", "signal"), "GND")
    assert payload.name == "GND" and payload.net_class == "ground"
    assert rename_net_payload(_net("N3", "signal"), "+5V").net_class == "power"


def test_a_class_set_by_hand_is_never_moved_by_a_rename() -> None:
    # A GND somebody made a signal stays a signal when it is renamed.
    assert rename_net_payload(_net("GND", "signal"), "AGND").net_class is None
    assert rename_net_payload(_net("SDA", "power"), "GND").net_class is None


def test_a_rename_that_implies_the_same_class_leaves_the_class_alone() -> None:
    assert rename_net_payload(_net("N3", "signal"), "SDA").net_class is None
