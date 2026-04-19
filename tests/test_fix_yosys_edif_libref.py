"""Tests for scripts/fix_yosys_edif_libref.py.

The yosys-vivado flow produces EDIFs where non-top user modules are
declared as black-box stubs in the ``external LIB`` library AND as full
netlists in the ``library DESIGN`` section, while every instance of those
modules references ``(libraryRef LIB)`` — so Vivado binds to the stub and
``opt_design`` fails with `DRC INBB-3` (black-box cell).

The fixer post-processes the EDIF to rewrite those instance references
from ``LIB`` to ``DESIGN`` so Vivado resolves them against the real
netlist. Auto-detects which modules to rewrite by finding cells that
appear in BOTH libraries (the smoking-gun signature of this bug).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import fix_yosys_edif_libref as fixer  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal EDIF fixture mirroring the real bug
# ---------------------------------------------------------------------------

MINIMAL_BROKEN_EDIF = """(edif top
  (edifVersion 2 0 0)
  (edifLevel 0)
  (keywordMap (keywordLevel 0))
  (external LIB
    (edifLevel 0)
    (technology (numberDefinition))
    (cell BUFG
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port I (direction INPUT)) (port O (direction OUTPUT)))
      )
    )
    (cell VexRiscv
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
      )
    )
    (cell DataCache
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
      )
    )
  )
  (library DESIGN
    (edifLevel 0)
    (technology (numberDefinition))
    (cell DataCache
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
        (contents (instance cache_ram (viewRef VIEW_NETLIST (cellRef RAMB36E1 (libraryRef LIB)))))
      )
    )
    (cell VexRiscv
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
        (contents
          (instance dc (viewRef VIEW_NETLIST (cellRef DataCache (libraryRef LIB))))
        )
      )
    )
    (cell top
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
        (contents
          (instance cpu (viewRef VIEW_NETLIST (cellRef VexRiscv (libraryRef LIB))))
          (instance buf (viewRef VIEW_NETLIST (cellRef BUFG (libraryRef LIB))))
        )
      )
    )
  )
  (design top (cellRef top (libraryRef DESIGN)))
)
"""


# ---------------------------------------------------------------------------
# find_duplicated_cells — the auto-detection of stuck-in-LIB user modules
# ---------------------------------------------------------------------------

def test_find_duplicated_cells_identifies_user_modules():
    # VexRiscv and DataCache appear in both LIB and DESIGN — the fixer
    # must pick exactly these, and NOT BUFG (only in LIB) or top (only in
    # DESIGN).
    dup = fixer.find_duplicated_cells(MINIMAL_BROKEN_EDIF)
    assert dup == {"DataCache", "VexRiscv"}


def test_find_duplicated_cells_empty_when_no_overlap():
    # An EDIF where LIB holds only primitives and DESIGN holds only
    # user cells (the correct shape) has no duplicates and needs no fix.
    clean = MINIMAL_BROKEN_EDIF.replace(
        """    (cell VexRiscv
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
      )
    )
    (cell DataCache
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
      )
    )
  )""",
        "  )",
        1,  # only the external LIB block
    )
    assert fixer.find_duplicated_cells(clean) == set()


# ---------------------------------------------------------------------------
# fix_edif — core rewrite
# ---------------------------------------------------------------------------

def test_fix_rewrites_instance_references_for_duplicated_cells():
    fixed, n = fixer.fix_edif(MINIMAL_BROKEN_EDIF)
    # Three rewrites expected: the VexRiscv instance in top, the BUFG is
    # NOT rewritten (it's a real primitive), and DataCache appears twice
    # as an instance reference (once inside VexRiscv's contents, once
    # wouldn't exist in this fixture, so exactly one).
    assert n == 2  # one VexRiscv instance + one DataCache instance
    # Positive assertions — the bug is fixed:
    assert "(cellRef VexRiscv (libraryRef DESIGN))" in fixed
    assert "(cellRef DataCache (libraryRef DESIGN))" in fixed
    # Primitives must still reference LIB:
    assert "(cellRef BUFG (libraryRef LIB))" in fixed
    # Negative assertion — no stale LIB references for user modules
    # remain:
    assert "(cellRef VexRiscv (libraryRef LIB))" not in fixed
    assert "(cellRef DataCache (libraryRef LIB))" not in fixed


def test_fix_is_idempotent():
    # Running the fix twice must not introduce further changes: all
    # user-module references are already in DESIGN after the first pass.
    fixed_once, _ = fixer.fix_edif(MINIMAL_BROKEN_EDIF)
    fixed_twice, n2 = fixer.fix_edif(fixed_once)
    assert fixed_once == fixed_twice
    assert n2 == 0


def test_fix_no_op_on_clean_edif():
    # An EDIF that doesn't exhibit the bug must be returned unchanged.
    clean = """(edif top
  (external LIB (cell BUFG (view V (interface (port I (direction INPUT))))))
  (library DESIGN (cell top (view V (contents (instance b (viewRef V (cellRef BUFG (libraryRef LIB))))))))
  (design top (cellRef top (libraryRef DESIGN)))
)
"""
    fixed, n = fixer.fix_edif(clean)
    assert fixed == clean
    assert n == 0


def test_fix_does_not_touch_word_boundary_neighbours():
    # If a cell name is a prefix of another name (e.g. "VexRiscv" and
    # "VexRiscvFoo"), the fixer must not rewrite the longer one.
    edif_with_neighbour = MINIMAL_BROKEN_EDIF.replace(
        "(instance cpu (viewRef VIEW_NETLIST (cellRef VexRiscv (libraryRef LIB))))",
        "(instance cpu (viewRef VIEW_NETLIST (cellRef VexRiscv (libraryRef LIB))))\n"
        "          (instance cpu2 (viewRef VIEW_NETLIST (cellRef VexRiscvFoo (libraryRef LIB))))",
    )
    fixed, _ = fixer.fix_edif(edif_with_neighbour)
    # VexRiscv rewritten, VexRiscvFoo untouched:
    assert "(cellRef VexRiscv (libraryRef DESIGN))" in fixed
    assert "(cellRef VexRiscvFoo (libraryRef LIB))" in fixed
    assert "(cellRef VexRiscvFoo (libraryRef DESIGN))" not in fixed


# ---------------------------------------------------------------------------
# Rename-syntax cells (paramod'd modules like pcie_7x)
# ---------------------------------------------------------------------------

# Yosys emits parameterized modules with EDIF rename syntax:
#     (cell (rename id00001 "$paramod$HASH\\pcie_7x") ...)
# because the external name contains characters EDIF can't put directly in
# an identifier. The internal id00001 is what instance references use
# ((cellRef id00001 (libraryRef LIB))), and Yosys double-declares these
# cells in both LIB and DESIGN exactly like it does with plain-name cells.
# Seen in pcie-enumeration (pcie_7x + pipe_wrapper + pcie_block + ...).
RENAME_SYNTAX_BROKEN_EDIF = r"""(edif top
  (edifVersion 2 0 0)
  (edifLevel 0)
  (keywordMap (keywordLevel 0))
  (external LIB
    (edifLevel 0)
    (technology (numberDefinition))
    (cell BUFG
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port I (direction INPUT)))
      )
    )
    (cell (rename id00001 "$paramod$1a0e78990f48fe175a1df9b8601fbffb844268c9\pcie_7x")
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port sys_clk (direction INPUT)))
      )
    )
    (cell (rename id00002 "$paramod$0100cf3830e5a3c0200dcbf6367bcb83f5758c75\pipe_wrapper")
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
      )
    )
  )
  (library DESIGN
    (edifLevel 0)
    (technology (numberDefinition))
    (cell (rename id00001 "$paramod$1a0e78990f48fe175a1df9b8601fbffb844268c9\pcie_7x")
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port sys_clk (direction INPUT)))
        (contents (instance pw (viewRef VIEW_NETLIST (cellRef id00002 (libraryRef LIB)))))
      )
    )
    (cell (rename id00002 "$paramod$0100cf3830e5a3c0200dcbf6367bcb83f5758c75\pipe_wrapper")
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
      )
    )
    (cell top
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
        (contents
          (instance pcie (viewRef VIEW_NETLIST (cellRef id00001 (libraryRef LIB))))
          (instance buf (viewRef VIEW_NETLIST (cellRef BUFG (libraryRef LIB))))
        )
      )
    )
  )
  (design top (cellRef top (libraryRef DESIGN)))
)
"""


def test_find_duplicated_cells_handles_rename_syntax():
    # Yosys emits pcie_7x / pipe_wrapper / pcie_block / ... with rename
    # syntax because the external name contains `$paramod$HASH\\...` which
    # isn't a legal EDIF identifier. Duplication detection must capture the
    # *internal* id (which is what `(cellRef ...)` references use) for the
    # substitution to wire up correctly.
    dup = fixer.find_duplicated_cells(RENAME_SYNTAX_BROKEN_EDIF)
    assert dup == {"id00001", "id00002"}


def test_fix_rewrites_rename_syntax_cellrefs():
    # The pcie_7x instance references (cellRef id00001 (libraryRef LIB)) —
    # id00001 being the internal id from the rename pair. Fix must flip
    # these to DESIGN. BUFG (primitive, LIB-only) stays put.
    fixed, n = fixer.fix_edif(RENAME_SYNTAX_BROKEN_EDIF)
    assert n == 2  # one pcie (id00001) + one pipe_wrapper (id00002) refs
    assert "(cellRef id00001 (libraryRef DESIGN))" in fixed
    assert "(cellRef id00002 (libraryRef DESIGN))" in fixed
    assert "(cellRef BUFG (libraryRef LIB))" in fixed
    assert "(cellRef id00001 (libraryRef LIB))" not in fixed
    assert "(cellRef id00002 (libraryRef LIB))" not in fixed


def test_fix_rewrites_mixed_plain_and_rename_cells():
    # Real EDIFs from this repo mix plain names (VexRiscv, DataCache, top)
    # and rename-syntax paramod'd cells. Both forms must be detected and
    # substituted in a single pass.
    mixed = MINIMAL_BROKEN_EDIF.replace(
        "  )\n  (library DESIGN",
        r"""    (cell (rename id00042 "$paramod$abc\pcie_7x")
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
      )
    )
  )
  (library DESIGN""",
    ).replace(
        (
            "    (cell top\n"
            "      (cellType GENERIC)\n"
            "      (view VIEW_NETLIST\n"
            "        (viewType NETLIST)\n"
            "        (interface (port clk (direction INPUT)))\n"
            "        (contents\n"
            "          (instance cpu (viewRef VIEW_NETLIST "
            "(cellRef VexRiscv (libraryRef LIB))))"
        ),
        r"""    (cell (rename id00042 "$paramod$abc\pcie_7x")
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
      )
    )
    (cell top
      (cellType GENERIC)
      (view VIEW_NETLIST
        (viewType NETLIST)
        (interface (port clk (direction INPUT)))
        (contents
          (instance pcie (viewRef VIEW_NETLIST (cellRef id00042 (libraryRef LIB))))
          (instance cpu (viewRef VIEW_NETLIST (cellRef VexRiscv (libraryRef LIB))))""",
    )
    dup = fixer.find_duplicated_cells(mixed)
    assert dup == {"DataCache", "VexRiscv", "id00042"}
    fixed, _ = fixer.fix_edif(mixed)
    assert "(cellRef VexRiscv (libraryRef DESIGN))" in fixed
    assert "(cellRef id00042 (libraryRef DESIGN))" in fixed
    # Primitives (BUFG) stay in LIB — they're not duplicated.
    assert "(cellRef BUFG (libraryRef LIB))" in fixed


# ---------------------------------------------------------------------------
# CLI entry — files in, files out
# ---------------------------------------------------------------------------

def test_cli_reads_and_writes_files(tmp_path):
    src = tmp_path / "top.edif"
    src.write_text(MINIMAL_BROKEN_EDIF)
    dst = tmp_path / "top.fixed.edif"
    fixer.run_cli([str(src), str(dst)])
    assert dst.exists()
    fixed = dst.read_text()
    assert "(cellRef VexRiscv (libraryRef DESIGN))" in fixed


def test_cli_in_place(tmp_path):
    # When invoked with a single path, the fixer rewrites the file
    # in place — convenient as a post-yosys step in a build script.
    src = tmp_path / "top.edif"
    src.write_text(MINIMAL_BROKEN_EDIF)
    fixer.run_cli([str(src)])
    fixed = src.read_text()
    assert "(cellRef VexRiscv (libraryRef DESIGN))" in fixed


def test_cli_exits_nonzero_on_missing_source(tmp_path):
    with pytest.raises(SystemExit):
        fixer.run_cli([str(tmp_path / "nonexistent.edif")])


# ---------------------------------------------------------------------------
# Bug 2 — unused iopad removal (IBUF/OBUF wrapping dont_touch'd ports)
# ---------------------------------------------------------------------------

# Minimal fixture mirroring the real shape: pmod-loopback Acorn emits an
# unused IBUF on clk200_p (DCE removed the IBUFDS, but LiteX's
# (* dont_touch *) preserved the port, and Yosys's iopadmap then wrapped
# it). The iopad instance, its dangling output net (with unused_bits),
# and the port-side net that joined it back to the primary input all
# need to be cleaned up. A second IBUF on serial_rx (USED — its output
# feeds real logic) must survive untouched.
UNUSED_IOPAD_EDIF = """(edif top
  (edifVersion 2 0 0)
  (external LIB
    (cell IBUF (view V (interface (port I (direction INPUT)) (port O (direction OUTPUT)))))
  )
  (library DESIGN
    (cell top
      (view V
        (interface
          (port clk200_p (direction INPUT))
          (port serial_rx (direction INPUT))
        )
        (contents
          (instance (rename id00006 "$iopadmap$top.clk200_p")
            (viewRef VIEW_NETLIST (cellRef IBUF (libraryRef LIB)))
            (property keep (integer 1)))
          (instance (rename id00007 "$iopadmap$top.serial_rx")
            (viewRef VIEW_NETLIST (cellRef IBUF (libraryRef LIB)))
            (property keep (integer 1)))
          (net clk200_p (joined
              (portRef I (instanceRef id00006))
              (portRef clk200_p)
            )
            (property dont_touch (string "true"))
          )
          (net serial_rx (joined
              (portRef I (instanceRef id00007))
              (portRef serial_rx)
            )
          )
          (net (rename id00010 "$iopadmap$clk200_p") (joined
              (portRef O (instanceRef id00006))
            )
            (property unused_bits (string "0"))
          )
          (net (rename id00011 "$real_logic$serial_rx_sink") (joined
              (portRef O (instanceRef id00007))
              (portRef some_fabric_port (instanceRef real_cell))
            )
          )
        )
      )
    )
  )
  (design top (cellRef top (libraryRef DESIGN)))
)
"""


def test_find_unused_iopads_only_reports_unused():
    unused = fixer.find_unused_iopads(UNUSED_IOPAD_EDIF)
    # Only the clk200_p iopad is "unused" (its output net has unused_bits);
    # the serial_rx iopad drives real logic and must NOT be identified.
    assert unused == {"id00006"}


def test_remove_unused_iopads_deletes_the_right_bits():
    fixed, n = fixer.remove_unused_iopads(UNUSED_IOPAD_EDIF)
    assert n == 1

    # The dead iopad instance is gone.
    assert '"$iopadmap$top.clk200_p"' not in fixed
    # The dangling output net is gone.
    assert '"$iopadmap$clk200_p"' not in fixed
    # The port-side net lost its IBUF reference but the primary port
    # reference remains.
    assert "(portRef I (instanceRef id00006))" not in fixed
    assert "(portRef clk200_p)" in fixed
    # The still-used iopad on serial_rx survives.
    assert '"$iopadmap$top.serial_rx"' in fixed
    assert "(portRef I (instanceRef id00007))" in fixed
    # dont_touch property on the port-side net is preserved.
    assert '(property dont_touch (string "true"))' in fixed


def test_remove_unused_iopads_is_idempotent():
    once, n1 = fixer.remove_unused_iopads(UNUSED_IOPAD_EDIF)
    twice, n2 = fixer.remove_unused_iopads(once)
    assert once == twice
    assert n1 == 1 and n2 == 0


def test_remove_unused_iopads_no_op_on_clean_edif():
    # An EDIF with no iopadmap nets at all must be returned unchanged.
    clean = """(edif top
  (external LIB (cell IBUF (view V)))
  (library DESIGN (cell top (view V (contents (instance x (viewRef V (cellRef IBUF (libraryRef LIB))))))))
  (design top (cellRef top (libraryRef DESIGN)))
)
"""
    fixed, n = fixer.remove_unused_iopads(clean)
    assert fixed == clean
    assert n == 0


def test_remove_unused_iopads_leaves_primitives_alone():
    # A BUFG cell (not IBUF/OBUF) on a similarly-named unused_bits net
    # must NOT be removed — we only target iopadmap instances, not any
    # random primitive.
    non_iopad = UNUSED_IOPAD_EDIF.replace(
        "$iopadmap$top.clk200_p",
        "$iopadmap$top.clk200_p",
    ).replace(
        "(cellRef IBUF (libraryRef LIB)))\n"
        "            (property keep (integer 1))",
        "(cellRef BUFG (libraryRef LIB)))\n"
        "            (property keep (integer 1))",
        1,
    )
    unused = fixer.find_unused_iopads(non_iopad)
    # The regex explicitly matches `(cellRef (IBUF|OBUF) (libraryRef LIB))`,
    # so BUFG instances are excluded from the candidate set. id00006 is
    # now a BUFG; id00007 is still IBUF but has no unused_bits net.
    assert unused == set()


# ---------------------------------------------------------------------------
# Malformed-EDIF error paths — must raise loudly, not silently no-op
# ---------------------------------------------------------------------------

def test_find_duplicated_cells_raises_on_missing_lib_block():
    # If a future Yosys template change drops the `(external LIB ...)`
    # block, the fixer must not silently return an empty duplicate set —
    # that would let a broken EDIF through to Vivado with the original
    # INBB-3 failure and no clue that the post-processor ran.
    no_lib = """(edif top
  (library DESIGN (cell top (view V)))
  (design top (cellRef top (libraryRef DESIGN)))
)
"""
    with pytest.raises(ValueError, match="external LIB"):
        fixer.find_duplicated_cells(no_lib)


def test_find_duplicated_cells_raises_on_missing_design_block():
    no_design = """(edif top
  (external LIB
    (cell BUFG (view V))
  )
  (library PRIMITIVES (cell X (view V)))
  (design top (cellRef BUFG (libraryRef LIB)))
)
"""
    with pytest.raises(ValueError, match="library DESIGN"):
        fixer.find_duplicated_cells(no_design)
