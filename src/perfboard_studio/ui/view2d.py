"""2D board editor on QGraphicsView, rewired onto the real engine.

Promoted from ``prototypes/qt/view2d.py``. The scene still works in MILLIMETRES (one
scene unit = 1 mm) -- that is what makes the 1:1 PDF export exact -- but everything it
draws now comes from a real ``perfboard_studio.model.PerfDocument`` rather than the
prototype's throwaway ``board_model`` dataclasses, and dragging a part no longer
mutates anything directly: it dispatches ``component.move`` on a
``perfboard_studio.command.CommandBus`` and waits to be told the result.

MIRRORING. ``hole_to_screen``/``screen_to_hole`` below are the single place that turns
a hole coordinate into a scene position and back, for either board side. The solder
side is a genuine reflection about the HOLE SPAN (``geometry.hole_span_mm``), not the
substrate size (``geometry.board_size_mm``) -- the two differ by half a pitch, and
reflecting about the wrong one silently shifts every hole by that half pitch, which is
exactly the kind of bug that only shows up once someone has already soldered the board
backwards (see the long comment on ``hole_span_mm`` in geometry.py). Every item in this
file that needs a screen position -- pads, conductor paths, component anchors AND a
component's local body/pin offsets -- routes through these two functions (or the
matching local-offset negation), so flipping the board is one reflection applied
consistently everywhere, not a family of ad hoc sign flips that can drift apart.
"""

from __future__ import annotations

import contextlib
import html
import math
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any, NamedTuple, cast

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetricsF,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QNativeGestureEvent,
    QPagedPaintDevice,
    QPaintEngine,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QResizeEvent,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QToolTip,
    QWidget,
)

from perfboard_studio.breadboard import (
    RAIL_CLASS,
    STANDARD_CHANNEL,
    channel_stretches,
    has_breadboard_pattern,
    has_hole,
    has_rails,
    is_breadboard,
    is_solderable_breadboard,
    rail_of,
    strip_letter,
)
from perfboard_studio.command import CommandBus, DispatchResult
from perfboard_studio.commands import (
    AddConductorPayload,
    AddCutPayload,
    AddNetPayload,
    ComponentPlacement,
    ConnectPinsPayload,
    DeleteCutPayload,
    MoveComponentPayload,
    MoveComponentsPayload,
    NewConductor,
    NewSolderTraceConductor,
    NewWireConductor,
    PartPlacement,
    PlaceComponentPayload,
    PlaceOffBoardPayload,
    PlacePartsPayload,
    SetConductorPathPayload,
    UpdateBoardNotePayload,
    count_noun,
    next_net_name,
    plan_pin_join,
)
from perfboard_studio.connectivity import FootprintLookup, PhysicalNet, extract_physical_nets
from perfboard_studio.drc import DrcViolation
from perfboard_studio.footprints import wire_entry
from perfboard_studio.geometry import (
    FLYING_LEAD_MARKER_MM,
    FingerCell,
    all_pin_holes,
    board_note_anchor,
    board_note_centre_mm,
    board_outline_mm,
    board_text_placement,
    column_label,
    consumed_holes,
    edge_finger_rect,
    finger_cells,
    finger_corner_radius_mm,
    flying_lead_routes,
    format_hole,
    hole_key,
    hole_span_mm,
    holeless_positions,
    holes_without_grid_pad,
    is_inside_board,
    legend_ink_width_mm,
    legend_layout,
    manhattan,
    mounting_hole_centre_mm,
    pad_extent_mm,
    path_length_mm,
    path_point_mm,
    printed_label,
    printed_label_is_clear,
    row_label,
    surviving_finger_holes,
    transform_offset,
    transform_pin_offset,
    undrilled_holes,
)
from perfboard_studio.guide import (
    conductor_word,
    is_bench_check,
    lead_end,
    lead_marker,
)
from perfboard_studio.model import (
    STANDARD_PITCH_MM,
    Board,
    BoardLabels,
    BoardNote,
    BoardSide,
    ComponentInstance,
    Conductor,
    ConductorKind,
    EdgeConnector,
    Footprint,
    HoleCoord,
    MountingHole,
    Net,
    NetClass,
    NetNode,
    PartSymbol,
    PerfDocument,
    PinNames,
    PinRoles,
    Point2,
    Rotation,
    TrackCut,
    contacts_every_path_hole,
    has_component_side_copper,
    pin_name_of,
)
from perfboard_studio.occupancy import build_occupancy, stacking_layers
from perfboard_studio.phrasebook import guide_language, phrasebook
from perfboard_studio.ratsnest import RatsnestLine, ratsnest_lines
from perfboard_studio.stripboard import cut_holes, is_stripboard, segments
from perfboard_studio.system import references_in_use

# The one place the wire-colour convention is defined, so the editor and the cut list a
# person actually works from cannot disagree about which wire is which.
from perfboard_studio.wirecolour import (
    COLOR_BY_NET_CLASS,
    SIGNAL_COLORS,
    net_colours,
    signal_colour_index,
)
from perfboard_studio.wiringstats import vias

from . import motion, theme
from .boardcolors import BREADBOARD, scheme_for
from .bodies import (
    AXIAL_ARCHETYPES,
    BODY_STYLES,
    ELECTROLYTIC_STRIPE_SHARE,
    FLAT_FACE_LOCAL,
    PIN_NAME_HEIGHT_MM,
    PIN_NAME_TAG_HEIGHT_MM,
    PIN_NAME_TAG_PAD_MM,
    PLUS_MARK_INK,
    PLUS_MARK_MM,
    PLUS_MARK_STROKE_MM,
    BodyPlacement,
    BodyStyle,
    PinLabel,
    RightAngle,
    flat_face_profile,
    lay_out_pin_names,
    leads_for,
    module_block_size,
    placement_for,
    plus_mark,
    polarity_pin_offset,
    resistor_bands,
    right_angle_for,
    style_for,
    surface_for,
)
from .canvasinput import wheel_intent
from .drawcheck import DrawCheck, DrawProblem, check_drawn, drawn_as
from .i18n import counted, t
from .i18n import language as current_language
from .moduleart import (
    ART_COLOURS,
    CAMERA_MM,
    ENCODER_MM,
    FPC_MM,
    FRESNEL_DOME_MM,
    GULL_WING_LEGS,
    HOLE_EDGE_MM,
    JST_SH_PITCH_MM,
    JST_SH_TAILS_MM,
    MICROSD_LATCH_MM,
    MICROSD_TAILS,
    OLED_LEDGE_MM,
    OLED_VIEW_MM,
    PCB_ANTENNA_TRACE_MM,
    SOT23_LEGS,
    TANTALUM_BAND_SHADE,
    TERMINAL_MOUTH_MM,
    TERMINAL_SCREW_MM,
    TQFP32_BODY_MM,
    TQFP32_LEG_MM,
    TQFP32_LEGS_PER_SIDE,
    TQFP32_PITCH_MM,
    PlacedArt,
    PlacedStanding,
    board_colour_for,
    fit_module_art,
    fit_standing_board,
    gull_wing_dot,
    module_pad_plating,
)
from .moduleart import outline as art_outline
from .offboard import OffBoardItem, things_for
from .partnames import footprint_label
from .scenetext import (
    draw_flag_label,
    draw_label,
    draw_outlined_reference,
    draw_physical_label,
    draw_printed_reference,
    label_font,
    label_plate_rect,
    physical_label_width_mm,
    pin_name_width_mm,
    reference_plate,
)

# The window's own palette, for what is drawn round the board, and the marks drawn on
# it that belong to the application rather than to the object -- see theme.py's note on
# why the two are apart.
from .theme import (
    CANVAS_ERROR,
    CANVAS_HOVER,
    CANVAS_HOVER_WIDTH_PX,
    CANVAS_SELECTED,
    CANVAS_WARNING,
    NET_COLOURS,
)
from .topview import TopView, top_view

#: Qt's QWIDGETSIZE_MAX: what ``setMaximumWidth`` takes to mean "no limit".
QWIDGETSIZE_MAX = (1 << 24) - 1

# --------------------------------------------------------------------------- theme

#: Around the board: the application's canvas, so it follows the theme. The board on it
#: does not.
BACKGROUND = QColor(theme.ACTIVE.canvas)
SUBSTRATE = {"FR4": QColor("#2e6b3f"), "FR2": QColor("#a8834e"), "FR1": QColor("#b8925c")}
SUBSTRATE_EDGE = QColor("#0d1a12")
#: The copper comes from the board's own scheme, because a phenolic board's pads are
#: BARE copper and a plated FR-4 board's are gold. These are the fallbacks for a painter
#: with no board to ask, and are the plated ones.
PAD = QColor("#c8a951")
PAD_RING = QColor("#8a7331")
PAD_SHEEN = QColor("#e4cd83")
DRILL = QColor("#22232a")
BODY_LINE = QColor("#31313a")
#: Tinned component lead, and the pin markers drawn over a body.
LEAD = QColor("#c2c8d0")
PIN_MARKER = QColor("#8d949e")
PIN_ONE = QColor("#f0f3f8")
#: A round LED's leads seen through its dome, from the component side: a mark this wide,
#: the dome's own colour a shade darker, and the + lead still the bright one. Full-size
#: rings stacked with the die between them read as an "8" on a 5 mm LED, which is a glyph
#: rather than a part; the electrolytic's two marks sit apart on a dark can and never did.
LED_LEAD_MARK_MM = 0.3
LED_LEAD_SHADE = 140
#: A part off the board's wires: how thick the jacket is drawn, how much tinned wire shows
#: between the pad and where the jacket starts, and how far past the edge each one is drawn,
#: fading out, before it goes off to the panel. Inside the scene's own 4 mm margin, so a
#: fitted view shows the wires leaving rather than cutting them off at the frame.
FLYING_LEAD_JACKET_MM = 1.0
FLYING_LEAD_BARE_MM = 0.9
FLYING_LEAD_PAST_EDGE_MM = 3.5
#: The marker each of those wires carries ("RV1·2"): a white sleeve with the text on it, held
#: at a screen size like every annotation, and drawn only once the board is close enough for
#: one to fit between two wires -- zoomed out, a row of them is a white smear.
FLYING_LEAD_MARKER_PX = 11
FLYING_LEAD_MARKER_MIN_SCALE = 6.5
#: How many times a marker may step out along its wire to clear one beside it.
FLYING_LEAD_MARKER_STEPS = 2
FLYING_LEAD_MARKER_FILL = QColor("#eceae4")
FLYING_LEAD_MARKER_EDGE = QColor("#2a2c31")
FLYING_LEAD_MARKER_INK = QColor("#15151a")
LABEL = QColor("#15151a")
REF_LABEL = QColor("#eef1f8")
#: The plate behind a reference ON PAPER: dark enough to carry light text over tinned
#: pads. On screen a reference is outlined instead (``REF_HALO``).
REF_PLATE = QColor(14, 16, 22, 185)
#: The outline round a reference's letters on screen, in place of a plate. Chosen on
#: 2026-10-28 from three rendered looks: the plates were a dark pill beside every part.
REF_HALO = QColor(10, 12, 16, 210)

#: EVERY PAD IS TIN, used or not, on screen as on the board and the 1:1 print. Pads nothing
#: landed in were drawn quieter for a while (2026-10-28), mixed toward the substrate so the
#: used ones drew the circuit; the user chose the board as it is in the hand (2026-11-03),
#: and a board that does not look like a real perfboard was the complaint it answered.
#: A body's contact shadow (the nearer of its two layers; the farther is half) and the
#: light across it from the top left, as alpha out of 255. Screen-only, like the pads:
#: paper gets the flat part.
CONTACT_SHADOW_ALPHA = 85
CONTACT_SHADOW_MM = (0.28, 0.55)
BODY_LIGHT_ALPHA = 40
#: Copper on the face away from the viewer, drawn at this opacity on screen: at full
#: strength it fought the pads in front of it.
FAR_SIDE_OPACITY = 0.55
#: The edge round far-side copper on screen (``ConductorItem._paint_back_layer``): what
#: makes a silver wire readable across the pale pads it passes over.
FAR_SIDE_EDGE = QColor(20, 26, 34, 210)
SELECTED = QColor(CANVAS_SELECTED)
ERROR_OUTLINE = QColor(CANVAS_ERROR)
WARNING_OUTLINE = QColor(CANVAS_WARNING)
#: The part on the far side, seen through the board. Dim on purpose: on the solder side
#: the pads are the subject, and anything that competes with them for attention is a way
#: to solder the wrong pad.
BODY_SHADOW = QColor("#95a3b8")
BODY_SHADOW_EDGE = QColor("#6d7a8c")
RISK_RING = QColor(CANVAS_ERROR)
#: A finding the build guide checks at the bench (``guide.is_bench_check``) is not a problem,
#: and its rings say so: in the dim colour the Problems drawer counts it in, and UNDER the
#: parts, over the copper they are about (``BENCH_RING_Z``). In danger red over every part,
#: two of them under a 5 mm LED read as an "8" on its dome, and told the opposite story from
#: the bar beneath. Picked or hovered in the drawer, its rings come up over the parts in
#: ``RISK_RING`` (``BoardScene.set_focused_holes``).
BENCH_RING = QColor(theme.ACTIVE.text_secondary)
#: Over the pads (-90) and the strips and spines (-84), under the parts (10) and the copper on
#: the side looked at (40).
BENCH_RING_Z = -80
#: Over every part: where a finding's rings go while it is a problem, or picked.
RISK_RING_Z = 60
#: The wiring before the last route, while it is compared with today's: over the copper
#: and under the rings, in a colour no copper is drawn in.
BEFORE_COPPER = QColor(236, 112, 255, 210)
BEFORE_COPPER_Z = RISK_RING_Z - 1
#: The ruler is drawn on the canvas, outside the board, so it is the theme's too.
RULER_TEXT = QColor(theme.ACTIVE.canvas_ruler)
RULER_TEXT_MAJOR = QColor(theme.ACTIVE.canvas_ruler_major)


def _set_colour(target: QColor, hex_colour: str) -> None:
    parsed = QColor(hex_colour)
    target.setRgb(parsed.red(), parsed.green(), parsed.blue(), parsed.alpha())


def sync_theme(tokens: theme.Tokens | None = None) -> None:
    """Update the canvas, ruler and bench-ring colours in place after a live theme switch."""
    active = theme.ACTIVE if tokens is None else tokens
    _set_colour(BACKGROUND, active.canvas)
    _set_colour(BENCH_RING, active.text_secondary)
    _set_colour(RULER_TEXT, active.canvas_ruler)
    _set_colour(RULER_TEXT_MAJOR, active.canvas_ruler_major)


theme.on_change(sync_theme)
#: Silkscreen. White ink on the board it is printed on, and a dim ghost of it when the
#: board is turned over -- the same convention component bodies on the far side follow.
LEGEND_INK = QColor("#eef2f8")
LEGEND_INK_FAR = QColor(190, 200, 215, 70)


def legend_ink(board: Board, near: bool) -> QColor:
    """The legend's colour on this board: white silkscreen on a masked board, the pads'
    copper on an unmasked one (``BoardScheme.etched``), and dim from the face it is not on."""
    scheme = scheme_for(board)
    if not scheme.etched:
        return QColor(LEGEND_INK if near else LEGEND_INK_FAR)
    ink = QColor(scheme.legend_ink())
    if not near:
        ink.setAlpha(LEGEND_INK_FAR.alpha())
    return ink
#: A mounting hole: the bore is a hole, so it is near black; the head ring is a keepout
#: rather than a thing, so it is a dashed outline in the warning colour.
MOUNT_BORE = QColor("#14151b")
MOUNT_EDGE = QColor("#0a0b0f")
MOUNT_KEEPOUT = QColor(229, 116, 61, 150)
#: A connector finger on the far face of the board.
FINGER_FAR = QColor(150, 130, 70, 110)
#: A track cut. The error colour, because a cut in the wrong hole is an error you cannot
#: see on the finished board from more than arm's length.
CUT_MARK = QColor(CANVAS_ERROR)

#: Ratsnest colours by net class -- ground and power read as rails at a glance, which is
#: the same distinction the router orders its work by. The sheet draws its wires in the
#: same three, from the same table (``theme.NET_COLOURS``).
RATSNEST = {net_class: QColor(colour) for net_class, colour in NET_COLOURS.items()}
RATSNEST_HIGHLIGHT = QColor("#ffd166")

#: kind -> (colour, stroke width mm, dashed).
#:
#: WIDTHS ARE PHYSICAL, and that is the point. A 1.9 mm pad is the reference: solder
#: sits inside it rather than swallowing it, tinned wire is about half a millimetre, and
#: insulated wire is thicker than bare because of the sleeve. These used to be set for
#: legibility alone, which made every trace wider than the pads it joined and turned a
#: routed board into a diagram of coloured bars with a board somewhere underneath.
#:
#: RED IS NOT A CONDUCTOR COLOUR here. It is the error and R5'-risk colour, and it was
#: also every insulated wire, so a fully correct board looked alarming. Insulated wire
#: now takes its NET's colour instead -- the same convention the build guide's cut list
#: prints, so the screen and the list a person works from agree.
CONDUCTOR_STYLE = {
    "solder-trace": (QColor("#b9bec6"), 0.9, False),
    "solder-trace-wired": (QColor("#aeb4bd"), 1.0, False),
    "bare-wire": (QColor("#dfe4ea"), 0.5, False),
    "insulated-wire": (QColor("#8e97a3"), 0.85, False),
    "top-jumper": (QColor("#8e97a3"), 0.75, True),
    "lead-bend": (QColor("#c2c8d0"), 0.45, False),
    "strip": (QColor("#c8a951"), 2.0, False),
}

#: Insulation colours, matching guide.py's cut list exactly. Named there and mapped to
#: screen colours here, because the guide names a colour a human buys ("black") and this
#: needs one that reads on a dark board.
_INSULATION_SCREEN = {
    "red": QColor("#e05252"),
    "black": QColor("#5c6470"),
    "yellow": QColor("#e2c541"),
    "green": QColor("#5cb85c"),
    "blue": QColor("#5b8dd9"),
    "white": QColor("#e8ecf2"),
    "orange": QColor("#e08b3c"),
    "violet": QColor("#a978d8"),
    "grey": QColor("#9aa2ad"),
    "brown": QColor("#a5764f"),
}

#: The tinned spine inside a wired solder trace, drawn as a core through the solder: a shade
#: warmer and duller than the solder, the same colour as the 3D view's (`view3d.SPINE_RGB`).
SPINE_CORE = QColor("#9e856b")

#: A via in 2D (``ViaMarkItem``): an amber ring round the hole and a pale dot in it, picked
#: from candidates rendered side by side. The ring is wider than a pad on purpose -- it is
#: the one hole on the board where the copper changes face, and it has to be found.
VIA_RING = QColor("#d9962b")
VIA_RING_RADIUS_MM = 1.38
VIA_RING_PEN_MM = 0.2
VIA_DOT = QColor("#f4f1e8")
VIA_DOT_RADIUS_MM = 0.34
VIA_DOT_EDGE = QColor("#6b6f78")
VIA_DOT_EDGE_MM = 0.06

#: What a solder run looks like on screen (not on the 1:1 print, which stays flat): a lit
#: ridge -- a dark casing, the run's colour, a thin highlight off the top-left, a domed
#: joint at every pad. One colour for both run kinds: the brass spine, not a slightly
#: different grey, is what tells a wired run apart. Darker than the paper's silver because
#: the highlight has to have somewhere to go; a run as bright as a pad read as a white bar.
RUN_SCREEN_COLOUR = QColor("#a9afba")

#: A run's width on screen follows its ``buildup``, the way the 3D view's bead is built up:
#: light solder is a thin ridge, heavy a fat one. The paper keeps ``CONDUCTOR_STYLE``'s
#: single width, which is what the print was drawn at.
RUN_BUILDUP_WIDTH = {"light": 0.72, "normal": 1.0, "heavy": 1.3}

#: A tinned wire's end, where the sleeve is stripped back and the solder holds it.
WIRE_END_TIN = QColor("#c9ced6")

#: How far the sleeve is stripped back from each end of an insulated wire, and how far the
#: spine of a wired run sticks out past its last pad -- both measured on the 3D view.
SLEEVE_STRIP_MM = 0.9
SPINE_STUB_MM = 0.85

#: Below this scale (screen pixels per mm) the highlights and gradients are noise: a stray
#: pixel per pad that costs a gradient fill each.
LIT_MIN_SCALE = 6.0


def insulation_color(net_class: NetClass | None, signal_index: int) -> QColor:
    """The colour a wire on this net should be, by the build guide's own convention.

    Red for power and black for ground, then a fixed cycle for signals -- ``signal_index``
    is ``guide.signal_colour_index``, so the same board gets the same colours in the editor
    and in the cut list, just built or reopened. A convention that changed between the
    screen and the printout would be worse than none.
    """
    if net_class is None:
        return CONDUCTOR_STYLE["insulated-wire"][0]
    fixed = COLOR_BY_NET_CLASS.get(net_class)
    name = fixed if fixed is not None else SIGNAL_COLORS[signal_index % len(SIGNAL_COLORS)]
    return _INSULATION_SCREEN.get(name, CONDUCTOR_STYLE["insulated-wire"][0])


def explicit_colour(value: str | None) -> QColor | None:
    """A conductor's OWN colour (``WireConductor.color``), or None for its net's or kind's.

    A name or a hex, read as ``QColor`` reads them. Anything ``QColor`` cannot read is no
    colour at all: an invalid ``QColor`` paints black, a wire nobody chose. The 3D view
    asks this too, so the two views cannot disagree about which wire is blue -- it used to
    read only ``#rrggbb`` and drew a wire named "red" in its net's colour -- and the build
    guide names the same choice in words (``guide.stocked_colour``).
    """
    if not value or not value.strip():
        return None
    colour = QColor(value.strip())
    return colour if colour.isValid() else None


def named_insulation(name: str | None) -> QColor:
    """A wire's colour given by NAME -- a cable wire's own, or the one ``wirecolour`` gives its
    net -- as the board's own wires of that name are drawn: "red" is this view's red, not
    ``QColor``'s. A name the table does not have is read as ``QColor`` reads it, and no name
    at all is the insulated wire's grey. The System view and the System's 3D both draw a
    cable's wires through it, so a cable is one colour in each and on the cut list."""
    if name:
        known = _INSULATION_SCREEN.get(name.strip().lower())
        if known is not None:
            return known
    return explicit_colour(name) or CONDUCTOR_STYLE["insulated-wire"][0]

#: Millimetres of scene reserved outside the substrate for the hole-address rulers.
RULER_MARGIN_MM = 6.0

#: How much of a part's note its tooltip shows before cutting it with an ellipsis: a
#: tooltip that fills the screen hides the board it is about. Part Properties shows it all.
NOTE_TOOLTIP_CHARS = 200

#: Label sizes in SCREEN PIXELS, not millimetres or points -- see ui/scenetext.py. These
#: hold their size while the board zooms, which is both what an annotation should do and
#: what keeps them clear of the size below which some font engines draw nothing.
RULER_LABEL_PX = 11
#: Device-pixel gap between the board outline and ruler / echoed legend labels, so the
#: clearance holds at low zoom (6 px/mm) instead of shrinking with scene millimetres.
RULER_GAP_PX = 6.0
REF_LABEL_PX = 12
#: How a part's reference sits on its anchor (``ComponentItem.reference_anchor``): centred,
#: and ABOVE the point in draw_label's terms, two device pixels clear. One pair for the
#: layer that prints the references and for the part's hit area, which takes the label in.
REF_LABEL_ALIGN = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
REF_LABEL_OFFSET = QPointF(0, -2)
#: Below this many pixels per millimetre the references are not printed at all.
REF_LABEL_MIN_SCALE = 3.0

#: The nets' names on the wires (Show on the Board > Net Names on Wires), on a flag like the
#: sheet's net labels and held at a pixel size like every label here. Below
#: ``NET_NAME_MIN_SCALE`` pixels per millimetre none is drawn: zoomed out the board is a
#: picture, and names on it are noise. Up to ``NET_NAME_EVERY_RUN_SCALE`` each net is named
#: once, on its longest straight run; past it, on every straight run of
#: ``NET_NAME_MIN_RUN_PITCHES`` holes or more. Chosen 2026-11-18 from rendered candidates:
#: one flag per net at fit and one per run zoomed in, over a flag on every run at every zoom
#: (crowded at fit) and over plain text beside the run (lost against the copper).
NET_NAME_PX = 11
NET_NAME_MIN_SCALE = 4.5
NET_NAME_EVERY_RUN_SCALE = 9.0
NET_NAME_MIN_RUN_PITCHES = 3
#: The flag's ground, the sheet's dark plate: a name in its net's colour on its own ground
#: reads over solder, over a wire of any colour and over a part's body alike.
NET_NAME_FILL = QColor("#1c2026")
#: A black wire's black is the one colour that does not read on that ground, so its name is
#: written a step lighter: still the darkest name on the board.
NET_NAME_BLACK = QColor("#8b93a0")
#: A part's value, after its reference on the same plate (View > Show Part Values): a step
#: dimmer than the reference, so the name still reads first.
VALUE_LABEL = QColor("#aeb6c8")
#: The reference and value on paper, in millimetres (``draw_printed_reference``), standing
#: a gap above the body as the editor's stand a few pixels above it. The reference a little
#: taller than the pin names' 0.9 mm, as the name of a part outranks the name of a pin; the
#: value a step under them, so the name reads first and a plate stays short. Chosen from
#: prints rendered side by side.
PRINT_REF_LABEL_MM = 1.1
PRINT_VALUE_LABEL_MM = 0.85
PRINT_REF_GAP_MM = 0.4


# --------------------------------------------------------------------- coordinates


def _outline_rect(board: Board) -> QRectF:
    """The substrate as a Qt rect, from ``geometry.board_outline_mm``.

    Every item that needs to know where the board's edge is asks this rather than
    assuming half a pitch past the outer holes: a board with a printed border has more
    substrate than that, and an item that guessed would draw its edge in the wrong place
    while the substrate underneath drew its own somewhere else.
    """
    outline = board_outline_mm(board)
    return QRectF(outline.x, outline.y, outline.width, outline.height)


def mm_to_screen(x_mm: float, y_mm: float, board: Board, side: BoardSide) -> QPointF:
    """A board-millimetre point -> scene position, for whichever side is being VIEWED.

    The same reflection :func:`hole_to_screen` applies, for the things that are NOT on the
    grid: a mounting bore sitting in the printed border, a finger's inset. About the hole
    span, never the substrate -- see the comment on ``hole_to_screen``.
    """
    if side == "bottom":
        span_w, _span_h = hole_span_mm(board)
        return QPointF(span_w - x_mm, y_mm)
    return QPointF(x_mm, y_mm)


def hole_to_screen(hole: HoleCoord, board: Board, side: BoardSide) -> QPointF:
    """Hole -> scene position (mm), for whichever side is being VIEWED.

    'top' is the identity mapping (col*pitch, row*pitch), same as
    ``geometry.hole_to_mm``. 'bottom' reflects x about the hole span's midpoint using
    ``geometry.hole_span_mm`` -- NOT ``board_size_mm`` -- so hole (0, r) lands exactly
    on the screen position hole (cols-1, r) occupies from the top, and vice versa.
    """
    x = hole.col * board.pitch
    y = hole.row * board.pitch
    if side == "bottom":
        span_w, _span_h = hole_span_mm(board)
        x = span_w - x
    return QPointF(x, y)


def path_point_to_screen(
    hole: HoleCoord, board: Board, side: BoardSide, cells: Mapping[str, FingerCell]
) -> QPointF:
    """One point of a conductor's path -> scene position (mm), for the side being VIEWED.

    :func:`hole_to_screen` for every hole of the grid. A finger cell -- the place one step
    outside the grid where solder lies on a stock board's outside finger -- is drawn on the
    finger's copper (``geometry.path_point_mm``), which on most stock boards is not where a
    hole one pitch further out would be: on the 6 x 8 cm board that is the gap between two
    fingers. Mirrored for the solder side about the hole span, as every hole is. With no
    cells this is exactly ``hole_to_screen``.
    """
    if not cells:
        return hole_to_screen(hole, board, side)
    point = path_point_mm(hole, board, cells)
    x = point.x
    if side == "bottom":
        span_w, _span_h = hole_span_mm(board)
        x = span_w - x
    return QPointF(x, point.y)


def screen_to_hole(point: QPointF, board: Board, side: BoardSide) -> HoleCoord:
    """Inverse of :func:`hole_to_screen`. Rounds to the nearest hole."""
    x = point.x()
    if side == "bottom":
        span_w, _span_h = hole_span_mm(board)
        x = span_w - x
    col = round(x / board.pitch)
    row = round(point.y() / board.pitch)
    return HoleCoord(col=col, row=row)


def _local_offset_mm(
    x_mm: float, y_mm: float, comp: ComponentInstance, side: BoardSide
) -> tuple[float, float]:
    """Millimetre variant of :func:`_local_offset`, for body geometry rather than pin steps.

    Pin offsets are grid steps and get scaled by the pitch afterwards; a body dimension is
    already in millimetres, so it must not be scaled again.
    """
    dx, dy = transform_offset(x_mm, y_mm, comp.rotation, comp.mirrored)
    if side == "bottom":
        dx = -dx
    return dx, dy


def _local_offset(x0: float, y0: float, comp: ComponentInstance, side: BoardSide) -> tuple[float, float]:
    """A component-local offset (body vertex or pin, in mm/grid-steps), transformed by
    the component's own rotation/mirror AND, if we are viewing the solder side, by the
    same x-reflection ``hole_to_screen`` applies to its anchor -- so the component's
    silhouette and pin markers flip along with the board instead of merely sliding to a
    mirrored anchor while still facing the wrong way.
    """
    dx, dy = transform_offset(x0, y0, comp.rotation, comp.mirrored)
    if side == "bottom":
        dx = -dx
    return dx, dy


# ------------------------------------------------------------------ pad grid item


class PadGridItem(QGraphicsItem):
    """The whole hole grid as ONE item, painting only what is exposed.

    ONE PAD IS DRAWN, ONCE, INTO A PIXMAP, and blitted per hole. That is the difference
    between a large board being usable and not: painting a 100x60 board (6000 holes) the
    obvious way -- a filled ring, a sheen arc and a drill circle per hole, three
    antialiased ellipse passes -- measured 124 ms a frame, which is 8 fps and feels like
    treacle to pan. Blitting a pre-rendered pad measured 12 ms. Ten times faster for a
    pad that looks the same, because every pad on a board is identical by definition and
    rasterising it 6000 times is 6000 times more work than necessary.

    Two approaches that did NOT work, recorded so nobody spends the afternoon again:
    collecting every ring into one even-odd QPainterPath and filling it in a single call
    took 5.8 SECONDS (Qt's scanline fill degrades badly past a few thousand subpaths),
    and turning antialiasing off only got 124 ms to 64 ms while making the board look
    cheap.

    Qt's ``exposedRect`` culling still does the first and largest share of the work: when
    zoomed in, most of the grid is never considered at all.
    """

    #: Pad sizes are bucketed to this many device pixels before the cache is rebuilt.
    #: Without bucketing, a smooth zoom re-rasterises the pad every frame and hands back
    #: the cost the cache exists to remove.
    _SIZE_BUCKET_PX = 4

    def __init__(
        self,
        board: Board,
        side: BoardSide,
        consumed: frozenset[str] = frozenset(),
        copper: bool = True,
    ) -> None:
        super().__init__()
        self.board = board
        self.side = side
        #: False draws the drilled holes with no copper round them -- the component side
        #: of a single-sided board, which still has every hole and none of the pads.
        #: Without this that face renders as a blank slab, which is the same mistake the
        #: 3D view's `build_drills` exists to correct.
        self.copper = copper
        #: Hole keys with no ordinary round pad on this face -- a mounting bore took the
        #: copper, or a connector finger IS the pad here. Passed in rather than derived,
        #: because it is a property of the whole document and this is a paint path: it
        #: must not walk the mounting holes once per hole.
        self.consumed = consumed
        self.drawn = 0
        #: Long side in px -> the pad rasterised that way.
        self._pads: dict[int, QPixmap] = {}
        self.setZValue(-90)

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board)

    def _pad_for(self, long_px: float) -> QPixmap:
        """A pad rasterised for roughly this on-screen size, cached between frames.

        Not necessarily square. An oblong pad is a stadium -- a rectangle capped with a
        semicircle at each end, which is what the copper on those boards actually is --
        so the pixmap carries the pad's aspect ratio and everything below is expressed
        as a fraction of it rather than of a single "side".
        """
        bucket = max(
            self._SIZE_BUCKET_PX,
            round(long_px / self._SIZE_BUCKET_PX) * self._SIZE_BUCKET_PX,
        )
        # Rendered at twice the on-screen size so the downscale stays crisp when the zoom
        # sits between two buckets, and capped so a deep zoom cannot ask for a huge one.
        long_side = min(256, max(6, bucket * 2))
        cached = self._pads.get(long_side)
        if cached is not None:
            return cached

        extent_x, extent_y = pad_extent_mm(self.board)
        longest = max(extent_x, extent_y)
        width = max(3, round(long_side * extent_x / longest))
        height = max(3, round(long_side * extent_y / longest))

        pixmap = QPixmap(width, height)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.copper:
            drill_only = long_side * (self.board.drill_diameter / longest)
            painter.setPen(QPen(QColor("#2b1d0e"), max(1.0, long_side * 0.03)))
            painter.setBrush(QBrush(DRILL))
            painter.drawEllipse(
                QRectF(
                    (width - drill_only) / 2, (height - drill_only) / 2, drill_only, drill_only
                )
            )
            painter.end()
            self._pads[long_side] = pixmap
            return pixmap
        inset = long_side * 0.03
        ring = QRectF(inset, inset, width - 2 * inset, height - 2 * inset)
        scheme = scheme_for(self.board)
        painter.setPen(QPen(QColor(scheme.pad_ring), max(1.0, long_side * 0.05)))
        painter.setBrush(QBrush(QColor(scheme.pad)))
        # Radius = half the short side, which turns the rounded rect into a true stadium
        # and, on a square pad, into the circle this used to draw.
        radius = min(ring.width(), ring.height()) / 2
        painter.drawRoundedRect(ring, radius, radius)

        # The sheen reads as tinned copper catching the light rather than a flat yellow
        # disc, and it is what makes the board look like a board. Skipped only when the
        # pad is too small on screen for the arc to be more than a smudge.
        if long_side >= 20:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(scheme.pad_sheen), max(1.0, long_side * 0.055)))
            sheen_w, sheen_h = width * 0.68, height * 0.68
            painter.drawArc(
                QRectF((width - sheen_w) / 2, (height - sheen_h) / 2, sheen_w, sheen_h),
                60 * 16,
                100 * 16,
            )

        drill_w = long_side * (self.board.drill_diameter / longest)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(DRILL))
        painter.drawEllipse(
            QRectF((width - drill_w) / 2, (height - drill_w) / 2, drill_w, drill_w)
        )
        painter.end()

        self._pads[long_side] = pixmap
        return pixmap

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        b = self.board
        area = option.exposedRect
        extent_x, extent_y = pad_extent_mm(b)
        half_x, half_y = extent_x / 2, extent_y / 2

        c0 = max(0, int((area.left() - half_x) / b.pitch) - 1)
        c1 = min(b.cols - 1, int((area.right() + half_x) / b.pitch) + 1)
        r0 = max(0, int((area.top() - half_y) / b.pitch) - 1)
        r1 = min(b.rows - 1, int((area.bottom() + half_y) / b.pitch) + 1)

        px_per_mm = painter.transform().m11() or 1.0
        long_px = max(extent_x, extent_y) * abs(px_per_mm)
        pixmap = self._pad_for(long_px)
        source = QRectF(0, 0, pixmap.width(), pixmap.height())

        count = 0
        for col in range(c0, c1 + 1):
            for row in range(r0, r1 + 1):
                # A mounting bore removed this pad. Drawing it anyway would show copper
                # to solder to where there is a hole, which is the one thing the DRC rule
                # for it exists to prevent somebody discovering with an iron in hand.
                if self.consumed and hole_key(HoleCoord(col, row)) in self.consumed:
                    continue
                p = hole_to_screen(HoleCoord(col, row), b, self.side)
                painter.drawPixmap(
                    QRectF(p.x() - half_x, p.y() - half_y, extent_x, extent_y), pixmap, source
                )
                count += 1
        self.drawn = count


# --------------------------------------------------------------------- rulers


class HoleRulerItem(QGraphicsItem):
    """Column letters along the top and row numbers down the left side.

    The whole tool speaks in hole addresses -- the build guide says "R3: C7 to C11", DRC
    says "check isolation at C7", the router's explanations name pads (PLAN.md Sec 4.1).
    Without a ruler the user has to count holes to find any of them, which is exactly the
    error-prone manual step this project exists to remove. The labels come from
    ``geometry.column_label``/``row_label``, so they cannot drift from the addresses the
    rest of the system prints.

    Every label is drawn on a dense board, so minor ticks are thinned by ``step`` while
    every fifth stays bright -- the same reading aid as a ruler's long and short marks.
    """

    def __init__(self, board: Board, side: BoardSide) -> None:
        super().__init__()
        self.board = board
        self.side = side
        self.setZValue(80)

    def boundingRect(self) -> QRectF:
        # Generously padded: the labels are a fixed pixel size, so the scene-space room they
        # need grows without limit as the view zooms out (see scenetext.label_extent_mm).
        # An over-large rect only widens a repaint region; too small leaves label debris on
        # the substrate when the view scrolls.
        outline = _outline_rect(self.board)
        pad = RULER_MARGIN_MM + 30
        return outline.adjusted(-pad, -pad, pad, pad)

    def _label_step(self, scale: float) -> int:
        """How many holes to skip between labels, so they never collide.

        Derived from the current view scale rather than fixed: zoomed out, one label in
        five is legible and one per hole is a grey smear; zoomed in, every hole fits.
        """
        px_per_hole = self.board.pitch * scale
        if px_per_hole >= 22:
            return 1
        if px_per_hole >= 11:
            return 2
        return 5

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        board = self.board
        scale = painter.transform().m11() or 1.0
        step = self._label_step(scale)

        outline = _outline_rect(board)
        for col in range(board.cols):
            if col % step and (col + 1) % 5:
                continue
            major = (col + 1) % 5 == 0 or col == 0
            painter.setPen(QPen(RULER_TEXT_MAJOR if major else RULER_TEXT))
            x = hole_to_screen(HoleCoord(col, 0), board, self.side).x()
            # ``draw_label`` aligns inside a box centred on the anchor (see viewsch.label_alignment):
            # AlignTop puts text ABOVE the anchor, AlignLeft puts text LEFT of it.
            draw_label(
                painter,
                QPointF(x, outline.top()),
                column_label(col),
                RULER_LABEL_PX,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                bold=major,
                offset=QPointF(0.0, -RULER_GAP_PX),
            )

        for row in range(board.rows):
            if row % step and (row + 1) % 5:
                continue
            major = (row + 1) % 5 == 0 or row == 0
            painter.setPen(QPen(RULER_TEXT_MAJOR if major else RULER_TEXT))
            draw_label(
                painter,
                QPointF(outline.left(), row * board.pitch),
                row_label(row),
                RULER_LABEL_PX,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                bold=major,
                offset=QPointF(-RULER_GAP_PX, 0.0),
            )


class LegendEchoItem(QGraphicsItem):
    """A printed address something stands on, said again just outside the board.

    The legend is ink on the substrate, so a part standing on it hides it, as it does on
    the real board -- a terminal on the first column took the row numbers beside it, a
    pin name or a reference the letter under it -- and the ruler that would name those
    holes stands down while the board prints its own (``BoardScene._build``). So each
    address hidden there is drawn where the ruler would draw it, in the ruler's style and
    at its pixel size, and only that one: the rest the board says itself. Outside the
    outline, so it is on screen and never on the 1:1 print, which renders the outline
    alone. Chosen 2026-11-23 from rendered candidates.
    """

    def __init__(self, scene: BoardScene, legend: BoardLegendItem) -> None:
        super().__init__()
        self._scene = scene
        self.legend = legend
        self.board = legend.board
        self.side = legend.side
        #: ``hidden`` at the last zoom it was asked at: a pan repaints every frame, and the
        #: answer changes with the zoom alone (a reference's plate holds a pixel size)
        #: until the scene is rebuilt, which makes a new item.
        self._hidden: tuple[float, list[tuple[QPointF, str, float]]] | None = None
        self.setZValue(80)

    def boundingRect(self) -> QRectF:
        # Padded as the ruler's is, for the same reason: a pixel-sized label needs more
        # scene room the further out the view is zoomed.
        pad = RULER_MARGIN_MM + 30
        return _outline_rect(self.board).adjusted(-pad, -pad, pad, pad)

    def hidden(self, transform: QTransform) -> list[tuple[QPointF, str, float]]:
        """Each printed address something stands on at this zoom: (centre, text,
        rotation), in scene millimetres."""
        covers: list[QRectF] = []
        for item in self._scene.component_items.values():
            if not item.isVisible() or not item.faces_the_viewer():
                continue
            covers.append(item.mapRectToScene(item._local_body_rect()))
            covers.extend(item.mapRectToScene(rect) for rect in item.pin_name_rects())
        under_references = self.legend.covered_labels(transform)
        return [
            (centre, text, rotation)
            for index, ((centre, text, _height, _wide, rotation, _ink), rect) in enumerate(
                zip(self.legend._printed(), self.legend.label_rects(), strict=True)
            )
            if index in under_references or any(rect.intersects(cover) for cover in covers)
        ]

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        outline = _outline_rect(self.board)
        painter.setPen(QPen(RULER_TEXT_MAJOR))
        transform = painter.worldTransform()
        if self._hidden is None or self._hidden[0] != transform.m11():
            self._hidden = (transform.m11(), self.hidden(transform))
        for centre, text, rotation in self._hidden[1]:
            if rotation:
                # A row number, beside the edge it is printed along. ``draw_label`` aligns
                # inside a box centred on the anchor, so AlignLeft sits left of the anchor
                # and AlignRight sits right of it (opposite of Qt's usual reading).
                left = centre.x() < outline.center().x()
                draw_label(
                    painter,
                    QPointF(outline.left() if left else outline.right(), centre.y()),
                    text,
                    RULER_LABEL_PX,
                    (Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignRight)
                    | Qt.AlignmentFlag.AlignVCenter,
                    bold=True,
                    offset=QPointF(-RULER_GAP_PX if left else RULER_GAP_PX, 0.0),
                )
            else:
                top = centre.y() < outline.center().y()
                draw_label(
                    painter,
                    QPointF(centre.x(), outline.top() if top else outline.bottom()),
                    text,
                    RULER_LABEL_PX,
                    Qt.AlignmentFlag.AlignHCenter
                    | (Qt.AlignmentFlag.AlignTop if top else Qt.AlignmentFlag.AlignBottom),
                    bold=True,
                    offset=QPointF(0.0, -RULER_GAP_PX if top else RULER_GAP_PX),
                )


# ------------------------------------------------- printed legend and board features


class BoardLegendItem(QGraphicsItem):
    """The hole addresses the BOARD itself carries, printed on the substrate.

    Not the same thing as :class:`HoleRulerItem`, and the difference is the whole point.
    The ruler is an annotation this program draws outside the board and sizes in screen
    pixels, so it holds its size as you zoom. This is silkscreen: it is ink on the
    substrate, it is there when you are holding the board with the program closed, and
    it therefore scales with the board like every other physical dimension in this scene.
    That is also what makes it come out right on the 1:1 PDF, which is the copy that ends
    up taped to the board.

    It lives in the half-pitch margin the substrate extends past the outer hole centres
    (``geometry.board_size_mm``), because that is the only room there is. Real boards with
    a wider printed border have a margin this format does not model.

    SEEN FROM THE OTHER SIDE the legend is drawn dim, and NOT mirrored. Mirroring the
    glyphs would be the physically accurate thing and the useless one: reversed 1 mm text
    is noise, and what the reader wants from a label is the address, not the reflection.
    The position is mirrored -- that comes free from ``hole_to_screen`` -- so a label
    still sits over the hole it names.
    """

    def __init__(self, document: PerfDocument, labels: BoardLabels, side: BoardSide) -> None:
        super().__init__()
        self.document = document
        self.board = document.board
        self.labels = labels
        self.side = side
        #: Printed on this face, or seen faintly through the board from the other one.
        self.near_side = labels.face == "both" or labels.face == side
        self._rects: list[QRectF] | None = None
        self.setZValue(-95)  # On the substrate, under the pads: ink goes on first.

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        # On paper every address is printed: the references there are millimetres over
        # their bodies, and this is the copy taped to the board.
        covered = set() if _on_paper(painter) else self.covered_labels(painter.transform())
        painter.save()
        painter.setPen(QPen(legend_ink(self.board, self.near_side)))
        for index, (centre, text, height, wide, rotation, _ink) in enumerate(self._printed()):
            if index in covered:
                continue
            draw_physical_label(
                painter, centre, text, height, max_width_mm=wide, rotation_deg=rotation
            )
        painter.restore()

    def label_rects(self) -> list[QRectF]:
        """The box of every address this board prints, in scene millimetres -- what a part's
        reference keeps off where it can (``ComponentItem.reference_placement``). Walked once
        per item: the scene builds a new one for a new document."""
        if self._rects is None:
            self._rects = []
            for centre, _text, height, _wide, rotation, ink in self._printed():
                width, tall = (height, ink) if rotation else (ink, height)
                self._rects.append(
                    self.mapRectToScene(
                        QRectF(centre.x() - width / 2, centre.y() - tall / 2, width, tall)
                    )
                )
        return self._rects

    def covered_labels(self, transform: QTransform) -> set[int]:
        """The labels a printed reference lies on at this zoom, left out there.

        A reference keeps off the legend where it can, over its part or under it, and where
        it cannot it still prints: a letter is one of a run anybody reads from its
        neighbours, and U1 is the board's only name for its chip -- hidden, atmega328-relay
        opened without it. So the letter under it gives way at that zoom, and nothing else
        does: a reference yields to a note, and never moves onto a pin name."""
        scene = self.scene()
        if scene is None or (transform.m11() or 1.0) < REF_LABEL_MIN_SCALE:
            return set()
        plates = []
        for item in getattr(scene, "component_items", {}).values():
            if not item.show_reference or not item.isVisible():
                continue
            placement = item.reference_placement(transform)
            if placement is not None:
                plates.append(item.reference_rect(transform.map(placement[0]), placement[1]))
        if not plates:
            return set()
        return {
            index
            for index, rect in enumerate(self.label_rects())
            if any(transform.mapRect(rect).intersects(plate) for plate in plates)
        }

    def _printed(self) -> Iterator[tuple[QPointF, str, float, float, float, float]]:
        """Each label this board prints: (centre, text, cap height, widest it may be,
        rotation, its ink's width) -- one walk for painting and for ``label_rects``."""
        board = self.board
        # WHERE AND HOW TALL is one answer for both views and the print
        # (`geometry.legend_layout`): the bare band along each edge a run is printed on, NOT
        # the whole margin -- the outer pads eat half their extent of it, and an edge strip
        # takes what it takes -- with the cap height the narrowest of those bands allows.
        layout = legend_layout(self.document, self.labels)
        height = layout.height

        # Letters along the top (and bottom), numbers down the left (and right) -- the
        # layout every board in this class uses, and the reason `all_edges` defaults to
        # true: with one edge each, the far half of the board is nearest the edge that
        # does not carry its address, which is where counting starts again.
        #
        # Each run is centred in ITS OWN free strip, which is why the two offsets differ:
        # a column letter clears the copper above it, a row number clears it to its left.
        #
        # MEASURED IN FROM THE BOARD EDGE, not out from the pad. The two agree on a plain
        # board and do not on one with connector fingers, where the copper reaches most of
        # the way to the edge: measured from the pad, the letters land ON the fingers, and
        # since ink is drawn under copper they vanish entirely. `legend_strip_mm` already
        # reports the right WIDTH there (the fingers' inset); this is the matching
        # position for it.
        #
        # THE NUMBERS ARE TURNED ON THEIR SIDE, as they are on the real boards, and for a
        # reason rather than as decoration: the strip beside a row is narrow across and a
        # whole pitch deep, so an upright "07" has to shrink to fit while a turned one
        # does not.
        span_w, _span_h = hole_span_mm(board)
        column_ys = list(layout.column_ys)
        row_xs = list(layout.row_xs)
        if self.side == "bottom":
            # A run is on a PHYSICAL edge, and turning the board over moves that edge to the
            # other side of the screen. Reflected about the hole span like every other x
            # here, never about the substrate -- see the module note.
            row_xs = [span_w - x for x in row_xs]

        # A LABEL IS NOT PRINTED WHERE A BORE HAS BEEN DRILLED. Ink goes on the substrate
        # and a mounting hole takes the substrate away, so the letter is not faint there,
        # it is absent -- which is what a real board shows and what the corner of this one
        # was not. `printed_label_is_clear` is asked in board millimetres, y growing down,
        # so the column run passes its unmirrored x.
        wide = board.pitch * 0.9
        # WHAT THE BOARD PRINTS (`printed_label`), the same answer the 3D board gives: a
        # board counting A..Z and then A..P again shows exactly that, and a hole it
        # leaves unmarked gets nothing.
        for col in range(board.cols):
            column_text = printed_label("columns", col, self.labels)
            if column_text is None:
                continue
            x = hole_to_screen(HoleCoord(col, 0), board, self.side).x()
            ink = legend_ink_width_mm(column_text, height, wide)
            for y in column_ys:
                if not printed_label_is_clear(
                    self.document, Point2(col * board.pitch, y), ink, height
                ):
                    continue
                yield QPointF(x, y), column_text, height, wide, 0.0, ink

        for row in range(board.rows):
            text = printed_label("rows", row, self.labels)
            if text is None:
                continue
            for x in row_xs:
                # Turned on its side, so its box is turned too.
                ink = legend_ink_width_mm(text, height, wide)
                if not printed_label_is_clear(
                    self.document,
                    Point2(x if self.side == "top" else _span_w_for(board) - x, row * board.pitch),
                    height,
                    ink,
                ):
                    continue
                yield QPointF(x, row * board.pitch), text, height, wide, -90.0, ink


class BoardTextItem(QGraphicsItem):
    """What the board is printed with besides its legend -- its size, a batch code, a
    maker's name (``model.BoardText``). Silkscreen like the legend: it scales with the
    board, is drawn under the pads, comes out on the 1:1 print, and is dim and unmirrored
    from the face it is not printed on, for the legend's reasons.

    Placed by ``geometry.board_text_placement``, the one answer the 3D board and the
    legend's own clear-check also ask, so a letter the line covers is left off in both
    views and the line is in the same place in both.
    """

    def __init__(self, document: PerfDocument, side: BoardSide) -> None:
        super().__init__()
        self.document = document
        self.board = document.board
        self.side = side
        self.setZValue(-95)  # The legend's: ink on the substrate, under the pads.

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        span_w = _span_w_for(self.board)
        painter.save()
        for line in self.board.printed:
            centre, _width, _height, turn = board_text_placement(self.document, line)
            height = _width if turn else _height
            if height <= 0:
                continue
            painter.setPen(QPen(legend_ink(self.board, line.face == self.side)))
            # Mirrored about the hole span on the solder side, like every other x here.
            x = centre.x if self.side == "top" else span_w - centre.x
            draw_physical_label(
                painter, QPointF(x, centre.y), line.text, height, rotation_deg=turn
            )
        painter.restore()


def _span_w_for(board: Board) -> float:
    """The hole span's width, for un-mirroring an x that was mirrored for the solder side."""
    span_w, _span_h = hole_span_mm(board)
    return span_w


#: A label on the board: warm white ink -- a paint marker's -- on a dark tag, so it reads
#: over pads, strips and copper alike.
BOARD_NOTE_INK = "#f7f2df"
BOARD_NOTE_TAG = QColor(24, 26, 31, 228)
#: How finely a dragged label lands: fine enough to line up with anything, coarse enough
#: that a file does not fill with 1.2345 mm offsets from an unsteady hand.
BOARD_NOTE_SNAP_MM = 0.25


class BoardNoteItem(QGraphicsItem):
    """A label written on the board -- ``model.BoardNote``.

    Drawn only from the face it is written on: a label on the solder side is not visible
    from above, any more than a marker note on the back of a real board is. Selectable,
    and dragged anywhere: on release the scene turns where it was dropped back into a hole
    and an offset (``BoardScene.commit_pending_moves``), which is how the file stores it.
    """

    def __init__(self, note: BoardNote, board: Board, side: BoardSide) -> None:
        super().__init__()
        self.note = note
        self.board = board
        self.side = side
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        # Over the parts: a label is written on top of whatever it is about.
        self.setZValue(60)
        centre = board_note_centre_mm(note, board)
        self.home = mm_to_screen(centre.x, centre.y, board, side)
        self.setPos(self.home)
        # Home is where it SITS, snapped (``itemChange``), not where the file put it: a label
        # whose offset is off the snap step -- nano-relay's two, at 0.86 and 1.01 mm -- was
        # "moved" from the moment it was drawn, and every drag of anything else on the board
        # wrote it back snapped, as an "Edit a label on the board" nobody made.
        self.home = self.pos()
        self._width = physical_label_width_mm(note.text, note.size_mm) + 0.8
        self._height = note.size_mm * 1.8

    @property
    def moved(self) -> bool:
        return (self.pos() - self.home).manhattanLength() > 1e-6

    def placement(self) -> tuple[HoleCoord, float, float]:
        """Where it is now, as a label addresses a place: a hole and an offset."""
        x = self.pos().x()
        if self.side == "bottom":
            span_w, _span_h = hole_span_mm(self.board)
            x = span_w - x
        return board_note_anchor(x, self.pos().y(), self.board)

    def _rect(self) -> QRectF:
        return QRectF(-self._width / 2, -self._height / 2, self._width, self._height)

    def boundingRect(self) -> QRectF:
        reach = max(self._width, self._height) / 2 + 0.3
        return QRectF(-reach, -reach, 2 * reach, 2 * reach)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self._rect())
        turned = QPainterPath()
        turned.addPolygon(QTransform().rotate(float(self.note.rotation)).map(path.toFillPolygon()))
        return turned

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        painter.save()
        painter.rotate(float(self.note.rotation))
        painter.setPen(QPen(QColor(SELECTED), 0.2) if self.isSelected() else Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(BOARD_NOTE_TAG))
        painter.drawRoundedRect(self._rect(), 0.4, 0.4)
        painter.setPen(QPen(QColor(BOARD_NOTE_INK)))
        draw_physical_label(painter, QPointF(0.0, 0.0), self.note.text, self.note.size_mm)
        painter.restore()

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Snapped as an OFFSET from the nearest hole, which is what the file stores:
            # snapping the scene position instead gave 1.01 mm for a 1 mm drop, because a
            # hole is not on a quarter-millimetre.
            p: QPointF = value
            centre = hole_to_screen(screen_to_hole(p, self.board, self.side), self.board, self.side)
            step = BOARD_NOTE_SNAP_MM
            x = centre.x() + round((p.x() - centre.x()) / step) * step
            y = centre.y() + round((p.y() - centre.y()) / step) * step
            # And never off the board, which the command refuses: held at the edge rather
            # than let go past it and sent back on release. A hundredth in, since the file
            # rounds the offset to one.
            edge = _outline_rect(self.board).adjusted(0.01, 0.01, -0.01, -0.01)
            return QPointF(
                min(max(x, edge.left()), edge.right()), min(max(y, edge.top()), edge.bottom())
            )
        return super().itemChange(change, value)


class MountingHoleItem(QGraphicsItem):
    """A screw hole: the bore, and -- while it matters -- the ring the screw head will cover.

    The head ring is a keep-out nobody can see otherwise: the bore looks small and harmless,
    and the reason you cannot put a capacitor next to it is the washer, which is not on the
    board yet. But drawn on every hole all the time, a dashed orange ring read as COPPER, a
    ring round the hole the real board does not have. So it is drawn while the pointer is
    over the hole, or while DRC says a part is inside it (``set_flagged``), and not
    otherwise.
    """

    def __init__(self, mount: MountingHole, board: Board, side: BoardSide) -> None:
        super().__init__()
        self.mount = mount
        self.board = board
        self.side = side
        self.flagged = False
        self.hovered = False
        self.setAcceptHoverEvents(True)
        self.setZValue(-85)  # Over the pads it removed, under the parts.
        # Chosen by a click, so Properties shows it -- where it is, its size, Remove.
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def set_flagged(self, flagged: bool) -> None:
        if flagged != self.flagged:
            self.flagged = flagged
            self.update()

    def hoverEnterEvent(self, event: Any) -> None:
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: Any) -> None:
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def _centre(self) -> QPointF:
        """Where the bore actually is.

        ``mounting_hole_centre_mm``, never the hole address: the offset is what lets a
        corner hole sit in the BORDER, and reading the address alone drew every one of
        them back on the grid -- in the middle of four pads that are perfectly intact, and
        a whole pad's width away from where the 3D view and DRC both put it.
        """
        centre = mounting_hole_centre_mm(self.mount, self.board)
        return mm_to_screen(centre.x, centre.y, self.board, self.side)

    def boundingRect(self) -> QRectF:
        centre = self._centre()
        r = max(self.mount.head_diameter, self.mount.diameter) / 2 + 0.5
        return QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        centre = self._centre()
        if self.isSelected() and not _on_paper(painter):
            head_r = self.mount.head_diameter / 2
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(SELECTED, 0.2))
            painter.drawEllipse(centre, head_r, head_r)
        elif (self.flagged or self.hovered) and not _on_paper(painter):
            head_r = self.mount.head_diameter / 2
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(MOUNT_KEEPOUT, 0.12)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawEllipse(centre, head_r, head_r)

        bore_r = self.mount.diameter / 2
        painter.setPen(QPen(MOUNT_EDGE, 0.15))
        painter.setBrush(QBrush(MOUNT_BORE))
        painter.drawEllipse(centre, bore_r, bore_r)


class StripGridItem(QGraphicsItem):
    """The copper the board came with: one bar per uncut run of holes.

    Stripboard's whole character is that these are already connected, and a board drawn
    as a grid of separate pads says the opposite of that. Two pins in one row are joined
    whether or not anybody drew a conductor, so the strip has to be visible or the screen
    is lying about the circuit.

    Drawn from ``stripboard.segments`` rather than from rows, so a cut visibly ends a bar
    -- which is what makes a cut inspectable at a glance, on screen and on the board.
    """

    def __init__(self, doc: PerfDocument, side: BoardSide) -> None:
        super().__init__()
        self.board = doc.board
        self.side = side
        self.segments = segments(doc)
        #: The strips are on the solder side. From the component side they are behind the
        #: board, so they are drawn faintly for reference rather than as copper in front
        #: of you -- the same rule the far-side hatching follows.
        self.far_side = side == "top"
        self.setZValue(-95)  # Under the pads: the strip is etched, then drilled through.

    @property
    def has_strips(self) -> bool:
        return bool(self.segments)

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        if not self.segments:
            return
        scheme = scheme_for(self.board)
        colour = QColor(scheme.pad)
        if self.far_side:
            colour.setAlpha(70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colour))

        extent_x, extent_y = pad_extent_mm(self.board)
        area = option.exposedRect
        for segment in self.segments:
            first = hole_to_screen(segment.holes[0], self.board, self.side)
            last = hole_to_screen(segment.holes[-1], self.board, self.side)
            left, right = sorted((first.x(), last.x()))
            top, bottom = sorted((first.y(), last.y()))
            rect = QRectF(
                left - extent_x / 2,
                top - extent_y / 2,
                (right - left) + extent_x,
                (bottom - top) + extent_y,
            )
            if not area.intersects(rect):
                continue
            radius = min(extent_x, extent_y) / 2
            painter.drawRoundedRect(rect, radius, radius)


#: The opening a lead goes into, across, in mm -- a square, as moulded.
BREADBOARD_HOLE_MM = 1.1
#: How wide the groove down the middle is drawn.
BREADBOARD_GROOVE_MM = 1.6
#: Print heights, in mm of plastic.
BREADBOARD_NUMBER_MM = 1.3
BREADBOARD_LETTER_MM = 1.5


def _pattern_row_y(board: Board, side: BoardSide, row: float) -> float:
    """A row position on screen, fractional rows included."""
    return hole_to_screen(HoleCoord(0, 0), board, side).y() + row * board.pitch


def _pattern_col_x(board: Board, side: BoardSide, col: float) -> float:
    """A column position on screen, mirrored with the board when it is turned over."""
    first = hole_to_screen(HoleCoord(0, 0), board, side).x()
    step = hole_to_screen(HoleCoord(1, 0), board, side).x() - first
    return first + col * step


def breadboard_groove_rects(board: Board, side: BoardSide) -> list[QRectF]:
    """The groove down a breadboard's middle, one rectangle per stretch of
    ``breadboard.channel_stretches``: the ordinary groove widened by every pitch the channel
    is wider, running to the board's edge at either end of the board."""
    outline = _outline_rect(board)
    rects: list[QRectF] = []
    for first, end, upper, lower in channel_stretches(board):
        middle = (_pattern_row_y(board, side, upper) + _pattern_row_y(board, side, lower)) / 2
        width = BREADBOARD_GROOVE_MM + (lower - upper - STANDARD_CHANNEL) * board.pitch
        # A stretch that reaches an end of the board runs to its edge; the step between two
        # is half way between their columns. Measured in columns and sorted afterwards, so
        # it holds on the solder side, where the columns run the other way.
        ends = [first - 0.5 if first else -board.cols, end - 0.5 if end != board.cols else 2 * board.cols]
        xs = [min(max(_pattern_col_x(board, side, at), outline.left()), outline.right()) for at in ends]
        left, right = sorted(xs)
        rects.append(QRectF(left, middle - width / 2, right - left, width))
    return rects


def _paint_rail_lines(painter: QPainter, board: Board, side: BoardSide) -> None:
    """A line beside each rail: outside the outer rail of a pair, inside the inner one, so
    the two lines frame the pair as on Fritzing's MB102. A line that would fall off the
    board is left out -- a solderable breadboard's border is a tenth of a millimetre, and
    its rails are told apart by the signs at their ends."""
    if not has_rails(board):
        return
    outline = _outline_rect(board)
    pitch = board.pitch
    rows = range(board.rows)
    left, right = sorted(
        (_pattern_col_x(board, side, -0.4), _pattern_col_x(board, side, board.cols - 1 + 0.4))
    )
    rail_rows = [row for row in rows if rail_of(board, row) is not None]
    for row in rail_rows:
        rail = rail_of(board, row)
        assert rail is not None
        pair = [r for r in rail_rows if (r < board.rows / 2) == (row < board.rows / 2)]
        away = -1 if row == min(pair) else 1
        y = _pattern_row_y(board, side, row + away * 0.62)
        if not outline.top() + pitch * 0.1 < y < outline.bottom() - pitch * 0.1:
            continue
        painter.setPen(QPen(QColor(BREADBOARD.rail_ink(RAIL_CLASS[rail])), 0.35))
        painter.drawLine(QPointF(left, y), QPointF(right, y))


def _paint_pattern_print(painter: QPainter, board: Board, side: BoardSide, ink: str) -> None:
    """The print a breadboard carries, plastic or copper: column numbers above the top strip
    row and below the bottom one, every five as the boards have them, the row letters at
    both ends, and a + or a - at each end of every rail -- what a builder reads "e12" off."""
    pitch = board.pitch
    rows = range(board.rows)
    painter.save()
    painter.setPen(QColor(ink))
    for col in range(board.cols):
        number = col + 1
        if number != 1 and number % 5:
            continue
        # Per column: where a wide channel narrows, its strips -- and the numbers beside
        # them -- move in with it.
        strip_rows = [row for row in rows if strip_letter(board, row, col) is not None]
        for at_row in (min(strip_rows) - 1.05, max(strip_rows) + 1.05):
            draw_physical_label(
                painter,
                QPointF(_pattern_col_x(board, side, col), _pattern_row_y(board, side, at_row)),
                str(number),
                BREADBOARD_NUMBER_MM,
                bold=False,
                max_width_mm=pitch * 1.6,
            )
    ends = (-1.15, board.cols - 1 + 1.15)
    # The letters at each end are that end's own: a board whose channel narrows has its
    # narrow end's strips on other rows than its wide end's.
    for at_col, col in zip(ends, (0, board.cols - 1), strict=True):
        for row in rows:
            letter = strip_letter(board, row, col)
            if letter is None:
                continue
            draw_physical_label(
                painter,
                QPointF(_pattern_col_x(board, side, at_col), _pattern_row_y(board, side, row)),
                letter,
                BREADBOARD_LETTER_MM,
                bold=False,
            )
    for row in rows:
        rail = rail_of(board, row)
        if rail is None:
            continue
        painter.setPen(QColor(BREADBOARD.rail_ink(RAIL_CLASS[rail])))
        for at_col in ends:
            draw_physical_label(
                painter,
                QPointF(_pattern_col_x(board, side, at_col), _pattern_row_y(board, side, row)),
                "+" if rail.endswith("+") else "−",
                BREADBOARD_LETTER_MM * 1.2,
            )
    painter.restore()


class BreadboardPrintItem(QGraphicsItem):
    """A solderable breadboard's silkscreen: the solderless board's print, in the board's
    own silkscreen ink, on the component side. The copper is ``StripGridItem`` and
    ``PadGridItem`` as on any copper board; this is only what is printed beside it."""

    def __init__(self, board: Board, side: BoardSide, ink: str) -> None:
        super().__init__()
        self.board = board
        self.side = side
        self.ink = ink
        self.setZValue(-96)  # Printed on the substrate, under the copper.

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        if self.side != "top":
            return  # The silkscreen is on the component side.
        _paint_rail_lines(painter, self.board, self.side)
        _paint_pattern_print(painter, self.board, self.side, self.ink)


class BreadboardItem(QGraphicsItem):
    """A solderless breadboard: its holes, the groove a DIP straddles, the rail lines and
    the print -- in place of the pads, the strips and the legend of a copper board.

    The holes follow ``PadGridItem``'s rule and for its reason: ONE opening rasterised once
    and blitted per hole, culled to what is exposed. The print is the board's own -- the
    column numbers every five and the row letters at each end, as an MB102 prints them --
    so it is drawn as silkscreen is, in millimetres that scale with the board, and it is
    what a builder reads "e12" off. From underneath there is no print to read and none is
    drawn; the rail lines stay, because they are what says which rail is which.
    """

    _SIZE_BUCKET_PX = 4

    def __init__(self, board: Board, side: BoardSide) -> None:
        super().__init__()
        self.board = board
        self.side = side
        self.drawn = 0
        self._hole_pixmap: QPixmap | None = None
        self._hole_pixmap_px = 0
        self.setZValue(-90)

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board)

    def _hole_for(self, px: float) -> QPixmap:
        bucket = max(self._SIZE_BUCKET_PX, round(px / self._SIZE_BUCKET_PX) * self._SIZE_BUCKET_PX)
        side = min(128, max(4, bucket * 2))
        if self._hole_pixmap is not None and self._hole_pixmap_px == side:
            return self._hole_pixmap
        pixmap = QPixmap(side, side)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # A moulded opening: a pale chamfer round a dark square, so it reads as a hole in
        # the plastic rather than a dot printed on it.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(BREADBOARD.hole_rim)))
        painter.drawRoundedRect(QRectF(0, 0, side, side), side * 0.18, side * 0.18)
        inset = side * 0.16
        painter.setBrush(QBrush(QColor(BREADBOARD.hole)))
        painter.drawRect(QRectF(inset, inset, side - 2 * inset, side - 2 * inset))
        painter.end()
        self._hole_pixmap = pixmap
        self._hole_pixmap_px = side
        return pixmap

    def _row_y(self, row: float) -> float:
        return _pattern_row_y(self.board, self.side, row)

    def _col_x(self, col: float) -> float:
        return _pattern_col_x(self.board, self.side, col)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        b = self.board
        rows = range(b.rows)

        # The groove down the middle: between the last upper row (f) and the first lower (e),
        # and as much wider than the ordinary one as the channel is.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(BREADBOARD.groove)))
        for rect in breadboard_groove_rects(b, self.side):
            painter.drawRect(rect)

        _paint_rail_lines(painter, b, self.side)

        # The openings.
        area = option.exposedRect
        px_per_mm = abs(painter.transform().m11()) or 1.0
        pixmap = self._hole_for(BREADBOARD_HOLE_MM * px_per_mm)
        source = QRectF(0, 0, pixmap.width(), pixmap.height())
        half = BREADBOARD_HOLE_MM / 2
        count = 0
        for row in rows:
            y = self._row_y(row)
            if y + half < area.top() or y - half > area.bottom():
                continue
            for col in range(b.cols):
                if not has_hole(b, HoleCoord(col, row)):
                    continue
                x = self._col_x(col)
                if x + half < area.left() or x - half > area.right():
                    continue
                painter.drawPixmap(
                    QRectF(x - half, y - half, BREADBOARD_HOLE_MM, BREADBOARD_HOLE_MM), pixmap, source
                )
                count += 1
        self.drawn = count

        if self.side != "top":
            return
        _paint_pattern_print(painter, b, self.side, BREADBOARD.print_ink)


class TrackCutItem(QGraphicsItem):
    """Where the copper has been drilled away.

    A cross rather than a gap, and drawn in the error colour, because a cut is the one
    feature of a stripboard design that is invisible on the finished board from more than
    arm's length -- and getting one in the wrong hole is the classic way to spend an
    evening. The pad is already missing underneath it; this says why.
    """

    def __init__(self, cut: TrackCut, board: Board, side: BoardSide) -> None:
        super().__init__()
        self.cut = cut
        self.board = board
        self.side = side
        self.setZValue(-84)  # Over the pads and the strips, under the parts.

    def boundingRect(self) -> QRectF:
        centre = hole_to_screen(self.cut.at, self.board, self.side)
        r = max(pad_extent_mm(self.board)) / 2 + 0.4
        return QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        centre = hole_to_screen(self.cut.at, self.board, self.side)
        r = max(pad_extent_mm(self.board)) / 2
        painter.setBrush(QBrush(SUBSTRATE.get(self.board.material, SUBSTRATE["FR4"]).darker(140)))
        painter.setPen(QPen(CUT_MARK, 0.14))
        painter.drawEllipse(centre, r, r)
        arm = r * 0.55
        painter.drawLine(
            QPointF(centre.x() - arm, centre.y() - arm), QPointF(centre.x() + arm, centre.y() + arm)
        )
        painter.drawLine(
            QPointF(centre.x() - arm, centre.y() + arm), QPointF(centre.x() + arm, centre.y() - arm)
        )


class EdgeConnectorItem(QGraphicsItem):
    """The finger pads of one edge connector.

    Drawn from ``geometry.edge_finger_rect`` rather than from a local idea of where the
    edge is, so that what is drawn and what DRC measures its gaps against are the same
    rectangle.
    """

    def __init__(
        self, connector: EdgeConnector, document: PerfDocument, side: BoardSide
    ) -> None:
        super().__init__()
        self.connector = connector
        # The DOCUMENT, not just the board: whether a finger still exists depends on the
        # mounting holes, which live on the document beside the connectors.
        self.document = document
        self.board = document.board
        self.side = side
        self.near_side = connector.face == "both" or connector.face == side
        self.setZValue(-88)

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board)

    def _fingers(self) -> list[tuple[QRectF, float]]:
        """Each surviving finger's rectangle on screen, with its corner radius."""
        found: list[tuple[QRectF, float]] = []
        for hole in surviving_finger_holes(self.document, self.connector):
            rect = edge_finger_rect(self.connector, hole, self.board)
            # The rect is in board mm; only x needs the solder-side reflection, and it
            # reflects about the hole span exactly as every other x in this file does.
            left = rect.x
            if self.side == "bottom":
                span_w, _ = hole_span_mm(self.board)
                left = span_w - (rect.x + rect.width)
            found.append((
                QRectF(left, rect.y, rect.width, rect.height),
                finger_corner_radius_mm(self.connector, rect),
            ))
        return found

    def shape(self) -> QPainterPath:
        """The fingers, and nothing else: chosen by a click on one, where the bounding
        rectangle -- the whole board -- would have made every click on the board this."""
        path = QPainterPath()
        for rect, _radius in self._fingers():
            path.addRect(rect)
        return path

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        # The fingers a bore has NOT drilled through: a mounting hole takes the copper
        # wherever it is drilled, and a finger is copper -- this used to draw one intact
        # under a 3.2 mm hole.
        scheme = scheme_for(self.board)
        fingers = self._fingers()
        for rect, radius in fingers:
            painter.setPen(QPen(QColor(scheme.pad_ring), 0.08))
            painter.setBrush(QBrush(QColor(scheme.pad) if self.near_side else FINGER_FAR))
            painter.drawRoundedRect(rect, radius, radius)
        if fingers and self.isSelected() and not _on_paper(painter):
            around = fingers[0][0]
            for rect, _radius in fingers[1:]:
                around = around.united(rect)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(SELECTED, 0.2))
            painter.drawRect(around.adjusted(-0.3, -0.3, 0.3, 0.3))

            # NO HOLE. A finger is a solid contact, soldered to from the surface -- there
            # is nothing to put a lead through, and that is the whole difference between a
            # finger and a pad. This used to punch the drill back through on the reasoning
            # that the finger is copper laid OVER the pad; it is not, it is the pad, and
            # drawing a bore in it made the strip read as an ordinary row of long pads.


# ------------------------------------------------------------- references and pins

#: Reference prefix per archetype, following the usual schematic letters. A part arrives with
#: no name, and "R4" tells a builder what it is at a glance where "cmp-4" tells them nothing --
#: and these are the names the build guide and every DRC message will use.
REF_PREFIXES: dict[str, str] = {
    "axial-cylinder": "R",
    "radial-electrolytic": "C",
    "disc-ceramic": "C",
    "box-film": "C",
    "dip": "U",
    "to92": "Q",
    "to220": "Q",
    "led-round": "LED",
    "pin-header": "J",
    "pin-socket": "J",
    "pin-header-ra": "J",
    "pin-socket-ra": "J",
    "screw-terminal": "TB",
    "potentiometer": "RV",
    "tactile-switch": "SW",
    "crystal-hc49": "Y",
    "relay-box": "K",
    "generic-box": "X",
    "box-header": "J",
    "wire-to-board": "J",
    "screw-terminal-vertical": "TB",
    "module-board": "U",
    # Whatever it is on the panel; "J" until it is given its own letter, as a jack would be.
    "flying-leads": "J",
    "smd-adapter": "U",
    "axial-upright": "R",
}


def reference_prefix(footprint: Footprint) -> str:
    """The schematic letter for a footprint. A polarized axial part is a diode, not a
    resistor -- the same distinction ui/bodies.py draws them by, lying or standing."""
    if footprint.body.archetype in AXIAL_ARCHETYPES and footprint.polarized:
        return "D"
    return REF_PREFIXES.get(footprint.body.archetype, "X")


def next_reference(document: PerfDocument, footprint_id: str, prefix: str | None = None) -> str:
    """The next free reference for this kind of part, e.g. "R3".

    Counts from what is already on the board rather than from a counter, so it stays correct
    across undo, redo, save, load and a part being deleted from the middle of a sequence -- a
    duplicate ref is refused by the bus, and being refused because a hidden counter disagreed
    with the document would be baffling.

    THE DESIGN COUNTS AS WELL AS THE BOARD. A reference is unique across both lists (see
    ``commands.assert_ref_free``), so counting only the placed parts would offer R1 to
    somebody who has just drawn R1 on the schematic and then have the bus refuse it -- and
    so do the other boards of a system and its cables, for the same reason. ``document`` is
    the bus's, the whole system, never a board's view.
    """
    from perfboard_studio.footprints import get_footprint

    if prefix is None:
        footprint = get_footprint(footprint_id)
        prefix = reference_prefix(footprint) if footprint is not None else "X"
    # Every board's, the design's and the cables': one namespace (``system.references_in_use``).
    used = references_in_use(document)
    index = 1
    while f"{prefix}{index}" in used:
        index += 1
    return f"{prefix}{index}"


def describe_span(a: HoleCoord, b: HoleCoord, board: Board) -> str:
    """Two holes, and the three different distances between them.

    They are genuinely three answers and not one rounded three ways:

      * **holes across** is what you count on the board and what a footprint is written
        in -- "R3: C7 to C11, 4 holes" is the language the build guide already speaks.
      * **mm** is the straight, centre-to-centre distance, which is what a lead-bending
        jig and a pair of pliers are set to, and the only one of the three that answers
        "will this part physically reach".
      * **steps** is the orthogonal count, which is how long a solder trace between them
        would be -- solder crosses the 0.6 mm gap to an orthogonal neighbour and not the
        1.7 mm diagonal one, so a diagonal is 2 steps of copper and not 1.4.

    Same hole twice is not an error and not a measurement; it says so instead.
    """
    if a == b:
        return t("{hole} — the same hole.").format(hole=format_hole(a, board))
    d_col, d_row = abs(b.col - a.col), abs(b.row - a.row)
    mm = path_length_mm((a, b), board)
    steps = manhattan(a, b)
    span = (
        f"{d_col + 1} × {d_row + 1} {t('holes')}"
        if d_col and d_row
        else f"{max(d_col, d_row) + 1} {t('holes')}"
    )
    return (
        f"{format_hole(a, board)} → {format_hole(b, board)}  ·  {span}  ·  "
        f"{t('{mm:.2f} mm apart').format(mm=mm)}  ·  "
        f"{counted(steps, t('{count} step by trace'), t('{count} steps by trace'))}"
    )


def net_holding(document: PerfDocument, ref: str, pin: str) -> Net | None:
    for net in document.nets:
        if any((node.component_ref, node.pin) == (ref, pin) for node in net.nodes):
            return net
    return None


def join_pins(
    bus: Any, first: tuple[str, str], second: tuple[str, str]
) -> tuple[Any | None, str | None]:
    """Join two pins, or say why not. Returns ``(dispatch result, refusal)``.

    ONE FUNCTION FOR TWO SURFACES. The board joins pins by clicking two pads and the
    schematic sheet joins them by clicking two symbol pins, and the two must not be able
    to disagree about what a click on each does -- especially about the three cases that
    are not "make a net": one pin already on a rail, both already on the same net, and
    both on DIFFERENT nets, which is refused because merging two nets is a decision about
    the circuit rather than about two clicks.

    WHAT the join does is ``commands.plan_pin_join``, the same plan ``sheet.wire`` follows,
    so a pin called GND makes or joins the net called GND by either door. This used to be a
    copy of that plan, which the two docstrings said was shared.

    Module level and untyped in the bus, because ``CommandBus`` lives above this file in
    the import order and the alternative is a cycle for one parameter.
    """
    document: PerfDocument = bus.document
    a = NetNode(component_ref=first[0], pin=first[1])
    b = NetNode(component_ref=second[0], pin=second[1])
    plan = plan_pin_join(document, a, b)
    net_a, net_b = plan.net_a, plan.net_b

    if plan.kind == "same-net" and net_a is not None:
        return None, t("{a} and {b} are both already on {net}.").format(
            a=f"{first[0]}.{first[1]}", b=f"{second[0]}.{second[1]}", net=net_a.name
        )
    if plan.kind == "two-nets" and net_a is not None and net_b is not None:
        return None, t(
            "{a} is on {net_a} and {b} is on {net_b}. Joining two nets is a change to "
            "the circuit — disconnect one of the pins first."
        ).format(
            a=f"{first[0]}.{first[1]}",
            net_a=net_a.name,
            b=f"{second[0]}.{second[1]}",
            net_b=net_b.name,
        )

    if plan.kind == "extend" and net_a is not None:
        # One command, so one undo step, even when the net takes a supply pin's name.
        return (
            bus.dispatch(
                "net.connect",
                ConnectPinsPayload(
                    id=net_a.id,
                    nodes=plan.nodes,
                    rename=plan.name,
                    net_class=plan.net_class if plan.name is not None else None,
                ),
            ),
            None,
        )
    return (
        bus.dispatch(
            "net.add",
            AddNetPayload(
                name=plan.name or next_net_name(document),
                net_class=plan.net_class,
                nodes=(a, b),
            ),
        ),
        None,
    )


def _pin_holes_of(
    comp: ComponentInstance, lookup: FootprintLookup
) -> list[tuple[Any, HoleCoord]]:
    footprint = lookup(comp.footprint_id)
    if footprint is None:
        return []
    return list(all_pin_holes(comp, footprint))


# --------------------------------------------------------------- placement ghost


class PlacementGhostItem(QGraphicsItem):
    """The part about to be placed, drawn under the cursor before it exists.

    Placing blind -- click and see where it landed -- is the difference between an editor you
    can aim with and one you correct after the fact. The ghost is the real body from
    ui/bodies.py at the real size, so what you line up is what you get, and its pin markers
    show exactly which holes it will occupy.
    """

    def __init__(
        self,
        footprint: Footprint,
        board: Board,
        side: BoardSide,
        rotation: int = 0,
        mirrored: bool = False,
    ) -> None:
        super().__init__()
        self.fp = footprint
        self.board = board
        self.side = side
        #: Turned and flipped as the part will be: a part already on the board keeps its
        #: own orientation when it is dragged back onto it from the sheet. Not ``rotation``,
        #: which is QGraphicsItem's own and turns the whole item about its origin.
        self.part_rotation = rotation
        self.part_mirrored = mirrored
        self.anchor = HoleCoord(0, 0)
        self.blocked = False
        #: "C2 100nF" over a part from the design, which already has its reference; empty
        #: for a library part, whose reference is only handed out when it lands.
        self.label = ""
        self.setZValue(120)
        self.setOpacity(0.62)

    def set_anchor(self, anchor: HoleCoord, blocked: bool) -> None:
        if (anchor, blocked) == (self.anchor, self.blocked):
            return
        self.prepareGeometryChange()
        self.anchor = anchor
        self.blocked = blocked
        self.setPos(hole_to_screen(anchor, self.board, self.side))
        self.update()

    def boundingRect(self) -> QRectF:
        placement = placement_for(self.fp, self.board.pitch)
        reach = max(placement.size_x, placement.size_y) + 4 * self.board.pitch
        return QRectF(-reach, -reach, 2 * reach, 2 * reach)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        placement = placement_for(self.fp, self.board.pitch)
        style = style_for(self.fp)
        rect = _body_rect(placement)

        # The anchor is mirrored by hole_to_screen on the solder side, and the pins have
        # to be mirrored with it -- the same reflection _local_offset applies to a placed
        # part. Without it the ghost showed a DIP's pins running one way while the
        # placement put them the other, which is the one thing a ghost exists to prevent.
        if self.side == "bottom":
            painter.scale(-1, 1)
        # Then the part's own turn and flip, in ComponentItem._apply_local_transform's order,
        # so the ghost and the part it becomes cannot disagree about which way round it is.
        painter.rotate(float(self.part_rotation))
        if self.part_mirrored:
            painter.scale(-1, 1)

        painter.setBrush(QBrush(QColor(style.fill)))
        painter.setPen(QPen(ERROR_OUTLINE if self.blocked else SELECTED, 0.3))
        painter.drawRect(rect)

        # The holes it will take. On a grid this is the thing you are actually aiming.
        painter.setBrush(QBrush(ERROR_OUTLINE if self.blocked else PIN_ONE))
        painter.setPen(QPen(QColor("#1b1d22"), 0.14))
        for pin in self.fp.pins:
            painter.drawEllipse(
                QPointF(pin.d_col * self.board.pitch, pin.d_row * self.board.pitch), 0.55, 0.55
            )
        if self.label:
            painter.setPen(QColor("#ffffff"))
            draw_label(
                painter,
                QPointF(rect.center().x(), rect.top()),
                self.label,
                12,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                bold=True,
                offset=QPointF(0, -3),
                background=QColor(27, 29, 34, 220),
            )


# ------------------------------------------------------------------ ratsnest overlay


class RatsnestItem(QGraphicsItem):
    """The connections the schematic still wants and the board does not yet make.

    Drawn as one item rather than one per link: a fresh netlist import can produce a few
    hundred of these, and they are decoration for the eye, never interactive.

    Highlighted nets are drawn brighter and thicker over the rest, which is how selecting
    a part answers "and what is this still supposed to connect to".
    """

    def __init__(
        self,
        links: Sequence[RatsnestLine],
        board: Board,
        side: BoardSide,
        highlight: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self.links = list(links)
        self.board = board
        self.side = side
        self.highlight = set(highlight)
        self.setZValue(30)

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        # Highlighted links last, so they sit on top of the rest rather than under it.
        for link in sorted(self.links, key=lambda item: item.net_id in self.highlight):
            lit = link.net_id in self.highlight
            colour = RATSNEST_HIGHLIGHT if lit else RATSNEST.get(link.net_class, RATSNEST["signal"])
            pen = QPen(colour, 0.34 if lit else 0.2)
            pen.setDashPattern([3.5, 2.5] if lit else [2.0, 2.6])
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(
                hole_to_screen(link.from_, self.board, self.side),
                hole_to_screen(link.to, self.board, self.side),
            )


# ------------------------------------------------------------- risk-ring overlay


class RiskRingsItem(QGraphicsItem):
    """Rings on the holes named by a ``solder-trace-proximity`` violation: red over the parts
    for a problem, ``BENCH_RING`` under them for a bench check.

    A separate, cheap item rather than folded into the pad grid: it is rebuilt after
    every DRC run and there is no reason to disturb the pad-grid item (and its own
    exposedRect culling) to do it.
    """

    def __init__(
        self,
        holes: Sequence[HoleCoord],
        board: Board,
        side: BoardSide,
        colour: QColor = RISK_RING,
        z: float = RISK_RING_Z,
    ) -> None:
        super().__init__()
        self.holes = list(holes)
        self.board = board
        self.side = side
        self.colour = QColor(colour)
        self.setZValue(z)

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board).adjusted(-1, -1, 1, 1)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        r = self.board.pad_diameter / 2 + 0.35
        pen = QPen(self.colour, 0.3)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for hole in self.holes:
            p = hole_to_screen(hole, self.board, self.side)
            painter.drawEllipse(p, r, r)


class PickedPinsItem(QGraphicsItem):
    """The pins collected so far while naming a net by clicking them.

    Deliberately the ratsnest's highlight colour: the yellow already means "this is the
    net you are looking at" everywhere else in the view, and a pin picked for a net is
    the same statement made one click at a time.
    """

    def __init__(self, board: Board, side: BoardSide) -> None:
        super().__init__()
        self.holes: list[HoleCoord] = []
        self.board = board
        self.side = side
        self.setZValue(61)

    def set_holes(self, holes: Sequence[HoleCoord]) -> None:
        self.holes = list(holes)
        self.update()

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board).adjusted(-1, -1, 1, 1)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        r = self.board.pad_diameter / 2 + 0.35
        painter.setPen(QPen(RATSNEST_HIGHLIGHT, 0.35))
        painter.setBrush(QBrush(QColor(255, 209, 102, 70)))
        for hole in self.holes:
            painter.drawEllipse(hole_to_screen(hole, self.board, self.side), r, r)


class PinHoverItem(QGraphicsItem):
    """The ring on the pin under the pointer while the connect or the draw tool is armed.

    The sheet's wire tool has always ringed the pin it would take; the board's tools did
    not, so a click was a guess at whether the hole under the pointer was the pin or the
    pad beside it. Thinner than a picked pin's ring and unfilled: it says "this one, if you
    click", where the picked ring says "this one, already". In the canvas hover colour
    (``theme.CANVAS_HOVER``), cosmetic, so it is the same hairline at every zoom.
    """

    def __init__(self, board: Board, side: BoardSide) -> None:
        super().__init__()
        self.board = board
        self.side = side
        self.hole: HoleCoord | None = None
        self.setZValue(62)  # Over a picked pin's ring, which it never sits on.

    def set_hole(self, hole: HoleCoord | None) -> None:
        if hole != self.hole:
            self.hole = hole
            self.update()

    def boundingRect(self) -> QRectF:
        return _outline_rect(self.board).adjusted(-1, -1, 1, 1)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        if self.hole is None:
            return
        pen = QPen(QColor(CANVAS_HOVER), CANVAS_HOVER_WIDTH_PX * 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        r = self.board.pad_diameter / 2 + 0.3
        painter.drawEllipse(hole_to_screen(self.hole, self.board, self.side), r, r)


# ------------------------------------------------------------------ conductor item


_SOLDER_RUNS = ("solder-trace", "solder-trace-wired")


def _orthogonal_run(from_: HoleCoord, to: HoleCoord, column_first: bool) -> list[HoleCoord]:
    """Every pad a solder run from ``from_`` to ``to`` crosses, ``to`` last: along the row
    first and then down the column, or the other way round."""
    col, row = from_.col, from_.row
    run: list[HoleCoord] = []
    for along_the_row in ((False, True) if column_first else (True, False)):
        if along_the_row:
            while col != to.col:
                col += 1 if to.col > col else -1
                run.append(HoleCoord(col, row))
        else:
            while row != to.row:
                row += 1 if to.row > row else -1
                run.append(HoleCoord(col, row))
    return run


def _distance_to_leg(p: QPointF, a: QPointF, b: QPointF) -> float:
    """How far ``p`` is from the straight leg ``a``-``b``, in scene millimetres."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = dx * dx + dy * dy
    t_ = 0.0 if length == 0 else max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / length))
    return math.hypot(p.x() - (a.x() + t_ * dx), p.y() - (a.y() + t_ * dy))


def _in_line(a: HoleCoord, b: HoleCoord, c: HoleCoord) -> bool:
    """Whether three holes lie on one row or one column: a drag from ``a`` through ``b`` to
    ``c`` has not turned."""
    return (a.row == b.row == c.row) or (a.col == b.col == c.col)


def _elbow(from_: HoleCoord, to: HoleCoord, column_first: bool) -> list[HoleCoord]:
    """A wire's leg from ``from_`` to ``to`` along the grid, ``to`` last: straight when they
    share a row or a column, else one corner -- the way the router lays a wire."""
    if from_.col == to.col or from_.row == to.row:
        return [to]
    corner = HoleCoord(from_.col, to.row) if column_first else HoleCoord(to.col, from_.row)
    return [corner, to]


def _straightened(path: Sequence[HoleCoord]) -> tuple[HoleCoord, ...]:
    """A wire's path without the corners that are not corners: a hole named twice in a row,
    or a point in the middle of a straight leg. A wire touches only its ends, so neither
    is anything on the board -- and the command refuses the first."""
    out: list[HoleCoord] = []
    for hole in path:
        if out and out[-1] == hole:
            continue
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            ab = (b.col - a.col, b.row - a.row)
            bc = (hole.col - b.col, hole.row - b.row)
            straight = ab[0] * bc[1] == ab[1] * bc[0] and ab[0] * bc[0] + ab[1] * bc[1] > 0
            if straight:
                out[-1] = hole
                continue
        out.append(hole)
    return tuple(out)


def reshaped_path(
    kind: ConductorKind, path: Sequence[HoleCoord], index: int, to: HoleCoord
) -> tuple[HoleCoord, ...] | None:
    """``path`` with its hole ``index`` dragged to ``to``, or None where that cannot be.

    - A solder run's END: back to a pad it already has shortens it there; anywhere else
      runs on to it along the grid, as the drawing tool does. Its middle has no handle --
      every pad of it is a joint.
    - A wire's end: its last leg is laid again from the corner before it, along the grid.
    - A wire's corner, or a jumper's: moved where it is dropped.
    - A top jumper's end: straight from the hole before it, as it is drawn.
    """
    holes = list(path)
    if not 0 <= index < len(holes):
        return None
    if to == holes[index]:
        return tuple(holes)
    last = len(holes) - 1
    if index not in (0, last):
        if kind in _SOLDER_RUNS:
            return None
        holes[index] = to
        shaped = _straightened(holes)
        return shaped if len(shaped) >= 2 else None
    oriented = holes if index == last else holes[::-1]
    if kind in _SOLDER_RUNS:
        if to in oriented:
            new = oriented[: oriented.index(to) + 1]
        else:
            step = _orthogonal_run(oriented[-1], to, False)
            if any(hole in oriented for hole in step):
                return None
            new = oriented + step
    elif kind == "top-jumper":
        new = [*oriented[:-1], to]
    else:
        new = list(_straightened([*oriented[:-1], *_elbow(oriented[-2], to, False)]))
    if len(new) < 2 or new[0] == new[-1]:
        return None
    return tuple(new if index == last else new[::-1])


def _corner_indices(path: Sequence[HoleCoord]) -> list[int]:
    """The indices of the holes where ``path`` starts, turns or ends."""
    out = [0]
    for i in range(1, len(path) - 1):
        a, b, c = path[i - 1], path[i], path[i + 1]
        ab = (b.col - a.col, b.row - a.row)
        bc = (c.col - b.col, c.row - b.row)
        if ab[0] * bc[1] != ab[1] * bc[0] or ab[0] * bc[0] + ab[1] * bc[1] <= 0:
            out.append(i)
    out.append(len(path) - 1)
    return out


def _tidied(points: Sequence[HoleCoord]) -> list[HoleCoord]:
    """Corners with nothing to say taken out until none is left: a hole named twice in a
    row, a point on a straight leg, and a leg that folds back along the one before it.
    Never the two ends -- they are where the copper is soldered."""
    out = list(points)
    while True:
        tidy: list[HoleCoord] = []
        for hole in out:
            if tidy and tidy[-1] == hole:
                continue
            if len(tidy) >= 2:
                a, b = tidy[-2], tidy[-1]
                if (b.col - a.col) * (hole.row - b.row) == (b.row - a.row) * (hole.col - b.col):
                    tidy[-1] = hole
                    continue
            tidy.append(hole)
        if tidy == out:
            return tidy
        out = tidy


def slid_path(
    kind: ConductorKind, path: Sequence[HoleCoord], leg: int, dcol: int, drow: int
) -> tuple[HoleCoord, ...] | None:
    """``path`` with the straight stretch through its holes ``leg`` and ``leg + 1`` slid
    sideways by (``dcol``, ``drow``) -- only the part across the stretch counts, so a hand
    that wanders along it changes nothing -- or None where that cannot be.

    The stretches on either side stretch to meet it, and the ends stay on their pads: where
    the stretch began or ended at one, a leg from that pad to it is put in. A solder run is
    every pad of the new chain, refused where it would cross itself, since each of those
    pads is soldered; a diagonal stretch -- a jumper laid straight -- has no sideways on the
    grid and is not slid.
    """
    holes = list(path)
    if not 0 <= leg < len(holes) - 1:
        return None
    corners = _corner_indices(holes)
    j = max(k for k in range(len(corners) - 1) if corners[k] <= leg)
    a, b = holes[corners[j]], holes[corners[j + 1]]
    if a.row == b.row:
        dcol = 0
    elif a.col == b.col:
        drow = 0
    else:
        return None
    if (dcol, drow) == (0, 0):
        return tuple(holes)
    points = [holes[k] for k in corners]
    last = len(points) - 1
    moved_a = HoleCoord(a.col + dcol, a.row + drow)
    moved_b = HoleCoord(b.col + dcol, b.row + drow)
    new = _tidied(
        [
            *points[:j],
            *([a] if j == 0 else []),
            moved_a,
            moved_b,
            *([b] if j + 1 == last else []),
            *points[j + 2 :],
        ]
    )
    if len(new) < 2 or new[0] == new[-1]:
        return None
    if kind not in _SOLDER_RUNS:
        return tuple(new)
    every = [new[0]]
    for corner in new[1:]:
        if corner.row != every[-1].row and corner.col != every[-1].col:
            return None
        every.extend(_orthogonal_run(every[-1], corner, False))
    return tuple(every) if len(set(every)) == len(every) else None


class CopperGrab(NamedTuple):
    """What a press in the Select tool picks up of the copper under it
    (``BoardScene.copper_grab_at``): an END of a conductor to move, a wire's CORNER to move,
    or a SEGMENT -- a straight stretch, by the leg ``position`` to ``position + 1`` of its path --
    to slide sideways. ``across`` is the way a segment slides: "rows" or "columns"."""

    conductor_id: str
    kind: str
    position: int
    across: str = ""


def grab_cursor(grab: CopperGrab | None) -> Qt.CursorShape | None:
    """The cursor that says what a press would pick up: the cross for a point -- an end or
    a corner, put down on a hole -- and the two-headed arrow a segment slides along. A part
    keeps the four-way move cursor, so the three never look alike."""
    if grab is None:
        return None
    if grab.kind == "segment":
        return (
            Qt.CursorShape.SizeVerCursor if grab.across == "rows" else Qt.CursorShape.SizeHorCursor
        )
    return Qt.CursorShape.CrossCursor


def _show_cursor(item: QGraphicsItem, shape: Qt.CursorShape | None) -> None:
    """``item``'s cursor set to ``shape``, or taken away for None -- touched only when it
    changes, since this runs on every hover move."""
    if shape is None:
        if item.hasCursor():
            item.unsetCursor()
    elif not item.hasCursor() or item.cursor().shape() != shape:
        item.setCursor(shape)


class CopperHandleItem(QGraphicsItem):
    """A square on an end -- or a wire's corner -- of the one conductor selected. Dragged to
    another hole, it is ONE ``conductor.setPath``: copper used to be deleted and drawn again
    to move an end by one hole."""

    def __init__(self, index: int, at: HoleCoord, board: Board, side: BoardSide) -> None:
        super().__init__()
        self.index = index
        self.at = at
        self.board = board
        self.setPos(hole_to_screen(at, board, side))
        self.setZValue(130)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def _half(self) -> float:
        return self.board.pad_diameter * 0.42

    def boundingRect(self) -> QRectF:
        half = self._half() + 0.2
        return QRectF(-half, -half, half * 2, half * 2)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        half = self._half()
        painter.setPen(QPen(QColor(CANVAS_SELECTED), 0.22))
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawRect(QRectF(-half, -half, half * 2, half * 2))


class DrawPreviewItem(QGraphicsItem):
    """The conductor being drawn, before it exists.

    Shows the chain committed so far solid and the step under the cursor dashed, so the
    difference between "this is what I have" and "this is where the next click goes" is
    visible without moving your eyes off the board. A step the command would refuse --
    a diagonal on a solder trace -- is drawn in the error colour rather than simply
    ignored, because silently dropping a click reads as the tool having stopped working.
    """

    def __init__(self, kind: ConductorKind, board: Board, side: BoardSide) -> None:
        super().__init__()
        self.kind = kind
        self.board = board
        self.side = side
        self.path: list[HoleCoord] = []
        # Not "cursor": QGraphicsItem already has a cursor() and shadowing it would make
        # the item's own cursor handling silently stop working.
        self.next_hole: HoleCoord | None = None
        self.next_ok = True
        #: The pads a click on ``next_hole`` would add, in order: one for a wire's end, the
        #: whole run to the pointer for a solder trace.
        self.run: list[HoleCoord] = []
        #: What laying it here would do wrong (``drawcheck``), marked at its hole: a short
        #: or a crossing in the error colour, a wire along another in amber.
        self.problem: DrawProblem | None = None
        self.setZValue(120)

    def boundingRect(self) -> QRectF:
        pitch = self.board.pitch
        return _outline_rect(self.board).adjusted(-pitch, -pitch, pitch, pitch)

    def set_path(
        self,
        path: list[HoleCoord],
        next_hole: HoleCoord | None,
        ok: bool,
        run: Sequence[HoleCoord] = (),
    ) -> None:
        self.path = path
        self.next_hole = next_hole
        self.next_ok = ok
        self.run = list(run)
        self.update()

    def set_problem(self, problem: DrawProblem | None) -> None:
        if problem != self.problem:
            self.problem = problem
            self.update()

    def _problem_tint(self) -> QColor | None:
        if self.problem is None:
            return None
        return ERROR_OUTLINE if self.problem.severity == "error" else WARNING_OUTLINE

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        colour, width, _dashed = CONDUCTOR_STYLE.get(self.kind, (QColor("#888"), 0.6, False))
        trouble = self._problem_tint()
        if trouble is not None:
            # The whole conductor takes the colour, not only the step: a short made three
            # clicks back is still what Enter would lay.
            colour = trouble
        points = [hole_to_screen(h, self.board, self.side) for h in self.path]
        # Joints are where a run is soldered -- every pad of it -- and where a wire is: its
        # two ends. A wire's corner lies over its hole and is not one.
        solders = self.kind in _SOLDER_RUNS
        joints = points if solders else points[:1] + points[-1:] if len(points) > 1 else points

        if len(points) >= 2:
            # A dark edge under it first: the preview is the kind's own colour, and over
            # copper of the same kind it was grey on grey.
            halo = QPen(QColor(0, 0, 0, 130), width * 1.9)
            halo.setCapStyle(Qt.PenCapStyle.RoundCap)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(halo)
            outline = QPainterPath(points[0])
            for p in points[1:]:
                outline.lineTo(p)
            painter.drawPath(outline)
            pen = QPen(colour, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath(points[0])
            for p in points[1:]:
                path.lineTo(p)
            painter.drawPath(path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colour.lighter(130)))
        for p in joints:
            painter.drawEllipse(p, width * 0.7, width * 0.7)

        if self.next_hole is not None:
            end = hole_to_screen(self.next_hole, self.board, self.side)
            tint = colour if self.next_ok else ERROR_OUTLINE
            if points:
                pen = QPen(tint, width)
                pen.setDashPattern([1.6, 1.4])
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                # No fill: the joints' brush is still set, and a step with a corner in it
                # is a path that encloses an area -- it filled as a white triangle.
                painter.setBrush(Qt.BrushStyle.NoBrush)
                # Through every pad of the run, so its corner is where it will be.
                ahead = QPainterPath(points[-1])
                for hole in self.run or [self.next_hole]:
                    ahead.lineTo(hole_to_screen(hole, self.board, self.side))
                painter.drawPath(ahead)
                # And a dot on each pad it would solder, because those are the joints.
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(tint))
                for hole in self.run[:-1] if solders else ():
                    painter.drawEllipse(hole_to_screen(hole, self.board, self.side), width * 0.45, width * 0.45)
            painter.setPen(QPen(tint, 0.22))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(end, self.board.pad_diameter * 0.62, self.board.pad_diameter * 0.62)

        if self.problem is not None and trouble is not None:
            # A double ring on the hole itself, which is where the eye has to go.
            at = hole_to_screen(self.problem.hole, self.board, self.side)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for scale, pen_width in ((0.75, 0.3), (1.05, 0.16)):
                painter.setPen(QPen(trouble, pen_width))
                radius = self.board.pad_diameter * scale
                painter.drawEllipse(at, radius, radius)


def _stroke_pen(colour: QColor, width: float) -> QPen:
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _polyline(points: Sequence[QPointF]) -> QPainterPath:
    path = QPainterPath(points[0])
    for point in points[1:]:
        path.lineTo(point)
    return path


def _trimmed(points: Sequence[QPointF], distance: float) -> list[QPointF]:
    """The polyline with ``distance`` mm taken off each end; empty when it is shorter than
    twice that, which is a wire with no sleeve left."""

    def cut(pts: Sequence[QPointF]) -> list[QPointF]:
        remaining = distance
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            length = math.hypot(b.x() - a.x(), b.y() - a.y())
            if length > remaining:
                t = remaining / length
                return [QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t), *pts[i + 1 :]]
            remaining -= length
        return []

    front = cut(points)
    if not front:
        return []
    back = cut(front[::-1])
    return back[::-1] if back else []


def _past(a: QPointF, b: QPointF, distance: float) -> QPointF:
    """The point ``distance`` beyond ``b``, on the line from ``a`` through ``b``."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = math.hypot(dx, dy) or 1.0
    return QPointF(b.x() + dx / length * distance, b.y() + dy / length * distance)


@lru_cache(maxsize=64)
def _dome_brush(rgba: int) -> QBrush:
    """A radial gradient that lights a joint from the top-left, in the item's OWN bounding
    box, so one brush serves every joint of that colour at any size and the painter never
    builds a gradient per pad -- the cost that mattered, on a board with a few hundred."""
    colour = QColor.fromRgba(rgba)
    gradient = QRadialGradient(0.5, 0.5, 0.5, 0.31, 0.30)
    gradient.setCoordinateMode(QRadialGradient.CoordinateMode.ObjectBoundingMode)
    gradient.setColorAt(0.0, colour.lighter(190))
    gradient.setColorAt(0.45, colour.lighter(112))
    gradient.setColorAt(1.0, colour.darker(135))
    return QBrush(gradient)


@lru_cache(maxsize=64)
def _dome_rim(rgba: int) -> QPen:
    return QPen(QColor.fromRgba(rgba).darker(165), 0.07)


def _paint_domes(painter: QPainter, centres: Sequence[QPointF], radius: float, colour: QColor) -> None:
    """A domed joint at each point. Zoomed out it is a flat disc, which is all it can be."""
    rgba = colour.rgba()
    if painter.transform().m11() >= LIT_MIN_SCALE:
        painter.setBrush(_dome_brush(rgba))
    else:
        painter.setBrush(QBrush(colour.lighter(112)))
    painter.setPen(_dome_rim(rgba))
    for centre in centres:
        painter.drawEllipse(centre, radius, radius)


class ConductorItem(QGraphicsItem):
    """Each conductor kind has to be tellable apart at a glance.

    ``model.contacts_every_path_hole`` (the engine's own predicate, not a re-derived
    copy of it) decides whether every hole gets a solder bead or only the two
    endpoints get a fillet -- this distinction is the heart of the whole data model and
    it must be read from the engine, never re-implemented here.
    """

    def __init__(
        self,
        conductor: Conductor,
        board: Board,
        side: BoardSide,
        net_class: NetClass | None = None,
        signal_index: int = 0,
        show_far_side: bool = True,
        stack: int = 0,
        net_name: str | None = None,
        cells: Mapping[str, FingerCell] | None = None,
    ) -> None:
        super().__init__()
        self.conductor = conductor
        self.board = board
        self.side = side
        #: The document's finger cells (``geometry.finger_cells``), so solder on an outside
        #: finger is drawn on the finger. Empty on every board without an outside strip.
        self.cells: Mapping[str, FingerCell] = cells or {}
        self.net_class = net_class
        self.signal_index = signal_index
        #: View > Copper on the Far Side: off, far-side copper is not drawn on screen.
        self.show_far_side = show_far_side
        self.stack = stack
        #: On the net selected in the Nets panel -- see BoardScene.set_highlighted_nets.
        self.net_lit = False
        # Selectable, so a single bad route can be deleted instead of the whole autoroute
        # being undone or the entire board re-routed -- which were the only two options.
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        # ``stack`` is the conductor's level from ``occupancy.stacking_layers``: how many
        # conductors it passes over. Every solder-side conductor used to sit at one z, so
        # which of two crossing wires was drawn on top came down to scene order -- and
        # could disagree with the 3D view, which is the one place a reader checks. A tenth
        # of a step keeps every conductor comfortably inside its band whatever the board
        # does.
        #
        # The band is the FACE, not the side: copper on the face being looked at is above
        # the parts and copper on the far face below them. Solder-side copper sat under the
        # parts from the solder side too, where the parts are only shadows of what stands
        # on the other face -- so wherever a part's outline covered a run, nothing on the
        # face the user was working on could be clicked.
        self.setZValue((40 if conductor.side == side else -50) + 0.1 * stack)
        # For the cursor: what a press here picks up (``_follow_the_pointer``).
        self.setAcceptHoverEvents(True)
        first, last = conductor.path[0], conductor.path[-1]
        # The net is the thing a reader hovering a trace is asking about -- "what IS this"
        # -- and it was the one field the tooltip left out.
        net_note = f"\n{net_name}" if net_name else ""
        self.setToolTip(
            f"{conductor_word(conductor.kind, guide_language(current_language()))}  "
            f"{format_hole(first, board)} → {format_hole(last, board)}{net_note}"
        )

    def _follow_the_pointer(self, at: QPointF) -> None:
        """The cursor a press here would earn: an end's, a corner's or a segment's
        (``grab_cursor``), or none -- a click that only selects."""
        scene = self.scene()
        grab = scene.copper_grab_at(at) if isinstance(scene, BoardScene) else None
        _show_cursor(self, grab_cursor(grab))

    def hoverEnterEvent(self, event: Any) -> None:
        self._follow_the_pointer(event.scenePos())
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event: Any) -> None:
        self._follow_the_pointer(event.scenePos())
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event: Any) -> None:
        _show_cursor(self, None)
        super().hoverLeaveEvent(event)

    def _points(self) -> list[QPointF]:
        return [
            path_point_to_screen(h, self.board, self.side, self.cells)
            for h in self.conductor.path
        ]

    def is_far_side(self) -> bool:
        """True when this conductor is on the face away from the one being viewed.

        Perfboard is opaque, so strictly you cannot see it at all -- but the whole point of
        the editor is to show it, and the honest way to do that is to mark it as being on
        the other side rather than to draw it as if it were in front of you. Public because
        the hatching is the visible consequence of this one predicate, and a test that has
        to inspect pixels to check which side a conductor was drawn on is testing the
        wrong thing.
        """
        return self.conductor.side != self.side

    def contact_points(self) -> list[QPointF]:
        """Where a solder joint is actually drawn: every hole for a conductor that
        contacts each one (a solder trace), or just the two endpoints for one that
        only contacts its ends (a wire) -- see ``model.contacts_every_path_hole``.
        Split out from :meth:`paint` so this distinction, the heart of the model, is
        assertable directly rather than only by inspecting rendered pixels.
        """
        pts = self._points()
        if contacts_every_path_hole(self.conductor):
            return pts
        return [pts[0], pts[-1]]

    def boundingRect(self) -> QRectF:
        pts = self._points()
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        pad = 2.0
        return QRectF(min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)

    @property
    def conductor_id(self) -> str:
        return self.conductor.id

    def set_net_lit(self, lit: bool) -> None:
        if lit != self.net_lit:
            self.net_lit = lit
            self.update()

    def shape(self) -> QPainterPath:
        """A clickable band along the path, so a conductor can be picked.

        A stroked path rather than the bounding rect: two wires crossing at an angle share
        a bounding rect the size of the board between them, and picking one would select
        whichever happened to be on top. Nothing at all while it is hidden: copper nobody
        can see is not something a click lands on.
        """
        if self.is_hidden_on_screen():
            return QPainterPath()
        pts = self._points()
        line = QPainterPath(pts[0])
        for p in pts[1:]:
            line.lineTo(p)
        stroker = QPainterPathStroker()
        # A little wider than the conductor: at 2.54 mm pitch, half a pad's worth of slack
        # is the difference between clicking a wire and clicking near it.
        stroker.setWidth(max(CONDUCTOR_STYLE.get(self.conductor.kind, (None, 0.6, None))[1], 0.6) + 0.8)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        return stroker.createStroke(line)

    def _colour(self) -> QColor:
        """This conductor's colour: its own if it has one, else its net's, else its kind's."""
        explicit = explicit_colour(getattr(self.conductor, "color", None))
        if explicit is not None:
            return explicit
        if self.conductor.kind in ("insulated-wire", "top-jumper"):
            return insulation_color(self.net_class, self.signal_index)
        return CONDUCTOR_STYLE.get(self.conductor.kind, (QColor("#888"), 0.6, False))[0]

    def _paint_through_the_board(
        self, painter: QPainter, path: QPainterPath, width: float, colour: QColor
    ) -> None:
        """A conductor on the far face, on the 1:1 print: hatched, the way a part on the far
        face already is. The screen draws a back layer instead (``_paint_back_layer``).

        The board is opaque. Drawing a solder-side trace solid while looking at the
        component side says "this is in front of you", which is the same misreading
        ``_paint_body_shadow`` exists to prevent for bodies -- and the one that gets a board
        soldered on the wrong face. Hatching is this application's established word for "on
        the other side", so a conductor and a part now say it the same way.

        Stroked into a fillable shape rather than dashed: a dash already means a top jumper
        (``CONDUCTOR_STYLE``), and giving one mark two meanings costs more than it saves.
        The outline keeps the run traceable end to end, which hatching alone does not at low
        zoom.
        """
        stroker = QPainterPathStroker()
        stroker.setWidth(width)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        body = stroker.createStroke(path)

        faded = QColor(colour)
        faded.setAlphaF(0.75)
        # A faint solid band under the hatch, so the run reads as one length of copper at
        # every zoom. Hatch alone is thin strokes over a busy grid of pads, and zoomed out --
        # where somebody looks to see what joins what -- it thins to nothing.
        underlay = QColor(colour)
        underlay.setAlphaF(0.3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(underlay))
        painter.drawPath(body)
        brush = QBrush(faded, Qt.BrushStyle.FDiagPattern)
        # Hatch patterns are defined in DEVICE pixels, so without this the hatch would hold
        # its screen size while the board zooms -- solid when zoomed in, gone when zoomed
        # out. The same inversion _paint_body_shadow needs, for the same reason.
        brush.setTransform(painter.transform().inverted()[0])
        painter.setBrush(brush)
        painter.setPen(QPen(SELECTED if self.isSelected() else faded, 0.1))
        painter.drawPath(body)
        self._paint_far_joints(painter, width, colour)

    def _paint_back_layer(
        self, painter: QPainter, path: QPainterPath, width: float, colour: QColor
    ) -> None:
        """A conductor on the far face, on screen: a dimmed band with a dark edge, the way a
        PCB tool draws its back layer.

        THE HATCH LEFT THE SCREEN BECAUSE NOBODY COULD SEE IT. Auto-wire lays bare wire on
        the solder side, and from the component side -- where the window opens -- a hatched
        band of silver over white pads at half opacity was nothing at all: the newcomer
        walkthrough's first stall was a board that looked exactly the same before and after
        Auto-wire. Rendered against three other looks (hatch with an edge, a stronger
        underlay), this one read on both the newcomer's board and the dense one, and Sinan
        picked it. The far side is still told apart: it is dimmed (FAR_SIDE_OPACITY), its
        joints are smaller than the beads of copper in front, and it sits under the parts.
        Paper keeps the hatch (``_paint_through_the_board``).
        """
        casing = QPen(SELECTED if self.isSelected() else FAR_SIDE_EDGE, width + 0.24)
        casing.setCapStyle(Qt.PenCapStyle.RoundCap)
        casing.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(casing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        band_colour = QColor(colour)
        band_colour.setAlphaF(0.75)
        band = QPen(band_colour, width)
        band.setCapStyle(Qt.PenCapStyle.RoundCap)
        band.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(band)
        painter.drawPath(path)
        self._paint_far_joints(painter, width, colour)

    def _paint_far_joints(self, painter: QPainter, width: float, colour: QColor) -> None:
        """The joints stay solid. Where a conductor is soldered down is the one fact that
        does not change with the face you are looking from -- the hole goes through the
        board -- and it is what someone counts pads against."""
        painter.setPen(QPen(colour.darker(140), 0.08))
        painter.setBrush(QBrush(colour))
        radius = min(width * 0.62, self.board.pad_diameter * 0.32)
        for point in self.contact_points():
            painter.drawEllipse(point, radius, radius)

    def is_hidden_on_screen(self) -> bool:
        """Far-side copper with View > Copper on the Far Side turned off -- unless it is
        selected or its net is lit, which is somebody looking for exactly this."""
        return (
            not self.show_far_side
            and self.is_far_side()
            and not self.isSelected()
            and not self.net_lit
        )

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        on_paper = _on_paper(painter)
        if not on_paper and self.is_hidden_on_screen():
            return
        # Copper on the far face, quieter on screen (FAR_SIDE_OPACITY) -- but never what is
        # selected or lit, which is being looked for, and never on paper.
        if (
            self.is_far_side()
            and not self.isSelected()
            and not self.net_lit
            and not on_paper
        ):
            painter.save()
            painter.setOpacity(painter.opacity() * FAR_SIDE_OPACITY)
            try:
                self._paint_conductor(painter)
            finally:
                painter.restore()
            return
        self._paint_conductor(painter)

    def _paint_conductor(self, painter: QPainter) -> None:
        kind = self.conductor.kind
        _default, width, dashed = CONDUCTOR_STYLE.get(kind, (QColor("#888"), 0.6, False))
        colour = self._colour()

        pts = self._points()
        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)

        # The selected net's copper glows in the colour its ratsnest lights in, under
        # everything else, on either face: which net this is does not depend on the side it
        # is seen from, and the glow is what somebody scanning the board looks for.
        if self.net_lit:
            glow = QPen(RATSNEST_HIGHLIGHT, width + 0.9)
            glow.setCapStyle(Qt.PenCapStyle.RoundCap)
            glow.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(glow)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        on_screen = not _on_paper(painter)
        if on_screen and contacts_every_path_hole(self.conductor):
            # Screen only: a run's colour and width are its own, and its buildup shows.
            colour = RUN_SCREEN_COLOUR
            width *= RUN_BUILDUP_WIDTH.get(getattr(self.conductor, "buildup", "normal"), 1.0)

        if self.is_far_side():
            # The 1:1 print and the exports keep the hatch; the screen draws a back layer.
            if not on_screen:
                self._paint_through_the_board(painter, path, width, colour)
            else:
                self._paint_back_layer(painter, path, width, colour)
                if kind == "solder-trace-wired":
                    # The joints just left their brush set, and an open path stroked with
                    # a brush is closed and filled: a bent spine was a solid triangle.
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(_stroke_pen(SPINE_CORE, 0.3))
                    painter.drawPath(path)
            return

        if on_screen:
            self._paint_lit(painter, pts, path, width, colour)
            return

        # Insulated wire and top jumpers get a dark casing line under the colour, so a
        # coloured sleeve reads as a sleeve rather than as a painted line, and stays
        # legible where it crosses a pad of nearly its own brightness.
        #
        # A conductor that PASSES OVER another gets the same outline whatever it is made
        # of, and that is the one cue this view had no way to give. The 3D view lifts it
        # clear (occupancy.stacking_layers, the same levels this item is built with), and
        # from directly above two conductors at one z are just two lines meeting -- which
        # reads as a junction, the opposite of what is there. An outline is the ordinary
        # drawing convention for "this one is in front", and it costs one line.
        if kind in ("insulated-wire", "top-jumper") or self.stack > 0:
            casing = QPen(QColor(0, 0, 0, 150), width + 0.22)
            casing.setCapStyle(Qt.PenCapStyle.RoundCap)
            casing.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(casing)
            painter.drawPath(path)

        if self.isSelected():
            halo = QPen(SELECTED, width + 0.7)
            halo.setCapStyle(Qt.PenCapStyle.RoundCap)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(halo)
            painter.drawPath(path)

        pen = QPen(colour, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if dashed:
            pen.setDashPattern([2.2, 1.6])
        painter.setPen(pen)
        painter.drawPath(path)

        # The spine, drawn as a thin copper core running through the solder -- which is
        # exactly what it is, and the only thing distinguishing the two trace kinds on
        # screen. Their electrical difference is about an order of magnitude, so it has
        # to be visible.
        if kind == "solder-trace-wired":
            core = QPen(SPINE_CORE, 0.3)
            core.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(core)
            painter.drawPath(path)

        contacts = self.contact_points()
        every_hole = contacts_every_path_hole(self.conductor)
        if every_hole:
            # A bead at every pad: this trace is soldered down all along its length.
            # Sized to sit INSIDE the pad rather than over it -- solder fills the pad, it
            # does not replace it, and a bead wider than the pad hides the thing being
            # soldered to.
            radius = min(width * 0.85, self.board.pad_diameter * 0.42)
            fill = colour.lighter(112)
        else:
            # A fillet at each end only: a wire is soldered at its two ends and merely
            # passes over everything between them.
            radius = min(width * 0.95, self.board.pad_diameter * 0.40)
            fill = colour.lighter(120)

        # A thin darker rim around each joint. Without it a run of beads at 2.54 mm pitch
        # merges into one lumpy caterpillar brighter than the trace under it, and the eye
        # reads a necklace rather than a length of copper soldered down at every pad. The
        # rim keeps each joint individually countable -- which is what someone tracing the
        # run against the board is actually doing -- while letting the trace itself carry
        # the line.
        painter.setPen(QPen(colour.darker(145), 0.08))
        painter.setBrush(QBrush(fill))
        for p in contacts:
            painter.drawEllipse(p, radius, radius)

        # A highlight off the top-left of each joint: solder is domed and wet-looking, and
        # a flat disc is the one thing it never looks like. Skipped when zoomed out far
        # enough that it would be a single stray pixel of noise per pad.
        if painter.transform().m11() >= 6.0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fill.lighter(135)))
            spot = radius * 0.34
            for p in contacts:
                painter.drawEllipse(
                    QPointF(p.x() - radius * 0.28, p.y() - radius * 0.28), spot, spot
                )


    def _paint_lit(
        self, painter: QPainter, pts: list[QPointF], path: QPainterPath, width: float, colour: QColor
    ) -> None:
        """The face being looked at, on screen: copper that has a surface.

        A run is a ridge -- a dark casing, the colour, a thin highlight off the top-left --
        with a domed joint on every pad; a wired run adds its brass spine through the solder
        and a stub of it past each end, which is what a wired run IS. A bare wire is a
        tinned round; an insulated one is a sleeve over a tinned core, stripped back at each
        end; a top jumper is the same lifted off the board by a drop shadow, which is the
        word a dash used to say on screen (the print keeps the dash: a shadow cannot be
        printed). Picked from candidates rendered side by side, on both faces.

        Highlights and gradients stop below ``LIT_MIN_SCALE``: at that size they are one
        stray pixel per pad. The casing stays, so a run still reads at every zoom.
        """
        kind = self.conductor.kind
        zoomed = painter.transform().m11() >= LIT_MIN_SCALE
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.isSelected():
            painter.setPen(_stroke_pen(SELECTED, width + 0.7))
            painter.drawPath(path)

        if contacts_every_path_hole(self.conductor):
            painter.setPen(_stroke_pen(QColor(34, 38, 46, 205), width + 0.22))
            painter.drawPath(path)
            painter.setPen(_stroke_pen(colour, width))
            painter.drawPath(path)
            if zoomed:
                painter.setPen(_stroke_pen(colour.lighter(128), width * 0.30))
                painter.drawPath(path.translated(-0.07, -0.10))
            if kind == "solder-trace-wired":
                painter.setPen(_stroke_pen(SPINE_CORE, 0.3))
                painter.drawPath(path)
                for inner, end in ((pts[1], pts[0]), (pts[-2], pts[-1])):
                    painter.drawLine(end, _past(inner, end, SPINE_STUB_MM))
            _paint_domes(painter, pts, min(width * 0.85, self.board.pad_diameter * 0.42), colour)
            return

        # A wire, a lead bend or a jumper: a joint at each end only.
        sleeved = kind in ("insulated-wire", "top-jumper")
        if kind == "top-jumper":
            painter.setPen(_stroke_pen(QColor(0, 0, 0, 80), width + 0.25))
            painter.drawPath(path.translated(0.20, 0.30))
        if sleeved:
            painter.setPen(_stroke_pen(WIRE_END_TIN.darker(120), 0.36))
            painter.drawPath(path)
            sleeve = _trimmed(pts, SLEEVE_STRIP_MM)
            if len(sleeve) > 1:
                body = _polyline(sleeve)
                painter.setPen(_stroke_pen(QColor(0, 0, 0, 150), width + 0.2))
                painter.drawPath(body)
                painter.setPen(_stroke_pen(colour, width))
                painter.drawPath(body)
                if zoomed:
                    painter.setPen(_stroke_pen(colour.lighter(150), width * 0.3))
                    painter.drawPath(body.translated(-0.05, -0.08))
        else:
            painter.setPen(_stroke_pen(QColor(30, 34, 42, 120), width + 0.14))
            painter.drawPath(path)
            painter.setPen(_stroke_pen(colour, width))
            painter.drawPath(path)
            if zoomed:
                painter.setPen(_stroke_pen(QColor(255, 255, 255, 190), width * 0.28))
                painter.drawPath(path.translated(-0.05, -0.07))
        _paint_domes(painter, [pts[0], pts[-1]], min(width * 0.95, self.board.pad_diameter * 0.40), WIRE_END_TIN)


# --------------------------------------------------------------- component bodies
#
# Drawn from the real dimensions in ui/bodies.py, in the footprint's own coordinate frame.
# Every mark here earns its place by answering a question someone actually has while
# soldering: which end is the cathode, which way round does the chip go, where does the wire
# enter the terminal block. A pale rectangle answers none of them.


def _body_rect(placement: BodyPlacement) -> QRectF:
    return QRectF(
        placement.centre_x - placement.size_x / 2,
        placement.centre_y - placement.size_y / 2,
        placement.size_x,
        placement.size_y,
    )


def _keyed_direction(placement: BodyPlacement, keyed: tuple[float, float]) -> int:
    """+1 or -1: which way along the body's axis the keyed pin lies."""
    delta = (
        keyed[0] - placement.centre_x if placement.axis == "x" else keyed[1] - placement.centre_y
    )
    return 1 if delta >= 0 else -1


def _flat_direction(
    footprint: Footprint, placement: BodyPlacement, keyed: tuple[float, float], pitch: float
) -> int:
    """+1 or -1: which way along the body's axis an LED's flat is.

    On a two-leg LED, its CATHODE's side: read off the pin the footprint calls K, and not
    off ``keyed``, which is pin 1 and on an LED is the ANODE. The flat was cut on the keyed
    side, so the 2D view, the guide's step images and the 1:1 print all showed it on the
    anode while the 3D view and the part in the hand had it on the cathode: an LED fitted
    from the picture went in backwards. A two-leg LED that names no K keeps the registry's
    numbering, anode first.

    On an LED with more legs -- an RGB one -- the flat is beside PIN 1, whatever the common
    leg is: the makers' drawings put it there on common-cathode and common-anode parts
    alike, and the common-anode one has no K at all.
    """
    if len(footprint.pins) != 2:
        return _keyed_direction(placement, keyed)
    cathode = next((pin for pin in footprint.pins if (pin.name or "").upper() == "K"), None)
    if cathode is not None:
        return _keyed_direction(placement, (cathode.d_col * pitch, cathode.d_row * pitch))
    return -_keyed_direction(placement, keyed)


def _body_path(
    footprint: Footprint,
    placement: BodyPlacement,
    keyed: tuple[float, float] | None,
    pitch: float = STANDARD_PITCH_MM,
) -> QPainterPath:
    """The body silhouette. A 'dcut' is a circle with the cathode side flattened, which is
    exactly how the flat on a real LED tells you which lead is which (``_flat_direction``).

    A 'flat-face' is a TO-92's case: the D ``bodies.flat_face_profile`` gives the 3D view
    too, its flat on local +y however the part is turned -- the painter's transform turns
    and mirrors it with the part. Not ``keyed``: the flat is moulded, so the solder-side
    shadow, which is drawn with ``keyed=None``, shows it as well.
    """
    rect = _body_rect(placement)
    path = QPainterPath()
    angle = right_angle_for(footprint, pitch)
    if angle is not None:
        # Only the moulding: the legs and the pins are drawn as what they are, gold, by
        # ``_paint_right_angle_pins`` -- see ``bodies.RightAngle``.
        moulding = QRectF(angle.left, angle.near, angle.right - angle.left, angle.far - angle.near)
        radius = min(moulding.width(), moulding.height()) * 0.12
        path.addRoundedRect(moulding, radius, radius)
        return path
    if placement.silhouette == "circle":
        path.addEllipse(rect)
        return path
    if placement.silhouette == "flat-face":
        profile = flat_face_profile(placement.size_x, placement.size_y)
        towards_x, towards_y = FLAT_FACE_LOCAL
        centre = QPointF(
            placement.centre_x + profile.shift * towards_x,
            placement.centre_y + profile.shift * towards_y,
        )
        r = profile.radius
        path.addEllipse(centre, r, r)
        side = QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r)
        if towards_y > 0:
            side.setBottom(centre.y() + profile.flat)
        elif towards_y < 0:
            side.setTop(centre.y() - profile.flat)
        elif towards_x > 0:
            side.setRight(centre.x() + profile.flat)
        else:
            side.setLeft(centre.x() - profile.flat)
        chord = QPainterPath()
        chord.addRect(side)
        return path.intersected(chord)
    if placement.silhouette == "rounded":
        radius = min(rect.width(), rect.height()) * 0.32
        path.addRoundedRect(rect, radius, radius)
        return path
    if placement.silhouette == "dcut" and keyed is not None:
        circle = QPainterPath()
        circle.addEllipse(rect)
        # Chop a chord off the cathode's side.
        cut = QRectF(rect)
        inset = rect.width() * 0.12 if placement.axis == "x" else rect.height() * 0.12
        if _flat_direction(footprint, placement, keyed, pitch) > 0:
            if placement.axis == "x":
                cut.setRight(rect.right() - inset)
            else:
                cut.setBottom(rect.bottom() - inset)
        else:
            if placement.axis == "x":
                cut.setLeft(rect.left() + inset)
            else:
                cut.setTop(rect.top() + inset)
        keep = QPainterPath()
        keep.addRect(cut)
        return circle.intersected(keep)
    if placement.silhouette == "dcut":
        path.addEllipse(rect)
        return path
    if footprint.body.archetype in BOARD_ARCHETYPES:
        # A module's board is a routed PCB, and its corners are square: drawn with the 12%
        # radius of a moulded case, a Nano came out a soft blue block with 2 mm corners, a
        # thing no board house makes. The 3D view already draws it as the box it is.
        path.addRect(rect)
        return path
    radius = min(rect.width(), rect.height()) * 0.12
    path.addRoundedRect(rect, radius, radius)
    return path


#: The archetypes whose body IS a printed circuit board -- a module, a chip's adapter -- and is
#: therefore cut with square corners, not moulded with round ones.
BOARD_ARCHETYPES = frozenset({"module-board", "smd-adapter"})


def _paint_body_shadow(
    painter: QPainter,
    footprint: Footprint,
    placement: BodyPlacement,
    selected: bool,
) -> None:
    """Where a part sits, seen through the board from the solder side.

    Hatched, not filled, and deliberately without a single one of the component-side
    marks. The distinction it has to carry is "something is on the other side here"
    rather than "here is a part", because on the solder side the second reading is how
    somebody solders a board backwards.

    Diagonal hatching rather than a tint because a tint competes with the pads for
    attention and this must never do that: on this side the pads ARE the subject.
    ``keyed=None`` is passed on purpose, so an LED's flat and a diode's band do not
    appear -- they are moulded into the top of the part and cannot be seen from below.
    """
    path = _body_path(footprint, placement, None)
    painter.setPen(QPen(QColor(SELECTED if selected else BODY_SHADOW_EDGE), 0.12))
    brush = QBrush(QColor(SELECTED if selected else BODY_SHADOW), Qt.BrushStyle.FDiagPattern)
    # Hatch patterns are defined in device pixels, so without this they would stay the
    # same size on screen while the board zooms -- turning into a solid block when zoomed
    # in and vanishing when zoomed out.
    brush.setTransform(painter.transform().inverted()[0])
    painter.setBrush(brush)
    painter.drawPath(path)


def _paint_body_sheen(
    painter: QPainter,
    path: QPainterPath,
    rect: QRectF,
    placement: BodyPlacement,
    style: BodyStyle,
) -> None:
    """A highlight along the top of the body, so it reads as a solid object.

    A flat fill is what made every part look like a sticker printed on the board. Real
    parts are round or moulded and catch the light along one edge, and how MUCH they catch
    is the difference between a plastic case and a metal can -- which is a fact
    ``bodies.surface_for`` owns, so the 3D view shades the same part the same way.

    Drawn across the body's SHORT axis, because that is the direction a cylinder curves
    in: a resistor lying on the board is lit along its length, not around its ends.
    """
    sheen = surface_for(style).sheen
    if sheen <= 0.0:
        return
    highlight = QColor(style.fill).lighter(100 + int(sheen * 120))
    highlight.setAlphaF(min(1.0, 0.35 + sheen * 0.5))
    band = QRectF(rect)
    if placement.axis == "x":
        band.setHeight(rect.height() * 0.34)
        band.moveTop(rect.top() + rect.height() * 0.13)
    else:
        band.setWidth(rect.width() * 0.34)
        band.moveLeft(rect.left() + rect.width() * 0.13)
    painter.save()
    painter.setClipPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(highlight))
    radius = min(band.width(), band.height()) * 0.5
    painter.drawRoundedRect(band, radius, radius)
    painter.restore()


def _paint_resistor_bands(
    painter: QPainter,
    path: QPainterPath,
    rect: QRectF,
    placement: BodyPlacement,
    bands: tuple[str, ...],
) -> None:
    """The printed colour code, across the body and clipped to it.

    Laid out from one end rather than centred, and with the tolerance band pushed to the
    far end, because that asymmetry is what tells a reader which way round to read the
    other three -- exactly as it does on the real part.
    """
    along = rect.width() if placement.axis == "x" else rect.height()
    if along <= 0:
        return
    width = along * 0.11
    painter.save()
    painter.setClipPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    for index, colour in enumerate(bands):
        # The first three sit in the near half; the tolerance band goes at the far end.
        fraction = 0.16 + index * 0.15 if index < len(bands) - 1 else 0.80
        band = QRectF(rect)
        if placement.axis == "x":
            band.setWidth(width)
            band.moveLeft(rect.left() + along * fraction)
        else:
            band.setHeight(width)
            band.moveTop(rect.top() + along * fraction)
        painter.setBrush(QBrush(QColor(colour)))
        painter.drawRect(band)
    painter.restore()


#: The ink a pin name on the board is printed in, and what it is printed on. White on a
#: grid of white pad rings is unreadable wherever the name crosses one, so a name off a
#: module sits on a tag -- a label stuck to the board, which is also what the builder
#: will put there. LIGHT, dark ink on a pale chip, chosen on 2026-10-28 with the board's
#: look: the dark tags were the largest dark shapes on a zoomed board after the chips.
PIN_NAME_INK = "#15171c"
PIN_NAME_TAG = QColor(236, 239, 244, 225)


def _ink_frame(comp: ComponentInstance, from_below: bool) -> tuple[float, bool]:
    """How the part's frame is turned on screen, and whether it is reflected there -- what
    printed ink has to undo to read the right way.

    From the solder side the view's reflection composes with the part's own: a part ON the
    solder side is mirrored and seen from below, and the two cancel, so its value reads
    plainly with nothing undone, turned the other way round (a reflection on each side of a
    turn reverses the turn).
    """
    rotation = -float(comp.rotation) if from_below else float(comp.rotation)
    return rotation, comp.mirrored != from_below


def _paint_pin_names(
    painter: QPainter,
    labels: tuple[PinLabel, ...],
    comp: ComponentInstance,
    module_ink: str,
    from_below: bool = False,
) -> None:
    """Each named pin's name, printed beside it -- see ``bodies.pin_labels`` for where and
    why, and ``bodies.lay_out_pin_names`` for what the rest of the board leaves room for.
    In the footprint's own frame, so the names turn with the part; each is kept upright on
    screen and unmirrored, and none is drawn when the view is too far out for 0.9 mm of ink
    to be anything but noise."""
    transform = painter.transform()
    if (transform.m11() ** 2 + transform.m12() ** 2) ** 0.5 < 5.0:
        return
    turned, reflected = _ink_frame(comp, from_below)
    for label in labels:
        width = physical_label_width_mm(label.name, PIN_NAME_HEIGHT_MM, label.room, bold=False)
        reach = label.start + width / 2
        centre = QPointF(label.x + label.dx * reach, label.y + label.dy * reach)
        rotation = 0.0 if label.dy == 0 else (90.0 if label.dy > 0 else -90.0)
        # Never upside down on screen: the frame is already turned with the part, so a
        # name that would come out reading backwards is turned half round about its own
        # centre, which leaves it exactly where it was.
        if 90.0 < (rotation + turned) % 360.0 < 270.0:
            rotation += 180.0
        painter.save()
        painter.translate(centre)
        if reflected:
            # The frame is reflected for a mirrored part; ink is not.
            painter.scale(-1.0, 1.0)
        # A name over a module's parts wears the tag the names on this board wear: chosen on
        # 2026-10-16 over one in the module's own board colour and a translucent one, side by
        # side on the XIAO and the two Pololu carriers -- it reads the same over a can, a
        # chip or bare board.
        tagged = not label.on_module or label.backed
        if tagged:
            painter.save()
            painter.rotate(rotation)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(PIN_NAME_TAG))
            tag_h = PIN_NAME_TAG_HEIGHT_MM
            pad = PIN_NAME_TAG_PAD_MM
            painter.drawRoundedRect(
                QRectF(-width / 2 - pad, -tag_h / 2, width + 2 * pad, tag_h), 0.3, 0.3
            )
            painter.restore()
        painter.setPen(QPen(QColor(PIN_NAME_INK if tagged else module_ink)))
        draw_physical_label(
            painter,
            QPointF(0.0, 0.0),
            label.name,
            PIN_NAME_HEIGHT_MM,
            bold=False,
            max_width_mm=label.room,
            rotation_deg=rotation,
        )
        painter.restore()


def _on_paper(painter: QPainter) -> bool:
    """Whether this is the 1:1 print: what is drawn for the eye on screen -- a shadow, a
    light -- stays off the sheet that gets taped to the board."""
    return isinstance(painter.device(), QPagedPaintDevice)


def _mixed(a: str, b: str, k: float) -> QColor:
    """``a`` taken ``k`` of the way toward ``b``."""
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * k),
        round(ca.green() + (cb.green() - ca.green()) * k),
        round(ca.blue() + (cb.blue() - ca.blue()) * k),
    )


def _screen_offset(painter: QPainter, dx_mm: float, dy_mm: float) -> QPointF:
    """A scene-space offset -- down and right on the screen, whichever way the part is
    turned or the board flipped -- in the painter's local frame."""
    world = painter.worldTransform()
    inverse, _invertible = world.inverted()
    scale = math.hypot(world.m11(), world.m12()) or 1.0
    origin = inverse.map(QPointF(0.0, 0.0))
    reach = inverse.map(QPointF(dx_mm * scale, dy_mm * scale))
    return QPointF(reach.x() - origin.x(), reach.y() - origin.y())


def _paint_contact_shadow(painter: QPainter, path: QPainterPath) -> None:
    """The body's own outline twice, dark and offset down-right on screen: what stands a
    part ON the board instead of printing it there. Two hard layers rather than a blur,
    which costs a filter pass per part per frame."""
    near, far = CONTACT_SHADOW_MM
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    for distance, alpha in ((far, CONTACT_SHADOW_ALPHA // 2), (near, CONTACT_SHADOW_ALPHA)):
        painter.setBrush(QColor(0, 0, 0, alpha))
        painter.drawPath(path.translated(_screen_offset(painter, distance, distance * 1.3)))
    painter.restore()


def _paint_body_light(painter: QPainter, path: QPainterPath) -> None:
    """Light from the top left across the body, dark toward the bottom right, clipped to
    it -- the screen's top-left, so every part on the board is lit from one side."""
    box = path.boundingRect()
    towards = _screen_offset(painter, -1.0, -1.0)
    length = math.hypot(towards.x(), towards.y()) or 1.0
    ux, uy = towards.x() / length, towards.y() / length
    reach = max(box.width(), box.height()) / 2
    centre = box.center()
    gradient = QLinearGradient(
        QPointF(centre.x() + ux * reach, centre.y() + uy * reach),
        QPointF(centre.x() - ux * reach, centre.y() - uy * reach),
    )
    gradient.setColorAt(0.0, QColor(255, 255, 255, BODY_LIGHT_ALPHA))
    gradient.setColorAt(0.5, QColor(255, 255, 255, 0))
    gradient.setColorAt(1.0, QColor(0, 0, 0, round(BODY_LIGHT_ALPHA * 1.3)))
    painter.save()
    painter.setClipPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    painter.drawPath(path)
    painter.restore()


def _paint_top_marking(
    painter: QPainter,
    footprint: Footprint,
    placement: BodyPlacement,
    comp: ComponentInstance,
    rect: QRectF | None = None,
    from_below: bool = False,
    names: tuple[PinLabel, ...] = (),
    pitch: float | None = None,
) -> None:
    """What a part says on its top: its value, as the part carries it -- a DIP's part number
    along the package, a sealed relay's part number over the contact diagram moulded beside
    it, an HC-49 can's frequency, a pot's value stamped in its cover in front of the shaft.
    Physical ink, so it scales with the board and prints on the 1:1 sheet too. ``rect`` is
    where the print goes when the measured top view says (``TopView.marking``): on the
    case's flat top, inside the shoulders, rather than across the whole body DRC measures.
    A DIP's part number in capitals, as chips are lasered; anything else as the document
    has it, as the 3D view prints it -- "16MHz" in capitals is a different unit. A DIP's is
    lasered, in the chip face (``_paint_laser_text``), beside the dimple moulded by pin 1
    (``_paint_dip_dimple``, given the ``pitch`` the pins are at)."""
    archetype = footprint.body.archetype
    if archetype == "dip" and rect is not None and pitch is not None and not any(
        label.on_body for label in names
    ):
        _paint_dip_dimple(painter, footprint, rect, pitch)
    text = comp.value.strip()
    if archetype not in TOP_PRINTED_ARCHETYPES or not text:
        return
    if archetype == "potentiometer":
        _paint_pot_marking(painter, placement, comp, text, from_below, _top_marking_ink(footprint))
        return
    if rect is None:
        rect = _body_rect(placement)
    # As tall as the whole package allows, even when the print moves into a strip of it.
    package_short = min(rect.width(), rect.height())
    if any(label.on_body for label in names):
        # Pin names printed on the chip (``bodies._on_its_own_top``): the print moves into
        # the room they leave, and when they leave none, the names are what it says.
        gap = _marking_gap(rect, names)
        if gap is None:
            return
        rect = gap
    along_x = rect.width() >= rect.height()
    long_side, short_side = (rect.width(), rect.height()) if along_x else (rect.height(), rect.width())
    rotation = 0.0 if along_x else 90.0
    turned, reflected = _ink_frame(comp, from_below)
    # Never upside down on screen, as the pin names are not.
    if 90.0 < (rotation + turned) % 360.0 < 270.0:
        rotation += 180.0
    ink = _top_marking_ink(footprint)
    painter.save()
    painter.translate(rect.center())
    if reflected:
        painter.scale(-1.0, 1.0)
    painter.setPen(ink)
    if archetype == "relay-box":
        painter.rotate(rotation)
        height = min(RELAY_MARKING_MM, short_side * 0.1)
        draw_physical_label(
            painter,
            QPointF(0.0, -height * 0.9),
            text,
            height,
            bold=True,
            max_width_mm=long_side * 0.62,
        )
        _paint_relay_diagram(painter, ink, height)
    elif archetype == "dip":
        painter.rotate(rotation)
        _paint_laser_text(
            painter,
            text.upper(),
            min(TOP_MARKING_MM, package_short * 0.16, short_side * 0.7),
            long_side * TOP_MARKING_SHARE,
        )
    else:
        draw_physical_label(
            painter,
            QPointF(0.0, 0.0),
            text if archetype == "crystal-hc49" else text.upper(),
            min(CRYSTAL_MARKING_MM, short_side * 0.2)
            if archetype == "crystal-hc49"
            else min(TOP_MARKING_MM, package_short * 0.16, short_side * 0.7),
            bold=False,
            max_width_mm=long_side * (0.45 if archetype == "crystal-hc49" else TOP_MARKING_SHARE),
            rotation_deg=rotation,
        )
    painter.restore()


#: A DIP's pin-1 dimple: its radius against the flat top's short side, and how far in from
#: the top's corner by pin 1 it sits, in radii.
DIP_DIMPLE_SHARE = 0.09
DIP_DIMPLE_INSET = 2.0


def _paint_dip_dimple(painter: QPainter, footprint: Footprint, top: QRectF, pitch: float) -> None:
    """The round dimple a DIP is moulded with in the corner of its top by pin 1, beside the
    notch: the mark people who do not look for the notch look for. A shade lighter than the
    case, its rim darker -- an indent, not a printed dot."""
    one = next((pin for pin in footprint.pins if pin.number == "1"), None)
    if one is None:
        return
    centre = top.center()
    radius = min(top.width(), top.height()) * DIP_DIMPLE_SHARE
    inset = radius * DIP_DIMPLE_INSET
    x = centre.x() + math.copysign(top.width() / 2 - inset, one.d_col * pitch - centre.x())
    y = centre.y() + math.copysign(top.height() / 2 - inset, one.d_row * pitch - centre.y())
    fill = QColor(style_for(footprint).fill)
    painter.save()
    painter.setPen(QPen(fill.darker(250), 0.06))
    painter.setBrush(QBrush(fill.lighter(160)))
    painter.drawEllipse(QPointF(x, y), radius, radius)
    painter.restore()


def _marking_gap(rect: QRectF, names: tuple[PinLabel, ...]) -> QRectF | None:
    """The widest strip of ``rect`` along its long side that no pin name printed on the
    part covers, in the part's own frame; None when that leaves less than a line of print.
    A name on the top runs across the package from its pin, so it covers an interval of
    the short side, its tag and all -- if it stands where the print runs, the middle
    ``TOP_MARKING_SHARE`` of the package: PB2 at the end of a DIP-28 is not in its way."""
    along_x = rect.width() >= rect.height()
    low, high = (rect.top(), rect.bottom()) if along_x else (rect.left(), rect.right())
    middle, long_side = (
        (rect.center().x(), rect.width()) if along_x else (rect.center().y(), rect.height())
    )
    reach = long_side * TOP_MARKING_SHARE / 2 + PIN_NAME_TAG_HEIGHT_MM / 2
    covered: list[tuple[float, float]] = []
    for label in names:
        if not label.on_body or abs((label.x if along_x else label.y) - middle) > reach:
            continue
        pin, way = (label.y, label.dy) if along_x else (label.x, label.dx)
        ends = (
            pin + way * (label.start - PIN_NAME_TAG_PAD_MM),
            pin + way * (label.start + label.room + PIN_NAME_TAG_PAD_MM),
        )
        covered.append((min(ends), max(ends)))
    best: tuple[float, float] = (low, low)
    edge = low
    for start, end in sorted([*covered, (high, high)]):
        if start - edge > best[1] - best[0]:
            best = (edge, start)
        edge = max(edge, end)
    a, b = best
    if b - a < TOP_MARKING_MM * 1.2:
        return None
    if along_x:
        return QRectF(rect.left(), a, rect.width(), b - a)
    return QRectF(a, rect.top(), b - a, rect.height())


#: The parts whose top carries their value in print, seen from above. Not a TO-92 or a
#: TO-220: theirs is on the front face, which this view does not see, and printing it on top
#: would draw a part that does not exist. The 3D view prints the relay and the pot
#: (``view3d.PRINTED_ARCHETYPES``); the crystal's frequency is stamped on its domed cap,
#: which only this flat view can ink without bending the glyphs over it.
TOP_PRINTED_ARCHETYPES = frozenset({"dip", "relay-box", "crystal-hc49", "potentiometer"})
#: How much of a package's length its print may take, at most.
TOP_MARKING_SHARE = 0.62
#: How tall a relay's part number is printed: Songle's is about this, in bold.
RELAY_MARKING_MM = 1.5
#: An HC-49 can's frequency, stamped smaller than a chip's print: the can is 4.65 mm across.
CRYSTAL_MARKING_MM = 0.75
#: Dark ink, for print on a light case -- a crystal's steel, where the etched grey a black
#: chip carries vanished into the metal.
TOP_MARKING_INK_DARK = QColor(40, 42, 48, 190)


def _top_marking_ink(footprint: Footprint) -> QColor:
    return TOP_MARKING_INK if QColor(style_for(footprint).fill).lightness() < 150 else TOP_MARKING_INK_DARK


def _paint_relay_diagram(painter: QPainter, ink: QColor, height: float) -> None:
    """The coil and the change-over contact printed under a relay's part number, as the
    cans carry them: a box for the coil, a blade from the common to one of two contacts.
    In the frame the part number was just drawn in, centred under it."""
    unit = height / RELAY_MARKING_MM
    painter.save()
    painter.scale(unit, unit)
    painter.setPen(QPen(ink, 0.16))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    top = 0.5
    painter.drawRect(QRectF(-3.0, top, 1.8, 1.3))
    painter.drawLine(QPointF(-2.1, top - 0.4), QPointF(-2.1, top))
    painter.drawLine(QPointF(-2.1, top + 1.3), QPointF(-2.1, top + 1.7))
    painter.drawLine(QPointF(0.8, top + 1.7), QPointF(0.8, top + 1.0))
    painter.drawLine(QPointF(0.8, top + 1.0), QPointF(2.5, top + 0.2))
    painter.drawEllipse(QPointF(2.7, top + 0.05), 0.18, 0.18)
    painter.drawEllipse(QPointF(2.7, top + 1.3), 0.18, 0.18)
    painter.restore()


def _paint_pot_marking(
    painter: QPainter,
    placement: BodyPlacement,
    comp: ComponentInstance,
    text: str,
    from_below: bool,
    ink: QColor,
) -> None:
    """A pot's value, stamped into its cover in front of the bushing -- where the 3D view
    stamps it (``view3d._pot_pieces``) -- and level on screen however the pot is turned: it
    is round, so no side of it is "along"."""
    rect = _body_rect(placement)
    radius = min(rect.width(), rect.height()) / 2
    turned, reflected = _ink_frame(comp, from_below)
    painter.save()
    painter.translate(rect.center())
    if reflected:
        painter.scale(-1.0, 1.0)
    painter.rotate(-turned)
    painter.setPen(ink)
    draw_physical_label(
        painter,
        QPointF(0.0, radius * (1 + POT_BUSHING_SHARE) / 2),
        text,
        radius * 0.17,
        bold=False,
        max_width_mm=radius * (1 - POT_BUSHING_SHARE) * 1.7,
    )
    painter.restore()


#: A panel pot's bushing and shaft as shares of its radius: the common 16 mm part's M7
#: bushing and 6 mm shaft, the proportions ``view3d._pot_pieces`` turns them in.
POT_BUSHING_SHARE = 0.44
POT_SHAFT_SHARE = 0.375
#: The knurl's teeth round the shaft, seen end on.
POT_KNURL_TEETH = 24


#: How much darker a case's sloped side is drawn than its flat top, as ``QColor.darker``
#: takes it. Most of a cylinder seen from above is its side, so this is what a resistor's
#: colour mostly IS: at 118 a beige 0207 read khaki. Chosen from rendered candidates.
FLANK_SHADE = 106


def _role_colour(role: str, style: BodyStyle, ink: str | None = None) -> QColor:
    """How a top view's role is inked: from the part's own colours and the leads' metal, so
    no colour is added that ``bodies.BODY_STYLES`` and the board look do not already have.
    The flank is the case turned away from the light, a recess the moulding cut into, and a
    groove in metal the metal in shadow. A recess reads by CONTRAST with its case: lighter on
    a dark one (a DIP's notch), darker on a light one -- lightened, a red LED's flange and a
    ceramic disc's dimple came out pink and pale, a different part.

    A measured marking is the colour its piece is in 3D (``ink``): one accent for an LCD's
    bezel and its glass drew a grey slab, and a big button's dark collar came out cream."""
    if role == "marking" and ink:
        return QColor(ink)
    fill = QColor(style.fill)
    if role == "flank":
        return fill.darker(FLANK_SHADE)
    if role == "recess":
        return fill.lighter(165) if fill.lightness() < 90 else fill.darker(130)
    if role == "plastic":
        return QColor(style.edge)
    if role == "metal":
        return QColor(LEAD)
    if role == "metal-recess":
        return QColor(LEAD).darker(150)
    if role == "marking":
        return QColor(style.accent)
    return fill


def _paint_top_view(
    painter: QPainter,
    view: TopView,
    style: BodyStyle,
    selected: bool,
    placement: BodyPlacement,
    bands: tuple[str, ...] | None,
) -> None:
    """A part as it is seen from straight above, from the measured outlines of the very mesh
    the 3D view draws (``topview``): a DIP narrower than its rows with a metal shoulder out
    to every hole, a TO-220's tab, a terminal block's screws. On screen it stands on the
    board as every body does -- the contact shadow on the whole silhouette, the light
    clipped to the case -- and on the 1:1 sheet it is flat ink, as the rest of the print is.
    """
    on_screen = not _on_paper(painter)
    if on_screen:
        _paint_contact_shadow(painter, view.silhouette)
    painter.setPen(Qt.PenStyle.NoPen)
    for role, path, ink in view.shapes:
        painter.setBrush(QBrush(_role_colour(role, style, ink)))
        painter.drawPath(path)
    case = view.body
    if not case.isEmpty():
        # The material's own sheen first, as every drawn body has it: without it a beige
        # resistor and a blue trimmer, lit only by the light below, went dull.
        _paint_body_sheen(painter, case, case.boundingRect(), placement, style)
    if on_screen and not case.isEmpty():
        _paint_body_light(painter, case)
    # After the light, so the mark is flat and reads at a glance on screen and on paper alike.
    if not view.polarity.isEmpty():
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(style.accent)))
        painter.drawPath(view.polarity)
    if bands and not case.isEmpty():
        _paint_resistor_bands(painter, case, case.boundingRect(), placement, bands)
    if not case.isEmpty():
        # Round the case AND what is printed on it: outlined alone, the case drew a dark line
        # along every edge it shares with a stripe or a band, splitting the mark in pieces.
        outline = case
        for role, path, _ink in view.shapes:
            if role == "marking":
                outline = outline.united(path)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(SELECTED if selected else style.edge), 0.2 if selected else 0.1))
        painter.drawPath(outline.simplified())


#: A chip's top marking: laser-etched grey on black, about a millimetre tall.
TOP_MARKING_INK = QColor(220, 224, 232, 150)
TOP_MARKING_MM = 1.0


def _paint_body(
    painter: QPainter,
    footprint: Footprint,
    placement: BodyPlacement,
    style: BodyStyle,
    keyed: tuple[float, float] | None,
    selected: bool,
    pitch: float,
    bands: tuple[str, ...] | None = None,
    art: tuple[PlacedArt, ...] | None = None,
    art_cache: ArtCache | None = None,
) -> bool:
    """Paint the body in the part's own frame; True when that included its pins' pads
    (a recognised module's plated holes), which the item then leaves out."""
    rect = _body_rect(placement)
    path = _body_path(footprint, placement, keyed, pitch)
    angle = right_angle_for(footprint, pitch)
    if footprint.body.archetype == "module-board" and art and angle is None:
        _paint_module_board(painter, footprint, path, QColor(style.fill), selected, pitch, art, art_cache)
        return True
    on_screen = not _on_paper(painter)
    if on_screen:
        _paint_contact_shadow(painter, path)
    if angle is not None:
        _paint_right_angle_pins(painter, footprint, angle, pitch, QColor(style.accent))

    painter.setBrush(QBrush(QColor(style.fill)))
    painter.setPen(QPen(QColor(SELECTED if selected else style.edge), 0.2))
    painter.drawPath(path)

    accent = QColor(style.accent)
    archetype = footprint.body.archetype

    # Before the marks, so a cathode band or a pin-1 dot stays flat and readable on top of
    # it rather than being washed out by a highlight painted over it. Not on a board: a
    # sheen is moulded plastic catching the light, and a PCB is flat solder mask -- on a
    # Nano it was a soft oval that made the board read as a block.
    if archetype not in BOARD_ARCHETYPES:
        _paint_body_sheen(painter, path, rect, placement, style)
    if on_screen:
        _paint_body_light(painter, path)

    # From above, a resistor stood on end is its end cap: the bands are round its side,
    # where this view cannot see them (the 3D view prints them).
    if bands and archetype != "axial-upright":
        _paint_resistor_bands(painter, path, rect, placement, bands)

    if archetype == "axial-upright" and keyed is not None:
        # A diode stood on end shows its band from above only when the banded end -- the
        # cathode, pin 1 -- is the one at the top, i.e. when it is NOT standing on pin 1: a
        # ring round the end cap. Banded end down, the band is under the body, and nothing
        # is drawn that the part does not show.
        cathode_up = math.hypot(keyed[0] - placement.centre_x, keyed[1] - placement.centre_y) > 0.05
        if cathode_up:
            ring = max(min(rect.width(), rect.height()) * 0.14, 0.3)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, ring))
            painter.drawEllipse(rect.adjusted(ring / 2, ring / 2, -ring / 2, -ring / 2))

    elif archetype == "axial-cylinder" and keyed is not None:
        # A diode's cathode band. Clipped to the body so it cannot spill past a rounded end.
        painter.setClipPath(path)
        band = QRectF(rect)
        width = max(rect.width() * 0.17, 0.45) if placement.axis == "x" else rect.width()
        height = rect.height() if placement.axis == "x" else max(rect.height() * 0.17, 0.45)
        if placement.axis == "x":
            band.setWidth(width)
            if _keyed_direction(placement, keyed) > 0:
                band.moveRight(rect.right() - rect.width() * 0.16)
            else:
                band.moveLeft(rect.left() + rect.width() * 0.16)
        else:
            band.setHeight(height)
            if _keyed_direction(placement, keyed) > 0:
                band.moveBottom(rect.bottom() - rect.height() * 0.16)
            else:
                band.moveTop(rect.top() + rect.height() * 0.16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(accent))
        painter.drawRect(band)
        painter.setClipping(False)

    elif archetype == "radial-electrolytic" and keyed is not None:
        # The printed stripe marks the NEGATIVE side, so it goes opposite pin 1.
        painter.setClipPath(path)
        stripe = QRectF(rect)
        if placement.axis == "x":
            stripe.setWidth(rect.width() * ELECTROLYTIC_STRIPE_SHARE)
            if _keyed_direction(placement, keyed) > 0:
                stripe.moveLeft(rect.left())
            else:
                stripe.moveRight(rect.right())
        else:
            stripe.setHeight(rect.height() * ELECTROLYTIC_STRIPE_SHARE)
            if _keyed_direction(placement, keyed) > 0:
                stripe.moveTop(rect.top())
            else:
                stripe.moveBottom(rect.bottom())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(accent))
        painter.drawRect(stripe)
        painter.setClipping(False)

    elif archetype == "dip" and keyed is not None:
        # The moulded notch at the keyed end and a dot by pin 1 -- both, because a real
        # package has both and people look for whichever they are used to.
        #
        # CLIPPED to the body and drawn in a lighter shade of it. Painting the notch as a
        # filled circle in the edge colour instead put a large near-black disc bulging out of
        # a near-black package: invisible as a mark, and wrong as a silhouette. An indent has
        # to read as part of the body, which means inside its outline and lit differently.
        painter.setClipPath(path)
        notch = min(rect.width(), rect.height()) * 0.17
        painter.setBrush(QBrush(QColor(style.fill).lighter(190)))
        painter.setPen(Qt.PenStyle.NoPen)
        if placement.axis == "y":
            cy = rect.top() if _keyed_direction(placement, keyed) < 0 else rect.bottom()
            painter.drawEllipse(QPointF(rect.center().x(), cy), notch, notch)
        else:
            cx = rect.left() if _keyed_direction(placement, keyed) < 0 else rect.right()
            painter.drawEllipse(QPointF(cx, rect.center().y()), notch, notch)
        painter.setClipping(False)

        dot = min(rect.width(), rect.height()) * 0.075
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(
            QPointF(
                rect.center().x() + (keyed[0] - placement.centre_x) * 0.6,
                rect.center().y() + (keyed[1] - placement.centre_y) * 0.6,
            ),
            dot,
            dot,
        )

    elif archetype == "to220":
        # The metal tab, along the edge away from the pins.
        painter.setPen(QPen(QColor(style.edge), 0.12))
        painter.setBrush(QBrush(accent))
        tab = QRectF(rect)
        if placement.axis == "x":
            tab.setHeight(rect.height() * 0.34)
            tab.moveTop(rect.top())
        else:
            tab.setWidth(rect.width() * 0.34)
            tab.moveLeft(rect.left())
        painter.drawRect(tab)

    elif archetype == "pin-header":
        _paint_pin_marks(painter, footprint, pitch, accent, square=True)

    elif archetype == "pin-socket":
        _paint_socket_mouths(painter, footprint, pitch, accent)

    elif archetype == "pin-socket-ra" and angle is not None:
        # The mouths are on the far face, where this view cannot look into them: a notch
        # in the far edge over each column says which side a header goes in from.
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 170)))
        depth = min(0.45, (angle.far - angle.near) * 0.12)
        for x in sorted({pin.d_col * pitch for pin in footprint.pins}):
            painter.drawRect(QRectF(x - SOCKET_MOUTH_MM / 2, angle.far - depth, SOCKET_MOUTH_MM, depth))
        painter.setClipping(False)

    elif archetype == "box-header":
        # The cavity the socket goes into, and the key slot through the wall on the pin-1
        # row -- local -y, the side of row 0, where ``box_header_footprint`` puts it. Drawn
        # in the local frame like everything here, so it turns with the part.
        wall = min(rect.width(), rect.height()) * 0.13
        cavity = rect.adjusted(wall, wall, -wall, -wall)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(style.fill).lighter(170)))
        painter.drawRect(cavity)
        slot = footprint.body.dims.get("keySlot", 4.5)
        painter.drawRect(QRectF(rect.center().x() - slot / 2, rect.top(), slot, wall))
        _paint_pin_marks(painter, footprint, pitch, accent, square=True)

    elif archetype == "wire-to-board":
        # Where there is no mesh: the cavity the plug goes into, open to the side it comes
        # from, and the posts standing in it.
        wall = min(rect.width(), rect.height()) * 0.13
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(style.fill).darker(115)))
        painter.drawRect(rect.adjusted(wall, wall, -wall, -wall))
        _paint_pin_marks(painter, footprint, pitch, accent, square=True)

    elif archetype == "screw-terminal":
        _paint_pin_marks(painter, footprint, pitch, accent, square=False)
        _paint_wire_entries(painter, footprint, rect, pitch)

    elif archetype == "smd-adapter":
        _paint_adapter(painter, footprint, rect, keyed)

    elif archetype == "module-board" and art:
        _paint_module_art(painter, art)

    elif archetype == "module-board":
        # The module's chip, as a dark block in the middle of its board: enough to read as
        # a board with something on it rather than an empty rectangle, and no more -- the
        # pin names beside the pins are what this view is for (``_paint_pin_names``). A
        # module ``moduleart`` recognises is drawn as what is on it instead, above.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#1b1d22")))
        chip_w, chip_h = module_block_size(rect.width(), rect.height())
        painter.drawRect(
            QRectF(rect.center().x() - chip_w / 2, rect.center().y() - chip_h / 2, chip_w, chip_h)
        )

    elif archetype == "screw-terminal-vertical":
        # Seen from above, the openings ARE the top: a dark square per way over its pin,
        # which is where the wires go in -- and no mark on any side, because no side is the
        # mouth. The screws are on the plug's face and are not what this view is about.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
        side = 0.55 * pitch
        for pin in footprint.pins:
            x, y = pin.d_col * pitch, pin.d_row * pitch
            painter.drawRect(QRectF(x - side / 2, y - side / 2, side, side))

    elif archetype == "potentiometer":
        _paint_pot_shaft(painter, rect, style)

    elif archetype == "tactile-switch":
        # The button: the thing a finger has to reach.
        radius = min(rect.width(), rect.height()) * 0.24
        painter.setPen(QPen(QColor(style.edge), 0.14))
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(rect.center(), radius, radius)
    return False


def _paint_pot_shaft(painter: QPainter, rect: QRectF, style: BodyStyle) -> None:
    """A panel pot from above, as the 3D view turns it (``view3d._pot_pieces``): the
    threaded bushing a panel nut goes on, the knurled shaft a knob goes on, and the
    screwdriver slot across its end. It was a small grey dot on a blue disc, which said
    "round part" and not "pot"; picked by Sinan on 2026-11-23 from rendered candidates."""
    centre = rect.center()
    radius = min(rect.width(), rect.height()) / 2
    bushing = radius * POT_BUSHING_SHARE
    shaft = radius * POT_SHAFT_SHARE
    painter.setPen(QPen(QColor(style.edge), 0.12))
    painter.setBrush(QBrush(LEAD.darker(125)))
    painter.drawEllipse(centre, bushing, bushing)
    painter.setBrush(QBrush(LEAD.lighter(108)))
    painter.drawEllipse(centre, shaft, shaft)
    painter.setPen(QPen(LEAD.darker(160), 0.1))
    for tooth in range(POT_KNURL_TEETH):
        angle = 2 * math.pi * tooth / POT_KNURL_TEETH
        dx, dy = math.cos(angle), math.sin(angle)
        painter.drawLine(
            QPointF(centre.x() + shaft * 0.78 * dx, centre.y() + shaft * 0.78 * dy),
            QPointF(centre.x() + shaft * dx, centre.y() + shaft * dy),
        )
    slot = QPen(LEAD.darker(190), shaft * 0.26)
    slot.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(slot)
    painter.drawLine(QPointF(centre.x() - shaft * 0.7, centre.y()), QPointF(centre.x() + shaft * 0.7, centre.y()))


def _paint_adapter(
    painter: QPainter,
    footprint: Footprint,
    rect: QRectF,
    keyed: tuple[float, float] | None,
) -> None:
    """A chip on its adapter, from above: its legs out to either side, its moulding, and the
    dot by pin 1. The header pins need nothing here -- the item draws every pin over the
    body, pin 1 ringed, as it does for a module.

    In the footprint's frame, where the legs run along y as the DIP's pins do, and from the
    footprint's own ``dims`` -- the chip's JEDEC outline -- so a TSSOP-20 is drawn finer
    than a SOIC-8 rather than as one picture of "a chip". The 3D view reads the same keys.
    """
    dims = footprint.body.dims
    cx, cy = rect.center().x(), rect.center().y()
    length = dims.get("chipLength", rect.height() * 0.5)
    body = dims.get("chipWidth", rect.width() * 0.4)
    span = dims.get("chipSpan", body * 1.5)
    leg_pitch = dims.get("chipPitch", 1.27)
    per_side = max(1, len(footprint.pins) // 2)
    leg = leg_pitch * 0.45
    painter.setPen(QPen(QColor("#0c0d10"), 0.03))
    painter.setBrush(QBrush(LEAD))
    for index in range(per_side):
        y = cy + (index - (per_side - 1) / 2) * leg_pitch
        painter.drawRect(QRectF(cx - span / 2, y - leg / 2, (span - body) / 2, leg))
        painter.drawRect(QRectF(cx + body / 2, y - leg / 2, (span - body) / 2, leg))
    painter.setBrush(QBrush(_art_colour("epoxy")))
    painter.drawRect(QRectF(cx - body / 2, cy - length / 2, body, length))
    if keyed is not None:
        # The dot in the chip's pin-1 corner: towards pin 1's column and pin 1's end.
        dot = min(0.4, body * 0.1)
        inset = dot * 2.2
        sx = -1.0 if keyed[0] < cx else 1.0
        sy = -1.0 if keyed[1] < cy else 1.0
        painter.setBrush(QBrush(QColor(BODY_STYLES["smd-adapter"].accent)))
        painter.drawEllipse(
            QPointF(cx + sx * (body / 2 - inset), cy + sy * (length / 2 - inset)), dot, dot
        )


# -- what stands on a recognised module, from above ---------------------------------------
#
# THE PARTS THE 3D VIEW STANDS UP, SEEN FROM ABOVE. The block a module was drawn as said
# nothing about which way round it was -- an ESP32 devkit's antenna end and its USB end
# were the same -- and the module's pin names stopped short of parts this view did not
# show. Each part is the shape it has from above, in ``moduleart.ART_COLOURS``, the table
# the 3D view paints with: a can is a circle, a chip a dark rectangle with its legs, a radio
# module its can and its antenna. What the layout says is printed on a part -- a chip's
# number, a can's name, the board's own silkscreen -- is printed, in the inks the 3D view
# uses, and nothing it does not say: no guessed value on a resistor, no certification ids.
# On screen the parts are lit as the bodies are (``_ArtLook``) and the whole board is
# painted once per zoom (``ArtCache``); on the 1:1 sheet they are flat.


def _art_colour(name: str) -> QColor:
    return QColor(ART_COLOURS[name])


def _art_box(painter: QPainter, x0: float, x1: float, half: float, colour: QColor) -> None:
    """A rectangle along the part's own axis, from ``x0`` to ``x1``, ``half`` either side."""
    painter.setBrush(QBrush(colour))
    painter.drawRect(QRectF(x0, -half, x1 - x0, 2 * half))


def _art_legs(
    painter: QPainter, x0: float, x1: float, at: Sequence[float], width: float
) -> None:
    """Legs from ``x0`` to ``x1`` along the part's own axis, one at each ``at`` across it."""
    painter.setBrush(QBrush(LEAD))
    for across in at:
        painter.drawRect(QRectF(min(x0, x1), across - width / 2, abs(x1 - x0), width))


def _rect_path(x0: float, x1: float, y0: float, y1: float) -> QPainterPath:
    path = QPainterPath()
    path.addRect(QRectF(x0, y0, x1 - x0, y1 - y0))
    return path


def _paint_standing_board(
    painter: QPainter, placed: PlacedStanding, style: BodyStyle, selected: bool
) -> None:
    """A board standing on its edge (``moduleart.fit_standing_board``), from straight above:
    the header's plastic behind it, the board's top edge, and what stands out of its front
    -- an HC-SR04's two cans as the cylinders they are, lying out across this board, and its
    crystal along the top. Square, unlit: a board is not moulded."""
    x0, x1, y0, y1, _z0, _z1 = placed.board
    hx0, hx1, hy0, hy1, _hz0, _hz1 = placed.header
    shapes: list[tuple[QPainterPath, QColor]] = [
        (_rect_path(hx0, hx1, hy0, hy1), _art_colour("switch")),
        (_rect_path(x0, x1, y0, y1), QColor(placed.board_colour)),
    ]
    can = _art_colour("shield")
    for part in placed.parts:
        half = part.length / 2
        if part.kind == "transducer":
            shapes.append((_rect_path(part.x - half, part.x + half, part.y0, part.y1), can))
            # The light along the top of the cylinder, and its rolled rim at the mesh.
            shapes.append(
                (_rect_path(part.x - half * 0.3, part.x + half * 0.3, part.y0, part.y1), can.lighter(110))
            )
            shapes.append((_rect_path(part.x - half, part.x + half, part.y1 - 0.8, part.y1), can.darker(135)))
        elif part.kind == "crystal":
            shapes.append((_rect_path(part.x - half, part.x + half, part.y0, part.y1), can.darker(108)))
    outline = QPainterPath()
    for path, _colour in shapes:
        outline = outline.united(path)
    outline = outline.simplified()
    if not _on_paper(painter):
        _paint_contact_shadow(painter, outline)
    painter.setPen(Qt.PenStyle.NoPen)
    for path, colour in shapes:
        painter.setBrush(QBrush(colour))
        painter.drawPath(path)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(SELECTED if selected else style.edge), 0.2 if selected else 0.1))
    painter.drawPath(outline)


def _paint_plus_mark(painter: QPainter, footprint: Footprint, pitch: float) -> None:
    """A buzzer's "+" on its top, beside its + leg (``bodies.plus_mark``)."""
    at = plus_mark(footprint, pitch)
    if at is None:
        return
    half = PLUS_MARK_MM / 2
    pen = QPen(QColor(PLUS_MARK_INK), PLUS_MARK_STROKE_MM)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.save()
    painter.setPen(pen)
    x, y = at
    painter.drawLine(QPointF(x - half, y), QPointF(x + half, y))
    painter.drawLine(QPointF(x, y - half), QPointF(x, y + half))
    painter.restore()


#: The hairline round each part of a module's art.
ART_EDGE = QColor("#0c0d10")
#: A part's shadow on its module's board, on screen: how far it falls for a part of no
#: height, how much further per millimetre the part stands, at most, and its two steps'
#: darkness -- far and near. Much less than a body's contact shadow: these stand a
#: millimetre or two, on a board that is itself already lifted off the perfboard.
ART_SHADOW_BASE_MM = 0.08
ART_SHADOW_PER_MM = 0.06
ART_SHADOW_MAX_MM = 0.35
ART_SHADOW_ALPHA = (22, 34)
#: The rim of a pin-1 dimple catching the light, over the dot's own colour.
DIMPLE_RIM_ALPHA = 45
#: What is lasered on a chip and etched on a can, in the inks ``view3d`` prints them in
#: (``ART_COLOURS["ink"]`` and ``["etch"]``), let into the surface rather than over it.
ART_PRINT_ALPHA = 175
ART_ETCH_ALPHA = 215
#: A radio module's name on its can, and the room it leaves the can either side.
RF_NAME_MM = 1.15
RF_CAN_CORNER_MM = 0.5
#: A QFN's pads where they show along its sides.
QFN_PAD_PITCH_MM = 0.5
#: Silkscreen on a module's board: how much of its box the print's capitals fill, the corners
#: round a chip and their gap. A silk part's width is the box its letters were measured in.
SILK_TEXT_SHARE = 0.8
SILK_LINE_MM = 0.15
SILK_GAP_MM = 0.4
#: A module's plated holes, from above: the ring's radius and the header pin's tip.
MODULE_PAD_MM = 0.82
MODULE_PIN_TIP_MM = 0.64
#: The lit edge of a module's own board, on screen.
MODULE_EDGE_LIGHT_MM = 0.35
MODULE_EDGE_LIGHT_ALPHA = 70
#: The art cache's margin round the board for its contact shadow, and the largest image it
#: keeps: past that -- a module filling a deep zoom -- it is painted as it always was.
ART_CACHE_MARGIN_MM = 0.8
ART_CACHE_MAX_PX = 2048 * 2048
#: The sub-pixel steps a cached image is drawn at: a quarter of a pixel off at most.
ART_CACHE_PHASES = 4
#: How far an image held at one zoom is stretched to stand in for another while the zoom
#: is moving, before the part is painted directly instead (a factor, either way).
ART_CACHE_STRETCH = 2.0
#: How long a zoom must have settled before the stretched images are painted afresh.
ART_REFRESH_MS = 120


def _paint_module_art(painter: QPainter, parts: Sequence[PlacedArt]) -> None:
    """Each part in its own frame: its own axis along x, its feature (a can's stripe, a
    regulator's legs, an antenna) at +x, as ``view3d``'s builders have it.

    On screen each part that stands up off the board casts a small shadow down and to the
    right, metal catches the light and a package's top falls off from its lit corner
    (``_ArtLook``); on the 1:1 sheet all of that is left off and the parts are flat, as
    every other body on the print is."""
    look = _ArtLook(lit=not _on_paper(painter))
    if look.lit:
        _paint_art_shadows(painter, parts)
    painter.setPen(QPen(ART_EDGE, 0.05))
    for part in parts:
        painter.save()
        painter.translate(part.x, part.y)
        if part.axis == "y":
            painter.rotate(90)
        length, width = (part.size_x, part.size_y) if part.axis == "x" else (part.size_y, part.size_x)
        if part.kind == "silk":
            # Silkscreen the layout measured: the board's white ink, never upside down.
            _paint_art_print(
                painter, part.text, width * SILK_TEXT_SHARE, length,
                QColor(BODY_STYLES["module-board"].accent),
            )
            painter.restore()
            continue
        if part.facing < 0:
            # Mirrored along the axis rather than turned round: what is ACROSS the part --
            # a chip's pin-1 dot, a transistor's two legs -- stays on the side it is on.
            painter.scale(-1, 1)
        _paint_art_part(painter, part, length, width, look)
        painter.restore()


@dataclass(frozen=True, slots=True)
class _ArtLook:
    """How a module's parts are lit: on screen (``lit``) brushed metal, a moulded top and an
    edge catching the light from the top left; on paper, flat. Each brush keeps the part's
    own colour at its middle, so the part is still the colour ``ART_COLOURS`` gives it."""

    lit: bool

    def metal(self, rect: QRectF, base: QColor) -> QBrush:
        """Brushed metal: a bright band across the diagonal, falling off to either end."""
        if not self.lit:
            return QBrush(base)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, base.lighter(106))
        gradient.setColorAt(0.3, base.lighter(118))
        gradient.setColorAt(0.5, base)
        gradient.setColorAt(0.72, base.darker(104))
        gradient.setColorAt(1.0, base.darker(116))
        return QBrush(gradient)

    def moulded(self, rect: QRectF, base: QColor) -> QBrush:
        """A package's top: lighter at its lit corner, falling off to the shaded one."""
        if not self.lit:
            return QBrush(base)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, base.lighter(150))
        gradient.setColorAt(0.55, base)
        gradient.setColorAt(1.0, base.darker(130))
        return QBrush(gradient)

    def domed(self, centre: QPointF, radius: float, base: QColor, rise: int = 125) -> QBrush:
        """Something round and raised -- a button's stem, a plated ring: lit off-centre."""
        if not self.lit:
            return QBrush(base)
        gradient = QRadialGradient(
            QPointF(centre.x() - radius * 0.35, centre.y() - radius * 0.35), radius * 1.4
        )
        gradient.setColorAt(0.0, base.lighter(rise))
        gradient.setColorAt(1.0, base.darker(115))
        return QBrush(gradient)

    def bevel(
        self, painter: QPainter, rect: QRectF, width: float, strength: int, radius: float = 0.0
    ) -> None:
        """The edge of a box catching the light (``_paint_edge_light``), on screen only."""
        if self.lit:
            _paint_edge_light(painter, rect, width, strength, radius)


def _paint_edge_light(
    painter: QPainter, rect: QRectF, width: float, strength: int, radius: float = 0.0
) -> None:
    """The edge of a box catching the light: brighter along its top left and darker along
    its bottom right ON SCREEN, whichever way the part is turned, ``width`` into it."""
    towards = _screen_offset(painter, -1.0, -1.0)
    length = math.hypot(towards.x(), towards.y()) or 1.0
    ux, uy = towards.x() / length, towards.y() / length
    centre = rect.center()
    reach = max(rect.width(), rect.height()) / 2
    gradient = QLinearGradient(
        QPointF(centre.x() + ux * reach, centre.y() + uy * reach),
        QPointF(centre.x() - ux * reach, centre.y() - uy * reach),
    )
    gradient.setColorAt(0.0, QColor(255, 255, 255, strength))
    gradient.setColorAt(0.5, QColor(255, 255, 255, 0))
    gradient.setColorAt(0.5001, QColor(0, 0, 0, 0))
    gradient.setColorAt(1.0, QColor(0, 0, 0, min(255, round(strength * 1.2))))
    # A pen ``width`` wide round the outline drawn half that in: the band a clip would leave
    # of a pen twice as wide, without a clip path per part per frame.
    inner = rect.adjusted(width / 2, width / 2, -width / 2, -width / 2)
    painter.save()
    pen = QPen(QBrush(gradient), width)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if radius:
        corner = max(radius - width / 2, 0.0)
        painter.drawRoundedRect(inner, corner, corner)
    else:
        painter.drawRect(inner)
    painter.restore()


#: The parts whose legs lie flat on the board: only their moulding casts a shadow.
_LEGGED_KINDS = frozenset({"soic8", "sot223", *SOT23_LEGS, *GULL_WING_LEGS})
#: Printed on the board or let into it rather than standing on it: no shadow.
_FLAT_KINDS = frozenset({"silk", "hole", "pads", "pcb-antenna", "plate"})


def _paint_art_shadows(painter: QPainter, parts: Sequence[PlacedArt]) -> None:
    """A soft two-step shadow under each part, down and to the right on screen, longer for
    a taller part -- the contact shadow every body on the board has, at a part's scale."""
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    for part in parts:
        if part.kind in _FLAT_KINDS or part.height <= 0:
            continue
        reach = min(ART_SHADOW_BASE_MM + part.height * ART_SHADOW_PER_MM, ART_SHADOW_MAX_MM)
        size_x, size_y = part.size_x, part.size_y
        if part.kind in _LEGGED_KINDS:
            # Under the moulding only: the legs lie on the board and cast nothing.
            if part.axis == "x":
                size_y *= 0.6
            else:
                size_x *= 0.6
        path = QPainterPath()
        if part.diagonal:
            corners = art_outline(part)
            path.moveTo(QPointF(*corners[0]))
            for corner in corners[1:]:
                path.lineTo(QPointF(*corner))
            path.closeSubpath()
        elif part.kind in ("can", "capsule"):
            path.addEllipse(QPointF(part.x, part.y), size_x / 2, size_y / 2)
        else:
            path.addRect(QRectF(part.x - size_x / 2, part.y - size_y / 2, size_x, size_y))
        for share, alpha in zip((1.0, 0.5), ART_SHADOW_ALPHA, strict=True):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawPath(path.translated(_screen_offset(painter, reach * share, reach * share * 1.2)))
    painter.restore()


#: The face chips are lasered in: a plain sans with lining figures. The interface's own
#: face set "0805" in old-style figures, which no chip carries.
_LASER_FONT_PX = 64
_laser_font: QFont | None = None


def _paint_laser_text(painter: QPainter, text: str, height: float, room: float) -> None:
    """``text`` centred on the painter's origin, its capitals ``height`` mm tall and the
    whole no wider than ``room`` -- as ``scenetext.draw_physical_label``, in the laser face."""
    global _laser_font
    if _laser_font is None:
        _laser_font = QFont("Arial")
        _laser_font.setStyleHint(QFont.StyleHint.SansSerif)
        _laser_font.setPixelSize(_LASER_FONT_PX)
    metrics = QFontMetricsF(_laser_font)
    cap = metrics.capHeight() or _LASER_FONT_PX * 0.7
    scale = height / cap
    width = max(metrics.horizontalAdvance(text), 1.0)
    if width * scale > room:
        scale = room / width
    painter.save()
    painter.scale(scale, scale)
    painter.setFont(_laser_font)
    line = metrics.height()
    painter.drawText(QRectF(-width, -line, 2 * width, 2 * line), int(Qt.AlignmentFlag.AlignCenter), text)
    painter.restore()


#: How far off a quarter turn a print still counts as on it: a part along y is turned by
#: exactly 90 degrees, which ``atan2`` gives back a hair either side of it.
PRINT_TURN_SLACK_DEG = 1e-6


def _paint_art_print(
    painter: QPainter,
    text: str,
    height: float,
    room: float,
    ink: QColor,
    at: QPointF | None = None,
    rotation: float = 0.0,
) -> None:
    """What is printed on a part or on the board, in the part's own frame along its axis:
    turned the right way up and unmirrored on screen, as a reader holds the board. It is
    physical, so it scales with the board and is on the 1:1 sheet too."""
    if not text:
        return
    painter.save()
    if at is not None:
        painter.translate(at)
    painter.rotate(rotation)
    world = painter.worldTransform()
    if world.determinant() < 0:
        painter.scale(1.0, -1.0)
        world = painter.worldTransform()
    # Upright, or up the screen when it runs across it: read from the board's right side,
    # as a board prints it and as the 3D view lays it (``view3d._ArtSolid.printed``).
    turned = math.degrees(math.atan2(world.m12(), world.m11())) % 360.0
    if 90.0 - PRINT_TURN_SLACK_DEG <= turned < 270.0 - PRINT_TURN_SLACK_DEG:
        painter.rotate(180.0)
    painter.setPen(ink)
    _paint_laser_text(painter, text, height, room)
    painter.restore()


def _art_ink(name: str, alpha: int) -> QColor:
    colour = _art_colour(name)
    colour.setAlpha(alpha)
    return colour


def _dot_side(part: PlacedArt) -> float:
    """Which side of its axis a chip's pin-1 dot is on, in the frame ``_paint_module_art``
    paints the part in (``PlacedArt.across``): the quarter turn that lays a part along y
    takes local x to the frame's -y. 0 for a chip whose dot is not drawn."""
    return float(part.across) if part.axis == "x" else -float(part.across)


def _paint_dimple(painter: QPainter, at: QPointF, radius: float) -> None:
    """A pin-1 dot moulded in a chip's top: the dot's colour, its rim catching the light."""
    painter.save()
    painter.setPen(QPen(QColor(255, 255, 255, DIMPLE_RIM_ALPHA), radius * 0.2))
    painter.setBrush(QBrush(_art_colour("dot")))
    painter.drawEllipse(at, radius, radius)
    painter.restore()


def _paint_art_part(
    painter: QPainter, part: PlacedArt, length: float, width: float, look: _ArtLook
) -> None:
    half_l, half_w = length / 2, width / 2
    kind = part.kind
    pin_one = _dot_side(part)
    edge = QPen(ART_EDGE, 0.05)
    epoxy = _art_colour("epoxy")
    ink = _art_ink("ink", ART_PRINT_ALPHA)
    if kind == "can":
        style = BODY_STYLES["radial-electrolytic"]
        radius = min(length, width) / 2
        painter.setBrush(look.domed(QPointF(0.0, 0.0), radius, QColor(style.fill), 135))
        painter.drawEllipse(QPointF(0.0, 0.0), radius, radius)
        painter.setBrush(QBrush(QColor(style.accent)))
        painter.drawPie(QRectF(-radius, -radius, 2 * radius, 2 * radius), -40 * 16, 80 * 16)
        cap_radius = radius - 0.75
        painter.setBrush(
            look.metal(
                QRectF(-cap_radius, -cap_radius, 2 * cap_radius, 2 * cap_radius),
                QColor(style.accent).darker(115),
            )
        )
        painter.drawEllipse(QPointF(0.0, 0.0), cap_radius, cap_radius)
    elif kind == "capsule":
        radius = min(length, width) / 2
        steel = _art_colour("shield")
        painter.setBrush(look.metal(QRectF(-radius, -radius, 2 * radius, 2 * radius), steel.darker(112)))
        painter.drawEllipse(QPointF(0.0, 0.0), radius, radius)
        inner = QColor(part.colour) if part.colour else steel
        painter.setBrush(look.domed(QPointF(0.0, 0.0), radius - 0.6, inner, 112))
        painter.drawEllipse(QPointF(0.0, 0.0), radius - 0.6, radius - 0.6)
    elif kind == "inductor":
        side = min(length, width)
        corner = min(1.6, side * 0.14)
        body = QRectF(-side / 2, -side / 2, side, side)
        painter.setBrush(look.moulded(body, _art_colour("ferrite")))
        painter.drawRoundedRect(body, corner, corner)
        look.bevel(painter, body, 0.3, 45, corner)
        painter.setBrush(look.domed(QPointF(0.0, 0.0), side * 0.36, _art_colour("ferrite-top"), 130))
        painter.drawEllipse(QPointF(0.0, 0.0), side * 0.36, side * 0.36)
    elif kind == "to263":
        tab, tails = 1.3, 2.5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(look.metal(QRectF(-half_l, -half_w, length, width), LEAD))
        painter.drawRect(QRectF(-half_l, -half_w * 0.86, tab + 0.6, half_w * 1.72))
        for index in range(5):
            painter.drawRect(QRectF(half_l - tails, (index - 2) * 1.7 - 0.4, tails, 0.8))
        top = QRectF(-half_l + tab, -half_w, length - tab - tails, width)
        painter.setPen(edge)
        painter.setBrush(look.moulded(top, epoxy))
        painter.drawRect(top)
        look.bevel(painter, top, 0.25, 50)
        _paint_art_print(painter, part.text, min(1.0, width * 0.12), top.height() * 0.8, ink, top.center(), 90)
    elif kind == "sot223" or kind in SOT23_LEGS:
        if kind == "sot223":
            moulding_mm = 3.5
            runs = [(moulding_mm / 2, half_l, across, 0.7) for across in (-2.3, 0.0, 2.3)]
            runs.append((-half_l, -moulding_mm / 2, 0.0, width * 0.47))
        else:
            moulding_mm = length * 0.55
            rear, front = SOT23_LEGS[kind]
            runs = [(-half_l, -moulding_mm / 2, width * at, 0.4) for at in rear]
            runs += [(moulding_mm / 2, half_l, width * at, 0.4) for at in front]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(look.metal(QRectF(-half_l, -half_w, length, width), LEAD))
        for x0, x1, across, wide in runs:
            painter.drawRect(QRectF(x0, across - wide / 2, x1 - x0, wide))
        top = QRectF(-moulding_mm / 2, -half_w, moulding_mm, width)
        painter.setPen(edge)
        painter.setBrush(look.moulded(top, epoxy))
        painter.drawRect(top)
        look.bevel(painter, top, 0.12, 50)
        _paint_art_print(painter, part.text, min(0.5, moulding_mm * 0.2), width * 0.8, ink, rotation=90)
    elif kind == "trimpot":
        screw = min(1.1, width * 0.25)
        body = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(look.moulded(body, _art_colour("trimmer")))
        painter.drawRect(body)
        look.bevel(painter, body, 0.2, 45)
        centre = QPointF(half_l - screw - 0.45, 0.0)
        painter.setBrush(look.domed(centre, screw, _art_colour("brass"), 135))
        painter.drawEllipse(centre, screw, screw)
    elif kind == "soic8" or kind in GULL_WING_LEGS:
        if kind == "soic8":
            legs, pitch, reach, leg = 4, 1.27, 1.05, 0.42
        else:
            legs, pitch, reach = GULL_WING_LEGS[kind]
            leg = 0.3
        body_half = half_w - reach
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(look.metal(QRectF(-half_l, -half_w, length, width), LEAD))
        for index in range(legs):
            along = (index - (legs - 1) / 2) * pitch
            for side in (-1.0, 1.0):
                painter.drawRect(QRectF(along - leg / 2, min(side * body_half, side * half_w), leg, reach))
        top = QRectF(-half_l, -body_half, length, 2 * body_half)
        painter.setPen(edge)
        painter.setBrush(look.moulded(top, epoxy))
        painter.drawRect(top)
        look.bevel(painter, top, 0.15, 50)
        if pin_one:
            if kind == "soic8":
                _paint_dimple(painter, QPointF(half_l - 0.75, pin_one * (body_half - 0.7)), 0.32)
            else:
                end, side, radius = gull_wing_dot(body_half)
                _paint_dimple(painter, QPointF(half_l - end, pin_one * (body_half - side)), radius)
        _paint_art_print(painter, part.text, min(TOP_MARKING_MM * 0.8, body_half * 0.5), length * 0.7, ink)
    elif kind == "shield":
        can = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(look.metal(can, _art_colour("shield")))
        painter.drawRect(can)
        look.bevel(painter, can, min(0.35, min(length, width) * 0.05), 70)
        _paint_art_print(
            painter, part.text, min(1.0, width * 0.1), length * 0.8, _art_ink("etch", ART_ETCH_ALPHA)
        )
    elif kind == "ufl":
        _art_box(painter, -half_l, half_l, half_w, _art_colour("package"))
        ring = min(length, width) * 0.38
        painter.setBrush(look.domed(QPointF(0.0, 0.0), ring, _art_colour("brass"), 135))
        painter.drawEllipse(QPointF(0.0, 0.0), ring, ring)
        painter.setBrush(QBrush(_art_colour("mouth")))
        painter.drawEllipse(QPointF(0.0, 0.0), ring * 0.6, ring * 0.6)
        painter.setBrush(QBrush(_art_colour("brass")))
        painter.drawEllipse(QPointF(0.0, 0.0), ring * 0.22, ring * 0.22)
    elif kind == "qfn":
        dot = min(0.35, min(length, width) * 0.1)
        if part.diagonal:
            # A corner along the axis, as the TQFP's: the chip's own (1, 1) corner on +x.
            painter.rotate(-45)
        # The tinned ends of its pads, just showing along each side.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(LEAD))
        count = max(int(length / QFN_PAD_PITCH_MM) - 2, 3)
        for index in range(count):
            along = (index - (count - 1) / 2) * (length - 0.8) / (count - 1)
            for pad in (
                QRectF(along - 0.1, -half_w - 0.12, 0.2, 0.25),
                QRectF(along - 0.1, half_w - 0.13, 0.2, 0.25),
                QRectF(-half_l - 0.12, along - 0.1, 0.25, 0.2),
                QRectF(half_l - 0.13, along - 0.1, 0.25, 0.2),
            ):
                painter.drawRect(pad)
        top = QRectF(-half_l + 0.08, -half_w + 0.08, length - 0.16, width - 0.16)
        painter.setPen(edge)
        painter.setBrush(look.moulded(top, epoxy))
        painter.drawRect(top)
        look.bevel(painter, top, 0.14, 50)
        if part.diagonal:
            _paint_dimple(painter, QPointF(half_l - dot * 2.2, half_w - dot * 2.2), dot)
        elif pin_one:
            _paint_dimple(painter, QPointF(half_l - dot * 2.2, pin_one * (half_w - dot * 2.2)), dot)
        _paint_art_print(painter, part.text, min(0.55, width * 0.12), length * 0.82, ink)
        _paint_silk_corners(painter, half_l, half_w, min(1.0, length * 0.2))
    elif kind == "tqfp32":
        if part.diagonal:
            # A corner along the axis: the chip's own (1, 1) corner, turned onto +x.
            painter.rotate(-45)
        quad = TQFP32_BODY_MM / 2
        offsets = [
            (index - (TQFP32_LEGS_PER_SIDE - 1) / 2) * TQFP32_PITCH_MM
            for index in range(TQFP32_LEGS_PER_SIDE)
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(look.metal(QRectF(-half_l, -half_l, length, length), LEAD))
        for offset in offsets:
            for x0, y0, w, h in (
                (quad, offset - TQFP32_LEG_MM / 2, half_l - quad, TQFP32_LEG_MM),
                (-half_l, offset - TQFP32_LEG_MM / 2, half_l - quad, TQFP32_LEG_MM),
                (offset - TQFP32_LEG_MM / 2, quad, TQFP32_LEG_MM, half_l - quad),
                (offset - TQFP32_LEG_MM / 2, -half_l, TQFP32_LEG_MM, half_l - quad),
            ):
                painter.drawRect(QRectF(x0, y0, w, h))
        top = QRectF(-quad, -quad, 2 * quad, 2 * quad)
        painter.setPen(edge)
        painter.setBrush(look.moulded(top, epoxy))
        painter.drawRect(top)
        look.bevel(painter, top, 0.18, 55)
        # Turned on its corner, that corner is its feature's; square, its pin-1 corner.
        corner = quad - 1.0
        if part.diagonal or pin_one:
            _paint_dimple(painter, QPointF(corner, corner if part.diagonal else pin_one * corner), 0.4)
        _paint_art_print(painter, part.text, 0.62, quad * 1.6, ink)
    elif kind == "rf-module":
        board = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(QBrush(_art_colour("rf-board")))
        painter.drawRect(board)
        look.bevel(painter, board, 0.2, 30)
        can = QRectF(
            -half_l + part.inset, -half_w + part.inset,
            length - part.antenna - part.inset, width - 2 * part.inset,
        )
        steel = _art_colour("shield")
        painter.setPen(QPen(steel.darker(140), 0.08))
        painter.setBrush(look.metal(can, steel))
        painter.drawRoundedRect(can, RF_CAN_CORNER_MM, RF_CAN_CORNER_MM)
        look.bevel(painter, can, 0.3, 90, RF_CAN_CORNER_MM)
        # The antenna: a meander on the bare end, as ``view3d._art_rf_module`` prints it.
        teeth, reach, depth = 5, width * 0.8, part.antenna * 0.55
        near = half_l - part.antenna / 2 - depth / 2
        far = near + depth
        step = reach / (2 * teeth - 1)
        trace = QPen(_art_colour("antenna"), 0.4)
        trace.setCapStyle(Qt.PenCapStyle.SquareCap)
        trace.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        meander = QPainterPath(QPointF(near, -reach / 2))
        for index in range(2 * teeth):
            across = -reach / 2 + index * step
            enter, leave = (near, far) if index % 2 == 0 else (far, near)
            meander.lineTo(enter, across)
            meander.lineTo(leave, across)
            if index < 2 * teeth - 1:
                meander.lineTo(leave, across + step)
        painter.setPen(trace)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(meander)
        painter.setPen(edge)
        # The module's name etched across the can, on its antenna side of the middle, where
        # the maker puts it. Only the name: the certification ids under it are unreadable at
        # any zoom, and not what the builder needs.
        _paint_art_print(
            painter, part.text, min(RF_NAME_MM, can.height() * 0.07), can.height() * 0.86,
            _art_ink("etch", ART_ETCH_ALPHA), QPointF(can.center().x() + can.width() * 0.1, 0.0), 90,
        )
    elif kind == "usb":
        steel = _art_colour("usb")
        # The tabs either side that the shell is soldered down by, then the shell itself.
        tab = min(1.1, length * 0.14)
        painter.setPen(QPen(steel.darker(150), 0.06))
        painter.setBrush(QBrush(steel.darker(112)))
        painter.drawRect(QRectF(-half_l * 0.45 - tab / 2, -half_w, tab, 0.55))
        painter.drawRect(QRectF(-half_l * 0.45 - tab / 2, half_w - 0.55, tab, 0.55))
        shell = QRectF(-half_l, -half_w * 0.92, length, 2 * half_w * 0.92)
        painter.setBrush(look.metal(shell, steel))
        painter.drawRoundedRect(shell, 0.35, 0.35)
        look.bevel(painter, shell, 0.22, 80, 0.35)
        # The seam the shell is folded along, and the dark of the mouth at the board's edge.
        painter.setPen(QPen(steel.darker(135), 0.08))
        painter.drawLine(QPointF(-half_l + 0.6, 0.0), QPointF(half_l - 1.0, 0.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_art_colour("mouth")))
        painter.drawRect(QRectF(half_l - 0.45, -half_w * 0.7, 0.45, 2 * half_w * 0.7))
        painter.setPen(edge)
    elif kind == "button":
        coloured = bool(part.colour)
        frame = QRectF(-half_l, -half_w, length, width)
        if coloured:
            painter.setBrush(look.moulded(frame, QColor(part.colour).darker(113)))
            painter.drawRect(frame)
            look.bevel(painter, frame, 0.15, 40)
        else:
            # A tact switch from above: its dark base, the steel cover over it, and the
            # round stem up through the cover.
            painter.setBrush(QBrush(_art_colour("switch")))
            painter.drawRect(frame)
            cover = frame.adjusted(0.18, 0.18, -0.18, -0.18)
            painter.setBrush(look.metal(cover, _art_colour("frame")))
            painter.drawRect(cover)
            look.bevel(painter, cover, 0.15, 70)
        radius = min(length, width) * 0.3
        stem = QColor(part.colour) if coloured else _art_colour("switch")
        painter.setPen(QPen(stem.darker(160) if coloured else ART_EDGE, 0.07))
        painter.setBrush(look.domed(QPointF(0.0, 0.0), radius, stem, 108 if coloured else 160))
        painter.drawEllipse(QPointF(0.0, 0.0), radius, radius)
        painter.setPen(edge)
    elif kind == "side-button":
        cap = min(0.6, length / 3)
        body = QRectF(-half_l, -half_w, length - cap, width)
        painter.setBrush(look.metal(body, _art_colour("frame")))
        painter.drawRect(body)
        look.bevel(painter, body, 0.12, 50)
        _art_box(painter, half_l - cap, half_l, half_w * 0.4, _art_colour("switch"))
    elif kind == "led":
        lens = QColor(part.colour) if part.colour else _art_colour("lens")
        if abs(length - width) < 0.3:
            _art_box(painter, -half_l, half_l, half_w, _art_colour("package"))
            radius = min(length, width) * 0.36
            painter.setBrush(look.domed(QPointF(0.0, 0.0), radius, lens, 135))
            painter.drawEllipse(QPointF(0.0, 0.0), radius, radius)
        else:
            # An 0603/0805 LED: tinned ends, and its lens between them, glowing at its
            # middle on screen. No cathode mark: the layout does not say which end it is.
            cap = min(0.3, length * 0.2)
            painter.setBrush(look.metal(QRectF(-half_l, -half_w, length, width), LEAD))
            painter.drawRect(QRectF(-half_l, -half_w, length, width))
            body = QRectF(-half_l + cap, -half_w, length - 2 * cap, width)
            if look.lit:
                glow = QRadialGradient(body.center(), max(body.width(), body.height()) * 0.6)
                glow.setColorAt(0.0, lens.lighter(135))
                glow.setColorAt(1.0, lens)
                painter.setBrush(QBrush(glow))
            else:
                painter.setBrush(QBrush(lens))
            painter.drawRect(body)
    elif kind == "crystal":
        base = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(QBrush(_art_colour("ceramic")))
        painter.drawRect(base)
        lid = base.adjusted(0.15, 0.15, -0.15, -0.15)
        painter.setBrush(look.metal(lid, _art_colour("shield")))
        painter.drawRect(lid)
        look.bevel(painter, lid, 0.12, 60)
    elif kind == "sma":
        # A tantalum is the colour it is moulded in, its band a darker shade of it.
        moulding = QColor(part.colour) if part.colour else epoxy
        body = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(look.moulded(body, moulding))
        painter.drawRect(body)
        look.bevel(painter, body, 0.1, 40)
        band = moulding.darker(TANTALUM_BAND_SHADE) if part.colour else _art_colour("band")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(band))
        painter.drawRect(QRectF(half_l - 1.1, -half_w, 0.7, width))
        painter.setPen(edge)
    elif kind == "hole":
        radius = min(length, width) / 2
        ring = part.inset or HOLE_EDGE_MM
        plated = QColor(part.colour) if part.colour else _art_colour("hole-edge")
        painter.setPen(QPen(plated.darker(150), 0.06))
        painter.setBrush(look.domed(QPointF(0.0, 0.0), radius, plated))
        painter.drawEllipse(QPointF(0.0, 0.0), radius, radius)
        painter.setBrush(QBrush(_art_colour("hole")))
        painter.drawEllipse(QPointF(0.0, 0.0), radius - ring, radius - ring)
        painter.setPen(edge)
    elif kind == "plate":
        _art_box(painter, -half_l, half_l, half_w, QColor(part.colour) if part.colour else _art_colour("plate"))
    elif kind == "terminal":
        # From above: the blue block, a slotted screw head per way over its pin, the test
        # slot behind each, and the dark of the wire mouths along the face they open in.
        ways = max(round(width / part.pitch), 1) if part.pitch else 1
        step = width / ways
        mouth_wide = TERMINAL_MOUTH_MM[0]
        block = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(look.moulded(block, _art_colour("terminal")))
        painter.drawRect(block)
        look.bevel(painter, block, 0.2, 40)
        radius = min(TERMINAL_SCREW_MM, step * 0.86) / 2
        for way in range(ways):
            across = (way - (ways - 1) / 2) * step
            painter.setBrush(QBrush(_art_colour("mouth")))
            painter.drawRect(QRectF(half_l - 0.35, across - mouth_wide / 2, 0.35, mouth_wide))
            painter.drawRect(QRectF(-half_l + 0.8, across - mouth_wide / 2, 0.4, mouth_wide))
            head = QPointF(-0.1, across)
            painter.setBrush(look.domed(head, radius, _art_colour("screw"), 130))
            painter.drawEllipse(head, radius, radius)
            painter.save()
            painter.setPen(QPen(_art_colour("mouth"), 0.3))
            painter.drawLine(QPointF(-0.1 - radius * 0.7, across), QPointF(-0.1 + radius * 0.7, across))
            painter.drawLine(QPointF(-0.1, across - radius * 0.7), QPointF(-0.1, across + radius * 0.7))
            painter.restore()
    elif kind == "jst-sh":
        # The natural nylon housing, its mouth at the front and its contacts' tails, tinned,
        # out of the back past the housing.
        _art_legs(
            painter, -half_l - JST_SH_TAILS_MM, -half_l + 0.2,
            [(index - 1.5) * JST_SH_PITCH_MM for index in range(4)], 0.3,
        )
        housing = QColor(part.colour) if part.colour else _art_colour("jst")
        body = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(look.moulded(body, housing))
        painter.drawRect(body)
        look.bevel(painter, body, 0.12, 40)
        _art_box(painter, half_l - 0.45, half_l, half_w * 0.68, _art_colour("mouth"))
    elif kind == "encoder":
        _paint_art_encoder(painter, length, width, look)
    elif kind == "microsd":
        _paint_art_microsd(painter, length, width, look, _dot_side(part))
    elif kind == "camera":
        _paint_art_camera(painter, length, width, look)
    elif kind == "fpc":
        _paint_art_fpc(painter, length, width, look, part.pitch)
    elif kind == "fresnel":
        # The square foot, the dome on it, and the facets a Fresnel lens is moulded in: a
        # hexagon at the top of the dome and the ridges out from its corners.
        lens = _art_colour("fresnel")
        painter.setBrush(QBrush(lens.darker(108)))
        painter.drawRoundedRect(QRectF(-half_l, -half_w, length, width), 0.8, 0.8)
        dome = min(FRESNEL_DOME_MM, length, width) / 2
        painter.setBrush(look.domed(QPointF(0.0, 0.0), dome, lens, 106))
        painter.drawEllipse(QPointF(0.0, 0.0), dome, dome)
        painter.save()
        painter.setPen(QPen(lens.darker(118), 0.12))
        corners = [
            QPointF(dome * 0.42 * math.cos(math.radians(60 * k + 30)),
                    dome * 0.42 * math.sin(math.radians(60 * k + 30)))
            for k in range(6)
        ]
        painter.drawPolygon(QPolygonF(corners))
        for tip in corners:
            painter.drawLine(tip, QPointF(tip.x() / 0.42 * 0.97, tip.y() / 0.42 * 0.97))
        painter.restore()
    elif kind == "oled":
        glass = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(look.moulded(glass, _art_colour("glass")))
        painter.drawRect(glass)
        view_across, view_along = OLED_VIEW_MM
        # The viewing area sits in the glass short of its ledge, at +x.
        middle = -OLED_LEDGE_MM / 2
        _art_box(
            painter, middle - view_along / 2, middle + view_along / 2, view_across / 2,
            _art_colour("oled-view"),
        )
        look.bevel(painter, glass, 0.3, 45)
    elif kind == "pcb-antenna":
        # A meander across the part, its own axis along x: strokes ``pitch`` apart, each
        # running the width of the part and joined at alternate ends.
        trace = QPen(_art_colour("antenna"), PCB_ANTENNA_TRACE_MM)
        trace.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(trace)
        pitch = part.pitch or 1.0
        turns = max(int(length // pitch), 1)
        start = -half_l + (length - turns * pitch) / 2
        reach = half_w - PCB_ANTENNA_TRACE_MM
        for index in range(turns + 1):
            at = start + index * pitch
            painter.drawLine(QPointF(at, -reach), QPointF(at, reach))
            if index < turns:
                end = reach if index % 2 == 0 else -reach
                painter.drawLine(QPointF(at, end), QPointF(at + pitch, end))
        painter.setPen(edge)
    elif kind == "hc49":
        # From above, the can's top: round-ended, its crimped rim a shade darker round it.
        can = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(QBrush(_art_colour("shield").darker(118)))
        painter.drawRoundedRect(can, half_w, half_w)
        rim = min(0.35, half_w * 0.2)
        top = can.adjusted(rim, rim, -rim, -rim)
        painter.setBrush(look.metal(top, _art_colour("shield")))
        painter.drawRoundedRect(top, half_w - rim, half_w - rim)
    elif kind == "flex":
        _art_box(painter, -half_l, half_l, half_w, _art_colour("flex"))
        if part.text:
            # A camera's flex: bare polyimide, the copper running along it, and its printing.
            painter.save()
            painter.setPen(QPen(_art_colour("flex").darker(125), 0.12))
            for share in (-0.6, -0.3, 0.0, 0.3, 0.6):
                painter.drawLine(QPointF(-half_l, half_w * share), QPointF(half_l, half_w * share))
            painter.restore()
            _paint_art_print(painter, part.text, min(0.9, width * 0.16), length * 0.9, _art_ink("ink", ART_PRINT_ALPHA))
        else:
            _art_box(painter, -half_l, half_l, half_w * 0.8, _art_colour("flex-stiffener"))
    elif kind == "trimmer":
        body = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(look.moulded(body, _art_colour("trimmer-base")))
        painter.drawRect(body)
        look.bevel(painter, body, 0.12, 40)
        radius = min(length, width) * 0.4
        painter.setBrush(look.domed(QPointF(0.0, 0.0), radius, _art_colour("rotor"), 130))
        painter.drawEllipse(QPointF(0.0, 0.0), radius, radius)
        _art_box(painter, -radius * 0.7, radius * 0.7, radius * 0.14, _art_colour("slot"))
    elif kind in ("chip-r", "chip-c"):
        # Tinned ends and the body between: a resistor's black, a capacitor's tan ceramic.
        # No value printed on it: the layout does not say it, and a guessed one would.
        cap = min(0.4, length * 0.2)
        ends = QRectF(-half_l, -half_w, length, width)
        painter.setBrush(look.metal(ends, LEAD))
        painter.drawRect(ends)
        body = QRectF(-half_l + cap, -half_w, length - 2 * cap, width)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(look.moulded(body, _art_colour("resistor" if kind == "chip-r" else "mlcc")))
        painter.drawRect(body)
        painter.setPen(edge)
    elif kind == "pads":
        # A header nobody fitted (a Nano's ICSP): its plated holes, open, pin 1 square.
        along_count = max(round(length / 2.54), 1)
        across_count = max(round(width / 2.54), 1)
        for a in range(along_count):
            for b in range(across_count):
                centre = QPointF((a - (along_count - 1) / 2) * 2.54, (b - (across_count - 1) / 2) * 2.54)
                _paint_plated_pad(
                    painter, centre, 0.85, _art_colour("tin"), square=a == 0 and b == 0, pin=False,
                    lit=look.lit,
                )
        painter.setPen(edge)


#: An illuminated encoder's shaft, end on: the knurl's teeth round it, and the three LEDs'
#: colours it carries round its edge, faint, unlit -- clear plastic with red, green and blue
#: under it, not a lamp that is on.
ENCODER_KNURL_TEETH = 24
ENCODER_TINTS = ("#ff7c7c", "#7cf09a", "#7ca6ff")
ENCODER_TINT_SHARE = 0.3


def _paint_art_encoder(painter: QPainter, length: float, width: float, look: _ArtLook) -> None:
    """A 12 mm rotary encoder from above (``moduleart.ENCODER_MM``), its pin rows at the
    ends of ``length``: its moulded base where it shows at the pin rows, the steel bracket
    over it with a leg out of each side, the M9 bushing's thread seen end on as rings, and
    the clear knurled shaft its LEDs light."""
    half_l, half_w = length / 2, width / 2
    edge = QPen(ART_EDGE, 0.05)
    steel = _art_colour("shield")
    leg_out, leg_wide = ENCODER_MM["leg-out"], ENCODER_MM["leg-wide"]
    painter.setPen(edge)
    legs = QRectF(-leg_wide / 2, -half_w - leg_out, leg_wide, width + 2 * leg_out)
    painter.setBrush(look.metal(legs, steel.darker(112)))
    painter.drawRect(legs)
    base = QRectF(-half_l, -half_w, length, width)
    painter.setBrush(look.moulded(base, _art_colour("epoxy")))
    painter.drawRoundedRect(base, 0.8, 0.8)
    along = min(ENCODER_MM["bracket"], length) / 2
    bracket = QRectF(-along, -half_w, 2 * along, width)
    painter.setBrush(look.metal(bracket, steel))
    painter.drawRect(bracket)
    look.bevel(painter, bracket, 0.15, 45)

    centre = QPointF(0.0, 0.0)
    bushing = min(ENCODER_MM["bushing"], length, width) / 2
    shaft = min(ENCODER_MM["shaft"] / 2, bushing * 0.8)
    painter.setBrush(look.domed(centre, bushing, steel.darker(106), 118))
    painter.drawEllipse(centre, bushing, bushing)
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(steel.darker(140), 0.06))
    ring = bushing - 0.4
    while ring > shaft + 0.25:
        painter.drawEllipse(centre, ring, ring)
        ring -= 0.5
    painter.restore()

    clear = ART_COLOURS["shaft"]
    if look.lit:
        tint = QConicalGradient(centre, 90.0)
        for index, hue in enumerate((*ENCODER_TINTS, ENCODER_TINTS[0])):
            tint.setColorAt(index / len(ENCODER_TINTS), _mixed(clear, hue, ENCODER_TINT_SHARE))
        painter.setBrush(QBrush(tint))
    else:
        painter.setBrush(QBrush(QColor(clear)))
    painter.drawEllipse(centre, shaft, shaft)
    if look.lit:
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        frost = QRadialGradient(QPointF(-shaft * 0.3, -shaft * 0.3), shaft * 1.2)
        frost.setColorAt(0.0, QColor(255, 255, 255, 150))
        frost.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(frost))
        painter.drawEllipse(centre, shaft, shaft)
        painter.restore()
    painter.save()
    painter.setPen(QPen(QColor(clear).darker(135), 0.08))
    for tooth in range(ENCODER_KNURL_TEETH):
        angle = 2 * math.pi * tooth / ENCODER_KNURL_TEETH
        dx, dy = math.cos(angle), math.sin(angle)
        painter.drawLine(QPointF(shaft * 0.8 * dx, shaft * 0.8 * dy), QPointF(shaft * dx, shaft * dy))
    painter.restore()


def _paint_art_microsd(
    painter: QPainter, length: float, width: float, look: _ArtLook, side: float
) -> None:
    """A push-push micro SD socket from above, its mouth at +x (``moduleart.MICROSD_TAILS``,
    ``MICROSD_LATCH_MM``): the contacts' tails out of the back, the steel shell with the two
    ribs pressed along it, the latch's window by the mouth on ``side``, and the dark of the
    mouth itself."""
    half_l, half_w = length / 2, width / 2
    count, pitch, reach, offset = MICROSD_TAILS
    middle = -side * offset if side else 0.0
    _art_legs(
        painter, -half_l - reach, -half_l + 0.2,
        [middle + (index - (count - 1) / 2) * pitch for index in range(count)], 0.45,
    )
    painter.setPen(QPen(ART_EDGE, 0.05))
    steel = _art_colour("shield")
    shell = QRectF(-half_l, -half_w, length, width)
    painter.setBrush(look.metal(shell, steel))
    painter.drawRect(shell)
    look.bevel(painter, shell, 0.2, 55)
    painter.save()
    painter.setPen(QPen(steel.darker(128), 0.12))
    for share in (-0.18, 0.18):
        painter.drawLine(QPointF(-half_l * 0.7, half_w * share), QPointF(half_l * 0.45, half_w * share))
    painter.restore()
    start, long, wide = MICROSD_LATCH_MM
    if side:
        window = QRectF(half_l - start - long, 0.0, long, wide)
        window.moveTop(side * (half_w - 0.15 - wide / 2) - wide / 2)
        painter.setBrush(QBrush(_art_colour("mouth")))
        painter.drawRect(window)
        painter.save()
        painter.setPen(QPen(steel.lighter(108), 0.25))
        painter.drawLine(
            QPointF(window.left() + 0.4, window.center().y()),
            QPointF(window.right() - 0.5, window.center().y() + side * wide * 0.25),
        )
        painter.restore()
    _art_box(painter, half_l - 0.25, half_l, half_w * 0.9, _art_colour("mouth"))


def _paint_art_camera(painter: QPainter, length: float, width: float, look: _ArtLook) -> None:
    """A camera module from above (``moduleart.CAMERA_MM``): the black holder, the lens
    barrel standing out of it with its thread, and the glass, catching the light."""
    half_l, half_w = length / 2, width / 2
    holder = QRectF(-half_l, -half_w, length, width)
    painter.setPen(QPen(ART_EDGE, 0.05))
    painter.setBrush(look.moulded(holder, _art_colour("camera")))
    painter.drawRoundedRect(holder, 0.4, 0.4)
    look.bevel(painter, holder, 0.18, 40, 0.4)
    centre = QPointF(0.0, 0.0)
    barrel = min(CAMERA_MM["barrel"], length, width) / 2
    painter.setBrush(look.domed(centre, barrel, _art_colour("barrel"), 140))
    painter.drawEllipse(centre, barrel, barrel)
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_art_colour("barrel").lighter(135), 0.08))
    for share in (0.82, 0.66):
        painter.drawEllipse(centre, barrel * share, barrel * share)
    painter.restore()
    glass = min(CAMERA_MM["glass"], 2 * barrel) / 2
    tint = _art_colour("lens-glass")
    if look.lit:
        shine = QRadialGradient(QPointF(-glass * 0.35, -glass * 0.35), glass * 1.3)
        shine.setColorAt(0.0, tint.lighter(260))
        shine.setColorAt(0.45, tint)
        shine.setColorAt(1.0, tint.darker(160))
        painter.setBrush(QBrush(shine))
    else:
        painter.setBrush(QBrush(tint))
    painter.drawEllipse(centre, glass, glass)


def _paint_art_fpc(
    painter: QPainter, length: float, width: float, look: _ArtLook, pitch: float
) -> None:
    """A flip-lock FPC connector from above, its actuator at +x (``moduleart.FPC_MM``): the
    contacts' tails out of the back, the cream housing with its contacts' teeth showing at
    the actuator, and the dark actuator itself."""
    half_l, half_w = length / 2, width / 2
    step = pitch or 0.5
    count = max(int((width - 4.0) / step), 1)
    at = [(index - (count - 1) / 2) * step for index in range(count)]
    _art_legs(painter, -half_l - FPC_MM["tails"], -half_l + 0.2, at, step * 0.5)
    painter.setPen(QPen(ART_EDGE, 0.05))
    body = QRectF(-half_l, -half_w, length, width)
    painter.setBrush(look.moulded(body, _art_colour("fpc")))
    painter.drawRect(body)
    look.bevel(painter, body, 0.15, 35)
    actuator = min(FPC_MM["actuator"], length * 0.5)
    face = half_l - actuator
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(_art_colour("fpc").darker(112)))
    for across in at:
        painter.drawRect(QRectF(face - 0.9, across - step * 0.2, 0.9, step * 0.4))
    painter.restore()
    bar = QRectF(face, -half_w + 0.6, actuator, width - 1.2)
    painter.setBrush(look.moulded(bar, _art_colour("actuator")))
    painter.drawRect(bar)


def _paint_silk_corners(painter: QPainter, half_l: float, half_w: float, arm: float) -> None:
    """The silkscreen corners a board prints round a chip, just outside its pads."""
    pen = QPen(QColor(BODY_STYLES["module-board"].accent), SILK_LINE_MM)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.save()
    painter.setPen(pen)
    x, y = half_l + SILK_GAP_MM, half_w + SILK_GAP_MM
    for sx in (-1, 1):
        for sy in (-1, 1):
            painter.drawLine(QPointF(sx * x, sy * y), QPointF(sx * (x - arm), sy * y))
            painter.drawLine(QPointF(sx * x, sy * y), QPointF(sx * x, sy * (y - arm)))
    painter.restore()


def _paint_plated_pad(
    painter: QPainter,
    centre: QPointF,
    radius: float,
    plating: QColor,
    *,
    square: bool,
    pin: bool,
    lit: bool,
    selected: bool = False,
) -> None:
    """A plated hole in a module's board, from above: its ring (square for pin 1), and the
    header pin up through it in its cone of solder -- or, with no pin, the open bore."""
    if selected:
        painter.setPen(QPen(SELECTED, 0.16))
    else:
        painter.setPen(QPen(plating.darker(170), 0.07))
    painter.setBrush(_ArtLook(lit).domed(centre, radius, plating, 122))
    ring = QRectF(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius)
    if square:
        painter.drawRect(ring)
    else:
        painter.drawEllipse(ring)
    painter.setPen(Qt.PenStyle.NoPen)
    if not pin:
        painter.setBrush(QBrush(_art_colour("hole")))
        painter.drawEllipse(centre, radius * 0.5, radius * 0.5)
        return
    painter.setBrush(QBrush(_art_colour("solder")))
    painter.drawEllipse(centre, radius * 0.72, radius * 0.72)
    tip = MODULE_PIN_TIP_MM / 2
    painter.setPen(QPen(_art_colour("solder").darker(140), 0.05))
    painter.setBrush(QBrush(_art_colour("pin-tip")))
    painter.drawRect(QRectF(centre.x() - tip, centre.y() - tip, 2 * tip, 2 * tip))


def _paint_module_board(
    painter: QPainter,
    footprint: Footprint,
    path: QPainterPath,
    fill: QColor,
    selected: bool,
    pitch: float,
    art: Sequence[PlacedArt],
    cache: ArtCache | None,
) -> None:
    """A recognised module from above: its board, what stands on it and its header pins in
    their plated holes, then its outline. On screen the first three come out of ``cache``
    (``ArtCache``), painted once for the zoom and turn they are seen at; the outline, in
    the selection's colour when selected, is drawn over them every time."""
    if cache is None or not cache.paint(painter, footprint, path, fill, selected, pitch, art):
        _paint_module_board_now(painter, footprint, path, fill, selected, pitch, art)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(SELECTED if selected else fill.darker(190), 0.2 if selected else 0.1))
    painter.drawPath(path)


def _paint_module_board_now(
    painter: QPainter,
    footprint: Footprint,
    path: QPainterPath,
    fill: QColor,
    selected: bool,
    pitch: float,
    art: Sequence[PlacedArt],
) -> None:
    lit = not _on_paper(painter)
    if lit:
        _paint_contact_shadow(painter, path)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(fill))
    painter.drawPath(path)
    if lit:
        _paint_body_light(painter, path)
        # The board's edge: the solder mask catching the light along the top left, the cut
        # FR4 a shade darker along the bottom right.
        _paint_edge_light(painter, path.boundingRect(), MODULE_EDGE_LIGHT_MM, MODULE_EDGE_LIGHT_ALPHA)
    painter.save()
    # Inside the board, whatever the art says: what stands on a module never overhangs it
    # here, as ``fit_module_art`` already keeps it from doing in the layout.
    painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
    _paint_module_art(painter, art)
    painter.restore()
    plating = QColor(module_pad_plating(fill.name()))
    for pin in footprint.pins:
        _paint_plated_pad(
            painter, QPointF(pin.d_col * pitch, pin.d_row * pitch), MODULE_PAD_MM, plating,
            square=pin.number == "1", pin=True, lit=lit, selected=selected,
        )


class ArtCache:
    """A recognised module's board, art and pads, rasterised at the zoom and turn they were
    last painted at, so a repaint is one image drawn rather than a few hundred gradients.

    One image per part: kept while the view's scale and rotation, the part's colour and its
    selection are what they were, and the quarter pixel it lands on. Panning keeps it.
    A zoom in progress passes through a new scale every frame, and filling an image per part
    per frame cost more than painting the parts: so a new scale is first served from the
    image already held, scaled (``ART_CACHE_STRETCH``), and the item asks its scene to paint
    it again once the zoom has settled (``stale``), when the second sight of that scale
    fills the image afresh. With nothing held, the part is painted directly. Never on paper,
    nor on any device that is not pixels -- the 1:1 PDF and an SVG are drawn as they always
    were, in vectors -- nor past ``ART_CACHE_MAX_PX``, where it would cost more memory than
    it saves time."""

    __slots__ = ("_image", "_key", "_look", "_seen", "_to_local", "_turn", "stale")

    def __init__(self) -> None:
        self._key: tuple[object, ...] | None = None
        self._image: QImage | None = None
        #: The key without the view's transform: what the image shows, at any zoom.
        self._look: tuple[object, ...] | None = None
        #: The view's rotation and mirroring the image was drawn under, scale divided out.
        self._turn: tuple[float, ...] | None = None
        #: From the image's own (logical) pixels back to the part's frame.
        self._to_local = QTransform()
        #: The last key served stale, waiting to be asked for a second time.
        self._seen: tuple[object, ...] | None = None
        #: The last paint was a stretched image: the scene should paint it again soon.
        self.stale = False

    def paint(
        self,
        painter: QPainter,
        footprint: Footprint,
        path: QPainterPath,
        fill: QColor,
        selected: bool,
        pitch: float,
        art: Sequence[PlacedArt],
    ) -> bool:
        """Draw from the cache, filling it first if it is stale; False when this painter is
        not one the cache serves, and the caller paints directly."""
        self.stale = False
        engine = painter.paintEngine()
        if engine is None or engine.type() != QPaintEngine.Type.Raster or _on_paper(painter):
            return False
        # The device's own pixels, asked of the painter rather than worked out: whether the
        # painter's transform already holds the device's pixel ratio depends on how it was
        # opened -- a window grabbed at a 125 % scale had it, and multiplying by the ratio
        # again drew the art a quarter too big and off its board. ``base`` is what is left
        # between the painter's own units and the device's once its transform is reset: the
        # ratio, and for a view inside a window the view's place in it, since the window
        # paints every widget into one image. The image is put back through it, so it lands
        # one image pixel to one device pixel and at the pixel it was measured at -- drawn
        # at the measured pixel over again, the place was counted twice and the art left the
        # view on any screen once the view was not in the window's top-left corner.
        to_device = painter.deviceTransform()
        painter.save()
        painter.resetTransform()
        base = painter.deviceTransform()
        painter.restore()
        ratio = abs(base.m11()) or 1.0
        from_device = base.inverted()[0]
        margin = ART_CACHE_MARGIN_MM
        area = to_device.mapRect(path.boundingRect().adjusted(-margin, -margin, margin, margin))
        width, height = math.ceil(area.width()) + 2, math.ceil(area.height()) + 2
        if width * height > ART_CACHE_MAX_PX:
            return False
        left, top = math.floor(area.left()), math.floor(area.top())
        phase_x = round((area.left() - left) * ART_CACHE_PHASES) / ART_CACHE_PHASES
        phase_y = round((area.top() - top) * ART_CACHE_PHASES) / ART_CACHE_PHASES
        # The selection's colour too: the pads take it, and a theme may change it.
        look = (
            fill.rgba(), SELECTED.rgba() if selected else 0, pitch, id(footprint), id(art),
            int(painter.renderHints().value),
        )
        scale = math.sqrt(abs(to_device.determinant())) or 1.0
        turn = tuple(round(m / scale, 3) for m in (to_device.m11(), to_device.m12(), to_device.m21(), to_device.m22()))
        key = (
            round(to_device.m11(), 6), round(to_device.m12(), 6),
            round(to_device.m21(), 6), round(to_device.m22(), 6),
            phase_x, phase_y, width, height, ratio, *look,
        )
        if key == self._key and self._image is not None:
            painter.save()
            painter.resetTransform()
            painter.drawImage(from_device.map(QPointF(left, top)), self._image)
            painter.restore()
            return True
        if key != self._seen:
            self._seen = key
            if self._image is None or look != self._look or turn != self._turn:
                return False
            held = math.sqrt(abs(self._to_local.determinant())) * ratio
            if not 1 / ART_CACHE_STRETCH <= held * scale <= ART_CACHE_STRETCH:
                return False
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setTransform(
                QTransform.fromScale(ratio, ratio) * self._to_local * painter.transform()
            )
            painter.drawImage(QPointF(0, 0), self._image)
            painter.restore()
            self.stale = True
            return True
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        inner = QPainter(image)
        inner.setRenderHints(painter.renderHints())
        to_image = to_device * QTransform.fromTranslate(phase_x - area.left(), phase_y - area.top())
        inner.setTransform(to_image)
        _paint_module_board_now(inner, footprint, path, fill, selected, pitch, art)
        inner.end()
        image.setDevicePixelRatio(ratio)
        self._key, self._image, self._look, self._turn = key, image, look, turn
        self._to_local = to_image.inverted()[0]
        painter.save()
        painter.resetTransform()
        painter.drawImage(from_device.map(QPointF(left, top)), self._image)
        painter.restore()
        return True


def _paint_wire_entries(
    painter: QPainter, footprint: Footprint, rect: QRectF, pitch: float
) -> None:
    """A dark opening per way on the face the wires go in by (``footprints.wire_entry``).

    The screw heads say where a terminal is; only these say which way round it is, and a
    terminal soldered with its mouth against its neighbour looks exactly like one that can
    be wired until somebody tries. Drawn in the part's own frame, like every other mark
    here, so the item's transform turns it with the part.
    """
    direction = wire_entry(footprint)
    if direction is None:
        return
    dx, dy = direction
    width = 0.6 * pitch
    depth = min(0.9, 0.25 * min(rect.width(), rect.height()))
    painter.setPen(Qt.PenStyle.NoPen)
    # Alpha given explicitly: an 8-digit Qt colour string is #AARRGGBB, not #RRGGBBAA.
    painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
    for pin in footprint.pins:
        x, y = pin.d_col * pitch, pin.d_row * pitch
        if dy > 0:
            opening = QRectF(x - width / 2, rect.bottom() - depth, width, depth)
        elif dy < 0:
            opening = QRectF(x - width / 2, rect.top(), width, depth)
        elif dx > 0:
            opening = QRectF(rect.right() - depth, y - width / 2, depth, width)
        else:
            opening = QRectF(rect.left(), y - width / 2, depth, width)
        painter.drawRect(opening)


#: A female header's mouth, from above: the square a pin goes into.
SOCKET_MOUTH_MM = 1.0
#: A header's pin, square, as stamped.
HEADER_PIN_MM = 0.64


def _paint_socket_mouths(painter: QPainter, footprint: Footprint, pitch: float, accent: QColor) -> None:
    """A female header from above: a dark mouth over each pin, the contact a glint of
    gold down in it. A plain black strip read as a header with its pins cut off."""
    painter.setPen(QPen(QColor(255, 255, 255, 0x30), 0.08))
    painter.setBrush(QBrush(QColor(0, 0, 0, 210)))
    mouth = SOCKET_MOUTH_MM
    for pin in footprint.pins:
        x, y = pin.d_col * pitch, pin.d_row * pitch
        painter.drawRect(QRectF(x - mouth / 2, y - mouth / 2, mouth, mouth))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(accent.darker(170)))
    glint = mouth * 0.34
    for pin in footprint.pins:
        x, y = pin.d_col * pitch, pin.d_row * pitch
        painter.drawRect(QRectF(x - glint / 2, y - glint / 2, glint, glint))


def _paint_right_angle_pins(
    painter: QPainter,
    footprint: Footprint,
    angle: RightAngle,
    pitch: float,
    accent: QColor,
) -> None:
    """A right-angle part's gold, under its moulding: each leg from its hole over to the
    moulding's near face, and a header's pins on from the far face to their tips."""
    painter.setPen(QPen(QColor(0, 0, 0, 0x60), 0.1))
    painter.setBrush(QBrush(accent))
    half = HEADER_PIN_MM / 2
    for pin in footprint.pins:
        x, y = pin.d_col * pitch, pin.d_row * pitch
        painter.drawRect(QRectF(x - half, y - half, HEADER_PIN_MM, angle.near - y + half))
    if angle.socket:
        return
    for x in sorted({pin.d_col * pitch for pin in footprint.pins}):
        painter.drawRect(QRectF(x - half, angle.far - half, HEADER_PIN_MM, angle.reach - angle.far + half))


def _paint_pin_marks(
    painter: QPainter,
    footprint: Footprint,
    pitch: float,
    accent: QColor,
    square: bool,
) -> None:
    """A contact per pin: square for a header's pins, round for a terminal's screw heads."""
    painter.setPen(QPen(QColor(0, 0, 0, 0x60), 0.1))  # Not "#00000060": Qt reads that as #AARRGGBB
    painter.setBrush(QBrush(accent))
    size = 0.62
    for pin in footprint.pins:
        centre = QPointF(pin.d_col * pitch, pin.d_row * pitch)
        if square:
            painter.drawRect(QRectF(centre.x() - size / 2, centre.y() - size / 2, size, size))
        else:
            painter.drawEllipse(centre, size * 0.85, size * 0.85)


# ------------------------------------------------------------------ component item


class ComponentItem(QGraphicsItem):
    """A placed part. Movable (unless locked), and snapped to the hole grid while
    dragging.

    Dragging never mutates ``self.comp`` -- it is a frozen snapshot from the document
    the scene was last built from. ``itemChange`` only tracks the SNAPPED HOLE the item
    is currently hovering over (``pending_anchor``); the scene compares that against
    ``comp.anchor`` on release to decide whether (and where) to dispatch
    ``component.move``. If the bus refuses the move, the next rebuild redraws this item
    back at ``comp.anchor`` -- there is no separate "snap back" code path, just the one
    source of truth.
    """

    def __init__(
        self,
        comp: ComponentInstance,
        fp: Footprint,
        board: Board,
        side: BoardSide,
        show_pin_names: bool = True,
        pin_names: tuple[PinLabel, ...] = (),
        names_left_off: tuple[tuple[str, str], ...] = (),
        lead_colours: dict[str, QColor] | None = None,
        lead_wires: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self.comp = comp
        self.fp = fp
        self.board = board
        self.side = side
        #: Pin number -> the colour of the wire leaving that pad, for a part off the board:
        #: its net's, by the cut list's convention (``insulation_color``).
        self.lead_colours = lead_colours or {}
        #: The thing at the far end of the wires is drawn beside the board
        #: (``offboard.OffBoardItem``), so the wires carry on to it rather than fading out.
        self.leads_carry_on = False
        #: Print the part's pin names beside its pins (View > Show Pin Names).
        self.show_pin_names = show_pin_names
        #: Print the part's reference above it. Off only in a board PICTURE
        #: (``boardpreview``), where a label held at a pixel size is most of a thumbnail.
        self.show_reference = True
        #: Where they go, as the scene laid them out against the rest of the board.
        self.pin_names = pin_names
        self.pending_anchor: HoleCoord = comp.anchor
        self.has_error = False
        #: Dragged to where it cannot land (``BoardScene.report_drag``). Only ever true
        #: during a drag: a rebuild makes a fresh item.
        self.drag_blocked = False
        # Locked components stay draggable on purpose: the bus (not the item flags) is
        # what refuses the move ("component-locked"), and that refusal has to be
        # reachable and its message surfaced, rather than the UI silently pre-empting
        # the attempt -- see the module docstring and MainWindow.on_move_committed.
        flags = (
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setFlags(flags)
        self.setZValue(10)
        #: Under the pointer, with no tool armed: outlined, and the move cursor if it can
        #: move (``_follow_the_pointer``). Nothing said a part could be picked up until it
        #: was, which is how the board read as a picture rather than a thing to arrange.
        self.hovered = False
        self.setAcceptHoverEvents(True)
        lock_note = f"  [{t('locked')}]" if comp.locked else ""
        where = format_hole(comp.anchor, board)
        if comp.rotation:
            where += f"  {comp.rotation}°"
        tip = f"{comp.ref}  {comp.value}\n{footprint_label(fp.name)}{lock_note}\n{where}"
        if names_left_off and show_pin_names:
            # Printed nowhere on the board for want of room, so said here instead.
            pins = ", ".join(f"{number} {name}" for number, name in names_left_off)
            tip += f"\n{t('No room to print:')} {pins}"
        if fp.body.archetype == "flying-leads":
            tip += "".join(f"\n{line}" for line in self._wire_lines(lead_wires or {}))
        if comp.note:
            # The builder's own words (#10), last and set apart by a blank line.
            note = comp.note
            if len(note) > NOTE_TOOLTIP_CHARS:
                note = note[: NOTE_TOOLTIP_CHARS - 1].rstrip() + "…"
            tip += f"\n\n{note}"
        self.setToolTip(tip)
        #: What stands on a module ``moduleart`` recognises, laid out once: the part is a
        #: frozen snapshot and the item is rebuilt with the document.
        self.art = fit_module_art(fp, comp, board.pitch, names_shown=show_pin_names)
        self.standing = fit_standing_board(fp, comp, board.pitch)
        #: Its own board's colour, when that is not the module style's (a Pico is green).
        self.board_colour = board_colour_for(fp, comp, board.pitch)
        #: The module's board and art as last painted (``ArtCache``).
        self.art_cache = ArtCache()
        self._names_rect = self._pin_names_rect()
        self._leads_rect = self._flying_leads_rect()
        #: What a click on this part is (:meth:`shape`), worked out on first ask: the item is
        #: rebuilt with the document and with the side, so it never goes stale.
        self._hit_shape: QPainterPath | None = None
        #: The same with the printed reference taken in, for the zoom it was worked out at:
        #: the label holds a pixel size, so its share of the scene changes with every zoom.
        self._hit_with_label: tuple[tuple[float, str, float, float, float], QPainterPath] | None = None
        self._sync_position()

    def _sync_position(self) -> None:
        self.setPos(hole_to_screen(self.comp.anchor, self.board, self.side))

    def set_error(self, has_error: bool) -> None:
        if has_error != self.has_error:
            self.has_error = has_error
            self.update()

    def _local_body_rect(self) -> QRectF:
        """The real body (``bodies.placement_for``), in item coordinates -- turned and
        mirrored with the part, so the reference above it stays above the body whichever
        way the part is placed."""
        placement = placement_for(self.fp, self.board.pitch)
        half_x, half_y = placement.size_x / 2, placement.size_y / 2
        corners = [
            _local_offset_mm(placement.centre_x + sx * half_x, placement.centre_y + sy * half_y,
                             self.comp, self.side)
            for sx, sy in ((-1, -1), (1, 1))
        ]
        xs = [x for x, _ in corners]
        ys = [y for _, y in corners]
        return QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))

    def _local_outline(self) -> QPolygonF:
        poly = QPolygonF()
        for pt in self.fp.body_outline:
            dx, dy = _local_offset(pt.x, pt.y, self.comp, self.side)
            poly.append(QPointF(dx, dy))
        return poly

    def _pin_names_rect(self) -> QRectF:
        """What the printed pin names cover, in item coordinates -- they run past the
        body, and a repaint that does not reach them leaves them smeared behind a drag."""
        rect = QRectF()
        for label in self.pin_name_rects():
            rect = rect.united(label)
        return rect

    def pin_name_rects(self) -> list[QRectF]:
        """Each printed pin name's tag, in item coordinates: one rectangle a name."""
        if not self.show_pin_names or not self.faces_the_viewer():
            return []
        half = PIN_NAME_TAG_HEIGHT_MM / 2
        rects = []
        for label in self.pin_names:
            rect = QRectF()
            reach = label.start + label.room + PIN_NAME_TAG_PAD_MM
            for along in (label.start - PIN_NAME_TAG_PAD_MM, reach):
                x, y = _local_offset_mm(
                    label.x + label.dx * along, label.y + label.dy * along, self.comp, self.side
                )
                rect = rect.united(QRectF(x - half, y - half, 2 * half, 2 * half))
            rects.append(rect)
        return rects

    def pin_name_ink_rects(self) -> list[QRectF]:
        """Each printed pin name's tag as it is DRAWN, in item coordinates: from where the
        name starts to where its text ends, not over all the room it may take
        (``pin_name_rects``). What a reference must not be printed over."""
        if not self.show_pin_names or not self.faces_the_viewer():
            return []
        half = PIN_NAME_TAG_HEIGHT_MM / 2
        rects = []
        for label in self.pin_names:
            width = physical_label_width_mm(
                label.name, PIN_NAME_HEIGHT_MM, label.room, bold=False
            )
            rect = QRectF()
            for along in (
                label.start - PIN_NAME_TAG_PAD_MM,
                label.start + width + PIN_NAME_TAG_PAD_MM,
            ):
                x, y = _local_offset_mm(
                    label.x + label.dx * along, label.y + label.dy * along, self.comp, self.side
                )
                rect = rect.united(QRectF(x - half, y - half, 2 * half, 2 * half))
            rects.append(rect)
        return rects

    def _flying_lead_routes(self) -> list[tuple[str, list[QPointF]]]:
        """Each wire of a part off the board, pad to past the edge, in item coordinates.

        ``geometry.flying_lead_routes`` is the one answer to where they run -- the edge the
        guide's step names, the lanes a row pointing at that edge is fanned into -- and the
        3D view draws the same routes. The direction is the BOARD's, not the part's: a row
        of pads turned end for end sends its wires to the same edge. Only on the component
        face, which is where the wires are.
        """
        if self.fp.body.archetype != "flying-leads" or self.side != "top":
            return []
        origin = hole_to_screen(self.comp.anchor, self.board, self.side)
        return [
            (number, [QPointF(p.x - origin.x(), p.y - origin.y()) for p in points])
            for number, points in flying_lead_routes(
                self.comp, self.fp, self.board, FLYING_LEAD_PAST_EDGE_MM
            )
        ]

    def _wire_lines(self, wires: dict[str, tuple[str, str]]) -> list[str]:
        """One line per wire of a part off the board, for its tooltip: which pad, which lead
        of the part at the other end, its net and its colour -- in the words and the order the
        guide's step uses, so hovering over the board and reading the step say one thing."""
        say = phrasebook(guide_language(current_language()))
        lines = []
        for pin, at in all_pin_holes(self.comp, self.fp):
            far_end = lead_end(self.comp.ref, pin.number, pin_name_of(self.comp, pin), say)
            line = f"{format_hole(at, self.board)} → {far_end}"
            wire = wires.get(pin.number)
            if wire is not None:
                line += f" · {wire[0]} · {say(wire[1])}"
            lines.append(line)
        return lines

    def _lead_markers(self) -> list[tuple[str, QPointF, bool, QPointF]]:
        """Each wire's marker: its text, where it is centred in item coordinates -- the same
        ``FLYING_LEAD_MARKER_MM`` past the edge the 3D view puts it -- whether the wire runs
        across the screen there (so the text does) or up and down it, and the unit direction
        it runs off the board in."""
        names = {pin.number: pin_name_of(self.comp, pin) for pin in self.fp.pins}
        markers = []
        for number, points in self._flying_lead_routes():
            edge, end = points[-2], points[-1]
            dx, dy = end.x() - edge.x(), end.y() - edge.y()
            run = math.hypot(dx, dy) or 1.0
            centre = QPointF(
                edge.x() + dx / run * FLYING_LEAD_MARKER_MM,
                edge.y() + dy / run * FLYING_LEAD_MARKER_MM,
            )
            text = lead_marker(self.comp.ref, number, names.get(number))
            markers.append((text, centre, abs(dx) >= abs(dy), QPointF(dx / run, dy / run)))
        return markers

    def _flying_leads_rect(self) -> QRectF:
        rect = QRectF()
        half = FLYING_LEAD_JACKET_MM
        for _number, points in self._flying_lead_routes():
            for point in points:
                rect = rect.united(QRectF(point.x() - half, point.y() - half, 2 * half, 2 * half))
        # The markers are held at a screen size, so they are largest in millimetres at the
        # furthest zoom they are drawn at.
        metrics = QFontMetricsF(label_font(FLYING_LEAD_MARKER_PX))
        for text, centre, _across, _direction in self._lead_markers():
            # Half the marker, and as many whole markers as it may step out by.
            length = (metrics.horizontalAdvance(text) + 10) / FLYING_LEAD_MARKER_MIN_SCALE
            reach = length * (FLYING_LEAD_MARKER_STEPS + 0.5)
            rect = rect.united(
                QRectF(centre.x() - reach, centre.y() - reach, 2 * reach, 2 * reach)
            )
        return rect

    def _paint_lead_markers(self, painter: QPainter) -> None:
        """A sleeve on each wire with where it goes written on it, as a harness is labelled.

        Turned to run along its wire, so a row of wires a pitch apart has room for one each.
        Held at a screen size like the references, and left off a board picture, where a
        label the size of a word is most of a thumbnail.

        Wires laid in lanes are closer than a pitch, and a marker held at a screen size is
        wider than the gap at an ordinary zoom: one that would land on the marker beside it
        steps out along its own wire instead, a marker's length at a time, so each is still
        on the wire it names.
        """
        scale = abs(painter.transform().m11())
        if not self.show_reference or scale < FLYING_LEAD_MARKER_MIN_SCALE:
            return
        font = label_font(FLYING_LEAD_MARKER_PX)
        metrics = QFontMetricsF(font)
        transform = painter.transform()
        placed: list[QRectF] = []
        for text, centre, across, direction in self._lead_markers():
            device = transform.map(centre)
            heading = transform.map(centre + direction) - device
            run = math.hypot(heading.x(), heading.y()) or 1.0
            heading = QPointF(heading.x() / run, heading.y() / run)
            width = metrics.horizontalAdvance(text) + 8
            height = metrics.height() + 1
            box_w, box_h = (width, height) if across else (height, width)
            for _step in range(FLYING_LEAD_MARKER_STEPS):
                box = QRectF(device.x() - box_w / 2, device.y() - box_h / 2, box_w, box_h)
                if not any(box.intersects(other) for other in placed):
                    break
                device += heading * (width + 2)
            placed.append(QRectF(device.x() - box_w / 2, device.y() - box_h / 2, box_w, box_h))
            painter.save()
            painter.resetTransform()
            painter.translate(device)
            if not across:
                painter.rotate(-90.0)
            sleeve = QRectF(-width / 2, -height / 2, width, height)
            painter.setPen(QPen(FLYING_LEAD_MARKER_EDGE, 1.0))
            painter.setBrush(QBrush(FLYING_LEAD_MARKER_FILL))
            painter.drawRoundedRect(sleeve, 2.0, 2.0)
            painter.setPen(FLYING_LEAD_MARKER_INK)
            painter.setFont(font)
            painter.drawText(sleeve, int(Qt.AlignmentFlag.AlignCenter), text)
            painter.restore()

    def _paint_flying_leads(self, painter: QPainter) -> None:
        """The wires leaving a part off the board, drawn as the insulated wire they are.

        In the same dress as an insulated wire on the board (``ConductorItem``): a dark
        casing under the net's colour, so a sleeve reads as a sleeve. Between the pad and the
        jacket is the tinned end that went into the hole, and past the edge the wire fades
        out -- it carries on to the panel, and a wire that simply stopped there would say it
        ended there.
        """
        for number, points in self._flying_lead_routes():
            colour = self.lead_colours.get(number, CONDUCTOR_STYLE["insulated-wire"][0])
            pad, first = points[0], points[1]
            run = math.hypot(first.x() - pad.x(), first.y() - pad.y()) or 1.0
            jacket_start = QPointF(
                pad.x() + (first.x() - pad.x()) * FLYING_LEAD_BARE_MM / run,
                pad.y() + (first.y() - pad.y()) * FLYING_LEAD_BARE_MM / run,
            )
            on_board = QPainterPath(jacket_start)
            for point in points[1:-1]:
                on_board.lineTo(point)
            edge, end = points[-2], points[-1]

            core = QPen(LEAD, 0.45)
            core.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(core)
            painter.drawLine(pad, jacket_start)

            for pen_colour, width in (
                (QColor(0, 0, 0, 150), FLYING_LEAD_JACKET_MM + 0.22),
                (colour, FLYING_LEAD_JACKET_MM),
            ):
                pen = QPen(pen_colour, width)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(on_board)
                if self.leads_carry_on:
                    # The thing it goes to is drawn, and its cable starts where this stops.
                    painter.drawLine(edge, end)
                    continue
                # Off the board: the same wire, fading towards the panel it is going to.
                fade = QLinearGradient(edge, end)
                fade.setColorAt(0.0, pen_colour)
                clear = QColor(pen_colour)
                clear.setAlpha(0)
                fade.setColorAt(1.0, clear)
                tail = QPen(QBrush(fade), width)
                tail.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(tail)
                painter.drawLine(edge, end)
        self._paint_lead_markers(painter)

    def boundingRect(self) -> QRectF:
        # The top margin has to hold a fixed-pixel-size ref label, which occupies more scene
        # space the further out the view is zoomed (see scenetext.label_extent_mm). Sized for
        # the lowest zoom at which the label is still drawn.
        top = 1.5 + REF_LABEL_PX / 3.0
        body = self._local_outline().boundingRect().adjusted(-1.5, -top, 1.5, 3.0)
        if not self._leads_rect.isNull():
            body = body.united(self._leads_rect)
        return body.united(self._names_rect) if not self._names_rect.isNull() else body

    def shape(self) -> QPainterPath:
        """What a click on this part is: its BODY and the pads its pins stand in.

        Not the bounding rect, which is sized to repaint far more than the part. And not the
        courtyard with a strip for the reference over it, which is what this was: the
        courtyard is already padded by half a pitch, and the strip was kept for a label the
        part no longer paints (``ReferenceLabelsItem`` prints every reference, over the
        body), so on a board built two rows apart every part's hit area reached over its
        neighbour's body and a click on a resistor selected the one below it -- and most of
        the solder-side copper lay under some part's hit area, where no click could reach
        it from either face. The pads are in it because an axial part's leads stand outside
        its body, and a part is dragged from pin 1 as often as from the middle.

        United rather than added: overlapping subpaths under the default odd-even fill
        would make a pad inside the body a hole in it.

        And the printed reference, where it is printed: a name is the obvious thing to click
        on a crowded board. Its plate is measured as ``ReferenceLayerItem`` draws it, at the
        view's zoom -- the label holds a pixel size, so it covers less board the further in
        the view is -- and kept inside the bounding rect, which is what the scene's index
        finds an item by.
        """
        if self._hit_shape is None:
            path = QPainterPath()
            path.addRect(self._local_body_rect())
            radius = max(self.board.pad_diameter / 2, 0.62)
            for pin in self.fp.pins:
                dx, dy = _local_offset(pin.d_col, pin.d_row, self.comp, self.side)
                pad = QPainterPath()
                pad.addEllipse(QPointF(dx * self.board.pitch, dy * self.board.pitch), radius, radius)
                path = path.united(pad)
            self._hit_shape = path
        transform = self._view_transform()
        if transform is None or not self.show_reference or transform.m11() < REF_LABEL_MIN_SCALE:
            return self._hit_shape
        scale = transform.m11()
        value = self.shown_value()
        placement = self.reference_placement(transform)
        if placement is None:
            return self._hit_shape
        key = (scale, value, placement[0].x(), placement[0].y(), placement[1].y())
        if self._hit_with_label is None or self._hit_with_label[0] != key:
            # The value is on the reference's plate, so the plate a click lands on is the
            # whole of it -- wherever ``reference_placement`` has put it.
            plate = self.reference_rect(transform.map(placement[0]), placement[1])
            label = QPainterPath()
            label.addRect(
                self.mapRectFromScene(transform.inverted()[0].mapRect(plate)).intersected(
                    self.boundingRect()
                )
            )
            self._hit_with_label = (key, self._hit_shape.united(label))
        return self._hit_with_label[1]

    def shown_value(self) -> str:
        """The value printed after this part's reference: its own, when the scene shows
        values (View > Show Part Values) and it has one, else nothing."""
        scene = self.scene()
        if not getattr(scene, "show_values", False):
            return ""
        return self.comp.value.strip()

    def faces_the_viewer(self) -> bool:
        """Whether this part is on the face the view looks at: drawn as a part, rather than
        as the hatched shadow of one through the board."""
        return self.side == self.comp.side

    def _view_transform(self) -> QTransform | None:
        """The board view's scene-to-pixel transform, or None in a scene nobody is
        looking at (a board picture, a test that never shows one)."""
        scene = self.scene()
        views = scene.views() if scene is not None else []
        return views[0].transform() if views else None

    def _apply_local_transform(self, painter: QPainter) -> None:
        """Enter the footprint's own coordinate frame, so a body can be drawn as a shape.

        Mirrors ``geometry.transform_offset`` exactly -- mirror about the vertical axis, then
        rotate clockwise -- with the solder side's reflection outermost, matching
        ``_local_offset``. QPainter applies the transforms it is given innermost-last, which
        is why they are called in the reverse of that order here.
        """
        if self.side == "bottom":
            painter.scale(-1.0, 1.0)
        painter.rotate(float(self.comp.rotation))
        if self.comp.mirrored:
            painter.scale(-1.0, 1.0)

    def _in_a_mode(self) -> bool:
        scene = self.scene()
        return bool(getattr(scene, "in_a_mode", False))

    def _follow_the_pointer(self, at: QPointF) -> None:
        """The move cursor over a part that can move and while no tool is armed; none
        otherwise, so a mode's cross shows through. A locked part gets no promise it cannot
        keep: the bus refuses its move with a message, which is the answer to the drag.

        Over a pad a copper end lies on, the copper's cursor: a press there picks up the
        end (``BoardScene.copper_grab_at``), and the part is moved by its body."""
        if self._in_a_mode():
            _show_cursor(self, None)
            return
        scene = self.scene()
        grab = scene.copper_grab_at(at) if isinstance(scene, BoardScene) else None
        if grab is not None:
            _show_cursor(self, grab_cursor(grab))
        else:
            _show_cursor(self, None if self.comp.locked else Qt.CursorShape.SizeAllCursor)

    def hoverEnterEvent(self, event: Any) -> None:
        self.hovered = True
        self._follow_the_pointer(event.scenePos())
        self.update()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event: Any) -> None:
        # A tool armed or put down with the pointer still on the part.
        self._follow_the_pointer(event.scenePos())
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event: Any) -> None:
        self.hovered = False
        if self.hasCursor():
            self.unsetCursor()
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        placement = placement_for(self.fp, self.board.pitch)
        style = style_for(self.fp, self.comp.value)
        keyed = polarity_pin_offset(self.fp, self.board.pitch)
        if self.board_colour is not None:
            style = replace(
                style, fill=self.board_colour, edge=QColor(self.board_colour).darker(160).name()
            )

        # The courtyard, faint and only when it matters. It is what DRC checks for overlap,
        # and it is padded well beyond the part -- drawing it as the body is what used to make
        # every component an oversized pale rectangle.
        if self.isSelected() or self.has_error or self.drag_blocked:
            ok = self.isSelected() and not self.drag_blocked
            outline_pen = QPen(SELECTED if ok else ERROR_OUTLINE, 0.22)
            outline_pen.setDashPattern([2.0, 2.0])
            painter.setPen(outline_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(self._local_outline())
        elif self.hovered and not self._in_a_mode() and not _on_paper(painter):
            # A hairline in the hover colour, solid where the selection is dashed: "this
            # one, if you press", not "this one".
            hover_pen = QPen(QColor(CANVAS_HOVER), CANVAS_HOVER_WIDTH_PX)
            hover_pen.setCosmetic(True)
            painter.setPen(hover_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(self._local_outline())

        # THE SOLDER SIDE SHOWS NO BODY, only where one IS. Turn a real board over and the
        # parts are on the far face: what you see is the substrate, the pads and the cut
        # lead ends. Drawing the silhouettes as if seen from above -- which this used to do
        # -- shows a view that does not exist, on the very side where a misreading gets
        # soldered in.
        #
        # But you can still see the part through the board, and you need to: "is there room
        # for this wire" and "which of these pads belongs to the chip" are solder-side
        # questions. So the footprint is hatched rather than drawn: the area is marked as
        # occupied, with none of the component-side detail -- no cathode band, no pin-1
        # notch, no tab -- that would make it read as a part you are looking at.
        #
        # A part ON the solder side is the same thing the other way up: from the component
        # side it is the hatched shadow, and from the solder side it is the part, drawn in
        # full and the right way round (``_apply_local_transform`` undoes the view's
        # reflection with the part's own).
        off_board = self.fp.body.archetype == "flying-leads"
        near = self.faces_the_viewer()
        from_below = self.side == "bottom"
        if not near and not off_board:
            painter.save()
            self._apply_local_transform(painter)
            _paint_body_shadow(painter, self.fp, placement, self.isSelected())
            painter.restore()

        # From above as KiCad's mesh of it is, where there is one; drawn by archetype where
        # not (``topview``'s parametric shapes stay a fallback for the data, not for this).
        view = top_view(self.fp, self.board.pitch)
        measured = view.source != "parametric"
        pads_drawn = False
        if near:
            # Leads, in item coordinates: a line does not care which way its frame is turned,
            # and the endpoints already come from the shared transform. A measured view has
            # its leads in it, as metal, where the mesh has them.
            leads = [] if measured else leads_for(self.fp, placement, self.board.pitch)
            if leads:
                lead_pen = QPen(LEAD, self.fp.lead_diameter or 0.5)
                lead_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(lead_pen)
                for lead in leads:
                    start = _local_offset_mm(lead.from_x, lead.from_y, self.comp, self.side)
                    end = _local_offset_mm(lead.to_x, lead.to_y, self.comp, self.side)
                    painter.drawLine(QPointF(*start), QPointF(*end))

            # A part off the board has no body here to draw -- only its wires, leaving.
            if off_board:
                self._paint_flying_leads(painter)
            painter.save()
            self._apply_local_transform(painter)
            # From the document's own value, so the bands cannot disagree with the
            # netlist. None for anything that is not a resistor with a readable value.
            bands = resistor_bands(self.fp, self.comp.value)
            names = self.pin_names if self.show_pin_names else ()
            if not off_board and measured:
                _paint_top_view(painter, view, style, self.isSelected(), placement, bands)
                _paint_top_marking(
                    painter, self.fp, placement, self.comp, view.marking, from_below, names,
                    self.board.pitch,
                )
                _paint_plus_mark(painter, self.fp, self.board.pitch)
            elif not off_board and self.standing is not None:
                _paint_standing_board(painter, self.standing, style, self.isSelected())
            elif not off_board:
                pads_drawn = _paint_body(
                    painter,
                    self.fp,
                    placement,
                    style,
                    keyed,
                    self.isSelected(),
                    self.board.pitch,
                    bands=bands,
                    art=self.art,
                    art_cache=self.art_cache,
                )
                _paint_top_marking(
                    painter, self.fp, placement, self.comp, None, from_below, names
                )
            if self.show_pin_names:
                _paint_pin_names(painter, self.pin_names, self.comp, style.accent, from_below)
            painter.restore()

        # From the solder side the scene paints the lead ends over the copper instead
        # (LeadEndsLayerItem); a part in a scene without that layer still paints its own.
        if self.art_cache.stale:
            refresh = getattr(self.scene(), "art_refresh", None)
            if refresh is not None:
                refresh.start()
        if not pads_drawn and (near or getattr(self.scene(), "lead_ends_layer", None) is None):
            self._paint_pin_ends(painter, keyed)

    def _paint_pin_ends(self, painter: QPainter, keyed: tuple[float, float] | None) -> None:
        """The holes this part occupies.

        Drawn on both sides, but they are the WHOLE story on the solder side: a cut lead end
        sitting in its pad is exactly what a person looks at while soldering. Pin 1 is filled
        brighter on a keyed part, because "which pad is pin 1, from the back" is the question
        that decides whether the part goes in the right way round.
        """
        # The lead ends are on the face away from the body: the solder side's for a part on
        # the component side, the component side's for one turned over.
        solder_side = not self.faces_the_viewer()
        # Under a round LED's dome the leads are what the lens shows of them: quiet marks.
        dome = not solder_side and self.fp.body.archetype == "led-round"
        radius = 0.62 if solder_side else (LED_LEAD_MARK_MM if dome else 0.5)
        lead = QColor(style_for(self.fp, self.comp.value).fill).darker(LED_LEAD_SHADE) if dome else PIN_MARKER
        for pin in self.fp.pins:
            dx, dy = _local_offset(pin.d_col, pin.d_row, self.comp, self.side)
            centre = QPointF(dx * self.board.pitch, dy * self.board.pitch)
            marked = pin.number == "1" and keyed is not None
            if self.isSelected():
                edge = SELECTED
            elif marked:
                edge = QColor("#1b1d22")
            elif dome:
                edge = lead
            else:
                edge = QColor("#42464b")
            painter.setPen(QPen(edge, 0.18 if solder_side else (0.08 if dome else 0.14)))
            painter.setBrush(QBrush(PIN_ONE if marked else lead))
            painter.drawEllipse(centre, radius, radius)

    def set_drag_blocked(self, blocked: bool) -> None:
        if blocked != self.drag_blocked:
            self.drag_blocked = blocked
            self.update()

    def reference_anchor(self) -> QPointF:
        """Where this part's reference is printed, in scene coordinates: just over the
        middle of its real body, whichever way the part is turned."""
        body = self._local_body_rect()
        return self.mapToScene(QPointF(body.center().x(), body.top()))

    def reference_placement(self, transform: QTransform) -> tuple[QPointF, QPointF] | None:
        """Where this part's reference goes on screen at this zoom, as (scene anchor, device
        offset): where its own board puts it (``_own_reference_placement``), unless
        another part's reference or pin names are already there -- then the scene moves
        it to another side of its body (``BoardScene.reference_placements``).

        The layer that prints it, the legend that gives way under it and the part's hit
        area all ask here."""
        scene = self.scene()
        if isinstance(scene, BoardScene):
            settled = scene.reference_placements(transform)
            if self.comp.id in settled:
                return settled[self.comp.id]
        return self._own_reference_placement(transform)

    def reference_sides(
        self, transform: QTransform
    ) -> list[tuple[QPointF, QPointF]]:
        """Every place this part's reference may go, in the order it is tried when the
        place its own board gives it is taken: over the body, under it, left of it,
        right of it. As (scene anchor, device offset), like ``reference_placement``.

        Left and right are measured on the body as it is SEEN, whichever way the part is
        turned, and the label stands centred on the body's middle row, clear of it."""
        body = self._local_body_rect()
        height = QFontMetricsF(label_font(REF_LABEL_PX, True)).height()
        sides = [
            (self.reference_anchor(), REF_LABEL_OFFSET),
            (
                self.mapToScene(QPointF(body.center().x(), body.bottom())),
                QPointF(0.0, height - REF_LABEL_OFFSET.y()),
            ),
        ]
        centre = self.mapToScene(body.center())
        seen = transform.mapRect(self.mapRectToScene(body))
        middle = transform.map(centre)
        width = self.reference_rect(middle, QPointF(0.0, 0.0)).width()
        bottom = seen.center().y() + height / 2 - middle.y()
        gap = 2.0
        sides.append((centre, QPointF(seen.left() - gap - width / 2 - middle.x(), bottom)))
        sides.append((centre, QPointF(seen.right() + gap + width / 2 - middle.x(), bottom)))
        return sides

    def _own_reference_placement(
        self, transform: QTransform
    ) -> tuple[QPointF, QPointF] | None:
        """Where this part's reference goes on screen at this zoom, as (scene anchor, device
        offset), looking at the board and not at the other references: over its body, as
        ``reference_anchor`` says -- or under it, where over it
        would print on a board note, or nowhere when both would.

        A reference is held at a pixel size and a note is written in millimetres, so zoomed
        out the reference outgrows the gap between them: on nano-relay J2's landed on the
        "LOAD" written over it and the two read "LOJ2D". The note is the builder's own and
        the reference is in Properties, so the reference is the one that moves, and yields.
        Under it, it must not print on a pin name either -- its own part's or the next
        one's -- or it would only have moved the collision.

        The board's printed legend is kept off too, where a place clear of it exists: a
        part on the first row had its reference over the column letters above it, and on
        ne555-astable LED1's hid the "F" its own pins are counted from. Where neither place
        is clear of the legend, the reference prints all the same, over its part if no note
        is there, and the letter under it gives way (``BoardLegendItem.covered_labels``): a
        letter is one of a run, and U1 is the only name the board's chip has."""
        over = (self.reference_anchor(), REF_LABEL_OFFSET)
        notes = self._note_rects(transform)
        legend = self._legend_rects(transform)
        if not notes and not legend:
            return over
        plate = self.reference_rect(transform.map(over[0]), over[1])
        over_clear = not any(plate.intersects(note) for note in notes)
        if over_clear and not any(plate.intersects(label) for label in legend):
            return over
        height = QFontMetricsF(label_font(REF_LABEL_PX, True)).height()
        body = self._local_body_rect()
        under = (
            self.mapToScene(QPointF(body.center().x(), body.bottom())),
            QPointF(0.0, height - REF_LABEL_OFFSET.y()),
        )
        plate = self.reference_rect(transform.map(under[0]), under[1])
        taken = notes + self._pin_name_rects_on_screen(transform)
        under_clear = not any(plate.intersects(rect) for rect in taken)
        if under_clear and not any(plate.intersects(label) for label in legend):
            return under
        # Neither is clear of the legend: a letter gives way, a note or a pin name never.
        if over_clear:
            return over
        if under_clear:
            return under
        return None

    def _pin_name_rects_on_screen_of_own(self, transform: QTransform) -> list[QRectF]:
        """This part's printed pin names, in device pixels."""
        if not self.isVisible():
            return []
        return [transform.mapRect(self.mapRectToScene(rect)) for rect in self.pin_name_rects()]

    def _pin_name_ink_on_screen(self, transform: QTransform) -> list[QRectF]:
        """This part's pin names as printed, in device pixels -- none when the view is too
        far out for ``_paint_pin_names`` to print them."""
        if not self.isVisible() or math.hypot(transform.m11(), transform.m12()) < 5.0:
            return []
        return [
            transform.mapRect(self.mapRectToScene(rect)) for rect in self.pin_name_ink_rects()
        ]

    def _pin_name_rects_on_screen(self, transform: QTransform) -> list[QRectF]:
        """Every part's printed pin names in this scene, in device pixels."""
        scene = self.scene()
        items: dict[str, ComponentItem] = getattr(scene, "component_items", {}) if scene else {}
        return [
            transform.mapRect(item.mapRectToScene(rect))
            for item in items.values()
            if item.isVisible()
            for rect in item.pin_name_rects()
        ]

    def reference_rect(self, device_anchor: QPointF, offset: QPointF) -> QRectF:
        """The plate a reference (and its value, when shown) is printed on, in device pixels."""
        value = self.shown_value()
        if value:
            return reference_plate(device_anchor, self.comp.ref, value, REF_LABEL_PX, offset=offset)[0]
        return label_plate_rect(
            device_anchor, self.comp.ref, REF_LABEL_PX, REF_LABEL_ALIGN, bold=True, offset=offset
        )

    def _legend_rects(self, transform: QTransform) -> list[QRectF]:
        """The addresses the board prints, as rectangles in device pixels."""
        scene = self.scene()
        legend: BoardLegendItem | None = getattr(scene, "legend_item", None) if scene else None
        if legend is None or not legend.isVisible():
            return []
        return [transform.mapRect(rect) for rect in legend.label_rects()]

    def _note_rects(self, transform: QTransform) -> list[QRectF]:
        """The board notes this scene shows, as rectangles in device pixels."""
        scene = self.scene()
        if scene is None or not getattr(scene, "show_board_notes", False):
            return []
        items: dict[str, BoardNoteItem] = getattr(scene, "board_note_items", {})
        return [
            transform.mapRect(note.mapToScene(note.shape()).boundingRect())
            for note in items.values()
            if note.isVisible()
        ]

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change in (
            QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged,
            QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged,
        ):
            for name in ("reference_layer", "lead_ends_layer", "legend_item"):
                layer = getattr(self.scene(), name, None)
                if layer is not None:
                    layer.update()
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            # Snap to the nearest hole, but do NOT clamp to the board bounds: dragging
            # a part past the edge and releasing there must reach the bus's own
            # off-board refusal (see BoardScene.commit_pending_moves), not be silently
            # prevented by the item itself. The board substrate visually bounds the
            # scene anyway, so the UX cost of not clamping is small.
            p: QPointF = value
            snapped = screen_to_hole(p, self.board, self.side)
            self.pending_anchor = snapped
            return hole_to_screen(snapped, self.board, self.side)
        return super().itemChange(change, value)


# ------------------------------------------------------------------------- scene


def _reference_order(ref: str) -> tuple[str, int, str]:
    """R2 before R10: the order references are settled in, after where they stand."""
    letters = ref.rstrip("0123456789")
    digits = ref[len(letters):]
    return letters, int(digits) if digits else 0, ref


def settle_reference_placements(
    items: list[ComponentItem], transform: QTransform
) -> dict[str, tuple[QPointF, QPointF] | None]:
    """Where every part's reference is printed at this zoom, none on another's.

    Each reference first takes the place its own board gives it
    (``ComponentItem._own_reference_placement``): over its body, or under it where over is
    a note or the legend. Two of those could be one place -- on ne555-astable "R1", moved
    under its resistor off the column letters, landed on "U1" over the chip under it, and
    "J1" under the header on "C1" -- because each part looked only at the board.

    So they are settled one at a time, the ones over their bodies first and then by
    reference, and a reference whose place is already another's tries the other sides of
    its body in turn (``reference_sides``): the first one clear of the references settled,
    every pin name, the notes and the legend, or, if none is, the first clear of all but
    the legend. Where no side is clear it stays where its board put it. Nothing is moved
    where no two names share a place, so such a board prints as it always did -- and the
    order is the references', so the same board prints the same way every time.

    A pin name's ROOM keeps a moved reference off it but does not move one: it is wider
    than the name, and asked of every reference it moved R2 on ne555-astable off a place
    nothing was printed on. The name's INK does move one: on atmega328-relay K1's
    reference, over the relay, was printed across U1's "AVCC" under the chip."""
    if not items:
        return {}
    own = {item.comp.id: item._own_reference_placement(transform) for item in items}
    pins = {item.comp.id: item._pin_name_rects_on_screen_of_own(transform) for item in items}
    ink = [rect for item in items for rect in item._pin_name_ink_on_screen(transform)]
    notes = items[0]._note_rects(transform)
    legend = items[0]._legend_rects(transform)

    def plate(item: ComponentItem, where: tuple[QPointF, QPointF]) -> QRectF:
        return item.reference_rect(transform.map(where[0]), where[1])

    def hits(rect: QRectF, rects: list[QRectF]) -> bool:
        return any(rect.intersects(other) for other in rects)

    def rank(item: ComponentItem) -> tuple[int, tuple[str, int, str]]:
        where = own[item.comp.id]
        first = 0 if where is not None and where[1] == REF_LABEL_OFFSET else 1
        return first, _reference_order(item.comp.ref)

    every_pin = [rect for rects in pins.values() for rect in rects]
    settled: list[QRectF] = []
    placed: dict[str, tuple[QPointF, QPointF] | None] = {}
    for item in sorted(items, key=rank):
        where = own[item.comp.id]
        if where is None:
            placed[item.comp.id] = None
            continue
        here = plate(item, where)
        if not hits(here, settled + ink):
            placed[item.comp.id] = where
            settled.append(here)
            continue
        taken = settled + every_pin + notes
        sides = [side for side in item.reference_sides(transform) if side != where]
        choice = next(
            (side for side in sides if not hits(plate(item, side), taken + legend)), None
        ) or next((side for side in sides if not hits(plate(item, side), taken)), None)
        placed[item.comp.id] = choice or where
        settled.append(plate(item, choice or where))
    return placed


class ReferenceLayerItem(QGraphicsItem):
    """Every part's reference, printed OVER every part.

    A reference is centred just above its part's body, on a plate (``REF_PLATE``), and it
    used to be painted by the part itself -- so it sat at the part's own place in the
    stacking order, and on a crowded board the next part along was drawn over it: "X1" came
    out as "X" with an LED across the rest. One item above all of them prints them all, so
    no body can cover a name. Below the placement ghost and the tools' previews, which are
    about what is being done now.

    Skipped when zoomed out far enough that the text would be an unreadable smear, as it
    always was, and in a board picture (``show_reference``), where a label held at a pixel
    size is most of a thumbnail.
    """

    def __init__(self, scene: BoardScene) -> None:
        super().__init__()
        self._board_scene = scene
        self.setZValue(70)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self) -> QRectF:
        scene = self.scene()
        return scene.sceneRect() if scene is not None else QRectF()

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        # Paper -- the 1:1 PDF -- is told apart by its device, and gets its labels in
        # millimetres; on a screen they hold a pixel size (``ui/scenetext.py``).
        printed = isinstance(painter.device(), QPagedPaintDevice)
        scale = painter.transform().m11() or 1.0
        if scale < REF_LABEL_MIN_SCALE and not printed:
            return
        for item in self._board_scene.component_items.values():
            if not item.show_reference or not item.isVisible():
                continue
            colour = SELECTED if item.isSelected() else REF_LABEL
            value = item.shown_value()
            if printed:
                draw_printed_reference(
                    painter, item.reference_anchor(), item.comp.ref, value,
                    PRINT_REF_LABEL_MM, PRINT_VALUE_LABEL_MM, PRINT_REF_GAP_MM,
                    background=REF_PLATE,
                    reference_colour=REF_LABEL, value_colour=VALUE_LABEL,
                )
                continue
            # Over the body, never on it, where it would hide a resistor's bands, and laid
            # out as the plate was, so the part's hit area (ComponentItem.shape) still
            # takes it in -- or under it, or not at all, where over it is a board note
            # (``ComponentItem.reference_placement``). Outlined rather than plated: see
            # REF_HALO.
            placement = item.reference_placement(painter.transform())
            if placement is None:
                continue
            anchor, offset = placement
            draw_outlined_reference(
                painter, anchor, item.comp.ref, value, REF_LABEL_PX,
                offset=offset, reference_colour=colour, value_colour=VALUE_LABEL,
                halo=REF_HALO,
            )


class LeadEndsLayerItem(QGraphicsItem):
    """Every part's cut lead ends, from the SOLDER side, painted over the copper.

    From the solder side the copper is what is being worked on, so it is drawn above the
    parts (``ConductorItem``). But a lead comes up THROUGH its joint: the end standing out of
    the solder is the one thing on that face that belongs to the part, and pin 1's brighter
    fill is how somebody reading the back of the board tells which way round a chip went in.
    Painted by the part, it would sit at the part's place in the stacking order, and the
    fillet at the end of every wire landing on a pin would cover it. Above the copper, below
    the risk rings and the tools' previews.
    """

    def __init__(self, scene: BoardScene) -> None:
        super().__init__()
        self._board_scene = scene
        self.setZValue(50)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self) -> QRectF:
        scene = self.scene()
        return scene.sceneRect() if scene is not None else QRectF()

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        for item in self._board_scene.component_items.values():
            # A part on the solder side has its lead ends on the OTHER face, and is looked at
            # from this one: it paints its own pins, as a part from above does.
            if not item.isVisible() or item.faces_the_viewer():
                continue
            painter.save()
            painter.setTransform(item.sceneTransform(), True)
            item._paint_pin_ends(painter, polarity_pin_offset(item.fp, item.board.pitch))
            painter.restore()


class ViaMarkItem(QGraphicsItem):
    """A via: a pinless hole where a solder run on the component side meets copper on the
    solder side (``wiringstats.vias``, the guide's and the 3D view's list too).

    Drawn on both faces, over the copper: the hole goes through the board, so it is the same
    place from either side, and it is the one place a builder solders both faces of a hole
    with no lead in it. Screen only -- ``print_scene`` leaves it off the 1:1 sheet, which is
    the copper and nothing the copper does not have. Takes no clicks: what is under it is
    the copper, and that is what a click means.
    """

    def __init__(
        self,
        hole: HoleCoord,
        board: Board,
        side: BoardSide,
        cells: Mapping[str, FingerCell] | None = None,
    ) -> None:
        super().__init__()
        self.hole = hole
        # On a finger's copper where the via is a finger cell, as the rail's own copper is.
        self.setPos(path_point_to_screen(hole, board, side, cells or {}))
        self.setZValue(45)  # Over the copper of either face, under the lead ends and tools.
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self) -> QRectF:
        reach = VIA_RING_RADIUS_MM + VIA_RING_PEN_MM
        return QRectF(-reach, -reach, 2 * reach, 2 * reach)

    def shape(self) -> QPainterPath:
        return QPainterPath()  # Never what the pointer is over.

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        centre = QPointF(0, 0)
        painter.setPen(QPen(VIA_RING, VIA_RING_PEN_MM))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(centre, VIA_RING_RADIUS_MM, VIA_RING_RADIUS_MM)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(VIA_DOT))
        painter.drawEllipse(centre, VIA_DOT_RADIUS_MM, VIA_DOT_RADIUS_MM)
        painter.setPen(QPen(VIA_DOT_EDGE, VIA_DOT_EDGE_MM))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(centre, VIA_DOT_RADIUS_MM, VIA_DOT_RADIUS_MM)


def print_scene(
    doc: PerfDocument, lookup: FootprintLookup, side: BoardSide, *, show_values: bool = False
) -> BoardScene:
    """The scene a 1:1 sheet is printed from: the board and nothing else. No ratsnest (a
    line on paper reads as a wire to solder), no rulers, no via marks. The window's export
    and ``--headless`` both build their sheets here, so the two cannot print different
    things from one board."""
    return BoardScene(
        doc,
        lookup,
        side=side,
        show_ratsnest=False,
        show_rulers=False,
        show_values=show_values,
        show_vias=False,
    )


def straight_runs(points: Sequence[QPointF]) -> list[tuple[QPointF, QPointF]]:
    """A polyline as its longest straight stretches, (start, end) each: a wire laid from A1
    to A9 by way of A5 is one run, and a bend starts the next."""
    out: list[tuple[QPointF, QPointF]] = []
    if len(points) < 2:
        return out
    start = previous = points[0]
    heading: tuple[float, float] | None = None
    for point in points[1:]:
        dx, dy = point.x() - previous.x(), point.y() - previous.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        unit = (round(dx / length, 3), round(dy / length, 3))
        if heading is not None and unit != heading:
            out.append((start, previous))
            start = previous
        heading = unit
        previous = point
    out.append((start, previous))
    return out


class NetNameRun(NamedTuple):
    """One straight stretch of copper a net's name may be written on, in scene mm."""

    net_id: str
    text: str
    ink: QColor
    start: QPointF
    end: QPointF
    length: float

    def middle(self) -> QPointF:
        return QPointF((self.start.x() + self.end.x()) / 2, (self.start.y() + self.end.y()) / 2)


class NetNameLayerItem(QGraphicsItem):
    """The nets' names, on the wires and the solder runs that carry them.

    One item for the whole board, as ``ReferenceLayerItem`` is, because which run is named
    depends on every other run: they are tried longest first, a name goes only on a run
    longer on screen than the name, and one that would overlap a name already written is
    left off -- so a crowded corner keeps its clearest name instead of a pile of them, and
    zooming in brings the rest out. How many is in ``NET_NAME_EVERY_RUN_SCALE``.

    Only the copper on the face in view: a name on the far face would be read as being on
    this one. Never on paper, which is soldered from, and takes no clicks: what is under a
    name is the wire, and that is what a click means.
    """

    def __init__(self, scene: BoardScene) -> None:
        super().__init__()
        self._board_scene = scene
        # Over the copper, the parts and the board's own labels; under the references.
        self.setZValue(65)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.runs = self._collect()

    def _collect(self) -> list[NetNameRun]:
        scene = self._board_scene
        document = scene.document
        names = {net.id: net.name for net in document.nets}
        colours = net_colours(document)
        shortest = NET_NAME_MIN_RUN_PITCHES * document.board.pitch - 1e-6
        found: list[NetNameRun] = []
        for item in scene.conductor_items.values():
            net_id = item.conductor.net_id
            if item.is_far_side() or net_id is None or net_id not in names:
                continue
            colour = colours.get(net_id, "grey")
            ink = NET_NAME_BLACK if colour == "black" else named_insulation(colour)
            for start, end in straight_runs(item._points()):
                length = math.hypot(end.x() - start.x(), end.y() - start.y())
                if length >= shortest:
                    found.append(NetNameRun(net_id, names[net_id], ink, start, end, length))
        found.sort(key=lambda run: (-run.length, run.text, run.start.x(), run.start.y()))
        return found

    def placed(self, transform: QTransform) -> list[tuple[NetNameRun, QRectF]]:
        """The runs named at this zoom, each with the flag's box in device pixels."""
        scale = abs(transform.m11()) or abs(transform.m12()) or 1.0
        if scale < NET_NAME_MIN_SCALE:
            return []
        every_run = scale >= NET_NAME_EVERY_RUN_SCALE
        metrics = QFontMetricsF(label_font(NET_NAME_PX, True))
        height = metrics.height()
        named: set[str] = set()
        taken: list[QRectF] = []
        out: list[tuple[NetNameRun, QRectF]] = []
        for run in self.runs:
            if not every_run and run.net_id in named:
                continue
            width = metrics.horizontalAdvance(run.text)
            across = abs(run.end.x() - run.start.x()) >= abs(run.end.y() - run.start.y())
            # Room either side of the name along a run, or two names' height down one.
            need = width + 16 if across else height * 2.2
            if run.length * scale < need:
                continue
            centre = transform.map(run.middle())
            box = QRectF(
                centre.x() - (width + 14) / 2, centre.y() - (height + 6) / 2, width + 14, height + 6
            )
            if any(box.intersects(other) for other in taken):
                continue
            taken.append(box.adjusted(-4, -4, 4, 4))
            named.add(run.net_id)
            out.append((run, box))
        return out

    def boundingRect(self) -> QRectF:
        scene = self.scene()
        return scene.sceneRect() if scene is not None else QRectF()

    def shape(self) -> QPainterPath:
        return QPainterPath()  # Never what the pointer is over.

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        if not self._board_scene.show_net_names or isinstance(painter.device(), QPagedPaintDevice):
            return
        centred = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        for run, _box in self.placed(painter.transform()):
            draw_flag_label(
                painter, run.middle(), run.text, NET_NAME_PX, centred,
                colour=run.ink, fill=NET_NAME_FILL,
            )


#: How long one conductor takes to fade in after an Auto-wire, how far apart two start,
#: and the most the whole reveal takes however many there are -- see
#: ``BoardScene.reveal_conductors``.
REVEAL_FADE_MS = 220
REVEAL_STEP_MS = 45.0
REVEAL_SPAN_MS = 1200


class BoardScene(QGraphicsScene):
    """The 2D board, rebuilt from a ``PerfDocument`` snapshot each time it changes.

    Read-only by itself: it never mutates ``self.document``. When a bus is supplied,
    dragging a component dispatches ``component.move`` on release and emits
    ``moveCommitted`` with the ``DispatchResult`` list so the host (``main.py``) can
    decide how to react -- rerun DRC, update the status bar, rebuild from
    ``bus.document`` -- rather than the scene reaching into that policy itself.
    """

    moveCommitted = Signal(list)
    #: Emitted with the ids of the schematic nets under the current selection, so the host
    #: can update a net list or a status line without the scene knowing either exists.
    selectionNetsChanged = Signal(list)
    #: Emitted with the armed conductor kind, or an empty string when drawing ends.
    drawArmed = Signal(str)
    #: Emitted with the DispatchResult of a hand-drawn conductor.
    conductorDrawn = Signal(object)
    #: Emitted with what the conductor being drawn would do (``drawcheck.DrawCheck``) as
    #: the pointer moves, or None when there is nothing to check yet.
    drawChecked = Signal(object)
    #: Emitted with the conductor already lying exactly where the one just finished would
    #: have gone, which was therefore not laid.
    drawnAlready = Signal(object)
    #: A click where several conductors lie took the next one: (which, of how many).
    pickCycled = Signal(int, int)
    #: Emitted with the id of the net being filled by clicking pins, or "" when that ends.
    netPinsArmed = Signal(str)
    #: Emitted with the "U1.8" labels picked so far, after every pick.
    netPinsChanged = Signal(list)
    #: Emitted with why a click did not count: an empty hole, or a pin already spoken for.
    #: A silently ignored click reads as the tool having stopped working.
    netPinRejected = Signal(str)
    #: Emitted with the DispatchResult of the committed net.connect.
    netPinsCommitted = Signal(object)
    #: Emitted when the two-click connect tool is armed or disarmed.
    connectArmed = Signal(bool)
    #: Emitted with the pin waiting for its partner, as a one-item list, or empty.
    connectProgress = Signal(list)
    #: Emitted with the DispatchResult of a pair that was joined.
    pinsConnected = Signal(object)
    #: (col, row) under the cursor. The whole tool speaks hole addresses, so the status
    #: bar has to be able to say which one the pointer is on -- otherwise you count.
    hoveredHole = Signal(int, int)
    #: Emitted when the track-cutting tool is armed or disarmed.
    cutArmed = Signal(bool)
    #: Emitted with the DispatchResult of a cut made or taken back.
    cutMade = Signal(object)
    #: Emitted when the measuring tool is armed or disarmed.
    measureArmed = Signal(bool)
    #: The measurement as a sentence, live while the pointer moves, or "" when there is
    #: nothing to say. Text rather than numbers because every consumer of it is prose.
    measured = Signal(str)
    #: A plain click on what a finding marks on the board: a ringed hole (a ``HoleCoord``)
    #: or a part drawn in error (its id). The window picks the finding's row for it.
    findingPicked = Signal(object)

    def __init__(
        self,
        document: PerfDocument,
        lookup: FootprintLookup,
        side: BoardSide = "top",
        bus: CommandBus | None = None,
        show_ratsnest: bool = True,
        show_rulers: bool = True,
        show_far_side: bool = True,
        show_pin_names: bool = True,
        show_references: bool = True,
        show_values: bool = False,
        show_vias: bool = True,
        show_net_names: bool = False,
        show_off_board: bool = False,
    ) -> None:
        super().__init__()
        self.lookup = lookup
        #: Restarted by every part whose art was drawn stretched (``ArtCache``): when the
        #: zoom has been still for ``ART_REFRESH_MS``, the scene is painted again and the
        #: parts' images are filled at the scale it settled on.
        self.art_refresh = QTimer(self)
        self.art_refresh.setSingleShot(True)
        self.art_refresh.setInterval(ART_REFRESH_MS)
        self.art_refresh.timeout.connect(self.update)
        #: Draw the thing each part off the board is, beside the board (View > Parts Off the
        #: Board): the window's, on by default there; off in every picture, print and export,
        #: which show the board and only the board.
        self.show_off_board = show_off_board
        self.off_board_items: dict[str, OffBoardItem] = {}
        #: A thing let go somewhere, waiting for the release to finish before it is committed.
        self._off_board_drop: tuple[str, Point2] | None = None
        #: The nets' names on the wires (``NetNameLayerItem``): the window's view setting,
        #: on there by default; off in every picture, print and export made from a scene.
        self.show_net_names = show_net_names
        self.net_name_layer: NetNameLayerItem | None = None
        #: Mark each via (``ViaMarkItem``). On screen always; off on the 1:1 sheet.
        self.show_vias = show_vias
        self.via_items: list[ViaMarkItem] = []
        self.show_pin_names = show_pin_names
        self.show_references = show_references
        #: Each part's value after its reference (View > Show Part Values): a view setting,
        #: like the pin names, never a document field.
        self.show_values = show_values
        self.side = side
        self.bus = bus
        self.show_far_side = show_far_side
        self.document = document
        self.violations: tuple[DrcViolation, ...] = ()
        #: What the findings marked on the board say, as tooltips (``set_finding_notes``):
        #: by ringed hole, and by the id of a part drawn in error.
        self._finding_holes: dict[tuple[int, int], str] = {}
        self._finding_parts: dict[str, str] = {}
        self.component_items: dict[str, ComponentItem] = {}
        #: ``reference_placements``' last answer and what it was worked out from.
        self._reference_cache: tuple[object, dict[str, tuple[QPointF, QPointF] | None]] | None = None
        self.mount_items: dict[str, MountingHoleItem] = {}
        self.connector_items: dict[str, EdgeConnectorItem] = {}
        #: The face the hand tools draw on: the face being looked at, which every flip
        #: sets, or the window's Draw on choice until the next flip. Read through
        #: ``solder_draw_face`` and ``drawing_as``: it counts only on a board with pads on
        #: both faces.
        self.draw_face: BoardSide = side
        #: ``geometry.finger_cells`` of the document, once per build: where solder on an
        #: outside finger is drawn, for every conductor item and every zoom to a hole.
        self.finger_cells: dict[str, FingerCell] = {}
        #: Every part's reference, over every part -- see ``ReferenceLayerItem``.
        self.reference_layer: ReferenceLayerItem | None = None
        #: The solder side's lead ends, over the copper; None on the component side.
        self.lead_ends_layer: LeadEndsLayerItem | None = None
        self.board_note_items: dict[str, BoardNoteItem] = {}
        #: Draw the labels written on the board (View > Show Board Labels).
        self.show_board_notes = True
        self.pad_grid: PadGridItem | None = None
        #: The board itself, on a breadboard -- see BreadboardItem. None on every other.
        self.breadboard_item: BreadboardItem | None = None
        #: The addresses the board prints (BoardLegendItem); None on a board printing none.
        self.legend_item: BoardLegendItem | None = None
        self.legend_echo: LegendEchoItem | None = None
        self.show_ratsnest = show_ratsnest
        self.show_rulers = show_rulers
        self.highlighted_nets: tuple[str, ...] = ()
        #: The conductors on the board, by id, so lighting a net touches only them.
        self.conductor_items: dict[str, ConductorItem] = {}
        #: Copper an Auto-wire just laid, fading in one conductor after another, by id --
        #: see ``reveal_conductors``. None when nothing is fading in.
        self._reveal: QVariantAnimation | None = None
        self._reveal_ids: tuple[str, ...] = ()
        self._reveal_step_ms = 0.0
        #: The physical nets of the document last asked about -- see _conductors_on.
        self._physical_nets: tuple[PerfDocument, list[PhysicalNet]] | None = None
        self._risk_item: RiskRingsItem | None = None
        self._bench_item: RiskRingsItem | None = None
        self._focus_item: RiskRingsItem | None = None
        #: The copper as it was before the last Auto-wire or Redo Wiring, shown dashed over
        #: today's while the window compares them; empty when it does not.
        self._before_copper: tuple[Conductor, ...] = ()
        self._before_item: QGraphicsPathItem | None = None
        #: The holes of the finding picked or hovered in the drawer, and the holes a bench
        #: check rings -- see ``set_focused_holes``.
        self._focused_holes: tuple[HoleCoord, ...] = ()
        self._bench_holes: frozenset[tuple[int, int]] = frozenset()
        self._ratsnest_item: RatsnestItem | None = None
        self._ratsnest_links: tuple[RatsnestLine, ...] = ()
        self._armed_footprint: Footprint | None = None
        #: How the part about to be placed is turned and flipped (R, Shift+R and M while
        #: placing). Kept across placements of the same part -- a row of resistors all go
        #: down the same way round -- and back to upright when another part is armed.
        self._armed_rotation: Rotation = 0
        self._armed_mirrored = False
        self._armed_id: str | None = None
        #: The design part in hand (``arm_part``): placing it is ``part.place`` for THAT part,
        #: its reference kept, not a new part of the same footprint.
        self._armed_part_id: str | None = None
        self._draw_kind: ConductorKind | None = None
        self._draw_path: list[HoleCoord] = []
        #: Whether a solder run goes down the column before along the row (``/`` flips it).
        self._draw_column_first = False
        self._draw_preview: DrawPreviewItem | None = None
        #: The last ``check_drawn`` asked, by (document, kind, path): the pointer moves far
        #: more often than it changes holes.
        self._draw_checked: (
            tuple[PerfDocument, str, tuple[HoleCoord, ...], DrawCheck] | None
        ) = None
        #: What the conductor just laid was found to do, and its kind and holes, for the
        #: host's status line.
        self.last_draw_check: DrawCheck | None = None
        self.last_drawn: tuple[ConductorKind, tuple[HoleCoord, ...]] | None = None
        #: How the copper just laid came to be: "drew" a new conductor, "extended" a run
        #: from its end, or "reshaped" one by a handle.
        self.last_draw_verb = "drew"
        #: The run being drawn on from its end (``_continue_from``), and how many of the
        #: path's holes were already its own.
        self._draw_continuing: str | None = None
        self._draw_base = 0
        #: The path so far and the step to the pointer: what Enter or the next click lays.
        self._draw_ahead: tuple[HoleCoord, ...] = ()
        #: A drawing press still held: the hole it went down on and the last hole the
        #: pointer was in (``draw_press``), and whether it has become a drag.
        self._draw_drag: tuple[HoleCoord, HoleCoord] | None = None
        self._draw_dragged = False
        #: The squares on the one conductor selected (``CopperHandleItem``), and the drag of
        #: one: (conductor id, index in its path), the path it would get, its preview.
        self._handles: list[CopperHandleItem] = []
        self._reshape: tuple[str, int] | None = None
        self._reshape_path: tuple[HoleCoord, ...] | None = None
        self._reshape_preview: DrawPreviewItem | None = None
        self._reshape_check: DrawCheck | None = None
        #: A segment's drag: the hole it was pressed on, which the slide is measured from.
        #: None while an end or a corner is dragged.
        self._reshape_slide: HoleCoord | None = None
        self._net_pin_target: str | None = None
        self._net_pin_picks: list[tuple[str, str]] = []
        self._net_pin_holes: list[HoleCoord] = []
        self._net_pin_item: PickedPinsItem | None = None
        self._connect_armed = False
        self._connect_first: tuple[str, str] | None = None
        self._connect_hole: HoleCoord | None = None
        self._connect_item: PickedPinsItem | None = None
        #: The ring on the pin under the pointer in the connect and draw tools, made on
        #: the first hover and destroyed with the rest by a rebuild (``_build``).
        self._pin_hover: PinHoverItem | None = None
        self._measure_armed = False
        self._measure_from: HoleCoord | None = None
        self._measure_item: PickedPinsItem | None = None
        #: The last finished measurement (``describe_span``), until the next first click.
        self.measurement = ""
        self._cut_armed = False
        #: Set when a mode consumed a right press, read and cleared by the view before it
        #: decides whether to offer a context menu. See take_consumed_right_click.
        self._right_click_taken = False
        #: The hole the pointer was last over, or None once it has left the view. Kept so
        #: a rebuilt ghost can land where the pointer is rather than at A1, and so a pan
        #: or a keyboard zoom can re-read what is under a pointer that has not moved.
        self._last_hole: HoleCoord | None = None
        self._ghost: PlacementGhostItem | None = None
        #: The part being dragged in from the Parts panel or the sheet -- see
        #: ``show_drop_ghost``. Separate from ``_ghost``, which belongs to an armed tool.
        self._drop_ghost: PlacementGhostItem | None = None
        #: Whether the last placement landed somewhere already occupied. Read by the host to
        #: say so, since the bus allows it and only DRC objects.
        self.last_placement_overlapped = False
        #: Whether the last placement put a pin where no lead can go at all -- a mounting
        #: bore, an edge-connector finger, a cut track. Separate from the above because
        #: the two need different sentences: one is a board you probably do not want, the
        #: other is a board that cannot be built.
        self.last_placement_on_a_dead_hole = False
        #: Whether the last drag let a part go with a pin where no lead can be soldered: a
        #: bore, a finger, a cut. Allowed, as a placement there is (the board is still
        #: legal and DRC calls it an error), and said, as a placement there is -- a drag
        #: went red while it moved and then landed with "Done" and nothing else.
        self.last_move_on_a_dead_hole = False
        #: What every part placed from here is given as its value ("10k", "100nF"), set by
        #: the host from the parts panel. Held across placements rather than cleared with
        #: the armed footprint: five resistors of the same value is the case, and retyping
        #: it between each of them is the friction this exists to remove.
        self.placement_value = ""
        #: What a part chosen from the catalog says about itself -- its pin names, what it
        #: is, and the letter its reference takes (a 7805 is a TO-220 and not a "Q") --
        #: given to every part placed from here. Set by the host with the armed footprint
        #: and cleared when a plain package is picked, so a TO-92 chosen after a BC547 is
        #: not quietly a BC547.
        self.placement_pin_names: PinNames = ()
        self.placement_symbol: PartSymbol | None = None
        #: What each pin of the catalog part being placed does, and the package they
        #: were read for: a part placed in any other package gets none, and keeps the
        #: numbered box.
        self.placement_pin_roles: PinRoles = ()
        self.placement_roles_footprint_id: str | None = None
        self.placement_prefix: str | None = None
        self._build()
        self.selectionChanged.connect(self._on_selection_changed)

    # -- (re)building -----------------------------------------------------

    def set_document(self, document: PerfDocument) -> None:
        self.document = document
        self._build()

    # -- newly laid copper -------------------------------------------------

    def reveal_conductors(self, ids: Sequence[str]) -> None:
        """Fade the copper ``ids`` names in, one conductor after another, in that order.

        What an Auto-wire laid then reads as laid, in the planner's order, rather than
        appearing all at once. The whole thing is short (``REVEAL_SPAN_MS`` at most, however
        many conductors), and it is decoration only: every conductor is in the document,
        hit-testable and selectable from the first frame, and with motion reduced or the
        view hidden nothing fades at all.

        Kept by id, not by item: a rebuild in the middle (every command makes one) draws
        the new items at the opacity the reveal has reached, so it neither restarts nor
        touches an item ``clear()`` destroyed.
        """
        self.stop_reveal()
        present = tuple(cid for cid in ids if cid in self.conductor_items)
        if not present or not any(view.isVisible() for view in self.views()):
            return
        count = len(present)
        step = (
            min(REVEAL_STEP_MS, (REVEAL_SPAN_MS - REVEAL_FADE_MS) / (count - 1))
            if count > 1
            else 0.0
        )
        total = motion.duration(round(REVEAL_FADE_MS + step * (count - 1)))
        if total <= 0:
            return
        self._reveal_ids = present
        self._reveal_step_ms = step
        anim = QVariantAnimation(self)
        anim.setDuration(total)
        anim.setStartValue(0.0)
        anim.setEndValue(float(total))
        anim.valueChanged.connect(lambda value: self._reveal_at(float(cast(float, value))))
        anim.finished.connect(self.stop_reveal)
        self._reveal = anim
        self._reveal_at(0.0)
        anim.start()

    @property
    def revealing(self) -> bool:
        """True while newly laid copper is still fading in."""
        return self._reveal is not None

    def _reveal_at(self, elapsed_ms: float) -> None:
        for index, conductor_id in enumerate(self._reveal_ids):
            item = self.conductor_items.get(conductor_id)
            if item is None:
                continue
            local = (elapsed_ms - index * self._reveal_step_ms) / REVEAL_FADE_MS
            local = min(1.0, max(0.0, local))
            item.setOpacity(1.0 - (1.0 - local) ** 3)

    def stop_reveal(self) -> None:
        """Show every conductor the reveal was fading in at full strength, at once."""
        anim, self._reveal = self._reveal, None
        if anim is not None:
            anim.stop()
            anim.deleteLater()
        for conductor_id in self._reveal_ids:
            item = self.conductor_items.get(conductor_id)
            if item is not None:
                item.setOpacity(1.0)
        self._reveal_ids = ()

    def set_side(self, side: BoardSide) -> None:
        """Look at the board from ``side``. What is drawn next goes on that face too: a flip
        is the builder saying which face they mean, and undoes a Draw on override."""
        if side != self.side:
            self.side = side
            self._build()
        self.set_draw_face(side)

    def set_show_ratsnest(self, show: bool) -> None:
        if show != self.show_ratsnest:
            self.show_ratsnest = show
            self._rebuild_ratsnest()

    def set_show_far_side(self, show: bool) -> None:
        """Whether copper on the face away from the viewer is drawn through the board.

        A full rebuild rather than an item-by-item update: the flag is read when each
        ConductorItem is built, and one source of truth for "what is in this scene" is worth
        more than saving a rebuild nobody is waiting on.
        """
        if show != self.show_far_side:
            self.show_far_side = show
            self._build()

    def _add_off_board_things(
        self, net_by_pin: Mapping[tuple[str, str], Net], colour_names: Mapping[str, str]
    ) -> None:
        """The thing each part off the board is, beside the board, and room to see it.

        Its wires are coloured as the part's own are -- the net's, by the cut list's name
        for it -- and the scene grows to hold every thing, so a fit frames the board and
        what hangs off it, and a thing dragged further out can still be scrolled to.
        """

        def colour_of(comp: ComponentInstance, pin: str) -> QColor:
            net = net_by_pin.get((comp.ref, pin))
            if net is None:
                return CONDUCTOR_STYLE["insulated-wire"][0]
            return _INSULATION_SCREEN.get(
                colour_names.get(net.id, "grey"), CONDUCTOR_STYLE["insulated-wire"][0]
            )

        board = self.document.board
        things = things_for(
            self.document,
            self.lookup,
            colour_of,
            self.component_items,
            _outline_rect(board),
            self._note_off_board_drop,
        )
        rect = self.sceneRect()
        for thing in things:
            self.addItem(thing)
            self.off_board_items[thing.comp.id] = thing
            owner = self.component_items.get(thing.comp.id)
            if owner is not None:
                owner.leads_carry_on = True
            rect = rect.united(thing.sceneBoundingRect().adjusted(-6.0, -6.0, 6.0, 6.0))
        self.setSceneRect(rect)

    def _note_off_board_drop(self, comp_id: str, at: Point2) -> None:
        self._off_board_drop = (comp_id, at)

    def commit_off_board_drop(self) -> DispatchResult | None:
        """Dispatch ``component.placeOffBoard`` for the thing just let go, if one was.

        Called after the release has been delivered, never from the item's own handler: the
        command rebuilds the scene, which destroys the item."""
        drop, self._off_board_drop = self._off_board_drop, None
        if drop is None or self.bus is None:
            return None
        comp_id, at = drop
        current = next((c for c in self.document.components if c.id == comp_id), None)
        if current is None or current.off_board_at == at:
            # Let go where it already was: nothing to do, and nothing to say -- a refusal
            # would reach the status line as an error for an ordinary click.
            return None
        result = self.bus.dispatch("component.placeOffBoard", PlaceOffBoardPayload(id=comp_id, at=at))
        self.moveCommitted.emit([result])
        return result

    def set_show_off_board(self, show: bool) -> None:
        """Draw what each part off the board is, beside the board, or only its wires."""
        if show != self.show_off_board:
            self.show_off_board = show
            self._build()

    def set_show_board_notes(self, show: bool) -> None:
        """Draw the labels written on the board, or not."""
        if show != self.show_board_notes:
            self.show_board_notes = show
            self._build()

    def selected_mount_ids(self) -> tuple[str, ...]:
        return tuple(mount_id for mount_id, item in self.mount_items.items() if item.isSelected())

    def selected_connector_ids(self) -> tuple[str, ...]:
        return tuple(
            connector_id for connector_id, item in self.connector_items.items()
            if item.isSelected()
        )

    def selected_board_note_ids(self) -> tuple[str, ...]:
        return tuple(
            note_id for note_id, item in self.board_note_items.items() if item.isSelected()
        )

    def board_note_at(self, pos: QPointF) -> BoardNoteItem | None:
        """The label under a scene position, if any -- asked before the parts, because a
        label is drawn over them."""
        for item in self.board_note_items.values():
            if item.shape().contains(item.mapFromScene(pos)):
                return item
        return None

    def board_point(self, pos: QPointF) -> tuple[HoleCoord, float, float]:
        """A scene position as a label addresses a place: the nearest hole and an offset."""
        x = pos.x()
        if self.side == "bottom":
            span_w, _span_h = hole_span_mm(self.document.board)
            x = span_w - x
        return board_note_anchor(x, pos.y(), self.document.board)

    def set_show_pin_names(self, show: bool) -> None:
        """Print parts' pin names beside their pins, or not. Off for a dense board being
        placed or routed, where they are clutter; on for wiring and for the printout."""
        if show != self.show_pin_names:
            self.show_pin_names = show
            self._build()

    def set_show_values(self, show: bool) -> None:
        """Print each part's value after its reference, or not. Nothing to rebuild: the
        reference layer reads it as it paints, and each part's hit area as it is asked."""
        if show == self.show_values:
            return
        self.show_values = show
        for item in self.component_items.values():
            item.prepareGeometryChange()
        if self.reference_layer is not None:
            self.reference_layer.update()
        self.update()

    def set_show_net_names(self, show: bool) -> None:
        """Write the nets' names on the wires, or not. Nothing to rebuild: the layer reads
        the setting as it paints."""
        if show == self.show_net_names:
            return
        self.show_net_names = show
        if self.net_name_layer is not None:
            self.net_name_layer.update()

    def set_show_rulers(self, show: bool) -> None:
        if show != self.show_rulers:
            self.show_rulers = show
            self._build()

    def legend_is_readable(self) -> bool:
        """Whether the board's own printed addresses can be read from the side in view.

        Public because the host greys out "Show Hole Addresses" when this is true: the
        ruler is suppressed then (see ``_build``), and a menu item that silently does
        nothing is worse than one that is visibly unavailable.
        """
        if has_breadboard_pattern(self.document.board):
            # It prints its own addresses -- "e12" -- on the face a builder reads it from,
            # and a grid ruler of A, B, C beside them would name the holes a second way.
            # So does a solderable one, in silkscreen.
            return self.side == "top"
        labels = self.document.board.labels
        # A board printing its OWN numbering (A..Z and then A..P again) is not printing
        # the addresses, so the ruler is then the one thing on screen that says them.
        return (
            labels is not None
            and labels.face in ("both", self.side)
            and labels.columns is None
            and labels.rows is None
        )

    def set_highlighted_nets(self, net_ids: Sequence[str]) -> None:
        """Light up the given schematic nets: what is left to route, and the copper laid.

        The copper half is new. Selecting a net used to light only its ratsnest, so on a
        finished board -- no ratsnest left -- choosing GND in the Nets panel changed nothing
        anyone could see, and the one question it exists to answer, "where does this net
        go", had no answer on the board.
        """
        wanted = tuple(net_ids)
        if wanted != self.highlighted_nets:
            self.highlighted_nets = wanted
            self._rebuild_ratsnest()
            self._light_net_copper()

    def _light_net_copper(self) -> None:
        lit = self._conductors_on(self.highlighted_nets)
        for conductor_id, item in self.conductor_items.items():
            item.set_net_lit(conductor_id in lit)

    def _conductors_on(self, net_ids: Sequence[str]) -> set[str]:
        """Every conductor electrically on one of these schematic nets.

        Judged by the PHYSICAL net -- what the copper actually joins, from connectivity --
        rather than by ``net_id``: a hand-drawn wire carries no net id, and it is exactly
        the copper somebody selecting a net wants to find. A conductor that names the net
        but touches none of its pins is lit as well, since that is what it claims to be.
        """
        if not net_ids:
            return set()
        wanted = set(net_ids)
        nodes = {
            (node.component_ref, node.pin)
            for net in self.document.nets
            if net.id in wanted
            for node in net.nodes
        }
        if self._physical_nets is None or self._physical_nets[0] is not self.document:
            self._physical_nets = (self.document, extract_physical_nets(self.document, self.lookup))
        lit = {
            conductor.id for conductor in self.document.conductors if conductor.net_id in wanted
        }
        for physical in self._physical_nets[1]:
            if any((pin.component_ref, pin.pin) in nodes for pin in physical.pins):
                lit.update(physical.conductor_ids)
        return lit

    def _build(self) -> None:
        # Selection survives a rebuild. Every command triggers one, so without this a part
        # is deselected the instant it is acted on -- pressing R twice would rotate once and
        # then do nothing, which reads as the key having stopped working.
        previously_selected = {
            comp_id for comp_id, item in self.component_items.items() if item.isSelected()
        }
        # Conductors too: a trace selected to be deleted must still be selected after the
        # unrelated command that rebuilt the scene, or Delete acts on nothing.
        previously_selected_conductors = set(self.selected_conductor_ids())
        # The dict is emptied BEFORE clear(), not after. clear() destroys the underlying C++
        # items and Qt emits selectionChanged while doing so, which reaches
        # _on_selection_changed -- and if that handler can still see the old dict, it touches
        # wrappers whose C++ object is gone and raises "Internal C++ object already deleted".
        # Emptying first means the handler sees an empty selection, which is the truth.
        self.component_items = {}
        self.conductor_items = {}
        self.off_board_items = {}
        # Handles and a handle's drag go with the items clear() destroys; the handles are
        # made again below from the selection, and a drag the rebuild interrupted is over.
        self._handles = []
        self._reshape = None
        self._reshape_path = None
        self._reshape_preview = None
        self._reshape_slide = None
        # Dropped with the dict, for the same reason: a part selected while clear() runs
        # tells the layer to repaint, and the layer is one of the items being destroyed.
        self.reference_layer = None
        self.lead_ends_layer = None
        self.net_name_layer = None
        previously_selected_notes = {
            note_id for note_id, note_item in self.board_note_items.items() if note_item.isSelected()
        }
        self.board_note_items = {}
        # Every grid position a lead cannot be fitted into: a mounting bore has taken the
        # pad, a finger was never drilled, a cut took the pad with it. Computed once per
        # rebuild because the placement ghost asks about it on every mouse move.
        self._unusable_holes = (
            consumed_holes(self.document)
            | undrilled_holes(self.document)
            | cut_holes(self.document)
            | holeless_positions(self.document.board)
        )
        self.finger_cells = finger_cells(self.document)
        self.clear()
        self._risk_item = None
        self._bench_item = None
        self._focus_item = None
        self._before_item = None
        self._ratsnest_item = None
        self._ghost = None
        # Destroyed with the rest and not re-created: the next drag move draws it again.
        self._drop_ghost = None
        self._draw_preview = None
        # The pin markers are RE-created rather than merely forgotten, because a rebuild
        # happens on every command and the mode survives one: a half-collected net whose
        # picks vanished off the board reads as the clicks having been lost.
        self._net_pin_item = None
        self._connect_item = None
        # Destroyed with the rest; the next hover makes it again where the pointer is.
        self._pin_hover = None
        # The measurement marker is an item like the rest, so clear() has just destroyed
        # it. Forgetting to forget it here left a wrapper whose C++ object was gone, and
        # the next Escape -- or the next arming of ANY tool, all of which disarm
        # measuring first -- raised from removeItem and left every tool unreachable.
        self._measure_item = None
        board = self.document.board
        outline = _outline_rect(board)
        # Room outside the substrate is reserved for the ruler, so it is only needed when
        # one is actually going to be drawn -- see the note beside HoleRulerItem below.
        margin = RULER_MARGIN_MM if (self.show_rulers and not self.legend_is_readable()) else 4.0
        self.setSceneRect(
            outline.left() - margin,
            outline.top() - margin,
            outline.width() + margin + 4,
            outline.height() + margin + 4,
        )
        self.setBackgroundBrush(QBrush(BACKGROUND))

        scheme = scheme_for(board)
        breadboard = is_breadboard(board)
        substrate = self.addRect(
            outline,
            QPen(QColor(BREADBOARD.edge if breadboard else scheme.edge), 0.4),
            QBrush(QColor(BREADBOARD.body if breadboard else scheme.fill)),
        )
        substrate.setZValue(-100)

        # A breadboard is plastic with holes and print, and none of the copper below: no
        # pads, no strips, no legend, no fingers or bores (commands refuse those on one).
        self.pad_grid = None
        if breadboard:
            self.breadboard_item = BreadboardItem(board, self.side)
            self.addItem(self.breadboard_item)
        else:
            self.breadboard_item = None

        # Ink first, then copper on top of it: the legend is printed on the substrate and
        # a pad sits over the print, which is also the order that keeps a label legible
        # where it passes close to the outer row of pads.
        self.legend_item = None
        if board.labels is not None and not breadboard:
            self.legend_item = BoardLegendItem(self.document, board.labels, self.side)
            self.addItem(self.legend_item)
        if board.printed and not breadboard:
            self.addItem(BoardTextItem(self.document, self.side))

        # A single-sided board has copper on the solder side ONLY. From the component
        # side you are looking at bare phenolic with holes drilled through it -- the holes
        # are still all there, and drawing neither them nor the pads would leave a blank
        # slab that says nothing about where anything goes.
        # `undrilled_holes` on top of the face-sensitive set, and unconditionally: a
        # finger has no bore, so its position gets neither a pad NOR a hole, on either
        # face. Without it the component side of a board whose fingers are on the solder
        # side shows a drilled hole where the board is solid.
        # The board's own copper goes UNDER the pads, because that is the order the
        # physical board is made in: the strip is etched and the holes are drilled
        # through it. Cut holes join the no-pad set for the same reason a mounting bore
        # does -- the copper there was drilled away, and drawing a pad on it would offer
        # something to solder to that is not there.
        strips = StripGridItem(self.document, self.side)
        if strips.has_strips:
            self.addItem(strips)
        if is_solderable_breadboard(board):
            # The breadboard's print, in the board's own silkscreen ink: its strips are the
            # StripGridItem above, its pads the PadGridItem below, as on any copper board.
            self.addItem(BreadboardPrintItem(board, self.side, scheme.silk))
        if not breadboard:
            # ``holeless_positions`` is empty on every board but a breadboard's pattern,
            # where it is the channel, the strips beside the rails and the columns a rail
            # leaves out: no hole there, so no pad either.
            self.pad_grid = PadGridItem(
                board,
                self.side,
                holes_without_grid_pad(self.document, self.side)
                | undrilled_holes(self.document)
                | cut_holes(self.document)
                | holeless_positions(board),
                copper=not (board.single_sided and self.side == "top"),
            )
            self.addItem(self.pad_grid)
        for cut in self.document.cuts:
            if is_stripboard(board):
                self.addItem(TrackCutItem(cut, board, self.side))

        self.connector_items = {}
        for connector in self.document.edge_connectors:
            self.connector_items[connector.id] = EdgeConnectorItem(
                connector, self.document, self.side
            )
            self.connector_items[connector.id].setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True
            )
            self.addItem(self.connector_items[connector.id])
        self.mount_items = {}
        for mount in self.document.mounting_holes:
            self.mount_items[mount.id] = MountingHoleItem(mount, board, self.side)
            self.addItem(self.mount_items[mount.id])

        # THE RULER STANDS DOWN WHEN THE BOARD SPEAKS FOR ITSELF. The ruler exists to name
        # a hole on a board that carries no addresses of its own; drawing it alongside a
        # printed legend puts the same twenty-four letters on screen twice, a few
        # millimetres apart and in two different styles, which reads as a rendering fault
        # rather than as two features. Only when the legend is on the far face -- where it
        # is a dim ghost rather than something you can read -- is the ruler wanted again.
        self.legend_echo = None
        if self.show_rulers and not self.legend_is_readable():
            self.addItem(HoleRulerItem(board, self.side))
        elif self.show_rulers and self.legend_item is not None:
            # ...except for an address something stands on: see LegendEchoItem.
            self.legend_echo = LegendEchoItem(self, self.legend_item)
            self.addItem(self.legend_echo)

        net_class_by_id = {net.id: net.net_class for net in self.document.nets}
        net_name_by_id = {net.id: net.name for net in self.document.nets}
        # The cut list's own count, in the saved file's net order: see
        # guide.signal_colour_index for the board that changed colour when reopened.
        signal_index = signal_colour_index(self.document)
        # From the engine, so the wire drawn passing over another here is the one drawn
        # passing over it in 3D. See occupancy.stacking_layers.
        conductor_layers = stacking_layers(self.document, lookup=self.lookup)
        for conductor in self.document.conductors:
            conductor_item = ConductorItem(
                conductor,
                board,
                self.side,
                net_class=net_class_by_id.get(conductor.net_id or ""),
                signal_index=signal_index.get(conductor.net_id or "", 0),
                show_far_side=self.show_far_side,
                stack=conductor_layers.get(conductor.id, conductor.layer_z),
                net_name=net_name_by_id.get(conductor.net_id or ""),
                cells=self.finger_cells,
            )
            self.addItem(conductor_item)
            self.conductor_items[conductor.id] = conductor_item
            if conductor.id in previously_selected_conductors:
                conductor_item.setSelected(True)
        if self._reveal is not None:
            # A rebuild while copper fades in: the new items pick up where the old left off.
            current = self._reveal.currentValue()
            self._reveal_at(float(cast(float, current)) if current is not None else 0.0)
        self._light_net_copper()
        self.via_items = []
        if self.show_vias:
            for hole in self._via_holes():
                mark = ViaMarkItem(hole, board, self.side, self.finger_cells)
                self.addItem(mark)
                self.via_items.append(mark)
        self.net_name_layer = NetNameLayerItem(self)
        self.addItem(self.net_name_layer)

        # Laid out for the whole board at once: where one part's names go depends on what
        # stands beside it. See bodies.lay_out_pin_names.
        names = lay_out_pin_names(self.document, self.lookup, pin_name_width_mm)
        self.reference_layer = ReferenceLayerItem(self)
        self.addItem(self.reference_layer)
        if self.side == "bottom":
            self.lead_ends_layer = LeadEndsLayerItem(self)
            self.addItem(self.lead_ends_layer)
        net_by_pin = {
            (node.component_ref, node.pin): net for net in self.document.nets for node in net.nodes
        }
        colour_names = net_colours(self.document)
        for comp in self.document.components:
            fp = self.lookup(comp.footprint_id)
            if fp is None:
                continue
            lead_colours: dict[str, QColor] = {}
            lead_wires: dict[str, tuple[str, str]] = {}
            if fp.body.archetype == "flying-leads":
                for pin in fp.pins:
                    net = net_by_pin.get((comp.ref, pin.number))
                    if net is not None:
                        # By NAME, from the guide's own assignment: the colour a wire is
                        # drawn in and the colour its tooltip calls it are the cut list's.
                        name = colour_names.get(net.id, "grey")
                        lead_colours[pin.number] = _INSULATION_SCREEN.get(
                            name, CONDUCTOR_STYLE["insulated-wire"][0]
                        )
                        lead_wires[pin.number] = (net.name, name)
            item = ComponentItem(
                comp,
                fp,
                board,
                self.side,
                self.show_pin_names,
                pin_names=names.labels.get(comp.id, ()),
                names_left_off=names.left_off.get(comp.id, ()),
                lead_colours=lead_colours,
                lead_wires=lead_wires,
            )
            item.show_reference = self.show_references
            self.addItem(item)
            self.component_items[comp.id] = item
            if comp.id in previously_selected:
                item.setSelected(True)
        if self.show_off_board and self.side == "top":
            self._add_off_board_things(net_by_pin, colour_names)

        # Labels last, over everything: they are written on top of what they are about.
        # Only the face in view -- a label on the far side is on the far side.
        if self.show_board_notes:
            for note in self.document.board_notes:
                if note.side != self.side:
                    continue
                note_item = BoardNoteItem(note, board, self.side)
                self.addItem(note_item)
                self.board_note_items[note.id] = note_item
                if note.id in previously_selected_notes:
                    note_item.setSelected(True)

        # Recomputed on every rebuild rather than cached across one: a rebuild follows a
        # committed command, which is exactly when what remains to be connected changes.
        self._ratsnest_links = ratsnest_lines(self.document, self.lookup)
        self._rebuild_ratsnest()
        self._apply_violations()
        # The ghost is an item like any other, so the rebuild above removed it. Placement is a
        # mode that survives placing a part -- you usually want several -- so it comes back.
        if self._armed_footprint is not None:
            self._ghost = PlacementGhostItem(
                self._armed_footprint,
                board,
                self.side,
                self._armed_rotation,
                self._armed_mirrored,
            )
            self.addItem(self._ghost)
            # Back under the pointer, not at A1: a fresh ghost starts at the origin, and
            # placing a part is exactly the moment the next one is being lined up.
            if self._last_hole is not None:
                self._ghost.set_anchor(self._last_hole, self._placement_blocked(self._last_hole))
        # The half-drawn conductor survives a rebuild in the same way the picked pins do:
        # the path is state, the preview is only its picture, and a flip or an undo in the
        # middle of a trace must not leave the tool armed with nothing on the board.
        if self._draw_kind is not None:
            self._draw_preview = DrawPreviewItem(self._draw_kind, board, self.side)
            self.addItem(self._draw_preview)
            self._refresh_draw_preview(self._last_hole)
        self._sync_handles()
        if self._measure_from is not None:
            self._measure_item = PickedPinsItem(board, self.side)
            self._measure_item.set_holes([self._measure_from])
            self.addItem(self._measure_item)
        if self._net_pin_target is not None:
            self._net_pin_item = PickedPinsItem(board, self.side)
            self._net_pin_item.set_holes(self._net_pin_holes)
            self.addItem(self._net_pin_item)
        if self._connect_first is not None and self._connect_hole is not None:
            self._connect_item = PickedPinsItem(board, self.side)
            self._connect_item.set_holes([self._connect_hole])
            self.addItem(self._connect_item)
        # Re-created, as the markers above are: clear() destroyed the last one.
        self._refresh_before()

    # -- the wiring before --------------------------------------------------

    def set_before_copper(self, conductors: Sequence[Conductor]) -> None:
        """Draw ``conductors`` -- the copper before the last Auto-wire or Redo Wiring --
        dashed over the copper there now; nothing to stop. Ctrl+Z was the only way to see
        what a route had changed, and it took the new wiring away to show it."""
        self._before_copper = tuple(conductors)
        self._refresh_before()

    @property
    def showing_before(self) -> bool:
        return bool(self._before_copper)

    def _refresh_before(self) -> None:
        if self._before_item is not None:
            self.removeItem(self._before_item)
            self._before_item = None
        if not self._before_copper or self.document is None:
            return
        board = self.document.board
        # ``_before_copper`` is frozen to what the last route replaced (``gone_copper``):
        # later manual deletions never enter it, and filtering out shapes that are back in
        # the current document keeps Ctrl+Z from leaving dashes over restored copper while
        # letting Ctrl+Y bring the route's ghosts straight back.
        shown = gone_copper(self._before_copper, self.document.conductors)
        if not shown:
            return
        outline = QPainterPath()
        for conductor in shown:
            points = [hole_to_screen(hole, board, self.side) for hole in conductor.path]
            if len(points) < 2:
                continue
            outline.moveTo(points[0])
            for point in points[1:]:
                outline.lineTo(point)
        item = QGraphicsPathItem(outline)
        pen = QPen(BEFORE_COPPER, board.pitch * 0.14)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        item.setPen(pen)
        item.setZValue(BEFORE_COPPER_Z)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setAcceptHoverEvents(False)
        self.addItem(item)
        self._before_item = item

    # -- ratsnest -----------------------------------------------------------

    def _rebuild_ratsnest(self) -> None:
        if self._ratsnest_item is not None:
            self.removeItem(self._ratsnest_item)
            self._ratsnest_item = None
        if not self.show_ratsnest or not self._ratsnest_links:
            return
        self._ratsnest_item = RatsnestItem(
            self._ratsnest_links, self.document.board, self.side, self.highlighted_nets
        )
        self.addItem(self._ratsnest_item)

    def ratsnest_links(self) -> tuple[RatsnestLine, ...]:
        """What the scene is currently drawing as outstanding, for a status readout."""
        return self._ratsnest_links

    # -- DRC overlay --------------------------------------------------------

    def set_focused_holes(self, holes: Sequence[HoleCoord]) -> None:
        """The holes of the finding picked or hovered in the Problems drawer, or none.

        A bench check's rings are under the parts and dim (``BENCH_RING``), which is right
        for a finding that is not a problem and wrong for one somebody has just asked to
        see: going to it must still show exactly which two pads. So those of its holes that
        a bench check rings come up over the parts in ``RISK_RING`` while it is picked. A
        problem's rings are already on top, so nothing else changes.
        """
        self._focused_holes = tuple(holes)
        self._refresh_focus()

    def _refresh_focus(self) -> None:
        focus = [h for h in self._focused_holes if (h.col, h.row) in self._bench_holes]
        self._focus_item = self._rings(self._focus_item, focus, RISK_RING, RISK_RING_Z)

    def _rings(
        self,
        item: RiskRingsItem | None,
        holes: Sequence[HoleCoord],
        colour: QColor,
        z: float,
    ) -> RiskRingsItem | None:
        """``item`` replaced by rings on ``holes``, or by nothing where there are none."""
        if item is not None:
            self.removeItem(item)
        if not holes:
            return None
        rings = RiskRingsItem(holes, self.document.board, self.side, colour, z)
        self.addItem(rings)
        return rings

    def set_violations(self, violations: Sequence[DrcViolation]) -> None:
        self.violations = tuple(violations)
        self._apply_violations()

    def refresh_theme(self) -> None:
        """Apply the active theme's canvas, ruler and bench-ring colours and repaint."""
        self.setBackgroundBrush(QBrush(BACKGROUND))
        if self._bench_item is not None:
            self._apply_violations()
        self.update()

    def _apply_violations(self) -> None:
        risk_holes: list[HoleCoord] = []
        bench_holes: list[HoleCoord] = []
        error_component_ids: set[str] = set()
        for v in self.violations:
            if v.rule == "solder-trace-proximity":
                # The drawer's own predicate, so the two cannot disagree about which is which.
                (bench_holes if is_bench_check(v) else risk_holes).extend(v.holes)
            if v.severity == "error":
                error_component_ids.update(v.component_ids)

        self._risk_item = self._rings(self._risk_item, risk_holes, RISK_RING, RISK_RING_Z)
        self._bench_item = self._rings(self._bench_item, bench_holes, BENCH_RING, BENCH_RING_Z)
        self._bench_holes = frozenset((hole.col, hole.row) for hole in bench_holes)
        self._refresh_focus()

        for comp_id, item in self.component_items.items():
            item.set_error(comp_id in error_component_ids)

        # A screw hole shows the ring its head will cover while DRC says something is in it.
        crowded = {
            (hole.col, hole.row)
            for v in self.violations
            if v.rule in ("mounting-hole-clearance", "mounting-hole-conflict")
            for hole in v.holes
        }
        for mount_item in self.mount_items.values():
            mount_item.set_flagged((mount_item.mount.at.col, mount_item.mount.at.row) in crowded)

    def set_finding_notes(self, holes: Mapping[HoleCoord, str], parts: Mapping[str, str]) -> None:
        """What a ring and a part drawn in error say when the pointer rests on them, made
        by the window (``MainWindow._finding_notes``) in its words. The rings and the red
        tint said only that something was wrong; what, and what to do, was a row in a
        drawer that might be closed, found by reading the list (Sinan's dev4 walk)."""
        self._finding_holes = {(hole.col, hole.row): note for hole, note in holes.items()}
        self._finding_parts = dict(parts)

    def _finding_part_at(self, pos: QPointF) -> ComponentItem | None:
        """The part under ``pos`` that a finding draws in error -- the topmost part only,
        so a finding about the part underneath is not said over another one."""
        for item in self.items(pos):
            if isinstance(item, ComponentItem):
                return item if item.comp.id in self._finding_parts else None
        return None

    def finding_tip_at(self, pos: QPointF) -> str:
        """The tooltip a finding gives at ``pos``, or ``""`` where none is marked."""
        at = screen_to_hole(pos, self.document.board, self.side)
        note = self._finding_holes.get((at.col, at.row))
        if note:
            return note
        part = self._finding_part_at(pos)
        if part is None:
            return ""
        own = html.escape(part.toolTip()).replace("\n", "<br>")
        return f"{self._finding_parts[part.comp.id]}<hr>{own}"

    def helpEvent(self, event: Any) -> None:
        tip = self.finding_tip_at(event.scenePos())
        if not tip:
            super().helpEvent(event)
            return
        QToolTip.showText(event.screenPos(), tip, event.widget())
        event.accept()

    def pick_finding_at(self, pos: QPointF) -> str:
        """Say which finding a plain click at ``pos`` landed on (``findingPicked``):
        ``"ring"`` for a ringed hole, whose click is the finding's -- the window selects
        what its row selects, and the press goes no further -- ``"part"`` for a part drawn
        in error, whose click goes on to select or drag the part, or ``""``."""
        at = screen_to_hole(pos, self.document.board, self.side)
        if (at.col, at.row) in self._finding_holes:
            self.findingPicked.emit(at)
            return "ring"
        part = self._finding_part_at(pos)
        if part is not None:
            self.findingPicked.emit(part.comp.id)
            return "part"
        return ""

    # -- selection helpers, used by the DRC/LVS dock -------------------------

    def select_components(self, component_ids: Sequence[str]) -> None:
        wanted = set(component_ids)
        for comp_id, item in self.component_items.items():
            item.setSelected(comp_id in wanted)

    def select_all(self) -> None:
        """Every part on the board (Edit > Select All). Parts and not their copper: what a
        selection of everything is for is moving, turning or locking the parts, and none of
        that carries a trace with it."""
        self.select_components(list(self.component_items))

    def __del__(self) -> None:
        """A scene going away says nothing on the way out.

        Its own destructor clears its items, and clearing a SELECTED item emits
        ``selectionChanged`` -- into ``_on_selection_changed``, on the very object Python is
        half way through tearing down. That raised "Slot 'BoardScene::' not found" in the
        event loop of whatever test happened to be running when the collector got round to
        a scene an earlier one left behind: test_theme, after test_canvas_gestures and
        test_i18n, three runs in four. Safe because a scene has no Qt parent (its
        ``__init__`` passes none), so Python owns it and this runs only as it is destroyed.
        """
        # RuntimeError: the C++ side is already gone, and there is nothing left to emit.
        with contextlib.suppress(RuntimeError):
            self.blockSignals(True)

    def _on_selection_changed(self) -> None:
        """Selecting a part highlights every net it belongs to.

        And one conductor selected gets its handles (``_sync_handles``).

        This is the question a user asks constantly while placing -- "what is this still
        supposed to reach?" -- and the ratsnest already knows. The scene only reports the
        net ids; what to do with them is the host's business.
        """
        self._sync_handles()
        for thing in self.off_board_items.values():
            thing.update()
        selected_refs = {
            item.comp.ref for item in self.component_items.values() if item.isSelected()
        }
        if not selected_refs:
            self.set_highlighted_nets(())
            self.selectionNetsChanged.emit([])
            return
        net_ids = [
            net.id
            for net in self.document.nets
            if any(node.component_ref in selected_refs for node in net.nodes)
        ]
        self.set_highlighted_nets(net_ids)
        self.selectionNetsChanged.emit(net_ids)

    def selected_component_ids(self) -> tuple[str, ...]:
        return tuple(
            comp_id for comp_id, item in self.component_items.items() if item.isSelected()
        )

    # -- dragging: dispatch on release, never per-frame ----------------------

    # -- placing a new part -------------------------------------------------
    #
    # Nothing in this application could add a component at all: the registry has sixty-one
    # footprints and `component.place` has existed since the first commit, with no way to reach
    # either. Placement is a MODE rather than a dialog because the position is the decision --
    # you aim it on the grid, and the ghost shows the holes it will take before you commit.

    #: Emitted with the DispatchResult of a placement attempt, successful or refused.
    componentPlaced = Signal(object)
    #: Emitted with the armed footprint id, or an empty string when placement is cancelled.
    placementArmed = Signal(str)
    #: Emitted with the id of a part that was double-clicked. What the host does about it
    #: (open its properties) is the host's business; the scene only reports the gesture.
    componentActivated = Signal(str)
    #: A label on the board was double-clicked. Carries its id; the host opens it.
    boardNoteActivated = Signal(str)

    # -- drawing conductors by hand ------------------------------------------
    #
    # The engine has had conductor.add since the first commit and nothing in the window
    # could reach it, so on a perfboard tool there was no way to run a wire or lay a
    # solder trace yourself -- only to accept whatever the router produced or throw the
    # whole thing away.

    #: Kinds that are exactly two holes: click a start, click an end, done. A top jumper is
    #: one straight piece of wire bent over the parts.
    _TWO_POINT_KINDS: frozenset[ConductorKind] = frozenset({"top-jumper"})
    #: Kinds drawn in RUNS: a click is where the copper turns, and every pad between it
    #: and the last click is soldered on the way. A trace had to be clicked pad by pad --
    #: seven clicks for seven holes -- and a click two holes away was silently ignored.
    _RUN_KINDS: frozenset[ConductorKind] = frozenset({"solder-trace", "solder-trace-wired"})
    #: Wires under the board, drawn with CORNERS ON THE GRID as the router lays them: a
    #: click is where it turns, and Enter, a right-click or a double-click ends it. They
    #: were two clicks and one straight line at any angle, so a hand wire could not follow
    #: the path a routed one does, and a third click for a bend was lost.
    _WIRE_KINDS: frozenset[ConductorKind] = frozenset({"bare-wire", "insulated-wire"})
    #: Everything that turns corners: ``/`` flips the next one, and a click on the last hole
    #: again finishes.
    _CORNER_KINDS: frozenset[ConductorKind] = _RUN_KINDS | _WIRE_KINDS

    def arm_drawing(self, kind: ConductorKind | None) -> None:
        """Arm (or, with None, disarm) drawing a conductor of this kind."""
        self._clear_draw()
        self._draw_kind = kind
        if kind is not None:
            self.arm_placement(None)  # The board modes are mutually exclusive.
            self._disarm_net_pins()
            self._disarm_connect()
            self._disarm_measure()
            self._disarm_cutting()
            self._draw_preview = DrawPreviewItem(kind, self.document.board, self.side)
            self.addItem(self._draw_preview)
        self.drawArmed.emit(kind or "")

    @property
    def armed_draw_kind(self) -> ConductorKind | None:
        return self._draw_kind

    @property
    def solder_draw_face(self) -> BoardSide:
        """The face a hand-drawn solder run goes on: ``draw_face`` -- the face in view, or
        the Draw on choice -- where the board has pads on the component side, the solder
        side everywhere else."""
        if has_component_side_copper(self.document.board):
            return self.draw_face
        return "bottom"

    def drawing_as(self, kind: ConductorKind) -> tuple[ConductorKind, BoardSide]:
        """What the tool for ``kind`` lays now, and on which face (``drawcheck.drawn_as``)."""
        return drawn_as(kind, self.document.board, self.draw_face)

    def set_draw_face(self, face: BoardSide) -> None:
        """Choose the face the hand tools draw on. Copper half drawn carries on, on the new
        face -- every step is checked again as it is drawn -- unless it was carrying on a run
        from its end: that run is on the old face, so drawing starts again."""
        if face == self.draw_face:
            return
        kind = self._draw_kind
        before = self.drawing_as(kind) if kind is not None else None
        self.draw_face = face
        if kind is not None and self._draw_continuing is not None and self.drawing_as(kind) != before:
            self.arm_drawing(kind)

    @property
    def drawn_path(self) -> tuple[HoleCoord, ...]:
        """The holes of the conductor being drawn, clicked so far."""
        return tuple(self._draw_path)

    @property
    def drawn_ahead(self) -> tuple[HoleCoord, ...]:
        """The holes Enter or the next click would lay: the path and the step to the
        pointer, when that step is one the tool would take."""
        return self._draw_ahead

    @property
    def continuing(self) -> str | None:
        """The id of the run being drawn on from its end, or None."""
        return self._draw_continuing

    @property
    def reshaping(self) -> bool:
        """Whether a handle of the selected conductor is being dragged."""
        return self._reshape is not None

    def check_drawing(self, path: Sequence[HoleCoord]) -> DrawCheck | None:
        """What laying the armed kind along ``path`` would do, from the engine's own
        predicates (``drawcheck``); None with nothing armed or under two holes."""
        if self._draw_kind is None or len(path) < 2:
            return None
        laid, face = self.drawing_as(self._draw_kind)
        kind = f"{laid}|{self._draw_continuing or ''}|{face}"
        holes = tuple(path)
        cached = self._draw_checked
        if (
            cached is not None
            and cached[0] is self.document
            and cached[1] == kind
            and cached[2] == holes
        ):
            return cached[3]
        checked = check_drawn(
            self.document,
            self.lookup,
            laid,
            holes,
            ignoring=self._draw_continuing,
            side=face,
        )
        self._draw_checked = (self.document, kind, holes, checked)
        return checked

    def _clear_draw(self) -> None:
        if self._draw_preview is not None:
            self.removeItem(self._draw_preview)
            self._draw_preview = None
        if self._pin_hover is not None:
            self._pin_hover.set_hole(None)
        self._draw_path = []
        self._draw_kind = None
        self._draw_column_first = False
        self._draw_continuing = None
        self._draw_base = 0
        self._draw_ahead = ()
        self._draw_drag = None
        self._draw_dragged = False

    def _run_to(self, at: HoleCoord) -> list[HoleCoord]:
        """The pads an orthogonal run from the last hole drawn to ``at`` takes, ``at`` last.

        Along the row first and then down the column, or the other way round once ``/``
        has flipped it. ONE RULE, as the sheet's wire tool has (``viewsch._elbow``): a
        corner that changed sides with the direction the pointer came from could not be
        aimed. Each step is to an orthogonal neighbour, so the path is still the chain
        ``validate_orthogonal_chain`` and the command require.
        """
        if not self._draw_path:
            return [at]
        return _orthogonal_run(self._draw_path[-1], at, self._draw_column_first)

    def _step_to(self, at: HoleCoord) -> list[HoleCoord]:
        """The holes a click on ``at`` adds, ``at`` last: a run's every pad, a wire's corner
        if it needs one, a jumper's end."""
        if not self._draw_path:
            return [at]
        if self._draw_kind in self._RUN_KINDS:
            return self._run_to(at)
        if self._draw_kind in self._WIRE_KINDS:
            return _elbow(self._draw_path[-1], at, self._draw_column_first)
        return [at]

    def flip_draw_corner(self) -> None:
        """Turn the corner of the run or wire being drawn the other way (``/``)."""
        if self._draw_kind not in self._CORNER_KINDS:
            return
        self._draw_column_first = not self._draw_column_first
        self._refresh_draw_preview(self._last_hole)

    def _step_is_legal(self, at: HoleCoord) -> bool:
        """Whether the next click may go here, by the same rule the command applies.

        A solder trace joins orthogonal neighbours only: at 2.54 mm pitch the orthogonal
        pad gap is about 0.6 mm and the diagonal one about 1.7 mm, and solder does not
        reliably span the second. Checked here so the preview can say so before the click
        rather than the command refusing after it.
        """
        board = self.document.board
        if not is_inside_board(at, board):
            return False
        if not self._draw_path:
            return True
        # The whole step, hole by hole: on the board, and never back over the conductor's
        # own holes, which a chain cannot visit twice.
        step = self._step_to(at)
        return (
            bool(step)
            and at != self._draw_path[-1]
            and all(is_inside_board(hole, board) and hole not in self._draw_path for hole in step)
        )

    def _continue_from(self, at: HoleCoord) -> bool:
        """Start on the run of the armed kind that ends at ``at``, if exactly one does.

        Drawing on from a run's end made a second, separate run with no net, where the
        person had plainly meant the same one longer. ONLY RUNS: a run is soldered at every
        pad, so its old end stays joined in the middle of the longer one. A wire touches
        only its ends -- carried on, its old end would become a corner lying over the hole,
        and whatever was soldered there would come off it.
        """
        if self._draw_kind not in self._RUN_KINDS:
            return False
        # Only a run on the face being drawn on: one on the other face ends at the same pad
        # and is joined to it by the hole, not continued by solder across the board.
        face = self.solder_draw_face
        ends = [
            c
            for c in self.document.conductors
            if c.kind == self._draw_kind
            and c.side == face
            and len(c.path) >= 2
            and at in (c.path[0], c.path[-1])
        ]
        if len(ends) != 1:
            return False
        run = ends[0]
        self._draw_path = list(run.path) if run.path[-1] == at else list(reversed(run.path))
        self._draw_continuing = run.id
        self._draw_base = len(run.path)
        return True

    def draw_click(self, at: HoleCoord) -> DispatchResult | None:
        """Extend the conductor being drawn, committing it when it is complete.

        A solder trace takes the whole run to the click, and a click on its last pad
        finishes it -- which is also what the second half of a double-click is.
        """
        if self._draw_kind is None:
            return None
        if not self._draw_path and self._continue_from(at):
            self._refresh_draw_preview(at)
            return None
        corners = self._draw_kind in self._CORNER_KINDS
        if corners and self._draw_path and at == self._draw_path[-1]:
            return self.commit_drawing()
        if not self._step_is_legal(at):
            return None
        self._draw_path.extend(self._step_to(at))
        if self._draw_kind in self._TWO_POINT_KINDS and len(self._draw_path) == 2:
            return self.commit_drawing()
        self._refresh_draw_preview(at)
        return None

    # -- drawing by dragging ------------------------------------------------
    #
    # Every tool was click by click: a click where the copper turns, Enter or a right-click
    # to finish. Pressing on a pad, dragging to another and letting go -- what every
    # drawing program does -- laid one hole and waited. A drag is now that gesture, made
    # of the same clicks: the press is the first, each turn of the drag is a corner, and
    # the release is the last and finishes. So the preview, ``drawcheck`` and every rule a
    # click obeys hold for a drag without a second path through them, and a press let go
    # where it went down is still a click.

    def draw_press(self, at: HoleCoord) -> DispatchResult | None:
        """The button goes down on ``at`` while drawing: a click, which a drag may follow."""
        result = self.draw_click(at)
        # Only while something is being drawn: a click that laid the copper -- a jumper's
        # second end, a run's last pad clicked again -- leaves nothing to drag.
        self._draw_drag = (at, at) if self._draw_path else None
        self._draw_dragged = False
        return result

    def draw_drag(self, at: HoleCoord) -> None:
        """The held press has moved to ``at``. Where the drag turns -- leaves the line it
        was on from the last corner -- the hole it turned at becomes a corner, as a click
        there would have made it."""
        if self._draw_drag is None or not self._draw_path:
            return
        pressed, last = self._draw_drag
        if at == last:
            return
        self._draw_dragged = True
        anchor = self._draw_path[-1]
        if self._draw_kind in self._CORNER_KINDS and last != anchor and not _in_line(anchor, last, at):
            self.draw_click(last)
            self._refresh_draw_preview(at)
        self._draw_drag = (pressed, at)

    def draw_release(self, at: HoleCoord) -> DispatchResult | None:
        """The held press is let go over ``at``. After a drag that is the last click, and the
        conductor is laid; a press let go where it went down was a click, and drawing goes on.
        A last step the tool refuses leaves the drawing where it was, the banner saying why,
        to be finished with clicks."""
        drag, dragged = self._draw_drag, self._draw_dragged
        self._draw_drag = None
        self._draw_dragged = False
        if drag is None or not dragged or not self._draw_path:
            return None
        self._draw_drag = drag
        self.draw_drag(at)
        self._draw_drag = None
        if at != self._draw_path[-1]:
            result = self.draw_click(at)
            if result is not None or not self._draw_path or self._draw_path[-1] != at:
                return result
        return self.commit_drawing() if len(self._draw_path) >= 2 else None

    @property
    def drawing_by_drag(self) -> bool:
        """Whether a drawing press is held and has moved off the hole it went down on."""
        return self._draw_drag is not None and self._draw_dragged

    def commit_drawing(self) -> DispatchResult | None:
        """Dispatch the drawn conductor, and stay armed for the next one.

        THE TOOL KEEPS ITS KIND after a conductor goes in: copper is laid in a series, and it
        let go after every piece -- ten wires were W pressed ten times. Esc, another tool or
        Enter on nothing drawn leaves it. Under two holes is a cancel, not an error: of the
        run alone when one hole was clicked, of the tool when none was.
        """
        nothing_new = self._draw_continuing is not None and len(self._draw_path) <= self._draw_base
        if self.bus is None or self._draw_kind is None or len(self._draw_path) < 2 or nothing_new:
            if self._draw_kind is not None and self._draw_path:
                self._start_next_conductor()
                return None
            self._clear_draw()
            self.drawArmed.emit("")
            return None

        kind = self._draw_kind
        path = (
            _straightened(self._draw_path)
            if kind in self._WIRE_KINDS
            else tuple(self._draw_path)
        )
        # The net is the one the copper's contacts meet -- a pin's or a conductor's -- so a
        # run drawn on from another run's end, or from a pin to its own net's copper, joins
        # that net. Copper that meets two nets (a short) or none stays unclaimed, which is
        # not a failure: copper with no net claim is what rip-up-and-reroute and the
        # stale-conductor cleanup both promise never to touch.
        checked = self.check_drawing(path)
        if checked is not None and checked.duplicate is not None and self._draw_continuing is None:
            # Copper already lying exactly there: a second piece in the same place joins
            # nothing and is one more thing to solder, and it was laid without a word.
            self.last_draw_check = checked
            self.last_drawn = (kind, path)
            self._start_next_conductor()
            self.drawnAlready.emit(checked.duplicate)
            return None
        if self._draw_continuing is not None:
            # The run drawn on from its end is the same run, longer: one setPath, its net
            # as it was.
            result = self.bus.dispatch(
                "conductor.setPath",
                SetConductorPathPayload(id=self._draw_continuing, path=path),
            )
            self.last_draw_check = checked
            self.last_drawn = (kind, path)
            self.last_draw_verb = "extended"
            self._start_next_conductor()
            self.conductorDrawn.emit(result)
            return result
        net_id = checked.net_id if checked is not None else None
        spec: NewConductor
        laid, face = self.drawing_as(kind)
        if laid in ("solder-trace", "solder-trace-wired"):
            spec = NewSolderTraceConductor(path=path, kind=cast(Any, laid), net_id=net_id, side=face)
        else:
            spec = NewWireConductor(path=path, kind=cast(Any, laid), side=face, net_id=net_id)

        result = self.bus.dispatch("conductor.add", AddConductorPayload(conductor=spec))
        self.last_draw_check = checked
        # What was laid, which the status line names: an insulated wire drawn on the
        # component side went in as a top jumper, and the banner already said so.
        self.last_drawn = (laid, path)
        self.last_draw_verb = "drew"
        self._start_next_conductor()
        self.conductorDrawn.emit(result)
        return result

    def _start_next_conductor(self) -> None:
        """Forget the conductor being drawn and keep the tool."""
        self._draw_path = []
        self._draw_column_first = False
        self._draw_continuing = None
        self._draw_base = 0
        self._refresh_draw_preview(self._last_hole)
        self.drawArmed.emit(self._draw_kind or "")

    def _refresh_draw_preview(self, cursor: HoleCoord | None) -> None:
        if self._draw_preview is None:
            return
        # Off the board there is no hole to draw to, and the ring the next click would take
        # was drawn there anyway, red, over the empty canvas past the edge.
        if cursor is not None and not is_inside_board(cursor, self.document.board):
            cursor = None
        ok = cursor is None or self._step_is_legal(cursor)
        run = (
            self._step_to(cursor)
            if cursor is not None and self._draw_path and self._draw_kind in self._CORNER_KINDS
            else []
        )
        self._draw_preview.set_path(list(self._draw_path), cursor, ok, run)
        # What Enter or the next click would lay: the path so far and the step to the
        # pointer, when that step is one the tool would take.
        ahead = list(self._draw_path)
        if cursor is not None and ok and self._draw_path:
            ahead += run if self._draw_kind in self._CORNER_KINDS else [cursor]
        self._draw_ahead = tuple(ahead)
        checked = self.check_drawing(ahead)
        self._draw_preview.set_problem(checked.worst if checked is not None else None)
        self.drawChecked.emit(checked)

    # -- naming a net by clicking its pins -----------------------------------
    #
    # A net could only ever arrive from a KiCad netlist, which made a schematic capture
    # package a prerequisite for the ratsnest -- and so for autoroute, LVS and the guide's
    # continuity tests. Nobody opens KiCad to wire four parts on a scrap of perfboard.
    #
    # A MODE over the board rather than a dialog listing refs, for the same reason
    # placement is one: the pin IS the decision, and on a perfboard a pin is a hole you
    # can point at. A list of "U1.8, U1.7, C2.2" asks the user to do the translation the
    # board is already showing them.

    def arm_net_pins(self, net_id: str | None) -> None:
        """Arm (or, with None, disarm) collecting pins for a net.

        An unknown id disarms rather than collecting clicks for a net that is not there.
        """
        if net_id is not None and not any(n.id == net_id for n in self.document.nets):
            net_id = None
        if net_id is not None:
            # The board modes are mutually exclusive: a click means one thing.
            self.arm_placement(None)
            self.arm_drawing(None)
            self._disarm_connect()
            self._disarm_measure()
            self._disarm_cutting()
        self._clear_net_pins()
        self._net_pin_target = net_id
        if net_id is not None:
            self._net_pin_item = PickedPinsItem(self.document.board, self.side)
            self.addItem(self._net_pin_item)
        self.netPinsArmed.emit(net_id or "")
        self.netPinsChanged.emit([])

    @property
    def armed_net_id(self) -> str | None:
        return self._net_pin_target

    def picked_pins(self) -> tuple[tuple[str, str], ...]:
        """(ref, pin) collected so far. Also what the seam tests assert on."""
        return tuple(self._net_pin_picks)

    def _disarm_net_pins(self) -> None:
        """End the mode without committing, for the other two modes to call."""
        if self._net_pin_target is None:
            return
        self._clear_net_pins()
        self._net_pin_target = None
        self.netPinsArmed.emit("")

    def _clear_net_pins(self) -> None:
        if self._net_pin_item is not None:
            self.removeItem(self._net_pin_item)
            self._net_pin_item = None
        self._net_pin_picks = []
        self._net_pin_holes = []

    def _pin_at(self, hole: HoleCoord) -> tuple[str, str] | None:
        """The component pin occupying a hole, as (ref, pin number).

        Two parts on one hole is a legal document that DRC objects to, so this takes the
        first in document order -- deterministic, and the overlap is already reported by
        the rule that owns it.
        """
        for comp in self.document.components:
            for pin, at in _pin_holes_of(comp, self.lookup):
                if at.col == hole.col and at.row == hole.row:
                    return comp.ref, pin.number
        return None

    def _net_holding(self, ref: str, pin: str) -> Net | None:
        for net in self.document.nets:
            if any((node.component_ref, node.pin) == (ref, pin) for node in net.nodes):
                return net
        return None

    def net_pin_click(self, at: HoleCoord) -> None:
        """Add the pin at this hole to the list being collected, or say why not.

        Every refusal the command would make is made HERE, one click at a time, rather
        than letting a session accumulate pins and then bounce the whole batch at commit
        for something the user did five clicks ago.
        """
        target = self._net_pin_target
        if target is None:
            return

        found = self._pin_at(at)
        if found is None:
            self.netPinRejected.emit(t("No component pin at {hole}.").format(hole=format_hole(at, self.document.board)))
            return

        ref, pin = found
        if (ref, pin) in self._net_pin_picks:
            self.netPinRejected.emit(t("{pin} is already on the list.").format(pin=f"{ref}.{pin}"))
            return

        holder = self._net_holding(ref, pin)
        if holder is not None and holder.id == target:
            self.netPinRejected.emit(
                t("{pin} is already on {net}.").format(pin=f"{ref}.{pin}", net=holder.name)
            )
            return
        if holder is not None:
            self.netPinRejected.emit(
                t(
                    "{pin} belongs to {net}. Disconnect it there first — a pin can only "
                    "be on one net."
                ).format(pin=f"{ref}.{pin}", net=holder.name)
            )
            return

        self._net_pin_picks.append((ref, pin))
        self._net_pin_holes.append(at)
        if self._net_pin_item is not None:
            self._net_pin_item.set_holes(self._net_pin_holes)
        self.netPinsChanged.emit([f"{r}.{p}" for r, p in self._net_pin_picks])

    # -- joining two pins, which is the whole job in two clicks --------------
    #
    # Naming a net, then filling it, then routing it is the honest model and it was also
    # four steps deep in two menus before a single pin could be joined to anything. Most
    # of the time the user is not thinking "I shall declare a net"; they are pointing at
    # two legs and saying THOSE go together. This is that, and it produces exactly the
    # same documents the long way round does -- one command per pair, on the same bus.

    # -- cutting a track, which is how a stripboard is designed --------------
    #
    # On a pad-per-hole board every connection is added. On stripboard the copper is
    # already there in whole rows and the design is decided by where it is BROKEN, so
    # this is that board's primary edit -- the counterpart of drawing a solder trace.

    def arm_cutting(self, on: bool) -> None:
        """Arm (or disarm) cutting tracks. Silently refuses on a board with no tracks."""
        if on and not is_stripboard(self.document.board):
            on = False
        if on:
            self.arm_placement(None)
            self.arm_drawing(None)
            self._disarm_net_pins()
            self._disarm_connect()
            self._disarm_measure()
        self._cut_armed = on
        self.cutArmed.emit(on)

    @property
    def cut_armed(self) -> bool:
        return self._cut_armed

    def _disarm_cutting(self) -> None:
        if not self._cut_armed:
            return
        self._cut_armed = False
        self.cutArmed.emit(False)

    def cut_at(self, hole: HoleCoord) -> TrackCut | None:
        return next((c for c in self.document.cuts if c.at == hole), None)

    def cut_click(self, at: HoleCoord) -> DispatchResult | None:
        """Cut the track at this hole, or take back the cut already there.

        A toggle rather than an add-only tool, because a cut is small, invisible on the
        finished board and easy to put one hole out -- so the fix has to be the same
        gesture as the mistake. Each direction is still its own command and its own undo
        step; nothing here edits the document.
        """
        if not self._cut_armed or self.bus is None:
            return None
        if not is_inside_board(at, self.document.board):
            return None

        existing = self.cut_at(at)
        result = (
            self.bus.dispatch("cut.delete", DeleteCutPayload(id=existing.id))
            if existing is not None
            else self.bus.dispatch("cut.add", AddCutPayload(at=at))
        )
        self.cutMade.emit(result)
        return result

    # -- measuring, which is the one tool that changes nothing ---------------
    #
    # Perfboard work is full of distances that have to be right before anything is
    # soldered: how far apart to bend a resistor's legs, whether a TO-220 clears the
    # capacitor beside it, how long a wire has to be cut. All of it was countable off the
    # ruler and none of it was readable, so people counted holes on the screen with a
    # finger. Three numbers answer nearly all of it, and they are not the same number:
    # the hole span (how many holes across), the straight distance in mm (what you set a
    # pair of pliers or a lead-bending jig to), and the orthogonal step count (how long a
    # solder trace between the two would be).

    def arm_measure(self, on: bool) -> None:
        """Arm (or disarm) measuring between two holes."""
        if on:
            # The board modes are mutually exclusive: a click means one thing.
            self.arm_placement(None)
            self.arm_drawing(None)
            self._disarm_net_pins()
            self._disarm_connect()
            self._disarm_cutting()
        self._clear_measure()
        self._measure_armed = on
        self.measureArmed.emit(on)
        self.measured.emit(t("Click the first hole.") if on else "")

    @property
    def measure_armed(self) -> bool:
        return self._measure_armed

    def measure_from(self) -> HoleCoord | None:
        """The hole a measurement started from, if one is half made."""
        return self._measure_from

    def _disarm_measure(self) -> None:
        if not self._measure_armed:
            return
        self._clear_measure()
        self._measure_armed = False
        self.measureArmed.emit(False)
        self.measured.emit("")

    def _clear_measure(self) -> None:
        if self._measure_item is not None:
            self.removeItem(self._measure_item)
            self._measure_item = None
        self._measure_from = None
        self.measurement = ""

    def measure_click(self, at: HoleCoord) -> None:
        """Take the first hole, or finish the measurement at the second.

        Finishing leaves the tool armed and the answer on screen: measuring one distance
        is almost never what somebody is doing -- they are comparing several -- and a
        tool that disarmed itself after each one would have to be re-armed for every
        comparison.
        """
        if not self._measure_armed or not is_inside_board(at, self.document.board):
            return
        if self._measure_from is None or self._measure_from == at:
            self._measure_from = at
            self.measurement = ""
            if self._measure_item is None:
                self._measure_item = PickedPinsItem(self.document.board, self.side)
                self.addItem(self._measure_item)
            self._measure_item.set_holes([at])
            self.measured.emit(t("From {hole} — click the second hole.").format(hole=format_hole(at, self.document.board)))
            return

        if self._measure_item is not None:
            self._measure_item.set_holes([self._measure_from, at])
        # Finished before it is said, so whoever hears it sees a tool waiting for the next pair.
        self.measurement = describe_span(self._measure_from, at, self.document.board)
        self._measure_from = None
        self.measured.emit(self.measurement)

    # -- leaving whatever mode you are in ------------------------------------

    @property
    def in_a_mode(self) -> bool:
        """Whether a click on the board currently means something other than 'select'."""
        return (
            self._armed_footprint is not None
            or self._draw_kind is not None
            or self._net_pin_target is not None
            or self._connect_armed
            or self._measure_armed
            or self._cut_armed
        )

    def leave_mode(self) -> None:
        """Disarm every board mode. This is what Escape means, wherever it is pressed.

        ONE method rather than a branch per mode at each call site, and that is the fix
        for a real bug rather than tidiness. Escape is a window shortcut, so it fires
        wherever the focus is -- and it fires BEFORE this scene sees the key at all, which
        made the placement branch that used to live in ``keyPressEvent`` unreachable in the
        running application: a part armed from the library could not be cancelled from the
        keyboard at all, and the hint under the list said "Esc cancels" the whole time.
        The window's shortcut and this handler now call the same method, so they cannot
        cancel different sets of things.
        """
        self.arm_placement(None)
        self.arm_drawing(None)
        self.arm_net_pins(None)
        self.arm_connect(False)
        self.arm_measure(False)
        self.arm_cutting(False)

    def arm_connect(self, on: bool) -> None:
        """Arm (or disarm) joining pins by clicking two of them."""
        if on:
            self.arm_placement(None)
            self.arm_drawing(None)
            self._disarm_net_pins()
            self._disarm_measure()
            self._disarm_cutting()
        self._clear_connect()
        self._connect_armed = on
        self.connectArmed.emit(on)
        self.connectProgress.emit([])

    @property
    def connect_armed(self) -> bool:
        return self._connect_armed

    def connect_from(self) -> tuple[str, str] | None:
        """The pin waiting for its partner, if a pair is half made. For the banner, and
        what the seam tests assert on."""
        return self._connect_first

    def _disarm_connect(self) -> None:
        if not self._connect_armed:
            return
        self._clear_connect()
        self._connect_armed = False
        self.connectArmed.emit(False)

    def _clear_connect(self) -> None:
        self._connect_first = None
        self._connect_hole = None
        self._ring_the_pin(None)
        if self._connect_item is not None:
            self.removeItem(self._connect_item)
            self._connect_item = None

    def connect_click(self, at: HoleCoord) -> DispatchResult | None:
        """Take the first pin, or join the second to it.

        Four outcomes, and each is stated rather than guessed at:
          - neither pin is on a net  -> a new net, named for you, holding both
          - one of them is           -> the other joins THAT net, which is what a person
                                        pointing at a pin and then at a rail means
          - both, and the same net   -> nothing to do, and it says so
          - both, different nets     -> refused, naming both. Merging two nets is a
                                        decision about the circuit, not about two clicks,
                                        and it is not one this tool may take on its own.
        """
        if not self._connect_armed:
            return None

        found = self._pin_at(at)
        if found is None:
            self.netPinRejected.emit(t("No component pin at {hole}.").format(hole=format_hole(at, self.document.board)))
            return None

        first = self._connect_first
        if first is None:
            self._connect_first = found
            self._connect_hole = at
            self._connect_item = PickedPinsItem(self.document.board, self.side)
            self._connect_item.set_holes([at])
            self.addItem(self._connect_item)
            self.connectProgress.emit([f"{found[0]}.{found[1]}"])
            return None

        if found == first:
            self.netPinRejected.emit(t("{pin} is already the pin you started from.").format(pin=f"{found[0]}.{found[1]}"))
            return None

        result = self._join_pins(first, found)
        # Cleared either way: a refused pair is not a pair you are still in the middle of,
        # and leaving the first pin armed would make the next click join something the
        # user has stopped thinking about.
        self._clear_connect()
        self.connectProgress.emit([])
        if result is not None:
            self.pinsConnected.emit(result)
        return result

    def _join_pins(
        self, first: tuple[str, str], second: tuple[str, str]
    ) -> DispatchResult | None:
        """The scene's half: turn the shared decision into this scene's signals.

        The decision itself is ``join_pins`` above, shared with the schematic sheet so
        that clicking two pads and clicking two symbol pins cannot mean different things.
        """
        if self.bus is None:
            return None
        result, refusal = join_pins(self.bus, first, second)
        if refusal is not None:
            self.netPinRejected.emit(refusal)
        return cast("DispatchResult | None", result)

    def commit_net_pins(self) -> DispatchResult | None:
        """Dispatch ONE ``net.connect`` for everything picked. Nothing picked is a cancel.

        One command for the whole session on purpose: "GND is these five pins" was one
        decision, and an undo that leaves three of them attached is a state nobody asked
        for.
        """
        target = self._net_pin_target
        picks = list(self._net_pin_picks)
        self._clear_net_pins()
        self._net_pin_target = None
        self.netPinsArmed.emit("")

        if self.bus is None or target is None or not picks:
            return None

        result = self.bus.dispatch(
            "net.connect",
            ConnectPinsPayload(
                id=target,
                nodes=tuple(NetNode(component_ref=ref, pin=pin) for ref, pin in picks),
            ),
        )
        self.netPinsCommitted.emit(result)
        return result

    def selected_conductor_ids(self) -> tuple[str, ...]:
        return tuple(
            item.conductor_id
            for item in self.items()
            if isinstance(item, ConductorItem) and item.isSelected()
        )

    def _sync_handles(self) -> None:
        """Handles on the one conductor selected, and on nothing otherwise.

        From the dicts, never ``items()``: this runs from ``selectionChanged``, which Qt
        emits while ``clear()`` is destroying the items, and the dicts are emptied first.
        """
        for handle in self._handles:
            with contextlib.suppress(RuntimeError):
                if handle.scene() is self:
                    self.removeItem(handle)
        self._handles = []
        chosen = [cid for cid, item in self.conductor_items.items() if item.isSelected()]
        if len(chosen) != 1 or any(i.isSelected() for i in self.component_items.values()):
            return
        conductor = next((c for c in self.document.conductors if c.id == chosen[0]), None)
        if conductor is None or conductor.kind not in self._CORNER_KINDS | self._TWO_POINT_KINDS:
            return
        last = len(conductor.path) - 1
        # Every corner of a wire, and of a jumper drawn with corners; a run's middle is
        # pads, every one a joint.
        indices = range(len(conductor.path)) if conductor.kind not in self._RUN_KINDS else (0, last)
        for index in indices:
            handle = CopperHandleItem(index, conductor.path[index], self.document.board, self.side)
            self.addItem(handle)
            self._handles.append(handle)

    def handle_at(self, pos: QPointF) -> int | None:
        """The index in its path of the selected conductor's handle under ``pos``, or None."""
        reach = self.document.board.pad_diameter * 0.6
        for handle in self._handles:
            offset = handle.pos() - pos
            if math.hypot(offset.x(), offset.y()) <= reach:
                return handle.index
        return None

    def begin_reshape(
        self,
        index: int,
        conductor_id: str | None = None,
        *,
        slide_from: HoleCoord | None = None,
    ) -> bool:
        """Pick up hole ``index`` of a conductor: the one selected, or ``conductor_id``.
        With ``slide_from``, the leg from ``index`` to ``index + 1`` instead, to be slid
        sideways from that hole (``slid_path``). Also the seam tests drive."""
        if conductor_id is None:
            chosen = self.selected_conductor_ids()
            if len(chosen) != 1:
                return False
            conductor_id = chosen[0]
        conductor = next((c for c in self.document.conductors if c.id == conductor_id), None)
        if conductor is None:
            return False
        self._reshape = (conductor.id, index)
        self._reshape_slide = slide_from
        self._reshape_path = None
        self._reshape_check = None
        self._reshape_preview = DrawPreviewItem(conductor.kind, self.document.board, self.side)
        self._reshape_preview.set_path(list(conductor.path), None, True)
        self.addItem(self._reshape_preview)
        return True

    def reshape_to(self, at: HoleCoord) -> None:
        """The handle held is over ``at``: preview the path it would give, checked as a
        drawn one is."""
        if self._reshape is None or self._reshape_preview is None:
            return
        conductor_id, index = self._reshape
        conductor = next((c for c in self.document.conductors if c.id == conductor_id), None)
        if conductor is None:
            return
        board = self.document.board
        slide = self._reshape_slide
        path = (
            reshaped_path(conductor.kind, conductor.path, index, at)
            if slide is None
            else slid_path(
                conductor.kind, conductor.path, index, at.col - slide.col, at.row - slide.row
            )
        )
        legal = path is not None and all(is_inside_board(hole, board) for hole in path)
        self._reshape_path = path if legal and path != conductor.path else None
        shown = path if legal and path is not None else conductor.path
        self._reshape_preview.set_path(list(shown), None if legal else at, legal)
        # Asked from the end that stays put, as if drawn from there to the handle: the check
        # names the hole where the copper meets a second net, and walked from the moved end
        # that was a pad the run already had, not the one the drag brought in.
        asked = (
            self._reshape_path[::-1]
            if self._reshape_path is not None and index == 0 and slide is None
            else self._reshape_path
        )
        checked = (
            check_drawn(
                self.document,
                self.lookup,
                conductor.kind,
                asked,
                ignoring=conductor_id,
                side=conductor.side,
            )
            if asked is not None
            else None
        )
        self._reshape_check = checked
        self._reshape_preview.set_problem(checked.worst if checked is not None else None)
        self.drawChecked.emit(checked)

    def finish_reshape(self) -> DispatchResult | None:
        """Put the handle down: one ``conductor.setPath``, or nothing if it is where it was."""
        if self._reshape is None:
            return None
        conductor_id, _index = self._reshape
        path, checked = self._reshape_path, self._reshape_check
        self.cancel_reshape()
        conductor = next((c for c in self.document.conductors if c.id == conductor_id), None)
        if self.bus is None or path is None or conductor is None:
            return None
        result = self.bus.dispatch(
            "conductor.setPath", SetConductorPathPayload(id=conductor_id, path=path)
        )
        self.last_draw_check = checked
        self.last_drawn = (conductor.kind, path)
        self.last_draw_verb = "reshaped"
        self.conductorDrawn.emit(result)
        return result

    def cancel_reshape(self) -> bool:
        """Drop a handle's drag without changing anything. True if there was one."""
        if self._reshape is None:
            return False
        if self._reshape_preview is not None:
            with contextlib.suppress(RuntimeError):
                self.removeItem(self._reshape_preview)
        self._reshape = None
        self._reshape_path = None
        self._reshape_preview = None
        self._reshape_check = None
        self._reshape_slide = None
        self.drawChecked.emit(None)
        return True

    # -- copper picked up where it lies ----------------------------------------------------
    #
    # A part was dragged the moment it was pressed; copper had to be clicked first, and then
    # only its ends moved, by squares a third of a pad wide -- so on a board the eye reads as
    # parts AND wiring, half of it would not move under the hand. A press on copper in the
    # Select tool now picks up what it is on: an end (on its pad, which is where it is
    # soldered), a wire's corner, or a straight stretch to slide sideways. Each is the
    # handle drag that was there already -- one ``conductor.setPath``, checked live as it is
    # drawn, Esc puts it back -- and a press let go where it went down still only selects.

    def copper_grab_at(self, pos: QPointF) -> CopperGrab | None:
        """What a press at scene position ``pos`` in the Select tool picks up of the copper,
        or None for nothing -- the part under it, or the board.

        An END within a pad's reach comes first, wherever the copper lies, a part's pin on
        the same pad included: the end is soldered there, and the part is moved by its
        body. A wire's CORNER next, the same way. Then a SEGMENT, by the band the copper is
        clicked by (``conductor_at``), unless a part lies over it (``component_at``'s rule).
        Ties go to the conductor drawn on top.
        """
        if self.in_a_mode or self.bus is None:
            return None
        board = self.document.board
        reach = board.pad_diameter / 2
        kinds = self._CORNER_KINDS | self._TWO_POINT_KINDS
        by_id = {c.id: c for c in self.document.conductors}
        best: tuple[tuple[bool, float, str], CopperGrab] | None = None
        for conductor_id, item in self.conductor_items.items():
            conductor = by_id.get(conductor_id)
            if (
                conductor is None
                or conductor.kind not in kinds
                or not item.isVisible()
                or item.is_hidden_on_screen()
            ):
                continue
            last = len(conductor.path) - 1
            points = (
                range(len(conductor.path)) if conductor.kind not in self._RUN_KINDS else (0, last)
            )
            for index in points:
                spot = hole_to_screen(conductor.path[index], board, self.side)
                if math.hypot(spot.x() - pos.x(), spot.y() - pos.y()) > reach:
                    continue
                kind = "end" if index in (0, last) else "corner"
                key = (kind != "end", -item.zValue(), conductor_id)
                if best is None or key < best[0]:
                    best = (key, CopperGrab(conductor_id, kind, index))
        if best is not None:
            return best[1]
        over = self.conductor_at(pos)
        if over is None or self.component_at(pos) is not None:
            return None
        conductor = by_id.get(over.conductor_id)
        if conductor is None or conductor.kind not in kinds:
            return None
        return self._segment_grab(conductor, pos)

    def _segment_grab(self, conductor: Conductor, pos: QPointF) -> CopperGrab | None:
        """The leg of ``conductor`` nearest ``pos``, as a segment to slide -- None for a
        diagonal one, which has no sideways on the grid."""
        board = self.document.board
        spots = [hole_to_screen(hole, board, self.side) for hole in conductor.path]
        nearest = min(
            range(len(spots) - 1), key=lambda i: _distance_to_leg(pos, spots[i], spots[i + 1])
        )
        a, b = conductor.path[nearest], conductor.path[nearest + 1]
        if a.row == b.row:
            return CopperGrab(conductor.id, "segment", nearest, "rows")
        if a.col == b.col:
            return CopperGrab(conductor.id, "segment", nearest, "columns")
        return None

    def grab_copper(self, pos: QPointF) -> bool:
        """Pick up what a press at ``pos`` would (``copper_grab_at``). True if it did."""
        grab = self.copper_grab_at(pos)
        if grab is None:
            return False
        at = screen_to_hole(pos, self.document.board, self.side)
        return self.begin_reshape(
            grab.position, grab.conductor_id, slide_from=at if grab.kind == "segment" else None
        )

    # -- several conductors under one click ----------------------------------------------

    def conductors_at(self, pos: QPointF) -> list[ConductorItem]:
        """Every conductor under a scene position, the one on top first."""
        found = [
            item for item in self.conductor_items.values() if item.contains(item.mapFromScene(pos))
        ]
        return sorted(found, key=lambda item: (-item.zValue(), item.conductor_id))

    def cycle_pick(self, pos: QPointF) -> bool:
        """Select the next of several conductors under ``pos``. True if it did.

        Where a run and a wire lie along the same row, the one on top was all a click could
        reach, and Delete then took the wrong one. The first click takes the top one, the
        next click on the same spot the one under it, round and round.
        """
        here = self.conductors_at(pos)
        if len(here) < 2 or self.component_at(pos) is not None:
            return False
        ids = [item.conductor_id for item in here]
        chosen = self.selected_conductor_ids()
        if len(chosen) == 1 and chosen[0] in ids and not self.selected_component_ids():
            pick = ids[(ids.index(chosen[0]) + 1) % len(ids)]
        else:
            pick = ids[0]
        self.select_conductors([pick])
        self.pickCycled.emit(ids.index(pick) + 1, len(ids))
        return True

    def select_conductors(self, conductor_ids: Collection[str]) -> None:
        """Exactly these conductors, and nothing else, selected."""
        wanted = set(conductor_ids)
        self.clearSelection()
        for conductor_id, item in self.conductor_items.items():
            if conductor_id in wanted:
                item.setSelected(True)

    def arm_placement(self, footprint_id: str | None, *, part_id: str | None = None) -> None:
        """Arm (or, with None, disarm) placing a footprint on the next board click.

        With ``part_id``, the footprint is that design part's and the click places IT
        (:meth:`arm_part`).
        """
        if footprint_id is None or footprint_id != self._armed_id:
            self._armed_rotation = 0
            self._armed_mirrored = False
        self._armed_footprint = None if footprint_id is None else self.lookup(footprint_id)
        self._armed_id = footprint_id if self._armed_footprint is not None else None
        self._armed_part_id = part_id if self._armed_id is not None else None
        self._clear_ghost()
        if self._armed_footprint is not None:
            # The board modes are mutually exclusive, and drawing is one of them: a part
            # picked from the library mid-trace used to leave both armed, with the ghost
            # following the pointer while every click still extended the trace.
            if self._draw_kind is not None:
                self.arm_drawing(None)
            self._disarm_net_pins()
            self._disarm_connect()
            self._disarm_measure()
            self._disarm_cutting()
            self._ghost = PlacementGhostItem(
                self._armed_footprint,
                self.document.board,
                self.side,
                self._armed_rotation,
                self._armed_mirrored,
            )
            self._ghost.label = self._armed_part_label()
            self.addItem(self._ghost)
            if self._last_hole is not None:
                self._ghost.set_anchor(self._last_hole, self._placement_blocked(self._last_hole))
        self.placementArmed.emit(self._armed_id or "")

    def arm_part(self, part_id: str | None) -> None:
        """Put a part from the design in hand: the next click on the board places that part.

        A PART DROPPED ON THE SHEET came onto the board as its footprint, and a click put down
        a second part of the same footprint beside the one on the sheet. In hand it is the
        sheet's own part, with its reference over the ghost; the click is ``part.place`` for
        it, one undo step, and the window puts the next part still off the board in hand.
        """
        part = next((p for p in self.document.parts if p.id == part_id), None)
        if part is None:
            self.arm_placement(None)
            return
        self.arm_placement(part.footprint_id, part_id=part.id)

    @property
    def armed_part_id(self) -> str | None:
        """The design part in hand, or None for a library part or nothing."""
        return self._armed_part_id

    def _armed_part_label(self) -> str:
        part = next((p for p in self.document.parts if p.id == self._armed_part_id), None)
        if part is None:
            return ""
        return f"{part.ref} {part.value}".strip()

    @property
    def armed_footprint_id(self) -> str | None:
        return self._armed_id

    @property
    def armed_orientation(self) -> tuple[Rotation, bool]:
        """How the part about to be placed is turned, and whether it is flipped."""
        return self._armed_rotation, self._armed_mirrored

    def orient_armed(self, rotation: Rotation, mirrored: bool) -> None:
        """Turn or flip the part about to be placed, before it is put down.

        R TURNED THE SELECTION WHILE A PART WAS ARMED, and the ghost stayed upright: an
        electrolytic that had to go in sideways went down the wrong way and was turned
        afterwards -- a second command, and a second look at where its pins had gone. The
        ghost is redrawn in the new orientation under the pointer, red where that
        orientation does not fit, and the placement takes it (``component.place`` has
        always accepted a rotation and a flip).
        """
        if self._armed_footprint is None:
            return
        self._armed_rotation = rotation
        self._armed_mirrored = mirrored
        self._clear_ghost()
        self._ghost = PlacementGhostItem(
            self._armed_footprint, self.document.board, self.side, rotation, mirrored
        )
        self._ghost.label = self._armed_part_label()
        self.addItem(self._ghost)
        if self._last_hole is not None:
            self._ghost.set_anchor(self._last_hole, self._placement_blocked(self._last_hole))

    def _clear_ghost(self) -> None:
        if self._ghost is not None:
            self.removeItem(self._ghost)
            self._ghost = None

    def show_drop_ghost(
        self,
        footprint: Footprint,
        anchor: HoleCoord,
        rotation: int = 0,
        mirrored: bool = False,
        moving: str | None = None,
    ) -> None:
        """The part being dragged onto the board, drawn at the size and in the holes it
        will take -- red where it cannot go.

        A DROP HAD NOTHING ON THE BOARD, only the picture under the pointer: a list icon
        at a fixed size, centred on the pointer, while the drop puts the part's FIRST PIN
        in the hole under it. So what was carried was not where the part landed, and was
        not the size of the part either. This is the same ghost a part picked from the list
        gets, with the orientation it will actually go down in. ``moving`` is the part
        itself when it is already on the board, so its own holes do not count against it.
        """
        ghost = self._drop_ghost
        if ghost is None or ghost.fp is not footprint or (
            ghost.part_rotation,
            ghost.part_mirrored,
        ) != (rotation, mirrored):
            self.clear_drop_ghost()
            ghost = PlacementGhostItem(footprint, self.document.board, self.side, rotation, mirrored)
            self.addItem(ghost)
            self._drop_ghost = ghost
        ghost.set_anchor(anchor, self._drop_blocked(footprint, anchor, rotation, mirrored, moving))

    def clear_drop_ghost(self) -> None:
        if self._drop_ghost is not None:
            self.removeItem(self._drop_ghost)
            self._drop_ghost = None

    def _drop_blocked(
        self,
        footprint: Footprint,
        anchor: HoleCoord,
        rotation: int,
        mirrored: bool,
        moving: str | None,
    ) -> bool:
        """``_placement_blocked``'s three questions, for a part that may be turned and may
        already be on the board."""
        occupied = self._occupied_pins(() if moving is None else (moving,))
        return any(self._landing_problems(footprint, anchor, rotation, mirrored, occupied))

    def _occupied_pins(self, moving: Collection[str]) -> set[tuple[int, int]]:
        """Every hole a pin of a part that is staying put is in."""
        return {
            (hole.col, hole.row)
            for comp in self.document.components
            if comp.id not in moving
            for _pin, hole in _pin_holes_of(comp, self.lookup)
        }

    def _landing_problems(
        self,
        footprint: Footprint,
        anchor: HoleCoord,
        rotation: int,
        mirrored: bool,
        occupied: set[tuple[int, int]],
    ) -> tuple[int, int, int]:
        """How many of a part's pins would land off the board, in a hole another part's pin
        is in, and where no lead can be soldered -- the ONE question the placement ghost,
        a part dragged from a list and a placed part dragged across the board all ask, so
        the three gestures cannot disagree about where a part can go. The bus is still the
        authority; this is the moment before it says so."""
        board = self.document.board
        off = used = unpadded = 0
        for pin in footprint.pins:
            d_col, d_row = transform_pin_offset(
                pin.d_col, pin.d_row, cast(Rotation, rotation), mirrored
            )
            hole = HoleCoord(anchor.col + d_col, anchor.row + d_row)
            if not is_inside_board(hole, board):
                off += 1
            elif (hole.col, hole.row) in occupied:
                used += 1
            elif hole_key(hole) in self._unusable_holes:
                unpadded += 1
        return off, used, unpadded

    def _placement_holes(self, anchor: HoleCoord) -> list[HoleCoord]:
        """Where the armed footprint's pins would land, anchored here."""
        footprint = self._armed_footprint
        if footprint is None:
            return []
        holes = []
        for pin in footprint.pins:
            d_col, d_row = transform_pin_offset(
                pin.d_col, pin.d_row, self._armed_rotation, self._armed_mirrored
            )
            holes.append(HoleCoord(anchor.col + d_col, anchor.row + d_row))
        return holes

    def placement_lands_on_nothing(self, anchor: HoleCoord) -> bool:
        """Whether a pin would land where no lead can be soldered at all.

        A mounting bore has destroyed the pad; an edge-connector finger is solid copper
        that was never drilled; a track cut took the pad with it. In all three there is
        a position on the grid and nothing to fit a lead into, which is why DRC calls
        each of them an ERROR rather than a warning -- it is physical impossibility, not
        a risk. Reported separately from the rest of the ghost's reasons so the message
        after the click can say WHICH thing is wrong.
        """
        return any(hole_key(hole) in self._unusable_holes for hole in self._placement_holes(anchor))

    def _placement_blocked(self, anchor: HoleCoord) -> bool:
        """Would this placement be refused, or land somewhere it cannot be soldered?

        Only a preview -- the bus is still the authority and still gets to refuse. Showing
        it red beforehand saves the user a click and a status-bar message.

        Mounting bores, edge-connector fingers and track cuts are in here and were not:
        the ghost stayed green over a corner mounting hole, so a part went down on a
        position with no pad, and the only thing that ever said so was a line in the DRC
        panel after the fact. The ghost is where "you cannot solder that there" belongs,
        because it is the moment before it happens.
        """
        footprint = self._armed_footprint
        if footprint is None:
            return True
        return any(
            self._landing_problems(
                footprint, anchor, self._armed_rotation, self._armed_mirrored, self._occupied_pins(())
            )
        )

    def mouseMoveEvent(self, event: Any) -> None:
        self.hover_at(event.scenePos())
        if self._draw_drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            # A drag only once the pointer has moved as far as a drag is anywhere on this
            # desktop: a click whose hand slipped one hole was not meant to finish anything.
            moved = event.screenPos() - event.buttonDownScreenPos(Qt.MouseButton.LeftButton)
            if self._draw_dragged or moved.manhattanLength() >= QApplication.startDragDistance():
                self.draw_drag(screen_to_hole(event.scenePos(), self.document.board, self.side))
            event.accept()
            return
        if self._reshape is not None:
            self.reshape_to(screen_to_hole(event.scenePos(), self.document.board, self.side))
            event.accept()
            return
        super().mouseMoveEvent(event)
        if isinstance(self.mouseGrabberItem(), ComponentItem):
            self.report_drag()

    def hover_at(self, pos: QPointF) -> None:
        """Everything that follows the pointer, given where it is in scene coordinates.

        Split from ``mouseMoveEvent`` because the pointer is not the only thing that
        moves: a middle-button pan or a keyboard zoom changes what is under a pointer that
        has not moved at all, and the view calls this afterwards so the ghost and the
        status bar's address do not describe the hole that scrolled away.
        """
        at = screen_to_hole(pos, self.document.board, self.side)
        self._last_hole = at
        self._ring_the_pin(at)
        if self._ghost is not None:
            self._ghost.set_anchor(at, self._placement_blocked(at))
        if self._draw_preview is not None:
            self._refresh_draw_preview(at)
        # Live, because the question is nearly always "how far is it to about there"
        # rather than "how far is it to exactly that hole": the answer has to move with
        # the pointer or it is a two-click way of asking something already answered.
        if self._measure_from is not None and is_inside_board(at, self.document.board):
            self.measured.emit(describe_span(self._measure_from, at, self.document.board))
        self.hoveredHole.emit(at.col, at.row)

    def hover_left(self) -> None:
        """The pointer has left the view: there is no hole under it any more.

        Reported as an off-board address, which the status bar already shows as a dash
        and which Paste already treats as "nowhere in particular" -- so a block is not
        pasted at the hole the pointer happened to leave the board over.
        """
        self._last_hole = None
        self._ring_the_pin(None)
        self.hoveredHole.emit(-1, -1)

    def _ring_the_pin(self, at: HoleCoord | None) -> None:
        """Ring the pin at ``at`` if the connect or the draw tool is armed and there is one,
        and take the ring away otherwise."""
        armed = self._connect_armed or self._draw_kind is not None
        pin_hole = (
            at
            if armed and at is not None and is_inside_board(at, self.document.board)
            and self._pin_at(at) is not None
            else None
        )
        if pin_hole is None and self._pin_hover is None:
            return
        if self._pin_hover is None:
            self._pin_hover = PinHoverItem(self.document.board, self.side)
            self.addItem(self._pin_hover)
        self._pin_hover.set_hole(pin_hole)

    def pin_hover_hole(self) -> HoleCoord | None:
        """The pin the connect or draw tool would take under the pointer, ringed. For the
        seam tests."""
        return self._pin_hover.hole if self._pin_hover is not None else None

    def take_consumed_right_click(self) -> bool:
        """Whether the last right press was a MODE's, and clear the record of it.

        Right-click already means something on this board: it finishes a trace, commits a
        net, or leaves the tool. Those are handled on the press, and a context menu event
        follows the release -- by which time the mode has been left, so a menu built on
        "is a mode armed" would pop up on top of the very gesture that ended it. The press
        says it took the click; the view asks once and the answer is spent.
        """
        taken = self._right_click_taken
        self._right_click_taken = False
        return taken

    def mousePressEvent(self, event: Any) -> None:
        if self.in_a_mode and event.button() == Qt.MouseButton.RightButton:
            self._right_click_taken = True
        if self._cut_armed:
            at = screen_to_hole(event.scenePos(), self.document.board, self.side)
            if event.button() == Qt.MouseButton.LeftButton:
                self.cut_click(at)
            elif event.button() == Qt.MouseButton.RightButton:
                self._disarm_cutting()
            event.accept()
            return
        if self._measure_armed:
            at = screen_to_hole(event.scenePos(), self.document.board, self.side)
            if event.button() == Qt.MouseButton.LeftButton:
                self.measure_click(at)
            elif event.button() == Qt.MouseButton.RightButton:
                self._disarm_measure()
            event.accept()
            return
        if self._connect_armed:
            at = screen_to_hole(event.scenePos(), self.document.board, self.side)
            if event.button() == Qt.MouseButton.LeftButton:
                self.connect_click(at)
            elif event.button() == Qt.MouseButton.RightButton:
                self._disarm_connect()
            event.accept()
            return
        if self._net_pin_target is not None:
            at = screen_to_hole(event.scenePos(), self.document.board, self.side)
            if event.button() == Qt.MouseButton.LeftButton:
                self.net_pin_click(at)
            elif event.button() == Qt.MouseButton.RightButton:
                # Right-click finishes the net, the same gesture that finishes a trace.
                self.commit_net_pins()
            event.accept()
            return
        if self._draw_kind is not None:
            at = screen_to_hole(event.scenePos(), self.document.board, self.side)
            if event.button() == Qt.MouseButton.LeftButton:
                self.draw_press(at)
            elif event.button() == Qt.MouseButton.RightButton:
                # Right-click ends a trace where it is, which is what a chain-drawing tool
                # in any editor does. Under two holes it cancels instead.
                self.commit_drawing()
            event.accept()
            return
        if self._armed_footprint is not None and event.button() == Qt.MouseButton.LeftButton:
            anchor = screen_to_hole(event.scenePos(), self.document.board, self.side)
            self.place_armed(anchor)
            event.accept()
            return
        if self._armed_footprint is not None and event.button() == Qt.MouseButton.RightButton:
            self.arm_placement(None)  # Right-click cancels, as it does in every editor.
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not event.modifiers():
            index = self.handle_at(event.scenePos())
            if index is not None and self.begin_reshape(index):
                event.accept()
                return
            # A ring's click is its finding's, as a click on its row; a handle of the copper
            # that click selected, on the same hole, still takes the next press.
            if self.pick_finding_at(event.scenePos()) == "ring":
                event.accept()
                return
            if self.grab_copper(event.scenePos()):
                event.accept()
                return
            if self.cycle_pick(event.scenePos()):
                event.accept()
                return
        super().mousePressEvent(event)

    def reference_placements(
        self, transform: QTransform
    ) -> dict[str, tuple[QPointF, QPointF] | None]:
        """Every printed reference's place at this zoom (``settle_reference_placements``),
        worked out once for the layer, the legend and every part's hit area.

        Kept until something that could move one changes: the zoom (a reference holds a
        pixel size, so the board it covers changes with it -- panning does not, since the
        places are an anchor on the board and an offset in pixels), a part's place, turn,
        value or pin names, the notes, or the legend."""
        items = [
            item
            for item in self.component_items.values()
            if item.show_reference and item.isVisible()
        ]
        notes = getattr(self, "board_note_items", {})
        legend = getattr(self, "legend_item", None)
        key = (
            round(transform.m11(), 6), round(transform.m12(), 6),
            round(transform.m21(), 6), round(transform.m22(), 6),
            self.side,
            getattr(self, "show_board_notes", False),
            tuple(
                (id(note), note.pos().x(), note.pos().y(), note.isVisible())
                for note in notes.values()
            ),
            (id(legend), legend.isVisible()) if legend is not None else None,
            tuple(
                (
                    id(item), item.pos().x(), item.pos().y(), item.rotation(),
                    item.shown_value(), item.show_pin_names, item.isSelected(),
                )
                for item in items
            ),
        )
        if self._reference_cache is None or self._reference_cache[0] != key:
            self._reference_cache = (key, settle_reference_placements(items, transform))
        return self._reference_cache[1]

    def placing_face(self) -> BoardSide:
        """The face a part placed now goes on: the one in view, except on a solderless
        breadboard, which has no underside to put one on."""
        if self.side == "bottom" and not is_breadboard(self.document.board):
            return "bottom"
        return "top"

    def placement_roles_for(self, footprint_id: str | None) -> PinRoles:
        """The roles a part placed from here in ``footprint_id`` takes: the catalog
        part's, in the package they were read for, and none in any other."""
        if footprint_id is None or footprint_id != self.placement_roles_footprint_id:
            return ()
        return self.placement_pin_roles

    def place_armed(self, anchor: HoleCoord) -> DispatchResult | None:
        """Dispatch ``component.place`` for the armed footprint. Also the seam tests drive.

        A placement that lands on an occupied hole is NOT refused here. Two pins in one hole is
        a legal document that describes a board you probably do not want, which makes it DRC's
        business, not a command's (see the division of responsibility in commands.py). The ghost
        warns in red beforehand and ``overlapped`` says so afterwards, so the user is told twice
        and still gets to decide.
        """
        if self.bus is None or self._armed_footprint is None or self._armed_id is None:
            return None
        self.last_placement_overlapped = self._placement_blocked(anchor)
        self.last_placement_on_a_dead_hole = self.placement_lands_on_nothing(anchor)
        if self._armed_part_id is not None:
            part = next((p for p in self.bus.document.parts if p.id == self._armed_part_id), None)
            if part is None:
                # Placed or deleted another way while it was in hand.
                self.arm_placement(None)
                return None
            result = self.bus.dispatch(
                "part.place",
                PlacePartsPayload(
                    placements=(
                        PartPlacement(
                            id=part.id,
                            anchor=anchor,
                            rotation=self._armed_rotation,
                            mirrored=(
                                None if self.placing_face() == "bottom" else self._armed_mirrored
                            ),
                            side=self.placing_face(),
                        ),
                    ),
                    label=f"Place {part.ref} at {format_hole(anchor, self.document.board)}",
                ),
            )
            self.componentPlaced.emit(result)
            return result
        result = self.bus.dispatch(
            "component.place",
            PlaceComponentPayload(
                # From the BUS's document, not this scene's. The scene holds a snapshot that is
                # only refreshed after a command lands, so reading the reference from it would
                # hand out a name that is already taken -- and the bus would refuse the second
                # part of every pair as a duplicate ref.
                # Free in the whole system: the window's bus shows the board in front
                # as ``document``, and a reference another board holds is not free.
                ref=next_reference(
                    self.bus.system_document, self._armed_id, self.placement_prefix
                ),
                value=self.placement_value,
                footprint_id=self._armed_id,
                anchor=anchor,
                rotation=self._armed_rotation,
                # Placed while the board is turned over, it goes in from the face in view:
                # on the solder side, turned over, which is what mirrors it.
                mirrored=None if self.placing_face() == "bottom" else self._armed_mirrored,
                pin_names=self.placement_pin_names,
                pin_roles=self.placement_roles_for(self._armed_id),
                symbol=self.placement_symbol,
                side=self.placing_face(),
            ),
        )
        self.componentPlaced.emit(result)
        return result

    def mouseReleaseEvent(self, event: Any) -> None:
        if self._draw_drag is not None and event.button() == Qt.MouseButton.LeftButton:
            self.draw_release(screen_to_hole(event.scenePos(), self.document.board, self.side))
            event.accept()
            return
        if self._reshape is not None:
            moved = self._reshape_path is not None
            held = self._reshape[0]
            self.finish_reshape()
            if not moved and not self.cycle_pick(event.scenePos()):
                # Copper pressed and let go where it was is a click: it selects what was
                # pressed -- and where copper lies over copper, the next one.
                self.select_conductors([held])
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._say_drag("")
        self.commit_pending_moves()
        self.commit_off_board_drop()

    def report_drag(self) -> str:
        """Whether the parts being dragged can land where they are, said while they are
        dragged rather than after the release: each one's outline goes red where it cannot,
        and the line returned -- and shown over every view of this board -- says where the
        part held is going and what is in the way: "R1 → D11 · 1 pin in a used hole".

        A DRAG USED TO SAY NOTHING UNTIL IT WAS OVER. The placement ghost has always been red
        where a part cannot go; a part already on the board, dragged, was the one gesture
        that found out from a refusal in the status bar. It asks ``_landing_problems``, the
        ghost's own question, with every part that moves taken off the board first -- a
        group moves rigidly, so its members can only meet what stays.
        """
        grabbed = self.mouseGrabberItem()
        moving = [
            item for item in self.component_items.values() if item.pending_anchor != item.comp.anchor
        ]
        if not isinstance(grabbed, ComponentItem) or not moving:
            self._clear_drag_marks()
            self._say_drag("")
            return ""
        occupied = self._occupied_pins({item.comp.id for item in moving})
        off = used = unpadded = 0
        for item in moving:
            problems = self._landing_problems(
                item.fp, item.pending_anchor, item.comp.rotation, item.comp.mirrored, occupied
            )
            off, used, unpadded = off + problems[0], used + problems[1], unpadded + problems[2]
            item.set_drag_blocked(any(problems))
        board = self.document.board
        where = format_hole(grabbed.pending_anchor, board)
        who = grabbed.comp.ref
        if len(moving) > 1:
            who = f"{who} {t('and {count} more').format(count=len(moving) - 1)}"
        line = f"{who} → {where}"
        if off:
            line += f" · {t('off the board')}"
        elif used:
            line += " · " + counted(
                used, t("{count} pin in a used hole"), t("{count} pins in a used hole")
            )
        elif unpadded:
            line += " · " + counted(
                unpadded,
                t("{count} pin where there is no pad"),
                t("{count} pins where there is no pad"),
            )
        self._say_drag(line)
        return line

    def _say_drag(self, text: str) -> None:
        """Over every view of this board that is still there. Asked of ``views()`` rather
        than through a signal, because a scene outlives a view it was connected to and a
        signal into a deleted view raises in the event loop of whatever runs next."""
        for view in self.views():
            if isinstance(view, BoardView):
                view.show_drag(text)

    def _clear_drag_marks(self) -> None:
        for item in self.component_items.values():
            item.set_drag_blocked(False)

    def component_at(self, pos: QPointF) -> ComponentItem | None:
        """The topmost part under a scene position, or None.

        Walks this scene's own component table rather than calling ``itemAt``, which
        answers a different question: it returns the topmost item of ANY kind, so a
        conductor or a ratsnest line lying over a part -- which is the normal state of a
        routed board -- would swallow the click and report no part at all. Ties go to the
        highest z, so two overlapping parts resolve to the one the user can see.

        The one thing that does take the click from a part is copper drawn OVER it, on the
        face being looked at, with the pointer on the copper itself: that is what a left
        click there selects (:meth:`conductor_at`), and a right-click or a double-click
        meaning the part underneath would be acting on something the user did not pick.
        """
        best: ComponentItem | None = None
        for item in self.component_items.values():
            if not item.contains(item.mapFromScene(pos)):
                continue
            if best is None or item.zValue() >= best.zValue():
                best = item
        if best is not None:
            over = self.conductor_at(pos)
            if over is not None and over.zValue() > best.zValue():
                return None
            return best
        # The thing at the end of a part's wires is that part, to the right-click menu and
        # a double-click: what is done to it is done to the part.
        for thing in self.off_board_items.values():
            if thing.shape().contains(thing.mapFromScene(pos)):
                return self.component_items.get(thing.comp.id)
        return None

    def connector_at(self, pos: QPointF) -> str | None:
        """The id of the edge connector whose finger is under a scene position, or None --
        by the fingers' own shape, never the board-sized bounding rectangle."""
        for connector_id, item in self.connector_items.items():
            if item.shape().contains(item.mapFromScene(pos)):
                return connector_id
        return None

    def _via_holes(self) -> tuple[HoleCoord, ...]:
        """The vias on the board. Asked only where there is a run on the component side,
        so a board without one -- nearly every board -- builds no occupancy for it."""
        if not any(
            c.side == "top" and contacts_every_path_hole(c) for c in self.document.conductors
        ):
            return ()
        return vias(self.document, build_occupancy(self.document, self.lookup))

    def conductor_at(self, pos: QPointF) -> ConductorItem | None:
        """The topmost conductor under a scene position, or None -- by its clickable band,
        ties to the highest z, as :meth:`component_at` does for parts."""
        best: ConductorItem | None = None
        for item in self.conductor_items.values():
            if not item.contains(item.mapFromScene(pos)):
                continue
            if best is None or item.zValue() >= best.zValue():
                best = item
        return best

    def mouseDoubleClickEvent(self, event: Any) -> None:
        """Double-clicking a part asks the host to open it.

        Ignored outright while a mode is armed. Every mode gives the FIRST click of the
        pair a meaning of its own -- a double-click while drawing has already laid two
        steps of a trace -- so opening a dialog on top of that would interrupt the tool
        with a window the user did not ask for.
        """
        if self._draw_kind in self._CORNER_KINDS and event.button() == Qt.MouseButton.LeftButton:
            # The second half of a double-click is a click on the pad the first half just
            # reached, which is what finishes a solder run (``draw_click``). Said here because
            # Qt's own double-click handler never calls ``mousePressEvent``.
            self.draw_click(screen_to_hole(event.scenePos(), self.document.board, self.side))
            event.accept()
            return
        if self.in_a_mode or event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        note = self.board_note_at(event.scenePos())
        if note is not None:
            self.boardNoteActivated.emit(note.note.id)
            event.accept()
            return
        item = self.component_at(event.scenePos())
        if item is None:
            super().mouseDoubleClickEvent(event)
            return
        self.componentActivated.emit(item.comp.id)
        event.accept()

    #: Hole steps an arrow key moves the selection, plain and with Shift held.
    NUDGE_STEP = 1
    NUDGE_STEP_FAST = 5

    def keyPressEvent(self, event: Any) -> None:
        """Arrow keys move the selected parts one hole at a time.

        Dispatched as ``component.move``, the same command a drag ends in -- so a nudge
        undoes, journals and reaches an agent's view of the board identically. Placing a part
        exactly is far easier by keyboard than by dragging at 2.54 mm pitch, and the arrow
        keys were previously spent on scrolling a view that already pans with the middle
        button and both scrollbars.
        """
        deltas = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if event.key() == Qt.Key.Key_Escape and (self.cancel_reshape() or self.cancel_drag()):
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.in_a_mode:
            self.leave_mode()
            event.accept()
            return
        if self._net_pin_target is not None and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.commit_net_pins()
            event.accept()
            return
        if self._draw_kind is not None and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.commit_drawing()
            event.accept()
            return
        if self._draw_kind in self._CORNER_KINDS and event.key() == Qt.Key.Key_Slash:
            self.flip_draw_corner()
            event.accept()
            return
        delta = deltas.get(Qt.Key(event.key()))
        if delta is None or self.bus is None or not self.selected_component_ids():
            super().keyPressEvent(event)
            return
        fast = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = self.NUDGE_STEP_FAST if fast else self.NUDGE_STEP
        d_col, d_row = delta
        # The keys are named for the screen, and the solder side is the board mirrored:
        # hole_to_screen reflects x, so a column further along is a step to the LEFT
        # there. A drag is unaffected because it round-trips through screen_to_hole; the
        # arrows have to make the same correction by hand or Right moves the part left.
        if self.side == "bottom":
            d_col = -d_col
        self.nudge_selection(d_col * step, d_row * step)
        event.accept()

    def nudge_selection(self, d_col: int, d_row: int) -> list[DispatchResult]:
        """Move every selected part by a hole offset. Also the seam tests drive."""
        if self.bus is None:
            return []
        # SNAPSHOT FIRST, then dispatch. The first dispatch rebuilds this scene, which
        # destroys every item -- so a loop that both reads items and dispatches is reading
        # destroyed objects from its second iteration onwards.
        targets = [
            (item.comp.id, HoleCoord(col=item.comp.anchor.col + d_col, row=item.comp.anchor.row + d_row))
            for item in self.component_items.values()
            if item.isSelected()
        ]
        results = self._dispatch_moves(targets)
        if results:
            self.moveCommitted.emit(results)
        return results

    def _dispatch_moves(self, moves: list[tuple[str, HoleCoord]]) -> list[DispatchResult]:
        """One part is ``component.move``; several are ONE ``component.moveMany``.

        A group dragged or nudged together is one decision, so it is one undo step: five
        parts moved with one gesture used to take five Ctrl+Z presses to put back, and a
        refusal part-way through left the group torn apart. The batch is all-or-nothing --
        a locked part in the selection refuses the whole move and says which part, which
        is the honest answer rather than moving everything around it.
        """
        if self.bus is None or not moves:
            return []
        if len(moves) == 1:
            comp_id, anchor = moves[0]
            return [self.bus.dispatch("component.move", MoveComponentPayload(id=comp_id, anchor=anchor))]
        return [
            self.bus.dispatch(
                "component.moveMany",
                MoveComponentsPayload(
                    placements=tuple(
                        ComponentPlacement(id=comp_id, anchor=anchor) for comp_id, anchor in moves
                    ),
                    label=f"Move {count_noun(len(moves), 'component')}",
                ),
            )
        ]

    def drag_in_flight(self) -> bool:
        """Whether a part or a label is being dragged and has left where it was: what an
        Escape now would put back."""
        if not isinstance(self.mouseGrabberItem(), ComponentItem | BoardNoteItem):
            return False
        return any(
            item.pending_anchor != item.comp.anchor for item in self.component_items.values()
        ) or any(item.moved for item in self.board_note_items.values())

    def cancel_drag(self) -> bool:
        """Put back everything a drag in flight has moved, and make the rest of the
        gesture inert. True if there was one.

        By a REBUILD, which is the one source of truth this scene already has for "where
        is everything": the items are re-made at the document's anchors, the item holding
        the mouse goes with them, and the release that follows finds nothing pending. The
        same thing happens to a move the bus refuses (see ``ComponentItem``).
        """
        if not self.drag_in_flight():
            return False
        self._build()
        self._say_drag("")
        return True

    def commit_pending_moves(self) -> list[DispatchResult]:
        """Dispatch ``component.move`` for every item whose snapped position differs
        from its last-known document anchor. Called on mouse release (never per drag
        frame -- see the module docstring), and directly by tests so drag behaviour is
        exercisable without synthesizing real Qt mouse events.
        """
        if self.bus is None:
            return []
        # Snapshotted before any dispatch, for the reason given in nudge_selection: the first
        # dispatch rebuilds the scene and destroys these items. This loop happened to survive
        # that because pending_anchor and comp are plain Python attributes, which a wrapper
        # whose C++ object is gone will still hand over -- an accident, not a design.
        pending = [
            (comp_id, item.pending_anchor)
            for comp_id, item in self.component_items.items()
            if item.pending_anchor != item.comp.anchor
        ]
        # Asked before the dispatch rebuilds the items, of the landing the drag showed.
        staying = self._occupied_pins({comp_id for comp_id, _at in pending})
        self.last_move_on_a_dead_hole = any(
            self._landing_problems(
                item.fp, item.pending_anchor, item.comp.rotation, item.comp.mirrored, staying
            )[2]
            for comp_id, item in self.component_items.items()
            if item.pending_anchor != item.comp.anchor
        )
        moved_notes = [
            (note_id, item.placement())
            for note_id, item in self.board_note_items.items()
            if item.moved
        ]
        results = self._dispatch_moves(pending)
        for note_id, (at, dx, dy) in moved_notes:
            results.append(
                self.bus.dispatch(
                    "board.note.update",
                    UpdateBoardNotePayload(id=note_id, at=at, offset_x_mm=dx, offset_y_mm=dy),
                )
            )
        if results:
            self.moveCommitted.emit(results)
        return results


#: Zoom bounds in scene pixels per millimetre. Below the minimum a whole board is a few
#: hundred pixels and nothing is distinguishable; above the maximum a single pad fills the
#: viewport. Both ends are reachable by accident on a trackpad, so they are clamped.
MIN_SCALE = 1.5
MAX_SCALE = 90.0

#: Going to a finding (``BoardView.center_on_holes``) frames at least this many holes each
#: way round it, and never closer than ``FINDING_MAX_SCALE`` pixels per millimetre. Two
#: pads named by a finding were framed alone, at the zoom's limit: a click on a row put
#: two pads across the whole view, with nothing round them to say where on the board they
#: were (Sinan's dev4 walk).
FINDING_FRAME_PITCHES = 8
FINDING_MAX_SCALE = 24.0


class CameraFlight(QObject):
    """Log-scale camera interpolation for 2D ``QGraphicsView`` canvases.

    Interpolates ``log(scale)`` and scene centre together with ``OutCubic`` easing so zoom
    velocity stays perceptually constant, cancels cleanly on manual navigation, and snaps
    immediately under Reduce Motion or while the view is hidden.
    """

    def __init__(self, view: QGraphicsView) -> None:
        super().__init__(view)
        self._view = view
        self._anim: QVariantAnimation | None = None
        self._start_center = QPointF()
        self._end_center = QPointF()
        self._start_log_scale = 0.0
        self._end_log_scale = 0.0
        self._target_scale = 1.0
        self._on_done: Callable[[], None] | None = None

    @property
    def is_running(self) -> bool:
        return self._anim is not None

    @property
    def target_scale(self) -> float:
        return self._target_scale

    @property
    def target_center(self) -> QPointF:
        return QPointF(self._end_center)

    def cancel(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._on_done = None

    def fly_to(
        self,
        center: QPointF,
        scale: float,
        *,
        duration_ms: int = 240,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self.cancel()
        target_scale = max(1e-3, float(scale))
        self._target_scale = target_scale
        self._end_center = QPointF(center)
        cur_scale = max(1e-3, float(self._view.transform().m11()))
        cur_center = self._view.mapToScene(self._view.viewport().rect().center())
        dur = motion.duration(duration_ms) if self._view.isVisible() else 0
        dist = math.hypot(center.x() - cur_center.x(), center.y() - cur_center.y())
        log_diff = abs(math.log(target_scale / cur_scale))
        if dur <= 0 or (dist < 0.25 and log_diff < 1e-3):
            self._apply(target_scale, center)
            if on_done is not None:
                on_done()
            return

        self._start_center = cur_center
        self._start_log_scale = math.log(cur_scale)
        self._end_log_scale = math.log(target_scale)
        self._on_done = on_done

        anim = QVariantAnimation(self)
        anim.setDuration(dur)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._step)
        anim.finished.connect(self._finish)
        self._anim = anim
        anim.start()

    def _apply(self, scale: float, center: QPointF) -> None:
        self._view.resetTransform()
        self._view.scale(scale, scale)
        self._view.centerOn(center)

    def _step(self, value: object) -> None:
        t_val = float(value) if isinstance(value, (int, float)) else 1.0
        s = math.exp(self._start_log_scale + (self._end_log_scale - self._start_log_scale) * t_val)
        cx = self._start_center.x() + (self._end_center.x() - self._start_center.x()) * t_val
        cy = self._start_center.y() + (self._end_center.y() - self._start_center.y()) * t_val
        self._apply(s, QPointF(cx, cy))

    def _finish(self) -> None:
        self._anim = None
        self._apply(self._target_scale, self._end_center)
        done = self._on_done
        self._on_done = None
        if done is not None:
            done()


class SpotlightPulse(QObject):
    """Brief cosmetic concentric ring pulse at a navigated scene target.

    Strictly cosmetic: never triggers under Reduce Motion, never paints when ``_on_paper``
    is true (1:1 PDF/PNG export), and automatically clears when finished.
    """

    def __init__(self, view: QGraphicsView) -> None:
        super().__init__(view)
        self._view = view
        self._anim: QVariantAnimation | None = None
        self._center: QPointF | None = None
        self._base_radius = 3.0
        self._colour_hex: str | None = None
        self._progress = 0.0

    @property
    def active(self) -> bool:
        return self._center is not None and self._anim is not None

    def _invalidate(self) -> None:
        if self._center is not None:
            reach = self._base_radius + 8.0
            dirty = QRectF(
                self._center.x() - reach,
                self._center.y() - reach,
                reach * 2.0,
                reach * 2.0,
            )
            self._view.invalidateScene(dirty, QGraphicsScene.SceneLayer.ForegroundLayer)
        else:
            self._view.invalidateScene(QRectF(), QGraphicsScene.SceneLayer.ForegroundLayer)
        self._view.viewport().update()

    def clear(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        had = self._center is not None
        if had:
            self._invalidate()
        self._center = None
        self._progress = 0.0
        if had:
            self._view.viewport().update()

    def trigger(
        self,
        center: QPointF,
        *,
        radius_mm: float = 3.0,
        colour_hex: str | None = None,
        duration_ms: int = 650,
    ) -> None:
        dur = motion.duration(duration_ms) if self._view.isVisible() else 0
        if dur <= 0:
            self.clear()
            return
        if self._anim is not None:
            self._anim.stop()
        self._center = QPointF(center)
        self._base_radius = max(1.5, float(radius_mm))
        self._colour_hex = colour_hex
        self._progress = 0.0
        anim = QVariantAnimation(self)
        anim.setDuration(dur)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._step)
        anim.finished.connect(self.clear)
        self._anim = anim
        anim.start()
        self._invalidate()

    def _step(self, value: object) -> None:
        self._progress = float(value) if isinstance(value, (int, float)) else 1.0
        self._invalidate()

    def paint(self, painter: QPainter) -> None:
        if self._center is None or self._anim is None or _on_paper(painter):
            return
        p = max(0.0, min(1.0, self._progress))
        base = QColor(self._colour_hex or theme.ACTIVE.accent)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Soft radial wash inside the target area.
        wash = QColor(base)
        wash.setAlphaF((1.0 - p) * 0.22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(wash)
        painter.drawEllipse(self._center, self._base_radius, self._base_radius)

        # Leading expanding ring with subtle bright core so it reads over green/blue boards.
        r1 = self._base_radius + 4.2 * p
        alpha1 = ((1.0 - p) ** 1.25) * 0.94
        c1 = QColor(base)
        c1.setAlphaF(alpha1)
        pen1 = QPen(c1, 3.0)
        pen1.setCosmetic(True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen1)
        painter.drawEllipse(self._center, r1, r1)

        core = QColor("#ffffff")
        core.setAlphaF(alpha1 * 0.65)
        pen_core = QPen(core, 1.2)
        pen_core.setCosmetic(True)
        painter.setPen(pen_core)
        painter.drawEllipse(self._center, r1, r1)

        # Trailing inner ring for subtle depth.
        if p > 0.16:
            p2 = (p - 0.16) / 0.84
            r2 = self._base_radius * 0.60 + 3.0 * p2
            c2 = QColor(base)
            c2.setAlphaF(((1.0 - p2) ** 1.25) * 0.72)
            pen2 = QPen(c2, 1.8)
            pen2.setCosmetic(True)
            painter.setPen(pen2)
            painter.drawEllipse(self._center, r2, r2)

        painter.restore()


class FlipCurtain(QWidget):
    """The board turning over (``BoardView.turn_over``): the face seen before, pictured,
    turning edge-on about the middle of the view, and the face after turning in from
    edge-on -- as a hand turns a board over to solder it.

    The scene under it is ALREADY the other face. The curtain is two pictures and a
    quarter of a second; it takes no click and changes nothing, so a click while it turns
    lands on the board as it now is."""

    done = Signal()

    #: How far the eye is from the board, in widths of the view: the perspective of the
    #: turn, enough to read as turning rather than squeezing.
    EYE_DISTANCE = 2.5

    def __init__(
        self, viewport: QWidget, before: QPixmap, after: QPixmap, ms: int, background: QColor
    ) -> None:
        super().__init__(viewport)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(viewport.rect())
        self._before = before
        self._after = after
        self._background = background
        self._turn = 0.0
        self._over = False
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(ms)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.valueChanged.connect(self._on_turn)
        animation.finished.connect(self.finish)
        self._animation = animation
        animation.start()

    def _on_turn(self, value: object) -> None:
        self._turn = float(cast(float, value))
        self.update()

    def finish(self) -> None:
        """Land: the board as it now is, and the curtain gone. Once."""
        if self._over:
            return
        self._over = True
        self._animation.stop()
        self.hide()
        self.deleteLater()
        self.done.emit()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._background)
        angle = 180.0 * self._turn
        picture = self._before if angle < 90.0 else self._after
        tilt = angle if angle < 90.0 else angle - 180.0
        half_w, half_h = self.width() / 2.0, self.height() / 2.0
        turned = QTransform()
        turned.translate(half_w, half_h)
        turned.rotate(tilt, Qt.Axis.YAxis, self.width() * self.EYE_DISTANCE)
        turned.translate(-half_w, -half_h)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setTransform(turned)
        painter.drawPixmap(0, 0, picture)
        # Darker as it goes edge-on, the way a face turned from the light is.
        painter.resetTransform()
        shade = QColor(0, 0, 0, round(70 * math.sin(math.radians(angle))))
        painter.fillRect(self.rect(), shade)
        painter.end()


class ViewOverlay(QLabel):
    """A line of text pinned over the board itself.

    The status bar is the bottom edge of a window a metre wide and the cursor is in the
    middle of the board, which is exactly where "why is my click doing nothing" gets
    asked. A mode is that question's usual answer, so what is armed and how to leave it
    has to be where the eye already is.

    TRANSPARENT TO THE MOUSE, without exception. This sits over the top of the board and
    the whole point of a mode is that the next click goes to the board -- an overlay that
    ate the click it is describing would be worse than no overlay.
    """

    def __init__(self, parent: Any, name: str) -> None:
        super().__init__(parent)
        # Styled by name in the one stylesheet (``theme.stylesheet``).
        self.setObjectName(name)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.hide()

    def show_text(self, text: str) -> None:
        """Set the text and show it, or hide entirely when there is nothing to say."""
        if not text:
            self.hide()
            return
        self.setText(text)
        self.adjustSize()
        self.show()



#: What a symbol dragged off the schematic carries. Its own type rather than plain text:
#: a board must not accept an arbitrary string dropped on it, and Qt only offers a target
#: the formats the source actually declared.
#:
#: Here rather than in viewsch because this is the side that RECEIVES it, and because this
#: module already owns the vocabulary a drop lands in -- screen_to_hole, and a hole is the
#: only position a part has. One constant, two views, and the import goes the way that does
#: not make a cycle.
PART_MIME = "application/x-perfboard-studio-part"

#: What a row dragged out of the Parts panel carries: a FOOTPRINT id, which is a part that
#: does not exist yet -- as against ``PART_MIME``, which is a part that does.
#:
#: Two formats and not one flag, because the two drops are different commands onto
#: different lists: a footprint dropped on the board is ``component.place`` and a new
#: reference, a footprint dropped on the sheet is ``part.add``. A target that had to read
#: the payload to find out which it was would be a target that could get it wrong.
FOOTPRINT_MIME = "application/x-perfboard-studio-footprint"

#: How far below and to the right of the pointer a dragged part's picture is carried.
DRAG_PICTURE_OFFSET_PX = 18


def picture_beside_the_pointer(picture: QPixmap) -> QPixmap:
    """``picture`` with transparent room above and to its left, to be dragged with its hot
    spot at the top-left corner -- so it travels BESIDE the pointer instead of under it.

    Centred on the pointer, the picture covered the very holes the drop was aimed at, and
    on the board it covered the ghost that now shows where the part will really land.
    """
    offset = DRAG_PICTURE_OFFSET_PX
    ratio = picture.devicePixelRatio()
    padded = QPixmap(
        round(picture.width() + offset * ratio), round(picture.height() + offset * ratio)
    )
    padded.setDevicePixelRatio(ratio)
    padded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(padded)
    painter.drawPixmap(QPointF(offset, offset), picture)
    painter.end()
    return padded


def overlay_room(
    view: QGraphicsView, overlays: Sequence[QWidget], viewport: QRect
) -> tuple[int, int]:
    """(across, down): the room the visible bars laid over ``view`` take from its viewport's
    sides -- a bar along a side edge takes its width, one along the top or bottom its height.

    One function for both canvases, the board's fit and the sheet's, so the two cannot drift
    apart: the sheet fitted to the bare viewport ran under its zoom and Arrange bar at 1366
    px, and on nano-relay C3's wire could not be grabbed.
    """
    across = down = 0
    gap = 8
    for bar in overlays:
        if not bar.isVisible():
            continue
        corner = view.viewport().mapFromGlobal(bar.mapToGlobal(QPoint(0, 0)))
        box = QRect(corner, bar.size())
        if box.height() > box.width():
            side = box.right() if box.center().x() < viewport.center().x() else viewport.right() - box.left()
            across = max(across, side + gap)
        else:
            side = viewport.bottom() - box.top() if box.center().y() > viewport.center().y() else box.bottom()
            down = max(down, side + gap)
    return across, down


class BoardView(QGraphicsView):
    #: Gap between the top of the viewport and the mode banner.
    BANNER_MARGIN_PX = 10

    #: Emitted with the viewport position of a right-click that wants a menu. WHAT is on
    #: that menu is the host's business -- it owns the actions, and a view that built its
    #: own would be a second list of what can be done to a part, free to disagree with the
    #: menu bar about which of them are available.
    contextMenuRequested = Signal(QPoint)

    #: A part was dragged off the schematic and dropped on a hole. Carries the reference
    #: and the hole. The VIEW does not place it: which command that is depends on whether
    #: the part is in the design or already on the board, and that is the window's to know
    #: -- the same division contextMenuRequested above is drawn on.
    partDropped = Signal(str, object)

    #: A row was dragged out of the Parts panel and dropped on a hole. Carries the footprint
    #: id and the hole. Same division as ``partDropped``: the view reports what landed where
    #: and the window decides which command that is.
    footprintDropped = Signal(str, object)

    def __init__(self, scene: BoardScene) -> None:
        super().__init__(scene)
        # A symbol dragged from the sheet lands on a hole, which is the only position a
        # part has. See viewsch.PART_MIME.
        self.setAcceptDrops(True)
        self.board_scene = scene
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        #: A dashed frame round the viewport in this colour while the board shows
        #: something it does not have yet (Rearrange's cards); None otherwise.
        self._preview_frame: QColor | None = None
        self.scale(6, 6)  # ~6 px per mm to start
        self._panning = False
        self._pan_origin = QPointF()
        #: Which button the pan started on: the middle one, or the left with Space held.
        self._pan_button = Qt.MouseButton.MiddleButton
        #: Space is down, so the left button pans -- the laptop's middle button.
        self._space_held = False
        #: Every wheel pans, and Ctrl+wheel zooms (View > Mouse Wheel). The window sets it.
        self.wheel_scrolls = False
        #: The board was fitted and nobody has zoomed or panned since, so a resize -- a panel
        #: dragged wider, the window maximised, the docks laid out again -- fits it again
        #: (``resizeEvent``). A navigation of the person's own ends it (``_navigated``).
        self._fitted = False
        for scrollbar in (self.horizontalScrollBar(), self.verticalScrollBar()):
            # actionTriggered is somebody on the scrollbar; a resize moves it by setValue.
            scrollbar.actionTriggered.connect(lambda _action: self._navigated())
        # Children of the VIEWPORT, not of the view: the viewport is what the scrollbars
        # leave behind, so an overlay parented to it stays inside the board area and does
        # not drift under a scrollbar when one appears.
        self.mode_banner = ViewOverlay(self.viewport(), "modeBanner")
        self.empty_hint = ViewOverlay(self.viewport(), "emptyHint")
        #: Where a dragged part is going and what is in the way. Styled as the mode banner,
        #: and under it when a mode is up too.
        self.drag_banner = ViewOverlay(self.viewport(), "modeBanner")
        #: The board turning over, while it does (``turn_over``).
        self._curtain: FlipCurtain | None = None
        #: Smooth 2D camera flight and cosmetic target spotlight pulse.
        self._camera = CameraFlight(self)
        self._pulse = SpotlightPulse(self)
        self.viewport().installEventFilter(self)

    def set_preview_frame(self, colour: QColor | None) -> None:
        """Frame the viewport in ``colour``, dashed, or take the frame away (None).

        Painted here rather than by a stylesheet border: the view has no frame, and a
        border would also shrink the viewport and move the board under the pointer.
        Every repaint is a whole one while it shows, because a scroll moves the
        viewport's pixels and would carry the frame's edges along with the board."""
        self._preview_frame = colour
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate
            if colour is not None
            else QGraphicsView.ViewportUpdateMode.SmartViewportUpdate
        )
        self.viewport().update()

    def refresh_theme(self) -> None:
        """Repaint the viewport and any active preview frame in the current theme."""
        if self._preview_frame is not None:
            self._preview_frame = QColor(theme.ACTIVE.accent)
        self.resetCachedContent()
        self.viewport().update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self._preview_frame is None:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QPen(self._preview_frame, 2, Qt.PenStyle.DashLine))
        painter.drawRect(self.viewport().rect().adjusted(1, 1, -2, -2))
        painter.end()

    def drawForeground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        super().drawForeground(painter, rect)
        self._pulse.paint(painter)

    # -- turning the board over -----------------------------------------------

    #: How long the board takes to turn over, in milliseconds.
    FLIP_MS = 260

    def turn_over(self, turn: Callable[[], None]) -> None:
        """Run ``turn`` -- which shows the other face -- with the board seen turning over
        about the middle of the view (``FlipCurtain``).

        The solder side is the component side's mirror image, and that is what a beginner
        loses track of: the picture jumped, and which edge had gone where was a puzzle. The
        turn says it. The scene flips at once, under the curtain, so nothing waits on the
        animation; a press while it is turning lands it and flips straight back."""
        self._camera.cancel()
        self._pulse.clear()
        curtain = self._curtain
        if curtain is not None:
            curtain.finish()
        viewport = self.viewport()
        if (
            curtain is not None
            or motion.reduced()
            or not viewport.isVisible()
            or viewport.width() < 2
        ):
            turn()
            return
        before = self._frame()
        turn()
        after = self._frame()
        curtain = FlipCurtain(viewport, before, after, self.FLIP_MS, BACKGROUND)
        curtain.done.connect(self._curtain_down)
        # Under the banners: "Measuring" and its kind stay readable through the turn.
        curtain.lower()
        curtain.show()
        self._curtain = curtain

    def _curtain_down(self) -> None:
        self._curtain = None

    def _frame(self) -> QPixmap:
        """The board as the view shows it now, without the view's own overlays."""
        viewport = self.viewport()
        ratio = viewport.devicePixelRatioF()
        pixmap = QPixmap(round(viewport.width() * ratio), round(viewport.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(BACKGROUND)
        painter = QPainter(pixmap)
        painter.setRenderHints(self.renderHints())
        self.render(
            painter, QRectF(0, 0, viewport.width(), viewport.height()), viewport.rect()
        )
        painter.end()
        return pixmap

    # -- a part dropped from the sheet ---------------------------------------

    def _dropped_ref(self, event: QDropEvent | QDragMoveEvent) -> str | None:
        """The reference being dragged, if this is a part from the schematic."""
        return self._dropped_ref_from(event.mimeData())

    @staticmethod
    def _payload_from(data: QMimeData | None, fmt: str) -> str | None:
        """Split out from the event so it can be exercised without one: constructing a
        real QDropEvent needs a live drag, and what is being decided here is only whether
        the payload is ours.

        ``QMimeData.text`` alongside the typed payload: every drag this application starts
        sets both, and the string one needs no decoding dance to read back.
        """
        if data is None or not data.hasFormat(fmt):
            return None
        text = data.text().strip()
        return text or None

    @classmethod
    def _dropped_ref_from(cls, data: QMimeData | None) -> str | None:
        return cls._payload_from(data, PART_MIME)

    @classmethod
    def _dropped_footprint_from(cls, data: QMimeData | None) -> str | None:
        return cls._payload_from(data, FOOTPRINT_MIME)

    def _dropped_footprint(self, event: QDropEvent | QDragMoveEvent) -> str | None:
        return self._dropped_footprint_from(event.mimeData())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped_ref(event) is None and self._dropped_footprint(event) is None:
            event.ignore()
            return
        event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        what = self._dropped_ref(event) or self._dropped_footprint(event)
        if what is None:
            event.ignore()
            return
        # Said while the pointer is still moving, because the whole question during a drag
        # is "which hole is this going into" and the answer is otherwise invisible.
        hole = self._hole_under(event.position().toPoint())
        self.show_mode(f"{what} \u2192 {format_hole(hole, self.board_scene.document.board)}")
        landing = self._landing_of(event)
        if landing is not None:
            footprint, rotation, mirrored, moving = landing
            self.board_scene.show_drop_ghost(footprint, hole, rotation, mirrored, moving)
        event.acceptProposedAction()

    def _landing_of(
        self, event: QDropEvent | QDragMoveEvent
    ) -> tuple[Footprint, int, bool, str | None] | None:
        """What a drag would put down, and how: the footprint, its turn and flip, and the
        id of the part itself when it is already on the board. The same split the window
        makes on the drop -- ``component.move`` keeps a placed part's orientation, and
        ``part.place`` and a footprint from the list put one down unturned."""
        scene = self.board_scene
        ref = self._dropped_ref(event)
        if ref is not None:
            placed = next((c for c in scene.document.components if c.ref == ref), None)
            if placed is not None:
                footprint = scene.lookup(placed.footprint_id)
                if footprint is None:
                    return None
                return footprint, int(placed.rotation), placed.mirrored, placed.id
            part = next((p for p in scene.document.parts if p.ref == ref), None)
            footprint = scene.lookup(part.footprint_id) if part is not None else None
            return (footprint, 0, False, None) if footprint is not None else None
        footprint_id = self._dropped_footprint(event)
        footprint = scene.lookup(footprint_id) if footprint_id is not None else None
        if footprint is None:
            return None
        # Turned as the armed part is: the drop places it through the arming
        # (``MainWindow._on_footprint_dropped``), so that is how it will go down.
        rotation, mirrored = (
            scene.armed_orientation if scene.armed_footprint_id == footprint_id else (0, False)
        )
        return footprint, int(rotation), mirrored, None

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.show_mode("")
        self.board_scene.clear_drop_ghost()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.show_mode("")
        self.board_scene.clear_drop_ghost()
        hole = self._hole_under(event.position().toPoint())
        ref = self._dropped_ref(event)
        if ref is not None:
            event.acceptProposedAction()
            self.partDropped.emit(ref, hole)
            return
        footprint_id = self._dropped_footprint(event)
        if footprint_id is not None:
            event.acceptProposedAction()
            self.footprintDropped.emit(footprint_id, hole)
            return
        event.ignore()

    def _hole_under(self, point: QPoint) -> HoleCoord:
        return screen_to_hole(
            self.mapToScene(point), self.board_scene.document.board, self.board_scene.side
        )

    # -- overlays ------------------------------------------------------------

    def show_mode(self, text: str) -> None:
        """Say which mode is armed and how to leave it, or clear it with an empty string."""
        self.mode_banner.show_text(text)
        self._place_overlays()

    def show_drag(self, text: str) -> None:
        """Where a dragged part is going and what is in the way (``BoardScene.report_drag``),
        or nothing with an empty string."""
        self.drag_banner.show_text(text)
        self._place_overlays()

    def set_empty_hint(self, text: str) -> None:
        """Guidance for a board with nothing on it. Empty text takes it away."""
        self.empty_hint.show_text(text)
        self._place_overlays()

    #: How wide the guidance block is allowed to get. Measured rather than chosen: a line
    #: much longer than this stops being read as a sentence and starts being skipped.
    HINT_WIDTH_PX = 460

    def _place_overlays(self) -> None:
        area = self.viewport().rect()

        # isHidden(), never isVisible(). A widget is "visible" only once every ancestor is
        # too, so during window construction -- which is exactly when the first hint is set
        # -- these labels are shown but not yet visible, and an isVisible() test would skip
        # placing them and leave them where the un-laid-out viewport put them.
        banner = self.mode_banner
        if not banner.isHidden():
            # One line if it fits, because the banner is a label rather than a paragraph
            # and a two-line label reads as a warning. Only a viewport too narrow for the
            # sentence makes it wrap.
            # Measured afresh every time: a banner fixed to the room on one pass came back
            # at exactly that width on the next, never wider than the room, so it was never
            # wrapped again and a longer line was cut off at both ends.
            banner.setWordWrap(False)
            banner.setMinimumWidth(0)
            banner.setMaximumWidth(QWIDGETSIZE_MAX)
            banner.adjustSize()
            # Clear of the tool rail down the left, and as far in from the right, so it is
            # still centred: over the rail it hid the tools and the rail hid its first words.
            across, _down = self._overlay_room(area)
            widest = max(area.width() - 2 * max(self.BANNER_MARGIN_PX, across), 120)
            if banner.width() > widest:
                banner.setWordWrap(True)
                banner.setFixedWidth(widest)
                banner.adjustSize()
            banner.move(
                area.center().x() - banner.width() // 2,
                area.top() + self.BANNER_MARGIN_PX,
            )

        drag = self.drag_banner
        if not drag.isHidden():
            drag.adjustSize()
            top = area.top() + self.BANNER_MARGIN_PX
            if not banner.isHidden():
                top = banner.geometry().bottom() + self.BANNER_MARGIN_PX // 2
            drag.move(area.center().x() - drag.width() // 2, top)

        hint = self.empty_hint
        if not hint.isHidden():
            hint.setFixedWidth(min(self.HINT_WIDTH_PX, max(area.width() - 80, 160)))
            hint.adjustSize()
            hint.move(
                area.center().x() - hint.width() // 2, area.center().y() - hint.height() // 2
            )

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """Re-place the overlays whenever the area under them changes size.

        Watching the VIEWPORT rather than overriding resizeEvent on the view, because the
        viewport is what actually changes: a scrollbar appearing takes 15 px off it without
        the view being resized at all, and the first layout after show() resizes the
        viewport when the view has already had its resize event. Getting this wrong leaves
        the guidance block sitting off to one side of the board, which is exactly where a
        first-time user is not looking.
        """
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            self._place_overlays()
        return bool(super().eventFilter(watched, event))

    def contextMenuEvent(self, event: Any) -> None:
        """Ask the host for a menu, unless a mode has a claim on this click.

        Two guards rather than one, and both are needed. ``in_a_mode`` covers a platform
        that delivers the context-menu event on the PRESS; ``take_consumed_right_click``
        covers one that delivers it on the release, after a press that ended the mode --
        which is Windows, and is exactly where a menu would appear over a trace the user
        had just finished.
        """
        if self.board_scene.in_a_mode or self.board_scene.take_consumed_right_click():
            event.accept()
            return
        self.contextMenuRequested.emit(event.pos())
        event.accept()

    def current_scale(self) -> float:
        return float(self.transform().m11())

    def _clamped_factor(self, factor: float) -> float:
        """The part of a zoom step that stays inside [MIN_SCALE, MAX_SCALE].

        Clamped rather than refused: the last notch before a limit used to do nothing at
        all, so the zoom stopped one step short of its own bound and the wheel appeared
        to have died. Landing ON the bound is what the bound means.
        """
        current = self.current_scale()
        target = min(MAX_SCALE, max(MIN_SCALE, current * factor))
        return target / current if current else 1.0

    def _clamp_scale(self) -> None:
        """Pull a scale ``fitInView`` chose back inside the zoom range.

        A fit is not exempt from the limits: a wide board in a narrow central area, or two
        pads framed from a DRC finding in a large viewport, can land outside them -- and
        then EVERY wheel step is outside the range too, so the wheel is dead both ways.
        """
        factor = self._clamped_factor(1.0)
        if factor != 1.0:
            self.scale(factor, factor)

    def wheelEvent(self, event: Any) -> None:
        """Zoom or pan, by the rule the sheet uses too (``canvasinput.wheel_intent``)."""
        intent = wheel_intent(event, self.wheel_scrolls)
        if intent.zoom_steps:
            self._navigated()
            factor = self._clamped_factor(1.15**intent.zoom_steps)
            if factor != 1.0:
                self.scale(factor, factor)
        elif intent.pan_x or intent.pan_y:
            self._pan_by(intent.pan_x, intent.pan_y)
        event.accept()

    def event(self, event: QEvent) -> bool:
        # ESCAPE IS THE WINDOW'S, except in the middle of a drag. The window's shortcut
        # leaves a tool from anywhere and fires before this view sees the key, so a drag
        # could not be called off: let go, and the part landed wherever the pointer was.
        # Accepting the override is how a focused widget takes a key back -- the sheet does
        # the same for R -- and only while there is a drag to cancel. Copper picked up in the
        # Select tool is a drag as well: without it here, Escape went to the window, which
        # had no tool to leave, and the release then put the copper down where it was.
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
            and (self.board_scene.drag_in_flight() or self.board_scene.reshaping)
        ):
            event.accept()
            return True
        # A trackpad pinch the platform reports as a gesture (macOS) rather than as the
        # Ctrl+wheel ``wheelEvent`` already zooms (Windows).
        if (
            isinstance(event, QNativeGestureEvent)
            and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture
        ):
            self._navigated()
            factor = self._clamped_factor(1.0 + event.value())
            if factor != 1.0:
                self.scale(factor, factor)
            self._refresh_hover()
            event.accept()
            return True
        return bool(super().event(event))

    def _pan_by(self, dx: float, dy: float) -> None:
        """Move the board by this many pixels: right and down are positive."""
        self._navigated()
        h = self.horizontalScrollBar()
        v = self.verticalScrollBar()
        h.setValue(h.value() - round(dx))
        v.setValue(v.value() - round(dy))
        self._refresh_hover()

    def zoom_by(self, factor: float) -> None:
        """Zoom about the viewport centre, for a toolbar button or a keyboard shortcut."""
        base_scale = self._camera.target_scale if self._camera.is_running else self.current_scale()
        target_center = (
            self._camera.target_center
            if self._camera.is_running
            else self.mapToScene(self.viewport().rect().center())
        )
        self._navigated()
        target_scale = min(MAX_SCALE, max(MIN_SCALE, base_scale * factor))
        if abs(target_scale - self.current_scale()) < 1e-4:
            return
        self._camera.fly_to(
            target_center, target_scale, duration_ms=140, on_done=self._refresh_hover
        )

    #: Widgets laid over the view's edges -- the tool rail at the left, the view bar at the
    #: bottom right (``FloatingBar``) -- that a fit leaves room for (``fit_board``).
    overlays: tuple[QWidget, ...] = ()

    def fit_board(self, *, animate: bool = False) -> None:
        """The whole board in view, clear of the bars laid over the view.

        Fitted to the viewport, the board's top-left corner was under the tool rail and a
        corner hole chosen there half hidden by it (lead's R2 review). Each bar keeps its
        side's room AND the opposite side's, so the board, centred as the view centres
        anything smaller than itself, clears it -- a fit that leaned the board to one side
        would be undone the moment the view re-centred it.
        """
        rect = self.sceneRect()
        viewport = self.viewport().rect()
        across, down = self._overlay_room(viewport)
        room = viewport.adjusted(across, down, -across, -down)
        if rect.isEmpty() or room.width() < 80 or room.height() < 80:
            self._camera.cancel()
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            self._clamp_scale()
            self._fitted = True
            return
        scale = min((room.width() - 4) / rect.width(), (room.height() - 4) / rect.height())
        scale = min(MAX_SCALE, max(MIN_SCALE, scale))
        if animate and not motion.reduced() and self.isVisible():
            # Mark navigated during flight so scrollbar resizeEvents do not snap back.
            self._navigated()

            def _landed() -> None:
                self._fitted = True
                self._refresh_hover()

            self._camera.fly_to(rect.center(), scale, duration_ms=260, on_done=_landed)
            return
        self._camera.cancel()
        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(rect.center())
        self._clamp_scale()
        self._fitted = True

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Fit the board again if it was fitted and nobody has moved it since.

        A fit was good for the size it was made at: a panel dragged wider, the window
        maximised, or the docks laid out again after the first showing left the board where
        it was, smaller than the room or slid under the tool rail. The bars are at the new
        edges already -- their filter on this view saw the resize before this handler did
        (``FloatingBar.eventFilter``) -- so the fit leaves them their room."""
        super().resizeEvent(event)
        if self._fitted:
            self.fit_board(animate=False)

    def _navigated(self) -> None:
        """The person zoomed or panned: a resize leaves the board where they put it."""
        self._camera.cancel()
        self._fitted = False

    def look_at(self, point: QPointF, *, pulse: bool = True) -> None:
        """Centre on one point -- a part somebody asked to go to."""
        self._navigated()
        self._camera.fly_to(
            point, self.current_scale(), duration_ms=240, on_done=self._refresh_hover
        )
        if pulse:
            self._pulse.trigger(point, radius_mm=2.8)

    def _overlay_room(self, viewport: QRect) -> tuple[int, int]:
        """(across, down): the room the visible bars take from the viewport's sides
        (``overlay_room``)."""
        return overlay_room(self, self.overlays, viewport)

    def _refresh_hover(self) -> None:
        """Re-read what is under a pointer that has not moved.

        After a pan or a keyboard zoom the scene under the pointer has changed without a
        mouse-move event, so the placement ghost and the status bar's hole address would
        go on describing the hole that scrolled away.
        """
        local = self.viewport().mapFromGlobal(QCursor.pos())
        if self.viewport().rect().contains(local):
            self.board_scene.hover_at(self.mapToScene(local))

    def leaveEvent(self, event: Any) -> None:
        self.board_scene.hover_left()
        super().leaveEvent(event)

    # Middle-button pan, and the left button with Space held for a laptop that has no
    # middle one. Rubber-band selection owns the left button otherwise, and reaching for a
    # scrollbar to cross a 60-column board is the kind of friction that makes an editor
    # feel unfinished.
    @staticmethod
    def _shift_as_ctrl(event: Any) -> Any:
        """The same event with Ctrl added when Shift is held.

        ONE SELECTION GRAMMAR ON BOTH CANVASES: Shift and Ctrl each add a part to the
        selection or take it back out. Qt's own selection reads only Ctrl, so on the board
        Shift+click REPLACED the selection, while on the sheet Shift was the one that added
        -- the same gesture did opposite things a panel apart. Handing Qt the Ctrl it
        understands is what makes Shift mean it too, for a click and for a rubber band.
        """
        modifiers = event.modifiers()
        if not modifiers & Qt.KeyboardModifier.ShiftModifier:
            return event
        return QMouseEvent(
            event.type(),
            event.position(),
            event.globalPosition(),
            event.button(),
            event.buttons(),
            modifiers | Qt.KeyboardModifier.ControlModifier,
        )

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_held
        ):
            self._panning = True
            self._pan_button = event.button()
            self._pan_origin = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(self._shift_as_ctrl(event))

    def mouseMoveEvent(self, event: Any) -> None:
        if self._panning:
            delta = event.position() - self._pan_origin
            self._pan_origin = event.position()
            self._pan_by(delta.x(), delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if self._panning and event.button() == self._pan_button:
            self._panning = False
            self._restore_cursor()
            event.accept()
            return
        # The release too: Qt takes a Ctrl-clicked part back out of the selection on the
        # release, not the press, so a drag can carry it first.
        super().mouseReleaseEvent(self._shift_as_ctrl(event))

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Space:
            # Held, it turns the left button into the hand. Taken here, autorepeat and all,
            # so it never reaches the scene or a mode as a key of its own.
            if not event.isAutoRepeat():
                self._space_held = True
                if not self._panning:
                    self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self._space_held = False
                if not self._panning:
                    self._restore_cursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event: Any) -> None:
        # A Space released while another widget had the keyboard never comes back here,
        # and a left button that went on panning afterwards would be a board that had
        # stopped selecting.
        self._space_held = False
        if not self._panning:
            self._restore_cursor()
        super().focusOutEvent(event)

    def _restore_cursor(self) -> None:
        """The hand while Space is held, and otherwise what the window gives a mode: the
        cross. A pan used to unset the cursor outright, so a part being placed lost its
        cross the first time the board was panned under it."""
        if self._space_held:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        elif self.board_scene.in_a_mode:
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.viewport().unsetCursor()

    def _holes_rect(
        self, holes: Sequence[HoleCoord], board: Board, side: BoardSide, margin: float
    ) -> QRectF:
        # A finding about a rail names a finger's cell, drawn on the finger rather than in
        # the border; the cells are the scene's, so only for the board the scene shows.
        scene = self.scene()
        cells = (
            scene.finger_cells
            if isinstance(scene, BoardScene) and scene.document.board == board
            else {}
        )
        pts = [path_point_to_screen(h, board, side, cells) for h in holes]
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        return QRectF(
            min(xs) - margin,
            min(ys) - margin,
            max(xs) - min(xs) + 2 * margin,
            max(ys) - min(ys) + 2 * margin,
        )

    def center_on_holes(self, holes: Sequence[HoleCoord], board: Board, side: BoardSide) -> None:
        """Zoom to frame the given holes, for the Problems drawer: close enough to see the
        pads a finding names, with the board round them in view (``FINDING_FRAME_PITCHES``,
        ``FINDING_MAX_SCALE``)."""
        if not holes:
            return
        self._navigated()
        tight = self._holes_rect(holes, board, side, 1.5)
        rect = self._holes_rect(holes, board, side, 6.0)
        least = FINDING_FRAME_PITCHES * board.pitch
        grow_x = max(0.0, least - rect.width()) / 2
        grow_y = max(0.0, least - rect.height()) / 2
        rect = rect.adjusted(-grow_x, -grow_y, grow_x, grow_y)
        viewport = self.viewport().rect()
        if viewport.width() >= 16 and viewport.height() >= 16 and not rect.isEmpty():
            scale = min(
                (viewport.width() - 4) / rect.width(),
                (viewport.height() - 4) / rect.height(),
            )
            scale = min(FINDING_MAX_SCALE, MAX_SCALE, max(MIN_SCALE, scale))
            self._camera.fly_to(
                rect.center(), scale, duration_ms=280, on_done=self._refresh_hover
            )
        else:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            if self.current_scale() > FINDING_MAX_SCALE:
                factor = FINDING_MAX_SCALE / self.current_scale()
                self.scale(factor, factor)
                self.centerOn(rect.center())
            self._clamp_scale()
        radius = min(4.2, max(1.8, max(tight.width(), tight.height()) * 0.45))
        self._pulse.trigger(tight.center(), radius_mm=radius)

    def reveal_holes(self, holes: Sequence[HoleCoord], board: Board, side: BoardSide) -> None:
        """Bring the given holes into view WITHOUT changing zoom, unless they cannot fit.

        Used when selecting a whole net: a net can span the board, so framing it would zoom
        right out, and framing a two-pin net would zoom right in. Either way the user loses
        the working magnification they had chosen, having asked only to see a net.
        """
        if not holes:
            return
        rect = self._holes_rect(holes, board, side, 4.0)
        viewport_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        if rect.width() > viewport_scene.width() or rect.height() > viewport_scene.height():
            self._navigated()
            viewport = self.viewport().rect()
            if viewport.width() >= 16 and viewport.height() >= 16 and not rect.isEmpty():
                scale = min(
                    (viewport.width() - 4) / rect.width(),
                    (viewport.height() - 4) / rect.height(),
                )
                scale = min(MAX_SCALE, max(MIN_SCALE, scale))
                self._camera.fly_to(
                    rect.center(), scale, duration_ms=260, on_done=self._refresh_hover
                )
            else:
                self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
                self._clamp_scale()
            self._pulse.trigger(rect.center(), radius_mm=3.2)
            return
        if not viewport_scene.contains(rect):
            self._navigated()
            self._camera.fly_to(
                rect.center(), self.current_scale(), duration_ms=240, on_done=self._refresh_hover
            )
            self._pulse.trigger(rect.center(), radius_mm=3.2)


def copper_shape(conductor: Conductor) -> tuple[str, str, tuple[tuple[int, int], ...]]:
    """A piece of copper as what it is on the board: its kind on these holes on this face,
    whichever end it was drawn from. What the comparison with the wiring before leaves
    out, and what Redo Wiring counts as kept (``main._copper_change``)."""
    holes = tuple((hole.col, hole.row) for hole in conductor.path)
    return (conductor.kind, conductor.side, min(holes, holes[::-1]))


def gone_copper(
    before: Sequence[Conductor], after: Sequence[Conductor]
) -> tuple[Conductor, ...]:
    """Conductors in ``before`` whose shape is no longer in ``after``.

    Computed once when a route commits rather than on every repaint, so copper removed
    later by hand or by Remove All Wiring does not turn into dashed ghosts from an earlier
    route.
    """
    kept = Counter(copper_shape(c) for c in after)
    gone: list[Conductor] = []
    for conductor in before:
        shape = copper_shape(conductor)
        if kept[shape]:
            kept[shape] -= 1
            continue
        gone.append(conductor)
    return tuple(gone)
