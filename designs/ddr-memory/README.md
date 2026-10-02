# DDR3 Memory Test

LiteX SoC with DDR3 SDRAM controller. The LiteX BIOS performs PHY
calibration on boot and provides `sdram_init`, `sdram_test`, `mem_test`
and `mem_speed` commands for verifying memory integrity and bandwidth.

## Boards

| Script | Board | FPGA | DDR3 |
|--------|-------|------|------|
| `gateware/ddr_soc_arty.py` | Digilent Arty A7 | XC7A35T | MT41K128M16, 256 MiB |
| `gateware/ddr_soc_netv2.py` | Kosagi NeTV2 | XC7A35T / XC7A100T | 2 × K4B2G1646F, 512 MiB |
| `gateware/ddr_soc_acorn.py` | SQRL Acorn (CLE-215+/215/101) | XC7A200T / XC7A100T | MT41K512M16, 1 GiB (CLE-215+/215); MT41K256M16, 512 MiB (CLE-101) |

The module decides how many address bits the SoC drives, so it has to be the board's: one with a row
bit the board does not route gives a `MAIN_RAM` twice the real size, whose top half is the bottom half
again. The host test checks for that.

Boards without DDR3 (Fomu, TT FPGA) are not supported by this design.

## Building

```sh
uv run python designs/ddr-memory/gateware/ddr_soc_arty.py --toolchain openxc7 --build
```

### openXC7 builds

The openXC7 flow (yosys + nextpnr-xilinx) needs three things the Vivado flow does not:

- **Clock periods and strict timing.** LiteX constrains only the board's input clock
  for nextpnr-xilinx, and lets a build that misses timing through. The targets constrain
  every PLL output (`constrain_openxc7_clocks` in `designs/_shared/platform_fixups.py`), so
  a build that misses timing fails, after retrying place-and-route with up to five seeds.
- **Slower system clocks.** The system clock is 75 MHz on the Arty (DDR3 at 600 MT/s),
  80 MHz on the Acorn (640 MT/s) and 50 MHz on the NeTV2 (400 MT/s). nextpnr-xilinx
  cannot place the SoC at 100 MHz. Vivado builds keep 100 MHz on the Arty and the Acorn.
- **IO fixes.** nextpnr-xilinx does not know SSTL15_R, which is the NeTV2's DDR3 IO
  standard: a design that asks for it gets data pins with no input buffer. It also gives every SSTL
  bank VREF 0.675 V. The NeTV2 target asks for SSTL15 instead. `designs/_shared/fasm_io_fixups.py`
  then sets VREF 0.75 V (NeTV2, Acorn) and SSTL15_R's reduced drive (NeTV2) in the FASM, so the
  DDR3 pins match what Vivado builds.

## Testing

```sh
uv run python designs/ddr-memory/host/test_ddr.py --port /dev/ttyUSB1                # Arty
uv run python designs/ddr-memory/host/test_ddr.py --port /dev/ttyAMA0 --board netv2
```

The test does not read the BIOS's boot output. It finds the BIOS prompt, checks `ident` is this design
for the board, then runs:

| Command | Checked |
|---------|---------|
| `mem_list` | the design's `MAIN_RAM` is the size of the board's DRAM (256 MiB on the Arty, 512 MiB on the NeTV2, 512 MiB or 1 GiB on the Acorn) |
| `sdram_init` | read leveling reports each of the board's byte lanes, with a window on every one; the BIOS's 2 MiB memtest passes; write and read speed are reported |
| `sdram_test` | a memtest passes, over at least 1/32 of the DRAM (8 MiB on the Arty, 16 MiB on the NeTV2) |
| `mem_write`, `flush_l2_cache`, `mem_read` | the address test: a different word at the DRAM's base and at every address bit from 4 bytes to half its size, read back from the DRAM after the cache is flushed. Two addresses that are one cell (half the memory missing, a broken address line) fail it; a memtest over a small range does not notice them |

Its last line is the result for `fpgas-verify`:

```text
RESULT_JSON {"test": "ddr", "board": "netv2", "result": "pass", "ident": "...", "commands": [...],
             "main_ram_base": 1073741824, "main_ram_bytes": 536870912, "leveling": {"m0": "b01 14+-14", ...},
             "bytes_tested": 16777216, "errors": 0, "address_bits_tested": 27,
             "write_mib_per_s": 27.2, "read_mib_per_s": 30.9}
```

A failure adds `"reason"`; `leveling` has `null` for a lane with no window, and `errors` is the worst
memtest's bus, address and data errors together. A port that cannot be opened, or that fails during the
test, is a `fail` with that `reason`: the line is always printed. The speeds are the BIOS's, in MiB/s over 2 MiB.

## Directory Structure

```
ddr-memory/
  gateware/     Board-specific LiteX SoC build scripts
  host/         test_ddr.py — asks the BIOS to calibrate and test the DDR3, and judges that run
```
