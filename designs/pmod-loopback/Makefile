BOARD       ?= arty
VARIANT     ?= a7-35
TOOLCHAIN   ?= openxc7

include ../../mk/common.mk

VIVADO_SETTINGS ?= /opt/Xilinx/2025.2/Vivado/settings64.sh
VIVADO_ENV      := . $(VIVADO_SETTINGS) &&

# Per-board default variants for the three-flow targets. Override if
# you want to exercise a non-default variant.
ACORN_VARIANT ?= cle-215+
NETV2_VARIANT ?= a7-100

.PHONY: gateware gateware-arty gateware-netv2 gateware-fomu \
        test test-arty test-netv2 test-fomu \
        program-arty program-netv2 program-fomu clean \
        gateware-arty-vivado gateware-netv2-vivado gateware-acorn-vivado \
        gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado \
        gateware-arty-openxc7 gateware-netv2-openxc7 gateware-acorn-openxc7 \
        gateware-vivado-all gateware-yosys-vivado-all gateware-openxc7-all \
        gateware-all-flows check-vivado

# -- Gateware builds ----------------------------------------------------------

gateware: gateware-$(BOARD)

gateware-arty:
	$(PYTHON) gateware/gpio_loopback_arty.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

gateware-netv2:
	$(PYTHON) gateware/gpio_loopback_netv2.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

gateware-fomu:
	$(PYTHON) gateware/gpio_loopback_fomu.py \
		--build

# -- Three-flow targets ------------------------------------------------------

gateware-arty-openxc7:
	$(PYTHON) gateware/gpio_loopback_arty.py --variant $(VARIANT) --toolchain openxc7 --build
gateware-netv2-openxc7:
	$(PYTHON) gateware/gpio_loopback_netv2.py --variant $(NETV2_VARIANT) --toolchain openxc7 --build
gateware-acorn-openxc7:
	$(PYTHON) gateware/gpio_loopback_acorn.py --variant $(ACORN_VARIANT) --toolchain openxc7 --build

gateware-arty-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/gpio_loopback_arty.py \
	    --variant $(VARIANT) --toolchain vivado --synth-mode vivado --build
gateware-netv2-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/gpio_loopback_netv2.py \
	    --variant $(NETV2_VARIANT) --toolchain vivado --synth-mode vivado --build
gateware-acorn-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/gpio_loopback_acorn.py \
	    --variant $(ACORN_VARIANT) --toolchain vivado --synth-mode vivado --build

gateware-arty-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/gpio_loopback_arty.py \
	    --variant $(VARIANT) --toolchain vivado --synth-mode yosys --build
gateware-netv2-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/gpio_loopback_netv2.py \
	    --variant $(NETV2_VARIANT) --toolchain vivado --synth-mode yosys --build
gateware-acorn-yosys-vivado:
	$(VIVADO_ENV) $(PYTHON) gateware/gpio_loopback_acorn.py \
	    --variant $(ACORN_VARIANT) --toolchain vivado --synth-mode yosys --build

gateware-vivado-all: gateware-arty-vivado gateware-netv2-vivado gateware-acorn-vivado
gateware-yosys-vivado-all: gateware-arty-yosys-vivado gateware-netv2-yosys-vivado gateware-acorn-yosys-vivado
gateware-openxc7-all: gateware-arty-openxc7 gateware-netv2-openxc7 gateware-acorn-openxc7
gateware-all-flows: gateware-vivado-all gateware-yosys-vivado-all gateware-openxc7-all

check-vivado:
	@test -f $(VIVADO_SETTINGS) || (echo "Vivado not found at $(VIVADO_SETTINGS)"; exit 1)
	@$(VIVADO_ENV) vivado -version

# -- Program -------------------------------------------------------------------

program-arty:
	openFPGALoader -b arty build/arty/gateware/digilent_arty.bit

program-netv2:
	openFPGALoader -b netv2 build/netv2/gateware/kosagi_netv2.bit

program-fomu:
	openFPGALoader -b fomu_evt build/fomu/gateware/kosagi_fomu_evt.bin

# -- Tests ---------------------------------------------------------------------

test: test-$(BOARD)

test-arty:
	$(PYTHON) host/test_pmod_loopback.py --board arty

test-netv2:
	$(PYTHON) host/test_pmod_loopback.py --board netv2

test-fomu:
	$(PYTHON) host/test_pmod_loopback.py --board fomu

# -- Cleanup -------------------------------------------------------------------

clean:
	rm -rf build/
