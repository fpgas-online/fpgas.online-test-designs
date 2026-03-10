# designs/uart/Makefile
#
# Requires: openXC7 toolchain on PATH (/opt/openxc7/bin)
#           LiteX and litex-boards installed (uv sync --extra build)
#
# NOTE: Run 'make setup' from the repo root first to install toolchains
#       and Python dependencies.

include ../../mk/common.mk

# --------------------------------------------------------------------------- #
# UART Test
# --------------------------------------------------------------------------- #

.PHONY: uart-arty uart-netv2 uart-fomu uart-all

uart-arty:
	$(PYTHON) gateware/uart_soc_arty.py --toolchain openxc7 --build

uart-netv2:
	$(PYTHON) gateware/uart_soc_netv2.py --toolchain openxc7 --build

uart-fomu:
	$(PYTHON) gateware/uart_soc_fomu.py --build

uart-all: uart-arty uart-netv2 uart-fomu

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
