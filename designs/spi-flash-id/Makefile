# Makefile for SPI Flash ID test design.
#
# Usage:
#   make arty      — Build bitstream for Arty A7
#   make netv2     — Build bitstream for NeTV2
#   make fomu      — Build bitstream for Fomu EVT (iCE40UP5K)
#   make all       — Build all bitstreams
#   make test-arty — Run host-side test (Arty, requires FPGA attached)
#   make test-netv2— Run host-side test (NeTV2, requires FPGA attached)
#   make test-fomu — Run host-side test (Fomu, requires FPGA attached)
#   make clean     — Remove build artifacts
#
# NOTE: Firmware is built separately after gateware. See firmware/Makefile.

include ../../mk/common.mk

VIVADO_SETTINGS ?= /opt/Xilinx/2025.2/Vivado/settings64.sh
VIVADO_ENV      := . $(VIVADO_SETTINGS) &&

.PHONY: all arty netv2 fomu test-arty test-netv2 test-fomu program-arty program-netv2 program-fomu clean \
        gateware-arty-vivado gateware-netv2-vivado gateware-acorn-vivado \
        gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado \
        gateware-arty-openxc7 gateware-netv2-openxc7 gateware-acorn-openxc7 \
        gateware-vivado-all gateware-yosys-vivado-all gateware-openxc7-all \
        gateware-all-flows check-vivado

all: arty netv2 fomu

arty:
	$(PYTHON) gateware/spiflash_soc_arty.py --toolchain openxc7 --build

netv2:
	$(PYTHON) gateware/spiflash_soc_netv2.py --toolchain openxc7 --build

fomu:
	$(PYTHON) gateware/spiflash_soc_fomu.py --build

# -- Three-flow targets ------------------------------------------------------

gateware-arty-openxc7: arty
gateware-netv2-openxc7: netv2
gateware-acorn-openxc7:
	$(PYTHON) gateware/spiflash_soc_acorn.py --toolchain openxc7 --build

gateware-arty-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_arty.py --toolchain vivado --synth-mode vivado --build
gateware-netv2-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_netv2.py --toolchain vivado --synth-mode vivado --build
gateware-acorn-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_acorn.py --toolchain vivado --synth-mode vivado --build

gateware-arty-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_arty.py --toolchain vivado --synth-mode yosys --build
gateware-netv2-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_netv2.py --toolchain vivado --synth-mode yosys --build
gateware-acorn-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_acorn.py --toolchain vivado --synth-mode yosys --build

gateware-vivado-all: gateware-arty-vivado gateware-netv2-vivado gateware-acorn-vivado
gateware-yosys-vivado-all: gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado
gateware-openxc7-all: gateware-arty-openxc7 gateware-netv2-openxc7 gateware-acorn-openxc7
gateware-all-flows: gateware-vivado-all gateware-yosys-vivado-all gateware-openxc7-all

check-vivado:
	@test -f $(VIVADO_SETTINGS) || (echo "Vivado not found at $(VIVADO_SETTINGS)"; exit 1)
	@$(VIVADO_ENV) vivado -version

# --------------------------------------------------------------------------- #
# Host-side tests (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

test-arty:
	$(PYTHON) host/test_spiflash.py --port /dev/ttyUSB1 --board arty

test-netv2:
	$(PYTHON) host/test_spiflash.py --port /dev/ttyAMA0 --board netv2

test-fomu:
	$(PYTHON) host/test_spiflash.py --port /dev/ttyUSB0 --board fomu

# --------------------------------------------------------------------------- #
# Programming (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

program-arty:
	openFPGALoader -b arty build/arty/gateware/arty_spiflash_test.bit

program-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2/gateware/netv2_spiflash_test.bit; exit"

program-fomu:
	iceprog build/fomu/gateware/fomu_spiflash_test.bin

# --------------------------------------------------------------------------- #
# Clean
# --------------------------------------------------------------------------- #

clean:
	rm -rf build/
	$(MAKE) -C firmware clean
