# PMOD Pin Identification

Pure gateware design (no CPU) that continuously transmits a pin
identification string over UART on each GPIO pin. Used to verify which
physical pin corresponds to which FPGA I/O by reading the serial output
with a logic analyser or UART adapter.

## Boards

| Script | Board | FPGA |
|--------|-------|------|
| `gateware/pmod_pin_id_arty.py` | Digilent Arty A7 | XC7A35T |
| `gateware/pmod_pin_id_fomu.py` | Fomu EVT | iCE40UP5K |
| `gateware/pmod_pin_id_tt.py` | TT FPGA Demo Board | iCE40UP5K |
| `gateware/pmod_pin_id_acorn.py` | SQRL Acorn | XC7A200T |
| `gateware/pmod_pin_id_netv2.py` | Kosagi NeTV2 | XC7A35T |

## Building

```sh
uv run python designs/pmod-pin-id/gateware/pmod_pin_id_arty.py --toolchain openxc7 --build
```

## Testing

```sh
uv run python designs/pmod-pin-id/host/identify_pmod_pins.py --board arty
```

## Key Files

- `gateware/pmod_pin_id.py` — Shared pin identification gateware module

## Directory Structure

```
pmod-pin-id/
  gateware/
    pmod_pin_id.py          Shared pin ID gateware module
    pmod_pin_id_arty.py     Board-specific build scripts
    ...
  host/
    identify_pmod_pins.py   Host-side pin identification reader
```
