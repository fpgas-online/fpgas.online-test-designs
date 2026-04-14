include ../../mk/common.mk

TOOLCHAIN      ?= yosys+nextpnr
VARIANT        ?= a7-35
BUILD_DIR      ?= build/netv2
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
        gateware-netv2-vivado gateware-acorn-cle215p-vivado \
        gateware-acorn-cle215-vivado gateware-acorn-cle101-vivado \
        gateware-netv2-yosys-vivado gateware-acorn-cle215p-yosys-vivado \
        gateware-acorn-cle215-yosys-vivado gateware-acorn-cle101-yosys-vivado \
        gateware-netv2-openxc7 gateware-acorn-cle215p-openxc7 \
        gateware-acorn-cle215-openxc7 gateware-acorn-cle101-openxc7 \
        gateware-vivado-all gateware-yosys-vivado-all gateware-openxc7-all \
        gateware-all-flows check-vivado

# -- Flow C (existing default): Yosys + nextpnr via openxc7 -----------------

gateware:
	$(PYTHON) gateware/pcie_soc_netv2.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

program:
	openocd -f $(OPENOCD_CFG) -c "init; pld load 0 $(BITSTREAM); exit"

test:
	sudo $(VENV_DIR)/bin/python host/test_pcie_enumeration.py

clean:
	rm -rf build/

# -- Flow C: explicit openxc7 targets for aggregators ----------------------

gateware-netv2-openxc7:
	$(PYTHON) gateware/pcie_soc_netv2.py --variant $(VARIANT) --toolchain openxc7 --build
gateware-acorn-cle215p-openxc7:
	$(PYTHON) gateware/pcie_soc_acorn.py --variant cle-215+ --toolchain openxc7 --build
gateware-acorn-cle215-openxc7:
	$(PYTHON) gateware/pcie_soc_acorn.py --variant cle-215 --toolchain openxc7 --build
gateware-acorn-cle101-openxc7:
	$(PYTHON) gateware/pcie_soc_acorn.py --variant cle-101 --toolchain openxc7 --build

# -- Flow A: pure Vivado ---------------------------------------------------

gateware-netv2-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_netv2.py \
	    --variant $(VARIANT) --toolchain vivado --synth-mode vivado --build
gateware-acorn-cle215p-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_acorn.py \
	    --variant cle-215+ --toolchain vivado --synth-mode vivado --build
gateware-acorn-cle215-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pcie_soc_acorn.py \
	    --variant cle-215 --toolchain vivado --synth-mode vivado --build
gateware-acorn-cle101-vivado:
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

gateware-vivado-all: \
    gateware-netv2-vivado \
    gateware-acorn-cle215p-vivado \
    gateware-acorn-cle215-vivado \
    gateware-acorn-cle101-vivado

gateware-yosys-vivado-all: \
    gateware-netv2-yosys-vivado \
    gateware-acorn-cle215p-yosys-vivado \
    gateware-acorn-cle215-yosys-vivado \
    gateware-acorn-cle101-yosys-vivado

gateware-openxc7-all: \
    gateware-netv2-openxc7 \
    gateware-acorn-cle215p-openxc7 \
    gateware-acorn-cle215-openxc7 \
    gateware-acorn-cle101-openxc7

gateware-all-flows: gateware-vivado-all gateware-yosys-vivado-all gateware-openxc7-all

check-vivado:
	@test -f $(VIVADO_SETTINGS) || (echo "Vivado not found at $(VIVADO_SETTINGS)"; exit 1)
	@$(VIVADO_ENV) vivado -version
