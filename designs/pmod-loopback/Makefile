BOARD       ?= arty
VARIANT     ?= a7-35
TOOLCHAIN   ?= openxc7

include ../../mk/common.mk
include ../../mk/three-flows.mk

ARTY_VARIANTS  := a7-35 a7-100
NETV2_VARIANTS := a7-35 a7-100
ACORN_VARIANTS := cle-101 cle-215 cle-215+

$(eval $(call flow_rules,arty,gpio_loopback_arty.py,$(ARTY_VARIANTS)))
$(eval $(call flow_rules,netv2,gpio_loopback_netv2.py,$(NETV2_VARIANTS)))
$(eval $(call flow_rules,acorn,gpio_loopback_acorn.py,$(ACORN_VARIANTS)))

.PHONY: gateware gateware-arty gateware-netv2 gateware-fomu \
        test test-arty test-netv2 test-fomu \
        program-arty program-netv2 program-fomu clean

# -- Legacy gateware builds (honour top-level VARIANT + TOOLCHAIN) -----------

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

# -- Program -------------------------------------------------------------------

program-arty:
	openFPGALoader -b arty build/arty-$(VARIANT)-$(PROGRAM_FLOW)/gateware/digilent_arty.bit

program-netv2:
	openFPGALoader -b netv2 build/netv2-$(VARIANT)-$(PROGRAM_FLOW)/gateware/kosagi_netv2.bit

program-fomu:
	openFPGALoader -b fomu_evt build/fomu-evt-yosys-nextpnr/gateware/kosagi_fomu_evt.bin

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
