#!/usr/bin/env python3
"""Program TT FPGA Demo Board for PMOD loopback and release RP2350 GPIOs.

Programs the iCE40 with the loopback bitstream via RP2350, starts the
50 MHz clock, then releases all RP2350 GPIOs to high-Z so the RPi can
drive/read them directly through the PMOD HAT. That is exactly
`tt_fpga_program.py --gpio-release`, which this calls: the RP2350 reads
the bitstream from this host over the serial link, and nothing is written
to the demo board.

The actual GPIO loopback test runs on the RPi via test_pmod_loopback.py.

Usage (on RPi):
    python3 tt_pmod_wrapper.py /dev/ttyACM0 bitstream.bin
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tt_fpga_program
from tt_test_wrapper import reset_rp2350


def main():
    if len(sys.argv) < 3:
        print("usage: tt_pmod_wrapper.py PORT BITSTREAM", file=sys.stderr)
        return 2
    port, bitstream = sys.argv[1], sys.argv[2]

    print("Programming FPGA and releasing GPIOs...")
    reset_rp2350(port)
    rc, out, err = tt_fpga_program.program(port, bitstream, gpio_release=True)
    print(out.strip())
    if err.strip():
        print(err.strip(), file=sys.stderr)
    if rc != 0 or "GPIO_RELEASED" not in out:
        print("ERROR: Setup did not complete", file=sys.stderr)
        return 1
    print("FPGA programmed with loopback, GPIOs released.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
