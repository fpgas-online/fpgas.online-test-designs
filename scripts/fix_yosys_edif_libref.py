#!/usr/bin/env python3
"""Post-process a Yosys-generated EDIF so Vivado can route hierarchical designs.

Applies two independent fixes to the EDIF that the Yosys 0.64 + synth_xilinx
flow produces for the LiteX SoCs in this repo:

**Bug 1 — dual library declarations (libraryRef LIB vs DESIGN).** Yosys
writes non-top user modules (VexRiscv, InstructionCache, DataCache, ...)
TWICE: once as a port-only black-box stub in the ``external LIB`` library,
and once as the fully-elaborated netlist in ``library DESIGN``. Every
instance references ``(libraryRef LIB)`` — the stub — so Vivado's
``opt_design`` fails with::

    ERROR: [DRC INBB-3] Black Box Instances: Cell 'VexRiscv' of type
    'VexRiscv' has undefined contents and is considered a black box.

Fix: rewrite ``(cellRef X (libraryRef LIB))`` → ``(cellRef X (libraryRef
DESIGN))`` for any cell name X that is defined in both libraries. Xilinx
primitives (BUFG, DSP48E1, LUT*, RAMB*, IBUF, ...) appear only in LIB and
are left alone.

**Bug 2 — redundant IBUFs on unused differential-pair inputs.** Yosys's
default ``iopadmap`` pass wraps every top-level primary port in a
single-ended ``IBUF``/``OBUF``. For differential inputs (e.g. Acorn's
``clk200_p``/``clk200_n`` at DIFF_SSTL15), LiteX's Verilog explicitly
instantiates an ``IBUFDS`` — and when the design doesn't actually use that
clock (pmod-loopback on Acorn is purely combinational), Yosys's DCE
deletes the IBUFDS but iopadmap still wraps the top-level ports in IBUFs
because the ``(* dont_touch *)`` attribute preserves them. Vivado's DRC
then fails with::

    ERROR: [DRC IOSTDTYPE-1] IOStandard Type: I/O port clk200_p is
    Single-Ended but has an IOStandard of DIFF_SSTL15 which can only
    support Differential

Fix: remove IBUF/OBUF instances whose output (IBUF) or input (OBUF) is on
a net that Yosys marked ``(property unused_bits ...)``. After removal the
top-level port is connected to only its port declaration — an unused
port — which Vivado accepts as a no-op for that pin (a warning, but
not an error).

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

# Parse cell definitions. Yosys indents cells with four spaces in both
# ``external LIB`` and ``library DESIGN``, and uses two forms:
#
#   (1) Plain:     ``    (cell VexRiscv``
#   (2) Rename:    ``    (cell (rename id00001 "$paramod$HASH\pcie_7x")``
#
# Form (2) is EDIF 2 0 0's escape for Verilog identifiers containing
# characters EDIF can't put directly in an identifier — pcie-enumeration
# triggers it for every parameterized module (pcie_7x, pipe_wrapper,
# pcie_block, two_beats, …). The *internal* id in the rename pair is what
# ``(cellRef ...)`` references use throughout the file, so both forms must
# be captured here and the substitution in ``fix_edif`` uses whichever
# token the alternation matched. Group 1 captures the rename internal id;
# group 2 captures a plain name.
_CELL_DEF_RE = re.compile(
    r'^    \(cell (?:\(rename (\S+) "[^"]+"\)|(\S+)\s*$)',
    re.MULTILINE,
)

# Library section boundaries. Yosys writes exactly one ``external LIB`` and
# exactly one ``library DESIGN``; this regex captures the body of each up
# to the start of the next top-level section.
_LIB_BLOCK_RE = re.compile(r"\(external LIB\b.*?(?=\n  \(library\b)", re.DOTALL)
_DESIGN_BLOCK_RE = re.compile(r"\(library DESIGN\b.*?(?=\n  \(design\b)", re.DOTALL)


def _cells_in(block_match: re.Match | None) -> set[str]:
    """Return the set of cell identifiers defined inside a library-block match.

    For plain ``(cell NAME`` the identifier is NAME; for rename-syntax
    ``(cell (rename ID "EXTERNAL"))`` the identifier is the internal ID,
    because that's what ``(cellRef ID ...)`` references use throughout the
    EDIF — matching by ID is what lets the substitution wire up correctly.
    """
    if not block_match:
        return set()
    return {
        m.group(1) or m.group(2)
        for m in _CELL_DEF_RE.finditer(block_match.group(0))
    }


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


# ---------------------------------------------------------------------------
# Bug 2 — unused IBUF/OBUF instances on dont-touched top ports
# ---------------------------------------------------------------------------

# Match a complete `(instance (rename ID ...) ... (cellRef TYPE (libraryRef
# LIB)) ... )` block — three lines, consistent 10-space outer indent in the
# Yosys EDIF emitter output. The `(?:...)?` around the trailing property
# line tolerates iopads emitted without the `keep` property.
_IOPAD_INSTANCE_RE = re.compile(
    r"          \(instance \(rename (\S+) \"\$iopadmap\$[^\"]+\"\)\n"
    r"            \(viewRef VIEW_NETLIST \(cellRef (IBUF|OBUF) \(libraryRef LIB\)\)\)"
    r"(?:\n            \(property keep \(integer 1\)\))?\)\n"
)

# Match a complete `(net ... (joined (portRef X (instanceRef ID))) (property
# unused_bits ...))` block — six lines, the telltale shape Yosys writes when
# iopadmap wraps a top-level port whose synthesized usage was removed by
# DCE.
_UNUSED_IOPAD_NET_RE = re.compile(
    r"          \(net \(rename \S+ \"\$iopadmap\$[^\"]+\"\) \(joined\n"
    r"              \(portRef [IO] \(instanceRef (\S+)\)\)\n"
    r"            \)\n"
    r"            \(property unused_bits \(string \"0\"\)\)\n"
    r"          \)\n"
)

# Strip a single `(portRef X (instanceRef ID))` line (with trailing newline)
# from inside a (joined ...) block — used to clean up the port-side net
# after the IBUF/OBUF it referenced is deleted.
def _strip_port_ref_line(text: str, inst_id: str) -> tuple[str, int]:
    pattern = re.compile(
        rf"              \(portRef [IO] \(instanceRef {re.escape(inst_id)}\)\)\n"
    )
    return pattern.subn("", text)


def find_unused_iopads(edif_text: str) -> set[str]:
    """Return instance IDs of IBUF/OBUF cells whose output sits on an
    ``(property unused_bits ...)`` net.

    These are the redundant iopads that Yosys adds around top-level ports
    whose driven logic was removed by DCE but whose port declaration
    was preserved (typically because LiteX marked the port with
    ``(* dont_touch *)``).
    """
    # First: gather the set of IDs that are IBUF/OBUF instances. The same
    # RegEx that finds the instance block also names the cell type — we
    # could filter at the same time, but separating keeps the two passes
    # independent and easy to reason about.
    iopad_ids = {m.group(1) for m in _IOPAD_INSTANCE_RE.finditer(edif_text)}

    # Second: find `unused_bits` nets and record which iopad IDs they
    # reference. The intersection is exactly what we want.
    unused_ids = {m.group(1) for m in _UNUSED_IOPAD_NET_RE.finditer(edif_text)}

    return iopad_ids & unused_ids


def remove_unused_iopads(edif_text: str) -> tuple[str, int]:
    """Delete redundant iopad instances and their dangling nets.

    For every IBUF/OBUF identified by :func:`find_unused_iopads`:

    - Delete the `(instance (rename ID ...) ... IBUF|OBUF ...)` block.
    - Delete the `(net ... (portRef O (instanceRef ID))) ... unused_bits)`
      net that Yosys emitted as a placeholder for the dangling output.
    - Remove the `(portRef I (instanceRef ID))` reference from the
      port-side net that joined the top-level port to the now-deleted
      iopad's input. The port itself stays declared in the cell's
      interface — Vivado tolerates the resulting "declared but unused"
      port, treating the associated XDC constraints as a no-op.

    Returns ``(fixed_text, number_of_iopads_removed)``.
    """
    to_remove = find_unused_iopads(edif_text)
    if not to_remove:
        return edif_text, 0

    text = edif_text
    for inst_id in to_remove:
        # Narrowly scoped regexes — each is keyed on the specific ID so
        # we can't accidentally delete a sibling iopad that happens to
        # share the pattern skeleton.
        inst_pat = re.compile(
            r"          \(instance \(rename " + re.escape(inst_id) + r" "
            r"\"\$iopadmap\$[^\"]+\"\)\n"
            r"            \(viewRef VIEW_NETLIST "
            r"\(cellRef (?:IBUF|OBUF) \(libraryRef LIB\)\)\)"
            r"(?:\n            \(property keep \(integer 1\)\))?\)\n"
        )
        net_pat = re.compile(
            r"          \(net \(rename \S+ \"\$iopadmap\$[^\"]+\"\) "
            r"\(joined\n"
            r"              \(portRef [IO] \(instanceRef "
            + re.escape(inst_id) + r"\)\)\n"
            r"            \)\n"
            r"            \(property unused_bits \(string \"0\"\)\)\n"
            r"          \)\n"
        )
        text, _ = inst_pat.subn("", text, count=1)
        text, _ = net_pat.subn("", text, count=1)
        text, _ = _strip_port_ref_line(text, inst_id)
    return text, len(to_remove)


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

    # Read once, reuse for summary so the in-place case (dst == src)
    # doesn't stale-read the already-fixed content after writing.
    original = src.read_text()

    # Apply bug-1 fix first (libraryRef rewrite). Bug-2's unused-iopad
    # detection doesn't depend on it, but doing libref first keeps the
    # output deterministic and the summary consistent.
    fixed, n_libref = fix_edif(original)
    fixed, n_iopads = remove_unused_iopads(fixed)

    dst.write_text(fixed)

    # Summary keyed off the ORIGINAL text so messages describe what was
    # present in the input file, not what's left after the rewrites.
    duplicated = find_duplicated_cells(original)
    unused = find_unused_iopads(original)
    if n_libref == 0 and n_iopads == 0:
        print(f"  {src}: no Yosys-EDIF bugs found; nothing to fix.")
        return 0
    if n_libref > 0:
        print(
            f"  {src}: rewrote {n_libref} instance reference(s) for "
            f"{len(duplicated)} duplicated cell(s): "
            f"{', '.join(sorted(duplicated))}"
        )
    if n_iopads > 0:
        print(
            f"  {src}: removed {n_iopads} unused iopad(s) "
            f"(instance IDs: {', '.join(sorted(unused))})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
