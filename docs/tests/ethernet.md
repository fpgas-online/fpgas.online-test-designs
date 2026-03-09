# Ethernet Test

## Purpose

Verify Ethernet connectivity between the FPGA and the network. This test reads the MAC address, confirms ARP responses, and validates ICMP ping — establishing that the FPGA's Ethernet MAC and PHY are functional and the board can participate on the network.

## Target Boards

| Board | PHY Chip | Interface | Speed | Status |
|-------|----------|-----------|-------|--------|
| [Digilent Arty A7](../hardware/arty-a7.md) | TI DP83848J | MII (4-bit) | 100 Mbps | Active |
| [Kosagi NeTV2](../hardware/netv2.md) (RPi5) | RMII PHY | RMII (2-bit) | 100 Mbps | Active |
| [GSG ButterStick](../hardware/butterstick.md) | TBD | RGMII | 1000 Mbps | Planned |

### NeTV2 Network Independence

The NeTV2's FPGA Ethernet interface is independent of the Raspberry Pi's own Ethernet. The FPGA has its own RMII PHY with a separate RJ45 jack (or connection to a switch). The RPi communicates with the FPGA's Ethernet over the local network, not through an internal bus.

- RMII reference clock pin: D17
- RMII data bus: 2-bit

This means testing requires either:
- A separate Ethernet cable from the FPGA to the same switch/network as the RPi, or
- A direct Ethernet cable between the RPi and FPGA (requires static IP configuration on both ends)

## Prerequisites

- FPGA programmed with Ethernet test bitstream (LiteX SoC with LiteEth)
- Ethernet cable connected to the FPGA board's RJ45 jack
- Network connectivity between host and FPGA (same subnet)
- UART connection available for MAC address and status reporting

## How It Works

### Step 1: FPGA Design with LiteEth

The FPGA is loaded with a LiteX SoC that includes the LiteEth core, providing:

- Ethernet MAC (Media Access Controller)
- PHY interface matching the board's hardware (MII, RMII, or RGMII)
- IP/UDP/ARP stack (built into LiteX BIOS)

Source: [LiteEth library](https://github.com/enjoy-digital/liteeth)

### Step 2: Boot and MAC Address Report

1. On boot, the LiteX BIOS firmware initializes the Ethernet PHY.
2. The firmware reads and prints the MAC address over UART.
3. The host script reads the UART output and records the MAC address.

### Step 3: ARP Test

1. The host sends an ARP request for the FPGA's configured IP address.
2. The FPGA's LiteX BIOS ARP handler responds with its MAC address.
3. The host verifies the ARP response is received.

### Step 4: ICMP Ping Test

1. The host pings the FPGA's IP address.
2. The FPGA's LiteX BIOS responds to ICMP echo requests.
3. The host verifies ping responses are received with acceptable latency.

### Step 5: TFTP Transfer Test (Optional)

1. The host sets up a TFTP server (or the FPGA attempts a TFTP boot).
2. A known data file is transferred via TFTP.
3. Data integrity is verified by comparing checksums.

This step tests sustained data transfer and catches intermittent PHY/MAC issues.

## Pass/Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| MAC address | Readable, matches expected format | Not readable or garbled |
| ARP response | FPGA responds to ARP requests | No ARP response |
| ICMP ping | Ping succeeds with <100ms latency | No ping response or excessive loss |
| TFTP transfer (optional) | Data transferred with correct checksum | Checksum mismatch or transfer failure |

## LiteX Ethernet Configuration

### Build Flags

| Flag | Purpose |
|------|---------|
| `--with-ethernet` | Adds Ethernet with CPU access (for BIOS networking) |
| `--with-etherbone` | Adds Ethernet-to-Wishbone bridge (for host-side register access) |

### Default Network Configuration

| Parameter | Default Value |
|-----------|---------------|
| FPGA IP address | `192.168.1.50` (LiteX BIOS default) |
| Host IP address | `192.168.1.100` (expected TFTP server) |
| MAC address prefix | `0x10e2d5xxxxxx` (LiteX default range) |
| Subnet mask | `255.255.255.0` |

The MAC address is configurable at build time via the `--eth-ip` and `--remote-ip` LiteX build flags.

Source: [LiteX BIOS networking](https://github.com/enjoy-digital/litex/blob/master/litex/soc/software/bios/net.c)

### LiteEth Architecture

```
┌──────────────┐
│   LiteX CPU  │
│   (BIOS)     │
│      │       │
│   Wishbone   │
│      │       │
│  ┌───┴────┐  │
│  │ LiteEth│  │
│  │  MAC   │  │
│  └───┬────┘  │
│      │       │
│  ┌───┴────┐  │
│  │  PHY   │  │
│  │ (MII/  │  │
│  │ RMII/  │  │
│  │ RGMII) │  │
│  └───┬────┘  │
└──────┼───────┘
       │
   ┌───┴───┐
   │  RJ45 │
   └───────┘
```

## Board-Specific Details

### Arty A7 — MII Interface

| Parameter | Value |
|-----------|-------|
| PHY chip | TI DP83848J |
| Interface | MII (Media Independent Interface) |
| Data width | 4-bit TX, 4-bit RX |
| Speed | 10/100 Mbps |
| PHY address | Board-dependent (typically 0 or 1) |
| Reference | [DP83848J datasheet](https://www.ti.com/product/DP83848J) |

Source: [Arty A7 Reference Manual](https://digilent.com/reference/programmable-logic/arty-a7/reference-manual)

### NeTV2 — RMII Interface

| Parameter | Value |
|-----------|-------|
| Interface | RMII (Reduced MII) |
| Data width | 2-bit TX, 2-bit RX |
| Reference clock pin | D17 |
| Speed | 100 Mbps |
| Network | Independent of RPi Ethernet — requires separate cable/switch |

Source: [NeTV2 FPGA repository](https://github.com/AlphamaxMedia/netv2-fpga)

### ButterStick — RGMII Interface (Planned)

| Parameter | Value |
|-----------|-------|
| Interface | RGMII (Reduced Gigabit MII) |
| Speed | 10/100/1000 Mbps |
| Status | Planned |

## Host-Side Test Commands

```bash
# Read MAC address from UART output
# (parsed from LiteX BIOS boot log)

# ARP test
arping -c 3 192.168.1.50

# ICMP ping test
ping -c 5 -W 2 192.168.1.50

# TFTP transfer test (optional)
# Start TFTP server on host, then trigger FPGA netboot via UART
```

## References

- [LiteEth library](https://github.com/enjoy-digital/liteeth) — Ethernet MAC/PHY for LiteX
- [LiteX SoC builder](https://github.com/enjoy-digital/litex)
- [LiteX BIOS networking source](https://github.com/enjoy-digital/litex/blob/master/litex/soc/software/bios/net.c)
- [TI DP83848J datasheet](https://www.ti.com/product/DP83848J)
- [NeTV2 FPGA repository](https://github.com/AlphamaxMedia/netv2-fpga)
- [Arty A7 Reference Manual](https://digilent.com/reference/programmable-logic/arty-a7/reference-manual)
