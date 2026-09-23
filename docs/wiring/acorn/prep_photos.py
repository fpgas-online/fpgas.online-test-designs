"""Cut the reference photos down to the board pictures the sheets embed.

Backgrounds are removed by connectivity, not by painting boxes: everything that is not part of the
largest non-white object (the board) becomes paper. That removes dimension lines and captions from the
vendor drawings without touching a single board pixel.
"""

import pathlib
from collections import deque

from PIL import Image, ImageFilter

REF = pathlib.Path("ref")
OUT = pathlib.Path("photos")
OUT.mkdir(exist_ok=True)
PAPER = (251, 250, 247)


def keep_largest_object(im, white=236, line_px=2):
    """Return `im` with every pixel outside the board set to PAPER.

    The board is the largest connected non-white region AFTER an erosion of `line_px`, so dimension
    lines and leader arrows that touch the board (1-2 px wide) do not count as part of it.
    """
    im = im.convert("RGB")
    w, h = im.size
    solid_im = im.convert("L").point(lambda v: 255 if v < white else 0)
    # min over RGB would be stricter than luminance; luminance is enough for white paper backgrounds
    eroded = solid_im.filter(ImageFilter.MinFilter(2 * line_px + 1))
    e = eroded.load()
    label = [[0] * w for _ in range(h)]
    sizes, n = {}, 0
    for y0 in range(h):
        for x0 in range(w):
            if not e[x0, y0] or label[y0][x0]:
                continue
            n += 1
            label[y0][x0] = n
            queue, size = deque([(x0, y0)]), 0
            while queue:
                x, y = queue.popleft()
                size += 1
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and e[nx, ny] and not label[ny][nx]:
                        label[ny][nx] = n
                        queue.append((nx, ny))
            sizes[n] = size
    board = max(sizes, key=sizes.get)
    core = Image.new("L", (w, h), 0)
    c = core.load()
    for y in range(h):
        for x in range(w):
            if label[y][x] == board:
                c[x, y] = 255
    grown = core.filter(ImageFilter.MaxFilter(2 * line_px + 3)).load()  # back out to the true edge, plus one pixel
    # Flood in from the border through everything that is not board: holes inside the board stay as they are.
    outside = [[False] * w for _ in range(h)]
    queue = deque([(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)])
    px = im.load()
    while queue:
        x, y = queue.popleft()
        if not (0 <= x < w and 0 <= y < h) or outside[y][x] or grown[x, y]:
            continue
        outside[y][x] = True
        px[x, y] = PAPER
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return im


def flatten(path):
    im = Image.open(path).convert("RGBA")
    return Image.alpha_composite(Image.new("RGBA", im.size, "white"), im).convert("RGB")


# Acorn / LiteFury underside (RHS Research "contents" photo): fan end left, M.2 edge right,
# connectors on the bottom edge.
acorn = keep_largest_object(flatten(REF / "rhs-contents.PNG").crop((200, 740, 1990, 1262)))
acorn.save(OUT / "acorn-flat.jpg", quality=90)
end = acorn.crop((0, 0, 1100, 522))  # only the connector end: the connectors are a few mm long and need the pixels
end.rotate(-90, expand=True).save(
    OUT / "acorn-cw.jpg", quality=90
)  # connectors on the LEFT edge, P2 on top, pin 1 at the bottom
end.rotate(90, expand=True).save(
    OUT / "acorn-ccw.jpg", quality=90
)  # connectors on the RIGHT edge, P1 on top, pin 1 at the top

# Waveshare PoE M.2 HAT+ top view (their dimension drawing): header on the bottom edge, pin 1 at the right.
hat = keep_largest_object(flatten(REF / "ws-PoE-M.2-HAT-plus-details-size.jpg").crop((170, 70, 795, 580)))
hat.rotate(90, expand=True).save(
    OUT / "hat-ccw.jpg", quality=92
)  # header on the RIGHT edge, pin 1 on top (pinout-chart order)
hat.rotate(-90, expand=True).save(OUT / "hat-cw.jpg", quality=92)  # header on the LEFT edge, pin 1 at the bottom

# Compute Blade top view and the close-up of its Expansion Port (vendor docs).
blade = keep_largest_object(flatten(REF / "blade-mk4-k-dev.webp").resize((3120, 521)))
blade.save(OUT / "blade.jpg", quality=86)
full = flatten(REF / "blade-mk4-k-dev.webp")
W, H = full.size
full.crop((int(W * 0.59) + 80, int(H * 0.55) + 10, int(W * 0.59) + 1720, int(H * 0.55) + 520)).save(
    OUT / "blade-port.jpg", quality=90
)

for p in sorted(OUT.glob("*.jpg")):
    print(p, Image.open(p).size, p.stat().st_size)
