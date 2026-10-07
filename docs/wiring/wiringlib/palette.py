# SPDX-License-Identifier: Apache-2.0
"""Every colour the drawings use, for the light sheet and for the dark one, in one place.

A drawing is made once, its colours written as tokens (`@@ink@@`, `@@wire-0f766e@@`), and resolve() turns it
into the light SVG and the dark SVG, which differ only in their colours (and in words drawn inside
Sheet.dark_only()). The dark one is for the dark theme of docs.fpgas.online: its paper is the theme's own
background, its ink light. themed() makes both for every drawing a generator writes.

One palette for every generator under docs/wiring/: their pictures sit on the pages of one site, so the
paper, the ink and the warnings must be the same colours on all of them, and a wire colour that two boards
both use (the teal, the rust, the purple) must turn into the same dark colour on both. A role that only one
board's drawings use says so in its description.

A colour is named by what it is and what it stands on, not by its value, because one value can mean two
things: "#fff" is the fill of a label box (dark on the dark sheet) and the text on a coloured tag (dark there
too, as the tag gets lighter), but the needle on the meter's black knob stays white. Things that stand on
something that keeps its colour in both (the yellow meter, the gold pads, a photograph) keep theirs.

Photographs are never recoloured: a photo's strokes are wrapped in PHOTO_START ... PHOTO_END, which resolve()
leaves as they are and strips. Anywhere else, a colour that is not a token stops the build.
"""

import re

# role: (light, dark, what it is). The light values are those the sheets were drawn with before there was a
# dark sheet, written exactly as they were, so the light sheets keep their colours.
ROLES = {
    # the sheet itself, and what is drawn straight on it
    "paper": ("#fbfaf7", "#131416", "the sheet; dark: Furo's dark background (--color-background-primary)"),
    "ink": ("#15181d", "#e3e6ea", "text and lines"),
    "muted": ("#5b6470", "#a9b0ba", "secondary text, dimension lines, the sample wire of the legend"),
    "faint": ("#c9ced6", "#4a5059", "the outline of a plug's box"),
    "red": ("#c62828", "#ff7b7b", "VCC, 5 V, warnings, the red probe lead, the marked corner"),
    "kicker": ("#0f766e", "#4fd1c5", "the small capitals over a sheet's title"),
    # surfaces drawn on the sheet, and their edges
    "box": ("#fff", "#202328", "a label box, a cavity, the heat shrink, the eye: white on the light sheet"),
    "box-edge": ("#9aa0a8", "#6b737d", "the outline of the host's pin name beside a wire"),
    "warn-fill": ("#fdecea", "#3d1c1c", "the box of a warning, an empty 5 V cavity"),
    "note-fill": ("#fff8e1", "#2e2914", "the box of what is not yet checked"),
    "housing": ("#f1f3f5", "#2c3036", "a Dupont housing, drawn cut open"),
    "empty": ("#d9dbde", "#3b4048", "an empty cavity"),
    "sketch-board": ("#c9ced6", "#50575f", "the circuit board in the 'seen from the wire side' sketch"),
    # black plastic and black wires: dark on the light sheet; on the dark sheet lighter, so they still show
    "body": ("#1d1f23", "#474d56", "black plastic: a plug, a header, a numbered disc"),
    "body-strip": ("#3a3d42", "#5d646e", "the lighter band of a plug, a housing in the sketch"),
    "black-wire": ("#1d1f23", "#c4c9d0", "a real black wire or the black probe lead, and its tip"),
    "on-body": (
        "#fff",
        "#fff",
        "white on black plastic: the --pins text, a disc's number, the needle on the meter's black knob",
    ),
    "on-wire": ("#fff", "#131416", "the words on a tag filled with a wire's colour, or red, or grey"),
    # things that keep their colour on both sheets, and what stands on them
    "gold": ("#e2b33c", "#e2b33c", "a gold pad, a wire's number token"),
    "on-gold": ("#1d1f23", "#1d1f23", "the number on a gold pad or token, and the token's edge"),
    "pad-danger": ("#ef9a9a", "#ef9a9a", "a 5 V pad"),
    "pad-unused": ("#6d6a5f", "#6d6a5f", "a pad nothing goes on"),
    "on-pad-unused": ("#d8d5cb", "#f3f1ea", "the number on such a pad: lighter on the dark sheet, for contrast"),
    "halo-on-body": ("#f1f3f5", "#f1f3f5", "the gap round a wire where it crosses a header's black body"),
    "mark": ("#ffd60a", "#ffd60a", "the yellow highlight on a photo, and a socket's name tag"),
    "mark-edge": ("#15181d", "#15181d", "the dark edge of a highlight and of its tag, on a photo"),
    "on-mark": ("#15181d", "#15181d", "the words on a yellow tag"),
    "photo-edge": ("#fff", "#fff", "the white edge of the marked corner, drawn on a photo"),
    "brass": ("#c9a227", "#c9a227", "a crimp terminal"),
    "copper": ("#b87333", "#b87333", "bare wire"),
    "meter": ("#f3c623", "#f3c623", "the meter's case"),
    "meter-display": ("#dfe8d8", "#dfe8d8", "the meter's display"),
    "on-meter": ("#15181d", "#15181d", "the word on the meter's display"),
    "knob": ("#1d1f23", "#1d1f23", "the meter's black knob"),
    # the Tiny Tapeout FPGA pictures (tt-fpga/picture.py)
    "board": ("#eef0f3", "#1b1d21", "a board drawn as a diagram: the demo board, the Pmod HAT"),
    "pad-ground": ("#aab1ba", "#3b4048", "a ground pin of a Pmod connector, and its key"),
    "pad-power": ("#f6c9c9", "#4a1f1f", "a power pin of a Pmod connector, and its key, edged red"),
    "shared-ring": ("#1d6fb8", "#6fb3f2", "the ring round a pin whose GPIO another port shares"),
    "cable-off": ("#8a929c", "#8a929c", "a cable the picture is not about, and its tag"),
    "caution-fill": ("#fff4d6", "#2e2914", "the gold-edged box of what has not been checked on a board"),
}

# The wire colours of every wiring.toml (light, as written there) and each one's dark counterpart: the same named
# colour, lighter, so that it shows on the dark sheet and dark words read on a tag of it. A colour that is
# drawn as ink on the light sheet (ground) is drawn as the dark sheet's ink.
WIRES = {
    "#0f766e": "#4fd1c5",  # teal: the Acorn's K2; the Tiny Tapeout board's uo_out
    "#b4491f": "#ff9466",  # rust: the Acorn's J2; the Tiny Tapeout board's ui_in
    "#6b4aa0": "#c3a6f2",  # purple: the Acorn's J5; the Tiny Tapeout board's uio
    "#1d6fb8": "#6fb3f2",  # H5, blue
    "#d97706": "#ffb547",  # TDI, amber
    "#2e7d32": "#74c776",  # TDO, green
    "#546e7a": "#a3b8c2",  # TCK, blue grey
    "#d81b60": "#ff79a8",  # TMS, pink
    "#15181d": "#e3e6ea",  # GND, ink
    "#9aa0a8": "#a0a6ae",  # a wire that is cut back and is not VCC, grey (acorn/sheetlib.GREY)
}
THEMES = ("light", "dark")
PHOTO_START, PHOTO_END = "<!--photo-->", "<!--/photo-->"
# Words for the dark sheet only (Sheet.dark_only()): the light sheet leaves their place empty.
DARK_START, DARK_END = "<!--dark-only-->", "<!--/dark-only-->"
TOKEN = re.compile(r"@@([a-z0-9-]+)@@")
# A colour attribute whose value is not a token and not "none": a colour the palette does not know.
STRAY = re.compile(r'\b(?:fill|stroke|stop-color|color|flood-color)="(?!none"|@@[a-z0-9-]+@@")([^"]*)"')
PHOTO = re.compile(re.escape(PHOTO_START) + "(.*?)" + re.escape(PHOTO_END), re.S)
DARK_ONLY = re.compile(re.escape(DARK_START) + ".*?" + re.escape(DARK_END), re.S)
# A colour written any other way: a hex value anywhere (an attribute, CSS, a comment), once the references to
# elements by id (href="#r12", url(#g)) are taken out; and any style attribute or <style> element, since
# colours go only through fill and stroke attributes and their tokens.
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
REFERENCE = re.compile(r'\b(?:xlink:)?href="#[^"]*"|url\(#[^)]*\)')
STYLE = re.compile(r'\bstyle="[^"]*"|<style\b')


def role(name):
    """The token for a role of ROLES."""
    if name not in ROLES:
        raise KeyError(f"no colour role {name!r} in palette.ROLES")
    return f"@@{name}@@"


def wire(colour):
    """The token for a wire colour of wiring.toml."""
    if colour.lower() not in WIRES:
        raise KeyError(f"wire colour {colour} has no dark counterpart in palette.WIRES")
    return f"@@wire-{colour.lower()[1:]}@@"


WASH = re.compile(r"wash(\d{1,3})-([a-z0-9-]+)")


def wash(token, percent):
    """The token for what `token` drawn at `percent` % opacity over the paper looks like: what text drawn on such a
    translucent fill stands on, for the contrast check (Sheet.rect(opacity=...) records it)."""
    m = TOKEN.fullmatch(token)
    if m is None or not 0 < percent <= 100 or percent != int(percent):
        raise ValueError(f"no wash of {token!r} at {percent} %")
    return f"@@wash{int(percent)}-{m.group(1)}@@"


def value(token, theme):
    """The colour a token stands for on a sheet of `theme`."""
    m = TOKEN.fullmatch(token)
    if m is None:
        raise ValueError(f"{token!r} is not a colour token")
    name = m.group(1)
    washed = WASH.fullmatch(name)
    if washed:
        a = int(washed.group(1)) / 100
        top, paper = rgb(value(f"@@{washed.group(2)}@@", theme)), rgb(value("@@paper@@", theme))
        return "#" + "".join(f"{round(a * t + (1 - a) * p):02x}" for t, p in zip(top, paper, strict=True))
    if name.startswith("wire-"):
        light = "#" + name[5:]
        if light not in WIRES:
            raise KeyError(f"wire colour {light} has no dark counterpart in palette.WIRES")
        return light if theme == "light" else WIRES[light]
    if name not in ROLES:
        raise KeyError(f"no colour role {name!r} in palette.ROLES")
    return ROLES[name][THEMES.index(theme)]


def rgb(colour):
    """(r, g, b) of "#rgb" or "#rrggbb"."""
    h = colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"not a colour: {colour!r}")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def luminance(colour):
    """WCAG 2 relative luminance."""

    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG 2 contrast ratio of two colours, 1 to 21."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def resolve(svg, theme):
    """The SVG of a drawing for `theme`: every token replaced by its colour, the photos left as they are.

    Fails if any colour outside a photo is not a token, so a colour added without a role cannot reach a sheet.
    """
    if theme not in THEMES:
        raise ValueError(f"no theme {theme!r}")
    if theme == "light":  # what is for the dark sheet only goes; the dark sheet keeps it, marks and all
        svg = DARK_ONLY.sub("", svg)
    out, at = [], 0
    for m in PHOTO.finditer(svg):
        out.append(_tokens(svg[at : m.start()], theme))
        out.append(m.group(1))
        at = m.end()
    out.append(_tokens(svg[at:], theme))
    return "".join(out)


def _tokens(text, theme):
    stray = STRAY.findall(text) + HEX.findall(REFERENCE.sub("", text)) + STYLE.findall(text)
    if stray:
        raise SystemExit(f"palette: colours outside palette.py in a drawing: {sorted(set(stray))}")
    if PHOTO_START in text or PHOTO_END in text:
        raise SystemExit("palette: a photo's start and end marks do not pair")
    return TOKEN.sub(lambda m: value(m.group(0), theme), text)


def dark_name(name):
    """acorn-x.svg -> acorn-x-dark.svg, acorn-x.png -> acorn-x-dark.png."""
    stem, _, ext = name.rpartition(".")
    return f"{stem}-dark.{ext}"


def themed(files):
    """Every drawing twice: its light SVG under its own name, its dark SVG beside it as <name>-dark.svg.

    `files` is a generator's {file name: text}, the drawings with their colours as tokens; the two SVGs of each
    differ only in the colours and in the words for the dark sheet only. Any other file is passed through."""
    out = {}
    for name, text in files.items():
        if name.endswith(".svg"):
            out[name] = resolve(text, "light")
            out[dark_name(name)] = resolve(text, "dark")
        else:
            out[name] = text
    return out
