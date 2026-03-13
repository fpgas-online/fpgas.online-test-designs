"""Generate minimal RV32I firmware for iCE40 targets that bypasses the LiteX BIOS.

The LiteX BIOS (~24 KB) does not fit in the iCE40UP5K's 15 KB of EBR (block RAM).
This module generates tiny custom firmware (<500 bytes) that provides the same
functionality the host-side test scripts expect:

  - UART firmware: prints identification, then echoes all received bytes.
  - SPI Flash firmware: reads JEDEC ID via SPI, prints it, reports PASS/FAIL.

The firmware is returned as a list of 32-bit words suitable for passing to
LiteX's ``integrated_rom_init`` parameter (with ``compile_software=False``).

Usage in SoC scripts::

    soc = BaseSoC(...)
    builder = Builder(soc, ..., compile_software=False)
    soc.finalize()  # allocates CSR addresses

    uart_base = soc.bus.regions["csr"].origin + soc.csr.locs["uart"] * soc.csr.paging
    soc.rom.mem.init = generate_uart_firmware(uart_base, ident="My SoC Ident")
    builder.build(run=True)
"""

# ---------------------------------------------------------------------------
# RV32I register aliases
# ---------------------------------------------------------------------------
ZERO = 0   # x0  — hardwired zero
RA   = 1   # x1  — return address
SP   = 2   # x2  — stack pointer
T0   = 5   # x5  — temporary
T1   = 6   # x6  — temporary
T2   = 7   # x7  — temporary
S0   = 8   # x8  — callee-saved (used for UART base)
S1   = 9   # x9  — callee-saved (used for SPI base)
A0   = 10  # x10 — argument / return value
A1   = 11  # x11 — argument (SPI xfer accumulator)
S2   = 18  # x18 — callee-saved (JEDEC byte 0)
S3   = 19  # x19 — callee-saved (JEDEC byte 1)
S4   = 20  # x20 — callee-saved (JEDEC byte 2)
S5   = 21  # x21 — callee-saved (saved return address)
T3   = 28  # x28 — temporary (hex table base)


# ---------------------------------------------------------------------------
# RV32I instruction encoders
# ---------------------------------------------------------------------------

def _u_type(opcode, rd, imm20):
    return ((imm20 & 0xFFFFF) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)

def _i_type(opcode, rd, funct3, rs1, imm12):
    return ((imm12 & 0xFFF) << 20) | ((rs1 & 0x1F) << 15) \
        | ((funct3 & 0x7) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)

def _s_type(opcode, funct3, rs1, rs2, imm12):
    imm = imm12 & 0xFFF
    return (((imm >> 5) & 0x7F) << 25) | ((rs2 & 0x1F) << 20) \
        | ((rs1 & 0x1F) << 15) | ((funct3 & 0x7) << 12) \
        | ((imm & 0x1F) << 7) | (opcode & 0x7F)

def _b_type(opcode, funct3, rs1, rs2, imm13):
    """Encode B-type. *imm13* is a signed byte offset (must be even)."""
    imm = imm13 & 0x1FFF
    return (((imm >> 12) & 0x1) << 31) \
        | (((imm >> 5) & 0x3F) << 25) \
        | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) \
        | ((funct3 & 0x7) << 12) \
        | (((imm >> 1) & 0xF) << 8) \
        | (((imm >> 11) & 0x1) << 7) \
        | (opcode & 0x7F)

def _j_type(opcode, rd, imm21):
    """Encode J-type. *imm21* is a signed byte offset (must be even)."""
    imm = imm21 & 0x1FFFFF
    return (((imm >> 20) & 0x1) << 31) \
        | (((imm >> 1) & 0x3FF) << 21) \
        | (((imm >> 11) & 0x1) << 20) \
        | (((imm >> 12) & 0xFF) << 12) \
        | ((rd & 0x1F) << 7) \
        | (opcode & 0x7F)

def _r_type(opcode, rd, funct3, rs1, rs2, funct7=0):
    return ((funct7 & 0x7F) << 25) | ((rs2 & 0x1F) << 20) \
        | ((rs1 & 0x1F) << 15) | ((funct3 & 0x7) << 12) \
        | ((rd & 0x1F) << 7) | (opcode & 0x7F)


# --- Instruction wrappers ---

_OP_LUI    = 0b0110111
_OP_AUIPC  = 0b0010111
_OP_JAL    = 0b1101111
_OP_JALR   = 0b1100111
_OP_BRANCH = 0b1100011
_OP_LOAD   = 0b0000011
_OP_STORE  = 0b0100011
_OP_IMM    = 0b0010011
_OP_ALU    = 0b0110011

def _lui(rd, imm20):       return _u_type(_OP_LUI, rd, imm20)
def _auipc(rd, imm20):     return _u_type(_OP_AUIPC, rd, imm20)
def _jal(rd, off):          return _j_type(_OP_JAL, rd, off)
def _jalr(rd, rs1, off=0):  return _i_type(_OP_JALR, rd, 0b000, rs1, off)
def _beq(rs1, rs2, off):   return _b_type(_OP_BRANCH, 0b000, rs1, rs2, off)
def _bne(rs1, rs2, off):   return _b_type(_OP_BRANCH, 0b001, rs1, rs2, off)
def _lw(rd, rs1, off=0):   return _i_type(_OP_LOAD, rd, 0b010, rs1, off)
def _lbu(rd, rs1, off=0):  return _i_type(_OP_LOAD, rd, 0b100, rs1, off)
def _sw(rs2, rs1, off=0):  return _s_type(_OP_STORE, 0b010, rs1, rs2, off)
def _addi(rd, rs1, imm):   return _i_type(_OP_IMM, rd, 0b000, rs1, imm)
def _andi(rd, rs1, imm):   return _i_type(_OP_IMM, rd, 0b111, rs1, imm)
def _ori(rd, rs1, imm):    return _i_type(_OP_IMM, rd, 0b110, rs1, imm)
def _slli(rd, rs1, shamt): return _i_type(_OP_IMM, rd, 0b001, rs1, shamt)
def _srli(rd, rs1, shamt): return _i_type(_OP_IMM, rd, 0b101, rs1, shamt)
def _add(rd, rs1, rs2):    return _r_type(_OP_ALU, rd, 0b000, rs1, rs2)
def _or(rd, rs1, rs2):     return _r_type(_OP_ALU, rd, 0b110, rs1, rs2)
def _and(rd, rs1, rs2):    return _r_type(_OP_ALU, rd, 0b111, rs1, rs2)
def _nop():                 return _addi(ZERO, ZERO, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_imm32(value):
    """Split a 32-bit address into (upper20, lower12) for a LUI+ADDI pair.

    ADDI sign-extends its 12-bit immediate. When bit 11 of the lower part is
    set, we add 1 to the upper part to compensate.

    Returns (upper, lower) where lower is a signed 12-bit value encoded as
    the low 12 bits of a 32-bit unsigned int (suitable for the encoder).
    """
    value = value & 0xFFFFFFFF
    lower = value & 0xFFF
    upper = (value >> 12) & 0xFFFFF
    if lower >= 0x800:
        upper = (upper + 1) & 0xFFFFF
        lower = lower - 0x1000        # now negative; & 0xFFF in encoder
    return upper, lower


def _emit_string(words, s):
    """Append a null-terminated, 4-byte-aligned ASCII string to *words*."""
    data = s.encode("ascii") + b"\x00"
    # Pad to 4-byte alignment.
    while len(data) % 4:
        data += b"\x00"
    for i in range(0, len(data), 4):
        words.append(int.from_bytes(data[i:i+4], "little"))


# ---------------------------------------------------------------------------
# UART echo firmware
# ---------------------------------------------------------------------------

def generate_uart_firmware(uart_base, ident):
    """Generate minimal UART echo firmware.

    The firmware:
      1. Prints a banner line containing "LiteX" (required by test_uart.py).
      2. Prints the *ident* string (board identification).
      3. Prints "litex> " prompt (required by test_uart.py).
      4. Enters an echo loop: every received byte is sent back.

    Parameters
    ----------
    uart_base : int
        UART CSR base address (e.g. 0xf0001800).
    ident : str
        SoC identification string (e.g. "fpgas-online UART Test SoC -- TT FPGA").

    Returns
    -------
    list[int]
        32-bit words for ``integrated_rom_init``.
    """
    words = []
    upper, lower = _split_imm32(uart_base)

    def w(idx):
        """Byte address of word *idx*."""
        return idx * 4

    # --- Code section -------------------------------------------------------
    # Placeholder indices for instructions that need patching.

    # Word 0-1: Load UART base into s0.
    words.append(_lui(S0, upper))                       # 0
    words.append(_addi(S0, S0, lower))                  # 1

    # Word 2-4: Print banner string.
    i_banner_auipc = len(words); words.append(0)        # 2  (patch later)
    i_banner_addi  = len(words); words.append(0)        # 3  (patch later)
    i_banner_jal   = len(words); words.append(0)        # 4  (patch later)

    # Word 5-7: Print ident string.
    i_ident_auipc = len(words); words.append(0)         # 5
    i_ident_addi  = len(words); words.append(0)         # 6
    i_ident_jal   = len(words); words.append(0)         # 7

    # Word 8-10: Print prompt.
    i_prompt_auipc = len(words); words.append(0)        # 8
    i_prompt_addi  = len(words); words.append(0)        # 9
    i_prompt_jal   = len(words); words.append(0)        # 10

    # Echo loop.
    #
    # LiteX UART's RX FIFO does NOT pop on a CSR read of RXTX.  The FIFO
    # only advances when the RX event pending bit is cleared by writing to
    # UART_EV_PENDING (offset 0x10, bit 1 = RX).  Without this write the
    # firmware would re-read the same byte forever, producing a flood.
    #
    # CSR layout (from csr.csv):
    #   +0x00  RXTX        read=RX data, write=TX data
    #   +0x04  TXFULL      1 when TX FIFO full
    #   +0x08  RXEMPTY     1 when RX FIFO empty
    #   +0x10  EV_PENDING  write bit 1 to clear RX event → pops RX FIFO
    i_echo_loop = len(words)
    words.append(_lw(T0, S0, 8))                        # t0 = UART_RXEMPTY
    words.append(_bne(T0, ZERO, w(i_echo_loop) - w(i_echo_loop + 1)))
    words.append(_lw(A0, S0, 0))                        # a0 = UART_RXTX (read)
    words.append(_addi(T0, ZERO, 2))                    # t0 = EV_RX (bit 1)
    words.append(_sw(T0, S0, 16))                       # UART_EV_PENDING = 2 (pop RX FIFO)

    i_tx_wait = len(words)
    words.append(_lw(T0, S0, 4))                        # t0 = UART_TXFULL
    words.append(_bne(T0, ZERO, w(i_tx_wait) - w(i_tx_wait + 1)))
    words.append(_sw(A0, S0, 0))                        # UART_RXTX = a0 (echo)

    i_echo_jal = len(words)
    words.append(_jal(ZERO, w(i_echo_loop) - w(i_echo_jal)))

    # putstr subroutine.
    i_putstr = len(words)
    words.append(_lbu(T0, A0, 0))                       # 18: t0 = *a0
    i_putstr_beq = len(words); words.append(0)          # 19: if null → return (patch)

    i_putstr_tx = len(words)
    words.append(_lw(T1, S0, 4))                        # 20: t1 = UART_TXFULL
    words.append(_bne(T1, ZERO, w(i_putstr_tx) - w(i_putstr_tx + 1)))  # 21: wait
    words.append(_sw(T0, S0, 0))                        # 22: UART_RXTX = t0
    words.append(_addi(A0, A0, 1))                      # 23: a0++

    i_putstr_loop = len(words)
    words.append(_jal(ZERO, w(i_putstr) - w(i_putstr_loop)))  # 24: → putstr

    i_putstr_ret = len(words)
    words.append(_jalr(ZERO, RA, 0))                    # 25: return

    # Patch putstr's forward branch.
    words[i_putstr_beq] = _beq(T0, ZERO, w(i_putstr_ret) - w(i_putstr_beq))

    # --- String data --------------------------------------------------------
    banner_str = "\r\nLiteX custom firmware\r\n"
    ident_str  = ident + "\r\n"
    prompt_str = "litex> "

    i_banner_data = len(words)
    _emit_string(words, banner_str)

    i_ident_data = len(words)
    _emit_string(words, ident_str)

    i_prompt_data = len(words)
    _emit_string(words, prompt_str)

    # --- Patch string-loading instructions ----------------------------------
    # Pattern: auipc a0, 0  →  a0 = PC_of_auipc
    #          addi  a0, a0, offset  →  a0 = address of string
    #          jal   ra, putstr

    words[i_banner_auipc] = _auipc(A0, 0)
    words[i_banner_addi]  = _addi(A0, A0, w(i_banner_data) - w(i_banner_auipc))
    words[i_banner_jal]   = _jal(RA, w(i_putstr) - w(i_banner_jal))

    words[i_ident_auipc] = _auipc(A0, 0)
    words[i_ident_addi]  = _addi(A0, A0, w(i_ident_data) - w(i_ident_auipc))
    words[i_ident_jal]   = _jal(RA, w(i_putstr) - w(i_ident_jal))

    words[i_prompt_auipc] = _auipc(A0, 0)
    words[i_prompt_addi]  = _addi(A0, A0, w(i_prompt_data) - w(i_prompt_auipc))
    words[i_prompt_jal]   = _jal(RA, w(i_putstr) - w(i_prompt_jal))

    return words


# ---------------------------------------------------------------------------
# SPI Flash JEDEC ID firmware
# ---------------------------------------------------------------------------

def generate_spiflash_firmware(uart_base, spiflash_base, ident):
    """Generate SPI Flash JEDEC ID reader firmware.

    The firmware:
      1. Prints a banner line containing "LiteX" (required by test scripts).
      2. Prints the *ident* string (board identification).
      3. Reads the JEDEC ID (command 0x9F) via SPI bitbang.
      4. Prints "JEDEC_ID: 0xMM 0xTT 0xCC".
      5. Prints "SPI_FLASH_TEST: PASS" or "FAIL".
      6. Prints "Test Complete" and halts.

    PASS when the JEDEC ID is not all-zeros or all-0xFF.

    The SPI flash is accessed via a bitbang CSR (Ice40SPIFlash):
        +0x00: bitbang (write: bit0=MOSI, bit1=CLK, bit2=CS_N)
        +0x04: miso    (read:  bit0=MISO)

    Parameters
    ----------
    uart_base : int
        UART CSR base address.
    spiflash_base : int
        SPI flash bitbang CSR base address.
    ident : str
        SoC identification string.

    Returns
    -------
    list[int]
        32-bit words for ``integrated_rom_init``.
    """
    words = []
    uart_upper, uart_lower = _split_imm32(uart_base)
    spi_upper, spi_lower = _split_imm32(spiflash_base)

    def w(idx):
        """Byte address of word *idx*."""
        return idx * 4

    # === Code section =====================================================

    # Load UART base into s0, SPI bitbang base into s1.
    words.append(_lui(S0, uart_upper))
    words.append(_addi(S0, S0, uart_lower))
    words.append(_lui(S1, spi_upper))
    words.append(_addi(S1, S1, spi_lower))

    # Print banner string.
    i_banner_auipc = len(words); words.append(0)
    i_banner_addi  = len(words); words.append(0)
    i_banner_jal   = len(words); words.append(0)

    # Print ident string.
    i_ident_auipc = len(words); words.append(0)
    i_ident_addi  = len(words); words.append(0)
    i_ident_jal   = len(words); words.append(0)

    # --- SPI: Read JEDEC ID (command 0x9F) --------------------------------
    # Assert CS (active low): MOSI=0, CLK=0, CS_N=0.
    words.append(_sw(ZERO, S1, 0))

    # Send command byte 0x9F.
    words.append(_addi(A0, ZERO, 0x9F))
    i_send_jal = len(words); words.append(0)

    # Read 3 response bytes (send 0x00 as dummy).
    words.append(_addi(A0, ZERO, 0))
    i_recv1_jal = len(words); words.append(0)
    words.append(_addi(S2, A0, 0))                              # manufacturer

    words.append(_addi(A0, ZERO, 0))
    i_recv2_jal = len(words); words.append(0)
    words.append(_addi(S3, A0, 0))                              # device type

    words.append(_addi(A0, ZERO, 0))
    i_recv3_jal = len(words); words.append(0)
    words.append(_addi(S4, A0, 0))                              # capacity

    # Deassert CS: CS_N=1.
    words.append(_addi(T0, ZERO, 4))
    words.append(_sw(T0, S1, 0))

    # --- Print JEDEC ID line ----------------------------------------------
    i_jedec_auipc = len(words); words.append(0)
    i_jedec_addi  = len(words); words.append(0)
    i_jedec_jal   = len(words); words.append(0)

    words.append(_addi(A0, S2, 0))                              # puthex(mfr)
    i_hex1_jal = len(words); words.append(0)

    i_sep1_auipc = len(words); words.append(0)
    i_sep1_addi  = len(words); words.append(0)
    i_sep1_jal   = len(words); words.append(0)

    words.append(_addi(A0, S3, 0))                              # puthex(dtype)
    i_hex2_jal = len(words); words.append(0)

    i_sep2_auipc = len(words); words.append(0)
    i_sep2_addi  = len(words); words.append(0)
    i_sep2_jal   = len(words); words.append(0)

    words.append(_addi(A0, S4, 0))                              # puthex(cap)
    i_hex3_jal = len(words); words.append(0)

    i_crlf_auipc = len(words); words.append(0)
    i_crlf_addi  = len(words); words.append(0)
    i_crlf_jal   = len(words); words.append(0)

    # --- PASS/FAIL check --------------------------------------------------
    # Print "SPI_FLASH_TEST: " prefix first.
    i_prefix_auipc = len(words); words.append(0)
    i_prefix_addi  = len(words); words.append(0)
    i_prefix_jal   = len(words); words.append(0)

    # FAIL if all three bytes are 0x00.
    words.append(_or(T0, S2, S3))
    words.append(_or(T0, T0, S4))
    i_zero_beq = len(words); words.append(0)                    # → fail

    # FAIL if all three bytes are 0xFF.
    words.append(_addi(T1, ZERO, 0xFF))
    i_ff1_bne = len(words); words.append(0)                     # s2≠0xFF → pass
    i_ff2_bne = len(words); words.append(0)                     # s3≠0xFF → pass
    i_ff3_bne = len(words); words.append(0)                     # s4≠0xFF → pass
    # Fall through: all 0xFF → fail.

    # Print FAIL.
    i_fail = len(words)
    i_fail_auipc = len(words); words.append(0)
    i_fail_addi  = len(words); words.append(0)
    i_fail_jal   = len(words); words.append(0)
    i_fail_done  = len(words); words.append(0)                  # → done

    # Print PASS.
    i_pass = len(words)
    i_pass_auipc = len(words); words.append(0)
    i_pass_addi  = len(words); words.append(0)
    i_pass_jal   = len(words); words.append(0)

    # Done: print "Test Complete" and halt.
    i_done = len(words)
    i_done_auipc = len(words); words.append(0)
    i_done_addi  = len(words); words.append(0)
    i_done_jal   = len(words); words.append(0)

    i_halt = len(words)
    words.append(_jal(ZERO, 0))                                 # self-loop

    # === Subroutines ======================================================

    # --- putstr(a0=string_pointer) ----------------------------------------
    i_putstr = len(words)
    words.append(_lbu(T0, A0, 0))
    i_putstr_beq = len(words); words.append(0)

    i_putstr_tx = len(words)
    words.append(_lw(T1, S0, 4))                                # UART_TXFULL
    words.append(_bne(T1, ZERO, w(i_putstr_tx) - w(i_putstr_tx + 1)))
    words.append(_sw(T0, S0, 0))                                # write char
    words.append(_addi(A0, A0, 1))

    i_putstr_loop = len(words)
    words.append(_jal(ZERO, w(i_putstr) - w(i_putstr_loop)))

    i_putstr_ret = len(words)
    words.append(_jalr(ZERO, RA, 0))

    words[i_putstr_beq] = _beq(T0, ZERO, w(i_putstr_ret) - w(i_putstr_beq))

    # --- puthex(a0=byte, prints two hex ASCII chars) ----------------------
    # Saves ra in s5 (called from main which uses JAL ra).
    i_puthex = len(words)
    words.append(_addi(S5, RA, 0))                              # save ra
    words.append(_addi(T2, A0, 0))                              # save byte

    # Load hex lookup table address into t3.
    i_hex_auipc = len(words); words.append(0)
    i_hex_addi  = len(words); words.append(0)

    # High nibble.
    words.append(_srli(A0, T2, 4))
    words.append(_andi(A0, A0, 0xF))
    words.append(_add(A0, T3, A0))
    words.append(_lbu(A0, A0, 0))

    i_puthex_tx1 = len(words)
    words.append(_lw(T1, S0, 4))
    words.append(_bne(T1, ZERO, w(i_puthex_tx1) - w(i_puthex_tx1 + 1)))
    words.append(_sw(A0, S0, 0))

    # Low nibble.
    words.append(_andi(A0, T2, 0xF))
    words.append(_add(A0, T3, A0))
    words.append(_lbu(A0, A0, 0))

    i_puthex_tx2 = len(words)
    words.append(_lw(T1, S0, 4))
    words.append(_bne(T1, ZERO, w(i_puthex_tx2) - w(i_puthex_tx2 + 1)))
    words.append(_sw(A0, S0, 0))

    words.append(_addi(RA, S5, 0))                              # restore ra
    words.append(_jalr(ZERO, RA, 0))

    # --- spi_xfer_byte(a0=send) → a0=received ----------------------------
    # Full-duplex SPI Mode 0 (CPOL=0, CPHA=0), MSB-first, 8 bits.
    i_spi_xfer = len(words)
    words.append(_addi(A1, ZERO, 0))                            # recv = 0
    words.append(_addi(T2, ZERO, 8))                            # 8 bits

    i_xfer_loop = len(words)
    words.append(_slli(A1, A1, 1))                              # make room
    words.append(_srli(T0, A0, 7))                              # MSB of send
    words.append(_andi(T0, T0, 1))                              # MOSI value
    words.append(_sw(T0, S1, 0))                                # CLK=0, MOSI
    words.append(_ori(T0, T0, 2))                               # set CLK
    words.append(_sw(T0, S1, 0))                                # CLK=1 (↑ edge)
    words.append(_lw(T1, S1, 4))                                # read MISO
    words.append(_andi(T1, T1, 1))                              # mask
    words.append(_or(A1, A1, T1))                               # accumulate
    words.append(_andi(T0, T0, 1))                              # clear CLK
    words.append(_sw(T0, S1, 0))                                # CLK=0 (↓ edge)
    words.append(_slli(A0, A0, 1))                              # shift send
    words.append(_addi(T2, T2, -1))                             # counter--

    i_xfer_bne = len(words)
    words.append(_bne(T2, ZERO, w(i_xfer_loop) - w(i_xfer_bne)))
    words.append(_addi(A0, A1, 0))                              # return value
    words.append(_jalr(ZERO, RA, 0))

    # === String data ======================================================

    i_banner_data = len(words)
    _emit_string(words, "\r\nLiteX custom firmware\r\n")

    i_ident_data = len(words)
    _emit_string(words, ident + "\r\n")

    i_jedec_data = len(words)
    _emit_string(words, "JEDEC_ID: 0x")

    i_sep_data = len(words)
    _emit_string(words, " 0x")

    i_crlf_data = len(words)
    _emit_string(words, "\r\n")

    i_prefix_data = len(words)
    _emit_string(words, "SPI_FLASH_TEST: ")

    i_pass_data = len(words)
    _emit_string(words, "PASS\r\n")

    i_fail_data = len(words)
    _emit_string(words, "FAIL\r\n")

    i_done_data = len(words)
    _emit_string(words, "Test Complete\r\n")

    i_hex_data = len(words)
    _emit_string(words, "0123456789ABCDEF")

    # === Patch forward references =========================================

    def _patch_print(auipc_idx, addi_idx, jal_idx, data_idx):
        words[auipc_idx] = _auipc(A0, 0)
        words[addi_idx]  = _addi(A0, A0, w(data_idx) - w(auipc_idx))
        words[jal_idx]   = _jal(RA, w(i_putstr) - w(jal_idx))

    _patch_print(i_banner_auipc, i_banner_addi, i_banner_jal, i_banner_data)
    _patch_print(i_ident_auipc,  i_ident_addi,  i_ident_jal,  i_ident_data)
    _patch_print(i_jedec_auipc,  i_jedec_addi,  i_jedec_jal,  i_jedec_data)
    _patch_print(i_sep1_auipc,   i_sep1_addi,   i_sep1_jal,   i_sep_data)
    _patch_print(i_sep2_auipc,   i_sep2_addi,   i_sep2_jal,   i_sep_data)
    _patch_print(i_crlf_auipc,   i_crlf_addi,   i_crlf_jal,   i_crlf_data)
    _patch_print(i_prefix_auipc, i_prefix_addi, i_prefix_jal, i_prefix_data)
    _patch_print(i_pass_auipc,   i_pass_addi,   i_pass_jal,   i_pass_data)
    _patch_print(i_fail_auipc,   i_fail_addi,   i_fail_jal,   i_fail_data)
    _patch_print(i_done_auipc,   i_done_addi,   i_done_jal,   i_done_data)

    # SPI xfer subroutine calls.
    words[i_send_jal] = _jal(RA, w(i_spi_xfer) - w(i_send_jal))
    words[i_recv1_jal] = _jal(RA, w(i_spi_xfer) - w(i_recv1_jal))
    words[i_recv2_jal] = _jal(RA, w(i_spi_xfer) - w(i_recv2_jal))
    words[i_recv3_jal] = _jal(RA, w(i_spi_xfer) - w(i_recv3_jal))

    # Puthex subroutine calls.
    words[i_hex1_jal] = _jal(RA, w(i_puthex) - w(i_hex1_jal))
    words[i_hex2_jal] = _jal(RA, w(i_puthex) - w(i_hex2_jal))
    words[i_hex3_jal] = _jal(RA, w(i_puthex) - w(i_hex3_jal))

    # PASS/FAIL branches.
    words[i_zero_beq] = _beq(T0, ZERO, w(i_fail) - w(i_zero_beq))
    words[i_ff1_bne]  = _bne(S2, T1, w(i_pass) - w(i_ff1_bne))
    words[i_ff2_bne]  = _bne(S3, T1, w(i_pass) - w(i_ff2_bne))
    words[i_ff3_bne]  = _bne(S4, T1, w(i_pass) - w(i_ff3_bne))
    words[i_fail_done] = _jal(ZERO, w(i_done) - w(i_fail_done))

    # Hex lookup table address for puthex.
    words[i_hex_auipc] = _auipc(T3, 0)
    words[i_hex_addi]  = _addi(T3, T3, w(i_hex_data) - w(i_hex_auipc))

    return words


# ---------------------------------------------------------------------------
# Helpers for SoC scripts
# ---------------------------------------------------------------------------

def install_uart_firmware(soc, ident):
    """Finalize *soc*, generate UART firmware, and install it into ROM.

    Call this after creating the Builder (with ``compile_software=False``)
    but before ``builder.build()``.  The SoC must NOT have been finalized yet.

    Returns the firmware word list (for inspection / testing).
    """
    soc.finalize()
    csr_origin = soc.bus.regions["csr"].origin
    uart_loc   = soc.csr.locs["uart"]
    paging     = soc.csr.paging
    uart_base  = csr_origin + uart_loc * paging
    fw = generate_uart_firmware(uart_base=uart_base, ident=ident)
    soc.rom.mem.init = fw
    return fw


def install_spiflash_firmware(soc, ident):
    """Finalize *soc*, generate SPI Flash firmware, and install it into ROM.

    Same contract as :func:`install_uart_firmware` but installs the SPI
    Flash JEDEC ID reader firmware instead.  The SoC must have both a
    ``uart`` and a ``spiflash`` CSR group.
    """
    soc.finalize()
    csr_origin = soc.bus.regions["csr"].origin
    paging     = soc.csr.paging
    uart_base  = csr_origin + soc.csr.locs["uart"] * paging
    spi_base   = csr_origin + soc.csr.locs["spiflash"] * paging
    fw = generate_spiflash_firmware(
        uart_base=uart_base,
        spiflash_base=spi_base,
        ident=ident,
    )
    soc.rom.mem.init = fw
    return fw


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Generate sample UART firmware and print diagnostics.
    uart_base = 0xf0001800
    ident = "fpgas-online UART Test SoC -- TT FPGA"
    fw = generate_uart_firmware(uart_base, ident)

    print(f"UART firmware: {len(fw)} words, {len(fw) * 4} bytes")
    assert len(fw) <= 256, f"UART firmware too large: {len(fw)} words > 256 (1 KB)"
    print(f"  Fits in 1 KB ROM: ✓")

    # Verify address split/reconstruction.
    upper, lower = _split_imm32(uart_base)
    if lower < 0:
        recon = ((upper << 12) & 0xFFFFFFFF) + lower
    else:
        recon = (upper << 12) + lower
    recon = recon & 0xFFFFFFFF
    assert recon == uart_base, f"Split mismatch: 0x{recon:08x} != 0x{uart_base:08x}"
    print(f"  UART base 0x{uart_base:08x} split/recon: ✓")

    # Generate sample SPI Flash firmware and verify size.
    spiflash_base = 0xf0002000
    spi_ident = "fpgas-online SPI Flash Test SoC -- Fomu EVT"
    spi_fw = generate_spiflash_firmware(uart_base, spiflash_base, spi_ident)

    print(f"\nSPI Flash firmware: {len(spi_fw)} words, {len(spi_fw) * 4} bytes")
    assert len(spi_fw) <= 256, f"SPI Flash firmware too large: {len(spi_fw)} words > 256 (1 KB)"
    print(f"  Fits in 1 KB ROM: ✓")

    # Verify SPI base address split.
    upper, lower = _split_imm32(spiflash_base)
    if lower < 0:
        recon = ((upper << 12) & 0xFFFFFFFF) + lower
    else:
        recon = (upper << 12) + lower
    recon = recon & 0xFFFFFFFF
    assert recon == spiflash_base, f"Split mismatch: 0x{recon:08x} != 0x{spiflash_base:08x}"
    print(f"  SPI base 0x{spiflash_base:08x} split/recon: ✓")

    # Show embedded strings from SPI firmware.
    raw = b""
    for word in spi_fw:
        raw += word.to_bytes(4, "little")
    print("\nSPI Flash firmware embedded strings:")
    for s in raw.split(b"\x00"):
        s = s.replace(b"\r", b"\\r").replace(b"\n", b"\\n")
        if s:
            text = s.decode("ascii", errors="replace")
            if any(c.isalpha() for c in text):
                print(f"  {text!r}")
