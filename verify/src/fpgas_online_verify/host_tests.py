"""The host test scripts the checks run. They live in this repository's designs/*/host/ (verify_hardware.py
uploads them from there too); a package build copies them into fpgas_online_verify/scripts/, and running from
a checkout uses them where they are."""

import pathlib

# Installed name -> where it is in the repository.
SCRIPTS = {
    "test_uart.py": "designs/uart/host/test_uart.py",
    "test_ddr.py": "designs/ddr-memory/host/test_ddr.py",
    "test_spiflash.py": "designs/spi-flash-id/host/test_spiflash.py",
    "test_ethernet.py": "designs/ethernet-test/host/test_ethernet.py",
    "test_pmod_loopback.py": "designs/pmod-loopback/host/test_pmod_loopback.py",
    "identify_pmod_pins.py": "designs/pmod-pin-id/host/identify_pmod_pins.py",
    "tt_fpga_program.py": "designs/_host/tt_fpga_program.py",
    "tt_test_wrapper.py": "designs/_host/tt_test_wrapper.py",
}
PACKAGED = pathlib.Path(__file__).resolve().parent / "scripts"
REPO = pathlib.Path(__file__).resolve().parents[3]


def path(name):
    packaged = PACKAGED / name
    return packaged if packaged.is_file() else REPO / SCRIPTS[name]
