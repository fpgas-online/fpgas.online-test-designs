# fpgas-verify: installing it

You have a Raspberry Pi with an FPGA board attached and want to install `fpgas-verify` for that board.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## Installing

### What you need

- a Raspberry Pi, or another host running Debian or Raspberry Pi OS bookworm or trixie, with the board attached
- `sudo` on it, and a network that reaches `apt.fpgas.online` and `fpgas.online`

`grep VERSION_CODENAME /etc/os-release` says which release the host runs.

### Steps

**1.** Add the fpgas.online apt repository.

```bash
# The fpgas.online apt repository (bookworm or trixie).
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://apt.fpgas.online/apt.gpg | sudo tee /etc/apt/keyrings/apt.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/apt.list
```

**2.** Add the fpgas.online-fpga-tools repository, before installing. A NeTV2 on a Raspberry Pi 5 needs it, and so
does an Acorn, an Arty or a NeTV2 on bookworm.

```bash
# fpgas.online's openFPGALoader; add it before installing. A NeTV2 on a Pi 5 needs it. Elsewhere Debian's own
# works from 0.13.0 on (trixie), but bookworm's (0.10.0) is too old: it cannot read the device DNA.
curl -fsSL https://fpgas.online/fpgas.online-fpga-tools/fpgas.online-fpga-tools.gpg \
  | sudo tee /etc/apt/keyrings/fpgas.online-fpga-tools.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/fpgas.online-fpga-tools.gpg] https://fpgas.online/fpgas.online-fpga-tools/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/fpgas.online-fpga-tools.list
```

**3.** Install the package for your board, **one** of the table below. They conflict, so a host is never set up
for two boards by accident.

```bash
sudo apt update
sudo apt install fpgas-online-arty         # the package for your board
```

| Package | Installs |
|---|---|
| `fpgas-online-acorn` | everything to check a Sqrl Acorn CLE-215+ / CLE-101 (and LiteFury), and turns the boot check on for it |
| `fpgas-online-arty` | everything to check a Digilent Arty A7-35T, and turns the boot check on for it |
| `fpgas-online-netv2` | everything to check a Kosagi NeTV2 (XC7A35T or XC7A100T), and turns the boot check on for it |
| `fpgas-online-fomu` | everything to check a Fomu EVT, and turns the boot check on for it |
| `fpgas-online-tt-fpga` | everything to check a TT FPGA Demo Board, and turns the boot check on for it |
| `fpgas-online-all-boards` | everything to check any of the boards, and turns the boot check on for whichever is found |
| `fpgas-online-multi-board` | turns the boot check on for whichever board is found, of those whose `fpgas-online-<board>-tools` you also install |

**4.** If you want the debug tool for when the check fails, install the board's `-debug` package too.

```bash
sudo apt install fpgas-online-arty-debug   # fpgas-arty-debug
```

### Check

`fpgas-verify --list` lists the installed boards and the one this host is set up for.

### If it fails

- `apt` cannot find a package: the repository line of step 1 is missing, or `sudo apt update` was not run after it.
- On bookworm, an `openfpgaloader` conflict or a version that is too old: step 2 was done after installing.
  `sudo apt install openfpgaloader-fpgasonline` switches to the repository's build.

### Next

- [Running it](running.md#running-it): run the check now, without waiting for a boot.
- The packages of each board, below.

## Notes

* `fpgas-online-<board>-debug` adds `fpgas-<board>-debug` and the tools for the tests the boot check skips.
* Installing does not run the check. It runs at the next boot, or when you run it.
* The packages are `Architecture: all`: they install on Raspberry Pi OS and on an x86 machine alike. The NeTV2
  and the Acorn need a Pi's GPIO header, and so does the Fomu EVT, which sits on it; the Arty and TT FPGA board
  need only USB.
* Versions are `0.0.postN` from `git describe`. Each package depends on the others'
  exact version, so `sudo apt upgrade` moves them together.
* What each board's packages pull in is listed [below](#what-the-packages-of-each-board-install).

## What the packages of each board install

### Acorn packages

| Package | Version scheme | Installs |
|---|---|---|
| `fpgas-online-acorn` | `X.Y.postN` from `git describe` (e.g. `0.0.post576`) | installs everything below to check an Acorn, and turns the boot check (`fpgas-verify.service`) on for it |
| `fpgas-online-acorn-tools` | `X.Y.postN` | the Acorn's module of `fpgas_online_verify` (`suite.py`, `check.py`, `bist.py`, `links.py`, `setup.py`, `spi_flash.py`, `uartbone_link.py`, and `data/wiring.toml` and `data/expected.toml`), `/usr/bin/fpgas-acorn-verify` and `/usr/bin/fpgas-acorn-flash`; with openFPGALoader for the P1 JTAG check (recommending `raspi-utils-core`, whose `pinctrl` puts the JTAG pins back after it and drives the Pi's side of J5/H5; Raspberry Pi OS only), and `python3-serial` for the P2 UART check |
| `fpgas-online-acorn-bitstreams` | pinned release date + commit (e.g. `20260923+ge48a750c8303`) | `/usr/share/fpgas-online/acorn-pcie/images/`: `manifest.json`, and for each of `cle-215p` / `cle-101` the golden (`0x000000`) and operational (`0x400000`) flash images, the operational `.bit`, and the CSR maps |
| `fpgas-online-verify` | `X.Y.postN` | `fpgas-verify` and its unit |

The tools package depends on one exact bitstreams version. Which release that is comes from [`packaging/acorn-pcie/release.toml`](../../packaging/acorn-pcie/release.toml), and a new release reaches hosts only when a reviewed PR moves that pin. Every package is built, and its install rules are checked in clean Debian bookworm and trixie, by [`collect-bitstreams.yml`](../../.github/workflows/collect-bitstreams.yml).

`fpgas-online-acorn-debug` adds `fpgas-acorn-debug`. It brings openFPGALoader for loading the `.bit` over GPIO JTAG, which is how a card still on the image it was sold with is converted, and `python3-serial` for `fpgas-acorn-flash --uart`.

The [fpgas.online-fpga-tools repository](https://github.com/fpgas-online/fpgas.online-fpga-tools#debian-packages-bookworm-trixie-sid-arm64-armhf) has the fpgas.online openFPGALoader build, with the RP1 PIO JTAG cable and SPI flash info. Add it **before** installing. Otherwise apt installs Debian's own package (bookworm 0.10.0, trixie 0.13.1). Adding the repository afterwards does not replace it: run `sudo apt install openfpgaloader-fpgasonline` to switch.

### Arty A7 packages

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

### Fomu EVT packages

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
