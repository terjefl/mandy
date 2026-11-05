"""An episode as the media server (Plex or Jellyfin) lists it."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Episode:
    item_id: str  # the server's id: a Plex rating key or a Jellyfin item id
    show: str
    season: int
    episode: int
    title: str
    aired: str  # YYYY-MM-DD
    watched: bool
    path: Path  # as this container sees it; for other sources, as the server sees it
    local: bool = True  # under library_path, i.e. one of ours
    duration: float = 0.0  # seconds
