# UART Echo Test

LiteX SoC with a VexRiscv CPU and UART peripheral. The LiteX BIOS provides
an interactive console over UART, and the host test verifies bidirectional
serial communication by sending data and checking the echo.

## Boards

| Script | Board | FPGA |
|--------|-------|------|
| `gateware/uart_soc_arty.py` | Digilent Arty A7 | XC7A35T |
| `gateware/uart_soc_netv2.py` | Kosagi NeTV2 | XC7A35T / XC7A100T |
| `gateware/uart_soc_acorn.py` | SQRL Acorn (CLE-215+/215/101) | XC7A200T / XC7A100T |
| `gateware/uart_soc_fomu.py` | Fomu EVT | iCE40UP5K |
| `gateware/uart_soc_tt.py` | TT FPGA Demo Board | iCE40UP5K |

## Building

```sh
uv run python designs/uart/gateware/uart_soc_arty.py --toolchain openxc7 --build
```

## Testing

```sh
uv run python designs/uart/host/test_uart.py --port /dev/ttyUSB1
```

## Directory Structure

```
uart/
  gateware/     Board-specific LiteX SoC build scripts
  host/         test_uart.py — host-side UART echo test
```
