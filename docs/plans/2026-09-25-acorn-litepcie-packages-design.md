# Acorn LitePCIe driver packages: design

Status: Parts A and B are implemented (Part A's plan: `docs/plans/2026-09-26-acorn-litepcie-part-a-plan.md`).
Part C, in fpgas-online/apt, is design only.

This repository's CI builds and publishes Debian packages for the LitePCIe kernel driver (`litepcie.ko`,
with its companion `liteuart.ko`) and the LitePCIe user tools (`litepcie_util`, `litepcie_test`), generated
for the Acorn PCIe SoC (`designs/acorn-pcie/gateware/acorn_pcie_soc.py`).

The work is in three parts, each planned and delivered on its own. **Part A is planned first.**

- **Part A** (§3): the driver source, the CSR cross-check, the driver patches, and the `-common`, `-utils` and
  `-dkms` packages. Their CI artifacts are enough for the #29 test on pi-sw2-p48.
- **Part B** (§4): the prebuilt `-modules-<kver>` packages for every chosen kernel, the meta package, the
  x86 builds of `-utils` and of the DKMS test, and this repository's own apt archive with its daily run.
- **Part C** (§5): fpgas-online/apt bundles that archive, so a host keeps one apt source.

## 1. Intent

What Tim asked for:

- "Have the test-design repo CI properly generate packages for litepcie.ko and litepcie_util on CI."
- The kernel module is shipped **both** as a DKMS source package **and** prebuilt per kernel.
- The user tools are built for **armhf and arm64**, and the driver gets a `compat_ioctl` so the 32-bit tools
  work against a 64-bit kernel.
- The sectioned design presented in conversation was approved on 2026-09-25 ("Approve, write spec").
- "Prebuilt modules for all the rpi kernels on rpi5 hardware", and the "DKMS package - for arm & x86"
  (2026-10-02). §4.2 says which kernels that is.
- The packages are published in this repository's own per-suite signed apt archive on GitHub Pages, through
  the shared machinery of mithro/apt-repo-action, and fpgas-online/apt bundles that archive, so the Pis keep
  one apt source (2026-10-02). §4.3 and §5.

What this spec assumes (correct these if they are wrong):

- The consumers are Raspberry Pi hosts with an Acorn on PCIe: Pi 5 and Compute Module 4/5 carriers. The
  Welland fleet runs a 32-bit (armhf) userland with a 64-bit `rpi-v8` kernel (on 2026-09-26
  `linux-image-6.12.109+rpt-rpi-v8`, arm64, installed as a foreign architecture).
- The first user is the #29 DMA test on one board, named here by what identifies it rather than by where it
  is plugged in: the Pi with Ethernet MAC `88:a2:9e:45:85:77` carrying the Acorn whose FPGA DNA is
  `0x0054b48664b04854`. It sits at pi-sw2-p48 today, and that name is only its placement: boards move ports,
  and this Pi was pi-sw2-p46 before. Both identifiers come from its bring-up record (2026-09-22). Loading the
  driver on every boot is a later decision (§7).
- One driver build serves all six Acorn images in the pinned release (§3.2 proves it and CI keeps checking it).

## 2. Packages

| Package | Part | Architecture | Contents |
|---|---|---|---|
| `fpgas-online-acorn-litepcie-common` | A | all, `Multi-Arch: foreign` | `/etc/modprobe.d/fpgas-online-acorn-litepcie.conf` (`blacklist litepcie`, §3.7) |
| `fpgas-online-acorn-litepcie-dkms` | A | all | driver source under `/usr/src/fpgas-online-acorn-litepcie-<X.Y.postN>/` plus `dkms.conf` building `litepcie` and `liteuart` |
| `fpgas-online-acorn-litepcie-utils` | A, B | armhf, arm64, amd64 | `/usr/bin/litepcie_util`, `/usr/bin/litepcie_test` |
| `fpgas-online-acorn-litepcie-modules-<kver>` | B | the kernel package's: arm64 for `rpi-v8` and `rpi-2712`; `Multi-Arch: foreign` | `litepcie.ko`, `liteuart.ko` under `/lib/modules/<kver>/updates/fpgas-online/` |
| `fpgas-online-acorn-litepcie` | B | all | nothing: the meta package a host asks for |

The first four are in this repository's apt archive (§4.3), built once per suite. The meta package is one
file for every suite, published as an asset of the rolling `vX.Y` series release, where fpgas-online/apt
collects it (§5).

Relationships:

- `-dkms` and every `-modules-<kver>` Depend on `-common` and Provide the virtual package
  `fpgas-online-acorn-litepcie-module`.
- `-modules-<kver>` Depends on `linux-image-<kver>`, and Provides `fpgas-online-acorn-litepcie-prebuilt`.
  `-dkms` Conflicts with `fpgas-online-acorn-litepcie-prebuilt`, so a host carries one or the other, never two
  copies of `litepcie.ko` for the same kernel with depmod choosing between them.
- `-dkms` Depends on `dkms`. It does not depend on any headers package: the RPi headers packages are per kernel
  and the operator installs the ones for their kernel.
- `-utils` Suggests `fpgas-online-acorn-litepcie-module`. Not Recommends: apt installs Recommends by default
  and would pull `-dkms`, `dkms` and a compiler into the fleet's armhf root, where DKMS cannot work (below).
- The modules packages run `depmod -a <kver>` in postinst and postrm. The postrm runs it only while the
  kernel's own modules (`/lib/modules/<kver>/kernel`) are still installed, so that removing the kernel and its
  modules package together leaves no index files behind.
- **The meta package** Depends on `fpgas-online-acorn-litepcie-common`, `fpgas-online-acorn-litepcie-utils`
  and `fpgas-online-acorn-litepcie-dkms | fpgas-online-acorn-litepcie-module`.
  - *Why `-dkms` is first*: apt installs the first alternative it can. On an ordinary host that is DKMS,
    which is what such a host wants. A host that already has a `-modules-<kver>` package satisfies the
    dependency through the virtual package, and gets no DKMS, compiler or headers. The netboot root installs
    its kernel's modules package first, then the meta package.
  - *Why it exists*: fpgas-online/apt bundles from this archive what its own packages Depend on (§5), and
    this package is the root of that.
- **`Multi-Arch: foreign`** on `-common` and on every `-modules-<kver>`. On the fleet the modules package is
  arm64 and the root is armhf. apt lets a package of one architecture satisfy a dependency of a package of
  another only when it is marked foreign: `-common` (Architecture: all, which apt counts as armhf there) for
  the arm64 modules package, and the arm64 modules package's Provides for the meta package.

**Who uses which.**

- **DKMS is for single-architecture hosts whose root filesystem keeps what DKMS builds**: an SD-booted Pi
  whose userland architecture matches its kernel, or an x86 PC with an Acorn in an M.2 slot. The x86 host
  takes `-dkms` and the amd64 `-utils`; no prebuilt modules are made for x86 kernels.
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
  with the litepcie pin in `uv.lock`, which is a version input (§3.8).

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

### 3.5 The coherent DMA mask

**The third patch.** On kernels from 5.18 onwards `main.c`'s probe calls
`dma_set_mask(&dev->dev, DMA_BIT_MASK(DMA_ADDR_WIDTH))`. That sets the streaming mask only. The coherent mask
stays at the 32-bit default, and every buffer the driver takes comes from `dmam_alloc_coherent`, which obeys
the coherent mask.

On a Pi 5 that fails every allocation. pcie1's `dma-ranges` put host RAM at bus address `0x10_0000_0000`, so
no RAM is reachable below 4 GiB on the bus, and each `dmam_alloc_coherent` returns `-ENOMEM` (-12). This was
seen on the test board of §1 (pi-sw2-p48, 2026-09-25), and a build with the patch below loaded and bound
there.

The patch replaces the call with the one that sets both masks:

    ret = dma_set_mask_and_coherent(&dev->dev, DMA_BIT_MASK(DMA_ADDR_WIDTH));

It sets both masks from the SoC's `DMA_ADDR_WIDTH` (64, §3.2). Like the other two, it is applied in the
packaging step, the step fails once upstream carries it, and it goes upstream in the same litepcie pull
request.

### 3.6 Builds

Every Arm build runs in Docker on GitHub's `ubuntu-24.04-arm` runners. armhf builds use
`docker run --platform linux/arm/v7`, which fpgas.online-fpga-tools' `debs.yml` already does successfully.
The amd64 builds run in Docker on `ubuntu-latest`.
The driver generation and the architecture-independent `-common` and `-dkms` run on `ubuntu-latest`: they
are Python and nfpm only, and LiteX elaborates the SoC faster there.

- **dkms, common**: architecture-independent, packaged once per suite from the same files (§3.8).
  `dkms.conf` calls kbuild directly and does not
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
- **utils**: for arm64, armhf and amd64, in each suite's own Debian image (`debian:bookworm`,
  `debian:trixie`), so each suite's tools are linked against that suite's glibc; the package's `libc6`
  dependency is the highest glibc symbol version the binaries use. The struct-layout asserts of §3.3 are
  compiled in every one of those builds. There is no i386 build: i386 aligns 64-bit integers to 4 bytes, so
  its ioctl structs would not match the 64-bit kernel's (§3.3).
- **the fleet kernel's modules, on every pull request**: the kernel the netbooted fleet runs is named as
  `fleet_kernel` in `packaging/acorn-litepcie/kernels.toml` (`6.12.109+rpt-rpi-v8`, bookworm). Every pull
  request builds its `-modules-<kver>` package (§4.4), and that job also uploads the bare `litepcie.ko` and
  `liteuart.ko` as the workflow artifact `acorn-litepcie-modules-<kver>`, for a host that loads them with
  `insmod` without installing a package (§3.9).

Two workflows, laid out as mithro/apt-repo-action's `docs/packaging.md` asks of every packaging repository:

- `.github/workflows/deb.yml` (`Debian packages`) runs on pull requests, on pushes to main, daily and on
  demand. Its jobs are `test`, `build-deb`, `publish-apt` and `release` (§4.3).
- `.github/workflows/acorn-litepcie.yml` holds the builds. `deb.yml` calls it as its `build-deb` job. Started
  by hand on any branch, it builds every kernel's modules and publishes nothing.

The Raspberry Pi archive is trusted through the keyring `raspberrypi-archive-keyring` 2025.1+rpt1 ships
(key `CF8A1AF502A2AA2D763BAE7E82B129927FA3303E`), kept in `packaging/acorn-litepcie/`. The copy of that key
at `archive.raspberrypi.com/debian/raspberrypi.gpg.key` carries a SHA-1 self-signature, which trixie's apt
refuses.

### 3.7 What installing the packages does to a host

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
    before they open BAR0. When `litepcie` is bound, they touch nothing on that device and report it. Any
    other bound driver (`vfio-pci`, say) owns BAR0 just the same and is treated alike, named in the reason.
    - The boot check's board result is then `driver-bound`, with the reason "litepcie.ko is bound: not
      checked". `driver-bound` ranks between `pass` and `degraded` in `SEVERITY`. A board on SQRL's factory
      or the vendor XDMA image is still `unconverted`: that is known from config space alone.
    - Its exit status is non-zero, because the board has not been verified. An operator who loaded the
      driver on purpose sees the unit fail for that reason, and nothing else.
    - `fpgas-acorn-flash` refuses with the same message.
  - *Where it lands*: this is a change to `designs/acorn-pcie/host/`, shipped in `fpgas-online-acorn-tools`,
    with tests in `tests/test_acorn_verify.py` against a fake sysfs. It belongs to Part A.
- **Load order.** The check cannot stop a driver being loaded while it is already running, so operators do
  not load the driver while the boot check or a flash operation runs.

### 3.8 Versions

Versions follow mithro/apt-repo-action's `docs/packaging.md` ("Versions", Set B), as every fpgas-online apt
repository's do. They are never dates.

    <X.Y>[.post<N>][~deb<R>][~pr<P>]

- `X.Y.postN` is `git describe`'s: the newest `vX.Y` tag and the commits since it.
- `~deb<R>` is the suite, `R` being its Debian release number: `~deb12` for bookworm, `~deb13` for trixie.
  The older suite's build of one driver version sorts lower, so an upgrade from bookworm to trixie replaces
  it: `0.0.post5~deb12` < `0.0.post5~deb13` < `0.0.post5`.
- `~pr<P>` is on pull request builds only, so a preview sorts below the merged build of the same commit.

**Every package in the archive carries its suite's suffix**, the `Architecture: all` ones too: the doc's
rule for an nfpm build is "packaged once per suite, since `~deb<R>` makes each suite's version different"
("The shared actions"), and its rule for a compiled one is "the build runs in the suite's own image"
("Builds"). So `-utils` and `-modules-<kver>` are compiled in each suite's image, and `-common` and `-dkms`
are the same files packaged once per suite. **The meta package has no suite suffix**: it is one file, not in
the archive, at `X.Y.postN`.

**DKMS knows the driver as `X.Y.postN`**, without the suffixes: `PACKAGE_VERSION` in `dkms.conf` and the
`/usr/src/fpgas-online-acorn-litepcie-<X.Y.postN>/` directory are the same in every suite. Only the deb's
version carries the suite.

The versions come from the shared `mithro/apt-repo-action/deb-version@main` action, not from a script of
this repository's own. That action versions a checkout, and the driver packages take their version from
**the last commit that changed the driver's inputs**, not from HEAD. So CI checks that commit out
(`build_debs.py --version-tree`) and gives the action that checkout. The inputs are:

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

The commit is `git log -1 --first-parent --format=%H -- <inputs>`. Otherwise every merge to main would be a
new version of every package, and would rebuild and republish all 42 modules (§4). `docs/packaging.md` asks
that "every push to the default branch MUST produce a version greater than everything already published";
here a push that changes none of the inputs produces the same version, and the published files are
published again unchanged (§4.3).

`--first-parent` is what keeps versions from going backwards. Without it, `git log` can return a commit
from a merged side branch, one that was written before an earlier main commit. That commit's `git describe`
count is lower, so the new version would sort below one already published. With it, the commit found is
always one on main's first-parent line: the merge commit that brought the change in. N then only grows as
main moves.

### 3.9 Tests

CI, on every pull request:

- the driver generation (§3.1) and the CSR cross-check (§3.2);
- the struct-layout asserts, compiled for armhf and arm64 (§3.3);
- the compat, liteuart-alias and coherent-mask patches apply, and none is already present upstream;
- the `driver-bound` refusal in `fpgas-acorn-verify` and `fpgas-acorn-flash` (fake-sysfs unit tests);
- builds of `-common`, `-dkms` and `-utils` (armhf, arm64, amd64) for each suite, each `-utils` with an
  install test in its suite's image, and the fleet-kernel module artifact with its vermagic check;
- a DKMS test in the shapes DKMS is for (§2), single-architecture containers of each suite: arm64 with the
  headers for the suite's newest v8 kernel from the Raspberry Pi archive, and amd64 with Debian's own
  `linux-headers-amd64`. Each installs the headers and the `-dkms` deb, checks that its postinst alone built
  and installed the modules for `<kver>` (no `dkms install` by hand, which would hide a postinst that builds
  nothing), then that `modinfo -k <kver> litepcie liteuart` resolves, and that purging the package removes
  them. The fleet's shape (armhf root, arm64 kernel) is not tested with DKMS, because it is not supported
  there. Part B's install test (§4.4) covers it with prebuilt modules.

On hardware, on the test board of §1 (MAC `88:a2:9e:45:85:77`, DNA `0x0054b48664b04854`; today at
pi-sw2-p48), running the #29 cle-215+ image from SRAM. It uses a pull request run's artifacts: the armhf
`-utils` and `-common` debs from `debs-bookworm`, and the fleet-kernel `.ko` files from
`acorn-litepcie-modules-<kver>`, copied to the host's tmpfs. These are operator steps, run once:

1. Stop anything using BAR0.
2. `insmod` the artifact `liteuart.ko`, then `litepcie.ko`. `insmod` resolves no aliases, so both are loaded
   by hand here. With Part B's package installed, `modprobe litepcie` alone is enough, and the patched alias
   (§3.4) brings in `liteuart`. dmesg shows the identifier, `/dev/litepcie0` and a `ttyLXU` port.
3. `litepcie_util info` (armhf tools against the arm64 kernel, which exercises compat_ioctl).
4. The #29 DMA test.
5. With the driver still loaded, `fpgas-acorn-verify --no-publish --report -` reports the board
   `driver-bound` and reads nothing from it (§3.7).
6. `rmmod litepcie liteuart`. Then `fpgas-acorn-verify --no-publish --report -` still reports the board
   correctly, which proves the driver leaves BAR0 access as it found it.

## 4. Part B: prebuilt modules per kernel

### 4.1 Builds

**modules**: one job per (suite, kernel) pair, on an `ubuntu-24.04-arm` runner.

1. *Build.* In the suite's Debian image (`debian:bookworm` or `debian:trixie`) for the kernel's architecture,
   with the Raspberry Pi archive (`archive.raspberrypi.com/debian`) added, it installs `linux-headers-<kver>`
   and runs `make -C /usr/src/linux-headers-<kver> M=$PWD modules` on the generated `driver/kernel`. It then
   checks that `modinfo -F vermagic` of each `.ko` starts with `<kver> ` and fails if not.
2. *Package.* `build_debs.py --only modules` makes `fpgas-online-acorn-litepcie-modules-<kver>` (§2) at the
   suite's version (§3.8). It refuses modules that were built for another kernel, suite or architecture than
   the one it is asked to package.
3. *Install.* The deb is installed in the fleet's shape (§4.4).

### 4.2 Which kernels

The RPi archive keeps every kernel it has ever shipped. On 2026-10-02 its arm64 indexes listed (the armhf
rows are as read on 2026-09-25):

| suite / arch | flavour | kernels |
|---|---|---|
| bookworm / arm64 | `rpi-v8` | 25: seven `6.1.0-rpiN` (6.1.21 … 6.1.73), seven 6.6.x, eleven 6.12.x (6.12.19 … 6.12.109) |
| bookworm / arm64 | `rpi-2712` | 23: five `6.1.0-rpiN` (from `6.1.0-rpi3`, 6.1.47), seven 6.6.x, eleven 6.12.x |
| bookworm / armhf | `rpi-v6`, `rpi-v7`, `rpi-v7l` | 25 each, the same kernels as `rpi-v8` |
| trixie / arm64 | `rpi-v8`, `rpi-2712` | 10 each: five 6.12.x (6.12.25 … 6.12.75), five 6.18.x (6.18.29 … 6.18.50) |
| trixie / armhf | `rpi-v6`, `rpi-v7` (no `rpi-v7l`) | 10 each, 6.12.25 … 6.18.50 |
| bookworm, trixie / arm64 | `rpi-v8-rt` | the real-time flavour: 8 on bookworm and 10 on trixie, all 6.12 or later |

The 6.1 kernels are named `6.1.0-rpiN` (`linux-headers-6.1.0-rpi8-rpi-v8`), not by their upstream version, so
the matrix script compares the package's Version (`1:6.1.73-1+rpt1`), not its name, against the floor. The
unversioned meta packages (`linux-headers-rpi-v8` and the like) are skipped, and so is a headers package
whose `linux-image-<kver>` is not in the index, since the modules package could never be installed.

The build set is **the kernels a Raspberry Pi 5 can boot**:

- **Flavours**: `rpi-v8` and `rpi-2712`, for bookworm and for trixie. A Pi 5 (BCM2712) boots only 64-bit
  kernels, and these are the two 64-bit flavours: `rpi-2712` is the Pi 5's own (16 KiB pages), and `rpi-v8` is
  the generic one (4 KiB pages), which the fleet's Pi 5s boot. Both are arm64 packages.
    A Compute Module 4 or 5 booting a 64-bit kernel is served by `rpi-v8` as well.
  - *Not built: the 32-bit flavours* (`rpi-v6`, `rpi-v7`, `rpi-v7l`). No Pi 5 boots them. The only
    PCIe-capable host they would serve is a Compute Module 4 booting a 32-bit kernel.
  - *Not built: `rpi-v8-rt`*. No fpgas.online host runs the real-time kernel, and it would add 18 modules (8
    bookworm, 10 trixie) that nothing installs.
- **Versions**: every kernel from 6.12 onwards. The fleet runs 6.12, and 6.1 and 6.6 are kernels no current
  host boots. That is 42 builds: bookworm 11 × 2, trixie 10 × 2. "Every kernel" with no floor would be 68.
- **Configuration**: the flavours and the floor live in one file, `packaging/acorn-litepcie/kernels.toml`:

      min_kernel = "6.12"

      [suites.bookworm]
      arm64 = ["rpi-v8", "rpi-2712"]

      [suites.trixie]
      arm64 = ["rpi-v8", "rpi-2712"]

  The key is the kernel's architecture, which is also the modules package's. Another flavour is one more list
  entry; a 32-bit one goes in an `armhf = [...]` line. `packaging/acorn-litepcie/plan.py` turns that file and
  the live `Packages` indexes into the job matrix. It fails, rather than plan nothing, when a listed flavour
  has no kernel in its index, and when `fleet_kernel` is not one of the kernels built.

A new RPi kernel is picked up by the **daily** scheduled run of `deb.yml`. A run builds only the modules
packages the archive does not have yet at the current driver version (§4.3), so a quiet day builds none, and
a new kernel costs one build per flavour.

The same kernel name can exist in both suites with different builds: `linux-headers-6.12.34+rpt-rpi-v8` is
`1:6.12.34-1+rpt1~bookworm` in bookworm and `1:6.12.34-1+rpt1` in trixie, built with GCC 12 and GCC 14.
Modules are therefore built per suite and never shared between suites. The two builds are the same package
name at different versions (`~deb12`, `~deb13`), each in its own suite of the archive.

### 4.3 The apt archive: publishing, retention and the kernel floor

**The archive.** `-common`, `-dkms`, `-utils` and every `-modules-<kver>` are published as this
repository's own apt archive on GitHub Pages: one signed flat repository per suite, as
mithro/apt-repo-action's `docs/conventions.md` lays every fpgas-online archive out.

    deb [signed-by=/etc/apt/keyrings/fpgas.online-test-designs.gpg] \
        https://fpgas.online/fpgas.online-test-designs/<suite>/ ./

- *Suites*: `bookworm` and `trixie`, the suites the Raspberry Pi archive has kernels for. There is no
  `raspbian-<codename>` suite: the only armhf hosts with PCIe are 64-bit Pis running a 32-bit userland, and
  they run Debian's ARMv7 build of the tools.
- *Architectures*: amd64, arm64 and armhf, the hosts an Acorn can be plugged into.
- *Only these packages*: the repository's other debs (`packaging/debs/`, `packaging/acorn-pcie/`) and the
  meta package are assets of the `vX.Y` series release, which fpgas-online/apt collects. They are not in
  this archive.
- *The declaration*: `.github/apt-packaging.toml` says all of this, with the reason for each difference from
  the conventions' defaults. `apt-repo-action`'s `scripts/apt-compliance.py` checks the repository against it.

**Who publishes.** `deb.yml`'s `publish-apt` job is a call to
`mithro/apt-repo-action/.github/workflows/publish-apt.yml@main`, which indexes, signs and deploys the
`debs-<suite>` artifacts. Nothing in this repository indexes or signs. It runs on main only, never for a pull
request. After it, the `release` job uploads the meta package to the series release if the release does not
have that version yet (`publish.py`).

**Every publish hands over the complete set.** A deploy replaces the whole site, and publish-apt drops a
package the deploy does not hold. So each suite's `debs-<suite>` artifact holds `-common`, `-dkms`, `-utils`
for the three architectures and a `-modules-<kver>` for every kernel of §4.2: 27 debs for bookworm and 25
for trixie.

**A published version never changes its bytes.** A rebuild's bytes differ (build times), and a host that
already has the index must not find another file under the same name and version. So a run takes from the
live site every deb the site already has at the wanted version, and builds only the rest:

1. `plan.py plan` lists each suite's wanted debs, reads the live site's `<suite>/Packages`, and marks each
   deb `reuse` (the site has that package, version and architecture) or `build`. With no site, or no such
   suite on it yet, everything is `build`.
2. The `modules` matrix is the modules packages marked `build`. `-common`, `-dkms` and `-utils` are built
   and tested by every run, whatever the site has.
3. `plan.py assemble` makes each `debs-<suite>`: a `reuse` deb is downloaded from the site and must have the
   size and SHA256 the site's `Packages` gives, and it is taken in preference to this run's rebuild of it; a
   `build` deb comes from this run. Anything missing fails the job.

A quiet day therefore builds no module and publishes every file again unchanged. A new kernel builds one
module per flavour. A new driver version builds everything.

**Sample and full runs.** A run is *full* when it can publish: on main, once the Pages site exists. Every
other run is a *sample*: pull requests, and every run while there is no site. A sample builds the modules of
the newest kernel of each (suite, flavour) and of the fleet kernel, its `debs-<suite>` artifacts are not
complete, and it publishes nothing. `acorn-litepcie.yml` started by hand builds the full set on any branch,
without publishing. Every run prints the plan, and a sample run also prints what the publishing run of the
same driver version would reuse and build.

**Retention** is publish-apt's (`keep-history`): each suite keeps earlier versions of its packages next to
the new ones, all indexed, while the site stays under 900 MB, so a host can go back a version. It keeps only
versions lower than the one being published, and only of packages the publish still holds.

**Raising the floor.** `min_kernel` in `packaging/acorn-litepcie/kernels.toml` is the floor.

- *Raising it* is a reviewed pull request that edits that one value. The next publish no longer holds the
  modules for kernels below it, so they leave the archive with that deploy.
- *Guard*: `plan.py` fails if `fleet_kernel` (§3.6) is below `min_kernel`, or is not one of the kernels
  built, so the floor can never drop the kernel the fleet boots. It also fails when a listed flavour has no
  kernel in the Raspberry Pi archive's index: an empty index must not read as "no modules wanted".

**What the repository needs once.** Two settings that only its owner can make, in this order:

1. the archive's own signing key, as the repository secret `APT_GPG_PRIVATE_KEY` (`docs/conventions.md`,
   "One signing setup");
2. GitHub Pages, built from GitHub Actions, with HTTPS enforced.

Until the Pages site exists, `plan.py` finds no site and every run on main is a sample run that publishes
nothing. The first run on main after both exist finds the site without suites, builds all 42 modules, and
publishes both suites and then the meta package.

**Scheduled runs and inactivity.** GitHub disables scheduled workflows in a public repository after 60 days
with no repository activity. Workflow runs do not count as activity; pushes do.

- *What stops*: the daily run. When it stops, new RPi kernels stop getting modules, with no error anywhere.
  Pushes to main keep building, because that trigger is not affected.
- *Mitigation*: a check outside this repository reads the workflow's state from the public API.
  `GET /repos/fpgas-online/fpgas.online-test-designs/actions/workflows/deb.yml` returns
  `"state": "disabled_inactivity"` once it has been disabled, and the fix is
  `gh workflow enable deb.yml -R fpgas-online/fpgas.online-test-designs`.
- *Why the watcher sits elsewhere*: a workflow cannot report its own disabling.

### 4.4 Tests

- on pull requests, a **sample** of `-modules-<kver>`: the newest kernel of each (suite, flavour), and the
  fleet kernel (§4.3);
- the vermagic check on every module built;
- an install test of **every** modules deb built, in the fleet's shape: the suite's Debian image under
  `--platform linux/arm/v7`.
  1. `dpkg --add-architecture arm64`, add the Raspberry Pi archive, and make a local flat repository of the
     suite's `-common`, `-dkms`, armhf `-utils`, the `-modules-<kver>` deb and the meta package;
  2. `apt-get install fpgas-online-acorn-litepcie-modules-<kver>:arm64 fpgas-online-acorn-litepcie-utils`.
     Only those two are named, so apt has to find `-common` and the RPi `linux-image-<kver>:arm64` from the
     modules package's Depends by itself;
  3. check each package is installed for the expected architecture, that `modinfo -k <kver> litepcie liteuart`
     resolves to the files under `updates/fpgas-online/` with the right vermagic, that `liteuart.ko` carries
     the `platform:liteuart` alias (§3.4), and that the blacklist is in place;
  4. check that `litepcie_util` prints its usage;
  5. `apt-get install fpgas-online-acorn-litepcie`: the meta package must install, and neither `dkms` nor
     `-dkms` may come with it, although the repository offers `-dkms` (§2);
  6. remove the meta and the modules package and check that `modinfo -k <kver> litepcie` no longer resolves
     (the postrm's `depmod`).
- an install test of the meta package on a plain arm64 host of each suite, from a flat repository of the
  whole assembled `debs-<suite>` and the meta package: `apt-get install fpgas-online-acorn-litepcie` must
  install `-common`, `-utils`, `-dkms` and `dkms`, and no `-modules-<kver>` package, although the repository
  offers them;
- the plan and the assembly of each suite against the live site, which change nothing (§4.3);
- unit tests (`tests/test_acorn_litepcie.py`) of the kernel selection, the wanted set of a suite, the reuse
  plan, the assembly, each package's nfpm configuration and the versions.

## 5. Part C: fpgas-online/apt

A host adds one apt source, fpgas-online/apt, and gets these packages from it. fpgas-online/apt does not
rebuild or re-index this repository's debs by hand: it **bundles** this archive as a dependency repository
(`docs/packaging.md`, "Bundling a dependency repository"), which copies the packages its own packages need
into its suites, verified against this archive's signed indexes and signed again with its own key.

- *The root*: bundling follows only `Depends` and `Pre-Depends`. fpgas-online/apt collects the meta package
  `fpgas-online-acorn-litepcie` from the series release like this repository's other debs, and that package's
  Depends are what pulls `-common`, `-utils`, `-dkms` and, through the virtual
  `fpgas-online-acorn-litepcie-module`, every provider of it: all the `-modules-<kver>` packages.
- *Not both*: the meta package must not also be in this archive. A package that is both fpgas-online/apt's
  own and a bundled repository's is refused.
- *Suites*: this archive has `bookworm` and `trixie` only, so the dependency is declared for those two.
- *Stale bundles*: a newer version here reaches fpgas-online/apt's users at its next publish, or sooner
  through `refresh-bundled.yml`.
- *The inactivity check* on this repository's `deb.yml` (§4.3).

## 6. Plan order

1. Part A. Its CI artifacts are what the #29 test on pi-sw2-p48 uses.
2. Part B.
3. Part C.

## 7. Out of scope

- **Loading the module at boot.** That needs its own design.
  - It must settle whether the boot check reads through the driver (its ioctls) or unbinds it first. Until
    then, a bound driver makes the check report `driver-bound` (§3.7).
  - Whether the kernel would police `resource0` is already answered: it does not (`CONFIG_STRICT_DEVMEM`
    unset).
  - The reset on probe (§3.7) means the driver must load before, not during, anything that uses the SoC.
- **The CI trigger.** This repository used to build every pull request twice (push and pull_request). #41
  already fixed that: `push` is limited to main and a concurrency group cancels stale runs. The new workflow
  follows the same pattern.
- **Other LitePCIe designs.** NeTV2 and other boards get their own driver packages only if they need them.
  The CSR cross-check is specific to the Acorn release.
