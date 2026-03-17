BOARD       ?= arty
VARIANT     ?= a7-35
TOOLCHAIN   ?= openxc7

include ../../mk/common.mk

.PHONY: gateware gateware-arty \
        program-arty \
        scan scan-arty \
        clean

# -- Gateware builds ----------------------------------------------------------

gateware: gateware-$(BOARD)

gateware-arty:
	$(PYTHON) gateware/pmod_pin_id_arty.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

# -- Program -------------------------------------------------------------------

program-arty:
	openFPGALoader -b arty build/arty/gateware/digilent_arty.bit

# -- Scan (host-side pin identification) ---------------------------------------

scan: scan-$(BOARD)

scan-arty:
	$(PYTHON) host/identify_pmod_pins.py

# -- Cleanup -------------------------------------------------------------------

clean:
	rm -rf build/
