# Makefile — fpgas-online test designs
#
# Top-level Makefile for building and testing all FPGA designs.
#
# Quick start:
#   make setup          # Create venv, install LiteX, download toolchains
#   make build-uart     # Build UART test bitstreams (requires setup)
#
# The 'setup' target creates a .venv/ directory containing:
#   - Python packages (LiteX, litex-boards, etc.) managed by uv
#   - FPGA toolchains (openXC7, OSS CAD Suite) in .venv/toolchains/

REPO_ROOT := $(realpath $(dir $(firstword $(MAKEFILE_LIST))))
include mk/common.mk

# ---------------------------------------------------------------------------
# Design targets — delegate to per-design Makefiles
# ---------------------------------------------------------------------------

DESIGNS := $(wildcard designs/*/Makefile)

.PHONY: help
help:
	@echo "fpgas-online test designs"
	@echo ""
	@echo "Setup:"
	@echo "  make setup              Full setup (venv + LiteX + toolchains)"
	@echo "  make venv               Create Python virtualenv only"
	@echo "  make install-litex      Install LiteX packages into venv"
	@echo "  make install-toolchains Download openXC7 + OSS CAD Suite"
	@echo ""
	@echo "Build (requires 'make setup' first):"
	@echo "  make build-<design>     Build bitstreams for a design"
	@echo "  make test-<design>      Run host-side tests for a design"
	@echo ""
	@echo "Available designs:"
	@for mf in $(DESIGNS); do \
		d=$$(basename $$(dirname $$mf)); \
		echo "  $$d"; \
	done
	@echo ""
	@echo "Utilities:"
	@echo "  make clean-venv         Remove venv and toolchains"
	@echo "  make clean-builds       Remove all build artifacts"

# ---------------------------------------------------------------------------
# UART test
# ---------------------------------------------------------------------------

.PHONY: build-uart test-uart-arty test-uart-netv2 test-uart-fomu
build-uart:
	$(MAKE) -C designs/uart uart-all
test-uart-arty:
	$(MAKE) -C designs/uart test-uart-arty
test-uart-netv2:
	$(MAKE) -C designs/uart test-uart-netv2
test-uart-fomu:
	$(MAKE) -C designs/uart test-uart-fomu

# ---------------------------------------------------------------------------
# Ethernet test
# ---------------------------------------------------------------------------

.PHONY: build-ethernet-arty build-ethernet-netv2 test-ethernet-arty test-ethernet-netv2
build-ethernet-arty:
	$(MAKE) -C designs/ethernet-test gateware-arty
build-ethernet-netv2:
	$(MAKE) -C designs/ethernet-test gateware-netv2
test-ethernet-arty:
	$(MAKE) -C designs/ethernet-test test-arty
test-ethernet-netv2:
	$(MAKE) -C designs/ethernet-test test-netv2

# ---------------------------------------------------------------------------
# DDR memory test
# ---------------------------------------------------------------------------

.PHONY: build-ddr-memory
build-ddr-memory:
	$(MAKE) -C designs/ddr-memory build-all

# ---------------------------------------------------------------------------
# SPI Flash ID test
# ---------------------------------------------------------------------------

.PHONY: build-spi-flash-id
build-spi-flash-id:
	$(MAKE) -C designs/spi-flash-id all

# ---------------------------------------------------------------------------
# PMOD / GPIO loopback test
# ---------------------------------------------------------------------------

.PHONY: build-pmod-loopback test-pmod-loopback
build-pmod-loopback:
	$(MAKE) -C designs/pmod-loopback gateware
test-pmod-loopback:
	$(MAKE) -C designs/pmod-loopback test

# ---------------------------------------------------------------------------
# PCIe enumeration test
# ---------------------------------------------------------------------------

.PHONY: build-pcie-enumeration test-pcie-enumeration
build-pcie-enumeration:
	$(MAKE) -C designs/pcie-enumeration gateware
test-pcie-enumeration:
	sudo $(MAKE) -C designs/pcie-enumeration test

# ---------------------------------------------------------------------------
# Three-flow Vivado / hybrid / openxc7 cross-design aggregators
# ---------------------------------------------------------------------------
#
# Each Xilinx-targeting design exposes three per-flow aggregators:
#   gateware-vivado-all        (pure Vivado)
#   gateware-yosys-vivado-all  (Yosys → Vivado hybrid)
#   gateware-openxc7-all       (Yosys → nextpnr, fully open)
# and a combined gateware-all-flows. The targets below pass those
# through for each Xilinx design and provide top-level aggregators
# that build every Xilinx design in a given flow (or all flows).

.PHONY: build-uart-vivado build-uart-yosys-vivado build-uart-openxc7 \
        build-ethernet-vivado build-ethernet-yosys-vivado build-ethernet-openxc7 \
        build-ddr-vivado build-ddr-yosys-vivado build-ddr-openxc7 \
        build-pmod-loopback-vivado build-pmod-loopback-yosys-vivado build-pmod-loopback-openxc7 \
        build-spi-flash-id-vivado build-spi-flash-id-yosys-vivado build-spi-flash-id-openxc7 \
        build-pcie-enumeration-vivado build-pcie-enumeration-yosys-vivado build-pcie-enumeration-openxc7 \
        build-all-xilinx-vivado build-all-xilinx-yosys-vivado \
        build-all-xilinx-openxc7 build-all-xilinx-all-flows \
        check-vivado

# -- Per-design flow passthroughs --------------------------------------------

build-uart-vivado:
	$(MAKE) -C designs/uart gateware-vivado-all
build-uart-yosys-vivado:
	$(MAKE) -C designs/uart gateware-yosys-vivado-all
build-uart-openxc7:
	$(MAKE) -C designs/uart gateware-openxc7-all

build-ethernet-vivado:
	$(MAKE) -C designs/ethernet-test gateware-vivado-all
build-ethernet-yosys-vivado:
	$(MAKE) -C designs/ethernet-test gateware-yosys-vivado-all
build-ethernet-openxc7:
	$(MAKE) -C designs/ethernet-test gateware-openxc7-all

build-ddr-vivado:
	$(MAKE) -C designs/ddr-memory gateware-vivado-all
build-ddr-yosys-vivado:
	$(MAKE) -C designs/ddr-memory gateware-yosys-vivado-all
build-ddr-openxc7:
	$(MAKE) -C designs/ddr-memory gateware-openxc7-all

build-pmod-loopback-vivado:
	$(MAKE) -C designs/pmod-loopback gateware-vivado-all
build-pmod-loopback-yosys-vivado:
	$(MAKE) -C designs/pmod-loopback gateware-yosys-vivado-all
build-pmod-loopback-openxc7:
	$(MAKE) -C designs/pmod-loopback gateware-openxc7-all

build-spi-flash-id-vivado:
	$(MAKE) -C designs/spi-flash-id gateware-vivado-all
build-spi-flash-id-yosys-vivado:
	$(MAKE) -C designs/spi-flash-id gateware-yosys-vivado-all
build-spi-flash-id-openxc7:
	$(MAKE) -C designs/spi-flash-id gateware-openxc7-all

build-pcie-enumeration-vivado:
	$(MAKE) -C designs/pcie-enumeration gateware-vivado-all
build-pcie-enumeration-yosys-vivado:
	$(MAKE) -C designs/pcie-enumeration gateware-yosys-vivado-all
build-pcie-enumeration-openxc7:
	$(MAKE) -C designs/pcie-enumeration gateware-openxc7-all

# -- All-Xilinx aggregators --------------------------------------------------

build-all-xilinx-vivado: \
    build-uart-vivado \
    build-ethernet-vivado \
    build-ddr-vivado \
    build-pmod-loopback-vivado \
    build-spi-flash-id-vivado \
    build-pcie-enumeration-vivado

build-all-xilinx-yosys-vivado: \
    build-uart-yosys-vivado \
    build-ethernet-yosys-vivado \
    build-ddr-yosys-vivado \
    build-pmod-loopback-yosys-vivado \
    build-spi-flash-id-yosys-vivado \
    build-pcie-enumeration-yosys-vivado

build-all-xilinx-openxc7: \
    build-uart-openxc7 \
    build-ethernet-openxc7 \
    build-ddr-openxc7 \
    build-pmod-loopback-openxc7 \
    build-spi-flash-id-openxc7 \
    build-pcie-enumeration-openxc7

build-all-xilinx-all-flows: \
    build-all-xilinx-vivado \
    build-all-xilinx-yosys-vivado \
    build-all-xilinx-openxc7

# -- Sanity check ------------------------------------------------------------

check-vivado:
	@$(MAKE) -C designs/uart check-vivado

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

.PHONY: clean-builds
clean-builds:
	@for mf in $(DESIGNS); do \
		$(MAKE) -C $$(dirname $$mf) clean 2>/dev/null || true; \
	done
