# SPI Flash ID Test

LiteX SoC that reads the JEDEC manufacturer and device ID from the
board's SPI Flash. Uses custom firmware (not the default LiteX BIOS) to
read the SPI Flash ID register and report it over UART.

## Boards

| Script | Board | FPGA |
|--------|-------|------|
| `gateware/spiflash_soc_arty.py` | Digilent Arty A7 | XC7A35T |
| `gateware/spiflash_soc_netv2.py` | Kosagi NeTV2 | XC7A35T / XC7A100T |
| `gateware/spiflash_soc_acorn.py` | SQRL Acorn (CLE-215+/215/101) | XC7A200T / XC7A100T |
| `gateware/spiflash_soc_fomu.py` | Fomu EVT | iCE40UP5K |
| `gateware/spiflash_soc_tt.py` | TT FPGA Demo Board | iCE40UP5K |

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
