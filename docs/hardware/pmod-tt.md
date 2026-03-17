# TinyTapeout PMOD Connector Standards

Standard PMOD pin layouts recommended by TinyTapeout for use on its demo board PMOD headers. These follow the [Digilent PMOD Interface Specification](https://digilent.com/reference/pmod/specification) and are used across the TinyTapeout community to ensure interoperability between designs and peripheral boards.

## TinyTapeout I/O Signal Groups

TinyTapeout projects have three groups of 8 signals (24 total):

| Signal Group | Direction       | Description                    |
|-------------|-----------------|--------------------------------|
| `ui_in[7:0]`  | Input to chip   | User inputs (from peripherals) |
| `uo_out[7:0]` | Output from chip | User outputs (to peripherals)  |
| `uio[7:0]`    | Bidirectional   | Configurable per-pin           |

## Demo Board PMOD Connectors

The TT demo board has three 12-pin PMOD connectors on the bottom edge, one per signal group. Looking at the board from the top:

```
            ┌──────────────────────────────────────────────────────┐
            │                   TT Demo Board                      │
            │                                                      │
            ├──────────┬──────────┬──────────┐                     │
            │ ui_in    │ uio      │ uo_out   │                     │
            │ (input)  │ (bidir)  │ (output) │                     │
            └──────────┴──────────┴──────────┘
              Left       Middle     Right
```

Each connector maps signals straight through: IO1=bit[0], IO2=bit[1], ... IO8=bit[7].

| PMOD Pin | Row    | TT Signal (for each group X) |
|----------|--------|------------------------------|
| 1 (IO1)  | Top    | X[0]                         |
| 2 (IO2)  | Top    | X[1]                         |
| 3 (IO3)  | Top    | X[2]                         |
| 4 (IO4)  | Top    | X[3]                         |
| 5        | Top    | GND                          |
| 6        | Top    | VCC (3.3V)                   |
| 7 (IO5)  | Bottom | X[4]                         |
| 8 (IO6)  | Bottom | X[5]                         |
| 9 (IO7)  | Bottom | X[6]                         |
| 10 (IO8) | Bottom | X[7]                         |
| 11       | Bottom | GND                          |
| 12       | Bottom | VCC (3.3V)                   |

## Standard Protocol Layouts

TinyTapeout recommends specific pin assignments that align with Digilent PMOD types. Each protocol can use either the top row ([0:3]) or bottom row ([4:7]) of a signal group; **top row is preferred**.

Source: [tinytapeout.com/specs/pinouts](https://tinytapeout.com/specs/pinouts/), [GPIO spreadsheet](https://docs.google.com/spreadsheets/d/1oClV8Y9fUVvqTYBOXfEt2CuNS86VK3US2h4tn60mHgw/edit?gid=1000041856#gid=1000041856)

### SPI (Digilent Type 2) — Bidirectional PMOD

| PMOD Pin | Top Row     | Bottom Row  | Function              |
|----------|-------------|-------------|-----------------------|
| 1 / 7    | uio[0]      | uio[4]      | CS (Chip Select)      |
| 2 / 8    | uio[1]      | uio[5]      | MOSI (Master Out)     |
| 3 / 9    | uio[2]      | uio[6]      | MISO (Master In)      |
| 4 / 10   | uio[3]      | uio[7]      | SCK (Serial Clock)    |

### SPI Alternate — Cross-PMOD (frees bidir for other use)

When the bidir PMOD is needed for something else, SPI can span the input and output PMODs (ASIC as SPI master):

| Function | TT Signal  | Direction    |
|----------|------------|--------------|
| CS       | uo_out[4]  | Output       |
| MOSI     | uo_out[3]  | Output       |
| MISO     | ui_in[2]   | Input        |
| SCK      | uo_out[5]  | Output       |

### QSPI Flash and PSRAM — Bidirectional PMOD (full)

Uses both rows for quad SPI with multiple chip selects. Compatible with the [QSPI PMOD](https://github.com/mole99/qspi-pmod) (16 MB Flash + 16 MB RAM) and [Digilent PmodSF3](https://digilent.com/reference/pmod/pmodsf3/start).

| PMOD Pin | TT Signal | Function         |
|----------|-----------|------------------|
| 1 (IO1)  | uio[0]    | CS0 (Flash)      |
| 2 (IO2)  | uio[1]    | SD0 / MOSI       |
| 3 (IO3)  | uio[2]    | SD1 / MISO       |
| 4 (IO4)  | uio[3]    | SCK              |
| 7 (IO5)  | uio[4]    | SD2              |
| 8 (IO6)  | uio[5]    | SD3              |
| 9 (IO7)  | uio[6]    | CS1 (RAM A)      |
| 10 (IO8) | uio[7]    | CS2 (RAM B)      |

### UART (Digilent Type 3) — Bidirectional PMOD

| PMOD Pin | Top Row     | Bottom Row  | Function                  |
|----------|-------------|-------------|---------------------------|
| 1 / 7    | uio[0]      | uio[4]      | CTS (optional)            |
| 2 / 8    | uio[1]      | uio[5]      | TXD (Transmit)            |
| 3 / 9    | uio[2]      | uio[6]      | RXD (Receive)             |
| 4 / 10   | uio[3]      | uio[7]      | RTS (optional)            |

### UART via RP2040/RP2350 (built-in USB bridge, no PMOD needed)

Two options for UART-to-USB through the on-board microcontroller:

| Variant | RX (to chip) | TX (from chip) |
|---------|-------------|----------------|
| UART0   | ui_in[3]    | uo_out[4]      |
| UART1   | ui_in[7]    | uo_out[0]      |

### I2C (Digilent Type 6) — Bidirectional PMOD

| PMOD Pin | Top Row     | Bottom Row  | Function                  |
|----------|-------------|-------------|---------------------------|
| 1 / 7    | uio[0]      | uio[4]      | INT (optional)            |
| 2 / 8    | uio[1]      | uio[5]      | RESET (optional)          |
| 3 / 9    | uio[2]      | uio[6]      | SCL (Serial Clock)        |
| 4 / 10   | uio[3]      | uio[7]      | SDA (Serial Data)         |

## Standard Peripheral Layouts

### VGA Output (Tiny VGA) — Output PMOD

2-bit per colour channel. Uses only the output PMOD, leaving bidir free.

| PMOD Pin | TT Signal  | Function   |
|----------|------------|------------|
| 1 (IO1)  | uo_out[0]  | R1         |
| 2 (IO2)  | uo_out[1]  | G1         |
| 3 (IO3)  | uo_out[2]  | B1         |
| 4 (IO4)  | uo_out[3]  | vsync      |
| 7 (IO5)  | uo_out[4]  | R0         |
| 8 (IO6)  | uo_out[5]  | G0         |
| 9 (IO7)  | uo_out[6]  | B0         |
| 10 (IO8) | uo_out[7]  | hsync      |

Board: [Tiny VGA](https://github.com/mole99/tiny-vga)

### Audio Output — Output or Bidirectional PMOD

| Mode   | TT Signal             | Function      |
|--------|-----------------------|---------------|
| Mono   | uo_out[7] or uio[7]  | Audio output  |
| Stereo | uo_out[6] or uio[6]  | Left channel  |
|        | uo_out[7] or uio[7]  | Right channel |

Board: [TT Audio Pmod](https://github.com/MichaelBell/tt-audio-pmod) — compatible with QSPI PMOD (uses different pins).

### Game Controller — Input PMOD

| TT Signal | Function |
|-----------|----------|
| ui_in[4]  | LATCH    |
| ui_in[5]  | CLOCK    |
| ui_in[6]  | DATA     |

## RP2350 GPIO Mapping (Demo Board v3, TT09+)

The latest demo board uses an RP2350B. Each TT signal maps to a specific RP2350 GPIO with hardware peripheral options.

Control signals: reset = GPIO14, clock = GPIO16.

| TT Signal   | PMOD Header | PMOD Pin | RP2350 GPIO | I2C       | SPI       | UART      |
|-------------|-------------|----------|-------------|-----------|-----------|-----------|
| ui_in[0]    | Input       | 1        | GPIO17      |           | SPI0.cs   |           |
| ui_in[1]    | Input       | 2        | GPIO18      |           | SPI0.sck  |           |
| ui_in[2]    | Input       | 3        | GPIO19      |           | SPI0.tx   |           |
| ui_in[3]    | Input       | 4        | GPIO20      |           |           | UART1.tx  |
| ui_in[4]    | Input       | 7        | GPIO21      |           | SPI0.cs   |           |
| ui_in[5]    | Input       | 8        | GPIO22      |           | SPI0.sck  |           |
| ui_in[6]    | Input       | 9        | GPIO23      |           | SPI0.tx   | UART1.rts |
| ui_in[7]    | Input       | 10       | GPIO24      |           |           |           |
| uio[0]      | Bidir       | 1        | GPIO25      | I2C0.scl  | SPI1.cs   | UART1.rx  |
| uio[1]      | Bidir       | 2        | GPIO26      | I2C1.sda  | SPI1.sck  | UART1.cts |
| uio[2]      | Bidir       | 3        | GPIO27      | I2C1.scl  | SPI1.tx   | UART0.rts |
| uio[3]      | Bidir       | 4        | GPIO28      | I2C0.sda  | SPI1.rx   | UART0.tx  |
| uio[4]      | Bidir       | 7        | GPIO29      | I2C0.scl  | SPI1.cs   | UART0.rx  |
| uio[5]      | Bidir       | 8        | GPIO30      | I2C1.sda  | SPI1.sck  | UART0.cts |
| uio[6]      | Bidir       | 9        | GPIO31      | I2C1.scl  | SPI1.tx   | UART0.rts |
| uio[7]      | Bidir       | 10       | GPIO32      |           |           |           |
| uo_out[0]   | Output      | 1        | GPIO33      |           |           | UART0.rx  |
| uo_out[1]   | Output      | 2        | GPIO34      |           |           | UART0.cts |
| uo_out[2]   | Output      | 3        | GPIO35      |           |           |           |
| uo_out[3]   | Output      | 4        | GPIO36      |           | SPI0.rx   |           |
| uo_out[4]   | Output      | 7        | GPIO37      |           |           | UART1.rx  |
| uo_out[5]   | Output      | 8        | GPIO38      |           |           | UART1.cts |
| uo_out[6]   | Output      | 9        | GPIO39      |           |           |           |
| uo_out[7]   | Output      | 10       | GPIO40      |           | SPI0.rx   |           |

## RP2040 GPIO Mapping (Demo Board v2, TT06-TT08)

Control signals: clock = GPIO0, reset = GPIO1. TT04/TT05 had a discrete MUX sharing uo_out[0:3] with control signals; TT06+ removed it.

| TT Signal   | PMOD Header | PMOD Pin | RP2040 GPIO | I2C       | SPI       | UART      |
|-------------|-------------|----------|-------------|-----------|-----------|-----------|
| ui_in[0]    | Input       | 1        | GPIO9       |           | SPI1.cs   |           |
| ui_in[1]    | Input       | 2        | GPIO10      |           | SPI1.sck  |           |
| ui_in[2]    | Input       | 3        | GPIO11      |           | SPI1.tx   |           |
| ui_in[3]    | Input       | 4        | GPIO12      |           | SPI1.rx   | UART0.tx  |
| ui_in[4]    | Input       | 7        | GPIO17      |           | SPI0.cs   |           |
| ui_in[5]    | Input       | 8        | GPIO18      |           | SPI0.sck  |           |
| ui_in[6]    | Input       | 9        | GPIO19      |           | SPI0.tx   |           |
| ui_in[7]    | Input       | 10       | GPIO20      |           | SPI0.rx   | UART1.tx  |
| uio[0]      | Bidir       | 1        | GPIO21      | I2C0.scl  |           | UART1.rx  |
| uio[1]      | Bidir       | 2        | GPIO22      |           |           |           |
| uio[2]      | Bidir       | 3        | GPIO23      |           |           |           |
| uio[3]      | Bidir       | 4        | GPIO24      |           | SPI1.rx   | UART1.tx  |
| uio[4]      | Bidir       | 7        | GPIO25      |           | SPI1.cs   | UART1.rx  |
| uio[5]      | Bidir       | 8        | GPIO26      |           | SPI1.sck  |           |
| uio[6]      | Bidir       | 9        | GPIO27      |           | SPI1.tx   |           |
| uio[7]      | Bidir       | 10       | GPIO28      |           | SPI1.rx   |           |
| uo_out[0]   | Output      | 1        | GPIO5       |           |           |           |
| uo_out[1]   | Output      | 2        | GPIO6       |           |           |           |
| uo_out[2]   | Output      | 3        | GPIO7       |           | SPI0.tx   |           |
| uo_out[3]   | Output      | 4        | GPIO8       |           | SPI0.rx   | UART1.tx  |
| uo_out[4]   | Output      | 7        | GPIO13      |           | SPI1.cs   |           |
| uo_out[5]   | Output      | 8        | GPIO14      |           | SPI1.sck  |           |
| uo_out[6]   | Output      | 9        | GPIO15      |           | SPI1.tx   |           |
| uo_out[7]   | Output      | 10       | GPIO16      |           | SPI1.rx   | UART0.tx  |

## Community PMOD Boards

| Board | Description | PMOD Port |
|-------|-------------|-----------|
| [Tiny VGA](https://github.com/mole99/tiny-vga) | VGA output, 2-bit/channel | Output |
| [QSPI PMOD](https://github.com/mole99/qspi-pmod) | 16 MB Flash + 16 MB RAM | Bidir |
| [TT Audio](https://github.com/MichaelBell/tt-audio-pmod) | Mono PWM audio, line out + piezo | Bidir or Output |
| [VGA Clock](https://github.com/TinyTapeout/tt-vga-clock-pmod) | VGA + 3 buttons | Input + Output |
| [Simon Says](https://github.com/urish/tt-simon-pmod) | 4 LEDs, 4 buttons, piezo, 7-seg | Custom |
| [ChipTune PWM](https://github.com/WallieEverest/pmod_pwm) | PWM audio filter + USB UART | Custom |
| [KianV QSPI](https://github.com/splinedrive/kianRiscV/tree/master/archive/pcb/pmod_nor_psram) | 8 MB Flash + 8 MB RAM | Bidir |

More at: [awesome-tinytapeout-pmods](https://github.com/TinyTapeout/awesome-tinytapeout-pmods)

## Design Guidelines

1. **Use common pinouts** where possible — shared pinouts make it easier to swap peripheral boards between designs.
2. **Not mandatory** — these are recommendations, not requirements.
3. **Prefer top row** — for protocols using only one row (SPI, UART, I2C), use pins 1-4 (signals [0:3]).
4. **Bidir for protocols** — the bidir PMOD is the natural choice for bidirectional protocols.
5. **3.3V I/O** — all signals use 3.3V logic levels.
6. **Propose new layouts** — if you use a protocol not listed here, propose it on the [TinyTapeout Discord](https://discord.gg/tinytapeout).

## References

- [TinyTapeout Pinout Recommendations](https://tinytapeout.com/specs/pinouts/)
- [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)
- [TT Demo PCB Repository](https://github.com/TinyTapeout/tt-demo-pcb)
- [TT KiCad PMOD Library](https://github.com/TinyTapeout/kicad-tinytapeout-pmod-lib)
- [GPIO Spreadsheet](https://docs.google.com/spreadsheets/d/1oClV8Y9fUVvqTYBOXfEt2CuNS86VK3US2h4tn60mHgw/edit?gid=1000041856#gid=1000041856)
- [Digilent PMOD Specification](https://digilent.com/reference/pmod/specification)
