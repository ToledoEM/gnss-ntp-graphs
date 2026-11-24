import json
from pathlib import Path

from gnss_ntp_graphs.sources import base, local
from gnss_ntp_graphs.sources.bridge import BridgeSource

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_text()


def test_system_from_ntpd_bridge_strings():
    # The bridge's ntpd endpoint publishes every value as a string
    crv = {
        "refid": "192.168.1.1",
        "stratum": "2",
        "offset": "-0.045123",
        "sys_jitter": "0.123456",
        "clk_jitter": "0.089",
        "frequency": "-4.371",
        "clk_wander": "0.012",
        "rootdelay": "12.345",
        "rootdisp": "32.211",
        "leap": "00",
    }
    s = base.system_from_crv(100, crv)
    assert s.stratum == 2 and s.offset == -0.045123 and s.wander == 0.012 and s.leap == "00"


def test_system_from_error():
    assert base.system_from_crv(1, {"error": "NTP not responding"}) is None
    assert base.peers_from_pn(1, {"error": "x"}) is None


def test_gps_from_sky_used_by_constellation():
    sky = json.loads(read("gps_sky_multignss.json"))
    g = base.gps_from_sky(1, sky["satellites"], sky)
    assert g.total == 8 and g.used == 5
    assert g.visible_by["glonass"] == 2 and g.used_by["glonass"] == 1
    assert g.used_by["sbas"] == 0 and g.visible_by["sbas"] == 1
    assert g.avg_ss == round((38 + 31 + 36 + 40 + 30) / 5, 2)
    assert g.dops["tdop"] == 0.74


def test_gps_no_sats():
    g = base.gps_from_sky(1, [], {})
    assert g.total == 0 and g.avg_ss is None


def test_ntpq_rv_parser():
    crv = local.ntpq_rv(read("ntpq_crv_normal.txt"))
    assert crv["stratum"] == "2" and crv["version"].startswith("ntpd 4.2.8p15")
    assert crv["leap_status"] == "Normal"
    s = base.system_from_crv(1, crv)
    assert s.offset == -0.045123 and s.rootdisp == 32.211


def test_ntpq_pn_parser():
    peers = base.peers_from_pn(1, local.ntpq_pn(read("ntpq_pn_normal.txt")))
    assert [p.remote for p in peers] == ["192.168.1.1", "192.168.1.2", "10.0.0.9", "10.0.0.5"]
    assert [p.tally for p in peers] == ["*", "+", "-", ""]
    assert peers[0].reach == 255 and peers[2].reach == 127
    assert peers[1].offset == 0.071


def test_chrony_tracking_matches_bridge_mapping():
    crv = local.chrony_crv(read("chronyc_tracking.csv"), read("chronyc_sourcestats.csv"))
    assert crv["refid"] == "GPS" and crv["stratum"] == 1
    assert crv["offset"] == 0.000045  # -(-45 ns) in ms
    assert crv["clk_jitter"] == 0.000089
    assert crv["frequency"] == -4.371 and crv["leap_status"] == "Normal"


def test_chrony_sources():
    pn = local.chrony_pn(
        read("chronyc_sources.csv"), read("chronyc_sourcestats.csv"), read("chronyc_ntpdata.txt")
    )
    assert [p["remote"] for p in pn] == ["GPS", "45.154.197.21", "45.138.55.61"]
    gps, net, dead = pn
    assert gps["refid"] == ".GPS." and gps["t"] == "l" and gps["tally"] == "*" and gps["poll"] == 16
    assert net["delay"] == 21.414597 and net["offset"] == -0.012 and net["jitter"] == 0.21
    assert net["refid"] == "139.143.5.30"  # hex refid with empty name
    assert dead["reach"] == 0 and dead["tally"] == "" and dead["refid"] == ".GPS."


def test_bridge_source(tmp_path, monkeypatch):
    payload = {
        "ntpq_crv.json": {"refid": "GPS", "stratum": 1, "offset": 0.001},
        "ntpq_pn.json": [{"remote": "GPS", "tally": "*", "st": 0, "reach": 255, "offset": 0.001}],
        "gps.json": {"error": "GPS not responding", "satellites": []},
    }
    src = BridgeSource("http://bridge")
    monkeypatch.setattr(src, "_get", lambda name: payload[name])
    assert src.system().refid == "GPS"
    assert src.peers()[0].reach == 255
    assert src.gps() is None
    # gpsd down: bridge publishes a processed record with no timestamp
    payload["gps.json"] = {
        "timestamp": None,
        "total_satellites": 0,
        "satellites": [],
        "dop_values": {},
    }
    assert src.gps() is None
    payload["gps.json"] = {"timestamp": "2026-11-24T10:00:00Z", "satellites": [], "dop_values": {}}
    assert src.gps().total == 0


def test_unsynced_system_not_in_series(tmp_path):
    from gnss_ntp_graphs.store import Store

    st = Store(str(tmp_path / "s.db"))
    st.add_system(base.SystemSample(ts=1, stratum=0, rootdelay=1000.0, leap="Not synchronised"))
    assert st.db.execute("SELECT COUNT(*) FROM system").fetchone()[0] == 0
    assert st.get_meta("system_latest")["leap"] == "Not synchronised"


def test_vcgencmd_temp():
    assert local.vcgencmd_temp(read("vcgencmd_measure_temp.txt")) == 48.3
    assert local.vcgencmd_temp("temp=-2'C") == -2.0
    assert local.vcgencmd_temp("error=1") is None
    assert local.vcgencmd_temp(None) is None


def test_thermal_zone_temp():
    assert local.thermal_zone_temp("51540\n") == 51.54
    assert local.thermal_zone_temp("") is None
