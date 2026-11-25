"""CLI, collector loop, built-in server, source factory, local source and gpsd reader."""

import json
import signal
import socket
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from gnss_ntp_graphs import __main__ as cli
from gnss_ntp_graphs import __version__, config
from gnss_ntp_graphs.collector import Collector, serve
from gnss_ntp_graphs.sources import base, local, make_source
from gnss_ntp_graphs.sources.bridge import BridgeSource
from gnss_ntp_graphs.sources.local import LocalSource

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_text()


def tmp_cfg(tmp_path, **source):
    cfg = config.load()
    cfg["paths"]["db"] = str(tmp_path / "samples.db")
    cfg["paths"]["www"] = str(tmp_path / "www")
    cfg["source"].update(source)
    return cfg


class StubSource:
    """Returns fixed samples; gps() raises to exercise the job error path."""

    def system(self):
        return base.SystemSample(ts=1, offset=0.001, stratum=1, refid="PPS", leap="Normal")

    def peers(self):
        return [base.PeerSample(ts=1, remote="PPS(0)", tally="*", reach=255, offset=0.001)]

    def gps(self):
        raise RuntimeError("gps boom")


# --- source factory ---------------------------------------------------------


def test_make_source_kinds(tmp_path):
    cfg = tmp_cfg(tmp_path, type="bridge", bridge_url="http://bridge")
    assert isinstance(make_source(cfg), BridgeSource)
    cfg = tmp_cfg(tmp_path, type="local", ntp="chrony", gpsd_port=1234)
    src = make_source(cfg)
    assert isinstance(src, LocalSource) and src.ntp == "chrony" and src.gpsd_port == 1234
    cfg["source"]["type"] = "other"
    with pytest.raises(ValueError, match="unknown source type"):
        make_source(cfg)


# --- bridge over real HTTP --------------------------------------------------


def test_bridge_get_over_http(tmp_path):
    (tmp_path / "ntpq_crv.json").write_text(json.dumps({"refid": "GPS", "stratum": 1}))
    (tmp_path / "bad.json").write_text("{not json")
    httpd = serve(str(tmp_path), "127.0.0.1", 0)
    try:
        port = httpd.server_address[1]
        src = BridgeSource(f"http://127.0.0.1:{port}", timeout=5)
        assert src.system().refid == "GPS"
        assert src._get("missing.json") is None  # 404
        assert src._get("bad.json") is None  # invalid JSON
    finally:
        httpd.shutdown()
        httpd.server_close()


# --- built-in web server ----------------------------------------------------


def test_serve_sets_no_cache_on_data(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "current.json").write_text("{}")
    (tmp_path / "index.html").write_text("<html></html>")
    httpd = serve(str(tmp_path), "127.0.0.1", 0)
    try:
        base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
        with urllib.request.urlopen(base_url + "/data/current.json") as r:  # noqa: S310
            assert r.headers["Cache-Control"] == "no-cache"
        with urllib.request.urlopen(base_url + "/index.html") as r:  # noqa: S310
            assert r.headers["Cache-Control"] is None
            assert b"<html>" in r.read()
    finally:
        httpd.shutdown()
        httpd.server_close()


# --- local source -----------------------------------------------------------


def test_run_helper():
    assert local._run([sys.executable, "-c", "print('hi')"], 10) == "hi\n"
    assert local._run([sys.executable, "-c", "raise SystemExit(3)"], 10) is None
    assert local._run(["/nonexistent/gng-test-binary"], 10) is None


CHRONY = {
    "tracking": "chronyc_tracking.csv",
    "sources": "chronyc_sources.csv",
    "sourcestats": "chronyc_sourcestats.csv",
    "ntpdata": "chronyc_ntpdata.txt",
}


def fake_run(answers):
    def run(cmd, timeout):
        key = cmd[-1] if cmd[0] == "chronyc" else " ".join(cmd[1:])
        name = answers.get(key)
        return read(name) if name else None

    return run


def test_local_chrony(monkeypatch):
    monkeypatch.setattr(local, "_run", fake_run(CHRONY))
    src = LocalSource(ntp="chrony")
    s = src.system()
    assert s is not None and s.stratum is not None and s.refid
    peers = src.peers()
    assert peers and all(p.remote for p in peers)


def test_local_ntpd(monkeypatch):
    monkeypatch.setattr(
        local, "_run", fake_run({"-c rv": "ntpq_crv_normal.txt", "-pn": "ntpq_pn_normal.txt"})
    )
    src = LocalSource(ntp="ntpd")
    assert src.system() is not None
    assert src.peers()


def test_local_daemon_failures(monkeypatch):
    monkeypatch.setattr(local, "_run", lambda cmd, timeout: None)
    for ntp in ("chrony", "ntpd"):
        src = LocalSource(ntp=ntp)
        assert src.system() is None
        assert src.peers() is None


def test_local_daemon_detection(monkeypatch):
    assert LocalSource(ntp="chronyd")._daemon() == "chrony"
    assert LocalSource(ntp="ntp")._daemon() == "ntpd"
    monkeypatch.setattr(local.shutil, "which", lambda name: "/usr/bin/chronyc")
    monkeypatch.setattr(local, "_run", lambda cmd, timeout: "x")
    assert LocalSource(ntp="auto")._daemon() == "chrony"
    monkeypatch.setattr(local.shutil, "which", lambda name: None)
    assert LocalSource(ntp="auto")._daemon() == "ntpd"


def test_local_gps(monkeypatch):
    sky = json.loads(read("gps_sky_multignss.json"))
    monkeypatch.setattr(local, "read_gpsd_sky", lambda host, port, timeout: sky)
    g = LocalSource().gps()
    assert g.total == 8 and g.used == 5
    monkeypatch.setattr(local, "read_gpsd_sky", lambda host, port, timeout: None)
    assert LocalSource().gps() is None


# --- gpsd reader ------------------------------------------------------------


def fake_gpsd(lines):
    """One-shot TCP server that waits for ?WATCH then sends lines."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def handle():
        conn, _ = srv.accept()
        with conn:
            conn.recv(1024)
            for line in lines:
                conn.sendall(line.encode() + b"\n")
        srv.close()

    threading.Thread(target=handle, daemon=True).start()
    return srv.getsockname()[1]


def test_read_gpsd_sky():
    sky = {"class": "SKY", "hdop": 0.8, "satellites": [{"PRN": 1, "used": True}]}
    port = fake_gpsd(
        [
            json.dumps({"class": "VERSION"}),
            "not json",
            json.dumps({"class": "SKY", "satellites": []}),
            json.dumps(sky),
        ]
    )
    assert local.read_gpsd_sky("127.0.0.1", port, 5) == sky


def test_read_gpsd_sky_no_report_and_refused():
    port = fake_gpsd([json.dumps({"class": "TPV"})])
    assert local.read_gpsd_sky("127.0.0.1", port, 2) is None
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    closed = s.getsockname()[1]
    s.close()
    assert local.read_gpsd_sky("127.0.0.1", closed, 2) is None


# --- collector --------------------------------------------------------------


def test_collector_once_writes_site(tmp_path):
    c = Collector(tmp_cfg(tmp_path))
    c.source = StubSource()
    c.source.gps = lambda: None
    c.once()
    data = tmp_path / "www" / "data"
    for name in ("config.json", "current.json", "range_24h.json", "stats.json"):
        assert (data / name).exists(), name
    assert (tmp_path / "www" / "index.html").exists()
    cur = json.loads((data / "current.json").read_text())
    assert cur["system"]["refid"] == "PPS" and cur["peers"][0]["remote"] == "PPS(0)"


def test_collector_run_loop_and_server(tmp_path):
    cfg = tmp_cfg(tmp_path)
    cfg["server"].update(serve=True, bind="127.0.0.1", port=0)
    for k in cfg["intervals"]:
        cfg["intervals"][k] = 1
    c = Collector(cfg)
    c.source = StubSource()  # gps() raises: the loop must log it and carry on
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    timer = threading.Timer(1.5, c.stop.set)
    timer.start()
    try:
        c.run()
    finally:
        timer.cancel()
        for sig, handler in saved.items():
            signal.signal(sig, handler)
    assert (tmp_path / "www" / "data" / "current.json").exists()


def test_collector_signal_handler_stops(tmp_path):
    c = Collector(tmp_cfg(tmp_path))
    c.source = StubSource()
    c.jobs = [(1.0, lambda: None)]
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        threading.Timer(0.3, lambda: signal.raise_signal(signal.SIGTERM)).start()
        c.run()
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)
    assert c.stop.is_set()


# --- command line -----------------------------------------------------------


def test_cli_once(tmp_path, monkeypatch):
    monkeypatch.setenv("GNG_PATHS_DB", str(tmp_path / "samples.db"))
    monkeypatch.setenv("GNG_PATHS_WWW", str(tmp_path / "www"))
    monkeypatch.setenv("GNG_SOURCE_BRIDGE_URL", "http://127.0.0.1:9/")
    monkeypatch.setenv("GNG_SOURCE_TIMEOUT", "0.5")
    assert cli.main(["-v", "once"]) == 0
    assert (tmp_path / "www" / "data" / "current.json").exists()


def test_cli_run_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli, "Collector", lambda cfg: type("C", (), {"run": lambda self: calls.append("run")})()
    )
    assert cli.main([]) == 0
    assert calls == ["run"]


def test_cli_config_errors(tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text('[web]\ntheme = "blue"\n')
    assert cli.main(["-c", str(bad), "once"]) == 2
    assert "config error" in capsys.readouterr().err
    assert cli.main(["-c", str(tmp_path / "missing.toml"), "once"]) == 2


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def zones(root, *pairs):
    for i, (kind, milli) in enumerate(pairs):
        z = root / f"thermal_zone{i}"
        z.mkdir(parents=True)
        (z / "type").write_text(kind + "\n")
        (z / "temp").write_text(f"{milli}\n")
    return root


def test_host_temp_vcgencmd(monkeypatch, tmp_path):
    monkeypatch.setattr(local.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(local, "_run", lambda cmd, timeout: "temp=47.2'C\n")
    h = local.HostTemp(root=tmp_path).read()
    assert h is not None and h.cpu_temp == 47.2


def test_host_temp_picks_cpu_zone_by_type(monkeypatch, tmp_path):
    monkeypatch.setattr(local.shutil, "which", lambda name: None)
    pi = zones(tmp_path / "pi", ("cpu-thermal", 50500))
    assert local.HostTemp(root=pi).read().cpu_temp == 50.5
    x86 = zones(
        tmp_path / "x86", ("acpitz", 25000), ("INT3400 Thermal", 20000), ("x86_pkg_temp", 65000)
    )
    assert local.HostTemp(root=x86).read().cpu_temp == 65.0
    acpi = zones(tmp_path / "acpi", ("acpitz", 25000))
    ht = local.HostTemp(root=acpi)
    assert ht.read() is None and ht.missing_logged
    assert local.HostTemp(root=tmp_path / "none").read() is None


def test_local_source_host(monkeypatch, tmp_path):
    monkeypatch.setattr(local.shutil, "which", lambda name: None)
    src = LocalSource()
    src.host_temp = local.HostTemp(root=zones(tmp_path, ("cpu-thermal", 49400)))
    assert src.host().cpu_temp == 49.4


def test_collector_poll_host(tmp_path, monkeypatch):
    c = Collector(tmp_cfg(tmp_path, type="local"))
    monkeypatch.setattr(c.source, "host", lambda: base.HostSample(ts=5, cpu_temp=50.0))
    c.poll_host()
    assert c.store.get_meta("host_latest") == {"ts": 5, "cpu_temp": 50.0}
    (tmp_path / "off").mkdir()
    off = Collector(tmp_cfg(tmp_path / "off", type="local", host_temp=False))
    monkeypatch.setattr(off.source, "host", lambda: base.HostSample(ts=5, cpu_temp=50.0))
    off.poll_host()
    assert off.store.get_meta("host_latest") is None


def test_collector_bridge_uses_only_bridge_temperature(tmp_path, monkeypatch):
    c = Collector(tmp_cfg(tmp_path, type="bridge"))
    monkeypatch.setattr(local.HostTemp, "read", lambda self: base.HostSample(ts=8, cpu_temp=25.0))
    monkeypatch.setattr(c.source, "host", lambda: None)
    c.poll_host()
    assert c.store.get_meta("host_latest") is None  # never this machine's sensor
    monkeypatch.setattr(c.source, "host", lambda: base.HostSample(ts=7, cpu_temp=49.4))
    c.poll_host()
    assert c.store.get_meta("host_latest")["cpu_temp"] == 49.4
