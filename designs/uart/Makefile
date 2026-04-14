# designs/uart/Makefile
#
# Requires: openXC7 toolchain on PATH (/opt/openxc7/bin)
#           LiteX and litex-boards installed (uv sync --extra build)
#
# NOTE: Run 'make setup' from the repo root first to install toolchains
#       and Python dependencies.

include ../../mk/common.mk
include ../../mk/three-flows.mk

ARTY_VARIANTS  := a7-35 a7-100
NETV2_VARIANTS := a7-35 a7-100
ACORN_VARIANTS := cle-101 cle-215 cle-215+

# --------------------------------------------------------------------------- #
# UART Test
# --------------------------------------------------------------------------- #

$(eval $(call flow_rules,arty,uart_soc_arty.py,$(ARTY_VARIANTS)))
$(eval $(call flow_rules,netv2,uart_soc_netv2.py,$(NETV2_VARIANTS)))
$(eval $(call flow_rules,acorn,uart_soc_acorn.py,$(ACORN_VARIANTS)))

.PHONY: uart-arty uart-netv2 uart-fomu uart-all

# Legacy aliases — pick the default variant for each board.
uart-arty: gateware-arty-a7-35-yosys-nextpnr
uart-netv2: gateware-netv2-a7-35-yosys-nextpnr
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
