# Shared Modules

Reusable Python modules imported by the design gateware scripts. These
provide common SoC configuration, platform fixups, and toolchain workarounds.

## Build Infrastructure

| Module | Purpose |
|--------|---------|
| `build_helpers.py` | Common SoC kwargs, build directory calculation, and `build_soc()` helper |
| `platform_fixups.py` | Fix openXC7 device name format (remove dash between part and package) and chipdb symlinks |
| `yosys_workarounds.py` | Patch Yosys template to strip `$scopeinfo` cells that nextpnr-xilinx cannot place |
| `migen_compat.py` | Monkey-patch migen's bytecode tracer for Python 3.11+ compatibility |

## iCE40 Support

| Module | Purpose |
|--------|---------|
| `ice40_firmware.py` | Minimal RV32I firmware generator for iCE40UP5K (bypasses LiteX BIOS for memory-constrained targets) |
| `ice40_spi_flash.py` | Minimal SPI Flash bitbang peripheral for iCE40 |
| `fomu_crg.py` | Clock/Reset generator for Fomu EVT (48 MHz oscillator to 12 MHz system clock) |
| `tt_fpga_crg.py` | Clock/Reset generator for TT FPGA Demo Board |
| `tt_fpga_platform.py` | Platform definition for TT FPGA Demo Board |

## Series 7 Support

| Module | Purpose |
|--------|---------|
| `s7_spi_flash.py` | SPI Flash peripheral for Xilinx 7-series (uses LiteSPI) |

## openXC7 GTP Workarounds

These scripts fix bugs in the `regymm/openxc7` Docker image that prevent
PCIe bitstream generation. See the [PCIe enumeration design](../pcie-enumeration/)
for details.

| Module | Purpose |
|--------|---------|
| `patch_fasm_gtp.py` | Rewrite FASM to prepend GTP_COMMON tile names to bare IBUFDS_GTE2 references |
| `patch_gtp_sitetype.py` | Add bracket-form port aliases to GTP site type JSONs for chipdb generation |
| `fasm2frames_wrapper.py` | Drop-in fasm2frames replacement that patches FASM before forwarding to the real tool |
