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
    Try progressively shorter forms, then scan part.yaml files for die aliases
    (e.g. xc7a35t shares a die with xc7a50t).
    """
    if part:
        for name in _part_name_variants(part):
            candidate = os.path.join(db_root, name, "tilegrid.json")
            if os.path.isfile(candidate):
                return candidate
        # Scan part.yaml files to resolve die aliases (e.g. xc7a35t → xc7a50t)
        result = _scan_part_yamls(db_root, part)
        if result:
            return result
    # Fallback: tilegrid directly under db_root
    candidate = os.path.join(db_root, "tilegrid.json")
    if os.path.isfile(candidate):
        return candidate
    return None


def _scan_part_yamls(db_root, part):
    """Find tilegrid by scanning part.yaml files for the device+package name.

    Some dies are shared between parts (e.g. xc7a35t and xc7a50t). The
    prjxray-db directory uses one name, but part.yaml lists all compatible
    device+package combinations.
    """
    part_no_speed = re.sub(r"-\d+$", "", part)
    try:
        entries = os.listdir(db_root)
    except OSError:
        return None
    for entry in sorted(entries):
        entry_dir = os.path.join(db_root, entry)
        if not os.path.isdir(entry_dir):
            continue
        part_yaml = os.path.join(entry_dir, "part.yaml")
        tilegrid = os.path.join(entry_dir, "tilegrid.json")
        if os.path.isfile(part_yaml) and os.path.isfile(tilegrid):
            with open(part_yaml) as f:
                if part_no_speed in f.read():
                    return tilegrid
    return None


def _part_name_variants(part):
    """Yield progressively shorter device name forms for directory lookup.

    ``xc7a35tfgg484-2`` → ``xc7a35tfgg484-2``, ``xc7a35tfgg484``, ``xc7a35t``, ``xc7a50t``
    """
    yield part
    # Strip speed grade suffix (-1, -2, -3)
    no_speed = re.sub(r"-\d+$", "", part)
    if no_speed != part:
        yield no_speed
    # Strip package to get die name only (xc7a200t)
    die_match = re.match(r"^(xc7[aksz]\d+t)", part)
    if die_match:
        die = die_match.group(1)
        if die != no_speed:
            yield die
        # Xilinx die equivalences: some parts share silicon
        alias = _ARTIX7_DIE_ALIASES.get(die)
        if alias:
            yield alias


# Artix-7 parts that share the same die (Xilinx uses die harvesting).
# prjxray-db may only have one directory per physical die.
_ARTIX7_DIE_ALIASES = {
    "xc7a12t": "xc7a25t",
    "xc7a25t": "xc7a12t",
    "xc7a35t": "xc7a50t",
    "xc7a50t": "xc7a35t",
    "xc7a75t": "xc7a100t",
    "xc7a100t": "xc7a75t",
}


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
