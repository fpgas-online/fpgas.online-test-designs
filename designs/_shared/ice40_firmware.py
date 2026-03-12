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
S0   = 8   # x8  — callee-saved (used for UART base)
A0   = 10  # x10 — argument / return value


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


# --- Instruction wrappers ---

_OP_LUI    = 0b0110111
_OP_AUIPC  = 0b0010111
_OP_JAL    = 0b1101111
_OP_JALR   = 0b1100111
_OP_BRANCH = 0b1100011
_OP_LOAD   = 0b0000011
_OP_STORE  = 0b0100011
_OP_IMM    = 0b0010011

def _lui(rd, imm20):      return _u_type(_OP_LUI, rd, imm20)
def _auipc(rd, imm20):    return _u_type(_OP_AUIPC, rd, imm20)
def _jal(rd, off):         return _j_type(_OP_JAL, rd, off)
def _jalr(rd, rs1, off=0): return _i_type(_OP_JALR, rd, 0b000, rs1, off)
def _beq(rs1, rs2, off):  return _b_type(_OP_BRANCH, 0b000, rs1, rs2, off)
def _bne(rs1, rs2, off):  return _b_type(_OP_BRANCH, 0b001, rs1, rs2, off)
def _lw(rd, rs1, off=0):  return _i_type(_OP_LOAD, rd, 0b010, rs1, off)
def _lbu(rd, rs1, off=0): return _i_type(_OP_LOAD, rd, 0b100, rs1, off)
def _sw(rs2, rs1, off=0): return _s_type(_OP_STORE, 0b010, rs1, rs2, off)
def _addi(rd, rs1, imm):  return _i_type(_OP_IMM, rd, 0b000, rs1, imm)
def _nop():                return _addi(ZERO, ZERO, 0)


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

    # Echo loop (words 11-17).
    i_echo_loop = len(words)
    words.append(_lw(T0, S0, 8))                        # 11: t0 = UART_RXEMPTY
    words.append(_bne(T0, ZERO, w(i_echo_loop) - w(i_echo_loop + 1)))  # 12: wait
    words.append(_lw(A0, S0, 0))                        # 13: a0 = UART_RXTX (read)

    i_tx_wait = len(words)
    words.append(_lw(T0, S0, 4))                        # 14: t0 = UART_TXFULL
    words.append(_bne(T0, ZERO, w(i_tx_wait) - w(i_tx_wait + 1)))  # 15: wait
    words.append(_sw(A0, S0, 0))                        # 16: UART_RXTX = a0 (write)

    i_echo_jal = len(words)
    words.append(_jal(ZERO, w(i_echo_loop) - w(i_echo_jal)))  # 17: → echo_loop

    # putstr subroutine (words 18-25).
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


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Generate sample firmware and print diagnostics.
    uart_base = 0xf0001800
    ident = "fpgas-online UART Test SoC -- TT FPGA"
    fw = generate_uart_firmware(uart_base, ident)

    print(f"Firmware: {len(fw)} words, {len(fw) * 4} bytes")
    print(f"UART base: 0x{uart_base:08x}")
    upper, lower = _split_imm32(uart_base)
    print(f"  LUI imm20: 0x{upper:05x} ({upper})")
    print(f"  ADDI imm12: {lower} (0x{lower & 0xFFF:03x})")
    recon = (upper << 12) + (lower if lower >= 0 else lower + 0x1000 - 0x1000)
    # Verify reconstruction.
    if lower < 0:
        recon = ((upper << 12) & 0xFFFFFFFF) + lower
    else:
        recon = (upper << 12) + lower
    recon = recon & 0xFFFFFFFF
    assert recon == uart_base, f"Split/reconstruct mismatch: 0x{recon:08x} != 0x{uart_base:08x}"
    print(f"  Reconstructed: 0x{recon:08x} ✓")

    print()
    print("Firmware hex dump (first 32 words):")
    for i, word in enumerate(fw[:32]):
        addr = i * 4
        print(f"  0x{addr:04x}: 0x{word:08x}")

    # Show string data.
    string_start = None
    for i, word in enumerate(fw):
        b = word.to_bytes(4, "little")
        if any(0x20 <= c < 0x7F or c in (0x0D, 0x0A, 0x00) for c in b):
            if all(0x20 <= c < 0x7F or c in (0x0D, 0x0A, 0x00) for c in b):
                if string_start is None:
                    string_start = i

    if string_start:
        raw = b""
        for word in fw[string_start:]:
            raw += word.to_bytes(4, "little")
        # Print strings (split on null).
        print()
        print("Embedded strings:")
        for s in raw.split(b"\x00"):
            s = s.replace(b"\r", b"\\r").replace(b"\n", b"\\n")
            if s:
                print(f"  {s.decode('ascii', errors='replace')!r}")
