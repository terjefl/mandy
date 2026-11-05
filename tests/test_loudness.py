import json
from pathlib import Path
from types import SimpleNamespace

from mandy import loudness, public_page, web
from mandy.config import Config, CreatorConfig, PlexConfig


def _cfg(tmp_path):
    return Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data",
                  creators=[CreatorConfig(creator="M", creator_name="Mandy Cane Lane")],
                  plex=PlexConfig(url="http://x", token="t", section_id=18))


def test_measure_file_parses_loudnorm_json(tmp_path, monkeypatch):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(loudness, "ffmpeg_path", lambda: "ffmpeg")
    stderr = 'size=N/A time=N/A ... {"input_i" : "-27.85", "input_tp" : "-3.10", "input_lra" : "5.20", "output_i" : "-16.00"}'
    monkeypatch.setattr(loudness.subprocess, "run", lambda *a, **k: SimpleNamespace(stderr=stderr))
    assert loudness.measure_file(f) == {"lufs": -27.9, "tp": -3.1, "lra": 5.2}


def test_measure_file_rejects_non_finite(tmp_path, monkeypatch):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(loudness, "ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(loudness.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stderr='{"input_i":"-inf","input_tp":"-inf","input_lra":"0.0"}'))
    assert loudness.measure_file(f) is None


def test_measure_file_without_ffmpeg_returns_none(tmp_path, monkeypatch):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(loudness, "ffmpeg_path", lambda: None)
    assert loudness.measure_file(f) is None


def test_store_roundtrip_and_staleness(tmp_path):
    cfg = _cfg(tmp_path)
    lib = cfg.library_dir
    f = lib / "show" / "ep.mp4"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"abc")
    store = loudness.LoudnessStore(cfg, cfg.creators[0])
    assert store.get(f) is None
    store.set(f, {"lufs": -28.0, "tp": -2.0, "lra": 6.0})
    store.save()
    assert loudness.LoudnessStore(cfg, cfg.creators[0]).get(f)["lufs"] == -28.0
    f.write_bytes(b"abcd")  # size changed -> the stored measurement is stale
    assert loudness.LoudnessStore(cfg, cfg.creators[0]).get(f) is None


def test_summary_median_and_below(tmp_path):
    cfg = _cfg(tmp_path)
    lib = cfg.library_dir
    lib.mkdir(parents=True)
    store = loudness.LoudnessStore(cfg, cfg.creators[0])
    for i, v in enumerate([-28, -26, -30, -19, -18]):
        f = lib / f"{i}.mp4"
        f.write_bytes(b"x")
        store.set(f, {"lufs": v, "tp": -1.0, "lra": 5.0})
    store.save()
    s = loudness.summary(cfg, cfg.creators[0])
    assert s["count"] == 5 and s["median"] == -26.0
    assert s["below"] == 3 and s["pct_below"] == 60
    assert s["min"] == -30 and s["max"] == -18


def test_public_items_carry_weighted_lufs_and_clean_keys(tmp_path):
    cfg = _cfg(tmp_path)
    lib = cfg.library_dir
    lib.mkdir(parents=True)
    f1, f2 = lib / "a.mp4", lib / "b.mp4"
    f1.write_bytes(b"x")
    f2.write_bytes(b"y")
    store = loudness.LoudnessStore(cfg, cfg.creators[0])
    store.set(f1, {"lufs": -30.0, "tp": -1, "lra": 5})
    store.set(f2, {"lufs": -20.0, "tp": -1, "lra": 5})
    store.save()
    url = "https://www.patreon.com/posts/1"
    rows = [
        web.Row("Mandy Cane Lane", "S", 1, 1, "Ep - pt1", "2024-01-01", True, True, url, "p1", "1", duration=300, path=f1),
        web.Row("Mandy Cane Lane", "S", 1, 1, "Ep - pt2", "2024-01-01", True, True, url, "p2", "2", duration=100, path=f2),
    ]
    entries = public_page.items(rows, cfg, cfg.creators[0])
    pat = [e for e in entries if e["s"] == "patreon"][0]
    assert pat["lufs"] == -27.5  # (-30*300 + -20*100) / 400
    assert not any(k.startswith("_") for k in pat)


def test_stats_page_shows_loudness_section(tmp_path, monkeypatch):
    from mandy import stats_page

    cfg = _cfg(tmp_path)
    lib = cfg.library_dir
    lib.mkdir(parents=True)
    store = loudness.LoudnessStore(cfg, cfg.creators[0])
    f = lib / "a.mp4"
    f.write_bytes(b"x")
    store.set(f, {"lufs": -28, "tp": -1, "lra": 5})
    store.save()
    monkeypatch.setattr(stats_page, "collect", lambda cfg, creator: [("patreon", "2023-01-02", 3600)])
    html = stats_page.render_stats(cfg, cfg.creators[0])
    assert "Audio levels" in html and "LUFS" in html


def test_public_videos_page_shows_a_lufs_badge(tmp_path):
    cfg = _cfg(tmp_path)
    lib = cfg.library_dir
    lib.mkdir(parents=True)
    f = lib / "a.mp4"
    f.write_bytes(b"x")
    store = loudness.LoudnessStore(cfg, cfg.creators[0])
    store.set(f, {"lufs": -27, "tp": -1, "lra": 5})
    store.save()
    rows = [web.Row("Mandy Cane Lane", "S", 1, 1, "Ep", "2024-01-01", True, True,
                    "https://www.patreon.com/posts/1", "p", "1", duration=300, path=f)]
    html = public_page.render_videos(rows, cfg, cfg.creators[0])
    assert '"lufs":-27' in html or '"lufs": -27' in html
