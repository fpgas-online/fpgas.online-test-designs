# fpgas-verify: what an Acorn check tests

You have an Acorn and want to know what its check does, test by test. The details of the tests (`ddr` step
by step, `not_run`, the driver unbound, the pins put back) are in [the Acorn's tests in detail](acorn-power-cycle.md#the-acorns-tests-in-detail).
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

The two boards that are not Acorns are reported as `xilinx-pcie`, followed by what their IDs say (for example `xilinx-pcie PCIe Screamer (PCILeech image): fail`), not as `acorn`, and the `fpga-verified` fleet event's `board0` says `xilinx-pcie - fail`. The report keeps `"board": "acorn"`, the check that found them, and so do the progress events (`fpga-board-found`, `fpga-board-identified`).

**Which setup the host is.** The Acorn has two setups, each wired its own way:

| Host (`/proc/device-tree/model`) | Setup | JTAG `--pins` (TDI:TDO:TCK:TMS) | GPIO chip | J5 / H5 |
|---|---|---|---|---|
| `Raspberry Pi 5 Model B` | Pi 5 with the Waveshare HAT | `10:9:11:8` | `raspberrypi,rp1-gpio` | GPIO3 / GPIO4 |
| `Raspberry Pi Compute Module 4` | Compute Blade | `2:3:4:14` | `brcm,bcm2711-gpio` | not wired |
| `Raspberry Pi Compute Module 5` | Compute Blade | `2:3:4:14` | `raspberrypi,rp1-gpio` | not wired |

* Both use openFPGALoader's `libgpiod` cable, and the P2 UART is `/dev/ttyAMA0`.
* Any other host is an `error`; the tests that do not need the wiring still run.
* On a Compute Blade J2 shares GPIO14 with TMS, through 470 Ω. So after the `jtag` test GPIO14 goes back to its
  UART function. On a Compute Module 5 with kernel 6.18 the kernel does not lend GPIO14 while the serial port
  has it: with the serial port on, `jtag` fails saying so, without running openFPGALoader
  ([fpgas.online-test-designs issue 127: on a Compute Blade the JTAG test cannot have GPIO14 while the serial port holds it](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)).

**The result:**

* It is `pass` only when every test passes.
* A board running its golden image fails: the operational slot did not boot.
* A Pi with no Acorn is `missing`. That is fatal, since the host was set up for one.
* `changed` compares the PCI slot and IDs, the device DNA, the flash's identity and the sha256 of each slot. So a
  flash rewritten since the last run (by `fpgas-acorn-flash write`, say) is fatal until `sudo fpgas-verify --update`.

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
| `rp1-pio` | the Pi's kernel | Pi 5 / CM5 (BCM2712) only, not run elsewhere: `/dev/pio0` is a character device that opens read-write, which openfpgaloader-rp1pio needs. No bootloader or `config.txt` setting is read. When it does not, the test also says whether `rp1_fw` and `rp1_pio` are loaded, and the kernel's own `rp1-pio` / RP1 firmware lines say why, e.g. `failed to contact RP1 firmware` on a bootloader rp1_pio cannot talk to (bootloader 2024/11/05) |
| `jtag` | P1 | `openFPGALoader --detect` finds one device, the variant's part in any silicon version ([the JTAG IDCODE](idcode-and-dna.md#the-jtag-idcode)), and `openFPGALoader --read-dna` reads a device DNA that is neither all zeros nor all ones. When BAR0's DNA is good, the two must match; otherwise the JTAG DNA is not compared. The IDCODE read does not use TDI; the DNA read does |
| `flash` | BAR0 | both 4 MiB slots (golden at `0x000000`, operational at `0x400000`), read whole with read opcodes only, hold the release's images |
| `ddr` | BAR0 | after the BIOS console is read out, the DRAM BIST makes two passes over the whole DRAM: no errors, and write and read bandwidth at least the variant's minimum; details: [the `ddr` test in detail](acorn-power-cycle.md#the-acorns-tests-in-detail) |
| `p2-uart` | P2 | the UARTBone identifier at 1200 baud is BAR0's; at 921600 baud the identifier, DNA and XADC readings are right and the DNA is BAR0's. The link is left at 1200 baud |
| `p2-serial` | BAR0 and the Pi's GPIO | J2/K2, borrowed from the UART by the `p2_serial` switch, carry 0 and 1 both ways; the switch goes back to serial by itself; the UARTBone then answers with BAR0's identifier |
| `scratch` | BAR0 and P2 | the `ctrl` scratch register holds two patterns written over each bridge; its value is put back |
| `p2-gpio` | BAR0 and the Pi's GPIO | Pi 5 setup only: J5/H5 carry 0 and 1 both ways, FPGA to Pi and Pi to FPGA |
| `power-cycle` (opt-in, after `pcie-bar0`) | BAR0 | the FPGA restarted since the last check: see [The Acorn's power-cycle check (opt-in)](acorn-power-cycle.md#the-acorns-power-cycle-check-opt-in) |
