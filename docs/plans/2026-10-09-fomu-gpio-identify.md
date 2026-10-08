# Fomu EVT: identified over the Pi's GPIO header (#200)

**Status: PLAN, then code.** The plan is written here before coding, as asked. The facts are from the EVT schematic (read only), upstream fomu-flash and foboot (read only), and one read-only look at the Fomu host at welland on 9 Oct 09:00 ACDT, which the coordinator granted. That look ran no sudo, set no pin and opened no device.

## The problem (#200)

`verify/src/fpgas_online_verify/boards/fomu.py` finds the Fomu only by foboot's DFU bootloader on USB (`1209:5bf0`). At the 8 Oct 11:36 boot of the Fomu host at welland (Pi 3B+ 00000000cc479fd1), USB carried an OpenVizsla OV3 (`1d50:607c`, serial OV100662) and no foboot. The check said "none of the installed boards (fomu) was found", although the Fomu EVT was on the Pi's header the whole time (Tim, 9 Oct: "The Fomu evt is 100% still plugged and you should be able to query it via the RPi GPIO pins").

## How the EVT sits on the Pi's header

The EVT is the "stretch" Fomu PCB with a Raspberry Pi header. Upstream `im-tomu/fomu-flash` (`fomu-flash.c`, read only) drives it from the Pi with these BCM pins:

| Signal | BCM GPIO | What it is on the EVT |
|---|---|---|
| CRESET_B | 27 (21 on a rev-1 Pi) | iCE40 reset; low holds the FPGA in reset with its SPI pins released |
| CDONE | 17 | iCE40 configuration done (high = a design is running) |
| SPI CS | 8 (CE0) | flash CS, shared with the iCE40's SPI_SS |
| SPI MOSI / MISO / CLK | 10 / 9 / 11 | flash DI / DO / CLK, shared with the iCE40's config SPI |
| WP / HOLD (IO2 / IO3) | 24 / 25 | flash quad pins |
| UART | 14 / 15 | the iCE40's serial (pins 21 RX / 13 TX in LiteX's platform) |

Confirmed against the EVT schematic (`im-tomu/fomu-hardware`, branch `evt`, `hardware/pcb/tomu-fpga.sch`: J1 "Raspberry Pi Hat"):
- The table above holds.
- The flash is U4, a Winbond W25Q128JV-IM ("SPI Flash - W25Q128JVSIM"), JEDEC ID `ef 70 18`.
- The six `dbg` pins of LiteX's platform go to BCM 2, 3, 4, 18, 22 and 7.
- The schematic's note: "To program SPI flash, put FPGA in RESET".
- CRESET is also on the board's reset button.

Seen on the Fomu host at welland (Pi 3B+ 00000000cc479fd1; 10.21.1.17 at 9 Oct 09:00):
- GPIO17 (CDONE) is an input reading **hi**: an iCE40 is configured on the header now, with no foboot on USB. Only the OV3 `1d50:607c` is on USB.
- GPIO27 (CRESET) and GPIO 8-11, 24, 25 are inputs reading hi.
- There is no `/dev/spidev*`, and neither `spi_bcm2835` nor `spidev` is loaded.

So the board is there and running a design, and the check could not see it.

A side finding: the "confirmed loopback pair GPIO27 → GPIO9" in `docs/hardware/fomu-pin-mapping.md` cannot be a loopback on this board. On it, GPIO27 is the iCE40's CRESET (a dedicated input) and GPIO9 the flash's MISO, and no net joins them. The Fomu's `pmod` and `pin-id` tests assume the PMOD HAT, which an EVT on the header is not. The docs say so here; the tests are left for a follow-up issue.

## The design

### 1. Identification over GPIO (the gate)

The host script `designs/_host/fomu_header_id.py` reads the Fomu through the header, in this order, under the board's lock:

1. Take GPIO 8-11, 17, 24, 25 and 27 as inputs.
2. Read CDONE (GPIO17): this is the passive sighting.
3. Drive CRESET (GPIO27) low, then read CDONE again. It must now be low; that proves an iCE40's reset is wired to GPIO27.
4. With the FPGA in reset, the Pi is the only master on the flash's SPI bus. It sends these commands, all reads or volatile:
   - `0xAB`: release from deep power-down.
   - `0x66 0x99`: reset-enable and reset. This leaves QPI or continuous-read modes a user design may have set, and writes no flash cell.
   - `0x9F`: JEDEC ID (RDID, 3 bytes).
   - `0x4B`: the 64-bit unique ID (W25Q128JV: 4 dummy bytes, then 8 bytes).
   - Status registers 1 to 3 (`0x05`, `0x35`, `0x15`).

   No erase, program, write-enable or write-status opcode is ever sent. The opcode set is a frozen allow-list in the module, and a unit test fails if any other opcode appears.
5. Put the SPI pins back as found, before the reset is released, so the iCE40 can master its flash to boot.
6. Release CRESET (back to its saved state, an input). The iCE40 then boots from its flash exactly as at power-up, into foboot.
7. Wait (bounded, 10 s) for CDONE high, and for foboot's `1209:5bf0` on USB.

The result is `{"variant": "evt", "flash_jedec", "flash_uid", "flash_uid_opcode": "0x4b", "flash_uid_bits": 64, "flash_status", "cdone": {...}, "usb_dfu": present/absent}`. These fields are identity fields that rpi-hwid already has (`identity.FIELDS`).

What passes and what fails:

| Outcome | Result |
|---|---|
| CDONE does not fall while CRESET is held | the check fails: "no iCE40 on the header's CRESET/CDONE" |
| A JEDEC ID of all 0x00 or all 0xff | the check fails: no flash answering |
| A unique ID of all 0x00 or all 0xff | the check fails |
| A JEDEC ID that is not the EVT's W25Q128JV (`ef 70 18`) | the check fails, naming what it read |
| A pin that cannot be read or put back | an error (as for the NeTV2's JTAG pins) |
| foboot absent on USB after the reset | **not** a fail of identification: it is said in the report ("foboot did not appear on USB after the reset"). The uart test that needs DFU fails with that reason. |

**Where it runs.**
Holding CRESET low stops whatever design a visitor loaded. So the reset runs only in the check: the boot check, at boot, before the board is offered, or an admin's `fpgas-fomu-verify`, which loads designs anyway. Finding the board never resets it, and neither does `--identify`.

- `Fomu.probes = True`, and `probe(host)` only reads CDONE (GPIO17) with `pinctrl get`, driving nothing. High means an iCE40 on the header has loaded a design, so a Fomu with no foboot on USB is found. That covers the 8 Oct case: an OV3 analysing, or a user design running.
- `spot()` keeps the USB sighting of foboot. It drives nothing either, and `auto` uses it first.
- In `check()`, the GPIO identification runs every time as `port_facts`, before any test. So the Fomu's identity always comes from its own flash, never from USB alone. A Fomu found on USB whose header does not answer fails the `header` test.
- **The safe state afterwards.** Every line the script took (GPIO 8-11, 17, 24, 25, 27) is an input again before it exits, whatever went wrong, as the TT board's safe state does. The SPI lines are inputs before CRESET is let go, and CRESET becomes an input that the board's pull-up takes high. The board module then reads those lines with `pinctrl get`: one that is not an input makes the check an error. Tests cover each part:
  - the script against a model of the EVT: the order, an exception mid-read, no ice40 on the reset, and no line driven while the iCE40 owns the bus;
  - the module, with a line left driven.
- The reset also brings foboot back for the DFU load. A Fomu that an earlier check left running its test design (#135) is now found by its CDONE and checked without a power cycle. `gone_after_check` and its advice are removed, since the Fomu was their only user. The runner tests for them are replaced by tests that name the OV3.

**`--identify`** must not disturb the board (`Board.identify`: "nothing reconfigured"). The reset reconfigures the FPGA, so `--identify` reads only CDONE and USB, and takes `flash_jedec` and `flash_uid` from the boot report (`report_fields`), as the Arty and NeTV2 already do for the flash. The Fomu has no board-unique key to match the report by: no USB serial, DNA or PCI slot. So a new `Board.one_per_host`, true for the Fomu, lets `--identify` take the one Fomu in the report. It sits on the Pi's own header, and changing it means powering the Pi off, which runs the boot check again. This came from the review.

**Label.** The `label_fields` change from `serial` to `flash_uid`. foboot has no USB serial number at all: `sw/src/usb-desc.c` gives `iSerialNumber` 0, and its README's log shows `SerialNumber=0`. So the Fomu's label had no value, and the flash's 64-bit unique ID is the board's own identifier.

**How the SPI is driven.** The host has no spidev, so a new host script, `designs/_host/fomu_header_id.py`, bit-bangs SPI mode 0 through python3-libgpiod. That is v2, with v1.6 as `tt_pmod_wiring.py` has it, and it is already a dependency of the Arty and TT tools and of the Fomu's debug package. The script:
- holds CRESET low;
- reads the flash;
- sets every line it drove back to an input **before** CRESET is let go, so the iCE40 masters its flash alone when it boots;
- prints one JSON line.

The board module runs it as the other host scripts are run, then checks with `pinctrl get` that every line it took is an input. WP is held low while the Pi has the bus (status-register writes blocked), and HOLD high.

### 2. The OpenVizsla OV3 as a debug tool

A board module can name USB debug tools: `Board.debug_usb = {(vendor, product): name}`. The Fomu's names `1d50:607c` as "OpenVizsla OV3". The runner then works as follows:
- It lists every such device seen on USB in the report as `usb_debug_tools`, for example "OpenVizsla OV3 OV100662 on USB, a debug tool, not a board".
- A "missing" reason ends with that sentence too, so an OV3 is never read as "no board".
- An OV3 is never taken as a board, and never fails a check.

### 3. The hardware pages

- `docs/hardware/fomu-evt.md`: how the check finds and identifies the Fomu (GPIO first, foboot on USB as information); the header table above; and that an OpenVizsla OV3 may sit inline on its USB to debug the Fomu's USB stack.
- `docs/hardware/fomu-pin-mapping.md`: the header table, which replaces the TODO about the header mapping; the GPIO27/GPIO9 note; the OV3; and corrections to the hosts (this page names "pi17/pi21" by port and an analyser on "pi21" that the site does not have now; it will name the Fomu host by its Pi serial instead).
- `docs/verify/common-failures.md`: the new reasons.

### Tests (CI, no hardware)

`tests/test_fomu_header_id.py` uses a model of the EVT: CRESET pulls CDONE low, and the flash answers 9F and 4B. It covers:
- the order: pins saved, then reset, then reads, then the SPI pins put back before CRESET is released;
- the opcode allow-list, so no write opcode can be sent;
- each fail row of the table above;
- that a pin which cannot be put back is an error.

`tests/test_verify_runner.py` will cover:
- a Fomu found by probing with no USB;
- the OV3 named in the missing reason and in the report;
- the #135 test rewritten.

`tests/test_verify_boards.py` will cover the Fomu's `label_fields` and `report_fields`.

### Follow-up

[#202](https://github.com/fpgas-online/fpgas.online-test-designs/issues/202) covers the docs' "GPIO27 → GPIO9 loopback" (CRESET → flash MISO on the EVT) and the Fomu `pmod`/`pin-id` tests, which assume a PMOD HAT. This PR corrects the docs only.

### Not in this PR

The iCE40 can be loaded over the same header in SPI-slave mode: CRESET is pulled with SS held low, as `fomu-flash -f` does. That loads into SRAM only, never writes the flash and needs no USB. It would end the DFU load's rewrite of the user image at every verify. It needs bit-banged SPI with MOSI/MISO swapped.

### Run on the real Fomu host (9 Oct 2026, 09:18 ACDT, the coordinator's grant)

`fomu_header_id.py` from head f756e96 (sha256 `1b471e90…ae664`) ran once as pi, without sudo, on the Pi 3B+ 00000000cc479fd1 (python3-libgpiod 1.6.3, the v1 path). The script was copied to the Pi's home and removed after. It printed:

```
fomu-header: {"boot_seconds": 0.071, "cdone_after": 1, "cdone_before": 1, "cdone_in_reset": 0, "creset_before": 1, "flash": {"busy_after_wait": false, "busy_at_reset": false, "jedec": "ef7018", "status": ["00", "02", "60"], "uid": "e467286593241321"}}
```

- Before the run: all eight lines were inputs, CDONE was high, and only the OV3 was on USB.
- During the run: CDONE fell in reset; the flash is the EVT's W25Q128JV, unique ID `e467286593241321`; the iCE40 booted from its flash again in 71 ms.
- After the run: all eight lines were inputs.
- 10 s later, foboot (`1209:5bf0`, "Generic Fomu EVT running DFU Bootloader v2.0.4") was back on USB beside the OV3.

Records: `scratch/data/welland/fomu-200/02-*`.

### Running on the real Fomu host

Nothing is run on the Fomu host at welland without the coordinator's grant. The first run will be `sudo fpgas-fomu-verify --no-publish --report -` with this branch's package, asked for with its exact command. It resets the FPGA (as a power cycle does) and writes nothing to the flash.

