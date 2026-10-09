"""Stake sizes: should SLAM and 1U be bet at different sizes? Flat 1 unit (current) vs a few fixed splits, plus
per-season ROI, a bootstrap range, and the worst losing run (drawdown) for each. 2021-26, open and close.

  python3 research/studies/stakes.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
import numpy as np
import pandas as pd

import dashboard
import history as h
import split_model as sm

SCHEMES = {"flat 1u (current)": (1.0, 1.0), "SLAM 1.5 / 1U 1": (1.5, 1.0), "SLAM 1 / 1U 1.5": (1.0, 1.5),
           "SLAM 1 / 1U 2": (1.0, 2.0), "SLAM 2 / 1U 1": (2.0, 1.0)}


def drawdown(units):
    c = np.cumsum(units)
    return float((np.maximum.accumulate(np.r_[0, c])[1:] - c).max())


def main():
    p = sm.walk_split(sm.load_split(), known_starters=False, record_detail=True)
    d = h.flagged(p).merge(h.lines(), on=["gameDate", "home", "away"])
    d = d[(d.season >= 2021) & d.both]
    d["call"] = [dashboard.call(r, True) for r in d.itertuples()]
    rng = np.random.default_rng(0)
    for when in ("open", "close"):
        b = h.bet_results(d[d.call.isin(["SLAM", "1U"])], when).sort_values("gameDate")
        print(f"\n=== {when.upper()} ===")
        print(f"{'call':5s} {'bets':>5s} {'W-L-P':>11s} {'win%':>6s} {'ROI':>6s} {'90% range':>16s}   per season ROI")
        for c in ("SLAM", "1U"):
            x = b[b.call == c]
            boots = [rng.choice(x.prof.values, len(x)).mean() for _ in range(4000)]
            lo, hi = np.percentile(boots, [5, 95])
            w, l_, pu = (x.res > 0).sum(), (x.res < 0).sum(), (x.res == 0).sum()
            seas = " ".join(f"{s}:{y.prof.mean():+.0%}({len(y)})" for s, y in x.groupby("season"))
            print(f"{c:5s} {len(x):5d} {f'{w}-{l_}-{pu}':>11s} {w / (w + l_):6.1%} {x.prof.mean():+6.1%} {f'{lo:+.1%}..{hi:+.1%}':>16s}   {seas}")
        diff = [rng.choice(b[b.call == '1U'].prof.values, (b.call == '1U').sum()).mean()
                - rng.choice(b[b.call == 'SLAM'].prof.values, (b.call == 'SLAM').sum()).mean() for _ in range(4000)]
        print(f"1U minus SLAM ROI: {np.mean(diff):+.1%}, 1U ahead in {np.mean(np.array(diff) > 0):.0%} of resamples")
        print(f"\n{'stakes':20s} {'risked':>7s} {'units':>7s} {'ROI':>6s} {'worst drawdown':>15s}   2021-22 / 2023-25 units")
        for name, (s_slam, s_1u) in SCHEMES.items():
            st = np.where(b.call == "SLAM", s_slam, s_1u)
            u = b.prof.values * st
            halves = [u[b.season.isin(ss).values].sum() for ss in ((2021, 2022), (2023, 2024, 2025))]
            print(f"{name:20s} {st.sum():7.0f} {u.sum():+7.1f} {u.sum() / st.sum():+6.1%} {drawdown(u):15.1f}   {halves[0]:+.1f} / {halves[1]:+.1f}")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
