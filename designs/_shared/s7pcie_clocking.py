"""Feed litepcie S7PCIEPHY's PIPE clock mux straight from its MMCM, and constrain it, as Xilinx's pipe_clock does.

S7PCIEPHY buffers the MMCM's 125 and 250 MHz outputs with BUFGs and muxes those BUFG outputs through a
BUFGCTRL to make PIPECLK: two global buffers in series, where USERCLK goes through one. The extra buffer's
delay puts the PCIE_2_1 PIPECLK/USERCLK Max Skew check over its limit (0.595 ns against 0.560 ns on the
Acorn CLE-215+ SoC, fast corner). With the BUFGCTRL fed from the MMCM outputs each path has one global
buffer: 0.513 ns on the rebuilt design. The BUFGs stay, in parallel, for the logic clocked by clk125
(the PIPE DRP port).

Both mux inputs' clocks also reach PIPECLK, so Vivado times paths launched at 125 MHz and captured at
250 MHz through it, which cannot happen: only one input drives the output at a time. Xilinx's XDC for its
own pipe_clock names a generated clock per input on the mux output and makes them physically exclusive;
so does this, after link, when the mux cell exists.
"""

from migen import ClockSignal
from migen.fhdl.specials import Instance

MUX_NAME = "pcie_pclk_mux"


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

    mux.name_override = MUX_NAME
    phy.platform.toolchain.pre_placement_commands += [
        f"create_generated_clock -name pcie_pclk_125 -source [get_pins {MUX_NAME}/I0] -divide_by 1"
        f" [get_pins {MUX_NAME}/O]",
        f"create_generated_clock -name pcie_pclk_250 -source [get_pins {MUX_NAME}/I1] -divide_by 1"
        f" -add -master_clock [get_clocks -of_objects [get_pins {MUX_NAME}/I1]] [get_pins {MUX_NAME}/O]",
        f"set_clock_groups -name {MUX_NAME} -physically_exclusive -group pcie_pclk_125 -group pcie_pclk_250",
    ]
