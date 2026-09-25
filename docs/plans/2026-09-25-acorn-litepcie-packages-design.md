# Acorn LitePCIe driver packages: design

Status: design, for review. Nothing here is implemented yet.

This repository's CI builds and publishes Debian packages for the LitePCIe kernel driver (`litepcie.ko`,
with its companion `liteuart.ko`) and the LitePCIe user tools (`litepcie_util`, `litepcie_test`), generated
for the Acorn PCIe SoC (`designs/acorn-pcie/gateware/acorn_pcie_soc.py`).

The work is in three parts, each planned and delivered on its own. **Part A is planned first.**

- **Part A** (§3): the driver source, the CSR cross-check, the compat patch, and the `-common`, `-utils` and
  `-dkms` packages. Their CI artifacts are enough for the #29 test on pi-sw2-p48.
- **Part B** (§4): the prebuilt `-modules-<kver>` packages for every chosen kernel, the daily run, and
  retention.
- **Part C** (§5): changes in fpgas-online/apt so it can serve these packages.

## 1. Intent

What Tim asked for:

- "Have the test-design repo CI properly generate packages for litepcie.ko and litepcie_util on CI."
- The kernel module is shipped **both** as a DKMS source package **and** prebuilt per kernel.
- The user tools are built for **armhf and arm64**, and the driver gets a `compat_ioctl` so the 32-bit tools
  work against a 64-bit kernel.
- The sectioned design presented in conversation was approved on 2026-09-25 ("Approve, write spec").

What this spec assumes (correct these if they are wrong):

- The consumers are Raspberry Pi hosts with an Acorn on PCIe: Pi 5 and Compute Module 4/5 carriers. The
  Welland fleet runs a 32-bit (armhf) userland with a 64-bit `rpi-v8` kernel (`linux-image-6.12.96+rpt-rpi-v8`,
  arm64, installed as a foreign architecture).
- The first user is the #29 DMA test on one board, named here by what identifies it rather than by where it
  is plugged in: the Pi with Ethernet MAC `88:a2:9e:45:85:77` carrying the Acorn whose FPGA DNA is
  `0x0054b48664b04854`. It sits at pi-sw2-p48 today, and that name is only its placement: boards move ports,
  and this Pi was pi-sw2-p46 before. Both identifiers come from its bring-up record (2026-09-22). Loading the
  driver on every boot is a later decision (§7).
- One driver build serves all six Acorn images in the pinned release (§3.2 proves it and CI keeps checking it).

## 2. Packages

| Package | Part | Architecture | Contents |
|---|---|---|---|
| `fpgas-online-acorn-litepcie-common` | A | all | `/etc/modprobe.d/fpgas-online-acorn-litepcie.conf` (`blacklist litepcie`, §3.6) |
| `fpgas-online-acorn-litepcie-dkms` | A | all | driver source under `/usr/src/fpgas-online-acorn-litepcie-<version>/` plus `dkms.conf` building `litepcie` and `liteuart` |
| `fpgas-online-acorn-litepcie-utils` | A | armhf, arm64 | `/usr/bin/litepcie_util`, `/usr/bin/litepcie_test` |
| `fpgas-online-acorn-litepcie-modules-<kver>` | B | the kernel package's (arm64 for `rpi-v8`/`rpi-2712`, armhf for `rpi-v7l`/`rpi-v7`) | `litepcie.ko`, `liteuart.ko` under `/lib/modules/<kver>/updates/fpgas-online/` |

Relationships:

- `-dkms` and every `-modules-<kver>` Depend on `-common` and Provide the virtual package
  `fpgas-online-acorn-litepcie-module`.
- `-modules-<kver>` Depends on `linux-image-<kver>`, and Provides `fpgas-online-acorn-litepcie-prebuilt`.
  `-dkms` Conflicts with `fpgas-online-acorn-litepcie-prebuilt`, so a host carries one or the other, never two
  copies of `litepcie.ko` for the same kernel with depmod choosing between them.
- `-dkms` Depends on `dkms`. It does not depend on any headers package: the RPi headers packages are per kernel
  and the operator installs the ones for their kernel.
- `-utils` Recommends `fpgas-online-acorn-litepcie-module`.
- The modules packages run `depmod -a <kver>` in postinst and postrm.

**Who uses which.**

- **DKMS is for single-architecture, SD-booted hosts**: a Pi whose userland architecture matches its kernel
  and whose root filesystem keeps what DKMS builds.
- **The netbooted fleet uses the prebuilt `-modules-<kver>` packages.** DKMS does not work there, for two
  reasons.
  - *Architectures*: the Welland root is armhf with an arm64 `rpi-v8` kernel. The headers package's
    `.kernelvariables` pins `override ARCH = arm64` and `override CROSS_COMPILE = aarch64-linux-gnu-` (read
    from `linux-headers-6.12.96+rpt-rpi-v8`). Its Depends pull in `gcc-12` and
    `linux-kbuild-6.12.96+rpt`. On an armhf root that means an aarch64 cross toolchain and arm64 kbuild
    tools that the root cannot run.
  - *Storage*: the root is a read-only NFS export under a tmpfs overlay, so anything DKMS builds at boot is
    lost at the next reboot.

`liblitepcie` is not a separate package: `driver/user/Makefile` builds it only as a static archive
(`liblitepcie.a`) and links it into both tools.

## 3. Part A: the driver source, `-common`, `-utils` and `-dkms`

### 3.1 Generation

CI generates the driver at the commit being built, with the dependency versions `uv.lock` pins (at the time
of writing, litepcie `aceef740dbfe`, litex `e2625f98d259`):

    uv run --extra build python designs/acorn-pcie/gateware/acorn_pcie_soc.py \
        --variant cle-215+ --driver --no-compile-software

No Vivado is involved: `--build` is not given, so `builder.build(run=False)` writes Verilog and headers only.
`--no-compile-software` is required: without it LiteX's `Builder` compiles the BIOS, which needs meson and a
RISC-V GCC that the packaging jobs do not have and the driver does not use. The result is
`designs/acorn-pcie/build/acorn-cle-215+/driver/{kernel,user}`: LitePCIe's `software/` tree copied verbatim,
plus the generated `kernel/csr.h`, `kernel/soc.h` and `kernel/mem.h`.

### 3.2 One driver for every image: the CSR cross-check

The generated headers describe the cle-215+ operational image. The driver and tools must work unchanged on
the golden image and on the cle-215 and cle-101 variants. Today they do: `acorn_pcie_soc.py` pins every
shared CSR with `csr_map`, and in release `vivado-bitstreams-acorn-pcie-20260923-ge48a750c8303` all six
`csr.json` agree on everything the driver reads (`dma_channels` 1, `dma_addr_width` 64,
`pcie_dma0_reader_interrupt` 0, `pcie_dma0_writer_interrupt` 1, and the same addresses for `ctrl_reset`, the
identifier memory, `pcie_msi_*`, `pcie_dma0`, `flash_spi_*`, `icap_*` and `uart_xover_*`). The golden images
leave out `ddrphy`, `sdram` and `p2_gpio`, which the driver never touches. cle-101 differs only in
`MAIN_RAM_SIZE`.

CI keeps this true. A check script:

1. Fetches the six `csr.json` of the release pinned in `packaging/acorn-pcie/release.toml`, verifying the
   manifest against `manifest_sha256` and each file against its manifest entry, as `build_debs.py` already
   does.
2. Collects every `CSR_*` macro and every `soc.h` constant that the sources under `driver/kernel` and
   `driver/user` reference, **including those they only test with `#ifdef`**.
3. Fails unless each one agrees between the generated headers and all six `csr.json` in **presence and
   value**: defined in all or in none, and equal wherever defined.

Presence matters as much as value. The sources compile different code depending on which CSRs exist:

| `#ifdef` | where | when it is defined, the build... |
|---|---|---|
| `CSR_XADC_BASE`, `CSR_DNA_BASE` | `user/litepcie_util.c` | ...prints temperatures/voltages and the FPGA DNA |
| `CSR_FLASH_BASE` | `user/litepcie_util.c`, `user/liblitepcie/litepcie_flash.c` | ...has the flash commands at all |
| `CSR_FLASH_BPI_CONTROL_ADDR`, `CSR_FLASH_SPI_CONTROL_ADDR` | `user/liblitepcie/litepcie_flash.c` | ...uses the BPI or the SPI flash path |
| `CSR_PCIE_DMA1_BASE` … `CSR_PCIE_DMA7_BASE` | `kernel/main.c` | ...sets up that DMA channel |
| `CSR_PCIE_MSI_PBA_ADDR` | `kernel/main.c` | ...asks for MSI-X instead of MSI |
| `CSR_PCIE_MSI_CLEAR_ADDR`, `CSR_CTRL_RESET_ADDR`, `CSR_UART_XOVER_RXTX_ADDR`, `CSR_ICAP_BASE`, `CSR_FLASH_SPI_CONTROL_ADDR` | `kernel/main.c` | ...turns on MSI clearing, the reset at probe, the liteuart device, ICAP, SPI flash |

A driver built from headers where one of these is present, run on an image where it is absent (or the other
way round), does the wrong thing without any error. Today every image agrees: none has `pcie_msi_pba`,
`flash_bpi_*` or `pcie_dma1`…`7`, and all six have the rest.

The header names map to `csr.json` keys like this (as LiteX exports them, checked against the pinned
release):

| header | `csr.json` |
|---|---|
| `CSR_<NAME>_ADDR` (`csr.h`) | `csr_registers["<name>"]["addr"]`, name lower-cased: `CSR_PCIE_MSI_ENABLE_ADDR` → `pcie_msi_enable` |
| `CSR_<NAME>_BASE` (`csr.h`) | `csr_bases["<name>"]`: `CSR_PCIE_DMA0_BASE` → `pcie_dma0` |
| `CSR_BASE` (`csr.h`) | `memories["csr"]["base"]` |
| `<NAME>` constants (`soc.h`) | `constants["<name>"]`: `DMA_CHANNELS` → `dma_channels`, `PCIE_DMA0_WRITER_INTERRUPT` → `pcie_dma0_writer_interrupt` |

Not every `DMA_*` name comes from the SoC:

- `DMA_CHANNELS` and `DMA_ADDR_WIDTH` are SoC constants in `soc.h`, so the check covers them.
- `DMA_BUFFER_COUNT`, `DMA_BUFFER_SIZE`, `DMA_BUFFER_PER_IRQ`, `DMA_IRQ_DISABLE`, `DMA_LAST_DISABLE` and the
  `PCIE_DMA_*_OFFSET` values are fixed in litepcie's `kernel/config.h`. `DMA_CHANNEL_COUNT` is also defined
  there, as `DMA_CHANNELS`. None of these is in `csr.json`, so they are outside the check. They change only
  with the litepcie pin in `uv.lock`, which is a version input (§3.7).

A gateware change that moves a CSR the driver uses therefore fails CI until the driver question is settled
(a new release, or a driver per image), rather than shipping a driver that is wrong for part of the fleet.

### 3.3 compat_ioctl

`litepcie_fops` sets only `.unlocked_ioctl`, so a 32-bit process calling an ioctl on a 64-bit kernel gets
`ENOTTY`. That is the Welland fleet's case: armhf tools on an `rpi-v8` kernel.

The fix is one line, applied as a patch in the packaging step:

    .compat_ioctl = compat_ptr_ioctl,

`compat_ptr_ioctl` (Linux ≥ 5.5) is correct only when every ioctl argument struct has the same layout for
32-bit ARM EABI as for arm64, so that the kernel can pass the converted pointer straight to the 64-bit
handler. Measured with GCC's `_Static_assert` for `arm-linux-gnueabihf` and for `aarch64-linux-gnu`, the two
layouts are identical:

| struct | size | 64-bit fields at |
|---|---|---|
| `litepcie_ioctl_reg` | 12 | none |
| `litepcie_ioctl_flash` | 24 | `tx_data` 8, `rx_data` 16 |
| `litepcie_ioctl_icap` | 8 | none |
| `litepcie_ioctl_dma` | 1 | none |
| `litepcie_ioctl_dma_writer`, `_dma_reader` | 24 | `hw_count` 8, `sw_count` 16 |
| `litepcie_ioctl_lock` | 6 | none |
| `litepcie_ioctl_mmap_dma_info` | 48 | all six |
| `litepcie_ioctl_mmap_dma_update` | 8 | `sw_count` 0 |

The ARM EABI aligns 64-bit integers to 8 bytes, as arm64 does (i386 would not, which is why this is not a
general property). CI compiles a test file with these asserts for both architectures, so a future litepcie
struct change that breaks the equivalence fails the build. The `mmap` offsets the tools use (0 and 2 MiB) fit
a 32-bit `off_t`.

The same line goes upstream as a pull request to enjoy-digital/litepcie. The packaging patch step fails when
the line is already present, so the patch is dropped as soon as `uv.lock` moves to a litepcie that carries
it.

### 3.4 liteuart

`liteuart.ko` is shipped because every image in the pinned release has the crossover UART
(`uart_xover_rxtx` is in all six `csr.json`), so `litepcie.ko`'s probe registers a `liteuart` platform device
(`main.c`, `#ifdef CSR_UART_XOVER_RXTX_ADDR`). Without `liteuart.ko` that device never binds and the SoC's
console is not reachable as `/dev/ttyLXU*`.

**The liteuart alias is broken upstream and is patched.** `liteuart.c` declares
`MODULE_ALIAS("platform: liteuart")`, with a space. The device's modalias is `platform:liteuart`, so udev
never matches it and `liteuart.ko` never loads by itself. The packaging applies a second one-line patch
alongside the compat one, making it `MODULE_ALIAS("platform:liteuart")`.

Patching beats documenting `modprobe liteuart` as an operator step:

- it is a plain bug with a one-character fix;
- it goes upstream in the same litepcie pull request as §3.3;
- with it, `modprobe litepcie` is the whole procedure, and nothing depends on an operator remembering a
  second module.

Like the compat patch, the step fails once upstream carries the fix, so it is dropped then. `liteuart` is not
blacklisted: it can only bind to the device that `litepcie.ko` registers, so it loads only when litepcie has
been loaded on purpose. The Pi kernel builds no in-tree LiteUART driver (`CONFIG_SERIAL_LITEUART` is unset in
`config-6.12.96+rpt-rpi-v8`), so nothing else claims the name `liteuart`.

### 3.5 Builds

All builds run in Docker on GitHub's `ubuntu-24.04-arm` runners. armhf builds use
`docker run --platform linux/arm/v7`, which fpgas.online-fpga-tools' `debs.yml` already does successfully.

- **dkms, common**: once per run, architecture-independent. `dkms.conf` calls kbuild directly and does not
  use the upstream `driver/kernel/Makefile`. That Makefile sets `ARCH?=$(shell uname -m)`, which is
  `aarch64` on arm64, not the kernel's `arm64`, and it finds the kernel through `KERNEL_PATH` (from
  `uname -r`) rather than the kernel DKMS is building for:

      PACKAGE_NAME="fpgas-online-acorn-litepcie"
      PACKAGE_VERSION="<X.Y.postN>"
      MAKE[0]="make -C ${kernel_source_dir} M=${dkms_tree}/${PACKAGE_NAME}/${PACKAGE_VERSION}/build modules"
      CLEAN="make -C ${kernel_source_dir} M=${dkms_tree}/${PACKAGE_NAME}/${PACKAGE_VERSION}/build clean"
      BUILT_MODULE_NAME[0]="litepcie"
      BUILT_MODULE_NAME[1]="liteuart"
      DEST_MODULE_LOCATION[0]="/updates/dkms"
      DEST_MODULE_LOCATION[1]="/updates/dkms"
      AUTOINSTALL="yes"

  kbuild reads the source's `Makefile` only for its `obj-m` list (`litepcie.o liteuart.o`,
  `litepcie-objs = main.o`), and that list is what gets built.
- **utils**: in `debian:bookworm` for arm64 and for armhf. Bookworm's glibc (2.36) is the older of the two
  fleet suites, so the same binaries install on trixie.
- **the fleet kernel's modules, as a CI artifact only**: one build of `litepcie.ko` and `liteuart.ko`
  against the kernel the netbooted fleet runs, named as `fleet_kernel` in
  `packaging/acorn-litepcie/kernels.toml` (today `6.12.96+rpt-rpi-v8`, bookworm). It is built the way §4.1
  builds a module and uploaded as a workflow artifact, not as a package. This is what makes Part A usable on
  pi-sw2-p48 before Part B exists: DKMS cannot serve that host (§2).

A new workflow, `.github/workflows/acorn-litepcie.yml`, builds on pull requests (no publishing), on pushes to
main, daily, and on demand. On main it uploads to the current `vX.Y` series release, the rolling pre-release
that `acorn-debs.yml` already publishes to. It sits apart from `acorn-debs.yml` because its matrix, its
runners (arm64) and its daily schedule are all different.

### 3.6 What installing the packages does to a host

Nothing changes on a running host until an operator loads the module.

- **No autoload.** `litepcie.ko` has a `MODULE_DEVICE_TABLE(pci, …)` that includes `10ee:7021`. Installed
  and depmod'ed, udev would load it on every boot for every Acorn running our SoC. `-common`'s
  `blacklist litepcie` stops that alias autoload, while `modprobe litepcie` still loads it on purpose.
  Without the blacklist, installing the packages would silently turn on boot-time loading, which §7 keeps out
  of scope.
- **Loading resets the SoC.** Probe writes `CSR_CTRL_RESET_ADDR`, so `modprobe litepcie` resets the SoC's
  CPU and logic. DDR3 recalibrates, and anything an operator had running on the SoC is lost.
- **One user at a time, enforced by the tools, because the kernel does not.**
  - *What collides*: probe claims BAR0 (`pcim_iomap_regions`). `fpgas-acorn-verify` and `fpgas-acorn-flash`
    (spi_flash.py) drive BAR0 directly through sysfs `resource0`, and serialise only with each other
    (`spi_flash.LOCK`). The driver's flash ioctl does not take that lock.
  - *Nothing stops them*: the fleet kernel has `# CONFIG_STRICT_DEVMEM is not set` (read from
    `config-6.12.96+rpt-rpi-v8`), so `IO_STRICT_DEVMEM` is off. The kernel neither revokes nor refuses a
    `resource0` mapping of a BAR a driver holds, and both would drive the same CSRs at once.
  - *Decision*: `fpgas-acorn-verify` and `fpgas-acorn-flash` check `/sys/bus/pci/devices/<bdf>/driver`
    before they open BAR0. When `litepcie` is bound, they touch nothing on that device and report it.
    - The boot check's board result is then `driver-bound`, with the reason "litepcie.ko is bound: not
      checked". `driver-bound` ranks between `pass` and `degraded` in `SEVERITY`.
    - Its exit status is non-zero, because the board has not been verified. An operator who loaded the
      driver on purpose sees the unit fail for that reason, and nothing else.
    - `fpgas-acorn-flash` refuses with the same message.
  - *Where it lands*: this is a change to `designs/acorn-pcie/host/`, shipped in `fpgas-online-acorn-tools`,
    with tests in `tests/test_acorn_verify.py` against a fake sysfs. It belongs to Part A.
- **Load order.** The check cannot stop a driver being loaded while it is already running, so operators do
  not load the driver while the boot check or a flash operation runs.

### 3.7 Versions

Versions are `X.Y.postN` from `git describe`, like every other deb this repository builds (`git_version()`
in `build_debs.py`). They are never dates.

The driver packages take their version from **the last commit that changed the driver's inputs**, not from
HEAD. The inputs are:

- `packaging/acorn-litepcie/`, which holds the patches, `dkms.conf`, `kernels.toml` and the build scripts.
  This is deliberately a new directory, not `packaging/acorn-pcie/`. That one holds `release.toml`, the
  bitstreams pin, which moves on its own schedule. If it were a version input, every pin move would give the
  driver a new version and rebuild every module, even though the driver had not changed. A pin move that does
  change a CSR the driver uses is caught by the cross-check (§3.2), which reads `release.toml` whatever
  directory it is in;
- `designs/acorn-pcie/gateware/acorn_pcie_soc.py`;
- `designs/_shared/`, which `acorn_pcie_soc.py` imports: `migen_compat`, `build_helpers`, `dna_reader`,
  `pin_check`, `s7pcie_clocking` and `uartbone_break`;
- `uv.lock`;
- `.github/workflows/acorn-litepcie.yml`.

The version is `git describe` of `git log -1 --first-parent --format=%H -- <inputs>`. Otherwise every merge to main
would bump the version and rebuild all 63 modules (§4). That would add 63 assets to the series release per
merge, and a GitHub release holds at most 1000 assets.

`--first-parent` is what keeps versions from going backwards. Without it, `git log` can return a commit
from a merged side branch, one that was written before an earlier main commit. That commit's `git describe`
count is lower, so the new version would sort below one already published. With it, the commit found is
always one on main's first-parent line: the merge commit that brought the change in. N then only grows as
main moves.

`-modules-<kver>` versions add the suite: `X.Y.postN+bookworm` or `X.Y.postN+trixie`.

### 3.8 Tests

CI, on every pull request:

- the driver generation (§3.1) and the CSR cross-check (§3.2);
- the struct-layout asserts, compiled for armhf and arm64 (§3.3);
- the compat and liteuart-alias patches apply, and neither is already present upstream;
- the `driver-bound` refusal in `fpgas-acorn-verify` and `fpgas-acorn-flash` (fake-sysfs unit tests);
- builds of `-common`, `-dkms` and `-utils` (armhf, arm64), and the fleet-kernel module artifact with its
  vermagic check;
- a DKMS test in the shape DKMS is for (§2), a single-architecture `debian:bookworm` arm64 container: install
  the headers for the newest v8 kernel and the `-dkms` deb, run `dkms install -k <kver>`, then check that
  `modinfo -k <kver> litepcie liteuart` resolves. The fleet's shape (armhf root, arm64 kernel) is not tested
  with DKMS, because it is not supported there. Part B's install test (§4.4) covers it with prebuilt modules.

On hardware, on the test board of §1 (MAC `88:a2:9e:45:85:77`, DNA `0x0054b48664b04854`; today at pi-sw2-p48), running the #29 cle-215+ image from SRAM. It uses Part A's CI artifacts: the
armhf `-utils` and `-common` debs, and the fleet-kernel `.ko` files, copied to the host's tmpfs. These are
operator steps, run once:

1. Stop anything using BAR0.
2. `insmod` the artifact `liteuart.ko`, then `litepcie.ko`. `insmod` resolves no aliases, so both are loaded
   by hand here. With Part B's package installed, `modprobe litepcie` alone is enough, and the patched alias
   (§3.4) brings in `liteuart`. dmesg shows the identifier, `/dev/litepcie0` and a `ttyLXU` port.
3. `litepcie_util info` (armhf tools against the arm64 kernel, which exercises compat_ioctl).
4. The #29 DMA test.
5. `rmmod litepcie liteuart`. Then `fpgas-acorn-verify --no-publish --report -` still reports the board
   correctly, which proves the driver leaves BAR0 access as it found it.

## 4. Part B: prebuilt modules per kernel

### 4.1 Builds

**modules**: one job per (suite, kernel) pair. It uses the suite's Debian image with the Raspberry Pi archive
(`archive.raspberrypi.com/debian`) added, installs `linux-headers-<kver>` for the kernel's architecture, and
runs `make -C /usr/src/linux-headers-<kver> M=$PWD modules` on the generated `driver/kernel`. It then checks
that `modinfo -F vermagic` of each `.ko` starts with `<kver> ` and fails if not.

### 4.2 Which kernels

The RPi archive keeps every kernel it has ever shipped. On 2026-09-25 its indexes listed:

| suite / arch | flavour | kernels |
|---|---|---|
| bookworm / arm64 | `rpi-v8` | 25: seven `6.1.0-rpiN` (6.1.21 … 6.1.73), seven 6.6.x, eleven 6.12.x (6.12.19 … 6.12.109) |
| bookworm / arm64 | `rpi-2712` | 23: five `6.1.0-rpiN` (from `6.1.0-rpi3`, 6.1.47), seven 6.6.x, eleven 6.12.x |
| bookworm / armhf | `rpi-v6`, `rpi-v7`, `rpi-v7l` | 25 each, the same kernels as `rpi-v8` |
| trixie / arm64 | `rpi-v8`, `rpi-2712` | 10 each, 6.12.25 … 6.18.50 |
| trixie / armhf | `rpi-v6`, `rpi-v7` (no `rpi-v7l`) | 10 each, 6.12.25 … 6.18.50 |
| bookworm, trixie / arm64 | `rpi-v8-rt` | the real-time flavour: 8 on bookworm and 10 on trixie, all 6.12 or later |

The 6.1 kernels are named `6.1.0-rpiN` (`linux-headers-6.1.0-rpi8-rpi-v8`), not by their upstream version, so
the matrix script compares the package's Version (`1:6.1.73-1+rpt1`), not its name, against the floor. The
unversioned meta packages (`linux-headers-rpi-v8` and the like) are skipped.

The build set is:

- **Flavours**: bookworm `rpi-v8`, `rpi-2712` and `rpi-v7l`; trixie `rpi-v8`, `rpi-2712` and `rpi-v7`.
  These are the kernels a PCIe-capable Pi (Pi 5, CM4, CM5) can boot, 64-bit or 32-bit. `rpi-v6` and
  bookworm's `rpi-v7` are for older Pis (Zero, 2, 3), which have no PCIe. Trixie ships no `rpi-v7l`, so its
  `rpi-v7` is the only 32-bit ARMv7 flavour left there. Which boards it targets has not been checked yet,
  and the first trixie host with an Acorn confirms it. **`rpi-v8-rt` is left out on purpose.** No fpgas.online
  host runs the real-time kernel, and building it would add 18 modules today (8 bookworm, 10 trixie) that
  nothing installs. Adding it later is one line in `kernels.toml`.
- **Versions**: every kernel from 6.12 onwards. The fleet runs 6.12, and 6.1 and 6.6 are kernels no current
  host boots. That is 63 builds today (bookworm 11 × 3, trixie 10 × 3). "Every kernel" with no floor would
  be 103.
- **Configuration**: the flavours and the floor live in one file, `packaging/acorn-litepcie/kernels.toml`.
  A script turns that file and the live `Packages` indexes into the job matrix.

A new RPi kernel is picked up by a **daily** scheduled run. A run builds only the (suite, kernel, driver
version) triples that have no asset on the series release yet, so a quiet day builds nothing, and a new
kernel costs one build per flavour.

The same kernel name can exist in both suites with different builds: `linux-headers-6.12.34+rpt-rpi-v8` is
`1:6.12.34-1+rpt1~bookworm` in bookworm and `1:6.12.34-1+rpt1` in trixie, built with GCC 12 and GCC 14.
Modules are therefore built per suite and never shared between suites.

### 4.3 Retention, pruning and the kernel floor

**Two budgets are at stake.**

- *The series release.* A GitHub release holds at most 1000 assets, and the `vX.Y` series release is shared:
  `acorn-debs.yml` uploads `fpgas-online-acorn-bitstreams` and `fpgas-online-acorn-tools` there. On
  2026-09-25 `v0.0` held 9 assets, 2 bitstreams and 7 tools; the tools deb adds one per merge.
- *The apt pool.* fpgas-online/apt commits every deb it pulls into `pool/main/` in git (29 debs, 3.7 MiB on
  2026-09-25), and nothing there is ever deleted.

**Release retention (this repository, Part B).** After a run has uploaded a complete new set,
`acorn-litepcie.yml` prunes the litepcie assets.

- *What stays*: for every `fpgas-online-acorn-litepcie-*` package, the assets of the current driver version
  and of the one before it, so a host can roll back one version. Everything older is deleted from the
  release.
- *Where old versions live*: in the apt pool. Removing an asset from the release does not remove a deb
  fpgas-online/apt has already pulled. `pull_debs.py` also counts a package as offered while any version
  remains, so the prefix entry never goes stale.
- *Only its own assets*: pruning never touches assets of other packages.
- *Headroom for acorn-debs*: before uploading, the workflow counts the release's assets and fails if the
  upload would take it past 900.

Two driver versions of 63 modules, plus `-common`, `-dkms` and two `-utils`, come to about 134 assets.

**Pool retention (fpgas-online/apt, Part C).** fpgas-online/apt keeps the newest two versions of each
`fpgas-online-acorn-litepcie-*` package in `pool/main/` and removes older ones in the same commit that adds a
new one. Removal only happens there, because the pool is that repository's.

**Raising the floor.** `min_kernel` in `packaging/acorn-litepcie/kernels.toml` is the floor.

- *Raising it* is a reviewed pull request that edits that one value. The next run neither builds nor keeps
  modules for kernels below it: their assets are pruned from the release by the same step.
  fpgas-online/apt's pool retention then drops them from the pool as newer versions arrive.
- *Guard*: CI fails if `fleet_kernel` (§3.5) is below `min_kernel`, so the floor can never drop the kernel
  the fleet boots.

**Scheduled runs and inactivity.** GitHub disables scheduled workflows in a public repository after 60 days
with no repository activity. Workflow runs do not count as activity; pushes do.

- *What stops*: the daily run. When it stops, new RPi kernels stop getting modules, with no error anywhere.
  Pushes to main keep building, because that trigger is not affected.
- *Mitigation*: fpgas-online/apt's `pull-debs.yml` (every 15 minutes) reads this workflow's state from the
  public API. `GET /repos/fpgas-online/fpgas.online-test-designs/actions/workflows/acorn-litepcie.yml` returns
  `"state": "disabled_inactivity"` once it has been disabled. The check fails that run loudly, naming the fix:
  `gh workflow enable acorn-litepcie.yml -R fpgas-online/fpgas.online-test-designs`.
- *Why the watcher sits elsewhere*: a workflow cannot report its own disabling, so the check lives in
  another repository.

### 4.4 Tests

- on pull requests, a **sample** of `-modules-<kver>`: the newest kernel of each (suite, flavour). Main and
  the daily run build the full set;
- the vermagic check on every module built;
- an install test in `debian:bookworm` under `--platform linux/arm/v7`, the fleet's shape:
  1. `dpkg --add-architecture arm64`, then install the RPi `linux-image-<newest v8 kver>:arm64` and the
     built `-common`, `-modules-<kver>` and `-utils` debs through apt from a local flat repository;
  2. check that `modinfo -k <kver> litepcie liteuart` resolves, and that the blacklist is in place;
  3. check that `litepcie_util` prints its usage.

## 5. Part C: fpgas-online/apt

fpgas-online/apt pulls from the series release. Its current design does not fit these packages, so this needs
a pull request there first:

- `tools/pull_debs.py` matches each `package_sources.toml` entry as an exact package name (`<package>_`).
  One package per kernel needs a prefix entry (`"fpgas-online-acorn-litepcie-modules-*"`), counted as
  offered when any matching asset exists.
- `publish.yml` gives every suite the whole pool ("Every package is Architecture: all"). Suite-specific debs
  need routing: a deb whose version ends in `+<suite>` goes only to that suite, and everything else goes to
  all suites, as now.
- Architecture-specific packages in a flat repository are already accepted by `pull_debs.py`'s asset-name
  pattern (`amd64|arm64|armhf`). The install test in §4.4 proves apt resolves them on an armhf host with
  arm64 as a foreign architecture.

If that apt change is not wanted, the fallback is what fpgas.online-fpga-tools does: publish this
repository's own per-suite archive with `mithro/apt-repo-action` (`debs-<suite>-<arch>` artifacts). That
means the Pis need one more apt source. **Decision for Tim**: extend fpgas-online/apt (recommended, because
the Pis keep one source for test-design packages) or run a separate archive.

## 6. Plan order

1. Part A. Its CI artifacts are what the #29 test on pi-sw2-p48 uses.
2. Part B.
3. Part C, once Tim has decided between extending fpgas-online/apt and a separate archive.

## 7. Out of scope

- **Loading the module at boot.** That needs its own design.
  - It must settle whether the boot check reads through the driver (its ioctls) or unbinds it first. Until
    then, a bound driver makes the check report `driver-bound` (§3.6).
  - Whether the kernel would police `resource0` is already answered: it does not (`CONFIG_STRICT_DEVMEM`
    unset).
  - The reset on probe (§3.6) means the driver must load before, not during, anything that uses the SoC.
- **The CI trigger.** This repository used to build every pull request twice (push and pull_request). #41
  already fixed that: `push` is limited to main and a concurrency group cancels stale runs. The new workflow
  follows the same pattern.
- **Other LitePCIe designs.** NeTV2 and other boards get their own driver packages only if they need them.
  The CSR cross-check is specific to the Acorn release.
