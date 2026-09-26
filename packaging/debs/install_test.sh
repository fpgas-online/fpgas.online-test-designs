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

echo "--- one board: fpgas-online-arty"
apt-get install -qq fpgas-online-arty >/dev/null
for p in fpgas-online-arty fpgas-online-arty-tools fpgas-online-arty-bitstreams fpgas-online-verify python3-serial; do
  installed "$p" || fail "$p not installed with fpgas-online-arty"
done
for p in fpgas-online-netv2-tools fpgas-online-fomu-tools fpgas-online-acorn-tools fpgas-online-arty-debug openocd \
         python3-libgpiod micropython-mpremote fpgas-online-setup-pi fpgas-online-multi-board; do
  if installed "$p"; then fail "$p was pulled in by fpgas-online-arty"; fi
done
command -v openFPGALoader >/dev/null || fail "no openFPGALoader for the Arty"
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
find /usr/lib/python3/dist-packages/fpgas_online_verify -name __pycache__ | grep -q . && fail "bytecode left in dist-packages"

echo "--- swapping to fpgas-online-fomu removes fpgas-online-arty (the mode packages conflict)"
apt-get install -qq fpgas-online-fomu >/dev/null
installed fpgas-online-arty && fail "two mode packages installed"
[ "$(ls /usr/share/fpgas-online/verify/mode.d)" = "fpgas-online-fomu.ini" ] || fail "mode.d: $(ls /usr/share/fpgas-online/verify/mode.d)"
enabled || fail "fpgas-verify.service not enabled after the swap"

echo "--- removing the mode package disables the boot check"
apt-get remove -qq fpgas-online-fomu >/dev/null
enabled && fail "fpgas-verify.service still enabled with no mode package"
apt-get purge -qq 'fpgas-online-*' >/dev/null
apt-get autoremove -qq --purge >/dev/null

echo "--- the Acorn: PCIe and the stdlib, nothing for USB or serial"
apt-get install -qq fpgas-online-acorn >/dev/null
for p in python3-serial openfpgaloader openocd python3-libgpiod libftdi1-2 libusb-1.0-0; do
  if installed "$p"; then fail "$p was pulled in by fpgas-online-acorn"; fi
done
enabled || fail "not enabled by fpgas-online-acorn"
set +e; fpgas-verify --no-publish --report /tmp/r.json; rc=$?; set -e
[ $rc -ne 0 ] && python3 -c 'import json; assert json.load(open("/tmp/r.json"))["result"] == "missing"' || fail "Acorn not missing"
fpgas-acorn-flash --help >/dev/null
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
