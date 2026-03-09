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

.PHONY: uart-arty uart-netv2 uart-all

uart-arty:
	$(PYTHON) gateware/uart_soc_arty.py --toolchain yosys+nextpnr --build

uart-netv2:
	$(PYTHON) gateware/uart_soc_netv2.py --toolchain yosys+nextpnr --build

uart-all: uart-arty uart-netv2

# --------------------------------------------------------------------------- #
# Host-side tests (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

.PHONY: test-uart-arty test-uart-netv2

test-uart-arty:
	$(PYTHON) host/test_uart.py --port /dev/ttyUSB1 --board arty

test-uart-netv2:
	$(PYTHON) host/test_uart.py --port /dev/ttyAMA0 --board netv2

# --------------------------------------------------------------------------- #
# Programming (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

.PHONY: program-arty program-netv2

program-arty:
	openFPGALoader -b arty build/arty/gateware/arty_uart_test.bit

program-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2/gateware/netv2_uart_test.bit; exit"

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
