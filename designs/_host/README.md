# Host Utilities

Host-side Python scripts for the TT FPGA Demo Board. These handle the
RP2350 microcontroller that sits between the Raspberry Pi and the iCE40
FPGA on TT boards.

## Scripts

| Script | Purpose |
|--------|---------|
| `tt_fpga_program.py` | Program the TT FPGA via the RP2350 USB CDC interface |
| `tt_test_wrapper.py` | Combined program + bridge + test runner for UART and SPI Flash tests |
| `tt_pmod_wrapper.py` | Program FPGA via RP2350, then hand off to RPi GPIO for PMOD tests |

## Usage

These scripts are uploaded to the Raspberry Pi by `verify_hardware.py` before
running tests. They are not called directly during development.
