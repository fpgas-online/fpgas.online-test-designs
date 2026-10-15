# Host Utilities

Host-side Python scripts for the TT FPGA Demo Board. These handle the
RP2350 microcontroller that sits between the Raspberry Pi and the iCE40
FPGA on TT boards.

## Scripts

| Script | Purpose |
|--------|---------|
| `tt_fpga_program.py` | Program the TT FPGA via the RP2350 USB CDC interface |
| `tt_test_wrapper.py` | Combined program + bridge + test runner for UART tests |
| `tt_main_py.py` | Reads the SHA-256 of the demo board's `main.py` and says whether it is still the SDK's own; the boot check runs it first, so a board a visitor changed fails with that reason |
| `tt_dip_switches.py` | Reads the demo board's eight DIP switches through the RP2350, in RAM, and fails naming any that is on; the boot check runs it first, under the display design (#166) |
| `tt_pmod_wiring.py` | Checks the three Pmod ribbons between a demo board with a Tiny Tapeout chip and the Pi's Pmod HAT, bit for bit: the RP2040 drives each signal from RAM over its raw REPL, the Pi reads every HAT line, the chip's factory test carries uio out on uo_out. The boot check's `wiring` test; a fault names its ribbon and pin |
| `tt_sdk_start.py` | Starts the demo board's Tiny Tapeout SDK (a soft reset from the friendly REPL) and says whether it came up; the boot check runs it before asking the board who it is |
| `tt_pmod_wrapper.py` | Program FPGA via RP2350, then hand off to RPi GPIO for PMOD tests |

## Usage

These scripts are uploaded to the Raspberry Pi by `verify_hardware.py` before
running tests. They are not called directly during development.
