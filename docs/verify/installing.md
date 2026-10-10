# fpgas-verify: installing it

You have a Raspberry Pi with an FPGA board attached and want to install `fpgas-verify` for that board.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## Installing

```bash
# The fpgas.online apt repository (bookworm or trixie).
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://apt.fpgas.online/apt.gpg | sudo tee /etc/apt/keyrings/apt.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/apt.list

# fpgas.online's openFPGALoader; add it before installing. A NeTV2 on a Pi 5 needs it. Elsewhere Debian's own
# works from 0.13.0 on (trixie), but bookworm's (0.10.0) is too old: it cannot read the device DNA.
curl -fsSL https://fpgas.online/fpgas.online-fpga-tools/fpgas.online-fpga-tools.gpg \
  | sudo tee /etc/apt/keyrings/fpgas.online-fpga-tools.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/fpgas.online-fpga-tools.gpg] https://fpgas.online/fpgas.online-fpga-tools/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/fpgas.online-fpga-tools.list

sudo apt update
sudo apt install fpgas-online-arty         # the package for your board: see the table
sudo apt install fpgas-online-arty-debug   # optional: fpgas-arty-debug, for when the check fails
```

Install **one** of these. They conflict, so a host is never set up for two boards by accident.

| Package | Installs |
|---|---|
| `fpgas-online-acorn` | everything to check a Sqrl Acorn CLE-215+ / CLE-101 (and LiteFury), and turns the boot check on for it |
| `fpgas-online-arty` | everything to check a Digilent Arty A7-35T, and turns the boot check on for it |
| `fpgas-online-netv2` | everything to check a Kosagi NeTV2 (XC7A35T or XC7A100T), and turns the boot check on for it |
| `fpgas-online-fomu` | everything to check a Fomu EVT, and turns the boot check on for it |
| `fpgas-online-tt-fpga` | everything to check a TT FPGA Demo Board, and turns the boot check on for it |
| `fpgas-online-all-boards` | everything to check any of the boards, and turns the boot check on for whichever is found |
| `fpgas-online-multi-board` | turns the boot check on for whichever board is found, of those whose `fpgas-online-<board>-tools` you also install |

* `fpgas-online-<board>-debug` adds `fpgas-<board>-debug` and the tools for the tests the boot check skips.
* Installing does not run the check. It runs at the next boot, or when you run it.
* The packages are `Architecture: all`: they install on Raspberry Pi OS and on an x86 machine alike. The NeTV2
  and the Acorn need a Pi's GPIO header, and so does the Fomu EVT, which sits on it; the Arty and TT FPGA board
  need only USB.
* Versions are `0.0.postN` from `git describe` (for example `0.0.post771`). Each package depends on the others'
  exact version, so `sudo apt upgrade` moves them together.
* What each board's packages pull in is listed [below](#what-each-boards-packages-install); the Acorn's are on
  [its page](../hardware/acorn.md#installing-the-acorn-packages).
* CI builds every package and checks its install rules in clean bookworm and trixie
  ([`collect-bitstreams.yml`](../../.github/workflows/collect-bitstreams.yml),
  [`build_debs.py`](../../packaging/debs/build_debs.py), [`install_test.sh`](../../packaging/debs/install_test.sh)).

## What each board's packages install

### Arty packages

| Package | Installs |
|---------|----------|
| `fpgas-online-arty` | installs everything below to check an Arty, and turns the boot check (`fpgas-verify.service`) on for it |
| `fpgas-online-arty-tools` | the Arty's module of `fpgas_online_verify`, and `fpgas-arty-verify`; with `python3-serial`, openFPGALoader, `python3-libgpiod` (the PMOD HAT scan) and `iproute2`/`ping`/`arping` (the Ethernet test, which runs as root), and recommending `raspi-utils-core` (`pinctrl`, which puts back the Pi's SPI/UART/I2C pin functions after the scan; Raspberry Pi OS only) |
| `fpgas-online-arty-bitstreams` | the Arty A7-35T test bitstreams built by the same commit's CI, in `/usr/share/fpgas-online/arty/bitstreams/` |
| `fpgas-online-verify` | `fpgas-verify`, the unit, and the host test scripts |

Without the [fpgas.online-fpga-tools repository](https://github.com/fpgas-online/fpgas.online-fpga-tools#debian-packages-bookworm-trixie-sid-arm64-armhf) apt installs Debian's `openfpgaloader`. That works for the Arty from 0.13.0 on (trixie's), because the check reads the device DNA with `--read-dna`. Bookworm's (0.10.0) is too old, so on bookworm `fpgas-online-arty` installs only with the repository added.

### NeTV2 packages

| Package | Installs |
|---------|----------|
| `fpgas-online-netv2` | installs everything below to check a NeTV2, and turns the boot check (`fpgas-verify.service`) on for it |
| `fpgas-online-netv2-tools` | the NeTV2's module of `fpgas_online_verify`, and `fpgas-netv2-verify`; with `python3-serial`, openFPGALoader and openocd |
| `fpgas-online-netv2-bitstreams` | the XC7A35T and XC7A100T test bitstreams built by the same commit's CI, in `/usr/share/fpgas-online/netv2/bitstreams/` |
| `fpgas-online-verify` | `fpgas-verify`, the unit, and the host test scripts |

On a Raspberry Pi 5 the [fpgas.online-fpga-tools repository](https://github.com/fpgas-online/fpgas.online-fpga-tools#debian-packages-bookworm-trixie-sid-arm64-armhf) is needed: only its openFPGALoader builds have the `rp1pio` cable. They also have the SPI-over-JTAG bridge for the XC7A35T-FGG484, which Debian bookworm's `openfpgaloader` lacks, so on bookworm the flash readback of an XC7A35T board fails without them.

### Fomu packages

| Package | Installs |
|---------|----------|
| `fpgas-online-fomu` | installs everything below to check a Fomu, and turns the boot check (`fpgas-verify.service`) on for it |
| `fpgas-online-fomu-tools` | the Fomu's module of `fpgas_online_verify`, and `fpgas-fomu-verify`; with `python3-serial` and openFPGALoader |
| `fpgas-online-fomu-bitstreams` | the test bitstreams built by the same commit's CI, in `/usr/share/fpgas-online/fomu/bitstreams/` |
| `fpgas-online-verify` | `fpgas-verify`, the unit, and the host test scripts |

### TT FPGA packages

| Package | Installs |
|---------|----------|
| `fpgas-online-tt-fpga` | installs everything below to check a TT FPGA Demo Board, and turns the boot check (`fpgas-verify.service`) on for it |
| `fpgas-online-tt-fpga-tools` | the board's module of `fpgas_online_verify`, and `fpgas-tt-fpga-verify`; with `python3-serial` and `python3-libgpiod` (the PMOD HAT scan), and recommending `micropython-mpremote` and `raspi-utils-core` (`pinctrl`, which puts back the Pi's SPI/UART/I2C pin functions after the scan; Raspberry Pi OS only) |
| `fpgas-online-tt-fpga-bitstreams` | the test bitstreams built by the same commit's CI, in `/usr/share/fpgas-online/tt-fpga/bitstreams/` |
| `fpgas-online-verify` | `fpgas-verify`, the unit, and the host test scripts |

`fpgas-online-tt` is a different package: the TT site's own.
