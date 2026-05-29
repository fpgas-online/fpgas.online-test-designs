BOARD       ?= arty
VARIANT     ?= a7-35
TOOLCHAIN   ?= openxc7

include ../../mk/common.mk

# openXC7 chipdb cache directory (.bin files for nextpnr-xilinx).
# Lives at the repo root so multiple designs can share the cache.
CHIPDB ?= $(REPO_ROOT)/chipdb
export CHIPDB

.PHONY: gateware gateware-arty gateware-acorn \
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

gateware-acorn:
	mkdir -p $(CHIPDB)
	$(PYTHON) gateware/pmod_pin_id_acorn.py \
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
