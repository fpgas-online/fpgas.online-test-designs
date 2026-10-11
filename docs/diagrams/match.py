# SPDX-License-Identifier: Apache-2.0
"""Hold the render to the photo: where an item's box lies in a photo, and what the photo shows there."""

from PIL import Image, ImageDraw, ImageStat

from .errors import DiagramError


def item_px(thing, item):
    """The item's box in the pixels of the photo of its face: (x0, y0, x1, y1), x0 < x1 and y0 < y1.

    The inverse of what measure_hat.py and measure_card.py did to get millimetres: `origin` is the photo pixel of
    the thing's (0, 0) for a photo of the top face, and of its (width, 0) for a photo of the bottom face, which
    shows the thing from beneath (x mirrored); y runs down the photo from the thing's end in both."""
    if item.face not in thing.photos:
        raise DiagramError(f"{item.id}: {thing.key} has no photo of its {item.face} face")
    photo = thing.photos[item.face]
    (sx, sy), (ox, oy) = photo["px_per_mm"], photo["origin"]
    box = item.box
    if item.face == "bottom":
        xs = [ox + (thing.size[0] - x) * sx for x in (box.x0, box.x1)]
    else:
        xs = [ox + x * sx for x in (box.x0, box.x1)]
    return (min(xs), oy + box.y0 * sy, max(xs), oy + box.y1 * sy)


def _pixels(box_px, size):
    """A box in float pixels as whole pixels inside an image of `size`: (x0, y0, x1, y1), at least one pixel wide."""
    x0, y0 = max(0, round(box_px[0])), max(0, round(box_px[1]))
    x1, y1 = min(size[0], max(x0 + 1, round(box_px[2]))), min(size[1], max(y0 + 1, round(box_px[3])))
    return x0, y0, x1, y1


def _sum(image, box):
    return ImageStat.Stat(image.crop(box)).sum[0], (box[2] - box[0]) * (box[3] - box[1])


def contrast_inside(image, box_px, ring_px, clip_px=None):
    """The mean luminance inside the box less the mean in the ring round it.

    `ring_px` is the ring's width, (across, down), in pixels; the ring is cut to `clip_px` (the thing's own outline
    in the photo) so that the paper beyond the board's edge is not counted as board. Pixels are whole: a box is
    rounded to the pixels it covers, and is never less than one."""
    image = image.convert("L")
    inner = _pixels(box_px, image.size)
    outer = (box_px[0] - ring_px[0], box_px[1] - ring_px[1], box_px[2] + ring_px[0], box_px[3] + ring_px[1])
    outer = _pixels(outer, image.size)
    if clip_px is not None:
        clip = _pixels(clip_px, image.size)
        outer = (max(outer[0], clip[0]), max(outer[1], clip[1]), min(outer[2], clip[2]), min(outer[3], clip[3]))
    inside, n_in = _sum(image, inner)
    around, n_out = _sum(image, outer)
    if n_out <= n_in:
        raise DiagramError(f"no ring round {box_px}: the box fills the part of the photo it may be compared in")
    return inside / n_in - (around - inside) / (n_out - n_in)


def _mean(image, rect, clip_px):
    """The mean luminance of `rect` (float pixels) cut to the image and `clip_px`; None if nothing is left."""
    cut = _pixels(rect, image.size)
    if clip_px is not None:
        clip = _pixels(clip_px, image.size)
        cut = (max(cut[0], clip[0]), max(cut[1], clip[1]), min(cut[2], clip[2]), min(cut[3], clip[3]))
    if cut[0] >= cut[2] or cut[1] >= cut[3]:
        return None
    total, n = _sum(image, cut)
    return total / n


def outline_sides(image, box_px, scale, band_mm, inside_mm, outside_mm, clip_px=None):
    """For each side of the box, how much brighter the band centred on that edge is than the board beside it:
    {"left": (inside, outside), ...} in photo terms, each value the edge band's mean luminance less that of the band
    `inside_mm` = (near, far) inside the side, or `outside_mm` outside it.

    A line is brighter than the board on at least one of its sides, so a value is None where its band is cut away
    entirely by `clip_px` (the board and the part of it the photo shows) or the image; if both are, DiagramError
    names the side. Both bands run the side's own length. `scale` is (across, down) in px/mm. This holds an item
    whose box is a drawn outline (a socket's silkscreen) to that outline."""
    image = image.convert("L")
    sx, sy = scale
    x0, y0, x1, y1 = box_px
    h = band_mm / 2
    (i0, i1), (o0, o1) = inside_mm, outside_mm
    sides = {
        "left": (
            (x0 - h * sx, y0, x0 + h * sx, y1),
            (x0 + i0 * sx, y0, x0 + i1 * sx, y1),
            (x0 - o1 * sx, y0, x0 - o0 * sx, y1),
        ),
        "right": (
            (x1 - h * sx, y0, x1 + h * sx, y1),
            (x1 - i1 * sx, y0, x1 - i0 * sx, y1),
            (x1 + o0 * sx, y0, x1 + o1 * sx, y1),
        ),
        "top": (
            (x0, y0 - h * sy, x1, y0 + h * sy),
            (x0, y0 + i0 * sy, x1, y0 + i1 * sy),
            (x0, y0 - o1 * sy, x1, y0 - o0 * sy),
        ),
        "bottom": (
            (x0, y1 - h * sy, x1, y1 + h * sy),
            (x0, y1 - i1 * sy, x1, y1 - i0 * sy),
            (x0, y1 + o0 * sy, x1, y1 + o1 * sy),
        ),
    }
    out = {}
    for name, (edge, inside, outside) in sides.items():
        e = _mean(image, edge, clip_px)
        if e is None:
            raise DiagramError(f"{name} side: the edge band lies outside the part of the photo it may be compared in")
        beside = tuple(None if (m := _mean(image, r, clip_px)) is None else e - m for r in (inside, outside))
        if beside == (None, None):
            raise DiagramError(f"{name} side: no board beside it, inside or outside, to compare it with")
        out[name] = beside
    return out


OUTLINES = {"board": "white", "header": "yellow", "pin": "red", "socket": "cyan", "slot": "cyan", "pad": "lime"}


def overlay(scene, thing_key, face, photos_dir):
    """The photo of `thing_key`'s `face` with every item's box on that face outlined, for a person to look at."""
    thing = scene.things[thing_key]
    if face not in thing.photos:
        raise DiagramError(f"{thing_key}: no photo of its {face} face")
    with Image.open(photos_dir / thing.photos[face]["file"]) as photo:
        image = photo.convert("RGB")
    draw = ImageDraw.Draw(image)
    for item in thing.items.values():
        if item.face == face:
            x0, y0, x1, y1 = item_px(thing, item)
            draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline=OUTLINES.get(item.kind, "magenta"))
    return image
