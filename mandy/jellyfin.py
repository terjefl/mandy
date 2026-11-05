"""Read episodes and watched status from a Jellyfin library, the same way plex.py does for Plex.

Watched status in Jellyfin belongs to a user, so the config names the user whose status the
index page shows and sets. The API key goes in the Authorization header, never in a URL.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

from .config import Config
from .episode import Episode

log = logging.getLogger(__name__)

NAME = "Jellyfin"
_TICKS_PER_SECOND = 10_000_000
_FIELDS = "Path,PremiereDate"


def _request(cfg: Config, method: str, path: str, params: dict | None = None, timeout: int = 30) -> dict | None:
    jf = cfg.jellyfin
    url = f"{jf.url.rstrip('/')}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method, headers={
        "Accept": "application/json",
        "Authorization": f'MediaBrowser Client="mandy", Device="mandy", DeviceId="mandy", Version="1", Token="{jf.api_key}"',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body) if body else None


def _get(cfg: Config, path: str, params: dict | None = None) -> dict:
    return _request(cfg, "GET", path, params) or {}


def _local_path(cfg: Config, file: str) -> tuple[Path, bool]:
    """The file as this container sees it, and whether it is under library_path (one of ours)."""
    root = cfg.jellyfin.library_path.rstrip("/")
    if file.startswith(root + "/"):
        return cfg.library_dir / file[len(root) + 1:], True
    return Path(file), False


def _episode(cfg: Config, item: dict, file: str, ticks: int | None) -> Episode:
    path, local = _local_path(cfg, file)
    return Episode(
        item_id=str(item["Id"]),
        show=item.get("SeriesName", ""),
        season=int(item.get("ParentIndexNumber") or 0),
        episode=int(item.get("IndexNumber") or 0),
        title=item.get("Name", ""),
        aired=(item.get("PremiereDate") or "")[:10],
        watched=bool((item.get("UserData") or {}).get("Played")),
        path=path,
        local=local,
        duration=(ticks or 0) / _TICKS_PER_SECOND,
    )


def episodes(cfg: Config, include_other: bool = False) -> list[Episode]:
    """Episodes in the Jellyfin libraries whose files are under library_path. With include_other,
    also the rest of the libraries (Mandy's YouTube videos from Pinchflat), as `local=False` with
    Jellyfin's own path. A video in parts (stacked "- pt1", "- pt2" files) is one item in Jellyfin;
    each part becomes an Episode of its own with the item's id, as Plex lists them."""
    jf = cfg.jellyfin
    result = []
    for library in jf.library_ids:
        items = _get(cfg, "/Items", {
            "ParentId": library, "IncludeItemTypes": "Episode", "Recursive": "true", "Fields": _FIELDS,
            "userId": jf.user_id, "EnableImages": "false", "EnableTotalRecordCount": "false",
        }).get("Items", [])
        for item in items:
            parts = [(item.get("Path", ""), item.get("RunTimeTicks"))]
            if (item.get("PartCount") or 1) > 1:
                extra = _get(cfg, f"/Videos/{item['Id']}/AdditionalParts", {"userId": jf.user_id}).get("Items", [])
                parts += [(p.get("Path", ""), p.get("RunTimeTicks")) for p in extra]
            for file, ticks in parts:
                if not file:
                    continue
                ep = _episode(cfg, item, file, ticks)
                if ep.local or include_other:
                    result.append(ep)
    return result


@lru_cache(maxsize=4)
def server_id(url: str) -> str:
    """The server's id, for links; /System/Info/Public needs no key."""
    with urllib.request.urlopen(f"{url.rstrip('/')}/System/Info/Public", timeout=15) as resp:
        return json.loads(resp.read())["Id"]


def web_link(cfg: Config, item_id: str) -> str:
    jf = cfg.jellyfin
    base = (jf.web_url or jf.url).rstrip("/")
    query = urllib.parse.urlencode({"id": item_id, "serverId": server_id(jf.url)})
    return f"{base}/web/#/details?{query}"


def _played(cfg: Config, method: str, item_id: str) -> None:
    jf = cfg.jellyfin
    try:
        _request(cfg, method, f"/UserPlayedItems/{item_id}", {"userId": jf.user_id})
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # servers before 10.9 only have the per-user path
        _request(cfg, method, f"/Users/{jf.user_id}/PlayedItems/{item_id}")


def mark_watched(cfg: Config, item_id: str) -> None:
    _played(cfg, "POST", item_id)


def mark_unwatched(cfg: Config, item_id: str) -> None:
    _played(cfg, "DELETE", item_id)


def refresh_metadata(cfg: Config, item_id: str) -> None:
    """Have Jellyfin re-read an item's metadata (with the Nfo reader: its .nfo sidecar)."""
    _request(cfg, "POST", f"/Items/{item_id}/Refresh", {
        "metadataRefreshMode": "FullRefresh", "imageRefreshMode": "Default",
        "replaceAllMetadata": "true", "replaceAllImages": "false",
    })


def scan(cfg: Config) -> None:
    """Have Jellyfin scan the libraries for new and moved files."""
    for library in cfg.jellyfin.library_ids:
        _request(cfg, "POST", f"/Items/{library}/Refresh", {
            "Recursive": "true", "metadataRefreshMode": "Default", "imageRefreshMode": "Default",
        })


def merge_stale_shows(cfg: Config, show_titles: dict[Path, str]) -> list[tuple[str, str]]:
    """Plex can keep a moved episode under its old show; Jellyfin builds shows from the folders
    and their tvshow.nfo, so a scan puts it right and there is nothing to merge."""
    return []
