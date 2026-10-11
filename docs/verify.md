# fpgas-verify: checking an FPGA board from its Raspberry Pi

**You use fpgas-verify, or look after Pis that run it, and want the page for what you are doing.**

`fpgas-verify` answers one question per Pi: **is this Pi and its FPGA board ready for users?** It finds the
board, tests the board and its wiring to the Pi, and gives one result, pass or fail, with every fault it found.

* What the tool must do: [verify-goals.md](verify-goals.md). Where this page and that one disagree,
  verify-goals.md says what the tool should do.
* The code: [`verify/`](../verify/).
* `verify_hardware.py` ([verify-hardware.md](verify-hardware.md)) is a different tool: a developer's script
  that loads freshly built bitstreams from a workstation over SSH.

This page has two parts:

1. [Using verify as a standalone tool](#using-verify-as-a-standalone-tool): installing, running, reading the
   result, and what each board's check tests.
2. [How the fleet uses verify](#how-the-fleet-uses-verify): at every boot of every
   netbooted Pi, the events it sends the site, and the [current results](verify/current-results.md#current-results).

---

## Using verify as a standalone tool

One page for each task, in this order:

<a id="installing"></a>

* [Installing](verify/installing.md#installing): for you if you have a Pi with an FPGA board and want to install the check for it.

<a id="running-it"></a>

* [Running it](verify/running.md#running-it): for you if you have installed it and want to run the check, part of it, or set how the host runs it.

<a id="identity-and-labels"></a>

* [Identity and labels](verify/identity-and-labels.md#identity-and-labels): for you if you want to print who the board is, or make its labels with rpi-hwid.

<a id="reading-the-result"></a>

* [Reading the result](verify/reading-the-result.md#reading-the-result): for you if you have run the check and want to know what its result and summary mean.

* [More results](verify/more-results.md): for you if you want to compare your summary with more failing and missing results.

<a id="help"></a>

* [`--help`](verify/help.md#the-help-of-each-tool): for you if you want the options and commands of each tool without installing it.

<a id="what-each-board-s-check-tests"></a>

<a id="what-each-boards-check-tests"></a>

<a id="arty-netv2-fomu-and-tt-fpga"></a>

* [What the check tests on each board](verify/tests.md#what-the-check-tests-on-each-board): for you if you have an Arty, NeTV2, Fomu or TT FPGA and want to know what each test does.

<a id="which-tiny-tapeout-board-it-is"></a>

<a id="what-the-tt-fpga-is-left-running"></a>

<a id="the-sdk-test"></a>

<a id="tt-fpga-identity"></a>

* [The Tiny Tapeout demo boards](verify/tt-fpga.md): for you if you have a Tiny Tapeout demo board and want to know how it is told apart, what it is left running, its `sdk` test and its identity.

<a id="acorn"></a>

* [What an Acorn check tests](verify/acorn.md#acorn): for you if you have an Acorn and want to know what its check does.

<a id="the-acorn-s-power-cycle-check-opt-in"></a>

<a id="the-acorns-power-cycle-check-opt-in"></a>

* [The Acorn's power-cycle check](verify/acorn-power-cycle.md#the-acorn-power-cycle-check-opt-in): for you if you have an Acorn and want to know how its opt-in power-cycle check works, and the details of its `ddr` test.

<a id="the-jtag-idcode"></a>

<a id="the-device-dna"></a>

* [The JTAG IDCODE and the device DNA](verify/idcode-and-dna.md): for you if you have an Acorn, Arty or NeTV2 and want to know how its IDCODE and DNA are read and judged.

<a id="not-done-yet"></a>

* [Not done yet](verify/not-done-yet.md#not-done-yet): for you if you want to know what the check does not do yet.

<a id="checking-an-acorn-s-wiring"></a>

<a id="checking-an-acorns-wiring"></a>

* [Checking an Acorn's wiring](verify/acorn-wiring.md#checking-the-wiring-of-an-acorn): for you if you have built an Acorn's cables and want the page that checks them.

<a id="common-failures"></a>

* [Common failures](verify/common-failures.md#common-failures): for you if you have a result that is not `pass` and want to know what to do.

<a id="the-report-and-the-recorded-state"></a>

* [The report and the recorded state](verify/report-and-state.md#the-report-and-the-recorded-state): for you if you want to read the JSON report, or know when a board is `changed`.

---

## How the fleet uses verify

<a id="events"></a>

<a id="how-a-deploy-picks-up-new-packages"></a>

<a id="collecting-every-pi-s-result"></a>

<a id="collecting-every-pis-result"></a>

* [How it is used in fpgas.online](verify/fleet.md): for you if you run the fleet and want to know how the check is installed and run there, its events, how a deploy reaches it and how to collect every Pi's result.

<a id="current-results"></a>

* [Current results](verify/current-results.md#current-results): for you if you want the last collected results of the fleet's Pis.
