"""Every Acorn design's P2 pins must be the fleet's wiring (docs/wiring/acorn/wiring.toml).

The serial pins come from designs/_shared/acorn_p2.py. This checks that file against wiring.toml,
that no Acorn design builds its platform any other way, and, by elaborating each design with a
UART (no toolchain run), that the pins it actually requests are FPGA TX on K2 and RX on J2.
"""

import importlib.util
import pathlib
import re

import pytest
import tomllib

pytest.importorskip("litex")

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared import acorn_p2

REPO = pathlib.Path(__file__).resolve().parents[1]
WIRING = tomllib.loads((REPO / "docs" / "wiring" / "acorn" / "wiring.toml").read_text())
ACORN_DESIGNS = sorted(REPO.glob("designs/*/gateware/*acorn*.py"))


def _wired(drive):
    return [name for name in WIRING["connectors"]["P2"]["pins"] if WIRING["signals"][name].get("drive") == drive]


def test_the_shared_pins_are_the_wiring():
    assert _wired("fpga") == [acorn_p2.SERIAL_TX]
    assert _wired("pi") == [acorn_p2.SERIAL_RX]
    assert list(acorn_p2.SPARE_GPIO) == _wired("both")  # in P2 pin order, as p2_gpio's bits


def test_switch_bits_follow_p2_pin_order():
    p2 = WIRING["connectors"]["P2"]["pins"]
    assert sorted(acorn_p2.SWITCH_BITS, key=p2.index) == sorted(acorn_p2.SWITCH_BITS, key=acorn_p2.SWITCH_BITS.get)


def test_no_acorn_design_takes_the_platform_unchanged_from_litex_boards():
    assert len(ACORN_DESIGNS) >= 7
    for path in ACORN_DESIGNS:
        code = path.read_text()
        direct = re.findall(r"(?<![\w.])(?:sqrl_acorn\.)?Platform\(", code)
        if path.name == "pmod_pin_id_acorn.py":
            continue  # drops `serial` altogether: every P2 pin is an output there
        assert not direct, f"{path.relative_to(REPO)} builds sqrl_acorn.Platform itself; use fleet_platform()"
        assert "fleet_platform(" in code, path.relative_to(REPO)


def _load(rel):
    spec = importlib.util.spec_from_file_location(pathlib.Path(rel).stem, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _serial_pins(platform):
    pins = {}
    for _sig, sig_pins, _others, (name, _number, sub) in platform.constraint_manager.get_sig_constraints():
        if name == "serial":
            pins[sub] = sig_pins
    return pins


def _acorn_pcie(golden):
    return _load("designs/acorn-pcie/gateware/acorn_pcie_soc.py").AcornPCIeSoC(golden=golden)


def _gpio_loopback():
    mod = _load("designs/pmod-loopback/gateware/gpio_loopback_acorn.py")
    platform = acorn_p2.fleet_platform("cle-215+", "vivado")
    mod.GPIOLoopback(platform)
    return platform


BUILDERS = {
    "acorn-pcie": lambda: _acorn_pcie(golden=False).platform,
    "acorn-pcie-golden": lambda: _acorn_pcie(golden=True).platform,
    "uart": lambda: _load("designs/uart/gateware/uart_soc_acorn.py").BaseSoC(toolchain="vivado").platform,
    "ddr-memory": lambda: _load("designs/ddr-memory/gateware/ddr_soc_acorn.py").BaseSoC(toolchain="vivado").platform,
    "spi-flash-id": lambda: (
        _load("designs/spi-flash-id/gateware/spiflash_soc_acorn.py").BaseSoC(toolchain="vivado").platform
    ),
    "pcie-enumeration": lambda: (
        _load("designs/pcie-enumeration/gateware/pcie_soc_acorn.py").PCIeEnumerationSoC(toolchain="vivado").platform
    ),
    "pmod-loopback": _gpio_loopback,
}


@pytest.mark.parametrize("design", sorted(BUILDERS))
def test_the_design_puts_its_uart_on_the_wired_pins(design):
    assert _serial_pins(BUILDERS[design]()) == {"tx": [acorn_p2.SERIAL_TX], "rx": [acorn_p2.SERIAL_RX]}
