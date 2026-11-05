import io
import json
import urllib.error
from pathlib import Path

from mandy import jellyfin, media, plex, web
from mandy.config import Config, CreatorConfig, JellyfinConfig, PlexConfig, load_config

LIB = "f137a2dd21bbc1b99aa5c0f6bf02a805"
YT_LIB = "a656b907eb3a73532e40e44b968d0225"
GUID = "4ad2c7f6e5b04c1f9e1a3b2c1d0e9f8a"


def _cfg(tmp_path, **jf):
    jf = {"url": "http://jf:8096", "api_key": "secret", "user_id": "u1", "library_ids": [LIB],
          "library_path": "/media/Mandy", "web_url": "https://jellyfin.example", **jf}
    return Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data",
                  creators=[CreatorConfig(creator="M", creator_name="Mandy")],
                  plex=PlexConfig(url="http://plex", token="t", section_id=1),
                  jellyfin=JellyfinConfig(**jf))


def _item(id, show, s, e, title, path, played=False, premiere="2024-03-01T00:00:00.0000000Z", ticks=6_000_000_000, **kw):
    return {"Id": id, "SeriesName": show, "ParentIndexNumber": s, "IndexNumber": e, "Name": title, "Path": path,
            "PremiereDate": premiere, "RunTimeTicks": ticks, "UserData": {"Played": played}, **kw}


class FakeServer:
    """Answers urlopen like Jellyfin, from a dict of path -> JSON; records each request."""

    def __init__(self, responses: dict, missing: tuple = ()):
        self.responses, self.missing, self.calls = responses, missing, []

    def __call__(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        method = "GET" if isinstance(req, str) else req.get_method()
        headers = {} if isinstance(req, str) else dict(req.header_items())
        self.calls.append((method, url, headers))
        path = url.split("://", 1)[1].split("/", 1)[1].split("?", 1)[0]
        if "/" + path in self.missing:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        body = json.dumps(self.responses["/" + path]).encode() if "/" + path in self.responses else b""
        return io.BytesIO(body)


def test_episodes_map_paths_dates_watched_and_parts(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, library_ids=[LIB, YT_LIB])
    server = FakeServer({
        "/Items": {"Items": [
            _item("a1", "Taskmaster", 21, 1, "Cube", "/media/Mandy/Taskmaster/S21E01 - Cube.mp4", played=True),
            _item("a2", "Peep Show", 3, 1, "Mugging", "/media/Mandy/Peep Show/S03E01 - Mugging - pt1.mp4",
                  ticks=12_000_000_000, PartCount=2),
            _item("y1", "Mandy Cane Lane - YouTube", 2026, 100999, "WALLY", "/youtube/Mandy/WALLY [abcdefghijk].mp4",
                  premiere=None),
        ]},
        "/Videos/a2/AdditionalParts": {"Items": [
            {"Id": "a2p", "Path": "/media/Mandy/Peep Show/S03E01 - Mugging - pt2.mp4", "RunTimeTicks": 3_000_000_000}]},
    })
    monkeypatch.setattr(jellyfin.urllib.request, "urlopen", server)

    ours = media.episodes(cfg)
    assert [(e.item_id, e.path.name, e.duration) for e in ours] == [  # once per library in this fake
        ("a1", "S21E01 - Cube.mp4", 600.0), ("a2", "S03E01 - Mugging - pt1.mp4", 1200.0),
        ("a2", "S03E01 - Mugging - pt2.mp4", 300.0)] * 2
    cube = ours[0]
    assert cube.path == cfg.library_dir / "Taskmaster" / "S21E01 - Cube.mp4"
    assert cube.watched and cube.aired == "2024-03-01" and (cube.season, cube.episode) == (21, 1)

    every = media.episodes(cfg, include_other=True)
    other = [e for e in every if not e.local]
    assert other[0].path == Path("/youtube/Mandy/WALLY [abcdefghijk].mp4") and other[0].aired == ""

    get = [c for c in server.calls if c[1].startswith("http://jf:8096/Items?")]
    assert "ParentId=" + LIB in get[0][1] and "ParentId=" + YT_LIB in get[-1][1] and "userId=u1" in get[0][1]
    for _, url, headers in server.calls:
        assert "secret" not in url  # the key travels in the header only
        assert 'Token="secret"' in headers["Authorization"]


def test_marking_watched_falls_back_to_the_old_path(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    new = FakeServer({})
    monkeypatch.setattr(jellyfin.urllib.request, "urlopen", new)
    media.mark_watched(cfg, GUID)
    media.mark_unwatched(cfg, GUID)
    assert [(m, u.split("?")[0]) for m, u, _ in new.calls] == [
        ("POST", f"http://jf:8096/UserPlayedItems/{GUID}"), ("DELETE", f"http://jf:8096/UserPlayedItems/{GUID}")]

    old = FakeServer({}, missing=(f"/UserPlayedItems/{GUID}",))
    monkeypatch.setattr(jellyfin.urllib.request, "urlopen", old)
    media.mark_watched(cfg, GUID)
    assert old.calls[-1][:2] == ("POST", f"http://jf:8096/Users/u1/PlayedItems/{GUID}")


def test_link_refresh_and_scan(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    jellyfin.server_id.cache_clear()
    server = FakeServer({"/System/Info/Public": {"Id": "srv1"}})
    monkeypatch.setattr(jellyfin.urllib.request, "urlopen", server)
    assert media.web_link(cfg, GUID) == f"https://jellyfin.example/web/#/details?id={GUID}&serverId=srv1"
    media.refresh_metadata(cfg, GUID)
    media.scan(cfg)
    posts = [u for m, u, _ in server.calls if m == "POST"]
    assert posts[0].startswith(f"http://jf:8096/Items/{GUID}/Refresh?") and "replaceAllMetadata=true" in posts[0]
    assert posts[1].startswith(f"http://jf:8096/Items/{LIB}/Refresh?") and "Recursive=true" in posts[1]
    assert media.merge_stale_shows(cfg, {}) == []
    assert media.name(cfg) == "Jellyfin"


def test_config_picks_jellyfin_over_plex(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "library_dir: /library\ncookies_file: /c\ndata_dir: /data\ncreators: [{creator: M}]\n"
        "plex: {url: http://plex, token: t, section_id: 1}\n"
        f"jellyfin: {{url: http://jf, api_key: k, user_id: u, library_id: {LIB}}}\n"
    )
    cfg = load_config(path)
    assert cfg.jellyfin.library_ids == [LIB] and media.name(cfg) == "Jellyfin"
    path.write_text(path.read_text().replace("api_key: k, ", ""))  # without a key it stays off
    assert load_config(path).jellyfin is None and media.name(load_config(path)) == "Plex"


def test_index_with_jellyfin_ids_links_and_sorts(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    files = [cfg.library_dir / "a.mp4", cfg.library_dir / "b.mp4"]
    from mandy.episode import Episode

    monkeypatch.setattr(jellyfin, "episodes", lambda cfg, include_other=False: [
        Episode(GUID, "Taskmaster", 21, 2, "Two", "2026-10-01", False, files[0]),
        Episode("0" + GUID[1:], "Taskmaster", 21, 1, "One", "2026-10-01", True, files[1]),
    ])
    monkeypatch.setattr(jellyfin, "web_link", lambda cfg, key: "https://jellyfin.example/" + key)
    monkeypatch.setattr(plex, "episodes", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Plex asked")))
    monkeypatch.setattr(web, "post_files", lambda posts: {f: str(i) for i, f in enumerate(files)})
    index = web.Index(cfg)
    html = web.render_chrono(index)  # GUIDs are not numbers; sorting must not need them to be
    assert html.index(" Two</td>") < html.index(" One</td>")
    assert f'href="https://jellyfin.example/{GUID}"' in html and ">Jellyfin</a>" in html
    assert "i Jellyfin" in html and "Plex" not in html
