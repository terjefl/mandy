import re

from mandy import levels_page, loudness, stats_page, web
from mandy.config import Config, CreatorConfig, PlexConfig


def _cfg(tmp_path):
    return Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data",
                  creators=[CreatorConfig(creator="Mandy Cane Lane", creator_name="Mandy Cane Lane")],
                  plex=PlexConfig(url="http://x", token="t", section_id=18))


def _rows(tmp_path, cfg, levels):
    """A measured file and a Row for each (title, lufs); lufs None leaves it unmeasured."""
    lib = cfg.library_dir
    lib.mkdir(parents=True, exist_ok=True)
    store = loudness.LoudnessStore(cfg, cfg.creators[0])
    rows = []
    for i, (title, lufs) in enumerate(levels):
        f = lib / f"{i}.mp4"
        f.write_bytes(b"x" * (i + 1))
        if lufs is not None:
            store.set(f, {"lufs": lufs, "tp": -1.5, "lra": 5.0})
        rows.append(web.Row("Mandy Cane Lane", "Mandy Cane Lane - Crafts", 1, i + 1, title, f"2024-01-{i + 1:02d}",
                            True, True, f"https://www.patreon.com/posts/{i}", "p", str(i), duration=600, path=f))
    store.save()
    return rows


def test_levels_page_is_public_safe_and_in_english(tmp_path):
    cfg = _cfg(tmp_path)
    rows = _rows(tmp_path, cfg, [("Knitting", -27.3), ("Baking", -15.2)])
    html = levels_page.render_levels(rows, cfg, cfg.creators[0])
    assert 'lang="en"' in html and "<title>Mandy Cane Lane: audio levels</title>" in html
    assert "−27.3" in html and 'role="img"' in html
    assert "1 of 2" in html  # under -24 LUFS
    assert 'href="statistics"' in html and 'href="videos"' in html
    assert ">Crafts S01E01<" in html.replace('class="series">', ">")
    text = html.casefold()
    for word in ("watched", "liked", "plex", "download", "library"):
        assert word not in text, word


def test_levels_table_is_newest_first_and_skips_unmeasured(tmp_path):
    cfg = _cfg(tmp_path)
    rows = _rows(tmp_path, cfg, [("Mid", -20.0), ("Unmeasured", None), ("Quiet", -31.0), ("Loud", -14.0)])
    rows.append(web.Row("Mandy Cane Lane", "Mandy Cane Lane", 2026, 1, "No file", "2026-01-01",
                        False, None, "", "", "9", source="youtube"))
    html = levels_page.render_levels(rows, cfg, cfg.creators[0])
    titles = re.findall(r'<td class="title">([^<]*)</td>', html)
    assert titles == ["Loud", "Quiet", "Mid"]  # by date, newest first
    assert 'class="lufs low"' in html and 'class="lufs mid"' in html and 'class="lufs good"' in html


def test_levels_page_without_measurements_shows_a_friendly_note(tmp_path):
    cfg = _cfg(tmp_path)  # no loudness.json at all
    rows = _rows(tmp_path, cfg, [("Knitting", None)])
    html = levels_page.render_levels(rows, cfg, cfg.creators[0])
    assert "still being measured" in html
    assert "<table" not in html and "<svg" not in html
    assert levels_page.render_levels([], cfg, cfg.creators[0])  # no rows either


def test_histogram_takes_levels_outside_the_usual_range(tmp_path):
    cfg = _cfg(tmp_path)
    rows = _rows(tmp_path, cfg, [("Very quiet", -41.0), ("Very loud", -5.0), ("Edge", -8.0)])
    html = levels_page.render_levels(rows, cfg, cfg.creators[0])
    assert html.count('<rect class="bar') == 3


def test_statistics_links_to_the_levels_page(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(stats_page, "collect", lambda cfg, creator: [("patreon", "2023-01-02", 3600)])
    assert '<a href="levels">Audio levels</a>' in stats_page.render_stats(cfg, cfg.creators[0])
    assert web.render_levels is levels_page.render_levels  # the route's renderer
