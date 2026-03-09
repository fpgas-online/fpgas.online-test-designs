"""
Shared helpers for UART test SoC targets.

Provides the Yosys template workaround and common build logic used by
both the Arty and NeTV2 targets.
"""

import os
from pathlib import Path

from litex.soc.integration.builder import Builder


# Yosys template that strips $scopeinfo cells emitted by newer Yosys
# versions, which nextpnr-xilinx does not support.
YOSYS_TEMPLATE_STRIP_SCOPEINFO = [
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


def default_soc_kwargs(parser, ident: str) -> dict:
    """Return common SoC keyword arguments with the given ident string."""
    soc_kwargs = parser.soc_argdict
    soc_kwargs["ident"]                    = ident
    soc_kwargs["ident_version"]            = True
    soc_kwargs["uart_baudrate"]            = 115200
    soc_kwargs["integrated_main_ram_size"] = 8192
    return soc_kwargs


def patch_yosys_template(soc) -> None:
    """Apply the $scopeinfo workaround to the platform toolchain.

    Asserts that the toolchain exposes the expected ``_yosys_template``
    attribute so we fail early if the LiteX internals change.
    """
    assert hasattr(soc.platform.toolchain, "_yosys_template"), (
        "Toolchain does not have '_yosys_template' attribute — "
        "the LiteX API may have changed"
    )
    soc.platform.toolchain._yosys_template = YOSYS_TEMPLATE_STRIP_SCOPEINFO


def build_soc(soc, parser, subdir: str) -> None:
    """Configure the Builder and run the build if requested.

    *subdir* is the board-specific subdirectory name under ``build/``
    (e.g. ``"arty"`` or ``"netv2"``).
    """
    args = parser.parse_args()

    # Resolve output_dir relative to the design directory (two levels up
    # from the gateware scripts).
    design_dir = Path(os.path.realpath(__file__)).parent.parent
    builder_kwargs = parser.builder_argdict
    builder_kwargs["output_dir"] = str(design_dir / "build" / subdir)
    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)
