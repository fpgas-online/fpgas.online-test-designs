# fpgas-verify: the Acorn's power-cycle check, and the details of its tests

You have an Acorn and want to know how its opt-in power-cycle check works, or the details of its tests: the
`ddr` test step by step, `not_run`, the driver it unbinds and the pins it puts back.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## The Acorn's power-cycle check (opt-in)

A board is to be tested as its flash configures it. If the FPGA kept its configuration while its Pi restarted
(the card fed from somewhere else, a restart that does not reach the card), it still holds whatever was in it
before, a visitor's design included. With `power-cycle-check = on` the board fails in that case:

```text
power-cycle fail: the FPGA has not restarted since an earlier boot's check (scratch is 0x…, neither its
value after configuration nor this boot's marker): it did not restart with the Pi. Power-cycle the Pi
```

How it tells, on the SoC the boards run (it has no uptime counter): the `ctrl` scratch register holds
`0x12345678` after configuration and only a write changes it. When the `power-cycle` test has passed, the check
ends by leaving a marker there, 32 bits of a hash of the kernel's boot id. At the next check:

| Scratch holds | Means | Result |
|---|---|---|
| `0x12345678` | the FPGA was configured, or its SoC reset, since the last check | pass |
| this boot's marker | the check already ran in this boot (an operator running it again) | pass |
| anything else | the card kept its configuration across the Pi's restart, or something else wrote the register | fail |

A board that fails is left as it was found, so it fails again until the card restarts (a power cycle does it).
`--test scratch` on its own leaves no marker; `--test power-cycle`, when it passes, does leave it. The report says when the check was on: `"power_cycle_check": {"on": true, "configured_by":
"/etc/fpgas-verify/…ini"}`.

**What a restart of the Pi does to the card depends on the setup, so the check is opt-in.** Measured on
5 Oct 2026 on a Pi 5 with the PCIe HAT (the Acorn with DNA `0x0054b48664b04854`): after a plain `systemctl
reboot` the scratch register read `0x12345678` again and the check passed, and the same after a PoE power cycle.
That is one board; whether the soft reboot reloads the FPGA from its flash or only resets the SoC was not
established, and the Compute Module setup has not been measured. Where a restart of the Pi does not reach the
card, every board fails after a restart, so switch the check on only for a setup that has been measured. Outside the fleet nothing says how a host is restarted, which is why it is off by default.

Two limits. A reset of the SoC (a write to `ctrl_reset`) also returns the register to `0x12345678`, and the
check cannot tell that from configuration. And anyone with root on the Pi can write the register; the check is
there to catch a card that did not restart with its Pi, not a visitor who sets out to hide it.

`fpgas-verify --test power-cycle` runs it alone, when the setting is on; with the setting off it is an error
that says how to switch it on.

## The Acorn's tests in detail

* `ddr` in detail ([`bist.py`](../../verify/src/fpgas_online_verify/boards/acorn/bist.py), the same code
  [`selftest.py`](../../designs/acorn-pcie/host/selftest.py) runs):
  1. The BIOS console is read until it has been quiet for 2 s. In the installed release
     (`vivado-bitstreams-acorn-pcie-20261001-ge568a408e7bd`, built from e568a40, which does not have
     [#47](https://github.com/fpgas-online/fpgas.online-test-designs/pull/47)) the BIOS stops while its
     console is full and unread, so reading it lets it finish setting up the DRAM. A build with #47 never
     waits for a reader. The BIOS's memtest line, when still there, is reported as `bios_memtest`.
  2. Two passes over the whole DRAM, in a low and a high half, each written before either is checked, with
     different data in each; the second pass swaps them. A dead top address bit, or half the expected DRAM,
     fails.
  3. Measurements: `bytes`, `passes`, `errors`, `write_MBps`, `read_MBps`, `seconds`.
* The golden image has no DRAM, no P2 switch and no spare GPIO: on it `ddr`, `p2-serial` and `p2-gpio` are
  in `not_run`, and the board fails for running golden.
* A test that cannot run because of an earlier fault is in the report's `not_run`, with why.
* A run in which none of the tests asked for ran (`--test p2-gpio` on a Compute Blade, say) fails.
* A kernel driver bound to the board (`litepcie.ko`) is unbound while a test that uses BAR0 runs, and bound
  again after. The events of those tests are held and sent once it is bound again.
* Every Pi pin a test drives is put back as it was found (function, pull, and an output's level); the FPGA's
  side is left as inputs. On a Compute Blade GPIO14 is both TMS and the UART's TX, and goes back to its UART
  function.
* Before the JTAG tool runs, the check asks the header's GPIO chip whether each JTAG pin can be had. A kernel
  whose pin controller is strict (the RP1's on 6.18, seen on a CM5) does not lend a pin a driver has: on a
  Compute Blade with the serial port on, that is GPIO14. The tool is then not run and `jtag` fails, naming the
  pin and who has it ([#127](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)). Which
  boot configuration a Compute Blade needs for both JTAG and the P2 UART is not settled.
