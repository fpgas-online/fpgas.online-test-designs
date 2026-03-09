# Infrastructure Overview

This document describes the physical host machines, FPGA boards, programming methods, and communication interfaces used in the fpgas.online test infrastructure.

## Host Machines

### tweed.welland.mithis.com

| Property | Value |
|----------|-------|
| Role | Primary FPGA test host |
| Connected boards | Arty A7, Fomu EVT, TT FPGA |
| Access | SSH (exact connectivity TBD) |
| Status | Could not reach during exploration -- details pending |

**Note:** This host was unreachable during the initial infrastructure exploration. The exact OS version, kernel, and USB/serial device topology remain to be documented once SSH access is confirmed.

### rpi5-netv2.iot.welland.mithis.com

| Property | Value |
|----------|-------|
| Hardware | Raspberry Pi 5 Model B Rev 1.0 |
| OS | Debian 13 (Trixie) |
| Kernel | 6.12.47+rpt-rpi-2712 aarch64 |
| Connected board | NeTV2 (bare developer board) |
| Connections to FPGA | GPIO (JTAG + UART) + PCIe Gen2 x1 |
| Network adapter | USB ASIX AX88179 Gigabit Ethernet |
| Software | OpenOCD installed for JTAG programming |
| Access | SSH |

The RPi5 host connects to a bare (unpackaged) NeTV2 developer board. Both GPIO-based JTAG/UART and PCIe are available. The PCIe connection uses Gen2 x1 speeds through the RPi5's PCIe connector.

### rpi3-netv2.iot.welland.mithis.com

| Property | Value |
|----------|-------|
| Hardware | Raspberry Pi 3 |
| Connected board | NeTV2 (stock packaged device, as shipped by bunnie) |
| Connections to FPGA | GPIO only (JTAG + UART) |
| PCIe | Not available (RPi3 has no PCIe) |
| Access | SSH |

The RPi3 host connects to a stock NeTV2 as originally shipped by bunnie/Alphamax via Crowd Supply. Only GPIO-based JTAG and UART are available; there is no PCIe connection.

## Programming Methods

### OpenOCD (GPIO Bitbang JTAG)

Used for: **NeTV2** (both RPi3 and RPi5 hosts)

OpenOCD drives JTAG signals through the Raspberry Pi GPIO header using the `bcm2835gpio` interface. The configuration file `alphamax-rpi.cfg` defines the GPIO-to-JTAG mapping:

- TCK = GPIO4 (RPi header pin 7)
- TMS = GPIO17 (RPi header pin 11)
- TDI = GPIO27 (RPi header pin 13)
- TDO = GPIO22 (RPi header pin 15)
- SRST = GPIO24 (RPi header pin 18)

Two programming modes are supported:

1. **Direct bitstream load** (volatile, lost on power cycle):
   ```
   openocd -f alphamax-rpi.cfg -c "pld load 0 top.bit; exit"
   ```

2. **SPI Flash via BSCAN_SPI** (persistent):
   ```
   openocd -f alphamax-rpi.cfg -c "init; jtagspi_init 0 bscan_spi_xc7a35t.bit; jtagspi_program top.bin 0x0; exit"
   ```

Source: [alphamax-rpi.cfg](https://github.com/alphamaxmedia/netv2mvp-scripts/blob/master/alphamax-rpi.cfg)

### openFPGALoader

Used for: **Arty A7** (via FTDI FT2232HQ USB), **NeTV2** (alternative to OpenOCD)

openFPGALoader supports direct bitstream loading and SPI flash programming over USB-JTAG or other interfaces.

```
openFPGALoader -b arty --write-flash design.bit
```

### USB DFU (dfu-util)

Used for: **Fomu EVT**

The Fomu connects directly via USB and is programmed using the DFU (Device Firmware Upgrade) protocol:

```
dfu-util -D design.dfu
```

Source: [workshop.fomu.im](https://workshop.fomu.im)

### IceStorm Programmer (iceprog)

Used for: **Fomu EVT**, **TT FPGA** (iCE40 devices)

The IceStorm toolchain includes `iceprog` for programming iCE40 SPI flash:

```
iceprog design.bin
```

## Communication Interfaces

### USB-UART

Used for: **Arty A7**

The Arty A7 has an FTDI FT2232HQ providing both JTAG and UART over a single USB connection. The UART appears as `/dev/ttyUSB*` on the host. FPGA pins: TX=D10, RX=A9.

Source: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)

### GPIO UART

Used for: **NeTV2** (primary serial)

UART signals are routed from the FPGA to the Raspberry Pi GPIO header:

| Signal | FPGA Pin | RPi GPIO | RPi Header Pin |
|--------|----------|----------|----------------|
| FPGA TX | E14 | GPIO15 (RXD) | Pin 10 |
| FPGA RX | E13 | GPIO14 (TXD) | Pin 8 |

The RPi's `/dev/ttyAMA0` or `/dev/serial0` connects to the FPGA's serial port. Note the crossover: the FPGA's TX connects to the RPi's RX and vice versa.

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

### Secondary UART via PCIe "hax" Pins

Used for: **NeTV2** (RPi5 only, via PCIe connector spare pins)

| Signal | FPGA Pin | PCIe Hax Pin |
|--------|----------|-------------|
| TX | B17 | hax7 |
| RX | A18 | hax8 |

These auxiliary pins on the PCIe connector provide a second serial channel independent of GPIO.

### PCIe

Used for: **NeTV2** (RPi5 only)

The NeTV2 supports PCIe x1/x2/x4. On the RPi5, it connects as PCIe Gen2 x1. The FPGA appears on the PCI bus with vendor ID `10ee` (Xilinx) and device ID `7011`.

```
lspci  # shows Xilinx device 10ee:7011
```

### USB (Native)

Used for: **Fomu EVT** (ValentyUSB), **TT FPGA** (via RP2040)

The Fomu uses a native USB core (ValentyUSB) directly on the iCE40 FPGA. The TT FPGA Demo Board communicates through an RP2040 microcontroller with USB-C.

### PMOD HAT

Used for: **Arty A7** (connected to RPi via Digilent PMOD HAT adapter)

The PMOD HAT provides 3 PMOD ports (JA, JB, JC) that connect RPi GPIO pins to standard 12-pin PMOD connectors. See [pmod-hat.md](pmod-hat.md) for the full pin mapping.

## Test Execution Flow

```
┌──────────────────────────────────────────────────────────────┐
│ 1. BOOT                                                      │
│    RPi boots and runs systemd service or cron job             │
│                                                              │
│ 2. PROGRAM FPGA                                              │
│    - OpenOCD (NeTV2): pld load 0 top.bit                     │
│    - openFPGALoader (Arty): --write-flash design.bit         │
│    - dfu-util (Fomu): -D design.dfu                          │
│                                                              │
│ 3. RUN TEST HARNESS                                          │
│    - Open serial port (USB-UART or GPIO UART)                │
│    - Send test commands to FPGA                              │
│    - Read responses and validate                             │
│                                                              │
│ 4. COLLECT RESULTS                                           │
│    - Parse UART output for PASS/FAIL                         │
│    - Check PCIe enumeration (NeTV2)                          │
│    - Verify PMOD loopback signals (Arty, TT FPGA)            │
│    - Report results                                          │
└──────────────────────────────────────────────────────────────┘
```

## Known Gaps

- **tweed.welland.mithis.com**: SSH access timed out during exploration. OS version, kernel, exact USB device topology, and board serial numbers are unknown.
- **RPi3 NeTV2**: Exact OS version and kernel not confirmed.
- **Arty A7 host connectivity**: Whether the Arty connects to `tweed` via USB directly or through an intermediate hub is not confirmed.
- **TT FPGA and Fomu EVT host**: Confirmed on `tweed` but physical USB port assignments are unknown.
