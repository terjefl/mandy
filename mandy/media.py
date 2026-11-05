"""The media server the library lives in: the one `media_server` names, or the only one
configured (Plex when both are and nothing is named). Callers use these functions and never
the server modules directly, so moving from one server to the other is a config change."""

from pathlib import Path
from types import ModuleType

from . import jellyfin, plex
from .config import Config
from .episode import Episode

__all__ = ["Episode", "enabled", "name", "episodes", "web_link", "mark_watched", "mark_unwatched",
           "refresh_metadata", "scan", "merge_stale_shows"]


def _pick(cfg: Config) -> ModuleType | None:
    if cfg.media_server == "jellyfin":
        return jellyfin if cfg.jellyfin else None
    if cfg.media_server == "plex":
        return plex if cfg.plex else None
    return plex if cfg.plex else jellyfin if cfg.jellyfin else None


def _server(cfg: Config) -> ModuleType:
    server = _pick(cfg)
    if server is None:
        raise RuntimeError("No media server in the config: a `jellyfin` or `plex` section, as `media_server` names")
    return server


def enabled(cfg: Config) -> bool:
    return _pick(cfg) is not None


def name(cfg: Config) -> str:
    return _server(cfg).NAME if enabled(cfg) else ""


def episodes(cfg: Config, include_other: bool = False) -> list[Episode]:
    return _server(cfg).episodes(cfg, include_other=include_other)


def web_link(cfg: Config, item_id: str) -> str:
    return _server(cfg).web_link(cfg, item_id)


def mark_watched(cfg: Config, item_id: str) -> None:
    _server(cfg).mark_watched(cfg, item_id)


def mark_unwatched(cfg: Config, item_id: str) -> None:
    _server(cfg).mark_unwatched(cfg, item_id)


def refresh_metadata(cfg: Config, item_id: str) -> None:
    _server(cfg).refresh_metadata(cfg, item_id)


def scan(cfg: Config) -> None:
    _server(cfg).scan(cfg)


def merge_stale_shows(cfg: Config, show_titles: dict[Path, str]) -> list[tuple[str, str]]:
    return _server(cfg).merge_stale_shows(cfg, show_titles)
