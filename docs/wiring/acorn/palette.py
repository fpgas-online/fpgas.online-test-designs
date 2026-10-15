# SPDX-License-Identifier: Apache-2.0
"""The palette is docs/diagrams/palette.py; this name is kept for the Acorn generator's imports."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from diagrams.palette import *  # noqa: F403
from diagrams.palette import ROLES, WIRES, _tokens  # noqa: F401
