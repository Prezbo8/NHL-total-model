"""Team speed matchups (Nov 9 2026): do fast-vs-fast, slow-vs-slow etc. games go over more than the model expects?

Each season, teams are split into thirds by the speed rating the model uses (speed.z_prev: LAST season's 20+ mph bursts
per game, z-scored): fast / mid / slow. Every game falls in one of six matchups (fast-fast, fast-mid, fast-slow,
mid-mid, mid-slow, slow-slow). For each: games, actual goals, actual minus the model's projection (live model, which
already has the straight-line speed terms SPEED_OWN / SPEED_OPP) and minus a projection with speed switched off, 7+
rate, overs at the closing line on 6 / 6.5 (all games, and the model's flagged games). Speed data starts 2021-22, so
ratings exist from 2022-23: halves 2022-24 and 2024-26, plus 2026-27 so far. A matchup effect is only real if it
shows up the same way in both halves.

  python3 research/studies/speed_matchups.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers

import numpy as np
import pandas as pd

import history as h
import speed
import split_model as sm

HALVES = (("2022-24", (2022, 2023)), ("2024-26", (2024, 2025)), ("2026-27 so far", (2026, 2026)))
ORDER = ["fast-fast", "fast-mid", "fast-slow", "mid-mid", "mid-slow", "slow-slow"]
RANK = {"fast": 0, "mid": 1, "slow": 2}


def thirds(z):
    """{(season, team): 'fast' / 'mid' / 'slow'}: thirds of that season's speed ratings."""
    s = pd.Series(z)
    out = {}
    for season, v in s.groupby(level=0):
        t = pd.qcut(v.rank(method="first"), 3, labels=["slow", "mid", "fast"])
        out.update({k: str(x) for k, x in t.items()})
    return out


def overs(b):
    """(wins, losses, pushes, ROI %) of over bets at the closing line, lines 6 / 6.5 only."""
    r = h.bet_results(b.assign(both=True), "close") if len(b) else b
    if not len(r):
        return 0, 0, 0, float("nan")
    return int((r.res > 0).sum()), int((r.res < 0).sum()), int((r.res == 0).sum()), r.prof.mean() * 100


def main():
    games = sm.load_split()
    live = sm.walk_split(games, known_starters=False)
    nospd = sm.walk_split(games, known_starters=False, use_speed=False)[["gameId", "proj"]].rename(columns={"proj": "proj_nospd"})
    tier = thirds(speed.z_prev(games))
    d = h.flagged(live).merge(nospd, on="gameId")  # flag needs last season's projections: before dropping any games
    d["th"], d["ta"] = [d.apply(lambda r, c=c: tier.get((r.season, r[c])), axis=1) for c in ("home", "away")]
    d = d.dropna(subset=["th", "ta"])
    d["match"] = [f"{a}-{b}" if RANK[a] <= RANK[b] else f"{b}-{a}" for a, b in zip(d.th, d.ta)]
    d = d.merge(h.lines(), on=["gameDate", "home", "away"], how="left")
    print(f"{len(d)} games with both teams' speed known, seasons {d.season.min()}-{d.season.max()}")
    print("resid = actual goals - projection (± 1 standard error); 'no-spd' = same with the speed terms switched off\n")
    hdr = (f"{'matchup':10s} {'games':>6s} {'actual':>7s} {'proj':>6s} {'resid':>13s} {'resid no-spd':>13s} {'7+':>6s}"
           f" {'overs 6/6.5 all (W-L-P ROI)':>30s} {'flagged overs (W-L-P ROI)':>28s}")
    for label, (a, b) in HALVES:
        x = d[d.season.between(a, b)]
        print(f"=== {label} ({len(x)} games, 7+ rate {(x.total >= 7).mean():.1%}) ===")
        print(hdr)
        for mt in ORDER + ["ALL"]:
            g = x if mt == "ALL" else x[x.match == mt]
            if not len(g):
                continue
            r, r0 = g.total - g.proj, g.total - g.proj_nospd
            se = r.std() / np.sqrt(len(g))
            w, l_, p, roi = overs(g)
            fw, fl, fp, froi = overs(g[g.both.fillna(False).astype(bool)])
            print(f"{mt:10s} {len(g):6d} {g.total.mean():7.2f} {g.proj.mean():6.2f} {r.mean():+6.2f} ±{se:4.2f}"
                  f" {r0.mean():+6.2f} ±{se:4.2f} {(g.total >= 7).mean():6.1%}"
                  f" {f'{w}-{l_}-{p} {roi:+.1f}%':>30s} {f'{fw}-{fl}-{fp} {froi:+.1f}%':>28s}")
        print()


if __name__ == "__main__":
    main()
