"""Feed litepcie S7PCIEPHY's PIPE clock mux straight from its MMCM, as Xilinx's pipe_clock does.

S7PCIEPHY buffers the MMCM's 125 and 250 MHz outputs with BUFGs and muxes those BUFG outputs through a
BUFGCTRL to make PIPECLK: two global buffers in series, where USERCLK goes through one. The extra buffer's
delay puts the PCIE_2_1 PIPECLK/USERCLK Max Skew check over its limit (0.595 ns against 0.560 ns on the
Acorn CLE-215+ SoC, fast corner). With the BUFGCTRL fed from the MMCM outputs each path has one global
buffer: 0.533 ns on the same routed design. The BUFGs stay, in parallel, for the logic clocked by clk125
(the PIPE DRP port).
"""

from migen import ClockSignal
from migen.fhdl.specials import Instance


def feed_pclk_mux_from_mmcm(phy):
    """Rewire *phy*'s PIPECLK BUFGCTRL inputs from the clk125/clk250 BUFGs to the MMCM outputs behind them."""
    (mux,) = [s for s in phy._fragment.specials if isinstance(s, Instance) and s.of == "BUFGCTRL"]
    # S7PCIEPHY creates clk125 then clk250 first; check that, so a litepcie change fails here, not in hardware.
    raw = {"I0": (phy.mmcm.clkouts[0], 125e6, "clk125"), "I1": (phy.mmcm.clkouts[1], 250e6, "clk250")}
    for item in mux.items:
        if item.name in raw:
            (clkout, freq, *_), want_freq, domain = raw[item.name]
            assert freq == want_freq, f"MMCM output for {domain} is {freq / 1e6} MHz"
            assert isinstance(item.expr, ClockSignal) and item.expr.cd == domain, (
                f"BUFGCTRL {item.name} is {item.expr!r}, not ClockSignal({domain!r})"
            )
            item.expr = clkout
