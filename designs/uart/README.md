# UART Echo Test

A LiteX SoC with a UART console. The host test checks the UART in both directions: it gets the console's
prompt, asks the design what it is, and types every printable byte and reads its echo.

## Boards

| Script | Board | FPGA | Console |
|--------|-------|------|---------|
| `gateware/uart_soc_arty.py` | Digilent Arty A7 | XC7A35T | LiteX BIOS |
| `gateware/uart_soc_netv2.py` | Kosagi NeTV2 | XC7A35T / XC7A100T | LiteX BIOS |
| `gateware/uart_soc_acorn.py` | SQRL Acorn (CLE-215+/215/101) | XC7A200T / XC7A100T | LiteX BIOS |
| `gateware/uart_soc_fomu.py` | Fomu EVT | iCE40UP5K | `designs/_shared/ice40_firmware.py` |
| `gateware/uart_soc_tt.py` | TT FPGA Demo Board | iCE40UP5K | `designs/_shared/ice40_firmware.py` |

The BIOS does not fit an iCE40UP5K's block RAM, so those two designs run a few hundred bytes of firmware
instead. It echoes every byte, and answers a newline with `Ident: <the design's ident>` and the `litex> `
prompt, which is what the BIOS's `ident` command prints.

## Building

```sh
uv run python designs/uart/gateware/uart_soc_arty.py --toolchain openxc7 --build
```

## Testing

```sh
uv run python designs/uart/host/test_uart.py --port /dev/ttyUSB1                 # Arty
uv run python designs/uart/host/test_uart.py --port /dev/ttyAMA0 --board netv2
```

The test does not read what the design printed when it started. It runs:

| Step | Checked |
|------|---------|
| a newline | the `litex> ` prompt comes back: the design receives and sends. A design that only echoes fails |
| `ident` | the design is the UART test design, built for this board |
| echo | each of the 95 printable ASCII bytes, typed one at a time, comes back as itself; the line is ended every 48 bytes and the prompt has to come back |

Its last line is the result for `fpgas-verify`:

```text
RESULT_JSON {"test": "uart", "board": "netv2", "result": "pass", "ident": "...", "commands": ["ident", "echo"],
             "echo_bytes": 95, "echo_errors": 0}
```

A failure adds `"reason"`. A port that cannot be opened, or that fails during the test, is a `fail` with
that `reason`: the line is always printed. `--skip-banner` is accepted and does nothing; there is no banner
check to skip.

## Directory Structure

```
uart/
  gateware/     Board-specific LiteX SoC build scripts
  host/         test_uart.py — asks the design for its ident and checks the echo of every printable byte
```
