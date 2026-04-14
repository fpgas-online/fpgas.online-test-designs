include ../../mk/common.mk

TOOLCHAIN      ?= yosys+nextpnr
VARIANT        ?= a7-35
PROGRAM_FLOW   ?= yosys-nextpnr
BUILD_DIR      ?= build/netv2-$(PROGRAM_FLOW)
OPENOCD_CFG    ?= openocd/alphamax-rpi.cfg
BITSTREAM      ?= $(BUILD_DIR)/gateware/kosagi_netv2.bit
UART_PORT      ?= /dev/ttyAMA0

VIVADO_SETTINGS ?= /opt/Xilinx/2025.2/Vivado/settings64.sh
VIVADO_ENV      := . $(VIVADO_SETTINGS) &&

# PCIe has four board variants in scope:
#   - NeTV2 a7-35 (default — see VARIANT above)
#   - Acorn cle-215+  (XC7A200T-3, default Acorn)
#   - Acorn cle-215   (XC7A200T-2, NiteFury)
#   - Acorn cle-101   (XC7A100T-2, LiteFury)

.PHONY: gateware program test clean \
        gateware-netv2-vivado-vivado gateware-acorn-cle215p-vivado-vivado \
        gateware-acorn-cle215-vivado-vivado gateware-acorn-cle101-vivado-vivado \
        gateware-netv2-yosys-vivado gateware-acorn-cle215p-yosys-vivado \
        gateware-acorn-cle215-yosys-vivado gateware-acorn-cle101-yosys-vivado \
        gateware-netv2-yosys-nextpnr gateware-acorn-cle215p-yosys-nextpnr \
        gateware-acorn-cle215-yosys-nextpnr gateware-acorn-cle101-yosys-nextpnr \
        gateware-vivado-vivado-all gateware-yosys-vivado-all gateware-yosys-nextpnr-all \
        gateware-all-flows check-vivado

# -- Legacy default `gateware` target: Yosys → nextpnr on NeTV2 --------------
# Preserved for backwards compat with plan.md Phase 10 commands.

gateware: gateware-netv2-yosys-nextpnr

program:
	openocd -f $(OPENOCD_CFG) -c "init; pld load 0 $(BITSTREAM); exit"

test:
	sudo $(VENV_DIR)/bin/python host/test_pcie_enumeration.py

clean:
	rm -rf build/

# -- Flow C: Yosys → nextpnr (openxc7) -------------------------------------

gateware-netv2-yosys-nextpnr:
	$(PYTHON) gateware/pcie_soc_netv2.py --variant $(VARIANT) --toolchain openxc7 --build
gateware-acorn-cle215p-yosys-nextpnr:
	$(PYTHON) gateware/pcie_soc_acorn.py --variant cle-215+ --toolchain openxc7 --build
gateware-acorn-cle215-yosys-nextpnr:
	$(PYTHON) gateware/pcie_soc_acorn.py --variant cle-215 --toolchain openxc7 --build
gateware-acorn-cle101-yosys-nextpnr:
	$(PYTHON) gateware/pcie_soc_acorn.py --variant cle-101 --toolchain openxc7 --build

# -- Flow A: pure Vivado ---------------------------------------------------

gateware-netv2-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_netv2.py \
	    --variant $(VARIANT) --toolchain vivado --synth-mode vivado --build
gateware-acorn-cle215p-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_acorn.py \
	    --variant cle-215+ --toolchain vivado --synth-mode vivado --build
gateware-acorn-cle215-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_acorn.py \
	    --variant cle-215 --toolchain vivado --synth-mode vivado --build
gateware-acorn-cle101-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_acorn.py \
	    --variant cle-101 --toolchain vivado --synth-mode vivado --build

# -- Flow B: Yosys → Vivado hybrid -----------------------------------------

gateware-netv2-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_netv2.py \
	    --variant $(VARIANT) --toolchain vivado --synth-mode yosys --build
gateware-acorn-cle215p-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_acorn.py \
	    --variant cle-215+ --toolchain vivado --synth-mode yosys --build
gateware-acorn-cle215-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_acorn.py \
	    --variant cle-215 --toolchain vivado --synth-mode yosys --build
gateware-acorn-cle101-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_acorn.py \
	    --variant cle-101 --toolchain vivado --synth-mode yosys --build

# -- Aggregators per flow --------------------------------------------------

gateware-vivado-vivado-all: \
    gateware-netv2-vivado-vivado \
    gateware-acorn-cle215p-vivado-vivado \
    gateware-acorn-cle215-vivado-vivado \
    gateware-acorn-cle101-vivado-vivado

gateware-yosys-vivado-all: \
    gateware-netv2-yosys-vivado \
    gateware-acorn-cle215p-yosys-vivado \
    gateware-acorn-cle215-yosys-vivado \
    gateware-acorn-cle101-yosys-vivado

gateware-yosys-nextpnr-all: \
    gateware-netv2-yosys-nextpnr \
    gateware-acorn-cle215p-yosys-nextpnr \
    gateware-acorn-cle215-yosys-nextpnr \
    gateware-acorn-cle101-yosys-nextpnr

gateware-all-flows: gateware-vivado-vivado-all gateware-yosys-vivado-all gateware-yosys-nextpnr-all

check-vivado:
	@test -f $(VIVADO_SETTINGS) || (echo "Vivado not found at $(VIVADO_SETTINGS)"; exit 1)
	@$(VIVADO_ENV) vivado -version
