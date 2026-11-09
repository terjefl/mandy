"""Audio loudness (EBU R128) of downloaded videos, for the public pages.

Each file is measured with ffmpeg's loudnorm filter over a window a few minutes into the
video: the level barely varies within an episode, and a window is far quicker than the whole
file. Results live in data/<creator>/loudness.json, keyed by the file's path under the
library together with its size and mtime, so a re-download is measured again.

This is CPU work (audio decoding and the loudness filter have no GPU path in ffmpeg), so the
backfill runs several files at once and stays off the download path.
"""

import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Config, CreatorConfig
from .state import State

log = logging.getLogger(__name__)

# A window a few minutes in: long enough to be representative, short enough to be quick.
WINDOW_OFFSET_SECONDS = 180
WINDOW_SECONDS = 420
DEFAULT_WORKERS = 4
# Files quieter than this are called out on the pages (YouTube normalises to about -14 LUFS).
LOW_LUFS = -24

# The block loudnorm prints with print_format=json
_JSON = re.compile(r'\{[^{}]*"input_i"[^{}]*\}', re.S)


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def _duration(path: Path) -> float | None:
    """The file's length in seconds from ffprobe, or None if it can't be read."""
    ffprobe = ffprobe_path()
    if not ffprobe:
        return None
    cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        value = float((proc.stdout or "").strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _offset(path: Path, offset: int, window: int) -> int:
    """Where the window starts: `offset`, pulled earlier so a full window fits before the end
    (from 0:00 when the file is shorter than offset + window). `offset` if the length is unknown."""
    duration = _duration(path)
    if duration is None:
        return offset
    return int(max(0, min(offset, duration - window)))


def _run(ffmpeg: str, path: Path, offset: int, window: int) -> dict | None:
    cmd = [ffmpeg, "-hide_banner", "-nostats"]
    if offset:
        cmd += ["-ss", str(offset)]
    cmd += [
        "-i", str(path), "-map", "0:a:0",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-t", str(window), "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Measuring %s failed: %s", path.name, e)
        return None
    found = _JSON.findall(proc.stderr or "")
    if not found:
        return None
    try:
        data = json.loads(found[-1])
        lufs, tp, lra = float(data["input_i"]), float(data["input_tp"]), float(data["input_lra"])
    except (ValueError, KeyError):
        return None
    if not all(math.isfinite(x) for x in (lufs, tp, lra)):
        return None  # silence reports "-inf", which is not valid JSON for the page
    return {"lufs": round(lufs, 1), "tp": round(tp, 1), "lra": round(lra, 1)}


def measure_file(path: Path, offset: int = WINDOW_OFFSET_SECONDS, window: int = WINDOW_SECONDS) -> dict | None:
    """Integrated loudness (LUFS), true peak (dBTP) and loudness range of one file, or None if
    ffmpeg is missing or the file can't be read. The window starts early enough to fit before the
    end, so a file shorter than offset + window is measured from the start; if its length can't
    be read, a file shorter than the offset is measured from the start instead."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        return None
    offset = _offset(path, offset, window)
    for off in ((offset, 0) if offset else (0,)):
        values = _run(ffmpeg, path, off, window)
        if values:
            return values
    return None


def _key(path: Path, library_dir: Path) -> str:
    try:
        return path.resolve().relative_to(library_dir.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


class LoudnessStore:
    """data/<creator>/loudness.json: {relpath: {lufs, tp, lra, size, mtime, measured_at}}."""

    def __init__(self, cfg: Config, creator: CreatorConfig):
        self.path = cfg.data_dir / creator.creator / "loudness.json"
        self.library_dir = cfg.library_dir
        self._data: dict | None = None
        self._changed: set[str] = set()

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _load(self) -> dict:
        if self._data is None:
            self._data = self._read()
        return self._data

    def get(self, file: Path) -> dict | None:
        """The stored measurement for `file`, or None if it was never measured or the file changed."""
        entry = self._load().get(_key(file, self.library_dir))
        if not entry:
            return None
        try:
            st = file.stat()
        except OSError:
            return entry
        if entry.get("size") != st.st_size or abs((entry.get("mtime") or 0) - st.st_mtime) > 1:
            return None
        return entry

    def set(self, file: Path, values: dict) -> None:
        try:
            st = file.stat()
            size, mtime = st.st_size, st.st_mtime
        except OSError:
            size, mtime = None, None
        key = _key(file, self.library_dir)
        self._load()[key] = {**values, "size": size, "mtime": mtime, "measured_at": int(time.time())}
        self._changed.add(key)

    def save(self) -> None:
        """Write this store's new measurements over what is on disk now, so a backfill and a
        regular run measuring at the same time don't drop each other's results."""
        data = self._load()
        merged = self._read()
        merged.update({k: data[k] for k in self._changed})
        self._data, self._changed = merged, set()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(merged, indent=1, sort_keys=True))
        os.replace(tmp, self.path)

    def all(self) -> dict:
        return self._load()


VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".m4v", ".mov"}


def done_files(cfg: Config, creator: CreatorConfig) -> list[Path]:
    """Every downloaded file for the creator (status "done" in state.json)."""
    state = State(cfg.data_dir / creator.creator / "state.json")
    return [Path(f) for p in state.posts.values() if p.get("status") == "done" for f in p.get("files", [])]


def youtube_files(creator: CreatorConfig) -> list[Path]:
    """Every video in the creator's youtube_dir (Pinchflat's folder), newest name first."""
    root = Path(creator.youtube_dir or "")
    if not creator.youtube_dir or not root.is_dir():
        return []
    files = [f for f in root.rglob("*") if f.suffix.lower() in VIDEO_SUFFIXES and not f.name.startswith(".") and f.is_file()]
    return sorted(files, key=lambda f: f.name, reverse=True)


def all_files(cfg: Config, creator: CreatorConfig) -> list[Path]:
    """The creator's Patreon downloads and YouTube videos."""
    return done_files(cfg, creator) + youtube_files(creator)


def measure_files(cfg: Config, creator: CreatorConfig, files: list[Path], *,
                  workers: int = DEFAULT_WORKERS, remeasure: bool = False) -> dict:
    """Measure the ones of `files` that exist and aren't measured yet (or all, with remeasure)."""
    store = LoudnessStore(cfg, creator)
    todo = [f for f in files if f.exists() and (remeasure or store.get(f) is None)]
    counts = {"measured": 0, "failed": 0, "skipped": len(files) - len(todo), "total": len(files)}
    if not todo:
        return counts

    def work(f: Path):
        return f, measure_file(f)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i, (f, values) in enumerate(pool.map(work, todo), 1):
            if values:
                store.set(f, values)
                counts["measured"] += 1
            else:
                counts["failed"] += 1
            if i % 20 == 0:
                store.save()
                log.info("%s: measured %d/%d", creator.creator, i, len(todo))
    store.save()
    return counts


def measure_missing(cfg: Config, creator: CreatorConfig, *, limit: int | None = None,
                    workers: int = DEFAULT_WORKERS, remeasure: bool = False) -> dict:
    """Measure every Patreon and YouTube video that lacks a current measurement, optionally
    capped at `limit`."""
    files = all_files(cfg, creator)
    if limit is not None:
        store = LoudnessStore(cfg, creator)
        files = [f for f in files if f.exists() and (remeasure or store.get(f) is None)][:limit]
    return measure_files(cfg, creator, files, workers=workers, remeasure=remeasure)


def summary(cfg: Config, creator: CreatorConfig) -> dict | None:
    """Median loudness and how many measured videos sit below LOW_LUFS, or None if nothing is measured."""
    values = sorted(
        float(e["lufs"]) for e in LoudnessStore(cfg, creator).all().values()
        if isinstance(e.get("lufs"), (int, float)) and math.isfinite(e["lufs"])
    )
    if not values:
        return None
    n = len(values)
    median = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
    below = sum(1 for v in values if v < LOW_LUFS)
    return {
        "count": n,
        "median": round(median, 1),
        "below": below,
        "pct_below": round(100 * below / n),
        "min": round(values[0], 1),
        "max": round(values[-1], 1),
    }
