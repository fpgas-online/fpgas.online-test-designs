# Acorn CLE-215+ Wiring Guide

Step-by-step instructions for wiring a Sqrl Acorn CLE-215+ (or LiteFury/NiteFury) to a Raspberry Pi 5 for use in the fpgas.online test infrastructure.

See [acorn-cle215.md](acorn-cle215.md) for board specs and [acorn-cle215-pinmap.md](acorn-cle215-pinmap.md) for the full pin mapping.

## Bill of Materials

| Item | Description | Qty |
|------|-------------|-----|
| Sqrl Acorn CLE-215+ | M.2 M-key PCIe FPGA accelerator | 1 |
| Raspberry Pi 5 | 8 GB recommended | 1 |
| M.2 PCIe HAT for RPi 5 | M.2 M-key to RPi PCIe adapter (e.g. Pimoroni NVMe Base, Geekworm X1001) | 1 |
| Molex Pico-EZmate cable (6-pin) | [Molex 0369200601](https://www.digikey.fr/en/products/detail/molex/0369200601/10233018) | 2 |
| 2×3 Dupont pin header (2.54 mm) | Male or female depending on your RPi header setup | 2 |
| Solder + heat shrink | For cable termination | — |

## Step 1: Prepare the Pico-EZmate Cables

The Acorn has two 6-pin Molex Pico-EZmate connectors: **P1** (JTAG) and **P2** (UART/GPIO). Each needs a cable adapted to connect to the RPi GPIO header.

1. Take two Pico-EZmate 6-pin cables.
2. Cut each cable roughly in half — you only need the end with the Pico-EZmate plug.
3. Strip ~3 mm of insulation from each wire.

## Step 2: Terminate the P2 Cable (UART + GPIO)

The P2 cable carries UART and 2 spare GPIOs. Solder or crimp Dupont connectors onto a 2×3 pin header arranged to plug directly into RPi header pins 5-10:

```
RPi Header (pins 5-10, looking at the board from above):

  Pin 5  Pin 6     ← GPIO3 (SDA1) / GND
  Pin 7  Pin 8     ← GPIO4 (GPCLK0) / GPIO14 (TXD0)
  Pin 9  Pin 10    ← GND / GPIO15 (RXD0)
```

Wire the P2 Pico-EZmate pins to the 2×3 header:

| P2 Pin | Wire Colour (typical) | Function     | → RPi Header Pin | RPi GPIO |
|--------|-----------------------|--------------|-------------------|----------|
| 1      | —                     | Serial TX    | Pin 8             | GPIO14   |
| 2      | —                     | Serial RX    | Pin 10            | GPIO15   |
| 3      | —                     | Spare GPIO 0 | Pin 5             | GPIO3    |
| 4      | —                     | Spare GPIO 1 | Pin 7             | GPIO4    |
| 5      | —                     | GND          | Pin 6             | GND      |
| 6      | —                     | VCC (3.3V)   | Pin 9             | GND      |

**Note**: P2 pin 6 is 3.3V from the Acorn. It connects to RPi pin 9 (GND) — this is intentional as a safety measure. Do NOT connect the Acorn's 3.3V to the RPi's 3.3V rail. If you need 3.3V reference, use a separate connection.

**Important**: Verify the wire order of your specific Pico-EZmate cable with a multimeter before connecting. The pin numbering on the Pico-EZmate connector may not match the wire colour order.

## Step 3: Terminate the P1 Cable (JTAG)

The P1 cable carries JTAG signals. Solder or crimp Dupont connectors onto a 2×3 pin header arranged to plug into RPi header pins 19-26 (the SPI0 pin group):

```
RPi Header (pins 19-26, looking at the board from above):

  Pin 19 Pin 20    ← GPIO10 (SPI0_MOSI) / GND
  Pin 21 Pin 22    ← GPIO9 (SPI0_MISO) / GPIO25
  Pin 23 Pin 24    ← GPIO11 (SPI0_SCLK) / GPIO8 (SPI0_CE0)
  Pin 25 Pin 26    ← GND / GPIO7 (SPI0_CE1)
```

Wire the P1 Pico-EZmate pins to the 2×3 header:

| P1 Pin | Function | → RPi Header Pin | RPi GPIO | BCM Function  |
|--------|----------|-------------------|----------|---------------|
| 1      | TCK      | Pin 23            | GPIO11   | SPI0_SCLK     |
| 2      | TDI      | Pin 19            | GPIO10   | SPI0_MOSI     |
| 3      | TDO      | Pin 21            | GPIO9    | SPI0_MISO     |
| 4      | TMS      | Pin 24            | GPIO8    | SPI0_CE0      |
| 5      | GND      | Pin 25            | GND      | —             |
| 6      | VCC      | Pin 26            | GPIO7    | SPI0_CE1      |

**Warning**: P1 pin 6 is VCC (3.3V). In the current wiring it connects to RPi pin 26 (GPIO7/SPI0_CE1). This is a signal pin being used as a reference, not a power connection. Verify your wiring before powering on.

## Step 4: Connect Cables to the Acorn

1. Plug the P1 Pico-EZmate connector into the Acorn's **P1** (JTAG) socket.
2. Plug the P2 Pico-EZmate connector into the Acorn's **P2** (Serial/GPIO) socket.
3. Route the cables so they don't obstruct the M.2 connector or the PCIe edge fingers.

## Step 5: Install the M.2 PCIe HAT

1. Mount the M.2 PCIe HAT onto the RPi 5 according to the HAT manufacturer's instructions.
2. Insert the Acorn into the M.2 M-key slot on the HAT. Push firmly until the edge connector is fully seated.
3. Secure with the M.2 retention screw if provided.

## Step 6: Connect the Dupont Headers to the RPi

1. Plug the **P2 header** (UART/GPIO) into RPi header pins 5-10.
2. Plug the **P1 header** (JTAG) into RPi header pins 19-26.
3. Double-check orientation — pin 1 of each header must align with the correct RPi pin.

## Step 7: Boot and Verify PCIe

1. Power on the RPi 5.
2. Check the Acorn appears on the PCIe bus:

```bash
lspci
```

Expected output should include:

```
0001:01:00.0 Processing accelerators: Squirrels Research Labs Acorn CLE-215+
```

If the Acorn doesn't appear:
- Check the M.2 connector is fully seated
- Verify the M.2 HAT's FPC cable is connected to the RPi's PCIe connector
- Try `lspci -vvv` for detailed diagnostics
- Check `dmesg | grep -i pci` for errors

## Step 8: Test JTAG Programming

Unload the SPI kernel modules (they conflict with the JTAG GPIO pins) and program a test bitstream:

```bash
# Unload SPI modules that claim GPIO7-11
sudo rmmod spidev spi_bcm2835

# Program using GPIO bitbang JTAG
# Pin order: TDI(GPIO10):TDO(GPIO9):TCK(GPIO11):TMS(GPIO8)
openFPGALoader --cable linuxgpiod_bitbang --pins 10:9:11:8 <bitstream.bit>
```

On RPi 5 with RP1 PIO support (faster, when available):

```bash
openFPGALoader -c rp1pio --pins 10:9:11:8 <bitstream.bit>
```

If programming succeeds, you should see output ending with `Done` and `done 1`.

## Step 9: Test UART and GPIO

1. Stop the serial console service:

```bash
sudo systemctl stop serial-getty@ttyAMA0
sudo systemctl mask serial-getty@ttyAMA0
```

2. Program the GPIO loopback bitstream:

```bash
rmmod spidev spi_bcm2835
openFPGALoader --cable linuxgpiod_bitbang --pins 10:9:11:8 gpio-loopback-acorn.bit
```

3. Verify UART — the loopback design echoes inverted serial data. Use a serial terminal:

```bash
stty -F /dev/ttyAMA0 115200 raw -echo
echo "test" > /dev/ttyAMA0
# Read back (inverted bytes expected)
```

4. Verify GPIO — test the spare GPIO pins (J5→GPIO3, H5→GPIO4):

```bash
# Drive GPIO3 high, read GPIO4 (loopback should invert)
gpioset gpiochip0 3=1
gpioget gpiochip0 4
# Expected: 0 (inverted)
```

5. Program the PMOD Pin ID bitstream for definitive pin verification:

```bash
openFPGALoader --cable linuxgpiod_bitbang --pins 10:9:11:8 pmod-pin-id-acorn.bit
```

Each pin should transmit its FPGA ball name at 1200 baud:
- GPIO14 should receive "K2" (serial TX)
- GPIO15 should receive "J2" (serial RX)
- GPIO3 should receive "J5" (spare GPIO 0)
- GPIO4 should receive "H5" (spare GPIO 1)

## Step 10: Test PCIe Bitstream

1. Program a PCIe-enabled bitstream:

```bash
openFPGALoader --cable linuxgpiod_bitbang --pins 10:9:11:8 pcie-acorn.bit
```

2. Trigger a PCIe rescan:

```bash
echo 1 > /sys/bus/pci/rescan
```

3. Verify the FPGA appears as a PCIe device:

```bash
lspci | grep -i xilinx
```

Expected: a device with Xilinx vendor ID `10ee`.

## Troubleshooting

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| Acorn not on PCIe | M.2 not seated, FPC cable loose | Reseat M.2, check FPC |
| JTAG programming fails | SPI modules loaded, wrong pins | `rmmod spidev spi_bcm2835`, verify pin order |
| No UART output | serial-getty holding port, wrong baud | Mask serial-getty, use 115200 |
| GPIO pins don't respond | Cable wired incorrectly | Check Pico-EZmate pin order with multimeter |
| PCIe device not appearing after programming | Need PCIe rescan | `echo 1 > /sys/bus/pci/rescan` |

## References

- Board spec: [acorn-cle215.md](acorn-cle215.md)
- Pin mapping: [acorn-cle215-pinmap.md](acorn-cle215-pinmap.md)
- LiteX Acorn wiki: <https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215>
- Molex Pico-EZmate cable: <https://www.digikey.fr/en/products/detail/molex/0369200601/10233018>
