"""Which picks out high-scoring games better: projected total >= 6.5 / 6.6 / ... or P(7+) >= 47% / 48% / ...?

For each threshold: games, how often they went 7+ goals (sportsbook total: shootout winner = +1), average goals,
and the over record + ROI at the closing line (any line; also 6/6.5 lines only, the ones the model bets).
P(7+) is fitted on 2021-23 only and judged on 2023-26 (out of sample); projections are the live walk-forward model.
This season's live games (data/paper_trades.csv, last pre-game projection) are shown separately (small sample).

  python3 research/studies/proj_vs_p7_thresholds.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

import numpy as np
import pandas as pd

import dashboard
import grade
import history
import model as m
import paths
import split_model as sm

PROJ = [6.5, 6.6, 6.7, 6.8, 6.9, 7.0]
P7 = [0.47, 0.48, 0.49, 0.50, 0.51]
P7_BINS = [(0.47, 0.48), (0.48, 0.49), (0.49, 0.50), (0.50, 0.51), (0.51, 1.0)]
PROJ_BINS = [(6.5, 6.6), (6.6, 6.7), (6.7, 6.8), (6.8, 6.9), (6.9, 7.0), (7.0, 99)]


def stats(x):
    """games | 7+ rate | avg goals | over W-L-P and ROI at the closing line (all lines) | same at 6/6.5 only."""
    if not len(x):
        return "      0"
    out = f"{len(x):6d}  {(x.final >= 7).mean():6.1%}  {x.final.mean():5.2f}"
    for sub in (x, x[x.close_total.isin([6.0, 6.5])]):
        w, l = (sub.final > sub.close_total).sum(), (sub.final < sub.close_total).sum()
        p = len(sub) - w - l
        u = np.where(sub.final > sub.close_total, grade.payout(sub.close_over), np.where(sub.final < sub.close_total, -1.0, 0.0))
        out += f"   {w:4d}-{l:4d}-{p:3d} {u.mean() if len(sub) else 0:+6.1%}" if len(sub) else "        –"
    return out


HEAD = f"{'':24s} {'games':>6s} {'7+':>7s} {'goals':>6s}   {'over at close (all lines)':>21s}   {'over at 6/6.5 only':>19s}"


def block(title, d, base):
    print(f"\n{title}\n{HEAD}")
    print(f"{'all games':24s} {stats(d)}")
    print(f"{'(base 7+ rate)':24s} {'':6s}  {base:6.1%}")
    print("  projected total, at or above:")
    for t in PROJ:
        print(f"    {f'>= {t:.1f}':20s} {stats(d[d.proj >= t])}")
    print("  P(7+), at or above:")
    for t in P7:
        print(f"    {f'>= {t:.0%}':20s} {stats(d[d.p7 >= t])}")
    print("  projected total, band:")
    for lo, hi in PROJ_BINS:
        print(f"    {f'{lo:.1f} - {hi:.1f}' if hi < 99 else f'{lo:.1f}+':20s} {stats(d[(d.proj >= lo) & (d.proj < hi)])}")
    print("  P(7+), band:")
    for lo, hi in P7_BINS:
        print(f"    {f'{lo:.0%} - {hi:.0%}' if hi < 1 else f'{lo:.0%}+':20s} {stats(d[(d.p7 >= lo) & (d.p7 < hi)])}")


def main():
    games = sm.load_split()
    proj = sm.walk_split(games, known_starters=False)
    cal = m.fit_calibration(proj[proj.season.between(2021, 2022)])  # 2021-22 + 2022-23 only
    test = proj[proj.season.between(2023, 2025)].copy()
    test["p7"] = m.p_from(cal, 7, test.proj.values, (test.lam_h - test.lam_a).abs().values)
    d = test.merge(history.lines().drop(columns="final"), on=["gameDate", "home", "away"]).rename(columns={"total": "final"})
    d = d[d.close_total.notna() & d.close_over.notna() & (d.close_over.abs() >= 100)]  # 'final' = goals, shootout winner +1
    block(f"BACKTEST 2023-26 (out of sample for P(7+)): {len(d)} games with closing lines", d, (d.final >= 7).mean())
    print("\n  overlap: projected >= 6.5 and P(7+) >= 50%:")
    print(f"    {'both':20s} {stats(d[(d.proj >= 6.5) & (d.p7 >= 0.50)])}")
    print(f"    {'proj only':20s} {stats(d[(d.proj >= 6.5) & (d.p7 < 0.50)])}")
    print(f"    {'P(7+) only':20s} {stats(d[(d.proj < 6.5) & (d.p7 >= 0.50)])}")

    live = dashboard.current(pd.read_csv(paths.data("paper_trades.csv")))
    live = live[live.final_total.notna() & live.close_total.notna() & live.close_over.notna()].rename(columns={"final_total": "final"})
    block(f"THIS SEASON, live (last pre-game projection): {len(live)} games", live, (live.final >= 7).mean())


if __name__ == "__main__":
    main()
