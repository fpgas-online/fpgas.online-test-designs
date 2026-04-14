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
# Three-flow synth→P&R cross-design aggregators
# ---------------------------------------------------------------------------
#
# Three toolchain flows are supported, named uniformly <synth>-<pnr>:
#
#   vivado-vivado   — pure proprietary Vivado (synth + P&R)
#   yosys-vivado    — Yosys synthesis + Vivado P&R (hybrid)
#   yosys-nextpnr   — Yosys synthesis + nextpnr-xilinx P&R (openxc7)
#
# Each Xilinx-targeting design exposes three per-flow aggregators:
#   gateware-vivado-vivado-all
#   gateware-yosys-vivado-all
#   gateware-yosys-nextpnr-all
# plus a combined gateware-all-flows. The targets below pass those
# through for each Xilinx design and provide top-level aggregators
# that build every Xilinx design in a given flow (or all flows).

.PHONY: build-uart-vivado-vivado build-uart-yosys-vivado build-uart-yosys-nextpnr \
        build-ethernet-vivado-vivado build-ethernet-yosys-vivado build-ethernet-yosys-nextpnr \
        build-ddr-vivado-vivado build-ddr-yosys-vivado build-ddr-yosys-nextpnr \
        build-pmod-loopback-vivado-vivado build-pmod-loopback-yosys-vivado build-pmod-loopback-yosys-nextpnr \
        build-pmod-pin-id-vivado-vivado build-pmod-pin-id-yosys-vivado build-pmod-pin-id-yosys-nextpnr \
        build-spi-flash-id-vivado-vivado build-spi-flash-id-yosys-vivado build-spi-flash-id-yosys-nextpnr \
        build-pcie-enumeration-vivado-vivado build-pcie-enumeration-yosys-vivado build-pcie-enumeration-yosys-nextpnr \
        build-all-xilinx-vivado-vivado build-all-xilinx-yosys-vivado \
        build-all-xilinx-yosys-nextpnr build-all-xilinx-all-flows \
        check-vivado

# -- Per-design flow passthroughs --------------------------------------------

build-uart-vivado-vivado:
	$(MAKE) -C designs/uart gateware-vivado-vivado-all
build-uart-yosys-vivado:
	$(MAKE) -C designs/uart gateware-yosys-vivado-all
build-uart-yosys-nextpnr:
	$(MAKE) -C designs/uart gateware-yosys-nextpnr-all

build-ethernet-vivado-vivado:
	$(MAKE) -C designs/ethernet-test gateware-vivado-vivado-all
build-ethernet-yosys-vivado:
	$(MAKE) -C designs/ethernet-test gateware-yosys-vivado-all
build-ethernet-yosys-nextpnr:
	$(MAKE) -C designs/ethernet-test gateware-yosys-nextpnr-all

build-ddr-vivado-vivado:
	$(MAKE) -C designs/ddr-memory gateware-vivado-vivado-all
build-ddr-yosys-vivado:
	$(MAKE) -C designs/ddr-memory gateware-yosys-vivado-all
build-ddr-yosys-nextpnr:
	$(MAKE) -C designs/ddr-memory gateware-yosys-nextpnr-all

build-pmod-loopback-vivado-vivado:
	$(MAKE) -C designs/pmod-loopback gateware-vivado-vivado-all
build-pmod-loopback-yosys-vivado:
	$(MAKE) -C designs/pmod-loopback gateware-yosys-vivado-all
build-pmod-loopback-yosys-nextpnr:
	$(MAKE) -C designs/pmod-loopback gateware-yosys-nextpnr-all

build-pmod-pin-id-vivado-vivado:
	$(MAKE) -C designs/pmod-pin-id gateware-vivado-vivado-all
build-pmod-pin-id-yosys-vivado:
	$(MAKE) -C designs/pmod-pin-id gateware-yosys-vivado-all
build-pmod-pin-id-yosys-nextpnr:
	$(MAKE) -C designs/pmod-pin-id gateware-yosys-nextpnr-all

build-spi-flash-id-vivado-vivado:
	$(MAKE) -C designs/spi-flash-id gateware-vivado-vivado-all
build-spi-flash-id-yosys-vivado:
	$(MAKE) -C designs/spi-flash-id gateware-yosys-vivado-all
build-spi-flash-id-yosys-nextpnr:
	$(MAKE) -C designs/spi-flash-id gateware-yosys-nextpnr-all

build-pcie-enumeration-vivado-vivado:
	$(MAKE) -C designs/pcie-enumeration gateware-vivado-vivado-all
build-pcie-enumeration-yosys-vivado:
	$(MAKE) -C designs/pcie-enumeration gateware-yosys-vivado-all
build-pcie-enumeration-yosys-nextpnr:
	$(MAKE) -C designs/pcie-enumeration gateware-yosys-nextpnr-all

# -- All-Xilinx aggregators --------------------------------------------------

build-all-xilinx-vivado-vivado: \
    build-uart-vivado-vivado \
    build-ethernet-vivado-vivado \
    build-ddr-vivado-vivado \
    build-pmod-loopback-vivado-vivado \
    build-pmod-pin-id-vivado-vivado \
    build-spi-flash-id-vivado-vivado \
    build-pcie-enumeration-vivado-vivado

build-all-xilinx-yosys-vivado: \
    build-uart-yosys-vivado \
    build-ethernet-yosys-vivado \
    build-ddr-yosys-vivado \
    build-pmod-loopback-yosys-vivado \
    build-pmod-pin-id-yosys-vivado \
    build-spi-flash-id-yosys-vivado \
    build-pcie-enumeration-yosys-vivado

build-all-xilinx-yosys-nextpnr: \
    build-uart-yosys-nextpnr \
    build-ethernet-yosys-nextpnr \
    build-ddr-yosys-nextpnr \
    build-pmod-loopback-yosys-nextpnr \
    build-pmod-pin-id-yosys-nextpnr \
    build-spi-flash-id-yosys-nextpnr \
    build-pcie-enumeration-yosys-nextpnr

build-all-xilinx-all-flows: \
    build-all-xilinx-vivado-vivado \
    build-all-xilinx-yosys-vivado \
    build-all-xilinx-yosys-nextpnr

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
