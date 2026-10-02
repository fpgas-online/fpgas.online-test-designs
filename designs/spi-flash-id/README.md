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
uv run python designs/spi-flash-id/host/test_spiflash.py --port /dev/ttyUSB1                 # Arty
uv run python designs/spi-flash-id/host/test_spiflash.py --port /dev/ttyAMA0 --board netv2
```

The firmware (`designs/_shared/ice40_firmware.py`, on every board) reads the ID when the design starts,
prints it and the `litex> ` prompt, then waits. A newline on the UART makes it read the flash again. The
test does not use the reading printed at start. It runs:

| Step | Checked |
|------|---------|
| a newline | the `litex> ` prompt comes back: the firmware is there and answers |
| a newline, twice | each makes the firmware send `0x9F` to the flash again. The ident is the SPI flash test design for this board; the ID is not `000000` or `ffffff`; the firmware's verdict is PASS; both readings agree; the ID is the board's known one (the Fomu's `1f8601`) or the `--expected-jedec` given |

Its last line is the result for `fpgas-verify`:

```text
RESULT_JSON {"test": "spiflash", "board": "netv2", "result": "pass", "ident": "...", "commands": ["read", "read"],
             "rdid": "ef4018", "manufacturer": "Winbond", "capacity_bytes": 16777216}
```

A failure adds `"reason"`. `capacity_bytes` is given only where the ID's third byte is the size's log2. A
port that cannot be opened, or that fails during the test, is a `fail` with that `reason`: the line is
always printed. The script can be started before or after the design is loaded: `--timeout` is how long it
waits for the prompt.

## Key Files

- `gateware/common.py` — Shared SPI Flash SoC configuration (CSR named `spi_id`)

## Directory Structure

```
spi-flash-id/
  gateware/     Board-specific SoC scripts + common.py shared config
  host/         test_spiflash.py — host-side JEDEC ID verification
```
