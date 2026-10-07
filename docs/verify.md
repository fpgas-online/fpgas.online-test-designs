# fpgas-verify: checking an FPGA board from its Raspberry Pi

`fpgas-verify` answers one question per Pi: **is this Pi and its FPGA board ready for users?** It finds the
board, tests the board and its wiring to the Pi, and gives one result, pass or fail, with every fault it found.

* What the tool must do: [verify-goals.md](verify-goals.md). Where this page and that one disagree,
  verify-goals.md says what the tool should do.
* The code: [`verify/`](../verify/). The design notes:
  [plans/2026-09-26-fpgas-online-verify-design.md](plans/2026-09-26-fpgas-online-verify-design.md).
* `verify_hardware.py` ([verify-hardware.md](verify-hardware.md)) is a different tool: a developer's script
  that loads freshly built bitstreams from a workstation over SSH.

This page has two parts:

1. [Using verify as a standalone tool](#1-using-verify-as-a-standalone-tool): installing, running, reading the
   result, and what each board's check tests.
2. [How verify is used in fpgas.online](#2-how-verify-is-used-in-fpgasonline): at every boot of every
   netbooted Pi, the events it sends the site, and the [current results](verify/current-results.md#current-results).

---

## 1. Using verify as a standalone tool

One page for each task, in this order:

| Page | For you if you |
|---|---|
| [Installing](verify/installing.md#installing) | have a Pi with an FPGA board and want to install the check for it |
| [Running it](verify/running.md#running-it) | have installed it and want to run the check, part of it, or set how the host runs it |
| [Identity and labels](verify/identity-and-labels.md#identity-and-labels) | want to print who the board is, or make its labels with rpi-hwid |
| [Reading the result](verify/reading-the-result.md#reading-the-result) | have run the check and want to know what its result and summary mean |
| [More results](verify/more-results.md) | want to compare your summary with more failing and missing results |
| [`--help`](verify/help.md#--help) | want the options and commands of each tool without installing it |
| [What each board's check tests](verify/tests.md#what-each-boards-check-tests) | have an Arty, NeTV2, Fomu or TT FPGA and want to know what each test does |
| [The Tiny Tapeout demo boards](verify/tt-fpga.md) | have a Tiny Tapeout demo board and want to know how it is told apart, what it is left running, its `sdk` test and its identity |
| [What an Acorn check tests](verify/acorn.md#acorn) | have an Acorn and want to know what its check does, and its power-cycle check |
| [The JTAG IDCODE and the device DNA](verify/idcode-and-dna.md) | have an Acorn, Arty or NeTV2 and want to know how its IDCODE and DNA are read and judged |
| [Not done yet](verify/not-done-yet.md#not-done-yet) | want to know what the check does not do yet |
| [Checking an Acorn's wiring](verify/acorn-wiring.md#checking-an-acorns-wiring) | have built an Acorn's cables and want the page that checks them |
| [Common failures](verify/common-failures.md#common-failures) | have a result that is not `pass` and want to know what to do |
| [The report and the recorded state](verify/report-and-state.md#the-report-and-the-recorded-state) | want to read the JSON report, or know when a board is `changed` |

---

## 2. How verify is used in fpgas.online

| Page | For you if you |
|---|---|
| [How it is used in fpgas.online](verify/fleet.md) | run the fleet and want to know how the check is installed and run there, its events, how a deploy reaches it and how to collect every Pi's result |
| [Current results](verify/current-results.md#current-results) | want the last collected results on the Welland Pis |
