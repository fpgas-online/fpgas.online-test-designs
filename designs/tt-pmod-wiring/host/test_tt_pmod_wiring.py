"""Tests for check_tt_pmod_wiring.py.

The GPIO reading and the serial link need a Raspberry Pi and a demo board,
but everything above them must be right without either: the expectation
tables, the verdict, the TTW protocol handling, and the measurement sequence
itself. The sequence is exercised end to end against a simulated board: a
fake RP2 that speaks the TTW protocol over a socket, an electrical model of
the ribbons, the HAT's JA/JB short, the Pi's fixed I2C pull-ups and the
ASIC's factory-test behaviour, and a fake HAT reader on the Pi side. The
model records any net whose settled state has two disagreeing drivers, so
the tests also prove the sequence never causes contention — with or without
the ASIC loopback, and on the shorted bits.
"""

import importlib.util
import pathlib
import socket
import threading

import pytest

_MOD_PATH = pathlib.Path(__file__).with_name("check_tt_pmod_wiring.py")
_spec = importlib.util.spec_from_file_location("check_tt_pmod_wiring", _MOD_PATH)
ttw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ttw)

RP2040 = ttw.CONTROLLERS["rp2040"]
JA, JB, JC = (ttw.PMOD_HAT_PORTS[p] for p in ("JA", "JB", "JC"))


# -- Electrical model ----------------------------------------------------------------


class BoardModel:
    """Nets between RP2 GPIOs, the ASIC and Pi GPIOs.

    *wires* maps an RP2 data GPIO to the Pi GPIOs its ribbon line reaches;
    *extra_shorts* joins further node pairs (``"pi:16"``, ``"rp2:9"``).
    The ASIC drives ``uo_out`` at the RP2-side node of each ``uo_out`` GPIO
    and, when a project has ``uio_oe`` set, ``uio`` likewise. Pi GPIO2/3
    carry the board's fixed 1.8k pull-ups, which beat every weak pull.
    """

    UI, UIO, UO = RP2040["ui_in"], RP2040["uio"], RP2040["uo_out"]

    def __init__(self, wires, project="factory", extra_shorts=(), held_ui_in=()):
        self.wires = wires
        self.project = project  # what the chip is running right now
        self.rp2 = {g: ("in", None) for g in self.UI + self.UIO + self.UO}
        self.pi_bias = "down"
        self.pi_pull_up = set()
        self.held_ui_in = set(held_ui_in)  # ui_in bits a DIP switch ties high
        self.levels = {}
        self.contentions = []
        self.reset_n = 1
        self.cnt = 7  # a stale counter value: reset must clear it
        # union-find over nodes
        self.parent = {}
        for g in self.rp2:
            self._add(f"rp2:{g}")
        for g in ttw.ALL_HAT_GPIOS:
            self._add(f"pi:{g}")
        for g, pis in wires.items():
            for pi in pis:
                self._union(f"rp2:{g}", f"pi:{pi}")
        for a, b in extra_shorts:
            self._union(a, b)

    def _add(self, n):
        self.parent.setdefault(n, n)

    def _find(self, n):
        while self.parent[n] != n:
            self.parent[n] = self.parent[self.parent[n]]
            n = self.parent[n]
        return n

    def _union(self, a, b):
        self._add(a)
        self._add(b)
        self.parent[self._find(a)] = self._find(b)

    def net(self, node):
        return self._find(node)

    # -- chip behaviour ------------------------------------------------------------

    def asic_drivers(self, levels):
        """{node: value} the ASIC drives, given the current net levels."""
        drivers = {}
        if self.project == "factory":
            # tt_um_factory_test: uo_out = ui_in[0] ? cnt : uio_in; uio_oe = ui_in[0] ? 0xff : 0
            ui0 = levels.get(self.net(f"rp2:{self.UI[0]}"), 0)
            for k in range(8):
                if ui0:
                    drivers[f"rp2:{self.UO[k]}"] = (self.cnt >> k) & 1
                    drivers[f"rp2:{self.UIO[k]}"] = (self.cnt >> k) & 1
                else:
                    drivers[f"rp2:{self.UO[k]}"] = levels.get(self.net(f"rp2:{self.UIO[k]}"), 0)
        elif self.project == "drives_uio":
            # Some project with all uio as outputs (0x55) and a fixed uo_out (0xA5).
            for k in range(8):
                drivers[f"rp2:{self.UO[k]}"] = (0xA5 >> k) & 1
                drivers[f"rp2:{self.UIO[k]}"] = (0x55 >> k) & 1
        elif self.project == "quiet":
            # uo_out low, uio inputs.
            for k in range(8):
                drivers[f"rp2:{self.UO[k]}"] = 0
        elif self.project == "echo":
            # uo_out = ui_in (an unknown project reacting to ui_in), uio inputs.
            for k in range(8):
                drivers[f"rp2:{self.UO[k]}"] = levels.get(self.net(f"rp2:{self.UI[k]}"), 0)
        for k in self.held_ui_in:
            drivers[f"rp2:{self.UI[k]}"] = 1
        return drivers

    def reset(self):
        self.cnt = 0

    # -- net resolution --------------------------------------------------------------

    def _drivers(self, levels):
        """Strong and weak drivers per net, with the ASIC reacting to *levels*."""
        asic = self.asic_drivers(levels)
        strong = {}
        weak = {}
        fixed_up = set()
        for node in self.parent:
            net = self.net(node)
            kind, gpio = node.split(":")
            gpio = int(gpio)
            if kind == "rp2":
                mode, val = self.rp2[gpio]
                if mode == "out":
                    strong.setdefault(net, []).append(("rp2", gpio, val))
                elif val == "up":
                    weak.setdefault(net, []).append(1)
                elif val == "down":
                    weak.setdefault(net, []).append(0)
                if node in asic:
                    strong.setdefault(net, []).append(("asic", gpio, asic[node]))
            else:
                if gpio in ttw.PI_FIXED_PULLUP_GPIOS:
                    fixed_up.add(net)
                if gpio in self.pi_pull_up or self.pi_bias == "up":
                    weak.setdefault(net, []).append(1)
                elif self.pi_bias == "down":
                    weak.setdefault(net, []).append(0)
        return strong, weak, fixed_up

    def resolve(self):
        """Settle every net; record contention at the settled state; return {net: level}.

        Contention is judged only once the nets have settled: the chip's
        combinational ``uo_out = uio_in`` lags the RP2 by one iteration, which
        is the propagation delay, not a fight.
        """
        levels = dict(self.levels)
        for _ in range(10):
            strong, weak, fixed_up = self._drivers(levels)
            new = {}
            for node in self.parent:
                net = self.net(node)
                if net in new:
                    continue
                if net in strong:
                    new[net] = strong[net][0][2]
                elif net in fixed_up:
                    new[net] = 1
                elif net in weak:
                    pulls = set(weak[net])
                    new[net] = weak[net][0] if len(pulls) == 1 else levels.get(net, 0)
                else:
                    new[net] = levels.get(net, 0)  # floating: keeps its charge
            if new == levels:
                break
            levels = new
        strong, _weak, _fixed = self._drivers(levels)
        for _net, drivers in strong.items():
            if len({d[2] for d in drivers}) > 1:
                self.contentions.append(sorted(drivers))
        self.levels = levels
        return levels

    def pi_read_all(self):
        levels = self.resolve()
        return {g: levels[self.net(f"pi:{g}")] for g in ttw.ALL_HAT_GPIOS}

    def rp2_read(self, gpio):
        levels = self.resolve()
        return levels[self.net(f"rp2:{gpio}")]


def standard_wires(controller="rp2040", cabling="standard", swap=None, unplug=(), drop=()):
    """The documented cabling as a wires dict.

    *swap* exchanges two RP2 GPIOs' lines; *unplug* removes whole groups;
    *drop* removes single RP2 GPIOs' lines (one broken wire).
    """
    table = ttw.CONTROLLERS[controller]
    ports = ttw.CABLINGS[cabling]
    wires = {}
    for group in ttw.GROUPS:
        if group in unplug:
            continue
        hat = ttw.PMOD_HAT_PORTS[ports[group]]
        for bit in range(8):
            if table[group][bit] not in drop:
                wires[table[group][bit]] = {hat[bit]}
    if swap:
        (ga, gb) = swap
        wires[ga], wires[gb] = wires[gb], wires[ga]
    return wires


def swapped_ja_jb_wires():
    """JA and JB ribbons plugged into each other's port."""
    wires = {}
    for bit in range(8):
        wires[RP2040["ui_in"][bit]] = {JC[bit]}
        wires[RP2040["uio"][bit]] = {JA[bit]}
        wires[RP2040["uo_out"][bit]] = {JB[bit]}
    return wires


# -- Fake RP2 speaking the TTW protocol ----------------------------------------------------


class FakeFirmware:
    """Mirror of the MicroPython command server, acting on a BoardModel."""

    def __init__(self, model, projects=("tt_um_factory_test",), sdk=True):
        self.model = model
        self.projects = projects
        self.sdk = sdk
        self.saved_mode = None

    def _release(self):
        for g in self.model.rp2:
            self.model.rp2[g] = ("in", None)

    def handle(self, line):
        parts = line.split()
        if not parts:
            return []
        cmd, args = parts[0], parts[1:]
        m = self.model
        try:
            if cmd == "out":
                g = int(args[0])
                m.rp2[g] = ("out", int(args[1]))
                return [f"TTW OK {m.rp2_read(g)}"]
            if cmd == "in":
                m.rp2[int(args[0])] = ("in", None if args[1] == "none" else args[1])
                return ["TTW OK"]
            if cmd == "read":
                g = int(args[0])
                return [f"TTW VAL {g} {m.rp2_read(g)}"]
            if cmd == "readall":
                m.resolve()
                return ["TTW VALS " + " ".join(str(m.rp2_read(g)) for g in m.UI + m.UIO + m.UO)]
            if cmd == "release":
                self._release()
                return ["TTW OK"]
            if cmd == "ping":
                return ["TTW PONG"]
            if cmd == "quit":
                self._release()
                return ["TTW BYE"]
            if cmd == "sdk":
                if not self.sdk:
                    raise ImportError("no module named 'ttboard'")
                op = args[0]
                if op == "init":
                    self.saved_mode = 1
                    return ["TTW WARN clock_project_stop: AttributeError", "TTW OK mode=1"]
                if op == "project":
                    if args[1] not in self.projects:
                        raise KeyError(args[1])
                    m.project = "factory" if args[1] == "tt_um_factory_test" else args[1]
                    return [f"TTW OK enabled={args[1]}"]
                if op == "reset":
                    m.reset()
                    return ["TTW OK"]
                if op == "restore":
                    self._release()
                    return ["TTW OK"]
            return [f"TTW ERR unknown command {cmd}"]
        except Exception as e:  # mirrors the firmware's catch-all
            return [f"TTW ERR {cmd}: {e!r}"]


def serve(sock, firmware):
    """Run *firmware* on *sock* until quit or EOF (thread target)."""
    buf = b""
    try:
        sock.sendall(b"TTW READY\n")
        while True:
            data = sock.recv(4096)
            if not data:
                return
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                for reply in firmware.handle(line.decode()):
                    sock.sendall(reply.encode() + b"\n")
                if line.strip() == b"quit":
                    sock.sendall(b"\x04\x04>")
                    return
    except OSError:
        return


class FakeHat:
    def __init__(self, model):
        self.model = model
        self.chip_path = "/dev/gpiochip-fake"

    def set_bias(self, bias, pull_up=()):
        self.model.pi_bias = bias
        self.model.pi_pull_up = set(pull_up)

    def read_all(self):
        return self.model.pi_read_all()


def run_simulated(model, argv=(), projects=("tt_um_factory_test",), sdk=True, firmware_cls=FakeFirmware,
                  hat_cls=FakeHat):
    """Run the full measurement against *model*; return (result, log_lines)."""
    a, b = socket.socketpair()
    firmware = firmware_cls(model, projects=projects, sdk=sdk)
    thread = threading.Thread(target=serve, args=(b, firmware), daemon=True)
    thread.start()
    log = []
    link = ttw.Rp2Link(a.fileno(), timeout=5.0, log=log.append)
    assert link.expect()[:1] == ["READY"]
    args = ttw.parse_args(list(argv))
    args.samples = 2
    try:
        result = ttw.run_wiring_test(link, hat_cls(model), args, log=log.append)
        link.cmd("quit")
    finally:
        a.close()
        b.close()
    thread.join(timeout=2)
    return result, log


def rows_by_name(result):
    return {r["signal"]: r for r in result["rows"]}


def statuses(result, group):
    rows = rows_by_name(result)
    return {k: rows[f"{group}[{k}]"]["status"] for k in range(8)}


# -- Tables --------------------------------------------------------------------------------


def test_hat_ports_are_21_unique_lines_with_ja_jb_shared():
    assert len(ttw.ALL_HAT_GPIOS) == 21
    assert ttw.HAT_GPIO_LABELS[10] == "JA2/JB2"
    assert ttw.HAT_GPIO_LABELS[16] == "JC1"


def test_shorted_uio_bits_are_1_to_3_for_standard_cabling():
    assert ttw.shorted_uio_bits("standard") == [1, 2, 3]


def test_expected_map_matches_documented_cabling():
    exp = ttw.expected_map("standard", asic_loopback=False)
    # docs/hardware/tt-fpga-pin-mapping.md: ui_in[0] = JC1 = GPIO16 ... ui_in[7] = JC10 = GPIO6
    assert [sorted(exp[f"ui_in[{k}]"]) for k in range(8)] == [[16], [14], [15], [17], [4], [12], [5], [6]]
    assert [sorted(exp[f"uio[{k}]"]) for k in range(8)] == [[7], [10], [9], [11], [26], [13], [3], [2]]
    with_asic = ttw.expected_map("standard", asic_loopback=True)
    assert with_asic["uio[0]"] == {7, 8}  # JB1 direct + JA1 through the chip
    assert with_asic["uio[1]"] == {10}  # JB2 and JA2 are the same Pi line
    assert with_asic["uio[7]"] == {2, 18}
    assert ttw.expected_direct("standard")["uio[0]"] == 7


def test_controller_tables():
    assert RP2040["ui_in"] == [9, 10, 11, 12, 17, 18, 19, 20]
    assert RP2040["uio"] == list(range(21, 29))
    assert RP2040["uo_out"] == [5, 6, 7, 8, 13, 14, 15, 16]
    assert ttw.CONTROLLERS["rp2350"]["uo_out"] == list(range(33, 41))
    fw = ttw.build_firmware("rp2350")
    assert "DATA = [17, 18" in fw and "40]" in fw
    assert "finally:" in fw  # pins are released even if the loop is interrupted


# -- Verdict ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expected,observed,status",
    [
        ({16}, {16}, "ok"),
        ({16}, set(), "open"),
        ({16}, {16, 17}, "short"),
        ({16}, {17}, "miswired"),
        ({7, 8}, {7, 9}, "miswired"),
        ({7, 8}, {7}, "partial"),
    ],
)
def test_classify(expected, observed, status):
    assert ttw.classify(expected, observed) == status


def test_evaluate_untested_required_row_fails():
    expected = ttw.expected_map("standard", False)
    observed = {name: set(pins) for name, pins in expected.items() if name.startswith("ui_in")}
    ok, rows, _shorts = ttw.evaluate(observed, expected, set(observed), set(expected))
    assert not ok
    assert {r["status"] for r in rows if r["signal"].startswith("uio")} == {"untested"}
    ok, _rows, _ = ttw.evaluate(observed, expected, set(observed), set(observed))
    assert ok


def test_evaluate_cross_checks_override_ok():
    expected = ttw.expected_map("standard", True)
    observed = {n: set(p) for n, p in expected.items()}
    direct = ttw.expected_direct("standard")
    # Reverse walk says uio[0]'s own line is JA1, not JB1 -> ribbons swapped.
    _ok, rows, _ = ttw.evaluate(observed, expected, set(observed), set(observed), direct=direct,
                                reverse={"uio[0]": {8}})
    assert rows_by_name({"rows": rows})["uio[0]"]["status"] == "miswired"
    _ok, rows, _ = ttw.evaluate(observed, expected, set(observed), set(observed), follows={"ui_in[2]": ["ui_in[3]"]})
    assert rows_by_name({"rows": rows})["ui_in[2]"]["status"] == "short"
    _ok, rows, _ = ttw.evaluate(observed, expected, set(observed), set(observed), drive_failures={"uio[1]": 0})
    assert rows_by_name({"rows": rows})["uio[1]"]["status"] == "contention"
    _ok, rows, _ = ttw.evaluate(observed, expected, set(observed), set(observed), latch={"uio[2]": False})
    assert rows_by_name({"rows": rows})["uio[2]"]["status"] == "partial"


# -- Protocol ----------------------------------------------------------------------------------


def _link_with(server_bytes):
    a, b = socket.socketpair()
    b.sendall(server_bytes)
    return ttw.Rp2Link(a.fileno(), timeout=1.0), a, b


def test_cmd_collects_warnings_and_returns_fields():
    link, a, b = _link_with(b"TTW WARN clock thing\r\nTTW VAL 21 1\r\n")
    assert link.cmd("read 21") == ["VAL", "21", "1"]
    assert link.warnings == ["clock thing"]
    assert b.recv(100) == b"read 21\n"
    a.close()
    b.close()


def test_cmd_err_raises():
    link, a, b = _link_with(b"TTW ERR sdk: KeyError('x')\n")
    with pytest.raises(ttw.ProtocolError, match="KeyError"):
        link.cmd("sdk project x")
    a.close()
    b.close()


def test_cmd_firmware_exit_raises():
    link, a, b = _link_with(b"Traceback (most recent call last):\n  File <stdin>\nValueError: boom\n\x04\x04>")
    with pytest.raises(ttw.ProtocolError, match="firmware exited"):
        link.cmd("ping")
    a.close()
    b.close()


def test_cmd_timeout_raises():
    link, a, b = _link_with(b"")
    link.timeout = 0.2
    with pytest.raises(ttw.ProtocolError, match="timeout"):
        link.cmd("ping")
    a.close()
    b.close()


# -- Simulated end-to-end runs -------------------------------------------------------------


def test_correct_wiring_with_factory_loopback_passes():
    # The chip starts on some project that drives uio: selecting the factory
    # test must be what makes uio (and uo_out through it) testable.
    model = BoardModel(standard_wires(), project="drives_uio")
    result, _log = run_simulated(model)
    assert result["asic_loopback"] is True
    assert result["pass"] is True, [r for r in result["rows"] if r["status"] != "ok"]
    assert {r["status"] for r in result["rows"]} == {"ok"}
    assert len(result["rows"]) == 16
    assert model.contentions == []
    assert model.cnt == 0
    # The reverse walk attributed every line the Pi can move.
    assert result["reverse"]["ui_in[1]"] == [14] and result["reverse"]["uio[0]"] == [7]
    assert "uio[6]" not in result["reverse"]  # GPIO3: fixed pull-up, cannot be moved
    assert "uio[1]" not in result["reverse"]  # shared with an ASIC-driven line
    # Lines the Pi could not move: the ASIC-driven JA lines, the I2C pull-ups,
    # and JC1 (ui_in[0] is held low by the RP2 throughout). Every other JB/JC
    # line followed the Pi's pulls.
    held = set(result["held"])
    assert set(JA) | {2, 3} <= held
    assert not held & ((set(JC) | set(JB)) - set(JA) - {2, 3, 16})
    assert result["latch"] == {"uio[1]": True, "uio[2]": True, "uio[3]": True}
    docs = ttw.format_docs_table({k: set(v) for k, v in result["observed"].items()}, "rp2040", "standard", True)
    assert "| uo_out[0] | 5           | JA1          | 8        | factory-test loopback via uio[0] |" in docs
    assert "| uo_out[1] | 6           | JA2/JB2      | 10       | factory-test loopback via uio[1] |" in docs
    assert "| ui_in[7]  | 20          | JC10         | 6        | wiring test |" in docs


def test_no_loopback_when_chip_drives_uio_tests_ui_in_only():
    model = BoardModel(standard_wires(), project="drives_uio")
    result, _log = run_simulated(model, argv=["--asic-project", "none"])
    assert result["asic_loopback"] is False
    assert set(statuses(result, "ui_in").values()) == {"ok"}
    assert set(statuses(result, "uio").values()) == {"untested"}
    assert result["pass"] is True  # not strict without the loopback
    assert model.contentions == []


def test_no_loopback_on_quiet_chip_tests_floating_uio_bits():
    # uio[1:3] share a Pi line with an ASIC-driven uo_out and uio[6:7] sit on
    # the Pi's 1.8k I2C pull-ups: neither follows the RP2's pulls, so only
    # uio[0], uio[4] and uio[5] are driven.
    model = BoardModel(standard_wires(), project="quiet")
    result, _log = run_simulated(model, argv=["--asic-project", "none"])
    st = statuses(result, "uio")
    assert {k for k in st if st[k] == "ok"} == {0, 4, 5}
    assert {k for k in st if st[k] == "untested"} == {1, 2, 3, 6, 7}
    assert result["pass"] is True
    assert model.contentions == []


def test_unknown_project_reacting_to_ui_in_is_not_a_short():
    model = BoardModel(standard_wires(), project="echo")
    result, _log = run_simulated(model, argv=["--asic-project", "none"])
    assert set(statuses(result, "ui_in").values()) == {"ok"}
    assert result["pass"] is True


def test_factory_project_unavailable_is_strict_failure():
    model = BoardModel(standard_wires(), project="drives_uio")
    result, _log = run_simulated(model, projects=())
    assert result["asic_loopback"] is False
    assert result["pass"] is False
    assert any("could not select tt_um_factory_test" in n for n in result["notes"])
    assert model.contentions == []


def test_factory_selection_that_did_not_take_is_detected():
    # The SDK says "enabled" but the chip keeps driving uio: nothing floats,
    # the on-board confirmation cannot run, and the run fails strictly.
    class StubbornFirmware(FakeFirmware):
        def handle(self, line):
            if line.startswith("sdk project"):
                return ["TTW OK enabled=tt_um_factory_test"]
            return super().handle(line)

    model = BoardModel(standard_wires(), project="drives_uio")
    result, _log = run_simulated(model, firmware_cls=StubbornFirmware)
    assert result["asic_loopback"] is False
    assert result["pass"] is False
    assert any("factory test not confirmed" in n for n in result["notes"])
    assert model.contentions == []


def test_wrong_project_with_floating_uio_fails_confirmation():
    # A quiet project lets uio float but does not loop it to uo_out.
    class QuietFirmware(FakeFirmware):
        def handle(self, line):
            if line.startswith("sdk project"):
                self.model.project = "quiet"
                return ["TTW OK enabled=tt_um_factory_test"]
            return super().handle(line)

    model = BoardModel(standard_wires(), project="drives_uio")
    result, _log = run_simulated(model, firmware_cls=QuietFirmware)
    assert result["asic_loopback"] is False
    assert any("not uo_out = uio_in" in n for n in result["notes"])
    assert model.contentions == []


def test_swapped_ui_in_bits_fail_as_miswired():
    model = BoardModel(standard_wires(swap=(RP2040["ui_in"][0], RP2040["ui_in"][1])))
    result, _log = run_simulated(model)
    rows = rows_by_name(result)
    assert result["pass"] is False
    assert rows["ui_in[0]"]["status"] == "miswired" and rows["ui_in[0]"]["observed"] == [14]
    assert rows["ui_in[1]"]["status"] == "miswired" and rows["ui_in[1]"]["observed"] == [16]
    assert all(rows[f"ui_in[{k}]"]["status"] == "ok" for k in range(2, 8))
    assert model.contentions == []


def test_swapped_ja_jb_ribbons_are_caught_by_the_reverse_walk():
    # The forward walk cannot tell: uio[k] lights JA[k] directly and JB[k]
    # through the chip, the same set as the correct cabling.
    model = BoardModel(swapped_ja_jb_wires())
    result, _log = run_simulated(model)
    rows = rows_by_name(result)
    assert result["pass"] is False
    assert rows["uio[0]"]["observed"] == [7, 8]
    assert rows["uio[0]"]["status"] == "miswired" and "its own line" in rows["uio[0]"]["detail"]
    assert result["reverse"]["uio[0]"] == [8]
    assert rows["uio[4]"]["status"] == "miswired"
    assert model.contentions == []


def test_unplugged_ui_in_ribbon_fails_as_open():
    model = BoardModel(standard_wires(unplug=("ui_in",)))
    result, _log = run_simulated(model)
    assert result["pass"] is False
    assert set(statuses(result, "ui_in").values()) == {"open"}
    assert set(statuses(result, "uio").values()) == {"ok"}


def test_unplugged_uo_out_ribbon_shows_in_uio_rows():
    model = BoardModel(standard_wires(unplug=("uo_out",)))
    result, _log = run_simulated(model)
    st = statuses(result, "uio")
    assert result["pass"] is False
    # Bits with their own JA line lose the through-the-chip pin; the shared
    # bits still see their single Pi line from the JB side but fail the latch.
    assert {k for k in st if st[k] == "partial"} == set(range(8))
    assert result["latch"] == {"uio[1]": False, "uio[2]": False, "uio[3]": False}


def test_single_broken_wire_on_shared_line_is_caught_by_latch():
    # JB2 (uio[1]) broken; the Pi still sees GPIO10 from uo_out[1] via JA2.
    model = BoardModel(standard_wires(drop=(RP2040["uio"][1],)))
    result, _log = run_simulated(model)
    rows = rows_by_name(result)
    assert result["pass"] is False
    assert rows["uio[1]"]["observed"] == [10]  # forward walk alone looks fine
    assert rows["uio[1]"]["status"] == "partial" and "loop open" in rows["uio[1]"]["detail"]
    assert result["latch"]["uio[1]"] is False and result["latch"]["uio[2]"] is True


def test_short_between_ribbon_lines_is_reported():
    model = BoardModel(standard_wires(), extra_shorts=[("pi:16", "pi:17")])
    result, _log = run_simulated(model)
    rows = rows_by_name(result)
    assert result["pass"] is False
    assert rows["ui_in[0]"]["status"] in ("short", "contention")
    assert rows["ui_in[3]"]["status"] in ("short", "open", "miswired", "contention")
    # Two RP2 outputs fight through a shorted ribbon during a walk; that is
    # inherent to any walking-1 test and harmless at the RP2040's drive.
    # The chip must never be one of the parties.
    assert all(d[0] == "rp2" for c in model.contentions for d in c)


def test_dip_switch_holding_ui_in_bit_is_skipped():
    model = BoardModel(standard_wires(), held_ui_in={5})
    result, _log = run_simulated(model)
    rows = rows_by_name(result)
    assert rows["ui_in[5]"]["status"] == "untested"
    assert any("ui_in[5] is held" in n for n in result["notes"])
    assert all(rows[f"ui_in[{k}]"]["status"] == "ok" for k in range(8) if k != 5)
    assert result["asic_loopback"] is True
    assert not any(d[1] == RP2040["ui_in"][5] and d[0] == "rp2" for c in model.contentions for d in c)


def test_held_ui_in0_disables_loopback():
    model = BoardModel(standard_wires(), held_ui_in={0})
    result, _log = run_simulated(model)
    assert result["asic_loopback"] is False
    assert any("ui_in[0] is held externally" in n for n in result["notes"])
    assert result["pass"] is False


def test_sdk_missing_is_reported_and_ui_in_still_tested():
    model = BoardModel(standard_wires(), project="quiet")
    result, _log = run_simulated(model, sdk=False)
    assert set(statuses(result, "ui_in").values()) == {"ok"}
    assert result["asic_loopback"] is False
    assert result["pass"] is False  # loopback was requested and is unavailable
    assert any("SDK init failed" in n for n in result["notes"])


def test_unstable_readings_abort():
    class NoisyHat(FakeHat):
        def __init__(self, model):
            super().__init__(model)
            self.n = 0

        def read_all(self):
            self.n += 1
            values = super().read_all()
            values[16] = self.n % 2
            return values

    model = BoardModel(standard_wires())
    with pytest.raises(ttw.UnstableReading):
        run_simulated(model, argv=["--asic-project", "none"], hat_cls=NoisyHat)


def test_discover_mode_reports_without_verdict(capsys):
    model = BoardModel(standard_wires())
    result, _log = run_simulated(model, argv=["--discover"])
    ttw.report(result, discover=True)
    out = capsys.readouterr().out
    assert "signals reached a Pi GPIO" in out
    assert "Wiring check" not in out
