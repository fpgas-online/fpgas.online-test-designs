"""The fpgas_online_verify package (verify/src) is importable from the tests without installing it."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "verify" / "src"))
