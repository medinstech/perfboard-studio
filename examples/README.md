# Examples

Four finished circuits, each shipped twice: as the `.net` a schematic tool exports, and as
the `.perf` that importing, placing and routing it produces. And one **project** —
[`ne555-blinker/`](./ne555-blinker/) — which is the other end of the same workflow: a
circuit that has been drawn and not yet built. Start there if what you want to see is how
the tool goes from a schematic to a board.

```sh
perfboard-studio examples/lm317-supply.perf     # open the finished board
```

...or start from the netlist the way you would with your own circuit: **File → Import
KiCad Netlist**, accept the placement, `Ctrl+Shift+A` to auto-place, `Ctrl+R` to route,
`Ctrl+B` for the build guide.

Every board below is one a supplier stocks, in the exact size on the packet, with the
finger strips down two edges and the screw hole in each corner it is sold with — and it is
the size this application's own **Place on the Board** would have suggested for that
circuit. They used to be on grids nobody sells (32 × 22, 30 × 20), which taught two wrong
things at once: that perfboard comes in whatever size you like, and that the fingers a real
one arrives with are somebody else's problem.

| | parts | board | what it is there to show |
|---|---|---|---|
| **ne555-astable** | 8 | **4 × 6 cm**, 14 × 20, FR-4 | The starting point. A 555 flashing an LED — the circuit everybody has built. |
| **lm317-supply** | 11 | **6 × 8 cm**, 22 × 30, FR-4 | A hot part. The regulator is a TO-220, so the heat-proximity rule has something to measure. |
| **lpb1-booster** | 12 | **7 × 9 cm**, 27 × 35, **FR-2** | The material mattering. Phenolic is what a pedal actually gets built on and it is the board whose pads lift, so the guide drops the iron 30 °C (350 → 320) and cuts the dwell from 3 s to 2 s. |
| **arduino-io-shield** | 11 | **5 × 7 cm**, 18 × 24, FR-4 | Headers. Two of them, 8-pin and 6-pin, which is what a shield mostly is — and the case where lead bends and short traces do nearly all the work. |
| **ne555-blinker/** | 10 | *none yet* | The workflow, rather than its result. Ten parts in the design and nothing on the board, so **Place on the Board** has a board size to suggest and an arrangement to make. Its own [README](./ne555-blinker/README.md) walks through it. |

All four route to completion, match their schematics under LVS, and carry no DRC error.
`tests/test_examples.py` asserts exactly that on every commit, so an example cannot rot
quietly — and for the project it asserts the walkthrough its README promises instead:
that the design is still a design, that a stock board with room to wire it is still
suggested, and that placing, routing and checking it still comes out clean.

## Regenerating them

```sh
python tools/build_examples.py            # rebuild every .perf from its .net
python tools/build_examples.py --check     # verify only, write nothing
```

The footprints are named in that script rather than guessed from the netlist. A netlist
knows a part is called `U1` and that three of its pins appear in nets, which is all
`guess_footprint_id` has to go on — enough for the app to land parts somewhere obvious
for you to correct, not enough for an example. An LM317 guesses to a DIP-8, and a TO-220
standing in for an 8-pin DIP would put the heat rule and the 3D height check both wrong.

The timestamps in the `.perf` files are fixed rather than current, so rebuilding an
example does not put a date change in the way of whatever the commit was about.

## Adding one

Write the `.net`, add an entry to `CATALOGUE` in `tools/build_examples.py` naming the
board size and each part's real footprint, and run the script. It fails loudly if the
circuit does not route cleanly, which is the point.
