"""The Acorn SoC names the board it was built for in the PCI subsystem IDs, and leaves the flash deselected.

Vendor:device must stay LitePCIe's own (10ee:7021) or litepcie.ko stops binding; the subsystem pair is what
`lspci` and rpi-hwid read to tell a CLE-215+ from a CLE-101 once SQRL's factory image is gone from the flash.
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
def _soc(variant="cle-215+", golden=False):
    return soc_mod.AcornPCIeSoC(variant=variant, golden=golden)  # about a minute each, so build each one once


@pytest.mark.parametrize(
    ("variant", "golden", "subsystem_id"),
    [("cle-215+", False, "021F"), ("cle-215+", True, "021F"), ("cle-101", False, "0101"), ("cle-101", True, "0101")],
)
def test_subsystem_ids_name_the_board_in_both_images(variant, golden, subsystem_id):
    config = _soc(variant, golden).pcie_phy.config
    assert config["Subsystem_Vendor_ID"] == "1E24"
    assert config["Subsystem_ID"] == subsystem_id
    assert "Device_ID" not in config and "Vendor_ID" not in config


def test_a_variant_nobody_has_seen_keeps_the_default_rather_than_a_guess():
    config = _soc("cle-215").pcie_phy.config
    assert "Subsystem_ID" not in config and "Subsystem_Vendor_ID" not in config


@pytest.mark.parametrize("golden", [False, True])
def test_the_flash_is_deselected_out_of_reset(golden):
    assert _soc(golden=golden).flash_cs_n.out.storage.reset.value == 1
