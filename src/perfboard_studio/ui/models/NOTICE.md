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
- **Two lost their legs.** `Relay_SPDT_SANYOU_SRD_Series_Form_C`'s blades and
  `LED_D5.0mm-4_RGB`'s 1.27 mm legs are hidden under their bodies and stand beside the
  holes the footprints have always had, so they were left off (the `leads` field); the
  relay's case is drawn at the 19.1 x 15.5 x 15.3 mm of Songle's drawing, a few tenths
  smaller than KiCad's, and the LED lowered the 3 mm KiCad stands it up so it sits on the
  board as its footprint measures it (the `case_size` and `sink` fields).
- **One was made bigger.** KiCad has no model of the DHT22 (AM2302), so it is
  `Sensor/Aosong_DHT11_5.5x12.0_P2.54mm`, the DHT11's grilled case, scaled to Aosong's
  15.1 x 7.7 x 25.1 mm drawing of the DHT22 and painted white, its leads left where they
  meet the board (the `case_size` field). Its grille is the DHT11's, stretched.

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

## Measured on makers' board files

Where the maker publishes the module's own board, the parts on it were measured there --
positions, packages and turns, never its artwork -- and nothing of the file is shipped:

- **SparkFun Arduino Pro Mini 328** -- SparkFun Electronics, Eagle board, CC BY-SA 3.0:
  <https://github.com/sparkfun/Arduino_Pro_Mini_328> (`Hardware/Arduino-Pro-Mini.brd`)
- **SparkFun Pro Micro** -- SparkFun Electronics, Eagle board, CC BY-SA 3.0:
  <https://github.com/sparkfun/Pro_Micro> (`Hardware/v13/SparkFun_Pro_Micro.brd`)
- **SparkFun Logic Level Converter - Bi-Directional** -- SparkFun Electronics, Eagle board,
  CC BY-SA 3.0: <https://github.com/sparkfun/Logic_Level_Bidirectional>
  (`Hardware/Logic_Level_Bidirectional.brd`)
- **Adafruit INA219 Current Sensor**, both revisions -- Adafruit Industries, Eagle boards,
  Creative Commons Attribution/Share-Alike, designed by Limor Fried/Ladyada:
  <https://github.com/adafruit/Adafruit-INA219-Current-Sensor-PCB>
  (`Adafruit_INA219_CurPowerMonitor.brd`, `Adafruit INA219 STEMMA QT.brd`)
- **Adafruit BME280 and BMP280 breakouts** -- Adafruit Industries, Eagle boards and
  photographs, Creative Commons Attribution/Share-Alike, designed by Limor Fried/Ladyada:
  <https://github.com/adafruit/Adafruit-BME280-Breakout-PCB>,
  <https://github.com/adafruit/Adafruit-BMP280-Breakout-PCB>
- **NodeMCU DevKit 1.0** -- the NodeMCU team, Gerbers, PCB print, schematic and
  photograph, MIT: <https://github.com/nodemcu/nodemcu-devkit-v1.0>
- **SparkFun Motor Driver - Dual TB6612FNG v1.1c** -- SparkFun Electronics, Eagle board
  (`SparkFun_Motor_Driver-TB6612FNG_v11c.brd`), credited here as the Pro Mini's is
- **Adafruit TCA9548A I2C Multiplexer** -- Adafruit Industries, Eagle board, CC BY-SA 3.0:
  <https://github.com/adafruit/Adafruit-TCA9548A-I2C-Multiplexer-PCB> (`Adafruit TCA9548A.brd`)
- **Adafruit ADS1115 STEMMA QT** -- Adafruit Industries, Eagle board:
  <https://github.com/adafruit/ADS1X15-Breakout-Board-PCBs>
  (`Adafruit ADS1115 ADC STEMMA QT.brd`); the repository states no licence, and only the
  parts' places, packages and turns were read from it
- **Adafruit SCD-40 / SCD-41** -- Adafruit Industries, Eagle board, CC BY-SA 3.0:
  <https://github.com/adafruit/Adafruit-SCD-4x-PCB> (`Adafruit SCD-41.brd`)
- **Adafruit DRV8871 motor driver** -- Adafruit Industries, Eagle board, CC BY-SA 3.0:
  <https://github.com/adafruit/Adafruit-DRV8871-Breakout-PCB> (`Adafruit DRV8871.brd`)
- **Adafruit MAX4466 microphone amplifier** -- Adafruit Industries, Eagle board, CC BY-SA 3.0:
  <https://github.com/adafruit/Adafruit-MAX4466-Electret-Mic-Amplifier-PCBs>
  (`Adafruit MAX4466 Mic Amp.brd`)
- **Adafruit MAX9814 AGC microphone** -- Adafruit Industries, Eagle board, CC BY-SA 3.0:
  <https://github.com/adafruit/Adafruit-MAX9814-AGC-Microphone-PCB> (`Adafruit MAX9814.brd`)
- **Adafruit 1.14 inch 240 x 135 TFT** -- Adafruit Industries, Eagle board and product
  photograph 4383, CC BY-SA 3.0: <https://github.com/adafruit/Adafruit-1.14-inch-240x135-TFT-PCB>
  (`Adafruit 1.14-inch 240x135 Color TFT.brd`)
- **Adafruit PCF8574 QT** -- Adafruit Industries, Eagle board and product photograph 5545,
  CC BY-SA 3.0: <https://github.com/adafruit/Adafruit-PCF8574-PCB> (`Adafruit PCF8574 QT.brd`,
  `assets/5545.jpg`: the parts' places from the board, the black board, the gold holes and
  the chip's marking from the photograph)
- **SparkFun ACS712 current sensor breakout** -- SparkFun Electronics, Eagle board,
  CC BY-SA 4.0: <https://github.com/sparkfun/Hall-Effect_Current_Sensor_Breakout-ACS712>
  (`Hardware/SparkFun_ACS712_Breakout_v11.brd`)
- **SparkFun Soil Moisture Sensor** -- SparkFun Electronics, Eagle board, CC BY-SA 4.0:
  <https://github.com/sparkfun/Soil_Moisture_Sensor> (`Hardware/SparkFun_Soil_Moisture_Sensor.brd`)
- **SparkFun Thumb Joystick breakout** -- SparkFun Electronics, Eagle board, CC BY-SA 4.0:
  <https://github.com/sparkfun/Thumb_Joystick_Breakout> (`Hardware/Joystick-Breakout-v12.brd`)
- **SparkFun Rotary Encoder Breakout - Illuminated** -- SparkFun Electronics, Eagle board,
  CC BY-SA 4.0: <https://github.com/sparkfun/Rotary_Encoder_Breakout-Illuminated>
  (`Hardware/SparkFun_Rotary_Encoder-Illuminated.brd`); the encoder's bracket, bushing and
  shaft from Top-Up Industry's drawing EC12PSD-062 rev B as SparkFun hosts it for COM-15141:
  <https://cdn.sparkfun.com/assets/e/1/a/4/7/MD-15141-_Rotary_Encoder_-_Illuminated__RGB_.pdf>
  (dimensions only)

## Measured on makers' drawings

Where a maker publishes a dimension drawing and no board file, the sizes and places were
read off the drawing; no part of the drawing is shipped:

- **DFRobot DFPlayer Mini (DFR0299)** -- DFRobot's dimension drawing v1.1
  <https://dfimg.dfrobot.com/wiki/20532/DFR0299_mp3-player-module_dimension_v1.1.jpg> (the
  board, the micro SD socket's outline and pads, the 0603s' and the LED's pads, the
  silkscreen's place) and the pinout picture on <https://wiki.dfrobot.com/DFPlayer_Mini_SKU_DFR0299>
  (the board's colour, which side the socket's latch is on, which chips are capacitors and
  which resistors). Neither states a licence -- the wiki says "All rights reserved" -- so
  only dimensions and those facts were measured, and nothing of either image is copied

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
- **ESP32 DevKit V1 (30-pin)** — photograph by Edwiyanto, Wikimedia Commons, CC BY-SA 4.0:
  <https://commons.wikimedia.org/wiki/File:ESP32_Dev_Board.jpg>
  (rectified to the board's plane on 25 of its 30 pads, about 33.9 px/mm)
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
- **HC-SR501 PIR** — photograph by Nowforever, Wikimedia Commons, CC BY-SA 4.0:
  <https://commons.wikimedia.org/wiki/File:PIR_sensor_for_arduino.jpg> (oblique, rectified
  onto the 32 x 24 mm board TruSens' sheet draws)
- **ESP32-CAM** — photograph by Nowforever, Wikimedia Commons, CC BY-SA 4.0:
  <https://commons.wikimedia.org/wiki/File:ESP32-CAM.jpg> (its camera side, about 42 px/mm on
  its sixteen header pins)
