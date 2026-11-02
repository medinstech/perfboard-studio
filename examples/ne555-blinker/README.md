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
   still empty and the answer is still free. The circuit is placed, wired and checked on a
   roomy board, then on each size below it for as long as it builds as well, and every one
   of those shows the placement it was judged by:

   | | | |
   |---|---|---|
   | 7 × 9 cm | 27 × 35 | fits, 21% full |
   | 6 × 8 cm | 22 × 30 | the roomy board the smaller ones are measured against |
   | 5 × 7 cm | 18 × 24 | builds as well, at 93% of its wiring cost |
   | 4 × 6 cm | 14 × 20 | builds as well, at 80% of its wiring cost |
   | 3 × 7 cm | 10 × 24 | builds as well, at 92% of its wiring cost |
   | **2 × 8 cm** | **5 × 30** | **builds as well, at 101% of its wiring cost — suggested** |

   The suggestion is the smallest board it builds as well on: every part placed, every
   connection made, no warning the roomy board does not have, and at most 20% dearer to
   wire. Here that is the 2 × 8 cm strip. Take it, take a bigger one, or keep the 60 × 40
   blank — it is your board.

   Then the placement that board was tried with goes down, exactly as the picture showed
   it: J1 and J2 **on the edge** where something can be plugged into them, RV1's body at
   the edge where a finger can turn it. One Ctrl+Z takes the whole thing back.
3. **Ctrl+R** — route. Seven nets, all closed, no DRC error and no LVS mismatch.
4. **Ctrl+4** — the build guide: 33 steps across 7 phases, 50 checkpoints.
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
`project.py` reserves a place for it. **File ▸ Import from KiCad…** on it does the
same thing from the other direction.

## Regenerating it

```sh
python tools/build_examples.py            # rebuilds this alongside the other four
python tools/build_examples.py --check     # verify only, write nothing
```

`outputs/` and any `.bak` are ignored by git: they are written from the document every
time the project is saved, so nothing in them is worth keeping and nothing in them is
lost by deleting them.
