"""The golden and operational Acorn images must agree on every CSR they share.

One litepcie.ko and one set of host tools serve both images (design §3.2,
decision 10). LiteX allocates CSR slots in sorted-name order, so dropping
DDR3 and the P2 GPIO from golden would move everything unless `csr_map`
pins the shared modules. This elaborates both SoCs (no Vivado) and compares.
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
    "dna",
    "xadc",
    "flash",
    "flash_cs_n",
    "icap",
    "pcie_phy",
    "pcie_msi",
    "pcie_dma0",
    "pcie_endpoint",
]
OPERATIONAL_ONLY = ["sdram", "ddrphy", "p2_gpio"]


def _csr_origins(golden, variant="cle-215+"):
    soc = soc_mod.AcornPCIeSoC(variant=variant, golden=golden)
    soc.finalize()
    return {name: region.origin for name, region in soc.csr_regions.items()}


@pytest.fixture(scope="module")
def maps():
    return _csr_origins(golden=False), _csr_origins(golden=True)


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
    host = pathlib.Path(__file__).resolve().parents[1] / "designs" / "acorn-pcie" / "host" / "uartbone_link.py"
    if not host.exists():
        pytest.skip("host helper lands in Phase 2")
    spec = importlib.util.spec_from_file_location("uartbone_link", host)
    link = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(link)
    assert operational["identifier_mem"] == link.IDENT_ADDR
    assert operational["uartbone"] == link.TUNING_WORD_ADDR
    assert link.tuning_word(link.FAST_BAUD) == soc_mod.tuning_word(soc_mod.UART_FAST_BAUD, 100e6)
