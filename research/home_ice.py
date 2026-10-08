"""League-wide home-ice factor: does scaling home goals up / away goals down improve the projection or the calls?

Ratings mix home and road games, so a team's projection is its 'neutral rink' number. Variants scale lam_h by
(1 + h) and lam_a by (1 - a), fitted on 2021-23 only, then judged on 2024-26 (and on the flag/SLAM/1U backtest).
The factor is applied like b2b/speed: on the team projection (so it moves the flag), not on the 5v5 tier.

  python3 research/home_ice.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
from math import lgamma

import numpy as np

import dashboard
import history as h
import split_model as sm


def scaled(p, hf, af):
    return p.assign(lam_h=p.lam_h * (1 + hf), lam_a=p.lam_a * (1 - af), proj=p.lam_h * (1 + hf) + p.lam_a * (1 - af))


def accuracy(p):
    """2024-26 team-goal and game-total errors (Poisson log loss on each side's goals; MAE on the total)."""
    t = p[p.season >= 2024]
    logpmf = lambda k, lam: k * np.log(lam) - lam - np.array([lgamma(x + 1) for x in k])
    ll = -np.mean(np.r_[logpmf(t.hg.values, t.lam_h.values), logpmf(t.ag.values, t.lam_a.values)])
    return ll, np.mean(np.abs(t.total - t.proj)), (t.total - t.proj).mean()


def calls(p):
    d = h.flagged(p).merge(h.lines(), on=["gameDate", "home", "away"])
    d = d[(d.season >= 2021) & d.both]
    c = np.array([dashboard.call(r, True) for r in d.itertuples()])
    out = {}
    for name, mask in (("all flagged", np.ones(len(d), bool)), ("SLAM", c == "SLAM"), ("1U", c == "1U"),
                       ("SLAM+1U", np.isin(c, ["SLAM", "1U"]))):
        for when in ("open", "close"):
            b = h.bet_results(d[mask], when)
            dec = b[b.res != 0]
            halves = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
            out[(name, when)] = (len(b), (dec.res > 0).mean(), b.prof.sum(), b.prof.mean(), *halves)
    return out


def main():
    g = sm.load_split()
    p = sm.walk_split(g, known_starters=False, record_detail=True)
    p = p.merge(g[["gameId", "hg", "ag"]], on="gameId")
    tr = p[p.season.between(2021, 2023)]
    hf, af = tr.hg.mean() / tr.lam_h.mean() - 1, 1 - tr.ag.mean() / tr.lam_a.mean()
    sym = (hf + af) / 2
    print(f"2021-23 (fit): home teams scored {tr.hg.mean():.3f} vs projected {tr.lam_h.mean():.3f}; "
          f"away {tr.ag.mean():.3f} vs {tr.lam_a.mean():.3f}")
    te = p[p.season >= 2024]
    print(f"2024-26 (test): home {te.hg.mean():.3f} vs {te.lam_h.mean():.3f}; away {te.ag.mean():.3f} vs {te.lam_a.mean():.3f}\n")
    variants = {"current (no home factor)": (0, 0), f"fitted home +{hf:.1%} / away -{af:.1%}": (hf, af),
                f"symmetric +/-{sym:.1%} (total unchanged)": (sym, sym)}
    res = {}
    print(f"{'variant':40s} {'goal LL':>8s} {'total MAE':>9s} {'total bias':>10s}   (2024-26, lower LL/MAE = better)")
    for name, (a, b) in variants.items():
        v = scaled(p, a, b)
        print(f"{name:40s} {accuracy(v)[0]:8.4f} {accuracy(v)[1]:9.3f} {accuracy(v)[2]:+10.3f}")
        res[name] = calls(v)
    print(f"\n{'variant':40s} {'group':12s} {'when':5s} {'bets':>5s} {'over%':>6s} {'units':>7s} {'ROI':>6s}   2021-22 / 2023-26 ROI")
    for name, r in res.items():
        for (grp, when), (n, w, u, roi, h1, h2) in r.items():
            print(f"{name:40s} {grp:12s} {when:5s} {n:5d} {w:6.1%} {u:+7.1f} {roi:+6.1%}   {h1:+6.1%} / {h2:+6.1%}")
        print()


if __name__ == "__main__":
    main()
