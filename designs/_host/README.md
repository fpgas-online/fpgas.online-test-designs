# Host Utilities

Host-side Python shared by the designs' test scripts: `bios_console.py`, which every script that talks to
a LiteX BIOS imports, and the scripts for the TT FPGA Demo Board, which handle the RP2350 microcontroller
that sits between the Raspberry Pi and the iCE40 FPGA on TT boards.

## Scripts

| Script | Purpose |
|--------|---------|
| `bios_console.py` | Find the LiteX BIOS prompt on a UART, run commands on it, and print a script's `RESULT_JSON` line |
| `tt_fpga_program.py` | Program the TT FPGA via the RP2350 USB CDC interface |
| `tt_test_wrapper.py` | Combined program + bridge + test runner for UART and SPI Flash tests |
| `tt_pmod_wrapper.py` | Program FPGA via RP2350, then hand off to RPi GPIO for PMOD tests |

## Usage

These scripts are uploaded to the Raspberry Pi by `verify_hardware.py` before
running tests. They are not called directly during development.
