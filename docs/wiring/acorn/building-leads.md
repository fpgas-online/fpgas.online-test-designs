# Leads of the Acorn building guide's pages

The opening of each page of the Acorn building guide on https://docs.fpgas.online, the paragraphs between its
title and the sheets it includes. Each section is one page, named by that page's path under docs/ in
fpgas.online-docs, whose tools/sync_repos.py writes the page from its row there: the title, this section word
for word (without the heading), then the includes. A link to a page of the site is written by its
published address, which the sync turns into a link inside the site.

## boards/acorn/building/compute-blade/bench-check.md

**You have built both cables for an Acorn on a Compute Blade. Before anything is powered, a check on the host with a meter that contact 1 of each plug beeps to the host's metal, and that contact 6 (the 3.3 V wire, cut back) is silent against that metal and the plug's other contacts. It does not show whether any wire reaches the right header pin.**

## boards/acorn/building/compute-blade/bom.md

**You are about to build the two cables for an Acorn on a Compute Blade: tick off every line before you start.**

## boards/acorn/building/compute-blade/fitting.md

**Your two cables for an Acorn on a Compute Blade have passed the bench check, and you are fitting them and the card.**

## boards/acorn/building/compute-blade/index.md

**You have an Acorn and a Compute Blade, and want to build the two cables between them, fit them and check them.** An Acorn on a Raspberry Pi 5 has [its own guide](https://docs.fpgas.online/en/latest/boards/acorn/building/rpi-5/index.html); nothing there is for a Compute Blade.

## boards/acorn/building/compute-blade/jtag-connector-1.md

**You have the parts for an Acorn on a Compute Blade and are making the first of its two cables, from the Acorn's P1 socket (JTAG). On this page: cut the bought cable in half, find wire 1, check it with a meter, cut back the wires that are not used, crimp the rest.**

## boards/acorn/building/compute-blade/jtag-connector-2.md

**You have the P1 cable for an Acorn on a Compute Blade with its wires flagged and crimped, and are putting them into their housing. On this page: which wire goes in which cavity, and a meter check of every wire.**

## boards/acorn/building/compute-blade/uart-connector-1.md

**You have the parts for an Acorn on a Compute Blade and are making the second of its two cables, from the Acorn's P2 socket (the serial port). On this page: find wire 1, check it with a meter, cut back the wires that are not used, solder the resistor into the J2 wire, crimp the rest.**

## boards/acorn/building/compute-blade/uart-connector-2.md

**You have the P2 cable for an Acorn on a Compute Blade with its wires flagged and crimped, and are putting them into their housing. On this page: which wire goes in which cavity, and a meter check of every wire.**

## boards/acorn/building/compute-blade/verifying-1.md

**You have an Acorn on a Compute Blade, its two cables built and fitted, and want to know what the check on the blade says about the wiring. On a Compute Blade today it cannot yet prove the cables: the paragraph "What to expect on a Compute Blade today" below says why.**

Log in to the blade first. At ps1:

## boards/acorn/building/compute-blade/verifying-2.md

**The check of your Acorn on a Compute Blade printed a failing line, and you want to know which wire it means.**

## boards/acorn/building/compute-blade/verifying-2b.md

**The check of your Acorn on a Compute Blade printed a line that is not about one of the cables' wires (the card's image, its memory, the tool itself), and you want to know what it means.**

## boards/acorn/building/compute-blade/verifying-3.md

**Your Compute Blade's check fails at `jtag` although the wiring is right, or you want to know what to expect before you start: what has and has not been run on a blade, and the pin JTAG shares with the serial port.**

## boards/acorn/building/rpi-5/bench-check.md

**You have built both cables for an Acorn on a Raspberry Pi 5. Before anything is powered, a check on the host with a meter that contact 1 of each plug beeps to the host's metal, and that contact 6 (the 3.3 V wire, cut back) is silent against that metal and the plug's other contacts. It does not show whether any wire reaches the right header pin.**

## boards/acorn/building/rpi-5/bom.md

**You are about to build the two cables for an Acorn on a Raspberry Pi 5: tick off every line before you start.**

## boards/acorn/building/rpi-5/fitting.md

**Your two cables for an Acorn on a Raspberry Pi 5 have passed the bench check, and you are fitting them and the card.**

## boards/acorn/building/rpi-5/index.md

**You have an Acorn and a Raspberry Pi 5, and want to build the two cables between them, fit them and check them.** An Acorn on a Compute Blade has [its own guide](https://docs.fpgas.online/en/latest/boards/acorn/building/compute-blade/index.html); nothing there is for a Raspberry Pi 5.

## boards/acorn/building/rpi-5/jtag-connector-1.md

**You have the parts for an Acorn on a Raspberry Pi 5 and are making the first of its two cables, from the Acorn's P1 socket (JTAG). On this page: cut the bought cable in half, find wire 1, check it with a meter, cut back the wires that are not used, crimp the rest.**

## boards/acorn/building/rpi-5/jtag-connector-2.md

**You have the P1 cable for an Acorn on a Raspberry Pi 5 with its wires flagged and crimped, and are putting them into their housing. On this page: which wire goes in which cavity, and a meter check of every wire.**

## boards/acorn/building/rpi-5/uart-connector-1.md

**You have the parts for an Acorn on a Raspberry Pi 5 and are making the second of its two cables, from the Acorn's P2 socket (the serial port). On this page: find wire 1, check it with a meter, cut back the wires that are not used, crimp the rest.**

## boards/acorn/building/rpi-5/uart-connector-2.md

**You have the P2 cable for an Acorn on a Raspberry Pi 5 with its wires flagged and crimped, and are putting them into their housing. On this page: which wire goes in which cavity, and a meter check of every wire.**

## boards/acorn/building/rpi-5/verifying-1.md

**You have an Acorn on a Raspberry Pi 5, its two cables built and fitted, and want to know whether the wiring is right.**

Log in to the Pi 5 first. At welland, the board's page on <https://welland.fpgas.online/fpgas/> shows its ssh command under "Use your own ssh client".

## boards/acorn/building/rpi-5/verifying-2.md

**The check of your Acorn on a Raspberry Pi 5 printed a failing line, and you want to know which wire it means.**

## boards/acorn/building/rpi-5/verifying-2b.md

**The check of your Acorn on a Raspberry Pi 5 printed a line that is not about one of the cables' wires (the card's image, its memory, the tool itself), and you want to know what it means.**

## boards/acorn/packages.md

**You have an Acorn on its host (a Raspberry Pi 5 with an M.2 HAT, or a CM4 or CM5 on a Compute Blade) and
want to install the fpgas.online packages for it, run the check, and identify or verify its flash with the
flash tool (`id` and `verify`; writing the flash is on [Installing and updating the
images](https://docs.fpgas.online/en/latest/boards/acorn/designs/install-images.html)).**

On a Raspberry Pi 5, before the check is run: its `p2-uart` and `p2-serial` tests need the header's serial
port on (`/dev/ttyAMA0`) and the kernel console off it: [the Pi's settings](https://docs.fpgas.online/en/latest/boards/acorn/wiring/rpi-5-host.html#the-serial-port).
