/*
 * SPI Flash JEDEC ID reader firmware for LiteX SoC.
 *
 * Reads the JEDEC ID (command 0x9F) from the SPI flash via CSR bitbang
 * registers and prints the result over UART.
 *
 * Output format:
 *   JEDEC_ID: 0xMM 0xTT 0xCC
 *   MANUFACTURER: 0xMM
 *   DEVICE_TYPE: 0xTT
 *   CAPACITY: 0xCC
 *   SPI_FLASH_TEST: PASS
 *
 * Where MM=manufacturer, TT=device type, CC=capacity.
 * If the ID is 0x000000 or 0xFFFFFF, it prints SPI_FLASH_TEST: FAIL.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <generated/csr.h>
#include <generated/mem.h>
#include <irq.h>
#include <uart.h>

/* SPI bitbang helpers */
#define SPI_CS_HIGH  (0 << 0)
#define SPI_CS_LOW   (1 << 0)
#define SPI_CLK_LOW  (0 << 1)
#define SPI_CLK_HIGH (1 << 1)
#define SPI_MOSI_LOW (0 << 2)
#define SPI_MOSI_HIGH (1 << 2)

static void spi_set(unsigned int val) {
    spiflash_bitbang_write(val);
}

static unsigned int spi_get_miso(void) {
    return (spiflash_bitbang_read() >> 1) & 1;
}

static void spi_cs_active(void) {
    spi_set(SPI_CS_LOW | SPI_CLK_LOW);
}

static void spi_cs_inactive(void) {
    spi_set(SPI_CS_HIGH | SPI_CLK_LOW);
}

static unsigned char spi_xfer_byte(unsigned char tx) {
    unsigned char rx = 0;
    int i;

    for (i = 7; i >= 0; i--) {
        /* Set MOSI */
        unsigned int mosi = (tx >> i) & 1 ? SPI_MOSI_HIGH : SPI_MOSI_LOW;
        spi_set(SPI_CS_LOW | SPI_CLK_LOW | mosi);

        /* Rising edge — latch data */
        spi_set(SPI_CS_LOW | SPI_CLK_HIGH | mosi);
        rx = (rx << 1) | spi_get_miso();

        /* Falling edge */
        spi_set(SPI_CS_LOW | SPI_CLK_LOW | mosi);
    }

    return rx;
}

static void read_jedec_id(unsigned char *mfr, unsigned char *type, unsigned char *cap) {
    /* Enable bitbang mode */
    spiflash_bitbang_en_write(1);

    spi_cs_active();

    /* Send JEDEC Read ID command (0x9F) */
    spi_xfer_byte(0x9F);

    /* Read 3 response bytes */
    *mfr  = spi_xfer_byte(0x00);
    *type = spi_xfer_byte(0x00);
    *cap  = spi_xfer_byte(0x00);

    spi_cs_inactive();

    /* Disable bitbang mode (return to memory-mapped) */
    spiflash_bitbang_en_write(0);
}

int main(void) {
    irq_setmask(0);
    irq_setie(1);
    uart_init();

    printf("\n");
    printf("=== SPI Flash JEDEC ID Test ===\n");
    printf("\n");

    unsigned char mfr, type, cap;
    read_jedec_id(&mfr, &type, &cap);

    printf("JEDEC_ID: 0x%02X 0x%02X 0x%02X\n", mfr, type, cap);
    printf("MANUFACTURER: 0x%02X\n", mfr);
    printf("DEVICE_TYPE: 0x%02X\n", type);
    printf("CAPACITY: 0x%02X\n", cap);

    /* Validate: all-zeros or all-ones means no device or bus fault */
    int all_zero = (mfr == 0x00 && type == 0x00 && cap == 0x00);
    int all_ones = (mfr == 0xFF && type == 0xFF && cap == 0xFF);

    if (all_zero) {
        printf("SPI_FLASH_TEST: FAIL (all zeros — MISO stuck low or no device)\n");
    } else if (all_ones) {
        printf("SPI_FLASH_TEST: FAIL (all ones — bus not connected or CS fault)\n");
    } else {
        printf("SPI_FLASH_TEST: PASS\n");
    }

    printf("=== Test Complete ===\n");

    /* Hang here */
    while (1);

    return 0;
}
