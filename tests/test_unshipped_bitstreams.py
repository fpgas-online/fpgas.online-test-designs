"""The openXC7 build of the Acorn PCIe SoC is built in CI, expected to fail, and never shipped (issue #105).

What must hold, until #105 is closed and someone decides otherwise:

  * collect-bitstreams.yml neither waits for that workflow nor bundles its artifacts, so no package can carry
    an openXC7 Acorn PCIe SoC bitstream, and the bundle (and so every deb) never waits on its builds;
  * nothing under packaging/ or verify/ names those artifacts or that build directory;
  * each of its jobs never fails the workflow, and judges its own result: a known failure is expected, an
    unknown one or a pass is reported (scripts/openxc7_expected_failure.py).
"""

import importlib.util
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
COLLECT = (WORKFLOWS / "collect-bitstreams.yml").read_text()
BUILD = (WORKFLOWS / "acorn-pcie-build.yml").read_text()

_spec = importlib.util.spec_from_file_location("xfail", REPO / "scripts" / "openxc7_expected_failure.py")
xfail = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(xfail)


def _env(text, name):
    m = re.search(rf'^  {name}: "([^"]+)"$', text, flags=re.M)
    assert m, f"{name} is not set in collect-bitstreams.yml's env"
    return m.group(1)


UNSHIPPED_WORKFLOW = _env(COLLECT, "UNSHIPPED_WORKFLOW")
UNSHIPPED_ARTIFACTS = _env(COLLECT, "UNSHIPPED_ARTIFACTS")


def test_the_unshipped_names_are_the_build_workflows_own():
    assert re.search(rf'^name: "{re.escape(UNSHIPPED_WORKFLOW)}"$', BUILD, flags=re.M)
    uploads = re.findall(r"^\s+name: (acorn-pcie-soc-openxc7-.+)$", BUILD, flags=re.M)
    assert uploads, "acorn-pcie-build.yml uploads no artifact under the name collect-bitstreams.yml leaves out"
    assert all(name.startswith(UNSHIPPED_ARTIFACTS) for name in uploads)


def test_the_bundle_does_not_wait_for_the_unshipped_workflow():
    (wait,) = [line for line in COLLECT.splitlines() if 'select(.status != \\"completed\\"' in line]
    assert '.name != \\"${UNSHIPPED_WORKFLOW}\\"' in wait


def test_the_bundle_takes_nothing_from_the_unshipped_workflow():
    (runs,) = [line for line in COLLECT.splitlines() if 'select(.conclusion == \\"success\\"' in line]
    assert '.name != \\"${UNSHIPPED_WORKFLOW}\\"' in runs
    assert re.search(r'case "\$artifact_name" in "\$\{UNSHIPPED_ARTIFACTS\}"\*\) .*continue ;; esac', COLLECT)


def test_the_bundles_wait_on_named_checks_does_not_take_in_the_unshipped_jobs():
    (regexp,) = re.findall(r'check-regexp: "([^"]+)"', COLLECT)
    boards = ("Acorn CLE-215+", "NiteFury (CLE-215)", "LiteFury (CLE-101)")
    images = ("operational", "golden")
    names = [f"{board} ({image} image, expected to fail: #105)" for board in boards for image in images]
    assert not [name for name in names if re.match(regexp, name)]


@pytest.mark.parametrize("tree", ["packaging", "verify"])
def test_no_package_names_the_unshipped_bitstreams(tree):
    for path in sorted((REPO / tree).rglob("*")):
        if path.is_file() and path.suffix in (".py", ".toml", ".yml", ".json", ".md", ".in", ".sh", ".service"):
            text = path.read_text(errors="replace")
            assert UNSHIPPED_ARTIFACTS not in text, path
            assert "designs/acorn-pcie/build" not in text, path


def test_no_other_workflow_needs_the_unshipped_one():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name != "acorn-pcie-build.yml":
            text = path.read_text()
            assert "acorn-pcie-build.yml" not in text, path
            assert path.name == "collect-bitstreams.yml" or UNSHIPPED_WORKFLOW not in text, path


def test_each_job_never_fails_the_workflow_and_judges_its_own_build():
    assert re.search(r"^    continue-on-error: true", BUILD, flags=re.M)
    assert "id: build" in BUILD
    assert "scripts/openxc7_expected_failure.py --outcome" in BUILD


# -- the judgement -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "ERROR: Unable to place cell 'XADC', no Bels remaining of type 'XADC'",
        "OSError: timing not met with any nextpnr seed 1..5",
    ],
)
def test_a_known_failure_is_expected(line):
    status, note = xfail.judge("failure", f"Info: packing\n{line}\nmore\n")
    assert status == 0
    assert note.startswith("::warning::Expected failure") and "issues/105" in note and line in note


def test_any_other_failure_is_reported():
    status, note = xfail.judge("failure", "ModuleNotFoundError: No module named 'litex'\n")
    assert status == 1 and note.startswith("::error::") and "does not record" in note


def test_a_pass_is_reported_so_that_someone_decides_whether_it_ships():
    status, note = xfail.judge("success", "")
    assert status == 1 and note.startswith("::error::Unexpected pass") and "never run on a board" in note


def test_a_cancelled_or_skipped_build_is_not_taken_for_either():
    assert xfail.judge("cancelled", "Unable to place cell 'XADC'")[0] == 1
    assert xfail.judge("skipped", "")[0] == 1


def test_a_missing_log_is_an_unknown_failure(tmp_path, capsys):
    assert xfail.main(["--outcome", "failure", "--log", str(tmp_path / "none.log")]) == 1
    assert "does not record" in capsys.readouterr().out
