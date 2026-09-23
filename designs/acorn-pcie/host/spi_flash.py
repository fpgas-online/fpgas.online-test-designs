#!/usr/bin/env python3
"""Identify, back up and rewrite the Acorn's configuration flash through the fpgas.online Acorn SoC.

The SoC exposes LiteX's `S7SPIFlash` (a 40-bit SPI master whose clock goes out
through STARTUPE2) and a separate `flash_cs_n` GPIO. Chip select being ours to
hold is what makes this work: any transaction is "CS low, shift as many bytes
as it takes, CS high", so every opcode the part has is available from the host
and the gateware knows nothing about flash commands.

Read-only unless asked: a `Flash` refuses every opcode that is not on the read
list until it is built with `allow_write=True`, and `write` refuses the golden
slot (0x0) without `--i-know-this-writes-golden`. An image is checked against
the slot before anything is erased: the golden slot wants the flavour that
chain-loads 0x400000, the operational slot the one with the watchdog, and both
want the IDCODE of the part that is actually there.

Measured on pi-sw2-p48 (Pi 5, PCIe BAR0, 2026-09-21): 32 MiB read in 58 s.

Self-contained on purpose (stdlib only): the Pi hosts boot a tmpfs root with no
LiteX. Runs over PCIe BAR0 by default, or over the UART bridge with `--uart`.

    sudo python3 spi_flash.py id
    sudo python3 spi_flash.py dump factory.bin
    sudo python3 spi_flash.py verify sqrl_acorn_operational.bin 0x400000
    sudo python3 spi_flash.py write  sqrl_acorn_operational.bin 0x400000
"""

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time

CSR_BASE = 0xF0000000
SPI_CONTROL = CSR_BASE + 0x3800  # csr_map: flash = 7
SPI_STATUS = CSR_BASE + 0x3804
SPI_MOSI_HI = CSR_BASE + 0x3808  # 40-bit registers, upper word first
SPI_MOSI_LO = CSR_BASE + 0x380C
SPI_MISO_HI = CSR_BASE + 0x3810
SPI_MISO_LO = CSR_BASE + 0x3814
FLASH_CS_N = CSR_BASE + 0x4000  # csr_map: flash_cs_n = 8
SHIFT_BYTES = 5
# Shared with fpgas-acorn-verify (acorn_verify.py): one user of the SoC's SPI master at a time. Its CS and
# shift registers are single-user: two tools interleaving would corrupt a read, or a write.
LOCK = "/run/lock/fpgas-acorn.lock"

GOLDEN_ADDR = 0x000000
OPERATIONAL_ADDR = 0x400000
SLOT_SIZE = 4 << 20

RDID, RDSR1, RDCR, READ4, OTPR = 0x9F, 0x05, 0x35, 0x13, 0x4B
WREN, CLSR, PP4, P4E4, SE4 = 0x06, 0x30, 0x12, 0x21, 0xDC
READ_OPCODES = {RDID, RDSR1, RDCR, READ4, OTPR}
WRITE_OPCODES = {WREN, CLSR, PP4, P4E4, SE4}

SR_WIP, SR_E_ERR, SR_P_ERR = 0x01, 0x20, 0x40
PAGE = 256
SECTOR = 0x10000
PARAM_SECTOR = 0x1000
READ_CHUNK = 0x10000
PARTS = {0x010219: "S25FL256S", 0x010220: "S25FL512S", 0x012018: "S25FL128S"}

SYNC = bytes.fromhex("aa995566")
REG_CMD, REG_IDCODE, REG_WBSTAR, REG_TIMER, REG_FDRI = 0x04, 0x0C, 0x10, 0x11, 0x02
CMD_IPROG = 0xF
IDCODE_MASK = 0x0FFFFFFF  # the top nibble is the silicon revision
HEADER_WORDS = 64


class FlashError(Exception):
    pass


def image_info(data):
    """What a 7-series .bin says about itself in the configuration writes before the first data frame."""
    start = data.find(SYNC, 0, 4096)
    if start < 0:
        raise FlashError("no bitstream sync word in the first 4 KiB: this is not a 7-series .bin")
    info = {"sync_offset": start, "wbstar": None, "iprog": False, "watchdog": False, "idcode": None}
    words = [int.from_bytes(data[i : i + 4], "big") for i in range(start + 4, start + 4 + 4 * HEADER_WORDS, 4)]
    i = 0
    while i < len(words) - 1:
        word = words[i]
        i += 1
        if word >> 29 != 1 or (word >> 27) & 3 != 2:  # not a type-1 write (NOPs land here)
            continue
        reg, count = (word >> 13) & 0x3FFF, word & 0x7FF
        if reg == REG_FDRI:
            break
        if count == 1:
            value = words[i]
            if reg == REG_WBSTAR:
                info["wbstar"] = value & 0x1FFFFFFF
            elif reg == REG_TIMER:
                info["watchdog"] = bool(value & 0x40000000)
            elif reg == REG_CMD and value == CMD_IPROG:
                info["iprog"] = True
            elif reg == REG_IDCODE:
                info["idcode"] = value
        i += count
    return info


def check_image_for_slot(addr, data, idcode, allow_golden=False):
    if addr not in (GOLDEN_ADDR, OPERATIONAL_ADDR):
        raise FlashError(f"{addr:#x} is not a slot: golden is {GOLDEN_ADDR:#x}, operational is {OPERATIONAL_ADDR:#x}")
    if len(data) > SLOT_SIZE:
        raise FlashError(f"image of {len(data)} bytes does not fit the {SLOT_SIZE}-byte slot")
    info = image_info(data)
    if info["idcode"] is None or (info["idcode"] ^ idcode) & IDCODE_MASK:
        found = "none" if info["idcode"] is None else f"{info['idcode']:#010x}"
        raise FlashError(f"image IDCODE {found} is not this part's {idcode:#010x}")
    chain_loads = info["iprog"] and info["wbstar"] == OPERATIONAL_ADDR
    if addr == OPERATIONAL_ADDR:
        if chain_loads or info["iprog"]:
            raise FlashError("this image chain-loads another one (the golden flavour): not for the operational slot")
        if not info["watchdog"]:
            raise FlashError("operational image has no watchdog (TIMER_CFG): a bad one would never fall back")
    else:
        if not chain_loads:
            raise FlashError(f"golden image does not chain-load {OPERATIONAL_ADDR:#x}: use the _fallback flavour")
        if not allow_golden:
            raise FlashError("writing the golden slot needs --i-know-this-writes-golden")
    return info


class Flash:
    """`bus` has `read(addr) -> int` and `write(addr, value)` for 32-bit CSRs."""

    def __init__(self, bus, allow_write=False):
        self.bus = bus
        self.allowed = READ_OPCODES | (WRITE_OPCODES if allow_write else set())
        self._woken = False

    # -- SPI ---------------------------------------------------------------------------------------

    def _shift(self, data):
        """Clock up to five bytes out, most significant bit first, and return the bytes that came back."""
        bits = 8 * len(data)
        value = int.from_bytes(data, "big") << (40 - bits)  # SPIMaster shifts from the top of the register
        self.bus.write(SPI_MOSI_HI, value >> 32)
        self.bus.write(SPI_MOSI_LO, value & 0xFFFFFFFF)
        self.bus.write(SPI_CONTROL, bits << 8 | 1)
        while not self.bus.read(SPI_STATUS) & 1:
            pass
        value = self.bus.read(SPI_MISO_HI) << 32 | self.bus.read(SPI_MISO_LO)
        return (value & ((1 << bits) - 1)).to_bytes(len(data), "big")

    def _wake(self):
        # STARTUPE2 does not pass the first three USRCCLKO edges after configuration on to CCLK, so the first
        # transfer reaches the flash three clocks short (on p48 the first RDID after every load read all ones).
        # Spend them with the flash deselected, where clocks mean nothing to it. The SoC resets flash_cs_n to
        # 0, so deselecting is a real step and not a formality.
        if not self._woken:
            self.bus.write(FLASH_CS_N, 1)
            self._shift(b"\xff")
            self._woken = True

    def transaction(self, tx, rx_len=0):
        if tx[0] not in self.allowed:
            kind = "this Flash is read-only" if tx[0] in WRITE_OPCODES else "not an opcode this tool knows"
            raise FlashError(f"opcode {tx[0]:#04x} refused: {kind}")
        self._wake()
        self.bus.write(FLASH_CS_N, 0)
        try:
            out = bytes(tx) + bytes(rx_len)
            back = b"".join(self._shift(out[i : i + SHIFT_BYTES]) for i in range(0, len(out), SHIFT_BYTES))
            return back[len(tx) :]
        finally:
            self.bus.write(FLASH_CS_N, 1)

    # -- reading -----------------------------------------------------------------------------------

    def identify(self):
        rdid = self.transaction([RDID], 6)
        jedec = int.from_bytes(rdid[:3], "big")
        capacity = rdid[2]
        otp = self.transaction([OTPR, 0, 0, 0, 0], 16)
        return {
            "rdid": rdid.hex(),
            "part": PARTS.get(jedec, "unknown"),
            "size_bytes": 1 << capacity if 0x10 <= capacity <= 0x20 else None,
            "unique_id": otp.hex(),  # Spansion programs a 128-bit random number here at the factory
            "status": self.transaction([RDSR1], 1).hex(),
            "config": self.transaction([RDCR], 1).hex(),
            "quad_enabled": bool(self.transaction([RDCR], 1)[0] & 0x02),
        }

    def read(self, addr, length):
        out = bytearray()
        while len(out) < length:
            n = min(READ_CHUNK, length - len(out))
            out += self.transaction([READ4, *(addr + len(out)).to_bytes(4, "big")], n)
        return bytes(out)

    def first_difference(self, addr, data):
        for base in range(0, len(data), READ_CHUNK):
            want = data[base : base + READ_CHUNK]
            got = self.read(addr + base, len(want))
            if got != want:
                return addr + base + next(i for i in range(len(want)) if got[i] != want[i])
        return None

    # -- writing -----------------------------------------------------------------------------------

    def _write_op(self, tx, what):
        self.transaction([WREN])
        self.transaction(tx)
        while True:
            status = self.transaction([RDSR1], 1)[0]
            if not status & SR_WIP:
                break
        if status & (SR_E_ERR | SR_P_ERR):
            self.transaction([CLSR])
            raise FlashError(f"{what} failed: status {status:#04x}")

    def _erase(self, addr, length):
        """Erase the sectors covering the range, then prove they are blank.

        This part overlays its first 128 KiB with 4 KiB parameter sectors. Whether a 64 KiB erase reaches
        them was not something to take on trust, so that region gets 4 KiB erases and everything is read back.
        """
        end = addr + length
        pos = addr
        while pos < end:
            if pos < 32 * PARAM_SECTOR:
                opcode, size = P4E4, PARAM_SECTOR
            else:
                opcode, size = SE4, SECTOR
            base = pos & ~(size - 1)
            self._write_op([opcode, *base.to_bytes(4, "big")], f"erase at {base:#x}")
            if self.read(base, size) != b"\xff" * size:
                raise FlashError(f"sector at {base:#x} is not blank after erase")
            pos = base + size

    def write_image(self, addr, data, idcode, allow_golden=False, progress=lambda done, total: None):
        if WREN not in self.allowed:
            raise FlashError("this Flash is read-only: build it with allow_write=True")
        check_image_for_slot(addr, data, idcode, allow_golden)
        self._erase(addr, len(data))
        pos = 0
        while pos < len(data):
            n = min(PAGE, len(data) - pos)  # both slots start on a page boundary, so pages never wrap
            self._write_op([PP4, *(addr + pos).to_bytes(4, "big"), *data[pos : pos + n]], f"program at {addr + pos:#x}")
            pos += n
            progress(pos, len(data))
        bad = self.first_difference(addr, data)
        if bad is not None:
            raise FlashError(f"verify failed at {bad:#x}")


# -- buses ---------------------------------------------------------------------------------------------


class Bar0Bus:
    """The SoC's CSRs through PCIe BAR0, with no kernel driver: needs root and memory decoding enabled."""

    def __init__(self, bdf):
        import mmap
        import os
        import struct

        self._struct = struct
        fd = os.open(f"/sys/bus/pci/devices/{bdf}/resource0", os.O_RDWR | os.O_SYNC)
        self._map = mmap.mmap(fd, 0x10000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)

    def read(self, addr):
        off = addr - CSR_BASE
        return self._struct.unpack("<I", self._map[off : off + 4])[0]

    def write(self, addr, value):
        off = addr - CSR_BASE
        self._map[off : off + 4] = self._struct.pack("<I", value)


class UARTBus:
    """The same CSRs over the UART bridge. Fine for `id`; a full dump would take hours."""

    def __init__(self, port):
        import pathlib

        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import uartbone_link

        self._link = uartbone_link.UARTBoneLink(uartbone_link._serial_opener(port))
        self._link.connect()

    def read(self, addr):
        return self._link.read(addr)[0]

    def write(self, addr, value):
        self._link.write(addr, [value])


def hold_lock(path=LOCK):
    """Take the SoC lock, waiting for whoever has it; the returned file holds it until closed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    held = open(path, "w")  # noqa: SIM115 -- the open file is the lock, kept by the caller
    fcntl.flock(held, fcntl.LOCK_EX)
    return held


def _progress(done, total):
    if done == total or done % (256 * PAGE) == 0:
        print(f"  programmed {done}/{total} bytes", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--bdf", default="0001:01:00.0", help="PCIe address of the SoC")
    parser.add_argument("--uart", metavar="PORT", help="use the UART bridge on PORT instead of PCIe")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("id", help="print what the flash says it is, as JSON")
    dump = sub.add_parser("dump", help="read the whole flash to a file")
    dump.add_argument("file")
    for name in ("verify", "write"):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("addr", type=lambda s: int(s, 0))
        p.add_argument("--idcode", type=lambda s: int(s, 0), required=name == "write", help="the FPGA's JTAG IDCODE")
    sub.choices["write"].add_argument("--i-know-this-writes-golden", action="store_true")
    args = parser.parse_args()

    lock = hold_lock()  # noqa: F841 -- held until main returns
    bus = UARTBus(args.uart) if args.uart else Bar0Bus(args.bdf)
    flash = Flash(bus, allow_write=args.command == "write")
    try:
        info = flash.identify()
        if info["size_bytes"] is None:
            raise FlashError(f"flash did not identify itself: RDID {info['rdid']}")
        if args.command == "id":
            print(json.dumps(info, indent=1))
        elif args.command == "dump":
            start = time.monotonic()
            data = flash.read(0, info["size_bytes"])
            with open(args.file, "wb") as f:
                f.write(data)
            print(f"{len(data)} bytes in {time.monotonic() - start:.0f} s, sha256 {hashlib.sha256(data).hexdigest()}")
        else:
            with open(args.file, "rb") as f:
                data = f.read()
            if args.command == "write":
                if not info["quad_enabled"]:
                    raise FlashError("the flash's QUAD bit is clear, and these images are built to load in x4 mode")
                flash.write_image(args.addr, data, args.idcode, args.i_know_this_writes_golden, _progress)
                digest = hashlib.sha256(data).hexdigest()
                print(f"wrote and verified {len(data)} bytes at {args.addr:#x}, sha256 {digest}")
            else:
                bad = flash.first_difference(args.addr, data)
                if bad is not None:
                    raise FlashError(f"verify failed at {bad:#x}")
                print(f"{len(data)} bytes at {args.addr:#x} match {args.file}")
        print("RESULT: PASS")
    except FlashError as e:
        print(f"error: {e}")
        print("RESULT: FAIL")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
