# Acorn PCIe test designs on welland.fpgas.online — design and phased plan

**Date:** 2026-09-03
**Status:** Draft for review (nothing in this document has been built yet)
**Scope:** The six Sqrl Acorn CLE-215+ hosts at Welland (`pi-sw2-p{29,43,44,46,47,48}`).
PS1 Compute Blade hosts (CLE-101 / LiteFury) are a follow-on and only mentioned
where the design must not preclude them.

> **Standing principle (from the task brief):** the hardware works. Every
> failure is our gateware, host software, configuration, or documentation.
> Where the *wiring* is inconsistent between boards, the wiring gets fixed to the
> canonical map; the software does not grow per-board special cases.

---

## 1. Goal

Get a single LiteX PCIe design running and *tested* on every Welland Acorn so
that, over PCIe, the host can:

| # | Requirement (from the brief)                                                            | Mechanism                                                                                   |
|---|------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| R1 | Read device DNA and board health (power rail voltages, temperature) via PCIe            | LiteX `DNA` + `XADC` CSRs read through the LitePCIe BAR0 → Wishbone bridge (`litepcie_util info` already prints exactly these) |
| R2 | Load a new FPGA design onto the device via PCIe, not via GPIO JTAG                      | `S7SPIFlash` bit-bang + `flash_cs_n` GPIO + `ICAP` warm reboot, driven by `litepcie_util flash_write` / `flash_reload`, with Xilinx multiboot (golden + operational slots) |
| R3 | Toggle the spare GPIO pins (P2 J5 / H5)                                                 | `GPIOTristate` CSR on J5/H5; host drives over PCIe and reads back on Pi GPIO3/GPIO4, and vice versa |
| R4 | LiteX BIOS on the UART                                                                  | VexRiscv + BIOS, `serial` on K2 (FPGA TX → Pi GPIO15) / J2 (FPGA RX ← Pi GPIO14), `/dev/ttyAMA0` at 115200 |
| R5 | Prove DDR3 works and test Pi memory ↔ FPGA DDR3 DMA in both directions                  | LiteDRAM (MT41K512M16, 1 GiB) + BIOS memtest for the first half; a LitePCIe DMA ↔ LiteDRAM DMA bridge with CSR-selected direction/base/length for the second half |

Ordering constraint from the brief: **Vivado flow first**, fully working and
tested on hardware, then the same design and tests on the **fully open-source
flow** (Yosys + nextpnr-xilinx, open `pcie_7x` core, no Vivado-only bitstream
properties).

## 2. Where things stand today (verified 2026-09-03)

Everything below was checked this session unless a source is cited. Facts
already in the repo are only summarised.

### 2.1 Hardware and host state (PR #11, re-probed today on p29)

| Host       | IP         | Flash contents          | JTAG (P1)       | P2 serial/GPIO wiring                         |
|------------|------------|-------------------------|-----------------|-----------------------------------------------|
| pi-sw2-p29 | 10.21.2.29 | Sqrl factory `1e24:021f` | OK              | serial OK; **J5 wire open**                   |
| pi-sw2-p43 | 10.21.2.43 | Sqrl factory `1e24:021f` | **empty chain** | untestable until JTAG works                   |
| pi-sw2-p44 | 10.21.2.44 | LiteX design `10ee:7011` | **empty chain** | untestable until JTAG works                   |
| pi-sw2-p46 | 10.21.2.46 | Sqrl factory `1e24:021f` | OK              | correct                                       |
| pi-sw2-p47 | 10.21.2.47 | Sqrl factory `1e24:021f` | OK              | **both pairs transposed** (K2↔J2, J5↔H5)      |
| pi-sw2-p48 | 10.21.2.48 | Sqrl factory `1e24:021f` | OK              | correct                                       |

Canonical P2 map (the one all software assumes): K2 → GPIO15 (RXD0),
J2 ← GPIO14 (TXD0), J5 ↔ GPIO3, H5 ↔ GPIO4. Source: PR #11
`acorn-pinmap.md` "Measured P2 wiring (Welland, 2026-08-31)".

Live probe of `pi-sw2-p29` today:

```
pi-sw2-p29, kernel 6.12.96+rpt-rpi-v8, 2 GB RAM, overlayroot tmpfs 991M
0001:01:00.0 Processing accelerators [1200]: Squirrels Research Labs Acorn CLE-215+ [1e24:021f]
openFPGALoader v0.10.0            (no --read-dna, opens /dev/gpiochip0; header is gpiochip15)
/dev/ttyAMA0 present, console=ttyAMA10
/lib/modules/6.12.96+rpt-rpi-v8/build: No such file or directory   (no kernel headers → cannot build litepcie.ko on the Pi)
gcc + make present; dpkg status: Stale file handle (known NFS-root issue, PR #11)
pi user: pubkey login works, passwordless sudo works; root login: denied
```

### 2.2 Access path from this machine

`tweed.welland.mithis.com` was reinstalled 2026-08-30 (PR #11). The old
`pi@tweed` jump account is gone. What works now, verified today:

```
ssh tim@10.21.0.1                                  # tweed, over the wg-desktop WireGuard route
ssh -o ProxyJump=tim@10.21.0.1 pi@10.21.2.<port>   # any Welland Pi, pubkey auth, sudo -n OK
```

`~/.ssh/known_hosts` line 44 still holds tweed's pre-reinstall RSA key for both
`tweed.welland.mithis.com` and `10.21.0.1`; the new ED25519 fingerprint is
`SHA256:8JMaRRnmbng14uL3q4fD3SvXo00k+mA/wUge9gLN2Ps`. This must be fixed
(`ssh-keygen -R`) before `verify_hardware.py` can run; I used a scratch
`known_hosts` for today's probes and did not touch the real file.
`verify_hardware.py` on `main` still uses `pi@tweed.welland.mithis.com` →
`root@10.21.0.1NN`, which no longer exists at all.

### 2.3 Toolchains

- **Vivado 2025.2** is installed locally at `/opt/Xilinx/2025.2/Vivado`.
- **openXC7** builds of the Acorn PCIe enumeration SoC (open `pcie_7x` core,
  `fasm2frames_wrapper.py` for `IBUFDS_GTE2`) are **green in CI** for all three
  Acorn variants (PR #7/#8/#9 checks). Nobody has confirmed one of those
  bitstreams enumerating on hardware.
- **LiteDRAM + openXC7 has never passed memtest** (`plan.md` Phase 8/9).
- **openXC7 cannot set multiboot bitstream properties** (`NEXT_CONFIG_ADDR`,
  `TIMER_CFG`, `CONFIGFALLBACK`); today those come from Vivado `write_bitstream`
  via `litex_boards.platforms.sqrl_acorn` (`with_multiboot=True`), which is why
  every Acorn Vivado build emits three flavours (`.bit`, `_operational.bit`,
  `_fallback.bit`).
- **LiteX 2025.12** (pinned in `uv.lock`) has the xc7 JTAGPHY RX bug that PR #9
  patches with `scripts/apply_litex_jtag_patch.py`; 2026.04 fixes it upstream.

### 2.4 In-flight work this plan builds on

| Branch / PR                         | State                          | What it gives us                                                                                  |
|-------------------------------------|--------------------------------|---------------------------------------------------------------------------------------------------|
| PR #11 `docs/device-inventory-refresh` | open, mergeable, CI green      | The hardware truth above (VLAN names, wiring survey, detach-before-JTAG rule, Pi 5 traps)         |
| PR #7 `ci-netv2-100t-fix`           | open                           | Stops NeTV2 PCIe openXC7 failures from failing every PR                                            |
| PR #8 `acorn-pin-id-fix`            | open, largely superseded by merged PR #10 | Only `static_high_acorn.py` diagnostic is still unique                                  |
| PR #9 `acorn-pcie-update`           | open, **lint failing**         | ICAP + S7SPIFlash on the Acorn PCIe SoC, JTAGBone `flash_writer` SoC, LiteX JTAG patch, deploy script (references a `native_jtagbone.py` that is not in the repo) |
| `vivado-xilinx-flows` (no PR)       | 60 commits on top of old main  | Three-flow Makefiles (`vivado-vivado` / `yosys-vivado` / `yosys-nextpnr`), variant-in-path build dirs, Yosys EDIF fixer, `publish_vivado_bitstreams.py`, `docs/toolchains/vivado.md` |
| Release `vivado-bitstreams-v0.0-496-gf162f60` | published 2026-04-17     | Vivado builds of every design × Acorn variant incl. `_fallback`/`_operational`; the PCIe one has **no** ICAP/flash core, so it can enumerate but cannot self-update |

`vivado-xilinx-flows` and PR #9 both modify `pcie_soc_acorn.py` in different
directions; they have to be reconciled before either can merge.

### 2.5 A finding to re-test rather than trust

PR #9's docs state that any JTAG-loaded *PCIe-capable* bitstream "auto-reverts
to the factory firmware via a PERST→PROG_B circuit", and builds the
`flash_writer` bootstrap around that. PR #11 later found that reconfiguring the
FPGA while its endpoint is enumerated crashes and reboots the Pi 5, and that the
same load "completes cleanly" once the endpoint is detached first. A Pi reboot
would look exactly like an auto-revert from the JTAG side. Phase 3 therefore
starts by loading the PCIe SoC into SRAM *with the detach rule applied* and
observing whether it survives. If it does, the classic SRAM bootstrap
(JTAG → SRAM → `litepcie_util flash_write`) is the flash path and `flash_writer`
becomes a documented fallback only.

## 3. Design

### 3.1 One SoC, one design directory

New design directory `designs/acorn-pcie/` (the existing `pcie-enumeration`
stays as the NeTV2/Acorn *enumeration-only* smoke test):

```
designs/acorn-pcie/
  gateware/acorn_pcie_soc.py     # the SoC; --golden builds the minimal recovery image
  host/
    acorn_pcie.py                # shared helpers: find BDF, detach/rescan, locate driver, CSR access
    test_pcie_info.py            # R1  DNA + XADC (temperature, VCCINT, VCCAUX, VCCBRAM) + identifier
    test_pcie_gpio.py            # R3  J5/H5 via PCIe CSR ↔ Pi GPIO3/GPIO4, both directions
    test_pcie_flash.py           # R2  flash_write to 0x400000 + flash_reload + re-enumerate + ident check
    test_pcie_dma.py             # R5b host↔FPGA DMA loopback, then host↔DDR3 in both directions
    test_uart_bios.py            # R4  thin wrapper over designs/uart/host/test_uart.py semantics (banner + echo)
    test_ddr_bios.py             # R5a reuse designs/ddr-memory/host/test_ddr.py parser (memtest OK/KO)
  driver/                        # generated by LiteX (`generate_litepcie_software`), committed headers only
  Makefile                       # three-flow targets via mk/three-flows.mk, plus `driver`, `kmod-cross`
  README.md
```

Why a new directory rather than growing `pcie-enumeration`: the repo pattern is
one directory per *test*, but here the five tests share one bitstream because
the whole point is that the flashed image carries everything. Five test scripts
against one gateware directory keeps `verify_hardware.py`'s "design → artifact +
script" model intact (each test is a `DESIGNS` entry pointing at the same
artifact).

### 3.2 SoC contents (`acorn_pcie_soc.py`)

Mirrors `litex_boards.targets.sqrl_acorn` (which is the reference the LiteX
authors run on this exact board) rather than the repo's hand-rolled minimal
CRGs, because it is the only known-good combination of PLL + IDELAYCTRL + DDR
on this board:

| Block            | Choice                                                                                          | Notes |
|------------------|-------------------------------------------------------------------------------------------------|-------|
| CRG              | S7PLL from `clk200` → `sys` (100 MHz), `sys4x`, `sys4x_dqs`, `idelay` (200 MHz) + `S7IDELAYCTRL` | Same as upstream target |
| CPU / BIOS / UART| VexRiscv (standard), BIOS in ROM, `serial` on K2/J2 at 115200                                   | R4. The real P2 pins, not `uart_name="crossover"`. No second (PCIe) console in this plan |
| DDR3             | `A7DDRPHY` + `MT41K512M16(sys_clk_freq, "1:4")`, L2 8 KiB                                       | R5a. `cle-101` variant gets `MT41K256M16` (512 MB) |
| PCIe             | `S7PCIEPHY` on a `pcie_x1` extension (lane 0: RX B10/A10, TX B6/A6, refclk F6/E6, PERST J1), `data_width=64`, BAR0 128 KiB; `add_pcie(ndmas=1, address_width=64, with_dma_loopback=True)` | Pi 5 gives exactly one lane. x1 also matches what the open `pcie_7x` core supports, so the same resource is used in every flow. `pcie_clkreq_n` driven low. **`address_width=64` is mandatory**: the BCM2712 root complex maps host RAM above 4 GiB on the bus and `litepcie.ko` does `dma_set_mask(DMA_ADDR_WIDTH)` at probe, so a 32-bit build fails probe and takes even `litepcie_util info` with it |
| PCI IDs          | Vendor `10ee`. Device ID **differs by flow**: LitePCIe's Vivado PHY sets `7020 + nlanes` = **`7021`** for x1, and the generated `litepcie.ko` binds `7021/7022/7024/7028` for 7-series; the open `pcie_7x` core hard-codes **`7011`** (`CFG_DEV_ID`) and `S7PCIEPHY` does not override it | Tests locate the device by vendor `10ee` + the LiteX ident string, and check the device ID against a per-flow expectation (`--expect-device-id`, default `7021`; Phase 5 steps 1–2 pass `7011` until step 3 lands). Phase 5 parameterises the open core to `7021` so one kernel module serves both flows |
| DNA, XADC        | `DNA()` + timing constraints, `XADC()`                                                          | R1 |
| Flash + ICAP     | `GPIOOut(flash_cs_n)`, `S7SPIFlash(flash, sys_clk_freq, 25e6)`, `ICAP()` + `add_reload()`       | R2. Exactly the CSR names `liblitepcie` expects (`CSR_FLASH_*`, `CSR_ICAP_*`) |
| Spare GPIO       | `GPIOTristate` on a new `p2_gpio` resource `Pins("J5 H5")`, LVCMOS33                            | R3. Tristate so the Pi can drive them too |
| DDR DMA bridge   | New module `PCIeDRAMBridge`: `LiteDRAMDMAWriter` fed from `pcie_dma0.source`, `LiteDRAMDMAReader` feeding `pcie_dma0.sink`, on a 64-bit LiteDRAM port (`crossbar.get_port(data_width=64)`, so no manual width converter against the 128-bit native port), CSRs `base`, `length`, `mode` (loopback / to-dram / from-dram), `start`, `done` | R5b. LitePCIe's `add_plugin_module` chain (loopback, then buffering with `add_pcie`'s defaults) leaves `pcie_dma0.sink/source` as the far end of the chain, so the bridge attaches there after construction, sees the streams when loopback is disabled, and the plain `litepcie_util dma_test` still works when it is enabled |
| LEDs             | `LedChaser` on the four user LEDs                                                               | Free "design is alive" indicator on camera feeds |
| Ident            | `"fpgas-online Acorn PCIe SoC <variant>"` + LiteX version                                       | Read back by `litepcie_util info` and by the BIOS banner |

`--golden` builds the recovery image: same CRG, PCIe (**including
`pcie_dma0` + MSI**, because `litepcie.ko` touches `CSR_PCIE_DMA0_BASE` at
probe), flash, ICAP, DNA/XADC, UART, **no DDR, no DMA bridge, no GPIO**.
Smaller and with nothing that can fail calibration. It goes to flash 0x0 once
and is rarely touched (`acorn-pcie-programming.md` safety rule 6).

**One driver for both images.** LiteX allocates CSR banks in sorted
module-name order, so dropping modules would move every CSR the host tools
use. Both builds therefore pin the shared modules to fixed CSR indices via
`SoCCore.csr_map` (`ctrl`, `identifier_mem`, `uart`, `timer0`, `dna`, `xadc`,
`flash`, `flash_cs_n`, `icap`, `pcie_phy`, `pcie_msi`, `pcie_dma0`), set as a
class attribute because `SoCCore.__init__` consumes it (32 locations at the
default 14-bit CSR address width, enough for the ~18 modules here), and Phase
1's gate diffs the two generated `csr.h` files to prove those addresses are
identical. Modules only in the operational image (`sdram`, `ddrphy`,
`p2_gpio`, `pcie_dram`) take indices above the pinned block.

Multiboot bitstream flavours come from the platform (`with_multiboot=True`)
in the Vivado flows; see §5 for how the open flow gets them.

### 3.3 Host side

- **`litepcie.ko` + `litepcie_util`** are generated by LiteX
  (`generate_litepcie_software`). The Pi has no kernel headers and a tmpfs root,
  so the module is **cross-compiled locally** against the Raspberry Pi kernel
  headers for `6.12.96+rpt-rpi-v8` (the `linux-headers-6.12.96+rpt-rpi-v8`
  arm64 package from the Raspberry Pi apt repository, unpacked under
  `tmp/`), and `litepcie_util` is cross-built with `aarch64-linux-gnu-gcc`.
  `verify_hardware.py` uploads both per test run (they are lost at reboot).
  Longer term this moves to an `fpgas-online/apt` package (`litepcie-dkms`
  or prebuilt-per-kernel) via fpgas.online-infra; that is out of this repo.
- **R1 and R3 do not strictly need the kernel module**: `litex_server --pcie
  --pcie-bar /sys/bus/pci/devices/0001:01:00.0/resource0` (as root) maps BAR0
  directly and every CSR is reachable. The tests use the kernel
  module path first (it is the documented, upstream-supported one) and fall
  back to BAR0 mmap for R1/R3 when the module is absent, so board health can
  be read on a Pi that has only the bitstream.
- **R2 and R5b need the kernel module**: `flash_write`/`flash_read`/
  `flash_reload` go through `LITEPCIE_IOCTL_FLASH`/`_ICAP`, and DMA needs host
  memory. No fallback.
- **Pre-test on every Acorn host**: `echo 1 > /sys/bus/pci/devices/0001:01:00.0/remove`
  before any JTAG load; `ln -sfn /dev/gpiochip15 /dev/gpiochip0` while the
  fleet is on openFPGALoader 0.10.0; `systemctl stop serial-getty@ttyAMA0`;
  program with `openFPGALoader --cable libgpiod --pins 10:9:11:8 <bit>` (the
  `-c rp1pio` cable in today's `verify_hardware.py` does not exist in 0.10.0;
  switch back to it when infra PR #48 lands); rescan after the load. All of
  this lives in one `acorn` `pre_test`/`program_cmd` pair in
  `verify_hardware.py`.
- **PoE power cycles**: `verify_hardware.py`'s `poe_reset()` runs `poe.sh` on
  the old `pi@tweed` account and matches only `piNN` names; `poe.sh` no longer
  exists on the reinstalled tweed (checked today; `snmpset` does). Phase 0
  rewrites it to talk SNMP to the S3300 (`10.1.5.11`, port = host suffix,
  write community from fpgas.online-infra) via `tim@10.21.0.1`. Until that
  lands, power cycles in Phase 3 are done by hand and the run log says so.
- **`verify_hardware.py` transport update**: gateway `tim@10.21.0.1`, target
  `pi@10.21.2.<port>` with `sudo` in commands, hosts renamed to the VLAN
  scheme (`welland-sw2-p29` …). Other Welland boards keep working because only
  the Acorn entries change in this pass; the rest are flagged in PR #11 as not
  re-probed.

### 3.4 Flash layout and update sequence (unchanged from `acorn-pcie-programming.md`)

```
0x000000  golden   (--golden build, NEXT_CONFIG_ADDR=0x400000)    written once
0x400000  operational (full SoC, TIMER_CFG watchdog + CONFIGFALLBACK)  updated over PCIe
```

Initial install on a factory board (per board, once):

1. Detach endpoint → JTAG-load the plain operational `.bit` into SRAM →
   rescan → `litepcie_util info` shows our ident and DNA. (`litepcie_util`
   cannot talk to the Sqrl firmware, so nothing can be read from flash before
   this step.)
2. `flash_read` **the whole 32 MiB of factory flash** and keep the image
   off-repo (tweed `~tim/acorn-factory-flash/<host>-<date>.bin`). The Sqrl
   firmware is the only thing that has ever booted on these boards; we do not
   throw it away. `litepcie_util flash_read` costs three syscalls per byte
   (CS low, flash ioctl, CS high), roughly 100 M syscalls for 32 MiB, so a
   buffered reader (page-sized `READ` commands driven through the same
   `LITEPCIE_IOCTL_FLASH` path, or a small C helper linked against
   `liblitepcie`) is a Phase 2 deliverable, not an option.
3. `flash_write golden.bin 0x0`, `flash_write operational.bin 0x400000`,
   `flash_read` back and compare.
4. Power cycle (PoE) → the board boots golden → chain-loads operational →
   enumerates `10ee:7021` with our ident. From then on R2 is
   `flash_write … 0x400000` + `flash_reload` + rescan.

Boards whose JTAG is not working (**p43, p44**) are **never flashed** until
JTAG is restored — a bad golden image on a JTAG-less board is a brick
(safety rule 4).

## 4. Phases, branches, pull requests

Each phase is its own branch in its own worktree under `.worktrees/`, small
commits, a `feature-dev:code-reviewer` pass every 1–3 commits or at each
phase boundary, and a PR when the phase's gate is met. Later phases branch from
the earlier phase's branch only when they genuinely depend on it; otherwise
from `main`.

### Phase 0 — land the prerequisites (branch `acorn-pcie/00-prereqs`)

1. Merge PR #11 (docs) and PR #7 (CI) as they are.
2. Open a PR for `vivado-xilinx-flows` rebased onto `main` (60 commits; the
   rebase is mostly mechanical, the one real conflict is
   `pmod_pin_id_acorn.py`, which both PR #10 and that branch touch). This is
   the infrastructure every Vivado build in this plan uses. Its `yosys-vivado`
   hybrid is nice-to-have; only `vivado-vivado` and `yosys-nextpnr` are on this
   plan's critical path.
3. Rebase PR #9 on top of that, fix its lint failure, drop the parts this plan
   replaces (the ICAP/flash edit to `pcie_soc_acorn.py` moves into the new
   SoC), **keep** its `pin-id` `DESIGNS` entry and the `--board acorn` decoder
   in `identify_pmod_pins.py`, keep `flash_writer_soc_acorn.py` + the LiteX
   JTAG patch as the documented JTAG-only fallback path, and either commit a
   `native_jtagbone.py` or delete the deploy script that references it.
4. Close PR #8 as superseded by PR #10, cherry-picking `static_high_acorn.py`
   if it is still wanted.
5. `verify_hardware.py`: new gateway/user/sudo transport, VLAN host names for
   the six Acorns, Acorn pre-test/program commands per §3.3, `poe_reset()`
   over SNMP per §3.3, `--repeat N` (the gates below need it), `--dry-run`.
   Update `docs/verify-hardware.md`.

**Gate:** `uv run python verify_hardware.py --list` shows the six Acorn hosts;
`--host welland-sw2-p46 --test pin-id` runs end-to-end against a Vivado pin-ID
bitstream **rebuilt after PR #10** (the released one predates the clock fix)
and reports the canonical wiring (`K2` on GPIO15, `J2` on GPIO14, `J5` on
GPIO3, `H5` on GPIO4). That proves the transport, the detach rule, the
symlink, and the pin-ID decoder in one shot.

### Phase 1 — the SoC, Vivado flow (branch `acorn-pcie/01-soc`)

1. `designs/acorn-pcie/gateware/acorn_pcie_soc.py` as in §3.2, built with
   `--toolchain vivado` for `cle-215+` (and `cle-101`, `cle-215` in the
   Makefile matrix). `--golden` variant. `--driver` output committed as
   `driver/kernel/{csr,soc,mem}.h` only.
2. `PCIeDRAMBridge` module in `designs/_shared/pcie_dram_bridge.py` with a
   migen simulation test (`tests/`), because this is the one piece of gateware
   that is new rather than assembled.
3. Makefile via `mk/three-flows.mk`; top-level `build-acorn-pcie-*` aggregators.
4. Timing must close in Vivado for both variants with zero critical warnings we
   have not explained in the README.

**Gate:** `make -C designs/acorn-pcie gateware-acorn-cle-215+-vivado-vivado`
produces `sqrl_acorn{,_operational,_fallback}.{bit,bin}` and the golden set;
the pinned CSR addresses in the operational and golden `csr.h` are identical
(a unit test diffs them); `ruff` clean; the bridge simulation passes.

### Phase 2 — host tools and driver (branch `acorn-pcie/02-host`)

1. `scripts/build_litepcie_driver.py`: fetch the matching Raspberry Pi kernel
   headers deb, cross-compile `litepcie.ko` and `litepcie_util`, drop them in
   `artifacts/acorn-pcie-driver/<kernel>/`. Kernel version comes from the
   Pi (`uname -r`) at run time, not hard-coded.
2. The six host scripts in §3.1, each printing exactly one `RESULT: PASS|FAIL`
   line, each with `--help` and unit tests for their parsers (same style as
   `identify_pmod_pins.py`'s tests in PR #9).
3. `verify_hardware.py` `DESIGNS` entries for `pcie-info`, `pcie-gpio`,
   `pcie-flash`, `pcie-dma`, `uart` (Acorn now uses the acorn-pcie bitstream),
   `ddr` (same).

**Gate:** all host scripts pass their unit tests; `verify_hardware.py --list`
shows the new tests; nothing has touched hardware yet.

### Phase 3 — hardware bring-up, Vivado bitstream (no new branch; fixes go to 01/02)

Order of boards: **p48 first** (correct wiring, factory flash), then p46, then
p29 (J5 test expected to fail until its wire is fixed), then p47 after its P2
connector is re-wired, then p43/p44 after their P1 cables are fixed.

Per board, in this order, each step a `verify_hardware.py` test:

1. Detach → JTAG SRAM load of the plain `.bit` (not `_operational.bit`, so
   the watchdog/fallback properties are not a variable) → rescan → `lspci`
   shows `10ee:7021`. **Record whether the design survives 60 s with PCIe up**
   (§2.5). If it reverts, fall back to PR #9's `flash_writer` path for step 7
   and open an issue with the evidence.
2. `pcie-info`: ident, DNA (57-bit), temperature in a sane range (20–80 °C),
   VCCINT ≈ 1.0 V, VCCAUX ≈ 1.8 V, VCCBRAM ≈ 1.0 V (±10 %).
3. `uart`: BIOS banner and echo on `/dev/ttyAMA0`.
4. `ddr`: BIOS memtest OK on the full 1 GiB, calibration output captured.
5. `pcie-gpio`: FPGA drives J5/H5 high/low, Pi reads GPIO3/4; Pi drives, FPGA
   CSR reads; both pins, both directions.
6. `pcie-dma`: `litepcie_util dma_test` loopback, then bridge mode: write a
   pattern to DDR3 from host memory, read it back to host memory, compare;
   then prove the same DRAM is being addressed by reading the first words of
   the region back over the UART with the BIOS (`mr 0x40000000`). The BAR0
   Wishbone window is the 128 KiB CSR region only, so DRAM is *not* reachable
   through it. Throughput is recorded, not gated.
7. Factory flash backup + golden/operational install per §3.4 (**p48 only**
   until step 8 passes there).
8. PoE power cycle → enumerates from flash → all of 2–6 pass again →
   `pcie-flash`: write a rebuilt operational image (different ident string) to
   0x400000, `flash_reload`, rescan, ident changed; then write a deliberately
   truncated image, `flash_reload`, confirm the watchdog brought golden back
   (ident is the golden one), then restore.
9. Repeat 7–8 on the other boards with working JTAG.

**Gate:** `verify_hardware.py --board acorn` passes every Acorn test three
times in a row on every board whose wiring is canonical. Boards excluded for
wiring reasons are listed in the run summary with the reason.

### Phase 4 — release and CI (branch `acorn-pcie/04-release`)

1. `publish_vivado_bitstreams.py` run for the new design →
   `vivado-bitstreams-<git describe>` release (tag ruleset already permits
   this prefix).
2. CI: lint the new host scripts and run the bridge simulation; the openXC7
   Acorn matrix job for `acorn-pcie` is added but `continue-on-error` until
   Phase 5 makes it green.
3. Docs: `docs/tests/acorn-pcie.md`, update `acorn.md` / `acorn-pcie-programming.md`
   per-board flash state table and expected PCI IDs, remove the "XC7A200T is
   too large for openXC7" claim (CI builds it), `README.md` test matrix.

### Phase 5 — the same thing with the open-source flow (branch `acorn-pcie/05-openxc7`)

Nothing here is speculative about *what* to do; it is speculative about how
much breaks. Steps, in the order that isolates faults:

1. Build `acorn_pcie_soc.py` with `--toolchain openxc7` on the existing CI
   image (`regymm/openxc7` + `fasm2frames_wrapper.py`). Expect synthesis and
   P&R to pass (the enumeration SoC already does).
2. Use the **hybrid `yosys-vivado` flow as the bisector**: if the hybrid
   bitstream works on hardware and the `yosys-nextpnr` one does not, the fault
   is in P&R/bitgen; if the hybrid also fails, it is in Yosys synthesis of the
   design. This is the reason to keep the hybrid flow alive from the
   `vivado-xilinx-flows` branch.
3. PCIe: `pcie_7x` is designed for exactly this (openXC7, Gen2 x1, 7-series).
   Known risk is `IBUFDS_GTE2` / GTP FASM (issue #1, already worked around).
   Two things the open core hard-codes must be made to match the Vivado
   build before the host tools can be shared: `CFG_DEV_ID` (`7011` → `7021`,
   overridden from the `pcie_s7` wrapper or the submodule's Verilog
   parameters) and `BAR0 = 32'hFC000000` (a 64 MiB BAR versus 128 KiB; the
   Pi root complex may refuse to re-assign a larger BAR on rescan without a
   reboot, and the Sqrl firmware's BAR0 is 128 KiB). Both are one-line
   parameter changes, but they live inside the `pcie_7x` git submodule
   (`litepcie_pcie_s7.v` is in `pcie_7x/src/`, and the SoC globs every `*.v`
   there). Carry them as a repo-local `pcie_s7` wrapper in
   `designs/_shared/` that the SoC adds instead of the submodule's copy
   (excluded from the glob), so the submodule stays pinned to upstream and the
   change is visible in review.
4. DDR3: the historically failing piece. Attack order: build the `ddr-memory`
   SoC (no PCIe) with openXC7 and drive BIOS `sdram_cal` / `mem_test` over the
   UART; compare calibration windows with the Vivado build of the same SoC;
   check `IDELAYCTRL`/`ISERDESE2`/`OSERDESE2` attribute handling and the
   `sys4x_dqs` phase in the FASM; drop `sys_clk_freq` to 50 MHz to widen
   margins if needed. Each finding is its own commit and, where it is a
   toolchain bug, an upstream issue link in the README.
5. Multiboot without Vivado: `NEXT_CONFIG_ADDR` and `TIMER_CFG` are ordinary
   configuration-register writes (`WBSTAR`, `TIMER`, `COR0` bits) in the
   bitstream header. Add `scripts/xc7_multiboot_patch.py` that inserts those
   packets into an openXC7 `.bit` (and produces the `.bin`), with a unit test
   that round-trips against the Vivado-generated `_fallback`/`_operational`
   pairs from Phase 1 to prove the packet stream matches. Until that exists,
   the open flow's image is written to the *operational* slot only and golden
   stays Vivado-built.
6. Re-run the entire Phase 3 sequence with the open-source bitstream.

**Gate:** same as Phase 3, using bitstreams built by the CI openXC7 job, on
every canonical-wiring board, three consecutive runs.

### Phase 6 — open-source JTAG flash path (stretch, branch `acorn-pcie/06-jtag-flash`)

Only if time allows and only for the bricked-board recovery story: get
`openFPGALoader --write-flash` working through an openXC7-built `spiOverJtag`
(an untracked `tmp/spi_over_jtag_fbg484` experiment exists in the main
checkout only, not in git; the missing piece is
`STARTUPE2 USRCCLKO` actually driving CCLK after configuration, which
`designs/_shared/s7_spi_flash.py` already does for the SPI-flash-ID test), or
finish PR #9's `flash_writer`. Not on the critical path because Phase 3 step 7
installs golden over PCIe.

## 5. Hardware work that is not software (for Tim)

The brief says fix the wiring, not the code. These are physical tasks and gate
which boards each phase can use:

| Board | Fix                                                                 | Unblocks                       |
|-------|---------------------------------------------------------------------|--------------------------------|
| p47   | Transpose both P2 pairs so K2→GPIO15, J2→GPIO14, J5→GPIO3, H5→GPIO4 (not a 180° re-seat) | UART, GPIO, all Phase 3 tests |
| p29   | Re-terminate the J5 (P2 pin 3) wire to GPIO3                        | `pcie-gpio`                    |
| p43   | Check/reseat P1 (JTAG) cable; TCK pull-up test from the PS1 notes   | everything (no JTAG = no safe flashing) |
| p44   | Same as p43. Also find out what LiteX design is in its flash (ident via UART once JTAG works) | everything |
| all   | Update `~/.ssh/known_hosts` for tweed's new host key                | `verify_hardware.py`           |
| infra | Merge fpgas.online-infra #48 (openFPGALoader with `rp1pio`, `--read-dna`) when the deb is published; add kernel headers or a `litepcie` package to the NFS root | removes the `gpiochip0` symlink and the cross-compile step |

## 6. Test definitions (pass/fail)

| Test         | PASS when                                                                                                       | FAIL / notes |
|--------------|-----------------------------------------------------------------------------------------------------------------|--------------|
| `pcie-info`  | vendor `10ee` at `0001:01:00.0` with the device ID the flow is expected to produce (`7021`), ident matches the built bitstream, DNA is non-zero and not all-ones and stable across two reads, XADC values in range (§4 Phase 3 step 2) | DNA `0xffffffffffffffff` means DNA port not clocked; out-of-range XADC means wrong scaling or unpowered rail |
| `pcie-gpio`  | For each of J5,H5 and each direction, the far side reads the driven value for 0 and 1                          | Pi side uses `gpiochip15` by label lookup, never a fixed number; never drives against an FPGA output (tristate the FPGA side first) |
| `uart`       | BIOS banner with the expected ident, then echo test                                                             | Reuses `test_uart.py` semantics |
| `ddr`        | BIOS prints `Memtest OK` for the full main RAM size for the variant                                             | Calibration lines captured for diagnostics |
| `pcie-dma`   | loopback `dma_test` OK; host→DDR→host round trip of ≥ 16 MiB of random data compares equal in both directions; BIOS `mr` over the UART shows the first 64 bytes the host wrote | Throughput logged |
| `pcie-flash` | operational rewrite changes ident after `flash_reload`; corrupt operational falls back to golden; restore succeeds; **golden slot is never written by this test** | Writes to 0x0 require a separate `--i-know-this-writes-golden` flag in the tool and are never run by `verify_hardware.py` |

## 7. Decisions taken in this draft (say so if you want them changed)

1. **x1 PCIe resource everywhere** (lane 0), not the platform's `pcie_x4`, so
   Vivado and open flows are the same design and the Pi 5 link is what we
   test. Upstream LiteX users use x4 on desktop slots; our slot has one lane.
2. **New `designs/acorn-pcie/` directory** with one bitstream and several test
   scripts, rather than adding features to `pcie-enumeration`.
3. **Kernel module is cross-compiled locally** for now; the infra-side
   package is a follow-up in another repo.
4. **The `vivado-xilinx-flows` branch gets a PR and lands first**; everything
   Vivado-related in this plan sits on its Makefile/flow infrastructure.
5. **Factory flash is backed up before it is overwritten**, kept outside git.
6. **JTAG-less boards are not flashed.** p43/p44 wait for hardware.
7. **Host names in `verify_hardware.py` switch to the VLAN scheme** for the
   Acorns now; other boards are migrated when their sections are re-probed.
8. **PR #9's `flash_writer` becomes the fallback path**, not the primary,
   pending the §2.5 re-test.
9. **PCI device ID is `10ee:7021` in every flow** (LitePCIe's x1 default, and
   what `litepcie.ko` binds); the open core is parameterised to match rather
   than the kernel ID table being extended.
10. **Golden and operational images share one driver** by pinning CSR indices,
    rather than building a driver per image.

## 8. Open questions

1. Should the golden image keep the CPU + UART (so a board that fell back is
   still diagnosable on the serial console), or be CSR-only to be as small and
   simple as possible? Draft says keep CPU + UART.
2. Is 3× consecutive clean runs per phase the right gate here, or should this
   reuse `plan.md`'s 10× rule?
3. Do you want the PS1 CLE-101 blades (pi14/pi16/pi20) included in Phase 3
   once their P1 cables are reseated, or is Welland the only target for now?

## References

- PR #11 (docs refresh, this plan's hardware source of truth)
- `docs/hardware/acorn-pcie-programming.md`, `docs/hardware/acorn-pinmap.md`
- `litex_boards/targets/sqrl_acorn.py` (LiteX 2025.12) — reference SoC
- `litepcie/software/user/litepcie_util.c` — `info`, `flash_write`, `flash_reload`, `dma_test`
- Issues #1 (IBUFDS_GTE2 fasm), #2 (Vivado Acorn PCIe bitstream), #4 (Compute Blade wiring)
- fpgas.online-infra PR #32 (Pi 5 header UART), PR #48 (openFPGALoader rp1pio)
