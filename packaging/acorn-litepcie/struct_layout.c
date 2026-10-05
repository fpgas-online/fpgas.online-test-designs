// SPDX-License-Identifier: Apache-2.0
//
// The litepcie ioctl structs must have one layout on 32-bit ARM (armhf) and on arm64: the driver sets
// `.compat_ioctl = compat_ptr_ioctl` (packaging patch), which hands a 32-bit caller's struct to the 64-bit
// handler unchanged. Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md §3.3.
//
// Compiled, not run, for both architectures by container.py: a struct change in a new litepcie pin that
// breaks the equivalence fails the build here instead of corrupting ioctls on the fleet.
//
//     gcc -fsyntax-only -I<driver>/kernel packaging/acorn-litepcie/struct_layout.c

#include <stddef.h>
#include <stdint.h>

#include "litepcie.h"

#define LAYOUT(type, size) _Static_assert(sizeof(struct type) == (size), #type " is not " #size " bytes")
#define AT(type, field, off) \
	_Static_assert(offsetof(struct type, field) == (off), #type "." #field " is not at " #off)

LAYOUT(litepcie_ioctl_reg, 12);

LAYOUT(litepcie_ioctl_flash, 24);
AT(litepcie_ioctl_flash, tx_data, 8);
AT(litepcie_ioctl_flash, rx_data, 16);

LAYOUT(litepcie_ioctl_icap, 8);

LAYOUT(litepcie_ioctl_dma, 1);

LAYOUT(litepcie_ioctl_dma_writer, 24);
AT(litepcie_ioctl_dma_writer, hw_count, 8);
AT(litepcie_ioctl_dma_writer, sw_count, 16);

LAYOUT(litepcie_ioctl_dma_reader, 24);
AT(litepcie_ioctl_dma_reader, hw_count, 8);
AT(litepcie_ioctl_dma_reader, sw_count, 16);

LAYOUT(litepcie_ioctl_lock, 6);

LAYOUT(litepcie_ioctl_mmap_dma_info, 48);
AT(litepcie_ioctl_mmap_dma_info, dma_tx_buf_offset, 0);
AT(litepcie_ioctl_mmap_dma_info, dma_tx_buf_size, 8);
AT(litepcie_ioctl_mmap_dma_info, dma_tx_buf_count, 16);
AT(litepcie_ioctl_mmap_dma_info, dma_rx_buf_offset, 24);
AT(litepcie_ioctl_mmap_dma_info, dma_rx_buf_size, 32);
AT(litepcie_ioctl_mmap_dma_info, dma_rx_buf_count, 40);

LAYOUT(litepcie_ioctl_mmap_dma_update, 8);
AT(litepcie_ioctl_mmap_dma_update, sw_count, 0);
