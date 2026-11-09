# Your first board, from Home to the build guide

About ten minutes, and no soldering yet: this takes the 555 LED blinker from a drawn
circuit to a board you can build, in the window and in the order the window offers it.
The soldering takes longer, and the guide at the end is what it is for.

You need Perfboard Studio ([installers or `pip install perfboard-studio`](../README.md#running-it))
and nothing else. The circuit is one of the examples that ship with it.

## What you will build

A 555 timer in astable mode flashing an LED, the flash rate set by a pot.

| | | |
|---|---|---|
| U1 | NE555, DIP-8 | the timer |
| R1 | 10k | charges the timing capacitor |
| RV1 | 100k pot | the flash rate, wired as a rheostat |
| C1 | 10 µF electrolytic | the timing capacitor |
| C2 | 10 nF | on the control pin |
| C3 | 100 nF | decouples the supply |
| R2 | 470 Ω | limits the LED's current |
| LED1 | 5 mm LED | |
| J1 | 2-pin screw terminal | 9 V in |
| J2 | 3-pin header | OUT, +9 V, GND |

For the bench: a perfboard of about 5 × 7 cm (this page picks that size, and the window will
offer others), a soldering iron and solder, wire cutters and a multimeter. The guide's
continuity and resistance checks are for the multimeter.

## 1. Start from Home

![Home: the first example, the 555 blinker drawn and not yet built, is picked out](images/first-board/1-home.png)

On a first start Home is the whole window. Click the first example card, "A 555 blinker,
drawn and not built". It opens as an untitled copy, so nothing you do touches the original.
(The tour card beside it walks through the same circuit one sentence at a time.)

## 2. A circuit with no board yet

![The blinker on the sheet: ten symbols, seven nets, nothing on a board](images/first-board/2-drawn.png)

What opens is the circuit: ten parts and seven nets, drawn on the schematic, and none of it
on a board. The step bar along the top says where you stand (Circuit is done, Board is next),
and the button at its right end is the next thing to do. You press that button for every
step below.

## 3. Choose the board

![The board dialog: every stock size the circuit was tried on, with how well it builds on each](images/first-board/3-board.png)

**Choose a Board…** does not ask you to guess. It places and wires the circuit on a roomy
board, then on each smaller stock size, and shows each result with its size in holes and
what the wiring cost against the roomy one. The smallest board that builds as well is
suggested. Pick one (this page picks 5 × 7 cm) and press **Use This Board**.

## 4. Place the parts

![The parts placed on the 5 × 7 cm board](images/first-board/4-placed.png)

**Place on the Board** puts every part on the board: the connectors at the edge where a cable
reaches them, the pot where a finger can turn it. One Ctrl+Z takes the whole placement
back, and **Rearrange** (Ctrl+Shift+A) tries another arrangement.

## 5. Wire it

![The same board wired: solder traces and bare wires between the pads](images/first-board/5-wired.png)

**Auto-wire** lays every connection. A connection on perfboard is not one thing: it can be
a solder trace, a bare wire, an insulated wire or a jumper over the parts, and the router
prices them differently. On this board it wired 21 connections across all seven nets. Four
of them needed an insulated wire or a jumper, which the summary line at the bottom of the
window says.

The Problems drawer under the board has the verdict: no problems, and "Matches the circuit:
7 of 7 nets", which is the board's real connectivity extracted and compared with the
circuit you drew.

## 6. Open the build guide

![The build guide's first step: R1, 10k, from I2 to I5, with the holes and the part's height](images/first-board/6-guide.png)

**Open the Build Guide** shows the first step large: the board zoomed onto the step's holes,
the part that goes in, and which holes it goes in. **Done, next** ticks it and moves to the
next one.

![The guide's overview: eight phases, from the lowest parts to the copper on the solder side](images/first-board/7-overview.png)

**Overview** is the same guide as a list. On this board it is 31 steps across 8 phases,
with 45 checks and 20 wires to cut. The numbers change with the board you chose.

The order is the order you solder in, which is not the order of the schematic:

- **Parts go in lowest first**, so the board lies flat on the bench while you work: the
  resistors, then the chip's socket, then the small bodies, the electrolytic, and last the
  tall and mechanical parts.
- **Then the board is turned over** and the copper goes on: the solder traces, then the wires.
- **Checks sit between the phases** and say what to measure: "U1 pin 4 to C3(−) must show
  continuity" is the kind of check, and before power-on one says the supply must not read as a
  short to GND. They are derived from the circuit, so they name the holes of your board.

Where a part has a polarity or a pin 1, the step says which way round, and says to check it
against the part's datasheet.

## 7. Save it and take it to the bench

**Save the Board…** (Ctrl+S) keeps the board as a plain `.perf` file. **Save Project**
(Ctrl+Alt+S) also writes everything generated from it into an `outputs/` folder beside it:
the 1:1 print of the board, the schematic as SVG, PDF and PNG, the guide, the bill of
materials and the cut list.

## Where to go next

- The other examples, finished boards you can open and change, are described in
  [examples/README.md](../examples/README.md).
- To drive the same steps from an agent, see [docs/MCP.md](MCP.md).

This is pre-alpha software, and nobody has yet reported building a board from a generated
guide. Check every measurement against the part in your hand, and if something in the guide
is wrong, [an issue](https://github.com/medinstech/perfboard-studio/issues) is the most useful
thing you can send.
