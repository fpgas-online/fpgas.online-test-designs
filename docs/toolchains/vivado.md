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

Every Xilinx-targeting design exposes three flows:

| Flow | `--toolchain`        | `--synth-mode` | Makefile suffix      | Synthesis        | P&R            | IP strategy (PCIe)    |
|------|----------------------|----------------|----------------------|------------------|----------------|------------------------|
| A    | `vivado`             | `vivado`       | `-vivado`            | Vivado           | Vivado         | Proprietary `pcie_7x` |
| B    | `vivado`             | `yosys`        | `-yosys-vivado`      | Yosys            | Vivado         | Open-source `pcie_7x` |
| C    | `openxc7` / `yosys+nextpnr` | —      | (none)               | Yosys            | nextpnr-xilinx | Open-source `pcie_7x` |

### Per-design targets

Every design Makefile exposes, for each of its supported board variants:

- `gateware-<board>-vivado`
- `gateware-<board>-yosys-vivado`
- `gateware-<board>-openxc7`

Plus these aggregators:

- `gateware-vivado-all`
- `gateware-yosys-vivado-all`
- `gateware-openxc7-all`
- `gateware-all-flows`
- `check-vivado`

### Top-level aggregators

From the repo root:

```sh
make build-<design>-{vivado,yosys-vivado,openxc7}   # per design
make build-all-xilinx-{vivado,yosys-vivado,openxc7} # every Xilinx design
make build-all-xilinx-all-flows                     # all three flows
make check-vivado                                   # sanity check
```

Build output directories:

- `designs/<design>/build/<board>/`              — flow C (openxc7)
- `designs/<design>/build/<board>-vivado/`       — flow A (pure Vivado)
- `designs/<design>/build/<board>-yosys-vivado/` — flow B (hybrid)

Keeping flow C at the bare `<board>` path preserves every existing
`program-*` rule and host test that hardcoded `build/<board>/gateware/*.bit`.

## Known limitations

### Flow B (Yosys → Vivado hybrid) is broken for SoCs with VexRiscv

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

- Flow B is verified to work for `pmod-loopback/gpio_loopback_*`
  (Arty and Acorn) — pure combinational loopback.
- Flow B is expected-fail for every other Xilinx design in the
  repo matrix.

This limitation is the reason the `build-all-xilinx-yosys-vivado`
target should be considered best-effort: it currently only produces
bitstreams for the pmod-loopback design.

### Flow A (pure Vivado) requires `cpu_reset_n` fix for uart_soc_arty

`designs/uart/gateware/uart_soc_arty.py` requests the
`cpu_reset` resource, but current `litex-boards` `digilent_arty.Platform`
exposes it as `cpu_reset_n`. This is a **pre-existing** bug unrelated
to the three-flow refactor — it affects all flows (openxc7, vivado,
hybrid) equally and was already broken on `main` before this plan.
Fix is out of scope for this plan; file a separate issue.

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
