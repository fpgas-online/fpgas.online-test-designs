"""The Acorn endpoint must offer a 64-bit MSI address, or litepcie.ko cannot probe on a Raspberry Pi 5.

The BCM2712 puts its MSI target above 4 GiB (0xfffffff000). With LitePCIe's default 32-bit MSI capability the
kernel refuses it: "arch assigned 64-bit MSI address 0xfffffff000 but device only supports 32 bits", then
"Failed to enable MSI" and probe error -5 (pi-sw2-p48, 2026-09-25). The 7-series hard block writes the MSI
itself from the address the host programs, so the IP option is the whole fix. Both images carry the driver.
"""

import functools
import importlib.util
import pathlib

import pytest

pytest.importorskip("litex")
pytest.importorskip("litepcie")

_PATH = pathlib.Path(__file__).resolve().parents[1] / "designs" / "acorn-pcie" / "gateware" / "acorn_pcie_soc.py"
_spec = importlib.util.spec_from_file_location("acorn_pcie_soc", _PATH)
soc_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(soc_mod)


@functools.cache
def _soc(variant, golden):
    return soc_mod.AcornPCIeSoC(variant=variant, golden=golden)  # about a minute each, so build each one once


@pytest.mark.parametrize(
    ("variant", "golden"), [("cle-215+", False), ("cle-215+", True), ("cle-101", False), ("cle-215", False)]
)
def test_the_endpoint_offers_a_64_bit_msi_address(variant, golden):
    assert _soc(variant, golden).pcie_phy.config.get("MSI_64b") is True
