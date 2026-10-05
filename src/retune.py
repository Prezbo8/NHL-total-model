"""Monthly model check-up: re-check the dashboard's fixed numbers with this season's games and report drift.

1. Tier cutoffs (great/good/mid/bad/trash) for 5v5, PP, Gl, Spd: recomputed as quintiles of the last two
   full seasons + this season so far, compared with dashboard.TIERS.
2. SLAM / 1U / PASS / AVOID record this season (last pre-game call at its line) vs the 2021-26 backtest.
3. Calibration this season: projected vs actual goals, model P(7+) vs actual 7+ rate.
4. Goalie predictions: how often the goalie the projection used actually started.

Report only: nothing in the model changes by itself (a new cutoff changes which games are SLAMs, so that's
a decision). The report is saved to data/monthly/YYYY-MM.md and posted as a GitHub issue.

  python3 src/retune.py            # write this month's report
  python3 src/retune.py --issue    # ... and post it as a GitHub issue (needs GH_TOKEN)
"""
import math
import os
import subprocess
import sys
from datetime import date

import numpy as np
import pandas as pd

import confirm
import dashboard
import paper
import paths
import split_model as sm

OUT_DIR = paths.data("monthly")
# 2021-26 backtest, closing lines (what the dashboard's history sentences quote)
BACKTEST = {"SLAM": 0.568, "1U": 0.585, "PASS": 0.452, "AVOID": 0.49}
STATS = (("ev", "5v5", False), ("pp", "PP", False), ("gadj", "Gl", True), ("spd", "Spd", True))


def fmt(v, pct):
    return f"{v * 100:+.1f}%" if pct else f"{v:.2f}"


def tier_section(season):
    p = sm.walk_split(sm.load_split(), known_starters=False, record_detail=True, live_season=season)
    p = p[p.season.between(season - 2, season)]
    lines = ["## 1. Tier cutoffs (trash | bad | mid | good | great boundaries)", "",
             f"Recomputed from {len(p) * 2:,} team-games ({season - 2}-{str(season - 1)[2:]} to now, "
             f"{(p.season == season).sum() * 2} from this season).", "",
             "| Stat | Dashboard now | Recomputed | Drifted? |", "|---|---|---|---|"]
    drift = []
    for col, name, pct in STATS:
        v = pd.concat([p[f"home_{col}"], p[f"away_{col}"]]).dropna()
        if col == "spd":
            v = v[v != 0]  # seasons without speed data
        new = tuple(np.quantile(v, [0.2, 0.4, 0.6, 0.8])) if len(v) else ()
        old = dashboard.TIERS[col]
        gap = np.mean(np.diff(old))
        moved = bool(new) and any(abs(a - b) > 0.5 * gap for a, b in zip(old, new))
        if moved:
            drift.append(name)
        lines.append(f"| {name} | {' / '.join(fmt(x, pct) for x in old)} | "
                     f"{' / '.join(fmt(x, pct) for x in new) if new else 'n/a'} | {'**yes**' if moved else 'no'} |")
    lines += ["", "A cutoff 'drifts' when it moved more than half a tier's width."]
    return lines, drift


def season_rows(season):
    d = paper.read_log()
    d = d[(pd.to_datetime(d.date).map(lambda x: sm.season_of(x.date())) == season) & d.final_total.notna()]
    return dashboard.current(d) if len(d) else d


def calls_section(g):
    lines = ["## 2. SLAM / 1U / PASS / AVOID this season (last pre-game call, at its line)", "",
             "| Call | Games | Went over | Over % | 2021-26 backtest | Different? |", "|---|---|---|---|---|---|"]
    drift = []
    for c in ("SLAM", "1U", "PASS", "AVOID"):
        res = [dashboard.call_result(r, bool(r.flag)) for r in g.itertuples()]
        x = [(r.final_total > r.bet_total) for r, (cc, o) in zip(g.itertuples(), res) if cc == c and o in ("W", "L")]
        n, w = len(x), sum(x)
        rate = w / n if n else float("nan")
        se = math.sqrt(BACKTEST[c] * (1 - BACKTEST[c]) / n) if n else float("inf")
        diff = n >= 30 and abs(rate - BACKTEST[c]) > 2 * se
        if diff:
            drift.append(c)
        lines.append(f"| {c} | {n} | {w} | {'–' if not n else f'{rate:.0%}'} | {BACKTEST[c]:.0%} | "
                     f"{'**yes**' if diff else 'too few games' if n < 30 else 'no'} |")
    lines += ["", "'Different' = this season is more than 2 standard errors from the backtest, with 30+ games."]
    return lines, drift


def calibration_section(g):
    if not len(g):
        return ["## 3. Calibration", "", "No finished games this season yet."], []
    goals = pd.concat([g.away_score, g.home_score]).astype(float)
    proj = pd.concat([g.proj_away, g.proj_home]).astype(float)
    p7, a7 = g.p7.astype(float).mean(), (g.final_total >= 7).mean()
    se = math.sqrt(p7 * (1 - p7) / len(g))
    off = len(g) >= 50 and abs(a7 - p7) > 2 * se
    return (["## 3. Calibration", "", f"{len(g)} finished games this season.", "",
             f"- Goals per team: projected {proj.mean():.2f}, actual {goals.mean():.2f} "
             f"(projections run a little low by design; P(7+) corrects for it)",
             f"- 7+ goal games: model {p7:.0%}, actual {a7:.0%} → {'**off**' if off else 'in line' if len(g) >= 50 else 'too few games to judge (50+)'}"],
            ["P(7+)"] if off else [])


def goalie_section(g):
    lines = ["## 4. Starting-goalie predictions", ""]
    right = n = 0
    for r in g.itertuples():
        for s in ("away", "home"):
            act, used = getattr(r, f"{s}_goalie_actual", None), dashboard.goalie_parts(getattr(r, f"{s}_goalie"))[0]
            if isinstance(act, str) and act and used != "unknown":
                n += 1; right += confirm.same(act, used)
    lines.append(f"- The goalie the last pre-game projection used actually started {right} of {n} times"
                 + (f" ({right / n:.0%})." if n else "."))
    return lines, []


def build(today=None):
    today = today or date.today()
    season = sm.season_of(today)
    g = season_rows(season)
    parts, drift = [], []
    for fn, arg in ((tier_section, season), (calls_section, g), (calibration_section, g), (goalie_section, g)):
        lines, d = fn(arg)
        parts += lines + [""]
        drift += d
    head = [f"# Monthly model check: {today:%B %Y}", "",
            ("**Nothing drifted.** The fixed numbers still match the data; no change needed." if not drift else
             f"**Worth a look: {', '.join(drift)}.** Nothing was changed automatically; reply or ask Claude to "
             "review before updating the dashboard's numbers (a new cutoff changes which games are SLAMs)."), ""]
    md = "\n".join(head + parts)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{today:%Y-%m}.md")
    open(path, "w").write(md)
    print(md)
    return path, md, drift


def post_issue(md, today=None):
    today = today or date.today()
    subprocess.run(["gh", "label", "create", "monthly-check", "--color", "0e8a16", "--description", "Monthly model check-up"],
                   capture_output=True)
    r = subprocess.run(["gh", "issue", "create", "--title", f"Monthly model check: {today:%B %Y}", "--label", "monthly-check",
                        "--body", md], capture_output=True, text=True)
    print(r.stdout or r.stderr)


if __name__ == "__main__":
    path, md, _ = build()
    if "--issue" in sys.argv:
        post_issue(md)
