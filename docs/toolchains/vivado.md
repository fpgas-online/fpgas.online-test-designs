# Vivado ML Standard 2025.2

## Installation

The repo's Vivado flows expect an install rooted at
`/opt/Xilinx/2025.2/Vivado/` with a working `settings64.sh`:

```
$ . /opt/Xilinx/2025.2/Vivado/settings64.sh
$ vivado -version
vivado v2025.2 (64-bit)
```

The Make-level `VIVADO_SETTINGS` variable defaults to
`/opt/Xilinx/2025.2/Vivado/settings64.sh` and can be overridden if
you install elsewhere.

### Batch install from the AMD unified installer

From the extracted AMD unified SDI installer directory:

```sh
# 1. Install runtime prereqs (apt-based distros only; on Debian 13 the
# script's Ubuntu branch mostly works, plus manual libtinfo5 symlinks).
sudo ./installLibs.sh

# 2. Make /opt/Xilinx user-writable so the rest of the install runs
# unprivileged.
sudo mkdir -p /opt/Xilinx && sudo chown "$USER:$USER" /opt/Xilinx

# 3. Generate a config template (interactive; pick "Vivado" then
# "Vivado ML Standard").
printf '2\n1\n' | ./xsetup -b ConfigGen

# 4. Edit ~/.Xilinx/install_config.txt (or copy it somewhere stable
# before running the install):
#   - Destination=/opt/Xilinx
#   - Modules=...,Artix-7 FPGAs:1,...  (disable every other device family
#     and disable Vitis Model Composer + DocNav for a minimal ~49 GB
#     footprint instead of the default ~100+ GB).
#   - CreateProgramGroupShortcuts=0, CreateDesktopShortcuts=0,
#     CreateFileAssociation=0   (headless install).

# 5. Run the batch install.
./xsetup --agree XilinxEULA,3rdPartyEULA \
         --batch Install \
         --config /path/to/xsetup-config.txt
```

### Debian 13 (trixie) compat tweaks

Vivado 2025.2 still links against `libtinfo.so.5`, `libncurses.so.5`
and `libncursesw.so.5` which Debian 13 no longer ships. Symlink the
`.so.6` ABI-compatible versions into place:

```sh
sudo ln -sf /lib/x86_64-linux-gnu/libtinfo.so.6   /lib/x86_64-linux-gnu/libtinfo.so.5
sudo ln -sf /lib/x86_64-linux-gnu/libncurses.so.6 /lib/x86_64-linux-gnu/libncurses.so.5
sudo ln -sf /lib/x86_64-linux-gnu/libncursesw.so.6 /lib/x86_64-linux-gnu/libncursesw.so.5
```

Vivado also needs the `en_US.UTF-8` locale (its loader hardcodes
`LC_ALL=en_US.UTF-8`). On Debian trixie:

```sh
sudo apt-get install -y locales
echo "en_US.UTF-8 UTF-8" | sudo tee -a /etc/locale.gen
sudo locale-gen en_US.UTF-8
```

Without this you will see `locale::facet::_S_create_c_locale name not valid`
and Vivado exits before running anything.

### Makefile shell

`mk/common.mk` sets `SHELL := /bin/bash` because
`/opt/Xilinx/2025.2/Vivado/settings64.sh` uses `source` (a bash
builtin) which dash — Debian's default `/bin/sh` for Make recipes —
does not understand.

## Three toolchain flows

Every Xilinx-targeting design exposes three flows, named uniformly
`<synthesis>-<pnr>`:

| Flow name       | `--toolchain`               | `--synth-mode` | Synthesis | P&R            | IP strategy (PCIe)    |
|-----------------|-----------------------------|----------------|-----------|----------------|------------------------|
| `vivado-vivado` | `vivado`                    | `vivado` (default) | Vivado    | Vivado         | Proprietary `pcie_7x` |
| `yosys-vivado`  | `vivado`                    | `yosys`        | Yosys     | Vivado         | Open-source `pcie_7x` |
| `yosys-nextpnr` | `openxc7` / `yosys+nextpnr` | —              | Yosys     | nextpnr-xilinx | Open-source `pcie_7x` |

### Per-design targets

Per-design Makefiles share `mk/three-flows.mk` which provides a
`flow_rules` macro. Each design declares its supported variant lists
and calls the macro once per board family; the macro emits three
per-flow pattern rules that match every variant:

- `gateware-<board>-<variant>-vivado-vivado`
- `gateware-<board>-<variant>-yosys-vivado`
- `gateware-<board>-<variant>-yosys-nextpnr`

For example, `designs/uart/` exposes:

    gateware-arty-a7-35-vivado-vivado       gateware-arty-a7-100-vivado-vivado
    gateware-arty-a7-35-yosys-vivado        gateware-arty-a7-100-yosys-vivado
    gateware-arty-a7-35-yosys-nextpnr       gateware-arty-a7-100-yosys-nextpnr
    gateware-netv2-a7-35-vivado-vivado      gateware-netv2-a7-100-vivado-vivado
    gateware-netv2-a7-35-yosys-vivado       gateware-netv2-a7-100-yosys-vivado
    gateware-netv2-a7-35-yosys-nextpnr      gateware-netv2-a7-100-yosys-nextpnr
    gateware-acorn-cle-101-vivado-vivado    gateware-acorn-cle-215-vivado-vivado
    gateware-acorn-cle-215+-vivado-vivado   (and similarly for yosys-vivado / yosys-nextpnr)

Plus these aggregators:

- `gateware-vivado-vivado-all`
- `gateware-yosys-vivado-all`
- `gateware-yosys-nextpnr-all`
- `gateware-all-flows`
- `check-vivado`

Adding a new variant to the `ARTY_VARIANTS` / `NETV2_VARIANTS` /
`ACORN_VARIANTS` list in a per-design Makefile automatically creates
matching targets thanks to Make pattern rules — no per-variant
boilerplate required.

### Top-level aggregators

From the repo root:

```sh
# Per-design, per-flow:
make build-<design>-{vivado-vivado,yosys-vivado,yosys-nextpnr}

# Every Xilinx design in one flow:
make build-all-xilinx-{vivado-vivado,yosys-vivado,yosys-nextpnr}

# All three flows across every Xilinx design:
make build-all-xilinx-all-flows

# Vivado install sanity check:
make check-vivado
```

Build output directories include the variant as well as the flow name.
Every board has multiple variants (Arty/NeTV2 have `a7-35`/`a7-100`,
Acorn has `cle-101`/`cle-215`/`cle-215+` → `cle-215p` in paths) so
every build writes to its own uniquely-named directory:

- `designs/<design>/build/<board>-<variant>-vivado-vivado/`
- `designs/<design>/build/<board>-<variant>-yosys-vivado/`
- `designs/<design>/build/<board>-<variant>-yosys-nextpnr/`

Concrete examples:

- `designs/uart/build/arty-a7-35-vivado-vivado/gateware/digilent_arty.bit`
- `designs/uart/build/netv2-a7-100-yosys-vivado/gateware/kosagi_netv2.bit`
- `designs/pcie-enumeration/build/acorn-cle-215p-yosys-nextpnr/gateware/sqrl_acorn.bit`

### Programming a built bitstream

The `program-*` Makefile rules default to programming the
`yosys-nextpnr` flow's output for the default variant of each board.
Override via the `PROGRAM_FLOW` variable to program a different flow,
or invoke `openFPGALoader` / `openocd` directly to target a specific
`(board, variant, flow)` combination:

```sh
# Program the openxc7 build for the default Arty variant:
make -C designs/uart program-arty

# Program the pure-Vivado build for the default Arty variant:
make -C designs/uart program-arty PROGRAM_FLOW=vivado-vivado

# Program a non-default variant manually:
openFPGALoader -b arty \
    designs/uart/build/arty-a7-100-vivado-vivado/gateware/digilent_arty.bit
```

### What differs between the flows

- **System clock.** Five SoCs run slower when built with `--toolchain openxc7` than with Vivado
  (`SYS_CLK_FREQ` in each script), because nextpnr-xilinx does not reach 100 MHz on them: `uart` and
  `ddr-memory` on the Arty, and `uart` and `spi-flash-id` on the Acorn, at 75 MHz; `ddr-memory` on the Acorn
  at 80 MHz. Vivado builds of all five run at 100 MHz. `--sys-clk-freq` overrides either.
- **Timing.** The `yosys-nextpnr` builds fail if a clock misses timing (`require_timing()` in
  `designs/_shared/platform_fixups.py`, which also retries nextpnr with other seeds). That helper does nothing
  under Vivado, which derives the PLL clocks itself: read Vivado's timing summary in
  `<build>/gateware/<platform>_timing.rpt`.
- **Pins.** `pcie-enumeration` checks every Vivado build's placed pins against its XDC
  (`designs/_shared/pin_check.py`) and fails the build on a mismatch.
- **PCIe core.** `vivado-vivado` uses Xilinx's `pcie_7x` IP; the two Yosys flows use the open-source
  `pcie_7x` sources, which identify as `10ee:7011` where the IP build is `10ee:7021`.

### Designs outside the three flows

`designs/acorn-pcie` (the Acorn's full test design) is not part of this scheme: it has no Makefile, it builds
with Vivado only, and it writes to `designs/acorn-pcie/build/acorn-<variant>[-golden]/`, which
`designs/acorn-pcie/tools/publish_release.py` reads. `scripts/publish_vivado_bitstreams.py` skips it.

## Known limitations

### The `yosys-vivado` flow needs the EDIF fixer

Yosys writes an EDIF that Vivado does not accept as it is. `designs/_shared/build_helpers.py` adds a step to
the generated build script, between Yosys and Vivado, that runs
[`scripts/fix_yosys_edif_libref.py`](../../scripts/fix_yosys_edif_libref.py) on it. The fixer:

- points instances of user modules (VexRiscv and its caches) at their definitions rather than at the
  black-box stubs Yosys also writes, which Vivado otherwise rejects with `[DRC INBB-3]` (issue #6);
- removes the single-ended buffers Yosys puts on unused differential pins (`[DRC IOSTDTYPE-1]` on the
  Acorn's `clk200_p`/`clk200_n`);
- drops `dont_touch` from GT reference clock port nets (`[Opt 31-38]`);
- writes binary primitive attributes as sized strings, which Vivado otherwise drops with `[Netlist 29-72]`.

A gateware script that does not import `designs._shared.build_helpers` does not get the fixer.

The last full run of both Vivado flows was on 2026-09-23 with Vivado 2025.2, before this branch was rebased
onto `main`: all 88 builds (44 design/board/variant combinations in `vivado-vivado` and `yosys-vivado`)
produced bitstreams and met timing. They have not been rerun since the rebase.

### `make install-litex` is incomplete for CPU-based SoCs

`make install-litex` installs the LiteX Python packages but not the
separately-packaged CPU and software pythondata modules. Before
building any SoC with a CPU (everything except `pmod-loopback`), run:

```sh
uv pip install --python .venv/bin/python \
    git+https://github.com/litex-hub/pythondata-cpu-vexriscv.git \
    git+https://github.com/litex-hub/pythondata-software-picolibc.git \
    git+https://github.com/litex-hub/pythondata-software-compiler_rt.git
```

This is pre-existing and should probably be folded into `install-litex`
in a follow-up PR.
