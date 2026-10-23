# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This file is loaded into every session, so it holds only the commands, the gates and the
invariants every change has to keep. Why everything else is the way it is lives in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), one decision to a section, and the
[list at the end of this file](#everything-else-docsarchitecturemd) says which section to
read before touching what.

## Commands

```sh
pip install -e ".[dev,mcp]"      # PySide6 + VTK + pytest/mypy/ruff + the MCP server

pytest                            # the whole suite
pytest tests/test_router.py       # one file
pytest tests/test_drc.py::test_name -x       # one test, stop on first failure
pytest -k "proximity"             # by name fragment

mypy --strict src                 # `src` ONLY — see below
ruff check src tests              # a gate: CI fails on a finding — see below

perfboard-studio                  # launch on a blank board
perfboard-studio some/board.perf  # ...or open a document
python -m perfboard_studio.ui.main --headless tools/diffcheck/golden/dense.perf
python -m perfboard_studio.mcp    # the MCP server (docs/MCP.md)
```

The suite is ~4500 tests in about four and a half minutes, so run all of it before a
commit; narrow to one file only while iterating.

**`mypy --strict src`, never `src tests`.** The engine is strict-clean and must stay
that way. The tests are not and never have been — `--strict` over `tests` reports ~267
errors, nearly all `no-untyped-def` on UI test helpers. CI gates on `src` alone, and
deliberately: gating on something already broken teaches everyone to ignore the red tick.

**Ruff is a gate; `ruff format` still must not be run casually.** `ruff check src tests`
is clean and CI fails on a finding. Two rules are switched off in `pyproject.toml` with
the reason at the switch: `E501`, because its 235 hits were prose a formatter could not
split either, and `RUF001`/`2`/`3`, because 137 of its 154 were the Turkish catalogue's
dotless ı — a rule that flags correct Turkish is a rule people learn to ignore.

Five suppressions in the source are load-bearing, not noise: `model.py`'s
`BoardMaterial`, `BoardType`, `BoardEdge`, `BodyArchetype` and `ConductorKind`, and
`router.py`'s `RoutingStyle`, keep the old `TypeAlias` spelling with `# noqa: UP040`
because they are read at run time by `get_args`, which returns an empty tuple for a PEP
695 `type` alias. Converting them made three completeness tests assert that an empty set
equals an empty set — and `BoardType` was found the same way later, refusing every board
type an agent asked for from a check that raises nothing.

`ruff format` would still rewrite 40 of the 57 files and point every line of blame in the
repository at a reformat. That is its own decision, not a side effect of another change.

`--headless` (`ui/headless.py`) renders 2D/3D/PDF, the schematic (SVG + PDF + PNG) and the
STEP model into
`headless_out/`, runs DRC + LVS and prints timings with no display. It is the only step
that exercises 2D, 3D and both exports against a real board end to end, and the fastest
way to check that a rendering change did not crash. It inspects a document and never edits
one. What the render LOOKS like is a separate question, answered by
`tests/test_render_golden.py` below.

**A test that renders through VTK must carry `@requires_offscreen_gl`** (`tests/test_gl.py`).
Without a GL context VTK does not raise, it aborts the process, so an unmarked test does
not fail — it ends the run partway through with no summary. `test_every_vtk_touching_test_is_marked`
finds them by reading the sources, because marking them by hand missed two.

**Three sets of goldens are this engine's own output rather than the TypeScript one's**, and
each is re-blessed by an environment variable, only after reading the diff or looking at the
render: the build guide (`tests/test_guide_golden.py`, `PERFBOARD_STUDIO_BLESS_GUIDE=1`), the
2D render (`tests/test_render_golden.py`, `PERFBOARD_STUDIO_BLESS_RENDER=1`) and the
schematic (`tests/schematic_golden/`, `PERFBOARD_STUDIO_BLESS_SCHEMATIC=1`). What each one
compares, and why, is in "CI and the goldens that are ours" in `docs/ARCHITECTURE.md`.

**Every destructive question in the window goes through `MainWindow._confirm`**, whose
button carries the verb and whose default is Cancel — `QMessageBox.question` with no
buttons named puts Yes under Enter. A test that needs the answer stubs
`type(window)._confirm`, never `QMessageBox.question`. Two more things a UI test must know:
`window._planner_running` is True while `_run_planner` pumps the event loop, and both the
file watcher and `closeEvent` stand down while it is; and the scene's modes survive a
rebuild by re-creating their markers in `_build` — a mode that keeps a wrapper to an item
`clear()` destroyed raises on the next disarm and takes every other mode with it, which is
what `test_measuring_survives_a_flip` is about.

UI tests run under `QT_QPA_PLATFORM=offscreen` (set in `tests/test_ui.py` before PySide6
is imported). Qt's offscreen plugin ships no font database on Windows, so tests that
assert on rendered *text* are skipped there — see the `skipif` guards in `test_ui.py`
before adding one.

The TypeScript side (`packages/`, pnpm + vitest) is the retired reference engine. Only
touch it to regenerate golden fixtures: `pnpm build && node tools/diffcheck/generate.mjs`.

## Invariants

### The document is immutable; every mutation is a command

`model.py` dataclasses are all `frozen=True, slots=True`. Nothing writes to a
`PerfDocument` in place. A mutation is a `CommandDefinition` in `commands.py` dispatched
through `CommandBus` (`command.py`), which builds a new document with
`dataclasses.replace` and records a `HistoryEntry`. The GUI, the MCP server, the headless
CLI and a replayed journal all go through that one bus — which is what makes undo/redo
work across a mixed human/agent session.

Adding a mutation means adding a command, not writing to the document from the caller.

**`persist.py` refuses at load what `board.set` refuses** — a board with no columns, a
zero pitch, a drill wider than its pad — and two components (or parts) sharing an id.
One fact, two consumers: a file with a zero pitch used to open without a word and then
every repaint divided by it, and a duplicated id is a part no command can ever reach.
A duplicated *reference* is a warning, like a diagonal solder-trace step: the board still
opens, and the ambiguity in the wiring is said out loud. `CommandBus.dispatch` catches a
payload of the wrong shape (`invalid-payload`) as well as `CommandError`, because "never
raises; callers branch on `ok`" has to hold for an agent handing it a dict, and the undo
stack is bounded (`UNDO_LIMIT`).

**A group of parts moved together is ONE `component.moveMany`** (`view2d._dispatch_moves`),
for drags and arrow-key nudges alike: one gesture, one undo step, all-or-nothing. A
locked part in the selection refuses the whole move and names itself.

**Commands enforce document integrity; DRC reports design quality.** Ids unique,
references resolve, paths on the board, model invariants hold → hard error, mutation
refused. Overlapping bodies, bridging risk, inadequate copper → reported by `drc.py`,
never refused. When deciding where a new check belongs, ask whether the result is still
a *document* (DRC) or not (command).

### The engine is pure

`src/perfboard_studio/` outside `ui/` and `mcp/` has no clock, no RNG, no filesystem, and no Qt
or VTK import. `persist.py` turns documents into strings and back; the *host* reads and
writes files. Timestamps (`meta.modified`) are stamped by the host, never the engine.
The placer's simulated annealing is seeded, so same document + same seed = same board.

Breaking this breaks the differential proof below.

### The differential proof

This Python engine is a port of the TypeScript one still in `packages/`. Its output is
frozen in `tools/diffcheck/golden/` and the tests assert against it byte-for-byte —
"produces identical results to the implementation we are replacing" rather than "all
tests pass". Three things depend on it:

- `test_persist.py::test_golden_round_trip_byte_identical` — every `*.perf` fixture must
  re-serialize to the exact bytes on disk. **This is why new optional fields must be
  omitted from the JSON when they hold their default** (see `stripAxis` for the pattern).
  A field emitted unconditionally breaks all 15 fixtures.
- `test_connectivity.py` / `test_occupancy_golden.py` — extracted nets must reproduce the
  `*.expected.json` arrays exactly.
- `test_autoroute.py` — the golden routes reproduce only with the default cost table, so
  changing `DEFAULT_ROUTER_COSTS` is a deliberate act with fixture regeneration attached.
  The planner's other starting orders (`autoroute._starting_orders`) go only to a builder
  committed to solder — a solder or lead-bend style, or no wire at all — because a trace
  cannot cross the ground rail laid first. A balanced plan starts from criticality alone,
  which is why the goldens, the guide golden and the placer (which prices every candidate
  placement through a balanced plan) did not move and did not slow down.

**Three recorded divergences, none of them a hole in the proof.** The
fixtures prove the port reproduces the original; that cannot also mean the port may never
improve on it. Each is named, excluded from the comparison rather than edited into an
`.expected.json` (those are dumps from the TypeScript engine, and hand-editing one makes
the next regeneration silently disagree), and pinned by its own test:

- `PYTHON_ONLY_RULES` — rules the original never had (`conductor-crossing`,
  `jumper-under-body`, `conductor-off-board`, `unknown-footprint`,
  `component-overhangs-edge`, `wire-too-thick-for-hole`, `terminal-entry-blocked`,
  `terminal-entry-faces-in`, `wire-over-joint`, `no-hole`, `not-on-breadboard`), so
  there is nothing for a fixture to record.
  `unknown-footprint` fires on eight of the fifteen fixtures, every time
  on the id `c-disc-1`, which exists in neither engine: the fixtures are dumps of the
  original and are left exactly as they are, so the rule is excluded here and pinned by
  its own test. `tests/test_placer.py` measures the placer against `PLACEMENT_ERRORS`
  only, for the same reason — no arrangement of parts makes that footprint exist.
  `component-overhangs-edge` fires on none of them, and a test says so.
- `SHARPER_THAN_TYPESCRIPT` — one finding the original reported and this engine does not:
  `random-02`'s X3 against X6, a rectangle clipping the corner of an electrolytic's 24-gon
  courtyard where the boxes meet and the shapes do not. 41 body-overlap findings across
  the fixtures become 40. Adding to this dict needs a test asserting the GEOMETRY, not
  just the absence.
- `DIVERGES_FROM_TYPESCRIPT` in `test_footprints.py` — `xtal-hc49`, whose can the original
  had as 4.65 × 3.5 mm (its thickness along the leads and a height across them) where it
  is 11.05 × 4.65 mm on the board, so a crystal stood on U1's pin on atmega328-relay and DRC
  saw nothing. Only the outline and `dims` are excused; every other field is still
  compared, and `test_the_crystal_is_as_long_as_the_can` pins the geometry.

`persist.py` hand-rolls its JSON writer to match `JSON.stringify(x, null, 2)` byte for
byte (whole-number floats print as `1`, not `1.0`), and every object's key order comes
from an explicit `*_KEY_ORDER` tuple, never dict insertion order.

### A perfboard connection is not one thing

The idea the project rests on. `ConductorKind` has six physically distinct members (lead
bend, solder trace, wired solder trace, bare wire, insulated wire, top jumper) with
different costs, limits and failure modes. Two predicates in `model.py` carry most of the
weight:

- `contacts_every_path_hole` — a solder trace is soldered down at *every* pad it crosses;
  a wire touches only its two endpoints and merely lies over the holes between. Getting
  this wrong silently produces a board wired differently from what the screen shows.
- `is_crossing_blocked` — what occupies the copper plane and therefore cannot cross.

This is why `connectivity.py` ("what is electrically joined") and `occupancy.py` ("what
is physically in the way") are separate modules over the same conductors.

`SolderTraceConductor.path` must be an orthogonal chain — solder cannot span a diagonal
gap. `geometry.validate_orthogonal_chain` is the only adjacency check in the codebase;
a hand-edited file that violates it loads with a *warning* and is reported by DRC, rather
than locking the user out of their own project.

**A wire's gauge is one answer with three askers** (`wiregauge.py`). DRC's
`current-capacity` measures a wire on a net that declares a current, `router.py` and
`striproute.py` write the gauge onto the wires they lay for such a net, and `guide.py`
prints it on the cut list — all through `cut_gauge_awg`: the gauge the document stores,
or else the one `wire_gauge_for_current` picks. The guide used to keep its own table and
DRC looked at no wire at all, which is how the cut list came to print AWG 18 for 50 A.
Two things about it are deliberate:

- **Rule 6 measures wires under the TypeScript rule id.** PLAN.md §5.2 rule 6 always said
  "wire or solder trace" and the original measured only the trace. No golden fixture
  declares a current, so the wire half cannot move a recorded finding — which is why it is
  not in `PYTHON_ONLY_RULES`. A fixture regenerated with currents and wires would show it.
- **A net that declares no current gets no stored gauge.** The router writes `None` and the
  guide still prints AWG 24 for it, so every golden route and every fixture keeps its bytes.

### Hole addressing

`HoleCoord(col, row)` is 0-indexed from the top-left, row growing downward.
`HoleRef` ("A1", "AC12", bijective base-26) is the language every user-facing message
speaks — the guide, DRC, the router's explanations, the MCP tools. `geometry.py` owns the
conversion:

- `coord_to_hole_ref` is strict and round-trips with `hole_ref_to_coord`.
- `format_hole` never raises — use it in any message, since off-board coordinates are
  negative by definition and that is exactly what the failing checker needs to print.
- **`format_hole(c, board)` takes the board, and every caller that has one passes it**: a
  breadboard prints its own addresses (`docs/ARCHITECTURE.md`, "A breadboard is stripboard
  nobody can cut"), so the answer depends on which board the hole is on. On every other
  board it is exactly the grid address, which is why no golden moved. A guide or export
  helper that names a hole takes `board` as a REQUIRED keyword (`*, board: Board | None`),
  so a new caller that forgets it is a type error rather than a breadboard guide quietly
  printing grid addresses. `parse_hole(text, board)` is the inverse, for anything a person
  or an agent types.

**`board_size_mm` vs `hole_span_mm` is a real trap.** The substrate extends half a pitch
past the outermost hole centres — plus `board.border_x_mm` / `border_y_mm` on a board cut
with a printed border — so they differ. Mirroring the board to the solder side reflects
about the *hole span*; reflecting about the substrate size shifts every hole and the user
solders the board backwards without the view ever looking wrong. Rule of thumb: holes and
routing use `hole_span_mm`; substrate, printing and 3D use `board_size_mm` /
`board_outline_mm`, and anything asking "how much bare board is outside the grid" uses
`board_edge_margin_mm(board, axis)`. Nothing recomputes any of them locally —
`ui/view2d._outline_rect` and `ui/view3d._board_size_mm` both delegate.

The border is **per axis** because real boards are not square about it (a 5 × 7 cm board
has ~2.1 mm at the sides, ~4.5 mm top and bottom), and the 1:1 PDF gets taped to the
physical board. `geometry.STANDARD_PRESETS` carries the sizes suppliers stock, keyed on
the advertised centimetres; `board_from_preset` *solves* the border from the size and the
hole count rather than quoting it.

### Layering

```
model → geometry → stripboard → connectivity / occupancy
                                    → erc, drc, lvs, router, autoroute, placer, ratsnest,
                                      striproute, schematic
                                                        → boardfit, step_export
                                                        → guide → guide_export
                                                        → ui/, mcp/
```

`boardfit.py` sits below `placer`, `autoroute` and `drc` because it is all three run in a row
on a candidate board and then compared; nothing in the engine imports it.

`breadboard.py` hangs off `model` alone too, and `geometry` imports it: see "A breadboard is
stripboard nobody can cut" in `docs/ARCHITECTURE.md`.

`wiregauge.py` hangs off `model` alone — it is arithmetic on a gauge number — and is read
by `drc`, `router`, `striproute` and `guide`, which is how three siblings and their
downstream share one fact without importing one another.

`phrasebook.py` hangs off nothing at all -- a table and a lookup -- and is read by `guide`,
`guide_export` and `ui/partnames`. See "i18n" below for why the guide is translated there.

`schematic.py` sits beside `ratsnest.py` on purpose: both take a document and a footprint
lookup and answer a question about the netlist, and neither is downstream of the other.
`ui/viewsch.py` is its only consumer.

### i18n

`ui/i18n.py` is a plain dict whose **keys are the English strings**, wrapped at each call
site with `t()`. `tests/test_i18n.py` scans the UI source and fails if the catalogue names
a string the interface no longer has, if a translation loses its `&` accelerator, or if
two items in one menu claim the same accelerator — so adding a menu item means adding its
Turkish entry and, if it is in one of the grouped menus, extending that test's group list.

It also fails the **other** direction, which is the one that let every tooltip stay
English while the menus were translated: `test_no_tooltip_or_placeholder_is_left_out_of_the_catalogue`
flags a `setToolTip` / `setPlaceholderText` / `setHeaderLabels` argument that is a bare
literal. A string never wrapped in `t()` is not a missing translation — it is not in the
system at all, so it moves no coverage number and nothing else would ever mention it. The
exceptions are derived, not listed: prose has a four-letter word in it, and the strings
deliberately left alone (`"GND, +5V, OUT…"`, `"R1, C3, U2…"`, `"10k, 100nF, NE555…"`) are
the tool's own vocabulary, whose longest alphabetic run is two.

The scanner treats **adjacent string literals as one key** (`ast.literal_eval` over the
lot), because a tooltip lives in the source as three quoted fragments on three lines.
`setText` is deliberately outside all of this: it is what every status field and every
f-string of engine output goes through.

Engine-generated text (DRC/LVS messages, rule ids, hole addresses, net and component
names) is not translated by the interface: it is compared byte-for-byte by golden
fixtures, and the addresses are the tool's vocabulary in every language.

**The build guide is the one exception, and it is translated in the ENGINE**
(`phrasebook.py`), not by `t()`. Its sentences are built from facts ("C7 → C11, 4 holes
apart"), so there is no finished English for the interface to translate after the fact,
and the MCP server and `--headless` write it with no interface loaded.
`GuideOptions.language` picks the language, `Guide.language` carries it so every exporter
says its own words (headings, columns, a step's tag) in the same one, and the window builds
every guide it shows or writes in its own language (`MainWindow._guide_language`). Four
rules hold it together:

- **The key is the English template, with NAMED fields** (`say("{hole} sits about one pad
  gap from {neighbour}...", hole=..., neighbour=...)`), so a translation orders them as its
  grammar needs. English is the key itself, which is why every English guide golden stayed
  byte for byte what it was while this was built -- and must stay so.
- **Ids stay ids.** An archetype, a conductor or checkpoint kind, a warning code and a wire
  colour are data in the guide's model and its JSON; they are said in words where they are
  SHOWN, by looking the id up like any other key. The JSON gains a `language` key only when
  it is not English (the `stripAxis` rule, for an export).
- **An address never takes a Turkish suffix** -- "C7'ye" needs the reader's pronunciation of
  a letter -- so the suffix goes on the word beside it: "C7 deliğine".
- **Footprint names are re-said, not renamed.** `phrasebook.NAME_TEMPLATES` recognises the
  engine's own phrasings and the footprint golden never moves; the Parts panel reads the
  same table (`ui/partnames.py`), so a part is called one thing in the list and the guide.

`tests/test_phrasebook.py` reads what the guide says out of the SOURCE (every literal handed
to `say`) and out of the tables it says from, and holds the Turkish to it in both directions,
field for field -- then builds every board in the repository in both languages and looks for
English words the two share, which is what a sentence nobody wrapped looks like from the
outside. `tests/test_guide_golden.py` freezes the NE555 guide in Turkish beside the English.

**Turkish stops at what the builder sees**: the interface, the build guide and
`README.tr.md`. `docs/`, `CHANGELOG.md`, `CONTRIBUTING.md` and this file are English on
purpose — their readers are developers and agents, and keeping pages in two languages
means making every change twice. Do not add a `.tr.md` beside them.

The two READMEs are held to one SHAPE rather than one meaning by `tests/test_docs.py`:
the same headings at the same levels, the same code blocks and table rows, and the same
inline code spans, counted. A translation cannot be checked for meaning, but a paragraph
added to one README and not the other is exactly a heading, a row or a handful of
identifiers that exist on one side only — so a change to one README is made to both in
the same commit. It earned its place on the first run, which found the Turkish README
calling the whole project Apache-2.0 in every release since the meshes arrived in 0.12.0.
In-page links are checked on every page, against GitHub's slugger exactly, marks
included: a heading that starts with "İ" gets an anchor with an invisible U+0307 in it,
so do not start one so.

The language is chosen `--lang` → `PERFBOARD_STUDIO_LANG` → the View menu's stored choice → the
system locale (`main._preferred_language`), and applies at the **next start**: every label
is translated once, as the window is built, so a live re-translation would leave whatever
a rebuild missed in English.

## Everything else: docs/ARCHITECTURE.md

The rest of the record, one section per decision, each with the first attempt that went
wrong and the test that pins it. It is NOT loaded with this file, so read the section about
the code you are changing before changing it; `grep -n '^## ' docs/ARCHITECTURE.md` gives
each section's line. A new section is written there and listed here, never written into
this file: `tests/test_docs.py` fails on a section this list does not name, and on this file
growing past 40 000 characters.

- Before re-blessing a golden, or when CI fails on one operating system only → [CI and the
  goldens that are ours](docs/ARCHITECTURE.md#ci-and-the-goldens-that-are-ours)
- Before touching `_run_planner`, or anything else that runs Python on a `QThread` → [The
  planner thread holds the cyclic collector
  off](docs/ARCHITECTURE.md#the-planner-thread-holds-the-cyclic-collector-off)
- Before measuring a part against the board's edge (`component-overhangs-edge`,
  `body_extent`) → [A body past the edge is measured on the
  body](docs/ARCHITECTURE.md#a-body-past-the-edge-is-measured-on-the-body)
- Before touching screw terminals, wire entries, mounting-hole clearance or
  `PHYSICAL_WARNING_RULES` → [A screw terminal has a
  mouth](docs/ARCHITECTURE.md#a-screw-terminal-has-a-mouth)
- Before touching parts mounted off the board (`wire-<n>` footprints, `off_board_mount`, the
  guide's lead list) → [A part off the board is the pads its wires land
  in](docs/ARCHITECTURE.md#a-part-off-the-board-is-the-pads-its-wires-land-in)
- Before bumping `version.py` or `DOCUMENT_FORMAT_VERSION` → [Two version
  numbers](docs/ARCHITECTURE.md#two-version-numbers)
- Before touching `footprints.py`, a generated footprint id, or anything that reads
  `body_outline` → [Footprints are generated, not
  shipped](docs/ARCHITECTURE.md#footprints-are-generated-not-shipped)
- Before touching `component-too-tall`, `jumper-under-body` or `heat-proximity`, or what the
  placer, router or guide does about them → [Three rules only the third dimension can
  see](docs/ARCHITECTURE.md#three-rules-only-the-third-dimension-can-see)
- Before touching `placer.arrange`, a placement cost term, `_build_cost`, `_pick_best` or
  `place_design` → [Placement is arranged first and annealed
  second](docs/ARCHITECTURE.md#placement-is-arranged-first-and-annealed-second)
- Before touching the stock-board suggestion or `boardfit.py` → [Which board to buy is
  tried, not estimated](docs/ARCHITECTURE.md#which-board-to-buy-is-tried-not-estimated)
- Before touching pad shapes, R5' (`solder-trace-proximity`), the printed legend, mounting
  holes, edge-connector fingers, `unusable_holes` or the holes in the 3D board → [A pad is
  not always round, and the board may say where it
  is](docs/ARCHITECTURE.md#a-pad-is-not-always-round-and-the-board-may-say-where-it-is)
- Before touching 3D materials, lighting, shadows or the tone curve (`view3d._finish`,
  `PERFBOARD_STUDIO_SIMPLE_3D`) → [Parts are shaded as materials, and the room is generated
  too](docs/ARCHITECTURE.md#parts-are-shaded-as-materials-and-the-room-is-generated-too)
- Before touching the KiCad meshes, `ui/partmodels.py` or `tools/import_kicad_models.py`, or
  their CC-BY-SA licence → [Packages borrowed from KiCad, and what was NOT
  borrowed](docs/ARCHITECTURE.md#packages-borrowed-from-kicad-and-what-was-not-borrowed)
- Before touching `ui/moduleart.py`, or how a module or a vertical terminal is drawn → [A
  module is drawn by what it is called, and never past its
  envelope](docs/ARCHITECTURE.md#a-module-is-drawn-by-what-it-is-called-and-never-past-its-envelope)
- Before touching `step_export.py` → [The board leaves as STEP solids, and they are the
  bodies DRC
  measured](docs/ARCHITECTURE.md#the-board-leaves-as-step-solids-and-they-are-the-bodies-drc-measured)
- Before touching the build guide's phase order, polarity notes or checkpoints → [The
  guide's order is physical, and its checks are
  derived](docs/ARCHITECTURE.md#the-guides-order-is-physical-and-its-checks-are-derived)
- Before touching `erc.py` → [The circuit is checked before the
  board](docs/ARCHITECTURE.md#the-circuit-is-checked-before-the-board)
- Before touching `doc.parts`, `part.place` / `component.unplace`, references or renames →
  [The design comes before the board, and the sheet is drawn from
  it](docs/ARCHITECTURE.md#the-design-comes-before-the-board-and-the-sheet-is-drawn-from-it)
- Before touching the schematic: the hand-drawn sheet, `SheetWire`, symbol shapes, rotation,
  or the SVG / PDF / PNG export → [Two kinds of sheet, and the document decides
  which](docs/ARCHITECTURE.md#two-kinds-of-sheet-and-the-document-decides-which)
- Before touching the step bar (`ui/workflow.py`), choosing a board in the window, or the
  toolbars → [The window walks through six
  steps](docs/ARCHITECTURE.md#the-window-walks-through-six-steps)
- Before touching docks, `WINDOW_STATE_VERSION`, which panel is in front, the sheet's tools,
  dragging between views or the sheet's right-click menu → [The window is panels all the way
  down](docs/ARCHITECTURE.md#the-window-is-panels-all-the-way-down)
- Before touching `mcp/`, and before adding an MCP tool → [The MCP server is behaviour in
  one file, protocol in the
  other](docs/ARCHITECTURE.md#the-mcp-server-is-behaviour-in-one-file-protocol-in-the-other)
- Before touching stripboard cuts, `striproute.py` or strip conflicts in the placer →
  [Stripboard is the board where the copper is
  subtracted](docs/ARCHITECTURE.md#stripboard-is-the-board-where-the-copper-is-subtracted)
- Before touching breadboards: `breadboard.py`, `breadroute.py`, hole names like `e12`, or
  how one is drawn, exported or guided → [A breadboard is stripboard nobody can
  cut](docs/ARCHITECTURE.md#a-breadboard-is-stripboard-nobody-can-cut)
- Before touching solderable breadboards, or `has_breadboard_pattern` against
  `is_breadboard` → [A solderable breadboard is the same pattern in
  copper](docs/ARCHITECTURE.md#a-solderable-breadboard-is-the-same-pattern-in-copper)
- Before touching `view2d`'s coordinates, `PadGridItem` or `scenetext`'s label sizes → [The
  2D view is in millimetres, and its costs were
  measured](docs/ARCHITECTURE.md#the-2d-view-is-in-millimetres-and-its-costs-were-measured)
- Before touching how solder runs and wires are drawn in 3D, or `stacking_layers` → [A
  solder run is IN the surface and a wire is ON
  it](docs/ARCHITECTURE.md#a-solder-run-is-in-the-surface-and-a-wire-is-on-it)
- Before touching picking in 3D or the selection tint → [A click in 3D is a third door to
  the same
  selection](docs/ARCHITECTURE.md#a-click-in-3d-is-a-third-door-to-the-same-selection)
- Before adding a visual option, or a colour to one of the three colour tables → [Appearance
  is a view setting, not a document
  field](docs/ARCHITECTURE.md#appearance-is-a-view-setting-not-a-document-field)
- Before touching `parsers/`, `ui/headless.py` or `ui/clipboard.py` → [Parsers, the headless
  run and the clipboard](docs/ARCHITECTURE.md#parsers-the-headless-run-and-the-clipboard)
- Before touching the file watcher, crash recovery or autosave → [The open file is watched,
  and unsaved work outlives a
  crash](docs/ARCHITECTURE.md#the-open-file-is-watched-and-unsaved-work-outlives-a-crash)
- Before touching project folders (`project.py`, `outputs/`) → [A project is a folder, and
  the board in it is still a plain
  `.perf`](docs/ARCHITECTURE.md#a-project-is-a-folder-and-the-board-in-it-is-still-a-plain-perf)
- Before touching `router.py`'s sets, wires laid along the grid, or bend costs → [The router
  keys its own sets, and lays wires on the
  grid](docs/ARCHITECTURE.md#the-router-keys-its-own-sets-and-lays-wires-on-the-grid)
- Before touching `QSettings`, the restored window layout or the guide's ticks → [What the
  window remembers](docs/ARCHITECTURE.md#what-the-window-remembers)
- Before touching the update check (`updates.py`, `ui/updater.py`) → [The update check
  decides nothing on the network and installs nothing at
  all](docs/ARCHITECTURE.md#the-update-check-decides-nothing-on-the-network-and-installs-nothing-at-all)
