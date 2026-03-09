BOARD       ?= arty
VARIANT     ?= a7-35
TOOLCHAIN   ?= yosys+nextpnr
UART_PORT   ?= /dev/ttyUSB1
BAUD_RATE   ?= 115200
BUILD_DIR   ?= build/digilent_arty

.PHONY: gateware firmware test clean

gateware:
	uv run python gateware/pmod_loopback_soc.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

firmware:
	uv run python gateware/pmod_loopback_soc.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--no-compile-gateware

program:
	openFPGALoader -b arty $(BUILD_DIR)/gateware/digilent_arty.bit

test:
	uv run python host/test_pmod_loopback.py \
		--port $(UART_PORT) \
		--baud $(BAUD_RATE)

clean:
	rm -rf build/
