/* designs/pmod-loopback/firmware/main.c
 *
 * PMOD Loopback Test Firmware
 *
 * Runs on the LiteX VexRiscv CPU.  Provides a UART command interface for
 * the host-side test script to read and drive PMOD GPIO pins.
 *
 * Commands (newline-terminated):
 *   READ <port>            -> "OK <hex>\n"   (read 8-bit input value)
 *   DRIVE <port> <hex>     -> "OK\n"         (set output value, enable OE)
 *   HIZ <port>             -> "OK\n"         (disable OE, set pins to input)
 *   PING                   -> "PONG\n"
 *
 * <port> is one of: A, B, C, D (maps to pmoda..pmodd)
 * <hex>  is a 2-digit hex value: 00..FF
 *
 * Example session:
 *   > PING
 *   < PONG
 *   > HIZ A
 *   < OK
 *   > READ A
 *   < OK 3F
 *   > DRIVE A FF
 *   < OK
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#include <irq.h>
#include <uart.h>
#include <generated/csr.h>

/* ---- helpers ------------------------------------------------------------ */

/* Read a line from UART into buf (max len-1 chars).  Returns length. */
static int uart_readline(char *buf, int len) {
    int i = 0;
    while (i < len - 1) {
        char c = uart_read();
        if (c == '\r' || c == '\n') {
            break;
        }
        buf[i++] = c;
    }
    buf[i] = '\0';
    return i;
}

/* Convert port letter (A-D) to index (0-3).  Returns -1 on invalid. */
static int parse_port(char c) {
    c = toupper(c);
    if (c >= 'A' && c <= 'D') return c - 'A';
    return -1;
}

/* CSR accessor macros -- generated names follow the pattern:
 *   pmoda_oe_read()  / pmoda_oe_write(v)
 *   pmoda_out_read() / pmoda_out_write(v)
 *   pmoda_in_read()
 * We use a dispatch table to avoid a giant switch. */

typedef struct {
    uint32_t (*in_read)(void);
    void     (*oe_write)(uint32_t);
    void     (*out_write)(uint32_t);
} pmod_ops_t;

static const pmod_ops_t pmod_ops[4] = {
    {
        .in_read   = pmoda_in_read,
        .oe_write  = pmoda_oe_write,
        .out_write = pmoda_out_write,
    },
    {
        .in_read   = pmodb_in_read,
        .oe_write  = pmodb_oe_write,
        .out_write = pmodb_out_write,
    },
    {
        .in_read   = pmodc_in_read,
        .oe_write  = pmodc_oe_write,
        .out_write = pmodc_out_write,
    },
    {
        .in_read   = pmodd_in_read,
        .oe_write  = pmodd_oe_write,
        .out_write = pmodd_out_write,
    },
};

/* ---- command handlers --------------------------------------------------- */

static void cmd_ping(void) {
    printf("PONG\n");
}

static void cmd_read(const char *args) {
    if (strlen(args) < 1) { printf("ERR bad args\n"); return; }
    int port = parse_port(args[0]);
    if (port < 0) { printf("ERR bad port\n"); return; }

    uint32_t val = pmod_ops[port].in_read() & 0xFF;
    printf("OK %02X\n", val);
}

static void cmd_drive(const char *args) {
    if (strlen(args) < 3) { printf("ERR bad args\n"); return; }
    int port = parse_port(args[0]);
    if (port < 0) { printf("ERR bad port\n"); return; }

    uint32_t val = (uint32_t)strtoul(&args[2], NULL, 16) & 0xFF;
    pmod_ops[port].oe_write(0xFF);    /* all 8 pins as outputs */
    pmod_ops[port].out_write(val);
    printf("OK\n");
}

static void cmd_hiz(const char *args) {
    if (strlen(args) < 1) { printf("ERR bad args\n"); return; }
    int port = parse_port(args[0]);
    if (port < 0) { printf("ERR bad port\n"); return; }

    pmod_ops[port].oe_write(0x00);    /* all 8 pins as inputs (high-Z) */
    printf("OK\n");
}

/* ---- main loop ---------------------------------------------------------- */

int main(void) {
    char line[64];

    irq_setmask(0);
    irq_setie(1);
    uart_init();

    printf("\n");
    printf("========================================\n");
    printf("  PMOD Loopback Test Firmware\n");
    printf("  Ports: A(JA), B(JB), C(JC), D(JD)\n");
    printf("  Commands: PING, READ, DRIVE, HIZ\n");
    printf("========================================\n");
    printf("READY\n");

    /* Default: all ports as inputs */
    for (int i = 0; i < 4; i++) {
        pmod_ops[i].oe_write(0x00);
    }

    while (1) {
        printf("> ");
        int len = uart_readline(line, sizeof(line));
        if (len == 0) continue;

        if (strncmp(line, "PING", 4) == 0) {
            cmd_ping();
        } else if (strncmp(line, "READ ", 5) == 0) {
            cmd_read(line + 5);
        } else if (strncmp(line, "DRIVE ", 6) == 0) {
            cmd_drive(line + 6);
        } else if (strncmp(line, "HIZ ", 4) == 0) {
            cmd_hiz(line + 4);
        } else {
            printf("ERR unknown command\n");
        }
    }

    return 0;
}
