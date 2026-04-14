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

## Known limitations

### `yosys-vivado` hybrid flow is broken for SoCs with VexRiscv

The Yosys → Vivado hybrid flow builds successfully for designs without
a CPU (e.g. `pmod-loopback`). For any design that instantiates a
VexRiscv CPU (i.e. every `*_soc_*.py` that inherits from `SoCCore`
with the default CPU), Vivado's `link_design` rejects the EDIF with:

```
CRITICAL WARNING: [Project 1-486] Could not resolve non-primitive
    black box cell 'VexRiscv' instantiated as 'VexRiscv' [...]
ERROR: [DRC INBB-3] Black Box Instances: Cell 'VexRiscv' of type
    'VexRiscv' has undefined contents and is considered a black box.
    The contents of this cell must be defined for opt_design to
    complete successfully.
```

Yosys **does** produce an EDIF that contains the VexRiscv cell
definition (grep the `.edif` for `(cell VexRiscv` — it's there).
Vivado's `read_edif` parser treats it as a stub anyway. This is an
interoperability bug between Yosys's `write_edif -pvector bra -attrprop`
output and Vivado's EDIF reader; it is not something this plan can
fix without patching LiteX's `_build_yosys_project` or the
upstream Yosys EDIF writer.

For now:

- `yosys-vivado` is verified to work for
  `pmod-loopback/gpio_loopback_{arty,netv2}` (pure combinational
  loopback, no CPU).
- `pmod-loopback/gpio_loopback_acorn` hybrid build fails for a
  different reason — an IOStandard mismatch on the unused `clk200_p`
  pin in the Acorn platform. Acorn-specific, unrelated to the VexRiscv
  EDIF issue.
- `yosys-vivado` is expected-fail for every other Xilinx design in the
  repo matrix (uart, ethernet, ddr, spi-flash, pcie) — every one of
  them instantiates a VexRiscv soft-CPU and hits the EDIF interop bug.

This limitation is the reason the `build-all-xilinx-yosys-vivado`
target should be considered best-effort: it currently only produces
bitstreams for pmod-loopback Arty and NeTV2 (2 of the 18 Xilinx
design/variant targets in the matrix).

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
