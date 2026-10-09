"""P(7+) with closeness (|home proj - away proj|) vs the live P(7+) (projected total only), every season 2020-21 to now.

Each season is scored with formulas fit WITHOUT that season (leave-one-season-out over 2020-26 finished seasons),
so no season grades itself. Accuracy: log loss and Brier score of 7+ (lower = better), calibration by closeness.
Results: over record at the closing line (6/6.5 lines) for games each version puts above 50%.

  python3 research/studies/close_p7_seasons.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
import numpy as np
import pandas as pd

import grade
import history as h
import model as m
import split_model as sm


def main():
    p = sm.walk_split(sm.load_split(), known_starters=False)
    p["gap"] = (p.lam_h - p.lam_a).abs()
    done = sorted(s for s in p.season.unique() if s <= 2025)
    rows = []
    for s in sorted(p.season.unique()):
        tr = p[p.season.isin([x for x in done if x != s])]
        y = (tr.total >= 7).values.astype(float)
        b1, b2 = m.logit_fit(tr[["proj"]].values, y), m.logit_fit(tr[["proj", "gap"]].values, y)
        te = p[p.season == s].copy()
        te["old"] = 1 / (1 + np.exp(-(b1[0] + b1[1] * te.proj)))
        te["new"] = 1 / (1 + np.exp(-(b2[0] + b2[1] * te.proj + b2[2] * te.gap)))
        rows.append(te)
    d = pd.concat(rows).merge(h.lines(), on=["gameDate", "home", "away"], how="left")
    d["hit"] = d.total >= 7
    ll = lambda q, y: -np.mean(np.where(y, np.log(q), np.log(1 - q)))
    br = lambda q, y: np.mean((q - y) ** 2)

    print("ACCURACY (lower = better)")
    print(f"{'season':8s} {'games':>5s} {'went 7+':>7s} | {'log loss old':>12s} {'new':>7s} {'better?':>7s} | {'Brier old':>9s} {'new':>7s}")
    for s, x in list(d.groupby("season")) + [("ALL", d)]:
        lo, ln = ll(x.old, x.hit), ll(x.new, x.hit)
        lab = f"{s}-{str(s + 1)[2:]}" if s != "ALL" else "ALL"
        part = " (so far)" if s == 2026 else ""
        print(f"{lab:8s} {len(x):5d} {x.hit.mean():7.1%} | {lo:12.4f} {ln:7.4f} {'yes' if ln < lo else 'no':>7s} | "
              f"{br(x.old, x.hit):9.4f} {br(x.new, x.hit):7.4f}{part}")

    print("\nCALIBRATION by closeness thirds (all seasons): predicted vs went 7+")
    q1, q2 = np.quantile(d.gap, [1 / 3, 2 / 3])
    d["third"] = np.where(d.gap < q1, "even", np.where(d.gap < q2, "mid", "lopsided"))
    for t in ("even", "mid", "lopsided"):
        x = d[d.third == t]
        print(f"  {t:9s} {len(x):5d} games: old {x.old.mean():.1%}  new {x.new.mean():.1%}  actual {x.hit.mean():.1%}")

    print("\nRESULTS: OVER at the closing line (6 / 6.5 only) when the version says P(7+) > 50%")
    print(f"{'season':8s} | {'OLD: bets  W-L  ROI':>26s} | {'NEW: bets  W-L  ROI':>26s}")
    ok = d.close_total.isin([6.0, 6.5]) & d.close_over.notna() & (d.close_over.abs() >= 100)
    b = d[ok].copy()
    b["res"] = np.sign(b.total - b.close_total)
    b["prof"] = np.where(b.res == 0, 0.0, np.where(b.res > 0, grade.payout(b.close_over), -1.0))
    for s, x in list(b.groupby("season")) + [("ALL", b)]:
        lab = f"{s}-{str(s + 1)[2:]}" if s != "ALL" else "ALL"
        cells = []
        for col in ("old", "new"):
            y = x[x[col] > 0.5]
            w, l_ = (y.res > 0).sum(), (y.res < 0).sum()
            cells.append(f"{len(y):5d} {f'{w}-{l_}':>9s} {y.prof.mean():+6.1%}" if len(y) else f"{0:5d} {'-':>9s} {'-':>6s}")
        print(f"{lab:8s} | {cells[0]:>26s} | {cells[1]:>26s}")


if __name__ == "__main__":
    main()
