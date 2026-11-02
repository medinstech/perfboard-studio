"""The original's inputs, for every test that holds this engine to the original's output.

THE PROOF IS ABOUT CODE. The fixtures in ``tools/diffcheck/golden`` are what the TypeScript
engine produced on its own footprints, so a test comparing with them has to give this engine
those same footprints. The registry's are allowed to be better -- a body the size of the real
package (``DIVERGES_FROM_TYPESCRIPT``), each held to its new geometry by a test of its own --
and for exactly those ids this serves the original's, rebuilt from
``footprints.expected.json``. Every other id comes from the registry, which
``tests/test_footprints.py`` holds to the same file field by field, so the two are one
footprint either way.

ONE HELPER, because a differential test that built its own lookup would compare this code
on the real bodies with the original's output on the original's, and a body made larger
would read as a regression in the rules. ``tests/test_differential.py`` fails if a test
comparing with the golden output asks the registry directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from perfboard_studio.connectivity import FootprintLookup
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import BodySpec, Footprint, FootprintPin, Point2

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tools" / "diffcheck" / "golden"

#: Footprints whose GEOMETRY deliberately differs from the TypeScript golden, and why. The
#: golden proves the port reproduces the original; that cannot also mean the port may never
#: correct it. Only the outline and the body's dimensions and height are excused -- every
#: other field is still compared (``test_footprints``) -- and each entry is pinned by its own
#: test of the geometry it now has, rather than by the absence of a comparison. Hand-editing
#: the .expected.json instead would make the next regeneration from the TypeScript engine
#: silently disagree.
DIVERGES_FROM_TYPESCRIPT: dict[str, str] = {
    "xtal-hc49": (
        "the original had the HC-49/U's can 4.65 x 3.5 mm -- its thickness along the leads "
        "and a height across them -- where it is 11.05 x 4.65 mm on the board; pinned by "
        "test_the_crystal_is_as_long_as_the_can"
    ),
    **{
        footprint_id: (
            "the body is the real package's -- the datasheet maximum, or KiCad's model where "
            "that is larger -- where the original's was smaller than the part drawn in 3D, and "
            "a DIP's courtyard holds its body's length where the original's held its pins "
            "alone; pinned by test_a_body_is_the_real_package"
        )
        for footprint_id in (
            "dip-8",
            "dip-14",
            "dip-16",
            "dip-18",
            "dip-20",
            "dip-28",
            "dip-40",
            "dip-40-wide",
            "r-axial-3",
            "r-axial-4",
            "r-axial-5",
            "d-do35",
            "led-3mm",
            "led-5mm",
            "led-10mm",
            "to92",
            "to220",
            "screw-terminal-2",
            "screw-terminal-3",
        )
    },
}


def original_footprint(raw: dict[str, Any]) -> Footprint:
    """One entry of footprints.expected.json, as the original had it."""
    return Footprint(
        id=raw["id"],
        name=raw["name"],
        pins=tuple(
            FootprintPin(number=p["number"], d_col=p["dCol"], d_row=p["dRow"], name=p.get("name"))
            for p in raw["pins"]
        ),
        body_outline=tuple(Point2(x=p["x"], y=p["y"]) for p in raw["bodyOutline"]),
        body_height=raw["bodyHeight"],
        body=BodySpec(
            archetype=raw["body"]["archetype"],
            dims=raw["body"].get("dims", {}),
            color=raw["body"].get("color"),
        ),
        lead_diameter=raw["leadDiameter"],
        polarized=raw["polarized"],
    )


def _original_footprints() -> dict[str, Footprint]:
    raw = json.loads((GOLDEN_DIR / "footprints.expected.json").read_text(encoding="utf-8"))
    return {footprint_id: original_footprint(entry) for footprint_id, entry in raw.items()}


ORIGINAL_FOOTPRINTS: dict[str, Footprint] = _original_footprints()


def differential_lookup() -> FootprintLookup:
    """The registry, but the original's footprint for every id that diverges from it."""
    registry = footprint_lookup()
    served = {footprint_id: ORIGINAL_FOOTPRINTS[footprint_id] for footprint_id in DIVERGES_FROM_TYPESCRIPT}

    def lookup(footprint_id: str) -> Footprint | None:
        return served.get(footprint_id) or registry(footprint_id)

    return lookup
