"""Run a board test that must be listening before its design is loaded.

    python3 -m fpgas_online_verify.listen PORT N TEST_ARGV... PROGRAM_ARGV...

The first N arguments after PORT are the test script's argv, the rest the programmer's. The test starts first;
once it has PORT open (Linux: /proc/<pid>/fd) and a moment more for the flush pyserial does on open, the design
is loaded, and the exit status is the test's (or the programmer's, if loading failed).

A design that prints its result once, the moment it starts (the SPI flash test's JEDEC ID), is otherwise lost on
a UART the kernel only receives on while it is open: the NeTV2's, on the Pi's own ttyAMA0. An FTDI UART (the
Arty's) keeps what arrives in the chip until the port is opened, so it does not need this.
"""

import os
import subprocess
import sys
import time

OPEN_TIMEOUT = 15.0
SETTLE = 0.3
PROGRAM_TIMEOUT = 300
TEST_TIMEOUT = 300


def has_open(pid, path):
    fd_dir = f"/proc/{pid}/fd"
    try:
        return any(os.path.realpath(os.path.join(fd_dir, fd)) == path for fd in os.listdir(fd_dir))
    except OSError:
        return False  # not started yet, exited, or an fd went away while we looked


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port, n = os.path.realpath(argv[0]), int(argv[1])
    test, program = argv[2 : 2 + n], argv[2 + n :]
    child = subprocess.Popen(test)
    deadline = time.monotonic() + OPEN_TIMEOUT
    while not has_open(child.pid, port) and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if not has_open(child.pid, port):
        print(f"the test did not open {port} within {OPEN_TIMEOUT:.0f} s; loading the design anyway", flush=True)
    time.sleep(SETTLE)
    print("$ " + " ".join(program), flush=True)
    try:
        rc = subprocess.run(program, check=False, timeout=PROGRAM_TIMEOUT).returncode
    except subprocess.TimeoutExpired:  # run() has killed it; the test must not be left holding the port
        print(f"loading the design did not finish within {PROGRAM_TIMEOUT} s", flush=True)
        rc = 1
    if rc != 0:
        child.kill()
        child.wait()
        print(f"loading the design failed (exit {rc})", flush=True)
        return rc
    try:
        return child.wait(timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        print(f"the test did not finish within {TEST_TIMEOUT} s", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
