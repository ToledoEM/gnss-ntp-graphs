"""deploy/gnss-ntp-cpu-temp: the publisher for the bridge host."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "gnss-ntp-cpu-temp"
BASE_PATH = "/usr/bin:/bin"


def run(tmp_path, *args, zone=None, path=BASE_PATH):
    env = {
        "PATH": path,
        "WEB_ROOT": str(tmp_path / "www"),
        "THERMAL_ZONE": str(zone or tmp_path / "missing"),
    }
    return subprocess.run(
        ["/bin/sh", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )


@pytest.fixture
def www(tmp_path):
    (tmp_path / "www").mkdir()
    return tmp_path / "www"


def test_thermal_zone(tmp_path, www):
    zone = tmp_path / "temp"
    zone.write_text("50500\n")
    r = run(tmp_path, zone=zone)
    assert r.returncode == 0, r.stderr
    data = json.loads((www / "cpu_temp.json").read_text())
    assert data["cpu_temp"] == 50.5 and isinstance(data["timestamp"], int)
    assert not (www / "cpu_temp.json.tmp").exists()
    assert oct((www / "cpu_temp.json").stat().st_mode & 0o777) == "0o644"


def test_vcgencmd_first(tmp_path, www):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "vcgencmd"
    fake.write_text('#!/bin/sh\necho "temp=49.4\'C"\n')
    fake.chmod(0o755)
    zone = tmp_path / "temp"
    zone.write_text("25000\n")
    r = run(tmp_path, zone=zone, path=f"{bindir}:{BASE_PATH}")
    assert r.returncode == 0, r.stderr
    assert json.loads((www / "cpu_temp.json").read_text())["cpu_temp"] == 49.4


def test_no_sensor(tmp_path, www):
    r = run(tmp_path)
    assert r.returncode == 1 and "no CPU temperature" in r.stderr
    assert not (www / "cpu_temp.json").exists()


def test_no_web_root(tmp_path):
    zone = tmp_path / "temp"
    zone.write_text("50500\n")
    r = run(tmp_path, zone=zone)
    assert r.returncode == 1 and "web root" in r.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="checks the non-root refusal")
def test_install_needs_root(tmp_path, www):
    r = run(tmp_path, "install")
    assert r.returncode == 1 and "needs root" in r.stderr


def test_bad_argument(tmp_path, www):
    assert run(tmp_path, "nope").returncode == 2


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck():
    r = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout
