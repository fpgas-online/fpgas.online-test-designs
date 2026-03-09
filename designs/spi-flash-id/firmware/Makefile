# Firmware Makefile for SPI Flash JEDEC ID test.
#
# This is compiled by the LiteX build system. The build directory
# must contain generated/csr.h and the linker script.
#
# Typically invoked indirectly by the LiteX Builder, not standalone.

BUILD_DIR ?= ../build/arty

include $(BUILD_DIR)/software/include/generated/variables.mak
include $(SOC_DIRECTORY)/software/common.mak

OBJECTS = main.o

all: firmware.bin

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

firmware.elf: $(OBJECTS)
	$(LD) $(LDFLAGS) -T linker.ld -o $@ $^ -L$(BUILD_DIR)/software/libbase -lbase-nofloat -L$(BUILD_DIR)/software/libcompiler_rt -lcompiler_rt

firmware.bin: firmware.elf
	$(OBJCOPY) -O binary $< $@

clean:
	rm -f *.o *.elf *.bin

.PHONY: all clean
