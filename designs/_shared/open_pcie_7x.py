"""The open-source pcie_7x core behind litepcie's S7PCIEPHY, configured as the PHY would configure the Xilinx IP.

S7PCIEPHY instantiates a module called `pcie_s7`. With Vivado that is the Xilinx pcie_7x IP, generated from
Tcl the PHY writes out of its own settings and `update_config()`. Without Vivado it is
https://github.com/regymm/pcie_7x (the submodule at designs/pcie-enumeration/gateware/pcie_7x), whose own
`pcie_s7` wrapper fixes the configuration: a 10ee:7011 device with a 64 MiB BAR0 that only offers 2.5 GT/s.
`open_pcie_s7.v`, next to this file, is that wrapper with the configuration as parameters, and
`use_open_pcie_7x()` sets them from the PHY, so one SoC source describes the endpoint for both flows.

What is carried over: device ID, subsystem IDs, BAR0 size, link speed, 64-bit MSI address. Everything else
the Xilinx IP derives from its settings (buffer credits, legacy interrupt pin, power management and ASPM
fields, ...) stays at the open core's defaults and has not been compared with the IP's.
"""

import pathlib

from migen import Constant

_HERE = pathlib.Path(__file__).resolve().parent
PCIE_7X_SRC = _HERE.parent / "pcie-enumeration" / "gateware" / "pcie_7x" / "src"
WRAPPER = _HERE / "open_pcie_s7.v"
UPSTREAM_WRAPPER = "litepcie_pcie_s7.v"  # defines pcie_s7 too: left out, WRAPPER replaces it

MB = 1024 * 1024

# The Xilinx IP's own defaults for what S7PCIEPHY leaves unset (PG054).
_IP_DEFAULTS = {"Subsystem_Vendor_ID": "10EE", "Subsystem_ID": "0007", "MSI_64b": False}


def open_pcie_7x_parameters(phy):
    """The `open_pcie_s7.v` parameters that give the endpoint *phy* asks the Xilinx IP for.

    Raises ValueError for a PHY the open core cannot stand in for, or an `update_config()` key this does
    not know how to carry over: better no build than an endpoint that silently differs from the Vivado one.
    """
    if phy.nlanes != 1 or phy.pcie_data_width != 64 or phy.refclk_freq != 100e6:
        raise ValueError(
            "the open pcie_7x core is x1, 64-bit, 100 MHz reference only:"
            f" got x{phy.nlanes}, {phy.pcie_data_width}-bit, {phy.refclk_freq / 1e6:g} MHz"
        )
    if phy.mode != "Endpoint" or phy.msi_type != "msi" or phy.with_ptm:
        raise ValueError("the open pcie_7x wrapper is an endpoint with single-vector MSI and no PTM")
    unknown = sorted(set(phy.config) - set(_IP_DEFAULTS))
    if unknown:
        raise ValueError(f"S7PCIEPHY config {unknown} has no equivalent in designs/_shared/open_pcie_s7.v yet")
    config = {**_IP_DEFAULTS, **phy.config}

    # S7PCIEPHY.add_sources gives the IP Bar0_Scale=Megabytes and Bar0_Size=max(bar0_size / MB, 1): no BAR0 is
    # smaller than 1 MiB whatever bar0_size says. The low four bits (memory, 32-bit, not prefetchable) stay 0.
    bar0_bytes = int(max(phy.bar0_size / MB, 1) * MB)
    if bar0_bytes & (bar0_bytes - 1) or bar0_bytes >= 1 << 32:
        raise ValueError(f"BAR0 of {bar0_bytes} bytes is not a power of two below 4 GiB")

    return {
        "p_CFG_DEV_ID": Constant(0x7020 + phy.nlanes, 16),  # what litepcie.ko binds to
        "p_CFG_SUBSYS_VEND_ID": Constant(int(config["Subsystem_Vendor_ID"], 16), 16),
        "p_CFG_SUBSYS_ID": Constant(int(config["Subsystem_ID"], 16), 16),
        "p_BAR0": Constant((1 << 32) - bar0_bytes, 32),
        # Link_Speed 5.0_GT/s and Trgt_Link_Speed 4'h2, which S7PCIEPHY always asks for.
        "p_LINK_CAP_MAX_LINK_SPEED": Constant(2, 4),
        "p_LINK_CTRL2_TARGET_LINK_SPEED": Constant(2, 4),
        "p_MSI_CAP_64_BIT_ADDR_CAPABLE": "TRUE" if config["MSI_64b"] else "FALSE",
    }


def use_open_pcie_7x(phy):
    """Make *phy*'s `pcie_s7` the open core. Call it after the last `phy.update_config()`."""
    sources = sorted(p for p in PCIE_7X_SRC.glob("*.v") if p.name != UPSTREAM_WRAPPER)
    if not sources:
        raise FileNotFoundError(f"no pcie_7x sources in {PCIE_7X_SRC}: run `git submodule update --init`")
    parameters = open_pcie_7x_parameters(phy)
    for source in [*sources, WRAPPER]:
        phy.platform.add_source(str(source))
    # The PHY must not write its Xilinx IP Tcl (create_ip, and reset_property on the IP's cell names).
    phy.external_hard_ip = True
    phy.pcie_phy_params.update(parameters)
