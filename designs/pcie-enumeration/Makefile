include ../../mk/common.mk
include ../../mk/three-flows.mk

TOOLCHAIN   ?= yosys+nextpnr
VARIANT     ?= a7-35
BUILD_DIR   ?= build/netv2-a7-35-$(PROGRAM_FLOW)
OPENOCD_CFG ?= openocd/alphamax-rpi.cfg
BITSTREAM   ?= $(BUILD_DIR)/gateware/kosagi_netv2.bit
UART_PORT   ?= /dev/ttyAMA0

# PCIe board/variant matrix:
#   - NeTV2    a7-35, a7-100
#   - Acorn    cle-101 (LiteFury), cle-215 (NiteFury), cle-215+ (CLE-215+)
# Note: ethernet-test has no Acorn variants and ddr-memory/uart/spi-flash-id
# use the shared helper — but pcie's CI jobs are tied to these exact names
# so we keep them here.
NETV2_VARIANTS := a7-35 a7-100
ACORN_VARIANTS := cle-101 cle-215 cle-215+

$(eval $(call flow_rules,netv2,pcie_soc_netv2.py,$(NETV2_VARIANTS)))
$(eval $(call flow_rules,acorn,pcie_soc_acorn.py,$(ACORN_VARIANTS)))

.PHONY: gateware program test clean

# -- Legacy default `gateware` target: Yosys → nextpnr on NeTV2 --------------
# Preserved for backwards compat with plan.md Phase 10 commands.

gateware: gateware-netv2-a7-35-yosys-nextpnr

program:
	openocd -f $(OPENOCD_CFG) -c "init; pld load 0 $(BITSTREAM); exit"

test:
	sudo $(VENV_DIR)/bin/python host/test_pcie_enumeration.py

clean:
	rm -rf build/
