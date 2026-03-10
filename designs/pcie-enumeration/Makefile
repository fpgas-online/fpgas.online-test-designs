include ../../mk/common.mk

TOOLCHAIN      ?= yosys+nextpnr
VARIANT        ?= a7-35
BUILD_DIR      ?= build/netv2
OPENOCD_CFG    ?= openocd/alphamax-rpi.cfg
BITSTREAM      ?= $(BUILD_DIR)/gateware/kosagi_netv2.bit
UART_PORT      ?= /dev/ttyAMA0

.PHONY: gateware program test clean

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
