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
        gateware-arty-vivado gateware-netv2-vivado gateware-acorn-vivado \
        gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado \
        gateware-arty-openxc7 gateware-netv2-openxc7 gateware-acorn-openxc7 \
        gateware-vivado-all gateware-yosys-vivado-all gateware-openxc7-all \
        gateware-all-flows check-vivado

# -- Flow C (existing): Yosys + nextpnr via openxc7 --------------------------

uart-arty:
	$(PYTHON) gateware/uart_soc_arty.py --toolchain openxc7 --build

uart-netv2:
	$(PYTHON) gateware/uart_soc_netv2.py --toolchain openxc7 --build

uart-fomu:
	$(PYTHON) gateware/uart_soc_fomu.py --build

uart-all: uart-arty uart-netv2 uart-fomu

# Explicit per-board openxc7 targets so the aggregators below can depend
# on them uniformly (old names stay as backwards-compat targets above).
gateware-arty-openxc7: uart-arty
gateware-netv2-openxc7: uart-netv2
gateware-acorn-openxc7:
	$(PYTHON) gateware/uart_soc_acorn.py --toolchain openxc7 --build

# -- Flow A: pure Vivado -----------------------------------------------------

gateware-arty-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/uart_soc_arty.py \
	    --toolchain vivado --synth-mode vivado --build
gateware-netv2-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/uart_soc_netv2.py \
	    --toolchain vivado --synth-mode vivado --build
gateware-acorn-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/uart_soc_acorn.py \
	    --toolchain vivado --synth-mode vivado --build

# -- Flow B: Yosys → Vivado hybrid -------------------------------------------

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

.PHONY: program-arty program-netv2 program-fomu

program-arty:
	openFPGALoader -b arty build/arty/gateware/digilent_arty.bit

program-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2/gateware/kosagi_netv2.bit; exit"

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
