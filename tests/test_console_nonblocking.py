"""Simulation tests: the BIOS console (LiteX's crossover UART) must not stall the CPU when nobody reads it.

The CPU side is driven the way LiteX's libbase uart_write() drives it: wait while `txfull`, then write
`rxtx`. The crossover side is the host's `xover_rxtx`/`xover_rxempty` CSRs.
"""

from litex.soc.cores.uart import UARTCrossover
from migen import Memory, Signal, run_simulation

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer

CLK_FREQ = 100_000  # a slow simulated clock keeps the flush timeout (1 ms here) at 100 cycles
TIMEOUT_S = 1e-3
TIMEOUT_CYCLES = int(CLK_FREQ * TIMEOUT_S)
TEXT = bytes((0x20 + i % 95) for i in range(300))  # far more than any FIFO on the path
WAIT_LIMIT = 50 * TIMEOUT_CYCLES  # the most a single character may wait before we call it blocked


def _console(nonblocking):
    uart = UARTCrossover(tx_fifo_depth=16, rx_fifo_depth=16)
    if nonblocking:
        uart.add_auto_tx_flush(sys_clk_freq=CLK_FREQ, timeout=TIMEOUT_S)
    # migen 7bf0214 (2026-01-02) made FIFO write ports write-only (dat_r=None), but its simulator's
    # MemoryToArray still reads dat_r from every port. Give those ports a read signal nobody uses.
    fragment = uart.get_fragment()
    for special in fragment.specials:
        if isinstance(special, Memory):
            for port in special.ports:
                if port.dat_r is None:
                    port.dat_r = Signal(special.width)
    return uart, fragment


def _run(console, read_every=None):
    """Write TEXT from the CPU side; read the crossover every `read_every` cycles (None: never).

    Returns (bytes written before a character blocked for WAIT_LIMIT cycles, bytes the reader got).
    """
    uart, fragment = console
    written = bytearray()
    received = bytearray()
    done = []

    def cpu():
        for c in TEXT:
            waited = 0
            while (yield uart._txfull.status):
                waited += 1
                if waited > WAIT_LIMIT:
                    done.append(True)
                    return
                yield
            yield uart._rxtx.r.eq(c)
            yield uart._rxtx.re.eq(1)
            yield
            yield uart._rxtx.re.eq(0)
            yield
            written.append(c)
        # Let whatever is still queued reach the reader.
        for _ in range(50 * (read_every or 1) * len(TEXT) // 16 + 1000):
            yield
        done.append(True)

    def host():
        cycle = 0
        while not done:
            if read_every is not None and cycle % read_every == 0 and not (yield uart.xover._rxempty.status):
                received.append((yield uart.xover._rxtx.w))
                yield uart.xover._rxtx.we.eq(1)
                yield
                yield uart.xover._rxtx.we.eq(0)
            yield
            cycle += 1

    run_simulation(fragment, [cpu(), host()])
    return bytes(written), bytes(received)


def test_stock_crossover_blocks_the_cpu_when_nobody_reads():
    # The control: without the fix the writer gets stuck once the FIFOs on the path fill up.
    written, _ = _run(_console(nonblocking=False))
    assert len(written) < 64


def test_nonblocking_console_never_blocks_the_cpu_without_a_reader():
    written, _ = _run(_console(nonblocking=True))
    assert written == TEXT


def test_nonblocking_console_loses_nothing_while_a_reader_keeps_up():
    # A reader that takes one character every 10 cycles is far slower than the CPU writes, but
    # never leaves the FIFO full for the flush timeout, so everything arrives, in order.
    written, received = _run(_console(nonblocking=True), read_every=10)
    assert written == TEXT
    assert received == TEXT
