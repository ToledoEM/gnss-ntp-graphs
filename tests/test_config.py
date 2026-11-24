import json
from pathlib import Path

import pytest

from gnss_ntp_graphs import config
from gnss_ntp_graphs.export import Exporter
from gnss_ntp_graphs.store import Store

DEPLOY = Path(__file__).parent.parent / "deploy" / "config.toml"


def write(tmp_path, text):
    p = tmp_path / "c.toml"
    p.write_text(text)
    return str(p)


def test_deploy_file_equals_defaults():
    assert config.load(str(DEPLOY)) == config.load()


def test_partial_file_merges(tmp_path):
    c = config.load(
        write(tmp_path, '[web]\ntheme = "dark"\ncolumns = 2\n[retention]\nraw_days = 3\n')
    )
    assert c["web"]["theme"] == "dark" and c["web"]["columns"] == 2
    assert c["retention"]["raw_days"] == 3.0 and isinstance(c["retention"]["raw_days"], float)
    assert c["web"]["layout"] == "tabs"  # untouched default


def test_graph_limits(tmp_path):
    c = config.load(
        write(tmp_path, "[graphs.offset]\ny_max = 0.05\n[graphs.peer-reach]\ny_min = 0\n")
    )
    assert c["graphs"] == {"offset": {"y_max": 0.05}, "peer-reach": {"y_min": 0}}


@pytest.mark.parametrize(
    "text, msg",
    [
        ('[web]\ntheme = "blue"\n', "theme"),
        ('[web]\nlayout = "grid"\n', "layout"),
        ("[web]\ncolumns = 5\n", "columns"),
        ('[web]\nsections = ["ntp", "weather"]\n', "sections"),
        ('[web]\nranges = ["2h"]\ndefault_range = "24h"\n', "default_range"),
        ('[web]\nhide_graphs = ["nope"]\n', "hide_graphs"),
        ('[web]\ngraph_height = "tall"\n', "graph_height"),
        ("[web]\nbogus = 1\n", "bogus"),
        ("[nosuch]\na = 1\n", "nosuch"),
        ("[graphs.offset]\ncolor = 1\n", "graphs.offset"),
        ("[graphs.unknown]\ny_max = 1\n", "graphs.unknown"),
        ("[source\n", "c.toml"),
    ],
)
def test_invalid(tmp_path, text, msg):
    with pytest.raises(config.ConfigError, match=msg.replace(".", r"\.")):
        config.load(write(tmp_path, text))


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("GNG_SOURCE_TYPE", "local")
    monkeypatch.setenv("GNG_SERVER_SERVE", "yes")
    monkeypatch.setenv("GNG_SERVER_PORT", "9000")
    monkeypatch.setenv("GNG_WEB_SECTIONS", "ntp, stats")
    monkeypatch.setenv("GNG_WEB_OFFSET_LINES", "-0.01,0.01")
    monkeypatch.setenv("GNG_WEB_COLUMNS", "1")
    c = config.load()
    assert (
        c["source"]["type"] == "local"
        and c["server"]["serve"] is True
        and c["server"]["port"] == 9000
    )
    assert c["web"]["sections"] == ["ntp", "stats"] and c["web"]["offset_lines"] == [-0.01, 0.01]
    assert c["web"]["columns"] == 1


def test_env_bad_value(monkeypatch):
    monkeypatch.setenv("GNG_SERVER_PORT", "eighty")
    with pytest.raises(config.ConfigError, match="GNG_SERVER_PORT"):
        config.load()


def test_export_config_json_and_range_filter(tmp_path):
    c = config.load(
        write(
            tmp_path,
            '[web]\nranges = ["24h", "2h"]\ndefault_range = "2h"\nhide_peers = ["NMEA"]\n'
            "[graphs.dop]\ny_max = 3\n",
        )
    )
    st = Store(str(tmp_path / "s.db"))
    ex = Exporter(st, str(tmp_path / "www"), c)
    ex.web_config()
    out = json.loads((tmp_path / "www" / "data" / "config.json").read_text())
    assert out["web"]["ranges"] == ["2h", "24h"]  # canonical order
    assert out["graphs"] == {"dop": {"y_max": 3}}
    ex.ranges(now=1_800_000_000, force=True)
    names = sorted(p.name for p in (tmp_path / "www" / "data").glob("range_*.json"))
    assert names == ["range_24h.json", "range_2h.json"]


def test_colorbrewer_vendored():
    schemes = config.palettes()
    assert sorted(schemes) == [
        "Accent",
        "Dark2",
        "Paired",
        "Pastel1",
        "Pastel2",
        "Set1",
        "Set2",
        "Set3",
    ]
    assert schemes["Paired"]["classes"]["4"] == ["#a6cee3", "#1f78b4", "#b2df8a", "#33a02c"]
    assert len(schemes["Paired"]["classes"]["12"]) == 12
    # Qualitative sets are prefixes of the largest one; app.js relies on this
    for s in schemes.values():
        big = s["classes"][str(max(map(int, s["classes"])))]
        assert all(v == big[: int(k)] for k, v in s["classes"].items())
    assert {n: config.safe_classes(s) for n, s in schemes.items() if config.safe_classes(s)} == {
        "Paired": 4,
        "Dark2": 3,
        "Set2": 3,
    }


def test_palette_validation(tmp_path):
    assert config.load()["web"]["palette"] == "Paired"
    assert config.load(write(tmp_path, '[web]\npalette = "Set1"\n'))["web"]["palette"] == "Set1"
    with pytest.raises(config.ConfigError, match="palette"):
        config.load(write(tmp_path, '[web]\npalette = "Viridis"\n'))
    with pytest.raises(config.ConfigError, match="colourblind safe"):
        config.load(write(tmp_path, '[web]\npalette = "Set1"\ncolourblind_safe = true\n'))
    c = config.load(write(tmp_path, '[web]\npalette = "Dark2"\ncolourblind_safe = true\n'))
    assert c["web"]["colourblind_safe"] is True


def test_link_defaults_and_palette_export(tmp_path):
    c = config.load(write(tmp_path, '[web]\ndocs_url = ""\npalette = "Set2"\n'))
    assert (
        c["web"]["repo_url"] == "https://github.com/ToledoEM/gnss-ntp-graphs"
        and c["web"]["docs_url"] == ""
    )
    ex = Exporter(Store(str(tmp_path / "s.db")), str(tmp_path / "www"), c)
    ex.web_config()
    out = json.loads((tmp_path / "www" / "data" / "config.json").read_text())
    assert out["palette"]["safe"] == 3 and out["palette"]["classes"]["3"][0] == "#66c2a5"
