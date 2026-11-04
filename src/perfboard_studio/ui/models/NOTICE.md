# Where these meshes came from

Every `.ply` file in this directory is a mesh of one through-hole package, derived from the
**KiCad `packages3D` library** — <https://gitlab.com/kicad/libraries/kicad-packages3D> —
by `tools/import_kicad_models.py` in this repository. `index.json` says which KiCad model
each one came from, under `source`.

## Licence

The KiCad libraries are licensed **CC-BY-SA 4.0 with an exception**, and the full text is
in [`LICENSE`](./LICENSE) beside this file. These meshes are derived from that library, so
they carry the same licence. **They are the only part of Perfboard Studio that is not
Apache-2.0.**

Two things follow, and both matter:

- **A board you design with this tool is not affected.** That is what the exception in the
  licence is for, and it is the same position anybody using KiCad's own libraries is in.
  Your `.perf` file, your schematic, your build guide and the board on your bench are
  yours.
- **Redistributing these meshes carries the licence with it.** If you fork this repository
  or ship a build of it, this directory keeps its `LICENSE` and this notice.

## What was changed

The meshes are not the KiCad models unaltered:

- **Everything below the board surface was cut away.** Perfboard Studio draws its own leads
  through the holes, because it knows the board's thickness and how far past the copper a
  trimmed lead stands; a model's own legs are drawn untrimmed and would hang out of the
  solder side.
- **They were tessellated** from STEP into triangles at 0.04 mm, and a facet turning at most
  0.3 rad -- 0.5 rad for the resistors and diodes stood on end (`STANDING_ANGULAR`), whose
  thin bent-over leads were half of their size at 0.3 for no difference anybody can see.
  A mesh that is the same triangles as another (a standing part's barrel at both pitches)
  is one file, named by both entries.
- **They were split by colour**, one mesh per colour the model was drawn with, so that the
  application can shade a metal tab and a plastic case differently.
- **Some were turned or shifted** so that the package sits on the holes of the footprint it
  is drawn for. The amounts are in `tools/import_kicad_models.py`.
- **Some had their leads bent.** A package made on a pitch the perfboard grid does not have
  — a radial electrolytic with its leads 2.5 mm apart, a 7.5 mm disc capacitor with 5 mm,
  a 6 mm tactile switch — has each bare lead leaned in a straight line from where it leaves
  the part to the hole it goes in, as whoever fits the part bends its legs. Which ones is
  the `splay` flag in `tools/import_kicad_models.py`.
- **Two were cut into ways.** `screw-terminal-head`, `-way` and `-tail` are three slices of
  `TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal`, and `screw-terminal-v-head`,
  `-way` and `-tail` three slices of
  `Connector_Phoenix_MSTB/PhoenixContact_MSTBVA_2,5_3-G-5,08_1x03_P5.08mm_Vertical`, each moved
  so its own pin is at the origin; the application puts them side by side to draw a block, or
  a header, of any length.
- **Six are another model turned.** A resistor stood over its second pin
  (`axial-<n>h-<L>x<D>-v2`) is the same KiCad `R_Axial_..._Vertical` model as the one over
  its first, turned half round and shifted by the span: `index.json` says `like`, with the
  turn and the shift, and names no files of its own.
- **One stands on another.** KiCad's `Display/WC1602A` is the 16 x 2 LCD module alone,
  4.4 mm above the board with nothing under it, so the 1 x 16 header it is soldered in by,
  `Connector_PinHeader_2.54mm/PinHeader_1x16_P2.54mm_Vertical`, is merged into its meshes,
  turned a quarter so its pins run along the module's (the `header` field in
  `tools/import_kicad_models.py`).
- **Some were painted another colour**, where the model shows another variant of the part
  than the one builders hold: the LCD's glass is yellow-green rather than beige, and
  Lite-On's LTS-6760 digit has the black face of the four-digit display beside it rather
  than a beige one; the bottom of a buzzer's sound hole is dark rather than red-brown. Which
  ones is the `colours` field in `tools/import_kicad_models.py`.
- **One was made shorter.** The 8.5 mm passive buzzer is `Buzzer_12x9.5RM7.6`, the 9.5 mm
  active one's 12 mm can, scaled in height to CUI's CEM-1203(42) (the `height` field).

Nothing about the source models' geometry was otherwise altered, and no colours or
materials were taken from them into the application's own tables.

`topviews.json` is derived from these meshes in turn: what each one looks like from straight
above, traced into outlines by `tools/make_topviews.py`, with each printed or moulded
marking's colour beside it. It carries the same licence.

## Rebuilding them

With KiCad installed and `cadquery-ocp` available:

```sh
python tools/import_kicad_models.py
```

Neither is a dependency of the application. The meshes are checked in, and a build without
them still draws every board — the generated parametric bodies are the fallback for
everything.

## Measured on photographs

What stands on a module (`ui/moduleart.py`) is drawn by this application, and no image is
shipped with it. Where no maker publishes a drawing of the parts on a module, their positions
were measured on a photograph of one, scaled by its header; each is credited here and in its
layout's `source`:

- **GY-521 (MPU-6050)** — photograph by Nevit Dilmen, Wikimedia Commons, CC BY-SA 3.0:
  <https://commons.wikimedia.org/wiki/File:GY-521_MPU-6050_Module_3_Axis_Gyroscope_%2B_Accelerometer_0487.jpg>
  (106.5 px/mm on its header)
- **SSD1306 0.96 inch I2C OLED** — photograph by Turbospok, Wikimedia Commons, CC BY-SA 4.0:
  <https://commons.wikimedia.org/wiki/File:MicroSD_card_connected_to_Arduino_nano_with_OLED_display.jpg>
  (22.95 px/mm on its header)
- **ESP-01** — photograph by SparkFun Electronics, Wikimedia Commons, CC BY 2.0:
  <https://commons.wikimedia.org/wiki/File:ESP-01.jpg> (oblique, rectified onto the board
  Ai-Thinker draws)
- **nRF24L01+ module** — photograph by Dmcole, Wikimedia Commons, CC BY-SA 3.0:
  <https://commons.wikimedia.org/wiki/File:NRF24l01_Nordic_Semiconductor_radio.JPG>
  (oblique, rectified onto the board KiCad's `nRF24L01_Breakout` draws)
- **HC-SR04** — photographs by Nevit Dilmen, Wikimedia Commons, CC BY-SA 3.0:
  <https://commons.wikimedia.org/wiki/File:HC_SR04_Ultrasonic_sensor_1480322_3_4_HDR_Enhancer.jpg>
  (its front, 27.8 px/mm on its header), and by Suyash Dwivedi, CC BY-SA 4.0:
  <https://commons.wikimedia.org/wiki/File:HC-SR04_ultrasonic_distance_sensor_module_pcb.jpg>
  (its back: the header behind the board)
