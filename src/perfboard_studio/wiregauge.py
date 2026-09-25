"""Hookup wire: how big a gauge is, what it carries, and which one to cut.

Three consumers need the same answers, which is why this is a module of its own rather
than a table in any one of them:

- ``drc.py`` measures a wire on a net that declares a current (rule 9,
  ``current-capacity``) and checks that its conductor goes through the board's holes
  (``wire-too-thick-for-hole``);
- ``router.py`` / ``striproute.py`` write the gauge onto the wires they lay for such a
  net, so the document says what was planned;
- ``guide.py`` prints the gauge on the cut list.

Before this module the guide picked a gauge from the declared current on its own and DRC
never looked at a wire at all, so the two could not disagree only because one of them
said nothing -- and the guide's table stopped at AWG 18, which it printed for 5 A and for
50 A alike. A cut list that names a wire the design-rule check would reject is the exact
drift the build guide's "one fact, two consumers" rule exists to prevent.

Pure and deterministic, like the rest of the engine: arithmetic on a gauge number.
"""

from __future__ import annotations

import math

from .model import Mm

#: What DRC allows a copper hookup wire to carry, in A/mm² of conductor.
#:
#: A rule of thumb, not a standard, and stated as one. It is the top of the 6-10 A/mm²
#: that ``DrcOptions.max_current_density_a_per_mm2`` already quotes for copper hookup
#: wire in free air, and it sits below every entry of the chassis-wiring column of the
#: widely reproduced AWG ampacity table (16 A at AWG 18 is ~19 A/mm², 55 A at AWG 10 is
#: ~10.5 A/mm²), because that column assumes a single wire in free air and a wire on a
#: perfboard lies against the substrate with a solder joint at each end.
#:
#: It is deliberately the same number for bare and insulated wire. The insulation is not
#: what gives out first here: a UL 1007 PVC jacket is rated 80 °C, which is about where
#: an FR-2 board starts to brown, and every wire -- bare or sleeved -- ends in two solder
#: joints on that board. The limit both kinds share is the board and the joints.
#:
#: Why not the 5 A/mm² the solder rule uses: that figure is derated for SOLDER, which
#: melts at ~183 °C and carries current at eight to nine times copper's resistivity. A
#: wire is copper along its whole length and meets solder only at its ends, where the
#: joint's own cross-section is several times the wire's.
WIRE_CURRENT_DENSITY_A_PER_MM2: float = 10.0

#: The comfortable gauge for a declared current, largest current first -- what the build
#: guide has always printed. Conservative: hookup wire in free air, derated because a
#: perfboard has no copper pour to spread heat into. Every row sits inside
#: ``wire_capacity_a`` at the default density (AWG 20 at 5 A is 97% of it), so below
#: ~8.2 A this table IS the answer and nothing the guide printed before has changed.
AWG_BY_CURRENT: tuple[tuple[float, int], ...] = ((5.0, 18), (3.0, 20), (1.5, 22), (0.0, 24))

#: The gauges stocked as hookup wire, thinnest first. Even numbers only: odd gauges exist
#: and nobody has a reel of AWG 17 on the bench, and a cut list that asked for one would
#: send the builder shopping for a wire one size either side of it would have done.
STOCKED_AWG: tuple[int, ...] = (30, 28, 26, 24, 22, 20, 18, 16, 14, 12, 10)

#: The heaviest gauge this module will name. Past AWG 10 (2.59 mm of copper) a conductor
#: no longer belongs on a board of 2.54 mm pitch at all: it is wider than the gap between
#: two holes, and whatever it carries should arrive on a terminal rated for it.
HEAVIEST_AWG: int = STOCKED_AWG[-1]


def awg_diameter_mm(awg: int) -> Mm:
    """Conductor diameter of a solid wire of this gauge, from the AWG definition itself.

    ``d = 0.127 mm x 92 ** ((36 - n) / 39)``: AWG 36 is 0.005 inch and AWG 0000 is 0.46
    inch, with 39 geometric steps between them. Computed rather than tabulated so that a
    gauge read from a file needs no table entry to be measured. Stranded wire of the same
    gauge has the same copper area and is slightly wider across, so this is the SMALLEST
    it can be -- which is the right side to err on when asking whether it fits a hole.
    """
    return 0.127 * math.pow(92, (36 - awg) / 39)


def awg_area_mm2(awg: int) -> float:
    """Copper cross-section of a wire of this gauge, in mm²."""
    radius = awg_diameter_mm(awg) / 2
    return math.pi * radius * radius


def wire_capacity_a(awg: int, density_a_per_mm2: float = WIRE_CURRENT_DENSITY_A_PER_MM2) -> float:
    """What a wire of this gauge is allowed to carry, in amperes."""
    return awg_area_mm2(awg) * density_a_per_mm2


def minimum_awg_for_current(
    current_a: float, density_a_per_mm2: float = WIRE_CURRENT_DENSITY_A_PER_MM2
) -> int | None:
    """The thinnest stocked gauge that carries ``current_a``, or None if none does.

    None rather than the heaviest gauge, because the two answers mean different things: a
    gauge is "cut this", and None is "no wire on this board carries that" -- which is what
    the design-rule check has to say out loud rather than print a size that is too small.
    """
    for awg in STOCKED_AWG:
        if wire_capacity_a(awg, density_a_per_mm2) >= current_a:
            return awg
    return None


def wire_gauge_for_current(
    current_a: float | None, density_a_per_mm2: float = WIRE_CURRENT_DENSITY_A_PER_MM2
) -> int:
    """The gauge to cut for a wire on a net declaring ``current_a``.

    The comfortable table first, and heavier only where the table's gauge would not carry
    the current -- the heavier of the two is always the answer, so the guide never prints
    a wire DRC would flag. A net that declares nothing gets AWG 24, as it always has.
    Capped at ``HEAVIEST_AWG``: past it there is nothing heavier to name, and DRC's
    ``current-capacity`` rule is what reports that the capped gauge is still too thin.
    """
    wanted = current_a or 0.0
    comfortable = next(gauge for threshold, gauge in AWG_BY_CURRENT if wanted >= threshold)
    minimum = minimum_awg_for_current(wanted, density_a_per_mm2)
    if minimum is None:
        return HEAVIEST_AWG
    # A smaller AWG number is a thicker wire.
    return min(comfortable, minimum)


def cut_gauge_awg(
    stored_awg: int | None,
    current_a: float | None,
    density_a_per_mm2: float = WIRE_CURRENT_DENSITY_A_PER_MM2,
) -> int:
    """The gauge a wire will actually be cut in: the one the document names, if it names
    one, and otherwise the one ``wire_gauge_for_current`` picks.

    One function because the cut list and DRC both have to answer "what gauge is this
    wire", and a wire the document says is AWG 24 must be measured as AWG 24 by the rule
    and printed as AWG 24 on the list -- not measured at the size the current would have
    chosen and printed at the size somebody typed.
    """
    if stored_awg is not None:
        return stored_awg
    return wire_gauge_for_current(current_a, density_a_per_mm2)


def fits_hole(awg: int, drill_diameter_mm: Mm) -> bool:
    """Whether the stripped conductor of this gauge goes through a hole this wide.

    Strictly narrower, with no allowance: ``awg_diameter_mm`` is already the solid-wire
    minimum, and a stranded conductor of the same gauge is wider still. AWG 18 is 1.02 mm,
    which is why it does not go through the 1.0 mm hole most perfboard is drilled with.
    """
    return awg_diameter_mm(awg) < drill_diameter_mm
