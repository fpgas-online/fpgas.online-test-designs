# SPI Flash ID Test

LiteX SoC that reads the JEDEC manufacturer and device ID from the
board's SPI Flash. Uses custom firmware (not the default LiteX BIOS) to
read the SPI Flash ID register and report it over UART.

## Boards

| Script | Board | FPGA | System clock |
|--------|-------|------|--------------|
| `gateware/spiflash_soc_arty.py` | Digilent Arty A7 | XC7A35T | 75 MHz with openXC7, 100 MHz with Vivado |
| `gateware/spiflash_soc_netv2.py` | Kosagi NeTV2 | XC7A35T / XC7A100T | 50 MHz |
| `gateware/spiflash_soc_acorn.py` | SQRL Acorn (CLE-215+/215/101) | XC7A200T / XC7A100T | 75 MHz with openXC7, 100 MHz with Vivado |
| `gateware/spiflash_soc_fomu.py` | Fomu EVT | iCE40UP5K | 12 MHz |
| `gateware/spiflash_soc_tt.py` | TT FPGA Demo Board | iCE40UP5K | 12 MHz |

nextpnr-xilinx cannot place the Arty and Acorn SoCs at 100 MHz on most seeds, so openXC7 builds run
them at 75 MHz. Nothing in the test depends on the clock: the UART divisor follows it, and the
firmware drives the flash's clock by hand, so it only runs slower.

## Building

```sh
uv run python designs/spi-flash-id/gateware/spiflash_soc_arty.py --toolchain openxc7 --build
```

## Testing

```sh
uv run python designs/spi-flash-id/host/test_spiflash.py --port /dev/ttyUSB1
```

## Key Files

- `gateware/common.py` — Shared SPI Flash SoC configuration (CSR named `spi_id`)

## Directory Structure

```
spi-flash-id/
  gateware/     Board-specific SoC scripts + common.py shared config
  host/         test_spiflash.py — host-side JEDEC ID verification
```
