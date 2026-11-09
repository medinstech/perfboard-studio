"""Rendering the soldering guide to the formats PLAN.md Sec 7.6 asks for.

Three writers, one model. ``guide.py`` decides WHAT the guide says; this file decides
what it looks like, and knows nothing about perfboard.

  HTML   one self-contained file. No CDN, no fonts, no network: it is meant to be opened
         on a phone propped against the monitor in a room that may not have wifi, and to
         still work in five years. Steps tick off and the progress is kept in
         localStorage, keyed by the document name, so closing the tab mid-build does not
         lose the place.
  CSV    the cut list and the BOM -- the two things people paste into a spreadsheet or
         hand to a supplier.
  JSON   the whole guide, for agents and integrations. Stable key order.

Pure and deterministic, stdlib only: no Qt, no I/O of its own beyond returning strings.
That is what lets the MCP server and a headless CI run produce the same guide the
desktop app does.

Every word this file adds -- a heading, a column, the tag beside a step -- is said in the
guide's own language (``guide.language``, through ``phrasebook``), so a Turkish guide is
Turkish all the way through without anybody passing the language twice. The ids the
guide carries as DATA (an archetype, a checkpoint kind, a wire colour) stay ids in the
JSON and are said in words where a person reads them.

The 1:1 printable sheets of the BOARD are a different thing and live in ui/export_pdf.py,
because they need a real renderer. This file references them rather than reproducing
them. The 1:1 wire templates at the end of the HTML guide are not that: they are lines,
written as SVG in millimetres, which a browser prints at real size with no renderer of
ours involved -- and the ruler printed beside them is how the reader checks it did.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import math
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from html import escape
from typing import Any

from .breadboard import has_breadboard_pattern, is_breadboard, is_solderable_breadboard
from .drc import MATERIAL_LABELS
from .geometry import board_size_mm, format_hole, holeless_positions
from .guide import (
    JSON_OMITTED_AT_DEFAULT,
    TEMPLATE_MARGIN_MM,
    WIRE_INK,
    Checkpoint,
    ConductorStep,
    Guide,
    GuideStep,
    LeadCut,
    PartStep,
    WireCut,
    WireMarkKind,
    WireTemplate,
    all_steps,
    conductor_word,
    is_guide_gap,
    lead_end,
    step_focus,
    wire_template,
)
from .harness import HarnessEnd
from .model import Board, HoleCoord
from .phrasebook import Phrasebook, phrasebook
from .version import __version__

# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def guide_to_json(guide: Guide, indent: int = 2) -> str:
    """The whole guide as JSON, for agents and integrations.

    Hole coordinates are emitted BOTH ways -- ``{"col": 2, "row": 6, "ref": "C7"}`` --
    because a consumer needs the numbers and a human reading the file needs the address,
    and making either one derive the other means two implementations of the hole
    encoding in the wild.
    """
    head: dict[str, Any] = {
        "generator": f"Perfboard Studio {__version__}",
        "document": guide.document_name,
    }
    # Only when it is not English -- the stripAxis rule, applied to an export: every
    # English guide ever written is still byte for byte what it was, and a reader that
    # finds no language knows it is reading English.
    if guide.language != "en":
        head["language"] = guide.language
    return json.dumps(
        {
            **head,
            "board": {
                "cols": guide.board.cols,
                "rows": guide.board.rows,
                "pitch_mm": guide.board.pitch,
                "material": guide.board.material,
                "thickness_mm": guide.board.thickness,
            },
            "iron": _plain(guide.iron, board=guide.board),
            "tools": list(guide.tools),
            "warnings": [_plain(w, board=guide.board) for w in guide.warnings],
            "bom": [_plain(line, board=guide.board) for line in guide.bom],
            "cut_list": [_plain(cut, board=guide.board) for cut in guide.cut_list],
            "spine_list": [_plain(spine, board=guide.board) for spine in guide.spine_list],
            "track_cuts": [_plain(cut, board=guide.board) for cut in guide.track_cuts],
            # Only when there are any, for the reason ``language`` is: a guide with no part
            # off the board is byte for byte the guide it always was.
            **({"lead_list": [_plain(lead, board=guide.board) for lead in guide.lead_list]} if guide.lead_list else {}),
            # The cables between a system's boards, only when there are any.
            **({"harness": [_plain(cable, board=None) for cable in guide.harness]} if guide.harness else {}),
            "phases": [
                {
                    "number": phase.number,
                    "title": phase.title,
                    "summary": phase.summary,
                    "steps": [_plain(step, board=guide.board) for step in phase.steps],
                    "checkpoints": [_plain(check, board=guide.board) for check in phase.checkpoints],
                }
                for phase in guide.phases
            ],
            "totals": {
                "part_steps": guide.part_steps,
                "conductor_steps": guide.conductor_steps,
                "checkpoints": guide.checkpoint_count,
            },
        },
        indent=indent,
        ensure_ascii=False,
    )


def _plain(value: Any, *, board: Board | None) -> Any:
    """Dataclasses to dicts, with every HoleCoord carrying its own address.

    Walks the fields itself rather than calling ``dataclasses.asdict``, which recurses
    first and would hand back holes already flattened to ``{"col", "row"}`` -- the
    address would be silently missing from every nested step.
    """
    if isinstance(value, HoleCoord):
        return {"col": value.col, "row": value.row, "ref": format_hole(value, board)}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _plain(getattr(value, f.name), board=board)
            for f in fields(value)
            if not (f.metadata.get(JSON_OMITTED_AT_DEFAULT) and getattr(value, f.name) == f.default)
        }
    if isinstance(value, dict):
        return {key: _plain(item, board=board) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item, board=board) for item in value]
    return value


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

#: Column headings, said in the guide's language like every other word here. Named here,
#: rather than written where they are used, because they reach ``say`` one at a time
#: through a loop -- and ``tests/test_phrasebook.py`` reads these to know they are said.
CUT_LIST_COLUMNS: tuple[str, ...] = (
    "type", "net", "from", "to", "path_mm", "cut_mm", "strip_mm", "awg", "colour", "note",
)
BOM_COLUMNS: tuple[str, ...] = ("quantity", "value", "footprint", "references")


def cut_list_to_csv(guide: Guide) -> str:
    """The wire cut list (PLAN.md Sec 7.3), plus the spine wires as their own rows.

    One table rather than two files: at the bench they are the same job -- cut these
    lengths of this wire -- and the ``type`` column is enough to tell them apart.
    """
    say = phrasebook(guide.language)
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([say(column) for column in CUT_LIST_COLUMNS])
    for cut in guide.cut_list:
        writer.writerow(
            [
                _wire_type(cut.insulated, say),
                cut.net_name,
                format_hole(cut.from_hole, guide.board),
                format_hole(cut.to_hole, guide.board),
                f"{cut.path_mm:.1f}",
                f"{cut.cut_mm:.1f}",
                f"{cut.strip_mm:.1f}",
                cut.awg,
                say(cut.colour),
                "",
            ]
        )
    for lead in guide.lead_list:
        writer.writerow(
            [
                say("wire off the board"),
                lead.net_name,
                format_hole(lead.hole, guide.board),
                lead_end(lead.ref, lead.pin, lead.pin_name, say),
                "",
                "" if lead.cut_mm is None else f"{lead.cut_mm:.1f}",
                f"{lead.strip_mm:.1f}",
                lead.awg,
                say(lead.colour),
                say("cut to fit") if lead.cut_mm is None else "",
            ]
        )
    for cable in guide.harness:
        for wire in cable.wires:
            writer.writerow(
                [
                    say("cable wire"),
                    wire.net_name,
                    harness_end(wire.a, say),
                    harness_end(wire.b, say),
                    "",
                    "" if wire.cut_mm is None else f"{wire.cut_mm:.1f}",
                    f"{wire.strip_mm:.1f}",
                    wire.awg,
                    say(wire.colour),
                    cable.ref if wire.cut_mm is not None else f"{cable.ref}, {say('cut to fit')}",
                ]
            )
    for spine in guide.spine_list:
        writer.writerow(
            [
                say("reinforcing wire"),
                spine.net_name,
                "",
                "",
                f"{spine.length_mm:.1f}",
                f"{spine.length_mm:.1f}",
                "0.0",
                "",
                say(spine.material),
                say("{gauge:g} mm, laid along {pads} pads", gauge=spine.gauge_mm, pads=spine.pads),
            ]
        )
    return out.getvalue()


def _html_lead_row(lead: LeadCut, say: Phrasebook, *, board: Board | None) -> str:
    """A wire to a part off the board, in the cut list's table: one hole, and the lug."""
    cut = say("cut to fit") if lead.cut_mm is None else f"{lead.cut_mm:.0f} mm"
    return (
        f"<tr><td>{say('wire off the board')}</td><td>{escape(lead.net_name)}</td>"
        f"<td>{_hole(lead.hole, board=board)}</td>"
        f"<td>{escape(lead_end(lead.ref, lead.pin, lead.pin_name, say))}</td>"
        f"<td>{escape(cut)}</td><td>{lead.awg}</td><td>{escape(say(lead.colour))}</td></tr>"
    )


def harness_end(end: HarnessEnd, say: Phrasebook) -> str:
    """A cable wire's end in the cut list: "Supply J2 pin 1", with the pin's name when the
    connector gives one -- the harness steps' own words."""
    if end.pin_name:
        return say(
            "{board} {ref} pin {pin} ({name})",
            board=end.board, ref=end.ref, pin=end.pin, name=end.pin_name,
        )
    return say("{board} {ref} pin {pin}", board=end.board, ref=end.ref, pin=end.pin)


def _wire_type(insulated: bool, say: Phrasebook) -> str:
    """One spelling for the cut list's two kinds of wire, in the CSV and the HTML table."""
    return say("insulated wire") if insulated else say("bare wire")


def bom_to_csv(guide: Guide) -> str:
    say = phrasebook(guide.language)
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([say(column) for column in BOM_COLUMNS])
    for line in guide.bom:
        writer.writerow([line.quantity, line.value, line.footprint_name, line.refs])
    return out.getvalue()


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

#: The wire table's headings -- the same list as the cut-list CSV, for a person.
WIRE_TABLE_COLUMNS: tuple[str, ...] = ("Type", "Net", "From", "To", "Cut", "AWG", "Colour")

_STYLE = """
:root {
  --bg: #14161b; --panel: #1b1e25; --panel-2: #22262f; --line: #2e333d;
  --text: #e7e9ee; --dim: #9aa3b2; --accent: #6fb3ff; --ok: #57c785;
  --warn: #f0b34a; --error: #ef6b6b; --trace: #d8a44a;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f6f7f9; --panel: #ffffff; --panel-2: #f0f2f5; --line: #d9dee6;
    --text: #1a1d23; --dim: #5d6673; --accent: #1667c8; --ok: #1d7a49;
    --warn: #8a5a00; --error: #b32020; --trace: #8a6100;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
main { max-width: 54rem; margin: 0 auto; padding: 1.5rem 1rem 6rem; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
h2 { font-size: 1.2rem; margin: 2.5rem 0 .25rem; }
h3 { font-size: 1rem; margin: 1.5rem 0 .5rem; color: var(--dim);
     text-transform: uppercase; letter-spacing: .06em; }
p  { margin: .4rem 0; }
a  { color: var(--accent); }
.sub { color: var(--dim); }
.phase { border-top: 2px solid var(--line); padding-top: .5rem; margin-top: 2rem; }
.phase-num { color: var(--accent); font-variant-numeric: tabular-nums; }
.step, .check {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: .7rem .9rem; margin: .5rem 0; display: flex; gap: .75rem; align-items: start;
}
.step.done, .check.done { opacity: .45; }
.step.done .title { text-decoration: line-through; }
input[type=checkbox] { width: 1.25rem; height: 1.25rem; margin-top: .2rem; flex: none; }
.body { flex: 1; min-width: 0; }
.title { font-weight: 600; }
.meta { color: var(--dim); font-size: .875rem; }
.note { font-size: .9rem; margin-top: .35rem; }
.shot { display: block; width: 100%; max-width: 30rem; margin: .6rem 0 .1rem;
        border: 1px solid var(--line); border-radius: 8px; background: #14161b; }
.hole { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        background: var(--panel-2); border-radius: 4px; padding: 0 .3rem; }
.tag { font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
       border: 1px solid var(--line); border-radius: 999px; padding: .1rem .5rem;
       color: var(--dim); white-space: nowrap; }
.polarity { color: var(--warn); font-weight: 600; }
.risk { color: var(--error); }
.check { border-left: 3px solid var(--ok); }
.check.isolation { border-left-color: var(--warn); }
.check.blocking { border-left-color: var(--error); }
.warnbox { background: var(--panel-2); border-left: 3px solid var(--warn);
           border-radius: 6px; padding: .6rem .9rem; margin: .5rem 0; }
.notebox { background: var(--panel-2); border-left: 3px solid var(--line);
           border-radius: 6px; padding: .6rem .9rem; margin: .5rem 0; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; margin: .5rem 0; }
th, td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid var(--line); }
th { color: var(--dim); font-weight: 600; }
.wrap { overflow-x: auto; }
.progress { position: fixed; left: 0; right: 0; bottom: 0; background: var(--panel);
            border-top: 1px solid var(--line); padding: .6rem 1rem;
            display: flex; gap: 1rem; align-items: center; justify-content: center; }
.bar { flex: 1; max-width: 30rem; height: 8px; background: var(--panel-2);
       border-radius: 999px; overflow: hidden; }
.bar > i { display: block; height: 100%; width: 0; background: var(--ok); }
button { font: inherit; color: var(--text); background: var(--panel-2);
         border: 1px solid var(--line); border-radius: 6px; padding: .3rem .7rem;
         cursor: pointer; }
@media print {
  /* The whole palette, not just body: printed from a browser whose OS is in dark mode
     the tokens above are still the dark ones, and browsers drop background colours when
     they print -- so --dim's pale grey lands on white paper and the meta line under
     every step is the part that fades out. This guide gets taped next to the board. */
  :root {
    --bg: #fff; --panel: #fff; --panel-2: #f0f0f0; --line: #bbb;
    --text: #000; --dim: #444; --accent: #10305c; --ok: #14562f;
    --warn: #6b4300; --error: #8c1616; --trace: #6b4b00;
  }
  .progress, input[type=checkbox] { display: none; }
  body { background: #fff; color: #000; }
  .step, .check { break-inside: avoid; }
  .shot { break-inside: avoid; max-width: 20rem; }
  /* A step's enlarged template is for the screen; paper gets the 1:1 pages at the end. */
  .tpl-preview { display: none; }
  .templates { break-before: page; }
}
/* Wire templates. Drawn on white whatever the theme, as the paper they stand for. */
.tpl-preview { margin: .5rem 0 .1rem; }
.tpl-pair { display: flex; flex-wrap: wrap; gap: .4rem 1.2rem; align-items: flex-start; }
.tpl-pair svg, .ruler { display: block; background: #fff; border-radius: 4px; }
/* Only on screen: printed, a template scaled to fit is a template that lies. */
@media screen { .tpl-pair svg { max-width: 100%; height: auto; } }
/* The 1:1 pages pack templates in rows, each as wide as its own drawings, so a board's
   worth of short wires is a page or two rather than a page per handful. */
.tpl-grid { display: flex; flex-wrap: wrap; gap: 5mm 6mm; align-items: flex-start;
            margin-top: 4mm; }
.tpl { break-inside: avoid; width: min-content; }
.tpl .title { white-space: nowrap; font-size: .85rem; }
.tpl .meta { font-size: .75rem; }
"""

_SCRIPT = """
(function () {
  var key = 'perfboard-studio-guide:' + document.body.dataset.doc;
  var boxes = Array.prototype.slice.call(document.querySelectorAll('input[type=checkbox]'));
  var fill = document.querySelector('.bar > i');
  var count = document.querySelector('.count');
  var done = {};
  try { done = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) { done = {}; }

  function paint() {
    var n = 0;
    boxes.forEach(function (box) {
      box.closest('.step, .check').classList.toggle('done', box.checked);
      if (box.checked) n++;
    });
    if (fill) fill.style.width = (boxes.length ? (n / boxes.length) * 100 : 0) + '%';
    if (count) count.textContent = n + '__OF__' + boxes.length + '__DONE__';
  }

  boxes.forEach(function (box) {
    box.checked = !!done[box.id];
    box.addEventListener('change', function () {
      done[box.id] = box.checked;
      try { localStorage.setItem(key, JSON.stringify(done)); } catch (e) {}
      paint();
    });
  });

  var reset = document.querySelector('.reset');
  if (reset) reset.addEventListener('click', function () {
    done = {};
    try { localStorage.removeItem(key); } catch (e) {}
    boxes.forEach(function (box) { box.checked = false; });
    paint();
  });

  paint();
})();
"""


def guide_to_html(guide: Guide, step_images: Mapping[str, bytes] | None = None) -> str:
    """One self-contained HTML file: no network, no assets, no build step.

    Deliberately not a framework. This file has to open from a USB stick on a phone in
    five years' time, which rules out every dependency that could stop existing.

    ``step_images`` are the illustrations PLAN.md §7.2 asks for, keyed by
    ``guide.step_focus(step)``. **Raw image bytes, not URLs or paths** — this function
    base64s them into the document itself. That is the whole point: a caller cannot hand
    it a link, so the finished file cannot acquire a dependency on a server, a folder
    beside it, or a phone's network. Rendering them needs VTK and a real board, which is
    the host's job (``ui/view3d.render_offscreen``); this module has never known what a
    board looks like and still does not — including what format its pictures are in,
    which ``_image_media_type`` reads off the bytes rather than agreeing in advance.
    """
    say = phrasebook(guide.language)
    parts: list[str] = [
        "<!doctype html>",
        f'<html lang="{guide.language}"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>"
        + say("{name} — build guide", name=escape(guide.document_name))
        + "</title>",
        f"<style>{_STYLE}</style></head>",
        f'<body data-doc="{escape(guide.document_name)}"><main>',
        f"<h1>{escape(guide.document_name)}</h1>",
        # Spelled the way the sheet below it spells them: "32 × 22" with spaces, and the
        # material as the guide's own prose writes it (FR-4, not the enum's FR4). The
        # header and the "Cut it to..." line twelve lines down described one board in two
        # notations.
        '<p class="sub">'
        + (
            say(
                "Building guide · solderless breadboard, {points} points · {steps} steps, "
                "{checks} checks · Perfboard Studio {version}",
                points=guide.board.cols * guide.board.rows - len(holeless_positions(guide.board)),
                steps=guide.total_steps,
                checks=guide.checkpoint_count,
                version=escape(__version__),
            )
            if is_breadboard(guide.board)
            else say(
                "Soldering guide · solderable breadboard, {points} points · {steps} steps, "
                "{checks} checks · Perfboard Studio {version}",
                points=guide.board.cols * guide.board.rows - len(holeless_positions(guide.board)),
                steps=guide.total_steps,
                checks=guide.checkpoint_count,
                version=escape(__version__),
            )
            if is_solderable_breadboard(guide.board)
            else say(
                "Soldering guide · {cols} × {rows} {material} perfboard at {pitch:g} mm pitch · "
                "{steps} steps, {checks} checks · Perfboard Studio {version}",
                cols=guide.board.cols,
                rows=guide.board.rows,
                material=escape(MATERIAL_LABELS[guide.board.material]),
                pitch=guide.board.pitch,
                steps=guide.total_steps,
                checks=guide.checkpoint_count,
                version=escape(__version__),
            )
        )
        + "</p>",
    ]

    # A gap -- a part of the build the guide does not cover -- in the warning box; a note
    # about the board -- a stock board's fingers -- in a quiet one, as the window lists it
    # beside the files rather than in its "The guide has gaps" dialog (``is_guide_gap``).
    for warning in guide.warnings:
        box = "warnbox" if is_guide_gap(warning) else "notebox"
        parts.append(
            f'<div class="{box}"><b>{escape(say(warning.code))}</b> — '
            f"{escape(warning.message)}</div>"
        )

    parts.append(_html_preparation(guide, say))

    images = step_images or {}
    step_id = 0
    for phase in guide.phases:
        if phase.is_empty or phase.number == 0:
            continue
        parts.append(
            '<section class="phase"><h2><span class="phase-num">'
            + say("Phase {number}", number=phase.number)
            + f"</span> — {escape(phase.title)}</h2>"
            f'<p class="sub">{escape(phase.summary)}</p>'
        )
        for step in phase.steps:
            step_id += 1
            parts.append(_html_step(step, f"s{step_id}", images, say, guide.board))
        if phase.checkpoints:
            parts.append("<h3>" + say("Check before moving on") + "</h3>")
            for check in phase.checkpoints:
                step_id += 1
                parts.append(_html_check(check, f"s{step_id}", say, board=guide.board))
        parts.append("</section>")

    if guide.harness:
        parts.append(
            '<section class="phase"><h2>'
            + escape(say("Harness"))
            + f'</h2><p class="sub">{escape(say("Fitted once every board is built: a cable joins connectors that are already soldered, and is checked end to end before anything is powered."))}</p>'
        )
        for cable in guide.harness:
            parts.append(f"<h3>{escape(cable.ref)}</h3><ol>")
            parts.extend(f"<li>{escape(text)}</li>" for text in cable.steps)
            parts.append("</ol>")
            if cable.checkpoints:
                parts.append("<h3>" + say("Check before moving on") + "</h3>")
                for check in cable.checkpoints:
                    step_id += 1
                    parts.append(_html_check(check, f"s{step_id}", say, board=None))
        parts.append("</section>")

    parts.append(_html_tables(guide, say))
    parts.append(_html_templates(guide, say))
    # The counter's words go into the script as JavaScript string literals, which is why
    # a translation of them may hold no quote or backslash (tests/test_phrasebook.py).
    script = _SCRIPT.replace("__OF__", say(" of ")).replace("__DONE__", say(" done"))
    parts.append(
        '</main><div class="progress"><span class="count"></span>'
        '<span class="bar"><i></i></span>'
        '<button class="reset" type="button">'
        + say("Reset progress")
        + "</button></div>"
        f"<script>{script}</script></body></html>"
    )
    return "\n".join(parts)


def _hole(at: HoleCoord, *, board: Board | None) -> str:
    return f'<span class="hole">{escape(format_hole(at, board))}</span>'


def _html_cuts(guide: Guide, say: Phrasebook) -> str:
    """The tracks to break, before anything is soldered.

    In phase 0 and nowhere else, because that is when they are physically possible: the
    cut is drilled through the hole from the copper side, and a part sitting over it puts
    the hole out of a drill bit's reach for good.
    """
    if not guide.track_cuts:
        return ""
    rows = "".join(
        f"<tr><td>{_hole(cut.at, board=guide.board)}"
        f"{(' – ' + _hole(cut.to, board=guide.board)) if cut.to is not None else ''}</td><td>{escape(cut.strip)}</td>"
        f"<td>{_hole(cut.separates[0], board=guide.board)} ↔ {_hole(cut.separates[1], board=guide.board)}</td></tr>"
        if cut.separates is not None
        else f"<tr><td>{_hole(cut.at, board=guide.board)}</td><td>{escape(cut.strip)}</td><td>—</td></tr>"
        for cut in guide.track_cuts
    )
    if any(cut.to is not None for cut in guide.track_cuts):
        instructions = say(
            "{count} track cut(s). A single hole marks a cut through that pad. "
            "Two hole addresses mark a cut in the copper between those holes. "
            "Make the cuts from the copper side before fitting parts.",
            count=len(guide.track_cuts),
        )
    else:
        instructions = say(
            "{count} cut(s), made from the copper side with a spot-face cutter or a 3 mm "
            "drill turned by hand. Each one takes the pad with it, so the hole it is made in "
            "has nothing to solder to afterwards. Do them all before the first part goes in "
            "— once a part is over a hole there is no way back to it.",
            count=len(guide.track_cuts),
        )
    return (
        "<h3>" + say("Cut these tracks first") + "</h3><p>"
        + instructions
        + '</p><div class="wrap"><table>'
        f"<tr><th>{say('Hole')}</th><th>{say('Strip')}</th><th>{say('Separates')}</th></tr>"
        f"{rows}</table></div>"
    )


def _board_mm(guide: Guide) -> str:
    """The substrate's real size, as ``W × H mm``."""
    width, height = board_size_mm(guide.board)
    return f"{width:.1f} × {height:.1f} mm"


def _html_preparation(guide: Guide, say: Phrasebook) -> str:
    phase = guide.phases[0]
    rows = "".join(f"<li>{escape(tool)}</li>" for tool in guide.tools)
    checks = "".join(
        _html_check(check, f"p0-{n}", say, board=guide.board) for n, check in enumerate(phase.checkpoints)
    )
    return (
        '<section class="phase"><h2><span class="phase-num">'
        + say("Phase {number}", number=0)
        + f"</span> — {escape(phase.title)}</h2>"
        f'<p class="sub">{escape(phase.summary)}</p>'
        f"<h3>{say('On the bench')}</h3><ul>{rows}</ul>"
        + _html_iron(guide, say)
        + f"<h3>{say('The board')}</h3><p>"
        + (_html_breadboard(guide, say) if has_breadboard_pattern(guide.board) else say(
            "Cut it to {cols} × {rows} holes ({size}) and mark hole {a1} in the top-left "
            "corner on the COMPONENT side. Every address below is counted from it, so if it "
            "is marked wrong, everything else is.",
            cols=guide.board.cols,
            rows=guide.board.rows,
            # geometry.board_size_mm, never cols*pitch: the substrate runs half a pitch
            # past the outermost hole centres PLUS the printed border, and its docstring
            # says nothing else may recompute it. Cutting to the recomputed number cuts a
            # bordered board short by the border on both sides.
            size=_board_mm(guide),
            a1='<span class="hole">A1</span>',
        ))
        + f"</p>{_html_cuts(guide, say)}{checks}</section>"
    )


def _html_iron(guide: Guide, say: Phrasebook) -> str:
    """The iron, when there is one: a breadboard with nothing to solder has none."""
    if guide.iron is None:
        return ""
    return (
        f"<h3>{say('Iron')}</h3><p>"
        + say(
            "{temperature} °C, no more than {dwell:g} s on any one pad. {note}",
            temperature=guide.iron.temperature_c,
            dwell=guide.iron.max_dwell_s,
            note=escape(guide.iron.note),
        )
        + "</p>"
    )


def _html_breadboard(guide: Guide, say: Phrasebook) -> str:
    """What the board is, where a perfboard's says what to cut it to. Which way round it
    goes is the phase-0 summary just above, which the window's guide shows too."""
    if is_solderable_breadboard(guide.board):
        return say(
            "A solderable breadboard, {points} points: a breadboard's holes and strips in "
            "copper. Nothing on it is cut: every part goes through its holes and is soldered "
            "to the strip under it.",
            points=guide.board.cols * guide.board.rows - len(holeless_positions(guide.board)),
        )
    return say(
        "A solderless breadboard, {points} points. Nothing on it is cut, drilled or "
        "soldered: every part and every wire is pushed into its holes.",
        points=guide.board.cols * guide.board.rows - len(holeless_positions(guide.board)),
    )


def _html_step(
    step: GuideStep, dom_id: str, images: Mapping[str, bytes], say: Phrasebook, board: Board
) -> str:
    picture = _html_step_image(step, images)
    if isinstance(step, PartStep):
        return _html_part_step(step, dom_id, picture, say, board=board)
    return _html_conductor_step(step, dom_id, picture, say, wire_template(step, board), board=board)


#: Magic bytes to media type, longest signature first. A data URI carries its own type,
#: so the one thing this must never do is guess: a JPEG announced as ``image/png`` is a
#: broken picture in the one place there is no network to re-fetch it from.
_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),  # bytes 8..12 say WEBP; _image_media_type checks them
    (b"\x89PNG", "image/png"),  # the truncated stub the tests hand over
)


def _image_media_type(data: bytes) -> str:
    """What the bytes actually are, read off the front of them.

    The renderer's format is its own decision (``ui/view3d`` writes JPEG, and wrote PNG
    before that), and this module has no way to ask. Sniffing keeps the two from having
    to agree in advance -- and keeps a stale caller from mislabelling its own picture.
    """
    for magic, media in _IMAGE_MAGIC:
        if not data.startswith(magic):
            continue
        if magic == b"RIFF" and data[8:12] != b"WEBP":
            continue
        return media
    return "application/octet-stream"


def _html_step_image(step: GuideStep, images: Mapping[str, bytes]) -> str:
    """The board as it stands at this step, with this step's own part picked out.

    Inlined as a data URI. The alt text is the step's title rather than "step image":
    printed, or read aloud, or opened where the picture will not load, the sentence that
    survives has to be the one that says what to do.
    """
    picture = images.get(step_focus(step))
    if not picture:
        return ""
    encoded = base64.b64encode(picture).decode("ascii")
    return (
        f'<img class="shot" alt="{escape(step.title)}" '
        f'src="data:{_image_media_type(picture)};base64,{encoded}">'
    )


def _html_part_step(
    step: PartStep, dom_id: str, picture: str = "", say: Phrasebook | None = None, *, board: Board | None
) -> str:
    say = say or phrasebook("en")
    holes = " ".join(f"{escape(number)}:{_hole(at, board=board)}" for number, at in step.pin_holes)
    # A cabled module's notes give its leads pin by pin, by name: a second, numbered list of
    # the same holes would be the same thing said twice.
    meta = (
        escape(step.footprint_name)
        if step.cabled
        else say("{footprint} · pins {holes}", footprint=escape(step.footprint_name), holes=holes)
    )
    bits = [
        f'<div class="title">{escape(step.title)}</div>',
        '<div class="meta">' + meta + (f" · {step.rotation}°" if step.rotation else "") + "</div>",
    ]
    if step.bend_template_mm:
        bits.append(
            '<div class="note">'
            + say(
                "Bend the leads to {pitch:.2f} mm ({holes:.0f} holes).",
                pitch=step.bend_template_mm,
                holes=step.bend_template_mm / 2.54,
            )
            + "</div>"
        )
    if step.polarity:
        bits.append(f'<div class="note polarity">{escape(step.polarity)}</div>')
    for note in step.notes:
        bits.append(f'<div class="note sub">{escape(note)}</div>')
    return (
        f'<label class="step" for="{dom_id}">'
        f'<input type="checkbox" id="{dom_id}">'
        f'<span class="body">{"".join(bits)}{picture}</span>'
        f'<span class="tag">{escape(say(step.archetype))}</span></label>'
    )


def _conductor_word(step: ConductorStep, say: Phrasebook) -> str:
    """What the copper is made of, as the tag beside the step and its meta line say it."""
    return conductor_word(step.conductor_kind, say.language)


def _html_conductor_step(
    step: ConductorStep,
    dom_id: str,
    picture: str = "",
    say: Phrasebook | None = None,
    template: WireTemplate | None = None, *, board: Board | None,
) -> str:
    say = say or phrasebook("en")
    bits = [
        f'<div class="title">{escape(step.net_name)}: '
        f"{_hole(step.path[0], board=board)} → {_hole(step.path[-1], board=board)}</div>"
        if step.path
        else f'<div class="title">{escape(step.title)}</div>',
        f'<div class="meta">{escape(_conductor_word(step, say))} · '
        f"{step.length_mm:.1f} mm"
        + (" · " + say("{pads} pads", pads=step.pads) if step.pads > 2 else "")
        + (
            " · " + say("about {milliohm:.1f} mΩ", milliohm=step.resistance_ohm * 1000)
            if step.resistance_ohm is not None
            else ""
        )
        + (
            " · " + say("{drop:.0f} mV drop", drop=step.drop_mv)
            if step.drop_mv is not None
            else ""
        )
        + "</div>",
    ]
    # The path's own length, not its pad count: a wire's corners are where to bend it, and
    # they are exactly what a wire laid along the grid most needs to say.
    if len(step.path) > 2:
        bits.append(
            '<div class="meta">'
            + say("Path: {holes}", holes=" → ".join(_hole(at, board=board) for at in step.path))
            + "</div>"
        )
    if step.cut is not None:
        # Bare wire has nothing to strip, and "strip 0 mm at each end" is an instruction
        # to do nothing -- so the clause is left out rather than printed as a zero.
        strip = (
            say(", strip {strip:.0f} mm at each end", strip=step.cut.strip_mm)
            if step.cut.strip_mm > 0
            else ""
        )
        bits.append(
            '<div class="note">'
            + say(
                "Cut {length:.0f} mm of {colour} AWG {awg}{strip}.",
                length=step.cut.cut_mm,
                colour=escape(say(step.cut.colour)),
                awg=step.cut.awg,
                strip=strip,
            )
            + "</div>"
        )
        if template is not None:
            # Enlarged, for a screen: a phone has no millimetres, and a 20 mm wire at
            # "1:1" is a smudge beside its instructions. Paper gets the real size at the end.
            bits.append(
                '<div class="tpl-preview">'
                + _template_pair(template, step, step.cut, TEMPLATE_PREVIEW_SCALE, board=board)
                + "</div>"
            )
    if step.spine is not None:
        bits.append(
            '<div class="note">'
            + say(
                "Reinforcing wire: {length:.0f} mm of {gauge:g} mm {material}.",
                length=step.spine.length_mm,
                gauge=step.spine.gauge_mm,
                material=escape(say(step.spine.material)),
            )
            + "</div>"
        )
    for note in step.notes:
        bits.append(f'<div class="note sub">{escape(note)}</div>')
    for risk in step.risks:
        bits.append(f'<div class="note risk">⚠ {escape(risk.message)}</div>')
    return (
        f'<label class="step" for="{dom_id}">'
        f'<input type="checkbox" id="{dom_id}">'
        f'<span class="body">{"".join(bits)}{picture}</span>'
        f'<span class="tag" style="color:var(--trace)">'
        f"{escape(_conductor_word(step, say))}</span></label>"
    )


def _html_check(check: Checkpoint, dom_id: str, say: Phrasebook | None = None, *, board: Board | None) -> str:
    say = say or phrasebook("en")
    classes = f"check {check.kind}" + (" blocking" if check.blocking else "")
    holes = (
        '<div class="meta">'
        + say("Probe {holes}", holes=say.joined([_hole(at, board=board) for at in check.holes]))
        + "</div>"
        if check.holes
        else ""
    )
    gate = (
        '<div class="note risk">' + say("Do not apply power until this passes.") + "</div>"
        if check.blocking
        else ""
    )
    return (
        f'<label class="{classes}" for="{dom_id}">'
        f'<input type="checkbox" id="{dom_id}">'
        f'<span class="body"><div class="title">{escape(check.title)}</div>'
        f'<div class="note">{escape(check.instruction)}</div>{holes}'
        '<div class="note sub">'
        + say("Expect: {expected}", expected=escape(check.expected))
        + f"</div>{gate}</span>"
        f'<span class="tag">{escape(say(check.kind))}</span></label>'
    )


# ---------------------------------------------------------------------------
# Wire templates (guide.wire_template), as SVG in millimetres
# ---------------------------------------------------------------------------

#: Stripped copper, at both ends of an insulated wire.
_COPPER_INK = "#c8783a"
#: The bends -- the same blue on the shape and on the straightened wire, solid where the
#: wire goes down through the board and dashed where it turns along it.
_BEND_INK = "#1667c8"
_TURN_DASH = ' stroke-dasharray=".9 .6"'
#: Drawn line widths, in mm. Near a wire's own but not meant to be it: what has to read at
#: arm's length is where the bends are, not the gauge.
_INSULATED_MM = 1.2
_BARE_MM = 0.6
#: Lettering, in mm of paper, and a generous width per character for keeping it inside.
_LABEL_MM = 2.4
_CHAR_MM = 1.6
#: How much bigger than life a step's own preview is drawn on screen.
TEMPLATE_PREVIEW_SCALE = 2.5
#: The calibration bar's length, in mm: long enough that "fit to page" at 97 % comes out
#: 1.5 mm short against a ruler, which is visible.
RULER_MM = 50


def _wire_ink(cut: WireCut) -> tuple[str, float]:
    """A wire's ink and drawn width. A colour the guide cannot ink -- a word a document
    gave its wire that is no stocked colour -- is drawn grey, under its own name."""
    ink = WIRE_INK.get(cut.colour, WIRE_INK["grey"])
    return ink, _INSULATED_MM if cut.insulated else _BARE_MM


def _svg(
    width: float, height: float, scale: float, body: str, left: float = 0.0, top: float = 0.0
) -> str:
    """An SVG whose units are millimetres of paper: ``width`` and ``height`` carry ``mm``
    and the viewBox is the same numbers, so at ``scale`` 1 a line 30 units long prints
    30 mm long. ``scale`` enlarges the picture without touching what is drawn in it.

    No ``xmlns``: inline in HTML an SVG needs none, and the guide holds no URL at all
    (``test_html_is_self_contained``), not even one that is only a name."""
    return (
        f'<svg width="{width * scale:.2f}mm" height="{height * scale:.2f}mm" '
        f'viewBox="{left:.2f} {top:.2f} {width:.2f} {height:.2f}">{body}</svg>'
    )


def _wire_line(points: list[tuple[float, float]], ink: str, width: float) -> str:
    """The wire, with a dark edge under it so a white or yellow one shows on white paper."""
    line = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return (
        f'<polyline points="{line}" fill="none" stroke="#4a4a4a" stroke-width="{width + .3:.2f}" '
        'stroke-linejoin="round"/>'
        f'<polyline points="{line}" fill="none" stroke="{ink}" stroke-width="{width:.2f}" '
        'stroke-linejoin="round"/>'
    )


def _label(x: float, y: float, text: str, anchor: str = "middle", size: float = _LABEL_MM) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size:g}" font-family="sans-serif" '
        f'text-anchor="{anchor}" fill="#222">{escape(text)}</text>'
    )


def _shape_svg(template: WireTemplate, step: ConductorStep, cut: WireCut, scale: float, *, board: Board | None) -> str:
    """The wire's shape over the board's holes: lay the bent wire on it to check it."""
    ink, width = _wire_ink(cut)
    shape = list(template.shape)
    # The holes as ONE path of zero-length strokes, each a dot by its round cap: a third
    # of the bytes of a circle apiece, and a 53-wire guide draws the holes twice per wire.
    # (Not a <pattern>: that is filled by url(), and the guide holds no url() of any kind.)
    holes = "".join(f"M{x:.2f} {y:.2f}h0" for x, y in template.holes)
    body = [
        f'<path d="{holes}" stroke="#d4d4d4" stroke-width=".9" stroke-linecap="round"/>',
        _wire_line(shape, ink, width),
    ]
    if template.strip_mm > 0:
        for tip, inner in ((shape[0], shape[1]), (shape[-1], shape[-2])):
            k = template.strip_mm / math.dist(tip, inner)
            end = (tip[0] + (inner[0] - tip[0]) * k, tip[1] + (inner[1] - tip[1]) * k)
            body.append(
                f'<line x1="{tip[0]:.2f}" y1="{tip[1]:.2f}" x2="{end[0]:.2f}" y2="{end[1]:.2f}" '
                f'stroke="{_COPPER_INK}" stroke-width="{width + .3:.2f}"/>'
            )
    ends = (1, len(shape) - 2)
    for index in template.bends:
        x, y = shape[index]
        dash = "" if index in ends else _TURN_DASH
        body.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.3" fill="none" stroke="{_BEND_INK}" '
            f'stroke-width=".35"{dash}/>'
        )
    # Each TIP named by the hole it goes into, just past the tip along its leg -- the one
    # place on the drawing nothing else is, however short the wire. Named beside its ring
    # instead, a 14 mm wire's two names sat on its own corner. The straightened wire names
    # its tips the same way, which is what says which end its marks are measured from.
    box = [0.0, 0.0, template.width_mm, template.height_mm]
    for tip, inner, at in ((shape[0], shape[1], step.path[0]), (shape[-1], shape[-2], step.path[-1])):
        name = format_hole(at, board)
        run = math.dist(tip, inner)
        ux, uy = (tip[0] - inner[0]) / run, (tip[1] - inner[1]) / run
        half_w, half_h = len(name) * _CHAR_MM * 0.45, _LABEL_MM / 2
        cx = tip[0] + ux * (0.8 + half_w * abs(ux))
        cy = tip[1] + uy * (0.8 + half_h * abs(uy))
        body.append(_label(cx, cy + _LABEL_MM / 3, name))
        box = [
            min(box[0], cx - half_w - 0.5),
            min(box[1], cy - half_h - 0.5),
            max(box[2], cx + half_w + 0.5),
            max(box[3], cy + half_h + 0.5),
        ]
    return _svg(box[2] - box[0], box[3] - box[1], scale, "".join(body), box[0], box[1])


#: The marks on the straightened wire, by what happens there.
_MARK_INK: dict[WireMarkKind, str] = {"strip": "#333333", "through": _BEND_INK, "turn": _BEND_INK}


def _straight_svg(template: WireTemplate, step: ConductorStep, cut: WireCut, scale: float, *, board: Board | None) -> str:
    """The same wire straight, at 1:1: what is cut and marked before anything is bent.

    Each mark's distance from the left-hand tip is printed under it, so a whole wire is
    marked from one end with one ruler and no error adds up from mark to mark. The two
    tips are named by the holes they end in, which is what says which way round to hold it.
    """
    ink, width = _wire_ink(cut)
    m, length, y = TEMPLATE_MARGIN_MM, template.length_mm, 6.0
    rows = (y + 4.6, y + 7.2)
    body = [_wire_line([(m, y), (m + length, y)], ink, width)]
    if template.strip_mm > 0:
        for start in (0.0, length - template.strip_mm):
            body.append(
                f'<line x1="{m + start:.2f}" y1="{y}" x2="{m + start + template.strip_mm:.2f}" '
                f'y2="{y}" stroke="{_COPPER_INK}" stroke-width="{width + .3:.2f}"/>'
            )
    body.append(_label(m, y - 2.2, format_hole(step.path[0], board), "start"))
    body.append(_label(m + length, y - 2.2, format_hole(step.path[-1], board), "end"))
    # A number drops to the second row when it would touch the last one on the first: a
    # corner one pitch from a bend puts two distances 2.54 mm apart. The tip's own number,
    # last, is the whole length -- the cut list's figure, where the wire is cut.
    last_on_first_row = -math.inf
    for mark in (*template.marks, None):
        at = length if mark is None else mark.at_mm
        x = m + at
        text = f"{at:.1f}"
        row = 0 if x - last_on_first_row >= len(text) * _CHAR_MM * 0.75 else 1
        if row == 0:
            last_on_first_row = x
        if mark is not None:
            dash = _TURN_DASH if mark.kind == "turn" else ""
            body.append(
                f'<line x1="{x:.2f}" y1="{y - 1.5:.2f}" x2="{x:.2f}" y2="{rows[row] - 2:.2f}" '
                f'stroke="{_MARK_INK[mark.kind]}" stroke-width=".35"{dash}/>'
            )
        body.append(_label(x, rows[row], text, size=2.0))
    return _svg(length + 2 * m, rows[1] + 1.0, scale, "".join(body))


def _template_pair(
    template: WireTemplate, step: ConductorStep, cut: WireCut, scale: float = 1.0, *, board: Board | None
) -> str:
    return (
        '<div class="tpl-pair">'
        + _shape_svg(template, step, cut, scale, board=board)
        + _straight_svg(template, step, cut, scale, board=board)
        + "</div>"
    )


def _ruler_svg() -> str:
    ticks = "".join(
        f'<line x1="{x}" y1="{1 if x % 10 else 0}" x2="{x}" y2="4" stroke="#000" '
        'stroke-width=".25"/>'
        for x in range(0, RULER_MM + 1, 5)
    )
    return (
        f'<svg class="ruler" width="{RULER_MM + 2}mm" '
        f'height="8mm" viewBox="-1 0 {RULER_MM + 2} 8">'
        f'<line x1="0" y1="4" x2="{RULER_MM}" y2="4" stroke="#000" stroke-width=".35"/>{ticks}'
        + _label(0, 7.4, "0", "start", 2.6)
        + _label(RULER_MM, 7.4, f"{RULER_MM} mm", "end", 2.6)
        + "</svg>"
    )


def _html_templates(guide: Guide, say: Phrasebook) -> str:
    """The last pages: every wire at 1:1, in the order they are fitted, to cut and bend on.

    A screen has no millimetres -- CSS's ``mm`` is a fixed number of pixels that is right
    on no particular phone -- so the 1:1 promise is made only on paper, and the ruler is how
    the reader checks the printer kept it.
    """
    items: list[str] = []
    for step in all_steps(guide):
        if not isinstance(step, ConductorStep) or step.cut is None:
            continue
        template = wire_template(step, guide.board)
        if template is None:
            continue
        face = (
            say("from the component side")
            if template.seen_from == "top"
            else say("from the solder side")
        )
        meta = say(
            "{length:.0f} mm · {colour} · AWG {awg}",
            length=step.cut.cut_mm,
            colour=escape(say(step.cut.colour)),
            awg=step.cut.awg,
        )
        turned = " · " + say("turned to fit the page") if template.turned else ""
        items.append(
            f'<div class="tpl"><div class="title">{escape(step.net_name)}: '
            f"{_hole(step.path[0], board=guide.board)} → {_hole(step.path[-1], board=guide.board)}</div>"
            f'<div class="meta">{meta} · {face}{turned}</div>'
            f"{_template_pair(template, step, step.cut, board=guide.board)}</div>"
        )
    if not items:
        return ""
    return (
        f'<section class="phase templates"><h2>{say("Wire templates (1:1)")}</h2><p>'
        + say(
            "Print these pages at 100 % — actual size, not fit to page — and hold the bar "
            "below against a ruler: if it is not {ruler} mm, the printer has scaled them. "
            "Cut each wire to the length of its straight drawing and mark it there: a dark "
            "mark is where the insulation is cut, a solid blue one where the wire goes down "
            "through the board, a dashed one where it turns along it. Then bend it to the "
            "shape beside, drawn as seen from the face the wire lies on.",
            ruler=RULER_MM,
        )
        + f'</p>{_ruler_svg()}<div class="tpl-grid">{"".join(items)}</div></section>'
    )


def _html_tables(guide: Guide, say: Phrasebook) -> str:
    parts = [f'<section class="phase"><h2>{say("Lists")}</h2>']

    parts.append(f'<h3>{say("Parts")}</h3><div class="wrap"><table>')
    parts.append(
        f"<tr><th>{say('Qty')}</th><th>{say('Value')}</th><th>{say('Package')}</th>"
        f"<th>{say('References')}</th></tr>"
    )
    for line in guide.bom:
        parts.append(
            f"<tr><td>{line.quantity}</td><td>{escape(line.value)}</td>"
            f"<td>{escape(line.footprint_name)}</td><td>{escape(line.refs)}</td></tr>"
        )
    parts.append("</table></div>")

    if guide.cut_list or guide.spine_list or guide.lead_list or guide.harness:
        parts.append(f'<h3>{say("Wire")}</h3><div class="wrap"><table>')
        parts.append(
            "<tr>"
            + "".join(
                f"<th>{say(column)}</th>"
                for column in WIRE_TABLE_COLUMNS
            )
            + "</tr>"
        )
        # One spelling per thing, and it is the CSV's: the two tables are the same list
        # and somebody comparing them should not have to work out that "bare" here and
        # "bare wire" there are one row. The gauge belongs under AWG and the material
        # under Colour -- a spine's "0.6 mm tinned copper" used to sit under Colour with
        # an em dash under AWG, so the column headings said the opposite of the cells.
        for cut in guide.cut_list:
            parts.append(
                f"<tr><td>{_wire_type(cut.insulated, say)}</td>"
                f"<td>{escape(cut.net_name)}</td><td>{_hole(cut.from_hole, board=guide.board)}</td>"
                f"<td>{_hole(cut.to_hole, board=guide.board)}</td><td>{cut.cut_mm:.0f} mm</td>"
                f"<td>{cut.awg}</td><td>{escape(say(cut.colour))}</td></tr>"
            )
        for lead in guide.lead_list:
            parts.append(_html_lead_row(lead, say, board=guide.board))
        for cable in guide.harness:
            for wire in cable.wires:
                length = say("cut to fit") if wire.cut_mm is None else f"{wire.cut_mm:.0f} mm"
                parts.append(
                    f"<tr><td>{say('cable wire')} ({escape(cable.ref)})</td>"
                    f"<td>{escape(wire.net_name)}</td><td>{escape(harness_end(wire.a, say))}</td>"
                    f"<td>{escape(harness_end(wire.b, say))}</td><td>{escape(length)}</td>"
                    f"<td>{wire.awg}</td><td>{escape(say(wire.colour))}</td></tr>"
                )
        for spine in guide.spine_list:
            parts.append(
                f"<tr><td>{say('reinforcing wire')}</td><td>{escape(spine.net_name)}</td>"
                f"<td colspan=2>{say('{pads} pads', pads=spine.pads)}</td>"
                f"<td>{spine.length_mm:.0f} mm</td>"
                f"<td>{spine.gauge_mm:g} mm</td><td>{escape(say(spine.material))}</td></tr>"
            )
        parts.append("</table></div>")

    parts.append("</section>")
    return "".join(parts)


__all__ = [
    "BOM_COLUMNS",
    "CUT_LIST_COLUMNS",
    "WIRE_TABLE_COLUMNS",
    "bom_to_csv",
    "cut_list_to_csv",
    "guide_to_html",
    "guide_to_json",
]

