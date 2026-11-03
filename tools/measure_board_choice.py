"""Measure the board question on every example: which board it is tried on, what each
trial found, and how long it took.

    python tools/measure_board_choice.py                 # seed 0, every example
    python tools/measure_board_choice.py --seeds 0 1 2 3 # how often a verdict flips
    python tools/measure_board_choice.py lm317-supply    # one example

Where ``boardfit.ROUTE_COST_TOLERANCE`` and ``TRIAL_PLACEMENT_OPTIONS`` get their numbers:
their docstrings quote this script's output, and a change to the placer, the router or
the presets is a reason to run it again rather than trust them.

Each example is taken back to its DESIGN first -- every part off the board, the copper
gone -- which is the state the window asks the question in: a board is chosen before the
design is placed on it. A host tool, so it may read the clock; the engine it measures may
not.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from perfboard_studio import persist  # noqa: E402
from perfboard_studio.boardfamily import BoardPreset  # noqa: E402
from perfboard_studio.boardfit import (  # noqa: E402
    PLACEMENT_WARNING_RULES,
    TRIAL_PLACEMENT_OPTIONS,
    BoardTrialOptions,
    choose_board,
)
from perfboard_studio.command import CommandContext  # noqa: E402
from perfboard_studio.commands import (  # noqa: E402
    UnplaceComponentPayload,
    create_document_id_generator,
    unplace_component,
)
from perfboard_studio.footprints import footprint_lookup  # noqa: E402
from perfboard_studio.model import PerfDocument  # noqa: E402


def the_design(doc: PerfDocument) -> PerfDocument:
    """``doc`` with every part back in the design and nothing on the board."""
    doc = replace(
        doc,
        conductors=(),
        cuts=(),
        components=tuple(replace(c, locked=False) for c in doc.components),
    )
    for component in doc.components:
        doc = unplace_component.apply(
            doc,
            UnplaceComponentPayload(id=component.id),
            CommandContext(next_id=create_document_id_generator(doc)),
        )
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("examples", nargs="*", help="example names (default: all)")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    args = parser.parse_args()

    paths = sorted((REPO_ROOT / "examples").glob("*.perf")) + sorted(
        (REPO_ROOT / "examples").glob("*/*.perf")
    )
    if args.examples:
        paths = [p for p in paths if p.stem in args.examples]
    lookup = footprint_lookup()
    short = {rule: "".join(word[0] for word in rule.split("-")) for rule in PLACEMENT_WARNING_RULES}

    for path in paths:
        design = the_design(persist.parse_document_or_throw(path.read_text(encoding="utf-8")))
        for seed in args.seeds:
            options = BoardTrialOptions(placement=replace(TRIAL_PLACEMENT_OPTIONS, seed=seed))
            clock: dict[str, float] = {}

            def tick(preset: BoardPreset, clock: dict[str, float] = clock) -> None:
                clock[preset.name] = time.perf_counter()

            started = time.perf_counter()
            choice = choose_board(design, lookup, options=options, on_trial=tick)
            finished = time.perf_counter()
            reference = choice.reference.preset.name if choice.reference else "-"
            recommended = choice.recommended.preset.name if choice.recommended else "-"
            print(f"{path.stem}  seed {seed}: reference {reference} -> {recommended}"
                  f"  ({finished - started:.1f} s)")
            names = [v.preset.name for v in choice.verdicts]
            for index, verdict in enumerate(choice.verdicts):
                end = clock[names[index + 1]] if index + 1 < len(names) else finished
                ratio = "-" if verdict.cost_ratio is None else f"x{verdict.cost_ratio:.2f}"
                warns = ",".join(short[r] for r in verdict.new_warnings)
                print(f"    {verdict.preset.name:10} {verdict.kind:13} {ratio:6} "
                      f"cost {verdict.trial.route_cost:7.1f}  {warns:8} "
                      f"{end - clock[names[index]]:5.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
