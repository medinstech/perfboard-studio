# NE555 Blinker — a project with nothing built yet

The other four examples are finished boards. This one is the state a project is actually
in when you have just drawn a circuit: **ten parts in the design, nothing on the board.**

It is here to be walked through rather than looked at.

```sh
perfboard-studio examples/ne555-blinker/ne555-blinker.perf
```

...or **File ▸ Open Project…** and pick the `ne555-blinker` folder, which is the same
thing said the other way: a project is a directory built around exactly one `.perf`.

## What to press

1. **Ctrl+5** — the Schematic panel. Ten symbols, ground and power drawn as rail glyphs
   rather than as wires. Click a symbol to select that part; click a wire to select its
   net everywhere. Nothing is on the board yet, so every symbol is drawn as unplaced.
2. **Place on the Board.** It asks which board first — and only now, while the board is
   still empty and the answer is still free. Every size in the list was tried with this
   circuit actually laid out on it:

   | | | |
   |---|---|---|
   | 4 × 6 cm | 14 × 20 | too small — 2 parts will not fit |
   | 5 × 7 cm | 18 × 24 | fits, 46% full |
   | **6 × 8 cm** | **22 × 30** | **fits, 30% full — suggested** |
   | 7 × 9 cm | 27 × 35 | fits, 21% full |

   The suggestion is the smallest board with room left to *wire* it, which is not the
   smallest it fits on. Take it, take a bigger one, or keep the 60 × 40 blank — it is
   your board.

   Then it arranges: J1 and J2 land **on the edge** where something can be plugged into
   them, RV1's body reaches the edge where a finger can turn it, and the rest line up in
   lanes by what they connect to. One Ctrl+Z takes the whole thing back.
3. **Ctrl+R** — route. Seven nets, all closed, no DRC error and no LVS mismatch.
4. **Ctrl+4** — the build guide: 31 steps across 8 phases, 47 checkpoints.
5. **Ctrl+Alt+S** — Save Project. The board, plus everything generated from it, into
   `outputs/` beside it: the 1:1 sheets, the schematic as SVG/PDF/PNG, the guide, the
   bill of materials and the cut list.

`Ctrl+Shift+A` arranges it again from a different seed, on whatever board you settled on.

## The circuit

A 555 astable flashing an LED, with the flash rate on a pot.

| | |
|---|---|
| U1 | NE555, DIP-8 |
| R1 | 10k, charge resistor — +9V to DISCH |
| RV1 | 100k pot, wired as a rheostat between DISCH and THRESH: the flash rate |
| C1 | 10µF electrolytic, THRESH to GND: the timing capacitor |
| C2 | 10nF, CV to GND |
| C3 | 100nF, supply decoupling |
| R2 | 470Ω, OUT to the LED |
| LED1 | 5 mm |
| J1 | screw terminal, 9 V in |
| J2 | 3-pin header: OUT, +9V, GND |

`netlist.net` is the KiCad export the design was built from, kept in the project the way
`project.py` reserves a place for it. **File ▸ Import KiCad Netlist…** on it does the
same thing from the other direction.

## Regenerating it

```sh
python tools/build_examples.py            # rebuilds this alongside the other four
python tools/build_examples.py --check     # verify only, write nothing
```

`outputs/` and any `.bak` are ignored by git: they are written from the document every
time the project is saved, so nothing in them is worth keeping and nothing in them is
lost by deleting them.
