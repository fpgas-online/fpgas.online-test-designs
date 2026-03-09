# mk/common.mk — Shared rules for FPGA test design Makefiles
#
# Include this from any designs/<test>/Makefile:
#   include ../../mk/common.mk
#
# Provides:
#   - VENV_DIR, PYTHON, UV variables
#   - PATH setup to include toolchains
#   - Targets: venv, install-litex, install-toolchains, setup, clean-venv

# ---------------------------------------------------------------------------
# Paths (relative to repo root)
# ---------------------------------------------------------------------------

# Locate the repo root relative to the including Makefile.
# Each design Makefile is at designs/<test>/Makefile, so ../../ is the root.
REPO_ROOT  ?= $(realpath $(dir $(lastword $(MAKEFILE_LIST)))/..)
VENV_DIR   ?= $(REPO_ROOT)/.venv
UV         ?= uv

# Python inside the venv (via uv run)
PYTHON     := $(UV) run python

# ---------------------------------------------------------------------------
# Toolchain PATH setup
# ---------------------------------------------------------------------------

# Add toolchain bin directories to PATH if they exist.
# openXC7 (nextpnr-xilinx, yosys for Xilinx 7-Series)
OPENXC7_DIR := $(VENV_DIR)/toolchains/openxc7
ifneq ($(wildcard $(OPENXC7_DIR)/bin),)
  export PATH := $(OPENXC7_DIR)/bin:$(PATH)
else ifneq ($(wildcard $(OPENXC7_DIR)/*/bin),)
  export PATH := $(wildcard $(OPENXC7_DIR)/*/bin):$(PATH)
endif

# OSS CAD Suite (nextpnr-ice40, nextpnr-ecp5, yosys, icestorm, trellis)
OSS_CAD_DIR := $(VENV_DIR)/toolchains/oss-cad-suite
ifneq ($(wildcard $(OSS_CAD_DIR)/bin),)
  export PATH := $(OSS_CAD_DIR)/bin:$(PATH)
else ifneq ($(wildcard $(OSS_CAD_DIR)/*/bin),)
  export PATH := $(wildcard $(OSS_CAD_DIR)/*/bin):$(PATH)
endif

# ---------------------------------------------------------------------------
# Virtual environment and dependency targets
# ---------------------------------------------------------------------------

.PHONY: venv install-litex install-toolchains setup clean-venv

## Create the Python virtual environment using uv
venv: $(VENV_DIR)/bin/activate

$(VENV_DIR)/bin/activate:
	$(UV) venv $(VENV_DIR)

## Install LiteX and all related packages into the venv
install-litex: venv
	$(UV) pip install --python $(VENV_DIR)/bin/python \
		litex \
		litex-boards \
		migen \
		litedram \
		liteeth \
		litepcie \
		litespi \
		litescope \
		pyserial

## Download and install FPGA toolchains (openXC7 + OSS CAD Suite)
install-toolchains: venv
	$(PYTHON) $(REPO_ROOT)/scripts/setup_toolchains.py --venv-dir $(VENV_DIR)

## Full setup: venv + LiteX + toolchains
setup: install-litex install-toolchains
	@echo ""
	@echo "=== Environment ready ==="
	@echo "Activate with:  source $(VENV_DIR)/activate-all.sh"
	@echo "Or use 'make' targets which handle PATH automatically."

## Remove the virtual environment and all toolchains
clean-venv:
	rm -rf $(VENV_DIR)
