include ../../mk/common.mk
include ../../mk/three-flows.mk

BAUD_RATE ?= 115200

# ethernet-test targets only Arty and NeTV2 (Acorn has no Ethernet PHY).
ARTY_VARIANTS  := a7-35 a7-100
NETV2_VARIANTS := a7-35 a7-100
ACORN_VARIANTS :=

$(eval $(call flow_rules,arty,ethernet_soc_arty.py,$(ARTY_VARIANTS)))
$(eval $(call flow_rules,netv2,ethernet_soc_netv2.py,$(NETV2_VARIANTS)))

# ---- Arty A7 ----------------------------------------------------------------
ARTY_UART      ?= /dev/ttyUSB1
ARTY_BUILD_DIR ?= build/arty-a7-35-$(PROGRAM_FLOW)

# ---- NeTV2 -------------------------------------------------------------------
NETV2_UART     ?= /dev/ttyAMA0
NETV2_BUILD_DIR?= build/netv2-a7-35-$(PROGRAM_FLOW)

.PHONY: gateware-arty gateware-netv2 program-arty program-netv2 test-arty test-netv2 clean

# Legacy aliases — pick the default variant for each board.
gateware-arty: gateware-arty-a7-35-yosys-nextpnr
gateware-netv2: gateware-netv2-a7-35-yosys-nextpnr

program-arty:
	openFPGALoader -b arty $(ARTY_BUILD_DIR)/gateware/digilent_arty.bit

test-arty:
	$(PYTHON) host/test_ethernet.py \
		--board arty \
		--uart-port $(ARTY_UART) \
		--baud $(BAUD_RATE)

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
