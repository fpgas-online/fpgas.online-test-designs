# PCIe Enumeration Test

## Purpose

Verify that the PCIe link between the NeTV2 FPGA and the Raspberry Pi 5 trains successfully, and that the FPGA's PCIe endpoint is properly enumerated by the host operating system. This test confirms the PCIe hard IP block, physical link, and Linux kernel enumeration are all working.

## Target Boards

| Board | PCIe Generation | Lane Width | Host | Status |
|-------|----------------|------------|------|--------|
| [Kosagi NeTV2](../hardware/netv2.md) | Gen2 | x1 | RPi5 only | Active |

### Why RPi5 Only

- **RPi3:** No accessible PCIe interface.
- **RPi4:** Has PCIe internally (used for the USB3 controller VL805) but it is not exposed for user devices.
- **RPi5:** Exposes PCIe Gen2 x1 via an FPC (Flat Printed Circuit) connector, which connects to the NeTV2's PCIe edge connector via an adapter.

Source: [Raspberry Pi 5 PCIe documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi-5.html)

## Prerequisites

- NeTV2 board connected to RPi5 via PCIe FPC adapter
- FPGA programmed with PCIe endpoint test bitstream (LiteX SoC with LitePCIe)
- RPi5 running a Linux kernel with PCIe support enabled
- Root access on RPi5 (required for `lspci`, `setpci`, and PCIe rescan)

## How It Works

### Step 1: FPGA Design with LitePCIe

The FPGA is loaded with a LiteX SoC that includes a LitePCIe endpoint:

- Uses the Xilinx 7-Series integrated hard PCIe block (no soft logic required for the PHY)
- Configured as a PCIe endpoint with vendor/device ID `10ee:7011` (Xilinx 7-Series default)
- Includes BARs (Base Address Registers) for host access to FPGA resources

Source: [LitePCIe library](https://github.com/enjoy-digital/litepcie)

### Step 2: PCIe Bus Rescan

After programming the FPGA (which resets the PCIe endpoint), the host must rescan the PCIe bus to detect the new device:

```bash
echo 1 | sudo tee /sys/bus/pci/rescan
```

This triggers Linux to re-enumerate all PCIe devices.

### Step 3: Device Detection

The host checks for the FPGA device using `lspci`:

```bash
sudo lspci -vvv -d 10ee:7011
```

Expected output includes:
- Device identified as a Xilinx Corporation device
- Link capabilities and status (speed, width)
- BAR allocation details
- Power management state

### Step 4: Link Verification

The host verifies PCIe link training parameters:

```bash
# Check link status register
sudo lspci -vvv -d 10ee:7011 | grep -E "LnkCap|LnkSta"
```

Expected values:
- **Link Capability:** Speed 5GT/s (Gen2), Width x1
- **Link Status:** Speed 2.5GT/s or 5GT/s (Gen1 or Gen2), Width x1

### Step 5: BAR Verification

Confirm that at least one BAR is allocated (non-zero address):

```bash
sudo lspci -vvv -d 10ee:7011 | grep "Region"
```

## Pass/Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| Device detection | `10ee:7011` appears in `lspci` output | Device not found |
| Link training | Link Status shows active link (Speed and Width non-zero) | Link down or not trained |
| Link speed | 2.5 GT/s (Gen1) or 5 GT/s (Gen2) | No link speed reported |
| Link width | x1 | Width x0 or not reported |
| BAR allocation | At least one BAR has a non-zero address | No BARs allocated |

## Host-Side Commands

### Full Test Sequence

```bash
# 1. Rescan PCIe bus after FPGA programming
echo 1 | sudo tee /sys/bus/pci/rescan

# 2. Check device presence
sudo lspci -d 10ee:7011
# Expected: XX:XX.X Communication controller: Xilinx Corporation Device 7011

# 3. Detailed device info
sudo lspci -vvv -d 10ee:7011

# 4. Verify config space (optional)
# Get Bus:Device.Function from lspci output, then:
sudo setpci -s <BDF> VENDOR_ID.w   # Should return 10ee
sudo setpci -s <BDF> DEVICE_ID.w   # Should return 7011
sudo setpci -s <BDF> COMMAND.w     # Check command register

# 5. Check link status via sysfs (alternative)
cat /sys/bus/pci/devices/0000:<BDF>/current_link_speed
cat /sys/bus/pci/devices/0000:<BDF>/current_link_width
```

### Expected Vendor/Device ID

| Field | Value | Meaning |
|-------|-------|---------|
| Vendor ID | `10ee` | Xilinx Corporation |
| Device ID | `7011` | 7-Series PCIe endpoint (LitePCIe default) |

## LiteX PCIe Details

### LitePCIe Architecture

```
┌─────────────────────────────┐
│         LiteX SoC           │
│                             │
│  ┌───────────┐              │
│  │ LitePCIe  │              │
│  │ Endpoint  │              │
│  │           │              │
│  │ ┌───────┐ │  ┌────────┐  │
│  │ │ MSI   │ │  │Wishbone│  │
│  │ │       │ │  │ Bridge │  │
│  │ └───────┘ │  └────────┘  │
│  │ ┌───────┐ │              │
│  │ │ DMA   │ │              │
│  │ │ S-G   │ │              │
│  │ └───────┘ │              │
│  └─────┬─────┘              │
│        │                    │
│  ┌─────┴─────┐              │
│  │ 7-Series  │              │
│  │ Hard IP   │              │
│  │ PCIe PHY  │              │
│  └─────┬─────┘              │
└────────┼────────────────────┘
         │ PCIe x1
    ┌────┴────┐
    │  FPC    │
    │ to RPi5 │
    └─────────┘
```

### Configuration

| Parameter | Value |
|-----------|-------|
| PHY | Xilinx 7-Series integrated hard IP block |
| Max lanes | x1 (NeTV2), configurable up to x4 in LitePCIe |
| Max speed | Gen2 (5 GT/s) |
| BAR size | Configurable (default varies by design) |
| DMA | Scatter-gather DMA engine (optional) |
| Interrupts | MSI (Message Signaled Interrupts) |

Source: [LitePCIe library](https://github.com/enjoy-digital/litepcie)

### Linux Driver

LitePCIe includes a Linux kernel module that provides:

- Character device interface (`/dev/litepcie*`)
- MMAP access to FPGA BARs
- Scatter-gather DMA for high-throughput data transfer
- Interrupt handling via MSI

For this enumeration test, the kernel module is not required — the test only checks that Linux's built-in PCIe enumeration detects the device.

Source: [LitePCIe Linux driver](https://github.com/enjoy-digital/litepcie/tree/master/software/kernel)

## NeTV2 PCIe "Hax" Pins

The NeTV2 repurposes unused PCIe connector pins for additional interfaces. These auxiliary signals share the physical PCIe connector but are not part of the PCIe protocol:

| Signal | Purpose | Notes |
|--------|---------|-------|
| JTAG | FPGA programming | Directly from RPi GPIO |
| UART | Serial console | TX/RX for LiteX BIOS |
| SPI | Flash programming | For bitstream storage |
| I2C | Auxiliary communication | Board management |

These "hax" pins allow the RPi to program and communicate with the FPGA through the same physical connector that carries PCIe, simplifying the hardware design.

Source: [NeTV2 FPGA repository](https://github.com/AlphamaxMedia/netv2-fpga)

## References

- [LitePCIe library](https://github.com/enjoy-digital/litepcie)
- [LitePCIe Linux driver](https://github.com/enjoy-digital/litepcie/tree/master/software/kernel)
- [NeTV2 FPGA repository](https://github.com/AlphamaxMedia/netv2-fpga)
- [Raspberry Pi 5 PCIe documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi-5.html)
- [PCI Express specification (overview)](https://pcisig.com/specifications)
- [Xilinx 7-Series Integrated Block for PCIe (PG054)](https://docs.amd.com/r/en-US/pg054-7series-pcie)
