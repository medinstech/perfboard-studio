"""The real shape of a through-hole package, borrowed from KiCad's model library.

WHY THIS EXISTS, AND WHAT PLAN.md D6 STILL SAYS. D6 chose parametric generation for the 3D
bodies and gave three reasons: zero assets, a body that cannot disagree with its own
footprint, and no share-alike licence inherited into an Apache-2.0 project. Two of them are
untouched. The third did not survive looking at the result -- a potentiometer generated from
a diameter and a height is a disc with a peg on it, a relay is a box, and no amount of
shading makes either of those the part. So the geometry for the packages KiCad has is
borrowed, and everything D6 was protecting is kept by being careful about WHAT is borrowed:

  * **The generated body is still the answer for everything else**, and it is still the
    fallback here. A footprint with no entry, a generated id (``box-4x2-p1-r3-15x10x8``), a
    part nobody has mapped -- all of them draw exactly as they did. Nothing depends on a
    model existing.
  * **Only the shape above the board is taken.** The leads are this application's own, drawn
    by ``view3d._through_hole_pieces``, which knows the board's thickness, where the copper
    is and how far past it a trimmed lead stands. A model's own legs are drawn untrimmed for
    a 1.6 mm board and would hang out of the solder side.
  * **The body keeps OUR colour.** ``bodies.BODY_STYLES`` is one table for the 2D view, the
    3D view and the guide's step images, and a red LED coming out a different red in two of
    the three would be giving that up for a borrowed mesh. The converter marks the biggest
    non-metal piece as the body and it is painted from our table; leads, tabs, bands and the
    gold on a header pin keep the colour they were drawn with, because our table has no
    opinion about those.
  * **Materials are ours.** Each piece names one of ``view3d``'s materials, so a borrowed
    mesh answers light by the same rules as a generated one.

THE MESHES ARE DATA, NOT CODE. They are the only part of this repository that is not
Apache-2.0: they are derived from KiCad's packages3D library, which is CC-BY-SA 4.0, and
they carry their own LICENSE and NOTICE beside them. ``tools/import_kicad_models.py`` is
what makes them, it runs against a KiCad installation, and it is not needed to run the
application.

NOTHING HERE READS A FILE UNTIL IT IS ASKED FOR ONE. The index is a few kilobytes and is
read once; a mesh is read when a part using it is first drawn and then kept, because a
board is mostly the same twenty parts over and over and a refresh happens on every edit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

MODELS_DIR = Path(__file__).resolve().parent / "models"
INDEX_PATH = MODELS_DIR / "index.json"


@dataclass(frozen=True, slots=True)
class ModelPiece:
    """One mesh of one package: everything KiCad painted a single colour."""

    mesh: str
    #: The colour it was drawn with, as ``#rrggbb``. Ignored for the body piece, which
    #: takes the style's own fill -- see the module docstring.
    color: str
    #: One of ``view3d``'s material names.
    material: str
    #: Whether this is the case rather than a lead, a tab or a band.
    is_body: bool = False
    #: What it measures, as ``(xmin, ymin, zmin, xmax, ymax, zmax)`` in the model's own
    #: frame -- which is the world's, translated to pin 1. Empty when the index predates it.
    bounds: tuple[float, ...] = ()

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.mesh


@dataclass(frozen=True, slots=True)
class PartModel:
    footprint_id: str
    #: Where it came from, kept so a mesh can be traced back to a KiCad package by name.
    source: str
    pieces: tuple[ModelPiece, ...]

    @property
    def body(self) -> ModelPiece | None:
        """The case, which is the piece anything printed on the part goes on."""
        return next((piece for piece in self.pieces if piece.is_body), None)


@lru_cache(maxsize=1)
def _index() -> dict[str, PartModel]:
    """Every model there is, read once.

    A missing or unreadable index is "there are no models", not an error: the generated
    bodies are the fallback for every part anyway, so a build that shipped without the
    meshes draws a complete board rather than refusing to draw one.
    """
    try:
        raw: dict[str, Any] = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    models: dict[str, PartModel] = {}
    for footprint_id, entry in raw.items():
        pieces = tuple(
            ModelPiece(
                mesh=piece["mesh"],
                color=piece["color"],
                material=piece["material"],
                is_body=piece.get("role") == "body",
                bounds=tuple(piece.get("bounds", ())),
            )
            for piece in entry.get("parts", ())
        )
        if pieces:
            models[footprint_id] = PartModel(
                footprint_id=footprint_id, source=entry.get("source", ""), pieces=pieces
            )
    return models


def model_for(footprint_id: str | None) -> PartModel | None:
    """The model for a footprint, or ``None`` to draw the generated body."""
    if footprint_id is None:
        return None
    return _index().get(footprint_id)


#: The single pin of a pin header, drawn once per pin rather than once per header.
#:
#: A header is the one package in the library that IS a repetition -- KiCad ships a model
#: per length, forty of them per row count, and they are the same pin over and over. One
#: mesh glyphed at every pin is the same picture for a fortieth of the library, and it is
#: also what lets a header of a length nobody shipped a model for still be drawn.
HEADER_PIN = "hdr-pin"


def header_pin_model() -> PartModel | None:
    return model_for(HEADER_PIN)


def known_footprints() -> frozenset[str]:
    """Every footprint that has a model. For tests and for the About box's count."""
    return frozenset(_index())
