#!/bin/sh
# The install rules of the fpgas-online-verify debs (docs/plans/2026-09-26-fpgas-online-verify-design.md),
# checked in a clean Debian container with the built debs at /dist (read-only), served as an apt repository so
# apt resolves the dependencies as it would from apt.fpgas.online. Run with no FPGA visible: the host's own USB
# and PCI devices hidden (tmpfs over /sys/bus/{usb,pci}/devices), so every verify here must be "missing".
#
#   docker run --rm --mount type=tmpfs,destination=/sys/bus/pci/devices \
#     --mount type=tmpfs,destination=/sys/bus/usb/devices -v "$PWD/dist:/dist:ro" \
#     -v "$PWD/packaging/debs/install_test.sh:/install_test.sh:ro" debian:bookworm sh /install_test.sh
set -eu
export DEBIAN_FRONTEND=noninteractive
echo 'APT::Get::Assume-Yes "true";' > /etc/apt/apt.conf.d/90yes
apt-get update -qq
apt-get install -qq dpkg-dev >/dev/null
mkdir /repo && cp /dist/*.deb /repo/ && (cd /repo && dpkg-scanpackages --multiversion . > Packages)
echo "deb [trusted=yes] file:/repo ./" > /etc/apt/sources.list.d/local.list
apt-get update -qq
. /etc/os-release
echo "=== $PRETTY_NAME, $(dpkg --print-architecture)"

fail() { echo "FAIL: $*" >&2; exit 1; }
# dpkg-query's complaint about a package it has never heard of goes into the pipe, where it matches nothing.
installed() { dpkg-query -W -f='${db:Status-Status}' "$1" 2>&1 | grep -qx installed; }
enabled() { [ -L /etc/systemd/system/multi-user.target.wants/fpgas-verify.service ]; }

# The boards need an openFPGALoader that has --read-dna: fpgas.online's build, or Debian's own from 0.13.0 on.
# Bookworm's own is 0.10.0, so there a board is refused until apt.fpgas.online's build is available; this
# repository has none, so an empty stand-in named like it (pulling in Debian's binary) takes its place.
if [ "$VERSION_CODENAME" = bookworm ]; then
  echo "--- bookworm without fpgas.online's openFPGALoader: fpgas-online-arty refused"
  if apt-get install -qq fpgas-online-arty >/dev/null; then fail "fpgas-online-arty installed with openFPGALoader 0.10.0"; fi
  mkdir -p /standin/DEBIAN
  printf 'Package: openfpgaloader-fpgasonline\nVersion: 0.0-standin\nArchitecture: all\nDepends: openfpgaloader\nMaintainer: install test <noreply@fpgas.online>\nDescription: stand-in for the install test\n' \
    > /standin/DEBIAN/control
  dpkg-deb --build /standin /repo/openfpgaloader-fpgasonline_0.0-standin_all.deb >/dev/null
  (cd /repo && dpkg-scanpackages --multiversion . > Packages)
  apt-get update -qq
fi

echo "--- one board: fpgas-online-arty"
apt-get install -qq fpgas-online-arty >/dev/null
# The boot check also runs the Arty's Ethernet test and PMOD HAT pin-ID scan, so their tools come with it.
for p in fpgas-online-arty fpgas-online-arty-tools fpgas-online-arty-bitstreams fpgas-online-verify python3-serial \
         python3-libgpiod iproute2 iputils-ping; do
  installed "$p" || fail "$p not installed with fpgas-online-arty"
done
for p in fpgas-online-netv2-tools fpgas-online-fomu-tools fpgas-online-acorn-tools fpgas-online-arty-debug openocd \
         micropython-mpremote fpgas-online-setup-pi fpgas-online-multi-board sudo; do
  if installed "$p"; then fail "$p was pulled in by fpgas-online-arty"; fi
done
command -v openFPGALoader >/dev/null || fail "no openFPGALoader for the Arty"
command -v arping >/dev/null || fail "no arping for the Arty's Ethernet test"
enabled || fail "fpgas-verify.service not enabled by fpgas-online-arty"
cat /usr/share/fpgas-online/verify/mode.d/*.ini
set +e
fpgas-verify --no-publish --report /tmp/r.json 2>/tmp/err; rc=$?
set -e
cat /tmp/err
[ $rc -ne 0 ] || fail "fpgas-verify passed with no Arty"
python3 -c 'import json; r = json.load(open("/tmp/r.json")); assert r["result"] == "missing", r; print("result:", r["result"])'
grep -q '\*\*\* FPGA VERIFY: MISSING' /tmp/err || fail "the failure is not loud"
set +e; fpgas-arty-verify --no-publish --report /tmp/r2.json 2>/tmp/err2; rc=$?; set -e
[ $rc -ne 0 ] || fail "fpgas-arty-verify passed with no Arty"
[ ! -e /var/lib/fpgas-online/verify-state.json ] || fail "state recorded for a board that is not there"
fpgas-verify --list

echo "--- publishing: nothing is sent unless /etc/fpgas-verify says so (the fpgas.online Pi root does)"
# A stand-in fleet-event that records how it was called, where the fleet's own would be.
printf '#!/bin/sh\necho "$@" >> /tmp/fleet-events\n' > /usr/local/bin/fleet-event && chmod +x /usr/local/bin/fleet-event
set +e; fpgas-verify --report /tmp/r3.json 2>/tmp/err3; set -e
[ ! -e /tmp/fleet-events ] || fail "a host with only the packages published: $(cat /tmp/fleet-events)"
if grep -q 'could not publish' /tmp/err3; then fail "a host with only the packages tried to publish: $(cat /tmp/err3)"; fi
grep -q '^  not published: no file says `publish = on`' /tmp/err3 \
  || fail "the summary does not say nothing was published: $(cat /tmp/err3)"
python3 -c 'import json; r = json.load(open("/tmp/r3.json")); assert r["publish"]["on"] is False and "no file" in r["publish"]["why"], r'
mkdir -p /etc/fpgas-verify
printf '[verify]\npublish = on\n' > /etc/fpgas-verify/fleet.ini
set +e; fpgas-verify --report /tmp/r4.json 2>/tmp/err4; set -e
grep -q '^fpga-verifying ' /tmp/fleet-events || fail "the fleet's file did not turn publishing on: $(cat /tmp/err4)"
grep -q '^fpga-verified .*result=missing' /tmp/fleet-events || fail "no fpga-verified: $(cat /tmp/fleet-events)"
grep -q '^  published to the fleet: `publish = on` in /etc/fpgas-verify/fleet.ini' /tmp/err4 \
  || fail "the summary does not say it published: $(cat /tmp/err4)"
python3 -c 'import json; r = json.load(open("/tmp/r4.json")); assert r["publish"] == {"on": True, "configured_by": "/etc/fpgas-verify/fleet.ini"}, r'
rm /tmp/fleet-events
set +e; fpgas-verify --no-publish --report /tmp/r5.json 2>/tmp/err5; set -e
[ ! -e /tmp/fleet-events ] || fail "--no-publish published: $(cat /tmp/fleet-events)"
printf '[verify]\npublish = sometimes\n' > /etc/fpgas-verify/fleet.ini
set +e; fpgas-verify --report /tmp/r6.json 2>/tmp/err6; rc=$?; set -e
[ $rc -ne 0 ] || fail "a bad publish setting was not an error"
[ ! -e /tmp/fleet-events ] || fail "a bad publish setting still published: $(cat /tmp/fleet-events)"
python3 -c 'import json; r = json.load(open("/tmp/r6.json")); assert r["result"] == "error" and "publish is" in r["reason"], r'
rm -r /etc/fpgas-verify /usr/local/bin/fleet-event
find /usr/lib/python3/dist-packages/fpgas_online_verify -name __pycache__ | grep -q . && fail "bytecode left in dist-packages"

echo "--- swapping to fpgas-online-fomu removes fpgas-online-arty (the boards' packages conflict)"
apt-get install -qq fpgas-online-fomu >/dev/null
installed fpgas-online-arty && fail "two boards' packages installed"
[ "$(ls /usr/share/fpgas-online/verify/mode.d)" = "fpgas-online-fomu.ini" ] || fail "mode.d: $(ls /usr/share/fpgas-online/verify/mode.d)"
enabled || fail "fpgas-verify.service not enabled after the swap"

echo "--- removing fpgas-online-fomu turns the boot check off"
apt-get remove -qq fpgas-online-fomu >/dev/null
enabled && fail "fpgas-verify.service still enabled with no board's package"
apt-get purge -qq 'fpgas-online-*' >/dev/null
apt-get autoremove -qq --purge >/dev/null

echo "--- the Acorn: PCIe, plus openFPGALoader (P1 JTAG) and pyserial (P2 UART); pinctrl is only Recommended"
apt-get install -qq fpgas-online-acorn >/dev/null
installed python3-serial || fail "python3-serial not installed with fpgas-online-acorn"
command -v openFPGALoader >/dev/null || fail "no openFPGALoader for the Acorn's P1 JTAG check"
for p in openocd python3-libgpiod micropython-mpremote; do
  if installed "$p"; then fail "$p was pulled in by fpgas-online-acorn"; fi
done
enabled || fail "not enabled by fpgas-online-acorn"
set +e; fpgas-verify --no-publish --report /tmp/r.json; rc=$?; set -e
[ $rc -ne 0 ] && python3 -c 'import json; assert json.load(open("/tmp/r.json"))["result"] == "missing"' || fail "Acorn not missing"
fpgas-acorn-flash --help >/dev/null
# the setups' wiring and figures are installed with the module, where it reads them
python3 -c 'from fpgas_online_verify.boards.acorn import setup; s = setup.detect("Raspberry Pi 5 Model B Rev 1.1"); assert s.jtag_pins == "10:9:11:8" and s.expected["pcie"]["width"] == 1' \
  || fail "the Acorn's wiring.toml / expected.toml are not installed"
apt-get purge -qq 'fpgas-online-*' >/dev/null
apt-get autoremove -qq --purge >/dev/null

echo "--- every board: fpgas-online-all-boards"
apt-get install -qq fpgas-online-all-boards >/dev/null
for b in acorn arty netv2 fomu tt-fpga; do
  installed "fpgas-online-$b-tools" || fail "fpgas-online-$b-tools missing"
  installed "fpgas-online-$b-debug" || fail "fpgas-online-$b-debug not recommended in"
  command -v "fpgas-$b-verify" >/dev/null && command -v "fpgas-$b-debug" >/dev/null || fail "commands for $b"
done
enabled || fail "not enabled by fpgas-online-all-boards"
set +e; fpgas-verify --no-publish --report /tmp/r.json 2>/tmp/err; rc=$?; set -e
cat /tmp/err
[ $rc -ne 0 ] || fail "all-boards passed with no board"
python3 -c 'import json; r = json.load(open("/tmp/r.json")); assert r["result"] == "missing" and r["mode"] == "auto", r'
for b in arty netv2 fomu tt-fpga; do fpgas-$b-debug check | tail -1; done
fpgas-netv2-debug list | head -3
echo "ALL-OK"
