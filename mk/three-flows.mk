# mk/three-flows.mk — Shared three-flow target generator for Xilinx designs
#
# Every Xilinx-targeting design builds the same three toolchain flows for
# every (board, variant) pair. This file defines:
#
#   - A `flow_rules` macro that emits the three per-flow pattern rules for
#     one (board family, gateware python file, variant list) tuple. The
#     variant list is expanded into the aggregator prerequisite lists.
#
#   - The per-flow aggregator targets (`gateware-<flow>-all`),
#     `gateware-all-flows`, and `check-vivado`.
#
# Usage from a per-design Makefile:
#
#     include ../../mk/common.mk
#     include ../../mk/three-flows.mk
#
#     ARTY_VARIANTS  := a7-35 a7-100
#     NETV2_VARIANTS := a7-35 a7-100
#     ACORN_VARIANTS := cle-101 cle-215 cle-215+
#
#     $(eval $(call flow_rules,arty, uart_soc_arty.py, $(ARTY_VARIANTS)))
#     $(eval $(call flow_rules,netv2,uart_soc_netv2.py,$(NETV2_VARIANTS)))
#     $(eval $(call flow_rules,acorn,uart_soc_acorn.py,$(ACORN_VARIANTS)))
#
# Each flow_rules call expands to:
#     gateware-<board>-%-vivado-vivado  — pure Vivado
#     gateware-<board>-%-yosys-vivado   — Yosys synth + Vivado P&R
#     gateware-<board>-%-yosys-nextpnr  — openxc7 (fully open-source)
#
# The `%` pattern stem matches the variant string so adding a variant to
# the *_VARIANTS list automatically creates matching targets.

VIVADO_SETTINGS ?= /opt/Xilinx/2025.2/Vivado/settings64.sh
VIVADO_ENV      := . $(VIVADO_SETTINGS) &&
PROGRAM_FLOW    ?= yosys-nextpnr

# Per-flow aggregator prereq lists. Each flow_rules call appends its
# variant-expanded target names. The aggregator targets below consume
# these lists (deferred expansion so the order of $(eval $(call …))
# calls relative to the aggregator declarations doesn't matter).
_FLOW_VV_TARGETS =
_FLOW_YV_TARGETS =
_FLOW_YN_TARGETS =

# flow_rules(board, gateware_file, variants)
#
# Emits three pattern rules and appends target names to the aggregator
# prereq lists. The `$$` in recipe lines defers expansion so PYTHON and
# VIVADO_ENV resolve when the rule runs, not when the macro is called.
# The `$$*` is the pattern stem — the variant string.
define flow_rules
gateware-$(1)-%-vivado-vivado:
	$$(VIVADO_ENV) $$(PYTHON) gateware/$(2) \
	    --variant $$* --toolchain vivado --synth-mode vivado --build

gateware-$(1)-%-yosys-vivado:
	$$(VIVADO_ENV) $$(PYTHON) gateware/$(2) \
	    --variant $$* --toolchain vivado --synth-mode yosys --build

gateware-$(1)-%-yosys-nextpnr:
	$$(PYTHON) gateware/$(2) \
	    --variant $$* --toolchain openxc7 --build

_FLOW_VV_TARGETS += $$(addprefix gateware-$(1)-,$$(addsuffix -vivado-vivado,$(3)))
_FLOW_YV_TARGETS += $$(addprefix gateware-$(1)-,$$(addsuffix -yosys-vivado,$(3)))
_FLOW_YN_TARGETS += $$(addprefix gateware-$(1)-,$$(addsuffix -yosys-nextpnr,$(3)))
endef

# ---------------------------------------------------------------------------
# Aggregator targets
# ---------------------------------------------------------------------------
#
# `.SECONDEXPANSION` + `$$(…)` defers prerequisite expansion until the
# second pass, so `_FLOW_*_TARGETS` is fully populated by every
# `flow_rules` call *before* the aggregator prereqs are resolved. This
# decouples the order of includes from the order of flow_rules calls.

.PHONY: gateware-vivado-vivado-all gateware-yosys-vivado-all \
        gateware-yosys-nextpnr-all gateware-all-flows check-vivado

.SECONDEXPANSION:

gateware-vivado-vivado-all: $$(_FLOW_VV_TARGETS)
gateware-yosys-vivado-all:  $$(_FLOW_YV_TARGETS)
gateware-yosys-nextpnr-all: $$(_FLOW_YN_TARGETS)
gateware-all-flows: gateware-vivado-vivado-all gateware-yosys-vivado-all gateware-yosys-nextpnr-all

check-vivado:
	@test -f $(VIVADO_SETTINGS) || (echo "Vivado not found at $(VIVADO_SETTINGS)"; exit 1)
	@$(VIVADO_ENV) vivado -version
