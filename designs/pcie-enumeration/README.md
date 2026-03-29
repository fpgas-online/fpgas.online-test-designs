# PCIe Enumeration Test

LiteX SoC with a PCIe Gen2 x1 endpoint using the open-source
[pcie_7x](gateware/pcie_7x/) core. Tests PCIe link training, bus
enumeration, and BAR allocation on the host.

## Boards

| Script | Board | FPGA | Variant |
|--------|-------|------|---------|
| `gateware/pcie_soc_netv2.py` | Kosagi NeTV2 | XC7A35T | `--variant a7-35` |
| `gateware/pcie_soc_netv2.py` | Kosagi NeTV2 | XC7A100T | `--variant a7-100` |
| `gateware/pcie_soc_acorn.py` | SQRL Acorn CLE-215+ | XC7A200T | `--variant cle-215+` |
| `gateware/pcie_soc_acorn.py` | SQRL Acorn CLE-215 (NiteFury) | XC7A200T | `--variant cle-215` |
| `gateware/pcie_soc_acorn.py` | SQRL Acorn CLE-101 (LiteFury) | XC7A100T | `--variant cle-101` |

## Building

```sh
uv run python designs/pcie-enumeration/gateware/pcie_soc_acorn.py \
    --variant cle-215+ --toolchain openxc7 --build
```

## Testing

After programming the FPGA (SRAM only, never flash on Acorn boards):

```sh
echo 1 > /sys/bus/pci/rescan
uv run python designs/pcie-enumeration/host/test_pcie_enumeration.py --board acorn
```

The test checks for PCIe device `10ee:7011`, link speed 5 GT/s, width x1,
and BAR0 allocation.

## openXC7 Toolchain Workarounds

The CI workflow applies two workarounds for bugs in the `regymm/openxc7`
Docker image:

1. **FASM IBUFDS_GTE2 tile names** (all boards): nextpnr emits bare
   `IBUFDS_GTE2_Y0.feature` FASM lines, but fasm2frames needs the
   GTP_COMMON tile prefix. Fixed by `_shared/fasm2frames_wrapper.py`.

2. **GTP bracket-form port names** (NeTV2 only): nextpnr uses `RXDATA[0]`
   but the chipdb only has `RXDATA0`. Fixed by patching site type JSONs
   with `_shared/patch_gtp_sitetype.py` and regenerating the chipdb.

## Directory Structure

```
pcie-enumeration/
  gateware/
    pcie_soc_acorn.py     Acorn SoC (CLE-215+/215/101)
    pcie_soc_netv2.py     NeTV2 SoC (A7-35T/100T)
    pcie_7x/              Open-source PCIe 7-series core (git submodule)
  host/
    test_pcie_enumeration.py    Host-side PCIe device verification
```
