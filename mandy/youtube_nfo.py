"""Pinchflat's .nfo files for the creator's YouTube videos, put in the form Plex reads.

Pinchflat writes the date as `<aired>2026-10-12 00:00:00Z</aired>`, which Plex's NFO agent reads
as no date at all (a new video then sorts nowhere), and the channel's name as `<showtitle>`.
Only files with such a date are touched; the rest of the file stays as Pinchflat wrote it."""
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

from . import plex
from .config import Config, CreatorConfig

log = logging.getLogger(__name__)

_AIRED_WITH_TIME = re.compile(r"<aired>(\d{4}-\d{2}-\d{2})[^<]+</aired>")


def fix_nfo(path: Path, show_title: str) -> bool:
    """Set a Pinchflat episode .nfo's date (and show) right. False if it had nothing to fix."""
    text = path.read_text(encoding="utf-8")
    m = _AIRED_WITH_TIME.search(text)
    if not m:
        return False
    day = m[1]
    premiered = "" if "<premiered>" in text else f"\n  <premiered>{day}</premiered>"
    text = text.replace(m[0], f"<aired>{day}</aired>{premiered}")
    text = re.sub(r"<showtitle>[^<]*</showtitle>", f"<showtitle>{escape(show_title)}</showtitle>", text, count=1)
    path.write_text(text, encoding="utf-8")
    return True


def _show_title(show_dir: Path) -> str:
    """The show as Plex names it: its tvshow.nfo title, or else the folder's name."""
    try:
        return ET.parse(show_dir / "tvshow.nfo").getroot().findtext("title") or show_dir.name
    except (OSError, ET.ParseError):
        return show_dir.name


def fix_youtube_nfos(cfg: Config, creator: CreatorConfig) -> list[Path]:
    """Fix every .nfo under the creator's youtube_dir that needs it, and have Plex re-read the
    episodes it already knows (the rest it reads right when it first scans them)."""
    root = Path(creator.youtube_dir or "")
    if not creator.youtube_dir or not root.is_dir():
        if creator.youtube_dir:
            log.warning("youtube_dir %s isn't there; is it mounted?", root)
        return []
    fixed = []
    for nfo in root.rglob("*.nfo"):
        if nfo.name == "tvshow.nfo":
            continue
        try:
            if fix_nfo(nfo, _show_title(nfo.parent.parent)):
                fixed.append(nfo)
        except OSError as e:
            log.warning("Could not fix %s: %s", nfo.name, e)
    if fixed:
        log.info("Set the date in %d YouTube .nfo file(s): %s", len(fixed), ", ".join(f.stem for f in fixed))
    if fixed and cfg.plex:
        stems = {f.stem for f in fixed}
        for ep in plex.episodes(cfg, include_other=True):
            if not ep.local and ep.path.stem in stems:
                plex.refresh_metadata(cfg, ep.rating_key)
    return fixed
