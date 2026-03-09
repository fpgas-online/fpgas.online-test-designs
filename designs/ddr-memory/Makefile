# --------------------------------------------------------------------------- #
# DDR Memory Test
# --------------------------------------------------------------------------- #

include ../../mk/common.mk

.PHONY: build-arty build-netv2 build-all

build-arty:
	$(PYTHON) gateware/ddr_soc_arty.py --toolchain yosys+nextpnr --build

build-netv2:
	$(PYTHON) gateware/ddr_soc_netv2.py --toolchain yosys+nextpnr --build

build-all: build-arty build-netv2

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
	openFPGALoader -b arty build/arty/gateware/arty_ddr_test.bit

program-ddr-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2/gateware/netv2_ddr_test.bit; exit"
