"""Rewrite FASM to fix IBUFDS_GTE2 tile name references for fasm2frames.

nextpnr-xilinx emits bare ``IBUFDS_GTE2_Y0.feature`` lines in FASM output,
but fasm2frames requires a full tile name from the tilegrid (e.g.
``GTP_COMMON_X130Y23.IBUFDS_GTE2_Y0.feature``).

This works around a bug in the openXC7 toolchain where IBUFDS_GTE2 BEL names
are not mapped to their parent GTP_COMMON tiles during FASM generation.

Usage::

    python patch_fasm_gtp.py <fasm_file> <tilegrid.json>
"""

import json
import re
import sys

_IBUFDS_RE = re.compile(r"^(IBUFDS_GTE2_Y\d+)\.")


def find_gtp_common_tile(tilegrid_path):
    """Find the GTP_COMMON tile name from the prjxray tilegrid.

    For single-quad Artix-7 parts (all current targets), returns the one
    GTP_COMMON tile name.  Warns if multiple tiles are found — the
    single-tile mapping may not be correct for multi-quad parts.
    """
    with open(tilegrid_path) as f:
        tilegrid = json.load(f)

    gtp_tiles = sorted(
        (info["grid_y"], name)
        for name, info in tilegrid.items()
        if info.get("type") == "GTP_COMMON"
    )

    if not gtp_tiles:
        return None

    if len(gtp_tiles) > 1:
        print(
            f"patch_fasm_gtp: WARNING — {len(gtp_tiles)} GTP_COMMON tiles found; "
            "using first tile for all IBUFDS_GTE2 references",
            file=sys.stderr,
        )

    return gtp_tiles[0][1]


def patch_fasm(fasm_path, tilegrid_path):
    """Prepend the GTP_COMMON tile name to bare IBUFDS_GTE2 FASM lines.

    Modifies *fasm_path* in place.  Lines matching
    ``IBUFDS_GTE2_Y<n>.<feature>`` become
    ``<GTP_COMMON_tile>.IBUFDS_GTE2_Y<n>.<feature>``.

    Returns the number of lines patched.
    """
    tile = find_gtp_common_tile(tilegrid_path)
    if not tile:
        print("patch_fasm_gtp: no GTP_COMMON tile in tilegrid — skipping", file=sys.stderr)
        return 0

    print(f"patch_fasm_gtp: IBUFDS_GTE2 → {tile}", file=sys.stderr)

    with open(fasm_path) as f:
        lines = f.readlines()

    patched = 0
    for i, line in enumerate(lines):
        if _IBUFDS_RE.match(line):
            lines[i] = f"{tile}.{line}"
            patched += 1

    if patched:
        with open(fasm_path, "w") as f:
            f.writelines(lines)

    print(f"patch_fasm_gtp: patched {patched} line(s) in {fasm_path}", file=sys.stderr)
    return patched


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <fasm_file> <tilegrid.json>", file=sys.stderr)
        sys.exit(1)
    patch_fasm(sys.argv[1], sys.argv[2])
