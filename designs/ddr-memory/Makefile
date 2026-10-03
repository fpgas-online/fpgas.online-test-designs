# --------------------------------------------------------------------------- #
# DDR Memory Test
# --------------------------------------------------------------------------- #

include ../../mk/common.mk
include ../../mk/three-flows.mk

ARTY_VARIANTS  := a7-35 a7-100
NETV2_VARIANTS := a7-35 a7-100
ACORN_VARIANTS := cle-101 cle-215 cle-215+

$(eval $(call flow_rules,arty,ddr_soc_arty.py,$(ARTY_VARIANTS)))
$(eval $(call flow_rules,netv2,ddr_soc_netv2.py,$(NETV2_VARIANTS)))
$(eval $(call flow_rules,acorn,ddr_soc_acorn.py,$(ACORN_VARIANTS)))

.PHONY: build-arty build-netv2 build-all clean

# Legacy aliases — pick the default variant for each board.
build-arty: gateware-arty-a7-35-yosys-nextpnr
build-netv2: gateware-netv2-a7-35-yosys-nextpnr
build-all: build-arty build-netv2

clean:
	rm -rf build/

# --------------------------------------------------------------------------- #
# DDR Host-side tests (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

.PHONY: test-ddr-arty test-ddr-netv2

test-ddr-arty:
	$(PYTHON) host/test_ddr.py --port /dev/ttyUSB1 --board arty

test-ddr-netv2:
	$(PYTHON) host/test_ddr.py --port /dev/ttyAMA0 --board netv2

# --------------------------------------------------------------------------- #
# DDR Programming (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

.PHONY: program-ddr-arty program-ddr-netv2

program-ddr-arty:
	openFPGALoader -b arty build/arty-a7-35-$(PROGRAM_FLOW)/gateware/digilent_arty.bit

program-ddr-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2-a7-35-$(PROGRAM_FLOW)/gateware/kosagi_netv2.bit; exit"
