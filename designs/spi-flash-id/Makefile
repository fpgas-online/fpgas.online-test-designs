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

.PHONY: all arty netv2 fomu test-arty test-netv2 test-fomu program-arty program-netv2 program-fomu clean

all: arty netv2 fomu

arty:
	$(PYTHON) gateware/spiflash_soc_arty.py --toolchain openxc7 --build

netv2:
	$(PYTHON) gateware/spiflash_soc_netv2.py --toolchain openxc7 --build

fomu:
	$(PYTHON) gateware/spiflash_soc_fomu.py --build

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
