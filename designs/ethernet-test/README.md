# Ethernet Test

LiteX SoC with LiteEth MAC/PHY for Ethernet connectivity testing. The
LiteX BIOS provides DHCP and ping, and the host test verifies link status
and network reachability.

## Boards

| Script | Board | FPGA | PHY Interface |
|--------|-------|------|---------------|
| `gateware/ethernet_soc_arty.py` | Digilent Arty A7 | XC7A35T | MII |
| `gateware/ethernet_soc_netv2.py` | Kosagi NeTV2 | XC7A35T / XC7A100T | RMII |

Boards without Ethernet PHY (Fomu, TT FPGA, Acorn) are not supported.

## Building

```sh
uv run python designs/ethernet-test/gateware/ethernet_soc_arty.py --toolchain openxc7 --build
```

## Testing

```sh
uv run python designs/ethernet-test/host/test_ethernet.py --port /dev/ttyUSB1
```

## Directory Structure

```
ethernet-test/
  gateware/     Board-specific LiteX SoC build scripts
  host/         test_ethernet.py — host-side link and ping verification
```
