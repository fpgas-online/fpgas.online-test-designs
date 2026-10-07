# fpgas-verify: not done yet

You want to know what the check does not do yet, of what [verify-goals.md](../verify-goals.md) asks for.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## Not done yet

What [verify-goals.md](../verify-goals.md) asks for that the check does not do yet:

* The Arty, NeTV2, Fomu and TT FPGA are checked with the single-function test designs, loaded one at a time,
  not with the full test design.
* `pin-id` checks each Pmod pin in one direction only, FPGA to Pi.
* On an Arty, `pin-id` does not test the six wires on HAT JA pins 2-4 and JB pins 2-4 (they share three Pi
  pins, and the Arty design sends on both at once); its output says so. The TT FPGA's design takes turns there
  and tests all 24 ([#142](https://github.com/fpgas-online/fpgas.online-test-designs/issues/142)).
* What `pin-id` cannot tell on a TT FPGA board: the JA wire and the JB wire of the same number (2, 3 or 4)
  swapped with each other. The HAT joins those two wires on one Pi pin, so the Pi hears the same two pin
  numbers either way. Every other miswiring of the three ribbons changes what some Pi pin hears.
* The Acorn's PCIe transfer rate is not measured, nor the Arty's and NeTV2's DDR and Ethernet bandwidth:
  their `ddr` and `ethernet` tests pass or fail only.
* The Arty's and NeTV2's flash is fingerprinted (a sha256 of its boot image region) and compared only with the
  last run's, not checked against a golden full test design.
* Only the Acorn's flash can be written with its golden images (`fpgas-acorn-flash write`).
* The Arty's and NeTV2's flash IDs are not read, nor the flash IDs of the TT and Fomu; their
  [identity](../identity.md) has only what finding the board, its IDCODE and its device DNA give, and on the
  TT FPGA what rpi-hwid reads.
* Nothing is compared with the site's records.
* rpi-hwid refuses the Arty's and NeTV2's labels until their flash IDs are read; `--identify` exits 1 for
  them meanwhile.
