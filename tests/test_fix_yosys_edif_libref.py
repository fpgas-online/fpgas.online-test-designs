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
