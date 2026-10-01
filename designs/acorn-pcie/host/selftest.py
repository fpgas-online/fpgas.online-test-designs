#!/usr/bin/env python3
"""Exercise the Acorn SoC's DRAM BIST and every P2 pin, over PCIe BAR0, on the Pi the board is wired to.

Needs the operational image of a release that has the BIST and the P2 switch (csr.json lists `dram_generator`,
`dram_checker` and `p2_serial`), no kernel driver bound to the board, and `pinctrl` (raspi-utils) for the Pi's
side of the P2 pins. Run as root:

    sudo python3 selftest.py --csr acorn-cle-215p-csr.json [--bdf 0001:01:00.0] [--uart /dev/ttyAMA0]
        [--carrier pi5|blade]

The work is done by fpgas_online_verify.boards.acorn.bist, the same code the boot check (fpgas-verify's `ddr`,
`p2-serial` and `p2-gpio` tests) runs, so the two cannot drift apart. It comes from the installed
fpgas-online-acorn-tools package or, run from a checkout, from verify/src. Which Pi GPIO each P2 ball and
JTAG signal reaches comes from docs/wiring/acorn/wiring.toml, through the same package.

0. The BIOS console (the crossover UART) is read out over BAR0 first. The BIOS sets the DRAM up after its
   banner, and with this LiteX it stops when its console fills and nobody reads it (PR #47), so on a
   board nobody has attached to, reading it is what lets DRAM initialisation finish.
1. DRAM: two passes over the whole DRAM, each split into a low and a high half, both halves written before
   either is checked, with different data, swapped in the second pass (bist.dram()).
2. P2: each P2 ball the carrier wires to the Pi, in both directions (bist.balls()). J2/K2 are borrowed from
   the UART with `p2_serial`; J5/H5 are `p2_gpio`. Balls the carrier does not wire are skipped (on the
   Compute Blade, J5/H5), and no ball is driven on the Pi's TDI, TDO or TCK.
3. The switch's own timeout: switch to GPIO with a 200 ms timeout and see it come back to serial alone.
4. With `--uart`: the UARTBone answers on P2 afterwards, with the identifier BAR0 reads.

Every Pi pin is put back exactly as it was, and the switch is back on serial, even when a step fails. If the
script is killed while the pins are GPIOs, the switch goes back to serial by itself after
bist.SWITCH_TIMEOUT_MS. Prints one line per check and exits 1 if any failed.
"""

import argparse
import json
import pathlib
import sys

# Run from a checkout, the checkout's own code, before any older fpgas-online-acorn-tools installed on the Pi;
# otherwise the installed package.
CHECKOUT = pathlib.Path(__file__).resolve().parents[3] / "verify" / "src"
if (CHECKOUT / "fpgas_online_verify").is_dir():
    sys.path.insert(0, str(CHECKOUT))

from fpgas_online_verify.boards.acorn import bist, check, setup, spi_flash  # noqa: E402  -- after sys.path
from fpgas_online_verify.core import pi_model, run  # noqa: E402

results = []


def log(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}", flush=True)
    return ok


def carrier(name=None):
    """The setup (wiring.toml carrier) by its key, or this host's from its device-tree model."""
    if name is None:
        return setup.detect(pi_model())
    wiring = setup.load(setup.WIRING)
    model, _ = setup.setups(wiring)[name][0]
    return setup.detect(model, wiring)


def dram(regs, length=None):
    out = bist.dram(regs, length, log=log)
    faults = out.pop("faults")
    log("dram bist", not faults and out["errors"] == 0,
        f"{out['bytes'] >> 20} MiB x 2 passes, {out['errors']} errors, "
        f"write {out.get('write_MBps')} MB/s, read {out.get('read_MBps')} MB/s")  # fmt: skip
    return out


def p2(regs, host):
    jtag = dict(zip(("TDI", "TDO", "TCK", "TMS"), host.jtag_gpios))
    for module, wired_here in (("p2_serial", host.p2_serial), ("p2_gpio", host.p2_gpio)):
        wired, skipped = bist.testable(wired_here, jtag)
        for ball, why in skipped.items():
            print(f"     {ball}: not driven, {why}", flush=True)
        if not wired:
            continue
        if module == "p2_serial":
            with bist.borrowed_serial(regs):
                log("p2_serial switched to GPIO", regs["p2_serial_mode"] == 1)
                faults, _ = bist.balls(regs, module, wired, run, log=log)
            log("p2_serial back on serial", regs["p2_serial_mode"] == 0)
        else:
            faults, _ = bist.balls(regs, module, wired, run, log=log)
        for fault in faults:
            if "drove" not in fault:
                log("Pi pins put back", False, fault)
    for ball in bist.FPGA_SIDE:
        if ball not in host.p2_serial and ball not in host.p2_gpio:
            print(f"     {ball}: not wired on the {host.name} setup (wiring.toml)", flush=True)
    log("p2_serial returns to serial by itself", *bist.switch_times_out(regs))


def uart(port, ident):
    from fpgas_online_verify.boards.acorn import uartbone_link

    link = uartbone_link.UARTBoneLink(uartbone_link._serial_opener(port))
    try:
        link.connect()
        got = link.ident()
    finally:
        link.close()
    log("UARTBone on P2 answers after the switch", got == ident, repr(got))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--csr", required=True, type=pathlib.Path, help="the running image's csr.json")
    parser.add_argument("--bdf", default="0001:01:00.0")
    parser.add_argument("--uart", metavar="PORT", help="also check the UARTBone on PORT afterwards")
    parser.add_argument("--carrier", choices=sorted(setup.setups()), help="default: from /proc/device-tree/model")
    parser.add_argument("--dram-bytes", type=lambda s: int(s, 0), help="test this much DRAM (default: all of it)")
    parser.add_argument("--skip-console", action="store_true", help="do not read the BIOS console first")
    parser.add_argument("--skip-dram", action="store_true")
    parser.add_argument("--skip-p2", action="store_true")
    args = parser.parse_args()
    csrs = check.Csrs(json.loads(args.csr.read_text()), args.csr.name)
    host = carrier(args.carrier)
    driver = spi_flash.bound_driver(args.bdf)
    if driver:
        sys.exit(f"error: {driver} is bound to {args.bdf}; unbind it first")

    report = {"carrier": host.key}
    with spi_flash.open_bar0(args.bdf) as bus:
        regs = bist.Regs(bus.read, bus.write, csrs)
        ident = check.read_identifier(bus)
        print(f"     running: {ident} (carrier {host.key})", flush=True)
        report["ident"] = ident
        if not args.skip_console:
            console = bist.console(regs)
            print("     BIOS console:\n" + "\n".join("       " + line for line in console.splitlines()), flush=True)
        if not args.skip_dram:
            report["dram"] = dram(regs, args.dram_bytes)
        if not args.skip_p2:
            p2(regs, host)
    if args.uart:
        uart(args.uart, ident)
    print(json.dumps(report))
    ok = all(results)
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
