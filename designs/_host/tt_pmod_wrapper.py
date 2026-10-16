#!/usr/bin/env python3
"""Program TT FPGA Demo Board for PMOD loopback and release RP2350 GPIOs.

Programs the iCE40 with the loopback bitstream via RP2350 (`openFPGALoader
-b tt_fpga`, tt_test_wrapper.load), which also starts the 50 MHz clock and
leaves the RP2350's ui_in/uo_out/uio GPIOs high-Z so the RPi can drive/read
them directly through the PMOD HAT. The bitstream is streamed from this host
over the serial link, and nothing is written to the demo board.

The actual GPIO loopback test runs on the RPi via test_pmod_loopback.py.

Usage (on RPi):
    python3 tt_pmod_wrapper.py /dev/ttyACM0 bitstream.bin
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tt_test_wrapper import LOADED, load, reset_rp2350


def main():
    if len(sys.argv) < 3:
        print("usage: tt_pmod_wrapper.py PORT BITSTREAM", file=sys.stderr)
        return 2
    port, bitstream = sys.argv[1], sys.argv[2]

    print("Programming FPGA and releasing GPIOs...")
    reset_rp2350(port)
    rc, out, err = load(port, bitstream)
    print(out.strip())
    if err.strip():
        print(err.strip(), file=sys.stderr)
    if rc != 0 or LOADED not in out:
        print("ERROR: Setup did not complete", file=sys.stderr)
        return 1
    print("FPGA programmed with loopback, GPIOs released.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
