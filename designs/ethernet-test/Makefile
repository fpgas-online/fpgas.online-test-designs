include ../../mk/common.mk

TOOLCHAIN   ?= openxc7
BAUD_RATE   ?= 115200

# ---- Arty A7 ----------------------------------------------------------------
ARTY_VARIANT   ?= a7-35
ARTY_UART      ?= /dev/ttyUSB1
ARTY_BUILD_DIR ?= build/arty

# ---- NeTV2 -------------------------------------------------------------------
NETV2_UART     ?= /dev/ttyAMA0
NETV2_BUILD_DIR?= build/netv2

.PHONY: gateware-arty gateware-netv2 program-arty program-netv2 test-arty test-netv2 clean

# -- Arty A7 --
gateware-arty:
	$(PYTHON) gateware/ethernet_soc_arty.py \
		--variant $(ARTY_VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

program-arty:
	openFPGALoader -b arty $(ARTY_BUILD_DIR)/gateware/digilent_arty.bit

test-arty:
	$(PYTHON) host/test_ethernet.py \
		--board arty \
		--uart-port $(ARTY_UART) \
		--baud $(BAUD_RATE)

# -- NeTV2 --
gateware-netv2:
	$(PYTHON) gateware/ethernet_soc_netv2.py \
		--toolchain $(TOOLCHAIN) \
		--build

# alphamax-rpi.cfg is the OpenOCD config for the NeTV2's JTAG interface via RPi GPIO.
# See: https://github.com/AlphamaxMedia/netv2-fpga/tree/master/openocd
program-netv2:
	openocd -f alphamax-rpi.cfg -c "init; pld load 0 $(NETV2_BUILD_DIR)/gateware/kosagi_netv2.bit; exit"

test-netv2:
	$(PYTHON) host/test_ethernet.py \
		--board netv2 \
		--uart-port $(NETV2_UART) \
		--baud $(BAUD_RATE)

clean:
	rm -rf build/
