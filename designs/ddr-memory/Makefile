# --------------------------------------------------------------------------- #
# DDR Memory Test
# --------------------------------------------------------------------------- #

include ../../mk/common.mk

VIVADO_SETTINGS ?= /opt/Xilinx/2025.2/Vivado/settings64.sh
VIVADO_ENV      := . $(VIVADO_SETTINGS) &&
PROGRAM_FLOW    ?= yosys-nextpnr

.PHONY: build-arty build-netv2 build-all clean \
        gateware-arty-vivado-vivado gateware-netv2-vivado-vivado gateware-acorn-vivado-vivado \
        gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado \
        gateware-arty-yosys-nextpnr gateware-netv2-yosys-nextpnr gateware-acorn-yosys-nextpnr \
        gateware-vivado-vivado-all gateware-yosys-vivado-all gateware-yosys-nextpnr-all \
        gateware-all-flows check-vivado

build-arty: gateware-arty-yosys-nextpnr
build-netv2: gateware-netv2-yosys-nextpnr
build-all: build-arty build-netv2

# -- Three-flow targets ------------------------------------------------------

gateware-arty-yosys-nextpnr:
	$(PYTHON) gateware/ddr_soc_arty.py --toolchain openxc7 --build
gateware-netv2-yosys-nextpnr:
	$(PYTHON) gateware/ddr_soc_netv2.py --toolchain openxc7 --build
gateware-acorn-yosys-nextpnr:
	$(PYTHON) gateware/ddr_soc_acorn.py --toolchain openxc7 --build

gateware-arty-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_arty.py --toolchain vivado --synth-mode vivado --build
gateware-netv2-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_netv2.py --toolchain vivado --synth-mode vivado --build
gateware-acorn-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_acorn.py --toolchain vivado --synth-mode vivado --build

gateware-arty-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_arty.py --toolchain vivado --synth-mode yosys --build
gateware-netv2-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_netv2.py --toolchain vivado --synth-mode yosys --build
gateware-acorn-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/ddr_soc_acorn.py --toolchain vivado --synth-mode yosys --build

gateware-vivado-vivado-all: gateware-arty-vivado-vivado gateware-netv2-vivado-vivado gateware-acorn-vivado-vivado
gateware-yosys-vivado-all:  gateware-arty-yosys-vivado  gateware-netv2-yosys-vivado  gateware-acorn-yosys-vivado
gateware-yosys-nextpnr-all: gateware-arty-yosys-nextpnr gateware-netv2-yosys-nextpnr gateware-acorn-yosys-nextpnr
gateware-all-flows: gateware-vivado-vivado-all gateware-yosys-vivado-all gateware-yosys-nextpnr-all

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
	openFPGALoader -b arty build/arty-$(PROGRAM_FLOW)/gateware/digilent_arty.bit

program-ddr-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2-$(PROGRAM_FLOW)/gateware/kosagi_netv2.bit; exit"
