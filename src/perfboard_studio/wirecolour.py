"""What colour a net's wire is: red for power, black for ground, then a cycle.

One answer with several askers -- the build guide's cut list, the harness, the 2D view's wire
tooltips and the system's LVS when it names a cable's wire -- kept here, under all of them,
so the colour a wire is called on the screen is the colour it is called at the bench and in a
finding. Hangs off ``model`` alone.
"""

from __future__ import annotations

from .model import NetClass, PerfDocument

#: Insulation colour by net class, the convention every schematic reader already knows.
COLOR_BY_NET_CLASS: dict[NetClass, str] = {"power": "red", "ground": "black"}

#: Signal colours, cycled by net order so the same board always assigns the same colours.
SIGNAL_COLORS: tuple[str, ...] = (
    "yellow", "green", "blue", "white", "orange", "violet", "grey", "brown",
)


def signal_colour_index(doc: PerfDocument) -> dict[str, int]:
    """Each signal net's place in the ``SIGNAL_COLORS`` cycle, per net id.

    Counted over the nets sorted by id -- the order ``persist`` writes them in -- and never
    in the order the document happens to hold them. A board built in a session holds its
    nets in the order they were made, and the same board opened from its .perf holds them
    in the file's order: counted in whichever order was at hand, one wire was brown in the
    cut list printed before saving and blue on the screen after reopening. Every board ever
    opened from a file already had its nets in this order, so no colour it showed moves.
    The guide, the 2D view and the 3D view and STEP export (``view3d.net_colouring``) all
    count here, which is what keeps the three agreeing.
    """
    signals = sorted(
        (net for net in doc.nets if net.net_class not in COLOR_BY_NET_CLASS),
        key=lambda net: net.id,
    )
    return {net.id: index for index, net in enumerate(signals)}


def net_colours(doc: PerfDocument) -> dict[str, str]:
    """Insulation colour per net id, by NAME: red for power, black for ground, then a cycle.

    The cycle is :func:`signal_colour_index`, so the same board produces the same cut list
    whether it was just built or opened from its file -- a colour convention that changed
    between two runs would be worse than none. The cut list, the guide's steps and the
    board view's wire tooltips all read this, so the colour a wire is called on the screen
    is the colour it is called at the bench.
    """
    signal_index = signal_colour_index(doc)
    colors: dict[str, str] = {}
    for net in doc.nets:
        fixed = COLOR_BY_NET_CLASS.get(net.net_class)
        if fixed is not None:
            colors[net.id] = fixed
        else:
            colors[net.id] = SIGNAL_COLORS[signal_index[net.id] % len(SIGNAL_COLORS)]
    return colors
