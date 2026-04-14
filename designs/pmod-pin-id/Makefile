BOARD       ?= arty
VARIANT     ?= a7-35
TOOLCHAIN   ?= openxc7

include ../../mk/common.mk

VIVADO_SETTINGS ?= /opt/Xilinx/2025.2/Vivado/settings64.sh
VIVADO_ENV      := . $(VIVADO_SETTINGS) &&
PROGRAM_FLOW    ?= yosys-nextpnr

# Per-board default variants for the three-flow targets.
ACORN_VARIANT ?= cle-215+
NETV2_VARIANT ?= a7-100

.PHONY: gateware gateware-arty \
        program-arty \
        scan scan-arty \
        clean \
        gateware-arty-vivado-vivado gateware-netv2-vivado-vivado gateware-acorn-vivado-vivado \
        gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado \
        gateware-arty-yosys-nextpnr gateware-netv2-yosys-nextpnr gateware-acorn-yosys-nextpnr \
        gateware-vivado-vivado-all gateware-yosys-vivado-all gateware-yosys-nextpnr-all \
        gateware-all-flows check-vivado

# -- Gateware builds ----------------------------------------------------------

gateware: gateware-$(BOARD)

gateware-arty:
	$(PYTHON) gateware/pmod_pin_id_arty.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

# -- Three-flow targets ------------------------------------------------------

gateware-arty-yosys-nextpnr:
	$(PYTHON) gateware/pmod_pin_id_arty.py --variant $(VARIANT) --toolchain openxc7 --build
gateware-netv2-yosys-nextpnr:
	$(PYTHON) gateware/pmod_pin_id_netv2.py --variant $(NETV2_VARIANT) --toolchain openxc7 --build
gateware-acorn-yosys-nextpnr:
	$(PYTHON) gateware/pmod_pin_id_acorn.py --variant $(ACORN_VARIANT) --toolchain openxc7 --build

gateware-arty-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pmod_pin_id_arty.py \
	    --variant $(VARIANT) --toolchain vivado --synth-mode vivado --build
gateware-netv2-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pmod_pin_id_netv2.py \
	    --variant $(NETV2_VARIANT) --toolchain vivado --synth-mode vivado --build
gateware-acorn-vivado-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pmod_pin_id_acorn.py \
	    --variant $(ACORN_VARIANT) --toolchain vivado --synth-mode vivado --build

gateware-arty-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pmod_pin_id_arty.py \
	    --variant $(VARIANT) --toolchain vivado --synth-mode yosys --build
gateware-netv2-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pmod_pin_id_netv2.py \
	    --variant $(NETV2_VARIANT) --toolchain vivado --synth-mode yosys --build
gateware-acorn-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/pmod_pin_id_acorn.py \
	    --variant $(ACORN_VARIANT) --toolchain vivado --synth-mode yosys --build

gateware-vivado-vivado-all: gateware-arty-vivado-vivado gateware-netv2-vivado-vivado gateware-acorn-vivado-vivado
gateware-yosys-vivado-all:  gateware-arty-yosys-vivado  gateware-netv2-yosys-vivado  gateware-acorn-yosys-vivado
gateware-yosys-nextpnr-all: gateware-arty-yosys-nextpnr gateware-netv2-yosys-nextpnr gateware-acorn-yosys-nextpnr
gateware-all-flows: gateware-vivado-vivado-all gateware-yosys-vivado-all gateware-yosys-nextpnr-all

check-vivado:
	@test -f $(VIVADO_SETTINGS) || (echo "Vivado not found at $(VIVADO_SETTINGS)"; exit 1)
	@$(VIVADO_ENV) vivado -version

# -- Program -------------------------------------------------------------------

program-arty:
	openFPGALoader -b arty build/arty-$(PROGRAM_FLOW)/gateware/digilent_arty.bit

# -- Scan (host-side pin identification) ---------------------------------------

scan: scan-$(BOARD)

scan-arty:
	$(PYTHON) host/identify_pmod_pins.py

# -- Cleanup -------------------------------------------------------------------

clean:
	rm -rf build/
