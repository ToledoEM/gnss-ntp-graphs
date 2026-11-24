import subprocess
from pathlib import Path

import pytest

LINT = Path(__file__).parent.parent / ".githooks" / "commit-lint.sh"


@pytest.mark.parametrize("msg, ok", [
    ("feat(web): add colour palettes\n", True),
    ("fix: guard null axis ticks\n\nLog scale passes null ticks.\n", True),
    ("Added stuff.\n", False),
    ("feat: added palettes\n", False),
    ("feat: add palettes\n\nCo-Authored-By: Claude <x@y>\n", False),
])
def test_commit_lint(tmp_path, msg, ok):
    f = tmp_path / "msg"
    f.write_text(msg)
    r = subprocess.run(["sh", str(LINT), str(f)], capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stdout
