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
# UART design targets
# ---------------------------------------------------------------------------

.PHONY: build-uart test-uart-arty test-uart-netv2

build-uart:
	$(MAKE) -C designs/uart uart-all

test-uart-arty:
	$(MAKE) -C designs/uart test-uart-arty

test-uart-netv2:
	$(MAKE) -C designs/uart test-uart-netv2

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

.PHONY: clean-builds
clean-builds:
	@for mf in $(DESIGNS); do \
		$(MAKE) -C $$(dirname $$mf) clean 2>/dev/null || true; \
	done
