"""SVG canvas for the Acorn wiring sheets: measures its own text and checks the layout.

check() FAILS the build if any text leaves its box or the canvas, overlaps other text, sits on a wire
or on a keep-out shape, or if one rectangle that must contain another does not.

The SVG loads nothing, not even a data: URI. raw.githubusercontent.com serves SVGs with
`Content-Security-Policy: default-src 'none'`, which blocks embedded images and fonts, so text is
drawn as glyph outlines and photos as runs of coloured strokes. A sheet opened from its raw URL looks
exactly like the PNG.
"""

import itertools
import pathlib

import wiring
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image

HERE = pathlib.Path(__file__).parent
OUT = HERE / "generated"
W, H = 1600, 900

# The fonts are in the repository, not taken from the system, so every machine draws the same outlines.
FONT_FILES = {
    "regular": HERE / "fonts" / "LiberationSans-Regular.ttf",
    "bold": HERE / "fonts" / "LiberationSans-Bold.ttf",
    "mono": HERE / "fonts" / "LiberationMono-Bold.ttf",
}

INK, MUTED, FAINT, PAPER = "#15181d", "#5b6470", "#c9ced6", "#fbfaf7"
RED, GOLD, BODY = "#c62828", "#e2b33c", "#1d1f23"

# name: (colour, who drives it, what it is), from wiring.toml
SIGNALS = {k: (v["colour"], v.get("drive"), v["what"]) for k, v in wiring.SIGNALS.items() if k != "VCC"}
P1_PINS = wiring.CONNECTORS["P1"]["pins"]  # pin 1 .. pin 6, physical order
P2_PINS = wiring.CONNECTORS["P2"]["pins"]


def label_of(sig):
    return wiring.SIGNALS[sig]["label"]


# ----------------------------------------------------------------------------------------------
# SVG canvas that knows how wide its text is
# ----------------------------------------------------------------------------------------------
class Sheet:
    def __init__(self):
        self.parts = []
        self.texts = []  # (bbox, string, may_touch_wire)
        self.wire_segments = []  # (x0, y0, x1, y1)
        self.contain = []  # (inner, outer, what)
        self.keepouts = []  # (bbox, what): shapes no text may touch
        self.boxes = []  # (bbox, label): filled labels, which may not overlap each other
        self.glyphs = {}  # (face, glyph name): id of its outline in <defs>

    def width(self, s, size, face="regular"):
        """Advance width of `s`: the same numbers text() lays the glyphs out with."""
        f = FONTS[face]
        return sum(f.advance(ch) for ch in s) * size / f.upm

    def add(self, s):
        self.parts.append(s)

    def rect(self, x, y, w, h, fill="none", stroke="none", sw=1, rx=0, extra=""):
        self.add(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}" {extra}/>'
        )

    def text(self, x, y, s, size=13, face="regular", fill=INK, anchor="start", box=None, on_wire=False):
        """Draw text with its baseline at y, as glyph outlines. `box` = (x0, y0, x1, y1) the text must stay inside."""
        f = FONTS[face]
        w = self.width(s, size, face)
        x0 = {"start": x, "middle": x - w / 2, "end": x - w}[anchor]
        bbox = (x0, y - size * 0.76, x0 + w, y + size * 0.24)
        self.texts.append((bbox, s, on_wire))
        if box is not None:
            self.contain.append((bbox, box, f"text {s!r}"))
        uses, pen_x = [], 0
        for ch in s:
            name = f.glyph_name(ch)
            if f.has_outline(name):
                gid = self.glyphs.setdefault((face, name), f"{face[0]}{len(self.glyphs)}")
                uses.append(f'<use href="#{gid}" x="{pen_x}"/>' if pen_x else f'<use href="#{gid}"/>')
            pen_x += f.advance(ch)
        k = size / f.upm
        esc = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        # aria-label keeps the words in the file for search and screen readers; nothing is drawn from it
        self.add(
            f'<g transform="translate({x0:.1f} {y:.1f}) scale({k:.5f} {-k:.5f})" fill="{fill}" aria-label="{esc}">'
            + "".join(uses)
            + "</g>"
        )
        return w

    def tag(self, x, y, s, fill, size=12, h=20, anchor="start", pad=7, on_wire=False, fg="#fff", stroke="none"):
        """A filled label whose box is sized FROM the text. (x, y) = left/right/centre edge, vertical centre."""
        w = self.width(s, size, "bold") + 2 * pad
        x0 = {"start": x, "middle": x - w / 2, "end": x - w}[anchor]
        self.rect(x0, y - h / 2, w, h, fill=fill, rx=4, stroke=stroke)
        self.boxes.append(((x0, y - h / 2, x0 + w, y + h / 2), s))
        self.text(
            x0 + w / 2,
            y + size * 0.35,
            s,
            size,
            "bold",
            fg,
            "middle",
            box=(x0, y - h / 2, x0 + w, y + h / 2),
            on_wire=on_wire,
        )
        return x0, x0 + w

    def photo(self, name, x, y, w, density=1.5, colours=96, crop=None):
        """A photo as vector art: `density` samples per sheet pixel, `colours` colours, one stroked path per colour.

        Each run of same-coloured samples along a row is one horizontal stroke. Pixels that are paper
        (the prep script's background) are left out, so the sheet shows through. `crop` = (x0, y0, x1, y1)
        in photo pixels; the returned scale then maps cropped-photo pixels to the sheet.
        """
        im = Image.open(HERE / "photos" / name).convert("RGB")
        if crop is not None:
            im = im.crop(crop)
        h = w * im.height / im.width
        small = im.resize((round(w * density), round(h * density)), Image.LANCZOS)
        sw, shh = small.size
        paper = tuple(int(PAPER[i : i + 2], 16) for i in (1, 3, 5))
        src = small.load()
        is_paper = [
            [max(abs(a - b) for a, b in zip(src[i, j], paper, strict=True)) <= 6 for i in range(sw)] for j in range(shh)
        ]
        q = small.quantize(colors=colours, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        pal = q.getpalette()[: 3 * colours]
        px = q.load()
        paths = {}  # palette index -> [pieces, current x, current y]
        for j in range(shh):
            i = 0
            while i < sw:
                c, i0 = px[i, j], i
                while i < sw and px[i, j] == c and is_paper[j][i] == is_paper[j][i0]:
                    i += 1
                if is_paper[j][i0]:
                    continue
                d = paths.setdefault(c, [[], None, None])
                if d[1] is None:
                    d[0].append(f"M{i0} {j + 0.5}h{i - i0}")
                else:
                    d[0].append(f"m{i0 - d[1]} {j + 0.5 - d[2]:g}h{i - i0}")
                d[1], d[2] = i, j + 0.5
        body = "".join(
            f'<path stroke="#{pal[3 * c]:02x}{pal[3 * c + 1]:02x}{pal[3 * c + 2]:02x}" d="{"".join(d[0])}"/>'
            for c, d in sorted(paths.items())
        )
        # square caps and a 1.1 stroke overlap each neighbour slightly, so no paper seams show between runs
        self.add(
            f'<g transform="translate({x} {y}) scale({1 / density:.6f})" fill="none" stroke-width="1.1" '
            f'stroke-linecap="square">{body}</g>'
        )
        return (x, y, w, h), w / im.width

    # ---- checks ------------------------------------------------------------------------------
    def check(self, name):
        errors = []
        for inner, outer, what in self.contain:
            if (
                inner[0] < outer[0] - 0.5
                or inner[1] < outer[1] - 0.5
                or inner[2] > outer[2] + 0.5
                or inner[3] > outer[3] + 0.5
            ):
                errors.append(
                    f"{what} leaves its box: {tuple(round(v) for v in inner)} vs {tuple(round(v) for v in outer)}"
                )
        for bbox, s, _ in self.texts:
            if bbox[0] < 8 or bbox[1] < 8 or bbox[2] > W - 8 or bbox[3] > H - 8:
                errors.append(f"text {s!r} leaves the canvas")
        for (a, sa, _), (b, sb, _) in itertools.combinations(self.texts, 2):
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                errors.append(f"text {sa!r} overlaps text {sb!r}")
        for bbox, s, on_wire in self.texts:
            if on_wire:
                continue
            for x0, y0, x1, y1 in self.wire_segments:
                lo_x, hi_x, lo_y, hi_y = min(x0, x1) - 4, max(x0, x1) + 4, min(y0, y1) - 4, max(y0, y1) + 4
                if bbox[0] < hi_x and lo_x < bbox[2] and bbox[1] < hi_y and lo_y < bbox[3]:
                    errors.append(
                        f"text {s!r} at {tuple(round(v) for v in bbox)} sits on the wire run {(x0, y0, x1, y1)}"
                    )
                    break
        for (a, sa), (b, sb) in itertools.combinations(self.boxes, 2):
            if a[0] < b[2] - 0.5 and b[0] < a[2] - 0.5 and a[1] < b[3] - 0.5 and b[1] < a[3] - 0.5:
                errors.append(
                    f"label {sa!r} at {tuple(round(v) for v in a)} overlaps label {sb!r} at "
                    f"{tuple(round(v) for v in b)}"
                )
        for bbox, s, _ in self.texts:
            for k, what in self.keepouts:
                if bbox[0] < k[2] and k[0] < bbox[2] and bbox[1] < k[3] and k[1] < bbox[3]:
                    errors.append(f"text {s!r} touches {what}")
        if errors:
            raise SystemExit(f"{name}: {len(errors)} layout errors\n  " + "\n  ".join(errors))

    def glyph_defs(self):
        out = []
        for (face, name), gid in self.glyphs.items():
            out.append(f'<path id="{gid}" d="{FONTS[face].outline(name)}"/>')
        return "<defs>" + "".join(out) + "</defs>"

    def svg(self):
        body = "".join(self.parts)  # glyph ids are allocated while the parts are drawn
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
            + self.glyph_defs()
            + f'<rect width="{W}" height="{H}" fill="{PAPER}"/>'
            + body
            + "</svg>"
        )


class Font:
    """One TrueType face: advances for measuring, outlines for drawing. No kerning, so measure == draw."""

    def __init__(self, path):
        self.tt = TTFont(path)
        self.upm = self.tt["head"].unitsPerEm
        self.cmap = self.tt.getBestCmap()
        self.hmtx = self.tt["hmtx"]
        self.gs = self.tt.getGlyphSet()

    def glyph_name(self, ch):
        if ord(ch) not in self.cmap:
            raise SystemExit(f"{self.tt.reader.file.name}: no glyph for {ch!r}")
        return self.cmap[ord(ch)]

    def advance(self, ch):
        return self.hmtx[self.glyph_name(ch)][0]

    def has_outline(self, name):
        return self.tt["glyf"][name].numberOfContours != 0

    def outline(self, name):
        pen = SVGPathPen(self.gs)
        self.gs[name].draw(pen)
        return pen.getCommands()


FONTS = {face: Font(path) for face, path in FONT_FILES.items()}
