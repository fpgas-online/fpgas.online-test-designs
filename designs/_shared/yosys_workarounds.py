"""Yosys/nextpnr-xilinx workarounds for openXC7 toolchain builds.

Newer Yosys versions (>= 0.40) emit ``$scopeinfo`` debug cells that
nextpnr-xilinx cannot place.  This module provides the patched Yosys
template and helpers to apply it.
"""

from litex.build.yosys_wrapper import YosysWrapper


# The default LiteX Yosys template with an extra ``delete t:$scopeinfo``
# step inserted just before the ``write_*`` command.
YOSYS_TEMPLATE_STRIP_SCOPEINFO = list(YosysWrapper._default_template)
for _i, _line in enumerate(YOSYS_TEMPLATE_STRIP_SCOPEINFO):
    if _line.startswith("write_"):
        YOSYS_TEMPLATE_STRIP_SCOPEINFO.insert(_i, "delete t:$scopeinfo")
        break


def patch_yosys_template(soc):
    """Apply the ``$scopeinfo`` workaround to *soc*'s platform toolchain.

    Asserts that the toolchain exposes the expected ``_yosys_template``
    attribute so we fail early if the LiteX internals change.
    """
    assert hasattr(soc.platform.toolchain, "_yosys_template"), (
        "Toolchain does not have '_yosys_template' attribute — "
        "the LiteX API may have changed"
    )
    soc.platform.toolchain._yosys_template = list(YOSYS_TEMPLATE_STRIP_SCOPEINFO)


def apply_nodram_workaround(soc):
    """Add ``-nodram`` to synthesis options if supported.

    nextpnr-xilinx may not support RAM256X1S (distributed RAM) placement
    for some packages.  Adding ``-nodram`` forces Yosys to use block RAM
    or LUT-based storage instead.
    """
    if hasattr(soc.platform.toolchain, "_synth_opts"):
        soc.platform.toolchain._synth_opts += " -nodram"
