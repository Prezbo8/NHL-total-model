"""SLAM / 1U / PASS / AVOID judged fairly (Nov 2026 audit, item 2.3): each season's tier cutoffs cut only from the two
seasons BEFORE it (as the live 2026-27 cutoffs come from 2024-26), vs the live cutoffs (2024-26 quintiles) used for
every season, which is how the quoted rates (SLAM 55% / 56.5%, 1U 58% / 59%, ...) were made.

The tiers that decide a call: 5v5 projected goals (ev) and the opposing-goalie adjustment (gadj). Cutoffs = quintiles of
every team-game's value in the two earlier seasons (2021-22: 2020-21 only, the cold-start season). Games with a 6 / 6.5
line at the open / close; flagged games get their call, unflagged ones are AVOID. Over % = overs / (overs + unders).
Error bars: 90% range of 1,000 resamples of game nights.

  python3 research/studies/walk_forward_tiers.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers

import numpy as np
import pandas as pd

import dashboard
import grade
import history
import model as m
import split_model as sm

LIVE = {k: dashboard.TIERS[k] for k in ("ev", "gadj")}
CALLS = ("SLAM", "1U", "PASS", "AVOID")


def cuts(p, seasons, col):
    x = p[p.season.isin(seasons)]
    return tuple(round(float(q), 3) for q in np.quantile(np.r_[x[f"home_{col}"].values, x[f"away_{col}"].values], (0.2, 0.4, 0.6, 0.8)))


def graded(d, tiers_by_season, when):
    """One row per game with a 6 / 6.5 line at `when`: season, night, call, over (1 / 0; pushes dropped), units if bet."""
    t, o = d[f"{when}_total"], d[f"{when}_over"]
    x = d[t.isin(m.FLAG_LINES) & o.notna() & (d.total != t)].copy()
    rows = []
    for s, g in x.groupby("season"):
        for k, v in tiers_by_season[s].items():
            dashboard.TIERS[k] = v
        try:
            calls = [dashboard.call(r, bool(r.both)) for r in g.itertuples()]
        finally:
            dashboard.TIERS.update(LIVE)
        over = (g.total > g[f"{when}_total"]).astype(int)
        units = np.where(over == 1, grade.payout(g[f"{when}_over"]), -1.0)
        rows.append(pd.DataFrame({"season": s, "night": g.gameDate, "call": calls, "over": over, "units": units}))
    return pd.concat(rows, ignore_index=True)


def boot(g, stat, n=1000, seed=0):
    nights = g.night.unique()
    idx = {k: v.index.values for k, v in g.groupby("night")}
    rs = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        pick = rs.choice(nights, len(nights))
        vals.append(stat(g.loc[np.concatenate([idx[k] for k in pick])]))
    return np.quantile(vals, [0.05, 0.95])


def main():
    games = sm.load_split()
    p = sm.walk_split(games, known_starters=False, record_detail=True)
    remade = {k: cuts(p, (2024, 2025), k) for k in LIVE}
    print(f"live cutoffs {LIVE} | re-made from 2024-26: {remade}\n")
    d = history.flagged(p).merge(history.lines()[lambda z: z.gameDate >= 20200801], on=["gameDate", "home", "away"])
    seasons = sorted(d.season.unique())
    fixed = {s: LIVE for s in seasons}
    walk = {s: {k: cuts(p, [y for y in (s - 2, s - 1) if y >= 2020], k) for k in LIVE} for s in seasons}
    for s in seasons:
        print(f"{s}-{str(s + 1)[2:]} cutoffs from {[y for y in (s - 2, s - 1) if y >= 2020]}: {walk[s]}")
    for when in ("open", "close"):
        a, b = graded(d, fixed, when), graded(d, walk, when)
        print(f"\n=== at the {when} (games with a 6 / 6.5 line; {(a.call != b.call).sum()} of {len(a)} change call) ===")
        print(f"{'call':6s} | {'quoted (live cutoffs)':>24s} | {'fair (earlier seasons only)':>38s}")
        for c in CALLS:
            x, y = a[a.call == c], b[b.call == c]
            lo, hi = boot(y, lambda g: g.over.mean()) if len(y) else (np.nan, np.nan)
            print(f"{c:6s} | {len(x):5d} games {x.over.mean():6.1%} over | {len(y):5d} games {y.over.mean():6.1%} over "
                  f"(90%: {lo:.1%}..{hi:.1%})")
        for lab, g in (("quoted", a), ("fair", b)):
            f = g[g.call.isin(["SLAM", "1U", "PASS"])]
            diff = lambda z: z[z.call == "SLAM"].over.mean() - z[z.call == "PASS"].over.mean()
            lo, hi = boot(f, diff)
            su = g[g.call.isin(["SLAM", "1U"])]
            ulo, uhi = boot(su, lambda z: z.units.sum())
            print(f"  {lab:7s} SLAM minus PASS over %: {diff(f):+.1%} (90%: {lo:+.1%}..{hi:+.1%}) | SLAM+1U {len(su)} bets "
                  f"{su.units.sum():+.1f}u ({su.units.mean():+.1%} ROI; 90%: {ulo:+.1f}..{uhi:+.1f}u)")
        print("  fair, by season (SLAM over % / bets; 1U; PASS):")
        for s in seasons:
            g = b[b.season == s]
            cell = lambda c: f"{g[g.call == c].over.mean():.0%}/{(g.call == c).sum()}" if (g.call == c).any() else "-"
            print(f"    {s}-{str(s + 1)[2:]}  SLAM {cell('SLAM'):>9s}  1U {cell('1U'):>9s}  PASS {cell('PASS'):>9s}  AVOID {cell('AVOID'):>9s}")


if __name__ == "__main__":
    main()
