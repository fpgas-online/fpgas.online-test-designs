# fpgas-verify: running it

You have installed `fpgas-verify` and want to run the check, or part of it, and set how the host runs it.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## Running it

### What you need

- the packages for your board installed ([Installing](installing.md#installing))
- `sudo` on the host

### Steps

**1.** Run the check. Nothing is sent to the site: `--no-publish` makes sure.

```bash
sudo fpgas-verify --no-publish
```

**2.** To run one test on its own, name it: the names are in [What the check tests on each board](tests.md#what-the-check-tests-on-each-board)
and, for an Acorn, [What an Acorn check tests](acorn.md#acorn). The report then goes to stdout.

```bash
sudo fpgas-verify --no-publish --test TEST
```

### Check

The summary, on stderr, starts with `fpgas-verify: pass`. The board's line under it ends in `pass`, and
so does the line of each test that ran.

### If it fails

- [Reading the result](reading-the-result.md#reading-the-result) says what each result and each line mean.
- [Common failures](common-failures.md#common-failures) lists the messages and what to do about each.
- `fpgas-<board>-debug` (package `fpgas-online-<board>-debug`) loads one test's design and shows all its output.

### Next

- [Identity and labels](identity-and-labels.md#identity-and-labels): who the board is, and its labels.
- The commands and settings below.

## Commands and settings

```bash
sudo fpgas-verify                          # check this host's board, as the boot does
sudo fpgas-arty-verify                     # check the Arty, whatever this host is set up for
sudo fpgas-arty-verify --test ddr          # run one test; the JSON report goes to stdout
sudo fpgas-acorn-verify --test pcie-link --test flash   # only some tests (these two only read)
sudo fpgas-verify --update                 # after flashing or swapping a board on purpose
fpgas-verify --list                        # the installed boards, and which this host checks

sudo fpgas-verify --identify               # who the board is, as JSON (see "Identity and labels")
sudo fpgas-verify --label --out labels.pdf # this Pi's and its board's labels, made by rpi-hwid

sudo fpgas-arty-debug test ddr             # load the DDR design and run its test, all output live
sudo fpgas-acorn-debug identify            # the same as fpgas-acorn-verify --identify
```

`--identify` and `--label` are described in [Identity and labels](identity-and-labels.md#identity-and-labels).

* Run them with `sudo`; [`--help`](help.md#the-help-of-each-tool), `--list` and `fpgas-<board>-debug list` do not need it.
* Nothing is sent anywhere unless a file says `[verify] publish = on` (next to `fpga-board`, below). A host that
  only has the packages installed publishes nothing, at boot or by hand; its summary says so in one line
  (`not published: no file says ...`), and there is no error. The
  fpgas.online Pi root sets it in `/etc/fpgas-verify/fleet.ini`, so a fleet Pi tells its site how the check
  went; there, `--no-publish` is how a run by hand stays private. Each transcript of [Reading the result](reading-the-result.md#reading-the-result) shows the line that says
  whether it was published.
* `--test` runs part of the check. It is never published, never recorded, and its report goes to stdout
  unless `--report` says otherwise.
* Only one command uses a board at a time. A second one prints
  `waiting for another user of the <board> to finish...` and waits. Looking for a NeTV2 drives its JTAG pins,
  so the check and `fpgas-netv2-debug detect` take its lock for that too, waiting as for the check, and let
  it go before the check takes it again.
* The locks are files: `/run/fpgas-online/<board>.lock`, and the Acorn's `/run/lock/fpgas-acorn.lock` (shared
  with `fpgas-acorn-flash`). The packages' `/usr/lib/tmpfiles.d/fpgas-online-*.conf` create them at boot,
  root-owned and 0644, so no other user can create one first. A lock file that cannot be opened is an error
  naming the file and its owner: remove it, or reboot.
* Which board a host checks is `[verify] fpga-board = <board>` or `auto`, in `*.ini` files: the board's
  package puts one in `/usr/share/fpgas-online/verify/mode.d/`; one in `/etc/fpgas-verify/` overrides it.
* `[verify] publish = on` in the same files makes the check tell the fleet how it went. It
  is off unless a file says so; a value that is neither `on` nor `off`, or two files that disagree, is an
  error and nothing is sent. Accepted values are `on`, `yes`, `true`, `1` and `off`, `no`, `false`, `0`, as for `power-cycle-check`.
  Every report and summary says whether the run was published and why: `"publish": {"on": true,
  "configured_by": "/etc/fpgas-verify/fleet.ini"}` and `published to the fleet: ...`, or `"publish": {"on":
  false, "why": "..."}` and `not published: ...`. On a fleet Pi, `not published: no file ...` in
  `journalctl -b -u fpgas-verify` means the root lost its `fleet.ini`.
* `[verify] power-cycle-check = on` in the same files switches on the Acorn's [power-cycle
  check](acorn-power-cycle.md#the-acorn-power-cycle-check-opt-in). It is off unless a file says so: the fpgas.online Pi root sets it
  in `/etc/fpgas-verify/`; elsewhere it stays off.
* Options for the boot run go in `FPGAS_VERIFY_ARGS` in `/etc/default/fpgas-verify`. The package installs that
  file with every line a comment (it is what `EnvironmentFile=` in `systemctl cat fpgas-verify` names), so
  the boot run is plain `fpgas-verify` until you edit it. It is a configuration file: an upgrade keeps your
  edit.
* From a checkout, without installing: `PYTHONPATH=verify/src python3 -m fpgas_online_verify --help` (its output: [`--help`](help.md#the-help-of-each-tool)).
