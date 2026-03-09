# TinyTapeout FPGA Demo Board

The TinyTapeout (TT) FPGA Demo Board is a development platform that combines an FPGA breakout board (Lattice iCE40UP5K) with the TinyTapeout demo PCB (RP2040-based). It allows testing TinyTapeout designs on real FPGA hardware before silicon fabrication.

## Key Specifications

| Parameter | Value |
|-----------|-------|
| FPGA | Lattice iCE40UP5K (on FPGA breakout board) |
| Logic cells | 5,280 LUT4s |
| SPRAM | 128 KB (4 x 32 KB blocks) |
| DPRAM (EBR) | 120 Kbit (15 x 8 Kbit blocks) |
| Controller | RP2040 (dual-core Arm Cortex-M0+, on demo PCB) |
| USB | USB-C (via RP2040) |
| Display | 7-segment LED display |
| DIP switches | Configuration switches |
| PMOD headers | 2x standard PMOD (following Digilent spec) |
| Max clock | ~66 MHz |
| I/O voltage | 3.3V |

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/), [TinyTapeout FPGA Breakout Guide](https://tinytapeout.com/guides/fpga-breakout/)

## Architecture

The TT FPGA Demo Board consists of two PCBs:

1. **TinyTapeout Demo PCB** (bottom): Contains the RP2040 microcontroller, USB-C connector, 7-segment display, DIP switches, and PMOD headers. This PCB is designed to interface with TinyTapeout ASICs but also accepts the FPGA breakout board.

2. **FPGA Breakout Board** (top): Contains the iCE40UP5K FPGA and SPI flash. It plugs into the demo PCB's chip socket, presenting the same interface as a TinyTapeout ASIC.

```
┌──────────────────────────────┐
│    FPGA Breakout Board       │
│    (iCE40UP5K + SPI Flash)   │
│                              │
│    ┌────────────────────┐    │
│    │  Pin headers down  │    │
│    └────────────────────┘    │
└──────────────┬───────────────┘
               │ (plugs into)
┌──────────────┴───────────────┐
│    TinyTapeout Demo PCB      │
│                              │
│  [USB-C] [RP2040] [7-seg]   │
│  [DIP SW] [PMOD A] [PMOD B] │
└──────────────────────────────┘
```

## TinyTapeout I/O Interface

The FPGA implements a TinyTapeout-compatible interface with the following signals:

| Signal Group | Width | Direction | Description |
|-------------|-------|-----------|-------------|
| `ui_in[7:0]` | 8 bits | Input | User inputs (directly from DIP switches or RP2040) |
| `uo_out[7:0]` | 8 bits | Output | User outputs (directly to 7-segment display or RP2040) |
| `uio[7:0]` | 8 bits | Bidirectional | User bidirectional I/O |
| `ena` | 1 bit | Input | Enable signal |
| `clk` | 1 bit | Input | Clock (up to ~66 MHz) |
| `rst_n` | 1 bit | Input | Active-low reset |

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)

## Serial Interface

The TT FPGA board supports UART communication through the TinyTapeout I/O pins. Two serial pin configurations are available:

### Option 1 (Default TT UART)

| Signal | TT Pin | Direction (FPGA perspective) |
|--------|--------|------------------------------|
| RX | ui_in[3] | Input |
| TX | uo_out[4] | Output |

### Option 2 (Alternate)

| Signal | TT Pin | Direction (FPGA perspective) |
|--------|--------|------------------------------|
| RX | ui_in[7] | Input |
| TX | uo_out[0] | Output |

The RP2040 on the demo PCB can act as a USB-to-UART bridge, forwarding serial data between the USB-C port and the FPGA's UART pins.

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)

## PMOD Headers

The demo PCB has 2 standard PMOD headers following the Digilent specification:

- Each header is a 12-pin connector (8 signal + 2 GND + 2 VCC)
- Signal voltage: 3.3V
- The PMOD signals are routed through the TinyTapeout bidirectional I/O (`uio`) or directly to the FPGA breakout board

These PMOD headers can be used for loopback testing in the fpgas.online infrastructure.

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)

## Clock

The FPGA can be clocked at up to approximately 66 MHz. The clock signal is provided by the RP2040 or an on-board oscillator on the FPGA breakout board. The exact maximum frequency depends on the design complexity and routing.

## 7-Segment Display

The demo PCB includes a 7-segment LED display connected to the `uo_out` pins. This provides immediate visual feedback from the FPGA design:

| Segment | TT Output Pin |
|---------|--------------|
| a | uo_out[0] |
| b | uo_out[1] |
| c | uo_out[2] |
| d | uo_out[3] |
| e | uo_out[4] |
| f | uo_out[5] |
| g | uo_out[6] |
| dp | uo_out[7] |

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)

## DIP Switches

The demo PCB has DIP switches connected to the `ui_in` pins, allowing manual input to the FPGA design during development and testing.

## Programming

The FPGA breakout board is programmed through the RP2040 on the demo PCB. The RP2040 acts as a USB bridge and can load bitstreams into the iCE40UP5K.

```bash
# Programming is typically done via the RP2040's USB interface
# The exact command depends on the RP2040 firmware
```

The FPGA breakout board also has SPI flash for persistent bitstream storage.

## LiteX Integration

| Property | Value |
|----------|-------|
| FPGA | iCE40UP5K (same as Fomu) |
| Toolchain | Yosys + nextpnr-ice40 (open source, IceStorm flow) |

The TT FPGA board does not have a dedicated LiteX platform file in litex-boards. Designs target the iCE40UP5K with a custom pin constraint file matching the TinyTapeout I/O interface.

## Test Infrastructure Usage

In the fpgas.online setup, the TT FPGA Demo Board connects to the host (`tweed.welland.mithis.com`) via USB-C. The RP2040 provides:

1. USB-to-UART bridge for serial communication with the FPGA
2. Bitstream loading capability
3. Clock generation for the FPGA

Available tests:
- **PMOD Loopback**: Verifies signal integrity through the PMOD headers
- **SPI Flash ID**: Reads and verifies the SPI flash JEDEC ID

## References

- TinyTapeout Demo PCB design: <https://github.com/TinyTapeout/tt-demo-pcb>
- TinyTapeout PCB specifications: <https://tinytapeout.com/specs/pcb/>
- TinyTapeout FPGA Breakout Guide: <https://tinytapeout.com/guides/fpga-breakout/>
- TT FPGA Demo repository: <https://github.com/efabless/tt-fpga-demo>
- TinyTapeout main site: <https://tinytapeout.com>
