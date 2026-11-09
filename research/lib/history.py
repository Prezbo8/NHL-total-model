"""Test the frozen OVER-flag rule on every season with odds (2008-09 to 2025-26).

Rule (unchanged from the daily job): OVER only, line 6 or 6.5, both teams' projected
goals >= the previous season's 60th percentile of team projections.

  python3 research/lib/history.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))  # model code lives in src/
import numpy as np
import pandas as pd

import grade
import odds
import sbr
import model as m
import split_model as sm


def flagged(proj):
    """Per season, mark games where both teams clear last season's cutoff."""
    out = []
    for s, x in proj.groupby("season"):
        prev = proj[proj.season == s - 1]
        if prev.empty:
            continue
        out.append(x.assign(both=m.both_high(x.lam_h, x.lam_a, m.flag_cutoff(prev))))  # the live rule (model.py)
    return pd.concat(out)


def _sane(d, pre):
    """True per row when that row's open / close line is one someone could have bet before the game (paper.sane: both
    prices -100 or longer, a normal margin, fair over chance 38-62%); rows without that line count as fine."""
    import paper
    t, o, u = d[f"{pre}_total"], d[f"{pre}_over"], d[f"{pre}_under"]
    return pd.Series([pd.isna(a) or paper.sane({"total": a, "over": b, "under": c}) for a, b, c in zip(t, o, u)], index=d.index)


def bad_lines():
    """The open / close lines lines() drops: [(gameDate, away, home, 'open' / 'close', total, over, under)]."""
    raw = lines(clean=False)
    return [(r.gameDate, r.away, r.home, pre, getattr(r, f"{pre}_total"), getattr(r, f"{pre}_over"), getattr(r, f"{pre}_under"))
            for pre in ("open", "close") for r in raw[~_sane(raw, pre)].itertuples()]


def lines(clean=True):
    """One row per game: open/close total + over/under prices. SBR through 2021-22, Action Network after.
    clean (default): a line nobody could have bet before the game (an in-game line kept by the feed, a broken consensus
    pair or a typo; paper.sane) is dropped (set to empty), so no bet is graded at it (Nov 2026 audit: e.g. 2024-11-15
    DET@ANA 6.5, over +350)."""
    s = pd.read_csv(sbr.SBR)
    s = s[s.gameDate < 20220801]
    s["final"] = s.away_final + s.home_final
    s = s[["gameDate", "home", "away", "final", "open_total", "open_over", "open_under",
           "close_total", "close_over", "close_under"]]
    parts = []
    for path, pre in ((odds.ODDS_OPEN, "open"), (odds.ODDS, "close")):
        o = pd.read_csv(path).dropna(subset=["total", "over", "under"])
        o["home"], o["away"] = o.home.replace(grade.ABBR), o.away.replace(grade.ABBR)
        o["gameDate"] = o.date.str.replace("-", "").astype(int)
        for c in ("home", "away"):
            o.loc[(o[c] == "UTA") & (o.gameDate < 20240801), c] = "ARI"
        o = o[o.gameDate >= 20220801].drop_duplicates(["gameDate", "home", "away"])
        parts.append(o[["gameDate", "home", "away", "total", "over", "under"]]
                     .rename(columns={"total": f"{pre}_total", "over": f"{pre}_over", "under": f"{pre}_under"}))
    a = parts[0].merge(parts[1], on=["gameDate", "home", "away"], how="outer")
    out = pd.concat([s, a], ignore_index=True)
    if clean:
        for pre in ("open", "close"):
            out.loc[~_sane(out, pre), [f"{pre}_total", f"{pre}_over", f"{pre}_under"]] = np.nan
    return out


def bet_results(d, when):
    t, o = d[f"{when}_total"], d[f"{when}_over"]
    ok = d.both & t.isin(m.FLAG_LINES) & o.notna() & (o.abs() >= 100)
    b = d[ok]
    total = b.total  # actual goals, shootout winner counted
    res = np.sign(total - b[f"{when}_total"])
    prof = np.where(res == 0, 0.0, np.where(res > 0, grade.payout(b[f"{when}_over"]), -1.0))
    return b.assign(res=res, prof=prof)


def table(proj, label):
    d = flagged(proj).merge(lines(), on=["gameDate", "home", "away"])
    print(f"\n=== {label} ===")
    print(f"{'season':8s} {'OPEN: bets  win%   ROI':>26s}   {'CLOSE: bets  win%   ROI':>27s}")
    pooled = {"open": [], "close": []}
    for s in sorted(d.season.unique()):
        row = f"{s}-{str(s + 1)[2:]}  "
        for when in ("open", "close"):
            b = bet_results(d[d.season == s], when)
            pooled[when].append(b)
            dec = b[b.res != 0]
            row += (f"   {len(b):5d}  {(dec.res > 0).mean():5.1%}  {b.prof.mean():+6.1%}   " if len(b) else
                    f"   {0:5d}      -       -   ")
        print(row)
    for name, seasons in (("2008-2021 (never tested before)", range(2008, 2022)),
                          ("2022-2025 (earlier test)", range(2022, 2026)), ("ALL", range(2008, 2026))):
        row = f"{name:32s}"
        for when in ("open", "close"):
            b = pd.concat(pooled[when])
            b = b[b.season.isin(list(seasons))]
            dec = b[b.res != 0]
            pos = sum(1 for s in seasons if len(b[b.season == s]) and b[b.season == s].prof.mean() > 0)
            n_s = sum(1 for s in seasons if len(b[b.season == s]))
            row += f"  {when}: {len(b):4d} bets, win {(dec.res > 0).mean():5.1%}, ROI {b.prof.mean():+5.1%}, profitable {pos}/{n_s} seasons |"
        print(row)


def main():
    games = sm.load_split()
    table(sm.walk_split(games, known_starters=False), "FROZEN RULE (team-based ratings, as running daily)")
    table(sm.walk_split(games, known_starters=False, roster_w=0.5), "SAME RULE + player-based starting ratings (50% roster)")


if __name__ == "__main__":
    main()
