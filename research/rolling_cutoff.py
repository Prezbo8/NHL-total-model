"""Rolling high-scoring cutoff: does using THIS season's projections (instead of last season's) pick better flags?

  current : 60th pct of last season's team projections, fixed all season (what runs daily)
  rolling : last season's until 200 games of this season are played, then 60th pct of this season's
            projections from games before that date
  blend   : last season's, moving linearly to this season's 60th pct by 600 games played

Judged on the flag rule and the SLAM / 1U calls, 2021-26, open and close, and in both halves.

  python3 research/rolling_cutoff.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
import numpy as np
import pandas as pd

import dashboard
import history as h
import split_model as sm

Q = h.HIGH_Q
MIN_GAMES, FULL_GAMES = 200, 600


def cutoffs(p):
    """Per game: (fixed, rolling, blend) cutoffs, using only games before that date."""
    out = []
    for s, x in p.groupby("season"):
        prev = p[p.season == s - 1]
        if prev.empty:
            continue
        fixed = np.quantile(np.r_[prev.lam_h, prev.lam_a], Q)
        x = x.sort_values("gameDate")
        for day, xd in x.groupby("gameDate", sort=True):
            before = x[x.gameDate < day]
            n = len(before)
            now = np.quantile(np.r_[before.lam_h, before.lam_a], Q) if n else fixed
            roll = now if n >= MIN_GAMES else fixed
            w = min(n / FULL_GAMES, 1.0)
            out.append(xd.assign(cut_current=fixed, cut_rolling=roll, cut_blend=(1 - w) * fixed + w * now))
    return pd.concat(out)


def main():
    p = cutoffs(sm.walk_split(sm.load_split(), known_starters=False, record_detail=True))
    d = p.merge(h.lines(), on=["gameDate", "home", "away"])
    d = d[d.season >= 2021]
    late = d.groupby("season").gameDate.transform(lambda s: s.rank(method="dense") > s.rank(method="dense").max() / 2)
    print("average cutoff (first half of season / second half):")
    for v in ("current", "rolling", "blend"):
        print(f"  {v:8s} {d[~late][f'cut_{v}'].mean():.3f} / {d[late][f'cut_{v}'].mean():.3f}")
    print(f"\n{'cutoff':9s} {'group':9s} {'when':5s} {'bets':>5s} {'W-L':>9s} {'over%':>6s} {'units':>7s} {'ROI':>6s}   2021-22 / 2023-25 ROI")
    for v in ("current", "rolling", "blend"):
        x = d.assign(both=(d.lam_h >= d[f"cut_{v}"]) & (d.lam_a >= d[f"cut_{v}"]))
        x = x[x.both]
        c = np.array([dashboard.call(r, True) for r in x.itertuples()])
        for grp, mask in (("flagged", np.ones(len(x), bool)), ("SLAM", c == "SLAM"), ("1U", c == "1U"),
                          ("SLAM+1U", np.isin(c, ["SLAM", "1U"]))):
            for when in ("open", "close"):
                b = h.bet_results(x[mask], when)
                w_, l_ = (b.res > 0).sum(), (b.res < 0).sum()
                hv = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
                print(f"{v:9s} {grp:9s} {when:5s} {len(b):5d} {f'{w_}-{l_}':>9s} {w_ / (w_ + l_):6.1%} {b.prof.sum():+7.1f} "
                      f"{b.prof.mean():+6.1%}   {hv[0]:+6.1%} / {hv[1]:+6.1%}")
        print()


if __name__ == "__main__":
    main()
