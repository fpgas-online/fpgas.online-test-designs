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

import contextlib
import importlib.util
import itertools
import pathlib
import socket
import sys
import threading
import types

import pytest

_MOD_PATH = pathlib.Path(__file__).parents[1] / "designs" / "_host" / "tt_pmod_wiring.py"
_spec = importlib.util.spec_from_file_location("tt_pmod_wiring", _MOD_PATH)
ttw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ttw)

RP2040 = ttw.CONTROLLERS["rp2040"]
JA, JB, JC = (ttw.PMOD_HAT_PORTS[p] for p in ("JA", "JB", "JC"))


# -- Electrical model ----------------------------------------------------------------


HAT_GROUND = 0  # a node on the HAT's ground: Pi GPIO0 is on no HAT port, so it stands for ground in `wires`


class BoardModel:
    """Nets between RP2 GPIOs, the ASIC and Pi GPIOs.

    *wires* maps an RP2 data GPIO to the Pi GPIOs its ribbon line reaches;
    *extra_shorts* joins further node pairs (``"pi:16"``, ``"rp2:9"``).
    The ASIC drives ``uo_out`` at the RP2-side node of each ``uo_out`` GPIO
    and, when a project has ``uio_oe`` set, ``uio`` likewise. Pi GPIO2/3
    carry the board's fixed 1.8k pull-ups, which beat every weak pull.
    """

    UI, UIO, UO = RP2040["ui_in"], RP2040["uio"], RP2040["uo_out"]

    def __init__(
        self, wires, project="factory", extra_shorts=(), held_ui_in=(), hard_ui_in=(), dip_level=0, grounded=()
    ):
        self.wires = wires
        self.project = project  # what the chip is running right now
        self.rp2 = {g: ("in", None) for g in self.UI + self.UIO + self.UO}
        self.pi_bias = "down"
        self.pi_pull_up = set()
        self.held_ui_in = set(held_ui_in)  # ui_in bits a DIP switch pulls to dip_level through a resistor
        self.dip_level = dip_level  # 1: a switch that is on ties its line to 3.3 V (the demo board's own)
        self.grounded = set(grounded) | {HAT_GROUND}  # Pi GPIOs whose HAT line is shorted to ground
        self.hard_ui_in = set(hard_ui_in)  # ui_in bits shorted to a rail (low)
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
        medium = {}  # beats pulls, loses to outputs: a DIP switch through its resistor
        for node in self.parent:
            net = self.net(node)
            kind, gpio = node.split(":")
            gpio = int(gpio)
            if kind == "pi" and gpio in self.grounded:
                strong.setdefault(net, []).insert(0, ("rail", gpio, 0))  # ground always wins
            if kind == "rp2":
                mode, val = self.rp2[gpio]
                if gpio in self.UI and self.UI.index(gpio) in self.held_ui_in:
                    medium[net] = self.dip_level
                if gpio in self.UI and self.UI.index(gpio) in self.hard_ui_in:
                    strong.setdefault(net, []).insert(0, ("rail", gpio, 0))  # a rail always wins
                if mode == "out":
                    strong.setdefault(net, []).append(("rp2", gpio, val))
                elif mode == "tx":  # transmitting a label: idle high between frames
                    strong.setdefault(net, []).append(("rp2", gpio, 1))
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
        return strong, weak, fixed_up, medium

    def resolve(self):
        """Settle every net; record contention at the settled state; return {net: level}.

        Contention is judged only once the nets have settled: the chip's
        combinational ``uo_out = uio_in`` lags the RP2 by one iteration, which
        is the propagation delay, not a fight.
        """
        levels = dict(self.levels)
        for _ in range(10):
            strong, weak, fixed_up, medium = self._drivers(levels)
            new = {}
            for node in self.parent:
                net = self.net(node)
                if net in new:
                    continue
                if net in strong:
                    new[net] = strong[net][0][2]
                elif net in medium:
                    new[net] = medium[net]
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
        strong, _weak, _fixed, _medium = self._drivers(levels)
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


def standard_wires(controller="rp2040", cabling="fpga", swap=None, unplug=(), drop=()):
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


def asic_wires():
    """The ASIC hosts' cabling as measured on 4 Sep 2026: JA -> ui_in, JB -> uio, JC -> uo_out."""
    return standard_wires(cabling="asic")


def make_fake_scanner(model):
    """What identify_pmod_pins' decoder would see on each Pi line of *model*.

    A line carries the label of a transmitting RP2 pin on its net, or, with
    the factory test and ui_in[0] low, the label on the uio net that the
    chip echoes onto that uo_out pin. Two different labels decode as garbage.
    """

    def scan():
        levels = model.resolve()
        ui0 = levels.get(model.net(f"rp2:{model.UI[0]}"), 0)
        ui0_tx = model.rp2[model.UI[0]][0] == "tx"
        chip_nodes = {f"rp2:{g}" for g in model.UIO + model.UO}
        decoded = {}
        for g in ttw.ALL_HAT_GPIOS:
            net = model.net(f"pi:{g}")
            if model.project == "factory" and ui0_tx and any(model.net(n) == net for n in chip_nodes):
                # The chip toggles uio_oe/uo_out with ui_in[0]; against the
                # decoder's pull-up that reads as garbage (seen on hardware).
                decoded[g] = "?chip"
                continue
            labels = set()
            for gpio, (mode, val) in model.rp2.items():
                if mode == "tx" and model.net(f"rp2:{gpio}") == net:
                    labels.add(val)
            if model.project == "factory" and not ui0:
                for k in range(8):
                    if model.net(f"rp2:{model.UO[k]}") == net:
                        unet = model.net(f"rp2:{model.UIO[k]}")
                        for gpio, (mode, val) in model.rp2.items():
                            if mode == "tx" and model.net(f"rp2:{gpio}") == unet:
                                labels.add(val)
            if len(labels) == 1:
                decoded[g] = labels.pop()
            elif labels:
                decoded[g] = "?" + "/".join(sorted(labels))
            else:
                decoded[g] = None
        return decoded

    return scan


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
            if cmd == "txid":
                for a in args:
                    g, label = a.split("=")
                    m.rp2[int(g)] = ("tx", label)
                m.resolve()  # a fight would be recorded here
                return ["TTW OK started mem_free=51000"]
            if cmd == "stop":
                for g, (mode, _val) in list(m.rp2.items()):
                    if mode == "tx":
                        m.rp2[g] = ("out", 1)
                return ["TTW OK stopped"]
            if cmd == "release":
                self._release()
                return ["TTW OK"]
            if cmd == "creset":
                self.creset = int(args[0])
                return ["TTW OK"]
            if cmd == "group":  # the pins change together: no state in between
                value, gs = int(args[0]), [int(g) for g in args[1:]]
                for g in gs:
                    m.rp2[g] = ("out", value)
                m.resolve()
                return ["TTW VALS " + " ".join(str(m.rp2_read(g)) for g in gs)]
            if cmd == "ungroup":
                for g in args:
                    m.rp2[int(g)] = ("in", None)
                return ["TTW OK"]
            if cmd == "mem":
                return ["TTW VAL mem 60000"]
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
        sock.sendall(b"TTW READY mem_free=60000\n")
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

    def close(self):
        self.model.pi_bias = "none"
        self.model.pi_pull_up = set()

    def read_all(self):
        return self.model.pi_read_all()


def run_simulated(
    model, argv=(), projects=("tt_um_factory_test",), sdk=True, firmware_cls=FakeFirmware, hat_cls=FakeHat, pin_id=False
):
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
    scanner = make_fake_scanner(model) if pin_id else None
    try:
        result = ttw.run_wiring_test(link, hat_cls(model), args, log=log.append, pin_scanner=scanner)
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


def test_shared_lines_per_cabling_profile():
    # fpga cabling: the HAT's JA2-4/JB2-4 short ties uio[1:3] to the chip's uo_out[1:3].
    assert ttw.latch_bits("fpga") == [1, 2, 3]
    assert ttw.shared_partners("fpga")["uio[1]"] == []
    # asic cabling: the same short ties ui_in[1:3] to uio[1:3], both RP2-driven.
    assert ttw.latch_bits("asic") == []
    assert ttw.shared_partners("asic")["ui_in[1]"] == ["uio[1]"]
    assert ttw.shared_partners("asic")["uio[3]"] == ["ui_in[3]"]
    assert ttw.connected_uio("asic", "ui_in[2]") == [2]
    assert ttw.connected_uio("fpga", "ui_in[2]") == []


def test_expected_map_matches_documented_cabling():
    exp = ttw.expected_map("fpga", asic_loopback=False)
    # docs/hardware/tt-fpga-pin-mapping.md: ui_in[0] = JC1 = GPIO16 ... ui_in[7] = JC10 = GPIO6
    assert [sorted(exp[f"ui_in[{k}]"]) for k in range(8)] == [[16], [14], [15], [17], [4], [12], [5], [6]]
    assert [sorted(exp[f"uio[{k}]"]) for k in range(8)] == [[7], [10], [9], [11], [26], [13], [3], [2]]
    with_asic = ttw.expected_map("fpga", asic_loopback=True)
    assert with_asic["uio[0]"] == {7, 8}  # JB1 direct + JA1 through the chip
    assert with_asic["uio[1]"] == {10}  # JB2 and JA2 are the same Pi line
    assert with_asic["uio[7]"] == {2, 18}
    assert ttw.expected_direct("fpga")["uio[0]"] == 7
    # asic cabling as measured on 4 Sep 2026: ui_in[1] drives the shared line
    # with uio[1], so the chip echoes it onto uo_out[1] = JC2 too.
    asic = ttw.expected_map("asic", asic_loopback=True)
    assert asic["ui_in[0]"] == {8}
    assert asic["ui_in[1]"] == {10, 14}
    assert asic["uio[1]"] == {10, 14}
    assert asic["uio[4]"] == {26, 4}
    assert ttw.expected_followers("asic", True, "ui_in[1]") == {"uio[1]", "uo_out[1]"}
    assert ttw.expected_followers("fpga", True, "uio[4]") == {"uo_out[4]"}


def test_choose_cabling():
    fpga_lines = ttw.profile_lines("fpga")
    observed = {f"ui_in[{k}]": {fpga_lines[f"ui_in[{k}]"]} for k in range(8)}
    assert ttw.choose_cabling(observed, {})[0] == "fpga"
    asic_lines = ttw.profile_lines("asic")
    observed = {f"ui_in[{k}]": {asic_lines[f"ui_in[{k}]"]} for k in range(8)}
    assert ttw.choose_cabling(observed, {})[0] == "asic"


def test_pin_id_labels_and_expectations():
    assert ttw.pin_id_label("ui_in[3]") == "UI3" and ttw.pin_id_label("uio[7]") == "IO7"
    assert ttw.expected_labels("fpga", True, {"uio[0]": "IO0"}) == {7: "IO0", 8: "IO0"}
    assert ttw.expected_labels("fpga", False, {"uio[0]": "IO0"}) == {7: "IO0"}
    assert ttw.expected_labels("asic", True, {"ui_in[1]": "UI1"}) == {10: "UI1", 14: "UI1"}
    ok, rows = ttw.evaluate_pin_id({7: "IO0", 8: "IO0"}, {7: "IO0", 8: "IO0"})
    assert ok and {r["status"] for r in rows} == {"ok", "idle"}
    by = {
        r["gpio"]: r["status"]
        for r in ttw.evaluate_pin_id({7: None, 8: "?IOx", 16: "UI0", 14: "IO0"}, {7: "IO0", 8: "IO0", 16: "IO0"})[1]
    }
    assert by[7] == "open" and by[8] == "garbled" and by[16] == "wrong" and by[14] == "unexpected"


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
    expected = ttw.expected_map("fpga", False)
    observed = {name: set(pins) for name, pins in expected.items() if name.startswith("ui_in")}
    ok, rows, _shorts = ttw.evaluate(observed, expected, set(observed), set(expected))
    assert not ok
    assert {r["status"] for r in rows if r["signal"].startswith("uio")} == {"untested"}
    ok, _rows, _ = ttw.evaluate(observed, expected, set(observed), set(observed))
    assert ok


def test_evaluate_cross_checks_override_ok():
    expected = ttw.expected_map("fpga", True)
    observed = {n: set(p) for n, p in expected.items()}
    direct = ttw.expected_direct("fpga")
    # Reverse walk says uio[0]'s own line is JA1, not JB1 -> ribbons swapped.
    _ok, rows, _ = ttw.evaluate(
        observed, expected, set(observed), set(observed), direct=direct, reverse={"uio[0]": {8}}
    )
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
    assert result["cabling"] == "fpga"
    docs = ttw.format_docs_table({k: set(v) for k, v in result["observed"].items()}, "rp2040", "fpga", True)
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


def test_factory_project_unavailable_stops_a_strict_test():
    model = BoardModel(standard_wires(), project="drives_uio")
    with pytest.raises(ttw.ProtocolError, match="the chip's tt_um_factory_test could not be selected"):
        run_simulated(model, projects=())
    assert model.contentions == []


def test_factory_project_unavailable_without_strict_is_noted():
    model = BoardModel(standard_wires(), project="drives_uio")
    result, _log = run_simulated(model, argv=["--no-strict"], projects=())
    assert result["asic_loopback"] is False
    assert any("could not select tt_um_factory_test" in n for n in result["notes"])
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
    # The shorted partner is found held by ui_in[0]'s output in the pre-check
    # (or reads as one of the fault statuses); either way it is not OK.
    assert rows["ui_in[3]"]["status"] in ("short", "open", "miswired", "contention", "untested")
    # Two RP2 outputs fight through a shorted ribbon during a walk; that is
    # inherent to any walking-1 test and harmless at the RP2040's drive.
    # The chip must never be one of the parties.
    assert all(d[0] == "rp2" for c in model.contentions for d in c)


def test_hard_held_ui_in0_disables_loopback():
    model = BoardModel(standard_wires(), hard_ui_in={0})
    result, _log = run_simulated(model)
    assert result["asic_loopback"] is False
    assert any("ui_in[0] is held externally" in n for n in result["notes"])
    assert result["pass"] is False


def test_no_sdk_stops_a_strict_test_before_any_pin_is_driven():
    """The boot check needs the chip's loopback: an SDK it cannot use stops the test (exit 2), not a half test."""
    model = BoardModel(standard_wires(), project="quiet")
    with pytest.raises(ttw.ProtocolError, match="the board's SDK could not be used: 'sdk init' -> sdk: ImportError"):
        run_simulated(model, sdk=False)
    assert all(mode == "in" for mode, _ in model.rp2.values())  # nothing was driven


def test_sdk_missing_without_strict_is_reported_and_ui_in_still_tested():
    model = BoardModel(standard_wires(), project="quiet")
    result, _log = run_simulated(model, argv=["--no-strict"], sdk=False)
    assert set(statuses(result, "ui_in").values()) == {"ok"}
    assert result["asic_loopback"] is False
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


def test_asic_cabling_is_detected_and_passes():
    # The ASIC hosts' cabling: JA -> ui_in, JB -> uio, JC -> uo_out. The HAT
    # short now ties ui_in[1:3] to uio[1:3]; the partner is released while
    # the other is driven, so two RP2 outputs never fight.
    model = BoardModel(asic_wires(), project="drives_uio")
    result, _log = run_simulated(model)
    assert result["cabling"] == "asic"
    assert result["pass"] is True, [r for r in result["rows"] if r["status"] != "ok"]
    assert {r["status"] for r in result["rows"]} == {"ok"}
    assert result["latch"] == {}
    assert model.contentions == []
    rows = rows_by_name(result)
    assert rows["ui_in[1]"]["observed"] == [10, 14]  # shared JA2/JB2 line, and JC2 through the chip
    assert rows["uio[4]"]["observed"] == [4, 26]
    docs = ttw.format_docs_table({k: set(v) for k, v in result["observed"].items()}, "rp2040", "asic", True)
    assert "| uo_out[4] | 13          | JC7          | 4        | factory-test loopback via uio[4] |" in docs
    assert "| uo_out[1] | 6           | JC2          | 14       | factory-test loopback via uio[1] |" in docs


def test_asic_cabling_against_the_fpga_profile_fails():
    model = BoardModel(asic_wires())
    result, _log = run_simulated(model, argv=["--cabling", "fpga"])
    assert result["cabling"] == "fpga"
    assert result["pass"] is False
    assert rows_by_name(result)["ui_in[0]"]["status"] == "miswired"


@pytest.mark.parametrize("wires,cabling", [(standard_wires(), "fpga"), (asic_wires(), "asic")])
def test_pin_id_rounds_decode_every_name(wires, cabling):
    model = BoardModel(wires, project="drives_uio")
    result, _log = run_simulated(model, pin_id=True)
    assert result["cabling"] == cabling
    assert result["pin_id_ok"] is True and result["pass"] is True
    lines = ttw.profile_lines(cabling)
    assert list(result["pin_id"]) == ["ui_in", "ui_in[0]", "uio"]
    ui = result["pin_id"]["ui_in"]
    assert ui["decoded"][lines["ui_in[3]"]] == "UI3"
    assert result["pin_id"]["ui_in[0]"]["decoded"][lines["ui_in[0]"]] == "UI0"
    uio = result["pin_id"]["uio"]
    assert uio["decoded"][lines["uio[4]"]] == "IO4"
    assert uio["decoded"][lines["uo_out[4]"]] == "IO4"  # echoed through the chip
    assert {r["status"] for r in ui["rows"]} <= {"ok", "idle"}
    assert {r["status"] for r in uio["rows"]} <= {"ok", "idle"}
    assert model.contentions == []


def test_pin_id_shares_the_reverse_walks_blind_spot_on_swapped_ribbons():
    # A JA/JB swap gives the same label on the same lines (direct vs echoed),
    # so pin-id alone passes; the reverse walk in the same run still fails it.
    model = BoardModel(swapped_ja_jb_wires())
    result, _log = run_simulated(model, pin_id=True)
    assert result["pin_id_ok"] is True
    assert result["pass"] is False


def test_pin_id_reports_an_open_line():
    model = BoardModel(standard_wires(drop=(RP2040["ui_in"][5],)))
    result, _log = run_simulated(model, pin_id=True)
    rows = {r["gpio"]: r for r in result["pin_id"]["ui_in"]["rows"]}
    assert rows[12]["status"] == "open" and rows[12]["expected"] == "UI5"
    assert result["pin_id_ok"] is False


def test_discover_mode_reports_without_verdict(capsys):
    model = BoardModel(standard_wires())
    result, _log = run_simulated(model, argv=["--discover"])
    ttw.report(result, discover=True)
    out = capsys.readouterr().out
    assert "signals reached a Pi GPIO" in out
    assert "Wiring check" not in out


# -- The boot check's line: WIRING: names the ribbon and the pin -----------------------------------------

ASIC = ["--cabling", "asic"]  # as the boot check runs it: the cabling the boards have
WHERE = "ui_in on HAT JA, uio on HAT JB, uo_out on HAT JC"


def asic_verdict(wires, argv=ASIC, pin_id=False, **model):
    result, _log = run_simulated(BoardModel(wires, **model), argv=argv, pin_id=pin_id)
    return ttw.verdict(result)


def test_the_boards_cabling_passes_and_says_where_every_ribbon_is():
    code, line = asic_verdict(asic_wires(), project="drives_uio", pin_id=True)
    assert (code, line) == (
        0,
        f"all 24 Pmod signals reached the Pi where they should: {WHERE} (uo_out through the chip)",
    )


def placed(ports, offset=()):
    """Wires for ribbons on HAT `ports` ({group: port}); the groups in offset turned round and one position over
    (Pmod pin n on HAT pin 12 - n; pins 1 and 7 on the HAT's ground, as the 4 Sep fleet record found them)."""
    wires = {}
    for group, port in ports.items():
        for k in range(8):
            pin = ttw.PMOD_PIN_NUMBERS[k]
            if group in offset:
                pin = 12 - pin
                if pin not in ttw.PMOD_PIN_NUMBERS:
                    wires[RP2040[group][k]] = {HAT_GROUND}
                    continue
            wires[RP2040[group][k]] = {ttw.PMOD_HAT_PORTS[port][ttw.PMOD_PIN_NUMBERS.index(pin)]}
    return wires


def ours(contentions):
    """The fights an RP2040 pin of ours is in: those of the chip's outputs against a wire's fault (one on ground,
    two bridged) are the fault's, and happen whatever the test does."""
    return [c for c in contentions if any(d[0] == "rp2" for d in c)]


def wiring_line(wires, pin_id=True):
    """(exit, WIRING: line, our fights) for `wires`, run as the boot check runs it, with pin-id."""
    model = BoardModel(wires, project="drives_uio")
    try:
        result, _log = run_simulated(model, argv=ASIC, pin_id=pin_id)
        code, line = ttw.verdict(result)
    except ttw.Unclear:
        code, line = 1, "UNCLEAR"
    except ttw.ProtocolError as e:
        code, line = 2, f"the wiring could not be tested: {e}"
    return code, line, ours(model.contentions)


@pytest.mark.parametrize("wires, line", [
    (standard_wires(cabling="asic", drop=(RP2040["ui_in"][5],)),
     "the ui_in ribbon (to HAT JA): ui_in[5] (Pmod pin 8) did not reach HAT JA pin 8"),
    # on a line the HAT shares (JA/JB pins 2-4): the uo_out wire it reaches through the chip is not blamed
    (standard_wires(cabling="asic", drop=(RP2040["ui_in"][2],)),
     "the ui_in ribbon (to HAT JA): ui_in[2] (Pmod pin 3) did not reach HAT JA/JB pin 3"),
    (standard_wires(cabling="asic", drop=(RP2040["uio"][2],)),
     "the uio ribbon (to HAT JB): uio[2] (Pmod pin 3) did not reach HAT JA/JB pin 3"),
    (standard_wires(cabling="asic", drop=(RP2040["uo_out"][5],)),
     "the uo_out ribbon (to HAT JC): uo_out[5] (Pmod pin 8) did not reach HAT JC pin 8"),
    (standard_wires(cabling="asic", swap=(RP2040["ui_in"][4], RP2040["ui_in"][5])),
     "the ui_in ribbon (to HAT JA): ui_in[4] (Pmod pin 7) did not reach HAT JA pin 7: it reached HAT JA pin 8; "
     "ui_in[5] (Pmod pin 8) did not reach HAT JA pin 8: it reached HAT JA pin 7"),
    (standard_wires(cabling="asic", drop=(RP2040["ui_in"][0], *RP2040["ui_in"][4:6])),
     "the ui_in ribbon (to HAT JA): ui_in[0] (Pmod pin 1) did not reach HAT JA pin 1; ui_in[4] (Pmod pin 7) did "
     "not reach HAT JA pin 7; and 1 more"),
    *[(standard_wires(cabling="asic", unplug=(g,)),
       f"the {g} ribbon (to HAT {p}): none of its signals reached the Pi (not plugged in, or broken)")
      for g, p in (("ui_in", "JA"), ("uio", "JB"), ("uo_out", "JC"))],
    (placed({"ui_in": "JB", "uio": "JA", "uo_out": "JC"}),
     "the ui_in and uio ribbons are on each other's HAT ports (JB and JA): swap them"),
    (placed({"ui_in": "JA", "uio": "JC", "uo_out": "JB"}),
     # ui_in[1:3] are then held by the chip's uo_out (the HAT joins JB2-4 to JA2-4): not driven, said
     "the uio and uo_out ribbons are on each other's HAT ports (JC and JB): swap them; and some ui_in signals could "
     "not be tested until then"),
    (placed({"ui_in": "JC", "uio": "JB", "uo_out": "JA"}),
     "the ui_in and uo_out ribbons are on each other's HAT ports (JC and JA): swap them; and some uio signals could "
     "not be tested until then"),
    # the TT04 board of 4 Sep: all three turned round, ui_in and uo_out on each other's ports. The chip's uo_out
    # then drives the uio lines it lands on, so those are not driven: ui_in is named, the rest after its reseat
    (placed({"ui_in": "JC", "uio": "JB", "uo_out": "JA"}, offset=("ui_in", "uio", "uo_out")),
     "the ui_in ribbon is plugged in turned round and one position over (ui_in on HAT JC (it goes on JA)): Pmod "
     "pin n arrives on HAT pin 12-n, and Pmod pins 1 and 7 are on the HAT's ground; plug it in the right way "
     "round, Pmod pin 1 to HAT pin 1; and some uio and uo_out signals could not be tested until then"),
    # review 2: uo_out alone, and with ui_in, turned round (its lines are what uio reaches through the chip)
    (placed({"ui_in": "JA", "uio": "JB", "uo_out": "JC"}, offset=("uo_out",)),
     "the uo_out ribbon is plugged in turned round and one position over (uo_out on HAT JC): Pmod pin n arrives on "
     "HAT pin 12-n, and Pmod pins 1 and 7 are on the HAT's ground; plug it in the right way round, Pmod pin 1 to "
     "HAT pin 1"),
    # ui_in[0] then sits on ground, so the chip's loopback cannot be used: uo_out is said untested until then
    (placed({"ui_in": "JA", "uio": "JB", "uo_out": "JC"}, offset=("ui_in", "uo_out")),
     "the ui_in ribbon is plugged in turned round and one position over (ui_in on HAT JA): Pmod pin n arrives on "
     "HAT pin 12-n, and Pmod pins 1 and 7 are on the HAT's ground; plug it in the right way round, Pmod pin 1 to "
     "HAT pin 1; and some uio and uo_out signals could not be tested until then"),
    (placed({"ui_in": "JA", "uio": "JB", "uo_out": "JC"}, offset=("ui_in",)),
     "the ui_in ribbon is plugged in turned round and one position over (ui_in on HAT JA): Pmod pin n arrives on "
     "HAT pin 12-n, and Pmod pins 1 and 7 are on the HAT's ground; plug it in the right way round, Pmod pin 1 to "
     "HAT pin 1; and some uio and uo_out signals could not be tested until then"),
])  # fmt: skip
def test_each_wrong_wiring_has_its_own_line_and_no_two_parties_ever_drive_one_net(wires, line):
    assert wiring_line(wires) == (1, line, [])


def test_the_boards_cabling_passes_with_pin_id_and_no_contention():
    code, line, fights = wiring_line(asic_wires())
    assert (code, fights) == (0, []) and line.startswith("all 24 Pmod signals reached the Pi where they should")


def test_a_bit_something_holds_is_never_driven_and_fails_the_board_named():
    """A DIP switch that is on (TT08 and TT03p5 had some on 4 Sep) or a hard short holds a ui_in line: it is never
    driven (it could be a chip output), and the board fails, naming the bit and the switch advice."""
    for kind in ("held_ui_in", "hard_ui_in"):
        model = BoardModel(asic_wires(), project="drives_uio", **{kind: {5}})
        result, _log = run_simulated(model, argv=ASIC)
        assert rows_by_name(result)["ui_in[5]"]["status"] == "untested" and model.contentions == []
        assert all(rows_by_name(result)[f"ui_in[{k}]"]["status"] == "ok" for k in range(8) if k != 5)
        code, line = ttw.verdict(result)
        assert code == 1 and line == (
            "the ui_in ribbon (to HAT JA): ui_in[5] (Pmod pin 8) is held low on the demo board (something drives it "
            "low: a short to ground, or a chip output a wrong ribbon joins to it)")  # fmt: skip


def test_a_factory_test_that_does_not_confirm_stops_the_test():
    class StubbornFirmware(FakeFirmware):  # says it selected the project; the chip keeps driving uio
        def handle(self, line):
            if line.startswith("sdk project"):
                return ["TTW OK enabled=tt_um_factory_test"]
            return super().handle(line)

    class QuietFirmware(FakeFirmware):  # a project that lets uio float but does not loop it to uo_out
        def handle(self, line):
            if line.startswith("sdk project"):
                self.model.project = "quiet"
                return ["TTW OK enabled=tt_um_factory_test"]
            return super().handle(line)

    # a uo_out that does not follow uio is a reading a bridge also gives (exit 1, the unclear line); a factory
    # test that could not even be tried is the chip's or the SDK's (exit 2)
    for firmware, raised, why in ((StubbornFirmware, ttw.ProtocolError, "could not be confirmed: only 0 u"),
                                  (QuietFirmware, ttw.ProtocolError, "only 0 uo_out bits followed")):  # fmt: skip
        model = BoardModel(asic_wires(), project="drives_uio")
        with pytest.raises(raised, match=why):
            run_simulated(model, argv=ASIC, firmware_cls=firmware)
        assert model.contentions == []
        # by hand, --no-strict, it goes on without the loopback, never driving ui_in[0] against the chip
        result, _log = run_simulated(model, argv=[*ASIC, "--no-strict"], firmware_cls=firmware)
        assert result["asic_loopback"] is False and model.contentions == []


def test_a_name_not_read_on_a_line_is_named_by_the_signal_that_sent_it():
    result = {"cabling": "asic", "pin_id": {"uio": {"transmitting": {"uio[4]": "IO4"}, "rows": [
        {"gpio": 26, "expected": "IO4", "decoded": None, "status": "open"},
        {"gpio": 4, "expected": "IO4", "decoded": "?xy", "status": "garbled"},
        {"gpio": 7, "expected": None, "decoded": "IO4", "status": "unexpected"},
    ]}}}  # fmt: skip
    assert [(f["group"], f["text"]) for f in ttw.pin_id_faults(result)] == [
        ("uio", "uio[4] (Pmod pin 7): its name was not read on HAT JB pin 7 (read: nothing)"),
        ("uo_out", "uo_out[4] (Pmod pin 7): its name was not read on HAT JC pin 7 (read: (garbled))"),
        ("", "HAT JB pin 1 also heard IO4"),
    ]


def test_hat_pins_are_named_as_the_hat_s_connectors_are():
    assert (
        ttw.hat_pin(8) == "HAT JA pin 1" and ttw.hat_pin(10) == "HAT JA/JB pin 2" and ttw.hat_pin(6) == "HAT JC pin 10"
    )


# -- The pin-id decoder is the one the package installs -----------------------------------------------


def test_the_pin_id_scanner_calls_the_real_decoder_as_it_is_now(monkeypatch):
    """PR #15 called identify_pin(reader, attempts=5), which the decoder no longer takes: a fake scanner hid it."""
    pinid = ttw.load_sibling("identify_pmod_pins")
    assert pinid is not None and pinid.__file__.endswith("designs/pmod-pin-id/host/identify_pmod_pins.py")
    opened = []

    class Reader:
        def __init__(self, gpio, chip):
            self.gpio = gpio

        def open(self):
            opened.append(self.gpio)

        def capture_edges(self, seconds):
            return []  # a silent line

        def close(self):
            pass

    monkeypatch.setattr(pinid, "GpioReader", Reader)
    monkeypatch.setattr(pinid, "detect_gpio_chip", lambda: "/dev/gpiochip0")
    assert ttw.make_pin_id_scanner(pinid)() == dict.fromkeys(ttw.ALL_HAT_GPIOS)
    assert opened == ttw.ALL_HAT_GPIOS


def test_the_pinctrl_helpers_are_found_next_to_the_script():
    pins = ttw.load_sibling("tt_dip_switches")
    assert pins is not None and callable(pins.set_pins) and callable(pins.pinctrl)


# -- The Pi is put back as it was -------------------------------------------------------------------------


class Pinctrl:
    """pinctrl as tt_dip_switches calls it: `get` answers from `state`, `set` changes it and is recorded."""

    def __init__(self, state, unreadable_pull=False):
        self.state, self.sets, self.unreadable_pull = dict(state), [], unreadable_pull

    def __call__(self, args, run=None):
        if args[0] == "get":
            lines = []
            for g in map(int, args[1].split(",")):
                func, pull, level = self.state[g]
                pull = "--" if self.unreadable_pull else pull
                lines.append(f"{g}: {func}    {pull} | {level} // GPIO{g} = x")
            return 0, "\n".join(lines) + "\n"
        self.sets.append(args[1:])
        return 0, ""


def _env(monkeypatch, pinctrl):
    pins = ttw.load_sibling("tt_dip_switches")
    monkeypatch.setattr(pins, "pinctrl", pinctrl)
    calls = []
    monkeypatch.setattr(ttw, "run_quiet", lambda cmd, check=False: calls.append(cmd) or _Done())
    monkeypatch.setattr(ttw.os, "geteuid", lambda: 0)
    env = ttw.PiEnvironment(manage_daemon=False, log=lambda *_: None, pins=pins)
    return env, calls


class _Done:
    returncode, stdout, stderr = 0, "", ""


BEFORE = {g: ("ip", "pu" if g < 9 else "pd", "hi" if g < 9 else "lo") for g in ttw.ALL_HAT_GPIOS}
BEFORE[14] = BEFORE[15] = ("a0", "pn", "hi")  # the console UART


def test_every_hat_gpio_is_set_back_to_its_function_and_pull(monkeypatch):
    pinctrl = Pinctrl(BEFORE)
    env, _calls = _env(monkeypatch, pinctrl)
    env.enter()
    assert pinctrl.sets == [] and env.assumed_pulls == {}
    assert env.leave() == []
    assert sorted(pinctrl.sets) == sorted([str(g), f, p] for g, (f, p, _) in BEFORE.items())
    assert ["14", "a0", "pn"] in pinctrl.sets


def _dt_node(path, **props):
    """A device-tree node under `path`, its properties as /proc/device-tree has them (cells big-endian u32)."""
    path.mkdir(parents=True)
    for name, value in props.items():
        name = name.replace("_", ",", 1) if name.startswith("brcm_") else name.replace("_", "-")
        data = value if isinstance(value, bytes) else b"".join(v.to_bytes(4, "big") for v in value)
        (path / name).write_bytes(data)


def fake_device_tree(root):
    """A Pi 3's: the GPIO controller with uart0's pins (TX no pull, RX up) and spi0's (no pull given), uart0
    enabled, spi0 enabled, i2c1 disabled with a pull-up group."""
    gpio = root / "soc" / "gpio@7e200000"
    _dt_node(gpio / "uart0_pins", brcm_pins=[14, 15], brcm_function=[4, 4], brcm_pull=[0, 2], phandle=[1])
    _dt_node(gpio / "spi0_pins", brcm_pins=[9, 10, 11], brcm_function=[4], phandle=[2])
    _dt_node(gpio / "i2c1_pins", brcm_pins=[2, 3], brcm_function=[4], brcm_pull=[2], phandle=[3])
    _dt_node(root / "soc" / "serial@7e201000", pinctrl_0=[1], pinctrl_names=b"default\0", status=b"okay\0")
    _dt_node(root / "soc" / "spi@7e204000", pinctrl_0=[2], status=b"okay\0")
    _dt_node(root / "soc" / "i2c@7e804000", pinctrl_0=[3], status=b"disabled\0")
    return root


def test_the_running_device_tree_says_the_pulls_of_the_pins_its_enabled_nodes_take(tmp_path):
    found = ttw.device_tree_pulls(fake_device_tree(tmp_path / "dt"))
    assert found == {14: ("pn", "the device tree's uart0_pins pins of serial@7e201000"),
                     15: ("pu", "the device tree's uart0_pins pins of serial@7e201000")}  # fmt: skip


def test_a_pull_no_enabled_node_sets_is_the_bcm2835_power_on_default(tmp_path):
    pulls = ttw.known_pulls([2, 8, 9, 14, 15, 26], fake_device_tree(tmp_path / "dt"))
    assert {g: p for g, (p, _why) in pulls.items()} == {2: "pu", 8: "pu", 9: "pd", 14: "pn", 15: "pu", 26: "pd"}
    assert pulls[2][1] == pulls[26][1] == "the BCM2835 power-on default"
    # no device tree to read: every pin its default
    assert ttw.known_pulls([3, 10], tmp_path / "none") == {3: ("pu", "the BCM2835 power-on default"),
                                                            10: ("pd", "the BCM2835 power-on default")}  # fmt: skip


def test_a_pi_3_s_unreadable_pulls_are_set_to_known_ones_and_said(monkeypatch, tmp_path):
    monkeypatch.setattr(ttw, "DEVICE_TREE", fake_device_tree(tmp_path / "dt"))
    monkeypatch.setattr(ttw.known_pulls, "__defaults__", (ttw.DEVICE_TREE,))
    pinctrl = Pinctrl(BEFORE, unreadable_pull=True)
    env, _calls = _env(monkeypatch, pinctrl)
    logged = []
    env.log = logged.append
    env.enter()
    assert set(env.assumed_pulls) == set(ttw.ALL_HAT_GPIOS)
    assert env.leave() == []
    pull = {int(s[0]): s[2] for s in pinctrl.sets}
    assert pull == {g: ("pu" if g <= 8 else "pd") for g in ttw.ALL_HAT_GPIOS if g not in (14, 15)} | {
        14: "pn",
        15: "pu",
    }
    assert ["14", "a0", "pn"] in pinctrl.sets and ["15", "a0", "pu"] in pinctrl.sets
    (said,) = [line for line in logged if line.startswith("PULLS: ")]
    assert "the BCM2835 power-on default: GPIO2 pu, GPIO3 pu" in said
    assert "the device tree's uart0_pins pins of serial@7e201000: GPIO14 pn, GPIO15 pu" in said


def test_an_output_whose_level_cannot_be_read_is_refused_before_anything_changes(monkeypatch):
    pinctrl = Pinctrl({**BEFORE, 26: ("op", "pd", "--")})
    env, calls = _env(monkeypatch, pinctrl)
    with pytest.raises(RuntimeError, match="cannot read the level of output GPIO26"):
        env.enter()
    assert calls == [] and pinctrl.sets == []
    assert env.leave() == []  # nothing to put back


def test_what_cannot_be_put_back_is_said(monkeypatch):
    pinctrl = Pinctrl(BEFORE)
    env, _calls = _env(monkeypatch, pinctrl)
    env.enter()
    monkeypatch.setattr(env.pins, "pinctrl", lambda args, run=None: (1, "pinctrl: no such pin"))
    assert all(f.startswith("GPIO") and "could not be set" in f for f in env.leave())


# -- main: the line, the exit, and a stop ------------------------------------------------------------


class _Env:
    def __init__(self, *a, **k):
        self.pins, self.left = object(), []

    def enter(self):
        pass

    def leave(self):
        self.left.append(True)
        return _Env.faults


class _Hat:
    chip_path = "/dev/gpiochip-fake"

    def __init__(self, gpios):
        pass

    def open(self, bias):
        pass

    def close(self):
        pass


def _main(monkeypatch, capsys, measure, faults=(), heap=60000, mem=None, restore=None, fallbacks=None, start=None):
    """main() with the Pi and the board replaced: `measure` stands in for run_wiring_test; `restore` is what
    "sdk restore" answers (an exception is raised); `fallbacks` collects tt_sdk_start fallbacks."""
    _Env.faults = list(faults)
    fallbacks = [] if fallbacks is None else fallbacks
    monkeypatch.setattr(ttw, "sdk_fallback", lambda port: fallbacks.append(port))

    def cmd(self, text, timeout=None):
        if text == "mem":
            return ["VAL", "mem", "41000"]
        if text == "sdk restore" and isinstance(restore, Exception):
            raise restore
        return restore if text == "sdk restore" and restore else ["OK"]

    envs = []
    monkeypatch.setattr(ttw, "PiEnvironment", lambda *a, **k: envs.append(_Env()) or envs[-1])
    monkeypatch.setattr(ttw, "HatGpio", _Hat)
    monkeypatch.setattr(ttw, "load_sibling", lambda name: object())
    monkeypatch.setattr(ttw, "make_pin_id_scanner", lambda pinid: None)
    monkeypatch.setattr(ttw, "open_raw_serial", lambda port: 99)
    monkeypatch.setattr(ttw.os, "close", lambda fd: None)
    monkeypatch.setattr(ttw, "start_firmware", start or (lambda link, fw: ["READY", f"mem_free={heap}"]))
    monkeypatch.setattr(ttw, "stop_firmware", lambda link: None)
    monkeypatch.setattr(ttw.Rp2Link, "cmd", cmd)
    monkeypatch.setattr(ttw.Rp2Link, "resync", lambda self, timeout=5.0: None)
    monkeypatch.setattr(ttw.Rp2Link, "write", lambda self, data: None)
    monkeypatch.setattr(ttw, "run_wiring_test", lambda *a, **k: measure())
    monkeypatch.setattr(ttw, "report", lambda result, discover, log=print: None)
    before = {sig: ttw.signal.getsignal(sig) for sig in ttw.STOPS}
    code = ttw.main(["--port", "/dev/ttyACM0", *ASIC, "--no-daemon"])
    assert {sig: ttw.signal.getsignal(sig) for sig in ttw.STOPS} == before  # handlers given back
    out = capsys.readouterr().out.splitlines()
    assert envs[0].left == [True]  # the Pi is put back whatever happened
    said = [line for line in out if line.startswith("WIRING: ")]
    if mem is not None:
        mem.extend(line for line in out if line.startswith("MEM: "))
    assert said and out[-1] == f"RESULT: {'PASS' if code == 0 else 'FAIL'}"
    return code, said[-1][len("WIRING: ") :]


def _passed():
    return {"pass": True, "asic_loopback": True, "cabling": "asic", "observed": {}}


def test_main_says_the_verdict_and_exits_with_it(monkeypatch, capsys):
    assert _main(monkeypatch, capsys, _passed)[0] == 0


def test_a_stop_during_the_test_puts_the_pi_back_and_is_exit_2(monkeypatch, capsys):
    def stopped():
        ttw.signal.raise_signal(ttw.signal.SIGTERM)  # the boot check's unit being stopped
        raise AssertionError("not reached: the handler raises")

    code, line = _main(monkeypatch, capsys, stopped)
    assert (
        code == 2
        and line == f"the wiring test was stopped (signal {int(ttw.signal.SIGTERM)}): the wiring was not tested"
    )


def test_unsteady_readings_fail_and_a_board_that_does_not_answer_is_exit_2(monkeypatch, capsys):
    def unsteady():
        raise ttw.UnstableReading("the two ui_in passes disagree on ui_in[3] (intermittent contact?)")

    def silent():
        raise ttw.ProtocolError("timeout waiting for the RP2")

    assert _main(monkeypatch, capsys, unsteady) == (
        1, "the readings were not steady, so the wiring is not known to be right: the two ui_in passes disagree "
           "on ui_in[3] (intermittent contact?)")  # fmt: skip
    assert _main(monkeypatch, capsys, silent) == (2, "the wiring could not be tested: timeout waiting for the RP2")


def test_a_pi_not_put_back_is_exit_2_after_the_verdict(monkeypatch, capsys):
    code, line = _main(monkeypatch, capsys, _passed, faults=["GPIO8 could not be set to ip pu: x"])
    assert code == 2 and line.endswith("; and the Pi was not put back as it was (GPIO8 could not be set to ip pu: x)")
    assert line.startswith("all 24 Pmod signals reached the Pi where they should")


def test_the_rp2_heap_is_said_and_a_heap_too_low_stops_the_test_before_it_starts(monkeypatch, capsys):
    mem = []
    assert _main(monkeypatch, capsys, _passed, mem=mem)[0] == 0
    # said where they happen, and again just before the WIRING: line, where the boot report keeps them
    assert mem == ["MEM: 60000 bytes of the RP2's heap free with the command server loaded",
                   "MEM: 41000 bytes of the RP2's heap free after the test"] * 2  # fmt: skip
    measured = []
    low = ttw.MIN_HEAP_FREE - 1
    code, line = _main(monkeypatch, capsys, lambda: measured.append(1) or _passed(), heap=low)
    assert code == 2 and measured == []  # not started
    assert line == (f"the wiring could not be tested: RP2040 heap too low: {low} bytes free with the command "
                    f"server loaded (the test needs {ttw.MIN_HEAP_FREE})")  # fmt: skip


def test_each_pin_id_round_says_the_heap_free_while_it_sends():
    _result, log = run_simulated(BoardModel(asic_wires(), project="drives_uio"), argv=ASIC, pin_id=True)
    rounds = [line for line in log if line.startswith("MEM: ")]
    sends = [line for line in rounds if "while it sends" in line]
    assert sends and all(line.startswith("MEM: 51000 bytes of the RP2's heap free while it sends ") for line in sends)
    assert "MEM: 60000 bytes of the RP2's heap free (collected) before the walks" in rounds


def test_the_command_server_never_imports_the_sdk_and_reports_its_heap():
    fw = ttw.build_firmware("rp2040")
    assert "import ttboard" not in fw and "from ttboard.demoboard" not in fw and "DemoBoard(" not in fw
    assert "the SDK is not running on the board (no tt object)" in fw
    assert "READY mem_free=" in fw and "VAL mem " in fw and "OK started mem_free=" in fw
    compile(fw, "firmware", "exec")  # it is valid Python, as MicroPython will parse it


def test_the_board_is_put_back_from_ram_and_a_restore_that_does_not_match_falls_back_to_a_soft_reset(
    monkeypatch, capsys
):
    fallbacks = []
    code, line = _main(
        monkeypatch, capsys, _passed, restore=["OK", "restored:", "<DemoBoard ...>"], fallbacks=fallbacks
    )
    assert code == 0 and fallbacks == []  # the good path: no reset, no boot.log
    err = ttw.ProtocolError("'sdk restore' -> restore: the board was <A> and is now <B>")
    code, line = _main(monkeypatch, capsys, _passed, restore=err, fallbacks=fallbacks)
    assert code == 2 and fallbacks == ["/dev/ttyACM0"]
    assert line.endswith("; and the board's SDK state could not be put back from RAM: 'sdk restore' -> restore: the "
                         "board was <A> and is now <B>; its SDK was started again by a soft reset")  # fmt: skip


def test_a_board_left_in_the_command_server_is_started_again(monkeypatch, capsys):
    def no_banner(link, firmware):
        raise ttw.ProtocolError("no raw REPL banner")

    fallbacks = []
    code, line = _main(monkeypatch, capsys, _passed, start=no_banner, fallbacks=fallbacks)
    assert code == 2 and fallbacks == ["/dev/ttyACM0"]
    assert line.startswith("the wiring could not be tested: no raw REPL banner; and the board was left in the test's "
                           "command server; its SDK was started again by a soft reset")  # fmt: skip


def test_its_own_time_limit_stops_the_test_and_puts_everything_back(monkeypatch, capsys):
    def slow():
        ttw.signal.raise_signal(ttw.signal.SIGALRM)
        raise AssertionError("not reached")

    code, line = _main(monkeypatch, capsys, slow)
    assert (code, line) == (2, "the wiring test was stopped (its own time limit): the wiring was not tested")
    assert ttw.signal.alarm(0) == 0  # no alarm left pending


def test_an_unexpected_exception_is_the_test_s_failure_not_the_wiring_s(monkeypatch, capsys):
    def broken():
        raise ValueError("invalid literal for int() with base 10: 'x'")

    assert _main(monkeypatch, capsys, broken) == (
        2, "the wiring test failed unexpectedly: ValueError: invalid literal for int() with base 10: 'x'")  # fmt: skip


def test_readings_that_disagree_fail_at_once_naming_the_lines(monkeypatch):
    class Flicker:
        def __init__(self):
            self.n = 0

        def read_all(self):
            self.n += 1
            return {8: 0, 10: self.n % 2, 26: 0}

    probe = ttw.WiringProbe(rp2=None, hat=Flicker(), controller="rp2040", samples=3, settle=0, log=lambda *_: None)
    with pytest.raises(ttw.UnstableReading, match=r"^HAT JA/JB pin 2 changed between readings"):
        probe.sample()
    assert probe.hat.n == 3  # one set of readings: no retry


def test_the_spi_modules_are_loaded_again_and_the_restore_is_read_back(monkeypatch):
    pinctrl = Pinctrl(BEFORE)
    env, calls = _env(monkeypatch, pinctrl)
    env.enter()
    assert env.unloaded == ["spidev", "spi_bcm2835"]
    assert env.leave() == []
    assert calls[-2:] == [["modprobe", "spi_bcm2835"], ["modprobe", "spidev"]] or (
        ["modprobe", "spi_bcm2835"] in calls and calls.index(["modprobe", "spi_bcm2835"]) < calls.index(
            ["modprobe", "spidev"]))  # fmt: skip
    # a pin that reads back otherwise is said
    pinctrl.state[8] = ("op", "pu", "hi")
    env.saved_pins = dict(env.saved_pins)
    assert env.check_pins() == ["GPIO8 reads back op pu hi, not ip pu"]


def test_a_bit_held_high_suggests_a_dip_switch_and_ui_in0_held_is_said_once():
    row = {"signal": "ui_in[4]", "status": "untested", "expected": [19], "observed": [], "detail": ""}
    (f,) = ttw.row_faults(row, "asic", {"ui_in[4]": "high"})
    assert f["text"] == "ui_in[4] (Pmod pin 7) is held high on the demo board (a DIP switch that is on? set all DIP " \
                        "switches off)"  # fmt: skip
    # ui_in[0] held: the factory test then drives uio, which holds ui_in[1:3] too; only ui_in[0] is named
    model = BoardModel(asic_wires(), project="drives_uio", hard_ui_in={0})
    result, _log = run_simulated(model, argv=ASIC)
    assert model.contentions == []
    code, line = ttw.verdict(result)
    assert code == 1 and line.startswith("the ui_in ribbon (to HAT JA): ui_in[0] (Pmod pin 1) is held low on the ")
    assert "ui_in[1]" not in line and "ui_in[2]" not in line and "ui_in[3]" not in line
    assert line.endswith(
        "; uio[6] (Pmod pin 9), uio[7] (Pmod pin 10) and uo_out were not tested: the chip's factory test could not "
        "be used (ui_in[0] is held)"
    )  # review 8, finding 2: held low, ui_in[0] leaves uio[0:5] tested


def test_replies_cut_short_by_a_stop_are_brought_back_in_step():
    """The reply of a command a stop cut short arrives after the resync's ping: it is read past, up to the PONG,
    and the next command reads its own reply."""
    a, b = socket.socketpair()

    def board():
        buf = b""
        while b"ping\n" not in buf:
            buf += b.recv(64)
        b.sendall(b"TTW OK 1\nTTW PONG\n")  # the late reply, then the ping's
        while b"mem\n" not in buf:
            buf += b.recv(64)
        b.sendall(b"TTW VAL mem 41000\n")

    thread = threading.Thread(target=board, daemon=True)
    thread.start()
    link = ttw.Rp2Link(a.fileno(), timeout=2.0)
    link.resync(timeout=2)
    assert link.cmd("mem") == ["VAL", "mem", "41000"]
    thread.join(timeout=2)
    a.close()
    b.close()
    silent, other = socket.socketpair()
    with pytest.raises(ttw.ProtocolError):
        ttw.Rp2Link(silent.fileno(), timeout=0.5).resync(timeout=0.5)
    silent.close()
    other.close()


def test_the_sdk_s_config_is_off_for_our_project_enable_and_on_again_for_the_restore():
    """SDK 2.0.4's enable() applies config.ini (the factory test's: ui_in = 1, a 10 Hz clock) unless apply_configs
    is off (demoboard.py line 477): the chip would then drive uio[1:3] against ui_in[1:3] through the HAT."""
    fw = ttw.build_firmware("rp2040")
    project = fw[fw.index("elif op == 'project':") : fw.index("elif op == 'reset':")]
    assert project.index("t.apply_configs = False") < project.index("p.enable()")
    restore = fw[fw.index("project, freq, was = _saved") :]
    assert restore.index("t.apply_configs = _saved_apply") < restore.index("project.enable()")


PLACEMENTS = [
    (dict(zip(ttw.GROUPS, order)), turned)
    for order in itertools.permutations(ttw.PORTS)
    for n in range(4)
    for turned in itertools.combinations(ttw.GROUPS, n)
]


@pytest.mark.parametrize("ports, turned", PLACEMENTS, ids=lambda v: str(v))
def test_no_ribbon_placement_makes_two_parties_drive_one_net(ports, turned):
    """Review 3's sweep: the 6 orders of the three ribbons over JA, JB and JC, each with every set of them turned
    round. No placement may make the RP2040 drive a net the chip drives, and only the right one passes."""
    code, line, fights = wiring_line(placed(ports, offset=turned))
    assert fights == [], line
    right = ports == {"ui_in": "JA", "uio": "JB", "uo_out": "JC"} and not turned
    assert (code == 0) == right, line


def test_a_dip_switch_that_is_on_is_named_and_on_ui_in0_blames_no_ribbon():
    for bit, pin in ((4, 7), (0, 1)):
        model = BoardModel(asic_wires(), project="drives_uio", held_ui_in={bit}, dip_level=1)
        result, _log = run_simulated(model, argv=ASIC)
        assert model.contentions == []
        code, line = ttw.verdict(result)
        said = f"the ui_in ribbon (to HAT JA): ui_in[{bit}] (Pmod pin {pin}) is held high on the demo board (a DIP " \
               "switch that is on? set all DIP switches off)"  # fmt: skip
        assert code == 1 and line.startswith(said), line
        assert "uio ribbon" not in line and "ui_in[1]" not in line  # nothing the held ui_in[0] explains is blamed


def test_a_resync_that_fails_trusts_no_reply_and_the_board_gets_the_fallback(monkeypatch, capsys):
    restored = []
    fallbacks = []

    def no_pong(self, timeout=5.0):
        raise ttw.ProtocolError("no PONG from the RP2 while bringing its replies back in step")

    def measure():
        monkeypatch.setattr(ttw.Rp2Link, "resync", no_pong)
        return _passed()

    monkeypatch.setattr(ttw.Rp2Link, "cmd", lambda self, text, timeout=None: restored.append(text) or ["OK"])
    code, line = _main(monkeypatch, capsys, measure, fallbacks=fallbacks)
    assert code == 2 and fallbacks == ["/dev/ttyACM0"]
    assert "; and the board's replies were out of step (no PONG" in line


def test_the_command_server_does_not_use_an_sdk_still_logging_to_its_boot_log():
    fw = ttw.build_firmware("rp2040")
    find = fw[fw.index("def _find_tt():") : fw.index("def _sdk(args):")]
    assert "Logger" in find and "OutFile" in find and "RuntimeError" in find


# Shorts among HAT JB9, JB10, JC9 and JC10 join uio[6:7] to their own copies or each other's: uio[6:7] are walked
# together, in phase, so those are not seen (said in the PR and the docs), and nothing fights.
UNSEEN = {(3, 6), (2, 5)}  # JB9-JC10, JB10-JC9 (and JB9-JB10, JC9-JC10, not lines to JC here)
SHORTS_TO_UO_OUT = [(fixed, jc) for fixed in (3, 2) for jc in ttw.PMOD_HAT_PORTS["JC"]]


@pytest.mark.parametrize("fixed, jc", SHORTS_TO_UO_OUT)
def test_a_short_from_an_i2c_pulled_up_line_to_a_uo_out_line_makes_no_fight(fixed, jc):
    """Review 4: HAT JB9/JB10 (Pi GPIO3/2, with the Pi's 1.8 kOhm pull-ups, so neither probe can see past them)
    shorted to a uo_out line on JC. uio[6:7] are driven only if the reverse walk did not reach them and neither
    followed another uio bit's walk, and then together, in phase, switched at once."""
    model = BoardModel(asic_wires(), project="drives_uio", extra_shorts=[(f"pi:{fixed}", f"pi:{jc}")])
    result, _log = run_simulated(model, argv=ASIC, pin_id=True)
    assert model.contentions == []
    assert ttw.verdict(result)[0] == (0 if (fixed, jc) in UNSEEN else 1)


NEIGHBOURS = [(1, 7), (7, 2), (2, 8), (8, 3), (3, 9), (9, 4), (4, 10)]  # Pmod pins next to each other on a ribbon


@pytest.mark.parametrize("port", ttw.PORTS)
@pytest.mark.parametrize("a, b", NEIGHBOURS)
def test_a_short_between_neighbouring_wires_points_nowhere_wrong_and_makes_us_fight_nothing(port, a, b):
    """Review 4, finding 2 (the coordinator's middle path): readings that fit no single fault say so, name the
    ribbon to look at, and carry no DIP-switch advice and no blame on the factory test. The RP2040 never drives
    against the chip or against itself; what the short makes the chip's own outputs do is the short's."""
    ga, gb = (ttw.PMOD_HAT_PORTS[port][ttw.PMOD_PIN_NUMBERS.index(n)] for n in (a, b))
    model = BoardModel(asic_wires(), project="drives_uio", extra_shorts=[(f"pi:{ga}", f"pi:{gb}")])
    try:
        result, _log = run_simulated(model, argv=ASIC, pin_id=True)
        code, line = ttw.verdict(result)
    except ttw.Unclear:  # stopped before the walks: main says the same line
        code, line = 1, ttw.UNCLEAR.format(ribbons="")
    assert code == 1 and line.startswith("the readings fit no single open wire, swapped or turned ribbon"), line
    assert "DIP" not in line and "factory" not in line
    ours = [c for c in model.contentions if any(d[0] == "rp2" for d in c)]
    assert ours == [], ours


def test_an_sdk_never_used_leaves_released_pins_so_the_board_gets_the_fallback(monkeypatch, capsys):
    """Review 4, finding 7: the server released the SDK's pins, then the SDK was never used (init failed by hand,
    --no-strict): the restore only says so, which is not the board as it started."""
    fallbacks = []
    code, line = _main(monkeypatch, capsys, _passed, restore=["OK", "pins", "released;", "the", "SDK", "was", "not",
                                                              "changed"], fallbacks=fallbacks)  # fmt: skip
    assert code == 2 and fallbacks == ["/dev/ttyACM0"]
    assert "; and the board's SDK was not used, so its pins were left released; its SDK was started again" in line


@pytest.mark.parametrize("gpio", [3, 2])
def test_hat_jb9_or_jb10_shorted_to_ground_is_never_driven_against(gpio):
    """Review 5: Pmod pin 10 lies next to pin 5, ground. A JB9/JB10 line held low is not the Pi's pull-up holding it
    high, so uio[6:7] are not driven into it, and the board fails, saying what holds the line."""
    model = BoardModel(asic_wires(), project="drives_uio", grounded={gpio})
    result, _log = run_simulated(model, argv=ASIC, pin_id=True)
    ours = [c for c in model.contentions if any(d[0] == "rp2" for d in c)]
    assert ours == []
    code, line = ttw.verdict(result)
    assert code == 1 and "could not be tested: something holds its line low" in line, line


def test_the_group_drive_is_refused_on_anything_but_an_rp2040():
    probe = ttw.WiringProbe(rp2=None, hat=None, controller="rp2350", log=lambda *_: None)
    with pytest.raises(ttw.ProtocolError, match="written for the RP2040 only"):
        probe.walk_together(["uio[6]", "uio[7]"])


def test_ui_in0_held_low_says_nothing_of_uio_and_not_that_the_pi_s_pull_ups_hold_uio6_7():
    """Review 6, finding 2: with ui_in[0] held at either level the loopback cannot be used, so uio is not blamed
    on its ribbon; and the Pi's own pull-ups on uio[6:7] are never given as "something holds its line". Review 8,
    finding 2: the uio bits not tested are named as that."""
    model = BoardModel(asic_wires(), project="drives_uio", hard_ui_in={0})
    result, _log = run_simulated(model, argv=ASIC)
    code, line = ttw.verdict(result)
    assert code == 1 and "uio ribbon" not in line and "holds its line" not in line, line
    assert "; uio[6] (Pmod pin 9), uio[7] (Pmod pin 10) and uo_out were not tested" in line, line


@pytest.mark.parametrize("gpio, pin", [(5, 9), (6, 10)])
def test_a_uo_out_line_shorted_to_ground_is_said_as_held_low_not_as_an_open_wire(gpio, pin):
    """Review 6, finding 3: JC10 lies next to Pmod pin 5, ground, on the ribbon."""
    model = BoardModel(asic_wires(), project="drives_uio", grounded={gpio})
    result, _log = run_simulated(model, argv=ASIC, pin_id=True)
    assert ours(model.contentions) == []
    code, line = ttw.verdict(result)
    assert code == 1 and f"did not reach HAT JC pin {pin} (that line is held low: a short to ground?)" in line, line


def test_the_chip_s_uio_never_fights_a_rail_in_any_placement():
    """Review 7, finding 5: the tests leave out fights of the chip's outputs against a wire's fault, as the fault's
    own; that holds only for uo_out (always driven). The chip's uio, which the test controls through ui_in[0], must
    never meet ground or a rail, in any of the 48 placements."""
    uio_nodes = set(RP2040["uio"])
    for ports, turned in PLACEMENTS:
        model = BoardModel(placed(ports, offset=turned), project="drives_uio")
        with contextlib.suppress(ttw.ProtocolError):
            run_simulated(model, argv=ASIC, pin_id=True)
        bad = [
            c
            for c in model.contentions
            if any(d[0] == "asic" and d[1] in uio_nodes for d in c) and any(d[0] == "rail" for d in c)
        ]
        assert bad == [], (ports, turned, bad[:2])


def test_the_tt04_placement_says_uio_and_uo_out_could_not_be_tested():
    """Review 7, finding 1: the fleet's one miswiring (4 Sep, TT04): all three ribbons turned round, ui_in on JC,
    uio on JB, uo_out on JA. ui_in[0] lands on the HAT's ground, so uio and uo_out are both untested."""
    code, line, fights = wiring_line(placed({"ui_in": "JC", "uio": "JB", "uo_out": "JA"}, offset=ttw.GROUPS))
    assert fights == [] and code == 1, line
    assert "some uio and uo_out signals could not be tested" in line or "uio and uo_out were not tested" in line, line


@pytest.mark.parametrize("model", [dict(hard_ui_in={0}), dict(held_ui_in={0}, dip_level=0)])
def test_ui_in0_held_low_names_the_uio_bits_not_tested_not_all_of_uio(model):
    """Review 8, finding 2: held low, ui_in[0] leaves uio[0:5] tested; only uio[6:7] (driven only through the chip's
    factory test) and uo_out are not."""
    code, line = asic_verdict(asic_wires(), project="drives_uio", pin_id=True, **model)
    assert code == 1 and line.endswith(
        "; uio[6] (Pmod pin 9), uio[7] (Pmod pin 10) and uo_out were not tested: the chip's factory test could not "
        "be used (ui_in[0] is held)"
    ), line


@pytest.mark.parametrize("bit", [1, 2, 3])
def test_a_dip_switch_on_ui_in1_to_3_says_why_its_uio_bit_is_untested(bit):
    """Review 8, finding 3: uio[k] is on ui_in[k]'s HAT line (JA2-4 and JB2-4 are the same Pi GPIOs)."""
    code, line = asic_verdict(asic_wires(), project="drives_uio", pin_id=True, held_ui_in={bit}, dip_level=1)
    assert code == 1 and line.endswith(
        f"the uio ribbon (to HAT JB): uio[{bit}] (Pmod pin {bit + 1}) could not be tested: HAT JA/JB pin {bit + 1} is "
        f"one Pi line, where ui_in[{bit}] is held high"
    ), line


class _FirmwareTT:
    """As much of the SDK's DemoBoard as the command server's `sdk` commands use."""

    def __init__(self, log):
        self._log = log
        self.mode = 2  # ASIC_RP_CONTROL
        self.shuttle = types.SimpleNamespace(enabled=types.SimpleNamespace(name="tt_um_factory_test", enable=self._on))
        self.apply_configs = True
        self.clock = 10
        self.drift = False  # a restore that does not come back the same

    def _on(self):
        self._log.append(("sdk", "enable"))

    @property
    def is_auto_clocking(self):
        return bool(self.clock)

    @property
    def auto_clocking_freq(self):
        return self.clock

    def clock_project_stop(self):
        self.clock = 0

    def clock_project_PWM(self, hz):
        self.clock = hz

    def reset_project(self, putInReset):
        pass

    def clock_project_once(self):
        pass

    def __repr__(self):
        clocking = f", auto-clocking @ {self.clock}" if self.clock else ""
        return f"<DemoBoard mode {self.mode}{clocking}{' drifted' if self.drift else ''}>"


def run_command_server(monkeypatch, commands, drift_after_init=False):
    """Run the RP2040 command server itself (FIRMWARE), under CPython, with a fake `machine`, `gc`, `time` and SDK.
    Returns the log: ("pin", gpio, mode, pull) for every Pin made, ("out", line) for every line it says."""
    log = []

    class Pin:
        IN, OUT, PULL_UP, PULL_DOWN = 0, 1, 1, 2

        def __init__(self, g, mode=0, pull=None, value=None, drive=None):
            log.append(("pin", g, mode, pull))

        def value(self, v=None):
            return 0

    machine = types.ModuleType("machine")
    machine.Pin, machine.mem32 = Pin, {}
    fake_gc = types.ModuleType("gc")
    fake_gc.collect, fake_gc.mem_free = lambda: None, lambda: 100000
    fake_time = types.ModuleType("time")
    fake_time.sleep_ms = fake_time.sleep_us = lambda n: None
    for name, mod in (("machine", machine), ("gc", fake_gc), ("time", fake_time)):
        monkeypatch.setitem(sys.modules, name, mod)
    tt = _FirmwareTT(log)
    script = list(commands)

    class Stdin:
        def readline(self):
            line = script.pop(0) + "\n"
            if line.startswith("sdk restore") and drift_after_init:
                tt.drift = True
            return line

    class Stdout:
        def write(self, s):
            log.extend(("out", x) for x in s.splitlines() if x)

    monkeypatch.setattr(sys, "stdin", Stdin())
    monkeypatch.setattr(sys, "stdout", Stdout())
    try:
        exec(ttw.build_firmware("rp2040"), {"tt": tt, "__name__": "__main__"})  # the server itself
    finally:
        monkeypatch.undo()
    return log


DATA_PINS = RP2040["ui_in"] + RP2040["uio"] + RP2040["uo_out"]  # what the server releases


def released_after(log, text):
    """Pins made plain inputs with no pull after the server said a line starting with `text`."""
    at = next(i for i, e in enumerate(log) if e[0] == "out" and e[1].startswith("TTW " + text))
    return [e[1] for e in log[at:] if e[0] == "pin" and e[2:] == (0, None)]


def test_after_the_sdks_restore_the_way_out_leaves_its_pins_alone(monkeypatch):
    """Issue #196: the server's `finally` released every data pin after `sdk restore`, so the SDK's own ui_in drive
    was undone (on board de641070db746f27, 8 Oct 2026: the RP2040's output enable off on all eight ui_in GPIOs)."""
    log = run_command_server(monkeypatch, ["sdk init", "sdk restore", "quit"])
    assert ("out", "TTW OK restored: <DemoBoard mode 2, auto-clocking @ 10>") in log
    assert released_after(log, "OK restored") == []


def test_a_ping_or_heap_read_after_the_restore_keeps_the_sdks_pins(monkeypatch):
    """Review 1 of #198: the host asks `ping` and `mem` after the restore; they touch no pin."""
    log = run_command_server(monkeypatch, ["sdk init", "sdk restore", "ping", "mem", "quit"])
    assert released_after(log, "OK restored") == []


@pytest.mark.parametrize(
    "commands",
    [
        ["sdk restore", "quit"],  # a restore with nothing saved: the SDK not changed, its pins released
        ["quit"],  # the SDK never used
        ["sdk init", "quit"],  # stopped before the restore
        ["sdk init", "sdk restore", f"out {RP2040['ui_in'][3]} 1", "quit"],  # a pin driven after the restore
    ],
)
def test_on_every_other_way_out_the_pins_are_released(monkeypatch, commands):
    log = run_command_server(monkeypatch, commands)
    assert sorted(released_after(log, "BYE")) == sorted(DATA_PINS)


def test_a_restore_that_did_not_come_back_the_same_releases_the_pins(monkeypatch):
    log = run_command_server(monkeypatch, ["sdk init", "sdk restore", "quit"], drift_after_init=True)
    assert any(e[0] == "out" and e[1].startswith("TTW ERR restore:") for e in log)
    assert sorted(released_after(log, "BYE")) == sorted(DATA_PINS)
