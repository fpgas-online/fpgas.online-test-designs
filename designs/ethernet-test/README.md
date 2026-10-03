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
sudo python3 designs/ethernet-test/host/test_ethernet.py --board arty --uart-port /dev/ttyUSB1   # needs root
```

The test does not read what the BIOS printed while it booted. It runs:

| Step | Checked |
|------|---------|
| the UART | a newline brings the BIOS prompt back, and `ident` is `fpgas-online Ethernet Test SoC -- <board>` |
| ARP | `arping 192.168.1.50` on the Pi's free USB Ethernet adapter is answered, by the BIOS's MAC `10:e2:d5:00:00:00` |
| ping | at least 2 of 10 pings are answered (the BIOS takes one packet at a time) |

The designs build litex_boards' SoC, whose own ident (`LiteX SoC on Arty A7`) does not say which design it
is, so they replace it with the design's.

Its last line is the result for `fpgas-verify`:

```text
RESULT_JSON {"test": "ethernet", "board": "arty", "result": "pass", "ident": "...", "interface": "eth1",
             "arp": true, "mac": "10:e2:d5:00:00:00", "ping_sent": 10, "ping_received": 6, "rtt_avg_ms": 0.501}
```

## Directory Structure

```
ethernet-test/
  gateware/     Board-specific LiteX SoC build scripts
  host/         test_ethernet.py — host-side link and ping verification
```
