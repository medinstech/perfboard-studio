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
- **They were tessellated** from STEP into triangles at 0.04 mm.
- **They were split by colour**, one mesh per colour the model was drawn with, so that the
  application can shade a metal tab and a plastic case differently.
- **Some were turned or shifted** so that the package sits on the holes of the footprint it
  is drawn for. The amounts are in `tools/import_kicad_models.py`.
- **Some had their leads bent.** A package made on a pitch the perfboard grid does not have
  — a radial electrolytic with its leads 2.5 mm apart, a 7.5 mm disc capacitor with 5 mm,
  a 6 mm tactile switch — has each bare lead leaned in a straight line from where it leaves
  the part to the hole it goes in, as whoever fits the part bends its legs. Which ones is
  the `splay` flag in `tools/import_kicad_models.py`.
- **One was cut into ways.** `screw-terminal-head`, `-way` and `-tail` are three slices of
  `TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal`, each moved so its own pin
  is at the origin; the application puts them side by side to draw a block of any length.

Nothing about the source models' geometry was otherwise altered, and no colours or
materials were taken from them into the application's own tables.

## Rebuilding them

With KiCad installed and `cadquery-ocp` available:

```sh
python tools/import_kicad_models.py
```

Neither is a dependency of the application. The meshes are checked in, and a build without
them still draws every board — the generated parametric bodies are the fallback for
everything.
