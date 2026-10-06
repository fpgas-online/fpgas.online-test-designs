What has been run on a Compute Blade, and what has not, as of 5 October 2026:

| | State |
|---|---|
| Installing the packages and running the check (Raspberry Pi OS trixie, CM5) | run at ps1: the failing run printed on the page "verifying 1" is that host's result, taken with 0.0.post1100, before the check named the pin's holder |
| `pcie-link` | run at ps1: passes (5.0 GT/s, x1) |
| `jtag` with the serial port on, kernel 6.18 | run at ps1: **cannot work**. TMS is GPIO14, which is also the serial port's TX; that kernel does not lend a pin a driver has, and the serial driver cannot be detached while the system runs. From 0.0.post1111 the test fails saying so, without running the tool ([#127](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)) |
| `jtag` with the serial port off | **not yet run by us on this hardware** |
| `jtag` under kernel 6.12, serial port on | recorded as working on one ps1 blade (`--pins 2:3:4:14`), before these packages existed; not run with them |
| The `p2-uart` and `p2-serial` tests | **not yet run by us on this hardware**: they need a converted card |
| Converting a card on a Compute Blade | **not yet run by us on this hardware**; the [written steps](hardware/acorn-pcie-programming.md) are for the Pi 5 setup |
| A Compute Blade that passes the whole check | **not yet seen** |
| The `p2-serial` test on a blade whose J2 wire has no 470 Ω resistor (pi20 at ps1 as wired on 5 October 2026: the pair on Extension Port pins 9 and 10) | **not yet run by us on this hardware**. From the code: while it runs to its end or raises an error, the test never has both ends of a wire driving at once (the Pi's pins are made inputs before the FPGA drives, and the FPGA's outputs are switched off before the Pi drives), so it does not rely on the resistor. What the resistor guards against is a design that drives J2 while JTAG or the serial port drives GPIO14; the fpgas.online design leaves J2 an input except while the host has switched J2/K2 to GPIO mode and enabled J2's output, which is what this test does, with the Pi's GPIO14 an input at that moment |

JTAG and the serial pair share GPIO14 on a Compute Blade (J2 reaches it through 470 Ω, so JTAG wins
electrically). Under kernel 6.18 they cannot both be had from one boot: with the header's serial port on, the
kernel keeps GPIO14 for it. The configuration we expect to work for JTAG, and with it for converting a card,
is the header's serial port off at boot. **Not yet run by us on this hardware**, and Raspberry Pi's
documentation does not say that it frees GPIO14 on a Compute Module 5:

* in `config.txt`, the line `enable_uart=0`, written out (Raspberry Pi's documentation gives the default as 1
  when the primary serial port is a PL011; we have not seen it left unset on a Compute Blade); and if the
  port is switched on by a `dtoverlay=uart0…` or `dtparam=uart0` line, that line has to go instead;
* in `cmdline.txt`, the word `console=serial0,115200` deleted from the one line, if it is there.

**These two files are not on the blade, and the change is not yours to make from the blade.** At ps1 every
netbooted host fetches them from one directory on the gateway, `/srv/nfs/rpi/trixie/boot/`: the gateway's TFTP
root has one entry for each host's serial number, and every one of them points at that same directory (read on
the ps1 gateway, 6 October 2026). So one `config.txt` and one `cmdline.txt` serve every host that boots from it,
and a change there reaches all of them at their next boot. The gateway belongs to whoever runs the site (at ps1: Carl), and the change is theirs to make. The blades' root file
system is the gateway's `/srv/nfs/rpi/trixie/root` (read from the kernel command line of pi16 and pi20 at ps1,
5 October 2026).

Then check that the pin is free (the commands below) before trying JTAG. With the serial port off, `/dev/ttyAMA0` is not there, so the
`p2-uart`, `p2-serial` and `scratch` tests cannot pass in that boot; what a Compute Blade's check should
count as its result in each of the two configurations is not settled.

To see who has the JTAG pins on a host, without running anything on the card:

```bash
pinctrl get 2,3,4,14,15     # the function each pin is switched to
gpiodetect                  # the header's chip: `pinctrl-rp1` on a CM5, `pinctrl-bcm2711` on a CM4
gpioinfo -c gpiochip0 | grep -E 'line +(2|3|4|14):'   # with that chip's name (gpiod 2; gpiod 1: `gpioinfo gpiochip0`)
# a line shown with a consumer (`consumer="kernel"`) or `[used]` is one the kernel will not hand out
```
