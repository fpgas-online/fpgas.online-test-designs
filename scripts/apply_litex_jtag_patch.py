#!/usr/bin/env python3
"""Apply the JTAGPHY rx-wiring fix to a target jtag.py file.

Inserts the missing wiring block after the FSM's XFER-PADDING state, before
the next class definition (ECP5JTAGPHY).
"""
import sys

INSERT_MARKER = "# ECP5 JTAG PHY (Verilog + AsyncFIFO)"
SENTINEL = "# BUG FIX: upstream LiteX xc7 JTAGPHY"

FIX_TEXT = """
        # BUG FIX: upstream LiteX xc7 JTAGPHY declares rx_data/rx_valid/ready/
        # update_*/ready_value but never wires them to the source stream.
        # Without this fixup host->target writes are silently dropped.
        self.comb += ready_value.eq(source.ready)
        self.sync.jtag += [
            If(update_ready,
                ready.eq(ready_value),
            ),
            If(update_rx,
                rx_valid.eq(rx_valid_in),
                rx_data.eq(data),
            ).Elif(source.ready & rx_valid,
                rx_valid.eq(0),
            ),
        ]
        self.comb += [
            source.valid.eq(rx_valid),
            source.data.eq(rx_data),
        ]

"""

target = sys.argv[1]
with open(target) as f:
    src = f.read()

if SENTINEL in src:
    print(f"{target}: already patched, skipping.")
    sys.exit(0)

if INSERT_MARKER not in src:
    print(f"{target}: cannot find marker '{INSERT_MARKER}'", file=sys.stderr)
    sys.exit(1)

new_src = src.replace(INSERT_MARKER, FIX_TEXT.lstrip("\n") + INSERT_MARKER)
with open(target, "w") as f:
    f.write(new_src)
print(f"{target}: patched OK ({len(new_src) - len(src)} bytes added)")
