"""Move a block between LitePCIe's DMA streams and DDR3: Pi RAM -> Acorn DDR3, and back.

LitePCIe's DMA gives the FPGA two 64-bit streams: `source` carries what the host's DMA reader fetched from Pi
memory, `sink` takes what the DMA writer will store there. This bridge sits at the far end of those streams.
A transfer is `length` 64-bit words starting at DRAM word `base` (word 0 is the first 8 bytes of main RAM):

    mode = MODE_TO_DRAM    words from the host are written to base, base+1, ...
    mode = MODE_FROM_DRAM  words base, base+1, ... are read and sent to the host

Write `start` to go; `done` rises when the last word has reached the DRAM port (to-DRAM) or has been taken by
the PCIe side (from-DRAM), and `count` says how many words have moved. Outside a transfer the bridge neither
takes nor sends anything, so a block that arrives early waits, and one transfer cannot eat the next one's data.

It needs a write port and a read port of its own, at the controller's width (`crossbar.get_port(mode=...)`,
twice): LiteDRAM's DMA writer and reader each drive a port's command stream, so they cannot share one.

A controller word is usually wider than 64 bits (128 on the Acorn: 16 DQ, both edges, four phases), so the
bridge puts LiteDRAM's width converter between its 64-bit streams and each port. The converter sends the
controller a word once every 64-bit part of it has been asked for, or once a command says it is the last; a
block that starts or ends part-way through a controller word leaves the other parts of that word as they
were. So the bridge marks the last word of every transfer, and in the to-DRAM direction counts the words the
controller has taken: `done` is not the converter having been handed the data, but the DRAM having it.
"""

from litedram.common import LiteDRAMNativePort
from litedram.frontend.adapter import LiteDRAMNativePortConverter
from litedram.frontend.dma import LiteDRAMDMAReader, LiteDRAMDMAWriter
from litex.gen import LiteXModule
from litex.soc.interconnect import stream
from litex.soc.interconnect.csr import CSRStatus, CSRStorage
from migen import FSM, If, NextState, NextValue, Signal, log2_int

MODE_TO_DRAM = 1
MODE_FROM_DRAM = 2
DATA_WIDTH = 64  # LitePCIe's DMA streams


class PCIeDRAMBridge(LiteXModule):
    def __init__(self, write_port, read_port, fifo_depth=16):
        assert write_port.data_width == read_port.data_width
        assert write_port.address_width == read_port.address_width
        self.write_port, self.read_port = write_port, read_port  # the controller's
        shift = log2_int(write_port.data_width // DATA_WIDTH)  # 64-bit words per controller word, as a shift
        self.sink = stream.Endpoint([("data", DATA_WIDTH)])  # from the host (pcie_dma.source)
        self.source = stream.Endpoint([("data", DATA_WIDTH)])  # to the host (pcie_dma.sink)

        aw = write_port.address_width + shift
        self._base = CSRStorage(
            aw, description="First DRAM word of the transfer (64-bit words from the start of main RAM)."
        )
        self._length = CSRStorage(aw + 1, description="Number of 64-bit words to move.")
        self._mode = CSRStorage(2, description="1: host to DRAM. 2: DRAM to host.")
        self._start = CSRStorage(1, description="Write to start a transfer with the settings above.")
        self._done = CSRStatus(1, description="The last transfer has finished. Cleared by start.")
        self._count = CSRStatus(aw + 1, description="Words moved so far in this transfer.")

        # # #

        if shift:
            write_user = LiteDRAMNativePort("write", aw, DATA_WIDTH)
            read_user = LiteDRAMNativePort("read", aw, DATA_WIDTH)
            self.write_converter = LiteDRAMNativePortConverter(write_user, write_port)
            self.read_converter = LiteDRAMNativePortConverter(read_user, read_port)
        else:
            write_user, read_user = write_port, read_port
        self.writer = writer = LiteDRAMDMAWriter(write_user, fifo_depth=fifo_depth)
        self.reader = reader = LiteDRAMDMAReader(read_user, fifo_depth=fifo_depth)

        base, length = Signal(aw), Signal(aw + 1)
        issued, moved = Signal(aw + 1), Signal(aw + 1)  # read requests sent; words through the data handshake
        last = Signal(aw + 1)  # the last word of the block, as an offset from base
        stored, to_store = Signal(aw + 1), Signal(aw + 1)  # controller words taken by the DRAM; and in the block
        done = Signal()
        self.comb += [self._done.status.eq(done), self._count.status.eq(moved)]
        self.sync += If(write_port.wdata.valid & write_port.wdata.ready, stored.eq(stored + 1))

        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act(
            "IDLE",
            If(
                self._start.re,
                NextValue(base, self._base.storage),
                NextValue(length, self._length.storage),
                NextValue(last, self._length.storage - 1),
                NextValue(issued, 0),
                NextValue(moved, 0),
                NextValue(stored, 0),
                # the controller words from the one holding `base` to the one holding the block's last word
                NextValue(
                    to_store,
                    ((self._base.storage + self._length.storage - 1) >> shift) - (self._base.storage >> shift) + 1,
                ),
                NextValue(done, self._length.storage == 0),
                If(
                    self._length.storage != 0,
                    If(self._mode.storage == MODE_TO_DRAM, NextState("TO-DRAM")),
                    If(self._mode.storage == MODE_FROM_DRAM, NextState("FROM-DRAM")),
                ),
            ),
        )
        fsm.act(
            "TO-DRAM",
            writer.sink.valid.eq(self.sink.valid),
            writer.sink.address.eq(base + moved),
            writer.sink.data.eq(self.sink.data),
            # The converter must not wait for the rest of a controller word after the block's last word. Only with
            # the command itself: the converter samples `last` every cycle it is filling a word, valid or not, and
            # an early one makes it send the controller half a word before the block's last word has arrived.
            write_user.cmd.last.eq(write_user.cmd.valid & (moved == last)),
            self.sink.ready.eq(writer.sink.ready),
            If(
                self.sink.valid & writer.sink.ready,
                NextValue(moved, moved + 1),
                If(moved == last, NextState("FLUSH")),
            ),
        )
        # The DMA writer queues data behind its commands, and the converter behind that: done must not rise until
        # the controller has taken every word of the block.
        fsm.act("FLUSH", If(stored == to_store, NextValue(done, 1), NextState("IDLE")))
        fsm.act(
            "FROM-DRAM",
            reader.sink.valid.eq(issued != length),
            reader.sink.address.eq(base + issued),
            reader.sink.last.eq(read_user.cmd.valid & (issued == last)),  # as above, for a part-asked word
            If(reader.sink.valid & reader.sink.ready, NextValue(issued, issued + 1)),
            # `last` stays here: LitePCIe's DMA writer would end the host's buffer early on it
            reader.source.connect(self.source, omit={"last"}),
            If(
                self.source.valid & self.source.ready,
                NextValue(moved, moved + 1),
                If(moved == last, NextValue(done, 1), NextState("IDLE")),
            ),
        )
