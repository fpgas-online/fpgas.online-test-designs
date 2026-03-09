# Root Makefile for fpgas-online-test-designs.

.PHONY: all

all: spiflash-all

# --------------------------------------------------------------------------- #
# SPI Flash ID Test
# --------------------------------------------------------------------------- #

.PHONY: spiflash-arty spiflash-netv2 spiflash-all

spiflash-arty:
	$(MAKE) -C designs/spi-flash-id arty

spiflash-netv2:
	$(MAKE) -C designs/spi-flash-id netv2

spiflash-all: spiflash-arty spiflash-netv2

# --------------------------------------------------------------------------- #
# SPI Flash Host-side tests (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

.PHONY: test-spiflash-arty test-spiflash-netv2

test-spiflash-arty:
	$(MAKE) -C designs/spi-flash-id test-arty

test-spiflash-netv2:
	$(MAKE) -C designs/spi-flash-id test-netv2

# --------------------------------------------------------------------------- #
# SPI Flash Programming (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

.PHONY: program-spiflash-arty program-spiflash-netv2

program-spiflash-arty:
	$(MAKE) -C designs/spi-flash-id program-arty

program-spiflash-netv2:
	$(MAKE) -C designs/spi-flash-id program-netv2
