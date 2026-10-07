# TT display pattern

A moving pattern for the seven-segment display of the TinyTapeout FPGA Demo Board. It is not a test: nothing
reads it. The boot check (`fpgas-verify`) streams it into the FPGA as its last step, so the board looks alive on
its camera until a visitor loads a design
([#139](https://github.com/fpgas-online/fpgas.online-test-designs/issues/139)).

| | |
|---|---|
| Board | TT FPGA Demo Board (iCE40UP5K) |
| Clock | the iCE40's own low-frequency oscillator (`SB_LFOSC`, 10 kHz nominal) |
| Pins driven | `uo_out[7:0]` only: bits 0 to 6 are segments a to g, bit 7 is the dot |
| Pins held as inputs | `ui_in`, `uio`: never driven, never read, with the iCE40's pull-up off, so the check can read the DIP switches on `ui_in` under this design (#166) |
| Pins ignored | `clk`, `rst_n` |
| Pattern | one segment runs round the outer ring (a to f), an eighth of a second a step; the middle segment changes at each lap; the dot is lit for the first half of each second |

It needs nothing from the demo board's microcontroller once it is loaded: no clock, no reset, no input.
(Whether a reset of the microcontroller leaves the FPGA configured is the board's, and had not been tried when
this was written.) It is replaced when the board's own SDK next starts (the SDK loads its default project then)
or when a visitor loads a design.

## Build

```sh
uv sync --extra build
uv run python designs/tt-display/gateware/tt_display.py --build
```

The bitstream is `designs/tt-display/build/tt-fpga-yosys-nextpnr/gateware/tt_fpga_platform.bin`. CI builds it
(`.github/workflows/tt-display-build.yml`, artifact `tt-display-tt-fpga`) and it ships in
`fpgas-online-tt-fpga-bitstreams`.

## Test

```sh
uv run --extra build --with pytest pytest tests/test_tt_display.py
```

A simulation of the pattern, and a check that the design asks the platform for `uo_out` and nothing else.

## By hand

```sh
sudo fpgas-tt-fpga-debug list     # shows the file, marked "left running"
python3 /usr/lib/python3/dist-packages/fpgas_online_verify/scripts/tt_fpga_program.py /dev/ttyACM0 \
    /usr/share/fpgas-online/tt-fpga/bitstreams/tt-display-tt-fpga/tt_fpga_platform.bin --gpio-release
```

with `fpgas-tt.service` stopped, as for any load by hand.
