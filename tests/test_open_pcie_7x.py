"""The open pcie_7x core is given the endpoint the Xilinx IP would get (designs/_shared/open_pcie_7x.py).

With Vivado, S7PCIEPHY's settings and `update_config()` become the Xilinx IP's Tcl. Without it they have to
reach the open core as Verilog parameters, or the open-source image is a different PCI device: upstream's
wrapper is 10ee:7011 with a 64 MiB BAR0 at 2.5 GT/s, and litepcie.ko binds to 10ee:7021.
"""

import pathlib
import types

import pytest

pytest.importorskip("litex")
pytest.importorskip("litepcie")

from litepcie.phy.s7pciephy import S7PCIEPHY
from litex_boards.platforms import kosagi_netv2

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.open_pcie_7x import (
    PCIE_7X_SRC,
    UPSTREAM_WRAPPER,
    WRAPPER,
    open_pcie_7x_parameters,
    use_open_pcie_7x,
)


def _phy(**kwargs):
    platform = kosagi_netv2.Platform(variant="a7-35", toolchain="vivado")
    return S7PCIEPHY(platform, platform.request("pcie_x1"), data_width=64, bar0_size=0x20000, **kwargs)


def _values(parameters):
    return {k: getattr(v, "value", v) for k, v in parameters.items()}


def test_defaults_are_what_litepcie_asks_the_xilinx_ip_for():
    assert _values(open_pcie_7x_parameters(_phy())) == {
        "p_CFG_DEV_ID": 0x7021,
        "p_CFG_SUBSYS_VEND_ID": 0x10EE,
        "p_CFG_SUBSYS_ID": 0x0007,
        "p_BAR0": 0xFFF00000,  # litepcie rounds BAR0 up to 1 MiB: Bar0_Scale Megabytes, Bar0_Size 1
        "p_LINK_CAP_MAX_LINK_SPEED": 2,
        "p_LINK_CTRL2_TARGET_LINK_SPEED": 2,
        "p_MSI_CAP_64_BIT_ADDR_CAPABLE": "FALSE",
    }


def test_update_config_reaches_the_open_core():
    phy = _phy()
    phy.update_config({"MSI_64b": True, "Subsystem_Vendor_ID": "1E24", "Subsystem_ID": "021F"})
    values = _values(open_pcie_7x_parameters(phy))
    assert values["p_MSI_CAP_64_BIT_ADDR_CAPABLE"] == "TRUE"
    assert (values["p_CFG_SUBSYS_VEND_ID"], values["p_CFG_SUBSYS_ID"]) == (0x1E24, 0x021F)


def test_a_bigger_bar0_is_a_smaller_mask():
    phy = _phy()
    phy.bar0_size = 0x400000
    assert _values(open_pcie_7x_parameters(phy))["p_BAR0"] == 0xFFC00000


def test_a_setting_with_no_equivalent_stops_the_build():
    phy = _phy()
    phy.update_config({"Class_Code_Base": "02"})
    with pytest.raises(ValueError, match="Class_Code_Base"):
        open_pcie_7x_parameters(phy)


@pytest.mark.parametrize("change", [{"nlanes": 2}, {"msi_type": "msi-x"}, {"mode": "RootPort"}, {"refclk_freq": 125e6}])
def test_a_phy_the_open_core_cannot_stand_in_for_stops_the_build(change):
    phy = types.SimpleNamespace(
        nlanes=1, pcie_data_width=64, refclk_freq=100e6, mode="Endpoint", msi_type="msi", with_ptm=False,
        config={}, bar0_size=0x20000,
    )  # fmt: skip
    open_pcie_7x_parameters(phy)
    vars(phy).update(change)
    with pytest.raises(ValueError):
        open_pcie_7x_parameters(phy)


def test_the_phy_instantiates_the_repo_wrapper_and_writes_no_ip_tcl():
    if not (PCIE_7X_SRC / UPSTREAM_WRAPPER).exists():
        pytest.skip("pcie_7x submodule not checked out")
    phy = _phy()
    use_open_pcie_7x(phy)
    sources = [pathlib.Path(source[0]).name for source in phy.platform.sources]
    assert WRAPPER.name in sources and "pcie_7x.v" in sources
    assert UPSTREAM_WRAPPER not in sources  # two modules called pcie_s7 otherwise
    assert phy.external_hard_ip is True
    assert phy.pcie_phy_params["p_CFG_DEV_ID"].value == 0x7021


def test_the_submodule_missing_is_said_plainly(monkeypatch, tmp_path):
    monkeypatch.setattr("designs._shared.open_pcie_7x.PCIE_7X_SRC", tmp_path)
    with pytest.raises(FileNotFoundError, match="git submodule update --init"):
        use_open_pcie_7x(_phy())


def _without_parameters(text):
    """The wrapper's port list and body, with the lines that exist only to carry the parameters removed."""
    kept, in_header = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("module pcie_s7"):
            in_header = stripped.endswith("#(")
            kept.append("module pcie_s7 (")
            continue
        if in_header:
            in_header = stripped != ") ("
            continue
        if stripped.startswith("//") or stripped.startswith(".BAR0("):
            continue
        if any(stripped == f".{name}({name})," for name in _PARAMETERS):
            continue
        kept.append(line)
    return kept


_PARAMETERS = (
    "CFG_DEV_ID",
    "CFG_SUBSYS_VEND_ID",
    "CFG_SUBSYS_ID",
    "BAR0",
    "LINK_CAP_MAX_LINK_SPEED",
    "LINK_CTRL2_TARGET_LINK_SPEED",
    "MSI_CAP_64_BIT_ADDR_CAPABLE",
)


def test_the_repo_wrapper_is_upstreams_plus_the_parameters():
    # A submodule bump that changes upstream's wrapper (a new port, a new fixed setting) must be carried over.
    upstream = PCIE_7X_SRC / UPSTREAM_WRAPPER
    if not upstream.exists():
        pytest.skip("pcie_7x submodule not checked out")
    assert _without_parameters(WRAPPER.read_text()) == _without_parameters(upstream.read_text())
    for name in _PARAMETERS:
        assert f".{name}({name})," in WRAPPER.read_text()
