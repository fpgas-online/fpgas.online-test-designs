"""Shared helpers for DDR memory test SoC targets."""

import os

from litex.soc.integration.builder import Builder


# Yosys template that strips $scopeinfo cells newer Yosys emits but
# nextpnr-xilinx does not understand.
YOSYS_TEMPLATE = [
    "verilog_defaults -push",
    "verilog_defaults -add -defer",
    "{read_files}",
    "verilog_defaults -pop",
    'attrmap -tocase keep -imap keep="true" keep=1 -imap keep="false" keep=0 -remove keep=0',
    "{yosys_cmds}",
    "synth_{target} {synth_opts} -top {build_name}",
    "delete t:$scopeinfo",
    "write_{write_fmt} {write_opts} {output_name}.{synth_fmt}",
]


def patch_yosys_template(toolchain):
    """Apply the $scopeinfo workaround if the toolchain has _yosys_template."""
    if hasattr(toolchain, "_yosys_template"):
        toolchain._yosys_template = list(YOSYS_TEMPLATE)


def build_soc(soc, parser, args, board_name):
    """Configure builder with correct output dir and run the build."""
    patch_yosys_template(soc.platform.toolchain)

    builder_kwargs = parser.builder_argdict
    builder_kwargs["output_dir"] = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "build",
        board_name,
    )
    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)
