from pathlib import Path

from mandy import plex, web, youtube_nfo
from mandy.config import Config, CreatorConfig, PlexConfig

# As Pinchflat writes it
PINCHFLAT = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<episodedetails>
  <title>SEAN LOCK Mascots - 8 Out of 10 Cats Does Countdown - REACTION!</title>
  <showtitle>Mandy Cane Lane</showtitle>
  <uniqueid type="youtube" default="true">doBX3NP18pg</uniqueid>
  <plot>#reaction &amp; more</plot>
  <aired>2026-10-12 00:00:00Z</aired>
  <season>2026</season>
  <episode>101299</episode>
  <genre>YouTube</genre>
</episodedetails>
"""
# As the rest of the library has it
FIXED = """<?xml version="1.0" encoding="utf-8"?>
<episodedetails>
  <title>WALLY</title>
  <showtitle>Mandy Cane Lane - YouTube</showtitle>
  <aired>2026-10-09</aired>
  <premiered>2026-10-09</premiered>
</episodedetails>
"""


def setup(tmp_path):
    season = tmp_path / "yt" / "Mandy Cane Lane - YouTube" / "Season 2026"
    season.mkdir(parents=True)
    new = season / "s2026e101299 - SEAN LOCK Mascots [doBX3NP18pg].nfo"
    new.write_text(PINCHFLAT)
    old = season / "s2026e100999 - WALLY [gtitf4ECTzY].nfo"
    old.write_text(FIXED)
    creator = CreatorConfig(creator="M", creator_name="Mandy Cane Lane", youtube_dir=str(tmp_path / "yt"))
    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data",
                 creators=[creator], plex=PlexConfig(url="http://x", token="t", section_id=18))
    return cfg, creator, new, old


def test_pinchflat_date_and_show_are_set_right_and_plex_rereads_it(tmp_path, monkeypatch):
    cfg, creator, new, old = setup(tmp_path)
    plex_path = Path("/Media01/Pinchflat/TV/Mandy Cane Lane - YouTube/Mandy Cane Lane - YouTube/Season 2026")
    monkeypatch.setattr(plex, "episodes", lambda cfg, include_other=False: [
        plex.PlexEpisode("28382", "Mandy Cane Lane - YouTube", 2026, 101299, "SEAN LOCK", "", False,
                         plex_path / (new.stem + ".mp4"), local=False),
        plex.PlexEpisode("27341", "Mandy Cane Lane - YouTube", 2026, 100999, "WALLY", "2026-10-09", True,
                         plex_path / (old.stem + ".mp4"), local=False),
    ])
    refreshed = []
    monkeypatch.setattr(plex, "refresh_metadata", lambda cfg, key: refreshed.append(key))

    assert youtube_nfo.fix_youtube_nfos(cfg, creator) == [new]
    text = new.read_text()
    assert "<aired>2026-10-12</aired>\n  <premiered>2026-10-12</premiered>" in text
    assert "<showtitle>Mandy Cane Lane - YouTube</showtitle>" in text
    assert "<plot>#reaction &amp; more</plot>" in text and "<episode>101299</episode>" in text  # the rest as it was
    assert old.read_text() == FIXED  # a file already right is left alone
    assert refreshed == ["28382"]
    # and a second run has nothing to do
    assert youtube_nfo.fix_youtube_nfos(cfg, creator) == [] and refreshed == ["28382"]


def test_missing_youtube_dir_is_skipped(tmp_path):
    cfg, creator, _, _ = setup(tmp_path)
    creator.youtube_dir = str(tmp_path / "not mounted")
    assert youtube_nfo.fix_youtube_nfos(cfg, creator) == []
    creator.youtube_dir = None
    assert youtube_nfo.fix_youtube_nfos(cfg, creator) == []


def test_page_takes_the_date_from_a_pinchflat_name_when_plex_has_none():
    assert web._date_from_name("s2026e101299 - SEAN LOCK Mascots [doBX3NP18pg].mp4") == "2026-10-12"
    assert web._date_from_name("Mandy Cane Lane - S2026E09 - Live At The Apollo.mp4") == ""
    assert web._date_from_name("s2026e991299 - odd.mp4") == ""
