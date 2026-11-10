"""Should injuries decide the over flag? (Nov 10 2026 audit, M2.) The live run multiplies the injury adjustment into
each team's projected goals BEFORE the 'both teams >= cutoff' test, but the cutoff and the backtest (585 / 845 bets)
use projections without injuries. Compared here on who actually dressed 2021-26 (injury_backtest.py's method, the
live size injuries.SCALE and the defensemen's offense effect at injuries.D_OFF; best case: live only knows the
projected lineup):
  A  injury-free projection vs the injury-free cutoff          (the backtested rule)
  B  injury-adjusted projection vs the injury-free cutoff      (the live rule)
  C  injury-adjusted projection vs a cutoff built with injuries too
Bets: flagged overs at 6 / 6.5, open and close; SLAM + 1U units; the games each rule adds or drops vs A; 90% ranges
of B - A and C - A from 1,000 resamples of game nights.

  python3 research/studies/flag_injuries.py      # needs data/dressed.csv (research/lib/lineups_hist.py download)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import dashboard
import history
import injuries
import model as m
import paths
import split_model as sm
from injury_backtest import adjusted, missing_effects
from injury_position import shrink_d


def flagged(p, cut_from):
    """p with 'both' (both teams >= the cutoff), each season's cutoff from cut_from's previous season (model.flag_cutoff)."""
    out = []
    for s, x in p.groupby("season"):
        prev = cut_from[cut_from.season == s - 1]
        if len(prev):
            out.append(x.assign(both=m.both_high(x.lam_h, x.lam_a, m.flag_cutoff(prev))))
    return pd.concat(out)


def bets(d, when):
    b = history.bet_results(d[d.season >= 2021], when)
    calls = np.array([dashboard.call(r, True) for r in b.itertuples()])
    return b.assign(slam1u=np.isin(calls, ["SLAM", "1U"]))


def summary(b):
    dec = b[b.res != 0]
    s = b[b.slam1u]
    return (f"{len(b):4d} bets {(dec.res > 0).mean():5.1%} {b.prof.mean():+6.1%} {b.prof.sum():+6.1f}u | "
            f"SLAM+1U {len(s):3d} {s.prof.sum():+6.1f}u")


def boot(a, b, col, n=1000, seed=0):
    """90% range of (sum of b's col) - (sum of a's col), resampling game nights."""
    na, nb = a.groupby("gameDate")[col].sum(), b.groupby("gameDate")[col].sum()
    nights = sorted(set(na.index) | set(nb.index))
    da = na.reindex(nights, fill_value=0).values
    db = nb.reindex(nights, fill_value=0).values
    rs = np.random.default_rng(seed)
    w = np.stack([np.bincount(rs.integers(0, len(nights), len(nights)), minlength=len(nights)) for _ in range(n)])
    diff = w @ db - w @ da
    return float(db.sum() - da.sum()), *np.quantile(diff, [0.05, 0.95])


def main():
    games = sm.load_split()
    dressed = pd.read_csv(paths.data("dressed.csv"))
    base = sm.walk_split(games, known_starters=False, record_detail=True)
    eff, pos = missing_effects(games, dressed, positions=True)
    inj = adjusted(base, shrink_d(eff, pos, injuries.D_OFF, 1.0), scale=injuries.SCALE)
    lines = history.lines()[lambda z: z.gameDate >= 20200801]
    rules = {"A injury-free (backtested)": flagged(base, base), "B injuries vs injury-free cutoff (live)": flagged(inj, base),
             "C injuries vs injury cutoff": flagged(inj, inj)}
    d = {k: v.merge(lines, on=["gameDate", "home", "away"]) for k, v in rules.items()}
    a_key = "A injury-free (backtested)"
    for when in ("open", "close"):
        print(f"\n=== at the {when} (2021-26) ===")
        res = {k: bets(v, when) for k, v in d.items()}
        for k, b in res.items():
            print(f"  {k:42s} {summary(b)}")
        a = res[a_key]
        for k, b in res.items():
            if k == a_key:
                continue
            added, dropped = b[~b.gameId.isin(a.gameId)], a[~a.gameId.isin(b.gameId)]
            u, lo, hi = boot(a, b, "prof")
            su, slo, shi = boot(a.assign(prof=a.prof.where(a.slam1u, 0.0)), b.assign(prof=b.prof.where(b.slam1u, 0.0)), "prof")
            print(f"  {k[:1]} vs A: adds {len(added)} bets ({(added.res > 0).sum()}-{(added.res < 0).sum()}, {added.prof.sum():+.1f}u), "
                  f"drops {len(dropped)} ({(dropped.res > 0).sum()}-{(dropped.res < 0).sum()}, {dropped.prof.sum():+.1f}u) | "
                  f"units {u:+.1f} (90%: {lo:+.1f}..{hi:+.1f}) | SLAM+1U {su:+.1f} ({slo:+.1f}..{shi:+.1f})")
        print("  by season (close bets / ROI): " if when == "close" else "", end="")
        if when == "close":
            for k, b in res.items():
                print(f"\n    {k[:1]}: " + "  ".join(f"{s}-{str(s + 1)[2:]} {len(x)} {x.prof.mean():+.1%}" for s, x in b.groupby("season")), end="")
            print()


if __name__ == "__main__":
    main()
