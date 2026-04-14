BOARD       ?= arty
VARIANT     ?= a7-35
TOOLCHAIN   ?= openxc7

include ../../mk/common.mk
include ../../mk/three-flows.mk

ARTY_VARIANTS  := a7-35 a7-100
NETV2_VARIANTS := a7-35 a7-100
ACORN_VARIANTS := cle-101 cle-215 cle-215+

$(eval $(call flow_rules,arty,pmod_pin_id_arty.py,$(ARTY_VARIANTS)))
$(eval $(call flow_rules,netv2,pmod_pin_id_netv2.py,$(NETV2_VARIANTS)))
$(eval $(call flow_rules,acorn,pmod_pin_id_acorn.py,$(ACORN_VARIANTS)))

.PHONY: gateware gateware-arty \
        program-arty \
        scan scan-arty \
        clean

# -- Legacy gateware build (honours top-level VARIANT + TOOLCHAIN) -----------

gateware: gateware-$(BOARD)

gateware-arty:
	$(PYTHON) gateware/pmod_pin_id_arty.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

# -- Program -------------------------------------------------------------------

# pmod-pin-id gateware files use platform.build() directly (not
# LiteX's Builder), so bitstreams land flat in build_dir/top.bit.
program-arty:
	openFPGALoader -b arty build/arty-$(VARIANT)-$(PROGRAM_FLOW)/top.bit

# -- Scan (host-side pin identification) ---------------------------------------

scan: scan-$(BOARD)

scan-arty:
	$(PYTHON) host/identify_pmod_pins.py

# -- Cleanup -------------------------------------------------------------------

clean:
	rm -rf build/
