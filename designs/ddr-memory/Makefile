# --------------------------------------------------------------------------- #
# DDR Memory Test
# --------------------------------------------------------------------------- #

include ../../mk/common.mk

VIVADO_SETTINGS ?= /opt/Xilinx/2025.2/Vivado/settings64.sh
VIVADO_ENV      := . $(VIVADO_SETTINGS) &&

.PHONY: build-arty build-netv2 build-all clean \
        gateware-arty-vivado gateware-netv2-vivado gateware-acorn-vivado \
        gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado \
        gateware-arty-openxc7 gateware-netv2-openxc7 gateware-acorn-openxc7 \
        gateware-vivado-all gateware-yosys-vivado-all gateware-openxc7-all \
        gateware-all-flows check-vivado

build-arty:
	$(PYTHON) gateware/ddr_soc_arty.py --toolchain openxc7 --build

build-netv2:
	$(PYTHON) gateware/ddr_soc_netv2.py --toolchain openxc7 --build

build-all: build-arty build-netv2

# -- Three-flow targets ------------------------------------------------------

gateware-arty-openxc7: build-arty
gateware-netv2-openxc7: build-netv2
gateware-acorn-openxc7:
	$(PYTHON) gateware/ddr_soc_acorn.py --toolchain openxc7 --build

gateware-arty-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_arty.py --toolchain vivado --synth-mode vivado --build
gateware-netv2-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_netv2.py --toolchain vivado --synth-mode vivado --build
gateware-acorn-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_acorn.py --toolchain vivado --synth-mode vivado --build

gateware-arty-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_arty.py --toolchain vivado --synth-mode yosys --build
gateware-netv2-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_netv2.py --toolchain vivado --synth-mode yosys --build
gateware-acorn-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_acorn.py --toolchain vivado --synth-mode yosys --build

gateware-vivado-all: gateware-arty-vivado gateware-netv2-vivado gateware-acorn-vivado
gateware-yosys-vivado-all: gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado
gateware-openxc7-all: gateware-arty-openxc7 gateware-netv2-openxc7 gateware-acorn-openxc7
gateware-all-flows: gateware-vivado-all gateware-yosys-vivado-all gateware-openxc7-all

check-vivado:
	@test -f $(VIVADO_SETTINGS) || (echo "Vivado not found at $(VIVADO_SETTINGS)"; exit 1)
	@$(VIVADO_ENV) vivado -version

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
	openFPGALoader -b arty build/arty/gateware/digilent_arty.bit

program-ddr-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2/gateware/kosagi_netv2.bit; exit"
