"""Altitude: do games in Denver (COL, ~1,600 m) and Salt Lake City (UTA, ~1,300 m, from 2024-25) score
differently than projected? Calgary (~1,050 m) shown separately. Every other rink is the comparison.

(1) home goals, visitor goals and the total vs projection, by venue group and season.
(2) SLAM + 1U record in high-altitude games.

  python3 research/altitude.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
import numpy as np

import dashboard
import history as h
import split_model as sm

HIGH = {"COL", "UTA"}


def main():
    g = sm.load_split()
    p = sm.walk_split(g, known_starters=True, record_detail=True).merge(g[["gameId", "hg", "ag"]], on="gameId")
    a = p[p.season.between(2021, 2025)].copy()
    a["venue"] = np.where(a.home.isin(HIGH), "Denver / Salt Lake", np.where(a.home == "CGY", "Calgary", "other rinks"))
    print("(1) actual / projected goals (real starters)")
    print(f"{'venue':20s} {'games':>6s} {'home':>6s} {'visitor':>8s} {'total diff':>10s} {'± 2 SE':>7s} {'7+':>6s}")
    for v in ("Denver / Salt Lake", "Calgary", "other rinks"):
        x = a[a.venue == v]
        d = x.total - x.proj
        print(f"{v:20s} {len(x):6d} {x.hg.sum() / x.lam_h.sum():6.3f} {x.ag.sum() / x.lam_a.sum():8.3f} "
              f"{d.mean():+10.2f} {2 * d.std() / np.sqrt(len(x)):7.2f} {(x.total >= 7).mean():6.1%}")
    print("\nDenver / Salt Lake by season (visitor actual/projected, total diff):")
    for s, x in a[a.venue == "Denver / Salt Lake"].groupby("season"):
        print(f"  {s}-{str(s + 1)[2:]}: {len(x):3d} games, visitor {x.ag.sum() / x.lam_a.sum():.3f}, home {x.hg.sum() / x.lam_h.sum():.3f}, "
              f"total {(x.total - x.proj).mean():+.2f}")
    print("\nsame teams on the road at sea level vs at home (are COL/UTA just mis-rated?):")
    for t in sorted(HIGH):
        home, road = a[a.home == t], a[a.away == t]
        if len(home):
            print(f"  {t}: at home scored {home.hg.sum() / home.lam_h.sum():.3f}, allowed {home.ag.sum() / home.lam_a.sum():.3f} | "
                  f"on the road scored {road.ag.sum() / road.lam_a.sum():.3f}, allowed {road.hg.sum() / road.lam_h.sum():.3f}")

    q = sm.walk_split(g, known_starters=False, record_detail=True)
    d = h.flagged(q).merge(h.lines(), on=["gameDate", "home", "away"])
    d = d[(d.season >= 2021) & d.both]
    d = d[np.isin([dashboard.call(r, True) for r in d.itertuples()], ["SLAM", "1U"])]
    print(f"\n(2) SLAM + 1U: {'when':5s} {'bets':>5s} {'W-L':>8s} {'ROI':>6s}")
    for name, sel in (("Denver / Salt Lake", d.home.isin(HIGH)), ("everywhere else", ~d.home.isin(HIGH))):
        for when in ("open", "close"):
            b = h.bet_results(d[sel], when)
            w, l_ = (b.res > 0).sum(), (b.res < 0).sum()
            print(f"  {name:18s} {when:5s} {len(b):5d} {f'{w}-{l_}':>8s} {b.prof.mean():+6.1%}")


if __name__ == "__main__":
    main()
