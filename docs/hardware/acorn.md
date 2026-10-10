\[[top](./README.md)\] \[[pinmap](./acorn-pinmap.md)\] \[[wiring](./acorn-pinmap.md)\] \[[pcie programming](./acorn-pcie-programming.md)\] \[[litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py)\]

# Sqrl Acorn CLE-215+ / LiteFury

The Sqrl Acorn CLE-215+ is an M.2 form factor PCIe FPGA accelerator card, pin-compatible with the [NiteFury and LiteFury](https://github.com/RHSResearchLLC/NiteFury-and-LiteFury) boards. In the fpgas.online infrastructure it has two setups: on a Raspberry Pi 5 through a Waveshare HAT (Welland), and on a Compute Blade with a CM4 or CM5 (PS1). Either way JTAG (P1) and the UART and spare GPIOs (P2) reach the host's GPIO pins through adapted Pico-EZmate cables. How each setup is wired is in [`docs/wiring/acorn/wiring.toml`](../wiring/acorn/wiring.toml), which fpgas-verify reads.

See [acorn-pinmap.md](acorn-pinmap.md) for the full RPi GPIO pinmap.

## Installing the Acorn Packages

Add the fpgas.online APT repository first ([fpgas-verify: installing it](../verify/installing.md#installing)), then on the Acorn's Pi 5 host:

```bash
sudo apt install fpgas-online-acorn
```

| Package | Version scheme | Installs |
|---------|----------------|----------|
| `fpgas-online-acorn` | `X.Y.postN` from `git describe` (e.g. `0.0.post576`) | installs everything below to check an Acorn, and turns the boot check (`fpgas-verify.service`) on for it |
| `fpgas-online-acorn-tools` | `X.Y.postN` | the Acorn's module of `fpgas_online_verify` (`suite.py`, `check.py`, `bist.py`, `links.py`, `setup.py`, `spi_flash.py`, `uartbone_link.py`, and `data/wiring.toml` and `data/expected.toml`), `/usr/bin/fpgas-acorn-verify` and `/usr/bin/fpgas-acorn-flash`; with openFPGALoader for the P1 JTAG check (recommending `raspi-utils-core`, whose `pinctrl` puts the JTAG pins back after it and drives the Pi's side of J5/H5; Raspberry Pi OS only), and `python3-serial` for the P2 UART check |
| `fpgas-online-acorn-bitstreams` | pinned release date + commit (e.g. `20260923+ge48a750c8303`) | `/usr/share/fpgas-online/acorn-pcie/images/`: `manifest.json`, and for each of `cle-215p` / `cle-101` the golden (`0x000000`) and operational (`0x400000`) flash images, the operational `.bit`, and the CSR maps |
| `fpgas-online-verify` | `X.Y.postN` | `fpgas-verify` and its unit |

The tools package depends on one exact bitstreams version. Which release that is comes from [`packaging/acorn-pcie/release.toml`](../../packaging/acorn-pcie/release.toml), and a new release reaches hosts only when a reviewed PR moves that pin. Every package is built, and its install rules are checked in clean Debian bookworm and trixie, by [`collect-bitstreams.yml`](../../.github/workflows/collect-bitstreams.yml).

At boot the check finds the Acorn on PCI (Xilinx `10ee` or SQRL `1e24`), works out which setup the host is
from its device-tree model, and runs these tests ([fpgas-verify: what each board's check tests](../verify/tests.md#what-each-boards-check-tests) has the
details). It never writes the flash and never reconfigures the FPGA, and a fault in one test does not stop
the others:

| Test | Checks |
|---|---|
| `pcie-link` | the link is 5.0 GT/s x1 ([`expected.toml`](../wiring/acorn/expected.toml)) |
| `pcie-bar0` | over BAR0: the operational build of the installed release runs, the flash identifies itself, the device DNA reads, and the XADC temperature and voltages are in range |
| `rp1-pio` | Pi 5 / CM5 only: `/dev/pio0` opens, for openfpgaloader-rp1pio; when it does not, the `rp1_fw` / `rp1_pio` modules and the kernel's reason are reported (`failed to contact RP1 firmware` on bootloader 2024/11/05) |
| `jtag` | over P1: the whole IDCODE, decoded into `idcode_version`, `idcode_part_number`, `idcode_manufacturer_id`, `idcode_manufacturer` and `idcode_device`, must be the variant's part in any silicon version ([fpgas-verify: the JTAG IDCODE](../verify/idcode-and-dna.md#the-jtag-idcode)); and the device DNA, which must be BAR0's (this proves TDI) |
| `flash` | both 4 MiB slots hold the release's images |
| `ddr` | the BIOS console read out, then the DRAM BIST over the whole DRAM, two passes: no errors, and write and read at least 1100 MB/s ([`expected.toml`](../wiring/acorn/expected.toml)); p48 measures 1327 / 1350 MB/s |
| `p2-uart` | the UARTBone bridge on P2 at 1200 and 921600 baud: identifier, DNA and XADC, as over BAR0 |
| `p2-serial` | both setups: J2 and K2 borrowed with `p2_serial` and tested both ways, the switch's own timeout, and the UARTBone answering again |
| `scratch` | the `ctrl` scratch register written and read back over BAR0 and over P2 |
| `p2-gpio` | Pi 5 setup only: J5 and H5 driven from the FPGA and read on GPIO3/GPIO4, then driven from the Pi and read on the FPGA |
| `power-cycle` (opt-in: `power-cycle-check = on`, set on the fpgas.online fleet) | the FPGA restarted since the last check (it was configured, or its SoC reset), that is, it did not keep its state across the Pi's restart ([fpgas-verify: the Acorn's power-cycle check](../verify/acorn-power-cycle.md#the-acorns-power-cycle-check-opt-in)) |

Where each setup's wires land on the host:

| Setup | JTAG `--pins` | openFPGALoader cable | J2 / K2 | J5 / H5 |
|---|---|---|---|---|
| Pi 5 + Waveshare HAT | `10:9:11:8` | `libgpiod` (the RP1's GPIO chip, linked as `/dev/gpiochip0`) | GPIO14 / GPIO15 | GPIO3 / GPIO4 |
| Compute Blade, CM4 | `2:3:4:14` | `libgpiod` (the BCM2711's GPIO chip; a CM4 has no RP1, so no `rp1pio`) | GPIO14 / GPIO15 | cut |
| Compute Blade, CM5 | `2:3:4:14` | `libgpiod` (the RP1's GPIO chip) | GPIO14 / GPIO15 | cut |

On the Blade J2 shares GPIO14 with TMS through 470 Ω, so after the JTAG test GPIO14 goes back to its UART
function. On a CM5 with kernel 6.18 the kernel does not lend GPIO14 while the serial port has it, so with the
serial port on the `jtag` test fails saying so, without running openFPGALoader
([#127](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)). The PCI slot and IDs, the device DNA, the flash's identity and the sha256 of each slot are what
`changed` compares, so a flash rewritten since the last run (by `fpgas-acorn-flash write`, say) is fatal
until `sudo fpgas-verify --update`. The PCIe transfer rate (DMA) is not measured yet.

**Check the board now:**

```bash
sudo fpgas-verify                                    # what the boot unit runs
sudo fpgas-acorn-verify --no-publish --report -      # the Acorn only, the JSON report on stdout
```

The result is `pass` only when every test passes. A board running its golden image (the operational slot did
not boot) fails. A kernel driver bound to the board (`litepcie.ko`) is unbound for the check, when a test asked for
uses BAR0, and bound again afterwards (`fpgas-acorn-flash` instead refuses a board a driver is bound to). A board still on SQRL's factory
image, or the vendor XDMA sample, is `fail` with a reason starting `unconverted:`: it does not run the
fpgas.online image, so it cannot be offered to users until `fpgas-acorn-flash` converts it (the XDMA sample can
also be a NeTV2 on PCIe, which that tool does not apply to). Its PCIe link, the RP1 PIO check and P1 JTAG are
still tested: on a card on the XDMA sample only when the host is set up for an Acorn, and then `jtag` names the
variant from the FPGA's IDCODE, which the sample's PCI IDs do not say. A PCIe Screamer (PCILeech, `10ee:0666`) or a stock
Xilinx XDMA design (most likely a PicoEVB: `10ee:7021` with the Xilinx default subsystem, told apart
from an old fpgas.online build by its XDMA class code and BAR2) is named, and fails: the check has no test design for it ([issue 238](https://github.com/fpgas-online/fpgas.online-test-designs/issues/238)). Any
other PCIe FPGA whose design the check does not recognise is `fail` too. A Pi with no Acorn is `missing`:
fatal, since the host was set up for one.

**When a check fails**, `sudo apt install fpgas-online-acorn-debug`. It brings openFPGALoader for loading the `.bit` over GPIO JTAG ([below](#via-gpio-jtag-openfpgaloader--what-the-fleet-uses)), which is how a board still on SQRL's factory image is converted, and `python3-serial` for `fpgas-acorn-flash --uart`:

```bash
sudo fpgas-acorn-debug detect       # the Acorn-family endpoints on PCI
sudo fpgas-acorn-debug identify     # the running build and the flash's part, JEDEC ID and unique ID, read live
```

For the fpgas.online openFPGALoader build (with the RP1 PIO JTAG cable and SPI flash info), add the [fpgas.online-fpga-tools repository](https://github.com/fpgas-online/fpgas.online-fpga-tools#debian-packages-bookworm-trixie-sid-arm64-armhf) **before** installing. Otherwise apt installs Debian's own package (bookworm 0.10.0, trixie 0.13.1). Adding the repository afterwards does not replace it; run `sudo apt install openfpgaloader-fpgasonline` to switch. Fleet Pis already get the patched `openfpgaloader-fpgasonline-git` from the infra role.

**Use the flash tool** against the installed images (CLE-215+ shown; use `acorn-cle-101-*` for a CLE-101):

```bash
sudo fpgas-acorn-flash id
sudo fpgas-acorn-flash verify /usr/share/fpgas-online/acorn-pcie/images/acorn-cle-215p-sqrl_acorn_operational.bin 0x400000
```

Writing the flash, and converting a board that still runs the factory image, are covered in [acorn-pcie-programming.md](acorn-pcie-programming.md). After writing it, run `sudo fpgas-verify --update`. `fpgas-acorn-flash` reaches the flash through the fpgas.online SoC's PCIe BAR0, so it needs that SoC to be running already. By default it expects the SoC at `0001:01:00.0`; pass `--bdf` for another address, or `--uart PORT` to use the UART bridge instead.

## Key Specifications

| Parameter        | Value                            |
| ---------------- | -------------------------------- |
| FPGA             | Xilinx Artix-7 XC7A200T-FBG484-3 |
| Package          | FBG484 (484-ball BGA)            |
| Logic cells      | 215,360                          |
| CLB flip-flops   | 269,200                          |
| DSP slices       | 740                              |
| Block RAM        | 13,140 Kib                       |
| GTP transceivers | 4 (up to 6.6 Gb/s each)          |
| DDR3 SDRAM       | 1 GiB (MT41K512M16, 16-bit); 512 MiB (MT41K256M16) on the CLE-101 |
| SPI Flash        | S25FL256S (256 Mbit, quad SPI)   |
| PCIe             | Gen2 x4 (M.2 M-key)              |
| Form factor      | M.2 2280                         |
| Power            | Via M.2 / mPCIe slot (3.3V)      |
| Process          | 28 nm HPL                        |

Source: [LiteX sqrl_acorn.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py)

## Compatible Boards

All boards share the same PCB layout and pin assignments. The LiteX platform file `sqrl_acorn.py` works for all variants — change only the device string.

| Board          | FPGA            | Speed Grade | DDR3                  | PCIe    |
| -------------- | --------------- | ----------- | --------------------- | ------- |
| LiteFury       | XC7A100T-FBG484 | -2          | 512 MiB (MT41K256M16) | Gen2 x4 |
| NiteFury       | XC7A200T-FBG484 | -2          | 1 GiB (MT41K512M16)   | Gen2 x4 |
| Acorn CLE-101  | XC7A100T-FBG484 | -2          | 512 MiB (MT41K256M16) | Gen2 x4 |
| Acorn CLE-215  | XC7A200T-FBG484 | -2          | 1 GiB (MT41K512M16)   | Gen2 x4 |
| Acorn CLE-215+ | XC7A200T-FBG484 | -3          | 1 GiB (MT41K512M16)   | Gen2 x4 |

Source: [NiteFury and LiteFury](https://github.com/RHSResearchLLC/NiteFury-and-LiteFury), [LiteX Acorn CLE-215 wiki](https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215)

The CLE-215+ is the RHSResearchLLC NiteFury (CLE-215) in the faster -3 speed grade; both have 1 GiB of DDR3. The designs here build the `cle-215` variant for both the CLE-215 and the NiteFury, with the same DDR3 part.

## PCIe Interface

| Parameter       | Value                                    |
| --------------- | ---------------------------------------- |
| Link            | Gen2 x4 (4-lane GTP transceivers)        |
| Connector       | M.2 M-key                                |
| Reference clock | Differential (FPGA pins F6/E6)           |
| Reset           | LVCMOS33 (FPGA pin J1, internal pull-up) |
| Vendor:Device   | `1e24:021f` Squirrels Research Labs "Acorn CLE-215+" with the factory (mining) firmware in flash; `1e24:0101` for a CLE-101; `10ee:7011` (Xilinx) once a LiteX/Vivado design is in flash |

On RPi 5, the Acorn connects via an mPCIe HAT and appears on PCIe bus `0001:01:00.0` (the RP1 south bridge is `0002:01:00.0`). Reconfiguring the FPGA over JTAG while that endpoint is enumerated crashes a Pi 5 host — detach it first, see [acorn-pcie-programming.md](acorn-pcie-programming.md#detach-the-pcie-endpoint-before-any-jtag-reconfiguration).

## Clock

| Signal         | FPGA Pins | Standard    | Frequency |
| -------------- | --------- | ----------- | --------- |
| System clock   | J19 / H19 | DIFF_SSTL15 | 200 MHz   |
| PCIe ref clock | F6 / E6   | —           | 100 MHz   |

## User LEDs

| LED | FPGA Pin |
| --- | -------- |
| 0   | G3       |
| 1   | H3       |
| 2   | G4       |
| 3   | H4       |

## Serial (UART)

Available on the P2 connector (active low accent LEDs double as serial adapter pins):

| Signal | FPGA Pin |
| ------ | -------- |
| RX     | J2       |
| TX     | K2       |

## SPI Flash

| Signal | FPGA Pin |
| ------ | -------- |
| CS_n   | T19      |
| MOSI   | P22      |
| MISO   | R22      |
| WP     | P21      |
| HOLD   | R21      |

Flash part: Spansion S25FL256S (256 Mbit). Supports multiboot with separate fallback and operational bitstream regions.

## DDR3 SDRAM

One 16-bit Micron DDR3 chip: MT41K512M16 (8 Gbit, 1 GiB) on the CLE-215/215+, MT41K256M16 (4 Gbit,
512 MiB) on the CLE-101. Two byte lanes, each with
its own DQS pair and DM. Uses the 7-series native DDR PHY (A7DDRPHY). CS_N is not wired to the FPGA.
Address, command, CLK and RESET_N are in bank 15; DQ, DQS and DM in bank 16, whose inputs use the
internal VREF of 0.75 V (per Vivado's IO report and bit2fasm of its image). The platform's
`set_property INTERNAL_VREF 0.750 [get_iobanks 34]` names a bank the DDR3 does not use.

| Signal     | FPGA pins (bit 0 first)                                         | IO standard                      |
| ---------- | --------------------------------------------------------------- | -------------------------------- |
| A[15:0]    | M15 L21 M16 L18 K21 M18 M21 N20 M20 N19 J21 M22 K22 N18 N22 J22 | SSTL15                           |
| BA[2:0]    | L19 J20 L20                                                     | SSTL15                           |
| RAS_N      | H20                                                             | SSTL15                           |
| CAS_N      | K18                                                             | SSTL15                           |
| WE_N       | L16                                                             | SSTL15                           |
| DM[1:0]    | A19 G22                                                         | SSTL15                           |
| DQ[15:0]   | D19 B20 E19 A20 F19 C19 F20 C18 E22 G21 D20 E21 C22 D21 B22 D22 | SSTL15, IN_TERM=UNTUNED_SPLIT_50 |
| DQS_P[1:0] | F18 B21                                                         | DIFF_SSTL15                      |
| DQS_N[1:0] | E18 A21                                                         | DIFF_SSTL15                      |
| CLK_P      | K17                                                             | DIFF_SSTL15                      |
| CLK_N      | J17                                                             | DIFF_SSTL15                      |
| CKE        | H22                                                             | SSTL15                           |
| ODT        | K19                                                             | SSTL15                           |
| RESET_N    | K16                                                             | LVCMOS15                         |

Source: `_io["ddram"]` in [LiteX sqrl_acorn.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py)
(litex-boards dc89d11, as pinned in `uv.lock`). The DDR memory test built from these pins passes memtest on
pi-sw2-p48 (2026-09-29).

## Programming

### Via GPIO JTAG (openFPGALoader) — what the fleet uses

P1 is wired to the Pi's SPI0 pins; openFPGALoader bit-bangs JTAG through libgpiod
(about 16 s for a full XC7A200T bitstream). The load goes to SRAM only and is
lost at power cycle, which is what makes it safe to experiment with.

On a Raspberry Pi 5 with the M.2 HAT (the card is at `0001:01:00.0`; P1's TDI, TDO, TCK, TMS are GPIO 10, 9,
11, 8, which is `--pins 10:9:11:8`):

```bash
echo 1 | sudo tee /sys/bus/pci/devices/0001:01:00.0/remove   # MUST detach the endpoint first on a Pi 5
sudo ln -sfn /dev/gpiochip15 /dev/gpiochip0                   # Pi 5 only: the libgpiod cable opens gpiochip0
openFPGALoader --cable libgpiod --pins 10:9:11:8 <bitstream.bit>
```

On a Compute Blade the address is the one `lspci -D` shows (`0000:01:00.0` on a CM4, `0001:01:00.0` on a
CM5) and the pins are `--pins 2:3:4:14`. Detach the endpoint first there too (the CM5 has the Pi 5's BCM2712
root complex; we have not tried a CM4 without it). `/dev/gpiochip0` is already the header's chip on a CM4; on
a CM5 run `gpiodetect` and use the chip it lists as `pinctrl-rp1` (it was `gpiochip0` under kernel 6.18; a
Pi 5 under 6.12 had `gpiochip15`), so the `ln` line above may not apply. The differences are listed in
[acorn-pcie-programming.md](acorn-pcie-programming.md#on-a-compute-blade). **Not yet run by us on a Compute
Blade with these packages.**

Pin order, the Pi 5 `gpiochip15` trap, the PCIe detach rule and the
`overlayroot=tmpfs` gotcha are all in [acorn-pinmap.md](acorn-pinmap.md).
Prebuilt Vivado bitstreams for every test design and Acorn variant are on the
`vivado-bitstreams-v0.0-496-gf162f60` release — see
[acorn-pcie-programming.md](acorn-pcie-programming.md#prebuilt-vivado-bitstreams).

### Via JTAG (OpenOCD + FT232H)

Alternative for a bench setup — uses an FT232H USB adapter with a BSCAN_SPI proxy bitstream:

```bash
openocd -f openocd_xc7_ft232.cfg -c "init; pld load 0 <bitstream>; exit"
```

### Via SPI Flash

Flash a persistent bitstream using OpenOCD or openFPGALoader. The S25FL256S supports multiboot with fallback. `openFPGALoader --write-flash` does **not** work over the GPIO JTAG wiring (the open-source spiOverJtag bridge never toggles CCLK after configuration); see [acorn-pcie-programming.md](acorn-pcie-programming.md).

### Via PCIe (LiteX)

LiteX provides PCIe-based programming via `litepcie_util` when a LiteX bitstream with PCIe support is already loaded. Which Welland boards run the fpgas.online SoC is in the [current verify results](../verify/current-results.md#current-results) and [#53](https://github.com/fpgas-online/fpgas.online-test-designs/issues/53).

## Self-test registers

The operational image of the fpgas.online Acorn SoC (`designs/acorn-pcie/`) lets a host check the DRAM and
every P2 pin with no driver and no BIOS, over PCIe BAR0 or the P2 UARTBone. The golden image has none of
this. Every CSR module sits at a fixed address (`csr_map` in `acorn_pcie_soc.py`; `tests/test_acorn_pcie_csr_map.py`
fails if one moves). Each release ships each image's `csr.json` and `csr.csv` beside it, and
`fpgas-online-acorn-bitstreams` installs them. `designs/acorn-pcie/host/selftest.py` runs all of it from the Pi,
through the same code as the boot check's `ddr`, `p2-serial` and `p2-gpio` tests
([`boards/acorn/bist.py`](../../verify/src/fpgas_online_verify/boards/acorn/bist.py)), with the pins from
`wiring.toml`. From a checkout it finds that code in `verify/src`; otherwise it needs `fpgas-online-acorn-tools`.

| Module | Base | What it is |
|---|---|---|
| `ddrphy` | `0xf0007800` | LiteDRAM's PHY (calibration) |
| `p2_gpio` | `0xf0008000` | J5 (bit 0) and H5 (bit 1): `oe` +0x0, `in` +0x4, `out` +0x8 |
| `sdram` | `0xf0008800` | LiteDRAM's controller (DFI) |
| `dram_generator` | `0xf0009000` | BIST pattern writer |
| `dram_checker` | `0xf0009800` | BIST pattern checker |
| `p2_serial` | `0xf000a000` | the J2/K2 serial/GPIO switch |

### DRAM BIST

`dram_generator` and `dram_checker` have the same registers, at the same offsets. The checker adds `errors`.

| Offset | Register | Meaning |
|---|---|---|
| +0x00 | `reset` | any write resets the core |
| +0x04 | `start` | any write starts a pass |
| +0x08 | `done` | 1 when the pass has finished |
| +0x0c | `base` | first byte address |
| +0x10 | `end` | end of the range, used only to wrap random addresses (`end - base` a power of two) |
| +0x14 | `length` | bytes to write or check |
| +0x18 | `random` | bit 0: PRBS data (else a counter); bit 1: random addresses |
| +0x1c | `ticks` | sys clock cycles the pass took |
| +0x20 | `errors` | checker only: words that did not match |

A run: write `reset`, `base`, `end`, `length` and `random`, write `start`, wait for `done`, read `ticks`.
Run the generator, then the checker over the same range with the same `random`. Bandwidth is
`length / (ticks / sys clock)`; the sys clock is `CONFIG_CLOCK_FREQUENCY` in `csr.json` (100 MHz).

The data is a 31-bit value per 128-bit word, repeated and cut off at 128 bits (four copies and the low 4 bits
of a fifth): a PRBS31 value with `random` bit 0 set, otherwise a counter of the words written. `reset`
restarts both, so every run of one pattern writes the same data from its `base`. The check counts words that
differ, not bits.

`base`, `end` and `length` are as wide as a DRAM byte address, so the whole DRAM takes two halves. To catch a
dead top address bit (or an image for twice the DRAM the board has), write both halves before checking
either, with different patterns in each: with the same pattern, a high half that lands on the low one writes
the same data there and every check passes. `designs/acorn-pcie/host/selftest.py` does two passes, PRBS low and
counter high, then the other way round, so each half gets both patterns. That does not guarantee every bit
is written as both 0 and 1: the counter's top bits stay 0 over a half, so those bits see only the PRBS value
and 0.

The BIOS sets the DRAM up after printing its banner on the crossover UART, and stops once that console is full
and nobody reads it ([#47](https://github.com/fpgas-online/fpgas.online-test-designs/pull/47)). On a board
nobody has attached to, the DRAM is then never initialised and every word of a BIST pass is an error. Read the
console out first (`uart_xover_rxempty` at `0xf0001028`, `uart_xover_rxtx` at `0xf0001020`, where each read
takes one character) until it is quiet; that also gives the BIOS's calibration and memtest output.

### P2 serial/GPIO switch

J5 and H5 are always GPIOs (`p2_gpio`). J2 and K2 carry the UARTBone, so to check them in both directions a
host borrows them with `p2_serial`. Bit 0 is J2, bit 1 is K2.

| Offset | Register | Meaning |
|---|---|---|
| +0x00 | `mode` | 0: serial link (reset). 1: GPIOs |
| +0x04 | `oe` | output enables in GPIO mode; 0 = input |
| +0x08 | `in` | the two balls as the FPGA sees them, in either mode |
| +0x0c | `out` | output values in GPIO mode |
| +0x10 | `timeout` | ms after the last write to `mode` before GPIO mode ends by itself; 0 = never; 5000 at reset |

While `mode` is 1 the UARTBone sees an idle line and is held in reset, as by a break: any half-received
command is dropped and the baud rate returns to 1200. Switch over BAR0, not over the UARTBone: switching over
the UARTBone cuts the link that sent the write, until `timeout` brings it back. Before writing `mode` back to
0, set the Pi's GPIO14 back to its UART function, or the UART sees the level the Pi left on J2. After that,
reopen the link at 1200 baud (break, probe, raise the rate), as at any other start.

On a Compute Blade, J2 shares GPIO14 with JTAG TMS through a 470 Ω resistor, so do not run JTAG while J2 is a
GPIO.

## Host Inventory

### Welland Site ([site-welland.md](site-welland.md))

Seven Acorn CLE-215+ hosts, all Raspberry Pi 5, on the S3300 switch (switch
index 2) under the [VLAN-per-port scheme](site-welland.md#network-topology):
hostname `pi-sw2-p<port>`, IP `10.21.2.<port>`. Their MACs and revision codes
are in [site-welland.md](site-welland.md#sqrl-acorn-cle-215).
What each board runs and whether its JTAG and P2 links pass is in the
[current verify results](../verify/current-results.md#current-results); moving them all to the
pinned release is
[#53](https://github.com/fpgas-online/fpgas.online-test-designs/issues/53).

Hosts: pi-sw2-p29, p37, p43, p44, p46, p47 and p48. All run the shared NFS root
(`overlayroot=tmpfs`) and have `/dev/ttyAMA0` enabled with the kernel console on
`ttyAMA10`; p29 and p43–p48 also have an ov5647 camera.

### PS1 Site ([site-ps1.md](site-ps1.md))

Four Compute Blades (val2 gateway, flat `10.21.0.1xx` addressing).

| Host | Port | IP          | Module               | Flash contents                                   | JTAG (P1)                     | P2 serial                   |
| ---- | ---- | ----------- | -------------------- | ------------------------------------------------ | ----------------------------- | --------------------------- |
| pi14 | e14  | 10.21.0.114 | CM4 Rev 1.1 4 GB     | Sqrl Acorn CLE-101 `1e24:0101`                   | no response — P1 unmated      | untested                    |
| pi16 | e16  | 10.21.0.116 | CM5 Lite Rev 1.0 8 GB| Sqrl Acorn CLE-101 `1e24:0101`                   | no response — P1 unmated      | untested                    |
| pi18 | e18  | 10.21.0.118 | CM4 Rev 1.1 4 GB     | none — M.2 slot empty                            | n/a                           | n/a                         |
| pi20 | e20  | 10.21.0.120 | CM5 Lite Rev 1.0 8 GB| XC7A100T design `10ee:7011`, DNA `0x0028e5c45e304854` | OK (openFPGALoader 0.13.1) | OK, crossover present       |

The factory PCI ID on pi14/pi16 identifies these boards as Sqrl Acorn CLE-101
(the LiteFury's PCB family, XC7A100T, 512 MB).

### Deployment Summary

| Variant                  | FPGA          | DDR3   | Welland (deployed) | Welland (pending) | PS1 (deployed) | PS1 (pending)        |
| ------------------------ | ------------- | ------ | ------------------ | ----------------- | -------------- | -------------------- |
| Acorn CLE-215+           | XC7A200T (-3) | 1 GB   | ×7                 | —                 | —              | —                    |
| LiteFury / Acorn CLE-101 | XC7A100T (-2) | 512 MB | —                  | —                 | ×3             | ×1 host (pi18) empty |

No USB serial devices on any host — JTAG and UART are connected via adapted Pico-EZmate cables to the RPi GPIO header (see [acorn-pinmap.md](acorn-pinmap.md)). PCIe is via the M.2 HAT.

## LiteX Support

The LiteX target (`litex_boards/targets/sqrl_acorn.py`) provides:

- PCIe Gen2 x4 endpoint with DMA
- DDR3 SDRAM controller (LiteDRAM)
- SPI Flash access (LiteSPI)
- ICAP for warm-boot / multiboot
- Optional Ethernet via PCIe bridge

Build example:

```bash
python3 -m litex_boards.targets.sqrl_acorn --build
```

## References

- LiteX platform: [sqrl_acorn.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py)
- LiteX target: [sqrl_acorn.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/targets/sqrl_acorn.py)
- LiteX wiki: [Use LiteX on the Acorn CLE-215](https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215)
- OpenOCD flashing: [NiteFury/Acorn flashing guide](https://github.com/Gbps/nitefury-openocd-flashing-guide)
- Running Linux: [Acorn CLE-215+ blog post](https://spoolqueue.com/new-design/fpga/migen/litex/2020/08/11/acorn-cle-215.html)
