# Makefile for SPI Flash ID test design.
#
# Usage:
#   make arty      — Build bitstream for Arty A7
#   make netv2     — Build bitstream for NeTV2
#   make all       — Build all bitstreams
#   make test-arty — Run host-side test (Arty, requires FPGA attached)
#   make test-netv2— Run host-side test (NeTV2, requires FPGA attached)

PYTHON ?= uv run python

.PHONY: all arty netv2 test-arty test-netv2 program-arty program-netv2

all: arty netv2

arty:
	$(PYTHON) gateware/spiflash_soc_arty.py --toolchain yosys+nextpnr --build

netv2:
	$(PYTHON) gateware/spiflash_soc_netv2.py --toolchain yosys+nextpnr --build

# --------------------------------------------------------------------------- #
# Host-side tests (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

test-arty:
	$(PYTHON) host/test_spiflash.py --port /dev/ttyUSB1 --board arty

test-netv2:
	$(PYTHON) host/test_spiflash.py --port /dev/ttyAMA0 --board netv2

# --------------------------------------------------------------------------- #
# Programming (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

program-arty:
	openFPGALoader -b arty build/arty/gateware/arty_spiflash_test.bit

program-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2/gateware/netv2_spiflash_test.bit; exit"
