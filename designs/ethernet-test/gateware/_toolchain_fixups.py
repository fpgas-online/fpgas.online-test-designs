"""Shared toolchain workarounds and SoC kwarg helpers for Ethernet test designs.

Consolidates boilerplate that was duplicated across ethernet_soc_arty.py and
ethernet_soc_netv2.py.
"""


def clean_soc_kwargs(parser):
    """Return a cleaned soc_argdict from a LiteXArgumentParser.

    Removes ident/ident_version (hard-coded by upstream BaseSoC targets) and
    sets a default uart_baudrate of 115200.
    """
    soc_kwargs = parser.soc_argdict
    # Note: ident/ident_version are hard-coded by the upstream BaseSoC and
    # cannot be overridden via kwargs without causing a duplicate-keyword error.
    soc_kwargs.pop("ident", None)
    soc_kwargs.pop("ident_version", None)
    soc_kwargs["uart_baudrate"] = 115200
    return soc_kwargs


def apply_yosys_nextpnr_workarounds(soc):
    """Apply workarounds for yosys/nextpnr-xilinx incompatibilities.

    1. Newer yosys emits $scopeinfo debug cells that nextpnr-xilinx cannot
       place -- add a "delete t:$scopeinfo" step before writing the netlist.
    2. nextpnr-xilinx may not support RAM256X1S (distributed RAM) placement
       -- add -nodram to disable distributed RAM inference.
    """
    if hasattr(soc.platform.toolchain, "_synth_opts"):
        soc.platform.toolchain._synth_opts += " -nodram"
    from litex.build.yosys_wrapper import YosysWrapper
    patched = []
    for line in YosysWrapper._default_template:
        if line.startswith("write_"):
            patched.append("delete t:$scopeinfo")
        patched.append(line)
    soc.platform.toolchain._yosys_template = patched
