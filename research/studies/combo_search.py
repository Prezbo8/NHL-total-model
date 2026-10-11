"""Which combination of pre-game signals finds the most 7+ (over 6.5) games?

Every combination of 1-3 signals is scored on the SEARCH seasons (2020-21 to 2022-23) by how often its games
went 7+; the best ones (enough games, clearly above average) are then checked on the HOLDOUT seasons
(2023-24 to 2025-26), which the search never saw. Only what holds up there is worth looking for.

Signals are things the dashboard shows before puck drop: the flag, 5v5 / PP / goalie (Gl) tiers for each
team, projected total, P(7+), closeness, back-to-backs, team speed, the line. Backtest goalies are each
team's usual starter (the last pre-game run knows the real one); injuries aren't in the backtest.

  python3 research/studies/combo_search.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
from itertools import combinations

import numpy as np
import pandas as pd

import dashboard as db
import grade
import history as h
import model as m
import split_model as sm

SEARCH, HOLDOUT = (2020, 2022), (2023, 2025)
MIN_SEARCH, MIN_HOLD = 150, 60


def games():
    p = sm.walk_split(sm.load_split(), known_starters=False, record_detail=True)
    p["gap"] = (p.lam_h - p.lam_a).abs()
    done = sorted(s for s in p.season.unique() if s <= 2025)
    out = []
    for s in done:  # P(7+) never fit on its own season (walk-forward from 2023, leave-one-season-out before)
        tr = p[p.season.between(2022, s - 1)] if s >= 2023 else p[p.season.isin([x for x in done if x != s])]
        cal = m.fit_calibration(tr)
        x = p[p.season == s].copy()
        x["p7"] = m.p_from(cal, 7, x.proj.values, x.gap.values)
        out.append(x)
    d = pd.concat(out)
    d = d.merge(h.flagged(p)[["gameId", "both"]], on="gameId", how="left").merge(h.lines(), on=["gameDate", "home", "away"], how="left")
    for sd in ("home", "away"):
        for stat, col in (("ev", "ev"), ("pp", "pp"), ("gadj", "gadj")):
            d[f"{sd}_{col}_t"] = d[f"{sd}_{col}"].map(lambda v, st=stat: db.tier(st, v))
    return d


def signals(d):
    gg = lambda c: d[f"home_{c}_t"].isin(["good", "great"]) & d[f"away_{c}_t"].isin(["good", "great"])
    anyt = lambda c, t: (d[f"home_{c}_t"] == t) | (d[f"away_{c}_t"] == t)
    return {
        "FLAG (both teams high-scoring)": d.both.fillna(False).astype(bool),
        "both good/great 5v5": gg("ev"),
        "one+ great 5v5": anyt("ev", "great"),
        "both great 5v5": (d.home_ev_t == "great") & (d.away_ev_t == "great"),
        "no bad/trash 5v5": ~d.home_ev_t.isin(["bad", "trash"]) & ~d.away_ev_t.isin(["bad", "trash"]),
        "both good/great PP": gg("pp"),
        "one+ great PP": anyt("pp", "great"),
        "both good/great Gl (weak goalies)": gg("gadj"),
        "no bad/trash Gl (no strong goalie)": ~d.home_gadj_t.isin(["bad", "trash"]) & ~d.away_gadj_t.isin(["bad", "trash"]),
        "proj 6.3+": d.proj >= 6.3,
        "proj 6.5+": d.proj >= 6.5,
        "P(7+) 47%+": d.p7 >= 0.47,
        "P(7+) 50%+": d.p7 >= 0.50,
        "even matchup (gap < 0.3)": d.gap < 0.3,
        "a team on a back-to-back": (d.home_b2badj != 0) | (d.away_b2badj != 0),
        "no back-to-back": (d.home_b2badj == 0) & (d.away_b2badj == 0),
        "both teams fast (speed +)": (d.home_spd > 0) & (d.away_spd > 0),
        "line 6.5+": d.close_total >= 6.5,
        "line 6 or 5.5": d.close_total <= 6.0,
    }


def stats(x):
    n, hit = len(x), (x.total >= 7).mean() if len(x) else np.nan
    ok = x.close_total.notna() & x.close_over.notna() & (x.close_over.abs() >= 100)
    b = x[ok]
    res = np.sign(b.total - b.close_total)
    prof = np.where(res == 0, 0, np.where(res > 0, grade.payout(b.close_over), -1.0))
    return n, hit, (res > 0).sum(), (res < 0).sum(), prof.mean() if len(b) else np.nan


def main():
    d = games()
    d = d[d.season.between(SEARCH[0], HOLDOUT[1])]
    sig = signals(d)
    srch, hold = d.season.between(*SEARCH), d.season.between(*HOLDOUT)
    base_s, base_h = (d[srch].total >= 7).mean(), (d[hold].total >= 7).mean()
    print(f"baseline 7+ rate: search {base_s:.1%} ({srch.sum()} games) | holdout {base_h:.1%} ({hold.sum()} games)\n")
    rows = []
    names = list(sig)
    for k in (1, 2, 3):
        for combo in combinations(names, k):
            mask = np.logical_and.reduce([sig[c].values for c in combo])
            ns = int((mask & srch.values).sum())
            if ns < MIN_SEARCH:
                continue
            hs = (d.total.values[mask & srch.values] >= 7).mean()
            rows.append((combo, ns, hs, mask))
    rows.sort(key=lambda r: -r[2])
    print(f"{len(rows)} combinations with {MIN_SEARCH}+ search games. Top 25 by search 7+ rate, then the holdout:")
    print(f"{'combination':86s} | {'search: n 7+':>14s} | {'HOLDOUT: n  7+':>15s}  over at close (ROI)")
    for combo, ns, hs, mask in rows[:25]:
        nh, hh, w, l_, roi = stats(d[mask & hold.values])
        held = "✓" if nh >= MIN_HOLD and hh >= base_h + 0.04 else " "
        print(f"{' + '.join(combo):86s} | {ns:5d} {hs:6.1%} | {nh:5d} {hh:6.1%} {held} {w}-{l_} ({roi:+.1%})")

    # best combos judged on the holdout among those that were good in the search (top 100 by search rate)
    good = []
    for combo, ns, hs, mask in rows[:100]:
        nh, hh, w, l_, roi = stats(d[mask & hold.values])
        if nh >= MIN_HOLD:
            good.append((hh, combo, ns, hs, nh, w, l_, roi))
    good.sort(key=lambda r: -r[0])
    print(f"\nOf the search's top 100, the 15 that did best in the holdout ({MIN_HOLD}+ games):")
    for hh, combo, ns, hs, nh, w, l_, roi in good[:15]:
        print(f"  {' + '.join(combo):86s} search {hs:5.1%} ({ns}) | holdout {hh:5.1%} ({nh}) | over at close {w}-{l_} ({roi:+.1%})")

    print("\nsingle signals, search vs holdout 7+ rate:")
    for c in names:
        a, b = d[sig[c].values & srch.values], d[sig[c].values & hold.values]
        print(f"  {c:40s} search {(a.total >= 7).mean():5.1%} ({len(a):4d}) | holdout {(b.total >= 7).mean():5.1%} ({len(b):4d})")


if __name__ == "__main__":
    main()
