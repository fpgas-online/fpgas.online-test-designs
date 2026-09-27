"""Run a board test that must be listening before its design is loaded.

    python3 -m fpgas_online_verify.listen PORT N TEST_ARGV... PROGRAM_ARGV...

The first N arguments after PORT are the test script's argv, the rest the programmer's. The test starts first;
once it has PORT open (Linux: /proc/<pid>/fd) and a moment more for the flush pyserial does on open, the design
is loaded, and the exit status is the test's (or the programmer's, if loading failed).

A design that prints its result once, the moment it starts (the SPI flash test's JEDEC ID), is otherwise lost on
a UART the kernel only receives on while it is open: the NeTV2's, on the Pi's own ttyAMA0 (pi-sw1-p10,
2026-09-27). An FTDI UART (the Arty's) keeps what arrives in the chip until the port is opened, so it did not
need this.
"""

import os
import subprocess
import sys
import time

OPEN_TIMEOUT = 15.0
SETTLE = 0.3
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
    time.sleep(SETTLE)
    print("$ " + " ".join(program), flush=True)
    loaded = subprocess.run(program, check=False)
    if loaded.returncode != 0:
        child.kill()
        child.wait()
        print(f"loading the design failed (exit {loaded.returncode})", flush=True)
        return loaded.returncode
    try:
        return child.wait(timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        print(f"the test did not finish within {TEST_TIMEOUT} s", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
