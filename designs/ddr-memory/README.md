# DDR3 Memory Test

LiteX SoC with DDR3 SDRAM controller. The LiteX BIOS performs PHY
calibration on boot and provides `memtest` and `memspeed` commands for
verifying memory integrity and bandwidth.

## Boards

| Script | Board | FPGA | DDR3 |
|--------|-------|------|------|
| `gateware/ddr_soc_arty.py` | Digilent Arty A7 | XC7A35T | MT41K128M16 |
| `gateware/ddr_soc_netv2.py` | Kosagi NeTV2 | XC7A35T / XC7A100T | MT41K256M16 |
| `gateware/ddr_soc_acorn.py` | SQRL Acorn (CLE-215+/215/101) | XC7A200T / XC7A100T | MT41K512M16 |

Boards without DDR3 (Fomu, TT FPGA) are not supported by this design.

## Building

```sh
uv run python designs/ddr-memory/gateware/ddr_soc_arty.py --toolchain openxc7 --build
```

### openXC7 builds

The openXC7 flow (yosys + nextpnr-xilinx) needs three things the Vivado flow does not
(fpgas-online/fpgas.online-test-designs#50):

- **Clock periods and strict timing.** LiteX constrains only the board's input clock
  for nextpnr-xilinx, and lets a build that misses timing through. The targets constrain
  every PLL output (`constrain_openxc7_clocks` in `designs/_shared/platform_fixups.py`), so
  a build that misses timing fails, after retrying place-and-route with up to five seeds.
- **Slower system clocks.** The system clock is 75 MHz on the Arty (DDR3 at 600 MT/s),
  80 MHz on the Acorn (640 MT/s) and 50 MHz on the NeTV2 (400 MT/s). nextpnr-xilinx
  cannot place the SoC at 100 MHz. Vivado builds keep 100 MHz on the Arty and the Acorn.
- **IO fixes.** nextpnr-xilinx does not know SSTL15_R, which is the NeTV2's DDR3 IO
  standard: it built the data pins with no input buffer at all. It also gives every SSTL
  bank VREF 0.675 V. The NeTV2 target asks for SSTL15 instead. `designs/_shared/fasm_io_fixups.py`
  then sets VREF 0.75 V (NeTV2, Acorn) and SSTL15_R's reduced drive (NeTV2) in the FASM, so the
  DDR3 pins match what Vivado builds.

## Testing

```sh
uv run python designs/ddr-memory/host/test_ddr.py --port /dev/ttyUSB1
```

## Directory Structure

```
ddr-memory/
  gateware/     Board-specific LiteX SoC build scripts
  host/         test_ddr.py — host-side DDR3 memtest verification
```
