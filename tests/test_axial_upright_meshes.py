"""Resistors and diodes stood on end, drawn from KiCad's own models of them.

A standing axial part exists only as a generated id, so these are the first borrowed
packages attached to generated ids -- each to the id the importer gives one of KiCad's
``_Vertical`` packages, and to no other (``tools/import_kicad_models.py``,
``STANDING_MODELS``). Every other standing size is generated, as every generated id is.

What has to hold, and is measured here rather than trusted:

* the mesh index and the importer name the same part for each model;
* the barrel is the package the id says -- its diameter, its span off the board, the pin
  it stands over;
* every piece is inside the envelope DRC measures, at every turn and flip, with no
  tolerance -- which is why the heights in ``footprints`` ("Stood on end") are the models'
  B-rep tops;
* our print goes on KiCad's barrel, and a diode has one band, the model's;
* a resistor over its second pin is the pin-1 model turned, the same files placed by the
  index, not a copy.
"""

from __future__ import annotations

import json

import pytest

from perfboard_studio.drc import courtyard_box, placed_body_box
from perfboard_studio.footprints import get_footprint, standing_pin, upright_body_span
from perfboard_studio.geometry import hole_to_mm
from perfboard_studio.model import STANDARD_PITCH_MM, HoleCoord
from perfboard_studio.parsers.kicad_parts import kicad_footprint_ids
from perfboard_studio.ui import partmodels

from .test_axial_upright import LOOKUP, TURNS, _bus, _place

STANDING = sorted(
    fid
    for fid in partmodels.known_footprints()
    if (fp := get_footprint(fid)) is not None and fp.body.archetype == "axial-upright"
)

pytestmark = pytest.mark.skipif(not STANDING, reason="this build has no borrowed meshes")


def _raw_index() -> dict[str, dict[str, object]]:
    raw: dict[str, dict[str, object]] = json.loads(partmodels.INDEX_PATH.read_text(encoding="utf-8"))
    return raw


def test_every_kicad_package_at_both_pitches_and_on_both_pins_has_its_model() -> None:
    """Five packages, the two pitches a perfboard has, both pins: twenty ids."""
    expected = {
        f"axial-{holes}h-{size}-v{pin}"
        for size in ("3.6x1.6", "6.3x2.5", "9x3.2", "4x2-pol", "5.2x2.7-pol")
        for holes in (1, 2)
        for pin in ("", "2")
    }
    assert set(STANDING) == expected


@pytest.mark.parametrize("fid", STANDING)
def test_each_model_is_the_id_the_importer_gives_its_package(fid: str) -> None:
    """The index is read off the importer, so a netlist's ``R_Axial_..._Vertical`` lands on
    exactly the part drawn from that package's model. A resistor over pin 2 is the only
    entry KiCad has no package for, and it is the pin-1 model turned end for end."""
    entry = _raw_index()[fid]
    if "like" in entry:
        base = str(entry["like"])
        footprint = get_footprint(base)
        assert footprint is not None and not footprint.polarized
        assert fid == base + "2"
        span = max(pin.d_col for pin in footprint.pins) * STANDARD_PITCH_MM
        assert entry["rotate"] == 180.0 and entry["offset"] == [span, 0.0]
        assert "parts" not in entry, "a turned entry names the base's files, it has none"
        return
    ids, note = kicad_footprint_ids(str(entry["source"]).replace("/", ":", 1))
    assert ids[:1] == [fid] and note == ""


@pytest.mark.parametrize("fid", STANDING)
def test_the_barrel_is_the_package_the_id_says(fid: str) -> None:
    """Its diameter, its span off the board -- the standoff and the body's length, which
    is the id's -- and the pin it stands over, in the model's frame (pin 1 at the origin)."""
    model = partmodels.model_for(fid)
    footprint = get_footprint(fid)
    assert model is not None and model.body is not None and footprint is not None
    x0, y0, z0, x1, y1, z1 = model.body.bounds
    diameter = float(footprint.body.dims["diameter"])
    assert x1 - x0 == pytest.approx(diameter, abs=0.02)
    assert y1 - y0 == pytest.approx(diameter, abs=0.05)
    assert (z0, z1) == pytest.approx(upright_body_span(footprint), abs=1e-3)
    stood = standing_pin(footprint)
    assert stood is not None
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((stood.d_col * STANDARD_PITCH_MM, 0.0), abs=0.02)


def _placed(fid: str, rotation: int = 0, mirrored: bool = False, value: str = "4k7"):  # type: ignore[no-untyped-def]
    from perfboard_studio.ui import view3d

    bus = _bus()
    _place(bus, "X1", fid, 10, 8, rotation, mirrored, value=value)
    document = bus.document
    comp = document.components[0]
    footprint = LOOKUP(comp.footprint_id)
    body = view3d._world_body(LOOKUP, comp, document.board)
    assert footprint is not None and body is not None
    pieces = view3d._pieces_for(body, footprint, comp, document.board)
    return document, comp, footprint, body, pieces


def _world_box(box: tuple[float, float, float, float], document) -> tuple[float, float, float, float]:  # type: ignore[no-untyped-def]
    """A board-space (min x, max x, min y, max y) in the 3D world: x from the first hole,
    rows counted up-negative."""
    first = hole_to_mm(HoleCoord(0, 0), document.board)
    min_x, max_x, min_y, max_y = box
    return (min_x - first.x, max_x - first.x, -(max_y - first.y), -(min_y - first.y))


@pytest.mark.parametrize("fid", STANDING)
@pytest.mark.parametrize(("rotation", "mirrored"), TURNS)
def test_every_piece_is_inside_the_envelope_drc_measures(fid: str, rotation: int, mirrored: bool) -> None:
    """With no tolerance but the float's: no higher than ``body_height`` -- the model's own
    B-rep top, which a tessellation lies under -- and no wider than the courtyard; the barrel
    inside the body DRC measures. And as tall as it says: the bent-over lead is the top."""
    from perfboard_studio.ui import view3d

    document, comp, footprint, body, pieces = _placed(fid, rotation, mirrored)
    model = partmodels.model_for(fid)
    assert model is not None
    cy = courtyard_box(comp, footprint, document.board)
    assert cy is not None
    court = _world_box((cy[0], cy[2], cy[1], cy[3]), document)
    bodybox = _world_box(placed_body_box(comp, footprint, document.board), document)
    fill = view3d._rgb(body.style.fill)
    eps = 1e-6
    tops = []
    for piece in pieces:
        x0, x1, y0, y1, _z0, z1 = view3d._actor_for(piece).GetBounds()
        tops.append(z1)
        assert z1 <= footprint.body_height + eps, (piece.rgb, z1)
        assert court[0] - eps <= x0 and x1 <= court[1] + eps, ("x", x0, x1, court)
        assert court[2] - eps <= y0 and y1 <= court[3] + eps, ("y", y0, y1, court)
        if piece.rgb == fill:
            assert bodybox[0] - eps <= x0 and x1 <= bodybox[1] + eps, ("barrel x", x0, x1, bodybox)
            assert bodybox[2] - eps <= y0 and y1 <= bodybox[3] + eps, ("barrel y", y0, y1, bodybox)
    assert max(tops) == pytest.approx(footprint.body_height, abs=0.02)


@pytest.mark.parametrize("fid", [f for f in STANDING if "-pol" not in f])
def test_a_standing_resistors_value_is_printed_on_kicads_barrel(fid: str) -> None:
    """KiCad's barrel is bare; the colour code is ours, read from the top down, printed at
    the barrel's own radius over the pin it stands on -- the turned one's over pin 2."""
    from perfboard_studio.ui import view3d

    _document, _comp, _footprint, body, pieces = _placed(fid, value="4k7")
    model = partmodels.model_for(fid)
    assert model is not None and body.bands
    barrel = view3d._standing_barrel_of(model)
    assert barrel is not None
    radius, centre, length = barrel
    band_colours = {view3d._rgb(colour) for colour in body.bands}
    bands = [piece for piece in pieces if piece.rgb in band_colours and piece.rgb != view3d._rgb(body.style.fill)]
    assert len(bands) == len(body.bands)
    for band in bands:
        x0, x1, y0, y1, z0, z1 = view3d._actor_for(band).GetBounds()
        assert (x1 - x0) / 2 >= radius and (y1 - y0) / 2 >= radius * 0.99, "printed on the barrel, not inside it"
        assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((body.x, body.y), abs=0.02)
        assert centre - length / 2 <= (z0 + z1) / 2 <= centre + length / 2
    heights = [band.position[2] for band in bands]
    assert heights == sorted(heights, reverse=True), "the first band is the top one"


@pytest.mark.parametrize("fid", [f for f in STANDING if "-pol" in f])
def test_a_standing_diode_has_one_band_and_it_is_the_models(fid: str) -> None:
    """The model's own band, painted in the style's accent, and no second one printed --
    at the bottom when the part stands on its cathode (``-v``), at the top when not."""
    from perfboard_studio.ui import view3d

    _document, comp, _footprint, body, pieces = _placed(fid)
    model = partmodels.model_for(fid)
    assert model is not None
    mark = view3d._polarity_mark(model)
    assert mark is not None
    accent = view3d._rgb(body.style.accent)
    banded = [piece for piece in pieces if piece.rgb == accent]
    assert len(banded) == 1
    assert banded[0].source is view3d._mesh(str(mark.path), comp.mirrored, model.turn_deg, model.offset)
    _radius, middle, _length = view3d._standing_barrel_of(model)  # type: ignore[misc]
    band_z = (mark.bounds[2] + mark.bounds[5]) / 2
    assert (band_z < middle) == fid.endswith("-v")


def test_a_turned_entry_is_the_base_models_files_placed_by_the_index() -> None:
    """The same files, and their boxes turned half round and shifted by the span: the barrel
    over pin 2, every lead still landing where the base model's did, end for end."""
    turned = partmodels.model_for("axial-2h-6.3x2.5-v2")
    base = partmodels.model_for("axial-2h-6.3x2.5-v")
    assert turned is not None and base is not None
    assert [p.mesh for p in turned.pieces] == [p.mesh for p in base.pieces]
    assert (turned.turn_deg, turned.offset) == (180.0, (2 * STANDARD_PITCH_MM, 0.0))
    for a, b in zip(base.pieces, turned.pieces, strict=True):
        x0, y0, z0, x1, y1, z1 = a.bounds
        span = 2 * STANDARD_PITCH_MM
        assert b.bounds == pytest.approx((span - x1, -y1, z0, span - x0, -y0, z1))
    assert turned.placed(0.0, 0.0) == pytest.approx((2 * STANDARD_PITCH_MM, 0.0))


def test_a_turned_entry_whose_base_is_missing_is_no_model(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The fallback rule, again: a part with nothing to draw it from is generated, not an
    error -- here, an entry that names a base the index does not have."""
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"axial-1h-6.3x2.5-v2": {"like": "gone", "rotate": 180.0, "offset": [2.54, 0.0]}}))
    monkeypatch.setattr(partmodels, "INDEX_PATH", index)
    partmodels._index.cache_clear()
    try:
        assert partmodels.model_for("axial-1h-6.3x2.5-v2") is None
    finally:
        monkeypatch.undo()
        partmodels._index.cache_clear()


@pytest.mark.parametrize("fid", ["axial-1h-6.3x2.5-v", "axial-1h-5.2x2.7-pol-v2"])
def test_without_the_models_a_standing_part_is_generated(fid: str, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A build that shipped without the meshes draws the standing part it always drew."""
    from perfboard_studio.ui import view3d

    monkeypatch.setattr(view3d, "_model_for", lambda _footprint_id: None)
    _document, _comp, footprint, body, pieces = _placed(fid)
    assert len(pieces) == len(view3d._axial_upright_pieces(body))
    tops = [view3d._actor_for(piece).GetBounds()[5] for piece in pieces]
    assert max(tops) == pytest.approx(footprint.body_height + view3d._LIFT, abs=0.02)
