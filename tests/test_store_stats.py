import json
import math
import random
from pathlib import Path

from gnss_ntp_graphs import config, logs, stats
from gnss_ntp_graphs.export import Exporter, install_web
from gnss_ntp_graphs.sources.base import HostSample, PeerSample, SystemSample, gps_from_sky
from gnss_ntp_graphs.store import Store

FIX = Path(__file__).parent / "fixtures"
NOW = 1_800_000_000


def filled_store(tmp_path, days=2):
    st = Store(str(tmp_path / "s.db"))
    rng = random.Random(1)
    sky = json.loads((FIX / "gps_sky_multignss.json").read_text())
    for i in range(int(days * 1440)):
        ts = NOW - days * 86400 + i * 60
        st._insert(
            "system",
            [
                SystemSample(
                    ts=ts,
                    offset=rng.gauss(0, 0.01),
                    sys_jitter=0.005,
                    frequency=-4.3,
                    wander=0.01,
                    rootdelay=0.0,
                    rootdisp=0.01,
                    stratum=1,
                    refid="GPS",
                    leap="Normal",
                ).__dict__
            ],
        )
        st._insert(
            "peers",
            [
                PeerSample(
                    ts=ts, remote="GPS", tally="*", reach=255, offset=0.001, delay=0.0, jitter=0.002
                ).__dict__
            ],
        )
    st.add_gps(gps_from_sky(NOW, sky["satellites"], sky))
    st.db.commit()
    return st


def test_series_grid_and_gaps(tmp_path):
    st = filled_store(tmp_path)
    s = st.series("system", ["offset", "stratum"], NOW - 7200, NOW + 3600, 600, now=NOW)
    assert s["t"][0] % 600 == 0 and len(s["t"]) == 18
    assert all(v == 1 for v in s["stratum"][:12])
    assert s["stratum"][-1] is None  # future bucket


def test_rollup_and_retention(tmp_path):
    st = Store(str(tmp_path / "s.db"), raw_days=1, days_5m=2, days_1h=10)
    for i in range(3 * 1440):
        ts = NOW - 3 * 86400 + i * 60
        st._insert("system", [{"ts": ts, "offset": 1.0, "stratum": 1, "refid": "GPS"}])
    st.db.commit()
    st.rollup(now=NOW)

    def count(t):
        return st.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    assert count("system") == 1440
    assert 2 * 288 - 1 <= count("system_5m") <= 2 * 288 + 1
    assert count("system_1h") == 72
    assert st.db.execute("SELECT MAX(refid), AVG(offset) FROM system_1h").fetchone() == ("GPS", 1.0)
    # old range reads from the coarser tier
    s = st.series("system", ["offset"], NOW - 3 * 86400, NOW, 3600, now=NOW)
    assert sum(v is not None for v in s["offset"]) >= 71


def test_summary_percentiles():
    s = stats.summary(list(range(101)))
    assert s["p50"] == 50 and s["p1"] == 1 and s["p99"] == 99 and s["range90"] == 90
    assert stats.summary([None, None]) is None


def test_histogram_counts_all():
    vals = [random.Random(2).gauss(0, 1) for _ in range(1000)]
    h = stats.histogram(vals, bins=20)
    assert sum(h["count"]) == 1000 and len(h["x"]) == 20


def test_allan_deviation_white_phase_noise():
    # White phase noise: ADEV ~ sqrt(3) * sigma / tau
    rng = random.Random(3)
    sigma, tau0 = 1e-6, 1.0
    x = [rng.gauss(0, sigma) for _ in range(20000)]
    a = stats.allan_deviation(x, tau0)
    i = a["tau"].index(10.0)
    expected = math.sqrt(3) * sigma / 10.0
    assert abs(a["adev"][i] / expected - 1) < 0.1


def test_allan_skips_gaps():
    grid = stats.regularise([(0, 1.0), (60, 2.0), (240, 3.0)], 60)
    assert grid == [1.0, 2.0, None, None, 3.0]


def test_logs_parsers():
    rows = logs.read_log("chrony_tracking", str(FIX / "chrony_tracking.log"), 0)
    assert len(rows) == 2 and rows[0][1] == 0.0004512 and rows[0][2] == -4.371
    rows = logs.read_log("ntpd_loopstats", str(FIX / "loopstats"), 0)
    assert len(rows) == 2 and rows[0][1] == -0.045123 and rows[1][0] - rows[0][0] == 64


def test_export_writes_site(tmp_path):
    st = filled_store(tmp_path)
    www = tmp_path / "www"
    install_web(www)
    ex = Exporter(st, str(www), config.load())
    ex.current("bridge", now=NOW)
    ex.ranges(now=NOW, force=True)
    ex.stats(now=NOW)
    assert (www / "index.html").exists() and (www / "vendor" / "uPlot.iife.min.js").exists()
    cur = json.loads((www / "data" / "current.json").read_text())
    assert cur["gps"]["used"] == 5
    r = json.loads((www / "data" / "range_24h.json").read_text())
    assert "GPS" in r["peers"] and len(r["system"]["t"]) == len(r["system"]["offset"])
    s = json.loads((www / "data" / "stats.json").read_text())
    w = s["windows"]["24h"]
    assert w["origin"] == "polled" and w["tau0"] == 60 and w["adev"]["tau"][0] == 60
    assert w["peers"]["GPS"]["reach_full_pct"] == 100.0


def test_short_range_ntp_bucket_not_finer_than_poll(tmp_path):
    st = filled_store(tmp_path)
    ex = Exporter(st, str(tmp_path / "www"), config.load())
    ex.ranges(now=NOW, force=True)
    r = json.loads((tmp_path / "www" / "data" / "range_2h.json").read_text())
    sys_t, gps_t = r["system"]["t"], r["gps"]["t"]
    assert sys_t[1] - sys_t[0] == 60 and gps_t[1] - gps_t[0] == 30
    assert all(v is not None for v in r["system"]["offset"][-10:-1])
    assert all(v is not None for v in r["peers"]["GPS"]["offset"][-10:-1])


def test_linfit_and_pearson():
    fit = stats.linfit([20, 30, 40, None], [1.0, 2.0, 3.0, 9.0])
    assert fit == {"slope": 0.1, "intercept": -1.0, "r": 1.0, "n": 3}
    assert stats.pearson([1, 2, 3], [3, 2, 1]) == -1.0
    assert stats.linfit([1, 1, 1], [1, 2, 3]) is None
    assert stats.linfit([1, 2], [1, 2]) is None


def test_export_thermal(tmp_path):
    st = filled_store(tmp_path)
    for i in range(1440):
        ts = NOW - 86400 + i * 60
        temp = 45.0 + 5 * math.sin(i / 200)
        st._insert("host", [{"ts": ts, "cpu_temp": temp}])
        st.db.execute(
            "UPDATE system SET frequency = ? WHERE ts = ?", (-4.3 + 0.02 * (temp - 45), ts)
        )
    st.add_host(HostSample(ts=NOW, cpu_temp=46.0))
    www = tmp_path / "www"
    ex = Exporter(st, str(www), config.load())
    ex.current("local", now=NOW)
    ex.ranges(now=NOW, force=True)
    ex.stats(now=NOW)
    cur = json.loads((www / "data" / "current.json").read_text())
    assert cur["host"]["cpu_temp"] == 46.0
    r = json.loads((www / "data" / "range_24h.json").read_text())
    assert r["host"]["t"] == r["system"]["t"]
    w = json.loads((www / "data" / "stats.json").read_text())["windows"]["24h"]
    th = w["thermal"]
    assert th["step"] == 300 and len(th["temp"]) == len(th["frequency"]) == len(th["offset"])
    assert abs(th["fit_frequency"]["slope"] - 0.02) < 1e-3 and th["fit_frequency"]["r"] > 0.99
    assert w["cpu_temp"]["n"] >= 1440


def test_export_thermal_absent(tmp_path):
    st = filled_store(tmp_path)
    ex = Exporter(st, str(tmp_path / "www"), config.load())
    ex.stats(now=NOW)
    w = json.loads((tmp_path / "www" / "data" / "stats.json").read_text())["windows"]["24h"]
    assert w["thermal"] is None and w["cpu_temp"] is None
