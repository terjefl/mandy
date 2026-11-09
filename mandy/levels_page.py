"""Public audio-levels page: how loud each of a creator's videos is mastered.

In English, for sharing with the creator, and free of anything private: only her videos, their
dates and their measured levels.
"""

import html
import math
import time

from . import favicon
from .config import Config, CreatorConfig
from .loudness import LOW_LUFS, LoudnessStore

# Reference levels marked on the histogram: (LUFS, label)
REFERENCES = ((-14, "YouTube"), (-16, "Podcast"), (-24, "−24"))
HIST_MIN, HIST_MAX, HIST_STEP = -36, -8, 2


def _e(text) -> str:
    return html.escape(str(text))


def _num(value: float) -> str:
    """A level with a real minus sign: -27.5 -> '−27.5'."""
    return f"{value:.1f}".replace("-", "−")


def entries(rows: list, cfg: Config, creator: CreatorConfig) -> list[dict]:
    """One entry per measured video, newest first."""
    store = LoudnessStore(cfg, creator)
    out = []
    for r in rows:
        if r.path is None:
            continue
        info = store.get(r.path)
        if not info or not isinstance(info.get("lufs"), (int, float)):
            continue
        show = r.show.removeprefix(r.creator + " - ") if r.show != r.creator else r.show
        out.append({
            "show": show, "code": r.code, "title": r.title, "aired": r.aired,
            "lufs": float(info["lufs"]), "tp": info.get("tp"),
        })
    out.sort(key=lambda e: (e["aired"] or "", e["code"] or "", e["title"] or ""), reverse=True)
    return out


def _summary(values: list[float]) -> dict:
    n = len(values)
    s = sorted(values)
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    below = sum(1 for v in s if v < LOW_LUFS)
    return {"count": n, "median": median, "below": below, "pct_below": round(100 * below / n),
            "min": s[0], "max": s[-1]}


def _tile(value: str, label: str, note: str) -> str:
    return f'<div class="tile"><div class="label">{_e(label)}</div><div class="big">{_e(value)}</div><div class="note">{_e(note)}</div></div>'


def _tiles(s: dict) -> str:
    return (
        _tile(f"{s['median']:.0f} LUFS".replace("-", "−"), "Typical level", f"median of {s['count']:,} videos")
        + _tile(f"{s['below']:,} of {s['count']:,}", f"Under −{abs(LOW_LUFS)} LUFS", f"{s['pct_below']}% sit low")
        + _tile(f"{s['min']:.0f} … {s['max']:.0f}".replace("-", "−"), "Range", "quietest to loudest, LUFS")
    )


def _histogram(values: list[float]) -> str:
    """Count of videos per 2 dB bucket of integrated loudness, with reference lines."""
    # widen the fixed range if a video falls outside it
    lo = min(HIST_MIN, HIST_STEP * math.floor(min(values) / HIST_STEP))
    hi = max(HIST_MAX, HIST_STEP * math.ceil(max(values) / HIST_STEP))
    edges = list(range(lo, hi, HIST_STEP))
    counts = [0] * len(edges)
    for v in values:
        counts[min(int((v - lo) // HIST_STEP), len(edges) - 1)] += 1
    top = max(counts + [1])
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500) if top / s <= 5)
    ymax = step * (int(top // step) + 1)
    w, h, left, bottom, top_pad = 960, 280, 40, 28, 22
    plot_w, plot_h = w - left - 8, h - bottom - top_pad
    base = top_pad + plot_h

    def x_of(lufs: float) -> float:
        return left + plot_w * (lufs - lo) / (hi - lo)

    parts = []
    for t in range(0, ymax + 1, step):
        yy = base - plot_h * t / ymax
        parts.append(f'<line class="grid" x1="{left}" x2="{w - 8}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 6}" y="{yy + 4:.1f}" text-anchor="end">{t}</text>')
    band = plot_w / len(edges)
    for e, c in zip(edges, counts):
        if not c:
            continue
        bh = plot_h * c / ymax
        cls = "good" if e >= -18 else "mid" if e >= LOW_LUFS else "low"
        parts.append(
            f'<rect class="bar {cls}" x="{x_of(e) + 1:.1f}" y="{base - bh:.1f}" width="{band - 2:.1f}" height="{bh:.1f}">'
            f'<title>{_num(e)} to {_num(e + HIST_STEP)} LUFS: {c} video{"s" if c != 1 else ""}</title></rect>'
        )
    for e in range(lo, hi + 1, 4):
        parts.append(f'<text class="tick" x="{x_of(e):.1f}" y="{h - 8}" text-anchor="middle">{str(e).replace("-", chr(0x2212))}</text>')
    for lufs, label in REFERENCES:
        xx = x_of(lufs)
        parts.append(f'<line class="ref" x1="{xx:.1f}" x2="{xx:.1f}" y1="{top_pad - 4}" y2="{base}"/>')
        parts.append(f'<text class="ref-label" x="{xx:.1f}" y="{top_pad - 8}" text-anchor="middle">{_e(label)}</text>')
    parts.append(f'<line class="axis" x1="{left}" x2="{w - 8}" y1="{base}" y2="{base}"/>')
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Number of videos per 2 dB of loudness, '
        f'from {_num(lo)} to {_num(hi)} LUFS, with YouTube (−14), podcast (−16) and −24 LUFS marked">'
        + "".join(parts)
        + "</svg>"
    )


def _badge(lufs: float) -> str:
    cls = "good" if lufs >= -18 else "mid" if lufs >= LOW_LUFS else "low"
    return f'<span class="lufs {cls}">{_num(lufs)}</span>'


def _table(items: list[dict]) -> str:
    rows = []
    for e in items:
        series = " ".join(_e(x) for x in (e["show"], e["code"]) if x)
        tp = _num(float(e["tp"])) if isinstance(e["tp"], (int, float)) else ""
        rows.append(
            f'<tr><td class="series">{series}</td><td class="title">{_e(e["title"])}</td>'
            f'<td class="date">{_e(e["aired"])}</td><td>{_badge(e["lufs"])}</td><td>{tp}</td></tr>'
        )
    return (
        '<div class="scroll"><table><thead><tr><th>Series</th><th>Title</th><th>Date</th>'
        '<th class="num">LUFS</th><th class="num">True peak (dBTP)</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


NOTE = (
    '<p class="note">Integrated loudness (EBU R128), measured over a few minutes of each video. '
    'YouTube turns loudness down to about −14 LUFS and never turns it up, so a quiet master '
    'plays quietly everywhere. Common targets: YouTube −14, podcasts −16, broadcast −23 LUFS.</p>'
)


def render_levels(rows: list, cfg: Config, creator: CreatorConfig) -> str:
    name = creator.creator_name or creator.creator
    items = entries(rows, cfg, creator)
    if items:
        values = [e["lufs"] for e in items]
        body = (
            f'<div class="tiles">{_tiles(_summary(values))}</div>'
            f'<section><h2>About these numbers</h2>{NOTE}</section>'
            '<section><h2>Distribution</h2>'
            '<div class="legend"><span><span class="key good"></span>−18 or louder</span>'
            f'<span><span class="key mid"></span>−18 to −{abs(LOW_LUFS)}</span>'
            f'<span><span class="key low"></span>under −{abs(LOW_LUFS)}</span></div>'
            f'{_histogram(values)}</section>'
            f'<section><h2>Every video, newest first</h2>{_table(items)}</section>'
        )
    else:
        body = (
            '<section class="empty"><p>Audio levels are still being measured — check back soon.</p>'
            f'{NOTE}</section>'
        )
    return PAGE.format(name=_e(name), body=body, updated=time.strftime("%-d %b %Y"))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + favicon.LINKS + """<title>{name}: audio levels</title>
<style>
:root {{ color-scheme: light; --bg:#f6f5f2; --card:#fcfcfb; --fg:#0b0b0b; --muted:#52514e; --line:#e4e2dd;
  --grid:#ecebe7; --link:#2a78d6; --good:#2f8f4e; --mid:#c99a06; --low:#d03b3b; --ref:#8a8984; }}
@media (prefers-color-scheme: dark) {{ :root {{ color-scheme: dark; --bg:#121211; --card:#1a1a19; --fg:#fff;
  --muted:#c3c2b7; --line:#2e2e2b; --grid:#262624; --link:#3987e5; --good:#4cb26c; --mid:#e0b42a;
  --low:#e5605c; --ref:#8f8e88; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,system-ui,Segoe UI,Roboto,sans-serif }}
main {{ max-width:1000px; margin:0 auto; padding:28px 16px 64px }}
h1 {{ margin:0; font-size:28px }} h2 {{ font-size:18px; margin:0 0 10px }}
.sub, .note {{ color:var(--muted) }} .sub a {{ color:var(--link) }} .note {{ font-size:13px; margin:6px 0 0 }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:20px 0 }}
.tile, section {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px }}
section {{ margin:12px 0 }}
.tile .label {{ color:var(--muted); font-size:13px }}
.tile .big {{ font-size:26px; font-weight:650; font-variant-numeric:tabular-nums; margin:2px 0 }}
.legend {{ display:flex; flex-wrap:wrap; gap:16px; font-size:13px; color:var(--muted); margin-bottom:6px }}
.legend > span {{ display:flex; align-items:center; gap:6px }}
.key {{ display:inline-block; width:10px; height:10px; border-radius:3px }}
.key.good {{ background:var(--good) }} .key.mid {{ background:var(--mid) }} .key.low {{ background:var(--low) }}
svg {{ width:100%; height:auto; display:block }}
.grid {{ stroke:var(--grid); stroke-width:1 }} .axis {{ stroke:var(--line); stroke-width:1 }}
.tick {{ fill:var(--muted); font-size:11px }}
.bar.good {{ fill:var(--good) }} .bar.mid {{ fill:var(--mid) }} .bar.low {{ fill:var(--low) }}
.ref {{ stroke:var(--ref); stroke-width:1; stroke-dasharray:4 3 }} .ref-label {{ fill:var(--muted); font-size:11px }}
table {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums }}
th, td {{ padding:5px 8px; border-top:1px solid var(--line); text-align:right; white-space:nowrap }}
th:nth-child(-n+3), td:nth-child(-n+3) {{ text-align:left }}
td.title {{ white-space:normal; min-width:200px }}
thead th {{ color:var(--muted); font-weight:500; font-size:12px; border-top:0 }}
.lufs {{ display:inline-block; min-width:52px; padding:1px 7px; border-radius:6px; font-weight:600; color:#fff; text-align:center }}
.lufs.good {{ background:var(--good) }} .lufs.mid {{ background:var(--mid); color:#1a1a19 }} .lufs.low {{ background:var(--low) }}
.scroll {{ overflow-x:auto }}
.empty p:first-child {{ font-size:17px; margin:0 }}
footer {{ color:var(--muted); font-size:13px; margin-top:24px }}
@media (max-width:640px) {{ th, td {{ padding:4px 5px }} table {{ font-size:13px }} }}
</style></head>
<body><main>
<h1>{name}</h1>
<div class="sub">Audio levels of her videos · <a href="statistics">In numbers</a> · <a href="videos">All videos</a></div>
{body}
<footer>Updated {updated}. Levels are filled in as videos are measured.</footer>
</main>
</body></html>
"""
