"""A small RV32I machine with a LiteX UART and a bit-banged SPI flash, to run designs/_shared/ice40_firmware.py.

The firmware is hand-encoded words, so a wrong branch offset or register is only found by running it. This
runs it: the ROM at address 0, the UART's CSRs (RXTX, TXFULL, RXEMPTY, EV_PENDING) at `uart_base`, and the
flash's bitbang and miso CSRs at `spi_base`. Only the instructions the firmware uses are implemented; any
other raises.
"""

MASK = 0xFFFFFFFF


def _sx(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


class SpiFlash:
    """Answers 0x9F with its three JEDEC ID bytes. SPI mode 0: sampled on the rising edge, driven on the falling."""

    def __init__(self, jedec):
        self.jedec = bytes(jedec)
        self.pins = 0b100  # CS_N high
        self.miso = 1
        self.selects = 0  # how many times CS_N went low
        self._deselect()

    def _deselect(self):
        self.command = 0
        self.bits_in = 0
        self.bits_out = 0

    def write(self, pins):
        mosi, clk, cs_n = pins & 1, (pins >> 1) & 1, (pins >> 2) & 1
        was_clk, was_cs_n = (self.pins >> 1) & 1, (self.pins >> 2) & 1
        self.pins = pins
        if cs_n:
            self._deselect()
            self.miso = 1
            return
        if was_cs_n:
            self.selects += 1
        if clk and not was_clk and self.bits_in < 8:
            self.command = (self.command << 1) | mosi
            self.bits_in += 1
        if was_clk and not clk and self.bits_in == 8 and self.command == 0x9F:
            byte = self.jedec[(self.bits_out // 8) % len(self.jedec)]
            self.miso = (byte >> (7 - self.bits_out % 8)) & 1
            self.bits_out += 1


class Machine:
    def __init__(self, rom, uart_base, spi_base=None, flash=None):
        self.rom = list(rom)
        self.uart_base = uart_base
        self.spi_base = spi_base
        self.flash = flash
        self.x = [0] * 32
        self.pc = 0
        self.rx = bytearray()  # sent by the host, not yet taken by the firmware
        self.tx = bytearray()  # sent by the firmware
        self.steps = 0

    # -- the bus -----------------------------------------------------------------------------------------

    def _load(self, addr, size):
        if addr < len(self.rom) * 4:
            word = self.rom[addr // 4]
            return (word >> (8 * (addr % 4))) & 0xFF if size == 1 else word
        if addr == self.uart_base:
            return self.rx[0] if self.rx else 0
        if addr == self.uart_base + 4:
            return 0  # TX never full
        if addr == self.uart_base + 8:
            return 0 if self.rx else 1
        if self.spi_base is not None and addr == self.spi_base + 4:
            return self.flash.miso
        raise ValueError(f"load from {addr:#x} at pc {self.pc:#x}")

    def _store(self, addr, value):
        if addr == self.uart_base:
            self.tx.append(value & 0xFF)
        elif addr == self.uart_base + 16:
            if value & 2 and self.rx:  # clearing the RX event takes the byte off the FIFO
                del self.rx[0]
        elif self.spi_base is not None and addr == self.spi_base:
            self.flash.write(value & 7)
        else:
            raise ValueError(f"store to {addr:#x} at pc {self.pc:#x}")

    # -- the CPU -----------------------------------------------------------------------------------------

    def step(self):
        """Run one instruction. True when it can never get further: waiting for a byte, or a jump to itself."""
        ins = self.rom[self.pc // 4]
        opcode, rd, funct3 = ins & 0x7F, (ins >> 7) & 0x1F, (ins >> 12) & 7
        rs1, rs2 = (ins >> 15) & 0x1F, (ins >> 20) & 0x1F
        imm_i = _sx(ins >> 20, 12)
        x = self.x
        next_pc = self.pc + 4
        value = None
        waiting = False
        if opcode == 0b0110111:  # LUI
            value = ins & 0xFFFFF000
        elif opcode == 0b0010111:  # AUIPC
            value = self.pc + (ins & 0xFFFFF000)
        elif opcode == 0b1101111:  # JAL
            imm = ((ins >> 31) << 20) | (((ins >> 12) & 0xFF) << 12) | (((ins >> 20) & 1) << 11)
            imm |= ((ins >> 21) & 0x3FF) << 1
            value, next_pc = next_pc, self.pc + _sx(imm, 21)
        elif opcode == 0b1100111 and funct3 == 0:  # JALR
            value, next_pc = next_pc, (x[rs1] + imm_i) & ~1 & MASK
        elif opcode == 0b1100011 and funct3 in (0, 1):  # BEQ, BNE
            imm = ((ins >> 31) << 12) | (((ins >> 7) & 1) << 11) | (((ins >> 25) & 0x3F) << 5)
            imm |= ((ins >> 8) & 0xF) << 1
            if (x[rs1] == x[rs2]) == (funct3 == 0):
                next_pc = self.pc + _sx(imm, 13)
        elif opcode == 0b0000011 and funct3 in (0b010, 0b100):  # LW, LBU
            addr = (x[rs1] + imm_i) & MASK
            value = self._load(addr, 4 if funct3 == 0b010 else 1)
            waiting = addr == self.uart_base + 8 and value == 1
        elif opcode == 0b0100011 and funct3 == 0b010:  # SW
            imm = _sx(((ins >> 25) << 5) | ((ins >> 7) & 0x1F), 12)
            self._store((x[rs1] + imm) & MASK, x[rs2])
        elif opcode == 0b0010011 and funct3 == 0b000:  # ADDI
            value = x[rs1] + imm_i
        elif opcode == 0b0010011 and funct3 == 0b111:  # ANDI
            value = x[rs1] & (imm_i & MASK)
        elif opcode == 0b0010011 and funct3 == 0b110:  # ORI
            value = x[rs1] | (imm_i & MASK)
        elif opcode == 0b0010011 and funct3 == 0b001 and ins >> 25 == 0:  # SLLI
            value = x[rs1] << rs2
        elif opcode == 0b0010011 and funct3 == 0b101 and ins >> 25 == 0:  # SRLI
            value = x[rs1] >> rs2
        elif opcode == 0b0110011 and ins >> 25 == 0 and funct3 == 0b000:  # ADD
            value = x[rs1] + x[rs2]
        elif opcode == 0b0110011 and ins >> 25 == 0 and funct3 == 0b110:  # OR
            value = x[rs1] | x[rs2]
        elif opcode == 0b0110011 and ins >> 25 == 0 and funct3 == 0b111:  # AND
            value = x[rs1] & x[rs2]
        else:
            raise ValueError(f"instruction {ins:#010x} at pc {self.pc:#x} is not one the firmware should use")
        if value is not None and rd:
            x[rd] = value & MASK
        halted = next_pc == self.pc
        self.pc = next_pc
        self.steps += 1
        return waiting or halted

    def run(self, max_steps=5_000_000):
        """Run until the firmware waits for a byte that is not there, or halts. What it sent meanwhile, as text."""
        sent = len(self.tx)
        for _ in range(max_steps):
            if self.step():
                return self.tx[sent:].decode("ascii")
        raise AssertionError(f"still running after {max_steps} instructions, at pc {self.pc:#x}")

    def send(self, data):
        """The host sends `data`; what the firmware sent back by the time it is idle again."""
        self.rx += data
        return self.run()
