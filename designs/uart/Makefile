# designs/uart/Makefile
#
# Requires: openXC7 toolchain on PATH (/opt/openxc7/bin)
#           LiteX and litex-boards installed (uv sync --extra build)
#
# NOTE: Run 'make setup' from the repo root first to install toolchains
#       and Python dependencies.

include ../../mk/common.mk

VIVADO_SETTINGS ?= /opt/Xilinx/2025.2/Vivado/settings64.sh
VIVADO_ENV      := . $(VIVADO_SETTINGS) &&

# --------------------------------------------------------------------------- #
# UART Test
# --------------------------------------------------------------------------- #

.PHONY: uart-arty uart-netv2 uart-fomu uart-all \
        gateware-arty-vivado-vivado gateware-netv2-vivado-vivado gateware-acorn-vivado-vivado \
        gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado \
        gateware-arty-yosys-nextpnr gateware-netv2-yosys-nextpnr gateware-acorn-yosys-nextpnr \
        gateware-vivado-vivado-all gateware-yosys-vivado-all gateware-yosys-nextpnr-all \
        gateware-all-flows check-vivado

# -- Flow C: Yosys → nextpnr (openxc7) ---------------------------------------

uart-arty: gateware-arty-yosys-nextpnr
uart-netv2: gateware-netv2-yosys-nextpnr
uart-fomu:
	$(PYTHON) gateware/uart_soc_fomu.py --build

uart-all: uart-arty uart-netv2 uart-fomu

gateware-arty-yosys-nextpnr:
	$(PYTHON) gateware/uart_soc_arty.py --toolchain openxc7 --build
gateware-netv2-yosys-nextpnr:
	$(PYTHON) gateware/uart_soc_netv2.py --toolchain openxc7 --build
gateware-acorn-yosys-nextpnr:
	$(PYTHON) gateware/uart_soc_acorn.py --toolchain openxc7 --build

# -- Flow A: pure Vivado (synth + P&R) ---------------------------------------

gateware-arty-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/uart_soc_arty.py \
	    --toolchain vivado --synth-mode vivado --build
gateware-netv2-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/uart_soc_netv2.py \
	    --toolchain vivado --synth-mode vivado --build
gateware-acorn-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/uart_soc_acorn.py \
	    --toolchain vivado --synth-mode vivado --build

# -- Flow B: Yosys → Vivado (hybrid) -----------------------------------------

gateware-arty-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/uart_soc_arty.py \
	    --toolchain vivado --synth-mode yosys --build
gateware-netv2-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/uart_soc_netv2.py \
	    --toolchain vivado --synth-mode yosys --build
gateware-acorn-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/uart_soc_acorn.py \
	    --toolchain vivado --synth-mode yosys --build

# -- Aggregators per flow ----------------------------------------------------

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

.PHONY: test-uart-arty test-uart-netv2 test-uart-fomu

test-uart-arty:
	$(PYTHON) host/test_uart.py --port /dev/ttyUSB1 --board arty

test-uart-netv2:
	$(PYTHON) host/test_uart.py --port /dev/ttyAMA0 --board netv2

test-uart-fomu:
	$(PYTHON) host/test_uart.py --port /dev/ttyUSB0 --board fomu

# --------------------------------------------------------------------------- #
# Programming (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #
#
# program-* targets default to the Yosys→nextpnr (openxc7) flow. To
# program a different flow, override PROGRAM_FLOW, e.g.
#
#   make program-arty PROGRAM_FLOW=vivado-vivado

PROGRAM_FLOW ?= yosys-nextpnr

.PHONY: program-arty program-netv2 program-fomu

program-arty:
	openFPGALoader -b arty build/arty-$(PROGRAM_FLOW)/gateware/digilent_arty.bit

program-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2-$(PROGRAM_FLOW)/gateware/kosagi_netv2.bit; exit"

program-fomu:
	openFPGALoader -b fomu_evt build/fomu/gateware/kosagi_fomu_evt.bit

# --------------------------------------------------------------------------- #
# Utilities
# --------------------------------------------------------------------------- #

.PHONY: clean

clean:
	rm -rf build/

# --------------------------------------------------------------------------- #
# All
# --------------------------------------------------------------------------- #

.PHONY: all
all: uart-all
