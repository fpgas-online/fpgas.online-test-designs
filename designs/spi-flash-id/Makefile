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
PROGRAM_FLOW    ?= yosys-nextpnr

.PHONY: all arty netv2 fomu test-arty test-netv2 test-fomu program-arty program-netv2 program-fomu clean \
        gateware-arty-vivado-vivado gateware-netv2-vivado-vivado gateware-acorn-vivado-vivado \
        gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado \
        gateware-arty-yosys-nextpnr gateware-netv2-yosys-nextpnr gateware-acorn-yosys-nextpnr \
        gateware-vivado-vivado-all gateware-yosys-vivado-all gateware-yosys-nextpnr-all \
        gateware-all-flows check-vivado

all: arty netv2 fomu

arty: gateware-arty-yosys-nextpnr
netv2: gateware-netv2-yosys-nextpnr
fomu:
	$(PYTHON) gateware/spiflash_soc_fomu.py --build

# -- Three-flow targets ------------------------------------------------------

gateware-arty-yosys-nextpnr:
	$(PYTHON) gateware/spiflash_soc_arty.py --toolchain openxc7 --build
gateware-netv2-yosys-nextpnr:
	$(PYTHON) gateware/spiflash_soc_netv2.py --toolchain openxc7 --build
gateware-acorn-yosys-nextpnr:
	$(PYTHON) gateware/spiflash_soc_acorn.py --toolchain openxc7 --build

gateware-arty-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_arty.py --toolchain vivado --synth-mode vivado --build
gateware-netv2-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_netv2.py --toolchain vivado --synth-mode vivado --build
gateware-acorn-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_acorn.py --toolchain vivado --synth-mode vivado --build

gateware-arty-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_arty.py --toolchain vivado --synth-mode yosys --build
gateware-netv2-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_netv2.py --toolchain vivado --synth-mode yosys --build
gateware-acorn-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/spiflash_soc_acorn.py --toolchain vivado --synth-mode yosys --build

gateware-vivado-vivado-all: gateware-arty-vivado-vivado gateware-netv2-vivado-vivado gateware-acorn-vivado-vivado
gateware-yosys-vivado-all:  gateware-arty-yosys-vivado  gateware-netv2-yosys-vivado  gateware-acorn-yosys-vivado
gateware-yosys-nextpnr-all: gateware-arty-yosys-nextpnr gateware-netv2-yosys-nextpnr gateware-acorn-yosys-nextpnr
gateware-all-flows: gateware-vivado-vivado-all gateware-yosys-vivado-all gateware-yosys-nextpnr-all

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
	openFPGALoader -b arty build/arty-$(PROGRAM_FLOW)/gateware/arty_spiflash_test.bit

program-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2-$(PROGRAM_FLOW)/gateware/netv2_spiflash_test.bit; exit"

program-fomu:
	iceprog build/fomu/gateware/fomu_spiflash_test.bin

# --------------------------------------------------------------------------- #
# Clean
# --------------------------------------------------------------------------- #

clean:
	rm -rf build/
	$(MAKE) -C firmware clean
