BOARD       ?= arty
VARIANT     ?= a7-35
TOOLCHAIN   ?= openxc7
UART_PORT   ?= /dev/ttyUSB1
BAUD_RATE   ?= 115200
BUILD_DIR   ?= build/digilent_arty

include ../../mk/common.mk

.PHONY: gateware firmware program test clean

gateware:
	$(PYTHON) gateware/pmod_loopback_soc.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

firmware:
	$(PYTHON) gateware/pmod_loopback_soc.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--no-compile-gateware \
		--build

program:
	openFPGALoader -b arty $(BUILD_DIR)/gateware/digilent_arty.bit

test:
	$(PYTHON) host/test_pmod_loopback.py \
		--port $(UART_PORT) \
		--baud $(BAUD_RATE)

clean:
	rm -rf build/
