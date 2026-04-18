"""Common build helpers for LiteX test SoC targets.

Provides standardised SoC kwarg preparation and Builder invocation so
that each design target only needs to define its SoC class and call
these helpers.
"""

import os
import sys
from pathlib import Path

from litex.soc.integration.builder import Builder

# Monkey-patch the Vivado toolchain so yosys-vivado builds don't hit the
# EDIF libraryRef bug. See patch_vivado_toolchain_for_yosys_edif() below
# for the full rationale — applying at import time is the same idiom the
# rest of this module uses (patch_builder_for_ice40 etc.).
_FIX_EDIF_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "fix_yosys_edif_libref.py"
)


def variant_dir(variant):
    """Normalise a board variant string for use in a build-directory name.

    Most variant strings (``a7-35``, ``a7-100``, ``cle-101``, ``cle-215``)
    are already directory-safe. The one special case is the Acorn
    CLE-215**+** variant whose ``+`` character is awkward in paths and
    shell-quoted Makefile targets; map it to ``p`` to match the pcie
    convention (``cle-215p``). All other characters pass through
    unchanged so the result matches the user-visible ``--variant`` arg.
    """
    return variant.replace("+", "p")


def board_dir(base, variant):
    """Return the ``build/<board-variant>`` base name for a design.

    Combines the board family (``arty``/``netv2``/``acorn``/…) with a
    normalised variant so every build lands in a uniquely-named
    directory. Every Xilinx design in the repo uses this — there are
    no special cases.
    """
    return f"{base}-{variant_dir(variant)}"


def flow_suffix(toolchain, synth_mode=None):
    """Return the ``build/<board>`` directory suffix for a toolchain flow.

    Four flows are supported across the designs. The suffix follows
    the uniform ``-<synth>-<pnr>`` shape so every flow sits side by
    side with no special cases:

    - ``vivado`` + ``synth_mode="vivado"`` (pure proprietary) →
      ``"-vivado-vivado"``. Vivado does both synthesis and P&R.
    - ``vivado`` + ``synth_mode="yosys"`` (hybrid; see the
      ``synth_mode`` branch in ``litex/build/xilinx/vivado.py``) →
      ``"-yosys-vivado"``. Yosys does synthesis, Vivado does P&R.
    - ``openxc7`` / ``yosys+nextpnr`` (fully open-source Xilinx) →
      ``"-yosys-nextpnr"``. Yosys does synthesis, nextpnr-xilinx
      does P&R.
    - ``icestorm`` (fully open-source iCE40 — Fomu, TT FPGA) →
      ``"-yosys-nextpnr"``. Same synth-pnr family as openxc7 but
      uses nextpnr-ice40 + icestorm bitgen. The directory suffix is
      identical because the tool family is identical; the platform
      name in the bitstream path already identifies which FPGA
      target it built for.

    Keeping every flow in its own directory prevents back-to-back
    runs from clobbering each other's output.
    """
    if toolchain == "vivado":
        return "-yosys-vivado" if synth_mode == "yosys" else "-vivado-vivado"
    if toolchain in ("openxc7", "yosys+nextpnr", "icestorm"):
        return "-yosys-nextpnr"
    raise ValueError(
        f"flow_suffix: unknown toolchain {toolchain!r}; expected one of "
        "'vivado', 'openxc7', 'yosys+nextpnr', 'icestorm'"
    )


def default_soc_kwargs(parser, ident):
    """Return common SoC keyword arguments with the given *ident* string.

    Sets reasonable defaults for the test designs:
    - ``ident``: design identification string (shown in BIOS banner)
    - ``ident_version``: True (include LiteX version in ident)
    - ``uart_baudrate``: 115200 (standard for all test designs)
    - ``integrated_main_ram_size``: 8192 (for openXC7 builds without DDR)
    """
    soc_kwargs = parser.soc_argdict
    soc_kwargs["ident"] = ident
    soc_kwargs["ident_version"] = True
    soc_kwargs["uart_baudrate"] = 115200
    soc_kwargs["integrated_main_ram_size"] = 8192
    return soc_kwargs


def default_build_dir(gateware_file, board_name):
    """Return the default build output directory for *board_name*.

    *gateware_file* should be ``__file__`` from the calling script.
    The build directory is placed at ``<design_dir>/build/<board_name>/``
    where ``<design_dir>`` is two levels up from the gateware script.
    """
    design_dir = Path(os.path.realpath(gateware_file)).parent.parent
    return str(design_dir / "build" / board_name)


def patch_vivado_toolchain_for_yosys_edif():
    """Patch XilinxVivadoToolchain.build_script to fix Yosys-emitted EDIFs.

    Yosys 0.64+68 writes non-top user modules (VexRiscv, InstructionCache,
    DataCache, …) as port-only black-box stubs in the EDIF's ``external LIB``
    library AND as full synthesized netlists in ``library DESIGN``, while
    every instance reference points to ``(libraryRef LIB)``. Vivado binds
    the instances to the stubs and ``opt_design`` dies with
    ``[DRC INBB-3] Black Box Instances``. See issue #6 and
    ``scripts/fix_yosys_edif_libref.py`` for the full story.

    This patch inserts a post-Yosys / pre-Vivado step into the generated
    build script that rewrites the EDIF's instance references from LIB
    to DESIGN. Only active when ``synth_mode=="yosys"`` — pure Vivado
    builds don't hit the bug and aren't touched.

    Applied unconditionally at import time because every yosys-vivado
    build is affected; there is no build-time kwarg that would want to
    opt out. Guarded against double-patching so repeated imports are
    safe.
    """
    from litex.build.xilinx.vivado import XilinxVivadoToolchain

    if getattr(XilinxVivadoToolchain.build_script,
               "_fpgas_online_yosys_edif_patched", False):
        return

    orig = XilinxVivadoToolchain.build_script

    def patched(self):
        script_file = orig(self)
        if self._synth_mode != "yosys":
            return script_file
        # Splice the EDIF fixer between the yosys invocation and the
        # vivado invocation in the generated build_*.sh / build_*.bat.
        # Use the absolute path to sys.executable so the fix runs in
        # the same Python interpreter as the rest of the LiteX build —
        # no reliance on `uv` or `python` being first on $PATH when the
        # build script is later executed by bash.
        path = Path(script_file)
        content = path.read_text()
        fix_cmd = (
            f"{sys.executable} {_FIX_EDIF_SCRIPT} "
            f"{self._build_name}.edif\n"
        )
        marker = f"vivado -mode batch -source {self._build_name}.tcl"
        if marker not in content:
            raise RuntimeError(
                f"patch_vivado_toolchain_for_yosys_edif: expected marker "
                f"{marker!r} in generated build script {path}; LiteX may "
                "have changed its template and the patch needs updating."
            )
        content = content.replace(marker, fix_cmd + marker, 1)
        path.write_text(content)
        return script_file

    patched._fpgas_online_yosys_edif_patched = True
    XilinxVivadoToolchain.build_script = patched


# Apply the patch at import time. Every gateware script that uses these
# helpers will benefit; standalone scripts that don't import this module
# are expected to be openxc7/yosys+nextpnr/icestorm-only and won't hit
# the bug anyway.
patch_vivado_toolchain_for_yosys_edif()


def patch_builder_for_ice40(builder):
    """Patch Builder to minimise BIOS binary size for iCE40UP5K.

    - Adds ``-ffunction-sections -fdata-sections`` so ``--gc-sections``
      can discard individual unused functions (not just whole objects).
    - Forces ``BIOS_CONSOLE_LITE=1`` so the Makefile compiles the small
      ``readline_simple.o`` instead of the full ``readline.o``, even when
      ``bios_console="disable"`` is used.  The C code only checks
      ``BIOS_CONSOLE_DISABLE`` for the console loop, so both flags are
      safe to combine.
    """
    orig = builder._get_variables_contents

    def _patched():
        extra = (
            "\nCPUFLAGS += -ffunction-sections -fdata-sections"
            "\nBIOS_CONSOLE_LITE=1"
        )
        return orig() + extra

    builder._get_variables_contents = _patched


def build_soc(soc, parser, board_name, gateware_file=None, args=None):
    """Configure the Builder and run the build if requested.

    *board_name* is the board-specific subdirectory name under ``build/``
    (e.g. ``"arty"`` or ``"netv2"``). A flow-specific suffix is appended
    automatically so the three supported toolchain flows write to
    distinct directories — see :func:`flow_suffix` for the mapping.

    If *gateware_file* is provided, the output directory is resolved
    relative to that file's design directory.  Otherwise falls back to
    the parser's builder_argdict output_dir (if set).

    If *args* is provided, it is used directly instead of calling
    ``parser.parse_args()`` again (which would cause argparse conflicts
    when the caller has already parsed arguments).
    """
    if args is None:
        args = parser.parse_args()

    # ``toolchain_argdict`` is ``{"synth_mode": ...}`` for the Vivado
    # toolchain and an empty dict for openxc7/yosys+nextpnr — both
    # handled by ``flow_suffix``. ``getattr`` is a defensive guard
    # for LiteXArgumentParser instances whose ``parse_args`` has not
    # run yet (``_toolchain`` is ``None`` in that case, which would
    # otherwise fall through to ``flow_suffix(None, …)`` and raise).
    # All current callers use LiteXArgumentParser, so only the
    # ``_toolchain is not None`` path is exercised.
    toolchain = getattr(parser, "_toolchain", None)
    toolchain_argdict = getattr(parser, "toolchain_argdict", {})
    if toolchain is not None:
        board_name = board_name + flow_suffix(toolchain,
                                              toolchain_argdict.get("synth_mode"))

    builder_kwargs = getattr(parser, "builder_argdict", {})
    if gateware_file is not None:
        builder_kwargs["output_dir"] = default_build_dir(gateware_file, board_name)

    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**toolchain_argdict)
