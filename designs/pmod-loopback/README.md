# PMOD GPIO Loopback

Pure gateware design (no CPU) that inverts signals between paired GPIO
pins. The host test drives one pin of each pair and reads back the
inverted value on the other, verifying physical connectivity.

## Boards

| Script | Board | FPGA | Pins |
|--------|-------|------|------|
| `gateware/gpio_loopback_arty.py` | Digilent Arty A7 | XC7A35T | PMOD A/B |
| `gateware/gpio_loopback_netv2.py` | Kosagi NeTV2 | XC7A35T | UART header pins |
| `gateware/gpio_loopback_tt.py` | TT FPGA Demo Board | iCE40UP5K | PMOD pins |
| `gateware/gpio_loopback_fomu.py` | Fomu EVT | iCE40UP5K | Touch pads: they reach no pin of the Pi's header, so the test cannot pass on the EVT ([#202](https://github.com/fpgas-online/fpgas.online-test-designs/issues/202)) |
| `gateware/gpio_loopback_acorn.py` | SQRL Acorn | XC7A200T | P2 header |

## Building

```sh
uv run python designs/pmod-loopback/gateware/gpio_loopback_arty.py --toolchain openxc7 --build
```

## Testing

```sh
uv run python designs/pmod-loopback/host/test_pmod_loopback.py --board arty
```

## Directory Structure

```
pmod-loopback/
  gateware/     Board-specific GPIO loopback gateware (no CPU)
  host/         test_pmod_loopback.py — RPi GPIO loopback verification
```
