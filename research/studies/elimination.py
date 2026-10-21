"""Late-season motivation: do teams already eliminated from the playoffs (or nearly out, or already clinched) score /
allow more or fewer goals than the model projects? 2021-22 to 2025-26.

Status of each team before each game = standings the day before (data/standings_hist.csv, research/lib/standings_hist.py):
  out    = can't reach the playoffs on points: 8+ conference teams and 3+ division teams already have more points than
           its maximum (or the NHL's 'e' flag, 2024-25 on). Matches the official flag 344 of 363 team-days; the 19 misses
           are tiebreaker cases tagged 1-2 days late.
  long   = not out, 8+ points behind the conference's 8th team, March on
  in     = clinched (NHL flag x/y/z/p 2024-25 on, else at most 7 conference teams can still reach its points)
  race   = everyone else, March on

(1) goals scored / allowed vs projection by status, every season.
(2) game total vs projection: neither / one / both teams out.
(3) Walk-forward adjustment: each season's factors for 'out' teams (and 'long') come only from EARLIER seasons
    (actual / projected, shrunk halfway to 1), on the team's own goals and the goals it allows. Judged by judge.scorecard.
(4) SLAM / 1U at the closing line in games with an eliminated team.

  python3 research/studies/elimination.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

from judge import dev, header, row, scorecard  # first: puts src/ on the path
import numpy as np
import pandas as pd

import dashboard
import history as h
import paths
import split_model as sm

STATUSES = ["out", "long", "in", "race"]


def statuses():
    """{(yyyymmdd of the game, team): status}, from the standings the day before."""
    d = pd.read_csv(paths.data("standings_hist.csv"))
    d["maxp"] = d.pts + 2 * (82 - d.gp)
    out = {}
    for day, x in d.groupby("date"):
        game_day = int((pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y%m%d"))
        official = (x.clinch != "").any()
        eighth = x.groupby("conf").pts.apply(lambda p: p.nlargest(8).min())
        for r in x.itertuples():
            c = x[x.conf == r.conf]
            above = (c.pts > r.maxp).sum() >= 8 and (c[c["div"] == r.div].pts > r.maxp).sum() >= 3
            if above or r.clinch == "e":
                s = "out"
            elif (r.clinch in ("x", "y", "z", "p")) if official else ((c.team != r.team) & (c.maxp >= r.pts)).sum() <= 7:
                s = "in"
            elif game_day % 10000 < 301:
                s = None
            elif eighth[r.conf] - r.pts >= 8:
                s = "long"
            else:
                s = "race"
            if s:
                out[(game_day, r.team)] = s
    return out


def tagged(p, st):
    p = p.copy()
    p["st_h"] = [st.get((d, t)) for d, t in zip(p.gameDate, p.home)]
    p["st_a"] = [st.get((d, t)) for d, t in zip(p.gameDate, p.away)]
    return p


def sides(p):
    """One row per team-game: status, goals for / against and the model's projections for both."""
    a = p.assign(st=p.st_h, gf=p.hg, ga=p.ag, lf=p.lam_h, la=p.lam_a)
    b = p.assign(st=p.st_a, gf=p.ag, ga=p.hg, lf=p.lam_a, la=p.lam_h)
    return pd.concat([a, b])[["season", "gameDate", "st", "gf", "ga", "lf", "la"]].dropna(subset=["st"])


def adjusted(p, groups):
    """Walk-forward: scale each team's goals for / against by factors from earlier seasons for its status."""
    s = sides(p)
    q = []
    for season, x in p.groupby("season"):
        prev = s[s.season < season]
        f = {}
        for g in groups:
            y = prev[prev.st == g]
            f[g] = (1 + 0.5 * (y.gf.sum() / y.lf.sum() - 1), 1 + 0.5 * (y.ga.sum() / y.la.sum() - 1)) if len(y) else (1, 1)
        off = lambda col: np.array([f.get(v, (1, 1))[0] for v in x[col]])
        dfn = lambda col: np.array([f.get(v, (1, 1))[1] for v in x[col]])
        lh = x.lam_h * off("st_h") * dfn("st_a")
        la = x.lam_a * off("st_a") * dfn("st_h")
        q.append(x.assign(lam_h=lh, lam_a=la, proj=lh + la))
    return pd.concat(q), f


def out_dev(p):
    """Team-goal deviance on games with an eliminated team only (where the adjustment acts), both halves."""
    x = p[(p.st_h == "out") | (p.st_a == "out")]
    cells = []
    for lo, hi in ((2021, 2022), (2023, 2025)):
        y = x[x.season.between(lo, hi)]
        cells.append(np.concatenate([dev(y.hg, y.lam_h), dev(y.ag, y.lam_a)]).mean())
    return f"{cells[0]:.4f} / {cells[1]:.4f}"


def main():
    g = sm.load_split()
    p = sm.walk_split(g, known_starters=False, record_detail=True).merge(g[["gameId", "hg", "ag"]], on="gameId")
    p = tagged(p, statuses())
    s = sides(p[p.season.between(2021, 2025)])

    print("(1) goals vs projection per team-game, by status (scored = own goals - projected; allowed = goals against - projected)")
    print(f"{'status':6s} {'games':>6s} {'scored':>8s} {'±2SE':>6s} {'allowed':>8s} {'±2SE':>6s}   by season scored / allowed")
    for st in STATUSES:
        x = s[s.st == st]
        sc, al = x.gf - x.lf, x.ga - x.la
        per = "  ".join(f"{yr % 100}: {(y.gf - y.lf).mean():+.2f}/{(y.ga - y.la).mean():+.2f} ({len(y)})"
                        for yr, y in x.groupby("season"))
        print(f"{st:6s} {len(x):6d} {sc.mean():+8.3f} {2 * sc.std() / np.sqrt(len(x)):6.3f} {al.mean():+8.3f} "
              f"{2 * al.std() / np.sqrt(len(x)):6.3f}   {per}")

    late = p[p.season.between(2021, 2025) & p.st_h.notna() & p.st_a.notna()]
    n_out = (late.st_h == "out").astype(int) + (late.st_a == "out").astype(int)
    print("\n(2) game total - projection, March on")
    for k, name in ((0, "neither out"), (1, "one team out"), (2, "both out")):
        x = late[n_out == k]
        dv = x.total - x.proj
        per = "  ".join(f"{yr % 100}: {(y.total - y.proj).mean():+.2f} ({len(y)})" for yr, y in x.groupby("season"))
        print(f"{name:13s} {len(x):5d} games {dv.mean():+.3f} ±{2 * dv.std() / np.sqrt(len(x)):.3f}   {per}")

    print("\n(3) walk-forward adjustment (factors from earlier seasons only)")
    print(header(34) + "   dev out-games 21-23 / 23-26")
    base = scorecard(p.drop(columns=["hg", "ag"]), g)
    print(row("current", base, 34) + "   " + out_dev(p))
    for name, groups in (("+ out teams", ["out"]), ("+ out and long-shot teams", ["out", "long"]),
                         ("+ all four statuses", STATUSES)):
        q, f = adjusted(p, groups)
        print(row(name, scorecard(q.drop(columns=["hg", "ag"]), g), 34, base) + "   " + out_dev(q))
        print("    factors 2026-27 would use (scored / allowed): " +
              "  ".join(f"{k} {v[0] - 1:+.1%}/{v[1] - 1:+.1%}" for k, v in f.items()))

    print("\n(4) SLAM / 1U at the closing line, March on")
    d = h.flagged(p).merge(h.lines(), on=["gameDate", "home", "away"])
    d = d[d.season.between(2021, 2025) & d.both & d.st_h.notna() & d.st_a.notna()]
    b = h.bet_results(d, "close")
    b = b[np.isin([dashboard.call(r, True) for r in b.itertuples()], ["SLAM", "1U"])]
    k = (b.st_h == "out").astype(int) + (b.st_a == "out").astype(int)
    for mask, name in ((k == 0, "no team out"), (k >= 1, "a team out")):
        x = b[mask]
        print(f"{name:12s} {len(x):4d} bets  {(x.res > 0).sum()}-{(x.res < 0).sum()}-{(x.res == 0).sum()}  "
              f"{x.prof.sum():+.1f}u  {x.prof.mean() if len(x) else 0:+.1%}")


if __name__ == "__main__":
    main()
