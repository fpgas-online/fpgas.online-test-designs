# SPDX-License-Identifier: Apache-2.0
"""gen.py's --check and its write agree about what belongs in generated/ (docs/wiring/wiringlib/output.py).

Run: uv run --no-project --with pytest --with fonttools==4.65.0 pytest docs/wiring/tt-fpga
"""

import hashlib

import picture  # noqa: F401  (it puts docs/wiring on the import path, which wiringlib is found on)
import pytest
from wiringlib import output

FILES = {"a.svg": "<svg/>", "a.md": "words"}


def current(tmp_path):
    for name, text in FILES.items():
        (tmp_path / name).write_text(text)
    (tmp_path / "a.png").write_bytes(b"png")
    (tmp_path / "png-sources.sha256").write_text(f"{hashlib.sha256(b'<svg/>').hexdigest()}  a.svg\n")


def test_a_current_directory_is_not_stale(tmp_path):
    current(tmp_path)
    assert output.stale(FILES, tmp_path) == []


def test_a_png_whose_svg_is_gone_is_stale_as_write_would_remove_it(tmp_path, capsys):
    current(tmp_path)
    (tmp_path / "old.png").write_bytes(b"png")
    (tmp_path / "old.md").write_text("gone")
    assert output.stale(FILES, tmp_path) == [
        "old.md (the generator no longer writes it)",
        "old.png (the generator no longer writes it)",
    ]
    with pytest.raises(SystemExit, match=r"old\.png"):
        output.check(FILES, tmp_path)
    output.write(FILES, tmp_path)
    said = capsys.readouterr().out
    assert "old.png: the generator no longer writes it" in said and "old.md: the generator no longer writes it" in said
    assert not (tmp_path / "old.png").exists() and (tmp_path / "a.png").exists()
    assert output.stale(FILES, tmp_path) == []


def test_a_png_rendered_from_an_older_svg_is_stale(tmp_path):
    current(tmp_path)
    assert output.stale({**FILES, "a.svg": "<svg>new</svg>"}, tmp_path) == [
        "a.png (rendered from an older a.svg; run render.py)",
        "a.svg",
    ]
