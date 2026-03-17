# GPIO Connectivity Analysis Using FPGA Pin Identification

This document describes how to use the `pmod-pin-id` FPGA design to automatically determine the physical wiring between an FPGA board and a host (such as a Raspberry Pi with a PMOD HAT). Instead of manually tracing cables or trusting documentation, the FPGA tells you exactly what pin you're looking at.

## How It Works

The technique is simple: each FPGA output pin continuously transmits its own name as slow UART data. Connect any host GPIO to any FPGA pin, and the host decodes the name to identify the connection.

```
FPGA Pin G13 ──── transmits "G13\r\n" at 1200 baud ────> RPi GPIO8
FPGA Pin B18 ──── transmits "B18\r\n" at 1200 baud ────> RPi GPIO21
FPGA Pin E15 ──── transmits "E15\r\n" at 1200 baud ────> RPi GPIO7
  ...every pin simultaneously...
```

### Why 1200 Baud?

- **Reliable with software bit-banging**: At 1200 baud each bit is ~833 us, easily sampled by Python on a Raspberry Pi without real-time scheduling.
- **Trivial FPGA divider**: A 100 MHz clock divides to 1200 baud with 83,333 cycles per bit (0.0004% error). Even a 12 MHz iCE40 clock gives 10,000 cycles per bit.
- **No hardware UART needed on the host**: The RPi scanner uses `gpiod` to read GPIO values directly — no serial port, no kernel driver, no device tree overlay.

### Why FPGA Pin Names?

The design transmits the FPGA package ball name (e.g. `G13`, `V14`, `K16`) rather than a connector label (e.g. `JA01`). This is the canonical, unambiguous identifier:

- It doesn't depend on which connector naming convention the board uses.
- It matches what you see in constraint files (XDC, PCF) and schematics.
- You can look up the pin in the FPGA datasheet directly.
- The connector label can be derived by cross-referencing with the platform file.

## Components

### FPGA Gateware

Two files in `designs/pmod-pin-id/gateware/`:

**`pmod_pin_id.py`** — The reusable `UARTTxIdentifier` Migen module. Each instance is a tiny state machine: a baud rate counter, a character index into the label string, and a 10-bit shift register (start + 8 data + stop). The pin idles high and continuously cycles through the label characters. Board-agnostic — works with any LiteX platform.

**`pmod_pin_id_<board>.py`** — Board-specific build script. Extracts FPGA pin names from the LiteX platform's connector table and instantiates one `UARTTxIdentifier` per pin. Pure gateware (no CPU, no firmware).

Example for the Arty A7 (`pmod_pin_id_arty.py`):

```python
CONNECTORS = ["pmoda", "pmodb", "pmodc", "pmodd"]

def build_pin_list(platform):
    pins = []
    for connector_name in CONNECTORS:
        connector_pins = platform.constraint_manager.connector_manager.connector_table[connector_name]
        for idx in range(len(connector_pins)):
            resource_pin = f"{connector_name}:{idx}"
            fpga_pin = connector_pins[idx]
            label = f"{fpga_pin}\r\n"
            pins.append((resource_pin, label))
    return pins
```

The pin names come directly from the platform definition — no hardcoding, no manual lookup tables.

### Host Scanner

**`designs/pmod-pin-id/host/identify_pmod_pins.py`** — Python script that runs on the RPi. For each GPIO pin:

1. Configures the GPIO as input using `gpiod` (v1.6+ or v2.x).
2. Waits for the line to go HIGH (idle state).
3. Detects the HIGH-to-LOW transition (UART start bit).
4. Samples 8 data bits at the centre of each bit period.
5. Repeats for multiple frames to build a label string.
6. Validates the decoded label against expected format.
7. Reports the mapping.

The scanner tries 10 frames per GPIO and uses majority voting. Labels must match `^[A-Z][A-Za-z0-9]{1,3}$` (FPGA pin names like `G13`, `V14`) to be accepted as valid.

## Usage

### Quick Start (Arty A7)

```bash
# 1. Build the bitstream (CI does this automatically)
cd designs/pmod-pin-id
make gateware-arty

# 2. Program the FPGA
make program-arty

# 3. Run the scanner on the RPi
make scan-arty
```

### Scanner Options

```bash
# Scan all PMOD HAT GPIOs (default)
uv run python host/identify_pmod_pins.py

# Scan specific GPIOs
uv run python host/identify_pmod_pins.py --gpios 8 19 21

# Scan a single HAT port
uv run python host/identify_pmod_pins.py --hat-port JA

# Skip kernel module unloading (if already done)
uv run python host/identify_pmod_pins.py --no-unload
```

### Example Output

```
=== FPGA Pin Identification Scanner ===
Baud rate:  1200
GPIO chip:  /dev/gpiochip0
Scanning:   21 GPIO pins

  GPIO 8 (HAT JA pin 01       ) -> G13
  GPIO19 (HAT JA pin 07       ) -> D13
  GPIO21 (HAT JA pin 08       ) -> B18
  GPIO20 (HAT JA pin 09       ) -> A18
  GPIO18 (HAT JA pin 10       ) -> K16
  GPIO 7 (HAT JB pin 01       ) -> E15
  GPIO26 (HAT JB pin 07       ) -> J17
  GPIO13 (HAT JB pin 08       ) -> J18
  ...

=== Pin Mapping Table (21 confirmed, 0 garbled, 0 no signal) ===

| RPi GPIO | HAT Location           | FPGA Pin |
|----------|------------------------|----------|
| GPIO7    | HAT JB pin 01          | E15      |
| GPIO8    | HAT JA pin 01          | G13      |
| ...
```

## Adding a New Board

To use this tool with a different FPGA board:

### 1. Create the board-specific build script

Copy `pmod_pin_id_arty.py` and modify:

```python
# Change the platform import
from litex_boards.platforms.your_board import Platform

# Change the connector list to match your board's connectors
CONNECTORS = ["pmoda", "pmodb"]  # whatever your board has

# Change the clock frequency
SYS_CLK_FREQ = 48e6  # your board's clock

# Change the I/O standard if needed (in build_io_extensions)
IOStandard("LVCMOS33")  # or LVCMOS18, etc.
```

The `build_pin_list()` function works unchanged — it reads connector pin names from any LiteX platform.

### 2. Update the scanner's GPIO list (if needed)

If your host uses a different GPIO-to-connector mapping than the Digilent PMOD HAT, update `PMOD_HAT_PORTS` in `identify_pmod_pins.py` or pass `--gpios` explicitly.

### 3. Add Makefile targets

```makefile
gateware-yourboard:
	$(PYTHON) gateware/pmod_pin_id_yourboard.py --build

program-yourboard:
	openFPGALoader -b yourboard build/yourboard/gateware/your_board.bit

scan-yourboard:
	$(PYTHON) host/identify_pmod_pins.py --gpios 2 3 4 5 6 7
```

## Interpreting Results

### Clean decode

```
GPIO8 (HAT JA pin 01) -> G13
```

The FPGA pin G13 is physically connected to RPi GPIO8 through the cable. Cross-reference G13 with the FPGA platform file to determine which connector and pin position it belongs to.

### Garbled decode

```
GPIO7 (HAT JB pin 07) -> (garbled: '????a????a')
```

Signal is present (start bits detected) but the UART frames are not decoding cleanly. Causes:

- **Python timing jitter**: The bit-bang sampling missed bit boundaries. Re-running usually helps.
- **Bus contention**: Two FPGA outputs driving the same GPIO (e.g. the PMOD HAT's shared SPI pins JA2-4 / JB2-4).
- **Kernel driver conflict**: A kernel driver (SPI, I2C, UART) is actively driving the GPIO. Run with `--no-unload` disabled (default) to let the scanner unload SPI modules.

### No signal

```
GPIO0 (HAT JB pin 09) -> (no signal)
```

The GPIO is stuck high (idle). Causes:

- **Not connected**: The GPIO doesn't route to any FPGA pin (e.g. GPIO0/1 are I2C EEPROM on the PMOD HAT, not routed to any PMOD port).
- **Hardware pull-up too strong**: The GPIO has a pull-up that overrides the FPGA's drive (unlikely with LVCMOS33 at 3.3V).
- **Cable not plugged in**: The PMOD cable isn't connecting this port.
- **Wrong GPIO chip**: On RPi 5, the GPIO chip is different (`pinctrl-rp1` vs `pinctrl-bcm2711`). The scanner auto-detects this.

## Cross-Validation

For high confidence, run two independent scans:

1. **PMOD name scan**: Modify the gateware to transmit connector pin names (e.g. `JA01`) instead of FPGA ball names. This tests the firmware's index-to-physical-pin mapping.

2. **FPGA pin name scan**: The default mode. This reads pin names directly from the LiteX platform connector table.

If both scans agree (each GPIO maps to the expected FPGA pin for its connector position), the mapping is verified. Any disagreement points to a bug in the connector table, a cable swap, or a documentation error.

This is how the Arty A7 mapping was verified in the fpgas.online infrastructure: 17 of 21 unique GPIOs decoded correctly in both scans, and the 4 that garbled in one scan were confirmed via the other.

## Limitations

- **Shared GPIOs**: The PMOD HAT shares GPIO9/10/11 between ports JA and JB (SPI bus). When cables are connected to both Arty JA and JB, these GPIOs see bus contention and will read the stronger driver's signal (typically JB wins). Pins 2-4 of JA cannot be independently verified while JB is also connected.

- **I2C EEPROM GPIOs**: GPIO0 and GPIO1 on the RPi are used for the HAT's I2C EEPROM and are not routed to any PMOD port. They will always show "no signal".

- **Baud rate vs. label length**: Shorter labels (2-3 chars for FPGA names like `G13`) repeat faster than longer ones (4 chars like `JA01`), giving more decode attempts but slightly different timing characteristics. Both work reliably.

- **32 simultaneous UART TX modules**: Uses minimal FPGA resources (a few hundred LUTs on Artix-7 for 32 instances) but the design cannot be combined with other gateware. It's a dedicated diagnostic bitstream, not a test overlay.

## References

- Gateware source: [`designs/pmod-pin-id/gateware/`](../../designs/pmod-pin-id/gateware/)
- Host scanner: [`designs/pmod-pin-id/host/identify_pmod_pins.py`](../../designs/pmod-pin-id/host/identify_pmod_pins.py)
- PMOD HAT pin mapping: [rpi-hat-pmod.md](rpi-hat-pmod.md)
- Arty A7 pin mapping (with scan results): [arty-pin-mapping.md](arty-pin-mapping.md)
- TinyTapeout PMOD standards: [pmod-tt.md](pmod-tt.md)
