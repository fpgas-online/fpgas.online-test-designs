BOARD       ?= arty
VARIANT     ?= a7-35
TOOLCHAIN   ?= openxc7

include ../../mk/common.mk

.PHONY: gateware gateware-arty gateware-netv2 gateware-fomu \
        test test-arty test-netv2 test-fomu \
        program-arty program-netv2 program-fomu clean

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
