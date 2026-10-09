"""Close games: when two teams project about even, games stay close late, goalies get pulled, empty-net goals
follow. Do evenly matched games go 7+ more often than their projected total says?

closeness = |home projection - away projection| (goals); small = evenly matched.
(1) Mechanism: 'other' goals (empty net, 4-on-4, 3-on-3, extra attacker) by closeness third.
(2) P(7+) from projected total alone (live) vs + closeness: log loss 2023-26, walk-forward (fit 2022..season-1).
(3) Within SLAM + 1U, results by closeness third (both halves, open and close).

  python3 research/studies/close_games.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
import numpy as np
import pandas as pd

import dashboard
import history as h
import model as m
import split_model as sm


def main():
    g = sm.load_split()
    p = sm.walk_split(g, known_starters=False, record_detail=True).merge(
        g[["gameId", "o_goalsFor", "o_goalsAgainst", "hg", "ag"]], on="gameId")
    p["gap"] = (p.lam_h - p.lam_a).abs()
    p["oth"] = p.o_goalsFor + p.o_goalsAgainst
    p["tied_reg"] = p.hg == p.ag  # MoneyPuck goals exclude the shootout; equal = went to a shootout
    a = p[p.season >= 2021].copy()
    q1, q2 = np.quantile(a.gap, [1 / 3, 2 / 3])
    cut = lambda x: np.where(x < q1, "even", np.where(x < q2, "mid", "lopsided"))
    a["close_t"] = cut(a.gap)
    print(f"closeness thirds: even = gap under {q1:.2f} goals, lopsided = over {q2:.2f}")
    print(f"corr of gap with projected total: {a[['gap', 'proj']].corr().iloc[0, 1]:+.3f}\n")
    print(f"{'third':9s} {'games':>6s} {'proj':>5s} {'actual':>6s} {'diff':>6s} {'other goals':>11s} {'shootouts':>9s} {'went 7+':>7s}")
    for t in ("even", "mid", "lopsided"):
        x = a[a.close_t == t]
        print(f"{t:9s} {len(x):6d} {x.proj.mean():5.2f} {x.total.mean():6.2f} {x.total.mean() - x.proj.mean():+6.2f} "
              f"{x.oth.mean():11.2f} {x.tied_reg.mean():9.1%} {(x.total >= 7).mean():7.1%}")

    rows = []
    for s in range(2023, 2026):
        tr, te = p[p.season.between(2022, s - 1)], p[p.season == s].copy()
        y = (tr.total >= 7).values.astype(float)
        b1 = m.logit_fit(tr[["proj"]].values, y)
        b2 = m.logit_fit(tr[["proj", "gap"]].values, y)
        te["p1"] = 1 / (1 + np.exp(-(b1[0] + b1[1] * te.proj)))
        te["p2"] = 1 / (1 + np.exp(-(b2[0] + b2[1] * te.proj + b2[2] * te.gap)))
        print(f"\n  fit 2022-{str(s)[2:]}: gap coefficient {b2[2]:+.3f} per goal of gap (projected total {b2[1]:+.3f} per goal)", end="")
        rows.append(te)
    te = pd.concat(rows)
    y = (te.total >= 7).values
    ll = lambda q: -np.mean(np.where(y, np.log(q), np.log(1 - q)))
    print(f"\nP(7+) log loss 2023-26 ({len(te)} games): projected total only {ll(te.p1):.4f} | + closeness {ll(te.p2):.4f}  (lower = better)")
    te["close_t"] = cut(te.gap)
    for t in ("even", "mid", "lopsided"):
        x = te[te.close_t == t]
        print(f"  {t:9s} {len(x)} games: P(7+) said {x.p1.mean():.1%}, went 7+ {(x.total >= 7).mean():.1%}")

    d = h.flagged(p).merge(h.lines(), on=["gameDate", "home", "away"])
    d = d[(d.season >= 2021) & d.both]
    d = d[np.isin([dashboard.call(r, True) for r in d.itertuples()], ["SLAM", "1U"])]
    d["close_t"] = cut(d.gap)
    print(f"\nSLAM + 1U by closeness: {'when':5s} {'bets':>5s} {'W-L':>8s} {'win%':>6s} {'ROI':>6s}   2021-22 / 2023-25")
    for t in ("even", "mid", "lopsided"):
        for when in ("open", "close"):
            b = h.bet_results(d[d.close_t == t], when)
            w, l_ = (b.res > 0).sum(), (b.res < 0).sum()
            hv = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
            print(f"  {t:8s} {when:5s} {len(b):5d} {f'{w}-{l_}':>8s} {w / (w + l_):6.1%} {b.prof.mean():+6.1%}   {hv[0]:+.1%} / {hv[1]:+.1%}")


if __name__ == "__main__":
    main()
