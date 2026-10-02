#!/usr/bin/env python3
"""Move blocks between the Pi's RAM and the Acorn's DDR3 through litepcie.ko's DMA, and check every byte.

Needs the operational image of a build that has the PCIeDRAMBridge (csr.json lists `pcie_dram`) and
litepcie.ko bound to the board (/dev/litepcie0). Run as root on the Pi the board is in:

    sudo python3 dma_selftest.py --csr acorn-cle-215p-csr.json [--device /dev/litepcie0] [--big-mib 64]

The transfers are done by fpgas_online_verify.boards.acorn.dma, the same code the boot check's `dma` test
runs. It comes from the installed fpgas-online-acorn-tools package or, run from a checkout, from verify/src.

1. The driver's device answers: the SoC's identifier is read through its register ioctl.
2. The DRAM is the controller's (the BIOS has finished setting it up), waited for.
3. A zero-length transfer in each direction finishes at once with nothing moved.
4. Round trips: a block of random data is written to the DRAM and read back, for lengths of 1 word, just
   under, exactly and just over one DMA buffer, a page, and several buffers, at bases at the bottom, in the
   middle and at the very top of the DRAM.
5. Addressing: a block in which every word holds its own DRAM address is written once, then read back in
   pieces that start part-way in. A piece read from base B must hold B, B+1, ...: a bridge that ignored the
   base, or counted from the wrong end, fails here though it passes the round trips.
6. Neighbours: the words either side of a block are written first and must be unchanged after it.
7. A big block (`--big-mib`), timed in both directions.

Prints one line per check, the measurements as JSON, and exits 1 if any check failed.
"""

import argparse
import json
import pathlib
import random
import struct
import sys
import time

# Run from a checkout, the checkout's own code, before any older fpgas-online-acorn-tools installed on the Pi;
# otherwise the installed package.
CHECKOUT = pathlib.Path(__file__).resolve().parents[3] / "verify" / "src"
if (CHECKOUT / "fpgas_online_verify").is_dir():
    sys.path.insert(0, str(CHECKOUT))

from fpgas_online_verify.boards.acorn import check, dma  # noqa: E402  -- after sys.path

results = []


def log(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}", flush=True)
    return ok


def identifier(bridge, csrs):
    base = csrs.bases["identifier_mem"]
    out = bytearray()
    for i in range(check.IDENTIFIER_MAX):
        c = bridge.reg_read(base + 4 * i) & 0xFF
        if not c:
            break
        out.append(c)
    return out.decode(errors="replace")


def wait_dram(bridge, timeout_s, settle_s):
    """The BIOS sets the DRAM up after every SoC reset (loading litepcie.ko is one), then runs its memtest."""
    start = time.monotonic()
    while not bridge.dram_ready():
        if time.monotonic() - start > timeout_s:
            return log("the DRAM is the controller's", False, f"sdram_dfii_control still software after {timeout_s} s")
        time.sleep(0.05)
    waited = time.monotonic() - start
    time.sleep(settle_s)  # the BIOS memtest writes the bottom of the DRAM for a moment after this
    detail = f"after {waited:.1f} s, then {settle_s} s for the memtest"
    return log("the DRAM is the controller's", bridge.dram_ready(), detail)


def round_trip(bridge, rng, base, nwords):
    data = rng.randbytes(nwords * dma.WORD)
    try:
        bridge.to_dram(base, data)
        back = bridge.from_dram(base, nwords)
    except dma.DMAError as e:
        return log(f"round trip of {nwords} words at {base:#x}", False, str(e))
    return log(f"round trip of {nwords} words at {base:#x}", back == data, dma.first_difference(back, data) or "")


def addressing(bridge, base, nwords):
    def block(first, n):
        return b"".join(struct.pack("<Q", 0xA5A5_0000_0000_0000 | w) for w in range(first, first + n))

    bridge.to_dram(base, block(base, nwords))
    for offset, n in ((0, 1), (1, 1), (5, 3), (1023, 2), (1024, 1024), (nwords - 1, 1), (3000, nwords - 3000)):
        got = bridge.from_dram(base + offset, n)
        want = block(base + offset, n)
        log(f"addressing: {n} words from {base + offset:#x}", got == want, dma.first_difference(got, want) or "")


def neighbours(bridge, rng, base, nwords):
    before, after = rng.randbytes(dma.WORD), rng.randbytes(dma.WORD)
    bridge.to_dram(base - 1, before)
    bridge.to_dram(base + nwords, after)
    bridge.to_dram(base, rng.randbytes(nwords * dma.WORD))
    got = bridge.from_dram(base - 1, 1), bridge.from_dram(base + nwords, 1)
    detail = f"below {got[0].hex()} not {before.hex()}, above {got[1].hex()} not {after.hex()}"
    log(
        f"neighbours of {nwords} words at {base:#x} unchanged",
        got == (before, after),
        "" if got == (before, after) else detail,
    )


def big(bridge, rng, base, mib):
    nwords = mib * (1 << 20) // dma.WORD
    data = rng.randbytes(nwords * dma.WORD)
    t0 = time.monotonic()
    bridge.to_dram(base, data)
    t1 = time.monotonic()
    back = bridge.from_dram(base, nwords)
    t2 = time.monotonic()
    out = {"MiB": mib, "to_dram_MBps": round(len(data) / (t1 - t0) / 1e6, 1),
           "from_dram_MBps": round(len(data) / (t2 - t1) / 1e6, 1)}  # fmt: skip
    rates = f"to DRAM {out['to_dram_MBps']} MB/s, from DRAM {out['from_dram_MBps']} MB/s"
    log(f"big block of {mib} MiB at {base:#x}", back == data, dma.first_difference(back, data) or rates)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--csr", required=True, type=pathlib.Path, help="the running image's csr.json")
    parser.add_argument("--device", default=dma.DEVICE)
    parser.add_argument("--big-mib", type=int, default=64, help="size of the timed block (0: skip it)")
    parser.add_argument("--seed", type=int, default=29)
    parser.add_argument("--dram-timeout", type=float, default=60.0, help="how long to wait for the BIOS's DRAM set-up")
    parser.add_argument("--settle", type=float, default=5.0, help="how long to leave the BIOS memtest after that")
    args = parser.parse_args()
    csrs = check.Csrs(json.loads(args.csr.read_text()), args.csr.name)
    missing = dma.module_missing(args.device)
    if missing:
        sys.exit(f"error: {missing}")
    rng = random.Random(args.seed)
    dram_words = csrs.memories["main_ram"]["size"] // dma.WORD
    report = {"dram_words": dram_words}
    with dma.Bridge(csrs, args.device) as bridge:
        bridge.lock()
        report["ident"] = identifier(bridge, csrs)
        print(f"     running: {report['ident']}", flush=True)
        if not wait_dram(bridge, args.dram_timeout, args.settle):
            print("RESULT: FAIL")
            return 1
        bridge.loopback(False)
        for mode, name in ((dma.MODE_TO_DRAM, "to DRAM"), (dma.MODE_FROM_DRAM, "from DRAM")):
            bridge._start(0, 0, mode)
            log(f"zero-length transfer {name}", bridge["pcie_dram_done"] == 1 and bridge["pcie_dram_count"] == 0,
                f"done {bridge['pcie_dram_done']}, count {bridge['pcie_dram_count']}")  # fmt: skip
        b = dma.BUFFER_WORDS
        for nwords in (1, 2, b - 1, b, b + 1, 512, 5 * b + 7, 64 * b, 64 * b + 1, 70 * b + 3):
            for base in (0, dram_words // 2 + 12345, dram_words - nwords):
                round_trip(bridge, rng, base, nwords)
        addressing(bridge, dram_words // 4 + 7, 8 * b)
        neighbours(bridge, rng, dram_words // 8, 3 * b + 5)
        if args.big_mib:
            report["big"] = big(bridge, rng, dram_words // 2, args.big_mib)
    print(json.dumps(report))
    ok = all(results)
    print(f"RESULT: {'PASS' if ok else 'FAIL'} ({results.count(True)} passed, {results.count(False)} failed)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
