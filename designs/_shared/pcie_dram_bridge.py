"""Move a block between LitePCIe's DMA streams and DDR3: Pi RAM -> Acorn DDR3, and back.

LitePCIe's DMA gives the FPGA two 64-bit streams: `source` carries what the host's DMA reader fetched from Pi
memory, `sink` takes what the DMA writer will store there. This bridge sits at the far end of those streams.
A transfer is `length` 64-bit words starting at DRAM word `base` (word 0 is the first 8 bytes of main RAM):

    mode = MODE_TO_DRAM    words from the host are written to base, base+1, ...
    mode = MODE_FROM_DRAM  words base, base+1, ... are read and sent to the host

Write `start` to go; `done` rises when the last word has reached the DRAM port (to-DRAM) or has been taken by
the PCIe side (from-DRAM), and `count` says how many words have moved. Outside a transfer the bridge neither
takes nor sends anything, so a block that arrives early waits, and one transfer cannot eat the next one's data.

It needs a write port and a read port of its own (`crossbar.get_port(data_width=64)`, twice): LiteDRAM's DMA
writer and reader each drive a port's command stream, so they cannot share one.
"""

from litedram.frontend.dma import LiteDRAMDMAReader, LiteDRAMDMAWriter
from litex.gen import LiteXModule
from litex.soc.interconnect import stream
from litex.soc.interconnect.csr import CSRStatus, CSRStorage
from migen import FSM, If, NextState, NextValue, Signal

MODE_TO_DRAM = 1
MODE_FROM_DRAM = 2


class PCIeDRAMBridge(LiteXModule):
    def __init__(self, write_port, read_port, fifo_depth=16):
        data_width = write_port.data_width
        assert read_port.data_width == data_width
        self.write_port, self.read_port = write_port, read_port
        self.sink = stream.Endpoint([("data", data_width)])  # from the host (pcie_dma.source)
        self.source = stream.Endpoint([("data", data_width)])  # to the host (pcie_dma.sink)

        aw = write_port.address_width
        self._base = CSRStorage(
            aw, description="First DRAM word of the transfer (64-bit words from the start of main RAM)."
        )
        self._length = CSRStorage(aw + 1, description="Number of 64-bit words to move.")
        self._mode = CSRStorage(2, description="1: host to DRAM. 2: DRAM to host.")
        self._start = CSRStorage(1, description="Write to start a transfer with the settings above.")
        self._done = CSRStatus(1, description="The last transfer has finished. Cleared by start.")
        self._count = CSRStatus(aw + 1, description="Words moved so far in this transfer.")

        # # #

        self.writer = writer = LiteDRAMDMAWriter(write_port, fifo_depth=fifo_depth)
        self.reader = reader = LiteDRAMDMAReader(read_port, fifo_depth=fifo_depth)

        base, length = Signal(aw), Signal(aw + 1)
        issued, moved = Signal(aw + 1), Signal(aw + 1)  # read requests sent; words through the data handshake
        done = Signal()
        self.comb += [self._done.status.eq(done), self._count.status.eq(moved)]

        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act(
            "IDLE",
            If(
                self._start.re,
                NextValue(base, self._base.storage),
                NextValue(length, self._length.storage),
                NextValue(issued, 0),
                NextValue(moved, 0),
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
            self.sink.ready.eq(writer.sink.ready),
            If(
                self.sink.valid & writer.sink.ready,
                NextValue(moved, moved + 1),
                If(moved == length - 1, NextState("FLUSH")),
            ),
        )
        # The DMA writer queues data behind its commands; done must not rise while words are still in that queue.
        fsm.act("FLUSH", If(~writer.fifo.source.valid, NextValue(done, 1), NextState("IDLE")))
        fsm.act(
            "FROM-DRAM",
            reader.sink.valid.eq(issued != length),
            reader.sink.address.eq(base + issued),
            If(reader.sink.valid & reader.sink.ready, NextValue(issued, issued + 1)),
            reader.source.connect(self.source),
            If(
                self.source.valid & self.source.ready,
                NextValue(moved, moved + 1),
                If(moved == length - 1, NextValue(done, 1), NextState("IDLE")),
            ),
        )
