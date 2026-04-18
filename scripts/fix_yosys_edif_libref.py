#!/usr/bin/env python3
"""Post-process a Yosys-generated EDIF so Vivado can route hierarchical designs.

**The bug**: When Yosys 0.64 writes EDIF for a design that keeps user-module
hierarchy (like the LiteX + VexRiscv flow used here), non-top modules end up
defined TWICE — once as a port-only black-box stub in the ``external LIB``
library, and once as the fully-elaborated netlist in ``library DESIGN``.
Every instance of those modules in the parent netlist references
``(libraryRef LIB)``, which points at the stub. When Vivado later reads the
EDIF and runs ``opt_design``, it sees the stub and fails with::

    ERROR: [DRC INBB-3] Black Box Instances: Cell 'VexRiscv' of type
    'VexRiscv' has undefined contents and is considered a black box.

The full netlist is right there in the same EDIF file — just one token
over in ``library DESIGN``.

**The fix**: For any cell name that appears as a definition in BOTH ``LIB``
and ``DESIGN``, rewrite every ``(cellRef X (libraryRef LIB))`` to
``(cellRef X (libraryRef DESIGN))`` so Vivado resolves to the real netlist.
Cells that appear only in ``LIB`` (Xilinx primitives: BUFG, DSP48E1, BRAM,
…) are left alone.

Usage::

    fix_yosys_edif_libref.py <in.edif> <out.edif>   # write fixed copy
    fix_yosys_edif_libref.py <in.edif>              # rewrite in place

Designed to be called from a build script between the Yosys and Vivado
steps — see ``designs/_shared/build_helpers.py`` for the LiteX-side hook
that wires it in automatically for the yosys-vivado flow.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Parse cell definitions:  "    (cell NAME"  (NAME is the capture group).
# Yosys indents cells with four spaces in both ``external LIB`` and
# ``library DESIGN``.
#
# NOTE: EDIF 2 0 0 allows ``(cell (rename INTERNAL "external name"))`` for
# Verilog identifiers containing special characters. Yosys only emits these
# when a user Verilog module has a name like ``foo\bar`` — the LiteX +
# VexRiscv + LiteDRAM hierarchy used in this repo uses plain-ASCII
# identifiers, so the simple ``(\S+)`` capture is sufficient. If a future
# design introduces a module whose name requires a rename pair, this regex
# will miss it and the fixer will silently no-op on that cell. Add a
# ``(?:\(rename \S+ "[^"]+"\)|\S+)`` alternation at that point.
_CELL_DEF_RE = re.compile(r"^    \(cell (\S+)$", re.MULTILINE)

# Library section boundaries. Yosys writes exactly one ``external LIB`` and
# exactly one ``library DESIGN``; this regex captures the body of each up
# to the start of the next top-level section.
_LIB_BLOCK_RE = re.compile(r"\(external LIB\b.*?(?=\n  \(library\b)", re.DOTALL)
_DESIGN_BLOCK_RE = re.compile(r"\(library DESIGN\b.*?(?=\n  \(design\b)", re.DOTALL)


def _cells_in(block_match: re.Match | None) -> set[str]:
    """Return the set of cell names defined inside a library-block match."""
    if not block_match:
        return set()
    return set(_CELL_DEF_RE.findall(block_match.group(0)))


def find_duplicated_cells(edif_text: str) -> set[str]:
    """Return cell names that appear in BOTH ``LIB`` and ``DESIGN``.

    These are the non-top user modules that Yosys double-declared. They
    are exactly the cells whose instance references need rewriting.

    Raises ``ValueError`` if either library block is missing — silently
    returning an empty set would let a malformed EDIF (future Yosys
    template change, truncated file) pass through unfixed, and Vivado
    would then fail at ``opt_design`` with no hint that the post-processor
    didn't run.
    """
    lib_match = _LIB_BLOCK_RE.search(edif_text)
    design_match = _DESIGN_BLOCK_RE.search(edif_text)
    if not lib_match:
        raise ValueError(
            "EDIF is missing an `(external LIB ...)` block followed by a "
            "`(library ...)` section. Is this a Yosys-generated EDIF?"
        )
    if not design_match:
        raise ValueError(
            "EDIF is missing a `(library DESIGN ...)` block followed by a "
            "`(design ...)` section. Is this a Yosys-generated EDIF?"
        )
    return _cells_in(lib_match) & _cells_in(design_match)


def fix_edif(edif_text: str) -> tuple[str, int]:
    """Rewrite ``LIB``-qualified instance references for duplicated cells.

    Returns ``(fixed_text, number_of_substitutions)``. The count lets
    callers sanity-check that the rewrite actually matched something.
    """
    duplicated = find_duplicated_cells(edif_text)
    if not duplicated:
        return edif_text, 0

    total = 0
    text = edif_text
    for name in duplicated:
        # ``\b`` after the cell name ensures ``VexRiscv`` doesn't match
        # a ``VexRiscvFoo`` reference. The literal spaces and parentheses
        # pin the match to instance-reference syntax only — we never
        # touch the cell-definition lines themselves (which don't have
        # this exact shape).
        pattern = re.compile(
            rf"\(cellRef {re.escape(name)}\b \(libraryRef LIB\)\)"
        )
        text, n = pattern.subn(
            f"(cellRef {name} (libraryRef DESIGN))",
            text,
        )
        total += n
    return text, total


def run_cli(argv: list[str]) -> int:
    if not argv or len(argv) > 2:
        print(
            "usage: fix_yosys_edif_libref.py <input.edif> [<output.edif>]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    src = Path(argv[0])
    if not src.is_file():
        print(f"ERROR: input EDIF not found: {src}", file=sys.stderr)
        raise SystemExit(1)

    dst = Path(argv[1]) if len(argv) == 2 else src

    # Read once, reuse for both the fix and the log summary — avoids a
    # stale re-read in the in-place case where `dst == src` and the second
    # read would see the already-fixed content.
    original = src.read_text()
    fixed, n = fix_edif(original)
    dst.write_text(fixed)

    duplicated = find_duplicated_cells(original)
    if n == 0:
        print(f"  {src}: no duplicated user-module cells found; nothing to fix.")
    else:
        print(
            f"  {src}: rewrote {n} instance reference(s) for "
            f"{len(duplicated)} duplicated cell(s): {', '.join(sorted(duplicated))}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
