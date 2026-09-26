"""Placing the parts a netlist names but the board does not have yet.

Shared by the window's import and the MCP ``import_netlist``, so that a part an agent imports
arrives as the one a person imports does: with the footprint, value, pin names and symbol that
``parsers.kicad_parts`` worked out, laid out by ``placer.arrange`` -- best-connected first,
connectors on an edge, the rest in lanes beside what they connect to -- around whatever is on
the board already. A first pass, stated as one: the placer or a person refines it.

It used to be a grid in the order of the references, which is to say in an order that has
nothing to do with the circuit; the placer's own notes measure what that costs.
"""

from __future__ import annotations

from collections.abc import Callable

from .commands import PlaceComponentPayload
from .model import Footprint, PerfDocument
from .parsers.kicad_parts import PartSuggestion
from .placer import ArrangeRequest, arrange_around


def import_placements(
    suggestions: list[PartSuggestion],
    document: PerfDocument,
    lookup: Callable[[str], Footprint | None],
) -> tuple[list[PlaceComponentPayload], list[str]]:
    """Each suggestion as a placement on ``document``'s board -- whose nets should already be
    the imported ones, since they are what says which parts belong together -- and the refs
    that found no room or whose footprint does not build."""
    by_ref = {suggestion.ref: suggestion for suggestion in suggestions}
    arrangement = arrange_around(
        document,
        # The id is only for matching the answer back: the bus gives each part its own.
        [ArrangeRequest(f"import:{s.ref}", s.ref, s.footprint_id) for s in by_ref.values()],
        lookup,
    )
    placements = [
        PlaceComponentPayload(
            ref=placed.ref,
            value=by_ref[placed.ref].value,
            footprint_id=by_ref[placed.ref].footprint_id,
            anchor=placed.anchor,
            rotation=placed.rotation,
            pin_names=by_ref[placed.ref].pin_names,
            symbol=by_ref[placed.ref].symbol,
        )
        for placed in arrangement.placements
    ]
    return placements, sorted(arrangement.unplaced)
