#!/usr/bin/env python3
"""fasm2frames wrapper — patches GTP IBUFDS_GTE2 tile names before invoking the real tool.

Installed in CI as a drop-in replacement for fasm2frames.  Intercepts the
FASM file, runs patch_fasm_gtp.py to fix bare IBUFDS_GTE2 references, then
exec's the real fasm2frames with the original arguments.
"""

import os
import subprocess
import sys

_REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fasm2frames.real")


def _find_args():
    """Extract --db-root value and the positional FASM file from argv."""
    db_root = fasm_file = None
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
        elif arg == "--part":
            skip = True  # --part takes a value, skip it
        elif arg.startswith("--part="):
            pass
        elif not arg.startswith("-"):
            fasm_file = arg
    return db_root, fasm_file


def main():
    db_root, fasm_file = _find_args()

    if fasm_file and db_root:
        tilegrid = os.path.join(db_root, "tilegrid.json")
        patch_script = os.path.join(
            os.environ.get("GITHUB_WORKSPACE", os.getcwd()),
            "designs", "_shared", "patch_fasm_gtp.py",
        )
        if (
            os.path.isfile(tilegrid)
            and os.path.isfile(fasm_file)
            and os.path.isfile(patch_script)
        ):
            print(f"[fasm2frames wrapper] patching {fasm_file}", file=sys.stderr)
            subprocess.run(
                [sys.executable, patch_script, fasm_file, tilegrid],
                check=True,
            )

    os.execv(_REAL, [_REAL, *sys.argv[1:]])


if __name__ == "__main__":
    main()
