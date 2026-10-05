"""The golden and operational Acorn images must agree on every CSR they share.

One litepcie.ko and one set of host tools serve both images (design §3.2,
decision 10). LiteX allocates CSR slots in sorted-name order, so dropping
DDR3 and the P2 GPIO from golden would move everything unless `csr_map`
pins the shared modules. This elaborates both SoCs (no Vivado) and compares.

Every other CSR a host reads is pinned too, so its address can only move by
an edit to this file: the slots below are the ones the released images have.
"""

import importlib.util
import pathlib

import pytest

pytest.importorskip("litex")
pytest.importorskip("litepcie")

_PATH = pathlib.Path(__file__).resolve().parents[1] / "designs" / "acorn-pcie" / "gateware" / "acorn_pcie_soc.py"
_spec = importlib.util.spec_from_file_location("acorn_pcie_soc", _PATH)
soc_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(soc_mod)

# What the host tools touch in either image.
SHARED = [
    "ctrl",
    "identifier_mem",
    "uart",
    "uartbone",
    "timer0",
    "dna",
    "xadc",
    "flash",
    "flash_cs_n",
    "icap",
    "pcie_phy",
    "pcie_msi",
    "pcie_dma0",
    "pcie_endpoint",
    "leds",
]
OPERATIONAL_ONLY = ["sdram", "ddrphy", "p2_gpio", "dram_generator", "dram_checker", "p2_serial"]

# The slot of every module, as released. Slots 0-17 are in release
# vivado-bitstreams-acorn-pcie-20260923-ge48a750c8303 (15-17 were unpinned there,
# and sat where these pins keep them); 18-20 came with the DRAM BIST and the P2 switch.
SLOTS = {
    "ctrl": 0,
    "identifier_mem": 1,
    "uart": 2,
    "uartbone": 3,
    "timer0": 4,
    "dna": 5,
    "xadc": 6,
    "flash": 7,
    "flash_cs_n": 8,
    "icap": 9,
    "pcie_phy": 10,
    "pcie_msi": 11,
    "pcie_dma0": 12,
    "pcie_endpoint": 13,
    "leds": 14,
    "ddrphy": 15,
    "p2_gpio": 16,
    "sdram": 17,
    "dram_generator": 18,
    "dram_checker": 19,
    "p2_serial": 20,
}
CSR_BASE = 0xF0000000
PAGING = 0x800
VARIANTS = ["cle-215+", "cle-215", "cle-101"]


def _csr_origins(golden, variant="cle-215+"):
    soc = soc_mod.AcornPCIeSoC(variant=variant, golden=golden)
    soc.finalize()
    return {name: region.origin for name, region in soc.csr_regions.items()}


@pytest.fixture(scope="module")
def maps():
    return _csr_origins(golden=False), _csr_origins(golden=True)


def test_csr_map_pins_every_slot_where_it_was_released():
    assert soc_mod.AcornPCIeSoC.csr_map == SLOTS


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("golden", [False, True], ids=["operational", "golden"])
def test_every_csr_sits_in_its_pinned_slot(variant, golden):
    origins = _csr_origins(golden=golden, variant=variant)
    want = set(SHARED) if golden else set(SHARED) | set(OPERATIONAL_ONLY)
    assert set(origins) == want, "a CSR module that is not pinned (or a pinned one missing)"
    assert {n: hex(o) for n, o in origins.items()} == {n: hex(CSR_BASE + SLOTS[n] * PAGING) for n in origins}


def test_shared_csrs_sit_at_the_same_address_in_both_images(maps):
    operational, golden = maps
    moved = {n: (hex(operational[n]), hex(golden[n])) for n in SHARED if operational[n] != golden[n]}
    assert moved == {}


def test_golden_has_nothing_that_can_fail_calibration(maps):
    operational, golden = maps
    for name in OPERATIONAL_ONLY:
        assert name in operational
        assert name not in golden


def test_operational_only_modules_sit_above_the_pinned_block(maps):
    operational, _ = maps
    top_of_pinned = max(operational[n] for n in SHARED)
    for name in OPERATIONAL_ONLY:
        assert operational[name] > top_of_pinned


def test_the_host_link_helper_uses_the_addresses_the_gateware_has(maps):
    operational, _ = maps
    host = (pathlib.Path(__file__).resolve().parents[1] / "verify" / "src" / "fpgas_online_verify" / "boards"
            / "acorn" / "uartbone_link.py")  # fmt: skip
    spec = importlib.util.spec_from_file_location("uartbone_link", host)
    link = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(link)
    assert operational["identifier_mem"] == link.IDENT_ADDR
    assert operational["uartbone"] == link.TUNING_WORD_ADDR
    assert link.tuning_word(link.FAST_BAUD) == soc_mod.tuning_word(soc_mod.UART_FAST_BAUD, 100e6)
