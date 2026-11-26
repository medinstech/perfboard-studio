"""A pinout card as an SVG page: every pin where its pad is, with what it can do.

``pinout`` decides what is on the card; this draws it. The page is plain SVG Tiny 1.2 --
the profile QtSvg renders, so the window shows the very file a builder saves -- which is
why nothing here leans on ``dominant-baseline`` or a font-family list Qt does not parse:
the families are ink (:class:`PinoutInk`), and the window hands in the one it has.

**THE MIDDLE IS THE CALLER'S.** The part itself, drawn from above, is the board view's own
drawing (``ui/view2d``, ``ui/moduleart``), which is Qt. The engine imports no Qt, so it
takes that drawing as SVG TEXT (``art``) and places it in the card's frame; with none it
draws a plain body -- a DIP's package and legs, a module's board and pads -- which is
what the MCP server writes. The labels are laid out the same either way, so a card with
art and one without differ in the middle and nowhere else.

**EVERY WORD IS SAID THROUGH THE PHRASEBOOK**, the guide's, so a Turkish card is written
with no interface loaded. Pin names, ports and function labels are the maker's and are
never translated; what a kind of function, a warning and a document are called is.

Pure: a card, a language and ink in, a string out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, TypeAlias
from xml.sax.saxutils import escape

from .phrasebook import GuideLanguage, Phrasebook, phrasebook
from .pinfunctions import Document, DocumentKind, FunctionKind, PinFunction, PinWarning
from .pinout import PinoutCard, PinoutPin

#: The colour groups a function is drawn in: one colour per kind a builder looks for, and
#: the rest (timers, the comparator, the crystal, reset, debugging, the reference) in one.
KindGroup: TypeAlias = Literal[  # noqa: UP040
    "pwm", "adc", "dac", "touch", "int", "uart", "spi", "i2c", "other"
]

KIND_GROUPS: tuple[KindGroup, ...] = (
    "pwm", "adc", "dac", "touch", "int", "uart", "spi", "i2c", "other",
)

#: Which group each kind is drawn in; ``None`` for a kind the card says once instead of on
#: every pin (a pin-change interrupt is on every AVR port pin).
GROUP_OF: dict[FunctionKind, KindGroup | None] = {
    "pwm": "pwm", "adc": "adc", "dac": "dac", "touch": "touch", "int": "int",
    "uart": "uart", "spi": "spi", "i2c": "i2c", "timer": "other", "comparator": "other",
    "clock": "other", "reset": "other", "debug": "other", "ref": "other", "pcint": None,
}

#: What the legend calls each group.
GROUP_WORDS: dict[KindGroup, str] = {
    "pwm": "PWM",
    "adc": "Analog input (ADC)",
    "dac": "Analog output (DAC)",
    "touch": "Touch",
    "int": "External interrupt",
    "uart": "Serial (UART)",
    "spi": "SPI",
    "i2c": "I2C",
    "other": "Other: {kinds}",
}

#: The kinds in the "other" group, as the legend lists them.
OTHER_WORDS: dict[FunctionKind, str] = {
    "timer": "timer",
    "comparator": "comparator",
    "clock": "crystal/clock",
    "reset": "reset",
    "debug": "debugging",
    "ref": "reference",
}

#: What each warning says under the card.
WARNING_WORDS: dict[PinWarning, str] = {
    "reset-fuse": (
        "Reset pin: it is an I/O only with the RSTDISBL fuse set, and then the chip can no "
        "longer be programmed over ISP."
    ),
    "analog-only": "Analog input only: it cannot be a digital I/O.",
    "led": "The board's LED is on this pin: as an input, the LED and its resistor load it.",
    "upload-serial": "Programs are uploaded through this pin: disconnect its circuit to upload.",
    "strapping": (
        "Strapping pin: read at power-up to choose how the chip boots; do not hold it high or "
        "low while it starts."
    ),
    "input-only": "Input only: this pin has no output driver.",
    "flash": "Wired to the module's flash memory: do not use it in the circuit.",
    "adc2-wifi": "ADC2 channel: it cannot be read while Wi-Fi is running.",
}

#: How a document is named, by kind; the title and the number are names.
DOCUMENT_WORDS: dict[DocumentKind, str] = {
    "datasheet": "{title} datasheet",
    "schematic": "{title} schematic",
    "user-guide": "{title} user guide",
    "board-file": "{title} board file",
}

#: Font families for a file opened anywhere: a list, which every browser reads. The window
#: hands in a single family, the one QtSvg can parse.
FONT_FAMILY = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
MONO_FAMILY = "Consolas, 'DejaVu Sans Mono', monospace"


@dataclass(frozen=True, slots=True)
class PinoutInk:
    """Every colour and font on a card. The window builds one from its theme each time it
    paints, so a card follows a theme switch; the two below are for a file."""

    background: str
    border: str
    text: str
    muted: str
    faint: str
    #: A pin name's chip, by role.
    name_fill: str
    name_line: str
    power_fill: str
    power_text: str
    ground_fill: str
    ground_text: str
    power_out_fill: str
    power_out_text: str
    warning_line: str
    warning_fill: str
    warning_text: str
    #: The plain body: a module's board, a DIP's package.
    module: str
    module_line: str
    module_text: str
    package: str
    package_text: str
    leg: str
    pad: str
    pad_hole: str
    leader: str
    kinds: dict[KindGroup, str] = field(default_factory=dict)
    #: How strongly a function's chip is tinted with its kind's colour.
    kind_opacity: float = 0.16
    font_family: str = FONT_FAMILY
    mono_family: str = MONO_FAMILY


PINOUT_LIGHT = PinoutInk(
    background="#ffffff", border="#e4e4e8", text="#18181b", muted="#5a5a66", faint="#80808c",
    name_fill="#f1f1f4", name_line="#d3d3d9",
    power_fill="#fdeaea", power_text="#c42727", ground_fill="#e4e4e8", ground_text="#18181b",
    power_out_fill="#fdf3e1", power_out_text="#9a5a00",
    warning_line="#b45309", warning_fill="#fde68a", warning_text="#7c2d12",
    module="#2b3442", module_line="#151a22", module_text="#e4e7ee",
    package="#2a2b2f", package_text="#c9ccd3", leg="#a7acb5",
    pad="#d4a62a", pad_hole="#2b3442", leader="#c9c9d1",
    kinds={
        "pwm": "#7c3aed", "adc": "#0f766e", "dac": "#0e7490", "touch": "#a16207",
        "int": "#be185d", "uart": "#1d4ed8", "spi": "#c2410c", "i2c": "#15803d",
        "other": "#52525b",
    },
    kind_opacity=0.16,
)

PINOUT_DARK = PinoutInk(
    background="#1b1e25", border="#2a2f3a", text="#e4e7ee", muted="#a0a8b8", faint="#6b7387",
    name_fill="#272b36", name_line="#363c4a",
    power_fill="#3a1f24", power_text="#ef5b5f", ground_fill="#363c4a", ground_text="#e4e7ee",
    power_out_fill="#3a2f1c", power_out_text="#e5a840",
    warning_line="#e5a840", warning_fill="#3a2f1c", warning_text="#e5a840",
    module="#2e3646", module_line="#4a5468", module_text="#e4e7ee",
    package="#0e0f12", package_text="#c9ccd3", leg="#8b93a3",
    pad="#d4a62a", pad_hole="#2e3646", leader="#3a404d",
    kinds={
        "pwm": "#a78bfa", "adc": "#2dd4bf", "dac": "#22d3ee", "touch": "#facc15",
        "int": "#f472b6", "uart": "#60a5fa", "spi": "#fb923c", "i2c": "#4ade80",
        "other": "#a1a1aa",
    },
    kind_opacity=0.22,
)

# -- measures, in the page's pixels --------------------------------------------------

#: Page pixels per millimetre of the part: a Nano is 500 px tall, an ESP32 board 600.
MM = 11.0
MARGIN = 22.0
HEADER = 64.0
#: A chip's height, the gap between two, the padding inside one.
CHIP_H = 17.0
GAP = 3.0
PAD_X = 5.0
LABEL_PX = 11.0
#: The leader from the frame to the labels, and the slot for a pin's warnings (one triangle
#: each, side by side) and for its pad-number tag.
LEADER = 10.0
WARNING_W = 16.0
TAG_W = 18.0
TAG_SLOT = 24.0
#: Labels above or below the part go down (or up) a staircase, one pin to a step, so no
#: label crosses another pin's leader. One row of pins fans out: its left half steps out to
#: the left and its right half to the right, each with its outermost pin nearest the part,
#: which makes the card about half as tall as one staircase would.
STAIR = CHIP_H + 7.0
TAG_H = 14.0
#: The narrowest the foot's text is wrapped to, on a card whose drawing is narrower still.
FOOT_MIN_W = 300.0


def _text_width(text: str, size: float) -> float:
    """A label's width, estimated: the engine has no font metrics, and a chip a little too
    wide reads better than one its text spills out of."""
    return len(text) * size * 0.58


def _wrap(text: str, size: float, limit: float) -> list[str]:
    """``text`` in lines no wider than ``limit`` (estimated), broken between words."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        tried = f"{line} {word}" if line else word
        if line and _text_width(tried, size) > limit:
            lines.append(line)
            line = word
        else:
            line = tried
    return [*lines, line] if line else lines


def _chip_width(text: str, size: float = LABEL_PX) -> float:
    return _text_width(text, size) + 2 * PAD_X


def _number(value: float) -> str:
    """A coordinate as the page writes it: one decimal, no trailing zero."""
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def shown_functions(pin: PinoutPin) -> tuple[PinFunction, ...]:
    """What a pin's chips list: not a kind said once for the card, and not a label that
    only repeats the pin's own name or its port ("AREF" on AREF)."""
    return tuple(
        f for f in pin.functions
        if GROUP_OF[f.kind] is not None and f.label not in (pin.name, pin.port)
    )


def shown_port(pin: PinoutPin) -> str | None:
    """The port beside a pin's name, unless it is the name ("PB3" on a bare ATtiny)."""
    return None if pin.port is None or pin.port == pin.name else pin.port


def document_title(document: Document, say: Phrasebook) -> str:
    named = say(DOCUMENT_WORDS[document.kind], title=document.title)
    return f"{named} {document.number}" if document.number else named


class _Page:
    """The elements of one page, in drawing order."""

    def __init__(self, ink: PinoutInk) -> None:
        self.ink = ink
        self.parts: list[str] = []

    def rect(
        self, x: float, y: float, w: float, h: float, fill: str, *, rx: float = 0.0,
        stroke: str | None = None, width: float = 1.0, opacity: float | None = None,
    ) -> None:
        attrs = (
            f'x="{_number(x)}" y="{_number(y)}" width="{_number(w)}" height="{_number(h)}" '
            f'rx="{_number(rx)}" fill="{fill}"'
        )
        if opacity is not None:
            attrs += f' fill-opacity="{opacity:g}"'
        if stroke is not None:
            attrs += f' stroke="{stroke}" stroke-width="{width:g}"'
        self.parts.append(f"<rect {attrs}/>")

    def circle(self, x: float, y: float, r: float, fill: str) -> None:
        self.parts.append(
            f'<circle cx="{_number(x)}" cy="{_number(y)}" r="{_number(r)}" fill="{fill}"/>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, stroke: str) -> None:
        self.parts.append(
            f'<line x1="{_number(x1)}" y1="{_number(y1)}" x2="{_number(x2)}" '
            f'y2="{_number(y2)}" stroke="{stroke}" stroke-width="1"/>'
        )

    def text(
        self, x: float, y: float, text: str, fill: str, *, size: float = LABEL_PX,
        anchor: str = "start", bold: bool = False, mono: bool = False,
        turned: bool = False,
    ) -> None:
        family = self.ink.mono_family if mono else self.ink.font_family
        turn = f' transform="rotate(90 {_number(x)} {_number(y)})"' if turned else ""
        weight = "bold" if bold else "normal"
        self.parts.append(
            f'<text x="{_number(x)}" y="{_number(y)}" font-family="{escape(family)}" '
            f'font-size="{size:g}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{turn}>{escape(text)}</text>'
        )

    def warning(self, x: float, y: float, number: int) -> None:
        """A numbered triangle, its number matching a line under the card."""
        h = 13.0
        half = h * 0.58
        points = (
            f"{_number(x)},{_number(y - h / 2)} {_number(x + half)},{_number(y + h / 2)} "
            f"{_number(x - half)},{_number(y + h / 2)}"
        )
        self.parts.append(
            f'<polygon points="{points}" fill="{self.ink.warning_fill}" '
            f'stroke="{self.ink.warning_line}" stroke-width="1.2" stroke-linejoin="round"/>'
        )
        self.text(x, y + h / 2 - 2.5, str(number), self.ink.warning_text, size=8.5,
                  anchor="middle", bold=True)


_SVG_ROOT = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)
_VIEW_BOX = re.compile(r'viewBox="([^"]+)"')
_DROPPED = re.compile(r"<(title|desc)\b[^>]*>.*?</\1>|<\?xml[^>]*\?>|<!DOCTYPE[^>]*>", re.DOTALL)


def _art_inside(art: str, x: float, y: float, w: float, h: float) -> str:
    """``art`` -- an SVG document whose viewBox is the card's frame -- as a group scaled
    into the page rectangle ``x, y, w, h``.

    Its root, title and description go; its definitions and drawing stay as they are, so
    the engine never has to understand what the board view drew.
    """
    root = _SVG_ROOT.search(art)
    if root is None:
        raise ValueError("the art is not an SVG document")
    box = _VIEW_BOX.search(root.group(0))
    if box is None:
        raise ValueError("the art has no viewBox")
    bx, by, bw, bh = (float(v) for v in box.group(1).replace(",", " ").split())
    body = art[root.end():]
    body = body[: body.rfind("</svg>")] if "</svg>" in body else body
    body = _DROPPED.sub("", body).strip()
    sx, sy = w / bw, h / bh
    return (
        f'<g transform="translate({_number(x)} {_number(y)}) scale({sx:.6g} {sy:.6g}) '
        f'translate({_number(-bx)} {_number(-by)})">{body}</g>'
    )


def pinout_svg(
    card: PinoutCard,
    *,
    language: GuideLanguage = "en",
    ink: PinoutInk = PINOUT_LIGHT,
    art: str | None = None,
) -> str:
    """The card as an SVG document.

    ``art`` is the part drawn from above as an SVG document whose viewBox is
    ``card.frame`` in millimetres (``ui/pinoutart.py`` makes it from the board view); with
    none, the card draws a plain body.
    """
    say = phrasebook(language)
    page = _Page(ink)
    pins = card.pins
    # A pad number goes in a tag outside the frame wherever the middle does not print it:
    # always on a module (the app's count, not the maker's print -- said under the card),
    # and on a chip whose middle is the art.
    tagged = art is not None or not card.numbered_by_maker
    tag_slot = TAG_SLOT if tagged else 0.0
    warn_index = {w: i + 1 for i, w in enumerate(card.warnings)}

    def chips_width(pin: PinoutPin) -> float:
        width = _chip_width(pin.name) + 2 + GAP
        port = shown_port(pin)
        if port is not None:
            width += _chip_width(port) + GAP
        return width + sum(_chip_width(f.label) + GAP for f in shown_functions(pin))

    def side_width(side: str) -> float:
        on_side = [chips_width(p) for p in pins if p.side == side]
        return tag_slot + LEADER + warn_slot + max(on_side) if on_side else 0.0

    def stair(side: str) -> list[PinoutPin]:
        return sorted((p for p in pins if p.side == side), key=lambda p: (p.x, p.y))

    def own_width(pin: PinoutPin) -> float:
        return 6.0 + WARNING_W * len(pin.warnings) if pin.warnings else 0.0

    def fan(side: str) -> tuple[list[PinoutPin], list[PinoutPin]]:
        """The pins whose labels go out to the left and to the right, each list in the
        order of its steps, the first nearest the part. One row of two or more pins splits
        down the middle; anything else is one staircase going right."""
        steps = stair(side)
        one_row = len(steps) > 1 and max(p.y for p in steps) - min(p.y for p in steps) < 0.5
        if not one_row:
            return [], list(reversed(steps))
        cut = (len(steps) + 1) // 2
        return steps[:cut], list(reversed(steps[cut:]))

    def stair_height(side: str) -> float:
        count = max(len(half) for half in fan(side))
        return (TAG_H + 6 if tagged else 0.0) + LEADER + count * STAIR if count else 0.0

    warn_slot = 6.0 + WARNING_W * max((len(p.warnings) for p in pins), default=0)
    fx0, fx1, fy0, fy1 = card.frame
    # The left half of a fanned row reaches out past the frame's left edge.
    reach = max(
        (6 + own_width(p) + chips_width(p) - (p.x - fx0) * MM
         for side in ("above", "below") for p in fan(side)[0]),
        default=0.0,
    )
    ox = MARGIN + max(side_width("left"), reach) - fx0 * MM
    oy = MARGIN + HEADER + stair_height("above") - fy0 * MM

    def px(mm: float) -> float:
        return ox + mm * MM

    def py(mm: float) -> float:
        return oy + mm * MM

    width = px(fx1) + side_width("right") + MARGIN
    for side in ("above", "below"):
        for pin in fan(side)[1]:
            width = max(width, px(pin.x) + 6 + own_width(pin) + chips_width(pin) + MARGIN)

    # -- the heading -------------------------------------------------------------------
    facts: list[str] = []
    if card.mcu_name:
        facts.append(card.mcu_name)
    if card.logic is not None:
        facts.append(say("Logic {volts}", volts=card.logic.volts))
        if card.logic.pin_max_ma is not None:
            facts.append(say("at most {ma} mA per pin", ma=f"{card.logic.pin_max_ma:g}"))
    facts.append(say("seen from above"))
    subtitle = "  ·  ".join(facts)
    # The card is as wide as its drawing or its heading; the foot is wrapped to fit it, and
    # widens a narrow card only when there is a foot to wrap.
    footed = bool(
        card.warnings or card.documents or card.any_pin or "pcint" in card.kinds
        or not card.numbered_by_maker
    )
    drawn = width
    width = max(
        width,
        MARGIN + _text_width(card.title, 18) + MARGIN,
        MARGIN + _text_width(subtitle, 12) + MARGIN,
        MARGIN + FOOT_MIN_W + MARGIN if footed else 0.0,
    )
    # A card made wider by its heading or its foot has the part and its labels in the middle.
    ox += (width - drawn) / 2
    page.text(MARGIN, MARGIN + 16, card.title, ink.text, size=18, bold=True)
    page.text(MARGIN, MARGIN + 38, subtitle, ink.muted, size=12)

    # -- the middle --------------------------------------------------------------------
    bx0, bx1, by0, by1 = card.body
    if art is not None:
        page.parts.append(
            _art_inside(art, px(fx0), py(fy0), (fx1 - fx0) * MM, (fy1 - fy0) * MM)
        )
    elif card.numbered_by_maker and all(p.side in ("left", "right") for p in pins):
        # A chip: its package between the two rows of pads, legs out to them.
        xs = sorted({p.x for p in pins})
        inner0 = xs[0] + 1.0 if len(xs) > 1 else bx0
        inner1 = xs[-1] - 1.0 if len(xs) > 1 else bx1
        for pin in pins:
            y = py(pin.y)
            if pin.x < inner0:
                page.rect(px(pin.x) - 3, y - 3.5, px(inner0) - px(pin.x) + 3, 7, ink.leg, rx=1.5)
            else:
                page.rect(px(inner1), y - 3.5, px(pin.x) - px(inner1) + 3, 7, ink.leg, rx=1.5)
        x, w = px(inner0), (inner1 - inner0) * MM
        y, h = py(by0), (by1 - by0) * MM
        page.rect(x, y, w, h, ink.package, rx=3)
        page.parts.append(
            f'<path d="M {_number(x + w / 2 - 9)} {_number(y)} A 9 9 0 0 0 '
            f'{_number(x + w / 2 + 9)} {_number(y)} Z" fill="{ink.background}"/>'
        )
        page.circle(x + 9, y + 12, 3.2, ink.leg)
        page.text(x + w / 2, y + h / 2, card.title, ink.package_text, size=13,
                  anchor="middle", bold=True, turned=True)
        for pin in pins:
            inside = px(inner0) + 7 if pin.x < inner0 else px(inner1) - 7
            page.text(inside, py(pin.y) + 3.5, pin.number, ink.package_text, size=9,
                      anchor="start" if pin.x < inner0 else "end")
    else:
        page.rect(px(bx0), py(by0), (bx1 - bx0) * MM, (by1 - by0) * MM, ink.module, rx=6,
                  stroke=ink.module_line, width=1.5)
        page.text(px((bx0 + bx1) / 2), py((by0 + by1) / 2), card.title, ink.module_text,
                  size=14, anchor="middle", bold=True, turned=True)
        for pin in pins:
            page.circle(px(pin.x), py(pin.y), 0.85 * MM, ink.pad)
            page.circle(px(pin.x), py(pin.y), 0.38 * MM, ink.pad_hole)

    def tag(x: float, y: float, number: str) -> None:
        """A pad number in its frame, centred on ``x, y``."""
        page.rect(x - TAG_W / 2, y - TAG_H / 2, TAG_W, TAG_H, ink.background, rx=3,
                  stroke=ink.leader)
        page.text(x, y + 3.5, number, ink.faint, size=9, anchor="middle")

    def row(pin: PinoutPin, y: float, cursor: float, sign: float, slot_width: float) -> None:
        """A pin's warnings and chips on the line ``y``, out from ``cursor``."""
        # One triangle per warning, side by side, their numbers rising left to right on
        # every side of the part: so on the left the first is the furthest out.
        count = len(pin.warnings)
        for index, warning in enumerate(pin.warnings):
            slot = index if sign > 0 else count - 1 - index
            page.warning(cursor + sign * (WARNING_W * slot + WARNING_W / 2 + 3), y,
                         warn_index[warning])
        cursor += sign * slot_width

        def place(chip: float) -> float:
            nonlocal cursor
            x0 = cursor if sign > 0 else cursor - chip
            cursor += sign * (chip + GAP)
            return x0

        top, base = y - CHIP_H / 2, y + 4
        fill, colour = {
            "power": (ink.power_fill, ink.power_text),
            "ground": (ink.ground_fill, ink.ground_text),
            "power-out": (ink.power_out_fill, ink.power_out_text),
        }.get(pin.role or "", (ink.name_fill, ink.text))
        chip = _chip_width(pin.name) + 2
        x0 = place(chip)
        page.rect(x0, top, chip, CHIP_H, fill, rx=CHIP_H / 2,
                  stroke=ink.name_line if fill == ink.name_fill else None)
        page.text(x0 + chip / 2, base, pin.name, colour, anchor="middle", bold=True)
        port = shown_port(pin)
        if port is not None:
            chip = _chip_width(port)
            x0 = place(chip)
            page.text(x0 + chip / 2, base, port, ink.muted, size=10.5, anchor="middle",
                      mono=True)
        for function in shown_functions(pin):
            group = GROUP_OF[function.kind]
            assert group is not None
            colour = ink.kinds.get(group, ink.text)
            chip = _chip_width(function.label)
            x0 = place(chip)
            page.rect(x0, top, chip, CHIP_H, colour, rx=CHIP_H / 2, opacity=ink.kind_opacity)
            page.text(x0 + chip / 2, base, function.label, colour, size=10.5,
                      anchor="middle", bold=True)

    # -- the labels, out from the frame on each pin's side -------------------------------
    for pin in pins:
        if pin.side not in ("left", "right"):
            continue
        y = py(pin.y)
        sign = -1.0 if pin.side == "left" else 1.0
        cursor = px(fx0) - 4 if sign < 0 else px(fx1) + 4
        if tagged:
            tag(cursor + sign * TAG_W / 2, y, pin.number)
            cursor += sign * tag_slot
        page.line(cursor, y, cursor + sign * LEADER, y, ink.leader)
        row(pin, y, cursor + sign * LEADER, sign, warn_slot)
    # ...and down (or up) the staircase from the frame's bottom (or top) edge.
    for side, sign in (("above", -1.0), ("below", 1.0)):
        edge = py(fy0) if sign < 0 else py(fy1)
        left, right = fan(side)
        for half, going in ((left, -1.0), (right, 1.0)):
            for depth, pin in enumerate(half):
                x = px(pin.x)
                start = edge + sign * 3
                if tagged:
                    tag(x, start + sign * TAG_H / 2, pin.number)
                    start += sign * (TAG_H + 3)
                y = start + sign * (LEADER + depth * STAIR + CHIP_H / 2)
                page.line(x, start, x, y, ink.leader)
                page.line(x, y, x + going * 6, y, ink.leader)
                row(pin, y, x + going * 6, going, own_width(pin))

    # -- the legend, the notes, the warnings and the documents ---------------------------
    groups = _groups(card.kinds)
    notes: list[str] = []
    if "pcint" in card.kinds:
        notes.append(say(
            "Every port pin also has a pin-change interrupt (PCINT); the card does not show it."
        ))
    if card.any_pin:
        kinds = ", ".join(say(GROUP_WORDS[g]) for g in _groups(card.any_pin))
        notes.append(say(
            "{kinds} can be routed to any GPIO (the GPIO matrix); the card does not show it.",
            kinds=kinds,
        ))
    if not card.numbered_by_maker:
        notes.append(say(
            "The small framed numbers are the app's pad numbers (U1.2 on the schematic), not "
            "what is printed on the board."
        ))
    lines = [say(WARNING_WORDS[w]) for w in card.warnings]
    y = py(fy1) + stair_height("below") + 30
    x = MARGIN
    if groups or notes or lines or card.documents:
        # A rule over the foot; a card with no foot (a 555's names alone) ends at its labels.
        page.line(MARGIN, y - 14, width - MARGIN, y - 14, ink.border)
    else:
        y -= 30
    for group in groups:
        if group == "other":
            others = [say(OTHER_WORDS[k]) for k in card.kinds if GROUP_OF[k] == "other"]
            words = say(GROUP_WORDS["other"], kinds=", ".join(others))
        else:
            words = say(GROUP_WORDS[group])
        colour = ink.kinds.get(group, ink.text)
        step = _text_width(words, 11.5) + 26
        if x + step > width - MARGIN and x > MARGIN:
            x, y = MARGIN, y + 22
        page.rect(x, y - 11, 14, 14, colour, rx=7, opacity=0.25)
        page.circle(x + 7, y - 4, 3, colour)
        page.text(x + 20, y, words, ink.text, size=11.5)
        x += step + 14
    y += 24 if groups else 0
    room = width - 2 * MARGIN
    for note in notes:
        for part in _wrap(note, 11, room):
            page.text(MARGIN, y, part, ink.muted, size=11)
            y += 17
        y += 3
    y += 2
    for number, words in enumerate(lines, start=1):
        page.warning(MARGIN + 7, y - 4, number)
        for part in _wrap(words, 11.5, room - 22):
            page.text(MARGIN + 22, y, part, ink.text, size=11.5)
            y += 17
        y += 4
    if card.documents:
        y += 6
        named = "; ".join(document_title(d, say) for d in card.documents)
        for part in _wrap(say("Read from: {documents}", documents=named), 10, room):
            page.text(MARGIN, y, part, ink.faint, size=10)
            y += 14
        y -= 10
    height = y + MARGIN

    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.2" baseProfile="tiny" '
        f'width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">'
    )
    frame = (
        f'<rect x="0.5" y="0.5" width="{width - 1:.0f}" height="{height - 1:.0f}" rx="10" '
        f'fill="{ink.background}" stroke="{ink.border}"/>'
    )
    return head + "\n" + frame + "\n" + "\n".join(page.parts) + "\n</svg>\n"


def _groups(kinds: tuple[FunctionKind, ...]) -> list[KindGroup]:
    found: list[KindGroup] = []
    for kind in kinds:
        group = GROUP_OF[kind]
        if group is not None and group not in found:
            found.append(group)
    return found


__all__ = [
    "DOCUMENT_WORDS",
    "FONT_FAMILY",
    "GROUP_OF",
    "GROUP_WORDS",
    "KIND_GROUPS",
    "MONO_FAMILY",
    "OTHER_WORDS",
    "PINOUT_DARK",
    "PINOUT_LIGHT",
    "WARNING_WORDS",
    "KindGroup",
    "PinoutInk",
    "document_title",
    "pinout_svg",
    "shown_functions",
    "shown_port",
]
