# PMOD Interface Specification

The PMOD (Peripheral Module) interface is a standard defined by Digilent for connecting peripheral modules to FPGA and microcontroller host boards. This document covers the standard PMOD connector types, pinouts, and the extended I2C interface.

Source: [Digilent PMOD Interface Specification 1.3.1](https://digilent.com/reference/pmod/pmod-interface-specification), [High Speed PMOD Spreadsheet](https://docs.google.com/spreadsheets/d/1D-GboyrP57VVpejQzEm0P1WEORo1LAIt92hk1bZGEoo/edit?gid=0#gid=0)

## Physical Connectors

PMOD connectors use standard 100 mil (2.54 mm) pitch pin headers. There are two widths:

### Single Width (6-pin, 1×6)

4 signal pins + 1 GND + 1 VCC.

```
Host side (looking at board edge):

  ┌───┬───┬───┬───┬───┬───┐
  │ 1 │ 2 │ 3 │ 4 │ 5 │ 6 │
  └───┴───┴───┴───┴───┴───┘
   IO  IO  IO  IO GND VCC
        ◄── 0.40" ──►
   ◄0.15"►  (edge setback)
```

| Pin | Function   |
|-----|------------|
| 1   | Signal I/O |
| 2   | Signal I/O |
| 3   | Signal I/O |
| 4   | Signal I/O |
| 5   | GND        |
| 6   | VCC        |

### Double Width (12-pin, 2×6)

8 signal pins + 2 GND + 2 VCC. The top row (pins 1-6) matches the single width pinout.

```
Host side (looking at board edge):

  ┌───┬───┬───┬───┬───┬───┐
  │ 1 │ 2 │ 3 │ 4 │ 5 │ 6 │  (top row)
  ├───┼───┼───┼───┼───┼───┤
  │ 7 │ 8 │ 9 │10 │11 │12 │  (bottom row)
  └───┴───┴───┴───┴───┴───┘
   IO  IO  IO  IO GND VCC
        ◄── 0.45" ──►
   ◄0.20"►  (edge setback)
```

| Pin | Function   | Pin | Function   |
|-----|------------|-----|------------|
| 1   | Signal I/O | 7   | Signal I/O |
| 2   | Signal I/O | 8   | Signal I/O |
| 3   | Signal I/O | 9   | Signal I/O |
| 4   | Signal I/O | 10  | Signal I/O |
| 5   | GND        | 11  | GND        |
| 6   | VCC        | 12  | VCC        |

### Electrical Characteristics

| Parameter           | Value                          |
|---------------------|--------------------------------|
| VCC voltage         | 3.3V (standard)                |
| Max current per VCC | 100 mA                         |
| I/O standard        | LVCMOS33 (matched to VCC)      |
| Pin pitch           | 100 mil (2.54 mm)              |
| Connector type      | Standard 100 mil pin header    |

## Standard PMOD Interface Types

Digilent defines 9 interface types that assign specific protocols to the signal pins. All types share pins 5/6 (and 11/12 for double width) as GND/VCC.

### Type 1 — GPIO (6-pin)

General-purpose I/O. All 4 signal pins are bidirectional.

| Pin | Signal | Direction |
|-----|--------|-----------|
| 1   | IO1    | In/Out    |
| 2   | IO2    | In/Out    |
| 3   | IO3    | In/Out    |
| 4   | IO4    | In/Out    |
| 5   | GND    | —         |
| 6   | VCC    | —         |

### Type 1A — Expanded GPIO (12-pin)

Double-width GPIO with 8 bidirectional I/O pins in two banks (A and B).

| Pin | Signal | Direction | Pin | Signal | Direction |
|-----|--------|-----------|-----|--------|-----------|
| 1   | IOA1   | In/Out    | 7   | IOB1   | In/Out    |
| 2   | IOA2   | In/Out    | 8   | IOB2   | In/Out    |
| 3   | IOA3   | In/Out    | 9   | IOB3   | In/Out    |
| 4   | IOA4   | In/Out    | 10  | IOB4   | In/Out    |
| 5   | GND    | —         | 11  | GND    | —         |
| 6   | VCC    | —         | 12  | VCC    | —         |

### Type 2 — SPI (6-pin)

SPI bus interface. Direction is from the host's perspective (host is SPI master).

| Pin | Signal | Direction | Description                          |
|-----|--------|-----------|--------------------------------------|
| 1   | SS     | Out       | Slave Select (active low)            |
| 2   | MOSI   | Out       | Master Out Slave In (data to slave)  |
| 3   | MISO   | In        | Master In Slave Out (data from slave)|
| 4   | SCK    | Out       | Serial Clock (from master)           |
| 5   | GND    | —         |                                      |
| 6   | VCC    | —         |                                      |

### Type 2A — Expanded SPI (12-pin)

SPI with additional control signals on the bottom row.

| Pin | Signal | Direction | Pin | Signal | Direction | Description                     |
|-----|--------|-----------|-----|--------|-----------|---------------------------------|
| 1   | SS     | Out       | 7   | INT    | In        | Interrupt (peripheral → host)   |
| 2   | MOSI   | Out       | 8   | RESET  | Out       | Reset (host → peripheral)       |
| 3   | MISO   | In        | 9   | N/S    | N/S       | Module-specific or unconnected  |
| 4   | SCK    | Out       | 10  | N/S    | N/S       | Module-specific or unconnected  |
| 5   | GND    | —         | 11  | GND    | —         |                                 |
| 6   | VCC    | —         | 12  | VCC    | —         |                                 |

### Type 3 — UART (6-pin)

UART with hardware flow control. Direction is from the **peripheral's** perspective (peripheral sends CTS/RXD, receives RTS/TXD).

| Pin | Signal | Direction | Description                               |
|-----|--------|-----------|-------------------------------------------|
| 1   | CTS    | Out       | Permission for peripheral to send to host |
| 2   | RTS    | In        | Request from peripheral to send to host   |
| 3   | RXD    | In        | Data from peripheral to host              |
| 4   | TXD    | Out       | Data from host to peripheral              |
| 5   | GND    | —         |                                           |
| 6   | VCC    | —         |                                           |

Note: Type 3 is defined from a different perspective than Type 4. Type 3 "Out" means the host drives the signal.

### Type 4 — UART (6-pin)

UART with hardware flow control. Direction is from the **device's** perspective (device asserts CTS when ready to receive, asserts RTS when ready to send).

| Pin | Signal | Direction | Description                       |
|-----|--------|-----------|-----------------------------------|
| 1   | CTS    | In        | Device transmits only when active |
| 2   | TXD    | Out       | Data from peripheral to host      |
| 3   | RXD    | In        | Data from host to peripheral      |
| 4   | RTS    | Out       | Device is ready to receive data   |
| 5   | GND    | —         |                                   |
| 6   | VCC    | —         |                                   |

### Type 4A — Expanded UART (12-pin)

UART (Type 4 pinout) with additional control signals on the bottom row.

| Pin | Signal | Direction | Pin | Signal | Direction | Description                     |
|-----|--------|-----------|-----|--------|-----------|---------------------------------|
| 1   | CTS    | In        | 7   | INT    | In        | Interrupt (peripheral → host)   |
| 2   | TXD    | Out       | 8   | RESET  | Out       | Reset (host → peripheral)       |
| 3   | RXD    | In        | 9   | N/S    | N/S       | Module-specific or unconnected  |
| 4   | RTS    | Out       | 10  | N/S    | N/S       | Module-specific or unconnected  |
| 5   | GND    | —         | 11  | GND    | —         |                                 |
| 6   | VCC    | —         | 12  | VCC    | —         |                                 |

### Type 5 — H-Bridge (6-pin)

Single H-bridge motor driver interface.

| Pin | Signal | Direction | Description            |
|-----|--------|-----------|------------------------|
| 1   | DIR    | Out       | Motor direction        |
| 2   | EN     | Out       | Motor enable (active high) |
| 3   | SA     | In        | Feedback sense A       |
| 4   | SB     | In        | Feedback sense B       |
| 5   | GND    | —         |                        |
| 6   | VCC    | —         |                        |

### Type 6 — Dual H-Bridge (6-pin)

Two H-bridge motor/phase drivers on a single 6-pin connector (no feedback).

| Pin | Signal | Direction | Description                          |
|-----|--------|-----------|--------------------------------------|
| 1   | DIR1   | Out       | Motor/Phase 1 direction (active high)|
| 2   | EN1    | Out       | Motor/Phase 1 enable                 |
| 3   | DIR2   | Out       | Motor/Phase 2 direction (active high)|
| 4   | EN2    | Out       | Motor/Phase 2 enable                 |
| 5   | GND    | —         |                                      |
| 6   | VCC    | —         |                                      |

## Extended Interface: I2C (8-pin)

The I2C PMOD interface is not part of the standard Digilent PMOD specification but is defined as an extension. It uses an 8-pin connector with paired signals for improved signal integrity.

```
  ┌───┬───┬───┬───┬───┬───┬───┬───┐
  │ 1 │ 2 │ 3 │ 4 │ 5 │ 6 │ 7 │ 8 │
  └───┴───┴───┴───┴───┴───┴───┴───┘
  SCL SCL SDA SDA GND GND VCC VCC
```

| Pin | Signal | Pin | Signal |
|-----|--------|-----|--------|
| 1   | SCL    | 2   | SCL    |
| 3   | SDA    | 4   | SDA    |
| 5   | GND    | 6   | GND    |
| 7   | VCC    | 8   | VCC    |

Each signal has two pins for lower impedance and better signal integrity at higher I2C speeds (400 kHz Fast Mode, 1 MHz Fast Mode Plus).

Source: [High Speed PMOD Spreadsheet](https://docs.google.com/spreadsheets/d/1D-GboyrP57VVpejQzEm0P1WEORo1LAIt92hk1bZGEoo/edit?gid=0#gid=0)

## Summary Table

| Type | Name           | Width  | Pins | Protocol          |
|------|----------------|--------|------|-------------------|
| 1    | GPIO           | Single | 6    | General I/O       |
| 1A   | Expanded GPIO  | Double | 12   | General I/O (×8)  |
| 2    | SPI            | Single | 6    | SPI bus           |
| 2A   | Expanded SPI   | Double | 12   | SPI + INT/RESET   |
| 3    | UART           | Single | 6    | UART + flow ctrl  |
| 4    | UART           | Single | 6    | UART + flow ctrl  |
| 4A   | Expanded UART  | Double | 12   | UART + INT/RESET  |
| 5    | H-Bridge       | Single | 6    | Motor driver      |
| 6    | Dual H-Bridge  | Single | 6    | Dual motor driver |
| —    | I2C (extended) | Custom | 8    | I2C bus           |

## References

- Digilent PMOD Interface Specification 1.3.1: <https://digilent.com/reference/pmod/pmod-interface-specification>
- Digilent PMOD product listing: <https://digilent.com/reference/pmod/start>
- High Speed PMOD Spreadsheet: <https://docs.google.com/spreadsheets/d/1D-GboyrP57VVpejQzEm0P1WEORo1LAIt92hk1bZGEoo/edit?gid=0#gid=0>
- Digilent PMOD HAT Adapter (for RPi): [rpi-hat-pmod.md](rpi-hat-pmod.md)
