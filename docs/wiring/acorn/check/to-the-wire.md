| The failing line | Look at |
|---|---|
| `pcie-link fail: link is x2, expected x1` (or a speed) | the M.2 seat; or the setup's expected figures are not this host's |
| `jtag fail: no device on the P1 JTAG chain` | the P1 cable is not plugged in, or TCK, TMS or TDO is open or on the wrong pin |
| `jtag fail: P1 JTAG chain has …, expected one …` | another device answers, or the card is not the variant the host expects |
| `jtag fail: device DNA over P1 JTAG reads 0x0: the DNA port is not being read` (or `reads 0x1ffffffffffffff`), `openFPGALoader --read-dna read no device DNA over P1 JTAG`, or `device DNA over JTAG … is not the one over BAR0 …` | TDI: the IDCODE read worked without it |
<!-- blade -->| `jtag fail: … GPIO14 (TMS) is held by … (uart0): the kernel does not hand out a pin that is held …` | not a wire: the serial port holds GPIO14, which is also TMS, so JTAG cannot run in a boot that has the header's serial port on (kernel 6.18). [How to make a Compute Blade boot ready for JTAG](https://docs.fpgas.online/en/latest/boards/acorn/checks/compute-blade-jtag.html) gives a boot with that port off |
| `p2-uart fail: no UARTBone reply on /dev/ttyAMA0 (P2 K2/J2)` | the serial pair: open, or crossed; `p2-serial` says which |
| `p2-serial fail: J2 -> GPIO14: the FPGA drove 1, the Pi read 0; K2 -> GPIO15: the FPGA drove 0, the Pi read 1; …` with the `01` and `10` lines swapped and `00` and `11` right | J2 and K2 are **crossed**: {crossed_serial} |
<!-- pi5 -->| `p2-serial` or `p2-gpio` naming one of its two signals only (J2 or K2; J5 or H5) | that one wire is **open**, or on the wrong pin. Before the FPGA drives, the test sets the Pi's pull against the level to come, so an open wire reads the opposite of what was driven; GPIO3 (J5's pin) has a pull-up of its own on the Pi, so an open J5 wire reads 1 whatever is driven |
<!-- blade -->| `p2-serial` naming one of its two signals only (J2 or K2) | that one wire is **open**, or on the wrong pin. Before the FPGA drives, the test sets the host's pull against the level to come, so an open wire reads the opposite of what was driven. When you then check the J2 wire with a meter, set it to ohms: a good J2 wire reads close to 470 Ω end to end, and a continuity buzzer usually stays silent through that |
<!-- pi5 -->| `p2-gpio fail: J5 -> GPIO3: …; H5 -> GPIO4: …` with the `01` and `10` lines swapped and `00` and `11` right | J5 and H5 are **crossed**: {crossed_spare} |

<!-- pi5 -->`p2-serial` and `p2-gpio` print what was driven and what was read, eight lines for two wires. The two digits are the two signals: the right-hand digit is J2 (or J5), the left-hand one K2 (or H5).
<!-- blade -->`p2-serial` prints what was driven and what was read, eight lines for two wires. The two digits are the two signals: the right-hand digit is J2, the left-hand one K2.

<!-- pi5:begin -->
**A crossed pair.** The `p2-serial` test
drives each wire as a plain pin, first from the FPGA and then from the host. The line `FPGA drives 01` raises J2, which
should arrive on GPIO14; J2 arrives on GPIO15:

```text
    p2-serial  fail: J2 -> GPIO14: the FPGA drove 1, the Pi read 0; K2 -> GPIO15: the FPGA drove 0, the Pi read 1; J2 -> GPIO14: the FPGA drove 0, the Pi read 1; K2 -> GPIO15: the FPGA drove 1, the Pi read 0; GPIO14 -> J2: the Pi drove 1, the FPGA read 0; GPIO15 -> K2: the Pi drove 0, the FPGA read 1; GPIO14 -> J2: the Pi drove 0, the FPGA read 1; GPIO15 -> K2: the Pi drove 1, the FPGA read 0; the UARTBone does not answer on /dev/ttyAMA0 after the switch (no fpgas.online SoC answered at 1200 baud after a break)
        FPGA drives 00: Pi reads GPIO14=0 GPIO15=0
        FPGA drives 01: Pi reads GPIO14=0 GPIO15=1
        FPGA drives 10: Pi reads GPIO14=1 GPIO15=0
        FPGA drives 11: Pi reads GPIO14=1 GPIO15=1
        Pi drives 00: FPGA reads 00
        Pi drives 01: FPGA reads 10
        Pi drives 10: FPGA reads 01
        Pi drives 11: FPGA reads 11
```

**One open wire**, a J5 wire that does not reach GPIO3. GPIO3
reads 1 whatever the FPGA drives. The Pi's own pull-up on GPIO3 wins over the test's pull-down. On GPIO4 an
open wire would read the opposite of what was driven. On this card the FPGA read J5 as 1 whatever the Pi
drove, and H5 and GPIO4 follow each other:

```text
    p2-gpio    fail: J5 -> GPIO3: the FPGA drove 0, the Pi read 1; J5 -> GPIO3: the FPGA drove 0, the Pi read 1; GPIO3 -> J5: the Pi drove 0, the FPGA read 1; GPIO3 -> J5: the Pi drove 0, the FPGA read 1
        FPGA drives 00: Pi reads GPIO3=1 GPIO4=0
        FPGA drives 01: Pi reads GPIO3=1 GPIO4=0
        FPGA drives 10: Pi reads GPIO3=1 GPIO4=1
        FPGA drives 11: Pi reads GPIO3=1 GPIO4=1
        Pi drives 00: FPGA reads 01
        Pi drives 01: FPGA reads 01
        Pi drives 10: FPGA reads 11
        Pi drives 11: FPGA reads 11
```

<!-- pi5:end -->
A correctly wired pair reads back what was driven: `FPGA drives 01: Pi reads GPIO14=1 GPIO15=0`, `Pi drives 01:
FPGA reads 01`, and so on for every pattern.

