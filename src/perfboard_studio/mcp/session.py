"""The board an agent is working on, and every operation it can perform on one.

This file is where the MCP tools actually live. ``server.py`` only binds them to the
protocol -- names, docstrings, transport -- so that everything below can be tested by
calling it, with no client, no stdio and no event loop. A test that needs a live MCP
session is testing the transport; the interesting failures are all here.

TWO RULES, both inherited rather than invented:

  EVERY MUTATION GOES THROUGH THE COMMAND BUS (PLAN.md Sec 8.1). Not one method here
  writes to a document. That is what makes undo work for an agent exactly as it works
  for the user, what puts the agent's edits in the same journal, and what lets the two
  drive the same board without one of them silently winning.

  EVERY RESULT IS PLAIN JSON-ABLE DATA. No dataclasses cross this boundary, no tuples of
  tuples, and every hole is given as its ADDRESS ("C7") because that is the language the
  rest of the tool, the DRC messages and the build guide all speak. An agent that has to
  convert between two hole encodings will eventually convert one of them wrongly.

A refused command comes back as ``{"ok": false, "code": ..., "message": ...}`` rather
than raising, matching ``CommandBus.dispatch``'s own contract. An agent needs to be able
to try something and be told no.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast, get_args

from perfboard_studio import persist
from perfboard_studio.autoroute import (
    AutorouteOptions,
    describe_reroute,
    plan_autoroute,
    plan_best_autoroute,
    plan_reroute,
)
from perfboard_studio.autoroute import describe as describe_route
from perfboard_studio.breadboard import (
    MAX_CHANNEL,
    PATTERN_TYPES,
    ROWS_WITH_RAILS,
    ROWS_WITHOUT_RAILS,
    channel_of,
    has_breadboard_pattern,
    has_rails,
    is_breadboard,
    pattern_board,
    rows_for,
)
from perfboard_studio.breadroute import plan_joined_board, plan_joined_reroute
from perfboard_studio.catalog import (
    CATEGORY_ORDER,
    CatalogCategory,
    CatalogPart,
    catalog_part,
    free_reference,
    search_catalog,
)
from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import (
    KEEP,
    AddBoardNotePayload,
    AddConductorPayload,
    AddCutPayload,
    AddEdgeConnectorPayload,
    AddMountingHolePayload,
    AddNetPayload,
    AddPartPayload,
    ConnectPinsPayload,
    DeleteBoardNotesPayload,
    DeleteComponentPayload,
    DeleteConductorsPayload,
    DeleteCutPayload,
    DeleteEdgeConnectorPayload,
    DeleteMountingHolePayload,
    DeleteNetPayload,
    DeletePartPayload,
    DisconnectPinsPayload,
    ImportNetlistPayload,
    MirrorComponentPayload,
    MoveComponentPayload,
    NewConductor,
    NewSolderTraceConductor,
    NewWireConductor,
    PartPlacement,
    PlaceBlockPayload,
    PlaceComponentPayload,
    PlacePartsPayload,
    RenameDocumentPayload,
    RotateComponentPayload,
    SetBoardPayload,
    SetBodyClearancePayload,
    SetHeightLimitPayload,
    UnplaceComponentPayload,
    UpdateComponentPayload,
    UpdateNetPayload,
    UpdatePartPayload,
    create_document_id_generator,
    create_empty_document,
    create_standard_registry,
    wire_side,
)
from perfboard_studio.connectivity import extract_physical_nets
from perfboard_studio.drc import run_drc
from perfboard_studio.erc import run_erc
from perfboard_studio.footprints import (
    GENERATED_ID_GRAMMAR,
    footprint_lookup,
    off_board_mount,
    standard_footprints,
)
from perfboard_studio.geometry import (
    all_pin_holes,
    consumed_holes,
    edge_connector_holes,
    format_hole,
    hole_key,
    legend_runs_text,
    pad_edge_gap_mm,
    parse_hole,
)
from perfboard_studio.guide import GuideOptions, build_guide
from perfboard_studio.guide import describe as describe_guide
from perfboard_studio.guide_export import bom_to_csv, cut_list_to_csv, guide_to_html, guide_to_json
from perfboard_studio.lvs import run_lvs, stale_conductor_ids
from perfboard_studio.model import (
    UNTITLED_NAME,
    Board,
    BoardEdge,
    BoardFace,
    BoardMaterial,
    BoardSide,
    BoardType,
    ComponentInstance,
    DocumentMeta,
    HoleCoord,
    NetClass,
    NetId,
    NetNode,
    PartSymbol,
    PerfDocument,
    PinNames,
    Rotation,
    SchematicPart,
    SpineSpec,
    pin_name_of,
)
from perfboard_studio.phrasebook import GUIDE_LANGUAGES
from perfboard_studio.placer import PlacementOptions, plan_placement
from perfboard_studio.placer import describe as describe_placement
from perfboard_studio.ratsnest import ratsnest, summarize
from perfboard_studio.router import (
    CROSSING_POLICIES,
    WIRE_PATHS,
    RouterOptions,
    RoutingStyle,
    options_for_style,
)
from perfboard_studio.step_export import Plate, board_model, model_to_step
from perfboard_studio.stripboard import board_joins_holes
from perfboard_studio.striproute import describe_plan as describe_strip_plan
from perfboard_studio.version import __version__

# ---------------------------------------------------------------------------
# Errors and results
# ---------------------------------------------------------------------------


class SessionError(Exception):
    """Bad input from the caller: a hole that will not parse, a ref that is not there.

    Distinct from a REFUSED command, which is a legitimate answer and comes back as
    data. This is "the request did not make sense", and the server turns it into an
    error the model can read.
    """


def _ok(**fields: Any) -> dict[str, Any]:
    return {"ok": True, **fields}


def _refused(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "message": message}


def _never_stopped() -> bool:
    """The stop a tool call hands the planner: an MCP call has no Cancel button."""
    return False


def _path_arg(path: str, tool: str) -> Path:
    """A filesystem path from an agent, expanded the way a shell would expand it.

    Two things a bare ``Path(path)`` gets wrong. ``~/board.perf`` is a literal directory
    called "~", so the file lands somewhere nobody can find; and ``""`` is ``Path(".")``,
    so the failure arrives as "Cannot open .: Permission denied" -- a message about the
    current directory, which is not what was asked for.
    """
    if not path.strip():
        raise SessionError(f"{tool} needs a path; none was given.")
    return Path(path).expanduser()


def _hole(ref: str, board: Board) -> HoleCoord:
    """Parse a hole address on this board, or say clearly what was wrong with it.

    On a breadboard the board's own names ("e12", "T+12") -- the ones every result about
    it is written in -- and the parser's refusal already says what they look like.
    """
    try:
        return parse_hole(ref, board)
    except Exception as err:
        if has_breadboard_pattern(board):
            raise SessionError(str(err)) from err
        raise SessionError(
            f"{ref!r} is not a hole address. They look like 'A1', 'C7' or 'AC12': "
            f"column letters then a 1-based row ({err})."
        ) from err


def _pin(spec: str) -> NetNode:
    """Parse ``"U1.8"`` into a net node, or say clearly what was wrong with it.

    Split from the RIGHT, because a reference may contain a dot and a pin number is the
    part after the last one.
    """
    ref, separator, pin = spec.strip().rpartition(".")
    if not separator or not ref or not pin:
        raise SessionError(
            f"{spec!r} is not a pin. They look like 'U1.8' or 'R3.1': the component's "
            f"reference, a dot, then the pin number."
        )
    return NetNode(component_ref=ref, pin=pin)


def _now_iso() -> str:
    """Timestamp for a new document's metadata.

    The only clock in the engine's world, and it lives here rather than in core on
    purpose: commands.py and persist.py are pure, and a clock inside them would make
    replay non-deterministic.
    """
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class _Snapshot:
    label: str
    document: PerfDocument


@dataclass
class BoardSession:
    """One board, its bus, and the snapshots an agent has taken of it.

    Deliberately a single board rather than a workspace of them. An agent working on two
    boards at once is not a thing anybody asked for, and the ambiguity of "which board
    did that tool mean" is a whole class of confusing failure avoided for free.
    """

    document: PerfDocument = field(
        default_factory=lambda: create_empty_document(
            DocumentMeta(name=UNTITLED_NAME, created=_now_iso(), modified=_now_iso())
        )
    )
    path: Path | None = None
    bus: CommandBus = field(init=False)
    snapshots: dict[str, _Snapshot] = field(default_factory=dict, init=False)
    _snapshot_counter: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.lookup = footprint_lookup()
        self._install(self.document)

    def _install(self, document: PerfDocument) -> None:
        """Point the session at a document, with a bus seeded from its own ids.

        Seeded, not fresh: a loaded document already contains cmp-1..cmp-8, and a
        generator starting at 1 would have its first edit refused as a duplicate id.
        """
        self.document = document
        self.bus = CommandBus(
            document,
            create_standard_registry(),
            CommandContext(next_id=create_document_id_generator(document)),
        )
        self.bus.subscribe(self._on_change)

    def _on_change(self, document: PerfDocument, _entry: Any) -> None:
        self.document = document

    # -- dispatch ----------------------------------------------------------

    def _dispatch(self, type_: str, payload: Any) -> dict[str, Any]:
        result = self.bus.dispatch(type_, payload)
        if not result.ok:
            return _refused(result.code or "refused", result.message or "Command refused.")
        return _ok(description=result.description, undo_depth=len(self.bus.history()))

    # -- reading -----------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Where the board is right now: counts, verification and the undo depth.

        The tool an agent should call first and after anything surprising, which is why
        it carries the DRC and LVS summaries rather than making that two more round
        trips.
        """
        erc = run_erc(self.document, self.lookup)
        drc = run_drc(self.document, self.lookup)
        lvs = run_lvs(self.document, self.lookup)
        remaining = summarize(ratsnest(self.document, self.lookup))
        return {
            "version": __version__,
            "document": self.document.meta.name,
            "path": str(self.path) if self.path else None,
            "board": f"{self.document.board.cols}x{self.document.board.rows} "
            f"{self.document.board.material}",
            "components": len(self.document.components),
            # Parts in the design and not on the board. Reported beside the components
            # rather than folded into them, because "the circuit is drawn and nothing is
            # placed" and "the board is empty" look identical from a component count and
            # call for opposite next moves.
            "parts_not_placed": len(self.document.parts),
            "conductors": len(self.document.conductors),
            "schematic_nets": len(self.document.nets),
            # The circuit's own check, before the board's: a design with nothing placed
            # has no DRC or LVS worth reading, and this is already the whole answer for it.
            "erc": {
                "errors": sum(1 for f in erc if f.severity == "error"),
                "warnings": sum(1 for f in erc if f.severity == "warning"),
            },
            "drc": {
                "errors": sum(1 for v in drc if v.severity == "error"),
                "warnings": sum(1 for v in drc if v.severity == "warning"),
            },
            "lvs": {
                "matched_nets": lvs.summary.matched_nets,
                "schematic_nets": lvs.summary.schematic_nets,
                "opens": lvs.summary.opens,
                "shorts": lvs.summary.shorts,
            },
            "unrouted_connections": remaining.links,
            "stale_conductors": len(stale_conductor_ids(self.document, self.lookup)),
            "undo_depth": len(self.bus.history()),
            # The last few entries, not the whole journal: an agent wants to know what
            # just happened, and a hundred-entry list in every status call is context
            # spent on nothing.
            "recent_history": list(self.bus.history()[-8:]),
            "snapshots": sorted(self.snapshots),
        }

    def get_board_info(self) -> dict[str, Any]:
        board = self.document.board
        info: dict[str, Any] = {
            "type": board.type,
            "cols": board.cols,
            "rows": board.rows,
            "pitch_mm": board.pitch,
            "thickness_mm": board.thickness,
            "material": board.material,
            "pad_shape": board.pad_shape,
            "pad_diameter_mm": board.pad_diameter,
            "drill_diameter_mm": board.drill_diameter,
            # Reported for both axes rather than as one figure, because on an oblong-pad
            # board they differ and the difference decides which way a solder trace should
            # run. An agent laying out a board needs to know that before it routes, not
            # after DRC tells it off.
            "pad_gap_along_row_mm": round(pad_edge_gap_mm(board, "horizontal"), 3),
            "pad_gap_down_column_mm": round(pad_edge_gap_mm(board, "vertical"), 3),
            "top_left_hole": format_hole(HoleCoord(0, 0), board),
            "bottom_right_hole": format_hole(HoleCoord(board.cols - 1, board.rows - 1), board),
        }
        if has_breadboard_pattern(board):
            # Row e to row f, where the channel is widest; and the columns that keep the
            # ordinary one, when a wide channel narrows. An agent placing a module across
            # the channel needs both before it places, not from a no-hole finding after.
            info["channel_mil"] = channel_of(board) * 100
            info["rails"] = has_rails(board)
            if board.narrow_channel_cols:
                info["narrow_channel_cols"] = board.narrow_channel_cols
        if board.pad_shape == "oblong":
            info["pad_length_mm"] = board.pad_length
            info["pad_axis"] = board.pad_axis
        if board.labels is not None:
            legend: dict[str, Any] = {
                "face": board.labels.face,
                "row_digits": board.labels.row_digits,
            }
            # What the board prints when it counts in its own way (A..Z then A..P
            # again). Said so an agent can tell a person what to look for; every address
            # in and out of this server is still the tool's own.
            for axis, printed in (
                ("columns", board.labels.columns),
                ("rows", board.labels.rows),
            ):
                if printed is not None:
                    legend[axis] = {
                        "printed": legend_runs_text(printed.runs),
                        "every": printed.every,
                        "digits": printed.digits,
                    }
            info["printed_legend"] = legend
        if self.document.mounting_holes:
            info["mounting_holes"] = [
                {
                    "id": mount.id,
                    "at": format_hole(mount.at, board),
                    "diameter_mm": mount.diameter,
                    "head_diameter_mm": mount.head_diameter,
                }
                for mount in self.document.mounting_holes
            ]
            # The pads a bore has taken out. An agent that cannot see this places a part
            # on a hole with no copper and only finds out from DRC.
            consumed = consumed_holes(self.document)
            info["holes_without_pads"] = sorted(
                format_hole(HoleCoord(col, row), board)
                for col in range(board.cols)
                for row in range(board.rows)
                if hole_key(HoleCoord(col, row)) in consumed
            )
        if self.document.board_notes:
            info["labels"] = [
                {
                    "id": note.id,
                    "text": note.text,
                    "at": format_hole(note.at, board),
                    **(
                        {"offset_mm": [note.offset_x_mm, note.offset_y_mm]}
                        if note.offset_x_mm or note.offset_y_mm
                        else {}
                    ),
                    **({"side": note.side} if note.side != "top" else {}),
                }
                for note in self.document.board_notes
            ]
        if self.document.edge_connectors:
            info["edge_connectors"] = [
                {
                    "id": connector.id,
                    "edge": connector.edge,
                    "holes": [
                        format_hole(hole, board)
                        for hole in edge_connector_holes(connector, board)
                    ],
                    "face": connector.face,
                }
                for connector in self.document.edge_connectors
            ]
        if self.document.conductors:
            # The copper, by id, which is what delete_conductors takes: before this the
            # only place an id appeared was a net's islands, and a wire joining no pin
            # appeared nowhere at all.
            names = {net.id: net.name for net in self.document.nets}
            info["conductors"] = [
                {
                    "id": conductor.id,
                    "kind": conductor.kind,
                    **(
                        {"net": names.get(conductor.net_id, conductor.net_id)}
                        if conductor.net_id is not None
                        else {}
                    ),
                    "side": conductor.side,
                    "path": [format_hole(hole, board) for hole in conductor.path],
                }
                for conductor in self.document.conductors
            ]
        if self.document.height_limit_mm is not None:
            info["height_limit_mm"] = self.document.height_limit_mm
        if self.document.body_clearance_mm is not None:
            info["body_clearance_mm"] = self.document.body_clearance_mm
        return info

    def check_heights(self) -> dict[str, Any]:
        """How tall the build stands, and what does not fit under the declared limit.

        Separate from ``run_drc`` because it answers a question rather than reporting a
        fault: an agent choosing an enclosure needs the tallest part whether or not any
        limit has been set, and with no limit set the height rule is silent by design.
        """
        parts: list[dict[str, Any]] = []
        unknown: list[str] = []
        for component in self.document.components:
            footprint = self.lookup(component.footprint_id)
            if footprint is None:
                unknown.append(component.ref)
                continue
            parts.append(
                {
                    "ref": component.ref,
                    "at": format_hole(component.anchor, self.document.board),
                    "height_mm": footprint.body_height,
                    "archetype": footprint.body.archetype,
                }
            )
        # Tallest first: the answer to "what decides the case height" is the first row.
        parts.sort(key=lambda p: (-float(p["height_mm"]), str(p["ref"])))

        limit = self.document.height_limit_mm
        over = [p["ref"] for p in parts if limit is not None and float(p["height_mm"]) > limit]
        return {
            "height_limit_mm": limit,
            "tallest_mm": parts[0]["height_mm"] if parts else 0,
            "tallest_ref": parts[0]["ref"] if parts else None,
            "over_limit": over,
            "parts": parts,
            # Named rather than silently omitted: a part whose footprint is unknown has
            # no height, and an agent must not read "nothing is too tall" as "everything
            # was measured".
            "unknown_footprints": sorted(unknown),
        }

    def list_components(self) -> list[dict[str, Any]]:
        return [self._component_summary(c) for c in self.document.components]

    def _component_summary(self, component: ComponentInstance) -> dict[str, Any]:
        footprint = self.lookup(component.footprint_id)
        return {
            "ref": component.ref,
            "value": component.value,
            "footprint_id": component.footprint_id,
            "footprint_known": footprint is not None,
            "anchor": format_hole(component.anchor, self.document.board),
            "rotation": component.rotation,
            "mirrored": component.mirrored,
            "locked": component.locked,
            # Only when declared, like the file: a summary of forty parts that said
            # "symbol: null" forty times would bury the one that says "pmos".
            **({"symbol": component.symbol} if component.symbol is not None else {}),
            **({"note": component.note} if component.note else {}),
        }

    def get_component(self, ref: str) -> dict[str, Any]:
        component = self._require_component(ref)
        summary = self._component_summary(component)
        footprint = self.lookup(component.footprint_id)
        if footprint is not None:
            summary["footprint_name"] = footprint.name
            summary["body_height_mm"] = footprint.body_height
            summary["polarized"] = footprint.polarized
            # The name the PART gives each lead, over the footprint's: a declared "GPIO21"
            # is what an agent wiring a module needs to read back, not "21".
            summary["pins"] = [
                {"pin": pin.number, "name": pin_name_of(component, pin), "hole": format_hole(at, self.document.board)}
                for pin, at in all_pin_holes(component, footprint)
            ]
        return summary

    def get_nets(self) -> list[dict[str, Any]]:
        """The SCHEMATIC's nets -- what the circuit is supposed to connect.

        What the board actually connects is a different question, answered by
        ``get_net_connections``. Keeping the two apart is the whole basis of LVS.
        """
        return [
            {
                "id": net.id,
                "name": net.name,
                "net_class": net.net_class,
                "pins": [f"{node.component_ref}.{node.pin}" for node in net.nodes],
                "current_a": net.current_a,
                "voltage_v": net.voltage_v,
            }
            for net in self.document.nets
        ]

    def get_net_connections(self, name: str) -> dict[str, Any]:
        """What the BOARD joins for one schematic net, and what it still does not."""
        net = next((n for n in self.document.nets if n.name == name or n.id == name), None)
        if net is None:
            raise SessionError(
                f"No net called {name!r}. Known nets: "
                f"{', '.join(n.name for n in self.document.nets) or '(none imported)'}."
            )

        physical = extract_physical_nets(self.document, self.lookup)
        wanted = {(node.component_ref, node.pin) for node in net.nodes}
        groups: list[dict[str, Any]] = []
        for island in physical:
            members = [p for p in island.pins if (p.component_ref, p.pin) in wanted]
            if members:
                groups.append(
                    {
                        "pins": [f"{p.component_ref}.{p.pin}" for p in members],
                        "conductors": list(island.conductor_ids),
                    }
                )

        entry = next(
            (n for n in ratsnest(self.document, self.lookup) if n.net_id == net.id), None
        )
        return {
            "net": net.name,
            "net_class": net.net_class,
            "declared_pins": sorted(f"{ref}.{pin}" for ref, pin in wanted),
            "physical_groups": groups,
            "connected": len(groups) <= 1 and bool(groups),
            "remaining_connections": [
                {
                    "from": format_hole(link.from_, self.document.board),
                    "to": format_hole(link.to, self.document.board),
                    "length_mm": round(link.length_mm, 2),
                }
                for link in (entry.links if entry is not None else ())
            ],
        }

    def list_catalog(self, search: str = "", category: str = "") -> list[dict[str, Any]]:
        """Real parts by name, each already described: package, pin names, symbol, value.

        What ``list_footprints`` cannot say. A TO-92 is a package; a BC547 is a part, and
        which of its legs is the base is the fact the board depends on. Placing one with
        ``place_component(part=...)`` fills all of that in.
        """
        if category and category not in CATEGORY_ORDER:
            raise SessionError(
                f"{category!r} is not a catalog category. They are: {', '.join(CATEGORY_ORDER)}."
            )
        chosen: CatalogCategory | None = category if category else None
        return [_catalog_summary(part) for part in search_catalog(search, chosen)]

    def _from_catalog(
        self,
        part: str,
        ref: str,
        footprint_id: str,
        value: str,
        pin_names: dict[str, str] | None,
        symbol: str | None,
    ) -> tuple[str, str, str, PinNames, str | None]:
        """A catalog part's description, under anything the caller said explicitly.

        Explicit wins, field by field: ``part="bc547", value="BC547B"`` is a BC547 with a
        more exact value on the bill. An empty ``ref`` takes the part's letter and the next
        free number.
        """
        names = _pin_names_arg(pin_names)
        if not part:
            return ref, footprint_id, value, names or (), symbol
        entry: CatalogPart | None = catalog_part(part)
        if entry is None:
            raise SessionError(f"{part!r} is not in the catalog. list_catalog lists what is.")
        return (
            ref.strip() or free_reference(self.document, entry.reference_prefix),
            footprint_id or entry.footprint_id,
            value or entry.placed_value,
            names if names is not None else entry.pin_names,
            symbol or entry.symbol,
        )

    def list_footprints(self, search: str = "") -> list[dict[str, Any]]:
        """The parts library. Free text matches the id, the name or the body type."""
        needle = search.strip().lower()
        out: list[dict[str, Any]] = []
        for footprint in standard_footprints().values():
            haystack = f"{footprint.id} {footprint.name} {footprint.body.archetype}".lower()
            if needle and needle not in haystack:
                continue
            out.append(
                {
                    "id": footprint.id,
                    "name": footprint.name,
                    "archetype": footprint.body.archetype,
                    "pins": len(footprint.pins),
                    "height_mm": footprint.body_height,
                    "polarized": footprint.polarized,
                }
            )
        out.sort(key=lambda entry: str(entry["id"]))
        return out

    # -- documents ---------------------------------------------------------

    def open_document(self, path: str) -> dict[str, Any]:
        target = _path_arg(path, "open_document")
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as err:
            raise SessionError(f"Cannot open {target}: {err.strerror or err}.") from err
        result = persist.deserialize_document(text)
        if not result.ok:
            return _refused(result.code or "parse-error", result.message or "Unreadable document.")
        self.path = target
        self._install(result.document)
        self.snapshots.clear()
        return _ok(
            opened=str(target),
            warnings=list(result.warnings),
            status=self.get_status(),
        )

    def save_document(self, path: str | None = None, name: str | None = None) -> dict[str, Any]:
        """Write the board, naming it first if it has no name of its own.

        ``name`` renames it explicitly. Without one, a board still called
        ``UNTITLED_NAME`` takes its file's name -- the rule the window follows too, so a
        board saved as ``relay-driver.perf`` has a guide titled "relay-driver" rather than
        "untitled" whichever of the two saved it. Either way the rename is a command, so it
        is on the undo stack like any other edit.
        """
        target = _path_arg(path, "save_document") if path else self.path
        if target is None:
            raise SessionError(
                "This board has never been saved, so save_document needs a path."
            )
        wanted = name.strip() if name is not None and name.strip() else None
        if wanted is None and self.document.meta.name == UNTITLED_NAME:
            wanted = target.stem
        if wanted is not None and wanted != self.document.meta.name:
            renamed = self._dispatch("document.rename", RenameDocumentPayload(name=wanted))
            if not renamed["ok"]:
                return renamed
        stamped = dataclasses.replace(
            self.document,
            meta=dataclasses.replace(self.document.meta, modified=_now_iso()),
        )
        try:
            target.write_text(persist.serialize_document(stamped), encoding="utf-8")
        except OSError as err:
            raise SessionError(f"Cannot write {target}: {err.strerror or err}.") from err
        self.path = target
        return _ok(saved=str(target), bytes=target.stat().st_size, name=self.document.meta.name)

    def import_netlist(self, path: str, place_missing: bool = False) -> dict[str, Any]:
        """Replace the netlist with a KiCad one.

        Each component is read for what it is (``parsers.kicad_parts``): the catalog part
        its value names, the footprint its KiCad footprint names, or a guess from its
        reference. Its pins are renumbered where the schematic's symbol numbers them
        differently from the real part -- KiCad's LED, a generic EBC transistor -- and
        ``notes`` says where. ``suggested_parts`` is what would be placed for each part in
        neither the board nor the design; ``place_missing`` places them, beside what they
        connect to, as one undo step.
        """
        from perfboard_studio.netlist_import import import_placements
        from perfboard_studio.parsers.kicad import parse_kicad_netlist
        from perfboard_studio.parsers.kicad_parts import plan_import

        target = _path_arg(path, "import_netlist")
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as err:
            raise SessionError(f"Cannot open {target}: {err.strerror or err}.") from err
        try:
            imported = parse_kicad_netlist(text)
        except ValueError as err:
            return _refused("parse-error", f"{target.name}: {err}")

        plan = plan_import(imported, self.document, self.lookup)
        result = self._dispatch("netlist.import", ImportNetlistPayload(nets=plan.nets))
        if not result["ok"]:
            return result
        result["nets"] = len(imported.nets)
        result["warnings"] = list(imported.warnings)
        if plan.notes:
            result["notes"] = {ref: list(lines) for ref, lines in sorted(plan.notes.items())}
        suggestions = sorted(plan.suggestions.values(), key=lambda s: s.ref)
        result["suggested_parts"] = [
            {
                "ref": s.ref,
                "footprint": s.footprint_id,
                "value": s.value,
                "from": s.source,
                **({"part": s.part_id} if s.part_id else {}),
                **({"pin_names": dict(s.pin_names)} if s.pin_names else {}),
            }
            for s in suggestions
        ]
        if place_missing and suggestions:
            placements, left_out = import_placements(suggestions, self.document, self.lookup)
            if placements:
                placed = self._dispatch(
                    "block.place",
                    PlaceBlockPayload(
                        components=tuple(placements),
                        label=f"Place {len(placements)} imported part(s)",
                    ),
                )
                if not placed["ok"]:
                    result["place_missing"] = placed
                    return result
            result["placed"] = [
                {"ref": p.ref, "at": format_hole(p.anchor, self.document.board), "rotation": p.rotation}
                for p in placements
            ]
            if left_out:
                result["not_placed"] = left_out
        on_board = {c.ref for c in self.document.components}
        result["missing_components"] = sorted(
            {node.component_ref for net in plan.nets for node in net.nodes} - on_board
        )
        return result

    # -- the netlist, without KiCad ------------------------------------------
    #
    # ``import_netlist`` above replaces the whole netlist, which is what re-exporting a
    # schematic means. These five edit it. They exist because a netlist was previously the
    # one thing an agent could not produce -- it could place parts, draw copper and route,
    # but the intent those are measured against had to come from a file somebody exported
    # from KiCad, so on a board that never had a schematic there was nothing to route.

    def create_net(
        self,
        name: str,
        net_class: str = "signal",
        pins: list[str] | None = None,
        current_a: float | None = None,
        voltage_v: float | None = None,
    ) -> dict[str, Any]:
        """Declare a net. ``pins`` are ``"U1.8"`` addresses and may be given later."""
        nodes = tuple(_pin(spec) for spec in (pins or []))
        result = self._dispatch(
            "net.add",
            AddNetPayload(
                name=name,
                net_class=cast(NetClass, net_class),
                nodes=nodes,
                current_a=current_a,
                voltage_v=voltage_v,
            ),
        )
        if result["ok"]:
            result["unplaced_pins"] = self._unplaced(nodes)
        return result

    def update_net(
        self,
        name: str,
        new_name: str | None = None,
        net_class: str | None = None,
        current_a: float | None = None,
        voltage_v: float | None = None,
        clear_current: bool = False,
        clear_voltage: bool = False,
    ) -> dict[str, Any]:
        """Rename a net, reclassify it, or state what it carries.

        A field left out is left ALONE. ``current_a: null`` therefore means "this call
        says nothing about the current", never "erase what the net declares" -- an agent
        that omits a field has not asked for it to be destroyed. Erasing is explicit, via
        ``clear_current`` / ``clear_voltage``.

        The two numbers matter more than they look: DRC's current-capacity rule, its
        creepage rule and the wire gauge on the build guide's cut list are all silent
        until a net declares them, and no netlist format carries them.
        """
        return self._dispatch(
            "net.update",
            UpdateNetPayload(
                id=self._net_id_strict(name),
                name=new_name,
                net_class=cast(NetClass, net_class) if net_class is not None else None,
                current_a=None if clear_current else (KEEP if current_a is None else current_a),
                voltage_v=None if clear_voltage else (KEEP if voltage_v is None else voltage_v),
            ),
        )

    def delete_net(self, name: str) -> dict[str, Any]:
        """Forget a net. Copper already laid for it stays on the board, and stops being
        anything ``reroute`` or ``remove_stale_conductors`` will touch."""
        return self._dispatch("net.delete", DeleteNetPayload(id=self._net_id_strict(name)))

    def connect_pins(self, net: str, pins: list[str]) -> dict[str, Any]:
        """Add pins to a net, as one undo step. ``pins`` are ``"U1.8"`` addresses."""
        nodes = tuple(_pin(spec) for spec in pins)
        result = self._dispatch(
            "net.connect", ConnectPinsPayload(id=self._net_id_strict(net), nodes=nodes)
        )
        if result["ok"]:
            result["unplaced_pins"] = self._unplaced(nodes)
        return result

    def disconnect_pins(self, net: str, pins: list[str]) -> dict[str, Any]:
        """Take pins off a net, as one undo step."""
        return self._dispatch(
            "net.disconnect",
            DisconnectPinsPayload(
                id=self._net_id_strict(net), nodes=tuple(_pin(spec) for spec in pins)
            ),
        )

    # -- the design, before the board ----------------------------------------
    #
    # THE ORDER EVERY OTHER EDA TOOL WORKS IN, and the one an agent could not follow here:
    # every route a part had into a document ended in ``place_component``, which needs a
    # hole. So an agent asked to "design a 555 astable" had to invent a layout before it
    # had finished inventing the circuit, and then live with it -- or place everything in
    # a corner and move it afterwards, which is the same thing with extra steps.
    #
    # Now: ``add_part`` for each part, ``connect_pins`` to wire them (which never required
    # a part to be on the board), ``place_parts`` when the circuit is settled, and
    # ``optimize_placement`` to arrange it.

    def add_part(
        self,
        ref: str,
        footprint_id: str,
        value: str = "",
        pin_names: dict[str, str] | None = None,
        symbol: str | None = None,
        part: str = "",
    ) -> dict[str, Any]:
        """Put a part in the DESIGN without deciding where on the board it goes.

        The footprint is asked for now rather than at placement because everything else
        needs it: the symbol this part is drawn as is derived from it, and so are its pins,
        its 3D body and its line in the bill of materials.

        ``pin_names`` and ``symbol`` are what the part says about itself that its package
        cannot -- see ``model.PartSymbol``. Both are optional and both travel with the part
        when it is placed. ``part`` is a catalog id (``list_catalog``) that fills in the
        footprint, value, names and symbol, under anything given explicitly.
        """
        ref, footprint_id, value, names, symbol = self._from_catalog(
            part, ref, footprint_id, value, pin_names, symbol
        )
        if self.lookup(footprint_id) is None:
            raise _no_such_footprint(footprint_id)
        return self._dispatch(
            "part.add",
            AddPartPayload(
                ref=ref,
                footprint_id=footprint_id,
                value=value,
                pin_names=names,
                symbol=cast(PartSymbol | None, symbol or None),
            ),
        )

    def update_part(
        self,
        ref: str,
        new_ref: str | None = None,
        value: str | None = None,
        footprint_id: str | None = None,
        pin_names: dict[str, str] | None = None,
        symbol: str | None = None,
        off_board: bool = False,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Rename a part, or change what it is. Omitted fields are left alone.

        A rename CARRIES THE WIRING: a reference is the only name a net has for a part, so
        renaming the part renames what the net points at. It is refused if that would put
        one pin on two nets.

        ``pin_names`` REPLACES the part's names whole (``{}`` clears them); ``symbol`` of
        ``""`` clears a declaration, since an omitted argument already means "leave it".
        ``note`` is the builder's own reason for the part, on the board or not; ``""``
        clears it. A locked part takes one: the lock is about where it is.

        It reaches a part ON THE BOARD as well -- which is how a placed part's VALUE is
        set, ``update_part("R1", value="4k7")``, so there is no separate tool for it. Naming
        the pins of a module is something
        done after it has been placed as often as before, and "unplace it, rename its pins,
        place it back" would lose its lead bends for no reason. Only the footprint of a
        placed part is out of reach: changing the package under a part soldered into holes
        is a different edit from renaming it, and it stays with ``unplace_component``.

        ``off_board`` is the one exception, and it is the window's Mount on the Panel: the
        part goes off the board and is wired to it (``footprints.off_board_mount``), its
        footprint becoming the pads its wires land in -- where its pins were, when they were
        one row -- and its package's pin names and symbol becoming its own. Explicit
        ``pin_names`` and ``symbol`` still win over what it keeps.
        """
        if footprint_id is not None and self.lookup(footprint_id) is None:
            raise _no_such_footprint(footprint_id)
        symbol_arg = KEEP if symbol is None else cast(PartSymbol | None, symbol or None)
        names_arg = _pin_names_arg(pin_names)
        placed = next((c for c in self.document.components if c.ref == ref), None)
        if off_board:
            if footprint_id is not None:
                raise SessionError(
                    "off_board chooses the footprint itself: the pads the wires land in. Give "
                    "one or the other."
                )
            current = placed if placed is not None else self._require_part(ref)
            package = self.lookup(current.footprint_id)
            if package is None:
                raise _no_such_footprint(current.footprint_id)
            try:
                moved = off_board_mount(current, package)
            except ValueError as error:
                raise SessionError(str(error)) from error
            footprint_id = moved.footprint_id
            names_arg = moved.pin_names if names_arg is None else names_arg
            symbol_arg = moved.symbol if symbol_arg is KEEP else symbol_arg
        if placed is not None:
            if footprint_id is not None and not off_board:
                raise SessionError(
                    f"{ref} is on the board, and its footprint is what its holes were chosen "
                    f"for. unplace_component takes it off; change the footprint there."
                )
            return self._dispatch(
                "component.update",
                UpdateComponentPayload(
                    id=placed.id,
                    ref=new_ref,
                    value=value,
                    pin_names=names_arg,
                    symbol=symbol_arg,
                    note=note,
                    footprint_id=footprint_id,
                ),
            )
        return self._dispatch(
            "part.update",
            UpdatePartPayload(
                id=self._require_part(ref).id,
                ref=new_ref,
                value=value,
                footprint_id=footprint_id,
                pin_names=names_arg,
                symbol=symbol_arg,
                note=note,
            ),
        )

    def delete_part(self, ref: str) -> dict[str, Any]:
        """Take a part out of the design, ALONG WITH its connections.

        Different from ``delete_component``, which takes a part off the board and leaves
        the schematic still asking for it — an open LVS reports. This says the design does
        not have the part, so a net still naming its pins would be asking for something
        nothing in the document has heard of.
        """
        return self._dispatch("part.delete", DeletePartPayload(id=self._require_part(ref).id))

    def place_parts(self, placements: list[dict[str, Any]]) -> dict[str, Any]:
        """Move parts from the design onto the board, all as ONE undo step.

        Each placement is ``{"ref": "R1", "at": "C7", "rotation": 90}``; rotation is
        optional and defaults to 0, and ``"mirrored": true`` puts the part on the solder
        side. One command however many parts, because laying out a
        drawn circuit is one decision — dispatched one at a time it takes one undo press
        per part, each leaving a board that is half laid out.
        """
        if not placements:
            raise SessionError("place_parts needs at least one placement.")
        specs: list[PartPlacement] = []
        for entry in placements:
            ref = entry.get("ref")
            at = entry.get("at")
            if not isinstance(ref, str) or not isinstance(at, str):
                raise SessionError(
                    'Each placement needs a "ref" and an "at", e.g. {"ref": "R1", "at": "C7"}.'
                )
            specs.append(
                PartPlacement(
                    id=self._require_part(ref).id,
                    anchor=_hole(at, self.document.board),
                    rotation=_rotation(int(entry.get("rotation", 0))),
                    mirrored=_mirrored(entry.get("mirrored", False)),
                )
            )
        return self._dispatch("part.place", PlacePartsPayload(placements=tuple(specs)))

    def unplace_component(self, ref: str) -> dict[str, Any]:
        """Take a part off the board and keep it in the design, wiring intact.

        The inverse of ``place_parts``, and what to reach for instead of
        ``delete_component`` when the part belongs in the circuit and not in that hole.
        """
        return self._dispatch(
            "component.unplace", UnplaceComponentPayload(id=self._require_component(ref).id)
        )

    def list_parts(self) -> dict[str, Any]:
        """Every part in the design that is not on the board yet."""
        return {
            "ok": True,
            "parts": [
                {
                    "ref": part.ref,
                    "value": part.value,
                    "footprint": part.footprint_id,
                    "pins": [pin.number for pin in footprint.pins] if footprint else [],
                    # Declared names and symbol, only when there are any -- see
                    # ``_component_summary`` for why they are not printed empty.
                    **({"pin_names": dict(part.pin_names)} if part.pin_names else {}),
                    **({"symbol": part.symbol} if part.symbol is not None else {}),
                    **({"note": part.note} if part.note else {}),
                }
                for part in self.document.parts
                for footprint in (self.lookup(part.footprint_id),)
            ],
        }

    def _require_part(self, ref: str) -> SchematicPart:
        for part in self.document.parts:
            if part.ref == ref:
                return part
        known = ", ".join(p.ref for p in self.document.parts) or "(nothing is waiting)"
        on_board = any(c.ref == ref for c in self.document.components)
        extra = (
            f" {ref} IS on the board; unplace_component takes it off." if on_board else ""
        )
        raise SessionError(f"No part called {ref!r} in the design. Waiting: {known}.{extra}")

    def _unplaced(self, nodes: tuple[NetNode, ...]) -> list[str]:
        """Which of these pins name a part that is not on the board yet.

        Reported rather than refused, because declaring the netlist first and placing what
        it asks for afterwards is a real order of work -- it is what importing a netlist
        does. But an agent that meant to write "U1.8" and wrote "U11.8" needs to hear
        about it now rather than from LVS at the end.
        """
        placed = {c.ref for c in self.document.components}
        return sorted({node.component_ref for node in nodes if node.component_ref not in placed})

    # -- editing -----------------------------------------------------------

    def set_height_limit(self, height_limit_mm: float | None) -> dict[str, Any]:
        return self._dispatch(
            "height-limit.set", SetHeightLimitPayload(height_limit_mm=height_limit_mm)
        )

    def set_body_clearance(self, body_clearance_mm: float | None) -> dict[str, Any]:
        return self._dispatch(
            "body-clearance.set", SetBodyClearancePayload(body_clearance_mm=body_clearance_mm)
        )

    # -- the board itself, and the things that are part of it ----------------
    #
    # An agent could place parts on a board and could not change the board: the only way
    # to a different size, a different material or a stripboard was new_document, which
    # throws the work away. And a mounting hole or an edge connector could be READ back
    # (get_board_info reports both) with no way to add one, which is the kind of asymmetry
    # that reads as a broken tool rather than a missing one.

    def set_board(
        self,
        cols: int | None = None,
        rows: int | None = None,
        material: str | None = None,
        board_type: str | None = None,
        strip_axis: str | None = None,
        pitch: float | None = None,
        single_sided: bool | None = None,
        channel_mil: int | None = None,
        narrow_channel_cols: int | None = None,
    ) -> dict[str, Any]:
        """Change the board under the design. Anything left out is left alone.

        Shrinking a board that still has a part hanging off the new edge comes back as a
        refusal naming the part, because ``board.set`` checks it -- the same answer the
        window gets from the same command.

        ``channel_mil`` is a breadboard's channel, row e to row f: 300 is the ordinary one,
        and a wide one is one more row of grid per 100 mil (``breadboard.channel_of``), so
        it sets ``rows``, keeping the rails the board has (or ``rows`` says, as 20 or 12).
        ``narrow_channel_cols`` keeps the ordinary channel for that many columns from
        column 1. ``board.set`` judges both, through ``breadboard.board_problem``.
        """
        board = self.document.board
        if board_type is not None and board_type not in get_args(BoardType):
            raise SessionError(
                f"{board_type!r} is not a board type. Use one of: "
                f"{', '.join(get_args(BoardType))}."
            )
        if material is not None and material not in get_args(BoardMaterial):
            raise SessionError(
                f"{material!r} is not a board material. Use one of: "
                f"{', '.join(get_args(BoardMaterial))}."
            )
        if strip_axis is not None and strip_axis not in ("horizontal", "vertical"):
            raise SessionError(
                f"{strip_axis!r} is not a strip axis. Use 'horizontal' or 'vertical'."
            )
        wanted_type = cast(BoardType, board_type) if board_type is not None else board.type
        if channel_mil is not None:
            if wanted_type not in PATTERN_TYPES:
                raise SessionError("Only a breadboard has a channel; set board_type to one first.")
            if channel_mil % 100 or not 300 <= channel_mil <= MAX_CHANNEL * 100:
                raise SessionError(
                    f"{channel_mil} mil is not a channel: it is a whole number of pitches, "
                    f"300 to {MAX_CHANNEL * 100} mil in steps of 100."
                )
            if rows in (ROWS_WITH_RAILS, ROWS_WITHOUT_RAILS):
                rails = rows == ROWS_WITH_RAILS
            else:
                rails = has_rails(board) or not has_breadboard_pattern(board)
            try:
                rows = rows_for(channel_mil // 100, rails)
            except ValueError as exc:
                raise SessionError(str(exc)) from exc
        narrow = board.narrow_channel_cols if narrow_channel_cols is None else narrow_channel_cols
        if wanted_type not in PATTERN_TYPES:
            narrow = 0  # Only a breadboard has a channel to narrow.
        if wanted_type in PATTERN_TYPES and wanted_type != board.type:
            # A breadboard's thickness, drill and border follow its KIND, and turning one
            # kind into the other changes them all (breadboard.pattern_board) -- a board
            # keeping the plastic's 8.5 mm as copper would be drawn and exported as a slab.
            return self._dispatch(
                "board.set",
                SetBoardPayload(
                    board=pattern_board(
                        wanted_type,
                        cols if cols is not None else board.cols,
                        rows if rows is not None else board.rows,
                        narrow,
                    )
                ),
            )
        updated = dataclasses.replace(
            board,
            type=wanted_type,
            cols=cols if cols is not None else board.cols,
            rows=rows if rows is not None else board.rows,
            material=cast(BoardMaterial, material) if material is not None else board.material,
            pitch=pitch if pitch is not None else board.pitch,
            single_sided=single_sided if single_sided is not None else board.single_sided,
            narrow_channel_cols=narrow,
            # Only a stripboard has an axis, the way only an oblong pad has a length: a
            # field describing nothing does not belong in the file.
            strip_axis=(
                cast(Literal["horizontal", "vertical"], strip_axis)
                if strip_axis is not None and wanted_type == "stripboard"
                else (board.strip_axis if wanted_type == "stripboard" else None)
            ),
        )
        return self._dispatch("board.set", SetBoardPayload(board=updated))

    def add_mounting_hole(
        self, hole: str, diameter: float = 3.2, head_diameter: float = 6.0
    ) -> dict[str, Any]:
        """Drill a screw hole. It removes the copper from the pads it lands on."""
        return self._dispatch(
            "mounting-hole.add",
            AddMountingHolePayload(
                at=_hole(hole, self.document.board), diameter=diameter, head_diameter=head_diameter
            ),
        )

    def add_edge_connector(
        self,
        edge: str,
        start: int,
        count: int,
        finger_width: float = 2.0,
        face: str = "bottom",
    ) -> dict[str, Any]:
        """Replace a run of grid pads along one edge with connector fingers."""
        if edge not in get_args(BoardEdge):
            raise SessionError(
                f"{edge!r} is not a board edge. Use one of: {', '.join(get_args(BoardEdge))}."
            )
        if face not in ("top", "bottom"):
            raise SessionError(f"{face!r} is not a face. Use 'top' or 'bottom'.")
        return self._dispatch(
            "edge-connector.add",
            AddEdgeConnectorPayload(
                edge=cast(BoardEdge, edge),
                start=start,
                count=count,
                finger_width=finger_width,
                face=cast(BoardFace, face),
            ),
        )

    def cut_track(self, hole: str) -> dict[str, Any]:
        """Break a stripboard track at a hole. The cut takes that hole's pad with it."""
        return self._dispatch("cut.add", AddCutPayload(at=_hole(hole, self.document.board)))

    def add_board_label(
        self,
        text: str,
        hole: str,
        offset_x_mm: float = 0.0,
        offset_y_mm: float = 0.0,
        size_mm: float = 1.5,
        rotation: int = 0,
        side: str = "top",
    ) -> dict[str, Any]:
        """Write something on the board: centred on a hole, or millimetres off it."""
        if side not in ("top", "bottom"):
            raise SessionError('side is "top" or "bottom".')
        return self._dispatch(
            "board.note.add",
            AddBoardNotePayload(
                text=text,
                at=_hole(hole, self.document.board),
                offset_x_mm=offset_x_mm,
                offset_y_mm=offset_y_mm,
                size_mm=size_mm,
                rotation=_rotation(rotation),
                side=cast(BoardSide, side),
            ),
        )

    def remove_board_feature(self, id: str) -> dict[str, Any]:
        """Take back a mounting hole, an edge connector, a track cut or a label, by its id.

        One tool rather than three, because the three deletes differ only in which list
        the id is in -- and an agent that has just been handed an id by
        ``get_board_info`` should not have to work out which kind of thing it named.
        """
        if any(mount.id == id for mount in self.document.mounting_holes):
            return self._dispatch("mounting-hole.delete", DeleteMountingHolePayload(id=id))
        if any(connector.id == id for connector in self.document.edge_connectors):
            return self._dispatch("edge-connector.delete", DeleteEdgeConnectorPayload(id=id))
        if any(cut.id == id for cut in self.document.cuts):
            return self._dispatch("cut.delete", DeleteCutPayload(id=id))
        if any(note.id == id for note in self.document.board_notes):
            return self._dispatch("board.note.delete", DeleteBoardNotesPayload(ids=(id,)))
        known = [
            *(m.id for m in self.document.mounting_holes),
            *(c.id for c in self.document.edge_connectors),
            *(c.id for c in self.document.cuts),
            *(n.id for n in self.document.board_notes),
        ]
        return _refused(
            "no-such-feature",
            f"No mounting hole, edge connector, cut or label with id {id!r}. "
            f"This board has: {', '.join(known) if known else 'none'}.",
        )

    def place_component(
        self,
        ref: str,
        footprint_id: str,
        hole: str,
        value: str = "",
        rotation: int = 0,
        pin_names: dict[str, str] | None = None,
        symbol: str | None = None,
        part: str = "",
        mirrored: bool = False,
    ) -> dict[str, Any]:
        ref, footprint_id, value, names, symbol = self._from_catalog(
            part, ref, footprint_id, value, pin_names, symbol
        )
        if self.lookup(footprint_id) is None:
            raise _no_such_footprint(footprint_id)
        return self._dispatch(
            "component.place",
            PlaceComponentPayload(
                ref=ref,
                value=value,
                footprint_id=footprint_id,
                anchor=_hole(hole, self.document.board),
                rotation=_rotation(rotation),
                mirrored=_mirrored(mirrored),
                pin_names=names,
                symbol=cast(PartSymbol | None, symbol or None),
            ),
        )

    def move_component(self, ref: str, hole: str) -> dict[str, Any]:
        component = self._require_component(ref)
        return self._dispatch(
            "component.move", MoveComponentPayload(id=component.id, anchor=_hole(hole, self.document.board))
        )

    def rotate_component(self, ref: str, rotation: int) -> dict[str, Any]:
        component = self._require_component(ref)
        return self._dispatch(
            "component.rotate",
            RotateComponentPayload(id=component.id, rotation=_rotation(rotation)),
        )

    def mirror_component(self, ref: str, mirrored: bool = True) -> dict[str, Any]:
        """Put a part on the solder side, or back: ``mirrored`` is absolute, as
        ``rotate_component``'s rotation is. A mirrored part's pins are reflected, so the
        holes it takes change with it. Refused on a locked part, as the window refuses it.

        Its own verb and not a flag on ``rotate_component``: one call would then be two
        decisions and two undo steps.
        """
        component = self._require_component(ref)
        return self._dispatch(
            "component.mirror", MirrorComponentPayload(id=component.id, mirrored=mirrored)
        )

    def set_component_locked(self, ref: str, locked: bool) -> dict[str, Any]:
        """Pin a part in place so the placement optimiser works around it."""
        component = self._require_component(ref)
        return self._dispatch(
            "component.update", UpdateComponentPayload(id=component.id, locked=locked)
        )

    def delete_component(self, ref: str) -> dict[str, Any]:
        component = self._require_component(ref)
        return self._dispatch("component.delete", DeleteComponentPayload(id=component.id))

    def add_wire(
        self,
        from_hole: str,
        to_hole: str,
        kind: str = "insulated-wire",
        net: str | None = None,
        via: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a wire from one hole to another, bent at each hole in ``via`` on the way.

        A wire is joined at its two ends and only lies over the holes between, so ``via``
        is where it BENDS, not where it is soldered -- the corners a wire dressed along the
        grid has, which ``autoroute(wires="grid")`` lays and a two-hole wire could not.

        The side follows from the wire, as it does in the window: a top jumper runs over the
        component side, and on a solderless breadboard EVERY wire does, pushed into the
        plastic from above -- there is no other side there, and a wire left on the default
        bottom was a ``not-on-breadboard`` error the moment it was laid.

        The new conductor's ``id`` comes back with the result, which is what
        ``delete_conductors`` takes.
        """
        if kind not in ("bare-wire", "insulated-wire", "top-jumper"):
            raise SessionError(
                f"{kind!r} is not a wire. Use 'insulated-wire' (may cross other copper), "
                "'bare-wire' (may not) or 'top-jumper' (over the component side)."
            )
        board = self.document.board
        path = (
            _hole(from_hole, board),
            *(_hole(corner, board) for corner in via or ()),
            _hole(to_hole, board),
        )
        return self._add_conductor(
            NewWireConductor(
                path=path,
                kind=kind,  # type: ignore[arg-type]
                side=wire_side(kind, board),
                net_id=self._net_id(net),
            )
        )

    def add_solder_trace(
        self, holes: list[str], spine_gauge_mm: float | None = None, net: str | None = None
    ) -> dict[str, Any]:
        """Join adjacent pads with solder (PLAN.md D8).

        ``holes`` must be an orthogonally-adjacent chain; the command refuses a diagonal
        step, because solder does not reliably span the 1.7 mm diagonal gap the way it
        spans the 0.6 mm orthogonal one. A two-hole trace is what other tools call a
        solder bridge -- one concept, one rule set, so there is no separate tool for it.
        """
        if len(holes) < 2:
            raise SessionError("A solder trace needs at least two holes.")
        spine = (
            SpineSpec(material="tinned-copper", gauge=spine_gauge_mm)
            if spine_gauge_mm is not None
            else None
        )
        return self._add_conductor(
            NewSolderTraceConductor(
                path=tuple(_hole(h, self.document.board) for h in holes),
                kind="solder-trace-wired" if spine is not None else "solder-trace",
                spine=spine,
                net_id=self._net_id(net),
            )
        )

    def _add_conductor(self, conductor: NewConductor) -> dict[str, Any]:
        """One ``conductor.add``, answered with the id it was given.

        Without the id an agent could lay a wire and never take that wire back but by
        ``undo``: nothing else in a result named it, and a wire joining no pin appears in
        no tool's output at all.
        """
        before = {c.id for c in self.document.conductors}
        result = self._dispatch("conductor.add", AddConductorPayload(conductor=conductor))
        if result["ok"]:
            result["id"] = next(c.id for c in self.document.conductors if c.id not in before)
        return result

    def delete_conductors(self, ids: list[str]) -> dict[str, Any]:
        """Take copper off the board by id, all of it or none, as ONE undo step.

        The inverse ``add_wire`` and ``add_solder_trace`` never had: ``undo`` takes back the
        last step only, ``reroute`` only what claims a net, and ``remove_stale_conductors``
        only what a move left stranded. The ids are in ``get_board_info``'s ``conductors``,
        in ``run_drc``'s violations and in what an add returns. An id that is not on the
        board refuses the whole batch, as the command does -- a partly applied cleanup
        leaves nobody able to tell what went.
        """
        if not ids:
            raise SessionError("delete_conductors needs at least one conductor id.")
        return self._dispatch(
            "conductor.deleteMany",
            DeleteConductorsPayload(ids=tuple(dict.fromkeys(ids))),
        )

    # -- the planners ------------------------------------------------------

    def autoroute(
        self,
        nets: list[str] | None = None,
        style: str = "balanced",
        wires: str = "grid",
        crossings: str = "hop",
    ) -> dict[str, Any]:
        """Plan and commit the routing, as one undoable command."""
        if not self.document.nets:
            return _refused("no-netlist", "Nothing to route: no netlist has been imported.")

        only = None
        if nets:
            only = tuple(self._net_id_strict(name) for name in nets)

        # A stripboard is a different problem: its copper is already there, so the work
        # is deciding where to BREAK it. The perfboard router would lay solder traces
        # along tracks that are already joined and bare wire across a solid copper face,
        # so the board type picks the planner -- for an agent exactly as for the window.
        # A breadboard is the same problem with nothing to cut (breadroute.py).
        joined = board_joins_holes(self.document.board)
        if joined:
            # Checked here, before anything is cleared, as _route_options checks it below.
            _route_options(style, wires, crossings)

        # Cleared BEFORE planning, exactly as the GUI does it, so the plan is made
        # against the board as it will be rather than around copper that is about to go.
        # An agent that moves a part and re-routes must get the same result a user does.
        # On a breadboard too: a jumper left in a clip a part has moved out of joins the
        # part that moved IN, and the planner -- which takes what is fitted as fitted --
        # wires round it into a short.
        cleared = stale_conductor_ids(self.document, self.lookup)
        if cleared:
            self.remove_stale_conductors()

        if joined:
            return self._autoroute_stripboard(only, wires, stale_removed=len(cleared))

        options = _route_options(style, wires, crossings)
        # Every variant's measurements travel with the result, not just the winner's. An
        # agent that is told only "solder won" cannot judge whether to accept it, and the
        # trade it was decided on -- wires against bridging risk -- is exactly the kind a
        # caller may reasonably want to make differently.
        comparison: list[dict[str, Any]] = []
        chosen_style = style
        if style == BEST_STYLE:
            best = plan_best_autoroute(self.document, self.lookup, options, only_net_ids=only)
            plan = best.plan
            chosen_style = best.style
            comparison = [
                {
                    "style": variant.style,
                    "chosen": variant.style == best.style,
                    "routed": variant.plan.summary.links_routed,
                    "unrouted": variant.score.unrouted,
                    "traces": variant.score.traces,
                    "wires": variant.score.wires,
                    "wire_mm": round(variant.score.wire_mm, 1),
                    "risk_holes": variant.score.risk_holes,
                    "effort": round(variant.score.effort, 1),
                }
                for variant in sorted(best.variants, key=lambda v: v.score.key())
            ]
        else:
            plan = plan_autoroute(self.document, self.lookup, options, only_net_ids=only)

        if plan.is_empty:
            return _ok(
                committed=False,
                summary=describe_route(plan),
                routed=0,
                unrouted=0,
                stale_removed=len(cleared),
                style=chosen_style,
                comparison=comparison,
            )

        result = self._dispatch("conductor.addMany", plan.payload())
        if not result["ok"]:
            return result
        result.update(
            committed=True,
            summary=describe_route(plan),
            stale_removed=len(cleared),
            style=chosen_style,
            comparison=comparison,
            routed=plan.summary.links_routed,
            unrouted=plan.summary.links_unrouted,
            # Never summarised away: PLAN.md Sec 13 names "it routed most of it and left
            # four connections" as the trap this project is built to avoid.
            unrouted_detail=[
                {
                    "net": item.link.net_name,
                    "from": format_hole(item.link.from_, self.document.board),
                    "to": format_hole(item.link.to, self.document.board),
                    "reason": item.reason,
                }
                for outcome in plan.nets
                for item in outcome.unrouted
            ],
        )
        return result

    def _autoroute_stripboard(
        self,
        only: tuple[NetId, ...] | None,
        wires: str = "grid",
        stale_removed: int = 0,
    ) -> dict[str, Any]:
        """Cut the tracks that short two nets, link the islands that are left.

        One command for both, so an agent's undo takes back a whole plan rather than
        leaving the board cut apart with nothing linking it. Everything the planner could
        not do comes back in ``problems`` -- an agent that is told only what worked cannot
        tell a finished board from a half-finished one.

        ``wires`` shapes a breadboard's jumpers, as it shapes a perfboard's wires.
        """
        wire_path = _route_options("balanced", wires).router.wire_path
        plan = plan_joined_board(self.document, self.lookup, only, wire_path)
        problems = [
            {
                "code": problem.code,
                "message": problem.message,
                "holes": [format_hole(hole, self.document.board) for hole in problem.holes],
            }
            for problem in plan.problems
        ]
        if plan.is_empty:
            # Empty LISTS, not zeroes: an agent that reads ``cuts`` gets the same shape
            # whether or not there was anything to do, and does not have to handle a plan
            # whose fields change type when it happens to be empty.
            return _ok(
                committed=False,
                summary=describe_strip_plan(plan),
                cuts=[],
                links=[],
                cut_count=0,
                link_count=0,
                stale_removed=stale_removed,
                problems=problems,
            )

        result = self._dispatch("stripboard.apply", plan.payload())
        if not result["ok"]:
            return result
        result.update(
            committed=True,
            summary=describe_strip_plan(plan),
            cut_count=len(plan.cuts),
            link_count=len(plan.links),
            stale_removed=stale_removed,
            cuts=[format_hole(cut.at, self.document.board) for cut in plan.cuts],
            links=[
                {
                    "net": link.net_name,
                    "from": format_hole(link.from_hole, self.document.board),
                    "to": format_hole(link.to_hole, self.document.board),
                    "holes": link.holes,
                }
                for link in plan.links
            ],
            problems=problems,
        )
        return result

    def reroute(
        self,
        nets: list[str] | None = None,
        style: str = "balanced",
        wires: str = "grid",
        crossings: str = "hop",
    ) -> dict[str, Any]:
        """Rip up the existing routing and plan it again, as one undoable command.

        Different from ``autoroute``, which only ADDS: after a part moves, the copper
        laid for its old position still joins the right pins, so nothing reports it and
        autoroute simply puts more copper beside it. Measured on the NE555 fixture:
        14 conductors routed fresh, 16 after moving one resistor and autorouting again,
        14 again after this. Removes only conductors that claim one of these nets;
        copper with no net is left alone.
        """
        if not self.document.nets:
            return _refused("no-netlist", "Nothing to route: no netlist has been imported.")
        only = tuple(self._net_id_strict(name) for name in nets) if nets else None
        if board_joins_holes(self.document.board):
            # Its own planner, as autoroute's: the perfboard router laid solder traces on a
            # breadboard and traces along a stripboard's joined strips. The options are
            # checked all the same, and ``wires`` shapes a breadboard's jumpers.
            wire_path = _route_options(style, wires, crossings).router.wire_path
            joined = plan_joined_reroute(self.document, self.lookup, only, wire_path)
            if joined.is_empty:
                return _ok(committed=False, summary=describe_strip_plan(joined))
            outcome = self._dispatch("stripboard.apply", joined.payload())
            if not outcome["ok"]:
                return outcome
            # The same fields a perfboard re-route answers with, and the planner's problems
            # where it lists the connections it could not make.
            outcome.update(
                committed=True,
                summary=describe_strip_plan(joined),
                ripped_up=len(joined.remove_ids),
                routed=len(joined.links),
                unrouted=len(joined.problems),
                unrouted_detail=[
                    {
                        "code": problem.code,
                        "reason": problem.message,
                        "holes": [format_hole(h, self.document.board) for h in problem.holes],
                    }
                    for problem in joined.problems
                ],
            )
            return outcome

        plan = plan_reroute(
            self.document,
            self.lookup,
            only_net_ids=only,
            options=_route_options(style, wires, crossings),
        )
        if plan.is_empty:
            return _ok(committed=False, summary=describe_reroute(plan))

        result = self._dispatch("conductor.replace", plan.payload())
        if not result["ok"]:
            return result
        result.update(
            committed=True,
            summary=describe_reroute(plan),
            ripped_up=len(plan.remove_ids),
            routed=plan.summary.links_routed,
            unrouted=plan.summary.links_unrouted,
            unrouted_detail=[
                {
                    "net": item.link.net_name,
                    "from": format_hole(item.link.from_, self.document.board),
                    "to": format_hole(item.link.to, self.document.board),
                    "reason": item.reason,
                }
                for outcome in plan.nets
                for item in outcome.unrouted
            ],
        )
        return result

    def optimize_placement(self, seed: int = 0, apply: bool = True) -> dict[str, Any]:
        """Anneal the placement of every unlocked part (PLAN.md Sec 6.3).

        ``apply=False`` reports what it would do without touching the board, which is
        what an agent should use before spending a user's layout on it.

        The restarts run in worker processes, as the window runs them (``ui/planner_pool``):
        the same plan, in the time of the slowest restart rather than the sum. None of
        them may write to stdout, which here is the protocol -- a worker's streams go to
        the null device before it runs anything -- and a session whose workers will not
        start places in this process, as one with none does. ``planner`` says which.
        Imported here, as the renderers are: a server that never places starts no pool.
        """
        from perfboard_studio.ui import planner_pool

        plan = plan_placement(
            self.document,
            self.lookup,
            PlacementOptions(seed=seed),
            mapper=planner_pool.mapper_for(_never_stopped),
        )
        report = {
            "summary": describe_placement(plan),
            "planner": planner_pool.describe(),
            "seed": plan.seed,
            "moves": [
                {
                    "ref": change.ref,
                    "from": format_hole(change.from_anchor, self.document.board),
                    "to": format_hole(change.to_anchor, self.document.board),
                    "rotation": change.to_rotation,
                }
                for change in plan.changes
            ],
            "hpwl_mm_before": round(plan.before.hpwl_mm, 1),
            "hpwl_mm_after": round(plan.after.hpwl_mm, 1),
            "router_cost": plan.route_cost,
            "legal": plan.after.is_legal,
        }
        if plan.is_empty:
            return _ok(committed=False, **report)
        if not apply:
            return _ok(committed=False, **report)

        result = self._dispatch("component.moveMany", plan.payload())
        if not result["ok"]:
            return result
        result.update(committed=True, **report)
        return result

    def remove_stale_conductors(self) -> dict[str, Any]:
        """Delete copper a moved part left behind, as one undoable command."""
        strays = stale_conductor_ids(self.document, self.lookup)
        if not strays:
            return _ok(removed=0, message="Every conductor still connects the net it claims.")
        result = self._dispatch(
            "conductor.deleteMany",
            DeleteConductorsPayload(ids=strays, label=f"Remove {len(strays)} stale conductor(s)"),
        )
        if result["ok"]:
            result["removed"] = len(strays)
        return result

    # -- verification ------------------------------------------------------

    def run_erc(self) -> dict[str, Any]:
        findings = run_erc(self.document, self.lookup)
        names = {net.id: net.name for net in self.document.nets}
        return {
            # "ok" is the call, as everywhere here; the verdict is the error count.
            "ok": True,
            "errors": sum(1 for f in findings if f.severity == "error"),
            "warnings": sum(1 for f in findings if f.severity == "warning"),
            "findings": [
                {
                    "rule": f.rule,
                    "severity": f.severity,
                    "message": f.message,
                    "parts": list(f.refs),
                    "pins": [f"{p.component_ref}.{p.pin}" for p in f.pins],
                    "nets": [names[net_id] for net_id in f.net_ids if net_id in names],
                }
                for f in findings
            ],
        }

    def run_drc(self) -> dict[str, Any]:
        violations = run_drc(self.document, self.lookup)
        refs = {c.id: c.ref for c in self.document.components}
        return {
            # "ok" means the CALL ran, the same as everywhere else in this API. A check
            # that found something is still a check that ran; what it found is "errors".
            "ok": True,
            "errors": sum(1 for v in violations if v.severity == "error"),
            "warnings": sum(1 for v in violations if v.severity == "warning"),
            "violations": [
                {
                    "rule": v.rule,
                    "severity": v.severity,
                    "message": v.message,
                    "holes": [format_hole(h, self.document.board) for h in v.holes],
                    # What the finding is ABOUT, so it can be acted on: the parts by the
                    # reference every other tool takes, the copper by the id
                    # delete_conductors takes. Only when the rule names any, as the
                    # optional fields are everywhere else.
                    **(
                        {"components": [refs.get(id_, id_) for id_ in v.component_ids]}
                        if v.component_ids
                        else {}
                    ),
                    **({"conductor_ids": list(v.conductor_ids)} if v.conductor_ids else {}),
                }
                for v in violations
            ],
        }

    def run_lvs(self) -> dict[str, Any]:
        result = run_lvs(self.document, self.lookup)
        return {
            # "ok" is this API's word for "the call was not refused", and it read here as
            # "the board matches" -- so a board with an open came back looking like a tool
            # that had failed. The verdict has its own name.
            "ok": True,
            "matches_schematic": result.ok,
            "matched_nets": result.summary.matched_nets,
            "schematic_nets": result.summary.schematic_nets,
            "opens": result.summary.opens,
            "shorts": result.summary.shorts,
            "physical_nets": result.summary.physical_nets,
            "issues": [
                {
                    "kind": issue.kind,
                    "message": issue.message,
                    "nets": list(issue.net_names),
                    "pins": [f"{p.component_ref}.{p.pin}" for p in issue.pins],
                }
                for issue in result.issues
            ],
        }

    # -- output ------------------------------------------------------------

    def generate_guide(
        self, directory: str | None = None, language: str = "en"
    ) -> dict[str, Any]:
        """Build the soldering guide, and optionally write it out.

        Without a directory it returns the summary and the warnings only. That is
        usually what an agent wants -- "is this board buildable, and what is missing" --
        and it avoids writing four files into somebody's project as a side effect of
        asking a question.

        ``language`` is what the guide is written in, for the person who will build from
        it -- which is not necessarily the agent's language. Refused rather than guessed
        when it is not one the guide can be written in: an agent that asked for German and
        got English without a word would hand it on as German.
        """
        if language not in GUIDE_LANGUAGES:
            return _refused(
                "unknown-language",
                f"A guide can be written in {', '.join(GUIDE_LANGUAGES)}; "
                f"{language!r} is not one of them.",
            )
        guide = build_guide(
            self.document, self.lookup, GuideOptions(language=language)
        )
        report: dict[str, Any] = {
            "summary": describe_guide(guide),
            "part_steps": guide.part_steps,
            "conductor_steps": guide.conductor_steps,
            "checkpoints": guide.checkpoint_count,
            "wires_to_cut": len(guide.cut_list),
            "phases": [
                {"number": p.number, "title": p.title, "steps": len(p.steps),
                 "checks": len(p.checkpoints)}
                for p in guide.phases
                if not p.is_empty
            ],
            "warnings": [{"code": w.code, "message": w.message} for w in guide.warnings],
        }
        if directory is None:
            return _ok(written=[], **report)

        # A picture per step if VTK is usable here, and a guide without them if it is
        # not. Illustrations are worth having and are not worth failing an export over:
        # every word of the guide is still correct without one, and `report` says how
        # many were made so an agent is not left guessing whether it got them.
        # The `except` below covers a VTK that will not import. It cannot cover a VTK
        # that imports and then finds no GL context behind the offscreen window, because
        # that does not raise -- it ends the process, and an agent gets a dead server
        # instead of a guide. `offscreen_gl_available` spends that crash in a child
        # process where it costs nothing. Both paths land on the same picture-less guide.
        images: dict[str, bytes] = {}
        try:
            from perfboard_studio.ui.view3d import offscreen_gl_available, render_step_images

            if offscreen_gl_available():
                _ensure_qt_application()
                images = render_step_images(self.document, guide, self.lookup)
        except Exception:  # pragma: no cover - only on a VTK-less install
            images = {}
        report["step_images"] = len(images)

        out = _path_arg(directory, "generate_guide")
        try:
            out.mkdir(parents=True, exist_ok=True)
            written = []
            for name, text in (
                ("guide.html", guide_to_html(guide, images)),
                ("guide.json", guide_to_json(guide)),
                ("cut_list.csv", cut_list_to_csv(guide)),
                ("bom.csv", bom_to_csv(guide)),
            ):
                (out / name).write_text(text, encoding="utf-8")
                written.append(str(out / name))
        except OSError as err:
            raise SessionError(f"Cannot write the guide to {out}: {err.strerror or err}.") from err
        return _ok(written=written, **report)

    def export_pdf(self, directory: str | None = None) -> dict[str, Any]:
        """The 1:1 printable sheets, component side and mirrored solder side -- the
        component side alone on a solderless breadboard, which has the adhesive backing
        under it and no solder side, as the window's export decides.

        Needs Qt, which the engine does not, so it is imported here and its absence is
        reported as a refusal rather than taking the server down at import time.
        """
        if not directory or not directory.strip():
            # The server's own INSTRUCTIONS promise that nothing writes to disk unless a
            # path is named, and this wrote two PDFs into whatever the process happened to
            # be started in. Refused rather than defaulted: there is no directory an agent
            # asking for a PDF can be assumed to have meant.
            return _refused(
                "no-directory",
                "export_pdf writes two files, so it needs a directory to write them to. "
                "Nothing is written without one.",
            )
        out = _path_arg(directory, "export_pdf")
        try:
            from perfboard_studio.ui.export_pdf import export_pdf as write_pdf
            from perfboard_studio.ui.export_pdf import verify_scale
            from perfboard_studio.ui.view2d import BoardScene
        except Exception as err:  # pragma: no cover - only on a Qt-less install
            return _refused(
                "qt-unavailable",
                f"The 1:1 PDF export needs PySide6, which is not usable here ({err}).",
            )

        _ensure_qt_application()
        out.mkdir(parents=True, exist_ok=True)
        top = BoardScene(self.document, self.lookup, side="top", show_ratsnest=False,
                         show_rulers=False)
        check = verify_scale(top, self.document.board)
        written = [write_pdf(self.document.board, top, out / "board_component_side.pdf")]
        if not is_breadboard(self.document.board):
            bottom = BoardScene(self.document, self.lookup, side="bottom", show_ratsnest=False,
                                show_rulers=False)
            written.append(
                write_pdf(self.document.board, bottom, out / "board_solder_side.pdf", mirrored=True)
            )
        return _ok(
            written=[str(path) for path in written],
            scale_exact=check.ok,
            scale_error_um=round(check.error_mm * 1000, 3),
        )

    def export_step(self, path: str | None = None) -> dict[str, Any]:
        """The board as a STEP model: solids for a mechanical CAD program (``step_export``).

        Text the engine writes, so unlike the renders it needs no GL and cannot take the
        server down. The colours are the views' when the UI imports and neutral ones when
        it does not -- a model without its colours is still the whole model.
        """
        if not path or not path.strip():
            return _refused(
                "no-path",
                "export_step writes a file, so it needs a path to write it to. Nothing is "
                "written without one.",
            )
        target = _path_arg(path, "export_step")
        if target.suffix.lower() not in (".step", ".stp"):
            target = target.with_name(f"{target.name}.step")
        palette = None
        try:
            from perfboard_studio.ui.export_step import step_palette

            palette = step_palette(self.document)
        except Exception:  # pragma: no cover - only on a Qt- or VTK-less install
            palette = None
        model = board_model(self.document, self.lookup, palette)
        text = model_to_step(
            model,
            name=self.document.meta.name or "board",
            timestamp=_now_iso(),
            file_name=target.name,
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="ascii", newline="\n")
        except OSError as err:
            raise SessionError(f"Cannot write {target}: {err.strerror or err}.") from err
        board = model[0].solids[0].shape
        assert isinstance(board, Plate)
        return _ok(
            written=[str(target)],
            parts=[part.name for part in model],
            solids=sum(len(part.solids) for part in model),
            board_mm=[round(board.high[0], 3), round(board.high[1], 3), round(board.high[2], 3)],
            frame=(
                "millimetres, z up, the solder side on z = 0 and the board's corner at the "
                "origin; seen from +z it is the component side, A1 at the top left"
            ),
        )

    def render_2d(self, side: str = "top", px_per_mm: int = 12) -> tuple[bytes, dict[str, Any]]:
        """A PNG of the board as the editor draws it. Returns (png_bytes, metadata).

        The most important tool in the write-side surface, per PLAN.md Sec 9.2: without
        a picture an agent is editing a board it cannot see, and every judgement about
        whether a change helped is guesswork.
        """
        if side not in ("top", "bottom"):
            raise SessionError("side must be 'top' (component side) or 'bottom' (solder side).")
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QImage, QPainter

        from perfboard_studio.geometry import board_outline_mm
        from perfboard_studio.ui.view2d import RULER_MARGIN_MM, BoardScene

        _ensure_qt_application()
        board = self.document.board
        scene = BoardScene(self.document, self.lookup, side=side)  # type: ignore[arg-type]
        outline = board_outline_mm(board)
        width_mm, height_mm = outline.width, outline.height
        margin = RULER_MARGIN_MM
        src_w, src_h = width_mm + margin + 4, height_mm + margin + 4
        image = QImage(int(src_w * px_per_mm), int(src_h * px_per_mm), QImage.Format.Format_ARGB32)
        image.fill(QColor("#12131a"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scene.render(
            painter,
            QRectF(0, 0, image.width(), image.height()),
            QRectF(outline.x - margin, outline.y - margin, src_w, src_h),
        )
        painter.end()
        return _png_bytes(image), {
            "side": side,
            "width_px": image.width(),
            "height_px": image.height(),
        }

    def render_schematic(self, px_per_mm: int = 8) -> tuple[bytes, dict[str, Any]]:
        """A PNG of the CIRCUIT rather than of the board. Returns (png_bytes, metadata).

        The counterpart of ``render_2d`` for the half of the document a board picture cannot
        show. An agent that has just called ``connect_pins`` eleven times has changed the
        thing this application exists to build and has, until now, had no way to look at it
        -- the board renders show copper, and copper is what the circuit was turned INTO.

        The notes come back with the picture on purpose. They are where a pin the netlist
        names and the footprint does not, or a part nothing defines, is recorded, and an
        agent reading only the image would be reading a drawing of a circuit nobody has --
        the exact thing ``schematic.py`` keeps the field to prevent.

        Eight pixels per millimetre rather than the board renderer's twelve: a sheet is
        two or three times the size of the board it becomes, and the text on it is
        millimetres of sheet rather than a fixed pixel size, so it stays legible as the
        picture gets smaller.
        """
        from perfboard_studio.schematic import build_schematic
        from perfboard_studio.schematic_export import drawing_to_svg
        from perfboard_studio.ui.export_schematic import svg_to_image

        _ensure_qt_application()
        drawing = build_schematic(self.document, self.lookup)
        svg = drawing_to_svg(drawing, title=self.document.meta.name)
        image = svg_to_image(svg, px_per_mm=px_per_mm)
        return _png_bytes(image), {
            "parts": len(drawing.symbols),
            "nets_drawn": len(drawing.wires) + len(drawing.rails),
            "rails": len(drawing.rails),
            "width_px": image.width(),
            "height_px": image.height(),
            "notes": list(drawing.notes),
        }

    def render_3d(self, flipped: bool = False) -> tuple[bytes, dict[str, Any]]:
        """A PNG of the 3D view, component side or turned over."""
        import tempfile

        from perfboard_studio.ui import view3d

        _ensure_qt_application()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "view.png"
            stats = view3d.render_offscreen(
                self.document, self.lookup, str(target), flipped=flipped
            )
            return target.read_bytes(), {"flipped": flipped, **stats}

    # -- history and snapshots ---------------------------------------------

    def undo(self) -> dict[str, Any]:
        if not self.bus.can_undo():
            return _refused("nothing-to-undo", "The undo stack is empty.")
        last = self.bus.history()[-1]
        self.bus.undo()
        return _ok(undone=last, undo_depth=len(self.bus.history()))

    def redo(self) -> dict[str, Any]:
        if not self.bus.can_redo():
            return _refused("nothing-to-redo", "The redo stack is empty.")
        self.bus.redo()
        return _ok(undo_depth=len(self.bus.history()))

    def history(self) -> list[str]:
        return list(self.bus.history())

    def snapshot(self, label: str = "") -> dict[str, Any]:
        """Remember the board as it is now, under a name.

        Cheap: documents are immutable and commands replace only the tuples they touch,
        so a snapshot is a reference, not a copy. This and ``restore`` are what let an
        agent try something drastic and get out of it -- the second-most-important pair
        in this surface after the renderers.
        """
        self._snapshot_counter += 1
        key = label.strip() or f"snapshot-{self._snapshot_counter}"
        self.snapshots[key] = _Snapshot(label=key, document=self.document)
        return _ok(snapshot=key, snapshots=sorted(self.snapshots))

    #: Where ``restore`` parks the board it is about to replace.
    AUTO_SNAPSHOT = "before-restore"

    def restore(self, label: str) -> dict[str, Any]:
        """Go back to a snapshot.

        RESTORING CLEARS THE UNDO STACK, and that is worth stating because it is the one
        surprising thing in this surface. It happens because restoring replaces the
        session's bus: there is no command meaning "become this other document", and
        inventing one would put a whole-document payload in the journal that replay
        would then have to honour.

        So instead of pretending, the state being replaced is snapshotted first, under
        ``before-restore``. Nothing is lost, and the way back is another restore rather
        than an undo.
        """
        snapshot = self.snapshots.get(label)
        if snapshot is None:
            return _refused(
                "no-such-snapshot",
                f"No snapshot called {label!r}. Have: {', '.join(sorted(self.snapshots)) or 'none'}.",
            )
        self.snapshots[self.AUTO_SNAPSHOT] = _Snapshot(
            label=self.AUTO_SNAPSHOT, document=self.document
        )
        self._install(snapshot.document)
        return _ok(
            restored=label,
            undo_stack_cleared=True,
            previous_state_saved_as=self.AUTO_SNAPSHOT,
            status=self.get_status(),
        )

    # -- helpers -----------------------------------------------------------

    def _require_component(self, ref: str) -> ComponentInstance:
        for component in self.document.components:
            if component.ref == ref:
                return component
        known = ", ".join(c.ref for c in self.document.components) or "(the board is empty)"
        raise SessionError(f"No component called {ref!r}. On this board: {known}.")

    def _net_id(self, name: str | None) -> str | None:
        if not name:
            return None
        return self._net_id_strict(name)

    def _net_id_strict(self, name: str) -> str:
        for net in self.document.nets:
            if net.name == name or net.id == name:
                return net.id
        known = ", ".join(n.name for n in self.document.nets) or "(none imported)"
        raise SessionError(f"No net called {name!r}. Known nets: {known}.")


#: Accepted by ``autoroute``'s ``style`` alongside the router's own names: route once with
#: every style and keep whichever produces the board that is least work to build.
BEST_STYLE = "best"


def _route_styles() -> str:
    return ", ".join((*get_args(RoutingStyle), BEST_STYLE))


def _route_options(style: str, wires: str = "grid", crossings: str = "hop") -> AutorouteOptions:
    """Turn a style name into router options, or say what the names are.

    ``wires`` is how a wire is laid (``router.WirePath``), and it is ``"grid"`` here as it is
    in the window: square to the rows and columns, the way anybody builds a board. The
    engine's own default stays straight, because that is what every golden route records.

    ``crossings`` is what a trace does where it may not cross (``router.CrossingPolicy``),
    ``"hop"`` here as in the engine and the window. Like the wire path it is not part of a
    style, so it reaches the "best" sweep too.

    The style is a judgement about the builder rather than about the board -- which
    primitive they would rather use -- so it is per call, not a session setting: an agent
    may reasonably want the power rails as solder rails and the signals as wire.

    ``"best"`` returns the UNSTYLED defaults: the sweep applies each style itself, and
    priming it with one style's cost table would bias every variant.
    """
    if wires not in WIRE_PATHS:
        raise SessionError(
            f"{wires!r} is not a way to lay wire. Use one of: {', '.join(WIRE_PATHS)}."
        )
    if crossings not in CROSSING_POLICIES:
        raise SessionError(
            f"{crossings!r} is not a way to handle a crossing. "
            f"Use one of: {', '.join(CROSSING_POLICIES)}."
        )
    base = RouterOptions(wire_path=wires, crossing_policy=crossings)
    if style == BEST_STYLE:
        return AutorouteOptions(router=base)
    if style not in get_args(RoutingStyle):
        raise SessionError(f"{style!r} is not a routing style. Use one of: {_route_styles()}.")
    return AutorouteOptions(router=options_for_style(cast(RoutingStyle, style), base))


def _catalog_summary(part: CatalogPart) -> dict[str, Any]:
    """One catalog entry as an agent reads it. ``check`` only when there is something to
    check -- an empty field in every row is noise that hides the rows that have one."""
    return {
        "id": part.id,
        "name": part.name,
        "category": part.category,
        "summary": part.summary,
        "footprint": part.footprint_id,
        "value": part.placed_value,
        "ref_prefix": part.reference_prefix,
        **({"pin_names": dict(part.pin_names)} if part.pin_names else {}),
        **({"symbol": part.symbol} if part.symbol is not None else {}),
        "source": part.source,
        **({"check": part.check} if part.check else {}),
    }


def _pin_names_arg(names: dict[str, str] | None) -> PinNames | None:
    """An agent's ``{"1": "G"}`` as the pairs a payload carries, or ``None`` for "not given".

    Passed on UNCHECKED on purpose: ``commands.checked_pin_names`` is the one place the
    shape is judged, and a refusal from there comes back as data (``invalid-pin-names``)
    the way every other refusal does, rather than as an exception from this side.
    """
    if names is None:
        return None
    if not isinstance(names, dict):
        raise SessionError('pin_names is a mapping of pin number to name, e.g. {"1": "G"}.')
    return cast(PinNames, tuple(names.items()))


def _mirrored(value: object) -> bool | None:
    """A placement's ``mirrored``, or ``None`` for the command's own default.

    ``None`` rather than ``False`` when it is not asked for, so a placement that says
    nothing about the side dispatches exactly the payload it always did. A string is
    refused rather than read as true: ``"false"`` is a non-empty string.
    """
    if not isinstance(value, bool):
        raise SessionError(f"mirrored must be true or false, not {value!r}.")
    return True if value else None


def _rotation(value: int) -> Rotation:
    if value not in (0, 90, 180, 270):
        raise SessionError(f"Rotation must be 0, 90, 180 or 270 degrees, not {value}.")
    return value  # type: ignore[return-value]


def _ensure_qt_application() -> None:
    """A QApplication must exist before any QPainter or scene is built.

    Offscreen by default, but not on Windows: that platform plugin ships no font
    database at all, so every label renders as a missing-glyph box while looking perfect
    in the GUI. The normal plugin draws into a QImage without ever showing a window.
    """
    import os
    import sys

    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        os.environ.setdefault(
            "QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "offscreen"
        )
        QApplication(["perfboard-studio-mcp"])


def _no_such_footprint(footprint_id: str) -> SessionError:
    """The refusal, carrying the way out with it.

    The grammar is spelled out HERE rather than in a tool description, because this is the
    moment somebody needs it: an agent that has just been told a part does not exist is
    about to give up on the part, and the answer -- describe it by its dimensions -- is not
    something it could have guessed from a list of sixty-one names. Costing nothing until it
    is needed is the point; a tool docstring pays for it on every listing.
    """
    return SessionError(
        f"No footprint {footprint_id!r} in the library. Call list_footprints to see what is "
        f"available, or ask for a part by its measurements:\n\n{GENERATED_ID_GRAMMAR}"
    )


def _png_bytes(image: Any) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def new_board(
    cols: int = 30, rows: int = 20, material: str = "FR4", name: str = UNTITLED_NAME
) -> PerfDocument:
    """A blank document, for a session that starts from nothing."""
    if material not in ("FR4", "FR2", "FR1"):
        raise SessionError("Board material must be FR4, FR2 or FR1.")
    board = Board(
        type="pad-per-hole",
        cols=cols,
        rows=rows,
        pitch=2.54,
        thickness=1.6,
        material=material,  # type: ignore[arg-type]
        pad_diameter=1.9,
        drill_diameter=0.8,
    )
    return create_empty_document(
        DocumentMeta(name=name.strip() or UNTITLED_NAME, created=_now_iso(), modified=_now_iso()),
        board,
    )
