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
