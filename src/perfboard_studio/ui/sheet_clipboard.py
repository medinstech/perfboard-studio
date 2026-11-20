"""Sheet clipboard serialization: pure JSON conversion for ``sheet.paste`` (no Qt)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Literal, cast

from perfboard_studio.commands import PasteSheetPart, PasteSheetPayload
from perfboard_studio.model import (
    VALID_ROTATIONS,
    LooseWire,
    NetNode,
    PartSymbol,
    PerfDocument,
    PinNames,
    PinRoles,
    Point2,
    PortLink,
    SheetNote,
    SheetNoteKind,
    SheetPort,
    SheetPortKind,
    SheetWire,
    normalized_pin_names,
    normalized_pin_roles,
)
from perfboard_studio.schematic import SchematicDrawing, snap_to_grid
from perfboard_studio.system import circuit_parts

SHEET_CLIPBOARD_MARKER = "perfboard-studio-sheet-block"
SHEET_CLIPBOARD_VERSION = 1


def _pt_dict(pt: Point2) -> dict[str, float]:
    return {"x": pt.x, "y": pt.y}


def _pt_from(raw: object) -> Point2:
    if not isinstance(raw, dict):
        raise ValueError("point")
    return Point2(x=float(raw["x"]), y=float(raw["y"]))


def _node_dict(node: NetNode) -> dict[str, str]:
    return {"componentRef": node.component_ref, "pin": node.pin}


def _node_from(raw: object) -> NetNode:
    if not isinstance(raw, dict):
        raise ValueError("node")
    return NetNode(component_ref=str(raw["componentRef"]), pin=str(raw["pin"]))


def sheet_block_to_json(
    doc: PerfDocument,
    drawing: SchematicDrawing,
    refs: Iterable[str] = (),
    port_ids: Iterable[str] = (),
    note_indices: Iterable[int] = (),
    loose_ids: Iterable[str] = (),
) -> str:
    """Serialize the selected symbols, wires between them, ports, loose wires and notes."""
    ref_set = set(refs)
    port_set = set(port_ids)
    note_idx_set = set(note_indices)
    loose_set = set(loose_ids)
    if not (ref_set or port_set or note_idx_set or loose_set):
        return ""

    parts_by_ref = {part.ref: part for part in circuit_parts(doc)}
    placements_by_id = {pl.id: pl for pl in doc.sheet}
    symbols_by_ref = {sym.ref: sym for sym in drawing.symbols}

    parts_out: list[dict[str, object]] = []
    for ref in sorted(ref_set):
        part = parts_by_ref.get(ref)
        sym = symbols_by_ref.get(ref)
        if part is None or sym is None:
            continue
        pl = placements_by_id.get(part.id)
        entry: dict[str, object] = {
            "sourceRef": part.ref,
            "footprintId": part.footprint_id,
            "value": part.value,
            "at": _pt_dict(pl.at if pl is not None else snap_to_grid(sym.at)),
            "rotation": int(pl.rotation if pl is not None else sym.rotation),
            "mirrored": bool(pl.mirrored if pl is not None else sym.mirrored),
        }
        if part.pin_names:
            entry["pinNames"] = [[n, label] for n, label in part.pin_names]
        if part.pin_roles:
            entry["pinRoles"] = [[n, role] for n, role in part.pin_roles]
        if part.symbol is not None:
            entry["symbol"] = part.symbol
        if part.note:
            entry["note"] = part.note
        if pl is not None and pl.ref_offset is not None:
            entry["refOffset"] = _pt_dict(pl.ref_offset)
        if pl is not None and pl.value_offset is not None:
            entry["valueOffset"] = _pt_dict(pl.value_offset)
        parts_out.append(entry)

    # Carry every drawn wire whose ends are all in the copied symbol set.
    wires_out: list[dict[str, object]] = []
    for wire in doc.sheet_wires:
        if wire.a.component_ref not in ref_set or wire.b.component_ref not in ref_set:
            continue
        if wire.tap is not None and wire.tap.component_ref not in ref_set:
            continue
        w_obj: dict[str, object] = {
            "a": _node_dict(wire.a),
            "b": _node_dict(wire.b),
            "path": [_pt_dict(pt) for pt in wire.path],
        }
        if wire.tap is not None:
            w_obj["tap"] = _node_dict(wire.tap)
        wires_out.append(w_obj)

    # Carry selected ports, plus ports linked solely to selected symbols.
    ports_out: list[dict[str, object]] = []
    included_ports: set[str] = set()
    for port in doc.sheet_ports:
        linked_in = [link for link in port.links if link.pin.component_ref in ref_set]
        if port.id in port_set or (linked_in and len(linked_in) == len(port.links)):
            included_ports.add(port.id)
            ports_out.append(
                {
                    "id": port.id,
                    "kind": port.kind,
                    "name": port.name,
                    "at": _pt_dict(port.at),
                    "links": [
                        {"pin": _node_dict(link.pin), "path": [_pt_dict(pt) for pt in link.path]}
                        for link in linked_in
                    ],
                }
            )

    loose_out: list[dict[str, object]] = []
    for lw in doc.sheet_loose_wires:
        anchored_in = (
            (lw.pin is not None and lw.pin.component_ref in ref_set)
            or (
                lw.on is not None
                and lw.on[0].component_ref in ref_set
                and lw.on[1].component_ref in ref_set
            )
            or (lw.port is not None and lw.port in included_ports)
        )
        if lw.id in loose_set or anchored_in:
            l_obj: dict[str, object] = {
                "id": lw.id,
                "path": [_pt_dict(pt) for pt in lw.path],
            }
            if lw.pin is not None:
                l_obj["pin"] = _node_dict(lw.pin)
            if lw.on is not None:
                l_obj["on"] = [_node_dict(lw.on[0]), _node_dict(lw.on[1])]
            if lw.port is not None:
                l_obj["port"] = lw.port
            loose_out.append(l_obj)

    notes_out: list[dict[str, object]] = []
    for idx in sorted(note_idx_set):
        if 0 <= idx < len(doc.sheet_notes):
            note = doc.sheet_notes[idx]
            notes_out.append(
                {
                    "id": note.id,
                    "kind": note.kind,
                    "at": _pt_dict(note.at),
                    "to": _pt_dict(note.to),
                    "text": note.text,
                    "sizeMm": note.size_mm,
                }
            )

    if not (parts_out or wires_out or ports_out or loose_out or notes_out):
        return ""

    payload = {
        "kind": SHEET_CLIPBOARD_MARKER,
        "version": SHEET_CLIPBOARD_VERSION,
        "parts": parts_out,
        "wires": wires_out,
        "ports": ports_out,
        "looseWires": loose_out,
        "notes": notes_out,
    }
    return json.dumps(payload, indent=2)


_ZERO_OFFSET = Point2(x=0.0, y=0.0)


def sheet_block_from_json(
    text: str, *, offset: Point2 = _ZERO_OFFSET, label: str | None = None
) -> PasteSheetPayload | None:
    """Parse a JSON clipboard snippet back into a ``PasteSheetPayload``, or ``None``."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("kind") != SHEET_CLIPBOARD_MARKER:
        return None
    try:
        parts: list[PasteSheetPart] = []
        for raw in data.get("parts", ()):
            rot = int(raw.get("rotation", 0))
            if rot not in VALID_ROTATIONS:
                return None
            pin_names: PinNames = (
                normalized_pin_names({str(k): str(v) for k, v in raw["pinNames"]})
                if "pinNames" in raw
                else ()
            )
            pin_roles: PinRoles = (
                normalized_pin_roles({str(k): str(v) for k, v in raw["pinRoles"]})
                if "pinRoles" in raw
                else ()
            )
            parts.append(
                PasteSheetPart(
                    source_ref=str(raw["sourceRef"]),
                    footprint_id=str(raw["footprintId"]),
                    value=str(raw.get("value", "")),
                    at=_pt_from(raw["at"]),
                    rotation=rot,
                    mirrored=bool(raw.get("mirrored", False)),
                    pin_names=pin_names,
                    pin_roles=pin_roles,
                    symbol=cast(PartSymbol | None, raw.get("symbol")),
                    note=str(raw.get("note", "")),
                    ref_offset=_pt_from(raw["refOffset"]) if "refOffset" in raw else None,
                    value_offset=_pt_from(raw["valueOffset"]) if "valueOffset" in raw else None,
                )
            )
        wires = tuple(
            SheetWire(
                a=_node_from(raw["a"]),
                b=_node_from(raw["b"]),
                path=tuple(_pt_from(pt) for pt in raw["path"]),
                tap=_node_from(raw["tap"]) if "tap" in raw else None,
            )
            for raw in data.get("wires", ())
        )
        ports = tuple(
            SheetPort(
                id=str(raw["id"]),
                kind=cast(SheetPortKind, str(raw["kind"])),
                name=str(raw["name"]),
                at=_pt_from(raw["at"]),
                links=tuple(
                    PortLink(
                        pin=_node_from(link["pin"]),
                        path=tuple(_pt_from(pt) for pt in link["path"]),
                    )
                    for link in raw.get("links", ())
                ),
            )
            for raw in data.get("ports", ())
        )
        loose_wires = tuple(
            LooseWire(
                id=str(raw["id"]),
                path=tuple(_pt_from(pt) for pt in raw["path"]),
                pin=_node_from(raw["pin"]) if "pin" in raw else None,
                on=(_node_from(raw["on"][0]), _node_from(raw["on"][1]))
                if "on" in raw
                else None,
                port=str(raw["port"]) if "port" in raw else None,
            )
            for raw in data.get("looseWires", ())
        )
        notes = tuple(
            SheetNote(
                id=str(raw["id"]),
                kind=cast(SheetNoteKind, str(raw["kind"])),
                at=_pt_from(raw["at"]),
                to=_pt_from(raw["to"]),
                text=str(raw.get("text", "")),
                size_mm=float(raw.get("sizeMm", 2.0)),
            )
            for raw in data.get("notes", ())
        )
    except (KeyError, TypeError, ValueError):
        return None
    if not (parts or wires or ports or loose_wires or notes):
        return None
    return PasteSheetPayload(
        parts=tuple(parts),
        wires=wires,
        loose_wires=loose_wires,
        ports=ports,
        notes=notes,
        offset=offset,
        label=label,
    )


type MirrorAxis = Literal["x", "y"]
