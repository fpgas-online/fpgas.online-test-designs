# fpgas-verify: what an Acorn check tests

You have an Acorn and want to know what its check does, test by test, and how its opt-in power-cycle check
works.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## Acorn

The Acorn check ([`suite.py`](../../verify/src/fpgas_online_verify/boards/acorn/suite.py),
[`check.py`](../../verify/src/fpgas_online_verify/boards/acorn/check.py),
[`links.py`](../../verify/src/fpgas_online_verify/boards/acorn/links.py),
[`bist.py`](../../verify/src/fpgas_online_verify/boards/acorn/bist.py)) tests the board as it booted from its
flash:

* It loads nothing, never writes the flash and never reconfigures the FPGA.
* It runs every test it can, in the order below; a fault in one does not stop the others.
* Nothing is sent to the BARs of a board whose PCI IDs are not ours.
* On ours, nothing past the identifier read is sent over BAR0 or the P2 UART unless that identifier is a build
  of the installed release. The CSR addresses then come from that build's `csr.json`; one that puts a CSR the
  check uses outside the 64 KiB of BAR0 it maps is an `error`.

**Which board it is**, from the PCI IDs alone:

| PCI IDs | Is | Result |
|---|---|---|
| `10ee:7021`, subsystem `1e24:021f` (CLE-215+) or `1e24:0101` (CLE-101) | the fpgas.online Acorn SoC | tested |
| `1e24:021f` or `1e24:0101` as vendor:device | an Acorn on SQRL's factory image | `fail`, `unconverted: …`; only `pcie-link`, `rp1-pio` and `jtag` run |
| `10ee:7011` | the vendor XDMA sample (an Acorn or a NeTV2) | `fail`, `unconverted: …`; on a host set up for an Acorn (`fpga-board = acorn`, or `fpgas-acorn-verify`) `pcie-link`, `rp1-pio` and `jtag` run, and `jtag` takes either Acorn FPGA and names the variant from its IDCODE where only one variant has that part (an XC7A100T is a `cle-101`); with `auto` nothing runs, since it may be a NeTV2 |
| `10ee:0666` | a PCIe Screamer running PCILeech | `fail`: fpgas.online has no test design for this board yet |
| `10ee:7021`, subsystem `10ee:0007`, class `070001`, with a BAR2 | a stock Xilinx XDMA design (most likely a PicoEVB) | `fail`: fpgas.online has no test design for this board yet |
| any other Xilinx or SQRL ID | not a design we built | `fail` |

**Which setup the host is.** The Acorn has two setups, each wired its own way:

| Host (`/proc/device-tree/model`) | Setup | JTAG `--pins` (TDI:TDO:TCK:TMS) | GPIO chip | J5 / H5 |
|---|---|---|---|---|
| `Raspberry Pi 5 Model B` | Pi 5 with the Waveshare HAT | `10:9:11:8` | `raspberrypi,rp1-gpio` | GPIO3 / GPIO4 |
| `Raspberry Pi Compute Module 4` | Compute Blade | `2:3:4:14` | `brcm,bcm2711-gpio` | not wired |
| `Raspberry Pi Compute Module 5` | Compute Blade | `2:3:4:14` | `raspberrypi,rp1-gpio` | not wired |

* Both use openFPGALoader's `libgpiod` cable, and the P2 UART is `/dev/ttyAMA0`.
* Any other host is an `error`; the tests that do not need the wiring still run.

**The expected data**, one copy each, in the repository and installed by `fpgas-online-acorn-tools`:

| File | Holds | In the repository | Installed |
|---|---|---|---|
| `wiring.toml` | each setup's wiring: which Pi GPIO each P1/P2 signal lands on, the JTAG cable and pins, the UART, and which hosts are that setup | [`docs/wiring/acorn/wiring.toml`](../wiring/acorn/wiring.toml) | `/usr/lib/python3/dist-packages/fpgas_online_verify/boards/acorn/data/` |
| `expected.toml` | the figures the board must meet: PCIe link speed and width per setup, XADC ranges, and the least DRAM write and read bandwidth per variant | [`docs/wiring/acorn/expected.toml`](../wiring/acorn/expected.toml) | the same |

From a checkout, the check reads them from the repository.

**The tests**, in the order they run:

| Test | Over | Passes when |
|---|---|---|
| `pcie-link` | sysfs | `current_link_speed` and `current_link_width` are the setup's (5.0 GT/s, x1) |
| `pcie-bar0` | BAR0 | the operational build runs (the golden build means the operational slot did not boot), the flash identifies itself and its SFDP header can be read (a flash with no SFDP passes), the device DNA is neither all zeros nor all ones, and the XADC temperature and VCCINT, VCCAUX and VCCBRAM are in range |
| `rp1-pio` | the Pi's kernel | Pi 5 / CM5 (BCM2712) only, not run elsewhere: `/dev/pio0` is a character device that opens read-write, which openfpgaloader-rp1pio needs. No bootloader or `config.txt` setting is read. When it does not, the test also says whether `rp1_fw` and `rp1_pio` are loaded, and the kernel's own `rp1-pio` / RP1 firmware lines say why, e.g. `failed to contact RP1 firmware` on a bootloader rp1_pio cannot talk to (pi-sw2-p47 and p48, bootloader 2024/11/05, 2026-10-03) |
| `jtag` | P1 | `openFPGALoader --detect` finds one device, the variant's part in any silicon version ([the JTAG IDCODE](idcode-and-dna.md#the-jtag-idcode)), and `openFPGALoader --read-dna` reads a device DNA that is neither all zeros nor all ones. When BAR0's DNA is good, the two must match; otherwise the JTAG DNA is not compared. The IDCODE read does not use TDI; the DNA read does |
| `flash` | BAR0 | both 4 MiB slots (golden at `0x000000`, operational at `0x400000`), read whole with read opcodes only, hold the release's images |
| `ddr` | BAR0 | after the BIOS console is read out, the DRAM BIST makes two passes over the whole DRAM: no errors, and write and read bandwidth at least the variant's minimum |
| `p2-uart` | P2 | the UARTBone identifier at 1200 baud is BAR0's; at 921600 baud the identifier, DNA and XADC readings are right and the DNA is BAR0's. The link is left at 1200 baud |
| `p2-serial` | BAR0 and the Pi's GPIO | J2/K2, borrowed from the UART by the `p2_serial` switch, carry 0 and 1 both ways; the switch goes back to serial by itself; the UARTBone then answers with BAR0's identifier |
| `scratch` | BAR0 and P2 | the `ctrl` scratch register holds two patterns written over each bridge; its value is put back |
| `p2-gpio` | BAR0 and the Pi's GPIO | Pi 5 setup only: J5/H5 carry 0 and 1 both ways, FPGA to Pi and Pi to FPGA |
| `power-cycle` (opt-in, after `pcie-bar0`) | BAR0 | the FPGA restarted since the last check: see below |

## The Acorn's power-cycle check (opt-in)

A board is to be tested as its flash configures it. If the FPGA kept its configuration while its Pi restarted
(the card fed from somewhere else, a restart that does not reach the card), it still holds whatever was in it
before, a visitor's design included. With `power-cycle-check = on` the board fails in that case:

```text
power-cycle fail: the FPGA has not restarted since an earlier boot's check (scratch is 0x…, neither its
value after configuration nor this boot's marker): it did not restart with the Pi. Power-cycle the Pi
```

How it tells, on the SoC the boards run (it has no uptime counter): the `ctrl` scratch register holds
`0x12345678` after configuration and only a write changes it. When the `power-cycle` test has passed, the check
ends by leaving a marker there, 32 bits of a hash of the kernel's boot id. At the next check:

| Scratch holds | Means | Result |
|---|---|---|
| `0x12345678` | the FPGA was configured, or its SoC reset, since the last check | pass |
| this boot's marker | the check already ran in this boot (an operator running it again) | pass |
| anything else | the card kept its configuration across the Pi's restart, or something else wrote the register | fail |

A board that fails is left as it was found, so it fails again until the card restarts (a power cycle does it).
`--test scratch` on its own leaves no marker; `--test power-cycle`, when it passes, does leave it. The report says when the check was on: `"power_cycle_check": {"on": true, "configured_by":
"/etc/fpgas-verify/…ini"}`.

**What a restart of the Pi does to the card depends on the setup, so the check is opt-in.** Measured on
5 Oct 2026 on a Pi 5 with the PCIe HAT (the Acorn with DNA `0x0054b48664b04854`): after a plain `systemctl
reboot` the scratch register read `0x12345678` again and the check passed, and the same after a PoE power cycle.
That is one board; whether the soft reboot reloads the FPGA from its flash or only resets the SoC was not
established, and the Compute Module setup has not been measured. Where a restart of the Pi does not reach the
card, every board fails after a restart, so switch the check on only for a setup that has been measured. Outside the fleet nothing says how a host is restarted, which is why it is off by default.

Two limits. A reset of the SoC (a write to `ctrl_reset`) also returns the register to `0x12345678`, and the
check cannot tell that from configuration. And anyone with root on the Pi can write the register; the check is
there to catch a card that did not restart with its Pi, not a visitor who sets out to hide it.

`fpgas-verify --test power-cycle` runs it alone, when the setting is on; with the setting off it is an error
that says how to switch it on.

* `ddr` in detail ([`bist.py`](../../verify/src/fpgas_online_verify/boards/acorn/bist.py), the same code
  [`selftest.py`](../../designs/acorn-pcie/host/selftest.py) runs):
  1. The BIOS console is read until it has been quiet for 2 s. In the installed release
     (`vivado-bitstreams-acorn-pcie-20261001-ge568a408e7bd`, built from e568a40, which does not have
     [#47](https://github.com/fpgas-online/fpgas.online-test-designs/pull/47)) the BIOS stops while its
     console is full and unread, so reading it lets it finish setting up the DRAM. A build with #47 never
     waits for a reader. The BIOS's memtest line, when still there, is reported as `bios_memtest`.
  2. Two passes over the whole DRAM, in a low and a high half, each written before either is checked, with
     different data in each; the second pass swaps them. A dead top address bit, or half the expected DRAM,
     fails.
  3. Measurements: `bytes`, `passes`, `errors`, `write_MBps`, `read_MBps`, `seconds`.
* The golden image has no DRAM, no P2 switch and no spare GPIO: on it `ddr`, `p2-serial` and `p2-gpio` are
  in `not_run`, and the board fails for running golden.
* A test that cannot run because of an earlier fault is in the report's `not_run`, with why.
* A run in which none of the tests asked for ran (`--test p2-gpio` on a Compute Blade, say) fails.
* A kernel driver bound to the board (`litepcie.ko`) is unbound while a test that uses BAR0 runs, and bound
  again after. The events of those tests are held and sent once it is bound again.
* Every Pi pin a test drives is put back as it was found (function, pull, and an output's level); the FPGA's
  side is left as inputs. On a Compute Blade GPIO14 is both TMS and the UART's TX, and goes back to its UART
  function.
* Before the JTAG tool runs, the check asks the header's GPIO chip whether each JTAG pin can be had. A kernel
  whose pin controller is strict (the RP1's on 6.18, seen on a CM5) does not lend a pin a driver has: on a
  Compute Blade with the serial port on, that is GPIO14. The tool is then not run and `jtag` fails, naming the
  pin and who has it ([#127](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)). Which
  boot configuration a Compute Blade needs for both JTAG and the P2 UART is not settled.
