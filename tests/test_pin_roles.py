"""What each lead of a part DOES: stored on the part, carried with it, reported when it
does not fit.

Roles (``model.PinRole``) are read from a maker's pin table into the catalog and copied
onto the part when it is placed, so that the sheet can draw an IC as what it does --
supplies on top, grounds below, inputs left, outputs right -- rather than as a numbered
box. Three things are pinned here, layer by layer:

- what is REFUSED, by a command and at load alike: a role that is not one, a pin with no
  number, a pin given two roles -- everything that can be seen without the footprint
  registry;
- what is CARRIED: through placing and unplacing, an update that leaves them, a new value
  and a new package (as the pin names are, one rule), the file and the clipboard;
- what is REPORTED and not refused: roles that do not cover the package's pins exactly,
  by the sheet's note and by ERC in the same words, because only the registry knows a
  part's pins and no command has one.
"""

from __future__ import annotations

import json

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    AddPartPayload,
    PartPlacement,
    PlaceComponentPayload,
    PlacePartsPayload,
    UnplaceComponentPayload,
    UpdateComponentPayload,
    UpdatePartPayload,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.erc import run_erc
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import (
    DocumentMeta,
    HoleCoord,
    PerfDocument,
    normalized_pin_roles,
    pin_roles_misfit,
)
from perfboard_studio.schematic import build_schematic
from perfboard_studio.ui.clipboard import block_from_json, block_to_json, paste_payload

META = DocumentMeta(name="roles", created="", modified="")
REGISTRY = footprint_lookup()

#: The NE555's roles, pin 1 to 8, from TI's pin-function table.
NE555 = (
    ("1", "ground"),
    ("2", "in"),
    ("3", "out"),
    ("4", "in"),
    ("5", "passive"),
    ("6", "in"),
    ("7", "out"),
    ("8", "power"),
)
NE555_NAMES = (
    ("1", "GND"),
    ("2", "TRIG"),
    ("3", "OUT"),
    ("4", "RESET"),
    ("5", "CTRL"),
    ("6", "THR"),
    ("7", "DIS"),
    ("8", "VCC"),
)


def new_bus() -> CommandBus:
    return CommandBus(
        create_empty_document(META),
        create_standard_registry(),
        CommandContext(next_id=create_id_generator()),
    )


def add(bus: CommandBus, ref: str = "U1", footprint: str = "dip-8", **fields) -> None:
    result = bus.dispatch(
        "part.add", AddPartPayload(ref=ref, footprint_id=footprint, value="NE555", **fields)
    )
    assert result.ok, result.message


def place(bus: CommandBus) -> str:
    part_id = bus.document.parts[0].id
    result = bus.dispatch(
        "part.place",
        PlacePartsPayload(placements=(PartPlacement(id=part_id, anchor=HoleCoord(3, 3)),)),
    )
    assert result.ok, result.message
    return part_id


# ---------------------------------------------------------------------------
# The model: one normal form, and what it refuses
# ---------------------------------------------------------------------------


def test_roles_are_stored_in_pin_order_from_a_mapping_or_pairs() -> None:
    assert normalized_pin_roles({"10": "io", "2": " in ", "1": "power"}) == (
        ("1", "power"),
        ("2", "in"),
        ("10", "io"),
    )
    assert normalized_pin_roles([("2", "out"), ("1", "ground")]) == (
        ("1", "ground"),
        ("2", "out"),
    )


@pytest.mark.parametrize(
    "roles",
    [
        {"1": "supply"},  # not a role
        {"1": ""},  # a blank role is not "no role": every pin or none
        {"": "in"},  # a role on no pin
        [("1", "in"), ("1", "out")],  # one pin, two roles
        "in,out",  # not a mapping at all
        {"1": 3},  # not text
    ],
)
def test_what_is_wrong_with_the_roles_themselves_is_refused(roles: object) -> None:
    with pytest.raises(ValueError):
        normalized_pin_roles(roles)


# ---------------------------------------------------------------------------
# The commands
# ---------------------------------------------------------------------------


def test_a_part_takes_its_roles_and_a_bad_one_refuses_the_command() -> None:
    bus = new_bus()
    add(bus, pin_roles=NE555)
    assert bus.document.parts[0].pin_roles == NE555
    refused = bus.dispatch(
        "part.add",
        AddPartPayload(ref="U2", footprint_id="dip-8", pin_roles=(("1", "vcc"),)),
    )
    assert not refused.ok
    assert refused.code == "invalid-pin-roles"
    assert "U2" in refused.message
    placed = bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref="U3",
            value="NE555",
            footprint_id="dip-8",
            anchor=HoleCoord(12, 3),
            pin_roles=(("1", "ground"), ("1 ", "in")),
        ),
    )
    assert not placed.ok
    assert placed.code == "invalid-pin-roles"


def test_placing_and_unplacing_carry_the_roles_both_ways() -> None:
    bus = new_bus()
    add(bus, pin_roles=NE555)
    part_id = place(bus)
    assert bus.document.components[0].pin_roles == NE555
    assert bus.dispatch("component.unplace", UnplaceComponentPayload(id=part_id)).ok
    assert bus.document.parts[0].pin_roles == NE555


def test_component_place_takes_roles_too() -> None:
    """The route a paste and an agent's place_component both take."""
    bus = new_bus()
    assert bus.dispatch(
        "component.place",
        PlaceComponentPayload(
            ref="U1", value="NE555", footprint_id="dip-8", anchor=HoleCoord(3, 3), pin_roles=NE555
        ),
    ).ok
    assert bus.document.components[0].pin_roles == NE555


@pytest.mark.parametrize("placed", [False, True], ids=["part.update", "component.update"])
def test_a_new_value_or_package_does_to_roles_what_it_does_to_names(placed: bool) -> None:
    """ONE RULE FOR BOTH: kept. A new package is not refused for roles that no longer fit
    it -- the command cannot see its pins -- and a later footprint change back would find
    them gone if this dropped them. What does not fit is reported instead, below."""
    bus = new_bus()
    add(bus, pin_names=NE555_NAMES, pin_roles=NE555)
    part_id = place(bus) if placed else bus.document.parts[0].id

    def update(**fields):
        if placed:
            return bus.dispatch("component.update", UpdateComponentPayload(id=part_id, **fields))
        return bus.dispatch("part.update", UpdatePartPayload(id=part_id, **fields))

    def current():
        return (bus.document.components if placed else bus.document.parts)[0]

    assert update(value="LM555").ok
    assert (current().pin_names, current().pin_roles) == (NE555_NAMES, NE555)
    assert update(footprint_id="dip-14").ok
    assert (current().pin_names, current().pin_roles) == (NE555_NAMES, NE555)
    # None leaves them, a new set replaces them whole, an empty one clears them.
    assert update(pin_roles=(("1", "ground"),)).ok
    assert current().pin_roles == (("1", "ground"),)
    assert current().pin_names == NE555_NAMES
    assert update(pin_roles=()).ok
    assert current().pin_roles == ()
    refused = update(pin_roles=(("1", "earth"),))
    assert not refused.ok
    assert refused.code == "invalid-pin-roles"


# ---------------------------------------------------------------------------
# The file and the clipboard
# ---------------------------------------------------------------------------


def _round_trip(doc: PerfDocument) -> tuple[dict, PerfDocument]:
    text = persist.serialize_document(doc)
    loaded = persist.deserialize_document(text)
    assert loaded.ok, loaded
    return json.loads(text), loaded.document


def test_the_file_keeps_roles_in_pin_order_and_says_nothing_without_them() -> None:
    bus = new_bus()
    add(bus, pin_roles=NE555)
    add(bus, ref="R1", footprint="r-axial-4")
    raw, loaded = _round_trip(bus.document)
    u1, r1 = raw["parts"]
    assert list(u1["pinRoles"]) == [number for number, _ in NE555]
    assert "pinRoles" not in r1
    assert loaded.parts == bus.document.parts

    place(bus)
    raw, loaded = _round_trip(bus.document)
    assert raw["components"][0]["pinRoles"]["8"] == "power"
    assert loaded.components == bus.document.components


@pytest.mark.parametrize(
    "roles,fragment",
    [({"1": "vcc"}, "not a pin role"), ({" ": "in"}, "no number"), ({"1": 5}, "pinRoles.1")],
)
def test_a_file_with_a_role_no_command_would_take_does_not_open(roles, fragment) -> None:
    """Refused at load for exactly what a command refuses: a document that holds what no
    command could have made is not a document the rest of the engine has to defend
    against."""
    bus = new_bus()
    add(bus)
    raw = json.loads(persist.serialize_document(bus.document))
    raw["parts"][0]["pinRoles"] = roles
    loaded = persist.deserialize_document(json.dumps(raw))
    assert not loaded.ok
    assert fragment in loaded.message
    assert loaded.path.startswith("parts[0].pinRoles")


def test_a_copied_part_pastes_with_its_roles() -> None:
    bus = new_bus()
    add(bus, pin_roles=NE555)
    place(bus)
    doc = bus.document
    text = block_to_json(doc, [doc.components[0].id])
    assert json.loads(text)["components"][0]["pinRoles"]["3"] == "out"
    block = block_from_json(text)
    assert block is not None
    assert block.components[0].pin_roles == NE555
    paste = paste_payload(doc, block, HoleCoord(14, 3))
    result = bus.dispatch("block.place", paste.payload)
    assert result.ok, result.message
    assert [c.pin_roles for c in bus.document.components] == [NE555, NE555]


def test_a_clipboard_role_that_is_not_one_is_dropped_not_refused() -> None:
    """The clipboard is text anybody can put anything into, so it is read leniently --
    as its pin names are."""
    bus = new_bus()
    add(bus, pin_roles=NE555)
    place(bus)
    raw = json.loads(block_to_json(bus.document, [bus.document.components[0].id]))
    raw["components"][0]["pinRoles"] = {"1": "vcc"}
    block = block_from_json(json.dumps(raw))
    assert block is not None
    assert block.components[0].pin_roles == ()


# ---------------------------------------------------------------------------
# What does not fit is said, not refused
# ---------------------------------------------------------------------------


def test_the_fit_is_every_pin_or_none() -> None:
    pins = [str(n) for n in range(1, 9)]
    assert pin_roles_misfit((), pins) is None
    assert pin_roles_misfit(NE555, pins) is None
    assert pin_roles_misfit(NE555[:7], pins) == (7, 8, ())
    assert pin_roles_misfit((*NE555, ("9", "nc")), pins) == (8, 8, ("9",))


def _with_roles(roles) -> PerfDocument:
    bus = new_bus()
    add(bus, pin_roles=roles)
    return bus.document


@pytest.mark.parametrize(
    "roles,said",
    [
        (NE555[:7], "roles for 7 of 8 pins"),
        ((*NE555, ("9", "nc"), ("10", "nc")), "a role for pins 9 and 10, which the package does not have"),
    ],
    ids=["a pin with none", "a role on pins it lacks"],
)
def test_the_sheet_and_erc_say_the_same_words(roles, said: str) -> None:
    doc = _with_roles(roles)
    assert f"U1: {said}, drawn as a numbered box" in build_schematic(doc, REGISTRY).notes
    findings = [f for f in run_erc(doc, REGISTRY) if f.rule == "pin-roles-incomplete"]
    assert [(f.message, f.severity, f.refs) for f in findings] == [
        (f"U1 has {said}, so it is drawn as a numbered box.", "warning", ("U1",))
    ]


def test_roles_that_fit_and_no_roles_at_all_say_nothing() -> None:
    for roles in (NE555, ()):
        doc = _with_roles(roles)
        assert not any("numbered box" in note for note in build_schematic(doc, REGISTRY).notes)
        assert not [f for f in run_erc(doc, REGISTRY) if f.rule == "pin-roles-incomplete"]


def test_a_new_package_that_the_roles_no_longer_fit_is_reported() -> None:
    """The other half of keeping them across a footprint change: an NE555's eight roles on
    a 14-pin package are said, at once, in the place a person looks."""
    bus = new_bus()
    add(bus, pin_roles=NE555)
    assert bus.dispatch(
        "part.update", UpdatePartPayload(id=bus.document.parts[0].id, footprint_id="dip-14")
    ).ok
    assert "U1: roles for 8 of 14 pins, drawn as a numbered box" in build_schematic(
        bus.document, REGISTRY
    ).notes
