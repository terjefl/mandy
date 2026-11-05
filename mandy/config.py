from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


@dataclass
class PlexConfig:
    url: str
    token: str
    section_id: int
    library_path: str = "/Media01/Mandy"  # library_dir as Plex sees it
    # Other folders in the library as Plex sees them -> as this container sees them, e.g.
    # {"/Media01/Pinchflat/TV/Mandy Cane Lane - YouTube": "/youtube"}, so their files can be found
    path_map: dict[str, str] = field(default_factory=dict)


@dataclass
class JellyfinConfig:
    url: str  # for the API, e.g. http://10.11.12.16:8096
    api_key: str  # or api_key_file in the YAML: a file holding the key, kept out of the config
    user_id: str  # whose watched status the index page shows and sets
    library_ids: list[str]  # the libraries with the creator's shows (Patreon and YouTube)
    library_path: str = "/Media01/Mandy"  # library_dir as Jellyfin sees it
    web_url: str | None = None  # for links in the browser, e.g. https://jellyfin.flagan.net; defaults to url
    # Other folders in the library as Jellyfin sees them -> as this container sees them, e.g.
    # {"/Media01/YouTube/Mandy": "/youtube"}, so their files can be found
    path_map: dict[str, str] = field(default_factory=dict)


@dataclass
class CreatorConfig:
    creator: str  # slug from patreon.com/c/<creator>
    creator_name: str | None = None
    folder: str | None = None  # subfolder of library_dir; defaults to creator_name or slug; "" = library_dir itself
    since: date | None = None
    max_downloads_per_run: int = 0
    show_name_template: str = "{creator} - {show}"  # folder name
    show_title_template: str = "{show}"  # title shown in Plex
    misc_show_name: str = "{creator}"
    show_aliases: dict[str, str] = field(default_factory=dict)
    # Official special numbers per show, e.g. {"Only Fools And Horses": {"Dates": 8}}
    specials: dict[str, dict[str, int]] = field(default_factory=dict)
    # Title to file a post by instead of its own, per post id, when its title can't say where it
    # belongs, e.g. {"83877577": "Travel Man - S2 E3 - Copenhagen (Noel Fielding)"}
    title_overrides: dict[str, str] = field(default_factory=dict)
    # The creator's YouTube channel (e.g. https://www.youtube.com/@MandyCaneLane), for the statistics page
    youtube_url: str | None = None
    # Where Pinchflat puts the channel's videos, as this container sees it: their .nfo files get
    # the date in a form Plex reads
    youtube_dir: str | None = None

    @property
    def campaign_url(self) -> str:
        return f"https://www.patreon.com/c/{self.creator}/posts"

    @property
    def folder_name(self) -> str:
        return self.folder if self.folder is not None else (self.creator_name or self.creator)


@dataclass
class Config:
    library_dir: Path
    cookies_file: Path
    data_dir: Path
    creators: list[CreatorConfig]
    interval_minutes: int = 60
    # Throttling, so a backlog doesn't look like a scraper: max download speed
    # (yt-dlp syntax, e.g. "4M" = 4 MiB/s) and a random pause between videos.
    rate_limit: str | None = None
    pause_seconds: tuple[int, int] = (0, 0)
    heartbeat_url: str | None = None
    web_port: int | None = 8000  # index page (needs a media server); None to disable
    plex: PlexConfig | None = None
    jellyfin: JellyfinConfig | None = None
    # "plex" or "jellyfin": which one to use when both are configured (Plex unless set);
    # with only one configured, that one
    media_server: str | None = None

    def find_creator(self, slug: str) -> CreatorConfig:
        for c in self.creators:
            if c.creator.casefold() == slug.casefold():
                return c
        raise SystemExit(f"No creator {slug!r} in config")


def _creator(raw: dict) -> CreatorConfig:
    since = raw.pop("since", None)
    if isinstance(since, str):
        since = date.fromisoformat(since)
    return CreatorConfig(**raw, since=since)


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text()) or {}
    plex = raw.pop("plex", None)
    jellyfin = raw.pop("jellyfin", None)
    if jellyfin and "library_id" in jellyfin:
        jellyfin["library_ids"] = [jellyfin.pop("library_id")]
    if jellyfin and isinstance(jellyfin.get("library_ids"), str):
        jellyfin["library_ids"] = [jellyfin["library_ids"]]
    if jellyfin and jellyfin.get("api_key_file"):
        jellyfin["api_key"] = Path(jellyfin.pop("api_key_file")).read_text().strip()
    if raw.get("media_server") not in (None, "plex", "jellyfin"):
        raise SystemExit(f"media_server must be plex or jellyfin, not {raw['media_server']!r}")
    creators = [_creator(c) for c in raw.pop("creators", [])]
    if not creators:
        raise SystemExit("Config needs at least one entry under 'creators'")
    for key in ("library_dir", "cookies_file", "data_dir"):
        raw[key] = Path(raw[key])
    pause = raw.pop("pause_seconds", None)
    if isinstance(pause, (int, float)):
        pause = (pause, pause)
    return Config(
        **raw,
        pause_seconds=tuple(pause) if pause else (0, 0),
        creators=creators,
        plex=PlexConfig(**plex) if plex and plex.get("token") else None,
        jellyfin=JellyfinConfig(**jellyfin) if jellyfin and jellyfin.get("api_key") else None,
    )
