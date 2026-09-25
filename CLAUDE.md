# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```sh
pip install -e ".[dev,mcp]"      # PySide6 + VTK + pytest/mypy/ruff + the MCP server

pytest                            # the whole suite
pytest tests/test_router.py       # one file
pytest tests/test_drc.py::test_name -x       # one test, stop on first failure
pytest -k "proximity"             # by name fragment

mypy --strict src                 # `src` ONLY — see below
ruff check src tests --statistics # reports; NOT a gate — see below

perfboard-studio                  # launch on a blank board
perfboard-studio some/board.perf  # ...or open a document
python -m perfboard_studio.ui.main --headless tools/diffcheck/golden/dense.perf
python -m perfboard_studio.mcp    # the MCP server (docs/MCP.md)
```

The suite is ~2000 tests in under a minute, so run all of it; there is no reason to
narrow to one file except while iterating.

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

`--headless` (`ui/headless.py`) renders 2D/3D/PDF and the schematic (SVG + PDF + PNG) into
`headless_out/`, runs DRC + LVS and prints timings with no display. It is the only step
that exercises 2D, 3D and both exports against a real board end to end, and the fastest
way to check that a rendering change did not crash. It inspects a document and never edits
one. What the render LOOKS like is a separate question, answered by
`tests/test_render_golden.py` below.

CI runs the full three-OS matrix on every push. It was Linux-only off `main` while the
repository was private and minutes were metered; standard runners are free on public
repositories, so that restriction is gone. It earned its keep immediately — the first
full matrix found a VTK abort on Windows and two footprint goldens off by one ULP on
macOS arm64, neither of which Linux can see.

**A test that renders through VTK must carry `@requires_offscreen_gl`** (`tests/test_gl.py`).
Without a GL context VTK does not raise, it aborts the process, so an unmarked test does
not fail — it ends the run partway through with no summary. `test_every_vtk_touching_test_is_marked`
finds them by reading the sources, because marking them by hand missed two.

**What the guide SAYS is checked by `tests/test_guide_golden.py`**, which stores all four
exports of the routed NE555 fixture whole in `tests/guide_golden/` and compares them whole.
The targeted assertions in `test_guide.py` can only catch what somebody thought to name;
a phase that swapped places or a checkpoint that stopped being generated is exactly what
nobody names. Re-bless with `PERFBOARD_STUDIO_BLESS_GUIDE=1` **after reading the diff** — a
readable diff is the point of the test. Not part of the differential proof below: the
TypeScript side never had a guide exporter, so these are our own output, like
`render_signatures.json`, which is why they live under `tests/` and not in
`tools/diffcheck/golden/`. Floats are compared at 12 significant digits because the JSON
emits full-precision lengths through `math.hypot` and macOS arm64's libm disagrees in the
last ULP (`test_footprints.py` learned this the hard way); the other three formats print
to one decimal and are compared as text.

**What the render LOOKS like is checked by `tests/test_render_golden.py`**, not by the
headless PNGs, which nobody opens. It compares the mean colour of each cell of a 6 × 6
grid against `tests/render_signatures.json` — stable across renderers to a fraction of a
level, and 20+ levels away from a board that lost its parts. Re-bless with
`PERFBOARD_STUDIO_BLESS_RENDER=1` after looking at the render. The first attempt measured ink
coverage instead and was nearly useless (a perfboard is mostly board); that is written
down in the file so nobody tries it again.

**`_run_planner` holds the cyclic collector off, and that is a crash fix rather than an
optimisation.** It is the one place in this application where Python runs on two threads at
once: the placer or the router allocates hard on a `QThread` while the UI thread pumps Qt
in a loop. Python's cyclic collector runs on **whichever thread trips the allocation
threshold**, so it runs on the planner — and it finalises what it finds, including PySide
wrappers whose C++ objects the UI thread is at that instant painting with. The process does
not raise; it dies.

Measured, not feared: forty rounds of "move a part, autoroute" crashed in about half the
runs, `faulthandler` putting the worker inside a dataclass `__init__` marked
*Garbage-collecting* and the main thread inside `view2d`'s `paint`. The same forty with the
collector off finished clean, four times over. It had nothing to do with the 3D view, the
router, or what was being routed — only with two threads and one collector. Refcounting
still frees everything acyclic; only cycles wait, for the length of one route, and
`gc.collect()` on the way out pays for it once on the only thread there is. Two tests pin
it, including the failure path — a collector left disabled would be a memory leak traded
for a crash.

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

## Architecture

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

**Two recorded divergences, both in `test_drc.py`, neither one a hole in the proof.** The
fixtures prove the port reproduces the original; that cannot also mean the port may never
improve on it. Each is named, excluded from the comparison rather than edited into an
`.expected.json` (those are dumps from the TypeScript engine, and hand-editing one makes
the next regeneration silently disagree), and pinned by its own test:

- `PYTHON_ONLY_RULES` — rules the original never had (`conductor-crossing`,
  `jumper-under-body`, `conductor-off-board`, `unknown-footprint`,
  `component-overhangs-edge`, `wire-too-thick-for-hole`), so there is nothing for a
  fixture to record.
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

`persist.py` hand-rolls its JSON writer to match `JSON.stringify(x, null, 2)` byte for
byte (whole-number floats print as `1`, not `1.0`), and every object's key order comes
from an explicit `*_KEY_ORDER` tuple, never dict insertion order.

### A body past the edge is measured on the body

`component-off-board` asks about PIN holes; `component-overhangs-edge` asks whether the
BODY stands past the substrate while every pin is in a hole — a TO-220 on row 1. Three
choices carry it, and each is where the first attempt would go wrong:

- **The body, not the courtyard.** The courtyard is padded by half a pitch, so by that
  measure every resistor on the outermost row reaches a full millimetre past the board. The
  body is `footprints.body_extent` — the rectangle `ui/bodies.placement_for` draws, moved
  into the engine so the rule could read it, and read back by the renderers rather than
  worked out twice. A rectangle is exact here even for a round can: a part turns only by
  quarters, and a circle touches its box on all four sides.
- **The substrate, not the grid.** `geometry.substrate_edges_mm`, border included — the
  `board_size_mm` / `hole_span_mm` trap above. It is also the one derivation of the far edge,
  because `-margin + width` and `(n - 1) * pitch + margin` can differ in the last place.
- **A tolerance of 0.25 mm, measured.** A DO-41 on the edge row reaches 0.08 mm past the
  board and a 3 mm LED 0.23 mm; every part that genuinely hangs over clears 0.25 by a
  margin. `geometry.hangs_over_edge` is the only place it is compared.

**It is a WARNING and the placer prices it; `is_legal` does not include it.** Legal means
"breaks no DRC error", which is `strip_conflicts`' position too. `placer.overhang_terms`
reads the same body, edges and verdict as the rule, and
`test_the_placer_and_drc_agree_on_every_body_at_every_edge` holds the two to one count over
all 61 footprints, every rotation, mirrored and not. Both halves of the placer term are zero
inside the tolerance and added only when they are not, which is why no golden placement
moved.

### Two version numbers

`version.py` holds the application version — the single source, read by `pyproject.toml`,
the window title and `--version`. `model.DOCUMENT_FORMAT_VERSION` tracks the `.perf`
format and is bumped **only when an older file needs migrating in order to load**, with
the migration written into `MIGRATIONS` in the same commit. It is at 1 and has never
moved. `tests/test_version.py` fails if `version.py` and `CHANGELOG.md` disagree in
either direction, so a version cannot be bumped without a changelog entry. Ritual in
`docs/RELEASING.md`.

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

### Footprints are generated, not shipped

`footprints.py` computes all 61 footprints from a handful of numeric parameters — zero
assets, and it is still the whole answer for what a part IS. The same `BodySpec` that a
footprint carries is what `ui/bodies.py` extrudes in 3D, so the 2D footprint and the 3D
body cannot disagree. **PLAN.md D6 moved for the 3D SHAPE only** — see "Packages borrowed
from KiCad" below — and the generated body is still the fallback for every part.

Three conventions here are load-bearing:

- **The anchor is pin 1, at grid offset `(0, 0)`** — for two-lead, inline (TO-92,
  TO-220, headers) and DIP packages alike. It is a real physical pin in every case, never
  a geometric centre. This is the convention the heat-proximity rule above works around.
- **`body_outline` is the COURTYARD, not the body.** It is padded by
  `COURTYARD_MARGIN_MM` (half a grid step) so its bounding box contains every pin plus
  clearance, which is what overlap DRC needs. For `r-axial-3` it spans 10.16 mm while the
  resistor body is 5 mm long. Drawing the outline as the part draws a box half again too
  big — the specific mistake that made both renderers look wrong. The real body comes
  from `BodySpec.dims` via `bodies.placement_for`.
  - **53 of the 61 outlines are rectangles and 8 are 24-gons** (`_circle_outline`: the
    electrolytics and the LEDs), and rule 1 turns on that split. A part rotates only by a
    multiple of 90°, so a rectangle never leaves the axes and its bounding box *is* its
    courtyard — `drc._courtyards_overlap` keeps the box test for those on purpose (the
    exact test's projections scale by an edge length, which can collapse a one-ULP
    overlap the placer relies on) and reaches the exact convex test only for a circle.
    `placer.pair_terms` takes the same two paths from the same predicate; the two must
    never disagree about whether parts are in each other's way.
- **Pin offsets are integer steps on `STANDARD_PITCH_MM`** regardless of the board's own
  pitch; `body_outline` and `body_height` are always millimetres.

The file is a line-for-line port whose acceptance criterion is bit-for-bit reproduction
of `tools/diffcheck/golden/footprints.expected.json`, down to the last IEEE-754 double.
Preserve the original's arithmetic and generation order, not merely its intent.
`BodySpec.dims` keys stay camelCase (`"rowSpacing"`, `"tabHeight"`) because `dims` is a
free-form dict, not a model field — there is nothing there for `persist.py` to rename.

**A part the library does not have is asked for by an id that carries its parameters.**
Sixty-one is a good library and not every part anybody owns, and the answer is neither a
document field nor a user library on disk: `box-4x2-p1-r3-15x10x8` IS the definition, and
`generated_footprint` builds it on demand. `get_footprint` resolves the registry first and
the grammar second, so a generated id can never shadow a library part. The `.perf` format
does not move, the 15 golden fixtures are untouched, and a board mailed to a stranger opens
with the same part on it. `GENERATED_ID_GRAMMAR` is the single description of the grammar —
`docs/MCP.md`, the MCP refusal message and `tests/test_footprints.py` all read that one
string, and `ui/main.CustomPartDialog` never spells an id at all: it calls the generator and
shows what came back.

Three things hold it together:

- **One spelling per part, enforced structurally.** Every parse ends by rebuilding the id
  and refusing anything that does not come back identical, so `dip-08` is not a footprint.
  Without it a document could hold a part whose own `id` disagrees with the name it is
  stored under.
- **The id a generator writes for itself must reproduce it.** That is why the auto-ids for
  the electrolytic, disc and film capacitors gained their missing dimension: an auto-id
  that dropped the can height meant two different parts could be given one id, which
  `_build_standard_footprints` would have refused as a duplicate.
- **`generic_box_footprint` is not a shape editor**, and the reason is the format rather
  than the effort: an arbitrary outline would be state, state would be a document field,
  and a document field reopens the byte-for-byte format. (The sheet's own geometry pays
  that price deliberately and in one place — see "Two kinds of sheet" — which is exactly
  why a second field, for a shape nobody asked for, is not worth it.) A pin grid and three millimetre
  dimensions is what fits in an id. Its pins are numbered ROW BY ROW, which is a module's
  silkscreen convention and not a DIP's — `dip_footprint` is for when the answer is the
  other one.
  - **The body may sit OFF its pins' centre** (`-o<X>x<Y>`, mm, signed, `offsetX`/`offsetY`
    in `dims` only when not zero). That is a module with its header along one edge, and it
    is still a number in an id, not a shape. `footprints.body_extent` adds it to the pin
    centroid -- the ONE place, so DRC, the placer and both views move together -- and
    `_offset_rect_outline` makes the courtyard the union of the pins and the shifted body.
    With a zero offset that helper IS `_rect_outline`, float for float; keep it that way or
    every existing `box-` courtyard moves in the last place.
- **`idc-2x<n>` is the box header**, archetype `box-header`: numbered as `hdr-2xN` (odd pins
  row 0), shroud from Wurth WR-BHD, key slot in the wall on the pin-1 row (local -y). It is
  generated rather than registered on purpose -- the registry's 61 are frozen in a golden --
  and a new archetype rather than a `pin-header` variant because the key is the whole point
  and every archetype table (symbol, phase, style, silhouette, icon, 2D mark, 3D builder,
  edge-seeking) then has to say what it does with one; the completeness tests enforce that.
  The 3D builder finds the keyed wall from the direction pin 2 -> pin 1, not from a local
  axis, so it cannot disagree with the pins however the part is turned.

### Hole addressing

`HoleCoord(col, row)` is 0-indexed from the top-left, row growing downward.
`HoleRef` ("A1", "AC12", bijective base-26) is the language every user-facing message
speaks — the guide, DRC, the router's explanations, the MCP tools. `geometry.py` owns the
conversion:

- `coord_to_hole_ref` is strict and round-trips with `hole_ref_to_coord`.
- `format_hole` never raises — use it in any message, since off-board coordinates are
  negative by definition and that is exactly what the failing checker needs to print.

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

### Three rules only the third dimension can see

`component-too-tall`, `jumper-under-body` and `heat-proximity` are why the 3D view is a
checking tool and not a picture (PLAN.md §8.4). Each of them has a second consumer that
must not be allowed to disagree with it:

- **`heat-proximity` and the placer** read one set of facts —
  `model.HEAT_SOURCE_ARCHETYPES` / `HEAT_SENSITIVE_ARCHETYPES` / `HEAT_CLEARANCE_MM` —
  and both measure between **body-box centres**, never anchors. An anchor is pin 1,
  which on a TO-220 is one end of the tab: rotating the part moves the body and not the
  anchor. Two numbers here would mean the optimiser separating parts to a standard DRC
  declines to confirm. `EDGE_SEEKING_ARCHETYPES` stays in `placer.py` on purpose — it is
  a placement preference, not a fact any rule checks.
- **`jumper-under-body` and the router** both ask `occupancy.body_covers`. The router
  refuses to lay such a jumper at all, so DRC deliberately checks *less*: only holes
  strictly between the jumper's ends, because a body's bounding box covers its own pin
  holes and counting the ends would flag every jumper that lands on a part. DRC must
  never object to copper the router was willing to lay.
- **`jumper-under-body` and the build guide.** A flagged jumper moves from phase 7 to
  phase 1, because by phase 7 the part standing over it is already soldered down. The
  phase and the part-step note both come from `guide.trapped_jumper_ids`, so the order
  and the note cannot drift.

`doc.height_limit_mm` is `None` until someone says otherwise, and `component-too-tall` is
silent until then — with no case chosen there is nothing to be too tall for.

### Placement is arranged first and annealed second

`placer.arrange` builds a placement out of the NETLIST before the annealer ever runs, and
half the restarts start from it (`PlacementOptions.seed_from_arrangement`). Annealing
improves an arrangement; it does not invent one, and every restart starting from the
document's own layout meant the search only ever sampled basins around wherever the parts
already were. Three rules carry it:

- **Parts are ordered by connectivity** — the best-connected first, then whichever unplaced
  part is most tied to those already down — and **ground and power nets reaching three or
  more parts are left out of that graph**. Same call `schematic.py` makes drawing them as
  rail glyphs: a rail touching everything makes everything adjacent, and the ordering
  degenerates back to the alphabet it exists to escape.
- **Connectors take the edge before anything else can have the room**, alternating sides,
  turned so their pins run along the edge rather than into the board.
- **Everything else packs into lanes**, one hole of board between parts and a clear row
  between lanes. `ARRANGEMENT_GAP` is 1 and not 0 because a courtyard is padded by half a
  pitch: parts in touching hole cells have courtyards meeting *exactly*, and the overlap
  predicate compares floats.

`ArrangeRequest.mirrored` is not decoration — a part on the solder side has reflected pins,
and the first cut of this ignored it and laid a mirrored DIP-8 a column off the board.

**Two cost terms answer to two consumers each, the same shape as `heat-proximity`.** The
`edge` term measures from a part's COURTYARD to the outer edge of the SUBSTRATE
(`board_edge_margin_mm`, so a printed border counts as board in the way) — never from the
anchor, which is pin 1 and moves to the far end of a header when it turns. The `lanes` term
counts the distinct rows, or columns, that parts *start* on, keyed on the pins rather than
the anchor for the same reason, and is maintained incrementally on `_State` beside the
collision and strip-conflict counters because it is global in a third way: moving the last
part off a row deletes a lane every other part was sharing.

Its weight is set from a measurement rather than from taste — most of the tidiness is free
(1030.2 → 1030.9 of routed cost for 6.20 → 4.57 lanes over ten fixtures and three seeds),
and past ~1.5 the term starts buying alignment with wire.

**`_build_cost` strips the board's copper before scoring, and that is the whole meaning of
the comparison.** Every arrangement is asked one question — what would it cost to BUILD
this — and it is only an answer if all of them are asked it from the same starting board.
They were not: the baseline is the user's own document, whose copper still fits its own
parts, so the router found nothing left to do and returned almost nothing, while every
candidate has moved those parts, so its copper is stale and the router priced the whole
board again. On `atmega328-relay` with one part shoved into a corner the baseline scored
119 against 936–959 for four arrangements that beat it on every other measure. **Autoplace
could therefore never move anything on a board that had been routed** — which is every
board anybody would think to ask about. Pinned by
`test_what_a_placement_costs_to_build_ignores_the_copper_already_on_it`.

**An unchanged placement says what it compared.** `PlacementPlan.route_runner_up` carries
what the best REJECTED arrangement would have cost, for one reason: ten seconds of work
reported as "Placement unchanged" is indistinguishable from a broken button, and the same
ten seconds reported as "nothing found would be cheaper to build than the board you have
(796 against 845)" is an answer somebody can disagree with by asking for another
arrangement.

**Doing nothing is a candidate in `_pick_best`.** A constructive placement is not descended
from the user's board, so nothing else would stop it winning the routing comparison while
still being worse than leaving the board alone.

`placer.suggest_boards` answers which stock board a circuit needs by ARRANGING it on each
`geometry.STANDARD_PRESETS` size, not by summing footprint areas: a design is limited by its
biggest part and the lanes it packs into. `ARRANGEMENT_FILL_LIMIT` is what separates "fits"
from "fits with room to wire it", and `recommended_board` falls back to the smallest board
that merely fits, because "no board suits this" is not an answer anybody can act on.

### A pad is not always round, and the board may say where it is

`board.pad_shape` can be `oblong`, which gives a pad **two different neighbour gaps** —
tight along its long axis, comfortable across it. That is not decoration: R5'
(`solder-trace-proximity`, the most valuable rule in `drc.py`) is entirely about that gap,
so it is measured per pair by `geometry.copper_gap_mm`, which also accounts for a pad
widened into an edge-connector finger. Never reintroduce a single board-wide
`pitch - pad_diameter`.

**R5' fires on a run beside a PIN, once per physical pair** — not on a run beside another
run, and not once per conductor that can see the gap. Both gaps are the same 0.6 mm; the
difference is attention. A run beside a run is one you are laying yourself, on the face you
are looking at, in the same phase, and parallel returns are how dense perfboard is built —
the NE555 routed solder-first produced **51 findings on a board the tool had just routed**,
30 of them runs beside runs and 20 of them the same gap named from both ends. A run passing
a pin is a pad from a part soldered three phases ago with a lead for solder to wick up. The
router still prices the proximity, so it steers around it; it just no longer argues with
the style it was told to use.

`board.labels` is the `A`..`Z` / `01`..`22` legend printed on the board itself. It is the
same address space `coord_to_hole_ref` produces; `printed_row_label` only adds zero
padding for *rendering*, and `hole_ref_to_coord` still rejects `A07`. Silkscreen is
physical, so it scales with the board (`scenetext.draw_physical_label`) — the exact
opposite of the rulers and reference labels, which hold a screen size (`draw_label`).
Both exist because a millimetre-sized font is a fraction of a point, which some engines
draw as nothing while reporting no error.

`mounting_holes` and `edge_connectors` sit on the *document* (like `cuts`), so each is its
own command and its own undo step. A mounting bore removes copper from pads it was not
drilled on — `geometry.consumed_holes` is the single answer to which — and a pin left on
one is a DRC *error* about physical impossibility rather than likely failure.

**`geometry.unusable_holes` is that fact plus the fingers, and it has THREE consumers.** A
bore has taken the pad, or a finger is solid copper with no bore at all
(`undrilled_holes`); either way nothing can be soldered there. `drc.py` reports a pin or a
run on one, `placer.py` prices it beside a collision and refuses to call such a placement
legal, and `router.py` treats it as a wall and refuses an endpoint on one. All three used
to disagree: the planners produced boards the checker called errors, which surfaced the
moment the shipped examples moved onto the boards suppliers actually sell — a 6 × 8 cm
board has a finger strip down two edges, and a board edge is exactly where the placer's
`edge` term is pulling the connectors. A CUT is deliberately not in the set: a cut destroys
the copper and leaves the hole, so a lead still fits and what it is soldered to is nothing,
which is `cut-track-conflict` and a different question.

Three things here were got wrong first and corrected against photographs of real boards;
they are easy to get wrong the same way again:

- **Oblong pads on a real board are only the edge strip**, not the whole grid. The
  interior is round. "Oblong pad" and "edge-connector pad" are the same physical thing,
  which is why a finger replaces the grid pad rather than covering it —
  `geometry.holes_without_grid_pad` answers that for both faces.
- **Fingers stop short of the edge** (`inset_mm`); the strip outside them is where the
  row numbers are printed. `legend_strip_mm` asks the *document*, not the board, for that
  reason.
- **Corner mounting holes sit in the border** via `offset_x_mm` / `offset_y_mm`, eating
  no pads. Always go through `mounting_hole_centre_mm`, never `hole_to_mm(mount.at)`.

`board.single_sided` is the cheap phenolic board: copper on the solder side only. Both
renderers still draw the holes on the bare face — a face with neither holes nor pads is a
blank slab.

**In 3D the board is PUNCHED, not painted.** A face is one tile — a pitch square with its
hole taken out (`view3d._tile_with_hole`) — glyphed at every hole, so both faces of a
945-hole board cost one source and two actors where a boolean subtraction per hole would
be nearly two thousand. Tiles are exactly a pitch across so neighbours share an edge; the
strip left over is the printed border, as rectangles, and a mounting bore is cut out of
whichever of the two it lands in. The tiles a bore takes are exactly the holes
`consumed_holes` reports the copper gone from — one bore, one answer, for the renderer and
for DRC — and its centre comes from `mounting_hole_centre_mm`, never from `mount.at`.
Every lead is drawn through its hole and trimmed just past the far copper
(`view3d._through_hole_pieces`), which is the only evidence the solder side has that
anything came through it.

### Parts are shaded as materials, and the room is generated too

**Phong describes a HIGHLIGHT and says nothing about what a thing is made of.** That was
why the 3D board looked like painted card whatever numbers were tried: thirty call sites
each guessed a specular reflectance and an exponent, and there is no value of those two
that makes aluminium look like aluminium — what separates a crystal can from a DIP is that
one is a conductor and reflects the room in its own colour and the other scatters.
`view3d._finish` is now the single place a property is set, and it says it in two numbers
a person can check against a part in their hand: `metallic`, which is 0 or 1 and never
between, and `roughness`, which is the whole difference between moulded epoxy and glossy
nylon, or between a solder fillet and the tinned wire running into it. The materials
actually on a perfboard are named once at the top of the file; a builder names one rather
than inventing numbers, which is what stops a solder run and the bead at its end being
given two finishes and drawing a seam that is not there.

`bodies.Surface` carries the pair for the archetype-level answer, beside the Phong numbers
the 2D view still uses for its gradient — one table, two renderers, as before.

Four things here were got wrong first, and each has a test:

- **A colour reaches the shader as ALBEDO, not as sRGB.** `BODY_STYLES` is picked as hex,
  which is sRGB; a physical shader multiplies the fraction of light a surface returns, and
  the two differ by a gamma curve. A DIP's `#24262d` is 0.14 one way and 0.017 the other,
  so handing over the first number renders black epoxy as mid grey — every part on the
  board washed out together, which reads as "the lighting is wrong" rather than "the
  colours are wrong". `_finish` converts, which is why it must be called AFTER `SetColor`.
- **A PBR material with nothing to reflect is a flat colour.** Metallic and roughness
  describe how a surface answers its SURROUNDINGS, and two lamps in the void are not
  surroundings — a tinned can under them comes back darker than it was under Phong,
  because a mirror pointed at nothing is black. `apply_environment` gives every surface a
  whole room, and **the room is BUILT, not downloaded**: PLAN.md D6 applied to lighting
  rather than to geometry. Six small float faces of gradient plus one bright rectangle
  overhead, which is the only room this view is ever set in. The rectangle is the part that
  matters — a cylinder under a point light has a round dot on it and a cylinder under a
  softbox has a long streak, and the streak is what the eye reads as a photograph. Values
  run past 1.0 because the lamp has to be brighter than the room or a smooth surface has
  nothing to pick out.
- **`SetColorModeToDirectScalars` is the one call without which this is a rainbow.** A
  `vtkTexture` maps scalars through a lookup table by default and VTK's default table is
  the jet colormap, so the room came back as a spectrum and every metal part reflected it.
  And `SetEnvironmentUp` is the one that is easy to leave out and hard to see the absence
  of: VTK's environment frame is Y-up and this world is Z-up, so without it the lamp sits
  off to one side and everything is lit from the wrong place — consistently, which makes it
  look odd rather than broken.
- **Both of these can be turned off, and only these.** `PERFBOARD_STUDIO_SIMPLE_3D=1`
  makes `apply_environment` and `apply_contact_shadows` do nothing. They are the only
  things in this view that ask a driver for anything unusual — a float cube map with a
  prefiltered mip chain, and a second render pass with its own framebuffers — and VTK does
  not raise when a driver cannot do something, it ends the process, which is the whole
  reason `offscreen_gl_available` spends its crash in a child. What is lost is the room and
  the shadows; every material and every borrowed package stays, which is still a great deal
  more than the flat shading this replaced. Read from the environment on every call rather
  than cached, because a variable somebody can set and restart with is the only tool they
  have against a crash that happens before anything is logged.
- **Contact shadows are what make a part sit on the board.** Every solid is lit as though
  nothing else were in the scene, so a DIP and the board under it were two objects at the
  same brightness meeting at a line. `apply_contact_shadows` is one SSAO pass and its
  radius is in millimetres; it RETURNS whether it took, because it is the one piece of the
  render that is a luxury and a machine whose OpenGL is too old should get a flatter board
  rather than no board.

**Image-based lighting costs nothing per frame and a great deal per RENDERER.** Before a
renderer's first frame VTK fills an irradiance map, a prefiltered map and a BRDF table, at
defaults sized for photographed HDR environments. On a GPU that is milliseconds; on a
software renderer it was the whole of the 3D cost — the macOS CI runner (Apple Software
Renderer) spent 78 s of a 102 s first frame on the BRDF table alone, and its CI job went
from 3 minutes to two hours when the lighting landed. `_IRRADIANCE_PX` and `_BRDF_TABLE_PX`
size the two that were measured to matter, and the step images come from ONE renderer with
two cameras rather than a window per face. So: never build a renderer per image, and
measure a new lighting feature on software GL before trusting a GPU's timing. Mesa's
`opengl32.dll` from `pal1000/mesa-dist-win` loaded through `os.add_dll_directory`, with
`GALLIUM_DRIVER=llvmpipe`, is software GL on Windows — though llvmpipe vectorises arithmetic
that Apple's renderer does not, so it UNDER-reports exactly the table that cost the most.

`_dim` and `_pick_out` are a pair, and under PBR the way to push a part back is to ROUGHEN
it — dropping the old specular did nothing at all once the parts were materials.

**A moulded case has no knife edges, and `_moulded_box` is why a DIP stopped reading as a
black rectangle.** A `vtkCubeSource` meets its neighbours at a knife edge, and a knife edge
takes exactly one shade — this face flat, the next face flat, a line between them. An eye
finds an object's edge in the highlight running along it, and there was nowhere for one to
sit. Sixteen vertices fix it. Only the HORIZONTAL edges are cut: from anywhere this view is
looked at the top edge is the one seen against the board, and cutting the four vertical
corners as well doubles the geometry to change a silhouette nobody is looking at. The
feature angle on the normals keeps the chamfer a crease rather than smearing it into the
faces either side, which is the other way to get this wrong — a DIP that looks inflated.

**There is deliberately no golden IMAGE for the 3D view**, unlike `test_render_golden.py`'s
2D one: VTK draws through whatever OpenGL the machine has, and a mean-colour comparison
across the three-OS matrix would fail for reasons nobody can act on. What is held still
instead is every decision above, including "no actor is left on Phong" — a scene with both
models in it lights its two halves by different rules, and the leftover half reads as a
sticker stuck onto the picture.

### Packages borrowed from KiCad, and what was NOT borrowed

**PLAN.md D6 chose parametric generation and gave three reasons: zero assets, a body that
cannot disagree with its own footprint, and no share-alike licence inherited into an
Apache-2.0 project. Two of them are untouched.** The third did not survive looking at the
result — a potentiometer generated from a diameter and a height is a disc with a peg on it,
a relay is a box, a screw terminal is a block with no screws in it. `ui/partmodels.py` reads
meshes of the real packages, converted from KiCad's `packages3D` library by
`tools/import_kicad_models.py`.

What keeps everything D6 was protecting:

- **The generated body is still the fallback, for every part.** A footprint nobody mapped, a
  part asked for by a generated id, a build that shipped without the meshes — all of them
  draw exactly as they did. `test_a_board_still_renders_with_no_models_at_all` is the pin.
- **Only the shape ABOVE the board is borrowed.** The converter cuts every model at the
  board surface and this application draws the leads, because it knows the board's
  thickness, where the copper is and how far past it a trimmed lead stands. A model's own
  legs are drawn untrimmed for a 1.6 mm board and would hang out of the solder side.
- **The body keeps OUR colour.** `bodies.BODY_STYLES` is one table for the 2D view, the 3D
  view and the guide's step images; a red LED coming out a different red in two of the three
  would be giving that up for a borrowed mesh. The converter marks the biggest non-metal
  piece as the body and it is painted from our table. Leads, tabs, bands and the gold on a
  header pin keep the colour they were drawn with, because our table has no opinion there.
- **Materials are ours**, so a borrowed mesh answers light by the same rules as a generated
  one. The index names one of `view3d.MODEL_MATERIALS`; a name the renderer does not have is
  caught by a test rather than shaded as plastic in silence.
- **What is printed is still ours.** A KiCad resistor is a bare barrel — the library has no
  way to know what value a part is and this application does — so `_axial_markings` prints
  the colour code and the cathode band on the borrowed body. It takes the BARREL's own
  radius and length from the mesh, because a footprint describes a package family and a
  model is one part in it: printing at the footprint's size puts the bands inside the body,
  where they simply vanish.

Three things about the mapping:

- **A model is only named when it IS the package the footprint describes.** The converter
  prints the courtyard against the model's own size for every entry, and where nothing
  matched — the 16 mm potentiometer, the 0.3-inch 40-pin DIP — there is no entry and the
  generated body stands. A model whose leads are 5 mm apart on a footprint whose holes are
  2.54 mm apart is a part standing on nothing.
- **Position is not measured, because it is already right.** A KiCad through-hole model's
  origin is pin 1 and its axes run the way this world does — x with the column, y against
  the row. Both follow the footprint, and this project's convention is written down as "the
  anchor is pin 1, at grid offset (0, 0)". A quarter turn of a component is minus a quarter
  turn about world z: the footprint frame counts rows downward and the world counts them
  up-negative.
- **A header is the one package that is a repetition.** KiCad ships a model per length,
  forty per row count; one pin mesh glyphed at the holes is the same picture for a fortieth
  of the library, and it is what lets a header of a length nobody shipped a model for be
  drawn at all — which matters, because header footprints are generated on demand.

**The meshes are the only part of this repository that is not Apache-2.0.** They are
CC-BY-SA 4.0 with KiCad's design exception, and their `LICENSE` and `NOTICE.md` live in
`src/perfboard_studio/ui/models/` and travel with them. The exception means a board designed
with this tool is unaffected; redistribution means keeping that directory intact. The wheel
declares `Apache-2.0 AND CC-BY-SA-4.0` and `release.yml` checks the meshes and their licence
are actually in it, because a wheel without them still draws every board — which is exactly
why nothing else would notice them going missing.

### The guide's order is physical, and its checks are derived

`guide.py` has nine phases (`PHASE_TITLES`, 0–8) and the order is not editorial: parts go
in **shortest first**, because a tall part fitted early stops the board lying flat on the
bench while the short ones are soldered. `PHASE_BY_ARCHETYPE` is that height ordering
written down; `PHASE_BY_CONDUCTOR` puts the solder side in phase 6 and long insulated
wire in 7. ICs go last (phase 8) — heat and ESD.

Two derivations must not be replaced with conventions:

- **Polarity comes from the registry's pin NAMES** (`'+'`, `'K'`, `'A'`), never from a
  convention about pin 1 — an electrolytic's pin 1 is its positive lead, an LED's is its
  anode, a diode's is its cathode. A rule keyed on pin 1 produces a dead board.
- **Checkpoints come from the same lists that predicted the risk.** Continuity is read
  off the schematic's nets; isolation probes are generated from DRC's `R5'`
  (`solder-trace-proximity`) hits. The risk the tool predicted and the measurement the
  user performs are one list, which is the whole point.

### The design comes before the board, and the sheet is drawn from it

Two halves that must not be confused.

**`doc.parts` is the design.** A `SchematicPart` is a part the document has and the board
does not: ref, value, footprint, and no anchor. It is a SEPARATE list from
`doc.components` rather than a `ComponentInstance` with an optional anchor, and that is
the whole safety of the feature — DRC, occupancy, connectivity, the router, the placer,
the guide, the PDF and both renderers all iterate `doc.components` and are right to assume
every entry has a position. An optional anchor would make sixty-odd sites responsible for
remembering that a part might be nowhere. The cost is one rule instead: **a reference is
unique across BOTH lists** (`commands.assert_ref_free`), because every net node is a
`(ref, pin)` pair.

Placing is a MOVE between the lists (`part.place`), keeping the same id so a replayed
journal still describes one thing; `component.unplace` is the inverse and keeps the
wiring. `part.delete` takes the net nodes with it and `component.delete` does not — off
the board is an LVS open the schematic still asks about, out of the design is not.
`net.connect` never required a part to be on the board (`assert_pins_free` says so in its
docstring), which is what made the whole order of work possible without touching it.

**Renaming carries the wiring**, for a part and a component alike (`rename_in_nets`). It
did not always: R1 wired into six nets and relabelled R7 came out connected to nothing,
and the properties dialog carried a tooltip apologising for it. Refused rather than merged
when the new reference already has those pins wired.

**`schematic.py` derives the sheet and stores nothing.** Symbols, orthogonal wires,
junction dots, rail glyphs, labels — from `doc.parts`, `doc.components` and `doc.nets`,
every time. It is an engine module and obeys the engine's rule, so the layout is reachable
from a test that hands it a document; two sheets are frozen whole in
`tests/schematic_golden/` (`PERFBOARD_STUDIO_BLESS_SCHEMATIC=1`), for the reason
`test_guide_golden` exists.

### Two kinds of sheet, and the document decides which

**The sheet used to be a picture you could look at and not draw**, and the reason given for
that was a line in PLAN.md declining the cost of a schematic editor. The line is gone (see
"Devre girişi" there): what a netlist import brings is a list of CONNECTIONS with no geometry
in it at all, which is why `schematic.py` had to derive a sheet from nothing in the first
place — no drawing was ever arriving from anywhere. And the cost it was guarding against is
bounded by keeping the drawing's geometry OUT of the netlist, which is the whole design
below: nothing downstream of `doc.nets` changed by a line.

So `build_schematic` has two paths, chosen by whether `doc.sheet` is empty:

- **Derived** (`_derived_sheet`): everything above. Symbols in cells, wires only in the
  channels between them, no wire able to cross a symbol as a consequence of where the
  tracks may be. This is what every imported netlist, every fresh document and every press
  of `Arrange` produces, and it is what keeps "open it and look at it" free.
- **Hand-drawn** (`_hand_drawn_sheet`): every symbol where it was put, turned how it was
  turned, joined by the wires somebody drew. Nothing is arranged.

**There is no half-arranged sheet, and there must not be.** A layout that arranged twenty
symbols around the one somebody had placed would move the twenty every time the one moved.
So the first edit FREEZES the sheet: the window sends a `SymbolPlacement` for every symbol,
read off the drawing already on screen, in one `symbol.move` — one command, one undo step,
and nothing jumps (`MainWindow._sheet_placements`). A part added afterwards is PARKED in a
column past the right-hand edge rather than dropped at the origin on top of something.

**What is not joined by a wire is joined by NAME**, with a label at the pin. That is not a
fallback for wires nobody got round to: a reset line reaching six parts drawn as six wires
crosses the whole page, and every schematic ever drawn writes the name at the pin instead.
Here it is not even a convention — the net IS `doc.nets` and the label is printed FROM it,
so two pins carrying one name are the same net because they are. Ground and power keep their
rail glyphs either way, for the reason they always had them.

**A drawn wire carries no net id** (`model.SheetWire`). Which net it belongs to is whichever
net holds both of its ends, looked up every time (`_wire_net_of`). Three things follow, and
all three are the point:

- LVS, the router, the placer, the guide and the board read `doc.nets` and none of them has
  to learn anything about geometry.
- A wire left over from a connection somebody has since removed stops being drawn, instead
  of quietly asserting a join that no longer exists.
- Renaming a net costs nothing here.

Two pins and no more per wire. A net drawn as three wires between four pins reads exactly
like one branching run, and a branch point would need a fourth kind of endpoint — a point on
another wire — that moves whenever either end does.

**A symbol that moves takes its wires with it** (`_reanchored`). Only the two END segments
give: the first point becomes the pin and the point after it slides along whichever axis that
segment ran on, so the chain stays orthogonal and the middle is left exactly as drawn. A
two-point path is the case that bites — `points[0]` and `points[-2]` are the same element, so
the second fixup undoes the first — and it is handled before the loop, as an elbow.

**`_orient_body` is the whole of rotation and mirroring.** Mirror first, then turn, which is
the order `ComponentInstance` uses on the board: two places in this application answer "which
way round is this", and having them disagree would mean a part whose symbol and whose
footprint are flipped differently. Nothing in the transform knows what the symbol IS, which
is the point — a resistor, a relay and a 40-pin box all turn by the same arithmetic — and
`SymbolPin.side` gains `top` and `bottom`, which only a turned symbol ever has.

Four things keep the stored half honest:

- **It is keyed on the part's ID**, so a position survives a rename and survives
  `part.place` / `component.unplace` moving a part between the two lists.
- **All three arrays are omitted from the file when empty** — `sheet`, `sheetWires`,
  `sheetNotes` — the `stripAxis` rule, which is why all fifteen golden fixtures are untouched
  and `DOCUMENT_FORMAT_VERSION` has still never moved. A sheet nobody has drawn on says
  nothing. `rotation` and `mirrored` follow the same rule inside a placement.
- **A `sheet` written while positions were CELLS is dropped with a warning**, not migrated
  and not refused (`persist.OLD_CELL_KEYS`). A cell means nothing without the layout that
  produced it, so there is no sum that converts one; and locking somebody out of a board
  over where a symbol used to sit is not a trade anybody would make.
- **`symbol.auto` is its own command**, not an undo: undo takes back the last move, and
  handing the sheet back after an afternoon of tidying is a great many moves and one
  decision. Handing back the WHOLE sheet takes the drawn wires with it, because a wire was
  drawn between pins that were where somebody put them.

**`sheet.wire` joins the pins AND stores the line, in one command.** Two would mean an undo
that took back the drawing and kept the connection, which is a lie about what just happened.
What joining two pins MEANS is `commands.plan_pin_join`, which `view2d.join_pins` reads too —
one fact, two consumers, the shape this codebase uses everywhere. Two nets are never merged:
that is a change to the circuit rather than to a drawing.

**A note is a person writing on the drawing** (`model.SheetNote`). Nothing derives anything
from one: not DRC, not LVS, and no command refuses one for overlapping anything. A drawing
tool that argued with what was written on it would be worse than one with no notes at all.
It is the one piece of text on the sheet drawn in MILLIMETRES on screen as well as on paper,
because it is a size somebody chose rather than annotation the renderer is sizing.

`schematic.symbol_at`, `pin_at`, `pin_position` and `snap_to_grid` are the engine's answers
to the four questions the panel asks about a point on the sheet, answered from the DRAWING's
own output rather than by re-deriving anything — a second copy of "where is this symbol" is a
second thing to keep in step, which is the rule `cell_at` followed before them.

`Symbol.unplaced` and `Symbol.undefined` are different things and only the second is a
defect: unplaced is every part on a sheet being drawn, so it is counted in the panel's
summary and produces no note; undefined means a net names a part nothing defines, so it is
dashed and reported.

Four decisions carry it, and each has a test that would notice it going:

- **Ground and power are rail glyphs, not wires** (`SchematicOptions.rail_classes`), and
  they are also **kept out of the layering graph**. A GND net touching every part would
  otherwise make every part adjacent to every other and collapse the columns — the same
  hairball the glyphs prevent, arriving by the back door.
- **Symbols live in grid cells and wires only in the channels between them**, so no wire
  can cross a symbol; channels widen to fit whatever a left-edge sweep assigns them.
  `schematic.column_cap` is the single answer to how tall a column should be and it has
  three consumers — a layer too tall is split at it, consecutive layers too thin are folded
  together up to it, and the block of parts no net reaches is packed at it; two of those
  disagreeing would split a column and immediately merge it back. It divides by
  `CELL_ASPECT`, which is not taste: a symbol is wide and short and the horizontal channels
  sit between the ROWS, so a row costs far more height than a column costs width, and a
  square grid of cells draws a sheet taller than it is wide. Rail
  anchors come out of the **same** track pool as the trunks, because a crossing carries no
  dot and reads correctly while a line lying along a ground symbol's bars does not.
  `RAIL_GLYPH_MM`/`RAIL_GLYPH_DEPTH_MM` are the layout's contract with the renderer — one
  fact, two consumers, and both must stay under `TRACK_PITCH_MM` or the guarantee needs
  another allocation pass.
- **A symbol gets its real shape only where something knows what every lead IS**, and the
  question is always whether the fact belongs to the PACKAGE or to the PART. Polarity is
  read from the pin NAMES with pin 1 as the cathode for an unnamed polarised part — the
  same rule as `guide._polarity_note`, and the two must not drift: an LED's pin 1 is its
  anode and a diode's is its cathode.
  - A TO-92 has no E/B/C anywhere in the REGISTRY and a TO-220 no IN/GND/OUT, so both are
    boxes with numbered pins. That is not a gap in the registry: BC547 and 2N3904 share the
    package and disagree about the pinout, and a TO-220 is a regulator, a transistor, a
    MOSFET and a bridge rectifier. The pinout is a fact about the PART, and a symbol that
    asserted one would be wrong for half the parts using the package — silently, and all
    the way to the bench.
  - **So the PART carries it.** `ComponentInstance` and `SchematicPart` both have
    `pin_names` (pin number → name, in pin order, `model.normalized_pin_names`) and
    `symbol` (`model.PartSymbol`: `npn`/`pnp`/`nmos`/`pmos`/`zener`/`fuse`).
    `model.pin_name_of` is THE answer to "what is this pin called" — declared name first,
    footprint name second — and the sheet, the guide's polarity note and the MCP server all
    read it. A declaration is drawn only when `schematic.DECLARED_SYMBOL_PINS` is met
    (exactly B/C/E or G/D/S named; a zener needs a knowable cathode); otherwise the package
    decides and the sheet's notes say why. Commands check only the SHAPE
    (`checked_pin_names`/`checked_part_symbol`): a name on a pin the footprint lacks is a
    note on the sheet, the same finding as a net naming such a pin, not a refusal.
    - **Both fields are omitted from the file at their default** (the `stripAxis` rule),
      which is the only reason every fixture still round-trips. `part.place` and
      `component.unplace` carry them across the two lists; `block.place` (paste) and
      `component.place` take them in the payload. Update payloads use `None` = leave for
      the names and `KEEP` for the symbol, because `None` IS a symbol value.
    - **Only a DECLARED name is added to a probe** ("J1 pin 1 (24V-L)"), never the
      registry's own: appending "(A)" to every LED probe would change every guide golden
      and tell nobody anything the polarity note has not.
    - A named pin on a box prints the NAME inside and the NUMBER on the lead, and the box
      widens to whole grid squares to fit (`_named_body_width`, sized from
      `PIN_LABEL_MM`, which `SheetInk.pin_mm` now reads). A connector's names start past
      its shroud line. A box none of whose pins is named is byte-for-byte what it was.
  - A tactile switch and a relay get real shapes because the fact IS the package.
    `_switch_poles` reads four legs in two bonded pairs off the footprint's own geometry
    (the legs on one side of a 6 mm switch are bonded inside it, on every one ever made),
    and `_relay_sides` reads the winding off the COUNT — two pins along one side. Both
    helpers return `None` rather than guessing, and `symbol_kind_for` falls back to a box
    when they do.
  - **The relay stops exactly where the package stops.** Which contact is COM is not a
    package fact — Songle and Omron disagree on the same outline — so the contacts are
    numbered leads out of a block rather than a blade resting on one of them, and the
    numbers are printed (`show_pin_numbers` includes `relay`) or the refusal is not honest.
    A sheet that named the wrong pin builds a board normally-closed that was meant to be
    normally-open, and it looks right the whole way.
  - The one assumption the registry does not back is written at `_potentiometer_body`.
- **Everything is deterministic.** BFS layering, barycentre sweeps and track packing each
  have ties, and every one is broken by reference or net id — otherwise the goldens are
  unblessable and the sheet rearranges itself between runs.

**The sheet leaves as SVG, and the PDF and the PNG are made out of that SVG.**
`schematic_export.py` is the only thing that turns a `SchematicDrawing` into a picture for
paper — an engine module, so a whole exported sheet is frozen in `tests/schematic_golden/`
beside the text dumps and blessed by the same `PERFBOARD_STUDIO_BLESS_SCHEMATIC=1`.
`ui/export_schematic.py` renders nothing: it hands that string to Qt to paginate or
rasterise. Three writers over one drawing would be three chances for the printed sheet, the
emailed PNG and the embedded SVG to disagree about what the circuit is.

Three things there are load-bearing:

- **It is NOT a second copy of the panel, and the two differences are measurable.** Screen
  labels hold a PIXEL size (`ui/scenetext.py` argues it at length); paper labels are
  millimetres of sheet, the same split `export_pdf` already makes. And the panel is light
  ink on a dark sheet, which is right at midnight and wrong on every printer, so the export
  defaults to black on white — monochrome, because the rail glyphs already say which rail
  sinks and which sources and a photocopier keeps shapes and not colours. What the two must
  NOT decide separately is geometry: the glyph's bars come from `schematic.rail_glyph_bars`,
  which both call.
- **Qt's SVG support is SVG Tiny 1.2**, so `dominant-baseline` does not exist there — and Qt
  is what produces the PDF. The writer computes text baselines itself for that reason; an
  attribute nothing implements is ignored rather than refused, and every reference lands on
  top of its own symbol on paper while the browser preview looks perfect.
- **`svg_to_image` asks for `Format_ARGB32` on purpose.** Text painted onto `Format_RGB32`
  on Windows gets ClearType — subpixel antialiasing, which draws black text as orange and
  blue pixels because it exploits one monitor's stripe order. In a *file* that is wrong
  data: it survives the print and the resize. An alpha channel forces greyscale
  antialiasing. `test_an_exported_png_has_no_subpixel_colour_fringes` is the measurement,
  because nothing in the code says "no ClearType".

`--headless` writes the sheet too. It is the only place the writer, Qt's SVG renderer and a
real board meet on all three operating systems, and the only export that needs no GL.

### The window is panels all the way down

**The board is a dock widget and so is the schematic**, exactly like the 3D view and the
build guide. Everything else in the window could be moved, floated, stacked or closed; the
two views this application exists for were the one pair nailed down — a central widget with
a `QTabWidget` beside it — so "board left, sheet right" was not something a user could ask
for, and wanting both at once meant a second top-level window (`_DetachedSheet`) built by a
button and handed back on close. All of that is what a `QDockWidget` already is, and none
of it could be undone by dragging.

Six things follow, and each has a test:

- **The central widget is capped to nothing** (`_sync_central_hint`, `UNCAPPED`). QMainWindow
  surrounds a central widget with dock areas, so for the panels to have the whole window
  there must be nothing in the middle; a maximum of `(0, 0)` is the only way to say that.
  The cap comes off when every view panel is shut, and what shows then is the one screen in
  this application that would otherwise say nothing at all.
- **Every split comes before every tabify** in `_arrange_docks`. Qt's `splitDockWidget`,
  handed a dock that is already in a tab group, adds the second one to that GROUP instead of
  splitting — so the DRC panel asked for underneath the board arrived as a third tab behind
  it: present, checked and invisible.
- **DRC opens under the board, not across the bottom of the window.** A window with no
  central widget hands every leftover pixel of HEIGHT to the bottom dock area, and no
  `resizeDocks`, size hint or size policy takes it back: a findings list with four rows in
  it opened 556 px tall and squeezed the board into 302.
- **`_apply_default_sizes` caps and lets go**, from `showEvent` and through two turns of the
  event loop, because `resizeDocks` does nothing useful here — it divides the room the
  window HAS, and a window that is not on screen yet has none. A maximum is honoured at any
  moment; the splitters move to it; and the arrangement is photographed with `saveState`
  and put back afterwards, because a dock that is the only thing in its area springs
  straight back when the cap comes off.
- **A tabbed panel drops its own title bar** (`_sync_dock_titlebars`). Qt draws both the tab
  bar for the group and the current dock's title under it — the same word twice, on two
  rows, above a view that wanted the height. Dragging the tab moves the panel and the
  toolbar button closes it, so nothing is lost; the title bar comes back the moment the
  panel is pulled out beside another and is the only handle it has.
- **`WINDOW_STATE_VERSION` is bumped when a dock is added or removed.** `restoreState` puts
  back the docks it knows and leaves the ones it has never heard of wherever the constructor
  put them, which landed the board and the sheet off the side of the window for anybody with
  a saved layout. Refusing the old state costs one person one rearranged window, once.

**`schematic_is_showing` needs `_raised_dock`, which a tab widget answered for free.** The
panel fills itself only while it is in front of somebody, the same rule the 3D panel and the
build guide follow — and a dock stacked BEHIND another is not `isHidden`, so that test alone
would have the sheet rebuilding itself behind the board. Measuring it (`visibleRegion`) is
not an option either: it reads "behind" for every panel in a window nobody has shown, which
is every window in the test suite. So `_on_view_dock_visibility` records what Qt says came
forward, and that is the answer.

The update strip is a dock too, in the top area, with no title bar and no features
(`_build_update_strip`). It was a band inside the central widget, which is where the board
used to be. It is **not** a `QToolBar`, which was the first attempt and is worth writing
down: a toolbar lays its own widgets out, and one with no geometry yet — a window that has
not been shown, which is every window in the test suite — decides the strip does not fit and
HIDES it, in the middle of the call that was putting it up. `UpdateBar.visibilityChanged`
exists for the strip to follow, and it is emitted from `setVisible` rather than `showEvent`
because Qt sends no show event to a widget whose parent is hidden.

**The schematic panel's tools are a `QToolBar`, and that is a layout fix.** Nine push buttons
in a row gave the panel a minimum width of 1362 px — a panel inherits its minimum from
whatever is in it — so the window could not be made narrower than the row and nothing in the
layout could be resized at all.

**The panel is a tool group, and select is IN it.** `viewsch.SheetTool` is one of
select / wire / label / text / line / rectangle / circle, exactly one armed, `Escape` always
back to the pointer — an editor whose "no tool" state is unreachable is an editor you get
stuck in. **Panning moved to the middle button in every tool**, and that is what makes tools
possible at all: it used to be a left drag on empty sheet, so arming the wire tool had to
turn panning off, and with more than two tools that trade stops working — a rubber band, a
rectangle and a wire all want the left button on empty sheet.

**Nothing is committed until the button comes up.** The dragged symbols, the wire following
the pointer and the shape being pulled out are all painted by `SheetItem._ghost` as pictures
of an edit that has not happened, which is what lets Escape and a drag off the sheet both
mean "never mind" without a command having to be undone.

`viewsch` paints the grid in `drawBackground` at `schematic.GRID_MM`, not as items: a line
per square on a 460 mm sheet is nine thousand things to hold, transform and hit-test for
something nothing will ever click. The minor grid gives up before the major one does, so
zooming out reads instead of greying over.

**ONE GESTURE, TWO DESTINATIONS, decided by where the pointer goes.** Dragging a symbol
inside the sheet moves it; the moment the pointer leaves the panel the in-sheet move becomes
a Qt drag (`_start_board_drag`), which is what lands it on a hole when it is dropped on the
board. Anything else would mean two ways to pick a symbol up. `view2d.PART_MIME` is the
format the drag carries, the board is the drop target (`BoardView.partDropped`), and the
WINDOW decides which command it is — `part.place` for a part in the design, `component.move` for one already down, the same
split `on_schematic_remove` makes. The constant lives in `view2d` because that is the side
that receives it and already owns the vocabulary a drop lands in (`screen_to_hole`), and
because the import goes the way that does not make a cycle. With the two views as panels
a drag can simply cross from one to the other when they sit side by side; stacked, the dock
area's tab bar is the thing to drag over.

**A right-click on the sheet edits the CIRCUIT, because the drawing has nothing to edit.**
`MainWindow.sheet_menu` builds one of three menus from what is under the pointer — a symbol
is a part, a wire is a net, bare sheet is the sheet — and returns it rather than showing it,
so a test can read what a right-click would offer (`exec` in a headless run waits for a
click that never comes). It is the same division `board_menu` draws: the view reports a
position and the window owns the actions.

Three things about it are load-bearing:

- **A pin is asked for before the symbol it is on.** Not merely because it is the smaller
  target: a pin sits ON the edge of its symbol's box with its wire running away from it, so
  a click aimed at one misses the symbol and lands on the WIRE — which would offer to delete
  the net when what was clicked was one pin of it. The pin's entry then sits on TOP of the
  symbol's list rather than in a fourth menu, since a pin is always on a symbol.
- **Every entry is a command that already existed, reached from the thing it is about.**
  Renaming a net meant finding it in a tree of twenty names; here it is the wire you can see
  is wrong. The one exception is taking a single pin off a net, which has no other door on
  the sheet at all and is exactly what you ask for while looking at the pin. `Net Class` is
  not a label either: ground and power are drawn as rail glyphs and kept out of the layering
  graph, so that entry changes the drawing and the placement, not just what DRC says. Its
  three classes come from `NetDialog.NET_CLASSES` — one table, two consumers, pinned by a
  test — and the submenu is built with its parent rather than through `addMenu(title)`,
  which hands back a menu nothing holds and is collected out from under the entry that shows
  it.
- **The menu acts on what it was opened over**, selecting it first the way `board_menu`
  does. Remove reads the panel's own reference, so a menu that left it pointing at the last
  thing clicked would delete something else entirely.

`Duplicate` copies what a part IS and not what it is wired to — the same call
`ui/clipboard.py` makes about a pasted block's net claim — and a duplicate of a placed part
lands in the DESIGN, because the copy has no position and nothing there is entitled to guess
one.

Clicking cross-probes: a symbol selects that part on the board, a wire selects its net in
the Nets dock (which is what already lights it on the board). Routed through that one
panel deliberately, so three views cannot disagree about what is selected. **Joining two
pins is `view2d.join_pins`, shared with the board's connect tool** — the board joins pads
and the sheet joins symbol pins, and the two must not disagree about the three cases that
are not "make a net": one pin already on a rail, both on the same net, both on different
nets (refused, because merging two nets is a decision about the circuit).

### The MCP server is behaviour in one file, protocol in the other

`mcp/session.py` holds every tool's actual behaviour; `mcp/server.py` only binds names,
docstrings and transport. So the tools are tested by calling them — no client, no stdio,
no event loop. Put logic in `session.py`; a test that needs a live session is testing the
transport, and the interesting failures are never there.

**The stdout trap (PLAN.md §9.1): on stdio, stdout IS the protocol.** One stray `print`
corrupts the stream and the client reports something baffling and unrelated. Nothing
under `perfboard_studio.mcp` may print; logging is configured to stderr before anything else,
and the render tools import Qt and VTK *lazily inside the tool* rather than at module
scope — those imports are the real risk, since the engine itself has no prints.

Every result crossing this boundary is plain JSON-able data, and every hole is given as
its **address** (`"C7"`), the same language DRC and the guide speak. A refused command
returns `{"ok": false, "code": ..., "message": ...}` rather than raising, matching
`CommandBus.dispatch`'s contract — an agent must be able to try something and be told no.

**The defence against the tool count is a rule, not the ceiling, and the rule is now
measured.** PLAN.md §13 ties every tool to a group and a reason in `docs/MCP.md`. Nothing
checked that, so it slipped: `reroute` was registered and undocumented, and the count read
forty-four in the document and fifty in the plan while the server had fifty — three
numbers in three files.
`test_mcp.py::test_every_tool_is_named_in_the_documentation_and_nothing_else_is` reads the
table and both prose counts, in both directions: an undocumented tool is one nobody argued
for, and a documented one that no longer exists sends an agent after something that is not
there. Adding a tool therefore means adding its row and its paragraph, and bumping the
count in `docs/MCP.md` and PLAN.md §13.

### Stripboard is the board where the copper is subtracted

`board.type` is `pad-per-hole` or `stripboard`, and it is not a display setting. On
stripboard whole rows arrive already joined, so **`connectivity.py` has a fourth rule**
beside its three: on that board type the BOARD joins the holes along an uncut run, and
nobody soldered those connections. Only holes something is soldered into take part — a
strip physically joins all thirty holes in its row, and registering the rest would put
every empty pad into a net, which is what the module's own docstring says not to do.

`stripboard.py` owns the geometry, and one decision governs it: **a cut destroys the
copper AT a hole** (`TrackCut.at`), because that is how a track is broken — a drill turned
by hand, which takes the pad with it. A pin left in a cut hole is soldered to nothing,
which is DRC's `cut-track-conflict`, the twin of `mounting-hole-conflict`.

`striproute.py` is that board's router and it subtracts before it adds: cuts first, then
links over the COMPONENT side — the solder side is one sheet of parallel copper, and a
wire laid across it there shorts every strip it crosses. Both halves commit as one
command (`stripboard.apply`), because separately one Ctrl+Z leaves the board cut apart
with nothing linking it, or linked with nothing cut, which is a short. Pairs it cannot
separate (adjacent pins, no hole between them to drill) are reported, never routed around:
the fix is to move a part, and `placer.py` is what moves parts. It prices exactly those
pairs (`PlacementWeights.strip_conflict`) by exactly this rule — both modules read
`stripboard.MIN_SEPARABLE_GAP`, the same one-fact-two-consumers shape as `heat-proximity`
and the placer. Two more things follow from the board type there and were wrong before:
the alignment term counts **only the strip axis** (a shared column joins nothing on a
horizontal-strip board), and a candidate placement is judged by `plan_stripboard`, never
by `autoroute.py` — ranking a stripboard with the pad-per-hole router scores it on a build
nobody is going to follow.

### Layering

```
model → geometry → stripboard → connectivity / occupancy
                                    → drc, lvs, router, autoroute, placer, ratsnest,
                                      striproute, schematic
                                                        → guide → guide_export
                                                        → ui/, mcp/
```

`wiregauge.py` hangs off `model` alone — it is arithmetic on a gauge number — and is read
by `drc`, `router`, `striproute` and `guide`, which is how three siblings and their
downstream share one fact without importing one another.

`schematic.py` sits beside `ratsnest.py` on purpose: both take a document and a footprint
lookup and answer a question about the netlist, and neither is downstream of the other.
`ui/viewsch.py` is its only consumer.

`ui/view2d.py` works in millimetres (one scene unit = 1 mm), which is what makes the 1:1
PDF export exact without a fudge factor. `ui/view2d.hole_to_screen` / `screen_to_hole` are
the single place a hole becomes a scene position for either board side — every item that
needs a position routes through them rather than flipping signs locally.

Two rendering constraints that were measured, not guessed, and are documented at their
call sites: `PadGridItem` blits one pre-rasterised pad pixmap per hole (painting 6000
holes the obvious way took 124 ms/frame; a single even-odd `QPainterPath` took 5.8 s),
and `ui/scenetext.py` sizes annotation labels in **screen pixels** so they hold their size
as the board zooms — physical silkscreen scales with the board, annotations do not.

**A solder run is IN the surface and a wire is ON it, and that is geometry, not colour.**
Solder wets copper, so a run's centreline in 3D is the pad plane itself and only its outer
half shows; a wire's is a radius clear, and its two ends bend down into their holes. The
run is ONE varying-radius tube — wide at each joint, drawn in between — because a constant
tube with a sphere per pad meets it in a crease all the way round and reads as beads on a
stick. That narrowing is load-bearing: counting joints along a run against the real board
is what somebody following the guide does. Sizes live in `view3d`'s constants and say what
they measure; the two end pads get a solid at exactly the tube's radius there, so a flat
cap never shows.

**How high a conductor sits is `occupancy.stacking_layers` — the WHOLE answer, not
something to add `layer_z` back onto.** The document's own `layer_z` is that function's
floor; adding it again in `conductor_z` put conductors the stacker had deliberately
separated back at one height, on four of the fifteen fixtures.
`test_no_two_conductors_are_drawn_in_the_same_place` measures the drawn centrelines and
radii against each other across every fixture and is what found it — reach for that test
before trusting a render, because two solids in one place is a bug whatever the picture
looks like from the default camera. Two
crossing wires cannot occupy the same space; a solder trace never leaves the pads, because
it *is* the copper. The level is computed from what actually crosses what (`paths_cross` —
the same predicate DRC's `conductor-crossing` uses, so a shared endpoint stays a junction),
never from position in `doc.conductors`: that was the first answer and it lifted every
conductor past every earlier one, 4.47 mm off a 1.6 mm board, in 0.08 mm steps that were a
tenth of what two tubes need to clear — levitation and no clearance. `view3d.STACK_STEP_MM`
is derived from the tube radii for that reason, and `conductor_z` rests a tube on the *pad
plane* rather than at a fixed depth, so solder is tangent to the copper it is soldered to.
2D takes its z-order and its "passes over" outline from the same levels, so the two views
cannot disagree about which wire is on top.

`ui/view3d.populate_renderer` refreshes actors in an existing renderer and deliberately
leaves the camera alone; only `apply_default_camera` may move the viewpoint.

**Appearance is a view setting, not a document field.** Solder-mask colour changes
nothing about the circuit, and adding it to `Board` would reopen the byte-for-byte `.perf`
format for a cosmetic preference — so `ui/boardcolors.py` owns it, it is chosen from the
View menu, and it is not saved. Each scheme carries the 2D and 3D colours *together*, so
a board cannot be green in the editor and blue in the 3D view. Reach for this test on any
new visual option before adding a model field.

Three colour tables exist and answer different questions: `ui/theme.py` colours the
**application** (deliberately dim, so the eye lands on the board), `view2d`'s theme block
colours the **physical object** (FR4 green, tinned copper, solder grey), and
`ui/bodies.py` colours **parts** — in one table, so a resistor is the same beige in the
editor, the 3D view and the guide's step images.

`parsers/` is pure string-to-data: `sexpr.py` knows no KiCad semantics (just text to
tree), `kicad.py` maps a KiCad 6+ export netlist onto `Net` / `NetNode`. Reading the file
from disk is the caller's job, as everywhere else in the engine.

`ui/headless.py` is the `--headless` run, its own module rather than the bottom of
`main.py`: it is a program in its own right and being importable alone is what lets a
test call it. `ui/clipboard.py` is copy/paste — text in, `block.place` payload out, no
widgets — so the interesting half is tested by calling it.

**The window watches the open file** (`QFileSystemWatcher`, PLAN.md §9.3). With nothing
unsaved it reloads itself when the file changes; with unsaved edits it refuses and says
so, because losing somebody's work to a background event is the one outcome that must not
happen. A save does not trigger a reload — `_disk_text` is what tells our own write from
somebody else's.

**Crash recovery is the other half of that sentence**, because the process can also stop
without asking anybody. `recovery.py` is pure — what a record contains and whether one is
worth offering back are questions about strings — and `ui/autosave.py` is the host with the
clock, the directory and the writes. The same split as `updates.py` / `ui/updater.py`, and
it takes the same final position: **it protects work and never restores any.** A recovered
document is offered, the default answer is "Decide Later", and the file on disk is not
touched until the user saves. An automatic restore that guessed wrong would put an older
board in front of somebody who then presses Ctrl+S, and there is no way back from that.

Five decisions carry it, each with a test:

- **A record's existence means "there was unsaved work".** One is written only while the
  document differs from disk and deleted on every save and every clean close, which is what
  makes the question at startup simple.
- **`is_worth_offering` still checks two things**, because a crash can land between a save
  and the deletion after it: a record identical to the file means nothing was lost, and a
  record OLDER than the file is the stale copy. The second is the one that must not be got
  wrong.
- **Records live in the user's data directory, never beside the board.** A sidecar would be
  litter in a curated folder, would fail on a read-only location, and has nowhere to go at
  all for a board that was never saved — the board with the most to lose.
- **The write is atomic and never raises.** A crash during the write must not leave a
  half-file where the good one was, and a full disk must not take the board down *from the
  code meant to protect it*; `Autosave.write` returns a bool and the window says so once.
- **Nothing starts from the constructor** (`test_building_a_window_saves_nothing`), the same
  rule the update check follows: a suite that builds a great many windows must not leave a
  great many files in somebody's profile. `main()` starts the timer; `offer_recovery` runs
  off the event loop and prunes there, where it cannot delay the window appearing.

`_load_recovered` is deliberately **not** `_load_path`: the document did not come from the
file it names, so it arrives modified with `_disk_text = None`, and Ctrl+S is the gesture
that puts it back.

**Autosave also writes the DOCUMENT now** (`MainWindow._autosave_to_the_file`, the
`File ▸ Autosave to the File` toggle, on by default), and it is the one place this
application writes over somebody's file without being told to. Three hedges, each with a
test: never on a board with no path — that board is what the recovery record is for; the
file's last *deliberately* saved contents go to a `.bak` first and only once per save, so
the backup holds what the user chose to keep rather than what autosave last wrote; and if
the backup cannot be written, nothing is. It sets `_disk_text` exactly as `_save_to` does,
or the watcher reloads the window off its own autosave.

### A project is a folder, and the board in it is still a plain `.perf`

`project.py` says what a project contains without touching a filesystem — the names, the
layout, whether a directory is one — and `ui/project.py` has the disk and Qt's PDF writer.
The same split as `recovery.py`/`ui/autosave.py` and `updates.py`/`ui/updater.py`.

Not an archive, not a manifest, not a format: the byte-for-byte `.perf` does not move, the
document still opens in a text editor and an agent's file tools (PLAN.md §9.3), and
deleting the folder loses nothing the tool cannot write again. Everything generated lives
under `outputs/` and is rewritten wholesale on every project save, which is what makes it
safe to delete and pointless to edit — a folder where half the files are yours and half are
the tool's is a folder nobody dares tidy.

Three rules carry the writer:

- **The document is written first and alone.** It is the only file that cannot be
  regenerated, so it is not allowed to share a failure with the eight that can:
  `write_project` raises only if the BOARD could not be written.
- **Every export fails on its own and comes back named.** A circuit with no parts has no
  sheet to draw and a machine with no offscreen GL has no step images — a save that stopped
  at the first of those would stop working exactly as a project starts to have things in it.
- **The exports are named after the FILE, not after `meta.name`.** Renaming the `.perf` and
  saving again renames its outputs to match instead of leaving a set behind under the old
  name.

A folder with two boards in it is not a project (`project.is_project_dir`), because opening
it would mean guessing which one was meant.

**`router.py` keys its own sets on `(col, row)` tuples, not `geometry.hole_key`**, and
memoises the R5' proximity answer per hole. Both are measured (33% off a 100 × 60 board;
the numbers are in the module docstring) and neither may change a route: `hole_key` stays
the one encoding for everything that crosses a module boundary — occupancy, connectivity,
DRC — all of which have golden output. `tests/test_router.py` pins both properties.

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
names) is never translated: it is compared byte-for-byte by golden fixtures, and the
addresses are the tool's vocabulary in every language.

The language is chosen `--lang` → `PERFBOARD_STUDIO_LANG` → the View menu's stored choice → the
system locale (`main._preferred_language`), and applies at the **next start**: every label
is translated once, as the window is built, so a live re-translation would leave whatever
a rebuild missed in English.

### What the window remembers

`main.app_settings()` is the one `QSettings` store — recent files, the session
(geometry, dock state, board colour, the view toggles, routing style, language) and the
three `updates/` keys below. A test must point it somewhere temporary; `tests/test_ui.py`'s autouse `_settings_in_a_temp_file`
does, and has to, because every test there closes a window and closing saves.

Two rules it is easy to break: `restoreState` matches docks and toolbars **by
`objectName`** and silently drops the ones without one, and the **3D panel is forced shut
after a restore** — reopening it would build VTK's pipeline during startup for a board
nobody has looked at yet. Its size still comes back with the rest of the layout. The
build-guide dock (`Ctrl+4`) is the same shape of thing: it fills itself only while open,
because `build_guide` runs DRC and LVS, and `MainWindow.current_guide()` is the single
cache both it and the 3D assembly slider read — two views of one list that must not
disagree about how many steps there are.


### The update check decides nothing on the network and installs nothing at all

`updates.py` is an engine module and follows the engine's rule: **no network, no clock, no
disk.** Which release is newer, which of the three assets suits this machine, when to look
again, what the notes say — all of it maps a string to an answer, so all of it is reachable
from a test that hands it a string. `ui/updater.py` is the host: QtNetwork (the platform's
own TLS, so a frozen build has no CA bundle to forget to pack, and a 300 MB download gets a
progress bar and a working Cancel without a thread), the file, `hashlib`, and the clock.

Four decisions here are load-bearing and each is pinned by a test:

- **A `.devN` sorts BELOW the release it is heading for**, which is the opposite of
  `version.version_tuple()`. The two answer different questions — "which feature set is
  this?" versus "is there anything newer than what I am?" — and they are three lines apart
  in the imports.
- **Highest version wins, not newest publication.** The feed arrives in publication order,
  so a patch to an older line published after a newer minor would be offered to everyone
  as an upgrade.
- **A platform with no asset is offered no download.** The only macOS build is arm64 and
  the only AppImage x86_64; matching on the extension alone hands an Intel Mac 300 MB that
  cannot start. The release notes are offered instead — that is where "install from
  source" is written, and it is the same answer a `pip` install gets, since `sys.frozen`
  is what separates a packaged build from one whose update is `pip install -U`.
- **A response that is not a release feed is an error, never an answer.** A hotel wi-fi
  login page must read as "could not check", not as "you are up to date".

**It stops at the download.** The file is verified against the `SHA256SUMS` `release.yml`
attaches to every release, put in the user's Downloads folder and revealed in their file
manager. Running it needs elevation on Windows, a bundle swap in `/Applications` on macOS
and overwriting a running AppImage on Linux; doing that on somebody's behalf with an
installer nobody has signed (PLAN.md §12) is indistinguishable from malware and has no way
back. The checksum is worth exactly what it is worth, too: same host, same connection, so
it proves the download arrived intact and not who built it.

**Nothing runs by itself and nothing runs from a constructor.** The check starts from
`main()` through `QTimer.singleShot` after the window is shown, or from the Help menu —
never from `MainWindow.__init__`, which is what keeps a suite that builds a great many
windows off the network (`test_building_a_window_checks_nothing`). The first run asks
before the first request, so `updater.stored_preference` has **three** states: `None` is
"nobody has been asked", which is not "said no". Announcements land in a strip above the
board rather than a dialog, because a modal over a board somebody is routing gets
dismissed unread; Hide remembers **that version only**, so the next release is still
announced.
