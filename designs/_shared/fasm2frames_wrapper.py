#!/usr/bin/env python3
"""fasm2frames wrapper — patches GTP IBUFDS_GTE2 tile names before invoking the real tool.

Installed in CI as a drop-in replacement for fasm2frames.  Intercepts the
FASM file, runs patch_fasm_gtp.py to fix bare IBUFDS_GTE2 references, then
exec's the real fasm2frames with the original arguments.
"""

import os
import re
import subprocess
import sys

_REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fasm2frames.real")


def _find_args():
    """Extract --db-root, --part, and the positional FASM file from argv."""
    db_root = part = fasm_file = None
    skip = False
    for i in range(1, len(sys.argv)):
        if skip:
            skip = False
            continue
        arg = sys.argv[i]
        if arg == "--db-root" and i + 1 < len(sys.argv):
            db_root = sys.argv[i + 1]
            skip = True
        elif arg.startswith("--db-root="):
            db_root = arg.split("=", 1)[1]
        elif arg == "--part" and i + 1 < len(sys.argv):
            part = sys.argv[i + 1]
            skip = True
        elif arg.startswith("--part="):
            part = arg.split("=", 1)[1]
        elif not arg.startswith("-"):
            fasm_file = arg
    return db_root, part, fasm_file


def _find_tilegrid(db_root, part):
    """Locate tilegrid.json under db_root, trying part-specific subdirectory.

    The --part from LiteX is the full device string (e.g. ``xc7a200tsbg484-3``),
    but prjxray-db directories use the die name only (e.g. ``xc7a200t/``).
    Try progressively shorter forms: full → no speed grade → die only.
    """
    if part:
        for name in _part_name_variants(part):
            candidate = os.path.join(db_root, name, "tilegrid.json")
            if os.path.isfile(candidate):
                return candidate
    # Fallback: tilegrid directly under db_root
    candidate = os.path.join(db_root, "tilegrid.json")
    if os.path.isfile(candidate):
        return candidate
    return None


def _part_name_variants(part):
    """Yield progressively shorter device name forms for directory lookup.

    ``xc7a200tsbg484-3`` → ``xc7a200tsbg484-3``, ``xc7a200tsbg484``, ``xc7a200t``
    """
    yield part
    # Strip speed grade suffix (-1, -2, -3)
    no_speed = re.sub(r"-\d+$", "", part)
    if no_speed != part:
        yield no_speed
    # Strip package to get die name only (xc7a200t)
    die_match = re.match(r"^(xc7[aksz]\d+t)", part)
    if die_match and die_match.group(1) != no_speed:
        yield die_match.group(1)


def main():
    db_root, part, fasm_file = _find_args()

    if fasm_file and db_root:
        tilegrid = _find_tilegrid(db_root, part)
        patch_script = os.path.join(
            os.environ.get("GITHUB_WORKSPACE", os.getcwd()),
            "designs", "_shared", "patch_fasm_gtp.py",
        )
        if not tilegrid:
            print(
                f"[fasm2frames wrapper] tilegrid.json not found under {db_root} "
                f"(part={part}) — skipping FASM patch",
                file=sys.stderr,
            )
        elif not os.path.isfile(fasm_file):
            print(
                f"[fasm2frames wrapper] FASM file {fasm_file} not found — skipping patch",
                file=sys.stderr,
            )
        elif not os.path.isfile(patch_script):
            print(
                f"[fasm2frames wrapper] patch script not found at {patch_script}",
                file=sys.stderr,
            )
        else:
            print(f"[fasm2frames wrapper] patching {fasm_file} (tilegrid: {tilegrid})", file=sys.stderr)
            subprocess.run(
                [sys.executable, patch_script, fasm_file, tilegrid],
                check=True,
            )

    os.execv(_REAL, [_REAL, *sys.argv[1:]])


if __name__ == "__main__":
    main()
